"""QA-01~05 별 기준·근거 슬라이드 생성 (QA-02 보충 장 포함, 총 6장).

템플릿: 사용자가 준 품질 요구사항 PPT(2~5쪽 서식). 입력 덱의 마스터·레이아웃·내비게이션 도형을 재사용한다.
사용: python build_deck.py <in.pptx> <out.pptx>
수치는 같은 폴더의 JSON(qa_evidence_out / qa2_load_rho / vllm_commit_stats / burstgpt_load_stats)에서 읽는다. 손으로 쓰지 않는다.
"""
import copy
import json
import math
import sys
from pathlib import Path

from lxml import etree
from pptx import Presentation
from pptx.chart.data import XyChartData
from pptx.dml.color import RGBColor
from pptx.enum.chart import XL_CHART_TYPE, XL_LEGEND_POSITION, XL_MARKER_STYLE
from pptx.enum.dml import MSO_LINE
from pptx.enum.shapes import MSO_CONNECTOR, MSO_SHAPE
from pptx.enum.text import MSO_ANCHOR, PP_ALIGN
from pptx.oxml.ns import qn
from pptx.util import Inches, Pt

HERE = Path(__file__).parent
J = lambda n: json.load(open(HERE / n))
M, L2, VC, BG = J("qa_evidence_out.json"), J("qa2_load_rho.json"), J("vllm_commit_stats.json"), J("burstgpt_load_stats.json")
FONT = "맑은 고딕"
BLUE, ORANGE, GREEN, GRAY = "2E75B6", "C55A11", "548235", "7F7F7F"
CLS = {"lit": BLUE, "cond": ORANGE, "int": GREEN, "calc": GRAY}
STAR_FILL = ["FFFFFF", "FFF2CC", "FFF8E1", "DEEBF7", "EEF5FB", "E2F0D9"]  # ☆ ★ ★½ ★★ ★★½ ★★★
STAR_NAME = ["☆ 미충족", "★", "★½", "★★", "★★½", "★★★"]
STAR_SHORT = ["☆", "★", "★½", "★★", "★★½", "★★★"]
TOTAL = 6


def rgb(h):
    return RGBColor.from_string(h)


# ---------------------------------------------------------------- primitives
def set_font(run, size, bold=False, color="000000"):
    run.font.size = Pt(size)
    run.font.bold = bold
    run.font.color.rgb = rgb(color)
    rPr = run._r.get_or_add_rPr()
    for tag in ("a:latin", "a:ea", "a:cs"):
        for e in rPr.findall(qn(tag)):
            rPr.remove(e)
        etree.SubElement(rPr, qn(tag)).set("typeface", FONT)


def add_runs(par, content, size, bold=False, color="000000"):
    if isinstance(content, str):
        content = [(content, {})]
    for text, o in content:
        r = par.add_run()
        r.text = text
        set_font(r, size, o.get("bold", bold), o.get("color", color))


def paragraphs(content):
    """str → 1문단, list[str] → 문단들, list[tuple] → 1문단(runs), list[list] → 문단들"""
    if isinstance(content, str):
        return [content]
    if content and isinstance(content[0], (str, list)):
        return list(content)
    return [content]


def textbox(slide, x, y, w, h, content, size=8, bold=False, color="000000", align=PP_ALIGN.LEFT,
            anchor=MSO_ANCHOR.TOP, wrap=True, fill=None):
    tb = slide.shapes.add_textbox(Inches(x), Inches(y), Inches(w), Inches(h))
    if fill:
        tb.fill.solid()
        tb.fill.fore_color.rgb = rgb(fill)
    tf = tb.text_frame
    tf.word_wrap = wrap
    tf.margin_left = tf.margin_right = Inches(0.03)
    tf.margin_top = tf.margin_bottom = Inches(0.01)
    tf.vertical_anchor = anchor
    lines = paragraphs(content)
    for i, ln in enumerate(lines):
        p = tf.paragraphs[0] if i == 0 else tf.add_paragraph()
        p.alignment = align
        add_runs(p, ln, size, bold, color)
    return tb


def rect(slide, x, y, w, h, fill, line=None, shape=MSO_SHAPE.RECTANGLE, line_w=0.75):
    s = slide.shapes.add_shape(shape, Inches(x), Inches(y), Inches(w), Inches(h))
    s.shadow.inherit = False
    if fill:
        s.fill.solid()
        s.fill.fore_color.rgb = rgb(fill)
    else:
        s.fill.background()
    if line:
        s.line.color.rgb = rgb(line)
        s.line.width = Pt(line_w)
    else:
        s.line.fill.background()
    return s


def line(slide, x1, y1, x2, y2, color, w=0.75, dash=False):
    c = slide.shapes.add_connector(MSO_CONNECTOR.STRAIGHT, Inches(x1), Inches(y1), Inches(x2), Inches(y2))
    c.line.color.rgb = rgb(color)
    c.line.width = Pt(w)
    if dash:
        c.line.dash_style = MSO_LINE.DASH
    return c


def set_cell(cell, content, size, bold=False, color="000000", fill=None, align=PP_ALIGN.LEFT):
    tf = cell.text_frame
    tf.word_wrap = True
    cell.margin_left = cell.margin_right = Inches(0.05)
    cell.margin_top = cell.margin_bottom = Inches(0.02)
    cell.vertical_anchor = MSO_ANCHOR.MIDDLE
    lines = paragraphs(content)
    for i, ln in enumerate(lines):
        p = tf.paragraphs[0] if i == 0 else tf.add_paragraph()
        p.alignment = align
        add_runs(p, ln, size, bold, color)
    tcPr = cell._tc.get_or_add_tcPr()
    for tag in ("a:lnL", "a:lnR", "a:lnT", "a:lnB"):
        ln_ = etree.SubElement(tcPr, qn(tag))
        ln_.set("w", "6350")
        etree.SubElement(etree.SubElement(ln_, qn("a:solidFill")), qn("a:srgbClr")).set("val", "BFBFBF")
    if fill:
        etree.SubElement(etree.SubElement(tcPr, qn("a:solidFill")), qn("a:srgbClr")).set("val", fill)
    else:
        etree.SubElement(tcPr, qn("a:noFill"))


def table(slide, x, y, col_w, rows, row_h, size=8.5, header=True, fills=None, aligns=None, bold_cols=(),
          header_bold=True, col_colors=None):
    n_r, n_c = len(rows), len(col_w)
    gf = slide.shapes.add_table(n_r, n_c, Inches(x), Inches(y), Inches(sum(col_w)), Inches(sum(row_h)))
    tbl = gf.table
    tblPr = tbl._tbl.tblPr
    for a in ("firstRow", "bandRow"):
        tblPr.attrib.pop(a, None)
    sid = tblPr.find(qn("a:tableStyleId"))
    if sid is None:
        sid = etree.SubElement(tblPr, qn("a:tableStyleId"))
    sid.text = "{2D5ABB26-0587-4C30-8999-92F81FD0307C}"  # No Style, No Grid (원본과 동일)
    for i, w in enumerate(col_w):
        tbl.columns[i].width = Inches(w)
    for r in range(n_r):
        tbl.rows[r].height = Inches(row_h[r])
        for c in range(n_c):
            is_h = header and r == 0
            fill = "F2F2F2" if is_h else (fills.get((r, c)) if fills else None)
            al = PP_ALIGN.CENTER if is_h else (aligns[c] if aligns else PP_ALIGN.LEFT)
            color = (col_colors or {}).get((r, c), "000000")
            set_cell(tbl.cell(r, c), rows[r][c], size, bold=(is_h and header_bold) or (not is_h and c in bold_cols),
                     color=color, fill=fill, align=al)
    return gf


