# DP1. AI Data Placement Implementation UML

> `dp1-implementation-uml.md`의 KV Cache 배치 구현 UML을 기반으로, DP1의 범위를 **AI Runtime Data Placement**로 일반화한 상세 구현 UML이다.
>
> 핵심은 C1/C2를 단순한 Policy 이름 차이가 아니라 **Primary Object / Registry / Runtime State / Planner / Sequence**까지 구조적으로 다르게 정의하는 것이다.

---

# 0. Design Principles

## 0.1 DP1의 결정 대상

```mermaid
flowchart LR
    D[AI Runtime Data Object] -->|Placement Decision| M[Memory Tier]
```

| 질문 | DP |
|---|---|
| Data를 어느 Memory Tier에 둘 것인가? | **DP1** |
| Prefill을 어느 Compute Resource에서 수행할 것인가? | **DP2** |
| 어떤 Data를 제거할 것인가? | **DP3** |
| Data를 Tier 간 어떻게 이동할 것인가? | **DP4** |

`Memory Compute Capability`는 DP1에서 **Memory Descriptor의 속성**으로 사용할 수 있지만, Compute Placement 자체는 DP2에서 결정한다.

## 0.2 C1 / C2 정의

```mermaid
flowchart LR
    subgraph C1["C1 Memory-centric"]
        R[Memory Resource] --> RS[Resource State] --> RP[Resource-aware Planner]
    end
    subgraph C2["C2 Data-centric"]
        D[Data Object] --> DS[Data Runtime State] --> DP[Data-aware Planner]
    end
```

- **C1:** Memory Resource가 1차 decision subject
- **C2:** Data Object가 1차 decision subject
- Candidate Filtering / Cost Evaluation / Executor는 공통

---

# 1. Common Module View

```mermaid
graph TB
    subgraph RUNTIME["AI Runtime / Serving System"]
        SCH[Scheduler / Request Manager]
        PROD[Data Producer / Consumer]
        OBS[Runtime Observer]
    end

    subgraph DP1["DP1 Placement Framework"]
        LIFE[Placement Lifecycle Controller]
        PM[Placement Manager]
        POLICY[Placement Policy Interface]
        FILTER[Candidate Memory Filter]
        COST[Cost / Utility Evaluator]
        REG[Placement Registry]
        EXEC[Placement Executor]
    end

    subgraph DATA["Data Abstraction"]
        DD[Data Descriptor]
        DS[Data Runtime State]
        ADAPTER[Data Type Adapter]
    end

    subgraph MEM["Memory Abstraction"]
        MREG[Memory Resource Registry]
        MD[Memory Descriptor]
        MS[Memory State]
        SS[System State]
    end

    subgraph BACKEND["Memory Resources"]
        HBM[HBM]
        DRAM[DRAM]
        CXL[CXL Memory]
        PNM[PIM / PNM]
        SSD[SSD / SSD-PIM]
    end

    SCH --> LIFE
    PROD --> PM
    OBS --> LIFE
    LIFE --> PM
    PM --> POLICY
    POLICY --> DD
    POLICY --> DS
    POLICY --> FILTER
    FILTER --> COST
    COST --> POLICY
    POLICY --> PM
    PM --> REG
    PM --> EXEC

    FILTER --> MREG
    MREG --> MD
    MD --> MS
    COST --> SS
    EXEC --> HBM
    EXEC --> DRAM
    EXEC --> CXL
    EXEC --> PNM
    EXEC --> SSD

    DD --> ADAPTER
```

### Common module responsibility

