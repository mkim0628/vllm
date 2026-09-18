# DP1 C1/C2 QA Evaluation — Multi-AI-Data Simulation

> QA 별점 기준은 `evaluation-criteria.md`의 **DP1~DP4 공통 기준**만 사용한다. Fault-injection/coverage stress 3종은 trade-off 분석에는 포함하되 최종 QA 별점 산정에서는 제외했다.

## 1. Final QA score

| QA | C1 Memory-centric | C2 Data-centric | 공통 정량 기준 |
|---|---:|---:|---|
| **Performance Throughput** | ★★☆ | ★★☆ | Reference TPS 대비: ★★★ ≥0.85, ★★☆ 0.50~0.85 |
| **Performance Latency** | ★★★ | ★★★ | min(TTFT, TPOT): TTFT ≤2s, TPOT ≤25ms이면 ★★★ |
| **Resource Utilization** | ★★★ | ★★★ | RUI: ★★★ ≥0.85, ★★☆ 0.65~0.85 |
| **Modifiability** | ★★★ | ★★☆ | PM/Token 중 낮은 별점; ★★★ ≤0.25PM and ≤20K token |

## 2. Scored aggregate

| Metric | C1 | C2 |
|---|---:|---:|
| Throughput / physical reference | 0.8492 | 0.8493 |
| Token throughput mean [tok/s] | 3073.3762 | 3073.5219 |
| Request throughput mean [req/s] | 47.5197 | 47.5167 |
| Worst scored TTFT p99 [ms] | 398.5247 | 785.0139 |
| Worst scored TPOT p99 [ms] | 20.1117 | 20.9354 |
| Resource Utilization Index | 0.8835 | 0.9314 |
| HBM pressure violation rate | 0.1214 | 0.0000 |
| BW saturation rate | 0.0028 | 0.0153 |
| Migration decisions/run | 19.9765 | 3.5059 |
| Placement decision proxy [us] | 12.2000 | 34.0000 |

## 3. Scenario design — AI Data coverage

`write_heavy_logs`라는 모호한 이름은 제거하고 **`runtime_log_append`**로 명시했다. 이 시나리오는 SST/SSTable이 아니라 DP1 범위의 **AI Runtime / Agent execution log**다. SSTable 자체는 storage-engine 내부 구조이므로 AI Runtime Data로 보지 않는다.

| Scenario | AI Data | 의도 | Target tier coverage |
|---|---|---|---|
| `steady_hot_kv` (QA-score) | KV_CACHE:100% | Hot KV cache, stable load; HBM vs attention-capable offload. | hbm, custom_hbm, cxl_pnm |
| `mixed_kv_rag` (QA-score) | KV_CACHE:58%, RAG_DATA:42% | Interactive generation plus hot/cold retrieval corpus. | hbm, hbf, dram, cxl_pnm |
| `rag_hot_cold_index` (QA-score) | RAG_DATA:100% | Large read-mostly RAG index with skewed query locality. | hbm, hbf, dram, ssd_pim |
| `agent_memory_long_lived` (QA-score) | AGENT_MEMORY:100% | Long-retained agent episodic/semantic memory with sparse re-use. | dram, cxl_pnm, ssd_pim, hbf |
| `tool_result_bursty` (QA-score) | TOOL_RESULT:100% | Bursty tool results reused over several agent steps. | hbm, dram, hbf, ssd_pim |
| `runtime_log_append` (QA-score) | LOG_DATA:100% | AI runtime/agent execution logs: append-heavy, long retention, rarely reread. Not SST/SSTable. | dram, ssd_pim |
| `lora_multi_tenant` (QA-score) | LORA_ADAPTER:100% | Multi-LoRA serving with Zipf-like adapter popularity. | hbm, hbf, dram |
| `moe_expert_skew` (QA-score) | MOE_EXPERT:100% | MoE experts with routed hot/cold skew. | hbm, hbf, dram |
| `mixed_all_ai_data` (QA-score) | KV_CACHE:28%, RAG_DATA:18%, AGENT_MEMORY:14%, TOOL_RESULT:10%, LOG_DATA:8%, LORA_ADAPTER:10%, MOE_EXPERT:12% | All DP1 AI Runtime Data classes coexist. | hbm, custom_hbm, cxl_pnm, dram, hbf, ssd_pim |
| `hbm_pressure_ramp` (QA-score) | KV_CACHE:55%, LORA_ADAPTER:20%, MOE_EXPERT:25% | HBM capacity progressively tightens while KV/LoRA/MoE stay active. | hbm, custom_hbm, hbf, dram |
| `hbm_bw_shock` (QA-score) | KV_CACHE:75%, MOE_EXPERT:25% | Sudden HBM bandwidth shock tests C1 resource prediction/reaction. | hbm, custom_hbm, cxl_pnm, hbf |
| `host_path_pressure` (QA-score) | RAG_DATA:40%, AGENT_MEMORY:35%, TOOL_RESULT:25% | CPU/PCIe path contention while RAG/agent/tool data are active. | hbf, dram, cxl_pnm, ssd_pim |
| `resource_oscillation` (QA-score) | KV_CACHE:45%, RAG_DATA:25%, AGENT_MEMORY:15%, LORA_ADAPTER:15% | Alternating HBM and host-path pressure. | hbm, custom_hbm, hbf, dram, cxl_pnm |
| `hotness_flip` (QA-score) | RAG_DATA:35%, AGENT_MEMORY:25%, LORA_ADAPTER:20%, MOE_EXPERT:20% | Previously cold data becomes hot and vice versa. | hbm, hbf, dram, ssd_pim |
| `data_mix_shift` (QA-score) | KV_CACHE:35%, RAG_DATA:20%, AGENT_MEMORY:15%, LORA_ADAPTER:15%, TOOL_RESULT:15% | Workload shifts from KV/LoRA to RAG/Agent halfway through. | hbm, custom_hbm, hbf, dram, cxl_pnm, ssd_pim |
| `classifier_error` (robustness/coverage) | KV_CACHE:30%, RAG_DATA:25%, AGENT_MEMORY:20%, TOOL_RESULT:10%, LORA_ADAPTER:15% | 40% wrong DataDescriptor type hints; tests C2 mis-characterization risk. | hbm, hbf, dram, cxl_pnm, ssd_pim |
| `capacity_crunch` (robustness/coverage) | KV_CACHE:30%, RAG_DATA:22%, AGENT_MEMORY:18%, LOG_DATA:10%, LORA_ADAPTER:10%, MOE_EXPERT:10% | Artificially reduces all usable capacity to induce spill decisions. | hbm, custom_hbm, cxl_pnm, dram, hbf, ssd_pim |
| `long_context` (QA-score) | KV_CACHE:65%, RAG_DATA:35% | Long-context KV plus RAG raises capacity and decode-read pressure. | hbm, custom_hbm, cxl_pnm, hbf, dram |
| `cold_archive_reactivation` (QA-score) | AGENT_MEMORY:45%, TOOL_RESULT:25%, LOG_DATA:30% | Cold agent memories, tool results and logs are archived then sporadically reactivated. | dram, hbf, ssd_pim, cxl_pnm |
| `six_tier_stress` (robustness/coverage) | KV_CACHE:22%, RAG_DATA:20%, AGENT_MEMORY:16%, TOOL_RESULT:10%, LOG_DATA:12%, LORA_ADAPTER:10%, MOE_EXPERT:10% | Capacity ladder and mixed data intentionally create useful roles for all six target memories. | hbm, custom_hbm, cxl_pnm, dram, hbf, ssd_pim |

