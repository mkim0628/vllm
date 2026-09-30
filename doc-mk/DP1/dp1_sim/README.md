# DP1 Current-Architecture Migration Simulator

> **Two simulators live here.**
>
> 1. **Serving simulator (new, Evaluation plan §5-§17)** — request-level vLLM-V1-like
>    continuous-batching simulation with an A/B/C evidence pipeline, calibrated on
>    the user's A100/H100 (`run_dp1.py`, `serving_sim.py`, `policies_serving.py`,
>    `measure/`). This is the one that produces the QA table.
> 2. **Object-level mixed-AI-data simulator (legacy port)** — `run_eval.py`,
>    `simulator.py`, `policies.py`. Kept for the mixed AI-data stress cases
>    (RAG / Agent Memory / LoRA / MoE) that vLLM cannot express yet. Its numbers are [B+C].
>
> The serving simulator is described first; the legacy section follows.

## Serving simulator (DP1 evaluation pipeline)

```text
configs/hw_catalog.json (B: spec / paper / assumed)     measured/<gpu>/*.json (A: measure/ scripts)
                 \                                       /
                  hw.build_hw() -> ServingHW  (+ EvidenceTrail: which input is A/B/assumed)
                                      |
workload.py JSONL ──┬──> measure/dp1_client.py -> real vLLM   [A]  (same trace)
                    └──> serving_sim.ServingSim                [C]
                           ├─ perf_model.StepModel  (A100-fitted -> H100 blind, §12)
                           ├─ MigrationScheduler (events.py)  -> B0 | B1 | C1 | C2 (policies_serving.py)
                           └─ transfers on shared lanes (PCIe / HBF) with measured TransferCurve
                                      |
                           qa.py -> Max SLO Goodput / TTFT·TPOT P99 / useful util -> ★ + [A/B/C]
shadow.py : C1/C2 decisions overlaid on an actual vLLM trace (§7 Shadow Mode)      [A+C]
calibrate.py : fit / blind cross-validation / sim-vs-actual error band            [A]
```

| Candidate | What it is | Registry | Promotion |
|---|---|---|---|
| B0-vllm-lru-drop | vLLM default prefix cache: LRU drop, recompute on miss | – | – |
| B1-lru-offload | ≈ vLLM native CPU KV offloading (`--kv-offloading-size`), real executor for Phase 5 validation | type-agnostic | demand only |
| C1-resource-driven | ResourceStateMonitor/TrendAnalyzer → generic eviction (idle×size) → DataMemoryAffinityMapper → DestinationTierSelectorC1 | **type-agnostic** | capacity recovery (§17.2) |
| C2-behavior-driven | DataBehaviorMonitor → class-level reuse-interval survival model + object EWMA → FutureBehaviorPredictor → restore-aware tier choice | **type-aware** | predicted reuse + headroom (§17.3) |

All candidates share the vLLM runtime fallbacks (LRU drop, preemption-recompute) and
demand promotion, so differences come only from the DP1 decision pipeline (design doc §18).

### Evaluation rules fixed before results

- QA1 = each candidate's own **Max SLO Goodput** over the load sweep (SLO TTFT ≤ 2 s and TPOT ≤ 50 ms per request).
- T_ref = B0 Max SLO Goodput on the same workload/HW.
- QA2/QA3 are read at **one common operating point** — the load where B0 reaches its Max SLO Goodput.
- QA3 useful util = time-avg(running KV + retained KV that is re-accessed later, in hindsight) / HBM KV capacity × SLO attainment. Lower-tier occupancy is reported as `pool_util_mean` (diagnostic).
- Median over seeds with 95% CI and CV (criteria §2.1).
- Evidence label = union of input levels (hw trail + step model) + C; uncertainty = worst validated error from `measured/validation_*.json`, otherwise "NOT validated" + the list of assumed inputs.

### Run

```bash
python test_dp1.py                                           # 12 tests, no GPU
python run_dp1.py sweep --gpu h100_sxm5_80g --tp 4 --kind multiturn --rates 0.5,1,1.5,2 --quick
python run_dp1.py sweep --gpu h100_sxm5_80g --tp 4 --kind hotness_flip --tiers dram,cxl_mem,hbf
```

What to run on the A100/H100 boxes: **`measure/README.md`**.

### Workloads (`workload.py`)

