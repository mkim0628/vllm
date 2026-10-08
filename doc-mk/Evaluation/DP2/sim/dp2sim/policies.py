"""Estimator + candidate selection (M0 spec 6.2-6.3).

Cost(n_p, n_d) in SLO-fractions (A19 v2): TTFT_est/SLO_TTFT + TPOT_est/SLO_TPOT + handoff stall amortized over the
output tokens + the SLO-fractions the plan takes from other requests (running decodes at n_p, resident decodes at n_d,
later arrivals at n_p). The same code is used by C1, C2 and Oracle; only the state view (telemetry snapshot vs live),
the estimator error and the timing/lifecycle (engine) differ.
"""
from __future__ import annotations

import math
import random

from .physics import DECODE_TIERS, cfgv

SLO_TTFT = 2.0
SLO_TPOT = 0.050


class NodeView:
    __slots__ = ("idx", "role", "ndec", "groups", "pf_tokens", "njobs", "free", "evictable", "alive")

    def __init__(self, idx, role, ndec, groups, pf_tokens, njobs, free, evictable):
        self.idx, self.role, self.ndec, self.groups, self.pf_tokens, self.njobs = idx, role, ndec, groups, pf_tokens, njobs
        self.free, self.evictable, self.alive = free, evictable, True


class View:
    def __init__(self, nodes, flows):
        self.nodes, self.flows = nodes, flows


class Plan:
    __slots__ = ("n_p", "n_d", "cost", "backups", "t_plan", "k", "ttft_est", "tpot_est", "feasible", "bcost", "state")

    def __init__(self, n_p, n_d, cost, backups, t_plan, k, ttft_est, tpot_est, feasible=True):
        self.n_p, self.n_d, self.cost, self.backups, self.t_plan, self.k = n_p, n_d, cost, backups, t_plan, k
        self.ttft_est, self.tpot_est, self.feasible = ttft_est, tpot_est, feasible
        self.bcost, self.state = [], None


