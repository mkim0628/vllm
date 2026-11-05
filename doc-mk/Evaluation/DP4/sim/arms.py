"""The three arms. Data plane is shared (simulator.py); an arm only provides the control plane.

  Baseline-RDMA             no pool; central index lookup (fixed latency); no metadata critical sections
  C1-central-serialization  FIFO metadata server with T threads reached through CXL-RPC
  C2-distributed-lock       lock-free lookup; pin/publish/unpin under two-tier locks + lock-manager scan

Ablation variants (SKILL section 9): C1-no-batch (one block hash per RPC), C2-no-scan (lock granted
without the manager scan period; direct hand-off).
"""
from __future__ import annotations

import math
from collections import deque

LOCK_POSTED, LOCK_GRANT, LOCK_RELEASE, LOCK_FORCE = 100, 101, 102, 103
LOCK_KINDS = (LOCK_POSTED, LOCK_GRANT, LOCK_RELEASE, LOCK_FORCE)
U_INDEX = {"publish": 0, "pin": 1, "unpin": 2, "evict": 3, "alloc": 4, "lru": 5}
BASE, C1, C2 = "Baseline-RDMA", "C1-central-serialization", "C2-distributed-lock"
C1_NOBATCH, C2_NOSCAN = "C1-no-batch", "C2-no-scan"
ARM_NAMES = (BASE, C1, C2)
ABLATION_NAMES = (C1_NOBATCH, C2_NOSCAN)


def clip(a, b, w0, w1):
    return max(0.0, min(b, w1) - max(a, w0))


class Arm:
    name = "arm"
    uses_pool = False

    def __init__(self, sim, p, knobs, zero_cp=False):
        self.sim, self.p, self.knobs, self.zero_cp = sim, p, knobs, zero_cp
        self.lat = {}  # kind -> [seconds] for ops submitted inside the measurement window

    # --- API used by the simulator
    def op_sequence(self):
        """control-plane sections on a pooled request: (critical-path-before-move, critical path after move, after decode)"""
        return ()

    def submit(self, kind, t, req, nblocks, then):
        if self.zero_cp:
            self.sim.push(t, then, req)
            return
        self._submit(kind, t, req, nblocks, then)

    def _rec(self, kind, t, done):
        if self.sim.w0 <= t < self.sim.w1:
            self.lat.setdefault(kind, []).append(done - t)

    def on_event(self, kind, t, a, b):
        pass

    def node_crash(self, t, node):
        pass

    def server_down(self, t0, t1):
        pass

    def stats(self):
        return {}

    def _submit(self, kind, t, req, nblocks, then):
        raise NotImplementedError


class BaselineRDMA(Arm):
    name = BASE
    uses_pool = False

    def _submit(self, kind, t, req, nblocks, then):
        done = t + (self.p.index_lookup_us * 1e-6 if kind == "lookup" else 0.0)
        self._rec(kind, t, done)
        self.sim.push(done, then, req)

    def stats(self):
        return dict(cpu_core_eq=0.0, server_util=0.0)


class C1Central(Arm):
    name = C1
    uses_pool = True

    def __init__(self, sim, p, knobs, zero_cp=False, batch=None):
        super().__init__(sim, p, knobs, zero_cp)
        self.T = int(p.server_threads)
        self.svc = p.server_service_s
        self.transport = max(0.0, p.rpc_rtt_us * 1e-6 - self.svc)  # RTT floor minus server service
        self.batch = int(batch or p.rpc_hash_batch)
        self.busy = [0.0] * self.T
        self.down = []
        self.busy_acc = 0.0
        self.n_rpc = 0

    def op_sequence(self):
        return ("lookup", "publish", "pin", "unpin")

    def server_down(self, t0, t1):
        self.down.append((t0, t1))

    def _after_down(self, s):
        for a, b in self.down:
            if a <= s < b or s < a < s + self.svc:
                s = b
        return s

    def _submit(self, kind, t, req, nblocks, then):
        k = max(1, math.ceil(nblocks / self.batch))
        ta = t + self.transport / 2
        busy, svc, T = self.busy, self.svc, self.T
        last = ta
        w0, w1 = self.sim.w0, self.sim.w1
        for _ in range(k):
            idx = 0
            if T > 1:
                idx = min(range(T), key=busy.__getitem__)
            s = ta if ta > busy[idx] else busy[idx]
            if self.down:
                s = self._after_down(s)
            busy[idx] = s + svc
            self.busy_acc += clip(s, s + svc, w0, w1)
            last = busy[idx]
        self.n_rpc += k
        done = last + self.transport / 2
        self._rec(kind, t, done)
        self.sim.push(done, then, req)

    def stats(self):
        W = self.sim.w1 - self.sim.w0
        return dict(server_util=self.busy_acc / (self.T * W), cpu_core_eq=float(self.T),
                    server_busy_core_eq=self.busy_acc / W, rpc_count=self.n_rpc)


