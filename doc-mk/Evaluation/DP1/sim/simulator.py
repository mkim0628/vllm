from __future__ import annotations

import math
import random
from collections import Counter, defaultdict
from dataclasses import dataclass

from events import EventType, MigrationEvent, MigrationScheduler
from policies import (
    Telemetry,
    C1ResourceDrivenMigration,
    C2BehaviorDrivenMigration,
    StaticNoMigration,
)

FIRST_RESPONSE_SLO_S = 2.0
TPOT_SLO_S = 0.050


def weighted_quantile(samples, q: float) -> float:
    data = sorted((v, w) for v, w in samples if w > 0)
    if not data:
        return 0.0
    total = sum(w for _, w in data)
    target = total * q
    acc = 0.0
    for v, w in data:
        acc += w
        if acc >= target:
            return v
    return data[-1][0]


def poisson(rng, lam: float) -> int:
    if lam <= 0:
        return 0
    if lam < 30:
        L = math.exp(-lam)
        k = 0
        p = 1.0
        while p > L:
            k += 1
            p *= rng.random()
        return k - 1
    return max(0, int(round(rng.gauss(lam, math.sqrt(lam)))))


def effective_capacity_mult(sc, t: int, tier: str) -> float:
    mult = sc.capacity_mult
    if tier == "hbm":
        mult *= sc.hbm_capacity_mult
    if sc.phase == "capacity_ramp" and tier == "hbm":
        frac = t / max(1, sc.horizon_s - 1)
        mult *= max(0.45, 1.0 - 0.55 * frac)
    if sc.phase == "hbm_relief" and tier == "hbm":
        frac = t / max(1, sc.horizon_s - 1)
        start = mult
        mult = start + (sc.capacity_mult - start) * frac
    if tier in sc.disabled_tiers:
        return 0.0
    return mult


def effective_bw_mult(sc, t: int, tier: str) -> float:
    if tier in sc.disabled_tiers:
        return 0.01
    if (
        sc.phase == "hbm_bw_shock"
        and tier == "hbm"
        and t >= sc.horizon_s // 2
    ):
        return sc.hbm_bw_mult
    if (
        sc.phase == "host_bw_shock"
        and tier != "hbm"
        and t >= sc.horizon_s // 2
    ):
        return sc.host_bw_mult
    return 1.0


def tpot_s(
    system, obj, tier: str, candidate: str, bw_mult: float = 1.0
) -> float:
    if obj.data_class == "KV_CACHE":
        mem = system.memories[tier]
        if tier == "hbm":
            return system.decode_step_s(
                obj.context_tokens, obj.batch_size, "hbm", bw_mult
            )
        if candidate != "As-Is" and mem.attention_capable:
            return system.decode_step_s(
                obj.context_tokens, obj.batch_size, tier, bw_mult
            )
        restore = obj.size_bytes / max(1.0, mem.ext_bw * bw_mult)
        return restore / max(
            1, obj.output_tokens
        ) + system.decode_step_s(
            obj.context_tokens, obj.batch_size, "hbm"
        )

    base = system.decode_step_s(
        obj.context_tokens, obj.batch_size, "hbm"
    )
    if (
        obj.data_class in ("LORA_ADAPTER", "MOE_EXPERT")
        and tier != "hbm"
    ):
        mem = system.memories[tier]
        remote = min(
            obj.size_bytes, obj.access_bytes * obj.batch_size
        ) / max(1.0, mem.ext_bw * bw_mult)
        return base + remote / max(1, obj.output_tokens)
    return base


