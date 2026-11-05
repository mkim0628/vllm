#!/usr/bin/env python3
"""DP1 책임 경계 한 장: DP1(결정) / 공통 Migration subsystem(mapping·commit) / Device driver(전송·HW 주소 변환).

DP1이 의존하는 보장(G1~G3)과 범위 밖 overhead(O1~O2)를 명시한다. 근거: doc-mk/DP1/dp1-constraints.md 6절(G, O), C-X6, C-X7.
스타일: DP1-final-style-reference.pptx (gen_dp1_arch_views_pptx.py 의 begin/bx/takeaway 재사용).

사용: /usr/local/bin/python3 doc-mk/Evaluation/tools/gen_dp1_responsibility_pptx.py [--ref ...] [--out ...]
"""
import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import gen_c1_complement_styled_pptx as G
import gen_dp1_arch_views_pptx as V
import gen_dp1_exec_flow_pptx as X

T = X.T
OUT = os.path.join(V.OUT_DIR, "DP1-responsibility-boundary.pptx")


def build(ref, out):
    V.reset()
    prs, slide, diag = V.begin(
        ref, ["DP1. ", "책임 경계 ", "(결정 / Migration subsystem / Driver)", " ", "- ", "설계"], ["범위 선언", " · ", "의존하는 보장", " · ", "범위 밖 overhead", "", ""],
        [("DP1의 범위는 이동 결정(WHAT/WHERE) ", 1200, True, None), ("mapping·commit의 신뢰성은 Migration subsystem이 보장하는 것으로 둔다 (DP1의 가정)", 1200, True, G.RED)],
        [("“DP1은 ", 1100, False, None), ("무엇을 어디로", 1100, False, G.LINK_BLUE), (" 결정하고, mapping·commit의 ", 1100, False, None),
         ("신뢰성과 그 overhead는 하위 계층의 영역", 1100, False, G.LINK_BLUE), ("“", 1100, False, None)])
    C0X, C0W = 1150000, 2300000
    C1X, C1W = 3750000, 3100000
    C2X, C2W = 7050000, 2400000
    C3X, C3W = 9650000, 2300000
    for nm, x, w, t in (("h0", C0X, C0W, "계층 (소유)"), ("h1", C1X, C1W, "맡는 것"),
                        ("h2", C2X, C2W, "제공하는 보장 / DP1이 의존하는 것"), ("h3", C3X, C3W, "overhead·비용의 소유")):
        G.add_label(slide, nm, x, 1730000, w, 230000, [[T(t, 800, True)]], algn="ctr", border=G.GRAY_LINE)
    R = [2060000, 3340000, 4620000]
    RH = 1000000

    def row(i, name, fill, line, title, owner, take, guar, cost, cost_color=None):
        y = R[i]
        V.bx(slide, name, C0X, y, C0W, RH, fill, line, [[T(title, 880, True)], [T(owner, 700, False, G.SUBTXT)]])
        G.add_label(slide, f"t{i}", C1X, y, C1W, RH, [[T(x, 700)] for x in take], algn="l", border=G.GRAY_LINE, dash="solid")
        G.add_label(slide, f"g{i}", C2X, y, C2W, RH, [[T(x, 690, k == 0)] for k, x in enumerate(guar)], algn="l", border=G.GRAY_LINE, dash="solid")
        G.add_label(slide, f"c{i}", C3X, y, C3W, RH, [[T(x, 690, k == 0, cost_color if k == 0 else None)] for k, x in enumerate(cost)], algn="l", border=G.GRAY_LINE, dash="solid")

    row(0, "DP1", V.BLUE, V.BLUE_L, "DP1 (Decision Plane)", "결정: 무엇을, 어느 tier로",
        ["이동 대상과 목적지 tier 결정 (정책 C1/C2)", "MigrationIntent 발행 (object · src→dst · action · priority)", "위치는 Registry에서 읽기만 한다 (변경은 commit 결과로만)"],
        ["제공: MigrationIntent", "의존 G1: mapping·commit이 신뢰할 수 있게 동작", "의존 G2: 완료 통지 = target 가시화"],
        ["DP1이 책임지는 비용", "이동량(bytes), 링크 점유 시간, 서빙 간섭", "decision overhead (Selector·Executor 경계까지)", "→ 평가에 반영 (링크 간섭 모델)"], G.RED)
    row(1, "MIG", V.NEW, V.NEW_L, "공통 Migration subsystem", "EngineCore (제어) + Worker (실행), 신규·공통",
        ["logical block id → 물리 위치 관리 (DataLocationStore)", "계획 · 스케줄 · copy 지시", "version 검증 후 atomic commit, 실패 시 source 유지", "SchedulerOutput으로 새 위치를 엔진에 통지", "이동 중 접근 hazard 방지 (epoch · pin · grace)"],
        ["제공 G1 (신뢰성)", "copy-then-commit, atomic commit, rollback", "완료 유실 시 reconciliation", "시험으로 확인할 책임도 이 층"],
        ["범위 밖 O1 (DP1 아님)", "commit 지연, 상태기계 overhead", "epoch grace로 늘어나는 slot 점유", "완료 통지 지연"], G.NEW_LINE)
    row(2, "DRV", V.GRAY, V.GRAY_L, "Device driver / runtime", "CUDA · NVMe · CXL · 벤더 API, 하드웨어",
        ["실제 복사 (DMA, copy engine)", "HW 주소 변환 유지 (page table, IOMMU, HDM decoder)", "remap 시 TLB/ATC 무효화 (기본 경로에서는 불필요)", "완료와 오류 보고"],
        ["제공 G2·G3", "완료 = target 가시화, 오류 전파", "전송 순서·coherency fence, 변환 일관성", "장치별 확인 필요 [가정]"],
        ["범위 밖 O2", "TLB·page-table·driver 호출 비용", "전송 시간 추정은 descriptor로 노출해 DP1의 비용 판단 입력으로 쓴다"], G.NEW_LINE)
    # 계층 사이 화살표 (아래 = 결정/명령, 위 = 읽기/완료)
    for a, b, down_lbl, up_lbl in (("DP1", "MIG", "MigrationIntent", "위치 (읽기)"), ("MIG", "DRV", "Command", "Completion")):
        xa, ya, wa, ha = G.NODES[a]
        xb, yb, wb, hb = G.NODES[b]
        G.arrow(slide, f"dn-{a}", (xa + 500000, ya + ha), (xa + 500000, yb), G.RED if a == "DP1" else G.NEW_LINE, 15000, a, b)
        G.arrow(slide, f"up-{a}", (xa + 1500000, yb), (xa + 1500000, ya + ha), G.GRAY_LINE, 12700, b, a)
        G.add_label(slide, f"dl-{a}", xa + 540000, ya + ha + 60000, 900000, 150000, [[T(down_lbl, 600, True, G.RED if a == "DP1" else G.NEW_LINE)]], algn="l")
        G.add_label(slide, f"ul-{a}", xa + 1540000, ya + ha + 60000, 740000, 150000, [[T(up_lbl, 600, True, G.SUBTXT)]], algn="l")
    G.add_label(slide, "caveat", 1150000, 5730000, 10800000, 330000,
                [[T("주의: 이 선언은 하위 계층이 G1~G3을 만족한다는 가정이다. DP1의 평가 수치([B+C])는 이 overhead가 0이라는 조건부 값이다(C-E1, C-E2). ", 720, True, G.RED),
                  T("G1의 시험·보증은 Migration subsystem의 산출물이다.", 720)]], algn="l", border=G.RED, dash="dash")
    V.takeaway(slide, "DP1은 결정 계층이다. mapping·commit의 신뢰성과 그 overhead는 하위 계층의 영역이며 계약(G1~G3)으로만 의존한다. 설계 단계, 미구현")
    os.makedirs(os.path.dirname(os.path.abspath(out)), exist_ok=True)
    prs.save(out)
    return prs, diag


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--ref", default=G.DEFAULT_REF)
    ap.add_argument("--out", default=OUT)
    a = ap.parse_args()
    prs, diag = build(a.ref, a.out)
    probs = X.verify(prs, diag)
    print("saved:", a.out)
    for p in probs:
        print(" -", p)
    if probs:
        sys.exit(1)
    print("verify OK: bounds / text fit / node overlap / arrow edges")


if __name__ == "__main__":
    main()
