# DP1. AI Data Placement UML Design — Rendered

> **문서 유형:** UML / Implementation Design
>
> 본 문서는 `dp1-data-placement-design.md`의 C1/C2 Data Placement 구조를 구현 관점에서 정의한 UML 문서이다. GitHub에서 **Mermaid로 실제 도형/선/시퀀스가 렌더링**되도록 작성한다.
>
> 대상:
> - Common Module View
> - C1 Memory-centric Placement: Module / Class / Sequence
> - C2 Data-centric Placement: Module / Class / Sequence

## 1. UML 설계 원칙

C1과 C2는 동일한 DP1 공통 경계를 사용하지만, Placement Manager 내부의 **Primary Object / Registry / Runtime State / Planner** 구조를 다르게 구성한다.

- **C1:** Memory Resource 중심 → Resource Registry / Resource State / Resource Planner
- **C2:** Data Object 중심 → Data Registry / Data Characterizer / Data Planner
- Candidate Filtering / Cost Evaluation / Placement Execution은 공통 서비스로 유지한다.

## 2. Common Module View

```mermaid
flowchart LR
    RT[AI Runtime / Scheduler]

    subgraph DP1[DP1 Placement]
        PM[Placement Manager]
        CF[Candidate Memory Filter]
        CE[Cost / Utility Evaluator]
        EX[Placement Executor]
    end

    subgraph MA[Memory Resource Abstraction]
        RR[Memory Resource Registry]
        MD[Memory Descriptor]
        AD[Memory Adapter]
    end

    subgraph MEM[Memory Resources]
        HBM[HBM]
        DRAM[DRAM]
        CXL[CXL Memory]
        PIM[PIM / PNM]
    end

    RT -->|placement request / event| PM
    PM --> CF
    CF --> RR
    RR --> MD
    CF --> CE
    MD --> CE
    CE -->|scores / feasible set| PM
    PM --> EX
    EX --> AD
    AD --> HBM
    AD --> DRAM
    AD --> CXL
    AD --> PIM
```

### Common 책임

| Module | 책임 |
|---|---|
| Scheduler / Request Manager | Data 생성/유입, request lifecycle, placement trigger 제공 |
| Placement Manager | Placement decision 진입점 및 lifecycle 관리 |
| Candidate Memory Filter | Capacity, operation, reachability, QoS, constraint 기반 후보 제거 |
| Cost / Utility Evaluator | Access / Capacity / Migration / Operation / Constraint 비용 계산 |
| Placement Executor | 결정된 placement의 실제 allocation / release / placement action 수행 |
| Memory Resource Registry | Memory Resource 등록 및 조회 |
| Memory Descriptor | Capacity/BW/Latency/Compute Capability/Load 등 resource 상태 표현 |
| Memory Adapter | 실제 Memory backend와 공통 runtime interface 연결 |

> Migration 자체의 알고리즘은 DP4의 책임이다. DP1은 `PlacementDecision`을 생성하고 destination을 전달한다.

# 3. C1 Memory-centric Placement

## 3.1 C1 Module View

C1은 **Memory Resource를 primary state owner**로 둔다. 즉, Resource별 상태와 수용 가능량을 중심으로 Data allocation을 결정한다.

```mermaid
flowchart LR
    RT[AI Runtime / Scheduler]

    subgraph C1[C1 Memory-centric Placement]
        MRM[Memory Resource Manager]
        RR[Resource Registry]
        RSM[Resource State Monitor]
        RPP[Resource-aware Placement Planner]
        RAC[Resource Allocation Controller]
    end

    subgraph COMMON[Common Placement Services]
        CF[Candidate Memory Filter]
        CE[Cost / Utility Evaluator]
        EX[Placement Executor]
    end

    subgraph ADAPT[Memory Resource Adapters]
        HBM[HBM Adapter]
        DRAM[DRAM Adapter]
        CXL[CXL Adapter]
        PIM[PIM / PNM Adapter]
    end

    RT -->|AllocationRequest| MRM
    MRM --> RR
    RR --> RSM
    RSM -->|capacity / BW / load / capability| RPP
    RPP -->|candidate resources| CF
    CF -->|feasible resources| CE
    CE -->|resource scores| RPP
    RPP -->|selected resource| RAC
    RAC --> EX
    EX --> HBM
    EX --> DRAM
    EX --> CXL
    EX --> PIM

    RSM -. monitor .-> HBM
    RSM -. monitor .-> DRAM
    RSM -. monitor .-> CXL
    RSM -. monitor .-> PIM
```

