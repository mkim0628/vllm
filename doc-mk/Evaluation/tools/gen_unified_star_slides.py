#!/usr/bin/env python3
"""Update the all-DP overview deck with the unified star criteria (v2).

    python doc-mk/Evaluation/tools/gen_unified_star_slides.py IN.pptx OUT.pptx

Edits (text only, cell formats cloned from the deck itself):
  * DP2 slide: fills the Tradeoff stars/values (from DP2 results 2026-10-06, same rules as DP1/DP4).
  * DP3 slide: marks the Tradeoff cells "미평가 (TBD)" (no evaluation data exists).
  * DP1/DP4 slides: QA4 line shows (토큰 비용, M/M, 모듈 수) with unified basis (mid tier USD, man-month); stars unchanged.
  * inserts the unified-criteria appendix section after the "Appendix" divider; banners on superseded per-DP criteria slides.
Stars and sums come from tools/unified_stars.py (no hand-typed stars).
"""
from __future__ import annotations

import copy
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import unified_stars as U  # noqa: E402

from lxml import etree  # noqa: E402
from pptx import Presentation  # noqa: E402
from pptx.dml.color import RGBColor  # noqa: E402
from pptx.enum.shapes import MSO_SHAPE  # noqa: E402
from pptx.enum.text import MSO_ANCHOR, PP_ALIGN  # noqa: E402
from pptx.oxml.ns import qn  # noqa: E402
from pptx.util import Emu, Inches, Pt  # noqa: E402

FONT = "맑은 고딕"
NAVY, GREY, RED = "2F5597", "404040", "C00000"
FILL = {3: "E2EFDA", 2: "FFF2CC", 1: "FBE5D6"}
rgb = RGBColor.from_string


def S(n):
    return "★" * n + "☆" * (3 - n)


# ------------------------------------------------------------------ cell helpers on existing slides
def _runs_fill(p, star, text, color=None):
    """Rewrite paragraph p to: star run + ' ' + text run (clone first run's formatting)."""
    runs = p.findall(qn("a:r"))
    for r in runs[1:]:
        p.remove(r)
    r0 = runs[0]
    r0.find(qn("a:t")).text = star
    rsp = copy.deepcopy(r0)
    rsp.find(qn("a:t")).text = " "
    rt = copy.deepcopy(r0)
    rt.find(qn("a:t")).text = text
    for r in (rsp, rt):
        sf = r.find(qn("a:rPr")).find(qn("a:solidFill"))
        if sf is not None and sf.find(qn("a:srgbClr")) is not None:
            sf.find(qn("a:srgbClr")).set("val", "1A1A1A")
    if color:
        for r in (r0, rt):
            sf = r.find(qn("a:rPr")).find(qn("a:solidFill"))
            sf.find(qn("a:srgbClr")).set("val", color)
    p.insert(list(p).index(r0) + 1, rsp)
    p.insert(list(p).index(rsp) + 1, rt)


def fill_value_cell(cell, template_p, lines):
    """lines: [(star_text, value_text, color or None)]"""
    txb = cell._tc.txBody
    for p in txb.findall(qn("a:p")):
        txb.remove(p)
    for star, text, color in lines:
        p = copy.deepcopy(template_p)
        _runs_fill(p, star, text, color)
        txb.append(p)


def tradeoff_table(slide):
    for sh in slide.shapes:
        if sh.has_table:
            return sh.table
    raise KeyError


def set_run_text(para, idx, text):
    para.runs[idx].text = text


# ------------------------------------------------------------------ new slides (style cloned from the deck's own appendix slides)
class Builder:
    def __init__(self, prs, layout):
        self.prs, self.layout = prs, layout

    def tb(self, s, x, y, w, h, paras, size=9, anchor=MSO_ANCHOR.TOP, name=None):
        """paras: list of (text, dict(bold,color,size)) or str"""
        b = s.shapes.add_textbox(Inches(x), Inches(y), Inches(w), Inches(h))
        if name:
            b.name = name
        tf = b.text_frame
        tf.word_wrap = True
        tf.margin_left = tf.margin_right = Emu(73152)
        tf.margin_top = tf.margin_bottom = Emu(36576)
        tf.vertical_anchor = anchor
        for i, pr in enumerate(paras):
            text, o = (pr, {}) if isinstance(pr, str) else pr
            p = tf.paragraphs[0] if i == 0 else tf.add_paragraph()
            p.alignment = PP_ALIGN.LEFT
            p.space_after = Pt(2.5)
            r = p.add_run()
            r.text = text
            r.font.size = Pt(o.get("size", size))
            r.font.bold = o.get("bold", False)
            r.font.name = FONT
            r.font.color.rgb = rgb(o.get("color", "000000"))
            ea = etree.SubElement(r._r.get_or_add_rPr(), qn("a:ea"))
            ea.set("typeface", FONT)
        return b

    def frame(self, title, subtitle, footnote=None, src=None):
        s = self.prs.slides.add_slide(self.layout)
        for sh in list(s.placeholders):
            sh._element.getparent().remove(sh._element)
        self.tb(s, 0.4, 0.22, 12.5, 0.5, [(title, dict(bold=True, color=NAVY, size=22))], name="title", anchor=MSO_ANCHOR.MIDDLE)
        self.tb(s, 0.4, 0.74, 12.5, 0.35, [(subtitle, dict(color=GREY, size=11))], name="subtitle")
        r = s.shapes.add_shape(MSO_SHAPE.RECTANGLE, Inches(0.4), Inches(1.1), Inches(12.53), Inches(0.03))
        r.name = "rule"
        r.fill.solid(); r.fill.fore_color.rgb = rgb(NAVY); r.line.fill.background(); r.shadow.inherit = False
        if footnote:
            self.tb(s, 0.4, 7.0, 12.5, 0.3, [(footnote, dict(color=GREY, size=8.5))], name="footnote")
        if src:
            self.tb(s, 0.4, 7.2, 12.5, 0.25, [(src, dict(color=GREY, size=7.5))], name="src")
        return s

    def table(self, s, x, y, widths, rows, header=True, size=9.5, row_h=0.3, fills=None, bold_first_col=False, align=None, head_h=0.34):
        n, m = len(rows), len(widths)
        gf = s.shapes.add_table(n, m, Inches(x), Inches(y), Inches(sum(widths)), Inches(row_h * n))
        gf.name = "tbl"
        t = gf.table
        tblPr = t._tbl.tblPr
        for k in ("firstRow", "bandRow"):
            tblPr.set(k, "0")
        for j, w in enumerate(widths):
            t.columns[j].width = Inches(w)
        for i in range(n):
            t.rows[i].height = Inches(head_h if (header and i == 0) else row_h)
            for j in range(m):
                cell = t.cell(i, j)
                txt = rows[i][j]
                cell.margin_left = cell.margin_right = Emu(54864)
                cell.margin_top = cell.margin_bottom = Emu(22860)
                cell.vertical_anchor = MSO_ANCHOR.MIDDLE
                tf = cell.text_frame
                tf.word_wrap = True
                lines = txt if isinstance(txt, list) else [txt]
                for k, ln in enumerate(lines):
                    p = tf.paragraphs[0] if k == 0 else tf.add_paragraph()
                    p.alignment = PP_ALIGN.CENTER if (header and i == 0) or (align and align[j] == "c") else PP_ALIGN.LEFT
                    r = p.add_run()
                    r.text = ln
                    r.font.size = Pt(size)
                    r.font.name = FONT
                    r.font.bold = bool(header and i == 0) or (bold_first_col and j == 0)
                    r.font.color.rgb = rgb("FFFFFF" if header and i == 0 else "000000")
                    ea = etree.SubElement(r._r.get_or_add_rPr(), qn("a:ea"))
                    ea.set("typeface", FONT)
                color = NAVY if (header and i == 0) else (fills[i][j] if fills and fills.get(i) and fills[i][j] else "FFFFFF")
                cell.fill.solid(); cell.fill.fore_color.rgb = rgb(color)
                tcPr = cell._tc.get_or_add_tcPr()
                for q, tag in enumerate(("a:lnL", "a:lnR", "a:lnT", "a:lnB")):
                    ln = etree.Element(qn(tag), w="6350", cap="flat", cmpd="sng", algn="ctr")
                    sf = etree.SubElement(ln, qn("a:solidFill"))
                    etree.SubElement(sf, qn("a:srgbClr")).set("val", "BFBFBF")
                    etree.SubElement(ln, qn("a:prstDash")).set("val", "solid")
                    tcPr.insert(q, ln)
        return t

    def stars_table(self, s, rows, widths=(1.0, 2.6, 6.6, 2.33), y=1.4, size=10):
        data = [["별", "성능 기준 (정량)", "왜 이 값인가 (정량 근거)", "출처 · 확인 수준"]] + rows
        fills = {i + 1: [FILL[3 - i]] * 4 for i in range(3)}
        return self.table(s, 0.4, y, list(widths), data, size=size, row_h=0.72, fills=fills, align=["c", "l", "l", "l"])

    def blocks(self, s, left, right, y, h, lt="지표와 이전 기준", rt="정직한 주의", lw=6.12, size=10):
        self.tb(s, 0.4, y, lw, h, [(lt, dict(bold=True, color=NAVY, size=size + 1))] + [("• " + t, dict(size=size)) for t in left], name="l")
        self.tb(s, 6.78, y, 6.12, h, [(rt, dict(bold=True, color=RED, size=size + 1))] + [("• " + t, dict(size=size)) for t in right], name="r")


