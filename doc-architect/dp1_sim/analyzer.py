"""C2 전용 — KV 캐시 특성 분석 (설계 문서 §5.1, 구현 UML §2.3).

C1은 이 모듈에 의존하지 않는다. 의존 간선이 없으면 추정 오차가 도달할
경로도 없으므로, C1의 추정 오차 민감도가 정확히 0인 것이 구조로 보장된다.

세 추정 모델은 **관측 로그에서 학습**한다. 실제 실행 시간은 시뮬레이터가
독립적으로 샘플링하므로 추정과 실제가 다르며, 그 간극이 C2가 지불하는
대가다 — 이것을 제거하면 C2가 부당하게 유리해진다.
"""

from __future__ import annotations

import statistics
from dataclasses import dataclass, field
from enum import Enum

from .core import AgentToolInfo, AllocationRequest, AttentionPrimitive, DecisionPoint


class KVClass(Enum):
    HOT_COMPUTE_HEAVY = "hot_compute_heavy"
    WARM_READ_INTENSIVE = "warm_read_intensive"
    COLD_LONG_TERM = "cold_long_term"


@dataclass
class KVCharacteristics:
    """§5.4의 타당성 검토를 필드 구성으로 반영한다."""

    # Next-access Time을 두 성분으로 분리한다 (§5.4(2)).
    # 큐 성분은 시스템 상태이지 데이터 특성이 아니다.
    tool_exec_time_s: float
    queue_wait_time_s: float

    # 관측(observed_ref_cnt)과 추정(reuse_probability)을 따로 들고 있어야
    # Ablation에서 추정 성분만 제거할 수 있다 (§5.4).
    observed_ref_cnt: int
    reuse_probability: float

    # "몇 턴 남았나"는 예측이 어렵지만 "다음 턴이 있을 확률"은 로그에서
    # 추정된다 (§5.4(3)).
    turn_hazard_rate: float

    expected_decode_length: int          # 결정점 A용 특성 (§5.1)
    tool_info: AgentToolInfo | None
    next_op_primitives: frozenset

    def next_access_time_s(self) -> float:
        """파생값 — 두 성분의 합."""
        return self.tool_exec_time_s + self.queue_wait_time_s

    def expected_roundtrips(self) -> float:
        """hazard rate에서 유도한 기대 잔여 왕복 수. 점 추정이 아니다."""
        h = min(0.99, max(0.01, self.turn_hazard_rate))
        return h / (1.0 - h)


class _QuantileModel:
    """관측 로그에서 분위수를 추정한다. 표본이 모자라면 사전값으로 떨어진다."""

    def __init__(self, prior: float, min_samples: int = 5):
        self.prior = prior
        self.min_samples = min_samples
        self._obs: dict[str, list[float]] = {}

    def observe(self, key: str, value: float) -> None:
        self._obs.setdefault(key, []).append(value)
        if len(self._obs[key]) > 200:
            self._obs[key] = self._obs[key][-200:]

    def quantiles(self, key: str) -> dict[float, float]:
        s = self._obs.get(key, [])
        if len(s) < self.min_samples:
            return {0.5: self.prior, 0.9: self.prior * 2.0}
        ordered = sorted(s)
        return {
            0.5: statistics.median(ordered),
            0.9: ordered[int(0.9 * (len(ordered) - 1))],
        }

    def estimate(self, key: str) -> float:
        """중앙값을 점 추정으로 쓴다. 분산이 큰 툴에서 이 선택이 대가를 만든다."""
        return self.quantiles(key)[0.5]


class ToolLatencyModel(_QuantileModel):
    """툴 이름 -> 실행 시간 분포."""


class DecodeLengthModel(_QuantileModel):
    """툴 이름 -> 이번 턴의 예상 Decode 길이."""


class TurnHazardModel:
    """지금까지 n턴 진행된 세션에 다음 턴이 있을 확률."""

    def __init__(self, prior: float = 0.7):
        self.prior = prior
        self._continued: dict[int, int] = {}
        self._ended: dict[int, int] = {}

    def observe(self, turns_so_far: int, continued: bool) -> None:
        bucket = min(turns_so_far, 20)
        d = self._continued if continued else self._ended
        d[bucket] = d.get(bucket, 0) + 1

    def hazard(self, turns_so_far: int) -> float:
        bucket = min(turns_so_far, 20)
        c = self._continued.get(bucket, 0)
        e = self._ended.get(bucket, 0)
        if c + e < 5:
            return self.prior
        return c / (c + e)


