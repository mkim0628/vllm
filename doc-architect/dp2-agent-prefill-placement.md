# DP2. 이기종 메모리 환경의 Agent Prefill 실행 위치 결정 구조

## 1. DP2 정의

### DP1과 DP2의 관계

DP1에서는 Agent/LLM 실행 과정에서 생성되는 데이터를 **어느 Memory Tier에 배치할 것인가**를 결정한다.

DP2에서는 DP1에 의해 이기종 메모리에 배치된 데이터를 기반으로 **Prefill 연산을 어느 Compute Node에서 수행할 것인가**를 결정한다.

```text
                    Agent Workload
                         │
                         ▼
                Incremental Prefill
                         │
          ┌──────────────┴──────────────┐
          │                             │
          ▼                             ▼
        DP1                           DP2
   Data Placement               Compute Placement
          │                             │
          ▼                             ▼
 "KV를 어디에 둘까?"          "Prefill을 어디서 할까?"
          │                             │
          ▼                             ▼
 HBM / DRAM / CXL / HBF       P Node / D Node
          │                             │
          └──────────────┬──────────────┘
                         ▼
             Data Access / Movement
                         │
                         ▼
               Inference Performance
```

> **DP1: Data → Memory Placement**  
> **DP2: Memory Placement + Runtime State → Compute Placement**

---

# 2. 배경 / 문제 정의

## ① Agent Multi-turn 실행으로 기존 Context를 유지한 채 신규 입력이 지속적으로 추가

Agent workload는 일반적인 단일 LLM 요청과 달리 **LLM 추론 → Tool Call → Tool Result → LLM 추론** 과정이 반복된다.

이 과정에서 기존 Conversation History를 유지하면서 다음과 같은 신규 Context가 지속적으로 추가된다.

- User Input
- Tool Result
- Agent-generated Context

따라서 최초 Full Prefill 이후에는 기존 History KV를 재사용하면서 새롭게 추가된 입력에 대한 **Incremental Prefill이 반복적으로 발생**한다.

```text
User Input
    │
    ▼
  Prefill
    │
    ▼
  Decode ─────► Tool Call
                    │
                    ▼
              Tool Execution
                    │
                    ▼
                Tool Result
                    │
                    ▼
           Incremental Prefill
                    │
                    ▼
                  Decode
                    │
                   ...
```

Agent 실행이 지속되면서 History KV는 누적되고, 각 Agent Step에서 추가되는 Incremental Input의 크기는 달라질 수 있다.

↓

## ② Turn/Step별 Workload가 다양하고 History KV가 서로 다른 Memory Tier에 배치되어 Prefill 실행 위치별 Data Access/Movement Cost가 달라짐

Agent의 각 Step에서는 다음 특성이 지속적으로 변화한다.

### Agent Workload

- Incremental Input Size
- History KV Size
- Tool Result Size
- Request / Tool Type

### KV Placement

History KV는 시스템의 Memory Placement Policy에 따라 서로 다른 Memory Tier에 위치할 수 있다.

```text
                 History KV

        ┌──────────┼──────────┐
        ▼          ▼          ▼
       HBM        DRAM       CXL
        │          │          │
       ...        HBF        SSD
```

따라서 동일한 Prefill 연산이라도 **어느 Node에서 실행하는가에 따라 KV 접근 및 이동 경로가 달라진다.**

예:

```text
History KV @ D-HBM

D Node Prefill
→ Local KV Access
→ Data Movement ↓


P Node Prefill
→ KV/State Transfer 필요
→ Data Movement ↑
```

반면 History KV가 P/D가 접근 가능한 CXL Memory 등에 위치한다면 실행 위치별 Data Movement Cost 차이가 달라질 수 있다.

즉,

> **이기종 메모리 환경에서는 KV의 Memory Location이 Prefill 실행 위치의 Cost를 결정하는 핵심 요소가 됨**

↓

## ③ Agent Workload, KV Memory Placement 및 P/D Runtime State에 따라 적정 Prefill 실행 위치가 달라짐

Prefill 실행 위치는 단순히 Incremental Input Size만으로 결정하기 어렵다.

