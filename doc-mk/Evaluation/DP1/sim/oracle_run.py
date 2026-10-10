"""Run the Oracle-approx reference policy on the comparison-valid pairs (same scenarios, loads, seeds as the candidates).
    python oracle_run.py [--jobs 4]  ->  results/data/oracle/<SYS>/oracle.json  (per_scenario in qa_eval.per_scenario format)"""
import argparse, json
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path
import qa_eval as Q

DATA = Path(__file__).resolve().parent.parent / "results" / "data"
import sys
ORA = "Oracle-lean" if "--lean" in sys.argv else "Oracle-ideal" if "--ideal" in sys.argv else "Oracle-approx"
SYS = ("SYS-H100", "SYS-B200")
LAB = ("common_benchmark", "dp1_stress_benchmark", "dp1_dynamic_benchmark")


def one(a):
    sid, label, sn, ld, sd = a
    return Q._run_one((sid, label, sn, ORA, ld, sd))


def main():
    ap = argparse.ArgumentParser(); ap.add_argument("--jobs", type=int, default=4); ap.add_argument("--only", default=None); ap.add_argument("--ideal", action="store_true"); ap.add_argument("--lean", action="store_true")
    a = ap.parse_args()
    pairs = []
    for s in SYS:
        d = json.load(open(DATA / s / "qa_result.json"))
        for l in LAB:
            pairs += [(s, l, k) for k, f in d[l]["fit"].items() if f == "comparison_valid" and (a.only is None or k == a.only)]
    tasks = [(s, l, k, ld, sd) for s, l, k in pairs for ld in Q.LOADS for sd in Q.SEEDS]
    with ProcessPoolExecutor(max_workers=a.jobs) as ex:
        rows = list(ex.map(one, tasks, chunksize=4))
    Q.CANDS = (ORA,)
    out = {}
    for s, l, k in pairs:
        sub = [r for r in rows if r["scenario"] == k and r["_sys"] == s] if rows and "_sys" in rows[0] else None
    # rows carry no system tag -> regroup by task order
    idx = 0
    by = {}
    for t, r in zip(tasks, rows):
        by.setdefault((t[0], t[1], t[2]), []).append(r)
    for (s, l, k), rs in by.items():
        out.setdefault(s, {}).setdefault(l, {})[k] = Q.per_scenario(rs)[k][ORA]
    for s, v in out.items():
        fn = {"Oracle-ideal": "oracle_ideal.json", "Oracle-lean": "oracle_lean.json"}.get(ORA, "oracle.json")
        (DATA / "oracle" / s).mkdir(parents=True, exist_ok=True)
        json.dump(v, open(DATA / "oracle" / s / fn, "w"))
    print("done", {s: sum(len(x) for x in v.values()) for s, v in out.items()})


if __name__ == "__main__":
    main()
