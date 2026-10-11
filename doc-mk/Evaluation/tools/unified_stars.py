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
import math
from pathlib import Path

HERE = Path(__file__).resolve().parent
EVAL = HERE.parent

# ---------------------------------------------------------------- rules (v3)
QA1_HI, QA1_LO = 4.0 / 3.0, 0.97           # Max SLO goodput / Baseline (v2: 2.0, v1: 1.30)
QA2_SLO = (2000.0, 50.0)                    # TTFT P99 ms, TPOT P99 ms: exceeding either caps the star at 1
QA2_R = (1.20, 0.90)                        # improvement r = sqrt(TTFT_base/TTFT * TPOT_base/TPOT): 3 / 2 stars
QA3_HI, QA3_LO = 1.25, 0.95                 # HBM reduction multiple = Baseline / candidate
QA4_COST = (0.5, 2.0)                       # USD (mid tier) per change: <= -> 3 / 2 stars
QA4_MM = (0.5, 1.0)                         # man-month per change
QA4_MOD = (2.0, 6.0)                        # modules: <= 2 -> 3, < 6 -> 2
QA5_T = (1.0, 3.0)                          # relative F1 drop (%) vs pre-compression + full recompute
QA6_T = (90.0, 70.0)                        # SE(N_max) percent
MD_PER_MM = 21.0


def half_up(x):
    return int(x + 0.5 + 1e-9)


def qa1(r):
    return 3 if r >= QA1_HI else 2 if r >= QA1_LO else 1


def v2_qa1(r):
    return 3 if r >= 2.0 else 2 if r >= 0.97 else 1


def qa2_slo_ok(ttft_ms, tpot_ms):
    return ttft_ms <= QA2_SLO[0] and tpot_ms <= QA2_SLO[1]


def qa2_r(base_ttft, base_tpot, ttft, tpot):
    return ((base_ttft / ttft) * (base_tpot / tpot)) ** 0.5


def qa2_imp(r):
    return 3 if r >= QA2_R[0] else 2 if r >= QA2_R[1] else 1


def qa2(ttft_ms, tpot_ms, r):
    """QA2 = star from the improvement over Baseline; capped at 1 star if TTFT P99 > 2 s or TPOT P99 > 50 ms."""
    return qa2_imp(r) if qa2_slo_ok(ttft_ms, tpot_ms) else 1


def v2_qa2(ttft_ms, tpot_ms, r):
    a = 3 if (ttft_ms <= 2000 and tpot_ms <= 50) else 2 if (ttft_ms <= 4000 and tpot_ms <= 100) else 1
    return half_up((a + qa2_imp(r)) / 2)


def v1_qa2(ttft_ms, tpot_ms):
    return 3 if (ttft_ms <= 2000 and tpot_ms <= 50) else 2 if (ttft_ms <= 4000 and tpot_ms <= 100) else 1


def qa3(base, cand):
    red = base / cand
    return 3 if red >= QA3_HI else 2 if red >= QA3_LO else 1


def qa4_subs(usd_t2, mm, modules):
    c = 3 if usd_t2 <= QA4_COST[0] else 2 if usd_t2 <= QA4_COST[1] else 1
    e = 3 if mm <= QA4_MM[0] else 2 if mm <= QA4_MM[1] else 1
    m = 3 if modules <= QA4_MOD[0] else 2 if modules < QA4_MOD[1] else 1
    return c, e, m


def qa4(usd_t2, mm, modules):
    """AND rule: a star is earned only if all three sub-metrics reach it (= the minimum sub-star)."""
    return min(qa4_subs(usd_t2, mm, modules))


def v2_qa4(usd_t2, mm, modules):
    sc = qa4_score(usd_t2, mm, modules)
    return 3 if sc <= 1.0 else 2 if sc <= 3.2 else 1


def qa4_score(usd_t2, mm, modules):
    """Diagnostic only (v2 weighted score, not used for stars)."""
    return 0.5 * usd_t2 / 0.5 + 0.3 * mm / 0.5 + 0.2 * modules / 2.0


def qa5(drop_pct):
    return 3 if drop_pct <= QA5_T[0] else 2 if drop_pct <= QA5_T[1] else 1


