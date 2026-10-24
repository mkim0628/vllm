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

# 2. 회수 방식과 결정 시점

§1은 회수 동작을 "Low Tier로 Eviction"이라고만 서술했다. 그러나 그 표현은 **서로 다른 두 동작**을 가리키며, 둘은 회수하는 자원도 지불하는 대가도 다르다. 후보 구조를 논하기 전에 이 구분과 결정이 발생하는 시점을 고정한다.

## 2.1 Demote와 Drop은 같은 결정이 아니다

| | **Demote (강등)** | **Drop (폐기)** |
|---|---|---|
| 동작 | KV를 하위 Memory Tier로 이동, 내용 보존 | KV를 어느 계층에도 남기지 않고 버림 |
| 회수되는 것 | **HBM 용량만.** 시스템 전체 점유 바이트는 그대로 | **전체 용량.** 그 KV가 차지하던 모든 바이트 |
| Accuracy | **무손실 — 비트 단위로 동일한 Attention 결과** | **손실 발생** — 버린 KV는 Attention에 기여하지 못함 |
| 지불하는 대가 | 재접근 시 하위 계층 대역폭·지연, 또는 in-place Attention 비용 | 되돌릴 수 없음. 필요해지면 **재계산(Prefill)** 뿐 |
| 되돌리기 | Restore 또는 in-place 연산으로 가능 | 불가 |
| **결정 주체** | **DP1** — 어느 계층에 둘 것인가 | **DP3** — 무엇을 버릴 것인가 |

> **이 구분이 본 DP의 성립 근거다.** Attention Importance가 Accuracy와 교환되는 것은 **Drop에서만** 성립한다. Demote는 KV를 버리지 않으므로 Importance가 낮은 KV를 내려도 Attention 결과가 달라지지 않는다 — 달라지는 것은 그 KV에 다시 접근할 때의 속도뿐이고, **그것은 재접근 시점과 대역폭의 문제이지 중요도의 문제가 아니다.**
>
> 따라서 **Demote만 수행하는 구조에서는 Attention Importance를 쓸 이유가 없다.** 재접근 시점·확률로 충분하며 그것은 DP1의 배치 기준(설계 문서 §5.1)이다. §6의 "System Efficiency ↔ Model Accuracy" Trade-off는 **회수 동작에 Drop이 포함될 때에만** 성립한다.

**용어 고정.** 이하 본 문서에서 **Eviction은 Drop을 가리킨다.** Demote는 DP1의 배치 결정으로 다루며, DP3는 "DP1이 배치를 마친 뒤에도 용량이 모자랄 때 무엇을 버릴 것인가"를 결정한다.

## 2.2 Drop이 필요해지는 조건 — 본 DP의 성립 범위

Demote로 충분하면 Drop은 순손실이다. Drop이 값을 하는 것은 **Demote가 부족하거나 값을 하지 못할 때**이며, 그 조건은 셋이다.

| 조건 | 내용 | Drop이 필요한 이유 |
|---|---|---|
| **(a) 전체 용량 포화** | 하위 계층까지 모두 찼다 | Demote할 자리가 없다. 용량을 만드는 유일한 수단이 Drop |
| **(b) 재접근 비용이 SLO를 깬다** | 하위 계층에 두면 다시 쓸 때 TTFT/TPOT 예산을 넘는다 | 보관해도 쓰지 못한다. 보관 비용만 지불하는 셈 |
| **(c) 이동 비용이 보관 이득을 넘는다** | 잔여 수명이 짧거나 왕복이 잦아 대역폭·Endurance 소모가 크다 | 내렸다 올리는 비용 > 버리고 재계산하는 비용 |

> **본 DP의 이득은 DP1 구성의 함수다.** DP1 설계 문서 §4가 정의한 **Attention 오프로드(Mode C)** 가 성립하는 구성에서는 연산형 메모리로 강등해도 KV를 그 자리에서 쓸 수 있으므로 **(b)가 크게 완화된다.** 즉 **연산형 메모리(Custom HBM 노드 · CXL-PNM)의 용량이 클수록 Drop의 필요성은 줄어든다.**
>
> 따라서 본 DP의 후보 비교는 **연산형 계층의 용량을 Sweep 축에 넣지 않으면 성립하지 않는다**(§9.6). 그 축을 고정한 채 얻은 "C1이 C2보다 낫다"는 결론은 그 구성에서만 유효하다.

