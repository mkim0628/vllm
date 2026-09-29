# DP1 — Heterogeneous-Memory AI Data Migration Decision Architecture

> 대상 브랜치: **claude/vllm-call-path-analysis-qxulkr**  
> 배경 Architecture: **doc-mk/vllm-ai-data-migration-architecture.md**
>
> **목적:** HBM / DRAM / CXL Memory / HBF / Custom HBM / SSD 등 이기종 메모리가 혼재하는 AI Serving Runtime에서,
> 이미 존재하는 AI Data를 **언제, 무엇을, 어느 memory tier로 이동할지** 결정하는 DP1 구조를 정의한다.
>
> DP1은 **initial placement**가 아니라 **runtime data migration decision**이 대상이다.

---

# 1. Background / Problem

AI Serving Runtime의 메모리 계층은 단순한 HBM 단일 계층이 아니라 다음과 같이 확장될 수 있다.

~~~text
GPU HBM
  ↕
Host DRAM
  ↕
CXL Memory / HBF / Custom HBM
  ↕
SSD
~~~

각 memory resource는 Capacity, Bandwidth, Access latency, Current load/utilization,
Transfer path/cost, Compute capability 등의 특성이 다르다.

동시에 runtime이 관리하는 AI Data도 서로 다른 특성을 가진다.

- KV Cache
- Agent Memory
- LoRA Adapter
- MoE Expert
- Vector Index Cache
- 기타 runtime-managed AI data

AI Data마다 reuse pattern, lifetime, access frequency, bandwidth sensitivity, latency sensitivity가 다르기 때문에
단순히 "HBM이 부족하면 아무 data나 내린다"는 방식만으로는 장기적인 memory efficiency를 확보하기 어렵다.

따라서 DP1의 핵심 질문은 다음과 같다.

> **Runtime 중 memory state와 AI Data 특성이 변할 때,
> migration decision을 어떤 정보를 중심으로 내릴 것인가?**

본 설계에서는 두 후보를 비교한다.

1. **C1 — Resource State-driven Migration + Static Data-Memory Affinity**
2. **C2 — AI Data Behavior-driven Migration**

---

# 2. DP1과 공통 Migration Architecture의 관계

배경 문서 **doc-mk/vllm-ai-data-migration-architecture.md**는
migration decision 이후의 실제 data movement 구조를 정의한다.

공통 architecture의 핵심 경계는 다음과 같다.

~~~text
DP1 Decision Plane
  WHAT to move?
  WHERE to move?
        │
        │ MigrationIntent
        ▼
Migration Control Plane
  HOW to move?
  WHEN to execute?
  HOW to keep consistency?
        │
        ▼
Transfer Data Plane
  actual byte movement
~~~

즉 DP1은 **MigrationCoordinator 위에서 동작하는 decision architecture**다.

DP1이 생성하는 결과는 최종적으로 다음과 같은 MigrationIntent로 변환된다.

~~~text
MigrationIntent
 ├─ data_refs[]
 ├─ source_resource_id
 ├─ target_resource_id
 ├─ reason
 ├─ priority
 ├─ dependency_type
 └─ policy_metadata
~~~

DP1은 실제 DMA / P2P / CXL / NVMe transfer를 수행하지 않는다.
그 부분은 공통 **MigrationCoordinator → MigrationExecutor → TransferHandler** 구조가 담당한다.

---

# 3. Design Scope

## 3.1 In Scope

- memory resource state monitoring
- resource pressure / trend 분석
- migration 대상 data 후보 선택
- destination memory tier 선택
- AI Data별 static affinity 반영
- AI Data runtime behavior monitoring
- behavior trend 분석 / future behavior prediction
- migration decision 생성
- 공통 migration subsystem으로 MigrationIntent 전달

## 3.2 Out of Scope

- initial data placement
- 실제 byte transfer mechanism
- source pin / version check / atomic location commit
- migration failure rollback
- Prefill execution resource 선택 — DP2
- Agent tool-call lifecycle에 따른 KV residency 관리 — 별도 DP
- KV compression / recompute policy

특히 **Agent-aware KV 관리**는 DP1의 data movement policy와 구분한다.

~~~text
DP1
  resource/data behavior를 보고
  "어떤 KV를 어느 tier로 이동할지" 결정

