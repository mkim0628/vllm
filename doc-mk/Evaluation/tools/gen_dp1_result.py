#!/usr/bin/env python3
"""Render the unified DP1 QA evaluation result (7-section format, Common + DP1 Stress + DP1 Dynamic)
from DP1/results/data/SYS-*/qa_result.json. Numbers come only from those files.

    python tools/gen_dp1_result.py            # writes DP1/results/<DATE>_dp1-qa-evaluation.md
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "DP1" / "results" / "data"
SIM = ROOT / "DP1" / "sim"
DATE = "2026-10-02"
OUT = ROOT / "DP1" / "results" / f"{DATE}_dp1-qa-evaluation.md"
B, C1, C2 = "Baseline-static", "C1-resource-driven", "C2-behavior-driven"
SETS = [("common_benchmark", "Common"), ("dp1_stress_benchmark", "DP1 Stress"), ("dp1_dynamic_benchmark", "DP1 Dynamic")]
SYSIDS = ["SYS-H100", "SYS-B200"]   # generation profiles (all six memory kinds in each); SYS-A100 and SYS-VR excluded by owner decision
PRIMARY = "SYS-B200"                                       # per-scenario detail tables (equals legacy SYS-B200 numerically)
FIT_LETTER = {"comparison_valid": "V", "infeasible": "I", "saturated": "S"}

sys.path.insert(0, str(SIM))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from dp_selection import select as select_candidate  # noqa: E402
import scenarios as scn  # noqa: E402

MERGED = "INT-" + "-".join(x[4:] for x in SYSIDS)       # integrated result over SYSIDS (unit = scenario x system pair)
R = {s: json.load(open(DATA / s / "qa_result.json")) for s in SYSIDS + [MERGED]}
RT = {s: json.load(open(DATA / s / "dp1_rating.json")) for s in SYSIDS + [MERGED]}
RM, RTM = R[MERGED], RT[MERGED]
PRE = json.load(open(DATA / "pre_interference" / MERGED / "dp1_rating.json"))["sets"]["combined"]   # before link-interference fix
P = R[PRIMARY]


def rev():
    try:
        top = subprocess.check_output(["git", "rev-parse", "--show-toplevel"], cwd=ROOT, text=True).strip()
        r = subprocess.check_output(["git", "rev-parse", "--short", "HEAD"], cwd=top, text=True).strip()
        d = subprocess.check_output(["git", "status", "--porcelain", "--", "doc-mk/Evaluation"], cwd=top, text=True).strip()
        return f"{r} ({'dirty' if d else 'clean'})"
    except Exception:
        return "unknown"


def ratio_cell(q, c):
    x = q[c]
    s = f"{x['qa1']} x{x['qa1_ratio_geomean']:.3f}"
    if x.get("qa1_ratio_ci95"):
        s += f"±{x['qa1_ratio_ci95']:.3f}"
    return s


def qa2_cell(x):
    return f"{x['qa2']} {x['qa2_ttft_p99_worst_ms']:,.0f} ms / {x['qa2_tpot_p99_worst_ms']:,.0f} ms"


def final_table(res, key="qa_feasible"):
    rows = ["| Set (n) | QA | Baseline (T_ref) | C1 | C2 |", "|---|---|---|---|---|"]
    for label, name in SETS + [("combined", "Combined (3 set 통합)")]:
        d = res[label]
        q = d[key]
        n = q[B]["n_scenarios"] if "n_scenarios" in q[B] else d.get("n_feasible", "?")
        b = q[B]
        rows.append(f"| **{name}** ({n}) | QA1 Throughput | {b['qa1']} {b['qa1_abs_goodput_mean_tps']:,.0f} tps (x1.000) [B+C] | {ratio_cell(q, C1)} [B+C] | {ratio_cell(q, C2)} [B+C] |")
        rows.append(f"| | QA2 Latency (worst) | {qa2_cell(b)} [B+C] | {qa2_cell(q[C1])} [B+C] | {qa2_cell(q[C2])} [B+C] |")
        rows.append(f"| | QA3 Util. (v4 풀 U, 임시 정의) | {b['qa3']} {b['qa3_useful_util']*100:.2f}% [B+C] | {q[C1]['qa3']} {q[C1]['qa3_useful_util']*100:.2f}% [B+C] | {q[C2]['qa3']} {q[C2]['qa3_useful_util']*100:.2f}% [B+C] |")
    rows.append(f"| **QA4 Modifiability** | 3 sub-metric 중앙값 | — | {QA4_STARS[C1]} [B+C] | {QA4_STARS[C2]} [B+C] |")
    return "\n".join(rows)


def dp1_star_table(sysid=PRIMARY):
    rt = RT[sysid]
    rows = ["| Set (n, comparison-valid) | QA | Baseline (T_ref) | C1 | C2 |", "|---|---|---|---|---|"]
    for key, name in [("common_benchmark", "Common"), ("dp1_stress_benchmark", "DP1 Stress"), ("dp1_dynamic_benchmark", "DP1 Dynamic"), ("combined", "**Combined**")]:
        if key not in rt["sets"]:
            continue
        g = rt["sets"][key]; n = g[B]["n"]
        def c1(c):
            x = g[c]; return f"**{x['dp1_star']['qa1']}** x{x['qa1']['ratio']:.3f}±{x['qa1']['ci95']:.3f}" + (" (CI가 경계에 걸침)" if x["dp1_star"]["qa1_ci_straddles_edge"] and c != B else "")
        def c2(c):
            x = g[c]; l = x["qa2"]["latency"]
            return f"**{x['dp1_star']['qa2']}** x{x['qa2']['latency_improvement_geomean']:.2f} (TTFT P50/P95/P99 {l['ttft_p50_ms']['median']:,.0f}/{l['ttft_p95_ms']['median']:,.0f}/{l['ttft_p99_ms']['median']:,.0f} ms, TPOT {l['tpot_p50_ms']['median']:.1f}/{l['tpot_p95_ms']['median']:.1f}/{l['tpot_p99_ms']['median']:.1f} ms)"
        def c3(c):
            x = g[c]; return f"U {x['qa3']['useful_util']*100:.2f}% (x{x['qa3'].get('rel_vs_baseline', 1.0):.2f}) 진단"
        rows.append(f"| {name} ({n}) | QA1 Throughput | {c1(B)} [B+C] | {c1(C1)} [B+C] | {c1(C2)} [B+C] |")
        rows.append(f"| | QA2 Latency | {c2(B)} [B+C] | {c2(C1)} [B+C] | {c2(C2)} [B+C] |")
        rows.append(f"| | QA3 Utilization (진단, 별점 제외) | {c3(B)} [B+C] | {c3(C1)} [B+C] | {c3(C2)} [B+C] |")
    rows.append("| **QA4 Modifiability** | | — | ★★★ [C] | ★★ [C] |")
    return "\n".join(rows)


def all_star_tables():
    out = [f"### 통합 ({', '.join(SYSIDS)}) — 시나리오 x 시스템 쌍\n\n" + dp1_star_table(MERGED)]
    for sid in SYSIDS:
        out.append(f"### {sid} 단독\n\n" + dp1_star_table(sid))
    return "\n\n".join(out)


def sensitivity_table(sysid=PRIMARY):
    rt = RT[sysid]["sensitivity_combined_qa1"]
    g = RT[sysid]["sets"]["combined"]
    rows = ["| QA1 ★★★ 경계 (하한 0.97 고정) | C1 (x%.3f) | C2 (x%.3f) | C1과 C2가 구분되는가 |" % (g[C1]["qa1"]["ratio"], g[C2]["qa1"]["ratio"]), "|---|---|---|---|"]
    for edge, v in rt.items():
        diff = "구분됨" if v[C1] != v[C2] else "동일"
        mark = " **(채택)**" if abs(float(edge) - 1.30) < 1e-9 else ""
        rows.append(f"| >= {float(edge):.2f}{mark} | {v[C1]} | {v[C2]} | {diff} |")
    return "\n".join(rows)


def fine_table(sysid=PRIMARY):
    rt = RT[sysid]
    rows = ["| Set (n, comparison-valid) | 항목 | Baseline | C1 | C2 | C2 / C1 직접 비교 |", "|---|---|---|---|---|---|"]
    for key, name in [("common_benchmark", "Common"), ("dp1_stress_benchmark", "DP1 Stress"), ("dp1_dynamic_benchmark", "DP1 Dynamic"), ("combined", "Combined")]:
        if key not in rt["sets"]:
            continue
        g = rt["sets"][key]; h = rt["h2h"][key]; lo = h["latency_order"]
        n = g[B]["n"]
        def q1(c):
            x = g[c]["qa1"]; return f"T{x['tier']}/{x['tier_max']} x{x['ratio']:.3f}±{x['ci95']:.3f}"
        def q3(c):
            x = g[c]["qa3"]; return f"T{x['tier']}/{x['tier_max']} {x['useful_util']*100:.0f}% ({x['delta_pp_vs_baseline']:+.0f}pp)"
        def q2(c):
            l = g[c]["qa2"]["latency"]
            return (f"TTFT P50/P95/P99 {l['ttft_p50_ms']['median']:,.0f}/{l['ttft_p95_ms']['median']:,.0f}/{l['ttft_p99_ms']['median']:,.0f} ms; "
                    f"TPOT {l['tpot_p50_ms']['median']:.1f}/{l['tpot_p95_ms']['median']:.1f}/{l['tpot_p99_ms']['median']:.1f} ms")
        tally = h["tally"]
        rows.append(f"| **{name}** ({n}) | QA1 tier / ratio | T{g[B]['qa1']['tier']}/{g[B]['qa1']['tier_max']} x1.000 | {q1(C1)} | {q1(C2)} | "
                    f"x{h['geomean_goodput_ratio_C2_over_C1']:.3f}±{h['geomean_ci95']:.3f} (C2 {tally['C2']} / tie {tally['tie']} / C1 {tally['C1']}) |")
        rows.append(f"| | QA2 median P50/P95/P99 | {q2(B)} | {q2(C1)} | {q2(C2)} | " +
                    ", ".join(f"{p.upper()} x{lo[p]['C2_over_C1']:.2f} ({lo[p]['verdict']})" for p in ("p99", "p95", "p50")) + f" → **{lo['overall']}** |")
        rows.append(f"| | QA3 tier / util | T{g[B]['qa3']['tier']}/{g[B]['qa3']['tier_max']} {g[B]['qa3']['useful_util']*100:.0f}% | {q3(C1)} | {q3(C2)} | "
                    f"{(g[C2]['qa3']['useful_util']-g[C1]['qa3']['useful_util'])*100:+.0f}pp |")
    return "\n".join(rows)


def scenario_tables(res):
    out = []
    for label, name in SETS:
        d = res[label]
        out.append(f"### 4.2.{[s for s, _ in SETS].index(label)+1} {name}\n")
        out.append("| 시나리오 | Fit | Baseline (±CI) tok/s | C1 (ratio) | C2 (ratio) | TTFT P99 B/C1/C2 (ms) | TPOT P99 B/C1/C2 (ms) | C1 / C2 vs Baseline |")
        out.append("|---|---|---:|---:|---:|---|---|---|")
        for sn, v in d["per_scenario"].items():
            b, c1, c2 = v[B], v[C1], v[C2]
            fit = d["fit"][sn] if "fit" in d and sn in d["fit"] else d["scenario_labels"][sn]["fit"]
            sl = d["scenario_labels"][sn]["vs_baseline"]
            bg = b["max_goodput_tps"]
            r1 = f"x{c1['max_goodput_tps']/bg:.2f}" if bg > 0 else "n/a"
            r2 = f"x{c2['max_goodput_tps']/bg:.2f}" if bg > 0 else "n/a"
            out.append(f"| {sn} | {FIT_LETTER.get(fit, fit)} | {bg:,.0f} (±{b['goodput_ci95']:.0f}) | {c1['max_goodput_tps']:,.0f} ({r1}) | {c2['max_goodput_tps']:,.0f} ({r2}) | "
                       f"{b['ttft_p99_ms']:,.0f} / {c1['ttft_p99_ms']:,.0f} / {c2['ttft_p99_ms']:,.0f} | {b['tpot_p99_ms']:,.0f} / {c1['tpot_p99_ms']:,.0f} / {c2['tpot_p99_ms']:,.0f} | "
                       f"{sl.get(C1, {}).get('verdict', 'n/a')} / {sl.get(C2, {}).get('verdict', 'n/a')} |")
        out.append("")
    return "\n".join(out)


def scenario_catalog():
    funcs = {"common_benchmark": scn.common_benchmark, "dp1_stress_benchmark": scn.scenarios, "dp1_dynamic_benchmark": scn.dynamic_benchmark}
    rows = ["| Set | 시나리오 | " + " | ".join(SYSIDS) + " | 한 줄 설명 |", "|---|---|" + "---|" * len(SYSIDS) + "---|"]
    for label, name in SETS:
        for sc in funcs[label]():
            letters = []
            for s in SYSIDS:
                d = R[s][label]
                fit = d["fit"].get(sc.name) if "fit" in d else None
                letters.append(FIT_LETTER.get(fit, "?"))
            desc = (sc.brief or sc.description).replace("|", "/")
            rows.append(f"| {name} | `{sc.name}` | " + " | ".join(letters) + f" | {desc} |")
    return "\n".join(rows)


def cross_sys():
    rows = ["| SYS | 구성 | 공통 QA1 combined C1 / C2 | **DP1 별점 (QA1/QA2) C1** | **DP1 별점 C2** | C1 win/tie/loss | C2 win/tie/loss | dynamic: C1 / C2 win |", "|---|---|---|---|---|---|---|---|"]
    prof = json.load(open(SIM / "configs" / "systems.json"))["profiles"]
    for s in SYSIDS:
        r = R[s]; q = r["combined"]["qa_feasible"]; t = r["combined"]["tally"]
        dyn = r["dp1_dynamic_benchmark"]["tally"]
        dg = RT[s]["sets"]["combined"]
        ds = lambda c: " / ".join(dg[c]["dp1_star"][k] for k in ("qa1", "qa2"))
        rows.append(f"| {s} | {prof[s]['name']} | {ratio_cell(q, C1)} / {ratio_cell(q, C2)} | {ds(C1)} | {ds(C2)} | "
                    f"{len(t[C1]['win'])}/{len(t[C1]['tie'])}/{len(t[C1]['loss'])} | {len(t[C2]['win'])}/{len(t[C2]['tie'])}/{len(t[C2]['loss'])} | "
                    f"{len(dyn[C1]['win'])} / {len(dyn[C2]['win'])} (of {len(r['dp1_dynamic_benchmark']['per_scenario'])}) |")
    return "\n".join(rows)


def diagnostics():
    rows = ["| 지표 (SYS-B200, combined 평균) | Baseline | C1 | C2 |", "|---|---:|---:|---:|"]
    q = P["combined"]["qa_feasible"]
    rows.append(f"| migration 횟수 | {q[B]['migration_count']:.0f} | {q[C1]['migration_count']:.0f} | {q[C2]['migration_count']:.0f} |")
    rows.append(f"| migration bytes (GiB) | {q[B]['migration_gib']:,.0f} | {q[C1]['migration_gib']:,.0f} | {q[C2]['migration_gib']:,.0f} |")
    rows.append(f"| migration 링크 점유율 (migration 시간 / horizon) | {q[B]['migration_link_frac']*100:.1f}% | {q[C1]['migration_link_frac']*100:.1f}% | {q[C2]['migration_link_frac']*100:.1f}% |")
    rows.append(f"| decision overhead (ms/run) | {q[B]['decision_overhead_ms']:.1f} | {q[C1]['decision_overhead_ms']:.1f} | {q[C2]['decision_overhead_ms']:.1f} |")
    d = P["dp1_dynamic_benchmark"]["per_scenario"]
    gi = lambda c: sum(v[c]["migration_gib"] for v in d.values()) / len(d)
    rows.append(f"| dynamic set 평균 migration bytes (GiB) | {gi(B):,.0f} | {gi(C1):,.0f} | {gi(C2):,.0f} |")
    return "\n".join(rows)


def dynamic_analysis():
    d = P["dp1_dynamic_benchmark"]
    funcs = {sc.name: sc for sc in scn.dynamic_benchmark()}
    rows = ["| 시나리오 | C1 / C2 vs Baseline | Baseline SLO 만족률 | 후보 migration GiB (C1 / C2) | 원인 (시나리오가 재현하는 As-Is 약점) | Class |", "|---|---|---:|---|---|---|"]
    for sn, v in d["per_scenario"].items():
        sl = d["scenario_labels"][sn]["vs_baseline"]
        att = d["scenario_labels"][sn].get("baseline_slo_attainment")
        att = f"{att:.2f}" if att is not None else "n/a"
        rows.append(f"| {sn} | {sl[C1]['verdict']} (x{sl[C1]['goodput_ratio']:.2f}) / {sl[C2]['verdict']} (x{sl[C2]['goodput_ratio']:.2f}) | {att} | "
                    f"{v[C1]['migration_gib']:,.0f} / {v[C2]['migration_gib']:,.0f} | {funcs[sn].description.replace('|','/')} | B (벤치마크가 As-Is 약점을 드러냄) |")
    return "\n".join(rows)


QA4 = json.load(open(DATA / "qa4_modifiability.json"))
QA4_STARS = {B: "—", C1: QA4["qa4_stars"]["C1"], C2: QA4["qa4_stars"]["C2"]}   # measured on a simulator copy, DP1/qa4-modifiability.md
PRIO = json.load(open(ROOT / "DP1" / "qa_priority.json"))
EPS = json.load(open(DATA / "epsilon_SYS-B200.json"))


def stars_combined(sysid=PRIMARY):
    g = RT[sysid]["sets"]["combined"]
    out = {}
    for c in (C1, C2):
        d = g[c]["dp1_star"]
        out[c] = {"QA1": d["qa1"], "QA2": d["qa2"], "QA4": QA4_STARS[c]}
    return out


def representative():
    """Rule: Common = first scenario; Stress/Dynamic = largest and (Dynamic) smallest C2-C1 goodput-ratio gap among comparison-valid."""
    rows = []
    for key, name in SETS:
        sl = P[key]["scenario_labels"]
        valid = {sn: l for sn, l in sl.items() if l["fit"] == "comparison_valid"}
        if not valid:
            continue
        gap = {sn: l["vs_baseline"][C2]["goodput_ratio"] - l["vs_baseline"][C1]["goodput_ratio"] for sn, l in valid.items()}
        picks = [sorted(valid)[0]] if key == "common_benchmark" else [max(gap, key=gap.get)]
        if key == "dp1_dynamic_benchmark":
            picks.append(min(gap, key=gap.get))
        for sn in dict.fromkeys(picks):
            v = valid[sn]["vs_baseline"]
            rows.append((name, sn, v[C1]["goodput_ratio"], v[C2]["goodput_ratio"], v[C1]["verdict"], v[C2]["verdict"]))
    return rows


def eps_table():
    rows = ["| 오차 e (lognormal sigma) | C1 QA1 | C2 QA1 | C2/C1 | C1 win/tie/loss | C2 win/tie/loss | C1 QA3 | C2 QA3 |", "|---|---|---|---|---|---|---|---|"]
    for e, r in EPS.items():
        a, b = r[C1], r[C2]
        rows.append(f"| {e} | x{a['qa1']:.3f}±{a['qa1_ci']:.3f} | x{b['qa1']:.3f}±{b['qa1_ci']:.3f} | x{b['qa1']/a['qa1']:.3f} | {tuple(a['wtl'])} | {tuple(b['wtl'])} | {a['qa3']*100:.0f}% | {b['qa3']*100:.0f}% |")
    return "\n".join(rows)


def all_stars():
    """per-system DP1 stars (consistency check) and integrated stars. QA4 is system independent."""
    out = {}
    for sid in SYSIDS + [MERGED]:
        g = RT[sid]["sets"]["combined"]
        out[sid] = {c: {"QA1": g[c]["dp1_star"]["qa1"], "QA2": g[c]["dp1_star"]["qa2"], "QA4": QA4_STARS[c]} for c in (C1, C2)}
    return out


def overall_selection():
    """Selection on the INTEGRATED result: higher star total; tie -> QA priority (owner decision 2026-10-03)."""
    st = all_stars()
    sel = select_candidate(st[MERGED], PRIO["priority"])
    per = {sid: select_candidate(st[sid], PRIO["priority"]) for sid in SYSIDS}
    return dict(sel=sel, per=per, stars=st, winner=sel["winner"], rule=sel["rule"], deciding=sel["deciding_qa"],
                reversed_winner=sel["reversed_winner"], totals=sel["totals"])


def conclusion_bullets():
    o = overall_selection()
    nm = {C1: "C1", C2: "C2", None: "구분 불가"}
    st = o["stars"][MERGED]
    f = lambda c: " / ".join(st[c][k] for k in ("QA1", "QA2", "QA4"))
    per = ", ".join(f"{sid[4:]} 단독 {o['per'][sid]['totals'][C1]} 대 {o['per'][sid]['totals'][C2]}" for sid in SYSIDS)
    return (
        f"- **통합 DP1 별점 (QA1 / QA2 / QA4, QA3는 진단):** C1 {f(C1)}, C2 {f(C2)}. 별 합계 C1 {o['totals'][C1]}, C2 {o['totals'][C2]} -> **{nm[o['winner']]}** "
        f"({'별 합계가 높은 후보' if o['rule'] == 'total' else '합계가 같아 QA 우선순위(' + ' > '.join(PRIO['priority']) + ')로 결정, 결정 QA: ' + str(o['deciding'])}). 시스템별 단독 합계는 {per}이다(통합과 같은 방향인지 확인용). 별점 경계 의존성은 6장 9, 10.\n"
        "- **trade-off:** 성능(QA1)은 C2, 확장성(QA4)은 C1이 앞서고 QA2는 별이 같다. 이득은 H100/B200 모두에서 hot set이 이동하는 Dynamic 시나리오에 집중된다."
    )


def fit_counts():
    c = {"comparison_valid": 0, "saturated": 0, "infeasible": 0}
    for lab, _ in SETS:
        for v in RM[lab]["fit"].values():
            c[v] += 1
    return c


def summary_section():
    o = overall_selection()
    nm = {C1: "C1", C2: "C2", None: "구분 불가"}
    st = o["stars"][MERGED]
    G = RTM["sets"]["combined"]
    Qf = RM["combined"]["qa_feasible"]
    T = RM["combined"]["tally"]
    ft = fit_counts()
    m = QA4["mean_over_scenarios"]
    bs = G[B]
    def lat(c):
        l = G[c]["qa2"]["latency"]
        return f"TTFT P50/P95/P99 {l['ttft_p50_ms']['median']:,.0f}/{l['ttft_p95_ms']['median']:,.0f}/{l['ttft_p99_ms']['median']:,.0f} ms, TPOT {l['tpot_p50_ms']['median']:.1f}/{l['tpot_p95_ms']['median']:.1f}/{l['tpot_p99_ms']['median']:.1f} ms"
    def tier_hbm(c):
        return G[c]["qa3"]["tier_util"].get("hbm", 0.0) * 100
    wl = lambda c: f"{len(T[c]['win'])}승 {len(T[c]['tie'])}무 {len(T[c]['loss'])}패"
    rows = ["| QA | 평가 지표 (정량) | C1 Resource-driven | C2 Behavior-driven |", "|---|---|---|---|"]
    rows.append(f"| **QA1 Throughput** [B] | Baseline 대비 SLO goodput 배수 (시나리오별 비율의 geomean, 95% CI) · Baseline 대비 승/무/패 | **{st[C1]['QA1']}** x{G[C1]['qa1']['ratio']:.2f} ±{G[C1]['qa1']['ci95']:.2f} · {wl(C1)} | **{st[C2]['QA1']}** x{G[C2]['qa1']['ratio']:.2f} ±{G[C2]['qa1']['ci95']:.2f} · {wl(C2)} |")
    rows.append(f"| **QA2 Latency** [B] | TTFT/TPOT의 P50/P95/P99 개선 배수 6개의 geomean · 중앙값 지연 (Baseline: {lat(B)}) | **{st[C1]['QA2']}** x{G[C1]['qa2']['latency_improvement_geomean']:.2f} · {lat(C1)} | **{st[C2]['QA2']}** x{G[C2]['qa2']['latency_improvement_geomean']:.2f} · {lat(C2)} |")
    rows.append(f"| QA3 Utilization (진단, 별점 제외) [B] | 전 메모리 풀 U (Baseline 대비 상대) · HBM 점유율 · migration 링크 점유 · 이동량 | U {G[C1]['qa3']['useful_util']*100:.2f}% (x{G[C1]['qa3']['rel_vs_baseline']:.2f}) · HBM {tier_hbm(C1):.0f}% · 링크 {Qf[C1]['migration_link_frac']*100:.1f}% · {Qf[C1]['migration_gib']:,.0f} GiB | U {G[C2]['qa3']['useful_util']*100:.2f}% (x{G[C2]['qa3']['rel_vs_baseline']:.2f}) · HBM {tier_hbm(C2):.0f}% · 링크 {Qf[C2]['migration_link_frac']*100:.1f}% · {Qf[C2]['migration_gib']:,.0f} GiB |")
    rows.append(f"| **QA4 Modifiability** [B+C] | 변경 시나리오 4종 평균: module 수 · 개발 공수(man-month) · 에이전트 비용(frontier tier) | **{st[C1]['QA4']}** {m['C1']['modules']:.2f}개 · {m['C1']['man_months']:.2f} MM · ${m['C1']['usd_T1']:.2f} | **{st[C2]['QA4']}** {m['C2']['modules']:.2f}개 · {m['C2']['man_months']:.2f} MM · ${m['C2']['usd_T1']:.2f} |")
    rows.append(f"| **별 합계** | | **{o['totals'][C1]}** | **{o['totals'][C2]}** |")
    table = "\n".join(rows)
    pr = " > ".join(PRIO["priority"])
    dyn = RM["dp1_dynamic_benchmark"]["tally"]
    n_dyn_valid = sum(1 for v in RM["dp1_dynamic_benchmark"]["fit"].values() if v == "comparison_valid")
    rev = nm[o["reversed_winner"]]
    win_c = nm[o["winner"]]
    if o["rule"] == "total":
        why = f"별 합계가 높은 {win_c}를 선택한다."
    else:
        why = f"별 합계가 {o['totals'][C1]} 대 {o['totals'][C2]}로 같아 QA 우선순위({pr})를 적용한다. 별이 처음 갈리는 {o['deciding']}에서 앞선 {win_c}를 선택한다."
    text = f"""# 0. 최종 요약

