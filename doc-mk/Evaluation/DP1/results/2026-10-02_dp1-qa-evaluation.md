---
date: 2026-10-02
dp: DP1
candidates: [C1-resource-driven, C2-behavior-driven]   # Baseline-static 포함
sys_ids: [SYS-4, SYS-1, SYS-2, SYS-3, SYS-5]
git_rev: cfa8e6d (dirty)
evidence: { QA1: "[B+C]", QA2: "[B+C]", QA3: "[B+C]", QA4: "[C]" }
status: draft
---

# DP1 QA Evaluation — C1 vs C2 (Common + DP1 Stress + DP1 Dynamic, Baseline-regression loop 반영)

> 기준 문서: [`qa-evaluation-criteria.md`](../../qa-evaluation-criteria.md), [`common-benchmark.md`](../../common-benchmark.md), [`system-specs.md`](../../system-specs.md), [`DP1/benchmark.md`](../benchmark.md), [`DP1/simulation-plan.md`](../simulation-plan.md)
> 절차: `.claude/skills/evaluation/SKILL.md`
> 이 문서의 모든 simulation 수치는 Evidence [B+C]이며 [A] 실측이 아니다. 표는 `tools/gen_dp1_result.py`가 `results/data/SYS-*/qa_result.json`에서 생성했다.
> 이 문서는 [`2026-10-02_first-pass_superseded.md`](2026-10-02_first-pass_superseded.md)를 대체한다.

# 1. 시스템 환경

| 항목 | 값 |
|---|---|
| SYS id | **SYS-4** (primary, B200x8 + 6개 memory 전부), SYS-1 (HBM+DRAM, As-Is class), SYS-2 (+CXL-PNM), SYS-3 (+HBF), SYS-5 (Vera Rubin x8 + 6개 memory) |
| Model / precision | Llama-3.1-70B, BF16 (`models.json`) |
| Git revision | cfa8e6d (dirty) |
| Seeds / loads | seeds 11, 23, 37, 53, 71 (5회) / load x0.5, x1.0, x1.5, x2.0, 95% CI t=2.776 |
| Tie 판정 | goodput 상대 차이 < 1% 또는 95% CI 이내이면 tie ("material" 임계 1%는 이 평가의 임시 상수) |
| 재현 command | `cd doc-mk/Evaluation/DP1/sim && python3 test_sim.py && python3 loop_run.py --final` (SYS-1~5), 단일: `python3 qa_eval.py --system SYS-4` |
| 표 생성 | `python3 doc-mk/Evaluation/tools/gen_dp1_result.py` |
| Raw data | `DP1/results/data/SYS-{1..5}/qa_result.json`, `sensitivity_SYS-4.json` |

시스템 profile 상세: [system-specs.md](../../system-specs.md). SYS-5의 Custom HBM은 이번 평가 중 loader를 고쳐(paired-GPU 상대 규격: 용량 x2, 내부 BW x2, 연산 20%, TDP/3) Vera Rubin 기준 값(약 715 GiB, 56 TB/s, 1,665 TFLOPS)으로 계산했다. 이전에는 B200 기준 값으로 잘못 고정되어 있었다.

# 2. 평가 항목

| 항목 | 정의 / formula | 출처 |
|---|---|---|
| QA1 Max SLO Goodput | load sweep(x0.5~2.0) 중 SLO를 만족한 output token/s의 최대값. 시나리오별로 Baseline 대비 비율을 구하고 시나리오 간 **geometric mean**으로 집계. 별점은 criteria §4.3 (< 0.90 ★, 0.90~1.10 ★★, >= 1.10 ★★★) | criteria §4 |
| QA2 Latency | Max goodput load point의 TTFT P99 / TPOT P99. 시나리오 중 **worst-case**로 집계, 별점은 criteria §5 (≤2 s & ≤50 ms ★★★ / ≤4 s & ≤100 ms ★★ / 그 외 ★) | criteria §5 |
| QA3 Useful Utilization | `avg HBM occupancy x (SLO 만족 token / served token)`. 별점은 criteria §6 (< 65% ★, 65~85% ★★, >= 85% ★★★) | **임시 정의** (criteria에 formula 없음) |
| QA4 Modifiability | 신규 memory / data type / policy / event 추가 시 변경 module 수 (§5) | criteria §7, architecture argument [C] |
| 집계 범위 | "feasible" = Baseline goodput > 0 (comparison-valid + saturated). Combined는 3개 set 합산. "discriminating" = comparison-valid만 | 본 평가 정의 |
| Diagnostic | migration 횟수/bytes/time, decision overhead, tier별 access, SLO 만족률 | DP1 전용 |

# 3. 벤치마크 / 시나리오

최종 결과는 **Common Benchmark + DP1 Stress Benchmark + DP1 Dynamic Benchmark**를 모두 합친 것이다.