Agent Tool-aware KV Residency
  tool call / tool wait lifecycle을 보고
  "언제 KV를 유지/회수/복구할지" 관리
~~~

따라서 C1에서 동적 Agent lifecycle을 직접 해석하지 않더라도,
대표적인 KV 특성은 static affinity hint로 반영하고,
tool-call 시점의 세밀한 KV lifecycle 제어는 별도 구조에서 보완한다.

---

# 4. Candidate Overview

| 구분 | C1 | C2 |
|---|---|---|
| 구조명 | Resource State-driven Migration + Static Data-Memory Affinity | AI Data Behavior-driven Migration |
| 핵심 decision signal | Memory resource state | Per-data runtime behavior |
| 동적 관찰 대상 | Capacity / BW / Load / pressure trend | Reuse / access / lifetime / tool-related behavior |
| AI Data 정보 활용 | Data class 단위 static hint | Object/class 단위 runtime behavior |
| 주요 목적 | 빠른 pressure 대응과 전체 pool utilization | Fine-grained data-tier matching |
| 대표 비용 | 낮은 decision overhead | Monitoring / characterization / prediction overhead |

가장 중요한 차이는 다음과 같다.

> **C1은 "메모리 상태가 어떻게 변하는가"를 중심으로 결정하고,  
> C2는 "데이터가 앞으로 어떻게 사용될 것인가"를 중심으로 결정한다.**

---

# 5. Common Components

C1/C2 모두 다음 공통 component를 사용한다.

## 5.1 Memory Manager

AI Data의 allocation / load / free 등 runtime lifecycle event를 발생시킨다.
Memory Manager 자체가 migration policy를 결정하지는 않는다.

## 5.2 Resource Manager

전체 memory resource에 대한 공통 정보를 관리한다.

~~~text
Resource Manager
 ├─ Telemetry Collector
 └─ Memory Registry
~~~

### Telemetry Collector

runtime dynamic state를 수집한다.

- free / used capacity
- bandwidth utilization
- queue / load
- transfer bandwidth
- contention
- memory pressure
- moving average / trend

### Memory Registry

resource의 relatively static capability를 관리한다.

- capacity
- nominal bandwidth
- nominal latency
- topology / connectivity
- memory type
- compute capability
- transfer capability

## 5.3 Destination Tier Selector

주어진 migration candidate에 대해 destination memory resource/tier를 결정한다.

## 5.4 Migration Data Selector

실제로 이동할 data object를 선택한다.

## 5.5 Migration Executor

DP1이 선택한 source / target / data object 정보를
공통 migration architecture로 전달한다.

~~~text
Destination Tier Selector
          +
Migration Data Selector
          │
          ▼
MigrationDecision
          │
          ▼
MigrationIntent
          │
          ▼
MigrationCoordinator
          │
          ▼
MigrationExecutor
~~~

PPT의 Migration Executor는 DP1 내부에서 실제 copy를 직접 수행하는 의미가 아니라,
배경 architecture의 migration execution path로 연결되는 **execution boundary**로 본다.

---

# 6. Candidate 1 — Resource State-driven Migration + Static Data-Memory Affinity

## 6.1 Design Intent

C1의 기본 원칙은 다음과 같다.

> **Data object별 runtime behavior를 지속적으로 추적하지 않고,
> memory resource의 Capacity / Bandwidth / Load 변화와 pressure를 중심으로 migration을 결정한다.**

다만 순수 resource-only 구조는
"어떤 data를 어느 memory에 두는 것이 기본적으로 적합한가"를 전혀 구분하지 못한다.

이를 보완하기 위해 **Data-Memory Affinity Mapper**를 추가한다.

~~~text
Dynamic signal
  = Resource State / Pressure / Trend

Static hint
  = Data Type / Operation ↔ Memory Affinity
~~~

중요한 점은 static affinity가 C2의 behavior prediction과 다르다는 것이다.

- C1: data class에 대한 **미리 정의된 특성**
- C2: 실제 runtime에서 관찰한 **object별 동적 behavior**

---

# 7. C1 Component Architecture

