"""DP2 node-internal architecture-style evaluation (arch-styles-plan.md). Aggregation follows qa_eval.py (max SLO goodput over the
load sweep, QA2/QA3 at the Baseline's best load, paired-by-seed verdicts, fit labels, geometric means over comparison-valid pairs);
QA3 is the HBM KV occupancy (lower is better) with the equal-performance condition of the plan (section 4).

    python qa_eval_node.py run --workers 4      # -> ../results/data/arch/SYS-*/runs.jsonl (resumable)
    python qa_eval_node.py agg                  # -> ../results/data/arch/qa_result.json
Candidates for stars: Baseline-GPU-local, A-Dispatcher, B-Blackboard.
"""
from __future__ import annotations

import argparse
import json
import math
import os
import statistics
import sys
import time
from collections import defaultdict
import multiprocessing as mp
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from dp2sim.nodeint import N_BASE, N_BBRD, N_DISP, NodeSim  # noqa: E402
from dp2sim.runner import SEEDS  # noqa: E402
from dp2sim.scenarios_node import NODE_SCENARIOS as SCENARIOS  # noqa: E402

BASELINE, C1, C2 = N_BASE, N_DISP, N_BBRD

HERE = Path(__file__).resolve().parent
DATA = HERE.parent / "results" / "data" / "arch"
CALF = HERE / "configs" / "calibration_node.json"


def load_cal():
    return json.loads(CALF.read_text()) if CALF.exists() else {}


SYSTEMS = ("SYS-H100", "SYS-B200")
STAR_CANDS = (BASELINE, C1, C2)
REF_CANDS = ()
ALL_CANDS = STAR_CANDS + REF_CANDS
T95 = 2.776
MATERIAL_REL = 0.01
# pre-registered rating edges (inherited unchanged from DP1: qa-criteria-dp1.md A; fixed before any DP2 candidate run)
EDGES = dict(qa1=(0.97, 1.30), qa2=(0.95, 1.25), qa3=(0.95, 1.25))


def star(x, edges):
    return "★★★" if x >= edges[1] else ("★★" if x >= edges[0] else "★")


def common_q1(r):
    return "★★★" if r >= 1.10 else ("★★" if r >= 0.90 else "★")


def common_q2(ttft_s, tpot_s):
    if ttft_s <= 2 and tpot_s <= 0.05:
        return "★★★"
    if ttft_s <= 4 and tpot_s <= 0.1:
        return "★★"
    return "★"


def common_q3(u):
    return "★★★" if u >= 0.85 else ("★★" if u >= 0.65 else "★")


def mean_ci(xs):
    m = statistics.mean(xs)
    sd = statistics.stdev(xs) if len(xs) > 1 else 0.0
    return m, T95 * sd / math.sqrt(len(xs)), (sd / m if m else 0.0)


def geomean(xs):
    xs = [max(1e-12, x) for x in xs]
    return math.exp(statistics.mean(math.log(x) for x in xs))


# ------------------------------------------------------------------------------------------------- running
def compact(r):
    return dict(meta=r["meta"], qa=r["qa"], req=r["requests"], pool=r["utilization"]["pool_busy_frac"], cv_p=r["utilization"]["cv_p"],
                cv_d=r["utilization"]["cv_d"], gib_turn=r["transfers"]["per_turn_internode_gib_mean"], link=r["transfers"]["link_util_mean"],
                planner=r["planner"], comp=r["ttft_components_mean_s"], end=r["extra"]["end"], demote_gib=r["extra"]["demote_gib"],
                hbm=r["hbm"], arch=r["arch"])


def _job(a):
    sysid, scn, cand, seed, load, opts = a
    t = time.time()
    r = NodeSim(sysid, SCENARIOS[scn], seed, cand, load, opts).run()
    c = compact(r)
    c["wall"] = time.time() - t
    return c


def key_of(a):
    sysid, scn, cand, seed, load, opts = a
    return f"{sysid}|{scn}|{cand}|{seed}|{load}"