class C1NoBatch(C1Central):
    name = C1_NOBATCH

    def __init__(self, sim, p, knobs, zero_cp=False):
        super().__init__(sim, p, knobs, zero_cp, batch=1)


class _Ent:
    __slots__ = ("node", "req", "kind", "hold", "then", "t_submit", "t_post", "t_grant")

    def __init__(self, node, req, kind, hold, then, t_submit, t_post):
        self.node, self.req, self.kind, self.hold, self.then = node, req, kind, hold, then
        self.t_submit, self.t_post, self.t_grant = t_submit, t_post, None


class C2DistLock(Arm):
    name = C2
    uses_pool = True
    scan = True

    def __init__(self, sim, p, knobs, zero_cp=False):
        super().__init__(sim, p, knobs, zero_cp)
        self.S = int(p.lock_stripes)
        self.N = sim.N
        self.tp = p.probe_us * 1e-6
        self.period = self.S * self.N * self.tp
        self.rd = p.meta_read_us * 1e-6
        self.wf = p.meta_write_flush_us * 1e-6
        self.loc = p.local_lock_us * 1e-6
        self.queue = [deque() for _ in range(self.S)]
        self.holder = [None] * self.S
        self.pending = [False] * self.S
        self.gver = [0] * self.S
        self.rver = [0] * self.S
        self.hold_acc = [0.0] * self.S
        self.stuck = set()
        self.cpu = 0.0
        self.waits = []
        self.n_grants = 0
        self.mgr_busy_acc = 0.0
        self.lease = knobs.get("lease")
        self.crash_armed = False
        self.crash_node = None
        self.crash_t = None

    def op_sequence(self):
        return {2: ("lookup", "publish", "pin"), 3: ("lookup", "publish", "pin", "unpin"),
                5: ("lookup", "alloc", "publish", "pin", "unpin", "lru")}[int(self.p.cs_per_request)]

    def arm_crash(self, node, t):
        self.crash_armed, self.crash_node, self.crash_t = True, node, t

    def stripe_of(self, kind, req):
        if req.hot and kind in ("pin", "unpin"):
            return 0
        return min(self.S - 1, int(req.u[U_INDEX[kind]] * self.S))

    def _submit(self, kind, t, req, nblocks, then):
        if kind == "lookup":
            dur = nblocks * self.p.lookup_probe_mult * self.rd  # lock-free bucket probes, sequential
            self.cpu += dur
            done = t + dur
            self._rec(kind, t, done)
            self.sim.push(done, then, req)
            return
        node = req.p if kind in ("publish", "evict", "alloc") else self.sim.n_p + req.d
        lines = max(1, math.ceil(nblocks / self.p.meta_entries_per_line))
        hold = lines * (self.rd + self.wf)
        s = self.stripe_of(kind, req)
        t_post = t + self.loc + self.wf  # node-local lock, then WAITING slot write + flush
        ent = _Ent(node, req, kind, hold, then, t, t_post)
        self.sim.push(t_post, LOCK_POSTED, s, ent)

    def _next_probe(self, s, n, t):
        if not self.scan:
            return t
        ph = (s * self.N + n) * self.tp
        if t <= ph:
            return ph
        return ph + math.ceil((t - ph) / self.period) * self.period

    def _try(self, s, t):
        q = self.queue[s]
        while q and q[0].req.dead:
            q.popleft()
        if self.holder[s] is None and q and not self.pending[s]:
            head = q[0]
            g = self._next_probe(s, head.node, t)
            self.pending[s] = True
            self.gver[s] += 1
            self.sim.push(g, LOCK_GRANT, s, (head, self.gver[s]))

    def on_event(self, kind, t, a, b):
        s = a
        if kind == LOCK_POSTED:
            ent = b
            if ent.req.dead or not self.sim.alive[ent.node]:
                return
            self.queue[s].append(ent)
            self._try(s, t)
        elif kind == LOCK_GRANT:
            ent, v = b
            if v != self.gver[s]:
                return
            self.pending[s] = False
            q = self.queue[s]
            if not q or q[0] is not ent or ent.req.dead:
                self._try(s, t)
                return
            q.popleft()
            self.holder[s] = ent
            ent.t_grant = t
            self.n_grants += 1
            if self.sim.w0 <= t < self.sim.w1:
                self.waits.append(t - ent.t_post)
            begin = t + self.wf + self.rd  # grant write + client poll read
            rel = begin + ent.hold + self.wf
            self.rver[s] += 1
            self.sim.push(rel, LOCK_RELEASE, s, (ent, self.rver[s]))
            if self.crash_armed and ent.node == self.crash_node and t >= self.crash_t:
                self.crash_armed = False
                self.sim.push(begin + ent.hold / 2, self.sim.EV_NODE_CRASH, ent.node, "lockholder")
        elif kind == LOCK_RELEASE:
            ent, v = b
            if v != self.rver[s] or self.holder[s] is not ent:
                return
            self.holder[s] = None
            w0, w1 = self.sim.w0, self.sim.w1
            self.hold_acc[s] += clip(ent.t_grant, t, w0, w1)
            self.cpu += ent.hold + self.loc + self.wf
            self._rec(ent.kind, ent.t_submit, t)
            self.sim.push(t, ent.then, ent.req)
            self._try(s, t)
        elif kind == LOCK_FORCE:
            if self.holder[s] is not None and b == self.rver[s]:
                self.stuck.discard(s)
                ent = self.holder[s]
                self.hold_acc[s] += clip(ent.t_grant, t, self.sim.w0, self.sim.w1)
                self.holder[s] = None
                self._try(s, t)

    def node_crash(self, t, node):
        for s in range(self.S):
            q = self.queue[s]
            if any(e.node == node for e in q):
                self.queue[s] = deque(e for e in q if e.node != node)
            h = self.holder[s]
            if h is not None and h.node == node and s not in self.stuck:
                self.rver[s] += 1  # cancel the pending release: the holder is gone
                if self.lease is None:
                    self.stuck.add(s)  # as-published: never released
                else:
                    self.sim.push(t + self.lease, LOCK_FORCE, s, self.rver[s])
            if self.holder[s] is None:
                self._try(s, t)

    def stats(self):
        W = self.sim.w1 - self.sim.w0
        w1 = self.sim.w1
        hold = list(self.hold_acc)
        for s in self.stuck:  # never released: held until the end of the window
            h = self.holder[s]
            hold[s] += clip(h.t_grant, w1, self.sim.w0, w1)
        occ = [h / W for h in hold]
        w = sorted(self.waits)
        return dict(
            cpu_core_eq=1.0 + self.cpu / W, lock_scan_period_us=self.period * 1e6 if self.scan else 0.0,
            global_lock_util_mean=sum(occ) / self.S, global_lock_util_max=max(occ),
            lock_wait_mean_ms=1e3 * sum(w) / len(w) if w else 0.0,
            lock_wait_p99_ms=1e3 * w[min(len(w) - 1, int(0.99 * len(w)))] if w else 0.0,
            n_grants=self.n_grants, stuck_stripes=len(self.stuck), server_util=0.0,
            lock_mgr_util=min(1.0, self.n_grants * self.tp / W) if self.scan else 0.0)


class C2NoScan(C2DistLock):
    name = C2_NOSCAN
    scan = False


ARM_CLASSES = {BASE: BaselineRDMA, C1: C1Central, C2: C2DistLock, C1_NOBATCH: C1NoBatch, C2_NOSCAN: C2NoScan}
