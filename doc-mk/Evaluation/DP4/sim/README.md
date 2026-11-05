# DP4 simulator (`DP4/sim/`)

Discrete-event simulator of a P/D-disaggregated cluster with three arms: **Baseline-RDMA**, **C1-central-serialization**
(CXL-RPC metadata server), **C2-distributed-lock** (lock-free lookup, two-tier locks, lock-manager scan). Spec: `../simulation-plan.md`
(authoritative). Decisions and approximations: `DESIGN_NOTES.md`. Python standard library only; physics (`prefill_s`, `decode_step_s`)
is imported from `DP1/sim/model.py` (read-only, `dp1_bridge.py`). Output is Evidence [B+C].

| File | Role |
|---|---|
| `configs/cluster_dp4.json` | every parameter with `value`, `range`, `provenance` (PAPER/SPEC/ASSUMED) |
| `params.py` | config loader, `Params` dataclass, overrides |
| `scenarios.py` | single source of scenarios (`common_benchmark()`, `dp4_benchmark()`) |
| `arms.py` | control planes of the three arms + ablation variants (`C1-no-batch`, `C2-no-scan`); data plane is shared |
| `simulator.py` | DES: trace, DP2 argmin, prefill, link FIFO fluid servers, decode processor sharing, failures, metrics |
| `qa_eval.py` | QA1/QA2/QA3, fit labels, win/tie/loss, scaling efficiency, C1 vs C2 table, tail check, failure and control-plane saturation tables |
| `merge_systems.py` | SYS-H100 + SYS-B200 -> `INT-H100-B200` ((scenario, system) pairs) |
| `ablation.py` | SKILL section 9 ablation (control must equal the main result) |
| `star_basis.py` | SKILL section 10: Baseline-vs-Baseline noise for the lower star boundary |
| `test_sim.py` | unittest suite |

## Reproduce
```bash
cd doc-mk/Evaluation/DP4/sim
uv run --no-project python -m unittest test_sim -v
uv run --no-project python qa_eval.py --system SYS-H100 --jobs 4 --out-dir ../results/data/SYS-H100
uv run --no-project python qa_eval.py --system SYS-B200 --jobs 4 --out-dir ../results/data/SYS-B200
uv run --no-project python merge_systems.py SYS-H100 SYS-B200
uv run --no-project python ablation.py --system SYS-H100 --jobs 4     # and SYS-B200, then merge with --data-dir ../results/data/ablation
uv run --no-project python star_basis.py --system SYS-H100 --jobs 4
```
Seeds 11 23 37 53 71, load grid x0.5/1.0/1.5/2.0 (extended to x8 when a peak is at the grid end), 95 % CI t(0.975, df=4)=2.776, material
difference 1 %. `qa_result.json` records command, seeds, loads run per scenario, git revision (+dirty flag), config path and sha1.

## Output schema (`qa_result.json`)
Follows DP1: `{<set>: {per_scenario, qa, qa_feasible, qa_discriminating, fit, scenario_labels, tally}, combined, meta}` with sets
`common_benchmark`, `dp4_benchmark`. DP4 additions per set: `c1_vs_c2`, `scaling_efficiency`, `failure`, `cp_capacity`, `briefs`, `exposes`.
Per candidate in `per_scenario`: peak-load values, `at_base_peak` (QA3/common-load basis), `at_load1`, `by_load`. `qa*` blocks hold
QA1 geomean ratio, QA2 TTFT/TPOT (P50/P95/P99, own-peak / `_common` / `_load1`), QA3 residency GiB and saving multiplier, `tail_check_*`
(pairs where the candidate P99 is worse than the Baseline and the worst pair).

Scaling Efficiency is reported as a value only (proposal, no stars). QA4 and protocol model check are outside this directory part.
