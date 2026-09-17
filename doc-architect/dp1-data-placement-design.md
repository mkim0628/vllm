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

Agent Memory는 하나의 고정 자료구조가 아니라 Agent가 이후 Step/Turn에서 재사용하기 위해 보존하는 **Persistent State/Data의 논리적 범주**이다.

### 3.3 Common Data Descriptor

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

Data-specific 정보는 **Adapter / Characterizer**가 공통 Descriptor로 변환한다.

---

## 4. Memory Abstraction

### 4.1 Memory Descriptor

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

`Compute Capability`는 PIM/PNM 등 **Memory 자체에서 수행할 수 있는 연산 능력**을 표현한다. 특정 reduction, vector operation, search/filter 등의 지원 여부와 처리 성능을 나타낼 수 있다.

> Memory Compute Capability를 Placement 입력으로 사용하는 것은 **어느 Memory에 Data를 둘 것인가**를 판단하기 위한 것이다. 어떤 Compute Resource에서 Prefill을 수행할 것인가는 DP2에서 결정한다.

### 4.2 System State

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

```text
Data → Access Path → Effective Access Cost
              ├── Hop count
              ├── Link bandwidth
              ├── Link latency
              └── Contention
```

---

## 5. Placement Decision Model

### 5.1 전체 Decision Pipeline

Placement Decision은 **Data 특성, Memory Resource 특성, Runtime System State**를 통합하여 Placement Policy를 적용하고, 후보 Memory를 필터링한 뒤 비용/효용을 비교하여 최종 Tier를 선택한다.

```text
┌─────────────────┐      ┌──────────────────┐      ┌─────────────────┐
│ Data Descriptor │      │ Memory Descriptor│      │  System State  │
└────────┬────────┘      └────────┬─────────┘      └────────┬────────┘
         └────────────────────────┼─────────────────────────┘
                                  ▼
                         ┌─────────────────┐
                         │ Placement Policy│
                         │     C1 / C2    │
                         └────────┬────────┘
                                  ▼
                         ┌─────────────────┐
                         │Candidate Memory │
                         │    Filtering    │
                         └────────┬────────┘
                                  ▼
                    ┌─────────────┼─────────────┐
                    ▼             ▼             ▼
                 Capacity      Operation   Reachability
                   Check         Check        Check
                    └─────────────┼─────────────┘
                                  ▼
                         ┌─────────────────┐
                         │Candidate Memory │
                         │       Set       │
                         └────────┬────────┘
                                  ▼
                         ┌─────────────────┐
                         │ Cost / Utility  │
                         │   Evaluation    │
                         └────────┬────────┘
                                  ▼
                         ┌─────────────────┐
                         │  Tier Selection │
                         └────────┬────────┘
                                  ▼
                         ┌─────────────────┐
                         │PlacementDecision│
                         └────────┬────────┘
                                  ▼
                         ┌─────────────────┐
                         │PlacementExecutor│
                         └─────────────────┘
```

**C1/C2의 핵심 차이는 전체 Pipeline이 아니라 `Placement Policy` 내부의 소프트웨어 구조와 1차 Decision State가 무엇인가에 있다.** Candidate Filtering, Cost Model, Executor는 공통 Infrastructure로 유지한다.

### 5.2 Candidate Memory Filtering

```text
All Memory Tiers
       │
       ▼
┌─────────────────────────┐
│    Feasibility Filter   │
├─────────────────────────┤
│ Capacity                │
│ Supported Operation     │
│ Reachability            │
│ QoS / Latency           │
│ Endurance / Constraint  │
└────────────┬────────────┘
             ▼
      Candidate Memory Set
```

특히 **Memory Compute Capability는 Operation Feasibility의 핵심 입력**이다.

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

### 5.3 Cost / Utility Calculation

Feasible Memory에 대해서만 Placement Cost 또는 Utility를 계산한다.

\[
Cost(d,m,s)=C_{access}+C_{capacity}+C_{migration}+C_{operation}+C_{constraint}
\]

