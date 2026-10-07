#!/usr/bin/env python3
"""C1 QA1 보완 구조(doc-mk/DP1/dp1-c1-qa1-complement-design.md)를 사용자의 DP1 참조 deck 스타일로 다시 그린다.

참조 deck(final.pptx)을 template 으로 열어 slide master/theme/title/header bar/chip/장식선을 그대로 유지하고,
본문(표, 두 headline, C1/C2 블록)만 지운 뒤 같은 palette/폰트/박스/화살표 스타일로 새 다이어그램을 그린다.

사용:
  /usr/local/bin/python3 doc-mk/Evaluation/tools/gen_c1_complement_styled_pptx.py \
      [--ref <final.pptx>] [--out doc-mk/DP1/DP1-c1-qa1-complement-structure-styled.pptx]

참조 스타일(참조 deck 을 dump 해 얻은 값)
  기존 C1 블록  : rect, fill accent1 lumMod20/lumOff80, line 4D7EA8 12700, 900 bold, text 1A1A1A
  공통/외부 블록: rect, fill F0F1F3, line 888C91 12700, 800, text 1A1A1A
  신규 블록     : 참조 C2 쪽 accent2 계열(fill accent2 20/80, line C76E31)
  변경 블록     : accent6 계열(fill accent6 20/80, line accent6 lumMod75)  (참조 chip C1/C2 가 accent6)
  Mapper        : noFill + FF0000 line (static hint 채널, 참조와 동일)
  화살표        : 기존 accent1 11430 triangle / event 888C91 6350 / hint FF0000 11430 / 신규 C76E31 12700
  표            : tableStyleId {5940675A...}, 테두리 6350 bg1 lumMod75, label 칸 fill bg1 lumMod95
"""
import argparse
import copy
import os
import sys
import unicodedata

from lxml import etree
from pptx import Presentation
from pptx.util import Emu
from pptx.enum.shapes import MSO_SHAPE, MSO_CONNECTOR

A = "http://schemas.openxmlformats.org/drawingml/2006/main"
P = "http://schemas.openxmlformats.org/presentationml/2006/main"
NS = {"a": A, "p": P}
DEFAULT_REF = str(__import__("pathlib").Path(__file__).resolve().parents[2] / "DP1" / "ref" / "DP1-final-style-reference.pptx")
SLIDE_W, SLIDE_H = 12192000, 6858000
M = 1_000_000

# ---------------------------------------------------------------- 색 spec
# ('s', 'accent1', {'lumMod':20000,'lumOff':80000}) | ('r', '4D7EA8')
BLUE_FILL = ("s", "accent1", {"lumMod": 20000, "lumOff": 80000})
BLUE_LINE = ("r", "4D7EA8")
NEW_FILL = ("s", "accent2", {"lumMod": 20000, "lumOff": 80000})
NEW_LINE = ("r", "C76E31")
CHG_FILL = ("s", "accent6", {"lumMod": 20000, "lumOff": 80000})
CHG_LINE = ("s", "accent6", {"lumMod": 75000})
GRAY_FILL = ("r", "F0F1F3")
GRAY_LINE = ("r", "888C91")
TXT = ("r", "1A1A1A")
WHITE = ("s", "bg1", {})
SUBTXT = ("s", "bg1", {"lumMod": 50000})
TBL_LBL = ("s", "tx1", {"lumMod": 50000, "lumOff": 50000})
TBL_FILL = ("s", "bg1", {"lumMod": 95000})
TBL_LN = ("s", "bg1", {"lumMod": 75000})
RED = ("r", "FF0000")
DARK = ("r", "404040")
ACC_BLUE = ("s", "accent1", {})
LINK_BLUE = ("r", "0066FF")


def clr_xml(c):
    if c[0] == "r":
        return f'<a:srgbClr xmlns:a="{A}" val="{c[1]}"/>'
    mods = "".join(f'<a:{k} val="{v}"/>' for k, v in c[2].items())
    return f'<a:schemeClr xmlns:a="{A}" val="{c[1]}">{mods}</a:schemeClr>'


def solid(c):
    return etree.fromstring(f'<a:solidFill xmlns:a="{A}">{clr_xml(c)}</a:solidFill>')


# ---------------------------------------------------------------- 텍스트 기록(검증용)
TEXT_RECORDS = []   # dict(name, w, h, paras, ins(l,t,r,b), kind)
NODES = {}          # name -> (x, y, w, h)  겹침/화살표 검증용
ARROWS = []         # (name, (x1,y1), (x2,y2), from_node, to_node)


def make_runs(p_el, runs):
    for text, sz, bold, color in runs:
        r = etree.SubElement(p_el, f"{{{A}}}r")
        rpr = etree.SubElement(r, f"{{{A}}}rPr")
        rpr.set("lang", "ko-KR")
        rpr.set("altLang", "en-US")
        rpr.set("sz", str(sz))
        if bold:
            rpr.set("b", "1")
        rpr.set("dirty", "0")
        if color is not None:
            rpr.append(solid(color))
        t = etree.SubElement(r, f"{{{A}}}t")
        t.text = text


