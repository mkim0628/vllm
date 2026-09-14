# DP3. Long Context를 위한 KV Cache Eviction 구조

## 1. 배경 / 문제 정의

### ① Agent의 Multi-turn 실행 일반화에 따라 누적 Context 증가

- Agent workload는 단일 `Prefill → Decode`로 종료되는 일반적인 요청과 달리, **LLM 추론 → Tool Call → Tool Result → LLM 추론** 과정을 반복
- 각 Turn에서 이전 Conversation History를 유지하면서 User Input, Tool Result 등 새로운 Context가 추가됨
- Turn이 반복될수록 하나의 Agent Session에서 유지해야 하는 **누적 Context Length가 지속적으로 증가**

```text
Turn 1
[ Initial Context ]

Turn 2
[ Initial Context | Tool Result ]

Turn 3
[ Initial Context | Tool Result | New Context ]

                       ...

Turn N
[ ─────────────── Accumulated Long Context ─────────────── ]
```

**→ Multi-turn Agent workload의 일반화에 따라 Long Context 처리가 중요한 Serving 요구사항으로 부상**

---

### ② Long Context 환경에서는 KV Cache 증가로 상위 Memory의 Capacity Pressure 심화

- Transformer는 이전 Context에 대한 Attention 연산을 위해 Token별 KV Cache를 유지
- 따라서 Context Length 증가에 따라 **유지해야 하는 KV Cache 크기도 지속적으로 증가**
- 전체 KV Cache를 제한된 용량의 HBM에 유지하기 어려우며, 다수 Request가 동시에 수행되는 환경에서는 `Long Context × Concurrency`로 Capacity Pressure가 더욱 심화
- HBM Capacity 부족은 신규 Request 수용 제한 및 KV의 하위 Memory 이동/복구 증가로 이어질 수 있음

```text
Context Length ↑
      │
      ▼
KV Cache Size ↑
      │
      │ + Concurrency ↑
      ▼
HBM Capacity Pressure ↑
      │
      ▼
Available HBM Capacity ↓
KV Movement / Restore ↑
```

**→ Long Context Serving을 위해 제한된 상위 Memory에서 유지해야 하는 KV Working Set을 줄일 필요**

---

### ③ 모든 KV가 Attention 결과에 동일하게 기여하지 않으므로 중요도가 낮은 KV의 선별적 Eviction 가능

- Long Context를 구성하는 모든 Token/KV가 향후 Attention 결과에 동일한 수준으로 기여하지 않음
- Query에 높은 Attention을 받는 일부 KV가 결과 생성에 상대적으로 중요하며, 낮은 Attention을 받는 KV는 영향이 제한적일 수 있음
- 따라서 중요도가 낮은 KV를 DRAM/CXL Memory/SSD 등의 **Low Tier로 우선 Eviction**하여 HBM의 KV Working Set을 축소할 수 있음

```text
Long Context KV

[K1][K2][K3][K4][K5][K6] ... [Kn]
 │       │           │
High    Low         Low
Importance

             │
             │ Importance-based Eviction
             ▼

HBM
[K1][K3][K6] ...

Low Tier
[K2][K4][K5] ...

        ↓

HBM KV Working Set ↓
Memory / I/O Cost ↓
Attention Processing Cost ↓
```

- 단, 실제로 중요한 KV를 잘못 Eviction할 경우 모델 출력 품질이 저하될 수 있음
- 따라서 단순한 용량 확보가 아니라 **Accuracy 영향을 최소화하면서 최대한 많은 KV를 Eviction하는 구조**가 필요

### 문제 정의

> **Long Context 환경에서 Accuracy 영향을 최소화하면서 HBM Capacity 및 KV 처리 비용을 절감하기 위해, Attention 중요도에 기반하여 Eviction 대상 KV를 결정하는 구조 필요**

---

# 2. 설계 쟁점

## Query-dependent KV Importance를 언제 판단할 것인가?

Attention 기반으로 중요도가 낮은 KV를 Eviction하기 위해서는 **어떤 KV가 중요하고 중요하지 않은지 판단**해야 함.

그러나 동일한 Context라도 실제 입력 Query에 따라 Attention Pattern이 달라질 수 있음.

```text
                    Same Context
                        │
            ┌───────────┴───────────┐
            ▼                       ▼
         Query A                  Query B

K1  █████████               K1  ██
K2  █                       K2  ████████
K3  █████                   K3  ███
K4  ██                      K4  ███████

→ K1 중요                  → K2/K4 중요
```