def ttft_s(
    system,
    obj,
    tier: str,
    candidate: str,
    bw_mult: float,
    migration_debt: float,
    decision_debt: float,
) -> float:
    q = min(2048, obj.context_tokens)
    base = system.prefill_s(obj.context_tokens, q)
    mem = system.memories[tier]
    extra = 0.0

    if obj.data_class == "RAG_DATA":
        extra = system.rag_retrieval_s(
            obj.size_bytes, obj.batch_size, tier, obj.retrieval_dim
        )
    elif obj.data_class in ("AGENT_MEMORY", "TOOL_RESULT"):
        extra = (
            min(obj.size_bytes, obj.access_bytes * obj.batch_size)
            / max(1.0, mem.ext_bw * bw_mult)
            + mem.latency_s
        )
    elif (
        obj.data_class in ("LORA_ADAPTER", "MOE_EXPERT")
        and tier != "hbm"
    ):
        extra = min(
            obj.size_bytes, obj.access_bytes * obj.batch_size
        ) / max(1.0, mem.ext_bw * bw_mult)
    elif (
        obj.data_class == "KV_CACHE"
        and tier != "hbm"
        and not mem.attention_capable
    ):
        extra = obj.size_bytes / max(1.0, mem.ext_bw * bw_mult)

    return base + extra + migration_debt + decision_debt


@dataclass
class SimContext:
    system: object
    objects: dict[int, object]
    placements: dict[int, str]
    occupancy: Counter
    capacity_mult: float
    effective_capacity: dict[str, float]
    static_affinity_hints: dict[int, dict]


def initial_external_placement(system, objs, sc) -> dict[int, str]:
    """Common initial state, explicitly outside DP1.

    The same deterministic allocator is used for C1/C2. It is not counted as a
    DP1 decision. DP1 starts only after Event -> MigrationScheduler.
    """
    placements = {}
    occ = Counter()
    order = [
        "hbm",
        "dram",
        "cxl_pnm",
        "hbf",
        "ssd_pim",
        "custom_hbm",
    ]

    for obj in sorted(objs, key=lambda x: (x.arrival_s, x.oid)):
        if obj.arrival_s > 0:
            continue
        for tier in order:
            if tier not in system.memories or tier in sc.disabled_tiers:
                continue
            target = 0.80 if tier == "hbm" else 0.90
            cap = (
                system.memories[tier].capacity_bytes
                * effective_capacity_mult(sc, 0, tier)
            )
            if occ[tier] + obj.size_bytes <= target * cap:
                placements[obj.oid] = tier
                occ[tier] += obj.size_bytes
                break
        else:
            placements[obj.oid] = "hbm"
            occ["hbm"] += obj.size_bytes

    return placements


def allocate_new_object(
    system, obj, placements, occupancy, sc, t
):
    for tier in (
        "hbm",
        "dram",
        "cxl_pnm",
        "hbf",
        "ssd_pim",
        "custom_hbm",
    ):
        if tier not in system.memories or tier in sc.disabled_tiers:
            continue
        cap = (
            system.memories[tier].capacity_bytes
            * effective_capacity_mult(sc, t, tier)
        )
        if occupancy[tier] + obj.size_bytes <= 0.90 * cap:
            placements[obj.oid] = tier
            occupancy[tier] += obj.size_bytes
            return tier

    placements[obj.oid] = "hbm"
    occupancy["hbm"] += obj.size_bytes
    return "hbm"


def transfer_time_s(
    system, size_bytes: float, src: str, dst: str, sc, t: int
) -> float:
    if src == dst:
        return 0.0
    sm = system.memories[src]
    dm = system.memories[dst]
    sbw = sm.ext_bw * effective_bw_mult(sc, t, src)
    dbw = dm.ext_bw * effective_bw_mult(sc, t, dst)
    return size_bytes / max(1.0, min(sbw, dbw))


def static_hints(objs) -> dict[int, dict]:
    """Generic C1 hint channel, separate from C1 registry.

    The registry stays type-agnostic. These hints model static
    operation/configuration metadata.
    """
    out = {}
    for o in objs:
        out[o.oid] = {
            "latency_sensitivity": float(o.latency_sensitivity),
            "bandwidth_sensitivity": (
                0.85
                if o.access_bytes / max(1.0, o.size_bytes) > 0.1
                else 0.45
            ),
            "capacity_sensitivity": (
                0.8 if o.size_bytes > 8 * 1024**3 else 0.45
            ),
        }
    return out


REPLICA_TIER_ORDER = ("dram", "cxl_pnm", "hbf")


