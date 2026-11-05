#!/usr/bin/env python3
"""QA4 Modifiability: derive man-month and code-agent token cost from measured counts.

Usage (from repo root):
    uv run --no-project python doc-mk/Evaluation/tools/qa4_modifiability.py [--dp DP1|DP4]   (default DP1)

Input : <DP>/results/data/qa4_measured_counts.json   (measured modules / LOC per scenario and candidate)
Output: <DP>/results/data/qa4_modifiability.json
Formulas, constants and star thresholds are pre-registered in DP1/qa4-preregistration.md (sections 4, 5);
DP4/qa4-preregistration.md reuses them unchanged (mean aggregation from the start).
A scenario/candidate with "major_interface_change": true forces the M1 star to one star (preregistration rule);
counts files without that key (DP1) are unaffected.
All constants below are ASSUMED (2026-10-03); prices change, edit PRICES and re-run.
"""
from __future__ import annotations

import argparse
import itertools
import json
import statistics
from pathlib import Path

EVAL = Path(__file__).resolve().parents[1]
DATA = EVAL / "DP1" / "results" / "data"   # rebound in main() from --dp

# ---- ASSUMED constants (preregistration section 4) -------------------------------------------------
MID = dict(c_mod=3.0, k_real=5.0, P=40.0, f_ovh=2.0,           # man-month
           tpl=12.0, C0=25_000.0, a_read=1.5, n0=10.0, n_m=5.0, n_iter=2.0, o_turn=300.0)
LOW = dict(c_mod=2.0, k_real=3.0, P=80.0, f_ovh=1.5, tpl=8.0)   # optimistic
HIGH = dict(c_mod=5.0, k_real=10.0, P=25.0, f_ovh=3.0, tpl=16.0)  # pessimistic
DAYS_PER_MONTH = 21.0
# $/Mtok. ASSUMED illustrative prices as of 2026-10-03, not a price list.
PRICES = {
    "T1_frontier": dict(p_in=15.0, p_cache=1.5, p_out=75.0, mult=0.6),   # mult: tokens used relative to T2 (ASSUMED)
    "T2_mid":      dict(p_in=3.0,  p_cache=0.3, p_out=15.0, mult=1.0),
}
MULT_T1_RANGE = (0.4, 0.8)
STAR_TIER = "T1_frontier"      # tier whose dollars decide the M3 star (the more expensive one)
# thresholds (preregistration section 5)
M1_T = (2, 5)          # <=2 three stars, <=5 two stars, else one
M2_T = (0.5, 1.0)      # man-month per change
M3_T = (3.0, 10.0)     # USD per change at STAR_TIER


def stars_le(x: float, t3: float, t2: float) -> int:
    return 3 if x <= t3 else 2 if x <= t2 else 1


def man_month(n, loc, k):
    days = n * k["c_mod"] + (loc * k["k_real"] / k["P"]) * k["f_ovh"]
    return days / DAYS_PER_MONTH, days


def agent(n, loc, size, k, tier):
    pr = PRICES[tier]
    mult = k.get("mult_" + tier, pr["mult"])
    t_read = k["a_read"] * k["tpl"] * k["k_real"] * size
    cbar = k["C0"] + t_read
    turns = k["n0"] + k["n_m"] * n
    t_out = k["tpl"] * k["k_real"] * loc * k["n_iter"] + k["o_turn"] * turns
    tokens = mult * (cbar + turns * cbar + t_out)
    cost = mult * (cbar * pr["p_in"] + turns * cbar * pr["p_cache"] + t_out * pr["p_out"]) / 1e6
    return tokens, cost


def cand_metrics(changes, k):
    n = len(changes)
    loc = sum(c["loc_added"] for c in changes)
    size = sum(c["module_size_loc"] for c in changes)
    mm, days = man_month(n, loc, k)
    out = {"modules": n, "shared_modules": sum(1 for c in changes if c["shared"]),
           "files": sorted({f for c in changes for f in c["files"]}),
           "loc_added": loc, "module_size_loc": size,
           "engineer_days": round(days, 2), "man_months": round(mm, 3), "agent": {}}
    for tier in PRICES:
        tok, cost = agent(n, loc, size, k, tier)
        out["agent"][tier] = {"tokens": round(tok), "usd": round(cost, 2)}
    return out


