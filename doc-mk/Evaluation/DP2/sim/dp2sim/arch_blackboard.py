"""Architecture B: Blackboard. The Poster (thin scheduler) publishes Attention Tasks to a shared Task Board; independent Knowledge
Sources (Tier Admission Agents, HBM Budget Admission) claim them opportunistically from LIVE local measurements (no estimator, no
telemetry snapshot). Posting -> claim takes `t_bb` and is not serialized (arch-styles-plan 2, 2.2).

Components (qa4-preregistration-arch 2): Tier Descriptors (physics), Task Board (`TaskBoard`), Tier Admission Agents
(`TierAdmissionAgent`), HBM Budget Admission (`HbmBudgetAdmission`), Poster (`Poster`).
"""
from __future__ import annotations

from .physics import OFFLOAD, target
from .policies import Plan, SLO_TPOT

AGENT_ORDER = OFFLOAD            # arbitration priority: custom_hbm, then cxl_pnm


class TierAdmissionAgent:
    """Knowledge Source of one attention-capable Tier: claims iff the Tier has capacity and measured headroom (current offload
    attention time of the Tier <= theta * SLO_TPOT)."""

    def __init__(self, sim, tier, board=None):
        self.sim, self.tier, self.board = sim, tier, board
        self.claimed = {}                # node -> {rid: context tokens} of Tasks this agent has claimed but whose Decode has not started

    def node_iter(self, nd, ctx, view=None):
        """v2: projected node iteration time if this Task (context `ctx`) is added at this Tier, counting live decode groups, every
        claim backlog entry on the node (all Tiers, kept by the board) and the Task itself."""
        groups = dict((view.nodes[nd.idx].groups if view is not None else nd.groups()))
        for tier, c in self.board.backlog_groups(nd.idx).items():
            n0, s0 = groups.get(tier, (0, 0.0))
            groups[tier] = (n0 + c[0], s0 + c[1])
        n0, s0 = groups.get(self.tier, (0, 0.0))
        groups[self.tier] = (n0 + 1, s0 + ctx)
        return self.sim.P.iter_time(groups, ())

    def load(self, nd, view=None):
        """Offload attention time of this Tier on `nd`, counting resident sequences and the agent's own claim backlog. `view`: a
        telemetry snapshot to read instead of the live node (used only by the reference rule-dispatcher)."""
        cnt, ctx = (view.nodes[nd.idx].groups if view is not None else nd.groups()).get(self.tier, (0, 0.0))
        mine = self.claimed.get(nd.idx, {})
        cnt, ctx = cnt + len(mine), ctx + sum(mine.values())
        return self.sim.P.decode_att(self.tier, cnt, ctx)[1] if cnt else 0.0

    def headroom(self, nd, ctx, view=None):
        return self.node_iter(nd, ctx, view) <= self.sim.o["theta"] * SLO_TPOT

    def claim(self, node, delta, ctx, view=None):
        sim = self.sim
        free = view.nodes[node].free[self.tier] if view is not None else sim.kv.free(node, self.tier)
        if free < delta:
            return False
        return self.headroom(sim.nodes[node], ctx, view)


class HbmBudgetAdmission:
    """Grants HBM staging/residency iff capacity (free + evictable idle sessions) suffices and the HBM utilization after granting,
    counting idle (demotable) sessions as free, stays <= rho_hi. Already-resident KV only needs capacity."""

    def __init__(self, sim):
        self.sim = sim

    def grant(self, node, delta, sess, resident=False, view=None):
        sim = self.sim
        if view is not None:                      # reference rule-dispatcher: telemetry snapshot instead of live state
            free, idle = view.nodes[node].free["hbm"], view.nodes[node].evictable
            if free < delta and idle < delta - free:
                return False
        else:
            free = sim.kv.free(node, "hbm")
            if free < delta and sim.kv.victims(node, delta - free, sess.sid) is None:
                return False
        if resident:
            return True
        cap = target("hbm") * sim.kv.pool[(node, "hbm")]
        if view is None:
            idle = sum(s.kv_bytes for s in sim.kv.sessions.values()
                       if s.owner == (node, "hbm") and not s.active and not s.pinned and s.sid != sess.sid)
        return (cap - free - idle + delta) / cap <= sim.o["rho_hi"]


