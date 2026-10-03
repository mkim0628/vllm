# DP2 — Cost-based Prefill Execution Planning: Resource 결정 시점 구조

> 대상 브랜치: `claude/vllm-call-path-analysis-qxulkr`  
> 상세 공통 Architecture: `doc-mk/DP2/vllm-cost-model-prefill-execution-planning-architecture.md`
>
> **목적:** 동일한 cost-based Prefill Execution Planning 정책을 구현할 때,
> 실행 Resource 결정 기능을 runtime의 어느 시점에 배치할 것인지 비교한다.

---

# 1. Background / Problem

이기종 AI Serving Runtime에서는 Prefill 연산을 GPU/HBM, GPU/HBF, PNM/CXL 등
서로 다른 compute-memory resource에서 실행할 수 있다.

공통 정책은 다음과 같다.

> **Prefill을 실행 가능한 compute-memory candidate들의 end-to-end cost를 계산하고,
> 가장 낮은 cost의 execution resource를 선택한다.**

Cost는 논리적으로 다음 항목을 포함한다.

~~~text
Total Cost
  = Compute Cost
  + Memory Access Cost
  + Data Movement Cost
  + Queueing Cost
  + Interference Cost
~~~

여기서 DP2은 **Cost Model 자체를 어떻게 만들 것인가**가 아니다.

**Design Question**

> 동일한 Cost Model과 Resource Selection 정책을 사용할 때,
> Prefill Execution Resource를 **언제 결정할 것인가?**

---

# 2. Terminology

기존의 `Prefill Placement`는 Data Placement와 혼동될 수 있으므로 사용하지 않는다.

- 기능 명칭: **Prefill Execution Planning**
- 핵심 component: **PrefillExecutionPlanner**
- 결과: **ExecutionPlan**
- 결정 대상: **Prefill Execution Resource**
- 의미: "Prefill 연산을 어느 compute-memory resource에서 실행할지 결정"

---

# 3. Common Functional Architecture

C1/C2는 아래 기능 블록을 공통으로 사용한다.

~~~mermaid
flowchart LR
    S["Scheduler<br/>request / token budget"]
    P["PrefillExecutionPlanner<br/>candidate + cost + resource selection"]
    R["ResourceStateMonitor<br/>static + dynamic state"]
    C["CostModel<br/>compute / movement / queue / interference"]
    E["ExecutionRouter<br/>plan → worker/resource"]
    X["ExecutionResource<br/>GPU/HBM · GPU/HBF · PNM/CXL"]

    S -->|"Prefill Work"| P
    R -->|"resource state"| P
    C -->|"cost estimate"| P
    P -->|"ExecutionPlan"| E
    E -->|"dispatch"| X
~~~

공통 기능은 동일하며 **C1/C2 차이는 PrefillExecutionPlanner가 동작하는 시점과
ExecutionPlan lifecycle**에 있다.

---

# 4. Candidate 1 — 스케줄링 시점 결정 구조

## Scheduling-time Resource Selection

> **Scheduler가 실제 Prefill request와 token budget을 확정한 시점에
> 최신 Resource State를 읽고 Cost를 계산하여 즉시 Execution Resource를 결정한다.**

~~~mermaid
flowchart TD
    W["Waiting Requests"]
    S["Scheduler<br/>request + token budget 확정"]
    P["PrefillExecutionPlanner"]
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
    P["PrefillExecutionPlanner<br/>background planning"]
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
- queue에서 대기하는 동안 Resource State가 바뀌면 stale plan 가능
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
- HBM/HBF/CXL free capacity
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
required memory available?
queue below guardrail?
plan age within limit?
required data path reachable?
~~~

검증 실패 시 ranked backup candidate를 확인하고, 그것도 불가능하면 최신 state로 re-plan한다.

---

# 7. QA Selection

이번 DP는 LLM 모델의 Functional Correctness/Accuracy와 직접 관계가 없다.
따라서 다음 QA를 사용한다.

| QA | 평가 의미 |
|---|---|
| Performance Efficiency — Throughput | planning/scheduling overhead와 resource 선택 품질이 system throughput에 미치는 영향 |
| Performance Efficiency — Latency (TTFT) | decision + queue + movement + prefill이 first-token latency에 미치는 영향 |
| Resource Utilization | resource state를 반영해 GPU/HBF/PNM 등을 균형 있게 활용하는 정도 |
| Modifiability | Cost Model/resource 종류 변경이 Scheduler 및 다른 runtime module에 미치는 change impact |
| Scalability | request/candidate/resource 증가 시 execution planning 처리량 확장성 |
| **Decision Latency** | Scheduler critical path에서 Execution Resource 결정을 위해 추가되는 시간 |

TPOT는 Prefill Execution Resource 결정의 직접 대상이 아니므로 본 DP의 주 평가 항목에서는 제외한다.

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

따라서 TTFT는 어느 후보가 항상 우수하다고 단정하지 않는다.

> **C1은 decision overhead를 지불하고 execution-path quality를 높이는 구조**  
> **C2는 decision overhead를 숨기지만 stale plan으로 execution cost가 증가할 수 있는 구조**

---

# 9. QA Trade-off

| QA | C1 스케줄링 시점 결정 | C2 사전 계획 결정 | 근거 |
|---|---:|---:|---|
| Throughput | ●●○ | ●●●* | C2는 planning을 hot path 밖으로 이동. 단 stale plan에 의한 imbalance가 크면 이점 감소 |
| TTFT | ●●○ | ●●○ | C1: decision↑ / execution cost↓, C2: decision↓ / stale 시 execution cost↑ |
| Resource Utilization | ●●● | ●●○ | C1은 최신 load 반영, C2는 stale plan/herding 위험 |
| Modifiability | ●●○ | ●●● | C2는 planning subsystem을 Scheduler timing과 상대적으로 독립 진화 가능 |
| Scalability | ●●○ | ●●● | C2는 planning compute를 별도 worker/task로 확장 가능 |
| Decision Latency | ●○○ | ●●● | C1은 cost evaluation이 critical path, C2는 lookup/validation 위주 |

`* Throughput`은 **control-plane planning/scheduling throughput 관점**에서 C2가 구조적으로 유리하다.
실제 token throughput은 stale-plan 비율과 resource imbalance에 따라 실험으로 확인해야 한다.

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

# 11. vLLM Mapping

## C1

~~~text
EngineCore.step()
  → Scheduler.schedule()
      → request/token budget 확정
      → PrefillExecutionPlanner.plan_batch()
      → ExecutionPlan 생성
  → Executor / ExecutionRouter
  → Worker / ModelRunner
~~~

## C2

~~~text
request waiting
  → PrefillExecutionPlanner.plan()
  → ExecutionPlanCache

EngineCore.step()
  → Scheduler.schedule()
      → ExecutionPlanCache.lookup()
      → PlanValidator
      → [valid] use plan
      → [stale] re-plan / fallback
  → Executor / ExecutionRouter
  → Worker / ModelRunner
~~~

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