~~~mermaid
flowchart TD
    MM["Memory Manager"]
    RSM["Resource State Monitor"]
    RTA["Resource-based<br/>Trend Analyzer"]
    DEM["Data Eviction<br/>Manager"]
    DMA["Data-Memory<br/>Affinity Mapper"]
    DTS["Destination Tier<br/>Selector"]
    MDS["Migration Data<br/>Selector"]
    ME["Migration Executor<br/>(common migration subsystem)"]

    RM["Resource Manager"]
    TC["Telemetry Collector"]
    MR["Memory Registry"]
    REQ["Request Queue"]

    MM -->|"Data Load / Allocation Event"| RSM

    RM --> TC
    RM --> MR
    TC -->|"capacity / BW / load"| RSM
    MR -->|"resource capability"| RSM

    RSM --> RTA
    RSM --> DEM
    REQ --> RTA

    RTA -->|"pressure / trend"| DMA
    DEM -->|"eviction candidates"| DMA

    DMA -->|"tier affinity hint"| DTS
    DMA -->|"data affinity hint"| MDS

    MR -->|"available tier / capability"| DTS
    MR -->|"resource constraints"| MDS

    DTS --> ME
    MDS --> ME
~~~

---

# 8. C1 Component Responsibilities

## 8.1 Resource State Monitor

Telemetry Collector와 Memory Registry 정보를 사용해
현재 resource state를 normalized state로 만든다.

~~~text
ResourceState
 ├─ resource_id
 ├─ free_capacity
 ├─ capacity_pressure
 ├─ read_bw_util
 ├─ write_bw_util
 ├─ queue_depth
 ├─ load
 ├─ transfer_pressure
 └─ health
~~~

단순 순간값뿐 아니라 짧은 시간 범위의 state 변화도 볼 수 있다.

~~~text
HBM free capacity
80 GB → 55 GB → 30 GB → 12 GB

=> rapidly increasing pressure
~~~

따라서 C1은 현재 pressure뿐 아니라 near-future pressure에 선제적으로 반응할 수 있다.

## 8.2 Resource-based Trend Analyzer

Resource State와 Request Queue를 보고
resource pressure가 어느 방향으로 변할지를 분석한다.

~~~text
Current HBM free = 20 GB
Queued Prefill demand = +14 GB
Recent allocation rate = +3 GB/s

=> near-term HBM pressure expected
=> background demotion trigger
~~~

이 component의 출력은 data semantics가 아니라
**resource-side migration need**다.

~~~text
MigrationNeed
 ├─ source_tier = HBM
 ├─ required_free_bytes = 16 GB
 ├─ urgency = MEDIUM
 └─ reason = projected capacity pressure
~~~

## 8.3 Data Eviction Manager

pressure를 해소하기 위해 source tier에서
이동 가능한 data candidate set을 만든다.

~~~text
HBM pressure
   ↓
evictable objects
   ├─ KV block B1
   ├─ KV block B4
   ├─ LoRA A2
   └─ Expert E17
~~~

이 단계는 최종 선택이 아니라 **candidate generation**이다.

기본 정책은 LRU / age / size / pin state / migration eligibility 등
낮은 비용의 heuristic을 사용할 수 있다.

## 8.4 Data-Memory Affinity Mapper

C1에서 AI Data 특성을 보완하는 핵심 component다.

Data object의 runtime access history를 예측하지 않고,
대표적인 data type / operation 특성을 static metadata로 제공한다.

~~~text
DataMemoryAffinity
 ├─ data_type
 ├─ latency_sensitivity
 ├─ bandwidth_sensitivity
 ├─ capacity_preference
 ├─ mutability
 ├─ expected_access_granularity
 ├─ preferred_tiers[]
 ├─ disallowed_tiers[]
 └─ migration_cost_class
~~~

예를 들어 다음과 같은 **class-level hint**를 둘 수 있다.

| Data class | Static characteristic 예 | Affinity hint 예 |
|---|---|---|
| KV Cache | attention에서 반복 접근, latency/BW sensitive | active/hot KV는 upper tier 선호 |
| Agent Memory | 상대적으로 long-lived, large-capacity 가능 | capacity-rich tier 허용 |
| LoRA Adapter | read-mostly, adapter별 reuse 편차 | frequently selected adapter는 upper tier 선호 |
| MoE Expert | expert별 activation 편차 존재 | hot expert는 BW-rich tier 선호 |
| Vector Index Cache | large footprint, access granularity 상이 | capacity와 lookup latency trade-off 반영 |

