# DP1 Benchmark (DP1 맞춤형)

> 대상: **DP1 — AI Data Migration**
>
> 이 문서는 DP1 평가에 쓰는 benchmark scenario 전체를 정의한다. 모든 DP 공통 부분은 `../common-benchmark.md`, QA 정의/별점은 `../qa-evaluation-criteria.md`, 시스템 프로파일은 `../system-specs.md`를 따른다.
>
> **DP1의 최종 결과 = Common Benchmark + 이 문서의 DP1-specific benchmark.** 둘을 함께 제시해야 한다.

---

# 1. DP1 benchmark는 어디에 정의되어 있는가

- **단일 소스(single source of truth)는 `DP1/sim/scenarios.py`** 이다. 시나리오의 숫자(context, batch, knob 등)는 이 코드가 정의한다.
- `simulation-plan.md` 13.2는 시나리오의 **범주**(resource-pressure / data-behavior / mixed / stability)만 나열하며 개별 시나리오를 열거한 적이 없다.
- 이 문서의 4장 표는 `tools/gen_dp1_benchmark_doc.py`가 `scenarios.py`에서 생성한다. 시나리오가 바뀌면 재생성한다.

  ~~~text
  python3 doc-mk/Evaluation/tools/gen_dp1_benchmark_doc.py          # 갱신
  python3 doc-mk/Evaluation/tools/gen_dp1_benchmark_doc.py --check  # 최신 여부 (exit code)
  ~~~

- 시나리오 함수 -> benchmark set 대응:

| Set | 함수 | 목적 |
|---|---|---|
| Common Benchmark realization | `scenarios.common_benchmark()` (`cb_*`) | 공통 QA1/QA2/QA3 rating. 공통 profile을 DP1 simulator에서 실현 |
| DP1 Stress Benchmark | `scenarios.scenarios()` | DP1의 trade-off와 failure mode 관찰 (diagnostic) |
| DP1 Dynamic Benchmark | 추가 예정 (`*_benchmark` 함수) | As-Is 정적 배치가 SLO는 만족하지만 runtime에서 suboptimal이 되는 시나리오 |

# 2. Benchmark set 구조

## 2.1 Common Benchmark realization (`cb_*`)

`common-benchmark.md`의 profile(Llama-3.1-70B BF16, 8K in / 256 out, deterministic, load sweep, SLO TTFT P99 <= 2 s / TPOT P99 <= 50 ms)을 DP1 simulator에서 실현한 것이다. HBM을 `hbm_capacity_mult`로 줄여 메모리 계층이 의미를 갖게 한다 (HBM이 충분하면 모든 후보가 동일하다).

| 시나리오 | 이유 / 탐지하는 As-Is 실패 모드 | 대상 metric |
|---|---|---|
| `cb_kv_8k_b32` | KV만, tight HBM. static placement가 HBM overflow를 DRAM으로 흘릴 때의 TPOT 악화 | QA1, QA2, QA3 |
| `cb_kv_8k_b32_ramp` | 점진적 HBM pressure. 시간에 따라 필요한 배치가 바뀜 | QA1, QA2, pressure relief |
| `cb_mixed_8k_b32` | KV + LoRA + MoE + Agent/Tool 혼합. type-agnostic 관리의 필요성 | QA1~QA3, QA4 근거 |

## 2.2 DP1 Stress Benchmark (기존 23개)

`simulation-plan.md` 13.2 범주 기준. 목적은 별점이 아니라 **failure mode와 trade-off 관찰**이다 (simulation-plan.md 14.2 diagnostic metrics).

