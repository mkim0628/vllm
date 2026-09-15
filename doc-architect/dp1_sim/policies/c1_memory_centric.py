"""C1. 메모리 특성 중심 배치 구조 — 설계 문서 §7 Candidate 1.

구조: Memory State Collector -> Placement Planner(Tier Scoring -> arg max).

**후보를 좁히는 단계가 없다.** feasible한 메모리 전체를 매번 채점한다
(구현 UML §2.2의 "평면(flat)" 구조). `analyzer` 모듈에 의존하지 않으므로
추정 오차가 도달할 경로가 없다.
"""

from __future__ import annotations

from dataclasses import dataclass

from ..core import AllocationRequest, MemorySpec, MemoryStateView, ModelShape
from ..policy import PlacementDecision, PlacementPolicy, TierScorer


@dataclass
class MemoryStateSnapshot:
    """수집한 메모리 상태. Capacity / BW / Compute Capability / Load."""

    capacity: dict
    bandwidth: dict
    compute: dict
    load: dict


class MemoryStateCollector:
    def __init__(self):
        self.ops = 0

    def collect(self, memories: list[MemorySpec], view: MemoryStateView) -> MemoryStateSnapshot:
        self.ops += 1
        return MemoryStateSnapshot(
            capacity={s.name: view.capacity_headroom_of(s.name) for s in memories},
            bandwidth={s.name: s.ext_bw_bytes_per_s for s in memories},
            compute={s.name: s.supports_attention() for s in memories},
            load={s.name: view.load_of(s.name) for s in memories},
        )


class PlacementPlanner:
    """Tier Scoring 후 arg max score로 Best Tier Selection."""

    def __init__(self, scorer: TierScorer):
        self.scorer = scorer
        self.ops = 0

    def tier_scoring(self, candidates, request, view) -> dict:
        scores = {}
        for spec in candidates:
            self.ops += 1
            scores[spec.name] = self.scorer.score(spec, request, view)
        return scores

    def best_tier_selection(self, scores: dict) -> str:
        return max(scores.items(), key=lambda kv: kv[1])[0]


class MemoryCentricPolicy(PlacementPolicy):
    name = "C1-memory-centric"

    def __init__(self, model: ModelShape, scorer: TierScorer, step_budget_s: float):
        self.model = model
        self.step_budget_s = step_budget_s
        self.collector = MemoryStateCollector()
        self.planner = PlacementPlanner(scorer)

    def place(
        self, request: AllocationRequest, candidates: list[MemorySpec], view: MemoryStateView
    ) -> PlacementDecision:
        # 1. Collect -> 2. Tier Scoring(후보 전체) -> 3. arg max
        self.collector.collect(candidates, view)
        scores = self.planner.tier_scoring(candidates, request, view)
        best = self.planner.best_tier_selection(scores)

        spec = view.spec(best)
        kv = request.block_set.total_bytes
        headroom = view.capacity_headroom_of(best)
        if request.block_set.placed_at == best:
            headroom += kv
        mode = spec.reactivation_mode_for(self.model, kv, headroom, self.step_budget_s)
        return PlacementDecision(best, request.decision_point, mode,
                                 "C1: arg max tier score over all feasible", len(candidates))

    def decision_ops(self) -> int:
        return self.collector.ops + self.planner.ops
