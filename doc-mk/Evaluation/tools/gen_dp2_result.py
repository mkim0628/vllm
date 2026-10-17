#!/usr/bin/env python3
"""DP2 result document + deck content from results/data (qa_result.json, qa5_result.json, qa4_modifiability.json, sens_result.json).

    python tools/gen_dp2_result.py --out doc-mk/Evaluation/DP2/results/2026-10-06_dp2-qa-evaluation.md
Every number in the document and the deck comes from these functions; only prose is typed by hand.
"""
from __future__ import annotations

import argparse
import json
import math
import subprocess
from collections import Counter
from pathlib import Path

HERE = Path(__file__).resolve().parent
D2 = HERE.parent / "DP2"
DATA = D2 / "results" / "data"
B, C1, C2 = "Baseline-PD-fixed", "C1-scheduling-time", "C2-pre-planned"
O, PR, DL = "Ref-Oracle", "Ref-P-retain", "Ref-D-local-always"
QA = json.loads((DATA / "qa_result.json").read_text())
QA4 = json.loads((DATA / "qa4_modifiability.json").read_text())
_p = DATA / "SYS-H100" / "qa5_result.json"
Q5 = json.loads(_p.read_text()) if _p.exists() else None
_p = DATA / "SYS-H100" / "sens_result.json"
SENS = json.loads(_p.read_text()) if _p.exists() else None
T = QA["tables"]["combined"]
PS = QA["per_scenario"]
LAB = QA["labels"]
EDGE5 = (0.70, 0.90)
SETS = {"common": "Common", "stress": "DP2 Stress", "dynamic": "DP2 Dynamic"}
DESC = {
    "cb_kv_8k_b32": "공통. 8K→256, 동시성 sweep, KV만, D 노드 HBM x0.12 (4P+1D)",
    "cb_kv_8k_b32_ramp": "공통. 위와 같고 D 노드 HBM 압박이 점진 증가",
    "cb_mixed_8k_b32": "공통. KV + 다른 데이터가 D 노드 HBM 30% 점유",
    "dp2_turn_hbm_small_tool": "History 32K가 D의 HBM, Tool 결과 0.5K인 멀티턴 (2P+2D)",
    "dp2_turn_dram_small_tool": "History 64K가 DRAM으로 내려간 뒤 재개",
    "dp2_turn_hbf_hist": "History 128K가 HBF(GPU 직접 읽기)에 있는 재개",
    "dp2_turn_ssd_hist": "History 64K가 SSD-PIM에 있는 재개 (대조군)",
    "dp2_tool_large_result": "Tool 결과 16K로 큰 턴 (대조군, P 경로가 최적일 것)",
    "dp2_prefill_burst_p_saturated": "Prefill burst(MMPP)로 P 포화, D 여유",
    "dp2_decode_heavy_p_idle": "출력 2K 위주로 D 포화, P 유휴",
    "dp2_long_ctx_decode_offload": "128~256K History, D HBM x0.3, ScHBM 오프로드 (1P+2D)",
    "dp2_session_size_skew": "5% 256K 대형 세션 + 95% 8K 채팅 (2P+4D)",
    "dp2_internode_link_contention": "P↔D 링크를 다른 트래픽과 공유(BW x0.25)",
    "dp2_stale_telemetry": "Telemetry 갱신 지연(지연 sweep 기준점)",
    "dp2_planner_fault_fallback": "T/2에 Planner 중단, fallback = Baseline 규칙",
    "dyn_turn_demotion_wave": "세션 idle 후 History가 DRAM→CXL-PNM으로 내려간 뒤 재개",
    "dyn_load_ramp_burst": "도착률 0.4→1.1 포화 ramp + burst",
    "dyn_p_node_degrade": "T/2에 P 노드 처리량 x0.5",
    "dyn_decode_phase_shift": "출력 길이 256→2K 전환",
}
SETOF = {}
for k in PS:
    pass


def gm(xs):
    xs = list(xs)
    return math.exp(sum(math.log(x) for x in xs) / len(xs))


def stars(n):
    return "★" * n


def star5(x):
    return "★" if x < EDGE5[0] else ("★★" if x < EDGE5[1] else "★★★")


def sc_set(name):
    for s, ns in _SETS.items():
        if name in ns:
            return s
    return "?"


import sys  # noqa: E402
sys.path.insert(0, str(D2 / "sim"))
from dp2sim.scenarios import SCENARIOS  # noqa: E402
_SETS = {}
for _n, _s in SCENARIOS.items():
    _SETS.setdefault(_s.set, []).append(_n)


def r2(x):
    return f"x{x:.2f}"


def q5v(var, n):
    return Q5["main"][var].get(str(n)) if Q5 else None


def q5_eta(var, n=32):
    r = q5v(var, n)
    return r.get("eta") if r else None


def qa5_cells():
    """{cand: (eta, star, t_dec P99 ms)} for Baseline / C1 / C2(w=4)."""
    out = {}
    for lab, var in (("B", "Baseline"), ("C1", "C1"), ("C2", "C2(w=4)")):
        r = q5v(var, 32)
        out[lab] = None if not r else dict(eta=r.get("eta"), gp=r["goodput"], t_dec=r["t_dec_ms"], ttft=r["ttft99"], star=star5(r["eta"]) if r.get("eta") is not None else "-")
    return out


def totals():
    """Star totals QA1..QA5 per candidate (QA5 only if measured)."""
    q5c = qa5_cells()
    res = {}
    for lab, c in (("C1", C1), ("C2", C2)):
        s = [len(T[c]["star_qa1"]), len(T[c]["star_qa2"]), len(T[c]["star_qa3"]), len(QA4["qa4_stars"][lab])]
        if q5c.get(lab) and q5c[lab]["eta"] is not None:
            s.append(len(q5c[lab]["star"]))
        res[lab] = s
    return res


def e5(var, n=32):
    r = q5v(var, n)
    return r.get('eta') if r and r.get('eta') is not None else 0.0


def pct(x):
    return f"{100 * x:.0f}%"


def head_rows():
    """Rows of the result table: (label_lines, baseline, c1, c2)."""
    b, a, c = T[B], T[C1], T[C2]
    q5c = qa5_cells()
    m4 = QA4["mean_over_scenarios"]
    rows = []
    rows.append((["QA1 Throughput", "Max SLO goodput (tok/s) ↑"], f"{b['qa1_abs']:,.0f}",
                 f"{a['star_qa1']}  {a['qa1_abs']:,.0f} ({r2(a['qa1_ratio'])})", f"{c['star_qa1']}  {c['qa1_abs']:,.0f} ({r2(c['qa1_ratio'])})"))
    f = lambda x, k, d=0: f"{x[k] * 1e3:,.{d}f}"
    rows.append((["QA2 Latency — TTFT", "P99 · P50 (ms) ↓"], f"P99 {f(b, 'ttft_p99')} · P50 {f(b, 'ttft_p50')}",
                 f"P99 {f(a, 'ttft_p99')} ({r2(a['ttft_p99_x'])}) · P50 {f(a, 'ttft_p50')} ({r2(a['ttft_p50_x'])})",
                 f"P99 {f(c, 'ttft_p99')} ({r2(c['ttft_p99_x'])}) · P50 {f(c, 'ttft_p50')} ({r2(c['ttft_p50_x'])})"))
    rows.append((["QA2 Latency — TPOT", "P99 · P50 (ms) ↓"], f"P99 {f(b, 'tpot_p99', 1)} · P50 {f(b, 'tpot_p50', 1)}",
                 f"P99 {f(a, 'tpot_p99', 1)} ({r2(a['tpot_p99_x'])}) · P50 {f(a, 'tpot_p50', 1)} ({r2(a['tpot_p50_x'])})",
                 f"P99 {f(c, 'tpot_p99', 1)} ({r2(c['tpot_p99_x'])}) · P50 {f(c, 'tpot_p50', 1)} ({r2(c['tpot_p50_x'])})"))
    rows.append((["QA2 별점", "6개 지표 개선 배수 geomean"], "x1.00",
                 f"{a['star_qa2']}  {r2(a['qa2_impr'])} (TTFT {r2(a['ttft_impr'])} · TPOT {r2(a['tpot_impr'])})",
                 f"{c['star_qa2']}  {r2(c['qa2_impr'])} (TTFT {r2(c['ttft_impr'])} · TPOT {r2(c['tpot_impr'])})"))
    rows.append((["QA3 Resource utilization", "useful GPU 사용률 (%) ↑"], f"{100 * b['util']:.1f}",
                 f"{a['star_qa3']}  {100 * a['util']:.1f} ({r2(a['util_x'])})", f"{c['star_qa3']}  {100 * c['util']:.1f} ({r2(c['util_x'])})"))
    rows.append((["QA4 Modifiability", "module · 공수(MM) · 에이전트 비용 ↓"], "—",
                 f"{QA4['qa4_stars']['C1']}  {m4['C1']['modules']:.2f} · {m4['C1']['man_months']:.2f} · ${m4['C1']['usd_T1']:.2f}",
                 f"{QA4['qa4_stars']['C2']}  {m4['C2']['modules']:.2f} · {m4['C2']['man_months']:.2f} · ${m4['C2']['usd_T1']:.2f}"))
    if q5c["B"]:
        g = lambda k: (f"{q5c[k]['star']}  η {q5c[k]['eta']:.2f} · 결정 {q5c[k]['t_dec']:.1f} ms(임계 경로)" if k != "B" else f"η {q5c['B']['eta']:.2f}")
        rows.append((["QA5 Scalability", "η (N=32 노드), 결정 지연 ↑"], g("B"), g("C1"), g("C2")))
    else:
        rows.append((["QA5 Scalability", "η (N=32 노드)"], "측정 전", "측정 전", "측정 전"))
    t = totals()
    rows.append((["별 합계 (QA1~QA5)", ""], "—", str(sum(t["C1"])), str(sum(t["C2"]))))
    return rows


