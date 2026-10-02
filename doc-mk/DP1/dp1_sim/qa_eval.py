"""DP1 QA evaluation following doc-mk/Evaluation/qa-evaluation-criteria.md.

Candidates: Baseline-static (Common Reference Baseline, As-Is proxy), C1, C2.
Evidence: all numbers are simulation outputs driven by config parameters -> [B+C], never [A].

    python qa_eval.py            # common benchmark + DP1 stress benchmark, 5 seeds, load sweep
"""
from __future__ import annotations

import argparse
import csv
import json
import math
import statistics
from pathlib import Path

from model import DATA_PRIORS, load_system
from scenarios import common_benchmark, scenarios
from simulator import run_sim

CANDS = ("Baseline-static", "C1-resource-driven", "C2-behavior-driven")
SEEDS = (11, 23, 37, 53, 71)  # runs >= 5
LOADS = (0.5, 1.0, 1.5, 2.0)
T95 = 2.776  # t(0.975, df=4)


def stars_q1(ratio):
    return "★★★" if ratio >= 1.10 else ("★★" if ratio >= 0.90 else "★")


def stars_q2(ttft_ms, tpot_ms):
    if ttft_ms <= 2000 and tpot_ms <= 50:
        return "★★★"
    if ttft_ms <= 4000 and tpot_ms <= 100:
        return "★★"
    return "★"


def stars_q3(u):
    return "★★★" if u >= 0.85 else ("★★" if u >= 0.65 else "★")


def mean_ci(xs):
    m = statistics.mean(xs)
    sd = statistics.stdev(xs) if len(xs) > 1 else 0.0
    return m, T95 * sd / math.sqrt(len(xs)), (sd / m if m else 0.0)


def run_set(system, scs):
    rows = []
    for sc in scs:
        for cand in CANDS:
            for load in LOADS:
                for seed in SEEDS:
                    r = run_sim(system, sc, seed, cand, DATA_PRIORS, load)
                    r["goodput_tps"] = r["slo_goodput_tokens"] / sc.horizon_s
                    r["slo_ratio"] = r["slo_goodput_tokens"] / max(1e-9, r["served_tokens"])
                    r["useful_hbm_util"] = r["avg_hbm_util"] * r["slo_ratio"]
                    rows.append(r)
    return rows


def per_scenario(rows):
    """Max SLO goodput over the load sweep (mean of seeds), and metrics at that load."""
    out = {}
    names = sorted({r["scenario"] for r in rows})
    for sn in names:
        out[sn] = {}
        for cand in CANDS:
            best = None
            for load in LOADS:
                rs = [r for r in rows if r["scenario"] == sn and r["candidate"] == cand and r["load_scale"] == load]
                g, ci, cv = mean_ci([r["goodput_tps"] for r in rs])
                if best is None or g > best["max_goodput_tps"]:
                    best = dict(
                        load=load, max_goodput_tps=g, goodput_ci95=ci, goodput_cv=cv,
                        ttft_p99_ms=statistics.mean(r["ttft_p99_ms"] for r in rs),
                        tpot_p99_ms=statistics.mean(r["tpot_p99_ms"] for r in rs),
                        useful_hbm_util=statistics.mean(r["useful_hbm_util"] for r in rs),
                        avg_hbm_util=statistics.mean(r["avg_hbm_util"] for r in rs),
                        pool_util=statistics.mean(r["aggregate_capacity_util"] for r in rs),
                        slo_ratio=statistics.mean(r["slo_ratio"] for r in rs),
                        migration_count=statistics.mean(r["migration_count"] for r in rs),
                        migration_gib=statistics.mean(r["migration_gib"] for r in rs),
                        migration_time_s=statistics.mean(r["migration_time_s"] for r in rs),
                        decision_overhead_ms=statistics.mean(r["decision_overhead_ms"] for r in rs),
                        demotion=statistics.mean(r["demotion_count"] for r in rs),
                        promotion=statistics.mean(r["promotion_count"] for r in rs),
                    )
            out[sn][cand] = best
    return out