def star_range(lo, hi, th):
    a, b = STAR_SHORT[star_count(lo, th)], STAR_SHORT[star_count(hi, th)]
    return a if a == b else f"{a}~{b}"


def star_count(v, th, lower_better=False):
    """th: 5개 경계(★ ... ★★★). 달성한 별 단계(0=☆ ... 5=★★★)"""
    return sum((v <= t) if lower_better else (v >= t) for t in th)


# ---------------------------------------------------------------- chart (원본 서식: 근거별 범위 도식)
def chart(slide, spec, x_lab=6.85, x0=9.3, x1=12.45, y_top=1.52):
    vmin, vmax = spec["vmin"], spec["vmax"]
    X = lambda v: x0 + (min(max(v, vmin), vmax) - vmin) / (vmax - vmin) * (x1 - x0)
    levels = spec.get("levels", 2)
    textbox(slide, x_lab, y_top, 6.25, 0.24, spec["title"], 10, True)
    n = len(spec["rows"])
    pitch = 0.21
    y_rows = y_top + 0.3 + levels * 0.14
    y_axis = y_rows + n * pitch + 0.04
    for i, (lab, val) in enumerate(spec["marks"]):          # 별 기준선: 라벨 중심을 선의 x에 맞춤
        xv = X(val)
        ly = y_top + 0.27 + (i % levels) * 0.14
        textbox(slide, xv - 0.45, ly, 0.9, 0.15, lab, 8, True, "C00000", PP_ALIGN.CENTER, wrap=False)
        line(slide, xv, ly + 0.16, xv, y_axis, "C00000", 1.0, dash=True)
    line(slide, x0 - 0.05, y_axis, x1 + 0.05, y_axis, GRAY, 0.75)
    for t in spec["ticks"]:
        xt = X(t)
        line(slide, xt, y_axis, xt, y_axis + 0.05, GRAY, 0.75)
        textbox(slide, xt - 0.3, y_axis + 0.04, 0.6, 0.17, spec["fmt"](t), 8, False, GRAY, PP_ALIGN.CENTER)
    for i, r in enumerate(spec["rows"]):
        y = y_rows + i * pitch
        col = CLS[r["cls"]]
        textbox(slide, x_lab, y - 0.005, x0 - 0.12 - x_lab, 0.18, r["label"], 8, False, "404040", PP_ALIGN.RIGHT)  # 우측 정렬
        lo, hi = r["lo"], r.get("hi")
        if hi is None:
            xc = X(lo)
            rect(slide, xc - 0.06, y + 0.035, 0.12, 0.12, col, shape=MSO_SHAPE.OVAL)
            xe = xc + 0.1
        else:
            xa, xb = X(lo), X(hi)
            rect(slide, xa, y + 0.04, max(xb - xa, 0.05), 0.11, col)
            xe = xb + 0.04
        if r.get("clip"):
            textbox(slide, x1 - 0.02, y - 0.01, 0.25, 0.18, "▶", 8, False, col)
        txt = r["text"]
        tw = 0.075 * len(txt) + 0.12
        if xe + tw > 13.1 or r.get("text_left"):
            textbox(slide, X(lo) - tw - 0.1, y - 0.005, tw, 0.18, txt, 8, True, col, PP_ALIGN.RIGHT, fill="FFFFFF")
        else:
            textbox(slide, xe, y - 0.005, tw, 0.18, txt, 8, True, col, fill="FFFFFF")
    ly = y_axis + 0.27
    xs = x_lab
    for key, lab, w in (("lit", "문헌·실측·실트래픽", 1.15), ("cond", "문헌·시뮬/조건부", 1.1),
                        ("int", "내부 모델·계수 [B+C]", 1.35), ("calc", "환산·원리·정책", 1.0)):
        rect(slide, xs, ly + 0.05, 0.12, 0.1, CLS[key])
        textbox(slide, xs + 0.15, ly, w, 0.18, lab, 8, False, "404040", wrap=False)
        xs += w + 0.3
    return ly + 0.28


# ---------------------------------------------------------------- slide frame
def new_slide(prs, layout, nav, title):
    s = prs.slides.add_slide(layout)
    for ph in list(s.placeholders):
        if ph.placeholder_format.idx != 0:
            ph._element.getparent().remove(ph._element)
    s.shapes.title.text = title
    for sh in nav:
        s.shapes._spTree.append(copy.deepcopy(sh._element))
    return s


def key_box(s, label, text, y=0.68, h=0.72):
    rect(s, 0.27, y, 12.83, h, "F0F1F3", "BFBFBF", line_w=0.8)
    rect(s, 0.27, y, 0.07, h, "595959")
    textbox(s, 0.4, y + 0.02, 0.9, h - 0.04, label, 10, True, "000000", anchor=MSO_ANCHOR.MIDDLE)
    textbox(s, 1.3, y + 0.01, 11.75, h - 0.02, text, 9, False, "404040", anchor=MSO_ANCHOR.MIDDLE)


def footer(s, source, page):
    textbox(s, 0.27, 6.62, 12.83, 0.5, source, 7.5, False, GRAY)
    textbox(s, 5.85, 7.2, 1.6, 0.24, f"{page} / {TOTAL}", 10, False, GRAY, PP_ALIGN.CENTER)


