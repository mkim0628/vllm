"""배치 정책 — 이름으로 고른다.

DP1의 두 후보는 각각 여러 형태를 가질 수 있다. 어느 형태로 측정했는지가
결론을 좌우하므로, 형태마다 이름을 붙이고 **무엇이 최선 형태(steelman)인지**
명시한다.

    from dp1.policies import build, POLICIES
    placer = build("c2-steelman", table)
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from .model import TierTable
from .object_indexed import CostModel, HeuristicClassifier, ObjectIndexedPlacer
from .tier_indexed import TierIndexedPlacer


@dataclass(frozen=True)
class Policy:
    key: str
    label: str
    candidate: str          # "C1" | "C2"
    steelman: bool          # 이 후보의 최선 형태인가
    note: str
    build: Callable[[TierTable], object]


POLICIES: dict[str, Policy] = {}


def _reg(p: Policy) -> None:
    POLICIES[p.key] = p


# -- Candidate 1 ------------------------------------------------------------
_reg(Policy(
    "c1", "C1 Tier-Indexed", "C1", False,
    "기본형. 자원 상태 점수의 argmax, 유보 A(스텝 내 예약) 있음.",
    lambda t: TierIndexedPlacer(t),
))
_reg(Policy(
    "c1-steelman", "C1 + 컨텍스트 길이 보강", "C1", True,
    "11장에서 선택한 최종 구조. 관측 가능한 컨텍스트 길이를 score의 한 항으로 "
    "넣는다. 단일 진실 원천은 여전히 TierTable 하나이므로 혼합이 아니다.",
    lambda t: TierIndexedPlacer(t, context_length_term=True),
))
_reg(Policy(
    "c1-no-reserve", "C1 유보 A 없음", "C1", False,
    "비교용 결함 형태. 스텝 내 예약이 없어 자기 불변식(자원 제약)을 어긴다.",
    lambda t: TierIndexedPlacer(t, reserve_within_step=False),
))

# -- Candidate 2 ------------------------------------------------------------
_reg(Policy(
    "c2-contract", "C2 고정 계약", "C2", False,
    "초기 형태. 등급 → tier 고정 매핑. tier 상태가 아래로만 작용한다 "
    "(목표가 차면 내려가지만 위가 비어도 올라가지 않는다).",
    lambda t: ObjectIndexedPlacer(t),
))
_reg(Policy(
    "c2-naive-upgrade", "C2 상향(구멍)", "C2", False,
    "결함 형태. '빈자리 있으면 위로' 이진 규칙 — 등급도 크기도 보지 않는다. "
    "여기서 나온 크기 편향은 구조가 아니라 구현 아티팩트다.",
    lambda t: ObjectIndexedPlacer(t, upgrade_if_free=True),
))
_reg(Policy(
    "c2-cost", "C2 비용 모델 (유보 B 없음)", "C2", False,
    "블록 단위 가치-가격 모델. 크기가 상쇄된다. 다만 빈 tier의 값이 0이라 "
    "먼저 온 저강도 요청이 상위 tier를 채워 구분 능력이 C1과 같아진다.",
    lambda t: ObjectIndexedPlacer(t, cost_model=CostModel()),
))
_reg(Policy(
    "c2-steelman", "C2 비용 모델 + 유보 B", "C2", True,
    "C2의 최선 형태. 비용 모델 + 미래를 위한 유보. 구분 능력이 크게 오르는 "
    "대신 저부하 구간에서 빠른 tier를 비워 둔다.",
    lambda t: ObjectIndexedPlacer(t, cost_model=CostModel(reserve_for_future=True)),
))
_reg(Policy(
    "c2-mimic-c1", "C2가 C1 흉내", "C2", False,
    "상위호환 반박용. C1의 정책을 그대로 쓰면 배치는 같아지지만 분류 비용은 "
    "남는다 — C1보다 비싼 C1.",
    lambda t: ObjectIndexedPlacer(
        t, HeuristicClassifier(single_class=True), mimic_c1=True),
))


def build(key: str, table: TierTable):
    if key not in POLICIES:
        raise KeyError(f"알 수 없는 정책: {key}  (가능: {', '.join(POLICIES)})")
    return POLICIES[key].build(table)


def steelman_pair() -> tuple[str, str]:
    """두 후보의 최선 형태 키. 정직한 트레이드오프는 이 둘로 비교한다."""
    return "c1-steelman", "c2-steelman"
