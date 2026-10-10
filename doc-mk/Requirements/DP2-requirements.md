# DP2 요구사항 도출: 기능 요구사항, 품질 속성, 품질 시나리오, 제약 사항

> 상태: **초안(제안)**. `requirements-derivation` 스킬 Phase 2 (survey 단계). DP 번호는 최종 번호([`project-context.md`](project-context.md) §0): **DP2 = Prefill/Decode 실행 위치 결정 구조**. 과제 시나리오와 UC는 [`usecases.md`](usecases.md).
> **[2026-10-09 방침 변경]** 품질 시나리오(§4)의 **수치 임계값과 "현 평가값"은 폐기 예정 입력**이다. 사용자 결정에 따라 전 DP(DP1~DP4)를 훑은 뒤 품질 요구사항을 **일관된 기준으로 다시 작성**한다(`memo-threshold-unification.md`, `dp-evaluation-inventory.md`). 현재 유효한 것은 **FR, QA, 제약, 품질 시나리오의 6요소와 metric 정의**이며 §4의 숫자는 참고로만 본다.
> **이 문서의 모든 수치 임계값은 `[임시]`다.** 사용자 결정(2026-10-09, [`memo-threshold-unification.md`](memo-threshold-unification.md))에 따라 정량 조건은 모든 DP를 훑은 뒤 하나의 규칙으로 통일한다. 여기 적은 값은 DP2의 기존 평가 기준을 옮겨 적은 **작업용 값**이며 확정이 아니다. 근거 라벨: `[기준]`(공통·DP2 평가 문서) / `[DP문서]` / `[가정]` / `[임시]`(통합 전 작업값).
> 출처: `DP문서`(위치 표기) / `도출` / `사용자`. 상태: `문서 확정` / `제안`. 시뮬레이션 값은 모두 [B+C]이며 실측 [A]가 아니다(GC-1).

## 0. 읽은 입력

| 구분 | 파일 | 읽은 범위 |
|---|---|---|
| 설계 | `DP2/dp2-prefill-decode-execution-planning-decision-timing.md` | 전체 |
| 설계 | `DP2/dp2-qa-evaluation-rationale.md` | 전체 |
| 설계 | `DP2/vllm-cost-model-prefill-decode-execution-planning-architecture.md` (1,295줄) | §0, §1(Drivers), §8(Execution Routing), §13(Failure/Fallback), §15~16 읽음. §2~§7, §9~§12, §14, §17~18은 목차만 |
| 설계 | `DP2/dp2-cost-model-and-late-validation.md` | 전체 |
| 평가 | `Evaluation/DP2/qa-criteria-dp2.md`, `benchmark.md`, `qa4-preregistration.md`, `simulation-plan.md`, `README.md` | 전체 |
| 평가 결과 | `Evaluation/DP2/results/2026-10-06_dp2-qa-evaluation.md` | §0(최종 요약)만 |
| PPT | `DP2-appendix-qa-result.pptx`(1~2장), `DP2-cost-model-late-validation.pptx` | 텍스트 추출(그림은 못 읽음) |
| 공통 | `Evaluation/qa-evaluation-criteria.md`, `common-benchmark.md` | DP1 작업 때 읽음 |
| **읽지 못함** | `Evaluation/DP2/m0-spec.md`(316줄, 소유자 결정 O1~O11 포함), `sim-extension-scope.md`, `results/iterations/loop-log.md`, 결과 문서 §1 이후, `system-specs.md`, simulator 코드 | 필요 시 다음에 읽음 |

## 1. DP2 구조 재구성 (제약 도출용)

DP2는 **Turn 단위로 Prefill 실행 위치(n_p)와 Decode 시작 위치(n_d)를 하나의 `ExecutionPlan`으로 결정**한다. n은 `(노드, {GPU/HBM, GPU/HBF, ScHBM·CXL-PNM attention 오프로드})`다. 설계 질문은 "같은 Cost Model과 Resource Selection 정책을 쓸 때 **언제** 결정하는가"다(결정 시점 비교).

```text
Scheduler (request, token budget)
   │ Turn Work
   ▼
ExecutionPlanner ◄── ResourceStateMonitor (queue, utilization, memory pressure, Tier 용량·BW, 링크)
   │ candidate + cost + selection ◄── CostModel (compute / movement / queue / interference)
   │ ExecutionPlan = (prefill{compute,memory,group}, decode_start{...}, required_data_moves, estimated_cost)
   ▼
ExecutionRouter ──► ExecutionGroup (GPU/HBM · GPU/HBF · PNM/CXL, 동일 model weights 필수)
```

- **C1 스케줄링 시점 결정**: Scheduler가 request와 token budget을 확정한 시점에 최신 state로 inline 결정. 결정 지연이 Scheduler critical path에 들어간다.
- **C2 사전 계획 결정**: waiting 중 background planner가 ranked candidate를 `ExecutionPlanCache`에 저장, dispatch 직전 Late Validation(hard: health, n_d 용량, History KV 위치, n_p 큐 한도 / soft: Cost 재계산 tol 10%), 실패 시 백업 후보 → 동기 재계획 → 기본 vLLM GPU 경로.
- 경계: Decode 실행 중 Tier 간 KV 이동은 DP1, Cost Model 자체의 설계는 DP2가 아니다(설계 §1). 평가 결과: C1 13점, C2 13점 동점(선택 보류).

## 2. 기능 요구사항 (DP2-FR)

### 2.1 공통 (C1, C2)

