# DP1 V2 Simulation Result

> Source run: GitHub Actions `35323984989`  
> Status: unit test / baseline evaluator / reinforcement evaluator / V2 evaluator / artifact upload = **success**
>
> V2 evaluator: 23 scenarios × 5 seeds × 7 candidates × 5 load scales = **4,025 simulation cells**
>
> 이 결과는 architecture-level simulation이며 실제 B200/vLLM 실측 benchmark가 아니다.

---

## 1. Aggregate

| Candidate | Heavy Goodput / As-Is | 95% CI | Mean SLO Goodput [tok/s] | RUI | HBM pressure | Migration/run |
|---|---:|---:|---:|---:|---:|---:|
| As-Is | 1.000 | [1.000, 1.000] | **946.4** | 0.778 | 0.191 | 11.44 |
| C1 | 1.000 | [0.937, 1.067] | 685.3 | 0.784 | **0.126** | 15.93 |
| C1-R | **1.064** | [0.950, 1.192] | 695.7 | 0.815 | 0.171 | **1.78** |
| **C1-R2** | **1.056** | [0.909, 1.226] | 654.6 | **0.859** | **0.065** | 3.11 |
| C2 | 0.860 | [0.744, 0.995] | 823.1 | 0.739 | 0.185 | 46.75 |
| C2-R | 0.948 | [0.810, 1.110] | 842.3 | 0.769 | 0.205 | 11.34 |
| **C2-R2** | **1.061** | [0.947, 1.187] | **941.3** | 0.753 | 0.166 | 26.35 |

현재 별점 기준에서는 C1-R2/C2-R2 모두 ratio가 1.10 미만이고 CI가 1.0을 포함하므로 Throughput은 **★★☆**다.

---

## 2. V2 Target-domain

| Candidate | Neutral / HBM-fit | C2 Data-near | C2 Data-lifecycle |
|---|---:|---:|---:|
| C1-R2 | **1.000** | 0.445 | 0.352 |
| C2-R2 | **1.000** | **1.059** | **0.993** |

C1 Resource-pressure domain은 현재 선정된 pressure scenarios가 모두 SLO-infeasible stress라 Max Sustainable SLO Goodput ratio를 계산할 수 없다. 따라서 C1-R2의 “resource-pressure workload에서 As-Is보다 빠르다”는 가설은 이번 run으로는 검증되지 않았다.

---

## 3. 주요 Scenario

| Scenario | C1-R2 Goodput | C2-R2 Goodput | C2-R2 TTFT | C2-R2 TPOT | 해석 |
|---|---:|---:|---:|---:|---|
| `kv_b1_c32k_cold_cxl` | 1.000 | **1.000** | 1.001× | 1.000× | Performance Guard가 나쁜 CXL offload를 막음 |
| `kv_b16_c32k` | 1.000 | **1.000** | 1.001× | 1.000× | Neutral workload에서 As-Is 수렴 |
| `rag_1tib_b16` | 1.000 | **1.000** | 1.000× | 1.000× | Neutral |
| `rag_8tib_b64_ssd_pim` | **1.177** | **1.193** | **0.592×** | 1.004× | Data-near GEMV의 가장 명확한 WIN |
| `agent_memory_long_lived` | 1.000 | **1.000** | 1.001× | 1.000× | C2 baseline regression 제거 |
| `tool_result_bursty` | 1.000 | **1.000** | 1.001× | 1.000× | C2 baseline regression 제거 |
| `kv_b16_c32k_burst_chbm` | 0.075 | 0.995 | 0.941× | **2.934×** | C2-R2 goodput은 회복했지만 TPOT regression |
| `kv_mispredict_dram_wait` | 0.124 | 0.986 | 1.181× | **2.286×** | temporal path가 아직 latency에 불리 |

---

## 4. V2-specific counters

### C1-R2

- Emergency migration: **1.07/run**
- HBM pressure violation: **0.065**
- Migration: **3.11/run**

Emergency Pressure Policy는 pressure를 크게 줄이는 데 성공했지만, 일부 KV scenario에서 off-HBM path의 TPOT가 매우 커졌다. 즉 **“pressure를 낮추는 것”만 목적함수로 두면 Performance를 잃을 수 있음**이 확인됐다.

### C2-R2

- Fallback: **0/run**
- Degraded Placement: **75.62/run**
- True no-physical-capacity: **0/run**
- Performance Baseline Bypass: **2.46/run**

즉 기존 `Fallback` 개념을 없애고, 실제로 물리적 target tier가 없는 경우는 이번 run에서 **한 번도 발생하지 않았다.**

---

## 5. 현재 해석

### C1-R2

Emergency Pressure라는 보완 방향 자체는 HBM pressure 관점에서 효과가 있다.

하지만 현재 구현은 Emergency에서 “pressure relief”를 너무 우선하여 일부 workload의 TPOT를 크게 악화시킨다.

따라서 다음 보완은 threshold를 사후 tuning하는 것이 아니라:

> **Emergency candidate도 최소 Performance/SLO Guard를 통과해야 한다**

로 설계해야 한다.

### C2-R2

C2-R2는 이번 V2에서 가장 중요한 목표 세 가지를 달성했다.

1. Neutral workload → As-Is와 1.0×
2. 나쁜 CXL offload negative-control → As-Is path로 bypass
3. SSD-PIM RAG target → Goodput 1.193× + TTFT 0.592×

다만 KV burst / DRAM-wait scenario에서는 TPOT regression이 남아 있어, C2-R2가 모든 target workload에서 Performance WIN인 것은 아니다.

---

## 6. 다음 판단

현재 결과만으로는:

- **C1-R2:** Resource pressure를 잘 낮추지만 Performance Guard가 Emergency path에도 필요
- **C2-R2:** Data-near target에서는 명확한 win, neutral/adverse workload에서는 상당히 no-regret에 가까워졌지만 KV temporal/offload latency를 추가 보완해야 함

으로 정리한다.
