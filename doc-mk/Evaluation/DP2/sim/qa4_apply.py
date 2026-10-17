#!/usr/bin/env python3
"""Apply tools/qa4_modifiability.py (pre-registered formulas) to results/data/arch/qa4_measured_counts.json.
Candidate keys C1/C2 of the tool = A-Dispatcher / B-Blackboard. Also runs the S2 'full' variant for B as a sensitivity."""
import importlib.util
import json
import shutil
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
EVAL = HERE.parents[1]
DATA = EVAL / "DP2" / "results" / "data" / "arch"
spec = importlib.util.spec_from_file_location("qa4m", EVAL / "tools" / "qa4_modifiability.py")
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)


def apply(counts, out):
    with tempfile.TemporaryDirectory() as td:
        d = Path(td) / "DP2" / "results" / "data"
        d.mkdir(parents=True)
        (d / "qa4_measured_counts.json").write_text(json.dumps(counts))
        m.EVAL = Path(td)
        m.main("DP2")
        shutil.copy(d / "qa4_modifiability.json", out)


counts = json.loads((DATA / "qa4_measured_counts.json").read_text())
apply(counts, DATA / "qa4_modifiability.json")
alt = json.loads(json.dumps(counts))
alt["scenarios"]["S2"]["C2"] = counts["variants"]["S2full"]["C2"]
apply(alt, DATA / "qa4_modifiability_S2full.json")
for f in ("qa4_modifiability.json", "qa4_modifiability_S2full.json"):
    r = json.loads((DATA / f).read_text())
    print(f, r["qa4_stars"], r["sub_stars"], json.dumps(r["mean_over_scenarios"]))
