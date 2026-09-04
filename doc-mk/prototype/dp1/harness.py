"""시뮬레이션 하네스 — 워크로드를 배치기에 흘리고 DP1의 정량 프록시를 잰다.

측정하는 프록시는 DP1 문서 4.5절 '정량 지표 추출표'와 같은 항목이다.
문서의 값이 예측이라면 여기서 나오는 값은 실측이다.
"""

from __future__ import annotations

import math
from collections import Counter, defaultdict
from dataclasses import dataclass, field

from .model import BLOCK_TOKENS, TierTable, TripwireView
from .workload import Scenario


@dataclass
class Metrics:
    placer: str
    scenario: str
    decisions: int = 0
    messages: int = 0
    state_reads: int = 0
    object_reads: int = 0
    branches: int = 0
    refresh_items: int = 0
    evictions: int = 0
    grades_used: set = field(default_factory=set)
    reason_items: int = 0
    step_tier_counts: list = field(default_factory=list)
    placement_log: dict = field(default_factory=dict)   # req_id → tier (최초 배치)
    bandwidth_match: float = 0.0
    separation_ratio: float = 1.0
    shared_prefix_tier: str | None = None
    shared_contract_violations: int = 0
    overcommits: int = 0
    herding_first_step: float = 0.0

    # -- 파생 지표 --------------------------------------------------------
    @property
    def messages_per_decision(self) -> float:
        return self.messages / max(1, self.decisions)

    @property
    def distinct_grades(self) -> int:
        return max(1, len(self.grades_used))

    @property
    def herding(self) -> float:
        """스텝마다 '한 tier가 가져간 결정 비율'의 최댓값, 그 평균.

        1.0 이면 그 스텝의 모든 할당이 한 tier로 몰렸다는 뜻이다.
        """
        if not self.step_tier_counts:
            return 0.0
        shares = []
        for counter in self.step_tier_counts:
            total = sum(counter.values())
            if total:
                shares.append(max(counter.values()) / total)
        return sum(shares) / len(shares) if shares else 0.0

    def as_row(self) -> dict:
        return {
            "placer": self.placer,
            "scenario": self.scenario,
            "decisions": self.decisions,
            "msg/decision": round(self.messages_per_decision, 2),
            "state_reads": self.state_reads,
            "object_reads": self.object_reads,
            "branches": self.branches,
            "grades": self.distinct_grades,
            "herding": round(self.herding, 3),
            "bw_match": round(self.bandwidth_match, 3),
            "separation": round(self.separation_ratio, 2),
            "herding_1st": round(self.herding_first_step, 3),
            "overcommit": self.overcommits,
            "evictions": self.evictions,
            "shared_viol": self.shared_contract_violations,
        }


FAST_TIERS = ("HBM", "CUSTOM_HBM")


