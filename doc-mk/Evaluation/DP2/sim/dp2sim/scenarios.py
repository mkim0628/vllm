"""DP2 scenarios (benchmark.md / sim/configs/scenario_params.json; starting values per m0-spec 5.3)."""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Optional

CFGDIR = Path(__file__).resolve().parent.parent / "configs"


def const(v):
    return lambda rng, i=0: v


def uni(a, b):
    return lambda rng, i=0: rng.randint(a, b)


def choice(vals):
    return lambda rng, i=0: vals[rng.randrange(len(vals))]


def skew_hist(rng, i=0):
    return 262144 if rng.random() < 0.05 else 8192


@dataclass
class Scenario:
    name: str
    set: str
    nP: int
    nD: int
    mode: str                       # closed_clients | closed_sessions | open_sessions
    grid: tuple
    turns: int = 1
    hist0: Optional[Callable] = None
    tool: int = 512
    tool_first: Optional[int] = None
    prompt: Optional[Callable] = None
    out_fn: Callable = field(default=lambda t: 256)
    tier_pin: Optional[str] = None
    hbm_mult: float = 1.0
    bg_decode: int = 0
    link_scale: float = 1.0
    think_median: float = 10.0
    ramp: bool = False
    lam_profile: str = "const"
    occupant_frac: float = 0.0
    degrade: bool = False
    fault: bool = False
    demotion: tuple = ()
    tel: Optional[float] = None
    note: str = ""

    def out(self, t):
        return self.out_fn(t)

    def population(self, load):
        return int(load)

    # open-loop arrival rate profile (sessions/s); lam0 calibrated on the Baseline (A21)
    def lam(self, t, lam0, load):
        base = lam0 * load
        if self.lam_profile == "mmpp":
            return base * (3.0 if (t % 60.0) < 10.0 else 1.0)
        if self.lam_profile == "ramp_burst":
            f = 0.4 + 0.7 * min(1.0, t / 300.0)
            if 150.0 <= t < 160.0:
                f *= 3.0
            return base * f
        return base

    def lam_max(self, lam0, load):
        base = lam0 * load
        return base * {"mmpp": 3.0, "ramp_burst": 3.3}.get(self.lam_profile, 1.0)

    def ext_events(self, o):
        ev = []
        if self.ramp:
            for k in range(1, 40):
                t = 10.0 * k
                ev.append((t, "ext", (lambda sim, tt=t: _ramp(sim, tt, self))))
        if self.degrade:
            ev.append((150.0, "ext", _degrade))
        if self.fault:
            ev.append((150.0, "fault", True))
            ev.append((210.0, "fault", False))
        for (t, tier) in self.demotion:
            ev.append((t, "ext", (lambda sim, tier=tier: _demote_idle(sim, tier, 30.0))))
        return ev


def _ramp(sim, t, sc):
    frac = t / 300.0
    f = max(0.45, 1.0 - 0.55 * frac)
    cap = sim.sysspec.memories["hbm"].capacity_bytes
    for i in range(sim.N):
        sim.kv.pool[(i, "hbm")] = cap * sc.hbm_mult * f


def _degrade(sim):
    nd = sim.nodes[0]
    nd.advance(sim.now)
    nd.speed = 0.5
    sim.node_touch(nd)
    sim.net.advance(sim.now)
    sim.net.set_scale(f"nic_out:0", 0.5)
    sim.net.set_scale(f"nic_in:0", 0.5)
    sim.net_touch()


def _demote_idle(sim, tier, idle_s):
    for s in list(sim.kv.sessions.values()):
        if s.owner and not s.active and (sim.now - s.last_access) >= idle_s and s.owner[1] == "hbm":
            sim.kv.place(s, (s.owner[0], tier), s.kv_bytes)


CLOSED_CB = (8, 12, 16, 20, 24, 32, 48, 64)
OPEN_GRID = (0.5, 0.75, 1.0, 1.25, 1.5, 2.0)