## 2.3 결정 시점 — 축이 둘이다

회수에는 **언제 판단하는가**와 **언제 실행하는가**가 있고, 둘은 독립이다. §4의 C1/C2는 **평가 시점**의 축이며, 실행 시점은 두 후보에 공통으로 걸린다.

```text
        평가 시점 (Importance를 언제 산출하는가)   ← §4의 C1 / C2 축
                          │
                          │  (독립)
                          │
        실행 시점 (회수를 언제 수행하는가)         ← 아래 E1~E4, 두 후보 공통
```

### 실행 시점 후보

| | 계기 | 무엇을 회수할 수 있는가 | 문제 |
|---|---|---|---|
| **E1. Watermark** | HBM 점유가 임계치를 넘음 | 전체 세션의 KV | **사후 대응.** 임계치에 닿은 시점에는 이미 지연이 발생 |
| **E2. Admission** | 신규 Request 수용 직전 | 기존 세션의 KV | 선제적이나, 수용 경로에 회수 지연이 직렬로 붙음 |
| **E3. Decode Step 경계** | 매 N Step | 활성 세션 포함 전체 | **활성 Decode의 Critical Path 위에 있다.** 예산이 가장 작다 |
| **E4. 비활성 전환** | 턴 종료·선점·세션 종료 | 해당 세션의 KV | **DP1 결정점 B와 같은 시점·같은 대상** — §2.4 |

> **E3는 C2(Online)에만 실재하는 선택지다.** C2는 Actual Query의 Attention 결과를 봐야 판단하므로 평가 자체가 Decode/Prefill 경로 안에서 일어난다. **이것이 C2의 Runtime Overhead가 C1보다 크다는 §6 주장의 구조적 근거**이며, 그 크기를 재는 것이 §9.3의 M-C3다.
>
> **반대로 C1(Offline)은 E1·E2·E4를 자유롭게 쓸 수 있다.** Importance가 이미 산출되어 있으므로 회수 실행이 임의 시점에 가능하다. **C1의 "선제적·공격적" 성향은 평가 방식이 아니라 이 자유도에서 나온다.**

**실행 시점을 고정하지 않고 두 후보를 비교하면 안 된다.** C1을 E2로, C2를 E3로 돌린 뒤 "C1이 TTFT가 낫다"고 보고하면 그 차이가 평가 방식 때문인지 실행 시점 때문인지 분리되지 않는다. §9.6의 보고 원칙에 이를 고정 규칙으로 둔다.

## 2.4 DP1 결정점 B와 겹치는 지점

E4는 DP1 설계 문서 §1의 **결정점 B(비활성 전환)** 와 시점도 대상도 같다. 같은 순간에 같은 세션의 KV를 두고 두 정책이 서로 다른 기준으로 결정을 내리므로, **순서를 고정하지 않으면 모순이 생긴다.**

```text
   비활성 전환 시점

        ├── DP1: "이 KV를 어느 계층에 둘 것인가"      (재접근 시점·확률 기준)
        └── DP3: "이 KV를 버릴 것인가"                (Attention Importance 기준)
```

**고정 규칙 — DP1이 먼저, DP3는 그 결과가 용량 제약을 만족하지 못할 때만 개입한다.**

```text
   비활성 전환
        │
        ▼
   DP1 Placement 결정  ──► 배치 가능한 계층이 있는가?
        │                        │
        │                       Yes ──► 배치 완료. DP3 개입 없음
        │                        │
        │                        No (§2.2의 (a)(b)(c) 중 하나)
        ▼                        │
   DP3 Drop 결정  ◄──────────────┘
        │
        ▼
   Importance 하위 KV 폐기 → 확보된 용량으로 DP1 재시도
```

**순서를 반대로 두면 안 된다.** DP3가 먼저 버리면 DP1이 배치할 대상이 이미 사라져 있고, "버리지 않아도 강등만으로 해결됐을 KV"를 버리게 된다 — §2.1대로 그 손실은 되돌릴 수 없다. **DP3는 DP1의 실패 처리 경로이지 병렬 경로가 아니다.**

