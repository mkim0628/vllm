# DP2 — Cost-based Prefill/Decode Execution Planning: Resource 결정 시점 구조

> 대상 브랜치: `claude/vllm-call-path-analysis-qxulkr`  
> 상세 공통 Architecture: `doc-mk/DP2/vllm-cost-model-prefill-execution-planning-architecture.md`
>
> **목적:** 동일한 cost-based Prefill/Decode Execution Planning 정책을 구현할 때,
> 실행 Resource 결정 기능을 runtime의 어느 시점에 배치할 것인지 비교한다.

---

# 1. Background / Problem

이기종 AI Serving Runtime에서는 Prefill 연산을 GPU/HBM, GPU/HBF, PNM/CXL 등
서로 다른 compute-memory resource에서 실행할 수 있다.

공통 정책은 다음과 같다.

> **Turn 단위로 Prefill 실행 위치(n_p)와 Decode 시작 위치(n_d)의 후보 조합에 대해
> end-to-end cost를 계산하고, 가장 낮은 cost의 조합을 선택한다.**

Prefill 위치와 Decode 시작 위치는 하나의 결정이다. Prefill을 P에서 실행하면 결과 KV를
Decode 노드로 전달해야 하고, Decode 노드에서 실행하면 전달은 없지만 Decode와 자원을 다툰다.
n_p = n_d (Prefill한 곳에서 Decode 시작)인 조합도 후보에 포함된다.

Cost는 논리적으로 다음 항목을 포함한다.

~~~text
Cost(n_p, n_d)
  = Tmove(KV → n_p)            # History KV 이동 (KV 위치: 노드·Memory Tier)
  + Tprefill(n_p)              # Compute + Memory Access
  + Tqueue/interference(n_p)
  + Tmove(KV n_p → n_d)        # 결과 KV의 Decode 노드 전달
  + ΔTPOT(n_d)                 # Decode 노드 간섭 / Memory BW 영향
  s.t. n_d의 KV 용량·SLO feasible
~~~

목적함수는 TTFT와 TPOT 두 가지이므로 "TTFT 최소화, 단 TPOT ≤ SLO"와 같은 제약형 또는
SLO 가중합으로 정의한다. ΔTPOT은 출력 길이에 비례하므로 예측 출력 길이 또는 per-step 간섭 기준으로 근사한다.

여기서 DP2은 **Cost Model 자체를 어떻게 만들 것인가**가 아니다.

**Design Question**

> 동일한 Cost Model과 Resource Selection 정책을 사용할 때,
> Prefill 실행 위치와 Decode 시작 위치를 **언제 결정할 것인가?**

**Scope Boundary (DP1과의 경계)**

> DP2는 **Turn 단위로 연산이 실행될 위치(Prefill 위치, Decode 시작 위치)**를 정한다.
> Decode 실행 중 Memory Tier 간 KV 이동은 DP1이 담당한다.

---

# 2. Terminology

기존의 `Prefill Placement`는 Data Placement와 혼동될 수 있으므로 사용하지 않는다.

- 기능 명칭: **Prefill/Decode Execution Planning**
- 핵심 component: **ExecutionPlanner**
- 결과: **ExecutionPlan = (Prefill 실행 위치 n_p, Decode 시작 위치 n_d)**
- 결정 대상: **Prefill Execution Resource, Decode Start Resource**
- 의미: "Prefill 연산을 어느 compute-memory resource에서 실행하고, 그 결과 KV로 Decode를 어디에서 시작할지 결정"

---

# 3. Common Functional Architecture

C1/C2는 아래 기능 블록을 공통으로 사용한다.

~~~mermaid
flowchart LR
    S["Scheduler<br/>request / token budget"]
    P["ExecutionPlanner<br/>candidate + cost + resource selection"]
    R["ResourceStateMonitor<br/>static + dynamic state"]
    C["CostModel<br/>compute / movement / queue / interference"]
    E["ExecutionRouter<br/>plan → worker/resource"]
    X["ExecutionResource<br/>GPU/HBM · GPU/HBF · PNM/CXL"]

    S -->|"Turn Work (Prefill 요청)"| P
    R -->|"resource state"| P
    C -->|"cost estimate"| P
    P -->|"ExecutionPlan"| E
    E -->|"dispatch"| X
~~~

