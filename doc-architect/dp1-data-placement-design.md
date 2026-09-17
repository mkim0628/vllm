# DP1. AI Data Placement 설계

> **문서 유형:** Design Specification
>
> 본 문서는 DP1의 **Data Placement 설계 구조만 구체화**한다. 기존 `dp1-heterogeneous-memory-data-placement.md`는 Design Point의 배경, 대상 Memory Configuration, 평가 방법, 시뮬레이션 및 검증 결과를 포함하며, 해당 문서의 내용을 반복하지 않는다.
>
> - 상위 DP 정의 / 배경 / Memory Configuration / Evaluation: `dp1-heterogeneous-memory-data-placement.md`
> - 본 문서: **Data Placement Architecture / Data Abstraction / Candidate 구조 / Decision Flow / Interface / DP 경계**

---

## 1. Design Scope

### 1.1 목적

이기종 메모리 환경에서 AI Runtime이 관리하는 Data Object를 어떤 Memory Tier에 배치할 것인지 결정하는 **Data Placement 구조**를 정의한다.

본 DP의 Placement 대상은 Runtime 동안 생성·관리되며 workload 또는 system state에 따라 위치를 변경할 실질적인 가치가 있는 **AI Runtime Data**이다.

대표 대상:

- **KV Cache**
- **RAG Data**: Document / Chunk / Embedding / Retrieval Index
- **Agent Memory / State**
- **Tool Result / Agent State**
- **LoRA Adapter**
- **MoE Expert**

일반적인 Dense Model Weight 및 일반적인 short-lived Activation은 기본 대상에서 제외한다.

### 1.2 DP1의 핵심 질문

> **Memory Resource를 중심으로 Data를 배치할 것인가, Data Object의 특성을 중심으로 Memory Tier를 선택할 것인가?**

```text
                     DP1
          AI Data Placement
                    │
           ┌────────┴────────┐
           ▼                 ▼
          C1                 C2
   Memory-centric       Data-centric
      Placement            Placement
```

---

## 2. Terminology

### 2.1 AI Runtime Data

AI Runtime Data는 **Runtime에 의해 생성·관리되며, workload 및 system state에 따라 Memory Placement를 동적으로 결정하거나 재평가할 수 있는 Data Object**를 의미한다.

### 2.2 Data Object

Placement의 최소 논리 단위이다. Data Type마다 실제 물리적 구조는 다를 수 있으나 Placement Controller에는 공통 Descriptor를 제공한다.

```text
Data Object
├── Identity
├── Type
├── Size
├── Current Placement
├── Data Characteristics
├── Access Requirements
└── Lifecycle State
```

### 2.3 Memory Tier

Data Object를 저장하거나, 지원되는 경우 해당 Data를 대상으로 일부 연산을 수행할 수 있는 Memory Resource이다.

```text
Memory Tier
├── Identity
├── Capacity
├── Access Bandwidth
├── Latency
├── Compute Capability
├── Access Path
├── Current Utilization
└── Cost / Constraint
```

---

## 3. AI Data Abstraction

### 3.1 Logical Data Type과 Physical Representation의 분리

Data Type은 논리적인 용도를 나타내고, Physical Representation은 실제 Runtime에서 관리되는 자료구조를 나타낸다.

| Logical Data Type | Physical Representation 예 | Placement Unit |
|---|---|---|
| **KV Cache** | KV Block | Block / Session Block Set |
| **RAG Data** | Document / Chunk / Embedding / Index Partition | Chunk / Index Partition |
| **Agent Memory** | Serialized Record / Structured State / KV Record | Memory Entry / Session Group |
| **Tool Result** | Serialized Result / Object / KV Record | Result Object / Session State |
| **LoRA Adapter** | Adapter Weight Object | Adapter |
| **MoE Expert** | Expert Weight Object | Expert |

> Physical Representation은 Data Type에 따라 달라질 수 있지만, Placement Policy가 직접 Data-specific 자료구조를 해석하지 않도록 **공통 Data Descriptor 계층으로 추상화**한다.

### 3.2 Agent Memory

Agent Memory는 하나의 고정 자료구조가 아니라, Agent가 이후 Step/Turn에서 재사용하기 위해 보존하는 **Persistent State/Data의 논리적 범주**이다.