def build_jobs(systems=SYSTEMS, names=None, cands=ALL_CANDS, seeds=SEEDS, opts_extra=None):
    cal = load_cal()
    jobs = []
    for sysid in systems:
        for scn in (names or list(SCENARIOS)):
            sc = SCENARIOS[scn]
            lam0 = None
            if sc.mode == "open_sessions":
                lam0 = cal.get(f"{sysid}|{scn}", {}).get("lam0")
                if lam0 is None:
                    raise SystemExit(f"missing calibration for {sysid}|{scn}")
            for load in sc.grid:
                for cand in cands:
                    for seed in seeds:
                        o = {"lam0": lam0} if lam0 else {}
                        if opts_extra:
                            o = dict(o, **opts_extra)
                        jobs.append((sysid, scn, cand, seed, float(load), o or None))
    return jobs


def run_all(out_dir, jobs, workers=4):
    out_dir = Path(out_dir)
    done = set()
    paths = {}
    for sysid in {j[0] for j in jobs}:
        p = out_dir / sysid
        p.mkdir(parents=True, exist_ok=True)
        paths[sysid] = p / "runs.jsonl"
        if paths[sysid].exists():
            for line in paths[sysid].read_text().splitlines():
                m = json.loads(line)["meta"]
                done.add(f"{m['system']}|{m['scenario']}|{m['candidate']}|{m['seed']}|{float(m['load'])}")
    todo = [j for j in jobs if key_of(j) not in done]
    print(f"{len(jobs)} jobs, {len(done)} done, {len(todo)} to run", flush=True)
    t0 = time.time()
    fhs = {s: open(p, "a") for s, p in paths.items()}
    n = 0
    with mp.Pool(workers) as pool:
        for res in pool.imap_unordered(_job, todo, chunksize=4):
            fhs[res["meta"]["system"]].write(json.dumps(res) + "\n")
            n += 1
            if n % 100 == 0:
                for f in fhs.values():
                    f.flush()
                print(f"  {n}/{len(todo)} ({time.time()-t0:.0f}s)", flush=True)
    for f in fhs.values():
        f.close()
    print("run done", f"{time.time()-t0:.0f}s", flush=True)


# ------------------------------------------------------------------------------------------------ aggregation
def load_rows(data_dir):
    rows = []
    for sysid in SYSTEMS:
        p = Path(data_dir) / sysid / "runs.jsonl"
        if p.exists():
            rows += [json.loads(l) for l in p.read_text().splitlines()]
    return rows


def record(rs, load):
    g, ci, cv = mean_ci([r["qa"]["goodput_tok_s"] for r in rs])
    return dict(
        load=load, goodput=g, goodput_ci=ci, goodput_cv=cv,
        ttft_p50=statistics.mean(r["qa"]["ttft_p50_s"] for r in rs), ttft_p95=statistics.mean(r["qa"]["ttft_p95_s"] for r in rs),
        ttft_p99=statistics.mean(r["qa"]["ttft_p99_s"] for r in rs), tpot_p50=statistics.mean(r["qa"]["tpot_p50_s"] for r in rs),
        tpot_p95=statistics.mean(r["qa"]["tpot_p95_s"] for r in rs), tpot_p99=statistics.mean(r["qa"]["tpot_p99_s"] for r in rs),
        useful_util=statistics.mean(r["qa"]["useful_utilization"] for r in rs),
        slo_met=statistics.mean(r["qa"]["slo_met_frac"] for r in rs),
        pool_p=statistics.mean(r["pool"]["P"] for r in rs), pool_d=statistics.mean(r["pool"]["D"] for r in rs),
        cv_p=statistics.mean(r["cv_p"] for r in rs), cv_d=statistics.mean(r["cv_d"] for r in rs),
        gib_turn=statistics.mean(r["gib_turn"] for r in rs), link=statistics.mean(r["link"] for r in rs),
        t_dec_ms=1e3 * statistics.mean(r["planner"]["t_dec_mean_s"] for r in rs),
        plan_age_ms=1e3 * statistics.mean(r["planner"]["plan_age_mean_s"] for r in rs),
        replans=statistics.mean(r["planner"]["replans"] for r in rs), fallbacks=statistics.mean(r["planner"]["fallbacks"] for r in rs),
        regret=statistics.mean(r["planner"]["regret_mean_s"] for r in rs), mis=statistics.mean(r["planner"]["mis_selection_rate"] for r in rs),
        comp={k: statistics.mean(r["comp"][k] for r in rs) for k in rs[0]["comp"]},
        hbm_avg=statistics.mean(r["hbm"]["avg_gib"] for r in rs), hbm_net=statistics.mean(r["hbm"]["net_gib"] for r in rs),
        hbm_frac=statistics.mean(r["hbm"]["avg_frac"] for r in rs), hbm_peak=statistics.mean(r["hbm"]["peak_frac"] for r in rs),
        tiers={k: sum(r["arch"]["tiers"].get(k, 0) for r in rs) for k in ("hbm", "custom_hbm", "cxl_pnm", "hbf")},
        claims=statistics.mean(r["arch"].get("claims", 0) for r in rs), rejects=statistics.mean(r["arch"].get("rejects", 0) for r in rs),
        seeds_hbm=[r["hbm"]["avg_gib"] for r in rs],
        seeds_goodput=[r["qa"]["goodput_tok_s"] for r in rs], seeds_ttft99=[r["qa"]["ttft_p99_s"] for r in rs],
        seeds_tpot99=[r["qa"]["tpot_p99_s"] for r in rs], seeds_util=[r["qa"]["useful_utilization"] for r in rs],
        n_seeds=len(rs))