| 범주 | 시나리오 | 존재 이유 / As-Is 실패 모드 | 대상 diagnostic |
|---|---|---|---|
| KV decode placement (batch x context 격자) | `kv_b1_c32k_cold_cxl`, `kv_b16_c32k`, `kv_b16_c32k_burst_chbm`, `kv_hbm_relief_behavior_recovery`, `kv_b64_c128k_cold`, `kv_b256_c128k_burst`, `kv_b64_c512k_long`, `kv_b256_c512k_stress` | batch/context에 따라 최적 tier가 달라진다. As-Is는 HBM 부족 시 전량 DRAM 복원(Mode B)으로 떨어짐. cold KV의 CXL-PNM attention, burst 시 cHBM 오프로드, HBM 회복 시 promotion을 검증 | migration count/bytes, pressure relief bytes, eviction churn |
| Resource-pressure | `hbm_pressure_ramp_b64`, `hbm_bw_shock_b256`, `host_path_pressure_b64`, `six_tier_capacity_stress` | HBM capacity ramp, HBM BW pressure, host path(PCIe/CPU) pressure, tier saturation. C1이 pressure/trend를 보고 migration 시점을 올바르게 잡는지 | resource pressure detection, event-to-decision latency, tier imbalance, QA3 |
| RAG / vector index | `rag_1tib_b16`, `rag_8tib_b64_ssd_pim`, `rag_8tib_b256_ssd_pim`, `kv_rag_b64_c128k` | 대용량 read-mostly index의 tier 배치, SSD-PIM GEMV 경로, KV와의 경합 | retrieval latency, tier occupancy, migration BW |
| Other AI data | `agent_memory_long_lived`, `tool_result_bursty`, `lora_multi_tenant_b64`, `moe_expert_skew_b256` | long-lived cold object, suddenly hot object, popularity skew. KV 전용 정책이 다른 data type에서 깨지는지 (type-agnostic registry 검증) | promotion/demotion count, predictor accuracy |
| Mixed AI Data | `mixed_all_ai_data_b64`, `data_mix_shift_b64` | 6종 data class(KV/RAG/Agent/Tool/LoRA/MoE) 공존, 시간에 따른 mix 변화 | QA3, eviction churn |
| Stability | `behavior_flip_stress` | per-object hotness 급반전. C2 prediction lag / repeated promotion-demotion / migration storm | migration storm, thrashing, prediction lag |

> 위 grouping은 시나리오 이름/설명 기반의 해석이다. 정의는 4장 표(코드)가 우선한다.

## 2.3 DP1 Dynamic Benchmark

`scenarios.dynamic_benchmark()` — Baseline-regression loop iteration 2에서 추가한 6개 시나리오와 feasibility controls (표는 4장, 이력은 `results/iterations/loop-log.md`).

설계 원칙: **As-Is 정적 배치가 SLO를 만족하는 초기 상태(Baseline feasible)에서 시작하되, runtime에 workload가 바뀌어 정적 배치가 suboptimal이 되는 패턴**만 쓴다. 각 시나리오의 description에 실제 serving 패턴과 As-Is 약점을 명시한다. Baseline만 돌려 설계하고 후보 실행 전에 고정했다 (cherry-picking 방지). 그래도 **실패 모드를 알고 설계한 시나리오**이므로 이득은 "static 배치가 stale해지는 경우"에 한정된 결과로 읽어야 한다.

| 시나리오 | 재현하는 serving 패턴 |
|---|---|
| `dyn_cold_resident_chat_wave` | idle tenant의 long-lived Agent Memory가 먼저 HBM을 차지, 이후 chat 요청(KV)이 느린 tier로 밀림 |
| `dyn_idle_kv_holds_hbm` | tool call에 막힌 agent session의 KV(idle)가 HBM을 점유, 이후 hot 요청이 도착 |
| `dyn_kv_hotset_recency_shift` | working set drift: 먼저 생성된 대화가 초반에 hot, 이후 최근 대화로 이동 |
| `dyn_kv_rotating_hotset` | 사용자 그룹이 시간대별로 번갈아 활성화(60 s window) |
| `dyn_rag_shard_hotset_shift` | GPU 상주 vector index shard의 인기가 중간에 바뀜 |
| `dyn_host_path_contention_kv` | host PCIe 경합으로 host link BW 저하 |