따라서 정확한 Importance 판단을 위해서는 실제 Query의 Attention을 확인하는 것이 유리하지만, Query 도착 이후에 판단할 경우 선제적으로 KV Working Set을 줄이기 어려움.

반대로 대표 Query를 이용해 Importance를 미리 판단하면 공격적인 Eviction이 가능하지만, 실제 Query와 Attention Pattern이 다를 경우 중요한 KV가 Eviction될 수 있음.

### 설계 쟁점

> **Long Context의 KV Working Set을 효율적으로 축소하기 위해, Query-dependent KV Importance를 어느 시점에 평가하여 Eviction에 반영할 것인가?**

```text
                 KV Importance 판단
                        │
            ┌───────────┴───────────┐
            ▼                       ▼
      C1. Offline               C2. Online
        Eviction                  Eviction

 Representative Query          Actual Query
        │                         │
        ▼                         ▼
 사전 Importance 판단       Runtime Importance 판단
```

---

# 3. 후보 설계안

## C1. Offline Attention-based KV Cache Eviction

### 개념

워크로드별 **Representative Query를 사전에 선정**하고 Context와 Attention 연산을 수행하여 KV Importance를 미리 산출하는 구조.

Serving 이전에 여러 Representative Query에서 반복적으로 낮은 Attention Score를 갖는 KV를 식별하고 이를 Low Tier로 선제적으로 Eviction함.

### 동작 구조

```text
                   [ Offline Phase ]

Workload / Dataset
       │
       ▼
Representative Query Selection
 Q1 / Q2 / Q3 / ... / Qn
       │
       └────────────┐
                    ▼
                Context KV
                    │
                    ▼
             Attention Compute
                    │
                    ▼
          Attention Score Aggregation
                    │
                    ▼
             KV Importance Profile
                    │
             ┌──────┴──────┐
             ▼             ▼
          Important     Unimportant
             KV             KV
             │              │
             ▼              ▼
           Retain       Eviction Candidate


                   [ Online Phase ]

Actual Query
     │
     ▼
Precomputed KV Importance
     │
     ▼
KV Working Set
```

### 특징

- Actual Query 도착 이전에 KV Importance 판단 가능
- Representative Query들에서 공통적으로 Importance가 낮은 KV를 사전 식별
- 중요도가 낮다고 판단된 KV를 선제적으로 Low Tier로 이동 가능
- Serving 시점에는 이미 축소된 KV Working Set을 사용 가능

### 장점

**높은 압축률**

- Actual Query와 무관하게 중요도가 낮은 KV를 선제적으로 Eviction 가능
- HBM에 유지해야 하는 KV Working Set을 크게 축소 가능

**Latency 절감**

- Attention 대상 KV 감소
- Runtime Importance 판단을 위한 추가 연산 최소화

**I/O 절감**

- HBM에 유지되는 KV 양 감소
- 상위 Memory에서 처리해야 하는 데이터 양 감소

### 단점

**Accuracy 상대적 열세**

Representative Query의 Attention Pattern과 Actual Query의 Attention Pattern이 다를 수 있음.

```text
Representative Query

K1 ████████
K2 █████
K3 █
K4 █

→ K3/K4 Eviction


Actual Query

K1 ██
K2 ███
K3 ████████  ← 실제 Query에서는 중요
K4 █

→ 필요한 K3가 이미 Low Tier에 존재
```

즉 Offline Importance가 실제 Query의 Importance를 정확하게 반영하지 못할 경우 중요한 KV를 Eviction하여 Accuracy가 저하될 수 있음.

---

# 4. C2. Online Attention-based KV Cache Eviction

### 개념

Actual Query가 입력된 이후 **Query와 Context 간 실제 Attention 결과를 이용하여 KV Importance를 판단**하는 구조.

현재 Query에 대한 Attention Score가 낮은 KV를 식별하여 Low Tier로 Eviction함.

### 동작 구조

```text
                  [ Online Serving ]

Actual Query
     │
     ▼
Context KV
     │
     ▼
Attention Compute
     │
     ▼
Query-specific Attention Score
     │
     ▼
KV Importance Decision
     │
  ┌──┴──────────────┐
  ▼                 ▼
Important        Unimportant
   KV                KV
   │                 │
   ▼                 ▼
Retain         Eviction Candidate
```

### 특징

- 실제 Query가 입력된 이후 KV Importance 판단
- Query-specific Attention Pattern을 직접 반영
- 동일 Context라도 Query별로 서로 다른 KV Working Set 구성 가능

### 장점

**높은 Accuracy**

- Representative Query가 아닌 Actual Query의 Attention 결과를 사용
- 현재 Query에 중요한 KV가 잘못 Eviction될 가능성을 줄일 수 있음
- Query별 Attention Pattern 변화에 대응 가능

