"""첨부 덱(base/DP-QA-attached.pptx)을 베이스로 QA 평가 기준 덱 v4를 만든다 (판정 Baseline = B1 정적 offload).

기존 자료는 건드리지 않고 이 폴더에만 쓴다.  python3 build_deck.py  →  DP-QA-criteria-v4.pptx
"""
import copy
import math
import re

from pptx import Presentation
from pptx.util import Inches, Pt

import criteria_data as cd
import theory_model as tm
from deck_lib import *  # noqa: F401,F403  (헬퍼: tbox, rect, add_table, band_chart, criteria_page ...)
from deck_lib import _font, BAND_FILL, NAVY, BASE, OUT


def q4_spec():
    r = cd.BAND_TEXT["Q4"]
    return dict(
        title="시스템 확장성 - 평가 기준",
        subtitle="시스템 및 자원의 증가분 대비 처리량의 증가분 비율",
        src="출처: AthenaK (arXiv 2409.16053, 학습 workload) · USL 환산. 90% '효율적' 기준은 관례(정책)이며 인용 논문을 확인하지 못해 출처로 삼지 않았다",
        metric=["[Metric] SE(N) = Goodput 증가 배율 ÷ N 증가 배율  (N = 노드 수, 평가는 N=16 시뮬레이션)",
                "USL 환산: SE(N) = 1 ÷ (1 + σ(N−1)), σ = 조율 계층의 직렬 비중. N=16에서 SE 80%↔σ 1.67%, 85%↔1.18%, 90%↔0.74%, 92.5%↔0.54%, 95%↔0.35%",
                "Baseline 절대값(이론): B0·B1 모두 노드 독립이라 조율 비용이 없다 → SE 98%(부하 불균형 2% [가정]). 기준은 이상적 선형 확장 대비라 Baseline을 B1로 바꿔도 구간은 같다",
                "구간 규칙: ★1 = 요구 80%, ★2 = 90%(손실 10% 이내), ★3 = 95%(손실 5% 이내), 반 단계는 중점"],
        metric_h=1.05,
        table_y=2.3,
        rows=[
            (3, r[3], "처리량 손실 5% 이내(16노드에서 15.2노드분 효과). 조율 계층 직렬 비중 σ ≤ 0.35%(USL 환산, 정책 선택)", "USL 환산 / 정책"),
            (2.5, r[2.5], "★2와 ★3의 중점(손실 7.5%)", "—"),
            (2, r[2], "처리량 손실 10% 이내(16노드에서 14.4노드분 효과). 병렬 효율에서 '효율적'이라 부르는 관례 수준(정책 선택)", "정책 선택"),
            (1.5, r[1.5], "★1과 ★2의 중점(손실 15%)", "—"),
            (1, r[1], "Stakeholder 요구: SE > 80%. 문헌: 65,536 GPU에서 병렬 효율 80% 보고(AthenaK, 학습 workload라 서빙 SE와 의미가 다름)", "Stakeholder 요구사항, arXiv 2409.16053"),
            (0, r[0], "확장은 되지만 조율 계층이 병목. 시나리오 요구(80%) 미충족", "—"),
        ],
        chart=dict(
            title="구간 대비 근거 위치 (SE %, N=16)",
            axis=dict(min=50, max=100, log=False, ticks=[50, 60, 70, 80, 90, 100], unit="%"),
            bands=[(50, 80, 0), (80, 85, 1), (85, 90, 1.5), (90, 92.5, 2), (92.5, 95, 2.5), (95, 100, 3)],
            markers=[
                dict(kind="point", v=80, style="req", label="Stakeholder 요구: SE > 80%"),
                dict(kind="point", v=80, style="lit", label="AthenaK: 65,536 GPU에서 병렬 효율 80% (학습)"),
                dict(kind="point", v=90, style="calc", label="'효율적' 보고 관례 90% (정책, 손실 10% 이내)"),
                dict(kind="range", v=(80, 95), style="calc", label="USL 환산 σ: 80%↔1.67% · 90%↔0.74% · 95%↔0.35%"),
            ]),
    )


def q5_rows():
    return [
        (3, "≤ 2", "≤ 0.5", "일상 변경 규모: SWE-bench 평균 패치 1.7 file·32.8 line ≈ 0.32 MM(아래 공식 환산). 0.5 MM = 1인 2주 sprint", "SWE-bench (arXiv 2310.06770), 사전 등록 가정"),
        (2.5, "≤ 2.5", "≤ 0.625", "★2와 ★3의 중점", "—"),
        (2, "≤ 3", "≤ 0.75", "변경이 한 Plane/Layer 안에 머무는 규모(설계 component 12~14개의 약 1/4), 3주", "—"),
        (1.5, "≤ 4", "≤ 0.875", "★1과 ★2의 중점", "—"),
        (1, "≤ 5", "≤ 1.0",
         "최소 충족. module: 설계 component 12~14개 중 5개(36~42%) 초과 시 확장 지점이 없다고 본다. M/M: vLLM 최상위 KV connector 중앙값 356 LOC를 1개 신규 구현하는 비용 ≈ 1.0 MM(공식 환산) = 1인 1개월",
         "DP1 사전 등록 component 목록, vLLM 저장소 LOC 계수"),
        (0, "≥ 6 또는 major interface 변경", "> 1.0", "한 항목이라도 ★1 기준을 넘으면 미충족. 기존 필드 의미 변경(Backend I/F, Event schema)은 module 수와 무관하게 미충족", "—"),
    ]


def q5_page(slide):
    page_chrome(slide, "변경 용이성 - 평가 기준", "변경 module 수 AND M/M(개발 공수) — 시나리오 평균, 두 지표 중 낮은 별",
                "출처: SWE-bench (arXiv 2310.06770) · vLLM 저장소 kv_connector/v1 직접 계수(최상위 파일 192~1,190 LOC, 중앙값 356) · DP1 qa4-preregistration(공식·상수 ASSUMED)")
    for nm in ("tbl", "formula", "l"):
        for sh in [s for s in slide.shapes if s.name == nm]:
            remove(sh)
    # 변경 시나리오 박스
    tbox(slide, 0.4, 1.17, 12.5, 0.5,
         [[("[변경 시나리오 3종, KV 캐시 관리 범위] ", {"bold": True, "color": NAVY, "size": 10}),
           ("S1 새 메모리 tier 추가 · S2 이동·배치·재사용 정책 교체 · S3 vLLM upstream 갱신 대응(block pool, kv_offload, CUDA graph, async scheduling 접점 수정). "
            "시나리오 단순 평균으로 판정. module = 설계 문서의 component 단위(한 줄이라도 바꾸면 1개).", {"size": 9.5})]],
         size=9.5, line_spacing=1.1, name="metric")
    rows = [["별", "① 변경 module 수 (평균)", "② 개발 공수 (M/M, 평균)", "근거", "출처"]]
    stars = []
    for st, m, mm, ev, src in q5_rows():
        rows.append([[[(star_label(st), {"bold": True})]], m, mm, ev, src])
        stars.append(BAND_FILL[st])
    colw = [0.75, 1.6, 1.6, 6.05, 2.53]
    rowh = [0.26] + [0.34] * 6
    add_table(slide, 0.4, 1.7, colw, rows, rowh, fills=stars, size=8.3, aligns=["c", "c", "c", "l", "l"])
    # 공식 박스
    rect(slide, 0.4, 4.1, 12.53, 0.62, fill="F2F6FC", line="2F5597", line_w=1.0, shape=MSO_SHAPE.ROUNDED_RECTANGLE, name="formula")
    tbox(slide, 0.5, 4.12, 12.3, 0.6,
         [[("M/M = [ module 수 n × module당 고정 공수 3일 + 추가 LOC L ÷ 하루 생산성 40 LOC × 테스트·리뷰 overhead 2.0 ] ÷ 21일/MM", {"bold": True, "color": NAVY, "size": 9.5})],
          [("환산 예: SWE-bench 평균 패치 n=1.7, L=32.8 → 6.7일 = 0.32 MM · vLLM connector 중앙값 n=1, L=356 → 20.8일 = 0.99 MM. "
            "(LOC는 실제 vLLM 통합 기준. 시뮬레이터 proxy LOC는 ×5 배율로 환산한다.) 토큰 비용은 기준에서 제외했다.", {"size": 8.5, "color": "404040"})]],
         size=9, line_spacing=1.1, name="formula_text")
    # 두 지표의 관계
    tbox(slide, 0.4, 4.76, 12.5, 0.3,
         [[("두 지표의 관계: ", {"bold": True, "color": NAVY, "size": 9}),
           ("module 수 n이 M/M 안에 3일×n으로 들어 있어 독립이 아니다(n=2면 0.29 MM, n=5면 0.71 MM 선점). module 수가 M/M의 하한을 정하고, AND 판정은 'LOC까지 큰 변경'을 추가로 걸러 낸다.", {"size": 8.5})]],
         size=8.5, line_spacing=1.05)
    return 0



