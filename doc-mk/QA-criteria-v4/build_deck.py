"""첨부 덱(base/DP-QA-attached.pptx)을 베이스로 QA 평가 기준 덱 v4를 만든다.

기존 자료는 건드리지 않고 이 폴더에만 쓴다.
    python3 -I build_deck.py            # DP-QA-criteria-v4.pptx 생성
"""
import copy
import math
import os
import re

from lxml import etree
from pptx import Presentation
from pptx.dml.color import RGBColor
from pptx.enum.shapes import MSO_CONNECTOR, MSO_SHAPE
from pptx.enum.text import MSO_ANCHOR, PP_ALIGN
from pptx.oxml.ns import qn
from pptx.util import Emu, Inches, Pt

import criteria_data as cd

HERE = os.path.dirname(os.path.abspath(__file__))
BASE = os.path.join(HERE, "base", "DP-QA-attached.pptx")
OUT = os.path.join(HERE, "DP-QA-criteria-v4.pptx")

FONT = "맑은 고딕"
NAVY = "2F5597"
BAND_FILL = {0: "EDEDED", 1: "FBE0D6", 1.5: "FDE9D2", 2: "FFF2CC", 2.5: "EDF3D5", 3: "E2EFDA"}
STYLE_COLOR = {"lit": "2F5597", "req": "C00000", "calc": "7F7F7F", "excl": "A6A6A6"}


# ============================================================ 저수준 헬퍼
def rgb(h):
    return RGBColor.from_string(h)


def _font(run, size, bold=False, color="000000", name=FONT):
    f = run.font
    f.size = Pt(size)
    f.bold = bold
    f.color.rgb = rgb(color)
    f.name = name
    rPr = run._r.get_or_add_rPr()
    for old in rPr.findall(qn("a:ea")):
        rPr.remove(old)
    ea = etree.SubElement(rPr, qn("a:ea"))
    ea.set("typeface", name)


def add_runs(par, runs, size, bold=False, color="000000"):
    """runs: str 또는 [(text, {size,bold,color}), ...]"""
    if isinstance(runs, str):
        runs = [(runs, {})]
    for text, o in runs:
        r = par.add_run()
        r.text = text
        _font(r, o.get("size", size), o.get("bold", bold), o.get("color", color))


def tbox(slide, x, y, w, h, paras, size=10, bold=False, color="000000", align="l", anchor="t",
         name=None, line_spacing=None, margins=(0.08, 0.04, 0.08, 0.04), space_after=0, wrap=True):
    sh = slide.shapes.add_textbox(Inches(x), Inches(y), Inches(w), Inches(h))
    if name:
        sh.name = name
    tf = sh.text_frame
    tf.word_wrap = wrap
    tf.margin_left, tf.margin_top, tf.margin_right, tf.margin_bottom = [Inches(m) for m in margins]
    tf.vertical_anchor = {"t": MSO_ANCHOR.TOP, "m": MSO_ANCHOR.MIDDLE, "b": MSO_ANCHOR.BOTTOM}[anchor]
    if isinstance(paras, str):
        paras = [paras]
    for i, runs in enumerate(paras):
        p = tf.paragraphs[0] if i == 0 else tf.add_paragraph()
        p.alignment = {"l": PP_ALIGN.LEFT, "c": PP_ALIGN.CENTER, "r": PP_ALIGN.RIGHT}[align]
        if line_spacing:
            p.line_spacing = line_spacing
        p.space_after = Pt(space_after)
        add_runs(p, runs, size, bold, color)
    return sh


def rect(slide, x, y, w, h, fill=None, line=None, line_w=0.5, shape=MSO_SHAPE.RECTANGLE, name=None):
    sh = slide.shapes.add_shape(shape, Inches(x), Inches(y), Inches(w), Inches(h))
    if name:
        sh.name = name
    sh.shadow.inherit = False
    if fill:
        sh.fill.solid()
        sh.fill.fore_color.rgb = rgb(fill)
    else:
        sh.fill.background()
    if line:
        sh.line.color.rgb = rgb(line)
        sh.line.width = Pt(line_w)
    else:
        sh.line.fill.background()
    return sh


def hline(slide, x1, y1, x2, y2, color="BFBFBF", w=0.5, dash=False):
    c = slide.shapes.add_connector(MSO_CONNECTOR.STRAIGHT, Inches(x1), Inches(y1), Inches(x2), Inches(y2))
    c.line.color.rgb = rgb(color)
    c.line.width = Pt(w)
    if dash:
        ln = c.line._get_or_add_ln()
        d = etree.SubElement(ln, qn("a:prstDash"))
        d.set("val", "dash")
    return c


def remove(shape):
    el = shape._element
    el.getparent().remove(el)


def shape_by_name(slide, name, nth=0):
    hits = [s for s in slide.shapes if s.name == name]
    return hits[nth] if len(hits) > nth else None


def text_width(text, size):
    """대략적인 글자 폭(inch). 한글/전각은 size pt, 라틴·숫자는 약 0.55배."""
    w = 0.0
    for ch in text:
        w += (1.0 if ord(ch) > 0x2E80 or ch in "★☆●○◆▲▼×≤≥≈→" else 0.55) * size / 72.0
    return w


# ============================================================ 표 헬퍼
NO_STYLE = "{2D5ABB26-0587-4C30-8999-92F81FD0307C}"


def _cell_fmt(cell, fill, margins=(54864, 22860, 54864, 22860), anchor="ctr", border="BFBFBF"):
    tcPr = cell._tc.get_or_add_tcPr()
    for ch in list(tcPr):
        tcPr.remove(ch)
    tcPr.set("marL", str(margins[0]))
    tcPr.set("marT", str(margins[1]))
    tcPr.set("marR", str(margins[2]))
    tcPr.set("marB", str(margins[3]))
    tcPr.set("anchor", anchor)
    for tag in ("a:lnL", "a:lnR", "a:lnT", "a:lnB"):
        ln = etree.SubElement(tcPr, qn(tag))
        ln.set("w", "6350")
        sf = etree.SubElement(ln, qn("a:solidFill"))
        etree.SubElement(sf, qn("a:srgbClr")).set("val", border)
    if fill:
        sf = etree.SubElement(tcPr, qn("a:solidFill"))
        etree.SubElement(sf, qn("a:srgbClr")).set("val", fill)