> **Prefix Cache 후보 Block은 세션 경계를 넘는다.** DP1 설계 문서 §1의 비활성 전환 계기 중 "재사용분 보존"으로 남은 Block은 **다른 Request가 Hit할 대상**이므로, 이를 Drop하면 손실이 해당 세션에 국한되지 않는다. Attention Importance는 **자기 세션의 Query에 대해 산출된 값**이며 다른 세션의 Query에 대한 중요도가 아니다. 공유 Block에 대한 Drop 판정 근거를 §4의 두 후보 모두 갖고 있지 않으므로, **본 DP의 범위에서는 공유 Block을 Drop 대상에서 제외한다**(§9.5의 M-R2로 그 영향을 관측한다).

---

# 3. 설계 쟁점

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

# 4. 후보 설계안

> **두 후보는 §2.3의 두 축 중 "평가 시점"만 다르다.** 실행 시점(E1~E4)은 후보의 정의에 포함되지 않으며 두 후보에 공통으로 걸린다. 또한 이하에서 "Low Tier로 Eviction"이라고 쓴 동작은 §2.1의 용어 고정에 따라 **Drop(폐기)** 을 가리킨다 — 하위 계층으로의 단순 이동(Demote)은 DP1의 결정이며 Accuracy와 교환되지 않는다.

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

# 5. C2. Online Attention-based KV Cache Eviction

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

# 6. C1 / C2 Trade-off

> **아래 표는 회수 동작이 Drop일 때의 가설이다**(§2.1). Demote만 수행하는 구조에서는 두 후보의 Accuracy가 모두 B0와 동일하므로 "Accuracy" 행 자체가 성립하지 않고, 남는 차이는 판단 비용(M-C3)뿐이다. **표의 각 행은 §9의 어느 Metric으로 검증되는지가 정해져 있어야 하며, 검증 전까지는 정성적 가설로 읽는다.**

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

# 7. DP1과의 연결

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

# 8. 전체 Runtime 관점

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

# 9. QA별 평가 Metric

§6의 Trade-off 표는 **정성적 가설**이다. QA마다 **무엇을 재면 그 가설이 검증/반증되는지**를 먼저 고정한다. 실제 수치는 Prototype 실측으로 채우며 **본 문서에 가정값을 기재하지 않는다.**

## 9.1 Metric 선정 요약

| QA | 하위 특성 | Metric | 증거 종류 |
|---|---|---|---|
| **Performance Efficiency** | (종합) | **M-C1 SLO-제약 Goodput** — 주 지표 | 측정 |
| | Time Behaviour | M-C2 TTFT / M-C3 회수 결정 Latency | 측정 (**발생 빈도가 달라 각각 측정**) |
| | Resource Utilization | M-C4 HBM KV Footprint & Peak Occupancy / M-C5 Drop·Demote 분해 | 측정 |
| **Functional Suitability** | Functional Correctness | **M-A1 Task Accuracy** — 주 지표 | 측정 |
| | | M-A2 중요 KV 오분류율 (FNR) / M-A3 Representative–Actual 일치율 | 측정 |
| (공통 Risk) | | M-R1 재계산 비용 / M-R2 Prefix Cache 오염 | 측정 |

**Performance Efficiency와 Functional Correctness를 하나의 점수로 합치지 않는다.** 가중치를 사람이 정하는 순간 결론이 그 가중치의 함수가 되며, §9.6의 이중 보고(iso-accuracy / iso-compression)가 그 가중치 선택을 불필요하게 만든다.

## 9.2 먼저 고정할 것 — 대조군 셋

§2.1의 구분에 따라 **대조군이 셋**이며, **어느 것을 기준선으로 쓰는지가 결론을 지배한다.**

```text
B0. No Reclamation      전량 HBM 유지. Drop 없음, Demote 없음
                        → Accuracy의 상한. 단 Long Context에서는
                          용량 제약으로 실행 자체가 불가할 수 있다

B1. Demote-only         DP1 배치 정책만 적용. Drop 없음
                        → **본 DP의 진짜 대조군.** Accuracy는 B0과 동일(§2.1)하고
                          HBM 용량은 이미 회수되어 있다

C1 / C2                 B1 + Attention Importance 기반 Drop
```