# ============================================================ SLO 페이지 (슬라이드 9)
def budget_bar(slide, x, y, w, label, segs, slo, unit, scale_max, note, stacked=True):
    """segs=[(값, 색, 라벨)]. stacked면 누적 막대 1줄, 아니면 항목별 막대. SLO 기준선은 붉은 세로선."""
    tbox(slide, x, y, w, 0.2, [[(label, {"bold": True, "color": NAVY})]], size=9, margins=(0.02, 0, 0, 0))
    tx, tw, th = x + 0.02, w - 0.04, 0.24
    n = 1 if stacked else len(segs)
    top = y + 0.28
    for i in range(n):
        rect(slide, tx, top + i * (th + 0.05), tw, th, fill="F2F2F2", line="BFBFBF", line_w=0.5)
    cur = 0.0
    for i, (val, col, lab) in enumerate(segs):
        row = 0 if stacked else i
        sx = tx + (cur if stacked else 0) / scale_max * tw
        sw = val / scale_max * tw
        ty = top + row * (th + 0.05)
        rect(slide, sx, ty, sw, th, fill=col, line="FFFFFF", line_w=0.75)
        tbox(slide, sx, ty, sw, th, lab, size=7.5, color="FFFFFF" if col in ("2F5597", "7F7F7F") else "000000",
             align="c", anchor="m", margins=(0, 0, 0, 0), wrap=False)
        if stacked:
            cur += val
    bottom = top + n * (th + 0.05)
    lx = tx + slo / scale_max * tw
    hline(slide, lx, top - 0.04, lx, bottom, color="C00000", w=1.75)
    tbox(slide, lx - 1.4, y, 1.38, 0.2, "SLO %g %s" % (slo, unit), size=8, color="C00000", align="r",
         margins=(0, 0, 0, 0), wrap=False)
    tbox(slide, tx, bottom + 0.02, tw, 0.34, note, size=7.5, color="404040", margins=(0, 0, 0, 0))


def slo_page(slide):
    page_chrome(slide, "SLO 기준", "TTFT·TPOT의 측정 정의, 절대 기준, 근거 계산과 적용 규칙 (모든 DP·후보·Baseline에 동일 적용)",
                "출처: 공통 SLO 기준 · MLPerf Inference(2차) · Brysbaert 2019. 계산: 가중치 141 GB, H100×8 3.35 TB/s·989 TFLOPS, B200×8 8 TB/s, MFU 0.45. 하한은 attention 2차 항·통신·커널 제외")
    for sh in [s for s in slide.shapes if s.name == "tbl"]:
        remove(sh)
    rows = [["Metric", "측정 정의", "절대 SLO", "근거 (계산)"],
            ["TTFT\n(첫 토큰까지의 시간)",
             "요청 도착 → 첫 출력 토큰 수신. 큐잉 + prefill + (필요 시) KV 복원 시간 포함. 요청별 값의 P99로 판정",
             [[("TTFT P99 ≤ 2 s", {"bold": True})]],
             ["8K prefill 이론 0.32 s = (2 × 70.6B × 8,192 = 1.16 PFLOP) ÷ (H100×8 989 TFLOPS×8 × MFU 0.45 = 3.56 PFLOP/s). 2 s는 이의 약 6배(큐잉 여유).",
              "Agent KV Fleet의 16K 컨텍스트 재prefill은 0.65 s라 약 3배 여유. MLPerf Llama-2-70B 표준 시나리오와 같은 자릿수(2차 자료)"]],
            ["TPOT\n(출력 토큰당 시간)",
             "(요청 E2E − TTFT) ÷ (출력 토큰 수 − 1). 토큰 간 지연의 요청별 평균에 대한 P99로 판정",
             [[("TPOT P99 ≤ 50 ms", {"bold": True})]],
             ["50 ms = 20 tok/s = 성인 묵독(5~6 tok/s)의 약 3.5배. MLPerf interactive 40 ms와 표준 200 ms 사이(2차 자료).",
              "이론 하한: 가중치 141 GB를 step마다 읽으면 H100×8 5.3 ms, B200×8 2.2 ms. 16K KV(5 GiB/세션) batch 64를 더하면 H100 약 18 ms. 50 ms는 이의 약 2.8배 여유"]]]
    add_table(slide, 0.4, 1.25, [1.5, 3.3, 1.5, 6.23], rows, [0.26, 0.82, 0.82], fills=[None, None], size=8.3,
              aligns=["l", "l", "c", "l"])
    # 예산 막대 (좌: TTFT, 우: TPOT)
    tbox(slide, 0.4, 3.3, 12.5, 0.24, [[("SLO 대비 이론 예산 (대역폭·연산 한계 기준 하한이며 실측이 아니다)", {"bold": True, "color": NAVY})]],
         size=10, margins=(0.02, 0, 0, 0))
    budget_bar(slide, 0.4, 3.62, 6.0, "TTFT 예산 (s)", [(0.32, "2F5597", "8K 0.32 s"), (0.65, "7F7F7F", "16K 0.65 s")],
               2.0, "s", 2.4, "8K·16K 입력의 재계산 prefill 시간. 남는 시간이 큐잉·KV 복원·결정 지연의 예산이다(16K에서 1.35 s).", stacked=False)
    budget_bar(slide, 6.9, 3.62, 6.0, "TPOT 예산 (ms, H100×8)", [(5.3, "2F5597", "가중치 5.3"), (12.8, "7F7F7F", "KV 12.8 (batch 64, 16K)")],
               50, "ms", 60, "B200×8은 가중치 하한이 2.2 ms. 오타였던 TPOT 2 ms는 이 모델에서 가중치 읽기 하한보다 낮아 달성 불가.", stacked=True)
    # 적용 규칙
    tbox(slide, 0.4, 4.95, 12.5, 2.2,
         [[("적용 규칙", {"bold": True, "color": NAVY, "size": 10})],
          [("• Q1 SLO goodput: 요청별로 TTFT ≤ 2 s 그리고 TPOT ≤ 50 ms를 함께 만족한 요청의 출력 토큰만 합산한다. 부하 sweep의 최댓값이 Max SLO goodput이다.", {"size": 9})],
          [("• Q3 고부하 지연: 부하는 Baseline Max SLO goodput의 90%로 고정하고 TTFT·TPOT P99로 r을 계산한다. 후보가 SLO(P99)를 넘으면 개선 폭과 무관하게 ☆로 본다.", {"size": 9})],
          [("• 같은 값을 모든 DP 후보와 Baseline에 적용하고, 결과를 본 뒤 바꾸지 않는다. 바꾸면 새 버전으로 취급해 이전 결과와 비교하지 않는다.", {"size": 9})],
          [("• Baseline이 SLO를 만족하지 못하는 시나리오는 조용히 제외하지 않고 infeasible로 표시한다. P99 판정에는 구간당 요청 수 ≥ 1,000(seed별)을 확보한다 [가정].", {"size": 9})],
          [("• 이전 요구에 적힌 TPOT 2 ms는 50 ms의 오타로 확정해 이 덱의 모든 페이지에 50 ms를 쓴다 (소유자 확인 필요).", {"size": 9, "color": "C00000"})]],
         size=9, line_spacing=1.15)



# ============================================================ 이론 값 가져오기
_R = tm.all_results()
SGL = _R["single"]                    # 단일 노드(B0, B1, DP1, DP3)
B0_TPS, B1_TPS = SGL["B0"]["tps"], SGL["B1"]["tps"]
B1_TTFT, B1_TPOT = SGL["B1"]["ttft"], SGL["B1"]["tpot"]
HBM_B1 = SGL["B1"]["hbm"]
CEIL_RATIO = (1 / tm.G0) / SGL["B1"]["lam"]                   # GPU 한계 ÷ B1 (≈2.3)
HBM_FLOOR_GIB = 53                                             # decode 상주분 + 버퍼(이론 하한)


def n0(x):
    return format(round(x), ",")


def q1_spec():
    e = cd.EDGES["Q1"]
    ab = [n0(x * B1_TPS) for x in e]
    r = cd.BAND_TEXT["Q1"]

    def rng(star, extra):
        return [[(r[star], {})], [("(≥ %s tok/s)" % extra, {"size": 7.5, "color": "595959"})]]
    return dict(
        title="처리량 - 평가 기준",
        subtitle="B1(정적 offload) 대비, SLO를 만족하는 조건에서의 처리량(Max값) 증가율 — B0(GPU-only) 대비는 참고",
        src="출처: DirectKV OSDI'26 · KVFlow (arXiv 2507.07400) · InfiniGen OSDI'24 (arXiv 2406.19707). 'up to' 보고값이며 지표·baseline이 달라 직접 비교 아님. 절대값은 theory_model.py의 분석 모델(시뮬레이션 아님)",
        metric=["[Metric] R = Max SLO goodput(후보) ÷ Max SLO goodput(B1)",
                "B0 = vLLM 기본(HBM만, 부족하면 recompute) · B1 = HBM이 차면 LRU로 DRAM, DRAM이 차면 SSD로 옮기는 정적 offload(스케줄링·prefetch 없음). 판정은 B1 대비",
                "Baseline 절대값(이론, Agent KV Fleet 1노드): B0 %s tok/s · B1 %s tok/s (B1 = B0의 %.2fx). ★1 ≥ %s · ★2 ≥ %s · ★3 ≥ %s tok/s" % (
                    n0(B0_TPS), n0(B1_TPS), B1_TPS / B0_TPS, ab[0], ab[2], ab[4]),
                "구간 규칙: ★1 = 문헌 최소 개선 1.2x, ★3 = 1.8x(KVFlow 1.83x, 시나리오 이론 상한 %.1fx의 약 80%%), ★2 = 중점 1.5x, 반 단계는 중점" % CEIL_RATIO],
        metric_h=1.05,
        table_y=2.2,
        rows=[
            (3, rng(3, ab[4]), "KVFlow: agentic workflow에서 SGLang(HiCache, 계층 캐시 baseline) 대비 최대 1.83x(단일)·2.19x(동시 다수). 시나리오 이론 상한(GPU 한계) %.1fx의 약 80%%. "
                               "InfiniGen 3.0x(FlexGen 대비)는 weight까지 offload하는 다른 regime이라 앵커에서 제외" % CEIL_RATIO, "KVFlow, InfiniGen"),
            (2.5, rng(2.5, ab[3]), "★2와 ★3의 중점(1.65x)", "—"),
            (2, rng(2, ab[2]), "★1과 ★3의 중점(1.5x). 문헌 보고 1.2~1.83x의 중간", "—"),
            (1.5, rng(1.5, ab[1]), "★1과 ★2의 중점(1.35x)", "—"),
            (1, rng(1, ab[0]), "DirectKV(OSDI'26): 기존 offload 방식 대비 end-to-end 최대 1.2x = 'offload만으로 얻는 것 위의 최소 개선'. "
                              "참고: 기존 요구 '처리량 2배'는 B0 대비이며 B1이 이미 B0의 %.2fx라 B1 대비로는 %.2fx에 해당" % (B1_TPS / B0_TPS, 2 * B0_TPS / B1_TPS),
             "DirectKV, Stakeholder 요구(B0 대비)"),
            (0, [[(r[0], {})]], "B1 대비 최소 개선(1.2x) 미충족", "—"),
        ],
        chart=dict(
            title="구간 대비 근거 위치 (B1 대비 R)",
            axis=dict(min=1.0, max=3.2, log=False, ticks=[1.0, 1.5, 2.0, 2.5, 3.0], unit="x", ),
            bands=[(1.0, 1.2, 0), (1.2, 1.35, 1), (1.35, 1.5, 1.5), (1.5, 1.65, 2), (1.65, 1.8, 2.5), (1.8, 3.2, 3)],
            markers=[
                dict(kind="point", v=2 * B0_TPS / B1_TPS, style="req", label="Stakeholder '2배'(B0 대비) = B1 대비 %.2fx" % (2 * B0_TPS / B1_TPS)),
                dict(kind="point", v=1.2, style="lit", label="DirectKV: 기존 offload 대비 e2e 최대 1.2x"),
                dict(kind="point", v=1.83, style="lit", label="KVFlow: SGLang HiCache 대비 최대 1.83x (단일 workflow)"),
                dict(kind="point", v=2.19, style="lit", label="KVFlow: 동시 다수 workflow 최대 2.19x"),
                dict(kind="point", v=CEIL_RATIO, style="calc", label="이론 상한: GPU 한계 %.2f turn/s ÷ B1 %.2f turn/s = %.1fx" % (1 / tm.G0, SGL["B1"]["lam"], CEIL_RATIO)),
                dict(kind="point", v=3.0, style="excl", label="InfiniGen: 이전 KV 관리(FlexGen) 대비 최대 3.0x (weight offload 포함 regime)"),
            ]),
    )


