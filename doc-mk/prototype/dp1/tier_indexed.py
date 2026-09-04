"""Candidate 1 — Tier-Indexed Placement (자원 축 인덱스).

정책의 1급 개체는 Tier다. 요청은 익명이고, tier 상태가 결정을 지배한다.
불변식: **자원 제약을 절대 위반하지 않는다.** 상위 tier가 차 있으면 요청이
무엇이든 하위 tier로 흘러간다.
"""

from __future__ import annotations

from .model import Decision, Placement, TierTable


class TierIndexedPlacer:
    name = "C1 · Tier-Indexed"
    anonymous = True

    def __init__(
        self,
        table: TierTable,
        *,
        reserve_within_step: bool = True,
        context_length_term: bool = False,
    ) -> None:
        """
        reserve_within_step:
            스텝 내 예약 카운터. 끄면 같은 스텝의 모든 결정이 동일한 상태를
            보고 한 tier로 몰린다(herding) — DP1 QA3의 감점 근거.
        context_length_term:
            11장에서 선택한 **보강**. 관측 가능한 컨텍스트 길이를 score의 한
            항으로 넣는다. 단일 진실 원천은 여전히 TierTable 하나이므로
            이것은 혼합이 아니라 "C1 + 보강"이다.
        """
        self.table = table
        self.reserve_within_step = reserve_within_step
        self.context_length_term = context_length_term

    # -- 정책 -------------------------------------------------------------
    def _score(self, tier: str, spec, free: int, ctx_demand: float) -> float:
        bw = spec.bandwidth_gbps / 3200.0
        util = self.table.utilization(tier)
        mig = spec.migration_cost / 8.0
        score = bw - 1.5 * util - 0.15 * mig
        if ctx_demand:
            # 스텝당 대역폭 요구가 큰 요청일수록 대역폭이 큰 tier의 가치가 커진다
            score += 0.8 * ctx_demand * bw
        return score

    def place(self, num_blocks: int, obs=None) -> Decision:
        messages = 1  # ① Scheduler → Placer : allocate(n)

        ctx_demand = 0.0
        object_reads = 0
        if self.context_length_term and obs is not None:
            # 보강: 관측 가능한 값 하나만 읽는다. 등급을 만들지 않는다.
            ctx_demand = min(1.0, obs.prompt_len / 32768.0)
            object_reads = 1

        snap = self.table.snapshot()  # ② read states(T) / ③ scores 반환
        messages += 2

        best_tier = None
        best_score = float("-inf")
        for tier, free, spec in snap:
            if free < num_blocks:
                continue  # 하드 제약 — tier 상태는 '명령'이다
            s = self._score(tier, spec, free, ctx_demand)
            if s > best_score:
                best_score, best_tier = s, tier

        if best_tier is None:
            raise MemoryError("모든 tier에 여유가 없다")

        if self.reserve_within_step:
            self.table.reserve(best_tier, num_blocks)

        messages += 2  # ④ get_blocks(n) / ⑤ blocks 반환
        return Decision(
            tier=best_tier,
            messages=messages,
            state_reads=1,          # 전역 상태 조회 1회 (T개 tier 스캔)
            object_reads=object_reads,
            branches=0,             # 실행 경로에 데이터 의존 분기 없음
            grade=(),               # 등급 개념 자체가 없다
            reason=f"score;{best_tier}",
        )

    def commit(self, req_id: str, decision: Decision, num_blocks: int) -> Placement:
        p = Placement(req_id=req_id, tier=decision.tier, blocks=num_blocks)
        self.table.commit(p)
        return p
