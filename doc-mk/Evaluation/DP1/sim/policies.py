from __future__ import annotations

import math
import os
import random
import zlib
from collections import defaultdict, deque
from dataclasses import dataclass

from events import EventType, MigrationEvent
from registry import C1DataObjectRegistry, C2DataObjectRegistry


def clamp(x: float, lo: float = 0.0, hi: float = 1.0) -> float:
    return max(lo, min(hi, x))


@dataclass
class Telemetry:
    capacity_util: float = 0.0
    bw_util: float = 0.0


@dataclass
class ResourceState:
    current_pressure: float
    current_bw: float
    predicted_pressure: float
    predicted_bw: float
    capacity_headroom: float


# ---------------------------------------------------------------------------
# Global design parameters of the migration economics layer (loop iteration 1).
# Each is ONE value for every scenario / system / candidate; justification in
# results/iterations/loop-log.md (Iteration 1).
# ---------------------------------------------------------------------------
MIGRATION_EXPOSURE = 0.20   # fraction of a transfer's duration exposed to the next access (executor, single source)
LINK_SHARE = 0.25           # migration may use at most this share of link time (token-bucket refill rate)
COOLDOWN_S = 8.0            # per-object cooldown == budget window
BURST_CAP_S = float(os.environ["DP1_BURST_CAP_S"]) if os.environ.get("DP1_BURST_CAP_S") else None  # iteration 4 sweep knob; None = LINK_SHARE x window (registered behaviour)
MODEL_ERROR = 0.0   # eps: lognormal sigma on access-cost estimates (systematic, both candidates) and on C2's
                    # predicted hotness (per call, C2 only). 0.0 = registered setting. Reporting-only knob.
_ERR_SEED = 0
_PRED_RNG = random.Random(0)


def set_model_error(eps: float, seed: int = 0) -> None:
    global MODEL_ERROR, _ERR_SEED, _PRED_RNG
    MODEL_ERROR = float(eps)
    _ERR_SEED = int(seed)
    _PRED_RNG = random.Random(seed * 104729 + 17)


def _est_factor(key) -> float:
    if MODEL_ERROR <= 0.0:
        return 1.0
    r = random.Random(zlib.crc32(repr((key, _ERR_SEED)).encode()))
    return math.exp(r.gauss(0.0, MODEL_ERROR))


BENEFIT_HORIZON_S = 30.0    # C2 look-ahead over which predicted stall savings are counted
HIGH_WATERMARK = 0.82       # capacity pressure at which a tier is "pressured" (unchanged since first pass)
AFFINITY_MARGIN = 2.0       # C1 swap hysteresis: static penalty gain must be >= 2x the static penalty loss (iteration 3)


class AccessCostEstimator:
    """Resource-Manager side serving-cost model, built ONLY from memory descriptors
    (ext_bw, write_bw, latency, near-data primitives, int_bw, compute) and a generic operation hint
    (op class + shape). It never sees a data-type name, so both C1 (type-agnostic) and C2 may use it.

    estimate(tier, hint, size) -> (ttft_s, tpot_s) of one access served with the object resident in `tier`.
    Returns None when the hint carries no operation class (cost unknown -> callers apply no cost filter).
    """

    def __init__(self, system):
        self.system = system
        self._cache = {}

    def estimate(self, tier: str, hint: dict, size_bytes: float):
        op = hint.get("op") if hint else None
        if op is None:
            return None
        key = (
            tier, op, hint.get("ctx_tokens"), hint.get("concurrency"), hint.get("out_tokens"),
            int(hint.get("touch_bytes", 0)), hint.get("vec_dim"), int(size_bytes),
        )
        v = self._cache.get(key)
        if v is None:
            v = self._estimate(tier, op, hint, size_bytes)
            if v is not None and tier != "hbm" and MODEL_ERROR > 0.0:
                f = _est_factor(key)
                v = (v[0] * f, v[1] * f)
            self._cache[key] = v
        return v

    def _estimate(self, tier, op, hint, size):
        sysm = self.system
        mem = sysm.memories[tier]
        ctx = int(hint.get("ctx_tokens", 8192))
        batch = int(hint.get("concurrency", 1))
        out = max(1, int(hint.get("out_tokens", 64)))
        touch = float(hint.get("touch_bytes", size))
        base_ttft = sysm.prefill_s(ctx, min(2048, ctx))
        dec_hbm = sysm.decode_step_s(ctx, batch, "hbm")
        if op == "attention":
            if tier == "hbm":
                return base_ttft, dec_hbm
            if mem.attention_capable:
                return base_ttft, sysm.decode_step_s(ctx, batch, tier)
            restore = size / max(1.0, mem.ext_bw)
            return base_ttft + restore, restore / out + dec_hbm
        if op == "weight_fetch":
            if tier == "hbm":
                return base_ttft, dec_hbm
            remote = touch / max(1.0, mem.ext_bw)
            return base_ttft + remote, dec_hbm + remote / out
        if op == "context_fetch":
            return base_ttft + touch / max(1.0, mem.ext_bw) + mem.latency_s, dec_hbm
        if op == "index_scan":
            return base_ttft + sysm.rag_retrieval_s(size, batch, tier, int(hint.get("vec_dim", 1024))), dec_hbm
        return None

    def service_extra_s(self, tier, hint, size_bytes):
        """Per-access serving penalty of `tier` relative to HBM residency (TTFT extra + decode slowdown over
        the generated tokens). 0 for HBM; None when unknown."""
        e = self.estimate(tier, hint, size_bytes)
        if e is None:
            return None
        h = self.estimate("hbm", hint, size_bytes)
        out = max(1, int(hint.get("out_tokens", 64)))
        return max(0.0, (e[0] - h[0]) + out * (e[1] - h[1]))

    def slo_ok(self, tier, hint, size_bytes, slo_ttft_s, slo_tpot_s):
        e = self.estimate(tier, hint, size_bytes)
        return True if e is None else (e[0] <= slo_ttft_s and e[1] <= slo_tpot_s)

    def budget_fraction(self, tier, hint, size_bytes, slo_ttft_s, slo_tpot_s):
        """Serving penalty as a fraction of the SLO budget (dimensionless: no tuning weight)."""
        e = self.estimate(tier, hint, size_bytes)
        if e is None:
            return 0.0
        h = self.estimate("hbm", hint, size_bytes)
        return max(0.0, (e[0] - h[0]) / slo_ttft_s, (e[1] - h[1]) / slo_tpot_s)