def q2_spec():
    e = cd.EDGES["Q2"]
    ab = [n0(HBM_B1 * (1 - x / 100)) for x in e]
    r = cd.BAND_TEXT["Q2"]

    def rng(star, i):
        return [[(r[star], {})], [("(HBM ≤ %s GiB)" % ab[i], {"size": 7.5, "color": "595959"})]]
    ceil_red = (1 - HBM_FLOOR_GIB / HBM_B1) * 100
    return dict(
        title="자원(HBM) 효율성 - 평가 기준",
        subtitle="B1(정적 offload) 대비 HBM 사용량 감소율 (KV 캐시 관리, 압축 제외, 같은 부하·SLO 유지)",
        src="출처[1]: DirectKV OSDI'26 · HeadInfer (arXiv 2502.12574, 검색 요약 기준) · ShadowKV ICML'25 (arXiv 2410.21465). 40~80% 범위는 사용자 인용(원문 대조 필요). 절대값은 분석 모델",
        metric=["[Metric] 감소율 = (B1 HBM 사용 − 후보 HBM 사용) ÷ B1 HBM 사용  (HBM 사용 = HBM에 올라와 있는 KV 크기의 시간 평균)",
                "Baseline 절대값(이론): B0 %s GiB · B1 %s GiB — B1은 HBM이 찰 때까지 채우므로 HBM KV 풀(640×0.9 − 가중치 131 − 활성값 20) 전체를 쓴다. ★1 ≤ %s · ★2 ≤ %s · ★3 ≤ %s GiB" % (
                    n0(HBM_B1), n0(HBM_B1), ab[0], ab[2], ab[4]),
                "이론 상한: 같은 부하에서 decode 상주분(≈33 GiB)과 버퍼(≈20 GiB)만 남기면 ≈ %.0f%% 감소 가능(성능 유지 조건에서는 prefetch 적중에 의존)" % ceil_red,
                "구간 규칙: ★1 = 요구 20%, ★2 = 40%(DirectKV 43%, 'offload 대비' 보고), ★3 = 60%, 반 단계는 중점(10%p 등간격)"],
        metric_h=1.15,
        table_y=2.35,
        rows=[
            (3, rng(3, 4), "이론 상한(≈%.0f%%)과 문헌 상단(HeadInfer 92%%, 1M ctx 단일 요청 극단)보다 보수적인 60%%. ShadowKV(batch 6x)는 key 저랭크 압축 포함이라 제외" % ceil_red, "DirectKV, HeadInfer [1]"),
            (2.5, rng(2.5, 3), "★2와 ★3의 중점", "—"),
            (2, rng(2, 2), "DirectKV: CPU 메모리 직접 접근으로 GPU 메모리 43% 감소(GH200). 기존 offload 방식 대비 보고라 B1과 같은 종류의 baseline", "DirectKV [1]"),
            (1.5, rng(1.5, 1), "★1과 ★2의 중점", "—"),
            (1, rng(1, 0), "시나리오 요구 20%. 계산: HBM 20% 감소 = 같은 HBM에 KV 1/0.8 = 1.25배 수용", "시나리오 요구 / 이론 계산"),
            (0, [[(r[0], {})]], "시나리오 요구(20%) 미충족. 음수는 후보가 HBM을 더 쓴 경우", "—"),
        ],
        chart=dict(
            title="구간 대비 근거 위치 (HBM 감소율 %, B1 대비)",
            axis=dict(min=0, max=100, log=False, ticks=[0, 20, 40, 60, 80, 100], unit="%"),
            bands=[(0, 20, 0), (20, 30, 1), (30, 40, 1.5), (40, 50, 2), (50, 60, 2.5), (60, 100, 3)],
            markers=[
                dict(kind="point", v=20, style="req", label="시나리오 요구 20% (≈ 동시 수용 +25%)"),
                dict(kind="point", v=43, style="lit", label="DirectKV (OSDI'26): 기존 offload 대비 GPU 메모리 43% 감소"),
                dict(kind="range", v=(40, 80), style="lit", label="오프로딩 계열 보고 범위 40~80% [1]"),
                dict(kind="point", v=ceil_red, style="calc", label="이론 상한 ≈ %.0f%% (decode 상주분만 남김)" % ceil_red),
                dict(kind="point", v=83, style="excl", label="ShadowKV: batch 6x ≈ 83%/seq (key 저랭크 압축 포함)"),
                dict(kind="point", v=92, style="excl", label="HeadInfer: 총 GPU 메모리 92% (1M ctx 단일 요청, 극단)"),
            ]),
        left_note=True,
    )


def q3_spec():
    e = cd.EDGES["Q3"]
    tt = [B1_TTFT / (x * x) for x in e]
    r = cd.BAND_TEXT["Q3"]
    reds = [cd.red_of_r(x) for x in e]

    def rng(star, i):
        return [[(r[star] + " (감소율 %.0f%%)" % reds[i], {})], [("(TPOT 동일 시 TTFT ≤ %.2f s)" % tt[i], {"size": 7.5, "color": "595959"})]]
    return dict(
        title="고부하 지연시간(Tail Latency) - 평가 기준",
        subtitle="B1 대비 TTFT·TPOT P99 개선 r (고부하 = B1 Max SLO goodput의 90% 부하, SLO 충족 전제)",
        src="출처: DirectKV OSDI'26 · KVFlow (arXiv 2507.07400) · LMCache (arXiv 2510.09665, 검색 요약 기준). 'up to' 보고값. 절대값은 분석 모델(시뮬레이션 아님)",
        metric=["[Metric] r = √[ (B1 TTFT P99 ÷ 후보 TTFT P99) × (B1 TPOT P99 ÷ 후보 TPOT P99) ],  감소율 = 1 − 1/r",
                "Baseline 절대값(이론): B1 TTFT P99 %.2f s · TPOT P99 %.1f ms (B0는 같은 부하에서 과부하: TTFT %.1f s). TPOT이 같으면 TTFT가 ★1 ≤ %.2f · ★2 ≤ %.2f · ★3 ≤ %.2f s" % (
                    B1_TTFT, B1_TPOT, SGL["B0"]["ttft"], tt[0], tt[2], tt[4]),
                "고부하: 부하를 B1 Max SLO goodput의 90%에 고정(후보 기준이 아님) · SLO(TTFT ≤ 2 s, TPOT ≤ 50 ms) 충족 필수. 구간 규칙: Q1과 같은 앵커 r 1.2 / 1.5 / 1.8"],
        metric_h=0.95,
        table_y=2.1,
        rows=[
            (3, rng(3, 4), "KVFlow: 계층 캐시 baseline 대비 최대 1.83x(단일)·2.19x(동시 다수) workflow 가속의 하단. r 1.8 = 감소율 44%", "KVFlow"),
            (2.5, rng(2.5, 3), "★2와 ★3의 중점", "—"),
            (2, rng(2, 2), "★1과 ★3의 중점(r 1.5). 문헌 보고 1.2~1.83x의 중간", "—"),
            (1.5, rng(1.5, 1), "★1과 ★2의 중점. 기존 Stakeholder '체감 30% 감소'(r 1.43, B0 대비 요구)는 B1 기준에서 이 구간", "Stakeholder 요구사항"),
            (1, rng(1, 0), "DirectKV: 기존 offload 대비 e2e 최대 1.2x(지연 17% 감소) = offload 위의 최소 개선", "DirectKV"),
            (0, [[(r[0], {})]], "r < 1.2 또는 SLO 위반. 음수는 B1보다 나빠진 경우", "—"),
        ],
        chart=dict(
            title="구간 대비 근거 위치 (P99 개선 r, B1 대비)",
            axis=dict(min=1.0, max=3.0, log=False, ticks=[1.0, 1.5, 2.0, 2.5, 3.0], unit="x"),
            bands=[(1.0, 1.2, 0), (1.2, 1.35, 1), (1.35, 1.5, 1.5), (1.5, 1.65, 2), (1.65, 1.8, 2.5), (1.8, 3.0, 3)],
            markers=[
                dict(kind="point", v=1.43, style="req", label="기존 Stakeholder: 30% 감소(r 1.43, B0 대비 요구)"),
                dict(kind="point", v=1.2, style="lit", label="DirectKV: 기존 offload 대비 e2e 최대 1.2x"),
                dict(kind="point", v=1.83, style="lit", label="KVFlow: HiCache 대비 최대 1.83x"),
                dict(kind="point", v=2.19, style="lit", label="KVFlow: 동시 다수 workflow 최대 2.19x"),
                dict(kind="range", v=(1.52, 2.38), style="excl", label="LMCache ITL 34~58% 감소 (vLLM·GPU-only 대비, 참고)"),
            ]),
        keep_picture=True,
    )