### C1 핵심 구조

**Resource Registry → Resource State Monitor → Resource-aware Planner → Allocation Controller → Placement Executor**

## 3.2 C1 Class Diagram

```mermaid
classDiagram
    class MemoryResourceManager {
        +allocate(request: AllocationRequest) PlacementDecision
        +reevaluate(resourceId: ResourceId) PlacementDecision[]
        +registerResource(resource: MemoryResource)
    }

    class ResourceRegistry {
        +register(resource: MemoryResource)
        +get(resourceId: ResourceId) MemoryResource
        +listCandidates() MemoryResource[]
    }

    class ResourceStateMonitor {
        +getState(resourceId: ResourceId) ResourceState
        +refresh(resourceId: ResourceId) ResourceState
    }

    class ResourceAwarePlacementPlanner {
        +plan(request: AllocationRequest, resources: MemoryResource[]) PlacementDecision
        +rank(resources: MemoryResource[], request: AllocationRequest) MemoryResource[]
    }

    class ResourceAllocationController {
        +allocate(data: DataObject, resource: MemoryResource) AllocationHandle
        +release(handle: AllocationHandle)
    }

    class CandidateMemoryFilter {
        +filter(data: DataDescriptor, resources: MemoryResource[]) MemoryResource[]
    }

    class CostUtilityEvaluator {
        +evaluate(data: DataDescriptor, resource: MemoryResource, state: SystemState) PlacementScore
    }

    class PlacementExecutor {
        +execute(decision: PlacementDecision) ExecutionResult
    }

    class MemoryResource {
        <<interface>>
        +descriptor() MemoryDescriptor
        +state() ResourceState
        +allocate(sizeBytes: long) AllocationHandle
        +release(handle: AllocationHandle)
    }

    class MemoryDescriptor {
        +memoryId: ResourceId
        +memoryType: MemoryType
        +capacityBytes: long
        +availableBytes: long
        +externalBandwidth: Bandwidth
        +internalBandwidth: Bandwidth
        +latency: Duration
        +computeCapability: ComputeCapability
        +accessPath: AccessPath
    }

    class ResourceState {
        +currentLoad: float
        +bandwidthUtilization: float
        +memoryPressure: float
        +qosState: QoSState
    }

    class ComputeCapability {
        +supportedOperations: Operation[]
        +computeThroughput: Throughput
        +computeEfficiency: float
    }

    class AllocationRequest {
        +data: DataDescriptor
        +requiredOperations: Operation[]
        +qos: QoSRequirement
    }

    class DataDescriptor {
        +objectId: ObjectId
        +dataType: DataType
        +sizeBytes: long
        +currentTier: ResourceId
        +hotness: float
        +reuse: float
        +lifetime: Duration
        +locality: Locality
        +accessPattern: AccessPattern
    }

    class PlacementDecision {
        +objectId: ObjectId
        +sourceTier: ResourceId
        +destinationTier: ResourceId
        +decisionReason: String
        +estimatedCost: Cost
        +confidence: float
    }

    class DataObject
    class SystemState
    class PlacementScore
    class AllocationHandle
    class ExecutionResult
    class QoSRequirement
    class QoSState
    class AccessPath

    MemoryResourceManager --> ResourceRegistry : owns
    MemoryResourceManager --> ResourceStateMonitor : reads
    MemoryResourceManager --> ResourceAwarePlacementPlanner : invokes
    MemoryResourceManager --> ResourceAllocationController : invokes

    ResourceAwarePlacementPlanner --> CandidateMemoryFilter : filters
    ResourceAwarePlacementPlanner --> CostUtilityEvaluator : scores
    ResourceAwarePlacementPlanner --> PlacementDecision : creates

    ResourceRegistry o-- "1..*" MemoryResource : manages
    MemoryResource --> MemoryDescriptor : exposes
    MemoryResource --> ResourceState : reports
    MemoryDescriptor --> ComputeCapability : contains

    AllocationRequest --> DataDescriptor : carries
    CandidateMemoryFilter --> DataDescriptor : evaluates
    CandidateMemoryFilter --> MemoryResource : filters
    CostUtilityEvaluator --> DataDescriptor : evaluates
    CostUtilityEvaluator --> MemoryResource : evaluates
    CostUtilityEvaluator --> SystemState : reads

    ResourceAllocationController --> PlacementExecutor : delegates
    PlacementExecutor --> PlacementDecision : executes
```