def build_slide(prs, layout, nav, qa):
    assert len(qa["evidence"]) <= 5, "근거 표는 5개 이내"
    s = new_slide(prs, layout, nav, qa["title"])
    key_box(s, "지표 설명", qa["metric"])
    # 좌상: 별 기준 표 — 위로 갈수록 별이 많아짐(★★★ → ☆)
    rows = [["별", qa["cond_head"], "근거"]]
    fills = {}
    for disp, k in enumerate(range(5, -1, -1), start=1):
        cond, why = qa["stars"][k]
        rows.append([STAR_NAME[k], cond, why])
        fills[(disp, 0)] = fills[(disp, 1)] = STAR_FILL[k]
    table(s, 0.27, 1.52, [0.72, 1.35, 4.33], rows, [0.26] + [0.36] * 6, 8.5, fills=fills,
          aligns=[PP_ALIGN.CENTER, PP_ALIGN.CENTER, PP_ALIGN.LEFT], bold_cols=(0, 1))
    # 좌하: 측정 시나리오 6 element
    textbox(s, 0.27, 4.07, 6.4, 0.2, "품질 시나리오 측정 시나리오 (6 element)", 10, True)
    elems = ["자극원(Source)", "자극(Stimulus)", "대상(Artifact)", "환경(Environment)", "응답(Response)", "응답 측정(Measure)"]
    table(s, 0.27, 4.3, [1.2, 5.2], [[e, qa["scenario"][i]] for i, e in enumerate(elems)],
          qa.get("scenario_h", [0.3] * 6), 8.5, header=False, fills={(r, 0): "F2F2F2" for r in range(6)},
          aligns=[PP_ALIGN.CENTER, PP_ALIGN.LEFT], bold_cols=(0,))
    # 우: 근거 범위 도식 + 근거 표(굵게 하지 않음, 최대 5개)
    y_end = chart(s, qa["chart"])
    rows3 = [["구분", "문헌·출처", "지표·조건", "값", "별 반영"]] + [list(r[1:]) for r in qa["evidence"]]
    colors = {(i + 1, 0): CLS[r[0]] for i, r in enumerate(qa["evidence"])}
    table(s, 6.85, y_end, [0.55, 1.45, 2.55, 0.8, 0.9], rows3, [0.26] + [0.4] * len(qa["evidence"]), 8,
          aligns=[PP_ALIGN.CENTER, PP_ALIGN.LEFT, PP_ALIGN.LEFT, PP_ALIGN.CENTER, PP_ALIGN.LEFT],
          header_bold=False, col_colors=colors)
    footer(s, qa["source"], qa["page"])
    return s


# ---------------------------------------------------------------- QA-02 보충: 고부하
def build_highload(prs, layout, nav, page):
    s = new_slide(prs, layout, nav, "QA-02 보충. 고부하(High Load) - 조건 · 의미 · 빈도")
    fr = BG["60s"]
    key_box(s, "핵심", "고부하 = 서버 이용률 ρ(요청률 ÷ 포화 처리율) 70% 이상. 큐 대기가 ρ=70% 부근부터 급증해 P99가 커지고(이론·시뮬레이션), "
                       "실트래픽에서는 시간으로는 드물어도 요청의 약 1~11%가 이 구간에서 처리되어 P99를 결정한다(BurstGPT 계산 [C]).")
    # 좌: 곡선 (네이티브 차트, 편집 가능)
    textbox(s, 0.27, 1.52, 6.8, 0.24, "이용률 ρ별 P99 큐 대기시간 (평균 서비스 시간 대비 배수, 로그 축)", 10, True)
    cd = XyChartData()
    s1 = cd.add_series("M/M/1 이론: ln(100ρ)/(1−ρ)")
    for m in L2["mm1"]:
        s1.add_data_point(m["rho"] * 100, m["p99"])
    s2 = cd.add_series("내부 모델: Baseline(HBM+DRAM offload) 시뮬레이션")
    for c in L2["curve"]:
        s2.add_data_point(c["rho"] * 100, c["p99_wait_over_service"])
    s3 = cd.add_series("고부하 기준 ρ = 70%")
    s3.add_data_point(70, 1)
    s3.add_data_point(70, 500)
    gf = s.shapes.add_chart(XL_CHART_TYPE.XY_SCATTER_LINES_NO_MARKERS, Inches(0.27), Inches(1.78), Inches(6.8), Inches(4.7), cd)
    ch = gf.chart
    ch.font.size = Pt(9)
    ch.font.name = FONT
    ch.has_legend = True
    ch.legend.position = XL_LEGEND_POSITION.BOTTOM
    ch.legend.include_in_layout = False
    va, ca = ch.value_axis, ch.category_axis
    ca.minimum_scale, ca.maximum_scale, ca.major_unit = 30, 100, 10
    va.minimum_scale, va.maximum_scale = 1, 500
    va.has_major_gridlines = True
    va.major_gridlines.format.line.color.rgb = rgb("D9D9D9")
    ca.has_major_gridlines = False
    ca.has_title = va.has_title = True
    ca.axis_title.text_frame.text = "이용률 ρ (%)"
    va.axis_title.text_frame.text = "P99 대기 ÷ 평균 서비스 시간 (log)"
    for ax in (ca, va):
        for r in ax.axis_title.text_frame.paragraphs[0].runs:
            set_font(r, 9, False, "404040")
    sc = va._element.find(qn("c:scaling"))                       # 로그 축
    lb = etree.Element(qn("c:logBase")); lb.set("val", "10"); sc.insert(0, lb)
    styles = [(BLUE, 2.25, None), (GREEN, 2.25, XL_MARKER_STYLE.CIRCLE), ("C00000", 1.5, None)]
    for ser, (col, w, mk) in zip(ch.plots[0].series, styles):
        ser.smooth = False
        ser.format.line.color.rgb = rgb(col)
        ser.format.line.width = Pt(w)
        if mk:
            ser.marker.style = mk
            ser.marker.size = 6
            ser.marker.format.fill.solid()
            ser.marker.format.fill.fore_color.rgb = rgb(col)
            ser.marker.format.line.color.rgb = rgb(col)
    ch.plots[0].series[2].format.line.dash_style = MSO_LINE.DASH
    # 곡선 위 라벨 대신 콜아웃(겹침 방지): 배수는 데이터에서 계산
    mm = {round(m["rho"], 2): m["p99"] for m in L2["mm1"]}
    des = {round(c["rho"], 2): c["p99_wait_over_service"] for c in L2["curve"]}
    r_mm_5_7, r_mm_7_9, r_des_5_7 = mm[0.7] / mm[0.5], mm[0.9] / mm[0.7], des[0.7] / des[0.5]
    textbox(s, 1.2, 2.0, 3.3, 0.62, [[("M/M/1 이론: ", {"bold": True, "color": BLUE}), (f"ρ 50%→70% ×{r_mm_5_7:.1f}, 70%→90% ×{r_mm_7_9:.1f}", {})],
                                      [("내부 모델: ", {"bold": True, "color": GREEN}), (f"ρ 50%→70% ×{r_des_5_7:.1f}, 80%에서 급등", {})]],
            8.5, False, "404040", fill="FFFFFF")
    textbox(s, 0.27, 6.45, 6.8, 0.2, "내부 모델 ρ≥80% 구간은 6,000요청 시뮬레이션 길이 때문에 정상상태가 아니라 큐가 누적되는 값이다.",
            7.5, False, GRAY)
    # 우: 조건 / 의미 / 빈도
    def panel(y, h, head, body_lines, color):
        rect(s, 7.3, y, 5.8, 0.26, color)
        textbox(s, 7.35, y + 0.02, 5.7, 0.22, head, 10, True, "FFFFFF")
        rect(s, 7.3, y + 0.26, 5.8, h - 0.26, "FFFFFF", "BFBFBF", line_w=0.6)
        textbox(s, 7.36, y + 0.3, 5.68, h - 0.32, body_lines, 8.5, False, "404040")
    panel(1.52, 1.28, "조건: 어떤 상태를 고부하라 하는가", [
        "ρ = 요청률 λ ÷ 포화 처리율(=1/평균 서비스시간) ≥ 70%. SLO와 무관한 서버 이용률이다.",
        "예: 평균 서비스 0.25 s → 포화 4 req/s → 고부하 시험 요청률 2.8 req/s.",
        "Baseline·후보를 같은 절대 요청률로 비교, working set > HBM+DRAM(KV miss 발생). 70%는 [정책]이며 50/70/90% sweep 병기."], "595959")
    panel(2.9, 1.5, "의미: 왜 70%인가 (꼬리가 급증하는 지점)", [
        f"큐 대기는 1/(1−ρ)에 비례해 늘어난다. 이론(M/M/1)에서 ρ 50%→70%는 P99 대기 ×{r_mm_5_7:.1f}, 70%→90%는 ×{r_mm_7_9:.1f}.",
        f"내부 모델도 같은 형태: ρ 50%→70% ×{r_des_5_7:.1f} 후 80%에서 급등(서비스 시간 편차가 커 knee가 일찍 옴).",
        "문헌(2차): 60~70%를 운영 상한으로 권고(arXiv 2608.14967), 70% 부근에서 꼬리가 커지기 시작. 서비스 편차가 크면 더 일찍 꺾임."], "595959")
    # 빈도 표
    rect(s, 7.3, 4.5, 5.8, 0.26, "595959")
    textbox(s, 7.35, 4.52, 5.7, 0.22, "빈도: 실트래픽에서 얼마나 자주 ρ ≥ 70%인가 (BurstGPT)", 10, True, "FFFFFF")
    pct = lambda v: f"{v*100:.1f}%" if v >= 0.001 else f"{v*100:.2f}%"
    rows = [["용량 가정 (1분 요청률)", "시간 기준 ρ ≥ 70%", "요청 기준 ρ ≥ 70%"],
            ["관측 최대치에 맞춤", pct(fr["max"]["0.7"]["time"]), pct(fr["max"]["0.7"]["req"])],
            ["99.9 분위에 맞춤", pct(fr["p99.9"]["0.7"]["time"]), pct(fr["p99.9"]["0.7"]["req"])],
            ["99 분위에 맞춤", pct(fr["p99"]["0.7"]["time"]), pct(fr["p99"]["0.7"]["req"])]]
    table(s, 7.3, 4.76, [2.3, 1.75, 1.75], rows, [0.24] + [0.26] * 3, 8.5, aligns=[PP_ALIGN.LEFT, PP_ALIGN.CENTER, PP_ALIGN.CENTER],
          header_bold=False)
    textbox(s, 7.3, 5.82, 5.8, 0.8, [
        f"트레이스: Azure OpenAI 실서비스 {fr['n']:,} 요청, {fr['days']:.0f}일. 1분 요청률 최대/평균 {fr['peak_to_mean']:.0f}배, 중앙값은 평균의 {fr['median']/fr['mean']*100:.0f}%.",
        "P99는 '상위 1% 요청'이 결정하므로 요청 기준 비율이 1% 이상이면 P99는 고부하 상태가 정한다. 용량을 최대치에 맞추면 요청의 1.2%(10초 창 0.13%)로 경계적이다.",
        "한계: 챗/API 트래픽(agent 세션 아님), 요청 수만 반영(토큰 작업량 제외), 용량은 가정, 오토스케일링 효과 없음 [C]."],
        7.5, False, GRAY)
    footer(s, "출처: arXiv 2401.17644(BurstGPT, GitHub HPMLL/BurstGPT BurstGPT_1.csv), arXiv 2608.14967(검색 요약 기준, 2차), M/M/1 대기 분포 P(Wq>t)=ρe^{-μ(1-ρ)t}. "
              "내부: doc-mk/QA-criteria-v5/qa2_load_rho.py, burstgpt_load_stats.py", page)
    return s


