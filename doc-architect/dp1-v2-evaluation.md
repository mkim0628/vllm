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

## 1.1 Case-separated QA Matrix

전체 aggregate에서 Performance가 1.000×로 보이는 이유는 C1/C2가 실제로 항상 동일해서가 아니다.

Strict-p99 기준에서 현재 score 가능한 workload가 제한적이고, score 가능한 neutral workload에서는 C1-R2/C2-R2 모두 As-Is/HBM path로 수렴하기 때문이다. 따라서 아래처럼 **architecture가 유리하도록 설계된 case를 별도로 본다.**

> `SLO Stress`는 QA 별점에는 포함하지 않는다. 다만 해당 architecture mechanism이 실제로 무엇을 개선하고 무엇을 악화시키는지 보여주는 보조 결과로 남긴다.

### C1-R2가 유리하도록 설계한 Case — Resource Pressure

| Case | Throughput | TTFT | TPOT | Resource | 판정 |
|---|---:|---:|---:|---:|---|
| `hbm_pressure_ramp_b64` | Raw token throughput **1.016×** As-Is | 0.999× | **4.97×** | RUI **0.933 vs 0.913**, HBM pressure 0.000 vs 0.009 | **Resource WIN / Performance SLO Stress** |
| `hbm_bw_shock_b256` | Raw token throughput **1.016×** | 1.000× | **5.11×** | RUI 0.873 vs 0.917 | **Performance SLO Stress** |
| `host_path_pressure_b64` | Raw token throughput 1.000× | **2.78×** | 1.000× | RUI **0.930 vs 0.819**, HBM pressure 0.000 vs 0.178 | **Resource WIN / Latency LOSS** |
| **C1 Resource-pressure strict aggregate** | **N/A** | N/A | N/A | — | As-Is 자체가 strict p99 SLO를 만족하는 paired cell이 없어 **Performance 우위 판정 불가** |

현재 C1-R2의 명확한 장점은 **Resource Pressure 해소**다.  
아직 strict-p99 기준의 **Performance WIN case는 확보하지 못했다.**

### C2-R2가 유리하도록 설계한 Case — Data-near / Data-lifecycle

| Case | Strict Goodput / As-Is | TTFT / As-Is | TPOT / As-Is | Resource | 판정 |
|---|---:|---:|---:|---:|---|
| `kv_b16_c32k_burst_chbm` | **0.958×** | **0.869×** | 2.586× | RUI 0.368 vs 0.382 | **TTFT 개선 / Goodput·TPOT Trade-off** |
| `kv_b1_c32k_cold_cxl` | **1.000×** | 1.001× | 1.000× | 동일 | **Negative-control PASS** — 느린 CXL offload를 하지 않음 |
| `kv_mispredict_dram_wait` | **0.986×** | 1.181× | 2.286× | RUI 동일 | **Near-neutral Goodput / Latency LOSS** |
| `rag_8tib_b64_ssd_pim` | **SLO Stress** | Stress TTFT **0.818×** | Stress TPOT 0.996× | RUI 0.528 vs 0.657 | **Data-near Performance Benefit은 보이나 2s TTFT SLO 밖** |
| `rag_1tib_b16` | **1.000×** | 1.000× | 1.000× | 동일 | **Neutral / No-regression** |
| `agent_memory_long_lived` | **1.000×** | 1.001× | 1.000× | 동일 | **Neutral / No-regression** |
| **C2 Data-near strict aggregate** | **0.979×** | — | — | — | As-Is와 근접하나 아직 **Performance WIN 아님** |
| **C2 Data-lifecycle strict aggregate** | **0.993×** | — | — | — | 사실상 As-Is 수준 |

### QA 관점에서 읽는 법

| QA | C1-R2 유리 영역 | C2-R2 유리 영역 | 현재 증명 수준 |
|---|---|---|---|
| **Performance Throughput** | Resource-pressure가 SLO-feasible한 영역을 아직 확보하지 못함 | SSD-PIM RAG / near-memory KV가 후보이나 strict aggregate 0.979× | **추가 target scenario 필요** |
| **Performance Latency — TTFT** | 현재 명확한 WIN 없음 | Custom-HBM KV burst에서 0.869×, 8 TiB RAG stress에서 0.818× | C2의 data-near 장점 일부 확인 |
| **Performance Latency — TPOT** | Emergency offload에서 악화 | KV offload/deferred path에서 headroom 감소 | 둘 다 보완 필요 |
| **Resource Utilization** | **명확한 강점** — aggregate RUI 0.859 | aggregate RUI 0.753 | C1-R2 우세 영역이 명확 |
| **Modifiability** | 재산정 필요 | 재산정 필요 | R2 구현 기준으로 다시 측정 |

따라서 **C1과 C2의 Performance가 실제로 같다고 결론 내리면 안 된다.**  
현재 strict-p99 QA suite가 두 후보의 target-domain Performance 차이를 충분히 관찰하지 못하고 있다는 것이 더 정확한 해석이다.

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