| Module | 책임 |
|---|---|
| `PlacementLifecycleController` | 생성/접근/비활성/pressure 등의 event를 placement trigger로 변환 |
| `PlacementManager` | placement lifecycle의 orchestration |
| `PlacementPolicy` | C1/C2 후보 정책의 공통 interface |
| `CandidateMemoryFilter` | Capacity / Operation / Reachability / QoS / Constraint 검사 |
| `CostUtilityEvaluator` | Access / Capacity / Migration / Operation / Constraint 비용 계산 |
| `PlacementRegistry` | object별 current placement 기록 |
| `PlacementExecutor` | 결정 결과의 실제 allocation / release 실행 |
| `DataTypeAdapter` | Data Type-specific representation을 공통 descriptor로 변환 |
| `MemoryResourceRegistry` | Memory backend 등록/조회 |
| `MemoryDescriptor` | 정적 Memory property |
| `MemoryState` | Runtime Memory property |

---

# 2. Common Class Model

## 2.1 Placement Core

```mermaid
classDiagram
    class PlacementManager {
        -PlacementPolicy policy
        -PlacementLifecycleController lifecycle
        -PlacementRegistry registry
        -PlacementExecutor executor
        +onCreate(event) PlacementDecision
        +onAccess(event) void
        +onPressure(event) void
        +reevaluate(objectId) PlacementDecision
    }

    class PlacementPolicy {
        <<interface>>
        +place(request, context) PlacementDecision
        +reevaluate(request, context) PlacementDecision
    }

    class PlacementContext {
        +DataDescriptor data
        +DataRuntimeState dataState
        +MemoryStateView memoryView
        +SystemState systemState
    }

    class PlacementDecision {
        +ObjectId objectId
        +ResourceId sourceTier
        +ResourceId destinationTier
        +DecisionReason reason
        +Cost estimatedCost
        +float confidence
        +bool requiresMigration
    }

    class PlacementRegistry {
        +record(decision) void
        +lookup(objectId) PlacementRecord
        +currentTier(objectId) ResourceId
    }

    class PlacementExecutor {
        +execute(decision) ExecutionResult
    }

    class CandidateMemoryFilter {
        +filter(data, memories, context) MemoryResource[]
    }

    class CostUtilityEvaluator {
        +evaluate(data, memory, context) PlacementScore
    }

    PlacementManager --> PlacementPolicy
    PlacementManager --> PlacementLifecycleController
    PlacementManager --> PlacementRegistry
    PlacementManager --> PlacementExecutor
    PlacementPolicy --> PlacementContext
    PlacementPolicy --> PlacementDecision
    PlacementPolicy --> CandidateMemoryFilter
    PlacementPolicy --> CostUtilityEvaluator
```

## 2.2 Data Model

```mermaid
classDiagram
    class DataObject {
        +ObjectId objectId
        +DataType dataType
        +long sizeBytes
        +ResourceId currentTier
        +LifecycleState lifecycle
    }

    class DataDescriptor {
        +ObjectId objectId
        +DataType dataType
        +long sizeBytes
        +ResourceId currentTier
        +float hotness
        +float reuse
        +Duration lifetime
        +Locality locality
        +AccessPattern accessPattern
        +float readWriteIntensity
        +SharingMode sharing
        +Set~Operation~ requiredOperations
        +Map~String,String~ attributes
    }

    class DataRuntimeState {
        +float recentAccessRate
        +float recentReuseRate
        +Timestamp lastAccess
        +Duration inactiveDuration
        +long accessCount
        +long accessBytes
        +LifecycleState lifecycle
    }

    class DataObjectEvent {
        +EventType type
        +ObjectId objectId
        +Timestamp timestamp
    }

    class DataAccessEvent {
        +ObjectId objectId
        +Operation operation
        +long bytes
        +Duration latency
        +Timestamp timestamp
    }

    DataObject --> DataDescriptor
    DataObject --> DataRuntimeState
    DataObjectEvent --> DataObject
    DataAccessEvent --> DataObject
```

## 2.3 Memory Model

