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


def qa_slides():
    o = g.overall_selection()
    st = o["stars"][g.MERGED]
    G = g.RTM["sets"]["combined"]
    Qf = g.RM["combined"]["qa_feasible"]
    T = g.RM["combined"]["tally"]
    B, C1, C2 = g.B, g.C1, g.C2
    m = g.QA4["mean_over_scenarios"]
    nm = {C1: "C1", C2: "C2", None: "구분 불가"}
    wl = lambda c: f"{len(T[c]['win'])}승 {len(T[c]['tie'])}무 {len(T[c]['loss'])}패"
    def lat(c):
        l = G[c]["qa2"]["latency"]
        return f"TTFT P50/P95/P99 {l['ttft_p50_ms']['median']:,.0f}/{l['ttft_p95_ms']['median']:,.0f}/{l['ttft_p99_ms']['median']:,.0f} ms"
    s = Slide("DP1 평가 결과 - QA별 후보 비교 (H100 + B200 통합)")
    cols = [("QA / 지표", 0.4, 3.2), ("C1 Resource-driven", 3.6, 4.65), ("C2 Behavior-driven", 8.25, 4.65)]
    y = 1.2
    for name, x, w in cols:
        s.box(x, y, w, 0.34, name, "head", 10, True, "ctr", False)
    rows = [
        (["QA1 Throughput [B]", "Baseline 대비 SLO goodput 배수, 승/무/패"],
         [f"{st[C1]['QA1']}  x{G[C1]['qa1']['ratio']:.2f} (±{G[C1]['qa1']['ci95']:.2f})", wl(C1)], [f"{st[C2]['QA1']}  x{G[C2]['qa1']['ratio']:.2f} (±{G[C2]['qa1']['ci95']:.2f})", wl(C2)]),
        (["QA2 Latency [B]", "TTFT/TPOT 개선 배수(geomean), 중앙값 TTFT"],
         [f"{st[C1]['QA2']}  x{G[C1]['qa2']['latency_improvement_geomean']:.2f}", lat(C1)], [f"{st[C2]['QA2']}  x{G[C2]['qa2']['latency_improvement_geomean']:.2f}", lat(C2)]),
        (["QA3 (진단, 별점 제외) [B]", "전 메모리 풀 U 상대값, 링크 점유, 이동량"],
         [f"U x{G[C1]['qa3']['rel_vs_baseline']:.2f} ({G[C1]['qa3']['useful_util']*100:.2f}%)", f"링크 {Qf[C1]['migration_link_frac']*100:.1f}% · {Qf[C1]['migration_gib']:,.0f} GiB"],
         [f"U x{G[C2]['qa3']['rel_vs_baseline']:.2f} ({G[C2]['qa3']['useful_util']*100:.2f}%)", f"링크 {Qf[C2]['migration_link_frac']*100:.1f}% · {Qf[C2]['migration_gib']:,.0f} GiB"]),
        (["QA4 Modifiability [B+C]", "변경 4종 평균: module, 공수, 에이전트 비용"],
         [f"{st[C1]['QA4']}  module {m['C1']['modules']:.2f}", f"{m['C1']['man_months']:.2f} man-month · ${m['C1']['usd_T1']:.2f}"], [f"{st[C2]['QA4']}  module {m['C2']['modules']:.2f}", f"{m['C2']['man_months']:.2f} man-month · ${m['C2']['usd_T1']:.2f}"]),
    ]
    y = 1.58
    for lab, a, b in rows:
        s.box(0.4, y, 3.2, 0.62, lab, "dp", 9.5, True, "l", False)
        s.box(3.6, y, 4.65, 0.62, a, "cell", 10, False, "ctr", False)
        s.box(8.25, y, 4.65, 0.62, b, "cell", 10, False, "ctr", False)
        y += 0.64
    s.box(0.4, y, 3.2, 0.4, "별 합계", "dp", 10, True, "l", False)
    s.box(3.6, y, 4.65, 0.4, f"{o['totals'][C1]}", "cell", 11, True, "ctr", False)
    s.box(8.25, y, 4.65, 0.4, f"{o['totals'][C2]}", "cell", 11, True, "ctr", False)
    y += 0.52
    d = g.RM["dp1_dynamic_benchmark"]["tally"]
    s.box(0.4, y, 6.2, 2.15, [
        "Trade-off와 이유",
        "- 성능은 C2: 데이터마다 접근 빈도·재사용·유휴를 보고 이동해, 같은 종류(KV) 안의 hot/cold를 구분한다. C1은 자원 압박에만 반응해 구분 못 함.",
        f"- 비용은 C2: migration {Qf[C2]['migration_gib']:,.0f} GiB (C1 {Qf[C1]['migration_gib']:,.0f}), 링크 점유 {Qf[C2]['migration_link_frac']*100:.1f}% (C1 {Qf[C1]['migration_link_frac']*100:.1f}%)라 이동이 서빙 링크를 나눠 써서 지연·처리량 이득이 줄어든다(간섭 모델 반영).",
        f"- 확장성은 C1: 종류를 모르는 구조라 새 데이터 종류 추가 시 module 1개 (C2 3개).",
        "- 지연(QA2)은 둘 다 ★★★ 경계를 넘어 별이 같지만 값은 C2가 높다."], "note", 9.5)
    why = (f"합계 {o['totals'][C1]} 대 {o['totals'][C2]}로 같아 QA 우선순위로 결정: {o['deciding']}에서 앞선 {nm[o['winner']]}" if o["rule"] == "priority"
           else f"별 합계가 높은 {nm[o['winner']]}")
    s.box(6.8, y, 6.1, 2.15, [
        f"선택: {nm[o['winner']]}",
        f"- 규칙: 별 합계가 높은 후보, 같을 때만 QA 우선순위({' > '.join(g.PRIO['priority'])}).",
        f"- {why}.",
        f"- 우선순위를 뒤집으면 {nm[o['reversed_winner']]}.",
        "- 한계: [B] simulation, 별 경계(QA1 1.30, QA4 평균 집계)는 결과를 본 뒤 정함. QA4 공수·비용은 가정 상수 추정."], "sel", 9.5)

    # slide 2: scenarios in plain language
    ft = g.fit_counts()
    s2 = Slide("DP1 평가에서 고려한 시나리오")
    s2.box(0.4, 1.2, 12.5, 0.55, [f"32개 시나리오를 H100과 B200에 각각 돌렸다(64쌍): 비교 가능 {ft['comparison_valid']}쌍, 포화 {ft['saturated']}쌍, Baseline도 SLO 불가라 비교 제외 {ft['infeasible']}쌍."], "note", 10)
    blocks = [
        ("기본 서비스 상황 (공통)", "8K 토큰 입력, 256 토큰 생성, 동시 32 요청의 대화 서비스. HBM이 빠듯한 경우 / 시간이 갈수록 여유가 줄어드는 경우 / KV cache에 LoRA·MoE·Agent 데이터가 섞이는 경우. 결과: 두 후보 모두 Baseline과 같다."),
        ("데이터 종류별", "대화 문맥(KV cache, 32K~512K 토큰, 동시 1~256) · 여러 고객이 쓰는 LoRA 어댑터(몇 개만 인기) · MoE expert(라우팅 쏠림) · 수 TiB 벡터 DB(RAG) · 오래 보관되는 Agent 기억과 Tool 결과(드물게 재사용 / 한꺼번에 생성 후 반복 참조)."),
        ("접근이 쏠리는 정도(hotness)", "소수만 인기 있는 skew · 거의 안 쓰이는 cold 데이터가 상위 메모리를 차지 · 갑자기 hot해지는 burst · hot/cold 급반전 · hot 대상이 옮겨 감(최근 세션으로 이동, 사용자 그룹이 번갈아 활성, 인기 검색 shard가 바뀜). 고르게 접근되는 전용 시나리오는 아직 없음(중간 KV 기준선이 대조군)."),
        ("자원 조건이 바뀌는 경우", "HBM 용량 압박(고정 / 점진 증가) · HBM 대역폭 급락 · 다른 작업과 공유하는 host 링크 경합(대역폭 25%로 저하) · 6개 메모리 용량을 모두 써야 하는 큰 용량 부담."),
        ("처음엔 문제없다가 나빠지는 경우 (Dynamic 6개)", "Baseline이 처음엔 SLO를 만족하다 중간에 working set이 바뀐다. 예: 오래 보관만 되던 Agent 기억이 HBM을 차지한 채 채팅이 몰림 / hot 대화가 초기 세션에서 최근 세션으로 이동. Baseline의 실패 양상을 알고 설계했으므로 이득은 이 상황에 한정."),
    ]
    y = 1.85
    for t, body in blocks:
        s2.box(0.4, y, 2.9, 0.92, t, "dp", 10, True, "l", False)
        s2.box(3.3, y, 9.6, 0.92, body, "cell", 11, False, "l", False)
        y += 0.97
    return [s, s2]