## 4. Six-memory actual coverage

### C1-memory-centric

- Exercised tiers: **custom_hbm, cxl_pnm, dram, hbf, hbm, ssd_pim**
- Placement decisions: `custom_hbm`=413, `cxl_pnm`=382, `dram`=560, `hbf`=2331, `hbm`=11291, `ssd_pim`=2014

### C2-data-centric

- Exercised tiers: **custom_hbm, cxl_pnm, dram, hbf, hbm, ssd_pim**
- Placement decisions: `custom_hbm`=203, `cxl_pnm`=216, `dram`=729, `hbf`=906, `hbm`=8640, `ssd_pim`=4153

### Data class × tier coverage

다음은 단순히 시나리오 이름에 tier를 적은 것이 아니라 실제 placement decision에서 관찰된 조합이다.

**C1-memory-centric**
- `KV_CACHE` → custom_hbm:263, cxl_pnm:84, dram:11, hbf:14, hbm:1040, ssd_pim:159
- `RAG_DATA` → custom_hbm:16, cxl_pnm:36, dram:101, hbf:296, hbm:806, ssd_pim:171
- `AGENT_MEMORY` → custom_hbm:31, cxl_pnm:62, dram:135, hbf:274, hbm:748, ssd_pim:133
- `TOOL_RESULT` → custom_hbm:15, cxl_pnm:33, dram:69, hbf:157, hbm:470, ssd_pim:33
- `LOG_DATA` → custom_hbm:10, cxl_pnm:65, dram:119, hbf:484, hbm:542, ssd_pim:90
- `LORA_ADAPTER` → custom_hbm:16, cxl_pnm:26, dram:22, hbf:60, hbm:492, ssd_pim:15
- `MOE_EXPERT` → custom_hbm:24, cxl_pnm:22, dram:32, hbf:89, hbm:484, ssd_pim:28

**C2-data-centric**
- `KV_CACHE` → custom_hbm:103, cxl_pnm:83, dram:29, hbf:48, hbm:1037, ssd_pim:89
- `RAG_DATA` → custom_hbm:7, cxl_pnm:15, dram:53, hbf:298, hbm:728, ssd_pim:130
- `AGENT_MEMORY` → custom_hbm:15, cxl_pnm:78, dram:278, hbf:58, hbm:486, ssd_pim:199
- `TOOL_RESULT` → custom_hbm:8, cxl_pnm:4, dram:45, hbf:59, hbm:379, ssd_pim:33
- `LOG_DATA` → custom_hbm:1, cxl_pnm:2, dram:74, hbf:7, hbm:4, ssd_pim:429
- `LORA_ADAPTER` → custom_hbm:8, cxl_pnm:4, dram:7, hbf:53, hbm:485, ssd_pim:19
- `MOE_EXPERT` → custom_hbm:8, cxl_pnm:7, dram:22, hbf:71, hbm:474, ssd_pim:33