## 3.3 C1 Sequence — Initial Placement

```mermaid
sequenceDiagram
    autonumber
    participant RT as AI Runtime
    participant MRM as MemoryResourceManager
    participant RR as ResourceRegistry
    participant RSM as ResourceStateMonitor
    participant RPP as ResourceAwarePlanner
    participant CF as CandidateMemoryFilter
    participant CE as CostUtilityEvaluator
    participant EX as PlacementExecutor
    participant MEM as MemoryResource

    RT->>MRM: allocate(data, requirements)
    MRM->>RR: listCandidates()
    RR-->>MRM: resources
    MRM->>RSM: getState(resources)
    RSM-->>MRM: resource states
    MRM->>RPP: plan(request, resources, states)
    RPP->>CF: filter(dataDescriptor, resources)
    CF-->>RPP: feasible resources
    RPP->>CE: evaluate(data, resource, state)
    CE-->>RPP: score(resource)
    RPP-->>MRM: PlacementDecision
    MRM->>EX: execute(decision)
    EX->>MEM: allocate(size)
    MEM-->>EX: AllocationHandle
    EX-->>MRM: ExecutionResult
    MRM-->>RT: PlacementResult
```

## 3.4 C1 Sequence — Re-placement Trigger

```mermaid
sequenceDiagram
    autonumber
    participant MON as Runtime Monitor
    participant MRM as MemoryResourceManager
    participant RSM as ResourceStateMonitor
    participant RPP as ResourceAwarePlanner
    participant EX as PlacementExecutor
    participant DP4 as DP4 Migration Service

    MON->>MRM: resource pressure / BW contention event
    MRM->>RSM: refresh(resource)
    RSM-->>MRM: updated ResourceState
    MRM->>RPP: reevaluate(affected data/resources)
    RPP-->>MRM: PlacementDecision

    alt destination differs from current tier
        MRM->>EX: execute(decision)
        EX->>DP4: migrate(source, destination, object)
        DP4-->>EX: migration result
    else keep current placement
        MRM-->>MON: no action
    end
```

# 4. C2 Data-centric Placement

## 4.1 C2 Module View

C2는 **Data Object를 primary state owner**로 둔다. Data별 lifecycle과 runtime characterization이 Tier 선택을 주도한다.

```mermaid
flowchart LR
    RT[AI Runtime / Scheduler]

    subgraph C2[C2 Data-centric Placement]
        DPM[Data Placement Manager]
        DR[Data Object Registry]
        DC[Data Characterizer]
        DSM[Data Runtime State Monitor]
        DPP[Data-aware Placement Planner]
        PLC[Placement Lifecycle Controller]
    end

    subgraph COMMON[Common Placement Services]
        CF[Candidate Memory Filter]
        CE[Cost / Utility Evaluator]
        EX[Placement Executor]
    end

    subgraph MA[Memory Resource Abstraction]
        MR[Memory Resource Registry]
        MD[Memory Descriptor / State]
    end

    subgraph ADAPT[Memory Resource Adapters]
        HBM[HBM Adapter]
        DRAM[DRAM Adapter]
        CXL[CXL Adapter]
        PIM[PIM / PNM Adapter]
    end

    RT -->|DataObjectEvent| DPM
    DPM --> DR
    DR --> DC
    DC --> DSM
    DSM -->|hotness / reuse / lifetime / locality| DPP
    DPP --> MR
    MR --> MD
    DPP --> CF
    CF --> CE
    CE -->|data × memory score| DPP
    DPP --> PLC
    PLC --> EX
    EX --> HBM
    EX --> DRAM
    EX --> CXL
    EX --> PIM
```