def set_text(shape, paras, algn="ctr", anchor="ctr", ins=None, wrap="square", name=None,
             record=True):
    """paras: [[(text, sz, bold, color), ...], ...]"""
    txb = shape._element.find(".//p:txBody", NS)
    if txb is None:
        txb = shape._element.find(f".//{{{P}}}txBody")
    for ch in list(txb):
        txb.remove(ch)
    bp = etree.SubElement(txb, f"{{{A}}}bodyPr")
    bp.set("wrap", wrap)
    ins = ins or (91440, 45720, 91440, 45720)
    bp.set("lIns", str(ins[0]))
    bp.set("tIns", str(ins[1]))
    bp.set("rIns", str(ins[2]))
    bp.set("bIns", str(ins[3]))
    bp.set("rtlCol", "0")
    bp.set("anchor", anchor)
    etree.SubElement(txb, f"{{{A}}}lstStyle")
    for runs in paras:
        p = etree.SubElement(txb, f"{{{A}}}p")
        ppr = etree.SubElement(p, f"{{{A}}}pPr")
        ppr.set("algn", algn)
        make_runs(p, runs)
    if record:
        TEXT_RECORDS.append(dict(name=name or shape.name, w=shape.width, h=shape.height,
                                 paras=paras, ins=ins, wrap=wrap))


def set_line(shape, color=None, w=12700, dash="solid", tail=None, head=None, sm=False):
    spPr = shape._element.find(f"{{{P}}}spPr")
    for old in spPr.findall(f"{{{A}}}ln"):
        spPr.remove(old)
    ln = etree.SubElement(spPr, f"{{{A}}}ln")
    if color is None:
        etree.SubElement(ln, f"{{{A}}}noFill")
        return
    ln.set("w", str(w))
    ln.append(solid(color))
    d = etree.SubElement(ln, f"{{{A}}}prstDash")
    d.set("val", dash)
    for tag, kind in (("headEnd", head), ("tailEnd", tail)):
        e = etree.SubElement(ln, f"{{{A}}}{tag}")
        e.set("type", kind or "none")
        if kind:
            e.set("w", "sm" if sm else "med")
            e.set("len", "sm" if sm else "med")


def set_fill(shape, color):
    spPr = shape._element.find(f"{{{P}}}spPr")
    for tag in ("solidFill", "noFill", "gradFill"):
        for old in spPr.findall(f"{{{A}}}{tag}"):
            spPr.remove(old)
    geom = spPr.find(f"{{{A}}}prstGeom")
    if geom is None:
        geom = spPr.find(f"{{{A}}}custGeom")
    el = etree.Element(f"{{{A}}}noFill") if color is None else solid(color)
    geom.addnext(el)


def strip_style(shape):
    st = shape._element.find(f"{{{P}}}style")
    if st is not None:
        shape._element.remove(st)


def add_box(slide, name, x, y, w, h, fill, line, paras, lw=12700, geom=MSO_SHAPE.RECTANGLE,
            node=True, ins=None, anchor="ctr", dash="solid", algn="ctr"):
    empty = not any(t for runs in paras for t, *_ in runs)
    s = slide.shapes.add_shape(geom, Emu(x), Emu(y), Emu(w), Emu(h))
    s.name = name
    strip_style(s)
    set_fill(s, fill)
    set_line(s, line, lw, dash)
    set_text(s, paras, algn=algn, anchor=anchor, ins=ins, name=name, record=not empty)
    if node:
        NODES[name] = (x, y, w, h)
    return s


def add_label(slide, name, x, y, w, h, paras, algn="l", border=None, dash="dash"):
    s = slide.shapes.add_textbox(Emu(x), Emu(y), Emu(w), Emu(h))
    s.name = name
    set_text(s, paras, algn=algn, anchor="ctr", ins=(45720, 0, 45720, 0), name=name)
    if border is not None:
        set_line(s, border, 12700, dash)
    return s


def add_tag(slide, name, x, y, text, fill):
    """참조의 작은 dark roundRect tag(tag_C1_MR 등) 스타일."""
    s = slide.shapes.add_shape(MSO_SHAPE.ROUNDED_RECTANGLE, Emu(x), Emu(y), Emu(300000), Emu(137160))
    s.name = name
    strip_style(s)
    set_fill(s, fill)
    set_line(s, None)
    set_text(s, [[(text, 600, True, ("r", "FFFFFF"))]], ins=(0, 0, 0, 0), name=name)
    return s


def arrow(slide, name, p1, p2, color, w=11430, from_node=None, to_node=None, dash="solid",
          both=False, sm=False):
    c = slide.shapes.add_connector(MSO_CONNECTOR.STRAIGHT, Emu(p1[0]), Emu(p1[1]),
                                   Emu(p2[0]), Emu(p2[1]))
    c.name = name
    strip_style(c)
    set_line(c, color, w, dash, tail="triangle", head="triangle" if both else None, sm=sm)
    ARROWS.append((name, p1, p2, from_node, to_node))
    return c


def polyline(slide, name, pts, color, w=12700, from_node=None, to_node=None):
    fb = slide.shapes.build_freeform(Emu(pts[0][0]), Emu(pts[0][1]))
    fb.add_line_segments([(Emu(x), Emu(y)) for x, y in pts[1:]], close=False)
    s = fb.convert_to_shape()
    s.name = name
    strip_style(s)
    set_fill(s, None)
    set_line(s, color, w, "solid", tail="triangle")
    ARROWS.append((name, pts[0], pts[-1], from_node, to_node))
    return s


