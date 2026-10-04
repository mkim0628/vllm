#!/usr/bin/env python3
"""Build the DP evaluation appendix slide(s) and the complement-design tactics slide (DP1) from result data.

    python tools/gen_dp_pptx.py --out-dir doc-mk/DP1 [--preview-dir DIR]

Needs python-pptx (+ Pillow for --preview-dir). Base template: doc-mk/DP1/DP-memory-backend-if.pptx (slide 9 frame).
Numbers come from tools/gen_dp1_result.py (RT/P/PRIO) so slide and result doc cannot diverge.
"""
from __future__ import annotations

import argparse
import copy
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import gen_dp1_result as g  # noqa: E402
from dp_selection import select  # noqa: E402

STY = {
    "dp": ("DCE9F5", "4D7EA8", "1A1A1A"), "head": ("1F4E79", "1F4E79", "FFFFFF"),
    "c2": ("E6E0F4", "7B66B0", "1A1A1A"), "rm": ("FDEBD3", "C98A3C", "1A1A1A"),
    "cell": ("FFFFFF", "BFBFBF", "1A1A1A"), "note": ("F2F2F2", "BFBFBF", "404040"),
    "sel": ("E3F1E3", "5B9B5B", "1A1A1A"), "warn": ("FFF8EC", "C98A3C", "1A1A1A"),
}
FONT_PATH = "/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc"


def _font(sz):
    from PIL import ImageFont
    return ImageFont.truetype(FONT_PATH, max(8, int(sz * 110 / 72)))


def wrap(text, width_in, size):
    """Pre-wrap to the box width (110 px/in, 8% safety)."""
    from PIL import Image, ImageDraw
    d = ImageDraw.Draw(Image.new("RGB", (10, 10)))
    f = _font(size)
    maxw = (width_in - 0.1) * 110 * 0.92
    out, cur = [], ""
    for ch in text:
        if d.textlength(cur + ch, font=f) > maxw and cur:
            out.append(cur)
            cur = ch.lstrip()
        else:
            cur += ch
    if cur:
        out.append(cur)
    return out


class Slide:
    def __init__(self, title):
        self.title, self.E = title, []

    def box(self, x, y, w, h, text, sty, size=8.5, bold=False, align="l", top=True):
        paras = []
        for para in (text if isinstance(text, list) else [text]):
            paras += wrap(para, w, size) or [""]
        self.E.append(dict(x=x, y=y, w=w, h=h, lines=paras, sty=sty, size=size, bold=bold, align=align, top=top))


def stars(c):
    return g.stars_combined()[c]


def system_slide():
    """Memory configuration of the evaluated systems (capacity, host link, bandwidth, compute capability, what the simulator uses)."""
    from model import load_profile
    loaded = {sid: load_profile(g.SIM / "configs", sid)[0] for sid in g.SYSIDS}
    ms = {sid: loaded[sid].memories for sid in g.SYSIDS}
    prof = g.json.load(open(g.SIM / "configs" / "systems.json"))["profiles"]
    gen = prof[g.SYSIDS[0]]["generation"]
    gpu = {sid: loaded[sid].gpu_compute_flops / 8 / 1e12 for sid in g.SYSIDS}   # dense FP16 per GPU (domain total / 8 GPUs)
    pct = lambda n: " / ".join(dict.fromkeys(f"{ms[sid][n].compute_flops / 1e12 / gpu[sid] * 100:.2g}%" for sid in g.SYSIDS))
    s = Slide("DP1 평가 시스템 - 메모리 구성 (H100x8 / B200x8, 값이 다르면 H100 / B200)")
    cols = [("메모리", 0.4, 2.1), ("용량", 2.5, 1.6), ("연결 (host와)", 4.1, 2.9), ("대역폭 (외부 / 내부)", 7.0, 2.2), ("연산 능력 (FP16)과 지원 연산", 9.2, 3.7)]
    for name, x, w in cols:
        s.box(x, 1.15, w, 0.32, name, "head", 10, True, "ctr", False)
    dd = lambda vals: " / ".join(dict.fromkeys(vals))
    cap = lambda n: dd([(f"{ms[sid][n].capacity_bytes / 2**40:g} TiB" if ms[sid][n].capacity_bytes >= 2**40 and n != "hbm" else f"{ms[sid][n].capacity_bytes / 2**30:,.0f} GiB") for sid in g.SYSIDS])
    bw = lambda n, attr: dd([f"{getattr(ms[sid][n], attr) / 1e9:,.0f}" for sid in g.SYSIDS])
    ops = "QK_GEMM, SOFTMAX, AV_GEMM, CAUSAL_MASK"
    comp = lambda n: dd([f"{ms[sid][n].compute_flops / 1e12:g}" for sid in g.SYSIDS])
    rows = [
        ("HBM", cap("hbm") + " (GPU 8장 합)", "GPU 온패키지", f"{bw('hbm', 'ext_bw')} GB/s (GPU 합)", f"GPU FP16 dense {' / '.join(f'{gpu[sid]:,.0f}' for sid in g.SYSIDS)} TFLOPS/GPU (참고, 8장 합 {' / '.join(f'{gpu[sid] * 8:,.0f}' for sid in g.SYSIDS)}) · GPU가 attention·FFN 실행"),
        ("Samsung Custom HBM (ScHBM)", cap("custom_hbm") + " (노드 1개)", f"CPU와 {gen['host_link']} x16, GPU→host→ScHBM 2홉 (GPU 직접 접근 불가)", f"{bw('custom_hbm', 'ext_bw')} GB/s / {bw('custom_hbm', 'int_bw')} GB/s", f"{comp('custom_hbm')} TFLOPS (GPU 1장의 {pct('custom_hbm')}) · {ops} (attention 오프로드)"),
        ("CXL-PNM", cap("cxl_pnm") + " (내부 DRAM)", f"{gen['cxl']}, host 경유", f"{bw('cxl_pnm', 'ext_bw')} GB/s / {bw('cxl_pnm', 'int_bw')} GB/s", f"{comp('cxl_pnm')} TFLOPS (GPU 1장의 {pct('cxl_pnm')}) · {ops} (attention 오프로드)"),
        ("DRAM (host)", cap("dram"), f"GPU와 {gen['host_link']} x16 ({gen['dram'].split('-')[0]})", f"{bw('dram', 'ext_bw')} GB/s / {bw('dram', 'int_bw')} GB/s", "—"),
        ("HBF", cap("hbf"), "GPU 직접 접근 (UCIe), PCIe 아님", f"읽기 {bw('hbf', 'ext_bw')} GB/s, 쓰기 {bw('hbf', 'write_bw')} GB/s", "—"),
        ("SSD-PIM", cap("ssd_pim"), gen["ssd"], f"{bw('ssd_pim', 'ext_bw')} GB/s / {bw('ssd_pim', 'int_bw')} GB/s", f"{comp('ssd_pim')} TFLOPS (GPU 1장의 {pct('ssd_pim')}) · GEMV (벡터 DB 유사도 계산만)"),
    ]
    y = 1.5
    for r in rows:
        for (name, x, w), v in zip(cols, r):
            s.box(x, y, w, 0.62, v, "dp" if name == "메모리" else "cell", 9.5, name == "메모리", "l", False)
        y += 0.64
    s.box(0.4, y + 0.08, 12.5, 1.55, [
        "시뮬레이션 반영: 용량, 외부·내부 대역폭, 지연, 쓰기 대역폭, 연산 능력과 지원 연산을 모두 쓴다. attention을 오프로드할 수 있는 tier는 4개 연산(QK_GEMM, SOFTMAX, AV_GEMM, CAUSAL_MASK)과 연산 능력을 모두 가진 ScHBM과 CXL-PNM뿐이며, 그때의 지연은 max(내부 BW 기반 읽기 시간, 연산 시간) + 활성 전송 + layer별 왕복으로 계산한다. SSD-PIM은 GEMV로 벡터 DB 유사도 계산에만 쓴다.",
        "미반영: HBF의 쓰기 증폭(3.0)과 endurance(100 PB), PCIe/CXL 프로토콜 오버헤드(링크는 이론 대역폭), 전력.",
        "값의 출처: ScHBM 용량·내부 BW·연산은 페어링 GPU 상대 규칙(용량 2배, 내부 BW 2배, 연산 20%), CXL-PNM 연산(FP32 1.64 TFLOPS의 2배), HBF·SSD-PIM 일부 값은 ASSUMED. 상세: system-specs.md"], "note", 9)
    return s


