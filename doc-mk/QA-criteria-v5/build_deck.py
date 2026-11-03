"""QA-01~05 별 기준·근거 슬라이드 5장 생성.

템플릿: 사용자가 준 품질 요구사항 PPT(2~5쪽 서식). 입력 덱의 마스터·레이아웃·내비게이션 도형을 재사용한다.
사용: python build_deck.py <in.pptx> <out.pptx>
내부 모델 수치는 qa_evidence_out.json(= qa_evidence_models.py 출력)에서 읽는다. 손으로 쓰지 않는다.
"""
import copy
import json
import statistics
import sys
from pathlib import Path

from lxml import etree
from pptx import Presentation
from pptx.dml.color import RGBColor
from pptx.enum.shapes import MSO_CONNECTOR, MSO_SHAPE
from pptx.enum.text import MSO_ANCHOR, PP_ALIGN
from pptx.oxml.ns import qn
from pptx.util import Emu, Inches, Pt

HERE = Path(__file__).parent
M = json.load(open(HERE / "qa_evidence_out.json"))
FONT = "맑은 고딕"
BLUE, ORANGE, GREEN, GRAY = "2E75B6", "C55A11", "548235", "7F7F7F"
CLS = {"lit": BLUE, "cond": ORANGE, "int": GREEN, "calc": GRAY}
STAR_FILL = ["FFFFFF", "FFF2CC", "FFF8E1", "DEEBF7", "EEF5FB", "E2F0D9"]


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
        el = etree.SubElement(rPr, qn(tag))
        el.set("typeface", FONT)


def add_runs(par, content, size, bold=False, color="000000"):
    """content: str | list[(text, {bold,color})]"""
    if isinstance(content, str):
        content = [(content, {})]
    for text, o in content:
        r = par.add_run()
        r.text = text
        set_font(r, size, o.get("bold", bold), o.get("color", color))


def textbox(slide, x, y, w, h, content, size=8, bold=False, color="000000", align=PP_ALIGN.LEFT,
            anchor=MSO_ANCHOR.TOP, wrap=True, name=None, fill=None):
    tb = slide.shapes.add_textbox(Inches(x), Inches(y), Inches(w), Inches(h))
    if name:
        tb.name = name
    if fill:
        tb.fill.solid()
        tb.fill.fore_color.rgb = rgb(fill)
    tf = tb.text_frame
    tf.word_wrap = wrap
    tf.margin_left = tf.margin_right = Inches(0.03)
    tf.margin_top = tf.margin_bottom = Inches(0.01)
    tf.vertical_anchor = anchor
    lines = content if isinstance(content, list) and content and isinstance(content[0], list) else [content]
    for i, ln in enumerate(lines):
        p = tf.paragraphs[0] if i == 0 else tf.add_paragraph()
        p.alignment = align
        add_runs(p, ln, size, bold, color)
    return tb


def rect(slide, x, y, w, h, fill, line=None, shape=MSO_SHAPE.RECTANGLE, line_w=0.75, dash=False):
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
        if dash:
            s.line.dash_style = 4
    else:
        s.line.fill.background()
    return s


def line(slide, x1, y1, x2, y2, color, w=0.75, dash=False):
    c = slide.shapes.add_connector(MSO_CONNECTOR.STRAIGHT, Inches(x1), Inches(y1), Inches(x2), Inches(y2))
    c.line.color.rgb = rgb(color)
    c.line.width = Pt(w)
    if dash:
        c.line.dash_style = 4
    return c


def set_cell(cell, content, size, bold=False, color="000000", fill=None, align=PP_ALIGN.LEFT, border="BFBFBF"):
    tf = cell.text_frame
    tf.word_wrap = True
    cell.margin_left = cell.margin_right = Inches(0.05)
    cell.margin_top = cell.margin_bottom = Inches(0.02)
    cell.vertical_anchor = MSO_ANCHOR.MIDDLE
    lines = content if isinstance(content, list) and content and isinstance(content[0], list) else [content]
    for i, ln in enumerate(lines):
        p = tf.paragraphs[0] if i == 0 else tf.add_paragraph()
        p.alignment = align
        add_runs(p, ln, size, bold, color)
    tcPr = cell._tc.get_or_add_tcPr()
    for tag in ("a:lnL", "a:lnR", "a:lnT", "a:lnB"):
        ln_ = etree.SubElement(tcPr, qn(tag))
        ln_.set("w", "6350")
        sf = etree.SubElement(ln_, qn("a:solidFill"))
        etree.SubElement(sf, qn("a:srgbClr")).set("val", border)
    if fill:
        sf = etree.SubElement(tcPr, qn("a:solidFill"))
        etree.SubElement(sf, qn("a:srgbClr")).set("val", fill)
    else:
        etree.SubElement(tcPr, qn("a:noFill"))


def table(slide, x, y, col_w, rows, row_h, size=8, header=True, fills=None, aligns=None, bold_cols=()):
    """rows: list[list[content]]; fills: dict[(r,c)]->hex or list per row"""
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
            set_cell(tbl.cell(r, c), rows[r][c], size, bold=is_h or c in bold_cols, fill=fill, align=al)
    return gf


