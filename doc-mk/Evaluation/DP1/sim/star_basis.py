"""Evidence for the DP1 star edges (QA1 0.97/1.30, QA2 0.95/1.25, QA3 saving 0.95/1.25).

What can be measured (not chosen) is recorded here:
  1. NULL NOISE: Baseline-static vs Baseline-static on disjoint seed groups (same 21 comparison-valid (scenario, system)
     pairs, same load sweep, same aggregation as the star metrics). Any "effect" seen is noise. This grounds the lower edge.
  2. EQUIVALENCES: what an edge means in hardware / latency terms for the evaluated systems (GPU-equivalents for QA1,
     GiB of HBM freed for QA3, ms for QA2) computed from the system profiles and Baseline values.

What cannot be measured (the "worth the added hardware + complexity" level of the upper edge) is a policy choice and is
reported as such; see qa-criteria-dp1.md section J.

    python star_basis.py            # ~4 min on 4 cores -> results/data/star_basis.json
"""
from __future__ import annotations

import json
import math
import statistics
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

import qa_eval as Q

HERE = Path(__file__).resolve().parent
DATA = HERE.parent / "results" / "data"
SYSTEMS = ("SYS-H100", "SYS-B200")
NULL_GROUPS = ((101, 113, 127, 139, 149), (163, 173, 181, 191, 199), (211, 223, 227, 229, 233), (239, 241, 251, 257, 263))
METRICS6 = ("ttft_p50_ms", "ttft_p95_ms", "ttft_p99_ms", "tpot_p50_ms", "tpot_p95_ms", "tpot_p99_ms")


def valid_pairs():
    out = []
    for sid in SYSTEMS:
        d = json.load(open(DATA / sid / "qa_result.json"))
        for label in ("common_benchmark", "dp1_stress_benchmark", "dp1_dynamic_benchmark"):
            for sn, fit in d[label]["fit"].items():
                if fit == "comparison_valid":
                    out.append((sid, label, sn))
    return out


def run_group(args):
    sid, label, sn, seeds = args
    rows = [Q._run_one((sid, label, sn, Q.BASE, ld, sd)) for ld in Q.LOADS for sd in seeds]
    Q.SEEDS, Q.CANDS = seeds, (Q.BASE,)
    return (sid, label, sn, seeds), Q.per_scenario(rows)[sn][Q.BASE]


def gm(xs):
    return math.exp(sum(math.log(max(1e-12, x)) for x in xs) / len(xs))


def main():
    pairs = valid_pairs()
    main_base = {}
    for sid, label, sn in pairs:
        d = json.load(open(DATA / sid / "qa_result.json"))
        main_base[(sid, label, sn)] = d[label]["per_scenario"][sn][Q.BASE]
    tasks = [(sid, label, sn, g) for (sid, label, sn) in pairs for g in NULL_GROUPS]
    with ProcessPoolExecutor(max_workers=4) as ex:
        res = dict(ex.map(run_group, tasks))
    groups = {i: {(p[0], p[1], p[2]): res[(p[0], p[1], p[2], g)] for p in pairs} for i, g in enumerate(NULL_GROUPS)}
    groups["main"] = main_base
    names = list(groups)

    def agg(a, b):
        """metrics of group a relative to group b (candidate=a, Baseline=b) over the 21 pairs"""
        q1 = gm([groups[a][p]["max_goodput_tps"] / max(1e-9, groups[b][p]["max_goodput_tps"]) for p in pairs])
        q2 = gm([groups[b][p][m] / max(1e-9, groups[a][p][m]) for p in pairs for m in METRICS6])
        hbm = gm([groups[a][p]["tier_occ_gib"]["hbm"] / max(1e-9, groups[b][p]["tier_occ_gib"]["hbm"]) for p in pairs])
        return dict(qa1_ratio=q1, qa2_improvement=q2, qa3_hbm_ratio=hbm, qa3_saving=1.0 / hbm)

    cmp = {f"{a}_vs_{b}": agg(a, b) for i, a in enumerate(names) for b in names[i + 1:]}
    # both directions so the null is symmetric around 1
    cmp.update({f"{b}_vs_{a}": agg(b, a) for i, a in enumerate(names) for b in names[i + 1:]})
    summ = {}
    for k in ("qa1_ratio", "qa2_improvement", "qa3_saving"):
        v = [c[k] for c in cmp.values()]
        summ[k] = dict(min=min(v), max=max(v), mean=statistics.mean(v), sd=statistics.pstdev(v), n=len(v),
                       p95_abs_dev_from_1=sorted(abs(math.log(x)) for x in v)[int(0.95 * (len(v) - 1))])
        summ[k]["p95_band"] = [math.exp(-summ[k]["p95_abs_dev_from_1"]), math.exp(summ[k]["p95_abs_dev_from_1"])]
    # per-pair noise (Baseline seed-group-to-group goodput CV), for context
    pair_cv = {f"{p[0]}/{p[2]}": statistics.pstdev([groups[g][p]["max_goodput_tps"] for g in names]) / statistics.mean([groups[g][p]["max_goodput_tps"] for g in names]) for p in pairs}
    out = dict(n_pairs=len(pairs), groups={str(i): list(g) for i, g in enumerate(NULL_GROUPS)}, comparisons=cmp, summary=summ,
               pair_goodput_cv_between_groups=pair_cv, note="Baseline-static vs Baseline-static: every deviation from 1.0 is noise")
    (DATA / "star_basis.json").write_text(json.dumps(out, indent=1))
    for k, v in summ.items():
        print(k, {a: (round(b, 4) if isinstance(b, float) else b) for a, b in v.items() if a != "p95_band"}, "95% band", [round(x, 4) for x in v["p95_band"]])


if __name__ == "__main__":
    main()
