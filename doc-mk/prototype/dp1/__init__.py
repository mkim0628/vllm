"""DP1 — Memory Placement Decision Basis 후보 구조 프로토타입.

vLLM 코어를 수정하지 않는다. DP1의 배치 결정 로직만 떼어내 독립 실행 가능한
형태로 구현하고, 문서의 정량 주장을 실측 가능한 형태로 만든다.
"""

from .model import (  # noqa: F401
    BLOCK_TOKENS,
    DEFAULT_TIERS,
    AnonymityViolation,
    Decision,
    ObservableRequest,
    Oracle,
    Placement,
    Request,
    TierSpec,
    TierTable,
    TripwireView,
)
from .object_indexed import (  # noqa: F401
    ClassTierContract,
    HeuristicClassifier,
    ObjectIndexedPlacer,
)
from .tier_indexed import TierIndexedPlacer  # noqa: F401

__all__ = [
    "BLOCK_TOKENS", "DEFAULT_TIERS", "AnonymityViolation", "Decision",
    "ObservableRequest", "Oracle", "Placement", "Request", "TierSpec",
    "TierTable", "TripwireView", "ClassTierContract", "HeuristicClassifier",
    "ObjectIndexedPlacer", "TierIndexedPlacer",
]