| ID | 요구사항 | 출처 | 설계 매핑 | 관련 UC | 검증 방법 | 상태 |
|---|---|---|---|---|---|---|
| DP2-FR-01 | 시스템은 Turn마다 Prefill과 Decode 시작의 **실행 후보 (n_p, n_d)** 를 만들고, 각 후보가 **실행 가능**(해당 HW가 실행 가능 ∧ 동일 model weights 보유 ∧ 입력·KV에 도달 가능 ∧ 목적지 KV memory 할당 가능)한지 판정해야 한다 | DP문서 arch §1.1, §8 | Candidate Generator, ExecutionGroupRegistry | UC-1, 2, 6, 8 | 후보 feasibility 단위 테스트, weights 없는 group 후보 제외 | 문서 확정 |
| DP2-FR-02 | 시스템은 후보마다 **Cost(n_p, n_d)** 를 계산해야 한다. 항: 이 요청의 TTFT, 이 요청의 TPOT, KV 이동(History 이동과 결과 KV n_p→n_d 전달), 외부효과(n_p의 실행 중 Decode 지연, 이후 도착 요청의 TTFT 지연, n_d의 resident Decode 지연). 모든 항은 SLO 분율로 환산해 TTFT와 TPOT를 같은 척도로 더한다 | DP문서 `dp2-cost-model-and-late-validation` §1 | CostModel / Cost Evaluator | UC-8 | Cost breakdown 로그와 실제 지연 대조 | 문서 확정 |
| DP2-FR-03 | 시스템은 Prefill 위치와 Decode 시작 위치를 **하나의 plan으로 같은 시점에 결정**하고(argmin Cost, feasible 후보 우선, 없으면 위반 최소 후보), 결과를 `ExecutionPlan`(prefill, decode_start, required_data_moves, estimated_cost, decision_metadata)으로 낸다 | DP문서 decision-timing §3, §1; rationale §1 | ExecutionPlanner, Resource Selector | UC-1, 6, 8 | plan 구조 검사, argmin 재현 테스트 | 문서 확정 |
| DP2-FR-04 | 시스템은 ExecutionPlan을 **ExecutionGroup/Worker로 변환해 dispatch**하고, 평가한 후보와 실제 실행되는 resource가 **동일**해야 한다(execution consistency) | DP문서 arch §1.2, §8 | ExecutionRouter, ExecutionPlanAwareExecutor | UC-8 | plan과 실제 실행 resource 일치율 | 문서 확정 |
| DP2-FR-05 | 시스템은 plan이 요구하는 **데이터 이동**(History KV를 n_p로, 결과 KV를 n_p에서 n_d로)을 표현하고 공통 data mover에 전달해야 한다. 가능하면 Prefill과 겹쳐(layer-wise) 전송한다 | DP문서 decision-timing §1, rationale §1 | required_data_moves, KV Staging | UC-7, 8 | 전송 완료 시점과 Decode 시작 시점 | 문서 확정 |
| DP2-FR-06 | 시스템은 노드별 **queue 깊이, 사용률, memory pressure, Tier별 용량·BW, 링크 상태, 실행 중 Decode 수**를 telemetry로 수집하고 snapshot에 수집 시각을 남겨 결정의 입력으로 써야 한다 | DP문서 arch §1.1, §11 | ResourceStateMonitor, RuntimeStateStore | UC-9 | telemetry 갱신 주기, snapshot age | 문서 확정 |
| DP2-FR-07 | 시스템은 **n_d를 (노드, Tier)로 선택**해 attention 경로가 다른 Tier(GPU HBM, HBF 직접 읽기, ScHBM·CXL-PNM 오프로드)의 TPOT 하한과 용량을 반영해야 한다 | DP문서 rationale §2.3, cost-model §1.2 | Cost Model의 Tier descriptor | UC-2, 6 | Tier별 TPOT 추정 vs 시뮬레이터 기준값 | 문서 확정 |
| DP2-FR-08 | 시스템은 신규 Tier, 신규 Cost 항, 정책(Selector) 교체, 신규 telemetry 신호를 **Scheduler를 수정하지 않고** 추가할 수 있어야 한다 | DP문서 arch §1.2(Extensibility), benchmark §7, qa4-preregistration | Pluggable Memory Tier I/F, Cost Evaluator(Strategy) | UC-6 | QS-5 | 문서 확정 |
| DP2-FR-09 | 시스템은 Cost Model 실패, telemetry stale, feasible 후보 없음, target unhealthy일 때 **기존 vLLM GPU 실행 경로로 복귀**하고 요청을 실패시키지 않아야 한다 | DP문서 arch §1.2(Fallback safety), §13 | Failure/Fallback path | UC-9 | planner 중단·Cost 오류 주입(`dp2_planner_fault_fallback`) | 문서 확정 |
| DP2-FR-10 | 시스템은 **plan마다 cost breakdown, 선택 사유, 예측 대 실제 지연**을 기록해야 한다 | DP문서 arch §1.2(Explainability), §14 | Observability | 전체 | 로그 완비율 | 문서 확정 |
| DP2-FR-11 | 시스템은 결정 비용을 **bounded**로 유지해야 한다(매 scheduling step에서 호출될 수 있음). 후보 수가 늘면 후보 pruning(top-k)으로 비용 증가를 제한할 수 있어야 한다 | DP문서 arch §1.2(Hot-path overhead), benchmark §6 | Candidate Generator, top-k | UC-9 | 결정 지연 vs 후보 수 | 문서 확정(top-k는 평가 변수) |
| DP2-FR-12 | 시스템은 실행 위치(n_p, n_d)와 무관하게 **모델 출력이 같아야** 한다 | 사용자(GC-7), DP문서 decision-timing §7 | 공통 | 전체 | 출력 비교 | 문서 확정(제약으로 둠) |

### 2.2 C1 특화

| ID | 요구사항 | 출처 | 설계 매핑 | 관련 UC | 검증 방법 | 상태 |
|---|---|---|---|---|---|---|
| DP2-FR-C1-01 | 시스템은 Scheduler가 request와 token budget을 확정한 **시점에 최신 Resource State를 읽어** inline으로 plan을 결정해야 한다. 별도 plan 캐시·검증·재계획 상태는 두지 않는다 | DP문서 decision-timing §4 | Scheduler-inline decision | UC-8 | 결정 시점과 snapshot age | 문서 확정 |

### 2.3 C2 특화

| ID | 요구사항 | 출처 | 설계 매핑 | 관련 UC | 검증 방법 | 상태 |
|---|---|---|---|---|---|---|
| DP2-FR-C2-01 | 시스템은 request가 waiting일 때 **background로 plan을 계산**해 ranked candidate(백업 포함)와 plan 생성 시의 상태값을 `ExecutionPlanCache`에 저장해야 한다 | DP문서 decision-timing §5, cost-model §2.1 | Planner worker, Plan Cache | UC-8 | plan age, 백업 순위 | 문서 확정 |
| DP2-FR-C2-02 | 시스템은 dispatch 직전 **Late Validation**을 수행해야 한다. Hard 조건(노드 health, n_d 용량, History KV 위치, n_p 큐 한도)이 하나라도 어긋나면 그 후보를 무효로 하고, Soft 조건은 같은 plan의 Cost를 현재 상태로 다시 계산해 저장값의 (1 + tol) 이내일 때 유효로 한다. Cost Model 전체를 다시 돌리지 않는다 | DP문서 decision-timing §6, cost-model §2.2 | Plan Validator | UC-8, 9 | 검증 비용, 재계획 비율 | 문서 확정 |
| DP2-FR-C2-03 | 시스템은 검증 실패 시 **백업 후보 → 동기 재계획 → 기본 vLLM GPU 경로** 순으로 처리하고 `plan_age`, `snapshot_version`, `validation_result`, `replan_count`를 관리해야 한다 | DP문서 arch §13.2, cost-model §2.3 | Re-planner | UC-9 | 재계획 비율, 최종 fallback 비율 | 문서 확정 |
| DP2-FR-C2-04 | 시스템은 planning 계산을 Scheduler와 독립으로 **worker 수를 늘려 확장**할 수 있어야 한다 | DP문서 decision-timing §5, §9(QA5) | Planner worker pool | UC-9 | worker 수별 plan 처리량 | 문서 확정 |

### 2.4 과제 UC와 DP2의 관계 (`usecases.md` FR과 대조)

