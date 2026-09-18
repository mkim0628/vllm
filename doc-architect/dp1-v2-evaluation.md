# DP1 V2 Evaluation — Strict p99 Sustainable Operating Point

> Source run: GitHub Actions `35326307384`  
> Unit test / baseline / reinforcement / V2 evaluator = **success**
>
> **Sustainable operating point 정의**
>
> ```text
> TTFT p99 <= 2,000 ms
> AND
> TPOT p99 <= 50 ms
> ```
>
> 두 조건을 동시에 만족하는 load point만 QA의 Max Sustainable SLO Goodput 후보로 인정한다.
> 일부 request만 SLO를 만족하는 load point는 sustainable point로 인정하지 않는다.
>
> Architecture-level simulation이며 실제 B200/vLLM 실측 benchmark가 아니다.

---

## 1. V2 QA 평가표

| QA | C1-R2 | C2-R2 | 기준 |
|---|:---:|:---:|---|
| **Performance Throughput** | **★★☆** | **★★☆** | Strict-p99 Heavy Goodput / As-Is |
| **Performance Latency — TTFT** | **★★★** | **★★★** | Sustainable point의 worst p99 ≤ 2,000 ms |
| **Performance Latency — TPOT** | **★★☆** | **★★☆** | Sustainable point의 worst p99 = 약 50 ms |
| **Resource Utilization** | **★★★** | **★★☆** | RUI ≥0.85 / 0.65~0.85 |
| **Modifiability** | 재산정 필요 | 재산정 필요 | R2 구조 기준 별도 측정 필요 |

### 정량값

| Metric | As-Is | C1-R2 | C2-R2 |
|---|---:|---:|---:|
| Strict-p99 Heavy Goodput / As-Is | 1.000 | **1.000** | **1.000** |
| 95% CI | [1.000, 1.000] | [1.000, 1.000] | [1.000, 1.000] |
| Strict sustainable points | 35 | 25 | **35** |
| Worst sustainable TTFT p99 | 213.46 ms | **213.50 ms** | 213.57 ms |
| Worst sustainable TPOT p99 | 49.99 ms | **49.99 ms** | **49.99 ms** |
| RUI | 0.778 | **0.859** | 0.753 |
| HBM pressure violation ↓ | 0.191 | **0.065** | 0.166 |
| Migration/run ↓ | 11.44 | **3.11** | 26.35 |

---

## 2. 왜 이전 결과와 달라졌는가

이전 evaluator는 request-level `slo_goodput > 0`인 load point도 Max Sustainable 후보가 될 수 있었다.

따라서:

```text
일부 request는 SLO 만족
하지만 p99 TTFT/TPOT는 SLO 초과
```

인 load가 Goodput 계산에 들어갔다.

Strict-p99 기준에서는 이런 load를 제외한다.

그 결과 이전 V2에서:

- C1-R2 Heavy Goodput ≈ 1.056×
- C2-R2 Heavy Goodput ≈ 1.061×

로 보였던 개선은 **최종 QA 근거로 사용하지 않는다.**

새 기준에서 두 후보 모두 **1.000×**다.

---

## 3. Strict-p99에서 실제로 SLO-feasible한 Scenario

As-Is 기준으로 현재 5개 seed 모두 sustainable point가 존재하는 scenario는:

- `kv_b1_c32k_cold_cxl`
- `kv_b16_c32k`
- `kv_b16_c32k_burst_chbm`
- `kv_mispredict_dram_wait`
- `rag_1tib_b16`
- `agent_memory_long_lived`
- `tool_result_bursty`

현재 heavy QA에서 실제로 baseline과 pair되는 workload가 제한적이다.

특히:

- `rag_8tib_b64_ssd_pim`
- 128K / 512K long-context
- 현재 Resource-pressure B64/B256 scenario

는 p99 SLO 관점에서는 **Stress / Infeasible 영역**이다.

따라서 이전에 `rag_8tib_b64_ssd_pim`의 C2-R2가 Goodput 1.193×, TTFT 0.592×로 보였던 것은 **stress 영역 안에서의 상대적 개선**이지, 현재 2초 TTFT SLO를 만족하는 QA WIN으로 계산하지 않는다.

---

## 4. Target-domain Strict Goodput

| Candidate | Neutral / HBM-fit | C1 Resource-pressure | C2 Data-near | C2 Data-lifecycle |
|---|---:|---:|---:|---:|
| C1-R2 | **1.000** | N/A | SLO loss 포함 | SLO loss 포함 |
| C2-R2 | **1.000** | N/A | **0.979** | **0.993** |

### C1 Resource-pressure

현재 선정한:

- `hbm_pressure_ramp_b64`
- `hbm_bw_shock_b256`
- `host_path_pressure_b64`
- `data_mix_shift_b64`
- `mixed_all_ai_data_b64`

는 As-Is 자체가 strict p99 SLO를 만족하는 operating point가 없다.

따라서 **C1이 Resource-pressure workload에서 As-Is보다 빠르다는 가설은 아직 검증할 수 없다.**

### C2 Data-near

Strict-p99 기준에서 C2-R2의 Data-near aggregate는 약 **0.979×**다.

즉 현재 SLO-feasible Data-near 영역에서는 As-Is와 거의 비슷하지만 약간 낮다.

8 TiB SSD-PIM scenario의 큰 relative improvement는 여전히 의미 있는 stress 결과지만, 현재 TTFT 2초 SLO 기준 QA score에는 포함하지 않는다.

---

## 5. Scenario-level 핵심

| Scenario | C1-R2 | C2-R2 | 해석 |
|---|---:|---:|---|
| `kv_b1_c32k_cold_cxl` | 1.000 | **1.000** | 나쁜 CXL offload를 피하고 As-Is 수렴 |
| `kv_b16_c32k` | 1.000 | **1.000** | Neutral |
| `kv_b16_c32k_burst_chbm` | **SLO point 없음** | **0.958** | C1 Emergency path 실패, C2도 TPOT 여유 부족 |
| `kv_mispredict_dram_wait` | **SLO point 없음** | **0.986** | C2는 거의 As-Is, C1은 sustainable point 상실 |
| `rag_1tib_b16` | 1.000 | **1.000** | Neutral |
| `agent_memory_long_lived` | 1.000 | **1.000** | Neutral |
| `tool_result_bursty` | 1.000 | **1.000** | Neutral |
| `rag_8tib_b64_ssd_pim` | Stress | Stress | 상대 개선은 있으나 TTFT 2s SLO 불충족 |

---

## 6. 현재 결론

Strict-p99 기준으로 바꾸면서 QA 해석이 더 엄격해졌다.

### C1-R2

장점:

- RUI **0.859 → ★★★**
- HBM pressure violation **0.065**
- Migration **3.11/run**

문제:

- 일부 As-Is-feasible KV scenario에서 sustainable operating point 자체를 잃음.
- 따라서 Emergency Pressure Policy에는 **Performance/SLO Guard**가 필요하다.

### C2-R2

장점:

- As-Is가 sustainable한 heavy cell에서는 현재 **1.000×** 유지.
- Neutral workload도 As-Is 수준 유지.
- Baseline C2/C2-R에서 나타났던 strict-p99 feasibility loss는 R2에서 회복.

문제:

- SLO-feasible Data-near domain aggregate가 **0.979×**로 아직 명확한 Performance WIN은 아님.
- SSD-PIM 8 TiB의 큰 개선은 현재 SLO 밖 Stress 영역.

따라서 다음 실험에서는 **C1/C2의 강점을 검증할 수 있으면서도 As-Is가 strict p99 SLO를 만족하는 target scenario**를 추가해야 한다.