> 발표용 요약이다. H100과 B200 두 세대의 시스템을 **하나로 통합**해 본 결과이고(시나리오 x 시스템 쌍이 단위), 별점은 DP1 기준이다(`qa-criteria-dp1.md`). 근거 표는 4장, 한계는 6장. 시스템별 단독 결과는 4.1/4.4에 있다.

## 0.1 QA별 비교

{table}

Baseline(현재 방식: 최초 배치를 고정하고 이동하지 않음)을 1.00으로 둔 상대값이다. 별은 DP1 기준이며 공통 기준 별점은 4.1a에 참고로 둔다.

## 0.2 Trade-off와 그 이유

**성능(QA1)은 C2, 확장성(QA4)은 C1이 앞선다. 지연(QA2)은 별이 같지만 값은 C2가 높다.** 이동 비용은 지연과 처리량에 이미 반영되어 있어(링크 간섭 모델) 별도 QA로 두지 않는다.

- **왜 C2의 처리량(QA1)과 지연(QA2)이 좋은가.** C2는 데이터 하나하나의 접근 빈도, 재사용, 유휴 시간을 보고 "곧 뜨거워질 것/식을 것"을 판단해 이동한다. 같은 종류(예: 모두 KV cache) 안에서도 방금 활발해진 세션과 오래 놀고 있는 세션을 구분할 수 있다. C1은 메모리 자원 상태(용량 압박, 대역폭)에만 반응하고 데이터를 종류로 구분하지 않아 같은 종류 안의 hot/cold를 구분하지 못한다. 그래서 같은 종류의 데이터에서 hot 대상이 시간에 따라 바뀌는 시나리오(hot 대화가 옮겨 감, 사용자 그룹이 번갈아 활성)에서 C2만 이기고 C1은 Baseline과 같다. Dynamic에서 Baseline을 유의하게 이긴 쌍은 C1 {len(dyn[C1]['win'])}개, C2 {len(dyn[C2]['win'])}개(비교 가능 {n_dyn_valid}개 중)이다.
- **왜 QA2는 별이 같은가.** 두 후보 모두 개선 배수가 ★★★ 경계(1.25)를 넘는다. 값은 C1 x{G[C1]['qa2']['latency_improvement_geomean']:.2f}, C2 x{G[C2]['qa2']['latency_improvement_geomean']:.2f}로 C2가 낫지만 3단계 별에서는 가려진다. 지연 분포의 꼬리(P99)는 간섭 모델 반영 후 차이가 더 벌어졌다(중앙값 TTFT P99 C1 {G[C1]['qa2']['latency']['ttft_p99_ms']['median']:,.0f} ms 대 C2 {G[C2]['qa2']['latency']['ttft_p99_ms']['median']:,.0f} ms).
- **이동 비용은 어디에 반영되나.** 이동은 같은 링크의 서빙 대역폭을 나눠 쓴다(간섭 모델, 2026-10-03). C2는 migration {Qf[C2]['migration_gib']:,.0f} GiB(C1 {Qf[C1]['migration_gib']:,.0f} GiB), 링크 점유 {Qf[C2]['migration_link_frac']*100:.1f}%(C1 {Qf[C1]['migration_link_frac']*100:.1f}%), 결정 연산 {Qf[C2]['decision_overhead_ms']:.0f} ms/run(C1 {Qf[C1]['decision_overhead_ms']:.0f} ms)이고, 이 비용 때문에 지연 개선 배수가 C2 x{PRE[C2]['qa2']['latency_improvement_geomean']:.2f}에서 x{G[C2]['qa2']['latency_improvement_geomean']:.2f}로, C1 x{PRE[C1]['qa2']['latency_improvement_geomean']:.2f}에서 x{G[C1]['qa2']['latency_improvement_geomean']:.2f}로 낮아졌다(처리량 배수 C2 x{PRE[C2]['qa1']['ratio']:.2f}에서 x{G[C2]['qa1']['ratio']:.2f}, C1 x{PRE[C1]['qa1']['ratio']:.2f}에서 x{G[C1]['qa1']['ratio']:.2f}; 비교 가능한 쌍 수도 달라져 단순 비교는 아니다).
- **왜 C1의 확장성(QA4)이 높은가.** C1은 데이터 종류를 모르는 구조라 새 종류의 데이터(예: sparse embedding)를 추가해도 고칠 곳이 거의 없다(module 1개). C2는 종류별 선호와 특성을 알고 있어 새 데이터 종류에 module 3개, 새 메모리를 선호 목록에 올려야 쓰이는 문제(module 2개)가 있다. 공수와 에이전트 비용도 C2가 1.3배 안팎이다. 이 값들은 시뮬레이터 복사본에 변경을 구현해 module/LOC를 측정하고 공수·비용은 가정 상수로 계산한 추정이다.