위 표는 **runtime hotness prediction 결과가 아니라 static policy hint**다.

따라서 같은 KV Cache class 안에서 B1은 hot하고 B2는 cold하다는 차이까지는
C1이 직접 알지 못한다.

## 8.5 Destination Tier Selector

다음 정보를 결합해 target tier를 선택한다.

~~~text
resource trend
+ available capacity
+ topology/capability
+ static data-memory affinity
~~~

개념적으로:

~~~text
candidate target tier
  = feasible(resource constraints)
  ∩ preferred(data-memory affinity)
~~~

## 8.6 Migration Data Selector

Eviction candidate 중 실제 migration object를 결정한다.

고려 정보:

- migration eligibility
- object size
- pin state
- basic age/LRU
- source pressure relief 효과
- static data-memory affinity
- target feasibility

C1에서는 runtime per-object behavior prediction을 하지 않으므로
selection logic은 상대적으로 단순하게 유지한다.

---

# 9. C1 Main Sequence

~~~mermaid
sequenceDiagram
    participant MM as Memory Manager
    participant TC as Telemetry Collector
    participant RSM as Resource State Monitor
    participant RTA as Resource Trend Analyzer
    participant DEM as Data Eviction Manager
    participant AM as Data-Memory Affinity Mapper
    participant DTS as Destination Tier Selector
    participant MDS as Migration Data Selector
    participant MC as MigrationCoordinator

    TC->>RSM: capacity / BW / load telemetry
    MM->>RSM: allocation / load event
    RSM->>RTA: normalized resource state
    RSM->>DEM: pressure state

    RTA->>RTA: detect current / projected pressure
    DEM->>DEM: generate migration candidates

    RTA->>AM: resource-side migration need
    DEM->>AM: candidate data objects
    AM->>AM: apply static data-memory affinity

    AM->>DTS: target-tier hints
    AM->>MDS: candidate ranking hints

    DTS-->>MC: target resource
    MDS-->>MC: selected data objects
    MC->>MC: build MigrationIntent
~~~

---

# 10. C1 Strengths / Limitations

## 장점

- **낮은 Decision Overhead**
  - per-object behavior history와 predictor가 없어 runtime hot path가 단순함.
- **Resource State 변화에 즉시 반응**
  - capacity/BW/load pressure가 발생하면 바로 migration trigger 가능.
- **전체 Memory Pool Utilization 관리에 유리**
  - 특정 tier pressure를 빠르게 해소하고 idle capacity를 활용하기 쉬움.
- **Modifiability가 상대적으로 높음**
  - 새로운 memory resource 추가 시 registry/affinity mapping 확장으로 대응 가능.
- **AI Data 특성을 완전히 무시하지 않음**
  - 대표적인 Data/Operation 특성을 static hint로 반영.

## 한계

- **Data별 실제 접근 특성 반영 한계**
  - 같은 data class 내부 object별 hot/cold 차이를 직접 모델링하지 않음.
- **동일 Resource State에서 서로 다른 Data Access Pattern 구분 한계**
  - 동일한 HBM pressure라도 어떤 object가 곧 다시 사용될지는 알기 어려움.
- **Static hint의 granularity 한계**
  - workload phase 변화나 request-specific reuse 변화를 빠르게 반영하기 어려움.

Agent tool-call에 따른 KV lifetime/residency는
DP1 C1에 동적 behavior predictor를 추가하기보다
별도의 Agent-aware KV management 구조로 보완한다.

---

# 11. Candidate 2 — AI Data Behavior-driven Migration

## 11.1 Design Intent

C2의 기본 원칙은 다음과 같다.

> **각 AI Data의 runtime access/reuse/lifetime behavior를 관찰하고,
> 향후 사용 가능성을 예측하여 data별 migration을 결정한다.**

Resource state는 여전히 constraint로 사용하지만,
decision의 중심 signal은 **data behavior**다.

~~~text
Primary signal
  = Data Behavior / Future Behavior

Constraint
  = Resource Capacity / BW / Load
~~~

---

# 12. C2 Component Architecture