def qa6(se):
    return 3 if se >= QA6_T[0] else 2 if se >= QA6_T[1] else 1


PRIORITY = {"DP1": ["QA1", "QA2", "QA3", "QA4"], "DP2": ["QA1", "QA3", "QA2", "QA4"], "DP3": ["QA2", "QA5", "QA1", "QA3"], "DP4": ["QA1", "QA2", "QA4", "QA6"]}   # DP2/DP3: proposals


def select(dp, res):
    """Higher star total wins; a tie is broken by the DP's QA priority (SKILL H13). Returns (winner or None, totals, how)."""
    tot = {c: sum(v.values()) for c, v in res[dp].items()}
    best = max(tot.values())
    top = [c for c, t in tot.items() if t == best]
    if len(top) == 1:
        return top[0], tot, "합계"
    for qa in PRIORITY[dp]:
        vals = {c: res[dp][c].get(qa, 0) for c in top}
        if len(set(vals.values())) > 1:
            m = max(vals.values())
            w = [c for c in top if vals[c] == m]
            if len(w) == 1:
                return w[0], tot, f"동점 → {qa}"
            top = w
    return None, tot, "동점, 우선순위로도 못 가름"


def S(n):
    return "★" * n + "☆" * (3 - n)


# ---------------------------------------------------------------- data
def qa4_from_json(dp, path=None):
    d = json.load(open(path or (EVAL / dp / "results" / "data" / "qa4_modifiability.json")))
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
    inp["DP1-1안"]["values"]["C1"]["qa4"] = inp["DP1"]["values"]["C1"]["qa4"]   # PPT 3장은 1안에 C1과 같은 QA4 값을 표기
    # DP2: node-internal evaluation (2026-10-11 owner: DP2 decides inside one node). Source = DP2/results/data/arch/qa_result.json
    # (candidates A-Dispatcher = 1안 scheduling-time decision / Client-Dispatcher, B-Blackboard = 2안 pre-plan / Shared Repository).
    # QA4 (owner 2026-10-11: added back) comes from the node-internal change scenarios (qa4_modifiability.json, S1-S4).
    # QA3 uses hbm_save over the equal-performance pairs of that candidate.
    qa = json.load(open(EVAL / "DP2" / "results" / "data" / "arch" / "qa_result.json"))
    t = qa["tables"]["combined"]
    bl = t["Baseline-GPU-local"]
    inp["DP2"]["source"] = "DP2/results/2026-10-10_dp2-arch-styles.md, data/arch/qa_result.json (노드 내 결정, H100+B200 통합, comparison-valid 21쌍)"
    inp["DP2"]["baseline"] = dict(tps=bl["qa1_abs"], ttft_p99_ms=bl["ttft_p99"] * 1e3, tpot_p99_ms=bl["tpot_p99"] * 1e3, hbm_gib=bl["hbm_abs_gib"])
    inp["DP2"]["values"] = {}
    for c, key in (("C1", "A-Dispatcher"), ("C2", "B-Blackboard")):
        v = t[key]
        inp["DP2"]["values"][c] = dict(qa1_tps=v["qa1_abs"], qa1_ratio=v["qa1_ratio"], ttft_p99_ms=v["ttft_p99"] * 1e3, tpot_p99_ms=v["tpot_p99"] * 1e3,
                                       hbm_gib=v["hbm_abs_gib"], hbm_base_gib=v["hbm_base_gib"], qa3_ratio=v["hbm_save"], hbm_n_eq=v["hbm_n_eq"])
    q4 = qa4_from_json("DP2", EVAL / "DP2" / "results" / "data" / "arch" / "qa4_modifiability.json")
    for c in ("C1", "C2"):
        inp["DP2"]["values"][c]["qa4"] = q4[c]
    inp["DP2"]["previous_stars"] = {"C1": {"QA1": 2, "QA2": 2, "QA3": 2, "QA4": 3}, "C2": {"QA1": 2, "QA2": 1, "QA3": 2, "QA4": 3}}   # 10-10 document
    # DP3: simulation summary (aggregated by DP3/sim/aggregate.py) and, if present, the QA5 file
    sm = json.load(open(EVAL / "DP3" / "results" / "data" / "dp3_summary.json"))
    ag = sm["aggregate"]
    b = ag["abs"]["Baseline-As-Is"]
    inp["DP3"]["baseline"] = dict(ttft_p99_ms=b["ttft"] * 1e3, tpot_p99_ms=b["tpot"] * 1e3, hbm_gib=b["hbm"])
    for c, pol in (("C1", "C1-Offline"), ("C2", "C2-Online")):
        a = ag["abs"][pol]
        inp["DP3"]["values"][c] = dict(ttft_p99_ms=a["ttft"] * 1e3, tpot_p99_ms=a["tpot"] * 1e3, hbm_gib=a["hbm"],
                                       qa2_r=ag[pol]["qa2_r"], qa3_ratio=ag[pol]["hbm"]["ratio_gm"], n_pairs=ag[pol]["ttft"]["n"])
    q1p = EVAL / "DP3" / "results" / "data" / "dp3_qa1.json"       # QA1 added 2026-10-11 (registered in DP3/simulation-plan.md change log)
    if q1p.exists():
        q1 = json.load(open(q1p))["pairs"]
        valid = [k for k, e in sm["pairs"].items() if e["valid"] and q1[k]["Baseline-As-Is"]["max_goodput"] > 0]
        gm = lambda x: math.exp(sum(math.log(a) for a in x) / len(x))
        inp["DP3"]["baseline"]["tps"] = gm([q1[k]["Baseline-As-Is"]["max_goodput"] for k in valid])
        for c, pol in (("C1", "C1-Offline"), ("C2", "C2-Online")):
            inp["DP3"]["values"][c]["qa1_tps"] = gm([q1[k][pol]["max_goodput"] for k in valid])
            inp["DP3"]["values"][c]["qa1_ratio"] = gm([q1[k][pol]["max_goodput"] / q1[k]["Baseline-As-Is"]["max_goodput"] for k in valid])
            inp["DP3"]["values"][c]["qa1_n"] = len(valid)
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
    """Stars under the previously published v2 rules (QA1 2.0, QA2 A+R average, QA4 weighted score), to print what v3 changed."""
    out = {}
    for dp, d in inp.items():
        if dp.startswith("_"):
            continue
        for c, v in d["values"].items():
            o = {}
            if "qa1_ratio" in v:
                o["QA1"] = v2_qa1(v["qa1_ratio"])
            if "ttft_p99_ms" in v:
                o["QA2"] = v2_qa2(v["ttft_p99_ms"], v["tpot_p99_ms"], qa2_ratio(d, v))
            q4 = v.get("qa4") or v.get("qa4_equal")
            if q4:
                o["QA4"] = v2_qa4(q4["usd_t2"], q4["mm"], q4["modules"])
            out[(dp, c)] = o
    return out


