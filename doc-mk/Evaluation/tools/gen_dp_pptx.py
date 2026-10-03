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
    sel = g.overall_selection()
    st = sel["stars"]
    B, C1, C2 = g.B, g.C1, g.C2
    SY = g.SYSIDS
    m = g.QA4["mean_over_scenarios"]
    s = Slide(f"DP1 평가 결과 - QA별 후보 비교 (메모리 세대별 {len(SY)}개 시스템: {', '.join(x[4:] for x in SY)}, Common + Stress + Dynamic)")
    cw = 10.2 / len(g.SYSIDS)
    cols = [("QA", 0.4, 1.9)] + [(sid, 2.3 + k * cw, cw) for k, sid in enumerate(SY)]
    y = 1.2
    for name, x, w in cols:
        s.box(x, y, w, 0.34, name if name == "QA" else f"{name} ({g.RT[name]['sets']['combined'][B]['n']}개)", "head", 9, True, "ctr", False)
    def two(sid, key):
        G = g.RT[sid]["sets"]["combined"]
        f = {"QA1": lambda c: f"x{G[c]['qa1']['ratio']:.2f}", "QA2": lambda c: f"x{G[c]['qa2']['latency_improvement_geomean']:.2f}",
             "QA3": lambda c: f"x{G[c]['qa3'].get('rel_vs_baseline', 1.0):.2f}"}.get(key)
        out = []
        for c, nm in ((C1, "C1"), (C2, "C2")):
            v = f(c) if f else (f"{m[nm]['modules']:.1f}모듈 ${m[nm]['usd_T1']:.2f}")
            out.append(f"{nm} {st[sid][c][key]} {v}")
        return out
    labels = {"QA1": "QA1 Throughput [B]\n(Baseline 대비 goodput)", "QA2": "QA2 Latency [B]\n(개선 배수)", "QA3": "QA3 Utilization [B]\n(전 메모리 풀 U 상대)", "QA4": "QA4 Modifiability [B+C]\n(module / 에이전트 비용)"}
    y = 1.58
    for key in ("QA1", "QA2", "QA3", "QA4"):
        s.box(0.4, y, 1.9, 0.56, labels[key].split("\n"), "dp", 9, True, "l", False)
        for k, sid in enumerate(SY):
            s.box(2.3 + k * cw, y, cw, 0.56, two(sid, key), "cell", 10, False, "ctr", False)
        y += 0.58
    s.box(0.4, y, 1.9, 0.4, "별 합계 (C1 / C2)", "dp", 9, True, "l", False)
    for k, sid in enumerate(SY):
        t = sel["per"][sid]["totals"]
        s.box(2.3 + k * cw, y, cw, 0.4, f"{t[C1]} / {t[C2]}", "cell", 10, True, "ctr", False)
    y += 0.42
    nm = {C1: "C1", C2: "C2", None: "구분 불가"}
    s.box(0.4, y, 1.9, 0.4, "선택 (우선순위 규칙)", "dp", 9, True, "l", False)
    for k, sid in enumerate(SY):
        w = sel["per"][sid]
        s.box(2.3 + k * cw, y, cw, 0.4, f"{nm[w['winner']]}" + (f" ({w['deciding_qa']})" if w["deciding_qa"] else (" (합계)" if w["winner"] else "")), "sel", 10, True, "ctr", False)
    y += 0.52
    cells = g.tradeoff_cells()
    Q = g.R[g.PRIMARY]["combined"]["qa_feasible"]
    s.box(0.4, y, 6.1, 1.6, [
        "Trade-off",
        f"- C2 우세 칸: {', '.join(cells[1]) or '없음'}",
        f"- C1 우세 칸: {', '.join(cells[0]) or '없음'}",
        f"- C2 비용({g.PRIMARY}): migration {Q[C2]['migration_gib']:,.0f} GiB (C1 {Q[C1]['migration_gib']:,.0f}), 링크 점유 {Q[C2]['migration_link_frac']*100:.1f}% (C1 {Q[C1]['migration_link_frac']*100:.1f}%)",
        "- QA4 [B+C]: 평균 집계로 C1 ★★★, C2 ★★ (C2의 공수가 경계 0.5 MM를 0.006 넘음)"], "note", 9.5)
    s.box(6.7, y, 6.2, 1.6, [
        f"선택: {nm[sel['winner']]}",
        f"- 규칙: 별 합계가 높은 후보. 합계가 같을 때만 QA 우선순위({' > '.join(g.PRIO['priority'])}).",
        f"- 시스템별 별 합계 합: C1 {sel['totals'][C1]}, C2 {sel['totals'][C2]} -> {nm[sel['winner']]}.",
        f"- 우선순위 상태: {g.PRIO['status'].split(' - ')[0]}"], "sel", 9.5)
    y += 1.7
    s.box(0.4, y, 12.5, 0.55, [
        "한계: [B] simulation(config 기반, [A] 실측 아님). H100 규격·link 스케일 ASSUMED. QA3는 SSD-PIM이 풀의 약 75%라 U가 1~2%대(상대값으로 판정). QA4 공수·비용은 가정 상수 추정. 별 경계는 결과를 본 뒤 정한 값 포함."], "warn", 8.5)
    return s


def tactics_slide():
    Q = g.P["combined"]["qa_feasible"]
    C1, C2 = g.C1, g.C2
    s = Slide("DP1 보완 설계 택틱 - 제안 (선택 구조 C2 기준)")
    cols = [("#", 0.4, 0.45), ("약점 (평가 근거)", 0.85, 3.2), ("보완 택틱", 4.05, 5.0), ("개선 QA", 9.05, 1.0), ("검증 상태", 10.05, 2.85)]
    for name, x, w in cols:
        s.box(x, 1.2, w, 0.34, name, "head", 9, True, "ctr", False)
    rows = [
        ("W1", f"QA4: 신규 AI data class 추가 시 C2 module {g.QA4['scenarios']['S2']['C2']['modules']}개(C1 {g.QA4['scenarios']['S2']['C1']['modules']}개), 신규 memory는 선호 목록에 명시해야 사용됨(C1은 코드 변경 없이 사용)",
         "T1 type 특성을 descriptor(데이터)로 외부화. descriptor가 없는 class는 type-agnostic 경로로 처리 -> 신규 type 추가 = descriptor 1개", "QA4", "[C] 논증, 미구현. 기대: 변경 module 3 -> 1~2 (미검증)"),
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