```mermaid
classDiagram
    class MemoryResource {
        <<interface>>
        +descriptor() MemoryDescriptor
        +state() MemoryState
        +allocate(sizeBytes) AllocationHandle
        +release(handle) void
        +contains(objectId) bool
    }

    class MemoryDescriptor {
        +ResourceId memoryId
        +MemoryType memoryType
        +long capacityBytes
        +long availableBytes
        +Bandwidth externalBandwidth
        +Bandwidth internalBandwidth
        +Duration latency
        +ComputeCapability computeCapability
        +AccessPath accessPath
        +WriteConstraint writeConstraint
    }

    class MemoryState {
        +long usedBytes
        +float memoryPressure
        +float currentLoad
        +float bandwidthUtilization
        +float queueDepth
        +long writeBytes
    }

    class ComputeCapability {
        +Set~Operation~ supportedOperations
        +Throughput computeThroughput
        +float computeEfficiency
    }

    class MemoryResourceRegistry {
        +register(resource) void
        +get(id) MemoryResource
        +list() MemoryResource[]
    }

    class MemoryStateView {
        +memories() MemoryResource[]
        +descriptor(id) MemoryDescriptor
        +state(id) MemoryState
        +available(id) long
        +supports(id, operations) bool
    }

    MemoryResource --> MemoryDescriptor
    MemoryResource --> MemoryState
    MemoryDescriptor --> ComputeCapability
    MemoryStateView --> MemoryResourceRegistry
    MemoryStateView --> MemoryDescriptor
    MemoryStateView --> MemoryState
```

---

# 3. C1 Memory-centric

## 3.1 C1 Module View

```mermaid
graph TB
    RT[AI Runtime / Scheduler]

    subgraph C1["C1 Memory-centric Placement"]
        MRM[Memory Resource Manager]
        RR[Resource Registry]
        MON[Resource State Monitor]
        COL[Memory State Collector]
        PLAN[Resource-aware Placement Planner]
        RAC[Resource Allocation Controller]
    end

    subgraph COMMON["Common Placement Services"]
        FILTER[Candidate Memory Filter]
        COST[Cost / Utility Evaluator]
        EXEC[Placement Executor]
    end

    subgraph MEM["Memory Resource Layer"]
        HBM[HBM Resource]
        DRAM[DRAM Resource]
        CXL[CXL Memory]
        PNM[PIM / PNM]
        SSD[SSD / SSD-PIM]
    end

    RT -->|AllocationRequest| MRM
    MRM --> RR
    RR --> MON
    MON --> COL
    COL --> PLAN
    PLAN --> FILTER
    FILTER --> COST
    COST --> PLAN
    PLAN --> RAC
    RAC --> EXEC
    EXEC --> HBM
    EXEC --> DRAM
    EXEC --> CXL
    EXEC --> PNM
    EXEC --> SSD
    MON -. monitor .-> HBM
    MON -. monitor .-> DRAM
    MON -. monitor .-> CXL
    MON -. monitor .-> PNM
    MON -. monitor .-> SSD
```

### C1 구조

> **Resource Registry → Resource State → Resource-aware Planner → Allocation Controller → Executor**

Data descriptor는 입력이지만 C1의 primary state는 아니다.

## 3.2 C1 Class Diagram

```mermaid
classDiagram
    class MemoryResourceManager {
        -ResourceRegistry registry
        -ResourceStateMonitor monitor
        -MemoryStateCollector collector
        -ResourceAwarePlacementPlanner planner
        -ResourceAllocationController allocator
        +allocate(request, context) PlacementDecision
        +reevaluate(resources) PlacementDecision[]
        +registerResource(resource) void
    }

    class ResourceRegistry {
        +register(resource) void
        +get(id) MemoryResource
        +listCandidates() MemoryResource[]
    }

    class ResourceStateMonitor {
        +refresh(id) MemoryState
        +refreshAll() MemoryState[]
    }

    class MemoryStateCollector {
        +collect(view) MemoryStateSnapshot
    }

    class MemoryStateSnapshot {
        +Map~ResourceId,MemoryDescriptor~ descriptors
        +Map~ResourceId,MemoryState~ states
        +availableCapacity(id) long
        +load(id) float
        +bandwidth(id) Bandwidth
    }

    class ResourceAwarePlacementPlanner {
        -CandidateMemoryFilter filter
        -CostUtilityEvaluator evaluator
        +plan(request, snapshot, context) PlacementDecision
        +rank(resources, request) PlacementScore[]
    }

    class ResourceAllocationController {
        +allocate(data, resource) AllocationHandle
        +release(handle) void
    }

    MemoryResourceManager --> ResourceRegistry
    MemoryResourceManager --> ResourceStateMonitor
    MemoryResourceManager --> MemoryStateCollector
    MemoryResourceManager --> ResourceAwarePlacementPlanner
    MemoryResourceManager --> ResourceAllocationController
    ResourceStateMonitor --> ResourceRegistry
    MemoryStateCollector --> MemoryStateSnapshot
    ResourceAwarePlacementPlanner --> CandidateMemoryFilter
    ResourceAwarePlacementPlanner --> CostUtilityEvaluator
    ResourceAllocationController --> MemoryResource
```

