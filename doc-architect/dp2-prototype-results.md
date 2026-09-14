# DP2 프로토타입 결과

`dp2-prototype-spec.md`에서 고정한 지표/시나리오로 `python -m dp2_placement.run_eval --all`을 실행한 결과다. 원자료는 [`results/dp2_results.json`](results/dp2_results.json)에 커밋되어 있다.

---

## 1. Performance Efficiency 결과

`objective_seconds`를 `always_local`(As-Is) 대비로 정규화. 낮을수록 좋다.

| scenario | always_local | c1_rule_based | c2_cost_aware | C2−C1 (paired) | 판정 |
|---|---:|---:|---:|---:|---|
| `low_variation` | 1.0000 | 0.6542 [0.6317, 0.6767] | 0.2683 [0.2651, 0.2714] | −0.3859 [−0.4091, −0.3627] | **c2_cost_aware** |
| `high_variation` | 1.0000 | 0.7154 [0.6937, 0.7372] | 0.5392 [0.5075, 0.5708] | −0.1763 [−0.1920, −0.1605] | **c2_cost_aware** |

두 시나리오 모두 신뢰구간이 0을 지나지 않는다 — C2가 C1보다 실행 효율이 유의하게 낫다. 다만 격차는 **워크로드 변동성이 낮을수록 더 크다**(−0.386 vs −0.176): `low_variation`에서는 배경 Decode Load가 완만해 C1의 정적 Rule이 상대적으로 자주 틀리고, `high_variation`에서는 Runtime State 자체가 더 불안정해 두 후보 모두 정확도가 흔들리면서 격차가 줄어든다. **워크로드가 격렬하게 변할수록 Runtime State를 보는 이점이 커진다는 원래의 직관과는 반대 방향**이다 — 이는 §5의 한계(Oracle이 C2의 Cost Model과 동일함)와 함께 읽어야 한다(아래 §5 참조).

### Node Count Sweep

| p_count | c1_rule_based (relcost) | c2_cost_aware (relcost) |
|---:|---:|---:|
| 2 | 0.7179 | 0.5456 |
| 4 | 0.7154 | 0.5392 |
| 8 | 0.7145 | 0.5372 |
| 16 | 0.7145 | 0.5372 |

P Node가 늘어날수록 C2의 objective가 조금씩 개선되다가(더 나은 후보를 고를 확률이 커짐) 8개 이후로는 정체된다 — 이 워크로드(step당 도착률 0.3, D Node 4개, 100 step)가 만드는 요청량이 8개보다 많은 P Node를 실제로 필요로 하지 않기 때문이다. `node_count` 자체는 8→16에서 어느 후보의 objective도 바꾸지 않았다.

---

## 2. Scalability 결과

`decision_ops_per_placement`을 `c1_rule_based` 대비로 정규화(`always_local`은 아무것도 읽지 않아 분모가 0이 되므로 쓸 수 없다 — `dp2-prototype-spec.md` §3 참조).

| scenario | c1_rule_based | c2_cost_aware |
|---|---:|---:|
| `low_variation` | 1.0000 | 1.2479 [1.2403, 1.2555] |
| `high_variation` | 1.0000 | 1.2747 [1.2623, 1.2870] |

### Node Count Sweep

| p_count | c1_rule_based | c2_cost_aware |
|---:|---:|---:|
| 2 | 1.0000 | 0.8112 |
| 4 | 1.0000 | 1.2747 |
| 8 | 1.0000 | 2.2017 |
| 16 | 1.0000 | 4.0558 |

**`dp2-agent-prefill-placement.md` §6~8, §10에서 서술로만 주장했던 것이 그대로 측정됐다**: C1의 decision cost는 P Node 수와 무관하게 정확히 1.0x(`test_c1_decision_cost_is_independent_of_p_node_count`), C2는 Candidate 수에 선형으로 증가한다(0.81x → 4.06x, p_count 2→16). C2는 매 Candidate마다 `observation_of()` 1회 + `total_cost()` 1회를 반드시 호출하기 때문이다(§2.3 UML 참조).

### Memory Resource Sweep

