"""DP1 supplementary rating (dp1-rating-v3; QA3 official star = relative U_cand/U_base) (fine-grained tiers + C1-vs-C2 head-to-head) computed from qa_result.json.

The common stars (qa-evaluation-criteria.md) are NOT replaced; see Evaluation/DP1/qa-criteria-dp1.md.

    python dp1_rating.py ../results/data/SYS-4/qa_result.json      # prints, and writes dp1_rating.json next to it
"""
from __future__ import annotations

import json
import math
import statistics
import sys
from pathlib import Path

CFG = json.loads((Path(__file__).with_name("dp1_rating.json")).read_text())
BASE, C1, C2 = "Baseline-static", "C1-resource-driven", "C2-behavior-driven"
SETS = ("common_benchmark", "dp1_stress_benchmark", "dp1_dynamic_benchmark")
T95 = CFG["t95"]


def tier(x, edges):
    """index of the band x falls in (0 = below first edge)."""
    return sum(1 for e in edges if x >= e)


def tier_lower_better(x, edges):
    """tier where SMALLER is better: 0 = worse than the largest edge, len(edges) = better than the smallest."""
    return sum(1 for e in edges if x <= e)


def mean_ci(xs):
    m = statistics.mean(xs)
    sd = statistics.stdev(xs) if len(xs) > 1 else 0.0
    return m, T95 * sd / math.sqrt(len(xs))


def geomean(xs):
    return math.exp(statistics.mean(math.log(max(1e-12, x)) for x in xs))


def valid_scenarios(res, labels):
    """(set, name) of comparison-valid scenarios among the given sets."""
    out = []
    for lab in labels:
        for sn, v in res[lab]["scenario_labels"].items():
            if v["fit"] == "comparison_valid":
                out.append((lab, sn))
    return out


def agg_ratio(res, scen, num, den, key="seeds_goodput"):
    """point = geometric mean over scenarios of (mean metric num / mean metric den), same as qa_eval's QA1 ratio;
    CI95 = t-interval over the paired per-seed geometric means (same trace and seed for both candidates)."""
    ps = res
    point = geomean([statistics.mean(ps[l]["per_scenario"][s][num][key]) / max(1e-12, statistics.mean(ps[l]["per_scenario"][s][den][key])) for l, s in scen])
    n = len(ps[scen[0][0]]["per_scenario"][scen[0][1]][num][key])
    per_seed = [geomean([ps[l]["per_scenario"][s][num][key][i] / max(1e-12, ps[l]["per_scenario"][s][den][key][i]) for l, s in scen]) for i in range(n)]
    return point, mean_ci(per_seed)[1]


def eff_group(res, scen, c):
    """QA3 v5 resource efficiency = SLO goodput / cost-weighted occupancy (cost_model.py), relative to Baseline.
    Same aggregation as QA1: geometric mean over scenarios of the ratio of seed-means, CI over paired per-seed geomeans."""
    base_keys = res[scen[0][0]]["per_scenario"][scen[0][1]][BASE]
    schemes = [k[len("seeds_eff_"):] for k in base_keys if k.startswith("seeds_eff_")]
    by = {}
    for sch in schemes:
        r, ci = agg_ratio(res, scen, c, BASE, "seeds_eff_" + sch) if scen else (1.0, 0.0)
        by[sch] = dict(rel=r, ci95=ci)
    ps = [res[l]["per_scenario"][s][c] for l, s in scen]
    bs = [res[l]["per_scenario"][s][BASE] for l, s in scen]
    cost, base_cost = statistics.mean(p["cost_occ"] for p in ps), statistics.mean(p["cost_occ"] for p in bs)
    tiers = sorted(ps[0]["tier_occ_gib"])
    # QA3 v6 (official): HBM usage relative to Baseline (lower is better); saving factor = 1 / ratio. Cost-weighted occupancy = auxiliary.
    hbm_r, hbm_ci = agg_ratio(res, scen, c, BASE, "seeds_hbm_occ") if scen else (1.0, 0.0)
    cost_by = {}
    for sch in schemes:
        cr, cci = agg_ratio(res, scen, c, BASE, "seeds_cost_" + sch) if scen else (1.0, 0.0)
        cost_by[sch] = dict(ratio=cr, ci95=cci)
    hbm = dict(ratio=hbm_r, ci95=hbm_ci, saving=1.0 / max(1e-12, hbm_r), saving_ci95=hbm_ci / max(1e-12, hbm_r) ** 2,
               gib=statistics.mean(p["tier_occ_gib"]["hbm"] for p in ps), base_gib=statistics.mean(p["tier_occ_gib"]["hbm"] for p in bs),
               n_reduced=sum(1 for p, b in zip(ps, bs) if p["tier_occ_gib"]["hbm"] < 0.99 * b["tier_occ_gib"]["hbm"]),
               n_increased=sum(1 for p, b in zip(ps, bs) if p["tier_occ_gib"]["hbm"] > 1.01 * b["tier_occ_gib"]["hbm"]))
    return dict(rel=by["registered"]["rel"], ci95=by["registered"]["ci95"], by_scheme=by, hbm=hbm, cost_ratio_by_scheme=cost_by,
                cost_occ=cost, base_cost_occ=base_cost,
                cost_ratio=cost / max(1e-12, base_cost),
                tier_occ_gib={m: statistics.mean(p["tier_occ_gib"][m] for p in ps) for m in tiers})