# ============================================================ 페이지 6~11 구성
def build_criteria_slides(prs):
    sl = prs.slides
    specs = {5: q1_spec(), 6: q2_spec(), 7: q3_spec(), 9: q4_spec()}
    for idx, spec in specs.items():
        s = sl[idx]
        ty = criteria_page(s, spec)
        ch = spec["chart"]
        if spec.get("keep_picture") or spec.get("left_note"):
            cx, cw = 4.85, 8.1
        else:
            cx, cw = 0.4, 12.5
        band_chart(s, cx, ty + 0.02, cw, ch["axis"], ch["bands"], ch["markers"], title=ch["title"])
    s = sl[7]                                   # Q3: P99 설명 + 그림
    pics = [p for p in s.shapes if p.shape_type == 13]
    tbox(s, 0.4, 4.45, 4.3, 0.55,
         [[("P99의 의미", {"bold": True, "color": NAVY, "size": 9.5})],
          [("상위 1%의 극단적 지연을 포착해 고부하 서비스 끊김을 검증", {"size": 8.5})]], size=8.5, line_spacing=1.05)
    for p in pics:
        p.left, p.top = Inches(0.45), Inches(5.05)
        scale = 1.85 / (p.height / 914400)
        p.width, p.height = int(p.width * scale), int(p.height * scale)
    s = sl[6]                                   # Q2: HBM 사용률 정의
    tbox(s, 0.4, 5.0, 4.3, 1.9,
         [[("HBM 사용량과 전체 Data 대비 사용률", {"bold": True, "color": NAVY, "size": 9.5})],
          [("• HBM 사용량: HBM에 올라와 있는 KV의 시간 평균 크기", {"size": 8.5})],
          [("  예) 100초 중 40초 100 GiB, 60초 50 GiB → 70 GiB", {"size": 8.5, "color": "404040"})],
          [("• 요청이 늘면 HBM 크기 내 점유율은 포화되어 이동 효율을 가리지 못한다 → 전체 KV 대비 사용률을 병기", {"size": 8.5})],
          [("  예) HBM 점유 40→64 GiB, KV 120 GiB: 크기 내 50→80%, 전체 대비 66→53%", {"size": 8.5, "color": "404040"})],
          [("• 압축이 아니므로 정확도(출력)는 변하지 않는다.", {"size": 8.5})]],
         size=8.5, line_spacing=1.1)
    slo_page(sl[8])
    q5_page(sl[10])
    s = sl[10]
    ax_m = dict(min=0, max=7, log=False, ticks=[0, 1, 2, 3, 4, 5, 6, 7], unit="")
    bands_m = [(0, 2, 3), (2, 2.5, 2.5), (2.5, 3, 2), (3, 4, 1.5), (4, 5, 1), (5, 7, 0)]
    mk_m = [dict(kind="point", v=1.7, style="lit", label="SWE-bench 평균 패치 1.7 file (★3 경계 2)"),
            dict(kind="point", v=3.0, style="calc", label="★2 경계 3 ≈ component 12~14개의 1/4"),
            dict(kind="point", v=5, style="req", label="★1 경계: component 12~14개 중 5개(36~42%)")]
    ax_mm = dict(min=0, max=1.5, log=False, ticks=[0, 0.25, 0.5, 0.75, 1.0, 1.25, 1.5], unit="")
    bands_mm = [(0, 0.5, 3), (0.5, 0.625, 2.5), (0.625, 0.75, 2), (0.75, 0.875, 1.5), (0.875, 1.0, 1), (1.0, 1.5, 0)]
    mk_mm = [dict(kind="point", v=0.32, style="calc", label="SWE-bench 평균 패치 환산 0.32 MM"),
             dict(kind="point", v=0.5, style="req", label="1인 2주 sprint (★3 경계)"),
             dict(kind="point", v=1.0, style="req", label="1인 1개월 (★1 경계)"),
             dict(kind="range", v=(0.60, 1.5), style="calc", label="vLLM connector 신규 구현 0.60(192 LOC)~2.98(1,190 LOC) MM")]
    band_chart(s, 0.4, 5.15, 6.0, ax_m, bands_m, mk_m, title="① module 수 (시나리오 평균)", row_h=0.18, label_size=6.8, legend=False)
    band_chart(s, 6.7, 5.15, 6.2, ax_mm, bands_mm, mk_mm, title="② 개발 공수 M/M", row_h=0.18, label_size=6.8, legend=True)


# ============================================================ DP 페이지(2~5): 절대값·개선율 병기
DP_SLIDE = {"DP1": 1, "DP2": 2, "DP3": 3, "DP4": 4}
# 같은 후보 영역(병합된 폭) 안에서 [라벨, (빈 칸), 별] 열 너비를 다시 나눈다 (별 칸을 넓혀 절대값을 넣는다)
COL_PLAN = {
    "DP1": [0.96, 2.86, 1.33, 1.75, 3.05, 1.15, 1.75],
    "DP2": [0.96, 4.20, 1.75, 4.20, 1.75],
    "DP3": [0.96, 4.20, 1.75, 4.20, 1.75],
    "DP4": [0.96, 4.19, 1.75, 4.20, 1.75],
}


def _auto_comment(dp, k, q):
    o = cd.OWNER[(dp, k)].get(q)
    t = cd.theory_star(dp, k, q)
    if o is None or t is None:
        return None
    other = 2 if k == 1 else 1
    if (dp, other) in cd.THEORY and q in cd.THEORY[(dp, other)]:
        a, b = cd.THEORY[(dp, k)][q], cd.THEORY[(dp, other)][q]
        key = {"Q1": "c", "Q4": "c"}.get(q)
        if key and abs(a[key] - b[key]) / max(abs(a[key]), 1e-9) < 0.01:
            return "%d안과 동일" % other
    if t - o >= 1.0:
        return "예상보다 높음"
    if o - t >= 1.0:
        return "예상보다 낮음"
    return None


def annotate_dp(slide, dp):
    tbl_shape = next(s for s in slide.shapes if s.has_table)
    tbl = tbl_shape.table
    for i, w in enumerate(COL_PLAN[dp]):
        tbl.columns[i].width = Inches(w)
    row = tbl.rows[len(tbl.rows) - 1]
    cells = row.cells
    star_idx = [i for i, c in enumerate(cells) if "●" in c.text]
    for k, si in enumerate(star_idx, start=1):
        li = si - 1
        blanks = []
        while li > 0 and not cells[li].text.strip().startswith("Q"):
            blanks.append(li)
            li -= 1
        label_cell, star_cell = cells[li], cells[si]
        labels = {}
        for p in label_cell.text_frame.paragraphs:
            m = re.match(r"\s*Q(\d)\.", p.text)
            if m:
                labels["Q" + m.group(1)] = p
        q_order = list(labels.keys())
        star_pars = [p for p in star_cell.text_frame.paragraphs if p.text.strip()]
        star_cell._tc.get_or_add_tcPr().set("marR", "0")
        blank_cell = cells[blanks[0]] if blanks else None
        if blank_cell is not None:
            btf = blank_cell.text_frame
            while len(btf.paragraphs) < len(q_order):
                btf.add_paragraph()
        for qi, q in enumerate(q_order):
            txt = cd.cell_text(dp, k, q) if (dp, k) in cd.THEORY else "—"
            r = star_pars[qi].add_run()
            r.text = " " + txt
            _font(r, 6.3, False, "404040")
            cm = _auto_comment(dp, k, q) if (dp, k) in cd.THEORY else None
            if blank_cell is not None:
                bp = blank_cell.text_frame.paragraphs[qi]
                sp0 = bp.add_run()
                sp0.text = " "
                _font(sp0, 12, False, "FFFFFF")
                if cm:
                    rr = bp.add_run()
                    rr.text = "▸ " + cm
                    _font(rr, 7.5, False, "0000FF")
            elif cm:
                rr = labels[q].add_run()
                rr.text = "   ▸ " + cm
                _font(rr, 7.5, False, "0000FF")
    tbox(slide, 0.62, 7.2, 4.3, 0.28,
         [[("작은 수치 = B1(정적 offload) → 후보의 이론 예상값(분석 모델, 시뮬레이션 아님)과 개선율. ", {"size": 6.3, "color": "595959"}),
           ("파란 글씨 = 소유자 별 대비 코멘트.", {"size": 6.3, "color": "0000FF"})]],
         size=6.3, line_spacing=0.95, margins=(0.02, 0.0, 0.02, 0.0), name="legend_v4")


# ============================================================ 요구사항 페이지(1)
def _replace_run(par, old, new):
    for r in par.runs:
        if r.text == old:
            r.text = new
            return True
    return False


