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

그리고 두 후보 모두 공통적으로 **Event-driven Migration Scheduler**를 entry point로 사용한다.

---

# 2. DP1과 공통 Migration Architecture의 관계

배경 문서 **doc-mk/vllm-ai-data-migration-architecture.md**는
migration decision 이후의 실제 data movement 구조를 정의한다.

현재 DP1의 상위 흐름은 다음처럼 본다.

~~~text
Runtime Event
    │
    ▼
DP1 Migration Scheduler
    │  asynchronous event dispatch
    ▼
C1 or C2 Decision Pipeline
    │
    │ MigrationDecision / MigrationIntent
    ▼
Migration Control Plane
    │
    ▼
Transfer Data Plane
~~~

DP1의 책임은 다음과 같다.

~~~text
WHEN to evaluate migration?
  → Event + Migration Scheduler

WHAT to move?
WHERE to move?
  → C1 / C2 decision pipeline
~~~

반면 공통 migration subsystem의 책임은 다음과 같다.

~~~text
HOW to move?
HOW to order / execute transfer?
HOW to keep consistency?
HOW to commit / rollback?
~~~

따라서 DP1이 생성한 decision은 최종적으로 다음과 같은 MigrationIntent로 변환된다.

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
그 부분은 공통 **MigrationCoordinator → MigrationPlanner → execution-side scheduler/queue → MigrationExecutor → TransferHandler** 구조가 담당한다.

> **주의:** 본 문서의 **DP1 Migration Scheduler**는 Event를 받아 migration decision cycle을 시작하는 orchestration component다.  
> 배경 architecture의 execution-side scheduler/queue와 역할이 다르다.

---

# 3. Design Scope

## 3.1 In Scope

- runtime event 기반 migration decision trigger
- Migration Scheduler를 통한 비동기 decision pipeline 호출
- memory resource state monitoring
- resource pressure / trend 분석
- Data Object Registry 기반 object 위치/크기/tier 조회
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
| 구조명 | Resource State-driven Migration + Data-Memory Affinity | AI Data Behavior-driven Migration |
| 공통 trigger | Event → Migration Scheduler | Event → Migration Scheduler |
| 핵심 decision signal | Memory resource state | Per-data runtime behavior |
| 동적 관찰 대상 | Capacity / BW / Load / pressure trend | Reuse / access / lifetime / tool-related behavior |
| Data Object Registry 사용 | 위치·크기·현재 tier 등 object state 조회 | object identity/class/metadata와 behavior 연결 |
| AI Data 정보 활용 | Data class / operation 단위 static hint | Object/class 단위 runtime behavior |
| 주요 목적 | 빠른 pressure 대응과 전체 pool utilization | Fine-grained data-tier matching |
| 대표 비용 | 낮은 decision overhead | Monitoring / characterization / prediction overhead |

가장 중요한 차이는 다음과 같다.

> **C1은 "메모리 상태가 어떻게 변하는가"를 중심으로 결정하고,  
> C2는 "데이터가 앞으로 어떻게 사용될 것인가"를 중심으로 결정한다.**

Data Object Registry는 두 후보에 모두 존재한다.
차이는 Registry의 존재 여부가 아니라 **Registry의 정보를 어떻게 decision에 사용하는가**다.

---

# 5. Common Components

C1/C2 모두 다음 공통 component를 사용한다.

## 5.1 Event Source

migration 판단이 필요한 runtime state change를 Event로 전달한다.

구체적인 Event type은 구현에 따라 달라질 수 있지만,
DP1 관점에서는 다음처럼 추상화한다.

~~~text
MigrationEvent
 ├─ event_type
 ├─ timestamp
 ├─ related_resource
 ├─ related_data_ref
 └─ optional_metadata
~~~

Event는 policy logic을 직접 수행하지 않는다.

## 5.2 Migration Scheduler

Migration Scheduler는 DP1 decision plane의 **entry / orchestration component**다.

역할:

- Event 수신
- Event를 비동기로 처리
- C1 또는 C2의 monitoring / analysis pipeline을 실행하도록 trigger
- 중복/과도한 decision invocation을 조정할 수 있는 entry point 제공
- 최종 migration decision이 생성되면 공통 migration subsystem으로 넘김

핵심 흐름:

~~~text
Event
  ↓
Migration Scheduler
  ↓ async event push
