"""KV capacity accounting, external allocator and capacity-fit demotion (M0 spec 4.6)."""
from __future__ import annotations

from .physics import ALLOC_ORDER, target


class Session:
    __slots__ = ("sid", "owner", "kv_bytes", "last_access", "active", "turns_left", "hist_tokens", "idx", "pinned", "p_cache",
                 "p_cache_node", "params")

    def __init__(self, sid, idx):
        self.sid, self.idx = sid, idx
        self.owner = None            # (node, tier) where the KV owner copy lives
        self.kv_bytes = 0.0
        self.last_access = 0.0
        self.active = False
        self.turns_left = 0
        self.hist_tokens = 0
        self.pinned = False
        self.p_cache = 0             # tokens retained at a P node (P-retain reference only)
        self.p_cache_node = None
        self.params = None


class KVStore:
    def __init__(self, nodes, caps, hbm_mult):
        """caps: {tier: capacity_bytes per node}. HBM pool = capacity x hbm_mult (A08, weights excluded)."""
        self.pool = {}
        self.occ = {}
        self.resv = {}
        for n in nodes:
            for t, c in caps.items():
                self.pool[(n, t)] = c * (hbm_mult if t == "hbm" else 1.0)
                self.occ[(n, t)] = 0.0
                self.resv[(n, t)] = 0.0
        self.sessions = {}

    def free(self, node, tier):
        k = (node, tier)
        return target(tier) * self.pool[k] - self.occ[k] - self.resv[k]

    def place(self, sess, loc, nbytes):
        """Set session owner location/size (moves occupancy)."""
        if sess.owner is not None:
            self.occ[sess.owner] -= sess.kv_bytes
        sess.owner, sess.kv_bytes = loc, nbytes
        if loc is not None:
            self.occ[loc] += nbytes

    def allocate(self, nodes, nbytes, exclude_tiers=()):
        """DP1 external allocator order over the given nodes (least-occupied node first within a tier)."""
        for tier in ALLOC_ORDER:
            if tier in exclude_tiers:
                continue
            best = None
            for n in nodes:
                if self.free(n, tier) >= nbytes:
                    if best is None or self.occ[(n, tier)] < self.occ[(best, tier)]:
                        best = n
            if best is not None:
                return (best, tier)
        return None

    def victims(self, node, need, exclude_sid):
        """LRU idle sessions with owner copy in (node, hbm) that free at least `need` bytes."""
        cand = [s for s in self.sessions.values() if s.owner == (node, "hbm") and not s.active and s.sid != exclude_sid and not s.pinned]
        cand.sort(key=lambda s: s.last_access)
        out, got = [], 0.0
        for s in cand:
            out.append(s)
            got += s.kv_bytes
            if got >= need:
                return out
        return None

    def demote_dst(self, node, nbytes, avoid=("hbm",)):
        for tier in ALLOC_ORDER:
            if tier in avoid:
                continue
            if self.free(node, tier) >= nbytes:
                return tier
        return None