# ---------------------------------------------------------------- chart
def chart(slide, spec, x_lab=6.85, x0=9.3, x1=12.45, y_top=1.86):
    """문헌/시뮬레이션 범위 도식 (원본 서식). spec: title, vmin, vmax, ticks, fmt, marks[(label,val)], rows[...]"""
    vmin, vmax = spec["vmin"], spec["vmax"]
    X = lambda v: x0 + (min(max(v, vmin), vmax) - vmin) / (vmax - vmin) * (x1 - x0)
    textbox(slide, x_lab, y_top, 6.25, 0.24, spec["title"], 10, True)
    # 별 기준 세로선 + 라벨(엇갈려 배치)
    n = len(spec["rows"])
    pitch = 0.178
    y_rows = y_top + 0.5
    y_axis = y_rows + n * pitch + 0.04
    for i, (lab, val) in enumerate(spec["marks"]):
        xv = X(val)
        ly = y_top + (0.25 if i % 2 == 0 else 0.38)
        textbox(slide, xv - 0.6, ly, 1.2, 0.17, lab, 8, True, "C00000", PP_ALIGN.CENTER)
        line(slide, xv, ly + 0.18, xv, y_axis, "C00000", 1.0, dash=True)
    # 축
    line(slide, x0 - 0.05, y_axis, x1 + 0.05, y_axis, GRAY, 0.75)
    for t in spec["ticks"]:
        xt = X(t)
        line(slide, xt, y_axis, xt, y_axis + 0.05, GRAY, 0.75)
        textbox(slide, xt - 0.3, y_axis + 0.04, 0.6, 0.17, spec["fmt"](t), 8, False, GRAY, PP_ALIGN.CENTER)
    # 행
    for i, r in enumerate(spec["rows"]):
        y = y_rows + i * pitch
        col = CLS[r["cls"]]
        textbox(slide, x_lab, y - 0.005, 2.45, 0.18, r["label"], 8, False, "404040", wrap=True)
        lo, hi = r["lo"], r.get("hi")
        if hi is None:
            xc = X(lo)
            o = rect(slide, xc - 0.06, y + 0.035, 0.12, 0.12, col, shape=MSO_SHAPE.OVAL)
            xe = xc + 0.12
        else:
            xa, xb = X(lo), X(hi)
            rect(slide, xa, y + 0.04, max(xb - xa, 0.05), 0.11, col)
            xe = xb + 0.04
        txt = r["text"]
        if r.get("clip"):
            textbox(slide, x1 - 0.02, y - 0.01, 0.25, 0.18, "▶", 8, False, col)
        tw = 0.075 * len(txt) + 0.12
        left_edge = (X(lo) if hi is None else X(lo))
        if xe + tw > 13.1 or r.get("text_left"):
            textbox(slide, left_edge - tw - 0.1, y - 0.005, tw, 0.18, txt, 8, True, col, PP_ALIGN.RIGHT, fill="FFFFFF")
        else:
            textbox(slide, xe, y - 0.005, tw, 0.18, txt, 8, True, col, fill="FFFFFF")
    # 범례
    ly = y_axis + 0.27
    xs = x_lab
    for key, lab, w in (("lit", "문헌·실측·실트래픽", 1.15), ("cond", "문헌·시뮬/조건부", 1.1),
                        ("int", "내부 모델·계수 [B+C]", 1.35), ("calc", "환산·원리·정책", 1.0)):
        rect(slide, xs, ly + 0.05, 0.12, 0.1, CLS[key])
        textbox(slide, xs + 0.15, ly, w, 0.18, lab, 8, False, "404040", wrap=False)
        xs += w + 0.3
    return ly + 0.22


# ---------------------------------------------------------------- slide frame
def clone_nav(dst, src_shapes):
    for sh in src_shapes:
        dst.shapes._spTree.append(copy.deepcopy(sh._element))


def build_slide(prs, layout, nav_shapes, qa):
    s = prs.slides.add_slide(layout)
    for ph in list(s.placeholders):
        if ph.placeholder_format.type is not None and ph.placeholder_format.idx != 0:
            ph._element.getparent().remove(ph._element)
    s.shapes.title.text = qa["title"]
    clone_nav(s, nav_shapes["nav"])
    # 질문 띠 + 칩 (원본 복제 후 텍스트 교체)
    for sh in nav_shapes["band"]:
        el = copy.deepcopy(sh._element)
        s.shapes._spTree.append(el)
    for sh in s.shapes:
        if sh.has_text_frame and sh.name == "TextBox 11":
            r = sh.text_frame.paragraphs[0].runs
            r[0].text = qa["question"]
            for extra in r[1:]:
                extra._r.getparent().remove(extra._r)
        if sh.has_text_frame and sh.name == "Rounded Rectangle 12":
            sh.text_frame.paragraphs[0].runs[0].text = qa["chip"]
    # 지표 설명 (최상단)
    rect(s, 0.27, 1.13, 12.83, 0.66, "F0F1F3", "BFBFBF", line_w=0.8)
    rect(s, 0.27, 1.13, 0.07, 0.66, "595959")
    textbox(s, 0.4, 1.15, 0.9, 0.62, "지표 설명", 10, True, "000000", anchor=MSO_ANCHOR.MIDDLE)
    textbox(s, 1.3, 1.14, 11.75, 0.64, qa["metric"], 8.5, False, "404040", anchor=MSO_ANCHOR.MIDDLE)
    # 좌상: 별 기준 표 (5구간 + 미충족)
    star_names = ["☆ 미충족", "★", "★½", "★★", "★★½", "★★★"]
    rows = [["별", qa["cond_head"], "근거"]]
    fills = {}
    for i, (cond, why) in enumerate(qa["stars"]):
        rows.append([star_names[i], cond, why])
        fills[(i + 1, 0)] = STAR_FILL[i]
        fills[(i + 1, 1)] = STAR_FILL[i]
    table(s, 0.27, 1.88, [0.72, 1.28, 4.4], rows, [0.24] + [0.32] * 6, 8, fills=fills,
          aligns=[PP_ALIGN.CENTER, PP_ALIGN.CENTER, PP_ALIGN.LEFT], bold_cols=(0, 1))
    # 좌하: 측정 시나리오 6 segment
    textbox(s, 0.27, 4.2, 6.4, 0.2, "품질 시나리오 측정 시나리오 (6 element)", 10, True)
    elems = ["자극원(Source)", "자극(Stimulus)", "대상(Artifact)", "환경(Environment)", "응답(Response)", "응답 측정(Measure)"]
    rows2 = [[e, qa["scenario"][i]] for i, e in enumerate(elems)]
    h2 = qa.get("scenario_h", [0.27] * 6)
    table(s, 0.27, 4.42, [1.2, 5.2], rows2, h2, 8, header=False,
          fills={(r, 0): "F2F2F2" for r in range(6)}, aligns=[PP_ALIGN.CENTER, PP_ALIGN.LEFT], bold_cols=(0,))
    # 우: 도식 + 표
    y_end = chart(s, qa["chart"])
    rows3 = [["구분", "문헌·출처", "지표·조건", "값", "별 반영"]] + [list(r[1:]) for r in qa["evidence"]]
    f3 = {}
    for i, r in enumerate(qa["evidence"]):
        f3[(i + 1, 0)] = "FFFFFF"
    t = table(s, 6.85, y_end + 0.02, [0.62, 1.45, 2.58, 0.75, 0.85], rows3,
              [0.24] + qa.get("ev_h", [0.3] * len(qa["evidence"])), 7.5,
              aligns=[PP_ALIGN.CENTER, PP_ALIGN.LEFT, PP_ALIGN.LEFT, PP_ALIGN.CENTER, PP_ALIGN.LEFT])
    # 구분 열 글자색
    for i, r in enumerate(qa["evidence"]):
        c = t.table.cell(i + 1, 0)
        for p in c.text_frame.paragraphs:
            for run in p.runs:
                run.font.color.rgb = rgb(CLS[r[0]])
                run.font.bold = True
    # 하단: 주의 / 출처 (파란 화살표 구간은 삭제)
    textbox(s, 0.27, 6.5, 12.83, 0.4, [[("주의  ", {"bold": True, "color": "C00000"}), (qa["note"], {})]], 8, False, "404040")
    textbox(s, 0.27, 6.93, 12.83, 0.28, qa["source"], 7.5, False, GRAY)
    textbox(s, 5.85, 7.2, 1.6, 0.24, f"{qa['page']} / 5", 10, False, GRAY, PP_ALIGN.CENTER)
    return s


