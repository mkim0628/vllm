#!/usr/bin/env python3
"""Build the DP evaluation appendix slide(s) and the complement-design tactics slide (DP1) from result data.

    python tools/gen_dp_pptx.py --out-dir doc-mk/DP1 [--preview-dir DIR]

Needs python-pptx (+ Pillow for --preview-dir). Base template: doc-mk/DP1/DP-memory-backend-if.pptx (slide 9 frame).
Numbers come from tools/gen_dp1_result.py (RT/P/PRIO) so slide and result doc cannot diverge.
"""
from __future__ import annotations

import argparse
import copy
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import gen_dp1_result as g  # noqa: E402
from dp_selection import select  # noqa: E402

STY = {
    "dp": ("DCE9F5", "4D7EA8", "1A1A1A"), "head": ("1F4E79", "1F4E79", "FFFFFF"),
    "c2": ("E6E0F4", "7B66B0", "1A1A1A"), "rm": ("FDEBD3", "C98A3C", "1A1A1A"),
    "cell": ("FFFFFF", "BFBFBF", "1A1A1A"), "note": ("F2F2F2", "BFBFBF", "404040"),
    "sel": ("E3F1E3", "5B9B5B", "1A1A1A"), "warn": ("FFF8EC", "C98A3C", "1A1A1A"),
}
FONT_PATH = "/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc"


def _font(sz):
    from PIL import ImageFont
    return ImageFont.truetype(FONT_PATH, max(8, int(sz * 110 / 72)))


def wrap(text, width_in, size):
    """Pre-wrap to the box width (110 px/in, 8% safety)."""
    from PIL import Image, ImageDraw
    d = ImageDraw.Draw(Image.new("RGB", (10, 10)))
    f = _font(size)
    maxw = (width_in - 0.1) * 110 * 0.92
    out, cur = [], ""
    for ch in text:
        if d.textlength(cur + ch, font=f) > maxw and cur:
            out.append(cur)
            cur = ch.lstrip()
        else:
            cur += ch
    if cur:
        out.append(cur)
    return out


class Slide:
    def __init__(self, title):
        self.title, self.E = title, []

    def box(self, x, y, w, h, text, sty, size=8.5, bold=False, align="l", top=True):
        paras = []
        for para in (text if isinstance(text, list) else [text]):
            paras += wrap(para, w, size) or [""]
        self.E.append(dict(x=x, y=y, w=w, h=h, lines=paras, sty=sty, size=size, bold=bold, align=align, top=top))


def stars(c):
    return g.stars_combined()[c]


