"""QA 평가 시나리오 장표 4장 생성 (평가 기준 장표와 같은 서식).
1) 공통 환경·워크로드·부하 규모  2) QA-01·02 동시 요청 부하  3) QA-03 확장성  4) QA-04·05
사용: python build_scenarios.py <in.pptx> <out.pptx>
가정값(모델 70B급 fp16, KV 320 KB/token, HBM 사용률 90%)은 코드 상단 상수이며 슬라이드에 가정으로 표기한다."""
import sys
from pptx import Presentation
from pptx.enum.shapes import MSO_SHAPE
from pptx.enum.text import MSO_ANCHOR, PP_ALIGN
from pptx.util import Inches

import build_deck as B
from build_deck import textbox, rect, line, table, new_slide, key_box, GRAY

TOTAL = 5
# ---- 가정 (사용자 확인: 70B급 fp16) -------------------------------------------------
W_GB, KV_PER_TOK, CTX, HBM_USE = 140, 327_680, 16_384, 0.9
SESS_GB = CTX * KV_PER_TOK / 1e9
cap = lambda hbm, extra: int((HBM_USE * hbm - W_GB + extra) / SESS_GB)
BASE = dict(hbm=cap(640, 0), dram=cap(640, 1024))                     # 8GPU 노드
TGT = dict(hbm=cap(320, 0), dram=cap(320, 1024), cxl=cap(320, 1024 + 2048))  # 4GPU+CXL 노드
GRID = [20, 40, 80, 160, 320, 640]


def where_base(n):
    return "HBM" if n <= BASE["hbm"] else "HBM+DRAM" if n <= BASE["dram"] else "SSD로 밀림"


def where_tgt(n):
    return "HBM" if n <= TGT["hbm"] else "DRAM까지" if n <= TGT["dram"] else "CXL까지" if n <= TGT["cxl"] else "SSD로 밀림"


def head(s, x, y, w, text, color="595959"):
    rect(s, x, y, w, 0.26, color)
    textbox(s, x + 0.05, y + 0.02, w - 0.1, 0.22, text, 10, True, "FFFFFF")


def footer(s, note, page):
    textbox(s, 0.27, 6.62, 12.83, 0.5, note, 7.5, False, GRAY)
    textbox(s, 5.85, 7.2, 1.6, 0.24, f"{page} / {TOTAL}", 10, False, GRAY, PP_ALIGN.CENTER)


L = [PP_ALIGN.CENTER, PP_ALIGN.LEFT]