# ---------------------------------------------------------------- data
q1 = M["qa1"]
valid = [i for i, r in enumerate(q1) if r["base"] >= 1.0 and r["R"] > 1.10]
n_sat = sum(1 for r in q1 if r["base"] >= 1.0 and r["R"] <= 1.10)
n_collapse = sum(1 for r in q1 if 0.06 < r["base"] < 1.0)
n_infeas = sum(1 for r in q1 if r["base"] <= 0.06)
assert len(valid) + n_sat + n_collapse + n_infeas == len(q1)
R_valid = [q1[i]["R"] for i in valid]
sc2 = L2["scenarios"]
e2e = [sc2[i]["red_e2e"] * 100 for i in valid]
ttft = [sc2[i]["red_ttft"] * 100 for i in valid]
cand_p99 = [sc2[i]["cand_p99_ttft"] for i in valid]
gm = lambda xs: math.prod(xs) ** (1 / len(xs))
qa3 = {d["name"]: d["SE"] * 100 for d in M["qa3"]}
se_lo, se_hi = min(qa3.values()), max(qa3.values())
q4g = M["qa4"]
rng4 = lambda k: (min(v[k] for v in q4g.values()), max(v[k] for v in q4g.values()))
srcf = VC["src_files"]; kvs = VC["kv_src"]; kvf = VC["kv_feature_src"]
cdf = lambda d, k: f"{d['cdf'][str(k)]*100:.0f}%"
rt = M["qa5_roundtrip"]
TH1 = [1.5, 1.875, 2.25, 2.625, 3.0]
TH2 = [20, 27.5, 35, 42.5, 50]
SE_TH = [90, 91.25, 92.5, 93.75, 95]


def sigma(se, n=16):  # SE(N)=(1+σ)/(1+(N-1)σ), N0=2  →  σ
    se /= 100
    return (1 - se) / (se * (n - 1) - 1)


def se_at(sig, n):
    return (1 + sig) / (1 + (n - 1) * sig) * 100


fmx = lambda v: f"{v:g}x"
fmp = lambda v: f"{v:g}%"
fmn = lambda v: f"{v:g}"
QA = []

