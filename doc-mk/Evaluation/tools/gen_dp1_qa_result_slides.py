#!/usr/bin/env python3
"""DP1 QA 결과 deck을 DP0 deck(doc-mk/DP0/DP0-qa-result-slides.pptx)과 같은 포맷으로 만든다.

포맷(DP0 deck에서 읽은 값): Blank layout, 맑은 고딕, 제목 22pt bold #2F5597, 부제 11pt #404040, 제목 아래 파란 선(#2F5597),
표 헤더 #2F5597 + 흰색 bold, 합계 행 #F2F2F2, 별 열 색(★★★ #E2F0D9 / ★★ #FFF2CC / ★ #FBE5D6), 아래 설명 상자(#F2F2F2, #FBE5D6, #FFFBEA),
출처 8.5pt, 마지막 줄 '※' 주석. 별 표기는 '★★☆'(3칸).
숫자는 모두 gen_dp1_result.py 가 읽는 데이터(코드 출력)에서 가져온다.

사용: /usr/local/bin/python3 doc-mk/Evaluation/tools/gen_dp1_qa_result_slides.py [--ref DP0 deck] [--out ...]
"""
import argparse
import copy
import math
import os
import sys
import unicodedata

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import gen_dp1_result as g
from lxml import etree
from pptx import Presentation
from pptx.util import Emu, Pt

HERE = os.path.dirname(os.path.abspath(__file__))
REF = os.path.normpath(os.path.join(HERE, "..", "..", "DP0", "DP0-qa-result-slides.pptx"))
OUT = os.path.normpath(os.path.join(HERE, "..", "..", "DP1", "DP1-qa-result-slides.pptx"))
A = "http://schemas.openxmlformats.org/drawingml/2006/main"
FONT = "맑은 고딕"
BLUE, GREY, TXT, RED = "2F5597", "404040", "000000", "C00000"
SW, SH = 12191695, 6858000
E = 914400
B, C1, C2 = g.B, g.C1, g.C2
PROBLEMS = []


def star(n):
    return "★" * n + "☆" * (3 - n)


def stars_n(s):
    return s.count("★")


# ------------------------------------------------------------------ 글자 폭 추정 (한글 전각, 영문 0.55)
def cw(ch, sz):
    if unicodedata.east_asian_width(ch) in ("W", "F"):
        return sz * 1.0
    if ch in "★☆":
        return sz * 1.0
    return sz * 0.55


def nlines(text, width_pt, sz):
    n = 0
    for para in text.split("\n"):
        cur = 0.0
        lines = 1
        for ch in para:
            w = cw(ch, sz)
            if cur + w > width_pt:
                lines += 1
                cur = w
            else:
                cur += w
        n += lines
    return n


def need_h(paras, width_emu, ins=(73152, 36576)):
    """paras: [(text, size_pt, bold, color)] 단락 리스트 -> 필요 높이(EMU)"""
    wpt = (width_emu - 2 * ins[0]) / 12700.0
    tot = 0.0
    for t, sz, *_ in paras:
        tot += nlines(t, wpt, sz) * sz * 1.2 + sz * 0.2
    return tot * 12700 + 2 * ins[1]


# ------------------------------------------------------------------ XML 빌더
def run(p, text, sz, bold=False, color=TXT):
    r = etree.SubElement(p, f"{{{A}}}r")
    rpr = etree.SubElement(r, f"{{{A}}}rPr", sz=str(int(sz * 100)), b="1" if bold else "0")
    sf = etree.SubElement(rpr, f"{{{A}}}solidFill")
    etree.SubElement(sf, f"{{{A}}}srgbClr", val=color)
    etree.SubElement(rpr, f"{{{A}}}latin", typeface=FONT)
    etree.SubElement(rpr, f"{{{A}}}ea", typeface=FONT)
    t = etree.SubElement(r, f"{{{A}}}t")
    t.text = text


def textbox(slide, x, y, w, h, paras, fill=None, algn="l", name=None, check=True):
    """paras: [[(text, sz, bold, color), ...], ...]  (단락 = run 리스트)"""
    tb = slide.shapes.add_textbox(Emu(x), Emu(y), Emu(w), Emu(h))
    if name:
        tb.name = name
    sp = tb._element
    spPr = sp.find("{http://schemas.openxmlformats.org/presentationml/2006/main}spPr")
    if fill:
        sf = etree.SubElement(spPr, f"{{{A}}}solidFill")
        etree.SubElement(sf, f"{{{A}}}srgbClr", val=fill)
    tx = sp.find("{http://schemas.openxmlformats.org/presentationml/2006/main}txBody")
    for ch in list(tx):
        tx.remove(ch)
    etree.SubElement(tx, f"{{{A}}}bodyPr", wrap="square", anchor="t", lIns="73152", rIns="73152", tIns="36576", bIns="36576")
    etree.SubElement(tx, f"{{{A}}}lstStyle")
    flat = []
    for runs in paras:
        p = etree.SubElement(tx, f"{{{A}}}p")
        ppr = etree.SubElement(p, f"{{{A}}}pPr", algn=algn)
        sa = etree.SubElement(ppr, f"{{{A}}}spcAft")
        etree.SubElement(sa, f"{{{A}}}spcPts", val="250")
        for (t, sz, b, c) in runs:
            run(p, t, sz, b, c)
        flat.append(("".join(t for t, *_ in runs), max(sz for _, sz, _, _ in runs)))
    if check:
        nh = need_h(flat, w)
        if nh > h + 6000:
            PROBLEMS.append(f"TEXT OVERFLOW {name or flat[0][0][:20]}: need {nh / E:.2f}in > {h / E:.2f}in")
    return tb


def table(slide, x, y, colw, rows, header=True, sz=9.5, aligns=None, bold_first=True, fills=None, rowh=None, name="tbl", total_row=False):
    """rows: [[text,...]] (헤더 포함). fills: {(r,c): hex}. 행 높이는 내용에 맞게 자동 산정."""
    nr, nc = len(rows), len(colw)
    aligns = aligns or ["l"] * nc
    heights = []
    for r, row in enumerate(rows):
        hmax = 0
        for c, t in enumerate(row):
            hmax = max(hmax, need_h([(str(t), sz, False)], colw[c], ins=(54864, 22860)))
        heights.append(max(int(hmax), int((rowh or 0.3) * E)))
    gf = slide.shapes.add_table(nr, nc, Emu(x), Emu(y), Emu(sum(colw)), Emu(sum(heights)))
    gf.name = name
    tbl = gf.table
    tblPr = tbl._tbl.find(f"{{{A}}}tblPr")
    for k in list(tblPr.attrib):
        del tblPr.attrib[k]
    tblPr.set("firstRow", "0")
    tblPr.set("bandRow", "0")
    for i, w in enumerate(colw):
        tbl.columns[i].width = Emu(w)
    for i, h in enumerate(heights):
        tbl.rows[i].height = Emu(h)
    fills = fills or {}
    for r, row in enumerate(rows):
        for c, t in enumerate(row):
            tc = tbl.cell(r, c)._tc
            txb = tc.find(f"{{{A}}}txBody")
            for ch in list(txb):
                txb.remove(ch)
            etree.SubElement(txb, f"{{{A}}}bodyPr", wrap="square")
            etree.SubElement(txb, f"{{{A}}}lstStyle")
            hdr = header and r == 0
            last = total_row and r == nr - 1
            for line in str(t).split("\n"):
                p = etree.SubElement(txb, f"{{{A}}}p")
                etree.SubElement(p, f"{{{A}}}pPr", algn="ctr" if hdr else aligns[c])
                run(p, line, sz, bold=hdr or (bold_first and c == 0) or (last and c == 0), color="FFFFFF" if hdr else TXT)
            old = tc.find(f"{{{A}}}tcPr")
            if old is not None:
                tc.remove(old)
            tcpr = etree.SubElement(tc, f"{{{A}}}tcPr", marL="54864", marR="54864", marT="22860", marB="22860", anchor="ctr")
            for side in ("lnL", "lnR", "lnT", "lnB"):
                ln = etree.SubElement(tcpr, f"{{{A}}}{side}", w="9525")
                sf = etree.SubElement(ln, f"{{{A}}}solidFill")
                etree.SubElement(sf, f"{{{A}}}srgbClr", val="BFBFBF")
            fc = BLUE if hdr else fills.get((r, c), "F2F2F2" if last else "FFFFFF")
            sf = etree.SubElement(tcpr, f"{{{A}}}solidFill")
            etree.SubElement(sf, f"{{{A}}}srgbClr", val=fc)
    return y + sum(heights)


