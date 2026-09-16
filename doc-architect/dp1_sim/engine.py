"""이산 사건 시뮬레이션 엔진.

설계 문서 §4.6 — GPU 점유와 메모리 점유를 **별도 자원**으로 기록하고
턴 시간을 `max`로 합친다. `sum`으로 바꾸면 자원 병렬화가 사라져
이 DP의 논거 자체가 측정되지 않는다.

세션은 Poisson 도착하고, 각 턴은
  Incremental Prefill(GPU 고정) -> 결정점 A -> Decode N step -> 결정점 B -> 유휴
를 거친다. 유휴 시간은 툴 실행 시간이며 그 분포가 배치 결정의 대가를 정한다.
"""

from __future__ import annotations

import heapq
import random
import statistics
from dataclasses import dataclass, field

from .analyzer import KVCharacteristicAnalyzer
from .core import (
    AllocationRequest,
    DecisionPoint,
    GpuSpec,
    LinkCostModel,
    MemorySpec,
    MemoryStateView,
    ModelShape,
    QueueStateView,
    ReactivationMode,
    SessionBlockSet,
    TriggerKind,
)
from .policy import FeasibilityFilter, PlacementDecision, PlacementExecutor, PlacementPolicy
from .workload import ToolProfile, WorkloadGenerator


@dataclass
class TurnRecord:
    session_id: str
    turn_index: int
    tool_name: str
    reactivation_ttft_s: float
    tpot_s: float
    decode_steps: int
    gpu_seconds: float
    memory_seconds: float
    turn_seconds: float
    restore_seconds: float
    offload_seconds: float
    move_seconds: float
    decision_seconds: float
    placed_at: str
    mode: str
    idle_s: float
    met_slo: bool
    is_reactivation: bool = False


@dataclass
class Session:
    sid: str
    block_set: SessionBlockSet
    turns_total: int
    turn_index: int = 0
    next_tool: ToolProfile | None = None
    tokens: int = 0
    spec: object = None
    pending_stall_s: float = 0.0   # 이전 턴의 결정점 B 이동이 유휴로 못 숨긴 초과분


@dataclass
class EngineResult:
    policy: str
    scenario: str
    turns: list[TurnRecord] = field(default_factory=list)
    sim_seconds: float = 0.0
    output_tokens: int = 0
    slo_output_tokens: int = 0
    first_turn_tokens: int = 0
    gpu_busy_s: float = 0.0
    mem_busy_s: float = 0.0
    hbm_capacity_bytes: float = 0.0
    decision_ops: int = 0
    decision_seconds: float = 0.0
    decisions: int = 0
    offload_eligible: int = 0
    offload_adopted: int = 0
    hbm_kv_bytes_samples: list[float] = field(default_factory=list)
    #: 살아 있는 모든 세션의 KV 총합 — **정책과 무관한 수요량**.
    #: hbm_kv_bytes_samples는 정책이 HBM에 실제로 둔 양이라 다르다.
    kv_demand_bytes_samples: list[float] = field(default_factory=list)
    hbm_idle_kv_bytes_samples: list[float] = field(default_factory=list)
    endurance_consumed: dict = field(default_factory=dict)
    placement_hist: dict = field(default_factory=dict)
    mode_hist: dict = field(default_factory=dict)
    preemptions: int = 0
    rejected: int = 0
    candidates_scored: list[int] = field(default_factory=list)