# ============================ QA-01
QA.append(dict(
    page=1, title="QA-01. Performance (Throughput) - 별 기준과 근거",
    metric="Max Goodput 배수 R = SLO(TTFT ≤ 2 s, TPOT ≤ 50 ms)를 만족하는 최대 요청률(req/s)의 후보 ÷ Baseline. "
           "Baseline은 HBM-only가 아니라 HBM+DRAM 단순 offloading(LRU, 동기 로드)이다. 시나리오×시스템 쌍별 R의 기하평균. 단위 x(배), 높을수록 좋음(↑).",
    cond_head="조건 (R = 후보 ÷ Baseline)",
    stars=[
        ("R < 1.5x", "Stakeholder 요구사항 미달. 같은 수요에 서버를 2/3로 줄이지 못함"),
        ("R ≥ 1.5x", "Stakeholder 요구사항: SLO 만족 최대 처리량 ≥ Baseline 대비 1.5x. 서버 33% 절감 환산 [C]"),
        ("R ≥ 1.875x", "★(1.5x)과 ★★(2.25x)의 중점. 서버 47% 절감. InferCept 상단 2x에 대응"),
        ("R ≥ 2.25x", "★(1.5x)과 ★★★(3x)의 중점. 서버 56% 절감. KVFlow 최대 2.19x에 대응"),
        ("R ≥ 2.625x", "★★(2.25x)과 ★★★(3x)의 중점. 서버 62% 절감"),
        ("R ≥ 3.0x", "상한. 서버 67% 절감 환산. Pensieve 3.0x (실GPU 다중 턴 서빙 보고 상한)"),
    ],
    scenario=[
        "다수의 agent 세션(동시 요청 클라이언트)",
        "multi-turn 요청 동시 도착: 활성 세션 수백~1,200개, Poisson 도착, 부하 sweep",
        "KV cache 서빙 경로(HBM·DRAM·확장 메모리의 배치·이동·재사용 계층), 후보 vs Baseline",
        "정상 운영, working set > HBM+DRAM 용량. 8×H100급 노드, 70B급 모델, 컨텍스트 16K~32K",
        "KV 재사용 hit는 재계산 없이 로드, SLO 안에서 더 많은 요청을 처리",
        "SLO 만족 Max Goodput ÷ Baseline ≥ 1.5x (★, Stakeholder 요구사항), ≥ 3x (★★★)",
    ],
    chart=dict(
        title="Goodput·처리량 개선 배수 R (Baseline 대비)", vmin=1, vmax=8, ticks=list(range(1, 9)), fmt=fmx,
        marks=[("★ 1.5x", 1.5), ("★★ 2.25x", 2.25), ("★★★ 3x", 3.0)],
        rows=[
            dict(label="InferCept (2402.01869)", cls="lit", lo=1.6, hi=2.0, text="1.6~2x"),
            dict(label="KVFlow (2507.07400)", cls="lit", lo=1.83, hi=2.19, text="1.83~2.19x"),
            dict(label="Pensieve (2312.05516)", cls="lit", lo=1.14, hi=3.0, text="1.14~3.0x"),
            dict(label="vLLM offload (HBM-only 대비)", cls="cond", lo=5.0, text="최대 5x"),
            dict(label="Mooncake 시뮬레이션", cls="cond", lo=6.25, text="+525% (6.25x)", text_left=True),
            dict(label="LMCache (2510.09665)", cls="cond", lo=2.3, hi=8, text="2.3~14x", clip=True),
            dict(label="내부 모델: 단순 offload 대비", cls="int", lo=min(R_valid), hi=max(R_valid), text=f"{min(R_valid):.2f}~{max(R_valid):.2f}x"),
        ]),
    evidence=[
        ("lit", "문헌", "InferCept\narXiv 2402.01869", "tool 호출(augmented LLM) 서빙, 최신 서빙 시스템 대비 처리량", "1.6~2x", "★ 하한 / ★½ 상단"),
        ("lit", "문헌", "KVFlow\narXiv 2507.07400", "멀티에이전트 prefix cache, SGLang(HiCache) 대비 최대", "1.83x / 2.19x", "★½~★★"),
        ("lit", "문헌", "Pensieve\narXiv 2312.05516", "다중 턴 stateful 서빙, vLLM·TensorRT-LLM 대비", "1.14~3.0x", "★★★ 상한"),
        ("cond", "조건부", "vLLM blog 2026-01, Mooncake 시뮬, LMCache", "HBM-only 대비 CPU offload 최대 5x, 시뮬 +525%, LMCache 최대 14x (특정 조건)", "5~14x", "상한 제외"),
        ("int", "내부 [C]", f"qa_evidence_models.py\n(5 seeds, 유효 {len(valid)}/12)", "단순 offload(HBM 400 GB+DRAM 1.5 TB) 대비 4-tier(+CXL, SSD)+prefetch 겹침 70%",
         " / ".join(f"{r:.2f}x" for r in R_valid), star_range(min(R_valid), max(R_valid), TH1)),
    ],
    source=f"출처: arXiv 2402.01869, 2507.07400, 2312.05516, 2510.09665(LMCache, 검색 요약·원문 미확인), vLLM blog 2026-01-08(검색 요약), Mooncake arXiv 2407.00079. "
           f"내부 모델은 12개 시나리오 중 비교유효 {len(valid)}건(포화 {n_sat}, Baseline 붕괴 {n_collapse}(R 9~16x는 상한 제외), Baseline infeasible {n_infeas})이며 실측이 아닌 [C]. "
           "유효 판정(Baseline ≥ 1 req/s, R > 1.10)은 1차 결과를 본 뒤 fit-label 정의로 적용. 문헌은 baseline·workload가 달라 직접 비교 불가.",
))