| 과제 FR | DP2가 담당하는 부분 | DP2가 담당하지 않는 부분 |
|---|---|---|
| FR-24, 25 (UC-8 Prefill/Decode 분리 실행) | **핵심 담당**: DP2-FR-01~05. 분리 여부는 n_p = n_d 조합을 후보에 포함하는 것으로 표현한다 | 요청 라우팅과 서버 선택 자체는 DP4(요청 조율 계층). DP2 문서는 구현 프레임워크와 독립이라 llm-d 위의 실행은 DP4의 정책 P4, P5가 경로를 맡는다 |
| FR-18~20 (UC-6 연산 가능 메모리 offload) | **연산 위치 결정(GPU vs ScHBM/CXL-PNM attention 오프로드)과 fallback**: DP2-FR-07, 09 (n_d의 Tier 선택으로 표현) | PIM/PNM kernel·compiler는 GC-5(범위 밖), 지원 연산·성능은 profile 값 |
| FR-1~5 (UC-1 세션 재개) | 재개 Turn에서 **History가 하위 Tier에 있을 때 Prefill을 D에서 할지 P에서 할지** 결정(`dp2_turn_*`) | Tier 간 이동(prefetch 포함)은 DP1 |
| FR-7, 8 (UC-2 long-context) | `dp2_long_ctx_decode_offload`: HBM 초과분을 ScHBM 오프로드나 다른 D 노드로 보내는 선택 | KV Drop은 DP3 |
| FR-21~23 (UC-7 노드 간 KV 이동) | 노드 간 전송 **비용을 Cost에 반영**(`Tmove`) | 전송 실행과 공유 메모리 일관성은 DP4/DP6 |
| FR-26~28 (UC-9 혼합 부하) | n_p 포화·D 유휴 등 **P/D 풀 균형**(DP2-FR-06, 11) | 과부하 admission, 우선순위는 DP4 |
| FR-6 (출력 불변) | DP2-FR-12 | — |

## 3. 품질 속성 (QA)

### 3.1 (a) DP2가 선정한 QA

DP2 설계 문서 §7과 `qa-criteria-dp2.md`가 정한 6개다(Functional Correctness는 QA가 아니라 제약으로 둠). 이름·지표는 원문을 따른다.

| ID | QA | metric (원문) | DP2 별점 기준(사전 등록 `qa-criteria-dp2.md` §6, **DP1 값을 그대로 가져옴**) | ISO/IEC 25010:2023 매핑 |
|---|---|---|---|---|
| DP2-QA1 | Throughput | Max SLO Goodput (tok/s) | Baseline 대비 ratio: ★ < 0.97 / ★★ 0.97~1.30 / ★★★ ≥ 1.30 | Performance efficiency > Capacity (Time behavior 겸) |
| DP2-QA2 | Latency (TTFT, TPOT 분리) | P99·P50. 6개 지표 개선 배수 geomean, TTFT·TPOT 개선 배수 병기 | ★ < 0.95 / ★★ 0.95~1.25 / ★★★ ≥ 1.25. 공통 절대: TTFT P99 ≤ 2 s, TPOT P99 ≤ 50 ms | Performance efficiency > Time behavior |
| DP2-QA3 | Resource Utilization | **useful P/D 풀 평균 GPU 사용률(%)**, `U_cand / U_base` (임시 정의) | ★ < 0.95 / ★★ 0.95~1.25 / ★★★ ≥ 1.25. 공통 절대 65/85% 병기 | Performance efficiency > Resource utilization |
| DP2-QA4 | Modifiability | 변경 module 수, 공수(MM), 에이전트 비용($). 시나리오 4종(신규 Tier, 신규 Cost 항, 정책 교체, 신규 telemetry 신호) 평균. DP1·DP4와 같은 공식 | M1 ≤2/3~5/≥6, M2 ≤0.5/≤1.0/>1.0 MM, M3 ≤$3/≤$10/>$10 | Maintainability > Modifiability·Modularity, Flexibility > Adaptability(신규 Tier) |
| DP2-QA5 | Scalability (**DP2 전용 신규**) | η(N) = Max SLO Goodput(N 노드) ÷ (N/2 × Max SLO Goodput(1P+1D)), N = 32. 보조: 결정 지연 P99, scheduler step 시간 증가율 | ★ η < 0.70 / ★★ 0.70~0.90 / ★★★ ≥ 0.90 (**제안값, 소유자 확정 전**) | Flexibility > **Scalability** (2023판 신설 하위 특성) |

QA 우선순위(`qa_priority.json`)는 미작성. 후보 선택은 보류(별 합계 13 대 13 동점).

### 3.2 (b) 추가 후보 QA (ISO/IEC 25010:2023 목록 안)

설계 문서가 이미 언급한 것(arch §1.2의 Architectural Drivers 6개)과 도출한 것을 구분해 적는다.

| ID | ISO 특성 > 하위 특성 | 후보 | 출처 | 관련 이유 | 미선정 시 위험 | 선정 QA와의 관계 | 의견 |
|---|---|---|---|---|---|---|---|
| DP2-QA6 | Performance efficiency > Time behavior | **결정 지연(Hot-path overhead 제한)** | DP문서(arch §1.2, 진단 지표로만 둠, QA 아님) | 설계 §7이 Decision Latency를 "TTFT 분해 항이라 독립 QA로 두지 않음"으로 정리. 그러나 C1의 핵심 약점이고 QA5(Scalability)와 겹침 | C1이 critical path 지연으로 TTFT·TPOT·처리량을 해쳐도 별점에 직접 보이지 않음 | QA2의 분해 항, QA5의 보조 지표와 중복 | **권장**(QA5와 합쳐 하나의 시나리오로) |
| DP2-QA7 | Reliability > Fault tolerance, Recoverability | **Fallback safety** | DP문서(arch §1.2, §13) | planner 중단·Cost 오류·telemetry stale·노드 열화(`dp2_planner_fault_fallback`, `dyn_p_node_degrade`). device runtime 오류·복구는 GC-3로 제외, **우리 계층의 대응만** | planner 장애가 serving 중단으로 이어짐 | QA1/QA2와 연계(fallback 시 성능 하한) | **권장** |
| DP2-QA8 | Functional suitability > Functional correctness | **Execution consistency**(평가한 후보 = 실제 실행 resource) 와 출력 불변 | DP문서(arch §1.2). 출력 불변은 설계가 제약으로 둠 | plan과 dispatch 불일치, C2 stale plan으로 잘못된 resource 실행 | 사용자는 느린 결과가 아니라 틀린 resource 실행을 본다 | 다른 QA의 사전 조건 | **권장** |
| DP2-QA9 | Functional suitability > **Functional appropriateness** | **Decision Quality**(Oracle 대비 regret, 오판 비율, Cost Model 오차 ε 강건성) | DP문서(진단 지표: regret, mis-selection, plan age, ε sweep). QA는 아님 | 결정이 얼마나 최적에 가까운가가 C1/C2 우열의 원인 변수 | 성능 차이의 원인을 구분하지 못함 | QA1·QA2의 원인 변수 | **권장** |
| DP2-QA10 | Maintainability > Analysability | **Explainability**(cost breakdown 로그) | DP문서(arch §1.2) | `dp2-qa-evaluation-rationale` §3.2: 요청 단위 지연은 정상인데 시스템 단위만 나빠지는 경우 진단 | 결정이 틀린 이유를 알 수 없음 | 모든 QA의 검증 수단 | **권장** |
| DP2-QA11 | Compatibility > Interoperability | vLLM Scheduler/Executor와 DP1, DP4 접점 계약 | 도출 | arch §15의 vLLM 변경 지점, DP1(Decode 중 Tier 이동), DP4 정책 P4·P5 | 접점이 깨져도 DP2 단독 평가에 안 보임 | QA4와 일부 겹침 | **보류**: 평가 기준 없음, 제약으로 기록 |
| (제외/해당 없음) | Security, Interaction capability, Safety | — | — | 프로젝트 범위 밖(GC-6)·UI 없음 | — | — | 제외 |