def rate_group(res, scen):
    out = {}
    for c in (BASE, C1, C2):
        ps = [res[l]["per_scenario"][s][c] for l, s in scen]
        r, ci = agg_ratio(res, scen, c, BASE) if scen else (1.0, 0.0)
        t1 = tier(r, CFG["qa1_ratio_edges"])
        ttft = [p["ttft_p99_ms"] for p in ps]; tpot = [p["tpot_p99_ms"] for p in ps]
        util = statistics.mean(p["useful_util"] for p in ps)  # QA3 v4: pooled over ALL memories
        base_util = statistics.mean(res[l]["per_scenario"][s][BASE]["useful_util"] for l, s in scen)
        mean_tier = {}
        for p in ps:
            for m, u in p["tier_util"].items():
                mean_tier.setdefault(m, []).append(u)
        tt = tier_lower_better(statistics.median(ttft), CFG["qa2_ttft_p99_edges_ms"])
        tp = tier_lower_better(statistics.median(tpot), CFG["qa2_tpot_p99_edges_ms"])
        t3 = tier(util, CFG["qa3_util_edges"])
        lat = {}
        for k in ("ttft_p50_ms", "ttft_p95_ms", "ttft_p99_ms", "tpot_p50_ms", "tpot_p95_ms", "tpot_p99_ms"):
            vals = [p.get(k) for p in ps]
            if None in vals:
                continue
            lat[k] = dict(median=statistics.median(vals), worst=max(vals))
        # improvement factor vs baseline (>1 better), geometric mean over scenarios, P99
        imp = {}
        for k in ("ttft_p50_ms", "ttft_p95_ms", "ttft_p99_ms", "tpot_p50_ms", "tpot_p95_ms", "tpot_p99_ms"):
            if any(k not in res[l]["per_scenario"][s][c] for l, s in scen):
                continue
            imp[k] = geomean([res[l]["per_scenario"][s][BASE][k] / max(1e-9, res[l]["per_scenario"][s][c][k]) for l, s in scen])
        out[c] = dict(
            n=len(scen),
            eff=eff_group(res, scen, c),
            qa1=dict(ratio=r, ci95=ci, tier=t1, tier_max=len(CFG["qa1_ratio_edges"]), common_star=CFG["qa1_tier_to_common_star"][t1]),
            qa2=dict(latency=lat, improvement_vs_baseline=imp, ttft_tier=tt, ttft_tier_max=len(CFG["qa2_ttft_p99_edges_ms"]),
                     tpot_tier=tp, tpot_tier_max=len(CFG["qa2_tpot_p99_edges_ms"])),
            qa3=dict(useful_util=util, tier=t3, tier_max=len(CFG["qa3_util_edges"]), common_star=CFG["qa3_tier_to_common_star"][t3],
                     delta_pp_vs_baseline=(util - base_util) * 100,
                     rel_vs_baseline=util / max(1e-12, base_util),
                     pooled_occupancy=statistics.mean(p["pooled_util"] for p in ps),
                     tier_util={m: statistics.mean(v) for m, v in sorted(mean_tier.items())},
                     tier_util_mean_active=statistics.mean(p["tier_util_mean_active"] for p in ps),
                     useful_hbm_util=statistics.mean(p["useful_hbm_util"] for p in ps),
                     useful_hbm_delta_pp_vs_baseline=(statistics.mean(p["useful_hbm_util"] for p in ps) - statistics.mean(res[l]["per_scenario"][s][BASE]["useful_hbm_util"] for l, s in scen)) * 100),
        )
    return out


