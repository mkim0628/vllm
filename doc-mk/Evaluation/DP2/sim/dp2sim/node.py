"""Node model: fluid continuous batching (M0 spec 4.2). Decode-first, chunked prefill within a token budget.

Between events the batch composition is constant, so iteration time T is constant and the node evolves linearly
(`advance`). Every composition change goes through the engine, which reschedules the node's next wake-up.
"""
from __future__ import annotations

EPS = 1e-6


class Seq:
    """A decode sequence (one token per iteration)."""
    __slots__ = ("req", "rem", "ctx", "tier", "gpu_s", "bg", "t_join")

    def __init__(self, req, rem, ctx, tier, bg=False):
        self.req, self.rem, self.ctx, self.tier, self.gpu_s, self.bg, self.t_join = req, float(rem), float(ctx), tier, 0.0, bg, 0.0


class PJob:
    """A chunked prefill job."""
    __slots__ = ("req", "rem", "q", "ctx_full", "hist_tier", "hist_tokens", "gpu_s", "t_enq", "t_start", "done")

    def __init__(self, req, q, ctx_full, hist_tier, hist_tokens, t_enq):
        self.req, self.rem, self.q, self.ctx_full = req, float(q), q, ctx_full
        self.hist_tier, self.hist_tokens, self.gpu_s, self.t_enq, self.t_start, self.done = hist_tier, hist_tokens, 0.0, t_enq, None, False


class Node:
    def __init__(self, idx, role, phys):
        self.idx, self.role, self.P = idx, role, phys
        self.dec: list[Seq] = []
        self.pf: list[PJob] = []
        self.t = 0.0
        self.ver = 0
        self.speed = 1.0
        self.busy_all = 0.0
        self.busy_win = 0.0
        self.win = (0.0, float("inf"))
        self.useful_gpu_s = 0.0          # filled post-run from per-request gpu_s

    # -- composition -------------------------------------------------------------------------------------------
    def outstanding_prefill_tokens(self):
        return sum(j.rem for j in self.pf)

    def groups(self):
        g = {}
        for q in self.dec:
            c, s = g.get(q.tier, (0, 0.0))
            g[q.tier] = (c + 1, s + q.ctx)
        return g

    def alloc(self):
        left = max(0, self.P.budget - len(self.dec))
        out = []
        for j in self.pf:
            if left <= 0:
                break
            c = min(self.P.chunk, j.rem, left)
            if c > 0:
                out.append((j, c))
                left -= c
        return out

    def iter_and_alloc(self):
        al = self.alloc()
        pf = [(c, j.ctx_full, j.hist_tier, j.hist_tokens) for j, c in al]
        T = self.P.iter_time(self.groups(), pf) / self.speed
        return T, al

    def predict_dt(self, cap=1.0):
        """Time to the next internal event (a completion) or `cap` seconds."""
        if not self.dec and not self.pf:
            return None
        T, al = self.iter_and_alloc()
        dt = cap
        for q in self.dec:
            dt = min(dt, q.rem * T)
        for j, c in al:
            dt = min(dt, j.rem / c * T)
        return max(dt, 1e-9)           # rem <= EPS entries are popped by the wake-up at this time

    def advance(self, now):
        """Advance to `now` (never crosses a completion: the engine wakes the node at the next completion time)."""
        while self.t < now - 1e-12:
            if not self.dec and not self.pf:
                self.t = now
                return
            T, al = self.iter_and_alloc()
            dt = min(now - self.t, 1.0)
            for q in self.dec:
                if q.rem > EPS:
                    dt = min(dt, q.rem * T)
            for j, c in al:
                if j.rem > EPS:
                    dt = min(dt, j.rem / c * T)
            dt = max(dt, 1e-9)
            iters = dt / T
            ntok = len(self.dec) + sum(c for _, c in al)
            for q in self.dec:
                q.rem = max(0.0, q.rem - iters)
                q.ctx += iters
                q.gpu_s += dt / ntok
            for j, c in al:
                if j.t_start is None:
                    j.t_start = self.t
                j.rem = max(0.0, j.rem - iters * c)
                j.gpu_s += dt * c / ntok
            t0, t1 = self.t, self.t + dt
            self.busy_all += dt
            lo, hi = self.win
            self.busy_win += max(0.0, min(t1, hi) - max(t0, lo))
            self.t = t1

    def pop_completed(self):
        pdone = [j for j in self.pf if j.rem <= EPS]
        if pdone:
            self.pf = [j for j in self.pf if j.rem > EPS]
        ddone = [q for q in self.dec if q.rem <= EPS]
        if ddone:
            self.dec = [q for q in self.dec if q.rem > EPS]
        return pdone, ddone
