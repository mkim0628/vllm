# DP1. 이기종 메모리 기반 AI 데이터 배치 구조

## 1. Design Point 개요

### 목적

LLM/Agent 추론 시스템 내에서 HBM, DRAM, CXL-PNM, Custom HBM, HBF, SSD-PIM 등 저장·연산 특성이 서로 다른 메모리가 혼재할 때, **AI Runtime Data를 어느 메모리에 배치할 것인지**를 어떤 기준으로 결정할지 설계한다.

기존 DP1은 KV Cache를 대상으로 메모리 배치를 설계했으나, 본 판에서는 이를 **AI Runtime Data Placement** 문제로 확장한다.

여기서 AI Runtime Data는 AI 모델과 관련된 모든 데이터를 의미하지 않는다. **Runtime에 의해 생성·관리되며 workload 및 system state에 따라 Memory Placement를 동적으로 변경할 실질적인 가치가 있는 Data Object**를 대상으로 한다.

대표적인 대상은 다음과 같다.

- **KV Cache** — 요청/세션에 따라 생성·증가하며 Hotness, Reuse, Lifetime이 변화
- **RAG Data** — Document, Chunk, Embedding, Retrieval Index 등 Query에 따라 접근 locality가 변화
- **Agent Memory** — Conversation/Episodic Memory, Semantic Memory, Task/Working State 등 장기 보존되는 Runtime State
- **Tool Result / Agent State** — Multi-step Agent 실행 과정에서 생성되고 이후 재사용 가능
- **LoRA Adapter** — Multi-LoRA 환경에서 Request별 사용 빈도가 변화
- **MoE Expert** — Token routing에 따라 Expert별 접근 빈도가 변화

일반적인 Dense Model Weight와 일반 Activation은 기본 범위에서 제외한다. Dense Model Weight는 대부분 요청에서 지속적으로 사용되어 request-level dynamic placement의 필요성이 낮고, 일반 Activation은 lifetime이 짧아 heterogeneous-memory tiering의 효과가 제한적이다.

### 핵심 설계 질문

> **Memory Resource를 중심으로 데이터를 배치할 것인가, Data Object의 특성을 중심으로 메모리를 선택할 것인가?**

### 배치 결정 시점

AI Runtime Data의 lifecycle을 따라가면 Placement를 결정하거나 재평가해야 하는 시점이 반복적으로 발생한다.

```text
  Data 생성 / 유입
        │
        ▼
   [ 결정점 A ]
   "초기 배치를 어디에?"
        │
        ▼
      실행
        │
        ▼
   [ 상태 변화 ]
   Hotness / Lifetime / Access 변화
        │
        ▼
   [ 결정점 B ]
   "현재 위치를 유지할 것인가?"
        │
    ┌───┴───┐
    ▼       ▼
  유지    재배치
            │
      Promotion / Demotion
```

| | **결정점 A — 생성/유입 시점** | **결정점 B — Runtime 상태 변화 시점** |
|---|---|---|
| **질문** | 새 Data를 어느 Memory Tier에 배치할 것인가 | 기존 Data의 Placement를 유지할 것인가 변경할 것인가 |
| **대상** | 신규 KV / RAG Data / Agent Memory / Tool State / Adapter 등 | 이미 배치된 Data Object 또는 Data Group |
| **주요 판단 근거** | Data 특성, 예상 Access Pattern, Memory State | 실제/예상 Hotness, Reuse, Lifetime, Memory Pressure, Access Cost |
| **틀렸을 때** | 부적합한 Tier에 처음부터 배치되어 이후 이동 비용 발생 | 고속 Memory의 용량 점유 또는 재접근 비용 증가 |

### 대상 범위

| | |
|---|---|
| **대상** | AI Runtime Data의 초기 배치 및 Runtime 중 Placement 재평가 |
| **대표 대상** | KV Cache, RAG Data, Agent Memory, Tool Result / Agent State |
| **확장 대상** | LoRA Adapter, MoE Expert 등 Dynamic Model-related Data |
| **대상 아님** | **Prefill 연산의 실행 위치** — DP2의 쟁점 |
| **대상 아님** | **어떤 Data를 Evict할 것인가** — DP3의 쟁점 |
| **대상 아님** | **실제 Data Migration을 어떻게 수행할 것인가** — DP4의 쟁점 |
| **기본 대상 아님** | Dense Model Weight, 일반적인 짧은 lifetime의 Activation |

