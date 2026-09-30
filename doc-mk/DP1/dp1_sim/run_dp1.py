"""DP1 evaluation CLI (doc-mk/Evaluation/dp1-simulation-plan.md, Phase 1-8).

  workload   generate a workload JSONL (shared by real client and simulator)
  sweep      load sweep x policies x seeds on a (GPU, TP, tiers) config
             -> Max SLO Goodput / TTFT / TPOT / useful util + QA table   [C | A+C | B+C]
  calibrate  fit perf model from measured/<gpu>/step_profile_*           [A]
  crossval   A100-calibrated model -> H100 blind prediction vs H100 actual (step + serving)
  validate   serving_sim vs actual vLLM runs of the same trace (B0 or B1/offload)
  shadow     C1/C2 shadow decisions on actual dp1_client traces          [A+C]

Examples
  python run_dp1.py sweep --gpu h100_sxm5_80g --tp 4 --kind multiturn --rates 0.5,1,1.5,2 --quick
  python run_dp1.py sweep --gpu h100_sxm5_80g --tp 4 --tiers dram,cxl_mem,hbf --kind hotness_flip
  python run_dp1.py calibrate --gpu a100_sxm4_80g --tp 4
  python run_dp1.py crossval --src a100_sxm4_80g --dst h100_sxm5_80g --tp 4
  python run_dp1.py shadow --gpu h100_sxm5_80g --tp 4 --run-dir measured/h100_sxm5_80g/serve_llama_3_1_70b_tp4_dp1
"""

from __future__ import annotations

import argparse
import csv
import json
import os
from collections import defaultdict
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

HERE = Path(__file__).resolve().parent
POLICIES = (
    "B0-vllm-lru-drop",
    "B1-lru-offload",
    "C1-resource-driven",
    "C2-behavior-driven",
)


def _one(job):
    from calibrate import resolve_step_model
    from hw import build_hw
    from serving_sim import simulate
    from workload import WorkloadSpec, generate

    (
        gpu,
        tp,
        model,
        tiers,
        kind,
        rate,
        seed,
        policy,
        horizon,
        kv_cap,
        kv_scale,
        step_pref,
        measured,
    ) = job
    hw = build_hw(
        gpu, tp, model, tiers=tiers, hbm_kv_scale=kv_scale, use_measurements=measured
    )
    if kv_cap:
        hw.kv_capacity_bytes = kv_cap
    sm, sm_level = (
        resolve_step_model(gpu, tp, model, prefer=step_pref)
        if measured
        else (None, "B")
    )
    if sm is None:
        from perf_model import StepModel

        sm = StepModel()
    turns = generate(WorkloadSpec(kind, rate=rate, horizon_s=horizon, seed=seed))
    r = simulate(hw, sm, policy, turns, max_sim_s=3 * horizon + 120)
    r.update(kind=kind, load=rate, seed=seed, gpu=gpu, tp=tp, tiers="+".join(tiers))
    r["hw_evidence"] = hw.trail.label()
    r["step_model_evidence"] = sm_level
    r["input_rss_uncertainty"] = hw.trail.uncertainty()
    r["assumptions"] = ";".join(hw.trail.assumptions())
    return r


def cmd_workload(a):
    from workload import WorkloadSpec, generate, save

    spec = WorkloadSpec(a.kind, rate=a.rate, horizon_s=a.horizon, seed=a.seed)
    turns = generate(spec)
    save(turns, Path(a.out), spec)
    print(f"{len(turns)} turns, {len({t.session for t in turns})} sessions -> {a.out}")