# ---------------------------------------------------------------- 표 (참조 표 스타일)
CELL_RECORDS = []


def fmt_cell(cell, paras, fill=None, anchor="ctr", algn="l", mar=(91440, 45720, 91440, 45720),
             name="cell", width=0):
    tc = cell._tc
    txb = tc.find(f"{{{A}}}txBody")
    for ch in list(txb):
        txb.remove(ch)
    etree.SubElement(txb, f"{{{A}}}bodyPr")
    etree.SubElement(txb, f"{{{A}}}lstStyle")
    for runs in paras:
        p = etree.SubElement(txb, f"{{{A}}}p")
        ppr = etree.SubElement(p, f"{{{A}}}pPr")
        ppr.set("algn", algn)
        ppr.set("latinLnBrk", "1")
        make_runs(p, runs)
    old = tc.find(f"{{{A}}}tcPr")
    if old is not None:
        tc.remove(old)
    tcpr = etree.SubElement(tc, f"{{{A}}}tcPr")
    tcpr.set("marL", str(mar[0]))
    tcpr.set("marT", str(mar[1]))
    tcpr.set("marR", str(mar[2]))
    tcpr.set("marB", str(mar[3]))
    tcpr.set("anchor", anchor)
    for side in ("lnL", "lnR", "lnT", "lnB"):
        ln = etree.SubElement(tcpr, f"{{{A}}}{side}")
        ln.set("w", "6350")
        ln.set("cap", "flat")
        ln.set("cmpd", "sng")
        ln.set("algn", "ctr")
        ln.append(solid(TBL_LN))
        d = etree.SubElement(ln, f"{{{A}}}prstDash")
        d.set("val", "solid")
        etree.SubElement(ln, f"{{{A}}}round")
        for t in ("headEnd", "tailEnd"):
            e = etree.SubElement(ln, f"{{{A}}}{t}")
            e.set("type", "none")
            e.set("w", "med")
            e.set("len", "med")
    if fill is not None:
        tcpr.append(solid(fill))
    if width:
        CELL_RECORDS.append(dict(name=name, w=width, paras=paras, mar=mar))


def add_table(slide, name, x, y, col_w, row_h):
    gf = slide.shapes.add_table(len(row_h), len(col_w), Emu(x), Emu(y), Emu(sum(col_w)),
                                Emu(sum(row_h)))
    gf.name = name
    tbl = gf.table
    for i, w in enumerate(col_w):
        tbl.columns[i].width = Emu(w)
    for i, h in enumerate(row_h):
        tbl.rows[i].height = Emu(h)
    tblPr = tbl._tbl.find(f"{{{A}}}tblPr")
    for k in list(tblPr.attrib):
        del tblPr.attrib[k]
    tblPr.set("firstRow", "1")
    tblPr.set("bandRow", "1")
    sid = tblPr.find(f"{{{A}}}tableStyleId")
    if sid is None:
        sid = etree.SubElement(tblPr, f"{{{A}}}tableStyleId")
    sid.text = "{5940675A-B579-460E-94D1-54222C63F5DA}"
    return gf