# ------------------------------------------------------------------ 1. 공통 환경·워크로드
def slide1(prs, layout, nav):
    s = new_slide(prs, layout, nav, "QA 평가 시나리오 (1/5) - 평가 환경·부하 규모")
    key_box(s, "핵심", "평가 시나리오 = 어떤 워크로드를, 얼마나 많은 동시 세션으로, 얼마나 오래 넣고, 무엇을 재는가. "
                       "모든 QA가 같은 환경을 공유하고, 부하 규모는 '메모리 용량 대비 세션 수'와 'QPS 단계'로 정한다.", h=0.55)
    head(s, 0.27, 1.35, 6.3, "평가 시스템")
    rows = [["항목", "Baseline", "Target"],
            ["노드 수", "4노드", "1노드"],
            ["GPU / HBM", "H100 80GB × 8 / 640 GB", "H100 80GB × 4 / 320 GB"],
            ["DRAM", "1,024 GB", "1,024 GB"],
            ["CXL-PNM", "—", "512 GB × 4 = 2,048 GB"],
            ["SSD", "NVMe 16 TB", "NVMe 16 TB + PIM-SSD"],
            ["비용 / 노드", "$283K", "$242.7K"]]
    table(s, 0.27, 1.61, [1.2, 2.55, 2.55], rows, [0.26] + [0.29] * 6, 9, aligns=[PP_ALIGN.CENTER, PP_ALIGN.LEFT, PP_ALIGN.LEFT], header_bold=False,
          fills={(r, 0): "F2F2F2" for r in range(1, 7)})
    textbox(s, 0.27, 3.66, 6.3, 0.3, "모델: 70B급 fp16 (가중치 140 GB), KV 320 KB/token [가정]. Baseline은 HBM+DRAM 단순 offloading.", 8.5, False, "404040")

    head(s, 6.85, 1.35, 6.25, "시간·반복 규칙")
    textbox(s, 6.85, 1.64, 6.25, 2.3, [
        "• 워밍업 5분 (캐시 채움, 측정 제외)",
        "• QPS 시작점 = 예상 포화 QPS의 10%, 5분마다 +10%씩 증가 → SLO를 처음 깨는 단계에서 중단 (직전 단계 = Max Goodput)",
        "• 예상 포화 QPS는 짧은 탐색 실행으로 먼저 추정",
        "• 측정 구간: 단계당 5분 이상, 전체는 세션당 평균 8회 호출을 소화할 때까지",
        "• 시나리오 조합마다 5회 반복",
        "• 동시 in-flight 요청 = QPS × 체류시간 (예: 5 QPS × 4.2 s ≈ 21건). 정하는 값이 아니라 결과로 나온다"], 9, False, "404040")

    head(s, 0.27, 4.05, 6.3, f"동시 세션 수 격자 (16K 컨텍스트, {SESS_GB:.1f} GB/세션)")
    rows = [["세션 수", "Baseline 노드", "Target 노드"]] + [[str(n), where_base(n), where_tgt(n)] for n in GRID]
    table(s, 0.27, 4.31, [1.2, 2.55, 2.55], rows, [0.26] + [0.28] * 6, 9, aligns=[PP_ALIGN.CENTER, PP_ALIGN.CENTER, PP_ALIGN.CENTER], header_bold=False,
          fills={(r, 0): "F2F2F2" for r in range(1, 7)})
    textbox(s, 0.27, 6.3, 6.3, 0.3, f"수용 한계(세션): Baseline HBM {BASE['hbm']} / +DRAM {BASE['dram']}, Target HBM {TGT['hbm']} / +DRAM {TGT['dram']} / +CXL {TGT['cxl']}. "
                                   "양쪽에 같은 절대 세션 수를 넣는다.", 8, False, GRAY)

    head(s, 6.85, 4.05, 6.25, "QPS 단계 예시 (예상 포화 5 QPS인 경우)")
    steps = [f"{0.5 * i:g}" for i in range(1, 7)]
    rows = [["단계"] + [str(i) for i in range(1, 7)] + ["…"], ["QPS"] + steps + ["…"], ["누적 시간"] + [f"{5 * i}분" for i in range(1, 7)] + ["…"]]
    table(s, 6.85, 4.31, [0.95] + [0.7] * 6 + [0.45], rows, [0.3] * 3, 9, header=False, aligns=[PP_ALIGN.CENTER] * 8,
          fills={(r, 0): "F2F2F2" for r in range(3)}, bold_cols=(0,))
    textbox(s, 6.85, 5.3, 6.25, 0.9, ["• 단계마다 P99 TTFT·TPOT을 확인하고, SLO(TTFT ≤ 2 s, TPOT ≤ 50 ms)를 처음 넘는 단계에서 중단",
                                      "• 중단 직전 단계의 QPS를 Max Goodput으로 기록"], 9, False, "404040")
    footer(s, "가정: 모델 70B급 fp16, HBM 사용률 90%, 노드당 KV 용량 = 0.9×HBM − 가중치. 시스템 사양은 'Baseline vs Target 시스템' 장표 기준. 실제 모델·세션 크기가 다르면 격자를 다시 계산한다.", 1)


