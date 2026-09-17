# DP1. AI Data Placement UML Design — Rendered

> **문서 유형:** UML / Implementation Design
>
> 본 문서는 `dp1-data-placement-design.md`의 C1/C2 구조를 UML 관점에서 표현한다.
>
> - **C1:** Resource State 기반 Memory-centric Placement
> - **C2:** Data Characteristic 기반 Data-centric Placement

---

# 1. Design Principle

C1과 C2의 차이는 Monitor 이름만 다른 것이 아니라 **무엇을 관찰하고 무엇을 예측하여 Placement의 1차 기준으로 삼는가**에 있다.

```text
C1
Telemetry → Resource State Monitor
          → Resource trend / prediction
          → Memory State View
          → Resource-aware Placement

C2
Data Descriptor → Data Classifier
Runtime History → Runtime State Monitor
               → Data Characteristic Interpreter
               → Tier Affinity
Telemetry ─────→ Memory Tier Selector
```

---

# 2. Common External Components

```mermaid
flowchart LR
    SCH[Scheduler / Request Manager]
    DDA[Data Descriptor Adapter]
    TC[Telemetry Collector]
    MR[Memory Registry]
    EX[Placement Executor]

    SCH -->|Allocation Request| DDA
    TC -->|real-time HW state| C1[C1 Memory-centric]
    TC -->|real-time HW state| C2[C2 Data-centric]
    MR -->|static memory capability| C1
    MR -->|static memory capability| C2
    DDA --> C1
    DDA --> C2
    C1 --> EX
    C2 --> EX
```

### Common Component Responsibility

| Component | Responsibility |
|---|---|
| Scheduler / Request Manager | Placement 요청 발생 |
| Data Descriptor Adapter | Data-specific 정보를 공통 Descriptor로 변환 |
| Telemetry Collector | Memory/HW의 실시간 상태 수집 |
| Memory Registry | Capacity, BW, latency, operation support 등 정적/준정적 정보 보관 |
| Placement Executor | 결정된 destination tier에 실제 allocation/place 수행 |

---

# 3. C1 — Memory-centric Placement

## 3.1 Module View

```mermaid
flowchart LR
    SCH[Scheduler]
    DDA[Data Descriptor Adapter]
    TC[Telemetry Collector]
    MR[Memory Registry]

    subgraph MRM[Memory Resource Manager]
        RSM[Resource State Monitor]
        CB[Candidate Builder]
    end

    MSV[Memory State View]
    RPP[Resource-aware Placement Planner]
    MTS[Memory Tier Selector]
    EX[Placement Executor]

    SCH -->|Allocation Request| DDA
    DDA -->|Data Descriptor / constraints| RPP

    TC -->|capacity / BW util / load / pressure / latency| RSM
    RSM -->|current state + trend + predicted state| CB
    MR -->|static Memory Descriptor| CB

    CB -->|candidate resources| MSV
    MSV --> RPP
    RPP -->|ranked resource candidates| MTS
    MTS -->|selected tier| EX
```

### 핵심 구조

```text
Telemetry Collector
      ↓
Resource State Monitor
      ↓
Current / Trend / Predicted Resource State
      +
Memory Registry
      ↓
Candidate Builder
      ↓
Memory State View
      ↓
Resource-aware Placement Planner
      ↓
Memory Tier Selector
```

## 3.2 C1 Class Diagram