def add_table(slide, x, y, colw, rows, rowh, header_fill=NAVY, fills=None, size=8.5, aligns=None,
              header_size=9, name="tbl"):
    """rows[0]은 헤더. 각 셀은 str 또는 [para, ...], para = str | [(text, opts)...]"""
    nr, nc = len(rows), len(colw)
    gf = slide.shapes.add_table(nr, nc, Inches(x), Inches(y), Inches(sum(colw)), Inches(sum(rowh)))
    gf.name = name
    tbl = gf.table
    tblPr = tbl._tbl.tblPr
    for a in ("firstRow", "bandRow"):
        tblPr.set(a, "0")
    sid = tblPr.find(qn("a:tableStyleId"))
    if sid is None:
        sid = etree.SubElement(tblPr, qn("a:tableStyleId"))
    sid.text = NO_STYLE
    for i, w in enumerate(colw):
        tbl.columns[i].width = Inches(w)
    for i, h in enumerate(rowh):
        tbl.rows[i].height = Inches(h)
    for ri, row in enumerate(rows):
        for ci, val in enumerate(row):
            cell = tbl.cell(ri, ci)
            hdr = ri == 0
            fill = header_fill if hdr else (fills[ri - 1] if fills else None)
            _cell_fmt(cell, fill)
            paras = val if isinstance(val, list) and val and not isinstance(val[0], tuple) else [val]
            tf = cell.text_frame
            tf.word_wrap = True
            for pi, para in enumerate(paras):
                p = tf.paragraphs[0] if pi == 0 else tf.add_paragraph()
                al = "c" if hdr else (aligns[ci] if aligns else "l")
                p.alignment = {"l": PP_ALIGN.LEFT, "c": PP_ALIGN.CENTER}[al]
                add_runs(p, para, header_size if hdr else size, bold=hdr,
                         color="FFFFFF" if hdr else "000000")
    return gf


# ============================================================ 구간 그래프
def band_chart(slide, x, y, w, axis, bands, markers, title=None, row_h=0.205, label_size=7.2,
               tick_fmt="%g", legend=True):
    """band_chart: 별 구간 띠 + 문헌/요구 근거 점·범위.

    axis = dict(min, max, log=False, ticks=[...], unit='')
    bands = [(lo, hi, star_value)]  (star_value 0 = 미충족)
    markers = [dict(kind='point'|'range', v=..|(lo,hi), style='lit'|'req'|'calc'|'excl', label=str)]
    반환: 그래프 하단 y
    """
    amin, amax, log = axis["min"], axis["max"], axis.get("log", False)
    px0, pw = x + 0.05, w - 0.1

    def X(v):
        v = min(max(v, amin), amax)
        t = (math.log(v) - math.log(amin)) / (math.log(amax) - math.log(amin)) if log else (v - amin) / (amax - amin)
        return px0 + t * pw

    cy = y
    if title:
        tbox(slide, x, cy, w, 0.24, [[(title, {"bold": True, "color": NAVY})]], size=9.5, margins=(0.02, 0.02, 0.02, 0.0))
        cy += 0.26
    strip_h = 0.3
    for lo, hi, s in bands:
        bx0, bx1 = X(lo), X(hi)
        if bx1 - bx0 < 0.01:
            continue
        rect(slide, bx0, cy, bx1 - bx0, strip_h, fill=BAND_FILL[s], line="FFFFFF", line_w=0.75)
        tbox(slide, bx0, cy, bx1 - bx0, strip_h, [[(cd.fmt_star(s) if s else "☆ 미충족", {"bold": True})]],
             size=8.5 if (bx1 - bx0) > 0.6 else 7.5, align="c", anchor="m", margins=(0, 0, 0, 0))
    cy += strip_h
    # 눈금
    for t in axis["ticks"]:
        tbox(slide, X(t) - 0.35, cy, 0.7, 0.16, tick_fmt % t + axis.get("unit", ""), size=6.8, color="595959",
             align="c", margins=(0, 0, 0, 0))
    cy += 0.17
    rows_top = cy
    n = len(markers)
    bottom = rows_top + n * row_h + 0.02
    # 경계 가이드선
    for lo, hi, s in bands:
        if lo > amin:
            hline(slide, X(lo), rows_top - 0.02, X(lo), bottom, color="D0D0D0", w=0.5, dash=True)
    for i, m in enumerate(markers):
        ry = rows_top + i * row_h
        col = STYLE_COLOR[m["style"]]
        cyc = ry + row_h / 2
        if m["kind"] == "point":
            xs = X(m["v"])
            xe = xs
            if m["style"] == "req":
                sh = rect(slide, xs - 0.065, cyc - 0.065, 0.13, 0.13, fill=col, shape=MSO_SHAPE.DIAMOND)
            elif m["style"] == "calc":
                sh = rect(slide, xs - 0.065, cyc - 0.06, 0.13, 0.12, fill=col, shape=MSO_SHAPE.ISOSCELES_TRIANGLE)
            elif m["style"] == "excl":
                sh = rect(slide, xs - 0.055, cyc - 0.055, 0.11, 0.11, fill="FFFFFF", line=col, line_w=1.25, shape=MSO_SHAPE.OVAL)
            else:
                sh = rect(slide, xs - 0.055, cyc - 0.055, 0.11, 0.11, fill=col, shape=MSO_SHAPE.OVAL)
        else:
            lo, hi = m["v"]
            xs, xe = X(lo), X(hi)
            if m["style"] == "excl":
                rect(slide, xs, cyc - 0.04, max(xe - xs, 0.05), 0.08, fill="FFFFFF", line=col, line_w=1.0)
            else:
                rect(slide, xs, cyc - 0.04, max(xe - xs, 0.05), 0.08, fill=col)
            for ex in (xs, xe):
                hline(slide, ex, cyc - 0.07, ex, cyc + 0.07, color=col, w=1.0)
        label_color = "7F7F7F" if m["style"] == "excl" else "262626"
        avail_r = px0 + pw + 0.05 - (xe + 0.1)
        avail_l = (xs - 0.1) - (x - 0.02)
        use_right = avail_r >= avail_l or avail_r >= text_width(m["label"], label_size) + 0.05
        avail = avail_r if use_right else avail_l
        fs = label_size
        while text_width(m["label"], fs) + 0.05 > avail and fs > 5.8:
            fs -= 0.2
        lw = text_width(m["label"], fs) + 0.1
        if use_right:
            tbox(slide, xe + 0.08, ry, lw, row_h, m["label"], size=fs, color=label_color, anchor="m",
                 margins=(0, 0, 0, 0), wrap=False)
        else:
            tbox(slide, xs - 0.08 - lw, ry, lw, row_h, m["label"], size=fs, color=label_color, anchor="m",
                 align="r", margins=(0, 0, 0, 0), wrap=False)
    cy = bottom + 0.03
    if legend:
        lx = x + 0.02
        items = [("lit", "문헌 보고값(up to)"), ("req", "Stakeholder·시나리오 요구"), ("calc", "계산·정책"),
                 ("excl", "참고(극단 조건·압축 혼합, 앵커 제외)")]
        for st, lab in items:
            col = STYLE_COLOR[st]
            if st == "req":
                rect(slide, lx, cy + 0.045, 0.1, 0.1, fill=col, shape=MSO_SHAPE.DIAMOND)
            elif st == "calc":
                rect(slide, lx, cy + 0.045, 0.1, 0.09, fill=col, shape=MSO_SHAPE.ISOSCELES_TRIANGLE)
            elif st == "excl":
                rect(slide, lx, cy + 0.045, 0.09, 0.09, fill="FFFFFF", line=col, line_w=1.0, shape=MSO_SHAPE.OVAL)
            else:
                rect(slide, lx, cy + 0.045, 0.09, 0.09, fill=col, shape=MSO_SHAPE.OVAL)
            tw = text_width(lab, 7) + 0.1
            tbox(slide, lx + 0.13, cy, tw, 0.18, lab, size=7, color="404040", anchor="m", margins=(0, 0, 0, 0), wrap=False)
            lx += 0.13 + tw + 0.12
        cy += 0.2
    return cy


