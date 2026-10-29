"""Flow network with max-min fair sharing (M0 spec 4.4)."""
from __future__ import annotations


class Flow:
    __slots__ = ("fid", "rem", "res", "cb", "rate", "tag", "bytes")

    def __init__(self, fid, nbytes, res, cb, tag):
        self.fid, self.rem, self.res, self.cb, self.rate, self.tag, self.bytes = fid, float(nbytes), tuple(res), cb, 0.0, tag, float(nbytes)


class FlowNet:
    def __init__(self, caps):
        self.caps = dict(caps)
        self.scale = {}
        self.flows = {}
        self.t = 0.0
        self._n = 0
        self.bytes_by_class = {}
        self.res_busy_s = {}     # resource -> integral of utilization (for link utilization diagnostics)

    def cap(self, r):
        return self.caps[r] * self.scale.get(r, 1.0)

    def set_scale(self, r, k):
        self.scale[r] = k

    def advance(self, now):
        dt = now - self.t
        if dt > 0 and self.flows:
            used = {}
            for f in self.flows.values():
                f.rem -= f.rate * dt
                for r in f.res:
                    used[r] = used.get(r, 0.0) + f.rate
            for r, u in used.items():
                self.res_busy_s[r] = self.res_busy_s.get(r, 0.0) + dt * min(1.0, u / max(1.0, self.cap(r)))
        self.t = now

    def add(self, nbytes, res, cb, tag="x"):
        self._n += 1
        f = Flow(self._n, nbytes, res, cb, tag)
        self.flows[f.fid] = f
        self.bytes_by_class[tag] = self.bytes_by_class.get(tag, 0.0) + f.bytes
        return f

    def pop_done(self, eps=1.0):
        done = [f for f in self.flows.values() if f.rem <= eps]
        for f in done:
            del self.flows[f.fid]
        return done

    def recompute(self):
        un = list(self.flows.values())
        if not un:
            return
        capleft = {}
        for f in un:
            for r in f.res:
                if r not in capleft:
                    capleft[r] = self.cap(r)
        while un:
            cnt = {}
            for f in un:
                for r in f.res:
                    cnt[r] = cnt.get(r, 0) + 1
            rmin, share = None, float("inf")
            for r, n in cnt.items():
                s = capleft[r] / n
                if s < share:
                    rmin, share = r, s
            fr = [f for f in un if rmin in f.res]
            for f in fr:
                f.rate = max(1.0, share)
                for r in f.res:
                    capleft[r] = max(0.0, capleft[r] - share)
            un = [f for f in un if rmin not in f.res]

    def next_completion(self):
        best = None
        for f in self.flows.values():
            if f.rate > 0:
                t = self.t + f.rem / f.rate
                if best is None or t < best:
                    best = t
        return best
