"""Event-driven DP2 simulator (M0 spec 4-8). One Sim = one (system, scenario, candidate, seed, load) run."""
from __future__ import annotations

import heapq
import math
import random
import statistics
from collections import defaultdict

from .kvstore import KVStore, Session
from .net import FlowNet
from .node import Node, PJob, Seq
from .physics import (CFG, DECODE_TIERS, LINKS, OFFLOAD, Phys, cfgv, system, target)
from .policies import Estimator, NodeView, Plan, View, SLO_TPOT, SLO_TTFT

BASELINE, C1, C2 = "Baseline-PD-fixed", "C1-scheduling-time", "C2-pre-planned"
DLOCAL, ORACLE, PRETAIN = "Ref-D-local-always", "Ref-Oracle", "Ref-P-retain"
CANDIDATES = (BASELINE, C1, C2, DLOCAL, ORACLE, PRETAIN)
GIB = 2 ** 30


class Req:
    __slots__ = ("rid", "sess", "hist", "q", "out", "t_arr", "bg", "n_p", "n_d", "plan", "t_disp", "t_dec", "t_plan",
                 "t_stage0", "t_stage1", "t_enq", "t_first", "t_hand", "t_done", "gpu_s", "resv", "ctx_end", "hist_tier",
                 "promoted", "pend", "plan_ready", "plan_obj", "meas", "fallback", "regret", "plan_age", "wait_flows",
                 "t_pfstart", "decision_k")

    def __init__(self, rid, sess, hist, q, out, t_arr):
        self.rid, self.sess, self.hist, self.q, self.out, self.t_arr = rid, sess, hist, q, out, t_arr
        self.bg = False
        self.n_p = None
        self.n_d = None
        self.plan = None
        self.t_disp = self.t_dec = self.t_plan = None
        self.t_stage0 = self.t_stage1 = self.t_enq = self.t_first = self.t_hand = self.t_done = self.t_pfstart = None
        self.gpu_s = 0.0
        self.resv = None
        self.ctx_end = hist + q + out
        self.hist_tier = "hbm"
        self.promoted = False
        self.pend = 0
        self.plan_ready = False
        self.plan_obj = None
        self.meas = False
        self.fallback = False
        self.regret = None
        self.plan_age = None
        self.wait_flows = 0
        self.decision_k = 0