## 0.3 선택과 근거

1. QA 우선순위는 {pr}이다 ({PRIO['status']}). 근거: {PRIO['rationale']}
2. 규칙: 별 합계가 높은 후보를 선택하고, **합계가 같을 때만** 우선순위로 가른다 (`tools/dp_selection.py`).
3. 결과: C1 {o['totals'][C1]}, C2 {o['totals'][C2]}. {why} **선택: {win_c}.**
4. 결정 민감도: 우선순위를 뒤집으면({' > '.join(reversed(PRIO['priority']))}) 같은 규칙에서 {rev}가 선택된다. 이 선택은 "성능을 확장성보다 우선한다"는 판단에 의존한다.
5. 경계 취약성: QA1 ★★★ 경계(1.30)는 결과를 본 뒤 정했고 C1(x{G[C1]['qa1']['ratio']:.3f})은 그 바로 아래(95% CI가 경계에 걸침), C2(x{G[C2]['qa1']['ratio']:.3f})는 위에 있다. C1의 QA2(x{G[C1]['qa2']['latency_improvement_geomean']:.2f})도 ★★★ 경계(1.25) 바로 위다. QA4 평균 집계도 결과를 본 뒤 바꿨고 C2의 공수 평균이 경계(0.5 MM)를 0.006 넘은 수준이라 상수에 민감하다. 값 자체의 차이(C2/C1 goodput x{G[C2]['qa1']['ratio']/G[C1]['qa1']['ratio']:.2f})는 경계와 무관하다.