```text
Agent Memory
├── Conversation / Episodic Memory
│   └── Serialized Record / Document / KV Record
├── Semantic Memory
│   └── Structured Record (+ optional Embedding)
└── Task / Working State
    └── Structured State / Object / KV Record
```

실제 Placement 실험에서는 하나의 Physical Representation을 선택하여 고정한다.

예:

```text
Agent Memory
        ↓
Serialized Record
        ↓
Memory Object
        ↓
Placement Unit
```

### 3.3 Common Data Descriptor

모든 Data Type은 Placement Controller에 다음 공통 정보를 제공한다.

```text
DataDescriptor
├── object_id
├── data_type
├── size_bytes
├── owner / session
├── current_tier
├── hotness
├── locality
├── lifetime
├── reuse
├── access_pattern
├── read_write_intensity
├── sharing
└── required_operations
```

모든 필드가 모든 Data Type에 동일하게 채워질 필요는 없다.

예:

```text
KV Cache
→ hotness / lifetime / reuse / attention access

RAG Data
→ retrieval frequency / query locality / read intensity

Agent Memory
→ session locality / lifetime / reuse
```

Data-specific 정보는 **Adapter / Characterizer**가 공통 Descriptor로 변환한다.

---

## 4. Memory Abstraction

### 4.1 Memory Descriptor

Placement Policy는 Memory 자체의 상세 구현이 아니라 공통 Memory Descriptor를 사용한다.

```text
MemoryDescriptor
├── memory_id
├── memory_type
├── capacity_bytes
├── available_bytes
├── external_bandwidth
├── internal_bandwidth
├── latency
├── compute_capability
│   ├── supported_operations
│   ├── compute_throughput
│   └── compute_efficiency
├── access_path
├── current_load
├── bandwidth_utilization
└── write_cost / endurance
```

`Compute Capability`는 PIM/PNM 등 **Memory 자체에서 수행할 수 있는 연산 능력**을 표현한다. 예를 들어 특정 reduction, vector operation, search/filter 등의 지원 여부와 처리 성능을 나타낼 수 있다.

> Memory Compute Capability를 Placement 입력으로 사용하는 것은 **어느 Memory에 Data를 둘 것인가**를 판단하기 위한 것이다. 어떤 Compute Resource에서 Prefill을 수행할 것인가는 DP2에서 결정한다.

### 4.2 System State

Memory Descriptor가 정적인 Resource 특성을 표현한다면, System State는 Runtime 시점의 동적인 상태를 표현한다.

```text
SystemState
├── memory_pressure
├── tier_utilization
├── bandwidth_utilization
├── request_load
├── access_contention
├── active_data_population
├── QoS / latency state
└── runtime_policy_state
```

### 4.3 Access Path

Memory의 raw bandwidth와 실제 Data access cost를 구분한다.

```text
Data
  │
  ▼
Access Path
  │
  ├── Hop count
  ├── Link bandwidth
  ├── Link latency
  └── Contention
  │
  ▼
Effective Access Cost
```

따라서 Placement는 단순히 `Memory Bandwidth`가 높은 Tier를 선택하지 않는다.

```text
Effective Cost
≈ f(Data Access Pattern,
    Path Bandwidth,
    Path Latency,
    Contention,
    Memory State)
```

---

## 5. Placement Decision Model

### 5.1 전체 Decision Pipeline

Placement Decision은 **Data 특성, Memory Resource 특성, Runtime System State**를 통합하여 Placement Policy를 적용하고, 그 결과로 후보 Memory를 필터링한 뒤 비용/효용을 비교하여 최종 Tier를 선택한다.

```text
┌─────────────────┐
│ Data Descriptor │
└────────┬────────┘
         │
         │
┌────────▼────────┐       ┌─────────────────┐
│ Memory Descriptor│       │   System State  │
└────────┬────────┘       └────────┬────────┘
         │                         │
         └────────────┬────────────┘
                      ▼
             ┌──────────────────┐
             │  Placement Policy│
             │     Selection    │
             │                  │
             │ C1 Memory-centric│
             │ C2 Data-centric  │
             └────────┬─────────┘
                      │
                      ▼
             ┌──────────────────┐
             │ Candidate Memory │
             │    Filtering     │
             └────────┬─────────┘
                      │
          ┌───────────┼───────────┐
          ▼           ▼           ▼
      Capacity     Operation   Reachability
       Check         Check        Check
          │           │           │
          └───────────┼───────────┘
                      ▼
             ┌──────────────────┐
             │ Candidate Memory │
             │       Set        │
             └────────┬─────────┘
                      ▼
             ┌──────────────────┐
             │ Cost / Utility   │
             │    Evaluation    │
             └────────┬─────────┘
                      ▼
             ┌──────────────────┐
             │   Tier Selection │
             └────────┬─────────┘
                      ▼
             ┌──────────────────┐
             │Placement Decision│
             └────────┬─────────┘
                      ▼
             ┌──────────────────┐
             │Placement Executor│
             └──────────────────┘
```

