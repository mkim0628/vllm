"""Replay a DP1 workload JSONL against a running vLLM server (A evidence).

The same JSONL (workload.py) is fed to serving_sim.py, so real and simulated
runs share workload, per-session think times and token counts.

  * prompt = token ids (history + fresh random ids), exact lengths
  * streaming /v1/completions with return_token_ids -> exact history for
    the next turn, and per-token timestamps (TTFT / TPOT / ITL)
  * usage.prompt_tokens_details.cached_tokens (server flag
    --enable-prompt-tokens-details) -> actual prefix-cache hit per request,
    used by shadow.py to project C1/C2 onto the actual trace

  python measure/dp1_client.py --workload wl.jsonl --out run.jsonl --model <served-name>
"""

from __future__ import annotations

import argparse
import asyncio
import json
import random
import sys
import time
from pathlib import Path

import aiohttp

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from workload import load  # noqa: E402


async def one_turn(
    session: aiohttp.ClientSession,
    url: str,
    model: str,
    prompt_ids: list[int],
    out_tokens: int,
    timeout: float,
):
    body = {
        "model": model,
        "prompt": prompt_ids,
        "max_tokens": out_tokens,
        "min_tokens": out_tokens,
        "ignore_eos": True,
        "temperature": 0.0,
        "stream": True,
        "stream_options": {"include_usage": True},
        "return_token_ids": True,
    }
    t_send = time.perf_counter()
    tok_times, gen_ids, usage, err = [], [], None, None
    try:
        async with session.post(
            url, json=body, timeout=aiohttp.ClientTimeout(total=timeout)
        ) as resp:
            if resp.status != 200:
                return (
                    t_send,
                    [],
                    [],
                    None,
                    f"HTTP {resp.status}: {(await resp.text())[:200]}",
                )
            async for raw in resp.content:
                line = raw.decode().strip()
                if not line.startswith("data:"):
                    continue
                data = line[5:].strip()
                if data == "[DONE]":
                    break
                j = json.loads(data)
                if j.get("usage"):
                    usage = j["usage"]
                for ch in j.get("choices", []):
                    ids = ch.get("token_ids") or []
                    if ids or ch.get("text"):
                        now = time.perf_counter()
                        n = max(1, len(ids))
                        tok_times.extend([now] * n)
                        gen_ids.extend(ids)
    except Exception as e:  # noqa: BLE001
        err = repr(e)
    return t_send, tok_times, gen_ids, usage, err


async def run_session(turns, args, http, t0, rng, results, sem):
    history: list[int] = []
    for tr in turns:
        if tr.turn == 0:
            await asyncio.sleep(max(0.0, t0 + tr.arrival_s - time.perf_counter()))
        else:
            await asyncio.sleep(tr.think_s)
        new_ids = [rng.randint(1000, 30000) for _ in range(tr.new_tokens)]
        prompt = history + new_ids
        if len(prompt) + tr.output_tokens > args.max_model_len:
            results.append(
                {"session": tr.session, "turn": tr.turn, "skipped": "max_model_len"}
            )
            break
        async with sem:
            t_send, tt, gen, usage, err = await one_turn(
                http, args.url, args.model, prompt, tr.output_tokens, args.timeout
            )
        rec = {
            "session": tr.session,
            "turn": tr.turn,
            "behavior": tr.behavior,
            "arrival_s": t_send - t0,
            "prompt_tokens": len(prompt),
            "history_tokens": len(history),
            "output_tokens": len(tt),
            "requested_output_tokens": tr.output_tokens,
            "error": err,
        }
        if tt:
            rec["ttft_s"] = tt[0] - t_send
            rec["finish_s"] = tt[-1] - t0
            rec["tpot_s"] = (tt[-1] - tt[0]) / max(1, len(tt) - 1)
            rec["itl_s"] = [b - a for a, b in zip(tt, tt[1:])]
        if usage:
            det = usage.get("prompt_tokens_details") or {}
            rec["cached_tokens"] = det.get("cached_tokens")
        results.append(rec)
        if err or not gen:
            break
        history = prompt + gen


async def main_async(args):
    turns, spec = load(args.workload)
    by = {}
    for t in turns:
        by.setdefault(t.session, []).append(t)
    rng = random.Random(args.seed)
    results: list[dict] = []
    sem = asyncio.Semaphore(args.max_concurrency)
    conn = aiohttp.TCPConnector(limit=0)
    async with aiohttp.ClientSession(connector=conn) as http:
        t0 = time.perf_counter() + 1.0
        tasks = [
            run_session(
                sorted(v, key=lambda x: x.turn),
                args,
                http,
                t0,
                random.Random(rng.random()),
                results,
                sem,
            )
            for v in by.values()
        ]
        await asyncio.gather(*tasks)
    return results, spec


def summarize(res: list[dict], ttft_slo=2.0, tpot_slo=0.050) -> dict:
    ok = [r for r in res if r.get("ttft_s") is not None and not r.get("error")]
    if not ok:
        return {"requests": 0}
    t0 = min(r["arrival_s"] for r in ok)
    t1 = max(r["finish_s"] for r in ok)
    dur = t1 - t0
    good = sum(
        r["output_tokens"]
        for r in ok
        if r["ttft_s"] <= ttft_slo and r["tpot_s"] <= tpot_slo
    )

    def pct(xs, q):
        xs = sorted(xs)
        return xs[max(0, min(len(xs) - 1, int(round(q * len(xs))) - 1))]

    hits = [r for r in ok if r["turn"] > 0 and r.get("cached_tokens") is not None]
    return {
        "requests": len(ok),
        "errors": sum(1 for r in res if r.get("error")),
        "duration_s": dur,
        "slo_goodput_tok_s": good / dur,
        "raw_throughput_tok_s": sum(r["output_tokens"] for r in ok) / dur,
        "ttft_p50_s": pct([r["ttft_s"] for r in ok], 0.5),
        "ttft_p99_s": pct([r["ttft_s"] for r in ok], 0.99),
        "tpot_p50_s": pct([r["tpot_s"] for r in ok], 0.5),
        "tpot_p99_s": pct([r["tpot_s"] for r in ok], 0.99),
        "slo_attainment": sum(
            1 for r in ok if r["ttft_s"] <= ttft_slo and r["tpot_s"] <= tpot_slo
        )
        / len(ok),
        "prefix_hit_token_frac": (
            sum(r["cached_tokens"] for r in hits)
            / max(1, sum(r["history_tokens"] for r in hits))
        )
        if hits
        else None,
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--workload", type=Path, required=True)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--url", default="http://localhost:8000/v1/completions")
    ap.add_argument("--model", required=True, help="served model name")
    ap.add_argument("--max-model-len", type=int, default=32768)
    ap.add_argument("--max-concurrency", type=int, default=1024)
    ap.add_argument("--timeout", type=float, default=1800.0)
    ap.add_argument("--seed", type=int, default=0)
    args = ap.parse_args()
    res, spec = asyncio.run(main_async(args))
    args.out.parent.mkdir(parents=True, exist_ok=True)
    with args.out.open("w") as f:
        f.write(json.dumps({"_spec": spec, "_workload": str(args.workload)}) + "\n")
        for r in sorted(res, key=lambda r: (r.get("arrival_s", 0), r["session"])):
            f.write(json.dumps(r) + "\n")
    s = summarize(res)
    args.out.with_suffix(".summary.json").write_text(json.dumps(s, indent=2))
    print(json.dumps(s, indent=2))


if __name__ == "__main__":
    main()
