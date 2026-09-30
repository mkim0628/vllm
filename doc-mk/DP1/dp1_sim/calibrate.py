"""Phase 1/2/6: calibration and A100 -> H100 blind cross-validation.

  fit_gpu()        A100 step profile (A)  -> StepModel(A-calibrated)
  blind_step()     A100 StepModel + H100 spec (B3) -> predicted H100 step profile,
                   compared with H100 actual (A) -> step-level error
  validate_serving()
                   serving_sim (B0 / B1) vs actual vLLM runs of the SAME trace
                   (bench-serve common runs or dp1_client runs)
                   -> serving-level error on Max SLO Goodput / TTFT / TPOT
The worst of these errors becomes the projection band written into the
QA table for unsupported HW (criteria §2.3, §3: "★★★ [C, ±8%]").
"""

from __future__ import annotations

import json
from pathlib import Path

import hw as _hw
from hw import build_hw
from perf_model import StepModel, evaluate, fit, load_latency_runs
from serving_sim import simulate
from workload import Turn, load


def step_model_path(gpu: str, model: str, tp: int) -> Path:
    return _hw.MEASURED / gpu / f"step_model_{model}_tp{tp}.json"


def profile_dir(gpu: str, model: str, tp: int) -> Path:
    return _hw.MEASURED / gpu / f"step_profile_{model}_tp{tp}"


def fit_gpu(gpu: str, tp: int, model: str = "llama_3_1_70b") -> StepModel:
    runs = load_latency_runs(profile_dir(gpu, model, tp))
    if not runs:
        raise SystemExit(
            f"no step profile in {profile_dir(gpu, model, tp)} - run measure/02_step_profile.py first"
        )
    hw = build_hw(gpu, tp, model)
    sm = fit(hw, runs)
    sm.save(step_model_path(gpu, model, tp))
    return sm


def resolve_step_model(
    gpu: str, tp: int, model: str = "llama_3_1_70b", prefer: str | None = None
) -> tuple[StepModel, str]:
    """Pick the best available step model and its evidence label.

    own A-calibration  -> 'A'      ; other GPU's calibration (blind) -> 'A+C'
    nothing measured   -> 'B'(assumed efficiencies, labelled so)
    """
    own = step_model_path(gpu, model, tp)
    if own.exists() and prefer in (None, gpu):
        return StepModel.load(own), "A"
    M = _hw.MEASURED
    cands = sorted(M.glob(f"*/step_model_{model}_tp{tp}.json")) if M.exists() else []
    if prefer:
        cands = [c for c in cands if c.parent.name == prefer] or cands
    if cands:
        sm = StepModel.load(cands[0])
        sm.evidence = f"A({cands[0].parent.name})+C"
        return sm, "A+C"
    return StepModel(), "B"


def blind_step(
    src_gpu: str, dst_gpu: str, tp: int, model: str = "llama_3_1_70b"
) -> dict:
    sm = StepModel.load(step_model_path(src_gpu, model, tp))
    runs = load_latency_runs(profile_dir(dst_gpu, model, tp))
    if not runs:
        return {"error": f"no {dst_gpu} step profile (A) yet"}
    hw = build_hw(dst_gpu, tp, model)
    ev_blind = evaluate(hw, sm, runs)
    own = step_model_path(dst_gpu, model, tp)
    ev_own = evaluate(hw, StepModel.load(own), runs) if own.exists() else None
    return {
        "src": src_gpu,
        "dst": dst_gpu,
        "tp": tp,
        "blind": ev_blind,
        "dst_own_fit": ev_own,
    }


# ----------------------------------------------------------------------------
# serving-level validation
# ----------------------------------------------------------------------------


def turns_from_bench(path: Path, out_len: int = 256) -> tuple[list[Turn], dict]:
    """vllm bench serve --save-detailed JSON -> identical arrival trace + actual metrics."""
    j = json.loads(path.read_text())
    st = j.get("start_times") or []
    ins = j.get("input_lens") or []
    outs = j.get("output_lens") or []
    ttfts = j.get("ttfts") or []
    itls = j.get("itls") or []
    if not st:
        raise ValueError(f"{path} lacks start_times: re-run with --save-detailed")
    t0 = min(st)
    turns = [
        Turn(
            i, 0, int(ins[i]), int(outs[i] or out_len), st[i] - t0, 0.0, True, "single"
        )
        for i in range(len(st))
    ]
    ok = [(a, sum(b) / max(1, len(b))) for a, b in zip(ttfts, itls) if a and a > 0]
    actual = _metrics(
        [a for a, _ in ok], [b for _, b in ok], outs, dur=j.get("duration")
    )
    return turns, actual