def est_transfer_s(system, size_bytes: float, src: str, dst: str) -> float:
    """Nominal transfer time from Memory Registry descriptors (read at src ext_bw, written at dst write limit)."""
    sm, dm = system.memories[src], system.memories[dst]
    return size_bytes / max(1.0, min(sm.ext_bw, dm.ext_bw, dm.write_bw))


class MigrationBudget:
    """Link-time token bucket (seconds of transfer). Refill LINK_SHARE s per second, capacity
    LINK_SHARE * BUDGET_WINDOW. A migration whose transfer time exceeds the capacity is never admitted."""

    def __init__(self, share: float = LINK_SHARE, window_s: float = COOLDOWN_S):
        self.share = share
        self.cap = share * window_s if BURST_CAP_S is None else min(share * window_s, BURST_CAP_S)
        self.tokens = self.cap
        self.last = None
        self.spent_s = 0.0
        self.reserved = 0.0  # tokens held back for an in-flight swap's promotion step

    def refill(self, now_s: float) -> None:
        if self.last is not None:
            self.tokens = min(self.cap, self.tokens + self.share * max(0.0, now_s - self.last))
        self.last = now_s

    def can_spend(self, seconds: float) -> bool:
        return seconds <= self.tokens - self.reserved

    def try_spend(self, seconds: float, use_reserved: bool = False) -> bool:
        if seconds > (self.tokens if use_reserved else self.tokens - self.reserved):
            return False
        self.tokens -= seconds
        self.spent_s += seconds
        return True


@dataclass(frozen=True)
class MigrationDecision:
    object_id: int
    source_tier: str
    target_tier: str
    reason: str
    score: float
    direction: str
    # MOVE copies bytes source->target. DROP frees the source copy and promotes the
    # already-existing replica at target_tier to authoritative (no transfer).
    action: str = "MOVE"


class ResourceStateMonitor:
    """Telemetry -> current/trend/near-future ResourceState."""

    def __init__(self, window: int = 5, horizon: int = 2):
        self.window = window
        self.horizon = horizon
        self.hist = defaultdict(lambda: deque(maxlen=window))

    def observe(self, telemetry: dict[str, Telemetry]) -> None:
        for name, t in telemetry.items():
            self.hist[name].append((t.capacity_util, t.bw_util))

    def states(self, telemetry: dict[str, Telemetry]) -> dict[str, ResourceState]:
        out = {}
        for name, cur in telemetry.items():
            h = self.hist[name]
            if len(h) >= 2:
                dc = (h[-1][0] - h[0][0]) / max(1, len(h) - 1)
                db = (h[-1][1] - h[0][1]) / max(1, len(h) - 1)
            else:
                dc = db = 0.0
            out[name] = ResourceState(
                current_pressure=cur.capacity_util,
                current_bw=cur.bw_util,
                predicted_pressure=clamp(cur.capacity_util + dc * self.horizon, 0, 1.5),
                predicted_bw=clamp(cur.bw_util + db * self.horizon, 0, 2.0),
                capacity_headroom=max(0.0, 1 - cur.capacity_util),
            )
        return out


class ResourceBasedTrendAnalyzer:
    def __init__(self, high: float = 0.82, emergency: float = 0.94):
        self.high = high
        self.emergency = emergency

    def pressure_sources(self, states: dict[str, ResourceState]) -> list[tuple[str, float]]:
        sources = []
        for name, st in states.items():
            score = max(st.current_pressure, st.current_bw, st.predicted_pressure, st.predicted_bw)
            if score >= self.high:
                sources.append((name, score))
        return sorted(sources, key=lambda x: x[1], reverse=True)


