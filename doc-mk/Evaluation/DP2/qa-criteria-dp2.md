# DP2 QA Criteria

> 상태: **proposal** (소유자 확정 전, 결과 측정 전에 확정해야 한다). 공통 QA 문서(`../qa-evaluation-criteria.md`)는 바꾸지 않으며, DP2 전용 정의와 새 QA(QA5)를 여기에 둔다 (SKILL H11).
>
> 결과를 본 뒤 정의를 바꾸면 사유와 이전 값을 결과 문서 한계에 기록하고 `defined_after_first_look`로 공개한다 (SKILL H16).

# 1. 적용 QA

| QA | 공통 정의 | DP2 적용 |
|---|---|---|
| QA1 Throughput | 공통 §4 (Max SLO Goodput, 별 0.90/1.10 x T_ref) | 그대로 |
| QA2 Latency | 공통 §5 (TTFT/TPOT P99, 별 기준) | 그대로. TTFT와 TPOT를 별도 행으로 보고 (P99, P50) |
| QA3 Resource Utilization | 공통 §6 (useful utilization, 별 65/85%) | DP2 metric은 §2 |
| QA4 Modifiability | 공통 §7 (module 수 기준) + SKILL H21 (module·공수·에이전트 비용) | DP2 변경 시나리오는 `benchmark.md` §7 |
| QA5 Scalability | **DP2 전용 신규** | §3 |

결과 표는 공통 §10 형식(`정량 값 (Baseline 대비 배수)`, 시스템 표기)을 따른다. 여러 시나리오·시스템은 쌍별 값의 기하평균으로 합친다.

# 2. QA3 — DP2 Resource Utilization

DP1의 QA3(HBM 사용량)와 달리 DP2는 실행 위치가 바뀌어 P/D 풀 사용률이 후보마다 달라지므로, 공통 §6의 DP2 항목(Prefill/Decode 노드 사용률 등)을 headline으로 쓴다.

| 구분 | metric | 방향 | 용도 |
|---|---|---|---|
| **headline (별점)** | **useful P/D 풀 평균 GPU 사용률 (%)** | ↑ | 공통 §6 별 기준 (<65 / 65~85 / ≥85) |
| 진단 | 노드 간 부하 불균형 (노드별 큐 깊이·사용률의 CV) | ↓ | 결정 시점별 stale·herding 영향 |
| 진단 | Turn당 노드 간 KV 이동량 (GiB) | ↓ | Cost Model의 이동 비용 반영 여부 |
| 진단 | 노드 간 링크 사용률, GPU idle 비율 | — | 원인 분석 |

**임시 정의 (SKILL H8, 공통 문서에 없음)**

```text
U_useful = Σ_iteration ( iteration 시간 × [SLO 충족 요청 토큰 비중] )
           / ( 노드 수 × 측정 시간 )          # 노드·풀별로도 계산 (m0-spec §8)
```

- SLO 위반 요청이나 과도한 전송으로 얻은 사용률은 useful로 세지 않는다 (공통 §6).
- 자원 지표는 "비우되 성능이 나빠지는 정책"이 유리해질 수 있으므로 QA1/QA2와 함께 읽는다 (SKILL H20 취지).
- 고정 부하 한 점이 아니라 **부하 sweep에서의 값**으로 보고한다. Throughput과 겹치는 부분(포화 지점 이후의 차이)은 진단으로 구분해 해석한다.

# 3. QA5 — Scalability (신규, DP2 전용)

공통 문서 §9 형식을 따른다.

| 항목 | 내용 |
|---|---|
| **QA Name** | Scalability (DP2 전용) |
| **1. Motivation** | DP2 후보 공간은 `\|N_p\|×\|N_d\|×Tier 수`로 커진다. C1은 결정이 scheduler critical path에 있고 C2는 planning을 독립 worker로 확장할 수 있다는 것이 두 후보의 핵심 trade-off이므로 이를 정량으로 검증한다 |
| **2. Metric** | M1 **scaling efficiency** η(N) = Max SLO Goodput(N 노드) ÷ ( N/2 × Max SLO Goodput(1P+1D) ), N = 32 노드. M2 **결정 지연** P99 (ms)를 후보 수 K에 따라 보고. M3 scheduler step 시간 증가율 (%) |
| **3. Unit** | η: 무차원, M2: ms, M3: % |
| **4. Threshold (제안값)** | ★ η < 0.70 / ★★ 0.70 ~ 0.90 / ★★★ ≥ 0.90. 별은 M1로 매기고 M2, M3는 병기한다. **제안값이며 소유자 확정과 사전 등록이 필요하다** |
| **5. Measurement** | `benchmark.md` §6의 격자(노드 수 2~64, Tier 수 1~4, planner worker 1~16, top-k on/off). 노드당 offered load 동일. Baseline(고정 규칙)의 η도 보고해 배수를 병기 |
| **6. Applicable DP** | DP2 |
| **7. Evidence** | [B+C]. **결정 비용 모델(후보당 µs~ms)이 가정이므로** 실제 Planner 프로토타입의 [A] 측정이 없으면 비용 0.1 / 1 / 10 ms에 대한 민감도로 보고하고 결론을 그 범위에서만 주장한다 |
| **8. Diagnostics** | planner 처리량 (decisions/s), plan cache hit율, re-plan 비율, top-k 사용 시 regret |

# 4. 진단 지표 (별점에 쓰지 않음)

| 지표 | 정의 | 읽는 QA |
|---|---|---|
| Decision Latency | 결정 1건이 scheduler step에 더하는 시간, step 시간 증가율 | QA2(TTFT 분해 항, TPOT step 지연), QA1 |
| Decision Quality | regret = Cost(선택) − Cost(실행 시점 oracle), mis-selection 비율, plan age 분포, re-plan 비율 | QA1/QA2 원인 분석 |
| TTFT 분해 | `T_schedule`, `T_decision`, `T_queue`, `T_move`, `T_prefill` | QA2 |
| Cost Model 오차 sweep | 오차 ε (lognormal σ) 0 / 0.2 / 0.4 / 0.6 (SKILL H17) | 전체 |

Decision Quality는 **같은 Cost Model로 oracle과 비교**해 결정 시점의 효과만 분리한다. Cost Model 자체의 예측 정확도는 별도 변수(ε sweep)다.

# 5. 집계와 선택

- QA1: 시나리오별 ratio의 기하평균. QA2: P50/P95/P99 개선 배수의 기하평균(TTFT, TPOT 각각 보고). 집계는 comparison-valid 시나리오 기준이며 제외한 시나리오와 사유를 적는다 (DP1과 동일 규칙).
- DP2 전용 별점을 공식으로 쓰는 것은 사용자가 결정했을 때만이며, 쓰면 공통 별점을 병기하고 경계 sensitivity를 보고한다 (SKILL H11).
- 선택 규칙은 `qa_priority.json`(미작성, 소유자 확정 전에는 "proposal")과 `tools/dp_selection.py`를 따른다 (SKILL H13).
