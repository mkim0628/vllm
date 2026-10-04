"""Discrete-event simulator of the DP4 P/D cluster (heapq).

Request life: arrival (seeded Poisson, deterministic lengths) -> control-plane lookup -> DP2 cost argmin
(queue + prefill + move) -> prefill (node-exclusive FCFS) -> KV move (link FIFO fluid servers, layer-pipeline
overlap) -> [candidates: publish, pin] -> continuous-batching decode (processor sharing, batch cap) -> [unpin].
Output is a simulation result: Evidence [B+C].
"""
from __future__ import annotations

import heapq
import math
import random
from collections import deque
from dataclasses import dataclass, field

from arms import (ARM_CLASSES, BASE, LOCK_KINDS, C1, C2, clip)

NEVER_MS = 1e9  # latency of a request that never finished (stuck / failed): counts as an SLO violation

(EV_ARRIVE, EV_LOOKUP_DONE, EV_XFER, EV_MOVE_DONE, EV_PUBLISHED, EV_PINNED, EV_ADMIT, EV_DEC, EV_STALL_BEGIN,
 EV_STALL_END, EV_UNPINNED, EV_NODE_CRASH, EV_NODE_RECOVER, EV_EVICTED, EV_LRU_DONE, EV_ALLOCED) = range(16)


@dataclass(eq=False)
class Req:
    rid: int
    t: float
    L: int  # total context tokens
    H: int  # History KV tokens already cached (reuse)
    out: int
    session: int
    turn: int
    last_turn: bool
    hot: bool
    u: tuple
    p: int = -1
    d: int = -1
    mode: str = ""  # "p" (prefill node) | "dlocal"
    dead: bool = False
    evicted: bool = False
    alloced: bool = False
    t_pf_start: float = None
    t_pf_end: float = None
    t_flow_start: float = None
    t_flow_end: float = None
    t_admit: float = None
    t_first: float = None
    t_done: float = None
    t_unpin: float = None
    t_dead: float = None
    t_cp_done: float = None


class Link:
    __slots__ = ("cap", "bg0", "bg1", "H", "busy", "acc", "w0", "w1")

    def __init__(self, cap, bg0, bg1, H, w0, w1):
        self.cap, self.bg0, self.bg1, self.H, self.w0, self.w1 = cap, bg0, bg1, H, w0, w1
        self.busy = 0.0
        self.acc = 0.0

    def bw(self, t):
        x = min(max(t / self.H, 0.0), 1.0)
        return max(self.cap * (1.0 - (self.bg0 + (self.bg1 - self.bg0) * x)), self.cap * 0.01)

    def reserve(self, t, nbytes):
        s = t if t > self.busy else self.busy
        d0 = nbytes / self.bw(s)
        d = nbytes / self.bw(s + d0 / 2)
        e = s + d
        self.busy = e
        self.acc += clip(s, e, self.w0, self.w1)
        return s, e


