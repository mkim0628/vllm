# DP1. AI Data Placement 설계

> **문서 유형:** Design Specification
>
> 본 문서는 DP1의 **이기종 메모리 기반 AI Data Placement 구조**를 구체화한다. 핵심 비교 대상은 다음 두 구조이다.
>
> - **C1. Memory-centric Placement**: Memory Resource State를 1차 기준으로 배치
> - **C2. Data-centric Placement**: AI Data 특성을 1차 기준으로 적합한 Memory Tier를 선택

---

## 1. Design Scope

### 1.1 목적

HBM, DRAM, CXL Memory, SSD, PIM/PNM 등 서로 다른 특성을 가진 Memory Tier가 공존하는 환경에서 AI Runtime Data를 어떤 Memory Tier에 배치할지 결정하는 구조를 정의한다.

대표 Placement 대상은 다음과 같다.

- KV Cache
- RAG Data / Embedding / Retrieval Index
- Agent Memory / State
- Tool Result / Runtime Log
- LoRA Adapter
- MoE Expert

### 1.2 핵심 질문

> **Memory Resource의 현재/예측 상태를 기준으로 Data를 배치할 것인가, Data 자체의 특성과 Runtime 동향을 기준으로 적합한 Memory Tier를 선택할 것인가?**

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

## 2. Common Input / Output

### 2.1 Data Descriptor

Scheduler가 Placement 요청을 전달할 때 Data-specific 정보를 공통 형태로 전달한다.

```text
DataDescriptor
├── object_id
├── data_type_hint
├── size_bytes
├── owner / session
├── current_tier
├── lifecycle_hint
├── access_requirement
└── required_operations
```

C1에서는 Data Descriptor를 최소한의 allocation constraint로 사용한다. C2에서는 Data Classifier의 입력으로 사용한다.

### 2.2 Memory Registry

Memory Registry는 Memory Tier의 정적/준정적 특성을 관리한다.

```text
MemoryRegistry
├── memory_id / memory_type
├── capacity
├── external_bandwidth
├── internal_bandwidth
├── latency
├── supported_operations
├── compute_capability
├── access_path
└── endurance / write_cost
```

Memory Registry는 **정적인 Memory Capability 정보**를 제공하며, 실시간 utilization / pressure / contention은 Telemetry Collector를 통해 별도로 수집한다.

### 2.3 Telemetry Collector

Telemetry Collector는 Placement Manager 외부에 위치하며, Memory 및 System의 실시간 상태를 수집하여 C1/C2에 제공한다.

대표 Telemetry:

- available capacity
- bandwidth utilization
- queue/load
- memory pressure
- access contention
- latency variation
- request load

### 2.4 Placement Output

```text
PlacementDecision
├── object_id
├── source_tier
├── destination_tier
├── decision_reason
├── confidence
└── validity / reevaluation_hint
```

---

# 3. C1 — Memory-centric Placement

## 3.1 Definition

> **Memory Resource State를 1차 기준으로 배치한다.**

C1은 Data를 세밀하게 characterization하기보다, 현재 Memory Resource가 얼마나 사용 가능하고 앞으로 어떤 상태가 될지를 중심으로 Placement를 결정한다.

핵심 구조는 다음과 같다.

```text
Scheduler / Allocation Request
          │
          ▼
Data Descriptor Adapter
          │
          ▼
┌────────────────────────────────────────────┐
│         Memory Resource Manager            │
│                                            │
│   ┌──────────────────────────────┐         │
│   │ Resource State Monitor       │◀────────┼── Telemetry Collector
│   │ - current resource state     │         │
│   │ - trend monitoring           │         │
│   │ - near-future prediction     │         │
│   └──────────────┬───────────────┘         │
│                  │                         │
│                  │                         │
│   ┌──────────────▼───────────────┐         │
│   │ Candidate Builder            │◀────────┼── Memory Registry
│   │ - static capability          │         │
│   │ - monitored/predicted state  │         │
│   └──────────────┬───────────────┘         │
└──────────────────┼─────────────────────────┘
                   │
                   ▼
             Memory State View
                   │
                   ▼
      Resource-aware Placement Planner
                   │
                   ▼
             Memory Tier Selector
                   │
                   ▼
            Placement Executor
```

## 3.2 Resource State Monitor

