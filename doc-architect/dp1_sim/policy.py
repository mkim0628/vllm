"""정책 추상화와 공유 산술 — 구현 UML §2.1.

`TierScorer`와 `FeasibilityFilter`는 C1과 C2가 **같은 인스턴스**를 쓴다.
산술을 공유하지 않으면 비교가 "누가 Heuristic을 더 잘 썼는지"를 재게 된다
(구현 UML §0).
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass

from .core import (
    AllocationRequest,
    DecisionPoint,
    MemorySpec,
    MemoryStateView,
    ModelShape,
    ReactivationMode,
)


@dataclass
class PlacementDecision:
    memory_name: str
    decided_at: DecisionPoint
    mode: ReactivationMode
    reason: str
    candidates_scored: int = 0      # M-P5: 이 결정에서 실제로 채점한 후보 수


class FeasibilityFilter:
    """결정점에 따라 후보 범위를 정한다 (설계 문서 §1).

    구현 UML 검수(U3)의 권고안 A를 따른다 — **정책이 아니라
    `PlacementManager`가 정책 호출 전에 적용**한다. 그래야 두 후보가
    동일한 후보 집합을 받는 것이 구조적으로 보장된다.

    Capacity/Endurance/원시 연산만 판정하고 Load는 포함하지 않는다.
    Load는 비용이지 feasibility가 아니다.
    """

    def __init__(self, model: ModelShape, step_budget_s: float):
        self.model = model
        self.step_budget_s = step_budget_s

    def filter(
        self, memories: list[MemorySpec], request: AllocationRequest, view: MemoryStateView
    ) -> list[MemorySpec]:
        kv_bytes = request.block_set.total_bytes
        out = []
        for spec in memories:
            headroom = view.capacity_headroom_of(spec.name)
            # 이미 이 메모리에 있는 세션이면 자기 자리는 여유로 친다
            if request.block_set.placed_at == spec.name:
                headroom += kv_bytes
            if headroom < kv_bytes:
                continue
            if request.decision_point is DecisionPoint.PREFILL_COMPLETE:
                # 결정점 A — Decode Attention을 감당할 수 있는 메모리만.
                # DRAM/HBF/SSD-PIM은 여기서 탈락한다: 연산 기능이 없어
                # Decode 때 되가져와야 하므로 순손실이다.
                if not (
                    spec.gpu_reachable
                    or spec.can_serve_decode_attention(
                        self.model, kv_bytes, headroom, self.step_budget_s
                    )
                ):
                    continue
            out.append(spec)
        return out


class TierScorer:
    """§7 C1의 Tier Scoring. C1의 Planner와 C2의 Refiner가 공유한다.

    네 항의 가중치는 **두 후보에 동일하게** 적용된다. 가중치 선택 자체가
    결과에 영향을 주지만, 같은 값을 쓰는 한 후보 간 비교는 성립한다.
    """

    W_CAPACITY = 0.25
    W_BANDWIDTH = 0.25
    W_COMPUTE = 0.25
    W_LOAD = 0.25

    def __init__(self, model: ModelShape, max_ext_bw: float, step_budget_s: float):
        self.model = model
        self.max_ext_bw = max_ext_bw
        self.step_budget_s = step_budget_s

    def capacity_term(self, spec: MemorySpec, view: MemoryStateView, demand: int) -> float:
        headroom = view.capacity_headroom_of(spec.name)
        return min(1.0, headroom / max(1, demand * 4))

    def bandwidth_term(self, spec: MemorySpec) -> float:
        """재활성 시 KV가 GPU 쪽으로 오는 경로의 대역폭."""
        return spec.ext_bw_bytes_per_s / self.max_ext_bw

    def compute_term(self, spec: MemorySpec, request: AllocationRequest, view: MemoryStateView) -> float:
        """Compute Capability를 **가점으로만** 반영한다.

        이것이 §7 C1 단점("Operation-Compute capability 간 적합성 판단에 한계")의
        구현 레벨 근거다 — "이 KV가 곧 Attention을 받으므로 연산형 메모리에
        두면 링크를 안 건넌다"는 판단이 여기서 나오지 않는다.
        """
        kv = request.block_set.total_bytes
        headroom = view.capacity_headroom_of(spec.name)
        if spec.can_serve_decode_attention(self.model, kv, headroom, self.step_budget_s):
            return 1.0
        return 0.0

    def load_term(self, spec: MemorySpec, view: MemoryStateView) -> float:
        return 1.0 - view.load_of(spec.name)

    def score(self, spec: MemorySpec, request: AllocationRequest, view: MemoryStateView) -> float:
        demand = request.block_set.total_bytes
        return (
            self.W_CAPACITY * self.capacity_term(spec, view, demand)
            + self.W_BANDWIDTH * self.bandwidth_term(spec)
            + self.W_COMPUTE * self.compute_term(spec, request, view)
            + self.W_LOAD * self.load_term(spec, view)
        )


class PlacementPolicy(ABC):
    """C1/C2/As-Is가 구현하는 공통 인터페이스."""

    name: str = "abstract"

    @abstractmethod
    def place(
        self,
        request: AllocationRequest,
        candidates: list[MemorySpec],
        view: MemoryStateView,
    ) -> PlacementDecision:
        """이미 feasibility로 좁혀진 후보 집합을 받는다."""

    # 정책이 쓴 협력 객체 호출 횟수 — M-P5의 원자료
    def decision_ops(self) -> int:
        return 0


class PlacementExecutor:
    """결정을 실제 메모리 상태에 반영하고 이동 비용을 계산한다."""

    def __init__(self, view: MemoryStateView, model: ModelShape):
        self.view = view
        self.model = model

    def execute(self, decision: PlacementDecision, block_set, gpu) -> float:
        """이동 시간(초)을 반환한다. 제자리면 0."""
        src = block_set.placed_at
        dst = decision.memory_name
        if src == dst:
            block_set.mode = decision.mode
            return 0.0

        move_s = 0.0
        if src is not None:
            self.view.release(src, block_set.total_bytes)
            move_s += self.view.spec(src).transfer_seconds(block_set.total_bytes)
        dst_spec = self.view.spec(dst)
        move_s += dst_spec.write_seconds(block_set.total_bytes)
        self.view.allocate(dst, block_set.total_bytes)
        self.view.charge_write(dst, block_set.total_bytes)
        block_set.placed_at = dst
        block_set.mode = decision.mode
        return move_s
