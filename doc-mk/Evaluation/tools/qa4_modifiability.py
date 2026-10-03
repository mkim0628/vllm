#!/usr/bin/env python3
"""QA4 Modifiability: derive man-month and code-agent token cost from measured counts.

Usage (from repo root):
    python3 doc-mk/Evaluation/tools/qa4_modifiability.py

Input : DP1/results/data/qa4_measured_counts.json   (measured modules / LOC per scenario and candidate)
Output: DP1/results/data/qa4_modifiability.json
Formulas, constants and star thresholds are pre-registered in DP1/qa4-preregistration.md (sections 4, 5).
All constants below are ASSUMED (2026-10-03); prices change, edit PRICES and re-run.
"""
from __future__ import annotations

import itertools
import json
import statistics
from pathlib import Path

EVAL = Path(__file__).resolve().parents[1]
DATA = EVAL / "DP1" / "results" / "data"

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


def star_set(per_sc, k):
    """per_sc: {scenario: {cand: changes}} -> sub-stars (worst over scenarios) for each candidate."""
    res = {}
    for cand in ("C1", "C2"):
        m1, m2, m3 = [], [], []
        for sc, d in per_sc.items():
            ch = d[cand]["changes"]
            n = len(ch)
            m1.append(stars_le(n, *M1_T))
            m2.append(stars_le(man_month(n, sum(c["loc_added"] for c in ch), k)[0], *M2_T))
            m3.append(stars_le(agent(n, sum(c["loc_added"] for c in ch), sum(c["module_size_loc"] for c in ch),
                                     k, STAR_TIER)[1], *M3_T))
        sub = {"M1": min(m1), "M2": min(m2), "M3": min(m3)}
        res[cand] = {"sub": sub, "qa4": int(statistics.median(sub.values()))}
    return res


def s(n):
    return "★" * n


def main():
    src = json.loads((DATA / "qa4_measured_counts.json").read_text())
    scs = src["scenarios"]
    out = {"schema": "qa4_modifiability v1", "date": src["date"], "evidence": src["evidence"],
           "inputs": "DP1/results/data/qa4_measured_counts.json", "constants_mid": MID, "constants_low": LOW,
           "constants_high": HIGH, "prices_assumed_2026-10-03": PRICES, "thresholds": {
               "M1_modules": "<=2 ★★★, 3-5 ★★, >=6 ★", "M2_man_months": "<=0.5 ★★★, <=1.0 ★★, else ★",
               "M3_usd_T1": "<=3 ★★★, <=10 ★★, else ★", "qa4": "median of M1, M2, M3 stars"},
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

    # aggregation (worst scenario per sub-metric, QA4 = median of sub-stars)
    base = star_set(scs, MID)
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
    # sensitivity: module-count alternatives recorded in the counts file (analytic, not measured)
    alt = {}
    d1 = json.loads(json.dumps(scs))
    # S1 C2 with capability-class preference: drop the C2-only selector change
    d1["S1"]["C2"]["changes"] = [c for c in d1["S1"]["C2"]["changes"] if c["shared"]]
    # S4 with schema merged into Event Source
    for c in ("C1", "C2"):
        d1["S4"][c]["changes"] = [x for x in d1["S4"][c]["changes"] if not x["module"].startswith("Event/Migration")]
    r = star_set(d1, MID)
    alt["capclass_pref_and_event_schema_merged"] = {c: {"sub": {a: s(b) for a, b in r[c]["sub"].items()},
                                                          "qa4": s(r[c]["qa4"])} for c in r}
    out["sensitivity_structure_alternatives"] = alt
    # price/token break-even: T1 is cheaper in USD only if its token multiplier is below this
    be = {}
    for x in scs:
        for c in ("C1", "C2"):
            m = out["scenarios"][x][c]
            t1 = m["agent"]["T1_frontier"]["usd"] / PRICES["T1_frontier"]["mult"]   # USD at mult 1
            be[f"{x}_{c}"] = round(m["agent"]["T2_mid"]["usd"] / t1, 3) if t1 else None
    out["T1_break_even_token_multiplier"] = be
    (DATA / "qa4_modifiability.json").write_text(json.dumps(out, ensure_ascii=False, indent=1))
    print(json.dumps({"qa4_stars": out["qa4_stars"], "sub_stars": out["sub_stars"]}, ensure_ascii=False))


if __name__ == "__main__":
    main()