## 4. 품질 시나리오 (6요소)

공통: 환경은 **SYS-H100, SYS-B200**(노드 = 8-GPU TP8 1 인스턴스, 6종 메모리, Llama-3.1-70B BF16), 기본 SLO는 TTFT P99 ≤ 2 s, TPOT P99 ≤ 50 ms, **노드 간 링크는 RDMA 50 GB/s `[ASSUMED, 평가 문서]`**(사용자 환경의 PCIe 64 GB/s와 다름, GC-9, §6 D-3), 비교 대상은 **Baseline-PD-fixed**(Prefill은 항상 P, Decode는 항상 D, KV Tier 미고려)다. 현 평가값은 `2026-10-06_dp2-qa-evaluation.md` §0.1(38쌍, seed 5개, 시뮬레이션 [B+C])이다. 임계값은 모두 `[임시]`이며 통합 단계에서 다시 정한다.

#### DP2-QS-1 Throughput — 링크 경합과 Prefill 포화 상황의 처리량 (선정, DP2-QA1 · ISO: Capacity)
| 요소 | 내용 |
|---|---|
| 1. 자극 유발원 | 다수의 멀티턴 agent 요청 클라이언트 |
| 2. 자극 | P↔D 링크를 다른 트래픽과 공유해 대역폭이 25%로 저하(`dp2_internode_link_contention`)하거나 Prefill burst로 P 노드가 포화(`dp2_prefill_burst_p_saturated`). 부하 sweep |
| 3. 환경 | 정상 운전, 2P+2D 규모, SYS-H100과 SYS-B200, 링크 50 GB/s(→ 12.5로 저하) |
| 4. 자극 대상체 | ExecutionPlanner(Candidate Generator, Cost Model, Resource Selector)와 ExecutionRouter |
| 5. 응답 | History를 왕복 전송하는 대신 로컬 실행을 선택하고, 포화된 P를 피해 여유 노드에서 Prefill해 SLO를 지킨다 |
| 6. 응답 측정 | **Max SLO Goodput ≥ 1.30 × Baseline-PD-fixed** `[임시: DP2 기준, DP1 값 차용]`(comparison-valid 쌍 geometric mean, seed ≥ 5). 진 쌍 0 `[기준: 잡음 하한 0.97]` |
| 현 평가값 | C1 x1.66, C2 x1.66 (954/956 tok/s 대 575). **Baseline이 SLO를 거의 못 지키게 설계된 시나리오(링크 경합 x6~8, 긴 History x3~4)가 끌어올린 값**이며 중앙 시나리오는 x1.0~1.7 [B+C] |
| 연결 | QA: DP2-QA1. UC-8, 9. FR: DP2-FR-02, 03, 06. 평가: `benchmark.md` §4 |

#### DP2-QS-2 Latency (TTFT) — 하위 Tier에 있는 History로 세션 재개 (선정, DP2-QA2 · ISO: Time behavior)
| 요소 | 내용 |
|---|---|
| 1. 자극 유발원 | agent 요청 클라이언트(tool 결과를 들고 같은 세션의 다음 Turn 요청) |
| 2. 자극 | History 64K~128K 토큰이 D 노드의 DRAM, HBF, SSD-PIM에 있고 Tool 결과 0.5K~2K 토큰이 추가된 Turn(`dp2_turn_dram_small_tool`, `dp2_turn_hbf_hist`, `dp2_turn_ssd_hist`) |
| 3. 환경 | 정상 운전, 2P+2D, 링크 50 GB/s, History 위치는 외부 배치로 주어짐 |
| 4. 자극 대상체 | ExecutionPlanner(Cost의 `Tmove`, `Tprefill` 항)와 Resource State |
| 5. 응답 | Tier별 이동 비용과 D의 Decode 부하를 비교해 Prefill을 D 로컬 또는 P에서 하도록 결정해 History 전체의 왕복을 피한다 |
| 6. 응답 측정 | **TTFT P99 ≤ 2 s** `[기준: 공통 SLO]`, **6지표(TTFT·TPOT x P50·P95·P99) 개선 배수 geomean ≥ 1.25** `[임시: DP2 기준]`. TTFT 개선 배수는 따로 보고 |
| 현 평가값 | TTFT P99: Baseline 2,461 ms(**SLO 위반**), C1 984 ms (x0.40), C2 1,015 ms (x0.41). TTFT 개선 배수 C1 x2.83, C2 x2.77 [B+C] |
| 연결 | QA: DP2-QA2. UC-1, 8. FR: DP2-FR-02, 03, 07 |

#### DP2-QS-3 Latency (TPOT) — Decode 시작 위치와 TPOT (선정, DP2-QA2 · ISO: Time behavior)
| 요소 | 내용 |
|---|---|
| 1. 자극 유발원 | long-context 세션을 재개하는 요청 클라이언트 |
| 2. 자극 | 128K~256K History, D 노드 HBM 용량이 부족(x0.3), ScHBM 오프로드 사용 가능(`dp2_long_ctx_decode_offload`) |
| 3. 환경 | 정상 운전, 1P+2D, SYS-H100과 SYS-B200 |
| 4. 자극 대상체 | Cost의 `ΔTPOT(n_d)`와 Tier descriptor(Tier별 attention 경로), Resource Selector |
| 5. 응답 | HBM이 찬 D에서 DRAM으로 흘리는 대신 다른 D의 HBM이나 같은 노드의 ScHBM 오프로드에서 Decode를 시작해 TPOT를 SLO 안에 둔다 |
| 6. 응답 측정 | **TPOT P99 ≤ 50 ms** `[기준: 공통 SLO]`. TPOT P99가 Baseline의 1.10배를 넘는 쌍 = 0 `[임시, 근거: DP1 QS와 같은 잡음 대비 여유]` |
| 현 평가값 | TPOT P99: Baseline 8.9 ms, C1 12.0 ms (**x1.34, Baseline보다 나쁨**, 단 SLO 50 ms 이내), C2 12.0 ms (x1.35). TPOT 개선 배수 C1 x0.89, C2 x0.88. Cost가 TPOT 여유를 TTFT와 맞바꾼다(결과 §0.2-4, 보완 T1). `[임시]` 기준(≤ 1.10배)은 **미충족** [B+C] |
| 연결 | QA: DP2-QA2. UC-2, 6. FR: DP2-FR-07 |