> **반드시 B1을 기준선으로 보고한다.** B0 대비로 보고하면 **DP1의 Demote가 만든 용량 이득이 DP3의 성과로 집계된다.** C1/C2가 주장할 수 있는 것은 **B1이 회수하지 못한 잔여 용량**뿐이며, 그 크기가 §2.2의 (a)(b)(c)가 실제로 발생하는 범위를 말해준다.
>
> **B1이 이미 용량 제약을 만족한다면 그 구성에서 DP3는 불필요하다.** 이는 실패가 아니라 결과이며, §10의 조건부 선정에 "조건 X 범위에서는 DP3 불필요"로 기술되어야 한다.

**B0가 실행 불가능한 구성에서는 Accuracy 기준선을 어떻게 잡는가.** B0를 돌릴 수 없으면 Accuracy의 상한을 모르므로 M-A1을 해석할 수 없다. 이 경우 **Context 길이를 줄여 B0가 성립하는 축소 구성에서 Accuracy 상한을 먼저 확보**하고, 본 구성의 결과는 그 축소 구성과의 외삽임을 명시한다. 외삽 없이 절대 Accuracy를 주장하지 않는다.

## 9.3 Performance Efficiency

### M-C1. SLO-제약 Goodput (주 지표)

```text
Goodput = SLO를 만족한 Request의 출력 Token 수 / 실행 시간   [tokens/s]

SLO: TTFT ≤ T_ttft  AND  TPOT ≤ T_tpot
```

**왜 Throughput인가.** DP1 설계 문서 §11.2와 같은 이유다 — 본 DP의 본질이 **Capacity ↔ Accuracy·재계산 비용의 교환**이므로, Latency 단독 지표는 "아무것도 버리지 마라"고만 답하고 회수를 하는 이유 자체를 볼 수 없다. **SLO 제약을 반드시 건다** — 제약 없는 raw Throughput은 모든 Request를 느리게 만들고 Batch만 키워도 올라가므로 "전부 버리기"가 최적해가 된다.

**정규화:** B1(Demote-only) = 1.0. **Scheduler 고정 규칙은 §9.6.1을 따른다.**

> **Accuracy가 떨어진 Request를 Goodput의 분자에 넣으면 안 된다.** SLO에 **Accuracy 하한을 포함**시키거나, 포함시키지 않는다면 M-A1과 **반드시 쌍으로만 보고**한다. Goodput 단독 보고는 "많이 버릴수록 좋다"로 읽힌다.

### M-C2. TTFT

```text
C1 (Offline)  TTFT = Incremental Prefill 연산 시간
                     + (Drop된 KV가 필요하면) 재계산 시간        ← M-R1
              ※ Importance 판단은 Serving 이전에 끝나 있다

C2 (Online)   TTFT = Attention 수행 → Importance 산출 → 회수 결정 시간   ← M-C3
                     + Incremental Prefill 연산 시간
              ※ 판단이 경로 안에 있다
```

**측정 구분:** Drop된 KV에 접근한 Request와 접근하지 않은 Request를 **분리 보고한다.** 합치면 Drop의 대가가 평균에 희석되어 보이지 않는다. p50 / p99 병기.

### M-C3. 회수 결정 Latency

```text
Decision Cost = Importance 산출 + 회수 대상 선정에 든 시간 / 결정 건수
```

- **C1은 Online Phase의 이 값이 0에 가깝다** — Offline에서 이미 산출했으므로 조회 비용만 남는다. 대신 **Offline Phase 비용을 별도로 보고**한다(워크로드가 바뀔 때마다 재실행해야 하므로 무시할 수 없다).
- **C2는 이 값이 Critical Path 위에 있다**(§2.3 E3). **DP1과 결정적으로 다른 점**이다 — DP1의 배치 결정은 비활성 구간에 있어 여유가 있었지만, 본 DP의 C2는 그렇지 않다.
- **M-C1에 되먹여 합산한다.** 독립 보고만으로는 "C2의 판단 비용이 언제부터 회수 이득을 상쇄하는가"라는 Crossover 질문에 답할 수 없다.
- **정규화 기준을 B1로 둔다.** C1 = 1.0으로 정규화하면 C1 자신의 Offline 비용이 감춰진다.