# ------------------------------------------------------------------ 1-2. 워크로드·KV 재사용 정의
def reuse_bars(s, x, y, total_w):
    items = [(100, "100%"), (90, "90%"), (50, "50%"), (0, "0%")]
    for i, (r, lab) in enumerate(items):
        yy = y + i * 0.42
        textbox(s, x, yy, 0.8, 0.3, f"재사용 {lab}", 9, True, "404040", anchor=MSO_ANCHOR.MIDDLE)
        bx = x + 0.9
        w1 = (total_w - 0.9) * r / 100
        w2 = (total_w - 0.9) - w1
        if w1 > 0:
            rect(s, bx, yy, w1, 0.3, "548235")
        if w2 > 0:
            rect(s, bx + w1, yy, w2, 0.3, "BFBFBF")
    lx = x + 0.9
    rect(s, lx, y + 1.74, 0.14, 0.12, "548235"); textbox(s, lx + 0.17, y + 1.68, 2.6, 0.22, "이전과 같은 앞부분 (KV 재사용 가능)", 8.5, False, "404040", wrap=False)
    rect(s, lx + 3.0, y + 1.74, 0.14, 0.12, "BFBFBF"); textbox(s, lx + 3.17, y + 1.68, 2.2, 0.22, "새 내용 (재계산 필요)", 8.5, False, "404040", wrap=False)


def slide_workload(prs, layout, nav):
    s = new_slide(prs, layout, nav, "QA 평가 시나리오 (2/5) - 워크로드와 KV 재사용 비율")
    key_box(s, "핵심", "워크로드는 컨텍스트 길이와 KV 재사용 비율을 skill로 통제하는 합성 워크로드다(실제 agent 행동을 그대로 재현한 것은 아님). "
                       "KV 재사용 비율은 '입력 중 이전과 같은 앞부분의 비율'로, Target이 지는 구간과 이기는 구간을 모두 보이기 위한 축이다.", h=0.6)
    head(s, 0.27, 1.4, 6.3, "워크로드 3종 (각각 개별 실행 + 혼합 실행)")
    rows = [["ID", "내용", "컨텍스트", "혼합 비율"],
            ["W-A", "짧은 챗 (대조군)", "4K", "20%"],
            ["W-B", "멀티턴 agent (주 시나리오)", "16K", "50%"],
            ["W-C", "긴 컨텍스트 agent·코딩", "32K", "30%"]]
    table(s, 0.27, 1.66, [0.55, 3.0, 1.35, 1.4], rows, [0.26] + [0.3] * 3, 9.5, aligns=[PP_ALIGN.CENTER, PP_ALIGN.LEFT, PP_ALIGN.CENTER, PP_ALIGN.CENTER],
          header_bold=False)
    textbox(s, 0.27, 2.9, 6.3, 0.4, "혼합 비율은 설계 가정: 타깃이 agent 중심이라 W-B를 주력으로, W-A는 재사용 이득이 작은 대조군으로 최소, W-C는 용량 압박을 보이는 용도로 30%.", 8.5, False, GRAY)
    head(s, 0.27, 3.5, 6.3, "생성 방식 (skill 기반 합성 워크로드)")
    textbox(s, 0.27, 3.8, 6.3, 2.7, [
        "• 컨텍스트 길이(4K/16K/32K)와 재사용 비율을 skill로 통제. 컨텍스트는 시나리오마다 고정(단순화)",
        "• 세션당 LLM 호출(에이전트 내부 루프) 평균 8회, 3~20 분포 [가정]",
        "• 호출 1건: 신규 입력 ≈ 1K, 출력 ≈ 128 token, tool 대기 1~5 s [가정]",
        "• 세션 호출 쏠림: Zipf(α=0.8) — 호출 빈도 순위가 높은 소수 세션이 더 자주 호출된다. agent가 보이는 특성을 부하 생성기가 흉내 내는 값이며, 실제 로그가 있으면 α를 보정 [가정]",
        "• 한계: 실제 agent의 컨텍스트 증가·편집 패턴은 반영하지 않음. opencode 실제 세션 로그로 길이 분포를 보정하면 신뢰도가 올라감"], 9.5, False, "404040")

    head(s, 6.85, 1.4, 6.25, "KV 재사용 비율 = 입력 중 이전과 같은 앞부분의 비율")
    reuse_bars(s, 6.9, 1.8, 6.1)
    textbox(s, 6.85, 3.85, 6.25, 2.7, [
        "• 앞부분이 같으면 KV를 재사용하고, 달라진 지점부터는 재계산한다",
        "• 100%: 대화 끝에 이어 붙이기만 하는 경우 (append)",
        "• 50·90%: 컨텍스트 요약·편집, 오래된 tool 결과의 제거·교체로 앞부분이 일부만 같아지는 경우",
        "• 0%: 매번 처음부터 계산 (full prefill) — Target이 지는 구간(0.49x)",
        "• 실제 hit은 이 상한 이하이며 캐시 용량에 따라 달라진다",
        "• 범위 밖: 다른 세션끼리 KV를 공유하는 재사용(공통 system prompt 등). 필요하면 별도 축으로 추가"], 9.5, False, "404040")
    footer(s, "재사용 비율 축의 근거: 'Baseline vs Target 시스템' 장표 분석값(Full prefill 0.49x, Full KV reuse 1.63x). 호출 횟수·입력 크기·Zipf α·혼합 비율은 모두 가정이며 실제 로그로 보정 가능.", 2)


