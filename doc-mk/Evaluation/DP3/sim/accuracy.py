#!/usr/bin/env python3
"""DP3 QA5 (F1 relative drop) from the small-model eviction micro-benchmark (../accuracy) -> results/data/dp3_qa5.json.

Mapping (pre-registered in ../simulation-plan.md section 3, accuracy row):
  C2 Online (query-aware)      : drop = drop(aware, r)
  C1 Offline (representative)  : a request whose query is close to the representative query behaves like repB
                                 (a different question on the same paragraph); a far query behaves like repC (a question from another
                                 paragraph).  With scenario mismatch m:  drop = (1-m) * drop(repB) + m * drop(repC).
  Averaging over the DP3 scenarios (m from dp3_scenarios.py, comparison-valid pairs only).
Limits: eviction only (no selective recompute) -> an upper bound on the drop; small model (Qwen2.5-1.5B), SQuAD-style single paragraph
(~1.5K tokens, not 32K-256K); F1 relative to the full KV cache.  Evidence: measured on a small model [A, small scale] + mapping [C].
"""
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import dp3_scenarios as SC  # noqa: E402

R_KEEP = "0.3"
MIN_EXAMPLES = 30      # fixed before looking at the result; below this QA5 stays unevaluated


def main():
    acc = json.loads((HERE.parent / "accuracy" / "results" / "accuracy_summary.json").read_text())
    summ = json.loads((HERE.parent / "results" / "data" / "dp3_summary.json").read_text())
    br = acc["by_ratio"][R_KEEP]
    d = {k: br[k]["f1"]["rel_drop_pct"] for k in ("aware", "repA", "repB", "repC", "random")}
    mism = [SC.BY_ID[k.split("/")[1]].mismatch for k, e in summ["pairs"].items() if e["valid"]]
    m = sum(mism) / len(mism)
    c1 = (1 - m) * d["repB"] + m * d["repC"]
    # bootstrap-free interval: combine CI of the two measured conditions linearly (conservative: sum of half-widths)
    def hw(k):
        lo, hi = br[k]["f1"]["ci95"]
        return (hi - lo) / 2
    out = {"C1": {"f1_drop_pct": round(c1, 2), "ci95_halfwidth": round((1 - m) * hw("repB") + m * hw("repC"), 2)},
           "C2": {"f1_drop_pct": round(d["aware"], 2), "ci95_halfwidth": round(hw("aware"), 2)},
           "_meta": {"n_examples": acc["n_examples"], "r": R_KEEP, "mean_mismatch": round(m, 3), "full_f1": acc["full"]["f1"],
                     "drops_pct": {k: round(v, 2) for k, v in d.items()}, "min_examples": MIN_EXAMPLES, "model": "Qwen2.5-1.5B-Instruct (micro-benchmark)"}}
    (HERE.parent / "results" / "data" / "dp3_qa5.json").write_text(json.dumps(out, indent=1))
    print(json.dumps(out, indent=1))


if __name__ == "__main__":
    main()
