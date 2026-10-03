"""Run the full benchmark (all three sets) on the generation profiles (SYS-A100/H100/B200/VR; legacy SYS-1..5 via --systems) for one Baseline-regression loop iteration and
store compact summaries under results/iterations/it<N>/ .

    python loop_run.py --iter 0                 # four generation profiles
    python loop_run.py --iter 1 --systems SYS-B200 # one system only (diagnostic reruns)
    python loop_run.py --final                  # full qa_result.json (incl. per-seed vectors) -> results/data/<SYS>/

The summary keeps, per set: QA table (feasible scenarios), per-scenario fit/verdicts and win/tie/loss tally,
and the combined table. Nothing is filtered: losing scenarios stay in the file.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

from model import load_profile
from qa_eval import BASE, CANDS, evaluate, print_result

HERE = Path(__file__).resolve().parent
RES = HERE.parent / "results"
SYSTEMS = ("SYS-B200", "SYS-A100", "SYS-H100")  # generation profiles (SYS-VR defined but excluded by owner decision); legacy SYS-1..5 via --systems


def compact(result):
    out = {"meta": result["meta"], "combined": {}}
    for label, d in result.items():
        if label in ("meta", "combined"):
            continue
        out[label] = dict(
            qa_feasible=_strip(d["qa_feasible"]),
            qa_discriminating=_strip(d["qa_discriminating"]),
            fit=d["fit"],
            tally=d["tally"],
            per_scenario={
                sn: {
                    "fit": lb["fit"],
                    "baseline_slo_attainment": lb["baseline_slo_attainment"],
                    **{
                        c: dict(
                            verdict=lb["vs_baseline"][c]["verdict"], goodput=lb["vs_baseline"][c]["goodput"],
                            ratio=lb["vs_baseline"][c]["goodput_ratio"], ttft=lb["vs_baseline"][c]["ttft"],
                            tpot=lb["vs_baseline"][c]["tpot"],
                            ttft_p99_ms=d["per_scenario"][sn][c]["ttft_p99_ms"],
                            tpot_p99_ms=d["per_scenario"][sn][c]["tpot_p99_ms"],
                            mig=d["per_scenario"][sn][c]["migration_count"],
                            mig_gib=d["per_scenario"][sn][c]["migration_gib"],
                        )
                        for c in CANDS[1:]
                        if lb["vs_baseline"]
                    },
                    BASE: dict(
                        goodput_tps=d["per_scenario"][sn][BASE]["max_goodput_tps"],
                        ttft_p99_ms=d["per_scenario"][sn][BASE]["ttft_p99_ms"],
                        tpot_p99_ms=d["per_scenario"][sn][BASE]["tpot_p99_ms"],
                    ),
                }
                for sn, lb in d["scenario_labels"].items()
            },
        )
    c = result["combined"]
    out["combined"] = dict(
        n_feasible=c["n_feasible"], n_discriminating=c["n_discriminating"],
        qa_feasible=_strip(c["qa_feasible"]), qa_discriminating=_strip(c["qa_discriminating"]), tally=c["tally"],
    )
    return out


def _strip(qa):
    return {c: {k: v for k, v in q.items() if k != "qa1_per_scenario"} for c, q in qa.items()}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--iter", type=int, default=None)
    ap.add_argument("--final", action="store_true")
    ap.add_argument("--systems", nargs="*", default=list(SYSTEMS))
    ap.add_argument("--jobs", type=int, default=min(4, os.cpu_count() or 1))
    a = ap.parse_args()
    for sid in a.systems:
        load_profile(HERE / "configs", sid)
        res = evaluate(sid, [s for s in ("common_benchmark", "dp1_stress_benchmark", "dp1_dynamic_benchmark")
                             if _nonempty(s)], a.jobs, None)
        if a.final:
            d = RES / "data" / sid
            d.mkdir(parents=True, exist_ok=True)
            (d / "qa_result.json").write_text(json.dumps(res, indent=1, sort_keys=True))
        else:
            d = RES / "iterations" / f"it{a.iter}"
            d.mkdir(parents=True, exist_ok=True)
            (d / f"{sid}_summary.json").write_text(json.dumps(compact(res), indent=1, sort_keys=True))
        print(f"##### {sid}")
        print_result(res)


def _nonempty(label):
    from qa_eval import SET_FUNCS
    return bool(SET_FUNCS[label]())


if __name__ == "__main__":
    main()