C1 Resource State Monitor
or
C2 Data Behavior Monitor
~~~

Migration Scheduler가 resource/data 특성을 직접 분석하지는 않는다.

## 5.3 Data Object Registry

C1/C2가 공통으로 참조하는 AI Data object metadata 저장소다.

~~~text
DataObjectRecord
 ├─ object_id
 ├─ data_type
 ├─ size_bytes
 ├─ current_tier
 ├─ current_resource
 ├─ logical_owner / scope
 ├─ lifecycle state
 └─ data-class metadata reference
~~~

최소한 다음 정보를 제공한다.

- object identity
- data type / class
- 현재 위치
- 현재 memory tier
- object size
- migration 가능한 object인지 판단하기 위한 기본 metadata

### C1에서의 사용

~~~text
Data Eviction Manager
  → Data Object Registry 조회
  → 현재 위치 / 크기 / tier / class 확인
  → eviction candidate 생성
~~~

C1에서 Registry는 **dynamic behavior predictor가 아니다.**
최근 access count, reuse probability 등을 이용해 object를 예측 분류하지 않는다.

### C2에서의 사용

~~~text
Data Behavior Monitor
  ↔ Data Object Registry
  → behavior event를 stable object identity / data class와 연결
~~~

C2에서는 Registry가 KV Cache / Agent Memory / LoRA / MoE / Vector Index 등의
data-class metadata와 runtime behavior를 연결하는 기준점이 된다.

## 5.4 Resource Manager

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

## 5.5 Destination Tier Selector

주어진 migration candidate에 대해 destination memory resource/tier를 결정한다.

## 5.6 Migration Data Selector

실제로 이동할 data object를 선택한다.

## 5.7 Migration Executor Boundary

PPT의 Migration Executor는 DP1에서 결정된 source / target / data object를
공통 migration architecture로 넘기는 execution boundary로 본다.

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

즉 PPT의 단순 구조에서는 Selector 다음에 Migration Executor를 직접 그리지만,
상세 구현에서는 공통 Migration Control Plane을 거쳐 실제 transfer가 수행된다.

---

# 6. Candidate 1 — Resource State-driven Migration + Data-Memory Affinity

## 6.1 Design Intent

C1의 기본 원칙은 다음과 같다.

> **Data object별 runtime behavior를 지속적으로 추적하지 않고,
> memory resource의 Capacity / Bandwidth / Load 변화와 pressure를 중심으로 migration을 결정한다.**

다만 순수 resource-only 구조는
"어떤 data를 어느 memory에 두는 것이 기본적으로 적합한가"를 전혀 구분하지 못한다.

이를 보완하기 위해 **Data-Memory Affinity Mapper**를 둔다.

~~~text
Dynamic signal
  = Resource State / Pressure / Trend

Static hint
  = Data Type / Operation ↔ Memory Affinity

Object metadata
  = Data Object Registry
~~~

중요한 점은 static affinity가 C2의 behavior prediction과 다르다는 것이다.

- C1: data class / operation에 대한 **미리 정의된 특성**
- C2: 실제 runtime에서 관찰한 **object별 동적 behavior**

---

# 7. C1 Component Architecture

~~~mermaid
flowchart TD
    EV["Event"]
    MS["Migration Scheduler"]

    RSM["Resource State Monitor"]
    RTA["Resource-based<br/>Trend Analyzer"]
    DEM["Data Eviction<br/>Manager"]
    DMA["Data-Memory<br/>Affinity Mapper"]
    DTS["Destination Tier<br/>Selector"]
    MDS["Migration Data<br/>Selector"]
    ME["Migration Executor<br/>(common migration boundary)"]

    DOR["Data Object Registry<br/>location / size / tier / type"]

    RM["Resource Manager"]
    TC["Telemetry Collector"]
    MR["Memory Registry"]

    EV --> MS
    MS -. "Event push (async)" .-> RSM

    RM --> TC
    RM --> MR
    TC -->|"capacity / BW / load"| RSM

    RSM --> RTA
    RSM --> DEM

    DEM -->|"object metadata query"| DOR
    DOR -->|"location / size / tier / type"| DEM

    RTA -->|"resource trend"| DMA
    DEM -->|"eviction candidates"| DMA

    DMA -->|"tier affinity hint"| DTS
    DMA -->|"data affinity hint"| MDS

    MR -->|"memory capability"| DTS
    MR -->|"resource constraints"| MDS

    DTS --> ME
    MDS --> ME
