"""As-Is 기준선 — HBM 우선 유지 + 순차 Spill.

설계 문서 §11.6이 정규화 기준선으로 삼는 정책이다. 데이터 특성도
메모리 특성도 보지 않고 **고정된 계층 순서**로만 내려간다.

C1-C2 간 격차보다 "정책이 있는가 없는가"의 격차가 더 클 수 있으므로
(§11.4), 이 기준선 없이는 두 후보의 차이를 해석할 수 없다.
"""

from __future__ import annotations

from ..core import AllocationRequest, MemorySpec, MemoryStateView, ModelShape
from ..policy import PlacementDecision, PlacementPolicy


class AsIsPolicy(PlacementPolicy):
    name = "as-is"

    #: 고정 Spill 순서. 빠른 것부터 채우고 넘치면 다음으로 내린다.
    SPILL_ORDER = ["hbm", "custom_hbm", "hbf", "dram", "cxl_pnm", "ssd_pim"]

    def __init__(self, model: ModelShape, step_budget_s: float):
        self.model = model
        self.step_budget_s = step_budget_s
        self._ops = 0

    def place(
        self, request: AllocationRequest, candidates: list[MemorySpec], view: MemoryStateView
    ) -> PlacementDecision:
        by_name = {s.name: s for s in candidates}
        kv = request.block_set.total_bytes
        for name in self.SPILL_ORDER:
            spec = by_name.get(name)
            if spec is None:
                continue
            self._ops += 1
            headroom = view.capacity_headroom_of(name)
            if request.block_set.placed_at == name:
                headroom += kv
            if headroom >= kv:
                mode = spec.reactivation_mode_for(self.model, kv, headroom, self.step_budget_s)
                return PlacementDecision(name, request.decision_point, mode,
                                         "as-is: first fit in fixed spill order", 1)
        spec = candidates[-1]
        self._ops += 1
        mode = spec.reactivation_mode_for(
            self.model, kv, view.capacity_headroom_of(spec.name), self.step_budget_s)
        return PlacementDecision(spec.name, request.decision_point, mode, "as-is: last resort", 1)

    def decision_ops(self) -> int:
        return self._ops