def tactics_slide():
    Q = g.RM["combined"]["qa_feasible"]
    C1, C2 = g.C1, g.C2
    s = Slide("DP1 보완 설계 택틱 - 제안 (선택 구조 C2 기준)")
    cols = [("#", 0.4, 0.45), ("약점 (평가 근거)", 0.85, 3.2), ("보완 택틱", 4.05, 5.0), ("개선 QA", 9.05, 1.0), ("검증 상태", 10.05, 2.85)]
    for name, x, w in cols:
        s.box(x, 1.2, w, 0.34, name, "head", 9, True, "ctr", False)
    rows = [
        ("W1", f"QA4: 신규 AI data class 추가 시 C2 module {g.QA4['scenarios']['S2']['C2']['modules']}개(C1 {g.QA4['scenarios']['S2']['C1']['modules']}개), 신규 memory는 선호 목록에 명시해야 사용됨(C1은 코드 변경 없이 사용)",
         "T1 type 특성을 descriptor(데이터)로 외부화. descriptor가 없는 class는 type-agnostic 경로로 처리 -> 신규 type 추가 = descriptor 1개", "QA4", "[C] 논증, 미구현. 기대: 변경 module 3 -> 1~2 (미검증)"),
        ("W2", f"migration 비용: C2 {Q[C2]['migration_gib']:,.0f} GiB (C1 {Q[C1]['migration_gib']:,.0f}), 링크 점유 {Q[C2]['migration_link_frac']*100:.1f}% (C1 {Q[C1]['migration_link_frac']*100:.1f}%)",
         "T2 link-time budget + 이득/비용 gating (simulator 적용). traffic class 우선순위(demand > prefetch > demotion). replica가 있으면 DROP 우선", "QA1 QA2", "budget/gating [B] 적용. class 우선순위·DROP 우선은 [C]"),
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
    jobs = [("DP1-appendix-qa-result.pptx", qa_slides()), ("DP1-complement-design-tactics.pptx", [tactics_slide()])]
    for name, sls in jobs:
        build(sls, a.out_dir / name, base)
        print("wrote", a.out_dir / name, len(sls), "slide(s)")
        if a.preview_dir:
            a.preview_dir.mkdir(parents=True, exist_ok=True)
            for i, sl in enumerate(sls):
                preview(sl, a.preview_dir / f"{name[:-5]}-{i + 1}.png")


if __name__ == "__main__":
    main()