def turns_from_client(path: Path) -> tuple[list[Turn], dict]:
    lines = [json.loads(x) for x in path.read_text().splitlines() if x.strip()]
    head = lines[0]
    recs = [r for r in lines[1:] if r.get("ttft_s") is not None and not r.get("error")]
    turns, _ = load(Path(head["_workload"]))
    summ = (
        json.loads(path.with_suffix(".summary.json").read_text())
        if path.with_suffix(".summary.json").exists()
        else {}
    )
    actual = _metrics(
        [r["ttft_s"] for r in recs],
        [r["tpot_s"] for r in recs],
        [r["output_tokens"] for r in recs],
        dur=summ.get("duration_s"),
    )
    return turns, actual


def _metrics(ttfts, tpots, outs, dur=None) -> dict:
    from qa import weighted_pct

    good = sum(o for a, b, o in zip(ttfts, tpots, outs) if a <= 2.0 and b <= 0.050)
    d = {
        "ttft_p50_s": weighted_pct(ttfts, 0.5),
        "ttft_p99_s": weighted_pct(ttfts, 0.99),
        "tpot_p50_s": weighted_pct(tpots, 0.5),
        "tpot_p99_s": weighted_pct(tpots, 0.99),
        "slo_attainment": sum(
            1 for a, b in zip(ttfts, tpots) if a <= 2.0 and b <= 0.050
        )
        / max(1, len(ttfts)),
    }
    if dur:
        d["slo_goodput_tok_s"] = good / dur
    return d


def validate_serving(
    gpu: str,
    tp: int,
    run_dir: Path,
    sm: StepModel,
    model: str = "llama_3_1_70b",
    policy: str = "B0-vllm-lru-drop",
    kv_capacity_bytes: float | None = None,
) -> dict:
    hw = build_hw(gpu, tp, model, tiers=("dram",))
    if kv_capacity_bytes:
        hw.kv_capacity_bytes = kv_capacity_bytes
    rows = []
    for p in sorted(run_dir.glob("bench_r*_s*.json")):
        turns, actual = turns_from_bench(p)
        sim = simulate(hw, sm, policy, turns)
        rows.append(_cmp(p.name, actual, sim))
    for p in sorted(run_dir.glob("client_*.jsonl")):
        turns, actual = turns_from_client(p)
        sim = simulate(hw, sm, policy, turns)
        rows.append(_cmp(p.name, actual, sim))
    keys = ("ttft_p50_s", "ttft_p99_s", "tpot_p50_s", "tpot_p99_s", "slo_goodput_tok_s")
    worst = {
        k: max((abs(r["rel_err"][k]) for r in rows if k in r["rel_err"]), default=None)
        for k in keys
    }
    return {
        "gpu": gpu,
        "policy": policy,
        "step_model": sm.evidence,
        "runs": rows,
        "worst_abs_rel_err": worst,
    }


def _cmp(name, actual, sim) -> dict:
    err = {}
    for k, v in actual.items():
        if k in sim and v:
            err[k] = (sim[k] - v) / v
    return {
        "run": name,
        "actual": actual,
        "sim": {k: sim.get(k) for k in actual},
        "rel_err": err,
    }


def projection_band(val_files: list[Path]) -> float | None:
    """Worst relative error on Max-SLO-Goodput-relevant metrics across validations."""
    worst = None
    for f in val_files:
        if not f.exists():
            continue
        j = json.loads(f.read_text())
        for k in ("slo_goodput_tok_s", "ttft_p99_s", "tpot_p99_s"):
            v = (j.get("worst_abs_rel_err") or {}).get(k)
            if v is not None:
                worst = v if worst is None else max(worst, v)
        b = (j.get("blind") or {}).get("p90_abs_err")
        if b is not None:
            worst = b if worst is None else max(worst, b)
    return worst