- **Common**: 공통 profile(8K in / 256 out, Llama-3.1-70B BF16)의 DP1 realization 3개. HBM을 줄여 계층이 영향을 주게 했다.
- **DP1 Stress**: 기존 23개 (resource pressure / data behavior / mixed AI data / stability).
- **DP1 Dynamic**: Baseline-regression loop(iteration 2)에서 추가한 시나리오와 controls. **Baseline은 SLO를 만족하지만 static 배치가 runtime에 stale해지는** 패턴을 대상으로 한다.

Fit label: **V** = comparison-valid (Baseline이 SLO 만족), **I** = infeasible (Baseline도 SLO 불가, 비교 제외하되 목록 유지), **S** = saturated (모든 후보가 CI 안에서 동일, 판별 불가). SYS별로 label이 달라질 수 있다.

| Set | 시나리오 | SYS-1 | SYS-2 | SYS-3 | SYS-4 | SYS-5 | 설명 (실제 serving 패턴 / As-Is 약점) |
|---|---|---|---|---|---|---|---|
| Common | `cb_kv_8k_b32` | S | S | V | V | V | Common benchmark: KV only, 8K/256, batch 32, tight HBM. |
| Common | `cb_kv_8k_b32_ramp` | S | S | V | V | V | Common benchmark: KV only, progressive HBM pressure. |
| Common | `cb_mixed_8k_b32` | S | S | V | V | V | Common benchmark: KV + LoRA + MoE + Agent/Tool data, tight HBM. |
| DP1 Stress | `kv_b1_c32k_cold_cxl` | V | V | V | V | V | Cold latency-tolerant KV while Custom-HBM is reserved/unavailable; validates CXL-PNM Attention path. |
| DP1 Stress | `kv_b16_c32k` | S | S | S | S | S | KV baseline: moderate batch/context. |
| DP1 Stress | `kv_b16_c32k_burst_chbm` | S | S | V | V | S | Burst at a batch/context where HBM headroom is tight and Custom-HBM Attention can still meet TPOT. |
| DP1 Stress | `kv_hbm_relief_behavior_recovery` | S | S | V | V | V | HBM starts pressured and then recovers; tests whether C2 can promote behaviorally hot KV while C1 remains resource-triggered. |
| DP1 Stress | `kv_b64_c128k_cold` | I | I | I | I | V | Cold/latency-tolerant KV; CXL-PNM attention offload can be useful. |
| DP1 Stress | `kv_b256_c128k_burst` | I | I | I | I | I | Large-batch burst; tests Custom-HBM attention offload and shared-link pressure. |
| DP1 Stress | `kv_b64_c512k_long` | I | I | I | I | I | Long-context KV pressure at large batch. |
| DP1 Stress | `kv_b256_c512k_stress` | I | I | I | I | I | Heavy cell: batch 256 × 512K context. |
| DP1 Stress | `rag_1tib_b16` | S | S | S | S | V | 1 TiB read-mostly vector index; retrieval locality changes. |
| DP1 Stress | `rag_8tib_b64_ssd_pim` | S | S | S | S | V | 8 TiB cold/long-lived vector DB, 64 concurrent queries; SSD-PIM dot-product path. |
| DP1 Stress | `rag_8tib_b256_ssd_pim` | I | I | I | I | V | Heavy RAG: 8 TiB vector DB, 256 concurrent queries. |
| DP1 Stress | `kv_rag_b64_c128k` | I | I | I | I | S | KV decode plus large RAG index at batch/query concurrency 64. |
| DP1 Stress | `agent_memory_long_lived` | V | V | V | V | V | Long-lived episodic/semantic Agent Memory with sparse reuse. |
| DP1 Stress | `tool_result_bursty` | S | S | S | S | V | Bursty tool/agent-state results reused over multiple steps. |
| DP1 Stress | `lora_multi_tenant_b64` | I | I | I | I | V | Multi-LoRA serving with popularity skew. |
| DP1 Stress | `moe_expert_skew_b256` | I | I | I | I | I | MoE routing skew under large batch. |
| DP1 Stress | `mixed_all_ai_data_b64` | I | I | I | I | S | All primary DP1 AI data classes coexist. |
| DP1 Stress | `hbm_pressure_ramp_b64` | I | I | I | I | S | Progressive HBM pressure with KV/LoRA/MoE. |
| DP1 Stress | `hbm_bw_shock_b256` | I | I | I | I | I | Sudden HBM bandwidth shock at batch 256. |
| DP1 Stress | `host_path_pressure_b64` | I | I | I | I | S | CPU/PCIe contention with RAG/Agent/Tool data. |
| DP1 Stress | `data_mix_shift_b64` | I | I | I | I | S | Workload shifts from KV/LoRA to RAG/Agent. |
| DP1 Stress | `behavior_flip_stress` | S | S | S | S | S | Abrupt per-object hotness inversion; stresses C2 prediction lag/thrashing while C1 reacts only to resource pressure. |
| DP1 Stress | `six_tier_capacity_stress` | I | I | I | I | V | Capacity ladder intentionally exercises all six memories. |
| DP1 Dynamic | `dyn_cold_resident_chat_wave` | V | V | V | V | S | Serving pattern: long-lived Agent Memory (episodic state kept warm for idle tenants) is loaded at start-up and fills HBM first-come-first-served; at t=20-30 s an interactive long-context chat wave arrives. As-Is failure mode: the new hot KV sessions land in host DRAM (HBM is full of cold data) and are never promoted, so every turn pays the host-link restore. |
| DP1 Dynamic | `dyn_idle_kv_holds_hbm` | V | V | V | V | S | Serving pattern: agent sessions blocked on slow tool calls keep their KV resident (idle, rate x0.05) and hold HBM; at t=30-40 s the tool results return / new sessions arrive and become the hot set. As-Is failure mode: arrival order decided HBM residency; hot sessions are served from DRAM while idle sessions sit in HBM. All objects are the same data class, so only per-object behavior tells them apart. |
| DP1 Dynamic | `dyn_kv_hotset_recency_shift` | V | V | V | V | S | Serving pattern: working-set drift. Conversations created first are hot in the first half (HBM residents by first-come placement); at t=90 s users move on: the early sessions go cold (x0.1) and the later sessions (resident in DRAM) become hot (x3). As-Is failure mode: placement frozen at the old working set; post-shift traffic is served from DRAM. |
| DP1 Dynamic | `dyn_kv_rotating_hotset` | V | V | V | V | V | Serving pattern: three user groups active in turn (60 s windows, e.g. shift/time-zone hand-over); the active group is hot (x3), the others near idle (x0.1). As-Is failure mode: placement fits only the first window; in later windows the active group is in DRAM. Also probes anti-thrashing: the hot set moves every 60 s. |
| DP1 Dynamic | `dyn_rag_shard_hotset_shift` | V | V | V | V | V | Serving pattern: GPU-resident vector-index shards (8 x ~32 GiB). Query popularity shifts at t=90 s (trending topic / newly ingested documents): the first shards (HBM residents) cool down, the later shards (host DRAM) become hot. As-Is failure mode: the hot shards are scanned from DRAM (full index crosses the host link per query). |
| DP1 Dynamic | `dyn_host_path_contention_kv` | V | V | V | V | V | Serving pattern: host-side contention (co-located checkpoint / dataloader / NIC traffic on the shared PCIe root) cuts host-link bandwidth to 25% from t=90 s. 128K-context KV that spilled to DRAM was fine before. As-Is failure mode: static tier order keeps the spilled sessions on the degraded path. |

