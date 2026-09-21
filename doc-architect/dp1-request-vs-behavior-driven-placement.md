# DP1-B. Request-driven vs Behavior-driven AI Data Placement

> **문서 유형:** Design Point Specification
>
> 본 문서는 기존 DP1의 `Memory-centric vs Data-centric` 비교와 별도로, **Placement Decision의 Trigger와 시점**을 기준으로 두 구조를 비교한다.
>
> - **C1. Request-driven Placement**: Allocation Request 시점의 현재 정보로 즉시 Initial Placement
> - **C2. Behavior-driven Placement**: Runtime Data Behavior를 지속 관찰하고 향후 Behavior를 예측하여 Proactive Re-placement

---

## 1. 배경 / 문제 정의

이기종 Memory 환경에서는 AI Data를 HBM, Custom HBM/HBM-F, DRAM, CXL Memory, SSD 등 어느 Tier에 둘지 결정해야 한다.

기존 Allocation-time Placement만으로는 Runtime 중 변화하는 Data Access Behavior를 반영하기 어렵다. 반대로 Runtime Behavior를 지속적으로 추적하는 방식은 더 적응적인 Placement가 가능하지만 Monitoring, Prediction, Migration Overhead가 발생한다.

따라서 본 DP의 핵심 질문은 다음과 같다.

> **Placement Optimization을 언제, 어떤 정보를 기준으로 수행할 것인가?**

```text
                         AI Data Placement
                                 │
                    "언제 Placement를 판단할 것인가?"
                                 │
                ┌────────────────┴────────────────┐
                ▼                                 ▼
               C1                                C2
      Request-driven Placement          Behavior-driven Placement
                │                                 │
       Allocation Request                  Runtime Monitoring
                │                                 │
       Current Information               Observed Behavior
                │                                 │
       Rule/Policy Decision             Interpret + Predict
                │                                 │
       Initial Placement               Proactive Re-placement
```

---

## 2. 대상 AI Data

본 DP의 대상은 단순히 "AI System에 존재하는 모든 Data"가 아니다.

다음 lifecycle이 의미 있는 Data를 주요 대상으로 한다.

1. Memory에 배치된다.
2. 이후 Runtime에서 실제 Access가 발생한다.
3. Access Frequency, Reuse, Lifetime, Locality 등의 Behavior가 존재한다.
4. Placement에 따라 Latency, Bandwidth, Capacity 효율이 달라진다.

### 2.1 KV Cache

가장 대표적인 대상이다.

- Prefill/Decode 과정에서 생성 및 Allocation
- Decode 중 반복 Access
- Context length와 request lifecycle에 따라 Lifetime 변화
- Access/Reuse 상태 변화에 따라 상·하위 Memory Tier 간 Placement 가치가 큼

### 2.2 Agent Memory

Agent가 interaction/task 수행 과정에서 생성·저장한 Memory를 이후 turn/task에서 retrieve하는 경우를 대상으로 한다.

- Long-lived 가능
- Retrieve frequency가 불규칙
- Hot/Warm/Cold 변화 가능
- Runtime Behavior에 따라 상위/하위 Tier 이동 가능

### 2.3 LoRA Adapter

LoRA Adapter는 Base Model Weight에 추가되는 작은 Adapter Weight이다.

Multi-tenant Serving에서는 다수 Adapter를 동시에 서비스할 수 있으며 모든 Adapter를 Fast Memory에 상주시킬 필요가 없다.

- Adapter load 시 Allocation/Residency 필요
- 특정 Adapter request가 반복될 수 있음
- Tenant/domain popularity에 따라 Hotness 변화
- Hot Adapter는 Fast Tier, Cold Adapter는 Capacity Tier에 둘 수 있음

### 2.4 MoE Expert Weight

MoE Expert도 Access Frequency/Activation Skew를 기반으로 Placement/Rebalancing할 수 있다.

다만 일반적으로 request마다 새 Expert가 Allocation되는 것이 아니라 Model Load 시 Weight가 배치된 후 Router가 Expert를 선택한다.

따라서 본 DP의 **대표 Allocation-time 사례보다는 Runtime Residency/Rebalancing 확장 사례**로 취급한다.

### 2.5 Tool Result

일반적인 Tool Result는 다음과 같이 생성 직후 소비되는 경우가 많다.

```text
Tool Call → Tool Execution → Tool Result → LLM Context → Consume
```

따라서 단발성 Tool Result 자체는 주요 Placement 대상으로 보지 않는다.

단, Tool Result를 여러 turn/request에서 재사용하는 **Tool/Agent Result Cache**의 경우 Runtime Access Behavior가 형성되므로 본 DP의 확장 대상으로 포함할 수 있다.

---

# 3. C1 — Request-driven Placement

## 3.1 Definition

> **Allocation Request가 들어오는 순간 현재 이용 가능한 정보와 Resource State를 이용해 즉시 Target Memory를 결정한다.**

C1의 핵심은 미래 Data Behavior Prediction이 아니다.

Allocation 시점에 이미 알고 있는 정적/준정적 Data Property와 현재 Resource State를 기반으로 Rule/Policy를 적용한다.

