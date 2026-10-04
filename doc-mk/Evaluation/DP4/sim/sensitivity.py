"""Sensitivity runs of loop-log Iteration 1 and qa-criteria-dp4 section 6 (main parameters are never changed, H16).

    uv run --no-project python sensitivity.py run --group grid --jobs 4          # eta_cxl x background (12), full benchmark set
    uv run --no-project python sensitivity.py run --group others --jobs 4       # eta_rdma, overlap, S/probe/T/batch/cs, meta cost, bg +-0.1
    uv run --no-project python sensitivity.py summarize                         # -> results/data/sensitivity/summary.json
    uv run --no-project python sensitivity_table.py                             # markdown tables from summary.json

Every configuration is evaluated on SYS-H100 and SYS-B200 (5 seeds, load sweep as in the main run) and merged into an integrated
result. Background cap c means the CB-1/CB-3 level is c (every bg value is multiplied by c/0.85; the CB-2 ramp keeps its shape).
Control: (eta_cxl 0.5, bg 0.85) is the main configuration and must reproduce the main result.
"""
from __future__ import annotations

import argparse
import itertools
import json
import os
from pathlib import Path

import dp1_bridge
import merge_systems as ms
import params as params_mod
import qa_eval as q
from arms import BASE, C1, C2

HERE = Path(__file__).resolve().parent
DATA = HERE.parent / "results" / "data"
ROOT = DATA / "sensitivity"
SYSTEMS = ("SYS-H100", "SYS-B200")
MAIN_BG = 0.85
ETAS = (0.5, 0.7, 0.85, 1.0)
BGS = (0.0, 0.5, 0.85)
STAR_SCALES = (0.9, 1.0, 1.1)


def configs(group):
    """[(group, label, overrides, sets)]"""
    both = [s for s, _ in q.SETS]
    cb = ["common_benchmark"]
    out = []
    if group in ("grid", "all"):
        for e, b in itertools.product(ETAS, BGS):
            out.append(("eta_cxl_bg", f"eta{e}_bg{b}", dict(eta_cxl=e, bg_scale=b / MAIN_BG), both))
    if group in ("others", "all"):
        for v in (0.6, 0.95):
            out.append(("eta_rdma", f"eta_rdma{v}", dict(eta_rdma=v), cb))
        for v in (0.5, 0.9):
            out.append(("overlap", f"overlap{v}", dict(overlap_ratio=v), cb))
        for b in (0.75, 0.95):
            out.append(("bg_pm01", f"bg{b}", dict(bg_scale=b / MAIN_BG), cb))
        for v in (1, 8, 512):
            out.append(("lock_stripes", f"S{v}", dict(lock_stripes=v), both))
        for v in (0.1, 0.7):
            out.append(("probe_us", f"probe{v}", dict(probe_us=v), both))
        for v in (2, 5):
            out.append(("cs_per_request", f"cs{v}", dict(cs_per_request=v), both))
        for v in (0.7, 2.0):
            out.append(("meta_cost_us", f"meta{v}", dict(meta_read_us=v, meta_write_flush_us=v), both))
        for v in (2, 4):
            out.append(("server_threads", f"T{v}", dict(server_threads=v), both))
        for v in (4, 16):
            out.append(("rpc_hash_batch", f"batch{v}", dict(rpc_hash_batch=v), both))
    return out


def slim(res):
    """drop the bulky per-load tables (kept: everything needed to re-merge and to recompute QA tables)."""
    out = json.loads(json.dumps(res))
    for label in out["meta"]["sets"]:
        for v in out[label]["per_scenario"].values():
            for c in out["meta"]["candidates"]:
                v[c].pop("by_load", None)
    return out


