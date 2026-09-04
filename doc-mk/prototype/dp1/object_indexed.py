"""Candidate 2 — Object-Indexed Placement (객체 축 인덱스).

정책의 1급 개체는 메모리 객체의 특성 클래스다. 클래스가 목표 tier를 지시하고,
tier 상태는 그 지시를 만족시키기 위해 **조정되는 대상**이다.
불변식: **객체 클래스의 배치 계약을 지킨다.** 목표 tier가 차 있으면 기존
객체를 밀어내서라도 자리를 만든다.
"""

from __future__ import annotations

from dataclasses import dataclass

from .model import Decision, ObservableRequest, Placement, TierTable

# 등급 = (bandwidth_heavy, reuse_likely, long_lived) 세 이진 특성 → 2^3 = 8종
ObjectGrade = tuple


@dataclass(frozen=True)
class FeatureSpec:
    """특성 하나의 이름과 '할당 시점 관측 가능 여부' (부록 D.1 / D.2)."""

    name: str
    observable: bool


class HeuristicClassifier:
    """관측 가능한 신호 위주로 3개 이진 특성을 산출한다.

    - bandwidth_heavy : prompt_len 기반 — **확정 관측값**
    - reuse_likely    : prefix_hit_blocks 기반 — **확정 관측값**
    - long_lived      : max_tokens 기반 — **추정**. max_tokens는 상한일 뿐
                        실제 출력 길이와의 상관이 약하다(부록 D.4).
    """

    features = (
        FeatureSpec("bandwidth_heavy", True),
        FeatureSpec("reuse_likely", True),
        FeatureSpec("long_lived", False),
    )

    def __init__(self, *, single_class: bool = False) -> None:
        # single_class=True 는 "C2를 C1처럼 설정한" 상태다. 동작은 같아지지만
        # 분류 비용은 그대로 남는다 — 상위호환 반박 ②의 실행 가능한 형태.
        self.single_class = single_class

    @property
    def observable_ratio(self) -> float:
        return sum(f.observable for f in self.features) / len(self.features)

    def classify(self, obs: ObservableRequest) -> ObjectGrade:
        if self.single_class:
            # 요청을 읽지 않아도 되는 것처럼 보이지만, 파이프라인은 그대로 돈다.
            _ = obs.prompt_len
            return (False, False, False)
        return (
            obs.prompt_len >= 8192,
            obs.prefix_hit_blocks > 0,
            obs.max_tokens >= 2048,
        )


class ClassTierContract:
    """등급 → 목표 tier 계약. 정책이 사는 자리."""

    def __init__(self, table: TierTable) -> None:
        self.table = table
        self.map: dict[ObjectGrade, str] = {}
        for bw in (False, True):
            for reuse in (False, True):
                for longlived in (False, True):
                    if bw and longlived:
                        t = "HBM"
                    elif bw:
                        t = "CUSTOM_HBM"
                    elif longlived and reuse:
                        t = "CUSTOM_HBM"
                    elif longlived:
                        t = "DRAM"
                    elif reuse:
                        t = "DRAM"
                    else:
                        t = "CXL"
                    self.map[(bw, reuse, longlived)] = t

    def target(self, grade: ObjectGrade) -> str:
        return self.map[grade]

    def fallbacks(self, target: str) -> list[str]:
        order = self.table.by_bandwidth
        return order[order.index(target) + 1 :]

    def rank(self, tier: str) -> int:
        return self.table.by_bandwidth.index(tier)


class ObjectIndexedPlacer:
    name = "C2 · Object-Indexed"
    anonymous = False

    def __init__(
        self,
        table: TierTable,
        classifier: HeuristicClassifier | None = None,
        *,
        allow_eviction: bool = True,
        mimic_c1: bool = False,
    ) -> None:
        # mimic_c1=True: 계약을 버리고 C1의 정책(자원 상태 argmax)으로 tier를 고른다.
        # 배치 결과는 C1과 같아지지만 분류 파이프라인 비용은 그대로 남는다 —
        # DP1 3.3-③ 상위호환 반박 ②의 실행 가능한 형태다.
        from .tier_indexed import TierIndexedPlacer

        self._mimic = TierIndexedPlacer(table) if mimic_c1 else None
        self.table = table
        self.classifier = classifier or HeuristicClassifier()
        self.contract = ClassTierContract(table)
        self.allow_eviction = allow_eviction
        self.grades: dict[str, ObjectGrade] = {}  # 정적 고착: 한 번 정하면 끝

    @property
    def distinct_grades(self) -> int:
        return 1 if self.classifier.single_class else 2 ** len(self.classifier.features)

    def _evict_for(self, tier: str, need: int, incoming: ObjectGrade) -> list[str]:
        """계약을 지키기 위해 자리를 만든다 — tier 상태는 '조정 대상'이다."""
        evicted: list[str] = []
        occupants = sorted(
            self.table.placements[tier],
            key=lambda p: (sum(p.grade), p.blocks),
        )
        for p in occupants:
            if self.table.free(tier, _instrumented=False) >= need:
                break
            if sum(p.grade) >= sum(incoming):
                continue  # 더 높은 등급은 밀어내지 않는다
            for fb in self.contract.fallbacks(tier):
                if self.table.free(fb, _instrumented=False) >= p.blocks:
                    self.table.move(p, fb)
                    evicted.append(p.req_id)
                    break
        return evicted

    def place(self, num_blocks: int, obs: ObservableRequest) -> Decision:
        messages = 1  # ① allocate(n, request)

        grade = self.grades.get(getattr(obs, "req_id", None))
        if grade is None:
            grade = self.classifier.classify(obs)  # ②③ classify / class 반환
            if hasattr(obs, "req_id"):
                self.grades[obs.req_id] = grade
        messages += 2

        if self._mimic is not None:
            inner = self._mimic.place(num_blocks)
            messages += inner.messages - 1  # allocate 메시지는 이미 셌다
            return Decision(
                tier=inner.tier,
                messages=messages,
                state_reads=inner.state_reads,
                object_reads=1,      # 분류 비용은 그대로 지불한다
                branches=inner.branches,
                grade=grade,
                reason=f"mimic;{inner.tier}",
            )

        target = self.contract.target(grade)  # ④⑤ target_tier() / 반환
        messages += 2

        branches = 1  # 정책 판정 자체가 데이터 의존 분기다
        evicted: list[str] = []
        tier = target
        if self.table.free(target, _instrumented=False) < num_blocks:
            branches += 1
            if self.allow_eviction:
                evicted = self._evict_for(target, num_blocks, grade)
                messages += 2  # make_room / evicted 반환
            if self.table.free(target, _instrumented=False) < num_blocks:
                tier = None
                for fb in self.contract.fallbacks(target):
                    if self.table.free(fb, _instrumented=False) >= num_blocks:
                        tier = fb
                        break
                if tier is None:
                    raise MemoryError("모든 tier에 여유가 없다")

        messages += 2  # get_blocks(n) / blocks 반환
        return Decision(
            tier=tier,
            messages=messages,
            state_reads=1,
            object_reads=1,  # 분류를 위해 요청을 읽는다
            branches=branches,
            grade=grade,
            evicted=evicted,
            reason=f"grade={grade}",  # 근거가 라벨 하나로 남는다
        )

    def commit(self, req_id: str, decision: Decision, num_blocks: int) -> Placement:
        p = Placement(
            req_id=req_id, tier=decision.tier, blocks=num_blocks, grade=decision.grade
        )
        self.table.commit(p)
        return p
