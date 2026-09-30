"""DP1 migration policies for the request-level vLLM serving simulation.

Same architecture boundary as policies.py (object-level simulator):

  B0  vLLM default        : no DP1. Runtime drops LRU prefix-cache KV on pressure.
  B1  LRU offload         : ~ vLLM native CPU KV offloading (--kv-offloading-size).
                            Used to validate the sim against a real migration
                            executor on A100/H100 (Phase 5).
  C1  Resource-driven     : ResourceStateMonitor/TrendAnalyzer -> type-agnostic
                            C1 registry -> generic eviction (LRU x size) ->
                            DataMemoryAffinityMapper -> DestinationTierSelectorC1.
                            Promotion only from resource recovery (§17.2).
  C2  Behavior-driven     : type-aware C2 registry -> DataBehaviorMonitor ->
                            class-level reuse-interval survival model ->
                            FutureBehaviorPredictor -> demotion / drop /
                            *proactive promotion* (§17.3).

Decisions whose ``target_tier == "drop"`` discard the object (it will be
recomputed on its next access).
"""

from __future__ import annotations

import bisect
import math
from collections import defaultdict, deque

from events import EventType, MigrationEvent
from model import DATA_PRIORS
from policies import (
    DataMemoryAffinityMapper,
    DestinationTierSelectorC1,
    MigrationDecision,
    ResourceBasedTrendAnalyzer,
    ResourceStateMonitor,
)
from registry import C1DataObjectRegistry, C2DataObjectRegistry

DROP = "drop"
KV_TYPE = "KV_CACHE"
# KV-cache destination preference (C2 type-aware). Filtered by present tiers.
KV_TIER_PREFERENCE = (
    "hbm",
    "hbf",
    "custom_hbm",
    "cxl_pnm",
    "dram",
    "cxl_mem",
    "nvme_ssd",
)


class _SystemView:
    """Adapter so DestinationTierSelectorC1 (policies.py) can iterate tiers."""

    def __init__(self, memories):
        self.memories = memories


def _decision(oid, src, dst, reason, score):
    order = {n: i for i, n in enumerate(("hbm",) + KV_TIER_PREFERENCE[1:] + (DROP,))}
    if dst == DROP:
        direction = "drop"
    elif dst == "hbm":
        direction = "promotion"
    elif src == "hbm":
        direction = "demotion"
    else:
        direction = "demotion" if order.get(dst, 9) > order.get(src, 9) else "promotion"
    return MigrationDecision(oid, src, dst, reason, score, direction)


# =============================================================================
# B0 / B1 baselines
# =============================================================================


class B0VllmDefault:
    name = "B0-vllm-lru-drop"

    def on_event(self, ev: MigrationEvent, ctx):
        return [], 0.0

    def on_migration_committed(self, d, now_s):
        pass


class B1LruOffload:
    """Store LRU prefix-cache KV to host DRAM on HBM pressure; demand-load only."""

    name = "B1-lru-offload"

    def __init__(self, high: float = 0.95, target: float = 0.90):
        self.reg = C1DataObjectRegistry()
        self.last = {}
        self.high, self.target = high, target

    def on_event(self, ev: MigrationEvent, ctx):
        _common_registry_update(self.reg, self.last, ev)
        if ev.type is not EventType.TELEMETRY or "dram" not in ctx.capacity:
            return [], 0.5
        out = []
        need = ev.metadata.get("need_bytes", 0.0)
        cap = ctx.capacity["hbm"]
        required = max(need, ctx.occupancy["hbm"] + need - self.target * cap)
        if ctx.occupancy["hbm"] / cap < self.high and need <= 0:
            required = 0.0
        freed = 0.0
        free_dram = ctx.capacity["dram"] - ctx.occupancy["dram"]
        for r in sorted(
            self.reg.objects_in_tier("hbm"),
            key=lambda r: self.last.get(r.object_id, 0.0),
        ):
            if freed >= required:
                break
            if free_dram >= r.size_bytes:
                out.append(_decision(r.object_id, "hbm", "dram", "lru_offload", 0.0))
                free_dram -= r.size_bytes
            else:
                # DRAM full: native offloading evicts LRU from CPU; here drop the victim
                out.append(_decision(r.object_id, "hbm", DROP, "lru_offload_full", 0.0))
            freed += r.size_bytes
        return out, 5.0 + 2.0 * len(out)

    def on_migration_committed(self, d, now_s):
        if d.target_tier == DROP:
            self.reg.remove(d.object_id)
        else:
            self.reg.move(d.object_id, d.target_tier)