> **본 문서는 Placement의 결정 구조를 정의한다.** 실제 Tier 간 이동 실행은 DP4에서 다루며, Prefill Compute의 위치는 DP2에서 다룬다.

---

## 2. 배경 / 문제 정의

### ① AI Workload의 Memory Footprint 증가와 Heterogeneous Memory의 등장

AI Serving에서는 Context Length, Concurrency, RAG, Multi-turn, Agent Memory 등으로 Runtime Data Footprint가 증가한다.

```text
Long Context
      +
High Concurrency
      +
RAG / Agent Memory
      +
Multi-turn
      ↓
Runtime Data Footprint ↑
      ↓
HBM Capacity Pressure ↑
```

동시에 HBM, DRAM, CXL Memory, HBF, SSD 등 서로 다른 Capacity / BW / Latency 특성을 갖는 Memory가 하나의 시스템에서 함께 사용될 수 있다.

일부 Memory는 저장 기능뿐 아니라 **Near-memory Compute Capability**까지 제공한다. 다만 본 DP에서는 Compute Placement 자체를 결정하지 않으며, Data Placement 비용 및 해당 Data가 요구하는 Operation과의 적합성 판단에만 사용한다.

### ② AI Runtime Data는 서로 다른 Runtime 특성을 가짐

AI Runtime Data는 동일한 Access Pattern을 갖지 않는다.

| Data | Physical Representation 예 | 주요 Runtime 특성 | 자연스러운 Placement Unit |
|---|---|---|---|
| **KV Cache** | KV Block | 높은 Access 빈도, 증가하는 크기, Reuse, Session Lifetime | Block / Session Block Set |
| **RAG Data** | Document / Chunk / Embedding / Index Partition | Query-dependent Locality, Hot/Cold | Chunk / Index Partition |
| **Agent Memory** | Serialized Record / Structured State / KV Record | Long Lifetime, Session/User Locality, Reuse | Memory Entry / Session Group |
| **Tool Result** | Serialized Result / Object / KV Record | Step-dependent Reuse, Lifetime 다양 | Result Object / Session State |
| **LoRA Adapter** | Adapter Weight Object | Request-dependent Hotness, Reuse | Adapter |
| **MoE Expert** | Expert Weight Object | Token Routing-dependent Access Skew | Expert |

따라서 동일한 Memory Tier에 단순히 생성 순서대로 배치하거나 HBM이 부족할 때 순차적으로 하위 Tier로 Spill하는 방식만으로는 Data 특성을 충분히 활용하기 어렵다.

### ③ Agent Memory의 정의

본 DP에서 Agent Memory는 하나의 특정 자료구조를 의미하지 않고, **Agent가 이후 Step/Turn에서 재사용하기 위해 보존하는 Persistent State/Data의 논리적 범주**로 정의한다.

```text
Agent Memory
├── Conversation / Episodic Memory
│   └── Serialized Record / Document / KV Record
├── Semantic Memory
│   └── Structured Record + Optional Embedding
└── Task / Working State
    └── Structured State / Object / KV Record
```

실험에서는 각 Memory 유형의 Physical Representation을 고정하여 구현한다. 예를 들어 Agent Memory는 Serialized Record 또는 KV Record 형태로 저장하고, RAG Data는 Document/Chunk 또는 Embedding Index 형태로 저장한다.

### ④ 기존 단순 Tiering의 한계

### As-Is

**HBM 우선 할당 + Capacity 부족 시 하위 Memory로 Spill**

→ Memory Tier의 실제 특성과 Data별 Hotness / Lifetime / Locality / Reuse를 충분히 활용하지 못함

### To-Be

**AI Runtime Data 특성 + Memory Resource 특성 + System State를 함께 고려하는 Dynamic Data Placement**

