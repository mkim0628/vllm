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
    s = B.frame("공통 별 기준 v3 — 모든 DP에 같은 QA는 같은 기준", "QA마다 metric 계산식 → ★ 기준 → 근거 · QA2는 Baseline 대비 개선 + SLO 초과 시 ★ · QA3는 Baseline 대비 감소 배수 · QA4는 세 지표 AND 조건 · proposal (소유자 확정 전)",
                "※ 근거 문서: doc-mk/Evaluation/qa-star-criteria-unified.md · 별 계산: tools/unified_stars.py (값과 출처는 tools/unified_inputs.json, HBM 점유 비율은 tools/hbm_share.json)")
    rows = [["QA", "metric (같은 DP의 Baseline 대비 또는 절대 SLO)", "★★★", "★★", "★", "적용 DP"],
            ["QA1 처리량", "R = Max SLO goodput ÷ Baseline (쌍별 기하평균)", "R ≥ 4/3 (≈1.33)", "0.97 ≤ R < 4/3", "R < 0.97", "DP1 · DP2 · DP3 · DP4"],
            ["QA2 지연", ["r = √(Baseline TTFT P99 ÷ 후보 TTFT P99 × Baseline TPOT P99 ÷ 후보 TPOT P99)", "(r > 1이면 좋아짐) · TTFT P99 > 2 s 또는 TPOT P99 > 50 ms이면 r과 상관없이 ★로 강등"], "r ≥ 1.20", "0.90 ≤ r < 1.20", "r < 0.90 또는 SLO 초과", "DP1 ~ DP4"],
            ["QA3 자원", ["HBM에 올라간 AI Data(KV·LoRA·MoE expert·RAG 인덱스·Agent memory 등)의 시간 평균 GiB → 감소 배수 = Baseline ÷ 후보", "(표기: HBM 용량 대비 점유 비율 %도 병기)"], "배수 ≥ 1.25", "0.95 ≤ 배수 < 1.25", "배수 < 0.95", "DP1 · DP2 · DP3"],
            ["QA4 변경 용이성", ["세 지표를 각각 판정하고 셋이 모두 만족해야 그 별 (AND)", "① 토큰 비용(mid tier $/변경) ② 공수(MM/변경) ③ 변경 module 수"], "① ≤ $0.5 그리고 ② ≤ 0.5 그리고 ③ ≤ 2", "① ≤ $2 그리고 ② ≤ 1.0 그리고 ③ < 6", "그 밖 (하나라도 ★★ 기준을 넘음)", "DP1 · DP2 · DP4"],
            ["QA5 기능 정확성", "F1 상대 하락 (압축 전 + full recompute 대비)", "≤ 1%", "≤ 3% (제안)", "> 3%", "DP3"],
            ["QA6 확장성", "SE(N_max=16) = Goodput(N) ÷ ((N/N0) × Goodput(N0)), N0=2", "≥ 90%", "70 ~ 90%", "< 70%", "DP4"]]
    fills = {i: ["EAF0FA", None, "E2EFDA", "FFF2CC", "FBE5D6", None] for i in range(1, 7)}
    t = B.table(s, 0.4, 1.3, [1.35, 4.7, 1.8, 1.8, 1.5, 1.38], rows, size=9, row_h=0.46, fills=fills, bold_first_col=True)
    for i, h in ((2, 0.7), (3, 0.62), (4, 0.78)):
        t.rows[i].height = Inches(h)
    B.blocks(s, ["같은 QA는 DP와 무관하게 같은 metric·집계·경계를 쓴다. DP마다 다른 것은 후보와 시나리오(공통 + DP 전용)뿐이다.",
                 "경계마다 근거를 달았다: 측정(잡음 폭), 환산(자원·시간), 표준·문헌, 정책 선택을 구분해 적었다.",
                 "QA2: Baseline보다 나빠지면(r < 0.90) 절대 SLO를 지켜도 ★, SLO를 넘으면 개선 폭과 무관하게 ★다.",
                 "QA4: 세 지표 중 하나라도 한 단계 낮으면 전체가 그 단계다. 별 합계가 높은 후보를 선택하고 동점일 때만 QA 우선순위를 쓴다."],
             ["QA3의 기준은 Baseline 대비 감소 배수이고, 용량 대비 점유 비율(%)은 병기하는 참고 값이다(DP별 용량 구성이 달라 DP 간 비교용이 아님).",
              "QA5의 두 번째 경계(3%)는 데이터로 도출하지 못한 제안값이다.",
              "시뮬레이션 [B+C]와 Baseline 실측 + 시뮬레이션 [A+C]를 같은 표에 쓴다. 근거 수준은 별과 분리해 표기한다."],
             y=5.35, h=1.65, lt="원칙", rt="주의", size=9)
    add(s)

    def crit(title, subtitle, rows, left, right, foot, src, lt="지표와 이전 기준"):
        s = B.frame(title, subtitle, foot, src)
        B.stars_table(s, rows)
        B.blocks(s, left, right, 4.2, 2.8, lt=lt, size=10.5)
        add(s)

    # ---------------------------------------------------------------- QA1
    crit("QA1 처리량 — 공통 별 기준", "R = Max SLO goodput(output tok/s) ÷ 같은 DP Baseline · 시나리오 쌍별 비율의 기하평균 · SLO = TTFT P99 ≤ 2 s, TPOT P99 ≤ 50 ms",
         [["★★★", "R ≥ 4/3 (≈ 1.33)", "같은 수요를 75% 이하의 서버로 처리 = 서버 4대 중 1대가 필요 없다(자원 25% 절감). 새 메모리 HW와 스케줄링 복잡도를 정당화할 최소 규모로 둔 환산 값", "환산 [C], 정책 선택"],
          ["★★", "0.97 ≤ R < 4/3", "하한 0.97 = Baseline끼리 seed 묶음을 바꿔 비교한 20회 집계 범위 0.968~1.033의 아래 끝. 그 안은 잡음이라 열세로 보지 않는다", "측정 [B+C], DP1 star_basis.py"],
          ["★", "R < 0.97", "잡음 대역 밖의 열세: Baseline보다 느리다", "측정 [B+C]"]],
         ["이전: DP1·DP2 0.97/1.30, DP4 0.90/1.10(공통 룰 §4.3). 통합: 0.97/4/3.",
          "결과: DP1 C1 ×1.298(★★) · C2 ×1.423(★★★), DP2 ×1.66 · ×1.66(★★★), DP4 ×1.05 · ×1.04(★★).",
          "DP1 보완 버전(C1 + Affinity)은 436 ÷ 336 = ×1.2976이다. '×1.3'으로 반올림해 적었지만 판정 값은 소수 값이라 ★★다. 문서와 PPT에는 ×1.298로 쓴다."],
         ["상위 구간의 차이가 별에 보이는 해상도는 4/3 근처에서 가장 크다. DP4는 ×1.04~1.05로 모두 ★★ 하위에 있다.",
          "DP4는 Baseline이 실측이지만 재측정 잡음 폭을 아직 재지 않았다. 0.97은 시뮬레이터의 잡음 폭이다.",
          "DP2의 ×1.66은 Baseline이 SLO를 거의 못 지키는 시나리오가 끌어올린다."],
         "※ 공통 별점(0.90/1.10)은 필요하면 병기한다. 다른 기준 계열의 영향은 qa-star-criteria-unified.md §7.",
         "출처: DP1/qa-criteria-dp1.md §A·§J · DP1/sim/star_basis.py · tools/unified_stars.py")

    # ---------------------------------------------------------------- QA2
    s = B.frame("QA2 지연 — 공통 별 기준", "Baseline 대비 개선(r)으로 별을 매기고, 절대 SLO(TTFT P99 2 s, TPOT P99 50 ms)를 넘으면 ★로 강등 · TTFT P99·TPOT P99의 시나리오 쌍별 기하평균",
                "※ MLPerf 표준 값은 2차 자료다. 출처 링크는 PPT DP4 28장·34장과 같다.",
                "출처: 공통 QA 문서 §5 · MLPerf Inference v5.1 요약(marktechpost, it-online) [2차] · Brysbaert 2019 · DP3 시뮬레이션 seed 분산 · tools/unified_stars.py")
    B.tb(s, 0.4, 1.25, 8.2, 0.3, [("r = √[ (Baseline TTFT P99 ÷ 후보 TTFT P99) × (Baseline TPOT P99 ÷ 후보 TPOT P99) ]  (> 1이면 좋아짐)", dict(bold=True, color=NAVY, size=10))], name="r_formula")
    tR = [["별", "기준", "근거"],
          ["★★★", "r ≥ 1.20 그리고 SLO 충족", "잡음 폭(±10%)의 2배 = 확실한 개선 (정책 선택)"],
          ["★★", "0.90 ≤ r < 1.20 그리고 SLO 충족", "잡음 안 = Baseline과 동등. 단일 시나리오 P99 비율은 5 seed에서 ±15% 흔들리고 30여 쌍 평균은 약 ±3% (DP3 64개 비교의 CI 반폭 중앙값 14.7%)"],
          ["★", "r < 0.90, 또는 SLO 초과(TTFT P99 > 2 s 또는 TPOT P99 > 50 ms)", "r < 0.90은 잡음 밖의 열세. SLO 초과는 개선 폭과 무관하게 강등"]]
    B.table(s, 0.4, 1.6, [0.9, 3.4, 3.9], tR, size=9, row_h=0.62, fills={1: [FILL[3]] * 3, 2: [FILL[2]] * 3, 3: [FILL[1]] * 3}, align=["c", "l", "l"])
    tS = [["절대 SLO", "근거"],
          ["TTFT P99 ≤ 2 s", "8K prefill 이론 0.32 s(H100×8, MFU 0.45)의 약 6배(큐잉 여유). MLPerf Llama-2-70B 표준 시나리오와 같은 자릿수"],
          ["TPOT P99 ≤ 50 ms", "50 ms = 20 tok/s는 성인 묵독(약 5~6 tok/s)의 약 3.5배. MLPerf interactive 40 ms와 표준 200 ms 사이"]]
    B.table(s, 0.4, 4.45, [1.6, 6.6], tS, size=9, row_h=0.5, align=["l", "l"])
    rows = [["후보", "TTFT P99 / TPOT P99", "r", "QA2"]]
    for dp, c, lab in (("DP1", "C1", "DP1 C1"), ("DP1", "C2", "DP1 C2"), ("DP1-1안", "C1", "DP1 1안"), ("DP2", "C1", "DP2 C1"), ("DP2", "C2", "DP2 C2"), ("DP4", "C1", "DP4 후보1"), ("DP4", "C2", "DP4 후보2"), ("DP3", "C1", "DP3 C1"), ("DP3", "C2", "DP3 C2")):
        v = inp[dp]["values"][c]
        r = U.qa2_ratio(inp[dp], v)
        slo = "" if U.qa2_slo_ok(v["ttft_p99_ms"], v["tpot_p99_ms"]) else " ⚠"
        rows.append([lab, f"{v['ttft_p99_ms']:,.0f} ms{slo} / {v['tpot_p99_ms']:.1f} ms", f"{r:.2f}", S(res[dp][c]["QA2"])])
    B.table(s, 8.8, 1.25, [1.0, 1.9, 0.5, 0.75], rows, size=8.5, row_h=0.3, align=["l", "c", "c", "c"])
    B.tb(s, 8.8, 4.35, 4.1, 0.25, [("⚠ = 절대 SLO 초과(★로 강등)", dict(size=8.5, color=RED))], name="legend")
    B.blocks(s, ["이전(v1·v2)은 절대 SLO 등급을 별에 섞었다. v3는 Baseline 대비 개선으로 별을 정하고 절대 SLO는 넘으면 ★로 강등하는 조건으로만 쓴다.",
                 "이전: DP4 절대 SLO, DP1·DP2 6개 지표 개선 배수 geomean. r은 P99 두 지표만 쓴다(DP4가 P99만 보고)."],
             ["DP4 후보1은 TTFT P99 2,060 ms가 2 s를 3% 넘어 개선 r = 1.11인데도 ★다. 경계 근처에서 별이 한 번에 두 단계 바뀌는 구조(절벽)다.",
              "DP1 C1은 r = 0.948로 하한 0.90까지 +5% 남았다. DP1에서 C2가 C1보다 모든 지연 지표(P50·P99)에서 낫다."],
             y=5.65, h=1.35, lt="규칙의 의미", rt="주의", size=8.5)
    add(s)

    # ---------------------------------------------------------------- QA3
    hs = json.load(open(HERE / "hbm_share.json"))
    crit("QA3 자원 (HBM 사용량) — 공통 별 기준", "기준 = Baseline 대비 감소 배수(Baseline ÷ 후보) · PPT에는 HBM 용량 대비 점유 비율(%)을 병기 · 성능은 섞지 않는다 · DP1·DP2·DP3 적용",
         [["★★★", "감소 배수 ≥ 1.25", "HBM 점유 20% 감소 = DP1 평균 146.6 GiB 중 약 29 GiB(8K KV object 약 1.6개분). QA2와 같은 '눈에 띄는 개선' 크기로 둔 정책 선택", "환산 [C]"],
          ["★★", "0.95 ≤ 감소 배수 < 1.25", "하한 0.95: Baseline끼리 비교한 점유 잡음 범위 0.984~1.016보다 느슨하게 둠(5% 이내 증가는 열세로 보지 않음)", "측정 [B+C]"],
          ["★", "감소 배수 < 0.95", "HBM을 5% 넘게 더 쓴다(잡음 밖)", "측정 [B+C]"]],
         ["측정하는 것(쉬운 말): 모델이 돌아가는 동안 HBM에 올라와 있는 AI Data(KV, LoRA adapter, MoE expert, RAG 인덱스, Agent memory 등)의 평균 크기. 측정 구간 동안 HBM의 양을 계속 재서 시간으로 평균낸다(순간 최대 아님). 모델 가중치·활성값은 뺀다. DP1은 이 모든 종류를 잰다. DP2·DP3는 후보가 바꾸는 데이터가 KV뿐이라 KV만 잰다(다른 종류는 고정 배치).",
          "예: 100초 중 40초는 100 GiB, 60초는 50 GiB → (40×100 + 60×50) ÷ 100 = 70 GiB. 감소 배수 3.0이면 HBM을 1/3만 쓴다.",
          "PPT 표기: GiB, (HBM KV 용량 대비 점유 %, Baseline 대비 감소 배수). 용량 대비 비율은 시나리오·시스템별 비율의 기하평균이다.",
          f"DP1: C1 {hs['DP1']['C1']['gib']:.1f} GiB(용량의 {hs['DP1']['C1']['share']*100:.0f}%, ×{hs['DP1']['Baseline']['gib']/hs['DP1']['C1']['gib']:.2f}) · C2 {hs['DP1']['C2']['gib']:.1f} GiB({hs['DP1']['C2']['share']*100:.0f}%, ×{hs['DP1']['Baseline']['gib']/hs['DP1']['C2']['gib']:.2f}) · Baseline {hs['DP1']['Baseline']['share']*100:.0f}%. DP3: C1 {hs['DP3']['C1']['gib']:.1f} GiB({hs['DP3']['C1']['share']*100:.0f}%, ×{hs['DP3']['Baseline']['gib']/hs['DP3']['C1']['gib']:.2f}) · C2 {hs['DP3']['C2']['gib']:.1f} GiB({hs['DP3']['C2']['share']*100:.0f}%, ×{hs['DP3']['Baseline']['gib']/hs['DP3']['C2']['gib']:.2f}) · Baseline {hs['DP3']['Baseline']['share']*100:.0f}%."],
         ["DP3 C2의 ×1.26은 경계 1.25에서 +0.7%다. H100만 보면 1.34, B200만 보면 1.20이라 시스템 선택에 따라 ★★/★★★이 갈린다.",
          "DP1은 QA3 정의를 결과를 본 뒤 여러 번 바꿨다(활용률 → 풀 U → 성능÷비용 → HBM 사용량).",
          "'비우되 성능이 나빠지는 정책'이 유리하므로 QA1·QA2와 함께 읽어야 한다. 용량 대비 비율은 DP별 용량 정의가 달라 DP 간 비교용이 아니다."],
         "※ 용량 대비 비율: DP1 = tier_util.hbm(시나리오 HBM 배율 반영 유효 용량), DP3 = HBM 가용(0.9)에서 가중치를 뺀 KV 몫, DP2 = 노드 HBM KV 풀(hbm_frac).",
         "출처: DP1/qa-criteria-dp1.md §A·§I·§J · DP1/sim/simulator.py(occ_bytes_sum) · DP3/sim/dp3sim.py · tools/hbm_share.py",
         lt="무엇을 재는가 (이전 기준 포함)")

    # ---------------------------------------------------------------- QA4
    s = B.frame("QA4 변경 용이성 — 공통 별 기준", "세 지표를 각각 판정하고 셋이 모두(AND) 그 별의 기준을 만족해야 그 별 · 한 지표라도 낮으면 전체가 낮은 쪽 · 변경 시나리오 단순 평균에 적용",
                "※ 공수·비용은 구현 측정(module·LOC)에 가정 상수를 곱한 값이며 실제 에이전트 세션 측정이 아니다 [B+C]. 1 MM = 21 man-day, 비용은 mid tier($3/$15 per MTok).",
                "출처: DP1/qa4-preregistration.md · DP4 평가 장(토큰 비용 경계) · 공통 QA 문서 §7 · tools/unified_stars.py")
    t1 = [["별", "① 토큰 비용 ($/변경, mid tier)", "② 개발 공수 (MM/변경)", "③ 변경 module 수", "조건"],
          ["★★★", "≤ $0.5", "≤ 0.5", "≤ 2 (주요 interface 유지)", "①②③ 모두 ★★★ 기준 이내"],
          ["★★", "≤ $2", "≤ 1.0", "3 ~ 5 (2 초과 6 미만)", "①②③ 모두 ★★ 기준 이내 (하나라도 ★★★ 밖)"],
          ["★", "> $2", "> 1.0", "≥ 6 또는 major interface 변경", "①②③ 중 하나라도 ★★ 기준 밖"]]
    B.table(s, 0.4, 1.3, [0.8, 2.6, 2.2, 2.6, 4.33], t1, size=9.5, row_h=0.4, fills={1: [FILL[3]] * 5, 2: [FILL[2]] * 5, 3: [FILL[1]] * 5}, align=["c", "l", "l", "l", "l"])
    t2 = [["경계", "근거", "확인 수준"],
          ["① 비용 $0.5 / $2", "$0.5 = 원본 약 25k 토큰(module 약 3개 읽기 + 소규모 수정)을 한 세션에서 재작업 없이 끝내는 비용(유효 입력 재과금 6배, $3/$15 가정). $2는 그 4배 = 다중 세션·외부 코드 탐색", "사전 등록 가정 (DP4 pre-reg). 단가는 2차 자료"],
          ["② 공수 0.5 / 1.0 MM", "0.5 MM = 엔지니어 1명이 2주 sprint 안에 흡수. 1 MM = 한 달 전담이면 로드맵 항목", "사전 등록 가정 (DP1 qa4-preregistration)"],
          ["③ module 2 / 6", "공통 룰 §7", "공통 룰"]]
    B.table(s, 0.4, 3.0, [1.5, 4.6, 1.6], t2, size=8.5, row_h=0.62, align=["l", "l", "l"])
    rows = [["후보", "① 비용", "② 공수", "③ module", "①/②/③ sub-star", "QA4"]]
    names = {"DP1": ("DP1 C1", "DP1 C2"), "DP4": ("DP4 후보1", "DP4 후보2")}
    for dp in ("DP1", "DP4"):
        for k, c in enumerate(("C1", "C2")):
            q = inp[dp]["values"][c].get("qa4") or inp[dp]["values"][c]["qa4_equal"]
            a, b2, m = U.qa4_subs(q["usd_t2"], q["mm"], q["modules"])
            rows.append([names[dp][k], f"${q['usd_t2']:.2f}", f"{q['mm']:.2f}", f"{q['modules']:.2f}", f"{S(a)} / {S(b2)} / {S(m)}", S(res[dp][c]["QA4"])])
    B.table(s, 8.3, 3.0, [1.0, 0.65, 0.6, 0.7, 1.15, 0.55], rows, size=8.5, row_h=0.34, align=["l", "c", "c", "c", "c", "c"])
    B.blocks(s, ["예: 비용 $0.4, 공수 0.3 MM, module 4 → ③이 ★★이므로 전체 ★★. 비용 $0.4, 공수 0.3, module 2 → 전체 ★★★.",
                 "이전(v2)의 가중 점수는 지표 하나가 아주 나빠도 다른 지표가 0에 가까우면 ★★★이 가능했다. AND 조건은 그 경우를 막는다."],
             ["DP4 후보2는 module 2.30이 ★★★ 경계 2를 넘어 ★★이다(비용 $0.48, 공수 0.15 MM은 ★★★). DP4의 시나리오 가중(S2~S4 ×2, module 1.9)을 쓰면 ★★★이다. 지금은 DP1·DP2와 같은 단순 평균을 쓴다.",
              "DP1 C2는 공수 0.51 MM이 경계 0.5를 근소하게(2%) 넘어 ★★다. 비용·공수·module을 하나의 비중으로 합치지 않으므로 우선순위(토큰 비용 > 공수 > module)는 별에 반영되지 않는다."],
             y=5.2, h=1.8, lt="규칙", rt="주의", size=9.5)
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
    s = B.frame("적용 결과 — 정합성 점검 (공통 기준 v3)", "기존 별과 비교 · QA1 4/3, QA2 개선 + SLO 강등, QA4 AND 조건 · DP2는 노드 내 결정 평가(QA1~QA4) · DP3는 QA1 추가",
                "※ DP2·DP3·DP4는 선정 QA만 합산했다(DP2 QA1~QA4, DP3 QA1·QA2·QA3·QA5). DP4는 현 DP4(요청 조율)이며 근거는 PPT 26~31장이다. DP3 QA5는 소형 모델 실측 매핑이다.")
    nm = {"DP1": ("DP1 C1 자원 상태 기반", "DP1 C2 AI Data 특성 기반"), "DP2": ("DP2 C1 스케줄링 시점", "DP2 C2 사전 계획"), "DP4": ("DP4 후보1 OSS 확장", "DP4 후보2 자체 구현"),
          "DP3": ("DP3 C1 Offline", "DP3 C2 Online")}
    rows = [["DP · 후보", "QA1", "QA2", "QA3", "QA4", "QA5", "QA6", "합계 v3", "기존 합계", "선택"]]
    for dp in ("DP1", "DP2", "DP4", "DP3"):
        w, tot, how = U.select(dp, res)
        for k, c in enumerate(("C1", "C2")):
            st = res[dp][c]
            prev = sum(inp[dp]["previous_stars"][c].values()) if inp[dp].get("previous_stars", {}).get(c) else None
            rows.append([nm[dp][k]] + [S(st[q]) if q in st else "—" for q in ("QA1", "QA2", "QA3", "QA4", "QA5", "QA6")] + [str(sum(st.values())), str(prev) if prev else "—",
                         (f"{nm[dp][0 if w == 'C1' else 1].split(' ', 1)[0]} {w} ({how})" if w else how) if k == 0 else ""])
    st1 = res["DP1-1안"]["C1"]
    rows.append(["(참고) DP1 1안 Affinity 없음"] + [S(st1[q]) if q in st1 else "—" for q in ("QA1", "QA2", "QA3", "QA4", "QA5", "QA6")] + [str(sum(st1.values())), "9", "보완 전"])
    B.table(s, 0.4, 1.3, [2.6, 0.95, 0.95, 0.95, 0.95, 0.95, 0.95, 0.85, 0.85, 2.53], rows, size=9, row_h=0.31, align=["l", "c", "c", "c", "c", "c", "c", "c", "c", "l"])
    B.blocks(s, ["DP1: C1 10 → 9, C2 9 → 9로 동점이 되어 QA 우선순위(QA1)에서 C2가 앞선다. 이전에는 C1(합계 10 대 9)이었다.",
                 "DP4: 후보1 8, 후보2 7(QA2 후보1 ★, 후보2 ★★, QA4 후보2 ★★). 합계로 후보1이 앞선다. 이전에는 동점에서 후보2였다.",
                 "DP2: 한 노드 안의 결정 평가로 바꾸고 QA1~QA4를 쓴다(합계 9 대 8, 1안). DP3: QA1(처리량)을 추가해 C1 10 대 C2 9."],
             ["선택이 바뀌는 DP가 있다(DP1 C1→C2, DP4 후보2→후보1). 원인은 QA1 경계 4/3(C2가 ★★★), QA2의 SLO 강등(DP4 후보1 TTFT 2,060 ms), QA4 AND 조건(DP4 후보2 module 2.30)이다.",
              "DP4 QA2는 TTFT 2 s 경계를 3% 넘은 것이 별 두 단계 차이를 만든다. DP4 시나리오 가중(S2~S4 ×2)을 쓰면 후보2 QA4가 ★★★이 되어 8 대 8, QA2 우선순위에서 후보2가 앞선다.",
              "DP4 QA1·QA2·QA6의 Baseline은 실측이지만 후보는 시뮬레이터·추정이다 [A+C]. DP1·DP2·DP3은 시뮬레이션 [B+C]다."],
             y=4.75, h=2.25, lt="읽는 법", rt="주의", size=9.5)
    add(s)

    # ---------------------------------------------------------------- DP1 result
    s = B.frame("DP1 평가 결과 — 공통 기준 v3 (H100 + B200 통합)", "C1 자원 상태 기반(+ Data-Memory Affinity) vs C2 AI Data 특성 기반 · 괄호 = 후보 ÷ Baseline(이동 없는 정적 배치) · 비교 가능 21쌍 기하평균 · 시뮬레이션 [B+C]",
                "※ DP1은 Baseline 실측이 없어 모든 값이 [B+C]다. 근거: DP1/results/2026-10-02_dp1-qa-evaluation.md, 별은 tools/unified_stars.py(v3).")
    d1 = inp["DP1"]
    b1, c1v, c2v = d1["baseline"], d1["values"]["C1"], d1["values"]["C2"]
    s1, s2 = res["DP1"]["C1"], res["DP1"]["C2"]
    ra, rb = U.qa2_ratio(d1, c1v), U.qa2_ratio(d1, c2v)
    h1 = hs["DP1"]
    sub = lambda q: "/".join(S(x) for x in U.qa4_subs(q["usd_t2"], q["mm"], q["modules"]))
    slo1 = lambda v: "SLO 충족" if U.qa2_slo_ok(v["ttft_p99_ms"], v["tpot_p99_ms"]) else "SLO 초과 → ★"
    rows = [["QA", "평가 metric (↑/↓ 좋음)", "Baseline (정적 배치)", "C1 자원 상태 기반", "C2 AI Data 특성 기반"],
            ["QA1 처리량", "Max SLO goodput (tok/s) ↑", f"{b1['tps']:,}", f"{S(s1['QA1'])}  {c1v['qa1_tps']:,} (×{c1v['qa1_ratio']:.3f})", f"{S(s2['QA1'])}  {c2v['qa1_tps']:,} (×{c2v['qa1_ratio']:.3f})"],
            ["QA2 지연 (TTFT)", "TTFT P99 (ms) ↓", f"{b1['ttft_p99_ms']:,}", f"{c1v['ttft_p99_ms']:,} (×{c1v['ttft_p99_ms']/b1['ttft_p99_ms']:.2f})", f"{c2v['ttft_p99_ms']:,} (×{c2v['ttft_p99_ms']/b1['ttft_p99_ms']:.2f})"],
            ["QA2 지연 (TPOT)", "TPOT P99 (ms) ↓", f"{b1['tpot_p99_ms']}", f"{c1v['tpot_p99_ms']} (×{c1v['tpot_p99_ms']/b1['tpot_p99_ms']:.2f})", f"{c2v['tpot_p99_ms']} (×{c2v['tpot_p99_ms']/b1['tpot_p99_ms']:.2f})"],
            ["QA2 별점", "개선 r + SLO 강등", "—", f"{S(s1['QA2'])} (r={ra:.2f}, {slo1(c1v)})", f"{S(s2['QA2'])} (r={rb:.2f}, {slo1(c2v)})"],
            ["QA3 자원 (HBM)", "HBM AI Data 시간평균 GiB (용량 대비 %, 감소 배수) ↓", f"{b1['hbm_gib']} GiB (용량의 {h1['Baseline']['share']*100:.0f}%)", f"{S(s1['QA3'])}  {h1['C1']['gib']:.1f} GiB (용량의 {h1['C1']['share']*100:.0f}%, 감소 {h1['Baseline']['gib']/h1['C1']['gib']:.2f}배)", f"{S(s2['QA3'])}  {h1['C2']['gib']:.1f} GiB (용량의 {h1['C2']['share']*100:.0f}%, 감소 {h1['Baseline']['gib']/h1['C2']['gib']:.2f}배)"],
            ["QA4 변경 용이성", "비용($) / 공수(MM) / module — AND 조건", "—", f"{S(s1['QA4'])}  ${c1v['qa4']['usd_t2']:.2f} / {c1v['qa4']['mm']:.2f} / {c1v['qa4']['modules']:.2f} ({sub(c1v['qa4'])})", f"{S(s2['QA4'])}  ${c2v['qa4']['usd_t2']:.2f} / {c2v['qa4']['mm']:.2f} / {c2v['qa4']['modules']:.2f} ({sub(c2v['qa4'])})"],
            ["별 합계", "QA1 + QA2 + QA3 + QA4", "—", f"{sum(s1.values())}", f"{sum(s2.values())}"]]
    B.table(s, 0.4, 1.3, [1.7, 3.1, 1.8, 3.0, 2.93], rows, size=9.5, row_h=0.42, align=["l", "l", "c", "c", "c"], bold_first_col=True)
    w1, tot1, how1 = U.select("DP1", res)
    B.blocks(s, [f"선택: 합계 {tot1['C1']} 대 {tot1['C2']} 동점 → QA 우선순위(QA1 > QA2 > QA3 > QA4)에서 {'C2' if w1 == 'C2' else 'C1'}. C2는 처리량(×1.42)·지연(TTFT P99 ×0.72)이 좋고, C1은 HBM 점유와 변경 용이성이 낫다.",
                 "C2는 데이터별 접근 패턴으로 hot 데이터를 미리 HBM에 올려 TTFT·처리량이 좋다. 대가로 HBM 점유가 62%(C1 50%)이고 이동량(1,339 대 138 GiB)·결정 연산이 크다(부록 해석 장).",
                 "Affinity 없는 C1(1안)은 ×1.054, TTFT ×1.27, 합계 8로 보완 전 버전이다."],
             ["QA1 C1 ×1.298은 ★★★ 경계 4/3(≈1.33) 아래 2.7%, C2 ×1.423은 위 6.7%다. 별 차이가 이 경계에 의존한다.",
              "QA2 C1은 TTFT P99가 Baseline보다 ×1.04 나쁘고(P50은 ×0.44로 좋음) r = 0.95라 ★★다.",
              "QA3는 HBM에 올라간 모든 AI Data(KV·LoRA·MoE·RAG 등)의 평균이다. 비교 가능 21쌍 중 Dynamic 시나리오가 이득을 끌어올리고, 공통 3개는 포화(×1.00)다."],
             y=4.55, h=2.45, lt="읽는 법", rt="정직한 주의", size=9.5)
    add(s)

    # ---------------------------------------------------------------- DP2 result
    s = B.frame("DP2 평가 결과 — 공통 기준 v3 (노드 내 결정, H100 + B200 통합)", "1안 중앙 Dispatcher(스케줄링 시점) vs 2안 Blackboard · 한 노드 안의 결정 · 괄호 = 후보 ÷ Baseline · [B+C]",
                "※ 선정 QA: QA1, QA2, QA3(HBM 점유), QA4(변경 용이성, 소유자 요청으로 추가). 근거: DP2/results/2026-10-10_dp2-arch-styles.md, 별은 tools/unified_stars.py(v3)")
    v1, v2 = inp["DP2"]["values"]["C1"], inp["DP2"]["values"]["C2"]
    b = inp["DP2"]["baseline"]
    q1, q2 = res["DP2"]["C1"], res["DP2"]["C2"]
    r1, r2 = U.qa2_ratio(inp["DP2"], v1), U.qa2_ratio(inp["DP2"], v2)
    h2 = hs["DP2"]
    def hb(c, v, st):
        return f"{S(st['QA3'])}  {v['hbm_gib']:.0f} GiB (용량의 {h2[c]['share']*100:.0f}%, 감소 ×{v['qa3_ratio']:.2f}, {v['hbm_n_eq']}쌍)"
    slo = lambda v: "SLO 충족" if U.qa2_slo_ok(v["ttft_p99_ms"], v["tpot_p99_ms"]) else "TTFT > 2 s → ★"
    rows = [["QA", "평가 metric (↑/↓ 좋음)", "Baseline-GPU-local (vLLM As-Is)", "1안 중앙 Dispatcher", "2안 Blackboard"],
            ["QA1 처리량", "Max SLO goodput (tok/s) ↑", f"{b['tps']:,.0f}", f"{S(q1['QA1'])}  {v1['qa1_tps']:,.0f} (×{v1['qa1_ratio']:.2f}) [B+C]", f"{S(q2['QA1'])}  {v2['qa1_tps']:,.0f} (×{v2['qa1_ratio']:.2f}) [B+C]"],
            ["QA2 지연 (TTFT)", "TTFT P99 (ms) ↓", f"{b['ttft_p99_ms']:,.0f}", f"{v1['ttft_p99_ms']:,.0f} (×{v1['ttft_p99_ms']/b['ttft_p99_ms']:.2f})", f"{v2['ttft_p99_ms']:,.0f} (×{v2['ttft_p99_ms']/b['ttft_p99_ms']:.2f})"],
            ["QA2 지연 (TPOT)", "TPOT P99 (ms) ↓", f"{b['tpot_p99_ms']:.1f}", f"{v1['tpot_p99_ms']:.1f} (×{v1['tpot_p99_ms']/b['tpot_p99_ms']:.2f})", f"{v2['tpot_p99_ms']:.1f} (×{v2['tpot_p99_ms']/b['tpot_p99_ms']:.2f})"],
            ["QA2 별점", "개선 r + SLO 강등", "TTFT > 2 s", f"{S(q1['QA2'])} (r={r1:.2f}, {slo(v1)}) [B+C]", f"{S(q2['QA2'])} (r={r2:.2f}, {slo(v2)}) [B+C]"],
            ["QA3 자원 (HBM)", "HBM KV 시간평균 GiB (용량 대비 %, 감소 배수) ↓", f"{b['hbm_gib']:.0f} GiB (용량의 {h2['Baseline']['share']*100:.0f}%)", hb("C1", v1, q1), hb("C2", v2, q2)],
            ["QA4 변경 용이성", "비용($) / 공수(MM) / module — AND 조건", "—", f"{S(q1['QA4'])}  ${v1['qa4']['usd_t2']:.2f} / {v1['qa4']['mm']:.2f} / {v1['qa4']['modules']:.2f} [B+C]", f"{S(q2['QA4'])}  ${v2['qa4']['usd_t2']:.2f} / {v2['qa4']['mm']:.2f} / {v2['qa4']['modules']:.2f} [B+C]"],
            ["별 합계", "QA1 + QA2 + QA3 + QA4", "—", f"{sum(q1.values())}", f"{sum(q2.values())}"]]
    B.table(s, 0.4, 1.3, [1.9, 3.2, 2.1, 2.8, 2.53], rows, size=9.5, row_h=0.4, align=["l", "l", "c", "c", "c"], bold_first_col=True)
    B.blocks(s, ["1안(스케줄링 시점 결정): 노드 상태(telemetry)와 Cost 모델로 Turn 시작 때 실행 위치를 정한다. HBM 기회비용 항을 포함해 HBM을 덜 쓰고(×1.06 감소) TTFT P99를 줄이며(×0.57) 처리량이 오른다(×1.07).",
                 "대가: TPOT P99가 ×1.34 나빠진다(snapshot 주기 50 ms 사이에 쌓인 부하를 Cost 모델이 못 봄). Cost 추정 오차 σ ≥ 0.4에서는 Baseline 아래로 내려간다.",
                 "2안(Blackboard): 공유 Task Board에 게시하고 Tier agent가 라이브 측정으로 claim. 신호가 없으면 Baseline과 같은 결정을 하고(×1.00), HBM 압박 시 admission이 요청을 큐에 잡아 TTFT 꼬리가 길어진다(×1.15).",
                 "QA1·QA3·QA4는 두 후보가 같은 별이다(QA4 두 후보 ★★★: 2안이 module 1.25 대 1.75, 비용 $0.32 대 $0.39로 더 작다). 후보를 가르는 것은 QA2(1안 ★★, 2안 ★)로 합계 9 대 8이다."],
             ["1안 TTFT P99 1,995 ms는 SLO 2 s를 5 ms 아래다. 경계 바로 아래라 별이 한 번에 두 단계 바뀌는 구간이다(2 s를 넘으면 ★).",
              "trade-off는 별에서는 QA2 하나로만 나뉜다: 1안은 TTFT·HBM·처리량을 얻고 TPOT 꼬리(×1.34 대 ×1.05)를 내며, 2안은 변경이 더 쉽다(별은 같음).",
              "QA3는 SLO 달성률이 Baseline − 1pp 이상인 쌍만 쓴다(1안 20쌍, 2안 14쌍). 별 집계 비교 가능 21쌍, saturated 11쌍.",
              "Cost 추정 오차 σ = 0, telemetry 50 ms, 결정 지연·게시 지연(0.5 ms)은 ASSUMED. KV 외 AI Data(LoRA·MoE)는 고정 배치다."],
             y=4.7, h=2.3, lt="두 구조의 차이", rt="정직한 주의", size=9)
    add(s)

    # ---------------------------------------------------------------- DP3 result
    s = B.frame("DP3 평가 결과 — 시뮬레이션 [B+C] (H100 + B200 통합)", "C1 Offline(Query-agnostic) vs C2 Online(Query-aware) · 괄호 = 후보 ÷ Baseline(As-Is, 전체 KV 재사용) · 비교 가능 32쌍 기하평균 · 사전 등록 후 실행",
                "※ 정확도는 시뮬레이터 밖이다: 소형 모델 eviction 실측(93개) + 매핑 [A 소형 + C]. 근거: DP3/results/2026-10-11_dp3-qa-evaluation.md · DP3/simulation-plan.md(r=0.30, rho=0.15 사전 등록)")
    c1, c2 = D3["values"]["C1"], D3["values"]["C2"]
    b3 = D3["baseline"]
    s1, s2 = res["DP3"]["C1"], res["DP3"]["C2"]
    r1, r2 = U.qa2_ratio(D3, c1), U.qa2_ratio(D3, c2)
    q5c = {c: (f"{S(res['DP3'][c]['QA5'])} F1 하락 {D3['values'][c]['f1_drop_pct']:.1f}%" if q5ok else "측정 중 (표본 부족)") for c in ("C1", "C2")}
    h3 = hs["DP3"]
    def hb3(c, st):
        return f"{S(st['QA3'])}  {h3[c]['gib']:.1f} GiB (용량의 {h3[c]['share']*100:.0f}%, 감소 ×{h3['Baseline']['gib']/h3[c]['gib']:.2f})"
    rows = [["QA", "평가 metric (↑/↓ 좋음)", "Baseline (As-Is)", "C1 Offline", "C2 Online"],
            ["QA1 처리량", "Max SLO goodput (tok/s) ↑", f"{b3['tps']:,.0f}", f"{S(s1['QA1'])}  {c1['qa1_tps']:,.0f} (×{c1['qa1_ratio']:.2f})", f"{S(s2['QA1'])}  {c2['qa1_tps']:,.0f} (×{c2['qa1_ratio']:.2f})"],
            ["QA2 지연 (TTFT)", "TTFT P99 (ms) ↓", f"{b3['ttft_p99_ms']:,.0f}", f"{c1['ttft_p99_ms']:,.0f} (×{1/ag['C1-Offline']['ttft']['ratio_gm']:.2f})", f"{c2['ttft_p99_ms']:,.0f} (×{1/ag['C2-Online']['ttft']['ratio_gm']:.2f})"],
            ["QA2 지연 (TPOT)", "TPOT P99 (ms) ↓", f"{b3['tpot_p99_ms']:.1f}", f"{c1['tpot_p99_ms']:.1f} (×{1/ag['C1-Offline']['tpot']['ratio_gm']:.2f})", f"{c2['tpot_p99_ms']:.1f} (×{1/ag['C2-Online']['tpot']['ratio_gm']:.2f})"],
            ["QA2 별점", "개선 r + SLO 강등", "—", f"{S(s1['QA2'])} (r={r1:.2f}, SLO 충족)", f"{S(s2['QA2'])} (r={r2:.2f}, SLO 충족)"],
            ["QA3 자원 (HBM)", "HBM KV 시간평균 GiB (용량 대비 %, 감소 배수) ↓", f"{h3['Baseline']['gib']:.1f} GiB (용량의 {h3['Baseline']['share']*100:.0f}%)", hb3("C1", s1), hb3("C2", s2)],
            ["QA5 기능 정확성", "F1 상대 하락 (%) ↓", "0 (정의)", q5c["C1"], q5c["C2"]],
            ["별 합계", "QA1 + QA2 + QA3 + QA5", "—", f"{sum(s1.values())}", f"{sum(s2.values())}"]]
    B.table(s, 0.4, 1.3, [1.9, 3.2, 1.9, 2.8, 2.73], rows, size=9.5, row_h=0.37, align=["l", "l", "c", "c", "c"], bold_first_col=True)
    B.blocks(s, ["C1은 HBM을 C2보다 훨씬 적게 쓴다: 압축한 Comp.KV(유지 비율 r = 0.30)만 상주시켜 Baseline의 28%, C2는 80%다. TTFT도 줄인다(28/32쌍).",
                 "C2는 전체 KV를 적재해 상주 객체가 줄지 않고, 점수 계산 뒤 요청의 작업 사본만 줄어든다(HBM ×1.26). TTFT는 Baseline보다 나쁘다(32쌍 중 2쌍만 이김).",
                 "처리량(QA1)도 C1이 낫다(×1.51 대 ×0.99): 압축으로 요청당 적재·attention이 줄어 SLO를 지키는 도착률이 올라간다. 일부 쌍(CB-3 등)은 도착률이 포화에 못 닿아 ×1.00이다.",
                 "정확도는 반대로 C2가 낫다: C2(실제 질의로 점수) F1이 full과 구분되지 않고, C1(대표 질의)은 질의가 멀수록 크게 떨어진다. 이것이 DP3의 trade-off다.",
                 "Baseline이 못 끝내는 시나리오(ST-11, DY-03 H100)에서 C1은 끝낸다."],
             ["HBF처럼 GPU가 직접 읽는 tier(ST-06)에서는 Baseline이 적재 비용 없이 서빙해 C1·C2 모두 TTFT가 ×0.09~0.14로 진다. 선택 재계산이 원인이다.",
              "결과는 유지 비율 r = 0.30 가정에 의존한다. r = 0.5이면 H100에서 C1 TTFT 이득이 사라진다(×0.60).",
              "C1 사전 압축 비용·저장 공간은 모델링하지 않았다(C1에 유리). C2의 선택 복사 비용도 0으로 뒀다(C2에 유리).",
              "QA5는 소형 모델(1.5B)·1.4K token·재계산 없음이라 가정 의존이다. 신뢰구간이 넓다(C1 ±9.5%p)."],
             y=4.5, h=2.5, lt="읽는 법", rt="정직한 주의", size=9)
    add(s)

    # ---------------------------------------------------------------- DP4 result
    s = B.frame("DP4 평가 결과 — 공통 기준 v3 (2노드 × 8 GPU 실측 Baseline + 시뮬레이터)", "후보 1 OSS 확장 vs 후보 2 자체 구현 · 괄호 = 후보 ÷ Baseline · QA1·QA2·QA6 [A+C], QA4 [C]",
                "※ 근거: PPT DP4 26~31장. QA4 값은 변경 시나리오 6개의 단순 평균(DP4 가중 S2~S4 ×2를 쓰면 후보2 module 1.9, 후보2 QA4 ★★★).")
    d4 = inp["DP4"]
    b4 = d4["baseline"]
    k1, k2 = d4["values"]["C1"], d4["values"]["C2"]
    t1_, t2_ = res["DP4"]["C1"], res["DP4"]["C2"]
    ra, rb = U.qa2_ratio(d4, k1), U.qa2_ratio(d4, k2)
    sub4 = lambda q: "/".join(S(x) for x in U.qa4_subs(q["usd_t2"], q["mm"], q["modules"]))
    slo4 = lambda v: "SLO 충족" if U.qa2_slo_ok(v["ttft_p99_ms"], v["tpot_p99_ms"]) else "TTFT > 2 s → ★"
    rows = [["QA", "평가 metric (↑/↓ 좋음)", "Baseline (실측)", "후보 1 OSS 확장", "후보 2 자체 구현"],
            ["QA1 처리량", "Max SLO goodput (tok/s) ↑", f"{b4['tps']:,}", f"{S(t1_['QA1'])}  {k1['qa1_tps']:,} (×{k1['qa1_ratio']:.2f}) [A+C]", f"{S(t2_['QA1'])}  {k2['qa1_tps']:,} (×{k2['qa1_ratio']:.2f}) [A+C]"],
            ["QA2 지연 (TTFT)", "TTFT P99 (ms) ↓", f"{b4['ttft_p99_ms']:,}", f"{k1['ttft_p99_ms']:,} (×{k1['ttft_p99_ms']/b4['ttft_p99_ms']:.2f})", f"{k2['ttft_p99_ms']:,} (×{k2['ttft_p99_ms']/b4['ttft_p99_ms']:.2f})"],
            ["QA2 지연 (TPOT)", "TPOT P99 (ms) ↓", f"{b4['tpot_p99_ms']}", f"{k1['tpot_p99_ms']} (×{k1['tpot_p99_ms']/b4['tpot_p99_ms']:.2f})", f"{k2['tpot_p99_ms']} (×{k2['tpot_p99_ms']/b4['tpot_p99_ms']:.2f})"],
            ["QA2 별점", "개선 r + SLO 강등", "TTFT > 2 s", f"{S(t1_['QA2'])} (r={ra:.2f}, {slo4(k1)}) [A+C]", f"{S(t2_['QA2'])} (r={rb:.2f}, {slo4(k2)}) [A+C]"],
            ["QA4 변경 용이성", "비용($) / 공수(MM) / module — AND 조건", "—", f"{S(t1_['QA4'])}  ${k1['qa4_equal']['usd_t2']:.2f} / {k1['qa4_equal']['mm']:.2f} / {k1['qa4_equal']['modules']:.1f} ({sub4(k1['qa4_equal'])}) [C]", f"{S(t2_['QA4'])}  ${k2['qa4_equal']['usd_t2']:.2f} / {k2['qa4_equal']['mm']:.2f} / {k2['qa4_equal']['modules']:.1f} ({sub4(k2['qa4_equal'])}) [C]"],
            ["QA6 확장성", "SE(N=16) (%) ↑ (N0 = 2)", f"{b4['se16_pct']}%", f"{S(t1_['QA6'])}  {k1['se16_pct']}% [A+C]", f"{S(t2_['QA6'])}  {k2['se16_pct']}% [A+C]"],
            ["별 합계", "QA1 + QA2 + QA4 + QA6", "—", f"{sum(t1_.values())}", f"{sum(t2_.values())}"]]
    B.table(s, 0.4, 1.3, [1.7, 3.1, 1.6, 3.1, 3.03], rows, size=9.5, row_h=0.4, align=["l", "l", "c", "c", "c"], bold_first_col=True)
    w4, tot4, how4 = U.select("DP4", res)
    B.blocks(s, [f"선택: 합계 {tot4['C1']} 대 {tot4['C2']} → {'후보 1' if w4 == 'C1' else '후보 2'}. 후보 2는 결정 hop이 없어 TTFT가 낮고(1,940 ms) 변경 비용이 작지만, 레플리카가 상태를 공유하지 않아 서버 16대에서 SE가 64%로 떨어진다.",
                 "후보 1은 OSS 확장이라 확장성이 좋고(SE 93%) 설정·plugin으로 처리되는 변경(S1·S5·S6)이 싸다. 대가로 P/D 경로 hop 때문에 TTFT가 약 120 ms 높다(가설).",
                 "QA1은 정책이 prefix 재사용을 통제한 공통 부하에서 이득이 작아(×1.04~1.05) 두 후보 모두 ★★다."],
             ["후보 1 TTFT P99 2,060 ms는 2 s를 3% 넘어 개선 r = 1.11인데도 QA2 ★로 강등된다(별 두 단계 차이).",
              "후보 2 QA4는 module 2.30이 ★★★ 경계 2를 넘어 ★★이다(비용·공수는 ★★★). DP4 시나리오 가중을 쓰면 ★★★이 되어 합계 8 대 8, QA2에서 후보 2가 앞선다.",
              "N > 2 서버 확장과 후보 2는 실측이 아니라 모델이다. 후보 2의 ★(SE)은 샤딩 보완 전 기준이다."],
             y=4.55, h=2.45, lt="읽는 법", rt="정직한 주의", size=9.5)
    add(s)

    # ---------------------------------------------------------------- decisions
    s = B.frame("공통 별 기준 v3 — 소유자 결정이 필요한 사항", "결정 전까지는 proposal이다 · 상세는 qa-star-criteria-unified.md §8",
                "※ 평가 수치(측정·시뮬레이션 값)는 어떤 결정에서도 경계에 맞춰 바꾸지 않는다.")
    rows = [["#", "결정", "제안", "영향"],
            ["D1", "QA1 ★★★ = 4/3", "요청대로. 기준 근거는 '서버 25% 절감'이라는 환산이며 2.0보다 약하다", "DP1 C2, DP2 두 후보 ★★★ (DP1 선택 C2)"],
            ["D2", "QA2 TPOT 상한 50 ms(요청의 '2 ms'는 오타로 해석), R 경계 1.20 / 0.90", "50 ms로 적용. 확인 필요", "DP4 후보1 ★(TTFT 3% 초과), DP1 C1 ★★"],
            ["D3", "QA4 AND 조건에서 DP4 시나리오 가중 사용 여부", "지금은 DP1·DP2와 같은 단순 평균. 가중(S2~S4 ×2)을 쓰면 후보2 QA4 ★★★", "DP4 선택(후보1 대 후보2)"],
            ["D4", "QA5 두 번째 경계 3%", "제안 3%, task의 F1 변동을 재서 확인", "DP3 별"],
            ["D5", "DP2 정의: 한 노드 안의 결정(2026-10-10 재정의)으로 평가함", "PPT 설계 장 6p의 후보 이름(스케줄링 시점 / 사전 계획)과 평가의 후보(중앙 Dispatcher / Blackboard)를 맞춘다", "DP2 설계 장 문구"],
            ["D6", "DP3 r, rho 가정(0.30, 0.15)과 C2의 선택 재계산 필수 여부, HBF에서 압축 끄기", "r, rho는 사전 등록값 + 민감도. 재계산·HBF 정책은 설계 결정", "DP3 별과 선택"],
            ["D7", "QA 번호", "요구사항 덱의 QA-05 확장성 / QA-06 정확성을 PPT(QA5 정확성, QA6 확장성)에 맞춰 교환", "문서 일관성"],
            ["D8", "Evaluation/DP4 폴더", "옛 DP4(현 DP6) 자료다. 현 DP4 평가 문서 위치를 정한다", "평가 문서 정리"]]
    B.table(s, 0.4, 1.35, [0.6, 3.6, 5.6, 2.73], rows, size=9.5, row_h=0.56, align=["c", "l", "l", "l"], bold_first_col=True)
    add(s)

    # ================================================================ Appendix additions
    # ---- why absolute values differ
    s = B.frame("부록 — 같은 QA의 절대값이 DP마다 다른 이유", "그래서 별은 절대값이 아니라 '같은 DP의 Baseline 대비'(+ 절대 SLO)로 매긴다 · DP 간 절대값 비교는 하지 않는다",
                "※ DP1~DP3 = 시뮬레이션 [B+C], DP4 Baseline = 실측 [A]. 값은 각 DP 결과 문서·PPT 기준.")
    rows = [["", "DP1 이기종 메모리 데이터 배치", "DP2 노드 내 attention 실행 위치", "DP3 KV 압축·재사용", "DP4 다중 서버 요청 조율"],
            ["평가 단위", "서버 1대(8-GPU, TP8)", "노드 내 결정(통합 노드 1~4개, 노드 선택은 DP4)", "서버 1대(8-GPU, TP8)", "2노드 × 8 GPU = 16 GPU (실측)"],
            ["대표 워크로드", "KV 32K~512K, RAG 8 TiB, LoRA·MoE 혼합, HBM 압박", "단일 턴 8K + 멀티턴 History 16K~256K(Tier별 위치)", "재사용 문맥 8K~256K, 질의 64~2K", "입력 8K / 출력 256, prefix 재사용 통제"],
            ["Baseline 정의", "정적 배치(이동 없음)", "GPU-local (vLLM As-Is, 모든 attention을 GPU에서)", "전체 KV 그대로 재사용", "상태·캐시 비인지 라우팅"],
            ["부하 방식", "load sweep 최대(Max SLO goodput)", "Baseline 최적 부하(iso-load) + sweep", "Baseline 용량의 70%로 고정", "load sweep, 서버 수 N 증설"],
            ["QA1 Baseline (tok/s)", "336", "1,075", "897", "3,200"],
            ["QA2 Baseline TTFT P99 (ms)", "1,084", "3,529", "571", "2,300"],
            ["QA3 Baseline HBM (GiB)", "146.6", "605", "107.1", "—"]]
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
            ["DP2", "1안: QA1 ×1.00~1.11, TPOT P99 ×1.19~2.32 나쁨 / 2안: Baseline과 같음(×1.00) (H100·B200 공통 3개 시나리오 중 비교 가능 쌍)", "History 없는 단일 턴이라 attention 위치를 바꿀 이유가 적다. 1안만 Cost 모델이 일부 offload를 선택해 TPOT 꼬리가 길어진다"],
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

    # ---- DP1 interpretation
    s = B.frame("부록 — DP1 결과 해석: 왜 C2가 지연도 처리량도 좋은가", "C1 = 메모리 자원 상태에 반응해 이동, C2 = 데이터별 접근 패턴(hotness·재사용·유휴)으로 이동 · 지연은 C2가 P50과 P99 모두 낮다",
                "※ 출처: DP1/results/2026-10-02_dp1-qa-evaluation.md §0.2 (H100 + B200 통합, 21쌍). 아래 '원인'은 그 문서의 진단이며 요청 단위 분해로 확인한 것은 아니다.")
    rows = [["지표 (21쌍 기하평균)", "Baseline (이동 없음)", "C1 자원 상태 기반", "C2 AI Data 특성 기반"],
            ["TTFT P50 (ms)", "407", "181 (×0.44)", "118 (×0.29)"],
            ["TTFT P99 (ms)", "1,084", "1,128 (×1.04)", "785 (×0.72)"],
            ["TPOT P50 / P99 (ms)", "14.0 / 17.1", "12.7 / 18.3", "12.0 / 16.0"],
            ["Dynamic 6개 TTFT P99 중앙값 (ms)", "—", "1,411", "663"],
            ["이동량 (GiB) / 링크 점유", "0", "138 / 1.6%", "1,339 / 10.5%"],
            ["결정 연산 (ms/run)", "0", "3", "111"],
            ["HBM 점유 (용량 대비)", "51%", "50%", "62%"]]
    B.table(s, 0.4, 1.3, [3.6, 2.8, 3.0, 3.13], rows, size=10, row_h=0.36, align=["l", "c", "c", "c"], bold_first_col=True)
    B.blocks(s, ["C1은 용량 압박·대역폭 같은 자원 상태가 나빠진 뒤에 반응한다. 같은 종류(KV) 안에서 어느 세션이 hot인지 모르므로 hot 대상이 바뀌는 시나리오(hot 대화 이동, 사용자 그룹 교대)에서 Baseline과 같다. Dynamic에서 Baseline을 이긴 쌍은 C1 5개, C2 8개다.",
                 "C2는 접근 빈도·재사용·유휴 시간으로 '곧 뜨거워질 것'을 예측해 hot 데이터를 미리 HBM 쪽으로 올리고 cold를 내린다. 그래서 요청이 오는 시점에 hot KV가 이미 빠른 tier에 있어 TTFT가 줄고(P50·P99 모두), decode 접근도 빨라 처리량이 오른다.",
                 "C1의 P50이 Baseline보다 낮은데 P99가 높은 것은, 압박 뒤 반응형 이동이 늦게 도착하고 이동이 서빙 링크를 나눠 쓰는 간섭이 꼬리에 얹히기 때문으로 보인다(문서 진단: 간섭 반영 후 P99 격차가 벌어짐)."],
             ["대가는 HBM이다: C2는 성능을 위해 hot 데이터를 HBM에 더 올려 점유가 62%(C1 50%)다. 이동량(1,339 대 138 GiB)·링크 점유·결정 연산도 크다. 이 비용은 지연 개선 배수를 깎았다(C2 ×1.66 → ×1.56).",
              "그래서 'C1이 지연이 더 좋다'는 설명은 이 시뮬레이션에서 근거가 없다. 정적 워크로드(공통 3개)에서도 C1 TTFT P99는 ×2.95 나쁘고 C2는 ×1.03이다.",
              "시뮬레이션 [B+C]이며 이동 비용 모델(링크 간섭)과 접근 패턴 생성이 ASSUMED다. Dynamic은 Baseline의 실패 양상을 알고 설계한 시나리오다."],
             y=4.35, h=2.65, lt="해석", rt="대가와 한계", size=9.5)
    new_slide = s
    add(s)

    dp_scn("부록 — DP2 시나리오: 한 노드 안에서 Prefill/Decode 실행 위치를 정하는 조건", "Common 3 + Stress 10 + Dynamic 3 = 16 시나리오 × 2시스템 = 32쌍(비교 가능 21, saturated 11) · 노드 선택은 DP4 · 평가에서 Prefill은 항상 GPU, 결정 대상은 Decode attention을 돌릴 tier(HBM·ScHBM·CXL-PNM·HBF) · Baseline = GPU-local",
           [["Common (CB-1~3)", "단일 턴 8K, 통합 노드 1개", "1안 TPOT P99 ×1.19~2.32(B200 CB-1 ×2.32)", "H100 CB-3에서 1안 goodput ×1.11"],
            ["Stress — History 재개", "History 32K~256K가 HBM·DRAM·HBF·SSD에 있는 멀티턴, 긴 문맥 decode offload", "1안 long_ctx_decode_offload: TPOT P99 ×2.31~2.45 나쁨", "1안 long_ctx_decode_offload: goodput ×1.23(B200)·×1.23(H100), TTFT P99 ×0.39~0.46"],
            ["Stress — 포화·쏠림", "decode 편중, 대형 세션 쏠림, stale telemetry, Tool 결과 큼(대조군)", "2안 decode 편중: TTFT P99 ×1.87~4.02 나쁨. 2안 stale telemetry(B200): HBM ×1.98", "1안 decode 편중: TTFT P99 ×0.13~0.19. 2안 stale telemetry(B200): goodput ×1.36"],
            ["Dynamic 3", "decode phase 이동, load ramp·burst, demotion wave", "1안 load ramp(B200): TTFT P99 ×4.82 나쁨", "1안 load ramp: goodput ×1.25~1.28"]],
           ["이득은 'History가 HBM 밖에 있거나 decode가 한 노드에 몰려' attention 위치를 바꿀 가치가 있는 조건에 있다. 신호가 없으면 두 후보 모두 Baseline과 같다(saturated 11쌍).", "1안은 TTFT·HBM·처리량을 얻고 TPOT 꼬리(P99 ×1.34)를 낸다."],
           ["비율은 후보 ÷ Baseline(시나리오·시스템 쌍별, iso-load). 일부 시나리오는 후보와 Baseline의 부하 지점이 달라 단순 비교가 아니다.", "Cost 추정 오차 σ = 0 가정이다(σ ≥ 0.4에서 1안은 Baseline 아래)."],
           "※ 출처: DP2/benchmark.md §11, DP2/results/2026-10-10_dp2-arch-styles.md §4.2 (시나리오별 표)")

    # ---- DP2 interpretation
    s = B.frame("부록 — DP2 결과 해석: 왜 Decode 편중에서 2안이 1안보다 더 떨어지는가", "n_dp2_decode_heavy_p_idle(출력 2K 위주, decode가 한 노드에 몰림) · Baseline 최적 부하 · 1안 = 중앙 Dispatcher, 2안 = Blackboard",
                "※ 출처: DP2/results/data/arch/SYS-*/runs.jsonl (comp.schedule = admission 대기 평균, arch.tiers = tier별 decode 요청 수, seed 11의 1회 run·TTFT와 대기는 5 seed 평균). 원인 서술은 DP2 결과 문서의 진단(admission margin과 cost 신호 부재)과 위 수치로 확인한 것이다.")
    rows = [["SYS-B200", "Baseline GPU-local", "1안 중앙 Dispatcher", "2안 Blackboard"],
            ["TTFT P99 (s)", "5.73", "0.73 (×0.13)", "23.08 (×4.03)"],
            ["admission 대기 평균 (s)", "0.00", "0.00", "0.36"],
            ["decode 실행 tier (요청 수)", "HBM 3,134", "HBM 2,870 · ScHBM 505 · 기타 17", "HBM 3,102 · ScHBM 1"],
            ["HBM 점유 (용량 대비)", "65%", "61%", "65%"],
            ["SYS-H100", "Baseline GPU-local", "1안 중앙 Dispatcher", "2안 Blackboard"],
            ["TTFT P99 (s)", "21.5", "4.18 (×0.19)", "40.24 (×1.87)"],
            ["admission 대기 평균 (s)", "0.69", "0.00", "1.32"],
            ["decode 실행 tier (요청 수)", "HBM 1,408", "HBM 1,213 · ScHBM 232 · 기타 20", "HBM 1,376"]]
    B.table(s, 0.4, 1.3, [2.8, 2.6, 3.7, 3.43], rows, size=9.5, row_h=0.33, fills={5: ["EAF0FA"] * 4}, align=["l", "c", "c", "c"], bold_first_col=True)
    B.blocks(s, ["2안의 규칙은 'HBM 먼저, HBM budget(사용률 ≤ 0.85)이 거절할 때만 offload'다. offload tier agent는 자기 tier의 측정된 attention 시간이 SLO_TPOT의 0.8배 이내일 때만 claim한다.",
                 "Decode가 몰리면 HBM 사용률이 0.85를 넘어 HBM 경로가 거절되고, offload agent도 headroom이 없어 거절한다. 그래서 Task가 Board에서 기다린다(대기 0.36 s, H100 1.32 s). decode 요청 3,100여 개 중 ScHBM으로 간 것은 1개다.",
                 "1안은 Cost 모델(HBM 기회비용 포함)이 사용률이 오르기 전에 decode의 약 15%를 ScHBM으로 보낸다(B200 505개). 그래서 HBM에 여유가 생겨 admission 대기가 0이다. Baseline(모든 attention을 GPU/HBM)은 그 경로가 없어 대기가 생긴다."],
             ["그래서 2안이 Baseline보다도 나쁘다(×4.03, ×1.87): Baseline은 HBM에서 대기하고, 2안은 거기에 admission margin(0.85)이 더해져 더 일찍 막는다. 처리량은 비슷하다(×0.97, ×0.98).",
              "대가는 1안의 TPOT 꼬리다: 이 시나리오에서 H100 TPOT P99 ×1.54. ScHBM attention이 GPU보다 느려 SLO 이내의 TPOT 여유를 TTFT·HBM과 교환한다.",
              "한계: Baseline 최적 부하는 이미 과부하 구간이라 TTFT 절대값이 크다(5.7~40 s). 비율(×0.13, ×4.03)이 결정적이며, 결정 상수(θ = 0.8, ρ_hi = 0.85)는 사전 등록값이다. θ·ρ_hi 민감도 계획은 DP2/arch-styles-plan.md."],
             y=4.5, h=2.5, lt="원인", rt="대가와 한계", size=9.5)
    add(s)

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
                 "Interconnect: host PCIe 5.0 x16 63 GB/s(방향당), CXL 2.0. ScHBM의 외부 BW는 host link 1가닥을 도메인 전체가 공유한다. HBF는 GPU 직결(UCIe)이라 link와 무관. (DP2는 노드 내 결정이라 노드 간 링크를 쓰지 않는다.)"],
             ["시뮬레이터: DP1 = 객체 이동 정책 시뮬레이터, DP2 = 노드 내 attention 실행 위치 결정(Dispatcher 대 Blackboard), DP3 = 요청 단위 GPU timeline(적재 → prefill → decode). 서비스 시간 = 바이트 ÷ 대역폭 + 지연, tier별 FIFO.",
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

    hs = json.load(open(HERE / "hbm_share.json"))

    def set_star(p, star):
        """First run(s) of the paragraph that hold only star glyphs are rewritten to `star` (rest of the paragraph is kept)."""
        done = False
        for r in p.runs:
            if r.text.strip() and set(r.text.strip()) <= set("★☆"):
                r.text = "" if done else star
                done = True
            elif done:
                break

    def hbm_txt(gib, share, base_gib, ratio=None):
        return f"{gib:.1f}(용량 {share*100:.0f}%, 감소 {(ratio if ratio else base_gib/gib):.2f}배)"

    def relabel_hbm(t, paras_idx):
        for col in (1, 3):
            p = t.cell(4, col).text_frame.paragraphs[paras_idx]
            rs = p.runs
            rs[-1].text = rs[-1].text.rstrip(")") + ", 용량 %, 감소 배수)" if rs[-1].text.endswith(")") else rs[-1].text
            if not rs[-1].text.endswith(")"):
                rs[-1].text += ")"

    # --- DP1 slides (3, 4): QA4 line + label order, stars, HBM display
    for idx in (2, 3):
        t = tradeoff_table(prs.slides[idx])
        relabel_hbm(t, 2)
        for col, c, key in ((2, "C1", "DP1-1안" if idx == 2 else "DP1"), (4, "C2", "DP1")):
            st = res[key][c if key == "DP1" else "C1"]
            for k, qa in enumerate(("QA1", "QA2", "QA3", "QA4")):
                set_star(t.cell(4, col).text_frame.paragraphs[k], S(st[qa]))
            q = inp["DP1"]["values"][c]["qa4"]
            p = t.cell(4, col).text_frame.paragraphs[3]
            p.runs[-1].text = f"${q['usd_t2']:.2f}, {q['mm']:.2f}, {q['modules']:.2f}"
            hk = c if key == "DP1" else "C1_noaff"
            p3 = t.cell(4, col).text_frame.paragraphs[2]
            rs = p3.runs
            for r in rs[2:]:
                r.text = ""
            rs[2].text = hbm_txt(hs["DP1"][hk]["gib"], hs["DP1"][hk]["share"], hs["DP1"]["Baseline"]["gib"])
        for col in (1, 3):
            p = t.cell(4, col).text_frame.paragraphs[3]
            r = p.runs
            if len(r) == 4:   # 'Modifiability ', '(module, M/M, ', '토큰 비용', ')'
                r[1].text, r[2].text = "(토큰 비용, M/M, ", "모듈 수"
            else:             # 'Modifiability (module, M/M, ', '토큰 비용', ')'
                r[0].text, r[1].text = "Modifiability (토큰 비용, M/M, ", "모듈 수"
    t = tradeoff_table(prs.slides[3])
    for r in t.cell(4, 2).text_frame.paragraphs[0].runs:
        if r.text.startswith("436"):
            r.text = "436(x1.298)"
    dp1_label = tradeoff_table(prs.slides[2]).cell(4, 1)._tc.txBody          # 4 lines: throughput, latency, HBM, modifiability (already relabeled)

    # --- slide 1: DP2 adds QA3 (HBM) and keeps QA4; DP3 adds QA1 (throughput)
    for sh in prs.slides[0].shapes:
        if sh.has_table:
            tb = sh.table
            tx_src, tx_dst = tb.cell(3, 1)._tc.txBody, tb.cell(3, 2)._tc.txBody
            for p in tx_dst.findall(qn("a:p")):
                tx_dst.remove(p)
            for p in tx_src.findall(qn("a:p")):
                tx_dst.append(copy.deepcopy(p))
            tx_src, tx_dst = tb.cell(1, 1)._tc.txBody, tb.cell(1, 3)._tc.txBody
            for p in tx_dst.findall(qn("a:p")):
                tx_dst.remove(p)
            for p in tx_src.findall(qn("a:p")):
                tx_dst.append(copy.deepcopy(p))

    # --- DP2 slide (6): QA1, QA2, QA3 (HBM), QA4 (labels copied from the DP1 slide)
    t = tradeoff_table(prs.slides[5])
    for col in (1, 3):
        tx = t.cell(4, col)._tc.txBody
        for p in tx.findall(qn("a:p")):
            tx.remove(p)
        for p in dp1_label.findall(qn("a:p")):
            tx.append(copy.deepcopy(p))
    for col, c in ((2, "C1"), (4, "C2")):
        v = inp["DP2"]["values"][c]
        st = res["DP2"][c]
        q = v["qa4"]
        fill_value_cell(t.cell(4, col), tpl, [
            (S(st["QA1"]), f"{v['qa1_tps']:,.0f}(x{v['qa1_ratio']:.2f})", None),
            (S(st["QA2"]), f"{v['ttft_p99_ms']:,.0f}(x{v['ttft_p99_ms']/inp['DP2']['baseline']['ttft_p99_ms']:.2f}), {v['tpot_p99_ms']:.1f}(x{v['tpot_p99_ms']/inp['DP2']['baseline']['tpot_p99_ms']:.2f})", "FF0000"),
            (S(st["QA3"]), hbm_txt(v["hbm_gib"], hs["DP2"][c]["share"], v["hbm_base_gib"], v["qa3_ratio"]), None),
            (S(st["QA4"]), f"${q['usd_t2']:.2f}, {q['mm']:.2f}, {q['modules']:.2f}", None)])
    for idx in (5, 7):
        cols = tradeoff_table(prs.slides[idx]).columns
        for c, w in zip(cols, (0.96, 3.51, 2.44, 3.71, 2.24)):
            c.width = Inches(w)
    # --- DP3 slide (8): QA1 added; stars and values from the simulation
    t = tradeoff_table(prs.slides[7])
    sm = json.load(open(U.EVAL / "DP3" / "results" / "data" / "dp3_summary.json"))["aggregate"]
    relabel_hbm(t, 1)
    first = dp1_label.findall(qn("a:p"))[0]
    for col in (1, 3):
        tx = t.cell(4, col)._tc.txBody
        tx.insert(list(tx).index(tx.findall(qn("a:p"))[0]), copy.deepcopy(first))
    for col, c, pol in ((2, "C1", "C1-Offline"), (4, "C2", "C2-Online")):
        v, st = inp["DP3"]["values"][c], res["DP3"][c]
        l3 = (S(st["QA5"]), f"F1 하락 {v['f1_drop_pct']:.1f}%", None) if "QA5" in st else ("미평가", "(F1 측정 중)", "7F7F7F")
        fill_value_cell(t.cell(4, col), tpl, [
            (S(st["QA1"]), f"{v['qa1_tps']:,.0f}(x{v['qa1_ratio']:.2f})", None),
            (S(st["QA2"]), f"{v['ttft_p99_ms']:,.0f}(x{1/sm[pol]['ttft']['ratio_gm']:.2f}), {v['tpot_p99_ms']:.1f}(x{1/sm[pol]['tpot']['ratio_gm']:.2f})", "FF0000"),
            (S(st["QA3"]), hbm_txt(hs["DP3"][c]["gib"], hs["DP3"][c]["share"], hs["DP3"]["Baseline"]["gib"]), None),
            l3])

    # --- DP4 slide (10): stars and QA4 line unified basis
    t = tradeoff_table(prs.slides[9])
    for col, c in ((2, "C1"), (4, "C2")):
        for k, qa in enumerate(("QA1", "QA2", "QA4", "QA6")):
            set_star(t.cell(4, col).text_frame.paragraphs[k], S(res["DP4"][c][qa]))
        q = inp["DP4"]["values"][c]["qa4_equal"]
        p = t.cell(4, col).text_frame.paragraphs[2]
        txt = f"${q['usd_t2']:.2f}, {q['mm']:.2f}, {q['modules']:.1f}"
        rs = p.runs
        rs[-1].text = txt
        for r in rs[2:-1]:
            r.text = ""

    # --- main slides: the Tradeoff row now has up to 4 lines; use 10 pt so it stays on the page
    for idx in (2, 3, 5, 7, 9):
        t = tradeoff_table(prs.slides[idx])
        for col in (1, 2, 3, 4):
            for p in t.cell(4, col).text_frame.paragraphs:
                for r in p.runs:
                    r.font.size = Pt(10)

    # --- banners on superseded per-DP criteria slides
    layout = [l for l in prs.slide_layouts if l.name == "빈 화면"][0]
    B = Builder(prs, layout)
    def banner(slide, text, y=1.13):
        B.tb(slide, 0.4, y, 12.5, 0.24, [(text, dict(bold=True, color=RED, size=8.5))], name="banner")
    banner(prs.slides[12], "※ 공통 별 기준 v3: DP1 별 합계는 C1 9, C2 9(동점 → QA1에서 C2). 이 장의 표는 DP1 기준(v5)이고 v3와 QA2·QA4 판정이 다르다.")
    banner(prs.slides[18], "※ 공통 별 기준 v3 QA1과 같은 방식이다. ★★★ 경계는 4/3(≈1.33)이다. ★★ 하한 0.97은 같다.")
    banner(prs.slides[19], "※ 공통 별 기준 v3에서 대체됨: QA2 = Baseline 대비 개선 r(≥ 1.20 ★★★, ≥ 0.90 ★★)이며 TTFT > 2 s 또는 TPOT > 50 ms이면 ★.")
    banner(prs.slides[20], "※ 공통 별 기준 v3 QA3과 같은 기준이다(감소 배수 1.25/0.95). PPT에는 용량 대비 점유 %를 병기한다. 기존 별 그대로.")
    banner(prs.slides[21], "※ 공통 별 기준 v3에서 대체됨: 별 = 세 sub-star의 최솟값(AND), 비용은 mid tier $0.5/$2, 공수 0.5/1.0 MM. DP1 별 그대로.")
    banner(prs.slides[26], "※ 공통 별 기준 v3에서 대체됨: QA1 경계는 0.97/4/3(이 장의 0.90/1.10 대신). Q1 = 공통 QA1. DP4 별 그대로.")
    banner(prs.slides[27], "※ 공통 별 기준 v3에서 대체됨: 개선 r로 별을 정하고 절대 SLO 초과 시 ★. Q2 = 공통 QA2. DP4 후보1 ★, 후보2 ★★.")
    banner(prs.slides[28], "※ 공통 별 기준 v3에서 대체됨: 우선순위 규칙 대신 AND 조건, 공수는 MM(man-day ÷ 21), 단순 평균. Q3 = 공통 QA4. DP4 후보1·후보2 ★★.")
    banner(prs.slides[30], "※ 공통 별 기준 v3 QA6과 같은 기준이다(SE 90/70, N_max=16). Q4 = 공통 QA6. 기존 별 그대로.")

    # --- unified section after the Appendix divider (slide 11)
    new = build_slides(prs, res, inp)
    move_after(prs, new, 10)
    prs.save(dst)
    print("saved", dst, len(prs.slides._sldIdLst), "slides; new:", len(new))


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