다음 세 종류의 상태를 함께 고려해야 한다.

### Workload State

- Incremental Input Size
- History KV Size
- Tool / Request Type

### Memory State

- History KV Location
- Memory Tier
- Available Bandwidth
- Data Transfer Cost

### Compute State

- P/D Node Load
- Queue Length
- Decode Interference
- Available Compute Resource

```text
          Agent Workload
               +
         KV Memory State
               +
        P/D Runtime State
               │
               ▼
        Prefill Placement
             /     \
            ▼       ▼
         P Node   D Node
```

따라서 모든 Prefill을 P Node에서 수행하는 고정 PD 분리 또는 단순한 Input-size 기반 실행 위치 결정만으로는 다양한 Agent/Memory/Runtime 상태에서 항상 효율적인 실행을 보장하기 어렵다.

또한 Scale-out 환경에서는 하나의 P/D Node 선택 문제가 아니라 **다수의 P/D Node와 연결된 이기종 Memory Resource를 고려한 Placement 문제**로 확장된다.

> **결론: Agent Workload, KV의 이기종 메모리 배치 상태 및 P/D Runtime 상태를 고려하여 Prefill 실행 위치를 동적으로 결정하는 구조 필요**

---

# 3. Target Quality Attribute

DP2에서는 다음 세 가지 Quality Attribute를 주요 설계 목표로 선정한다.

| Quality Attribute | DP2에서의 의미 |
|---|---|
| **Performance Efficiency** | KV Access/Movement, Prefill Latency, Decode Interference 및 P/D Resource Utilization을 고려하여 실행 효율 최적화 |
| **Functional Correctness** | Workload, KV Memory Placement 및 Runtime State에 적합한 Prefill 실행 위치 결정 |
| **Scalability** | P/D Node 및 Memory Resource 증가에도 Decision/State 관리 복잡도의 과도한 증가 없이 Placement 수행 |

---

# 4. 설계 쟁점

## ① Performance Efficiency

**이기종 메모리 환경에서 Agent Prefill/Decode 실행 효율 최적화를 위한 Prefill 실행 위치 결정 구조 설계**

- KV Access Cost
- KV Movement Cost
- Prefill Execution Time
- Decode Interference
- P/D Resource Utilization

등을 종합적으로 고려하여 End-to-End 실행 효율을 높일 필요가 있다.

---

## ② Functional Correctness

**Agent Workload, KV Memory Placement 및 P/D Runtime 상태에 따른 적정 Prefill 실행 위치 결정을 위한 동적 Placement 구조 설계**

동일한 Prefill Request라도 KV의 위치와 Runtime State에 따라 적정 실행 위치가 달라질 수 있으므로 변화하는 실행 조건을 정확하게 반영할 필요가 있다.

---

## ③ Scalability

**P/D Node 및 이기종 Memory Resource 확장 시 Decision·상태 관리 복잡도 최소화를 위한 확장 가능한 Prefill Placement 구조 설계**

Node 및 Memory Resource 증가에 따라 다음 비용이 증가할 수 있다.

- Runtime State Collection
- Memory State Collection
- Candidate Node 탐색
- Candidate별 Data Movement Cost 계산
- Placement Decision

따라서 Resource 증가에도 Placement Overhead가 과도하게 증가하지 않는 구조가 필요하다.

---

# 5. 설계 후보

DP2의 핵심 설계 선택은 다음과 같다.

> **Prefill 실행 위치를 Workload/Memory 특성에 대한 사전 정의 Rule로 결정할 것인가, Runtime의 실제 Data Movement/Execution Cost를 기반으로 동적으로 결정할 것인가?**

---

# 6. C1. Workload & Memory-aware Rule-based Placement

## 6.1 핵심 아이디어

Agent Workload와 KV Memory Placement를 기준으로 **사전에 정의된 Rule/Threshold를 이용하여 Prefill 실행 위치를 결정**한다.