def maybe_assign_replica(
    system, obj, primary_tier, replicas, occupancy, sc, t, seed, fraction
):
    """Common external write-through of sealed-KV replicas (NOT a DP1 decision).

    Same role as initial_external_placement: deterministic, identical for C1/C2 and
    for drop on/off, so the DROP study isolates the *action* effect. The replica
    occupies capacity in its tier. Replica creation cost is not charged (see README).
    Only KV_CACHE objects are eligible; the simulator treats them as sealed/immutable.
    """
    if fraction <= 0 or obj.data_class != "KV_CACHE":
        return None
    if random.Random(seed * 131 + obj.oid).random() >= fraction:
        return None
    for tier in REPLICA_TIER_ORDER:
        if (
            tier == primary_tier
            or tier not in system.memories
            or tier in sc.disabled_tiers
        ):
            continue
        cap = system.memories[tier].capacity_bytes * effective_capacity_mult(sc, t, tier)
        if occupancy[tier] + obj.size_bytes <= 0.90 * cap:
            occupancy[tier] += obj.size_bytes
            replicas[obj.oid] = tier
            return tier
    return None


def _policy(system, candidate, priors, drop_enabled=False):
    if candidate == "Baseline-static":
        return StaticNoMigration(system)
    if candidate == "C1-resource-driven":
        return C1ResourceDrivenMigration(system, drop_enabled)
    if candidate == "C2-behavior-driven":
        return C2BehaviorDrivenMigration(system, priors, drop_enabled)
    raise ValueError(candidate)


