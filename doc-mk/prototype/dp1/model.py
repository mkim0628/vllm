"""DP1 배치 결정 프로토타입 — 공통 모델.

이 패키지는 vLLM 코어를 수정하지 않는다. DP1의 **배치 결정 로직만** 떼어내
독립 실행 가능한 형태로 구현하고, 문서의 정량 주장을 실측 가능하게 만든다.

핵심 설계 원칙 두 가지:

1. **관측 가능성을 타입으로 강제한다.**
   `ObservableRequest`는 할당 시점에 실제로 알 수 있는 값만 갖는다.
   미래 정보는 `Oracle`에 격리되어 있고, 배치기(Placer)는 Oracle을 볼 수 없다.
   시뮬레이터만 결과 채점을 위해 Oracle을 읽는다.

2. **익명성을 타입으로 강제한다.**
   Candidate 1은 요청 정보를 읽지 않는다. `TripwireView`를 넘기면
   속성 접근 시 예외가 나므로, "읽지 않음"이 테스트로 증명된다.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

BLOCK_TOKENS = 16  # vLLM 기본 block size (CacheConfig.DEFAULT_BLOCK_SIZE)


# --------------------------------------------------------------------------
# Tier
# --------------------------------------------------------------------------
@dataclass(frozen=True)
class TierSpec:
    name: str
    capacity_blocks: int
    bandwidth_gbps: float
    latency_us: float
    migration_cost: float


# 용량은 70B급 모델 기준의 대략적 규모다.
# 토큰당 KV ≈ 320KB (80 layer × 8 kv head × 128 dim × 2 × 2B) 로 잡으면
# HBM에 쓸 수 있는 40GB ≈ 131K 토큰 ≈ 8192 블록이 된다.
DEFAULT_TIERS: tuple[TierSpec, ...] = (
    TierSpec("HBM", 8_192, 3200.0, 0.5, 1.0),
    TierSpec("CUSTOM_HBM", 16_384, 1600.0, 0.8, 1.2),
    TierSpec("DRAM", 65_536, 200.0, 1.2, 1.8),
    TierSpec("CXL", 131_072, 64.0, 2.5, 2.0),
    TierSpec("HBF", 524_288, 16.0, 20.0, 4.0),
    TierSpec("SSD", 2_097_152, 6.0, 120.0, 8.0),
)


@dataclass
class Placement:
    """한 요청이 특정 tier에서 점유 중인 블록."""

    req_id: str
    tier: str
    blocks: int
    grade: tuple = ()  # C2에서만 채워진다 (객체 등급)


class TierTable:
    """C1의 단일 진실 원천이자 C2의 제약/비용 항.

    모든 읽기는 계측된다. `state_reads`는 '전역 상태 조회 횟수',
    `tier_scans`는 그때 훑은 tier 수다. 둘을 나눠 세야 문서의
    "조회 1회(6 tier 스캔)"를 그대로 검증할 수 있다.
    """

    def __init__(
        self,
        specs: tuple[TierSpec, ...] = DEFAULT_TIERS,
        *,
        stale_within_step: bool = True,
    ) -> None:
        # stale_within_step=True 가 현실이다. tier 상태는 스케줄 스텝 경계에서
        # 갱신되므로, 한 스텝 안의 결정들은 모두 '스텝 시작 시점의 상태'를 본다.
        # 이 staleness를 보정하는 유일한 수단이 예약(reserve) 카운터다.
        self.stale_within_step = stale_within_step
        self._view: dict[str, int] = {}
        self.specs: dict[str, TierSpec] = {s.name: s for s in specs}
        self.order: list[str] = [s.name for s in specs]
        self.by_bandwidth: list[str] = [
            s.name for s in sorted(specs, key=lambda t: -t.bandwidth_gbps)
        ]
        self.used: dict[str, int] = {n: 0 for n in self.order}
        self.reserved: dict[str, int] = {n: 0 for n in self.order}
        self.placements: dict[str, list[Placement]] = {n: [] for n in self.order}
        # 계측
        self.state_reads = 0
        self.tier_scans = 0
        self.refreshes = 0
        self.refresh_items = 0
        # 자기 불변식 위반: 커밋 결과 tier 용량을 넘겼다는 뜻.
        # 스텝 내 예약 카운터가 없으면 C1에서 실제로 발생한다.
        self.overcommits = 0

    # -- 관측 -------------------------------------------------------------
    def snapshot(self) -> list[tuple[str, int, TierSpec]]:
        """전역 상태 1회 조회. (tier 이름, 가용 블록, spec) 목록을 돌려준다."""
        self.state_reads += 1
        self.tier_scans += len(self.order)
        return [(n, self.free(n, _instrumented=False), self.specs[n]) for n in self.order]

    def free(self, name: str, *, _instrumented: bool = True) -> int:
        if _instrumented:
            self.state_reads += 1
            self.tier_scans += 1
        spec = self.specs[name]
        seen = self._view.get(name, self.used[name]) if self.stale_within_step \
            else self.used[name]
        return spec.capacity_blocks - seen - self.reserved[name]

    def refresh(self) -> None:
        """스텝 경계에서의 상태 갱신. 비용은 tier 수에 비례하고 요청 수와 무관하다."""
        self.refreshes += 1
        self.refresh_items += len(self.order)

    # -- 변경 -------------------------------------------------------------
    def reserve(self, name: str, blocks: int) -> None:
        """스텝 내 예약. C1의 herding 완화책이며, 이것이 없으면 같은 스텝의
        모든 결정이 동일한 상태를 보고 같은 tier로 몰린다."""
        self.reserved[name] += blocks

    def commit(self, placement: Placement) -> None:
        self.used[placement.tier] += placement.blocks
        self.placements[placement.tier].append(placement)
        if self.used[placement.tier] > self.specs[placement.tier].capacity_blocks:
            self.overcommits += 1

    def release(self, req_id: str) -> int:
        freed = 0
        for tier in self.order:
            keep = []
            for p in self.placements[tier]:
                if p.req_id == req_id:
                    self.used[tier] -= p.blocks
                    freed += p.blocks
                else:
                    keep.append(p)
            self.placements[tier] = keep
        return freed

    def move(self, placement: Placement, to_tier: str) -> None:
        """이미 놓인 블록을 다른 tier로 옮긴다 (C2의 자리 확보).

        배치기 **자신이 방금 한 행위**이므로 스텝 내 관측 창에도 즉시 반영한다.
        같은 스텝의 다른 결정이 만든 변화는 여전히 보이지 않는다 —
        그 보정 수단은 예약 카운터뿐이다.
        """
        frm = placement.tier
        self.placements[frm].remove(placement)
        self.used[frm] -= placement.blocks
        placement.tier = to_tier
        self.used[to_tier] += placement.blocks
        self.placements[to_tier].append(placement)
        if self._view:
            self._view[frm] = self._view.get(frm, 0) - placement.blocks
            self._view[to_tier] = self._view.get(to_tier, 0) + placement.blocks

    def begin_step(self) -> None:
        """스텝 경계에서만 상태를 갱신한다 — 이 스텝 동안 보이는 값이 고정된다."""
        self.refresh()
        self._view = dict(self.used)

    def end_step(self) -> None:
        """예약을 실사용으로 흡수한다."""
        for n in self.order:
            self.reserved[n] = 0
        self._view = dict(self.used)

    def tier_of(self, req_id: str) -> str | None:
        for tier in self.order:
            for p in self.placements[tier]:
                if p.req_id == req_id:
                    return tier
        return None

    def utilization(self, name: str) -> float:
        """점유율. 가용 블록과 **같은 관측 창**에서 계산해야 한다.

        하드 제약은 stale view로 보면서 점수는 실시간 값으로 보면
        모델이 현실보다 똑똑해진다 — 실제 배치기는 한 번 읽은 스냅샷 하나만 본다.
        """
        spec = self.specs[name]
        seen = self._view.get(name, self.used[name]) if self.stale_within_step \
            else self.used[name]
        return (seen + self.reserved[name]) / spec.capacity_blocks


# --------------------------------------------------------------------------
# 요청 — 관측 가능한 것과 불가능한 것의 분리
# --------------------------------------------------------------------------
@dataclass(frozen=True)
class ObservableRequest:
    """할당 시점에 실제로 알 수 있는 값만 담는다 (DP1 부록 D.1)."""

    req_id: str
    prompt_len: int          # len(prompt_token_ids) — 확정값
    max_tokens: int          # 상한일 뿐, 실제 출력 길이가 아니다
    endpoint: str
    model: str
    prefix_hit_blocks: int   # get_computed_blocks()가 allocate 직전에 알려준다
    attention: str = "full"  # "full" | "sliding"


@dataclass(frozen=True)
class Oracle:
    """시뮬레이터만 아는 미래 (DP1 부록 D.2). 배치기는 절대 읽지 않는다."""

    actual_output_len: int
    prefix_group: str | None = None


@dataclass
class Request:
    obs: ObservableRequest
    oracle: Oracle

    @property
    def req_id(self) -> str:
        return self.obs.req_id

    @property
    def prompt_blocks(self) -> int:
        return math.ceil(self.obs.prompt_len / BLOCK_TOKENS)

    def read_tokens(self) -> int:
        """디코드 전 구간에서 읽는 KV 토큰 총량 (부록 D.6의 계산).

        스텝 t에서 (prompt_len + t) 토큰을 읽는다고 보면
        Σ_{t=1..out} (prompt_len + t) 이다.
        """
        n = self.oracle.actual_output_len
        return n * self.obs.prompt_len + n * (n + 1) // 2

    def peak_step_read_tokens(self) -> int:
        """한 스텝에 읽는 최대 KV 토큰 = 최종 컨텍스트 길이."""
        return self.obs.prompt_len + self.oracle.actual_output_len


class AnonymityViolation(AssertionError):
    """익명 경로에서 요청 속성을 읽으면 발생한다."""


class TripwireView:
    """C1이 요청 정보를 읽지 않음을 구조적으로 증명하기 위한 감시 객체.

    C1에 이 객체를 넘기면 정상 동작해야 하고, C2에 넘기면 반드시 터져야 한다.
    """

    def __init__(self) -> None:
        object.__setattr__(self, "reads", [])

    def __getattr__(self, name: str):
        object.__getattribute__(self, "reads").append(name)
        raise AnonymityViolation(
            f"익명 요청 경로에서 요청 속성 '{name}'을(를) 읽었다"
        )


# --------------------------------------------------------------------------
# 결정
# --------------------------------------------------------------------------
@dataclass
class Decision:
    """한 번의 배치 결정과 그 비용 계측."""

    tier: str
    messages: int = 0          # dispatch 경로의 메시지 수 (시퀀스 다이어그램)
    state_reads: int = 0       # 전역 상태 조회 횟수
    object_reads: int = 0      # 객체(요청) 조회 횟수 — C1은 항상 0
    branches: int = 0          # 데이터 의존 분기 수
    grade: tuple = ()          # C2의 객체 등급 (C1은 빈 튜플 = 등급 없음)
    evicted: list[str] = field(default_factory=list)
    reason: str = ""           # 결정 근거 (QA4: 로깅 항목)

    @property
    def reason_items(self) -> int:
        """결정 근거를 재현하려면 몇 개 항목을 남겨야 하는가."""
        return self.reason.count(";") + 1 if self.reason else 0
