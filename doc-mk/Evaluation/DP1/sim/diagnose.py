"""Diagnostics used by the Baseline-regression loop (results/iterations/loop-log.md).

    python diagnose.py cost <scenario> [--system SYS-4]   # per-tier TTFT/TPOT of a representative object
    python diagnose.py run  <scenario> [--system SYS-4] [--seed 11] [--load 1.0]
                                                          # per-candidate tier accesses / migrations / SLO attainment
Scenario is looked up in all three sets.
"""
from __future__ import annotations

import argparse
import statistics
from pathlib import Path

from model import DATA_PRIORS, load_profile
from scenarios import common_benchmark, dynamic_benchmark, generate_trace, scenarios
from simulator import FIRST_RESPONSE_SLO_S, TPOT_SLO_S, run_sim, tpot_s, ttft_s

CANDS = ("Baseline-static", "C1-resource-driven", "C2-behavior-driven")


def find(name):
    for f in (common_benchmark, scenarios, dynamic_benchmark):
        for s in f():
            if s.name == name:
                return s
    raise SystemExit(f"unknown scenario {name}")


def cost(system, sc, seed=11):
    objs = generate_trace(sc, seed)
    print(f"{sc.name}: {len(objs)} objects, ctx {sc.context_tokens}, batch {sc.batch_size}, out {sc.output_tokens}")
    by = {}
    for o in objs:
        by.setdefault(o.data_class, []).append(o)
    for dc, os_ in by.items():
        o = sorted(os_, key=lambda x: x.size_bytes)[len(os_) // 2]
        print(f" {dc:13s} median obj {o.size_bytes / 1024**3:8.1f} GiB")
        for tier in system.memories:
            tp = tpot_s(system, o, tier, "C", 1.0) * 1e3
            tt = ttft_s(system, o, tier, "C", 1.0, 0.0, 0.0) * 1e3
            ok = "ok " if (tt <= FIRST_RESPONSE_SLO_S * 1e3 and tp <= TPOT_SLO_S * 1e3) else "VIOL"
            print(f"    {tier:11s} TTFT {tt:10.1f} ms  TPOT {tp:10.2f} ms  {ok}")


def run(system, sc, seed, load):
    for cand in CANDS:
        r = run_sim(system, sc, seed, cand, DATA_PRIORS, load)
        slo = r["slo_goodput_tokens"] / max(1e-9, r["served_tokens"])
        print(
            f"{cand:20s} SLO {slo:5.3f} TTFT99 {r['ttft_p99_ms']:9.1f} TPOT99 {r['tpot_p99_ms']:8.1f} "
            f"mig {r['migration_count']:4d} ({r['migration_gib']:8.1f} GiB, {r['migration_time_s']:7.1f}s) "
            f"P/D/R {r['promotion_count']}/{r['demotion_count']}/{r['rebalance_count']} "
            f"hbm {r['avg_hbm_util']:.2f} dec {r['decision_overhead_ms']:.1f}ms"
        )
        print("     accesses:", {k: int(v) for k, v in sorted(r["tier_accesses"].items())})


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["cost", "run"])
    ap.add_argument("scenario")
    ap.add_argument("--system", default=None)
    ap.add_argument("--seed", type=int, default=11)
    ap.add_argument("--load", type=float, default=1.0)
    a = ap.parse_args()
    system, sid, _ = load_profile(Path(__file__).resolve().parent / "configs", a.system)
    print("system", sid)
    sc = find(a.scenario)
    cost(system, sc, a.seed) if a.cmd == "cost" else run(system, sc, a.seed, a.load)