# 4. 결과

## 4.1 최종 QA 표 (SYS-4, Common + DP1 Stress + DP1 Dynamic 통합)

집계는 Baseline goodput > 0인 시나리오(V + S)이다. QA2 worst-case는 Baseline 자체가 SLO를 못 맞추는 시나리오가 지배할 수 있어 별점이 모두 ★로 나올 수 있다 (set별 값 참조).

| Set (n) | QA | Baseline (T_ref) | C1 | C2 |
|---|---|---|---|---|
| **Common** (3) | QA1 Throughput | ★★ 3,272 tps (x1.000) [B+C] | ★★ x1.000 [B+C] | ★★ x1.000 [B+C] |
| | QA2 Latency (worst) | ★★★ 337 ms / 5 ms [B+C] | ★★★ 263 ms / 5 ms [B+C] | ★★★ 324 ms / 5 ms [B+C] |
| | QA3 Util. (임시 정의) | ★ 44% [B+C] | ★ 41% [B+C] | ★ 59% [B+C] |
| **DP1 Stress** (9) | QA1 Throughput | ★★ 370 tps (x1.000) [B+C] | ★★ x1.000 [B+C] | ★★ x1.037±0.066 [B+C] |
| | QA2 Latency (worst) | ★ 793,052 ms / 14 ms [B+C] | ★ 793,052 ms / 14 ms [B+C] | ★ 793,052 ms / 14 ms [B+C] |
| | QA3 Util. (임시 정의) | ★ 31% [B+C] | ★ 31% [B+C] | ★ 34% [B+C] |
| **DP1 Dynamic** (6) | QA1 Throughput | ★★ 120 tps (x1.000) [B+C] | ★★★ x1.643±0.285 [B+C] | ★★★ x2.211±0.078 [B+C] |
| | QA2 Latency (worst) | ★ 9,567 ms / 63 ms [B+C] | ★★ 2,138 ms / 62 ms [B+C] | ★★ 2,160 ms / 62 ms [B+C] |
| | QA3 Util. (임시 정의) | ★ 30% [B+C] | ★ 48% [B+C] | ★★ 69% [B+C] |
| **Combined (3 set 통합)** (18) | QA1 Throughput | ★★ 770 tps (x1.000) [B+C] | ★★★ x1.180±0.066 [B+C] | ★★★ x1.327±0.042 [B+C] |
| | QA2 Latency (worst) | ★ 793,052 ms / 63 ms [B+C] | ★ 793,052 ms / 62 ms [B+C] | ★ 793,052 ms / 62 ms [B+C] |
| | QA3 Util. (임시 정의) | ★ 33% [B+C] | ★ 39% [B+C] | ★ 50% [B+C] |
| **QA4 Modifiability** | | — | ★★★ [C] | ★★ [C] |