## 3.3 C1 Decision Flow

```mermaid
flowchart TB
    REQ[AllocationRequest]
    RR[Resource Registry]
    SNAP[Resource State Snapshot]
    FIL[Feasibility Filter]
    SCORE[Common Cost / Utility]
    RANK[Resource Ranking]
    SEL[Best Resource]
    DEC[PlacementDecision]

    REQ --> RR
    RR --> SNAP
    REQ --> FIL
    SNAP --> FIL
    FIL --> SCORE
    REQ --> SCORE
    SNAP --> SCORE
    SCORE --> RANK --> SEL --> DEC
```

C1의 핵심 질문:

> **“현재 어느 Memory Resource가 이 Data를 가장 적합하게 수용할 수 있는가?”**

## 3.4 C1 Initial Placement Sequence

```mermaid
sequenceDiagram
    autonumber
    participant RT as AI Runtime
    participant MRM as MemoryResourceManager
    participant RR as ResourceRegistry
    participant MON as ResourceStateMonitor
    participant COL as MemoryStateCollector
    participant PLAN as ResourceAwarePlanner
    participant FIL as CandidateMemoryFilter
    participant COST as CostUtilityEvaluator
    participant EX as PlacementExecutor
    participant MEM as MemoryResource

    RT->>MRM: allocate(request, context)
    MRM->>RR: listCandidates()
    RR-->>MRM: MemoryResource[]
    MRM->>MON: refreshAll()
    MON-->>MRM: MemoryState[]
    MRM->>COL: collect(memoryView)
    COL-->>MRM: MemoryStateSnapshot
    MRM->>PLAN: plan(request, snapshot, context)
    PLAN->>FIL: filter(data, resources)
    FIL-->>PLAN: feasible resources
    PLAN->>COST: evaluate(data, each resource)
    COST-->>PLAN: PlacementScore[]
    PLAN-->>MRM: PlacementDecision
    MRM->>EX: execute(decision)
    EX->>MEM: allocate(sizeBytes)
    MEM-->>EX: AllocationHandle
    EX-->>MRM: ExecutionResult
    MRM-->>RT: PlacementResult
```

## 3.5 C1 Re-placement Sequence

```mermaid
sequenceDiagram
    autonumber
    participant MON as Runtime Monitor
    participant MRM as MemoryResourceManager
    participant RMON as ResourceStateMonitor
    participant PLAN as ResourceAwarePlanner
    participant EX as PlacementExecutor
    participant DP4 as DP4 Migration

    MON->>MRM: resource pressure / BW contention
    MRM->>RMON: refresh(affected resources)
    RMON-->>MRM: updated state
    MRM->>PLAN: reevaluate(affected data)
    PLAN-->>MRM: PlacementDecision
    alt destination changed
        MRM->>EX: execute(decision)
        EX->>DP4: migrate(object, source, destination)
        DP4-->>EX: migration result
    else no change
        MRM-->>MON: keep current placement
    end
```

---

# 4. C2 Data-centric

## 4.1 C2 Module View

