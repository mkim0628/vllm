"""DP PPT 제작 예시 스크립트 (doc-mk/slides/README.md 참고).

reference/DP-PPT-style-reference.pptx 를 템플릿으로 열어 기존 슬라이드를 지우고, 레이아웃 "1_제목 및 내용"에
내비게이션/띠/칩/점선 패널/표 헬퍼로 슬라이드를 만든다. 내용은 DP2 후보 구조(A / B′ / C) 예시이며,
다른 DP를 만들 때는 아래 슬라이드 정의부(# ==== 1 배경 이후)만 바꿔 쓴다.

실행: python build_dp_deck_example.py <reference.pptx> <out.pptx>   (python-pptx 필요, .venv 사용)
"""
import sys, copy
from pptx import Presentation
from pptx.util import Inches, Pt, Emu
from pptx.dml.color import RGBColor
from pptx.enum.shapes import MSO_SHAPE, MSO_CONNECTOR
from pptx.enum.text import PP_ALIGN, MSO_ANCHOR
from pptx.oxml.ns import qn
from lxml import etree

REF, OUT = sys.argv[1], sys.argv[2]
FONT = "맑은 고딕"
C = lambda h: RGBColor.from_string(h)
BLACK, WHITE = C("000000"), C("FFFFFF")
G40, G59, G7F, GBF, GD9, GF2, GF0 = C("404040"), C("595959"), C("7F7F7F"), C("BFBFBF"), C("D9D9D9"), C("F2F2F2"), C("F0F1F3")
BLUE, LBLUE = C("2E75B6"), C("DEEBF7")
ORG, LORG = C("C55A11"), C("FBE5D6")
GRN, LGRN = C("548235"), C("E2F0D9")
KEY = C("0066FF")
RED = C("FF0000")
CF, CQ, CC = C("203864"), C("833C0B"), C("375623")   # FR / QA / 제약 chips
TOTAL = 1

prs = Presentation(REF)
# ---- drop the reference slides (keep master/layout/theme)
sldIdLst = prs.slides._sldIdLst
for sldId in list(sldIdLst):
    prs.part.drop_rel(sldId.rId)
    sldIdLst.remove(sldId)
LAY = [l for l in prs.slide_layouts if l.name == "1_제목 및 내용"][0]
for sh in list(LAY.shapes):
    if sh.shape_type == 6:          # nav group -> drawn per slide
        sh._element.getparent().remove(sh._element)
    elif sh.has_text_frame and sh.text_frame.text.strip() == "/ 23":
        r = sh.text_frame.paragraphs[0].runs[0]
        r.text = ""
        for extra in sh.text_frame.paragraphs[0].runs[1:]:
            extra.text = ""
NAV = ["과제 소개", "요구사항", "설계", "구현/검증", "결론"]
NX = [8.227, 9.203, 10.186, 11.162, 12.145]
NW = [1.128, 1.128, 1.128, 1.128, 0.976]


def set_font(run, size, bold=False, color=BLACK):
    run.font.name = FONT
    run.font.size = Pt(size)
    run.font.bold = bold
    run.font.color.rgb = color
    rPr = run._r.get_or_add_rPr()
    for tag in ("a:ea", "a:cs"):
        el = rPr.find(qn(tag))
        if el is None:
            el = etree.SubElement(rPr, qn(tag))
        el.set("typeface", FONT)


def shape(slide, kind, x, y, w, h, fill=None, line=None, lw=0.8, dash=False):
    s = slide.shapes.add_shape(kind, Inches(x), Inches(y), Inches(w), Inches(h))
    if fill is None:
        s.fill.background()
    else:
        s.fill.solid(); s.fill.fore_color.rgb = fill
    if line is None:
        s.line.fill.background()
    else:
        s.line.color.rgb = line; s.line.width = Pt(lw)
        if dash:
            ln = s.line._get_or_add_ln()
            d = etree.SubElement(ln, qn("a:prstDash")); d.set("val", "dash")
    s.shadow.inherit = False
    return s


def write(s, paras, size=10, color=BLACK, bold=False, align=PP_ALIGN.LEFT, anchor=MSO_ANCHOR.TOP, margin=0.05, space=2):
    tf = s.text_frame
    tf.word_wrap = True
    tf.vertical_anchor = anchor
    tf.margin_left = tf.margin_right = Inches(margin)
    tf.margin_top = tf.margin_bottom = Inches(0.03)
    first = True
    for p in paras:
        t, o = (p, {}) if isinstance(p, str) else p
        para = tf.paragraphs[0] if first else tf.add_paragraph()
        first = False
        para.alignment = o.get("align", align)
        para.space_after = Pt(o.get("space", space))
        for st, so in (o.get("segs") or [(t, {})]):
            r = para.add_run(); r.text = st
            set_font(r, o.get("size", size), so.get("bold", o.get("bold", bold)), so.get("color", o.get("color", color)))
    return s