# ---------------------------------------------------------------- data (내부 모델 값은 JSON에서)
q1 = [r for r in M["qa1"]]
q2 = M["qa2"]
valid = [i for i, r in enumerate(q1) if r["base"] >= 1.0 and r["R"] > 1.10]
R_valid = [q1[i]["R"] for i in valid]
e2e = [q2[i]["red"] * 100 for i in valid]
ttft = [q2[i]["red_ttft"] * 100 for i in valid]
n_sat = sum(1 for r in q1 if r["base"] >= 1.0 and r["R"] <= 1.10)
n_collapse = sum(1 for r in q1 if 0.06 < r["base"] < 1.0)
n_infeas = sum(1 for r in q1 if r["base"] <= 0.06)
assert len(valid) + n_sat + n_collapse + n_infeas == len(q1), (len(valid), n_sat, n_collapse, n_infeas)
collapse_R = [r["R"] for r in q1 if 0.06 < r["base"] < 1.0]
gm = lambda xs: (lambda p: p ** (1 / len(xs)))(__import__("math").prod(xs))
qa3 = {d["name"]: d["SE"] * 100 for d in M["qa3"]}
se_lo, se_hi = min(qa3.values()), max(qa3.values())
q4 = M["qa4"]
med = lambda k: statistics.median(v[k] for v in q4.values())
rng4 = lambda k: (min(v[k] for v in q4.values()), max(v[k] for v in q4.values()))
rt = M["qa5_roundtrip"]

fm_x = lambda v: f"{v:g}x"
fm_p = lambda v: f"{v:g}%"
fm_n = lambda v: f"{v:g}"

QA = []

# ============================ QA-01
QA.append(dict(
    page=1, chip="QA-01",
    title="QA-01. Performance (Throughput) - 별 기준과 근거",
    question="SLO를 만족하는 Max Goodput이 Baseline(HBM+DRAM 단순 offloading)의 몇 배일 때 ★ / ★★ / ★★★ 인가",
    metric="Max Goodput 배수 R = [SLO(TTFT ≤ 2 s, TPOT ≤ 50 ms)를 만족하며 처리 가능한 최대 요청량(req/s)]의 후보 ÷ Baseline. "
           "Baseline은 HBM-only가 아니라 HBM+DRAM 단순 offloading(LRU, 동기 로드)이다. 같은 HW·모델·workload에서 부하를 sweep해 SLO 위반 직전 "
           "요청률을 Goodput으로 보고, 시나리오×시스템 쌍별 R을 구해 기하평균으로 집계한다. 단위 x(배), 높을수록 좋음(↑).",
    cond_head="조건 (R = 후보 ÷ Baseline)",
    stars=[
        ("R < 1.5x", "시나리오 목표 미달. 같은 수요에 서버를 2/3로 줄이지 못함(1/1.5)"),
        ("R ≥ 1.5x", "시나리오 목표(하한). 서버 33% 절감 환산 [C]. 문헌 하한대: InferCept 1.6x, Mooncake 실트래픽 +75%"),
        ("R ≥ 1.75x", "★(1.5x)과 ★★(2x)의 중점. 서버 43% 절감 환산. Mooncake +75%, KVFlow 1.83x 구간"),
        ("R ≥ 2.0x", "서버 50% 절감. KVFlow 최대 2.19x(vs SGLang HiCache, DRAM offload 기반), InferCept 상단 2x"),
        ("R ≥ 2.5x", "★★(2x)과 ★★★(3x)의 중점. 서버 60% 절감. 문헌 실GPU 보고 2~3x 구간의 상단"),
        ("R ≥ 3.0x", "상한. 서버 67% 절감 환산. 실GPU 다중 턴 서빙 보고 상한(Pensieve 3.0x)"),
    ],
    scenario=[
        "다수의 agent 세션(동시 요청 클라이언트)",
        "multi-turn 요청 동시 도착: 활성 세션 수백~1,200개, Poisson 도착, 부하 sweep",
        "KV cache 서빙 경로(HBM·DRAM·확장 메모리의 배치·이동·재사용 계층), 후보 vs Baseline",
        "정상 운영, working set > HBM+DRAM 용량. 8×H100급 노드, 70B급 모델, 컨텍스트 16K~32K",
        "KV 재사용 hit는 재계산 없이 로드, SLO 안에서 더 많은 요청을 처리",
        "SLO(TTFT ≤ 2 s, TPOT ≤ 50 ms) 만족 Max Goodput ÷ Baseline ≥ 1.5x (★), ≥ 3x (★★★)",
    ],
    chart=dict(
        title="Goodput·처리량 개선 배수 R (Baseline 대비)", vmin=1, vmax=8, ticks=list(range(1, 9)), fmt=fm_x,
        marks=[("★ 1.5x", 1.5), ("★★ 2x", 2.0), ("★★★ 3x", 3.0)],
        rows=[
            dict(label="InferCept (2402.01869)", cls="lit", lo=1.6, hi=2.0, text="1.6~2x"),
            dict(label="Mooncake 실트래픽 (2407.00079)", cls="lit", lo=1.75, text="+75%"),
            dict(label="KVFlow (2507.07400)", cls="lit", lo=1.83, hi=2.19, text="1.83~2.19x"),
            dict(label="Pensieve (2312.05516)", cls="lit", lo=1.14, hi=3.0, text="1.14~3.0x"),
            dict(label="vLLM offload (HBM-only 대비)", cls="cond", lo=5.0, text="최대 5x"),
            dict(label="Mooncake 시뮬레이션", cls="cond", lo=6.25, text="+525% (6.25x)", text_left=True),
            dict(label="LMCache (2510.09665)", cls="cond", lo=2.3, hi=8, text="2.3~14x", clip=True, text_left=False),
            dict(label="내부 모델: 단순 offload 대비", cls="int", lo=min(R_valid), hi=max(R_valid), text=f"{min(R_valid):.2f}~{max(R_valid):.2f}x"),
        ]),
    evidence=[
        ("lit", "문헌", "InferCept\narXiv 2402.01869", "tool 호출(augmented LLM) 서빙, 최신 서빙 시스템 대비 처리량", "1.6~2x", "★ 하한 / ★★ 상단"),
        ("lit", "문헌", "Mooncake FAST'25\narXiv 2407.00079", "KVCache 중심 분리 서빙, SLO 하 실트래픽(Kimi) 요청 처리", "+75%", "★~★½"),
        ("lit", "문헌", "KVFlow\narXiv 2507.07400", "멀티에이전트 workflow prefix cache, SGLang(HiCache) 대비 최대", "1.83x / 2.19x", "★½~★★ 근거"),
        ("lit", "문헌", "Pensieve\narXiv 2312.05516", "다중 턴 stateful 서빙, vLLM·TensorRT-LLM 대비 처리량", "1.14~3.0x", "★★★ 상한"),
        ("cond", "조건부", "vLLM blog 2026-01, Mooncake 시뮬, LMCache", "HBM-only 대비 CPU offload 최대 5x(v0.12); 특정 trace·조건의 최대치", "5~14x", "상한 제외"),
        ("int", "내부 [C]", f"qa_evidence_models.py\n(5 seeds, 12 시나리오 중 유효 {len(valid)})",
         "단순 offload(HBM 400 GB+DRAM 1.5 TB) 대비 4-tier(+CXL 2 TB, SSD 8 TB)+prefetch 겹침 70%, Zipf α=0.8 재방문",
         " / ".join(f"{r:.2f}x" for r in R_valid), f"geomean {gm(R_valid):.2f}x\n★~★★ 구간"),
    ],
    ev_h=[0.28, 0.28, 0.28, 0.28, 0.3, 0.46],
    note=f"문헌 지표(처리량·요청 수·goodput)와 baseline·workload가 달라 직접 비교 불가 [문헌 인용]. 문헌 baseline은 대부분 HBM-only·단일 offload라 'HBM+DRAM 단순 offloading 대비'로 읽을 수 없고 "
         f"KVFlow(vs HiCache)가 가장 가깝다. 내부 모델은 12개 시나리오 중 비교유효 {len(valid)}건(포화 {n_sat}: R≈1.02~1.06 · Baseline 붕괴(<1 req/s) {n_collapse}: "
         f"R {min(collapse_R):.0f}~{max(collapse_R):.0f}x는 상한 제외 · Baseline infeasible {n_infeas}: 64K 컨텍스트 miss 재계산이 SLO 초과이거나 goodput 탐색 하한 0.05 req/s 도달)이며 단일 큐·고정 파라미터 모델이라 실측이 아니다. "
         "유효 판정 기준(Baseline ≥ 1 req/s, R > 1.10; ≤1.10은 동등 처리, seed 간 CI 미산출)은 1차 실행 결과를 본 뒤 fit-label 정의에 따라 적용했다.",
    source="출처: arXiv 2402.01869, 2407.00079(FAST'25), 2507.07400, 2312.05516, 2510.09665(LMCache, 검색 요약 기준·원문 미확인), vLLM blog 2026-01-08 'Inside vLLM's New KV Offloading Connector'(검색 요약 기준). "
           "내부: doc-mk/QA-criteria-v5/qa_evidence_models.py, qa_evidence_out.json",
))