→ Data의 Runtime Access 특성에 따라 적합한 Memory Tier를 선택하고 필요 시 Placement를 재평가

---

## 3. 대상 메모리 구성

기존 DP1의 6종 Memory Configuration을 기본 환경으로 유지한다.

### 3.0 노드 구성

```text
   ┌──────────────── GPU 노드 ────────────────┐      ┌─── Custom HBM 노드 ───┐
   │                                          │      │                       │
   │   GPU  ══[on-package]══  HBM   192 GiB   │      │   Custom HBM  1 TiB   │
   │                     HBF     2 TiB        │      │   + 근접 연산 유닛     │
   │                                          │      │                       │
   │    ╚════════ scale-up fabric ════════════╪══════╪══► 외부 0.9 TB/s      │
   │                                          │      │   내부 8.0 TB/s       │
   └────╫─────────────────────────────────────┘      └───────────────────────┘
        ║ PCIe
   ┌────╨──── CPU 노드 ────┐
   │  CPU ── DRAM   1 TiB  │
   │   ║                   │
   │   ╠══ CXL ══ CXL-PNM  512 GiB
   │   ╚══ NVMe ═ SSD-PIM   16 TiB
   └───────────────────────┘
```

### 3.1 6종 Memory 특성

| Memory | 위치 | 연산 가능 | 용량 | 외부 BW | 내부 BW | GPU 직접 접근 |
|---|---|:---:|---:|---:|---:|:---:|
| **HBM** | GPU on-package | ✗ | 192 GiB | 8.0 TB/s | — | ✓ |
| **Custom HBM** | 별도 노드 | ✓ | 1.00 TiB | 0.9 TB/s | 8.0 TB/s | ✓ |
| **CXL-PNM** | CPU 측 CXL | ✓ | 512 GiB | 0.064 TB/s | 1.1 TB/s | ✗ |
| **DRAM** | CPU 측 | ✗ | 1.00 TiB | 0.064 TB/s | — | ✗ |
| **HBF** | GPU on-package | ✗ | 2.00 TiB | 1.0 TB/s | — | ✓ |
| **SSD-PIM** | CPU 측 NVMe | ✓ | 16.00 TiB | 0.016 TB/s | 0.2 TB/s | ✗ |

### 3.2 Access Path

Data Placement Cost 계산 시 Memory 자체의 BW만 사용하지 않고 **Data가 실제로 접근하는 경로의 BW / Latency / Contention**을 사용한다.

```text
on-package
HBM / HBF
    ↓
scale-up fabric
Custom HBM
    ↓
CPU-mediated path
DRAM / CXL-PNM / SSD-PIM
```

> **Memory의 내부 BW와 Data Access Path의 외부 BW는 분리한다.** 내부 BW가 높더라도 외부 Path가 병목이면 해당 Memory의 유효 Access Cost가 증가할 수 있다.

### 3.3 Memory State

Runtime에서 다음 상태를 관측한다.

- Available Capacity
- External / Internal Bandwidth
- Latency
- Current Load
- Queue / Contention
- Compute Capability
- Write Cost / Endurance Headroom

---

## 4. 설계 쟁점

### 쟁점 1. Placement의 1차 의사결정 주체

**C1. Memory-centric Placement**

> Memory Resource의 Capacity / BW / Load / Capability를 중심으로 Data를 배치

vs.

**C2. Data-centric Placement**

> Data Object의 Hotness / Lifetime / Locality / Reuse / Access Pattern을 중심으로 적합한 Memory를 선택

두 후보 모두 동일한 Memory State 및 Access Cost 정보를 사용할 수 있으며, 차이는 **Placement Decision을 무엇을 중심으로 구성하는가**에 있다.

### 쟁점 2. Data 특성의 활용 정도

C1은 Resource Allocation의 단순성과 전체 Memory Pool 관리에 중점을 두고, C2는 Data별 Runtime 특성을 이용한 Fine-grained Placement에 중점을 둔다.

### 쟁점 3. 신규 Data / Memory 추가에 대한 구조 변경 범위

