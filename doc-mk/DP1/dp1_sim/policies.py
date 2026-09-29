from __future__ import annotations

import math
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


@dataclass(frozen=True)
class MigrationDecision:
    object_id: int
    source_tier: str
    target_tier: str
    reason: str
    score: float
    direction: str


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


class DestinationTierSelectorC1:
    def __init__(self, system, affinity: DataMemoryAffinityMapper):
        self.system = system
        self.affinity = affinity

    def select(self, rec, source: str, states, occupancy, capacity_mult, hint):
        candidates = []
        for name, mem in self.system.memories.items():
            if name == source:
                continue
            cap = mem.capacity_bytes * capacity_mult
            free = max(0.0, cap - occupancy.get(name, 0.0))
            if free + 1e-6 < rec.size_bytes:
                continue
            if states[name].predicted_pressure >= states[source].predicted_pressure:
                continue
            candidates.append((self.affinity.score(mem, states[name], hint), name))
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

    def __init__(self, system):
        self.system = system
        self.registry = C1DataObjectRegistry()
        self.monitor = ResourceStateMonitor()
        self.trend = ResourceBasedTrendAnalyzer()
        self.eviction = DataEvictionManager(self.registry)
        self.affinity = DataMemoryAffinityMapper()
        self.destination = DestinationTierSelectorC1(system, self.affinity)
        self.selector = MigrationDataSelectorC1()
        self.last_states = None

    def on_event(self, ev: MigrationEvent, ctx):
        if ev.type is EventType.ALLOCATED:
            self.registry.add(ev.object_id, ev.metadata["size_bytes"], ev.metadata["tier"])
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
        decisions = []

        for source, pressure in self.trend.pressure_sources(states):
            if source not in ctx.occupancy:
                continue
            cap = self.system.memories[source].capacity_bytes * ctx.capacity_mult
            target_util = 0.72
            required = max(
                0.0, ctx.occupancy.get(source, 0.0) - target_util * cap
            )
            if required <= 0 and pressure < 0.94:
                continue
            if required <= 0:
                required = 0.05 * cap

            candidates = self.eviction.candidates(source, ev.now_s)
            for rec in self.selector.select(candidates, required):
                hint = ctx.static_affinity_hints.get(rec.object_id, {})
                dst = self.destination.select(
                    rec, source, states, ctx.occupancy, ctx.capacity_mult, hint
                )
                if dst is not None:
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
        return decisions, self.decision_cost_us * max(1, len(decisions))

    def on_migration_committed(
        self, decision: MigrationDecision, now_s: float
    ) -> None:
        self.registry.move(decision.object_id, decision.target_tier)
        self.eviction.on_moved(decision.object_id, now_s)


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
        return {
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


TYPE_TIER_PREFERENCE = {
    "KV_CACHE": ("hbm", "custom_hbm", "cxl_pnm", "dram", "hbf"),
    "RAG_DATA": ("hbm", "hbf", "dram", "ssd_pim", "cxl_pnm"),
    "AGENT_MEMORY": ("hbm", "dram", "hbf", "ssd_pim", "cxl_pnm"),
    "TOOL_RESULT": ("hbm", "dram", "hbf", "ssd_pim"),
    "LORA_ADAPTER": ("hbm", "hbf", "dram", "cxl_pnm"),
    "MOE_EXPERT": ("hbm", "hbf", "dram", "custom_hbm", "cxl_pnm"),
}


class DestinationTierSelectorC2:
    def __init__(self, system):
        self.system = system

    def select(
        self, rec, predicted: float, telemetry, occupancy, capacity_mult
    ):
        pref = [
            x
            for x in TYPE_TIER_PREFERENCE.get(
                rec.data_type, tuple(self.system.memories)
            )
            if x in self.system.memories
        ]
        feasible = []
        for rank, name in enumerate(pref):
            mem = self.system.memories[name]
            cap = mem.capacity_bytes * capacity_mult
            if (
                cap - occupancy.get(name, 0.0) + 1e-6
                < rec.size_bytes
            ):
                continue
            if telemetry[name].capacity_util >= 0.95:
                continue
            feasible.append((rank, name))
        if not feasible:
            return None
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

    def __init__(self, system, priors: dict[str, dict]):
        self.system = system
        self.priors = priors
        self.registry = C2DataObjectRegistry()
        self.monitor = DataBehaviorMonitor()
        self.trend = BehaviorBasedTrendAnalyzer()
        self.predictor = FutureBehaviorPredictor()
        self.destination = DestinationTierSelectorC2(system)
        self.cooldown_s = 8.0
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
        decisions = []
        for rec in list(self.registry):
            if (
                ev.now_s - self.last_migration[rec.object_id]
                < self.cooldown_s
            ):
                continue
            feat = self.monitor.features(rec.object_id, ev.now_s)
            trend = self.trend.analyze(rec, feat)
            pred = self.predictor.predict(rec, trend)
            self.last_prediction[rec.object_id] = pred
            dst = self.destination.select(
                rec,
                pred,
                telemetry,
                ctx.occupancy,
                ctx.capacity_mult,
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
            decisions.append(
                MigrationDecision(
                    rec.object_id,
                    rec.tier,
                    dst,
                    reason="predicted_behavior",
                    score=pred,
                    direction=direction,
                )
            )
        return decisions, self.decision_cost_us * max(1, len(self.registry))

    def on_migration_committed(
        self, decision: MigrationDecision, now_s: float
    ) -> None:
        self.registry.move(decision.object_id, decision.target_tier)
        self.last_migration[decision.object_id] = now_s
