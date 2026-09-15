"""C2. Data 특성 중심 배치 구조 — 설계 문서 §7 Candidate 2.

구조: KV Characteristic Analyzer -> KV Classifier -> Placement Policy Table
      -> Memory State-aware Refiner.

**후보를 먼저 데이터 특성으로 좁히고, 그 다음에만 Memory State로 보정한다**
(구현 UML §2.3의 "깔때기(funnel)" 구조). Refiner는 C1과 **동일한
TierScorer 인스턴스**를 쓴다 — 산술이 같아야 비교가 성립한다.
"""

from __future__ import annotations

from ..analyzer import KVCharacteristicAnalyzer, KVClassifier, PlacementPolicyTable
from ..core import AllocationRequest, MemorySpec, MemoryStateView, ModelShape
from ..policy import PlacementDecision, PlacementPolicy, TierScorer


class MemoryStateAwareRefiner:
    """이미 좁혀진 후보 안에서만 Memory State로 보정한다."""

    def __init__(self, scorer: TierScorer):
        self.scorer = scorer
        self.ops = 0

    def refine(self, candidates, request, view) -> str:
        best, best_score = None, float("-inf")
        for spec in candidates:
            self.ops += 1
            s = self.scorer.score(spec, request, view)
            if s > best_score:
                best, best_score = spec.name, s
        return best


class DataCentricPolicy(PlacementPolicy):
    name = "C2-data-centric"

    def __init__(
        self,
        model: ModelShape,
        scorer: TierScorer,
        analyzer: KVCharacteristicAnalyzer,
        step_budget_s: float,
    ):
        self.model = model
        self.step_budget_s = step_budget_s
        self.analyzer = analyzer
        self.classifier = KVClassifier()
        self.policy_table = PlacementPolicyTable(model, step_budget_s)
        self.refiner = MemoryStateAwareRefiner(scorer)
        self._classify_ops = 0
        self.last_class = None

    def place(
        self, request: AllocationRequest, candidates: list[MemorySpec], view: MemoryStateView
    ) -> PlacementDecision:
        # 1. Analyze -> 2. Classify -> 3. Candidates(KV Class + 재활성 연산만)
        #                            -> 4. Refine(Memory State로 보정)
        ch = self.analyzer.analyze(request)
        self._classify_ops += 1
        kv_class = self.classifier.classify(ch, request.decision_point)
        self.last_class = kv_class

        narrowed = self.policy_table.candidates(
            kv_class, ch.next_op_primitives, candidates, view
        )
        # 좁힌 결과가 feasible 집합을 벗어나지 않도록 교집합을 취한다.
        allowed = {s.name for s in candidates}
        narrowed = [s for s in narrowed if s.name in allowed] or candidates

        best = self.refiner.refine(narrowed, request, view)

        spec = view.spec(best)
        kv = request.block_set.total_bytes
        headroom = view.capacity_headroom_of(best)
        if request.block_set.placed_at == best:
            headroom += kv
        mode = spec.reactivation_mode_for(self.model, kv, headroom, self.step_budget_s)
        return PlacementDecision(
            best, request.decision_point, mode,
            f"C2: {kv_class.value} -> {len(narrowed)} candidates -> arg max",
            len(narrowed),
        )

    def decision_ops(self) -> int:
        return (
            self.analyzer.ops
            + self._classify_ops
            + self.policy_table.ops
            + self.refiner.ops
        )