def per_scenario(rows, cands=ALL_CANDS):
    """{(sys, scn): {cand: record at its own best load + 'iso': record at the Baseline's best load}}.
    Best load = argmax mean goodput over seeds (DP1 semantics). QA1 uses each candidate's own best load; QA2/QA3 are compared
    at the Baseline's best load (iso-load, amendment 1 in loop-log 0.4); own-best-load values are kept as a sensitivity."""
    idx = defaultdict(dict)
    for r in rows:
        m = r["meta"]
        idx[(m["system"], m["scenario"], m["candidate"], float(m["load"]))][m["seed"]] = r
    out = {}
    pairs = []
    for (sysid, scn) in sorted({(k[0], k[1]) for k in idx}):
        need = {(c, float(l), sd) for c in cands for l in SCENARIOS[scn].grid for sd in SEEDS}
        have = {(k[2], k[3], sd) for k in idx if k[0] == sysid and k[1] == scn for sd in idx[k]}
        if need <= have:
            pairs.append((sysid, scn))                      # only fully completed (scenario, system) pairs
    for (sysid, scn) in pairs:
        out[(sysid, scn)] = {}
        loads = sorted({k[3] for k in idx if k[0] == sysid and k[1] == scn})
        for cand in cands:
            best = None
            for load in loads:
                rs = idx.get((sysid, scn, cand, load))
                if not rs or len(rs) < len(SEEDS):
                    continue
                rec = record([rs[s] for s in SEEDS], load)
                if best is None or rec["goodput"] > best["goodput"]:
                    best = rec
            out[(sysid, scn)][cand] = best
        bl = out[(sysid, scn)][BASELINE]["load"]
        for cand in cands:
            rs = idx[(sysid, scn, cand, bl)]
            out[(sysid, scn)][cand]["iso"] = record([rs[s] for s in SEEDS], bl)
    return out


def paired(base, cand, higher_is_better):
    d = [c - b for b, c in zip(base, cand)]
    m, ci, _ = mean_ci(d)
    bm = statistics.mean(base)
    rel = m / bm if bm else (0.0 if m == 0 else math.inf)
    if abs(rel) < MATERIAL_REL or abs(m) <= ci:
        return "tie", m, ci, rel
    return ("win" if (m > 0) == higher_is_better else "loss"), m, ci, rel


def compare(ps_pair, cands=ALL_CANDS):
    b = ps_pair[BASELINE]
    out = {}
    for cand in cands[1:]:
        c = ps_pair.get(cand)
        if c is None or b is None:
            continue
        vg, mg, cg, rg = paired(b["seeds_goodput"], c["seeds_goodput"], True)
        vt, mt, ct, rt = paired(b["iso"]["seeds_ttft99"], c["iso"]["seeds_ttft99"], False)
        vp, mp, cp, rp = paired(b["iso"]["seeds_tpot99"], c["iso"]["seeds_tpot99"], False)
        v = vg
        if "loss" in (vt, vp) and vg != "win":
            v = "loss"
        elif "win" in (vt, vp) and vg != "loss":
            v = "win" if vg == "tie" else vg
        out[cand] = dict(verdict=v, goodput=vg, ttft=vt, tpot=vp, goodput_ratio=(c["goodput"] / b["goodput"]) if b["goodput"] > 0 else None)
    return out