### 단점

**압축률 상대적 열세**

- Actual Query가 도착하기 전에는 해당 Query에 대한 Importance를 알 수 없음
- Offline 방식처럼 사전에 공격적으로 KV Working Set을 축소하기 어려움
- Query 변화에 대비해 더 많은 KV를 유지해야 할 가능성이 있음

**Latency 절감률 상대적 열세**

- Query 입력 이후 Importance 판단 과정 필요
- C1 대비 더 큰 KV Working Set을 대상으로 처리할 가능성 존재

**I/O 절감률 상대적 열세**

- C1보다 많은 KV를 유지해야 하므로 HBM/Low Tier 간 데이터 처리량 절감 효과가 상대적으로 작음

---

# 5. C1 / C2 Trade-off

| 구분 | C1. Offline Eviction | C2. Online Eviction |
|---|---|---|
| Importance 판단 시점 | Serving 이전 | Actual Query 입력 이후 |
| Importance 판단 기준 | Representative Query | Actual Query |
| Query Specificity | 낮음 | **높음** |
| Eviction 성향 | **선제적 / 공격적** | Query-specific / 상대적으로 보수적 |
| Compression Ratio | **높음** | 상대적 열세 |
| Accuracy | 상대적 열세 | **높음** |
| HBM Capacity 절감 | **큼** | 상대적으로 작음 |
| I/O 절감 | **큼** | 상대적으로 작음 |
| Latency 절감 | **큼** | 상대적으로 작음 |
| Runtime Overhead | **낮음** | 상대적으로 높음 |
| 주요 Risk | Representative Query와 Actual Query 간 mismatch | 선제적 KV 축소 제한 |

### 핵심 Trade-off

```text
C1. Offline                           C2. Online

Representative Query                  Actual Query
        │                                  │
        ▼                                  ▼
Generalized Importance             Query-specific Importance
        │                                  │
        ▼                                  ▼
Aggressive Eviction               Conservative Eviction
        │                                  │
        ▼                                  ▼
Compression ↑↑                       Accuracy ↑↑
HBM Saving ↑↑                        Query Adaptability ↑
I/O Saving ↑↑
Latency ↓↓

              ◀──── Trade-off ────▶

        System Efficiency
               vs.
         Model Accuracy
```

> **C1은 Representative Query를 기반으로 KV를 선제적으로 축소하여 Capacity·Latency·I/O 효율을 높이는 반면, C2는 Actual Query의 Attention을 반영하여 Accuracy를 높이는 대신 KV 축소 효과가 상대적으로 제한됨.**

---

# 6. DP1과의 연결

## DP1 Placement 이후의 Capacity Management 구조

DP1과 DP3는 KV Cache를 대상으로 하지만 서로 다른 의사결정을 담당함.

- **DP1:** KV를 **어느 Memory Tier에 배치할 것인가?**
- **DP3:** 상위 Memory Capacity가 부족할 때 **어떤 KV를 우선적으로 회수할 것인가?**

```text
                 KV Cache
                    │
                    ▼
        DP1. Placement Decision
        "어디에 배치할 것인가?"
                    │
         ┌──────────┴──────────┐
         ▼                     ▼
 C1. Memory State       C2. Data Property
      based                  based
         │                     │
         └──────────┬──────────┘
                    ▼
             HBM / Low Tier
                    │
                    │ Long Context
                    ▼
          HBM Capacity Pressure
                    │
                    ▼
         DP3. Eviction Decision
      "무엇을 우선 회수할 것인가?"
                    │
                    ▼
          Attention Importance
```

### DP1-C1을 선택하는 경우

DP1-C1은 **Memory Capacity/BW/Load 등 현재 Memory State를 기반으로 Target Memory를 결정**함.

현재 Resource 변화에는 즉각적으로 대응할 수 있지만, HBM Capacity 확보가 필요할 때 **기존 KV 중 모델 결과에 상대적으로 덜 중요한 KV가 무엇인지 판단하지 않음**.

**→ DP3에서 Attention Importance를 추가적으로 고려하여 Eviction 대상을 선정함으로써 DP1-C1의 KV Importance 판단 한계를 보완**

```text
DP1-C1
Memory State
Capacity / BW / Load
       │
       ▼
Placement
       │
       ▼
HBM Pressure
       │
       ▼
DP3
Attention Importance
       │
       ▼
Eviction Target
```

### DP1-C2를 선택하는 경우

DP1-C2는 **Access Pattern, Hotness, Lifetime 등 Data Property를 기반으로 Target Memory를 결정​**함.