def v1_vs_v2(inp, res):
    v1 = v1_stars(inp)
    L = ["| DP | 후보 | QA | v2 별 | v3 별 | 이유 |", "|---|---|---|---|---|---|"]
    for (dp, c), o in v1.items():
        for qa, s1 in o.items():
            s2 = res[dp][c][qa]
            if s1 != s2:
                v = inp[dp]["values"][c]
                why = {"QA1": f"R={v.get('qa1_ratio', 0):.3f} (★★★ 경계 2.0 → 4/3)",
                       "QA2": f"개선 r={qa2_ratio(inp[dp], v):.2f}, TTFT {v.get('ttft_p99_ms', 0):,.0f} ms / TPOT {v.get('tpot_p99_ms', 0):.1f} ms (SLO 초과 시 ★)" if "ttft_p99_ms" in v else "",
                       "QA4": "세 지표 AND 조건 (최소 sub-star)"}[qa]
                L.append(f"| {dp} | {c} | {qa} | {S(s1)} | {S(s2)} | {why} |")
    return "\n".join(L) if len(L) > 2 else "(바뀐 별 없음)"


def md_table(inp, res):
    L = []
    L.append("| DP | 후보 | QA | 값 | 기존 별 | 공통 기준 v3 별 | 일치 |")
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
    L.append("| DP | 후보 | 별 합계(기존, 비교 가능 QA) | 별 합계(공통 기준 v3) | 일치 |")
    L.append("|---|---|---:|---:|---|")
    for k in tot_new:
        L.append(f"| {k[0]} | {k[1]} | {tot_prev.get(k, '—')} | {tot_new[k]} | {'O' if tot_prev.get(k) == tot_new[k] else ('N/A' if tot_prev.get(k) is None else '**X**')} |")
    return "\n".join(L), tot_prev, tot_new