def head_to_head(res, scen):
    """C2 vs C1, same trace & seeds (paired)."""
    rows = {}
    wins = dict(C2=0, tie=0, C1=0)
    for l, s in scen:
        a, b = res[l]["per_scenario"][s][C1], res[l]["per_scenario"][s][C2]
        diffs = [y / max(1e-12, x) for x, y in zip(a["seeds_goodput"], b["seeds_goodput"])]
        r, ci = mean_ci(diffs)
        rel = r - 1.0
        if abs(rel) < CFG["materiality_rel"] or abs(rel) <= ci:
            v = "tie"
        else:
            v = "C2" if rel > 0 else "C1"
        wins[v] += 1
        rows[f"{l}/{s}"] = dict(goodput_ratio_C2_over_C1=r, ci95=ci, verdict=v,
                                ttft_p99_ratio_C2_over_C1=b["ttft_p99_ms"] / max(1e-9, a["ttft_p99_ms"]),
                                tpot_p99_ratio_C2_over_C1=b["tpot_p99_ms"] / max(1e-9, a["tpot_p99_ms"]),
                                util_delta_pp_C2_minus_C1=(b["useful_util"] - a["useful_util"]) * 100,
                                hbm_util_delta_pp_C2_minus_C1=(b["useful_hbm_util"] - a["useful_hbm_util"]) * 100,
                                migration_gib_C1=a["migration_gib"], migration_gib_C2=b["migration_gib"])
    gm = agg_ratio_h2h(res, scen)
    return dict(per_scenario=rows, tally=wins, geomean_goodput_ratio_C2_over_C1=gm[0], geomean_ci95=gm[1])


def agg_ratio_h2h(res, scen):
    return agg_ratio(res, scen, C2, C1)


def latency_order(group):
    """C2 vs C1 latency comparison, P99 -> P95 -> P50 (improvement factor vs baseline, geometric mean of TTFT and TPOT).
    A percentile decides only if the two candidates differ by more than the latency materiality (5%)."""
    mat = CFG.get("latency_materiality_rel", 0.05)
    res = {}
    for p in ("p99", "p95", "p50"):
        f = {}
        for c in (C1, C2):
            imp = group[c]["qa2"]["improvement_vs_baseline"]
            f[c] = math.sqrt(imp[f"ttft_{p}_ms"] * imp[f"tpot_{p}_ms"])
        r = f[C2] / f[C1]
        res[p] = dict(C1_improvement=f[C1], C2_improvement=f[C2], C2_over_C1=r,
                      verdict=("tie" if abs(r - 1) < mat else ("C2" if r > 1 else "C1")))
    decided = next((p for p in ("p99", "p95", "p50") if res[p]["verdict"] != "tie"), None)
    res["decided_by"] = decided
    res["overall"] = res[decided]["verdict"] if decided else "tie"
    return res


def dp1_star(value, edges):
    return "★" * (1 + sum(1 for e in edges if value >= e))


def add_dp1_stars(group):
    """DP1 official stars (relative to Baseline-static). QA2 = geometric mean of the six improvement factors
    (TTFT/TPOT x P50/P95/P99); QA3 = utilization change in percentage points."""
    cfg = CFG["dp1_star"]
    for c, x in group.items():
        imp = x["qa2"]["improvement_vs_baseline"]
        l_all = geomean([imp[f"{m}_{p}_ms"] for m in ("ttft", "tpot") for p in cfg["qa2_percentiles"]])
        x["qa2"]["latency_improvement_geomean"] = l_all
        x["dp1_star"] = dict(
            qa1=dp1_star(x["qa1"]["ratio"], cfg["qa1_ratio_edges"]),
            qa2=dp1_star(l_all, cfg["qa2_latency_improvement_edges"]),
            qa3=dp1_star(x["eff"]["hbm"]["saving"], cfg["qa3_hbm_saving_edges"]),   # v6: HBM usage saving factor (official, higher is better)
            qa3_eff_ref=dp1_star(x["eff"]["rel"], cfg["qa3_eff_relative_edges"]),   # v5 performance-per-cost star, diagnostic only
            qa3_cost_saving_ref=dp1_star(1.0 / max(1e-12, x["eff"]["cost_ratio_by_scheme"]["registered"]["ratio"]), cfg["qa3_hbm_saving_edges"]),   # cost-weighted occupancy saving, auxiliary
            qa3_util_diag=dp1_star(x["qa3"]["rel_vs_baseline"], cfg["qa3_relative_edges"]),   # v4 pooled-utilization star, diagnostic only
            qa3_common_ref=x["qa3"]["common_star"],  # common 65%/85% absolute star, reference only
            qa1_ci_straddles_edge=any(abs(x["qa1"]["ratio"] - e) <= x["qa1"]["ci95"] for e in cfg["qa1_ratio_edges"]),
        )
    return group