### C2 핵심 구조

**Data Object Registry → Data Characterizer → Data Runtime State → Data-aware Planner → Lifecycle Controller → Placement Executor**

## 4.2 C2 Class Diagram

```mermaid
classDiagram
    class DataPlacementManager {
        +onDataEvent(event: DataObjectEvent) PlacementDecision
        +reevaluate(objectId: ObjectId) PlacementDecision
    }

    class DataObjectRegistry {
        +register(data: DataObject)
        +get(objectId: ObjectId) DataObject
        +listActiveObjects() DataObject[]
    }

    class DataCharacterizer {
        +characterize(data: DataObject) DataDescriptor
        +update(objectId: ObjectId, observation: AccessObservation)
    }

    class DataRuntimeStateMonitor {
        +observe(objectId: ObjectId, access: AccessObservation)
        +getState(objectId: ObjectId) DataRuntimeState
    }

    class DataAwarePlacementPlanner {
        +plan(data: DataDescriptor, memories: MemoryResource[], state: SystemState) PlacementDecision
        +rank(data: DataDescriptor, memories: MemoryResource[]) PlacementScore[]
    }

    class PlacementLifecycleController {
        +handle(decision: PlacementDecision)
        +shouldReevaluate(state: DataRuntimeState) bool
    }

    class CandidateMemoryFilter {
        +filter(data: DataDescriptor, resources: MemoryResource[]) MemoryResource[]
    }

    class CostUtilityEvaluator {
        +evaluate(data: DataDescriptor, resource: MemoryResource, state: SystemState) PlacementScore
    }

    class PlacementExecutor {
        +execute(decision: PlacementDecision) ExecutionResult
    }

    class DataObject {
        +objectId: ObjectId
        +dataType: DataType
        +sizeBytes: long
        +currentTier: ResourceId
        +lifecycle: LifecycleState
    }

    class DataDescriptor {
        +objectId: ObjectId
        +dataType: DataType
        +sizeBytes: long
        +hotness: float
        +locality: Locality
        +lifetime: Duration
        +reuse: float
        +accessPattern: AccessPattern
        +readWriteIntensity: float
        +sharing: SharingMode
        +requiredOperations: Operation[]
    }

    class DataRuntimeState {
        +hotness: float
        +recentAccessRate: float
        +reuseRate: float
        +estimatedLifetime: Duration
        +lastAccess: Timestamp
        +currentTier: ResourceId
    }

    class DataObjectEvent {
        +type: EventType
        +objectId: ObjectId
        +timestamp: Timestamp
    }

    class AccessObservation {
        +timestamp: Timestamp
        +bytes: long
        +operation: Operation
        +latency: Duration
    }

    class MemoryResource {
        <<interface>>
        +descriptor() MemoryDescriptor
        +state() ResourceState
        +allocate(sizeBytes: long) AllocationHandle
        +release(handle: AllocationHandle)
    }

    class MemoryDescriptor {
        +memoryId: ResourceId
        +memoryType: MemoryType
        +capacityBytes: long
        +availableBytes: long
        +externalBandwidth: Bandwidth
        +internalBandwidth: Bandwidth
        +latency: Duration
        +computeCapability: ComputeCapability
        +accessPath: AccessPath
    }

    class SystemState
    class PlacementDecision
    class PlacementScore
    class ExecutionResult

    DataPlacementManager --> DataObjectRegistry : owns
    DataPlacementManager --> DataCharacterizer : invokes
    DataPlacementManager --> DataRuntimeStateMonitor : reads
    DataPlacementManager --> DataAwarePlacementPlanner : invokes
    DataPlacementManager --> PlacementLifecycleController : manages

    DataObjectRegistry o-- "1..*" DataObject : manages
    DataCharacterizer --> DataObject : observes
    DataCharacterizer --> DataDescriptor : produces
    DataRuntimeStateMonitor --> DataRuntimeState : updates
    DataRuntimeState --> DataObject : describes

    DataAwarePlacementPlanner --> CandidateMemoryFilter : filters
    DataAwarePlacementPlanner --> CostUtilityEvaluator : scores
    DataAwarePlacementPlanner --> PlacementDecision : creates
    CostUtilityEvaluator --> DataDescriptor : evaluates
    CostUtilityEvaluator --> MemoryResource : evaluates
    CostUtilityEvaluator --> SystemState : reads

    PlacementLifecycleController --> PlacementDecision : handles
    PlacementLifecycleController --> DataRuntimeState : monitors
    PlacementExecutor --> PlacementDecision : executes

    MemoryResource --> MemoryDescriptor : exposes
```