def tbox(slide, x, y, w, h, paras, **kw):
    s = slide.shapes.add_textbox(Inches(x), Inches(y), Inches(w), Inches(h))
    return write(s, paras, **kw)


def rect(slide, x, y, w, h, paras, fill=WHITE, line=G59, lw=0.8, size=9, bold=False, align=PP_ALIGN.CENTER,
         anchor=MSO_ANCHOR.MIDDLE, color=BLACK, dash=False, kind=MSO_SHAPE.RECTANGLE, **kw):
    s = shape(slide, kind, x, y, w, h, fill, line, lw, dash)
    return write(s, paras, size=size, bold=bold, align=align, anchor=anchor, color=color, **kw)


def arrow(slide, x1, y1, x2, y2, color=G7F, w=1.0, dash=False, both=False):
    c = slide.shapes.add_connector(MSO_CONNECTOR.STRAIGHT, Inches(x1), Inches(y1), Inches(x2), Inches(y2))
    c.line.color.rgb = color; c.line.width = Pt(w)
    ln = c.line._get_or_add_ln()
    if dash:
        d = etree.SubElement(ln, qn("a:prstDash")); d.set("val", "dash")
    if both:
        h = etree.SubElement(ln, qn("a:headEnd")); h.set("type", "triangle")
    t = etree.SubElement(ln, qn("a:tailEnd")); t.set("type", "triangle")
    return c


def new_slide(title, nav):
    s = prs.slides.add_slide(LAY)
    s.shapes.title.text = title
    for i, (n, x, w) in enumerate(zip(NAV, NX, NW)):
        cur = i == nav
        sh = shape(s, MSO_SHAPE.CHEVRON, x, 0.15, w, 0.391, G59 if cur else GBF)
        write(sh, [n], size=10, bold=True, color=WHITE, align=PP_ALIGN.CENTER, anchor=MSO_ANCHOR.MIDDLE, margin=0)
    shape(s, MSO_SHAPE.RECTANGLE, 8.234, 0.15, 0.232, 0.391, G59 if nav == 0 else GBF)
    shape(s, MSO_SHAPE.RECTANGLE, 12.893, 0.15, 0.232, 0.391, G59 if nav == 4 else GBF)
    return s


def pageno(s, n):
    tbox(s, 5.85, 7.2, 0.68, 0.26, [(str(n), {"align": PP_ALIGN.RIGHT})], size=10, color=G7F)


def band(s, text, chips=()):
    shape(s, MSO_SHAPE.RECTANGLE, 0.26, 0.65, 12.85, 0.43, G7F)
    shape(s, MSO_SHAPE.RECTANGLE, 0.44, 0.74, 0.07, 0.24, WHITE)
    tbox(s, 0.51, 0.68, 8.3, 0.36, [text], size=14, bold=True, color=WHITE, anchor=MSO_ANCHOR.MIDDLE)
    x = 13.01
    for name, col in reversed(chips):
        w = 0.78
        x -= w + 0.04
        b = shape(s, MSO_SHAPE.ROUNDED_RECTANGLE, x, 0.69, w, 0.35, col)
        write(b, [name], size=9, bold=True, color=WHITE, align=PP_ALIGN.CENTER, anchor=MSO_ANCHOR.MIDDLE, margin=0)


def dashed(s, x, y, w, h, label, lw=2.6):
    shape(s, MSO_SHAPE.RECTANGLE, x, y, w, h, None, GBF, 1.0, dash=True)
    r = shape(s, MSO_SHAPE.ROUNDED_RECTANGLE, x + (w - lw) / 2, y - 0.17, lw, 0.34, GF2, G7F, 0.8)
    write(r, [label], size=12, bold=True, align=PP_ALIGN.CENTER, anchor=MSO_ANCHOR.MIDDLE, margin=0.02)


def container(s, x, y, w, h, title, fill, line, tsize=9):
    shape(s, MSO_SHAPE.RECTANGLE, x, y, w, h, fill, line, 1.0)
    r = shape(s, MSO_SHAPE.RECTANGLE, x, y, w, 0.24, line, line)
    write(r, [title], size=tsize, bold=True, color=WHITE, align=PP_ALIGN.CENTER, anchor=MSO_ANCHOR.MIDDLE, margin=0.02)