# ------------------------------------------------------------------ 2. QA-01·02
def staircase(s, x, y, w, h):
    n = 6
    bw = w / n
    for i in range(n):
        hh = h * (0.25 + 0.14 * i)
        col = "C00000" if i == n - 1 else "2E75B6"
        rect(s, x + i * bw + 0.05, y + h - hh, bw - 0.1, hh, col)
    line(s, x, y + h, x + w, y + h, GRAY, 0.75)
    textbox(s, x, y + h + 0.02, w, 0.2, "QPS 단계적 증가 (5분/단계) →", 8, False, "404040", PP_ALIGN.CENTER)
    textbox(s, x + w - 2.4, y - 0.2, 2.4, 0.2, "SLO 위반 → 직전 단계 = Max Goodput", 8, True, "C00000", PP_ALIGN.RIGHT)


def flatline(s, x, y, w, h):
    line(s, x, y + h, x + w, y + h, GRAY, 0.75)
    line(s, x, y + 0.15, x + w, y + 0.15, GRAY, 1.0, dash=True)
    line(s, x, y + 0.15 + h * 0.3 * 1.0, x + w, y + 0.15 + h * 0.3 * 1.0, "C00000", 2.0)
    textbox(s, x, y - 0.06, w, 0.2, "포화 처리율 μ (SLO 무관, 먼저 측정)", 8, False, "404040")
    textbox(s, x, y + 0.15 + h * 0.3 + 0.03, w, 0.2, "고부하 시험 요청률 = 0.7μ (같은 절대 QPS를 Baseline·Target 모두에 적용)", 8, True, "C00000")
    textbox(s, x, y + h + 0.02, w, 0.2, "측정 구간 10~15분 (워밍업 5분 제외)", 8, False, "404040", PP_ALIGN.CENTER)