```mermaid
graph TB
    RT[AI Runtime / Scheduler]

    subgraph C2["C2 Data-centric Placement"]
        DPM[Data Placement Manager]
        DREG[Data Object Registry]
        DAD[Data Type Adapter Layer]
        CHAR[Data Characterizer]
        DSM[Data Runtime State Monitor]
        PLAN[Data-aware Placement Planner]
        LIFE[Placement Lifecycle Controller]
    end

    subgraph TYPES["Data Type-specific Layer"]
        KV[KV Cache Adapter / Characterizer]
        RAG[RAG Data Adapter / Characterizer]
        AG[Agent Memory Adapter / Characterizer]
        TOOL[Tool Result Adapter / Characterizer]
        LORA[LoRA Adapter / Characterizer]
        MOE[MoE Expert Adapter / Characterizer]
    end

    subgraph COMMON["Common Services"]
        FILTER[Candidate Memory Filter]
        COST[Cost / Utility Evaluator]
        EXEC[Placement Executor]
        MREG[Memory Resource Registry]
    end

    RT -->|DataObjectEvent| DPM
    DPM --> DREG
    DREG --> DAD
    DAD --> CHAR
    CHAR --> DSM
    DSM --> PLAN
    PLAN --> FILTER
    FILTER --> COST
    COST --> PLAN
    PLAN --> LIFE
    LIFE --> EXEC
    PLAN --> MREG

    DAD --> KV
    DAD --> RAG
    DAD --> AG
    DAD --> TOOL
    DAD --> LORA
    DAD --> MOE
```

### C2 구조

> **Data Registry → Data Type Adapter → Characterization → Data Runtime State → Data-aware Planner → Executor**

## 4.2 C2 Class Diagram

```mermaid
classDiagram
    class DataPlacementManager {
        -DataObjectRegistry registry
        -DataCharacterizer characterizer
        -DataRuntimeStateMonitor stateMonitor
        -DataAwarePlacementPlanner planner
        -PlacementLifecycleController lifecycle
        +onDataEvent(event) PlacementDecision
        +reevaluate(objectId) PlacementDecision
    }

    class DataObjectRegistry {
        +register(data) void
        +get(id) DataObject
        +listActive() DataObject[]
        +listByType(type) DataObject[]
    }

    class DataTypeAdapter {
        <<interface>>
        +supports(type) bool
        +describe(data) DataDescriptor
        +placementUnit(data) PlacementUnit
        +accessRequirements(data) AccessRequirement
    }

    class DataCharacterizer {
        +characterize(data, runtimeState) DataDescriptor
        +update(objectId, observation) void
    }

    class DataRuntimeStateMonitor {
        +observe(event) void
        +getState(objectId) DataRuntimeState
        +snapshot(objectId) DataRuntimeState
    }

    class DataAwarePlacementPlanner {
        -CandidateMemoryFilter filter
        -CostUtilityEvaluator evaluator
        +plan(data, state, memoryView, systemState) PlacementDecision
        +rank(data, memories) PlacementScore[]
    }

    class PlacementLifecycleController {
        +onCreate(event) PlacementTrigger
        +onAccess(event) PlacementTrigger
        +onInactive(event) PlacementTrigger
        +onPressure(event) PlacementTrigger
    }

    DataPlacementManager --> DataObjectRegistry
    DataPlacementManager --> DataCharacterizer
    DataPlacementManager --> DataRuntimeStateMonitor
    DataPlacementManager --> DataAwarePlacementPlanner
    DataPlacementManager --> PlacementLifecycleController
    DataTypeAdapter --> DataDescriptor
    DataCharacterizer --> DataDescriptor
    DataRuntimeStateMonitor --> DataRuntimeState
    DataAwarePlacementPlanner --> CandidateMemoryFilter
    DataAwarePlacementPlanner --> CostUtilityEvaluator
```

## 4.3 C2 Data-centric Funnel