### M-C4. HBM KV Footprint & Peak Occupancy

```text
HBM KV Footprint     = Step별 HBM 상주 KV bytes (평균 / 최대)
HBM Peak Occupancy   = max(HBM 사용량) / HBM Capacity
KV Compression Ratio = 1 − (회수 후 KV bytes / 회수 전 KV bytes)
```

**DP1 설계 문서 §11의 M-P6와 공유하는 지표다.** 같은 정의로 측정해야 두 DP의 결과를 겹쳐 읽을 수 있다.

> **Compression Ratio를 단독 성과로 보고하지 않는다.** 분자에 Drop과 Demote가 섞이면 §2.1의 구분이 사라진다. **반드시 M-C5로 분해해서 낸다.**

### M-C5. Drop / Demote 분해

```text
Drop Bytes    = 폐기한 KV bytes (되돌릴 수 없음)
Demote Bytes  = 하위 계층으로 내린 KV bytes (DP1이 수행)

Drop 비중 = Drop Bytes / (Drop Bytes + Demote Bytes)
```

**본 DP가 실제로 한 일의 크기가 이 값이다.** Drop 비중이 낮은데 Goodput이 올랐다면 그 이득은 DP1의 것이다. **Drop 비중과 Accuracy 손실(M-A1)을 같은 그래프의 두 축으로 보고한다** — 이 한 장이 본 DP의 Trade-off 전부다.

**보조:** 계층별 회수 바이트 분포, 세션당 Drop 횟수 분포, Max Concurrent Sessions / 유효 Batch Size.

## 9.4 Functional Correctness

### M-A1. Task Accuracy (주 지표)

```text
Accuracy Retention = Task Accuracy(후보) / Task Accuracy(B0)
```

- **Task별로 분리 보고한다. 단일 평균을 내지 않는다.** Long-context Task는 필요한 KV의 분포가 서로 크게 다르다 — 요약은 전역 정보를, 검색형(needle-in-haystack)은 국소 정보를 요구하므로, **평균을 내면 후보의 실패 지점이 정확히 지워진다.** C1의 Representative Query mismatch 위험은 검색형에서 가장 크게 나타날 것으로 예상되며, 그것이 §6 가설의 핵심 검증 대상이다.
- **Drop이 0인 실행에서 Accuracy가 B0와 다르면 측정 파이프라인 오류다**(§2.1). 이를 **정합성 점검(sanity check)으로 먼저 돌린다.** 통과하지 못한 실행은 비교 불가로 표시한다.
- **Accuracy를 Drop된 바이트에 귀속시킨다** — 같은 Accuracy 손실이라도 적게 버리고 많이 잃었다면 판정 품질이 나쁜 것이다.

### M-A2. 중요 KV 오분류율 (False Negative Rate)

```text
FNR = 실제 Query에서 Attention Score 상위 k에 들었으나 Drop된 KV 수
      / 상위 k에 든 KV 수
```

**M-A1이 "얼마나 잃었는가"를 말한다면 이 지표는 "왜 잃었는가"를 말한다.** Accuracy 손실이 판정 실패에서 왔는지(FNR 높음), 아니면 상위 k 밖 KV도 결과에 기여하기 때문인지(FNR 낮은데 Accuracy 하락)를 가른다. **후자라면 "상위 k만 남기면 된다"는 §1 ③의 전제 자체가 반증된다** — 이것이 본 DP의 가장 근본적인 가정이며 반드시 확인해야 한다.

`k`는 **실행 전에 고정하고 사후에 바꾸지 않는다.** 여러 k에 대해 곡선으로 보고한다.

### M-A3. Representative–Actual Importance 일치율

```text
일치율 = Representative Query 기준 상위 k ∩ Actual Query 기준 상위 k  /  k
```