Resource State Monitor는 단순 Telemetry forwarding 계층이 아니다.

### 역할

1. **Telemetry Collector로부터 실시간 Resource 상태 수집**
2. 시간에 따른 Resource 상태 변화 추적
3. Memory Resource 관점에서 단기 상태 예측
4. Placement에 사용할 정규화된 Resource State 생성

예:

```text
ResourceState
├── available_capacity
├── bandwidth_utilization
├── current_load
├── memory_pressure
├── contention
├── latency_state
├── trend
└── predicted_state
```

예측 대상은 복잡한 장기 forecasting이 아니라 Placement decision window에서 필요한 near-future 상태이다.

```text
현재 HBM 사용률 82%
  ↓
최근 증가율 +5% / interval
  ↓
request load 증가 중
  ↓
near-term pressure 상승 예상
  ↓
HBM candidate priority 감소
```

## 3.3 Candidate Builder

Candidate Builder는 다음 두 입력을 결합한다.

```text
Memory Registry
  - capacity
  - BW
  - latency
  - supported operation
  - compute capability
        +
Resource State Monitor
  - current utilization
  - pressure
  - contention
  - predicted state
        ↓
Candidate Builder
        ↓
Memory State View
```

즉, `Memory State View`는 단순 Memory 목록이 아니라 **현재/예측 Resource 상태를 반영한 Placement 후보 집합**이다.

```text
MemoryStateView
├── Candidate[HBM]
│   ├── capability
│   ├── current_state
│   ├── predicted_state
│   └── availability
├── Candidate[DRAM]
├── Candidate[CXL]
└── Candidate[SSD]
```

## 3.4 Resource-aware Placement Planner

Resource-aware Placement Planner는 `Memory State View`를 입력으로 받아 Resource 관점에서 최적 Tier를 선택한다.

주요 판단 요소:

- capacity headroom
- current / predicted pressure
- effective bandwidth
- latency
- contention
- supported operation
- resource cost

Data Descriptor는 size, required operation, QoS와 같은 **최소 constraint**만 제공한다.

## 3.5 C1 Decision Flow

```text
Allocation Request
      ↓
Data Descriptor Adapter
      ↓
Telemetry Collector → Resource State Monitor
                         ↓
                 Current State + Trend
                         ↓
                  State Prediction
                         ↓
Memory Registry ────────┐
                        ▼
                Candidate Builder
                        ↓
                 Memory State View
                        ↓
         Resource-aware Placement Planner
                        ↓
                 Best Memory Tier
                        ↓
                Placement Executor
```

## 3.6 C1 특징

### 장점

- Resource 상태 변화에 즉시 반응
- Data characterization 없이 낮은 decision overhead

### 단점

- Data별 접근 특성 반영 한계
- Long-lived cold data가 고속 자원을 점유할 수 있음

위 장단점은 PPT의 C1 평가 항목과 동일하게 유지한다. Resource pressure/BW contention에 대한 빠른 대응은 첫 번째 장점의 구체적 효과이며, 서로 다른 Data class를 세밀하게 구분하기 어렵다는 점은 첫 번째 단점에 포함된다.

---

# 4. C2 — Data-centric Placement

## 4.1 Definition

> **AI Data의 Class와 Runtime Behavior를 먼저 분석하고, 해당 Data에 적합한 Memory Tier를 선택한다.**

C2의 핵심은 Data Object Registry를 유지하는 것이 아니라, **Data Classifier + Runtime State Monitor + Data Characteristic Interpreter**를 통해 Data 특성을 만들어내는 것이다.

```text
Scheduler / Allocation Request
          │
          ▼
Data Descriptor Adapter
          │
          ▼
┌────────────────────────────────────────────────────────┐
│               Data Placement Manager                  │
│                                                       │
│   ┌──────────────────┐     ┌───────────────────────┐  │
│   │ Data Classifier  │     │ Runtime State Monitor │  │
│   │ KV / RAG / Agent │     │ class behavior/history│  │
│   │ Log / Adapter... │     │ trend / statistics    │  │
│   └────────┬─────────┘     └──────────┬────────────┘  │
│            └──────────────┬───────────┘               │
│                           ▼                           │
│              Data Characteristic Interpreter         │
│              - hotness                               │
│              - lifetime                              │
│              - reuse                                 │
│              - locality                              │
│              - access pattern                        │
└───────────────────────────┬───────────────────────────┘
                            │
                            ▼
                Data-aware Placement Planner
                            │
             ┌──────────────┴──────────────┐
             ▼                             ▼
  Memory Tier Affinity Evaluator      Memory Registry
             │
             ▼
      Affinity Tier Set
             │
             ▼
      Memory Tier Selector ◀──────── Telemetry Collector
             │
             ▼
          Best Tier
             │
             ▼
      Placement Executor
```

