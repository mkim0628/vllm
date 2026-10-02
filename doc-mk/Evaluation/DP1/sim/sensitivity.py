"""Post-stop sensitivity of the global design parameters (reporting only; no parameter is re-tuned).

    python sensitivity.py [--system SYS-4]

One parameter at a time is moved away from its pre-registered value; all three benchmark sets are rerun.
Output: results/data/sensitivity_<SYS>.json and a markdown table on stdout.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

import policies
import qa_eval
from model import load_profile

HERE = Path(__file__).resolve().parent
BASE_VALUES = dict(LINK_SHARE=policies.LINK_SHARE, COOLDOWN_S=policies.COOLDOWN_S,
                   BENEFIT_HORIZON_S=policies.BENEFIT_HORIZON_S, AFFINITY_MARGIN=policies.AFFINITY_MARGIN)
VARIANTS = [
    ("registered", {}),
    ("LINK_SHARE=0.10", dict(LINK_SHARE=0.10)),
    ("LINK_SHARE=0.50", dict(LINK_SHARE=0.50)),
    ("COOLDOWN_S=4 (bucket window 4 s)", dict(COOLDOWN_S=4.0)),
    ("COOLDOWN_S=16 (bucket window 16 s)", dict(COOLDOWN_S=16.0)),
    ("BENEFIT_HORIZON_S=10", dict(BENEFIT_HORIZON_S=10.0)),
    ("BENEFIT_HORIZON_S=60", dict(BENEFIT_HORIZON_S=60.0)),
    ("AFFINITY_MARGIN=1.0", dict(AFFINITY_MARGIN=1.0)),
    ("AFFINITY_MARGIN=4.0", dict(AFFINITY_MARGIN=4.0)),
]


def apply(over):
    vals = dict(BASE_VALUES, **over)
    policies.LINK_SHARE = vals["LINK_SHARE"]
    policies.COOLDOWN_S = vals["COOLDOWN_S"]
    policies.BENEFIT_HORIZON_S = vals["BENEFIT_HORIZON_S"]
    policies.AFFINITY_MARGIN = vals["AFFINITY_MARGIN"]
    policies.MigrationBudget.__init__.__defaults__ = (vals["LINK_SHARE"], vals["COOLDOWN_S"])


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--system", default="SYS-4")
    ap.add_argument("--jobs", type=int, default=min(4, os.cpu_count() or 1))
    a = ap.parse_args()
    load_profile(HERE / "configs", a.system)
    out = {}
    print("| variant | set | C1 QA1 ratio (w/t/l) | C2 QA1 ratio (w/t/l) |\n|---|---|---|---|")
    for name, over in VARIANTS:
        apply(over)
        res = qa_eval.evaluate(a.system, ["common_benchmark", "dp1_stress_benchmark", "dp1_dynamic_benchmark"], a.jobs, None)
        out[name] = {}
        for lab in ("common_benchmark", "dp1_stress_benchmark", "dp1_dynamic_benchmark", "combined"):
            d = res[lab]
            qa = d["qa_feasible"]
            t = d["tally"]
            row = {}
            cells = []
            for c in qa_eval.CANDS[1:]:
                q = qa[c]
                w = (len(t[c]["win"]), len(t[c]["tie"]), len(t[c]["loss"]))
                row[c] = dict(qa1=q["qa1_ratio_geomean"], qa1_ci=q["qa1_ratio_ci95"], wtl=w, loss=t[c]["loss"],
                              mig=q["migration_count"], mig_gib=q["migration_gib"])
                cells.append(f"x{q['qa1_ratio_geomean']:.3f}±{q['qa1_ratio_ci95']:.3f} ({w[0]}/{w[1]}/{w[2]})")
            out[name][lab] = row
            print(f"| {name} | {lab} | {cells[0]} | {cells[1]} |", flush=True)
    apply({})
    dst = HERE.parent / "results" / "data"
    dst.mkdir(parents=True, exist_ok=True)
    (dst / f"sensitivity_{a.system}.json").write_text(json.dumps(out, indent=1, sort_keys=True))


if __name__ == "__main__":
    main()