class DataEvictionManager:
    """C1 victim candidate builder that never inspects AI data type."""

    def __init__(self, registry: C1DataObjectRegistry):
        self.registry = registry
        self.residency_since: dict[int, float] = defaultdict(float)

    def on_moved(self, object_id: int, now_s: float) -> None:
        self.residency_since[object_id] = now_s

    def candidates(self, source_tier: str, now_s: float) -> list:
        rows = self.registry.objects_in_tier(source_tier)

        def key(r):
            age = max(0.0, now_s - self.residency_since.get(r.object_id, 0.0))
            return (r.size_bytes * (1.0 + min(age / 60.0, 1.0)), r.object_id)

        return sorted(rows, key=key, reverse=True)


class DataMemoryAffinityMapper:
    """C1 static hints kept outside the C1 registry.

    Hints are generic sensitivity numbers supplied by the caller/runtime and do
    not include the AI data class name.
    """

    def score(self, mem, state: ResourceState, hint: dict[str, float]) -> float:
        latency_sens = clamp(float(hint.get("latency_sensitivity", 0.5)))
        bw_sens = clamp(float(hint.get("bandwidth_sensitivity", 0.5)))
        capacity_sens = clamp(float(hint.get("capacity_sensitivity", 0.5)))
        latency = 1.0 / (1.0 + mem.latency_s / 2e-6)
        bw = clamp(math.log10(max(1.0, mem.ext_bw)) / 14.0)
        cap = max(0.0, 1.0 - state.predicted_pressure)
        return (
            0.35 * cap
            + 0.25 * bw_sens * bw
            + 0.20 * latency_sens * latency
            + 0.20 * capacity_sens
            * clamp(math.log2(max(2.0, mem.capacity_bytes / (1024**3))) / 14.0)
        )


# Data-Memory Affinity ablation (reporting only): DP1_C1_AFFINITY = full | no_score | no_promo | none
#   score  = affinity score in the Destination Tier Selector (static latency/bandwidth/capacity sensitivity hints)
#   promo  = static-affinity promotion/swap pass (design 17.2)
# The shared access-cost estimator (op class + shape) stays in every variant: it is a module C1 and C2 share.
C1_AFFINITY_MODE = os.environ.get("DP1_C1_AFFINITY", "full")


class DestinationTierSelectorC1:
    """Capability/transfer-cost/affinity based destination choice (type-agnostic).

    Inputs (design 8.7): resource state per tier, Memory Registry descriptors (via the shared
    AccessCostEstimator), static affinity hint. Iteration 1 adds the destination's serving cost:
      * SLO feasibility filter (estimated TTFT/TPOT at the destination must meet the SLO, unless the
        source already violates it and the destination is strictly better)
      * do-no-harm for non-HBM sources (rebalance must not increase the per-access service penalty)
      * score = affinity - serving penalty as a fraction of the SLO budget
    """

    def __init__(self, system, affinity: DataMemoryAffinityMapper, estimator: AccessCostEstimator | None = None, use_score: bool = True):
        self.use_score = use_score
        self.system = system
        self.affinity = affinity
        self.estimator = estimator or AccessCostEstimator(system)

    def select(self, rec, source: str, states, occupancy, capacity_by_tier, hint, slo=(2.0, 0.050),
               strict_pressure=True):
        est = self.estimator
        src_pen = est.service_extra_s(source, hint, rec.size_bytes)
        src_ok = est.slo_ok(source, hint, rec.size_bytes, *slo)
        candidates = []
        for name, mem in self.system.memories.items():
            if name == source:
                continue
            cap = capacity_by_tier.get(name, mem.capacity_bytes)
            free = max(0.0, cap - occupancy.get(name, 0.0))
            if free + 1e-6 < rec.size_bytes:
                continue
            if strict_pressure and states[name].predicted_pressure >= states[source].predicted_pressure:
                continue
            pen = est.service_extra_s(name, hint, rec.size_bytes)
            if pen is not None and src_pen is not None:
                better = pen < src_pen
                if not est.slo_ok(name, hint, rec.size_bytes, *slo) and not (not src_ok and better):
                    continue
                if source != "hbm" and pen > src_pen + 1e-9:
                    continue  # do-no-harm: lateral/downward rebalance must not slow serving
            base = self.affinity.score(mem, states[name], hint) if self.use_score else max(0.0, 1.0 - states[name].predicted_pressure)
            score = base - est.budget_fraction(
                name, hint, rec.size_bytes, *slo
            )
            candidates.append((score, name))
        return max(candidates)[1] if candidates else None


class MigrationDataSelectorC1:
    def select(self, candidates, required_free_bytes: float) -> list:
        picked = []
        freed = 0.0
        for rec in candidates:
            picked.append(rec)
            freed += rec.size_bytes
            if freed >= required_free_bytes:
                break
        return picked