# ============================ QA-02
QA.append(dict(
    page=2, chip="QA-02",
    title="QA-02. Performance (Tail Latency) - 별 기준과 근거",
    question="고부하 Elapsed Time(P99)을 Baseline 대비 몇 % 줄이면 ★ / ★★ / ★★★ 인가 (단, SLO 만족)",
    metric="P99 지연 감소율 r = 1 − P99(후보) ÷ P99(Baseline). Elapsed Time = 요청 도착부터 마지막 토큰 완료까지(큐 대기 + KV 로드/재계산 + decode). "
           "같은 부하(Baseline 한계 처리량의 70%)에서 비교하고 SLO(TTFT ≤ 2 s, TPOT ≤ 50 ms)를 못 지키면 미충족. Baseline은 QA-01과 같은 HBM+DRAM 단순 offloading. "
           "단위 %, 높을수록 좋음(↑). r은 속도 배수 1/(1−r)와 같다(30% → 1.43x, 50% → 2x, 67% → 3x).",
    cond_head="조건 (r = P99 감소율)",
    stars=[
        ("r < 30%", "체감 임계 미달. 시간 지각 JND(≈7~21%)에 가까워 사용자가 개선을 확신하기 어려움"),
        ("r ≥ 30%", "시나리오 목표(하한). JND 20% 안팎의 1.5배: '분명히 빨라졌다'고 느끼는 수준 [환산], 속도 1.43x"),
        ("r ≥ 40%", "★(30%)과 ★★(50%)의 중점. 속도 1.67x. 지연이 절반에 가까워지는 구간"),
        ("r ≥ 50%", "지연이 절반(2x faster)이라 인지 구분이 명확. vLLM offload의 TTFT ×2 하한과 일치"),
        ("r ≥ 58.5%", "★★(50%)과 ★★★(67%)의 중점. 속도 2.4x"),
        ("r ≥ 67%", "상한. 지연 1/3(3x). Nielsen 응답시간 한계(0.1/1/10 s, 10배 단위)의 반 단계(10^0.5≈3.2x)에 대응 [환산]"),
    ],
    scenario=[
        "다수의 agent 세션, 사용자(응답을 기다리는 클라이언트)",
        "고부하 요청 폭주: Baseline 한계 처리량의 70% 부하, working set > HBM+DRAM",
        "KV cache 서빙 경로(요청 큐 → KV 로드/재계산 → prefill → decode)",
        "정상 운영·고부하, SLO(TTFT ≤ 2 s, TPOT ≤ 50 ms) 충족 조건, 70B급 모델, 컨텍스트 16K~64K",
        "KV tier 이동·prefetch로 miss 재계산과 큐 대기를 줄여 최악 지연을 단축",
        "Elapsed Time P99 감소율 ≥ 30% vs Baseline (★), ≥ 67% (★★★), SLO 만족 시",
    ],
    chart=dict(
        title="Elapsed Time(P99) 감소율 r (Baseline 대비, %)", vmin=0, vmax=100, ticks=[0, 20, 40, 60, 80, 100], fmt=fm_p,
        marks=[("★ 30%", 30), ("★★ 50%", 50), ("★★★ 67%", 67)],
        rows=[
            dict(label="시간 지각 JND (Weber, 2차)", cls="lit", lo=7, hi=21, text="7~21%"),
            dict(label="vLLM offload TTFT ×2~22", cls="cond", lo=50, hi=95.5, text="50~95%", text_left=True),
            dict(label="서버 절감 환산 (QA-01 1.5~3x)", cls="calc", lo=33, hi=67, text="33~67%"),
            dict(label="Nielsen 10배 단위의 반 단계(3.2x)", cls="calc", lo=68.4, text="68%", text_left=False),
            dict(label="내부 모델: E2E P99 감소", cls="int", lo=min(e2e), hi=max(e2e), text=f"{min(e2e):.0f}~{max(e2e):.0f}%"),
            dict(label="내부 모델: TTFT P99 감소", cls="int", lo=min(ttft), hi=max(ttft), text=f"{min(ttft):.0f}~{max(ttft):.0f}%"),
        ]),
    evidence=[
        ("lit", "문헌", "Calibre 'perceived performance' 등", "시간 지각 Weber 분수: 1 s 규모 JND ≈ 0.17~0.21, 일부 자료는 7~18%", "7~21%", "★ 근거 (30% > JND)"),
        ("lit", "문헌", "NN/g 3 response-time limits", "응답시간 한계 0.1 / 1 / 10 s (Miller 1968, Nielsen 1993): 10배 단위", "10배 단위", "★★★ 환산 (3x≈반 단계)"),
        ("lit", "문헌", "web.dev 'Milliseconds make millions' (Deloitte×Google, 2020)", "모바일 0.1 s 속도 개선 → 리테일 전환율 +8.4% (37개 브랜드, 4주)", "+8.4% / 0.1 s", "지연 민감도 (도메인 상이)"),
        ("lit", "일화", "Linden(Amazon), Mayer(Google) 발표", "+100 ms → 판매 약 −1%, +0.5 s → 트래픽 −20% (1차 자료 미확인)", "−1% / −20%", "참고(일화)"),
        ("cond", "문헌", "vLLM blog 2026-01 (KV offloading connector)", "CPU offload로 TTFT ×2~×22↓ (HBM-only 대비, 프롬프트 길이 의존)", "50~95%", "★★ 하한 / 상한 참고"),
        ("int", "내부 [C]", f"QA-01과 같은 모델 (유효 {len(valid)}/12)", "Baseline 한계 처리량의 70% 부하, 5 seeds, E2E = TTFT + 128 tok × 25 ms",
         f"E2E {min(e2e):.0f}~{max(e2e):.0f}%\nTTFT {min(ttft):.0f}~{max(ttft):.0f}%", "E2E ☆ / TTFT ★~★★"),
    ],
    ev_h=[0.28, 0.28, 0.28, 0.28, 0.28, 0.42],
    note="체감은 과업 의존이다: arXiv 2604.06183(TTFT 2/9/20 s 실험)에서 2 s 응답이 9~20 s보다 '덜 사려 깊다'고 평가됐고 arXiv 2608.24189(배포 데이터)는 TTFT와 만족도의 유의한 상관을 못 찾았다(둘 다 검색 요약 기준) "
         "→ 30~67%는 '분명한 속도 개선'의 기준이지 만족도 보증이 아니다. JND 값은 2차 자료(1차 심리물리 논문 미확인). 내부 모델의 E2E 감소율은 후보와 무관한 decode 구간(3.2 s)이 분모를 키워 희석되며, "
         "TTFT 기준으로는 ★~★★ 구간이다. 이 차이는 ★ 판정 시 어떤 지연을 쓸지(E2E vs TTFT)를 평가 정의에서 고정해야 함을 뜻한다.",
    source="출처: calibreapp.com/blog/perceived-performance, nngroup.com(3 response time limits), web.dev/case-studies/milliseconds-make-millions, Linden·Mayer 발표(2차 인용), "
           "vLLM blog 2026-01-08(검색 요약 기준), arXiv 2604.06183, 2608.24189. 내부: doc-mk/QA-criteria-v5/qa_evidence_models.py",
))

