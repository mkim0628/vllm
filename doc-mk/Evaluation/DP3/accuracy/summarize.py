#!/usr/bin/env python
"""Summarise results/accuracy_raw.jsonl -> results/accuracy_summary.json (+ markdown table on stdout).
Paired bootstrap over examples (resample examples, recompute relative drop vs full)."""
import json, os, sys
import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
raw = os.path.join(HERE, "results", "accuracy_raw.jsonl")
rows = [json.loads(l) for l in open(raw)]
N = len(rows)
CONDS = ["aware", "repA", "repB", "repC", "random"]
ratios = sorted({c["r"] for r in rows for c in r["conds"] if c["r"] < 1.0}, reverse=True)
B = 2000
rng = np.random.default_rng(0)


def get(metric, cond, r):
    return np.array([next(c[metric] for c in x["conds"] if c["cond"] == cond and c["r"] == r) for x in rows])


full = {m: get(m, "full", 1.0) for m in ["f1", "em"]}
idx = rng.integers(0, N, size=(B, N))


def drop(a, b):  # relative drop of b vs a, percent
    return 100 * (a - b) / a


out = dict(n_examples=N, bootstrap_resamples=B, mean_ctx_tokens=float(np.mean([x["n_ctx_tokens"] for x in rows])),
           full=dict(f1=float(full["f1"].mean()), em=float(full["em"].mean())),
           sanity_r1_exact=f"{sum(x['sanity_r1_exact'] for x in rows)}/{N}",
           sanity_generate_match=f"{sum(x['sanity_generate_match'] for x in rows if 'sanity_generate_match' in x)}/{sum('sanity_generate_match' in x for x in rows)}",
           by_ratio={})
for r in ratios:
    out["by_ratio"][str(r)] = {}
    for c in CONDS:
        d = {}
        for m in ["f1", "em"]:
            x = get(m, c, r)
            bs = drop(full[m][idx].mean(1), x[idx].mean(1))
            d[m] = dict(mean=float(x.mean()), rel_drop_pct=float(drop(full[m].mean(), x.mean())),
                        ci95=[float(np.percentile(bs, 2.5)), float(np.percentile(bs, 97.5))])
        d["mean_kept_ctx_tokens"] = float(np.mean([next(k["kept_ctx"] for k in y["conds"] if k["cond"] == c and k["r"] == r) for y in rows]))
        if c not in ("random", "aware"):
            d["mean_overlap_with_aware_kept_set"] = float(np.mean([next(k["overlap_with_aware"] for k in y["conds"] if k["cond"] == c and k["r"] == r) for y in rows]))
        out["by_ratio"][str(r)][c] = d
    # paired difference aware vs each rep (F1 points) with CI
    pd = {}
    a = get("f1", "aware", r)
    for c in CONDS[1:]:
        x = get("f1", c, r)
        bs = (a[idx].mean(1) - x[idx].mean(1))
        pd[c] = dict(f1_aware_minus_cond=float(a.mean() - x.mean()), ci95=[float(np.percentile(bs, 2.5)), float(np.percentile(bs, 97.5))])
    out["by_ratio"][str(r)]["paired_aware_minus"] = pd
json.dump(out, open(os.path.join(HERE, "results", "accuracy_summary.json"), "w"), indent=1)

print(f"N={N}  full F1={out['full']['f1']:.3f} EM={out['full']['em']:.3f}  mean ctx tokens={out['mean_ctx_tokens']:.0f}")
print("sanity r=1 exact:", out["sanity_r1_exact"], " vs HF generate:", out["sanity_generate_match"])
print("\n| r | full | " + " | ".join(CONDS) + " |\n|" + "---|" * (len(CONDS) + 2))
for r in ratios:
    cells = []
    for c in CONDS:
        d = out["by_ratio"][str(r)][c]["f1"]
        cells.append(f"{d['mean']:.3f} ({d['rel_drop_pct']:+.1f}% [{d['ci95'][0]:.1f}, {d['ci95'][1]:.1f}])")
    print(f"| {r} | {out['full']['f1']:.3f} | " + " | ".join(cells) + " |")
print("\nEM:")
for r in ratios:
    print(r, {c: round(out["by_ratio"][str(r)][c]["em"]["mean"], 3) for c in CONDS}, "full", round(out["full"]["em"], 3))
print("\npaired aware - cond (F1):")
for r in ratios:
    print(r, {c: f"{v['f1_aware_minus_cond']:+.3f} [{v['ci95'][0]:+.3f},{v['ci95'][1]:+.3f}]" for c, v in out["by_ratio"][str(r)]["paired_aware_minus"].items()})
print("\noverlap with aware kept set:")
for r in ratios:
    print(r, {c: round(out["by_ratio"][str(r)][c].get("mean_overlap_with_aware_kept_set", float('nan')), 2) for c in CONDS[1:4]})