~~~mermaid
flowchart TD
    MM["Memory Manager"]
    DBM["Data Behavior<br/>Monitor"]
    DCA["Data Class<br/>Adapter"]
    BTA["Behavior-based<br/>Trend Analyzer"]
    FBP["Future Behavior<br/>Predictor"]

    DTS["Destination Tier<br/>Selector"]
    MDS["Migration Data<br/>Selector"]
    ME["Migration Executor<br/>(common migration subsystem)"]

    REQ["Request Queue"]

    RM["Resource Manager"]
    TC["Telemetry Collector"]
    MR["Memory Registry"]

    KV["KV Cache"]
    AM["Agent Memory"]
    LA["LoRA Adapter"]
    MOE["MoE Expert"]
    IDX["Vector Index Cache"]
    META["Data Class Metadata"]

    MM -->|"Data Load / Allocation Event"| DBM
    REQ --> BTA

    DBM -->|"access / reuse / lifetime"| BTA
    DBM -->|"data affinity info"| DCA

    DCA --> KV
    DCA --> AM
    DCA --> LA
    DCA --> MOE
    DCA --> IDX
    DCA --> META

    BTA --> FBP

    RM --> TC
    RM --> MR

    FBP -->|"predicted behavior"| DTS
    FBP -->|"predicted behavior"| MDS

    TC -->|"current resource state"| DTS
    TC -->|"current resource state"| MDS
    MR -->|"resource capability"| DTS
    MR -->|"resource capability"| MDS

    DTS --> ME
    MDS --> ME
~~~

---

# 13. C2 Component Responsibilities

## 13.1 Data Behavior Monitor

각 data object의 runtime behavior signal을 수집한다.

~~~text
DataBehaviorState
 ├─ object_id
 ├─ data_type
 ├─ last_access_time
 ├─ access_count
 ├─ access_interval
 ├─ reuse_distance
 ├─ residency_time
 ├─ lifetime_state
 ├─ request / session relation
 └─ data-specific signals
~~~

모든 data type에 동일한 signal이 존재하지 않으므로
data-specific 정보는 Data Class Adapter를 통해 정규화한다.

## 13.2 Data Class Adapter

KV Cache, Agent Memory, LoRA, MoE Expert, Vector Index Cache 등
서로 다른 data semantics를 generic behavior model에 연결하는 adapter다.

~~~text
KVDataBehaviorAdapter
  block access / prefix reuse / request ownership
        │
        ▼
GenericBehaviorFeatures

LoRADataBehaviorAdapter
  adapter selection frequency / active sessions
        │
        ▼
GenericBehaviorFeatures

MoEDataBehaviorAdapter
  expert activation frequency
        │
        ▼
GenericBehaviorFeatures
~~~

Migration policy와 predictor가 각 data type 내부 구현을 직접 알지 않도록 한다.

## 13.3 Behavior-based Trend Analyzer

시간에 따른 behavior 변화를 분석한다.

- access frequency increasing / decreasing
- reuse interval shortening / lengthening
- session 종료에 따른 future reuse 감소
- expert activation frequency trend
- adapter popularity trend

~~~text
BehaviorTrend
 ├─ recency_score
 ├─ frequency_score
 ├─ reuse_trend
 ├─ lifetime_stage
 ├─ hotness_trend
 └─ confidence
~~~

## 13.4 Future Behavior Predictor

현재 behavior trend로부터 near-future data value를 예측한다.

~~~text
B1 → HOT, high reuse probability
B2 → WARM
B3 → COLD, low reuse probability
~~~

또는 연속 score:

~~~text
future_reuse_probability(B1) = high
expected_next_access(B1)     = near
expected_remaining_lifetime  = long
~~~

구체적인 predictor algorithm은 DP1 architecture와 분리한다.

가능한 구현:

- rule/threshold
- exponential moving average
- reuse-distance model
- Markov/state transition
- lightweight ML predictor

## 13.5 Destination Tier Selector / Migration Data Selector

예측 결과와 resource state를 함께 사용한다.

~~~text
Predicted Data Behavior
          +
Current Resource State
          +
Memory Capability
          │
          ▼
Data Object × Memory Tier matching
~~~

C2는 같은 data class 내부 object들도 서로 다른 tier로 migration할 수 있다.