# ============================================================ 평가 기준 페이지 공통
def set_text_keep_first(shape, paras):
    """텍스트 박스의 단락들을 새 텍스트로 교체(첫 단락·첫 run의 서식 유지)."""
    tf = shape.text_frame
    p0 = tf.paragraphs[0]
    tmpl_pPr = copy.deepcopy(p0._p.find(qn("a:pPr"))) if p0._p.find(qn("a:pPr")) is not None else None
    for p in tf.paragraphs[1:]:
        p._p.getparent().remove(p._p)
    for r in list(p0.runs):
        p0._p.remove(r._r)
    first = True
    for runs in paras:
        if first:
            p = p0
            first = False
        else:
            newp = copy.deepcopy(p0._p)
            for r in newp.findall(qn("a:r")):
                newp.remove(r)
            tf._txBody.append(newp)
            p = tf.paragraphs[-1]
        add_runs(p, runs, 10)


def page_chrome(slide, title, subtitle, src):
    t = shape_by_name(slide, "title")
    set_text_keep_first(t, [[(title, {"size": 22, "bold": True, "color": NAVY})]])
    s = None
    for sh in slide.shapes:
        if sh.name == "subtitle" and sh.top < Inches(0.9):
            s = sh
    set_text_keep_first(s, [[(subtitle, {"size": 11, "color": "404040"})]])
    sr = shape_by_name(slide, "src")
    if sr is None:
        sr = tbox(slide, 0.4, 7.22, 12.5, 0.22, [[(src, {"size": 7.5, "color": "404040"})]], size=7.5, name="src")
    else:
        set_text_keep_first(sr, [[(src, {"size": 7.5, "color": "404040"})]])
        sr.top = Inches(7.22)
        sr.height = Inches(0.22)
    return sr


def metric_box(slide, y, lines, h=0.95):
    """[Metric] 박스를 다시 그린다(기존 subtitle 중 Metric 박스 제거)."""
    for sh in list(slide.shapes):
        if sh.name in ("subtitle",) and sh.top > Inches(0.9):
            remove(sh)
    paras = [[(lines[0], {"bold": True, "color": NAVY, "size": 10.5})]]
    for ln in lines[1:]:
        paras.append([("- " + ln, {"size": 9.5})])
    return tbox(slide, 0.4, y, 12.5, h, paras, size=9.5, line_spacing=1.12, name="metric")


def star_label(s):
    return "미충족" if s == 0 else "★ %g" % s


def criteria_page(slide, spec):
    """spec: title, subtitle, src, metric(list), rows[(star, range, evidence, source)], chart dict, notes"""
    page_chrome(slide, spec["title"], spec["subtitle"], spec["src"])
    for nm in ("tbl", "formula", "l", "r_formula"):
        for sh in [s for s in slide.shapes if s.name == nm]:
            remove(sh)
    for sh in [s for s in slide.shapes if s.shape_type == 13]:  # picture는 Q3에서 다시 배치
        if not spec.get("keep_picture"):
            remove(sh)
    metric_box(slide, 1.17, spec["metric"], h=spec.get("metric_h", 0.95))
    y = spec.get("table_y", 2.2)
    stars = [3, 2.5, 2, 1.5, 1, 0]
    rows = [["별", "기준 (정량)", "근거", "출처"]]
    for st, rng, ev, srcx in spec["rows"]:
        rows.append([[[(star_label(st), {"bold": True})]], rng, ev, srcx])
    colw = spec.get("colw", [0.75, 1.75, 7.6, 2.43])
    rowh = [0.24] + [spec.get("row_h", 0.33)] * (len(rows) - 1)
    fills = [BAND_FILL[s] for s in stars]
    add_table(slide, 0.4, y, colw, rows, rowh, fills=fills, size=8.3, aligns=["c", "l", "l", "l"])
    ty = y + sum(rowh) + 0.12
    return ty