공통 기능은 동일하며 **C1/C2 차이는 ExecutionPlanner가 동작하는 시점과
ExecutionPlan lifecycle**에 있다. 두 후보 모두 n_p와 n_d를 같은 시점에 하나의 plan으로 결정한다
(Layer-wise KV 전송 중첩과 Decode 노드 KV block 예약을 위해 목적지는 Prefill 시작 시점에 필요).

---

# 4. Candidate 1 — 스케줄링 시점 결정 구조

## Scheduling-time Resource Selection

> **Scheduler가 실제 Prefill request와 token budget을 확정한 시점에
> 최신 Resource State를 읽고 Cost를 계산하여 즉시 Execution Resource를 결정한다.**

~~~mermaid
flowchart TD
    W["Waiting Requests"]
    S["Scheduler<br/>request + token budget 확정"]
    P["ExecutionPlanner"]
    R["ResourceStateMonitor<br/>latest state"]
    C["CostModel"]
    E["ExecutionRouter"]
    X["ExecutionResource"]

    W --> S --> P
    R --> P
    C --> P
    P -->|"ExecutionPlan"| E --> X
~~~

### 핵심 특성

- 실제 scheduled batch / token 수를 Cost Model에 그대로 반영
- execution 직전의 queue, utilization, memory pressure를 반영
- 별도 Plan Cache / Validation / Re-plan 상태 관리 불필요
- Cost evaluation 시간이 Scheduler critical path의 Decision Latency에 포함

---

# 5. Candidate 2 — 사전 계획 결정 구조

## Pre-planned Resource Selection

> **Request가 waiting 상태일 때 Execution Plan을 미리 계산·저장하고,
> Scheduler 실행 시에는 cached plan을 조회하고 빠르게 검증한 뒤 사용한다.**

~~~mermaid
flowchart TD
    W["Request Arrival / Waiting"]
    P["ExecutionPlanner<br/>background planning"]
    R["ResourceStateMonitor<br/>planning-time state"]
    C["CostModel"]
    PC["ExecutionPlanCache<br/>ranked candidates"]
    S["Scheduler"]
    V["Plan Validation"]
    E["ExecutionRouter"]
    X["ExecutionResource"]
    RP["Re-plan / Fallback"]

    W --> P
    R --> P
    C --> P
    P --> PC
    S --> PC --> V
    V -- valid --> E --> X
    V -- stale / invalid --> RP --> E
~~~

### 핵심 특성

- Cost evaluation을 Scheduler critical path 밖으로 이동
- planning compute를 Scheduler와 독립적으로 batch/scale-out 가능
- queue에서 대기하는 동안 Resource State가 바뀌면 stale plan 가능 (Prefill 노드뿐 아니라 Decode 노드의 용량·부하 포함)
- Plan Cache / Plan Age / Validation / Invalidation / Re-plan 관리 필요

---

# 6. Stale Plan과 Late Validation

Planning 시점의 state를 `S(t_plan)`, 실제 execution 시점을 `t_exec`라 하면

~~~text
plan_age = t_exec - t_plan
~~~

queue가 길어질수록 plan age가 증가하고, 그 사이 다음 값들이 바뀔 수 있다.

- GPU/PNM queue depth
- utilization
- HBM/HBF/CXL free capacity (Decode 노드의 KV 수용 용량 포함)
- Decode 노드의 batch 크기·TPOT 여유
- bandwidth contention
- 앞선 request들의 resource 선택 결과

따라서 C2의 cached plan은 세 상태로 구분한다.

| 상태 | 의미 | 처리 |
|---|---|---|
| Valid & still good | 계획 당시 선택이 여전히 적절 | 그대로 실행 |
| Feasible but sub-optimal | 실행 가능하지만 현재 더 좋은 candidate 존재 가능 | age/state-drift 기준으로 re-plan 여부 결정 |
| Invalid | capacity 부족, resource unavailable 등 | backup candidate 또는 re-plan |

**Late Validation**은 Cost Model 전체를 다시 실행하는 것이 아니라,
dispatch 직전에 cached plan이 최소한 실행 가능한지 빠르게 확인하는 단계다.

예:

~~~text
resource healthy?
required memory available? (n_p의 작업 메모리, n_d의 KV 수용 용량)
queue below guardrail?
plan age within limit?
required data path reachable?
~~~