---

# 14. C2 Main Sequence

~~~mermaid
sequenceDiagram
    participant MM as Memory Manager
    participant DBM as Data Behavior Monitor
    participant DCA as Data Class Adapter
    participant BTA as Behavior Trend Analyzer
    participant FBP as Future Behavior Predictor
    participant RM as Resource Manager
    participant DTS as Destination Tier Selector
    participant MDS as Migration Data Selector
    participant MC as MigrationCoordinator

    MM->>DBM: allocation / access / lifecycle events
    DBM->>DCA: data-specific behavior
    DCA-->>DBM: normalized behavior features

    DBM->>BTA: behavior history
    BTA->>FBP: behavior trend
    FBP->>FBP: predict future reuse / lifetime / hotness

    RM-->>DTS: resource state + capability
    RM-->>MDS: resource constraints

    FBP->>DTS: predicted behavior
    FBP->>MDS: predicted behavior

    DTS-->>MC: target resource
    MDS-->>MC: selected data objects
    MC->>MC: build MigrationIntent
~~~

---

# 15. C2 Strengths / Limitations

## 장점

- **Data 종류 및 object별 Access 특성에 맞는 Fine-grained migration 가능**
- **같은 class 내부에서도 hot/warm/cold object를 구분 가능**
- **고속 tier의 불필요한 점유 감소 가능**
- **promotion과 demotion 모두 자연스럽게 지원**
  - cold prediction → demotion
  - renewed hotness / reuse prediction → promotion

## 한계

- **Data 종류별 Characterization 비용 증가**
- **Monitoring overhead 증가**
- **Prediction overhead 증가**
- **예측 오류 시 Mis-placement 가능**
- **Thrashing 위험**

따라서 C2는 cooldown, hysteresis, confidence threshold, migration budget 같은
anti-thrashing mechanism이 중요하다.

---

# 16. C1 vs C2 — Decision Flow Comparison

~~~text
C1
Resource Telemetry
      │
      ▼
Resource State / Trend
      │
      ├── pressure?
      │
      ▼
Eviction Candidate
      │
      ▼
Static Data-Memory Affinity
      │
      ▼
Data + Target Tier
      │
      ▼
MigrationIntent


C2
Per-Data Runtime Events
      │
      ▼
Behavior Monitor
      │
      ▼
Behavior Trend
      │
      ▼
Future Behavior Prediction
      │
      ├── constrained by Resource State
      │
      ▼
Data + Target Tier
      │
      ▼
MigrationIntent
~~~

> **C1 = Resource pressure가 migration을 주도하고 data 특성은 static hint로 보정**  
> **C2 = Data의 future behavior가 migration을 주도하고 resource state는 실행 가능 범위를 제약**

---

# 17. Promotion / Demotion Semantics

두 후보 모두 promotion과 demotion을 지원할 수 있지만 trigger 성격이 다르다.

## 17.1 C1 Demotion

~~~text
HBM pressure rising
  → free capacity required
  → eviction candidates
  → lower tier selection
  → demotion
~~~

## 17.2 C1 Promotion

resource state만으로는 promotion trigger가 약하다.

가능한 trigger:

- lower tier read가 반복되어 upper-tier bandwidth 여유가 있을 때
- request queue상 soon-to-be-used data가 식별될 때
- static affinity상 upper tier 선호 data가 lower tier에 있고 upper tier pressure가 낮아졌을 때

다만 object별 future reuse 판단이 필요해질수록 C2 영역에 가까워진다.

## 17.3 C2 Demotion / Promotion

~~~text
future reuse probability ↓
+ upper-tier pressure
→ demotion

reuse / access trend ↑
+ expected near-future access
+ upper-tier capacity available
→ promotion
~~~

C2는 data behavior 자체가 promotion trigger를 제공한다.

---

# 18. QA Trade-off

PPT의 정성 평가를 문서에 그대로 정리하면 다음과 같다.