def qa_slide():
    st = g.stars_combined()
    sel = select(st, g.PRIO["priority"])
    G = g.RT[g.PRIMARY]["sets"]["combined"]
    Q = g.P["combined"]["qa_feasible"]
    B, C1, C2 = g.B, g.C1, g.C2
    s = Slide("DP1 평가 결과 - QA별 후보 비교 (SYS-4, Common + Stress + Dynamic)")
    cols = [("QA", 0.4, 1.55), ("지표 (DP1 별점 기준)", 1.95, 2.75), ("Baseline", 4.7, 1.7), ("C1 Resource-driven", 6.4, 2.0), ("C2 Behavior-driven", 8.4, 2.0), ("우세", 10.4, 2.5)]
    y = 1.2
    for name, x, w in cols:
        s.box(x, y, w, 0.34, name, "head", 9, True, "ctr", False)
    n_ = lambda t: t.count("★")
    win = lambda a, b: "동률" if n_(a) == n_(b) else ("C1" if n_(a) > n_(b) else "C2")
    rows = [
        ("QA1 Throughput [B]", "Baseline 대비 SLO goodput (geomean)", f"{G[B]['dp1_star']['qa1']} x1.00", f"{st[C1]['QA1']} x{G[C1]['qa1']['ratio']:.2f}", f"{st[C2]['QA1']} x{G[C2]['qa1']['ratio']:.2f}", win(st[C1]['QA1'], st[C2]['QA1'])),
        ("QA2 Latency [B]", "TTFT/TPOT x P50/P95/P99 개선 배수 (geomean)", f"{G[B]['dp1_star']['qa2']} x1.00", f"{st[C1]['QA2']} x{G[C1]['qa2']['latency_improvement_geomean']:.2f}", f"{st[C2]['QA2']} x{G[C2]['qa2']['latency_improvement_geomean']:.2f}", win(st[C1]['QA2'], st[C2]['QA2'])),
        ("QA3 Utilization [B]", "useful 활용률 (SLO 만족 비율 x HBM 점유 x (1-migration 링크 점유))", f"{G[B]['dp1_star']['qa3']} {G[B]['qa3']['useful_util']*100:.0f}%", f"{st[C1]['QA3']} {G[C1]['qa3']['useful_util']*100:.0f}% ({G[C1]['qa3']['delta_pp_vs_baseline']:+.0f}pp)", f"{st[C2]['QA3']} {G[C2]['qa3']['useful_util']*100:.0f}% ({G[C2]['qa3']['delta_pp_vs_baseline']:+.0f}pp)", win(st[C1]['QA3'], st[C2]['QA3'])),
        ("QA4 Modifiability [C]", "신규 data type / memory 추가 시 변경 module 수 (논증)", "—", f"{st[C1]['QA4']} (1~2개)", f"{st[C2]['QA4']} (4개)", win(st[C1]['QA4'], st[C2]['QA4'])),
    ]
    y = 1.58
    for r in rows:
        for (name, x, w), v in zip(cols, r):
            s.box(x, y, w, 0.58, v, "dp" if name == "QA" else "cell", 10, name in ("QA", "우세"), "ctr" if name not in ("QA", "지표 (DP1 별점 기준)") else "l", False)
        y += 0.6
    s.box(0.4, y, 5.95, 0.4, "별 합계", "dp", 9, True, "ctr", False)
    s.box(4.7, y, 1.7, 0.4, "—", "cell", 9, False, "ctr", False)
    s.box(6.4, y, 2.0, 0.4, f"{sel['totals'][C1]}", "cell", 10, True, "ctr", False)
    s.box(8.4, y, 2.0, 0.4, f"{sel['totals'][C2]}", "cell", 10, True, "ctr", False)
    s.box(10.4, y, 2.5, 0.4, "동점" if sel["gap"] == 0 else f"차이 {sel['gap']}", "cell", 9, True, "ctr", False)
    y += 0.55
    q2, q1 = Q[C2], Q[C1]
    s.box(0.4, y, 6.1, 1.75, [
        "Trade-off",
        f"- C2는 QA1에서 앞서고, C1은 QA4에서 앞선다. QA2·QA3는 같은 별이다.",
        f"- C2의 비용: migration {q2['migration_gib']:,.0f} GiB (C1 {q1['migration_gib']:,.0f}), 링크 점유 {q2['migration_link_frac']*100:.1f}% (C1 {q1['migration_link_frac']*100:.1f}%), 신규 data type 추가 시 module 4개.",
        "- 이득은 static 배치가 stale해지는 Dynamic 시나리오에 집중. Common/Stress는 Baseline과 동률."], "note", 10)
    s.box(6.7, y, 6.2, 1.75, [
        f"선택: {'C2' if sel['winner'] == g.C2 else 'C1'}",
        f"- 규칙: 별 합계 차이 2 이상이면 합계, 아니면 QA 우선순위({' > '.join(g.PRIO['priority'])}).",
        f"- 합계 {sel['totals'][C1]} 대 {sel['totals'][C2]} (동점)이므로 {sel['deciding_qa']}에서 앞선 후보 선택.",
        f"- 우선순위를 뒤집으면 {'C2' if sel['reversed_winner'] == g.C2 else 'C1'} ({sel['reversed_deciding_qa']}). 선택은 우선순위 판단에 의존."], "sel", 10)
    y += 1.85
    s.box(0.4, y, 12.5, 0.6, [
        "평가 조건 / 한계: Evidence [B] simulation(config 기반, [A] 실측 아님) + [C] 논증. DP1 별점 경계(QA1 1.30, QA3 +15pp)는 첫 결과를 본 뒤 정함. C2 QA3 +14pp는 경계 직전. 상세: DP1/results/2026-10-02_dp1-qa-evaluation.md"], "warn", 9)
    return s


