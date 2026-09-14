# DP2. C1 / C2 동작 시나리오 비교

## 1. 비교 목적

DP2에서는 Agent Multi-turn 실행 과정에서 발생하는 Incremental Prefill에 대해 다음 실행 위치 중 적정 위치를 결정한다.

- **Local Execution:** 현재 Request의 Decode를 담당하는 D Node에서 Prefill 수행
- **Remote Execution:** Prefill 전용 P Node에서 Prefill 수행

Scale-out 환경에서 Request `r`의 Candidate는 다음과 같이 정의한다.

```text
Candidates(r) = { D_current(r) } ∪ P_eligible
```

- `D_current(r)`: 해당 Request의 Decode를 담당하는 Current D Node
- `P_eligible`: 해당 Prefill을 수행할 수 있는 Prefill Node 집합

두 후보 구조의 핵심 차이는 **Prefill 실행 위치를 결정할 때 Runtime State를 동적으로 반영하는지 여부**이다.

### C1. Workload & Memory-aware Rule-based Placement

> **Workload/KV Memory 특성 → Rule/Threshold → 실행 위치 결정**

### C2. Runtime Cost-aware Dynamic Placement

> **Workload + KV Memory State + Compute Runtime State → Candidate Cost 비교 → 실행 위치 결정**

---

# 2. 공통 환경

Agent가 Tool을 호출한 뒤 Tool Result가 반환되어 Incremental Prefill이 발생한 상황을 가정한다.

```text
Agent Request A

Current Decode Node : D1
History KV          : 8 GB
KV Location         : D1-side CXL Memory
Incremental Input   : Tool Result 512 tokens

Eligible P Nodes    : P1, P2
```

C1과 C2가 Placement Decision에 사용하는 정보는 다음과 같다.

```text
C1
Workload + Memory Property
──────────────────────────
ΔInput = 512
KV Size = 8 GB
KV Location = D1-CXL
        │
        ▼
      Rule


C2
Workload + Memory + Runtime
───────────────────────────
ΔInput = 512
KV Size = 8 GB
KV Location = D1-CXL
P/D Load
Queue
Memory BW
Transfer Cost
        │
        ▼
   Cost Model
```

---

# 3. Scenario 1. D1이 여유로운 일반적인 상황

## 3.1 Runtime State

```text
                    KV @ D1-side CXL
                           │
                           ▼
                     ┌──────────┐
                     │    D1    │
                     │ Load 20% │
                     └──────────┘

          P1                              P2
       Load 50%                        Load 60%
```

## 3.2 C1 동작

사전에 Profiling된 Rule을 다음과 같이 가정한다.

```text
ΔInput ≤ 512
+
KV @ D-side

       ↓

Local Prefill
```

따라서:

```text
512 Tokens
+ KV @ D1-side
      │
      ▼
   Rule Match
      │
      ▼
 D1 Local Prefill
      │
      ▼
    Decode
```

**Decision: D1 Local Prefill**

## 3.3 C2 동작

C2는 각 Candidate의 Runtime Cost를 비교한다.

```text
D1 Local

Data Access       Low
Queue             Low
Interference      Low
────────────────────
Total Cost        3


P1 Remote

Data Movement     High
Queue             Medium
────────────────────
Total Cost        8


P2 Remote

Data Movement     High
Queue             Medium
────────────────────
Total Cost        9
```

Cost 관계:

```text
Cost(D1) < Cost(P1) < Cost(P2)
```

**Decision: D1 Local Prefill**

## 3.4 결과

```text
C1 → D1 Local
C2 → D1 Local
```

D1이 여유롭고 History KV의 Locality를 활용할 수 있는 일반적인 상황에서는 두 구조가 동일한 결정을 내릴 수 있다.

---

# 4. Scenario 2. D1 Decode Load가 급격히 증가한 상황

Agent Workload와 KV Placement는 Scenario 1과 동일하지만 Runtime State만 변경된 상황을 가정한다.

## 4.1 Runtime State

```text
                    KV @ D1-side CXL
                           │
                           ▼
                     ┌──────────┐
                     │    D1    │
                     │ Load 95% │ ◀ Decode Requests 집중
                     └──────────┘

          P1                              P2
       Load 10%                        Load 50%
```

