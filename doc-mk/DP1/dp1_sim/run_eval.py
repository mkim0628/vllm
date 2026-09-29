from __future__ import annotations

import argparse
import csv
import json
import statistics
from pathlib import Path

from model import DATA_PRIORS, load_system
from scenarios import scenarios
from simulator import run_sim

CANDIDATES = ("C1-resource-driven", "C2-behavior-driven")
DEFAULT_SEEDS = (11, 23, 37)
DEFAULT_LOADS = (0.5, 1.0, 1.25)


def aggregate(rows):
    out = {}
    for cand in CANDIDATES:
        rs = [r for r in rows if r["candidate"] == cand]
        out[cand] = {
            "mean_slo_goodput_tokens": statistics.mean(
                r["slo_goodput_tokens"] for r in rs
            ),
            "worst_ttft_p99_ms": max(
                r["ttft_p99_ms"] for r in rs
            ),
            "worst_tpot_p99_ms": max(
                r["tpot_p99_ms"] for r in rs
            ),
            "mean_hbm_util": statistics.mean(
                r["avg_hbm_util"] for r in rs
            ),
            "mean_pool_util": statistics.mean(
                r["aggregate_capacity_util"] for r in rs
            ),
            "mean_migration_count": statistics.mean(
                r["migration_count"] for r in rs
            ),
            "mean_migration_gib": statistics.mean(
                r["migration_gib"] for r in rs
            ),
            "mean_decision_overhead_ms": statistics.mean(
                r["decision_overhead_ms"] for r in rs
            ),
            "mean_occupied_tiers": statistics.mean(
                r["occupied_tiers"] for r in rs
            ),
        }
    return out


def main():
    ap = argparse.ArgumentParser()
    here = Path(__file__).resolve().parent
    ap.add_argument(
        "--config-dir",
        type=Path,
        default=here / "configs",
    )
    ap.add_argument(
        "--out-dir",
        type=Path,
        default=here / "out",
    )
    ap.add_argument("--cluster", default="b200_8gpu")
    ap.add_argument("--model", default="llama_3_1_70b")
    ap.add_argument(
        "--quick",
        action="store_true",
        help="one seed/load for smoke test",
    )
    args = ap.parse_args()

    system = load_system(
        args.config_dir, args.cluster, args.model
    )
    scs = scenarios()
    seeds = (11,) if args.quick else DEFAULT_SEEDS
    loads = (1.0,) if args.quick else DEFAULT_LOADS

    rows = []
    for sc in scs:
        for seed in seeds:
            for load in loads:
                for cand in CANDIDATES:
                    rows.append(
                        run_sim(
                            system,
                            sc,
                            seed,
                            cand,
                            DATA_PRIORS,
                            load,
                        )
                    )

    args.out_dir.mkdir(
        parents=True, exist_ok=True
    )
    csv_path = args.out_dir / "results_runs.csv"
    with csv_path.open("w", newline="") as f:
        w = csv.DictWriter(
            f, fieldnames=list(rows[0])
        )
        w.writeheader()
        for r in rows:
            rr = dict(r)
            rr["tier_accesses"] = json.dumps(
                rr["tier_accesses"], sort_keys=True
            )
            w.writerow(rr)

    summary = aggregate(rows)
    (
        args.out_dir / "results_summary.json"
    ).write_text(
        json.dumps(
            summary, indent=2, sort_keys=True
        )
    )
    print(
        json.dumps(
            summary, indent=2, sort_keys=True
        )
    )


if __name__ == "__main__":
    main()