~~~

구조의 핵심 path는 다음과 같다.

~~~text
Event
  → Migration Scheduler
  → Resource State Monitor
  → Resource-based Trend Analyzer / Data Eviction Manager
  → Data-Memory Affinity Mapper
  → Destination Tier Selector / Migration Data Selector
  → Migration Executor boundary
~~~

Data Eviction Manager는 별도로 Data Object Registry를 조회하여
실제 object의 위치·크기·현재 tier 정보를 얻는다.

---

# 8. C1 Component Responsibilities

## 8.1 Migration Scheduler

C1에서 Event를 받으면 Resource State Monitor의 evaluation cycle을 비동기로 시작한다.

~~~text
Event arrives
  ↓
Migration Scheduler
  ↓ async
Resource State Monitor refresh/evaluate
~~~

이렇게 하면 resource monitoring/decision logic이
request execution path에서 직접 동기 호출되는 구조를 피할 수 있다.

## 8.2 Resource State Monitor

Telemetry Collector 정보를 사용해 현재 resource state를 normalized state로 만든다.

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

## 8.3 Resource-based Trend Analyzer

Resource State의 시간 변화와 pending demand를 보고
resource pressure가 어느 방향으로 변할지를 분석한다.

~~~text
Current HBM free = 20 GB
Expected near-term demand = +14 GB
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

## 8.4 Data Eviction Manager

pressure를 해소하기 위해 source tier에서
이동 가능한 data candidate set을 만든다.

이때 Data Object Registry를 조회한다.

~~~text
HBM pressure
   ↓
Data Object Registry
  location / size / tier / type
   ↓
evictable objects
   ├─ KV block B1
   ├─ KV block B4
   ├─ LoRA A2
   └─ Expert E17
~~~

Data Eviction Manager는 최종 target tier를 정하지 않는다.
역할은 **source-side candidate generation**이다.

기본 정책은 LRU / age / size / pin state / migration eligibility 등
낮은 비용의 heuristic을 사용할 수 있다.

## 8.5 Data Object Registry

C1에서도 Data Object Registry는 필수다.

C1이 per-object future behavior를 예측하지 않을 뿐,
어떤 object를 이동할지 결정하려면 최소한 다음 정보가 필요하다.

~~~text
object_id
data_type
size
current location
current tier
migration eligibility
static metadata reference
~~~

따라서 C1의 의미는 "Data 정보를 사용하지 않는다"가 아니라

> **dynamic per-object behavior를 주요 decision signal로 사용하지 않는다**

로 정의해야 한다.

## 8.6 Data-Memory Affinity Mapper

C1에서 AI Data 특성을 보완하는 핵심 component다.

Data object의 runtime access history를 예측하지 않고,
대표적인 data type / operation 특성을 static metadata로 제공한다.

~~~text
DataMemoryAffinity
 ├─ data_type
 ├─ operation_class
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
| KV Cache | attention에서 반복 접근, latency/BW sensitive | active KV는 upper tier 선호 |
| Agent Memory | 상대적으로 long-lived, large-capacity 가능 | capacity-rich tier 허용 |
| LoRA Adapter | read-mostly | 자주 쓰이는 deployment profile은 upper tier 선호 가능 |
| MoE Expert | weight footprint가 크고 access가 selective | bandwidth-rich tier 우선순위 부여 가능 |
| Vector Index Cache | large footprint, lookup-oriented | capacity와 lookup latency trade-off 반영 |

위 표는 **runtime hotness prediction 결과가 아니라 static policy hint**다.

따라서 같은 KV Cache class 안에서
B1과 B2의 실제 future reuse 차이까지 C1이 직접 예측하지 않는다.

## 8.7 Destination Tier Selector

다음 정보를 결합해 target tier를 선택한다.

~~~text
resource trend
+ available capacity
+ memory capability
+ static data-memory affinity
~~~

개념적으로:

~~~text
candidate target tier
  = feasible(resource constraints)
  ∩ preferred(data-memory affinity)
~~~

## 8.8 Migration Data Selector

Eviction candidate 중 실제 migration object를 결정한다.

고려 정보:

- migration eligibility
- object size
- current tier/location
- pin state
- basic age/LRU
- source pressure relief 효과
- static data-memory affinity
- target feasibility

C1에서는 runtime per-object future behavior prediction을 하지 않으므로
selection logic은 상대적으로 단순하게 유지한다.

---

# 9. C1 Main Sequence

~~~mermaid
sequenceDiagram
    participant E as Event Source
    participant MS as Migration Scheduler
    participant TC as Telemetry Collector
    participant RSM as Resource State Monitor
    participant RTA as Resource Trend Analyzer
    participant DEM as Data Eviction Manager
    participant DOR as Data Object Registry
    participant AM as Data-Memory Affinity Mapper
    participant DTS as Destination Tier Selector
    participant MDS as Migration Data Selector
    participant MC as MigrationCoordinator

    E->>MS: Migration Event
    MS-->>RSM: async event push / evaluate

    TC->>RSM: capacity / BW / load telemetry
    RSM->>RTA: normalized resource state
    RSM->>DEM: pressure state

    RTA->>RTA: detect current / projected pressure

    DEM->>DOR: query candidate object metadata
    DOR-->>DEM: location / size / tier / type
    DEM->>DEM: generate eviction candidates

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
  - per-object behavior history와 predictor가 없어 decision pipeline이 단순함.
- **Event 기반 비동기 처리**
  - runtime event 발생 시 Migration Scheduler가 decision cycle을 시작하고 request path와 결합도를 낮출 수 있음.
- **Resource State 변화에 즉시 반응**
  - capacity/BW/load pressure가 발생하면 migration evaluation trigger 가능.
- **전체 Memory Pool Utilization 관리에 유리**
  - 특정 tier pressure를 빠르게 해소하고 idle capacity를 활용하기 쉬움.
- **Modifiability가 상대적으로 높음**
  - 새로운 memory resource 추가 시 Registry / affinity mapping 확장으로 대응 가능.
- **AI Data 특성을 완전히 무시하지 않음**
  - Data Object Registry + 대표적인 Data/Operation 특성을 static hint로 반영.

## 한계

- **Data별 실제 접근 특성 반영 한계**
  - 같은 data class 내부 object별 hot/cold 차이를 직접 예측하지 않음.
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

> **각 AI Data의 runtime reuse/access/lifetime behavior를 관찰하고,
> 향후 사용 가능성을 예측하여 data별 migration을 결정한다.**

Resource state는 여전히 constraint로 사용하지만,
decision의 중심 signal은 **data behavior**다.

~~~text
Primary signal
  = Data Behavior / Future Behavior

Constraint
  = Resource Capacity / BW / Load

Object identity / class
  = Data Object Registry
~~~

---

# 12. C2 Component Architecture

~~~mermaid
flowchart TD
    EV["Event"]
    MS["Migration Scheduler"]

    DBM["Data Behavior<br/>Monitor"]
    BTA["Behavior-based<br/>Trend Analyzer"]
    FBP["Future Behavior<br/>Predictor"]

    DOR["Data Object Registry"]
    KV["KV Cache"]
    AM["Agent Memory"]
    LA["LoRA Adapter"]
    MOE["MoE Expert"]
    IDX["Vector Index Cache"]
    META["Data Class Metadata"]

    DTS["Destination Tier<br/>Selector"]
    MDS["Migration Data<br/>Selector"]
    ME["Migration Executor<br/>(common migration boundary)"]

    RM["Resource Manager"]
    TC["Telemetry Collector"]
    MR["Memory Registry"]

    EV --> MS
    MS -. "Event push (async)" .-> DBM

    DBM -->|"object / behavior association"| DOR
    DBM -->|"data affinity / behavior info"| BTA
    BTA --> FBP

    DOR --> KV
    DOR --> AM
    DOR --> LA
    DOR --> MOE
    DOR --> IDX
    DOR --> META

    RM --> TC
    RM --> MR

    FBP -->|"predicted behavior"| DTS
    FBP -->|"predicted behavior"| MDS

    TC -->|"current resource state"| DTS
    TC -->|"current resource state"| MDS
    MR -->|"memory capability"| DTS
    MR -->|"resource constraints"| MDS

    DTS --> ME
    MDS --> ME
~~~

구조의 핵심 path는 다음과 같다.