class Estimator:
    def __init__(self, sim, eps=0.0):
        self.sim = sim
        self.P = sim.P
        self.eps = eps
        self.lam = {}          # per-node EWMA dispatch rate (planner's own knowledge)
        self._last = {}

    # -- transfers ---------------------------------------------------------------------------------------------
    def xfer(self, nbytes, src, dst, view):
        if nbytes <= 0 or src == dst:
            return 0.0
        res = self.sim.path_res(src, dst)
        rate = min(self.sim.net.cap(r) / (1 + view.flows.get(r, 0)) for r in res)
        return nbytes / max(1.0, rate) + self.sim.path_latency(src, dst)

    def note_dispatch(self, node, now):
        last = self._last.get(node)
        lam = self.lam.get(node, 0.0)
        if last is not None:
            dt = max(1e-3, now - last)
            lam = 0.8 * lam + 0.2 * (1.0 / dt)
        self.lam[node] = lam
        self._last[node] = now

    # -- candidate evaluation -------------------------------------------------------------------------------------
    def evaluate(self, view, req, sess, cand_nodes, rng, now, k_cost=None, topn=4):
        """Return (best_plan_or_None, ranked list). `cand_nodes`: n_p candidate node ids (admissible set)."""
        P, kvb = self.P, self.P.kvb
        H, q, out = req.hist, req.q, req.out
        hist_b, new_b = H * kvb, q * kvb
        need_total = (H + q + out) * kvb
        owner = sess.owner if H > 0 else None
        on, ot = owner if owner else (None, None)
        eps = self.eps
        noise = (lambda: math.exp(eps * rng.gauss(0, 1))) if eps > 0 else (lambda: 1.0)
        ctx_full = H + q
        nodes = view.nodes

        # ---- n_p side
        fp, ttft_p, info_p = {}, {}, {}
        for i in cand_nodes:
            nv = nodes[i]
            if H == 0:
                tst = 0.0
            elif i == on:
                tst = 0.0 if ot in ("hbm", "hbf") else self.xfer(hist_b, (on, ot), (i, "hbm"), view)
            else:
                tst = self.xfer(hist_b, (on, ot), (i, "hbm"), view)
            htier = "hbf" if (i == on and ot == "hbf") else "hbm"
            c = max(1, min(P.chunk, P.budget - nv.ndec))
            m = math.ceil(q / c)
            t_it = P.iter_time(nv.groups, [(c, ctx_full, htier, H)])
            tpf = m * t_it
            t_dec_only = P.iter_time(nv.groups, ()) if nv.ndec else 0.0
            x1 = nv.ndec * (m * max(0.0, t_it - t_dec_only) / max(1.0, out / 2.0)) / SLO_TPOT      # TPOT SLO-fractions lost by running decodes
            if nv.pf_tokens > 0:
                c_est = max(1, min(P.budget - nv.ndec, P.chunk * max(1, nv.njobs)))
                t_q = P.iter_time(nv.groups, [(c_est, ctx_full, "hbm", 0)])
                wait = nv.pf_tokens / c_est * t_q
            else:
                wait = 0.0
            tst, tpf, wait = tst * noise(), tpf * noise(), wait * noise()
            x2 = self.lam.get(i, 0.0) * tpf * tpf / 2.0 / SLO_TTFT                                     # TTFT SLO-fractions added to later arrivals
            fp[i] = (wait + tst + tpf) / SLO_TTFT + x1 + x2
            ttft_p[i] = wait + tst + tpf
            info_p[i] = (htier,)
        if not fp:
            return None, []
        order_p = sorted(fp, key=fp.get)

        # ---- n_d side (per (node, tier))
        results = []
        ndec_nodes = [nv for nv in nodes if nv.alive]
        for nv in ndec_nodes:
            d = nv.idx
            for t in DECODE_TIERS:
                if t == "hbf" and "hbf" not in P.mem:
                    continue
                delta = need_total - (sess.kv_bytes if (owner and owner == (d, t)) else 0.0)
                free = nv.free.get(t, 0.0)
                evict = 0.0
                if free < delta:
                    if t == "hbm" and free + nv.evictable >= delta:
                        evict = delta - free
                    else:
                        continue
                ctx_avg = H + q + out / 2.0
                g2 = dict(nv.groups)
                c0, s0 = g2.get(t, (0, 0.0))
                g2[t] = (c0 + 1, s0 + ctx_avg)
                try:
                    tpot = P.iter_time(g2, ()) * noise()
                except ValueError:
                    continue
                if tpot > SLO_TPOT:
                    continue
                t_base = P.iter_time(nv.groups, ()) if nv.ndec else 0.0
                x3 = nv.ndec * max(0.0, P.iter_time(g2, ()) - t_base) / SLO_TPOT                         # TPOT SLO-fractions added to resident decodes
                fd = tpot / SLO_TPOT + x3 + (self.xfer(evict, (d, "hbm"), (d, "dram"), view) / SLO_TTFT if evict else 0.0)
                # pair evaluation over n_p classes: owner node, d itself, and best others
                tried = []
                for i in (on, d):
                    if i is not None and i in fp and i not in tried:
                        tried.append(i)
                cnt = 0
                for i in order_p:
                    if i in tried:
                        continue
                    tried.append(i)
                    cnt += 1
                    if cnt >= 1:
                        break
                for i in tried:
                    if i == on:
                        promoted = ot not in ("hbm", "hbf")
                        hist_src = (i, "hbm") if promoted else (on, ot)
                        if ot == "hbf":
                            hist_src = (on, "hbf")
                    else:
                        hist_src = (on, ot)
                    th = self.xfer(new_b, (i, "hbm"), (d, t), view)
                    if H > 0 and hist_src != (d, t):
                        th += self.xfer(hist_b, hist_src, (d, t), view)
                    th *= noise()
                    cost = fp[i] + th / max(1.0, out - 1.0) / SLO_TPOT + fd       # handoff stall is amortized over the output tokens (TPOT_req)
                    results.append((cost, i, (d, t), ttft_p[i], tpot))
        if not results:
            return None, []
        results.sort(key=lambda x: x[0])
        feas = [r for r in results if r[3] <= SLO_TTFT]
        use = feas if feas else None
        if use is None:
            results.sort(key=lambda x: max(x[3] / SLO_TTFT, x[4] / SLO_TPOT))
            use = results
            feasible = False
        else:
            feasible = True
        ranked, seen = [], set()
        for r in use:
            key = (r[1], r[2])
            if key in seen:
                continue
            seen.add(key)
            ranked.append(r)
            if len(ranked) >= topn:
                break
        b = ranked[0]
        plan = Plan(b[1], b[2], b[0], [(r[1], r[2]) for r in ranked[1:]], now, 0, b[3], b[4], feasible)
        plan.bcost = [r[0] for r in ranked[1:]]
        return plan, ranked

    def cost_of(self, view, req, sess, n_p, n_d):
        """Exact cost of a specific plan under `view` (used for regret)."""
        ranked = []
        saved = self.eps
        self.eps = 0.0
        try:
            plan, ranked = self.evaluate(view, req, sess, [n_p], random.Random(0), 0.0, topn=1000)
        finally:
            self.eps = saved
        for r in ranked:
            if r[1] == n_p and r[2] == n_d:
                return r[0]
        return None