```text
Allocation Request
        │
        ▼
Data Descriptor
- data type
- size
- priority / QoS
- required operation
        │
        +--------------------+
        │                    │
        ▼                    ▼
   Memory Registry    Resource State Monitor
                           ▲
                           │
                   Telemetry Collector
        │                    │
        └─────────┬──────────┘
                  ▼
          Rule / Policy Engine
                  │
                  ▼
          Target Memory Tier
                  │
                  ▼
          Initial Placement
```

## 3.2 Resource State Monitor

Resource State Monitor는 Memory Resource의 현재 상태를 제공한다.

대표 정보:

- available capacity
- bandwidth utilization
- current pressure
- contention
- current latency state

본 후보에서는 Data의 미래 Access Behavior를 예측하지 않는다.

Resource State Monitor의 목적은 **현재 Allocation Request를 수용하기에 어느 Memory Resource가 적절한지 판단하기 위한 상태 제공**이다.

## 3.3 Rule / Policy 예

```text
KV_CACHE
  + HBM headroom >= threshold
      → HBM

KV_CACHE
  + HBM pressure high
      → CXL / DRAM candidate

LORA_ADAPTER
  + Fast-tier capacity available
      → HBM
  otherwise
      → DRAM / CXL
```

실제 Rule은 Data Type, Size, QoS, Required Operation과 현재 Resource State의 조합으로 정의한다.

## 3.4 C1 특징

### 장점

- Allocation 시 즉시 Placement 결정
- Runtime Data Monitoring 불필요
- Prediction Model 불필요
- Migration을 최소화할 수 있음
- 낮은 Runtime Overhead

### 단점

- Allocation 이후 변화하는 Access Behavior를 반영하기 어려움
- 초기 Placement가 잘못되면 장기간 Mis-placement 가능
- Dynamic workload / popularity 변화 대응 한계

---

# 4. C2 — Behavior-driven Placement

## 4.1 Definition

> **Runtime에서 Data의 실제 Access Behavior를 지속적으로 관찰하고, Behavior의 변화와 추세를 해석/예측하여 필요 시 선제적으로 Re-placement한다.**

C2에서 Allocation Request는 Placement Optimization의 핵심 Trigger가 아니다.

최초 Allocation은 Default/Simple Policy로 수행할 수 있으며, 이후 Runtime Monitoring Loop가 Placement를 지속적으로 평가한다.

```text
Initial / Default Placement
          │
          ▼
      Runtime Execution
          │
          ▼
┌─────────────────────────────┐
│     Data Behavior Monitor   │
│                             │
│ - access frequency          │
│ - reuse interval            │
│ - object age / lifetime     │
│ - active / idle duration    │
│ - locality                  │
│ - hotness trend             │
└──────────────┬──────────────┘
               │
               ▼
     Behavior Interpretation
               │
               ▼
      Future Behavior Prediction
               │
               ▼
       Placement Evaluation
               │
          ┌────┴────┐
          ▼         ▼
        Keep     Re-place
                    │
                    ▼
                 DP4 Migration
```

## 4.2 Data Behavior Monitor

C2의 핵심 Monitor는 Resource가 아니라 **Data의 Runtime Behavior**를 본다.

대표 관찰값:

```text
DataBehavior
├── access_frequency
├── reuse_interval
├── read_write_ratio
├── object_age
├── active_idle_duration
├── locality
├── sharing_degree
└── hotness_trend
```

예를 들어 LoRA Adapter의 Access Frequency가 다음과 같이 변한다고 하자.

```text
t0 :  2 req/s
t1 :  5 req/s
t2 : 15 req/s
t3 : 40 req/s
```

단순히 현재 `40 req/s`라는 값만 사용하는 것이 아니라 상승 추세를 해석하여 향후 Hotness 증가를 예측한다.

```text
Observed Behavior
      ↓
Increasing Hotness
      ↓
Future high access expected
      ↓
Proactive Promotion
DRAM/CXL → HBM
```

## 4.3 Proactive Re-placement

C2의 핵심 가치는 문제가 발생한 후 이동하는 Reactive Migration만이 아니다.

```text
Observe
   ↓
Interpret
   ↓
Predict
   ↓
Re-place before next high-demand phase
```

즉 향후 Access가 증가할 것으로 예상되는 Data는 Fast Tier로 미리 Promotion하고, 향후 Access가 감소할 것으로 예상되는 Data는 Capacity Tier로 Demotion할 수 있다.

### KV Cache 예

```text
KV #37
recent reuse ↑
access interval ↓
active context 지속
      ↓
future access high 예상
      ↓
CXL/DRAM → Fast Memory Promotion
```

반대로:

```text
KV #52
reuse ↓
idle duration ↑
session activity ↓
      ↓
future access low 예상
      ↓
HBM → CXL/DRAM Demotion
```

### Agent Memory 예

```text
Agent Memory #8
최근 여러 turn에서 반복 retrieve
      ↓
Hotness 상승
      ↓
Fast Tier Promotion
```

### LoRA Adapter 예

```text
Legal-LoRA
request frequency 지속 증가
      ↓
future popularity 증가 예상
      ↓
CXL/DRAM → HBM Promotion
```