- `C_access`: BW / latency / contention 비용
- `C_capacity`: 제한된 Memory Capacity 사용 비용
- `C_migration`: 향후 Placement 변경 시 예상 이동 비용
- `C_operation`: Memory Compute Capability를 사용했을 때의 연산 비용/효율
- `C_constraint`: QoS, Write Cost 등의 제약 비용

> Compute Placement 자체는 본 DP의 결정 대상이 아니다. Prefill Compute Location은 DP2에서 결정한다.

### 5.4 Placement Output

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

---

## 6. Candidate Structures

## C1. Memory-centric Placement

### 6.1 Definition

> **Memory Resource의 Capacity / Bandwidth / Load / Capability를 중심으로 Data를 배치한다.**

Placement의 1차 의사결정 주체가 **Memory Resource**이다.

### 6.2 Architecture — Resource-driven Software Structure

C1은 **Memory Resource를 중심으로 Runtime 상태를 관리하고, Resource별 Allocation/Admission 상태를 유지하는 구조**이다. Data는 Memory Resource Manager에 들어오는 Allocation 대상이며, 각 Memory Resource의 상태가 Placement Decision을 주도한다.

```text
                         ┌─────────────────────────────┐
                         │      AI Runtime / Scheduler │
                         └──────────────┬──────────────┘
                                        │ Allocation Request
                                        ▼
┌──────────────────────────────────────────────────────────────────┐
│              C1 Memory-centric Placement                         │
│                                                                  │
│  ┌────────────────────────────────────────────────────────────┐  │
│  │              Memory Resource Manager                       │  │
│  │                                                            │  │
│  │  ┌──────────────┐     ┌───────────────────────────────┐  │  │
│  │  │Resource      │────▶│ Resource State / Monitor      │  │  │
│  │  │Registry      │     │ Capacity / BW / Load /       │  │  │
│  │  └──────────────┘     │ Capability / Pressure        │  │  │
│  │                       └───────────────┬───────────────┘  │  │
│  │                                       ▼                  │  │
│  │                       ┌───────────────────────────────┐  │  │
│  │                       │ Resource-aware Placement     │  │  │
│  │                       │ Planner                      │  │  │
│  │                       └───────────────┬───────────────┘  │  │
│  └─────────────────────────────────────┼───────────────────┘  │
└────────────────────────────────────────┼──────────────────────┘
                                         │
                    ┌────────────────────┼────────────────────┐
                    ▼                    ▼                    ▼
              ┌───────────┐        ┌───────────┐        ┌───────────┐
              │HBM Resource│        │DRAM Resource│      │CXL Resource│
              │ Adapter    │        │ Adapter     │      │ Adapter    │
              └───────────┘        └───────────┘        └───────────┘
```

**구조적 특징**

- `Memory Resource Registry`가 상위 1차 객체이다.
- Resource별 상태와 Allocation 가능량을 관리한다.
- `Resource-aware Placement Planner`가 Memory Resource 상태를 비교하여 Data를 어느 Resource에 할당할지 결정한다.
- Data Characterization은 최소한의 Feasibility / Constraint 정보만 전달하는 보조 계층이다.
- 신규 Memory Type은 **새 Resource Adapter/Manager를 추가**하는 방향으로 확장한다.

### 6.3 Decision Flow

```text
Memory Resource State
        ↓
Resource별 Available Capacity / BW / Load / Capability 구성
        ↓
Data Allocation Request 수용 가능 Resource 확인
        ↓
Resource Cost / Pressure 비교
        ↓
Memory Tier 선택
        ↓
Data 배치
```

---

## C2. Data-centric Placement

### 6.4 Definition

> **Data Object의 Runtime 특성을 중심으로 적합한 Memory Tier를 선택한다.**

Placement의 1차 의사결정 주체가 **Data Object**이다.

### 6.5 Architecture — Object-driven Software Structure

C2는 **Data Object를 중심으로 Data Lifecycle과 Runtime Characterization을 관리하고, 각 Data Object에 대해 적합한 Memory Tier를 계산하는 구조**이다. Memory는 공통 Resource Registry로 추상화되고, Data별 Policy Evaluation이 Placement Decision을 주도한다.

