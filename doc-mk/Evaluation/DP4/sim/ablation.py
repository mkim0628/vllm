"""SKILL section 9 ablation: remove the core component of each candidate and rerun the same scenarios, systems, seeds.

    C2-no-scan   lock granted without the lock-manager scan period (direct hand-off; scan wait = 0)
    C1-no-batch  one block hash per CXL-RPC (rpc_hash_batch = 1)

    uv run --no-project python ablation.py --system SYS-H100 --jobs 4
    uv run --no-project python merge_systems.py SYS-H100 SYS-B200 --data-dir ../results/data/ablation --out-dir ../results/data/ablation/INT-H100-B200

The control (full C1 / C2 in the same run) must equal the main result file; otherwise the ablation is not used.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

import dp1_bridge
import qa_eval as q
from arms import ABLATION_NAMES, BASE, C1, C2

HERE = Path(__file__).resolve().parent
DATA = HERE.parent / "results" / "data"


def control_check(res, main_path):
    """full C1/C2 of this run vs the main qa_result.json: per-scenario Max SLO goodput must be identical."""
    if not main_path.exists():
        return dict(checked=False, reason=f"{main_path} missing")
    main = json.loads(main_path.read_text())
    bad = []
    n = 0
    for label in res["meta"]["sets"]:
        for sn, v in res[label]["per_scenario"].items():
            for a in (BASE, C1, C2):
                n += 1
                m = main[label]["per_scenario"][sn][a]["max_goodput_tps"]
                if abs(m - v[a]["max_goodput_tps"]) > 1e-9 * max(1.0, abs(m)):
                    bad.append((label, sn, a, m, v[a]["max_goodput_tps"]))
    return dict(checked=True, n_compared=n, mismatches=bad, match=not bad)


def stars_sum(qt):
    return sum(q.nstar(qt[k]) for k in ("qa1", "qa2", "qa3"))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--system", required=True, choices=list(dp1_bridge.SYSTEM_CLUSTER))
    ap.add_argument("--jobs", type=int, default=min(4, os.cpu_count() or 1))
    ap.add_argument("--out-dir", type=Path, default=None)
    a = ap.parse_args()
    out = a.out_dir or (DATA / "ablation" / a.system)
    out.mkdir(parents=True, exist_ok=True)
    cands = (BASE, C1, C2) + ABLATION_NAMES
    res = q.evaluate(a.system, [s for s, _ in q.SETS], a.jobs, None, None, None, q.SEEDS, False, cands)
    res["meta"]["ablation"] = dict(variants=list(ABLATION_NAMES), control_check=control_check(res, DATA / a.system / "qa_result.json"))
    # star totals on the common benchmark, full vs ablated
    cb = res["common_benchmark"]["qa_feasible"]
    res["meta"]["ablation"]["common_benchmark_star_sum"] = {c: stars_sum(cb[c]) for c in cands}
    (out / "qa_result.json").write_text(json.dumps(res, indent=1, sort_keys=True))
    print(json.dumps(res["meta"]["ablation"], indent=1)[:1500])


if __name__ == "__main__":
    main()