def edit_requirements(slide):
    tbl = next(s for s in slide.shapes if s.has_table).table
    for r in tbl.rows:
        n = r.cells[0].text.strip()
        c = r.cells[3]
        pars = c.text_frame.paragraphs
        if n == "QA-01":
            p = pars[0]
            _replace_run(p, "(Baseline)", "(B1: 정적 offload)")
            _replace_run(p, "≥ Baseline ", "≥ B1 ")
            _replace_run(p, "2x (Stakeholder ", "1.2x (B0 GPU-only 대비 2x는 Stakeholder ")
            _replace_run(p, "요구사항", "요구, 참고")
        elif n == "QA-02":
            p = pars[0]
            _replace_run(p, "Baseline", "B1(정적 offload)")
            _replace_run(p, "> Baseline ", "≥ B1 ")
            _replace_run(p, "20% ] ]", "20% ]")
        elif n == "QA-03":
            p = pars[1]
            _replace_run(pars[0], "baseline ", "B1 ")
            _replace_run(p, ": TTFT·TPOT(P99) ≥ Baseline ", ": TTFT·TPOT(P99) 개선 r ≥ B1 ")
            _replace_run(p, "대비 감소율 ", "대비 ")
            _replace_run(p, "30% (", "1.2 (감소율 17%, ")
            _replace_run(p, "사용자 체감 성능 개선 기준", "B0 대비 30%는 사용자 체감 기준")
        elif n == "QA-05":
            p0 = pars[0]
            sz = 9
            for run in p0.runs:
                if run.font.size:
                    sz = run.font.size.pt
                break
            for p in pars[1:]:
                p._p.getparent().remove(p._p)
            for run in list(p0.runs):
                p0._p.remove(run._r)
            add_runs(p0, "새로운 메모리 tier 추가, 이동·배치·재사용 정책 교체, vLLM upstream 갱신 시 서빙 경로를 수정하지 않고 반영할 수 있어야 한다.", sz)
            p1 = c.text_frame.add_paragraph()
            add_runs(p1, [("[측정: 변경 모듈 수 ≤ 5개, 개발 공수 ≤ 1.0 M/M (변경 시나리오 3종 평균, 두 조건 모두 만족)]", {"color": "000000", "bold": True})], sz)


# ============================================================ 신규 페이지
def clone_chrome(prs, ref_idx, title, subtitle, src):
    ref = prs.slides[ref_idx]
    s = prs.slides.add_slide(ref.slide_layout)
    for ph in list(s.placeholders):
        ph._element.getparent().remove(ph._element)
    for nm in ("title", "rule", "src"):
        sh = shape_by_name(ref, nm)
        s.shapes._spTree.append(copy.deepcopy(sh._element))
    sub = None
    for sh in ref.shapes:
        if sh.name == "subtitle" and sh.top < Inches(0.9):
            sub = sh
    s.shapes._spTree.append(copy.deepcopy(sub._element))
    set_text_keep_first(shape_by_name(s, "title"), [[(title, {"size": 22, "bold": True, "color": NAVY})]])
    for sh in s.shapes:
        if sh.name == "subtitle":
            set_text_keep_first(sh, [[(subtitle, {"size": 11, "color": "404040"})]])
    set_text_keep_first(shape_by_name(s, "src"), [[(src, {"size": 7.5, "color": "404040"})]])
    return s


def scenario_slides(prs):
    s = clone_chrome(prs, 5, "평가 시나리오 - Agent KV Fleet (DP1~4 공통)",
                     "KV 캐시 관리만 대상(RAG·LoRA·MoE 제외). KV가 HBM·DRAM 용량을 넘고 재사용할 history가 있는 구간을 겨냥한 통합 시나리오",
                     "근거: Llama-3.1-70B KV 327,680 B/token · H100×8 HBM 640 GiB, 가중치 약 131 GiB · prefill ≈ 25k tok/s(MFU 0.45) · DRAM 1 TiB, NVMe 16 GB/s(system-specs). 부하·idle 분포는 설계값[가정]")
    rows = [["항목", "값", "근거 / 계산"],
            ["모델·HW", "Llama-3.1-70B BF16, 8-GPU 노드(SYS-H100): HBM 640 GiB, DRAM 1 TiB(호스트 링크 64 GB/s), NVMe 16 GB/s. DP2·DP4는 4~16 노드",
             "기존 평가 환경과 동일(비교 가능성). 노드 간 링크는 RDMA 50 GB/s [ASSUMED]"],
            ["요청 모델", "open-loop. 세션 idle 시간 지수분포 평균 60 s(tool·사용자 대기, 0.2 s~수 분), 컨텍스트 평균 16K, 턴당 +1K 입력·출력 256, 세션당 10~20턴",
             "16K 세션 KV = 327,680 B × 16,384 ≈ 5.0 GiB. 동시 세션 수 = λ × (idle + 응답) ≈ 250~330 (λ 3.8~5 turn/s)"],
            ["메모리 압박", "HBM KV 풀 ≈ 425 GiB(≈85 세션분) + DRAM 922 GiB(≈184 세션분). 동시 세션 KV 1.3~1.6 TiB는 HBM+DRAM(1.35 TiB)도 넘어 SSD가 쓰인다",
             "반환 세션이 HBM/DRAM/SSD에서 발견될 확률은 LRU stack distance로 계산(idle ~ Exp(60 s))"],
            ["재사용", "세션 간 공유 문서 청크 30%, 그중 50%는 non-prefix 위치. 선택 재계산 15% 토큰 [가정]",
             "DP3 재사용·선택 재계산이 겨냥하는 조건. B0·B1은 세션마다 복제 저장"],
            ["부하·SLO", "Q1: 부하 sweep의 Max SLO goodput(이용률 상한 0.8 [가정]). Q3: B1 Max SLO goodput의 90% 고정 부하. TTFT P99 ≤ 2 s, TPOT P99 ≤ 50 ms",
             "Q4: 노드 2→16 sweep, SE(16)"],
            ["B0 GPU-only", "vLLM 기본: HBM prefix cache + preemption recompute, DRAM·SSD 사용 없음",
             "HBM에 없으면 16K 재prefill ≈ 0.65 s. '스케줄링도 offload도 없는' 하한"],
            ["B1 정적 offload (판정 Baseline)", "HBM이 차면 LRU로 DRAM, DRAM이 차면 SSD로 옮김. 전체 write-back, 요청 시 동기 복원, prefetch·예측·배치 정책 없음",
             "DP1의 '정적 DRAM swap/offload'를 SSD 계층까지 확장한 정의. 후보와 같은 메모리·대역폭을 쓴다(후보 전용 메모리는 B1이 쓰지 않음)"],
            ["반복", "분석 모델은 결정적(deterministic). 시뮬레이션 전환 시 seed ≥ 5, median, 95% CI", "단일 seed로 별점을 매기지 않는다"]]
    add_table(s, 0.4, 1.2, [1.55, 6.3, 4.68], rows, [0.26] + [0.55] * 8, fills=[None] * 8, size=8.2, aligns=["l", "l", "l"])
    tbox(s, 0.4, 6.2, 12.5, 0.8,
         [[("조건부 별: ", {"bold": True, "color": "C00000", "size": 9.5}),
           ("이 시나리오는 KV가 HBM·DRAM을 넘고 재사용할 history가 있는 구간을 의도적으로 겨냥한다(문헌이 이득을 보고한 조건과 같은 영역). "
            "짧은 컨텍스트·KV 여유 구간에서는 B1과의 차이가 줄어들므로 별은 '이 regime에서의 별'로 읽는다. 값은 분석 모델의 예상값이며 시뮬레이션 전이다.", {"size": 9})]],
         size=9, line_spacing=1.1)

    s2 = clone_chrome(prs, 5, "평가 시나리오 - 구간(Phase)과 DP·QA 대응",
                      "한 시나리오 안에서 DP별 메커니즘이 작동하는 구간을 나누고, QA별 측정 규칙을 정한다",
                      "N 노드 확장(P4)은 별도 run(N = 2, 4, 8, 16, 세션 수 ∝ N). 모든 값은 분석 모델 기반 설계값이다.")
    rows = [["Phase", "구간 내용", "겨냥하는 DP 메커니즘", "측정 QA"],
            ["P1 정상 multi-turn\n(0~10분)", "agent 세션이 idle을 두고 턴을 이어 감. 유휴 KV가 HBM을 점유",
             "DP1: 유휴 KV 하위 tier 이동(demote)과 재개 시 승격·prefetch. 1안 = 자원 상태 기반, 2안 = 데이터 접근 특성 기반", "Q1, Q2, Q3, Q5"],
            ["P2 burst\n(10~15분)", "신규 세션 3배 폭주 + 기존 세션 decode가 겹침(prefill burst + decode-heavy)",
             "DP2: Prefill/Decode 실행 위치 결정. 1안 = 스케줄링 시점 결정, 2안 = 사전 계획 결정(Re-plan 위험)", "Q1, Q2, Q3, Q4"],
            ["P3 공유 문서 wave\n(15~25분)", "같은 문서 청크를 여러 세션이 연달아 참조(non-prefix 50%)",
             "DP3: 재사용·재계산 대상 선정. 1안 = Pipe-and-Filter(요청마다 체인), 2안 = Shared Repository(분석 1회 + 조회), 둘 다 선택 재계산", "Q1, Q2, Q3"],
            ["P4 노드 확장\n(별도 run)", "노드 2→16, 세션 수 ∝ 노드 수. 노드 간 KV 블록 조회·소유권 이동 발생",
             "DP4: 서버 간 KV 공유. 1안 = 중앙 서버 중재, 2안 = 락 기반 직접 접근. CXL 공유 풀이 SSD를 대체", "Q1, Q3, Q4"],
            ["변경 시나리오\n(구현 측정)", "S1 새 메모리 tier · S2 정책 교체 · S3 vLLM upstream 갱신", "모든 DP 후보의 module 수·M/M (시나리오 평균)", "Q5"]]
    add_table(s2, 0.4, 1.2, [1.6, 3.9, 5.5, 1.53], rows, [0.26] + [0.62] * 5, fills=[None] * 5, size=8.5, aligns=["l", "l", "l", "c"])
    tbox(s2, 0.4, 4.9, 12.5, 1.5,
         [[("측정 규칙", {"bold": True, "color": NAVY, "size": 10})],
          [("• Q1: 부하 sweep 최댓값끼리 R = 후보 ÷ B1 · Q2: HBM 상주 KV 시간 평균의 B1 대비 감소율 · Q3: B1 Max SLO goodput의 90% 부하에서 TTFT·TPOT P99로 r 계산", {"size": 9})],
          [("• Q4: 노드 2→16 sweep, SE(16) = goodput 배율 ÷ 노드 배율 · Q5: 변경 시나리오 3종을 각 후보에 구현해 module 수·M/M 평균", {"size": 9})],
          [("• 기준·시나리오 값은 결과를 보기 전에 고정한다. 기존 중립 벤치마크(8K 입력, batch 32) 시뮬 결과는 md의 참고 표에만 두고 이 시나리오 값과 섞지 않는다.", {"size": 9})]],
         size=9, line_spacing=1.12)
    return s, s2