미포함(시뮬레이터가 모델링하지 못함): capacity ramp(hard capacity limit 없음), HBM BW shock(offload가 건강한 HBM을 이기지 못함). loop-log 한계 참조.

# 3. 규칙

## 3.1 Infeasible 시나리오는 숨기지 않는다

**Common Reference Baseline이 SLO를 전혀 만족하지 못하는 시나리오는 `infeasible-for-comparison`으로 표기해야 하며, 조용히 제외(silently drop)해서는 안 된다.** 결과 문서에 시나리오 목록, baseline 위반 지표(TTFT/TPOT P99), 제외 사유를 남긴다. 후보만 SLO를 만족하는 시나리오는 오히려 중요한 증거이므로 별도 표기한다.

## 3.2 Benchmark-fit 분류

모든 시나리오 x SYS 조합은 결과 문서에서 다음 중 하나로 분류한다.

| Label | 정의 | 사용 |
|---|---|---|
| comparison-valid | Common Reference Baseline이 SLO를 만족 | QA 별점 비교에 사용 (T_ref 기준) |
| infeasible | Baseline이 SLO를 만족하지 못함 | 별점 비교에서 제외, 반드시 flag. 후보의 SLO 달성 여부는 별도 기재 |
| saturated | 모든 후보가 동일한 결과 (차이 없음) | 변별력 없음. 목록에 남기되 별점 근거로 쓰지 않음 |

분류는 SYS id별로 따로 한다 (같은 시나리오도 SYS-1과 SYS-4에서 다를 수 있다). 분류 기준은 결과를 보기 전에 `qa-evaluation-criteria.md`의 SLO를 그대로 쓰며, 결과를 본 뒤 조정하지 않는다.

# 4. 시나리오 표 (generated)

<!-- BEGIN GENERATED -->
> Generated by `doc-mk/Evaluation/tools/gen_dp1_benchmark_doc.py` from `DP1/sim/scenarios.py`. Do not edit by hand.

Knob column lists only non-default knobs (defaults: size_scale=1, horizon_s=180, misclass_rate=0, capacity_mult=1, hbm_bw_mult=1, host_bw_mult=1, hbm_capacity_mult=1). Other non-default fields (e.g. `rag_index_total_gib`, `latency_sensitivity_override`, or fields added later) appear in the Extra column.

| Benchmark set | Function | Scenarios |
|---|---|---|
| Common Benchmark realization (cb_*) | `scenarios.common_benchmark()` | 3 |
| DP1 Stress Benchmark | `scenarios.scenarios()` | 23 |
| dynamic_benchmark | `scenarios.dynamic_benchmark()` | 6 |

## G.1 Common Benchmark realization (cb_*)

| # | name | data mix | ctx | out | batch | objs | demand | phase | knobs | disabled tiers | extra | description |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 1 | `cb_kv_8k_b32` | KV_CACHE:1 | 8K | 256 | 32 | 40 | 1 | - | hbm_capacity_mult=0.12 | - | - | Common benchmark: KV only, 8K/256, batch 32, tight HBM. |
| 2 | `cb_kv_8k_b32_ramp` | KV_CACHE:1 | 8K | 256 | 32 | 40 | 1 | capacity_ramp | hbm_capacity_mult=0.2 | - | - | Common benchmark: KV only, progressive HBM pressure. |
| 3 | `cb_mixed_8k_b32` | KV_CACHE:0.5, LORA_ADAPTER:0.15, MOE_EXPERT:0.15, AGENT_MEMORY:0.1, TOOL_RESULT:0.1 | 8K | 256 | 32 | 48 | 1 | bimodal | hbm_capacity_mult=0.12 | - | - | Common benchmark: KV + LoRA + MoE + Agent/Tool data, tight HBM. |

## G.2 DP1 Stress Benchmark