def slide2(prs, layout, nav):
    s = new_slide(prs, layout, nav, "QA-01·02 평가 시나리오 (3/5) - 동시 요청 부하")
    key_box(s, "핵심", "QA-01은 요청률을 올려 SLO 한계까지 밀어 최대 처리량(QPS)을 재고, QA-02는 포화 처리율의 70% 부하(고부하)를 고정해 꼬리 지연을 잰다. "
                       "둘 다 Target 1노드와 Baseline 8GPU 1노드를 같은 부하로 비교한다.", h=0.55)
    for x, t in ((0.27, "QA-01 처리량 (Max Goodput)"), (6.85, "QA-02 꼬리 지연 (P99)")):
        head(s, x, 1.35, 6.25 if x > 1 else 6.3, t)
    rows = [["비교", "Target 노드 vs Baseline 8GPU 노드 (노드 단위), 같은 부하"],
            ["워크로드", "W-A/B/C 개별 + 혼합(20/50/30) × 세션 수 20~640(6단계) × KV 재사용 0/50/90/100%"],
            ["부하", "Poisson 도착, 시작 = 예상 포화 QPS의 10%, 5분마다 +10%, SLO 위반 직전까지"],
            ["SLO", "P99 TTFT ≤ 2 s, TPOT ≤ 50 ms"],
            ["측정", "SLO 만족 최대 QPS(Goodput), R = Target ÷ Baseline의 기하평균"],
            ["보조", "Target에서 CXL을 끈 4GPU 구성(CXL 효과만 분리), 5회 반복"]]
    table(s, 0.27, 1.61, [0.9, 5.4], rows, [0.4] * 6, 9, header=False, aligns=L, fills={(r, 0): "F2F2F2" for r in range(6)}, bold_cols=(0,))
    staircase(s, 0.8, 4.75, 5.4, 1.3)
    rows = [["비교", "QA-01과 같음. 같은 절대 QPS에서 후보 vs Baseline"],
            ["워크로드", "W-B/C, 세션 160/320/640, KV 재사용 90/100%"],
            ["부하", "Baseline 포화 처리율 μ를 먼저 측정 → 요청률을 0.5μ / 0.7μ / 0.9μ로 각각 고정해 비교 (고부하 기준 70%의 민감도 확인)"],
            ["SLO", "후보가 SLO를 만족하는 조건에서만 판정"],
            ["측정", "P99 Elapsed Time(E2E)·TTFT 감소율 r = 1 − P99(후보)/P99(Baseline)"],
            ["반복", "구간 10~15분, 5회 반복. 고부하 근거는 'QA-02 보충' 장표"]]
    table(s, 6.85, 1.61, [0.9, 5.35], rows, [0.4] * 6, 9, header=False, aligns=L, fills={(r, 0): "F2F2F2" for r in range(6)}, bold_cols=(0,))
    flatline(s, 7.0, 4.75, 5.9, 1.3)
    footer(s, "KV 재사용 비율·워크로드 정의는 2/5 장표 참조. 조합이 많으면 재사용 비율을 0/90/100%로 줄일 수 있다.", 3)


# ------------------------------------------------------------------ 3. QA-03
def box(s, x, y, w, h, title, lines, color):
    head(s, x, y, w, title, color)
    rect(s, x, y + 0.26, w, h - 0.26, "FFFFFF", "BFBFBF", line_w=0.6)
    textbox(s, x + 0.06, y + 0.3, w - 0.12, h - 0.34, lines, 9, False, "404040")