(n = 집계된 시나리오 수. ratio의 ± 값은 95% CI. `qa_discriminating`(V만) 기준은 `qa_result.json` 참조)

## 4.2 시나리오별 결과 (SYS-4)

n_seeds = 5, 95% CI는 t 분포, V/I/S = Fit, ratio = 후보 / Baseline (Baseline goodput = 0이면 n/a).

### 4.2.1 Common

| 시나리오 | Fit | Baseline (±CI) tok/s | C1 (ratio) | C2 (ratio) | TTFT P99 B/C1/C2 (ms) | TPOT P99 B/C1/C2 (ms) | C1 / C2 vs Baseline |
|---|---|---:|---:|---:|---|---|---|
| cb_kv_8k_b32 | V | 3,578 (±192) | 3,578 (x1.00) | 3,578 (x1.00) | 337 / 250 / 324 | 5 / 5 / 5 | tie / tie |
| cb_kv_8k_b32_ramp | V | 3,595 (±41) | 3,595 (x1.00) | 3,595 (x1.00) | 318 / 239 / 183 | 5 / 5 / 4 | tie / tie |
| cb_mixed_8k_b32 | V | 2,641 (±308) | 2,641 (x1.00) | 2,641 (x1.00) | 329 / 263 / 263 | 5 / 5 / 5 | tie / tie |

### 4.2.2 DP1 Stress

| 시나리오 | Fit | Baseline (±CI) tok/s | C1 (ratio) | C2 (ratio) | TTFT P99 B/C1/C2 (ms) | TPOT P99 B/C1/C2 (ms) | C1 / C2 vs Baseline |
|---|---|---:|---:|---:|---|---|---|
| agent_memory_long_lived | V | 297 (±19) | 297 (x1.00) | 297 (x1.00) | 52 / 52 / 53 | 14 / 14 / 14 | tie / tie |
| behavior_flip_stress | S | 774 (±81) | 774 (x1.00) | 774 (x1.00) | 67 / 67 / 67 | 5 / 5 / 5 | tie / tie |
| data_mix_shift_b64 | I | 0 (±0) | 0 (n/a) | 0 (n/a) | 84,131 / 82,959 / 81,009 | 61 / 61 / 53 | n/a / n/a |
| hbm_bw_shock_b256 | I | 0 (±0) | 0 (n/a) | 0 (n/a) | 110 / 110 / 111 | 686 / 686 / 686 | n/a / n/a |
| hbm_pressure_ramp_b64 | I | 0 (±0) | 0 (n/a) | 0 (n/a) | 110 / 110 / 111 | 50 / 50 / 50 | n/a / n/a |
| host_path_pressure_b64 | I | 0 (±0) | 0 (n/a) | 0 (n/a) | 67,014 / 67,014 / 18,856 | 50 / 50 / 50 | n/a / n/a |
| kv_b16_c32k | S | 539 (±53) | 539 (x1.00) | 539 (x1.00) | 52 / 52 / 52 | 5 / 5 / 5 | tie / tie |
| kv_b16_c32k_burst_chbm | V | 954 (±59) | 954 (x1.00) | 954 (x1.00) | 331 / 240 / 162 | 10 / 8 / 6 | tie / tie |
| kv_b1_c32k_cold_cxl | V | 29 (±3) | 29 (x1.00) | 29 (x1.00) | 52 / 52 / 53 | 3 / 3 / 3 | tie / tie |
| kv_b256_c128k_burst | I | 0 (±0) | 0 (n/a) | 0 (n/a) | 110 / 110 / 111 | 195 / 195 / 195 | n/a / n/a |
| kv_b256_c512k_stress | I | 0 (±0) | 0 (n/a) | 0 (n/a) | 13,406 / 13,406 / 13,406 | 125,863 / 125,863 / 125,863 | n/a / n/a |
| kv_b64_c128k_cold | I | 0 (±0) | 0 (n/a) | 0 (n/a) | 110 / 110 / 111 | 50 / 50 / 50 | n/a / n/a |
| kv_b64_c512k_long | I | 0 (±0) | 0 (n/a) | 0 (n/a) | 3,344 / 3,344 / 3,344 | 39,273 / 39,273 / 39,273 | n/a / n/a |
| kv_hbm_relief_behavior_recovery | V | 192 (±15) | 192 (x1.00) | 192 (x1.00) | 343 / 330 / 173 | 10 / 10 / 7 | tie / tie |
| kv_rag_b64_c128k | I | 0 (±0) | 0 (n/a) | 0 (n/a) | 168,798 / 168,798 / 168,798 | 5,917 / 5,917 / 52 | n/a / n/a |
| lora_multi_tenant_b64 | I | 0 (±0) | 0 (n/a) | 0 (n/a) | 110 / 110 / 112 | 50 / 50 / 50 | n/a / n/a |
| mixed_all_ai_data_b64 | I | 0 (±0) | 0 (n/a) | 0 (n/a) | 110,027 / 108,859 / 82,159 | 61 / 61 / 54 | n/a / n/a |
| moe_expert_skew_b256 | I | 0 (±0) | 0 (n/a) | 0 (n/a) | 110 / 110 / 112 | 195 / 195 / 195 | n/a / n/a |
| rag_1tib_b16 | S | 268 (±26) | 268 (x1.00) | 268 (x1.00) | 83 / 83 / 83 | 5 / 5 / 5 | tie / tie |
| rag_8tib_b256_ssd_pim | I | 0 (±0) | 0 (n/a) | 0 (n/a) | 3,028,506 / 3,028,506 / 3,028,506 | 52 / 52 / 52 | n/a / n/a |
| rag_8tib_b64_ssd_pim | S | 38 (±25) | 38 (x1.00) | 52 (x1.39) | 793,052 / 793,052 / 793,052 | 14 / 14 / 14 | tie / tie |
| six_tier_capacity_stress | I | 0 (±0) | 0 (n/a) | 0 (n/a) | 168,617 / 168,617 / 168,617 | 7,881 / 5,938 / 2,083 | n/a / n/a |
| tool_result_bursty | S | 242 (±20) | 242 (x1.00) | 242 (x1.00) | 52 / 52 / 52 | 14 / 14 / 14 | tie / tie |