```mermaid
classDiagram
    class MemoryResourceManager {
        +allocate(request: AllocationRequest) PlacementDecision
        +reevaluate(trigger: ResourceEvent) PlacementDecision[]
    }

    class ResourceStateMonitor {
        +observe(sample: TelemetrySample)
        +getCurrentState(resourceId: ResourceId) ResourceState
        +getTrend(resourceId: ResourceId) ResourceTrend
        +predict(resourceId: ResourceId, horizon: Duration) PredictedResourceState
    }

    class CandidateBuilder {
        +build(registry: MemoryRegistry, states: ResourceState[]) MemoryStateView
    }

    class MemoryRegistry {
        +get(resourceId: ResourceId) MemoryDescriptor
        +list() MemoryDescriptor[]
    }

    class MemoryStateView {
        +candidates: MemoryCandidate[]
        +timestamp: Timestamp
        +validUntil: Timestamp
    }

    class MemoryCandidate {
        +resourceId: ResourceId
        +descriptor: MemoryDescriptor
        +currentState: ResourceState
        +predictedState: PredictedResourceState
        +available: bool
    }

    class ResourceAwarePlacementPlanner {
        +plan(request: AllocationRequest, view: MemoryStateView) PlacementPlan
        +rank(view: MemoryStateView, constraints: PlacementConstraint) MemoryCandidate[]
    }

    class MemoryTierSelector {
        +select(plan: PlacementPlan) ResourceId
    }

    class PlacementExecutor {
        +execute(decision: PlacementDecision) ExecutionResult
    }

    class TelemetryCollector {
        +collect() TelemetrySample[]
    }

    class TelemetrySample {
        +resourceId: ResourceId
        +availableCapacity: long
        +bandwidthUtilization: float
        +load: float
        +pressure: float
        +latency: Duration
        +timestamp: Timestamp
    }

    class ResourceState {
        +availableCapacity: long
        +bandwidthUtilization: float
        +load: float
        +pressure: float
        +contention: float
    }

    class ResourceTrend {
        +capacitySlope: float
        +bandwidthSlope: float
        +pressureSlope: float
    }

    class PredictedResourceState {
        +predictedPressure: float
        +predictedBandwidthUtilization: float
        +predictedAvailableCapacity: long
        +confidence: float
    }

    class MemoryDescriptor {
        +memoryId: ResourceId
        +memoryType: MemoryType
        +capacityBytes: long
        +externalBandwidth: Bandwidth
        +internalBandwidth: Bandwidth
        +latency: Duration
        +supportedOperations: Operation[]
        +computeCapability: ComputeCapability
    }

    class AllocationRequest
    class PlacementConstraint
    class PlacementPlan
    class PlacementDecision
    class ExecutionResult

    MemoryResourceManager --> ResourceStateMonitor : owns
    MemoryResourceManager --> CandidateBuilder : owns
    MemoryResourceManager --> ResourceAwarePlacementPlanner : invokes
    MemoryResourceManager --> MemoryTierSelector : invokes

    TelemetryCollector --> ResourceStateMonitor : feeds samples
    ResourceStateMonitor --> ResourceState : produces
    ResourceStateMonitor --> ResourceTrend : derives
    ResourceStateMonitor --> PredictedResourceState : predicts

    CandidateBuilder --> MemoryRegistry : reads static capability
    CandidateBuilder --> ResourceState : reads current state
    CandidateBuilder --> PredictedResourceState : reads prediction
    CandidateBuilder --> MemoryStateView : creates
    MemoryStateView o-- "1..*" MemoryCandidate

    ResourceAwarePlacementPlanner --> MemoryStateView : evaluates
    ResourceAwarePlacementPlanner --> PlacementPlan : creates
    MemoryTierSelector --> PlacementPlan : selects from
    MemoryTierSelector --> PlacementDecision : creates
    PlacementExecutor --> PlacementDecision : executes
```

## 3.3 C1 Sequence — Initial Placement

```mermaid
sequenceDiagram
    autonumber
    participant SCH as Scheduler
    participant DDA as DataDescriptorAdapter
    participant MRM as MemoryResourceManager
    participant TC as TelemetryCollector
    participant RSM as ResourceStateMonitor
    participant MR as MemoryRegistry
    participant CB as CandidateBuilder
    participant RPP as ResourceAwarePlanner
    participant MTS as MemoryTierSelector
    participant EX as PlacementExecutor

    SCH->>DDA: allocationRequest(data)
    DDA-->>MRM: DataDescriptor + constraints

    MRM->>TC: request latest telemetry
    TC-->>RSM: resource samples
    RSM->>RSM: update current state
    RSM->>RSM: analyze trend
    RSM->>RSM: predict near-future resource state

    MRM->>MR: list memory descriptors
    MR-->>CB: static memory capability
    RSM-->>CB: current + predicted resource state
    CB->>CB: build candidate resources
    CB-->>RPP: MemoryStateView

    MRM->>RPP: plan(request, MemoryStateView)
    RPP->>RPP: evaluate capacity / BW / latency / pressure / capability
    RPP-->>MTS: ranked resource candidates
    MTS-->>MRM: selected Memory Tier

    MRM->>EX: execute PlacementDecision
    EX-->>SCH: PlacementResult
```

## 3.4 C1 Sequence — Resource State Change / Re-placement