# ============================================================ 페이지별 사양
def q1_spec():
    r = cd.BAND_TEXT["Q1"]
    return dict(
        title="처리량 - 평가 기준",
        subtitle="Baseline 대비, SLO를 만족하는 조건에서의 처리량(Max값) 증가율",
        src="출처: LMCache (arXiv 2510.09665) · Sarathi-Serve OSDI'24 (2403.02310) · DistServe OSDI'24 (2401.09670) · Pensieve EuroSys'25 (2312.05516). 'up to' 보고값이며 지표·baseline이 달라 직접 비교 아님",
        metric=["[Metric] R = Max SLO goodput(후보) ÷ Max SLO goodput(Baseline)",
                "SLO: TTFT P99 ≤ 2 s, TPOT P99 ≤ 50 ms · SLO goodput: SLO를 만족한 요청이 처리한 토큰/초 (MLPerf Inference 참고)",
                "Max: 동시 요청이 늘면 goodput이 오르다 SLO 위반으로 꺾이므로 부하 sweep의 최댓값끼리 비교 (peak가 grid 끝이면 grid 확장)",
                "구간 규칙: ★1 = 요구 2x, ★ 한 단계 올라갈 때마다 처리량 2배(2→4→8, log 등간격), 반 단계는 기하 중점"],
        metric_h=0.95,
        table_y=2.15,
        rows=[
            (3, r[3], "★ 1단계 = 처리량 2배 추가 규칙(2→4→8). 문헌 상한대(SLO 내 처리량 Sarathi-Serve 최대 6.9x, DistServe 요청 수 7.4x)를 넘는 값. "
                      "LMCache 최대 14x는 컨텍스트 10~20K·적중률 극단 조건이라 앵커에서 제외", "Sarathi-Serve, DistServe, LMCache"),
            (2.5, r[2.5], "★2와 ★3의 기하 중점(√(4×8)=5.7). LMCache 실 기업 트레이스에서 고 QPS TTFT 3.7~6.8배 단축의 상단에 대응", "LMCache"),
            (2, r[2], "LMCache 고 QPS 구간: 동일 TTFT 제약으로 환산한 QPS 확장 통상 4~6배의 하한", "LMCache"),
            (1.5, r[1.5], "★1과 ★2의 기하 중점(√(2×4)=2.8). Sarathi-Serve 2.6x(Mistral-7B), Pensieve 최대 3.0x 구간", "Sarathi-Serve, Pensieve"),
            (1, r[1], "Stakeholder 요구: \"처리량 개선 2배 이상 되어야 제품화 논의 가능\". LMCache 단일 노드 로컬 CPU 오프로딩 다중 턴 QA(10~20K 토큰) 개선 하한선 2.3배",
             "Stakeholder 요구사항, LMCache"),
            (0, r[0], "시나리오 요구(2배) 미충족", "—"),
        ],
        chart=dict(
            title="구간 대비 근거 위치 (R, log 축)",
            axis=dict(min=1, max=16, log=True, ticks=[1, 2, 4, 8, 16], unit="x"),
            bands=[(1, 2, 0), (2, 2.8, 1), (2.8, 4, 1.5), (4, 5.7, 2), (5.7, 8, 2.5), (8, 16, 3)],
            markers=[
                dict(kind="point", v=2.0, style="req", label="Stakeholder 요구: 처리량 2배 이상 (제품화 논의 조건)"),
                dict(kind="point", v=2.3, style="lit", label="LMCache 단일 노드 CPU 오프로딩, 다중 턴 QA(10~20K) 개선 하한선 2.3x"),
                dict(kind="range", v=(1.14, 3.0), style="lit", label="Pensieve: vLLM·TRT-LLM 대비 1.14~3.0x"),
                dict(kind="range", v=(2.6, 6.9), style="lit", label="Sarathi-Serve: SLO 내 처리량 2.6x(Mistral-7B)~6.9x(Falcon-180B)"),
                dict(kind="range", v=(3.7, 6.8), style="lit", label="LMCache 기업 트레이스: 고 QPS TTFT 3.7~6.8x 단축"),
                dict(kind="range", v=(4, 6), style="lit", label="LMCache: 동일 TTFT 환산 QPS 확장 4~6x"),
                dict(kind="point", v=7.4, style="lit", label="DistServe: 요청 수 7.4x (SLO 내)"),
                dict(kind="point", v=14, style="excl", label="LMCache 최대 14x (극단 조건)"),
            ]),
    )


def q2_spec():
    r = cd.BAND_TEXT["Q2"]
    return dict(
        title="자원(HBM) 효율성 - 평가 기준",
        subtitle="Baseline 대비 HBM 사용률 감소율 (KV 캐시 관리, 압축 제외)",
        src="출처[1]: DirectKV OSDI'26 · HeadInfer (arXiv 2502.12574, 검색 요약 기준) · ShadowKV ICML'25 (arXiv 2410.21465). 40~80% 범위는 사용자 인용(원문 대조 필요)",
        metric=["[Metric] 감소율 = (Baseline HBM 사용률 − 후보 HBM 사용률) ÷ Baseline HBM 사용률",
                "HBM 사용률 = HBM에 위치한 KV 크기의 시간 평균 ÷ 전체 KV 크기 (오프로딩은 압축이 아니므로 전체 KV 크기는 같다)",
                "요청이 늘면 HBM 크기 내 점유율은 포화되어 이동 효율을 못 가리므로 '전체 Data 대비 HBM 사용률'을 쓴다 "
                "(예: HBM 점유 40→64 GiB, KV 120 GiB: 크기 내 50→80%, 전체 대비 66→53%)",
                "구간 규칙: ★1 = 요구 20%, ★2 = 오프로딩 문헌 하한 40%, ★3 = 60%, 반 단계는 중점 (10%p 등간격)"],
        metric_h=1.15,
        table_y=2.35,
        rows=[
            (3, r[3], "오프로딩 계열 보고 DirectKV 43%(기존 offload 대비)~HeadInfer 92%(1M ctx 단일 요청)의 중앙(≈67%)에 못 미치는 보수적 상한. "
                      "압축을 포함한 ShadowKV(batch 6x)와 극단 조건은 앵커에서 제외", "DirectKV, HeadInfer [1]"),
            (2.5, r[2.5], "★2와 ★3의 중점", "—"),
            (2, r[2], "DirectKV: CPU 메모리 직접 접근으로 GPU 메모리 43% 감소(GH200, 기존 offload 대비). 오프로딩 계열 보고 범위(40~80%)의 하한", "DirectKV [1]"),
            (1.5, r[1.5], "★1과 ★2의 중점", "—"),
            (1, r[1], "시나리오 요구 20%. 계산: HBM 20% 감소 = 같은 HBM에 KV 1/0.8 = 1.25배 수용(동시 처리 +25% 이상, 이론), 메모리 병목 대기 지연 단축", "시나리오 요구 / 이론 계산"),
            (0, r[0], "시나리오 요구(20%) 미충족. 음수는 후보가 HBM을 더 쓴 경우", "—"),
        ],
        chart=dict(
            title="구간 대비 근거 위치 (HBM 감소율 %)",
            axis=dict(min=0, max=100, log=False, ticks=[0, 20, 40, 60, 80, 100], unit="%"),
            bands=[(0, 20, 0), (20, 30, 1), (30, 40, 1.5), (40, 50, 2), (50, 60, 2.5), (60, 100, 3)],
            markers=[
                dict(kind="point", v=20, style="req", label="시나리오 요구 20% (≈ 동시 수용 +25%, 이론)"),
                dict(kind="point", v=43, style="lit", label="DirectKV (OSDI'26, GH200): GPU 메모리 43% 감소"),
                dict(kind="range", v=(40, 80), style="lit", label="오프로딩 계열 보고 범위 40~80% [1]"),
                dict(kind="point", v=67, style="calc", label="계산: 보고 43~92%의 중앙 ≈ 67% (★3 = 60%는 이보다 보수적)"),
                dict(kind="point", v=83, style="excl", label="ShadowKV: batch 6x ≈ 83%/seq (key 저랭크 압축 포함)"),
                dict(kind="point", v=92, style="excl", label="HeadInfer: 총 GPU 메모리 92% (1M ctx 단일 요청, 극단)"),
            ]),
        left_note=True,
    )