class Engine:
    """단일 GPU 노드 + 6종 메모리. 한 정책으로 한 시나리오를 돌린다."""

    #: 정책 결정 1회당 CPU 시간. 협력 객체 호출 수에 비례한다고 본다.
    #: 절대값은 ASSUMED이며, M-P5는 정책 간 **상대 비교**로만 쓴다.
    SECONDS_PER_DECISION_OP = 2.0e-6

    def __init__(
        self,
        policy: PlacementPolicy,
        gpu: GpuSpec,
        model: ModelShape,
        memories: list[MemorySpec],
        gen: WorkloadGenerator,
        rng: random.Random,
        *,
        trace: list | None = None,
        analyzer: KVCharacteristicAnalyzer | None = None,
        max_concurrent: int = 24,
        batch_size: int = 16,
        horizon_s: float = 120.0,
        ttft_slo_s: float = 2.0,
        tpot_slo_s: float = 0.05,
        step_budget_s: float = 0.05,
        burst: bool = False,
    ):
        self.policy = policy
        self.gpu = gpu
        self.model = model
        self.gen = gen
        self.rng = rng
        self.trace = trace
        self.analyzer = analyzer
        self.max_concurrent = max_concurrent
        self.batch_size = batch_size
        self.horizon_s = horizon_s
        self.ttft_slo_s = ttft_slo_s
        self.tpot_slo_s = tpot_slo_s
        self.burst = burst

        self.view = MemoryStateView(memories)
        self.queue_view = QueueStateView()
        self.feasibility = FeasibilityFilter(model, step_budget_s)
        self.executor = PlacementExecutor(self.view, model)
        self.link = LinkCostModel(model)
        self.step_budget_s = step_budget_s

        self.res = EngineResult(policy=policy.name, scenario=gen.sc.name)
        self.res.hbm_capacity_bytes = float(self.view.spec("hbm").capacity_bytes)

    # ── 도착률: burst 모드면 시간에 따라 3배까지 흔든다
    def _rate_multiplier(self, now: float) -> float:
        if not self.burst:
            return 1.0
        phase = (now / self.horizon_s) * 4.0
        return 0.4 + 2.6 * (0.5 + 0.5 * __import__("math").sin(phase * 3.14159))

    def _decide(self, req: AllocationRequest) -> tuple[PlacementDecision, float]:
        before = self.policy.decision_ops()
        candidates = self.feasibility.filter(self.view.memories(), req, self.view)
        if not candidates:
            candidates = [self.view.spec("ssd_pim")]
        decision = self.policy.place(req, candidates, self.view)
        ops = self.policy.decision_ops() - before
        secs = ops * self.SECONDS_PER_DECISION_OP
        self.res.decision_ops += ops
        self.res.decision_seconds += secs
        self.res.decisions += 1
        self.res.candidates_scored.append(decision.candidates_scored)

        # 오프로드 채택률 — eligible의 정의는 "원시 연산 집합을 모두
        # 지원하는 메모리가 후보에 존재하는가" (§11.2 M-P7 주의 2)
        if any(
            s.can_serve_decode_attention(
                self.model, req.block_set.total_bytes,
                self.view.capacity_headroom_of(s.name), self.step_budget_s)
            for s in candidates
        ):
            self.res.offload_eligible += 1
            if decision.mode is ReactivationMode.ATTENTION_OFFLOAD:
                self.res.offload_adopted += 1
        return decision, secs

    def _reactivation_cost(self, bs: SessionBlockSet) -> tuple[float, float, float]:
        """(TTFT의 KV 공급분, GPU 점유, 메모리 점유)를 돌려준다.

        Prefill 연산은 항상 GPU에서 일어난다 (§4.2(1)).
        """
        if bs.placed_at is None:
            return 0.0, 0.0, 0.0
        spec = self.view.spec(bs.placed_at)
        if bs.mode is ReactivationMode.ATTENTION_OFFLOAD:
            # 복원 없음. KV는 그 자리에 있고 활성화만 링크를 건넌다.
            return 0.0, 0.0, 0.0
        if bs.mode is ReactivationMode.RESIDENT:
            return 0.0, 0.0, 0.0
        # Mode B — History 전량 복원. all-or-nothing (§5.2(2)).
        restore_s = spec.transfer_seconds(bs.total_bytes)
        return restore_s, restore_s, 0.0

    def _decode_step_cost(self, bs: SessionBlockSet) -> tuple[float, float]:
        """한 Decode step의 (GPU 점유, 메모리 점유)."""
        spec = self.view.spec(bs.placed_at)
        if bs.mode is ReactivationMode.ATTENTION_OFFLOAD:
            mem_s = spec.offload_decode_seconds(self.model, bs.total_bytes, bs.context_tokens)
            link_s = self.link.total_seconds(spec, self.batch_size)
            # GPU는 Projection/FFN과 링크 왕복만 담당한다.
            return link_s, mem_s
        if bs.mode is ReactivationMode.RESIDENT and spec.name != "hbm":
            # Mode A — GPU가 그 메모리의 외부 대역폭으로 KV를 읽는다.
            return spec.resident_decode_seconds(bs.total_bytes), 0.0
        # HBM 상주 또는 복원 후
        return self.gpu.decode_attention_seconds(bs.total_bytes), 0.0

    def run(self) -> EngineResult:
        """사전 생성된 trace를 소비한다. 모든 정책이 동일한 워크로드를 본다."""
        assert self.trace is not None, "trace required"
        events: list[tuple[float, int, str, object]] = []
        seq = 0
        active: set[str] = set()
        sessions: dict[str, Session] = {}

        for spec in self.trace:
            bs = SessionBlockSet(
                session_id=spec.sid, context_tokens=spec.context_tokens,
                total_bytes=spec.context_tokens * self.model.kv_bytes_per_token())
            sessions[spec.sid] = Session(sid=spec.sid, block_set=bs,
                                         turns_total=len(spec.turns))
            sessions[spec.sid].spec = spec
            heapq.heappush(events, (spec.arrival_s, seq, "turn", sessions[spec.sid]))
            seq += 1

        gpu_free_at = 0.0
        mem_free_at: dict[str, float] = {}
        now = 0.0
        live_kv: dict[str, int] = {}   # sid -> 현재 KV 바이트 (수요량 측정용)

        while events:
            t, _, kind, sess = heapq.heappop(events)
            if t > self.horizon_s:
                break
            now = t
            s: Session = sess
            bs = s.block_set
            spec = s.spec

            if s.turn_index == 0:
                if len(active) >= self.max_concurrent:
                    self.res.rejected += 1
                    continue
                active.add(s.sid)

            ts = spec.turns[s.turn_index]
            tp = ts.tool
            terminal = ts.terminal

            # ── 재활성: KV를 GPU 쪽으로 공급
            restore_s, gpu_restore, mem_restore = self._reactivation_cost(bs)

            # ── Incremental Prefill (GPU 고정)
            prefill_tokens = ts.result_tokens if s.turn_index > 0 else min(bs.context_tokens, 4096)
            prefill_s = self.gpu.prefill_seconds(
                self.model, bs.context_tokens, max(1, prefill_tokens))
            # 이전 턴의 결정점 B 이동이 유휴 안에 숨지 못했으면, 그 초과분만큼
            # 이번 턴은 KV가 아직 제자리에 없다 — 사용자 관점에서는 대기다.
            ttft = s.pending_stall_s + restore_s + prefill_s
            s.pending_stall_s = 0.0

            # ── 결정점 A
            req_a = AllocationRequest(
                block_set=bs, decision_point=DecisionPoint.PREFILL_COMPLETE,
                trigger=None,
                tool_info=self.gen.tool_info_for(tp, terminal),
                next_op_primitives=self.gen.next_op_primitives(tp),
                turns_so_far=s.turn_index, step_index=0)
            dec_a, dsec_a = self._decide(req_a)
            move_a = self.executor.execute(dec_a, bs, self.gpu)

            # ── Decode
            decode_steps = ts.decode_len
            step_gpu, step_mem = self._decode_step_cost(bs)
            gpu_decode = step_gpu * decode_steps
            mem_decode = step_mem * decode_steps
            tpot = max(step_gpu, step_mem)

            # 결정점 A의 판단 시간과 이동은 Decode 시작을 막는다.
            gpu_total = gpu_restore + prefill_s + dsec_a + move_a + gpu_decode
            mem_total = mem_restore + mem_decode

            gpu_start = max(now, gpu_free_at)
            gpu_free_at = gpu_start + gpu_total
            mname = bs.placed_at or "hbm"
            mem_start = max(now, mem_free_at.get(mname, 0.0))
            mem_free_at[mname] = mem_start + mem_total
            queue_wait = gpu_start - now
            self.queue_view.observe_wait(queue_wait)
            finish = max(gpu_free_at, mem_free_at[mname])
            # §4.6 — 두 자원은 병렬로 돈다. 합이 아니라 max.
            turn_s = max(gpu_total, mem_total)

            self.res.gpu_busy_s += gpu_total
            self.res.mem_busy_s += mem_total

            is_reactivation = s.turn_index > 0
            met = (ttft + queue_wait) <= self.ttft_slo_s and tpot <= self.tpot_slo_s
            if is_reactivation:
                self.res.output_tokens += decode_steps
                if met:
                    self.res.slo_output_tokens += decode_steps
            else:
                self.res.first_turn_tokens += decode_steps

            # ── 결정점 B
            nxt_idx = s.turn_index + 1
            next_tp = spec.turns[nxt_idx].tool if (not terminal and nxt_idx < len(spec.turns)) else tp
            req_b = AllocationRequest(
                block_set=bs, decision_point=DecisionPoint.DEACTIVATION,
                trigger=TriggerKind.SESSION_DONE if terminal else TriggerKind.TURN_END,
                tool_info=self.gen.tool_info_for(next_tp, terminal),
                next_op_primitives=self.gen.next_op_primitives(next_tp),
                turns_so_far=nxt_idx, step_index=decode_steps)
            dec_b, dsec_b = self._decide(req_b)
            move_b = self.executor.execute(dec_b, bs, self.gpu)

            self.res.placement_hist[bs.placed_at] = self.res.placement_hist.get(bs.placed_at, 0) + 1
            self.res.mode_hist[bs.mode.value] = self.res.mode_hist.get(bs.mode.value, 0) + 1

            live_kv[s.sid] = bs.total_bytes
            self.res.kv_demand_bytes_samples.append(sum(live_kv.values()))
            hbm_used = self.view.state("hbm").used_bytes
            self.res.hbm_kv_bytes_samples.append(hbm_used)
            self.res.hbm_idle_kv_bytes_samples.append(
                bs.total_bytes if (bs.placed_at == "hbm" and not terminal) else 0.0)

            self.res.turns.append(TurnRecord(
                session_id=s.sid, turn_index=s.turn_index, tool_name=tp.name,
                reactivation_ttft_s=ttft + queue_wait, tpot_s=tpot,
                decode_steps=decode_steps, gpu_seconds=gpu_total, memory_seconds=mem_total,
                turn_seconds=turn_s, restore_seconds=restore_s, offload_seconds=mem_decode,
                move_seconds=move_a + move_b, decision_seconds=dsec_a + dsec_b,
                placed_at=bs.placed_at or "?", mode=bs.mode.value if bs.mode else "?",
                idle_s=ts.idle_s, met_slo=met, is_reactivation=is_reactivation))

            if self.analyzer is not None:
                self.analyzer.observe_turn(
                    tp.name, ts.idle_s, decode_steps, s.turn_index, continued=not terminal)

            # 결정점 B는 턴 종료 직후 일어나고, 이동은 유휴 중 백그라운드로
            # 진행될 수 있다. 유휴보다 길면 그 초과분이 다음 턴을 지연시킨다.
            deact_s = dsec_b + move_b
            migration_stall = max(0.0, deact_s - ts.idle_s)
            s.pending_stall_s = migration_stall
            # 이동은 대상 메모리의 대역폭도 점유한다
            if move_b > 0 and bs.placed_at:
                mem_free_at[bs.placed_at] = max(
                    mem_free_at.get(bs.placed_at, 0.0), finish) + move_b

            s.turn_index += 1
            if terminal or s.turn_index >= len(spec.turns):
                active.discard(s.sid)
                live_kv.pop(s.sid, None)
                if bs.placed_at:
                    self.view.release(bs.placed_at, bs.total_bytes)
            else:
                bs.context_tokens += ts.result_tokens + decode_steps
                bs.total_bytes = bs.context_tokens * self.model.kv_bytes_per_token()
                bs.observed_ref_cnt += 1
                heapq.heappush(events, (finish + ts.idle_s + migration_stall, seq, "turn", s))
                seq += 1

        # 분모는 horizon으로 **고정**한다. 정책마다 마지막 이벤트 시각이
        # 다르므로 그것을 분모로 쓰면 처리량 비교가 성립하지 않는다.
        self.res.sim_seconds = self.horizon_s
        for m in self.view.memories():
            self.res.endurance_consumed[m.name] = self.view.state(m.name).endurance_consumed_bytes
        return self.res