def run_config(group, label, overrides, sets, jobs):
    d = ROOT / group / label
    d.mkdir(parents=True, exist_ok=True)
    src = {}
    for sysid in SYSTEMS:
        res = q.evaluate(sysid, sets, jobs, None, None, overrides, q.SEEDS, False)
        src[sysid] = slim(res)
        (d / sysid).mkdir(exist_ok=True)
        (d / sysid / "qa_result.json").write_text(json.dumps(src[sysid], indent=1, sort_keys=True))
    if set(sets) == {"common_benchmark", "dp4_benchmark"}:
        merged = ms.merge_src(src, list(SYSTEMS))
        (d / "INT-H100-B200").mkdir(exist_ok=True)
        (d / "INT-H100-B200" / "qa_result.json").write_text(json.dumps(merged, indent=1, sort_keys=True))
    else:
        merged = merge_cb_only(src)
        (d / "INT-H100-B200").mkdir(exist_ok=True)
        (d / "INT-H100-B200" / "qa_result.json").write_text(json.dumps(merged, indent=1, sort_keys=True))
    (d / "config.json").write_text(json.dumps(dict(group=group, label=label, overrides=overrides, sets=list(sets), systems=list(SYSTEMS),
                                                    git=q.git_info(), seeds=list(q.SEEDS), main_bg=MAIN_BG,
                                                    command="python sensitivity.py run --group " + group), indent=1))


def merge_cb_only(src):
    """integrated result for a Common-Benchmark-only configuration (same rule as merge_systems, one set)."""
    cands = tuple(src[SYSTEMS[0]]["meta"]["candidates"])
    label = "common_benchmark"
    ps = {}
    for s in SYSTEMS:
        for sn, v in src[s][label]["per_scenario"].items():
            ps[f"{sn}@{s[4:]}"] = v
    lab = q.label_scenarios(ps, cands)
    feasible = [k for k, l in lab.items() if l["fit"] != "infeasible"]
    discr = [k for k, l in lab.items() if l["fit"] == "comparison_valid"]
    res = {label: dict(qa=q.qa_table(ps, None, cands), qa_feasible=q.qa_table(ps, feasible, cands),
                       qa_discriminating=q.qa_table(ps, discr, cands) if discr else {}, fit={k: l["fit"] for k, l in lab.items()},
                       scenario_labels=lab, tally={c: q.tally(lab, c) for c in cands[1:]}, per_scenario=ps)}
    all_ps = {f"{label}/{k}": v for k, v in ps.items()}
    all_lab = {f"{label}/{k}": v for k, v in lab.items()}
    feas = [k for k, l in all_lab.items() if l["fit"] != "infeasible"]
    res["combined"] = dict(n_feasible=len(feas), qa_feasible=q.qa_table(all_ps, feas, cands) if feas else {},
                           tally={c: q.tally(all_lab, c) for c in cands[1:]}, scope="common benchmark only")
    res["meta"] = dict(system="INT-H100-B200", systems=list(SYSTEMS), sets=[label], candidates=list(cands))
    return res


# --------------------------------------------------------------------------- summaries
def cand_metrics(qa, c):
    d = qa[c]
    out = dict(qa1_ratio=d["qa1_ratio_geomean"], qa1_stars=d["qa1"], qa1_abs_goodput_tps=d["qa1_abs_goodput_geomean_tps"],
               qa1_n_cand_zero=d.get("qa1_n_cand_zero", 0),
               ttft_p99_ms_own=d["qa2_ttft_p99_ms_geomean"], tpot_p99_ms_own=d["qa2_tpot_p99_ms_geomean"],
               ttft_p99_ms_common=d["qa2_common_ttft_p99_ms_geomean"], ttft_p99_ms_load1=d["qa2_load1_ttft_p99_ms_geomean"],
               qa2_stars_own=d["qa2"], qa2_stars_load1=d["qa2_load1"], ttft_p99_worst_own=d["qa2_ttft_p99_worst_ms"],
               tpot_p99_worst_own=d["qa2_tpot_p99_worst_ms"], ttft_p99_worst_load1=d["qa2_load1_ttft_p99_worst_ms"],
               tpot_p99_worst_load1=d["qa2_load1_tpot_p99_worst_ms"],
               qa3_gib=d["qa3_kv_resident_gib_geomean"], qa3_multiplier=d["qa3_saving_multiplier"], qa3_stars=d["qa3"],
               qa3_load1_multiplier=d["qa3_load1_saving_multiplier"])
    if c != BASE:
        for basis, key in (("common", "tail_check_common_load"), ("own", "tail_check_own_peak")):
            for m in ("ttft", "tpot"):
                t = d[key][m]
                out[f"tail_{m}_worse_{basis}"] = t["n_worse"]
                out[f"tail_{m}_pairs_{basis}"] = t["n_pairs"]
                out[f"tail_{m}_worst_ratio_{basis}"] = t["worst_ratio"]
    return out


