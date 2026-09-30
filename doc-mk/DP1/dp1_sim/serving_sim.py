"""Request-level vLLM-V1-like serving simulation with DP1 migration.

What is modelled (and why it is enough for DP1):
  * continuous batching, FCFS, chunked prefill (max_num_batched_tokens),
    max_num_seqs, decode-first scheduling as in the V1 scheduler
  * HBM KV capacity in bytes; running-request KV is pinned (not movable)
  * per-session retained KV (prefix cache of a finished turn) = one logical
    DP1 data object. It is movable across tiers by the DP1 policy.
  * vLLM runtime fallbacks, identical for every candidate:
      - HBM allocation failure -> drop LRU retained KV (prefix-cache eviction)
      - still failing for a running request -> preempt(recompute) the newest
  * demand promotion: a turn whose KV sits in a lower tier waits for the
    H2D copy (vLLM "WAITING_FOR_REMOTE_KVS"-like state); dropped KV is
    recomputed by prefill
  * transfers on shared lanes (PCIe full duplex, HBF read/write), FIFO,
    TransferCurve from measurements (A) or catalog (B)
  * step time from perf_model.StepModel (A-calibrated or default), inflated
    by copy_interference while a DMA is in flight, plus synchronous DP1
    decision time
Not modelled: speculative decoding, CUDA-graph padding, detokenizer / API
server overhead (absorbed in c0 by calibration), multi-node.
"""

from __future__ import annotations

import heapq
import time
from collections import Counter, defaultdict, deque
from dataclasses import dataclass, field

from events import EventType, MigrationEvent, MigrationScheduler
from hw import ServingHW, TierSpec, TransferCurve
from perf_model import StepModel
from policies import Telemetry
from policies_serving import DROP, make_policy
from workload import Turn

TTFT_SLO_S = 2.0
TPOT_SLO_S = 0.050


@dataclass
class KVObject:
    sid: int
    tokens: int
    tier: str | None  # None = dropped (must be recomputed)
    movable: bool = False
    busy_until: float = 0.0  # in-flight transfer end
    busy_dst: str | None = None
    last_access: float = 0.0
    moves: deque = field(default_factory=lambda: deque(maxlen=8))
    promoted_by_policy_at: float | None = None
    demoted_at: float | None = None


@dataclass
class Req:
    turn: Turn
    arrival: float
    history_tokens: int  # tokens of the session so far (prefix of this prompt)
    cached: int = 0  # tokens reusable from KV
    prompt: int = 0
    prefilled: int = 0
    generated: int = 0
    ready_at: float = 0.0
    first_token_t: float | None = None
    finish_t: float | None = None
    admitted: bool = False
    kv_bytes: float = 0.0  # HBM bytes this request holds (incl. pinned session KV)
    recomputed_tokens: int = 0
    promotion_wait_s: float = 0.0
    preempted: int = 0
    gen_in_prompt: int = 0  # generated tokens folded into prompt by a preemption

    @property
    def kv_tokens(self) -> int:
        return self.prompt + self.generated - self.gen_in_prompt


@dataclass
class SimCtx:
    """What DP1 policies may read (runtime-provided resource view)."""

    capacity: dict
    occupancy: Counter
    memories: dict
    tick_s: float
    _lane_busy: dict
    _restore: callable

    def lane_busy(self, lane: str) -> float:
        return self._lane_busy.get(lane, 0.0)

    def restore_time(self, tier: str, size: float) -> float:
        return self._restore(tier, size)