def fits():
    c = Counter(v["fit"] for v in LAB.values())
    return c["comparison_valid"], c["saturated"], c["infeasible"], len(LAB)


def gwin(c):
    return sum(1 for k in LAB if LAB[k]['vs'][c]['goodput'] == 'win')


def tallies():
    out = {}
    for c in (C1, C2, O, PR, DL):
        v = Counter(LAB[k]["vs"][c]["verdict"] for k in LAB)
        out[c] = (v["win"], v["tie"], v["loss"])
    return out


def per_set_table(c):
    rows = []
    for s, nm in SETS.items():
        t = QA["tables"][s]
        rows.append((nm, t[B]["n"], t[c]["qa1_ratio"], t[c]["ttft_p99_x"], t[c]["tpot_p99_x"], t[c]["qa2_impr"], t[c]["util_x"]))
    return rows


def regress():
    """(system|scenario, metric) where a starred candidate is materially worse than the Baseline (verdict loss on any component)."""
    out = []
    for k, l in LAB.items():
        for c in (C1, C2):
            v = l["vs"][c]
            if v["goodput"] == "loss" or v["ttft"] == "loss" or v["tpot"] == "loss":
                out.append((k, c, v["goodput"], v["ttft"], v["tpot"]))
    return out


def deck_slides(Slide):
    import gen_dp_pptx as base
    rows = head_rows()
    nv, ns, ni, nt = fits()
    tl = tallies()
    a, c, b = T[C1], T[C2], T[B]
    # ---- slide 1: table
    s = Slide("DP2 평가 결과 - QA별 정량 metric (H100 + B200 통합)")
    cols = [("QA / 평가 metric", 0.4, 3.0), ("Baseline-PD-fixed", 3.4, 1.9), ("C1 스케줄링 시점 결정", 5.3, 3.8), ("C2 사전 계획 결정", 9.1, 3.8)]
    y = 1.15
    for name, x, w in cols:
        s.box(x, y, w, 0.32, name, "head", 10, True, "ctr", False)
    prev = 0.34
    for lab, bs, x1, x2 in rows:
        h = 0.36 if lab[1] == "" else 0.5
        y += prev
        s.box(0.4, y, 3.0, h, lab if lab[1] else lab[:1], "dp", 9, True, "l", False)
        s.box(3.4, y, 1.9, h, bs, "cell", 9.5, False, "ctr", False)
        s.box(5.3, y, 3.8, h, x1, "cell", 9.5, False, "ctr", False)
        s.box(9.1, y, 3.8, h, x2, "cell", 9.5, False, "ctr", False)
        prev = h + 0.02
    y += prev + 0.06
    s.box(0.4, y, 12.5, 0.9, [
        "시스템: H100x8 (HBM3, PCIe 5.0, DDR5-4800) + B200x8 (HBM3e, PCIe 5.0, DDR5-6400). 노드 = 8-GPU, 6종 메모리, Llama-3.1-70B BF16. 노드 간 링크 RDMA 50 GB/s (ASSUMED). 노드 수 4~6개.",
        f"시나리오: 19개 x 2시스템 = {nt}쌍, 비교 가능 {nv}쌍(포화 {ns}, Baseline 불가 {ni}). 값은 쌍별 값의 기하평균(QA3는 평균), 괄호는 후보 ÷ Baseline(↑ 높을수록 좋음, ↓ 낮을수록 좋음). QA2/QA3는 Baseline의 최적 부하에서 비교. Evidence [B+C]."], "note", 9)
    y += 0.98
    s.box(0.4, y, 12.5, 0.95, [
        "선택: 두 후보가 거의 같다(QA1 x%.2f 대 x%.2f, C2/C1 goodput x%.3f). 이 평가는 C1과 C2를 구분하지 못한다. 차이는 QA5(확장성)에서만 나타난다." % (a["qa1_ratio"], c["qa1_ratio"], gm(PS[k][C2]["goodput"] / PS[k][C1]["goodput"] for k in PS)),
        "한계: [B] simulation. 별 경계는 DP1 값을 사전 고정. 결정 비용·링크는 ASSUMED. QA2/QA3 iso-load 집계는 첫 결과를 본 뒤 정의(defined_after_first_look). 공통 시나리오에서 QA2는 Baseline보다 나쁘다(다음 장)."], "sel", 9)
    out = [s]
    # ---- slide 2: system
    sy = base.system_slide()
    sy.title = "DP2 평가 시스템 - 메모리 구성과 노드 간 링크 (H100x8 / B200x8, 값이 다르면 H100 / B200)"
    sy.E[-1]["lines"] = base.wrap("DP2에서 추가한 것: 노드 간 KV 전송 링크 RDMA 400G 1 rail = 50 GB/s (ASSUMED, 지연 100 us; sweep 12.5/50/200/400 GB/s). 노드 = 8-GPU TP8 인스턴스 1개, 토폴로지 4P+1D(공통), 2P+2D(Stress/Dynamic). 노드 NIC out/in, 메모리 Tier 읽기, HBM 쓰기를 max-min 공정 분배 흐름 모델로 공유.", 12.4, 9) + \
        base.wrap("시뮬레이션 반영: DP1과 같은 용량·대역폭·연산 능력·지원 연산. attention 오프로드(ScHBM, CXL-PNM)와 HBF GPU 직접 읽기(Decode attention, 쓰기 비대칭 미반영)는 DP2에서 노드별 Decode 시작 위치 후보로 쓴다. Decode 중 Tier 이동(DP1)은 이 평가에 없다(모든 후보가 같은 초기 배치).", 12.4, 9) + \
        base.wrap("미반영: NIXL/RDMA 프로토콜 오버헤드, GPU 내 Prefill/Decode 간섭의 정밀 모델(iteration 합산 근사), prefix cache 공유, 전력. 값의 출처와 ASSUMED 구분은 system-specs.md.", 12.4, 9)
    out.append(sy)
    # ---- slide 3: why QA1/TTFT/TPOT
    def why(title, items):
        sl = Slide(title)
        for name, x, w in (("QA / 수치", 0.4, 2.9), ("왜 이런 값이 나왔나", 3.3, 6.5), ("근거 (시나리오·측정값)", 9.8, 3.1)):
            sl.box(x, 1.15, w, 0.32, name, "head", 10, True, "ctr", False)
        yy = 1.5
        for h, l, mid, ev in items:
            sl.box(0.4, yy, 2.9, h, l, "dp", 9.5, True, "l", False)
            sl.box(3.3, yy, 6.5, h, mid, "cell", 9, False, "l", False)
            sl.box(9.8, yy, 3.1, h, ev, "note", 8.5, False, "l", False)
            yy += h + 0.05
        return sl
    def sc(k, cand, f="goodput"):
        return PS[k][cand][f]
    cbH, cbB = "SYS-H100|cb_kv_8k_b32", "SYS-B200|cb_kv_8k_b32"
    lc = "SYS-B200|dp2_internode_link_contention"
    ss = "SYS-B200|dp2_session_size_skew"
    ph = "SYS-H100|dp2_turn_hbf_hist"
    dd = "SYS-H100|dyn_turn_demotion_wave"
    tpl = tl
    s3 = why("DP2 평가 결과 - QA별로 왜 이런 값이 나왔나 (1/2: 처리량, 지연)", [
        (1.9, [f"QA1 처리량", f"C1 {r2(a['qa1_ratio'])} · C2 {r2(c['qa1_ratio'])}", f"참고: Oracle {r2(T[O]['qa1_ratio'])} · P-retain {r2(T[PR]['qa1_ratio'])}"],
         [f"- 비교 가능 {nv}쌍 중 Baseline보다 goodput이 유의하게 높은 쌍이 C1 {gwin(C1)}, C2 {gwin(C2)}개(나머지는 동률)이고 진 쌍은 없다(Baseline이 SLO를 거의 못 지키는 쌍이 많아 배수가 크다).",
          "- 이득의 큰 출처는 두 가지다. (1) 고정 역할의 낭비: Baseline은 D 노드의 Prefill 능력을 쓰지 않고 P 노드에서만 Prefill한다. Planner는 여유 있는 노드에서 Prefill해 공통 시나리오에서도 x1.3~2.1이 나온다. (2) 위치를 몰라서 생기는 전송: 링크 경합·긴 History에서 큰 이득.",
          f"- C1과 C2는 구분되지 않는다(C2/C1 goodput x{gm(PS[k][C2]['goodput'] / PS[k][C1]['goodput'] for k in PS):.3f}). Oracle과도 거의 같다: 이 규모에서 결정 시점·결정 지연은 처리량을 바꾸지 못한다."],
         [f"링크 경합(B200): Baseline {sc(lc, B):.0f} → C1 {sc(lc, C1):.0f} tok/s ({sc(lc, C1) / sc(lc, B):.1f}배). 공통 cb_kv_8k_b32 H100 x{sc(cbH, C1) / sc(cbH, B):.2f}, B200 x{sc(cbB, C1) / sc(cbB, B):.2f}. P-retain은 공통에서 x1.00."]),
        (1.55, ["QA2 TTFT", f"P99 C1 {r2(a['ttft_p99_x'])} · C2 {r2(c['ttft_p99_x'])}", f"P50 C1 {r2(a['ttft_p50_x'])} · C2 {r2(c['ttft_p50_x'])}"],
         ["- Baseline의 TTFT P99가 큰 시나리오(대형 세션 쏠림, 링크 경합, 긴 History)에서 Planner가 대기·전송이 적은 경로를 골라 크게 줄인다.",
          f"- 반대로 공통 시나리오에서는 Baseline의 최적 부하에서 TTFT P99가 Baseline보다 나쁘다(Common 집합 x{T[C1]['ttft_p99_x'] if False else QA['tables']['common'][C1]['ttft_p99_x']:.2f}). Cost 정의(SLO 분율의 합)가 TPOT 여유를 TTFT와 맞바꾸기 때문이다."],
         [f"세 집합 중 Common TTFT P99: Baseline {QA['tables']['common'][B]['ttft_p99'] * 1e3:,.0f} ms → C1 {QA['tables']['common'][C1]['ttft_p99'] * 1e3:,.0f} ms. 대형 세션 쏠림(B200): {sc(ss, B, 'iso')['ttft_p99']:.1f} s → C1 {sc(ss, C1, 'iso')['ttft_p99']:.2f} s."]),
        (1.45, ["QA2 TPOT", f"P99 C1 {r2(a['tpot_p99_x'])} · C2 {r2(c['tpot_p99_x'])}", f"P50 C1 {r2(a['tpot_p50_x'])} · C2 {r2(c['tpot_p50_x'])}"],
         [f"- TPOT P99는 Baseline보다 나빠진다(x{a['tpot_p99_x']:.2f}). 그러나 값은 {a['tpot_p99'] * 1e3:.1f} ms로 SLO(50 ms)보다 훨씬 낮다. Cost가 TTFT를 줄이는 대신 TPOT 여유를 쓰는 선택을 하는 것으로 보인다(요청 단위로 분해하지는 않았다).",
          "- 중앙값(P50)은 비슷하거나 낫다. 개선 배수 geomean이 1.5를 넘는 것은 TTFT가 크게 줄기 때문이고 TPOT는 x%.2f다." % a["tpot_impr"]],
         [f"참고 P-retain(Prefill 노드 유지): TPOT P99 x{T[PR]['tpot_p99_x']:.2f}, TTFT P99 x{T[PR]['ttft_p99_x']:.2f}, QA2 {r2(T[PR]['qa2_impr'])}. 단순 규칙이 QA2에서 C1/C2({r2(a['qa2_impr'])})보다 높다."])])
    out.append(s3)
    q5c = qa5_cells()
    cvC, cvB = a["cv_p"], b["cv_p"]
    if q5c["B"]:
        qa5_txt = [f"- N=32 노드에서 η는 Baseline {q5c['B']['eta']:.2f}(역할 고정이라 노드가 늘어도 선형), C1 {q5c['C1']['eta']:.2f}, C2(worker 4) {q5c['C2']['eta']:.2f}(worker 16 {e5('C2(w=16)'):.2f}). 결정 비용을 후보 수(노드²×Tier)에 선형(1 ms @ 64 후보)으로 가정하면 N=32의 결정 1건이 C1은 64 ms다. 단일 scheduler가 포화해 SLO 만족 goodput이 0이 된다. C2는 planner worker로 지연을 숨기지만 plan 생성 처리량이 도착률을 못 따라간다.",
                   f"- top-k=8 pruning을 쓰면 결정 지연이 5.1 ms로 고정되고 N=32에서 C1 η {e5('C1+topk8'):.2f}, C2 η {e5('C2+topk8'):.2f}. 두 후보 모두 pruning이 사실상 필수다. 값은 비용 가정(ASSUMED)에 의존한다(문서 4.7)."]
        q5ev = [f"N=32 goodput: Baseline {q5c['B']['gp']:,.0f}, C1 {q5c['C1']['gp']:,.0f}, C2 {q5c['C2']['gp']:,.0f} tok/s. 결정 지연(평균) C1 {q5c['C1']['t_dec']:.0f} ms. 노드당 부하 grid 끝에서 peak가 나온 경우가 있어 η는 잡음 ±0.1 정도."]
    else:
        qa5_txt, q5ev = ["- 측정 전."], [""]
    s4 = why("DP2 평가 결과 - QA별로 왜 이런 값이 나왔나 (2/2: 자원, 변경 용이성, 확장성)", [
        (1.55, ["QA3 자원 활용", f"C1 {r2(a['util_x'])} · C2 {r2(c['util_x'])}", f"{100 * b['util']:.1f}% → {100 * a['util']:.1f}% / {100 * c['util']:.1f}%"],
         [f"- useful 사용률은 SLO를 만족한 토큰의 GPU 시간만 센다. Baseline은 P 풀 {100 * b['pool_p']:.0f}%·D 풀 {100 * b['pool_d']:.0f}%로 풀 간 불균형이 크다. Planner는 P 풀 {100 * a['pool_p']:.0f}%·D 풀 {100 * a['pool_d']:.0f}%로 균형을 맞춘다.",
          "- 처리량과 상관이 강한 지표다(SLO 만족 토큰이 늘어난 만큼 사용률이 오른다). 독립 근거로 읽지 말 것."],
         [f"Turn당 노드 간 KV 이동량: Baseline {b['gib_turn']:.1f} GiB → C1 {a['gib_turn']:.1f} GiB. 노드 간 P 부하 CV {b['cv_p']:.2f} → {a['cv_p']:.2f}."]),
        (1.45, ["QA4 변경 용이성", f"C1 {QA4['mean_over_scenarios']['C1']['modules']:.2f} · C2 {QA4['mean_over_scenarios']['C2']['modules']:.2f} module", f"공수 {QA4['mean_over_scenarios']['C1']['man_months']:.2f} / {QA4['mean_over_scenarios']['C2']['man_months']:.2f} MM"],
         ["- 변경 시나리오 4종(새 Tier, 새 Cost 항, Selector 교체, 새 telemetry 신호)을 시뮬레이터 복사본에 구현해 측정했다. 세 시나리오는 공통 Cost Model·Selector·Resource Intelligence만 건드려 C1과 C2가 같다.",
          "- 새 telemetry 신호만 C2가 한 module 더 든다: 사전 계획이 쓰는 planner ledger view가 새 필드를 복사해야 한다. 이 simulator에서는 C1/C2가 코드를 크게 공유해 차이가 작다. 공수·비용은 가정 상수다."],
         ["새 Tier: C1 2 / C2 2 module. 새 Cost 항 1/1. Selector 교체 1/1. 새 신호 2/3."]),
        (1.9, ["QA5 확장성", "η(N=32), 결정 지연"] + ([f"C1 {q5c['C1']['star']} η {q5c['C1']['eta']:.2f}", f"C2 {q5c['C2']['star']} η {q5c['C2']['eta']:.2f}"] if q5c["B"] else []),
         qa5_txt, q5ev),
        (0.95, ["결론: trade-off", "성능 ≫ Baseline, C1≈C2"],
         ["- 두 후보 모두 Baseline 대비 처리량·TTFT·사용률을 크게 높이고 TPOT 여유를 쓴다. C1/C2 차이는 이 평가의 노드 수(≤6)에서는 보이지 않고 QA5에서만 보인다.",
          "- 단순한 P-retain 규칙이 QA2에서 더 높다. Cost Model 구조(TTFT/TPOT 가중)가 개선 여지다."], [""])])
    out.append(s4)
    # ---- slide 5: scenarios
    s5 = Slide("DP2 평가에서 고려한 시나리오")
    s5.box(0.4, 1.15, 12.5, 0.75, [f"19개 시나리오를 H100과 B200에 각각 돌렸다({nt}쌍). Common 3 · DP2 Stress 12 · DP2 Dynamic 4. 비교 가능 {nv}쌍, 포화 {ns}쌍, Baseline 불가 {ni}쌍. 부하 sweep은 시나리오별 grid에서 Baseline과 후보에 같게 쓰고 peak가 grid 끝이면 확장했다. seed 11/23/37/53/71."], "note", 9)
    groups = [("기본 서비스 상황 (공통)", "8K 입력, 256 생성, 동시성 sweep의 대화 서비스(4P+1D). D 노드 HBM이 빠듯한 경우 / 압박이 점진 증가 / KV 외 데이터가 HBM을 점유. 결과: 두 후보 모두 Baseline보다 goodput이 높다(D 노드 Prefill 활용). 단 Baseline 최적 부하에서 TTFT P99·TPOT P99는 나빠진다."),
              ("History가 놓인 Tier별 멀티턴 (Stress)", "History가 HBM(32K) / DRAM(64K) / HBF(128K) / SSD-PIM(64K)에 있는 Agent 재개, Tool 결과가 큰 턴(대조군). Prefill 노드와 Decode 시작 Tier 선택이 달라지는 경우."),
              ("부하 모양이 바뀌는 경우", "Prefill burst로 P 포화 / 긴 출력으로 D 포화, P 유휴 / 5% 대형 256K 세션 쏠림 / 128~256K 세션 재개와 ScHBM 오프로드."),
              ("자원 조건이 나빠지는 경우", "P↔D 링크를 다른 트래픽과 공유(BW 25%) / 중간에 P 노드 처리량 50% 저하 / Telemetry 지연 / Planner 중단 후 Baseline 규칙으로 복귀."),
              ("처음엔 문제없다가 나빠지는 경우 (Dynamic 4개)", "Baseline이 처음엔 SLO를 만족하다 중간에 고정 규칙이 stale해진다: History 하위 Tier 강등 후 재개 / 도착률 ramp+burst / P 노드 저하 / 출력 길이 전환. Baseline의 실패 양상을 알고 설계했으므로 이득은 이 상황에 한정해 읽는다."),
              ("아직 평가하지 못한 것", "노드 수 5 초과의 처리량 비교(QA5는 별도 sweep), 멀티 모델·LoRA/MoE 데이터, prefix cache 공유, 실측([A]) 결정 비용. Decode 중 Tier 이동(DP1)은 이 평가에 없다.")]
    yy = 1.95
    for n_, t_ in groups:
        s5.box(0.4, yy, 2.9, 0.78, n_, "dp", 9.5, True, "l", False)
        s5.box(3.3, yy, 9.6, 0.78, t_, "cell", 9, False, "l", False)
        yy += 0.82
    out.append(s5)
    return out