```text
                Prefill Request
                      │
          ┌───────────┴───────────┐
          ▼                       ▼
    Workload Property        Memory Property

    ΔInput Size              KV Location
    History KV Size          Memory Tier
    Request Type             Local / Remote
          │                       │
          └───────────┬───────────┘
                      ▼
               Rule / Threshold
                      │
             ┌────────┴────────┐
             ▼                 ▼
          D Local           P Remote
```

### Rule 구성

C1의 Rule은 앞서 정의한 Workload Property(ΔInput Size, History KV Size, Request Type)와 Memory Property(KV Location = Memory Tier + Local/Remote) **각각을 조건절로 포함**시켜, Runtime State 없이 사전에 고정된 Threshold/분류 기준만으로 실행 위치를 결정한다.

#### ① ΔInput Size Rule

```text
IF ΔToken(r) ≤ T_delta
THEN InputClass = Small
ELSE
THEN InputClass = Large
```

- 예: `T_delta = 1024 tokens` (Offline Profiling으로 결정된 고정값)

#### ② History KV Size Rule

```text
IF HistoryKV(r) ≤ T_history
THEN HistoryClass = Small
ELSE
THEN HistoryClass = Large
```

- 예: `T_history = 16 GB`
- History KV가 Large인 경우, KV가 Local이 아닌 Node로 이동할 때의 Transfer Cost가 커지므로 **Memory Class가 D-Local이면 Local 유지를 우선하는 조건**(Rule R2)에 사용된다.

#### ③ Request Type Rule

```text
IF RequestType(r) ∈ { Interactive, Latency-Critical }
THEN TypeClass = Latency-Sensitive

ELIF RequestType(r) ∈ { Background, Batch-Tool-Result }
THEN TypeClass = Latency-Tolerant

ELSE
THEN TypeClass = Default
```

- Request Type은 Agent Step의 성격(예: 사용자에게 즉시 응답해야 하는 Turn vs 백그라운드로 처리 가능한 Tool 후처리)을 반영한다.

#### ④ Memory Rule (Memory Tier + Local/Remote)

```text
IF MemoryTier(r) ∈ { HBM, DRAM } AND Locality(r) == Local
THEN MemoryClass = D-Local-Fast

ELIF MemoryTier(r) == CXL AND Locality(r) == Shared
THEN MemoryClass = Shared

ELIF MemoryTier(r) == CXL AND Locality(r) == Local
THEN MemoryClass = D-Local-Slow

ELSE
THEN MemoryClass = Remote
```

- Memory Tier(HBM/DRAM/CXL/HBF/SSD)와 Local/Remote 여부를 함께 사용해 KV Location을 4가지 Class로 분류한다.

#### Combined Rule (Priority-ordered Rule Chain)

4개 Property를 단순 Table로 모두 교차시키면 조합 수가 급격히 늘어나므로, C1은 **위에서부터 순서대로 평가하고 첫 매치를 적용하는 Rule Chain**으로 구성한다.

```text
R1) IF TypeClass == Latency-Sensitive
    THEN Decision = D Local
    # 지연에 민감한 Turn은 Workload/Memory 상태와 무관하게 항상 Local 유지

R2) IF HistoryClass == Large AND MemoryClass ∈ { D-Local-Fast, D-Local-Slow }
    THEN Decision = D Local
    # 대형 History KV를 옮기는 Transfer Cost를 회피

R3) IF InputClass == Small AND MemoryClass ∈ { D-Local-Fast, D-Local-Slow, Shared }
    THEN Decision = D Local

R4) IF TypeClass == Latency-Tolerant AND MemoryClass == Shared
    THEN Decision = P Remote
    # 지연에 덜 민감한 요청은 Shared Memory를 통해 여유 P Node로 오프로드

R5) ELSE
    THEN Decision = P Remote   # Default
```

#### Pseudocode

```text
def rule_placement(r):
    input_class   = "Small" if delta_token(r) <= T_DELTA else "Large"
    history_class = "Small" if history_kv_size(r) <= T_HISTORY else "Large"
    type_class    = classify_request_type(r)   # Latency-Sensitive / Latency-Tolerant / Default
    memory_class  = classify_memory(r)          # D-Local-Fast / D-Local-Slow / Shared / Remote

    if type_class == "Latency-Sensitive":
        return D_current(r)
    if history_class == "Large" and memory_class in ("D-Local-Fast", "D-Local-Slow"):
        return D_current(r)
    if input_class == "Small" and memory_class in ("D-Local-Fast", "D-Local-Slow", "Shared"):
        return D_current(r)
    return select_p_node(r)  # 정적 규칙: Round-robin / Hash 기반 매핑
```

