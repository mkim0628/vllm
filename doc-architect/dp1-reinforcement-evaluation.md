# DP1 Reinforcement Evaluation — C1/C2 Before vs After

> Baseline C1/C2는 수정하지 않고, C1-R/C2-R을 별도 후보로 추가해 동일 trace에서 재평가했다.
>
> 기준 실행: GitHub Actions run `35302970469`  
> 실행 상태: unit test / baseline evaluator / reinforcement evaluator / artifact upload 모두 success

---

# 1. Aggregate Before / After

| Metric | C1 | C1-R | C2 | C2-R |
|---|---:|---:|---:|---:|
| Heavy Goodput / As-Is | 0.9999 | **1.0644** | 0.8604 | **0.9482** |
| Mean SLO Goodput [tok/s] | 687.6 | **699.5** | 806.6 | **826.7** |
| Resource Utilization Index | 0.7854 | **0.8101** | 0.7373 | **0.7693** |
| HBM pressure violation | **0.1294** | 0.1773 | **0.1889** | 0.2096 |
| BW saturation | 0.0214 | **0.0210** | 0.0322 | **0.0321** |
| Migration / run | 16.27 | **1.87** | 48.00 | **11.29** |
| Fallback / run | 0 | 0 | 75.81 | **14.27** |
| Suppressed migration / run | 0 | 11.97 | 0 | 10.44 |
| Feasibility-filtered candidates / run | 0 | 0 | 0 | 199.46 |
| Stable infeasible hold / run | 0 | 0 | 0 | 11.78 |
| Decision proxy [us] | 12.2 | 14.0 | 34.0 | 39.0 |

---

# 2. QA Star View

| QA | C1 | C1-R | C2 | C2-R |
|---|:---:|:---:|:---:|:---:|
| Performance Throughput | ★★☆ | ★★☆ | ★☆☆ | **★★☆** |
| Performance Latency — TTFT | ★☆☆ | ★☆☆ | ★☆☆ | ★☆☆ |
| Performance Latency — TPOT | ★☆☆ | ★☆☆ | ★☆☆ | ★☆☆ |
| Resource Utilization | ★★☆ | ★★☆ | ★★☆ | ★★☆ |

Latency 별점은 large-batch/long-context 및 대규모 RAG cell의 worst p99 때문에 낮다. 따라서 별점만 보지 않고 scenario별 raw TTFT/TPOT과 SLO-infeasible boundary를 함께 해석해야 한다.

---

# 3. 보완 효과

## 3.1 C1 → C1-R

- Migration: **16.27 → 1.87/run (-88.5%)**
- Heavy Goodput: **0.9999 → 1.0644 (+6.5%)**
- RUI: **0.7854 → 0.8101 (+3.1%)**
- Decision proxy: 12.2 → 14.0 us

즉 C1-R의 hysteresis / minimum residency / migration-benefit gate가 **거의 대부분의 불필요한 이동을 억제하면서 성능을 유지**했다.

다만 새로운 trade-off가 생겼다.

- HBM pressure violation: **0.1294 → 0.1773**

이유는 현재 tier hold가 강해져서 “옮기지 않는 안정성”은 좋아졌지만 pressure가 올라가는 순간 즉시 relief하지 않는 경우가 늘었기 때문이다.

### C1-R 1차 가설 판정

- PASS — Goodput 95% 이상 유지
- PASS — Migration 20% 이상 감소
- PASS — RUI baseline 이하로 내려가지 않음

C1-R은 1차 보완 가설을 모두 만족했다.

---

## 3.2 C2 → C2-R

- Fallback: **75.81 → 14.27/run (-81.2%)**
- Migration: **48.00 → 11.29/run (-76.5%)**
- Heavy Goodput: **0.8604 → 0.9482 (+10.2%)**
- Mean SLO Goodput: **806.6 → 826.7 tok/s**
- RUI: **0.7373 → 0.7693 (+4.3%)**
- Throughput 별점: **★☆☆ → ★★☆**

즉 C2 baseline에서 발견된 핵심 문제였던 fallback/migration storm은 크게 완화되었다.

### C2-R 1차 가설 판정