# ============================ QA-02
QA.append(dict(
    page=2, title="QA-02. Performance (Tail Latency) - 별 기준과 근거",
    metric="P99 지연 감소율 r = 1 − P99(후보) ÷ P99(Baseline). Elapsed Time = 요청 도착 ~ 마지막 토큰(큐 대기 + KV 로드/재계산 + decode). "
           "고부하 = 서버 이용률 ρ 70%(근거: 다음 장), SLO 만족 조건. Baseline은 QA-01과 같음. 단위 %, 높을수록 좋음(↑). r은 속도 1/(1−r)배와 같다(20% → 1.25x, 50% → 2x).",
    cond_head="조건 (r = P99 감소율)",
    stars=[
        ("r < 20%", "사용자 체감 성능 개선 기준 미달. 시간 지각 JND(≈7~21%) 이내라 개선을 확신하기 어려움"),
        ("r ≥ 20%", "사용자 체감 성능 개선 기준(요구사항). JND 상단(≈21%)에 해당하는 체감 가능 하한 [문헌 2차]. 속도 1.25x"),
        ("r ≥ 27.5%", "★(20%)과 ★★(35%)의 중점. 속도 1.38x"),
        ("r ≥ 35%", "★(20%)과 ★★★(50%)의 중점. 속도 1.54x"),
        ("r ≥ 42.5%", "★★(35%)과 ★★★(50%)의 중점. 속도 1.74x"),
        ("r ≥ 50%", "상한 [정책]. 지연이 절반(2x faster). vLLM offload의 TTFT ×2 하한과 일치"),
    ],
    scenario=[
        "다수의 agent 세션, 사용자(응답을 기다리는 클라이언트)",
        "고부하 요청 폭주: 서버 이용률 ρ 70%(Baseline 기준), working set > HBM+DRAM",
        "KV cache 서빙 경로(요청 큐 → KV 로드/재계산 → prefill → decode)",
        "정상 운영·고부하, SLO(TTFT ≤ 2 s, TPOT ≤ 50 ms) 충족 조건, 70B급 모델, 컨텍스트 16K~64K",
        "KV tier 이동·prefetch로 miss 재계산과 큐 대기를 줄여 최악 지연을 단축",
        "Elapsed Time P99 감소율 ≥ 20% vs Baseline (★, 사용자 체감 성능 개선 기준), ≥ 50% (★★★), SLO 만족 시",
    ],
    chart=dict(
        title="Elapsed Time(P99) 감소율 r (Baseline 대비, %)", vmin=0, vmax=100, ticks=[0, 20, 40, 60, 80, 100], fmt=fmp,
        marks=[("★ 20%", 20), ("★★ 35%", 35), ("★★★ 50%", 50)],
        rows=[
            dict(label="시간 지각 JND (Weber, 2차 자료)", cls="lit", lo=7, hi=21, text="7~21%"),
            dict(label="vLLM offload TTFT ×2~22 (HBM-only)", cls="cond", lo=50, hi=95.5, text="50~95%", text_left=True),
            dict(label="내부 모델: E2E P99 감소", cls="int", lo=min(e2e), hi=max(e2e), text=f"{min(e2e):.0f}~{max(e2e):.0f}%"),
            dict(label="내부 모델: TTFT P99 감소", cls="int", lo=min(ttft), hi=max(ttft), text=f"{min(ttft):.0f}~{max(ttft):.0f}%"),
        ]),
    evidence=[
        ("lit", "문헌", "Calibre 'perceived performance' 등 (2차)", "시간 지각 Weber 분수: 1 s 규모 JND ≈ 0.17~0.21, 일부 자료는 7~18%", "7~21%", "★ 근거"),
        ("lit", "문헌", "web.dev 'Milliseconds make millions' (Deloitte×Google 2020)", "모바일 0.1 s 속도 개선 → 리테일 전환율 +8.4% (37개 브랜드)", "+8.4% / 0.1 s", "지연 민감도 참고"),
        ("cond", "조건부", "vLLM blog 2026-01 (KV offloading connector)", "CPU offload로 TTFT ×2~×22↓ (HBM-only 대비, 프롬프트 길이 의존)", "50~95%", "★★★ 하한 참고"),
        ("int", "내부 [C]", f"qa2_load_rho.py (유효 {len(valid)}/12)", f"ρ 70%, 5 seeds. 후보 P99 TTFT {min(cand_p99):.1f}~{max(cand_p99):.1f} s로 SLO 2 s 충족",
         f"E2E {min(e2e):.0f}~{max(e2e):.0f}%\nTTFT {min(ttft):.0f}~{max(ttft):.0f}%",
         f"E2E {star_range(min(e2e), max(e2e), TH2)}\nTTFT {star_range(min(ttft), max(ttft), TH2)}"),
    ],
    source="출처: calibreapp.com/blog/perceived-performance(2차), web.dev/case-studies/milliseconds-make-millions, vLLM blog 2026-01-08(검색 요약). 내부: doc-mk/QA-criteria-v5/qa2_load_rho.py. "
           "JND는 1차 심리물리 논문 미확인이며 LLM 스트리밍 응답에 그대로 적용되는지 검증되지 않았다. 체감은 과업 의존(arXiv 2604.06183, 2608.24189: 검색 요약). "
           "이전 정의(Baseline SLO 한계 처리량의 70%)는 이 모델에서 ρ≈0.34라 폐기했고 그 값은 qa_evidence_out.json에 보존.",
))

# ============================ QA-03 (안 B: ★ 90% / ★★★ 95%)
sg = [sigma(v) * 100 for v in SE_TH]
QA.append(dict(
    page=4, title="QA-03. Scalability - 별 기준과 근거",
    metric=f"σ = 조율 계층(router·metadata·공유 tier)이 요청 처리 시간 중 직렬로 차지하는 비중(USL, 노드 간 경합 κ≈0 가정). SE(N) = Goodput(N) ÷ ((N/2) × Goodput(2)). "
           "비-target GPU 4노드에서 SE(2~4)를 실측해 σ를 피팅하고 target 16노드 SE는 외삽 [C]. 별은 σ(노드 수 무관)로 판정하고 SE(16)은 환산값이다. SE는 높을수록 좋음(↑).",
    cond_head="조건 (SE(N=16) ↔ σ 상한)",
    stars=[
        (f"SE ≤ 90%\n(σ > {sg[0]:.2f}%)", "조율 계층 손실이 10% 초과. 중앙 router·단일 공유 pool 구성은 이 구간(내부 모델 68~72%)"),
        (f"SE > 90%\n(σ ≤ {sg[0]:.2f}%)", "문헌 보고 값(대규모 4k~65k GPU에서도 80~97%)을 16노드 규모로 보정. QA-01 ★ 이득 1.5x가 확장 후 1.35x 이상 유지"),
        (f"SE > 91.25%\n(σ ≤ {sg[1]:.2f}%)", f"★(90%)과 ★★(92.5%)의 중점. 유효 14.6노드분. QA-01 순이득 1.37x"),
        (f"SE > 92.5%\n(σ ≤ {sg[2]:.2f}%)", "★(90%)과 ★★★(95%)의 중점. 유효 14.8노드분"),
        (f"SE > 93.75%\n(σ ≤ {sg[3]:.2f}%)", "★★(92.5%)과 ★★★(95%)의 중점. 유효 15.0노드분"),
        (f"SE > 95%\n(σ ≤ {sg[4]:.2f}%)", "상한. 조율 계층이 요청 처리의 0.38% 이하. MFC 95%(65,536 GCD), Athena++ 95~97%와 동급"),
    ],
    scenario=[
        "운영자(자원 증설) / 서비스 사용자(부하 증가)",
        "노드 수를 2 → 3 → 4로 증설(요청 도착률도 노드 수에 비례) 후 16노드로 외삽",
        "분산 KV 조율 계층(전역 router·metadata·공유 tier)과 노드별 서빙 경로",
        "정상 운영, N0 = 2 기준, target과 다른 사양의 GPU 4노드에서 측정, 공유 tier 경합 미반영",
        "증설한 노드 수만큼 SLO 만족 처리량이 선형에 가깝게 증가",
        f"피팅 σ ≤ {sg[0]:.2f}% (★) ↔ SE(16) > 90%, σ ≤ {sg[4]:.2f}% (★★★) ↔ SE(16) > 95%",
    ],
    chart=dict(
        title="Scaling Efficiency SE(N=16) (%) — 문헌은 대규모 weak scaling", vmin=60, vmax=100, ticks=[60, 70, 80, 90, 100], fmt=fmp, levels=3,
        marks=[("★ 90%", 90), ("★★ 92.5%", 92.5), ("★★★ 95%", 95)],
        rows=[
            dict(label="AthenaK Frontier 65,536 GPU", cls="lit", lo=80, text="80%", text_left=True),
            dict(label="Athena++ 8→250 노드", cls="lit", lo=95, hi=97, text="95~97%", text_left=True),
            dict(label="MFC Frontier 65,536 GCD", cls="lit", lo=95, text="95%", text_left=True),
            dict(label="LLM 서빙 2→8 GPU (2605.19775)", cls="lit", lo=100, text="≈100% (소규모)", text_left=True),
            dict(label="내부: 중앙 router 20 ms/요청", cls="int", lo=qa3["노드 로컬 tier + 중앙 router 20 ms/요청"], text=f"{qa3['노드 로컬 tier + 중앙 router 20 ms/요청']:.0f}%"),
            dict(label="내부: 단일 공유 pool(16노드)", cls="int", lo=qa3["전 노드 단일 공유 pool (shard=16)"], text=f"{qa3['전 노드 단일 공유 pool (shard=16)']:.0f}%"),
            dict(label="내부: pool shard(4노드/pool)", cls="int", lo=qa3["pool shard 4노드당 1개"], text=f"{qa3['pool shard 4노드당 1개']:.0f}%", text_left=True),
        ]),
    evidence=[
        ("lit", "문헌", "AthenaK\narXiv 2409.16053", "Frontier 65,536 GPU weak scaling 80% (MHD 시뮬레이션 코드)", "80%", "대규모 하한"),
        ("lit", "문헌", "MFC 2509.13575\nAthena++ 2005.06651", "MFC Frontier 65,536 GCD weak 95%, Athena++ 8→250 노드 95~97%", "95~97%", "★★★ 근거"),
        ("lit", "문헌", "arXiv 2605.19775\nLLM-Pilot 2410.02425", "LLM 서빙 8B 2→8 GPU ≈4x, 13B ≤8 pod 근사 선형", "≈100%", "소규모, 외삽 불가"),
        ("calc", "원리", "Amdahl 1967, Gunther USL 2008", f"SE = (1+σ)/(1+(N−1)σ). 90% → σ {sg[0]:.2f}%, 95% → σ {sg[4]:.2f}%. 4노드 SE는 {se_at(sg[0]/100, 4):.1f}~{se_at(sg[4]/100, 4):.1f}%",
         "σ 환산", "별 경계 환산"),
        ("int", "내부 [C]", "공유 tier 구성 sweep", "16노드, 로컬 처리 0.2 s, remote hit 30%, KV 10.7 GB, pool 200 GB/s", f"{se_lo:.0f}~{se_hi:.0f}%", "☆~★★★ 구성 의존"),
    ],
    source="출처: arXiv 2409.16053(AthenaK), 2509.13575(MFC), 2005.06651(Athena++), 2605.19775, 2410.02425(LLM-Pilot)(모두 검색 요약 기준, 원문 미확인), Amdahl 1967, Gunther 2008. "
           "문헌은 weak scaling 병렬 효율이라 서빙 SE와 정의가 다르다 [유추]. 4노드 SE 오차는 외삽 시 크게 증폭되므로(SE(4) ±1 point → SE(16) 약 80~90%) 별 판정은 σ의 신뢰구간으로 하고 경계 걸침을 표기한다. "
           "내부: doc-mk/QA-criteria-v5/qa_evidence_models.py.",
))

