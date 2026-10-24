#!/usr/bin/env python3
"""Smoke criteria for the QA4 change scenarios (qa4-preregistration-arch.md 1). Run against a working copy:
    python qa4_smoke_arch.py --tree <copy>/DP2/sim --scenario S1|S2|S3|S4|BASE --cand A|B     -> JSON on stdout
Fixture ("squeeze"): n_cb_kv_8k_b32, SYS-H100, seed 11, concurrency 8, HBM KV pool x0.001 so that every request must use an
attention-capable offload tier; for S1 the ScHBM capacity is additionally squeezed to 1 B (as in the DP2 QA4 measurement)."""
import argparse
import json
import sys
from collections import Counter

ap = argparse.ArgumentParser()
ap.add_argument("--tree", required=True)
ap.add_argument("--scenario", required=True)
ap.add_argument("--cand", required=True)
a = ap.parse_args()
sys.path.insert(0, a.tree)
from dp2sim.nodeint import N_BASE, N_BBRD, N_DISP, NodeSim  # noqa: E402
from dp2sim.scenarios_node import NODE_SCENARIOS  # noqa: E402

SHORT = dict(horizon=120.0, warmup=10.0, min_turns=100, max_horizon=200.0)
CAND = N_DISP if a.cand == "A" else N_BBRD
SC = NODE_SCENARIOS["n_cb_kv_8k_b32"]


def fixture(cand, squeeze_schbm=False, hook=None, **o):
    sim = NodeSim("SYS-H100", SC, 11, cand, 8.0, dict(SHORT, hbm_mult=0.001, **o))
    if squeeze_schbm:       # ScHBM and CXL-PNM capacity 1 B: a new CXL-PNM-class tier is the only attention-capable offload tier left
        for i in range(sim.N):
            sim.kv.pool[(i, "custom_hbm")] = 1.0
            sim.kv.pool[(i, "cxl_pnm")] = 1.0
    log = []
    orig = sim.commit

    def commit(req, plan, t_dec, _o=orig):
        ok = _o(req, plan, t_dec)
        if ok:
            log.append((sim.now, plan.n_d[1]))
        return ok

    sim.commit = commit
    if hook:
        hook(sim)
    r = sim.run()
    return sim, r, log


def dist(r):
    return {k: v for k, v in sorted(r["arch"]["tiers"].items()) if v}


out = {"scenario": a.scenario, "cand": a.cand}
b = NodeSim("SYS-H100", SC, 11, N_BASE, 4.0, SHORT).run()
out["base_check"] = dict(goodput=b["qa"]["goodput_tok_s"], ttft99=b["qa"]["ttft_p99_s"], hbm=b["hbm"]["avg_gib"])
s = a.scenario
if s == "BASE":
    for c, name in ((N_DISP, "A"), (N_BBRD, "B")):
        _, r, _ = fixture(c)
        out["fixture_" + name] = dist(r)
elif s == "S1":
    _, r, _ = fixture(CAND, squeeze_schbm=True)
    out.update(fixture="squeeze (HBM pool x0.001, ScHBM and CXL-PNM capacity 1 B)", tiers=dist(r), served=r["requests"]["served"])
    out["pass"] = r["arch"]["tiers"].get("cxl_pnm2", 0) >= 1 and r["requests"]["served"] > 0
elif s == "S2":
    _, r0, _ = fixture(CAND, w_energy=0.0)
    _, r5, _ = fixture(CAND, w_energy=5.0)
    out.update(fixture="squeeze (HBM pool x0.001)", w_E0=dist(r0), w_E5=dist(r5), pass_=dist(r0) != dist(r5))
    out["pass"] = out.pop("pass_")
elif s == "S3":
    from dp2sim.physics import OFFLOAD  # noqa: E402
    _, r0, _ = fixture(CAND)
    calls = Counter()
    if a.cand == "A":
        def key(r):
            calls["new"] += 1
            return (r[4] > 0.05, r[3])            # min TTFT among TPOT-feasible
        opts = dict(selector=key)
    else:
        holder = {}

        def least(claimants):
            calls["new"] += 1
            sim = holder["sim"]
            nd = sim.nodes[0]

            return min(claimants, key=lambda t: sim.board.agents[t].load(nd))
        opts = dict(arbitrate=least)

    def hook(sim):
        if a.cand == "B":
            holder["sim"] = sim
    _, r1, _ = fixture(CAND, hook=hook, **opts)
    out.update(fixture="squeeze (HBM pool x0.001)", before=dist(r0), after=dist(r1), new_policy_calls=calls["new"])
    out["pass"] = calls["new"] > 0 and dist(r0) != dist(r1)
elif s == "S4":
    state = {}

    def hook(sim):
        def mark(sm):
            cnt = Counter(t for (tt, t) in state["log"] if t in ("custom_hbm", "cxl_pnm") and tt < sm.now)
            if not cnt:
                state["tier"] = None
                return
            tier = cnt.most_common(1)[0][0]
            state["tier"], state["t_mark"] = tier, sm.now
            if a.cand == "A":
                sm.degraded_tiers.add(tier)
            else:
                sm.board.agents[tier].degraded = True
        sim.push(40.0, "ext", mark)

    holder = {}
    sim, r, log = None, None, None
    # the commit log is created inside fixture(); expose it to the hook through a shared list
    import dp2sim.nodeint as nodeint

    class _L(list):
        pass
    state["log"] = _L()
    orig_fixture = fixture

    def fixture_with_log(cand, **o):
        sim = NodeSim("SYS-H100", SC, 11, cand, 8.0, dict(SHORT, hbm_mult=0.001, **o))
        orig = sim.commit

        def commit(req, plan, t_dec, _o=orig):
            ok = _o(req, plan, t_dec)
            if ok:
                state["log"].append((sim.now, plan.n_d[1]))
            return ok
        sim.commit = commit
        hook(sim)
        return sim, sim.run()
    sim, r = fixture_with_log(CAND)
    tier = state.get("tier")
    tel = sim.o["tel"]
    if tier is None:
        out.update(fixture="squeeze", pass_=False, note="no offload tier used before the mark time; fixture invalid")
    else:
        t_mark = state["t_mark"]
        before = sum(1 for (t, x) in state["log"] if x == tier and t < t_mark)
        after = sum(1 for (t, x) in state["log"] if x == tier and t >= t_mark + tel + 1.0)
        total_after = sum(1 for (t, x) in state["log"] if t >= t_mark + tel + 1.0)
        out.update(fixture="squeeze (HBM pool x0.001), mark at t=40 s the most used offload tier", marked=tier, uses_before=before,
                   uses_after_mark_plus_tel_plus_1s=after, dispatches_after=total_after)
        out["pass_"] = before >= 1 and after == 0 and total_after > 0
    out["pass"] = out.pop("pass_", False)
print(json.dumps(out))
