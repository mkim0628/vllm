#!/usr/bin/env python3
"""DP3 accuracy x throughput joint evidence -> results/data/dp3_acc_tput.json.

    PYTHONHASHSEED=0 python accuracy_throughput.py [--workers 4]

NOTE (reproducibility): dp3sim.run() seeds its RNG with hash(sc.sid), and str hash is randomized per process.  Two runs of the same
command therefore differ per pair (measured up to 16% in Max goodput, see results/data/pre_hashseed_random_dp3_acc_tput.json vs
dp3_qa1.json).  This script requires PYTHONHASHSEED to be set and re-runs the Baseline in the same process family so every ratio
is formed inside one hash seed.  dp3sim.py itself is left untouched (reported as a finding).

Question: what is the Max SLO goodput (QA1) at each keep ratio r, and which of those r also satisfy the QA5 F1-drop bound?
Throughput side: same simulator, grid, seeds, SLO and comparison-valid pair set as run_qa1.py (qa1 pair set = dp3_summary valid and
Baseline goodput > 0); only r changes.  r = 0.30 must reproduce dp3_qa1.json (control, checked below).
Accuracy side is NOT simulated: it is read from ../accuracy/results/accuracy_summary.json (measured r in 0.5/0.3/0.2/0.1) and
mapped to C1/C2 exactly like accuracy.py (C2 = aware, C1 = (1-m)*repB + m*repC).  Joint analysis lives in analyze_acc_tput.py.
"""
import argparse
import json
import math
import statistics as st
import sys
from multiprocessing import Pool
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import dp3sim as D  # noqa: E402
import dp3_scenarios as SC  # noqa: E402

DATA = HERE.parent / "results" / "data"
MULTS = (0.5, 0.75, 1.0, 1.25, 1.5, 2.0, 3.0, 4.0, 6.0, 8.0)
EXT = (12.0, 16.0, 24.0, 32.0, 48.0, 64.0)
SEEDS = (11, 23, 37, 53, 71)
RATIOS = (0.1, 0.2, 0.3, 0.5)     # = the keep ratios measured in ../accuracy
RHO = 0.15
MODES = {"C1": "offline", "C2": "online", "Baseline": "full"}


def job(a):
    sysid, sid, mode, r, m, sd, rate = a
    pol = D.Policy(f"{mode}-{r}", mode, r, RHO)
    return a, D.summarize(D.run(SC.BY_ID[sid], D.load_system(sysid), pol, sd, rate * m))["goodput_tps"]


def main():
    import os
    if os.environ.get("PYTHONHASHSEED") is None:
        sys.exit("set PYTHONHASHSEED (e.g. 0): dp3sim seeds its RNG with hash(sid)")
    ap = argparse.ArgumentParser()
    ap.add_argument("--workers", type=int, default=4)
    a = ap.parse_args()
    summ = json.loads((DATA / "dp3_summary.json").read_text())
    q1 = json.loads((DATA / "dp3_qa1.json").read_text())["pairs"]
    valid = [k for k, e in summ["pairs"].items() if e["valid"] and q1[k]["Baseline-As-Is"]["max_goodput"] > 0]
    rate = {}
    for sysid in ("SYS-H100", "SYS-B200"):
        d = json.loads((DATA / sysid / "dp3_results.json").read_text())
        for sid, e in d["scenarios"].items():
            rate[f"{sysid}/{sid}"] = e["rate_used"]
    acc = {}
    def rs(mode):
        return (0.3,) if mode == "full" else RATIOS          # Baseline does not depend on r

    tasks = [(k.split("/")[0], k.split("/")[1], mode, r, m, sd, rate[k])
             for k in valid for mode in MODES.values() for r in rs(mode) for m in MULTS for sd in SEEDS]
    with Pool(a.workers) as pool:
        for t, g in pool.imap_unordered(job, tasks, chunksize=16):
            acc.setdefault((f"{t[0]}/{t[1]}", t[2], t[3], t[4]), []).append(g)
    # same extension rule as run_qa1.py, applied per (pair, mode, r): peak at last grid point -> extend
    ext = [(k, mode, r) for k in valid for mode in MODES.values() for r in rs(mode)
           if max(MULTS, key=lambda m: st.mean(acc[(k, mode, r, m)])) == MULTS[-1]]
    tasks2 = [(k.split("/")[0], k.split("/")[1], mode, r, m, sd, rate[k]) for (k, mode, r) in ext for m in EXT for sd in SEEDS]
    with Pool(a.workers) as pool:
        for t, g in pool.imap_unordered(job, tasks2, chunksize=16):
            acc.setdefault((f"{t[0]}/{t[1]}", t[2], t[3], t[4]), []).append(g)
    out = {"schema": "dp3_acc_tput v1", "rho": RHO, "ratios": RATIOS, "seeds": SEEDS, "valid_pairs": valid, "pairs": {}}
    for k in valid:
        curveb = {m: st.mean(acc[(k, "full", 0.3, m)]) for m in MULTS + EXT if (k, "full", 0.3, m) in acc}
        ent = {"Baseline": max(curveb.values())}
        for c, mode in MODES.items():
            if c == "Baseline":
                continue
            ent[c] = {}
            for r in RATIOS:
                curve = {str(m): st.mean(acc[(k, mode, r, m)]) for m in MULTS + EXT if (k, mode, r, m) in acc}
                ent[c][str(r)] = max(curve.values())
        out["pairs"][k] = ent
    # control: r = 0.30 aggregate must agree with dp3_qa1.json within the hash-seed noise (per pair it cannot be bit-equal, see NOTE)
    gmean = lambda x: math.exp(sum(map(math.log, x)) / len(x))
    ctl = {}
    for c, pol in (("C1", "C1-Offline"), ("C2", "C2-Online")):
        mine = gmean([out["pairs"][k][c]["0.3"] / out["pairs"][k]["Baseline"] for k in valid])
        ref = gmean([q1[k][pol]["max_goodput"] / q1[k]["Baseline-As-Is"]["max_goodput"] for k in valid])
        per = sorted(abs(out["pairs"][k][c]["0.3"] / out["pairs"][k]["Baseline"] / (q1[k][pol]["max_goodput"] / q1[k]["Baseline-As-Is"]["max_goodput"]) - 1) for k in valid)
        ctl[c] = dict(this_run=mine, dp3_qa1=ref, per_pair_ratio_rel_diff_median=per[len(per) // 2], per_pair_ratio_rel_diff_max=per[-1])
    out["control_r0.3_vs_dp3_qa1"] = ctl
    out["pythonhashseed"] = os.environ["PYTHONHASHSEED"]
    (DATA / "dp3_acc_tput.json").write_text(json.dumps(out, indent=1))
    print("wrote", len(tasks) + len(tasks2), "runs; control", json.dumps(ctl))


if __name__ == "__main__":
    main()