class DNode:
    def __init__(self, sim, idx):
        self.sim, self.idx = sim, idx
        self.active = {}  # rid -> [remaining steps, req]
        self.queue = deque()
        self.t_last = 0.0
        self.step = 0.0
        self.ver = 0
        self.stall_n = 0
        self.pf_busy = 0.0
        self.load = 0
        self._cache = {}

    def step_s(self, n, ctx):
        key = (n, ctx // 128)
        v = self._cache.get(key)
        if v is None:
            v = self.sim.system.decode_step_s(max(1, ctx), n, "hbm")
            self._cache[key] = v
        return v

    def advance(self, t):
        if t > self.t_last:
            if self.stall_n == 0 and self.active and self.step > 0:
                prog = (t - self.t_last) / self.step
                for e in self.active.values():
                    e[0] -= prog
            self.t_last = t

    def reschedule(self, t):
        self.ver += 1
        if not self.active or self.stall_n > 0:
            return
        n = len(self.active)
        ctx = sum(e[1].L + e[1].out - e[0] for e in self.active.values()) // n
        self.step = self.step_s(n, int(ctx))
        for e in self.active.values():
            if e[1].t_first is None:
                e[1].t_first = t + self.step
        m = min(e[0] for e in self.active.values())
        self.sim.push(t + max(m, 0.0) * self.step, EV_DEC, self, self.ver)

    def join(self, r, t):
        self.advance(t)
        if len(self.active) >= self.sim.p.batch_cap:
            self.queue.append(r)
            return
        self.active[r.rid] = [float(r.out), r]
        r.t_admit = t
        self.reschedule(t)


def percentile(xs, q):
    if not xs:
        return 0.0
    s = sorted(xs)
    return s[min(len(s) - 1, max(0, math.ceil(q * len(s)) - 1))]


def turn_plan(p, knobs):
    """[(L, H, q)] per turn of an agent session; single entry for a plain request."""
    if knobs["turns"] <= 1:
        return [(knobs["in_tokens"], 0, knobs["in_tokens"])]
    plan = []
    L = knobs["in_tokens"]
    plan.append((L, 0, L))
    for _ in range(knobs["turns"] - 1):
        H = L + knobs["out_tokens"]
        L = H + p.turn_new_tokens
        plan.append((L, H, p.turn_new_tokens))
    return plan


def p_sat_rate(system, p, knobs):
    plan = turn_plan(p, knobs)
    mean_pf = sum(system.prefill_s(L, q) for L, H, q in plan) / len(plan)
    return knobs["n_p"] / mean_pf


def base_rate(system, p, knobs):
    return p.base_load_frac * p_sat_rate(system, p, knobs)


def make_trace(system, p, knobs, seed, load, abs_rate=None, n_req=None):
    """Arm-independent trace. Unit exponentials make traces at different loads time-scaled copies.
    abs_rate/n_req: control-plane-only runs (cp_saturation) fix the request rate in req/s directly."""
    base = base_rate(system, p, knobs)
    rate = base * load if abs_rate is None else abs_rate
    H = (p.n_req_base if n_req is None else n_req) / (base if abs_rate is None else abs_rate)
    rng = random.Random(seed)
    rng2 = random.Random(seed * 7919 + 13)
    plan = turn_plan(p, knobs)
    nt = len(plan)
    reqs = []
    sid = 0
    if nt == 1:
        t = 0.0
        while True:
            t += rng.expovariate(1.0) / rate
            if t >= H:
                break
            u = tuple(rng2.random() for _ in range(6))
            hot = knobs["hot"] and rng2.random() < p.shared_prefix_frac
            L, Hh, _ = plan[0]
            reqs.append(Req(0, t, L, 0, knobs["out_tokens"], sid, 0, True, hot, u))
            sid += 1
    else:
        t = -(nt - 1) * p.turn_gap_s
        lam = rate / nt
        while True:
            t += rng.expovariate(1.0) / lam
            if t >= H:
                break
            for j, (L, Hh, _) in enumerate(plan):
                tj = t + j * p.turn_gap_s
                u = tuple(rng2.random() for _ in range(6))
                if 0.0 <= tj < H:
                    reqs.append(Req(0, tj, L, Hh, knobs["out_tokens"], sid, j, j == nt - 1, False, u))
            sid += 1
        reqs.sort(key=lambda r: (r.t, r.session, r.turn))
    for i, r in enumerate(reqs):
        r.rid = i
    return reqs, H, base


class Sim:
    EV_NODE_CRASH = EV_NODE_CRASH

    def __init__(self, system, p, knobs, arm_name, seed, load, zero_cp=False, cp_only=False, with_fail=True,
                 abs_rate=None, n_req=None):
        self.system, self.knobs = system, knobs
        over = {k: knobs[k] for k in ("block_tokens", "lock_stripes", "server_threads") if knobs.get(k)}
        self.p = p.with_overrides(**over) if over else p
        p = self.p
        self.arm_name, self.seed, self.load = arm_name, seed, load
        self.cp_only, self.with_fail = cp_only, with_fail
        self.n_p, self.n_d = knobs["n_p"], knobs["n_d"]
        self.N = self.n_p + self.n_d
        self.reqs, self.H, self.base = make_trace(system, p, knobs, seed, load, abs_rate, n_req)
        self.w0, self.w1 = p.warmup_frac * self.H, self.H
        self.heap = []
        self.seq = 0
        self.alive = [True] * self.N
        self.arm = ARM_CLASSES[arm_name](self, p, knobs, zero_cp)
        self.kvb = system.model.kv_bytes_per_token
        pool = self.arm.uses_pool
        self.pool_mode = pool
        nb = p.cxl_node_bw if pool else p.rdma_node_bw
        mk = lambda cap: Link(cap, knobs["bg0"], knobs["bg1"], self.H, self.w0, self.w1)
        self.eg = [mk(nb) for _ in range(self.N)]
        self.ing = [mk(nb) for _ in range(self.N)]
        self.pool = mk(p.pool_bw_Bps) if pool else None
        self.pbusy = [0.0] * self.n_p
        self.dn = [DNode(self, i) for i in range(self.n_d)]
        self.sess_d = {}
        self.inflight = {}
        self.fail_info = dict(window_s=0.0, t_fail=None, kind=knobs["fail"])
        extra = (1.0 - knobs["kv_share"]) / knobs["kv_share"]
        self.obj_mult = 1.0 + extra
        self.sections = self.arm.op_sequence() if pool else ()
        self.evict_needed = pool and knobs["pool_occ"] >= p.evict_threshold

    # ------------------------------------------------------------------ plumbing
    def push(self, t, kind, a=None, b=None):
        self.seq += 1
        heapq.heappush(self.heap, (t, self.seq, kind, a, b))

    def nblk(self, tokens):
        return max(1, math.ceil(tokens / self.p.block_tokens))

    # ------------------------------------------------------------------ helpers
    def flow(self, t, items):
        """items: [(link, bytes)] -> (start, finish): each link is an independent FIFO fluid server."""
        st, fin = t, t
        for lk, b in items:
            s, e = lk.reserve(t, b)
            st = max(st, s)
            fin = max(fin, e)
        return st, fin

    def pick_d(self, r):
        if self.arm_name == BASE and r.H > 0:
            d = self.sess_d.get(r.session)
            if d is not None and self.alive[self.n_p + d]:
                return d
        best, bi = None, -1
        for i, dn in enumerate(self.dn):
            if self.alive[self.n_p + i] and (best is None or dn.load < best):
                best, bi = dn.load, i
        if self.arm_name == BASE and r.H > 0 and bi >= 0:
            self.sess_d[r.session] = bi
        return bi

    def move_items(self, r, q):
        """bytes crossing each link for one request: q tokens produced by P, L tokens consumed by D."""
        k = self.kvb * self.obj_mult
        nd = self.n_p + r.d
        if self.pool_mode:
            return [(self.eg[r.p], q * k), (self.pool, (q + r.L) * k), (self.ing[nd], r.L * k)]
        return [(self.eg[r.p], q * k), (self.ing[nd], q * k)]

    # ------------------------------------------------------------------ main loop
    def run(self):
        p = self.p
        for r in self.reqs:
            self.push(r.t, EV_ARRIVE, r)
        if self.with_fail and self.knobs["fail"]:
            tf = self.w0 + 0.3 * (self.w1 - self.w0)
            self.fail_info["t_fail"] = tf
            if self.knobs["fail"] == "server":
                if self.arm_name in (C1, "C1-no-batch"):
                    win = p.server_rebuild_s if self.knobs["fail_rebuild"] else p.server_restart_s
                    self.arm.server_down(tf, tf + win)
                    self.fail_info["window_s"] = win
            elif self.knobs["fail"] == "lockholder":
                if self.arm_name in (C2, "C2-no-scan"):
                    self.arm.arm_crash(0, tf)
                    lease = self.knobs["lease"]
                    self.fail_info["window_s"] = float("inf") if lease is None else lease
                else:
                    self.push(tf, EV_NODE_CRASH, 0, "lockholder")
        heap = self.heap
        while heap:
            t, _, k, a, b = heapq.heappop(heap)
            if k in LOCK_KINDS:
                self.arm.on_event(k, t, a, b)
            elif k == EV_DEC:
                self.on_dec(t, a, b)
            elif k == EV_ARRIVE:
                self.on_arrive(t, a)
            elif k == EV_LOOKUP_DONE:
                if not a.dead:
                    self.on_lookup_done(t, a)
            elif k == EV_XFER:
                if not a.dead:
                    self.on_xfer(t, a)
            elif k == EV_MOVE_DONE:
                if not a.dead:
                    self.on_move_done(t, a)
            elif k == EV_PUBLISHED:
                if not a.dead:
                    self.arm.submit("pin", t, a, self.nblk(a.L * self.obj_mult), EV_PINNED)
            elif k == EV_PINNED:
                if not a.dead:
                    self.on_pinned(t, a)
            elif k == EV_ADMIT:
                if not a.dead:
                    self.dn[a.d].join(a, t)
            elif k == EV_STALL_BEGIN:
                a.advance(t)
                a.stall_n += 1
                a.ver += 1
            elif k == EV_STALL_END:
                a.advance(t)
                a.stall_n -= 1
                a.reschedule(t)
                if not b.dead:
                    a.join(b, t)
            elif k == EV_UNPINNED:
                a.t_unpin = t
                if "lru" in self.sections:
                    self.arm.submit("lru", t, a, self.nblk(a.L), EV_LRU_DONE)
            elif k == EV_LRU_DONE:
                pass
            elif k == EV_EVICTED:
                if not a.dead:
                    self.on_xfer(t, a)
            elif k == EV_ALLOCED:
                if not a.dead:
                    self.on_xfer(t, a)
            elif k == EV_NODE_CRASH:
                self.on_crash(t, a)
            elif k == EV_NODE_RECOVER:
                self.alive[a] = True
                if a < self.n_p:
                    self.pbusy[a] = max(self.pbusy[a], t)
        return self.metrics()

    # ------------------------------------------------------------------ handlers
    def on_arrive(self, t, r):
        self.inflight[r.rid] = r
        hits = r.H if r.H else (self.p.shared_prefix_tokens if r.hot else 0)
        self.arm.submit("lookup", t, r, self.nblk(hits) + 1, EV_LOOKUP_DONE)

    def alive_p(self):
        return [i for i in range(self.n_p) if self.alive[i]]

    def fail(self, r, t):
        r.dead, r.t_dead = True, t
        self.inflight.pop(r.rid, None)

    def on_lookup_done(self, t, r):
        p, sysm = self.p, self.system
        ps = self.alive_p()
        d = self.pick_d(r)
        if not ps or d < 0:
            self.fail(r, t)
            return
        r.d = d
        self.dn[d].load += 1
        q = r.L - r.H
        pf = sysm.prefill_s(r.L, q) if r.H else sysm.prefill_s(r.L)
        if self.cp_only:
            r.p = ps[r.rid % len(ps)]
            r.t_pf_start = r.t_pf_end = r.t_flow_start = r.t_flow_end = t
            self.arm.submit("publish", t, r, self.nblk(r.L), EV_PUBLISHED) if self.pool_mode else self.finish(r, t)
            return
        k = self.kvb * self.obj_mult
        bw_nd = (p.cxl_node_bw if self.pool_mode else p.rdma_node_bw)
        # Baseline reuse: History KV sits on D -> D-local incremental prefill vs D->P + P prefill + P->D
        if self.arm_name == BASE and r.H > 0:
            dn = self.dn[d]
            cost_a = max(0.0, dn.pf_busy - t) + pf
            bp = min(ps, key=lambda i: self.pbusy[i])
            nd = self.n_p + d
            s1 = max(t, self.eg[nd].busy, self.ing[bp].busy) + r.H * k / self.eg[nd].bw(t)
            end = max(s1, self.pbusy[bp]) + pf
            cost_b = (end - t) + max(0.0, q * k / bw_nd - p.overlap_ratio * pf)
            if cost_a <= cost_b:
                r.mode = "dlocal"
                st = max(t, dn.pf_busy)
                dn.pf_busy = st + pf
                r.t_pf_start, r.t_pf_end = st, st + pf
                self.push(st, EV_STALL_BEGIN, dn)
                self.push(st + pf, EV_STALL_END, dn, r)
                return
        # DP2 rule (all arms): argmin of queue + prefill + exposed move over prefill nodes
        best, bi = None, -1
        for i in ps:
            wait = max(0.0, self.pbusy[i] - t)
            lw = max(0.0, self.eg[i].busy - t)
            c = wait + pf + max(0.0, lw + q * k / bw_nd - p.overlap_ratio * pf)
            if best is None or c < best:
                best, bi = c, i
        r.p, r.mode = bi, "p"
        start = t
        if r.H > 0:  # stage 1: History KV to the prefill node
            nd = self.n_p + d
            src = self.ing[bi]
            if self.pool_mode:
                _, s1 = self.flow(t, [(self.pool, r.H * k), (src, r.H * k)])
            else:
                _, s1 = self.flow(t, [(self.eg[nd], r.H * k), (src, r.H * k)])
            start = s1
        start = max(start, self.pbusy[bi])
        end = start + pf
        self.pbusy[bi] = end
        r.t_pf_start, r.t_pf_end = start, end
        self.push(start + (1.0 - p.overlap_ratio) * pf, EV_XFER, r)

    def on_xfer(self, t, r):
        p = self.p
        if self.pool_mode:
            if "alloc" in self.sections and not r.alloced:
                r.alloced = True
                self.arm.submit("alloc", t, r, self.nblk(r.L - r.H), EV_ALLOCED)
                return
            if self.evict_needed and not r.evicted:
                r.evicted = True
                self.arm.submit("evict", t, r, self.nblk((r.L - r.H) * self.obj_mult), EV_EVICTED)
                return
        q = r.L - r.H
        st, fin = self.flow(t, self.move_items(r, q))
        if self.pool_mode:
            fin += p.gpu_cxl_write_16KB_us * 1e-6
        fin = max(fin, r.t_pf_end)
        r.t_flow_start, r.t_flow_end = st, fin
        self.push(fin, EV_MOVE_DONE, r)

    def on_move_done(self, t, r):
        if self.pool_mode:
            pub = (r.L - r.H) - (self.p.shared_prefix_tokens if r.hot else 0)
            self.arm.submit("publish", t, r, self.nblk(max(pub, 1) * self.obj_mult), EV_PUBLISHED)
        else:
            self.dn[r.d].join(r, t)

    def on_pinned(self, t, r):
        r.t_cp_done = t
        if self.cp_only:
            r.t_first = t
            self.finish(r, t)
        else:
            self.dn[r.d].join(r, t)
            if "unpin" in self.sections:  # the D read is complete: release the reader pin (refcount--)
                self.arm.submit("unpin", t, r, self.nblk(r.L * self.obj_mult), EV_UNPINNED)

    def on_dec(self, t, dn, ver):
        if ver != dn.ver:
            return
        dn.advance(t)
        done = [e[1] for e in dn.active.values() if e[0] <= 1e-6]
        for r in done:
            del dn.active[r.rid]
        for r in done:
            self.finish(r, t)
        cap = self.p.batch_cap
        while dn.queue and len(dn.active) < cap:
            r = dn.queue.popleft()
            if r.dead:
                continue
            dn.active[r.rid] = [float(r.out), r]
            r.t_admit = t
        dn.reschedule(t)

    def finish(self, r, t):
        r.t_done = t
        self.inflight.pop(r.rid, None)
        if r.d >= 0:
            self.dn[r.d].load -= 1
        if self.cp_only and self.pool_mode and "unpin" in self.sections:
            self.arm.submit("unpin", t, r, self.nblk(r.L * self.obj_mult), EV_UNPINNED)

    def on_crash(self, t, node):
        self.alive[node] = False
        self.fail_info["t_crash"] = t
        for r in list(self.inflight.values()):
            if r.p == node or (r.d >= 0 and self.n_p + r.d == node):
                if r.d >= 0:
                    self.dn[r.d].load -= 1
                self.fail(r, t)
        if node >= self.n_p:
            dn = self.dn[node - self.n_p]
            dn.advance(t)
            dn.active.clear()
            dn.queue.clear()
            dn.ver += 1
            dn.load = 0
        self.arm.node_crash(t, node)
        self.push(t + self.p.node_recovery_s, EV_NODE_RECOVER, node)

    # ------------------------------------------------------------------ metrics
    def residency_gib(self):
        """time-average cluster KV residency (P-side buffer + D HBM + pool) over the window, GiB."""
        p, k, w0, w1 = self.p, self.kvb, self.w0, self.w1
        W = w1 - w0
        total = 0.0
        by_sess = {}
        for r in self.reqs:
            by_sess.setdefault(r.session, []).append(r)
        INF = float("inf")
        sess_mode = self.knobs["turns"] > 1
        comp = dict(p_buffer=0.0, d_hbm=0.0, pool=0.0)
        for rs in by_sess.values():
            rs.sort(key=lambda r: r.turn)
            for i, r in enumerate(rs):
                end = r.t_done if r.t_done is not None else (r.t_dead if r.dead else INF)
                nxt = rs[i + 1] if i + 1 < len(rs) else None
                if r.mode == "p" and r.t_pf_start is not None:
                    fe = r.t_flow_end if r.t_flow_end is not None else (r.t_dead if r.dead else INF)
                    comp["p_buffer"] += clip(r.t_pf_start, fe, w0, w1) * r.L * k
                d0 = r.t_flow_start if r.t_flow_start is not None else (r.t_pf_start if r.mode == "dlocal" else None)
                if d0 is not None and not (r.t_flow_start is None and r.mode != "dlocal"):
                    dend = end
                    if sess_mode and not self.pool_mode and nxt is not None:
                        ns = nxt.t_flow_start if nxt.t_flow_start is not None else nxt.t_pf_start
                        dend = ns if ns is not None else end
                    comp["d_hbm"] += clip(d0, dend, w0, w1) * (r.L + r.out / 2) * k
                if self.pool_mode and r.t_flow_start is not None:
                    pend = r.t_unpin if r.t_unpin is not None else (r.t_dead if r.dead else (r.t_done if "unpin" not in self.sections and r.t_done else INF))
                    if sess_mode and nxt is not None and nxt.t_flow_start is not None:
                        pend = nxt.t_flow_start
                    priv = r.L - (p.shared_prefix_tokens if r.hot else 0)
                    comp["pool"] += clip(r.t_flow_start, pend, w0, w1) * priv * k
        if self.pool_mode and any(r.hot for r in self.reqs):
            comp["pool"] += W * p.shared_prefix_tokens * k  # shared prefix stored once (dedup by prefix hash)
        gib = 1024 ** 3
        return {k_: v / W / gib for k_, v in comp.items()}

    def metrics(self):
        p, w0, w1 = self.p, self.w0, self.w1
        W = w1 - w0
        coh = [r for r in self.reqs if w0 <= r.t < w1]
        ttft, tpot, ok_tok, n_ok = [], [], 0, 0
        n_done = n_dead = n_inc = 0
        for r in coh:
            if r.dead:
                n_dead += 1
            elif r.t_done is None:
                n_inc += 1
            else:
                n_done += 1
            if r.t_done is None or r.dead:
                ttft.append(NEVER_MS)
                tpot.append(NEVER_MS)
                continue
            tf = (r.t_first - r.t) * 1e3
            tp = max(0.0, (r.t_done - r.t_first) / max(1, r.out - 1)) * 1e3
            ttft.append(tf)
            tpot.append(tp)
            if tf <= p.slo_ttft_s * 1e3 and tp <= p.slo_tpot_s * 1e3:
                ok_tok += r.out
                n_ok += 1
        res = self.residency_gib()
        arm_stats = self.arm.stats()
        lat = {}
        for kind, xs in self.arm.lat.items():
            lat[kind] = dict(p50_us=percentile(xs, .5) * 1e6, p99_us=percentile(xs, .99) * 1e6, n=len(xs))
        sched = [i for i in range(self.n_p)]
        out = dict(
            arm=self.arm_name, seed=self.seed, load_scale=self.load, offered_rps=(self.load * self.base if not self.cp_only else len(self.reqs) / self.H), horizon_s=self.H,
            goodput_tps=ok_tok / W, served_tokens=sum(r.out for r in coh if r.t_done is not None and not r.dead),
            n_cohort=len(coh), n_done=n_done, n_incomplete=n_inc, n_failed=n_dead, n_slo_ok=n_ok,
            n_slo_viol=len(coh) - n_ok, n_arrived=len(self.reqs),
            n_total_done=sum(1 for r in self.reqs if r.t_done is not None and not r.dead),
            n_total_failed=sum(1 for r in self.reqs if r.dead),
            n_total_incomplete=sum(1 for r in self.reqs if r.t_done is None and not r.dead),
            ttft_p50_ms=percentile(ttft, .5), ttft_p95_ms=percentile(ttft, .95), ttft_p99_ms=percentile(ttft, .99),
            tpot_p50_ms=percentile(tpot, .5), tpot_p95_ms=percentile(tpot, .95), tpot_p99_ms=percentile(tpot, .99),
            kv_resident_gib=sum(res.values()), resid_gib=res,
            cp_lat=lat,
            link_util_egress=sum(l.acc for l in self.eg[:self.n_p]) / (W * self.n_p),
            link_util_ingress=sum(l.acc for l in self.ing[self.n_p:]) / (W * self.n_d),
            pool_util=(self.pool.acc / W) if self.pool else 0.0,
            fail=self.fail_info, arm_stats=arm_stats,
        )
        out["cpu_core_eq"] = arm_stats.get("cpu_core_eq", 0.0)
        if self.cp_only:
            ch = [(r.t_cp_done - r.t) * 1e6 for r in coh if r.t_cp_done is not None]
            out["cp_chain_p50_us"] = percentile(ch, .5)
            out["cp_chain_p99_us"] = percentile(ch, .99)
        return out


def run_sim(system, p, knobs, arm_name, seed, load, zero_cp=False, cp_only=False, with_fail=True,
            abs_rate=None, n_req=None):
    return Sim(system, p, knobs, arm_name, seed, load, zero_cp, cp_only, with_fail, abs_rate, n_req).run()