def keymsg(s, y, text, issues):
    ar = shape(s, MSO_SHAPE.RIGHT_ARROW, 0.31, y, 0.45, 0.3, BLUE, None)
    tbox(s, 0.8, y - 0.02, 12.2, 0.34, [text], size=12, bold=True, color=KEY, anchor=MSO_ANCHOR.MIDDLE)
    tbox(s, 0.42, y + 0.34, 12.5, 0.6, issues, size=11, bold=True, space=1)


def table(s, x, y, colw, rows, heights, hdr=True, size=10.5, fills=None, first_color=G7F, align_first=PP_ALIGN.CENTER):
    nr, nc = len(rows), len(colw)
    gs = s.shapes.add_table(nr, nc, Inches(x), Inches(y), Inches(sum(colw)), Inches(sum(heights)))
    tb = gs.table
    tbl = gs._element.graphic.graphicData.tbl
    sid = tbl.tblPr.find(qn("a:tableStyleId"))
    if sid is not None:
        sid.text = "{2D5ABB26-0587-4C30-8999-92F81FD0307C}"   # no style, no grid
    tbl.tblPr.set("bandRow", "0"); tbl.tblPr.set("firstRow", "0")
    for i, w in enumerate(colw):
        tb.columns[i].width = Inches(w)
    for r in range(nr):
        tb.rows[r].height = Inches(heights[r])
        for c in range(nc):
            cell = tb.cell(r, c)
            val = rows[r][c]
            cell.margin_left = cell.margin_right = Inches(0.07)
            cell.margin_top = cell.margin_bottom = Inches(0.03)
            cell.vertical_anchor = MSO_ANCHOR.MIDDLE
            tf = cell.text_frame; tf.word_wrap = True
            items = val if isinstance(val, list) else [val]
            for k, it in enumerate(items):
                para = tf.paragraphs[0] if k == 0 else tf.add_paragraph()
                text, o = (it, {}) if isinstance(it, str) else it
                para.space_after = Pt(1)
                head = hdr and r == 0
                if c == 0 or head:
                    para.alignment = o.get("align", PP_ALIGN.CENTER if (head or align_first == PP_ALIGN.CENTER) else PP_ALIGN.LEFT)
                for st, so in (o.get("segs") or [(text, {})]):
                    run = para.add_run(); run.text = st
                    col = first_color if (c == 0 or head) else so.get("color", o.get("color", BLACK))
                    set_font(run, o.get("size", size + (1 if head else 0)), so.get("bold", o.get("bold", head and c > 0)), col)
            cell.fill.solid()
            cell.fill.fore_color.rgb = (fills or {}).get((r, c), WHITE)
            tcPr = cell._tc.get_or_add_tcPr()
            fill_el = tcPr.find(qn("a:solidFill"))
            if fill_el is not None:
                tcPr.remove(fill_el)
            for tag in ("a:lnL", "a:lnR", "a:lnT", "a:lnB"):
                ln = etree.SubElement(tcPr, qn(tag)); ln.set("w", "6350")
                sf = etree.SubElement(ln, qn("a:solidFill")); cl = etree.SubElement(sf, qn("a:srgbClr")); cl.set("val", "BFBFBF")
            if fill_el is not None:
                tcPr.append(fill_el)
    return gs


def bullets(items, size=10.5):
    return [("• " + t if isinstance(t, str) else ("• " + t[0], t[1])) for t in items]


def notes(s, t):
    s.notes_slide.notes_text_frame.text = t


# ================================================================ 과제 필요성 (1장)
DARK = C("404040")
LX, RX, PW = 0.26, 6.78, 6.30


def panel(x, y, h, title):
    shape(s, MSO_SHAPE.RECTANGLE, x, y + 0.17, PW, h - 0.17, None, GBF, 1.0, dash=True)
    r = shape(s, MSO_SHAPE.RECTANGLE, x + 0.12, y, PW - 0.24, 0.34, DARK)
    write(r, [title], size=13, bold=True, color=WHITE, align=PP_ALIGN.CENTER, anchor=MSO_ANCHOR.MIDDLE, margin=0.02)


def head(x, y, text, w=None):
    tbox(s, x, y, w or PW - 0.3, 0.3, ["■ " + text], size=10.5, bold=True, anchor=MSO_ANCHOR.MIDDLE)


s = new_slide("과제 필요성", 0)
tbox(s, 4.6, 0.17, 3.4, 0.35, [("System 연구 필요성  ▶", {"align": PP_ALIGN.RIGHT})], size=9, color=G7F, anchor=MSO_ANCHOR.MIDDLE)