```mermaid
sequenceDiagram
    autonumber
    participant TC as TelemetryCollector
    participant RSM as ResourceStateMonitor
    participant MRM as MemoryResourceManager
    participant CB as CandidateBuilder
    participant RPP as ResourceAwarePlanner
    participant EX as PlacementExecutor
    participant DP4 as DP4 Migration Service

    TC-->>RSM: new telemetry sample
    RSM->>RSM: update state / trend / prediction

    alt significant pressure or predicted saturation
        RSM-->>MRM: ResourceStateChange event
        MRM->>CB: rebuild MemoryStateView
        CB-->>RPP: updated MemoryStateView
        RPP-->>MRM: new PlacementDecision

        alt destination tier changed
            MRM->>EX: execute(decision)
            EX->>DP4: migrate(object, source, destination)
            DP4-->>EX: migration result
        else current tier remains valid
            MRM->>MRM: keep placement
        end
    end
```

---

# 4. C2 — Data-centric Placement

## 4.1 Module View

```mermaid
flowchart LR
    SCH[Scheduler]
    DDA[Data Descriptor Adapter]
    TC[Telemetry Collector]
    MR[Memory Registry]

    subgraph DPM[Data Placement Manager]
        DC[Data Classifier]
        RSM[Runtime State Monitor]
        DCI[Data Characteristic Interpreter]
    end

    DPP[Data-aware Placement Planner]
    MAE[Memory Tier Affinity Evaluator]
    MTS[Memory Tier Selector]
    EX[Placement Executor]

    SCH -->|Allocation Request| DDA
    DDA -->|Data Descriptor| DC
    DDA -->|object/class identity| RSM

    DC -->|Data Class| DCI
    RSM -->|runtime stats / history / trend| DCI
    DCI -->|Data Characteristics| DPP

    DPP --> MAE
    MR -->|static memory capability| MAE
    MAE -->|Affinity Tier Set| MTS
    TC -->|real-time resource state| MTS
    MR -->|tier metadata| MTS

    MTS -->|Best Tier| EX
```

### 핵심 구조

```text
Data Descriptor
      ↓
Data Classifier ───────────────┐
                               │
Runtime State Monitor ─────────┤
                               ▼
                 Data Characteristic Interpreter
                               ↓
                  Predicted Data Characteristics
                               ↓
                   Memory Tier Affinity Evaluator
                               ↓
                        Affinity Tier Set
                               +
                    Real-time Telemetry
                               ↓
                     Memory Tier Selector
                               ↓
                           Best Tier
```

## 4.2 C2 Class Diagram

