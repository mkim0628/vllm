"""SKILL section 10: basis of the lower star boundary from Baseline-vs-Baseline noise.

Baseline-RDMA is run on disjoint seed groups with the same aggregation as QA1 (geometric mean over CB-1..3 of Max SLO
Goodput); the spread of the group-to-group ratio is the noise floor that the 0.90 boundary (star 1 / star 2) must exceed.
Upper boundaries (1.10) cannot be measured this way; they are a policy choice and are reported as such.

    uv run --no-project python star_basis.py --system SYS-H100 --jobs 4
"""
from __future__ import annotations

import argparse
import itertools
import json
import os
import statistics
from pathlib import Path

import dp1_bridge
import qa_eval as q
from arms import BASE

HERE = Path(__file__).resolve().parent
GROUPS = ((11, 23, 37, 53, 71), (101, 113, 127, 131, 149), (163, 173, 181, 191, 199), (211, 223, 227, 229, 233))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--system", required=True, choices=list(dp1_bridge.SYSTEM_CLUSTER))
    ap.add_argument("--jobs", type=int, default=min(4, os.cpu_count() or 1))
    ap.add_argument("--out-dir", type=Path, default=None)
    a = ap.parse_args()
    out = a.out_dir or (HERE.parent / "results" / "data" / "star_basis")
    out.mkdir(parents=True, exist_ok=True)
    per = []
    for g in GROUPS:
        runs, _ = q.sweep(a.system, "common_benchmark", a.jobs, (BASE,), None, None, g)
        ps = q.per_scenario(runs, (BASE,), g)
        per.append(dict(seeds=list(g),
                        goodput={sn: v[BASE]["max_goodput_tps"] for sn, v in ps.items()},
                        resid={sn: v[BASE]["at_base_peak"]["kv_resident_gib"] for sn, v in ps.items()},
                        ttft_p99={sn: v[BASE]["at_base_peak"]["ttft_p99_ms"] for sn, v in ps.items()}))
    pairs = []
    for i, j in itertools.combinations(range(len(GROUPS)), 2):
        r1 = q.geomean(per[j]["goodput"][s] / per[i]["goodput"][s] for s in per[i]["goodput"])
        r3 = q.geomean(per[j]["resid"][s] / per[i]["resid"][s] for s in per[i]["resid"])
        pairs.append(dict(groups=[i, j], qa1_ratio=r1, qa3_ratio=r3))
    dev1 = [abs(p["qa1_ratio"] - 1.0) for p in pairs]
    dev3 = [abs(p["qa3_ratio"] - 1.0) for p in pairs]
    res = dict(system=a.system, groups=[list(g) for g in GROUPS], per_group=per, pairs=pairs,
               qa1_noise_max_dev=max(dev1), qa1_noise_mean_dev=statistics.mean(dev1),
               qa3_noise_max_dev=max(dev3), qa3_noise_mean_dev=statistics.mean(dev3),
               lower_boundary_qa1=0.90, lower_margin_over_noise=(1.0 - 0.90) / max(max(dev1), 1e-12),
               upper_boundary_note="1.10 / 1.25 are policy choices (not measurable by Baseline-vs-Baseline noise); reported as such",
               note="qa3 boundary 0.95 compared with the saving-multiplier noise; sim noise only, not a hardware noise measurement [B+C]")
    (out / f"star_basis_{a.system}.json").write_text(json.dumps(res, indent=1, sort_keys=True))
    print(json.dumps({k: res[k] for k in res if k.startswith("qa") or k.startswith("lower")}, indent=1))


if __name__ == "__main__":
    main()