def summarize_result(res):
    cb = res["common_benchmark"]["qa_feasible"]
    d = dict(candidates={c: cand_metrics(cb, c) for c in cb}, n_cb_pairs=cb[BASE]["n_scenarios"])
    t = res["combined"]["tally"]
    d["tally"] = {c: {k: len(v) for k, v in t[c].items()} for c in t}
    d["fit_cb"] = {k: sum(1 for x in res["common_benchmark"]["fit"].values() if x == k) for k in ("comparison_valid", "saturated", "infeasible")}
    if "dp4_benchmark" in res:
        dp = res["dp4_benchmark"]
        d["fit_dp4"] = {k: sum(1 for x in dp["fit"].values() if x == k) for k in ("comparison_valid", "saturated", "infeasible")}
        gr = [v["goodput_ratio_c2_over_c1"] for v in dp["c1_vs_c2"].values() if v["goodput_ratio_c2_over_c1"]]
        d["c1_vs_c2_dp4_goodput_ratio_range"] = [min(gr), max(gr)]
        d["c1_vs_c2_dp4_max_abs_dev"] = max(abs(x - 1.0) for x in gr)
        d["dp4_c1_vs_c2_verdicts"] = {k: v["verdict_c2_vs_c1"] for k, v in dp["c1_vs_c2"].items() if any(x != "tie" for x in v["verdict_c2_vs_c1"].values())}
        d["dp4_qa1_ratio"] = {c: dp["qa_feasible"][c]["qa1_ratio_geomean"] for c in dp["qa_feasible"]}
        d["dp4_tally"] = {c: {k: len(v) for k, v in dp["tally"][c].items()} for c in dp["tally"]}
    return d


def load_dir(d):
    out = {}
    for name in (*SYSTEMS, "INT-H100-B200"):
        f = d / name / "qa_result.json"
        if f.exists():
            out[name] = summarize_result(json.loads(f.read_text()))
    return out


# --------------------------------------------------------------------------- break-even
def crossing(xs, ys, target, higher_is_better=True):
    """first x at which y reaches the target (linear interpolation between neighbouring grid points).
    -> dict(status: met_at_lowest | interpolated | none_in_grid, x, best_y, x_best)."""
    ok = [(y >= target) if higher_is_better else (y <= target) for y in ys]
    best_i = max(range(len(ys)), key=lambda i: ys[i] if higher_is_better else -ys[i])
    base = dict(best=ys[best_i], at=xs[best_i])
    if ok[0]:
        return dict(status="met_at_lowest", x=xs[0], **base)
    for i in range(1, len(xs)):
        if ok[i]:
            x0, x1, y0, y1 = xs[i - 1], xs[i], ys[i - 1], ys[i]
            x = x0 + (target - y0) * (x1 - x0) / (y1 - y0) if y1 != y0 else x1
            return dict(status="interpolated", x=x, bracket=[x0, x1], first_grid_point=x1, **base)
    return dict(status="none_in_grid", x=None, **base)


def provenance_of(param):
    raw = params_mod.load_raw()[param]
    return dict(provenance=raw["provenance"], registered_range=raw["range"], value=raw["value"])