- **C1 고유의 Risk 지표다. C2는 정의상 1.0**(Actual Query를 직접 쓰므로)이며, 이는 검증 가능한 정합성 점검이기도 하다.
- **워크로드 다양성을 Sweep 축에 넣는다.** Representative Query가 실제 분포를 대표하는 정도가 이 값을 결정하므로, 단일 워크로드에서 얻은 일치율은 C1의 성능이 아니라 그 워크로드의 동질성을 잰 것이다.
- **Representative Query 선정 방법과 개수를 결과와 함께 명시한다.** 명시하지 않으면 C1의 결과가 재현되지 않는다.

## 9.5 공통 Risk 지표

### M-R1. 재계산(Recompute) 비용

```text
Recompute Cost = Σ over (Drop된 KV에 재접근한 사건) Prefill 재연산 시간
재접근률       = Drop한 KV 중 이후 다시 필요해진 비율 (세션 수 기준 / 바이트 기준)
```

**Drop의 비용은 Accuracy 손실만이 아니다.** 버린 KV가 다시 필요해지면 재계산해야 하고, 그 연산은 **GPU에서 일어난다**(DP1 설계 문서 §4.2 — Prefill은 GPU 고정). 즉 **Drop은 메모리 압력을 GPU 압력으로 전환하는 것**이며, 그 전환율이 이 지표다. M-C1에 합산한다.

> Long Context에서 재계산 비용은 Context 길이에 대해 선형 이상으로 커지므로, **재접근률이 낮아도 총 비용이 클 수 있다.** 총 시간과 사건 횟수를 함께 낸다.

### M-R2. Prefix Cache 오염

```text
Prefix Cache Hit Rate 변화 = HitRate(후보) − HitRate(B1)
타 세션 영향 = Drop으로 인해 Hit에 실패한 Request 수
```

§2.4에서 공유 Block을 Drop 대상에서 제외했으므로 **이 지표는 그 제외 규칙이 실제로 지켜졌는지를 확인하는 안전장치**다. 0이 아니면 구현이 규칙을 위반한 것이며, 해당 실행은 비교 불가로 표시한다.

## 9.6 보고 원칙

- **기준선은 B1(Demote-only) = 1.0.** B0는 Accuracy 상한으로만 쓴다(§9.2).
- **실행 시점(§2.3 E1~E4)을 두 후보에 동일하게 고정한다.** 고정하지 않으면 평가 방식의 차이와 실행 시점의 차이가 분리되지 않는다. 실행 시점을 바꾼 결과는 **별도 조건**으로 보고한다.
- **이중 보고를 원칙으로 한다.** 단일 동작점 비교는 동작점 선택에 취약하다.

```text
  (1) Iso-accuracy   : 동일 Accuracy Retention에서 각 후보의 Compression / Goodput
  (2) Iso-compression: 동일 Compression Ratio에서 각 후보의 Accuracy / Goodput
```

두 방향의 결론이 다르면 **그 사실 자체가 결과**이며 §10의 조건부 선정에 들어간다.

- **Sweep 필수** — 후보의 우열이 바뀔 수 있는 파라미터를 훑고 **교차 지점을 Band로** 보고한다.

| Sweep 축 | 왜 필요한가 |
|---|---|
| **연산형 계층(Custom HBM · CXL-PNM)의 용량** | **가장 중요한 축.** §2.2대로 이 용량이 커지면 Demote만으로 해결되어 DP3의 이득이 사라진다 |
| **Context 길이** | 본 DP의 전제. 짧으면 §2.2의 (a)가 발생하지 않는다 |
| 동시 세션 수 (Concurrency) | Context 길이와 함께 전체 용량 압력을 정한다 |
| **상위 k (Importance 임계)** | M-A2의 축. 단일 k의 결과로 후보를 판정하지 않는다 |
| **워크로드 다양성 / Representative Query 수** | M-A3의 축. C1의 유불리를 직접 정한다 |
| Task 유형 (요약 / 검색형 / 추론형) | M-A1대로 필요 KV 분포가 다르다. 평균 금지 |
| 실행 시점 (E1~E4) | 별도 조건으로 훑는다 |
| Drop 비율 상한 | 동작점을 만드는 축. iso-accuracy / iso-compression 곡선이 여기서 나온다 |