def cmd_sweep(a):
    from calibrate import projection_band
    from qa import (
        aggregate_seeds,
        qa1_throughput,
        qa2_latency,
        qa3_utilization,
        qa_table,
        stars,
        useful_utilization,
    )

    tiers = tuple(t for t in a.tiers.split(",") if t)
    rates = [float(x) for x in a.rates.split(",")]
    seeds = [int(x) for x in a.seeds.split(",")] if not a.quick else [0]
    pols = [p for p in a.policies.split(",")] if a.policies else list(POLICIES)
    jobs = [
        (
            a.gpu,
            a.tp,
            a.model,
            tiers,
            a.kind,
            r,
            s,
            p,
            a.horizon if not a.quick else min(a.horizon, 120),
            a.kv_capacity_bytes,
            a.hbm_kv_scale,
            a.step_model_from,
            not a.no_measured,
        )
        for r in rates
        for s in seeds
        for p in pols
    ]
    with ProcessPoolExecutor(max_workers=a.jobs) as ex:
        rows = list(ex.map(_one, jobs))

    out = Path(
        a.out
        or HERE / "out" / f"sweep_{a.gpu}_tp{a.tp}_{a.kind}_{'+'.join(tiers) or 'hbm'}"
    )
    out.mkdir(parents=True, exist_ok=True)
    keys = sorted({k for r in rows for k in r})
    with (out / "runs.csv").open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=keys)
        w.writeheader()
        w.writerows(rows)

    agg = defaultdict(dict)
    by = defaultdict(list)
    for r in rows:
        by[(r["policy"], r["load"])].append(r)
    for (p, load), rs in by.items():
        agg[p][load] = aggregate_seeds(rs)
    # QA1 = each candidate's own Max SLO Goodput over the sweep.
    # QA2/QA3 = measured at ONE common operating point for all candidates:
    # the load where the reference baseline (B0) reaches its Max SLO Goodput
    # (rule fixed before results: same offered load -> comparable latency/util).
    ref_p = "B0-vllm-lru-drop" if "B0-vllm-lru-drop" in agg else next(iter(agg))
    ref_load = max(agg[ref_p], key=lambda L: agg[ref_p][L]["slo_goodput_tok_s"])
    best = {}
    for p, loads in agg.items():
        lb = max(loads, key=lambda L: loads[L]["slo_goodput_tok_s"])
        g = loads[lb]["slo_goodput_tok_s"]
        b = loads[ref_load]
        best[p] = {
            "max_goodput": g,
            "at_load": lb,
            "qa23_load": ref_load,
            "ttft_p99_s": b["ttft_p99_s"],
            "tpot_p99_s": b["tpot_p99_s"],
            "useful_util": useful_utilization(b),
            "hbm_util": b["hbm_util_mean"],
            "pool_util": b["pool_util_mean"],
            "migration_GiB": b["migration_GiB"],
            "reuse_hbm_hit_rate": b["reuse_hbm_hit_rate"],
            "reuse_miss_rate": b["reuse_miss_rate"],
            "recompute_tokens": b["recompute_tokens"],
            "prefetch_hit": b["prefetch_hit"],
            "unnecessary_promotion": b["unnecessary_promotion"],
            "unnecessary_demotion": b["unnecessary_demotion"],
            "thrash_events": b["thrash_events"],
            "decision_overhead_model_ms": b["decision_overhead_model_ms"],
            "promotion_wait_mean_s": b["promotion_wait_mean_s"],
        }
    t_ref = best.get("B0-vllm-lru-drop", {}).get("max_goodput", 0.0)
    r0 = rows[0]
    lv = {"A": 0, "B": 1, "C": 2}
    ev_levels = (
        set(r0["hw_evidence"].strip("[]").split("+"))
        | set(r0["step_model_evidence"].split("+"))
        | {"C"}
    )
    label = "[" + "+".join(sorted(ev_levels, key=lambda x: lv.get(x, 9))) + "]"
    import hw as _hw

    band = projection_band(sorted(_hw.MEASURED.glob("validation_*.json")))
    assumed = [x for x in r0["assumptions"].split(";") if x]
    unc_note = (
        f"±{band * 100:.0f}% (worst validated A100->H100 / sim-vs-actual error)"
        if band
        else "NOT validated yet (no measured/validation_*.json); assumed inputs: "
        + ", ".join(assumed)
    )
    table = qa_table(best, t_ref, {p: label for p in best}, band)
    summary = {
        "config": {
            "gpu": a.gpu,
            "tp": a.tp,
            "model": a.model,
            "tiers": tiers,
            "kind": a.kind,
            "rates": rates,
            "seeds": seeds,
            "horizon_s": jobs[0][8],
        },
        "evidence": label,
        "uncertainty": unc_note,
        "assumptions": r0["assumptions"].split(";"),
        "T_ref": t_ref,
        "best": best,
        "stars": {
            p: {
                "QA1": qa1_throughput(b["max_goodput"], t_ref),
                "QA2": qa2_latency(b["ttft_p99_s"], b["tpot_p99_s"]),
                "QA3": qa3_utilization(b["useful_util"]),
            }
            for p, b in best.items()
        },
        "per_load": {
            p: {str(k): v for k, v in loads.items()} for p, loads in agg.items()
        },
    }
    (out / "summary.json").write_text(json.dumps(summary, indent=2, default=str))
    (out / "qa_table.md").write_text(
        table + f"\n\nEvidence {label}, uncertainty {unc_note}\n"
    )
    print(table)
    print(f"\nEvidence {label}  uncertainty {unc_note}")
    print("\nDiagnostics at the common QA2/QA3 load:")
    for p, b in best.items():
        print(
            f"  {p:20s} maxload={b['at_load']:<5} @qa23load={b['qa23_load']:<5} hit(HBM)={b['reuse_hbm_hit_rate']:.2f} miss={b['reuse_miss_rate']:.2f} "
            f"mig={b['migration_GiB']:.0f}GiB pf_hit={b['prefetch_hit']:.0f} unnec_prom={b['unnecessary_promotion']:.0f} "
            f"unnec_dem={b['unnecessary_demotion']:.0f} thrash={b['thrash_events']:.0f} "
            f"prom_wait={b['promotion_wait_mean_s'] * 1e3:.1f}ms dec={b['decision_overhead_model_ms']:.0f}ms "
            f"{stars(summary['stars'][p]['QA1'])}/{stars(summary['stars'][p]['QA2'])}/{stars(summary['stars'][p]['QA3'])}"
        )
    print(f"\n-> {out}")