## 0.4 선택한 구조의 부족한 부분과 보완 설계

택틱 상세는 `DP1/DP1-complement-design-tactics.pptx`. 선택된 구조가 C2이면 아래를 적용한다.

| # | 약점 (평가 근거) | 보완 택틱 | 개선 대상 | 검증 상태 |
|---|---|---|---|---|
| W1 | QA4: 새 데이터 종류에 module {QA4['scenarios']['S2']['C2']['modules']}개, 새 메모리는 선호 목록에 올려야 사용(C1은 {QA4['scenarios']['S2']['C1']['modules']}개, 코드 변경 없이 사용) | 종류별 특성/선호를 descriptor로 외부화, descriptor가 없는 종류는 종류를 모르는 경로(C1 방식)로 처리 | QA4 | [C], 미구현 |
| W2 | migration 비용: C2 {Qf[C2]['migration_gib']:,.0f} GiB, 링크 점유 {Qf[C2]['migration_link_frac']*100:.1f}% | link 시간 예산 + 이득/비용 gating(simulator 적용), 트래픽 우선순위, replica가 있으면 DROP 우선 | QA1·QA2 | budget/gating [B] 적용, 나머지 [C] |
| W3 | 예측 의존: 모델 오차 e=0.6까지 C2 우위 유지(4.6, lognormal 한 종류) | 신뢰도 gating(낮으면 C1 트리거로 대체), do-no-harm guard, hysteresis | QA1 안정성 | [C], 미구현 |
| W4 | 결정 연산 {Qf[C2]['decision_overhead_ms']:.0f} ms/run (C1 {Qf[C1]['decision_overhead_ms']:.0f} ms) | event coalescing(구현), 점진 갱신, 비동기 판단 | QA2 | coalescing [B], 나머지 [C] |