## 4.2 Data Classifier

Data Classifier는 Data Descriptor의 정보를 이용해 Data를 논리적 Class로 분류한다.

예:

```text
DataClass
├── KV_CACHE
├── RAG_DATA
├── AGENT_MEMORY
├── TOOL_RESULT
├── LOG_DATA
├── LORA_ADAPTER
└── MOE_EXPERT
```

Classifier의 목적은 단순 label 생성이 아니라, 이후 Runtime State와 결합하여 **Data class별 behavior model**을 적용할 수 있게 하는 것이다.

예:

```text
DataDescriptor
  size=128MB
  owner=session-42
  type_hint=KV
      ↓
Data Classifier
      ↓
DataClass = KV_CACHE
```

## 4.3 Runtime State Monitor

Runtime State Monitor는 C1의 Resource State Monitor와 역할이 다르다.

- C1 Resource State Monitor: **Memory Resource가 어떻게 변하는지 관찰/예측**
- C2 Runtime State Monitor: **Data Class가 Runtime에서 어떤 동작/흐름을 보이는지 축적/관찰**

Runtime State Monitor는 Data Class별 혹은 Object Group별 Runtime 통계를 축적한다.

```text
DataRuntimeStats
├── access_frequency
├── reuse_interval
├── read_write_ratio
├── lifetime_distribution
├── sequentiality / locality
├── sharing_degree
├── active / idle duration
└── transition_history
```

초기 배치 시에는 충분한 History가 없을 수 있으므로 Data Class의 prior/default profile을 사용하고, Runtime이 진행되면서 실제 관찰값으로 갱신한다.

```text
Initial Placement
  Data Class prior
      ↓
Runtime observations accumulate
      ↓
Runtime State Monitor
      ↓
class/object behavior statistics updated
```

## 4.4 Data Characteristic Interpreter

Data Characteristic Interpreter는 다음 두 정보를 결합한다.

```text
Data Classifier Output
       +
Runtime State Monitor Output
       ↓
Data Characteristic Interpreter
       ↓
Predicted Data Characteristics
```

출력 예:

```text
DataCharacteristics
├── predicted_hotness
├── predicted_lifetime
├── predicted_reuse
├── locality
├── access_pattern
├── read_write_intensity
├── sharing
└── operation_requirement
```

예:

```text
KV_CACHE
 + 최근 access interval 짧음
 + active session
 + read-dominant
      ↓
Hotness = High
Lifetime = Medium
Reuse = High
      ↓
HBM / DRAM affinity 상승
```

```text
AGENT_MEMORY
 + long idle interval
 + sparse reuse
 + long retention
      ↓
Hotness = Low
Lifetime = Long
      ↓
CXL / SSD affinity 상승
```

## 4.5 Memory Tier Affinity Evaluator

Affinity Evaluator는 Data Characteristics와 Memory Registry의 정적 Capability를 비교하여 **Data에 적합한 Tier 집합**을 만든다.

예:

```text
Data Characteristics
  hotness=high
  latency_sensitivity=high
  lifetime=short
       ↓
Memory Tier Affinity Evaluator
       ↓
HBM: High Affinity
DRAM: Medium Affinity
CXL: Low Affinity
SSD: Reject
```

Affinity는 현재 Memory의 순간적인 load를 의미하지 않는다.

> **Affinity Evaluator = Data와 Memory Tier 특성 간의 본질적 적합성 평가**

## 4.6 Memory Tier Selector

Memory Tier Selector는 Affinity Evaluator가 만든 후보 중에서 **현재 실제 Resource 상태를 고려해 Best Tier를 선택**한다.

입력:

- Affinity Tier Set
- Memory Registry
- Telemetry Collector의 실시간 Memory Resource 상태

예:

```text
Affinity Result
  HBM = 0.95
  DRAM = 0.75
  CXL = 0.40
       +
Telemetry
  HBM pressure = 95%
  DRAM pressure = 45%
       ↓
Memory Tier Selector
       ↓
DRAM 선택
```

따라서 C2는 Data-aware이지만 Resource 상태를 무시하지 않는다.

- **1차:** Data 특성으로 적합한 Tier를 좁힘
- **2차:** 실시간 Resource 상태로 실제 Best Tier를 결정

## 4.7 C2 Decision Flow

```text
Allocation Request
      ↓
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
                               ↓
Telemetry Collector ─────▶ Memory Tier Selector
                               ↓
                           Best Tier
                               ↓
                      Placement Executor
```

## 4.8 C2 특징

### 장점

- KV / RAG / Agent 등 Data 특성 기반 fine-grained 배치
- 불필요한 고속 메모리 점유 감소 가능

### 단점

- Data Characterization / Runtime state 관리 overhead 증가
- 추정 오류 시 mis-placement 가능
- 신규 Data Type Adapter 설계 비용

여기서 신규 Data Type 지원 비용은 구현에 따라 별도 Adapter 추가뿐 아니라 Data Classifier와 Data Characteristic rule/model 확장 비용을 포함할 수 있다. 또한 초기 History 부족에 따른 prior/default profile 사용 문제는 Runtime State Monitor의 cold-start 처리로 남겨두되, PPT의 공식 장단점 항목에는 별도 항목으로 추가하지 않는다.

---

# 5. C1 vs C2 핵심 차이

| 구분 | C1 Memory-centric | C2 Data-centric |
|---|---|---|
| 1차 기준 | Memory Resource State | AI Data Characteristics |
| 핵심 Monitor | Resource State Monitor | Runtime State Monitor |
| Monitor 대상 | Memory Resource의 상태 변화 | Data Class의 동작/흐름/History |
| Prediction 대상 | Resource pressure/load/BW 변화 | Hotness/Lifetime/Reuse 등 Data 특성 |
| 정적 정보 | Memory Registry | Memory Registry + Data Class |
| 중간 결과 | Memory State View | Data Characteristics / Tier Affinity |
| 후보 생성 | Resource Candidate Builder | Memory Tier Affinity Evaluator |
| 최종 선택 | Resource-aware Planner | Memory Tier Selector |
| 실시간 Telemetry 사용 | Resource State 생성의 핵심 입력 | Affinity 후보 중 Best Tier 선택 시 사용 |
| Data Characterization | 최소화 | 핵심 기능 |

가장 중요한 차이는 다음과 같다.

```text
C1
Telemetry → Resource 변화 분석/예측
         → Memory State View
         → Resource 기준 Placement

C2
Data Class + Runtime History
         → Data 특성 분석/예측
         → Tier Affinity
         + 실시간 Resource Telemetry
         → Best Tier 선택
```

---

# 6. Component Responsibility Boundary

## C1

### Memory Resource Manager
- Allocation Request 진입점
- Resource State Monitor / Candidate Builder orchestration

### Resource State Monitor
- Telemetry 수집 결과 해석
- Resource 상태 변화 추적
- near-future Resource 상태 예측

### Candidate Builder
- Memory Registry + Resource State 결합
- Candidate Resource 생성
- `Memory State View` 생성

### Resource-aware Placement Planner
- Memory State View 기반 Tier 결정

## C2

### Data Placement Manager
- Data-centric Placement pipeline orchestration

### Data Classifier
- Data Descriptor 기반 Data Class 분류

### Runtime State Monitor
- Data Class/Object의 Runtime behavior와 History 축적

### Data Characteristic Interpreter
- Data Class + Runtime statistics 기반 Data 특성 분석/예측

### Memory Tier Affinity Evaluator
- Data Characteristics와 Memory Capability를 비교하여 적합 Tier 후보 생성

### Memory Tier Selector
- Affinity + Telemetry 기반 실제 Best Tier 선택

---

# 7. DP Boundary

DP1은 **어느 Memory Tier에 Data를 배치할 것인가**를 결정한다.

- DP1 — Data Placement
- DP2 — Prefill / Compute Placement
- DP3 — Data Eviction
- DP4 — Data Migration

Placement 결과로 destination tier가 바뀌고 실제 Data 이동이 필요해지는 경우, 실제 Migration 수행은 DP4에 위임한다.