class C1ResourceDrivenMigration:
    name = "C1-resource-driven"
    decision_cost_us = 14.0

    def __init__(self, system, drop_enabled: bool = False):
        self.system = system
        self.drop_enabled = drop_enabled
        self.registry = C1DataObjectRegistry()
        self.monitor = ResourceStateMonitor()
        self.trend = ResourceBasedTrendAnalyzer()
        self.eviction = DataEvictionManager(self.registry)
        self.affinity = DataMemoryAffinityMapper()
        self.estimator = AccessCostEstimator(system)
        self.use_aff_score = C1_AFFINITY_MODE in ("full", "no_promo")
        self.use_aff_promo = C1_AFFINITY_MODE in ("full", "no_score")
        self.destination = DestinationTierSelectorC1(system, self.affinity, self.estimator, use_score=self.use_aff_score)
        self.selector = MigrationDataSelectorC1()
        self.budget = MigrationBudget()
        self.cooldown_s = COOLDOWN_S
        self.last_migration = defaultdict(lambda: -1e9)
        self.last_states = None
        self.pending_promotion: dict[int, float] = {}  # promotee -> deadline (victims already demoted)

    def on_event(self, ev: MigrationEvent, ctx):
        if ev.type is EventType.ALLOCATED:
            self.registry.add(
                ev.object_id,
                ev.metadata["size_bytes"],
                ev.metadata["tier"],
                replica_tier=ev.metadata.get("replica_tier"),
            )
            self.eviction.on_moved(ev.object_id, ev.now_s)
            return [], 2.0
        if ev.type is EventType.FREED:
            self.registry.remove(ev.object_id)
            return [], 1.0
        if ev.type is not EventType.TELEMETRY:
            return [], 0.2

        telemetry = ev.metadata["telemetry"]
        self.monitor.observe(telemetry)
        states = self.monitor.states(telemetry)
        self.last_states = states
        self.budget.refill(ev.now_s)
        slo = (ctx.slo_ttft_s, ctx.slo_tpot_s)
        decisions = []

        for source, pressure in self.trend.pressure_sources(states):
            if source not in ctx.occupancy:
                continue
            cap = ctx.effective_capacity.get(
                source, self.system.memories[source].capacity_bytes
            )
            target_util = 0.72
            required = max(
                0.0, ctx.occupancy.get(source, 0.0) - target_util * cap
            )
            if required <= 0 and pressure < 0.94:
                continue
            if required <= 0:
                required = 0.05 * cap

            candidates = [
                r
                for r in self.eviction.candidates(source, ev.now_s)
                if ev.now_s - self.last_migration[r.object_id] >= self.cooldown_s
            ]
            for rec in self.selector.select(candidates, required):
                hint = ctx.static_affinity_hints.get(rec.object_id, {})
                # DROP: zero-transfer demotion when a valid replica already exists.
                # Same feasibility rule as a MOVE target (target must be less
                # pressured than the source); uses only generic registry metadata.
                rt = rec.replica_tier
                if (
                    self.drop_enabled
                    and source == "hbm"
                    and rt is not None
                    and rt != source
                    and rt in states
                    and states[rt].predicted_pressure
                    < states[source].predicted_pressure
                ):
                    decisions.append(
                        MigrationDecision(
                            rec.object_id,
                            source,
                            rt,
                            reason="resource_pressure",
                            score=pressure,
                            direction="demotion",
                            action="DROP",
                        )
                    )
                    continue
                dst = self.destination.select(
                    rec, source, states, ctx.occupancy, ctx.effective_capacity, hint, slo
                )
                if dst is not None:
                    if not self.budget.try_spend(est_transfer_s(self.system, rec.size_bytes, source, dst)):
                        continue
                    decisions.append(
                        MigrationDecision(
                            rec.object_id,
                            source,
                            dst,
                            reason="resource_pressure",
                            score=pressure,
                            direction="demotion" if source == "hbm" else "rebalance",
                        )
                    )
        if self.use_aff_promo:
            decisions += self._promotion_pass(ev, ctx, states, slo, decisions)
        return decisions, self.decision_cost_us * max(1, len(decisions))

    def _promotion_pass(self, ev, ctx, states, slo, planned):
        """Design 17.2: promotion trigger = static affinity prefers the upper tier for an object that sits in a
        lower tier. Static only: an object qualifies when the estimator (descriptors + operation hint, no rate,
        no type name) says it violates the SLO where it is but meets it in HBM. If HBM has no room, swap it
        against HBM residents whose static demotion penalty is far smaller (AFFINITY_MARGIN).

        A swap is a small plan (victim demotions, then the promotion) executed step by step under the link
        budget; one swap is in flight at a time, and once its victims are out the promotion's transfer time is
        reserved in the budget so that other migrations cannot starve it."""
        up = "hbm"
        out = []
        if up not in self.system.memories or up not in ctx.effective_capacity:
            return out
        est = self.estimator
        occ = dict(ctx.occupancy)
        moved = set()
        for d in planned:  # account for this cycle's demotions
            if d.action == "MOVE":
                rec = self.registry.get(d.object_id)
                occ[d.source_tier] = occ.get(d.source_tier, 0.0) - rec.size_bytes
                occ[d.target_tier] = occ.get(d.target_tier, 0.0) + rec.size_bytes
            moved.add(d.object_id)
        cap_up = ctx.effective_capacity[up]

        def xf(rec, src, dst):
            return est_transfer_s(self.system, rec.size_bytes, src, dst)

        def advance(oid, plan):
            """Run as many steps of one swap plan as the budget allows. Returns True when finished/invalid."""
            rec = self.registry.get(oid)
            if rec is None or rec.tier == up or ev.now_s > plan["deadline"]:
                return True
            for vid, dst in list(plan["victims"]):
                v = self.registry.get(vid)
                if v is None or v.tier != up:
                    plan["victims"].remove((vid, dst))
                    continue
                if vid in moved:
                    continue
                if ctx.effective_capacity.get(dst, 0.0) - occ.get(dst, 0.0) + 1e-6 < v.size_bytes:
                    return True  # destination filled up meanwhile: abandon the plan
                if not self.budget.try_spend(xf(v, up, dst)):
                    return False
                out.append(MigrationDecision(vid, up, dst, reason="static_affinity_swap",
                                             score=plan["gain"], direction="demotion"))
                occ[up] -= v.size_bytes
                occ[dst] = occ.get(dst, 0.0) + v.size_bytes
                moved.add(vid)
                plan["victims"].remove((vid, dst))
            if cap_up - occ.get(up, 0.0) < rec.size_bytes:
                return False
            if not self.budget.try_spend(xf(rec, rec.tier, up), use_reserved=True):
                self.budget.reserved = xf(rec, rec.tier, up)
                return False
            out.append(MigrationDecision(oid, rec.tier, up, reason="static_affinity_promotion",
                                         score=plan["gain"], direction="promotion"))
            occ[rec.tier] = occ.get(rec.tier, 0.0) - rec.size_bytes
            occ[up] = occ.get(up, 0.0) + rec.size_bytes
            moved.add(oid)
            return True

        for oid, plan in list(self.pending_promotion.items()):
            if advance(oid, plan):
                del self.pending_promotion[oid]
                self.budget.reserved = 0.0
        if self.pending_promotion:
            return out  # one swap in flight at a time

        cands = []
        for rec in self.registry:
            if rec.tier == up or not rec.movable or rec.object_id in moved:
                continue
            if ev.now_s - self.last_migration[rec.object_id] < self.cooldown_s:
                continue
            hint = ctx.static_affinity_hints.get(rec.object_id, {})
            pen = est.service_extra_s(rec.tier, hint, rec.size_bytes)
            if pen is None or est.slo_ok(rec.tier, hint, rec.size_bytes, *slo):
                continue
            if not est.slo_ok(up, hint, rec.size_bytes, *slo):
                continue
            cands.append((pen, rec))
        cands.sort(key=lambda x: (-x[0], x[1].object_id))
        for gain, rec in cands:
            need = max(
                rec.size_bytes - max(0.0, cap_up - occ.get(up, 0.0)),
                occ.get(up, 0.0) + rec.size_bytes - HIGH_WATERMARK * cap_up,
            )
            victims = []
            if need > 0:
                scored = []
                for v in self.registry.objects_in_tier(up):
                    if v.object_id in moved or ev.now_s - self.last_migration[v.object_id] < self.cooldown_s:
                        continue
                    vh = ctx.static_affinity_hints.get(v.object_id, {})
                    dst = self.destination.select(
                        v, up, states, occ, ctx.effective_capacity, vh, slo, strict_pressure=False
                    )
                    vloss = None if dst is None else est.service_extra_s(dst, vh, v.size_bytes)
                    if vloss is not None:
                        scored.append((vloss / v.size_bytes, v.object_id, v, dst, vloss))
                scored.sort(key=lambda x: (x[0], x[1]))
                freed = loss = 0.0
                tmp = dict(occ)
                for _, _, v, dst, vloss in scored:
                    if freed >= need:
                        break
                    if ctx.effective_capacity.get(dst, 0.0) - tmp.get(dst, 0.0) + 1e-6 < v.size_bytes:
                        continue
                    victims.append((v.object_id, dst))
                    freed += v.size_bytes
                    loss += vloss
                    tmp[dst] = tmp.get(dst, 0.0) + v.size_bytes
                if freed < need or gain < AFFINITY_MARGIN * loss:
                    continue
            plan = dict(victims=victims, gain=gain, deadline=ev.now_s + 4 * self.cooldown_s)
            if not advance(rec.object_id, plan):
                self.pending_promotion[rec.object_id] = plan
            break  # one swap in flight at a time
        return out

    def on_migration_committed(
        self, decision: MigrationDecision, now_s: float
    ) -> None:
        if decision.action == "DROP":
            self.registry.drop_to_replica(decision.object_id)
        else:
            self.registry.move(decision.object_id, decision.target_tier)
        self.eviction.on_moved(decision.object_id, now_s)
        self.last_migration[decision.object_id] = now_s