## 0.5 어떤 상황을 평가했나

총 {len(scn.scenarios()) + len(scn.common_benchmark()) + len(scn.dynamic_benchmark())}개 시나리오를 H100과 B200에 각각 돌렸다(64쌍). 현재 방식(Baseline)도 SLO를 만족하는 비교 가능한 쌍이 {ft['comparison_valid']}쌍, 어느 후보도 차이를 못 내는 포화가 {ft['saturated']}쌍, Baseline이 아예 SLO를 못 맞춰 비교할 수 없는 쌍이 {ft['infeasible']}쌍이다(초장문·대용량 인덱스 등). 비교할 수 없는 쌍은 결과에서 빼지 않고 별도로 표시했다(4.2).

- **기본 서비스 상황(공통 시나리오).** 8K 토큰을 넣고 256 토큰을 생성하는 요청이 동시에 32개 들어오는 대화 서비스다. HBM이 빠듯한 경우, 시간이 갈수록 HBM 여유가 줄어드는 경우, KV cache에 LoRA·MoE expert·Agent 데이터가 섞여 들어오는 경우 세 가지를 본다. 여기서는 두 후보 모두 Baseline과 같다.
- **데이터 종류별로.** 대화 문맥(KV cache: 32K~512K 토큰, 동시 1~256), 여러 고객이 쓰는 LoRA 어댑터(몇 개만 인기가 많은 skew), MoE expert(라우팅이 몇 expert에 쏠림), 수 TiB 벡터 DB(RAG 인덱스), 오래 보관되는 Agent 기억과 Tool 결과(드물게 재사용 또는 한꺼번에 생성되어 반복 참조)를 각각 따로 본다.
- **접근이 얼마나 쏠리는가(hotness).** 소수만 인기 있는 skew, 거의 접근되지 않는 cold 데이터가 상위 메모리를 차지하는 경우, 갑자기 hot해지는 burst, hot/cold가 급반전하는 경우, 시간이 지나며 hot 대상이 옮겨 가는 경우(최근 세션으로 이동, 사용자 그룹이 번갈아 활성, 인기 검색 shard가 바뀜). 반대로 모든 데이터가 고르게 접근되는 전용 시나리오는 아직 없고, 중간 규모 KV 기준선(`kv_b16_c32k`)이 대조군 역할만 한다.
- **자원 조건이 바뀌는 경우.** HBM 용량 압박(고정, 점진 증가), HBM 대역폭 급락, 다른 작업과 공유하는 host 링크의 경합(대역폭 25%로 저하), 6개 메모리 용량을 모두 써야 하는 큰 용량 부담을 본다.
- **현재 방식이 처음엔 문제없다가 나빠지는 경우(Dynamic 6개).** 처음에는 Baseline이 SLO를 만족하지만 중간에 working set이 바뀌는 시나리오다. 이 시나리오는 Baseline의 실패 양상을 알고 설계했으므로 이득은 "배치가 낡아지는 상황"에 한정된다.

대표 예 두 가지. (1) 오래 보관만 되던 Agent 기억이 HBM을 차지한 상태에서 갑자기 채팅이 몰리면(`dyn_cold_resident_chat_wave`) hot KV가 느린 DRAM에서 서비스된다. C1과 C2 모두 이를 이동으로 해결하지만 C2가 훨씬 많이 옮긴다(B200 기준 401 GiB 대 3,224 GiB). (2) 같은 KV cache 안에서 hot 대화가 초기 세션에서 최근 세션으로 옮겨 가면(`dyn_kv_hotset_recency_shift`) 자원 압박이 그대로라 C1은 반응하지 않고 C2만 이득을 낸다. 전체 시나리오 목록은 [`DP1/benchmark.md`](../benchmark.md).

"""
    return text


def loss_sentence():
    tot = {sid: sum(len(R[sid]["combined"]["tally"][c]["loss"]) for c in (C1, C2)) for sid in SYSIDS}
    dyn = {sid: (len(R[sid]["dp1_dynamic_benchmark"]["tally"][C1]["win"]), len(R[sid]["dp1_dynamic_benchmark"]["tally"][C2]["win"]), len(R[sid]["dp1_dynamic_benchmark"]["per_scenario"])) for sid in SYSIDS}
    if all(v == 0 for v in tot.values()):
        head = "H100/B200 두 시스템, 3개 set 전체에서 **어느 후보도 Baseline 미만(loss)인 시나리오가 없다** (4.4의 loss 열)."
    else:
        head = "Baseline 미만(loss) 시나리오가 있다: " + ", ".join(f"{sid} {n}건" for sid, n in tot.items() if n) + " (4.4)."
    return head + " Dynamic에서 유의하게 이긴 시나리오 수(C1 / C2, 전체): " + ", ".join(f"{sid} {a} / {b} (of {n})" for sid, (a, b, n) in dyn.items()) + "."


def qa4_table():
    sc = QA4["scenarios"]
    rows = ["| 시나리오 | C1: module / man-month / 에이전트 비용(frontier tier) | C2: module / man-month / 에이전트 비용(frontier tier) |", "|---|---|---|"]
    for k, v in sc.items():
        f = lambda c: f"{v[c]['modules']} / {v[c]['man_months']:.2f} / ${v[c]['agent']['T1_frontier']['usd']:.2f}"
        rows.append(f"| {k} {v['title']} | {f('C1')} | {f('C2')} |")
    m = QA4["mean_over_scenarios"]
    rows.append(f"| **평균** | {m['C1']['modules']:.2f} / {m['C1']['man_months']:.2f} / ${m['C1']['usd_T1']:.2f} | {m['C2']['modules']:.2f} / {m['C2']['man_months']:.2f} / ${m['C2']['usd_T1']:.2f} |")
    ss = QA4["sub_stars"]
    rows.append(f"| sub-star (M1 modules / M2 공수 / M3 비용) | {' / '.join(ss['C1'][k] for k in ('M1','M2','M3'))} | {' / '.join(ss['C2'][k] for k in ('M1','M2','M3'))} |")
    rows.append(f"| **QA4 (sub-star 중앙값, 시나리오 평균 집계)** | **{QA4_STARS[C1]}** | **{QA4_STARS[C2]}** |")
    return "\n".join(rows)


def qa4_note():
    return ("측정: 시뮬레이터 복사본에 4개 변경을 C1과 C2 각각 실제로 구현해 module 수와 LOC를 측정했다. 공수와 에이전트 비용은 가정 상수로 계산한 추정이다(사전 등록: `qa4-preregistration.md`). "
            "이전 문서의 '신규 data type에 C2는 module 4개'는 측정 결과 3개였다. C2는 선호 목록에 이름이 없으면 신규 memory를 쓰지 않는다(C1은 코드 변경 없이 사용). 모델 tier에 따라 토큰 수와 금액의 순위가 달라질 수 있어 비용은 금액으로 비교한다.")


def _brief(name):
    for fn in (scn.common_benchmark, scn.scenarios, scn.dynamic_benchmark):
        for sc in fn():
            if sc.name == name:
                return (sc.brief or sc.description).replace("|", "/")
    return ""


def main():
    PCT1 = P['combined']['qa_feasible'][C1]['migration_link_frac'] * 100
    PCT2 = P['combined']['qa_feasible'][C2]['migration_link_frac'] * 100
    meta = P["meta"]
    q = P["combined"]["qa_feasible"]
    t = P["combined"]["tally"]
    md = f"""---