def run_sim(
    system,
    sc,
    seed: int,
    candidate: str,
    priors: dict,
    load_scale: float = 1.0,
    replica_fraction: float = 0.0,
    drop_enabled: bool = False,
) -> dict:
    from scenarios import generate_trace

    rng = random.Random(
        seed * 7919 + sum(map(ord, sc.name))
    )
    objs = generate_trace(sc, seed)
    objects = {o.oid: o for o in objs}
    placements = initial_external_placement(system, objs, sc)
    occupancy = Counter()

    for oid, tier in placements.items():
        occupancy[tier] += objects[oid].size_bytes

    initial_caps = {
        name: mem.capacity_bytes
        * effective_capacity_mult(sc, 0, name)
        for name, mem in system.memories.items()
    }
    ctx = SimContext(
        system,
        objects,
        placements,
        occupancy,
        sc.capacity_mult,
        initial_caps,
        static_hints(objs),
    )
    policy = _policy(system, candidate, priors, drop_enabled)
    scheduler = MigrationScheduler()
    replicas: dict[int, str] = {}
    replica_gib_created = 0.0
    for oid in sorted(placements):
        o = objects[oid]
        if maybe_assign_replica(
            system, o, placements[oid], replicas, occupancy, sc, 0, seed, replica_fraction
        ):
            replica_gib_created += o.size_bytes / 1024**3
    migration_debt = defaultdict(float)
    prev_ext_bytes = Counter()

    for oid, tier in placements.items():
        o = objects[oid]
        scheduler.push(
            MigrationEvent(
                EventType.ALLOCATED,
                0.0,
                oid,
                metadata={
                    "size_bytes": o.size_bytes,
                    "tier": tier,
                    "data_type": o.data_class,
                    "replica_tier": replicas.get(oid),
                },
            )
        )
    scheduler.drain(policy, ctx)

    ttft_samples = []
    tpot_samples = []
    offered = served = good = 0.0
    migration_count = 0
    migration_bytes = 0.0
    migration_time_total = 0.0
    direction_count = Counter()
    drop_count = 0
    drop_bytes_avoided = 0.0
    tier_accesses = Counter()
    capacity_util_samples = defaultdict(list)
    hbm_pressure_seconds = 0
    allocated = set(placements)

    for t in range(sc.horizon_s):
        alive = [o for o in objs if o.alive(t)]
        alive_ids = {o.oid for o in alive}

        for o in alive:
            if o.oid not in allocated:
                tier = allocate_new_object(
                    system,
                    o,
                    placements,
                    occupancy,
                    sc,
                    t,
                )
                allocated.add(o.oid)
                if maybe_assign_replica(
                    system, o, tier, replicas, occupancy, sc, t, seed, replica_fraction
                ):
                    replica_gib_created += o.size_bytes / 1024**3
                scheduler.push(
                    MigrationEvent(
                        EventType.ALLOCATED,
                        float(t),
                        o.oid,
                        metadata={
                            "size_bytes": o.size_bytes,
                            "tier": tier,
                            "data_type": o.data_class,
                            "replica_tier": replicas.get(o.oid),
                        },
                    )
                )

        for oid in list(allocated):
            if (
                oid not in alive_ids
                and objects[oid].arrival_s
                + objects[oid].lifetime_s
                <= t
            ):
                tier = placements.get(oid)
                if tier is not None:
                    occupancy[tier] -= objects[oid].size_bytes
                rt = replicas.pop(oid, None)
                if rt is not None:
                    occupancy[rt] -= objects[oid].size_bytes
                scheduler.push(
                    MigrationEvent(
                        EventType.FREED, float(t), oid
                    )
                )
                allocated.remove(oid)
                placements.pop(oid, None)

        telemetry = {}
        current_caps = {}
        for name, mem in system.memories.items():
            capm = effective_capacity_mult(sc, t, name)
            effective_cap = max(
                1.0, mem.capacity_bytes * capm
            )
            current_caps[name] = effective_cap
            cap_util = (
                occupancy[name] / effective_cap
                if capm > 0
                else 1.5
            )
            bw_mult = effective_bw_mult(sc, t, name)
            bw_util = prev_ext_bytes[name] / max(
                1.0, mem.ext_bw * bw_mult
            )
            telemetry[name] = Telemetry(
                capacity_util=cap_util,
                bw_util=bw_util,
            )
            capacity_util_samples[name].append(cap_util)

        ctx.effective_capacity = current_caps

        if (
            telemetry.get("hbm", Telemetry()).capacity_util
            >= 0.82
        ):
            hbm_pressure_seconds += 1

        access_counts = {}
        for o in alive:
            count = poisson(
                rng, o.rate_at(t) * load_scale
            )
            access_counts[o.oid] = count
            if count > 0:
                scheduler.push(
                    MigrationEvent(
                        EventType.ACCESSED,
                        float(t),
                        o.oid,
                        count=count,
                    )
                )

        scheduler.push(
            MigrationEvent(
                EventType.TELEMETRY,
                float(t),
                metadata={"telemetry": telemetry},
            )
        )

        overhead_before_us = (
            scheduler.stats.decision_overhead_us
        )
        decisions = scheduler.drain(policy, ctx)
        tick_decision_overhead_us = (
            scheduler.stats.decision_overhead_us
            - overhead_before_us
        )
        migration_ext = Counter()

        for d in decisions:
            if (
                d.object_id not in placements
                or placements[d.object_id]
                != d.source_tier
            ):
                continue

            obj = objects[d.object_id]

            if d.action == "DROP":
                # No transfer: free the source copy, replica becomes authoritative.
                # Invalid unless the named replica really exists (stale decision).
                if replicas.get(d.object_id) != d.target_tier:
                    continue
                occupancy[d.source_tier] -= obj.size_bytes
                placements[d.object_id] = d.target_tier
                del replicas[d.object_id]
                policy.on_migration_committed(d, float(t))
                drop_count += 1
                drop_bytes_avoided += obj.size_bytes
                direction_count[d.direction] += 1
                continue

            dst_cap = ctx.effective_capacity[
                d.target_tier
            ]
            # A replica already sitting at the target is freed when the new
            # primary copy lands there (MOVE re-copies; only DROP exploits it).
            replica_at_target = (
                obj.size_bytes
                if replicas.get(d.object_id) == d.target_tier
                else 0.0
            )
            if (
                occupancy[d.target_tier]
                - replica_at_target
                + obj.size_bytes
                > dst_cap
            ):
                continue

            dt = transfer_time_s(
                system,
                obj.size_bytes,
                d.source_tier,
                d.target_tier,
                sc,
                t,
            )
            occupancy[d.source_tier] -= obj.size_bytes
            occupancy[d.target_tier] += obj.size_bytes - replica_at_target
            if replica_at_target:
                del replicas[d.object_id]
            placements[d.object_id] = d.target_tier
            policy.on_migration_committed(
                d, float(t)
            )

            migration_count += 1
            migration_bytes += obj.size_bytes
            migration_time_total += dt
            direction_count[d.direction] += 1

            migration_debt[d.object_id] += 0.20 * dt
            migration_ext[d.source_tier] += obj.size_bytes
            migration_ext[d.target_tier] += obj.size_bytes

        decision_debt_per_access = (
            tick_decision_overhead_us
            * 1e-6
            / max(1, sum(access_counts.values()))
        )
        next_ext = Counter(migration_ext)

        for o in alive:
            count = access_counts[o.oid]
            if (
                count <= 0
                or o.oid not in placements
            ):
                continue

            tier = placements[o.oid]
            tier_accesses[tier] += count
            bw_mult = effective_bw_mult(
                sc, t, tier
            )
            tpot = tpot_s(
                system,
                o,
                tier,
                candidate,
                bw_mult,
            )
            ttft = ttft_s(
                system,
                o,
                tier,
                candidate,
                bw_mult,
                migration_debt[o.oid],
                decision_debt_per_access,
            )
            migration_debt[o.oid] = 0.0

            ttft_samples.append((ttft, count))
            tpot_samples.append((tpot, count))
            offered += count * o.output_tokens

            capacity_req = max(
                0.0, 1.0 / max(1e-9, tpot)
            )
            done = min(count, capacity_req)
            served += done * o.output_tokens
            if (
                ttft <= FIRST_RESPONSE_SLO_S
                and tpot <= TPOT_SLO_S
            ):
                good += done * o.output_tokens

            if tier != "hbm":
                next_ext[tier] += min(
                    o.size_bytes,
                    o.access_bytes * max(1, count),
                )

        prev_ext_bytes = next_ext

    total_cap = sum(
        m.capacity_bytes * sc.capacity_mult
        for m in system.memories.values()
    )
    avg_used = sum(
        sum(vals) / max(1, len(vals))
        * system.memories[name].capacity_bytes
        * sc.capacity_mult
        for name, vals in capacity_util_samples.items()
    )
    hbm_vals = capacity_util_samples.get("hbm", [0.0])
    avg_hbm = sum(hbm_vals) / max(1, len(hbm_vals))

    return {
        "scenario": sc.name,
        "seed": seed,
        "candidate": candidate,
        "load_scale": load_scale,
        "offered_tokens": offered,
        "served_tokens": served,
        "slo_goodput_tokens": good,
        "ttft_p99_ms": (
            weighted_quantile(ttft_samples, 0.99) * 1e3
        ),
        "tpot_p99_ms": (
            weighted_quantile(tpot_samples, 0.99) * 1e3
        ),
        "migration_count": migration_count,
        "migration_gib": (
            migration_bytes / (1024**3)
        ),
        "migration_time_s": migration_time_total,
        "promotion_count": direction_count["promotion"],
        "demotion_count": direction_count["demotion"],
        "rebalance_count": direction_count["rebalance"],
        "replica_fraction": replica_fraction,
        "drop_enabled": drop_enabled,
        "replica_gib_created": replica_gib_created,
        "drop_count": drop_count,
        "drop_gib_avoided": drop_bytes_avoided / (1024**3),
        "decision_overhead_ms": (
            scheduler.stats.decision_overhead_us / 1e3
        ),
        "events_pushed": scheduler.stats.pushed,
        "events_coalesced": scheduler.stats.coalesced,
        "hbm_pressure_fraction": (
            hbm_pressure_seconds
            / max(1, sc.horizon_s)
        ),
        "avg_hbm_util": avg_hbm,
        "aggregate_capacity_util": (
            avg_used / max(1.0, total_cap)
        ),
        "occupied_tiers": sum(
            1 for v in tier_accesses.values() if v > 0
        ),
        "tier_accesses": dict(tier_accesses),
    }