```mermaid
flowchart TB
    D[Data Object]
    DESC[Data Descriptor]
    STATE[Data Runtime State]
    CLASS[Data Characteristic / Class]
    CAND[Data-aware Candidate Formation]
    FIL[Feasibility Filter]
    SCORE[Common Cost / Utility]
    BEST[Best Memory Tier]

    D --> DESC
    D --> STATE
    DESC --> CLASS
    STATE --> CLASS
    CLASS --> CAND
    CAND --> FIL
    FIL --> SCORE
    SCORE --> BEST
```

C2의 핵심 질문:

> **“이 Data Object의 Hotness / Reuse / Lifetime / Locality 등을 고려할 때 어느 Memory Tier가 적합한가?”**

## 4.4 C2 Initial Placement Sequence

```mermaid
sequenceDiagram
    autonumber
    participant RT as AI Runtime
    participant DPM as DataPlacementManager
    participant REG as DataObjectRegistry
    participant AD as DataTypeAdapter
    participant MON as DataRuntimeStateMonitor
    participant CHAR as DataCharacterizer
    participant PLAN as DataAwarePlanner
    participant FIL as CandidateMemoryFilter
    participant COST as CostUtilityEvaluator
    participant EX as PlacementExecutor

    RT->>DPM: onDataCreated(DataObjectEvent)
    DPM->>REG: get(objectId)
    REG-->>DPM: DataObject
    DPM->>AD: describe(data)
    AD-->>DPM: DataDescriptor
    DPM->>MON: getState(objectId)
    MON-->>DPM: DataRuntimeState
    DPM->>CHAR: characterize(data, state)
    CHAR-->>DPM: enriched DataDescriptor
    DPM->>PLAN: plan(data, state, memoryView, systemState)
    PLAN->>FIL: filter(data, memories)
    FIL-->>PLAN: feasible candidate set
    PLAN->>COST: evaluate(data, candidate)
    COST-->>PLAN: PlacementScore[]
    PLAN-->>DPM: PlacementDecision
    DPM->>EX: execute(decision)
    EX-->>DPM: ExecutionResult
    DPM-->>RT: PlacementResult
```

## 4.5 C2 Runtime Re-evaluation Sequence

```mermaid
sequenceDiagram
    autonumber
    participant RT as Runtime
    participant MON as DataRuntimeStateMonitor
    participant LIFE as LifecycleController
    participant DPM as DataPlacementManager
    participant CHAR as DataCharacterizer
    participant PLAN as DataAwarePlanner
    participant EX as PlacementExecutor
    participant DP4 as DP4 Migration

    RT->>MON: DataAccessEvent
    MON->>LIFE: access / state change
    LIFE-->>DPM: PlacementTrigger
    DPM->>MON: getState(object)
    MON-->>DPM: updated DataRuntimeState
    DPM->>CHAR: characterize(data, state)
    CHAR-->>DPM: updated DataDescriptor
    DPM->>PLAN: reevaluate(data, state, memoryView, systemState)
    PLAN-->>DPM: PlacementDecision
    alt destination changed
        DPM->>EX: execute(decision)
        EX->>DP4: migrate(object, source, destination)
        DP4-->>EX: migration result
    else keep current tier
        DPM-->>RT: no placement change
    end
```

---

# 5. Data Type-specific C2 Extension

## 5.1 Adapter Hierarchy

```mermaid
classDiagram
    class DataTypeAdapter {
        <<interface>>
        +supports(type) bool
        +describe(data) DataDescriptor
        +placementUnit(data) PlacementUnit
        +accessRequirements(data) AccessRequirement
    }
    class KVCacheAdapter
    class RAGDataAdapter
    class AgentMemoryAdapter
    class ToolResultAdapter
    class LoRAAdapter
    class MoEExpertAdapter

    DataTypeAdapter <|.. KVCacheAdapter
    DataTypeAdapter <|.. RAGDataAdapter
    DataTypeAdapter <|.. AgentMemoryAdapter
    DataTypeAdapter <|.. ToolResultAdapter
    DataTypeAdapter <|.. LoRAAdapter
    DataTypeAdapter <|.. MoEExpertAdapter
```

