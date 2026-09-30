"""DP1 policy decision overhead on the *serving host CPU* (A evidence for the
Python prototype; a C++/Rust production path would be faster - report both).

Runs C1/C2 inside serving_sim on a DP1 workload and records the wall-clock
time of every MigrationScheduler drain (event -> decision latency, §19.2).

  GPU_KEY=h100_sxm5_80g python measure/04_decision_overhead.py --kind multiturn --rate 1.0
"""

from __future__ import annotations

import argparse
import json
import os
import platform
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from calibrate import resolve_step_model  # noqa: E402
from hw import MEASURED, build_hw  # noqa: E402
from serving_sim import ServingSim  # noqa: E402
from workload import WorkloadSpec, generate  # noqa: E402


def pct(xs, q):
    xs = sorted(xs)
    return xs[min(len(xs) - 1, int(q * len(xs)))] if xs else float("nan")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--gpu-key", default=os.environ.get("GPU_KEY", "h100_sxm5_80g"))
    ap.add_argument("--tp", type=int, default=int(os.environ.get("TP", "4")))
    ap.add_argument("--kind", default="multiturn")
    ap.add_argument("--rate", type=float, default=1.0)
    ap.add_argument("--horizon", type=float, default=300)
    ap.add_argument("--tiers", default="dram")
    args = ap.parse_args()
    hw = build_hw(args.gpu_key, args.tp, tiers=tuple(args.tiers.split(",")))
    sm, _ = resolve_step_model(args.gpu_key, args.tp)
    turns = generate(
        WorkloadSpec(args.kind, rate=args.rate, horizon_s=args.horizon, seed=0)
    )
    out = {
        "host": platform.node(),
        "cpu": platform.processor(),
        "python": platform.python_version(),
        "workload": vars(args),
    }
    for pol in ("B1-lru-offload", "C1-resource-driven", "C2-behavior-driven"):
        sim = ServingSim(hw, sm, pol, turns, decision_cost="wall")
        r = sim.run()
        w = [x * 1e6 for x in sim.drain_walls]
        out[pol] = {
            "drains": len(w),
            "p50_us": pct(w, 0.5),
            "p99_us": pct(w, 0.99),
            "max_us": max(w),
            "total_ms": sum(w) / 1e3,
            "events": r["events"],
            "modeled_total_ms": r["decision_overhead_model_ms"],
        }
        print(pol, json.dumps(out[pol]))
    p = MEASURED / args.gpu_key / "decision_overhead.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(out, indent=2))
    print("->", p)


if __name__ == "__main__":
    main()