- 모든 Threshold(`T_DELTA`, `T_HISTORY`)와 분류 기준은 Offline Profiling 결과로 사전에 고정되며 Runtime 중에는 변경되지 않는다.
- Rule 순서(R1 → R5)는 우선순위를 의미하며, 앞선 Rule이 매치되면 이후 Rule은 평가하지 않는다.
- `select_p_node`는 P/D Load, Queue 등 Runtime State를 참조하지 않고 Round-robin, Hash 기반 정적 매핑과 같은 고정 규칙으로 Candidate P Node 중 하나를 선택한다.

### Rule 적용 예시

동일한 ΔInput Size/KV Location이라도 **History KV Size 또는 Request Type이 다르면 Decision이 달라질 수 있다.**

```text
Case A) History KV Size 차이
ΔInput = Large, KV @ D-HBM, Type = Latency-Tolerant

  History KV = Small (4 GB)
        │
        ▼
  InputClass=Large, HistoryClass=Small
  MemoryClass=D-Local-Fast, TypeClass=Latency-Tolerant
        │
        ▼
  R1~R4 불일치 → R5(Default)
        │
        ▼
      P Remote


  History KV = Large (32 GB)   ← History KV Size만 다름
        │
        ▼
  InputClass=Large, HistoryClass=Large
  MemoryClass=D-Local-Fast, TypeClass=Latency-Tolerant
        │
        ▼
  R2 매치 (HistoryClass=Large + MemoryClass=D-Local-Fast)
        │
        ▼
      D Local
```

```text
Case B) Request Type 차이
ΔInput = Large, History KV = Small, KV @ Shared CXL

  Request Type = Interactive (Latency-Sensitive)
        │
        ▼
  TypeClass=Latency-Sensitive
        │
        ▼
  R1 매치
        │
        ▼
      D Local


  Request Type = Background Tool Result (Latency-Tolerant)   ← Request Type만 다름
        │
        ▼
  InputClass=Large, HistoryClass=Small
  MemoryClass=Shared, TypeClass=Latency-Tolerant
        │
        ▼
  R1~R3 불일치 → R4 매치 (TypeClass=Latency-Tolerant + MemoryClass=Shared)
        │
        ▼
      P Remote
```

즉 C1의 Rule은 ΔInput Size와 KV Location뿐 아니라 **History KV Size, Request Type까지 조건절에 포함시켜 각각이 독립적으로 Decision에 영향을 줄 수 있는 구조**로 명세된다.

---

## 6.2 Scale-out 구조

Rule을 이용해 먼저 실행 가능한 Resource Group을 분류하고, Group 내에서 단순 Mapping을 수행한다.

```text
                Prefill Request
                      │
              Rule Classification
                      │
            ┌─────────┴─────────┐
            ▼                   ▼
        Local Group        Remote Group
            │                   │
            ▼                   ▼
        D Candidates         P Candidates
            │                   │
            └─────────┬─────────┘
                      ▼
             Simple Selection
```

모든 Node/Memory State를 지속적으로 수집하지 않아도 되므로 Node 증가에 따른 Scheduling Overhead를 제한할 수 있다.

---

## 6.3 장점

- 낮은 Placement Decision Overhead
- Runtime State Collection 최소화
- 구조 및 동작이 단순
- Offline Profiling 결과 활용 가능
- Node/Memory Resource 증가 시 비교적 높은 Scalability

## 6.4 단점

- Runtime Load 변화 반영 제한
- Rule/Threshold가 특정 HW 구성에 종속될 가능성
- Memory BW Contention 등의 동적 상태 반영 한계
- 동일 Workload/Memory Placement에서도 Runtime 상황에 따라 최적 위치가 달라지는 경우 대응 어려움

---