def baseline_slide(prs):
    s = clone_chrome(prs, 5, "평가 Baseline 정의와 절대 수치",
                     "판정은 B1(정적 offload) 대비. B0(GPU-only)는 참고. 절대값은 이론 계산(Agent KV Fleet, SYS-H100)",
                     "분석 모델: theory_model.py (GPU 한계 · DRAM 링크 51 GB/s · SSD 링크 12.8 GB/s 중 최솟값 × 이용률 0.8). 시뮬레이션이 아니며 후보 파라미터는 [가정]")
    c2, c4 = _R["dp2"], _R["dp4"]
    e1, e2, e3 = cd.EDGES["Q1"], cd.EDGES["Q2"], cd.EDGES["Q3"]
    t = lambda base, i: n0(base * e1[i])
    rows = [["QA", "범위", "지표", "B0 GPU-only", "B1 정적 offload", "이론 상한", "★1", "★2", "★3"],
            ["Q1 처리량", "1 노드", "Max SLO goodput (tok/s)", n0(B0_TPS), n0(B1_TPS), "%s (GPU 한계)" % n0(tm.UTIL_CAP * tm.OUT / tm.G0),
             "≥ " + t(B1_TPS, 0), "≥ " + t(B1_TPS, 2), "≥ " + t(B1_TPS, 4)],
            ["", "DP2 4노드 (P2+D2 고정)", "Max SLO goodput (tok/s)", n0(c2["B0"]["tps"]), n0(c2["B1"]["tps"]), "—",
             "≥ " + t(c2["B1"]["tps"], 0), "≥ " + t(c2["B1"]["tps"], 2), "≥ " + t(c2["B1"]["tps"], 4)],
            ["", "DP4 4노드 (노드 독립)", "Max SLO goodput (tok/s)", n0(c4["B0"]["tps"]), n0(c4["B1"]["tps"]), "—",
             "≥ " + t(c4["B1"]["tps"], 0), "≥ " + t(c4["B1"]["tps"], 2), "≥ " + t(c4["B1"]["tps"], 4)],
            ["Q2 HBM 효율", "1 노드", "HBM 상주 KV (GiB, 낮을수록 좋음)", n0(HBM_B1), n0(HBM_B1), "≈ %d (decode 상주분)" % HBM_FLOOR_GIB,
             "≤ %s" % n0(HBM_B1 * 0.8), "≤ %s" % n0(HBM_B1 * 0.6), "≤ %s" % n0(HBM_B1 * 0.4)],
            ["", "DP2 4노드", "HBM 상주 KV (GiB)", n0(c2["B1"]["hbm"]), n0(c2["B1"]["hbm"]), "—",
             "≤ %s" % n0(c2["B1"]["hbm"] * 0.8), "≤ %s" % n0(c2["B1"]["hbm"] * 0.6), "≤ %s" % n0(c2["B1"]["hbm"] * 0.4)],
            ["Q3 고부하 지연", "B1 90% 부하", "TTFT P99 (s) / TPOT P99 (ms)", "%.1f s / %.1f ms (과부하)" % (SGL["B0"]["ttft"], SGL["B0"]["tpot"]),
             "%.2f s / %.1f ms" % (B1_TTFT, B1_TPOT), "—",
             "TTFT ≤ %.2f s" % (B1_TTFT / e3[0] ** 2), "≤ %.2f s" % (B1_TTFT / e3[2] ** 2), "≤ %.2f s" % (B1_TTFT / e3[4] ** 2)],
            ["Q4 확장성", "N=16", "SE (%)", "98 (노드 독립)", "98 (노드 독립)", "100 (선형)", "≥ 80", "≥ 90", "≥ 95"],
            ["Q5 변경 용이성", "후보 구현", "module 수 · M/M (절대 기준)", "—", "—", "—", "≤5 · ≤1.0", "≤3 · ≤0.75", "≤2 · ≤0.5"]]
    add_table(s, 0.4, 1.2, [1.35, 1.75, 2.3, 1.55, 1.5, 1.35, 0.9, 0.9, 0.93], rows, [0.28] + [0.38] * 8, fills=[None] * 8, size=8,
              aligns=["l", "l", "l", "c", "c", "c", "c", "c", "c"])
    tbox(s, 0.4, 4.7, 6.1, 2.4,
         [[("Baseline 정의", {"bold": True, "color": NAVY, "size": 10})],
          [("• B0 GPU-only: vLLM 기본. KV가 HBM에 없으면 16K 재prefill(≈0.65 s). 스케줄링도 offload도 없음", {"size": 8.8})],
          [("• B1 정적 offload(판정 기준): HBM이 차면 LRU로 DRAM, DRAM이 차면 SSD로 이동. 전체 write-back, 요청 시 동기 복원, prefetch·예측 없음. "
            "DP1의 정적 DRAM swap/offload를 SSD 계층까지 확장", {"size": 8.8})],
          [("• 후보는 B1과 같은 메모리·대역폭을 쓴다. DP2의 B1은 P/D 고정 역할, DP4의 B1은 노드 독립(교차 라우팅 25%는 재계산)", {"size": 8.8})]],
         size=8.8, line_spacing=1.12)
    tbox(s, 6.7, 4.7, 6.2, 2.4,
         [[("읽는 법", {"bold": True, "color": NAVY, "size": 10})],
          [("• B1은 B0의 %.2f배: 정적 offload만으로 얻는 이득이 이미 크다. 이 위에서의 개선이 DP 후보의 몫이다" % (B1_TPS / B0_TPS), {"size": 8.8})],
          [("• 기존 요구 '처리량 2배'(B0 대비)는 B1 대비 %.2f배와 같다 → ★1(1.2배)과 거의 일치" % (2 * B0_TPS / B1_TPS), {"size": 8.8})],
          [("• 이론 상한: GPU 한계(8.85 turn/s)에서 B1(%.2f turn/s)까지의 여유 = %.1f배. 어떤 설계도 이 이상은 못 얻는다" % (SGL["B1"]["lam"], CEIL_RATIO), {"size": 8.8})],
          [("• Q2·Q3 이론 상한: HBM ≈ 88% 절감, TTFT는 prefill(≈41 ms)까지", {"size": 8.8})]],
         size=8.8, line_spacing=1.12)
    return s