def cmd_calibrate(a):
    from calibrate import fit_gpu, step_model_path

    sm = fit_gpu(a.gpu, a.tp, a.model)
    fi = sm.fit_info["rel_err"]
    print(
        json.dumps(
            {
                "coef": sm.coef,
                "mape": fi["mape"],
                "p90_abs_err": fi["p90_abs_err"],
                "bias": fi["bias"],
            },
            indent=2,
        )
    )
    print(f"-> {step_model_path(a.gpu, a.model, a.tp)}")


def cmd_crossval(a):
    from calibrate import blind_step, step_model_path, validate_serving
    from perf_model import StepModel

    res = {"step": blind_step(a.src, a.dst, a.tp, a.model)}
    sm = StepModel.load(step_model_path(a.src, a.model, a.tp))
    sm.evidence = f"A({a.src})+C blind"
    serving = []
    import hw as _hw

    for d in sorted((_hw.MEASURED / a.dst).glob(f"serve_{a.model}_tp{a.tp}_*")):
        if "offload" in d.name or "_kv" in d.name:
            continue
        serving.append(validate_serving(a.dst, a.tp, d, sm, a.model))
    res["serving"] = serving
    worst = {}
    for v in serving:
        for k, e in v["worst_abs_rel_err"].items():
            if e is not None:
                worst[k] = max(worst.get(k, 0.0), e)
    res["worst_abs_rel_err"] = worst
    res["blind"] = res["step"].get("blind", {})
    out = _hw.MEASURED / f"validation_{a.src}_to_{a.dst}_tp{a.tp}.json"
    out.write_text(json.dumps(res, indent=2))
    print(
        json.dumps(
            {
                "step_blind_mape": res["blind"].get("mape"),
                "step_blind_p90": res["blind"].get("p90_abs_err"),
                "serving_worst_abs_rel_err": worst,
            },
            indent=2,
        )
    )
    print(f"-> {out}")


def _kv_from_run_dir(a) -> float | None:
    """serve_*_kv<N> directories pinned --kv-cache-memory-bytes N per GPU."""
    if a.kv_capacity_bytes:
        return a.kv_capacity_bytes
    import re

    m = re.search(r"_kv(\d+)", Path(a.run_dir).name)
    return float(m.group(1)) * a.tp if m else None


def cmd_validate(a):
    from calibrate import resolve_step_model, validate_serving

    sm, lvl = resolve_step_model(a.gpu, a.tp, a.model)
    pol = "B1-lru-offload" if "offload" in Path(a.run_dir).name else "B0-vllm-lru-drop"
    res = validate_serving(
        a.gpu, a.tp, Path(a.run_dir), sm, a.model, pol, _kv_from_run_dir(a)
    )
    import hw as _hw

    out = _hw.MEASURED / f"validation_self_{a.gpu}_{Path(a.run_dir).name}.json"
    out.write_text(json.dumps(res, indent=2))
    print(json.dumps(res["worst_abs_rel_err"], indent=2))
    print(f"-> {out}")