class StaticNoMigration:
    """Common Reference Baseline (QA1 T_ref): As-Is proxy.

    Initial placement is fixed by the common external allocator and never revisited:
    no migration layer, tier order fixed, no reaction to pressure or data behavior.
    """

    name = "Baseline-static"
    decision_cost_us = 0.0

    def __init__(self, system, drop_enabled: bool = False):
        self.system = system

    def on_event(self, ev, ctx):
        return [], 0.0

    def on_migration_committed(self, decision, now_s):
        pass


class DataBehaviorMonitor:
    def __init__(self, alpha: float = 0.2):
        self.alpha = alpha
        self.rate_ewma = defaultdict(float)
        self.samples = defaultdict(int)
        self.last_access = {}
        self.reuse_ewma = {}
        self.first_seen = {}

    def observe_alloc(self, oid: int, now_s: float) -> None:
        self.first_seen.setdefault(oid, now_s)

    def observe_access(self, oid: int, count: float, now_s: float) -> None:
        self.first_seen.setdefault(oid, now_s)
        n = self.samples[oid]
        self.rate_ewma[oid] = (
            count
            if n == 0
            else (1 - self.alpha) * self.rate_ewma[oid] + self.alpha * count
        )
        if count > 0:
            if oid in self.last_access:
                interval = max(1e-3, now_s - self.last_access[oid])
                old = self.reuse_ewma.get(oid, interval)
                self.reuse_ewma[oid] = (
                    (1 - self.alpha) * old + self.alpha * interval
                )
            self.last_access[oid] = now_s
        self.samples[oid] += 1

    def features(self, oid: int, now_s: float) -> dict[str, float]:
        last = self.last_access.get(oid)
        interval = self.reuse_ewma.get(oid)
        idle = float("inf") if last is None else max(0.0, now_s - last)
        if interval is None or last is None:
            rate_per_s = None
        else:
            # accesses/s = (EWMA count per access event) / (EWMA inter-access interval), decayed once idle
            # for longer than two intervals (no access seen -> the object is cooling down).
            rate_per_s = self.rate_ewma[oid] / max(1.0, interval) * min(1.0, 2.0 * interval / max(idle, 1e-3))
        return {
            "rate_per_s": rate_per_s,
            "rate": self.rate_ewma[oid],
            "samples": float(self.samples[oid]),
            "reuse_interval_s": self.reuse_ewma.get(oid, float("inf")),
            "idle_s": (
                float("inf") if last is None else max(0.0, now_s - last)
            ),
            "age_s": max(
                0.0, now_s - self.first_seen.get(oid, now_s)
            ),
        }