def method_slide(prs):
    s = clone_chrome(prs, 5, "이론 계산 기반 예상값 산출 방식",
                     "B0·B1은 물리 한계에서 계산하고, 후보는 같은 식에 설계 파라미터만 바꿔 넣는다 (시뮬레이션 아님)",
                     "코드: doc-mk/QA-criteria-v4/theory_model.py. 후보 파라미터는 덱의 장단점과 DP1 요구 수치(prefetch 적중 ≥ 60~70%, 낭비 ≤ 30%)에서 방향만 가져온 [가정]이며 시뮬레이션으로 교체한다")
    tbox(s, 0.4, 1.17, 6.2, 3.0,
         [[("계산 구조", {"bold": True, "color": NAVY, "size": 10})],
          [("① 반환 세션 hit: LRU stack distance. idle ~ Exp(60 s), 그 사이 서로 다른 세션 λT개 접근 → HBM(85 세션분)·DRAM(184 세션분)에서 발견될 확률", {"size": 8.5})],
          [("② 처리 한계 λ = min(GPU 1/0.113 s, DRAM 링크 51 GB/s ÷ 이동 바이트, SSD 링크 12.8 GB/s ÷ 이동 바이트). Max SLO goodput = 0.8 × 256 tok × λ", {"size": 8.5})],
          [("③ 이동 바이트 = miss × (1−π) 동기 복원 + miss × π × (1+ω) prefetch + w × miss write-back (π 적시율, ω 낭비, w write-back 비율)", {"size": 8.5})],
          [("④ TTFT P99 = 새 입력 prefill 41 ms + 결정 지연 + 99% 복원 경로 ÷ (1 − 링크 이용률). TPOT P99 = 18.1 ms × (1 + 0.5 × 이용률)", {"size": 8.5})],
          [("⑤ SE(16) = min(1, 결정 용량 ÷ 요구 결정률). 결정 비용은 후보 수에 선형(2 ms × N) [기존 평가의 ASSUMED]", {"size": 8.5})]],
         size=8.5, line_spacing=1.1)
    tbox(s, 6.8, 1.17, 6.1, 3.0,
         [[("한계(정직하게)", {"bold": True, "color": "C00000", "size": 10})],
          [("• 후보 파라미터(θ, w, π, ω, watermark, u_P …)는 가정이다. 값이 바뀌면 별이 바뀐다", {"size": 8.5})],
          [("• 큐잉은 링크 이용률 1/(1−ρ)로 근사했다. 연속 배칭·chunked prefill의 세부는 반영하지 않았다", {"size": 8.5})],
          [("• 이용률 상한 0.8, idle 평균 60 s, 공유 문서 30%는 설계값이다", {"size": 8.5})],
          [("• DP2·DP4는 4노드 요약 모델이다. 결정 용량·제어 평면 지연은 기존 평가의 상수를 썼다", {"size": 8.5})],
          [("• 기존 중립 벤치마크 시뮬(8K, batch 32)과 값이 다르다. 그쪽은 압박이 없는 조건이라 B1 대비 이득이 작다", {"size": 8.5})]],
         size=8.5, line_spacing=1.1)
    rows = [["후보", "θ 배치 효율", "w write-back", "π prefetch 적시", "ω 낭비", "추가 GPU·결정 지연", "HBM watermark", "근거(덱 장단점·요구 수치)"],
            ["B1", "1.0", "1.0", "0", "0", "—", "1.00", "정의상 정적 LRU, 전체 write-back, 동기 복원"],
            ["DP1 1안 자원 상태", "1.1", "0.5", "0", "0", "결정 3 ms", "0.80", "임계 trigger로 HBM 압박 구간 단축, 접근 특성 구분 한계"],
            ["DP1 2안 데이터 특성", "1.3", "0.3", "0.6", "0.3", "0", "0.95", "접근 특성 기반 이동·prefetch(요구 70%에서 낭비 차감), snapshot stale로 HBM 확보 지연"],
            ["DP2 1안 스케줄링 시점", "유휴 P 노드 활용 u_P 0.2", "—", "—", "—", "결정 8 ms(2 ms × N)", "0.85", "실시간 상태 반영, 결정 지연이 critical path"],
            ["DP2 2안 사전 계획", "u_P 0.5", "—", "—", "—", "Re-plan P99 +40 ms", "0.92", "결정은 critical path 밖, 고부하 시 Re-plan(31%), plan 예약으로 HBM 여유 필요"],
            ["DP3 1안 Pipe-and-Filter", "dedup 0.70", "1.0", "0", "0", "GPU +27 ms, 체인 tail 25 ms", "0.60", "관련 KV만 보유(HBM↓), 요청마다 체인 중복 계산, 고부하 tail"],
            ["DP3 2안 Shared Repository", "dedup 0.70", "1.0", "0", "0", "GPU +3 ms", "0.75", "분석 1회+조회라 처리량·tail 유리, 재사용 KV·위치 사전 보유로 점유↑"],
            ["DP4 1안 / 2안", "CXL 풀이 SSD 대체", "1.0", "0", "0", "RPC 7 µs / 락 P99 804 µs × 4 op", "—", "노드 유효 63 GB/s, 교차 라우팅 25% 재계산 제거, 제어 평면은 요청당 ms 이하"]]
    add_table(s, 0.4, 4.2, [1.9, 1.35, 0.85, 1.05, 0.7, 1.9, 1.0, 3.78], rows, [0.3] + [0.325] * 8, fills=[None] * 8, size=7.4,
              aligns=["l", "c", "c", "c", "c", "c", "c", "l"], header_size=8)
    return s


QLAB = {"Q1": ("Q1 처리량", "SLO(TTFT ≤ 2 s, TPOT ≤ 50 ms) 만족 Max goodput"),
        "Q2": ("Q2 HBM 효율", "HBM 상주 KV 시간 평균(GiB), 같은 부하·SLO"),
        "Q3": ("Q3 고부하 지연", "B1 Max SLO goodput의 90% 부하에서 TTFT·TPOT P99"),
        "Q4": ("Q4 확장성", "SE(N=16) = goodput 배율 ÷ 노드 배율"),
        "Q5": ("Q5 변경 용이성", "변경 시나리오 평균 module 수·M/M (기존 구현 측정)")}

DPINFO = {
    "DP1": dict(title="DP1. Data Migration 결정 구조 — Trade-off 평가 결과", names=("1안 상태 관측+이동 결정 통합", "2안 관측·결정 분리"),
                qs=["Q1", "Q2", "Q3", "Q5"], scope="single",
                env=["1 노드: H100×8(HBM 640 GiB), DRAM 1 TiB(호스트 링크 64 GB/s), NVMe 16 GB/s", "Llama-3.1-70B BF16, SYS-H100 (B200은 같은 모델의 세대 민감도)"],
                scen=["Agent KV Fleet P1 정상 multi-turn: 컨텍스트 16K, 턴당 +1K·출력 256, idle 평균 60 s(open-loop)",
                      "동시 세션 ≈ 250~330 → KV 1.3~1.6 TiB(HBM 풀 425 GiB의 3~4배, HBM+DRAM도 초과)"]),
    "DP2": dict(title="DP2. 연산(Prefill/Decode) 실행 위치 결정 구조 — Trade-off 평가 결과", names=("1안 스케줄링 시점 결정", "2안 사전 계획 결정"),
                qs=["Q1", "Q2", "Q3", "Q4"], scope="cluster",
                env=["4 노드 클러스터: B1 = P 2대 + D 2대 고정 역할, 각 노드 정적 offload", "노드 간 RDMA 50 GB/s [ASSUMED], 결정 비용은 후보 수에 선형(2 ms × N)"],
                scen=["Agent KV Fleet P2 burst: 신규 세션 3배 폭주 + decode 중첩. 동적 배치가 유휴 P 노드의 tier·링크를 쓰는 정도 평가",
                      "확장성은 N=16 sweep(scheduler 결정 용량 대 요구 결정률)"]),
    "DP3": dict(title="DP3. KV 캐시 재사용 구조 — Trade-off 평가 결과", names=("1안 Pipe-and-Filter", "2안 Shared Repository"),
                qs=["Q1", "Q2", "Q3"], scope="single",
                env=["1 노드(DP1과 같은 HW). 압축은 범위 밖, 선택 재계산만 사용", "Llama-3.1-70B BF16, SYS-H100"],
                scen=["Agent KV Fleet P3 공유 문서 wave: 컨텍스트의 30%가 세션 간 공유 문서(그중 50% non-prefix)",
                      "B0·B1은 세션마다 복제 저장, DP3는 1회 보관 + 선택 재계산(15% 토큰) [가정]"]),
    "DP4": dict(title="DP4. 서버 간 KV 캐시 공유 구조 — Trade-off 평가 결과", names=("1안 중앙 서버 중재", "2안 락 기반 직접 접근"),
                qs=["Q1", "Q3", "Q4"], scope="cluster",
                env=["4 노드 + CXL 공유 풀 8 TiB(노드당 유효 63 GB/s). B1은 노드 독립(SSD 16 GB/s)", "교차 라우팅 25%는 B1에서 재계산, 후보는 풀에서 공유"],
                scen=["Agent KV Fleet P4 노드 확장: 2→16 노드(세션 ∝ 노드), 노드 간 KV 블록 조회·소유권 이동",
                      "제어 평면: 중앙 RPC ≈ 7 µs vs 분산 락 P99 ≈ 804 µs (요청당 4 op)"]),
}


def _cands(dp):
    return [cd.THEORY[(dp, 1)], cd.THEORY[(dp, 2)]]


def _conclusion(dp):
    a, b = _cands(dp)
    f = lambda x: "%+.0f%%" % x
    if dp == "DP1":
        return ["2안(데이터 특성 기반)은 B1 대비 처리량 %s·TTFT P99 %s로 성능에서 앞서고, 1안(자원 상태 기반)은 HBM %s로 자원 효율에서 앞선다 — 소유자 평가의 trade-off 방향과 같다." % (
            f((b["Q1"]["r1"] - 1) * 100), f(-b["Q3"]["ttft_red"]), f(-a["Q2"]["red"])),
            "GPU-only(B0) 대비 처리량은 ×%.1f~×%.1f. 다만 B1 대비 처리량·지연 개선은 ★1 구간(1.2~1.35배)에 머문다." % (a["Q1"]["r0"], b["Q1"]["r0"])]
    if dp == "DP2":
        return ["B1(P/D 고정 + 정적 offload) 대비 2안(사전 계획)이 처리량 %s·TTFT %s, 1안(스케줄링 시점)이 %s·%s. 유휴 P 노드의 tier·링크를 더 쓰는 쪽이 앞선다." % (
            f((b["Q1"]["r1"] - 1) * 100), f(-b["Q3"]["ttft_red"]), f((a["Q1"]["r1"] - 1) * 100), f(-a["Q3"]["ttft_red"])),
            "확장성은 1안이 단일 scheduler 결정 용량에 막혀 N=16에서 SE %.0f%%, 2안은 worker 분산으로 %.0f%%. HBM은 두 안 모두 %s~%s로 ★1(20%%) 미달." % (
                a["Q4"]["c"], b["Q4"]["c"], f(-b["Q2"]["red"]), f(-a["Q2"]["red"]))]
    if dp == "DP3":
        return ["두 안 모두 공유 문서를 1회만 보관(−30%%)해 B1 대비 처리량 %s, TTFT P99 %s~%s. 1안은 관련 KV만 보유해 HBM %s, 2안은 사전 보유로 %s." % (
            f((a["Q1"]["r1"] - 1) * 100), f(-a["Q3"]["ttft_red"]), f(-b["Q3"]["ttft_red"]), f(-a["Q2"]["red"]), f(-b["Q2"]["red"])),
            "안 간 처리량 차이는 링크 병목 구간이라 거의 없다(1안의 체인 비용은 GPU 병목이 아님). 소유자가 예상한 1안의 고부하 tail 발산은 90% 부하에서는 나타나지 않는다."]
    return ["CXL 공유 풀이 SSD(16 GB/s)를 대체하고 교차 라우팅 재계산을 없애 B1 대비 처리량 %s, TTFT P99 %s(r %.1f). B0 대비 ×%.1f." % (
        f((a["Q1"]["r1"] - 1) * 100), f(-a["Q3"]["ttft_red"]), a["Q3"]["r"], a["Q1"]["r0"]),
        "두 안의 제어 평면 차이(중앙 RPC 7 µs vs 락 P99 804 µs)는 요청당 수 ms 이하라 성능이 거의 같고, N=16에서 SE %.0f%%로 동일하다. 소유자가 예상한 락 기반의 확장 우위는 이 규모에서는 드러나지 않는다." % a["Q4"]["c"]]