def build_slides(prs, res, inp):
    layout = [l for l in prs.slide_layouts if l.name == "빈 화면"][0]
    B = Builder(prs, layout)
    new = []
    sm = json.load(open(U.EVAL / "DP3" / "results" / "data" / "dp3_summary.json"))
    ag = sm["aggregate"]
    D3 = inp["DP3"]
    q5ok = "QA5" in res["DP3"]["C1"]

    def add(s):
        new.append(s)
        return s

    # ---------------------------------------------------------------- overview (12p)
    s = B.frame("공통 별 기준 v2 — 모든 DP에 같은 QA는 같은 기준", "QA마다 metric 계산식 → ★ 기준 → 근거 · QA1 ★★★ 2배 · QA2 절대 SLO + Baseline 대비 개선 · QA4 점수식 · proposal (소유자 확정 전)",
                "※ 근거 문서: doc-mk/Evaluation/qa-star-criteria-unified.md · 별 계산: tools/unified_stars.py (값과 출처는 tools/unified_inputs.json) · 평가 수치는 경계에 맞춰 바꾸지 않는다")
    rows = [["QA", "metric (같은 DP의 Baseline 대비 또는 절대 SLO)", "★★★", "★★", "★", "적용 DP"],
            ["QA1 처리량", "R = Max SLO goodput ÷ Baseline (쌍별 기하평균)", "R ≥ 2.0", "0.97 ≤ R < 2.0", "R < 0.97", "DP1 · DP2 · DP4"],
            ["QA2 지연", ["별 = 올림((A + R) / 2)", "A = 절대 SLO 등급: ★★★ TTFT P99 ≤ 2 s 그리고 TPOT P99 ≤ 50 ms, ★★ ≤ 4 s 그리고 ≤ 100 ms", "R = 개선 등급: r = √(TTFT 배수 × TPOT 배수), ★★★ r ≥ 1.20, ★★ 0.90 ≤ r < 1.20"], "(A+R)/2 ≥ 2.5", "1.5 ≤ (A+R)/2 < 2.5", "< 1.5", "DP1 ~ DP4"],
            ["QA3 자원", "HBM에 올라간 Context KV의 시간 평균 GiB → 감소 배수 = Baseline ÷ 후보", "≥ 1.25", "0.95 ≤ 배수 < 1.25", "< 0.95", "DP1 · DP3"],
            ["QA4 변경 용이성", ["S = 0.5 × (비용 ÷ $0.5) + 0.3 × (공수 ÷ 0.5 MM) + 0.2 × (module 수 ÷ 2)", "낮을수록 좋음 · 비용 = mid tier $/변경 · 가중 = 토큰 비용 > 공수 > module"], "S ≤ 1.0", "1.0 < S ≤ 3.2", "S > 3.2", "DP1 · DP2 · DP4"],
            ["QA5 기능 정확성", "F1 상대 하락 (압축 전 + full recompute 대비)", "≤ 1%", "≤ 3% (제안)", "> 3%", "DP3"],
            ["QA6 확장성", "SE(N_max=16) = Goodput(N) ÷ ((N/N0) × Goodput(N0)), N0=2", "≥ 90%", "70 ~ 90%", "< 70%", "DP4"]]
    fills = {i: ["EAF0FA", None, "E2EFDA", "FFF2CC", "FBE5D6", None] for i in range(1, 7)}
    t = B.table(s, 0.4, 1.3, [1.35, 5.0, 1.55, 1.75, 1.2, 1.68], rows, size=9, row_h=0.46, fills=fills, bold_first_col=True)
    for i, h in ((2, 1.0), (4, 0.68)):
        t.rows[i].height = Inches(h)
    B.blocks(s, ["같은 QA는 DP와 무관하게 같은 metric·집계·경계를 쓴다. DP마다 다른 것은 후보와 시나리오(공통 + DP 전용)뿐이다.",
                 "경계마다 근거를 달았다: 측정(잡음 폭), 환산(자원·시간), 표준·문헌, 정책 선택을 구분해 적었다.",
                 "QA4의 세 지표는 같은 비중이 아니다: 같은 '경계 대비 2배'라도 비용은 S에 +0.5, 공수 +0.3, module +0.2를 더한다. 한 지표가 나쁘면 다른 지표가 보완할 수 있다.",
                 "별 합계가 높은 후보를 선택하고 동점일 때만 QA 우선순위를 쓴다(모든 DP 공통)."],
             ["QA1 ★★★ = 2.0은 '같은 수요를 절반의 서버로'라는 자원 환산 단위다. 경계를 올렸으므로 별이 내려갔다(DP1 C2, DP2 두 후보 ★★★ → ★★). 평가 수치는 그대로다.",
              "QA2 R 경계(1.20/0.90)와 QA4 S 경계는 '기존 DP1·DP4 별과 선택을 보존한다'는 제약 안에서 정했다(defined_after_first_look).",
              "QA5의 두 번째 경계(3%)는 데이터로 도출하지 못한 제안값이다.",
              "시뮬레이션 [B+C]와 Baseline 실측 + 시뮬레이션 [A+C]를 같은 표에 쓴다. 근거 수준은 별과 분리해 표기한다."],
             y=5.25, h=1.75, lt="원칙", rt="정직한 주의", size=9)
    add(s)

    def crit(title, subtitle, rows, left, right, foot, src, lt="지표와 이전 기준"):
        s = B.frame(title, subtitle, foot, src)
        B.stars_table(s, rows)
        B.blocks(s, left, right, 4.2, 2.8, lt=lt, size=10.5)
        add(s)

    # ---------------------------------------------------------------- QA1
    crit("QA1 처리량 — 공통 별 기준", "R = Max SLO goodput(output tok/s) ÷ 같은 DP Baseline · 시나리오 쌍별 비율의 기하평균 · SLO = TTFT P99 ≤ 2 s, TPOT P99 ≤ 50 ms",
         [["★★★", "R ≥ 2.0", "같은 수요를 절반의 서버로 처리 = 노드 수·전력·비용이 절반이라는 가장 단순한 자원 환산 단위. 새 메모리 HW와 스케줄링 복잡도를 정당화하려면 '서버 한 대로 두 대분'은 되어야 한다. 서빙 시스템 수준 개선이 2배를 넘는 사례를 주요 성과로 보고한다(vLLM PagedAttention 2~4배, SOSP 2023)", "환산 [C] + 문헌 [B], 정책 선택"],
          ["★★", "0.97 ≤ R < 2.0", "하한 0.97 = Baseline끼리 seed 묶음을 바꿔 비교한 20회 집계 범위 0.968~1.033의 아래 끝. 그 안은 잡음이라 열세로 보지 않는다", "측정 [B+C], DP1 star_basis.py"],
          ["★", "R < 0.97", "잡음 대역 밖의 열세: Baseline보다 느리다", "측정 [B+C]"]],
         ["이전(v1): 1.30 — '자원 23% 절감'이라는 정책 선택이었고 DP1 결과(×1.298, ×1.423)를 본 뒤 그 사이에 놓아 '왜 1.30인가'에 답하지 못했다.",
          "평가 수치는 경계에 맞춰 키우지 않았다(측정값 조작 금지). 경계를 올렸으므로 별이 내려간다: DP1 C2 ×1.423, DP2 ×1.66 모두 ★★★ → ★★. QA1 ★★★ 후보는 없다.",
          "결과: DP1 C1 ×1.298 · C2 ×1.423, DP2 ×1.66 · ×1.66, DP4 ×1.05 · ×1.04 (모두 ★★)."],
         ["DP1 보완 버전(C1 + Affinity)은 436 ÷ 336 = ×1.2976이다. '×1.3'으로 반올림해 적었지만 판정 값은 소수 값이고 v1 경계 1.30에서도 0.2% 아래라 ★★였다. 문서와 PPT에는 ×1.298로 쓴다.",
          "2.0에서는 QA1이 이번 후보들을 가르지 못한다(×1.30 대 ×1.66이 별에 안 보임). 차이는 R 값으로 병기한다.",
          "DP4는 Baseline이 실측이지만 재측정 잡음 폭을 아직 재지 않았다. 0.97은 시뮬레이터의 잡음 폭이다."],
         "※ 공통 별점(0.90/1.10)은 필요하면 병기한다. 다른 기준 계열의 영향은 qa-star-criteria-unified.md §7.",
         "출처: DP1/qa-criteria-dp1.md §A·§J · DP1/sim/star_basis.py · vLLM PagedAttention (arXiv 2309.06180) · tools/unified_stars.py")

    # ---------------------------------------------------------------- QA2
    s = B.frame("QA2 지연 — 공통 별 기준", "별 = 올림((A + R) / 2) · A = 절대 SLO 등급(유지) · R = Baseline 대비 개선 등급(추가) · TTFT P99·TPOT P99의 시나리오 쌍별 기하평균",
                "※ 출처 링크는 PPT DP4 28장·34장과 같다. MLPerf 표준 값은 2차 자료 확인이 필요하다.",
                "출처: 공통 QA 문서 §5 · MLPerf Inference v5.1 요약(marktechpost, it-online) [2차] · Brysbaert 2019 · DP3 시뮬레이션 seed 분산 · tools/unified_stars.py")
    tA = [["A 절대 SLO", "기준 (두 지표 중 낮은 등급)", "근거"],
          ["★★★", "TTFT P99 ≤ 2 s 그리고 TPOT P99 ≤ 50 ms", "공통 기본 SLO. 8K prefill 이론 0.32 s의 약 6배(큐잉 여유), MLPerf 표준과 같은 자릿수. 50 ms = 20 tok/s는 묵독 속도의 약 3.5배"],
          ["★★", "≤ 4 s 그리고 ≤ 100 ms", "기본 SLO의 2배 이내 = 느리지만 대화형 가능한 한계 (정책 환산)"],
          ["★", "그 밖", "대화형 사용 한계 초과"]]
    B.table(s, 0.4, 1.3, [1.1, 3.1, 4.0], tA, size=9, row_h=0.5, fills={1: [FILL[3]] * 3, 2: [FILL[2]] * 3, 3: [FILL[1]] * 3}, align=["c", "l", "l"])
    tR = [["R 개선 (r)", "기준", "근거"],
          ["★★★", "r ≥ 1.20", "잡음 폭(±10%)의 2배 = 확실한 개선 (정책 선택)"],
          ["★★", "0.90 ≤ r < 1.20", "잡음 안 = Baseline과 동등. 단일 시나리오 P99 비율은 5 seed에서 ±15% 흔들리고 30여 쌍 평균은 약 ±3% (DP3 64개 비교의 CI 반폭 중앙값 14.7%)"],
          ["★", "r < 0.90", "잡음 밖의 열세 (Baseline보다 10% 넘게 나쁨)"]]
    B.table(s, 0.4, 3.45, [1.1, 3.1, 4.0], tR, size=9, row_h=0.5, fills={1: [FILL[3]] * 3, 2: [FILL[2]] * 3, 3: [FILL[1]] * 3}, align=["c", "l", "l"])
    B.tb(s, 0.4, 5.5, 8.2, 0.3, [("r = √[ (Baseline TTFT P99 ÷ 후보 TTFT P99) × (Baseline TPOT P99 ÷ 후보 TPOT P99) ]  (> 1이면 좋아짐)", dict(bold=True, color=NAVY, size=10))], name="r_formula")
    mx = [["별", "R ★★★", "R ★★", "R ★"],
          ["A ★★★", "★★★", "★★★", "★★"],
          ["A ★★", "★★★", "★★", "★★"],
          ["A ★", "★★", "★★", "★"]]
    mf = {1: [None, FILL[3], FILL[3], FILL[2]], 2: [None, FILL[3], FILL[2], FILL[2]], 3: [None, FILL[2], FILL[2], FILL[1]]}
    B.table(s, 8.8, 1.3, [1.0, 1.05, 1.05, 1.05], mx, size=10, row_h=0.42, fills=mf, align=["c", "c", "c", "c"], bold_first_col=True)
    rows = [["후보", "r", "A / R", "QA2"]]
    for dp, c, lab in (("DP1", "C1", "DP1 C1"), ("DP1", "C2", "DP1 C2"), ("DP1-1안", "C1", "DP1 1안"), ("DP2", "C1", "DP2 C1"), ("DP4", "C1", "DP4 후보1"), ("DP4", "C2", "DP4 후보2"), ("DP3", "C1", "DP3 C1"), ("DP3", "C2", "DP3 C2")):
        v = inp[dp]["values"][c]
        r = U.qa2_ratio(inp[dp], v)
        rows.append([lab, f"{r:.2f}", f"{U.qa2_abs(v['ttft_p99_ms'], v['tpot_p99_ms'])} / {U.qa2_imp(r)}", S(res[dp][c]["QA2"])])
    B.table(s, 8.8, 3.1, [1.2, 0.7, 0.9, 1.3], rows, size=9, row_h=0.28, align=["l", "c", "c", "c"])
    B.blocks(s, ["v1(절대 SLO만)은 Baseline보다 크게 나빠져도 SLO 안이면 ★★★이었다(DP1 1안: TTFT P99 ×1.27 나쁨). v2는 절대 수준(A)을 유지하면서 개선(R)을 같이 본다.",
                 "이전: DP4 절대 SLO, DP1·DP2 6개 지표 개선 배수 geomean(1.25/0.95). R은 P99 두 지표만 쓴다(DP4가 P99만 보고)."],
             ["R 경계 1.20/0.90은 '기존 DP1·DP4 별 보존' 제약 안의 구간에서 골랐다: DP4 후보1(r=1.11)을 ★★로 두려면 상한 > 1.11, DP1 C1(0.948)을 ★★로 두려면 하한 ≤ 0.948, 1안(0.862)을 ★로 내리려면 하한 > 0.862.",
              "DP1 C1은 r = 0.948이라 TTFT가 ×1.04 나쁜데도 ★★★이다(A ★★★ + R ★★ → 2.5 올림). 하한 0.90까지 +5%. 올림 규칙을 내림으로 바꾸면 DP4 후보2가 ★★★ → ★★로 바뀌어 선택이 뒤집힌다."],
             y=5.85, h=1.15, lt="왜 바꿨나", rt="정직한 주의", size=8.5)
    add(s)

    # ---------------------------------------------------------------- QA3
    crit("QA3 자원 (HBM 사용량) — 공통 별 기준", "HBM에 올라간 Context KV의 평균 크기(GiB)로 잰 감소 배수 = Baseline ÷ 후보 · 성능은 섞지 않는다 · DP1·DP3 적용",
         [["★★★", "감소 배수 ≥ 1.25", "HBM 점유 20% 감소 = DP1 평균 146.6 GiB 중 약 29 GiB(8K KV object 약 1.6개분). QA2와 같은 '눈에 띄는 개선' 크기로 둔 정책 선택", "환산 [C]"],
          ["★★", "0.95 ≤ 감소 배수 < 1.25", "하한 0.95: Baseline끼리 비교한 점유 잡음 범위 0.984~1.016보다 느슨하게 둠(5% 이내 증가는 열세로 보지 않음)", "측정 [B+C]"],
          ["★", "감소 배수 < 0.95", "HBM을 5% 넘게 더 쓴다(잡음 밖)", "측정 [B+C]"]],
         ["측정하는 것(쉬운 말): 모델이 돌아가는 동안 HBM에 올라와 있는 Context KV의 평균 크기. 측정 구간 동안 HBM의 KV 양을 계속 재서 시간으로 평균낸다(순간 최대 아님). 모델 가중치·활성값은 뺀다.",
          "예: 100초 중 40초는 100 GiB, 60초는 50 GiB → (40×100 + 60×50) ÷ 100 = 70 GiB. 감소 배수 3.0이면 HBM을 1/3만 쓴다.",
          "DP1: HBM tier의 KV object 크기 × 머문 시간 ÷ 구간 길이. DP3: 상주 Comp.KV 객체 + 요청 작업 사본의 같은 시간 평균.",
          "결과: DP1 C1 142.7 GiB(1.03, ★★) · C2 178.0(0.82, ★) · DP3 C1 30.3 GiB(3.53, ★★★) · C2 85.1(1.26, ★★★)."],
         ["DP3 C2의 1.26은 경계 1.25에서 +0.7%다. H100만 보면 1.34, B200만 보면 1.20이라 시스템 선택에 따라 ★★/★★★이 갈린다.",
          "DP1은 QA3 정의를 결과를 본 뒤 여러 번 바꿨다(활용률 → 풀 U → 성능÷비용 → HBM 사용량). 마지막 변경이 선택을 C2에서 C1로 바꿨다.",
          "'비우되 성능이 나빠지는 정책'이 유리하므로 QA1·QA2와 함께 읽어야 한다."],
         "※ 공통 룰의 활용률(65%/85%)은 필요하면 병기한다.",
         "출처: DP1/qa-criteria-dp1.md §A·§I·§J · DP1/sim/simulator.py(occ_bytes_sum) · DP3/sim/dp3sim.py · tools/unified_stars.py",
         lt="무엇을 재는가 (이전 기준 포함)")

    # ---------------------------------------------------------------- QA4
    s = B.frame("QA4 변경 용이성 — 공통 별 기준", "세 지표를 하나의 점수 S로 합친다 (낮을수록 좋음) · 비중 토큰 비용 50% > 공수 30% > module 수 20% · 변경 시나리오 단순 평균에 적용",
                "※ 공수·비용은 구현 측정(module·LOC)에 가정 상수를 곱한 값이며 실제 에이전트 세션 측정이 아니다 [B+C]. 1 MM = 21 man-day, 비용은 mid tier($3/$15 per MTok).",
                "출처: DP1/qa4-preregistration.md · DP4 평가 장(토큰 비용 경계) · 공통 QA 문서 §7 · tools/unified_stars.py")
    f = s.shapes.add_shape(MSO_SHAPE.ROUNDED_RECTANGLE, Inches(0.4), Inches(1.28), Inches(12.53), Inches(0.5))
    f.name = "formula"
    f.fill.solid(); f.fill.fore_color.rgb = rgb("EAF0FA"); f.line.color.rgb = rgb(NAVY); f.shadow.inherit = False
    tf = f.text_frame; tf.word_wrap = True; tf.vertical_anchor = MSO_ANCHOR.MIDDLE
    p = tf.paragraphs[0]; p.alignment = PP_ALIGN.CENTER
    r = p.add_run(); r.text = "S = 0.5 × (비용 ÷ $0.5) + 0.3 × (공수 ÷ 0.5 MM) + 0.2 × (module 수 ÷ 2)"
    r.font.size = Pt(15); r.font.bold = True; r.font.name = FONT; r.font.color.rgb = rgb(NAVY)
    t1 = [["별", "S 기준", "도출 (세 지표가 함께 만족하는 모습)"],
          ["★★★", "S ≤ 1.0", "세 지표가 모두 ★★★ 경계(비용 $0.5, 0.5 MM, 2 module)면 0.5+0.3+0.2 = 1.0. 한 지표가 경계를 넘으면 다른 지표가 그만큼 낮아야 한다. 예: $0.25 + 0.5 MM + 4 module = 0.25+0.3+0.4 = 0.95"],
          ["★★", "1.0 < S ≤ 3.2", "세 지표가 모두 ★★ 경계($2, 1.0 MM, 6 module)면 0.5×4 + 0.3×2 + 0.2×3 = 3.2. 예: $0.5 + 1.0 MM + 2 module = 0.5+0.6+0.2 = 1.3"],
          ["★", "S > 3.2", "평균적으로 ★★ 경계도 넘음. 예: $2 + 1.0 MM + 8 module = 2.0+0.6+0.8 = 3.4"]]
    B.table(s, 0.4, 1.9, [0.8, 1.4, 5.3], t1, size=9, row_h=0.58, fills={1: [FILL[3]] * 3, 2: [FILL[2]] * 3, 3: [FILL[1]] * 3}, align=["c", "c", "l"])
    t2 = [["항 (★★★ 경계로 나눔)", "★★★ / ★★ 경계", "비중", "근거"],
          ["① 토큰 비용 (mid tier $/변경)", "$0.5 / $2", "0.5", "$0.5 = 약 25k 토큰 세션 1회 + 재작업 없음, $2는 그 4배"],
          ["② 개발 공수 (MM/변경)", "0.5 / 1.0", "0.3", "0.5 MM = 1명 2주 sprint 안에 흡수, 1 MM = 로드맵 항목"],
          ["③ 변경 module 수", "2 / 6", "0.2", "공통 룰 §7"]]
    B.table(s, 0.4, 4.15, [2.4, 1.3, 0.6, 3.2], t2, size=8.5, row_h=0.36, align=["l", "c", "c", "l"])
    rows = [["후보", "비용", "공수", "module", "S", "QA4"]]
    names = {"DP1": ("DP1 C1", "DP1 C2"), "DP2": ("DP2 C1", "DP2 C2"), "DP4": ("DP4 후보1", "DP4 후보2")}
    for dp in ("DP1", "DP2", "DP4"):
        for k, c in enumerate(("C1", "C2")):
            q = inp[dp]["values"][c].get("qa4") or inp[dp]["values"][c]["qa4_equal"]
            rows.append([names[dp][k], f"${q['usd_t2']:.2f}", f"{q['mm']:.2f}", f"{q['modules']:.2f}", f"{U.qa4_score(q['usd_t2'], q['mm'], q['modules']):.2f}", S(res[dp][c]["QA4"])])
    B.table(s, 8.2, 1.9, [1.15, 0.75, 0.7, 0.8, 0.5, 0.85], rows, size=9, row_h=0.3, align=["l", "c", "c", "c", "c", "c"])
    B.tb(s, 8.2, 4.35, 4.75, 0.5, [("세 지표는 같은 비중이 아니다: 경계 대비 2배일 때 S에 비용 +0.5, 공수 +0.3, module +0.2.", dict(size=9, bold=True, color=NAVY))], name="note")
    B.blocks(s, ["이전(v1): 세 지표 각각의 별을 구해 '비중 50% 초과' 중앙값으로 결정. 지표별 기준만 있어 교차 시 결과가 표에서 안 보였다. DP4는 비용 우선 규칙·man-day 3/7.",
                 "통합: 비용 mid tier, 공수 MM(man-day ÷ 21), 시나리오 단순 평균, 점수 S. DP1·DP2·DP4 별은 모두 기존과 같다."],
             ["S는 선형 합이라 한 지표가 아주 나빠도 다른 지표가 0에 가까우면 ★★★이 가능하다(예: 비용 0, 공수 0, module 10 → S=1.0). 지표별 가드를 둘지는 소유자 결정.",
              "DP1 C2는 S = 1.05로 ★★★ 경계 +5%. 가중 0.5/0.3/0.2는 제안값(조정 가능)."],
             y=5.7, h=1.3, lt="이전 기준과 통합", rt="정직한 주의", size=8.5)
    add(s)

    # ---------------------------------------------------------------- QA5, QA6
    crit("QA5 기능 정확성 — 공통 별 기준 (DP3)", "F1 상대 하락률 = (압축 전 + full recompute의 F1 − 후보 F1) ÷ 압축 전 + full recompute의 F1 · 같은 task·dataset·모델·precision",
         [["★★★", "하락 ≤ 1%", "소유자가 정한 허용 정확도 저하 한도(압축 전 + full recompute 대비 F1 1% 이내, 상대 비율, 2026-10-09 확정)", "소유자 결정"],
          ["★★", "1% < 하락 ≤ 3%", "제안값: 허용 한도의 3배. '눈에 띄는 열화'가 시작되는 구간으로 본다. task의 run-to-run F1 변동을 재서 하한을 확인해야 한다", "정책 선택, 소유자 결정 필요"],
          ["★", "하락 > 3%", "허용 한도를 크게 넘은 정확도 손실", "정책 선택"]],
         ["DP3 전용 QA다. 다른 DP는 출력이 변하지 않는 것이 전제이므로 bit-exact 확인으로 다룬다.",
          "Baseline은 '압축 전 + full recompute'다. 후보의 F1이 올라가는 경우는 하락 0%로 본다.",
          "DP3 측정: 소형 모델(Qwen2.5-1.5B) eviction micro-benchmark + 매핑. 시뮬레이터로는 정확도를 알 수 없다."],
         ["두 번째 경계 3%는 데이터로 도출하지 못했다. 문헌은 KV 압축을 '무시할 만한 저하'로 보고하지만(KVzip: 3~4배 KV 축소, NeurIPS 2025) F1 하락의 일반적 임계는 없다.",
          "소형 모델·단락 1.5K token·재계산 없는 eviction이라 DP3의 32K~256K 문맥을 대표하지 않는다. 별은 가정 의존이다.",
          "query-agnostic(C1)이 query-aware(C2)보다 정확도가 낮다는 가정은 이 측정으로 확인한다."],
         "※ 한도 1%는 PPT DP3 설계 장의 Functional Correctness(F1 score) 지표와 같은 값이다.",
         "출처: 소유자 확정(2026-10-09) · KVzip, NeurIPS 2025 (neurips.cc/virtual/2025/oral/118742) [초록 확인] · DP3/accuracy")

    crit("QA6 확장성 — 공통 별 기준 (DP4)", "SE(N) = Goodput(N) ÷ ((N / N0) × Goodput(N0)) · N0 = 2 노드 · 별은 SE(N_max=16) · N > 2는 모델 외삽(시뮬레이션)",
         [["★★★", "SE(N_max) ≥ 90%", "서버를 N배로 늘릴 때 처리량 손실 10% 이내(16노드에서 14.4노드분 효과). 병렬 효율 논문에서 '효율적'이라 보고할 때 흔히 쓰는 90%", "Cornell CVW · arXiv 1704.03329 [검색 확인]. 90%는 보고 관행이지 공식 표준이 아님"],
          ["★★", "SE(N_max) 70 ~ 90%", "확장은 되지만 조율 계층이 병목 조짐. 70% 하한 = 10대 증설에 7대분 효과(3대분 낭비). 매우 큰 규모에서 70~80%도 '우수'로 보고한 사례", "arXiv 2409.16053 AthenaK (65,536 GPU에서 80%) [검색 확인]"],
          ["★", "SE(N_max) < 70%", "손실 30% 초과 = 증설 비용의 1/3 이상 낭비. 조율 계층이 병목이다", "공통 QA 문서 §13 임시 정의(DP4 초안 값) [내부]"]],
         ["이전: DP4가 이 기준. DP2는 결과 문서에서 η(N=32) 0.90/0.70을 제안값으로 두었다(경계 같음, N_max만 다름. DP2는 PPT 선정 QA가 아님). N_max를 16으로 통일한다.",
          "결과: DP4 후보1 SE 93%(★★★), 후보2 64%(★). Baseline(무상태 LB)은 97%.",
          "레플리카가 상태를 공유하지 않는 후보2는 서버가 N배면 레플리카당 갱신 부하가 약 N배가 된다."],
         ["후보2의 ★은 보완(샤딩 구조) 전 설계 기준이다. 후보1의 Router도 전체 이벤트를 처리하는 구조라 비슷한 한계가 있을 수 있다.",
          "N > 2는 실측이 아니라 모델 외삽이다(C-04). 90%는 HPC 관행이며 공식 기준은 찾지 못했다.",
          "공통 룰 문서에는 §13이 없다(PPT가 인용한 DP4 초안의 절 번호)."],
         "※ DP4 PPT 31장의 SE 곡선과 같은 값이다.",
         "출처: cvw.cac.cornell.edu/parallel/efficiency/scaling · arxiv.org/abs/1704.03329 · arxiv.org/abs/2409.16053")

    # ---------------------------------------------------------------- consistency
    s = B.frame("적용 결과 — 정합성 점검 (공통 기준 v2)", "기존 별과 비교: DP1 C1·DP4 모든 별 불변 · QA1 ★★★ 경계 2.0으로 DP1 C2·DP2 QA1이 ★★ · DP3는 시뮬레이션 평가",
                "※ DP2는 PPT 선정 QA(QA1, QA2, QA4)만 합산했다. DP4는 현 DP4(요청 조율, 옛 DP0)이며 근거는 PPT 26~31장이다. DP3 QA5는 소형 모델 실측 매핑(§DP3 장).")
    nm = {"DP1": ("DP1 C1 자원 상태 기반", "DP1 C2 AI Data 특성 기반"), "DP2": ("DP2 C1 스케줄링 시점", "DP2 C2 사전 계획"), "DP4": ("DP4 후보1 OSS 확장", "DP4 후보2 자체 구현"),
          "DP3": ("DP3 C1 Offline", "DP3 C2 Online")}
    rows = [["DP · 후보", "QA1", "QA2", "QA3", "QA4", "QA5", "QA6", "합계 v2", "합계 v1", "선택"]]
    sel = {"DP1": "C1 (10 대 8)", "DP2": "구분 불가 (동점)", "DP4": "후보2 (동점, QA2에서 우세)", "DP3": "(아래 DP3 장)"}
    for dp in ("DP1", "DP2", "DP4", "DP3"):
        for k, c in enumerate(("C1", "C2")):
            st = res[dp][c]
            tot = sum(st.values())
            v1 = U.v1_stars(inp)[(dp, c)]
            prev = sum(inp[dp]["previous_stars"][c].values()) if inp[dp].get("previous_stars", {}).get(c) else None
            v1tot = str(prev) if prev else "—"
            rows.append([nm[dp][k]] + [S(st[q]) if q in st else "—" for q in ("QA1", "QA2", "QA3", "QA4", "QA5", "QA6")] + [str(tot), v1tot, sel[dp] if k == 0 else ""])
    st1 = res["DP1-1안"]["C1"]
    rows.append(["(참고) DP1 1안 Affinity 없음"] + [S(st1[q]) if q in st1 else "—" for q in ("QA1", "QA2", "QA3", "QA4", "QA5", "QA6")] + [str(sum(st1.values())), "9", "보완 전"])
    B.table(s, 0.4, 1.3, [2.6, 0.95, 0.95, 0.95, 0.95, 0.95, 0.95, 0.85, 0.85, 2.53], rows, size=9, row_h=0.31, align=["l", "c", "c", "c", "c", "c", "c", "c", "c", "l"])
    B.blocks(s, ["DP1 C1 합계 10, DP4 두 후보 9 대 9: 모든 QA 별과 합계가 같다. 선택도 같다.",
                 "DP1 C2 9 → 8, DP2 두 후보 9 → 8: QA1 ★★★ → ★★ (×1.423, ×1.66 < 2.0). 후보 간 순서는 그대로여서 선택은 바뀌지 않는다.",
                 "DP1 1안(Affinity 없음)은 QA2 r = 0.86(A ★★★ + R ★)로 ★★이다. PPT 표기와 같고, v1(절대 SLO만)이었다면 ★★★이 되는 모순이 사라졌다.",
                 "DP3는 사전 등록한 시뮬레이션 [B+C]를 처음 평가한 것이라 '기존 별'이 없다."],
             ["합계 v1 열은 DP별 기존 별(DP1 10/9, DP2 9/9, DP4 9/9)이다. 경계 근접: DP1 C1 QA2 r = 0.948(하한 0.90), DP1 C2 QA4 S = 1.05, DP4 후보2 QA2 r = 1.14, DP3 C2 QA3 ×1.26(경계 1.25).",
              "다른 기준 계열을 쓰면: 공통 룰 QA1(0.90/1.10) → DP1 C1 합계 10 → 11, 내림 규칙의 QA2 → DP4 후보2 9 → 8(선택 뒤집힘).",
              "DP4 QA1·QA2·QA6의 Baseline은 실측이지만 후보는 시뮬레이터·추정이다 [A+C]. DP1·DP2·DP3은 시뮬레이션 [B+C]다."],
             y=4.6, h=2.4, lt="읽는 법", rt="정직한 주의", size=9.5)
    add(s)

    # ---------------------------------------------------------------- DP2 result
    s = B.frame("DP2 평가 결과 — 공통 기준 v2 (H100 + B200 통합)", "C1 스케줄링 시점 결정 vs C2 사전 계획 결정 · 괄호 = 후보 ÷ Baseline · 시뮬레이션 [B+C] · 근거: DP2 평가 결과 2026-10-06",
                "※ 별 경계는 공통 별 기준 v2다(QA1 0.97/2.0, QA2 A·R 평균, QA4 점수 S). DP2 결과 문서의 QA3(GPU 사용률)·QA5(확장성)는 PPT 선정 QA가 아니라 제외했다.")
    v1, v2 = inp["DP2"]["values"]["C1"], inp["DP2"]["values"]["C2"]
    b = inp["DP2"]["baseline"]
    q1, q2 = res["DP2"]["C1"], res["DP2"]["C2"]
    qa4c = {c: inp["DP2"]["values"][c]["qa4"] for c in ("C1", "C2")}
    r1, r2 = U.qa2_ratio(inp["DP2"], v1), U.qa2_ratio(inp["DP2"], v2)
    rows = [["QA", "평가 metric (↑/↓ 좋음)", "Baseline-PD-fixed", "C1 스케줄링 시점 결정", "C2 사전 계획 결정"],
            ["QA1 처리량", "Max SLO goodput (tok/s) ↑", f"{b['tps']:,}", f"{S(q1['QA1'])}  {v1['qa1_tps']:,} (×{v1['qa1_ratio']:.2f}) [B+C]", f"{S(q2['QA1'])}  {v2['qa1_tps']:,} (×{v2['qa1_ratio']:.2f}) [B+C]"],
            ["QA2 지연 (TTFT)", "TTFT P99 (ms) ↓", f"{b['ttft_p99_ms']:,}", f"{v1['ttft_p99_ms']:,} (×0.40)", f"{v2['ttft_p99_ms']:,} (×0.41)"],
            ["QA2 지연 (TPOT)", "TPOT P99 (ms) ↓", f"{b['tpot_p99_ms']}", f"{v1['tpot_p99_ms']} (×1.34)", f"{v2['tpot_p99_ms']} (×1.35)"],
            ["QA2 별점", "A(절대 SLO)·R(개선 r)의 평균", "A ★★ (TTFT > 2 s)", f"{S(q1['QA2'])} (A3·R3, r={r1:.2f}) [B+C]", f"{S(q2['QA2'])} (A3·R3, r={r2:.2f}) [B+C]"],
            ["QA4 ① 비용", "에이전트 비용 $ (mid tier) ↓", "—", f"${qa4c['C1']['usd_t2']:.2f}", f"${qa4c['C2']['usd_t2']:.2f}"],
            ["QA4 ② 공수", "개발 공수 (man-month) ↓", "—", f"{qa4c['C1']['mm']:.2f}", f"{qa4c['C2']['mm']:.2f}"],
            ["QA4 ③ module", "변경 module 수 (4 시나리오 평균) ↓", "—", f"{qa4c['C1']['modules']:.2f}", f"{qa4c['C2']['modules']:.2f}"],
            ["QA4 별점", "점수 S [B+C]", "—", f"{S(q1['QA4'])} (S={U.qa4_score(qa4c['C1']['usd_t2'], qa4c['C1']['mm'], qa4c['C1']['modules']):.2f})", f"{S(q2['QA4'])} (S={U.qa4_score(qa4c['C2']['usd_t2'], qa4c['C2']['mm'], qa4c['C2']['modules']):.2f})"],
            ["별 합계", "QA1 + QA2 + QA4", "—", f"{sum(q1.values())}", f"{sum(q2.values())}"]]
    B.table(s, 0.4, 1.3, [2.2, 3.4, 1.8, 2.6, 2.53], rows, size=9.5, row_h=0.36, align=["l", "l", "c", "c", "c"], bold_first_col=True)
    B.blocks(s, ["시스템: SYS-H100 + SYS-B200 통합. 노드 = 8-GPU, 6종 메모리, Llama-3.1-70B BF16, 노드 간 링크 RDMA 50 GB/s(ASSUMED). 시나리오 19개 × 2시스템 = 38쌍.",
                 "값은 쌍별 값의 기하평균. QA2는 Baseline의 최적 부하(iso-load)에서 비교(결과를 본 뒤 정한 정의).",
                 "선택: 별 합계 8 대 8, QA1·QA2·QA4 모두 같아 이 평가는 선택을 가르지 못한다(goodput 비 C2/C1 = ×1.002)."],
             ["QA1 ×1.66은 Baseline이 SLO를 거의 못 지키도록 설계된 시나리오(링크 경합 ×6~8, 긴 History ×3~4)가 끌어올린다. 그래도 2.0에는 닿지 않아 ★★다.",
              "TPOT P99가 Baseline보다 나쁘다(×1.34, 단 12.0 ms로 SLO 50 ms 이내). 공통 시나리오 3개에서는 TTFT P99도 나빠진다.",
              "후보 간 차이는 결정 시점이 아니라 결정 비용 가정(1 ms @ 64 후보)에 의존한다."],
             y=5.05, h=1.95, lt="평가 환경과 선택", rt="정직한 주의", size=9.5)
    add(s)

    # ---------------------------------------------------------------- DP3 result
    s = B.frame("DP3 평가 결과 — 시뮬레이션 [B+C] (H100 + B200 통합)", "C1 Offline(Query-agnostic) vs C2 Online(Query-aware) · 괄호 = 후보 ÷ Baseline(As-Is, 전체 KV 재사용) · 비교 가능 32쌍 기하평균 · 사전 등록 후 실행",
                "※ 정확도는 시뮬레이터 밖이다: 소형 모델 eviction 실측 + 매핑 [A 소형 + C]. 근거: DP3/results/2026-10-11_dp3-qa-evaluation.md · DP3/simulation-plan.md(r=0.30, rho=0.15 사전 등록)")
    c1, c2 = D3["values"]["C1"], D3["values"]["C2"]
    b3 = D3["baseline"]
    s1, s2 = res["DP3"]["C1"], res["DP3"]["C2"]
    r1, r2 = U.qa2_ratio(D3, c1), U.qa2_ratio(D3, c2)
    q5c = {c: (f"{S(res['DP3'][c]['QA5'])} F1 하락 {D3['values'][c]['f1_drop_pct']:.1f}%" if q5ok else "측정 중 (표본 부족)") for c in ("C1", "C2")}
    rows = [["QA", "평가 metric (↑/↓ 좋음)", "Baseline (As-Is)", "C1 Offline", "C2 Online"],
            ["QA2 지연 (TTFT)", "TTFT P99 (ms) ↓", f"{b3['ttft_p99_ms']:,.0f}", f"{c1['ttft_p99_ms']:,.0f} (×{1/ag['C1-Offline']['ttft']['ratio_gm']:.2f})", f"{c2['ttft_p99_ms']:,.0f} (×{1/ag['C2-Online']['ttft']['ratio_gm']:.2f})"],
            ["QA2 지연 (TPOT)", "TPOT P99 (ms) ↓", f"{b3['tpot_p99_ms']:.1f}", f"{c1['tpot_p99_ms']:.1f} (×{1/ag['C1-Offline']['tpot']['ratio_gm']:.2f})", f"{c2['tpot_p99_ms']:.1f} (×{1/ag['C2-Online']['tpot']['ratio_gm']:.2f})"],
            ["QA2 별점", "A·R 평균", "—", f"{S(s1['QA2'])} (A3·R3, r={r1:.2f})", f"{S(s2['QA2'])} (A3·R1, r={r2:.2f})"],
            ["QA3 자원 (HBM)", "HBM KV 시간평균 (GiB) ↓", f"{b3['hbm_gib']:.1f}", f"{S(s1['QA3'])}  {c1['hbm_gib']:.1f} (×{1/c1['qa3_ratio']:.2f})", f"{S(s2['QA3'])}  {c2['hbm_gib']:.1f} (×{1/c2['qa3_ratio']:.2f})"],
            ["QA5 기능 정확성", "F1 상대 하락 (%) ↓", "0 (정의)", q5c["C1"], q5c["C2"]],
            ["별 합계", "QA2 + QA3 (+ QA5)", "—", f"{sum(s1.values())}" + ("" if q5ok else " + QA5"), f"{sum(s2.values())}" + ("" if q5ok else " + QA5")]]
    B.table(s, 0.4, 1.3, [2.0, 3.0, 1.8, 3.0, 2.73], rows, size=9.5, row_h=0.36, align=["l", "l", "c", "c", "c"], bold_first_col=True)
    B.blocks(s, ["C1은 TTFT를 줄이고(28/32쌍) HBM을 1/3로 줄이며(32/32쌍) TPOT는 비슷하다.",
                 "C2는 HBM 절감이 작고(×1.26) TTFT가 Baseline보다 나쁘다(32쌍 중 2쌍만 이김): 전체 KV를 적재해 적재 이득이 없는데 점수 계산 + 재계산이 요청 경로에 들어온다.",
                 "Baseline이 못 끝내는 시나리오(ST-11, DY-03 H100)에서 C1은 끝낸다(TTFT P99 461 ms, 679 ms). 집계에서는 제외한 쌍이다.",
                 "시나리오 18개(공통 3 + Stress 12 + Dynamic 3) × 2시스템 × 3정책 × 부하 4 × seed 5."],
             ["HBF처럼 GPU가 직접 읽는 tier(ST-06)에서는 Baseline이 적재 비용 없이 서빙해 C1·C2 모두 TTFT가 ×0.09~0.14로 진다. 선택 재계산(r·rho·L ≈ 5.9K token prefill)이 원인이다(rho = 0 what-if에서 역전).",
              "결과는 유지 비율 r = 0.30 가정에 의존한다. r = 0.5이면 H100에서 C1 TTFT 이득이 사라진다(×0.60). 사전 등록값이며 결과를 보고 바꾸지 않았다.",
              "C1 사전 압축 비용·저장 공간은 모델링하지 않았다(C1에 유리). C2의 선택 복사 비용도 0으로 뒀다(C2에 유리).",
              "QA3 C2의 ×1.26은 경계 1.25 바로 위다(H100 1.34, B200 1.20). QA5는 소형 모델·재계산 없음이라 가정 의존이다."],
             y=3.95, h=3.05, lt="읽는 법", rt="정직한 주의", size=9.5)
    add(s)

    # ---------------------------------------------------------------- decisions
    s = B.frame("공통 별 기준 v2 — 소유자 결정이 필요한 사항", "결정 전까지는 proposal이다 · 상세는 qa-star-criteria-unified.md §8",
                "※ 평가 수치(측정·시뮬레이션 값)는 어떤 결정에서도 경계에 맞춰 바꾸지 않는다.")
    rows = [["#", "결정", "제안", "영향"],
            ["D1", "QA1 ★★★ = 2.0", "확정(요청). 값은 조정하지 않고 별이 내려가는 것을 그대로 보고", "DP1 C2, DP2 두 후보 합계 −1 (선택은 같음)"],
            ["D2", "QA2 R 경계 1.20 / 0.90, 올림 규칙", "제안대로 (잡음 폭의 2배 / 열세 경계). 올림 대신 내림이면 DP4 선택이 뒤집힘", "DP1 C1이 하한에서 +5%"],
            ["D3", "QA4 가중 0.5/0.3/0.2, 지표별 가드 여부", "가중은 제안대로, 가드는 소유자 결정", "DP1 C2 S = 1.05"],
            ["D4", "QA5 두 번째 경계 3%", "제안 3%, task의 F1 변동을 재서 확인", "DP3 별"],
            ["D5", "DP2 결과 세트", "2026-10-06 C1/C2 사용. 2026-10-10 Dispatcher 대 Blackboard는 후보 축이 달라 제외", "PPT의 최종 DP2 확인"],
            ["D6", "DP3 r, rho 가정 (0.30, 0.15)과 C2의 선택 재계산 필수 여부, HBF에서 압축 끄기", "r, rho는 사전 등록값 + 민감도 병기. 재계산·HBF 정책은 설계 결정", "DP3 별과 선택"],
            ["D7", "QA 번호", "요구사항 덱의 QA-05 확장성 / QA-06 정확성을 PPT(QA5 정확성, QA6 확장성)에 맞춰 교환", "문서 일관성"],
            ["D8", "Evaluation/DP4 폴더", "옛 DP4(현 DP6) 자료다. 현 DP4(요청 조율) 평가 문서 위치를 정한다", "평가 문서 정리"]]
    B.table(s, 0.4, 1.35, [0.6, 3.6, 5.6, 2.73], rows, size=9.5, row_h=0.56, align=["c", "l", "l", "l"], bold_first_col=True)
    add(s)

    # ================================================================ Appendix additions
    # ---- why absolute values differ
    s = B.frame("부록 — 같은 QA의 절대값이 DP마다 다른 이유", "그래서 별은 절대값이 아니라 '같은 DP의 Baseline 대비'(+ 절대 SLO)로 매긴다 · DP 간 절대값 비교는 하지 않는다",
                "※ DP1~DP3 = 시뮬레이션 [B+C], DP4 Baseline = 실측 [A]. 값은 각 DP 결과 문서·PPT 기준.")
    rows = [["", "DP1 이기종 메모리 데이터 배치", "DP2 Prefill/Decode 실행 위치", "DP3 KV 압축·재사용", "DP4 다중 서버 요청 조율"],
            ["평가 단위", "서버 1대(8-GPU, TP8)", "P노드 + D노드 (노드당 TP8)", "서버 1대(8-GPU, TP8)", "2노드 × 8 GPU = 16 GPU (실측)"],
            ["대표 워크로드", "KV 32K~512K, RAG 8 TiB, LoRA·MoE 혼합, HBM 압박", "단일 턴 8K + 멀티턴 History 16K~256K", "재사용 문맥 8K~256K, 질의 64~2K", "입력 8K / 출력 256, prefix 재사용 통제"],
            ["Baseline 정의", "정적 배치(이동 없음)", "P/D 역할 고정", "전체 KV 그대로 재사용", "상태·캐시 비인지 라우팅"],
            ["부하 방식", "load sweep 최대(Max SLO goodput)", "Baseline 최적 부하 + sweep", "Baseline 용량의 70%로 고정", "load sweep, 서버 수 N 증설"],
            ["QA1 Baseline (tok/s)", "336", "575", "—", "3,200"],
            ["QA2 Baseline TTFT P99 (ms)", "1,084", "2,461", "571", "2,300"],
            ["QA3 Baseline HBM (GiB)", "146.6", "—", "107.1", "—"]]
    B.table(s, 0.4, 1.3, [2.2, 2.6, 2.6, 2.6, 2.53], rows, size=9, row_h=0.4, align=["l", "l", "l", "l", "l"], bold_first_col=True)
    B.blocks(s, ["대상 단위가 다르다: DP4만 16 GPU 클러스터라 처리량이 한 자릿수 배 크다(3,200 vs 336). DP1~DP3는 8-GPU 1대.",
                 "워크로드가 다르다: DP1·DP3는 긴 문맥(수십~수백 K token)이라 KV 적재가 지배하고 처리량이 낮다. DP4는 8K라 높다.",
                 "Baseline이 다르다: 각 DP의 As-Is가 다르므로 '1.0'의 의미가 다르다.",
                 "부하를 정하는 방식이 다르다: DP3 TTFT는 용량의 70% 부하의 값이라 낮고, DP1·DP2는 포화 근처의 값이다."],
             ["집계 범위가 다르다: 각 DP의 시나리오 집합(공통 + 전용)에 대한 쌍별 기하평균이라 시나리오 구성에 값이 따라간다.",
              "근거 수준이 다르다: DP4 Baseline은 실측이라 SLO 경계(2 s, 50 ms) 부근이고 DP1~DP3는 시뮬레이션이다.",
              "따라서 같은 QA의 별은 같은 DP 안의 Baseline 대비로 읽어야 하며, DP 간에는 별(기준이 같음)만 비교한다.",
              "공통 시나리오(다음 장)는 DP 간 같은 조건을 보기 위한 최소한의 연결고리다."],
             y=4.75, h=2.25, lt="왜 다른가", rt="어떻게 읽어야 하나", size=9.5)
    add(s)

    # ---- common scenarios
    s = B.frame("부록 — 공통 시나리오 (CB-1 ~ CB-3)", "모든 DP가 같은 이름·같은 조건으로 도는 3개 시나리오 · 후보가 Baseline보다 나빠지지 않는지(no-harm)와 DP 간 연결을 본다",
                "※ 정의: doc-mk/Evaluation/common-benchmark.md §2.1. 각 DP의 실현 방식은 DP별 benchmark 문서에 있다.")
    rows = [["ID", "무엇인가", "조건", "드러내는 것"],
            ["CB-1 cb_kv_8k_b32", "KV만, HBM 압박 고정", "입력 8K / 출력 256, 동시 32, HBM 용량 ×0.12", "HBM이 빠듯할 때 KV 배치·압축의 효과"],
            ["CB-2 cb_kv_8k_b32_ramp", "CB-1 + HBM 압박이 시간에 따라 증가", "같은 KV, HBM 압박 점진 증가", "압박 증가에 대한 반응"],
            ["CB-3 cb_mixed_8k_b32", "KV + LoRA + MoE + Agent/Tool 혼합", "KV 외 데이터는 고정 배치", "KV 외 data와 같이 있을 때의 경합"]]
    B.table(s, 0.4, 1.3, [2.4, 2.9, 3.6, 3.63], rows, size=9.5, row_h=0.42, align=["l", "l", "l", "l"], bold_first_col=True)
    rows = [["DP", "공통 시나리오에서의 QA (후보 ÷ Baseline 또는 배수)", "왜 이렇게 되나"],
            ["DP1", "QA1 ×1.00 (둘 다, Baseline이 이미 포화), C1 TTFT P99 ×2.95 나쁨 · C2 ×1.03", "이동할 이득이 없는 정적 워크로드라 이동 비용만 남는다. 이득은 Dynamic 시나리오에서 나온다"],
            ["DP2", "QA1 ×1.69, TTFT P99 ×1.50 나쁨(후보 ÷ Baseline), TPOT ×1.75", "단일 턴이라 History 효과는 없지만 Baseline의 고정 역할이 D 노드 Prefill 능력을 낭비한다"],
            ["DP3", f"C1 TTFT {ag['C1-Offline']['by_family']['ttft/common']:.2f}배 개선, HBM {ag['C1-Offline']['by_family']['hbm/common']:.2f}배 감소 / C2 TTFT {ag['C2-Online']['by_family']['ttft/common']:.2f}배, HBM {ag['C2-Online']['by_family']['hbm/common']:.2f}배", "8K 문맥도 DRAM에서 적재해야 하는 구성이라 압축이 적재 시간을 줄인다"],
            ["DP4", "W1(공통 벤치마크): 처리량 ×1.05 · ×1.04, TTFT P99 ×0.90 · ×0.84", "정책 효과가 크지 않게 prefix 재사용을 통제한 기준선"]]
    B.table(s, 0.4, 3.3, [1.0, 6.0, 5.53], rows, size=9.5, row_h=0.62, align=["c", "l", "l"], bold_first_col=True)
    B.tb(s, 0.4, 6.55, 12.5, 0.4, [("공통 시나리오만 보면 DP마다 QA 방향이 다르다(DP1은 거의 중립, DP3는 크게 개선). 그래서 별은 공통 + DP 전용 시나리오를 함께 집계한 값이고, 공통만의 별은 참고값이다.", dict(size=10, bold=True, color=NAVY))], name="foot_msg")
    add(s)

    # ---- DP scenario slides
    def dp_scn(title, subtitle, rows, left, right, foot):
        s = B.frame(title, subtitle, foot)
        B.table(s, 0.4, 1.3, [2.4, 4.0, 3.1, 3.03], [["시나리오군", "무엇인가", "QA가 떨어지는 곳", "QA가 오르는 곳"]] + rows, size=9, row_h=0.62, align=["l", "l", "l", "l"], bold_first_col=True)
        B.blocks(s, left, right, 1.3 + 0.34 + 0.62 * len(rows) + 0.15, 7.0 - (1.3 + 0.34 + 0.62 * len(rows) + 0.15), lt="이 DP의 시나리오가 의미하는 것", rt="정직한 주의", size=9.5)
        add(s)

    dp_scn("부록 — DP1 시나리오: 데이터 배치(이동)가 갈리는 조건", "Common 3 + Stress 23 + Dynamic 6 · 노드 1대 안에서 6종 메모리 사이 이동 · Baseline = 정적 배치(이동 없음)",
           [["Common (CB-1~3)", "8K KV, HBM 압박 고정·증가, 혼합", "QA1 ×1.00, C1 TTFT P99 ×2.95 (이동 비용만 남음)", "—"],
            ["Stress 23", "대형 batch, 512K 초장문, RAG 1~8 TiB, LoRA·MoE skew, HBM BW 저하 등 trade-off 관찰", "일부 시나리오에서 Baseline보다 TTFT 나쁨(21쌍 중 6쌍, 최악 ×4.32)", "Stress 9개 합산 QA1은 C1 ×1.00 · C2 ×1.04 (SYS-B200)"],
            ["Dynamic 6", "처음엔 Baseline이 SLO를 지키다 hot set 이동·유휴 KV의 HBM 점유·host link 저하로 stale해짐", "—", "QA1 C1 ×1.64 · C2 ×2.20 (SYS-B200). 이득이 몰린 곳"]],
           ["이득은 '정적 배치가 낡아지는' 조건에 집중된다. Dynamic은 Baseline의 실패 양상을 알고 설계했으므로 이득을 일반화하지 않는다.",
            "QA1 ★★★(≥ 2.0)은 Dynamic C2 하나가 넘고, 18~21쌍 통합에서는 ×1.30 / ×1.42다."],
           ["공통 시나리오에서 C1의 TTFT가 나쁜 것은 숨기지 않았다(진단 값).", "Dynamic은 benchmark-fit 시나리오(loop 2에서 추가)라 이득 크기에 selection이 개입했다."],
           "※ 출처: DP1/benchmark.md, DP1/results/2026-10-02_dp1-qa-evaluation.md (SYS-B200 Combined 표)")

    dp_scn("부록 — DP2 시나리오: Prefill 실행 위치를 정하는 조건", "Common 3 + Stress 12 + Dynamic 4 · P/D 노드 사이 · Baseline = P/D 역할 고정(Baseline-PD-fixed)",
           [["Common (CB-1~3)", "단일 턴 8K, D 노드 HBM 압박", "TTFT P99 ×1.50 나쁨, QA2 개선 배수 ×0.78", "QA1 ×1.69 (고정 역할 낭비 제거)"],
            ["Stress 12 — History 재개", "History 32K~256K가 HBM·DRAM·HBF·SSD에 있는 멀티턴 재개", "TPOT P99가 ×2~3 나빠지는 시나리오가 있다(H100 hbf_hist 12.5 → 36.5 ms, SLO 50 ms 이내)", "긴 History offload goodput ×3.20(H100), DRAM·SSD 재개 ×1.5~1.7"],
            ["Stress 12 — 포화·경합", "Prefill burst, Decode 편중, 노드 간 링크 경합(BW ×0.25)", "이득이 작은 곳: Decode 편중 goodput ×1.10~1.20", "링크 경합·burst에서 TTFT 큰 개선 (Stress 24쌍 TTFT ×0.29)"],
            ["Dynamic 4", "P 노드 처리량 저하 등 runtime 변화", "TPOT ×1.01로 변화 없음", "TTFT ×0.41, QA1 ×1.29"]],
           ["이득은 'KV가 있던 곳과 Prefill 노드가 달라 전송이 낭비되는' 조건에 있고 Planner가 좋은 위치를 고른다.", "C1·C2는 구분되지 않는다(goodput 비 ×1.002)."],
           ["Baseline이 SLO를 거의 못 지키게 설계한 시나리오가 ×1.66을 끌어올린다. 중앙 시나리오는 ×1.0~1.7.", "TPOT P99가 ×1.34로 나쁘다(SLO 50 ms 이내)."],
           "※ 출처: DP2/benchmark.md, DP2/results/2026-10-06_dp2-qa-evaluation.md (집합별 표, 비율은 후보 ÷ Baseline)")

    dp_scn("부록 — DP3 시나리오: KV 압축·재사용이 갈리는 조건", "Common 3 + Stress 12 + Dynamic 3 · 문맥 8K~256K 재사용 · Baseline = 전체 KV 재사용(As-Is) · 도착률 = Baseline 용량의 70%",
           [["Common (CB-1~3) 8K", "DRAM에서 적재하는 8K 문맥, HBM 압박", "C2 TTFT ×0.79~0.96 (온라인 점수 계산 + 재계산)", f"C1 TTFT ×{ag['C1-Offline']['by_family']['ttft/common']:.1f}, HBM ×{ag['C1-Offline']['by_family']['hbm/common']:.1f}"],
            ["Stress — 문맥 길이", "32K / 64K / 128K / 256K (DRAM·CXL)", "256K에서 C1 TTFT ×0.73(H100): 재계산 prefill이 김", "32K~128K에서 C1 TTFT 개선, HBM 감소"],
            ["Stress — tier·재사용", "SSD 차가운 재사용, HBF 직접 읽기, skew/uniform, 긴·짧은 질의, 대표 Query 불일치", "HBF(ST-06): C1·C2 TTFT ×0.09~0.14. SSD(ST-05)는 표본 부족", "HBM 압박·분산 재사용(ST-08, 10)에서 C1 이득 큼"],
            ["Dynamic 3", "hot set 이동, burst, HBM 압박 증가", "C2는 Baseline보다 TTFT 나쁨 (×0.76~0.88)", "ST-11·DY-03 H100: Baseline이 못 끝내는 걸 C1이 끝냄"]],
           ["이득은 '외부 tier에서 문맥을 적재해야 하고 HBM이 빠듯한' 조건에서 나온다. GPU가 직접 읽는 tier에서는 압축이 순손실이다.", "C2는 어떤 조건에서도 TTFT 이득이 작다."],
           ["Offline 사전 압축 비용·공간을 모델링하지 않았다. r = 0.30 가정에 의존한다.", "정확도(QA5)는 이 시나리오로 알 수 없다."],
           "※ 출처: DP3/benchmark.md, DP3/results/2026-10-11_dp3-qa-evaluation.md")

    dp_scn("부록 — DP4 시나리오: 서버를 고르는 조건", "W1~W5 + 변경 시나리오 S1~S6 · 2노드 × 8 GPU 실측 Baseline + 시뮬레이터 · Baseline = 상태·캐시 비인지 라우팅",
           [["W1 공통", "입력 8K / 출력 256, prefix 재사용 통제", "정책 이득이 작음 (처리량 ×1.04~1.05)", "TTFT P99 ×0.84~0.90"],
            ["W2~W4 전용", "재사용 대화(0/30/60%), 긴 입력 P/D 분리, 메모리 압박(HBM 70~95%)", "후보1 TTFT가 후보2보다 약 120 ms 높음(P/D 경로 hop, 가설)", "캐시·메모리 인지 라우팅(P1~P3)이 효과를 내는 곳"],
            ["W5 서버 증설", "N = 2, 4, 8, 16 (N0 = 2)", "후보2 SE 64% (상태 비공유로 갱신 부하 ≈ N배)", "후보1 SE 93%"],
            ["S1~S6 변경", "새 tier, 비용 함수, P/D 정책, 노드 지시, vLLM 계약, 신규 기능", "S2~S4는 후보1(OSS 탐색)이 비쌈", "S1·S5·S6은 후보1(설정·plugin)이 쌈"]],
           ["QA6은 서버 수 증가 시나리오(W5)에서만 갈린다. QA4는 변경이 어디까지 번지는지(S1~S6)가 결정한다.", "후보 간 QA2 차이는 TTFT 2 s 경계를 사이에 둔 약 6%다."],
           ["N > 2는 실측이 아니라 모델 외삽이다. 후보2는 미구현이라 모델이다.", "QA4 토큰 비용은 OSS 탐색 토큰 가정에 민감하다."],
           "※ 출처: PPT DP4 26~32장 (doc-mk/DP4/DP0-qa-result-slides.pptx)")

    # ---- real measurement system (DP4)
    s = B.frame("부록 — 실측 기반 평가 시스템 (DP4 Baseline)", "DP4의 Baseline은 보유한 시스템에서 실측했다 · 그 외 값은 시뮬레이터로 대체 · 노드 간 링크·DRAM·SSD 사양은 아직 미확인",
                "※ 출처: PPT DP4 33~34장. DP1~DP3 Baseline은 실측이 아니다(시뮬레이션).")
    rows = [["항목", "값", "상태"],
            ["노드 / GPU", "2 노드 × H100 SXM 80GB × 8 = 16 GPU", "보유"],
            ["GPU 사양", "HBM3 3.35 TB/s, BF16 dense 989 TFLOPS, NVLink 900 GB/s", "공개 spec [B]"],
            ["모델 / 정밀도", "Llama-3.1-70B, BF16, TP=8 (노드당 replica 1개)", "공통 프로필"],
            ["워크로드", "입력 8K / 출력 256, prefix 재사용 통제, SLO TTFT P99 ≤ 2 s · TPOT P99 ≤ 50 ms", "공통 프로필"],
            ["Baseline", "vLLM + 정책 없는 기본 라우팅 (상태·캐시 비인지)", "실측 [A]"],
            ["노드 간 링크 / 호스트 DRAM / SSD", "확인 필요 (KV 전송 계산은 400 Gb/s ≈ 50 GB/s 가정)", "미확인"]]
    B.table(s, 0.4, 1.3, [2.6, 7.0, 2.93], rows, size=10, row_h=0.4, align=["l", "l", "l"], bold_first_col=True)
    rows = [["값", "출처", "Evidence"],
            ["Baseline 처리량·지연·SE(N0=2)", "보유 시스템 실측 (seed ≥ 5, P99·Goodput 기록)", "[A]"],
            ["HBM·호스트 DRAM 대역폭·용량", "실물 + 공개 spec", "[A]/[B]"],
            ["CXL·HBF·SSD tier 성능", "문헌·vendor spec을 입력으로 한 시뮬레이터", "[B+C]"],
            ["후보 2 결정 경로·상태 갱신 부하", "모델 + E1 보정(미측정)", "[C]"],
            ["N > 2 서버 확장", "모델 외삽 (실측은 2노드까지)", "[C]"]]
    B.table(s, 0.4, 4.3, [4.2, 6.2, 2.13], rows, size=9.5, row_h=0.36, align=["l", "l", "c"])
    B.tb(s, 0.4, 6.55, 12.5, 0.4, [("실측으로 확인한 것은 Baseline뿐이다. 후보 값(처리량·지연·SE)은 Baseline 실측 위에 시뮬레이터를 얹은 [A+C]다.", dict(size=10, bold=True, color=NAVY))], name="foot_msg")
    add(s)

    # ---- simulation assumptions
    s = B.frame("부록 — 시뮬레이션 구성 가정 (DP1 · DP2 · DP3 공통 시스템)", "실물이 없어 모델로 평가 · 하드웨어는 공개 spec·vendor 자료를 입력으로 하고 모델은 이산 사건 시뮬레이터 · 증거 수준 [B+C] · ASSUMED 항목은 민감도 확인 필요",
                "※ 출처: doc-mk/Evaluation/system-specs.md (DP1/sim/configs, 값의 provenance는 거기). 평가는 SYS-H100과 SYS-B200 두 세대를 모두 보고한다.")
    rows = [["구분", "SYS-H100 (Hopper급)", "SYS-B200 (Blackwell급)", "비고"],
            ["GPU / HBM (노드 합계)", "H100 × 8, HBM3 80 GiB × 8 = 640 GiB, 26.8 TB/s", "B200 × 8, HBM3e 192 GiB × 8, 64 TB/s", "8-GPU 노드를 TP8 하나의 장치로 모델. HBM 90%만 사용"],
            ["FP16 dense / GPU", "989 TFLOPS", "2,250 TFLOPS", "공개 값 (원문 검증 필요)"],
            ["Custom HBM (ScHBM)", "160 GiB, 내부 6.7 TB/s, 외부 63 GB/s, 지연 2 µs", "384 GiB, 내부 16 TB/s, 외부 63 GB/s", "신규 메모리: 세대 없음, host link 속도만 다름 [ASSUMED]"],
            ["CXL-PNM", "512 GiB, 내부 400 GB/s, 외부 63 GB/s, 지연 300 ns", "같음", "신규 메모리 [ASSUMED]"],
            ["DRAM", "DDR5-4800, 1 TiB, 내부 300 GB/s, 외부 64 GB/s", "DDR5-6400, 내부 400 GB/s", "호스트 메모리 [PUBLIC]"],
            ["HBF", "2 TiB, 읽기 1 TB/s(GPU 직결), 쓰기 50 GB/s, 지연 5 µs", "같음", "신규 메모리, link와 무관 [ASSUMED]"],
            ["SSD-PIM", "16 TiB, 외부 16 GB/s, 내부 200 GB/s, 지연 60 µs", "같음 (NVMe PCIe 5.0 x4)", "신규 메모리 [ASSUMED]"]]
    B.table(s, 0.4, 1.3, [1.9, 4.2, 3.2, 3.23], rows, size=8.5, row_h=0.42, align=["l", "l", "l", "l"], bold_first_col=True)
    B.blocks(s, ["시스템 구성: 노드 1대 = 8-GPU(NVLink 도메인 1개). 6종 메모리(HBM, ScHBM, CXL-PNM, DRAM, HBF, SSD-PIM)가 모든 profile에 있다. 모델 Llama-3.1-70B BF16, KV 320 KiB/token.",
                 "신규 메모리 스펙: 실물이 없어 vendor·문헌 값과 가정으로 정했다. 신규 메모리에는 과거 세대가 없어 같은 장치를 모든 플랫폼에 쓰고 host link 속도만 바꾼다(link-bound scaling).",
                 "Interconnect: host PCIe 5.0 x16 63 GB/s(방향당), CXL 2.0. ScHBM의 외부 BW는 host link 1가닥을 도메인 전체가 공유한다. HBF는 GPU 직결(UCIe)이라 link와 무관. 노드 간 RDMA 50 GB/s [ASSUMED, DP2만]."],
             ["시뮬레이터: DP1 = 객체 이동 정책 시뮬레이터, DP2 = P/D 노드 사이 스케줄링, DP3 = 요청 단위 GPU timeline(적재 → prefill → decode). 서비스 시간 = 바이트 ÷ 대역폭 + 지연, tier별 FIFO.",
              "모든 평가는 seed ≥ 5, load sweep, Baseline-regression loop를 따른다. 시스템 profile 값은 결과를 보고 바꾸지 않았다.",
              "한계: 신규 메모리 값은 가정이고, A100/H100/B200 수치도 원문 검증을 못 했다. PCIe 6.0 raw 값, cxl_pnm FP16 = FP32 × 2 가정이 결과를 바꿀 수 있다."],
             y=4.75, h=2.25, lt="무엇을 어떻게 가정했나", rt="시뮬레이션 방식과 한계", size=9)
    add(s)
    return new