## 5. Scenario-level trade-offs

| Scenario | C1 thr/ref | C2 thr/ref | C2-C1 | 95% CI | C1 RUI | C2 RUI |
|---|---:|---:|---:|---:|---:|---:|
| `steady_hot_kv` | 0.532 | 0.532 | -0.0% | [-0.8, +0.8]% | 0.933 | 0.933 |
| `mixed_kv_rag` | 0.653 | 0.658 | +0.7% | [+0.0, +1.4]% | 0.925 | 0.925 |
| `rag_hot_cold_index` | 0.993 | 0.990 | -0.3% | [-0.6, +0.0]% | 0.812 | 0.930 |
| `agent_memory_long_lived` | 0.960 | 0.962 | +0.3% | [-0.2, +0.8]% | 0.925 | 0.925 |
| `tool_result_bursty` | 0.998 | 0.998 | +0.0% | [+0.0, +0.0]% | 0.924 | 0.915 |
| `runtime_log_append` | 0.937 | 0.936 | -0.1% | [-0.9, +0.6]% | 0.514 | 0.916 |
| `lora_multi_tenant` | 0.997 | 0.998 | +0.2% | [+0.1, +0.2]% | 0.933 | 0.933 |
| `moe_expert_skew` | 0.999 | 0.999 | -0.0% | [-0.1, +0.1]% | 0.933 | 0.933 |
| `mixed_all_ai_data` | 0.775 | 0.774 | -0.1% | [-0.5, +0.3]% | 0.947 | 0.947 |
| `hbm_pressure_ramp` | 0.786 | 0.793 | +1.0% | [+0.3, +1.7]% | 0.940 | 0.925 |
| `hbm_bw_shock` | 0.652 | 0.651 | -0.1% | [-1.1, +0.8]% | 0.955 | 0.925 |
| `host_path_pressure` | 0.973 | 0.969 | -0.3% | [-1.0, +0.4]% | 0.925 | 0.925 |
| `resource_oscillation` | 0.675 | 0.678 | +0.5% | [-0.3, +1.4]% | 0.944 | 0.944 |
| `hotness_flip` | 0.996 | 0.996 | -0.0% | [-0.4, +0.3]% | 0.925 | 0.925 |
| `data_mix_shift` | 0.886 | 0.884 | -0.3% | [-1.2, +0.5]% | 0.930 | 0.933 |
| `classifier_error` | 0.769 | 0.548 | -27.1% | [-51.0, -3.1]% | 0.940 | 0.953 |
| `capacity_crunch` | 0.203 | 0.309 | +56.5% | [+28.9, +84.0]% | 0.649 | 0.794 |
| `long_context` | 0.637 | 0.635 | -0.3% | [-2.0, +1.3]% | 0.960 | 0.940 |
| `cold_archive_reactivation` | 0.987 | 0.984 | -0.3% | [-0.7, +0.0]% | 0.594 | 0.958 |
| `six_tier_stress` | 0.199 | 0.225 | +14.1% | [-2.7, +31.0]% | 0.564 | 0.600 |

## 6. Modifiability — common DP1~DP4 basis

| Candidate | Person-month | Person-days | Static AI token estimate | PM star | Token star | Final |
|---|---:|---:|---:|---:|---:|---:|
| C1 | 0.1961 | 3.73 | 9,360 | ★★★ | ★★★ | ★★★ |
| C2 | 0.4235 | 8.05 | 10,937 | ★★☆ | ★★★ | ★★☆ |

AI token은 실제 agent usage telemetry가 아니라 공통 기준 문서의 **read/write source chars ÷ 3.6 char/token 정적 추정**이다. 실제 API usage를 가장한 값이 아니다.

## 7. Interpretation and limits

- **C1**은 Data class semantics를 사용하지 않아 classifier 오류에 구조적으로 영향받지 않고, 신규 Data Type 변경 비용이 작다.
- **C2**는 RAG/Agent/Log/LoRA/MoE 등 class/runtime behavior를 Tier affinity로 변환하므로 전체 suite의 RUI가 높다. 대신 잘못된 type hint를 주입한 `classifier_error`에서 failure mode가 드러난다.
- `capacity_crunch`와 `six_tier_stress`는 정상 SLO 운용점이 아니라 spill/coverage를 확인하는 stress test이므로 최종 별점에서는 제외했다.
- 실제 migration mechanism은 DP4 범위다. 본 simulator는 tier 변경 시 idealized path cost의 20%만 다음 access critical path에 반영한다.
- 실제 vLLM 실측이 아니라 architecture-level simulation이다. Config의 ASSUMED 값 때문에 절대값보다 **동일 trace의 후보 간 차이와 failure mode**를 더 신뢰해야 한다.
