"""Markdown tables for loop-log.md from results/iterations/it<N>/SYS-*_summary.json.

    python loop_tables.py 1            # iteration 1: SYS-4 detail + cross-system line
    python loop_tables.py 1 --scen     # include per-scenario verdicts for SYS-4
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

RES = Path(__file__).resolve().parent.parent / "results" / "iterations"
C = ("Baseline-static", "C1-resource-driven", "C2-behavior-driven")
SH = {"Baseline-static": "Base", "C1-resource-driven": "C1", "C2-behavior-driven": "C2"}
SETS = ("common_benchmark", "dp1_stress_benchmark", "dp1_dynamic_benchmark", "combined")


def cell(q):
    return (f"QA1 {q['qa1']} x{q['qa1_ratio_geomean']:.3f}±{q['qa1_ratio_ci95']:.3f} / "
            f"QA2 {q['qa2']} ({q['qa2_ttft_p99_worst_ms']:.0f}ms,{q['qa2_tpot_p99_worst_ms']:.0f}ms) / "
            f"QA3 {q['qa3']} {q['qa3_useful_hbm_util']*100:.0f}%")


def main():
    it = sys.argv[1]
    scen = "--scen" in sys.argv
    d = RES / f"it{it}"
    for sid in ("SYS-4", "SYS-1", "SYS-2", "SYS-3", "SYS-5"):
        f = d / f"{sid}_summary.json"
        if not f.exists():
            continue
        s = json.loads(f.read_text())
        print(f"\n#### iteration {it} - {sid}\n")
        print("| set (feasible n) | Baseline | C1 | C2 | C1 w/t/l | C2 w/t/l |")
        print("|---|---|---|---|---|---|")
        for lab in SETS:
            if lab not in s:
                continue
            blk = s[lab]
            qa = blk["qa_feasible"]
            if not qa:
                continue
            n = blk["n_feasible"] if lab == "combined" else sum(1 for v in blk["fit"].values() if v != "infeasible")
            t = blk["tally"]
            wtl = [f"{len(t[c]['win'])}/{len(t[c]['tie'])}/{len(t[c]['loss'])}" for c in C[1:]]
            print(f"| {lab} ({n}) | {cell(qa[C[0]])} | {cell(qa[C[1]])} | {cell(qa[C[2]])} | {wtl[0]} | {wtl[1]} |")
        if scen and sid == "SYS-4":
            print("\n| set/scenario | fit | base SLO | C1 ratio (verdict) | C2 ratio (verdict) | TTFT99 B/C1/C2 ms | TPOT99 B/C1/C2 ms |")
            print("|---|---|---|---|---|---|---|")
            for lab in SETS[:3]:
                if lab not in s:
                    continue
                for sn, v in s[lab]["per_scenario"].items():
                    if v["fit"] == "infeasible":
                        print(f"| {lab[:6]}/{sn} | infeasible | - | - | - | - | - |")
                        continue
                    def r(c):
                        x = v[c]
                        return f"x{x['ratio']:.3f} ({x['verdict']})"
                    tt = "/".join(f"{(v[c] if c != C[0] else v[c])['ttft_p99_ms']:.0f}" for c in C)
                    tp = "/".join(f"{v[c]['tpot_p99_ms']:.0f}" for c in C)
                    print(f"| {lab[:6]}/{sn} | {v['fit']} | {v['baseline_slo_attainment']:.2f} | {r(C[1])} | {r(C[2])} | {tt} | {tp} |")


if __name__ == "__main__":
    main()