| kind | purpose |
|---|---|
| common | 8K in / 256 out Poisson, no reuse (criteria §8 Common Benchmark) |
| multiturn | agentic multi-turn: 4-12 turns, 60% hot (think 3 s) / 40% cold (think 45 s) sessions |
| hotness_flip | multiturn with hot↔cold inversion half-way through each session (prediction lag) |
| long_cold | 70% large-document sessions with 1-2 turns that are never reused (long-lived cold objects) |

---

## Legacy object-level simulator

This simulator is a migration-oriented rewrite of the legacy
`doc-architect/dp1_eval` / `doc-architect/dp1_sim` experiments from branch
`claude/dp1-ai-data-placement`.

## Reused from the old simulator

- `model.py`: heterogeneous-memory physical model and Llama-3.1-70B cost model
- `scenarios.py`: multi-AI-data workload/scenario definitions and deterministic traces; obsolete classifier-error cases are converted to behavior-prediction stress cases
- `configs/`: B200 8-GPU, memory-tier and model configuration
- same-trace comparison: C1/C2 see the same `(scenario, seed, load)` trace
- TTFT/TPOT and migration-cost accounting style

## Replaced for the current DP1

The old `dp1_eval` was placement-centric, while old `dp1_sim` was KV/agent-turn-centric with explicit Prefill-complete / tool-idle decision points. The current DP1 is generic runtime **AI Data migration**, so those old policy boundaries are not copied.
Therefore the old `place(obj, ...)` interface is not reused.

```text
Runtime Event
    -> MigrationScheduler
        -> C1 Resource-State pipeline
        or
        -> C2 Data-Behavior pipeline
    -> MigrationDecision
    -> idealized MigrationExecutor in simulator
```

Initial placement is generated by one common external allocator and is not counted
as DP1. C1/C2 only act after runtime events.

## Architecture fidelity

### C1 — Resource State-driven Migration + Data-Memory Affinity

- `C1DataObjectRegistry` is **type-agnostic**.
- Registry stores only object ID, location/tier, size, movable state.
- `DataEvictionManager` selects victims with generic eviction information.
- It never branches on KV/LoRA/MoE/etc.
- Static affinity is a **separate generic hint channel** and is not stored in the C1 registry.

### C2 — AI Data Behavior-driven Migration

- `C2DataObjectRegistry` is **type-aware**.
- Registry manages data type/class metadata for KV Cache, RAG/Agent Memory,
  Tool Result, LoRA and MoE Expert.
- `DataBehaviorMonitor -> BehaviorBasedTrendAnalyzer -> FutureBehaviorPredictor`
  uses runtime access/reuse/lifetime signals.
- Both promotion and demotion are modeled.

## Files

- `events.py`: Event and event-driven MigrationScheduler
- `registry.py`: distinct C1/C2 registry abstractions
- `policies.py`: current C1/C2 decision pipelines
- `simulator.py`: migration execution, cost and QA measurement
- `model.py`: reused physical model from old `dp1_eval`
- `scenarios.py`: reused workload generator from old `dp1_eval`
- `configs/`: reused environment configuration
- `run_eval.py`: C1/C2 experiment runner
- `test_sim.py`: architecture-boundary smoke tests

## Run

```bash
cd doc-mk/DP1/dp1_sim
python test_sim.py
python run_eval.py --quick
python run_eval.py
```

Outputs:

```text
out/results_runs.csv
out/results_summary.json
```

## Current metrics

- SLO goodput proxy
- TTFT p99
- TPOT p99
- HBM utilization
- aggregate memory-pool utilization
- migration count / bytes / transfer time
- promotion / demotion count
- event/decision overhead
- number of tiers actually serving accesses

## Important modeling boundary

The simulator has workload ground truth (`DataObject.data_class`) so it can compute
physical access cost and generate C2 type-aware metadata. C1 policy code does **not**
receive that field through its registry. This separation is deliberate and tested.

### Scenario change from the legacy evaluator

The old C2 included a DataClassifier and therefore had `classifier_error` / `misclass_rate` fault injection. The current C2 registry is type-aware, so type misclassification is no longer the relevant failure mode. The port replaces that case with abrupt hotness/behavior shifts to measure prediction lag, mis-placement and thrashing.


## What was not ported from legacy `dp1_sim`

- `PlacementPolicy.place()` and initial-placement scoring
- KV-only `SessionBlockSet` / agent tool turn decision points
- tool execution time prediction as a DP1 signal
- `DataClassifier` misclassification fault injection

The reusable parts are the heterogeneous-memory cost assumptions, transfer-cost accounting, deterministic trace principle, and QA measurement patterns. Agent tool lifecycle-aware KV residency belongs to a separate DP rather than this generic migration simulator.