| # | name | data mix | ctx | out | batch | objs | demand | phase | knobs | disabled tiers | extra | description |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 1 | `kv_b1_c32k_cold_cxl` | KV_CACHE:1 | 32K | 64 | 1 | 24 | 0.15 | cold_kv | - | custom_hbm | latency_sensitivity_override=0.35 | Cold latency-tolerant KV while Custom-HBM is reserved/unavailable; validates CXL-PNM Attention path. |
| 2 | `kv_b16_c32k` | KV_CACHE:1 | 32K | 64 | 16 | 24 | 1 | - | - | - | - | KV baseline: moderate batch/context. |
| 3 | `kv_b16_c32k_burst_chbm` | KV_CACHE:1 | 32K | 64 | 16 | 30 | 1.45 | arrival_burst | hbm_capacity_mult=0.12 | - | latency_sensitivity_override=0.75 | Burst at a batch/context where HBM headroom is tight and Custom-HBM Attention can still meet TPOT. |
| 4 | `kv_hbm_relief_behavior_recovery` | KV_CACHE:1 | 32K | 64 | 16 | 24 | 0.35 | hbm_relief | hbm_capacity_mult=0.12 | - | latency_sensitivity_override=0.55 | HBM starts pressured and then recovers; tests whether C2 can promote behaviorally hot KV while C1 remains resource-triggered. |
| 5 | `kv_b64_c128k_cold` | KV_CACHE:1 | 128K | 64 | 64 | 24 | 0.85 | cold_kv | - | - | - | Cold/latency-tolerant KV; CXL-PNM attention offload can be useful. |
| 6 | `kv_b256_c128k_burst` | KV_CACHE:1 | 128K | 64 | 256 | 28 | 1.35 | arrival_burst | - | - | - | Large-batch burst; tests Custom-HBM attention offload and shared-link pressure. |
| 7 | `kv_b64_c512k_long` | KV_CACHE:1 | 512K | 64 | 64 | 24 | 1 | - | size_scale=1.15 | - | - | Long-context KV pressure at large batch. |
| 8 | `kv_b256_c512k_stress` | KV_CACHE:1 | 512K | 64 | 256 | 30 | 1.2 | - | size_scale=1.2; capacity_mult=0.55 | - | - | Heavy cell: batch 256 × 512K context. |
| 9 | `rag_1tib_b16` | RAG_DATA:1 | 32K | 96 | 16 | 10 | 0.9 | hotness_flip | - | - | rag_index_total_gib=1024 | 1 TiB read-mostly vector index; retrieval locality changes. |
| 10 | `rag_8tib_b64_ssd_pim` | RAG_DATA:1 | 32K | 96 | 64 | 12 | 1 | - | - | - | rag_index_total_gib=8192 | 8 TiB cold/long-lived vector DB, 64 concurrent queries; SSD-PIM dot-product path. |
| 11 | `rag_8tib_b256_ssd_pim` | RAG_DATA:1 | 32K | 96 | 256 | 12 | 1.15 | - | - | - | rag_index_total_gib=8192 | Heavy RAG: 8 TiB vector DB, 256 concurrent queries. |
| 12 | `kv_rag_b64_c128k` | KV_CACHE:0.55, RAG_DATA:0.45 | 128K | 80 | 64 | 30 | 1.1 | - | - | - | rag_index_total_gib=2048 | KV decode plus large RAG index at batch/query concurrency 64. |
| 13 | `agent_memory_long_lived` | AGENT_MEMORY:1 | 32K | 96 | 64 | 28 | 0.9 | - | size_scale=1.7 | - | - | Long-lived episodic/semantic Agent Memory with sparse reuse. |
| 14 | `tool_result_bursty` | TOOL_RESULT:1 | 32K | 64 | 64 | 28 | 1.15 | arrival_burst | - | - | - | Bursty tool/agent-state results reused over multiple steps. |
| 15 | `lora_multi_tenant_b64` | LORA_ADAPTER:1 | 128K | 64 | 64 | 32 | 1.05 | bimodal | - | - | - | Multi-LoRA serving with popularity skew. |
| 16 | `moe_expert_skew_b256` | MOE_EXPERT:1 | 128K | 64 | 256 | 36 | 1.15 | bimodal | - | - | - | MoE routing skew under large batch. |
| 17 | `mixed_all_ai_data_b64` | KV_CACHE:0.32, RAG_DATA:0.22, AGENT_MEMORY:0.16, TOOL_RESULT:0.1, LORA_ADAPTER:0.1, MOE_EXPERT:0.1 | 128K | 72 | 64 | 48 | 1.1 | - | size_scale=1.2 | - | rag_index_total_gib=1024 | All primary DP1 AI data classes coexist. |
| 18 | `hbm_pressure_ramp_b64` | KV_CACHE:0.55, LORA_ADAPTER:0.2, MOE_EXPERT:0.25 | 128K | 64 | 64 | 42 | 1.15 | capacity_ramp | size_scale=1.2 | - | - | Progressive HBM pressure with KV/LoRA/MoE. |
| 19 | `hbm_bw_shock_b256` | KV_CACHE:0.75, MOE_EXPERT:0.25 | 128K | 64 | 256 | 32 | 1.25 | hbm_bw_shock | hbm_bw_mult=0.28 | - | - | Sudden HBM bandwidth shock at batch 256. |
| 20 | `host_path_pressure_b64` | RAG_DATA:0.4, AGENT_MEMORY:0.35, TOOL_RESULT:0.25 | 128K | 80 | 64 | 36 | 1.05 | host_bw_shock | host_bw_mult=0.35 | - | rag_index_total_gib=1024 | CPU/PCIe contention with RAG/Agent/Tool data. |
| 21 | `data_mix_shift_b64` | KV_CACHE:0.35, RAG_DATA:0.25, AGENT_MEMORY:0.2, LORA_ADAPTER:0.1, TOOL_RESULT:0.1 | 128K | 72 | 64 | 44 | 1.1 | data_mix_shift | - | - | rag_index_total_gib=1024 | Workload shifts from KV/LoRA to RAG/Agent. |
| 22 | `behavior_flip_stress` | KV_CACHE:0.35, RAG_DATA:0.25, AGENT_MEMORY:0.2, TOOL_RESULT:0.1, LORA_ADAPTER:0.1 | 32K | 72 | 16 | 40 | 0.9 | hotness_flip | - | - | rag_index_total_gib=512 | Abrupt per-object hotness inversion; stresses C2 prediction lag/thrashing while C1 reacts only to resource pressure. |
| 23 | `six_tier_capacity_stress` | KV_CACHE:0.3, RAG_DATA:0.25, AGENT_MEMORY:0.2, TOOL_RESULT:0.1, LORA_ADAPTER:0.08, MOE_EXPERT:0.07 | 128K | 72 | 64 | 68 | 1.1 | - | size_scale=4; capacity_mult=0.35 | - | rag_index_total_gib=4096 | Capacity ladder intentionally exercises all six memories. |