def q3_spec():
    r = cd.BAND_TEXT["Q3"]
    return dict(
        title="고부하 지연시간(Tail Latency) - 평가 기준",
        subtitle="Baseline 대비 TTFT·TPOT P99 개선 r의 환산 감소율 (고부하 = Baseline 포화 부하의 90%, SLO 충족 전제)",
        src="출처: LMCache (arXiv 2510.09665) · AttentionStore (2403.19708) · Llumnix OSDI'24 (2406.03243). 검색 요약 기준(버전별 상이), LMCache E2E 50~75%는 사용자 인용(원문 대조 필요)",
        metric=["[Metric] r = √[ (Baseline TTFT P99 ÷ 후보 TTFT P99) × (Baseline TPOT P99 ÷ 후보 TPOT P99) ],  감소율 = 1 − 1/r",
                "고부하: 부하를 Baseline의 Max SLO goodput의 90%에 고정 (후보 기준으로 잡지 않는다) · SLO(TTFT ≤ 2 s, TPOT ≤ 50 ms) 충족 필수",
                "구간 규칙: ★1 = 요구 30%(r 1.43), ★2 = 50%(r 2.0), ★3 = 75%(r 4.0), 반 단계는 중점"],
        metric_h=0.85,
        table_y=2.05,
        rows=[
            (3, r[3], "LMCache E2E 지연 50~75% 감소의 상단. AttentionStore TTFT 87~88%, Llumnix P99 TTFT 5.5x(82%)는 TTFT 한정 상한이라 TPOT가 섞인 r에서는 75%로 보수 설정", "LMCache, AttentionStore, Llumnix"),
            (2.5, r[2.5], "★2와 ★3의 중점. 이 위쪽은 TTFT 한정 보고(LMCache 77~85%, Llumnix 82%)가 걸치는 구간", "LMCache, Llumnix"),
            (2, r[2], "LMCache Context 벤치마크 E2E 지연 약 50~75% 감소의 하한(r 2.0)", "LMCache"),
            (1.5, r[1.5], "★1과 ★2의 중점. LMCache ITL(≈TPOT) 34~58% 감소 보고 구간", "LMCache"),
            (1, r[1], "Stakeholder 요구: 사용자 체감 개선 30%. LMCache ITL 감소 하한 34%와 같은 자릿수", "Stakeholder 요구사항, LMCache"),
            (0, r[0], "시나리오 요구(30%) 미충족 또는 SLO 위반. 음수는 Baseline보다 나빠진 경우", "—"),
        ],
        chart=dict(
            title="구간 대비 근거 위치 (P99 감소율 %)",
            axis=dict(min=0, max=100, log=False, ticks=[0, 20, 40, 60, 80, 100], unit="%"),
            bands=[(0, 30, 0), (30, 40, 1), (40, 50, 1.5), (50, 62.5, 2), (62.5, 75, 2.5), (75, 100, 3)],
            markers=[
                dict(kind="point", v=30, style="req", label="Stakeholder: 사용자 체감 개선 30%"),
                dict(kind="range", v=(34, 58), style="lit", label="LMCache ITL(≈TPOT) 34~58% 감소 (고 QPS 실트래픽)"),
                dict(kind="range", v=(50, 75), style="lit", label="LMCache E2E 지연 50~75% 감소 (Context 벤치마크)"),
                dict(kind="range", v=(23, 82), style="lit", label="Llumnix: P99 per-token 23% ~ P99 TTFT 82%"),
                dict(kind="range", v=(77, 85), style="lit", label="LMCache TTFT 4.4~6.6x(77~85%) (고 QPS)"),
                dict(kind="range", v=(87, 88), style="lit", label="AttentionStore TTFT 87~88%"),
            ]),
        keep_picture=True,
    )