| QA | C1 Resource State + Affinity | C2 Data Behavior-driven | 해석 |
|---|---:|---:|---|
| Performance Efficiency — Throughput | ●●○ | ●●○ | C1은 decision이 가볍고, C2는 fine-grained placement 이점과 monitoring/prediction overhead가 상쇄 가능 |
| Performance Efficiency — Latency (TTFT, TPOT) | ●●○ | ●●● | C2는 hot data를 적절한 tier에 둘 수 있어 steady-state latency에 유리할 가능성. 단 prediction miss 시 반대 가능 |
| Resource Utilization | ●●● | ●●○ | C1은 pool pressure를 직접 기준으로 전체 memory capacity 활용에 유리. C2는 data-optimal decision이 resource-global optimum과 항상 같지는 않음 |
| Modifiability | ●●● | ●●○ | C1은 static affinity 확장 중심. C2는 data class별 monitor/adapter/feature/predictor 변경 영향이 큼 |

> 위 점수는 **architecture-level qualitative hypothesis**이며 측정 결과가 아니다.
> PPT의 00 TPS / 00 ms / 00%는 아직 simulation/benchmark 값이 들어가지 않은 placeholder이므로
> 실제 수치 평가는 별도의 QA simulation 문서에서 정의해야 한다.

---

# 19. QA Measurement Direction

## 19.1 Throughput

관찰 대상:

~~~text
request/s
output token/s
migration decision/s
migration bytes/s
scheduler overhead
predictor overhead
~~~

C2에서는 behavior event collection overhead와 predictor CPU cost,
metadata footprint를 별도로 측정한다.

## 19.2 Latency

~~~text
TTFT
TPOT
migration-induced stall
promotion wait time
decision latency
~~~

C2에서는 prediction hit/miss를 구분해야 한다.

## 19.3 Resource Utilization

~~~text
HBM occupancy
DRAM/CXL occupancy
aggregate pool utilization
tier imbalance
unused capacity
bandwidth utilization
~~~

C1의 pressure relief 효율:

~~~text
Pressure Relief Efficiency
 = useful freed bytes / migrated bytes
~~~

C2의 hot-tier residency quality:

~~~text
Hot-tier Useful Residency
 = accesses served by correctly promoted data
   / total hot-tier data residency
~~~

## 19.4 Modifiability

변경 시 영향을 받는 module 수와 interface 변경 범위를 본다.

- 신규 memory tier 추가
- 신규 AI data class 추가
- predictor 변경
- affinity rule 변경
- telemetry metric 추가

C1은 신규 data type 추가 시 affinity metadata 추가로 대응 가능한 범위가 넓다.
C2는 신규 data type별 Data Class Adapter / behavior feature / predictor input 검토가 필요하다.

---

# 20. vLLM / Migration Architecture Mapping

DP1은 기존 vLLM **Scheduler → Executor → Worker** call path를 대체하지 않는다.

~~~text
                    DP1 Decision Plane
                           │
             ┌─────────────┴─────────────┐
             │                           │
             ▼                           ▼
    C1 Resource Policy          C2 Behavior Policy
             │                           │
             └─────────────┬─────────────┘
                           │ MigrationIntent
                           ▼
                MigrationCoordinator
                           │
                    MigrationPlanner
                           │
                  MigrationScheduler
                           │
                  MigrationExecutor
                           │
                     Worker side
                           │
                  Transfer Handlers
                           │
                  HBM/DRAM/CXL/SSD
~~~

구현 관점에서는 다음 package boundary가 적절하다.

~~~text
vllm/v1/data_migration/
├── coordinator.py
├── planner.py
├── scheduler.py
├── ...
│
├── policy/                         # DP1 decision layer
│   ├── base.py
│   │
│   ├── resource_driven/
│   │   ├── state_monitor.py
│   │   ├── trend_analyzer.py
│   │   ├── eviction_manager.py
│   │   ├── affinity_mapper.py
│   │   ├── destination_selector.py
│   │   └── data_selector.py
│   │
│   └── behavior_driven/
│       ├── behavior_monitor.py
│       ├── trend_analyzer.py
│       ├── predictor.py
│       ├── destination_selector.py
│       ├── data_selector.py
│       └── adapters/
│           ├── kv_cache.py
│           ├── agent_memory.py
│           ├── lora.py
│           ├── moe.py
│           └── vector_index.py
│
├── resource/
│   ├── registry.py
│   └── telemetry.py
│
└── worker/
    └── executor.py
~~~