def dp_result_slide(prs, dp):
    info = DPINFO[dp]
    s = clone_chrome(prs, 5, info["title"],
                     "평가 환경·시나리오와 GPU-only(B0)·단순 offload(B1) 대비 개선 요약 (이론 계산 기반 예상값)",
                     "예상값은 theory_model.py 분석 모델(시뮬레이션 아님, 후보 파라미터 [가정]). 별은 B1 대비 새 기준(5구간) 적용 결과이고 괄호는 소유자 trade-off 별. 구간·근거는 평가 기준 페이지 참조")
    tbox(s, 0.4, 1.18, 6.15, 1.1,
         [[("평가 환경", {"bold": True, "color": NAVY, "size": 9.5})]] + [[("• " + x, {"size": 8.6})] for x in info["env"]],
         size=8.6, line_spacing=1.1)
    tbox(s, 6.75, 1.18, 6.15, 1.1,
         [[("평가 시나리오", {"bold": True, "color": NAVY, "size": 9.5})]] + [[("• " + x, {"size": 8.6})] for x in info["scen"]],
         size=8.6, line_spacing=1.1)
    rows = [["QA", "무엇을 평가했나", "B0 GPU-only", "B1 단순 offload", "후보 " + info["names"][0], "후보 " + info["names"][1]]]
    fills = []
    nrow = len(info["qs"])
    for q in info["qs"]:
        lab, how = QLAB[q]
        t1, t2 = cd.THEORY[(dp, 1)].get(q), cd.THEORY[(dp, 2)].get(q)
        if q == "Q1":
            b0c, b1c = n0(t1["b0"]) + " tok/s", n0(t1["b1"]) + " tok/s"
        elif q == "Q2":
            b0c, b1c = n0(t1["b0"]) + " GiB", n0(t1["b1"]) + " GiB"
        elif q == "Q3":
            b0c = "SLO 초과(과부하)"
            b1c = "TTFT %.2f s · TPOT %.1f ms" % (t1["b1_ttft"], t1["b1_tpot"])
        elif q == "Q4":
            b0c, b1c = "SE %.0f%%" % t1["b1"], "SE %.0f%%" % t1["b1"]
        else:
            b0c, b1c = "—", "—"
        cells = []
        for k, t in ((1, t1), (2, t2)):
            st = cd.theory_star(dp, k, q)
            own = cd.OWNER[(dp, k)][q]
            if q == "Q1":
                l1 = "%s tok/s" % n0(t["c"])
                l2 = "B1 %s · B0 ×%.1f" % ("%+.0f%%" % ((t["r1"] - 1) * 100), t["r0"])
            elif q == "Q2":
                l1 = "%s GiB" % n0(t["c"])
                l2 = "B1·B0 대비 %s" % ("%+.0f%%" % (-t["red"]))
            elif q == "Q3":
                l1 = "TTFT %.2f s · TPOT %.1f ms" % (t["c_ttft"], t["c_tpot"])
                l2 = "B1 대비 r %.2f (TTFT %s)" % (t["r"], "%+.0f%%" % (-t["ttft_red"]))
            elif q == "Q4":
                l1 = "SE %.0f%%" % t["c"]
                l2 = "B1 대비 %+.0f%%p" % (t["c"] - t["b1"])
            else:
                l1 = "%g module · %.2f MM" % (t["module"], t["mm"])
                l2 = "절대 기준(Baseline 없음)"
            l3 = "%s (소유자 %s)" % (cd.fmt_star(st), cd.fmt_star(own))
            cells.append([[(l1, {"bold": True, "size": 8.5})], [(l2, {"size": 7.8, "color": "404040"})], [(l3, {"size": 8, "bold": True, "color": NAVY})]])
        rows.append([[[(lab, {"bold": True})]], how, b0c, b1c, cells[0], cells[1]])
    add_table(s, 0.4, 2.4, [1.3, 2.55, 1.45, 1.75, 2.74, 2.74], rows, [0.3] + [0.72] * nrow, fills=[None] * nrow, size=8.2,
              aligns=["l", "l", "c", "c", "l", "l"])
    y = 2.4 + 0.3 + 0.72 * nrow + 0.12
    con = _conclusion(dp)
    rect(s, 0.4, y, 12.53, 0.95, fill="F2F6FC", line="2F5597", line_w=1.0, shape=MSO_SHAPE.ROUNDED_RECTANGLE)
    tbox(s, 0.5, y + 0.03, 12.3, 0.9,
         [[("요약 (심사용)", {"bold": True, "color": NAVY, "size": 9.5})]] + [[("• " + x, {"size": 8.8})] for x in con],
         size=8.8, line_spacing=1.1)
    return s


def mapping_slide(prs):
    s = clone_chrome(prs, 5, "Trade-off 별 ↔ 평가 기준 구간 ↔ 이론 예상값",
                     "DP 후보별 소유자 별이 새 기준(B1 대비)의 어떤 수치 구간에 해당하는지, 이론 예상값은 어디에 놓이는지",
                     "예상값 = theory_model.py 분석 모델(시뮬레이션 아님). 붉은 글씨 = 예상값이 소유자 별 구간보다 낮음, 파란 글씨 = 같거나 높음. 기존 중립 벤치마크 시뮬 값은 qa-criteria-v4.md 참조")
    hdr = ["DP / 안", "Q1 처리량", "Q2 HBM", "Q3 고부하 지연", "Q4 확장성", "Q5 변경 용이성"]
    names = {("DP1", 1): "DP1 1안 상태 관측+이동 결정 통합", ("DP1", 2): "DP1 2안 관측·결정 분리",
             ("DP2", 1): "DP2 1안 스케줄링 시점 결정", ("DP2", 2): "DP2 2안 사전 계획 결정",
             ("DP3", 1): "DP3 1안 Pipe-and-Filter", ("DP3", 2): "DP3 2안 Shared Repository",
             ("DP4", 1): "DP4 1안 중앙 서버 중재", ("DP4", 2): "DP4 2안 락 기반 직접 접근"}
    rows = [hdr]
    for key in sorted(cd.OWNER):
        row = [[[(names[key], {"bold": True, "size": 8})]]]
        for q in ("Q1", "Q2", "Q3", "Q4", "Q5"):
            o = cd.OWNER[key].get(q)
            if o is None:
                row.append([[("—", {"color": "A6A6A6"})]])
                continue
            line1 = [(cd.fmt_star(o) + " → " + cd.BAND_SHORT[q][o], {"size": 8, "bold": True})]
            st = cd.theory_star(*key, q)
            line2 = [(cd.cell_text(*key, q) + " → " + cd.fmt_star(st), {"size": 7.2, "color": "2F5597" if st >= o else "C00000"})]
            row.append([line1, line2])
        rows.append(row)
    add_table(s, 0.4, 1.2, [2.2, 2.15, 2.15, 2.15, 1.95, 1.93], rows, [0.28] + [0.5] * 8, fills=[None] * 8, size=8, aligns=["l"] * 6)
    agree = []
    tot = hit = 0
    for key in cd.OWNER:
        for q, o in cd.OWNER[key].items():
            st = cd.theory_star(*key, q)
            if st is None:
                continue
            tot += 1
            if abs(st - o) <= 0.5:
                hit += 1
    tbox(s, 0.4, 5.6, 12.5, 1.5,
         [[("읽는 법", {"bold": True, "color": NAVY, "size": 10})],
          [("• 굵은 줄: 소유자 별과 그 별이 요구하는 새 기준 구간. 작은 줄: 이론 예상값(B1 → 후보)과 새 기준으로 환산한 별.", {"size": 9})],
          [("• 소유자 별과 ±0.5 이내로 맞는 칸: %d / %d. 후보 간 순위가 소유자 평가와 같은 곳: DP1 Q1~Q3, DP2 Q1·Q2·Q4, DP3 Q2." % (hit, tot), {"size": 9})],
          [("• 어긋나는 곳: DP2 Q3(소유자는 1안이 유리, 예상값은 2안이 유리: Re-plan 비용이 작음), DP3 Q1·Q3(두 안 거의 동일), DP4 Q1·Q3·Q4(두 안 동일, 소유자는 안 간 차이를 예상). 파라미터를 바꾸면 달라지는 값이며 가정은 방법 페이지에 적었다.", {"size": 9})]],
         size=9, line_spacing=1.12)
    return s


# ============================================================ main
def main():
    prs = Presentation(BASE)
    S = list(prs.slides)
    edit_requirements(S[0])
    for dp, idx in DP_SLIDE.items():
        annotate_dp(S[idx], dp)
    build_criteria_slides(prs)
    sc1, sc2 = scenario_slides(prs)
    base_s = baseline_slide(prs)
    meth_s = method_slide(prs)
    res = {dp: dp_result_slide(prs, dp) for dp in ("DP1", "DP2", "DP3", "DP4")}
    map_s = mapping_slide(prs)
    order = [S[0], S[1], res["DP1"], S[2], res["DP2"], S[3], res["DP3"], S[4], res["DP4"], base_s, meth_s,
             S[5], S[6], S[7], S[8], S[9], S[10], sc1, sc2, map_s]
    lst = prs.slides._sldIdLst
    ids = [sl.slide_id for sl in order]
    els = {int(e.get("id")): e for e in lst}
    for e in list(lst):
        lst.remove(e)
    for i in ids:
        lst.append(els[i])
    prs.save(OUT)
    print("saved", OUT, len(prs.slides), "slides")


if __name__ == "__main__":
    main()