# ============================ QA-03
usl = lambda se: (1 / se - 1) / 15 * 100
QA.append(dict(
    page=3, chip="QA-03",
    title="QA-03. Scalability - 별 기준과 근거",
    question="노드를 N배로 늘릴 때 처리량이 선형 대비 몇 % 유지되면 ★ / ★★ / ★★★ 인가",
    metric="Scaling Efficiency SE(N) = 처리량 증가 배율 ÷ 자원 증가 배율 = Goodput(N) ÷ ((N / N0) × Goodput(N0)), N0 = 2, N = 16(요청 도착률도 N에 비례해 증가). "
           "Goodput은 QA-01과 같이 SLO(TTFT ≤ 2 s, TPOT ≤ 50 ms)를 만족한 처리량. 단위 %, 높을수록 좋음(↑), 이론 상한 100%. "
           "N > 2 구간은 모델 외삽(시뮬레이션, 제약 C04)이며, 별은 보완 설계(샤딩 등) 적용 전 구성 기준이다.",
    cond_head="조건 (SE(N=16))",
    stars=[
        ("SE ≤ 80%", "증설 비용의 20% 이상이 조율 계층에서 손실. 시나리오 목표 미달"),
        ("SE > 80%", f"시나리오 목표(하한). 조율 직렬 비중 σ ≤ {usl(.8):.2f}%. 유효 12.8노드분. AthenaK 65,536 GPU 80%와 동급"),
        ("SE > 83.75%", f"★(80%)과 ★★(87.5%)의 중점. σ ≤ {usl(.8375):.2f}%. 유효 13.4노드분"),
        ("SE > 87.5%", f"★(80%)과 ★★★(95%)의 중점. σ ≤ {usl(.875):.2f}%. 유효 14.0노드분"),
        ("SE > 91.25%", f"★★(87.5%)과 ★★★(95%)의 중점. σ ≤ {usl(.9125):.2f}%. 유효 14.6노드분"),
        ("SE > 95%", f"상한. σ ≤ {usl(.95):.2f}%(조율 계층이 요청 처리의 0.35% 이하). MFC 95%, Athena++ 95~97% 보고와 동급"),
    ],
    scenario=[
        "운영자(자원 증설) / 서비스 사용자(부하 증가)",
        "노드 수를 2 → 4 → 8 → 16으로 증설하고 요청 도착률을 노드 수에 비례해 증가",
        "분산 KV 조율 계층(전역 router·metadata·공유 tier)과 노드별 서빙 경로",
        "정상 운영, N0 = 2 기준, 공유 tier 대역폭 고정, 요청 독립 replica 가정",
        "증설한 노드 수만큼 SLO 만족 처리량이 선형에 가깝게 증가",
        "SE(16) = Goodput(16) ÷ (8 × Goodput(2)) > 80% (★), > 95% (★★★)",
    ],
    chart=dict(
        title="Scaling Efficiency SE(N) (%)", vmin=50, vmax=100, ticks=[50, 60, 70, 80, 90, 100], fmt=fm_p,
        marks=[("★ 80%", 80), ("★★ 87.5%", 87.5), ("★★★ 95%", 95)],
        rows=[
            dict(label="AthenaK Perlmutter 4,096 GPU", cls="lit", lo=70, text="≈70%"),
            dict(label="AthenaK Frontier 65,536 GPU", cls="lit", lo=80, text="80%", text_left=True),
            dict(label="Athena++ 8→250 노드", cls="lit", lo=95, hi=97, text="95~97%", text_left=True),
            dict(label="MFC Frontier 65,536 GCD", cls="lit", lo=95, text="95%", text_left=True),
            dict(label="LLM 서빙 2→8 GPU", cls="lit", lo=100, text="≈100% (소규모)", text_left=True),
            dict(label="내부 모델: 중앙 router 20 ms/요청", cls="int", lo=qa3["노드 로컬 tier + 중앙 router 20 ms/요청"], text=f"{qa3['노드 로컬 tier + 중앙 router 20 ms/요청']:.0f}%", text_left=False),
            dict(label="내부 모델: 단일 공유 pool(16노드)", cls="int", lo=qa3["전 노드 단일 공유 pool (shard=16)"], text=f"{qa3['전 노드 단일 공유 pool (shard=16)']:.0f}%", text_left=False),
            dict(label="내부 모델: pool shard(4노드/pool)", cls="int", lo=qa3["pool shard 4노드당 1개"], text=f"{qa3['pool shard 4노드당 1개']:.0f}%", text_left=True),
        ]),
    evidence=[
        ("lit", "문헌", "AthenaK\narXiv 2409.16053", "Frontier 65,536 GPU weak scaling 80%, Perlmutter 4,096 GPU ≈70% (MHD 시뮬레이션 코드)", "80% / 70%", "★ 근거 (유추)"),
        ("lit", "문헌", "MFC arXiv 2509.13575\nAthena++ arXiv 2005.06651", "MFC Frontier 65,536 GCD weak 95%; Athena++ 8→250 노드 hydro 97% / MHD 95%", "95~97%", "★★★ 근거 (유추)"),
        ("lit", "문헌", "arXiv 2605.19775\nLLM-Pilot 2410.02425", "8B 모델 2→8 GPU 처리량 ≈4x; 13B A100 ≤8 pod 근사 선형", "≈100%", "소규모, 외삽 불가"),
        ("calc", "원리", "Amdahl(1967)\nGunther USL(2008)", f"SE(N)=1/(1+σ(N−1)). N=16에서 80% → σ {usl(.8):.2f}%, 95% → σ {usl(.95):.2f}%", "σ 환산", "별 경계 환산"),
        ("int", "내부 [C]", "공유 tier 구성 sweep (후보 비종속)", "16노드, 노드당 로컬 처리 0.2 s, remote hit 30%, KV 10.7 GB(32K), pool 200 GB/s, M/M/1형 지연 고정점",
         f"{se_lo:.0f}~{se_hi:.0f}%", "☆~★★★ 구성 의존"),
    ],
    ev_h=[0.3, 0.3, 0.3, 0.3, 0.44],
    note="HPC 값은 문제 크기를 노드 수에 비례시킨 weak scaling 병렬 효율이라 서빙 SE와 정의가 다르고 [유추], 서빙 문헌은 ≤ 8 GPU라 N=16 외삽 근거가 못 된다. "
         "이전 문서가 'AMD Frontier 65,536 GPU 학습'으로 적은 arXiv 2409.16053은 AthenaK(천체물리 MHD 코드) 논문이라 위처럼 바로잡았다. 95%는 HPC 보고의 상한대이며 서빙 시스템에 적용하는 것은 정책 선택이다. "
         "내부 모델은 파라미터를 사전 고정한 해석 모델이며(공유 pool을 쓰면 용량 공유 이득이 있으나 모델에 미반영), 노드 로컬 tier+전역 metadata 구성의 100%는 hit가 로컬에 한정된 경우다.",
    source="출처: arXiv 2409.16053(AthenaK), 2509.13575(MFC), 2005.06651(Athena++), 2605.19775, 2410.02425(LLM-Pilot)(모두 검색 요약 기준, 원문 미확인), Amdahl 1967, Gunther USL 2008. "
           "내부: doc-mk/QA-criteria-v5/qa_evidence_models.py",
))