def qa_slides():
    """Results deck: (1) result table + brief system info + selection, (2)(3) why each QA value comes out that way, (4) covered scenarios."""
    import math as _m
    o = g.overall_selection()
    st = o["stars"][g.MERGED]
    G = g.RTM["sets"]["combined"]
    Qf = g.RM["combined"]["qa_feasible"]
    T = g.RM["combined"]["tally"]
    B, C1, C2 = g.B, g.C1, g.C2
    m = g.QA4["mean_over_scenarios"]
    sc4 = g.QA4["scenarios"]
    nm = {C1: "C1", C2: "C2", None: "구분 불가"}
    pairs = g.valid_pairs([x for x, _ in g.SETS])
    gm = lambda c, f: g.gm_abs(pairs, c, f)
    rt = lambda c, f: gm(c, f) / gm(B, f)
    gp = lambda p: p["max_goodput_tps"]
    t99, t50 = (lambda p: p["ttft_p99_ms"]), (lambda p: p["ttft_p50_ms"])
    o99, o50 = (lambda p: p["tpot_p99_ms"]), (lambda p: p["tpot_p50_ms"])
    hb = lambda p: p["tier_occ_gib"]["hbm"]
    imp = lambda c, mm: _m.exp(sum(_m.log(G[c]["qa2"]["improvement_vs_baseline"][f"{mm}_{p}_ms"]) for p in ("p50", "p95", "p99")) / 3)
    E1, E2 = G[C1]["eff"], G[C2]["eff"]

    def pair(key):
        for lab, _ in g.SETS:
            if key in g.RM[lab]["per_scenario"]:
                return g.RM[lab]["per_scenario"][key]
        raise KeyError(key)

    def ex(key, c, f):
        return pair(key)[c][f]

    # ---------------- slide 1: table + brief system + selection ----------------
    s = Slide("DP1 평가 결과 - QA별 정량 metric (H100 + B200 통합)")
    cols = [("QA / 평가 metric", 0.4, 3.0), ("Baseline", 3.4, 1.9), ("C1 Resource-driven", 5.3, 3.8), ("C2 Behavior-driven", 9.1, 3.8)]
    y = 1.15
    for name, x, w in cols:
        s.box(x, y, w, 0.32, name, "head", 10, True, "ctr", False)
    h_prev = [0.34]

    def row(label, base, a, b, h=0.5, size=9.5):
        nonlocal y
        y += h_prev[0]
        s.box(0.4, y, 3.0, h, label, "dp", 9, True, "l", False)
        s.box(3.4, y, 1.9, h, base, "cell", size, False, "ctr", False)
        s.box(5.3, y, 3.8, h, a, "cell", size, False, "ctr", False)
        s.box(9.1, y, 3.8, h, b, "cell", size, False, "ctr", False)
        h_prev[0] = h + 0.02

    row(["QA1 Throughput", "Max SLO goodput (tok/s) ↑"], f"{gm(B, gp):,.0f}", f"{st[C1]['QA1']}  {gm(C1, gp):,.0f} (x{rt(C1, gp):.2f})", f"{st[C2]['QA1']}  {gm(C2, gp):,.0f} (x{rt(C2, gp):.2f})")
    row(["QA2 Latency — TTFT", "P99 · P50 (ms) ↓"], f"P99 {gm(B, t99):,.0f} · P50 {gm(B, t50):,.0f}",
        f"P99 {gm(C1, t99):,.0f} (x{rt(C1, t99):.2f}) · P50 {gm(C1, t50):,.0f} (x{rt(C1, t50):.2f})", f"P99 {gm(C2, t99):,.0f} (x{rt(C2, t99):.2f}) · P50 {gm(C2, t50):,.0f} (x{rt(C2, t50):.2f})")
    row(["QA2 Latency — TPOT", "P99 · P50 (ms) ↓"], f"P99 {gm(B, o99):,.1f} · P50 {gm(B, o50):,.1f}",
        f"P99 {gm(C1, o99):,.1f} (x{rt(C1, o99):.2f}) · P50 {gm(C1, o50):,.1f} (x{rt(C1, o50):.2f})", f"P99 {gm(C2, o99):,.1f} (x{rt(C2, o99):.2f}) · P50 {gm(C2, o50):,.1f} (x{rt(C2, o50):.2f})")
    row(["QA2 별점", "6개 지표 개선 배수 geomean"], "x1.00",
        f"{st[C1]['QA2']}  x{G[C1]['qa2']['latency_improvement_geomean']:.2f} (TTFT x{imp(C1, 'ttft'):.2f} · TPOT x{imp(C1, 'tpot'):.2f})", f"{st[C2]['QA2']}  x{G[C2]['qa2']['latency_improvement_geomean']:.2f} (TTFT x{imp(C2, 'ttft'):.2f} · TPOT x{imp(C2, 'tpot'):.2f})")
    row(["QA3 Resource usage", "HBM 사용량 (GiB) ↓"], f"{gm(B, hb):,.1f}", f"{st[C1]['QA3']}  {gm(C1, hb):,.1f} (x{rt(C1, hb):.2f})", f"{st[C2]['QA3']}  {gm(C2, hb):,.1f} (x{rt(C2, hb):.2f})")
    row(["QA4 Modifiability", "module · 공수(MM) · 에이전트 비용 ↓"], "—",
        f"{st[C1]['QA4']}  {m['C1']['modules']:.2f} · {m['C1']['man_months']:.2f} · ${m['C1']['usd_T1']:.2f}", f"{st[C2]['QA4']}  {m['C2']['modules']:.2f} · {m['C2']['man_months']:.2f} · ${m['C2']['usd_T1']:.2f}")
    row(["별 합계", ""], "—", f"{o['totals'][C1]}", f"{o['totals'][C2]}", h=0.36, size=11)
    y += h_prev[0] + 0.06
    ft = g.fit_counts()
    prof = g.json.load(open(g.SIM / "configs" / "systems.json"))["profiles"]
    sysline = " + ".join(f"{sid[4:]}x8 ({prof[sid]['generation']['gpu_hbm'].split(' ')[0]}, {prof[sid]['generation']['host_link']}, {prof[sid]['generation']['dram']})" for sid in g.SYSIDS)
    s.box(0.4, y, 12.5, 0.95, [
        f"시스템: {sysline}. 8-GPU 1노드, Llama-3.1-70B BF16. 메모리(상세는 다음 장): " + g.memory_line().split("; ", 1)[1].replace("연산 ", "연산 ") + "." if False else f"시스템: {sysline}. 8-GPU 1노드, Llama-3.1-70B BF16. 6종 메모리 구성은 다음 장.",
        f"시나리오: 32개 x 2시스템 = 64쌍 중 비교 가능 {ft['comparison_valid']}쌍 기준(포화 {ft['saturated']}, Baseline도 SLO 불가 {ft['infeasible']}쌍 제외). 값은 쌍별 값의 기하평균, 괄호는 후보 ÷ Baseline(↑ 높을수록 좋음, ↓ 낮을수록 좋음). Evidence [B+C]."], "note", 9)
    y += 1.03
    why = (f"합계 {o['totals'][C1]} 대 {o['totals'][C2]}로 같아 우선순위({' > '.join(g.PRIO['priority'])})로 결정: {o['deciding']}에서 앞선 {nm[o['winner']]}" if o["rule"] == "priority"
           else f"별 합계가 높은 {nm[o['winner']]} 후보 ({o['totals'][C1]} 대 {o['totals'][C2]})")
    s.box(0.4, y, 12.5, 0.8, [
        f"선택: {nm[o['winner']]}  —  {why}. 합계 차이 1점이라 별 경계에 민감하다.",
        "한계: [B] simulation, 별 경계(QA1 1.30)와 QA3 정의(선택을 C2에서 C1로 바꿈), QA4 평균 집계는 결과를 본 뒤 정함. QA4 공수·비용은 ASSUMED."], "sel", 9)

    # ---------------- slide 2: why QA1, TTFT, TPOT ----------------
    def why_slide(title, items):
        sl = Slide(title)
        for name, x, w in (("QA / 수치", 0.4, 2.9), ("왜 이런 값이 나왔나", 3.3, 6.5), ("근거 (시나리오·측정값)", 9.8, 3.1)):
            sl.box(x, 1.15, w, 0.32, name, "head", 10, True, "ctr", False)
        yy = 1.5
        for h, a, b, c in items:
            sl.box(0.4, yy, 2.9, h, a, "dp", 9.5, True, "l", False)
            sl.box(3.3, yy, 6.5, h, b, "cell", 9.5, False, "l", False)
            sl.box(9.8, yy, 3.1, h, c, "note", 8.5, False, "l", False)
            yy += h + 0.05
        return sl

    kA, kB, kC = "dyn_kv_hotset_recency_shift@B200", "cb_kv_8k_b32@B200", "dyn_rag_shard_hotset_shift@B200"
    s2 = why_slide("DP1 평가 결과 - QA별로 왜 이런 값이 나왔나 (1/2: 처리량, 지연)", [
        (1.75, [f"QA1 처리량", f"C1 x{rt(C1, gp):.2f} · C2 x{rt(C2, gp):.2f}"],
         [f"- 비교 가능·포화 {g.RM['combined']['n_feasible']}쌍 중 C1 {len(T[C1]['tie'])}쌍, C2 {len(T[C2]['tie'])}쌍은 Baseline과 같다. Baseline이 이미 SLO를 만족하면 올릴 여지가 없기 때문이다 (공통 시나리오 x1.00).",
          f"- 이득은 hot 대상이 시간에 따라 옮겨 가는 Dynamic 시나리오에 집중된다 (승 C1 {len(T[C1]['win'])}, C2 {len(T[C2]['win'])}쌍).",
          "- C2는 데이터마다 접근 빈도·재사용·유휴를 보고 이동해 같은 종류(KV) 안의 hot/cold를 구분한다. C1은 자원 압박에만 반응해 구분하지 못한다."],
         [f"{kA.split('@')[0]} (B200): C1 x{ex(kA, C1, 'max_goodput_tps') / ex(kA, B, 'max_goodput_tps'):.2f}, C2 x{ex(kA, C2, 'max_goodput_tps') / ex(kA, B, 'max_goodput_tps'):.2f}. 이동량 C1 {ex(kA, C1, 'migration_gib'):,.0f} GiB 대 C2 {ex(kA, C2, 'migration_gib'):,.0f} GiB.",
          f"공통 {kB.split('@')[0]}: 모두 x1.00"]),
        (1.65, ["QA2 TTFT", f"P50 C1 x{rt(C1, t50):.2f} · C2 x{rt(C2, t50):.2f}", f"P99 C1 x{rt(C1, t99):.2f} · C2 x{rt(C2, t99):.2f}"],
         ["- P50이 크게 줄어드는 가장 큰 이유로 보이는 것: hot 데이터가 느린 tier(DRAM/HBF)에서 HBM으로 올라가 첫 토큰 전 복원 대기가 줄어든다(요청 단위로 분해하지는 않았다).",
          f"- C1의 P99는 개선이 없다(x{rt(C1, t99):.2f}). 진단한 `cb_kv_8k_b32`에서는 C1이 DRAM 링크 포화 신호에 반응해 이득 없는 재배치를 하고 그 이동이 링크를 나눠 써 꼬리가 늘었다(다른 시나리오의 원인은 분해하지 않음). C2는 hot 데이터를 HBM으로 올리는 이동이라 꼬리도 줄었다(x{rt(C2, t99):.2f}).",
          "- 이동이 같은 링크의 서빙 대역폭을 나눠 쓰는 간섭 모델을 반영했다."],
         [f"{kB.split('@')[0]} (B200) TTFT P99: Baseline {ex(kB, B, 't' + 'tft_p99_ms'):,.0f} ms, C1 {ex(kB, C1, 'ttft_p99_ms'):,.0f}, C2 {ex(kB, C2, 'ttft_p99_ms'):,.0f}.",
          f"C1은 재배치 {ex(kB, C1, 'rebalance'):.0f}회({ex(kB, C1, 'migration_gib'):,.0f} GiB), C2는 승격 {ex(kB, C2, 'promotion'):.0f}회"]),
        (1.35, ["QA2 TPOT", f"P99 C1 x{rt(C1, o99):.2f} · C2 x{rt(C2, o99):.2f}"],
         [f"- 거의 변하지 않는다. TPOT는 매 토큰 디코드가 HBM 대역폭에 묶여 정해지고, DP1은 데이터 위치만 바꾸지 디코드 방식은 바꾸지 못한다. Baseline의 TPOT P99가 {gm(B, o99):.1f} ms로 SLO(50 ms)보다 훨씬 낮아 개선 여지도 작다.",
          "- 개선이 있다면 KV가 HBM 밖에 있어 복원 비용이 TPOT에 섞이는 경우뿐이다. LoRA·MoE expert가 원격에 있을 때도 영향이 있으나 이번 비교 가능 시나리오에는 거의 없다(Baseline도 SLO 불가)."],
         ["Baseline TPOT P99 geomean " + f"{gm(B, o99):.1f} ms, SLO 50 ms", "LoRA·MoE 시나리오는 Baseline이 TPOT SLO를 못 맞춰 비교에서 제외"]),
    ])

    # ---------------- slide 3: why QA3, QA4 ----------------
    s3 = why_slide("DP1 평가 결과 - QA별로 왜 이런 값이 나왔나 (2/2: 자원, 확장성)", [
        (1.9, ["QA3 자원 사용 (HBM)", f"C1 x{rt(C1, hb):.2f} · C2 x{rt(C2, hb):.2f}", f"(HBM을 줄인/늘린 시나리오 C1 {E1['hbm']['n_reduced']}/{E1['hbm']['n_increased']}, C2 {E2['hbm']['n_reduced']}/{E2['hbm']['n_increased']})"],
         ["- 이동은 데이터 총량을 바꾸지 않고 어느 메모리에 두느냐만 바꾼다. 그래서 전 메모리 합 점유는 후보와 무관하고, 'HBM에 얼마나 두는가'가 차이를 만든다.",
          f"- C2는 성능을 위해 hot 데이터를 HBM으로 올려 HBM 사용이 늘어난다(비교 가능 {len(pairs)}쌍 중 {E2['hbm']['n_increased']}쌍에서 증가). C1은 HBM 압박이 있으면 데이터를 내리고(HBM 감소), DRAM 링크가 포화로 보일 때는 DRAM에서 더 싼 HBF로 옮겨 HBM 사용을 늘리지 않는다.",
          "- 성능과 자원은 반대 방향이다: C2는 성능을 얻는 대신 HBM을 더 쓰고, C1은 덜 쓰되 성능 이득이 작다.",
          f"- 보조 지표: 비용 가중 점유(DRAM 대비 상대 가격, ASSUMED) C1 x{E1['cost_ratio']:.2f}, C2 x{E2['cost_ratio']:.2f}로 같은 방향."],
         [f"{kB.split('@')[0]} (B200) HBM 사용: Baseline {ex(kB, B, 'tier_occ_gib')['hbm']:.0f} GiB, C1 {ex(kB, C1, 'tier_occ_gib')['hbm']:.0f}, C2 {ex(kB, C2, 'tier_occ_gib')['hbm']:.0f}",
          "정의 이력: 활용률 -> 풀 -> 성능÷비용 -> HBM 사용량. 마지막 변경으로 선택이 C2에서 C1로 바뀜"]),
        (1.75, ["QA4 확장성", f"C1 module {m['C1']['modules']:.2f} · C2 {m['C2']['modules']:.2f}", f"공수 {m['C1']['man_months']:.2f} vs {m['C2']['man_months']:.2f} MM", f"에이전트 비용 ${m['C1']['usd_T1']:.2f} vs ${m['C2']['usd_T1']:.2f}"],
         ["- 변경 시나리오 4종(새 메모리, 새 데이터 종류, 정책 교체, 새 event)을 시뮬레이터 복사본에 실제로 구현해 module 수를 쟀다.",
          "- C1은 데이터 종류를 모르는 구조라 새 데이터 종류를 추가해도 고칠 곳이 거의 없다. C2는 종류별 특성과 선호 목록을 알고 있어 새 데이터 종류는 module 3개, 새 메모리는 선호 목록에 올려야 쓰이므로 2개를 고친다.",
          "- 정책 교체와 새 event 추가는 두 후보가 같다(공유 module). 공수·비용은 가정 상수로 계산한 추정이다."],
         [f"새 메모리: C1 {sc4['S1']['C1']['modules']} / C2 {sc4['S1']['C2']['modules']}", f"새 데이터 종류: C1 {sc4['S2']['C1']['modules']} / C2 {sc4['S2']['C2']['modules']}", f"정책 교체: {sc4['S3']['C1']['modules']} / {sc4['S3']['C2']['modules']}", f"새 event: {sc4['S4']['C1']['modules']} / {sc4['S4']['C2']['modules']}"]),
        (1.1, ["결론: trade-off", f"성능 C2, 자원·확장성 C1"],
         [f"- C2는 처리량(x{rt(C2, gp):.2f})과 지연에서 앞서는 대신 HBM을 더 쓰고(x{rt(C2, hb):.2f}) 구조 변경 비용이 크다. C1은 반대다.",
          f"- 별 합계는 C1 {o['totals'][C1]}, C2 {o['totals'][C2]}로 근소해 선택({nm[o['winner']]})은 별 경계와 QA 정의에 민감하다."],
         ["TTFT P99: C1 개선 없음, C2 x" + f"{rt(C2, t99):.2f}", "TPOT: 두 후보 모두 거의 불변"]),
    ])

    # ---------------- ablation slide: Data-Memory Affinity ----------------
    _, ad = g.ablation_table()
    A = ad["A"]; bs = A["main"][B]; q4 = {C1: g.QA4_STARS[C1], C2: g.QA4_STARS[C2]}
    sa = Slide("C1의 Data-Memory Affinity 효과 - 제거 변형 비교 (H100 + B200 통합)")
    acols = [("지표", 0.4, 2.8), ("Baseline", 3.2, 1.5), ("C1 affinity 제거", 4.7, 2.7), ("C1 (affinity 포함, 평가 대상)", 7.4, 2.7), ("C2", 10.1, 2.8)]
    for name, x, w in acols:
        sa.box(x, 1.15, w, 0.32, name, "head", 10, True, "ctr", False)
    f0, f1 = (lambda v: f"{v:,.0f}"), (lambda v: f"{v:,.1f}")
    def cc(m, c, key, fmt=None):
        mm = m[c]
        if key == "gp":
            return f"{mm['star']['QA1']}  {f0(mm['gp'])} (x{mm['gp'] / bs['gp']:.2f})"
        if key == "t99":
            return f"{f0(mm['t99'])} (x{mm['t99'] / bs['t99']:.2f})"
        if key == "o99":
            return f"{f1(mm['o99'])} (x{mm['o99'] / bs['o99']:.2f})"
        if key == "qa2":
            return f"{mm['star']['QA2']}  x{mm['imp']:.2f}"
        if key == "hbm":
            return f"{mm['star']['QA3']}  {f1(mm['hbm'])} (x{mm['hbm'] / bs['hbm']:.2f})"
        return f"{mm['wtl'][0]}승 {mm['wtl'][1]}무 {mm['wtl'][2]}패"
    arows = [("QA1 goodput (tok/s) ↑", "gp", f0(bs["gp"])), ("QA2 TTFT P99 (ms) ↓", "t99", f0(bs["t99"])), ("QA2 TPOT P99 (ms) ↓", "o99", f1(bs["o99"])),
             ("QA2 별점 (개선 배수)", "qa2", "x1.00"), ("QA3 HBM 사용량 (GiB) ↓", "hbm", f1(bs["hbm"])), ("Baseline 대비 승/무/패", "wtl", "—")]
    yy = 1.5
    for label, key, base in arows:
        sa.box(0.4, yy, 2.8, 0.4, label, "dp", 9.5, True, "l", False)
        sa.box(3.2, yy, 1.5, 0.4, base, "cell", 9.5, False, "ctr", False)
        sa.box(4.7, yy, 2.7, 0.4, cc(A["none"], C1, key), "cell", 9.5, False, "ctr", False)
        sa.box(7.4, yy, 2.7, 0.4, cc(A["main"], C1, key), "cell", 9.5, False, "ctr", False)
        sa.box(10.1, yy, 2.8, 0.4, cc(A["main"], C2, key), "cell", 9.5, False, "ctr", False)
        yy += 0.42
    dec = lambda r: ("C1" if r["winner"] == "C1" else "C2") + (" (합계)" if r["rule"] == "total" else f" (동점, 우선순위 {r['deciding_qa']})")
    sa.box(0.4, yy, 2.8, 0.4, "별 합계 → 선택", "dp", 9.5, True, "l", False)
    sa.box(3.2, yy, 1.5, 0.4, "—", "cell", 9.5, False, "ctr", False)
    sa.box(4.7, yy, 2.7, 0.4, f"{ad['t_none']} → {dec(ad['sel_none'])}", "sel", 9.5, True, "ctr", False)
    sa.box(7.4, yy, 2.7, 0.4, f"{ad['t_main']} → {dec(ad['sel_main'])}", "sel", 9.5, True, "ctr", False)
    sa.box(10.1, yy, 2.8, 0.4, f"{ad['t_c2']}", "cell", 9.5, True, "ctr", False)
    yy += 0.52
    n, mm_, c2_ = A["none"][C1], A["main"][C1], A["main"][C2]
    ns, np_ = A["no_score"][C1], A["no_promo"][C1]
    sa.box(0.4, yy, 6.2, 2.45, [
        "보완 설계 스토리: affinity 추가",
        f"- affinity가 없는 C1은 자원 압박에만 반응한다. 처리량 x{n['gp'] / bs['gp']:.2f}, TTFT P99 x{n['t99'] / bs['t99']:.2f}(악화)로 C2(x{c2_['gp'] / bs['gp']:.2f})에 크게 못 미치고, 별 합계가 동점이라 우선순위로 C2가 선택된다.",
        f"- 정적 Data-Memory Affinity를 추가하면(힌트와 접근 비용 추정으로 'HBM에 있어야 SLO를 만족하는' 객체를 승격, 필요하면 교환) 처리량 x{mm_['gp'] / bs['gp']:.2f}, QA2 ★★★이 되어 합계 {ad['t_main']} 대 {ad['t_c2']}로 C1이 선택된다.",
        f"- 효과의 출처는 정적 승격 pass다: 점수만 제거 x{ns['gp'] / bs['gp']:.3f}(변화 없음), 승격 제거 x{np_['gp'] / bs['gp']:.3f}.",
        "- 승격은 두 후보가 공유하는 접근 비용 추정기(operation class·shape 힌트)에 의존한다."], "sel", 9.5)
    sa.box(6.8, yy, 6.1, 2.45, [
        "한계 (솔직하게)",
        f"- affinity를 넣어도 C1 처리량(x{mm_['gp'] / bs['gp']:.2f})은 C2(x{c2_['gp'] / bs['gp']:.2f})보다 낮다. 격차를 약 {(mm_['gp'] - n['gp']) / (c2_['gp'] - n['gp']) * 100:.0f}% 줄였지만 C2를 이기지는 못한다.",
        f"- 선택이 C1로 바뀐 것은 QA3(HBM x{mm_['hbm'] / bs['hbm']:.2f} 대 C2 x{c2_['hbm'] / bs['hbm']:.2f})·QA4 우위와 QA2 별 경계(x{mm_['imp']:.2f} vs 1.25)에서 온다. 합계 차이 1점이라 경계에 민감하다.",
        "- affinity 제거 변형에서도 QA4 별은 C1 ★★★로 같게 두었다(affinity 모듈은 C1 설계에 원래 포함).",
        "- 대조군(affinity 포함 재실행)은 본 결과와 정확히 일치. 5 seed, 동일 시나리오. 4.7절 참고."], "note", 9.5)

    # ---------------- slide: star-edge basis ----------------
    sbj = g.json.load(open(g.DATA / "star_basis.json"))["summary"]
    sbs = Slide("별점 경계의 근거 - 하한은 측정, 상한은 환산 + 정책 선택")
    for name, x, w in (("QA", 0.4, 1.3), ("하한 (★/★★) 근거: Baseline끼리 비교한 잡음 대역", 1.7, 4.6), ("현재 하한", 6.3, 1.1), ("상한 (★★/★★★) 환산", 7.4, 5.5)):
        sbs.box(x, 1.15, w, 0.32, name, "head", 10, True, "ctr", False)
    rows_ = [("QA1 처리량", "qa1_ratio", "0.97", "x1.30 = 23% 하드웨어 절감 = 8-GPU 노드에서 약 1.85 GPU (x1.14가 1 GPU)"),
             ("QA2 latency", "qa2_improvement", "0.95", "x1.25 = latency 20% 감소 (TTFT P99 1,084 -> 867 ms, TPOT P99 17.1 -> 13.7 ms)"),
             ("QA3 HBM 절감", "qa3_saving", "0.95", "x1.25 = HBM 20% 감소 (146.6 GiB 중 약 29 GiB, 8K KV object 약 1.6개)")]
    yy = 1.5
    for lab, k, edge, conv in rows_:
        v = sbj[k]
        sbs.box(0.4, yy, 1.3, 0.62, lab, "dp", 9.5, True, "l", False)
        sbs.box(1.7, yy, 4.6, 0.62, f"잡음 범위 {v['min']:.3f} ~ {v['max']:.3f} (sd {v['sd']:.3f}, 20개 비교)", "cell", 9.5, False, "l", False)
        sbs.box(6.3, yy, 1.1, 0.62, edge, "cell", 9.5, True, "ctr", False)
        sbs.box(7.4, yy, 5.5, 0.62, conv, "cell", 9, False, "l", False)
        yy += 0.66
    sbs.box(0.4, yy + 0.1, 6.2, 2.7, [
        "무엇이 근거 있고 무엇이 선택인가",
        "- 하한: QA1 0.97은 Baseline끼리 비교해도 나오는 잡음의 아래 끝과 같다(측정). QA2/QA3의 0.95는 잡음(0.97/0.98)보다 느슨하지만 조여도 현재 별은 바뀌지 않는다.",
        "- 상한: 잡음(약 3%)으로는 정해지지 않는다. '도입 가치가 있는 크기'라는 정책 선택이며 위 환산으로 의미만 붙였다.",
        "- QA1 상한 1.30은 결과를 본 뒤 정한 값(defined_after_first_look)이고 1.25와 환산 차이가 작다(1.6 GPU 대 1.85 GPU)."], "sel", 9.5)
    sbs.box(6.8, yy + 0.1, 6.1, 2.7, [
        "선택이 상한에 얼마나 민감한가 (상한을 QA1/2/3에 같게 적용)",
        "- 상한 1.10~1.25: C1 11점 대 C2 9점 -> C1 선택",
        "- 상한 1.30~1.40: 둘 다 9점 동점, QA1 우선순위로 C2 선택",
        "- 상한 1.45 이상: C1 9점 대 C2 8점 이하 -> C1 선택",
        "- 현재 공식 경계는 C1의 QA1(x1.298)과 0.2% 차이라 선택은 경계에 민감하다. 상한을 하드웨어 환산(예: 1 GPU = x1.14, 2 GPU = x1.33)으로 고정할지는 소유자 결정 사항이다. 근거 문서: qa-criteria-dp1.md §J."], "note", 9.5)

    # ---------------- slide: TTFT P99 tail regression ----------------
    bsj = g.json.load(open(g.DATA / "burst" / "summary.json"))
    st_ = Slide("TTFT P99 꼬리 악화 (Baseline-regression loop 4) - 이득과 같은 메커니즘")
    for name, x, w in (("burst 용량 (s)", 0.4, 1.9), ("C1: QA1 (x) / TTFT P99 악화 쌍 / 최악 쌍", 2.3, 5.0), ("C2: QA1 (x) / TTFT P99 악화 쌍 / 최악 쌍", 7.3, 5.6)):
        st_.box(x, 1.15, w, 0.32, name, "head", 10, True, "ctr", False)
    yy = 1.5
    for cap in ("2.0", "1.0", "0.5", "0.25"):
        a, b_ = bsj[cap][C1], bsj[cap][C2]
        st_.box(0.4, yy, 1.9, 0.4, cap + (" (현재)" if cap == "2.0" else ""), "dp", 9.5, True, "ctr", False)
        st_.box(2.3, yy, 5.0, 0.4, f"x{a['qa1']:.2f} / {a['n_worse']}쌍 / x{a['worst']:.2f}", "cell", 9.5, False, "ctr", False)
        st_.box(7.3, yy, 5.6, 0.4, f"x{b_['qa1']:.2f} / {b_['n_worse']}쌍 / x{b_['worst']:.2f}", "cell", 9.5, False, "ctr", False)
        yy += 0.42
    st_.box(0.4, yy + 0.1, 6.2, 3.0, [
        "무슨 일이 일어나나 (21쌍, H100+B200)",
        "- 현재 설정에서 TTFT P99가 Baseline보다 나쁜 쌍: C1 6개, C2 5개. C1 최악은 Common cb_kv_8k_b32(H100 x4.15, B200 x3.88).",
        "- 같은 쌍에서 TTFT P50은 개선(x0.32~0.67)된다: 중앙값은 좋아지고 꼬리가 나빠진다.",
        "- 꼬리는 이동된 객체가 아니라 DRAM에 남은 KV의 첫 응답이다. C1이 초반 20% 구간에 15 GiB급 이동 19건을 몰아 보내 DRAM 링크 서빙 대역폭이 0.10배까지 떨어지고, 그 구간 접근 2.5%가 P99를 정한다."], "sel", 9.5)
    st_.box(6.8, yy + 0.1, 6.1, 3.0, [
        "결론과 한계",
        "- burst 용량을 줄이면 꼬리가 줄지만 이득도 같이 사라진다(0.5 s: C1 QA1 x1.00, 0.25 s: C1이 Baseline과 동일). 용량 상수 하나로 둘을 동시에 얻지 못한다.",
        "- 기본값은 유지했다. 필요한 것은 큰 이동을 여러 tick에 나누는 staged 이동과 이동 중 접근에 대한 do-no-harm 검사이며 보완 설계 택틱([C], 미구현)이다.",
        "- 한계: 링크 간섭이 평균장 근사(대역폭 배율)라 꼬리가 과대일 수 있다. 사전 판정 규칙이 '이득이 0인 퇴화 해'를 허용하는 결함이 있었음을 loop-log에 기록했다."], "note", 9.5)

    # ---------------- slide: QA1 star basis = Oracle capture ratio ----------------
    cs = g.capture_stats()
    sq = Slide("QA1 별 기준의 문헌 근거 - Oracle 대비 이득 달성률")
    for name, x, w in (("후보", 0.4, 1.6), ("pooled 달성률", 2.0, 2.2), ("쌍별 평균", 4.2, 2.0), ("Oracle 초과 쌍", 6.2, 2.0), ("QA1 별 (x = 80%)", 8.2, 2.2), ("현재 공식 별", 10.4, 2.5)):
        sq.box(x, 1.15, w, 0.32, name, "head", 10, True, "ctr", False)
    for i, (nm, k, a, b) in enumerate((("C1", "c1", "★★", "★★ (x1.298)"), ("C2", "c2", "★★★", "★★★ (x1.422)"))):
        yy = 1.5 + i * 0.42
        for (x, w, v) in ((0.4, 1.6, nm), (2.0, 2.2, f"{cs[k]['pooled']:.2f}"), (4.2, 2.0, f"{cs[k]['mean']:.2f}"), (6.2, 2.0, str(cs[k]["over"])), (8.2, 2.2, a), (10.4, 2.5, b)):
            sq.box(x, yy, w, 0.4, v, "cell", 9.5, i >= 0 and x in (0.4, 8.2), "ctr", False)
    sq.box(0.4, 2.5, 6.2, 4.2, [
        "정의와 x의 근거",
        f"- 달성률 = (후보 - Baseline) / (Oracle - Baseline), 시나리오 쌍마다. Oracle = 미래 접근률 완전 정보 + 무비용 즉시 이동을 준 정책(Oracle-ideal, 증명된 최적은 아님). 개선 여지 3.3% 이하인 쌍은 제외(비교 가능 {cs['n_pairs']}쌍 중 {cs['n_head']}쌍 사용).",
        "- x = 80%: 문헌의 이득 달성률 {57, 75, 87, 95}%의 중앙값 81%를 반올림. Mockingjay(HPCA'22) Table I: SHiP 57%, Hawkeye 75%, Mockingjay 95%(Belady MIN 대비 IPC 개선), ARMS(arXiv 2508.04417): 튜닝 최적의 97% 이상 -> 87% 이상(환산).",
        "- ★/★★ 경계는 기존 잡음 기준(Baseline 대비 0.97) 유지."], "sel", 9.5)
    sq.box(6.8, 2.5, 6.1, 4.2, [
        "솔직한 한계",
        "- 문헌은 CPU 캐시 교체와 tiered memory 연구다. LLM 서빙에 직접 해당하는 이득 달성률 문헌은 찾지 못했다. LLM KV 연구(arXiv 2609.16215)는 대역폭이 경합하면 oracle prefetch도 이득이 없었다고 보고했고, 이는 우리 링크 간섭 결과와 같은 방향이다.",
        "- 쌍 10개뿐이라 부트스트랩 95% 구간이 C1 0.33~0.87, C2 0.70~0.93으로 겹친다. C2가 더 가깝다고 단정할 수 없다.",
        f"- 쌍별 평균을 쓰면 C2는 {cs['c2']['mean']:.2f}로 ★★이다(pooled는 문헌의 관례). 두 방식 모두 선택은 C1.",
        "- QA2(Oracle을 넘는 쌍 6개)와 QA3(Oracle 미정의)에는 적용하지 않았다. 출처 5개와 제외 사유: qa-capture-literature.md."], "note", 9.5)

    # ---------------- slide 4: scenarios ----------------
    s4 = Slide("DP1 평가에서 고려한 시나리오")
    per_set = []
    for lab, name in g.SETS:
        fit = g.json.load(open(g.DATA / g.MERGED / "qa_result.json"))[lab]["fit"]
        cnt = {k: sum(1 for v in fit.values() if v == k) for k in ("comparison_valid", "saturated", "infeasible")}
        per_set.append(f"{name} {len(fit) // 2}개 (쌍: 비교 {cnt['comparison_valid']}, 포화 {cnt['saturated']}, 불가 {cnt['infeasible']})")
    s4.box(0.4, 1.2, 12.5, 0.6, [f"32개 시나리오를 H100과 B200에 각각 돌렸다(64쌍). " + " · ".join(per_set) + ". 비교 불가 쌍은 결과에서 빼지 않고 별도 표시했다."], "note", 10)
    blocks = [
        ("기본 서비스 상황 (공통)", "8K 토큰 입력, 256 토큰 생성, 동시 32 요청의 대화 서비스. HBM이 빠듯한 경우 / 시간이 갈수록 여유가 줄어드는 경우 / KV cache에 LoRA·MoE·Agent 데이터가 섞이는 경우. 결과: 두 후보 모두 처리량은 Baseline과 같다."),
        ("데이터 종류별", "대화 문맥(KV cache, 32K~512K 토큰, 동시 1~256) · 여러 고객이 쓰는 LoRA 어댑터(몇 개만 인기) · MoE expert(라우팅 쏠림) · 수 TiB 벡터 DB(RAG) · 오래 보관되는 Agent 기억과 Tool 결과(드물게 재사용 / 한꺼번에 생성 후 반복 참조)."),
        ("접근이 쏠리는 정도(hotness)", "소수만 인기 있는 skew · 거의 안 쓰이는 cold 데이터가 상위 메모리를 차지 · 갑자기 hot해지는 burst · hot/cold 급반전 · hot 대상이 옮겨 감(최근 세션으로 이동, 사용자 그룹이 번갈아 활성, 인기 검색 shard가 바뀜). 고르게 접근되는 전용 시나리오는 아직 없음(중간 KV 기준선이 대조군)."),
        ("자원 조건이 바뀌는 경우", "HBM 용량 압박(고정 / 점진 증가) · HBM 대역폭 급락 · 다른 작업과 공유하는 host 링크 경합(대역폭 25%로 저하) · 6개 메모리 용량을 모두 써야 하는 큰 용량 부담."),
        ("처음엔 문제없다가 나빠지는 경우 (Dynamic 6개)", "Baseline이 처음엔 SLO를 만족하다 중간에 working set이 바뀐다. 예: 오래 보관만 되던 Agent 기억이 HBM을 차지한 채 채팅이 몰림 / hot 대화가 초기 세션에서 최근 세션으로 이동. Baseline의 실패 양상을 알고 설계했으므로 이득은 이 상황에 한정."),
    ]
    yy = 1.9
    for t, body in blocks:
        s4.box(0.4, yy, 2.9, 0.92, t, "dp", 10, True, "l", False)
        s4.box(3.3, yy, 9.6, 0.92, body, "cell", 10.5, False, "l", False)
        yy += 0.97
    return [s, system_slide(), s2, s3, sa, st_, sbs, sq, s4]