#### DP2-QS-4 Resource Utilization — 디코드 위주 부하에서 P 노드 유휴 (선정, DP2-QA3 · ISO: Resource utilization)
| 요소 | 내용 |
|---|---|
| 1. 자극 유발원 | 긴 출력(추론형) 요청 클라이언트 |
| 2. 자극 | 출력 길이 2K 토큰 위주로 D가 포화되고 P가 유휴(`dp2_decode_heavy_p_idle`, `dyn_decode_phase_shift`: 출력 256→2K 전환) |
| 3. 환경 | 정상 운전, 1P:1D, 부하 sweep |
| 4. 자극 대상체 | Resource State Monitor와 Resource Selector(P/D 풀 균형) |
| 5. 응답 | 유휴 P 노드의 Prefill·Decode 능력을 써 P/D 풀을 균형 있게 활용하면서 SLO를 유지한다 |
| 6. 응답 측정 | **`U_useful` ≥ 1.25 × Baseline** `[임시: DP2 기준]`. `U_useful` = Σ(iteration 시간 × SLO 충족 요청 토큰 비중) ÷ (노드 수 × 측정 시간)(임시 정의). 부하 sweep, 노드 간 부하 불균형 CV는 진단 병기 |
| 현 평가값 | U_useful: Baseline 43.7%, C1 67.0% (x1.52), C2 66.8% (x1.51). 공통 절대 기준(65/85%)으로는 ★★ [B+C] |
| 연결 | QA: DP2-QA3. UC-9. FR: DP2-FR-06 |

#### DP2-QS-5 Modifiability — 신규 Tier, Cost 항, 정책, telemetry 추가 (선정, DP2-QA4 · ISO: Adaptability, Modifiability, Modularity)
| 요소 | 내용 |
|---|---|
| 1. 자극 유발원 | 시스템 개발자 |
| 2. 자극 | (S1) 신규 Tier `cxl_pnm2`(내부 BW 800 GB/s)를 Decode 시작 후보로 추가. (S2) 전력 항을 Cost에 추가. (S3) Selector를 "TPOT feasible 중 TTFT 최소"로 교체. (S4) 노드 `health` 신호를 Resource State에 추가해 degraded 노드를 n_p에서 제외 |
| 3. 환경 | 개발 시점, simulator 코드 복사본에 실제 구현(사전 등록), C1과 C2 각각 |
| 4. 자극 대상체 | Pluggable Memory Tier I/F, Cost Evaluator(Strategy), Resource Selector, Resource State Monitor, (C2) Plan Validator, Plan Cache |
| 5. 응답 | Scheduler를 수정하지 않고 해당 component만 변경해 추가되고, 기존 주요 interface를 유지한다 |
| 6. 응답 측정 | 변경 **module ≤ 2, 공수 ≤ 0.5 MM, 에이전트 비용 ≤ $3**(frontier tier) `[임시: DP1·DP2·DP4 공통 사전 등록 값]`. 4개 시나리오 평균. S4 smoke: 표시 이후 새로 dispatch되는 요청에 degraded 노드가 n_p로 선택되지 않음 |
| 현 평가값 | C1 1.50 module / 0.27 MM / $1.03, C2 1.75 / 0.31 / $1.10 (둘 다 ★★★ 범위). 공수·비용은 ASSUMED 상수 기반 추정 [B+C] |
| 연결 | QA: DP2-QA4. UC-6. FR: DP2-FR-08. 평가: `qa4-preregistration.md` |

#### DP2-QS-6 Scalability — 노드 수 증가 (선정, DP2-QA5 · ISO: Flexibility > Scalability)
| 요소 | 내용 |
|---|---|
| 1. 자극 유발원 | 운영자(클러스터 증설)와 그에 비례해 늘어나는 요청 클라이언트 |
| 2. 자극 | 노드 수를 2 → 4 → 8 → 16 → 32 → 64로 늘림(노드당 offered load 동일), 노드당 Tier 수 1~4(후보 수 `|N_p|×|N_d|×Tier` 증가), planner worker 1/4/16, top-k pruning on/off |
| 3. 환경 | 정상 운전, SYS-H100과 SYS-B200, **시뮬레이션**(실환경은 서버 2대라 N=32 실측 불가), 결정 비용은 후보 수에 선형이라는 ASSUMED(0.1/1/10 ms @ 64 후보) |
| 4. 자극 대상체 | ExecutionPlanner(C1은 Scheduler critical path, C2는 Planner worker pool), Candidate Generator(top-k) |
| 5. 응답 | 후보가 늘어도 결정 비용이 병목이 되지 않아 처리량이 노드 수에 비례해 늘어난다 |
| 6. 응답 측정 | **η(N=32) ≥ 0.90** `[임시: DP2 제안값, 소유자 확정 전]`. 보조: 결정 지연 P99(ms), scheduler step 시간 증가율(%). 결정 비용 0.1/1/10 ms 민감도 병기 |
| 현 평가값 | η(N=32): Baseline 1.00, **C1 0.00**(결정 64 ms/건으로 단일 scheduler 포화), **C2 0.56**(worker 4)·0.64(worker 16). top-k=8이면 C1 1.00, C2 0.94. **목표 미달(둘 다 ★)**. η에는 ±0.1 정도의 잡음(seed 2개, 확장 부하는 1개) [B+C] |
| 연결 | QA: DP2-QA5. UC-9. FR: DP2-FR-11, C2-04. 제약: DP2-C-7, 8 |

### 4.2 추가 후보 QA (채택 전 초안)

#### DP2-QS-7 Time behavior — 결정 지연 (추가, DP2-QA6 · ISO: Time behavior)
| 요소 | 내용 |
|---|---|
| 1. 자극 유발원 | Scheduler(매 step 호출) |
| 2. 자극 | 초당 다수의 Prefill request, 후보 수 64 → 확장 시 수천(노드 수, Tier 수 증가) |
| 3. 환경 | 정상 운전, 결정 비용 가정 1 ms @ 64 후보(ASSUMED) |
| 4. 자극 대상체 | ExecutionPlanner(C1 inline, C2 lookup + Late Validation), Cost Model |
| 5. 응답 | 결정이 Scheduler step을 크게 늘리지 않고 TTFT 분해 항 `T_decision`이 작게 유지된다 |
| 6. 응답 측정 | **critical path 결정 지연 `T_decision` P99 ≤ 50 ms**(TTFT SLO 2 s의 2.5%) `[가정]`, **step 시간 증가율 ≤ 5%** `[가정]`(근거 없음, 확정 필요). C2는 Late Validation 비용 20 us `[ASSUMED]` 포함. 후보 수와 노드 수별로 보고 |
| 현 평가값 | 결정 지연: C1 64 ms(N=32, pruning 없음), C2 0.0 ms(임계 경로). 기본 조건에서는 C1/C2 차이가 성능에 드러나지 않음 [B+C] |
| 연결 | QA: DP2-QA6. FR: DP2-FR-11, C1-01, C2-02 |