# ============================ QA-04
QA.append(dict(
    page=4, chip="QA-04",
    title="QA-04. Modifiability - 별 기준과 근거",
    question="새 메모리·정책·데이터·이벤트 추가 1건의 변경 module이 몇 개 이하일 때 ★ / ★★ / ★★★ 인가",
    metric="변경 module 수 = 변경 시나리오 1건을 구현했을 때 수정·추가·삭제되는 module(소스 파일 단위, 테스트·문서 제외). 아래 변경 시나리오 S1~S5를 각각 구현해 세고 "
           "시나리오 평균으로 별을 판정한다. 단위 개(module), 낮을수록 좋음(↓). 서빙 경로(scheduler·worker)에 닿는 수정과 공개 interface 변경은 별도로 표기한다. "
           "현행 vLLM에서 같은 변경을 했을 때의 module 수를 Baseline으로 병기한다.",
    cond_head="조건 (변경 module 수)",
    stars=[
        ("≥ 7개", "오픈소스 commit 대부분(80%)이 6 file 이하라는 요구사항 기준을 벗어나는 변경"),
        ("≤ 6개", "시나리오 목표(하한). 요구사항 기준: 오픈소스 commit의 80%가 6 file 이하 [1차 출처 미확인]"),
        ("≤ 5개", "★(6)과 ★★(4)의 중점. Ferreira 2022: 대부분 commit이 1~10 file, 소스는 1~4 file"),
        ("≤ 4개", "★(6)과 ★★★(2)의 중점. 소스 file 1~4개 commit이 다수인 구간(Ferreira 2022)"),
        ("≤ 3개", "★★(4)과 ★★★(2)의 중점. 일상 변경 규모에 가까운 구간"),
        ("≤ 2개", "상한. SWE-bench 실제 issue 해결 패치의 평균 수정 1.7 file → 일상적 변경 한 건 규모"),
    ],
    scenario=[
        "제품 로드맵·운영 요구 → 개발자(또는 코드 에이전트)",
        "변경 S1 신규 메모리 tier(CXL → HBF/ScHBM) · S2 이동·배치 정책 교체(LRU → hotness 예측) · S3 신규 data type(LoRA·MoE expert·RAG 캐시를 tier 관리 대상에 추가) · S4 신규 이벤트(tool-call 종료 시 prefetch trigger) · S5 신규 KV 코덱(압축·양자화)",
        "서빙 경로의 메모리 계층 추상화(connector·manager·scheduler·worker)",
        "개발 시점. 현행 vLLM + 제안 구조에 구현, 기존 unit test 통과(회귀 없음)",
        "변경이 새 module 추가와 등록 지점 안에 머물고 서빙 경로 핵심 코드는 수정하지 않음",
        "변경 module 수(소스 file) 시나리오 평균 ≤ 6 (★), ≤ 2 (★★★). 공개 interface 변경 시 ☆",
    ],
    scenario_h=[0.25, 0.62, 0.25, 0.25, 0.25, 0.25],
    chart=dict(
        title="변경 module 수 (소스 file, 낮을수록 좋음)", vmin=0, vmax=10, ticks=[0, 2, 4, 6, 8, 10], fmt=fm_n,
        marks=[("★★★ ≤2", 2), ("★★ ≤4", 4), ("★ ≤6", 6)],
        rows=[
            dict(label="SWE-bench 패치 평균 (2310.06770)", cls="lit", lo=1.7, text="1.7"),
            dict(label="GitHub commit 소스 file (Ferreira 2022)", cls="lit", lo=1, hi=4, text="1~4 (다수 commit)"),
            dict(label="요구사항: commit 80% ≤ 6 file", cls="calc", lo=6, text="6", text_left=False),
            dict(label="vLLM backend 추가: 소스 file", cls="int", lo=rng4("src_only")[0], hi=rng4("src_only")[1], text=f"{rng4('src_only')[0]}~{rng4('src_only')[1]} (중앙 {med('src_only'):g})"),
            dict(label="vLLM backend 추가: 소스+문서·예제", cls="int", lo=rng4("non_test")[0], hi=rng4("non_test")[1], text=f"{rng4('non_test')[0]}~{rng4('non_test')[1]} (중앙 {med('non_test'):g})", text_left=False),
            dict(label="connector base interface 변경 파급", cls="int", lo=33, text="33 module", clip=True, text_left=True),
        ]),
    evidence=[
        ("lit", "문헌", "SWE-bench\narXiv 2310.06770", "실제 GitHub issue 해결 패치 2,294건: 평균 수정 파일 1.7개, 32.8줄", "1.7 file", "★★★ (≤ 2)"),
        ("lit", "문헌", "Ferreira 외, SBQS 2022 (GitHub commit)", "대부분 commit이 1~10 file, 소스 file은 1~4 (요약 기준)", "1~4 / 1~10", "★½~★★ 근거"),
        ("calc", "요구사항", "QAW 요구사항(품질 요구사항 표)", "오픈소스 commit의 80%가 6 file 이하 — 1차 출처 미확인", "6 file", "★ 하한"),
        ("int", "내부 계수", "이 저장소 grep: KV connector 5종 참조 file", f"backend 1개 추가에 닿는 file — 소스 {rng4('src_only')[0]}~{rng4('src_only')[1]}, +문서·예제 {rng4('non_test')[0]}~{rng4('non_test')[1]}, +테스트 {rng4('all')[0]}~{rng4('all')[1]}",
         f"중앙 {med('src_only'):g} / {med('non_test'):g} / {med('all'):g}", "As-Is ≈ ★~☆ 경계"),
        ("int", "내부 계수", "KVConnectorBase_V1 참조 module", "connector 공개 interface(base)를 바꿀 때 vllm/ 안에서 함께 영향받는 file 수", "33", "interface 변경 ☆"),
    ],
    ev_h=[0.28, 0.28, 0.28, 0.44, 0.34],
    note="변경 시나리오 S1~S5는 제안안이며, 선정 근거는 이 저장소에서 KV connector 구현이 FlexKV·LMCache·Mooncake·NIXL·hf3fs·moriio·P2P·offloading 등 8종 이상 누적됐다는 계수(S1이 가장 흔한 변경 유형)와 "
         "정책·data type·이벤트·코덱이 각각 독립적으로 바뀌는 축이라는 설계 가정이다. 계수는 '이 저장소에서 connector 이름을 참조하는 파일' 수로 변경량의 대리 지표일 뿐 실제 commit의 변경 file 수가 아니며, "
         "시나리오별 실제 구현·측정은 아직 하지 않았다(Evidence: 문헌 + 직접 계수, 구현 측정 미실시). Ferreira 2022와 요구사항의 80% 근거는 1차 출처 미확인.",
    source="출처: arXiv 2310.06770(SWE-bench), Ferreira 외 SBQS 2022(llp.dcc.ufmg.br, 검색 요약 기준), 품질 요구사항 표(QA-04). 내부: doc-mk/QA-criteria-v5/qa_evidence_out.json(qa4), "
           "grep 대상 vllm/·tests/·docs/·examples/ (doc-mk 제외)",
))