~~~text
Event
  → Migration Scheduler
  → Data Behavior Monitor
  → Behavior-based Trend Analyzer
  → Future Behavior Predictor
  → Destination Tier Selector / Migration Data Selector
  → Migration Executor boundary
~~~

Data Object Registry는 Data Behavior Monitor가 관찰한 behavior를
stable data object / data class와 연결하는 공통 metadata anchor다.

---

# 13. C2 Component Responsibilities

## 13.1 Migration Scheduler

C2에서 Event를 받으면 Data Behavior Monitor의 evaluation cycle을 비동기로 시작한다.

~~~text
Event
  ↓
Migration Scheduler
  ↓ async
Data Behavior Monitor
~~~

C1과 entry pattern은 동일하다.
후속 pipeline만 resource-driven과 behavior-driven으로 달라진다.

## 13.2 Data Behavior Monitor

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

Behavior Monitor는 Data Object Registry를 이용해
event를 logical object identity와 data class에 연결한다.

## 13.3 Data Object Registry

C2의 Registry는 다음 역할을 한다.

- data object identity 관리
- object의 type/class 관리
- 현재 location / tier / size metadata 관리
- KV Cache / Agent Memory / LoRA / MoE / Vector Index 등의 data-class metadata 연결
- Data Behavior Monitor가 수집한 event를 올바른 object에 귀속시키는 lookup 기준 제공

~~~text
Data Object Registry
 ├─ KV Cache objects
 ├─ Agent Memory objects
 ├─ LoRA Adapter objects
 ├─ MoE Expert objects
 ├─ Vector Index Cache objects
 └─ Data Class Metadata
~~~

기존 문서의 별도 **Data Class Adapter**는 현재 PPT 구조에서는
독립 top-level component로 두지 않는다.

필요한 data-class별 normalization/interpretation은
Data Object Registry의 data-class metadata 또는
Data Behavior Monitor 내부 adapter/plugin으로 구현할 수 있다.

즉 architecture view에서는 다음처럼 단순화한다.

~~~text
Data-specific runtime event
        │
        ▼
Data Behavior Monitor
        │
        ├─ Data Object Registry lookup
        └─ data-class metadata reference
        │
        ▼
normalized behavior information
~~~

## 13.4 Behavior-based Trend Analyzer

시간에 따른 behavior 변화를 분석한다.

- access frequency increasing / decreasing
- reuse interval shortening / lengthening
- session/lifetime 변화
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

## 13.5 Future Behavior Predictor

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
- state transition model
- lightweight ML predictor

## 13.6 Destination Tier Selector / Migration Data Selector

예측 결과와 resource state를 함께 사용한다.

~~~text
Predicted Data Behavior
          +
Current Resource State
          +
Memory Capability
          +
Current Object Location
          │
          ▼
Data Object × Memory Tier matching
~~~

C2는 같은 data class 내부 object들도 서로 다른 tier로 migration할 수 있다.

---

# 14. C2 Main Sequence

~~~mermaid
sequenceDiagram
    participant E as Event Source
    participant MS as Migration Scheduler
    participant DBM as Data Behavior Monitor
    participant DOR as Data Object Registry
    participant BTA as Behavior Trend Analyzer
    participant FBP as Future Behavior Predictor
    participant RM as Resource Manager
    participant DTS as Destination Tier Selector
    participant MDS as Migration Data Selector
    participant MC as MigrationCoordinator

    E->>MS: Migration / data behavior event
    MS-->>DBM: async event push

    DBM->>DOR: lookup object identity / class / current location
    DOR-->>DBM: object metadata + data-class metadata

    DBM->>BTA: normalized behavior / affinity information
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
- **공통 Data Object Registry 사용**
  - data type별 object identity/location 관리를 C1과 공유하면서 behavior logic만 별도로 확장 가능

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
Common Entry
Event
  │
  ▼
Migration Scheduler
  │
  ├───────────────────────────────┐
  │                               │
  ▼                               ▼
C1                              C2
Resource State Monitor          Data Behavior Monitor
  │                               │
  ▼                               ├── Data Object Registry
Resource Trend                    │
+ Eviction Manager                ▼
  │                            Behavior Trend
  ├── Data Object Registry        │
  │                               ▼
  ▼                            Future Behavior
Static Data-Memory                Prediction
Affinity                          │
  │                               │
  ▼                               ▼