#### DP2-QS-8 Fault tolerance / Recoverability — planner 장애와 노드 열화 (추가, DP2-QA7 · ISO: Reliability)
| 요소 | 내용 |
|---|---|
| 1. 자극 유발원 | planner 프로세스 중단, Cost 계산 오류, telemetry 지연, P 노드 처리량·링크 저하(장치 내부 오류는 GC-3으로 제외) |
| 2. 자극 | 실행 중간(T/2)에 planner 중단과 Cost 오류 주입(`dp2_planner_fault_fallback`), P 노드 처리량 x0.5(`dyn_p_node_degrade`), telemetry 갱신 10 ms~1 s(`dp2_stale_telemetry`) |
| 3. 환경 | 정상 운전 중 장애 발생 |
| 4. 자극 대상체 | Failure/Fallback path, Plan Validator, ExecutionRouter |
| 5. 응답 | 기존 vLLM GPU 경로(Baseline 수준)로 복귀하고 요청이 실패하지 않으며, 열화된 노드를 피해 재계획한다 |
| 6. 응답 측정 | 장애 중 **Max SLO Goodput ≥ 0.97 × Baseline-PD-fixed** `[기준: 잡음 하한]`, **실패 요청 0건**, **fallback 전환 시간 ≤ 1 s** `[가정]`(근거 없음). 복귀 후 SLO 만족 비율이 장애 전의 95%까지 회복되는 시간 ≤ 60 s `[가정]` |
| 현 평가값 | 시나리오가 정의되어 있으나 **이 문서에서는 결과 값을 확인하지 못함**(결과 §2 이후 미독). 안전성 확인용 시나리오로 분류(집계 포함) |
| 연결 | QA: DP2-QA7. UC-9. FR: DP2-FR-09, C2-03 |

#### DP2-QS-9 Functional correctness — 평가한 후보와 실행 resource의 일치 (추가, DP2-QA8 · ISO: Functional correctness)
| 요소 | 내용 |
|---|---|
| 1. 자극 유발원 | ExecutionPlanner가 만든 ExecutionPlan |
| 2. 자극 | C2에서 queue 대기 중 상태가 바뀐 stale plan, 노드·Tier 용량 변화, 백업 후보 전환 |
| 3. 환경 | 정상 운전, 부하 sweep |
| 4. 자극 대상체 | Plan Validator, ExecutionRouter, ExecutionGroupRegistry |
| 5. 응답 | 검증을 통과한 plan만 dispatch하고, dispatch된 resource는 평가한 후보와 같으며 모델 출력은 위치와 무관하게 같다 |
| 6. 응답 측정 | **plan과 실제 실행 resource 불일치 0건**, **출력 token 불일치 0건**(같은 precision, bit-exact) `[DP문서 arch §1.2, GC-7]`. S4형 누출(degraded 노드로 dispatch) 0건 `[기준: qa4 smoke]` |
| 현 평가값 | 불일치 계측은 평가 문서에서 확인하지 못함. QA4 S4에서 C2의 validator 단독은 누출 99건으로 불합격(planner view 단독은 합격) [B+C] |
| 연결 | QA: DP2-QA8. FR: DP2-FR-04, 12, C2-02 |

#### DP2-QS-10 Functional appropriateness — 결정 품질과 Cost Model 오차 강건성 (추가, DP2-QA9 · ISO: Functional appropriateness)
| 요소 | 내용 |
|---|---|
| 1. 자극 유발원 | Cost Model의 추정 오차(실제 지연과의 차이) |
| 2. 자극 | 추정 오차 ε(lognormal σ) = 0 / 0.2 / 0.4 / 0.6을 Cost에 곱함 |
| 3. 환경 | 정상 운전, 정책 상수는 재조정하지 않음(SKILL H17) |
| 4. 자극 대상체 | Cost Model, Resource Selector |
| 5. 응답 | 추정이 틀려도 Baseline보다 나빠지지 않고 Oracle에 가까운 선택을 한다 |
| 6. 응답 측정 | **ε = 0.6에서도 Max SLO Goodput ≥ 1.0 × Baseline** `[임시]`, **ε = 0에서 Oracle 대비 goodput ≥ 0.95배** `[가정]`, regret(= Cost(선택) − Cost(실행 시점 oracle)) 평균과 오판 비율을 보고 |
| 현 평가값 | ε = 0 기준 Oracle과 거의 같음(x1.66). C2/C1 goodput x1.002. ε sweep 값은 확인하지 못함. **P-retain(Prefill을 History 노드에서 유지)이 QA2에서 C1보다 높다**(x1.80 대 x1.58) — Cost의 TTFT/TPOT 가중 구조가 개선 여지 [B+C] |
| 연결 | QA: DP2-QA9. FR: DP2-FR-02, 03 |

#### DP2-QS-11 Analysability — plan 사유 추적 (추가, DP2-QA10 · ISO: Analysability)
| 요소 | 내용 |
|---|---|
| 1. 자극 유발원 | 시스템 개발자(원인 분석) |
| 2. 자극 | 시스템 단위 지표만 나빠지고 요청 단위 지연은 정상인 현상(다른 요청의 TPOT 악화, 불필요한 KV 이동) 발견 |
| 3. 환경 | 운영·평가 중, 로그 활성 |
| 4. 자극 대상체 | Observability(decision_metadata, cost breakdown, predicted vs actual) |
| 5. 응답 | plan마다 선택 사유와 항별 비용, 예측 대 실제 지연을 남겨 원인을 TTFT 분해(`T_schedule`, `T_decision`, `T_queue`, `T_move`, `T_prefill`) 항으로 분류할 수 있다 |
| 6. 응답 측정 | **plan 로그 필수 필드 완비율 100%** `[가정]`, **TTFT 분해 항 합이 실측 TTFT와 ±5% 이내인 요청 비율 ≥ 95%** `[가정]`(근거 없음, 확정 필요) |
| 현 평가값 | 시뮬레이터는 TTFT 분해를 출력함. 구현 로그는 미정 |
| 연결 | QA: DP2-QA10. FR: DP2-FR-10 |

## 5. 제약 사항 (예상 질문 기반)