- 신규 Data Type 추가
- 신규 Memory Type 추가

각 변경이 기존 Placement Policy와 Module에 미치는 영향을 Modifiability에서 측정한다.

---

## 5. Candidate 1. Memory-centric Placement

### 한 줄 정의

> **Memory Resource의 상태와 Capability를 1차 기준으로 Data를 배치**

### 구조

```text
                        Scheduler / Runtime
                                │
                         Allocation Request
                                │
                                ▼
                    ┌───────────────────────┐
                    │ Placement Manager     │
                    │                       │
                    │ Memory State Collector│
                    │  - Capacity           │
                    │  - Bandwidth          │
                    │  - Load               │
                    │  - Compute Capability │
                    │  - Access Cost        │
                    │          │            │
                    │          ▼            │
                    │ Placement Planner     │
                    │  - Resource Scoring   │
                    │  - Best Tier          │
                    │          │            │
                    │          ▼            │
                    │ Placement Executor    │
                    └───────────┬───────────┘
                                │
             ┌──────────────────┼──────────────────┐
             ▼                  ▼                  ▼
            HBM                DRAM               CXL
             │                  │                  │
             └──────────────────┴──────────────────┘
```

### 특징

- Memory State가 Placement의 1차 의사결정 기준이다.
- Data Type이 달라도 동일한 Resource Allocation 구조를 적용할 수 있다.
- Capacity Pressure와 Memory Contention에 빠르게 대응한다.
- 신규 Memory Tier 추가 시 Resource Descriptor 중심으로 확장한다.
- Data의 미래 Access Pattern을 자세히 예측하지 않아도 된다.

### 장점

- 구조가 단순하고 Decision Overhead가 낮다.
- 전체 Memory Pool의 Utilization 관리에 유리하다.
- 신규 Memory Type 추가가 용이하다.

### 단점

- Data별 Hotness / Lifetime / Locality / Reuse를 충분히 반영하지 못할 수 있다.
- 동일한 Memory State에서는 서로 다른 Data의 미래 Access 차이를 구별하기 어렵다.

### 한계가 드러나는 예

```text
Data A → 300 ms 후 재접근 예상
Data B → Session 종료, 재접근 없음

Memory State → 동일한 Free Capacity
```

Memory-centric 구조는 Memory State 자체를 중심으로 판단하므로 두 Data의 미래 Access 차이를 Placement의 핵심 입력으로 사용하지 않는다.

---

## 6. Candidate 2. Data-centric Placement

### 한 줄 정의

> **Data Object의 Runtime 특성을 중심으로 적합한 Memory Tier를 결정**

### 구조

```text
                        Scheduler / Runtime
                                │
                         Allocation Request
                                │
                                ▼
                    ┌─────────────────────────┐
                    │ Placement Manager       │
                    │                         │
                    │ Data Characterization   │
                    │  - Type                 │
                    │  - Size                 │
                    │  - Hotness              │
                    │  - Lifetime             │
                    │  - Locality             │
                    │  - Reuse                │
                    │  - Access Pattern       │
                    │          │              │
                    │          ▼              │
                    │ Data Classifier         │
                    │  - Hot / Warm / Cold    │
                    │  - Short / Long-lived   │
                    │  - High / Low Reuse     │
                    │          │              │
                    │          ▼              │
                    │ Tier Scorer             │
                    │  - Access Cost          │
                    │  - Capacity Cost        │
                    │  - Migration Cost       │
                    │  - Memory Capability    │
                    │          │              │
                    │          ▼              │
                    │ Placement Executor      │
                    └────────────┬────────────┘
                                 │
             ┌───────────────────┼───────────────────┐
             ▼                   ▼                   ▼
            HBM                 DRAM                 CXL
```

### 공통 Data-centric Abstraction

```text
                    Data Object
                         │
        ┌────────────────┼────────────────┐
        ▼                ▼                ▼
      Hotness          Lifetime         Locality
        │                │                │
        ├────────────────┼────────────────┤
        ▼                ▼                ▼
      Reuse         Access Pattern       Size
                         │
                         ▼
                  Memory Selection
```

