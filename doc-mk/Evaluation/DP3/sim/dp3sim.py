"""DP3 request-level simulator: long-context KV compression + reuse (offline C1 vs online C2 vs As-Is baseline).

Evidence: [B+C]. Hardware numbers come from DP1/sim/configs (SYS-H100 / SYS-B200, Llama-3.1-70B BF16, 8-GPU node, TP8 modelled as one
aggregate device exactly like DP1). Nothing here is a measurement of a real compression system.

Model in one paragraph
  Requests reuse a pool of *Context KV* objects (documents / agent histories) of L tokens that sit in a fixed tier (external placement,
  identical for all policies; DP1 decides placement). A request needs (1) HBM space, (2) the KV in HBM (link load if it sits in a colder
  tier), (3) a GPU "prefill job" (query prefill + policy extras), then (4) decode iterations shared by all active requests.
  GPU is one timeline: queued prefill jobs run first (vLLM-like), otherwise one decode iteration for all active requests.
  Policies:
    baseline  As-Is: reuse the full Context KV (load L tokens, attend over L).
    offline   C1: Comp.KV prepared offline (keep ratio r, shared by requests); load r*L, attend over r*L, selective recompute rho*r*L tokens.
    online    C2: full KV is loaded, query x KV attention scores it on the GPU, then keep r*L tokens + selective recompute rho*r*L tokens;
              the request keeps a compressed working copy (r*L) after scoring.
  Accuracy is NOT simulated here (see accuracy.py).
"""
from __future__ import annotations

import heapq
import math
import random
import sys
from collections import deque
from dataclasses import dataclass, field
from pathlib import Path

HERE = Path(__file__).resolve().parent
DP1_SIM = HERE.parents[1] / "DP1" / "sim"
sys.path.insert(0, str(DP1_SIM))
import model as M  # noqa: E402  (DP1 hardware model, single source of truth for SYS profiles)

CONFIG_DIR = DP1_SIM / "configs"
GIB = 1024 ** 3
SLO_TTFT_S, SLO_TPOT_S = 2.0, 0.050
HBM_USABLE = 0.90      # share of HBM capacity usable (rest = activations, fragmentation) -- ASSUMED, same as DP4 note
TIER_ORDER = ("hbm", "dram", "cxl_pnm", "hbf", "ssd_pim")


@dataclass(frozen=True)
class Policy:
    name: str               # baseline | C1 | C2
    mode: str               # full | offline | online
    r: float = 1.0          # keep ratio of context tokens
    rho: float = 0.0        # selective recompute fraction of the kept tokens


BASELINE = Policy("Baseline-As-Is", "full")
C1 = Policy("C1-Offline", "offline", r=0.30, rho=0.15)
C2 = Policy("C2-Online", "online", r=0.30, rho=0.15)


@dataclass(frozen=True)
class Scenario:
    sid: str
    brief: str
    family: str                           # common | stress | dynamic
    ctx_tokens: int
    query_tokens: int = 256
    out_tokens: int = 256
    n_ctx: int = 40                       # size of the reusable context pool
    zipf: float = 0.8                     # popularity skew over the pool
    tier_frac: tuple = (("hbm", 0.10), ("dram", 0.90))     # placement by popularity rank (fractions sum to 1)
    shift_frac: tuple | None = None       # placement after t = horizon/2 (hot set moves), same format
    kv_frac: float = 1.0                  # share of the HBM budget available to context KV (pressure knob)
    ramp: bool = False                    # kv_frac shrinks 1.0 -> 0.55 across the horizon (DP1 capacity_ramp analogue)
    burst: bool = False                   # arrival rate x2.5 in the middle third
    mismatch: float = 0.3                 # distance between representative and actual queries (accuracy model only)
    ctx_mix: tuple | None = None          # ((tokens, prob), ...) overrides ctx_tokens
    horizon_s: float = 90.0


@dataclass
class RunResult:
    ttft: list = field(default_factory=list)
    tpot: list = field(default_factory=list)
    hbm_gib: float = 0.0
    done: int = 0
    arrived: int = 0
    unfinished: int = 0
    wait_s: float = 0.0
    good_tokens: float = 0.0     # output tokens of requests that met TTFT <= SLO_TTFT_S and TPOT <= SLO_TPOT_S (measured window)
    window_s: float = 1.0


def hbm_budget(system, sc: Scenario, t: float, horizon: float) -> float:
    cap = system.memories["hbm"].capacity_bytes * HBM_USABLE
    weights = system.model.active_params * system.model.dtype_bytes
    frac = sc.kv_frac
    if sc.ramp:
        frac *= max(0.55, 1.0 - 0.45 * t / horizon)
    return max(0.0, (cap - weights) * frac)


