#!/usr/bin/env python3
"""Sensitivity sweeps (simulation-plan.md 5): link BW, estimator error eps, telemetry refresh, decision cost T_ref.
Fixed operating point per scenario = the Baseline's best load from qa_result.json (iso-load); SYS-H100; seeds 11/23/37.
Reports goodput ratio vs Baseline (same setting; the Baseline does not depend on eps/telemetry/T_ref but does on link BW).
    python3 sens.py run|agg
"""
import json, multiprocessing as mp, statistics, sys
from pathlib import Path
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from dp2sim.engine import BASELINE, C1, C2, ORACLE, Sim  # noqa: E402
from dp2sim.scenarios import SCENARIOS  # noqa: E402
from dp2sim.runner import lam0_for  # noqa: E402

OUT = HERE.parent / "results" / "data"
SYS = "SYS-H100"
SC = ("cb_kv_8k_b32", "dp2_turn_hbm_small_tool", "dp2_turn_dram_small_tool", "dp2_long_ctx_decode_offload", "dp2_internode_link_contention", "dyn_load_ramp_burst")
SEEDS = (11, 23, 37)
AX = {"link": ("rdma_100g", "rdma_400g_1rail", "rdma_400g_4rail", "rdma_400g_8rail"), "eps": (0.0, 0.2, 0.4, 0.6),
      "tel": (0.01, 0.05, 0.25, 1.0), "t_ref": (1e-4, 1e-3, 1e-2)}
CANDS = (BASELINE, C1, C2, ORACLE)


def job(a):
    scn, cand, seed, load, ax, val = a
    o = {ax: val, "lam0": lam0_for(SYS, scn)}
    if scn in ("dp2_planner_fault_fallback",):
        pass
    r = Sim(SYS, SCENARIOS[scn], seed, cand, load, o).run()
    q = r["qa"]
    return dict(scn=scn, cand=cand, seed=seed, ax=ax, val=val, gp=q["goodput_tok_s"], ttft99=q["ttft_p99_s"], tpot99=q["tpot_p99_s"])


def main():
    qa = json.load(open(OUT / "qa_result.json"))
    p = OUT / SYS / "sens.jsonl"
    if sys.argv[1] == "run":
        jobs = [(s, c, sd, qa["per_scenario"][f"{SYS}|{s}"][BASELINE]["load"], ax, v) for s in SC for ax, vs in AX.items() for v in vs for c in CANDS for sd in SEEDS]
        with mp.Pool(4) as pool, open(p, "w") as f:
            for i, r in enumerate(pool.imap_unordered(job, jobs), 1):
                f.write(json.dumps(r) + "\n"); f.flush()
                if i % 50 == 0: print(i, len(jobs), flush=True)
    rows = [json.loads(l) for l in p.read_text().splitlines()]
    out = {}
    for ax, vs in AX.items():
        out[ax] = {}
        for v in vs:
            row = {}
            for c in CANDS:
                rat = []
                gps_b = {s: statistics.mean(r['gp'] for r in rows if (r['scn'], r['cand'], r['ax'], r['val']) == (s, BASELINE, ax, v)) for s in SC}
                gps_o = {s: statistics.mean(r['gp'] for r in rows if (r['scn'], r['cand'], r['ax'], r['val']) == (s, ORACLE, ax, v)) for s in SC}
                for s in SC:
                    g = lambda cc: statistics.mean(r["gp"] for r in rows if (r["scn"], r["cand"], r["ax"], r["val"]) == (s, cc, ax, v))
                    b = g(BASELINE)
                    rat.append(g(c) / b if b > 0 else float("nan"))
                ok = [x for x, s in zip(rat, SC) if x == x and gps_b[s] >= 0.1 * max(1.0, gps_o[s])]
                import math
                gps = {s: statistics.mean(r['gp'] for r in rows if (r['scn'], r['cand'], r['ax'], r['val']) == (s, c, ax, v)) for s in SC}
                row[c] = dict(gp=gps, gm=math.exp(sum(math.log(x) for x in ok) / len(ok)) if ok and all(x > 0 for x in ok) else None, per=dict(zip(SC, rat)))
            out[ax][str(v)] = row
    (OUT / SYS / "sens_result.json").write_text(json.dumps(out, indent=1))
    for ax in out:
        for v, row in out[ax].items():
            print(ax, v, {c[:6]: (round(x["gm"], 2) if x["gm"] else None) for c, x in row.items()})

main()