def fmt_value(dp, c, qa, v, d):
    if qa == "QA1":
        return f"{v['qa1_tps']:,.0f} tok/s (x{v['qa1_ratio']:.3f})" if "qa1_tps" in v else f"x{v['qa1_ratio']:.3f}"
    if qa == "QA2":
        return f"TTFT P99 {v['ttft_p99_ms']:,.0f} ms · TPOT P99 {v['tpot_p99_ms']:.1f} ms · r={qa2_ratio(d, v):.2f}{'' if qa2_slo_ok(v['ttft_p99_ms'], v['tpot_p99_ms']) else ' · SLO 초과'}"
    if qa == "QA3":
        red = v.get("qa3_ratio") or d["baseline"]["hbm_gib"] / v["hbm_gib"]
        return f"HBM {v['hbm_gib']:.1f} GiB (감소 배수 {red:.2f})"
    if qa == "QA4":
        q = v.get("qa4") or v["qa4_equal"]
        return f"${q['usd_t2']:.2f} · {q['mm']:.2f} MM · {q['modules']:.2f} module → sub {'/'.join(S(x) for x in qa4_subs(q['usd_t2'], q['mm'], q['modules']))}"
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
                L.append(f"- QA2 {dp} {c}: r={r:.3f} (R 경계 {QA2_R[0]}/{QA2_R[1]}까지 {r/QA2_R[0]-1:+.1%}/{r/QA2_R[1]-1:+.1%}), SLO {'충족' if qa2_slo_ok(v['ttft_p99_ms'], v['tpot_p99_ms']) else '초과(★)'}, R={qa2_imp(r)}")
    # admissible QA2 R windows that keep every previous star
    for dp, d in inp.items():
        if dp.startswith("_"):
            continue
        for c, v in d["values"].items():
            q4 = v.get("qa4") or v.get("qa4_equal")
            if q4:
                L.append(f"- QA4 {dp} {c}: 비용/공수/module sub-star = {'/'.join(S(x) for x in qa4_subs(q4['usd_t2'], q4['mm'], q4['modules']))} (AND 조건 → {S(qa4(q4['usd_t2'], q4['mm'], q4['modules']))})")
    if "DP4" in inp:
        for c, v in inp["DP4"]["values"].items():
            w = v["qa4_weighted"]
            L.append(f"- DP4 {c} QA4 (PPT 원 값, S2~S4 가중 2): sub {'/'.join(S(x) for x in qa4_subs(w['usd_t2'], w['mm'], w['modules']))} → {S(qa4(w['usd_t2'], w['mm'], w['modules']))}")
    return L


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", type=Path, default=EVAL / "unified_stars_check.md")
    a = ap.parse_args()
    inp = load()
    res = evaluate(inp)
    table, tp, tn = md_table(inp, res)
    lines = ["# 공통 별 기준 v3 적용 점검 (자동 생성, 직접 편집 금지)", "",
             "> 생성: `python doc-mk/Evaluation/tools/unified_stars.py`. 규칙은 `qa-star-criteria-unified.md`. 값은 `tools/unified_inputs.json`(출처 기록), DP1·DP2 `results/data/qa4_modifiability.json`, DP3 `results/data/dp3_summary.json`.", "",
             "## 1. 기존 별과 공통 기준 v3 별의 비교", "", table, "", "## 2. v2 → v3에서 바뀐 별", "", v1_vs_v2(inp, res), "", "## 3. 민감도·경계 근접", ""]
    lines += sensitivity(inp, res)
    a.out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("\n".join(lines))
    bad = [k for k in tn if tp.get(k) is not None and tp[k] != tn[k]]
    print("\nTOTALS_CHANGED:", bad or "none")


if __name__ == "__main__":
    main()