- **통계적 판정 규칙을 사전 고정** — 동일 seed 쌍으로 반복하고 **신뢰구간이 0을 지나면 "차이 없음"** 으로 판정한다. 점 추정의 부호로 판정하지 않으며 사후에 규칙을 바꾸지 않는다. **Accuracy는 분산이 크므로 반복 횟수를 Performance 지표보다 크게 잡는다.**
- **DP1 Configuration 병기** — §2.2대로 본 DP의 이득은 DP1의 메모리 구성에 의존한다. DP1 설계 문서 §3.4의 Configuration을 결과와 함께 명시하지 않으면 시나리오 간 비교가 성립하지 않는다.
- **개수 편중 보정** — 모든 비율 지표를 **세션 수 기준과 바이트 기준 양쪽으로** 보고한다.
- **무결성 표시** — M-R2 ≠ 0인 실행, M-A1 정합성 점검에 실패한 실행은 **비교 불가**로 표시한다.

### 9.6.1 Scheduler 고정 규칙

Goodput을 주 지표로 쓰는 이상 Scheduler가 결과에 개입한다. **DP1 설계 문서 §11.6.1의 규칙을 그대로 따르며**, 본 DP에 고유한 항목만 추가한다.

| 항목 | 왜 기록해야 하는가 |
|---|---|
| Preemption 방식 (Recompute / Swap) | **본 DP와 직접 경쟁한다.** Recompute 기반 선점은 그 자체가 Drop + 재계산이므로, Scheduler가 이미 하는 일을 DP3의 성과로 집계할 위험이 있다. **하나를 고정하고 다른 하나는 별도 조건으로 보고한다** |
| Prefix Caching on/off | M-R2의 전제. off면 §2.4의 공유 Block 제외 규칙 자체가 작동하지 않는다 |
| 최대 동시 시퀀스 수 / Batch Token 예산 | 용량 압력의 크기를 직접 정한다 |
| Chunked Prefill on/off 및 chunk 크기 | M-R1의 재계산이 한 번에 발생하는지 나뉘는지를 바꾼다 |

> **Recompute 기반 선점과의 구분이 본 DP에서 가장 큰 교란 요인이다.** 둘 다 "KV를 버리고 나중에 재계산한다"는 동작이며, 차이는 **버릴 대상을 Attention Importance로 고르는가 아니면 Request 단위로 통째로 고르는가**뿐이다. **Recompute 선점을 켠 채 B1과 비교하면 본 DP의 고유 기여가 측정되지 않는다.**

---

# 10. 후보 선정 (본 문서 범위 밖)

DP1·DP2 설계 문서와 동일한 원칙을 따른다. **본 문서는 Design Point의 정의와 후보 구조 제시까지를 범위로 하며 후보를 선정하지 않는다.** 선정 근거를 먼저 고정하면 이후 측정이 그 결론을 확인하는 방향으로 편향된다.

선정은 §9의 Metric으로 얻은 정량 결과를 근거로 별도 문서에서 다루며, **"조건 X 범위에서는 C_i, 조건 Y 범위에서는 C_j"** 형태의 조건부 선정 + 유효 범위로 기술한다.

**본 DP의 선정 문서가 반드시 답해야 하는 것**

| 질문 | 근거 Metric |
|---|---|
| **그 구성에서 Drop이 필요하기는 한가** — B1(Demote-only)만으로 용량 제약이 해소되는 범위는 어디까지인가 | §9.2 B1, M-C5 |
| 연산형 계층 용량이 얼마를 넘으면 본 DP가 불필요해지는가 | M-C1, M-C5 (연산형 계층 용량 Sweep) |
| 상위 k만 남겨도 되는가 — §1 ③의 전제가 실제로 성립하는가 | M-A2 (FNR과 Accuracy의 관계) |
| C1의 Representative Query mismatch가 실제로 문제가 되는 워크로드 다양성 수준은 | M-A3, M-A1 (Task별) |
| C2의 판단 비용이 회수 이득을 상쇄하는 지점은 | M-C3을 M-C1에 합산한 Crossover |
| Recompute 기반 선점 대비 고유 기여가 있는가 | §9.6.1의 고정 조건별 M-C1 |

> **첫 번째 질문이 나머지에 선행한다.** B1이 이미 충분한 구성에서 C1/C2를 비교하는 것은 필요 없는 결정을 최적화하는 것이다.