- PASS — Fallback ≤ 20/run
- PASS — Migration ≤ 24/run
- FAIL — Heavy Goodput ≥ 0.95
  - 실제: **0.9482**
- FAIL — RUI ≥ 0.78
  - 실제: **0.7693**

두 실패 항목 모두 목표에 매우 가깝지만, threshold를 맞추기 위해 사후 tuning하지 않는다. 현재 결과를 그대로 보존한다.

---

# 4. C2 Fallback Root Cause — Before / After

## Baseline C2

총 fallback event 56,540건:

| Reason | Count | Share |
|---|---:|---:|
| predicted_first_response_violation | 33,387 | 59.1% |
| operation_infeasible | 11,328 | 20.0% |
| predicted_tpot_violation | 10,574 | 18.7% |
| low_classifier_confidence | 820 | 1.45% |
| runtime_behavior_mismatch | 262 | 0.46% |
| no_capacity_candidate | 169 | 0.30% |

Baseline에서 상위 3개가 97.8%였다.

이는:

```text
Affinity Ranking
   ↓
Best Tier 선택
   ↓
Operation / Latency 검증
   ↓
Reject
   ↓
Fallback
```

순서 때문에 발생했다.

## C2-R

| Reason | Count |
|---|---:|
| hard_feasibility_empty | 9,823 |
| low_classifier_confidence | 2,365 |
| runtime_behavior_mismatch | **2** |

기존의:

- `predicted_first_response_violation`
- `operation_infeasible`
- `predicted_tpot_violation`

반복 fallback은 제거되었다.

즉 C2-R에서는 문제가 다음처럼 바뀌었다.

```text
Before:
"잘못 고른 뒤 reject해서 반복 fallback"

After:
"애초에 실행 가능한 후보만 ranking"
        ↓
후보 자체가 없으면
hard_feasibility_empty로 명시
```

이 변화는 단순 수치 개선보다 중요하다. **Policy instability와 실제 hardware/workload infeasibility를 분리**할 수 있게 되었기 때문이다.

---

# 5. Scenario-level 주요 변화

| Scenario | C1 | C1-R | C2 | C2-R |
|---|---:|---:|---:|---:|
| kv_b1_c32k_cold_cxl | 1.000 | 1.000 | 0.249 | 0.250 |
| kv_b16_c32k | 1.000 | 1.000 | 1.000 | 1.000 |
| kv_b16_c32k_burst_chbm | 0.139 | **0.175** | 0.896 | **0.905** |
| kv_mispredict_dram_wait | 0.389 | 0.366 | 0.822 | **0.859** |
| rag_1tib_b16 | 1.000 | 1.000 | 1.000 | 1.000 |
| rag_8tib_b64_ssd_pim | 1.000 | **1.206** | 0.957 | **1.193** |
| agent_memory_long_lived | 1.000 | 1.000 | 0.665 | **0.715** |
| tool_result_bursty | 1.000 | 1.000 | 1.000 | 1.000 |
| classifier_error | 0.988 | 0.988 | 0.982 | 0.983 |

값은 Max Sustainable SLO Goodput / As-Is 비율이다.

특히 `rag_8tib_b64_ssd_pim`에서는 C1-R/C2-R 모두 1.0을 넘어, tier stability와 SSD-PIM GEMV path가 동시에 유효한 영역이 존재함을 보여준다.

반면 B64/B256 × 128K/512K 일부 KV/MoE/LoRA cell은 모든 후보가 SLO Goodput 0이어서 N/A다. 이 cell은 **placement policy 비교용이 아니라 hardware/SLO feasibility boundary**로 해석한다.

---

# 6. 보완 설계로 확인된 새로운 Trade-off

## C1-R

### 좋아진 점
- migration이 크게 감소
- goodput이 유지/개선
- resource index 개선

### 새 문제
- HBM pressure violation 증가

즉 C1-R은 너무 자주 이동하던 문제를 해결했지만, **hold가 과도하면 pressure relief가 늦어진다.**

## C2-R

### 좋아진 점
- fallback storm 제거
- migration 크게 감소
- throughput ★☆☆ → ★★☆
- runtime mismatch 반복 fallback 거의 제거