def slide3(prs, layout, nav):
    s = new_slide(prs, layout, nav, "QA-03 평가 시나리오 (4/5) - 확장성")
    key_box(s, "핵심", "Target은 1노드뿐이라 노드 간 확장을 직접 잴 수 없다. 노드 안 확장(Target)과 노드 간 확장(Baseline 4노드)을 따로 재서 "
                       "조율 직렬 비중 σ로 합치고, 16노드 SE는 외삽한다 [C].", h=0.55)
    w = 3.85
    box(s, 0.27, 1.4, w, 1.75, "① 노드 안 확장 — Target 1노드", [
        "• 활성 GPU를 1 → 2 → 4개로 증가",
        "• 부하(요청률)를 GPU 수에 비례해 증가",
        "• CXL-PNM 4카드는 GPU들이 공유",
        "• 얻는 값: σ_intra (CXL 공유 경합)"], "2E75B6")
    box(s, 4.74, 1.4, w, 1.75, "② 노드 간 확장 — Baseline 4노드", [
        "• 같은 조율 SW(router·전역 metadata)를 DRAM 계층만으로 구동",
        "• 노드를 1 → 2 → 3 → 4로 증가, 노드당 GPU 4개만 사용(Target과 맞춤)",
        "• 얻는 값: σ_inter, 요청당 조율 시간 t_coord(ms)"], "2E75B6")
    box(s, 9.21, 1.4, w, 1.75, "③ 합성 → 16노드 외삽 [C]", [
        "• σ_target ≈ σ_intra + t_coord ÷ t_service",
        "  (t_service = Target 노드의 요청 처리 시간)",
        "• SE(16) = 1 / (1 + 15σ)",
        "• 별 판정은 σ(와 신뢰구간)로 한다"], "C00000")
    for xa in (4.17, 8.62):
        a = s.shapes.add_shape(MSO_SHAPE.RIGHT_ARROW, Inches(xa), Inches(2.0), Inches(0.52), Inches(0.35))
        a.fill.solid(); a.fill.fore_color.rgb = B.rgb("7F7F7F"); a.line.fill.background(); a.shadow.inherit = False

    head(s, 0.27, 3.4, 6.3, "별 기준과 σ (N0=1 정의, 제안)")
    sg = lambda se: (1 / (se / 100) - 1) / 15 * 100
    rows = [["별", "SE(16)", "σ 상한"]] + [[n, f"> {v:g}%", f"{sg(v):.2f}%"] for n, v in (("★", 90), ("★★", 92.5), ("★★★", 95))]
    table(s, 0.27, 3.66, [1.5, 2.4, 2.4], rows, [0.26] + [0.3] * 3, 9, aligns=[PP_ALIGN.CENTER] * 3, header_bold=False,
          fills={(1, 0): B.STAR_FILL[1], (2, 0): B.STAR_FILL[3], (3, 0): B.STAR_FILL[5]})
    textbox(s, 0.27, 4.95, 6.3, 1.0, [
        "• Baseline 4노드는 독립 replica라 σ≈0(SE≈100%)이 기대된다 → 측정 방법 검증용으로 실측해 본다",
        "• 반복 측정으로 σ의 신뢰구간을 내고, 별 경계에 걸치면 '경계 걸침'으로 표기"], 9, False, "404040")
    head(s, 6.85, 3.4, 6.25, "한계·확인 필요", "7F7F7F")
    textbox(s, 6.85, 3.7, 6.25, 2.5, [
        "• Baseline 노드에는 CXL이 없어 노드 간 공유 tier 경합은 평가하지 못함",
        "• σ를 더하는 합성은 근사이고, Baseline 노드는 하드웨어가 달라 비율값만 가져옴",
        "• 노드 간 공유 경합(κ)을 무시한 값이라 실제 SE(16)은 더 낮을 수 있음",
        "• 확인 필요: ① 노드 간 네트워크 ② 조율 SW를 DRAM만으로 구동 가능한지 ③ N0=1 정의 동의",
        "• Target이 노드 간 KV를 옮기거나 공유하면 그 전송 비용도 σ에 더한다"], 9, False, "404040")
    footer(s, "SE(N) = 1/(1+σ(N−1)) (USL, N0=1). 기존 장표의 N0=2 정의 대신 Target 1노드 제약에 맞춘 제안이며, σ 상한은 ★ 0.74% / ★★★ 0.35%.", 4)


