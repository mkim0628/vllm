#!/usr/bin/env python3
"""QA5 Scalability runs (benchmark.md 6, qa-criteria-dp2.md 3). Workload: single-turn 4K->256 closed clients, P:D = 1:1,
per-node offered load grid, N total nodes. eta(N) = MaxSLOGoodput(N) / (N/2 * MaxSLOGoodput(N=2)).
    python3 qa5_scale.py run|agg [--system SYS-H100]
"""
from __future__ import annotations

import argparse
import json
import multiprocessing as mp
import statistics
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from dp2sim.engine import BASELINE, C1, C2, Sim  # noqa: E402
from dp2sim.scenarios import Scenario, const  # noqa: E402

OUT = HERE.parent / "results" / "data"
SEEDS = (11, 23)
NS = (2, 4, 8, 16, 32, 64)
PER_NODE = (2, 3, 4, 5, 6, 8, 10, 12)
VARIANTS = {                                    # name -> (candidate, opts)
    "Baseline": (BASELINE, {}),
    "C1": (C1, {}),
    "C1+topk8": (C1, {"topk": 8}),
    "C2(w=4)": (C2, {}),
    "C2(w=1)": (C2, {"workers": 1}),
    "C2(w=16)": (C2, {"workers": 16}),
    "C2+topk8": (C2, {"topk": 8}),
}
EXT = (16, 20, 24)                              # extension loads (peak was at the grid end): seed 11 only, main sweep only
TIERS = (1, 2, 4)
TREF = (0.1e-3, 1e-3, 10e-3)


def scn(n):
    return Scenario(f"scale_n{n}", "scale", n // 2, n // 2, "closed_clients", tuple(c * n for c in PER_NODE), turns=1,
                    prompt=const(4096), hbm_mult=1.0)


def jobs(system):
    J = []
    for n in NS:
        for v, (cand, o) in VARIANTS.items():
            for pn in PER_NODE + EXT:
                for sd in (SEEDS if pn in PER_NODE else SEEDS[:1]):
                    J.append(dict(system=system, n=n, var=v, cand=cand, opts=dict(o), load=pn * n, per_node=pn, seed=sd, kind="main"))
    for nt in TIERS:                                         # candidate-space growth: tiers per node (affects K only)
        for v in ("C1", "C2(w=4)"):
            cand, o = VARIANTS[v]
            for pn in PER_NODE:
                for sd in SEEDS:
                    J.append(dict(system=system, n=32, var=v, cand=cand, opts={**o, "ntiers": nt}, load=pn * 32, per_node=pn, seed=sd, kind=f"tiers{nt}"))
    for tr in TREF:                                          # decision cost sensitivity at N=32
        for v in ("C1", "C2(w=4)"):
            cand, o = VARIANTS[v]
            for pn in PER_NODE:
                for sd in SEEDS:
                    J.append(dict(system=system, n=32, var=v, cand=cand, opts={**o, "t_ref": tr}, load=pn * 32, per_node=pn, seed=sd, kind=f"tref{tr * 1e3:g}"))
    return J


def run1(j):
    s = Sim(j["system"], scn(j["n"]), j["seed"], j["cand"], j["load"], dict(j["opts"], horizon=120.0, warmup=15.0, min_turns=300, max_horizon=300.0))
    r = s.run()
    q = r["qa"]
    return dict(j, goodput=q["goodput_tok_s"], ttft99=q["ttft_p99_s"], tpot99=q["tpot_p99_s"], t_dec_ms=1e3 * r["planner"]["t_dec_mean_s"],
                replans=r["planner"]["replans"], decisions=r["planner"]["decisions"], regret=r["planner"]["regret_mean_s"],
                plan_age_ms=1e3 * r["planner"]["plan_age_mean_s"], util=q["useful_utilization"], met=q["slo_met_frac"])


def key(j):
    return json.dumps([j["system"], j["n"], j["var"], j["kind"], j["per_node"], j["seed"]])


def run(system, workers):
    p = OUT / system / "qa5.jsonl"
    p.parent.mkdir(parents=True, exist_ok=True)
    done = set()
    if p.exists():
        done = {key(json.loads(l)) for l in p.read_text().splitlines()}
    todo = [j for j in jobs(system) if key(j) not in done]
    todo.sort(key=lambda j: -j["n"])
    print(len(todo), "jobs to run", flush=True)
    with mp.Pool(workers) as pool, open(p, "a") as f:
        for i, r in enumerate(pool.imap_unordered(run1, todo, chunksize=1), 1):
            f.write(json.dumps(r) + "\n")
            f.flush()
            if i % 20 == 0:
                print(f"  {i}/{len(todo)}", flush=True)


def agg(system):
    p = OUT / system / "qa5.jsonl"
    rows = [json.loads(l) for l in p.read_text().splitlines()]
    def best(n, var, kind):
        by = {}
        for r in rows:
            if (r["n"], r["var"], r["kind"]) == (n, var, kind):
                by.setdefault(r["per_node"], []).append(r)
        out = None
        for pn, rs in by.items():
            if len(rs) < (len(SEEDS) if pn in PER_NODE else 1):
                continue
            g = statistics.mean(x["goodput"] for x in rs)
            if out is None or g > out["goodput"]:
                out = dict(per_node=pn, goodput=g, ttft99=statistics.mean(x["ttft99"] for x in rs), tpot99=statistics.mean(x["tpot99"] for x in rs),
                           t_dec_ms=statistics.mean(x["t_dec_ms"] for x in rs), replans=statistics.mean(x["replans"] for x in rs),
                           decisions=statistics.mean(x["decisions"] for x in rs), regret=statistics.mean(x["regret"] for x in rs),
                           plan_age_ms=statistics.mean(x["plan_age_ms"] for x in rs), seeds=[x["goodput"] for x in sorted(rs, key=lambda y: y["seed"])])
        return out
    res = {"main": {}, "tiers": {}, "tref": {}}
    for v in VARIANTS:
        res["main"][v] = {n: best(n, v, "main") for n in NS}
        base2 = res["main"][v][2]
        for n in NS:
            b = res["main"][v][n]
            if b and base2:
                b["eta"] = b["goodput"] / ((n / 2) * base2["goodput"])
    for nt in TIERS:
        res["tiers"][nt] = {v: best(32, v, f"tiers{nt}") for v in ("C1", "C2(w=4)")}
    for tr in TREF:
        res["tref"][f"{tr * 1e3:g}"] = {v: best(32, v, f"tref{tr * 1e3:g}") for v in ("C1", "C2(w=4)")}
    (OUT / system / "qa5_result.json").write_text(json.dumps(res, indent=1, default=float))
    return res


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=("run", "agg"))
    ap.add_argument("--system", default="SYS-H100")
    ap.add_argument("--workers", type=int, default=4)
    a = ap.parse_args()
    run(a.system, a.workers) if a.cmd == "run" else print(json.dumps(agg(a.system)["main"], indent=1, default=float)[:3000])
