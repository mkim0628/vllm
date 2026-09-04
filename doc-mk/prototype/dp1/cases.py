"""케이스 카탈로그 — 무엇을 재현하고, 무엇을 봐야 하는가.

각 케이스는 DP1 문서의 특정 주장 하나에 대응한다.

    python -m dp1.cases                 # 카탈로그 출력
    python -m dp1.run_experiment burst  # 케이스 하나 실행
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from . import workload
from .workload import Scenario


@dataclass(frozen=True)
class Case:
    key: str
    build: Callable[[], Scenario]
    doc_ref: str      # 문서 어느 절을 검증하나
    reproduces: str   # 무엇을 재현하나
    watch: str        # 어느 지표를 봐야 하나
    expect: str       # 무엇이 나와야 하나
    test: str         # 대응 테스트


CASES: dict[str, Case] = {c.key: c for c in [
    Case(
        "homogeneous", workload.homogeneous,
        "9장 선택 조건",
        "요청 간 편차가 작은 균질 워크로드 (프롬프트 1024 · 출력 256, 40건)",
        "separation · bw_match",
        "두 후보 모두 separation 1.00 — 구분의 이득이 사라진다. "
        "C1을 선택할 근거가 되는 조건.",
        "TestQA1PlacementQuality.test_separation_gain_vanishes_on_homogeneous_workload",
    ),
    Case(
        "heterogeneous", workload.heterogeneous,
        "QA1 배치 품질 / 부록 D.3",
        "long-context 6건(32768 토큰) + 짧은 요청 48건(512 토큰)",
        "separation · bw_match",
        "c2-steelman 8.40 vs c1 2.06 — C2의 구분 이득이 나오는 유일한 조건. "
        "유보 B를 끄면(c2-cost) 2.11로 떨어져 이득이 0이 된다.",
        "TestQA1PlacementQuality.test_c2_separates_hot_and_cold_on_heterogeneous_workload",
    ),
    Case(
        "burst", workload.burst,
        "QA3 적응성 / 발견 ③",
        "한 스텝에 200건 동시 도착 (max_num_seqs 128을 넘김)",
        "overcommit · herding_1st",
        "유보 A가 없으면 두 후보 모두 overcommit 72회 · herding 1.00. "
        "유보 A를 켜면 0회. 정합성 요건임을 보이는 케이스.",
        "TestQA3Adaptivity.test_reservation_counter_is_required_to_hold_c1_invariant",
    ),
    Case(
        "misclassification", workload.misclassification,
        "QA3 오분류 고착 / 부록 D.4",
        "max_tokens는 크게 잡았지만 100토큰에서 끝나는 요청 8건과 그 반대 8건",
        "separation (1.00 미만이면 역전)",
        "c2-contract에서 0.43 — 실제로 오래 사는 요청이 더 느린 tier를 받는다. "
        "C1은 1.00(구분 못 하지만 역전도 없음).",
        "TestQA3Adaptivity.test_c2_grade_is_sticky_and_can_invert_the_right_answer",
    ),
    Case(
        "shared_prefix", workload.shared_prefix,
        "QA3 예측 대상 오류",
        "같은 system prompt를 공유하는 100건 (최초 소유자는 cold, 이후 30건은 hot)",
        "shared_viol",
        "c2-contract에서 99건 — cold 소유자가 놓은 자리에 hot 요청들이 묶여 "
        "계약이 조용히 깨진다. C1은 계약이 없어 0건.",
        "TestQA3Adaptivity.test_shared_prefix_breaks_the_c2_contract_silently",
    ),
    Case(
        "invariant_conflict", lambda: workload.invariant_conflict()[0],
        "3.3-① 불변식 충돌",
        "상위 tier를 정확히 채운 뒤 더 높은 등급의 요청 1건 도착",
        "hot_arrival의 배치 tier · evictions",
        "C1 → CUSTOM_HBM, 축출 0 (자원 제약이 이긴다). "
        "c2-contract → HBM, 축출 발생 (객체 계약이 이긴다). 결정이 정반대.",
        "TestExclusivity.test_invariant_conflict_gives_opposite_decisions",
    ),
]}


def _fmt() -> str:
    out = []
    for c in CASES.values():
        out.append(f"■ {c.key}")
        out.append(f"    문서      {c.doc_ref}")
        out.append(f"    재현      {c.reproduces}")
        out.append(f"    볼 지표   {c.watch}")
        out.append(f"    기대      {c.expect}")
        out.append(f"    테스트    {c.test}")
        out.append(f"    실행      python -m dp1.run_experiment {c.key}")
        out.append("")
    return "\n".join(out)


if __name__ == "__main__":
    print("\nDP1 케이스 카탈로그 — 각 케이스는 문서의 주장 하나에 대응한다\n")
    print(_fmt())