class KVCharacteristicAnalyzer:
    """§5.1의 네 특성을 산출한다. 호출 1회 = 협력 객체 3회 조회."""

    def __init__(self, queue_view, sample_rate: float = 1.0):
        self.queue_view = queue_view
        self.sample_rate = sample_rate
        self.tool_model = ToolLatencyModel(prior=2.0)
        self.hazard_model = TurnHazardModel(prior=0.7)
        self.decode_model = DecodeLengthModel(prior=180.0)
        self.ops = 0

    def analyze(self, request: AllocationRequest) -> KVCharacteristics:
        self.ops += 3
        ti = request.tool_info
        key = ti.tool_name if ti else "__none__"

        if ti is None or ti.is_terminal:
            tool_s = 0.0
            reuse = 0.05
        else:
            tool_s = self.tool_model.estimate(key)
            reuse = 0.9

        hazard = self.hazard_model.hazard(request.turns_so_far)
        if ti is not None and ti.is_terminal:
            hazard = 0.02

        return KVCharacteristics(
            tool_exec_time_s=tool_s,
            queue_wait_time_s=self.queue_view.expected_wait_seconds(),
            observed_ref_cnt=request.block_set.observed_ref_cnt,
            reuse_probability=reuse * (0.5 + 0.5 * hazard),
            turn_hazard_rate=hazard,
            expected_decode_length=int(self.decode_model.estimate(key)),
            tool_info=ti,
            next_op_primitives=request.next_op_primitives,
        )

    # 사후 관측만이 세 모델의 갱신 경로다 (구현 UML §3.7).
    def observe_turn(
        self, tool_name: str, actual_tool_s: float, actual_decode_len: int,
        turns_so_far: int, continued: bool,
    ) -> None:
        self.tool_model.observe(tool_name, actual_tool_s)
        self.decode_model.observe(tool_name, float(actual_decode_len))
        self.hazard_model.observe(turns_so_far, continued)


class KVClassifier:
    """특성 -> KV Class. 결정점에 따라 **다른 축**을 쓴다 (§5.1).

    결정점 A: expected_decode_length + 재활성 연산
    결정점 B: next_access_time + reuse_probability
    """

    # 결정점 B 임계값 — 절대 시간(초). 하위 계층 왕복 비용과 같은 자릿수에 둔다.
    NEXT_ACCESS_HOT_S = 1.0
    NEXT_ACCESS_WARM_S = 10.0
    REUSE_HOT = 0.6
    # 결정점 A 임계값 — 이번 턴 Decode step 수.
    DECODE_LONG_STEPS = 64

    def classify(self, ch: KVCharacteristics, decision_point: DecisionPoint) -> KVClass:
        offloadable = bool(ch.next_op_primitives)

        if decision_point is DecisionPoint.PREFILL_COMPLETE:
            # 이번 턴 Decode가 길고 오프로드 가능한 연산을 받으면
            # 연산형 메모리로 옮길 값이 있다 — C1이 내리지 못하는 판단.
            if ch.expected_decode_length >= self.DECODE_LONG_STEPS and offloadable:
                return KVClass.HOT_COMPUTE_HEAVY
            return KVClass.WARM_READ_INTENSIVE

        nat = ch.next_access_time_s()
        if nat <= self.NEXT_ACCESS_HOT_S and ch.reuse_probability >= self.REUSE_HOT:
            return KVClass.HOT_COMPUTE_HEAVY if offloadable else KVClass.WARM_READ_INTENSIVE
        if nat <= self.NEXT_ACCESS_WARM_S and ch.reuse_probability >= 0.3:
            return KVClass.WARM_READ_INTENSIVE
        return KVClass.COLD_LONG_TERM


class PlacementPolicyTable:
    """KV Class -> 후보 메모리. **Memory State를 참조하지 않는다.**

    신규 메모리를 코드 수정 없이 편입하기 위해 `Medium`을 열거하지 않고
    **메모리의 성질로 일반 판정**한다 (UML 검수 U6의 권고).
    이 선택이 M-F1(Flexibility)과 M-M2(변경 지점 수)를 동시에 결정한다.
    """

    def __init__(self, model, step_budget_s: float):
        self.model = model
        self.step_budget_s = step_budget_s
        self.ops = 0

    #: Hot으로 인정할 재접근 경로의 대역폭 하한. HBM(8 TB/s)의 절반.
    FAST_PATH_BW = 4.0e12
    #: Warm이 감당할 수 있는 복원 대역폭 하한. HBF(1 TB/s) 등급.
    WARM_PATH_BW = 5.0e11
    #: 보관 계층으로 인정할 용량 하한. GPU HBM(192 GiB)의 5배.
    BULK_CAPACITY = 1.0e12

    def candidates(self, kv_class: KVClass, primitives: frozenset, memories, view) -> list:
        self.ops += 1
        out = []
        for spec in memories:
            if kv_class is KVClass.HOT_COMPUTE_HEAVY:
                # 곧(≤1s) 다시 쓰이고 확실히 쓰인다 -> 최고속 경로만.
                # in-place 연산이 가능하더라도 내부 대역폭이 느리면
                # Decode step이 예산을 넘으므로 Hot의 후보가 아니다.
                ok = (
                    (spec.supports_attention() and spec.int_bw_bytes_per_s >= self.FAST_PATH_BW)
                    or (spec.gpu_reachable and spec.ext_bw_bytes_per_s >= self.FAST_PATH_BW)
                )
            elif kv_class is KVClass.WARM_READ_INTENSIVE:
                # 중간(≤10s) — in-place 연산이 가능하거나 복원이 감당된다.
                ok = spec.supports_attention() or spec.ext_bw_bytes_per_s >= self.WARM_PATH_BW
            else:
                # 보관이 목적. **연산형 메모리를 배제한다** — 돌아오지 않을
                # KV가 연산형 메모리의 자리를 점유하면 Hot 세션이 그 자리를
                # 쓰지 못한다 (§11.2 M-P8의 "연산형 메모리 자리 낭비").
                ok = spec.capacity_bytes >= self.BULK_CAPACITY and not spec.supports_attention()
            if ok:
                out.append(spec)
        return out or list(memories)