다음 정보는 Scenario 1과 동일하다.

```text
ΔInput      = 512 tokens
History KV  = 8 GB
KV Location = D1-side CXL
```

변경된 것은 **P/D Runtime State**이다.

## 4.2 C1 동작

```text
ΔInput = 512
KV = 8 GB
KV @ D1-side CXL

       │
       ▼

이전과 동일한 Rule

       │
       ▼

 D1 Local Prefill
```

C1은 현재 D1의 Load 증가를 Placement의 주요 동적 입력으로 사용하지 않으므로 동일한 Rule에 따라 D1을 선택한다.

**Decision: D1 Local Prefill**

예상 결과:

```text
             D1
              │
       ┌──────┴──────┐
       ▼             ▼
    Prefill        Decode
       │             │
       └──────┬──────┘
              ▼
      Resource Contention
              │
              ▼
     Decode Interference ↑
```

## 4.3 C2 동작

C2는 변경된 Runtime State를 Cost Model에 반영한다.

```text
D1 Local

Data Access       Low
Queue             HIGH
Interference      HIGH
────────────────────
Total Cost        12


P1 Remote

Data Movement     Medium
Queue             LOW
Interference      Low
────────────────────
Total Cost        6


P2 Remote

Data Movement     Medium
Queue             Medium
────────────────────
Total Cost        9
```

Cost 관계:

```text
Cost(P1) < Cost(P2) < Cost(D1)
```

**Decision: P1 Remote Prefill**

```text
          Incremental Prefill
                  │
                  ▼
                 P1
                  │
             Prefill 수행
                  │
                  ▼
             Sync / Return
                  │
                  ▼
                 D1
                  │
                  ▼
                Decode
```

## 4.4 결과

```text
                Same Workload
                Same KV Placement
                       │
             Runtime State 변화
                       │
             ┌─────────┴─────────┐
             ▼                   ▼

            C1                  C2
       Rule-based           Cost-aware
             │                   │
             ▼                   ▼
         D1 Local             P1 Remote
```

> **C1은 Workload/KV 특성이 동일하면 동일한 결정을 유지하는 반면, C2는 Runtime State 변화에 따라 실행 위치를 변경할 수 있다.**

---

# 5. Scenario 3. KV Memory Placement에 따라 실행 위치가 달라지는 상황

Scenario 3에서는 **이기종 메모리 환경이 Compute Placement에 미치는 영향**을 비교한다.

공통 조건:

```text
Incremental Input = 512 tokens

D1 Load = 90%
P1 Load = 10%
```

Agent Workload와 Compute State는 동일하게 유지하고 **History KV의 Memory Placement만 변경**한다.

---

# 6. Scenario 3-A. History KV @ D1-HBM

```text
              History KV
                @ D1-HBM
                    │
                    ▼
                   D1
                Load 90%

        P1
      Load 10%
```

### D1 Local Prefill

```text
History KV
 @ D1-HBM
     │
     ▼
 D1 Prefill
     │
     ▼
 D1 Decode
```

KV가 Local HBM에 존재하므로 별도의 KV Transfer가 필요하지 않는다.

### P1 Remote Prefill

```text
History KV
 @ D1-HBM
     │
     │ Data Transfer
     ▼
    P1
     │
     ▼
  Prefill
     │
     ▼
Sync / Return
     │
     ▼
    D1
     │
     ▼
  Decode
```

예상 Cost:

```text
D1 Local

Data Cost          0
Queue/Interference 8
────────────────────
Total              8


P1 Remote

Data Cost          7
Queue              1
────────────────────
Total              8+
```

따라서 높은 D1 Load에도 불구하고 **KV Locality의 이점 때문에 D1 Local을 유지하는 것이 유리할 수 있다.**

---

# 7. Scenario 3-B. History KV @ Shared CXL Memory

```text
                  History KV
                  @ Shared CXL
                   /        \
                  /          \
                 ▼            ▼
                D1            P1
             Load 90%      Load 10%
```