### 데이터 유형별 적용 예

#### KV Cache

```text
Hot + High Reuse + Short Next-access
                ↓
               HBM

Warm + Moderate Reuse
                ↓
              DRAM

Cold + Long Lifetime
                ↓
             CXL / SSD
```

#### RAG Data

```text
Frequently Retrieved Chunk
                ↓
               HBM

Moderately Retrieved Data
                ↓
              DRAM/CXL

Rarely Retrieved Data
                ↓
               SSD
```

#### Agent Memory

```text
Recent / Frequently Accessed Memory
                ↓
               HBM

Inactive but Reusable Memory
                ↓
              DRAM/CXL

Long-term / Rarely Accessed Memory
                ↓
               SSD
```

#### LoRA Adapter / MoE Expert

```text
Frequently Requested / Frequently Routed
                ↓
               HBM

Occasionally Requested / Routed
                ↓
              DRAM/CXL

Rarely Requested / Routed
                ↓
             Lower Tier
```

### 장점

- Data별 Access 특성에 맞는 Fine-grained Placement가 가능하다.
- Hot/Cold 및 Lifetime 차이를 직접 반영할 수 있다.
- KV Cache뿐 아니라 RAG Data / Agent Memory / LoRA / MoE 등으로 확장 가능하다.
- Data별 Access Cost와 Memory Cost를 함께 최적화할 수 있다.

### 단점

- Data Characterization 및 Prediction을 위한 Runtime Overhead가 발생할 수 있다.
- 미래 Hotness / Lifetime / Reuse 추정 오차가 존재한다.
- Data Type별 Descriptor가 추가되면서 구조가 복잡해질 가능성이 있다.
- 잘못된 예측으로 불필요한 Migration이 발생할 수 있다.

---

## 7. C1 / C2 비교

| | **C1. Memory-centric** | **C2. Data-centric** |
|---|---|---|
| 1차 기준 | Memory Resource | Data Object |
| 핵심 질문 | 이 Memory를 누구에게 할당할 것인가? | 이 Data를 어디에 둘 것인가? |
| 주요 입력 | Capacity / BW / Load / Capability | Hotness / Lifetime / Locality / Reuse / Size |
| Access Cost | 공통 고려 | 공통 고려 |
| Memory State | 핵심 입력 | Feasibility / Cost 입력 |
| Data Prediction | 최소화 | 활용 |
| Decision granularity | Resource 중심 | Data Object 중심 |
| 강점 | 단순성 / Resource Utilization | Fine-grained Placement |
| 약점 | Data 특성 반영 한계 | Prediction / Characterization Overhead |
| 주요 확장 축 | New Memory | **New Data Type** |

> **C1과 C2의 차이는 Access Cost를 고려하느냐가 아니다.** 두 후보 모두 Data Access Path의 Cost를 고려한다. 차이는 **Placement Decision의 1차 주체를 Memory Resource로 둘 것인가, Data Object로 둘 것인가**에 있다.

---

## 8. DP2 / DP3 / DP4와의 경계

```text
                  Memory-Centric AI Runtime
                           │
             ┌─────────────┴─────────────┐
             │                           │
           DATA                        COMPUTE
             │                           │
             ▼                           ▼
            DP1                         DP2
       Data Placement            Prefill Compute
             │                     Placement
             │
       ┌─────┼─────┐
       ▼     ▼     ▼
     Where? When? How much?
       │
       ├──────────► DP3
       │             Data Eviction
       │             "What to remove?"
       │
       └──────────► DP4
                     Data Migration
                     "How to move?"
```

### DP1. Data Placement

> **어느 Memory Tier에 Data를 둘 것인가?**

### DP2. Prefill Compute Placement

> **Prefill을 어느 Compute Resource에서 수행할 것인가?**

DP1에서 Memory의 Compute Capability는 해당 Data를 해당 Memory에 배치했을 때의 Operation Cost 또는 Feasibility 판단에 사용될 수 있으나, **Compute Resource의 위치 자체는 DP2에서 결정한다.**

### DP3. Data Eviction

