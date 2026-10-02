"""Model-error (epsilon) sweep, reporting only: how much of C2's advantage survives estimator/predictor error.

    python epsilon_sweep.py [--system SYS-4]

eps = lognormal sigma on access-cost estimates (both candidates) and on C2's predicted hotness (C2 only).
No policy constant is re-tuned. Output: results/data/epsilon_<SYS>.json + markdown table.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

import qa_eval
from model import load_profile

HERE = Path(__file__).resolve().parent
EPS = (0.0, 0.2, 0.4, 0.6)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--system", default="SYS-4")
    ap.add_argument("--jobs", type=int, default=min(4, os.cpu_count() or 1))
    a = ap.parse_args()
    load_profile(HERE / "configs", a.system)
    out = {}
    print("| eps | C1 QA1 ratio | C2 QA1 ratio | C2/C1 | C1 win/tie/loss | C2 win/tie/loss | C1 QA3 | C2 QA3 |\n|---|---|---|---|---|---|---|---|")
    for eps in EPS:
        qa_eval.MODEL_ERROR = eps
        res = qa_eval.evaluate(a.system, ["common_benchmark", "dp1_stress_benchmark", "dp1_dynamic_benchmark"], a.jobs, None)
        c = res["combined"]
        qa = c["qa_discriminating"]
        t = c["tally"]
        row = {}
        for cand in qa_eval.CANDS[1:]:
            q = qa[cand]
            row[cand] = dict(qa1=q["qa1_ratio_geomean"], qa1_ci=q["qa1_ratio_ci95"], qa3=q["qa3_useful_hbm_util"],
                             wtl=(len(t[cand]["win"]), len(t[cand]["tie"]), len(t[cand]["loss"])),
                             loss=t[cand]["loss"], mig_gib=q["migration_gib"])
        out[str(eps)] = row
        c1, c2 = row["C1-resource-driven"], row["C2-behavior-driven"]
        print(f"| {eps} | x{c1['qa1']:.3f}±{c1['qa1_ci']:.3f} | x{c2['qa1']:.3f}±{c2['qa1_ci']:.3f} | x{c2['qa1']/c1['qa1']:.3f} | "
              f"{c1['wtl']} | {c2['wtl']} | {c1['qa3']*100:.0f}% | {c2['qa3']*100:.0f}% |", flush=True)
    qa_eval.MODEL_ERROR = 0.0
    dst = HERE.parent / "results" / "data"
    dst.mkdir(parents=True, exist_ok=True)
    (dst / f"epsilon_{a.system}.json").write_text(json.dumps(out, indent=1, sort_keys=True))


if __name__ == "__main__":
    main()