date: {DATE}
dp: DP1
candidates: [C1-resource-driven, C2-behavior-driven]   # Baseline-static 포함
sys_ids: [SYS-H100, SYS-B200]
git_rev: {rev()}
evidence: {{ QA1: "[B+C]", QA2: "[B+C]", QA3: "[B+C]", QA4: "[B+C]" }}
status: draft
---

# DP1 QA Evaluation — C1 vs C2 (Common + DP1 Stress + DP1 Dynamic, Baseline-regression loop 반영)

> 기준 문서: [`qa-evaluation-criteria.md`](../../qa-evaluation-criteria.md), [`common-benchmark.md`](../../common-benchmark.md), [`system-specs.md`](../../system-specs.md), [`DP1/benchmark.md`](../benchmark.md), [`DP1/simulation-plan.md`](../simulation-plan.md)
> 절차: `.claude/skills/evaluation/SKILL.md`
> 이 문서의 모든 simulation 수치는 Evidence [B+C]이며 [A] 실측이 아니다. 표는 `tools/gen_dp1_result.py`가 `results/data/SYS-*/qa_result.json`에서 생성했다.
> 이 문서는 [`2026-10-02_first-pass_superseded.md`](2026-10-02_first-pass_superseded.md)를 대체한다.

{summary_section()}# 1. 시스템 환경

| 항목 | 값 |
|---|---|
| SYS id | **메모리 세대별 2개 profile** (모두 6종 메모리 포함): SYS-H100 (HBM3, PCIe 5.0), SYS-B200 (HBM3e, PCIe 5.0). SYS-A100(HBM2e, PCIe 4.0)과 SYS-VR(HBM4, PCIe 6.0)은 profile만 정의하고 이 평가에서는 **제외**했다(소유자 결정, 2026-10-03). 이전 문서의 A100/VR 결과는 `results/data/SYS-A100`, `SYS-VR`에 보존된다. 기존 SYS-1~5는 legacy(메모리 부분집합 ablation)이며 이 문서의 주 결과가 아니다 |
| Model / precision | Llama-3.1-70B, BF16 (`models.json`) |
| Git revision | {rev()} |
| Seeds / loads | seeds {', '.join(map(str, meta['seeds']))} (5회) / load x{', x'.join(map(str, meta['loads']))}, 95% CI t={meta['t95']} |
| Tie 판정 | goodput 상대 차이 < {meta['material_rel']*100:.0f}% 또는 95% CI 이내이면 tie ("material" 임계 1%는 이 평가의 임시 상수) |
| 재현 command | `cd doc-mk/Evaluation/DP1/sim && python3 test_sim.py && python3 loop_run.py --final && python3 merge_systems.py SYS-H100 SYS-B200 && python3 dp1_rating.py ../results/data/INT-H100-B200/qa_result.json` (시스템별 단독은 각 SYS의 `dp1_rating.py`), 단일: `python3 qa_eval.py --system SYS-B200` |
| 표 생성 | `python3 doc-mk/Evaluation/tools/gen_dp1_result.py` |
| Raw data | `DP1/results/data/SYS-{{H100,B200}}/qa_result.json`, 통합 `INT-H100-B200/qa_result.json`, `epsilon_SYS-B200.json`, `qa4_modifiability.json`, `sensitivity_SYS-4.json`(legacy, SYS-B200과 동일 수치) |

시스템 profile 상세: [system-specs.md](../../system-specs.md). 세대별 profile의 H100 규격과 link 스케일링은 ASSUMED/PUBLIC(확인 필요)이며, CXL-PNM/HBF/SSD-PIM/Custom HBM 같은 신규 memory는 과거 세대가 없어 link 대역 스케일로만 세대를 표현했다(ASSUMED). 구 SYS-4 = SYS-B200(수치 동일), 구 SYS-5와 SYS-VR은 PCIe 6.0 반영으로 다르다.

# 2. 평가 항목

| 항목 | 정의 / formula | 출처 |
|---|---|---|
| QA1 Max SLO Goodput | load sweep(x0.5~2.0) 중 SLO를 만족한 output token/s의 최대값. 시나리오별 Baseline 대비 비율의 **geometric mean**. **DP1 별점:** < 0.97 ★ / 0.97~1.30 ★★ / >= 1.30 ★★★. 공통 별점(참고): criteria §4.3 (0.90 / 1.10) | criteria §4 + `DP1/qa-criteria-dp1.md` |
| QA2 Latency | Max goodput load point의 TTFT/TPOT P50/P95/P99. **DP1 별점:** 6개 improvement factor(Baseline / 후보)의 geometric mean, < 0.95 ★ / 0.95~1.25 ★★ / >= 1.25 ★★★. 공통 별점(참고): P99 worst-case, criteria §5 (≤2 s & ≤50 ms ★★★ / ≤4 s & ≤100 ms ★★) | criteria §5 + DP1 criteria |
| QA3 Utilization (**DP1에서는 진단, 별점 제외**) | `U = (sum_m 평균 점유 / sum_m 용량) x SLO 만족 비율 x (1 - migration 링크 점유율)`와 tier별 u_m. 별점 제외 이유: 처리량 이득과 상관 0.99로 독립 정보가 없고, 이동 비용은 링크 간섭 모델을 통해 QA1/QA2에 반영된다 (소유자 결정 2026-10-03) | **임시 정의** + `DP1/qa-criteria-dp1.md` §A.1 |
| QA4 Modifiability | 변경 시나리오 4개(신규 memory / data type / policy / event)에 대해 (M1) 변경 module 수, (M2) 개발 공수(man-month), (M3) 코드 에이전트 토큰 비용(USD, 모델 tier 2종). 시나리오별 최악값으로 sub-star를 정하고 QA4 = 세 sub-star의 중앙값 | `DP1/qa4-modifiability.md` (사전 등록: `qa4-preregistration.md`) |
| 집계 범위 | **DP1 별점은 comparison-valid만** 집계. 공통 별점(참고)은 "feasible" = Baseline goodput > 0 (comparison-valid + saturated). Combined는 3개 set 합산 | 본 평가 정의 |
| Diagnostic | migration 횟수/bytes/time, decision overhead, tier별 access, SLO 만족률 | DP1 전용 |

# 3. 벤치마크 / 시나리오

최종 결과는 **Common Benchmark + DP1 Stress Benchmark + DP1 Dynamic Benchmark**를 모두 합친 것이다.