Decision policy는 바뀔 수 있지만,
migration lifecycle / consistency / transfer mechanism은 공통으로 유지한다.

---

# 21. Recommended Interfaces

## 21.1 Common Policy Interface

~~~text
class MigrationDecisionPolicy:
    evaluate(
        resource_snapshot,
        request_state,
        data_state,
    ) -> list[MigrationDecision]
~~~

## 21.2 MigrationDecision

~~~text
MigrationDecision
 ├─ data_refs[]
 ├─ source_resource
 ├─ target_resource
 ├─ direction
 ├─ reason
 ├─ priority
 ├─ score
 └─ policy_metadata
~~~

## 21.3 C1 Policy Metadata

~~~text
policy_metadata
 ├─ pressure_type
 ├─ pressure_score
 ├─ predicted_pressure
 ├─ affinity_class
 └─ eviction_reason
~~~

## 21.4 C2 Policy Metadata

~~~text
policy_metadata
 ├─ behavior_class
 ├─ reuse_score
 ├─ predicted_hotness
 ├─ prediction_confidence
 └─ lifetime_state
~~~

---

# 22. Important Boundary: Static Affinity vs Dynamic Behavior

C1과 C2가 비슷해 보이지 않도록 이 경계를 명확히 유지해야 한다.

## C1 static affinity

~~~text
"KV Cache는 generally latency/BW sensitive"
"Agent Memory는 capacity-rich tier도 허용 가능"
"MoE Expert는 hot일 경우 BW-rich tier가 좋음"
~~~

- design-time / configuration-time 지식
- data class 수준
- request마다 다시 학습하지 않음
- runtime access history가 없어도 동작

## C2 dynamic behavior

~~~text
"KV block B17이 최근 500 ms 동안 여러 번 재사용됨"
"Expert E5의 activation frequency가 증가 중"
"LoRA A3의 active session이 종료되어 reuse 가능성이 낮아짐"
~~~

- runtime observation
- object/session 수준
- 시간에 따라 계속 바뀜
- history와 prediction이 필요

따라서 **C1에 Affinity Mapper를 추가해도 C2와 동일해지는 것은 아니다.**

---

# 23. Design Decision Summary

## C1 — Resource State-driven + Data-Memory Affinity

~~~text
Resource pressure is the primary trigger.
Static AI Data characteristics refine the decision.
~~~

주요 특성:

- low decision overhead
- fast pressure response
- strong global pool utilization orientation
- static AI data hints
- Agent-aware KV lifecycle은 별도 구조에서 보완

## C2 — AI Data Behavior-driven

~~~text
Future data usage is the primary trigger.
Resource state constrains the decision.
~~~

주요 특성:

- data/object-specific migration
- dynamic behavior monitoring
- future behavior prediction
- fine-grained hot-tier usage
- higher overhead / mis-placement risk

공통 migration execution은
**doc-mk/vllm-ai-data-migration-architecture.md**의
MigrationCoordinator / MigrationPlanner / MigrationExecutor 구조를 재사용한다.

---

# 24. Follow-up Items

DP1 상세 설계에서 다음 항목은 별도 페이지/문서로 구체화한다.

1. **C1 Data-Memory Affinity Table**
   - KV / Agent Memory / LoRA / MoE / Vector Index별 static hint 정의
2. **C1 Resource Trend Function**
   - pressure score / threshold / look-ahead window
3. **C1 Eviction Candidate Policy**
   - LRU / size-aware / pressure-relief-aware
4. **C2 Behavior Feature Schema**
   - data class별 observable 정의
5. **C2 Future Behavior Predictor**
   - rule-based vs history-based predictor
6. **C2 Anti-thrashing**
   - confidence / hysteresis / cooldown / migration budget
7. **QA별 quantitative evaluation criteria**
   - TPS, TTFT/TPOT, utilization, decision overhead 기준
8. **Simulation workload**
   - KV reuse skew / LoRA popularity / MoE expert skew / memory pressure 변화 시나리오

---

# 25. References

- **doc-mk/vllm-ai-data-migration-architecture.md**
- **doc-mk/vllm-call-path-analysis.md**
- **doc-mk/vllm-kv-cache-memory-abstraction-layer.md**
- **doc-mk/vllm-kv-cache-memory-tiering.md**