> **Memory Capacity가 부족할 때 어떤 Data를 제거할 것인가?**

DP1의 질문은 “어디에 둘 것인가”이고, DP3의 질문은 “무엇을 제거할 것인가”이다.

### DP4. Data Migration

> **Data를 다른 Memory Tier로 이동시키는 실행을 어떻게 수행할 것인가?**

DP1이 Placement Destination을 결정하면 DP4가 실제 Migration Path와 Mechanism을 담당한다.

---

## 9. Evaluation Metrics

### 9.1 Performance – Throughput

단위 시간당 처리량을 측정한다.

- **Request Throughput** — requests/s
- **Token Throughput** — tokens/s

Workload에 따라 Request throughput과 Token throughput을 함께 보고한다.

### 9.2 Performance – Latency

요청 처리 지연을 측정한다.

- **TTFT (Time to First Token)**
- **TPOT / ITL (Time Per Output Token / Inter-Token Latency)**
- **E2E Latency**

Placement Decision 및 Migration이 요청 critical path에 들어가는 경우 해당 비용은 최종 latency에 포함된다.

### 9.3 Resource Utilization

Heterogeneous Memory 자원의 활용 정도를 측정한다.

- **HBM Capacity Utilization**
- **Memory Bandwidth Utilization**
- **Tier Utilization** — HBM / DRAM / CXL / HBF / SSD 등
- **CPU / GPU Utilization**

필요 시 평균 Utilization뿐 아니라 Peak Utilization 및 시간에 따른 Utilization 분포를 함께 보고한다.

### 9.4 Modifiability

새로운 Data Type 또는 Memory Type을 추가할 때 요구되는 변경 노력을 측정한다.

#### Man-Month

> **Required Development Effort [man-month]**

다음의 변경 시나리오를 각각 측정한다.

```text
New Data Type
KV Cache / RAG Data / Agent Memory
        ↓
     New Data

New Memory Type
HBM / DRAM / CXL
        ↓
    New Memory
```

#### AI Token Consumption

AI Coding Agent를 이용한 개발에서 변경 작업에 소비된 Token 수를 측정한다.

\[
AI\ Token\ Consumption
=
Input\ Tokens + Output\ Tokens
\]

측정 시 모델, Agent 구성, 반복 횟수 등 측정 환경을 함께 기록한다.

#### # Modified Modules / Files

변경 작업에서 수정이 필요한 Module / File 수를 측정한다.

#### Change Propagation

하나의 변경 요구가 몇 개의 Module / Component로 전파되는지 측정한다.

---

## 10. Performance / Resource 보조 Metrics

### Migration-related Metrics

- **Migration Time [ms]**
- **Migration Traffic [GB]**
- **Migration Frequency [times/request]**
- **Migration Bandwidth [GB/s]**

Migration Time은 최종 Latency에 반영되며, Migration Traffic / Bandwidth는 Memory Bandwidth Utilization 및 Resource Contention 분석에 사용한다.

### Placement Decision Metrics

- **Placement Decision Latency [µs/ms]**
- **Placement Decision Frequency [times/request]**

Placement Decision Latency가 요청 critical path에 포함되는 경우 Performance–Latency에 반영하고, 포함되지 않는 경우 별도 profiling 결과로 기록한다.

### Data Characterization Metrics

C2에서 사용하는 Data Characterization 비용을 분석한다.

- Metadata Collection Time
- Characterization CPU Time
- Metadata Memory Footprint

---

## 11. Evaluation Scenario

### Scenario A. KV Cache

- Context Length 변화
- Multi-turn
- Prefix Reuse
- Hot / Cold Session 혼합
- HBM Capacity Pressure

### Scenario B. RAG Data

- Query Locality Skew
- Hot / Cold Document Distribution
- Retrieval Top-k 변화
- Large-scale Document / Index

### Scenario C. Agent Memory

- Short / Long Session
- Memory Access Frequency 변화
- Tool Call 간격 변화
- Recent / Long-term Memory 혼합

실험에서 Agent Memory는 **Serialized Record / Structured State / KV Record 중 하나의 Physical Representation으로 고정**하고, 해당 데이터가 HBM / DRAM / CXL / SSD 등에 배치되도록 구성한다.