def q4_spec():
    r = cd.BAND_TEXT["Q4"]
    return dict(
        title="시스템 확장성 - 평가 기준",
        subtitle="시스템 및 자원의 증가분 대비 처리량의 증가분 비율",
        src="출처: AthenaK (arXiv 2409.16053, 학습 workload) · USL 환산. 90% '효율적' 기준은 관례(정책)이며 인용 논문을 확인하지 못해 출처로 삼지 않았다",
        metric=["[Metric] SE(N) = Goodput 증가 배율 ÷ N 증가 배율  (N = 노드 수, 평가는 N=16 시뮬레이션)",
                "USL 환산: SE(N) = 1 ÷ (1 + σ(N−1)), σ = 조율 계층의 직렬 비중. N=16에서 SE 80%↔σ 1.67%, 85%↔1.18%, 90%↔0.74%, 92.5%↔0.54%, 95%↔0.35%",
                "구간 규칙: ★1 = 요구 80%, ★2 = 90%(손실 10% 이내), ★3 = 95%(손실 5% 이내), 반 단계는 중점"],
        metric_h=0.9,
        table_y=2.15,
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


# ============================================================ 페이지 6~11 구성
def build_criteria_slides(prs):
    sl = prs.slides
    specs = {5: q1_spec(), 6: q2_spec(), 7: q3_spec(), 9: q4_spec()}  # 0-based 슬라이드 인덱스
    for idx, spec in specs.items():
        s = sl[idx]
        ty = criteria_page(s, spec)
        ch = spec["chart"]
        if spec.get("keep_picture") or spec.get("left_note"):
            lx, lw = 0.4, 4.2
            cx, cw = 4.85, 8.1
        else:
            cx, cw = 0.4, 12.5
        band_chart(s, cx, ty + 0.02, cw, ch["axis"], ch["bands"], ch["markers"], title=ch["title"])
    # Q3 P99 설명 + 그림 (왼쪽 아래)
    s = sl[7]
    pics = [p for p in s.shapes if p.shape_type == 13]
    tbox(s, 0.4, 4.45, 4.3, 0.55,
         [[("P99의 의미", {"bold": True, "color": NAVY, "size": 9.5})],
          [("상위 1%의 극단적 지연을 포착해 고부하 서비스 끊김을 검증", {"size": 8.5})]], size=8.5, line_spacing=1.05)
    for p in pics:
        p.left, p.top = Inches(0.45), Inches(5.05)
        scale = 1.85 / (p.height / 914400)
        p.width, p.height = int(p.width * scale), int(p.height * scale)
    # Q2 왼쪽: 의미 설명(HBM 사용량)
    s = sl[6]
    tbox(s, 0.4, 5.0, 4.3, 1.9,
         [[("HBM 사용률(전체 Data 대비)", {"bold": True, "color": NAVY, "size": 9.5})],
          [("• HBM 사용량: HBM에 올라와 있는 KV의 시간 평균 크기", {"size": 8.5})],
          [("  예) 100초 중 40초 100 GiB, 60초 50 GiB → 70 GiB", {"size": 8.5, "color": "404040"})],
          [("• 전체 Data 대비 사용률 = HBM 사용량 ÷ 전체 KV 크기", {"size": 8.5})],
          [("  예) KV 120 GiB 중 HBM 64 GiB → 53% (이전 60 GiB / 80 GiB → 66%)", {"size": 8.5, "color": "404040"})],
          [("• 압축이 아니므로 정확도(출력)는 변하지 않는다.", {"size": 8.5})]],
         size=8.5, line_spacing=1.1)
    # Q4(확장성) 그래프는 기본 위치. Q5
    q5_page(sl[10])
    # Q5 그래프 2개 (module, MM)
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


# ============================================================ DP 페이지(2~5) 주석
DP_SLIDE = {"DP1": 1, "DP2": 2, "DP3": 3, "DP4": 4}  # 0-based 슬라이드 인덱스

# 별 왼쪽 코멘트(파란 글씨). None이면 달지 않는다. 소유자가 이미 코멘트 박스를 둔 줄은 건너뛴다.
COMMENTS = {
    ("DP1", 1): {"Q1": "예상보다 낮음(<2x)", "Q2": "예상보다 낮음(<20%)", "Q5": "예상보다 높음(★3)"},
    ("DP1", 2): {"Q1": "예상보다 낮음(<2x)", "Q3": "예상보다 낮음(<30%)"},
    ("DP2", 1): {"Q1": "2안과 같은 값", "Q2": "예상보다 낮음(20% 미달)", "Q3": "TPOT는 +34% 악화", "Q4": "예상보다 낮음(N=32 포화)"},
    ("DP2", 2): {"Q1": "1안과 같은 값", "Q2": "Baseline보다 HBM 증가", "Q4": "예상보다 낮음(η<0.8)"},
    ("DP4", 1): {"Q1": "Baseline(RDMA)보다 낮음", "Q3": "동일 부하에선 TTFT ×5 악화", "Q4": "N=16에선 2안과 같은 값"},
    ("DP4", 2): {"Q1": "1안과 같은 값", "Q3": "1안과 같은 값", "Q4": "N=16 동일, 락 확장 근거 미검증"},
}
LEGEND_BOX = {"DP1": (6.0, 4.8), "DP2": (7.35, 4.85), "DP3": (6.0, 5.0), "DP4": (6.2, 4.7)}


def _cell_texts(cell):
    return [p.text for p in cell.text_frame.paragraphs]


def annotate_dp(slide, dp):
    tbl_shape = next(s for s in slide.shapes if s.has_table)
    tbl = tbl_shape.table
    row = tbl.rows[len(tbl.rows) - 1]
    cells = row.cells
    # 후보별 (label_idx, [blank idx...], star_idx)
    star_idx = [i for i, c in enumerate(cells) if "●" in c.text]
    cands = []
    for k, si in enumerate(star_idx, start=1):
        li = si - 1
        blanks = []
        while li > 0 and not cells[li].text.strip().startswith("Q"):
            blanks.append(li)
            li -= 1
        cands.append((k, li, sorted(blanks), si))
    for k, li, blanks, si in cands:
        label_cell, star_cell = cells[li], cells[si]
        labels = {}
        for p in label_cell.text_frame.paragraphs:
            m = re.match(r"\s*Q(\d)\.", p.text)
            if m:
                labels["Q" + m.group(1)] = p
        q_order = list(labels.keys())
        star_pars = [p for p in star_cell.text_frame.paragraphs if p.text.strip()]
        # 별 칸 오른쪽 여백을 없애 수치가 줄바꿈되지 않게 한다
        star_cell._tc.get_or_add_tcPr().set("marR", "0")
        blank_cell = cells[blanks[0]] if blanks else None
        if blank_cell is not None:
            # 빈 칸의 단락 수를 Q 줄 수에 맞춘다
            btf = blank_cell.text_frame
            while len(btf.paragraphs) < len(q_order):
                btf.add_paragraph()
        for qi, q in enumerate(q_order):
            sp = star_pars[qi]
            act = cd.ACTUAL.get((dp, k), {}).get(q)
            txt = act["disp"] if act else "—"
            r = sp.add_run()
            r.text = " " + txt
            _font(r, 7, False, "595959" if act else "A6A6A6")
            cm = COMMENTS.get((dp, k), {}).get(q)
            if blank_cell is not None:
                bp = blank_cell.text_frame.paragraphs[qi]
                sp0 = bp.add_run()
                sp0.text = " "
                _font(sp0, 12, False, "FFFFFF")  # 12pt 줄 높이 유지용 공백
                if cm:
                    rr = bp.add_run()
                    rr.text = "▸ " + cm
                    _font(rr, 7.5, False, "0000FF")
            elif cm:
                rr = labels[q].add_run()
                rr.text = "   ▸ " + cm
                _font(rr, 8, False, "0000FF")
    # 범례(짧게). 지표 정의는 평가 기준 페이지와 마지막 정합 표에 있다.
    tbox(slide, 0.62, 7.2, 4.3, 0.28,
         [[("회색 수치 = 기존 중립 벤치마크 시뮬 실측[B+C] (Q3은 P99 개선 환산 감소율, Q4는 η/SE). ", {"size": 6.3, "color": "595959"}),
           ("파란 글씨 = 소유자 별 대비 코멘트.", {"size": 6.3, "color": "0000FF"}),
           ((" DP3는 후보가 달라 미측정." if dp == "DP3" else ""), {"size": 6.3, "color": "595959"})]],
         size=6.3, line_spacing=0.95, margins=(0.02, 0.0, 0.02, 0.0), name="legend_v4")


# ============================================================ 요구사항 페이지(1)
def edit_requirements(slide):
    tbl = next(s for s in slide.shapes if s.has_table).table
    for r in tbl.rows:
        if r.cells[0].text.strip() == "QA-05":
            cell = r.cells[3]
            p0 = cell.text_frame.paragraphs[0]
            tmpl = None
            for run in p0.runs:
                tmpl = run
                break
            # 단락 전체를 새 문장으로 교체(첫 run 서식 유지)
            paras = list(cell.text_frame.paragraphs)
            for p in paras[1:]:
                p._p.getparent().remove(p._p)
            for run in list(p0.runs):
                p0._p.remove(run._r)
            sz = 9
            if tmpl is not None and tmpl.font.size:
                sz = tmpl.font.size.pt
            add_runs(p0, "새로운 메모리 tier 추가, 이동·배치·재사용 정책 교체, vLLM upstream 갱신 시 서빙 경로를 수정하지 않고 반영할 수 있어야 한다.", sz)
            p1 = cell.text_frame.add_paragraph()
            add_runs(p1, [("[측정: 변경 모듈 수 ≤ 5개, 개발 공수 ≤ 1.0 M/M (변경 시나리오 3종 평균, 두 조건 모두 만족)]", {"color": "000000", "bold": True})], sz)


# ============================================================ 신규 페이지(평가 시나리오, 정합 표)
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
                     "KV 캐시 관리만 대상(RAG·LoRA·MoE 제외). KV가 HBM 용량을 넘고 재사용할 history가 있는 구간을 겨냥한 통합 시나리오",
                     "근거: Llama-3.1-70B KV 327,680 B/token(80 layer × 8 KV head × 128 dim × K·V × BF16) · H100×8 HBM 640 GiB, 가중치 약 131 GiB · "
                     "prefill 처리율은 MFU 0.45 가정(≈ 25k tok/s). 부하·tool 대기 분포는 설계값[가정]이며 시뮬레이션 전 값이다.")
    rows = [["항목", "값", "근거 / 계산"],
            ["모델·HW", "Llama-3.1-70B BF16, 8-GPU 노드(SYS-H100 / SYS-B200). DP2·DP4는 P/D 분리 2~16 노드",
             "기존 평가 환경과 동일(비교 가능성). 노드 간 링크는 RDMA 50 GB/s [ASSUMED]"],
            ["세션·컨텍스트", "동시 agent 세션 256, 컨텍스트 평균 16K(8K→24K), 턴당 +1K(tool 결과) 입력, 출력 256, 세션당 10~20턴",
             "16K 세션 KV = 327,680 B × 16,384 ≈ 5.0 GiB. LMCache가 이득을 보고한 10~20K 컨텍스트 구간"],
            ["tool 대기", "턴 사이 대기 lognormal, 중앙값 5 s (0.2~30 s sweep) — 대기 중 KV는 유휴",
             "유휴 비율 ≈ 50% [가정]. 활성 세션 ≈ 128 → 640 GiB ≫ HBM KV 풀"],
            ["HBM 압박", "HBM KV 풀 ≈ 425 GiB(640×0.9 − 가중치 131 − 활성값 약 20) ≈ 85 세션분. 활성 KV 640 GiB = 풀의 1.5배",
             "Baseline(vLLM)은 KV 부족 시 preemption→recompute. 16K 재prefill ≈ 0.65 s vs DRAM→HBM 복원 ≈ 10~50 ms(이론 PCIe 5.0 ×8)"],
            ["공유 KV", "세션 간 공유 문서 청크 30%, 그중 50%는 prefix가 아닌 위치(non-prefix)에서 재사용",
             "DP3 재사용 구조가 선택 재계산으로 이득을 내는 조건. 나머지 70%는 세션 고유"],
            ["부하·SLO", "세션 동시성 32→512 sweep(Max goodput), Q3는 Baseline Max goodput의 90% 고정 부하. SLO: TTFT P99 ≤ 2 s, TPOT P99 ≤ 50 ms",
             "Q1: R, Q3: 고부하 P99, 부하 90%는 후보 기준이 아니라 Baseline 기준"],
            ["Baseline", "vLLM 기본: HBM prefix cache + preemption recompute, KV 이동·노드 간 공유 없음, P/D 고정 역할",
             "후보와 같은 SLO·seed·workload. 후보 전용 메모리는 Baseline이 쓰지 않음을 명시"],
            ["반복", "seed ≥ 5, median, 95% CI. 별은 시나리오 단위 보고, 조건부 별로 표기", "단일 seed로 별점을 매기지 않는다"]]
    add_table(s, 0.4, 1.2, [1.15, 6.2, 5.18], rows, [0.26] + [0.52] * 8, fills=[None] * 8, size=8.3, aligns=["l", "l", "l"])
    # 우측 하단 조건부 별 안내
    tbox(s, 0.4, 5.85, 12.5, 0.55,
         [[("조건부 별: ", {"bold": True, "color": "C00000", "size": 9.5}),
           ("이 시나리오는 KV가 HBM을 넘고 재사용할 history가 있는 구간을 의도적으로 겨냥한다(문헌의 이득 보고 조건과 같은 영역). "
            "짧은 컨텍스트·KV 여유 구간에서는 이득이 줄어들 수 있으므로 별은 '이 regime에서의 별'로 읽는다.", {"size": 9})]],
         size=9, line_spacing=1.1)

    s2 = clone_chrome(prs, 5, "평가 시나리오 - 구간(Phase)과 DP·QA 대응",
                      "한 시나리오 안에서 DP별 메커니즘이 작동하는 구간을 나누고, QA별 측정 규칙을 정한다",
                      "N 노드 확장(P4)은 별도 run(N = 2, 4, 8, 16, 세션 수 ∝ N). 모든 값은 시뮬레이션 전 설계값이다.")
    rows = [["Phase", "구간 내용", "겨냥하는 DP 메커니즘", "측정 QA"],
            ["P1 정상 multi-turn\n(0~10분)", "agent 세션이 tool 대기를 두고 턴을 이어 감. 유휴 KV가 HBM을 점유",
             "DP1: 유휴 KV 하위 tier 이동(demote)과 재개 시 승격·prefetch(promote). 1안 = 자원 상태 기반, 2안 = 데이터 접근 특성 기반", "Q1, Q2, Q3"],
            ["P2 burst\n(10~15분)", "신규 세션 3배 폭주 + 기존 세션 decode가 겹침(prefill burst + decode-heavy 혼합)",
             "DP2: Prefill/Decode 실행 위치 결정. 1안 = 스케줄링 시점 결정, 2안 = 사전 계획 결정(Re-plan 위험)", "Q1, Q3, Q4"],
            ["P3 공유 문서 wave\n(15~25분)", "같은 문서 청크를 여러 세션이 연달아 참조(위치가 달라 prefix 재사용 불가 50%)",
             "DP3: 재사용·재계산 대상 선정. 1안 = 요청마다 전체 체인(Pipe-and-Filter), 2안 = 분석 1회 + 조회(Shared Repository), 둘 다 선택 재계산", "Q1, Q2, Q3"],
            ["P4 노드 확장\n(별도 run)", "노드 2→16, 세션 수 ∝ 노드 수. 노드 간 KV 블록 조회·소유권 이동 발생",
             "DP4: 서버 간 KV 공유. 1안 = 중앙 서버 중재, 2안 = 락 기반 직접 접근", "Q1, Q3, Q4"],
            ["변경 시나리오\n(구현 측정)", "S1 새 메모리 tier · S2 정책 교체 · S3 vLLM upstream 갱신",
             "모든 DP 후보의 module 수·M/M (시나리오 평균)", "Q5"]]
    add_table(s2, 0.4, 1.2, [1.6, 3.9, 5.5, 1.53], rows, [0.26] + [0.62] * 5, fills=[None] * 5, size=8.5, aligns=["l", "l", "l", "c"])
    tbox(s2, 0.4, 4.9, 12.5, 1.2,
         [[("측정 규칙", {"bold": True, "color": NAVY, "size": 10})],
          [("• Q1: 부하 sweep 최댓값끼리 R 비교 · Q2: 시간 평균 HBM 사용률의 Baseline 대비 감소율 · Q3: Baseline 포화 부하의 90%에서 TTFT·TPOT P99로 r 계산", {"size": 9})],
          [("• Q4: 노드 2→16 sweep, SE(16) = Goodput 배율 ÷ 노드 배율 · Q5: 변경 시나리오 3종을 각 후보에 구현해 module 수·M/M 평균", {"size": 9})],
          [("• 기준·시나리오 값은 시뮬레이션 결과를 보기 전에 고정한다. 기존 중립 벤치마크(8K 입력, batch 32) 결과는 'DP 페이지의 회색 수치'로 병기하고 이 시나리오 결과와 섞지 않는다.", {"size": 9})]],
         size=9, line_spacing=1.12)