def star_set(per_sc, k, agg="mean"):
    """per_sc: {scenario: {cand: changes}} -> sub-stars for each candidate.
    agg="mean": star of the mean metric over scenarios (v2, owner decision 2026-10-03, defined after first look).
    agg="worst": worst per-scenario star (v1, pre-registered; kept for transparency)."""
    res = {}
    for cand in ("C1", "C2"):
        n_l, mm_l, usd_l = [], [], []
        for sc, d in per_sc.items():
            ch = d[cand]["changes"]
            n = len(ch)
            loc = sum(c["loc_added"] for c in ch)
            n_l.append(n)
            mm_l.append(man_month(n, loc, k)[0])
            usd_l.append(agent(n, loc, sum(c["module_size_loc"] for c in ch), k, STAR_TIER)[1])
        if agg == "mean":
            sub = {"M1": stars_le(statistics.mean(n_l), *M1_T), "M2": stars_le(statistics.mean(mm_l), *M2_T),
                   "M3": stars_le(statistics.mean(usd_l), *M3_T)}
        else:
            sub = {"M1": min(stars_le(x, *M1_T) for x in n_l), "M2": min(stars_le(x, *M2_T) for x in mm_l),
                   "M3": min(stars_le(x, *M3_T) for x in usd_l)}
        if any(d[cand].get("major_interface_change") for d in per_sc.values()):
            sub["M1"] = 1   # preregistration: a major interface change forces M1 to one star
        res[cand] = {"sub": sub, "qa4": int(statistics.median(sub.values()))}
    return res


def s(n):
    return "★" * n


s_ = s