def star_sensitivity(group):
    """QA1 stars of C1/C2 when the top (3-star) edge is moved (lower edge fixed)."""
    cfg = CFG["dp1_star"]; lo = cfg["qa1_ratio_edges"][0]
    out = {}
    for top in cfg["sensitivity_qa1_top_edge"]:
        out[str(top)] = {c: dp1_star(group[c]["qa1"]["ratio"], [lo, top]) for c in (C1, C2)}
    return out


def star_sensitivity_qa3(group):
    """Auxiliary: cost-weighted occupancy saving (1/ratio) and its star under each price scheme (cost_model.py)."""
    cfg = CFG["dp1_star"]
    schemes = group[C1]["eff"]["cost_ratio_by_scheme"]
    return {sch: {c: dict(saving=1.0 / max(1e-12, group[c]["eff"]["cost_ratio_by_scheme"][sch]["ratio"]),
                          star=dp1_star(1.0 / max(1e-12, group[c]["eff"]["cost_ratio_by_scheme"][sch]["ratio"]), cfg["qa3_hbm_saving_edges"])) for c in (C1, C2)} for sch in schemes}


def rate(res):
    out = dict(version=CFG["version"], defined_after_first_look=CFG["defined_after_first_look"], sets={}, h2h={})
    for lab in SETS:
        scen = valid_scenarios(res, [lab])
        if scen:
            out["sets"][lab] = add_dp1_stars(rate_group(res, scen))
            out["h2h"][lab] = head_to_head(res, scen)
            out["h2h"][lab]["latency_order"] = latency_order(out["sets"][lab])
    scen = valid_scenarios(res, SETS)
    out["sets"]["combined"] = add_dp1_stars(rate_group(res, scen))
    out["sensitivity_combined_qa1"] = star_sensitivity(out["sets"]["combined"])
    out["sensitivity_combined_qa3"] = star_sensitivity_qa3(out["sets"]["combined"])
    out["h2h"]["combined"] = head_to_head(res, scen)
    out["h2h"]["combined"]["latency_order"] = latency_order(out["sets"]["combined"])
    out["scope"] = {"combined_n": len(scen)}
    return out


def main():
    p = Path(sys.argv[1])
    res = json.loads(p.read_text())
    out = rate(res)
    (p.parent / "dp1_rating.json").write_text(json.dumps(out, indent=1, sort_keys=True))
    for lab, g in out["sets"].items():
        print("==", lab, "n =", g[BASE]["n"])
        for c in (BASE, C1, C2):
            x = g[c]
            print(f"  {c[:8]:8s} QA1 T{x['qa1']['tier']}/{x['qa1']['tier_max']} x{x['qa1']['ratio']:.3f} | QA2 TTFT-tier {x['qa2']['ttft_tier']}/{x['qa2']['ttft_tier_max']} TPOT-tier {x['qa2']['tpot_tier']}/{x['qa2']['tpot_tier_max']} | QA3 T{x['qa3']['tier']}/{x['qa3']['tier_max']} {x['qa3']['useful_util']*100:.0f}%")
        h = out["h2h"][lab]
        lo = h["latency_order"]
        for c in (BASE, C1, C2):
            ds = g[c]["dp1_star"]; print(f"  {c[:8]:8s} DP1 stars QA1 {ds['qa1']} QA2 {ds['qa2']} (L x{g[c]['qa2']['latency_improvement_geomean']:.2f}) QA3 {ds['qa3']} (x{g[c]['qa3']['rel_vs_baseline']:.2f}, {g[c]['qa3']['delta_pp_vs_baseline']:+.0f}pp; common {ds['qa3_common_ref']}; HBM-only {g[c]['qa3']['useful_hbm_util']*100:.0f}%)")
        print(f"  C2/C1 goodput x{h['geomean_goodput_ratio_C2_over_C1']:.3f}±{h['geomean_ci95']:.3f}  C2 {h['tally']['C2']} / tie {h['tally']['tie']} / C1 {h['tally']['C1']} | latency: " + ", ".join(f"{p} C2/C1 x{lo[p]['C2_over_C1']:.2f} ({lo[p]['verdict']})" for p in ("p99","p95","p50")) + f" -> {lo['overall']} (by {lo['decided_by']})")


if __name__ == "__main__":
    main()