def mapping_slide(prs):
    s = clone_chrome(prs, 5, "Trade-off 별 ↔ 평가 기준 구간 ↔ 기존 실측",
                     "DP 후보별 소유자 별이 새 기준의 어떤 수치 구간에 해당하는지, 기존 중립 벤치마크 실측은 어디에 놓이는지",
                     "실측 = 기존 중립 벤치마크 시뮬레이션 [B+C] (H100+B200 통합). 새 시나리오 결과가 아니다. DP3는 후보가 달라 미측정. "
                     "붉은 글씨 = 실측이 소유자 별 구간에 못 미침, 파란 글씨 = 같거나 높음.")
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
            band = cd.BAND_SHORT[q][o]
            act = cd.ACTUAL.get(key, {}).get(q)
            line1 = [(cd.fmt_star(o) + " → " + band, {"size": 8, "bold": True})]
            if act is None:
                line2 = [("실측 없음", {"size": 7.5, "color": "A6A6A6"})]
            else:
                a_star = cd.actual_star(*key, q)
                ok = a_star >= o
                line2 = [("실측 " + act["disp"] + " → " + cd.fmt_star(a_star), {"size": 7.5, "color": "2F5597" if ok else "C00000"})]
            row.append([line1, line2])
        rows.append(row)
    add_table(s, 0.4, 1.2, [2.3, 2.0, 2.0, 2.15, 2.0, 2.08], rows, [0.28] + [0.5] * 8, fills=[None] * 8, size=8, aligns=["l"] * 6)
    tbox(s, 0.4, 5.6, 12.5, 1.4,
         [[("읽는 법", {"bold": True, "color": NAVY, "size": 10})],
          [("• 굵은 줄: 소유자 별과 그 별이 요구하는 새 기준 구간. 작은 줄: 기존 중립 벤치마크 실측과 새 기준으로 환산한 별.", {"size": 9})],
          [("• 실측이 구간에 못 미치는 곳이 대부분이다. Q1~Q3의 실측은 모두 ★1 기준(2x, 20%, 30%) 아래다. 중립 벤치마크는 8K 입력·batch 32라 HBM 압박과 재사용 history가 거의 없는 조건이기 때문이며, "
            "새 시나리오(Agent KV Fleet)가 그 조건을 만든다. 새 시나리오에서 이 구간에 도달하는지는 시뮬레이션 전이라 알 수 없다.", {"size": 9})],
          [("• 실측이 소유자 별과 방향이 반대인 곳: DP4 Q4(락 기반이 3, 실측은 N=16에서 두 안 동일), DP2 Q1(두 안 동일), DP1 Q5(실측이 더 높음).", {"size": 9})]],
         size=9, line_spacing=1.12)


# ============================================================ main
def main():
    prs = Presentation(BASE)
    edit_requirements(prs.slides[0])
    for dp, idx in DP_SLIDE.items():
        annotate_dp(prs.slides[idx], dp)
    build_criteria_slides(prs)
    scenario_slides(prs)
    mapping_slide(prs)
    prs.save(OUT)
    print("saved", OUT)


if __name__ == "__main__":
    main()