| tier 구성 | c1_rule_based | c2_cost_aware |
|---|---:|---:|
| `hbm, dram` (2종) | 1.0000 | 1.2775 |
| 전체 6종 | 1.0000 | 1.2747 |

**예상과 다른 결과**: Memory Resource(tier 종류) 수는 decision cost를 거의 바꾸지 않았다(1.2775 vs 1.2747, 0.3%p 차이). 이유는 §5에서 설명한다.

---

## 3. Functional Correctness 결과

`regret_seconds` = 선택한 노드의 실제 Cost − Oracle의 Cost(byte-weighted). `oracle_match_rate`는 Oracle과 같은 노드를 고른 비율.

| scenario | always_local match | c1 match | c2 match | always_local regret | c1 regret | c2 regret |
|---|---:|---:|---:|---:|---:|---:|
| `low_variation` | 0.0000 | 0.1771 [0.1430, 0.2113] | **1.0000** | 0.1219 | 0.0642 [0.0595, 0.0690] | **0.0000** |
| `high_variation` | 0.1271 [0.0747, 0.1795] | 0.3066 [0.2322, 0.3810] | **1.0000** | 0.2881 | 0.1136 [0.0883, 0.1390] | **0.0000** |

C2의 match rate가 정확히 1.0, regret이 정확히 0인 것은 우연이 아니라 **구조적으로 그렇게 되어야 한다** — `experiments.build_policies()`가 C2에게 Oracle을 계산할 때와 동일한 `CostModel` 인스턴스를 준다(§5에서 왜 이게 문제가 아니라 의도인지 설명). C1은 Runtime State를 전혀 안 보므로 Oracle과 항상 어긋나지는 않지만(0.18~0.31 사이에서 우연히 맞는 경우도 있음), 대부분 틀린다. `always_local`은 D Node가 마침 최적인 소수의 경우에만 우연히 맞는다.

---

## 4. 무결성

이 프로토타입에는 Capacity 기반 rejection이 없다(모든 Candidate가 항상 실행 가능) — `dp2-prototype-spec.md` §7에서 미리 밝힌 대로, 무결성 검증 항목에서 rejection 관련 항목은 해당 없음으로 처리한다. 실제로 13개 조건(시나리오 2개 + sweep 값 4+2개) 전부 예외 없이 완료됐다.

---

## 5. 유효 범위와 한계 (결과 해석에 중요)

**C2의 Cost Model이 Oracle과 동일하다.** §3의 결과가 보여주듯 C2의 "정확성"은 이 프로토타입 안에서는 항상 만점이다. 이는 **C2가 실제로 옳다는 증거가 아니라, C2와 Oracle이 같은 함수를 계산한다는 사실의 재확인**이다. 이 지표가 실제로 검증하는 것은 "C1이 Runtime State를 안 보면 얼마나 자주/얼마나 크게 틀리는가"이며, "C2가 실제 시스템에서도 옳은가"는 여기서 답할 수 없다(그러려면 C2의 Cost Model 자체에 대한 별도의 estimation-error 축이 필요하며, DP1의 data-first 후보처럼 예측이 개입해야 성립하는 질문이다 — 이번 스코프에는 없음).

**Decision Cost(Scalability)가 Objective(Performance Efficiency)에 되먹임되지 않는다.** §2에서 C2의 decision cost가 node_count=16에서 4배로 늘어도, §1의 objective는 전혀 나빠지지 않는다 — 이 시뮬레이션은 Decision 계산 자체에 걸리는 실제 시간(CPU 시간, Scheduler Latency)을 objective_seconds에 포함하지 않기 때문이다. 실제 시스템이라면 Candidate가 매우 많아질 때 Decision Latency 자체가 Prefill 착수를 늦춰 Performance Efficiency를 깎아먹을 수 있는데, 이 프로토타입은 그 경로를 모델링하지 않는다. **따라서 Scalability 결과를 "C2가 Node 수 증가에 취약하다"는 것 이상으로, "그래서 결국 C2가 손해를 본다"까지 확장해 해석하면 안 된다** — 이 프로토타입은 후자를 측정하지 않는다.

