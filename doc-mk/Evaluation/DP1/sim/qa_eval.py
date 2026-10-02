"""DP1 QA evaluation following doc-mk/Evaluation/qa-evaluation-criteria.md.

Candidates: Baseline-static (Common Reference Baseline, As-Is proxy), C1, C2.
Evidence: all numbers are simulation outputs driven by config parameters -> [B+C], never [A].

    python qa_eval.py                       # all three sets on SYS-4 (default), 5 seeds, load sweep
    python qa_eval.py --system SYS-2
    python qa_eval.py --sets common_benchmark dp1_dynamic_benchmark
    python qa_eval.py --out-dir ../results/data/SYS-4 --no-csv
    python qa_eval.py --jobs 4

Benchmark sets
    common_benchmark        cb_*  : qa-evaluation-criteria.md section 8 profile (steady state)
    dp1_stress_benchmark    23 stress scenarios (diagnostic; many infeasible for the baseline)
    dp1_dynamic_benchmark   dyn_* : runtime-dynamics scenarios where the baseline is feasible but its
                            static placement can go stale (scenarios.dynamic_benchmark())

Per-scenario labels (fit)
    infeasible        baseline Max SLO Goodput == 0 (cannot discriminate, excluded from QA tables)
    saturated         feasible, but baseline/C1/C2 are indistinguishable within the 95% CI
                      (goodput, TTFT P99, TPOT P99)  -> parity / no-harm evidence, no gain evidence
    comparison_valid  feasible and at least one candidate differs from the baseline significantly

Per-scenario verdict vs baseline (paired by seed, t(0.975,4)=2.776):
    win / tie / loss on Max SLO Goodput, TTFT P99 and TPOT P99.  A difference smaller than
    MATERIAL_REL (1 %, i.e. an order of magnitude below the smallest QA1 band) is a tie.
    Scenario verdict = goodput verdict, overridden by a latency verdict only when the QA2 star
    class of the candidate differs from the baseline's and the latency difference is significant.
"""
from __future__ import annotations

import argparse
import csv
import json
import math
import os
import statistics
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

from model import DATA_PRIORS, load_profile
from scenarios import common_benchmark, dynamic_benchmark, scenarios
from simulator import run_sim

BASE = "Baseline-static"
CANDS = (BASE, "C1-resource-driven", "C2-behavior-driven")
SEEDS = (11, 23, 37, 53, 71)  # runs >= 5
LOADS = (0.5, 1.0, 1.5, 2.0)
T95 = 2.776  # t(0.975, df=4)
MATERIAL_REL = 0.01  # differences < 1 % of the baseline value are ties (see module doc)

SETS = (
    ("common_benchmark", common_benchmark),
    ("dp1_stress_benchmark", scenarios),
    ("dp1_dynamic_benchmark", dynamic_benchmark),
)
SET_FUNCS = dict(SETS)


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


def nstar(s):
    return s.count("★")


def mean_ci(xs):
    m = statistics.mean(xs)
    sd = statistics.stdev(xs) if len(xs) > 1 else 0.0
    return m, T95 * sd / math.sqrt(len(xs)), (sd / m if m else 0.0)


MODEL_ERROR = 0.0  # reporting-only knob (epsilon sweep); registered value 0.0

# --------------------------------------------------------------------------- running
_SYS_CACHE = {}


def _system(sys_id):
    if sys_id not in _SYS_CACHE:
        here = Path(__file__).resolve().parent
        _SYS_CACHE[sys_id] = load_profile(here / "configs", sys_id)[0]
    return _SYS_CACHE[sys_id]


def _run_one(args):
    sys_id, label, sc_name, cand, load, seed = args
    sc = next(s for s in SET_FUNCS[label]() if s.name == sc_name)
    r = run_sim(_system(sys_id), sc, seed, cand, DATA_PRIORS, load, model_error=MODEL_ERROR)
    r["goodput_tps"] = r["slo_goodput_tokens"] / sc.horizon_s
    r["slo_ratio"] = r["slo_goodput_tokens"] / max(1e-9, r["served_tokens"])
    r["useful_hbm_util_raw"] = r["avg_hbm_util"] * r["slo_ratio"]
    # v3: link time spent migrating is not serving time -> discounted (definition in criteria QA3 note)
    r["useful_hbm_util"] = r["useful_hbm_util_raw"] * (1.0 - r["migration_link_frac"])
    r["set"] = label
    return r