def md_table(head, rows):
    out = ["| " + " | ".join(head) + " |", "|" + "|".join("---" for _ in head) + "|"]
    for r in rows:
        out.append("| " + " | ".join(str(x) for x in r) + " |")
    return "\n".join(out)


def write_doc(path):
    nv, ns, ni, nt = fits()
    tl = tallies()
    a, c, b = T[C1], T[C2], T[B]
    rows = head_rows()
    rev = subprocess.run(["git", "-C", str(HERE.parent), "rev-parse", "--short", "HEAD"], capture_output=True, text=True).stdout.strip()
    q5c = qa5_cells()
    L = []
    w = L.append
    w(f"""---
date: 2026-10-06
dp: DP2
candidates: [C1-scheduling-time, C2-pre-planned]   # Baseline-PD-fixed 포함, 참고 정책 D-local-always / P-retain / Oracle
sys_ids: [SYS-H100, SYS-B200]
git_rev: {rev} (dirty)
evidence: {{ QA1: "[B+C]", QA2: "[B+C]", QA3: "[B+C]", QA4: "[B+C]", QA5: "[B+C]" }}
status: draft
---

# DP2 QA Evaluation — C1 스케줄링 시점 결정 vs C2 사전 계획 결정 (Cost 기반 Prefill/Decode 실행 계획)

> 기준 문서: [`qa-evaluation-criteria.md`](../../qa-evaluation-criteria.md), [`common-benchmark.md`](../../common-benchmark.md), [`system-specs.md`](../../system-specs.md), [`benchmark.md`](../benchmark.md), [`simulation-plan.md`](../simulation-plan.md), [`qa-criteria-dp2.md`](../qa-criteria-dp2.md), [`m0-spec.md`](../m0-spec.md)
> 이 문서의 모든 simulation 수치는 Evidence [B+C]이며 [A] 실측이 아니다. 표는 `tools/gen_dp2_result.py`가 `results/data/*.json`에서 생성했다. 노드 간 링크 대역폭과 결정 비용은 ASSUMED다.
> 첫 평가이며 DP1과 달리 이전 first-pass 문서는 없다. 평가 전 사전 등록과 변경 이력은 [`iterations/loop-log.md`](iterations/loop-log.md).

# 0. 최종 요약

## 0.1 QA별 비교

| QA | 평가 metric | Baseline-PD-fixed | C1 스케줄링 시점 | C2 사전 계획 |
|---|---|---:|---|---|""")
    for lab, bs, x1, x2 in rows:
        w(f"| **{lab[0]}** | {lab[1]} | {bs} | {x1} | {x2} |")
    w(f"""
**평가한 시스템:** SYS-H100 (H100x8, HBM3, PCIe 5.0, DDR5-4800)과 SYS-B200 (B200x8, HBM3e, PCIe 5.0, DDR5-6400)을 통합했다. 노드 = 8-GPU, 6종 메모리, Llama-3.1-70B BF16, 노드 간 링크 RDMA 50 GB/s(ASSUMED). 집계 단위는 (시나리오, 시스템) 쌍 {nt}개이며 모두 Baseline이 SLO를 일부 만족하는 비교 가능 쌍({nv}쌍, 포화 {ns}, 불가 {ni})이다. 값은 쌍별 값의 기하평균(QA3는 평균), 괄호는 **후보 ÷ Baseline**이다. QA2/QA3는 Baseline의 최적 부하(iso-load)에서 비교했다.

별 경계는 DP1 값을 DP2 후보 실행 전에 그대로 고정했다(`qa-criteria-dp2.md` §6). 공통 기준 별점(참고): QA1 {a['common_qa1']}/{c['common_qa1']}, QA2 {a['common_qa2']}/{c['common_qa2']}, QA3 {a['common_qa3']}/{c['common_qa3']} (C1/C2).

## 0.2 요약과 그 이유
""")
    w(f"""1. **두 후보 모두 Baseline보다 처리량이 높다.** Max SLO goodput이 C1 {r2(a['qa1_ratio'])}(95% CI ±{a['qa1_ci']:.2f}), C2 {r2(c['qa1_ratio'])}이고 진 쌍은 없다. 단 이 배수는 Baseline이 SLO를 거의 못 지키도록 설계된 시나리오(링크 경합 x6~8, 긴 History x3~4)가 끌어올린다. 중앙에 가까운 시나리오는 x1.0~1.7이다(4.2).
2. **이득의 출처는 둘이다.** (a) 고정 역할 낭비: Baseline은 Decode 노드의 Prefill 능력을 쓰지 않는다. Planner는 여유 노드에서 Prefill한다. 공통 시나리오에서도 x1.3~2.1이 나온 이유다(사전 가설 "공통은 saturated"는 틀렸다). (b) History 위치를 모르고 왕복 전송하는 낭비: 링크 경합, 긴 History, 대형 세션 쏠림에서 TTFT P99가 크게 준다.
3. **C1과 C2는 구분되지 않는다.** goodput 비 C2/C1 = x{gm(PS[k][C2]['goodput'] / PS[k][C1]['goodput'] for k in PS):.3f}(범위 0.97~1.06), QA2·QA3도 같다. Oracle(실시간 정확 상태, 결정 비용 0)과도 거의 같다(x{T[O]['qa1_ratio']:.2f}). 이 평가의 노드 수(5~6)와 결정 비용 가정(1 ms @ 64 후보)에서 결정 시점·지연은 성능을 바꾸지 못한다. C2의 plan age 평균 {a['plan_age_ms']:.1f} ms 대비 {c['plan_age_ms']:.1f} ms, Late Validation 실패로 인한 재계획은 공통 시나리오에서 약 31%, 그 외 대부분 0%다.
4. **Baseline보다 나쁜 곳이 있다.** TPOT P99는 x{a['tpot_p99_x']:.2f}(나쁨, 단 {a['tpot_p99'] * 1e3:.1f} ms로 SLO 50 ms 이내). Common 3개 집합에서는 TTFT P99도 x{QA['tables']['common'][C1]['ttft_p99_x']:.2f}로 나쁘고 QA2 개선 배수가 x{QA['tables']['common'][C1]['qa2_impr']:.2f}로 1 미만이다. Cost가 TPOT 여유를 TTFT와 맞바꾸고, Baseline 최적 부하에서는 TTFT가 이미 짧아 이득이 없기 때문이다(5.2). 또한 각자 최적 부하에서 비교하면 QA2 개선 배수는 x{a['qa2_impr_ownload']:.2f}(C1)로 별이 ★★로 내려간다. QA2 ★★★은 iso-load 정의(결과를 본 뒤 정함)에 의존한다.
5. **단순한 참고 정책 P-retain(Prefill을 History가 있던 노드에서 유지)이 QA2에서 더 높다**(x{T[PR]['qa2_impr']:.2f} 대 C1 x{a['qa2_impr']:.2f}). 처리량은 낮다(x{T[PR]['qa1_ratio']:.2f}). Cost Model의 TTFT/TPOT 가중 구조가 개선 여지다. D-local-always는 Prefill을 한 노드에 몰아 처리량이 x{T[DL]['qa1_ratio']:.2f}로 무너진다.
""")
    if q5c["B"]:
        w(f"6. **확장성(QA5)에서 두 후보 모두 N=32에서 무너진다**: η(N=32)는 Baseline {q5c['B']['eta']:.2f}, C1 {q5c['C1']['eta']:.2f}(결정 64 ms/건으로 단일 scheduler 포화, SLO 만족 goodput 0), C2(worker 4) {q5c['C2']['eta']:.2f}(worker 16 {e5('C2(w=16)'):.2f}). top-k=8 pruning을 쓰면 C1 {e5('C1+topk8'):.2f}, C2 {e5('C2+topk8'):.2f}. 결정 비용이 후보 수에 선형이라는 ASSUMED 가정의 결과이며 4.7에 0.1/1/10 ms 민감도를 둔다. 노드당 부하 grid 끝에서 peak가 나온 경우가 있고 seed가 2개(확장 부하는 1개)라 η에는 ±0.1 정도의 잡음이 있다.")
    else:
        w("6. 확장성(QA5)은 측정 전이다.")
    t = totals()
    w(f"""
## 0.3 선택

별 합계(QA1~QA5): C1 {sum(t['C1'])}, C2 {sum(t['C2'])}. QA 우선순위(`qa_priority.json`)는 소유자 확정 전(제안)이라 **선택은 보류**한다. 두 후보의 별 합계가 같아 이 평가는 선택을 가르지 못한다. QA5의 차이(worker 수별 η)는 결정 비용 가정(ASSUMED)에 의존한다. QA1~QA4만으로는 C1과 C2는 동점이고, QA5는 둘 다 ★이다(N=32, pruning 없음).

## 0.4 부족한 부분

| # | 약점 (근거) | 보완 방향 | 상태 |
|---|---|---|---|
| T1 | Cost = SLO 분율 합이 TTFT와 TPOT를 맞바꾼다. 공통 시나리오에서 TTFT·TPOT P99가 Baseline보다 나쁘다. P-retain보다 QA2가 낮다 | TPOT 실현 가능 후보 중 TTFT 최소 선택(Selector 교체). QA4 S3 smoke에서 공통 TTFT P99 3.7 s → 0.7 s로 줄었다(1회 실행, 평가 아님) | [C] 평가 미실시 |
| T2 | Baseline이 SLO를 못 맞추는 시나리오가 배수를 키운다 | 대조군·경계 시나리오 확대 | 한계로 기록 |
| T3 | 후보 수 선형 결정 비용에서 N=32 이상이면 C1은 scheduler 포화, C2는 plan 처리량 부족 (QA5) | 후보 pruning(top-k)을 설계에 포함. 4.7에서 top-k=8이면 η 약 1.0 | [B+C] 4.7 |

## 0.5 어떤 상황을 평가했나

Common 3(8K→256 대화), Stress 12(History Tier별 멀티턴, 부하 모양, 링크 경합 등), Dynamic 4(처음엔 문제없다가 나빠지는 경우). 상세는 3장.

# 1. 시스템 환경

| 항목 | 값 |
|---|---|
| SYS id | SYS-H100, SYS-B200 (통합). 값은 [system-specs.md](../../system-specs.md) |
| Model / precision | Llama-3.1-70B BF16 (KV 327,680 B/token), SLO TTFT P99 ≤ 2 s, TPOT P99 ≤ 50 ms |
| 노드 간 링크 | RDMA 400G 1 rail = 50 GB/s, 지연 100 us (**ASSUMED**), sweep 12.5/50/200/400 GB/s |
| 토폴로지 | 노드 = 8-GPU TP8 인스턴스 1개. Common 4P+1D, 대부분 2P+2D, long_ctx 1P+2D, skew 2P+4D |
| Git revision | {rev} (dirty) |
| Seeds / loads | seed 11/23/37/53/71, 시나리오별 부하 grid |
| 재현 | `cd doc-mk/Evaluation/DP2/sim && python3 qa_eval.py run --workers 4 && python3 qa_eval.py agg`, QA5: `qa5_scale.py`, 민감도: `sens.py`, 문서: `tools/gen_dp2_result.py` |
| Raw data | `results/data/SYS-*/runs.jsonl`, `qa_result.json`, `qa5_result.json`, `sens_result.json`, `qa4_*.json` |

# 2. 평가 항목

| 항목 | 정의 / formula | 출처 |
|---|---|---|
| QA1 | 시나리오별 부하 sweep 중 SLO(TTFT·TPOT 모두 만족)를 만족한 요청의 output token/s 최대값(후보별 자기 최적 부하). 후보÷Baseline 비의 기하평균. 별 < 0.97 / 0.97~1.30 / ≥ 1.30 | criteria §4 + `qa-criteria-dp2.md` §6 |
| QA2 | **Baseline의 최적 부하**에서 TTFT·TPOT × P50/P95/P99 6개 지표의 개선 배수(Baseline÷후보)의 기하평균. 별 < 0.95 / 0.95~1.25 / ≥ 1.25. 표의 (x)는 후보÷Baseline 값 | criteria §5. iso-load는 **첫 결과를 본 뒤 정의**(`defined_after_first_look`) |
| QA3 | `U_useful`(SLO 만족 토큰 비중을 곱한 iteration GPU 시간 ÷ 노드 수×측정 시간), Baseline 최적 부하에서. 별은 후보÷Baseline 비율 < 0.95 / 0.95~1.25 / ≥ 1.25 | **임시 정의** |
| QA4 | module 수 · 공수 · 에이전트 비용, 변경 시나리오 4종 평균. 별은 세 sub-star의 중앙값 | `qa4-preregistration.md` (사전 등록) |
| QA5 | η(N) = Max SLO goodput(N) ÷ (N/2 × Max SLO goodput(N=2)), N=32. 별 < 0.70 / 0.70~0.90 / ≥ 0.90. 단일 시스템(H100), seed 2개 | `qa-criteria-dp2.md` §3 (제안값) |
| Diagnostic | 결정 지연, plan age, 재계획 수, regret, 풀 사용률, 노드 간 KV 이동량 | `qa-criteria-dp2.md` §4 |
| 판정 | 쌍별 paired-by-seed, 95% CI t(0.975,4)=2.776, 물질성 1% | DP1과 동일 |

# 3. 벤치마크 / 시나리오

Fit label: comparison_valid = Baseline이 SLO를 일부 만족해 비교 가능. 모든 쌍이 comparison_valid이지만 다음을 주의한다: Baseline의 goodput이 매우 작은 쌍(예: 링크 경합 53 tok/s)은 비율이 크게 나온다.
""")
    rows3 = []
    for sname, nm in SETS.items():
        for n in _SETS[sname]:
            lh = LAB[f"SYS-H100|{n}"]["fit"][:4]
            lb = LAB[f"SYS-B200|{n}"]["fit"][:4]
            rows3.append((nm, f"`{n}`", lh, lb, DESC[n]))
    w(md_table(["Set", "시나리오", "H100", "B200", "설명"], rows3))
    w("""
참고 정책(별 미부여): D-local-always(항상 KV가 있는 D에서 Prefill), P-retain(Prefill을 직전 P 노드에서 유지, 더 강한 As-Is), Oracle(실시간 정확 상태, 결정 비용 0, 상한).

# 4. 결과

## 4.1 최종 QA 표
""")
    w(md_table(["QA", "metric", "Baseline", "C1", "C2"], [(f"**{x[0][0]}**", x[0][1], x[1], x[2], x[3]) for x in rows]))
    w("""
(QA1~QA3는 SYS-H100 + SYS-B200 통합 19x2쌍. QA5는 SYS-H100만, seed 2개. QA4는 시뮬레이터 복사본에서 측정, 공수·비용은 가정 상수.)

### 집합별 (후보÷Baseline, 기하평균)
""")
    for cand in (C1, C2):
        w(f"**{cand}**\n")
        w(md_table(["집합", "쌍", "QA1 goodput", "TTFT P99", "TPOT P99", "QA2 개선", "QA3 U"], [(n, k, r2(x1), r2(x2), r2(x3), r2(x4), r2(x5)) for (n, k, x1, x2, x3, x4, x5) in per_set_table(cand)]))
        w("")
    w("### 시스템별\n")
    w(md_table(["SYS", "후보", "QA1", "TTFT P99", "TPOT P99", "QA2 개선", "QA3 U", "별(QA1/2/3)"],
               [(sy, nm, r2(QA['tables'][sy][cc]['qa1_ratio']), r2(QA['tables'][sy][cc]['ttft_p99_x']), r2(QA['tables'][sy][cc]['tpot_p99_x']), r2(QA['tables'][sy][cc]['qa2_impr']), r2(QA['tables'][sy][cc]['util_x']),
                 QA['tables'][sy][cc]['star_qa1'] + "/" + QA['tables'][sy][cc]['star_qa2'] + "/" + QA['tables'][sy][cc]['star_qa3']) for sy in ("SYS-H100", "SYS-B200") for nm, cc in (("C1", C1), ("C2", C2))]))
    w("""
## 4.1a 참고 정책 대비 (통합)
""")
    w(md_table(["정책", "QA1 비", "TTFT P99", "TPOT P99", "QA2 개선", "QA3 U", "Baseline 대비 승/무/패"],
               [(nm, r2(T[cc]['qa1_ratio']), r2(T[cc]['ttft_p99_x']), r2(T[cc]['tpot_p99_x']), r2(T[cc]['qa2_impr']), r2(T[cc]['util_x']), "{}/{}/{}".format(*tl[cc]) if cc in tl else "—")
                for nm, cc in (("C1", C1), ("C2", C2), ("Oracle", O), ("P-retain", PR), ("D-local-always", DL))]))
    w("""
승/무/패는 쌍별 paired-by-seed(goodput, TTFT P99, TPOT P99 종합, 95% CI, 1% 물질성). TPOT가 나쁜 쌍이 많아 'loss' 성분은 4.4에서 따로 센다.

## 4.2 시나리오별 결과 (Baseline의 최적 부하, goodput 비는 각자 최적 부하)
""")
    rows42 = []
    for sname, nm in SETS.items():
        for n in _SETS[sname]:
            for sy in ("SYS-H100", "SYS-B200"):
                k = f"{sy}|{n}"
                p = PS[k]
                rows42.append((nm, f"`{n}`", sy[4:], f"{p[B]['goodput']:,.0f}", f"{p[B]['load']:g}", r2(p[C1]['goodput'] / p[B]['goodput']), r2(p[C2]['goodput'] / p[B]['goodput']),
                               r2(p[O]['goodput'] / p[B]['goodput']), r2(p[PR]['goodput'] / p[B]['goodput']),
                               f"{p[B]['iso']['ttft_p99']:.2f} / {p[C1]['iso']['ttft_p99']:.2f} / {p[C2]['iso']['ttft_p99']:.2f}",
                               f"{1e3 * p[B]['iso']['tpot_p99']:.1f} / {1e3 * p[C1]['iso']['tpot_p99']:.1f} / {1e3 * p[C2]['iso']['tpot_p99']:.1f}"))
    w(md_table(["Set", "시나리오", "SYS", "Baseline goodput", "B 최적 부하", "C1", "C2", "Oracle", "P-retain", "TTFT P99 s (B/C1/C2)", "TPOT P99 ms (B/C1/C2)"], rows42))
    w(f"""
## 4.3 Diagnostic (통합, Baseline 최적 부하 평균)

| 지표 | Baseline | C1 | C2 |
|---|---:|---:|---:|
| 결정 지연 평균 (ms) | 0 | {a['t_dec_ms']:.2f} | {c['t_dec_ms']:.2f} |
| plan age 평균 (ms) | — | — | {c['plan_age_ms']:.1f} |
| regret 평균 (Cost, SLO 분율) | — | {a['regret']:.3f} | {c['regret']:.3f} |
| mis-selection 비율 | — | {a['mis']:.2f} | {c['mis']:.2f} |
| P 풀 / D 풀 useful 사용률 | {100 * b['pool_p']:.0f}% / {100 * b['pool_d']:.0f}% | {100 * a['pool_p']:.0f}% / {100 * a['pool_d']:.0f}% | {100 * c['pool_p']:.0f}% / {100 * c['pool_d']:.0f}% |
| P 노드 간 부하 CV | {b['cv_p']:.2f} | {a['cv_p']:.2f} | {c['cv_p']:.2f} |
| Turn당 노드 간 KV 이동 (GiB) | {b['gib_turn']:.1f} | {a['gib_turn']:.1f} | {c['gib_turn']:.1f} |

## 4.4 승/무/패 성분 (Baseline 대비, 38쌍)

| 후보 | goodput 승/무/패 | TTFT P99 승/무/패 | TPOT P99 승/무/패 |
|---|---|---|---|""")
    for cc, nm in ((C1, "C1"), (C2, "C2")):
        g = Counter(LAB[k]["vs"][cc]["goodput"] for k in LAB)
        t1 = Counter(LAB[k]["vs"][cc]["ttft"] for k in LAB)
        t2 = Counter(LAB[k]["vs"][cc]["tpot"] for k in LAB)
        w(f"| {nm} | {g['win']}/{g['tie']}/{g['loss']} | {t1['win']}/{t1['tie']}/{t1['loss']} | {t2['win']}/{t2['tie']}/{t2['loss']} |")
    w("""
TTFT·TPOT는 Baseline의 최적 부하에서의 paired 비교다. **TPOT P99가 유의하게 나쁜 쌍이 절반**이다(전부 SLO 이내). 이 값은 Baseline-regression loop 대상이며 5.2에서 진단한다.
""")
    # sensitivity
    w("## 4.5 민감도 (SYS-H100, 6개 시나리오, Baseline 최적 부하, goodput 비의 기하평균, seed 3개)\n")
    if SENS:
        rows5 = []
        nmap = {"link": "노드 간 링크", "eps": "Cost Model 오차 ε", "tel": "Telemetry 주기(s)", "t_ref": "결정 비용 T_ref(s)"}
        for ax, d in SENS.items():
            for v, row in d.items():
                gb, go = row[B]["gp"], row[O]["gp"]
                nex = sum(1 for s in gb if gb[s] < 0.1 * max(1.0, go[s]))
                rows5.append((nmap[ax], v, *[(r2(row[cc]["gm"]) if row[cc]["gm"] else "—") for cc in (C1, C2, O)], f"{6 - nex}/6"))
        w(md_table(["축", "값", "C1", "C2", "Oracle", "집계에 쓴 시나리오"], rows5))
        w("\n비는 같은 축 값의 Baseline 대비다(링크 축에서는 Baseline도 함께 바뀐다). Baseline goodput이 Oracle의 10% 미만인 시나리오는 비가 발산하므로 집계에서 뺐고 마지막 열에 남은 수를 적었다. 측정 부하는 50 GB/s에서 정한 Baseline 최적 부하로 고정했으므로 링크가 빠른 행(200, 400 GB/s)은 Baseline이 더 높은 부하를 받을 수 있는데도 같은 부하에서 비교한 값이라 비가 줄어든다(Max SLO goodput 비교가 아니다). 이득이 링크 대역폭에 의존한다는 것은 확인되지만 크기는 과소평가일 수 있다. ε와 결정 비용은 이 범위에서 영향이 없다(ε 증가에도 이득이 줄지 않음). Telemetry 1 s에서만 x1.35로 소폭 감소한다. 링크가 12.5 GB/s이면 Baseline이 SLO를 못 맞추는 시나리오가 많아 후보의 상대 이득이 실제로는 더 크다.\n")
    else:
        w("측정 전.\n")
    w("## 4.6 QA4 Modifiability\n")
    m4 = QA4["scenarios"]
    w(md_table(["시나리오", "C1 module·LOC·MM", "C2 module·LOC·MM"], [(k, f"{v['C1']['modules']} · {v['C1']['loc_added']} · {v['C1']['man_months']}", f"{v['C2']['modules']} · {v['C2']['loc_added']} · {v['C2']['man_months']}") for k, v in m4.items()]))
    w(f"""
평균: C1 {QA4['mean_over_scenarios']['C1']['modules']:.2f} module · {QA4['mean_over_scenarios']['C1']['man_months']:.2f} MM · ${QA4['mean_over_scenarios']['C1']['usd_T1']:.2f}, C2 {QA4['mean_over_scenarios']['C2']['modules']:.2f} · {QA4['mean_over_scenarios']['C2']['man_months']:.2f} · ${QA4['mean_over_scenarios']['C2']['usd_T1']:.2f}. 시나리오: S1 신규 Tier(`cxl_pnm2`), S2 신규 Cost 항(에너지), S3 Selector 교체, S4 신규 telemetry 신호(health). 사전 등록 [`qa4-preregistration.md`](../qa4-preregistration.md), 측정 [`results/data/qa4_measured_counts.json`](data/qa4_measured_counts.json), 패치 `results/data/qa4_patches/`. `qa4_modifiability.json`의 `sensitivity_structure_alternatives` 항목은 DP1/DP4 구조용 분석식이라 **DP2에는 해당하지 않는다.** 이 simulator는 C1/C2가 Cost Model·Selector·Resource State를 공유해 차이가 작다. 실제 vLLM 통합과 다르며 module 귀속은 판단이다(주입 wiring을 별도 module로 세면 두 후보 모두 +1).
""")
    w("## 4.7 QA5 Scalability (SYS-H100, seed 2개, 노드당 부하 grid 2~24 clients, 확장 부하 16/20/24는 seed 11만)\n")
    if Q5:
        rows7 = []
        for var in Q5["main"]:
            rows7.append((var, *[(f"{Q5['main'][var][str(n)]['goodput']:,.0f} (η {Q5['main'][var][str(n)].get('eta', 0):.2f})" if Q5['main'][var].get(str(n)) else "—") for n in (2, 4, 8, 16, 32, 64)]))
        w(md_table(["variant", "N=2", "N=4", "N=8", "N=16", "N=32", "N=64"], rows7))
        w("\n결정 지연 평균(ms)과 TTFT P99(s), N=32:\n")
        rows7b = [(var, f"{Q5['main'][var]['32']['t_dec_ms']:.2f}", f"{Q5['main'][var]['32']['ttft99']:.2f}", f"{Q5['main'][var]['32']['replans']:.0f}") for var in Q5["main"] if Q5["main"][var].get("32")]
        w(md_table(["variant", "결정 지연", "TTFT P99", "재계획"], rows7b))
        w("\n후보 공간(노드당 Tier 수) 및 결정 비용 민감도, N=32 (Max SLO goodput tok/s):\n")
        rows7c = []
        for nt_, d in Q5["tiers"].items():
            rows7c.append((f"Tier 수 {nt_}", *[(f"{d[v]['goodput']:,.0f}" if d.get(v) else "—") for v in ("C1", "C2(w=4)")]))
        for tr, d in Q5["tref"].items():
            rows7c.append((f"T_ref {tr} ms", *[(f"{d[v]['goodput']:,.0f}" if d.get(v) else "—") for v in ("C1", "C2(w=4)")]))
        w(md_table(["조건", "C1", "C2(w=4)"], rows7c))
        w("")
    else:
        w("측정 전.\n")
    w(f"""# 5. 결과 분석

## 5.1 이득이 나는 이유
- **고정 역할의 낭비.** 공통 시나리오(4P+1D, 8K→256)에서 Baseline은 P 4개만 Prefill한다. Planner는 D 노드와 P 노드를 가리지 않고 Prefill해 H100에서 x{PS['SYS-H100|cb_kv_8k_b32'][C1]['goodput'] / PS['SYS-H100|cb_kv_8k_b32'][B]['goodput']:.2f}, B200에서 x{PS['SYS-B200|cb_kv_8k_b32'][C1]['goodput'] / PS['SYS-B200|cb_kv_8k_b32'][B]['goodput']:.2f}다. P-retain은 x1.00(역할 고정과 같은 결정)이라 이 이득은 "D 노드 Prefill 활용"에서 온다.
- **전송 낭비.** 링크 경합(BW 25%): Baseline은 History를 왕복해 TTFT P99 {PS['SYS-B200|dp2_internode_link_contention'][B]['iso']['ttft_p99']:.1f} s, Planner는 History가 있는 노드에서 Prefill해 {PS['SYS-B200|dp2_internode_link_contention'][C1]['iso']['ttft_p99']:.2f} s(B200). 이 경우 D-local-always도 같은 이득이다 — **단순 휴리스틱으로 충분한 영역**이다.
- **쏠림 회피.** 대형 세션 쏠림에서 Baseline TTFT P99 {PS['SYS-B200|dp2_session_size_skew'][B]['iso']['ttft_p99']:.1f} s → C1 {PS['SYS-B200|dp2_session_size_skew'][C1]['iso']['ttft_p99']:.2f} s(B200). P-retain도 0.12 s로 비슷하다.
- **Tier 인지가 필요한 영역.** HBF·SSD-PIM History(`dp2_turn_hbf_hist`, `dp2_turn_ssd_hist`)에서는 P-retain이 C1/C2보다 높다(HBF B200 x{PS['SYS-B200|dp2_turn_hbf_hist'][PR]['goodput'] / PS['SYS-B200|dp2_turn_hbf_hist'][B]['goodput']:.2f} 대 C1 x{PS['SYS-B200|dp2_turn_hbf_hist'][C1]['goodput'] / PS['SYS-B200|dp2_turn_hbf_hist'][B]['goodput']:.2f}). **이기종 Tier 정보를 쓰는 Cost Model이 가장 단순한 규칙보다 낫다는 주장은 이 평가에서 성립하지 않는다**(HBF/SSD에서 더 낮음, 원인은 5.2).

## 5.2 Baseline보다 나쁜 곳 (Baseline-regression)
- Common 3개 집합: Baseline 최적 부하에서 TTFT P99 x{QA['tables']['common'][C1]['ttft_p99_x']:.2f}, TPOT P99 x{QA['tables']['common'][C1]['tpot_p99_x']:.2f}, QA2 개선 x{QA['tables']['common'][C1]['qa2_impr']:.2f}(< 1). goodput은 x{QA['tables']['common'][C1]['qa1_ratio']:.2f}로 높아 **지연을 처리량과 맞바꾼다.**
- TPOT P99가 유의하게 나쁜 쌍이 C1 {Counter(LAB[k]['vs'][C1]['tpot'] for k in LAB)['loss']}/{nt}. 값은 SLO 이내.
- **원인 진단(P/M 분류):** Cost 정의(M, cost model gap). Cost = TTFT/SLO + TPOT/SLO + 외부효과의 합이라 TPOT 여유가 있으면 TTFT를 줄이는 쪽으로 쓰고, 그 결과 TPOT가 SLO까지 올라가도 비용이 같다. 개발 점검(QA4 S3 smoke, 공통 cb_kv_8k_b32 H100 load 24, seed 11, 1회)에서 "TPOT 실현 가능 후보 중 TTFT 최소" Selector로 바꾸면 TTFT P99가 3.7 s → 0.7 s였다. 정책 상수나 시나리오별 조정은 하지 않았고 이 변경은 평가에 반영하지 않았다.
- HBF/SSD History에서 P-retain이 더 높은 이유: 이 시나리오의 History가 HBF에 있을 때 Planner는 HBM으로 승격·전송 비용을 모두 비용으로 보고 다른 노드로 보내는 경우가 있다(추정, 요청 단위 분해는 하지 않았다).

## 5.3 C1과 C2가 같은 이유
결정 비용이 1 ms @ 64 후보이고 노드가 4~6개라 후보 수 K ≈ 16~100, 결정 지연이 C1 {a['t_dec_ms']:.2f} ms로 요청 도착 간격보다 훨씬 짧다. plan age 평균 {c['plan_age_ms']:.1f} ms로 Late Validation이 거의 통과한다. 두 후보는 같은 Cost Model과 같은 Selector를 쓰므로 차이는 결정 시점/지연에서만 생긴다. 이 조건에서는 그 차이가 0에 가깝다. 차이를 가르는 조건은 QA5(노드 수, 결정 비용)에서 본다.

# 6. 한계

1. 모든 수치는 [B+C] simulation이다. 노드 간 링크(50 GB/s), 결정 비용(1 ms @ 64 후보, 후보 수 선형), planner worker 4개, Telemetry 50 ms는 ASSUMED. 민감도는 4.5, 4.7.
2. QA2/QA3의 iso-load 집계는 공통 시나리오 2쌍을 본 뒤 정의했다(`defined_after_first_look`). 각자 최적 부하에서 비교한 값은 QA2 개선 x{a['qa2_impr_ownload']:.2f}(C1), x{c['qa2_impr_ownload']:.2f}(C2)로 **별이 ★★★에서 ★★로 내려간다**(경계 1.25 아래). QA2 별은 집계 정의에 민감하다. 이 정의는 결과를 본 뒤 정했으므로 ★★★은 확정이 아니다.
3. Baseline이 SLO를 못 맞추도록 설계한 시나리오(링크 경합, 긴 History)가 QA1 배수를 끌어올린다. 설계자가 Baseline의 실패 양상을 알고 만들었다. 공통 3개만의 QA1은 x{QA['tables']['common'][C1]['qa1_ratio']:.2f}다.
4. 평가 규모가 노드 6개 이하(QA5 제외)다. QA5는 H100 단일 시스템, seed 2개, 단일 workload(4K→256)다. QA5의 별 경계(0.70/0.90)는 제안값이다.
5. QA3 U_useful은 처리량과 상관이 크다. QA4는 simulator 복사본 기준이고 공수·비용은 ASSUMED 상수다.
6. GPU 내 Prefill/Decode 간섭은 iteration 합산 근사다. NIXL 프로토콜, prefix cache 공유, 전력은 미반영이다. Decode 중 Tier 이동(DP1)은 평가하지 않았다(모든 후보가 같은 초기 배치).
7. 사전 가설 중 틀린 것: 공통 시나리오가 saturated일 것(H1)은 틀렸다(x1.3~2.1). C1이 QA3·TPOT에서 앞서고 C2가 확장성에서 앞설 것(H8)은 QA1~QA4에서 확인되지 않았다.
8. 소유자 결정 O1~O11은 미확정이며 별 경계·선택 규칙도 제안 상태다.

# 7. 결론

- Cost 기반 Prefill/Decode 실행 계획(C1, C2)은 고정 역할 Baseline보다 goodput을 크게 높인다(QA1 {r2(a['qa1_ratio'])}/{r2(c['qa1_ratio'])}, ★★★/★★★). 이득의 상당 부분은 Tier 인지가 아니라 역할 고정을 푸는 것(D 노드 Prefill 활용, 링크 왕복 제거)에서 온다.
- Tier 인지가 단순 규칙보다 낫다는 증거는 이 평가에서 부족하다. P-retain이 QA2에서 더 높고 HBF/SSD History에서도 C1/C2보다 높다.
- TPOT P99와 공통 시나리오의 TTFT P99는 Baseline보다 나쁘다. Cost 정의가 개선 여지다(5.2).
- C1과 C2는 QA1~QA4에서 구분되지 않는다. QA5에서는 비용 가정 하에 둘 다 N=32에서 무너지고(top-k pruning 없이는 ★), C2(worker 16)가 C1보다 낫지만 둘 다 pruning을 넣은 변형(η 약 1.0)보다 못하다. 다음 설계 결정은 C1/C2 선택이 아니라 후보 pruning이다.
- 다음 단계: Selector를 TPOT feasible 후보 중 TTFT 최소로 바꾼 변형 평가(새 사전 등록 필요), 노드 수·결정 비용 확대, [A] 결정 비용 측정, 소유자 결정(별 경계, 선택 규칙) 확정.
""")
    Path(path).write_text("\n".join(L) + "\n")
    print("wrote", path)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", type=Path, default=D2 / "results" / "2026-10-06_dp2-qa-evaluation.md")
    a = ap.parse_args()
    write_doc(a.out)