def build():
    S = {}

    def add(sc):
        S[sc.name] = sc
        return sc

    # --- Common (single-turn 8K -> 256, closed loop concurrency)
    cb = dict(nP=4, nD=1, mode="closed_clients", grid=CLOSED_CB, turns=1, prompt=const(8192), set="common")
    add(Scenario("cb_kv_8k_b32", hbm_mult=0.12, **cb))
    add(Scenario("cb_kv_8k_b32_ramp", hbm_mult=0.2, ramp=True, **cb))
    add(Scenario("cb_mixed_8k_b32", hbm_mult=0.12, occupant_frac=0.30, **cb))
    # --- Stress
    st = dict(set="stress", nP=2, nD=2, mode="closed_sessions", turns=8)
    add(Scenario("dp2_turn_hbm_small_tool", grid=(12, 24, 36, 48, 60, 72, 84, 96, 108), hist0=const(32768), tool=512, tier_pin="hbm", hbm_mult=1.0, **st))
    add(Scenario("dp2_turn_dram_small_tool", grid=(6, 12, 18, 24, 36), hist0=const(65536), tool=512, tier_pin="dram", hbm_mult=0.35, bg_decode=16, **st))
    add(Scenario("dp2_turn_hbf_hist", grid=(2, 4, 8, 12, 16, 24), hist0=const(131072), tool=2048, tier_pin="hbf", hbm_mult=0.35, bg_decode=16, **st))
    add(Scenario("dp2_turn_ssd_hist", grid=(1, 2, 3, 4, 6, 8), hist0=const(65536), tool=512, tier_pin="ssd_pim", hbm_mult=0.35, bg_decode=16, **st))
    add(Scenario("dp2_tool_large_result", grid=(4, 8, 12, 16, 24), hist0=const(16384), tool=16384, tier_pin="hbm", hbm_mult=1.0, bg_decode=16, set="stress", nP=2, nD=2, mode="closed_sessions", turns=3))
    add(Scenario("dp2_prefill_burst_p_saturated", set="stress", nP=2, nD=2, mode="open_sessions", grid=OPEN_GRID, turns=1,
                 prompt=choice([8192, 12288, 16384]), lam_profile="mmpp"))
    add(Scenario("dp2_decode_heavy_p_idle", set="stress", nP=2, nD=2, mode="closed_sessions", grid=(32, 48, 64, 96), turns=8,
                 prompt=const(2048), tool=512, out_fn=lambda t: 2048))
    add(Scenario("dp2_long_ctx_decode_offload", set="stress", nP=1, nD=2, mode="closed_sessions", grid=(1, 2, 3, 4, 6, 8), turns=4,
                 hist0=uni(131072, 262144), tool=2048, tier_pin="alloc", hbm_mult=0.3))
    add(Scenario("dp2_session_size_skew", set="stress", nP=2, nD=4, mode="open_sessions", grid=OPEN_GRID, turns=8, hist0=skew_hist, tool=512,
                 hbm_mult=1.0))
    add(Scenario("dp2_internode_link_contention", link_scale=0.25, grid=(2, 4, 6, 9, 12, 18), hist0=const(65536), tool=512, tier_pin="dram",
                 hbm_mult=0.35, bg_decode=16, **st))
    add(Scenario("dp2_stale_telemetry", set="stress", nP=2, nD=2, mode="open_sessions", grid=OPEN_GRID, turns=1,
                 prompt=choice([8192, 12288, 16384]), lam_profile="mmpp", tel=0.5, note="telemetry refresh 0.5 s; sweep in sensitivity"))
    add(Scenario("dp2_planner_fault_fallback", set="stress", nP=2, nD=2, mode="open_sessions", grid=OPEN_GRID, turns=1,
                 prompt=choice([8192, 12288, 16384]), lam_profile="mmpp", fault=True))
    # --- Dynamic
    dy = dict(set="dynamic", nP=2, nD=2)
    add(Scenario("dyn_turn_demotion_wave", mode="closed_sessions", grid=(24,), turns=8, hist0=const(32768), tool=512, tier_pin="hbm",
                 demotion=((100.0, "dram"), (200.0, "cxl_pnm")), think_median=40.0, **dy))
    add(Scenario("dyn_load_ramp_burst", mode="open_sessions", grid=OPEN_GRID, turns=8, hist0=const(32768), tool=512, tier_pin="hbm",
                 lam_profile="ramp_burst", **dy))
    add(Scenario("dyn_p_node_degrade", mode="closed_sessions", grid=(6, 12, 18, 24, 36), turns=8, hist0=const(65536), tool=512, tier_pin="dram",
                 hbm_mult=0.35, bg_decode=16, degrade=True, **dy))
    add(Scenario("dyn_decode_phase_shift", mode="closed_sessions", grid=(32, 48, 64, 96), turns=8, prompt=const(2048), tool=512,
                 out_fn=lambda t: 256 if t < 150.0 else 2048, **dy))
    return S


SCENARIOS = build()
ALL = tuple(SCENARIOS)


def check_against_json():
    d = {x["name"]: x for x in json.loads((CFGDIR / "scenario_params.json").read_text())["scenarios"]}
    assert set(d) == set(SCENARIOS), set(d) ^ set(SCENARIOS)
    for n, sc in SCENARIOS.items():
        j = d[n]
        topo = f"{sc.nP}P+{sc.nD}D"
        assert j["topology"] == topo, (n, j["topology"], topo)
        if "hbm_mult" in j:
            assert abs(j["hbm_mult"] - sc.hbm_mult) < 1e-9, n
        if "tool" in j and isinstance(j["tool"], int):
            assert j["tool"] == sc.tool, (n, j["tool"], sc.tool)
        if "bg_decode" in j:
            assert j["bg_decode"] == sc.bg_decode, n
        if "link_scale" in j:
            assert j["link_scale"] == sc.link_scale, n
    return True