class TaskBoard:
    """Shared board: holds posted Tasks, runs the claim round and arbitrates between claimants."""

    def __init__(self, sim):
        self.sim = sim
        self.posted = set()
        self.agents = {t: TierAdmissionAgent(sim, t, self) for t in (*AGENT_ORDER, "hbf")}
        self.budget = HbmBudgetAdmission(sim)
        self.backlog = {}                # node -> {rid: (tier, ctx)}: every claimed Task whose Decode has not started (all Tiers)

    def backlog_groups(self, node):
        g = {}
        for tier, ctx in self.backlog.get(node, {}).values():
            c = g.get(tier, (0, 0.0))
            g[tier] = (c[0] + 1, c[1] + ctx)
        return g

    def on_committed(self, node, tier, req):
        ag = self.agents.get(tier)
        if ag is not None:
            ag.claimed.setdefault(node, {})[req.rid] = req.ctx_end
        self.backlog.setdefault(node, {})[req.rid] = (tier, req.hist + req.q + req.out / 2.0)

    def on_decode_start(self, req):
        for mine in self.backlog.values():
            mine.pop(req.rid, None)
        for ag in self.agents.values():
            for mine in ag.claimed.values():
                mine.pop(req.rid, None)

    def decide(self, req, node, view=None):
        sim = self.sim
        sess = req.sess
        owner = sess.owner if (req.hist > 0 and sess.owner is not None and sess.owner[0] == node) else None
        ot = owner[1] if owner else None
        need = req.ctx_end * sim.P.kvb

        def delta(t):
            return need - (sess.kv_bytes if owner == (node, t) else 0.0)

        ctx = req.hist + req.q + req.out / 2.0
        if ot in self.agents and self.agents[ot].claim(node, delta(ot), ctx, view):      # v2: hbf is also admitted by node TPOT headroom
            return ot
        if self.budget.grant(node, delta("hbm"), sess, resident=(ot == "hbm"), view=view):
            return "hbm"
        if req.hist > 0:                             # v2: no movement-cost signal on the board -> History is only staged to HBM
            return None
        claimants = [t for t in AGENT_ORDER if self.agents[t].claim(node, delta(t), ctx, view)]
        if claimants:
            return claimants[0]                      # arbitration: first claimant in AGENT_ORDER
        return None

    def on_claim(self, req):
        sim = self.sim
        self.posted.discard(req.rid)
        if not any(x is req for x in sim.gq):
            return
        node = sim.assign_node(req, sim.est_view())
        if sim.fault:
            plan = sim.baseline_plan_gpu(req, sim.est_view())
            req.fallback = True
            sim.stats["fallbacks"] += 1
            ok = plan is not None and sim.commit(req, plan, sim.o["t_bb"])
            if not ok:
                req.fallback = False
                if plan is not None:
                    sim.stats["fallbacks"] -= 1
        else:
            nd = sim.nodes[node]
            nd.advance(sim.now)
            ok = False
            if sim.outstanding(node) < sim.o["qcap"]:
                tier = self.decide(req, node)
                if tier is not None:
                    ok = sim.commit(req, Plan(node, (node, tier), 0.0, [], sim.now, 0, 0.0, 0.0), sim.o["t_bb"])
            sim.arch_stats["claims" if ok else "rejects"] += 1
        if ok:
            for k, x in enumerate(sim.gq):
                if x is req:
                    sim.gq.pop(k)
                    break
            sim.try_dispatch()


class Poster:
    """Thin Scheduler: publishes a Task for every queued request (no Cost computation)."""

    def __init__(self, sim, board):
        self.sim, self.board = sim, board

    def post_all(self):
        sim = self.sim
        for r in sim.gq[:128]:
            if r.rid in self.board.posted:
                continue
            self.board.posted.add(r.rid)
            sim.push(sim.now + sim.o["t_bb"], "bbclaim", r)