### 4.2.3 DP1 Dynamic

| 시나리오 | Fit | Baseline (±CI) tok/s | C1 (ratio) | C2 (ratio) | TTFT P99 B/C1/C2 (ms) | TPOT P99 B/C1/C2 (ms) | C1 / C2 vs Baseline |
|---|---|---:|---:|---:|---|---|---|
| dyn_cold_resident_chat_wave | V | 107 (±18) | 197 (x1.83) | 183 (x1.70) | 2,200 / 1,964 / 2,160 | 63 / 59 / 62 | win / win |
| dyn_host_path_contention_kv | V | 245 (±37) | 338 (x1.38) | 337 (x1.38) | 3,176 / 1,386 / 1,393 | 62 / 34 / 33 | win / win |
| dyn_idle_kv_holds_hbm | V | 46 (±19) | 68 (x1.48) | 130 (x2.82) | 2,104 / 2,104 / 2,104 | 62 / 62 / 62 | tie / win |
| dyn_kv_hotset_recency_shift | V | 109 (±44) | 122 (x1.11) | 285 (x2.62) | 2,148 / 2,138 / 2,120 | 62 / 62 / 62 | tie / win |
| dyn_kv_rotating_hotset | V | 167 (±30) | 199 (x1.19) | 284 (x1.70) | 2,127 / 2,082 / 2,120 | 62 / 61 / 62 | tie / win |
| dyn_rag_shard_hotset_shift | V | 48 (±8) | 189 (x3.96) | 190 (x3.97) | 9,567 / 740 / 813 | 5 / 5 / 5 | win / win |

## 4.3 Diagnostic

| 지표 (SYS-4, combined 평균) | Baseline | C1 | C2 |
|---|---:|---:|---:|
| migration 횟수 | 0 | 4 | 58 |
| migration bytes (GiB) | 0 | 110 | 1,239 |
| decision overhead (ms/run) | 0.0 | 2.8 | 105.3 |
| dynamic set 평균 migration bytes (GiB) | 0 | 195 | 2,345 |

## 4.4 시스템 간 비교 (combined, win/tie/loss는 95% CI 유의성 기준)