def tactics_slide():
    Q = g.P["combined"]["qa_feasible"]
    C1, C2 = g.C1, g.C2
    s = Slide("DP1 선택 구조(C2)의 보완 설계 택틱 - 제안")
    cols = [("#", 0.4, 0.45), ("약점 (평가 근거)", 0.85, 3.2), ("보완 택틱", 4.05, 5.0), ("개선 QA", 9.05, 1.0), ("검증 상태", 10.05, 2.85)]
    for name, x, w in cols:
        s.box(x, 1.2, w, 0.34, name, "head", 9, True, "ctr", False)
    rows = [
        ("W1", f"QA4 ★★: 신규 AI data type 추가 시 변경 module 4개 (class metadata, Behavior Monitor feature, Predictor input, Destination 선호)",
         "T1 type 특성을 descriptor(데이터)로 외부화. descriptor가 없는 class는 type-agnostic 경로로 처리 -> 신규 type 추가 = descriptor 1개", "QA4", "[C] 논증, 미구현. 기대: 변경 module 4 -> 1~2 (미검증)"),
        ("W2", f"migration 비용: C2 {Q[C2]['migration_gib']:,.0f} GiB (C1 {Q[C1]['migration_gib']:,.0f}), 링크 점유 {Q[C2]['migration_link_frac']*100:.1f}% (C1 {Q[C1]['migration_link_frac']*100:.1f}%)",
         "T2 link-time budget + 이득/비용 gating (simulator 적용). traffic class 우선순위(demand > prefetch > demotion). replica가 있으면 DROP 우선", "QA1 QA3", "budget/gating [B] 적용. class 우선순위·DROP 우선은 [C]"),
        ("W3", "예측 의존: C2는 predictor가 틀리면 잘못된 migration. 오차 e=0.6까지는 우위 유지(lognormal 한 종류, 결과 4.6)",
         "T3 신뢰도 gating (낮으면 C1의 resource-pressure 트리거로 대체) + 이득 미실현 시 자동 중단(do-no-harm guard) + hysteresis", "QA1 안정성", "[C] 미구현. 실제 workload 이동 robustness는 미확인"),
        ("W4", f"decision overhead {Q[C2]['decision_overhead_ms']:.0f} ms/run (C1 {Q[C1]['decision_overhead_ms']:.0f} ms). SLO(초 단위) 영향은 작음",
         "T4 event coalescing(구현), feature 점진 갱신, decision을 critical path 밖에서 비동기 실행", "QA2", "coalescing [B], 나머지 [C]"),
    ]
    y = 1.6
    for r in rows:
        h = 1.12
        for (name, x, w), v in zip(cols, r):
            s.box(x, y, w, h, v, "dp" if name == "#" else ("c2" if name == "보완 택틱" else "cell"), 10, name == "#", "ctr" if name in ("#", "개선 QA") else "l", False)
        y += h + 0.06
    s.box(0.4, y + 0.05, 12.5, 0.75, [
        "적용 우선순위 제안: T1(QA4 직접 보완) > T3(예측 의존 리스크) > T2 잔여 항목 > T4. T1, T3는 simulator 적용 전까지 효과를 수치로 주장하지 않는다.",
        "택틱은 C2 구조에 추가되는 module(Descriptor Registry, Confidence Gate, Do-no-harm Guard)로 표현할 수 있다."], "note", 10)
    return s