| ID | 예상 질문 | 제약 문장 | 유형 | 설계 영향 | 출처 | 근거 위치 |
|---|---|---|---|---|---|---|
| DP2-C-1 | "Cost Model은 어떻게 만들었고 얼마나 정확한가?" | DP2는 **결정 시점 구조**만 비교하며 **Cost Model 자체의 설계와 정확도는 범위 밖**이다. 같은 Cost Model을 C1과 C2가 쓰고, 정확도는 오차 ε sweep의 변수로만 다룬다 | 범위 밖 | Cost Model 개선은 별도 과제. 결과는 이 Cost Model에 조건부 | DP문서 | decision-timing §1, qa-criteria §4 |
| DP2-C-2 | "Decode 중 Memory Tier 사이 KV 이동은 누가?" | **Decode 실행 중 Tier 간 KV 이동은 DP1 소관**이다. DP2는 Turn 단위로 Prefill 위치와 Decode 시작 위치만 정한다. DP2 평가는 DP1 Baseline-static 배치를 고정하고 DP1-C1 on은 민감도로만 본다 | 범위 밖/경계 | DP1 효과와 DP2 효과 분리. 실제로는 서로 영향 | DP문서 | decision-timing §1, §11 |
| DP2-C-3 | "vLLM 코드에는 어떻게 들어가나?" | DP2 결정 시점 문서는 구현 프레임워크의 호출 경로와 독립이고 **코드 레벨 매핑은 범위에서 제외**한다. 다만 아키텍처 문서(arch §15)는 vLLM 변경 지점 표를 갖고 있어 두 문서가 일관되지 않다. 아키텍처 문서의 sequence diagram, 상태 머신, 코드 변경 범위 표는 Prefill 단일 결정 기준으로 남아 있어 후속 정리가 필요하다 | 범위 밖/문서 불일치 | 구현 요구사항이 아니라 설계 참고로만 사용 | DP문서 | decision-timing §11, rationale §6-8 |
| DP2-C-4 | "정확도는?" | 실행 위치와 KV 이동은 **모델 출력을 바꾸지 않는다**는 전제이며 Functional Correctness는 QA가 아니라 제약으로 둔다(설계 문서 선택). 프로젝트 GC-7과 같다 | 전제 | DP2-QS-9로 검증은 하되 비교 축으로 쓰지 않음 | 사용자(GC-7), DP문서 | decision-timing §7 |
| DP2-C-5 | "다른 노드에서 Prefill하려면?" | Prefill을 보낼 ExecutionGroup은 **동일 model weights를 실행할 수 있어야** 한다. candidate는 HW 능력과 함께 model replica·shard 가용성을 검사한다 | 전제 | P/D 노드 모두 모델 전체 weight 보유 → 메모리 용량 영향 | DP문서 | arch §8 |
| DP2-C-6 | "노드 간 링크는 얼마인가? 사용자 환경과 같은가?" | 평가의 노드 간 링크는 **RDMA 50 GB/s (ASSUMED)**, sweep 12.5~400 GB/s다. **사용자 환경의 서버 2대는 PCIe 64 GB/s로 연결(GC-9)** 이며 값이 다르다. 결정이 이 값에 민감(D 로컬 대 P 경로 격차)하므로 평가 profile과 환경 제약 사이의 정합이 필요하다 | 환경/증거 한계 | 재평가 시 링크 profile을 사용자 환경에 맞춰 새 profile로 추가해야 함 | DP문서, 사용자(GC-9) | rationale §4, §6-2, simulation-plan §3 |
| DP2-C-7 | "결정 비용은 실측인가?" | 결정 비용(후보당 µs~ms, **후보 수에 선형**, 1 ms @ 64 후보)과 Late Validation 비용(20 us), telemetry 주기(50 ms), 큐 한도(16K 토큰), tol(10%)은 **ASSUMED**다. 실제 Planner 프로토타입 [A] 측정이 없어 C1/C2 결론과 QA5 값은 이 가정에 조건부이며 0.1/1/10 ms 민감도 범위에서만 주장한다 | 증거 한계 | QA5 ★와 C1/C2 동점의 해석에 영향 | DP문서 | rationale §6-3, qa-criteria §3 |
| DP2-C-8 | "32~64 노드 확장성은 실측인가?" | 사용자 실험 환경은 **GPU 8장 서버 2대**(project-context)라 N=32 노드 확장성은 **실측 불가**이며 시뮬레이션 [B+C]로만 평가한다. 노드 수 4~6개 시나리오가 주 평가이고 확장성 η는 별도 sweep이다 | 환경/증거 한계 | QA5의 실제 환경 대표성 낮음 | 사용자(GC-1), DP문서 | qa-criteria §3, 결과 §0.5 |
| DP2-C-9 | "SSD에 있는 History는 불러오는 대신 재계산하면?" | **재계산 후보는 현재 ExecutionPlan 후보 집합에 없다**(열린 결정). 따라서 SSD Tier의 History는 로드 비용만으로 평가된다 | 범위 밖(미결정) | 재계산을 넣으면 DP3와의 경계(KV reuse/Drop)가 겹칠 수 있음 | DP문서 | rationale §2.2, §6-6 |
| DP2-C-10 | "prefix cache, chunked prefill, NIXL, GPU 내 P/D 간섭은 모델링했나?" | **prefix cache 공유, chunked prefill의 세부 스케줄, NIXL 프로토콜 오버헤드, GPU 내 Prefill/Decode 간섭의 정밀 모델은 미반영**이다(간섭 계수로 근사). 프로젝트의 GC-2(device runtime 오버헤드 미고려)와 같은 방향 | 증거 한계 | 이득 수치는 이 오버헤드가 없을 때의 조건부 값 | DP문서 | benchmark §10 |
| DP2-C-11 | "Baseline은 공정한가?" | Baseline-PD-fixed는 Prefill은 항상 P, Decode는 항상 D인 고정 규칙이다. **Baseline이 SLO를 거의 못 지키게 설계된 시나리오(링크 경합, 긴 History)가 배수를 키운다**(T2). 공통 시나리오(단일 턴)에서 "이득 없음(saturated)" 가설이 틀렸고 x1.3~2.1이 나왔다. 단순 휴리스틱 P-retain이 QA2에서 더 높았다 | 증거 한계 | 이득의 일반성 한정, 대조군·경계 시나리오 확대 필요 | DP문서 | 결과 §0.2, §0.4 |
| DP2-C-12 | "별점 경계는 객관적인가?" | DP2 별 경계는 **DP1이 결과를 본 뒤 정한 값을 그대로 가져왔다**(`qa-criteria-dp2.md` §6). 즉 DP2는 사전 등록했지만 값의 기원은 post-hoc이다. QA2/QA3의 iso-load 집계는 **첫 결과를 본 뒤 정의**했고 그 정의에서 QA2 ★★★이 ★★로 바뀔 수 있다. QA5 임계(0.70/0.90)는 제안값이며 소유자 확정 전이다 | 증거 한계 | 임계 통일 단계에서 이 값들을 외부 근거로 다시 정해야 함 | DP문서 | qa-criteria §6, 결과 §0.2-4 |
| DP2-C-13 | "연산 가능 메모리의 kernel, 지원 연산은?" | ScHBM, CXL-PNM의 attention 오프로드 **kernel·compiler와 지원 연산 목록은 주어진 입력**이다(GC-5). DP2는 profile 값(지원 연산, 내부 BW, TFLOPS)으로 Tier를 기술한다. 오프로드 실제 연산 결과의 수치 동일성은 시뮬레이션에서 검증하지 못한다 | 범위 밖/증거 한계 | UC-6의 Q-9 제안과 연결 | 사용자(GC-5), DP문서 | cost-model §1.2, usecases Q-9 |
| DP2-C-14 | "요청 라우팅과 llm-d 연동은?" | 요청 단위 서버 선택, 흐름 제어, llm-d 위 실행 경로(정책 P4, P5)는 **DP4(요청 조율 계층)** 소관이다. DP2는 결정 로직과 시점만 정한다 | 범위 밖/경계 | DP4와의 접점 계약 필요 | DP문서 | decision-timing §11, DP4 README |
| DP2-C-15 | "소유자 결정이 남았나?" | 평가 문서 `m0-spec.md`의 **소유자 결정 O1~O11은 확정 전**이고 별 경계·선택 규칙은 제안 상태다. **이 문서는 O1~O11의 내용을 읽지 못했다** | 미확인 | 확정 시 일부 요구사항·임계값이 바뀔 수 있음 | DP문서 | Evaluation/DP2/README |