이 구조에서 **C1/C2는 전체 Pipeline을 대체하는 별도 시스템이 아니라 `Placement Policy`의 1차 Decision Logic을 구성하는 후보 구조**이다. Candidate Filtering, Cost Model, Executor는 원칙적으로 공통 Infrastructure로 유지한다.

### 5.2 Placement Policy

Placement Policy는 입력된 Data Descriptor, Memory Descriptor, System State를 바탕으로 **현재 Placement Decision에 적용할 의사결정 전략과 파라미터를 결정하는 계층**이다.

```text
Data Descriptor
      +
Memory Descriptor
      +
System State
      │
      ▼
Placement Policy
      │
      ├── C1: Memory-centric
      └── C2: Data-centric
```

실제 구현에서는 C1/C2 중 하나를 고정된 Policy로 사용할 수도 있고, 실험 목적에 따라 동일 입력에 대해 두 Policy를 교체하여 비교할 수 있다.

### 5.3 Candidate Memory Filtering

Policy 적용 후 모든 Memory Tier를 대상으로 **실제로 배치 가능한 후보 집합**을 구성한다.

```text
All Memory Tiers
       │
       ▼
┌─────────────────────┐
│ Feasibility Filter  │
├─────────────────────┤
│ Capacity            │
│ Supported Operation │
│ Reachability        │
│ QoS / Latency       │
│ Endurance / Constraint│
└──────────┬──────────┘
           ▼
Candidate Memory Set
```

Feasibility 조건 예:

- Data Size가 Memory의 Available Capacity 이하인가?
- `required_operations`를 해당 Memory가 지원하는가?
- Access Path가 Runtime에서 허용되는가?
- 해당 Data의 QoS / latency requirement를 만족할 수 있는가?
- Write Endurance 등 Memory-specific constraint를 위반하지 않는가?

특히 **Memory Compute Capability는 Operation Feasibility의 핵심 입력**이다.

예:

```text
Data.required_operations = {search, reduction}
                  │
                  ▼
      Memory Compute Capability
                  │
        ┌─────────┴─────────┐
        ▼                   ▼
   PNM: supported       DRAM: unsupported
        │                   │
        ▼                   ▼
    Candidate             Filtered out
```

### 5.4 Cost / Utility Calculation

Feasible Memory에 대해서만 Placement Cost 또는 Utility를 계산한다.

\[
Cost(d,m,s)
=
C_{access}(d,m,s)
+
C_{capacity}(d,m,s)
+
C_{migration}(d,m,s)
+
C_{operation}(d,m,s)
+
C_{constraint}(d,m,s)
\]

- `C_access`: Data Access에 발생하는 BW / latency / contention 비용
- `C_capacity`: 제한된 Memory Capacity 사용 비용
- `C_migration`: 향후 Placement 변경 시 예상 이동 비용
- `C_operation`: Memory Compute Capability를 사용하거나 사용하지 않음으로써 발생하는 Operation 비용
- `C_constraint`: QoS, Write Cost 등의 제약 비용

`C_operation`은 **Memory에서 수행 가능한 연산의 적합성/효율성**을 반영하며, Compute Placement 자체를 결정하지 않는다.

### 5.5 Tier Selection

후보 Memory 집합에서 Cost가 최소이거나 Utility가 최대인 Tier를 선택한다.

```text
Candidate Memory Set
        │
        ▼
Cost / Utility Evaluation
        │
        ├── HBM : Cost = ...
        ├── DRAM: Cost = ...
        ├── CXL : Cost = ...
        └── PNM : Cost = ...
        │
        ▼
     Argmin / Argmax
        │
        ▼
Selected Memory Tier
```

### 5.6 Placement Output

```text
PlacementDecision
├── object_id
├── source_tier
├── destination_tier
├── decision_reason
├── estimated_cost
├── selected_operation_capability (optional)
└── confidence / validity
```