| SYS | 구성 | QA1 combined C1 | QA1 combined C2 | C1 win/tie/loss | C2 win/tie/loss | dynamic set: C1 / C2 win |
|---|---|---|---|---|---|---|
| SYS-1 | B200x8 + host DRAM (As-Is class) | ★★ x1.049±0.025 | ★★★ x1.149±0.044 | 1/17/0 | 6/12/0 | 1 / 6 (of 6) |
| SYS-2 | B200x8 + DRAM + CXL-PNM | ★★ x1.049±0.022 | ★★★ x1.149±0.044 | 1/17/0 | 6/12/0 | 1 / 6 (of 6) |
| SYS-3 | B200x8 + DRAM + HBF | ★★★ x1.182±0.073 | ★★★ x1.303±0.015 | 3/15/0 | 6/12/0 | 3 / 6 (of 6) |
| SYS-4 | B200x8 + all six memories | ★★★ x1.180±0.066 | ★★★ x1.327±0.042 | 3/15/0 | 6/12/0 | 3 / 6 (of 6) |
| SYS-5 | Vera Rubin x8 + all six memories | ★★ x1.005±0.002 | ★★ x1.026±0.012 | 2/25/0 | 4/23/0 | 1 / 1 (of 6) |

## 4.5 Iteration summary

Baseline-regression loop가 발동했다 (first-pass에서 두 후보 모두 Baseline 이하). iteration 3에서 중단 조건 (i) 충족. 상세 로그: [iterations/loop-log.md](iterations/loop-log.md).

| Iteration | Class | Change | Effect (SYS-4, 전체 benchmark 기준) |
|---|---|---|---|
| 0 (initial) | 계측 + M | `qa_eval.py` 확장(3 set, fit label, win/tie/loss), 전송이 destination write BW를 따르도록 수정 | C1 combined x0.957 (5 loss, Common TPOT 311 ms), C2 x0.961 (4 loss) |
| 1 | P | 공통 access-cost estimator, SLO filter와 do-no-harm(C1 destination 선택), link-time migration budget, cooldown, C2 benefit-vs-cost gating, C2 demotion은 HBM pressure일 때만 | C1 x1.000 / C2 x1.028, **loss 0**, win 0 (Common/Stress는 parity) |
| 2 | B | `dynamic_benchmark()` 6개 + controls 추가 (policy 불변) | dynamic: C1 x1.106 (win 1), C2 x2.211 (win 6) |
| 3 | P | C1 promotion path (설계 §17.2): static 추정으로 SLO를 위반하는 object를 HBM으로 승격, HBM 거주 object와 swap, budget 예약 | dynamic: C1 x1.643 (win 3), C2 불변 |

# 5. 결과 분석

## 5.1 first-pass에서 Baseline보다 낮았던 이유 (iteration 0 진단, SYS-4)

| 시나리오 | 후보 < Baseline? | Root cause | Class | 근거 diagnostic |
|---|---|---|---|---|
| Common (`cb_*`) | C1 (x0.86~0.93), C2 (x1.00) | C1 Destination Tier Selector가 destination의 **serving 비용을 보지 않아** CXL-PNM attention 경로(TPOT 311 ms)를 선택, HBM이 아니라 DRAM pressure에 반응해 6개 tier로 rebalance | P | `diagnose.py`: HBM util 0.38인데 migration 105건 전부 rebalance, CXL-PNM access 147 |
| Common, RAG 시나리오 | C2 | **migration budget 없음**. 대형 object(RAG 3.4 TiB) 이동이 stall을 만들어 TTFT P99 34 s. demotion이 upper-tier pressure를 확인하지 않음(설계 §17.3 위반) | P | migration 342~389건, 3.7 TiB, decision overhead 약 140 ms/run |
| Common 전체 | 둘 다 이득 불가 | Baseline SLO 만족률이 3개 시나리오 모두 1.00이라 후보가 tie 이상을 낼 수 없음 | B | baseline slo_ratio = 1.00 |
| Stress 14/23 (SYS-4) | 비교 불가 | Baseline도 SLO 불가 (512K context, 8 TiB RAG, batch 256 등) | B | Fit = I |

## 5.2 Dynamic Benchmark에서 이득이 나는 이유 (SYS-4, 최종)