# ============================ QA-04 (vLLM commit 분포 기준)
QA.append(dict(
    page=5, title="QA-04. Modifiability - 별 기준과 근거",
    metric=f"변경 module 수 = 변경 시나리오(S1~S5) 1건을 구현했을 때 수정·추가·삭제되는 소스 파일 수(테스트·문서 제외), 시나리오 평균. "
           f"기준은 vLLM commit의 변경 파일 수 분포(vllm-project/vllm main 최근 {VC['commits']:,} commit, {VC['date_from']}~{VC['date_to']})에 맞췄다. 단위 개, 낮을수록 좋음(↓).",
    cond_head="조건 (변경 module 수)",
    stars=[
        ("≥ 7개", f"vLLM 소스 commit의 약 {100 - srcf['cdf']['6']*100:.0f}%만 해당하는 큰 변경(요구사항 기준 초과)"),
        ("≤ 6개", f"요구사항: vLLM commit의 80%가 6 file 이하. 계수: 소스 commit의 {cdf(srcf, 6)}"),
        ("≤ 5개", f"★(6)과 ★★(4)의 중점. vLLM 소스 commit의 {cdf(srcf, 5)} (p80 = {srcf['p80']:g})"),
        ("≤ 4개", f"★(6)과 ★★★(2)의 중점. vLLM 소스 commit의 {cdf(srcf, 4)}"),
        ("≤ 3개", f"★★(4)과 ★★★(2)의 중점. vLLM 소스 commit의 {cdf(srcf, 3)}"),
        ("≤ 2개", f"상한. vLLM 소스 commit의 {cdf(srcf, 2)}가 해당(중앙값 {srcf['median']:g}). SWE-bench 해결 패치 평균 1.7 file"),
    ],
    scenario=[
        "제품 로드맵·운영 요구 → 개발자(또는 코드 에이전트)",
        "변경 S1 신규 메모리 tier(CXL → HBF/ScHBM) · S2 이동·배치 정책 교체(LRU → hotness 예측) · S3 신규 data type(LoRA·MoE expert·RAG 캐시를 tier 관리 대상에 추가) · S4 신규 이벤트(tool-call 종료 시 prefetch trigger) · S5 신규 KV 코덱(압축·양자화)",
        "서빙 경로의 메모리 계층 추상화(connector·manager·scheduler·worker)",
        "개발 시점. 현행 vLLM + 제안 구조에 구현, 기존 unit test 통과(회귀 없음)",
        "변경이 새 module 추가와 등록 지점 안에 머물고 서빙 경로 핵심 코드는 수정하지 않음",
        "변경 module 수(소스 file) 시나리오 평균 ≤ 6 (★, vLLM commit의 80%가 6 file 이하), ≤ 2 (★★★)",
    ],
    scenario_h=[0.3, 0.74, 0.3, 0.3, 0.3, 0.3],
    chart=dict(
        title="변경 module 수 (소스 file, 낮을수록 좋음)", vmin=0, vmax=10, ticks=[0, 2, 4, 6, 8, 10], fmt=fmn,
        marks=[("★★★ ≤2", 2), ("★★ ≤4", 4), ("★ ≤6", 6)],
        rows=[
            dict(label="SWE-bench 패치 평균 (2310.06770)", cls="lit", lo=1.7, text="1.7"),
            dict(label="vLLM 소스 commit (중앙~84%)", cls="int", lo=srcf["median"], hi=6, text=f"중앙 {srcf['median']:g}, {cdf(srcf, 6)} ≤ 6"),
            dict(label="vLLM KV 기능추가형 commit 중앙", cls="int", lo=kvf["median"], text=f"{kvf['median']:g} (n={kvf['n']})", text_left=True),
            dict(label="vLLM backend 추가: 소스 file (계수)", cls="int", lo=rng4("src_only")[0], hi=rng4("src_only")[1], text=f"{rng4('src_only')[0]}~{rng4('src_only')[1]}"),
            dict(label="connector base interface 변경 파급", cls="int", lo=33, text="33 file", clip=True, text_left=True),
        ]),
    evidence=[
        ("int", "내부 계수", "vLLM 최근 commit, 소스 file", f"n={srcf['n']:,} (테스트·문서 제외). 요구사항의 '80%가 6 file 이하' 확인",
         f"중앙 {srcf['median']:g}\n≤6: {cdf(srcf, 6)}", "★ 근거"),
        ("int", "내부 계수", "KV connector·offload commit, 소스", f"n={kvs['n']}, 같은 기간", f"중앙 {kvs['median']:g}\n≤6: {cdf(kvs, 6)}", "★ 근거 보강"),
        ("int", "내부 계수", "KV 기능 추가형 commit", f"제목 키워드로 고른 {kvf['n']}건(표본 작음). S1~S5와 성격 유사", f"중앙 {kvf['median']:g}\n≤6: {cdf(kvf, 6)}", "★ 경계, ★★★은 상위"),
        ("lit", "문헌", "SWE-bench arXiv 2310.06770", "실제 GitHub issue 해결 패치 2,294건: 평균 수정 파일 1.7개", "1.7 file", "★★★ (≤ 2)"),
        ("int", "내부 계수", "이 저장소 grep", f"backend 추가에 닿는 소스 {rng4('src_only')[0]}~{rng4('src_only')[1]} file, connector base interface 참조 33 file", "4(중앙) / 33", "As-Is ★~☆ / interface ☆"),
    ],
    source="출처: vllm-project/vllm main git log(squash merge라 commit≈PR로 가정, 봇·revert 포함), arXiv 2310.06770(SWE-bench), 품질 요구사항 표(QA-04). "
           "한계: 3주 표본, 기능 추가형 15건은 제목 키워드 선별, 시나리오별 실제 구현·측정은 아직 하지 않았다. 내부: doc-mk/QA-criteria-v5/vllm_commit_stats.py, qa_evidence_out.json(qa4).",
))