### 남은 문제
- HBM pressure violation이 0.1889 → 0.2096으로 증가
- Heavy Goodput 목표 0.95에 0.0018 부족
- RUI 목표 0.78에 0.0107 부족
- 남은 fallback 대부분이 `hard_feasibility_empty`

즉 이제 C2의 핵심 문제는 “prediction이 틀려서 계속 흔들림”에서 **“현재 HW/SLO에서 실행 가능한 tier가 실제로 존재하는가”**로 바뀌었다.

---

# 7. 다음 보완 설계 방향

## 7.1 C1-R2 — Pressure-aware Stability

C1-R의 migration suppression은 유지하되, predicted pressure가 급격히 올라가면 residency/hysteresis를 우회한다.

```text
Normal
  Current-tier hold

Predicted pressure > emergency threshold
  ↓
Residency bypass
  ↓
가장 큰 pressure relief / migration-cost 비율의 object만 선택 이동
```

즉 “많이 이동하지 않되, 진짜 pressure가 올 때는 필요한 만큼만 이동”하는 방향이다.

평가 목표:

- C1-R migration 수준을 크게 넘지 않음
- HBM pressure violation을 C1 baseline 수준(≈0.13)에 가깝게 회복

## 7.2 C2-R2 — Infeasible-state Aware Selector

`hard_feasibility_empty`를 일반 fallback으로 다루지 않는다.

상태를 명시적으로 분리한다.

```text
FEASIBLE
  → normal Data-aware placement

TEMPORARILY_INFEASIBLE
  → best-effort tier hold
  → resource/SLO condition change event에서만 retry

STRUCTURALLY_INFEASIBLE
  → placement policy 문제가 아니라 HW/SLO mismatch로 report
```

이렇게 하면 policy가 해결할 수 없는 cell에서 불필요한 reevaluation을 없앨 수 있다.

## 7.3 C2-R2 — Low-confidence Conservative Envelope

Classifier confidence가 낮을 때 하나의 잘못된 class를 믿고 fallback하는 대신, plausible class들의 공통 safe tier를 찾는다.

예:

```text
P(KV)=0.55
P(AgentMemory)=0.30
P(ToolResult)=0.15

각 class의 feasible set 계산
        ↓
공통 safe subset 또는 worst-case cost 최소 Tier
        ↓
history가 쌓이면 정상 C2 path로 전환
```

목표는 남은 2,365개의 low-confidence fallback을 줄이는 것이다.

## 7.4 RAG Workload Model 분리

현재 8 TiB RAG scenario는 전체 index scan에 가까운 stress model이다.

실제 Vector DB에서는 ANN / partition / candidate filtering 때문에 query당 전체 DB를 읽지 않는 경우가 많다.

따라서 다음 단계에서는 SSD-PIM GEMV 자체의 효과를 더 정확히 보기 위해:

- index size
- query concurrency
- **scan fraction / candidate-set size**

를 별도 축으로 둔다.

이것은 C2 policy tuning이 아니라 **workload model refinement**다.

---

# 8. 현재 시점의 결론

1차 C1/C2 비교에서는 C1이 aggregate 안정성이 높았고 C2는 fallback/migration storm 때문에 성능이 낮았다.

1차 보완 이후:

- **C1-R**: 안정성 보완 성공. Migration -88.5%, Goodput +6.5%.
- **C2-R**: 구조적 문제였던 fallback storm을 대부분 제거. Fallback -81.2%, Migration -76.5%, Heavy Goodput +10.2%, Throughput 별점 ★☆☆→★★☆.

따라서 최초 결과만 보고 C2를 폐기하는 것은 타당하지 않다. C2의 성능 저하는 Data-aware 접근 자체보다 **feasibility check 순서와 state stability 설계 부족**의 영향이 컸다.

반대로 C2-R이 개선됐어도 아직 C1-R보다 구조가 복잡하고, HBM pressure 및 infeasible-state 처리가 남아 있다.

이 시점에서의 다음 비교는:

```text
C1-R2:
Stable Resource-centric
+ emergency pressure escape

vs

C2-R2:
Feasibility-first Data-centric
+ explicit infeasible-state
+ conservative low-confidence handling
```

으로 진행하는 것이 적절하다.