```text
                         ┌─────────────────────────────┐
                         │      AI Runtime / Scheduler │
                         └──────────────┬──────────────┘
                                        │ Data Object Event
                                        ▼
┌──────────────────────────────────────────────────────────────────┐
│               C2 Data-centric Placement                          │
│                                                                  │
│  ┌────────────────────────────────────────────────────────────┐  │
│  │              Data Placement Manager                        │  │
│  │                                                            │  │
│  │  ┌──────────────┐    ┌───────────────────────────────┐   │  │
│  │  │Data Object   │───▶│ Data Characterizer            │   │  │
│  │  │Registry      │    │ Hotness / Reuse / Lifetime / │   │  │
│  │  └──────────────┘    │ Locality / Access Pattern    │   │  │
│  │                      └──────────────┬────────────────┘   │  │
│  │                                     ▼                    │  │
│  │                      ┌───────────────────────────────┐   │  │
│  │                      │ Data-aware Placement Planner │   │  │
│  │                      │ Data × Memory Cost / Utility │   │  │
│  │                      └──────────────┬────────────────┘   │  │
│  └────────────────────────────────────┼────────────────────┘  │
│                                       │                       │
│                       ┌───────────────▼───────────────┐       │
│                       │ Common Memory Resource        │       │
│                       │ Registry / Descriptor         │       │
│                       └───────────────┬───────────────┘       │
└───────────────────────────────────────┼───────────────────────┘
                                        │
                         ┌──────────────┼──────────────┐
                         ▼              ▼              ▼
                    ┌────────┐     ┌────────┐     ┌────────┐
                    │  HBM   │     │  DRAM  │     │  CXL   │
                    └────────┘     └────────┘     └────────┘
```

**구조적 특징**

- `Data Object Registry`가 상위 1차 객체이다.
- Data별 Descriptor와 Lifecycle / Access History를 관리한다.
- `Data Characterizer`가 Runtime 관측값을 Data Descriptor로 변환한다.
- `Data-aware Placement Planner`가 하나의 Data Object에 대해 여러 Memory Tier의 Cost/Utility를 비교한다.
- 신규 Data Type은 **새 Data Adapter/Characterizer를 추가**하는 방향으로 확장한다.

### 6.6 C1 / C2 Software Structure의 핵심 차이

```text
C1. Memory-centric                     C2. Data-centric
────────────────────                   ────────────────────
Memory Resource가 중심                Data Object가 중심
        │                                      │
        ▼                                      ▼
Memory Resource Manager               Data Placement Manager
        │                                      │
        ├─ Resource Registry                  ├─ Data Registry
        ├─ Resource Monitor                   ├─ Data Characterizer
        └─ Resource Planner                   ├─ Data Descriptor
                                               └─ Data-aware Planner
        │                                      │
        ▼                                      ▼
"어느 Resource가 여유/적합한가?"       "이 Data에 어느 Tier가 적합한가?"
        │                                      │
        └───────────────┬──────────────────────┘
                        ▼
               Common Memory Interface
                        │
             Feasibility / Cost Model
                        │
                 Placement Executor
```

따라서 C1과 C2는 단순히 동일한 순서도에서 **Policy 이름만 바뀌는 구조가 아니다.**

- C1은 **Resource-centric State Management → Resource Planner → Data Allocation**의 소프트웨어 구조를 가진다.
- C2는 **Data Registry → Characterization → Data-aware Planner → Tier Selection**의 소프트웨어 구조를 가진다.
- 두 구조는 하위의 `Memory Descriptor`, `Feasibility Filter`, `Cost Model`, `Placement Executor`를 공유할 수 있다.

### 6.7 공통 / 차별화 모듈

| Software Layer | C1 Memory-centric | C2 Data-centric |
|---|---|---|
| Primary Registry | **Memory Resource Registry** | **Data Object Registry** |
| Runtime State Owner | **Resource State** | **Data Runtime State** |
| Characterization | 최소 / 보조 | **Data Characterizer** |
| Core Planner | **Resource-aware Planner** | **Data-aware Planner** |
| Decision Granularity | Resource 중심 | Data Object 중심 |
| Extension 축 | **New Memory Type** | **New Data Type** |
| Common Layer | Memory Descriptor / Feasibility / Cost / Executor | 동일 |