def labels(ps):
    lab = {}
    for pair, v in ps.items():
        b = v.get(BASELINE)
        if b is None or b["goodput"] <= 0:
            lab[pair] = dict(fit="infeasible", vs={})
            continue
        cmp_ = compare(v, STAR_CANDS)
        same = all(c["goodput"] == "tie" and c["ttft"] == "tie" and c["tpot"] == "tie" for c in cmp_.values())
        lab[pair] = dict(fit="saturated" if same else "comparison_valid", vs=compare(v, ALL_CANDS))
    return lab


def qa_table(ps, lab, pairs, cands=ALL_CANDS):
    """Aggregate over the given (sys, scn) pairs that are comparison-valid."""
    valid = [p for p in pairs if lab[p]["fit"] == "comparison_valid"]
    res = {}
    for cand in cands:
        if not valid:
            res[cand] = dict(n=0)
            continue
        rat = [ps[p][cand]["goodput"] / ps[p][BASELINE]["goodput"] for p in valid if ps[p].get(cand)]
        seed_gm = []
        for k in range(len(SEEDS)):
            ls = [ps[p][cand]["seeds_goodput"][k] / max(1e-9, ps[p][BASELINE]["seeds_goodput"][k]) for p in valid if ps[p][BASELINE]["seeds_goodput"][k] > 0]
            seed_gm.append(geomean(ls))
        gm = geomean(rat)
        gci = T95 * statistics.stdev(seed_gm) / math.sqrt(len(seed_gm)) if len(seed_gm) > 1 else 0.0
        def abs_gm(key, iso=True):
            return geomean([(ps[p][cand]["iso"] if iso else ps[p][cand])[key] for p in valid])
        def rel_gm(key, inv=True, iso=True):
            g_ = lambda p, c: (ps[p][c]["iso"] if iso else ps[p][c])[key]
            return geomean([(g_(p, BASELINE) / max(1e-12, g_(p, cand))) if inv else (g_(p, cand) / max(1e-12, g_(p, BASELINE))) for p in valid])
        six = [rel_gm(k) for k in ("ttft_p50", "ttft_p95", "ttft_p99", "tpot_p50", "tpot_p95", "tpot_p99")]
        six_own = [rel_gm(k, iso=False) for k in ("ttft_p50", "ttft_p95", "ttft_p99", "tpot_p50", "tpot_p95", "tpot_p99")]
        res[cand] = dict(
            n=len(valid), qa1_ratio=gm, qa1_ci=gci, qa1_abs=abs_gm("goodput", iso=False),
            ttft_p99=abs_gm("ttft_p99"), ttft_p50=abs_gm("ttft_p50"), tpot_p99=abs_gm("tpot_p99"), tpot_p50=abs_gm("tpot_p50"),
            ttft_p99_x=1.0 / rel_gm("ttft_p99"), ttft_p50_x=1.0 / rel_gm("ttft_p50"), tpot_p99_x=1.0 / rel_gm("tpot_p99"), tpot_p50_x=1.0 / rel_gm("tpot_p50"),
            ttft_impr=geomean(six[:3]), tpot_impr=geomean(six[3:]), qa2_impr=geomean(six),
            qa2_impr_ownload=geomean(six_own), ttft_impr_ownload=geomean(six_own[:3]), tpot_impr_ownload=geomean(six_own[3:]),
            util=statistics.mean(ps[p][cand]["iso"]["useful_util"] for p in valid), util_x=rel_gm("useful_util", inv=False),
            util_x_ownload=rel_gm("useful_util", inv=False, iso=False),
            pool_p=statistics.mean(ps[p][cand]["iso"]["pool_p"] for p in valid), pool_d=statistics.mean(ps[p][cand]["iso"]["pool_d"] for p in valid),
            cv_p=statistics.mean(ps[p][cand]["iso"]["cv_p"] for p in valid), cv_d=statistics.mean(ps[p][cand]["iso"]["cv_d"] for p in valid),
            gib_turn=statistics.mean(ps[p][cand]["iso"]["gib_turn"] for p in valid),
            t_dec_ms=statistics.mean(ps[p][cand]["iso"]["t_dec_ms"] for p in valid), plan_age_ms=statistics.mean(ps[p][cand]["iso"]["plan_age_ms"] for p in valid),
            regret=statistics.mean(ps[p][cand]["iso"]["regret"] for p in valid), mis=statistics.mean(ps[p][cand]["iso"]["mis"] for p in valid),
            ttft_worst=max(ps[p][cand]["iso"]["ttft_p99"] for p in valid), tpot_worst=max(ps[p][cand]["iso"]["tpot_p99"] for p in valid),
        )
        r = res[cand]
        r["star_qa1"] = star(gm, EDGES["qa1"])
        r["star_qa2"] = star(r["qa2_impr"], EDGES["qa2"])
        # QA3 = HBM KV occupancy (lower is better), iso-load, only pairs where the candidate keeps the Baseline's SLO attainment (plan 4)
        eq = [p for p in valid if ps[p][cand]["iso"]["slo_met"] >= ps[p][BASELINE]["iso"]["slo_met"] - 0.01]
        r["hbm_n_eq"], r["hbm_n_excluded"] = len(eq), len(valid) - len(eq)
        if eq:
            r["hbm_ratio"] = geomean([ps[p][cand]["iso"]["hbm_avg"] / max(1e-9, ps[p][BASELINE]["iso"]["hbm_avg"]) for p in eq])
            r["hbm_save"] = 1.0 / r["hbm_ratio"]
            r["hbm_abs_gib"] = statistics.mean(ps[p][cand]["iso"]["hbm_avg"] for p in eq)
            r["hbm_base_gib"] = statistics.mean(ps[p][BASELINE]["iso"]["hbm_avg"] for p in eq)
            r["hbm_net_ratio"] = geomean([max(1e-6, ps[p][cand]["iso"]["hbm_net"]) / max(1e-6, ps[p][BASELINE]["iso"]["hbm_net"]) for p in eq])
            r["hbm_peak"] = statistics.mean(ps[p][cand]["iso"]["hbm_peak"] for p in eq)
            r["star_qa3"] = star(r["hbm_save"], EDGES["qa3"])
        else:
            r["hbm_ratio"] = r["hbm_save"] = None
            r["star_qa3"] = "n/a"
        r["star_qa3_util_diag"] = star(r["util_x"], EDGES["qa3"])
        r["common_qa1"] = common_q1(gm)
        r["common_qa2"] = common_q2(r["ttft_p99"], r["tpot_p99"])
        r["common_qa3_util_diag"] = common_q3(r["util"])
    return res