# ---------------- 좌상: HBM 유지 + 불확실한 추가 수요
panel(LX, 1.0, 2.78, "HBM 수요는 유지, 어떤 메모리가 더 커질지는 불확실")
head(LX + 0.15, 1.40, "HBM 시장·수요를 해치지 않는 선에서 커질 메모리 type을 미리 대비")
tbox(s, 0.45, 1.72, 3.0, 0.22, ["AI 메모리 수요"], size=9, color=G7F, bold=True)
tbox(s, 3.55, 1.72, 3.0, 0.22, ["추가 수요 후보 (규모·순서 미정)"], size=9, color=G7F, bold=True)
rect(s, 0.55, 2.38, 0.95, 0.85, [("HBM", {"bold": True, "size": 10}), ("현재 수요", {"size": 8})], fill=LBLUE, line=BLUE, lw=1.2)
arrow(s, 1.6, 2.8, 2.45, 2.8, G59, 1.5)
tbox(s, 1.5, 2.28, 1.1, 0.5, [("AI 추론 · Agent 확산", {"align": PP_ALIGN.CENTER})], size=8, color=G59)
rect(s, 2.55, 2.38, 0.95, 0.85, [("HBM", {"bold": True, "size": 10}), ("유지 · 보존", {"size": 8, "color": BLUE})], fill=LBLUE, line=BLUE, lw=1.2)
tbox(s, 3.47, 2.6, 0.2, 0.4, ["+"], size=16, bold=True, color=G7F)
cands = [("CXL\nMemory", LGRN, GRN), ("Custom\nHBM", LBLUE, BLUE), ("HBF", LORG, ORG), ("기타\nPIM·PNM", GF0, G7F)]
for i, (t, f, l) in enumerate(cands):
    x = 3.75 + i * 0.70
    rect(s, x, 1.97, 0.62, 1.26, [("?", {"size": 16, "bold": True, "color": l}), (t, {"size": 8, "bold": True})], fill=f, line=l, lw=1.2, dash=True, margin=0.01)
tbox(s, 0.45, 3.24, 6.1, 0.2, ["※ 점선 막대의 높이는 규모 미정을 뜻하는 표기이며 실제 수치가 아님"], size=7, color=G7F)
ar = shape(s, MSO_SHAPE.RIGHT_ARROW, 0.38, 3.52, 0.3, 0.2, BLUE)
tbox(s, 0.72, 3.45, 5.8, 0.34, ["어느 type이 커질지 알 수 없으므로, 제품별 SW 솔루션을 미리 준비"], size=10.5, bold=True, color=KEY, anchor=MSO_ANCHOR.MIDDLE)

# ---------------- 우상: Offloading / Scheduling 효과
panel(RX, 1.0, 2.78, "런타임 역할의 한계: Offloading · Scheduling 효과 (공개 사례)")
head(RX + 0.15, 1.40, "Agent의 자원 수요가 동적으로 변하는 상황에서 런타임 역할이 결정적")
tbox(s, RX + 0.3, 2.05, PW - 0.6, 1.4, [
    ("", {"segs": [("Offloading 하는 경우 vs 안하는 경우 ", {}), ("성능 차이", {"bold": True})], "align": PP_ALIGN.CENTER, "space": 14}),
    ("", {"segs": [("스케줄링 하는 경우 vs 안하는 경우 성능 차이", {"bold": True})], "align": PP_ALIGN.CENTER}),
], size=18, anchor=MSO_ANCHOR.MIDDLE)

# ---------------- 좌하: HBM 외 제품 Biz Impact
panel(LX, 3.95, 2.30, "HBM 외 제품의 Biz Impact: HBM과 상호 보완")
head(LX + 0.15, 4.30, "HBM의 수요를 뺏지 않고, HBM이 담지 못하는 영역을 채움")
hdrs = ["제품", "담당 데이터", "시장 전망 (2030, 공개 전망)", "HBM 수요 영향"]
rows = [hdrs,
        ["HBM", "활성 KV·가중치", [("> $100B (Micron 전망) ①", {})], [("기준선, 수요 유지", {"bold": True, "color": BLUE})]],
        ["Custom HBM", "HBM 변형 (base die 맞춤)", "수십 B$ (SK hynix 전망) ②", [("HBM 시장 내 성장", {"color": BLUE})]],
        ["CXL Memory", "유휴·재사용 KV", "약 $4–7B (범위 정의별 차이) ③", [("HBM 비대체, DRAM 확장", {"color": BLUE})]],
        ["HBF", "대용량·저비용 계층", "$40–150B (Goldman, 2차 인용) ④", [("HBM 비대체, 신규 Tier", {"color": BLUE})]]]
