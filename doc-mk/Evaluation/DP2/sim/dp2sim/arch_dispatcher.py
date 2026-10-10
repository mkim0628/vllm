"""Architecture A: centralized Dispatcher (Master-Worker). One Planner decides synchronously at Turn start, in a single pass,
from a telemetry snapshot and the (possibly noisy) Cost estimator; decisions are serialized on the scheduler (arch-styles-plan 2).

Components (qa4-preregistration-arch 2): Tier Descriptors (physics), Candidate Generator / Cost Model / Resource Selector
(`policies.Estimator.evaluate`), Dispatcher (`DispatcherPlanner`), HBM opportunity cost (`HbmOpportunityCost`, part of the Cost Model).
"""
from __future__ import annotations

import random

from .physics import DECODE_TIERS, target
from .policies import NodeView, View


class HbmOpportunityCost:
    """lambda_HBM: price of keeping KV resident in the HBM pool (plan 2.1): c * u^2 * delta / cap."""

    def __init__(self, sim):
        self.sim = sim

    def __call__(self, nv, tier, delta, evict):
        if tier != "hbm":
            return 0.0
        sim = self.sim
        cap = target("hbm") * sim.kv.pool[(nv.idx, "hbm")]
        used = max(0.0, cap - nv.free["hbm"])
        u = min(1.5, (used + delta) / cap)
        return sim.o["lam_hbm"] * u * u * delta / cap


class DispatcherPlanner:
    """Dispatcher: picks the next queued Task, evaluates the node-local tier candidates with the global Cost, and commits after the
    (serialized) decision time `t_ref * k / 64` (the `c1done` event of the engine)."""

    def __init__(self, sim):
        self.sim = sim

    def plan(self, req):
        sim = self.sim
        view = sim.est_view()
        node = sim.assign_node(req, view)
        if view.nodes[node].pf_tokens >= sim.o["qcap"]:
            return None
        nodes = []
        for nv in view.nodes:
            c = NodeView(nv.idx, nv.role, nv.ndec, nv.groups, nv.pf_tokens, nv.njobs, nv.free, nv.evictable)
            c.alive = nv.idx == node
            nodes.append(c)
        plan, _ = sim.est.evaluate(View(nodes, view.flows), req, req.sess, [node], random.Random(sim.seed * 31 + req.rid), sim.now)
        if plan is not None:
            plan.k = len(DECODE_TIERS)
        return plan

    def dispatch(self):
        sim = self.sim
        if sim.sched_busy:
            return
        i, scanned = 0, 0
        while i < len(sim.gq) and scanned < 64:
            r = sim.gq[i]
            scanned += 1
            plan = self.plan(r)
            if plan is None:
                i += 1
                continue
            t_dec = sim.t_dec_for(plan.k)
            sim.gq.pop(i)
            sim.sched_busy = True
            r.t_dec = t_dec
            r.decision_k = plan.k
            sim.push(sim.now + t_dec, "c1done", r, plan)
            return