def _placement(sc: Scenario, rng: random.Random, frac: tuple) -> list[str]:
    tiers = []
    for tier, f in frac:
        tiers += [tier] * int(round(f * sc.n_ctx))
    while len(tiers) < sc.n_ctx:
        tiers.append(frac[-1][0])
    return tiers[: sc.n_ctx]


def object_tokens(pol: Policy, L: int, stored: bool) -> float:
    """Tokens of KV that live in a tier for a context of L tokens ('stored' = at rest)."""
    if pol.mode == "offline":
        return pol.r * L
    return float(L)          # baseline and online keep the full KV at rest


def run(sc: Scenario, system, pol: Policy, seed: int, rate_rps: float) -> RunResult:
    rng = random.Random(seed * 1_000_003 + hash(sc.sid) % 9973)
    kvb = system.model.kv_bytes_per_token
    H = sc.horizon_s
    warm = 0.1 * H
    place0 = _placement(sc, rng, sc.tier_frac)
    place1 = _placement(sc, rng, sc.shift_frac) if sc.shift_frac else place0
    w = [1.0 / (i + 1) ** sc.zipf for i in range(sc.n_ctx)]
    # arrivals
    reqs, t = [], 0.0
    while True:
        lam = rate_rps * (2.5 if (sc.burst and H / 3 <= t < 2 * H / 3) else 1.0)
        t += rng.expovariate(max(1e-9, lam))
        if t >= H:
            break
        c = rng.choices(range(sc.n_ctx), weights=w)[0]
        if sc.ctx_mix:
            L = rng.choices([x[0] for x in sc.ctx_mix], weights=[x[1] for x in sc.ctx_mix])[0]
        else:
            L = sc.ctx_tokens
        tier = (place1 if (sc.shift_frac and t >= H / 2) else place0)[c]
        reqs.append(dict(a=t, c=c, L=L, tier=tier, Q=sc.query_tokens, O=sc.out_tokens))
    res = RunResult(arrived=len(reqs))
    # resident (hot) set in HBM: fixed contexts, same for every policy
    resident_tok = sum(object_tokens(pol, sc.ctx_tokens if not sc.ctx_mix else sc.ctx_mix[0][0], True) for c in range(sc.n_ctx) if place0[c] == "hbm")
    resident = resident_tok * kvb

    def need_bytes(r):                       # reservation at admission
        if r["tier"] == "hbm":
            return 0.0                       # served in place from the resident copy
        return (pol.r * r["L"] if pol.mode == "offline" else r["L"]) * kvb

    def work_tokens(r):                      # tokens the decode attends to
        return pol.r * r["L"] if pol.mode != "full" else r["L"]

    def load_s(r):
        if r["tier"] == "hbm":
            return 0.0
        mem = system.memories[r["tier"]]
        tok = pol.r * r["L"] if pol.mode == "offline" else r["L"]
        return tok * kvb / mem.ext_bw + mem.latency_s

    def gpu_job_s(r):
        L, Q = r["L"], r["Q"]
        if pol.mode == "full":
            return system.prefill_s(L, Q)
        kept = pol.r * L
        rec = pol.rho * kept
        extra = system.prefill_s(int(kept), int(rec)) if rec > 0 else 0.0
        job = system.prefill_s(int(kept), Q) + extra
        if pol.mode == "online":              # query x full-KV attention scoring (read L tokens of KV from HBM once)
            bytes_ = L * kvb
            flops = system.model.attention_flops(L, Q)
            job += max(bytes_ / (system.gpu_hbm_bw * system.gpu_bw_eff), flops / (system.gpu_compute_flops * system.gpu_compute_eff))
        return job

    arr_i, n = 0, len(reqs)
    adm = deque()
    pend = []                                # (ready_time, idx)
    pf = deque()
    active = []                              # dict(idx, left, t_first)
    link_free = {k: 0.0 for k in TIER_ORDER}
    reserved = 0.0
    mem_integral, last_t = 0.0, 0.0
    now = 0.0
    horizon_drain = 4.0 * H
    kv_total = lambda: resident + reserved

    def integrate(t0, t1):
        nonlocal mem_integral
        lo, hi = max(t0, warm), min(t1, H)
        if hi > lo:
            mem_integral += (kv_total()) * (hi - lo)

    def try_admit(tnow):
        nonlocal reserved
        while adm:
            i = adm[0]
            r = reqs[i]
            budget = hbm_budget(system, sc, tnow, H) - resident
            nb = need_bytes(r)
            if nb > max(0.0, budget - reserved):
                r["fresh"] = False           # had to wait: admission time = now, not its arrival time
                break
            adm.popleft()
            reserved += nb
            t_adm = r["a"] if r.get("fresh") else tnow
            if r["tier"] == "hbm":
                r["ready"] = t_adm
            else:
                st = max(t_adm, link_free[r["tier"]])
                link_free[r["tier"]] = st + load_s(r)
                r["ready"] = link_free[r["tier"]]
            heapq.heappush(pend, (r["ready"], i))

    while True:
        # arrivals up to now
        while arr_i < n and reqs[arr_i]["a"] <= now:
            reqs[arr_i]["fresh"] = not adm
            adm.append(arr_i)
            arr_i += 1
        try_admit(now)
        while pend and pend[0][0] <= now:
            _, i = heapq.heappop(pend)
            pf.append(i)
        if now > horizon_drain:
            break
        if pf:
            i = pf.popleft()
            r = reqs[i]
            dur = gpu_job_s(r)
            integrate(now, now + dur)
            now += dur
            r["t_first"] = now
            if pol.mode == "online" and r["tier"] != "hbm":
                reserved -= (1 - pol.r) * r["L"] * kvb      # full copy shrinks to the compressed working copy
            if r["O"] > 1:
                active.append(dict(i=i, left=r["O"] - 1))
            else:
                reserved -= (pol.r * r["L"] if pol.mode != "full" else r["L"]) * kvb if r["tier"] != "hbm" else 0.0
                r["t_done"] = now
            continue
        if active:
            B = len(active)
            toks = sum(work_tokens(reqs[a["i"]]) for a in active)
            attn = max(toks * kvb / (system.gpu_hbm_bw * system.gpu_bw_eff),
                       system.model.attention_flops(int(toks), 1) / (system.gpu_compute_flops * system.gpu_compute_eff))
            dur = system.gpu_non_attention_decode_s(B) + attn
            integrate(now, now + dur)
            now += dur
            keep = []
            for a in active:
                a["left"] -= 1
                if a["left"] <= 0:
                    r = reqs[a["i"]]
                    r["t_done"] = now
                    if r["tier"] != "hbm":
                        reserved -= (pol.r * r["L"] if pol.mode != "full" else r["L"]) * kvb
                else:
                    keep.append(a)
            active = keep
            continue
        # idle: jump to next event
        nxt = []
        if arr_i < n:
            nxt.append(reqs[arr_i]["a"])
        if pend:
            nxt.append(pend[0][0])
        if not nxt:
            break                            # nothing left to do (a request that can never be admitted stays unfinished)
        integrate(now, min(nxt))
        now = max(now, min(nxt))

    ok_t, ok_p = [], []
    for r in reqs:
        if r["a"] < warm:
            continue
        if "t_first" in r:
            ok_t.append(r["t_first"] - r["a"])
            if "t_done" in r and r["O"] > 1:
                ok_p.append((r["t_done"] - r["t_first"]) / (r["O"] - 1))
            else:
                res.unfinished += 1
                ok_p.append(float("inf"))
        else:
            res.unfinished += 1
            ok_t.append(float("inf"))
            ok_p.append(float("inf"))
    res.ttft, res.tpot = ok_t, ok_p
    for r in reqs:
        if r["a"] >= warm and "t_done" in r and r["O"] > 1 and (r["t_first"] - r["a"]) <= SLO_TTFT_S and (r["t_done"] - r["t_first"]) / (r["O"] - 1) <= SLO_TPOT_S:
            res.good_tokens += r["O"]
    res.window_s = max(1e-9, H - warm)
    res.done = len(ok_t) - res.unfinished
    res.hbm_gib = mem_integral / max(1e-9, (H - warm)) / GIB
    return res


def pct(xs, q):
    xs = sorted(xs)
    if not xs:
        return float("nan")
    k = min(len(xs) - 1, max(0, int(math.ceil(q * len(xs))) - 1))
    return xs[k]


def summarize(res: RunResult) -> dict:
    return dict(ttft_p50=pct(res.ttft, .5), ttft_p99=pct(res.ttft, .99), tpot_p50=pct(res.tpot, .5), tpot_p99=pct(res.tpot, .99),
                hbm_gib=res.hbm_gib, n=res.arrived, unfinished=res.unfinished, goodput_tps=res.good_tokens / res.window_s)


def load_system(sys_id: str):
    s, pid, prof = M.load_profile(CONFIG_DIR, sys_id)
    return s