table(s, LX + 0.1, 4.62, [0.95, 1.55, 2.2, 1.3], rows, [0.22, 0.3, 0.3, 0.3, 0.3], size=8, first_color=G40)

# ---------------- 우하: 이기종 메모리 인지 SW 부재
panel(RX, 3.95, 2.30, "이기종 메모리를 인지하는 SW의 부재")
head(RX + 0.15, 4.30, "새 메모리를 AI 워크로드와 연결하는 소프트웨어 계층이 없음")
rect(s, RX + 0.3, 4.64, 5.7, 0.30, [("AI 워크로드 (LLM 추론 · Agent: 자원 수요가 동적으로 변동)", {"bold": True})], fill=LBLUE, line=BLUE, size=9)
arrow(s, RX + 3.15, 4.94, RX + 3.15, 5.06, RED, 1.5, dash=True)
rect(s, RX + 0.3, 5.06, 5.7, 0.54, [("이기종 메모리 인지형 런타임:  부재 (공백)", {"bold": True, "color": RED, "size": 11}),
                                    ("메모리 특성(대역폭·용량·연산 가능 여부) 인식 → 배치·스케줄링 결정", {"size": 8.5, "color": G59})],
     fill=WHITE, line=RED, lw=1.5, dash=True)
arrow(s, RX + 3.15, 5.6, RX + 3.15, 5.74, RED, 1.5, dash=True, both=True)
devs = [("HBM", 0), ("DRAM", 0), ("SSD", 0), ("CXL-Memory", 1), ("CXL-PNM", 1), ("HBF · PIM", 1)]
for i, (t, new) in enumerate(devs):
    rect(s, RX + 0.22 + i * 0.97, 5.74, 0.9, 0.28, [t], fill=GF0 if not new else WHITE, line=G7F if not new else ORG, lw=1.0, size=8.5, bold=True, dash=bool(new), margin=0.01)
tbox(s, RX + 0.22, 6.02, 2.9, 0.18, ["기존 메모리 계층"], size=7, color=G7F)
tbox(s, RX + 3.1, 6.02, 3.0, 0.18, [("신규 메모리: 특성 미인식 → 활용 불가", {"align": PP_ALIGN.RIGHT, "color": ORG})], size=7)

# ---------------- 하단 결론
ban = shape(s, MSO_SHAPE.ROUNDED_RECTANGLE, 0.26, 6.28, 12.85, 0.38, LORG)
write(ban, ["LLM 추론 처리량 향상을 위한 이기종 메모리 인지형 런타임 연구 개발 필요"], size=14, bold=True, color=C("C55A11"), align=PP_ALIGN.CENTER, anchor=MSO_ANCHOR.MIDDLE)

# ---------------- 출처
src = [
    "※ 시장 전망은 출처·범위 정의별 편차가 큼(검증 전 공개 전망).",
    "① Micron FQ1'25 실적발표(2024 $16B → 2030 > $100B, 회사 전망)  ② SK hynix 전망, Tom's Hardware  ③ Mordor Intelligence·Business Research Co. 등(2030 약 $4–7B, 보수적 정의 기준)  ④ Goldman Sachs 추정의 2차 인용(404k Research Substack), 원문 미확인; 샘플 2026 하반기·소규모 상용 2027–28 (OSCOO)",
]
tbox(s, 0.26, 6.70, 12.85, 0.7, src, size=6.5, color=G59, space=0)

notes(s, "핵심: 우리는 HBM 수요를 건드리지 않고, 앞으로 커질 수 있는 메모리 type(CXL, Custom HBM, HBF 등)별로 SW 솔루션을 미리 준비한다.\n"
         "근거: (a) offloading과 (b) scheduling 모두 baseline 대비 1.5배 이상의 처리량/지연 개선이 공개 사례로 확인되나, 모두 동질 계층(HBM-DRAM-SSD) 전제이다. 이기종 메모리 특성을 인지하는 런타임은 확인되지 않는다.\n"
         "의미: 수요가 확정된 후 대응하면 늦으므로 이기종 메모리 인지형 런타임을 선제 연구한다.\n"
         "주의: 시장 규모는 출처별 정의 편차가 크고 HBF 수치는 2차 인용이다. 'HBM 수요 영향' 열은 분석가 판단이다.")
prs.save(OUT)
print("saved", OUT)
