#!/usr/bin/env python3
"""Unified star rules v1 (all DPs) and consistency check against previously reported stars.

    python doc-mk/Evaluation/tools/unified_stars.py [--out doc-mk/Evaluation/unified_stars_check.md]

Inputs: tools/unified_inputs.json (values copied from each DP's result deck / doc, with provenance) and, for QA4 of DP1 and DP2,
the per-scenario measurements in DP1|DP2/results/data/qa4_modifiability.json (means over scenarios are computed here, not typed).
Rules: see doc-mk/Evaluation/qa-star-criteria-unified.md. Nothing here changes a threshold after seeing results; it only
applies the v1 thresholds to the reported values and compares the stars with the previously reported ones.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
EVAL = HERE.parent

# ---------------------------------------------------------------- rules (v1)
QA1_HI, QA1_LO = 1.30, 0.97                 # Max SLO goodput / Baseline
QA2_T = ((2000.0, 50.0), (4000.0, 100.0))   # (TTFT P99 ms, TPOT P99 ms) for 3 / 2 stars
QA3_HI, QA3_LO = 1.25, 0.95                 # HBM reduction multiple = Baseline / candidate
QA4_COST = (0.5, 2.0)                       # T2 (mid tier) USD per change
QA4_MM = (0.5, 1.0)                         # man-month per change (1 MM = 21 man-days)
QA4_MOD = (2.0, 6.0)                        # modules: <=2 -> 3, <6 -> 2, else 1
QA4_W = (0.5, 0.3, 0.2)                     # cost, effort, modules
QA5_T = (1.0, 3.0)                          # relative F1 drop (%) vs pre-compression + full recompute
QA6_T = (90.0, 70.0)                        # SE(N_max) percent
MD_PER_MM = 21.0


def qa1(r):
    return 3 if r >= QA1_HI else 2 if r >= QA1_LO else 1


def qa2(ttft_ms, tpot_ms):
    def lvl(v, t3, t2):
        return 3 if v <= t3 else 2 if v <= t2 else 1
    return min(lvl(ttft_ms, QA2_T[0][0], QA2_T[1][0]), lvl(tpot_ms, QA2_T[0][1], QA2_T[1][1]))


def qa3(base, cand):
    red = base / cand
    return 3 if red >= QA3_HI else 2 if red >= QA3_LO else 1


def qa4_subs(usd_t2, mm, modules):
    c = 3 if usd_t2 <= QA4_COST[0] else 2 if usd_t2 <= QA4_COST[1] else 1
    e = 3 if mm <= QA4_MM[0] else 2 if mm <= QA4_MM[1] else 1
    m = 3 if modules <= QA4_MOD[0] else 2 if modules < QA4_MOD[1] else 1
    return c, e, m


def qa4(usd_t2, mm, modules):
    subs = qa4_subs(usd_t2, mm, modules)
    for s in (3, 2):
        if sum(w for w, v in zip(QA4_W, subs) if v >= s) > 0.5 + 1e-12:   # strictly more than half of the weight
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
    # DP4: values reported in man-days and T2 USD; convert effort to MM
    for c, v in inp["DP4"]["values"].items():
        for k in ("qa4_equal", "qa4_weighted"):
            v[k]["mm"] = v[k]["man_days"] / MD_PER_MM
    return inp


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
                st["QA2"] = qa2(v["ttft_p99_ms"], v["tpot_p99_ms"])
            if "hbm_gib" in v:
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


def sensitivity(inp):
    """Margins to the nearest boundary and band over which the stars stay the same."""
    out = []
    # QA1 upper bound band over all reported ratios
    ratios = [(dp, c, v["qa1_ratio"]) for dp, d in inp.items() if not dp.startswith("_") for c, v in d["values"].items() if "qa1_ratio" in v]
    lo_band = max(r for _, _, r in ratios if r < 1.30 and r > 1.0) if ratios else None
    out.append(("QA1 ★★★ 경계(상한)", f"{QA1_HI}", "보고된 모든 값에서 같은 별이 나오는 구간", f"{lo_band:.3f} < U <= {min(r for _,_,r in ratios if r>=1.30):.3f}" if lo_band else ""))
    out.append(("QA1 ★★ 경계(하한)", f"{QA1_LO}", "보고된 값이 모두 이 경계 위(가장 낮은 값)", f"{min(r for _,_,r in ratios):.3f}"))
    return out



def alternatives(inp, res):
    """Which alternative rule families would have changed a reported total (why v1 was chosen)."""
    L = []
    tot = lambda dp, c, over: sum(over.get(k, v) for k, v in res[dp][c].items())
    # (a) common-document QA1 boundaries 0.90 / 1.10
    for dp in ("DP1", "DP2", "DP4"):
        for c, v in inp[dp]["values"].items():
            r = v["qa1_ratio"]
            alt = 3 if r >= 1.10 else 2 if r >= 0.90 else 1
            if alt != res[dp][c]["QA1"]:
                L.append(f"- 공통 문서 §4.3 경계(0.90/1.10)를 쓰면 {dp} {c} QA1이 {S(res[dp][c]['QA1'])} -> {S(alt)}로 바뀌어 별 합계가 {tot(dp, c, {})} -> {tot(dp, c, {'QA1': alt})}")
    # (b) improvement-multiplier QA2 (DP1/DP2 own rule) applied to DP4 with P99-only multiplier (P50/P95 not reported for DP4)
    b = inp["DP4"]["baseline"]
    for c, v in inp["DP4"]["values"].items():
        imp = (b["ttft_p99_ms"] / v["ttft_p99_ms"] * b["tpot_p99_ms"] / v["tpot_p99_ms"]) ** 0.5
        alt = 3 if imp >= 1.25 else 2 if imp >= 0.95 else 1
        if alt != res["DP4"][c]["QA2"]:
            L.append(f"- DP1/DP2의 개선 배수 기준(1.25/0.95)을 DP4에 쓰면(P99 두 값만 있어 근사, 배수 {imp:.2f}) DP4 {c} QA2가 {S(res['DP4'][c]['QA2'])} -> {S(alt)}로 바뀌어 별 합계가 {tot('DP4', c, {})} -> {tot('DP4', c, {'QA2': alt})}")
    # (c) DP4's own QA4 thresholds in man-days (<=3 / <=7) applied with equal-weight values
    for c, v in inp["DP4"]["values"].items():
        q = v["qa4_equal"]
        cs, es, ms = qa4_subs(q["usd_t2"], q["mm"], q["modules"])
        es2 = 3 if q["man_days"] <= 3 else 2 if q["man_days"] <= 7 else 1
        subs = (cs, es2, ms)
        s2 = 1
        for s in (3, 2):
            if sum(w for w, x in zip(QA4_W, subs) if x >= s) > 0.5 + 1e-12:
                s2 = s
                break
        if s2 != res["DP4"][c]["QA4"]:
            L.append(f"- DP4의 공수 경계(3/7 man-day)를 공통으로 쓰고 가중 없는 평균을 쓰면 DP4 {c} QA4가 {S(res['DP4'][c]['QA4'])} -> {S(s2)}로 바뀐다 (공수 {q['man_days']} md)")
    return L or ["- (바뀌는 대안 없음)"]


def md_table(inp, res):
    L = []
    L.append("| DP | 후보 | QA | 값 | 기존 별 | 공통 기준 v1 별 | 일치 |")
    L.append("|---|---|---|---|---|---|---|")
    tot_prev, tot_new = {}, {}
    for dp, d in inp.items():
        if dp.startswith("_"):
            continue
        for c, v in d["values"].items():
            for qa, new in res[dp][c].items():
                prev = d["previous_stars"][c].get(qa)
                val = fmt_value(dp, c, qa, v, d)
                ok = "O" if prev == new else ("N/A" if prev is None else "**X**")
                L.append(f"| {dp} | {c} | {qa} | {val} | {S(prev) if prev else '—'} | {S(new)} | {ok} |")
                if prev is not None:
                    tot_prev[(dp, c)] = tot_prev.get((dp, c), 0) + prev
                tot_new[(dp, c)] = tot_new.get((dp, c), 0) + new
    L.append("")
    L.append("| DP | 후보 | 별 합계(기존, 비교 가능 QA) | 별 합계(공통 기준 v1) | 일치 |")
    L.append("|---|---|---:|---:|---|")
    for k in tot_new:
        L.append(f"| {k[0]} | {k[1]} | {tot_prev.get(k, '—')} | {tot_new[k]} | {'O' if tot_prev.get(k) == tot_new[k] else '**X**'} |")
    return "\n".join(L), tot_prev, tot_new


def fmt_value(dp, c, qa, v, d):
    if qa == "QA1":
        return f"{v['qa1_tps']:,.0f} tok/s (x{v['qa1_ratio']:.3f})" if "qa1_tps" in v else f"x{v['qa1_ratio']:.3f}"
    if qa == "QA2":
        return f"TTFT P99 {v['ttft_p99_ms']:,.0f} ms · TPOT P99 {v['tpot_p99_ms']:.1f} ms"
    if qa == "QA3":
        return f"HBM {v['hbm_gib']:.1f} GiB (감소 배수 {d['baseline']['hbm_gib']/v['hbm_gib']:.2f})"
    if qa == "QA4":
        q = v.get("qa4") or v["qa4_equal"]
        subs = qa4_subs(q["usd_t2"], q["mm"], q["modules"])
        return f"${q['usd_t2']:.2f} · {q['mm']:.2f} MM · {q['modules']:.2f} module (sub {S(subs[0])}/{S(subs[1])}/{S(subs[2])})"
    if qa == "QA5":
        return f"F1 하락 {v['f1_drop_pct']}%"
    if qa == "QA6":
        return f"SE(16) {v['se16_pct']}%"
    return ""


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", type=Path, default=EVAL / "unified_stars_check.md")
    a = ap.parse_args()
    inp = load()
    res = evaluate(inp)
    table, tp, tn = md_table(inp, res)
    # sensitivity: QA4 weighted vs equal for DP4, T1 vs T2 for DP1/DP2, boundary margins
    extra = []
    for c, v in inp["DP4"]["values"].items():
        w = v["qa4_weighted"]
        extra.append(f"- DP4 {c} QA4 (S2~S4 가중 2, 원 값): {S(qa4(w['usd_t2'], w['mm'], w['modules']))} — 가중 없는 평균과 {'같다' if qa4(w['usd_t2'], w['mm'], w['modules']) == res['DP4'][c]['QA4'] else '다르다'}")
    for dp in ("DP1", "DP2"):
        for c, v in inp[dp]["values"].items():
            q = v["qa4"]
            t1 = qa4(q["usd_t1"] / 3.0, q["mm"], q["modules"])   # T1 USD / ~3 (T1/T2 ratio measured in DP1/DP2: 2.97~3.03)
            extra.append(f"- {dp} {c} QA4: T2 비용 {q['usd_t2']:.3f} (경계 0.5와의 차 {(0.5-q['usd_t2'])/0.5*100:+.1f}%), 공수 {q['mm']:.3f} MM (경계 0.5와의 차 {(0.5-q['mm'])/0.5*100:+.1f}%), 비용을 T1/3으로 환산해도 {'같은 별' if t1 == res[dp][c]['QA4'] else '다른 별'}")
    sens = sensitivity(inp)
    alts = alternatives(inp, res)
    lines = ["# 공통 별 기준 v1 적용 점검 (자동 생성, 직접 편집 금지)", "",
             "> 생성: `python doc-mk/Evaluation/tools/unified_stars.py`. 규칙은 `qa-star-criteria-unified.md`. 값은 `tools/unified_inputs.json`(출처 기록)과 DP1·DP2 `results/data/qa4_modifiability.json`.", "",
             "## 1. 기존 별과 공통 기준 v1 별의 비교", "", table, "", "## 2. 민감도·경계 근접", ""]
    lines += [f"- {a}: 값 {b}, {c}: {d}" for a, b, c, d in sens]
    lines += extra
    lines += ["", "## 3. 다른 기준 계열을 쓰면 무엇이 바뀌나", ""] + alts
    a.out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("\n".join(lines))
    bad = [k for k in tn if tp.get(k) is not None and tp[k] != tn[k]]
    print("\nTOTALS_CHANGED:", bad or "none")


if __name__ == "__main__":
    main()