def classify_eta(x):
    """where a break-even eta_cxl sits relative to what the config registers."""
    if x is None:
        return "no break-even in the evaluated grid"
    pv = provenance_of("eta_cxl")
    lo, hi = min(pv["registered_range"]), max(pv["registered_range"])
    if lo <= x <= hi:
        return f"inside the registered {pv['provenance']} sweep range [{lo}, {hi}] (eta_cxl is an ASSUMED efficiency, not a PAPER value)"
    return f"outside the registered {pv['provenance']} sweep range [{lo}, {hi}]; adapter bandwidth 63 GB/s itself is PAPER, the efficiency is ASSUMED"


def break_even(summary):
    """per system / candidate / criterion / bg level: where the candidate reaches the Baseline over eta_cxl."""
    grid = summary["eta_cxl_bg"]
    out = {}
    for sysname in (*SYSTEMS, "INT-H100-B200"):
        out[sysname] = {}
        for c in (C1, C2):
            out[sysname][c] = {}
            for b in BGS:
                xs = list(ETAS)
                rows = [grid[f"eta{e}_bg{b}"][sysname]["candidates"][c] for e in xs]
                out[sysname][c][f"bg{b}"] = dict(
                    qa1_ratio_ge_1=crossing(xs, [r["qa1_ratio"] for r in rows], 1.0, True),
                    qa3_multiplier_ge_1=crossing(xs, [r["qa3_multiplier"] for r in rows], 1.0, True),
                    qa3_load1_multiplier_ge_1=crossing(xs, [r["qa3_load1_multiplier"] for r in rows], 1.0, True),
                    ttft_worse_pairs_common_eq_0=crossing(xs, [float(r["tail_ttft_worse_common"]) for r in rows], 0.0, False),
                    ttft_worse_pairs_own_eq_0=crossing(xs, [float(r["tail_ttft_worse_own"]) for r in rows], 0.0, False))
                for r in out[sysname][c][f"bg{b}"].values():
                    r["eta_cxl_provenance_note"] = classify_eta(r["x"])
    return out


def one_param_break_even(summary):
    """for the single-parameter sweeps: does any evaluated value bring a candidate to the Baseline?"""
    out = {}
    for g, cfgs in summary.items():
        if g == "eta_cxl_bg":
            continue
        out[g] = {}
        for c in (C1, C2):
            rows = {lab: v["INT-H100-B200"]["candidates"][c] for lab, v in cfgs.items()}
            out[g][c] = {lab: dict(qa1_ratio=r["qa1_ratio"], qa3_multiplier=r["qa3_multiplier"], ttft_worse_common=r["tail_ttft_worse_common"])
                         for lab, r in rows.items()}
    return out


# --------------------------------------------------------------------------- star boundaries +-10 %
def stars_scaled(c, s):
    """re-score a stored candidate summary with every boundary multiplied by s (QA1 0.90/1.10, QA2 2 s/4 s and 50/100 ms,
    QA3 0.95/1.25)."""
    q1 = 3 if c["qa1_ratio"] >= 1.10 * s else (2 if c["qa1_ratio"] >= 0.90 * s else 1)
    t, p = c["ttft_p99_worst_own"], c["tpot_p99_worst_own"]
    q2 = 3 if (t <= 2000 * s and p <= 50 * s) else (2 if (t <= 4000 * s and p <= 100 * s) else 1)
    q3 = 3 if c["qa3_multiplier"] >= 1.25 * s else (2 if c["qa3_multiplier"] >= 0.95 * s else 1)
    return dict(qa1=q1, qa2=q2, qa3=q3, total=q1 + q2 + q3)


def star_boundary_table(main_summary):
    out = {}
    for sysname, v in main_summary.items():
        out[sysname] = {}
        for s in STAR_SCALES:
            out[sysname][str(s)] = {c: stars_scaled(m, s) for c, m in v["candidates"].items()}
        out[sysname]["changes_vs_scale_1.0"] = {
            str(s): {c: out[sysname][str(s)][c] != out[sysname]["1.0"][c] for c in v["candidates"]} for s in STAR_SCALES if s != 1.0}
    return out


