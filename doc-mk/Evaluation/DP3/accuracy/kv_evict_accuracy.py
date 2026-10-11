#!/usr/bin/env python
"""KV-cache eviction accuracy experiment (DP3 evidence, measurement only).

Question: how much does SQuAD token-F1 drop vs. the full KV cache when context
tokens are evicted at keep ratio r, under different importance scorers:
  aware  : attention from the ACTUAL question tokens to context tokens
  repA   : generic instruction ("Summarize the key facts in the text.")
  repB   : a different question about the SAME paragraph
  repC   : a question taken from a paragraph NOT in the context
  random : random eviction control
Eviction is global (same kept token set for every layer/head). Always kept:
prompt prefix (system+instruction), first 4 and last 8 context tokens, and all
question/answer tokens. Kept tokens retain their ORIGINAL position ids.

Run:  python kv_evict_accuracy.py --n 150 --model Qwen/Qwen2.5-1.5B-Instruct
Resumable: existing example ids in the raw jsonl are skipped.
"""
import argparse, collections, json, os, random, re, string, time
import torch
import torch.nn.functional as Fnn
from transformers import AutoModelForCausalLM, AutoTokenizer, DynamicCache

HERE = os.path.dirname(os.path.abspath(__file__))
PREFIX = ("<|im_start|>system\nYou are a helpful assistant.<|im_end|>\n<|im_start|>user\n"
          "Read the text and follow the instruction at the end.\n\nText:\n")
TAIL = "\nAnswer with a short phrase copied from the text, no explanation.<|im_end|>\n<|im_start|>assistant\n"
REP_A = "Summarize the key facts in the text."
SINK, RECENT = 4, 8


def q_suffix(q):
    return "\n\nQuestion: " + q + TAIL


def a_suffix():
    return "\n\nInstruction: " + REP_A + TAIL


# ---------------- SQuAD metric ----------------
def norm(s):
    s = s.lower()
    s = "".join(ch for ch in s if ch not in set(string.punctuation))
    s = re.sub(r"\b(a|an|the)\b", " ", s)
    return " ".join(s.split())


def f1_one(pred, gold):
    p, g = norm(pred).split(), norm(gold).split()
    common = collections.Counter(p) & collections.Counter(g)
    ns = sum(common.values())
    if ns == 0:
        return 0.0
    pr, rc = ns / len(p), ns / len(g)
    return 2 * pr * rc / (pr + rc)


def f1_max(pred, golds):
    return max(f1_one(pred, g) for g in golds)


def em_max(pred, golds):
    return float(max(norm(pred) == norm(g) for g in golds))


# ---------------- data ----------------
def build_examples(tok, n, seed, min_tokens=1200):
    from datasets import load_dataset
    ds = load_dataset("rajpurkar/squad", split="validation")
    paras = collections.OrderedDict()
    for r in ds:
        paras.setdefault((r["title"], r["context"]), []).append(r)
    keys = list(paras.keys())
    multi = [k for k in keys if len({r["question"] for r in paras[k]}) >= 2]
    rng = random.Random(seed)
    rng.shuffle(multi)
    exs = []
    for k in multi:
        if len(exs) >= n:
            break
        qs = paras[k]
        main = qs[rng.randrange(len(qs))]
        others = [r for r in qs if r["question"] != main["question"]]
        if not others:
            continue
        repb = rng.choice(others)
        for _ in range(30):  # 5-7 distractors, resample until context is long enough
            dis = rng.sample([x for x in keys if x[0] != k[0]], rng.randint(5, 7))
            allp = [k] + dis
            rng.shuffle(allp)
            ctx = "\n\n".join(p[1] for p in allp)
            if len(tok(ctx, add_special_tokens=False).input_ids) >= min_tokens:
                break
        used_titles = {p[0] for p in allp}
        while True:  # rep-C question: from a paragraph (title) absent from the context
            ck = rng.choice(keys)
            if ck[0] not in used_titles:
                break
        repc = rng.choice(paras[ck])
        exs.append(dict(id=main["id"], title=k[0], context=ctx, n_paras=len(allp),
                        question=main["question"], golds=main["answers"]["text"],
                        repB_q=repb["question"], repC_q=repc["question"]))
    return exs


# ---------------- model helpers ----------------
def cache_kv(cache):
    if hasattr(cache, "layers"):
        return [(l.keys, l.values) for l in cache.layers]
    return [(cache.key_cache[i], cache.value_cache[i]) for i in range(len(cache.key_cache))]