이를 통해 KV가 향후 다시 사용될 가능성을 Placement에 반영할 수 있지만, **재사용 가능성이 높다는 것이 실제 Query의 Attention에서 중요하다는 것을 의미하지는 않음**.

예를 들어 자주 접근되는 KV라도 특정 Query에서는 Attention Score가 낮을 수 있으며, 반대로 접근 빈도가 낮았던 KV가 특정 Query에서는 중요할 수 있음.

**→ DP3에서 Query에 대한 Attention Importance를 추가적으로 고려하여 Eviction 대상을 선정**

```text
DP1-C2                           DP3

"다시 접근할 것인가?"           "결과에 중요한가?"

Access Pattern                  Attention Score
Hotness             ≠          Query Relevance
Lifetime

      │                              │
      ▼                              ▼
Placement                       Eviction
```

따라서 DP1의 어느 후보를 선택하더라도 DP3는 독립적인 역할을 가짐.

> **DP1은 Memory/Data 특성을 기반으로 KV의 Placement를 결정하고, DP3는 Long Context에 따른 Capacity Pressure 발생 시 Attention Importance를 기반으로 회수할 KV를 결정함으로써 상위 Memory의 Working Set을 관리한다.**

---

# 7. 전체 Runtime 관점

DP1과 DP3를 결합하면 KV Cache의 **Placement → Residency → Reclamation**을 포괄하는 구조로 확장 가능함.

```text
                 New KV
                   │
                   ▼
        ┌─────────────────────┐
        │ DP1. KV Placement   │
        │                     │
        │ Which Memory Tier?  │
        └──────────┬──────────┘
                   │
                   ▼
          ┌─────────────────┐
          │ HBM / DRAM /    │
          │ CXL / SSD       │
          └────────┬────────┘
                   │
           Long Context /
           Capacity Pressure
                   │
                   ▼
        ┌─────────────────────┐
        │ DP3. KV Eviction    │
        │                     │
        │ Which KV to evict?  │
        └──────────┬──────────┘
                   │
                   ▼
             Low Memory Tier
```

DP1에서 어떤 Placement 구조를 선택하더라도 Long Context로 Working Set 자체가 증가하는 문제는 남으며, DP3가 이를 **Attention Importance 기반의 선택적 Eviction**으로 보완함.

---

# 8. 평가 방향

C1/C2의 핵심 Trade-off인 **System Efficiency ↔ Accuracy**를 아래 3개 Quality Attribute 관점에서 정량적으로 평가함.

| Quality Attribute | DP3 Metric | 의미 |
|---|---|---|
| **Performance Efficiency → Time Behaviour** | **TTFT** | KV Cache eviction을 통해 Long-context Attention의 실행 시간을 얼마나 단축하는가 |
| **Performance Efficiency → Resource Utilization** | **Capacity** | KV Cache가 차지하는 메모리 용량을 얼마나 절감하여 제한된 메모리를 효율적으로 활용하는가 |
| **Functional Suitability → Functional Correctness** | **Accuracy** | KV eviction 이후에도 모델 출력의 정확도를 얼마나 유지하는가 |

### TTFT (Performance Efficiency → Time Behaviour)

- TTFT
- Attention Execution Time
- TPOT / End-to-End Latency (Time Behaviour 보조 지표)

### Capacity (Performance Efficiency → Resource Utilization)

- KV Compression Ratio
- HBM KV Footprint
- HBM Peak Occupancy
- Low Tier Eviction Bytes
- HBM ↔ DRAM/CXL/SSD Transfer Bytes, KV Eviction/Restore Bytes, Restore 횟수 (Resource Utilization 보조 지표)

### Accuracy (Functional Suitability → Functional Correctness)

- Fully Retained KV 대비 Task Accuracy
- Eviction 전/후 Output Quality 변화
- 중요 KV 오분류율
- Representative Query와 Actual Query 간 Importance 일치율

### 주요 비교

```text
Baseline
No Eviction / Full KV

        vs.

C1
Offline Attention-based Eviction

        vs.

C2
Online Attention-based Eviction
```

**검증 질문**

> 동일한 Accuracy Budget에서 C1/C2가 각각 어느 수준의 KV Compression 및 Latency/I/O 절감을 달성할 수 있는가?

또는 반대 관점에서,

> 동일한 KV Compression Ratio에서 C1/C2가 각각 어느 수준의 Accuracy를 유지할 수 있는가?

이를 통해 **Offline의 System Efficiency 우위와 Online의 Accuracy 우위 간 Trade-off를 정량적으로 비교**함.