def _common_registry_update(reg, last, ev: MigrationEvent):
    """Type-agnostic bookkeeping shared by B1/C1 (no data_type is stored)."""
    if ev.type is EventType.ALLOCATED:
        reg.add(
            ev.object_id,
            ev.metadata["size_bytes"],
            ev.metadata["tier"],
            movable=ev.metadata.get("movable", True),
        )
        last[ev.object_id] = ev.now_s
    elif ev.type is EventType.FREED:
        reg.remove(ev.object_id)
        last.pop(ev.object_id, None)
    elif ev.type is EventType.ACCESSED:
        last[ev.object_id] = ev.now_s
    elif ev.type is EventType.PHASE_CHANGE and ev.object_id is not None:
        r = reg.get(ev.object_id)
        if r is not None:
            r.movable = ev.metadata.get("movable", r.movable)
            if "size_bytes" in ev.metadata:
                r.size_bytes = float(ev.metadata["size_bytes"])
            if "tier" in ev.metadata:
                reg.move(ev.object_id, ev.metadata["tier"])
        last[ev.object_id] = ev.now_s


# =============================================================================
# C1 — Resource State-driven + Data-Memory Affinity
# =============================================================================


class C1ServingResourceDriven:
    name = "C1-resource-driven"

    def __init__(
        self,
        high: float = 0.90,
        target: float = 0.80,
        low: float = 0.55,
        eviction: str = "lru_size",
    ):
        self.reg = C1DataObjectRegistry()  # type-agnostic: id / size / tier / movable
        self.last = {}
        self.monitor = ResourceStateMonitor(window=5, horizon=2)
        self.trend = ResourceBasedTrendAnalyzer(high=high, emergency=0.97)
        self.affinity = DataMemoryAffinityMapper()
        self.high, self.target, self.low = high, target, low
        self.eviction = eviction
        # static affinity hint channel (configuration, not registry). One generic
        # hint for all objects: C1 does not know what the objects are.
        self.static_hint = {
            "latency_sensitivity": 0.8,
            "bandwidth_sensitivity": 0.8,
            "capacity_sensitivity": 0.5,
        }

    # generic eviction ordering: LRU first, larger objects first among equals
    def _victims(self, tier: str, now: float):
        rows = self.reg.objects_in_tier(tier)
        if self.eviction == "lru":
            return sorted(rows, key=lambda r: self.last.get(r.object_id, 0.0))
        # pressure-relief efficiency: idle_time x size
        return sorted(
            rows,
            key=lambda r: -(now - self.last.get(r.object_id, 0.0) + 1.0) * r.size_bytes,
        )

    def on_event(self, ev: MigrationEvent, ctx):
        _common_registry_update(self.reg, self.last, ev)
        if ev.type is not EventType.TELEMETRY:
            return [], 1.0
        tel = ev.metadata["telemetry"]
        self.monitor.observe(tel)
        states = self.monitor.states(tel)
        need = float(ev.metadata.get("need_bytes", 0.0))
        system = _SystemView(ctx.memories)
        selector = DestinationTierSelectorC1(system, self.affinity)
        occ = dict(ctx.occupancy)
        out, scanned = [], 0

        # ---- demotion from any pressured tier (HBM first) --------------------
        sources = [s for s, _ in self.trend.pressure_sources(states)]
        if need > 0 and "hbm" not in sources:
            sources.insert(0, "hbm")
        for src in sources:
            cap = ctx.capacity.get(src, 0.0)
            if cap <= 0:
                continue
            req = (
                occ.get(src, 0.0) - self.target * cap + (need if src == "hbm" else 0.0)
            )
            if req <= 0:
                continue
            freed = 0.0
            for r in self._victims(src, ev.now_s):
                if freed >= req:
                    break
                scanned += 1
                dst = selector.select(
                    r, src, states, occ, ctx.capacity, self.static_hint
                )
                if dst is None or dst == "hbm":
                    dst = DROP
                out.append(
                    _decision(
                        r.object_id,
                        src,
                        dst,
                        "resource_pressure",
                        states[src].predicted_pressure,
                    )
                )
                occ[src] = occ.get(src, 0.0) - r.size_bytes
                if dst != DROP:
                    occ[dst] = occ.get(dst, 0.0) + r.size_bytes
                freed += r.size_bytes

        # ---- resource-recovery promotion (§17.2) ------------------------------
        hbm_cap = ctx.capacity["hbm"]
        if (
            not out
            and states["hbm"].predicted_pressure < self.low
            and ctx.lane_busy("pcie") < 0.5
        ):
            budget = (self.target - 0.05) * hbm_cap - occ["hbm"]
            lower = [r for r in self.reg if r.movable and r.tier != "hbm"]
            lower.sort(key=lambda r: -self.last.get(r.object_id, 0.0))  # MRU first
            for r in lower:
                if budget < r.size_bytes:
                    break
                scanned += 1
                out.append(
                    _decision(
                        r.object_id,
                        r.tier,
                        "hbm",
                        "capacity_recovered",
                        states["hbm"].predicted_pressure,
                    )
                )
                budget -= r.size_bytes
        return out, 12.0 + 0.8 * scanned + 4.0 * len(out)

    def on_migration_committed(self, d, now_s):
        if d.target_tier == DROP:
            self.reg.remove(d.object_id)
            self.last.pop(d.object_id, None)
        else:
            self.reg.move(d.object_id, d.target_tier)