Data + Target Tier              Data + Target Tier
  │                               │
  └───────────────┬───────────────┘
                  ▼
            MigrationIntent
~~~

정리하면:

> **공통 = Event → Migration Scheduler → candidate-specific decision pipeline**  
> **C1 = Resource pressure가 migration을 주도하고 Data Object Registry + static affinity가 object 선택을 보정**  
> **C2 = Data의 future behavior가 migration을 주도하고 Data Object Registry가 behavior를 object/class와 연결**

---

# 17. Promotion / Demotion Semantics

두 후보 모두 promotion과 demotion을 지원할 수 있지만 trigger 성격이 다르다.

## 17.1 C1 Demotion

~~~text
Event
  → Migration Scheduler
  → HBM pressure rising
  → free capacity required
  → Data Object Registry에서 candidate 조회
  → lower tier selection
  → demotion
~~~

## 17.2 C1 Promotion

resource state만으로는 promotion trigger가 상대적으로 약하다.

가능한 trigger:

- upper-tier capacity/pressure가 충분히 회복된 event
- static affinity상 upper tier 선호 object가 lower tier에 존재
- explicit demand/event로 해당 object가 다시 필요해짐

다만 object별 future reuse를 지속 예측하기 시작하면 C2 영역에 가까워진다.

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

C2는 data behavior 자체가 promotion/demotion의 강한 signal을 제공한다.

---

# 18. QA Trade-off

현재 PPT의 정성 평가를 문서에 정리하면 다음과 같다.

| QA | C1 Resource State + Affinity | C2 Data Behavior-driven | 해석 |
|---|---:|---:|---|
| Performance Efficiency — Throughput | ●●○ | ●●○ | C1은 decision이 가볍고, C2는 fine-grained migration 이점과 monitoring/prediction overhead가 상쇄 가능 |
| Performance Efficiency — Latency (TTFT, TPOT) | ●●○ | ●●● | C2는 hot data를 적절한 tier에 둘 수 있어 steady-state latency에 유리할 가능성. 단 prediction miss 시 반대 가능 |
| Resource Utilization | ●●● | ●●○ | C1은 pool pressure를 직접 기준으로 전체 memory capacity 활용에 유리. C2는 data-optimal decision이 resource-global optimum과 항상 같지는 않음 |
| Modifiability | ●●● | ●●○ | C1은 static affinity 확장 중심. C2는 behavior feature/predictor 변경 영향이 큼 |

> 위 점수는 **architecture-level qualitative hypothesis**이며 측정 결과가 아니다.
> PPT의 00 TPS / 00 ms / 00%는 아직 simulation/benchmark 값이 들어가지 않은 placeholder이므로
> 실제 수치 평가는 별도의 QA simulation 문서에서 정의해야 한다.

Event-driven Migration Scheduler와 공통 Data Object Registry는
두 후보에 동일하게 추가되므로 **C1/C2 간 QA 차이를 만드는 핵심 요인으로 보지 않는다.**
차이는 Scheduler 이후 decision pipeline에서 발생한다.

---

# 19. QA Measurement Direction

## 19.1 Throughput

관찰 대상:

~~~text
request/s
output token/s
migration decision/s
migration bytes/s
event handling overhead
migration scheduler queue delay
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
event-to-decision latency
decision latency
~~~

Event 기반 구조에서는 다음 구간을 별도로 보는 것이 좋다.

~~~text
T_event_to_decision
 = T_event_queue
 + T_monitor
 + T_analysis
 + T_selection
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

- 신규 event type 추가
- 신규 memory tier 추가
- 신규 AI data class 추가
- Data Object Registry schema 확장
- predictor 변경
- affinity rule 변경
- telemetry metric 추가

C1은 신규 data type 추가 시
Registry metadata + affinity metadata 추가로 대응 가능한 범위가 넓다.

C2는 신규 data type별
behavior feature / interpretation / predictor input 검토가 필요하다.

---

# 20. vLLM / Migration Architecture Mapping

DP1은 기존 vLLM **Scheduler → Executor → Worker** call path를 대체하지 않는다.

현재 구조에서는 request path의 특정 지점이 migration logic을 동기 호출하는 형태보다,
runtime Event를 DP1 Migration Scheduler에 전달하고
별도의 decision cycle을 비동기로 실행하는 구조를 사용한다.