class ServingSim:
    def __init__(
        self,
        hw: ServingHW,
        step_model: StepModel,
        policy_name: str,
        turns: list[Turn],
        tick_s: float = 0.25,
        decision_cost: str = "model",
        chunk_bytes: float = 2 * 1024**2,
        max_sim_s: float = 3600.0,
    ):
        self.hw, self.sm = hw, step_model
        self.policy = make_policy(policy_name)
        self.policy_name = policy_name
        self.tick_s = tick_s
        self.decision_cost = decision_cost
        self.chunk_bytes = chunk_bytes
        self.max_sim_s = max_sim_s
        self.kvB = hw.model.kv_bytes_per_token

        hbm = TierSpec("hbm", hw.kv_capacity_bytes, hw.hbm_bw, hw.hbm_bw, 3e-7, "hbm")
        self.mem = {"hbm": hbm, **hw.tiers}
        self.cap = {n: t.capacity_bytes for n, t in self.mem.items()}
        self.occ: Counter = Counter({n: 0.0 for n in self.mem})
        self.lane_free: dict = defaultdict(float)
        self.lane_busy_acc: dict = defaultdict(float)
        self.lane_busy_frac: dict = {}
        self.inflight: list = []  # heap (end, seq, kind, oid, src, dst, size)
        self._seq = 0

        self.sched = MigrationScheduler(coalesce_telemetry=True)
        self.ctx = SimCtx(
            self.cap,
            self.occ,
            self.mem,
            tick_s,
            self.lane_busy_frac,
            self._restore_time,
        )

        by_sid = defaultdict(list)
        for tr in turns:
            by_sid[tr.session].append(tr)
        self.sessions = {s: sorted(v, key=lambda x: x.turn) for s, v in by_sid.items()}
        self.pending: list = []  # heap (time, seq, Turn)
        for s, v in self.sessions.items():
            heapq.heappush(self.pending, (v[0].arrival_s, self._next_seq(), v[0]))
        self.hist_tokens: dict[int, int] = defaultdict(int)
        self.kv: dict[int, KVObject] = {}

        self.loading: list[Req] = []
        self.waiting: deque[Req] = deque()
        self.running: list[Req] = []
        self.done: list[Req] = []

        self.m = Counter()  # diagnostics counters
        self.util_samples = defaultdict(list)
        self.decision_wall_s = 0.0
        self.drain_walls: list[
            float
        ] = []  # per decision cycle wall-clock (A on the host CPU)
        self.pred_events: list = []
        self.hbm_snap: list = []  # (t, running_bytes, [(sid, bytes)]) for hindsight usefulness

    # ------------------------------------------------------------------ utils
    def _next_seq(self) -> int:
        self._seq += 1
        return self._seq

    def _lane(self, src: str, dst: str) -> tuple[tuple[str, str], TransferCurve]:
        if dst == "hbm":
            t = self.mem[src]
            return (t.lane, "up"), t.promote
        if src == "hbm":
            t = self.mem[dst]
            return (t.lane, "down"), t.demote
        a, b = self.mem[src], self.mem[dst]
        bw = min(a.ext_bw, b.write_bw)
        return ("host", "x"), TransferCurve(a.latency_s + b.latency_s, bw)

    def _restore_time(self, tier: str, size: float) -> float:
        if tier == "hbm":
            return 0.0
        (lane, _), curve = self._lane(tier, "hbm")
        backlog = max(0.0, self.lane_free[(lane, "up")] - self.now)
        return backlog + curve.time(size, self.chunk_bytes)

    def _push(self, ev: MigrationEvent):
        self.sched.push(ev)

    def _drain(self) -> float:
        """Run DP1 decision pipeline; return decision time (s) charged to the engine."""
        before = self.sched.stats.decision_overhead_us
        w0 = time.perf_counter()
        decisions = self.sched.drain(self.policy, self.ctx)
        wall = time.perf_counter() - w0
        self.decision_wall_s += wall
        self.drain_walls.append(wall)
        self._execute(decisions)
        modeled = (self.sched.stats.decision_overhead_us - before) * 1e-6
        return wall if self.decision_cost == "wall" else modeled

    # -------------------------------------------------------------- transfers
    def _execute(self, decisions):
        for d in decisions:
            o = self.kv.get(d.object_id)
            if (
                o is None
                or o.tier != d.source_tier
                or not o.movable
                or o.busy_until > self.now
            ):
                self.m["decision_rejected"] += 1
                continue
            size = o.tokens * self.kvB
            if d.target_tier == DROP:
                self.occ[o.tier] -= size
                o.tier = None
                o.demoted_at = self.now
                self.m["drop_by_policy"] += 1
                self.m["migration_drop_bytes"] += size
                self.policy.on_migration_committed(d, self.now)
                continue
            if self.occ[d.target_tier] + size > self.cap[d.target_tier]:
                self.m["decision_rejected"] += 1
                continue
            self._start_transfer(
                o, d.source_tier, d.target_tier, size, "policy_" + d.direction
            )
            self.policy.on_migration_committed(d, self.now)
            self.m[f"migrations_{d.direction}"] += 1
            self.m["migration_bytes"] += size
            if d.target_tier == "hbm":
                o.promoted_by_policy_at = self.now
            if d.source_tier == "hbm":
                o.demoted_at = self.now

    def _start_transfer(
        self, o: KVObject, src: str, dst: str, size: float, kind: str
    ) -> float:
        key, curve = self._lane(src, dst)
        start = max(self.now, self.lane_free[key])
        dur = curve.time(size, self.chunk_bytes)
        end = start + dur
        self.lane_free[key] = end
        self.lane_busy_acc[key[0]] += dur
        self.occ[dst] += size  # reserve destination
        o.busy_until, o.busy_dst = end, dst
        o.moves.append(self.now)
        if len(o.moves) >= 4 and self.now - o.moves[-4] < 30.0:
            self.m["thrash_events"] += 1
        heapq.heappush(
            self.inflight, (end, self._next_seq(), kind, o.sid, src, dst, size)
        )
        self.m["transfer_time_s"] += dur
        return end

    def _complete_transfers(self):
        while self.inflight and self.inflight[0][0] <= self.now:
            end, _, kind, sid, src, dst, size = heapq.heappop(self.inflight)
            o = self.kv[sid]
            self.occ[src] -= size
            o.tier = dst
            o.busy_dst = None

    def _dma_active(self) -> bool:
        return bool(self.inflight) and self.inflight[0][0] > self.now - 1e-12

    # --------------------------------------------------------------- telemetry
    def _telemetry(self, need_bytes: float = 0.0) -> float:
        tel = {}
        for n in self.mem:
            cu = self.occ[n] / self.cap[n] if self.cap[n] > 0 else 1.5
            lane = self.mem[n].lane
            tel[n] = Telemetry(
                capacity_util=cu,
                bw_util=self.lane_busy_frac.get(lane, 0.0) if n != "hbm" else 0.0,
            )
        md = {"telemetry": tel}
        if need_bytes > 0:
            md["need_bytes"] = need_bytes
        self._push(MigrationEvent(EventType.TELEMETRY, self.now, metadata=md))
        return self._drain()

    def _sample(self):
        for n in self.mem:
            self.util_samples[n].append(
                self.occ[n] / self.cap[n] if self.cap[n] else 0.0
            )
        running = sum(r.kv_bytes for r in self.running)
        retained = [
            (o.sid, o.tokens * self.kvB)
            for o in self.kv.values()
            if o.tier == "hbm" and o.movable
        ]
        self.hbm_snap.append((self.now, running, retained))
        for lane, acc in list(self.lane_busy_acc.items()):
            self.lane_busy_frac[lane] = min(1.0, acc / self.tick_s)
            self.lane_busy_acc[lane] = 0.0

    # ----------------------------------------------------------------- arrival
    def _arrive(self, tr: Turn):
        r = Req(tr, self.now, self.hist_tokens[tr.session])
        r.prompt = r.history_tokens + tr.new_tokens
        o = self.kv.get(tr.session)
        if tr.turn > 0:
            self._push(
                MigrationEvent(EventType.ACCESSED, self.now, tr.session, count=1)
            )
        if o is None or tr.turn == 0:
            self._enqueue(r)
            return
        o.last_access = self.now
        if o.demoted_at is not None and self.now - o.demoted_at < 30.0:
            self.m["unnecessary_demotion"] += 1  # re-accessed shortly after leaving HBM
        if o.tier is None and o.busy_dst is None:
            r.recomputed_tokens = r.history_tokens
            self.m["recompute_tokens"] += r.history_tokens
            self.m["reuse_miss_dropped"] += 1
            self._enqueue(r)
            return
        # pin: the running request now owns the session KV
        o.movable = False
        self._push(
            MigrationEvent(
                EventType.PHASE_CHANGE,
                self.now,
                tr.session,
                metadata={"movable": False},
            )
        )
        r.cached = o.tokens
        if o.tier == "hbm" and o.busy_dst is None:
            self.m["reuse_hit_hbm"] += 1
            if o.promoted_by_policy_at is not None:
                self.m["prefetch_hit"] += 1
                o.promoted_by_policy_at = None
            r.kv_bytes = o.tokens * self.kvB
            self._enqueue(r)
            return
        # in a lower tier or in flight -> demand promotion
        ready = self._demand_promote(o)
        if ready is None:
            # no HBM room even after fallback -> recompute
            r.cached = 0
            r.recomputed_tokens = r.history_tokens
            self.m["recompute_tokens"] += r.history_tokens
            self.m["reuse_miss_dropped"] += 1
            self._enqueue(r)
            return
        self.m["reuse_hit_lower"] += 1
        r.ready_at = ready
        r.kv_bytes = o.tokens * self.kvB
        self.loading.append(r)

    def _demand_promote(self, o: KVObject) -> float | None:
        if o.busy_dst == "hbm":
            return o.busy_until
        t0 = max(self.now, o.busy_until)
        if o.busy_dst is not None:
            # moving down: finish that first, then bring back (approximation)
            self.m["demand_after_demote"] += 1
        size = o.tokens * self.kvB
        if not self._ensure_hbm(size, allow_wait=False):
            if o.busy_dst is None and o.tier is not None:
                self.occ[o.tier] -= size
                o.tier = None
            return None
        src = o.busy_dst or o.tier
        saved = self.now
        self.now = t0
        end = self._start_transfer(o, src, "hbm", size, "demand")
        self.now = saved
        self.m["demand_promotions"] += 1
        return end

    def _enqueue(self, r: Req):
        self.waiting.append(r)

    # --------------------------------------------------------------- capacity
    def _hbm_free(self) -> float:
        return self.cap["hbm"] - self.occ["hbm"]

    def _pending_hbm_release(self) -> float:
        return sum(s for (e, _, k, sid, src, dst, s) in self.inflight if src == "hbm")

    def _ensure_hbm(self, need: float, allow_wait: bool) -> bool:
        if self._hbm_free() >= need:
            return True
        # 1) DP1 synchronous pressure event
        self.step_decision_s += self._telemetry(need_bytes=need - self._hbm_free())
        if self._hbm_free() >= need:
            return True
        if allow_wait and self._hbm_free() + self._pending_hbm_release() >= need:
            return False  # space is coming (async demotion); retry next step
        # 2) vLLM runtime fallback: evict LRU retained KV (prefix cache) -> drop
        cands = sorted(
            (
                o
                for o in self.kv.values()
                if o.tier == "hbm" and o.movable and o.busy_dst is None
            ),
            key=lambda o: o.last_access,
        )
        for o in cands:
            if self._hbm_free() >= need:
                break
            self.occ["hbm"] -= o.tokens * self.kvB
            o.tier = None
            o.demoted_at = self.now
            self.m["runtime_lru_drop"] += 1
            self._push(
                MigrationEvent(
                    EventType.FREED, self.now, o.sid, metadata={"reason": "evicted"}
                )
            )
        return self._hbm_free() >= need

    def _preempt(self, r: Req):
        self.running.remove(r)
        self.occ["hbm"] -= r.kv_bytes
        o = self.kv.get(r.turn.session)
        if o is not None and o.tier == "hbm" and not o.movable:
            o.tier = None  # its pinned KV was freed with the request
            self._push(
                MigrationEvent(
                    EventType.FREED, self.now, o.sid, metadata={"reason": "preempted"}
                )
            )
        r.kv_bytes = 0.0
        r.recomputed_tokens += r.prefilled + r.generated
        self.m["recompute_tokens"] += r.prefilled + r.generated
        r.prompt = r.prompt + r.generated - r.gen_in_prompt
        r.gen_in_prompt = r.generated
        r.cached = 0
        r.prefilled = 0
        r.admitted = False
        r.preempted += 1
        self.m["preemptions"] += 1
        self.waiting.appendleft(r)

    # ------------------------------------------------------------------- step
    def _schedule(self):
        budget = self.hw.max_num_batched_tokens
        prefill_chunks, decode = [], []
        # running requests first (V1): decodes and ongoing chunked prefills
        for r in sorted(self.running, key=lambda x: x.arrival):
            if r not in self.running:
                continue
            if r.prefilled < r.prompt - r.cached:
                q = min(budget, r.prompt - r.cached - r.prefilled)
                if q <= 0:
                    continue
                if not self._ensure_hbm(q * self.kvB, allow_wait=False):
                    continue
                self.occ["hbm"] += q * self.kvB
                r.kv_bytes += q * self.kvB
                prefill_chunks.append((r, q))
                budget -= q
            else:
                if budget <= 0:
                    continue
                need = self.kvB
                while not self._ensure_hbm(need, allow_wait=False):
                    victim = max(self.running, key=lambda x: x.arrival)
                    self._preempt(victim)
                    if victim is r:
                        break
                if r not in self.running:
                    continue
                self.occ["hbm"] += need
                r.kv_bytes += need
                decode.append(r)
                budget -= 1
        # admit waiting (FCFS, no skipping)
        while self.waiting and budget > 0 and len(self.running) < self.hw.max_num_seqs:
            r = self.waiting[0]
            q = min(budget, r.prompt - r.cached - r.prefilled)
            if not self._ensure_hbm(q * self.kvB, allow_wait=True):
                break
            self.waiting.popleft()
            r.admitted = True
            self.occ["hbm"] += q * self.kvB
            r.kv_bytes += q * self.kvB
            self.running.append(r)
            if (
                r.turn.turn == 0
                or r.turn.session not in self.kv
                or self.kv[r.turn.session].tier is None
            ):
                self._create_session_kv(r)
            prefill_chunks.append((r, q))
            budget -= q
        # drop work of requests preempted later in this same scheduling pass
        prefill_chunks = [(r, q) for r, q in prefill_chunks if r in self.running]
        decode = [r for r in decode if r in self.running]
        return prefill_chunks, decode

    def _create_session_kv(self, r: Req):
        sid = r.turn.session
        o = self.kv.get(sid)
        if o is None:
            o = KVObject(sid, 0, "hbm")
            self.kv[sid] = o
        o.tier, o.movable, o.tokens, o.last_access = "hbm", False, 0, self.now
        o.busy_dst = None
        # the KV bytes are accounted on the request while it runs
        self._push(
            MigrationEvent(
                EventType.ALLOCATED,
                self.now,
                sid,
                metadata={
                    "size_bytes": r.prompt * self.kvB,
                    "tier": "hbm",
                    "data_type": "KV_CACHE",
                    "movable": False,
                },
            )
        )

    def _finish(self, r: Req):
        self.running.remove(r)
        r.finish_t = self.now
        self.done.append(r)
        sid = r.turn.session
        o = self.kv[sid]
        total = r.kv_tokens
        self.hist_tokens[sid] = total
        # hand the request's HBM bytes to the retained session object
        o.tokens, o.tier, o.movable, o.last_access = total, "hbm", True, self.now
        o.busy_dst = None
        o.demoted_at = None
        self._push(
            MigrationEvent(
                EventType.PHASE_CHANGE,
                self.now,
                sid,
                metadata={
                    "movable": True,
                    "size_bytes": total * self.kvB,
                    "tier": "hbm",
                },
            )
        )
        # HBM occupancy: request held kv_bytes (pinned history + new); object now owns total*kvB
        self.occ["hbm"] += total * self.kvB - r.kv_bytes
        r.kv_bytes = 0.0
        turns = self.sessions[sid]
        if not r.turn.last:
            nxt = turns[r.turn.turn + 1]
            heapq.heappush(
                self.pending, (self.now + nxt.think_s, self._next_seq(), nxt)
            )

    # -------------------------------------------------------------------- run
    def run(self) -> dict:
        self.now = 0.0
        next_tick = 0.0
        busy_time = 0.0
        idle_spins = 0
        while (
            self.pending
            or self.loading
            or self.waiting
            or self.running
            or self.inflight
        ):
            if self.now > self.max_sim_s:
                self.m["truncated"] = 1
                break
            self.step_decision_s = 0.0
            self._complete_transfers()
            while self.pending and self.pending[0][0] <= self.now:
                _, _, tr = heapq.heappop(self.pending)
                self._arrive(tr)
            for r in [x for x in self.loading if x.ready_at <= self.now]:
                self.loading.remove(r)
                r.promotion_wait_s = self.now - r.arrival
                self.m["promotion_wait_s"] += r.promotion_wait_s
                self.waiting.append(r)
            if self.now >= next_tick:
                self._sample()
                self.step_decision_s += self._telemetry()
                next_tick = self.now + self.tick_s

            prefill_chunks, decode = self._schedule()
            if not prefill_chunks and not decode:
                idle_spins += 1
                if (
                    idle_spins > 200
                    and self.waiting
                    and not self.running
                    and not self.inflight
                ):
                    r = self.waiting.popleft()  # cannot ever fit: reject (counted)
                    self.m["rejected_requests"] += 1
                    idle_spins = 0
                    if not r.turn.last:
                        # keep the session going so later turns are still exercised
                        self.hist_tokens[r.turn.session] = 0
                        nxt = self.sessions[r.turn.session][r.turn.turn + 1]
                        heapq.heappush(
                            self.pending,
                            (self.now + nxt.think_s, self._next_seq(), nxt),
                        )
                    continue
                cands = [next_tick]
                if self.pending:
                    cands.append(self.pending[0][0])
                if self.inflight:
                    cands.append(self.inflight[0][0])
                cands += [r.ready_at for r in self.loading]
                self.now = max(self.now + 1e-6, min(cands)) + self.step_decision_s
                continue

            idle_spins = 0
            chunks = [(q, r.cached + r.prefilled) for r, q in prefill_chunks]
            dctx = sum(r.kv_tokens for r in decode)
            dt = self.sm.step_time(self.hw, chunks, dctx, len(decode))
            if self._dma_active():
                dt *= 1.0 + self.hw.copy_interference
                self.m["steps_with_dma"] += 1
            dt += self.step_decision_s
            self.m["steps"] += 1
            self.now += dt
            busy_time += dt

            for r, q in prefill_chunks:
                r.prefilled += q
                if r.prefilled >= r.prompt - r.cached and r.first_token_t is None:
                    r.first_token_t = self.now
                    r.generated = 1
                elif r.prefilled >= r.prompt - r.cached:
                    r.generated += (
                        1  # resumed after preemption: token sampled at end of prefill
                    )
            for r in decode:
                r.generated += 1
            for r in [
                x
                for x in self.running
                if x.first_token_t is not None and x.generated >= x.turn.output_tokens
            ]:
                self._finish(r)
        return self._report(busy_time)

    def request_records(self) -> list[dict]:
        """Per-request records in dp1_client.py format (for shadow/validation tests)."""
        out = []
        for r in sorted(self.done, key=lambda x: x.arrival):
            out.append(
                {
                    "session": r.turn.session,
                    "turn": r.turn.turn,
                    "behavior": r.turn.behavior,
                    "arrival_s": r.arrival,
                    "prompt_tokens": r.history_tokens + r.turn.new_tokens,
                    "history_tokens": r.history_tokens,
                    "output_tokens": r.turn.output_tokens,
                    "ttft_s": r.first_token_t - r.arrival,
                    "finish_s": r.finish_t,
                    "tpot_s": (r.finish_t - r.first_token_t)
                    / max(1, r.turn.output_tokens - 1),
                    "cached_tokens": r.history_tokens - r.recomputed_tokens
                    if r.turn.turn > 0
                    else 0,
                    "error": None,
                }
            )
        return out

    def check_invariants(self) -> list[str]:
        errs = []
        for n, v in self.occ.items():
            if v < -1.0:
                errs.append(f"negative occupancy {n}={v}")
        if not self.inflight and not self.running:
            for n in self.mem:
                exp = sum(o.tokens * self.kvB for o in self.kv.values() if o.tier == n)
                if abs(exp - self.occ[n]) > 1e3:
                    errs.append(
                        f"occupancy leak on {n}: occ={self.occ[n]:.0f} objects={exp:.0f}"
                    )
        return errs

    # ----------------------------------------------------------------- report
    def _report(self, busy_time: float) -> dict:
        from qa import weighted_pct

        done = self.done
        if not done:
            return {"policy": self.policy_name, "requests": 0}
        t0 = min(r.arrival for r in done)
        t1 = max(r.finish_t for r in done)
        dur = max(1e-9, t1 - t0)
        ttfts = [r.first_token_t - r.arrival for r in done]
        tpots = [
            (r.finish_t - r.first_token_t) / max(1, r.turn.output_tokens - 1)
            for r in done
        ]
        good = sum(
            r.turn.output_tokens
            for r, a, b in zip(done, ttfts, tpots)
            if a <= TTFT_SLO_S and b <= TPOT_SLO_S
        )
        outtok = sum(r.turn.output_tokens for r in done)
        pool_cap = sum(self.cap.values())
        pool_util = sum(
            sum(v) / max(1, len(v)) * self.cap[n] for n, v in self.util_samples.items()
        ) / max(1.0, pool_cap)
        hbm_u = self.util_samples.get("hbm", [0.0])
        lower_hits = self.m["reuse_hit_lower"]
        reuse_total = (
            self.m["reuse_hit_hbm"] + lower_hits + self.m["reuse_miss_dropped"]
        )
        prom = self.m["migrations_promotion"]
        # hindsight "useful" HBM: running KV + retained KV that is accessed again later
        acc = defaultdict(list)
        for r in done:
            if r.turn.turn > 0:
                acc[r.turn.session].append(r.arrival)
        useful = []
        for t, running, retained in self.hbm_snap:
            u = running + sum(
                b for sid, b in retained if any(a > t for a in acc.get(sid, ()))
            )
            useful.append(u / self.cap["hbm"])
        useful_hbm = sum(useful) / max(1, len(useful))
        return {
            "policy": self.policy_name,
            "requests": len(done),
            "duration_s": dur,
            "slo_goodput_tok_s": good / dur,
            "raw_throughput_tok_s": outtok / dur,
            "slo_attainment": sum(
                1 for a, b in zip(ttfts, tpots) if a <= TTFT_SLO_S and b <= TPOT_SLO_S
            )
            / len(done),
            "ttft_p50_s": weighted_pct(ttfts, 0.50),
            "ttft_p99_s": weighted_pct(ttfts, 0.99),
            "tpot_p50_s": weighted_pct(tpots, 0.50),
            "tpot_p99_s": weighted_pct(tpots, 0.99),
            "hbm_util_mean": sum(hbm_u) / len(hbm_u),
            "pool_util_mean": pool_util,
            "useful_hbm_util": useful_hbm,
            "engine_busy_frac": busy_time / dur,
            "reuse_hbm_hit_rate": self.m["reuse_hit_hbm"] / reuse_total
            if reuse_total
            else float("nan"),
            "reuse_lower_hit_rate": lower_hits / reuse_total
            if reuse_total
            else float("nan"),
            "reuse_miss_rate": self.m["reuse_miss_dropped"] / reuse_total
            if reuse_total
            else float("nan"),
            "recompute_tokens": self.m["recompute_tokens"],
            "preemptions": self.m["preemptions"],
            "demand_promotions": self.m["demand_promotions"],
            "promotion_wait_mean_s": self.m["promotion_wait_s"]
            / max(1, self.m["demand_promotions"]),
            "policy_promotions": prom,
            "prefetch_hit": self.m["prefetch_hit"],
            "unnecessary_promotion": max(0, prom - self.m["prefetch_hit"]),
            "unnecessary_demotion": self.m["unnecessary_demotion"],
            "policy_demotions": self.m["migrations_demotion"],
            "policy_drops": self.m["drop_by_policy"],
            "runtime_lru_drops": self.m["runtime_lru_drop"],
            "migration_GiB": self.m["migration_bytes"] / 2**30,
            "transfer_time_s": self.m["transfer_time_s"],
            "thrash_events": self.m["thrash_events"],
            "steps": self.m["steps"],
            "steps_with_dma_frac": self.m["steps_with_dma"] / max(1, self.m["steps"]),
            "decision_overhead_model_ms": self.sched.stats.decision_overhead_us / 1e3,
            "decision_overhead_wall_ms": self.decision_wall_s * 1e3,
            "events": self.sched.stats.pushed,
            "decision_rejected": self.m["decision_rejected"],
            "truncated": self.m["truncated"],
            "rejected_requests": self.m["rejected_requests"],
        }


def simulate(
    hw: ServingHW, sm: StepModel, policy: str, turns: list[Turn], **kw
) -> dict:
    return ServingSim(hw, sm, policy, turns, **kw).run()