def tactics_slide():
    """Complement design for the SELECTED structure (C1): what the evaluation shows is weak and the tactic that addresses it."""
    o = g.overall_selection()
    nm = {g.C1: "C1", g.C2: "C2"}
    sel = nm.get(o["winner"], "C1")
    A = {t: g.ablation_metrics(t) for t in ("none", "main")}
    C1, C2, B = g.C1, g.C2, g.B
    bs = A["main"][B]
    n, m, c2 = A["none"][C1], A["main"][C1], A["main"][C2]
    r = lambda x: x["gp"] / bs["gp"]
    Q = g.RM["combined"]["qa_feasible"]
    s = Slide(f"DP1 보완 설계 택틱 - 선택 구조 {sel} 기준")
    cols = [("#", 0.4, 0.45), ("약점 (평가 근거)", 0.85, 3.6), ("보완 택틱", 4.45, 4.9), ("개선 QA", 9.35, 0.9), ("검증 상태", 10.25, 2.65)]
    for name, x, w in cols:
        s.box(x, 1.2, w, 0.34, name, "head", 9, True, "ctr", False)
    rows = [
        ("T1", f"자원 압박에만 반응하는 C1은 처리량 x{r(n):.2f}, TTFT P99 x{n['t99'] / bs['t99']:.2f}(악화)로 C2(x{r(c2):.2f})에 크게 못 미침",
         "정적 Data-Memory Affinity 승격 추가: operation class·shape 힌트와 접근 비용 추정으로 'HBM에 있어야 SLO를 만족하는' 객체를 승격, 자리가 없으면 정적 페널티가 작은 HBM 거주 객체와 교환",
         "QA1 QA2", f"[B] 구현·측정됨: 처리량 x{r(n):.2f} -> x{r(m):.2f}, QA2 ★★ -> ★★★ (제거 변형 비교, 결과 4.7). 선택이 C2에서 C1로 바뀜"),
        ("T2", f"TTFT P99 꼬리 개선 없음(x{m['t99'] / bs['t99']:.2f}). 진단한 시나리오에서 이득 없는 재배치(DRAM 링크 포화 신호에 반응)가 링크를 나눠 씀",
         "재배치에도 이득/비용 gating 적용(C2에 있는 것과 같은 방식): 예상 서빙 이득이 이동 비용보다 작으면 이동하지 않음", "QA2", "[C] 미구현. 원인은 `cb_kv_8k_b32` 한 시나리오에서만 진단"),
        ("T3", f"같은 종류(KV) 안의 hot/cold를 구분하지 못해 C2보다 처리량이 낮음(x{r(m):.2f} 대 x{r(c2):.2f}), QA1 별 경계(1.30) 바로 아래",
         "affinity 힌트에 경량 접근 신호(최근 접근 시각, 접근 횟수)를 추가해 구조를 type-agnostic으로 유지하면서 hot/cold 승격 반영", "QA1", "[C] 미구현. C2의 behavior 모듈 전체를 들이지 않는 대안"),
        ("T4", "정적 힌트(operation class·shape)가 틀리거나 신규 메모리에 없으면 승격이 오작동. 승격이 공유 접근 비용 추정기에 의존",
         "힌트를 Memory Backend I/F의 descriptor에서 자동 도출하고, 힌트가 없으면 승격을 끄는 안전 장치(do-no-harm)", "QA4 안정성", "[C] 미구현"),
    ]
    y = 1.6
    for r_ in rows:
        h = 1.12
        for (name, x, w), v in zip(cols, r_):
            s.box(x, y, w, h, v, "dp" if name == "#" else ("c2" if name == "보완 택틱" else "cell"), 9.5, name == "#", "ctr" if name in ("#", "개선 QA") else "l", False)
        y += h + 0.06
    s.box(0.4, y + 0.05, 12.5, 0.6, [
        "T1은 이미 C1 설계(Data-Memory Affinity)에 포함된 구성요소를 평가에서 켠 것이다. 제거 변형으로 효과를 측정했다. T2~T4는 평가가 드러낸 약점에 대한 제안이며 simulator 적용 전까지 효과를 수치로 주장하지 않는다."], "note", 9.5)
    return s


