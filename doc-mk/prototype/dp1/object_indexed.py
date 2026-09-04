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
        upgrade_if_free: bool = False,
        upgrade_headroom: float = 1.0,
        cost_model: "CostModel | None" = None,
        reserve_within_step: bool = True,
        mimic_c1: bool = False,
    ) -> None:
        # mimic_c1=True: 계약을 버리고 C1의 정책(자원 상태 argmax)으로 tier를 고른다.
        # 배치 결과는 C1과 같아지지만 분류 파이프라인 비용은 그대로 남는다 —
        # DP1 3.3-③ 상위호환 반박 ②의 실행 가능한 형태다.
        from .tier_indexed import TierIndexedPlacer

        # upgrade_if_free=True: 계약이 지시한 tier를 **하한**으로만 쓰고,
        # 그보다 빠른 tier에 여유가 있으면 올려서 배치한다.
        # 순수 C2에서 tier 상태는 아래로만 작용한다(목표가 차면 내려간다).
        # 이 옵션은 위로도 작용하게 만드는데, 그 순간 '어느 tier인가'를 고르는
        # 주체가 계약이 아니라 자원 상태가 된다 — 축이 C1 쪽으로 이동한다.
        # cost_model이 주어지면 계약 대신 비용 최소화로 tier를 고른다.
        # 등급은 로깅·계약 검증용으로 남고, 정책의 인덱스는 여전히 객체 축이다.
        # 유보 A — 스텝 내 예약. C1과 같은 이유로 C2에도 필요하다.
        # tier 상태는 스텝 경계에서만 갱신되므로, 이것이 없으면 같은 스텝의
        # 결정들이 서로를 보지 못해 용량을 넘겨 커밋한다(정합성 요건).
        # 유보 B(CostModel.reserve_for_future)와는 다른 것이다 — 부록 D.3.
        self.reserve_within_step = reserve_within_step
        self.cost_model = cost_model
        self.upgrade_if_free = upgrade_if_free
        # 상향 시 남겨둘 여유. 1.0이면 빈 자리를 끝까지 쓴다(도착 순서가 등급을 이긴다).
        # 0.5면 상위 tier의 절반을 고등급용으로 남긴다.
        self.upgrade_headroom = upgrade_headroom
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

        if self.cost_model is not None:
            best, best_cost = None, float("inf")
            for name in self.table.order:
                branches += 1
                if self.table.free(name, _instrumented=False) < num_blocks:
                    continue
                c = self.cost_model.cost(
                    obs, self.table.specs[name],
                    self.table.utilization(name), num_blocks,
                )
                if c < best_cost:
                    best, best_cost = c, name if False else name
                    best_cost = c
                    best = name
            if best is None:
                raise MemoryError("모든 tier에 여유가 없다")
            if self.reserve_within_step:
                self.table.reserve(best, num_blocks)
            messages += 2  # get_blocks(n) / blocks 반환
            return Decision(
                tier=best, messages=messages, state_reads=1, object_reads=1,
                branches=branches, grade=grade,
                reason=f"grade={grade};cost={best_cost:.3f}",
            )

        if self.upgrade_if_free:
            # 계약을 하한으로 보고 위쪽 여유를 확인한다 (자원 상태로 '선택')
            order = self.table.by_bandwidth
            for faster in order[: order.index(target)]:
                branches += 1
                cap = self.table.specs[faster].capacity_blocks
                after = (cap - self.table.free(faster, _instrumented=False)
                         + num_blocks) / cap
                if (self.table.free(faster, _instrumented=False) >= num_blocks
                        and after <= self.upgrade_headroom):
                    tier = faster
                    target = faster
                    break
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

        if self.reserve_within_step:
            self.table.reserve(tier, num_blocks)
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