def aggregate(data_dir):
    rows = load_rows(data_dir)
    ps = per_scenario(rows)
    lab = labels(ps)
    pairs_all = sorted(ps)
    sets = {}
    for sc in SCENARIOS.values():
        sets.setdefault(sc.set, []).append(sc.name)
    out = dict(n_rows=len(rows), pairs={f"{a}|{b}": lab[(a, b)]["fit"] for (a, b) in pairs_all}, tables={}, per_scenario={}, labels={})
    for (a, b), v in ps.items():
        out["per_scenario"][f"{a}|{b}"] = {c: ({k: (({kk: xx for kk, xx in x.items() if not kk.startswith("seeds_")}) if k == "iso" else x) for k, x in d.items() if not k.startswith("seeds_")} if d else None) for c, d in v.items()}
        out["labels"][f"{a}|{b}"] = lab[(a, b)]
    out["tables"]["combined"] = qa_table(ps, lab, pairs_all)
    for name, ns in sets.items():
        out["tables"][name] = qa_table(ps, lab, [p for p in pairs_all if p[1] in ns])
    for sysid in SYSTEMS:
        out["tables"][sysid] = qa_table(ps, lab, [p for p in pairs_all if p[0] == sysid])
    return out, ps, lab


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=("run", "agg"))
    ap.add_argument("--out", default=str(DATA))
    ap.add_argument("--data", default=str(DATA))
    ap.add_argument("--scenarios", nargs="*")
    ap.add_argument("--systems", nargs="*", default=list(SYSTEMS))
    ap.add_argument("--cands", nargs="*", default=list(ALL_CANDS))
    ap.add_argument("--workers", type=int, default=4)
    a = ap.parse_args()
    if a.cmd == "run":
        run_all(a.out, build_jobs(a.systems, a.scenarios, tuple(a.cands)), a.workers)
    else:
        res, ps, lab = aggregate(a.data)
        Path(a.data, "qa_result.json").write_text(json.dumps(res, indent=1, default=float))
        print("rows", res["n_rows"], "pairs", len(res["pairs"]))
        from collections import Counter
        print(Counter(res["pairs"].values()))


if __name__ == "__main__":
    main()