**Memory Resource Sweep이 Scalability에 영향을 주지 않은 이유.** `cost_model.CostModel.data_cost()`는 Request가 선언한 KV Location **하나**만 읽는다 — Candidate Node를 채점할 때 클러스터에 존재하는 다른 Tier의 상태를 조회하지 않는다. 그래서 Tier 종류가 2개든 6개든 decision_ops_per_placement는 그대로다. `dp2-agent-prefill-placement.md` §6.3/§8이 "Memory Resource 증가"를 Decision Overhead 증가 요인으로 함께 언급한 것과 어긋나는 결과인데, 이는 설계 문서가 옳고 이 프로토타입이 그 경로를 구현하지 않은 것이다 — Memory Resource 수가 실제로 Decision Cost를 늘리려면 Candidate 채점 시 "이 KV가 각 Tier에서 재접근 가능한가"를 Tier 개수만큼 조회하는 구조가 필요하며, 이번 스코프의 `CostModel`은 그렇게 만들지 않았다. §7에 후속 과제로 남긴다.

**상수는 대표값이다.** `cost_model.py`의 `QUEUE_WAIT_PER_ITEM_SECONDS`, `PREFILL_TOKENS_PER_SECOND`, `KV_BYTES_PER_TOKEN`, `NodeFabric`의 대역폭/지연은 실측이 아니라 문서화된 가정값이다(`dp2-prototype-spec.md` §2). `DECODE_TPOT_BASELINE_SECONDS`/`DECODE_TPOT_INFLATION_FACTOR`만 설계 문서의 예시(30ms→90ms)를 그대로 재사용했다.

**규모.** 100 step, 조건당 10 paired seed, 시나리오당 약 120~340 요청(변동성에 따라 다름). DP1의 20 seed보다 축소된 스코프다.

---

## 6. QA 3개 평가

| QA | 결론 | 근거 |
|---|---|---|
| **Performance Efficiency** | C2가 두 시나리오 모두에서 유의하게 낫다(CI가 0을 지나지 않음). 격차는 `low_variation`(−38.6%p)에서 `high_variation`(−17.6%p)보다 크다 | §1 |
| **Functional Correctness** | C1은 Runtime State를 안 봐서 규칙적으로 Oracle과 어긋난다(match rate 0.18~0.31, regret > 0). C2는 구조적으로 Oracle과 일치(§5의 한계 참조) | §3 |
| **Scalability** | C1의 decision cost는 Node 수와 무관하게 1.0x. C2는 Node 수에 선형 증가(0.81x→4.06x, p_count 2→16). Memory Resource 수는 이 Cost Model 구현에서는 영향 없음(§5) | §2 |

세 QA를 종합하면: **설계 문서 §10의 예상 Trade-off가 이 프로토타입에서 그대로 재현됐다** — C1은 Decision Overhead가 낮고 Node 수 증가에 안전하지만 Runtime 변화에 규칙적으로 틀리고, C2는 정확하지만 Candidate가 늘수록 Decision Cost가 커진다. 단, 이 스코프에서는 Decision Cost 증가가 Objective에 되먹임되지 않으므로 "C2가 어느 시점부터 손해를 보는 Crossover"는 이 프로토타입만으로는 관찰되지 않았다(§5).

---

## 7. 설계 문서에 반영할 것

1. **Memory Resource 증가가 Scalability에 실제로 영향을 주려면** Candidate 채점 절차에 Tier별 조회를 명시적으로 포함해야 한다 — 현재 `dp2-agent-prefill-placement.md` §6.3/§8의 서술은 이 프로토타입의 `CostModel` 구현과 맞지 않는다.
2. **Decision Cost를 Objective에 되먹이는 모델**이 있어야 "C2가 언제부터 손해인가"라는 Crossover 질문에 답할 수 있다. 현재는 두 지표가 독립적으로 보고되어 이 질문에 답하지 못한다.
3. **C2의 Functional Correctness 결과는 "C2가 항상 옳다"로 인용하면 안 된다.** Oracle과 Cost Model이 동일해서 나온 구조적 결과이지, 실제 시스템에서의 정확성 증거가 아니다.

---

## 8. 재현

```bash
cd doc-architect
PYTHONPATH=. python -m dp2_placement.run_eval --all
```