def build(slides, out, base_pptx):
    from pptx import Presentation
    from pptx.dml.color import RGBColor
    from pptx.enum.shapes import MSO_SHAPE
    from pptx.enum.text import MSO_ANCHOR, PP_ALIGN
    from pptx.util import Inches, Pt
    from lxml import etree

    A = "http://schemas.openxmlformats.org/drawingml/2006/main"
    FONT = "맑은 고딕"
    rgb = RGBColor.from_string
    prs = Presentation(str(base_pptx))
    base = prs.slides[8]
    keep = {3, 5, 8, 39, 57}
    originals = list(prs.slides._sldIdLst)
    for sl in slides:
        s = prs.slides.add_slide(base.slide_layout)
        for sh in list(s.shapes):
            sh._element.getparent().remove(sh._element)
        for sh in base.shapes:
            if sh.shape_id in keep:
                s.shapes._spTree.append(copy.deepcopy(sh._element))
        for sh in s.shapes:
            if sh.shape_id == 3:
                r = sh.text_frame.paragraphs[0].runs
                r[0].text = "DP1. 이기종 메모리 기반 Data Migration 구조 - Appendix"
                for x in r[1:]:
                    x.text = ""
            if sh.shape_id == 8:
                r = sh.text_frame.paragraphs[0].runs
                r[0].text = sl.title
                for x in r[1:]:
                    x.text = ""
                sh.width = Inches(12.5)
        for e in sl.E:
            f, l, t = STY[e["sty"]]
            b = s.shapes.add_shape(MSO_SHAPE.RECTANGLE, Inches(e["x"]), Inches(e["y"]), Inches(e["w"]), Inches(e["h"]))
            b.shadow.inherit = False
            b.fill.solid(); b.fill.fore_color.rgb = rgb(f)
            b.line.color.rgb = rgb(l); b.line.width = Pt(0.75)
            tf = b.text_frame; tf.word_wrap = True
            tf.margin_left = tf.margin_right = Inches(0.05); tf.margin_top = tf.margin_bottom = Inches(0.03)
            tf.vertical_anchor = MSO_ANCHOR.TOP if e["top"] else MSO_ANCHOR.MIDDLE
            for i, ln in enumerate(e["lines"]):
                p = tf.paragraphs[0] if i == 0 else tf.add_paragraph()
                p.alignment = PP_ALIGN.CENTER if e["align"] == "ctr" else PP_ALIGN.LEFT
                r = p.add_run(); r.text = ln
                r.font.size = Pt(e["size"]); r.font.name = FONT
                r.font.bold = bool(e["bold"]) or (i == 0 and e["sty"] in ("note", "sel") and not ln.startswith("-") and not ln.startswith("평가"))
                r.font.color.rgb = rgb(t)
                ea = etree.SubElement(r._r.get_or_add_rPr(), "{%s}ea" % A); ea.set("typeface", FONT)
    lst = prs.slides._sldIdLst
    for el in originals:
        prs.part.drop_rel(el.rId)
        lst.remove(el)
    prs.save(str(out))