def build(slides, out, base_pptx):
    from pptx import Presentation
    from pptx.dml.color import RGBColor
    from pptx.enum.shapes import MSO_SHAPE
    from pptx.enum.text import MSO_ANCHOR, PP_ALIGN
    from pptx.util import Inches, Pt
    from lxml import etree

    A = "http://schemas.openxmlformats.org/drawingml/2006/main"
    FONT = "맑은 고딕"
    rgb = RGBColor.from_string
    prs = Presentation(str(base_pptx))
    base = prs.slides[8]
    keep = {3, 5, 8, 39, 57}
    originals = list(prs.slides._sldIdLst)
    for sl in slides:
        s = prs.slides.add_slide(base.slide_layout)
        for sh in list(s.shapes):
            sh._element.getparent().remove(sh._element)
        for sh in base.shapes:
            if sh.shape_id in keep:
                s.shapes._spTree.append(copy.deepcopy(sh._element))
        for sh in s.shapes:
            if sh.shape_id == 3:
                r = sh.text_frame.paragraphs[0].runs
                r[0].text = "DP1. 이기종 메모리 기반 Data Migration 구조 - Appendix"
                for x in r[1:]:
                    x.text = ""
            if sh.shape_id == 8:
                r = sh.text_frame.paragraphs[0].runs
                r[0].text = sl.title
                for x in r[1:]:
                    x.text = ""
                sh.width = Inches(12.5)
        for e in sl.E:
            f, l, t = STY[e["sty"]]
            b = s.shapes.add_shape(MSO_SHAPE.RECTANGLE, Inches(e["x"]), Inches(e["y"]), Inches(e["w"]), Inches(e["h"]))
            b.shadow.inherit = False
            b.fill.solid(); b.fill.fore_color.rgb = rgb(f)
            b.line.color.rgb = rgb(l); b.line.width = Pt(0.75)
            tf = b.text_frame; tf.word_wrap = True
            tf.margin_left = tf.margin_right = Inches(0.05); tf.margin_top = tf.margin_bottom = Inches(0.03)
            tf.vertical_anchor = MSO_ANCHOR.TOP if e["top"] else MSO_ANCHOR.MIDDLE
            for i, ln in enumerate(e["lines"]):
                p = tf.paragraphs[0] if i == 0 else tf.add_paragraph()
                p.alignment = PP_ALIGN.CENTER if e["align"] == "ctr" else PP_ALIGN.LEFT
                r = p.add_run(); r.text = ln
                r.font.size = Pt(e["size"]); r.font.name = FONT
                r.font.bold = bool(e["bold"]) or (i == 0 and e["sty"] in ("note", "sel") and not ln.startswith("-") and not ln.startswith("평가"))
                r.font.color.rgb = rgb(t)
                ea = etree.SubElement(r._r.get_or_add_rPr(), "{%s}ea" % A); ea.set("typeface", FONT)
    lst = prs.slides._sldIdLst
    for el in originals:
        prs.part.drop_rel(el.rId)
        lst.remove(el)
    prs.save(str(out))


def preview(sl, out):
    from PIL import Image, ImageDraw
    S = 110
    hx = lambda h: tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))
    im = Image.new("RGB", (int(13.333 * S), int(7.5 * S)), "white")
    d = ImageDraw.Draw(im)
    d.text((20, 15), sl.title, font=_font(14), fill=(0, 0, 0))
    for e in sl.E:
        f, l, t = STY[e["sty"]]
        x, y, w, h = [int(v * S) for v in (e["x"], e["y"], e["w"], e["h"])]
        d.rectangle([x, y, x + w, y + h], fill=hx(f), outline=hx(l))
        lh = int(e["size"] * S / 72 * 1.3)
        ty = y + 4 if e["top"] else y + max(2, (h - lh * len(e["lines"])) // 2)
        for i, ln in enumerate(e["lines"]):
            font = _font(e["size"])
            tw = d.textlength(ln, font=font)
            d.text((x + (w - tw) / 2 if e["align"] == "ctr" else x + 5, ty + i * lh), ln, font=font, fill=hx(t))
            if ty + (i + 1) * lh > y + h + 2:
                print("OVERFLOW", sl.title[:20], ln[:30])
    im.save(out)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out-dir", type=Path, default=g.ROOT.parent / "DP1")
    ap.add_argument("--preview-dir", type=Path, default=None)
    a = ap.parse_args()
    base = g.ROOT.parent / "DP1" / "DP-memory-backend-if.pptx"
    a.out_dir.mkdir(parents=True, exist_ok=True)
    jobs = [("DP1-appendix-qa-result.pptx", [qa_slide()]), ("DP1-complement-design-tactics.pptx", [tactics_slide()])]
    for name, sls in jobs:
        build(sls, a.out_dir / name, base)
        print("wrote", a.out_dir / name, len(sls), "slide(s)")
        if a.preview_dir:
            a.preview_dir.mkdir(parents=True, exist_ok=True)
            for i, sl in enumerate(sls):
                preview(sl, a.preview_dir / f"{name[:-5]}-{i + 1}.png")


if __name__ == "__main__":
    main()