class CostModel:
    """C2의 제대로 된 비용 모델.

    객체 특성에서 나온 **요구량**과 tier 속성으로 배치 비용을 계산한다.
    이전 구현의 상향 규칙("빈자리 있으면 위로")은 등급도 크기도 보지 않는
    구멍이었다. 여기서는 세 항을 모두 본다.

      service   : 요구량이 큰 객체를 느린 tier에 두면 비싸다
      occupancy : 자리값. **블록 수에 비례**하므로 큰 객체가 좁은 tier를
                  쓰면 비싸고, 희소한(점유율 높은) tier일수록 더 비싸다
      migration : 오래 살 객체를 이동비용 큰 tier에 두면 비싸다

    service/migration의 계수는 **객체 특성**에서 나오므로 정책의 인덱스는
    여전히 객체 축이다. occupancy는 자원 상태를 '가격'으로 쓰는 항이며,
    C2의 불변식(계약 우선)은 계수 비중으로 유지된다.
    """

    BW_MAX = 3200.0
    MIG_MAX = 8.0

    def __init__(self, *, w_service: float = 1.0, w_occupancy: float = 1.0,
                 w_migration: float = 0.05, reserve_for_future: bool = False) -> None:
        # reserve_for_future=True: 빈 상위 tier에도 값을 매겨 아직 오지 않은
        # 고강도 요청을 위해 공간을 유보한다. 구분 능력이 크게 오르지만
        # 저부하 구간에서 빠른 tier를 비워 둔다. 얼마를 유보할지는 미래
        # 도착 분포에 달려 있으므로 관측만으로는 정할 수 없다.
        self.reserve_for_future = reserve_for_future
        self.w_service = w_service
        self.w_occupancy = w_occupancy
        self.w_migration = w_migration

    # -- 객체 특성에서 나오는 계수 (관측 가능성은 부록 D.1/D.2 그대로) ----
    @staticmethod
    def bandwidth_demand(obs: ObservableRequest) -> float:
        """스텝당 대역폭 요구 — 컨텍스트 길이. **확정 관측값**."""
        return min(1.0, obs.prompt_len / 32768.0)

    @staticmethod
    def reuse_score(obs: ObservableRequest) -> float:
        """재사용 정도 — prefix 캐시 히트. **확정 관측값**."""
        return min(1.0, obs.prefix_hit_blocks / 128.0)

    @staticmethod
    def lifetime_score(obs: ObservableRequest) -> float:
        """수명 — max_tokens 기반 **추정**. C2의 미래 정보 노출 지점."""
        return min(1.0, obs.max_tokens / 4096.0)

    PRICE_SCALE = 1000.0

    def cost(self, obs, spec, util: float, blocks: int) -> float:
        """**블록 1개당** 비용 = -(가치) + (자리값) + (이동비용). 작을수록 좋다.

        여기서 핵심은 단위다. 빠른 tier의 공간은 **블록 단위로 사고팔린다.**
        큰 객체는 블록을 많이 쓰는 만큼 값도 많이 치르고 이득도 많이 얻으므로,
        **크기는 가치와 가격에 똑같이 비례해 상쇄된다.** 크기를 무시하는 것이
        아니라 상쇄되는 것이 옳다.

        그래서 남는 것은 **블록 1개가 얼마나 자주 읽히는가**, 즉 강도(intensity)다.
          - 수명이 긴 요청 : 같은 블록을 여러 스텝에 걸쳐 반복해 읽는다  → 가치 높음
          - prefix 재사용   : 여러 요청이 같은 블록을 읽는다              → 가치 높음
        자리값은 tier가 좁고 붐빌수록 비싸다 (기회비용).

        **강도의 주된 성분(수명)은 할당 시점에 관측할 수 없다.** C2의 구분
        능력이 미래 정보에 묶여 있다는 사실이 비용 함수의 형태에서 나온다.
        """
        bw = spec.bandwidth_gbps / self.BW_MAX
        intensity = self.lifetime_score(obs) + 0.5 * self.reuse_score(obs)

        value = intensity * bw
        # 빈 tier의 기회비용은 0이어야 한다 — 아무도 원하지 않는 공간에 값을
        # 매기면 빠른 tier를 비워둔 채 아래로 내려간다. (scarcity - 1)로 둔다.
        scarcity = 1.0 / max(0.02, 1.0 - util)
        if not self.reserve_for_future:
            # 빈 tier의 기회비용은 0 — 아무도 원하지 않는 공간에 값을 매기면
            # 빠른 tier를 비워둔 채 아래로 내려간다.
            scarcity -= 1.0
        price = (self.PRICE_SCALE / spec.capacity_blocks) * bw * scarcity
        migration = self.lifetime_score(obs) * (spec.migration_cost / self.MIG_MAX)

        return (-self.w_service * value
                + self.w_occupancy * price
                + self.w_migration * migration)
