#!/usr/bin/env python3
"""Aggregate DP3 simulation results -> results/data/dp3_summary.json (+ stdout tables).

Reads results/data/<SYS>/dp3_results.json (written by run_eval.py).  Star-level load = lam0 x 1.0.
Definitions (see ../simulation-plan.md section 2, ../../qa-star-criteria-unified.md):
  pair            = (scenario, system)
  comparison-valid= Baseline finished every request (unfinished == 0), >= MIN_N completed requests per run, and
                    the three policies are not all within 2% of each other on TTFT P99 and HBM (saturated).
  ratio (>1 good) = Baseline value / candidate value, per seed, then mean over seeds; pair set aggregated by geometric mean.
  loss            = candidate worse than Baseline and the 95% t-interval of the per-seed ratio lies fully below 1.
"""
from __future__ import annotations

import json
import math
import statistics as st
from pathlib import Path

HERE = Path(__file__).resolve().parent
DATA = HERE.parent / "results" / "data"
SYSTEMS = ("SYS-H100", "SYS-B200")
BASE, C1, C2 = "Baseline-As-Is", "C1-Offline", "C2-Online"
MIN_N = 10
T95 = {4: 2.776}   # df = seeds-1 = 4


def gm(xs):
    xs = [x for x in xs if x and math.isfinite(x) and x > 0]
    return math.exp(sum(math.log(x) for x in xs) / len(xs)) if xs else float("nan")


def ci_below_one(ratios):
    m = st.mean(ratios)
    h = T95[len(ratios) - 1] * st.stdev(ratios) / math.sqrt(len(ratios))
    return m + h < 1.0, m, h


def main():
    out = {"schema": "dp3_summary v1", "pairs": {}, "aggregate": {}, "losses": [], "excluded": []}
    per_pol = {C1: {k: [] for k in ("ttft", "tpot", "hbm")}, C2: {k: [] for k in ("ttft", "tpot", "hbm")}}
    absv = {p: {k: [] for k in ("ttft", "tpot", "hbm")} for p in (BASE, C1, C2)}
    fam = {}
    for sysid in SYSTEMS:
        d = json.loads((DATA / sysid / "dp3_results.json").read_text())
        out["git_rev_" + sysid] = d["git_rev"]
        for sid, sc in d["scenarios"].items():
            by = {}
            for r in sc["runs"]:
                if r["load"] == 1.0:
                    by.setdefault(r["policy"], {})[r["seed"]] = r
            seeds = sorted(by[BASE])
            ok = lambda v: v is not None and math.isfinite(v)
            b = [by[BASE][s] for s in seeds]
            reason = None
            if any(r["unfinished"] for r in b) or not all(ok(r["ttft_p99"]) for r in b):
                reason = "Baseline가 요청을 끝내지 못함(infeasible)"
            elif min(r["n"] for r in b) < MIN_N:
                reason = f"표본 부족(run당 완료 요청 <{MIN_N})"
            key = f"{sysid}/{sid}"
            ent = {"family": sc["family"], "ctx": sc["ctx_tokens"], "lam0": sc["lam0"], "valid": reason is None, "reason": reason, "pol": {}}
            for p in (BASE, C1, C2):
                rs = [by[p][s] for s in seeds]
                ent["pol"][p] = {k: (st.mean(r[k] for r in rs) if all(ok(r[k]) for r in rs) else None)
                                 for k in ("ttft_p50", "ttft_p99", "tpot_p99", "hbm_gib")}
                ent["pol"][p]["unfinished"] = sum(r["unfinished"] for r in rs)
            if reason is None:
                tt = [by[BASE][s]["ttft_p99"] for s in seeds]
                hb = [by[BASE][s]["hbm_gib"] for s in seeds]
                if all(abs(by[p][s]["ttft_p99"] / by[BASE][s]["ttft_p99"] - 1) < 0.02 and abs(by[p][s]["hbm_gib"] / by[BASE][s]["hbm_gib"] - 1) < 0.02
                       for p in (C1, C2) for s in seeds):
                    ent["valid"], ent["reason"] = False, "saturated(정책 간 차이 2% 미만)"
            out["pairs"][key] = ent
            if not ent["valid"]:
                out["excluded"].append((key, ent["reason"]))
                # candidate-only rows still reported in the per-pair table
                continue
            for p in (BASE, C1, C2):
                for k, kk in (("ttft", "ttft_p99"), ("tpot", "tpot_p99"), ("hbm", "hbm_gib")):
                    absv[p][k].append(ent["pol"][p][kk])
            for p in (C1, C2):
                for k, kk in (("ttft", "ttft_p99"), ("tpot", "tpot_p99"), ("hbm", "hbm_gib")):
                    rat = [by[BASE][s][kk] / by[p][s][kk] for s in seeds]
                    per_pol[p][k].append(st.mean(rat))
                    fam.setdefault((p, k, sc["family"]), []).append(st.mean(rat))
                    below, m, h = ci_below_one(rat)
                    if below:
                        out["losses"].append(dict(pair=key, policy=p, metric=kk, ratio=round(m, 3), ci95=round(h, 3)))
    for p in (C1, C2):
        out["aggregate"][p] = {k: dict(ratio_gm=gm(v), n=len(v), wins=sum(x > 1.0 for x in v)) for k, v in per_pol[p].items()}
        out["aggregate"][p]["by_family"] = {f"{k}/{f}": gm(v) for (pp, k, f), v in fam.items() if pp == p}
        # QA2 combined ratio r = geomean(TTFT ratio, TPOT ratio) per pair, then geomean over pairs
        n = min(len(per_pol[p]["ttft"]), len(per_pol[p]["tpot"]))
        out["aggregate"][p]["qa2_r"] = gm([math.sqrt(a * b) for a, b in zip(per_pol[p]["ttft"], per_pol[p]["tpot"])])
    for p in (BASE, C1, C2):
        out["aggregate"].setdefault("abs", {})[p] = {k: gm(v) for k, v in absv[p].items()}
    (DATA / "dp3_summary.json").write_text(json.dumps(out, indent=1, ensure_ascii=False, default=lambda x: None if isinstance(x, float) and math.isnan(x) else x))
    print("valid pairs:", sum(e["valid"] for e in out["pairs"].values()), "/", len(out["pairs"]))
    for k, r in out["excluded"]:
        print("  excluded", k, r)
    for p in (C1, C2):
        print(p, json.dumps(out["aggregate"][p], ensure_ascii=False, indent=None))
    print("abs gm", json.dumps(out["aggregate"]["abs"]))
    print("losses:", len(out["losses"]))
    for l in out["losses"]:
        print("  ", l)


if __name__ == "__main__":
    main()