def run_set(sys_id, label, jobs=1):
    scs = SET_FUNCS[label]()
    tasks = [(sys_id, label, sc.name, c, ld, sd) for sc in scs for c in CANDS for ld in LOADS for sd in SEEDS]
    if jobs > 1:
        with ProcessPoolExecutor(max_workers=jobs) as ex:
            return list(ex.map(_run_one, tasks, chunksize=8))
    return [_run_one(t) for t in tasks]


# --------------------------------------------------------------------------- per scenario
METRICS = (
    "goodput_tps", "ttft_p99_ms", "tpot_p99_ms", "useful_hbm_util", "avg_hbm_util",
    "aggregate_capacity_util", "slo_ratio", "migration_count", "migration_gib",
    "migration_time_s", "migration_link_frac", "decision_overhead_ms", "demotion_count", "promotion_count",
    "rebalance_count",
)


def per_scenario(rows):
    """Max SLO goodput over the load sweep (mean of seeds) and every metric at that load.
    Per-seed vectors at the chosen load are kept (`seeds_*`) for paired comparison."""
    idx = {}
    for r in rows:
        idx.setdefault((r["scenario"], r["candidate"], r["load_scale"]), {})[r["seed"]] = r
    out = {}
    for sn in sorted({r["scenario"] for r in rows}):
        out[sn] = {}
        for cand in CANDS:
            best = None
            for load in LOADS:
                rs = [idx[(sn, cand, load)][s] for s in SEEDS]
                g, ci, cv = mean_ci([r["goodput_tps"] for r in rs])
                if best is None or g > best["max_goodput_tps"]:
                    best = dict(
                        load=load, max_goodput_tps=g, goodput_ci95=ci, goodput_cv=cv,
                        ttft_p99_ms=statistics.mean(r["ttft_p99_ms"] for r in rs),
                        tpot_p99_ms=statistics.mean(r["tpot_p99_ms"] for r in rs),
                        ttft_p50_ms=statistics.mean(r["ttft_p50_ms"] for r in rs),
                        ttft_p95_ms=statistics.mean(r["ttft_p95_ms"] for r in rs),
                        tpot_p50_ms=statistics.mean(r["tpot_p50_ms"] for r in rs),
                        tpot_p95_ms=statistics.mean(r["tpot_p95_ms"] for r in rs),
                        useful_hbm_util=statistics.mean(r["useful_hbm_util"] for r in rs),
                        avg_hbm_util=statistics.mean(r["avg_hbm_util"] for r in rs),
                        pool_util=statistics.mean(r["aggregate_capacity_util"] for r in rs),
                        slo_ratio=statistics.mean(r["slo_ratio"] for r in rs),
                        migration_count=statistics.mean(r["migration_count"] for r in rs),
                        migration_gib=statistics.mean(r["migration_gib"] for r in rs),
                        migration_time_s=statistics.mean(r["migration_time_s"] for r in rs),
                        migration_link_frac=statistics.mean(r["migration_link_frac"] for r in rs),
                        decision_overhead_ms=statistics.mean(r["decision_overhead_ms"] for r in rs),
                        demotion=statistics.mean(r["demotion_count"] for r in rs),
                        promotion=statistics.mean(r["promotion_count"] for r in rs),
                        rebalance=statistics.mean(r["rebalance_count"] for r in rs),
                        seeds_goodput=[r["goodput_tps"] for r in rs],
                        seeds_ttft=[r["ttft_p99_ms"] for r in rs],
                        seeds_tpot=[r["tpot_p99_ms"] for r in rs],
                        seeds_useful_util=[r["useful_hbm_util"] for r in rs],
                    )
            out[sn][cand] = best
    return out


def paired(base, cand, higher_is_better):
    """Paired-by-seed difference cand-base. -> (verdict, mean_diff, ci, rel_diff)."""
    d = [c - b for b, c in zip(base, cand)]
    m, ci, _ = mean_ci(d)
    bm = statistics.mean(base)
    rel = m / bm if bm else (0.0 if m == 0 else math.inf)
    if abs(rel) < MATERIAL_REL or abs(m) <= ci:
        v = "tie"
    elif (m > 0) == higher_is_better:
        v = "win"
    else:
        v = "loss"
    return v, m, ci, rel


