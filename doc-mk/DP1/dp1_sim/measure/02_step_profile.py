"""Phase 1/6: offline step profile for perf_model calibration (A evidence).

Equivalent to a grid of ``vllm bench latency`` runs but loads the model once.
Each (batch, input_len, output_len) point is written in the same JSON shape as
``vllm bench latency --output-json`` so perf_model.load_latency_runs() reads it.
Also records the KV capacity vLLM actually allocated (measured/<gpu>/vllm_kv_capacity.json).

  GPU_KEY=a100_sxm4_80g TP=4 python measure/02_step_profile.py
  (quick: --quick ; 8B single-GPU fallback: --model meta-llama/Llama-3.1-8B-Instruct --model-key llama_3_1_8b --tp 1)
"""

from __future__ import annotations

import argparse
import json
import os
import random
import time
from pathlib import Path

from vllm import LLM, SamplingParams
from vllm.inputs import TokensPrompt

GRID_BATCH = (1, 4, 16, 64, 128)
GRID_INPUT = (512, 2048, 8192)
GRID_OUTPUT = (1, 129)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--gpu-key", default=os.environ.get("GPU_KEY"))
    ap.add_argument(
        "--model", default=os.environ.get("MODEL", "meta-llama/Llama-3.1-70B-Instruct")
    )
    ap.add_argument("--model-key", default=os.environ.get("MODEL_KEY", "llama_3_1_70b"))
    ap.add_argument("--tp", type=int, default=int(os.environ.get("TP", "4")))
    ap.add_argument("--iters", type=int, default=5)
    ap.add_argument("--warmup", type=int, default=2)
    ap.add_argument("--quick", action="store_true")
    ap.add_argument("--max-num-batched-tokens", type=int, default=8192)
    args = ap.parse_args()
    assert args.gpu_key
    out = Path(__file__).resolve().parent.parent / "measured" / args.gpu_key
    prof = out / f"step_profile_{args.model_key}_tp{args.tp}"
    prof.mkdir(parents=True, exist_ok=True)

    llm = LLM(
        model=args.model,
        tensor_parallel_size=args.tp,
        dtype="bfloat16",
        enable_prefix_caching=False,  # every iteration must recompute prefill
        max_num_batched_tokens=args.max_num_batched_tokens,
        max_num_seqs=256,
        max_model_len=16384,
        gpu_memory_utilization=0.90,
        seed=0,
    )
    cc = llm.llm_engine.vllm_config.cache_config
    kv_tokens = (cc.num_gpu_blocks or 0) * cc.block_size
    (out / "vllm_kv_capacity.json").write_text(
        json.dumps(
            {
                "model": args.model_key,
                "tp": args.tp,
                "kv_cache_tokens": kv_tokens,
                "num_gpu_blocks": cc.num_gpu_blocks,
                "block_size": cc.block_size,
                "gpu_memory_utilization": 0.90,
            },
            indent=2,
        )
    )
    print(f"KV capacity: {kv_tokens:,} tokens")

    rng = random.Random(0)
    batches = (1, 16, 64) if args.quick else GRID_BATCH
    inputs = (2048, 8192) if args.quick else GRID_INPUT
    for b in batches:
        for i in inputs:
            if b * (i + max(GRID_OUTPUT)) > kv_tokens:
                print(f"skip b={b} i={i}: exceeds KV capacity")
                continue
            for o in GRID_OUTPUT:
                sp = SamplingParams(
                    max_tokens=o, min_tokens=o, ignore_eos=True, temperature=0.0
                )
                lat = []
                for it in range(args.warmup + args.iters):
                    prompts = [
                        TokensPrompt(
                            prompt_token_ids=[
                                rng.randint(1000, 30000) for _ in range(i)
                            ]
                        )
                        for _ in range(b)
                    ]
                    t0 = time.perf_counter()
                    llm.generate(prompts, sp, use_tqdm=False)
                    dt = time.perf_counter() - t0
                    if it >= args.warmup:
                        lat.append(dt)
                lat.sort()
                res = {
                    "avg_latency": sum(lat) / len(lat),
                    "latencies": lat,
                    "percentiles": {
                        "50": lat[len(lat) // 2],
                        "90": lat[int(0.9 * (len(lat) - 1))],
                    },
                    "batch_size": b,
                    "input_len": i,
                    "output_len": o,
                    "tp": args.tp,
                }
                (prof / f"b{b}_i{i}_o{o}.json").write_text(json.dumps(res, indent=2))
                print(
                    f"b={b:4d} in={i:5d} out={o:4d}  median {res['percentiles']['50']:.3f}s"
                )


if __name__ == "__main__":
    main()
