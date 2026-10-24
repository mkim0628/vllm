#!/usr/bin/env python3
"""Run the DP3 evaluation grid and write results/data/<SYS>/dp3_results.json.

    python run_eval.py --system SYS-H100 [--system SYS-B200] [--seeds 11 23 37 53 71] [--out ../results/data] [--only CB-1 ST-03]

Procedure (pre-registered in ../simulation-plan.md):
  1. Feasibility control (Baseline only): bisect the largest arrival rate where Baseline meets TTFT P99 <= 2 s and TPOT P99 <= 50 ms
     with no unfinished request (seed 11).  Nominal rate lam0 = 0.7 x that capacity.  Same lam0 for every policy.
  2. For load multipliers {0.5, 0.75, 1.0, 1.25} x lam0 and every seed: run Baseline, C1, C2.
Evidence [B+C]: hardware from DP1/sim/configs, not measurements.
"""
from __future__ import annotations

import argparse
import json
import math
import subprocess
import sys
from multiprocessing import Pool
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import dp3sim as D  # noqa: E402
import dp3_scenarios as SC  # noqa: E402

LOADS = (0.5, 0.75, 1.0, 1.25)
POLICIES = (D.BASELINE, D.C1, D.C2)
NOMINAL_UTIL = 0.7


def feasible(sc, system, rate, seed=11):
    r = D.run(sc, system, D.BASELINE, seed, rate)
    s = D.summarize(r)
    return s["unfinished"] == 0 and s["ttft_p99"] <= D.SLO_TTFT_S and s["tpot_p99"] <= D.SLO_TPOT_S


def calibrate(sc, system):
    lo, hi = 0.02, 60.0
    if not feasible(sc, system, lo):
        return None
    if feasible(sc, system, hi):
        return hi
    for _ in range(14):
        mid = math.sqrt(lo * hi)
        if feasible(sc, system, mid):
            lo = mid
        else:
            hi = mid
    return lo


def job(args):
    sys_id, sid, pol_name, mult, seed, rate = args
    system = D.load_system(sys_id)
    sc = SC.BY_ID[sid]
    pol = {p.name: p for p in POLICIES}[pol_name]
    s = D.summarize(D.run(sc, system, pol, seed, rate * mult))
    return (sid, pol_name, mult, seed, s)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--system", action="append", required=True)
    ap.add_argument("--seeds", type=int, nargs="+", default=[11, 23, 37, 53, 71])
    ap.add_argument("--out", type=Path, default=HERE.parent / "results" / "data")
    ap.add_argument("--only", nargs="*")
    ap.add_argument("--workers", type=int, default=4)
    a = ap.parse_args()
    rev = subprocess.run(["git", "rev-parse", "--short", "HEAD"], capture_output=True, text=True, cwd=HERE).stdout.strip()
    dirty = bool(subprocess.run(["git", "status", "--porcelain", str(HERE.parent)], capture_output=True, text=True, cwd=HERE).stdout.strip())
    scs = [s for s in SC.ALL if not a.only or s.sid in a.only]
    for sys_id in a.system:
        system = D.load_system(sys_id)
        out = {"schema": "dp3_results v1", "system": sys_id, "git_rev": rev + ("+dirty" if dirty else ""), "seeds": a.seeds, "loads": LOADS,
               "policies": {p.name: dict(mode=p.mode, r=p.r, rho=p.rho) for p in POLICIES}, "scenarios": {}}
        tasks = []
        for sc in scs:
            cap = calibrate(sc, system)
            ent = dict(brief=sc.brief, family=sc.family, mismatch=sc.mismatch, ctx_tokens=sc.ctx_tokens,
                       baseline_capacity_rps=cap, lam0=(cap * NOMINAL_UTIL if cap else None), runs=[])
            out["scenarios"][sc.sid] = ent
            rate = ent["lam0"] if cap else 0.2     # infeasible Baseline: run diagnostics at 0.2 rps, flagged infeasible
            ent["rate_used"] = rate
            for pol in POLICIES:
                for m in LOADS:
                    for sd in a.seeds:
                        tasks.append((sys_id, sc.sid, pol.name, m, sd, rate))
        with Pool(a.workers) as pool:
            for sid, pn, m, sd, s in pool.imap_unordered(job, tasks, chunksize=8):
                out["scenarios"][sid]["runs"].append(dict(policy=pn, load=m, seed=sd, **s))
        d = a.out / sys_id
        d.mkdir(parents=True, exist_ok=True)
        (d / "dp3_results.json").write_text(json.dumps(out, indent=1, default=lambda x: None if (isinstance(x, float) and math.isnan(x)) else x))
        print("wrote", d / "dp3_results.json", len(tasks), "runs")


if __name__ == "__main__":
    main()