# ─────────────────────────────────────────────────────── derived metrics


def summarize(res: EngineResult) -> dict:
    t = res.turns
    if not t:
        return {"policy": res.policy, "scenario": res.scenario, "empty": True}

    react = [r for r in t if r.is_reactivation] or t
    ttfts = sorted(r.reactivation_ttft_s for r in react)
    tpots = sorted(r.tpot_s for r in react)

    def pct(xs, p):
        if not xs:
            return 0.0
        return xs[min(len(xs) - 1, int(p * (len(xs) - 1)))]

    wall = max(res.sim_seconds, 1e-9)
    hbm_avg = statistics.mean(res.hbm_kv_bytes_samples) if res.hbm_kv_bytes_samples else 0.0
    kv_demand = (statistics.mean(res.kv_demand_bytes_samples)
                 if res.kv_demand_bytes_samples else 0.0)
    hbm_idle = statistics.mean(res.hbm_idle_kv_bytes_samples) if res.hbm_idle_kv_bytes_samples else 0.0
    par = (res.gpu_busy_s + res.mem_busy_s) / max(res.gpu_busy_s, res.mem_busy_s, 1e-9)

    return {
        "policy": res.policy,
        "scenario": res.scenario,
        "turns": len(t),
        "goodput_tok_s": res.slo_output_tokens / wall,
        "throughput_tok_s": res.output_tokens / wall,
        "slo_attainment": res.slo_output_tokens / max(1, res.output_tokens),
        "ttft_p50_s": pct(ttfts, 0.50),
        "ttft_p99_s": pct(ttfts, 0.99),
        "tpot_p50_s": pct(tpots, 0.50),
        "tpot_p99_s": pct(tpots, 0.99),
        "restore_s_total": sum(r.restore_seconds for r in t),
        "move_s_total": sum(r.move_seconds for r in t),
        # 턴당 이동/결정 비용 — Performance 시간 지표에 실제로 들어간 양
        "move_s_per_turn": sum(r.move_seconds for r in t) / len(t),
        "decision_s_per_turn": sum(r.decision_seconds for r in t) / len(t),
        "overhead_share": (sum(r.move_seconds + r.decision_seconds for r in t)
                           / max(1e-9, sum(r.turn_seconds for r in t))),
        "decision_us_per_decision": (res.decision_seconds / max(1, res.decisions)) * 1e6,
        "decision_ops_per_decision": res.decision_ops / max(1, res.decisions),
        "candidates_scored_avg": statistics.mean(res.candidates_scored) if res.candidates_scored else 0,
        "offload_adoption": res.offload_adopted / max(1, res.offload_eligible),
        "hbm_kv_avg_gb": hbm_avg / 2**30,
        "hbm_idle_kv_avg_gb": hbm_idle / 2**30,
        "resource_parallelism": par,
        # ── 부하의 두 축 (§부하 정의). 정책과 무관한 입력 특성이므로
        #    세 정책에서 거의 같은 값이 나와야 한다.
        "kv_demand_avg_gb": kv_demand / 2**30,
        "kv_pressure": kv_demand / max(1.0, res.hbm_capacity_bytes),
        "gpu_pressure": res.gpu_busy_s / wall,
        "gpu_busy_s": res.gpu_busy_s,
        "mem_busy_s": res.mem_busy_s,
        "rejected": res.rejected,
        "placement_hist": dict(res.placement_hist),
        "mode_hist": dict(res.mode_hist),
        "endurance": {k: v for k, v in res.endurance_consumed.items() if v > 0},
    }