Placement Executor는 `PlacementDecision`을 받아 실제 Allocation 또는 Migration을 수행한다. Migration의 구체적인 mechanism은 DP4에서 정의한다.

> **Compute Placement 자체는 본 식의 결정 대상이 아니다.** 해당 Data를 특정 Memory에 배치했을 때 발생하는 Access/Operation Cost 및 Feasibility만 고려한다. Prefill의 Compute Location은 DP2에서 결정한다.

---

## 6. Candidate Structures

## C1. Memory-centric Placement

### 6.1 Definition

> **Memory Resource의 Capacity / Bandwidth / Load / Capability를 중심으로 Data를 배치한다.**

Placement의 1차 의사결정 주체가 **Memory Resource**이다.

### 6.2 Architecture

```text
                      Scheduler / Runtime
                              │
                       Allocation Request
                              │
                              ▼
                 ┌──────────────────────────┐
                 │    Placement Manager     │
                 │                          │
                 │  Data / Memory / State   │
                 │       Descriptors        │
                 │            │             │
                 │            ▼             │
                 │  Memory-centric Policy   │
                 │            │             │
                 │            ▼             │
                 │  Candidate Memory Filter │
                 │            │             │
                 │            ▼             │
                 │  Cost / Utility Model    │
                 │            │             │
                 │            ▼             │
                 │  Tier Selection          │
                 │            │             │
                 │            ▼             │
                 │  Placement Executor      │
                 └────────────┬─────────────┘
                              │
             ┌────────────────┼────────────────┐
             ▼                ▼                ▼
            HBM              DRAM              CXL
```

### 6.3 Decision Flow

```text
Memory Resource State
        ↓
Resource-aware Policy
        ↓
Candidate Memory Filtering
        ↓
Resource / Access Cost 계산
        ↓
Best Tier 선택
        ↓
Data 배치
```

Memory Compute Capability는 `Capability`의 일부로 취급하며, Data의 `required_operations`와 매칭하여 후보 Memory를 제한하거나 Operation Cost를 계산한다.

### 6.4 주요 특성

- Memory Resource 중심의 의사결정
- Global Capacity / Bandwidth Pressure에 빠른 대응
- Data Type과 독립적인 공통 Resource Allocation 구조
- 상대적으로 작은 Data Characterization 비용
- 신규 Memory Type 추가에 유리한 구조

### 6.5 대표적인 동작 예

```text
HBM Free Capacity ↓
        │
        ▼
CXL Available Capacity ↑
        │
        ▼
Cold / Non-critical Data
        │
        ▼
CXL 배치
```

Memory-centric 구조에서는 동일한 Memory State에서 Data A/B의 미래 Access 특성이 크게 다르더라도 Resource State가 같다면 유사한 Placement Decision이 발생할 수 있다.

---

## C2. Data-centric Placement

### 6.6 Definition

> **Data Object의 Runtime 특성을 중심으로 적합한 Memory Tier를 선택한다.**

Placement의 1차 의사결정 주체가 **Data Object**이다.

### 6.7 Architecture

```text
                      Scheduler / Runtime
                              │
                       Allocation Request
                              │
                              ▼
                 ┌──────────────────────────┐
                 │    Placement Manager     │
                 │                          │
                 │  Data Characterizer      │
                 │            │             │
                 │            ▼             │
                 │  Data Descriptor         │
                 │            │             │
                 │            ▼             │
                 │  Data-centric Policy     │
                 │            │             │
                 │            ▼             │
                 │  Candidate Memory Filter │
                 │            │             │
                 │            ▼             │
                 │  Cost / Utility Model    │
                 │            │             │
                 │            ▼             │
                 │  Tier Selection          │
                 │            │             │
                 │            ▼             │
                 │  Placement Executor      │
                 └────────────┬─────────────┘
                              │
             ┌────────────────┼────────────────┐
             ▼                ▼                ▼
            HBM              DRAM              CXL
```

### 6.8 Decision Flow

```text
Data Object
     ↓
Data Characterization
     ↓
Common Data Descriptor
     ↓
Data-centric Policy
     ↓
Feasibility / Candidate Memory Filtering
     ↓
Data × Memory Cost 계산
     ↓
Best Tier 선택
     ↓
Data 배치
```

### 6.9 Data-centric Placement의 핵심