| 시나리오 | C1 / C2 vs Baseline | Baseline SLO 만족률 | 후보 migration GiB (C1 / C2) | 원인 (시나리오가 재현하는 As-Is 약점) | Class |
|---|---|---:|---|---|---|
| dyn_cold_resident_chat_wave | win (x1.83) / win (x1.70) | 0.47 | 401 / 3,224 | Serving pattern: long-lived Agent Memory (episodic state kept warm for idle tenants) is loaded at start-up and fills HBM first-come-first-served; at t=20-30 s an interactive long-context chat wave arrives. As-Is failure mode: the new hot KV sessions land in host DRAM (HBM is full of cold data) and are never promoted, so every turn pays the host-link restore. | B (벤치마크가 As-Is 약점을 드러냄) |
| dyn_host_path_contention_kv | win (x1.38) / win (x1.38) | 0.71 | 175 / 2,474 | Serving pattern: host-side contention (co-located checkpoint / dataloader / NIC traffic on the shared PCIe root) cuts host-link bandwidth to 25% from t=90 s. 128K-context KV that spilled to DRAM was fine before. As-Is failure mode: static tier order keeps the spilled sessions on the degraded path. | B (벤치마크가 As-Is 약점을 드러냄) |
| dyn_idle_kv_holds_hbm | tie (x1.48) / win (x2.82) | 0.29 | 106 / 2,568 | Serving pattern: agent sessions blocked on slow tool calls keep their KV resident (idle, rate x0.05) and hold HBM; at t=30-40 s the tool results return / new sessions arrive and become the hot set. As-Is failure mode: arrival order decided HBM residency; hot sessions are served from DRAM while idle sessions sit in HBM. All objects are the same data class, so only per-object behavior tells them apart. | B (벤치마크가 As-Is 약점을 드러냄) |
| dyn_kv_hotset_recency_shift | tie (x1.11) / win (x2.62) | 0.31 | 70 / 2,210 | Serving pattern: working-set drift. Conversations created first are hot in the first half (HBM residents by first-come placement); at t=90 s users move on: the early sessions go cold (x0.1) and the later sessions (resident in DRAM) become hot (x3). As-Is failure mode: placement frozen at the old working set; post-shift traffic is served from DRAM. | B (벤치마크가 As-Is 약점을 드러냄) |
| dyn_kv_rotating_hotset | tie (x1.19) / win (x1.70) | 0.38 | 153 / 1,807 | Serving pattern: three user groups active in turn (60 s windows, e.g. shift/time-zone hand-over); the active group is hot (x3), the others near idle (x0.1). As-Is failure mode: placement fits only the first window; in later windows the active group is in DRAM. Also probes anti-thrashing: the hot set moves every 60 s. | B (벤치마크가 As-Is 약점을 드러냄) |
| dyn_rag_shard_hotset_shift | win (x3.96) / win (x3.97) | 0.26 | 265 / 1,789 | Serving pattern: GPU-resident vector-index shards (8 x ~32 GiB). Query popularity shifts at t=90 s (trending topic / newly ingested documents): the first shards (HBM residents) cool down, the later shards (host DRAM) become hot. As-Is failure mode: the hot shards are scanned from DRAM (full index crosses the host link per query). | B (벤치마크가 As-Is 약점을 드러냄) |

- C2는 object별 behavior(access rate, reuse, idle)를 쓰므로 같은 data class 안의 hot/cold를 구분한다. 그래서 6개 전부에서 유의하게 이긴다.
- C1은 data type을 모르고 static hint(operation class, shape)와 resource 상태만 쓴다. **object별 hot/cold를 구분해야 하는 KV-only 시나리오 3개(idle / recency / rotating)에서는 tie**이다 (ratio가 1.1~1.5배로 보이나 95% CI 이내). 같은 data class 안의 object를 C1이 구분할 근거가 없기 때문이다.
- C1이 이기는 3개는 Agent Memory + KV 혼합(`dyn_cold_resident_chat_wave`), 단일 class RAG shard(`dyn_rag_shard_hotset_shift`), host path 경합(`dyn_host_path_contention_kv`)이다. 이 세 시나리오에서 이기는 정확한 메커니즘은 loop-log iteration 3 진단을 따른다 (본 문서는 추측하지 않는다).
- C1은 훨씬 적게 옮긴다 (dynamic 평균 migration bytes는 4.3의 표 참조).

## 5.3 Baseline 미만 시나리오 (최종 코드)

SYS-1~SYS-5, 3개 set 전체에서 **어느 후보도 Baseline 미만(loss)인 시나리오가 없다** (4.4의 loss 열). SYS-5에서는 Vera Rubin의 큰 HBM 덕분에 Baseline이 dynamic 시나리오를 대부분 감당하여(`saturated`) C1/C2가 `dyn_host_path_contention_kv` 정도에서만 이긴다.

## 5.4 Sensitivity (iteration 3 이후 보고, 파라미터 재조정 아님; `results/data/sensitivity_SYS-4.json`)

- migration budget이 가장 민감하다. link share 0.10 또는 bucket window 4 s이면 후보당 win이 1~2개로 줄어 중단 조건 (i)이 충족되지 않는다. 0.50 또는 16 s이면 6개 모두 win이다.
- benefit horizon, C1 affinity margin은 거의 영향이 없다.
- 어느 변형에서도 loss는 나오지 않았다.

# 6. 한계

