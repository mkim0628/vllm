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