검증 실패 시(Decode 목적지 용량 부족 포함) ranked backup candidate((n_p, n_d) 조합)를 확인하고, 그것도 불가능하면 최신 state로 re-plan한다.

---

# 7. QA Selection

KV 이동과 실행 위치 결정은 모델 출력을 바꾸지 않는다는 전제로 Functional Correctness는 평가하지 않고 제약으로 둔다.
평가 QA는 아래 6개이며, 정의·threshold·측정 방법은 `doc-mk/Evaluation/DP2/qa-criteria-dp2.md`, 선정 근거는
`dp2-qa-evaluation-rationale.md`에 둔다.

| QA | 평가 metric | 평가 의미 |
|---|---|---|
| QA1 Throughput | Max SLO Goodput (tok/s) ↑ | planning/scheduling overhead와 resource 선택 품질이 system throughput에 미치는 영향 |
| QA2 Latency — TTFT | TTFT P99 · P50 (ms) ↓ | decision + queue + movement + prefill이 first-token latency에 미치는 영향 |
| QA2 Latency — TPOT | TPOT P99 · P50 (ms) ↓ | Decode 시작 위치(n_d)에 따른 Decode 노드 간섭·Memory BW가 token 생성 간격에 미치는 영향 |
| QA3 Resource Utilization | useful P/D 풀 GPU 사용률 (%) ↑ | resource state를 반영해 P/D 노드를 균형 있게 활용하는 정도 |
| QA4 Modifiability | 변경 module 수 · 공수 · 에이전트 비용 ↓ | Cost Model/resource 종류 변경이 Scheduler 및 다른 runtime module에 미치는 change impact |
| QA5 Scalability (DP2 전용) | scaling efficiency ↑ | request/candidate/resource 증가 시 execution planning과 시스템 처리량의 확장성 |

모든 결과는 `정량 값 (Baseline 대비 배수)` 형식으로 보고한다 (`qa-evaluation-criteria.md` §10).

## 진단 지표 (별도 QA가 아님)

| 진단 지표 | 정의 | 읽는 QA |
|---|---|---|
| Decision Latency | 결정 1건이 Scheduler step에 더하는 시간 (`T_decision`, step 시간 증가율) | TTFT(분해 항), TPOT(step 지연), Throughput |
| Decision Quality | regret = Cost(선택) − Cost(실행 시점 oracle), mis-selection 비율, plan age, re-plan 비율 | TTFT/TPOT/Throughput의 원인 분석 |
| 노드 간 부하 불균형 | 노드별 큐 깊이·사용률의 CV | QA3 |
| KV 이동량 | Turn당 노드 간 KV 전송 bytes | QA3 |

Decision Latency와 Decision Quality는 TTFT 분해식(§8)의 항이거나 그 원인이므로 독립 QA로 두지 않는다.
`ΔTTFT(C2 − C1) ≈ −ΔT_decision + stale plan으로 인한 regret`.

TTFT와 TPOT를 분리하는 이유: 결정 하나가 두 지표를 반대로 움직인다.
Prefill을 Decode 노드에서 실행하면 `T_move`가 줄어 TTFT는 좋아지지만 Decode 간섭으로 TPOT는 나빠진다.

---

# 8. TTFT Decomposition

이번 DP에서는 TTFT를 다음 관점으로 분해한다.

~~~text
TTFT
 ≈ T_schedule
 + T_decision
 + T_resource_queue
 + T_move
 + T_prefill
~~~

### C1

~~~text
T_decision       ↑  : 실행 직전 candidate/cost 평가
T_resource_queue ↓  : 최신 queue 반영 가능
T_move           ↓  : 최신 data/resource state 기반 경로 선택 가능
T_prefill        ↓  : 현재 가장 적합한 compute-memory resource 선택 가능
~~~

### C2

~~~text
T_decision       ↓  : cached plan lookup + validation 중심
T_resource_queue ↑ 가능 : stale queue 정보로 resource 선택 가능
T_move           ↑ 가능 : state/data-path 변화 시 과거 plan이 비효율적일 수 있음
T_prefill        ↑ 가능 : 현재 최적 resource와 cached resource가 달라질 수 있음
~~~

TPOT는 Decode 시작 위치에 의해 다음과 같이 영향받는다.

~~~text
TPOT(n_d) ≈ T_step(n_d) + T_interference(n_d)
~~~

