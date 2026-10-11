#!/usr/bin/env python3
"""DP3 QA1 (Max SLO goodput) -> results/data/dp3_qa1.json.  Registered in ../simulation-plan.md (change log 2026-10-11).

    python run_qa1.py [--workers 4]
Per (system, scenario, policy): goodput at each load multiplier (seed mean), Max over loads.  Rate base = rate_used of dp3_results.json (lam0).
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
EXT = (12.0, 16.0, 24.0, 32.0, 48.0, 64.0)     # second pass for pairs whose peak is at the grid end (SKILL: extend when the peak sits at the grid end)
SEEDS = (11, 23, 37, 53, 71)
POL = {p.name: p for p in (D.BASELINE, D.C1, D.C2)}


def job(a):
    sysid, sid, pn, m, sd, rate = a
    r = D.summarize(D.run(SC.BY_ID[sid], D.load_system(sysid), POL[pn], sd, rate * m))
    return a, r["goodput_tps"]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--workers", type=int, default=4)
    a = ap.parse_args()
    tasks, rates = [], {}
    for sysid in ("SYS-H100", "SYS-B200"):
        d = json.loads((DATA / sysid / "dp3_results.json").read_text())
        for sid, e in d["scenarios"].items():
            rates[(sysid, sid)] = e["rate_used"]
            for pn in POL:
                for m in MULTS:
                    for sd in SEEDS:
                        tasks.append((sysid, sid, pn, m, sd, e["rate_used"]))
    acc = {}
    with Pool(a.workers) as pool:
        for t, g in pool.imap_unordered(job, tasks, chunksize=8):
            acc.setdefault((t[0], t[1], t[2], t[3]), []).append(g)
    # second pass: extend the grid for every pair where some policy still peaks at the last load
    ext_pairs = [(sy, si) for (sy, si) in rates if any(max(MULTS, key=lambda m: st.mean(acc[(sy, si, pn, m)])) == MULTS[-1] for pn in POL)]
    tasks2 = [(sy, si, pn, m, sd, rates[(sy, si)]) for (sy, si) in ext_pairs for pn in POL for m in EXT for sd in SEEDS]
    with Pool(a.workers) as pool:
        for t, g in pool.imap_unordered(job, tasks2, chunksize=8):
            acc.setdefault((t[0], t[1], t[2], t[3]), []).append(g)
    out = {"schema": "dp3_qa1 v1", "mults": MULTS, "ext_mults": EXT, "ext_pairs": [f"{a}/{b}" for a, b in ext_pairs], "seeds": SEEDS, "pairs": {}}
    for (sysid, sid) in rates:
        ent = {}
        for pn in POL:
            ms = [m for m in MULTS + EXT if (sysid, sid, pn, m) in acc]
            curve = {str(m): st.mean(acc[(sysid, sid, pn, m)]) for m in ms}
            ent[pn] = dict(curve=curve, max_goodput=max(curve.values()), argmax=max(curve, key=curve.get))
        out["pairs"][f"{sysid}/{sid}"] = ent
    (DATA / "dp3_qa1.json").write_text(json.dumps(out, indent=1))
    print("wrote", DATA / "dp3_qa1.json", len(tasks) + len(tasks2), "runs;", len(ext_pairs), "pairs extended")


if __name__ == "__main__":
    main()