# =============================================================================
# C2 — AI Data Behavior-driven
# =============================================================================


class ClassReuseModel:
    """Per data-class reuse-interval survival model (type-aware knowledge).

    Closed intervals: retention -> next access. Open episodes are censored.
    P(reuse within h | idle a) = #(a < D <= a+h) / (#(D > a) + #open(age > a))
    Prior pseudo-counts come from DATA_PRIORS[class]["reuse"].
    """

    def __init__(
        self, prior_reuse: float, prior_interval_s: float = 10.0, window: int = 1024
    ):
        self.closed: deque[float] = deque(maxlen=window)
        self.prior_reuse = prior_reuse
        self.prior_interval = prior_interval_s

    def snapshot(self, open_ages: list[float]) -> tuple[list[float], list[float]]:
        """Sorted views taken once per decision cycle (O(log n) queries)."""
        return sorted(self.closed), sorted(open_ages)

    def p_reuse(self, idle: float, horizon: float, snap) -> float:
        closed, opened = snap
        k = 8.0  # prior strength (pseudo-observations)
        i_idle = bisect.bisect_right(closed, idle)
        hit = bisect.bisect_right(closed, idle + horizon) - i_idle
        at_risk = (len(closed) - i_idle) + (
            len(opened) - bisect.bisect_right(opened, idle)
        )
        prior_hit = (
            self.prior_reuse
            * (1 - math.exp(-horizon / self.prior_interval))
            * math.exp(-idle / (4 * self.prior_interval))
        )
        return (hit + k * prior_hit) / (at_risk + k)

    def expected_residual(self, idle: float, snap) -> float:
        closed = snap[0]
        i = bisect.bisect_right(closed, idle)
        if i >= len(closed):
            return self.prior_interval
        return closed[i + (len(closed) - i) // 2] - idle


class C2ServingBehaviorDriven:
    name = "C2-behavior-driven"

    def __init__(
        self,
        horizon_s: float = 30.0,
        cooldown_s: float = 3.0,
        p_keep: float = 0.5,
        p_drop: float = 0.08,
        min_prefetch_s: float = 0.02,
        p_prefetch: float = 0.3,
        pressure_util: float = 0.80,
        promote_util: float = 0.75,
    ):
        self.reg = C2DataObjectRegistry()  # type-aware
        self.class_model: dict[str, ClassReuseModel] = {}
        self.retained_at: dict[int, float] = {}  # object became idle (movable) at
        self.obj_interval: dict[int, float] = {}  # per-object reuse-interval EWMA
        self.last_move = defaultdict(lambda: -1e9)
        self.horizon, self.cooldown = horizon_s, cooldown_s
        self.p_keep, self.p_drop = p_keep, p_drop
        self.min_prefetch_s = min_prefetch_s
        self.p_prefetch = p_prefetch
        self.pressure_util = (
            pressure_util  # HBM util above which cold objects are demoted
        )
        self.promote_util = promote_util  # promotions may fill HBM up to this util
        self.pred_log: dict[
            int, tuple[float, float]
        ] = {}  # oid -> (t_pred, p) for accuracy
        # evicted/dropped objects keep their open retention episode so that a
        # later re-access is still learned (prediction-miss signal)
        self.ghost: dict[int, str] = {}

    def _cm(self, dt: str) -> ClassReuseModel:
        if dt not in self.class_model:
            self.class_model[dt] = ClassReuseModel(
                DATA_PRIORS.get(dt, {}).get("reuse", 0.5)
            )
        return self.class_model[dt]

    # -- Data Behavior Monitor ------------------------------------------------
    def _observe(self, ev: MigrationEvent):
        if ev.type is EventType.ALLOCATED:
            self.reg.add(
                ev.object_id,
                ev.metadata.get("data_type", KV_TYPE),
                ev.metadata["size_bytes"],
                ev.metadata["tier"],
                class_metadata=DATA_PRIORS.get(
                    ev.metadata.get("data_type", KV_TYPE), {}
                ),
                movable=ev.metadata.get("movable", True),
            )
            self.ghost.pop(ev.object_id, None)
        elif ev.type is EventType.FREED:
            r = self.reg.get(ev.object_id)
            if r is not None:
                self.ghost[ev.object_id] = r.data_type
            self.reg.remove(ev.object_id)
        elif ev.type is EventType.ACCESSED:
            r = self.reg.get(ev.object_id)
            dt = r.data_type if r is not None else self.ghost.pop(ev.object_id, None)
            t0 = self.retained_at.pop(ev.object_id, None)
            if dt is not None and t0 is not None:
                d = ev.now_s - t0
                self._cm(dt).closed.append(d)
                old = self.obj_interval.get(ev.object_id)
                self.obj_interval[ev.object_id] = (
                    d if old is None else 0.5 * old + 0.5 * d
                )
                if r is not None:
                    r.behavior_metadata["accesses"] = (
                        r.behavior_metadata.get("accesses", 0) + 1
                    )
        elif ev.type is EventType.PHASE_CHANGE and ev.object_id is not None:
            r = self.reg.get(ev.object_id)
            if r is None:
                return
            r.movable = ev.metadata.get("movable", r.movable)
            if "size_bytes" in ev.metadata:
                r.size_bytes = float(ev.metadata["size_bytes"])
            if "tier" in ev.metadata:
                self.reg.move(ev.object_id, ev.metadata["tier"])
            if r.movable:
                self.retained_at[ev.object_id] = ev.now_s

    # -- Behavior-based Trend Analyzer + Future Behavior Predictor --------------
    def _predict(self, r, now: float, open_ages_by_class) -> tuple[float, float]:
        """-> (P(reuse within horizon), expected time to next access)."""
        idle = now - self.retained_at.get(r.object_id, now)
        cm = self._cm(r.data_type)
        snap = open_ages_by_class[r.data_type]
        p = cm.p_reuse(idle, self.horizon, snap)
        own = self.obj_interval.get(r.object_id)
        if own is not None:
            # object-level trend blended with class-level survival
            resid = max(0.0, own - idle)
            p_own = (
                1.0
                if resid <= self.horizon
                else math.exp(-(resid - self.horizon) / max(1.0, own))
            )
            p = 0.5 * p + 0.5 * p_own
            t_next = 0.5 * resid + 0.5 * cm.expected_residual(idle, snap)
        else:
            t_next = cm.expected_residual(idle, snap)
        return p, t_next

    def on_event(self, ev: MigrationEvent, ctx):
        self._observe(ev)
        if ev.type is not EventType.TELEMETRY:
            return [], 1.0 if ev.type is EventType.ACCESSED else 2.0
        now = ev.now_s
        need = float(ev.metadata.get("need_bytes", 0.0))
        occ = dict(ctx.occupancy)
        cap = ctx.capacity
        open_ages = defaultdict(list)
        for oid, t0 in self.retained_at.items():
            r = self.reg.get(oid)
            dt = r.data_type if r is not None else self.ghost.get(oid)
            if dt is not None:
                open_ages[dt].append(now - t0)
        snaps = defaultdict(lambda: ([], []))
        for dt in set(open_ages) | {r.data_type for r in self.reg}:
            snaps[dt] = self._cm(dt).snapshot(open_ages.get(dt, []))

        preds = {}
        for r in self.reg:
            if r.movable:
                preds[r.object_id] = self._predict(r, now, snaps)
                self.pred_log[r.object_id] = (now, preds[r.object_id][0])
        out = []
        pref = [t for t in KV_TIER_PREFERENCE if t in cap and t != "hbm"]

        def lower_dest(r, p):
            if p < self.p_drop:
                return DROP
            # restore-latency-aware: fastest restorable tier with room and no pressure
            best = None
            for t in pref:
                if occ.get(t, 0.0) + r.size_bytes > 0.95 * cap[t]:
                    continue
                rt = ctx.restore_time(t, r.size_bytes)
                if best is None or rt < best[0]:
                    best = (rt, t)
            return best[1] if best else DROP

        # ---- demotion: HBM pressure or predicted-cold objects ------------------
        hbm_util = occ["hbm"] / cap["hbm"]
        req = max(0.0, occ["hbm"] + need - 0.85 * cap["hbm"])
        hbm_objs = [r for r in self.reg.objects_in_tier("hbm") if r.object_id in preds]
        # Belady-like: lowest reuse probability, then farthest next access
        hbm_objs.sort(key=lambda r: (preds[r.object_id][0], -preds[r.object_id][1]))
        freed = 0.0
        for r in hbm_objs:
            p, t_next = preds[r.object_id]
            urgent = freed < req
            # §17.3: future reuse probability low AND upper-tier pressure building
            cold = p < 0.2 and hbm_util > self.pressure_util
            if not (urgent or cold):
                break
            if not urgent and now - self.last_move[r.object_id] < self.cooldown:
                continue
            dst = lower_dest(r, p)
            out.append(
                _decision(
                    r.object_id,
                    "hbm",
                    dst,
                    "predicted_cold" if cold and not urgent else "pressure_victim",
                    p,
                )
            )
            occ["hbm"] -= r.size_bytes
            if dst != DROP:
                occ[dst] = occ.get(dst, 0.0) + r.size_bytes
            freed += r.size_bytes

        # ---- lower-tier hygiene: drop predicted-dead objects from full tiers ----
        for t in pref:
            if occ.get(t, 0.0) < 0.9 * cap[t]:
                continue
            for r in sorted(
                self.reg.objects_in_tier(t),
                key=lambda r: preds.get(r.object_id, (1, 0))[0],
            ):
                if occ[t] < 0.8 * cap[t]:
                    break
                out.append(
                    _decision(
                        r.object_id,
                        t,
                        DROP,
                        "predicted_dead",
                        preds.get(r.object_id, (0, 0))[0],
                    )
                )
                occ[t] -= r.size_bytes

        # ---- proactive promotion (§17.3: reuse expected + upper tier available) --
        if not freed:
            budget = self.promote_util * cap["hbm"] - occ["hbm"]
            lower = [
                r
                for r in self.reg
                if r.movable and r.tier != "hbm" and r.object_id in preds
            ]
            lower.sort(key=lambda r: preds[r.object_id][1])  # soonest first
            for r in lower:
                p, t_next = preds[r.object_id]
                if budget < r.size_bytes:
                    continue
                if now - self.last_move[r.object_id] < self.cooldown:
                    continue
                restore = ctx.restore_time(r.tier, r.size_bytes)
                if restore < self.min_prefetch_s:
                    continue  # demand fetch is already cheap; prefetch only adds traffic
                idle = now - self.retained_at.get(r.object_id, now)
                lead = restore + 2 * ctx.tick_s
                p_lead = self._cm(r.data_type).p_reuse(
                    idle, lead + self.horizon * 0.2, snaps[r.data_type]
                )
                if p_lead >= self.p_prefetch or (
                    p >= self.p_keep and occ["hbm"] < 0.6 * cap["hbm"]
                ):
                    out.append(
                        _decision(r.object_id, r.tier, "hbm", "predicted_reuse", p)
                    )
                    budget -= r.size_bytes
        n_eval = len(preds)
        return out, 10.0 + 1.5 * n_eval + 4.0 * len(out)

    def on_migration_committed(self, d, now_s):
        self.last_move[d.object_id] = now_s
        if d.target_tier == DROP:
            r = self.reg.get(d.object_id)
            if r is not None:
                self.ghost[d.object_id] = r.data_type
            self.reg.remove(d.object_id)
        else:
            self.reg.move(d.object_id, d.target_tier)


POLICIES = {
    "B0-vllm-lru-drop": B0VllmDefault,
    "B1-lru-offload": B1LruOffload,
    "C1-resource-driven": C1ServingResourceDriven,
    "C2-behavior-driven": C2ServingBehaviorDriven,
}


def make_policy(name: str):
    return POLICIES[name]()