Data-centric 구조에서도 **Memory State, Memory Descriptor, Access Cost, Compute Capability는 반드시 고려**한다.

차이는 Access Cost나 Memory Capability의 존재 여부가 아니라 **Placement Decision의 중심이 Data Object에 있다는 것**이다.

```text
             Data Object
                  │
     ┌────────────┼────────────┐
     ▼            ▼            ▼
  Hotness      Lifetime       Reuse
     │            │            │
     └────────────┼────────────┘
                  ▼
          Policy / Candidate
                  │
                  ▼
         Memory Capability
          + Access Cost
                  │
                  ▼
            Tier Selection
```

### 6.10 대표적인 동작 예

```text
Data A
Hot + High Reuse + Short Next Access
              ↓
             HBM

Data B
Warm + Moderate Reuse
              ↓
            DRAM

Data C
Cold + Long Lifetime
              ↓
             CXL/SSD
```

동일한 Memory State에서도 Data의 Runtime 특성이 다르면 서로 다른 Tier가 선택될 수 있다.

---

## 7. Data-centric Placement의 Data Type 적용

### 7.1 KV Cache

```text
KV Block
├─ Size
├─ Hotness
├─ Next Access / Reuse
├─ Session Lifetime
├─ Attention Access Pattern
└─ Required Operations
        │
        ▼
   HBM / DRAM / CXL / SSD
```

KV Cache는 Data-centric Placement의 가장 성숙한 적용 대상이다.

### 7.2 RAG Data

```text
Document / Chunk / Index Partition
├─ Retrieval Frequency
├─ Query Locality
├─ Size
├─ Sharing
├─ Read Intensity
└─ Required Operations
        │
        ▼
   HBM / DRAM / CXL / SSD / PNM
```

예:

```text
Frequently Retrieved Chunk → HBM
Moderately Retrieved Data  → DRAM / CXL
Rarely Retrieved Data      → SSD
Search-heavy Index         → PNM candidate
```

### 7.3 Agent Memory / State

```text
Agent Memory Object
├─ Session Locality
├─ Lifetime
├─ Hotness
├─ Reuse
└─ Size
        │
        ▼
   HBM / DRAM / CXL / SSD
```

### 7.4 LoRA Adapter

```text
Adapter
├─ Request Frequency
├─ Sharing
├─ Size
└─ Reuse
        │
        ▼
   HBM / DRAM / CXL / SSD
```

### 7.5 MoE Expert

```text
Expert
├─ Routing Frequency
├─ Size
├─ Sharing
├─ Access Pattern
└─ Required Operations
        │
        ▼
   HBM / DRAM / CXL / SSD
```

---

## 8. Placement Lifecycle

Placement는 한 번 결정하고 끝나는 것이 아니라 Data Lifecycle에 따라 반복적으로 평가될 수 있다.

```text
             Data 생성 / 유입
                    │
                    ▼
             Initial Placement
                    │
                    ▼
                Runtime
                    │
          ┌─────────┴─────────┐
          │                   │
      상태 변화 없음        상태 변화
          │                   │
          ▼                   ▼
         유지            Placement Re-evaluation
                              │
                     ┌────────┴────────┐
                     ▼                 ▼
                  유지             재배치
                                      │
                             Promotion / Demotion
```

### Re-evaluation Trigger

- Hotness 변화
- Access Pattern 변화
- Lifetime 변화
- Memory Pressure 증가
- Memory Bandwidth Contention 증가
- QoS / Latency Requirement 변화
- Data Type-specific state 변화
- Memory Compute Capability 또는 Operation Requirement 변화

---

## 9. Initial Placement vs Re-placement

### 9.1 Initial Placement

새로운 Data Object가 생성되거나 Runtime에 유입될 때 수행한다.

```text
New Data
   ↓
Descriptor 생성
   ↓
Placement Policy 적용
   ↓
Memory Candidate Filtering
   ↓
Cost / Utility Evaluation
   ↓
Placement Selection
```

### 9.2 Re-placement

이미 배치된 Data가 현재 위치에서 더 이상 적합하지 않다고 판단되는 경우 수행한다.

```text
Current Placement
       ↓
Current Cost Monitoring
       ↓
Re-evaluation
       ↓
Policy + Candidate Filtering
       ↓
New Placement
```

다음 조건을 만족하는 경우에만 실제 재배치를 수행한다.