def compare_scenario(ps_sn):
    """Verdicts of C1/C2 vs the baseline for one scenario."""
    b = ps_sn[BASE]
    out = {}
    for cand in CANDS[1:]:
        c = ps_sn[cand]
        vg, mg, cg, rg = paired(b["seeds_goodput"], c["seeds_goodput"], True)
        vt, mt, ct, rt = paired(b["seeds_ttft"], c["seeds_ttft"], False)
        vp, mp, cp, rp = paired(b["seeds_tpot"], c["seeds_tpot"], False)
        sb = stars_q2(b["ttft_p99_ms"], b["tpot_p99_ms"])
        sc_ = stars_q2(c["ttft_p99_ms"], c["tpot_p99_ms"])
        verdict = vg
        lat = "tie"
        if nstar(sc_) < nstar(sb) and "loss" in (vt, vp):
            lat = "loss"
        elif nstar(sc_) > nstar(sb) and "win" in (vt, vp):
            lat = "win"
        if lat == "loss":
            verdict = "loss"
        elif lat == "win" and vg != "loss":
            verdict = "win"
        out[cand] = dict(
            verdict=verdict, goodput=vg, ttft=vt, tpot=vp, latency_class=lat,
            goodput_ratio=(c["max_goodput_tps"] / b["max_goodput_tps"]) if b["max_goodput_tps"] > 0 else None,
            goodput_diff_ci95=cg, goodput_rel_diff=rg,
            ttft_diff_ms=mt, tpot_diff_ms=mp, qa2_stars_base=sb, qa2_stars_cand=sc_,
        )
    return out


def label_scenarios(ps):
    labels = {}
    for sn, v in ps.items():
        cmp_ = compare_scenario(v) if v[BASE]["max_goodput_tps"] > 0 else {}
        if v[BASE]["max_goodput_tps"] <= 0:
            fit = "infeasible"
        else:
            same = all(
                c["goodput"] == "tie" and c["ttft"] == "tie" and c["tpot"] == "tie" for c in cmp_.values()
            )
            fit = "saturated" if same else "comparison_valid"
        labels[sn] = dict(
            fit=fit,
            baseline_slo_attainment=v[BASE]["slo_ratio"],
            baseline_p99_meets_slo=bool(v[BASE]["ttft_p99_ms"] <= 2000 and v[BASE]["tpot_p99_ms"] <= 50),
            vs_baseline=cmp_,
        )
    return labels