```mermaid
classDiagram
    class DataPlacementManager {
        +place(request: AllocationRequest) PlacementDecision
        +observe(event: DataRuntimeEvent)
        +reevaluate(objectId: ObjectId) PlacementDecision
    }

    class DataClassifier {
        +classify(descriptor: DataDescriptor) DataClass
    }

    class RuntimeStateMonitor {
        +observe(event: DataRuntimeEvent)
        +getStats(key: DataClassKey) DataRuntimeStats
        +getHistory(key: DataClassKey) DataRuntimeHistory
    }

    class DataCharacteristicInterpreter {
        +interpret(dataClass: DataClass, stats: DataRuntimeStats) DataCharacteristics
        +predict(dataClass: DataClass, stats: DataRuntimeStats) DataCharacteristics
    }

    class DataAwarePlacementPlanner {
        +plan(characteristics: DataCharacteristics) PlacementPlan
    }

    class MemoryTierAffinityEvaluator {
        +evaluate(data: DataCharacteristics, memories: MemoryDescriptor[]) TierAffinity[]
    }

    class MemoryTierSelector {
        +select(affinity: TierAffinity[], telemetry: ResourceTelemetry[]) ResourceId
    }

    class DataDescriptor {
        +objectId: ObjectId
        +typeHint: DataTypeHint
        +sizeBytes: long
        +owner: OwnerId
        +currentTier: ResourceId
        +requiredOperations: Operation[]
    }

    class DataClass {
        <<enumeration>>
        KV_CACHE
        RAG_DATA
        AGENT_MEMORY
        TOOL_RESULT
        LOG_DATA
        LORA_ADAPTER
        MOE_EXPERT
    }

    class DataRuntimeEvent {
        +objectId: ObjectId
        +dataClass: DataClass
        +operation: Operation
        +bytes: long
        +timestamp: Timestamp
    }

    class DataRuntimeStats {
        +accessFrequency: float
        +reuseInterval: Duration
        +readWriteRatio: float
        +lifetimeEstimate: Duration
        +localityScore: float
        +sharingDegree: float
    }

    class DataRuntimeHistory {
        +samples: RuntimeSample[]
        +observationWindow: Duration
    }

    class DataCharacteristics {
        +predictedHotness: float
        +predictedLifetime: Duration
        +predictedReuse: float
        +locality: float
        +accessPattern: AccessPattern
        +readWriteIntensity: float
        +sharing: float
        +requiredOperations: Operation[]
    }

    class TierAffinity {
        +resourceId: ResourceId
        +affinityScore: float
        +eligible: bool
        +reason: String
    }

    class MemoryRegistry {
        +list() MemoryDescriptor[]
    }

    class MemoryDescriptor {
        +memoryId: ResourceId
        +memoryType: MemoryType
        +capacityBytes: long
        +bandwidth: Bandwidth
        +latency: Duration
        +supportedOperations: Operation[]
        +computeCapability: ComputeCapability
    }

    class TelemetryCollector {
        +collect() ResourceTelemetry[]
    }

    class ResourceTelemetry {
        +resourceId: ResourceId
        +availableCapacity: long
        +bandwidthUtilization: float
        +pressure: float
        +contention: float
        +latencyState: Duration
    }

    class PlacementPlan
    class PlacementDecision
    class PlacementExecutor
    class AllocationRequest

    DataPlacementManager --> DataClassifier : invokes
    DataPlacementManager --> RuntimeStateMonitor : reads / updates
    DataPlacementManager --> DataCharacteristicInterpreter : invokes
    DataPlacementManager --> DataAwarePlacementPlanner : invokes

    DataClassifier --> DataDescriptor : consumes
    DataClassifier --> DataClass : produces

    RuntimeStateMonitor --> DataRuntimeEvent : observes
    RuntimeStateMonitor --> DataRuntimeStats : accumulates
    RuntimeStateMonitor --> DataRuntimeHistory : maintains

    DataCharacteristicInterpreter --> DataClass : reads
    DataCharacteristicInterpreter --> DataRuntimeStats : reads
    DataCharacteristicInterpreter --> DataCharacteristics : produces

    DataAwarePlacementPlanner --> MemoryTierAffinityEvaluator : invokes
    MemoryTierAffinityEvaluator --> MemoryRegistry : reads
    MemoryTierAffinityEvaluator --> DataCharacteristics : evaluates
    MemoryTierAffinityEvaluator --> TierAffinity : produces

    MemoryTierSelector --> TierAffinity : selects from
    TelemetryCollector --> MemoryTierSelector : feeds realtime state
    MemoryTierSelector --> PlacementDecision : creates
    PlacementExecutor --> PlacementDecision : executes
```

## 4.3 C2 Sequence — Initial Placement

초기 배치에서는 충분한 Runtime History가 없을 수 있으므로 **Data Class prior/default profile**을 사용한다.

```mermaid
sequenceDiagram
    autonumber
    participant SCH as Scheduler
    participant DDA as DataDescriptorAdapter
    participant DPM as DataPlacementManager
    participant DC as DataClassifier
    participant RSM as RuntimeStateMonitor
    participant DCI as DataCharacteristicInterpreter
    participant MR as MemoryRegistry
    participant MAE as TierAffinityEvaluator
    participant TC as TelemetryCollector
    participant MTS as MemoryTierSelector
    participant EX as PlacementExecutor

    SCH->>DDA: allocationRequest(data)
    DDA-->>DPM: DataDescriptor

    DPM->>DC: classify(DataDescriptor)
    DC-->>DPM: DataClass

    DPM->>RSM: getStats(DataClass / ObjectGroup)

    alt sufficient runtime history exists
        RSM-->>DPM: observed runtime statistics
    else cold-start / first placement
        RSM-->>DPM: insufficient history
        DPM->>DCI: use DataClass prior/default profile
    end

    DPM->>DCI: interpret(DataClass, runtime stats)
    DCI->>DCI: predict hotness / lifetime / reuse / locality
    DCI-->>DPM: DataCharacteristics

    DPM->>MR: list memory descriptors
    MR-->>MAE: static Memory Tier capability
    DPM->>MAE: evaluate(DataCharacteristics)
    MAE->>MAE: calculate tier affinity
    MAE-->>MTS: Affinity Tier Set

    MTS->>TC: request latest resource state
    TC-->>MTS: real-time Memory telemetry
    MTS->>MTS: combine affinity + resource availability
    MTS-->>DPM: Best Tier

    DPM->>EX: execute PlacementDecision
    EX-->>SCH: PlacementResult
```