# ---------------------------------------------------------------- 메인
def build(ref, out):
    prs = Presentation(ref)
    assert (prs.slide_width, prs.slide_height) == (SLIDE_W, SLIDE_H)
    slide = prs.slides[0]
    sp_tree = slide.shapes._spTree

    # 1) header 요소 유지, 본문 제거 (shape_id 기준: 참조 dump)
    KEEP = {3, 5, 8, 39, 48, 31, 32, 38, 70, 57, 137,
            59, 60, 61, 62, 63, 64, 67, 97, 98, 101}
    for sh in list(slide.shapes):
        if sh.shape_id not in KEEP:
            sp_tree.remove(sh._element)

    by_id = {sh.shape_id: sh for sh in slide.shapes}

    # 2) title / subtitle 문구 교체 (run 서식은 참조 그대로 복제)
    title = by_id[3]
    r0 = title.text_frame.paragraphs[0].runs
    r0[0].text = "DP1. "
    r0[1].text = "C1 구조 보완 "
    r0[2].text = "(QA1 complement)"
    r0[3].text = " "
    r0[4].text = "- "
    r0[5].text = "설계"
    sub = by_id[8]
    rs = sub.text_frame.paragraphs[0].runs
    texts = ["C1의 QA1 격차 보완", ": ", "Activity", " 신호 + ", "Gate", " + ", "Pacer"]
    for i, r in enumerate(rs):
        r.text = texts[i] if i < len(texts) else ""
    TEXT_RECORDS.append(dict(name="title", w=title.width, h=title.height,
                             paras=[[("DP1. C1 구조 보완 (QA1 complement) - 설계", 2000, False, None)]],
                             ins=(91440, 45720, 91440, 45720), wrap="square", title=True))
    TEXT_RECORDS.append(dict(name="subtitle", w=sub.width, h=sub.height,
                             paras=[[("C1의 QA1 격차 보완: Activity 신호 + Gate + Pacer", 1400, True, None)]],
                             ins=(91440, 45720, 91440, 45720), wrap="square"))

    # 3) 구조 표 (설계 안 / 구조) : 참조와 같은 label 열 폭 875393, frame x=249035 y=1044054
    X0, Y0, TW = 249035, 1044054, 11747501
    LBL = 875393
    ROW_H = [342786, 2900000]
    gfA = add_table(slide, "표 구조", X0, Y0, [LBL, TW - LBL], ROW_H)
    ta = gfA.table
    ta.cell(0, 1).merge(ta.cell(0, 1))  # no-op, 1 colspan
    fmt_cell(ta.cell(0, 0), [[("설계 안", 1200, False, TBL_LBL)]], fill=TBL_FILL, algn="ctr",
             name="hdr-label", width=LBL)
    fmt_cell(ta.cell(0, 1), [[("(1안 보완) 메모리 Resource State driven Migration ", 1200, True, None),
                              ("+ Data-Memory Affinity", 1200, True, RED),
                              (" + Activity Tag Store / Gate / Pacer  [C] 설계 제안, 미구현", 1200, True, None)]],
             name="hdr-C1+", width=TW - LBL)
    fmt_cell(ta.cell(1, 0), [[("구조", 1200, False, TBL_LBL)]], fill=TBL_FILL, algn="ctr",
             name="row-label", width=LBL)
    fmt_cell(ta.cell(1, 1), [[("", 1050, False, None)]], name="diagram-cell")

    # headline quote (참조 TextBox 1 과 같은 위치/서식)
    q = slide.shapes.add_textbox(Emu(1111250), Emu(1397380), Emu(10700000), Emu(261610))
    q.name = "headline C1+"
    set_text(q, [[("“Data 종류 관계없이 ", 1100, False, None),
                  ("메모리 자원 상태(Capacity/BW/Load)", 1100, False, LINK_BLUE),
                  ("가 trigger인 구조를 유지하고, ", 1100, False, None),
                  ("Activity 신호는 후보 필터·가중·정렬", 1100, False, LINK_BLUE),
                  ("에만 사용한 Migration“", 1100, False, None)]],
             algn="l", anchor="t", name="headline")

    # 4) 다이어그램
    W, H = 1250000, 380000
    cx = lambda i: 1250000 + 1520000 * i       # column left
    R0, R1, R2, R3 = 1760000, 2200000, 2860000, 3520000

    def mid_x(n): x, y, w, h = NODES[n]; return x + w // 2
    def mid_y(n): x, y, w, h = NODES[n]; return y + h // 2
    def top(n): x, y, w, h = NODES[n]; return (x + w // 2, y)
    def bot(n): x, y, w, h = NODES[n]; return (x + w // 2, y + h)
    def left(n): x, y, w, h = NODES[n]; return (x, y + h // 2)
    def right(n): x, y, w, h = NODES[n]; return (x + w, y + h // 2)

    def B(sz=900): return lambda t: [[(t, sz, True, TXT)]]

    # 외부(공통) : Event Source
    add_box(slide, "Event Source", cx(0), R1, W, 1000000, GRAY_FILL, GRAY_LINE,
            [[("Serving runtime", 800, False, TXT)], [("Event Source", 800, False, TXT)],
             [("TELEMETRY", 650, False, SUBTXT)], [("ALLOCATED/FREED", 650, False, SUBTXT)],
             [("ACCESSED", 650, False, SUBTXT)]])
    # 기존 C1 블록 (blue)
    add_box(slide, "Resource State Monitor", cx(1), R1, W, H, BLUE_FILL, BLUE_LINE, B()("Resource State Monitor"))
    add_box(slide, "Resource-based Trend Analyzer", cx(2), R1, W, H, BLUE_FILL, BLUE_LINE,
            B()("Resource-based Trend Analyzer"))
    # 신규 B2
    add_box(slide, "No-benefit Rebalance Gate", cx(3), R1, W, H, NEW_FILL, NEW_LINE,
            B()("No-benefit Rebalance Gate"))
    # 변경 A3
    add_box(slide, "Data Eviction Manager", cx(4), R1, W, H, CHG_FILL, CHG_LINE, B()("Data Eviction Manager"))
    # Mapper (참조: noFill + 빨간 line)
    add_box(slide, "Data-Memory Affinity Mapper", cx(5), R1, W, H, None, RED,
            B()("Data-Memory Affinity Mapper"), lw=11430)
    add_box(slide, "Destination Tier Selector", cx(6), R1, W, H, BLUE_FILL, BLUE_LINE, B()("Destination Tier Selector"))
    # 공유 estimator (기존, R0)
    add_box(slide, "Access Cost Estimator", cx(5), R0, cx(6) + W - cx(5), 260000, BLUE_FILL, BLUE_LINE,
            [[("Access Cost Estimator", 900, True, TXT), (" (공유, descriptor 기반)", 700, False, TXT)]])
    # R2
    add_box(slide, "Activity Tag Store", cx(4), R2, W, H, NEW_FILL, NEW_LINE, B()("Activity Tag Store"))
    add_box(slide, "Promotion / Swap Pass", cx(5), R2, W, H, CHG_FILL, CHG_LINE, B()("Promotion / Swap Pass"))
    add_box(slide, "Data Object Registry", cx(6), R2, W, H, BLUE_FILL, BLUE_LINE, B()("Data Object Registry"))
    # R3 (오른쪽 -> 왼쪽)
    add_box(slide, "Migration Budget", cx(6), R3, W, H, CHG_FILL, CHG_LINE, B()("Migration Budget"))
    add_box(slide, "Staged Migration Pacer", cx(5), R3, W, H, NEW_FILL, NEW_LINE, B()("Staged Migration Pacer"))
    add_box(slide, "Migration Executor", cx(4), R3 + 60000, W, 260000, GRAY_FILL, GRAY_LINE,
            [[("Migration Executor", 800, False, TXT)]])
    # 공통 Memory Backend I/F bar (참조 MemIF bar)
    add_box(slide, "Memory Backend I/F", cx(4), 4030000, cx(6) + W - cx(4), 220000, DARK, None,
            [[("공통", 650, True, ("r", "FFFFFF")), (" Memory Backend I/F (Plug-in)", 650, True, ("r", "FFFFFF"))]],
            lw=0, ins=(18288, 9144, 18288, 9144))
    set_line(slide.shapes[-1], None)

    # tag chips (NEW / CHG) : box 위쪽 오른쪽 끝, 박스와 겹치지 않음
    for n, t, f in (("No-benefit Rebalance Gate", "NEW", NEW_LINE), ("Activity Tag Store", "NEW", NEW_LINE),
                    ("Staged Migration Pacer", "NEW", NEW_LINE), ("Data Eviction Manager", "CHG", CHG_LINE),
                    ("Promotion / Swap Pass", "CHG", CHG_LINE), ("Migration Budget", "CHG", CHG_LINE)):
        x, y, w, h = NODES[n]
        add_tag(slide, f"tag_{n}", x + w - 300000, y - 150000, t, f)

    # arrows : 기존=accent1(파랑) / event=회색 / 신규 관련=주황 / hint=빨강
    arrow(slide, "ES->RSM", right("Event Source")[0:1] + (mid_y("Resource State Monitor"),),
          left("Resource State Monitor"), GRAY_LINE, 6350, "Event Source", "Resource State Monitor")
    arrow(slide, "RSM->Trend", right("Resource State Monitor"), left("Resource-based Trend Analyzer"),
          ACC_BLUE, 11430, "Resource State Monitor", "Resource-based Trend Analyzer")
    arrow(slide, "Trend->B2", right("Resource-based Trend Analyzer"), left("No-benefit Rebalance Gate"),
          ACC_BLUE, 11430, "Resource-based Trend Analyzer", "No-benefit Rebalance Gate")
    arrow(slide, "B2->A3", right("No-benefit Rebalance Gate"), left("Data Eviction Manager"),
          NEW_LINE, 12700, "No-benefit Rebalance Gate", "Data Eviction Manager")
    arrow(slide, "A3->Mapper", right("Data Eviction Manager"), left("Data-Memory Affinity Mapper"),
          ACC_BLUE, 11430, "Data Eviction Manager", "Data-Memory Affinity Mapper")
    arrow(slide, "Mapper->DTS", right("Data-Memory Affinity Mapper"), left("Destination Tier Selector"),
          RED, 11430, "Data-Memory Affinity Mapper", "Destination Tier Selector")
    arrow(slide, "DTS->Registry", bot("Destination Tier Selector"), top("Data Object Registry"),
          ACC_BLUE, 11430, "Destination Tier Selector", "Data Object Registry")
    arrow(slide, "ACE->DTS", bot("Access Cost Estimator")[0:1] and (mid_x("Destination Tier Selector"),
          NODES["Access Cost Estimator"][1] + NODES["Access Cost Estimator"][3]),
          top("Destination Tier Selector"), ACC_BLUE, 11430, "Access Cost Estimator", "Destination Tier Selector")
    # ES -> A1 (ACCESSED, 신규 신호)
    arrow(slide, "ES->A1 ACCESSED", (cx(0) + W, mid_y("Activity Tag Store")), left("Activity Tag Store"),
          NEW_LINE, 12700, "Event Source", "Activity Tag Store")
    arrow(slide, "A1->A3 idle-first", top("Activity Tag Store"), bot("Data Eviction Manager"),
          NEW_LINE, 12700, "Activity Tag Store", "Data Eviction Manager")
    arrow(slide, "A1->A2 activity", right("Activity Tag Store"), left("Promotion / Swap Pass"),
          NEW_LINE, 12700, "Activity Tag Store", "Promotion / Swap Pass")
    arrow(slide, "A2->Registry", right("Promotion / Swap Pass"), left("Data Object Registry"),
          ACC_BLUE, 11430, "Promotion / Swap Pass", "Data Object Registry")
    arrow(slide, "Registry->Budget", bot("Data Object Registry"), top("Migration Budget"),
          ACC_BLUE, 11430, "Data Object Registry", "Migration Budget")
    arrow(slide, "Budget->Pacer", left("Migration Budget"), right("Staged Migration Pacer"),
          NEW_LINE, 12700, "Migration Budget", "Staged Migration Pacer")
    arrow(slide, "Pacer->Executor", left("Staged Migration Pacer"), right("Migration Executor"),
          NEW_LINE, 12700, "Staged Migration Pacer", "Migration Executor")
    arrow(slide, "Executor->I/F", bot("Migration Executor"), top("Memory Backend I/F"), DARK, 12700,
          "Migration Executor", "Memory Backend I/F", both=True, sm=True)
    # ACE -> B2 (est. SLO headroom): 위쪽 우회 polyline
    ace = NODES["Access Cost Estimator"]
    b2x = mid_x("No-benefit Rebalance Gate")
    ace_my = ace[1] + ace[3] // 2
    polyline(slide, "ACE->B2 SLO headroom", [(ace[0], ace_my), (b2x, ace_my), top("No-benefit Rebalance Gate")],
             NEW_LINE, 12700, "Access Cost Estimator", "No-benefit Rebalance Gate")

    # 화살표 라벨 (참조의 회색 700 라벨 스타일)
    add_label(slide, "lbl SLO headroom", b2x + 60000, 1665000, 2200000, 200000,
              [[("est. SLO headroom (이득 없으면 보류)", 700, False, SUBTXT)]])
    add_label(slide, "lbl ACCESSED", cx(1), mid_y("Activity Tag Store") - 230000, 3500000, 200000,
              [[("ACCESSED (기존 event, 현재 C1은 무시)", 700, False, SUBTXT)]])
    add_label(slide, "lbl idle-first", mid_x("Activity Tag Store") - 1140000, 2625000, 1100000, 200000,
              [[("idle-first", 700, False, SUBTXT)]], algn="r")
    # A1 -> A2 간격(270000) 이 좁으므로 A2 박스 안 서브 텍스트 대신 아래 라벨
    add_label(slide, "lbl activity", cx(4) + 100000, R2 + H + 20000, 1900000, 200000,
              [[("activity 가중 비교 (활성 객체만)", 700, False, SUBTXT)]])

    # 범례 (existing / new / changed)
    LX, LY = cx(0), 3300000
    add_label(slide, "legend title", LX, LY, 700000, 200000, [[("범례", 800, True, TXT)]])
    items = [("기존 C1 블록 (참조 그대로)", BLUE_FILL, BLUE_LINE, 0, 0),
             ("신규 (NEW)", NEW_FILL, NEW_LINE, 0, 1),
             ("변경 (CHG)", CHG_FILL, CHG_LINE, 0, 2)]
    for t, f, l, c, r in items:
        yy = LY + 230000 + r * 190000
        s = add_box(slide, f"legend sw {t}", LX + 60000, yy + 30000, 300000, 130000, f, l, [[("", 600, False, TXT)]],
                    node=False)
        add_label(slide, f"legend {t}", LX + 400000, yy, 2300000, 190000, [[(t, 800, False, TXT)]])
    # 화살표 범례
    for i, (t, col) in enumerate((("기존 flow", ACC_BLUE), ("신규 신호/flow", NEW_LINE), ("static hint", RED))):
        yy = LY + 230000 + i * 190000
        xx = LX + 2650000
        c = slide.shapes.add_connector(MSO_CONNECTOR.STRAIGHT, Emu(xx), Emu(yy + 95000), Emu(xx + 320000), Emu(yy + 95000))
        c.name = f"legend arrow {t}"
        strip_style(c)
        set_line(c, col, 11430 if col != NEW_LINE else 12700, "solid", tail="triangle")
        add_label(slide, f"legend arrow lbl {t}", xx + 360000, yy, 1000000, 190000, [[(t, 800, False, TXT)]])
    # 범례 외곽 (dashed, 참조의 점선 박스 스타일)
    fr = slide.shapes.add_shape(MSO_SHAPE.RECTANGLE, Emu(LX), Emu(LY - 20000), Emu(4150000), Emu(850000))
    fr.name = "legend frame"
    strip_style(fr)
    set_fill(fr, None)
    set_line(fr, GRAY_LINE, 6350, "dash")
    # fence 메모 (dashed 라벨)
    add_label(slide, "fence note", 5600000, 3300000, 1650000, 560000,
              [[("정체성 fence", 700, True, SUBTXT)],
               [("activity는 새 trigger 아님", 700, False, SUBTXT)],
               [("객체당 상태 2개 · type 없음", 700, False, SUBTXT)],
               [("새 상수 없음", 700, False, SUBTXT)]], border=SUBTXT)

    # 5) 컴포넌트 표 (참조 표 스타일)
    BX, BY = 249035, 4335000
    cw = [875393, 2380000, 3500000, 3500000, 0]
    cw[4] = TW - sum(cw[:4])
    rh = [260000] + [312000] * 5
    gfB = add_table(slide, "표 컴포넌트", BX, BY, cw, rh)
    tb = gfB.table
    heads = ["ID", "컴포넌트", "역할", "겨냥하는 QA1 진단 gap", "검증 상태"]
    for i, h in enumerate(heads):
        fmt_cell(tb.cell(0, i), [[(h, 1000, False if i == 0 else True, TBL_LBL if i == 0 else None)]],
                 fill=TBL_FILL, algn="ctr", mar=(91440, 18288, 91440, 18288), name=f"th{i}", width=cw[i])
    NEWC = ("r", "C76E31")
    CHGC = ("s", "accent6", {"lumMod": 75000})
    rows = [
        ("A1", "Activity Tag Store ", "신규", NEWC,
         "ACCESSED로 last_access·window count만 기록 (side-car)",
         "D1·D2·D3 같은 class KV 쌍(QA1 격차 96.5%), 접근 신호 없음"),
        ("A2", "Promotion / Swap Pass ", "변경", CHGC,
         "static SLO 위반 + 활성 객체만, gain×act ≥ margin×loss×act",
         "D1·D2 gain=loss라 swap 불통과 (10/15 run 이동 없음)"),
        ("A3", "Data Eviction Manager ", "변경", CHGC,
         "victim 순서를 idle 우선으로 (기존 key는 tie-break)",
         "D2 eviction key가 residency age"),
        ("B2", "No-benefit Rebalance Gate ", "신규", NEWC,
         "압박·SLO headroom 없으면 rebalance 보류",
         "D4 이득 없는 이동, TTFT P99 꼬리 (QA2 쪽)"),
        ("B1", "Staged Migration Pacer ", "신규", NEWC,
         "chunk/tick 전송, share=min(LINK_SHARE, 1-bw_util)",
         "D4·D5 큰 객체 admission (QA1 <-> QA2)"),
    ]
    for r, (idn, nm, tag, tc_, role, gap) in enumerate(rows, start=1):
        mar = (91440, 18288, 91440, 18288)
        fmt_cell(tb.cell(r, 0), [[(idn, 1000, False, TBL_LBL)]], fill=TBL_FILL, algn="ctr", mar=mar,
                 name=f"id{r}", width=cw[0])
        fmt_cell(tb.cell(r, 1), [[(nm, 900, True, None), (f"({tag})", 900, True, tc_)]], mar=mar,
                 name=f"nm{r}", width=cw[1])
        fmt_cell(tb.cell(r, 2), [[(role, 900, False, None)]], mar=mar, name=f"role{r}", width=cw[2])
        fmt_cell(tb.cell(r, 3), [[(gap, 900, False, None)]], mar=mar, name=f"gap{r}", width=cw[3])
        fmt_cell(tb.cell(r, 4), [[("[C] 미구현" + (" (M-class)" if idn == "B1" else ""), 900, False, None)]],
                 mar=mar, name=f"st{r}", width=cw[4])
    table_bottom = BY + sum(rh)

    # 6) takeaway bar (참조 header bar 와 같은 회색 rect + 흰색 bold)
    TY = 6195000
    bar = slide.shapes.add_shape(MSO_SHAPE.RECTANGLE, Emu(234949), Emu(TY), Emu(11747501), Emu(300000))
    bar.name = "takeaway"
    strip_style(bar)
    set_fill(bar, ("s", "bg1", {"lumMod": 50000}))
    set_line(bar, None)
    set_text(bar, [[("한 줄 요약: ", 1100, True, WHITE),
                    ("Activity는 trigger가 아니라 후보 필터·가중·정렬에만 써서 C1 정체성을 지킨다. 효과는 모두 [C] 논증이며 미구현", 1100, True, WHITE)]],
             algn="l", anchor="ctr", name="takeaway")
    NODES["__table_bottom__"] = (0, table_bottom, 0, 0)
    NODES["__takeaway__"] = (234949, TY, 11747501, 300000)

    os.makedirs(os.path.dirname(os.path.abspath(out)), exist_ok=True)
    prs.save(out)
    return prs, (gfA, gfB)


# ---------------------------------------------------------------- 검증
def char_w(ch, sz, bold):
    """보수적 폭(pt). CJK full-width = 1.0*sz, 대문자/숫자 0.65, 소문자 0.58, 공백 0.3."""
    ea = unicodedata.east_asian_width(ch)
    if ea in ("W", "F") or "가" <= ch <= "힣":
        return sz * 1.0
    if ch == " ":
        return sz * 0.32
    if ch.isupper() or ch.isdigit():
        return sz * (0.68 if bold else 0.64)
    if ch in "·→<>=×-/()[]":
        return sz * 0.6
    return sz * (0.6 if bold else 0.56)


def n_lines(runs, width_pt):
    lines, cur = 1, 0.0
    for text, sz, bold, _ in runs:
        for word in text.replace("\n", " \n ").split(" "):
            if word == "\n":
                lines += 1; cur = 0; continue
            ww = sum(char_w(c, sz / 100.0, bold) for c in word)
            sp = char_w(" ", sz / 100.0, bold)
            if cur + ww > width_pt and cur > 0:
                # CJK 는 글자 단위로 줄바꿈 가능
                if any(unicodedata.east_asian_width(c) in ("W", "F") for c in word) and ww > width_pt:
                    pass
                lines += 1; cur = 0
            while ww > width_pt:   # 한 단어가 한 줄보다 긴 경우
                lines += 1; ww -= width_pt
            cur += ww + sp
    return lines


def verify(prs, frames):
    ok = True
    problems = []
    EMU_PT = 12700.0
    slide = prs.slides[0]
    # (1) 슬라이드 경계
    for sh in slide.shapes:
        x, y, w, h = sh.left, sh.top, sh.width, sh.height
        if x < 0 or y < 0 or x + w > SLIDE_W or y + h > SLIDE_H:
            problems.append(f"OUT OF SLIDE: {sh.name} {x,y,w,h}")
    # (2) 텍스트 overflow
    for rec in TEXT_RECORDS:
        l, t, r, b = rec["ins"]
        wpt = (rec["w"] - l - r) / EMU_PT
        hpt = (rec["h"] - t - b) / EMU_PT
        total = 0.0
        for runs in rec["paras"]:
            n = n_lines(runs, wpt) if rec["wrap"] == "square" else 1
            mx = max((sz for _, sz, _, _ in runs), default=900) / 100.0
            total += n * mx * 1.2
        if rec.get("title"):
            continue
        if total > hpt + 0.5:
            problems.append(f"TEXT OVERFLOW: {rec['name']} need {total:.1f}pt > {hpt:.1f}pt")
    # 표 셀
    for gf, tag in zip(frames, ("A", "B")):
        pass
    tot_need = {}
    for rec in CELL_RECORDS:
        l, t, r, b = rec["mar"]
        wpt = (rec["w"] - l - r) / EMU_PT
        need = sum(n_lines(runs, wpt) * max(sz for _, sz, _, _ in runs) / 100.0 * 1.2 for runs in rec["paras"]) \
            + (t + b) / EMU_PT
        rec["need_emu"] = need * EMU_PT
    # 표 B: row 별 필요 높이 vs 설정 높이
    gfB = frames[1]
    rh = [r.height for r in gfB.table.rows]
    for ri in range(len(rh)):
        needs = [c["need_emu"] for c in CELL_RECORDS if c["name"].endswith(str(ri)) and ri > 0
                 and c["name"][:2] in ("id", "nm", "ro", "ga", "st")]
        if ri == 0:
            needs = [c["need_emu"] for c in CELL_RECORDS if c["name"].startswith("th")]
        if needs and max(needs) > rh[ri] + 1000:
            problems.append(f"TABLE ROW {ri} grows: need {max(needs):.0f} > {rh[ri]}")
            rh[ri] = int(max(needs))
    tb_bottom = gfB.top + sum(rh)
    tk = NODES["__takeaway__"]
    if tb_bottom > tk[1] - 20000:
        problems.append(f"TABLE B bottom {tb_bottom} collides with takeaway {tk[1]}")
    # 구조 표 bottom 과 표 B 간격
    gfA = frames[0]
    a_bottom = gfA.top + sum(r.height for r in gfA.table.rows)
    if a_bottom > gfB.top:
        problems.append(f"TABLE A bottom {a_bottom} overlaps TABLE B top {gfB.top}")
    # 레이아웃 하단 구분선(y=6540500)
    if tk[1] + tk[3] > 6540500:
        problems.append("takeaway crosses footer line")
    # (3) 노드 겹침 (+ diagram frame 안에 있는지)
    names = [n for n in NODES if not n.startswith("__")]
    for i, a in enumerate(names):
        ax, ay, aw, ah = NODES[a]
        if ay < gfA.top + gfA.table.rows[0].height or ay + ah > a_bottom:
            problems.append(f"NODE outside diagram cell: {a}")
        for b in names[i + 1:]:
            bx, by, bw, bh = NODES[b]
            if ax < bx + bw and bx < ax + aw and ay < by + bh and by < ay + ah:
                problems.append(f"NODE OVERLAP: {a} <-> {b}")
    # (4) 화살표 endpoint 가 박스 edge 위에 있는지
    def on_edge(pt, n):
        x, y, w, h = NODES[n]
        px, py = pt
        inx = x - 2 <= px <= x + w + 2
        iny = y - 2 <= py <= y + h + 2
        return (inx and (abs(py - y) <= 2 or abs(py - (y + h)) <= 2)) or \
               (iny and (abs(px - x) <= 2 or abs(px - (x + w)) <= 2))
    for name, p1, p2, fn, tn in ARROWS:
        if fn and not on_edge(p1, fn):
            problems.append(f"ARROW start not on edge: {name} {p1} {fn}")
        if tn and not on_edge(p2, tn):
            problems.append(f"ARROW end not on edge: {name} {p2} {tn}")
        # 선분이 다른 노드를 관통하는지 (직선만; polyline 은 첫/마지막 선분 제외 근사)
        segs = [(p1, p2)]
        for nn in names:
            if nn in (fn, tn):
                continue
            x, y, w, h = NODES[nn]
            (x1, y1), (x2, y2) = p1, p2
            if x1 == x2:   # 수직
                if x - 0 < x1 < x + w and min(y1, y2) < y + h and max(y1, y2) > y:
                    problems.append(f"ARROW crosses node: {name} x {nn}")
            elif y1 == y2:
                if y < y1 < y + h and min(x1, x2) < x + w and max(x1, x2) > x:
                    problems.append(f"ARROW crosses node: {name} x {nn}")
    return problems


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--ref", default=DEFAULT_REF)
    here = os.path.dirname(os.path.abspath(__file__))
    ap.add_argument("--out", default=os.path.normpath(
        os.path.join(here, "..", "..", "DP1", "DP1-c1-qa1-complement-structure-styled.pptx")))
    args = ap.parse_args()
    if not os.path.exists(args.ref):
        sys.exit(f"reference deck not found: {args.ref} (use --ref)")
    prs, frames = build(args.ref, args.out)
    probs = verify(prs, frames)
    print("saved:", args.out)
    if probs:
        print("VERIFY PROBLEMS:")
        for p in probs:
            print(" -", p)
        sys.exit(1)
    print("verify OK: bounds / text fit / node overlap / arrow edges")


if __name__ == "__main__":
    main()