---

## 7. Data-centric Placement의 Data Type 적용

### 7.1 KV Cache

```text
KV Block
├─ Size
├─ Hotness
├─ Next Access / Reuse
├─ Session Lifetime
└─ Attention Access Pattern
        │
        ▼
   HBM / DRAM / CXL / SSD
```

### 7.2 RAG Data

```text
Document / Chunk / Index Partition
├─ Retrieval Frequency
├─ Query Locality
├─ Size
├─ Sharing
└─ Read Intensity
        │
        ▼
   HBM / DRAM / CXL / SSD
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
└─ Access Pattern
        │
        ▼
   HBM / DRAM / CXL / SSD
```

---

## 8. Placement Lifecycle

```text
Data 생성 / 유입
       ↓
Initial Placement
       ↓
Runtime Monitoring
       ↓
상태 변화 감지
       ↓
Placement Re-evaluation
       ├── 유지
       └── 재배치 → Promotion / Demotion
```

Re-evaluation Trigger:

- Hotness 변화
- Access Pattern 변화
- Lifetime 변화
- Memory Pressure 증가
- Memory Bandwidth Contention 증가
- QoS / Latency Requirement 변화
- Data Type-specific state 변화

---

## 9. Initial Placement vs Re-placement

### 9.1 Initial Placement

```text
New Data → Descriptor 생성 → Candidate Filtering → Placement Selection
```

### 9.2 Re-placement

```text
Current Placement → Cost Monitoring → Re-evaluation → New Placement
```

실제 재배치는 다음 조건을 만족하는 경우 수행한다.

\[
Expected\ Benefit > Re\text{-}placement\ Cost
\]

실제 Data 이동은 DP4의 Migration Mechanism에 의해 수행된다.

---

## 10. Placement Manager Architecture

두 후보가 공통으로 사용하는 하위 계층과 후보별 핵심 모듈을 분리한다.

```text
                         Placement Manager
                                │
             ┌──────────────────┼──────────────────┐
             │                  │                  │
             ▼                  ▼                  ▼
        Data Descriptor    Memory State       Access Cost
             │                  │                  │
             └──────────────────┼──────────────────┘
                                │
                    ┌───────────┴───────────┐
                    ▼                       ▼
              C1 Resource              C2 Data
              Planner                  Planner
                    │                       │
                    └───────────┬───────────┘
                                ▼
                        Feasibility Filter
                                ▼
                         Cost / Utility Model
                                ▼
                       Placement Decision
                                ▼
                       Placement Executor
```

### 10.1 공통 모듈

- `MemoryStateCollector`
- `MemoryDescriptor`
- `AccessCostModel`
- `FeasibilityFilter`
- `PlacementExecutor`

### 10.2 C1 핵심 모듈

- `MemoryResourceRegistry`
- `ResourceStateEvaluator`
- `MemoryCentricPlanner`

### 10.3 C2 핵심 모듈

- `DataObjectRegistry`
- `DataCharacterizer`
- `DataDescriptorBuilder`
- `DataCentricPlanner`

---

## 11. Decision Interface

### 11.1 Placement Request

```text
PlacementRequest
├── data_descriptor
├── current_tier
├── candidate_memories
├── system_state
└── trigger
```

### 11.2 Placement Policy Interface

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

### 11.3 C1

```python
class MemoryCentricPolicy(PlacementPolicy):
    def select_tier(...):
        # Memory Resource state를 중심으로 Tier 선택
        ...
```

### 11.4 C2

```python
class DataCentricPolicy(PlacementPolicy):
    def select_tier(...):
        # Data Descriptor를 중심으로 Tier 선택
        ...
```

---

## 12. DP2 / DP3 / DP4와의 경계

### DP1. Data Placement

> **Data를 어느 Memory Tier에 둘 것인가?**

```text
Data → Memory Tier
```

### DP2. Prefill Compute Placement

> **Prefill Compute를 어느 Compute Resource에서 수행할 것인가?**

```text
Prefill → Compute Resource
```