- **Common**: 공통 profile(8K in / 256 out, Llama-3.1-70B BF16)의 DP1 realization 3개. HBM을 줄여 계층이 영향을 주게 했다.
- **DP1 Stress**: 기존 23개 (resource pressure / data behavior / mixed AI data / stability).
- **DP1 Dynamic**: Baseline-regression loop(iteration 2)에서 추가한 시나리오와 controls. **Baseline은 SLO를 만족하지만 static 배치가 runtime에 stale해지는** 패턴을 대상으로 한다.

Fit label: **V** = comparison-valid (Baseline이 SLO 만족), **I** = infeasible (Baseline도 SLO 불가, 비교 제외하되 목록 유지), **S** = saturated (모든 후보가 CI 안에서 동일, 판별 불가). SYS별로 label이 달라질 수 있다.

{scenario_catalog()}

# 4. 결과

## 4.1 최종 QA 표 — **DP1 기준 별점** (SYS-B200, Common + DP1 Stress + DP1 Dynamic 통합)

DP1 공식 별점이다 (기준: [`qa-criteria-dp1.md`](../qa-criteria-dp1.md) §A, Baseline 대비 효과 크기). 집계는 **comparison-valid 시나리오**(Baseline이 SLO를 만족)만 대상으로 한다. 공통 기준 별점은 4.1a에 참고로 싣는다.

{all_star_tables()}

> QA1 = Baseline 대비 goodput ratio(± 95% CI), 별 경계 0.97 / 1.30. QA2 = TTFT/TPOT x P50/P95/P99 6개 improvement factor의 geometric mean (>1이면 Baseline보다 빠름), 경계 0.95 / 1.25. QA3 = Baseline 대비 변화(pp), 경계 -5 / +15.
> **이 경계는 첫 결과를 본 뒤 정한 값이다.** 아래 4.1b에서 경계에 따른 별점 변화를 확인할 수 있다.

## 4.1a 공통 기준 별점 (참고, DP 간 비교용)

[`qa-evaluation-criteria.md`](../../qa-evaluation-criteria.md)의 기준 그대로이다. 집계는 Baseline goodput > 0인 시나리오(V + S)이고 QA2는 worst-case이다. Baseline 자체가 SLO를 못 맞추는 시나리오가 worst-case를 지배하면 별점이 모두 ★로 나올 수 있다.

{final_table(P)}

(n = 집계된 시나리오 수. ratio의 ± 값은 95% CI)

## 4.1b QA1 별점 경계 민감도 (SYS-B200, Combined)

DP1 별점의 차이가 경계 선택에 얼마나 의존하는지 보인다. 하한(0.97)은 고정하고 ★★★ 경계만 움직였다.

{sensitivity_table()}

C1(x1.258)과 C2(x1.442) 사이에 경계가 있을 때(약 1.26~1.44)에만 둘의 QA1 별점이 갈린다. 경계가 1.25 이하이면 둘 다 ★★★, 1.45 이상이면 둘 다 ★★이다.

## 4.1c DP1 세부 평가 (보조 진단, [`qa-criteria-dp1.md`](../qa-criteria-dp1.md) §B)

아래는 별점이 아니라 같은 별 안의 차이를 보기 위한 **진단** 지표이다 (구간은 첫 결과를 본 뒤 정의, 문서 §B.0 참조). 집계는 **comparison-valid 시나리오만** 대상으로 한다 (Baseline도 SLO를 못 맞추는 시나리오 제외).

{fine_table()}

읽는 법: `T3/7`은 7단계 중 3번째 tier (QA1 T3 = parity, T5~T7 = 공통 ★★★). QA3 tier는 8단계. QA2는 시나리오 간 median의 P50/P95/P99. 직접 비교의 ratio는 C2 / C1이다.

## 4.2 시나리오별 결과 (SYS-B200)

n_seeds = 5, 95% CI는 t 분포, V/I/S = Fit, ratio = 후보 / Baseline (Baseline goodput = 0이면 n/a).

{scenario_tables(P)}
## 4.3 Diagnostic

{diagnostics()}

## 4.4 시스템 간 비교 (combined, win/tie/loss는 95% CI 유의성 기준)

{cross_sys()}

## 4.5 Iteration summary

Baseline-regression loop가 발동했다 (first-pass에서 두 후보 모두 Baseline 이하). iteration 3에서 중단 조건 (i) 충족. 상세 로그: [iterations/loop-log.md](iterations/loop-log.md).

| Iteration | Class | Change | Effect (SYS-B200, 전체 benchmark 기준) |
|---|---|---|---|
| 0 (initial) | 계측 + M | `qa_eval.py` 확장(3 set, fit label, win/tie/loss), 전송이 destination write BW를 따르도록 수정 | C1 combined x0.957 (5 loss, Common TPOT 311 ms), C2 x0.961 (4 loss) |
| 1 | P | 공통 access-cost estimator, SLO filter와 do-no-harm(C1 destination 선택), link-time migration budget, cooldown, C2 benefit-vs-cost gating, C2 demotion은 HBM pressure일 때만 | C1 x1.000 / C2 x1.028, **loss 0**, win 0 (Common/Stress는 parity) |
| 2 | B | `dynamic_benchmark()` 6개 + controls 추가 (policy 불변) | dynamic: C1 x1.106 (win 1), C2 x2.211 (win 6) |
| 3 | P | C1 promotion path (설계 §17.2): static 추정으로 SLO를 위반하는 object를 HBM으로 승격, HBM 거주 object와 swap, budget 예약 | dynamic: C1 x1.643 (win 3), C2 불변 |

## 4.6 모델 오차 e sweep (SYS-B200, Combined, comparison-valid, 보고용)

access-cost 추정(두 후보 공통, 시스템적 편향)과 C2의 predicted hotness(C2만, 호출마다)에 lognormal 오차(sigma=e)를 넣고 같은 benchmark를 다시 돌렸다. 정책 상수는 바꾸지 않았다 (`DP1/sim/epsilon_sweep.py`).

{eps_table()}

e를 올려도 C2의 이득이 사라지는 지점(break-even)은 이 오차 모델에서는 나타나지 않았다. 오차가 커질수록 두 후보의 절대 이득이 오히려 e=0 일 때보다 커지는 구간이 있는데, 이는 e=0의 cost 추정식이 최적이 아님을 의미하며 오차가 정책을 개선한다는 뜻이 아니다. 이 결과는 lognormal 한 종류, 5 seed 기준이며 실제 workload 분포 이동에 대한 robustness는 확인하지 않았다.

# 5. 결과 분석

## 5.1 first-pass에서 Baseline보다 낮았던 이유 (iteration 0 진단, SYS-B200)

| 시나리오 | 후보 < Baseline? | Root cause | Class | 근거 diagnostic |
|---|---|---|---|---|
| Common (`cb_*`) | C1 (x0.86~0.93), C2 (x1.00) | C1 Destination Tier Selector가 destination의 **serving 비용을 보지 않아** CXL-PNM attention 경로(TPOT 311 ms)를 선택, HBM이 아니라 DRAM pressure에 반응해 6개 tier로 rebalance | P | `diagnose.py`: HBM util 0.38인데 migration 105건 전부 rebalance, CXL-PNM access 147 |
| Common, RAG 시나리오 | C2 | **migration budget 없음**. 대형 object(RAG 3.4 TiB) 이동이 stall을 만들어 TTFT P99 34 s. demotion이 upper-tier pressure를 확인하지 않음(설계 §17.3 위반) | P | migration 342~389건, 3.7 TiB, decision overhead 약 140 ms/run |
| Common 전체 | 둘 다 이득 불가 | Baseline SLO 만족률이 3개 시나리오 모두 1.00이라 후보가 tie 이상을 낼 수 없음 | B | baseline slo_ratio = 1.00 |
| Stress 14/23 (SYS-B200) | 비교 불가 | Baseline도 SLO 불가 (512K context, 8 TiB RAG, batch 256 등) | B | Fit = I |

## 5.2 Dynamic Benchmark에서 이득이 나는 이유 (SYS-B200, 최종)

{dynamic_analysis()}

