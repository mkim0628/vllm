"""DP4 QA evaluation (Baseline-RDMA vs C1 central serialization vs C2 distributed lock).

    uv run --no-project python qa_eval.py --system SYS-H100 --out-dir ../results/data/SYS-H100 --jobs 4
    uv run --no-project python qa_eval.py --system SYS-B200 --out-dir ../results/data/SYS-B200 --jobs 4
    uv run --no-project python merge_systems.py SYS-H100 SYS-B200

Evidence: every number is a simulation output driven by config parameters -> [B+C], never [A].
Statistics follow DP1/sim/qa_eval.py: paired by seed, t(0.975, df=4)=2.776, MATERIAL_REL=1 %,
per-scenario fit label (infeasible / saturated / comparison_valid), win / tie / loss.

QA1  Max SLO Goodput; stars at 0.90 / 1.10 of T_ref = Baseline-RDMA; aggregate = geometric mean over CB-1..3
QA2  TTFT P99 / TPOT P99 reported separately (and P50 / P95); star = worst case of the common-benchmark rows
QA3  time-average cluster KV residency (P buffer + D HBM + pool), GiB, at the load where the Baseline peaks
     (same offered load for all arms); star by saving multiplier 0.95 / 1.25
Scalability  Scaling Efficiency values only (no stars, proposal)
Tail check (SKILL 10)  pairs where the candidate's P99 is worse than the Baseline's, plus the worst pair
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import os
import statistics
import subprocess
import sys
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

import dp1_bridge
import params as params_mod
from arms import ABLATION_NAMES, BASE, C1, C2
from scenarios import common_benchmark, dp4_benchmark
from simulator import NEVER_MS, run_sim

HERE = Path(__file__).resolve().parent
CANDS = (BASE, C1, C2)
SEEDS = (11, 23, 37, 53, 71)
LOADS = (0.5, 1.0, 1.5, 2.0)
MAX_LOAD = 8.0
MIN_LOAD = 0.0625  # downward extension floor (peak at the lowest grid point, see DESIGN_NOTES 7)
T95 = 2.776
MATERIAL_REL = 0.01
SETS = (("common_benchmark", common_benchmark), ("dp4_benchmark", dp4_benchmark))
SET_FUNCS = dict(SETS)
COMMON_STAR_LOAD_NOTE = "QA3 and the common-load QA2 columns use the offered load at which the Baseline peaks"


# --------------------------------------------------------------------------- stars
def stars_q1(ratio):
    return "★★★" if ratio >= 1.10 else ("★★" if ratio >= 0.90 else "★")


def stars_q2(ttft_ms, tpot_ms):
    if ttft_ms <= 2000 and tpot_ms <= 50:
        return "★★★"
    if ttft_ms <= 4000 and tpot_ms <= 100:
        return "★★"
    return "★"


def stars_q3(saving):
    return "★★★" if saving >= 1.25 else ("★★" if saving >= 0.95 else "★")


def nstar(s):
    return s.count("★")


def mean_ci(xs):
    m = statistics.mean(xs)
    sd = statistics.stdev(xs) if len(xs) > 1 else 0.0
    return m, T95 * sd / math.sqrt(len(xs)), (sd / m if m else 0.0)


def geomean(xs):
    xs = list(xs)
    return math.exp(statistics.mean(math.log(max(1e-12, x)) for x in xs)) if xs else float("nan")


# --------------------------------------------------------------------------- running
def rows_of(label):
    out = []
    for sc in SET_FUNCS[label]():
        for name, kn in sc.rows():
            out.append((name, kn, sc))
    return out


_ROWS = {}


def _row_knobs(label, row):
    if label not in _ROWS:
        _ROWS[label] = {n: kn for n, kn, _ in rows_of(label)}
    return _ROWS[label][row]


_PARAMS = {}


def _params(cfg, overrides):
    key = (cfg, overrides)
    if key not in _PARAMS:
        _PARAMS[key] = params_mod.load_params(cfg, dict(overrides) if overrides else None)
    return _PARAMS[key]


def _run_one(task):
    sys_id, label, row, arm, load, seed, nofail, cfg, overrides = task
    r = run_sim(dp1_bridge.load_dp1_system(sys_id), _params(cfg, overrides), _row_knobs(label, row), arm, seed, load,
                with_fail=not nofail)
    r["set"], r["row"], r["nofail"] = label, row, nofail
    return r


def run_tasks(tasks, jobs):
    if jobs > 1 and len(tasks) > 8:
        with ProcessPoolExecutor(max_workers=jobs) as ex:
            return list(ex.map(_run_one, tasks, chunksize=8))
    return [_run_one(t) for t in tasks]


def next_load(cur):
    return 3.0 if cur < 3.0 else cur + 1.0


def sweep(sys_id, label, jobs=1, arms=CANDS, cfg=None, overrides=None, seeds=SEEDS, loads=LOADS):
    """Load sweep with peak-at-grid-end extension (x3, x4, ... up to x8) shared by all arms of a row. A peak at the lowest
    grid point (x0.5) extends downward (x0.25, x0.125, x0.0625) so that a peak below the grid is not missed either."""
    ov = tuple(sorted(overrides.items())) if overrides else None
    cfg = str(cfg) if cfg else None
    rows = [n for n, _, _ in rows_of(label)]
    runs = []
    todo = {n: list(loads) for n in rows}
    ran = {n: [] for n in rows}
    while todo:
        tasks = [(sys_id, label, n, a, ld, sd, False, cfg, ov) for n, lds in todo.items() for ld in lds for a in arms for sd in seeds]
        res = run_tasks(tasks, jobs)
        runs.extend(res)
        for n, lds in todo.items():
            ran[n].extend(lds)
        idx = {}
        for r in res:
            idx.setdefault((r["row"], r["arm"], r["load_scale"]), []).append(r["goodput_tps"])
        nxt = {}
        for n in todo:
            gp = {}
            for r in runs:
                if r["row"] == n:
                    gp.setdefault((r["arm"], r["load_scale"]), []).append(r["goodput_tps"])
            mx, mn = max(ran[n]), min(ran[n])
            peak_at_end = peak_at_start = False
            anyg = False
            for a in arms:
                means = {ld: statistics.mean(gp[(a, ld)]) for ld in ran[n]}
                best = max(ran[n], key=lambda ld: (means[ld], -ld))
                if means[best] > 0:
                    anyg = True
                    if best == mx:
                        peak_at_end = True
                    if best == mn:
                        peak_at_start = True
            if peak_at_end and anyg and mx < MAX_LOAD:
                nxt[n] = [next_load(mx)]
            elif peak_at_start and anyg and mn > MIN_LOAD:
                nxt[n] = [mn / 2.0]
        todo = nxt
    return runs, ran


# --------------------------------------------------------------------------- per scenario
MEAN_KEYS = (
    "goodput_tps", "ttft_p50_ms", "ttft_p95_ms", "ttft_p99_ms", "tpot_p50_ms", "tpot_p95_ms", "tpot_p99_ms",
    "kv_resident_gib", "link_util_egress", "link_util_ingress", "pool_util", "cpu_core_eq", "offered_rps",
    "n_slo_viol", "n_failed", "n_incomplete", "n_cohort",
)
ARM_STAT_KEYS = ("server_util", "global_lock_util_mean", "global_lock_util_max", "lock_wait_mean_ms", "lock_wait_p99_ms",
                 "lock_mgr_util", "lock_scan_period_us", "stuck_stripes")
SEED_KEYS = ("goodput_tps", "ttft_p99_ms", "tpot_p99_ms", "kv_resident_gib", "n_slo_viol")
KINDS = ("lookup", "publish", "pin", "unpin", "evict", "alloc", "lru")


def summarize(rs):
    """rs: runs of one (row, arm, load), ordered by seed."""
    d = {k: statistics.mean(r[k] for r in rs) for k in MEAN_KEYS}
    g, ci, cv = mean_ci([r["goodput_tps"] for r in rs])
    d.update(goodput_ci95=ci, goodput_cv=cv)
    for k in ARM_STAT_KEYS:
        d[k] = statistics.mean(r["arm_stats"].get(k, 0.0) for r in rs)
    d["resid_gib"] = {c: statistics.mean(r["resid_gib"][c] for r in rs) for c in rs[0]["resid_gib"]}
    d["cp_lat"] = {}
    for kd in KINDS:
        got = [r["cp_lat"][kd] for r in rs if kd in r["cp_lat"]]
        if got:
            d["cp_lat"][kd] = dict(p50_us=statistics.mean(x["p50_us"] for x in got), p99_us=statistics.mean(x["p99_us"] for x in got),
                                  n=statistics.mean(x["n"] for x in got))
    for k in SEED_KEYS:
        d["seeds_" + k] = [r[k] for r in rs]
    d["fail_window_s"] = rs[0]["fail"]["window_s"]
    d["conservation_ok"] = all(r["n_arrived"] == r["n_total_done"] + r["n_total_failed"] + r["n_total_incomplete"] for r in rs)
    return d


def per_scenario(runs, arms=CANDS, seeds=SEEDS):
    idx = {}
    for r in runs:
        if r.get("nofail"):
            continue
        idx.setdefault((r["row"], r["arm"], r["load_scale"]), {})[r["seed"]] = r
    rows = sorted({k[0] for k in idx})
    out = {}
    for sn in rows:
        loads = sorted({k[2] for k in idx if k[0] == sn})
        by = {a: {ld: summarize([idx[(sn, a, ld)][s] for s in seeds]) for ld in loads} for a in arms}
        base_best = max(loads, key=lambda ld: (by[BASE][ld]["goodput_tps"], -ld))
        out[sn] = {"_loads": loads, "_base_peak_load": base_best}
        for a in arms:
            best = max(loads, key=lambda ld: (by[a][ld]["goodput_tps"], -ld))
            e = dict(by[a][best])
            e.update(load=best, max_goodput_tps=e["goodput_tps"],
                     at_base_peak=dict(by[a][base_best], load=base_best),
                     at_load1=dict(by[a][1.0], load=1.0),
                     by_load={str(ld): by[a][ld] for ld in loads})
            out[sn][a] = e
    return out


def paired(base, cand, higher_is_better):
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


def compare_pair(b, c):
    """verdict of candidate entry c vs baseline entry b (each: per_scenario entry)."""
    vg, mg, cg, rg = paired(b["seeds_goodput_tps"], c["seeds_goodput_tps"], True)
    vt, mt, ct, rt = paired(b["seeds_ttft_p99_ms"], c["seeds_ttft_p99_ms"], False)
    vp, mp, cp, rp = paired(b["seeds_tpot_p99_ms"], c["seeds_tpot_p99_ms"], False)
    sb, sc_ = stars_q2(b["ttft_p99_ms"], b["tpot_p99_ms"]), stars_q2(c["ttft_p99_ms"], c["tpot_p99_ms"])
    verdict, lat = vg, "tie"
    if nstar(sc_) < nstar(sb) and "loss" in (vt, vp):
        lat = "loss"
    elif nstar(sc_) > nstar(sb) and "win" in (vt, vp):
        lat = "win"
    if lat == "loss":
        verdict = "loss"
    elif lat == "win" and vg != "loss":
        verdict = "win"
    return dict(verdict=verdict, goodput=vg, ttft=vt, tpot=vp, latency_class=lat,
                goodput_ratio=(c["max_goodput_tps"] / b["max_goodput_tps"]) if b["max_goodput_tps"] > 0 else None,
                goodput_diff_ci95=cg, goodput_rel_diff=rg, ttft_diff_ms=mt, tpot_diff_ms=mp,
                qa2_stars_base=sb, qa2_stars_cand=sc_)


def label_scenarios(ps, cands=CANDS):
    labels = {}
    for sn, v in ps.items():
        feasible = v[BASE]["max_goodput_tps"] > 0
        cmp_ = {c: compare_pair(v[BASE], v[c]) for c in cands[1:]} if feasible else {}
        if not feasible:
            fit = "infeasible"
        else:
            same = all(c["goodput"] == "tie" and c["ttft"] == "tie" and c["tpot"] == "tie" for c in cmp_.values())
            fit = "saturated" if same else "comparison_valid"
        labels[sn] = dict(fit=fit, baseline_slo_attainment=1.0 - v[BASE]["n_slo_viol"] / max(1.0, v[BASE]["n_cohort"]),
                          baseline_p99_meets_slo=bool(v[BASE]["ttft_p99_ms"] <= 2000 and v[BASE]["tpot_p99_ms"] <= 50),
                          vs_baseline=cmp_)
    return labels


# --------------------------------------------------------------------------- QA tables
def tail_check(sub, cand, basis):
    """pairs where the candidate's P99 is worse than the Baseline's (> MATERIAL_REL), and the worst pair."""
    res = {}
    for m in ("ttft", "tpot"):
        worse, worst, worst_sn, n = 0, 1.0, None, 0
        for sn, v in sub.items():
            b = (v[BASE] if basis == "own_peak" else v[BASE]["at_base_peak"])[m + "_p99_ms"]
            c = (v[cand] if basis == "own_peak" else v[cand]["at_base_peak"])[m + "_p99_ms"]
            if b <= 0:
                continue
            n += 1
            ratio = c / b
            if ratio > 1.0 + MATERIAL_REL:
                worse += 1
            if ratio > worst:
                worst, worst_sn = ratio, sn
        res[m] = dict(n_pairs=n, n_worse=worse, worst_ratio=worst, worst_pair=worst_sn)
    return res


def qa_table(ps, names=None, cands=CANDS):
    names = list(ps) if names is None else list(names)
    sub = {sn: ps[sn] for sn in names}
    res = {}
    base = {sn: v[BASE]["max_goodput_tps"] for sn, v in sub.items()}
    for cand in cands:
        valid = {sn: v for sn, v in sub.items() if base[sn] > 0}
        ratios = [v[cand]["max_goodput_tps"] / base[sn] for sn, v in valid.items()]
        gm = geomean(ratios)
        seed_gm = []
        for k in range(len(SEEDS)):
            ls = [math.log(max(1e-9, v[cand]["seeds_goodput_tps"][k]) / max(1e-9, v[BASE]["seeds_goodput_tps"][k]))
                  for v in valid.values() if v[BASE]["seeds_goodput_tps"][k] > 0]
            if ls:
                seed_gm.append(math.exp(statistics.mean(ls)))
        gm_ci = T95 * statistics.stdev(seed_gm) / math.sqrt(len(seed_gm)) if len(seed_gm) > 1 else 0.0
        zero = [sn for sn, v in valid.items() if v[cand]["max_goodput_tps"] <= 0]
        gm_nz = geomean(r_ for r_ in ratios if r_ > 0) if any(r_ > 0 for r_ in ratios) else 0.0
        d = dict(qa1_n_cand_zero=len(zero), qa1_cand_zero_scenarios=zero, qa1_ratio_geomean_excl_zero=gm_nz, qa1_ratio_geomean=gm, qa1_ratio_ci95=gm_ci, qa1=stars_q1(gm) if ratios else "n/a", qa1_n_valid=len(ratios),
                 qa1_per_scenario={sn: (v[cand]["max_goodput_tps"] / base[sn] if base[sn] > 0 else None) for sn, v in sub.items()},
                 qa1_abs_goodput_geomean_tps=geomean(v[cand]["max_goodput_tps"] for v in valid.values()) if valid else float("nan"),
                 qa1_t_ref_geomean_tps=geomean(base[sn] for sn in valid) if valid else float("nan"), n_scenarios=len(sub))
        if sub:
            for basis, get in (("", lambda v: v[cand]), ("_common", lambda v: v[cand]["at_base_peak"]), ("_load1", lambda v: v[cand]["at_load1"])):
                for m in ("ttft", "tpot"):
                    for q in ("p50", "p95", "p99"):
                        d[f"qa2{basis}_{m}_{q}_ms_geomean"] = geomean(min(get(v)[f"{m}_{q}_ms"], NEVER_MS) for v in sub.values())
                    d[f"qa2{basis}_{m}_p99_worst_ms"] = max(get(v)[f"{m}_p99_ms"] for v in sub.values())
                d[f"qa2{basis}"] = stars_q2(d[f"qa2{basis}_ttft_p99_worst_ms"], d[f"qa2{basis}_tpot_p99_worst_ms"])
            gib = {sn: v[cand]["at_base_peak"]["kv_resident_gib"] for sn, v in sub.items()}
            bgib = {sn: v[BASE]["at_base_peak"]["kv_resident_gib"] for sn, v in sub.items()}
            d["qa3_kv_resident_gib_geomean"] = geomean(gib.values())
            d["qa3_ratio_vs_base_geomean"] = geomean(gib[sn] / bgib[sn] for sn in sub if bgib[sn] > 0)
            d["qa3_saving_multiplier"] = 1.0 / d["qa3_ratio_vs_base_geomean"]
            d["qa3"] = stars_q3(d["qa3_saving_multiplier"])
            lg = [v[cand]["at_load1"]["kv_resident_gib"] / v[BASE]["at_load1"]["kv_resident_gib"] for v in sub.values() if v[BASE]["at_load1"]["kv_resident_gib"] > 0]
            d["qa3_load1_ratio_vs_base_geomean"] = geomean(lg)
            d["qa3_load1_saving_multiplier"] = 1.0 / d["qa3_load1_ratio_vs_base_geomean"]
            d["qa3_per_scenario_gib"] = gib
            d["qa3_components_gib_mean"] = {c: statistics.mean(v[cand]["at_base_peak"]["resid_gib"][c] for v in sub.values()) for c in ("p_buffer", "d_hbm", "pool")}
            d["qa3_at_own_peak_gib_geomean"] = geomean(v[cand]["kv_resident_gib"] for v in sub.values())
            for k in ("cpu_core_eq", "link_util_egress", "link_util_ingress", "pool_util", "server_util", "global_lock_util_max", "lock_wait_p99_ms"):
                d["diag_" + k] = statistics.mean(v[cand]["at_base_peak"][k] for v in sub.values())
            if cand != BASE:
                d["tail_check_common_load"] = tail_check(sub, cand, "base_peak")
                d["tail_check_own_peak"] = tail_check(sub, cand, "own_peak")
        res[cand] = d
    b = res[BASE]
    for cand in cands[1:]:
        c = res[cand]
        c["qa1_ge_baseline"] = bool(c["qa1_n_valid"] and c["qa1_ratio_geomean"] + c["qa1_ratio_ci95"] >= 1.0)
        c["qa2_ge_baseline"] = bool(sub and nstar(c["qa2"]) >= nstar(b["qa2"]))
        c["qa3_ge_baseline"] = bool(sub and nstar(c["qa3"]) >= nstar(b["qa3"]))
    return res


def tally(labels, cand):
    t = dict(win=[], tie=[], loss=[])
    for sn, lb in labels.items():
        if lb["fit"] != "infeasible":
            t[lb["vs_baseline"][cand]["verdict"]].append(sn)
    return t


# --------------------------------------------------------------------------- DP4 extras
def scaling(ps, cands=CANDS):
    """Scaling Efficiency = Goodput(N) / ((N/2) * Goodput(2)); node load fixed. Values only, no stars (proposal)."""
    need = ["d4_node_scale_n2", "d4_node_scale_n4", "d4_node_scale_n8", "d4_node_scale_n16"]
    if not all(n in ps for n in need):
        return {}
    out = {}
    for a in cands:
        g2 = ps["d4_node_scale_n2"][a]["max_goodput_tps"]
        out[a] = {str(n): (ps[f"d4_node_scale_n{n}"][a]["max_goodput_tps"] / ((n / 2) * g2) if g2 > 0 else None) for n in (4, 8, 16)}
        out[a]["goodput_tps"] = {str(n): ps[f"d4_node_scale_n{n}"][a]["max_goodput_tps"] for n in (2, 4, 8, 16)}
        out[a]["note"] = "proposal metric, not an official QA; no stars (H11)"
    return out


def c1_vs_c2(ps):
    """Direct C1 vs C2 comparison (qa-criteria-dp4 section 5), at the load where the Baseline peaks."""
    out = {}
    for sn, v in ps.items():
        a, b = v[C1], v[C2]
        ca, cb = a["at_base_peak"], b["at_base_peak"]
        lat = {}
        for kd in ("lookup", "publish", "pin", "unpin"):
            if kd in ca["cp_lat"] and kd in cb["cp_lat"]:
                lat[kd] = dict(p50_ratio_c2_over_c1=cb["cp_lat"][kd]["p50_us"] / max(1e-12, ca["cp_lat"][kd]["p50_us"]),
                               p99_ratio_c2_over_c1=cb["cp_lat"][kd]["p99_us"] / max(1e-12, ca["cp_lat"][kd]["p99_us"]),
                               c1_p50_us=ca["cp_lat"][kd]["p50_us"], c1_p99_us=ca["cp_lat"][kd]["p99_us"],
                               c2_p50_us=cb["cp_lat"][kd]["p50_us"], c2_p99_us=cb["cp_lat"][kd]["p99_us"])
        vg, mg, cg, rg = paired(a["seeds_goodput_tps"], b["seeds_goodput_tps"], True)
        vt, mt, _, _ = paired(a["seeds_ttft_p99_ms"], b["seeds_ttft_p99_ms"], False)
        vp, mp, _, _ = paired(a["seeds_tpot_p99_ms"], b["seeds_tpot_p99_ms"], False)
        out[sn] = dict(
            goodput_ratio_c2_over_c1=b["max_goodput_tps"] / a["max_goodput_tps"] if a["max_goodput_tps"] > 0 else None,
            ttft_p99_ratio=cb["ttft_p99_ms"] / ca["ttft_p99_ms"] if ca["ttft_p99_ms"] > 0 else None,
            tpot_p99_ratio=cb["tpot_p99_ms"] / ca["tpot_p99_ms"] if ca["tpot_p99_ms"] > 0 else None,
            kv_resident_ratio=cb["kv_resident_gib"] / ca["kv_resident_gib"] if ca["kv_resident_gib"] > 0 else None,
            verdict_c2_vs_c1=dict(goodput=vg, ttft=vt, tpot=vp), cp_op_latency=lat,
            saturation_offered_rps=dict(c1=a["offered_rps"], c2=b["offered_rps"]),
            cpu_core_eq=dict(c1=ca["cpu_core_eq"], c2=cb["cpu_core_eq"]),
            occupancy=dict(c1_server_util=ca["server_util"], c2_global_lock_util_mean=cb["global_lock_util_mean"],
                           c2_global_lock_util_max=cb["global_lock_util_max"], c2_lock_mgr_util=cb["lock_mgr_util"],
                           c2_lock_wait_p99_ms=cb["lock_wait_p99_ms"]),
            fail=dict(c1_window_s=ca["fail_window_s"], c2_window_s=cb["fail_window_s"], c1_viol=ca["n_slo_viol"], c2_viol=cb["n_slo_viol"],
                      c1_failed=ca["n_failed"], c2_failed=cb["n_failed"], c1_incomplete=ca["n_incomplete"], c2_incomplete=cb["n_incomplete"]),
        )
    return out


def failure_table(sys_id, label, ps, jobs, cfg=None, overrides=None, cands=CANDS):
    """Counterfactual no-failure runs at the Baseline-peak load -> SLO violations attributable to the failure."""
    ov = tuple(sorted(overrides.items())) if overrides else None
    rows = [n for n, kn, _ in rows_of(label) if kn["fail"]]
    tasks = [(sys_id, label, n, a, ps[n]["_base_peak_load"], sd, True, str(cfg) if cfg else None, ov) for n in rows for a in cands for sd in SEEDS]
    res = run_tasks(tasks, jobs)
    idx = {}
    for r in res:
        idx.setdefault((r["row"], r["arm"]), []).append(r)
    out = {}
    for n in rows:
        out[n] = {}
        for a in cands:
            nf = idx[(n, a)]
            w = ps[n][a]["at_base_peak"]
            out[n][a] = dict(load=ps[n]["_base_peak_load"], window_s=w["fail_window_s"], slo_viol_with_failure=w["n_slo_viol"],
                             slo_viol_no_failure=statistics.mean(r["n_slo_viol"] for r in nf),
                             slo_viol_excess=w["n_slo_viol"] - statistics.mean(r["n_slo_viol"] for r in nf),
                             n_failed=w["n_failed"], n_incomplete_stuck=w["n_incomplete"], n_cohort=w["n_cohort"],
                             stuck_stripes=w["stuck_stripes"], ttft_p99_ms_with=w["ttft_p99_ms"],
                             ttft_p99_ms_no_failure=statistics.mean(r["ttft_p99_ms"] for r in nf))
    return out


def cp_capacity(sys_id, label, jobs, cfg=None, overrides=None, seeds=SEEDS):
    """Control-plane saturation: open-loop requests that only run lookup/publish/pin/unpin (no GPU work).
    Saturation = lowest rate in the geometric sweep where the P99 control-plane chain latency exceeds CP_BLOWUP times the
    P99 at the lowest rate (queueing blow-up; the unloaded latency itself, e.g. S*N*t_probe scan wait, is not saturation)."""
    return cp_capacity_impl(sys_id, label, jobs, cfg, overrides, seeds)


CP_BLOWUP = 10.0
CP_RATES = tuple(100.0 * 2 ** k for k in range(0, 21))  # 100 req/s ... ~105 Mreq/s


def _cp_one(task):
    sys_id, label, row, arm, rate, seed, cfg, ov = task
    kn = _row_knobs(label, row)
    r = run_sim(dp1_bridge.load_dp1_system(sys_id), _params(cfg, ov), kn, arm, seed, 1.0, cp_only=True, with_fail=False,
                abs_rate=rate, n_req=4000)
    return (row, arm, rate, seed, r["cp_chain_p99_us"], r["cp_chain_p50_us"], r["arm_stats"].get("server_util", 0.0))


def cp_capacity_impl(sys_id, label, jobs, cfg, overrides, seeds):
    ov = tuple(sorted(overrides.items())) if overrides else None
    rows = [n for n, kn, _ in rows_of(label) if not kn["fail"] and kn["turns"] == 1]
    tasks = [(sys_id, label, n, a, rt, sd, str(cfg) if cfg else None, ov) for n in rows for a in (C1, C2) for rt in CP_RATES for sd in seeds[:3]]
    if jobs > 1:
        with ProcessPoolExecutor(max_workers=jobs) as ex:
            res = list(ex.map(_cp_one, tasks, chunksize=16))
    else:
        res = [_cp_one(t) for t in tasks]
    agg = {}
    for row, arm, rate, seed, p99, p50, su in res:
        agg.setdefault((row, arm, rate), []).append((p99, p50, su))
    out = {}
    for n in rows:
        out[n] = {}
        for a in (C1, C2):
            sat, curve = None, []
            for rt in CP_RATES:
                v = agg[(n, a, rt)]
                p99 = statistics.mean(x[0] for x in v)
                curve.append(dict(rate=rt, chain_p99_us=p99, chain_p50_us=statistics.mean(x[1] for x in v), server_util=statistics.mean(x[2] for x in v)))
                if sat is None and p99 > CP_BLOWUP * curve[0]["chain_p99_us"]:
                    sat = rt
            out[n][a] = dict(saturation_rps=sat, blowup_factor=CP_BLOWUP, sweep_max_rps=CP_RATES[-1], curve=curve,
                             unloaded_chain_p99_us=curve[0]["chain_p99_us"],
                             unloaded_chain_p50_us=curve[0]["chain_p50_us"])
    return out


# --------------------------------------------------------------------------- evaluate
def git_info():
    def g(*a):
        try:
            return subprocess.run(["git", "-C", str(HERE), *a], capture_output=True, text=True, check=True).stdout.strip()
        except Exception:
            return "unknown"
    return dict(revision=g("rev-parse", "--short", "HEAD"), dirty=bool(g("status", "--porcelain", "--", str(HERE.parent))))


def evaluate(sys_id, labels_to_run, jobs=1, csv_dir=None, cfg=None, overrides=None, seeds=SEEDS, with_cp=True, cands=CANDS):
    result, all_ps, all_lab = {}, {}, {}
    ran_loads = {}
    for label in labels_to_run:
        runs, ran = sweep(sys_id, label, jobs, cands, cfg, overrides, seeds)
        ran_loads.update(ran)
        ps = per_scenario(runs, cands, seeds)
        lab = label_scenarios(ps, cands)
        feasible = [sn for sn, l in lab.items() if l["fit"] != "infeasible"]
        discr = [sn for sn, l in lab.items() if l["fit"] == "comparison_valid"]
        result[label] = dict(
            per_scenario=ps, qa=qa_table(ps, None, cands), qa_feasible=qa_table(ps, feasible, cands), qa_discriminating=qa_table(ps, discr, cands) if discr else {},
            fit={sn: l["fit"] for sn, l in lab.items()}, scenario_labels=lab, tally={c: tally(lab, c) for c in cands[1:]},
            briefs={n: sc.brief for n, kn, sc in rows_of(label)}, exposes={n: sc.exposes for n, kn, sc in rows_of(label)},
        )
        if C1 in cands and C2 in cands:
            result[label]["c1_vs_c2"] = c1_vs_c2(ps)
        if label == "dp4_benchmark":
            result[label]["scaling_efficiency"] = scaling(ps, cands)
            result[label]["failure"] = failure_table(sys_id, label, ps, jobs, cfg, overrides, cands)
            if with_cp:
                result[label]["cp_capacity"] = cp_capacity(sys_id, label, jobs, cfg, overrides, seeds)
        all_ps.update({f"{label}/{sn}": v for sn, v in ps.items()})
        all_lab.update({f"{label}/{sn}": v for sn, v in lab.items()})
        if csv_dir is not None:
            csv_dir.mkdir(parents=True, exist_ok=True)
            flat = [{k: v for k, v in r.items() if not isinstance(v, (dict, list))} for r in runs]
            keys = sorted({k for r in flat for k in r})
            with (csv_dir / f"{label}_runs.csv").open("w", newline="") as f:
                w = csv.DictWriter(f, fieldnames=keys)
                w.writeheader()
                w.writerows(flat)
    feas = [k for k, l in all_lab.items() if l["fit"] != "infeasible"]
    disc = [k for k, l in all_lab.items() if l["fit"] == "comparison_valid"]
    result["combined"] = dict(
        scope="all sets; feasible = baseline goodput > 0 (comparison_valid + saturated); discriminating = comparison_valid only",
        n_feasible=len(feas), n_discriminating=len(disc),
        qa_feasible=qa_table(all_ps, feas, cands) if feas else {}, qa_discriminating=qa_table(all_ps, disc, cands) if disc else {},
        tally={c: tally(all_lab, c) for c in cands[1:]})
    cfg_path = Path(cfg) if cfg else params_mod.DEFAULT_CONFIG
    result["meta"] = dict(
        system=sys_id, seeds=list(seeds), loads=list(LOADS), max_load=MAX_LOAD, loads_run={k: sorted(v) for k, v in ran_loads.items()},
        t95=T95, material_rel=MATERIAL_REL, evidence="[B+C] simulation; not [A]", sets=list(labels_to_run), candidates=list(cands),
        command=" ".join([sys.executable.split("/")[-1], "qa_eval.py"] + sys.argv[1:]), git=git_info(),
        config=str(cfg_path.relative_to(HERE.parent.parent.parent.parent) if cfg_path.is_relative_to(HERE.parent.parent.parent.parent) else cfg_path),
        config_sha1=hashlib.sha1(cfg_path.read_bytes()).hexdigest(), overrides=overrides or {},
        qa_definitions=dict(
            qa1="geomean over CB rows of Max SLO Goodput / T_ref; stars 0.90/1.10",
            qa2="TTFT/TPOT P99 reported separately; star = worst case over CB rows (own-peak load); *_common = at Baseline-peak load; *_load1 = at x1.0",
            qa3="time-average KV residency (P buffer + D HBM + pool) at the Baseline-peak load; saving multiplier = base/cand; stars 0.95/1.25 (temporary definition, qa-criteria-dp4 section 2)",
            scalability="Scaling Efficiency values only, no stars",
            goodput="per-request SLO: TTFT <= 2 s and TPOT <= 50 ms; cohort = arrivals after the 10 % warm-up",
            never_ms=NEVER_MS),
    )
    return result


def fmt_qa(cand, q):
    return (f"{cand:26s} QA1 {q['qa1']} x{q['qa1_ratio_geomean']:.3f} (±{q['qa1_ratio_ci95']:.3f}) | QA2 {q['qa2']} "
            f"TTFT {q['qa2_ttft_p99_worst_ms']:.0f}ms TPOT {q['qa2_tpot_p99_worst_ms']:.1f}ms | QA3 {q['qa3']} {q['qa3_kv_resident_gib_geomean']:.1f} GiB (save x{q['qa3_saving_multiplier']:.3f})")


def print_result(result):
    for label, d in result.items():
        if label in ("meta", "combined"):
            continue
        n = {f: sum(1 for v in d["fit"].values() if v == f) for f in ("comparison_valid", "saturated", "infeasible")}
        print(f"== {label}  scenarios: {n}")
        key = "qa_feasible" if d["qa_feasible"] and d["qa_feasible"][BASE]["n_scenarios"] else "qa"
        for cand, q in d[key].items():
            print("  ", fmt_qa(cand, q))
        for c in d["tally"]:
            t = d["tally"][c]
            print(f"   {c:26s} win {len(t['win'])} tie {len(t['tie'])} loss {len(t['loss'])}  loss={t['loss']}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--system", required=True, choices=list(dp1_bridge.SYSTEM_CLUSTER))
    ap.add_argument("--sets", nargs="*", default=[s for s, _ in SETS], choices=[s for s, _ in SETS])
    ap.add_argument("--seeds", nargs="*", type=int, default=list(SEEDS))
    ap.add_argument("--jobs", type=int, default=min(4, os.cpu_count() or 1))
    ap.add_argument("--out-dir", type=Path, default=None)
    ap.add_argument("--config", type=Path, default=None)
    ap.add_argument("--no-csv", action="store_true")
    ap.add_argument("--no-cp", action="store_true", help="skip the control-plane saturation sweep")
    args = ap.parse_args()
    out_dir = args.out_dir or (HERE.parent / "results" / "data" / args.system)
    out_dir.mkdir(parents=True, exist_ok=True)
    print("system:", args.system)
    res = evaluate(args.system, args.sets, args.jobs, None if args.no_csv else out_dir, args.config, None, tuple(args.seeds), not args.no_cp)
    (out_dir / "qa_result.json").write_text(json.dumps(res, indent=1, sort_keys=True))
    print_result(res)
    print("wrote", out_dir / "qa_result.json")


if __name__ == "__main__":
    main()