## 4.4 C2 특징

### 장점

- 실제 Runtime Behavior를 기반으로 Placement 최적화
- Dynamic workload 변화 대응
- Hot/Warm/Cold 변화 반영
- 선제적 Promotion/Demotion 가능
- 초기 Mis-placement를 Runtime에서 교정 가능

### 단점

- Continuous Monitoring Overhead
- Behavior Interpretation/Prediction Overhead
- Migration Cost
- Prediction 오류 시 불필요한 Migration 가능
- Oscillation/Thrashing 방지 정책 필요

---

# 5. C1 vs C2 핵심 차이

| 구분 | C1 Request-driven | C2 Behavior-driven |
|---|---|---|
| Placement Trigger | Allocation Request | Runtime Behavior 변화 |
| 주요 시점 | Allocation 순간 | Allocation 이후 Runtime |
| 핵심 입력 | Data Property + Current Resource State | Observed Data Behavior + Resource State |
| Data Behavior Monitoring | 없음 | 핵심 기능 |
| Future Behavior Prediction | 없음 | 있음 |
| Decision 방식 | Rule / Policy-based | Adaptive / Predictive |
| 주요 동작 | Initial Placement | Proactive Re-placement |
| Migration 필요성 | 낮음 | 높음 |
| Runtime Overhead | 낮음 | 상대적으로 높음 |
| Dynamic Workload 대응 | 제한적 | 높음 |
| 핵심 질문 | "지금 어디에 할당할까?" | "곧 어디에 있어야 할까?" |

가장 중요한 차이는 다음과 같다.

```text
C1
Allocation Event
   ↓
Current Information
   ↓
Rule / Policy
   ↓
Initial Placement

C2
Runtime Execution
   ↓
Actual Data Behavior
   ↓
Interpret + Predict
   ↓
Proactive Re-placement
```

---

# 6. C1/C2가 대안이 되는 이유

C1과 C2를 단순히 `Initial Placement`와 `Migration 기능`으로 정의하면 두 구조는 상호보완적 기능이 되어 Candidate 비교가 성립하기 어렵다.

본 DP에서는 두 후보를 **Placement Optimization Strategy**의 대안으로 정의한다.

### C1

Allocation 시점에 Placement Optimization을 수행하고 이후 Data Behavior 기반의 지속적 재평가는 하지 않는다.

### C2

최초 Allocation은 Default/Simple Policy로 처리하고, Runtime Behavior를 기반으로 Placement Optimization을 지속 수행한다.

따라서 비교 질문은 다음과 같다.

> **낮은 Overhead의 Allocation-time Placement를 사용할 것인가, 추가 Monitoring/Migration Cost를 감수하고 Runtime Behavior 기반 Adaptive Placement를 사용할 것인가?**

실제 제품 구조에서는 두 방식을 결합한 Hybrid도 가능하지만, QA 단계에서는 각 접근법의 독립적인 효과와 비용을 비교한다.

---

# 7. Hybrid Extension

C1과 C2 평가 결과에 따라 다음과 같은 Hybrid 구조로 확장할 수 있다.

```text
Allocation Request
      │
      ▼
C1 Rule-based Initial Placement
      │
      ▼
Runtime Execution
      │
      ▼
C2 Data Behavior Monitoring
      │
      ▼
Behavior Prediction
      │
      ├── Current placement valid → Keep
      │
      └── Better tier expected
                    │
                    ▼
                DP4 Migration
```

Hybrid의 의미는 명확하다.

- **C1:** 낮은 비용으로 합리적인 초기 위치 결정
- **C2:** Runtime Behavior를 이용해 초기 판단을 교정하고 workload 변화에 적응

단, Hybrid는 C1/C2의 Candidate 비교 이후 선택 가능한 Integration 방향이며 본 DP의 C1/C2 구분 자체를 흐리지 않는다.

---

# 8. DP Boundary

본 DP는 **Placement Decision의 Trigger/Strategy**를 정의한다.

- C1은 Allocation-time Initial Placement를 결정한다.
- C2는 Runtime Behavior 기반 Re-placement 필요성과 Destination Tier를 결정한다.
- 실제 Data Copy/Migration 수행은 DP4에 위임한다.
- Capacity Pressure에 따른 Eviction 대상 선정은 DP3의 책임으로 유지한다.

따라서 C2가 Migration을 결정하더라도 실제 이동 mechanism을 직접 구현하지 않는다.

```text
C2
Behavior-driven Placement Decision
      ↓
source / destination / reason
      ↓
DP4
Migration Execution
```

---

# 9. 요약

본 DP의 핵심 비교는 **Resource-centric vs Data-centric**가 아니라 **Placement Decision Timing/Trigger**이다.

> **C1 = Allocation-time, Request-driven, Rule/Policy-based Initial Placement**
>
> **C2 = Runtime, Behavior-driven, Predictive/Adaptive Re-placement**

C1은 단순성과 낮은 Runtime Overhead를 우선하고, C2는 실제 Data Behavior를 이용한 Dynamic Adaptability와 Proactive Placement를 우선한다.