## 5.2 Characterization Hierarchy

```mermaid
classDiagram
    class DataCharacterizer {
        +characterize(data, state) DataDescriptor
    }
    class KVCacheCharacterizer {
        +hotness(data, state) float
        +reuse(data, state) float
        +lifetime(data, state) Duration
        +locality(data, state) Locality
    }
    class RAGCharacterizer {
        +queryHotness(data, state) float
        +reuse(data, state) float
        +indexLocality(data, state) Locality
        +readIntensity(data, state) float
    }
    class AgentMemoryCharacterizer {
        +sessionHotness(data, state) float
        +turnReuse(data, state) float
        +lifetime(data, state) Duration
        +stepLocality(data, state) Locality
    }
    class ToolResultCharacterizer {
        +reuseProbability(data, state) float
        +lifetime(data, state) Duration
        +producerConsumerLocality(data, state) Locality
    }
    class LoRACharacterizer {
        +requestFrequency(data, state) float
        +reuse(data, state) float
        +activeWindow(data, state) Duration
    }
    class MoEExpertCharacterizer {
        +routingFrequency(data, state) float
        +routingSkew(data, state) float
        +reuse(data, state) float
    }

    DataCharacterizer <|-- KVCacheCharacterizer
    DataCharacterizer <|-- RAGCharacterizer
    DataCharacterizer <|-- AgentMemoryCharacterizer
    DataCharacterizer <|-- ToolResultCharacterizer
    DataCharacterizer <|-- LoRACharacterizer
    DataCharacterizer <|-- MoEExpertCharacterizer
```

> C2의 범용성을 유지하기 위해 **Data-specific knowledge는 Characterizer까지**, Tier selection은 공통 `DataAwarePlacementPlanner`로 올라간다.

---

# 6. Common Candidate / Cost / Execution UML

## 6.1 Feasibility vs Cost

```mermaid
flowchart LR
    ALL[All Memory Resources]
    FEAS[Feasibility Filter]
    CAND[Candidate Set]
    COST[Cost / Utility Evaluator]
    BEST[Tier Selection]

    ALL --> FEAS --> CAND --> COST --> BEST
```

### Feasibility

- Capacity
- Supported Operation
- Reachability
- Mandatory QoS
- Endurance / Write Constraint

### Cost

\[
Cost(d,m,s)=C_{access}+C_{capacity}+C_{migration}+C_{operation}+C_{constraint}
\]

## 6.2 Executor / DP4 boundary

```mermaid
sequenceDiagram
    participant P as DP1 Policy
    participant E as PlacementExecutor
    participant M as Memory Resource
    participant D as DP4 Migration

    P->>E: PlacementDecision
    alt new allocation
        E->>M: allocate(data)
        M-->>E: handle
    else tier change
        E->>D: migrate(source, destination, data)
        D-->>E: migration result
    end
```

DP1이 migration algorithm을 소유하지 않는 것이 핵심이다.

---

# 7. Lifecycle UML

```mermaid
stateDiagram-v2
    [*] --> Created
    Created --> Placing: create / ingest
    Placing --> Active: placement success
    Active --> Active: access / observe
    Active --> Reevaluate: state change
    Reevaluate --> Active: keep current tier
    Reevaluate --> Migrating: destination changes
    Migrating --> Active: DP4 complete
    Active --> Inactive: timeout / preemption / session end
    Inactive --> Reevaluate: reactivation / reuse
    Inactive --> [*]: release
```

### Trigger source

```mermaid
flowchart LR
    subgraph C1Trigger["C1"]
        RSTATE[Resource State Change]
        PRESS[Memory Pressure / BW Contention]
        RSTATE --> RP[Resource Re-evaluation]
        PRESS --> RP
    end

    subgraph C2Trigger["C2"]
        ACCESS[Data Access]
        HOTNESS[Hotness / Reuse Change]
        LIFETIME[Lifetime / Locality Change]
        ACCESS --> DP[Data Re-evaluation]
        HOTNESS --> DP
        LIFETIME --> DP
    end
```