## 4.3 C2 Sequence — Initial Placement

```mermaid
sequenceDiagram
    autonumber
    participant RT as AI Runtime
    participant DPM as DataPlacementManager
    participant DR as DataObjectRegistry
    participant DC as DataCharacterizer
    participant DSM as DataRuntimeStateMonitor
    participant DPP as DataAwarePlanner
    participant CF as CandidateMemoryFilter
    participant CE as CostUtilityEvaluator
    participant PLC as LifecycleController
    participant EX as PlacementExecutor

    RT->>DPM: onDataEvent(Create / Admit)
    DPM->>DR: get(objectId)
    DR-->>DPM: DataObject
    DPM->>DC: characterize(DataObject)
    DC-->>DPM: DataDescriptor
    DPM->>DSM: getState(objectId)
    DSM-->>DPM: DataRuntimeState
    DPM->>DPP: plan(descriptor, memories, state)
    DPP->>CF: filter(descriptor, memories)
    CF-->>DPP: feasible memories
    DPP->>CE: evaluate(data, memory, systemState)
    CE-->>DPP: score(memory)
    DPP-->>DPM: PlacementDecision
    DPM->>PLC: handle(decision)
    PLC->>EX: execute(decision)
    EX-->>PLC: ExecutionResult
```

## 4.4 C2 Sequence — Runtime Re-evaluation

```mermaid
sequenceDiagram
    autonumber
    participant DATA as Runtime Data Access
    participant DSM as DataRuntimeStateMonitor
    participant PLC as PlacementLifecycleController
    participant DPP as DataAwarePlanner
    participant CE as CostUtilityEvaluator
    participant EX as PlacementExecutor
    participant DP4 as DP4 Migration Service

    DATA->>DSM: access observation
    DSM->>DSM: update hotness / reuse / lifetime
    DSM->>PLC: state changed
    PLC->>PLC: shouldReevaluate(state)

    alt re-evaluation required
        PLC->>DPP: reevaluate(data, state)
        DPP->>CE: recompute data × memory cost
        CE-->>DPP: updated scores
        DPP-->>PLC: PlacementDecision

        alt destination differs
            PLC->>EX: execute(decision)
            EX->>DP4: migrate(source, destination, object)
            DP4-->>EX: migration result
        else keep current tier
            PLC-->>DATA: keep placement
        end
    else threshold not crossed
        PLC-->>DATA: keep placement
    end
```

# 5. C1 vs C2 Structural View

```mermaid
flowchart TB
    subgraph C1[C1 Memory-centric]
        C1R[Memory Resource]
        C1RR[Resource Registry]
        C1S[Resource State]
        C1P[Resource-aware Planner]
        C1D[Data Allocation]
        C1R --> C1RR --> C1S --> C1P --> C1D
    end

    subgraph C2[C2 Data-centric]
        C2D[Data Object]
        C2RR[Data Registry]
        C2C[Data Characterization]
        C2S[Data Runtime State]
        C2P[Data-aware Planner]
        C2T[Tier Selection]
        C2D --> C2RR --> C2C --> C2S --> C2P --> C2T
    end

    C1D --- COMMON[Common Services: Feasibility / Cost / Executor]
    C2T --- COMMON
```

| 항목 | C1 Memory-centric | C2 Data-centric |
|---|---|---|
| Primary Object | Memory Resource | Data Object |
| Primary Registry | Resource Registry | Data Object Registry |
| Runtime State Owner | Resource State | Data Runtime State |
| Characterization | Minimal / support info | Hotness / Reuse / Lifetime / Locality |
| Core Planner | Resource-aware Planner | Data-aware Planner |
| Decision Granularity | Resource 중심 | Data Object 중심 |
| Extension Axis | New Memory Type | New Data Type / Characterizer |