def move_after(prs, slides, after_index):
    lst = prs.slides._sldIdLst
    ids = list(lst)
    n_orig = len(ids) - len(slides)
    news = ids[n_orig:]
    for el in news:
        lst.remove(el)
    for k, el in enumerate(news):
        lst.insert(after_index + 1 + k, el)


# ------------------------------------------------------------------ main
def main(src, dst):
    inp = U.load()
    res = U.evaluate(inp)
    prs = Presentation(src)
    tpl_slide = prs.slides[2]   # DP1 tradeoff cell with the star/value run structure
    tpl = tradeoff_table(tpl_slide).cell(4, 2)._tc.txBody.findall(qn("a:p"))[0]

    # --- DP2 slide (6): fill tradeoff
    t = tradeoff_table(prs.slides[5])
    for col, c in ((2, "C1"), (4, "C2")):
        v = inp["DP2"]["values"][c]
        st = res["DP2"][c]
        q = v["qa4"]
        fill_value_cell(t.cell(4, col), tpl, [
            (S(st["QA1"]), f"{v['qa1_tps']:,}(x{v['qa1_ratio']:.2f})", None),
            (S(st["QA2"]), f"{v['ttft_p99_ms']:,}(x{v['ttft_p99_ms']/inp['DP2']['baseline']['ttft_p99_ms']:.2f}), {v['tpot_p99_ms']}(x{v['tpot_p99_ms']/inp['DP2']['baseline']['tpot_p99_ms']:.2f})", "FF0000"),
            (S(st["QA4"]), f"${q['usd_t2']:.2f}, {q['mm']:.2f}, {q['modules']:.2f}", None)])
    for idx in (5, 7):
        cols = tradeoff_table(prs.slides[idx]).columns
        for c, w in zip(cols, (0.96, 3.51, 2.44, 3.71, 2.24)):
            c.width = Inches(w)
    # --- DP3 slide (8): stars and values from the simulation
    t = tradeoff_table(prs.slides[7])
    sm = json.load(open(U.EVAL / "DP3" / "results" / "data" / "dp3_summary.json"))["aggregate"]
    for col, c, pol in ((2, "C1", "C1-Offline"), (4, "C2", "C2-Online")):
        v, st = inp["DP3"]["values"][c], res["DP3"][c]
        l3 = (S(st["QA5"]), f"F1 하락 {v['f1_drop_pct']:.1f}%", None) if "QA5" in st else ("미평가", "(F1 측정 중)", "7F7F7F")
        fill_value_cell(t.cell(4, col), tpl, [
            (S(st["QA2"]), f"{v['ttft_p99_ms']:,.0f}(x{1/sm[pol]['ttft']['ratio_gm']:.2f}), {v['tpot_p99_ms']:.1f}(x{1/sm[pol]['tpot']['ratio_gm']:.2f})", "FF0000"),
            (S(st["QA3"]), f"{v['hbm_gib']:.1f}(x{1/v['qa3_ratio']:.2f})", None),
            l3])

    # --- DP1 slides (3, 4): QA4 line + label order
    for idx in (2, 3):
        t = tradeoff_table(prs.slides[idx])
        for col, c in ((2, "C1"), (4, "C2")):
            q = inp["DP1"]["values"][c]["qa4"]
            p = t.cell(4, col).text_frame.paragraphs[3]
            runs = p.runs
            runs[-1].text = f"${q['usd_t2']:.2f}, {q['mm']:.2f}, {q['modules']:.2f}"
        for col in (1, 3):
            p = t.cell(4, col).text_frame.paragraphs[3]
            r = p.runs
            if len(r) == 4:   # 'Modifiability ', '(module, M/M, ', '토큰 비용', ')'
                r[1].text, r[2].text = "(토큰 비용, M/M, ", "모듈 수"
            else:             # 'Modifiability (module, M/M, ', '토큰 비용', ')'
                r[0].text, r[1].text = "Modifiability (토큰 비용, M/M, ", "모듈 수"
    # --- DP1 C2 QA1 star (v2: 2.0 bound) and C1 ratio shown with 3 decimals
    for idx in (2, 3):
        t = tradeoff_table(prs.slides[idx])
        t.cell(4, 4).text_frame.paragraphs[0].runs[0].text = S(res["DP1"]["C2"]["QA1"])
    t = tradeoff_table(prs.slides[3])
    t.cell(4, 2).text_frame.paragraphs[0].runs[2].text = "436(x1.298)"
    # --- DP4 slide (10): QA4 line unified basis
    t = tradeoff_table(prs.slides[9])
    for col, c in ((2, "C1"), (4, "C2")):
        q = inp["DP4"]["values"][c]["qa4_equal"]
        p = t.cell(4, col).text_frame.paragraphs[2]
        txt = f"${q['usd_t2']:.2f}, {q['mm']:.2f}, {q['modules']:.1f}"
        rs = p.runs
        rs[-1].text = txt
        for r in rs[2:-1]:
            r.text = ""

    # --- banners on superseded per-DP criteria slides
    layout = [l for l in prs.slide_layouts if l.name == "빈 화면"][0]
    B = Builder(prs, layout)
    def banner(slide, text, y=1.13):
        B.tb(slide, 0.4, y, 12.5, 0.24, [(text, dict(bold=True, color=RED, size=8.5))], name="banner")
    banner(prs.slides[12], "※ 공통 별 기준 v2: DP1 C2 QA1은 ×1.42 < 2.0이라 ★★(합계 8). QA2 별은 A·R 평균으로 바뀌었고 DP1 별은 그대로. C1 합계 10 불변.")
    banner(prs.slides[18], "※ 공통 별 기준 v2에서 대체됨: QA1 ★★★ 경계 1.30 → 2.0 (DP1 C2 ★★★ → ★★). ★★ 하한 0.97은 같다.")
    banner(prs.slides[19], "※ 공통 별 기준 v2에서 대체됨: QA2 = 절대 SLO 등급 A와 개선 등급 R(r ≥ 1.20 / 0.90)의 평균. 이 장의 개선 배수는 R로 쓴다.")
    banner(prs.slides[20], "※ 공통 별 기준 v2 QA3과 같은 기준이다(감소 배수 1.25/0.95). 정의를 '평균 KV 크기'로 풀어 썼다. 기존 별 그대로.")
    banner(prs.slides[21], "※ 공통 별 기준 v2에서 대체됨: 점수 S = 0.5×비용/$0.5 + 0.3×공수/0.5MM + 0.2×module/2 (★★★ ≤ 1.0, ★★ ≤ 3.2). DP1 별 그대로.")
    banner(prs.slides[26], "※ 공통 별 기준 v2에서 대체됨: QA1 경계는 0.97/2.0(이 장의 0.90/1.10 대신). 이 PPT의 Q1 = 공통 QA1. DP4 별 그대로.")
    banner(prs.slides[27], "※ 공통 별 기준 v2에서 대체됨: 이 장의 절대 SLO 등급이 A이고 Baseline 대비 개선 R과 평균. Q2 = 공통 QA2. DP4 별 그대로.")
    banner(prs.slides[28], "※ 공통 별 기준 v2에서 대체됨: 우선순위 규칙 대신 점수 S, 공수는 MM(man-day ÷ 21), 단순 평균. Q3 = 공통 QA4. DP4 별 그대로.")
    banner(prs.slides[30], "※ 공통 별 기준 v2 QA6과 같은 기준이다(SE 90/70, N_max=16). 이 PPT의 Q4 = 공통 QA6. 기존 별 그대로.")

    # --- unified section after the Appendix divider (slide 11)
    new = build_slides(prs, res, inp)
    move_after(prs, new, 10)
    prs.save(dst)
    print("saved", dst, len(prs.slides._sldIdLst), "slides; new:", len(new))


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
