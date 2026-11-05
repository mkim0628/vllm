"""DP3(CXL 메모리 풀) Q3 확장성 측정 방법 1장. 풀이 실구현되지 않아, Target 1노드의 CXL-PNM 4카드를 작은 풀로 보고
GPU를 늘리며 경합을 실측한 뒤 σ를 피팅해 외삽한다. 사용: python build_dp3_q3.py <in.pptx> <out.pptx>"""
import sys
from pptx import Presentation
from pptx.enum.shapes import MSO_SHAPE
from pptx.enum.text import PP_ALIGN
from pptx.util import Inches

import build_deck as B
from build_deck import textbox, rect, table, new_slide, key_box, GRAY


def head(s, x, y, w, text, color="595959"):
    rect(s, x, y, w, 0.26, color)
    textbox(s, x + 0.05, y + 0.02, w - 0.1, 0.22, text, 10, True, "FFFFFF")


def arrow(s, x, y, w=0.4, h=0.28):
    a = s.shapes.add_shape(MSO_SHAPE.RIGHT_ARROW, Inches(x), Inches(y), Inches(w), Inches(h))
    a.fill.solid(); a.fill.fore_color.rgb = B.rgb("7F7F7F"); a.line.fill.background(); a.shadow.inherit = False


def config_row(s, y, n_active):
    textbox(s, 0.27, y + 0.1, 1.1, 0.4, f"GPU {n_active}개 활성", 9.5, True, "404040")
    for i in range(4):                       # GPU 4개
        on = i < n_active
        r = rect(s, 1.4 + i * 0.62, y, 0.54, 0.45, "2E75B6" if on else "D9D9D9")
        textbox(s, 1.4 + i * 0.62, y + 0.1, 0.54, 0.25, f"GPU{i}", 8, True, "FFFFFF" if on else "7F7F7F", PP_ALIGN.CENTER)
    arrow(s, 3.95, y + 0.08, 0.45, 0.28)
    rect(s, 4.5, y - 0.05, 2.0, 0.55, "FFF2CC", "BF9000", line_w=0.8)       # CXL-PNM 4카드(공유)
    for i in range(4):
        rect(s, 4.58 + i * 0.47, y + 0.05, 0.4, 0.35, "BF9000")
        textbox(s, 4.58 + i * 0.47, y + 0.12, 0.4, 0.2, f"C{i}", 8, True, "FFFFFF", PP_ALIGN.CENTER)


def build(src, dst):
    prs = Presentation(src)
    tmpl = prs.slides[1]
    layout = tmpl.slide_layout
    names = {sh.name: sh for sh in tmpl.shapes}
    nav = [names[n] for n in ("Chevron 2", "Chevron 3", "Chevron 4", "Chevron 5", "Chevron 6", "Rectangle 7", "Rectangle 8")]
    n_old = len(prs.slides)
    s = new_slide(prs, layout, nav, "DP3. CXL 메모리 풀 - Q3 확장성 측정 방법")
    key_box(s, "핵심", "CXL 메모리 풀은 실구현이 없다. Target 1노드의 CXL-PNM 4카드를 '작은 풀'로 보고 GPU를 1·2·4개로 늘려 경합을 실측한 뒤, "
                       "그 적은 측정점으로 σ를 구해 풀을 공유하는 GPU가 늘어날 때의 SE를 외삽한다 [C].", h=0.6)

    head(s, 0.27, 1.4, 6.3, "① 측정: Target 1노드 (GPU 4 + CXL-PNM 4카드 공유)")
    for i, n in enumerate((1, 2, 4)):
        config_row(s, 1.85 + i * 0.75, n)
    textbox(s, 0.27, 4.1, 6.3, 0.45, "GPU 수에 비례해 요청률을 올리고, CXL 카드 4개와 KV 배치는 고정. 구성마다 5회 반복해 Goodput(SLO 만족 처리량)을 잰다.", 9, False, "404040")
    rows = [["활성 GPU N", "Goodput", "SE(N) = G(N) ÷ (N·G(1))"], ["1", "G(1)", "기준 (100%)"], ["2", "G(2)", "G(2) ÷ (2·G(1))"], ["4", "G(4)", "G(4) ÷ (4·G(1))"]]
    table(s, 0.27, 4.6, [1.4, 1.6, 3.3], rows, [0.26] + [0.28] * 3, 9, aligns=[PP_ALIGN.CENTER] * 3, header_bold=False)

    head(s, 6.85, 1.4, 6.25, "② 피팅: 측정한 SE로 σ를 구한다")
    textbox(s, 6.85, 1.7, 6.25, 0.85, [
        "• SE(N) = 1 / (1 + σ(N−1)) → σ = (1/SE − 1) / (N−1)",
        "• N=2, N=4 두 점에서 각각 σ를 구해 평균하고, 반복 측정으로 신뢰구간을 낸다",
        "• σ = 풀(CXL 카드)을 여러 GPU가 공유하며 생기는 직렬 경합 비중"], 9, False, "404040")

    head(s, 6.85, 2.65, 6.25, "③ 외삽: 풀을 공유하는 GPU 수를 늘리면", "C00000")
    sig = (0.003, 0.005, 0.01)
    se = lambda sg, n: 100 / (1 + sg * (n - 1))
    rows = [["피팅 σ (예시)", "SE(4) 실측권", "SE(16) 외삽", "SE(64) 외삽"]] + [[f"{x*100:.1f}%", f"{se(x, 4):.1f}%", f"{se(x, 16):.1f}%", f"{se(x, 64):.1f}%"] for x in sig]
    table(s, 6.85, 2.95, [1.6, 1.5, 1.6, 1.55], rows, [0.26] + [0.28] * 3, 9, aligns=[PP_ALIGN.CENTER] * 4, header_bold=False)
    textbox(s, 6.85, 4.1, 6.25, 0.9, [
        "• 4 GPU까지만 측정하고 16·64 GPU는 σ가 일정하다고 가정해 계산한다",
        "• 별 판정은 σ 기준: ★ ≤ 0.74%, ★★★ ≤ 0.35% (QA-03과 동일, 제안)"], 9, False, "404040")

    head(s, 6.85, 5.0, 6.25, "한계", "7F7F7F")
    textbox(s, 6.85, 5.28, 6.25, 1.3, [
        "• 측정점이 3개(1·2·4 GPU)뿐이고 외삽 폭이 4배~16배로 커서 불확실성이 큼 → 신뢰구간 병기",
        "• 스위치·패브릭 지연, 풀 관리 SW 비용, 혼잡 급증(κ)은 반영 못 해 낙관적일 수 있음",
        "• 풀 크기를 GPU 수에 비례해 늘린다고 가정"], 9, False, "404040")
    textbox(s, 0.27, 6.62, 12.83, 0.4, "σ 예시값은 설명용 가정이며 실측값이 아니다. 노드 간 풀은 별도로 에뮬레이션(원격 DRAM의 지연·대역폭 제한)이나 모델로 보완한다.", 7.5, False, GRAY)
    textbox(s, 5.85, 7.2, 1.6, 0.24, "1 / 1", 10, False, GRAY, PP_ALIGN.CENTER)

    lst = prs.slides._sldIdLst
    for sldId in list(lst)[:n_old]:
        prs.part.drop_rel(sldId.rId)
        lst.remove(sldId)
    prs.save(dst)


if __name__ == "__main__":
    build(sys.argv[1], sys.argv[2])