\[
Expected\ Benefit > Re\text{-}placement\ Cost
\]

실제 Data 이동은 DP4의 Migration Mechanism에 의해 수행된다.

---

## 10. Placement Manager Architecture

두 후보가 공통으로 사용하는 구조와 후보별 차이를 분리한다.

```text
                         Placement Manager
                                │
             ┌──────────────────┼──────────────────┐
             │                  │                  │
             ▼                  ▼                  ▼
        Data Descriptor    Memory Descriptor    System State
             │                  │                  │
             └──────────────────┼──────────────────┘
                                ▼
                        Placement Policy
                           ┌────┴────┐
                           ▼         ▼
                          C1        C2
                       Memory-    Data-
                       centric    centric
                           │         │
                           └────┬────┘
                                ▼
                    Candidate Memory Filtering
                                │
                                ▼
                        Cost / Utility Model
                                │
                                ▼
                        Placement Decision
                                │
                                ▼
                       Placement Executor
```

### 10.1 공통 모듈

- `DataDescriptorBuilder`
- `MemoryStateCollector`
- `MemoryDescriptor`
- `SystemStateCollector`
- `FeasibilityFilter`
- `AccessCostModel`
- `OperationCostModel`
- `PlacementExecutor`

### 10.2 C1 전용 핵심 모듈

- `ResourceStateEvaluator`
- `MemoryCentricPlanner`

### 10.3 C2 전용 핵심 모듈

- `DataCharacterizer`
- `DataDescriptorBuilder`
- `DataCentricPlanner`

> **C1과 C2의 공정한 비교를 위해 공통 Memory State / Access Cost / Operation Feasibility / Executor 계층은 동일하게 유지하고, 1차 Decision Logic만 변경한다.**

---

## 11. Decision Interface

### 11.1 Placement Request

```text
PlacementRequest
├── data_descriptor
├── memory_descriptors
├── current_tier
├── system_state
└── trigger
```

### 11.2 Placement Policy Interface

개념적인 인터페이스는 다음과 같다.

```python
class PlacementPolicy:
    def select_tier(
        self,
        request: PlacementRequest,
        memories: list[MemoryDescriptor],
        state: SystemState,
    ) -> PlacementDecision:
        ...
```

실제 내부 흐름은 다음과 같다.

```text
PlacementRequest
      │
      ▼
Policy-specific Evaluation
      │
      ▼
Candidate Memory Filtering
      │
      ▼
Cost / Utility Evaluation
      │
      ▼
PlacementDecision
```

### 11.3 C1

```python
class MemoryCentricPolicy(PlacementPolicy):
    def select_tier(...):
        # Memory Resource state를 1차 기준으로 Tier 선택
        # Data requirement는 feasibility / cost 보조 입력
        ...
```

### 11.4 C2

```python
class DataCentricPolicy(PlacementPolicy):
    def select_tier(...):
        # Data Descriptor를 1차 기준으로 Tier 선택
        # Memory state / capability는 feasibility / cost 입력
        ...
```

두 정책은 동일한 출력 형식을 반환한다.

```text
PlacementDecision
├── destination_tier
├── estimated_cost
├── decision_reason
├── selected_operation_capability (optional)
└── confidence
```

---

## 12. DP2 / DP3 / DP4와의 경계

### DP1. Data Placement

> **Data를 어느 Memory Tier에 둘 것인가?**

```text
Data → Memory Tier
```

Memory Compute Capability는 **Placement의 Feasibility 및 Cost 판단에 입력으로 사용**한다.

### DP2. Prefill Compute Placement

> **Prefill Compute를 어느 Compute Resource에서 수행할 것인가?**

```text
Prefill → Compute Resource
```

DP1에서 Memory의 Compute Capability를 고려할 수 있지만, **Compute Resource의 위치 자체를 결정하지 않는다.**

### DP3. Data Eviction

> **Capacity가 부족할 때 어떤 Data를 제거할 것인가?**

```text
Memory Pressure
      ↓
Data Selection for Eviction
```

DP1은 Destination을 결정하고, DP3는 제거 대상을 결정한다.

### DP4. Data Migration

> **결정된 Data Placement를 실제로 어떻게 이동시킬 것인가?**

```text
Source Tier
    ↓
Migration Mechanism
    ↓
Destination Tier
```