def preview(sl, out):
    from PIL import Image, ImageDraw
    S = 110
    hx = lambda h: tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))
    im = Image.new("RGB", (int(13.333 * S), int(7.5 * S)), "white")
    d = ImageDraw.Draw(im)
    d.text((20, 15), sl.title, font=_font(14), fill=(0, 0, 0))
    for e in sl.E:
        f, l, t = STY[e["sty"]]
        x, y, w, h = [int(v * S) for v in (e["x"], e["y"], e["w"], e["h"])]
        d.rectangle([x, y, x + w, y + h], fill=hx(f), outline=hx(l))
        lh = int(e["size"] * S / 72 * 1.3)
        ty = y + 4 if e["top"] else y + max(2, (h - lh * len(e["lines"])) // 2)
        for i, ln in enumerate(e["lines"]):
            font = _font(e["size"])
            tw = d.textlength(ln, font=font)
            d.text((x + (w - tw) / 2 if e["align"] == "ctr" else x + 5, ty + i * lh), ln, font=font, fill=hx(t))
            if ty + (i + 1) * lh > y + h + 2:
                print("OVERFLOW", sl.title[:20], ln[:30])
    im.save(out)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out-dir", type=Path, default=g.ROOT.parent / "DP1")
    ap.add_argument("--preview-dir", type=Path, default=None)
    a = ap.parse_args()
    base = g.ROOT.parent / "DP1" / "DP-memory-backend-if.pptx"
    a.out_dir.mkdir(parents=True, exist_ok=True)
    jobs = [("DP1-appendix-qa-result.pptx", qa_slides()), ("DP1-complement-design-tactics.pptx", [tactics_slide()])]
    for name, sls in jobs:
        build(sls, a.out_dir / name, base)
        print("wrote", a.out_dir / name, len(sls), "slide(s)")
        if a.preview_dir:
            a.preview_dir.mkdir(parents=True, exist_ok=True)
            for i, sl in enumerate(sls):
                preview(sl, a.preview_dir / f"{name[:-5]}-{i + 1}.png")


if __name__ == "__main__":
    main()