1. **Evidence가 [A]가 아니다.** 모든 수치는 config parameter(SPEC/PUBLIC/ASSUMED 혼재) 기반 simulation이다. vLLM trace replay, A100/H100 calibration이 없다.
2. **비용 추정이 완벽하다.** 정책의 access-cost estimator가 simulator와 같은 식을 쓴다 (테스트로 일치 확인). 실제 [A] 측정으로 보정한 추정은 오차가 있어 이득은 **상한에 가깝다.**
3. **Dynamic 시나리오는 실패 모드를 알고 설계했다.** Baseline만 돌려 설계하고 후보 실행 전에 고정했지만, 시나리오 선택이 결과를 좌우한다. 이득은 "static 배치가 stale해지는 경우"에 한정된 결과이며 일반 이득이 아니다. KV dynamic은 320K context, batch 16 셀(DRAM serving이 TPOT SLO를 못 맞추는 구성)이라 Llama-3.1 공식 context(128K)를 넘는다.
4. **정책 상수는 근거 데이터가 없는 설계 선택이다.** LINK_SHARE 0.25, window 8 s, horizon 30 s, affinity margin 2.0. sensitivity에서 budget이 결과를 크게 바꾼다 (5.4).
5. **미모델링:** capacity ramp(hard capacity limit 없음), HBM BW shock(offload가 건강한 HBM을 이길 수 없음), migration 간섭(단일 0.20 계수), HBF endurance, queueing/saturation(QA1이 load에 거의 비례). 개정된 **Memory Backend I/F 구조는 구현하지 않았다** (decision 로직은 기존 C1/C2, 개정 구조는 QA4에만 반영). DROP action은 이 평가에 포함하지 않았다.
6. **임시 정의:** QA3 formula, tie 판정의 1% material 임계, "saturated" fit label(모든 후보 CI 이내 동일).
7. **QA2 집계가 worst-case**라 Baseline 자체가 SLO를 못 맞추는 시나리오가 있는 set에서는 모든 후보가 ★로 나온다 (Stress set).
8. **SYS-5의 Custom HBM**은 평가 중 loader 수정 후의 값이며, 이전 first-pass 결과(SYS-5)와 비교할 수 없다.

# 7. 결론

- **현재 simulator 기준으로 C1, C2는 모든 시스템·모든 benchmark에서 Baseline 이상이다** (loss 0). first-pass의 Baseline 미만 결과는 정책 결함(P: serving 비용 무시, migration budget 없음)과 benchmark 부적합(B)에서 왔고 iteration 1~3에서 해소되었다.
- **이득은 "static 배치가 runtime에 stale해지는" 조건에서만 확인된다.** Common과 feasible Stress에서는 둘 다 Baseline과 동률이다. SYS-4 Dynamic에서 C2는 6/6, C1은 3/6 시나리오에서 유의하게 이긴다. 그 외는 parity다. 이것은 일반 이득 주장이 아니다.
- **C2 vs C1:** C2의 성능 이득이 크고 C1은 훨씬 적은 byte를 옮긴다. Modifiability는 C1이 우위다 (★★★ vs ★★). 같은 data class 안의 hot/cold 구분이 필요한 workload에서는 C1이 구조적으로 이기지 못한다.
- **다음 단계:** (1) Destination Tier Selector의 serving-cost 입력, link-time migration budget, C2 benefit-vs-cost gating, C1 promotion 경로를 설계 문서에 반영한다 (loop-log '설계 문서에 미치는 영향'). (2) vLLM trace 수집과 HBM↔DRAM 실측으로 access-cost 모델의 오차를 [A]로 확인하고, 오차를 넣은 estimator로 재평가한다. (3) budget 파라미터 근거 확보. (4) 개정 구조(Backend I/F, snapshot)를 simulator에 반영한다.

## QA4 — Modifiability (architecture argument, [C])

| 변경 시나리오 | C1 변경 module | C2 변경 module |
|---|---|---|
| 신규 memory 추가 | Backend plug-in 1 (+ TransferHandler 1) = ≤2 → ★★★ | 동일 ≤2 → ★★★ (선호 tier를 capability class로 둘 때) |
| 신규 AI data type 추가 | Affinity/hint 항목 1~2 (Registry는 type-agnostic이라 무변경) → ★★★ | class metadata + Behavior Monitor feature + Predictor input + Destination 선호 = 4 → ★★ |
| 신규 정책 교체 | 1 → ★★★ | 1 → ★★★ |
| 신규 event type | 2 → ★★★ | 2 → ★★★ |

종합 C1 ★★★ / C2 ★★ [C]. loop에서 추가된 access-cost estimator와 migration budget은 두 후보가 **공유하는 module**이라 후보 간 QA4 차이를 바꾸지 않는다 (신규 memory 추가 시 estimator의 입력 descriptor만 갱신).
