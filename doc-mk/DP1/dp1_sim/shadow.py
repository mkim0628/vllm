"""Phase 4: event-driven DP1 Shadow Mode on an *actual* vLLM trace (Evaluation §7).

The actual run (dp1_client.py output, A) supplies request timing, sizes and the
per-request actual prefix-cache hit (cached_tokens). C1/C2 receive the
runtime events of that trace through the MigrationScheduler and make
decisions that are *not* executed on the server. Their placement is tracked
in a shadow state and overlaid on the trace:

  TTFT_proj = TTFT_actual - T_recompute_actual + T_shadow_restore
      T_recompute_actual : prefill time of the history tokens vLLM actually
                           missed (history - cached_tokens), step model
      T_shadow_restore   : 0 (shadow HBM) | transfer time (shadow lower tier)
                           | prefill time of history (shadow dropped)
  TPOT_proj = TPOT_actual * (1 + copy_interference * DMA-overlap fraction)

Evidence of the projected numbers: [A+C] (A trace + A/B transfer model + C overlay).
"""

from __future__ import annotations

import heapq
import json
from collections import Counter, defaultdict
from pathlib import Path

from events import EventType, MigrationEvent, MigrationScheduler
from hw import ServingHW, TierSpec
from perf_model import StepModel
from policies import Telemetry
from policies_serving import DROP, make_policy
from qa import weighted_pct
from serving_sim import TPOT_SLO_S, TTFT_SLO_S, SimCtx


def prefill_time(hw: ServingHW, sm: StepModel, tokens: int, cached: int = 0) -> float:
    t, done = 0.0, 0
    while done < tokens:
        q = min(hw.max_num_batched_tokens, tokens - done)
        t += sm.step_time(hw, [(q, cached + done)], 0, 0)
        done += q
    return t


def load_client(path: Path) -> list[dict]:
    lines = [json.loads(x) for x in path.read_text().splitlines() if x.strip()]
    return [r for r in lines[1:] if r.get("ttft_s") is not None and not r.get("error")]


