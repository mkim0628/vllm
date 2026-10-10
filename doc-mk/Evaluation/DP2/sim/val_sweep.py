#!/usr/bin/env python3
"""Late-validation sweep (loop-log section 2). python3 val_sweep.py run|agg"""
import json, math, multiprocessing as mp, statistics, sys
from pathlib import Path
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from dp2sim.engine import BASELINE, C2, Sim  # noqa: E402
from dp2sim.scenarios import SCENARIOS  # noqa: E402
from dp2sim.runner import lam0_for  # noqa: E402
import qa5_scale as Q5  # noqa: E402
OUT = HERE.parent / "results" / "data" / "SYS-H100"
SYS = "SYS-H100"
SC = ("cb_kv_8k_b32", "dp2_turn_hbm_small_tool", "dp2_turn_dram_small_tool", "dp2_long_ctx_decode_offload", "dp2_internode_link_contention", "dyn_load_ramp_burst")
TOLS = (None, 0.05, 0.10, 0.20)


def job(a):
    kind, scn, cand, seed, load, opts = a
    sc = SCENARIOS[scn] if kind == "E1" else Q5.scn(int(scn[1:]))
    o = dict(opts)
    if kind == "E1":
        o["lam0"] = lam0_for(SYS, scn)
    else:
        o.update(horizon=120.0, warmup=15.0, min_turns=300, max_horizon=300.0)
    s = Sim(SYS, sc, seed, cand, load, o)
    r = s.run()
    q = r["qa"]
    st = s.stats
    return dict(kind=kind, scn=scn, cand=cand, seed=seed, load=load, opts={k: v for k, v in opts.items()}, gp=q["goodput_tok_s"], ttft99=q["ttft_p99_s"],
                tpot99=q["tpot_p99_s"], replans=st["replans"], dec=st["decisions"], age=statistics.mean(st["plan_age"]) if st["plan_age"] else 0.0)


def jobs():
    qa = json.load(open(HERE.parent / "results" / "data" / "qa_result.json"))
    J = []
    for s in SC:
        ld = qa["per_scenario"][f"{SYS}|{s}"][BASELINE]["load"]
        for tel in (0.05, 1.0):
            for sd in (11, 23, 37):
                J.append(("E1", s, BASELINE, sd, ld, {"tel": tel}))
                for tol in TOLS:
                    J.append(("E1", s, C2, sd, ld, {"tel": tel, "val_tol": tol}))
    for n in (16, 32):
        for w in (4, 16):
            for pn in (5, 8):
                for sd in (11, 23):
                    J.append(("E2", f"N{n}", BASELINE, sd, pn * n, {}))
                    for tol in TOLS:
                        J.append(("E2", f"N{n}", C2, sd, pn * n, {"workers": w, "val_tol": tol}))
    return J


if __name__ == "__main__":
    p = OUT / "val_sweep.jsonl"
    if sys.argv[1] == "run":
        J = jobs()
        J.sort(key=lambda a: -(int(a[1][1:]) if a[0] == "E2" else 0))
        with mp.Pool(4) as pool, open(p, "w") as f:
            for i, r in enumerate(pool.imap_unordered(job, J), 1):
                f.write(json.dumps(r) + "\n"); f.flush()
                if i % 50 == 0: print(i, len(J), flush=True)
    rows = [json.loads(l) for l in p.read_text().splitlines()]
    def key(r): return (r["kind"], r["scn"], r["cand"], r["load"], json.dumps(r["opts"], sort_keys=True))
    agg = {}
    for r in rows:
        agg.setdefault(key(r), []).append(r)
    mean = lambda k, f: statistics.mean(x[f] for x in agg[k])
    res = {}
    for r in rows:
        if r["cand"] != C2: continue
        o = r["opts"]; k = key(r)
        grp = (r["kind"], str(o.get("tel", "")), str(o.get("workers", "")), str(o.get("val_tol")))
        res.setdefault(grp, {}).setdefault((r["scn"], r["load"]), k)
    out = []
    for grp, d in sorted(res.items()):
        ratios, tt, rp = [], [], []
        for (scn, load), k in d.items():
            o = json.loads(k[4]); bo = {"tel": o["tel"]} if "tel" in o else {}
            bk = (k[0], scn, BASELINE, load, json.dumps(bo, sort_keys=True))
            b = mean(bk, "gp") if bk in agg else None
            if b and b > 0 and mean(k, "gp") > 0: ratios.append(mean(k, "gp") / b)
            tt.append(mean(k, "ttft99")); rp.append(sum(x["replans"] for x in agg[k]) / max(1, sum(x["dec"] for x in agg[k])))
        gm = math.exp(sum(map(math.log, ratios)) / len(ratios)) if ratios else None
        out.append(dict(kind=grp[0], tel=grp[1], workers=grp[2], tol=grp[3], n=len(d), gp_ratio_gm=gm, ttft99_mean=statistics.mean(tt), replan_rate=statistics.mean(rp)))
        print(out[-1])
    (OUT / "val_sweep_result.json").write_text(json.dumps(out, indent=1))