- C1: Decode 노드의 최신 용량·부하를 반영해 n_d 선택 가능
- C2: 계획 시점 이후 Decode 노드 상태가 변하면 n_d가 sub-optimal일 수 있으며, Late Validation으로 용량·health만 보정

따라서 TTFT는 어느 후보가 항상 우수하다고 단정하지 않는다.

> **C1은 decision overhead를 지불하고 execution-path quality를 높이는 구조**  
> **C2는 decision overhead를 숨기지만 stale plan으로 execution cost가 증가할 수 있는 구조**

---

# 9. QA Trade-off

아래 별은 **실험 전 가정**이다. 실제 값과 별점은 `doc-mk/Evaluation/DP2/` 평가 결과로 대체한다.

| QA | C1 스케줄링 시점 결정 | C2 사전 계획 결정 | 근거 |
|---|---:|---:|---|
| QA1 Throughput | ●●○ | ●●●* | C2는 planning을 hot path 밖으로 이동. 단 stale plan에 의한 imbalance가 크면 이점 감소 |
| QA2 TTFT | ●●○ | ●●○ | C1: decision↑ / execution cost↓, C2: decision↓ / stale 시 execution cost↑ |
| QA2 TPOT | ●●● | ●●○ | C1은 최신 Decode 노드 상태로 n_d 선택, C2는 stale 시 Decode 노드 혼잡/용량 불일치 가능 |
| QA3 Resource Utilization | ●●● | ●●○ | C1은 최신 load 반영, C2는 stale plan/herding 위험 |
| QA4 Modifiability | ●●○ | ●●● | C2는 planning subsystem을 Scheduler timing과 상대적으로 독립 진화 가능 |
| QA5 Scalability | ●●○ | ●●● | C2는 planning compute를 별도 worker/task로 확장 가능 |

`* Throughput`은 **control-plane planning/scheduling throughput 관점**에서 C2가 구조적으로 유리하다.
실제 token throughput은 stale-plan 비율과 resource imbalance에 따라 실험으로 확인해야 한다.
Decision Latency는 별도 행이 아니라 진단 지표이며 C1 ●○○ / C2 ●●●로 예상한다 (§7).

---

# 10. 핵심 Trade-off

### C1 — 스케줄링 시점 결정

> **Decision Freshness / Execution Plan Quality 우선**

- 최신 runtime state
- 실제 scheduled workload 반영
- Resource Utilization에 유리
- 단, Decision Latency와 Scheduler critical-path overhead 증가

### C2 — 사전 계획 결정

> **Decision Overhead / Planning Scalability 우선**

- Cost evaluation을 미리 수행
- Scheduler hot path 단순화
- planning compute 독립 확장 가능
- 단, stale plan과 plan consistency 관리 비용 발생

한 줄로 정리하면:

> **C1 = 늦게 결정해서 최신 정보를 쓴다.**  
> **C2 = 미리 결정해서 실행 시점의 결정 비용을 줄인다.**

---

# 11. Scope Boundary

본 DP는 구현 프레임워크(vLLM 등)의 호출 경로와 독립적으로 **결정 시점 구조**만 비교한다.
vLLM Scheduler/Executor 등과의 코드 레벨 매핑은 본 DP의 범위에서 제외한다.

| 항목 | 담당 |
|---|---|
| Turn 단위 Prefill 실행 위치 / Decode 시작 위치 결정 | DP2 (본 문서) |
| Decode 실행 중 Memory Tier 간 KV 이동 (when / what / where) | DP1 |

---

# 12. PPT에서 설명할 핵심 그림

상세 Architecture 문서의 모든 view를 후보별로 복제할 필요는 없다.
PPT 또는 상세 질의 대응용으로는 아래 네 가지가 가장 차이를 잘 보여준다.

1. **Scheduler Integration View** — 결정 시점 차이
2. **Component View** — C2의 Background Planner / Plan Cache / Validator 추가
3. **Main Sequence Diagram** — C1 inline decision vs C2 pre-plan + validation
4. **Failure / Stale Plan Handling** — C2에만 필요한 invalidation/re-plan lifecycle

Layered Architecture, Cost Model Boundary, Execution Routing, Data Movement, Telemetry, Deployment는
대부분 공통이므로 공통 그림 하나를 사용하고 delta만 설명한다.