def make_cache(kv, idx=None):
    c = DynamicCache()
    for i, (k, v) in enumerate(kv):
        if idx is not None:
            k, v = k.index_select(2, idx), v.index_select(2, idx)
        c.update(k, v, i)
    return c


@torch.no_grad()
def score_attention(model, kv, L, ctx_lo, ctx_hi, suffix_ids, smooth=5):
    """mean attention (over layers x heads x suffix tokens) onto context positions."""
    cache = make_cache(kv)
    S = suffix_ids.shape[1]
    out = model(input_ids=suffix_ids, past_key_values=cache,
                position_ids=torch.arange(L, L + S)[None],
                attention_mask=torch.ones(1, L + S, dtype=torch.long),
                use_cache=True, output_attentions=True)
    acc = None
    for a in out.attentions:  # [1,H,S,L+S]
        s = a[0, :, :, ctx_lo:ctx_hi].float().mean(dim=(0, 1))
        acc = s if acc is None else acc + s
    sc = acc / len(out.attentions)
    if smooth and smooth > 1:
        sc = Fnn.avg_pool1d(sc[None, None], smooth, 1, smooth // 2, count_include_pad=False)[0, 0]
    return sc


def select_keep(score, n_ctx, r, rng=None):
    """bool mask over context positions; score=None -> random."""
    budget = n_ctx if r >= 1.0 else max(int(round(r * n_ctx)), SINK + RECENT)
    forced = torch.zeros(n_ctx, dtype=torch.bool)
    forced[:SINK] = True
    forced[n_ctx - RECENT:] = True
    keep = forced.clone()
    extra = max(budget - int(forced.sum()), 0)
    if extra > 0:
        if score is None:
            cand = torch.nonzero(~forced).flatten().tolist()
            keep[torch.tensor(rng.sample(cand, min(extra, len(cand))), dtype=torch.long)] = True
        else:
            s = score.clone()
            s[forced] = -1.0
            keep[torch.topk(s, min(extra, int((~forced).sum()))).indices] = True
    return keep


@torch.no_grad()
def decode(model, cache, cache_len, L, suffix_ids, max_new, eos_ids):
    S = suffix_ids.shape[1]
    out = model(input_ids=suffix_ids, past_key_values=cache,
                position_ids=torch.arange(L, L + S)[None],
                attention_mask=torch.ones(1, cache_len + S, dtype=torch.long), use_cache=True)
    gen, cur, pos = [], cache_len + S, L + S
    for _ in range(max_new):
        nxt = int(out.logits[0, -1].argmax())
        if nxt in eos_ids:
            break
        gen.append(nxt)
        out = model(input_ids=torch.tensor([[nxt]]), past_key_values=cache,
                    position_ids=torch.tensor([[pos]]),
                    attention_mask=torch.ones(1, cur + 1, dtype=torch.long), use_cache=True)
        cur += 1
        pos += 1
    return gen


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=150)
    ap.add_argument("--model", default="Qwen/Qwen2.5-1.5B-Instruct")
    ap.add_argument("--ratios", default="0.5,0.3,0.2,0.1")
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--max-new", type=int, default=32)
    ap.add_argument("--smooth", type=int, default=5)
    ap.add_argument("--min-tokens", type=int, default=1200)
    ap.add_argument("--out", default=os.path.join(HERE, "results", "accuracy_raw.jsonl"))
    ap.add_argument("--sanity", type=int, default=8, help="# examples cross-checked against HF generate()")
    ap.add_argument("--threads", type=int, default=4)
    ap.add_argument("--time-budget-min", type=float, default=1e9, help="stop starting new examples after this")
    args = ap.parse_args()
    torch.set_num_threads(args.threads)
    torch.manual_seed(args.seed)
    ratios = [float(x) for x in args.ratios.split(",")]
    tok = AutoTokenizer.from_pretrained(args.model)
    model = AutoModelForCausalLM.from_pretrained(args.model, dtype=torch.float32, attn_implementation="eager")
    model.eval()
    eos_ids = {tok.convert_tokens_to_ids("<|im_end|>"), tok.eos_token_id}
    exs = build_examples(tok, args.n, args.seed, args.min_tokens)
    os.makedirs(os.path.dirname(args.out), exist_ok=True)
    done = set()
    if os.path.exists(args.out):
        done = {json.loads(l)["id"] for l in open(args.out)}
    sanity_path = os.path.join(os.path.dirname(args.out), "sanity_generate_check.jsonl")
    t0 = time.time()
    fout = open(args.out, "a")
    ids_of = lambda s: tok(s, add_special_tokens=False, return_tensors="pt").input_ids
    for ei, ex in enumerate(exs):
        if ex["id"] in done:
            continue
        if (time.time() - t0) / 60 > args.time_budget_min:
            print("time budget reached, stopping", flush=True)
            break
        pre, ctx = ids_of(PREFIX), ids_of(ex["context"])
        n_pre, n_ctx = pre.shape[1], ctx.shape[1]
        L = n_pre + n_ctx
        with torch.no_grad():
            o = model(input_ids=torch.cat([pre, ctx], 1), use_cache=True)
        kv = [(k.clone(), v.clone()) for k, v in cache_kv(o.past_key_values)]
        del o
        q_ids = ids_of(q_suffix(ex["question"]))
        scorers = {"aware": q_ids, "repA": ids_of(a_suffix()),
                   "repB": ids_of(q_suffix(ex["repB_q"])), "repC": ids_of(q_suffix(ex["repC_q"]))}
        scores = {m: score_attention(model, kv, L, n_pre, L, s, args.smooth) for m, s in scorers.items()}
        rec = dict(id=ex["id"], title=ex["title"], question=ex["question"], golds=ex["golds"],
                   repB_q=ex["repB_q"], repC_q=ex["repC_q"], n_ctx_tokens=n_ctx, n_paras=ex["n_paras"], conds=[])
        rng = random.Random(args.seed * 1000003 + ei)

        def run(cond, r, score, plain=False):
            if plain:  # untouched full cache
                idx, keep = None, None
            else:
                keep = select_keep(score, n_ctx, r, rng)
                idx = torch.cat([torch.arange(n_pre), n_pre + torch.nonzero(keep).flatten()])
            cache = make_cache(kv, idx)
            gen = decode(model, cache, L if idx is None else idx.numel(), L, q_ids, args.max_new, eos_ids)
            pred = tok.decode(gen, skip_special_tokens=True).strip().split("\n")[0].strip()
            row = dict(cond=cond, r=r, kept_ctx=n_ctx if keep is None else int(keep.sum()), pred=pred,
                       f1=f1_max(pred, ex["golds"]), em=em_max(pred, ex["golds"]), gen_ids=gen)
            if keep is not None and cond != "random" and r < 1.0:
                ka = select_keep(scores["aware"], n_ctx, r)
                row["overlap_with_aware"] = float((keep & ka).sum() / ka.sum())
            rec["conds"].append(row)
            return gen

        gen_full = run("full", 1.0, None, plain=True)
        gen_r1 = run("aware_r1.0_via_prune_path", 1.0, scores["aware"])  # sanity: keep-all through the prune path
        rec["sanity_r1_exact"] = gen_r1 == gen_full
        if ei < args.sanity:  # cross-check against HF generate() on the plain, un-cached full sequence
            full_ids = torch.cat([pre, ctx, q_ids], 1)
            with torch.no_grad():
                g = model.generate(full_ids, attention_mask=torch.ones_like(full_ids), do_sample=False,
                                   max_new_tokens=args.max_new, eos_token_id=list(eos_ids), pad_token_id=tok.eos_token_id)
            g = [t for t in g[0, full_ids.shape[1]:].tolist() if t not in eos_ids]
            rec["sanity_generate_match"] = g == gen_full
            with open(sanity_path, "a") as f:
                f.write(json.dumps(dict(id=ex["id"], match=g == gen_full, generate=tok.decode(g), ours=tok.decode(gen_full))) + "\n")
        for r in ratios:
            for m in ["aware", "repA", "repB", "repC"]:
                run(m, r, scores[m])
            run("random", r, None)
        fout.write(json.dumps(rec) + "\n")
        fout.flush()
        print(f"[{ei+1}/{len(exs)}] ctx={n_ctx} {(time.time()-t0)/60:.1f} min  r1exact={rec['sanity_r1_exact']} "
              f"full='{rec['conds'][0]['pred']}' f1={rec['conds'][0]['f1']:.2f}", flush=True)


if __name__ == "__main__":
    main()