def qa_table(ps):
    """Aggregate across scenarios of one benchmark set -> QA1..QA3 per candidate."""
    res = {}
    base = {sn: v["Baseline-static"]["max_goodput_tps"] for sn, v in ps.items()}
    for cand in CANDS:
        valid = {sn: v for sn, v in ps.items() if base[sn] > 0}
        ratios = [v[cand]["max_goodput_tps"] / base[sn] for sn, v in valid.items()]
        gm = math.exp(statistics.mean(math.log(max(1e-9, x)) for x in ratios)) if ratios else float("nan")
        rescued = [sn for sn, v in ps.items() if base[sn] <= 0 and v[cand]["max_goodput_tps"] > 0]
        ttft_w = max(v[cand]["ttft_p99_ms"] for v in ps.values())
        tpot_w = max(v[cand]["tpot_p99_ms"] for v in ps.values())
        ttft_m = statistics.median(v[cand]["ttft_p99_ms"] for v in ps.values())
        tpot_m = statistics.median(v[cand]["tpot_p99_ms"] for v in ps.values())
        util = statistics.mean(v[cand]["useful_hbm_util"] for v in ps.values())
        res[cand] = dict(
            qa1_ratio_geomean=gm, qa1=stars_q1(gm),
            qa1_per_scenario={sn: (v[cand]["max_goodput_tps"] / base[sn] if base[sn] > 0 else None) for sn, v in ps.items()},
            qa1_rescued_scenarios=rescued, qa1_n_valid=len(ratios),
            qa2_ttft_p99_worst_ms=ttft_w, qa2_tpot_p99_worst_ms=tpot_w,
            qa2_ttft_p99_median_ms=ttft_m, qa2_tpot_p99_median_ms=tpot_m,
            qa2=stars_q2(ttft_w, tpot_w),
            qa3_useful_hbm_util=util, qa3=stars_q3(util),
            pool_util=statistics.mean(v[cand]["pool_util"] for v in ps.values()),
            migration_count=statistics.mean(v[cand]["migration_count"] for v in ps.values()),
            migration_gib=statistics.mean(v[cand]["migration_gib"] for v in ps.values()),
            decision_overhead_ms=statistics.mean(v[cand]["decision_overhead_ms"] for v in ps.values()),
        )
    return res


def main():
    ap = argparse.ArgumentParser()
    here = Path(__file__).resolve().parent
    ap.add_argument("--out-dir", type=Path, default=here / "out_qa")
    args = ap.parse_args()
    system = load_system(here / "configs", "b200_8gpu", "llama_3_1_70b")
    args.out_dir.mkdir(parents=True, exist_ok=True)
    result = {}
    for label, scs in (("common_benchmark", common_benchmark()), ("dp1_stress_benchmark", scenarios())):
        rows = run_set(system, scs)
        ps = per_scenario(rows)
        result[label] = dict(per_scenario=ps, qa=qa_table(ps))
        with (args.out_dir / f"{label}_runs.csv").open("w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=[k for k in rows[0] if k != "tier_accesses"], extrasaction="ignore")
            w.writeheader()
            w.writerows(rows)
    (args.out_dir / "qa_result.json").write_text(json.dumps(result, indent=1, sort_keys=True))
    for label, d in result.items():
        print("==", label)
        for cand, q in d["qa"].items():
            print(f"{cand:20s} QA1 {q['qa1']} x{q['qa1_ratio_geomean']:.3f} | QA2 {q['qa2']} TTFT {q['qa2_ttft_p99_worst_ms']:.0f}ms TPOT {q['qa2_tpot_p99_worst_ms']:.0f}ms | QA3 {q['qa3']} {q['qa3_useful_hbm_util']*100:.0f}% | mig {q['migration_count']:.0f}/{q['migration_gib']:.0f}GiB")


if __name__ == "__main__":
    main()