# 6. Data Type Characterization Extension

```mermaid
flowchart LR
    subgraph DT[AI Runtime Data Types]
        KV[KV Cache]
        RAG[RAG Data]
        AM[Agent Memory / State]
        TR[Tool Result]
        LORA[LoRA Adapter]
        MOE[MoE Expert]
    end

    subgraph CHAR[Data Characterization]
        KVC[KV Characterizer]
        RAGC[RAG Characterizer]
        AMC[Agent Memory Characterizer]
        TRC[Tool Result Characterizer]
        LC[LoRA Characterizer]
        MOEC[MoE Characterizer]
    end

    DESC[Common DataDescriptor]

    KV --> KVC
    RAG --> RAGC
    AM --> AMC
    TR --> TRC
    LORA --> LC
    MOE --> MOEC

    KVC --> DESC
    RAGC --> DESC
    AMC --> DESC
    TRC --> DESC
    LC --> DESC
    MOEC --> DESC
```

| Logical Data Type | Physical Representation 예 | Placement Unit |
|---|---|---|
| KV Cache | KV Block | Block / Session Block Set |
| RAG Data | Document / Chunk / Embedding / Index Partition | Chunk / Index Partition |
| Agent Memory | Serialized Record / Structured State / KV Record | Memory Entry / Session Group |
| Tool Result | Serialized Result / Object / KV Record | Result Object / Session State |
| LoRA Adapter | Adapter Weight Object | Adapter |
| MoE Expert | Expert Weight Object | Expert |

# 7. Common Placement Interface

```mermaid
classDiagram
    class PlacementPolicy {
        <<interface>>
        +plan(input: PlacementInput) PlacementDecision
    }

    class C1ResourceAwarePolicy {
        +plan(input: PlacementInput) PlacementDecision
    }

    class C2DataAwarePolicy {
        +plan(input: PlacementInput) PlacementDecision
    }

    class PlacementInput {
        +data: DataDescriptor
        +memories: MemoryResource[]
        +systemState: SystemState
    }

    class PlacementDecision {
        +sourceTier: ResourceId
        +destinationTier: ResourceId
        +estimatedCost: Cost
        +reason: String
    }

    PlacementPolicy <|.. C1ResourceAwarePolicy
    PlacementPolicy <|.. C2DataAwarePolicy
    C1ResourceAwarePolicy --> PlacementInput
    C2DataAwarePolicy --> PlacementInput
    C1ResourceAwarePolicy --> PlacementDecision
    C2DataAwarePolicy --> PlacementDecision
```

# 8. DP Boundary

```mermaid
flowchart LR
    DP1[DP1
AI Data Placement]
    DP2[DP2
Prefill Compute Placement]
    DP3[DP3
Data Eviction]
    DP4[DP4
Data Migration]

    DP1 -->|Which Memory Tier?| DP3
    DP1 -->|PlacementDecision / destination| DP4
    DP2 -->|Compute location independent decision| DP1
```

> **Boundary:** DP1 answers **Data → Memory Tier**, DP2 answers **Prefill → Compute Resource**, DP3 answers **What Data should be removed?**, DP4 answers **How should Data be moved?**

# 9. UML → Architecture 재구성 포인트

UML에서 Architecture 문서로 다시 그릴 때는 단순 module list가 아니라 다음 구조가 보이도록 한다.

- C1: `Memory Resource Manager`가 중심에 있고 `Resource Registry / State Monitor / Resource-aware Planner`가 그 내부 핵심으로 배치된다.
- C2: `Data Placement Manager`가 중심에 있고 `Data Registry / Characterizer / Data Runtime State / Data-aware Planner`가 그 내부 핵심으로 배치된다.
- 두 후보 모두 아래 공통 계층을 공유한다.
  - Candidate Memory Filtering
  - Cost / Utility Evaluation
  - Memory Resource Abstraction
  - Placement Executor
- `Compute Capability`는 DP1의 Memory Descriptor/Feasibility 입력으로 표현하되, Prefill의 Compute Placement는 DP2로 분리한다.