def shadow_run(
    hw: ServingHW,
    sm: StepModel,
    policy_name: str,
    recs: list[dict],
    tick_s: float = 0.25,
) -> dict:
    kvB = hw.model.kv_bytes_per_token
    mem = {
        "hbm": TierSpec("hbm", hw.kv_capacity_bytes, hw.hbm_bw, hw.hbm_bw, 3e-7, "hbm"),
        **hw.tiers,
    }
    cap = {n: t.capacity_bytes for n, t in mem.items()}
    occ: Counter = Counter({n: 0.0 for n in mem})  # retained objects only
    lane_free = defaultdict(float)
    dma: list[tuple[float, float]] = []
    now = [0.0]

    def restore(tier, size):
        if tier == "hbm":
            return 0.0
        t = mem[tier]
        return max(0.0, lane_free[(t.lane, "up")] - now[0]) + t.promote.time(size)

    lane_busy: dict = {}
    ctx = SimCtx(cap, occ, mem, tick_s, lane_busy, restore)
    policy = make_policy(policy_name)
    sched = MigrationScheduler()
    place: dict[int, str | None] = {}
    size: dict[int, float] = {}
    last: dict[int, float] = {}
    movable: dict[int, bool] = {}
    m = Counter()

    ev: list = []
    for i, r in enumerate(recs):
        ta = r["arrival_s"]
        heapq.heappush(ev, (ta, 0, i, "arrive"))
        heapq.heappush(ev, (ta + r["ttft_s"], 1, i, "prefilled"))
        heapq.heappush(ev, (r["finish_s"], 2, i, "finish"))
    running: dict[int, dict] = {}
    proj_ttft = [0.0] * len(recs)
    next_tick = 0.0

    def running_bytes(t):
        b = 0.0
        for r in running.values():
            ft = r["arrival_s"] + r["ttft_s"]
            frac = (
                0.0 if t <= ft else min(1.0, (t - ft) / max(1e-9, r["finish_s"] - ft))
            )
            b += (r["prompt_tokens"] + frac * r["output_tokens"]) * kvB
        return b

    def execute(decs):
        for d in decs:
            sid = d.object_id
            if place.get(sid) != d.source_tier or not movable.get(sid):
                m["rejected"] += 1
                continue
            s = size[sid]
            if d.target_tier == DROP:
                occ[d.source_tier] -= s
                place[sid] = None
                m["drops"] += 1
            else:
                if occ[d.target_tier] + s > cap[d.target_tier]:
                    m["rejected"] += 1
                    continue
                t = mem[d.target_tier if d.target_tier != "hbm" else d.source_tier]
                key = (t.lane, "up" if d.target_tier == "hbm" else "down")
                curve = t.promote if d.target_tier == "hbm" else t.demote
                st = max(now[0], lane_free[key])
                lane_free[key] = st + curve.time(s)
                dma.append((st, lane_free[key]))
                occ[d.source_tier] -= s
                occ[d.target_tier] += s
                place[sid] = d.target_tier
                m[f"mig_{d.direction}"] += 1
                m["mig_bytes"] += s
            policy.on_migration_committed(d, now[0])

    def telemetry(need=0.0):
        hbm_used = occ["hbm"] + running_bytes(now[0])
        tel = {
            n: Telemetry(
                (hbm_used if n == "hbm" else occ[n]) / cap[n] if cap[n] else 1.5, 0.0
            )
            for n in mem
        }
        md = {"telemetry": tel}
        if need > 0:
            md["need_bytes"] = need
        saved = occ["hbm"]
        occ["hbm"] = hbm_used  # policies see total HBM occupancy
        sched.push(MigrationEvent(EventType.TELEMETRY, now[0], metadata=md))
        decs = sched.drain(policy, ctx)
        occ["hbm"] = saved + (occ["hbm"] - hbm_used)
        execute(decs)

    while ev:
        t, _, i, kind = heapq.heappop(ev)
        while next_tick <= t:
            now[0] = next_tick
            telemetry()
            next_tick += tick_s
        now[0] = t
        r = recs[i]
        sid = r["session"]
        if kind == "arrive":
            if r["turn"] > 0:
                sched.push(MigrationEvent(EventType.ACCESSED, t, sid, count=1))
            hist = r["history_tokens"]
            cached_act = r.get("cached_tokens")
            miss_act = max(0, hist - (cached_act if cached_act is not None else hist))
            t_act = prefill_time(hw, sm, miss_act, hist - miss_act) if miss_act else 0.0
            loc = place.get(sid) if r["turn"] > 0 else "hbm"
            if r["turn"] == 0 or loc == "hbm":
                t_sh = 0.0
                m["shadow_hbm_hit"] += r["turn"] > 0
            elif loc is None:
                t_sh = prefill_time(hw, sm, hist)
                m["shadow_miss"] += 1
            else:
                t_sh = restore(loc, size[sid])
                m["shadow_lower_hit"] += 1
            proj_ttft[i] = max(0.001, r["ttft_s"] - t_act + t_sh)
            if loc is not None and sid in place:
                occ[loc] -= size[sid]  # becomes part of the running request
            place[sid] = "hbm"
            movable[sid] = False
            if r["turn"] == 0 or loc is None:
                # new or dropped (recomputed) object -> (re)registered
                sched.push(
                    MigrationEvent(
                        EventType.ALLOCATED,
                        t,
                        sid,
                        metadata={
                            "size_bytes": r["prompt_tokens"] * kvB,
                            "tier": "hbm",
                            "data_type": "KV_CACHE",
                            "movable": False,
                        },
                    )
                )
            else:
                sched.push(
                    MigrationEvent(
                        EventType.PHASE_CHANGE,
                        t,
                        sid,
                        metadata={"movable": False, "tier": "hbm"},
                    )
                )
            running[i] = r
        elif kind == "finish":
            running.pop(i, None)
            tot = (r["prompt_tokens"] + r["output_tokens"]) * kvB
            size[sid] = tot
            occ["hbm"] += tot
            movable[sid] = True
            last[sid] = t
            sched.push(
                MigrationEvent(
                    EventType.PHASE_CHANGE,
                    t,
                    sid,
                    metadata={"movable": True, "size_bytes": tot, "tier": "hbm"},
                )
            )
            # vLLM fallback when shadow HBM overflows: LRU drop of retained
            over = occ["hbm"] + running_bytes(t) - cap["hbm"]
            if over > 0:
                telemetry(need=over)
                over = occ["hbm"] + running_bytes(t) - cap["hbm"]
                for s2 in sorted(
                    (s for s, p in place.items() if p == "hbm" and movable.get(s)),
                    key=lambda s: last.get(s, 0),
                ):
                    if over <= 0:
                        break
                    occ["hbm"] -= size[s2]
                    over -= size[s2]
                    place[s2] = None
                    m["runtime_lru_drop"] += 1
                    sched.push(MigrationEvent(EventType.FREED, t, s2))

    # TPOT overlay: DMA overlap with each request's decode window
    dma.sort()
    proj_tpot = []
    for r in recs:
        a, b = r["arrival_s"] + r["ttft_s"], r["finish_s"]
        ov = sum(max(0.0, min(b, e) - max(a, s)) for s, e in dma if s < b and e > a)
        frac = min(1.0, ov / max(1e-9, b - a))
        proj_tpot.append(r["tpot_s"] * (1 + hw.copy_interference * frac))

    t0 = min(r["arrival_s"] for r in recs)
    t1 = max(r["finish_s"] for r in recs)
    dur = t1 - t0
    ok = [a <= TTFT_SLO_S and b <= TPOT_SLO_S for a, b in zip(proj_ttft, proj_tpot)]
    act_ok = [r["ttft_s"] <= TTFT_SLO_S and r["tpot_s"] <= TPOT_SLO_S for r in recs]
    return {
        "policy": policy_name,
        "requests": len(recs),
        "actual": {
            "slo_goodput_tok_s": sum(
                r["output_tokens"] for r, g in zip(recs, act_ok) if g
            )
            / dur,
            "ttft_p99_s": weighted_pct([r["ttft_s"] for r in recs], 0.99),
            "tpot_p99_s": weighted_pct([r["tpot_s"] for r in recs], 0.99),
        },
        "projected": {
            "slo_goodput_tok_s": sum(r["output_tokens"] for r, g in zip(recs, ok) if g)
            / dur,
            "ttft_p50_s": weighted_pct(proj_ttft, 0.5),
            "ttft_p99_s": weighted_pct(proj_ttft, 0.99),
            "tpot_p99_s": weighted_pct(proj_tpot, 0.99),
            "slo_attainment": sum(ok) / len(ok),
        },
        "diagnostics": dict(m)
        | {
            "decision_overhead_model_ms": sched.stats.decision_overhead_us / 1e3,
            "migration_GiB": m["mig_bytes"] / 2**30,
        },
        "evidence": "[A+C]",
    }
