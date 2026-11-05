#!/usr/bin/env python3
"""Baseline-only control for the node-internal evaluation (arch-styles-plan.md 8.2): calibrates lam0 of the open-loop scenarios on
Baseline-GPU-local and sweeps the closed-loop grids, BEFORE any candidate is run. Output: configs/calibration_node.json and
../results/data/arch/control_baseline.json.

    python node_control.py calib       # open-loop lam0
    python node_control.py sweep       # closed-loop grid peaks (seeds 11, 23)
"""
from __future__ import annotations

import json
import multiprocessing as mp
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from dp2sim.nodeint import N_BASE, NodeSim  # noqa: E402
from dp2sim.runner import LAM_GRID  # noqa: E402
from dp2sim.scenarios_node import NODE_SCENARIOS  # noqa: E402

HERE = Path(__file__).resolve().parent
SYSTEMS = ("SYS-H100", "SYS-B200")
CAL = HERE / "configs" / "calibration_node.json"
OUT = HERE.parent / "results" / "data" / "arch"


def _calib(a):
    sysid, scn = a
    curve, gmax = [], 0.0
    for lam in LAM_GRID:
        r = NodeSim(sysid, NODE_SCENARIOS[scn], 11, N_BASE, 1.0, {"lam0": lam, "max_horizon": 400.0}).run()
        g = r["qa"]["goodput_tok_s"]
        curve.append((lam, g, r["qa"]["ttft_p99_s"], r["qa"]["tpot_p99_s"]))
        gmax = max(gmax, g)
        if gmax > 0 and g < 0.3 * gmax:
            break
    lam_sat = next((lam for lam, g, _, _ in curve if g >= 0.98 * gmax), None)
    return f"{sysid}|{scn}", dict(lam_sat=lam_sat, lam0=0.6 * lam_sat if lam_sat else None, gmax=gmax, curve=curve)


def _sweep(a):
    sysid, scn, load, seed = a
    sc = NODE_SCENARIOS[scn]
    lam0 = json.loads(CAL.read_text()).get(f"{sysid}|{scn}", {}).get("lam0") if sc.mode == "open_sessions" else None
    r = NodeSim(sysid, sc, seed, N_BASE, float(load), {"lam0": lam0} if lam0 else None).run()
    q = r["qa"]
    return dict(system=sysid, scenario=scn, load=load, seed=seed, goodput=q["goodput_tok_s"], ttft99=q["ttft_p99_s"], tpot99=q["tpot_p99_s"],
                slo=q["slo_met_frac"], served=r["requests"]["served"], offered=r["requests"]["offered"])


def main():
    cmd = sys.argv[1]
    OUT.mkdir(parents=True, exist_ok=True)
    if cmd == "calib":
        jobs = [(s, n) for s in SYSTEMS for n, sc in NODE_SCENARIOS.items() if sc.mode == "open_sessions"]
        with mp.Pool(4) as p:
            res = dict(p.map(_calib, jobs))
        CAL.write_text(json.dumps(res, indent=1))
        for k, v in res.items():
            print(k, "lam_sat", v["lam_sat"], "lam0", v["lam0"], "gmax", round(v["gmax"], 1))
    else:
        cal = json.loads(CAL.read_text()) if CAL.exists() else {}
        import os
        only = [x for x in os.environ.get("NODE_CONTROL_ONLY", "").split(",") if x]
        jobs = []
        for s in SYSTEMS:
            for n, sc in NODE_SCENARIOS.items():
                if only and n not in only:
                    continue
                for load in sc.grid:
                    for seed in (11, 23):
                        jobs.append((s, n, load, seed))
        with mp.Pool(4) as p:
            rows = p.map(_sweep, jobs)
        (OUT / ("control_baseline_extra.json" if only else "control_baseline.json")).write_text(json.dumps(rows, indent=1))
        import statistics
        by = {}
        for r in rows:
            by.setdefault((r["system"], r["scenario"]), {}).setdefault(r["load"], []).append(r)
        for (s, n), d in by.items():
            gl = {l: statistics.mean(x["goodput"] for x in v) for l, v in d.items()}
            pk = max(gl, key=gl.get)
            loads = sorted(gl)
            pos = "LOW-END" if pk == loads[0] else ("HIGH-END" if pk == loads[-1] else "interior")
            print(f"{s} {n:34s} peak load {pk:>5} ({pos}) goodput {gl[pk]:8.1f}  curve " + " ".join(f"{l}:{gl[l]:.0f}" for l in loads))


if __name__ == "__main__":
    main()