DP1의 `Placement Decision`은 DP4의 실행 대상과 Destination을 제공할 수 있지만, 실제 Data Movement의 Path / DMA / Scheduling은 DP4에서 다룬다.

---

## 13. Candidate Comparison Summary

| 항목 | C1. Memory-centric | C2. Data-centric |
|---|---|---|
| 1차 Decision 주체 | **Memory Resource** | **Data Object** |
| 핵심 질문 | 이 Memory Resource를 누구에게 할당할 것인가? | 이 Data Object를 어디에 둘 것인가? |
| 주요 입력 | Capacity / BW / Load / Capability | Hotness / Lifetime / Locality / Reuse / Access Pattern |
| Memory State | 핵심 입력 | 공통 입력 |
| Access Cost | 공통 입력 | 공통 입력 |
| Compute Capability | 공통 입력 / Operation Feasibility | 공통 입력 / Operation Feasibility |
| Data Characterization | 최소 | 핵심 |
| Placement Granularity | Resource 중심 | Data Object 중심 |
| 강점 | 단순성 / Resource Utilization | Fine-grained Data-aware Placement |
| 주요 비용 | Data 특성 활용 제한 | Characterization / Prediction |
| 주요 확장 축 | **New Memory Type** | **New Data Type** |

> **두 후보의 차이는 Access Cost 또는 Compute Capability의 사용 여부가 아니다.** 두 후보 모두 동일한 Memory State, Access Cost, Memory Compute Capability를 사용할 수 있다. 차이는 **어떤 객체가 Placement Decision을 주도하는가**에 있다.

---

## 14. Design Decision Points

최종 후보 선정 전에 다음을 독립적으로 검증한다.

### DD1. Data Descriptor 범위

서로 다른 Data Type을 어느 수준까지 공통 Descriptor로 표현할 수 있는가?

### DD2. Placement Granularity

Data Object / Block / Session Group / Index Partition 중 어느 단위를 기본 Placement Unit으로 사용할 것인가?

### DD3. Re-placement Frequency

상태 변화를 얼마나 자주 감지하고 Placement를 재평가할 것인가?

### DD4. Cost Model

Access / Capacity / Migration / Operation / Constraint 비용을 어떤 형태로 결합할 것인가?

### DD5. Candidate Filtering

Capacity / Operation / Reachability / QoS / Endurance 등의 조건을 어느 단계에서 적용할 것인가?

### DD6. C1 / C2 Decision Boundary

Memory State를 중심으로 결정하는 C1과 Data Characteristics를 중심으로 결정하는 C2의 실제 차이가 어느 workload/system condition에서 나타나는가?

### DD7. Data Type Extension

신규 Data Type이 추가되었을 때 기존 Placement Policy를 유지하면서 Descriptor Adapter만 추가할 수 있는가?

### DD8. Memory Type Extension

신규 Memory Type이 추가되었을 때 기존 Placement Policy를 수정하지 않고 Memory Descriptor와 Capability만 추가하여 지원할 수 있는가?

### DD9. Memory Compute Capability

Memory가 제공하는 Operation을 어떤 granularity로 Descriptor화하고, Placement Cost/Utility에 어떻게 반영할 것인가?

---

## 15. Design Principles

1. **Data Placement와 Compute Placement를 분리한다.**
2. **Data Type과 Physical Representation을 분리한다.**
3. **Memory raw specification과 Effective Access Cost를 분리한다.**
4. **Memory Compute Capability를 Placement Feasibility 및 Cost의 입력으로 취급한다.**
5. **C1/C2의 공통 Runtime Infrastructure를 최대한 공유한다.**
6. **Placement Policy → Candidate Filtering → Cost/Utility → Tier Selection의 명시적인 Decision Pipeline을 유지한다.**
7. **Placement Decision과 Migration Execution을 분리한다.**
8. **모든 Data를 무조건 dynamic placement 대상으로 취급하지 않는다.**
9. **신규 Data Type / Memory Type 확장을 공통 Interface를 통해 수용한다.**

---

## 16. 관련 문서

- `dp1-heterogeneous-memory-data-placement.md` — DP1 전체 Design Point / Background / Memory Configuration / Evaluation
- `dp1-implementation-uml.md` — 구현 구조 및 UML
- `dp1-simulation-results.md` — 후보 구조 정량 평가 및 시뮬레이션 결과
- DP2 — Prefill Compute Placement
- DP3 — Data Eviction
- DP4 — Data Migration