def main(dp="DP1"):
    global DATA
    DATA = EVAL / dp / "results" / "data"
    src = json.loads((DATA / "qa4_measured_counts.json").read_text())
    scs = src["scenarios"]
    out = {"schema": "qa4_modifiability v2", "date": src["date"], "evidence": src["evidence"],
           "inputs": f"{dp}/results/data/qa4_measured_counts.json", "constants_mid": MID, "constants_low": LOW,
           "constants_high": HIGH, "prices_assumed_2026-10-03": PRICES, "thresholds": {
               "M1_modules": "<=2 ★★★, 3-5 ★★, >=6 ★", "M2_man_months": "<=0.5 ★★★, <=1.0 ★★, else ★",
               "M3_usd_T1": "<=3 ★★★, <=10 ★★, else ★", "qa4": "median of M1, M2, M3 stars", "aggregation": "mean metric over the 4 scenarios, then star (v2); worst-case v1 kept as *_worst_case"},
           "scenarios": {}}
    for sc, d in scs.items():
        row = {"title": d["title"]}
        for cand in ("C1", "C2"):
            m = cand_metrics(d[cand]["changes"], MID)
            m["stars"] = {"M1": s(stars_le(m["modules"], *M1_T)), "M2": s(stars_le(m["man_months"], *M2_T)),
                          "M3": s(stars_le(m["agent"][STAR_TIER]["usd"], *M3_T))}
            lo = cand_metrics(d[cand]["changes"], {**MID, **LOW})
            hi = cand_metrics(d[cand]["changes"], {**MID, **HIGH})
            m["man_months_range"] = [lo["man_months"], hi["man_months"]]
            m["usd_T1_range"] = [lo["agent"]["T1_frontier"]["usd"], hi["agent"]["T1_frontier"]["usd"]]
            row[cand] = m
        out["scenarios"][sc] = row

    # aggregation: mean over scenarios per sub-metric (v2), QA4 = median of sub-stars; v1 worst-case kept
    base = star_set(scs, MID)
    worst = star_set(scs, MID, agg="worst")
    out["sub_stars_worst_case"] = {c: {k: s_(v) for k, v in worst[c]["sub"].items()} for c in worst}
    out["qa4_stars_worst_case"] = {c: s_(worst[c]["qa4"]) for c in worst}
    out["sub_stars"] = {c: {k: s(v) for k, v in base[c]["sub"].items()} for c in base}
    out["qa4_stars"] = {c: s(base[c]["qa4"]) for c in base}
    out["mean_over_scenarios"] = {
        c: {"modules": round(statistics.mean(out["scenarios"][x][c]["modules"] for x in scs), 2),
            "man_months": round(statistics.mean(out["scenarios"][x][c]["man_months"] for x in scs), 3),
            "usd_T1": round(statistics.mean(out["scenarios"][x][c]["agent"]["T1_frontier"]["usd"] for x in scs), 2),
            "usd_T2": round(statistics.mean(out["scenarios"][x][c]["agent"]["T2_mid"]["usd"] for x in scs), 2),
            "tokens_T1": round(statistics.mean(out["scenarios"][x][c]["agent"]["T1_frontier"]["tokens"] for x in scs)),
            "tokens_T2": round(statistics.mean(out["scenarios"][x][c]["agent"]["T2_mid"]["tokens"] for x in scs))}
        for c in ("C1", "C2")}

    # sensitivity: every combination of {LOW, MID, HIGH} for man-month constants and token constants, T1 mult range
    sens = {}
    for name, k in (("optimistic", {**MID, **LOW, "mult_T1_frontier": MULT_T1_RANGE[0]}),
                    ("mid", dict(MID)),
                    ("pessimistic", {**MID, **HIGH, "mult_T1_frontier": MULT_T1_RANGE[1]})):
        r = star_set(scs, k)
        sens[name] = {c: {"sub": {a: s(b) for a, b in r[c]["sub"].items()}, "qa4": s(r[c]["qa4"])} for c in r}
    out["sensitivity_constants"] = sens
    if dp != "DP1":
        cross = {}
        for nm, kk in (("mm_low_tokens_low", {**MID, **LOW, "mult_T1_frontier": MULT_T1_RANGE[0]}),
                       ("mm_low_tokens_high", {**MID, "c_mod": LOW["c_mod"], "k_real": MID["k_real"], "P": LOW["P"], "f_ovh": LOW["f_ovh"], "tpl": HIGH["tpl"], "mult_T1_frontier": MULT_T1_RANGE[1]}),
                       ("mm_high_tokens_low", {**MID, "c_mod": HIGH["c_mod"], "P": HIGH["P"], "f_ovh": HIGH["f_ovh"], "tpl": LOW["tpl"], "mult_T1_frontier": MULT_T1_RANGE[0]}),
                       ("mm_high_tokens_high", {**MID, **HIGH, "mult_T1_frontier": MULT_T1_RANGE[1]})):
            r = star_set(scs, kk)
            cross[nm] = {c: {"sub": {a: s(b) for a, b in r[c]["sub"].items()}, "qa4": s(r[c]["qa4"])} for c in r}
        out["sensitivity_constants_cross"] = cross
        # one constant at a time (others MID): where does a sub-star first move?
        one = {}
        for key in ("c_mod", "k_real", "P", "f_ovh", "tpl"):
            for nm, grp in (("low", LOW), ("high", HIGH)):
                r = star_set(scs, {**MID, key: grp[key]})
                one[f"{key}={grp[key]}"] = {c: {"sub": {a: s(b) for a, b in r[c]["sub"].items()}, "qa4": s(r[c]["qa4"])} for c in r}
        out["sensitivity_one_at_a_time"] = one
    # sensitivity: module-count alternatives recorded in the counts file (analytic, not measured)
    alt = {}
    if dp == "DP1":
        d1 = json.loads(json.dumps(scs))
        # S1 C2 with capability-class preference: drop the C2-only selector change
        d1["S1"]["C2"]["changes"] = [c for c in d1["S1"]["C2"]["changes"] if c["shared"]]
        # S4 with schema merged into Event Source
        for c in ("C1", "C2"):
            d1["S4"][c]["changes"] = [x for x in d1["S4"][c]["changes"] if not x["module"].startswith("Event/Migration")]
        r = star_set(d1, MID)
        alt["capclass_pref_and_event_schema_merged"] = {c: {"sub": {a: s(b) for a, b in r[c]["sub"].items()},
                                                              "qa4": s(r[c]["qa4"])} for c in r}
    else:
        def put(name, dd, note):
            r = star_set(dd, MID)
            mm = {c: round(statistics.mean(man_month(len(dd[x][c]["changes"]), sum(y["loc_added"] for y in dd[x][c]["changes"]), MID)[0] for x in dd), 3) for c in r}
            alt[name] = {"note": note, "mean_man_months": mm,
                         **{c: {"sub": {a: s(b) for a, b in r[c]["sub"].items()}, "qa4": s(r[c]["qa4"])} for c in r}}
        # (a) S1: CoherentRegion hardware model counted as a shared change of Publish/Visibility protocol (+1 module, +4 LOC each; analytic)
        d1 = json.loads(json.dumps(scs))
        for c in ("C1", "C2"):
            d1["S1"][c]["changes"].append(dict(module="Publish/Visibility protocol (analytic)", shared=True, files=[], loc_added=4, module_size_loc=36))
        put("S1_coherent_region_counted_as_shared_module", d1, "analytic: +1 shared module, +4 LOC (config 2 + Params 2) for both candidates; size 36 = Sim.on_xfer+on_move_done+on_pinned")
        # (b) S3: C2 also needs its cacheline-packed entry layout extended (freq + reconstruction cost fields); analytic
        d2 = json.loads(json.dumps(scs))
        d2["S3"]["C2"]["changes"].append(dict(module="Shared metadata layout (analytic)", shared=False, files=[], loc_added=2, module_size_loc=15))
        put("S3_C2_entry_layout_extended", d2, "analytic: C2 +1 module, +2 LOC (two per-entry fields); C1 unchanged")
        # (c) S1 C2 grant protocol replacement regarded as a major interface change
        d3 = json.loads(json.dumps(scs))
        d3["S1"]["C2"]["major_interface_change"] = True
        put("S1_C2_flagged_major_interface_change", d3, "preregistration rule: M1 = one star for C2 (module count irrelevant)")
        # (d) all three analytic assumptions at once, against C1 (pessimistic for C2)
        d4 = json.loads(json.dumps(d2))
        for c in ("C1", "C2"):
            d4["S1"][c]["changes"].append(dict(module="Publish/Visibility protocol (analytic)", shared=True, files=[], loc_added=4, module_size_loc=36))
        d4["S1"]["C2"]["major_interface_change"] = True
        put("all_analytic_alternatives_together", d4, "(a)+(b)+(c)")
    out["sensitivity_structure_alternatives"] = alt
    # price/token break-even: T1 is cheaper in USD only if its token multiplier is below this
    be = {}
    for x in scs:
        for c in ("C1", "C2"):
            m = out["scenarios"][x][c]
            t1 = m["agent"]["T1_frontier"]["usd"] / PRICES["T1_frontier"]["mult"]   # USD at mult 1
            be[f"{x}_{c}"] = round(m["agent"]["T2_mid"]["usd"] / t1, 3) if t1 else None
    out["T1_break_even_token_multiplier"] = be
    if dp != "DP1":
        out["mean_over_scenarios_unrounded"] = {c: {
            "modules": statistics.mean(out["scenarios"][x][c]["modules"] for x in scs),
            "man_months": statistics.mean(man_month(out["scenarios"][x][c]["modules"], out["scenarios"][x][c]["loc_added"], MID)[0] for x in scs),
            "usd_T1": statistics.mean(agent(out["scenarios"][x][c]["modules"], out["scenarios"][x][c]["loc_added"], out["scenarios"][x][c]["module_size_loc"], MID, STAR_TIER)[1] for x in scs)}
            for c in ("C1", "C2")}
        out["major_interface_change_flags"] = {x: {c: bool(scs[x][c].get("major_interface_change")) for c in ("C1", "C2")} for x in scs}
    (DATA / "qa4_modifiability.json").write_text(json.dumps(out, ensure_ascii=False, indent=1))
    print(json.dumps({"qa4_stars": out["qa4_stars"], "sub_stars": out["sub_stars"]}, ensure_ascii=False))


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--dp", default="DP1", help="design point folder holding results/data/qa4_measured_counts.json (default DP1)")
    main(ap.parse_args().dp)
