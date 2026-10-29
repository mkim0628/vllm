"""Node-internal DP2 simulator (arch-styles-plan.md). Subclass of the existing engine: the existing candidates and their results are
untouched. Adds (1) unified-node candidates Baseline-GPU-local / A-Dispatcher / B-Blackboard that decide only the Decode attention
tier inside the node chosen by a shared rule, (2) time-average HBM KV occupancy (QA3), (3) per-tier decision counters.
"""
from __future__ import annotations

from collections import defaultdict

from .arch_blackboard import Poster, TaskBoard
from .arch_dispatcher import DispatcherPlanner, HbmOpportunityCost, PendingLedger, RuleDispatcher
from .engine import GIB, Sim
from .policies import Plan

N_BASE, N_DISP, N_BBRD = "Baseline-GPU-local", "A-Dispatcher", "B-Blackboard"
N_DRULE = "Ref-Dispatcher-with-board-rules"      # reference: Dispatcher architecture + Blackboard rule set
NODE_CANDS = (N_BASE, N_DISP, N_BBRD, N_DRULE)
NODE_DEFAULTS = dict(lam_hbm=1.0, theta=0.8, rho_hi=0.85, t_bb=0.0005)


class NodeSim(Sim):
    def __init__(self, sys_id, sc, seed, cand, load=1.0, opts=None):
        o = dict(NODE_DEFAULTS)
        if opts:
            o.update(opts)
        super().__init__(sys_id, sc, seed, cand, load, o)
        self.arch_stats = defaultdict(int)
        self.tier_counts = defaultdict(int)
        self._started = False
        self._last_t = 0.0
        self._occ_cur = 0.0
        self._frac_cur = 0.0
        self._occ_int = 0.0
        self._frac_int = 0.0
        self._peak = 0.0
        self.disp = self.board = self.poster = None
        self.ledger = PendingLedger() if cand == N_DISP else None
        if cand == N_DISP:
            self.disp = DispatcherPlanner(self)
            if self.o["lam_hbm"] > 0:
                self.est.price_fn = HbmOpportunityCost(self)
        elif cand == N_BBRD:
            self.board = TaskBoard(self)
            self.poster = Poster(self, self.board)
        elif cand == N_DRULE:
            self.board = TaskBoard(self)
            self.disp = RuleDispatcher(self, self.board)

    # ------------------------------------------------------------------------------------------ shared node rule
    def assign_node(self, req, view):
        """Node choice is outside DP2 (DP4): the same rule for every candidate."""
        sess = req.sess
        if req.hist > 0 and sess.owner is not None:
            return sess.owner[0]
        return max((n.idx for n in self.nodes), key=lambda i: view.nodes[i].free["hbm"])

    def baseline_plan_gpu(self, req, view):
        """Baseline-GPU-local (vLLM As-Is on a unified node): Prefill on the node, ALL decode attention on the GPU (Decode tier = HBM,
        History outside HBM is swapped in; same decode semantics as Baseline-PD-fixed)."""
        node = self.assign_node(req, view)
        if view.nodes[node].pf_tokens >= self.o["qcap"]:
            return None
        return Plan(node, (node, "hbm"), 0.0, [], self.now, 0, 0, 0)

    # ----------------------------------------------------------------------------------------------- dispatch
    def _dispatch_instant(self, fallback):
        i, scanned = 0, 0
        while i < len(self.gq) and scanned < 128:
            r = self.gq[i]
            scanned += 1
            plan = self.baseline_plan_gpu(r, self.est_view())
            r.fallback = fallback
            if fallback:
                self.stats["fallbacks"] += 1
            if plan is not None and self.commit(r, plan, 0.0):
                self.gq.pop(i)
            else:
                if plan is not None and fallback:
                    self.stats["fallbacks"] -= 1
                r.fallback = False
                i += 1

    def try_dispatch(self):
        if not self.gq:
            return
        c = self.cand
        if c == N_BASE or (self.fault and c in (N_DISP, N_BBRD, N_DRULE)):
            self._dispatch_instant(fallback=(c != N_BASE))
        elif c in (N_DISP, N_DRULE):
            self.disp.dispatch()
        else:
            self.poster.post_all()

    def commit(self, req, plan, t_dec):
        ok = super().commit(req, plan, t_dec)
        if ok and self.board is not None:
            self.board.on_committed(plan.n_d[0], plan.n_d[1], req)
        if ok and self.ledger is not None:
            self.ledger.add(req.rid, plan.n_d[0], plan.n_d[1], req.hist + req.q + req.out / 2.0)
        if ok and not req.fallback and req.t_arr >= self.o["warmup"]:
            self.tier_counts[plan.n_d[1]] += 1
            if self.cand in (N_DISP, N_DRULE):
                self.stats["decisions"] += 1
                self.stats["t_dec"].append(req.t_dec or 0.0)
        return ok

    def start_decode(self, req):
        if self.board is not None:
            self.board.on_decode_start(req)
        if self.ledger is not None:
            self.ledger.started(req.rid, self.now)
        super().start_decode(req)

    def take_snapshot(self):
        super().take_snapshot()
        if self.ledger is not None:
            self.ledger.prune(self.now)

    # ------------------------------------------------------------------------------------- HBM occupancy (QA3)
    def _occ_now(self):
        occ = sum(self.kv.occ[(i, "hbm")] + self.kv.resv[(i, "hbm")] for i in range(self.N))
        pool = sum(self.kv.pool[(i, "hbm")] for i in range(self.N))
        return occ, (occ / pool if pool else 0.0)

    def _acc(self, t):
        lo = max(self._last_t, self.o["warmup"])
        if t > lo:
            self._occ_int += self._occ_cur * (t - lo)
            self._frac_int += self._frac_cur * (t - lo)
        self._last_t = max(self._last_t, t)

    def dispatch_event(self, kind, a, b):
        if not self._started:
            self._started = True
            self._occ_cur, self._frac_cur = self._occ_now()
        self._acc(self.now)
        if kind == "bbclaim":
            self.board.on_claim(a)
        else:
            super().dispatch_event(kind, a, b)
        self._occ_cur, self._frac_cur = self._occ_now()
        if self.now >= self.o["warmup"]:
            self._peak = max(self._peak, self._frac_cur)

    def finish(self):
        if not self._started:
            self._occ_cur, self._frac_cur = self._occ_now()
        self._acc(self.end)
        r = super().finish()
        win = max(1e-9, self.end - self.o["warmup"])
        sc = self.sc
        pool0 = self.sysspec.memories["hbm"].capacity_bytes * (sc.hbm_mult if self.o["hbm_mult"] is None else self.o["hbm_mult"])
        exog = sc.bg_decode * 8192 * self.P.kvb + sc.occupant_frac * pool0 * self.N
        avg = self._occ_int / win
        r["hbm"] = dict(avg_gib=avg / GIB, avg_frac=self._frac_int / win, peak_frac=self._peak,
                        net_gib=max(0.0, avg - exog) / GIB, exog_gib=exog / GIB)
        r["arch"] = dict(tiers=dict(self.tier_counts), **dict(self.arch_stats))
        return r