# 7. C2. Runtime Cost-aware Dynamic Placement

## 7.1 핵심 아이디어

Agent Workload, KV Memory Placement와 현재 Compute/Memory Runtime State를 기반으로 **각 Candidate Node에서 Prefill을 수행했을 때의 예상 Cost를 계산하여 실행 위치를 결정**한다.

```text
                      Prefill Request
                            │
       ┌────────────────────┼────────────────────┐
       ▼                    ▼                    ▼
  Workload State       Memory State        Compute State

  ΔInput Size          KV Location         P/D Load
  History KV Size      Memory Tier         Queue Length
  Request Type         Memory BW           Interference
                       Transfer Cost
       │                    │                    │
       └────────────────────┼────────────────────┘
                            ▼
                        Cost Model
                            │
             ┌──────────────┼──────────────┐
             ▼              ▼              ▼
          Cost@D1        Cost@P1        Cost@PN
             │              │              │
             └──────────────┼──────────────┘
                            ▼
                      Minimum Cost
                        Candidate
                            │
                            ▼
                     Prefill Execute
```

---

## 7.2 Cost Model

Candidate Node $n$의 Cost를 다음과 같이 구성할 수 있다.

$$
C(n) = C_{data}(n) + C_{queue}(n) + C_{prefill}(n) + C_{interference}(n)
$$

### Data Access / Movement Cost

$$
C_{data}(n) = f(\text{KV Location},\ \text{Memory Tier},\ \text{BW},\ \text{Transfer Path})
$$

KV가 Candidate Node에서 Local한 경우 작아지고, Remote Memory 또는 다른 Node에 존재하는 경우 증가한다.

### Queue Cost

$$
C_{queue}(n) = f(\text{Node Load},\ \text{Queue Length})
$$

### Prefill Execution Cost

$$
C_{prefill}(n) = f(\Delta \text{Token},\ \text{Compute Capability})
$$

### Interference Cost

$$
C_{interference}(n) = f(\text{Prefill/Decode Co-location},\ \text{Current Workload})
$$

Prefill과 Decode가 같은 Node(GPU)에서 동시에 실행될 때 발생하는 **Compute/Memory Bandwidth 경쟁**을 의미한다.

- Prefill은 짧은 시간에 많은 GPU Compute와 HBM Bandwidth를 소비하는 Compute-bound 연산이다.
- Decode는 Token 단위로 반복 실행되며 Latency(TPOT, Time-Per-Output-Token)에 민감한 연산이다.

두 연산이 같은 Node에 함께 스케줄되면 Prefill Batch가 GPU를 점유하는 동안 진행 중인 Decode Step이 지연되어 Decode Latency가 급증할 수 있다.

예:

```text
D1에서 Decode 진행 중 (Active Decode Requests: 20)
        │
        ▼
D1에서 Local Prefill 추가 실행
        │
        ▼
Prefill Batch가 GPU Compute 점유
        │
        ▼
진행 중인 20개 Decode Step 지연
        │
        ▼
Decode TPOT 증가 (예: 30ms → 90ms)
        │
        ▼
C_interference(D1) ↑
```

반면 P Node가 Prefill 전용으로 분리되어 있고 해당 시점에 Decode Workload가 없다면 `C_interference(P) ≈ 0`에 가깝다.

즉, 동일한 Prefill 연산이라도 **Decode를 함께 수행 중인 Node에서 실행하면 Interference Cost가 커지고, Prefill 전용 Node에서 실행하면 Interference Cost가 낮아진다.**

최종적으로:

$$
Node^{*} = \arg\min_{n \in Candidates} C(n)
$$

을 선택한다.

---

# 8. C2 Scale-out 구조

Scale-out 환경에서 모든 Node/Memory Resource의 Cost를 매번 계산하면 Scheduling Overhead가 커질 수 있다.

따라서 **Candidate Filtering → Cost Evaluation**의 2단계 구조를 적용할 수 있다.