### Scenario D. Extension

- Multi-LoRA Adapter
- MoE Expert

추가 Scenario는 동일한 Data Descriptor 및 Placement Interface를 이용할 수 있는지 검증하는 데 사용한다.

---

## 12. Modifiability 검증 방법

### 12.1 New Data Type 추가

기존 Data Type 집합에 새로운 Data Type을 추가한다.

```text
KV Cache
RAG Data
Agent Memory
      ↓
New Data Type
```

측정 항목:

- Man-Month
- AI Token Consumption
- Modified Modules / Files
- Change Propagation

### 12.2 New Memory Type 추가

기존 Memory Pool에 새로운 Memory Tier를 추가한다.

```text
HBM / DRAM / CXL / HBF / SSD
                ↓
           New Memory
```

측정 항목:

- Man-Month
- AI Token Consumption
- Modified Modules / Files
- Change Propagation

### 12.3 측정 원칙

동일한 기능 요구사항과 동일한 구현 범위를 기준으로 측정하고, AI Coding Agent 사용 여부와 모델/Agent Configuration을 결과에 함께 기록한다.

---

## 13. 후보 선정

본 문서는 Design Point의 정의, 대상 Data 및 Memory Configuration, 후보 구조, 평가 Metric과 검증 방법의 명세까지를 범위로 한다.

C1과 C2 중 어느 구조가 우수한지는 다음 조건에 따라 달라질 수 있다.

- Data Access Pattern의 안정성
- Hotness / Lifetime / Reuse 추정 정확도
- Memory Pressure
- Memory Tier의 Capacity / BW 차이
- Placement Decision 및 Data Characterization 비용
- Migration Cost
- Data Type 및 Memory Type의 다양성

따라서 단일 workload 또는 단일 Memory Configuration에서의 점 성능만으로 후보를 선정하지 않는다.

### 선정 원칙

> **Performance Throughput + Performance Latency + Resource Utilization + Modifiability를 함께 평가하고, 조건에 따른 Trade-off를 기준으로 후보를 선정한다.**

특히 C2는 특정 KV Cache 특성에만 최적화된 정책이 아니라 **KV Cache, RAG Data, Agent Memory 등 서로 다른 Data Type에서 동일한 Data Descriptor와 Placement Framework가 유지되는지**를 검증한다.

---

## 14. 향후 검증 항목

| 항목 | 검증 내용 |
|---|---|
| **Performance – Throughput** | Request / Token Throughput 비교 |
| **Performance – Latency** | TTFT / TPOT / E2E Latency 비교 |
| **Resource Utilization** | HBM Capacity / Memory BW / Tier / CPU / GPU Utilization 비교 |
| **Modifiability** | New Data / Memory 추가에 대한 Man-Month / AI Token / 변경 범위 측정 |
| **Migration Impact** | Migration Time / Traffic / Frequency가 Performance에 미치는 영향 |
| **Placement Decision Cost** | Decision Latency 및 Characterization 비용 |
| **Data Generality** | KV / RAG / Agent Memory에 동일 Framework 적용 |
| **Memory Extensibility** | 신규 Memory Type 추가 시 변경 범위 |
| **Topology Sensitivity** | Memory Access Path 및 Interconnect 변화 |

### 최종 연구 가설

> **AI Runtime Data는 서로 다른 형태와 의미를 가지더라도 Size, Hotness, Locality, Lifetime, Access Pattern 등의 공통 Runtime 특성으로 추상화할 수 있으며, 이러한 특성과 Heterogeneous Memory의 Capacity, Bandwidth, Latency, Access Cost를 함께 고려하면 Data Type에 종속되지 않는 Runtime Data Placement가 가능하다.**

> **C1은 Memory Resource 중심의 단순하고 낮은 Overhead의 Placement를 제공하고, C2는 Data Object 중심의 Fine-grained Placement를 제공한다. 두 구조의 Trade-off를 Performance, Resource Utilization, Modifiability 관점에서 정량적으로 평가한다.**