class Sim:
    def __init__(self, sys_id, sc, seed, cand, load=1.0, opts=None):
        self.sys_id, self.sc, self.seed, self.cand, self.load = sys_id, sc, seed, cand, load
        o = dict(kappa=cfgv("kappa_mix"), link=cfgv("internode_link"), tel=cfgv("telemetry_refresh_s"),
                 eps=cfgv("estimator_error_eps"), t_ref=cfgv("decision_cost_ref_s"), workers=cfgv("planner_workers_c2"),
                 topk=None, lam0=None, qcap=cfgv("node_queue_cap_tokens"), plan_age_max=cfgv("plan_age_max_s"),
                 c_val=cfgv("validation_cost_s"), hbm_mult=None, coalesce=False, horizon=300.0, warmup=30.0,
                 min_turns=1000, max_horizon=1200.0, regret_every=3)
        if sc.tel is not None:
            o["tel"] = sc.tel
        if opts:
            o.update(opts)
        self.o = o
        self.sysspec = system(sys_id)
        self.P = Phys(self.sysspec, o["kappa"])
        self.rng = random.Random(seed * 1000003 + sum(map(ord, sc.name)) * 7 + int(load * 1000))
        self.N = sc.nP + sc.nD
        self.nodes = [Node(i, "P" if i < sc.nP else "D", self.P) for i in range(self.N)]
        link = LINKS["profiles"][o["link"]]
        self.link_bw, self.link_lat = link["bw_bytes_per_s"] * link["efficiency"], link["base_latency_s"]
        mem = self.sysspec.memories
        caps = {t: mem[t].capacity_bytes for t in mem}
        hm = sc.hbm_mult if o["hbm_mult"] is None else o["hbm_mult"]
        self.kv = KVStore(range(self.N), caps, hm)
        self.net = FlowNet(self._caps())
        self.q = []          # event heap
        self._n = 0
        self.now = 0.0
        self.gq: list[Req] = []
        self.reqs: list[Req] = []
        self.rid = 0
        self.pending_tokens = defaultdict(float)
        self.sched_busy = False
        self.net_ver = 0
        self.snap = None
        self.est = Estimator(self, o["eps"])
        self.planner_q: list[Req] = []
        self.workers_busy = 0
        self.fault = False
        self.horizon = o["horizon"]
        self.end = None
        self.completed_meas = 0
        self.stats = dict(decisions=0, t_dec=[], replans=0, fallbacks=0, plan_age=[], regret=[], mis=0, dec_n=0,
                          demote_bytes=0.0)
        self.ttft_cens = []
        self.hist_loc = {}
        self.rr_d = 0
        self.bg_seqs = []
        self.sess_n = 0
        self.lam0 = o["lam0"]
        self.done_meas = []
        self.bg_gpu = 0.0

    # ------------------------------------------------------------------------------------------------------ infra
    def _caps(self):
        caps = {}
        mem = self.sysspec.memories
        scale = self.sc.link_scale
        for i in range(self.N):
            caps[f"nic_out:{i}"] = self.link_bw * scale
            caps[f"nic_in:{i}"] = self.link_bw * scale
            caps[f"hbm_w:{i}"] = self.P.hbm_w
            for t, m in mem.items():
                caps[f"tier:{i}:{t}"] = m.ext_bw
            caps[f"tierw:{i}:hbf"] = mem["hbf"].write_bw
        return caps

    def push(self, t, kind, a=None, b=None):
        self._n += 1
        heapq.heappush(self.q, (t, self._n, kind, a, b))

    def path_res(self, src, dst):
        res = []
        sn, st = src
        dn, dt = dst
        if st != "hbm":
            res.append(f"tier:{sn}:{st}")
        if sn != dn:
            res += [f"nic_out:{sn}", f"nic_in:{dn}"]
        if dt == "hbm":
            res.append(f"hbm_w:{dn}")
        elif dt == "hbf":
            res.append(f"tierw:{dn}:hbf")
        else:
            res.append(f"tier:{dn}:{dt}")
        return res

    def path_latency(self, src, dst):
        lat = self.sysspec.memories[src[1]].latency_s + self.sysspec.memories[dst[1]].latency_s
        return lat + (self.link_lat if src[0] != dst[0] else 0.0)

    def start_flow(self, nbytes, src, dst, cb, tag):
        """Start a transfer after its latency; `cb()` fires on completion."""
        if nbytes <= 0 or src == dst:
            self.push(self.now, "call", cb)
            return
        res = self.path_res(src, dst)
        lat = self.path_latency(src, dst)
        self.push(self.now + lat, "flowstart", (nbytes, res, cb, tag, src[0] != dst[0]))

    def net_touch(self):
        self.net.advance(self.now)
        for f in self.net.pop_done():
            f.cb()
        self.net.recompute()
        self.net_ver += 1
        t = self.net.next_completion()
        if t is not None:
            self.push(max(t, self.now), "netw", self.net_ver)

    def node_touch(self, nd):
        """Reschedule a node's next wake-up after a composition change."""
        nd.ver += 1
        dt = nd.predict_dt()
        if dt is not None:
            self.push(self.now + dt, "nodew", nd.idx, nd.ver)

    # ------------------------------------------------------------------------------------------------- views
    def _nodeview(self, nd, ev_by_node):
        i = nd.idx
        free = {t: self.kv.free(i, t) for t in ("hbm", "custom_hbm", "cxl_pnm", "hbf", "dram")}
        ev = ev_by_node.get(i, 0.0)
        groups = nd.groups()
        return NodeView(i, nd.role, len(nd.dec), groups, nd.outstanding_prefill_tokens() + self.pending_tokens[i], len(nd.pf), free, ev)

    def make_view(self):
        flows = defaultdict(int)
        for f in self.net.flows.values():
            for r in f.res:
                flows[r] += 1
        ev = defaultdict(float)
        for ss in self.kv.sessions.values():
            if ss.owner is not None and ss.owner[1] == "hbm" and not ss.active and not ss.pinned:
                ev[ss.owner[0]] += ss.kv_bytes
        return View([self._nodeview(nd, ev) for nd in self.nodes], flows)

    def live_view(self):
        for nd in self.nodes:
            nd.advance(self.now)
        return self.make_view()

    def take_snapshot(self):
        for nd in self.nodes:
            nd.advance(self.now)
        self.snap = self.make_view()

    # --------------------------------------------------------------------------------------------- workload
    def new_session(self, idx=None):
        sc = self.sc
        self.sess_n += 1
        s = Session(self.sess_n, self.sess_n)
        s.turns_left = sc.turns
        s.params = sc
        s.hist_tokens = sc.hist0(self.rng, self.sess_n) if sc.hist0 else 0
        s.last_access = self.now
        self.kv.sessions[s.sid] = s
        if s.hist_tokens > 0:
            dn = [n.idx for n in self.nodes if n.role == "D"]
            node = dn[self.rr_d % len(dn)]
            self.rr_d += 1
            nbytes = s.hist_tokens * self.P.kvb
            if sc.tier_pin and sc.tier_pin != "alloc":
                loc = (node, sc.tier_pin)
                s.pinned = False
                self.kv.place(s, loc, nbytes)
            else:
                loc = self.kv.allocate(dn, nbytes)
                if loc is None:
                    loc = (node, "dram")
                self.kv.place(s, loc, nbytes)
        return s

    def start_turn(self, s):
        sc = self.sc
        first = s.turns_left == sc.turns
        if first and s.hist_tokens == 0 and sc.prompt:
            q = sc.prompt(self.rng)
        elif first and s.hist_tokens > 0:
            q = sc.tool_first if sc.tool_first else sc.tool
        else:
            q = sc.tool
        out = sc.out(self.now)
        self.rid += 1
        r = Req(self.rid, s, s.hist_tokens, q, out, self.now)
        self.reqs.append(r)
        s.active = True
        self.on_arrival(r)

    def think(self):
        return self.rng.lognormvariate(math.log(self.sc.think_median), 0.5)

    def open_arrivals(self):
        """Thinned Poisson session arrivals for open-loop scenarios."""
        sc = self.sc
        lam_max = sc.lam_max(self.lam0, self.load)
        t = self.now
        while True:
            t += self.rng.expovariate(lam_max)
            if t > self.max_end:
                break
            if self.rng.random() <= sc.lam(t, self.lam0, self.load) / lam_max:
                self.push(t, "sess_arrive")

    # ----------------------------------------------------------------------------------------------- admission
    def outstanding(self, i):
        return self.nodes[i].outstanding_prefill_tokens() + self.pending_tokens[i]

    def est_view(self):
        return self.snap if self.snap is not None else self.make_view()

    # ------------------------------------------------------------------------------------------ arrival/dispatch
    def on_arrival(self, r):
        self.gq.append(r)
        if self.cand == C2:
            self.planner_q.append(r)
            self.run_workers()
        self.try_dispatch()

    def kcount(self, cand_nodes):
        n = self.N
        tk = self.o["topk"]
        if tk:
            return (min(tk, n) + 1) * (min(tk, n) + 1) * len(DECODE_TIERS)
        return len(cand_nodes) * n * len(DECODE_TIERS)

    def t_dec_for(self, k):
        return self.o["t_ref"] * k / 64.0

    def cand_nodes_for(self, view, cap_mult):
        nodes = [nv.idx for nv in view.nodes if nv.pf_tokens < self.o["qcap"] * cap_mult]
        return nodes

    def restrict(self, view, sess, hist):
        """top-k pruning (optional): keep k least-loaded P candidates and k most-free D nodes (+ owner node)."""
        tk = self.o["topk"]
        if not tk:
            return view, None
        on = sess.owner[0] if (sess.owner and hist > 0) else None
        by_load = sorted(view.nodes, key=lambda nv: nv.pf_tokens)[:tk]
        by_free = sorted(view.nodes, key=lambda nv: -nv.free["hbm"])[:tk]
        keep_p = {nv.idx for nv in by_load} | ({on} if on is not None else set())
        keep_d = {nv.idx for nv in by_free} | ({on} if on is not None else set())
        nodes = []
        for nv in view.nodes:
            c = NodeView(nv.idx, nv.role, nv.ndec, nv.groups, nv.pf_tokens, nv.njobs, nv.free, nv.evictable)
            c.alive = nv.idx in keep_d
            nodes.append(c)
        return View(nodes, view.flows), keep_p

    def baseline_plan(self, req, view, role_split=True, dlocal=False, retain=False):
        sess = req.sess
        sc = self.sc
        dn = [n.idx for n in self.nodes if n.role == "D"]
        if sess.owner is not None and req.hist > 0:
            on, ot = sess.owner
        else:
            on, ot = None, None
        if on is None:
            on = max(dn, key=lambda i: view.nodes[i].free["hbm"])
        if dlocal:
            n_p = on
            if view.nodes[n_p].pf_tokens >= self.o["qcap"]:
                return None
            tier = ot if ot in ("hbm", "hbf") else "hbm"
            return Plan(n_p, (on, tier), 0.0, [], self.now, 0, 0, 0)
        pn = [n.idx for n in self.nodes if n.role == "P"]
        if retain and sess.p_cache_node is not None and view.nodes[sess.p_cache_node].pf_tokens < self.o["qcap"]:
            n_p = sess.p_cache_node
        else:
            ok = [i for i in pn if view.nodes[i].pf_tokens < self.o["qcap"]]
            if not ok:
                return None
            n_p = min(ok, key=lambda i: (view.nodes[i].pf_tokens, i))
        return Plan(n_p, (on, "hbm"), 0.0, [], self.now, 0, 0, 0)

    def plan_with(self, view, req, now, cap_mult=1.0, rng=None, gate=True):
        sess = req.sess
        v, keep_p = self.restrict(view, sess, req.hist)
        cn = [nv.idx for nv in v.nodes if (not gate or nv.pf_tokens < self.o["qcap"] * cap_mult) and (keep_p is None or nv.idx in keep_p)]
        if not cn:
            return None
        plan, ranked = self.est.evaluate(v, req, sess, cn, rng or random.Random(self.seed * 31 + req.rid), now)
        if plan is not None:
            plan.k = self.kcount(cn)
        return plan

    def decide_instant(self, req):
        """Rule / Oracle policies: decision at dispatch time, zero cost."""
        if self.cand == ORACLE:
            ov = self.live_view()
            saved = self.est.eps
            self.est.eps = 0.0
            try:
                return self.plan_with(ov, req, self.now, 1.0, random.Random(0))
            finally:
                self.est.eps = saved
        return self.baseline_plan(req, self.est_view(), dlocal=(self.cand == DLOCAL), retain=(self.cand == PRETAIN))

    def try_dispatch(self):
        if not self.gq:
            return
        c = self.cand
        scanned = 0
        i = 0
        if c in (BASELINE, DLOCAL, PRETAIN, ORACLE) or (self.fault and c in (C1, C2)):
            while i < len(self.gq) and scanned < 128:
                r = self.gq[i]
                scanned += 1
                if self.fault and c in (C1, C2):
                    plan = self.baseline_plan(r, self.est_view())
                    r.fallback = True
                    self.stats["fallbacks"] += 1
                else:
                    plan = self.decide_instant(r)
                if plan is not None and self.commit(r, plan, 0.0):
                    self.gq.pop(i)
                else:
                    if plan is not None and r.fallback:
                        self.stats["fallbacks"] -= 1
                    r.fallback = False
                    i += 1
            return
        if self.sched_busy:
            return
        if c == C1:
            while i < len(self.gq) and scanned < 64:
                r = self.gq[i]
                scanned += 1
                view = self.est_view()
                plan = self.plan_with(view, r, self.now)
                if plan is None:
                    i += 1
                    continue
                t_dec = self.t_dec_for(plan.k)
                self.gq.pop(i)
                self.sched_busy = True
                r.t_dec = t_dec
                r.decision_k = plan.k
                self.push(self.now + t_dec, "c1done", r, plan)
                return
            return
        # C2: dispatch requests whose plan is ready
        while i < len(self.gq) and scanned < 64:
            r = self.gq[i]
            scanned += 1
            if not r.plan_ready:
                i += 1
                continue
            # at least one node must have room (global queue gate)
            if not any(self.outstanding(n.idx) < self.o["qcap"] for n in self.nodes):
                return
            self.gq.pop(i)
            self.sched_busy = True
            self.push(self.now + self.o["c_val"], "c2valid", r)
            return

    # --------------------------------------------------------------------------------------------- C2 workers
    def run_workers(self):
        while self.workers_busy < self.o["workers"] and self.planner_q:
            r = self.planner_q.pop(0)
            if self.fault:
                r.plan_ready = True
                r.plan_obj = None
                continue
            view = self.est_view()
            plan = self.plan_with(view, r, self.now, gate=False)
            self.workers_busy += 1
            k = plan.k if plan else self.kcount(range(self.N))
            self.push(self.now + self.t_dec_for(k), "planready", r, plan)

    # ------------------------------------------------------------------------------------------------- commit
    def commit(self, req, plan, t_dec):
        """Reserve capacity and start execution. Returns False if the plan cannot start now (request stays queued)."""
        sess = req.sess
        d, t = plan.n_d
        i = plan.n_p
        if self.outstanding(i) >= self.o["qcap"] * (2.0 if self.cand == C2 else 1.0):
            return False
        delta = req.ctx_end * self.P.kvb - (sess.kv_bytes if sess.owner == (d, t) else 0.0)
        flows = []
        if self.kv.free(d, t) < delta:
            if t == "hbm":
                need = delta - self.kv.free(d, t)
                vic = self.kv.victims(d, need, sess.sid)
                if vic is None:
                    return False
                for v in vic:
                    dst = self.kv.demote_dst(d, v.kv_bytes)
                    if dst is None:
                        return False
                for v in vic:
                    dst = self.kv.demote_dst(d, v.kv_bytes)
                    nb = v.kv_bytes
                    self.kv.place(v, (d, dst), nb)
                    flows.append((nb, (d, "hbm"), (d, dst)))
            else:
                return False
        self.kv.resv[(d, t)] += delta
        req.resv = (d, t, delta)
        req.n_p, req.n_d, req.plan = i, (d, t), plan
        req.t_disp = self.now
        req.t_dec = t_dec if req.t_dec is None else req.t_dec
        self.pending_tokens[i] += req.q
        req.pend = req.q
        if self.snap is not None:               # the router knows its own dispatches immediately (local bookkeeping)
            nv = self.snap.nodes[i]
            nv.pf_tokens += req.q
            nv.njobs += 1
            self.snap.nodes[d].free[t] -= delta
        self.est.note_dispatch(i, self.now)
        if self.cand in (C1, C2) and not req.fallback:
            self.stats["decisions"] += 1
            self.stats["t_dec"].append(req.t_dec or 0.0)
            self.stats["plan_age"].append(self.now - plan.t_plan if self.cand == C2 else 0.0)
            if self.stats["decisions"] % self.o["regret_every"] == 0:
                self.record_regret(req, plan)
        if flows:
            req.wait_flows = len(flows)
            for nb, src, dst in flows:
                self.stats["demote_bytes"] += nb
                self.start_flow(nb, src, dst, lambda r=req: self._room_done(r), "demote")
        else:
            self.start_staging(req)
        return True

    def record_regret(self, req, plan):
        try:
            lv = self.live_view()
            sess = req.sess
            saved = self.est.eps
            self.est.eps = 0.0
            try:
                best, ranked = self.est.evaluate(lv, req, sess, [n.idx for n in self.nodes], random.Random(0), self.now, topn=2000)
            finally:
                self.est.eps = saved
            if best is None:
                return
            ch = None
            for r in ranked:
                if r[1] == plan.n_p and r[2] == plan.n_d:
                    ch = r[0]
                    break
            if ch is None:
                return
            reg = max(0.0, ch - best.cost)
            req.regret = reg
            self.stats["regret"].append(reg)
            if reg > 1e-9:
                self.stats["mis"] += 1
            self.stats["dec_n"] += 1
        except Exception:
            pass

    def _room_done(self, req):
        req.wait_flows -= 1
        if req.wait_flows == 0:
            self.start_staging(req)

    # ------------------------------------------------------------------------------------------------ staging
    def start_staging(self, req):
        sess = req.sess
        H, i = req.hist, req.n_p
        req.t_stage0 = self.now
        if H == 0 or sess.owner is None:
            return self.stage_done(req)
        on, ot = sess.owner
        hist_b = H * self.P.kvb
        if i == on:
            if ot in ("hbm", "hbf"):
                req.hist_tier = ot
                return self.stage_done(req)
            req.promoted = True
            self.start_flow(hist_b, (on, ot), (i, "hbm"), lambda r=req: self._promoted(r), "promote")
            return
        nb = hist_b
        if self.cand == PRETAIN and sess.p_cache_node == i:
            nb = max(0.0, hist_b - sess.p_cache * self.P.kvb)
        self.start_flow(nb, (on, ot), (i, "hbm"), lambda r=req: self.stage_done(r), "copy")

    def _promoted(self, req):
        sess = req.sess
        i = req.n_p
        self.kv.place(sess, (i, "hbm"), req.hist * self.P.kvb)
        req.hist_tier = "hbm"
        self.stage_done(req)

    def stage_done(self, req):
        self.now_stage = self.now
        req.t_stage1 = self.now
        i = req.n_p
        nd = self.nodes[i]
        nd.advance(self.now)
        job = PJob(req, req.q, req.hist + req.q, req.hist_tier, req.hist, self.now)
        req.t_enq = self.now
        self.pending_tokens[i] -= req.pend
        req.pend = 0
        nd.pf.append(job)
        self.node_touch(nd)

    # ------------------------------------------------------------------------------------------ completions
    def on_prefill_done(self, nd, job):
        req = job.req
        req.t_first = self.now
        req.t_pfstart = job.t_start
        req.gpu_s += job.gpu_s
        sess = req.sess
        i = nd.idx
        d, t = req.n_d
        self.try_dispatch()
        # P-retain bookkeeping
        if self.cand == PRETAIN and nd.role == "P":
            sess.p_cache, sess.p_cache_node = req.hist + req.q, i
        pending = []
        new_b = req.q * self.P.kvb
        if (i, "hbm") != (d, t):
            pending.append((new_b, (i, "hbm"), (d, t), "handoff"))
        if req.hist > 0 and sess.owner is not None and sess.owner != (d, t):
            pending.append((req.hist * self.P.kvb, sess.owner, (d, t), "handoff"))
        if not pending:
            return self.start_decode(req)
        req.wait_flows = len(pending)
        for nb, src, dst, tag in pending:
            self.start_flow(nb, src, dst, lambda r=req: self._hand_done(r), tag)

    def _hand_done(self, req):
        req.wait_flows -= 1
        if req.wait_flows == 0:
            self.start_decode(req)

    def start_decode(self, req):
        d, t = req.n_d
        nd = self.nodes[d]
        nd.advance(self.now)
        req.t_hand = self.now
        sess = req.sess
        dres, tres, delta = req.resv
        self.kv.resv[(dres, tres)] -= delta
        self.kv.place(sess, (d, t), req.ctx_end * self.P.kvb)
        if req.out <= 1:
            nd.dec.append(Seq(req, 1e-9, req.hist + req.q, t))
        else:
            nd.dec.append(Seq(req, req.out - 1, req.hist + req.q, t))
        self.node_touch(nd)

    def on_decode_done(self, nd, seq):
        req = seq.req
        if seq.bg:
            self.bg_gpu += seq.gpu_s
            self.add_bg(nd.idx)
            return
        req.t_done = self.now
        req.gpu_s += seq.gpu_s
        sess = req.sess
        sess.active = False
        sess.last_access = self.now
        sess.hist_tokens = req.ctx_end
        sc = self.sc
        if sc.tier_pin and sc.tier_pin not in ("alloc", "hbm") and sess.owner and sess.owner[1] != sc.tier_pin:
            self.kv.place(sess, (sess.owner[0], sc.tier_pin), sess.kv_bytes)
        sess.turns_left -= 1
        if req.t_arr >= self.warm:
            self.completed_meas += 1
        self.try_dispatch()
        if sc.mode == "closed_clients":
            self.kv.sessions.pop(sess.sid, None)
            if sess.owner:
                self.kv.occ[sess.owner] -= sess.kv_bytes
            s2 = self.new_session()
            self.start_turn(s2)
            return
        if sess.turns_left > 0:
            self.push(self.now + self.think(), "turn", sess)
        else:
            if sess.owner:
                self.kv.occ[sess.owner] -= sess.kv_bytes
            self.kv.sessions.pop(sess.sid, None)
            if sc.mode == "closed_sessions":
                self.push(self.now + 0.5, "sess_replace")

    def add_bg(self, d):
        nd = self.nodes[d]
        nd.advance(self.now)
        s = Seq(None, 2048, 8192, "hbm", bg=True)
        nd.dec.append(s)
        self.node_touch(nd)

    # ----------------------------------------------------------------------------------------------- run loop
    def run(self):
        sc, o = self.sc, self.o
        self.warm = o["warmup"]
        self.max_end = o["max_horizon"]
        for nd in self.nodes:
            nd.win = (self.warm, float("inf"))
        # background decode sessions (occupy HBM pool; excluded from metrics)
        dn = [n.idx for n in self.nodes if n.role == "D"]
        for k in range(sc.bg_decode):
            d = dn[k % len(dn)]
            self.kv.occ[(d, "hbm")] += 8192 * self.P.kvb
            self.nodes[d].dec.append(Seq(None, 2048.0 * (1 + (k % 5) / 5), 8192, "hbm", bg=True))
        if sc.occupant_frac:
            for d in dn:
                self.kv.occ[(d, "hbm")] += sc.occupant_frac * self.kv.pool[(d, "hbm")]
        for d in dn:
            self.node_touch(self.nodes[d])
        self.take_snapshot()
        self.push(o["tel"], "tel")
        # workload
        pop = sc.population(self.load)
        if sc.mode in ("closed_clients", "closed_sessions"):
            for k in range(pop):
                s = self.new_session()
                if sc.mode == "closed_clients":
                    self.push(1e-3 * k, "turn", s)
                else:
                    self.push(self.rng.uniform(0, sc.think_median), "turn", s)
        else:
            if self.lam0 is None:
                raise ValueError("open-loop scenario needs lam0")
            self.open_arrivals()
        for (t, kind, a) in sc.ext_events(o):
            self.push(t, kind, a)
        self.end = None
        while self.q:
            t, _, kind, a, b = heapq.heappop(self.q)
            if t > self.max_end:
                break
            self.now = t
            if self.end is None and t >= self.horizon and (self.completed_meas >= o["min_turns"] or t >= self.max_end):
                self.end = t
                break
            self.dispatch_event(kind, a, b)
        if self.end is None:
            self.end = min(self.now, self.max_end)
        return self.finish()

    def dispatch_event(self, kind, a, b):
        if kind == "nodew":
            nd = self.nodes[a]
            if b != nd.ver:
                return
            nd.advance(self.now)
            pdone, ddone = nd.pop_completed()
            for j in pdone:
                self.on_prefill_done(nd, j)
            for sq in ddone:
                self.on_decode_done(nd, sq)
            self.node_touch(nd)
        elif kind == "netw":
            if a == self.net_ver:
                self.net_touch()
        elif kind == "flowstart":
            nbytes, res, cb, tag, inter = a
            self.net.advance(self.now)
            f = self.net.add(nbytes, res, cb, tag + (":inter" if inter else ":intra"))
            self.net_touch()
        elif kind == "call":
            a()
        elif kind == "turn":
            self.start_turn(a)
        elif kind == "sess_arrive":
            s = self.new_session()
            self.start_turn(s)
        elif kind == "sess_replace":
            s = self.new_session()
            self.start_turn(s)
        elif kind == "tel":
            self.take_snapshot()
            self.push(self.now + self.o["tel"], "tel")
            self.try_dispatch()
        elif kind == "c1done":
            self.sched_busy = False
            r, plan = a, b
            if not self.commit(r, plan, r.t_dec):
                r.t_dec = None
                self.gq.insert(0, r)
            self.try_dispatch()
        elif kind == "planready":
            self.workers_busy -= 1
            r, plan = a, b
            r.plan_ready = True
            r.plan_obj = plan
            r.t_plan = self.now if plan is None else plan.t_plan
            self.run_workers()
            self.try_dispatch()
        elif kind == "c2valid":
            self.c2_validate(a)
        elif kind == "ext":
            a(self)
        elif kind == "fault":
            self.fault = bool(a)
            if self.fault:
                self.workers_busy = 0
            self.try_dispatch()

    def c2_validate(self, r):
        self.sched_busy = False
        plan = r.plan_obj
        view = self.est_view()
        age = self.now - (plan.t_plan if plan else self.now)
        cands = []
        if plan is not None:
            cands = [(plan.n_p, plan.n_d)] + list(plan.backups)
        sess = r.sess
        okplan = None
        for (i, (d, t)) in cands:
            nv = view.nodes[i]
            if age > self.o["plan_age_max"]:
                break
            if nv.pf_tokens >= 2 * self.o["qcap"]:
                continue
            delta = r.ctx_end * self.P.kvb - (sess.kv_bytes if sess.owner == (d, t) else 0.0)
            if self.kv.free(d, t) + (view.nodes[d].evictable if t == "hbm" else 0) < delta:
                continue
            okplan = Plan(i, (d, t), plan.cost, [], plan.t_plan, plan.k, 0, 0)
            break
        if okplan is not None:
            if self.commit(r, okplan, self.o["c_val"]):
                self.try_dispatch()
                return
            okplan = None
        # re-plan synchronously (C1-like cost)
        self.stats["replans"] += 1
        plan2 = self.plan_with(view, r, self.now)
        if plan2 is None:
            self.gq.insert(0, r)
            r.plan_ready = False
            self.planner_q.append(r)
            self.run_workers()
            self.try_dispatch()
            return
        t_dec = self.t_dec_for(plan2.k)
        self.sched_busy = True
        r.t_dec = t_dec
        plan2.t_plan = self.now
        self.push(self.now + t_dec, "c1done", r, plan2)

    # ------------------------------------------------------------------------------------------------ metrics
    def finish(self):
        end = self.end
        w0 = self.warm
        win = max(1e-9, end - w0)
        for nd in self.nodes:
            nd.advance(end)
        ttfts, tpots, good_tok, met, served = [], [], 0.0, 0, 0
        comp = defaultdict(float)
        ncomp = 0
        gpu_total, gpu_useful = defaultdict(float), defaultdict(float)
        offered = 0
        for r in self.reqs:
            if r.t_arr < w0 or r.t_arr > end:
                continue
            offered += 1
            if r.t_first is None:
                ttfts.append(end - r.t_arr)           # censored
                continue
            ttft = r.t_first - r.t_arr
            ttfts.append(ttft)
            if r.t_done is not None and r.t_done <= end:
                served += 1
                tpot = (r.t_done - r.t_first) / max(1, r.out - 1)
                tpots.append(tpot)
                if ttft <= SLO_TTFT and tpot <= SLO_TPOT:
                    good_tok += r.out
                    met += 1
                    r.meas = True
                c_sched = (r.t_disp or r.t_arr) - r.t_arr - (r.t_dec or 0.0)
                comp["schedule"] += max(0.0, c_sched)
                comp["decision"] += r.t_dec or 0.0
                comp["move"] += (r.t_stage1 - r.t_stage0) if r.t_stage0 is not None else 0.0
                comp["queue"] += ((r.t_pfstart or r.t_enq) - r.t_enq) if r.t_enq is not None else 0.0
                comp["prefill"] += (r.t_first - (r.t_pfstart or r.t_enq)) if r.t_enq is not None else 0.0
                ncomp += 1
        for k in comp:
            comp[k] /= max(1, ncomp)

        def pct(xs, p):
            if not xs:
                return float("nan")
            xs = sorted(xs)
            k = min(len(xs) - 1, max(0, int(math.ceil(p * len(xs))) - 1))
            return xs[k]

        # utilization
        busy = [nd.busy_win / win for nd in self.nodes]
        pool = {}
        for role in ("P", "D"):
            xs = [busy[i] for i, nd in enumerate(self.nodes) if nd.role == role]
            pool[role] = statistics.mean(xs) if xs else 0.0

        def cv(role):
            xs = [busy[i] for i, nd in enumerate(self.nodes) if nd.role == role]
            if len(xs) < 2 or statistics.mean(xs) == 0:
                return 0.0
            return statistics.pstdev(xs) / statistics.mean(xs)

        met_gpu = sum(r.gpu_s for r in self.reqs if r.meas)
        bg_gpu = self.bg_gpu + sum(q.gpu_s for nd in self.nodes for q in nd.dec if q.bg)
        busy_all = sum(nd.busy_all for nd in self.nodes)
        share = (met_gpu + bg_gpu) / busy_all if busy_all > 0 else 0.0
        useful_util = min(1.0, share) * (sum(busy) / self.N)
        nb = self.net.bytes_by_class
        inter = sum(v for k, v in nb.items() if k.endswith(":inter"))
        intra = sum(v for k, v in nb.items() if k.endswith(":intra"))
        turns = max(1, served)
        nic_util = [self.net.res_busy_s.get(f"nic_out:{i}", 0.0) / max(1e-9, end) for i in range(self.N)]
        st = self.stats

        def mean(x):
            return statistics.mean(x) if x else 0.0

        return dict(
            meta=dict(system=self.sys_id, scenario=self.sc.name, candidate=self.cand, seed=self.seed, load=self.load),
            qa=dict(goodput_tok_s=good_tok / win, ttft_p50_s=pct(ttfts, .5), ttft_p95_s=pct(ttfts, .95), ttft_p99_s=pct(ttfts, .99),
                    tpot_p50_s=pct(tpots, .5), tpot_p95_s=pct(tpots, .95), tpot_p99_s=pct(tpots, .99),
                    slo_met_frac=(met / offered if offered else 0.0), useful_utilization=useful_util),
            requests=dict(offered=offered, served=served, measured_turns=served, dropped=offered - served),
            utilization=dict(node_busy_frac={str(i): b for i, b in enumerate(busy)}, pool_busy_frac=pool, cv_p=cv("P"), cv_d=cv("D"),
                             gpu_idle_frac=1.0 - mean(busy)),
            transfers=dict(internode_bytes=inter, intranode_bytes=intra, per_turn_internode_gib_mean=inter / GIB / turns,
                           link_util_mean=mean(nic_util), link_util_p99=pct(nic_util, .99)),
            planner=dict(decisions=st["decisions"], t_dec_mean_s=mean(st["t_dec"]), t_dec_p99_s=pct(st["t_dec"], .99) if st["t_dec"] else 0.0,
                         plan_age_mean_s=mean(st["plan_age"]), plan_age_p99_s=pct(st["plan_age"], .99) if st["plan_age"] else 0.0,
                         replans=st["replans"], fallbacks=st["fallbacks"], regret_mean_s=mean(st["regret"]),
                         regret_p99_s=pct(st["regret"], .99) if st["regret"] else 0.0,
                         mis_selection_rate=(st["mis"] / st["dec_n"]) if st["dec_n"] else 0.0),
            ttft_components_mean_s={k: comp.get(k, 0.0) for k in ("schedule", "decision", "queue", "move", "prefill")},
            extra=dict(end=end, horizon=self.horizon, turns=served, demote_gib=st["demote_bytes"] / GIB),
        )