def run(placer, table: TierTable, scenario: Scenario, *, order_key=None) -> Metrics:
    """시나리오를 한 번 흘린다.

    order_key: 같은 스텝 안의 처리 순서를 바꾸기 위한 키. 재현성(QA4) 검증에 쓴다.
    """
    m = Metrics(placer=placer.name, scenario=scenario.name)
    active: dict[str, tuple] = {}   # req_id → (request, remaining_steps, blocks)
    # prefix 공유: 같은 group의 블록은 최초 소유자가 놓은 자리에 하나만 존재한다.
    prefix_owner: dict[str, str] = {}   # group → tier

    for step in range(scenario.horizon):
        table.begin_step()
        counter = Counter()

        arrivals = list(scenario.arrivals.get(step, []))
        if order_key is not None:
            arrivals.sort(key=order_key)

        # 1) 신규 도착 — prompt 블록 할당
        for req in arrivals:
            n = req.prompt_blocks
            group = req.oracle.prefix_group
            if group and req.obs.prefix_hit_blocks and group in prefix_owner:
                # 캐시 히트 — 공유 블록은 새로 할당하지 않는다. 배치 결정도 없다.
                n = max(1, n - req.obs.prefix_hit_blocks)
            d = placer.place(n, req.obs)
            placer.commit(req.req_id, d, n)
            _tally(m, d, counter, req.req_id, first=True)
            if group and group not in prefix_owner:
                prefix_owner[group] = d.tier
                m.shared_prefix_tier = d.tier
            elif group and req.obs.prefix_hit_blocks:
                # 공유 블록은 최초 소유자의 tier에 그대로 있다.
                # 이 요청의 계약이 그보다 빠른 tier를 요구했다면 계약이 조용히 깨진 것이다.
                want = getattr(placer, "contract", None)
                if want is not None and d.grade:
                    target = want.target(d.grade)
                    if want.rank(target) < want.rank(prefix_owner[group]):
                        m.shared_contract_violations += 1
            active[req.req_id] = [req, req.oracle.actual_output_len, n]

        # 2) 진행 중인 요청 — 16토큰마다 블록 1개 추가 (점진 할당)
        for req_id, state in list(active.items()):
            req, remaining, blocks = state
            if remaining <= 0:
                continue
            produced = req.oracle.actual_output_len - remaining
            if produced > 0 and produced % BLOCK_TOKENS == 0:
                d = placer.place(1, req.obs)
                placer.commit(req_id, d, 1)
                _tally(m, d, counter, req_id, first=False)
                state[2] = blocks + 1
            state[1] = remaining - 1

        # 3) 종료된 요청 해제
        for req_id, state in list(active.items()):
            if state[1] <= 0:
                table.release(req_id)
                del active[req_id]

        if counter:
            m.step_tier_counts.append(counter)
        table.end_step()

    m.refresh_items = table.refresh_items
    m.overcommits = table.overcommits
    if m.step_tier_counts:
        first = m.step_tier_counts[0]
        m.herding_first_step = max(first.values()) / sum(first.values())
    _score_quality(m, scenario, table)
    return m


def _tally(m: Metrics, d, counter, req_id, *, first: bool) -> None:
    m.decisions += 1
    m.messages += d.messages
    m.state_reads += d.state_reads
    m.object_reads += d.object_reads
    m.branches += d.branches
    m.evictions += len(d.evicted)
    m.reason_items += d.reason_items
    if d.grade:
        m.grades_used.add(d.grade)
    counter[d.tier] += 1
    if first:
        m.placement_log[req_id] = d.tier


def _score_quality(m: Metrics, scenario: Scenario, table: TierTable) -> None:
    """배치 품질 — 오라클(실제 읽기량)을 기준으로 채점한다.

    배치기는 오라클을 볼 수 없다. 채점만 본다.
    """
    reqs = [r for lst in scenario.arrivals.values() for r in lst]
    if not reqs:
        return
    bw_max = max(s.bandwidth_gbps for s in table.specs.values())
    num = den = 0.0
    for r in reqs:
        demand = r.peak_step_read_tokens()
        tier = m.placement_log.get(r.req_id)
        if tier is None:
            continue
        num += demand * table.specs[tier].bandwidth_gbps
        den += demand * bw_max
    m.bandwidth_match = num / den if den else 0.0

    # 구분 능력: 대역폭 요구 상위 20% 요청이 받은 평균 tier 대역폭을
    # 나머지 80%의 평균으로 나눈 값. 1.0이면 전혀 구분하지 못한 것이다.
    ranked = sorted(reqs, key=lambda r: -r.peak_step_read_tokens())
    k = max(1, len(ranked) // 5)

    def avg_bw(group):
        vals = [
            table.specs[m.placement_log[r.req_id]].bandwidth_gbps
            for r in group
            if r.req_id in m.placement_log
        ]
        return sum(vals) / len(vals) if vals else 0.0

    hi, lo = avg_bw(ranked[:k]), avg_bw(ranked[k:])
    m.separation_ratio = (hi / lo) if lo else 1.0


def check_anonymity(placer) -> bool:
    """배치기가 요청 정보를 읽는지 구조적으로 확인한다.

    True  → 요청을 전혀 읽지 않았다 (익명 경로)
    False → 요청 속성을 읽었다
    """
    from .model import AnonymityViolation

    table = placer.table
    try:
        placer.place(1, TripwireView())
    except AnonymityViolation:
        return False
    return True
