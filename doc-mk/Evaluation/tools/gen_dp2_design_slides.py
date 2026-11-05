#!/usr/bin/env python3
"""DP2 design slides: (1) Cost Model composition, (2) C2 state storage / Late Validation / mismatch handling.
    python tools/gen_dp2_design_slides.py --out-dir doc-mk/DP2 [--preview-dir DIR]
Content mirrors doc-mk/DP2/dp2-cost-model-and-late-validation.md and sim/dp2sim/policies.py (Cost v2), engine.py (c2_validate)."""
import argparse
import inspect
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import gen_dp_pptx as base  # noqa: E402

Slide, preview = base.Slide, base.preview
HEADER = "DP2. Cost 기반 Prefill/Decode 실행 계획 - 설계 보충"
exec(compile(inspect.getsource(base.build).replace("DP1. 이기종 메모리 기반 Data Migration 구조 - Appendix", HEADER), "b", "exec"), base.__dict__, base.__dict__)
build = base.__dict__["build"]


def cost_slide():
    s = Slide("Cost Model - 무엇이고 어떤 항으로 이루어지나")
    s.box(0.4, 1.15, 12.5, 0.62, ["Cost(n_p, n_d) = 이 plan이 요청에 주는 SLO 소모량 + 다른 요청에 주는 SLO 소모량.  모든 항을 SLO 분율(무차원)로 맞춰 TTFT와 TPOT를 같은 척도로 더한다.",
                                  "n_p = Prefill 실행 노드,  n_d = Decode 시작 위치 (노드, Tier).  후보 (n_p, n_d) 전부의 Cost를 계산해 최소를 고른다."], "sel", 10)
    cols = [("구분", 0.4, 1.6), ("항", 2.0, 2.6), ("의미 / 계산", 4.6, 4.6), ("입력 (Resource Intelligence)", 9.2, 3.7)]
    for n, x, w in cols:
        s.box(x, 1.9, w, 0.32, n, "head", 10, True, "ctr", False)
    rows = [
        ("이 요청의 TTFT", "TTFT_est / SLO_TTFT", "대기(wait) + History 전송·승격(stage) + Prefill 시간.  Prefill은 chunk 단위 iteration 시간 x 횟수", "n_p의 대기 Prefill 토큰·작업 수, 실행 중 Decode, History KV 위치(Tier), Tier·링크 BW"),
        ("이 요청의 TPOT", "TPOT_est / SLO_TPOT", "n_d에 합류한 뒤의 iteration 시간.  Tier별 attention 경로(GPU HBM, HBF 직접 읽기, ScHBM·CXL-PNM 오프로드)가 다름", "n_d의 Tier별 Decode 수·컨텍스트 합, Tier descriptor(BW·지연·연산 능력)"),
        ("KV 이동", "T_handoff / (N_out-1) / SLO_TPOT", "Prefill 결과 KV를 n_p에서 n_d로 보내는 시간(첫 Decode 지연)을 출력 토큰에 나눠 반영.  HBM evict 시 내리는 시간도 포함", "노드 간 링크·Tier 읽기의 동시 흐름 수(공정 분배 BW), KV 크기"),
        ("외부효과 X1", "n_p의 실행 중 Decode 지연 / SLO_TPOT", "이 Prefill이 n_p에서 이미 Decode 중인 요청의 iteration을 늘린 만큼", "n_p의 Decode 수·컨텍스트"),
        ("외부효과 X2", "이후 도착 요청의 TTFT 지연 / SLO_TTFT", "이 Prefill이 n_p를 점유해 뒤따라 오는 요청이 기다리는 시간 (도착률 x Prefill 시간^2 / 2)", "n_p의 최근 도착률(EWMA)"),
        ("외부효과 X3", "n_d의 resident Decode 지연 / SLO_TPOT", "이 요청이 합류해 n_d의 기존 Decode들이 느려지는 만큼", "n_d의 Decode 수·컨텍스트"),
    ]
    y = 2.26
    for r in rows:
        for (n, x, w), v in zip(cols, r):
            s.box(x, y, w, 0.62, v, "dp" if n == "구분" else "cell", 8.5, n == "구분", "l", False)
        y += 0.65
    s.box(0.4, y + 0.05, 4.1, 1.15, ["제약 (feasible 후보만)", "- n_d에 이 요청의 KV 용량이 들어감 (HBM은 evict 가능한 idle KV 포함)", "- TTFT_est ≤ SLO, TPOT_est ≤ SLO", "- feasible 후보가 없으면 위반 최소 후보"], "note", 8.5)
    s.box(4.6, y + 0.05, 4.1, 1.15, ["선택", "- (n_p, n_d) 쌍 전체 Cost를 계산해 argmin (n_p 후보 클래스: History 소유 노드, n_d 자신, 최선 다른 노드)", "- 상위 4개를 순위로 보관, 2~4위는 C2의 백업 후보"], "note", 8.5)
    s.box(8.8, y + 0.05, 4.1, 1.15, ["C1·C2 공통, 교체 가능", "- 같은 Cost Model, 다른 점은 계산 시점·상태 신선도·lifecycle", "- Cost 항 추가는 Cost Evaluator(Strategy) 한 곳 (QA4 S2 측정: 1 module)", "- 추정 오차 ε는 lognormal로 민감도 평가"], "c2", 8.5)
    return s