class BehaviorBasedTrendAnalyzer:
    def analyze(self, rec, feat: dict[str, float]) -> dict[str, float]:
        prior_hot = float(rec.class_metadata.get("hotness", 0.5))
        rate_hot = clamp(feat["rate"] / 0.35)
        n = feat["samples"]
        prior_w = max(0.15, math.exp(-n / 6.0))
        hotness = clamp(prior_w * prior_hot + (1 - prior_w) * rate_hot)
        interval = feat["reuse_interval_s"]
        reuse = (
            0.0
            if not math.isfinite(interval)
            else 1 - math.exp(-5.0 / max(1e-3, interval))
        )
        age = clamp(feat["age_s"] / 120.0)
        return {
            "hotness": hotness,
            "reuse": reuse,
            "age": age,
            "idle_s": feat["idle_s"],
        }


class FutureBehaviorPredictor:
    def predict(self, rec, trend: dict[str, float]) -> float:
        prior_reuse = float(rec.class_metadata.get("reuse", 0.5))
        prior_lifetime = float(rec.class_metadata.get("lifetime", 0.5))
        idle_penalty = 0.25 if trend["idle_s"] > 10 else 0.0
        return clamp(
            0.45 * trend["hotness"]
            + 0.25 * max(trend["reuse"], prior_reuse)
            + 0.20 * prior_lifetime
            + 0.10 * trend["age"]
            - idle_penalty
        )


def expected_rate(rec, feat) -> float:
    """Predicted near-future accesses/s: observed rate blended with the class prior while the object is young
    (same prior weight as BehaviorBasedTrendAnalyzer; 0.35/s == hotness 1.0 as in that analyzer)."""
    if "oracle_rate_per_s" in feat:   # Oracle-approx only: true mean rate over the benefit horizon
        return feat["oracle_rate_per_s"]
    prior_rate = float(rec.class_metadata.get("hotness", 0.5)) * 0.35
    obs = feat.get("rate_per_s")
    if obs is None:
        return prior_rate
    prior_w = max(0.15, math.exp(-feat["samples"] / 6.0))
    return prior_w * prior_rate + (1 - prior_w) * obs


TYPE_TIER_PREFERENCE = {
    "KV_CACHE": ("hbm", "custom_hbm", "cxl_pnm", "dram", "hbf"),
    "RAG_DATA": ("hbm", "hbf", "dram", "ssd_pim", "cxl_pnm"),
    "AGENT_MEMORY": ("hbm", "dram", "hbf", "ssd_pim", "cxl_pnm"),
    "TOOL_RESULT": ("hbm", "dram", "hbf", "ssd_pim"),
    "LORA_ADAPTER": ("hbm", "hbf", "dram", "cxl_pnm"),
    "MOE_EXPERT": ("hbm", "hbf", "dram", "custom_hbm", "cxl_pnm"),
}