def summarize(root=ROOT):
    summary = {}
    for gdir in sorted(p for p in root.iterdir() if p.is_dir()):
        summary[gdir.name] = {}
        for cdir in sorted(p for p in gdir.iterdir() if p.is_dir() and (p / "config.json").exists()):
            cfg = json.loads((cdir / "config.json").read_text())
            r = load_dir(cdir)
            r["_config"] = dict(overrides=cfg["overrides"], sets=cfg["sets"], git=cfg["git"])
            summary[gdir.name][cdir.name] = r
    return summary


def main_summary():
    return {s: summarize_result(json.loads((DATA / s / "qa_result.json").read_text())) for s in (*SYSTEMS, "INT-H100-B200")}


def control_check(summary):
    """grid cell (eta_cxl 0.5, bg 0.85) must reproduce the main result."""
    cell = summary["eta_cxl_bg"]["eta0.5_bg0.85"]
    main = main_summary()
    out = {}
    for sysname in main:
        diffs = {}
        for c in main[sysname]["candidates"]:
            for k in ("qa1_ratio", "qa1_abs_goodput_tps", "qa3_gib", "ttft_p99_ms_own"):
                a, b = main[sysname]["candidates"][c][k], cell[sysname]["candidates"][c][k]
                diffs[f"{c}:{k}"] = abs(a - b)
        out[sysname] = dict(max_abs_diff=max(diffs.values()), match=max(diffs.values()) <= 1e-9 * 1e3)
    return out


def write_summary():
    summary = summarize()
    out = dict(
        meta=dict(loop_log="results/iterations/loop-log.md Iteration 1", etas=list(ETAS), backgrounds=list(BGS), main_bg=MAIN_BG,
                  bg_definition="bg level c = CB-1/CB-3 constant level; all bg values scaled by c/0.85 (CB-2 ramp keeps its shape); DP4-specific rows have bg 0",
                  eta_bw_parity=params_mod.load_params().rdma_node_bw / (params_mod.load_params().cxl_adapters_per_node * params_mod.load_params().cxl_adapter_bw_Bps),
                  provenance=dict(eta_cxl=provenance_of("eta_cxl"), eta_rdma=provenance_of("eta_rdma"), overlap_ratio=provenance_of("overlap_ratio"),
                                  lock_stripes=provenance_of("lock_stripes"), probe_us=provenance_of("probe_us"), server_threads=provenance_of("server_threads"),
                                  rpc_hash_batch=provenance_of("rpc_hash_batch"), cs_per_request=provenance_of("cs_per_request"),
                                  background_load="ASSUMED (plan 6.1; scenario constant, not a PAPER/SPEC value)"),
                  note="main parameters are unchanged; no sensitivity cell is promoted to main (loop-log decision rule)"),
        main=main_summary(), configs=summary)
    if "eta_cxl_bg" in summary and len(summary["eta_cxl_bg"]) == len(ETAS) * len(BGS):
        out["control_check"] = control_check(summary)
        be = break_even(summary)
        out["break_even"] = be
    out["one_param_sweeps"] = one_param_break_even(summary)
    out["star_boundary_pm10"] = star_boundary_table(out["main"])
    (ROOT / "summary.json").write_text(json.dumps(out, indent=1, sort_keys=True))
    return out


def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run")
    r.add_argument("--group", default="grid", choices=["grid", "others", "all"])
    r.add_argument("--jobs", type=int, default=min(4, os.cpu_count() or 1))
    r.add_argument("--only", nargs="*", default=None, help="labels to run (default: all of the group)")
    r.add_argument("--skip-existing", action="store_true")
    sub.add_parser("summarize")
    a = ap.parse_args()
    if a.cmd == "run":
        for group, label, ov, sets in configs(a.group):
            if a.only and label not in a.only:
                continue
            if a.skip_existing and (ROOT / group / label / "config.json").exists():
                continue
            print("config", group, label, ov, flush=True)
            run_config(group, label, ov, sets, a.jobs)
    else:
        write_summary()
        print("wrote", ROOT / "summary.json")


if __name__ == "__main__":
    main()