def valid_slide():
    s = Slide("C2 - Plan에 저장하는 상태값과 Late Validation, mismatch 처리")
    s.box(0.4, 1.15, 12.5, 0.5, ["plan을 만들 때 의존한 상태를 함께 저장하고, dispatch 직전에 현재 상태와 비교한다.  \"시간이 얼마나 지났나\"가 아니라 \"상태가 얼마나 달라졌나\"를 본다."], "sel", 10)
    # column 1: stored state
    s.box(0.4, 1.78, 4.1, 0.32, "1. 저장하는 상태값 (후보별: 선택 plan + 백업)", "head", 9.5, True, "ctr", False)
    st = [("n_p 노드", "pf_tokens(대기 Prefill 토큰), njobs, ndec(실행 중 Decode 수)"),
          ("n_d (노드, Tier)", "free(Tier 여유 용량), ndec(resident Decode 수)"),
          ("전송 경로", "경로 자원의 동시 흐름 수(flows)"),
          ("후보별 Cost", "저장 시점의 Cost (선택 plan, 백업 각각)"),
          ("요청·세션", "History KV 위치 (node, tier)"),
          ("제외", "도착률 EWMA(노이즈), plan age는 판정에 안 씀")]
    y = 2.14
    for a, b in st:
        s.box(0.4, y, 1.2, 0.56, a, "dp", 8.5, True, "l", False)
        s.box(1.6, y, 2.9, 0.56, b, "cell", 8.5, False, "l", False)
        y += 0.58
    # column 2: validation
    s.box(4.7, 1.78, 4.1, 0.32, "2. dispatch 직전 검증 (후보 순서대로)", "head", 9.5, True, "ctr", False)
    s.box(4.7, 2.14, 4.1, 1.55, ["Hard (하나라도 어긋나면 그 후보 무효)", "- 노드 health 정상", "- n_d 용량: 이 요청 KV가 아직 들어감", "- History KV 위치가 저장 시점과 같음", "- n_p 노드 큐가 한도(16K 토큰) 미만"], "cell", 8.5)
    s.box(4.7, 3.73, 4.1, 1.5, ["Soft (상태 유사도)", "- 현재 상태로 같은 plan의 Cost를 다시 계산", "- Cost_now ≤ Cost_저장 x (1 + tol) 이면 유효", "- tol 기본 10% (5 / 10 / 20% 민감도)", "- Cost가 줄어든 변화는 허용"], "cell", 8.5)
    s.box(4.7, 5.27, 4.1, 0.8, ["한계: 저장한 후보 밖의 노드가 더 좋아진 경우는 못 잡는다.  \"현재 상태\"는 telemetry snapshot이라 갱신 주기만큼 늦다."], "warn", 8.5)
    # column 3: mismatch
    s.box(9.0, 1.78, 3.9, 0.32, "3. mismatch 시 처리", "head", 9.5, True, "ctr", False)
    steps = [("① 선택 plan 무효", "저장 순위 2위 백업 후보로 같은 검증"),
             ("② 백업도 무효", "순위 3, 4위 백업을 차례로 검증"),
             ("③ 모두 무효", "Re-planner가 최신 상태로 동기 재계획 (C1과 같은 결정 비용, Scheduler 직렬)"),
             ("④ 재계획도 후보 없음", "요청을 대기열 앞으로 되돌리고 계획을 다시 요청, 최종 실패 시 기존 vLLM GPU 경로(안전 경로)"),
             ("통과", "해당 plan으로 dispatch, 검증 비용 20 us(ASSUMED)")]
    y = 2.14
    for a, b in steps:
        s.box(9.0, y, 1.35, 0.72, a, "c2" if a != "통과" else "sel", 8.5, True, "l", False)
        s.box(10.35, y, 2.55, 0.72, b, "cell", 8.5, False, "l", False)
        y += 0.75
    s.box(0.4, 6.15, 12.5, 0.85, ["평가 결과 (시뮬레이션 [B+C], H100): 기본 조건(plan age 약 4 ms)에서는 기존 검증(age 2 s·큐·용량)과 차이가 없다(goodput x1.41~1.43).  N=16/32처럼 결정이 느린 조건에서는 tol이 작을수록 재계획이 늘어(1% -> 27~37%) goodput이 x0.75~0.84로 떨어진다. 재계획이 C1과 같은 직렬 결정 비용을 내 C2의 이점이 사라지기 때문이다.  -> 재계획을 싼 경로(백업 후보 확대, top-k 재평가)로 두는 설계가 필요하다(미평가)."], "warn", 8.5)
    return s


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out-dir", type=Path, default=HERE.parent.parent / "DP2")
    ap.add_argument("--preview-dir", type=Path, default=None)
    a = ap.parse_args()
    tmpl = HERE.parent.parent / "DP1" / "DP-memory-backend-if.pptx"
    sls = [cost_slide(), valid_slide()]
    out = a.out_dir / "DP2-cost-model-late-validation.pptx"
    build(sls, out, tmpl)
    print("wrote", out)
    if a.preview_dir:
        a.preview_dir.mkdir(parents=True, exist_ok=True)
        for i, sl in enumerate(sls):
            preview(sl, a.preview_dir / f"dsg-{i + 1}.png")


if __name__ == "__main__":
    main()