def header(slide, title, sub):
    textbox(slide, 365760, 201168, 11430000, 457200, [[(title, 22, True, BLUE)]], name="title", check=False)
    textbox(slide, 365760, 676656, 11430000, 320040, [[(sub, 11, False, GREY)]], name="subtitle", check=False)
    rect = slide.shapes.add_shape(1, Emu(365760), Emu(1005840), Emu(11457432), Emu(27432))
    rect.name = "rule"
    st = rect._element.find("{http://schemas.openxmlformats.org/presentationml/2006/main}style")
    if st is not None:
        rect._element.remove(st)
    spPr = rect._element.find("{http://schemas.openxmlformats.org/presentationml/2006/main}spPr")
    sf = etree.SubElement(spPr, f"{{{A}}}solidFill")
    etree.SubElement(sf, f"{{{A}}}srgbClr", val=BLUE)
    ln = etree.SubElement(spPr, f"{{{A}}}ln")
    etree.SubElement(ln, f"{{{A}}}noFill")


def footer(slide, text, y=6473952 + 0):
    textbox(slide, 365760, 6473952, 11430000, 274320, [[(text, 8.5, False, GREY)]], name="footnote")


def new_slide(prs, title, sub, foot=None):
    s = prs.slides.add_slide(prs.slide_layouts[6] if len(prs.slide_layouts) > 6 else prs.slide_layouts[0])
    for ph in list(s.placeholders):
        ph._element.getparent().remove(ph._element)
    header(s, title, sub)
    if foot:
        footer(s, foot)
    return s


def W(*inches):
    return [int(i * E) for i in inches]


def bullets(title, items, tcolor=BLUE):
    paras = [[(title, 9.5, True, tcolor)]]
    for it in items:
        paras.append([("• " + it, 9, False, TXT)])
    return paras


# ================================================================== 데이터
o = g.overall_selection()
ST = o["stars"][g.MERGED]
G = g.RTM["sets"]["combined"]
pairs = g.valid_pairs([x for x, _ in g.SETS])
labs = [x for x, _ in g.SETS]
gmv = lambda c, f: g.gm_abs(pairs, c, f)
rt = lambda c, f: gmv(c, f) / gmv(B, f)
gp = lambda p: p["max_goodput_tps"]
t99, t50 = (lambda p: p["ttft_p99_ms"]), (lambda p: p["ttft_p50_ms"])
o99, o50 = (lambda p: p["tpot_p99_ms"]), (lambda p: p["tpot_p50_ms"])
hb = lambda p: p["tier_occ_gib"]["hbm"]
f0, f1 = (lambda v: f"{v:,.0f}"), (lambda v: f"{v:,.1f}")
m4 = g.QA4["mean_over_scenarios"]
Q4S = g.QA4_STARS
SUB4 = g.QA4["sub_stars"]
tot = o["totals"]
M6 = ("ttft_p50_ms", "ttft_p95_ms", "ttft_p99_ms", "tpot_p50_ms", "tpot_p95_ms", "tpot_p99_ms")


def qstar(v, lo, hi):
    return 1 if v < lo else (2 if v < hi else 3)


def cell(c, getter, fmt, s=None):
    return (f"{star(stars_n(s))}  " if s else "") + f"{fmt(gmv(c, getter))} (×{rt(c, getter):.2f})"


# 공통(CB-1~3)만 본 값 — 다른 DP와 같은 시나리오 집합
cpairs = g.valid_pairs(["common_benchmark"])
cgm = lambda c, f: g.gm_abs(cpairs, c, f)
crt = lambda c, f: cgm(c, f) / cgm(B, f)
cimp = lambda c: math.exp(sum(math.log(g.RM["common_benchmark"]["per_scenario"][k][B][m] / g.RM["common_benchmark"]["per_scenario"][k][c][m]) for lab, k in cpairs for m in M6) / (len(cpairs) * len(M6)))