def cmd_shadow(a):
    from calibrate import resolve_step_model
    from hw import build_hw
    from shadow import load_client, shadow_run

    tiers = tuple(t for t in a.tiers.split(",") if t)
    hw = build_hw(a.gpu, a.tp, a.model, tiers=tiers)
    kv = _kv_from_run_dir(a)
    if kv:
        hw.kv_capacity_bytes = kv
    sm, _ = resolve_step_model(a.gpu, a.tp, a.model)
    allres = {}
    for p in sorted(Path(a.run_dir).glob("client_*.jsonl")):
        recs = load_client(p)
        allres[p.name] = {
            pol: shadow_run(hw, sm, pol, recs)
            for pol in POLICIES
            if pol != "B0-vllm-lru-drop"
        }
        print(f"\n{p.name}")
        for pol, r in allres[p.name].items():
            ac, pr = r["actual"], r["projected"]
            print(
                f"  {pol:20s} goodput {ac['slo_goodput_tok_s']:.0f}->{pr['slo_goodput_tok_s']:.0f} tok/s  "
                f"TTFT99 {ac['ttft_p99_s']:.2f}->{pr['ttft_p99_s']:.2f}s  TPOT99 {ac['tpot_p99_s'] * 1e3:.0f}->{pr['tpot_p99_s'] * 1e3:.0f}ms  "
                f"mig {r['diagnostics']['migration_GiB']:.0f}GiB"
            )
    out = Path(a.run_dir) / f"shadow_{'+'.join(tiers)}.json"
    out.write_text(json.dumps(allres, indent=2))
    print(f"-> {out}")


def main():
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    sp = ap.add_subparsers(dest="cmd", required=True)

    def common(p, gpu=True):
        if gpu:
            p.add_argument("--gpu", required=True)
        p.add_argument("--tp", type=int, default=4)
        p.add_argument("--model", default="llama_3_1_70b")
        p.add_argument(
            "--kv-capacity-bytes",
            type=float,
            default=None,
            help="pin HBM KV capacity (match --kv-cache-memory-bytes of the real run)",
        )

    p = sp.add_parser("workload")
    p.add_argument(
        "--kind",
        default="multiturn",
        choices=["common", "multiturn", "hotness_flip", "long_cold"],
    )
    p.add_argument("--rate", type=float, required=True)
    p.add_argument("--seed", type=int, default=0)
    p.add_argument("--horizon", type=float, default=300)
    p.add_argument("--out", required=True)
    p.set_defaults(fn=cmd_workload)

    p = sp.add_parser("sweep")
    common(p)
    p.add_argument(
        "--tiers",
        default="dram",
        help="comma list from hw_catalog tiers; '' = HBM only",
    )
    p.add_argument(
        "--kind",
        default="multiturn",
        choices=["common", "multiturn", "hotness_flip", "long_cold"],
    )
    p.add_argument("--rates", default="0.5,1.0,1.5,2.0")
    p.add_argument("--seeds", default="0,1,2,3,4")
    p.add_argument("--policies", default="")
    p.add_argument("--horizon", type=float, default=300)
    p.add_argument(
        "--hbm-kv-scale",
        type=float,
        default=1.0,
        help="stress knob: scale HBM KV capacity",
    )
    p.add_argument(
        "--step-model-from",
        default=None,
        help="use this GPU's calibrated step model (blind projection)",
    )
    p.add_argument(
        "--no-measured", action="store_true", help="ignore measured/ (pure B/C)"
    )
    p.add_argument("--quick", action="store_true")
    p.add_argument("--jobs", type=int, default=os.cpu_count())
    p.add_argument("--out", default=None)
    p.set_defaults(fn=cmd_sweep)

    p = sp.add_parser("calibrate")
    common(p)
    p.set_defaults(fn=cmd_calibrate)

    p = sp.add_parser("crossval")
    common(p, gpu=False)
    p.add_argument("--src", default="a100_sxm4_80g")
    p.add_argument("--dst", default="h100_sxm5_80g")
    p.set_defaults(fn=cmd_crossval)

    p = sp.add_parser("validate")
    common(p)
    p.add_argument("--run-dir", required=True)
    p.set_defaults(fn=cmd_validate)

    p = sp.add_parser("shadow")
    common(p)
    p.add_argument("--run-dir", required=True)
    p.add_argument("--tiers", default="dram")
    p.set_defaults(fn=cmd_shadow)

    a = ap.parse_args()
    a.fn(a)


if __name__ == "__main__":
    main()