```text
            All P/D Nodes
                  │
                  ▼
         Candidate Filtering
                  │
       ┌──────────┼──────────┐
       │          │          │
   KV Local    Low Load    Compatible
       │          │          │
       └──────────┼──────────┘
                  ▼
         Candidate Subset
                  │
                  ▼
          Cost Evaluation
                  │
                  ▼
           Execution Node
```

이를 통해 Cost-aware Placement의 실행 품질을 유지하면서 Scale-out에 따른 Decision Overhead 증가를 제한한다.

---

## 8.1 장점

- Runtime State(P/D Load, Queue, Interference)를 반영하여 상황에 맞는 실행 위치 선택 가능
- KV Memory Placement가 동일해도 Runtime 변화에 따라 Decision을 동적으로 조정 (Scenario B 참고)
- Data Movement Cost와 Compute/Interference Cost를 함께 고려하여 End-to-End 실행 효율 최적화 기대
- Decode Interference를 Cost Model에 명시적으로 반영하여 Prefill/Decode Co-location에 의한 성능 저하를 회피 가능
- KV Memory Tier/위치 변화(예: HBM vs Shared CXL)에 따른 Cost 차이를 정량적으로 반영

## 8.2 단점

- 모든 Candidate Node에 대해 Runtime State(Load, Queue, Memory BW 등)를 지속적으로 수집해야 하므로 Monitoring/State Collection Overhead 발생
- Node/Memory Resource 증가 시 Candidate 수와 Cost 계산량이 함께 늘어나 Scalability에서 C1 대비 불리
- Cost Model의 $f(\cdot)$ 함수와 가중치를 정확히 튜닝해야 하며, Cost Estimation Error가 Placement 품질에 직접 영향
- Candidate Filtering을 적용해도 Filtering 자체의 비용과 정확도 사이 Trade-off가 존재
- C1 대비 Decision 절차(Cost 계산 → 비교)가 복잡해 Decision Overhead가 높고, 이는 Latency-critical한 경로에서 추가 지연 요소가 될 수 있음

---

# 9. C1 / C2 동작 비교 예시

동일한 Agent 요청을 가정한다.

```text
Incremental Input = 512 Tokens
History KV = D-side CXL Memory
```

### Case A

```text
D Load = Low
P Load = High
CXL → D Access Cost = Low
```

C1:

```text
Workload + KV Location Rule
          ↓
       D Local
```

C2:

```text
Data Cost(D)        Low
Queue Cost(D)       Low
Interference(D)     Low

          ↓

       D Local
```

두 구조가 동일한 결정을 내릴 수 있다.

---

### Case B

동일한 Workload/KV Placement에서 Runtime State만 변경한다.

```text
D Load = High
P Load = Low
CXL → P Access Cost = Acceptable
```

C1:

```text
Workload + KV Location 동일
          ↓
       D Local
```

C2:

```text
D Queue/Interference ↑
P Queue ↓
P Data Cost = Acceptable

          ↓
       P Remote
```

즉 C2는 **Memory Placement가 동일하더라도 Runtime 상태에 따라 실행 위치를 변경할 수 있다.**

---

# 10. 예상 Trade-off

| QA | C1. Workload & Memory-aware Rule-based | C2. Runtime Cost-aware Dynamic |
|---|---|---|
| **Performance Efficiency** | ○ Decision Overhead가 작으나 Runtime Contention/Load 변화 반영 제한 | **◎ Data Movement + Compute + Interference를 함께 고려하여 높은 실행 효율 기대** |
| **Functional Correctness** | ○ Profiling 범위 내에서는 안정적이나 예상하지 못한 Runtime 상태에서 적정 Placement와 불일치 가능 | **◎ 현재 Memory/Compute 상태를 반영하여 상황에 적합한 Placement 가능. 단, Cost Estimation Error 영향 존재** |
| **Scalability** | **◎ State Collection 및 Candidate Evaluation이 제한적이어서 Resource 증가에 유리** | △ Node/Memory 증가 시 State Collection 및 Cost Evaluation 증가 |

---

# 11. 후보별 유리한 환경

## C1이 유리한 경우

- Workload/Memory 특성과 적정 실행 위치 간 관계가 명확
- P/D Load 변화가 상대적으로 작음
- 많은 P/D Node 및 Memory Resource가 존재
- Scheduling Overhead 최소화가 중요

