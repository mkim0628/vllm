# DP1 C1/C2 Baseline Evaluation Snapshot (V1)

> 이 문서는 **보완 설계 이전의 결과를 동결(freeze)** 하기 위한 baseline snapshot이다.
>
> 기준 실행: GitHub Actions run `35296757825`  
> 기준 policy: `As-Is-HBM-first`, `C1-memory-centric`, `C2-data-centric`  
> 목적: C1/C2의 최초 trade-off를 보존하고, 이후 C1-R/C2-R 보완 설계가 무엇을 개선했는지 비교 가능하게 한다.

---

# 1. 평가 구성

- Model: `llama_3_1_70b`
- Cluster: `b200_8gpu`
- Memory: `memories_default.json`의 6개 Tier
- Scenario: 23개
- Seed: 5개
- Offered-load scale: 0.25 / 0.50 / 0.75 / 1.00 / 1.25
- 후보: As-Is / C1 / C2
- 총 실행 cell: 23 × 5 × 5 × 3 = **1,725 runs**

Throughput은 analytical peak 대비 비율이 아니라 **As-Is 대비 Max Sustainable SLO Goodput**으로 평가한다.

Latency는 하나로 합치지 않고 다음을 별도 관찰한다.

- First-response: TTFT p99
- Decode: TPOT p99

---

# 2. Baseline QA 결과

| Metric | As-Is | C1 | C2 |
|---|---:|---:|---:|
| Mean Token Throughput [tok/s] | 1,739.7 | 1,524.2 | 1,692.6 |
| Mean SLO Goodput [tok/s] | 925.0 | 687.6 | 806.6 |
| Heavy Goodput / As-Is | 1.000 | **1.000** | **0.860** |
| Heavy Goodput 95% CI | [1.000, 1.000] | [0.937, 1.067] | [0.744, 0.995] |
| Resource Utilization Index | 0.783 | **0.785** | **0.737** |
| HBM pressure violation rate | 0.191 | **0.129** | 0.189 |
| BW saturation rate | 0.0269 | **0.0214** | 0.0322 |
| Migration count / run | 11.55 | **16.27** | **48.00** |
| Placement decision proxy [us] | 3.0 | **12.2** | **34.0** |
| Fallback count / run | 0 | 0 | **75.81** |
| DRAM deferred stage / run | 0 | 0 | 0.91 |
| Deferred DRAM→HBM promotion / run | 0 | 0 | 0.17 |

현재 공통 별점 기준을 그대로 적용하면:

| QA | C1 | C2 | 해석 |
|---|:---:|:---:|---|
| Performance Throughput | ★★☆ | ★☆☆ | C1은 As-Is와 통계적으로 유사, C2는 heavy-goodput 회귀 |
| Performance Latency — TTFT | ★☆☆ | ★☆☆ | 일부 대규모 RAG/long-context cell의 절대 TTFT가 매우 큼 |
| Performance Latency — TPOT | ★☆☆ | ★☆☆ | 일부 large-batch/long-context cell이 SLO를 초과 |
| Resource Utilization | ★★☆ | ★★☆ | C1이 C2보다 안정적 |
| Modifiability | ★★☆ | ★☆☆ | C2가 Classifier/Interpreter/Affinity/Fallback 변화 전파가 큼 |

> Latency의 ★☆☆는 “모든 normal workload가 나쁘다”는 의미가 아니다. 현재 집계가 모든 SLO-feasible cell의 worst p99를 사용하고 있고, 8 TiB RAG / large-batch-long-context 같은 매우 무거운 cell이 포함되어 있다. 따라서 이 baseline snapshot에서는 **절대값을 그대로 보존**하되, 보완 실험에서는 workload class별 latency도 함께 본다.

---

# 3. C1의 현재 trade-off

## 강점

1. **Resource pressure 대응이 단순하고 안정적**
   - HBM pressure violation: 0.129
   - BW saturation: 0.0214
   - C2보다 낮음

2. **Heavy Goodput이 As-Is와 거의 동일**
   - 0.9999×
   - 95% CI가 1.0을 포함하므로 유의한 차이 없음

3. **Decision path가 짧음**
   - 12.2 us proxy
   - C2 34.0 us보다 가벼움

## 약점

1. Data semantics가 없으므로 cold/long-lived object와 hot object를 본질적으로 구분하지 못함.
2. Resource 변화가 threshold 근처에서 반복되면 unnecessary re-placement 가능.
3. 현재 migration 16.27/run으로 As-Is 11.55/run보다 많음.
4. “현재 tier를 유지하는 비용”과 “새 tier로 옮기는 migration cost”의 명시적 비교가 없음.