# ============================ QA-05
QA.append(dict(
    page=5, chip="QA-05",
    title="QA-05. Functional Correctness - 별 기준과 근거",
    question="LLM 출력 F1이 Baseline(full recompute) 대비 몇 % 이내로 유지되면 ★ / ★★ / ★★★ 인가",
    metric="F1 상대 하락률 = (F1_baseline − F1_후보) ÷ F1_baseline. Baseline = KV 압축·재사용 전 full recompute 경로. 같은 task·dataset·모델·precision·greedy decoding(temperature 0)에서 비교한다. "
           "압축 없이 이동·복원·재사용만 거치는 무손실 경로는 출력 bit-exact 확인(하락 0%)으로 갈음한다. 단위 %(상대), 낮을수록 좋음(↓).",
    cond_head="조건 (F1 상대 하락률)",
    stars=[
        ("하락 ≥ 1%", "시나리오 허용 한도(1%) 초과"),
        ("하락 < 1%", "시나리오 목표(하한). 소유자 허용 한도. 손실 압축 문헌의 'negligible' 구간과 같은 방향"),
        ("하락 < 0.775%", "★(1%)과 ★★(0.55%)의 중점"),
        ("하락 < 0.55%", "★(1%)과 ★★★(0.1%)의 중점"),
        ("하락 < 0.325%", "★★(0.55%)과 ★★★(0.1%)의 중점"),
        ("하락 < 0.1%", "상한 [정책]. 사실상 무손실. 비결정성 등 측정 잡음과 구분이 어려워 반복 측정·CI 필요"),
    ],
    scenario=[
        "서빙 엔진 운영자(KV 재사용·압축 경로 변경)",
        "KV cache를 tier 간 이동·복원·재사용(또는 압축)한 뒤 추론 요청 수행",
        "KV 변환·이동 경로(압축 코덱·재계산 경로), 추론 결과(task별 F1)",
        "동일 task·dataset·모델·precision, greedy decoding, 고정 seed, 정상 운영",
        "압축·재사용 경로를 거쳐도 추론 결과가 Baseline과 동등",
        "F1 상대 하락률 < 1% (★), < 0.1% (★★★). 무손실 경로는 bit-exact(0%)",
    ],
    chart=dict(
        title="F1 상대 하락률 (압축·재사용 전 full recompute 대비, %)", vmin=0, vmax=5, ticks=[0, 1, 2, 3, 4, 5], fmt=fm_p,
        marks=[("★★★ 0.1%", 0.1), ("★★ 0.55%", 0.55), ("★ 1%", 1.0)],
        rows=[
            dict(label="무손실 경로 (offload·전송·reuse)", cls="int", lo=0.0, text="0% (bit-exact)"),
            dict(label="소유자 허용 한도 (2026-10-09)", cls="calc", lo=1.0, text="1%"),
            dict(label="이전 ★ 기준 (v4)", cls="calc", lo=3.0, text="3%"),
            dict(label="KVmix 2-bit LongBench 평균", cls="lit", lo=4.53, text="4.53%", text_left=True),
        ]),
    evidence=[
        ("lit", "문헌", "KVQuant arXiv 2401.18079", "3-bit KV 양자화(outlier 1% 분리), perplexity 저하 < 0.1 (Wikitext-2, C4)", "ppl < 0.1", "F1 아님 (★★★ 방향 참고)"),
        ("lit", "문헌", "KVmix arXiv 2506.08018", "KV 2-bit급 혼합정밀도, LongBench 평균 상대 손실 4.53% (검색 요약, KVQuant 3-bit과 비슷)", "4.53%", "☆ (≥ 1%)"),
        ("lit", "vendor", "vLLM FP8 KV-cache blog (2026-04)", "FP8 KV는 검증 경로에서 near-baseline, 장문 accumulation 오류 수정 후 BF16 수준 회복", "정성", "★ 가능성"),
        ("lit", "문헌", "Thinking Machines Lab (2025-09)", "batch-invariant가 아닌 kernel은 같은 입력에도 출력이 변동", "정성", "★★★ 측정 잡음 유의"),
        ("calc", "정책", "소유자 결정 (2026-10-09)", "압축·재사용 전 + full recompute 대비 F1 1% 이내 허용", "1%", "★ 하한"),
        ("int", "내부 검증", "qa_evidence_models.py", f"tier 왕복 복사(직렬화→복원) 후 비트 비교: fp16 KV block {rt['blocks']:,}개(NaN·denormal 포함 임의 비트패턴)",
         f"불일치 {rt['mismatch']}", "무손실 경로 0%"),
    ],
    ev_h=[0.3, 0.3, 0.3, 0.28, 0.28, 0.3],
    note="문헌은 perplexity·정성 표현이라 F1으로 직접 환산할 수 없고 F1 하락의 일반 임계 문헌이 없어 1%는 소유자 한도, 0.1%는 정책이다. 이전(v4) 기준은 ★ 3% / ★★ 2% / ★★★ 1%였으므로 이번 기준은 3~10배 엄격하다. "
         "내부 검증은 무손실 경로의 복사 정확성(메모리 왕복)만 보이며 압축 경로의 F1은 측정하지 않았다. 0.1%는 반복 측정 잡음과 겹칠 수 있어 seed·prompt 반복의 신뢰구간으로 판정해야 한다.",
    source="출처: arXiv 2401.18079(KVQuant), 2506.08018(KVmix, 검색 요약 기준), vLLM blog 2026-04-22 'The State of FP8 KV-Cache...'(검색 요약 기준), Thinking Machines Lab 'Defeating Nondeterminism in LLM Inference'(2차 요약). "
           "내부: doc-mk/QA-criteria-v5/qa_evidence_models.py, 소유자 결정: doc-mk/Requirements/qa-star-criteria-evidence.md",
))


def main(src, dst):
    prs = Presentation(src)
    tmpl = prs.slides[1]
    layout = tmpl.slide_layout
    names = {sh.name: sh for sh in tmpl.shapes}
    nav = {"nav": [names[n] for n in ("Chevron 2", "Chevron 3", "Chevron 4", "Chevron 5", "Chevron 6", "Rectangle 7", "Rectangle 8")],
           "band": [names[n] for n in ("Rectangle 9", "Rectangle 10", "TextBox 11", "Rounded Rectangle 12")]}
    n_old = len(prs.slides)
    for qa in QA:
        build_slide(prs, layout, nav, qa)
    # 원본 5장 제거
    lst = prs.slides._sldIdLst
    for sldId in list(lst)[:n_old]:
        prs.part.drop_rel(sldId.rId)
        lst.remove(sldId)
    prs.save(dst)


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