### 핵심 강점

> **Low-overhead & Scalable Placement**

---

## C2가 유리한 경우

- Agent workload variation이 큼
- P/D Load가 동적으로 변화
- KV가 다양한 Memory Tier에 배치
- Memory BW/Transfer Contention 변화가 큼
- Data Movement와 Compute Placement를 함께 최적화해야 함

### 핵심 강점

> **Runtime-adaptive & Data-location-aware Placement**

---

# 12. DP1–DP2 전체 구조

```text
                    Agent Runtime
                         │
                         ▼
                Prefill / Decode
                         │
            ┌────────────┴────────────┐
            │                         │
            ▼                         ▼

          DP1                       DP2
   Data Placement             Compute Placement

 "어디에 저장할까?"          "어디서 실행할까?"

            │                         ▲
            ▼                         │
     ┌──────────────┐                 │
     │ Memory State │─────────────────┘
     ├──────────────┤
     │ HBM          │
     │ DRAM         │
     │ CXL Memory   │
     │ HBF / SSD    │
     └──────────────┘
            │
            │
            └────────────┐
                         ▼
                 Data Movement
                       +
                 Compute Cost
                         │
                         ▼
                Inference Performance
```

DP1과 DP2는 독립적인 최적화 문제가 아니라 연결된 문제이다.

> **DP1은 데이터 특성과 Memory Resource 특성을 이용하여 KV의 Memory Placement를 결정하고, DP2는 그 Placement 결과를 실행 시점의 Workload 및 Compute State와 결합하여 Prefill의 Compute Placement를 결정한다.**

---

# 13. DP2 요약

## 문제 정의

1. **Agent는 LLM–Tool 실행을 반복하면서 기존 Context를 유지한 채 User Input, Tool Result 등 신규 입력을 지속적으로 추가하여 Incremental Prefill이 반복적으로 발생**
2. **Turn/Step별 Workload가 다양하고 History KV가 서로 다른 Memory Tier에 배치될 수 있어 Prefill 실행 위치별 Data Access/Movement Cost가 달라짐**
3. **Agent Workload, KV Memory Placement 및 P/D Runtime 상태에 따라 Prefill을 어느 Node에서 수행하는 것이 유리한지가 달라짐**

→ **이기종 메모리의 KV 배치 상태와 Runtime 상태를 고려하여 Agent Prefill 실행 위치를 동적으로 결정하는 구조 필요**

## Target QA

- **Performance Efficiency**
- **Functional Correctness**
- **Scalability**

## 설계 쟁점

1. **이기종 메모리 환경에서 Agent Prefill/Decode 실행 효율 최적화를 위한 Prefill 실행 위치 결정 구조 설계**
2. **Agent Workload, KV Memory Placement 및 P/D Runtime 상태에 따른 적정 Prefill 실행 위치 결정을 위한 동적 Placement 구조 설계**
3. **P/D Node 및 이기종 Memory Resource 확장 시 Decision·상태 관리 복잡도 최소화를 위한 확장 가능한 Prefill Placement 구조 설계**

## 후보 설계안

### C1. Workload & Memory-aware Rule-based Placement

> **Workload/KV Memory 특성 → Rule/Threshold → 실행 Node 결정**

- 낮은 Decision Overhead
- 단순한 구조
- 높은 Scalability
- Runtime 변화 반영 한계

### C2. Runtime Cost-aware Dynamic Placement

> **Workload + KV Memory State + Compute Runtime State → Candidate Cost 계산 → 실행 Node 결정**

- Data Movement와 Compute 상태를 함께 고려
- 높은 Runtime Adaptability
- 실행 효율 및 Placement 정확성 향상 기대
- Scale-out 시 State Collection 및 Cost Evaluation Overhead 증가

## 핵심 Trade-off

> **C1: 낮은 Decision Overhead 및 높은 Scalability ↔ Runtime 변화 대응 한계**

> **C2: 높은 실행 효율 및 상황별 Placement 정확성 ↔ Scale-out에 따른 State/Decision 복잡도 증가**