# ============================ QA-05 (CI 상한 판정)
QA.append(dict(
    page=6, title="QA-05. Functional Correctness - 별 기준과 근거",
    metric="F1 상대 하락률 = (F1_baseline − F1_후보) ÷ F1_baseline, Baseline = 재사용 전 full recompute. 본 시스템은 압축을 쓰지 않으므로 이동·복원·재사용 경로가 대상이다(무손실 경로는 bit-exact 확인). "
           "판정은 문항별 paired bootstrap으로 얻은 하락률 95% 신뢰구간의 상한이 기준 미만일 때 해당 별. 단위 %(상대), 낮을수록 좋음(↓).",
    cond_head="조건 (하락률 95% CI 상한)",
    stars=[
        ("상한 ≥ 1%", "Stakeholder 요구사항 초과: 1%를 넘을 가능성을 배제하지 못함"),
        ("상한 < 1%", "요구사항(품질 요구사항 표): Baseline 대비 F1 감소율 1% 이하. 소유자 허용 한도"),
        ("상한 < 0.775%", "★(1%)과 ★★(0.55%)의 중점"),
        ("상한 < 0.55%", "★(1%)과 ★★★(0.1%)의 중점"),
        ("상한 < 0.325%", "★★(0.55%)과 ★★★(0.1%)의 중점"),
        ("상한 < 0.1%", "상한 [정책]. 사실상 무손실. 입증에는 평가 문항 수가 많이 필요(CI 폭이 문항 수에 반비례)"),
    ],
    scenario=[
        "서빙 엔진 운영자(KV 재사용·이동 경로 변경)",
        "KV cache를 tier 간 이동·복원·재사용한 뒤 추론 요청 수행(압축 미사용)",
        "KV 이동·복원·재사용 경로, 추론 결과(task별 F1)",
        "동일 task·dataset·모델·precision, greedy decoding, 고정 seed, 정상 운영",
        "재사용 경로를 거쳐도 추론 결과가 full recompute와 동등",
        "F1 하락률 95% CI 상한 < 1% (★, 요구사항), < 0.1% (★★★). 이동·복원은 bit-exact(0%)",
    ],
    chart=dict(
        title="F1 상대 하락률 (재사용 전 full recompute 대비, %)", vmin=0, vmax=5, ticks=[0, 1, 2, 3, 4, 5], fmt=fmp, levels=3,
        marks=[("★★★ 0.1%", 0.1), ("★★ 0.55%", 0.55), ("★ 1%", 1.0)],
        rows=[
            dict(label="이동·복원·재사용 경로", cls="int", lo=0.0, text="0% (bit-exact)"),
            dict(label="요구사항·소유자 허용 한도", cls="calc", lo=1.0, text="1%"),
            dict(label="(참고) 압축 시 KVmix 2-bit", cls="lit", lo=4.53, text="4.53%", text_left=True),
        ]),
    evidence=[
        ("calc", "요구사항", "품질 요구사항 표, 소유자 결정(2026-10-09)", "LLM 출력 정확도(F1) Baseline 대비 감소율 1% 이하", "1%", "★ 근거"),
        ("lit", "문헌", "KVQuant 2401.18079, KVmix 2506.08018", "(참고) 손실 압축: 3-bit ppl 저하 < 0.1, 2-bit급 LongBench 평균 상대 손실 4.53% (검색 요약)", "ppl<0.1 / 4.53%", "압축 미사용: 참고"),
        ("lit", "문헌", "vLLM FP8 KV-cache blog (2026-04)", "FP8 KV near-baseline, 장문 accumulation 오류 수정 후 BF16 수준 회복", "정성", "★ 가능성(참고)"),
        ("lit", "문헌", "Thinking Machines Lab (2025-09)", "batch-invariant가 아닌 kernel은 같은 입력에도 출력 변동 → 재사용 경로 비트 차이 가능", "정성", "★★★ 잡음 유의"),
        ("int", "내부 검증", "qa_evidence_models.py", f"tier 왕복 복사(직렬화→복원) 후 비트 비교: fp16 KV block {rt['blocks']:,}개(NaN·denormal 포함)", f"불일치 {rt['mismatch']}", "무손실 경로 0%"),
    ],
    source="출처: arXiv 2401.18079, 2506.08018(검색 요약 기준), vLLM blog 2026-04-22(검색 요약), Thinking Machines Lab 'Defeating Nondeterminism in LLM Inference'(2차 요약), 품질 요구사항 표(QA-05). "
           "내부 검증은 복사 정확성(메모리 왕복)만 보이며 평가 데이터셋 F1은 측정하지 않았다. 0.1%는 문항 수가 부족하면 CI 상한으로 입증하기 어렵다.",
))


def main(src, dst):
    prs = Presentation(src)
    tmpl = prs.slides[1]
    layout = tmpl.slide_layout
    names = {sh.name: sh for sh in tmpl.shapes}
    nav = [names[n] for n in ("Chevron 2", "Chevron 3", "Chevron 4", "Chevron 5", "Chevron 6", "Rectangle 7", "Rectangle 8")]
    n_old = len(prs.slides)
    order = {q["page"]: q for q in QA}
    build_slide(prs, layout, nav, order[1])
    build_slide(prs, layout, nav, order[2])
    build_highload(prs, layout, nav, 3)
    for p in (4, 5, 6):
        build_slide(prs, layout, nav, order[p])
    lst = prs.slides._sldIdLst
    for sldId in list(lst)[:n_old]:
        prs.part.drop_rel(sldId.rId)
        lst.remove(sldId)
    prs.save(dst)


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