## G.3 dynamic_benchmark

| # | name | data mix | ctx | out | batch | objs | demand | phase | knobs | disabled tiers | extra | description |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 1 | `dyn_cold_resident_chat_wave` | AGENT_MEMORY:0.7, KV_CACHE:0.3 | 320K | 64 | 16 | 13 | 1 | - | size_scale=2.7; hbm_capacity_mult=0.4 | - | plan=(('AGENT_MEMORY', 9, 0, 0, 1.0, ()), ('KV_CACHE', 4, 20, 30, 1.0, ())) | Serving pattern: long-lived Agent Memory (episodic state kept warm for idle tenants) is loaded at start-up and fills HBM first-come-first-served; at t=20-30 s an interactive long-context chat wave arrives. As-Is failure mode: the new hot KV sessions land in host DRAM (HBM is full of cold data) and are never promoted, so every turn pays the host-link restore. |
| 2 | `dyn_idle_kv_holds_hbm` | KV_CACHE:1 | 320K | 64 | 16 | 8 | 1 | - | hbm_capacity_mult=0.4 | - | plan=(('KV_CACHE', 4, 0, 0, 0.05, ()), ('KV_CACHE', 4, 30, 40, 1.0, ())) | Serving pattern: agent sessions blocked on slow tool calls keep their KV resident (idle, rate x0.05) and hold HBM; at t=30-40 s the tool results return / new sessions arrive and become the hot set. As-Is failure mode: arrival order decided HBM residency; hot sessions are served from DRAM while idle sessions sit in HBM. All objects are the same data class, so only per-object behavior tells them apart. |
| 3 | `dyn_kv_hotset_recency_shift` | KV_CACHE:1 | 320K | 64 | 16 | 8 | 1 | - | hbm_capacity_mult=0.4 | - | plan=(('KV_CACHE', 4, 0, 0, 1.0, ((0, 1.0), (90, 0.1))), ('KV_CACHE', 4, 0, 0, 0.1, ((0, 1.0), (90, 30.0)))) | Serving pattern: working-set drift. Conversations created first are hot in the first half (HBM residents by first-come placement); at t=90 s users move on: the early sessions go cold (x0.1) and the later sessions (resident in DRAM) become hot (x3). As-Is failure mode: placement frozen at the old working set; post-shift traffic is served from DRAM. |
| 4 | `dyn_kv_rotating_hotset` | KV_CACHE:1 | 320K | 64 | 16 | 9 | 1 | - | hbm_capacity_mult=0.3 | - | plan=(('KV_CACHE', 3, 0, 0, 1.0, ((0, 3.0), (60, 0.1))), ('KV_CACHE', 3, 0, 0, 1.0, ((0, 0.1), (60, 3.0), (120, 0.1))), ('KV_CACHE', 3, 0, 0, 1.0, ((0, 0.1), (120, 3.0)))) | Serving pattern: three user groups active in turn (60 s windows, e.g. shift/time-zone hand-over); the active group is hot (x3), the others near idle (x0.1). As-Is failure mode: placement fits only the first window; in later windows the active group is in DRAM. Also probes anti-thrashing: the hot set moves every 60 s. |
| 5 | `dyn_rag_shard_hotset_shift` | RAG_DATA:1 | 32K | 96 | 16 | 8 | 1 | - | hbm_capacity_mult=0.12 | - | rag_index_total_gib=256; plan=(('RAG_DATA', 4, 0, 0, 1.0, ((0, 1.0), (90, 0.1))), ('RAG_DATA', 4, 0, 0, 0.1, ((0, 1.0), (90, 30.0)))) | Serving pattern: GPU-resident vector-index shards (8 x ~32 GiB). Query popularity shifts at t=90 s (trending topic / newly ingested documents): the first shards (HBM residents) cool down, the later shards (host DRAM) become hot. As-Is failure mode: the hot shards are scanned from DRAM (full index crosses the host link per query). |
| 6 | `dyn_host_path_contention_kv` | KV_CACHE:1 | 128K | 64 | 16 | 8 | 1 | host_bw_shock | host_bw_mult=0.25; hbm_capacity_mult=0.12 | - | plan=(('KV_CACHE', 8, 0, 0, 1.0, ()),) | Serving pattern: host-side contention (co-located checkpoint / dataloader / NIC traffic on the shared PCIe root) cuts host-link bandwidth to 25% from t=90 s. 128K-context KV that spilled to DRAM was fine before. As-Is failure mode: static tier order keeps the spilled sessions on the degraded path. |
<!-- END GENERATED -->

# 5. 관련 문서

- `../common-benchmark.md`, `../qa-evaluation-criteria.md`, `../system-specs.md`
- `simulation-plan.md` (13장 workload set, 14장 metrics)
- `sim/scenarios.py` (정의), `sim/qa_eval.py` (QA 산출)
- `results/` (결과)
