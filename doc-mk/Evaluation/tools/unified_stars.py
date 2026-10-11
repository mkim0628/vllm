#!/usr/bin/env python3
"""Unified star rules v2 (all DPs) and consistency check against previously reported stars.

    python doc-mk/Evaluation/tools/unified_stars.py [--out doc-mk/Evaluation/unified_stars_check.md]

Inputs: tools/unified_inputs.json (values copied from each DP's result deck / doc, with provenance) and, for QA4 of DP1 and DP2,
the per-scenario measurements in DP1|DP2/results/data/qa4_modifiability.json (means over scenarios are computed here, not typed).
Rules: see doc-mk/Evaluation/qa-star-criteria-unified.md.  v2 = v1 with (1) QA1 3-star bound 2.0, (2) QA2 = absolute SLO level AND improvement
vs Baseline combined, (3) QA4 = weighted score S.  v1 functions are kept (v1_*) only to print what changed.  Nothing here rescales a measured value.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
EVAL = HERE.parent

# ---------------------------------------------------------------- rules (v2)
QA1_HI, QA1_LO = 2.0, 0.97                  # Max SLO goodput / Baseline  (v1: 1.30)
QA2_T = ((2000.0, 50.0), (4000.0, 100.0))   # absolute level A: (TTFT P99 ms, TPOT P99 ms) for 3 / 2 stars
QA2_R = (1.20, 0.90)                        # improvement R: r = sqrt(TTFT_base/TTFT * TPOT_base/TPOT), 3 / 2 stars
QA3_HI, QA3_LO = 1.25, 0.95                 # HBM reduction multiple = Baseline / candidate
QA4_REF = (0.5, 0.5, 2.0)                   # reference = 3-star bound of each sub-metric: USD(T2), man-month, modules
QA4_W = (0.5, 0.3, 0.2)                     # cost, effort, modules (order of importance)
QA4_S = (1.0, 3.2)                          # S <= 1.0 -> 3 stars, S <= 3.2 -> 2 stars (3.2 = score of the 2-star bound 2.0/1.0/6)
QA5_T = (1.0, 3.0)                          # relative F1 drop (%) vs pre-compression + full recompute
QA6_T = (90.0, 70.0)                        # SE(N_max) percent
MD_PER_MM = 21.0


def half_up(x):
    return int(x + 0.5 + 1e-9)


def qa1(r):
    return 3 if r >= QA1_HI else 2 if r >= QA1_LO else 1


def v1_qa1(r):
    return 3 if r >= 1.30 else 2 if r >= QA1_LO else 1


def qa2_abs(ttft_ms, tpot_ms):
    def lvl(v, t3, t2):
        return 3 if v <= t3 else 2 if v <= t2 else 1
    return min(lvl(ttft_ms, QA2_T[0][0], QA2_T[1][0]), lvl(tpot_ms, QA2_T[0][1], QA2_T[1][1]))


def qa2_r(base_ttft, base_tpot, ttft, tpot):
    return ((base_ttft / ttft) * (base_tpot / tpot)) ** 0.5


def qa2_imp(r):
    return 3 if r >= QA2_R[0] else 2 if r >= QA2_R[1] else 1


def qa2(ttft_ms, tpot_ms, r):
    """QA2 = round-half-up of the mean of the absolute-SLO level A and the improvement level R."""
    return half_up((qa2_abs(ttft_ms, tpot_ms) + qa2_imp(r)) / 2)


def v1_qa2(ttft_ms, tpot_ms):
    return qa2_abs(ttft_ms, tpot_ms)


def qa3(base, cand):
    red = base / cand
    return 3 if red >= QA3_HI else 2 if red >= QA3_LO else 1


def qa4_score(usd_t2, mm, modules):
    return sum(w * v / ref for w, v, ref in zip(QA4_W, (usd_t2, mm, modules), QA4_REF))


def qa4(usd_t2, mm, modules):
    sc = qa4_score(usd_t2, mm, modules)
    return 3 if sc <= QA4_S[0] else 2 if sc <= QA4_S[1] else 1


def v1_qa4(usd_t2, mm, modules):
    c = 3 if usd_t2 <= 0.5 else 2 if usd_t2 <= 2.0 else 1
    e = 3 if mm <= 0.5 else 2 if mm <= 1.0 else 1
    m = 3 if modules <= 2.0 else 2 if modules < 6.0 else 1
    for s in (3, 2):
        if sum(w for w, v in zip(QA4_W, (c, e, m)) if v >= s) > 0.5 + 1e-12:
            return s
    return 1


def qa5(drop_pct):
    return 3 if drop_pct <= QA5_T[0] else 2 if drop_pct <= QA5_T[1] else 1


def qa6(se):
    return 3 if se >= QA6_T[0] else 2 if se >= QA6_T[1] else 1


def S(n):
    return "★" * n + "☆" * (3 - n)


# ---------------------------------------------------------------- data
def qa4_from_json(dp):
    d = json.load(open(EVAL / dp / "results" / "data" / "qa4_modifiability.json"))
    out = {}
    for c in ("C1", "C2"):
        sc = [v[c] for v in d["scenarios"].values()]
        n = len(sc)
        out[c] = dict(modules=sum(s["modules"] for s in sc) / n, mm=sum(s["man_months"] for s in sc) / n,
                      usd_t2=sum(s["agent"]["T2_mid"]["usd"] for s in sc) / n, usd_t1=sum(s["agent"]["T1_frontier"]["usd"] for s in sc) / n, n=n)
    return out


def load():
    inp = json.load(open(HERE / "unified_inputs.json"))
    for dp in ("DP1", "DP2"):
        q = qa4_from_json(dp)
        for c in ("C1", "C2"):
            inp[dp]["values"][c]["qa4"] = q[c]
    # DP3: simulation summary (aggregated by DP3/sim/aggregate.py) and, if present, the QA5 file
    sm = json.load(open(EVAL / "DP3" / "results" / "data" / "dp3_summary.json"))
    ag = sm["aggregate"]
    b = ag["abs"]["Baseline-As-Is"]
    inp["DP3"]["baseline"] = dict(ttft_p99_ms=b["ttft"] * 1e3, tpot_p99_ms=b["tpot"] * 1e3, hbm_gib=b["hbm"])
    for c, pol in (("C1", "C1-Offline"), ("C2", "C2-Online")):
        a = ag["abs"][pol]
        inp["DP3"]["values"][c] = dict(ttft_p99_ms=a["ttft"] * 1e3, tpot_p99_ms=a["tpot"] * 1e3, hbm_gib=a["hbm"],
                                       qa2_r=ag[pol]["qa2_r"], qa3_ratio=ag[pol]["hbm"]["ratio_gm"], n_pairs=ag[pol]["ttft"]["n"])
    q5 = EVAL / "DP3" / "results" / "data" / "dp3_qa5.json"
    if q5.exists():
        q = json.load(open(q5))
        if q["_meta"]["n_examples"] >= q["_meta"]["min_examples"]:      # below the minimum sample, QA5 stays unevaluated
            for c in ("C1", "C2"):
                inp["DP3"]["values"][c]["f1_drop_pct"] = q[c]["f1_drop_pct"]
    # DP4: values reported in man-days and T2 USD; convert effort to MM
    for c, v in inp["DP4"]["values"].items():
        for k in ("qa4_equal", "qa4_weighted"):
            v[k]["mm"] = v[k]["man_days"] / MD_PER_MM
    return inp


def qa2_ratio(d, v):
    if "qa2_r" in v:
        return v["qa2_r"]
    b = d["baseline"]
    return qa2_r(b["ttft_p99_ms"], b["tpot_p99_ms"], v["ttft_p99_ms"], v["tpot_p99_ms"])


def evaluate(inp):
    res = {}
    for dp, d in inp.items():
        if dp.startswith("_"):
            continue
        res[dp] = {}
        for c, v in d["values"].items():
            st = {}
            if "qa1_ratio" in v:
                st["QA1"] = qa1(v["qa1_ratio"])
            if "ttft_p99_ms" in v:
                st["QA2"] = qa2(v["ttft_p99_ms"], v["tpot_p99_ms"], qa2_ratio(d, v))
            if "qa3_ratio" in v:
                st["QA3"] = 3 if v["qa3_ratio"] >= QA3_HI else 2 if v["qa3_ratio"] >= QA3_LO else 1
            elif "hbm_gib" in v:
                st["QA3"] = qa3(d["baseline"]["hbm_gib"], v["hbm_gib"])
            q4 = v.get("qa4") or v.get("qa4_equal")
            if q4:
                st["QA4"] = qa4(q4["usd_t2"], q4["mm"], q4["modules"])
            if "f1_drop_pct" in v:
                st["QA5"] = qa5(v["f1_drop_pct"])
            if "se16_pct" in v:
                st["QA6"] = qa6(v["se16_pct"])
            res[dp][c] = st
    return res


def v1_stars(inp):
    """Stars under the v1 rules, to print what v2 changed."""
    out = {}
    for dp, d in inp.items():
        if dp.startswith("_"):
            continue
        for c, v in d["values"].items():
            o = {}
            if "qa1_ratio" in v:
                o["QA1"] = v1_qa1(v["qa1_ratio"])
            if "ttft_p99_ms" in v:
                o["QA2"] = v1_qa2(v["ttft_p99_ms"], v["tpot_p99_ms"])
            q4 = v.get("qa4") or v.get("qa4_equal")
            if q4:
                o["QA4"] = v1_qa4(q4["usd_t2"], q4["mm"], q4["modules"])
            out[(dp, c)] = o
    return out


def v1_vs_v2(inp, res):
    v1 = v1_stars(inp)
    L = ["| DP | 후보 | QA | v1 별 | v2 별 | 이유 |", "|---|---|---|---|---|---|"]
    for (dp, c), o in v1.items():
        for qa, s1 in o.items():
            s2 = res[dp][c][qa]
            if s1 != s2:
                v = inp[dp]["values"][c]
                why = {"QA1": f"R={v.get('qa1_ratio', 0):.3f} < 2.0 (v1 경계 1.30)",
                       "QA2": f"절대 SLO 등급과 개선 등급을 평균 (개선 r={qa2_ratio(inp[dp], v):.2f})" if "ttft_p99_ms" in v else "",
                       "QA4": "가중 점수 S"}[qa]
                L.append(f"| {dp} | {c} | {qa} | {S(s1)} | {S(s2)} | {why} |")
    return "\n".join(L) if len(L) > 2 else "(바뀐 별 없음)"


def md_table(inp, res):
    L = []
    L.append("| DP | 후보 | QA | 값 | 기존 별 | 공통 기준 v2 별 | 일치 |")
    L.append("|---|---|---|---|---|---|---|")
    tot_prev, tot_new = {}, {}
    for dp, d in inp.items():
        if dp.startswith("_"):
            continue
        for c, v in d["values"].items():
            for qa, new in res[dp][c].items():
                prev = d.get("previous_stars", {}).get(c, {}).get(qa)
                val = fmt_value(dp, c, qa, v, d)
                ok = "O" if prev == new else ("N/A" if prev is None else "**X**")
                L.append(f"| {dp} | {c} | {qa} | {val} | {S(prev) if prev else '—'} | {S(new)} | {ok} |")
                if prev is not None:
                    tot_prev[(dp, c)] = tot_prev.get((dp, c), 0) + prev
                tot_new[(dp, c)] = tot_new.get((dp, c), 0) + new
    L.append("")
    L.append("| DP | 후보 | 별 합계(기존, 비교 가능 QA) | 별 합계(공통 기준 v2) | 일치 |")
    L.append("|---|---|---:|---:|---|")
    for k in tot_new:
        L.append(f"| {k[0]} | {k[1]} | {tot_prev.get(k, '—')} | {tot_new[k]} | {'O' if tot_prev.get(k) == tot_new[k] else ('N/A' if tot_prev.get(k) is None else '**X**')} |")
    return "\n".join(L), tot_prev, tot_new


def fmt_value(dp, c, qa, v, d):
    if qa == "QA1":
        return f"{v['qa1_tps']:,.0f} tok/s (x{v['qa1_ratio']:.3f})" if "qa1_tps" in v else f"x{v['qa1_ratio']:.3f}"
    if qa == "QA2":
        return f"TTFT P99 {v['ttft_p99_ms']:,.0f} ms · TPOT P99 {v['tpot_p99_ms']:.1f} ms · A{qa2_abs(v['ttft_p99_ms'], v['tpot_p99_ms'])}/R{qa2_imp(qa2_ratio(d, v))} (r={qa2_ratio(d, v):.2f})"
    if qa == "QA3":
        red = v.get("qa3_ratio") or d["baseline"]["hbm_gib"] / v["hbm_gib"]
        return f"HBM {v['hbm_gib']:.1f} GiB (감소 배수 {red:.2f})"
    if qa == "QA4":
        q = v.get("qa4") or v["qa4_equal"]
        return f"${q['usd_t2']:.2f} · {q['mm']:.2f} MM · {q['modules']:.2f} module → S={qa4_score(q['usd_t2'], q['mm'], q['modules']):.2f}"
    if qa == "QA5":
        return f"F1 하락 {v['f1_drop_pct']}%"
    if qa == "QA6":
        return f"SE(16) {v['se16_pct']}%"
    return ""


def sensitivity(inp, res):
    L = []
    ratios = sorted((v["qa1_ratio"], dp, c) for dp, d in inp.items() if not dp.startswith("_") for c, v in d["values"].items() if "qa1_ratio" in v)
    L.append("- QA1 보고된 R 값(오름차순): " + ", ".join(f"{dp} {c} {r:.3f}" for r, dp, c in ratios) + f" — ★★★(R≥{QA1_HI}) 도달 후보: " +
             (", ".join(f"{dp} {c}" for r, dp, c in ratios if r >= QA1_HI) or "없음"))
    L.append(f"- QA1 DP1 C1(보완 버전 = C1+Affinity)은 R=1.2976이라 '×1.3'으로 반올림되지만 v1 경계 1.30에서도 0.2% 아래라 ★★이다. v2(2.0)에서도 ★★.")
    for dp, d in inp.items():
        if dp.startswith("_"):
            continue
        for c, v in d["values"].items():
            if "ttft_p99_ms" in v:
                r = qa2_ratio(d, v)
                L.append(f"- QA2 {dp} {c}: r={r:.3f} (R 경계 {QA2_R[0]}/{QA2_R[1]}까지 {r/QA2_R[0]-1:+.1%}/{r/QA2_R[1]-1:+.1%}), A={qa2_abs(v['ttft_p99_ms'], v['tpot_p99_ms'])}, R={qa2_imp(r)}")
    # admissible QA2 R windows that keep every previous star
    for dp, d in inp.items():
        if dp.startswith("_"):
            continue
        for c, v in d["values"].items():
            q4 = v.get("qa4") or v.get("qa4_equal")
            if q4:
                L.append(f"- QA4 {dp} {c}: S={qa4_score(q4['usd_t2'], q4['mm'], q4['modules']):.2f} (★★★ ≤{QA4_S[0]}, ★★ ≤{QA4_S[1]})")
    if "DP4" in inp:
        for c, v in inp["DP4"]["values"].items():
            w = v["qa4_weighted"]
            L.append(f"- DP4 {c} QA4 (S2~S4 가중 2 원 값): S={qa4_score(w['usd_t2'], w['mm'], w['modules']):.2f} → {S(qa4(w['usd_t2'], w['mm'], w['modules']))}")
    return L


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", type=Path, default=EVAL / "unified_stars_check.md")
    a = ap.parse_args()
    inp = load()
    res = evaluate(inp)
    table, tp, tn = md_table(inp, res)
    lines = ["# 공통 별 기준 v2 적용 점검 (자동 생성, 직접 편집 금지)", "",
             "> 생성: `python doc-mk/Evaluation/tools/unified_stars.py`. 규칙은 `qa-star-criteria-unified.md`. 값은 `tools/unified_inputs.json`(출처 기록), DP1·DP2 `results/data/qa4_modifiability.json`, DP3 `results/data/dp3_summary.json`.", "",
             "## 1. 기존 별과 공통 기준 v2 별의 비교", "", table, "", "## 2. v1 → v2에서 바뀐 별", "", v1_vs_v2(inp, res), "", "## 3. 민감도·경계 근접", ""]
    lines += sensitivity(inp, res)
    a.out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("\n".join(lines))
    bad = [k for k in tn if tp.get(k) is not None and tp[k] != tn[k]]
    print("\nTOTALS_CHANGED:", bad or "none")


if __name__ == "__main__":
    main()