DP1에서 Memory의 Compute Capability를 고려할 수 있지만, **Compute Resource의 위치 자체를 결정하지 않는다.**

### DP3. Data Eviction

> **Capacity가 부족할 때 어떤 Data를 제거할 것인가?**

```text
Memory Pressure → Data Selection for Eviction
```

### DP4. Data Migration

> **결정된 Data Placement를 실제로 어떻게 이동시킬 것인가?**

```text
Source Tier → Migration Mechanism → Destination Tier
```

---

## 13. Candidate Comparison Summary

| 항목 | C1. Memory-centric | C2. Data-centric |
|---|---|---|
| 1차 Decision 주체 | **Memory Resource** | **Data Object** |
| Primary Registry | Memory Resource | Data Object |
| Core Planner | Resource-aware Planner | Data-aware Planner |
| 핵심 질문 | 이 Resource를 누구에게 할당할 것인가? | 이 Data를 어디에 둘 것인가? |
| 주요 입력 | Capacity / BW / Load / Capability | Hotness / Lifetime / Locality / Reuse / Access Pattern |
| Memory State | 핵심 입력 | 공통 입력 |
| Access Cost | 공통 입력 | 공통 입력 |
| Data Characterization | 최소 | 핵심 |
| Placement Granularity | Resource 중심 | Data Object 중심 |
| 확장 축 | **New Memory Type** | **New Data Type** |

> **두 후보의 차이는 Access Cost의 사용 여부가 아니다.** 두 후보 모두 동일한 Access Cost Model과 Memory State를 사용할 수 있다. 차이는 **어떤 객체가 Placement Decision을 주도하는가**와 그에 따라 **어떤 Registry / Planner / Characterizer가 중심이 되는가**에 있다.

---

## 14. Design Decision Points

### DD1. Data Descriptor 범위
서로 다른 Data Type을 어느 수준까지 공통 Descriptor로 표현할 수 있는가?

### DD2. Placement Granularity
Data Object / Block / Session Group / Index Partition 중 어느 단위를 기본 Placement Unit으로 사용할 것인가?

### DD3. Re-placement Frequency
상태 변화를 얼마나 자주 감지하고 Placement를 재평가할 것인가?

### DD4. Cost Model
Access / Capacity / Migration / Operation / Constraint 비용을 어떤 형태로 결합할 것인가?

### DD5. C1 / C2 Decision Boundary
Memory State를 중심으로 결정하는 C1과 Data Characteristics를 중심으로 결정하는 C2의 실제 차이가 어느 workload/system condition에서 나타나는가?

### DD6. Data Type Extension
신규 Data Type이 추가되었을 때 기존 Placement Policy를 유지하면서 Descriptor Adapter만 추가할 수 있는가?

### DD7. Memory Type Extension
신규 Memory Type이 추가되었을 때 기존 Placement Policy를 수정하지 않고 Memory Descriptor / Resource Adapter만 추가하여 지원할 수 있는가?

---

## 15. Design Principles

1. **Data Placement와 Compute Placement를 분리한다.**
2. **Data Type과 Physical Representation을 분리한다.**
3. **Memory raw specification과 Effective Access Cost를 분리한다.**
4. **C1/C2의 공통 Runtime Infrastructure를 최대한 공유한다.**
5. **Placement Decision과 Migration Execution을 분리한다.**
6. **모든 Data를 무조건 dynamic placement 대상으로 취급하지 않는다.**
7. **신규 Data Type / Memory Type 확장을 공통 Interface를 통해 수용한다.**
8. **C1/C2의 차이는 Policy 명칭이 아니라 소프트웨어 구조와 1차 State Ownership에서 명확히 드러나야 한다.**

---

## 16. 관련 문서

- `dp1-heterogeneous-memory-data-placement.md` — DP1 전체 Design Point / Background / Memory Configuration / Evaluation
- `dp1-implementation-uml.md` — 구현 구조 및 UML
- `dp1-simulation-results.md` — 후보 구조 정량 평가 및 시뮬레이션 결과
- DP2 — Prefill Compute Placement
- DP3 — Data Eviction
- DP4 — Data Migration