# ================================================================== 슬라이드
def build(ref, out):
    prs = Presentation(ref)
    sld = prs.slides._sldIdLst
    for sldId in list(sld):
        prs.part.drop_rel(sldId.rId)
        sld.remove(sldId)

    # ---------------- 1. 결과
    s = new_slide(prs, "DP1 QA 평가 결과 — 정량 (H100 + B200 통합)",
                  "C1(Resource State-driven + Data-Memory Affinity) vs C2(Behavior-driven) · 공통 룰 §10 형식 · 괄호 = 후보 ÷ Baseline · 시뮬레이션 [B+C]",
                  "※ 별 경계는 DP1 별점 기준 v5(Baseline 대비 경계, qa-criteria-dp1.md). 경계 일부는 결과를 본 뒤 정했다(defined_after_first_look). 수치는 시뮬레이션이며 실측 전까지 근거로 쓰지 않는다.")
    rows = [["QA", "평가 metric (↑/↓ 좋음)", "Baseline", "C1 (Resource State-driven)", "C2 (Behavior-driven)"],
            ["QA1 처리량", "Max SLO goodput (tok/s) ↑", f0(gmv(B, gp)), cell(C1, gp, f0, ST[C1]["QA1"]) + " [B+C]", cell(C2, gp, f0, ST[C2]["QA1"]) + " [B+C]"],
            ["QA2 지연 (TTFT)", "TTFT P99 (ms) ↓", f0(gmv(B, t99)), cell(C1, t99, f0), cell(C2, t99, f0)],
            ["QA2 지연 (TPOT)", "TPOT P99 (ms) ↓", f1(gmv(B, o99)), cell(C1, o99, f1), cell(C2, o99, f1)],
            ["QA2 별점", "TTFT·TPOT × P50/P95/P99 6개 개선 배수 geomean", "×1.00",
             f"{star(stars_n(ST[C1]['QA2']))}  ×{G[C1]['qa2']['latency_improvement_geomean']:.2f} [B+C]", f"{star(stars_n(ST[C2]['QA2']))}  ×{G[C2]['qa2']['latency_improvement_geomean']:.2f} [B+C]"],
            ["QA3 자원 (HBM)", "HBM 사용량 (GiB, 시간 평균) ↓", f1(gmv(B, hb)), cell(C1, hb, f1, ST[C1]["QA3"]) + " [B+C]", cell(C2, hb, f1, ST[C2]["QA3"]) + " [B+C]"],
            ["QA4 ① module", "변경 module 수 (4 시나리오 평균) ↓", "—", f"{star(stars_n(SUB4['C1']['M1']))}  {m4['C1']['modules']:.2f}", f"{star(stars_n(SUB4['C2']['M1']))}  {m4['C2']['modules']:.2f}"],
            ["QA4 ② 공수", "개발 공수 (man-month) ↓", "—", f"{star(stars_n(SUB4['C1']['M2']))}  {m4['C1']['man_months']:.2f}", f"{star(stars_n(SUB4['C2']['M2']))}  {m4['C2']['man_months']:.2f}"],
            ["QA4 ③ 비용", "에이전트 비용 $ (frontier tier) ↓", "—", f"{star(stars_n(SUB4['C1']['M3']))}  ${m4['C1']['usd_T1']:.2f}", f"{star(stars_n(SUB4['C2']['M3']))}  ${m4['C2']['usd_T1']:.2f}"],
            ["QA4 별점", "세 sub-star의 중앙값 [B+C]", "—", f"{star(stars_n(Q4S[C1]))}", f"{star(stars_n(Q4S[C2]))}"],
            ["별 합계", "QA1 + QA2 + QA3 + QA4", "—", f"{'+'.join(str(stars_n(ST[C1][k])) for k in ('QA1','QA2','QA3','QA4'))} = {tot[C1]}", f"{'+'.join(str(stars_n(ST[C2][k])) for k in ('QA1','QA2','QA3','QA4'))} = {tot[C2]}"]]
    y = table(s, 365760, 1170432, W(1.5, 3.55, 1.05, 3.2, 3.23), rows, sz=10, aligns=["l", "l", "ctr", "ctr", "ctr"], total_row=True, rowh=0.3)
    textbox(s, 365760, y + 70000, 11430000, 460000, [[("근거 수준 표기: ", 9, True, TXT),
            ("[B] 공개 spec · [C] 모델/시뮬레이션. DP1은 실측 Baseline이 없어 모든 값이 [B+C]다. 평가 시스템: SYS-H100, SYS-B200 (각 8-GPU 1노드), Llama-3.1-70B BF16, 입력 8K / 출력 256, "
             f"SLO = TTFT P99 ≤ 2 s · TPOT P99 ≤ 50 ms. 집계 = 시나리오 × 시스템 쌍 {len(pairs)}쌍(비교 가능, 64쌍 중)의 기하평균.", 9, False, TXT)]], fill="F2F2F2", name="evidence")
    y2 = y + 70000 + 460000 + 90000
    textbox(s, 365760, y2, 6100000, 6420000 - y2, bullets("선택 (별 합계 → 동점이면 QA 우선순위 QA1>QA2>QA3>QA4)", [
        f"합계 C1 {tot[C1]} 대 C2 {tot[C2]} → {'C1' if o['winner'] == C1 else 'C2'} 선택 (합계 차이 {abs(tot[C1] - tot[C2])}점).",
        "C2는 처리량(QA1)·지연 값이 높고, C1은 HBM 사용(QA3)·변경 비용(QA4)이 낫다.",
        "선택이 근소하고 별 경계에 민감하다(오른쪽)."]), fill="FBE5D6", name="selection")
    textbox(s, 6580000, y2, 5215000, 6420000 - y2, bullets("읽을 때 주의", [
        f"QA1 C1 ×{rt(C1, gp):.3f}은 ★★★ 경계 1.30 바로 아래(0.2%). 경계를 1.25로 두면 합계가 달라지고, 1.30~1.40이면 동점(QA1 우선순위로 C2).",
        f"C1의 TTFT P99는 Baseline보다 나쁘다(×{rt(C1, t99):.2f}). P50은 좋아지는데 꼬리가 나빠진다(이동이 링크를 점유).",
        "평가는 mapping·commit·driver overhead를 0으로 가정한다(조건부 값).",
    ], tcolor=RED), fill="FFFBEA", name="caution")

    # ---------------- 2. 공통 시나리오만 (정합)
    s = new_slide(prs, "공통 시나리오(CB-1~3)만 본 값 — 다른 DP와 같은 시나리오·같은 형식",
                  f"공통 벤치마크 3개 × 2시스템 = 6쌍 중 비교 가능 {len(cpairs)}쌍 · 같은 QA의 같은 시나리오를 DP 간 비교할 수 있게 별도 표기 · 괄호 = 후보 ÷ Baseline",
                  "※ 공통 별점은 공통 시나리오에서만 산출한다(common-benchmark.md §7). DP1의 공식 별(1장)은 Common+Stress+Dynamic 21쌍 기준이며(소유자 결정, H11), 이 장의 별은 공통 6쌍 기준의 참고값이다.")
    c1g, c2g = crt(C1, gp), crt(C2, gp)
    sv = lambda c: 1.0 / crt(c, hb)
    rows = [["QA", "평가 metric (↑/↓ 좋음)", "Baseline", "C1", "C2"],
            ["QA1 처리량", "Max SLO goodput (tok/s) ↑", f0(cgm(B, gp)), f"{star(qstar(c1g, 0.97, 1.30))}  {f0(cgm(C1, gp))} (×{c1g:.2f})", f"{star(qstar(c2g, 0.97, 1.30))}  {f0(cgm(C2, gp))} (×{c2g:.2f})"],
            ["QA2 지연 (TTFT)", "TTFT P99 (ms) ↓", f0(cgm(B, t99)), f"{f0(cgm(C1, t99))} (×{crt(C1, t99):.2f})", f"{f0(cgm(C2, t99))} (×{crt(C2, t99):.2f})"],
            ["QA2 지연 (TPOT)", "TPOT P99 (ms) ↓", f1(cgm(B, o99)), f"{f1(cgm(C1, o99))} (×{crt(C1, o99):.2f})", f"{f1(cgm(C2, o99))} (×{crt(C2, o99):.2f})"],
            ["QA2 별점", "6개 지표 개선 배수 geomean", "×1.00", f"{star(qstar(cimp(C1), 0.95, 1.25))}  ×{cimp(C1):.2f}", f"{star(qstar(cimp(C2), 0.95, 1.25))}  ×{cimp(C2):.2f}"],
            ["QA3 자원 (HBM)", "HBM 사용량 (GiB) ↓", f1(cgm(B, hb)), f"{star(qstar(sv(C1), 0.95, 1.25))}  {f1(cgm(C1, hb))} (×{crt(C1, hb):.2f})", f"{star(qstar(sv(C2), 0.95, 1.25))}  {f1(cgm(C2, hb))} (×{crt(C2, hb):.2f})"]]
    y = table(s, 365760, 1170432, W(1.5, 3.55, 1.05, 3.2, 3.23), rows, sz=10, aligns=["l", "l", "ctr", "ctr", "ctr"], rowh=0.3)
    # 쌍별
    prow = [["시나리오", "시스템", "fit", "Baseline goodput", "C1 goodput (×)", "C2 goodput (×)", "TTFT P99 C1 (×)", "TTFT P99 C2 (×)"]]
    lab_fit = {}
    for sid in g.SYSIDS:
        d = g.json.load(open(g.DATA / sid / "qa_result.json"))["common_benchmark"]
        for k, f in d["fit"].items():
            ps = d["per_scenario"][k]
            lab_fit[(k, sid)] = f
            if f == "comparison_valid":
                bb, a, b2 = ps[B], ps[C1], ps[C2]
                prow.append([{"cb_kv_8k_b32": "CB-1  cb_kv_8k_b32", "cb_kv_8k_b32_ramp": "CB-2  cb_kv_8k_b32_ramp", "cb_mixed_8k_b32": "CB-3  cb_mixed_8k_b32"}[k], sid[4:], "비교 가능", f0(bb["max_goodput_tps"]),
                             f"{f0(a['max_goodput_tps'])} (×{a['max_goodput_tps'] / bb['max_goodput_tps']:.2f})", f"{f0(b2['max_goodput_tps'])} (×{b2['max_goodput_tps'] / bb['max_goodput_tps']:.2f})",
                             f"×{a['ttft_p99_ms'] / bb['ttft_p99_ms']:.2f}", f"×{b2['ttft_p99_ms'] / bb['ttft_p99_ms']:.2f}"])
            else:
                prow.append([{"cb_kv_8k_b32": "CB-1  cb_kv_8k_b32", "cb_kv_8k_b32_ramp": "CB-2  cb_kv_8k_b32_ramp", "cb_mixed_8k_b32": "CB-3  cb_mixed_8k_b32"}[k], sid[4:], {"saturated": "포화(제외)", "infeasible": "Baseline 불가"}[f], "—", "—", "—", "—", "—"])
    order = {"CB-1": 0, "CB-2": 1, "CB-3": 2}
    prow = [prow[0]] + sorted(prow[1:], key=lambda r: (order[r[0][:4]], r[1]))
    y = table(s, 365760, y + 120000, W(2.3, 0.8, 1.2, 1.5, 1.8, 1.8, 1.55, 1.58), prow, sz=9, aligns=["l", "ctr", "ctr", "ctr", "ctr", "ctr", "ctr", "ctr"], rowh=0.27)
    textbox(s, 365760, y + 90000, 11430000, 6400000 - y - 90000, bullets("읽는 법", [
        "공통 3개 시나리오는 Baseline이 이미 SLO를 지키고 처리량이 포화에 가까워 후보의 QA1 이득이 거의 없다(×1.00). 이득은 DP1 전용 Dynamic 시나리오에서 나온다(1장).",
        f"공통에서 C1은 지연 쪽이 나쁘다: TTFT P99 ×{crt(C1, t99):.2f}, QA2 개선 배수 ×{cimp(C1):.2f}(★ 경계 0.95 아래). C2는 TTFT P99가 Baseline과 같은 수준이다.",
        "CB-3(B200)은 모든 후보가 CI 이내로 같아 '포화'로 집계에서 제외했다(삭제하지 않고 목록에 남김).",
        "DP4는 공통 6쌍으로 별을 매기고 DP2는 전체 쌍으로 매겨 DP마다 집합이 다르다. 이 장은 DP1의 공통 값을 같은 형식으로 내어 비교 근거로 쓴다(12장 정합 점검)."]), fill="F2F2F2", name="read")

    # ---------------- 3. 평가 대상 구조
    s = new_slide(prs, "평가 대상 구조 C1 · C2",
                  "같은 이벤트·Selector 경계·Migration budget 위에서 '무엇을 보고 이동을 결정하나'만 다른 두 후보 · 결정은 DP1, mapping·commit은 공통 Migration subsystem",
                  "※ 정의는 dp1-ai-data-migration-decision-architecture.md §4~5, 구현은 DP1/sim/policies.py. 블록 이름은 설계 문서 용어. 변경 시나리오 S1~S4는 QA4(qa-criteria-dp1.md).")
    rows = [["ID", "이름", "쉬운 설명", "입력 → 출력", "블록", "C1 구현", "C2 구현", "변경 시나리오"],
            ["K1", "Event · Migration Scheduler", "용량 압박·접근·할당 같은 사건이 오면 이동 판단을 시작", "telemetry · ALLOCATED/FREED/ACCESSED → 결정 주기", "공통", "동일", "동일", "S4 새 event"],
            ["K2", "Data Object Registry", "객체의 위치·크기·tier를 적어 두는 장부", "객체 id → 위치·크기·tier", "공통(스키마 다름)", "type-agnostic (종류를 모름)", "type-aware (KV/LoRA/MoE/RAG별 특성)", "S2 새 data 종류"],
            ["K3", "관찰", "무엇을 보고 상황을 파악하나", "tier 상태 / 접근 이력 → 상태 값", "후보별", "Resource State Monitor (용량·BW·부하)", "Data Behavior Monitor (빈도·재사용·유휴)", "S4"],
            ["K4", "판단", "지금 이동이 필요한가, 무엇이 유리한가", "상태 값 → 압력 · 선호", "후보별", "Trend Analyzer + Data-Memory Affinity(정적 힌트)", "Trend Analyzer + Future Behavior Predictor", "S3 정책 교체"],
            ["K5", "Destination Tier Selector", "어느 tier로 보낼지 고른다", "후보 tier 목록 → 목적지", "공통 비용 추정 + 후보별", "affinity 점수 − 서빙 penalty, SLO 필터", "type 선호 목록 + benefit-vs-cost gating", "S1 새 메모리"],
            ["K6", "Eviction · 승격", "누구를 내리고 누구를 올릴지", "압력 · 후보 → 이동 대상", "후보별", "Eviction Manager + 정적 승격/교환 pass", "coldest-first 강등(압력 시) + 예측 승격", "S3"],
            ["K7", "Migration Budget · Executor 경계", "이동이 서빙 링크를 너무 쓰지 않게 제한하고 결정을 넘긴다", "이동 결정 → MigrationIntent", "공통", "link 시간 token bucket (몫 0.25, cooldown 8 s)", "동일", "—"]]
    y = table(s, 365760, 1290000, W(0.45, 1.55, 2.0, 1.85, 0.95, 2.1, 2.2, 1.43), rows, sz=8.5, aligns=["ctr", "l", "l", "l", "ctr", "l", "l", "l"], rowh=0.3)
    textbox(s, 365760, y + 110000, 6150000, 6400000 - y - 110000, bullets("읽는 법", [
        "K1·K7과 Memory Backend I/F는 두 후보 공통이고 K2~K6이 갈린다. 그래서 C1/C2는 같은 Policy 틀의 두 구현으로 볼 수 있다.",
        "C1은 '메모리 상태가 어떻게 변하나'를, C2는 '데이터가 앞으로 어떻게 쓰이나'를 본다. 같은 종류 안의 hot/cold 구분은 C2만 한다.",
        "C1의 Data-Memory Affinity 효과는 정적 승격 pass에서 나온다(제거 실험: 처리량 ×1.30 → ×1.05)."]), fill="F2F2F2", name="r1")
    textbox(s, 6640000, y + 110000, 5155000, 6400000 - y - 110000, bullets("범위 주의", [
        "DP1은 결정(WHAT/WHERE)까지다. location 변경과 commit, 전송, HW 주소 변환은 공통 Migration subsystem과 driver의 영역이다(dp1-constraints.md C-X6, 6절).",
        "평가는 그 구간의 overhead를 0으로 가정한다. 구현 후 실측이 필요하다."], tcolor=RED), fill="FFFBEA", name="r2")

    # ---------------- 4. 평가 시나리오
    s = new_slide(prs, "평가 시나리오",
                  "공통 벤치마크 CB-1~3을 기본으로 하고 DP1 전용 시나리오를 더한다 · 시나리오당 한 줄 · 시스템 2개(H100, B200)에 각각 실행",
                  "※ 시나리오 정의는 평가 계획이며 결과가 아니다. 파라미터는 사전 등록 값이고 결과를 본 뒤 바꾸지 않는다. 정의 원천: common-benchmark.md 2.1, DP1/benchmark.md, DP1/sim/scenarios.py.")
    fc = {"comparison_valid": 0, "saturated": 0, "infeasible": 0}
    for sid in g.SYSIDS:
        for lab, _ in g.SETS:
            for k, f in g.json.load(open(g.DATA / sid / "qa_result.json"))[lab]["fit"].items():
                fc[f] += 1
    rows = [["ID", "시나리오", "무엇인가", "대상 QA", "드러내는 차이 (As-Is 약점)", "핵심 파라미터"],
            ["CB-1", "cb_kv_8k_b32 (공통)", "KV만, 정상 상태, HBM 용량 압박 고정", "QA1 QA2 QA3", "정적 배치가 fast tier 초과분을 느린 tier로 흘릴 때의 TPOT 악화", "8K/256, batch 32, 40 objs, HBM ×0.12"],
            ["CB-2", "cb_kv_8k_b32_ramp (공통)", "CB-1과 같은 KV, 압박이 시간에 따라 점진 증가", "QA1 QA2 QA3", "시간에 따라 필요한 배치가 바뀌는데 정적 배치가 따라가지 못함", "HBM ×0.2, capacity_ramp"],
            ["CB-3", "cb_mixed_8k_b32 (공통)", "KV + LoRA + MoE + Agent/Tool 혼합", "QA1 QA2 QA3", "data 종류를 구분하지 않는 관리의 한계", "KV 50/LoRA 15/MoE 15/Agent 10/Tool 10 %, 48 objs"],
            ["ST (23)", "DP1 Stress", "데이터 종류(KV, RAG, Agent, Tool, LoRA, MoE)·크기(32K~512K, 1~8 TiB)·압박 양상을 바꾼 시나리오", "QA1 QA2 QA3", "tier 선택과 용량 사다리(6개 메모리 전부), 공유 링크 압박, hotness 급반전", "예: rag_1tib_b16, kv_b256_c512k_stress, behavior_flip_stress"],
            ["DY (6)", "DP1 Dynamic", "Baseline이 처음엔 SLO를 만족하다 중간에 고정 규칙이 stale해지는 6개", "QA1 QA2 QA3", "hot 집합이 이동·idle 점유·링크 저하 (Baseline의 실패 양상을 알고 설계함)", "dyn_kv_rotating_hotset, dyn_idle_kv_holds_hbm, dyn_rag_shard_hotset_shift 등"],
            ["S1~S4", "변경 시나리오 4개", "새 메모리 추가 · 새 AI data 종류 · 정책 교체 · 새 event", "QA4", "변경이 어디까지 번지는가 (module · 공수 · 에이전트 비용)", "시뮬레이터 복사본에 구현해 측정, 가중 없음(평균)"]]
    y = table(s, 365760, 1300000, W(0.75, 1.85, 3.2, 0.95, 3.2, 2.58), rows, sz=9, aligns=["ctr", "l", "l", "ctr", "l", "l"], rowh=0.3)
    textbox(s, 365760, y + 110000, 11430000, 6400000 - y - 110000, bullets("읽는 법", [
        f"32개 시나리오 × 2시스템 = 64쌍 중 비교 가능 {fc['comparison_valid']}쌍, 포화 {fc['saturated']}쌍(모든 후보가 CI 이내로 같음), Baseline도 SLO 불가 {fc['infeasible']}쌍. 불가·포화 쌍은 집계에서 빼되 목록에는 남겼다.",
        "공통 CB-1~3은 다른 DP와 같은 ID·파라미터다(common-benchmark.md). 그 외는 DP1 전용이며 후보가 지는 시나리오도 삭제하지 않았다.",
        "Dynamic은 failure mode를 알고 설계했으므로 이득은 그 상황에 한정해 읽어야 한다(시스템·시나리오 선택 의존)."]), fill="F2F2F2", name="r")

    # ---------------- 5. 시뮬레이션 수행 방식
    s = new_slide(prs, "시뮬레이션 수행 방식 — 시뮬레이터 단독 (실측 Baseline 없음)",
                  "DP1은 실물 이기종 메모리(ScHBM, CXL-PNM, HBF, SSD-PIM)가 없어 Baseline까지 시뮬레이터로 돌린다: 모든 값이 [B+C]",
                  "※ 이 장은 평가 절차다. 시뮬레이터(DP1/sim)와 결과 데이터(DP1/results/data)는 같은 명령·같은 revision이면 같은 값이 나온다(seed 11/23/37/53/71).")
    steps = [("① 시스템 모델 구성 [B]", "H100×8 / B200×8 프로필(공개 spec) + 6종 메모리의 용량·대역폭·지연·primitive·연산 능력(`systems.json`, SPEC/PUBLIC/ASSUMED 표기). 공통 프로필 Llama-3.1-70B BF16."),
             ("② 시나리오 trace 생성", "CB-1~3 + Stress 23 + Dynamic 6의 객체·접근률·압박을 seed별로 생성. Baseline과 후보가 같은 trace를 받는다."),
             ("③ 정책 주입", "Baseline-static(최초 배치 고정, 이동 없음) / C1 / C2를 같은 시뮬레이터에서 실행. 이동 비용은 링크 간섭 모델(이동이 쓴 링크 시간만큼 서빙 BW 감소)로 지연·처리량에 반영."),
             ("④ 시나리오 실행", "load ×0.5/1.0/1.5/2.0 sweep × seed 5개. Max SLO goodput은 SLO를 만족한 토큰의 최대값. 같은 seed·부하로 Baseline과 짝지어 비교(95% CI)."),
             ("⑤ 후처리", "QA1 비율, QA2 6개 지표 개선 배수, QA3 HBM 점유, QA4는 변경 시나리오를 시뮬레이터 복사본에 구현해 module·LOC를 측정하고 공수·비용은 가정 상수로 계산.")]
    y = 1290000
    for a, b_ in steps:
        textbox(s, 365760, y, 2560000, 520000, [[(a, 10, True, BLUE)]], fill="F2F2F2", name=a[:4])
        textbox(s, 3000000, y, 8795000, 520000, [[(b_, 9.5, False, TXT)]], name="d" + a[:2])
        y += 570000
    rows = [["값", "출처", "Evidence"],
            ["GPU·호스트 spec, 모델·워크로드", "공개 spec + 공통 프로필", "[B]"],
            ["ScHBM·HBF·SSD-PIM·CXL-PNM 성능, 연산 능력", "문헌·vendor spec을 입력으로 한 모델 (CXL-PNM 연산 3.28 TFLOPS는 ASSUMED)", "[B+C]"],
            ["이동 비용(링크 간섭), decision overhead", "모델 (mapping·commit·driver overhead는 0으로 가정)", "[C]"],
            ["QA4 공수·에이전트 비용", "시뮬레이터 복사본 구현 측정 + 가정 상수·가격(ASSUMED)", "[B+C]"],
            ["실측 Baseline", "없음 (DP0는 H100 실측 Baseline이 있어 [A+C])", "—"]]
    table(s, 365760, y + 20000, W(4.2, 7.1, 1.2), rows, sz=9, aligns=["l", "l", "ctr"], rowh=0.27)

    # ---------------- 6. 시스템과 SLO
    s = new_slide(prs, "평가 시스템과 SLO",
                  "TTFT P99 ≤ 2 s · TPOT P99 ≤ 50 ms는 공통 문서의 고정값이며 DP0·DP2·DP4와 같다 · 시스템은 메모리 세대 두 개(H100, B200)를 통합",
                  "※ SYS 값은 SPEC/PUBLIC/ASSUMED를 필드별로 표기(system-specs.md). 확인하지 못한 값은 ASSUMED로 두었다. B200·ScHBM 값은 세대 스케일 가정을 포함한다.")
    mem = g.memory_line().split("; ")
    rows = [["항목", "값", "상태"],
            ["노드 / GPU", "8-GPU 1노드 × 2시스템: SYS-H100 (H100 SXM5 80GB HBM3), SYS-B200 (HBM3e)", "공개 spec [B]"],
            ["GPU 연산", "FP16 dense 989 TFLOPS (H100) / 2,250 TFLOPS (B200), GPU 1개당", "공개 spec [B]"],
            ["모델 / 정밀도", "Llama-3.1-70B, BF16, 8-GPU 1노드", "공통 프로필"],
            ["워크로드", "입력 8K / 출력 256, prefix 재사용 통제 (공통 CB), DP1 전용은 5장 시나리오", "공통 프로필"],
            ["호스트 연결 / DRAM", "PCIe 5.0 x16, DDR5-4800 (H100) / DDR5-6400 (B200), 1 TiB", "PUBLIC [B]"]]
    rows += [["메모리 구성", m, "SPEC/PUBLIC/ASSUMED"] if i == 0 else ["", m, ""] for i, m in enumerate(mem)]
    rows += [["Baseline", "Baseline-static: 최초 배치를 고정하고 이동하지 않음 (As-Is proxy)", "정의"],
             ["SLO", "TTFT P99 ≤ 2 s, TPOT P99 ≤ 50 ms (공통 문서 §2, DP0와 동일)", "공통"]]
    y = table(s, 365760, 1290000, W(1.6, 8.7, 2.2), rows, sz=9, aligns=["l", "l", "ctr"], rowh=0.27)
    textbox(s, 365760, y + 100000, 11430000, 6400000 - y - 100000, bullets("SLO 선정 근거 (DP0 장표 5장과 같은 값, 같은 근거)", [
        "TTFT 2 s: H100×8에서 8K prefill 이론 시간은 약 0.32 s(2×70.6B×8,192 ÷ (8×989 TFLOPS×MFU 0.45), DP0 장표 계산)이며 2 s는 큐잉·스케줄링 여유를 포함한 값이다. B200은 연산이 더 커 여유가 더 크다.",
        "TPOT 50 ms: 디코드 step의 이론 하한(가중치 + KV 읽기)에 통신·스케줄링을 더해도 포화 시 약 40 ms대라는 DP0 장표의 계산과 같은 모델이다. DP1에서는 attention 오프로드 경로의 TPOT가 이 경계로 SLO 위반을 판정한다.",
        "이 SLO는 DP 간 비교 가능성을 위해 공통 고정값이며 결과를 본 뒤 바꾸지 않는다."]), fill="F2F2F2", name="slo")

    # ---------------- 7~10. QA별 기준
    def crit_slide(title, sub, rows, notes_l, notes_r, foot, src):
        s = new_slide(prs, title, sub, foot)
        fills = {(1, 0): "E2F0D9", (2, 0): "FFF2CC", (3, 0): "FBE5D6"}
        y = table(s, 365760, 1280000, W(1.0, 2.5, 6.6, 2.43), rows, sz=9.5, aligns=["ctr", "l", "l", "l"], fills=fills, rowh=0.6)
        h = 6780000 - 300000 - (y + 110000)
        textbox(s, 365760, y + 110000, 5600000, h, notes_l, name="l")
        textbox(s, 6200000, y + 110000, 5600000, h, notes_r, name="r")
        textbox(s, 365760, 6500000 - 0, 11430000, 230000, [[(src, 7.5, False, GREY)]], name="src")
        return s

    sb = g.json.load(open(g.DATA / "star_basis.json"))["summary"]
    rg = lambda k: f"{sb[k]['min']:.3f}~{sb[k]['max']:.3f}"
    rows = [["별", "성능 기준 (정량)", "왜 이 값인가 (정량 근거)", "출처 · 확인 수준"],
            ["★★★", "≥ 1.30 × Baseline", "같은 수요를 77%의 하드웨어로 처리 = 8-GPU 노드에서 약 1.85 GPU 절감(1.14배가 GPU 1장). 추가 메모리 HW와 migration 복잡도를 정당화할 크기라는 판단(정책 선택).", "환산 [C]. 결과를 본 뒤 정한 값(defined_after_first_look)"],
            ["★★☆", "0.97 ~ 1.30 × Baseline", f"하한 0.97 = Baseline끼리 seed 묶음을 바꿔 비교한 20회의 집계 범위 {rg('qa1_ratio')}의 아래 끝. 그 안은 잡음이라 열세로 보지 않는다.", "측정 [B+C], star_basis.py"],
            ["★☆☆", "< 0.97 × Baseline", "잡음 대역 밖의 열세: Baseline보다 느리다.", "측정 [B+C]"]]
    crit_slide("QA1 처리량 — 별 기준", "QA1 · Max SLO Goodput(output tok/s) ÷ Baseline · 시나리오 쌍별 비율의 기하평균 · SLO = TTFT P99 ≤ 2 s, TPOT P99 ≤ 50 ms",
               rows, bullets("지표와 결과", [
                   "Max SLO goodput = SLO를 위반한 요청의 토큰을 뺀 output tok/s를 load sweep으로 구한 최대값(공통 룰).",
                   f"결과 ×{rt(C1, gp):.2f} (C1) / ×{rt(C2, gp):.2f} (C2). 이득은 Dynamic 시나리오에 집중되고 공통 CB는 ×1.00이다(2장).",
                   "공통 룰의 별 경계는 0.90 / 1.10이다. DP1은 0.97 / 1.30을 쓰고 공통 별점을 병기한다(근거: qa-criteria-dp1.md §A)."]),
               bullets("정직한 주의", [
                   "★★★ 경계 1.30은 결과(C1 ×1.298, C2 ×1.422)를 본 뒤 정했다. 경계를 1.25로 하면 C1도 ★★★이다.",
                   "문헌 기반 대안(Oracle 대비 이득 달성률 80%)도 계산했으나 참고 지표로만 둔다(qa-capture-literature.md): C1 62% / C2 83%."], tcolor=RED),
               "※ DP1 별 기준 v5. 하한은 측정, 상한은 환산이며 정책 선택이 남는다. 같은 별 경계로 QA2·QA3도 같은 방식으로 정했다.",
               "출처: DP1/qa-criteria-dp1.md §A·§J · DP1/sim/star_basis.py · 공통 QA 문서 §4.3 (0.90/1.10, 참고 병기)")
    rows = [["별", "성능 기준 (정량)", "왜 이 값인가 (정량 근거)", "출처 · 확인 수준"],
            ["★★★", "6개 지표 개선 배수 ≥ 1.25", "지연 20% 감소 (예: TTFT P99 1,084 ms → 867 ms). '눈에 띄는 개선'의 크기로 둔 정책 선택.", "환산 [C]"],
            ["★★☆", "0.95 ~ 1.25", f"하한 0.95: Baseline끼리 비교한 잡음 범위 {rg('qa2_improvement')} 보다 약간 느슨하게 둠(5% 이내 열세는 열세로 보지 않음).", "측정 [B+C]"],
            ["★☆☆", "< 0.95", "지연이 5% 넘게 나빠짐(잡음 밖).", "측정 [B+C]"]]
    crit_slide("QA2 지연 — 별 기준", "QA2 · TTFT와 TPOT × P50/P95/P99 6개 지표의 개선 배수(Baseline ÷ 후보) 기하평균 · TTFT, TPOT는 따로 보고하고 별은 합친 값",
               rows, bullets("지표와 결과", [
                   f"C1 ×{G[C1]['qa2']['latency_improvement_geomean']:.2f} (TTFT ×{math.exp(sum(math.log(G[C1]['qa2']['improvement_vs_baseline'][f'ttft_{p}_ms']) for p in ('p50','p95','p99')) / 3):.2f} · TPOT ×{math.exp(sum(math.log(G[C1]['qa2']['improvement_vs_baseline'][f'tpot_{p}_ms']) for p in ('p50','p95','p99')) / 3):.2f}), "
                   f"C2 ×{G[C2]['qa2']['latency_improvement_geomean']:.2f}. 데이터 종류별로 RAG/Agent/Tool은 TTFT, LoRA/MoE는 TPOT, KV는 둘 다 영향을 받는다.",
                   "공통 룰의 QA2는 P99 worst-case(TTFT ≤ 2 s & TPOT ≤ 50 ms ★★★)다. DP1은 개선 배수를 쓰고 공통 별점을 병기한다."]),
               bullets("정직한 주의", [
                   f"평균은 좋아지지만 C1의 P99는 나쁘다: TTFT P99 ×{rt(C1, t99):.2f}, 21쌍 중 6쌍에서 Baseline보다 나쁘고 최악 ×4.32. 원인은 초반에 몰린 큰 이동이 DRAM 링크를 점유하는 것(loop-log iteration 4).",
                   "burst 용량을 줄이면 꼬리는 줄지만 이득도 같이 사라진다(trade-off)."], tcolor=RED),
               "※ DP1 별 기준 v5. 평균 개선 배수로 별을 정하므로 꼬리 악화는 별에 드러나지 않는다. 꼬리는 P99 값과 악화 쌍 수로 따로 본다.",
               "출처: DP1/qa-criteria-dp1.md §A·§J · DP1/results/iterations/loop-log.md (iteration 4) · 공통 QA 문서 §5 (참고 병기)")
    rows = [["별", "성능 기준 (정량)", "왜 이 값인가 (정량 근거)", "출처 · 확인 수준"],
            ["★★★", "HBM 절감 배수 ≥ 1.25", "HBM 점유 20% 감소 = 평균 146.6 GiB 중 약 29 GiB (8K KV object 약 1.6개분). QA2와 같은 '눈에 띄는 개선' 기준.", "환산 [C]"],
            ["★★☆", "0.95 ~ 1.25", f"하한 0.95: Baseline끼리 비교한 잡음 범위 {rg('qa3_saving')}보다 느슨하게 둠.", "측정 [B+C]"],
            ["★☆☆", "< 0.95", "HBM을 5% 넘게 더 씀(잡음 밖).", "측정 [B+C]"]]
    crit_slide("QA3 자원 (HBM 사용량) — 별 기준", "QA3 · HBM 사용량(GiB, 시간 평균 점유)의 Baseline 대비 비율(낮을수록 좋음) · 별은 절감 배수 = 1 ÷ 비율 · 성능은 섞지 않는다",
               rows, bullets("지표와 결과", [
                   f"C1 {f1(gmv(C1, hb))} GiB (×{rt(C1, hb):.2f}, 절감 {1 / rt(C1, hb):.2f}), C2 {f1(gmv(C2, hb))} GiB (×{rt(C2, hb):.2f}, 절감 {1 / rt(C2, hb):.2f}).",
                   "C2는 성능을 위해 hot 데이터를 HBM으로 올려 HBM을 더 쓴다. C1은 압력 때 DRAM·HBF로 내려 약간 줄인다.",
                   "보조: 어느 tier로 보냈는지(가격 차)를 보는 비용 가중 점유(ASSUMED 가격). 풀 활용률은 처리량과 상관이 0.99라 진단으로만 둔다."]),
               bullets("정직한 주의", [
                   "정의를 여러 번 바꿨다(활용률 → 풀 U → 성능÷비용 → HBM 사용량). 모두 결과를 본 뒤의 변경이며 마지막 변경이 선택을 C2에서 C1로 바꿨다.",
                   "HBM을 비우되 성능이 나빠지는 정책이 유리하므로 QA1·QA2와 함께 읽어야 한다. 공통 룰의 활용률(65%/85%)은 병기한다."], tcolor=RED),
               "※ DP1 별 기준 v5(QA3 정의 v6 = HBM 사용량). 가격은 ASSUMED, HBM 가중은 3배/5배/10배 민감도를 둔다.",
               "출처: DP1/qa-criteria-dp1.md §A·§I·§J · DP1/sim/cost_model.py · 공통 QA 문서 §6 (참고 병기)")

    # QA4 기준
    s = new_slide(prs, "QA4 변경 용이성 — 별 기준",
                  "공통 QA4 Modifiability · 세 지표를 모두 보고 세 sub-star의 중앙값으로 별 결정 · 시나리오 4개의 평균값에 기준을 적용",
                  "※ module 수 경계는 공통 QA 문서 그대로. 공수·비용 경계는 측정 전에 사전 등록한 가정이며 결과를 본 뒤 바꾸지 않는다(qa4-preregistration.md).")
    rows = [["별", "① 변경 module 수", "② 개발 공수 (man-month)", "③ 에이전트 비용 ($/변경, frontier tier)"],
            ["★★★", "≤ 2 (주요 interface 유지)", "≤ 0.5", "≤ $3"],
            ["★★☆", "3 ~ 5", "≤ 1.0", "≤ $10"],
            ["★☆☆", "≥ 6 또는 major interface 변경", "> 1.0", "> $10"]]
    y = table(s, 365760, 1300000, W(1.0, 3.6, 3.6, 4.33), rows, sz=9.5, aligns=["ctr", "l", "l", "l"], fills={(1, 0): "E2F0D9", (2, 0): "FFF2CC", (3, 0): "FBE5D6"}, rowh=0.5)
    rows2 = [["", "C1", "C2"], ["① module 수 (평균)", f"{star(stars_n(SUB4['C1']['M1']))}  {m4['C1']['modules']:.2f}", f"{star(stars_n(SUB4['C2']['M1']))}  {m4['C2']['modules']:.2f}"],
             ["② 공수 (man-month)", f"{star(stars_n(SUB4['C1']['M2']))}  {m4['C1']['man_months']:.3f}", f"{star(stars_n(SUB4['C2']['M2']))}  {m4['C2']['man_months']:.3f}"],
             ["③ 비용 (frontier / 중간 tier)", f"{star(stars_n(SUB4['C1']['M3']))}  ${m4['C1']['usd_T1']:.2f} / ${m4['C1']['usd_T2']:.2f}", f"{star(stars_n(SUB4['C2']['M3']))}  ${m4['C2']['usd_T1']:.2f} / ${m4['C2']['usd_T2']:.2f}"],
             ["QA4 별 (중앙값)", star(stars_n(Q4S[C1])), star(stars_n(Q4S[C2]))]]
    y = table(s, 365760, y + 130000, W(3.0, 2.6, 2.6), rows2, sz=9.5, aligns=["l", "ctr", "ctr"], rowh=0.3, total_row=True)
    textbox(s, 365760, y + 110000, 5600000, 6420000 - y - 110000, bullets("별 결정 규칙과 근거", [
        "QA4 별 = 세 sub-star의 중앙값. 세 값을 모두 보인다. sub-star는 시나리오 평균값에 적용한다(최악값 집계는 공유 module 하나가 결과를 정해 신호를 가려 쓰지 않음, 소유자 결정, 결과를 본 뒤 변경).",
        "② 공수: 변경 module 수와 LOC에서 가정 상수로 계산(c_mod 3.0, 검증 비율 등, ASSUMED). ③ 비용: 에이전트 토큰 × 가격 가정(frontier $15/$75 per MTok, 중간 tier $3/$15)."]), fill="F2F2F2", name="l")
    textbox(s, 6200000, y + 110000, 5600000, 6420000 - y - 110000, bullets("정직한 주의", [
        "상수 낙관/비관 조합에서도 C1과 C2의 QA4 별은 같지 않을 수 있다(민감도 qa4-modifiability.md). C2의 공수 0.506이 경계 0.5를 0.006 넘은 수준이라 상수에 민감하다.",
        "DP0의 QA4 경계(① $0.5/$2, ② man-day 3/7)와 값·단위가 다르다. 같은 QA의 경계 정합은 12장에서 점검한다."], tcolor=RED), fill="FFFBEA", name="r")

    # ---------------- 11. QA4 산출 근거
    s = new_slide(prs, "QA4 산출 근거 — 변경 시나리오별 module · 공수 · 비용",
                  "각 변경을 C1·C2 시뮬레이터 복사본에 실제로 구현해 module·LOC를 측정하고 공수·비용은 가정 상수로 계산 · 가중 없는 평균",
                  "※ 예상이 아닌 구현 측정이지만 시뮬레이터 복사본이며 실제 에이전트 세션 측정이 아니다. 공수·비용은 가정 상수(qa4-modifiability.md)에서 재계산된다. [B+C]")
    rows = [["S", "시나리오", "C1 (module · LOC · MM · $T1)", "C2 (module · LOC · MM · $T1)", "우세"]]
    sc = g.QA4["scenarios"]
    nm = {"S1": "새 메모리 추가 (CXL.mem expander)  ※ DP0 S1 새 tier 추가와 같은 변경", "S2": "새 AI data 종류 (SPARSE_EMBED)", "S3": "정책 교체 (C1 Affinity Mapper 지연 우선 / C2 Predictor 관측 전용)", "S4": "새 event 종류 (SLO_ALERT)"}
    for k in ("S1", "S2", "S3", "S4"):
        a, b2 = sc[k]["C1"], sc[k]["C2"]
        f = lambda x: f"{x['modules']} · {x['loc_added']} · {x['man_months']:.2f} · ${x['agent']['T1_frontier']['usd']:.2f}"
        win = "C1" if (a["modules"], a["man_months"]) < (b2["modules"], b2["man_months"]) else ("C2" if (a["modules"], a["man_months"]) > (b2["modules"], b2["man_months"]) else "동일")
        rows.append([k, nm[k], f(a), f(b2), win])
    rows.append(["평균", "4개 시나리오 평균", f"{m4['C1']['modules']:.2f} · — · {m4['C1']['man_months']:.2f} · ${m4['C1']['usd_T1']:.2f}", f"{m4['C2']['modules']:.2f} · — · {m4['C2']['man_months']:.2f} · ${m4['C2']['usd_T1']:.2f}", "C1"])
    y = table(s, 365760, 1300000, W(0.7, 5.0, 2.7, 2.7, 1.43), rows, sz=9.5, aligns=["ctr", "l", "ctr", "ctr", "ctr"], rowh=0.34, total_row=True)
    textbox(s, 365760, y + 120000, 5600000, 6420000 - y - 120000, bullets("차이가 나는 이유", [
        "C2는 type-aware라 새 메모리(S1)와 새 data 종류(S2)에서 Selector·registry class 수정이 더 필요하다(module 2, 3 대 1, 1).",
        "정책 교체(S3)와 새 event(S4)는 구조가 공유하는 부분이라 두 후보가 같다(2/2, 3/3).",
        "설계 문서의 약속(선호를 capability class로 두면 S1에서 C2 selector 무변경)은 시뮬레이터의 C2 구현에서는 지켜지지 않아 S1이 2가 되었다."]), fill="F2F2F2", name="l")
    textbox(s, 6200000, y + 120000, 5600000, 6420000 - y - 120000, bullets("한계", [
        "공수·비용은 가정 상수에 의존한다. 별은 상수 조합에 따라 ★★★~★★로 흔들린다. 후보 간 차이(module 1.75 대 2.50, 비용 약 1.3배)는 별 경계를 넘지 않을 수 있다.",
        "S2의 C1 smoke는 estimator 입력 도달까지만 확인했다(해당 trace에서 C1 migration 0건).",
        "DP0의 S1~S6과 달리 시나리오 가중을 두지 않았다(12장)."], tcolor=RED), fill="FFFBEA", name="r")

    # ---------------- 12. 정합 점검
    s = new_slide(prs, "정합 점검 — DP0와 같은 QA의 시나리오·기준",
                  "같은 QA에서 같은 시나리오·같은 기준은 같은 ID·값을 쓰고, 다른 것은 다르다고 표기 · '조치'는 이 deck에서 한 것, '결정 필요'는 소유자 확인 사항",
                  "※ DP0 deck(doc-mk/DP0/DP0-qa-result-slides.pptx)과 DP2·DP4 deck(Appendix)을 읽어 비교했다. DP0·DP2·DP4 파일은 수정하지 않았다.")
    rows = [["항목", "DP0", "DP1 (이 deck)", "상태", "조치 / 결정 필요"],
            ["QA 번호", "Q1 처리량 · Q2 지연 · Q3 변경 용이성 · Q4 확장성", "QA1 처리량 · QA2 지연 · QA3 HBM 사용 · QA4 변경 용이성", "다름", "이 deck은 공통 문서 번호 사용. DP0의 Q3 = 공통 QA4(변경 용이성), Q4 = 공통 QA6. DP0 번호 정리는 결정 필요"],
            ["모델·워크로드·SLO", "Llama-3.1-70B BF16, 8K/256, TTFT P99 ≤ 2 s, TPOT P99 ≤ 50 ms", "같음", "일치", "조치 없음 (공통 문서 §2 고정값)"],
            ["load sweep · seed", "load ×0.5/1.0/1.5/2.0, seed ≥ 5", "load ×0.5/1.0/1.5/2.0, seed 5개", "일치", "조치 없음"],
            ["공통 벤치마크", "W1 '공통 벤치마크' 1개 (CB 대응 없음)", "CB-1·CB-2·CB-3 (common-benchmark.md 2.1과 같은 ID·파라미터)", "다름", "DP1은 공통 문서 ID 사용. DP0 W1을 CB-1~3으로 실현할지는 결정 필요(common-benchmark.md §8 DP0 행 없음)"],
            ["별을 매기는 시나리오 집합", "W1~W5 (DP0 정의)", "공식: Common+Stress+Dynamic 21쌍 / 참고: Common만 (2장)", "DP마다 다름", "공통 문서는 Common만. DP4는 Common 6쌍, DP2는 전체 38쌍. 통일 여부는 결정 필요. 이 deck은 2장에 Common-only를 병기해 비교 가능하게 함"],
            ["QA4 변경 시나리오", "S1~S6 (새 tier, 비용 함수, P/D 정책, 노드 지시, vLLM 계약, 신규 기능), S2~S4 가중 2", "S1~S4 (새 메모리, 새 data 종류, 정책 교체, 새 event), 가중 없음", "일부 같음", "S1은 같은 변경(새 메모리/tier 추가)이라 문구를 맞춤. S2~S4는 DP마다 의미가 달라 DP 접두사(DP1-S2) 권장"],
            ["QA4 경계", "① $0.5/$2 ② 3/7 man-day ③ module ≤2/3~5/≥6", "① module 같음 ② ≤0.5/≤1.0 man-month ③ ≤$3/≤$10 (frontier $15/$75)", "다름", "module은 일치. 공수 단위(man-day 대 man-month)와 비용 가격 tier가 다름. DP1에 중간 tier($3/$15, DP0와 같은 가격) 값을 병기. 경계 통일은 결정 필요(결과를 본 뒤 변경 금지 H5)"],
            ["Baseline·Evidence", "정책 없는 기본 라우팅, 실측 [A+C]", "Baseline-static(이동 없음), 시뮬레이션 [B+C]", "다름(정상)", "대상 DP가 달라 Baseline 정의가 다르다. Evidence 표기로 구분"]]
    fills = {}
    for r in range(1, len(rows)):
        st = rows[r][3]
        fills[(r, 3)] = "E2F0D9" if st == "일치" else ("FFF2CC" if st in ("일부 같음", "다름(정상)") else "FBE5D6")
    table(s, 365760, 1290000, W(1.5, 2.6, 2.8, 0.9, 4.73), rows, sz=8.5, aligns=["l", "l", "l", "ctr", "l"], fills=fills, rowh=0.3)
    prs.save(out)
    return prs


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--ref", default=REF)
    ap.add_argument("--out", default=OUT)
    a = ap.parse_args()
    prs = build(a.ref, a.out)
    # 경계 검사
    for i, s in enumerate(prs.slides, 1):
        for sh in s.shapes:
            if sh.left < 0 or sh.top < 0 or sh.left + sh.width > SW + 10 or sh.top + sh.height > SH + 10:
                PROBLEMS.append(f"slide {i}: out of slide: {sh.name} ({(sh.top + sh.height) / E:.2f}in)")
    print("saved:", a.out, len(prs.slides), "slides")
    for p in PROBLEMS:
        print(" -", p)
    if PROBLEMS:
        sys.exit(1)
    print("verify OK")


if __name__ == "__main__":
    main()