프로젝트 공통 제약 중 DP2에 직접 걸리는 것: **GC-1**(차세대 메모리는 시뮬레이션), **GC-2**, **GC-3**(device runtime reliability·availability 보장 가정), **GC-5**, **GC-6**, **GC-7**(출력 불변), **GC-9**(서버 간 PCIe 64 GB/s, DP2-C-6과 충돌 가능).

## 6. 추적성 및 확인 사항

### 6.1 UC → DP2 FR → QS

| UC | DP2 FR | 품질 시나리오 |
|---|---|---|
| UC-1 세션 재개 | FR-01, 02, 03, 07 | QS-2 |
| UC-2 long-context | FR-03, 07 | QS-3 |
| UC-6 연산 가능 메모리 | FR-03, 07, 08 | QS-3, 5 |
| UC-7 노드 간 KV 이동 | FR-02, 05 (비용 반영) | QS-1, 2 |
| UC-8 Prefill/Decode 분리 | FR-01~05, C1-01, C2-01~04 | QS-1~4, 6~11 |
| UC-9 혼합 부하 | FR-06, 09, 11, C2-02, 03 | QS-1, 4, 6, 7, 8 |

### 6.2 DP 간 비교를 위한 관찰 (통합 단계 입력)

| ID | 관찰 | 영향 |
|---|---|---|
| X-1 | **DP2의 별 경계(QA1 1.30, QA2 1.25, QA3 1.25)는 DP1의 결과 후 정한 값을 그대로 복사**했다. 서로 다른 DP에 같은 숫자가 쓰였지만 근거는 같은 post-hoc 기원이다 | 통일 시 외부 근거로 재도출 필요 |
| X-2 | **QA3 정의가 DP마다 다르다**: DP1 = HBM 사용량(낮을수록 좋음), DP2 = useful P/D 풀 GPU 사용률(높을수록 좋음), 공통 문서 = useful resource utilization. 같은 ISO 특성(Resource utilization)이지만 방향과 단위가 다르다 | 통일 시 공유 지표 vs DP 고유 지표 분리 |
| X-3 | **Scalability(QA5)는 DP2 전용 QA**이고 공통 문서에 없다. ISO 2023에서는 Flexibility > Scalability로 정식 하위 특성이다 | 다른 DP의 Scalability 요구 확인 필요 |
| X-4 | 노드 간 링크: DP2는 RDMA 50 GB/s(ASSUMED). 사용자 환경은 PCIe 64 GB/s(GC-9). DP1은 단일 노드라 host link만(PCIe 5.0 x16 ≈ 63 GB/s) | 공통 시스템 profile 정렬 필요 |
| X-5 | DP2는 단일 턴 중심 공통 시나리오(CB-1~3)에서 Baseline이 SLO를 일부 못 맞추는 상태(Baseline TTFT P99 2,461 ms)여서 "Baseline 대비 배수"가 DP1(Baseline TTFT P99 1,084 ms)과 의미가 다르다 | 상대 배수의 DP 간 비교 불가. 절대 SLO 관문과 같이 써야 함 |
| X-6 | 집계 단위: DP1 = 64쌍 중 비교 가능 21쌍, DP2 = 38쌍 모두 비교 가능. DP2 QA2/QA3는 Baseline 최적 부하(iso-load)에서 비교(결과를 본 뒤 정의), DP1은 다른 집계 | 집계 규칙 통일 필요 |
| X-7 | QA4(Modifiability)는 DP1·DP2·DP4가 **같은 공식·상수·경계**를 쓴다(사전 등록). 이 QA가 통일에 가장 가깝다. 단 공수·가격은 ASSUMED | 통일의 모범 사례 |
| X-8 | DP2 C1/C2는 동점(13 대 13)이고 QA5는 결정 비용 가정(ASSUMED)에 의존. DP1 C1/C2 선택(10 대 9)은 경계에 민감. 어느 DP도 선택 근거가 견고하지 않음 | 재평가 필요성 확인(memo-reevaluation) |

### 6.3 사용자 확정이 필요한 점

| ID | 질문 | 현재 가정 |
|---|---|---|
| Q-2-1 | 평가의 노드 간 링크 profile을 사용자 환경(PCIe 64 GB/s)에 맞출지, 50 GB/s RDMA(ASSUMED)를 유지할지 | 재평가 시 사용자 환경으로 정렬(미확정) |
| Q-2-2 | 재계산 후보(SSD History를 불러오지 않고 재계산)를 DP2 후보 집합에 넣을지 | 현재 제외. DP3와의 경계 확인 필요 |
| Q-2-3 | 추가 후보 QA(QA6~QA10) 채택 여부 | QA6~QA10 권장, QA11 보류 |
| Q-2-4 | 아키텍처 문서(arch §15의 vLLM 변경 지점)를 DP2 요구사항으로 볼지 참고로만 볼지 | 참고(DP2-C-3) |
| Q-2-5 | 읽지 못한 `m0-spec.md`의 소유자 결정 O1~O11 | 다음에 읽어 반영 |
| Q-2-6 | QS의 `[가정]` 값(결정 지연 50 ms, step 증가율 5%, fallback 1 s, 복구 60 s, 로그 완비율 100%, TTFT 분해 오차 ±5%/95%, Oracle 0.95배) | 통합 단계에서 일괄 정함 |