# --------------------------------------------------------------------------- QA tables
def qa_table(ps, names=None):
    """Aggregate QA1..QA3 per candidate over `names` (default: every scenario with baseline goodput > 0
    for QA1; every scenario for the legacy QA2/QA3 aggregates)."""
    res = {}
    names = list(ps) if names is None else list(names)
    sub = {sn: ps[sn] for sn in names}
    base = {sn: v[BASE]["max_goodput_tps"] for sn, v in sub.items()}
    for cand in CANDS:
        valid = {sn: v for sn, v in sub.items() if base[sn] > 0}
        ratios = [v[cand]["max_goodput_tps"] / base[sn] for sn, v in valid.items()]
        gm = math.exp(statistics.mean(math.log(max(1e-9, x)) for x in ratios)) if ratios else float("nan")
        # per-seed geometric mean ratio -> 95% CI over seeds
        seed_gm = []
        for k in range(len(SEEDS)):
            ls = [
                math.log(max(1e-9, v[cand]["seeds_goodput"][k]) / max(1e-9, v[BASE]["seeds_goodput"][k]))
                for v in valid.values()
                if v[BASE]["seeds_goodput"][k] > 0
            ]
            if ls:
                seed_gm.append(math.exp(statistics.mean(ls)))
        gm_ci = T95 * statistics.stdev(seed_gm) / math.sqrt(len(seed_gm)) if len(seed_gm) > 1 else 0.0
        rescued = [sn for sn, v in sub.items() if base[sn] <= 0 and v[cand]["max_goodput_tps"] > 0]
        if sub:
            ttft_w = max(v[cand]["ttft_p99_ms"] for v in sub.values())
            tpot_w = max(v[cand]["tpot_p99_ms"] for v in sub.values())
            ttft_m = statistics.median(v[cand]["ttft_p99_ms"] for v in sub.values())
            tpot_m = statistics.median(v[cand]["tpot_p99_ms"] for v in sub.values())
            util = statistics.mean(v[cand]["useful_hbm_util"] for v in sub.values())
            pool = statistics.mean(v[cand]["pool_util"] for v in sub.values())
            mc = statistics.mean(v[cand]["migration_count"] for v in sub.values())
            mg = statistics.mean(v[cand]["migration_gib"] for v in sub.values())
            do = statistics.mean(v[cand]["decision_overhead_ms"] for v in sub.values())
            lf = statistics.mean(v[cand]["migration_link_frac"] for v in sub.values())
        else:
            lf = float("nan")
            ttft_w = tpot_w = ttft_m = tpot_m = util = pool = mc = mg = do = float("nan")
        res[cand] = dict(
            qa1_ratio_geomean=gm, qa1_ratio_ci95=gm_ci, qa1=stars_q1(gm) if ratios else "n/a",
            qa1_per_scenario={sn: (v[cand]["max_goodput_tps"] / base[sn] if base[sn] > 0 else None) for sn, v in sub.items()},
            qa1_rescued_scenarios=rescued, qa1_n_valid=len(ratios),
            qa1_abs_goodput_mean_tps=statistics.mean(v[cand]["max_goodput_tps"] for v in valid.values()) if valid else float("nan"),
            qa2_ttft_p99_worst_ms=ttft_w, qa2_tpot_p99_worst_ms=tpot_w,
            qa2_ttft_p99_median_ms=ttft_m, qa2_tpot_p99_median_ms=tpot_m,
            qa2=stars_q2(ttft_w, tpot_w) if sub else "n/a",
            qa3_useful_hbm_util=util, qa3=stars_q3(util) if sub else "n/a",
            pool_util=pool, migration_count=mc, migration_gib=mg, decision_overhead_ms=do, migration_link_frac=lf,
            n_scenarios=len(sub),
        )
    # parity-with-baseline flags (used by the stop criterion)
    b = res[BASE]
    for cand in CANDS[1:]:
        c = res[cand]
        c["qa1_ge_baseline"] = bool(c["qa1_n_valid"] and (c["qa1_ratio_geomean"] + c["qa1_ratio_ci95"] >= 1.0))
        c["qa2_ge_baseline"] = bool(sub and nstar(c["qa2"]) >= nstar(b["qa2"]))
        c["qa3_ge_baseline"] = bool(sub and nstar(c["qa3"]) >= nstar(b["qa3"]))
    return res


def tally(labels, cand):
    t = dict(win=[], tie=[], loss=[])
    for sn, lb in labels.items():
        if lb["fit"] == "infeasible":
            continue
        t[lb["vs_baseline"][cand]["verdict"]].append(sn)
    return t


# --------------------------------------------------------------------------- main
def fmt_qa(cand, q):
    return (
        f"{cand:20s} QA1 {q['qa1']} x{q['qa1_ratio_geomean']:.3f} (±{q['qa1_ratio_ci95']:.3f}) | "
        f"QA2 {q['qa2']} TTFT {q['qa2_ttft_p99_worst_ms']:.0f}ms TPOT {q['qa2_tpot_p99_worst_ms']:.0f}ms | "
        f"QA3 {q['qa3']} {q['qa3_useful_hbm_util']*100:.0f}% | mig {q['migration_count']:.0f}/{q['migration_gib']:.0f}GiB"
    )