---

# 8. C1 vs C2 UML Comparison

```mermaid
flowchart LR
    subgraph C1["C1"]
        CR[Resource Registry]
        CS[Resource State]
        CP[Resource-aware Planner]
        CR --> CS --> CP
    end

    subgraph C2["C2"]
        DR[Data Registry]
        DC[Data Characterization]
        DS[Data Runtime State]
        DP[Data-aware Planner]
        DR --> DC --> DS --> DP
    end

    F[Common Feasibility]
    S[Common Cost / Utility]
    X[Common Executor]

    CP --> F
    DP --> F
    F --> S --> X
```

| 항목 | C1 | C2 |
|---|---|---|
| Primary Decision Subject | Memory Resource | Data Object |
| Primary Registry | Resource Registry | Data Object Registry |
| Primary Runtime State | Memory State | Data Runtime State |
| Candidate Formation | Resource State / Feasibility | Data Characteristic |
| Planner | Resource-aware | Data-aware |
| Data-specific Characterization | 최소 / 보조 | 핵심 |
| Extension Axis | New Memory Type | New Data Type |
| Common Cost Model | O | O |
| Common Executor | O | O |

---

# 9. UML → Architecture Mapping

최종 DP1 Architecture 그림은 다음 UML 객체를 블록으로 승격한다.

```mermaid
flowchart TB
    INPUT[Data Descriptor + Memory Descriptor + Runtime State]
    POLICY[Placement Policy]
    FILTER[Candidate Memory Filtering]
    COST[Cost / Utility Evaluation]
    DEC[Placement Decision]
    EXEC[Placement Executor]

    subgraph C1A["C1 Memory-centric"]
        RREG[Resource Registry]
        RM[Resource State Monitor]
        RP[Resource-aware Planner]
        RREG --> RM --> RP
    end

    subgraph C2A["C2 Data-centric"]
        DREG[Data Object Registry]
        DC[Data Characterizer]
        DM[Data Runtime State]
        DP[Data-aware Planner]
        DREG --> DC --> DM --> DP
    end

    INPUT --> POLICY
    POLICY --> FILTER --> COST --> DEC --> EXEC
    RP --> FILTER
    DP --> FILTER
```

### Architecture 재작성 시 보존해야 하는 것

1. **C1과 C2의 primary state owner 차이**
2. **C1은 Resource 중심의 flat decision 구조**
3. **C2는 Data characterization을 먼저 수행하는 funnel 구조**
4. Candidate Filter / Cost Model / Executor의 공통화
5. Memory Compute Capability는 Memory Descriptor에 포함하되 DP2 Compute Placement와 분리
6. 실제 movement는 DP4로 위임

---

# 10. Implementation Checklist

- [ ] `DataDescriptor`는 모든 Data Type에서 공통으로 제공한다.
- [ ] `DataTypeAdapter`가 physical representation 차이를 격리한다.
- [ ] `DataCharacterizer`가 Data-specific runtime characteristic을 생성한다.
- [ ] C1은 Resource Registry / Resource State를 primary state로 사용한다.
- [ ] C2는 Data Registry / Data Runtime State를 primary state로 사용한다.
- [ ] Candidate Filter와 Cost Evaluator를 분리한다.
- [ ] C1/C2가 동일 Cost / Utility evaluator를 공유한다.
- [ ] Memory Compute Capability를 Memory Descriptor에서 표현한다.
- [ ] Compute placement는 DP2에 두지 DP1로 가져오지 않는다.
- [ ] 실제 Migration algorithm은 DP4에 둔다.
- [ ] 신규 Memory Type 추가 시 Policy에 Memory 이름을 하드코딩하지 않는다.
- [ ] 신규 Data Type 추가 시 Common Planner interface를 변경하지 않는다.
