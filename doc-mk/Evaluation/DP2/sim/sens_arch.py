#!/usr/bin/env python3
"""Sensitivity sweeps for the architecture-style evaluation (arch-styles-plan.md 6; SKILL H17: policy constants are NOT re-tuned,
the sweeps only show how the pre-registered constants matter). Fixed operating point per scenario = the Baseline's best load from
results/data/arch/qa_result.json (iso-load); SYS-H100; seeds 11/23/37.
    python sens_arch.py run | agg
"""
import json
import math
import multiprocessing as mp
import statistics
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from dp2sim.nodeint import N_BASE, N_BBRD, N_DISP, NodeSim  # noqa: E402
from dp2sim.scenarios_node import NODE_SCENARIOS  # noqa: E402

OUT = HERE.parent / "results" / "data" / "arch"
CAL = json.loads((HERE / "configs" / "calibration_node.json").read_text())
SYS = "SYS-H100"
SC = ("n_cb_kv_8k_b32", "n_dp2_turn_dram_small_tool", "n_dp2_turn_hbf_hist", "n_dp2_long_ctx_decode_offload", "n_dp2_stale_telemetry", "n_dyn_load_ramp_burst")
SEEDS = (11, 23, 37)
AX = {   # axis -> (values, candidates it applies to)
    "eps": ((0.0, 0.2, 0.4, 0.6), (N_DISP,)),
    "lam_hbm": ((0.0, 0.25, 1.0, 4.0), (N_DISP,)),
    "t_ref": ((1e-4, 1e-3, 1e-2), (N_DISP,)),
    "theta": ((0.6, 0.8, 1.0), (N_BBRD,)),
    "rho_hi": ((0.7, 0.85, 0.95), (N_BBRD,)),
    "t_bb": ((1e-4, 5e-4, 2e-3), (N_BBRD,)),
    "tel": ((0.01, 0.05, 0.5, 1.0), (N_DISP, N_BBRD)),
}


def job(a):
    scn, cand, seed, load, ax, val = a
    sc = NODE_SCENARIOS[scn]
    o = {ax: val}
    if sc.mode == "open_sessions":
        o["lam0"] = CAL[f"{SYS}|{scn}"]["lam0"]
    r = NodeSim(SYS, sc, seed, cand, load, o).run()
    q = r["qa"]
    return dict(scn=scn, cand=cand, seed=seed, ax=ax, val=val, gp=q["goodput_tok_s"], ttft99=q["ttft_p99_s"], tpot99=q["tpot_p99_s"],
                hbm=r["hbm"]["avg_gib"], slo=q["slo_met_frac"], tiers=r["arch"]["tiers"])


def main():
    qa = json.load(open(OUT / "qa_result.json"))
    p = OUT / SYS / "sens.jsonl"
    if sys.argv[1] == "run":
        jobs = []
        for s in SC:
            load = qa["per_scenario"][f"{SYS}|{s}"][N_BASE]["load"]
            for ax, (vs, cs) in AX.items():
                for v in vs:
                    for c in (N_BASE,) + tuple(cs):
                        for sd in SEEDS:
                            jobs.append((s, c, sd, load, ax, v))
        with mp.Pool(4) as pool, open(p, "w") as f:
            for i, r in enumerate(pool.imap_unordered(job, jobs), 1):
                f.write(json.dumps(r) + "\n")
                f.flush()
                if i % 100 == 0:
                    print(i, len(jobs), flush=True)
    rows = [json.loads(l) for l in p.read_text().splitlines()]

    def m(s, c, ax, v, key):
        return statistics.mean(r[key] for r in rows if (r["scn"], r["cand"], r["ax"], r["val"]) == (s, c, ax, v))

    def gm(xs):
        xs = [x for x in xs if x and x > 0]
        return math.exp(sum(math.log(x) for x in xs) / len(xs)) if xs else None

    out = {}
    for ax, (vs, cs) in AX.items():
        out[ax] = {}
        for v in vs:
            row = {}
            for c in cs:
                gp, tt, tp, hb = [], [], [], []
                for s in SC:
                    b = m(s, N_BASE, ax, v, "gp")
                    if b <= 0:
                        continue
                    gp.append(m(s, c, ax, v, "gp") / b)
                    tt.append(m(s, c, ax, v, "ttft99") / max(1e-9, m(s, N_BASE, ax, v, "ttft99")))
                    tp.append(m(s, c, ax, v, "tpot99") / max(1e-9, m(s, N_BASE, ax, v, "tpot99")))
                    hb.append(m(s, c, ax, v, "hbm") / max(1e-9, m(s, N_BASE, ax, v, "hbm")))
                row[c] = dict(goodput=gm(gp), ttft99=gm(tt), tpot99=gm(tp), hbm=gm(hb), n=len(gp))
            out[ax][str(v)] = row
    (OUT / SYS / "sens_result.json").write_text(json.dumps(out, indent=1))
    for ax in out:
        for v, row in out[ax].items():
            print(ax, v, {c[:3]: {k: (round(x, 3) if isinstance(x, float) else x) for k, x in d.items()} for c, d in row.items()})


main()