def evaluate(sys_id, labels_to_run, jobs=1, csv_dir=None):
    result = {}
    all_ps, all_lab = {}, {}
    for label in labels_to_run:
        rows = run_set(sys_id, label, jobs)
        ps = per_scenario(rows)
        lab = label_scenarios(ps)
        feasible = [sn for sn, l in lab.items() if l["fit"] != "infeasible"]
        discr = [sn for sn, l in lab.items() if l["fit"] == "comparison_valid"]
        result[label] = dict(
            per_scenario=ps,
            qa=qa_table(ps),  # legacy: QA2/QA3 over every scenario
            qa_feasible=qa_table(ps, feasible),  # baseline goodput > 0 (valid + saturated)
            qa_discriminating=qa_table(ps, discr),  # comparison_valid only
            fit={sn: l["fit"] for sn, l in lab.items()},
            scenario_labels=lab,
            tally={c: tally(lab, c) for c in CANDS[1:]},
        )
        all_ps.update({f"{label}/{sn}": v for sn, v in ps.items()})
        all_lab.update({f"{label}/{sn}": v for sn, v in lab.items()})
        if csv_dir is not None:
            csv_dir.mkdir(parents=True, exist_ok=True)
            with (csv_dir / f"{label}_runs.csv").open("w", newline="") as f:
                w = csv.DictWriter(f, fieldnames=[k for k in rows[0] if k != "tier_accesses"], extrasaction="ignore")
                w.writeheader()
                w.writerows(rows)
    feas = [k for k, l in all_lab.items() if l["fit"] != "infeasible"]
    disc = [k for k, l in all_lab.items() if l["fit"] == "comparison_valid"]
    result["combined"] = dict(
        scope="all sets; feasible = baseline goodput > 0 (comparison_valid + saturated); discriminating = comparison_valid only",
        n_feasible=len(feas), n_discriminating=len(disc),
        qa_feasible=qa_table(all_ps, feas) if feas else {},
        qa_discriminating=qa_table(all_ps, disc) if disc else {},
        tally={c: tally(all_lab, c) for c in CANDS[1:]},
    )
    result["meta"] = dict(
        system=sys_id, seeds=list(SEEDS), loads=list(LOADS), t95=T95, material_rel=MATERIAL_REL,
        evidence="[B+C] simulation; not [A]",
        sets=list(labels_to_run),
    )
    return result


def print_result(result):
    for label, d in result.items():
        if label in ("meta", "combined"):
            continue
        n = {f: sum(1 for v in d["fit"].values() if v == f) for f in ("comparison_valid", "saturated", "infeasible")}
        print(f"== {label}  scenarios: {n}")
        key = "qa_feasible" if d["qa_feasible"] and d["qa_feasible"][BASE]["n_scenarios"] else "qa"
        print(f"   (QA table over feasible scenarios n={d['qa_feasible'][BASE]['n_scenarios']})" if key == "qa_feasible" else "   (QA table over all scenarios)")
        for cand, q in d[key].items():
            print("  ", fmt_qa(cand, q))
        for c in CANDS[1:]:
            t = d["tally"][c]
            print(f"   {c:20s} win {len(t['win'])} tie {len(t['tie'])} loss {len(t['loss'])}  loss={t['loss']}")
    c = result["combined"]
    print(f"== combined over feasible scenarios (n={c['n_feasible']}, discriminating n={c['n_discriminating']})")
    for cand, q in c["qa_feasible"].items():
        print("  ", fmt_qa(cand, q))
    for cand in CANDS[1:]:
        t = c["tally"][cand]
        print(f"   {cand:20s} win {len(t['win'])} {t['win']}\n{'':25s} loss {len(t['loss'])} {t['loss']}")


def main():
    ap = argparse.ArgumentParser()
    here = Path(__file__).resolve().parent
    ap.add_argument("--system", default=None, help="profile id in configs/systems.json (default: SYS-4)")
    ap.add_argument("--out-dir", type=Path, default=None)
    ap.add_argument("--sets", nargs="*", default=None, choices=[s for s, _ in SETS], help="default: all three sets")
    ap.add_argument("--jobs", type=int, default=min(4, os.cpu_count() or 1))
    ap.add_argument("--no-csv", action="store_true", help="do not write the per-run CSV")
    args = ap.parse_args()
    _, sys_id, _ = load_profile(here / "configs", args.system)
    if args.out_dir is None:
        args.out_dir = here / "out_qa" / sys_id
    print("system:", sys_id)
    args.out_dir.mkdir(parents=True, exist_ok=True)
    labels = args.sets or [s for s, f in SETS if f()]
    result = evaluate(sys_id, labels, args.jobs, None if args.no_csv else args.out_dir)
    (args.out_dir / "qa_result.json").write_text(json.dumps(result, indent=1, sort_keys=True))
    print_result(result)


if __name__ == "__main__":
    main()