class DestinationTierSelectorC2:
    def __init__(self, system, estimator: AccessCostEstimator | None = None):
        self.system = system
        self.estimator = estimator or AccessCostEstimator(system)

    def preferred(self, rec) -> tuple[str, ...]:
        return tuple(
            x
            for x in TYPE_TIER_PREFERENCE.get(
                rec.data_type, tuple(self.system.memories)
            )
            if x in self.system.memories
        )

    def select(
        self, rec, predicted: float, telemetry, occupancy, capacity_by_tier, hint=None, slo=(2.0, 0.050)
    ):
        pref = self.preferred(rec)
        hint = hint or {}
        src_pen = self.estimator.service_extra_s(rec.tier, hint, rec.size_bytes)
        feasible = []
        for rank, name in enumerate(pref):
            mem = self.system.memories[name]
            cap = capacity_by_tier.get(name, mem.capacity_bytes)
            if (
                cap - occupancy.get(name, 0.0) + 1e-6
                < rec.size_bytes
            ):
                continue
            if telemetry[name].capacity_util >= 0.95:
                continue
            # Iteration 1: destination must serve within the SLO (or, if the object already violates it
            # at its current tier, at least be strictly better there).
            pen = self.estimator.service_extra_s(name, hint, rec.size_bytes)
            if pen is not None and not self.estimator.slo_ok(name, hint, rec.size_bytes, *slo):
                src_ok = self.estimator.slo_ok(rec.tier, hint, rec.size_bytes, *slo)
                if src_ok or src_pen is None or pen >= src_pen:
                    continue
            feasible.append((rank, name))
        if not feasible:
            return None
        pens = {
            name: self.estimator.service_extra_s(name, hint, rec.size_bytes) for _, name in feasible
        }
        if all(v is not None for v in pens.values()):
            # Iteration 1: access-cost aware matching. Predicted-hot objects take the cheapest feasible tier
            # (HBM when it has room); everything else takes the cheapest feasible NON-HBM tier, ties broken
            # by type preference rank. HBM is reserved for objects predicted hot.
            if predicted >= 0.72:
                return min(feasible, key=lambda x: (pens[x[1]], x[0]))[1]
            lower = [x for x in feasible if x[1] != "hbm"]
            if not lower:
                return None
            return min(lower, key=lambda x: (pens[x[1]], x[0]))[1]
        if predicted >= 0.72:
            return feasible[0][1]
        if predicted <= 0.35:
            return max(
                feasible,
                key=lambda x: self.system.memories[x[1]].capacity_bytes,
            )[1]
        idx = min(len(feasible) - 1, max(0, len(feasible) // 2))
        return feasible[idx][1]


class C2BehaviorDrivenMigration:
    name = "C2-behavior-driven"
    decision_cost_us = 38.0

    def __init__(self, system, priors: dict[str, dict], drop_enabled: bool = False):
        self.system = system
        self.drop_enabled = drop_enabled
        self.priors = priors
        self.registry = C2DataObjectRegistry()
        self.monitor = DataBehaviorMonitor()
        self.trend = BehaviorBasedTrendAnalyzer()
        self.predictor = FutureBehaviorPredictor()
        self.estimator = AccessCostEstimator(system)
        self.destination = DestinationTierSelectorC2(system, self.estimator)
        self.budget = MigrationBudget()
        self.cooldown_s = COOLDOWN_S
        self.horizon_s = BENEFIT_HORIZON_S
        self.last_migration = defaultdict(lambda: -1e9)
        self.last_prediction = {}

    def on_event(self, ev: MigrationEvent, ctx):
        if ev.type is EventType.ALLOCATED:
            dt = ev.metadata["data_type"]
            self.registry.add(
                ev.object_id,
                dt,
                ev.metadata["size_bytes"],
                ev.metadata["tier"],
                class_metadata=self.priors.get(dt, {}),
                replica_tier=ev.metadata.get("replica_tier"),
            )
            self.monitor.observe_alloc(ev.object_id, ev.now_s)
            return [], 3.0
        if ev.type is EventType.FREED:
            self.registry.remove(ev.object_id)
            return [], 1.0
        if ev.type is EventType.ACCESSED:
            if self.registry.get(ev.object_id) is not None:
                self.monitor.observe_access(
                    ev.object_id, ev.count, ev.now_s
                )
            return [], 1.0
        if ev.type is not EventType.TELEMETRY:
            return [], 0.5

        telemetry = ev.metadata["telemetry"]
        self.budget.refill(ev.now_s)
        slo = (ctx.slo_ttft_s, ctx.slo_tpot_s)
        planned = []  # (priority, decision)
        for rec in list(self.registry):
            if (
                ev.now_s - self.last_migration[rec.object_id]
                < self.cooldown_s
            ):
                continue
            feat = self.monitor.features(rec.object_id, ev.now_s)
            trend = self.trend.analyze(rec, feat)
            pred = self.predictor.predict(rec, trend)
            if MODEL_ERROR > 0.0:
                pred = clamp(pred * math.exp(_PRED_RNG.gauss(0.0, MODEL_ERROR)))
            self.last_prediction[rec.object_id] = pred
            hint = ctx.static_affinity_hints.get(rec.object_id, {})
            dst = self.destination.select(
                rec,
                pred,
                telemetry,
                ctx.occupancy,
                ctx.effective_capacity,
                hint,
                slo,
            )
            if dst is None or dst == rec.tier:
                continue
            if (
                0.42 < pred < 0.62
                and telemetry[rec.tier].capacity_util < 0.88
            ):
                continue
            direction = (
                "promotion"
                if dst == "hbm"
                else "demotion"
                if rec.tier == "hbm"
                else "rebalance"
            )
            action = "MOVE"
            # DROP: HBM demotion with a valid lower-tier replica. The replica tier
            # must be acceptable to the same destination rules (type preference
            # list, not overloaded); no capacity is needed since it already exists.
            rt = rec.replica_tier
            if (
                self.drop_enabled
                and direction == "demotion"
                and rt is not None
                and rt in self.destination.preferred(rec)
                and telemetry[rt].capacity_util < 0.95
            ):
                dst, action = rt, "DROP"

            # ---- Iteration 1 gating: benefit vs cost, pressure for demotion, budget -------------
            pen_src = self.estimator.service_extra_s(rec.tier, hint, rec.size_bytes)
            pen_dst = self.estimator.service_extra_s(dst, hint, rec.size_bytes)
            xfer_s = (
                0.0 if action == "DROP"
                else est_transfer_s(self.system, rec.size_bytes, rec.tier, dst)
            )
            if direction == "demotion":
                # design 17.3: demotion = reuse decline AND upper-tier pressure
                if telemetry[rec.tier].capacity_util < HIGH_WATERMARK:
                    continue
                priority = -expected_rate(rec, feat)  # coldest first
            else:
                if pen_src is None or pen_dst is None:
                    gain = 0.0
                else:
                    gain = pen_src - pen_dst
                benefit = expected_rate(rec, feat) * self.horizon_s * gain
                cost = MIGRATION_EXPOSURE * xfer_s
                if gain <= 0 or benefit <= cost:
                    continue
                priority = benefit - cost
            planned.append(
                (
                    priority,
                    MigrationDecision(
                        rec.object_id,
                        rec.tier,
                        dst,
                        reason="predicted_behavior",
                        score=pred,
                        direction=direction,
                        action=action,
                    ),
                    xfer_s,
                )
            )
        # demotions free upper-tier capacity first, then promotions/rebalances by net benefit
        planned.sort(key=lambda x: (x[1].direction != "demotion", -x[0]))
        decisions = []
        for _, d, xfer_s in planned:
            if xfer_s > 0 and not self.budget.try_spend(xfer_s):
                continue
            decisions.append(d)
        return decisions, self.decision_cost_us * max(1, len(self.registry))

    def on_migration_committed(
        self, decision: MigrationDecision, now_s: float
    ) -> None:
        if decision.action == "DROP":
            self.registry.drop_to_replica(decision.object_id)
        else:
            self.registry.move(decision.object_id, decision.target_tier)
        self.last_migration[decision.object_id] = now_s


class OracleBehaviorMonitor(DataBehaviorMonitor):
    """Replaces the EWMA behaviour estimate by the TRUE trace rate (perfect knowledge of the future access rate)."""

    def __init__(self, ctx_holder, horizon_s: float):
        super().__init__()
        self.ctx_holder = ctx_holder
        self.horizon_s = horizon_s

    def features(self, oid: int, now_s: float) -> dict[str, float]:
        f = super().features(oid, now_s)
        ctx = self.ctx_holder[0]
        o = ctx.objects.get(oid)
        if o is None:
            return f
        scale = getattr(ctx, "load_scale", 1.0)
        steps = max(1, int(self.horizon_s))
        mean_rate = sum(o.rate_at(now_s + k) * scale for k in range(steps)) / steps
        now_rate = o.rate_at(now_s) * scale
        f.update(
            oracle_rate_per_s=mean_rate,
            rate=now_rate,
            samples=100.0,                 # no prior blending: the estimate is exact
            reuse_interval_s=1.0 / max(1e-3, now_rate),
            idle_s=0.0,
        )
        return f


class OracleBoundMigration(C2BehaviorDrivenMigration):
    """ORACLE-APPROX upper-bound reference (not a candidate): the C2 pipeline (type-aware destination, benefit-vs-cost
    gating, cooldown, the SAME MigrationBudget and link-interference model) driven by perfect knowledge of the future access
    rate and the exact access-cost estimator (eps=0). It is an approximate bound, not a proven optimum: a candidate that
    exceeds it in a pair means the bound is not tight there (reported)."""

    name = "Oracle-approx"

    def __init__(self, system, priors, drop_enabled: bool = False):
        super().__init__(system, priors, drop_enabled)
        self._ctx = [None]
        self.monitor = OracleBehaviorMonitor(self._ctx, self.horizon_s)

    def on_event(self, ev, ctx):
        self._ctx[0] = ctx
        return super().on_event(ev, ctx)


class OracleIdealMigration(OracleBoundMigration):
    """Oracle-ideal: the Oracle-approx pipeline with FREE, instantaneous migration (no transfer time, no link interference,
    no budget, no cooldown). It removes every migration cost, so it is the reference for what perfect placement knowledge can
    buy under the capacity/bandwidth constraints. Still a heuristic placement (type preference lists, greedy by net benefit),
    hence 'ideal' not 'optimal'."""

    name = "Oracle-ideal"
    free_migration = True

    def __init__(self, system, priors, drop_enabled: bool = False):
        super().__init__(system, priors, drop_enabled)
        self.budget = MigrationBudget(share=1e9)
        self.cooldown_s = 0.0