## 4.4 C2 Sequence — Runtime Learning / Re-placement

```mermaid
sequenceDiagram
    autonumber
    participant RT as AI Runtime
    participant DPM as DataPlacementManager
    participant RSM as RuntimeStateMonitor
    participant DCI as DataCharacteristicInterpreter
    participant MAE as TierAffinityEvaluator
    participant TC as TelemetryCollector
    participant MTS as MemoryTierSelector
    participant EX as PlacementExecutor
    participant DP4 as DP4 Migration Service

    RT-->>RSM: DataRuntimeEvent(access / reuse / idle / release)
    RSM->>RSM: accumulate class/object behavior stats

    alt characteristic change exceeds threshold
        RSM-->>DPM: reevaluation trigger
        DPM->>DCI: recompute characteristics
        DCI-->>DPM: updated hotness / lifetime / reuse / locality

        DPM->>MAE: reevaluate tier affinity
        MAE-->>MTS: updated Affinity Tier Set

        MTS->>TC: get current resource telemetry
        TC-->>MTS: pressure / BW / capacity / contention
        MTS-->>DPM: Best Tier

        alt Best Tier differs from current tier
            DPM->>EX: execute PlacementDecision
            EX->>DP4: migrate(object, source, destination)
            DP4-->>EX: migration result
        else keep current placement
            DPM->>DPM: no migration
        end
    end
```

---

# 5. C1 vs C2 Monitor Difference

```mermaid
flowchart TB
    subgraph C1[C1 Resource-centric Monitoring]
        TC1[Telemetry Collector]
        RSM1[Resource State Monitor]
        P1[Resource State Prediction]
        V1[Memory State View]

        TC1 --> RSM1 --> P1 --> V1
    end

    subgraph C2[C2 Data-centric Monitoring]
        DC2[Data Classifier]
        RSM2[Runtime State Monitor]
        DCI2[Data Characteristic Interpreter]
        CH2[Predicted Data Characteristics]

        DC2 --> DCI2
        RSM2 --> DCI2 --> CH2
    end
```

| 항목 | C1 Resource State Monitor | C2 Runtime State Monitor |
|---|---|---|
| 관찰 대상 | Memory/HW Resource | Data Class / Object behavior |
| 원천 정보 | Telemetry Collector | Runtime access/history event |
| 축적 정보 | Capacity, BW, load, pressure, contention | Access frequency, reuse, lifetime, locality, R/W pattern |
| Prediction | Resource가 앞으로 얼마나 바빠질지 | Data가 앞으로 얼마나 hot/long-lived/reused될지 |
| 출력 사용처 | Candidate Builder / Memory State View | Data Characteristic Interpreter |
| Placement에서의 의미 | Resource 자체의 적합성 판단 | Data의 요구 특성 생성 |

---

# 6. C1 vs C2 Final Decision Flow

```mermaid
flowchart LR
    subgraph C1[C1 Memory-centric]
        T1[Telemetry]
        R1[Resource State Monitor]
        B1[Candidate Builder]
        V1[Memory State View]
        P1[Resource-aware Planner]
        S1[Best Tier]

        T1 --> R1 --> B1 --> V1 --> P1 --> S1
    end

    subgraph C2[C2 Data-centric]
        D2[Data Descriptor]
        C2C[Data Classifier]
        R2[Runtime State Monitor]
        I2[Data Characteristic Interpreter]
        A2[Tier Affinity Evaluator]
        T2[Telemetry]
        S2[Memory Tier Selector]
        B2[Best Tier]

        D2 --> C2C --> I2
        R2 --> I2
        I2 --> A2 --> S2 --> B2
        T2 --> S2
    end
```

---

# 7. DP Boundary

- **DP1:** Data Placement 결정
- **DP2:** Prefill / Compute Placement
- **DP3:** Data Eviction 결정
- **DP4:** 실제 Data Migration 수행

DP1은 destination Memory Tier를 결정하고, 기존 위치와 destination이 다를 경우 실제 Data 이동은 DP4 Migration Service에 위임한다.