즉 C1의 다음 보완 방향은 **Data-aware로 바꾸는 것이 아니라 Resource-centric 철학을 유지하면서 decision stability를 높이는 것**이다.

---

# 4. C2의 현재 trade-off

## 강점

1. KV/RAG/Agent/LoRA/MoE의 특성을 구분 가능.
2. CXL-PNM / Custom HBM / SSD-PIM의 operation capability를 placement cost에 반영 가능.
3. Prediction error 시 DRAM stage → HBM promotion 같은 temporal fallback까지 표현 가능.
4. 특정 scenario에서는 C1보다 큰 개선이 존재.
   - `kv_b16_c32k_burst_chbm`: C2/C1 goodput ≈ 6.44×
   - `kv_mispredict_dram_wait`: C2/C1 goodput ≈ 2.11×

## 약점

전체 평균에서는 C2가 **0.860× As-Is heavy goodput**까지 떨어졌다.

가장 큰 현상은:

- Migration: **48/run**
- Fallback: **75.81/run**

으로, C1 대비 decision instability가 크다는 것이다.

### Fallback 원인 분해

전체 C2 fallback event 56,540건:

| Reason | Count | Share |
|---|---:|---:|
| predicted_first_response_violation | 33,387 | **59.1%** |
| operation_infeasible | 11,328 | **20.0%** |
| predicted_tpot_violation | 10,574 | **18.7%** |
| low_classifier_confidence | 820 | 1.45% |
| runtime_behavior_mismatch | 262 | 0.46% |
| no_capacity_candidate | 169 | 0.30% |

상위 세 원인이 **97.8%**를 차지한다.

이 결과는 “C2 prediction 자체가 대부분 틀렸다”기보다, 현재 selector가 다음 순서로 동작하기 때문에 발생한다.

```text
Affinity로 일단 Best Tier 선택
       ↓
Operation / Latency guard 검사
       ↓
불가하면 Fallback
       ↓
후속 reevaluation에서 같은 판단 반복 가능
```

즉 **애초에 실행 불가능한 tier가 affinity ranking에 올라온 뒤 fallback되는 구조**가 fallback storm의 주원인이다.

---

# 5. 현재 결과에서 발견된 핵심 설계 문제

## P1. Feasibility가 Affinity 뒤에 있음

현재 C2는 affinity를 계산한 후 required-operation / TTFT / TPOT guard에서 reject한다.

개선 방향:

```text
Before
Affinity Ranking → Best Tier → Feasibility Check → Fallback

After
Hard Feasibility Filter
    → Affinity Ranking
    → Migration/Benefit Gate
    → Final Tier
```

## P2. 같은 object에 대한 repeated fallback

한 번 fallback된 object가 짧은 주기로 다시 평가되면서 같은 violation을 반복할 수 있다.

개선 방향:

- fallback cooldown
- reason-specific retry condition
- state-machine 방식의 one-shot transition

## P3. Migration benefit과 migration cost를 직접 비교하지 않음

현재 “더 좋은 tier”이면 이동하는 경향이 있지만, 실제로 이동해서 얻는 이득이 transfer/migration cost보다 큰지 명시적으로 비교하지 않는다.

개선 방향:

```
Expected Gain > Migration Cost + Hysteresis Margin
```

일 때만 이동.

## P4. C1도 pressure threshold 근처의 oscillation 여지가 있음

C1은 C2만큼 심하지 않지만 current tier hold/min-residency가 없다.

개선 방향:

- high/low watermark
- minimum residency time
- score improvement threshold
- migration budget

---

# 6. Baseline 결론

이 시점의 결과만 보면:

- **C1**: 평균 성능과 resource stability가 더 안정적이고 구조가 단순함.
- **C2**: 일부 data-aware / operation-aware scenario에서 큰 잠재력이 있지만, 현재 구현은 fallback/migration instability 때문에 aggregate performance가 낮음.

따라서 이 baseline만으로 바로 C1/C2 하나를 고르기보다, 두 후보의 철학을 유지한 채 각각 한 번의 **보완 설계(Reinforcement Design)** 를 적용한 뒤 다시 비교하는 것이 타당하다.

다음 단계는:

1. C1-R: Resource-centric + stability/hysteresis
2. C2-R: Data-centric + feasibility-first + decision stability

를 추가하고 **동일 23 scenario / seed / load sweep**으로 재평가한다.