- C2는 object별 behavior(access rate, reuse, idle)를 쓰므로 같은 data class 안의 hot/cold를 구분한다. 그래서 6개 전부에서 유의하게 이긴다.
- C1은 data type을 모르고 static hint(operation class, shape)와 resource 상태만 쓴다. **object별 hot/cold를 구분해야 하는 KV-only 시나리오 3개(idle / recency / rotating)에서는 tie**이다 (ratio가 1.1~1.5배로 보이나 95% CI 이내). 같은 data class 안의 object를 C1이 구분할 근거가 없기 때문이다.
- C1이 이기는 3개는 Agent Memory + KV 혼합(`dyn_cold_resident_chat_wave`), 단일 class RAG shard(`dyn_rag_shard_hotset_shift`), host path 경합(`dyn_host_path_contention_kv`)이다. 이 세 시나리오에서 이기는 정확한 메커니즘은 loop-log iteration 3 진단을 따른다 (본 문서는 추측하지 않는다).
- C1은 훨씬 적게 옮긴다 (dynamic 평균 migration bytes는 4.3의 표 참조).

## 5.3 Baseline 미만 시나리오 (최종 코드)

{loss_sentence()}

## 5.4 Sensitivity (iteration 3 이후 보고, 파라미터 재조정 아님; `results/data/sensitivity_SYS-4.json`)

- migration budget이 가장 민감하다. link share 0.10 또는 bucket window 4 s이면 후보당 win이 1~2개로 줄어 중단 조건 (i)이 충족되지 않는다. 0.50 또는 16 s이면 6개 모두 win이다.
- benefit horizon, C1 affinity margin은 거의 영향이 없다.
- 어느 변형에서도 loss는 나오지 않았다.

# 6. 한계

1. **Evidence가 [A]가 아니다.** 모든 수치는 config parameter(SPEC/PUBLIC/ASSUMED 혼재) 기반 simulation이다. vLLM trace replay, H100/B200 calibration이 없다.
2. **비용 추정이 완벽하다.** 정책의 access-cost estimator가 simulator와 같은 식을 쓴다 (테스트로 일치 확인). 실제 [A] 측정으로 보정한 추정은 오차가 있어 이득은 **상한에 가깝다.**
3. **Dynamic 시나리오는 실패 모드를 알고 설계했다.** Baseline만 돌려 설계하고 후보 실행 전에 고정했지만, 시나리오 선택이 결과를 좌우한다. 이득은 "static 배치가 stale해지는 경우"에 한정된 결과이며 일반 이득이 아니다. KV dynamic은 320K context, batch 16 셀(DRAM serving이 TPOT SLO를 못 맞추는 구성)이라 Llama-3.1 공식 context(128K)를 넘는다.
4. **정책 상수는 근거 데이터가 없는 설계 선택이다.** LINK_SHARE 0.25, window 8 s, horizon 30 s, affinity margin 2.0. sensitivity에서 budget이 결과를 크게 바꾼다 (5.4).
5. **미모델링:** capacity ramp(hard capacity limit 없음), HBM BW shock(offload가 건강한 HBM을 이길 수 없음), 다른 workload와의 링크 경합, HBF endurance, queueing/saturation(QA1이 load에 거의 비례). 개정된 **Memory Backend I/F 구조는 구현하지 않았다** (decision 로직은 기존 C1/C2, 개정 구조는 QA4에만 반영). DROP action은 이 평가에 포함하지 않았다.
6. **임시 정의:** QA3 formula, tie 판정의 1% material 임계, "saturated" fit label(모든 후보 CI 이내 동일).
7. **QA2 집계가 worst-case**라 Baseline 자체가 SLO를 못 맞추는 시나리오가 있는 set에서는 모든 후보가 ★로 나온다 (Stress set).
8. **세대별 profile의 규격은 일부 ASSUMED**: H100 HBM·연산 값은 PUBLIC(확인 필요), PCIe 세대별 link 스케일은 가정이다(제외된 SYS-A100의 CXL-PNM은 가상 구성). 신규 memory(CXL-PNM, HBF, SSD-PIM, Custom HBM)는 과거 세대가 없어 link 대역으로만 세대를 표현했다.
9. **DP1 별점 기준(4.1)은 공통 룰(criteria rule 2: 같은 QA는 DP 간 같은 룰)과 의도적으로 다르며, 첫 결과를 본 뒤 정의했다** (`defined_after_first_look`). 공통 별점은 4.1a에 병기한다. 후보 간 ★ 차이는 QA1 ★★★ 경계(1.30)에 의존한다. 4.1b의 sensitivity에서 경계가 약 1.26~1.44일 때만 C1/C2가 갈리고 1.25 이하에서는 같으며 1.50이면 둘 다 ★★이다. 새 benchmark로 같은 경계를 재확인해야 한다. 집계는 comparison-valid 시나리오만 대상으로 하므로 feasible 전체 기준 값과 n이 다르다.

10. **QA3를 DP1 별점에서 뺐다**(소유자 결정). 이유: 통합 결과에서 U 상대값과 처리량 배수의 상관이 0.99이고, 풀 점유는 후보와 무관하며(migration은 byte만 옮김), 풀이 SSD-PIM(약 75%)에 지배되어 U가 1~2%대다. 진단으로는 유지한다(tier별 u_m, 링크 점유, 이동량). 공통 QA 문서의 QA3는 DP2~4에서는 독립 축일 수 있어 그대로 둔다.
11. **링크 간섭 모델(2026-10-03)은 모델 결함 수정이다.** 이전에는 이동이 지연에 첫 접근 한 번의 0.20 x 전송시간으로만 반영되어 C2의 10배 이동이 지연에 거의 안 나타났다. 수정: 이동이 쓰는 링크 시간만큼 해당 tier의 서빙 대역폭을 줄인다(HBM 제외, 상한 90%). 수정 전 결과는 `results/data/pre_interference/`에 보존했고 수치 변화는 0.2에 있다. 남은 한계: 다른 workload와의 링크 경합, HBF endurance, 전력은 모델링하지 않았다.
12. **QA4는 추정이다.** 시뮬레이터 복사본에 변경 4종을 구현해 module/LOC를 측정했으나, 공수(man-month)와 에이전트 비용은 가정 상수(LOC 배율, 생산성, 토큰/LOC, 가격)로 계산한 값이며 실제 에이전트 세션 측정이 아니다. 상수를 낙관/비관으로 바꾸면 QA4는 두 후보 모두 같이 움직이고(★★★ 또는 ★★) 후보 차이는 별로 드러나지 않는다. 실제 vLLM 통합 비용과는 다르다. 오차 sweep(4.6)에서도 C2 우위는 역전되지 않았다. 이를 '예측 오차가 없어서'로 단정할 수는 없다(C2 predictor는 EWMA 추정기이지 oracle이 아니다). 단 access-cost 추정이 simulator와 같은 식을 쓴다는 한계(2번)는 그대로다.

# 7. 결론

- {loss_sentence()} first-pass의 Baseline 미만 결과는 정책 결함(P: serving 비용 무시, migration budget 없음)과 benchmark 부적합(B)에서 왔고 iteration 1~3(당시 SYS-4=SYS-B200)에서 해소되었다.
- **이득은 "static 배치가 runtime에 stale해지는" 조건에서만 확인된다.** Common과 feasible Stress에서는 대부분 동률이다. 이것은 일반 이득 주장이 아니다.
{conclusion_bullets()}
- **다음 단계:** (1) Destination Tier Selector의 serving-cost 입력, link-time migration budget, C2 benefit-vs-cost gating, C1 promotion 경로를 설계 문서에 반영한다 (loop-log '설계 문서에 미치는 영향'). (2) vLLM trace 수집과 HBM↔DRAM 실측으로 access-cost 모델의 오차를 [A]로 확인하고, 오차를 넣은 estimator로 재평가한다. (3) budget 파라미터 근거 확보. (4) 개정 구조(Backend I/F, snapshot)를 simulator에 반영한다.

## QA4 — Modifiability (3 sub-metric, [B+C], [`qa4-modifiability.md`](../qa4-modifiability.md))

{qa4_table()}

{qa4_note()}
"""
    OUT.write_text(md, encoding="utf-8")
    print("wrote", OUT)


if __name__ == "__main__":
    main()