~~~text
Runtime / vLLM Event
        │
        ▼
DP1 Migration Scheduler
        │
        ├───────────────┬───────────────┐
        │               │
        ▼               ▼
C1 Resource         C2 Behavior
Decision Pipeline   Decision Pipeline
        │               │
        └───────┬───────┘
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
         MigrationPlanner
                │
     execution-side queue/scheduler
                │
       MigrationExecutor
                │
          Worker side
                │
       Transfer Handlers
                │
       HBM/DRAM/CXL/SSD
~~~

여기서 두 scheduler를 구분한다.

| Component | 역할 |
|---|---|
| **DP1 Migration Scheduler** | Event-driven decision orchestration. C1/C2 monitor/analysis pipeline을 시작 |
| **Execution-side Migration Scheduler/Queue** | 이미 결정된 MigrationPlan의 실행 순서/priority/bandwidth를 관리 |

---

# 21. Recommended Module Boundary

구현 관점에서는 다음 package boundary가 적절하다.

~~~text
vllm/v1/data_migration/
├── coordinator.py
├── planner.py
├── execution_scheduler.py          # execution-side migration queue
├── ...
│
├── decision/                       # DP1 decision layer
│   ├── migration_scheduler.py      # Event-driven DP1 Migration Scheduler
│   ├── events.py
│   ├── base.py
│   │
│   ├── data_object_registry.py     # C1/C2 common
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
│       └── data_selector.py
│
├── resource/
│   ├── registry.py
│   └── telemetry.py
│
└── worker/
    └── executor.py
~~~

Data-class별 세부 logic이 필요하면
Data Object Registry의 metadata provider 또는
Data Behavior Monitor plugin으로 확장할 수 있다.

~~~text
behavior_driven/
└── plugins/
    ├── kv_cache.py
    ├── agent_memory.py
    ├── lora.py
    ├── moe.py
    └── vector_index.py
~~~

중요한 원칙은 다음과 같다.

> **Data Object Registry는 C1/C2 공통 object metadata authority이고,  
> C1/C2의 차이는 Registry 자체가 아니라 그 위에 쌓이는 decision logic이다.**

---

# 22. Recommended Interfaces

## 22.1 Event Input

~~~text
MigrationEvent
 ├─ event_id
 ├─ event_type
 ├─ timestamp
 ├─ resource_id?
 ├─ data_ref?
 └─ metadata
~~~

## 22.2 Migration Scheduler

~~~text
MigrationScheduler.on_event(event)

  → enqueue / coalesce event
  → select decision pipeline
  → asynchronously trigger evaluate()
~~~

## 22.3 Data Object Registry

~~~text
DataObjectRegistry
  get(object_id) -> DataObjectRecord
  get_by_tier(tier) -> list[DataObjectRecord]
  get_migratable(resource_id) -> list[DataObjectRecord]
  update_location(object_id, location)
~~~

DP1 decision 단계에서는 Registry를 read-mostly로 사용한다.
실제 migration 완료 후 authoritative location update는
공통 migration control plane의 commit 결과와 동기화되어야 한다.

## 22.4 Common Policy Interface

~~~text
MigrationDecisionPolicy.evaluate(
    event,
    resource_snapshot,
    data_object_registry,
) -> list[MigrationDecision]
~~~

## 22.5 MigrationDecision

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

## 22.6 C1 Policy Metadata

~~~text
policy_metadata
 ├─ trigger_event
 ├─ pressure_type
 ├─ pressure_score
 ├─ predicted_pressure
 ├─ affinity_class
 └─ eviction_reason
~~~

## 22.7 C2 Policy Metadata

~~~text
policy_metadata
 ├─ trigger_event
 ├─ behavior_class
 ├─ reuse_score
 ├─ predicted_hotness
 ├─ prediction_confidence
 └─ lifetime_state
~~~

---

# 23. Important Boundary: Data Object Registry vs Behavior Prediction

C1과 C2 모두 Data Object Registry가 있으므로,
"Registry가 있는가 없는가"로 후보를 구분하면 안 된다.

## 23.1 C1 Registry usage

~~~text
"이 object는 KV Cache다"
"현재 CXL tier에 있다"
"크기는 256 MB다"
"현재 migration 가능한 상태다"
~~~