P/D Node 모두 CXL Memory의 KV에 접근할 수 있는 시스템을 가정하면 P1에서 Prefill을 수행하기 위한 Data Movement Cost가 상대적으로 감소할 수 있다.

```text
D1 Local

Data Cost          2
Queue/Interference 8
────────────────────
Total             10


P1 Remote

Data Cost          3
Queue              1
────────────────────
Total              4
```

Cost 관계:

```text
Cost(P1) < Cost(D1)
```

**Decision: P1 Remote Prefill**

---

# 8. 이기종 메모리에 따른 Compute Placement 변화

```text
                   Same Agent Workload
                   Same Compute State
                           │
                           ▼
                   KV Memory Placement
                           │
              ┌────────────┴────────────┐
              ▼                         ▼

         KV @ D1-HBM             KV @ Shared CXL
              │                         │
              ▼                         ▼
       Data Movement ↑             Remote Access
        for P Remote                Cost ↓
              │                         │
              ▼                         ▼
          D1 Local                  P1 Remote
```

> **동일한 Agent Workload 및 P/D Runtime 상태에서도 KV가 어느 Memory Tier에 배치되어 있는지에 따라 적정 Prefill 실행 위치가 달라질 수 있다.**

이는 DP1의 **Data Placement 결과가 DP2의 Compute Placement Decision에 직접적인 영향을 줄 수 있음**을 의미한다.

---

# 9. C1 / C2 핵심 동작 차이

| Decision Information | C1. Workload & Memory-aware Rule | C2. Runtime Cost-aware Dynamic |
|---|---:|---:|
| Incremental Input Size | ✓ | ✓ |
| History KV Size | ✓ | ✓ |
| KV Location / Memory Tier | ✓ | ✓ |
| P/D Runtime Load | 제한적 / 미반영 | **✓** |
| Queue State | 제한적 / 미반영 | **✓** |
| Memory BW / Contention | 제한적 / 미반영 | **✓** |
| Transfer Cost 변화 | Static Rule로 근사 | **✓ Dynamic Evaluation** |
| Decision 방식 | **Condition → Rule Match** | **Candidate → Cost Comparison** |
| 동일 Workload/KV 조건 | 대부분 동일 Decision | Runtime State에 따라 Decision 변경 가능 |

---

# 10. 대표 Scenario

```text
              Agent Incremental Prefill
                ΔInput = 512 tokens
                       │
                       ▼
              History KV @ CXL
                       │
             ┌─────────┴─────────┐
             │                   │

            C1                  C2
       Rule-based           Cost-aware
             │                   │
             │             Runtime State
             │             D1 Load = 95%
             │             P1 Load = 10%
             │                   │
             ▼                   ▼
        Rule: Local       Cost(D1) > Cost(P1)
             │                   │
             ▼                   ▼
         D1 Prefill           P1 Prefill
             │                   │
             ▼                   ▼
    Decode Interference       D1 Decode
             │
             ▼
 Potential Performance
        Degradation
```

### C1

> **Workload/KV 특성에 대한 사전 정의 Rule을 기반으로 낮은 Overhead로 Placement 수행**

### C2

> **Workload/KV 특성과 현재 Memory/Compute Runtime State를 함께 고려하여 Candidate별 Cost를 비교하고 Placement 수행**

---

# 11. DP1–DP2 관점의 의미

```text
                  DP1
           Data Placement
                 │
                 ▼
        History KV Location
       HBM / DRAM / CXL / ...
                 │
                 ▼
                  DP2
         Compute Placement
                 │
            ┌────┴────┐
            ▼         ▼
         D Local    P Remote
```

> **DP1의 Memory Placement 결과가 Prefill 실행 위치별 Data Access/Movement Cost를 결정하고, DP2는 이를 Agent Workload 및 Runtime State와 결합하여 Compute Placement를 결정한다.**

따라서 DP2는 단순한 P/D Load Balancing 문제가 아니라,

> **이기종 메모리에 배치된 KV의 Data Locality/Movement Cost와 Compute Runtime State를 함께 고려하는 Prefill Compute Placement 문제**

로 정의할 수 있다.