# ------------------------------------------------------------------ 4. QA-04·05
def slide4(prs, layout, nav):
    s = new_slide(prs, layout, nav, "QA-04·05 평가 시나리오 (5/5) - 변경 용이성·정확성")
    key_box(s, "핵심", "QA-04는 변경 5건을 실제로 구현해 바뀐 소스 파일 수를 세고, QA-05는 KV 재사용 경로를 강제로 타게 한 뒤 "
                       "full recompute와 F1을 문항별로 비교한다.", h=0.55)
    head(s, 0.27, 1.35, 6.3, "QA-04 변경 용이성 — 변경 시나리오 5건")
    rows = [["ID", "변경 내용", "예"],
            ["S1", "신규 메모리 tier 추가", "CXL → HBF / ScHBM"],
            ["S2", "이동·배치 정책 교체", "LRU → hotness 예측"],
            ["S3", "신규 data type 추가", "LoRA·MoE expert·RAG 캐시"],
            ["S4", "신규 이벤트 추가", "tool-call 종료 시 prefetch"],
            ["S5", "신규 KV 코덱 추가", "압축·양자화"]]
    table(s, 0.27, 1.61, [0.55, 2.7, 3.05], rows, [0.26] + [0.4] * 5, 10.5, aligns=[PP_ALIGN.CENTER, PP_ALIGN.LEFT, PP_ALIGN.LEFT], header_bold=False)
    textbox(s, 0.27, 4.05, 6.3, 2.5, [
        "• 각 변경을 현행 vLLM과 제안 구조에서 각각 구현",
        "• 측정: 수정·추가·삭제된 소스 파일 수 (테스트·문서 제외)",
        "• 판정: 5건 평균 ≤ 6개 (★), ≤ 2개 (★★★) — vLLM commit 분포 기준",
        "• 조건: 기존 unit test 통과(회귀 없음), 서빙 경로 핵심 코드(scheduler·worker) 수정 최소",
        "• 구현자·구현 도구와 소요 시간도 함께 기록 (참고)"], 10.5, False, "404040")

    head(s, 6.85, 1.35, 6.25, "QA-05 정확성 — F1 비교")
    rows = [["항목", "내용"],
            ["데이터", "멀티턴 QA 데이터셋, 500문항 이상 (가정)"],
            ["실행", "2-pass: 1회차에 KV 캐시를 채우고, 2회차에 재사용 경로를 강제"],
            ["비교", "재사용 경로 vs full recompute, 같은 모델·precision, greedy, 고정 seed"],
            ["판정", "문항별 paired bootstrap, F1 하락률 95% CI 상한 < 1% (★), < 0.1% (★★★)"],
            ["추가 검사", "tier 왕복 복사 후 KV 비트 일치(bit-exact) 확인"]]
    table(s, 6.85, 1.61, [1.05, 5.2], rows, [0.26] + [0.4] * 5, 10.5, aligns=[PP_ALIGN.CENTER, PP_ALIGN.LEFT], header_bold=False,
          fills={(r, 0): "F2F2F2" for r in range(1, 6)})
    textbox(s, 6.85, 4.3, 6.25, 1.6, [
        "• 본 시스템은 압축을 쓰지 않으므로 이동·복원·재사용 경로만 대상",
        "• 재사용 경로가 다른 kernel·chunk 경계를 타면 비트 차이가 생길 수 있어 F1로 확인",
        "• 0.1%는 문항 수가 부족하면 입증이 어려움 → 문항 수를 늘리거나 기준 재검토"], 10.5, False, "404040")
    footer(s, "QA-04 구현 측정은 아직 수행하지 않았다(계획). QA-05 데이터셋 크기와 종류는 가정이며 확정이 필요하다.", 5)


def main(src, dst):
    prs = Presentation(src)
    tmpl = prs.slides[1]
    layout = tmpl.slide_layout
    names = {sh.name: sh for sh in tmpl.shapes}
    nav = [names[n] for n in ("Chevron 2", "Chevron 3", "Chevron 4", "Chevron 5", "Chevron 6", "Rectangle 7", "Rectangle 8")]
    n_old = len(prs.slides)
    for f in (slide1, slide_workload, slide2, slide3, slide4):
        f(prs, layout, nav)
    lst = prs.slides._sldIdLst
    for sldId in list(lst)[:n_old]:
        prs.part.drop_rel(sldId.rId)
        lst.remove(sldId)
    prs.save(dst)


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