- object identity / type / location / size 중심
- static metadata 중심
- runtime future behavior를 예측하지 않음

## 23.2 C2 Registry + behavior usage

~~~text
"이 object는 KV Cache B17이다"
"현재 CXL tier에 있다"
+
"최근 reuse interval이 짧아지고 있다"
"future reuse probability가 높다"
~~~

- Registry의 object metadata
- Behavior Monitor의 runtime history
- Trend Analyzer / Predictor의 dynamic inference

즉:

> **C1도 Data Object를 안다. C2는 Data Object의 future behavior까지 추론한다.**

---

# 24. Important Boundary: Static Affinity vs Dynamic Behavior

C1과 C2가 비슷해 보이지 않도록 이 경계를 명확히 유지해야 한다.

## C1 static affinity

~~~text
"KV Cache는 generally latency/BW sensitive"
"Agent Memory는 capacity-rich tier도 허용 가능"
"MoE Expert weight는 bandwidth-rich tier가 유리할 수 있음"
~~~

- design-time / configuration-time 지식
- data class / operation 수준
- request마다 다시 학습하지 않음
- runtime access history가 없어도 동작

## C2 dynamic behavior

~~~text
"KV block B17의 최근 reuse가 증가 중"
"Expert E5의 activation frequency가 증가 중"
"LoRA A3의 active session이 종료되어 reuse 가능성이 낮아짐"
~~~

- runtime observation
- object/session 수준
- 시간에 따라 계속 바뀜
- history와 prediction이 필요

따라서 **C1에 Data Object Registry와 Affinity Mapper를 모두 두어도 C2와 동일해지는 것은 아니다.**

---

# 25. Design Decision Summary

## 공통 Entry Structure

~~~text
Event
  ↓
Migration Scheduler
  ↓ asynchronous decision trigger
C1 or C2
~~~

## C1 — Resource State-driven + Data-Memory Affinity

~~~text
Resource pressure is the primary signal.
Data Object Registry identifies candidate objects.
Static AI Data characteristics refine the decision.
~~~

주요 특성:

- event-driven / asynchronous entry
- low decision overhead
- fast pressure response
- strong global pool utilization orientation
- common Data Object Registry
- static AI data hints
- Agent-aware KV lifecycle은 별도 구조에서 보완

## C2 — AI Data Behavior-driven

~~~text
Future data usage is the primary signal.
Data Object Registry anchors object identity/class.
Resource state constrains the decision.
~~~

주요 특성:

- event-driven / asynchronous entry
- data/object-specific migration
- dynamic behavior monitoring
- future behavior prediction
- fine-grained hot-tier usage
- higher overhead / mis-placement risk

공통 migration execution은
**doc-mk/vllm-ai-data-migration-architecture.md**의
MigrationCoordinator / MigrationPlanner / MigrationExecutor 구조를 재사용한다.

---

# 26. Follow-up Items

DP1 상세 설계에서 다음 항목은 별도 페이지/문서로 구체화한다.

1. **Migration Event Model**
   - 어떤 event가 C1/C2 evaluation을 trigger하는지
   - event coalescing / debounce / priority
2. **Data Object Registry Schema**
   - common field와 data-class-specific metadata 분리
   - location update ownership
3. **C1 Data-Memory Affinity Table**
   - KV / Agent Memory / LoRA / MoE / Vector Index별 static hint 정의
4. **C1 Resource Trend Function**
   - pressure score / threshold / look-ahead window
5. **C1 Eviction Candidate Policy**
   - LRU / size-aware / pressure-relief-aware
6. **C2 Behavior Feature Schema**
   - data class별 observable 정의
7. **C2 Future Behavior Predictor**
   - rule-based vs history-based predictor
8. **C2 Anti-thrashing**
   - confidence / hysteresis / cooldown / migration budget
9. **QA별 quantitative evaluation criteria**
   - TPS, TTFT/TPOT, utilization, event-to-decision latency 기준
10. **Simulation workload**
   - KV reuse skew / LoRA popularity / MoE expert skew / memory pressure 변화 시나리오

---

# 27. References

- **doc-mk/vllm-ai-data-migration-architecture.md**
- **doc-mk/vllm-call-path-analysis.md**
- **doc-mk/vllm-kv-cache-memory-abstraction-layer.md**
- **doc-mk/vllm-kv-cache-memory-tiering.md**
