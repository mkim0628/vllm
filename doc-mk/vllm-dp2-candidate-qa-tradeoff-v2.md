# DP2 Candidate QA / Trade-off Evaluation

> DP2: Compute-Capable Memory Abstraction
>
> Design question: **How should the runtime represent and resolve the relationship between data location and compute capability?**

## 1. Candidate Summary

### Candidate 1 — Memory-Coupled Compute

> **MemoryResource가 Compute capability와 execution path를 함께 소유하여, 짧고 예측 가능한 Compute dispatch 경로를 제공하는 구조.**

```text
Block
  ↓
MemoryResource
  ├── supported_ops
  └── execute_op()
```

Location과 Compute capability의 binding이 MemoryResource 내부에 존재한다.

### Candidate 2 — Decoupled Memory / Compute

> **MemoryResource와 ComputeResource를 분리하고 Runtime이 topology/binding을 통해 적절한 Compute Resource를 선택하는 구조.**

```text
Block
  ↓
MemoryResource
  ↓
Topology / Resource Binding
  ↓
ComputeResource candidates
  ↓
Planner
  ↓
Execute
```

Location과 Compute capability의 binding을 Runtime-level layer에서 관리한다.

---

# 2. QA Evaluation

별점은 **3점 만점**이며, 동일한 HW/workload를 기준으로 구조적인 상대 평가를 의미한다.

| QA | Candidate 1 | Candidate 2 | 핵심 비교 |
|---|:---:|:---:|---|
| **Runtime Compute Efficiency** | ★★★ | ★★☆ | 짧은 dispatch path vs 추가 binding/planning |
| **Compute Resource Utilization** | ★★☆ | ★★★ | 고정 capability vs 여러 Compute Resource 선택 |
| **Memory–Compute Flexibility** | ★★☆ | ★★★ | 강한 coupling vs 독립 resource binding |
| **Maintainability & Extensibility** | ★★☆ | ★★★ | 단순한 통합 vs 독립적인 확장 |

---

## 3. QA 상세 평가

### 3.1 Runtime Compute Efficiency

**질문:** Compute operation을 얼마나 낮은 runtime overhead로 실행할 수 있는가?

#### Candidate 1 — ★★★

```text
Block
 ↓
Memory ID
 ↓
MemoryResource
 ↓
Capability
 ↓
execute_op()
```

- Location lookup과 capability lookup이 동일 Resource abstraction 안에서 해결된다.
- 별도의 Resource Binding resolution이나 candidate planning이 필요하지 않다.
- Compute dispatch path가 짧고 예측 가능하다.

#### Candidate 2 — ★★☆

```text
Block
 ↓
MemoryResource
 ↓
Topology / Binding
 ↓
ComputeResource
 ↓
Capability filtering
 ↓
Planner
 ↓
Execute
```

- Memory → Compute 관계를 resolve해야 한다.
- 여러 Compute Resource가 연결된 경우 candidate filtering과 selection이 필요하다.
- 대신 이 추가 overhead를 통해 더 유연한 Compute selection이 가능하다.

**Trade-off:** Low dispatch overhead / predictability ↔ dynamic selection flexibility

---

### 3.2 Compute Resource Utilization

**질문:** 가용한 Compute Resource를 얼마나 효율적으로 활용할 수 있는가?

#### Candidate 1 — ★★☆

MemoryResource가 자신의 Compute capability를 소유하므로 단순하고 빠르지만, Memory와 Compute의 관계가 강하게 결합된다.

예:

```text
CXL-PNM MemoryResource
 └── supported_ops = {GEMM, Reduce}
```

여러 Compute Resource를 Runtime이 비교하여 선택하는 구조에는 상대적으로 불리하다.

#### Candidate 2 — ★★★

Topology/Binding을 통해 하나의 Memory에 여러 Compute Resource를 연결할 수 있다.

```text
CXL Memory
 ├── PNM0 : {GEMM, Reduce}
 ├── PNM1 : {GEMM}
 └── GPU0 : {GEMM, GEMV, ...}
```

Runtime이 capability, locality, cost 등의 policy를 기준으로 선택할 수 있다.

**Trade-off:** Fixed/simple execution ↔ broader resource utilization

---

### 3.3 Memory–Compute Flexibility

**질문:** Memory와 Compute의 다양한 조합 및 동적 binding을 얼마나 지원할 수 있는가?

#### Candidate 1 — ★★☆

```text
MemoryResource
 └── Compute capability
```

Memory와 Compute가 하나의 abstraction에 결합되어 있어 PNM/PIM처럼 강하게 결합된 HW에는 자연스럽지만, 다양한 조합을 표현할수록 Resource abstraction의 coupling이 커질 수 있다.

#### Candidate 2 — ★★★

```text
MemoryResource ──┐
                 ├── Resource Binding
ComputeResource ─┘
```

Memory와 Compute를 독립적으로 관리하고 topology에 따라 관계를 구성할 수 있다.

예:

```text
CXL-PNM → PNM0
```

에서

```text
CXL-PNM → {PNM0, PNM1}
```

와 같은 확장이 자연스럽다.

**Trade-off:** Tight HW coupling ↔ flexible Memory–Compute composition

---

### 3.4 Maintainability & Extensibility

**질문:** 새로운 Memory type 또는 Compute capability 추가 시 기존 abstraction 변경을 얼마나 최소화할 수 있는가?

#### Candidate 1 — ★★☆

장점은 구조가 단순하다는 것이지만, Compute capability가 다양해질수록 MemoryResource가 allocation, memory operation, capability, execution까지 많은 책임을 가지게 된다.

#### Candidate 2 — ★★★

MemoryResource와 ComputeResource를 독립적으로 확장할 수 있다.

```text
New ComputeResource
        ↓
register capability
        ↓
Topology / Binding 추가
```

기존 MemoryResource의 interface를 수정하지 않고 새로운 Compute backend를 추가하기 쉽다.

**Trade-off:** Simple integrated abstraction ↔ independent extensibility

---

# 4. Overall Trade-off

```text
Candidate 1                         Candidate 2
Memory-Coupled                      Decoupled
      │                                  │
      ▼                                  ▼
Simple / Predictable            Flexible / Extensible
      │                                  │
Low Dispatch Overhead            Dynamic Resource Selection
      │                                  │
Strong HW Coupling                Independent Resources
```

### Candidate 1 — 장점

- Compute dispatch path가 짧다.
- Runtime control overhead가 낮다.
- Data Location → Capability → Execution 관계가 명확하다.
- PNM/PIM처럼 Memory와 Compute가 강하게 결합된 HW에 자연스럽다.
- 구현 및 초기 운영 구조가 단순하다.

### Candidate 1 — 단점

- MemoryResource와 Compute capability의 coupling이 증가한다.
- 하나의 Memory에 여러 Compute backend를 연결하고 선택하기 어렵다.
- 새로운 Compute backend가 추가될수록 MemoryResource 책임이 증가할 수 있다.
- Dynamic Compute selection에 제한이 있다.

### Candidate 2 — 장점

- Memory와 Compute를 독립적으로 확장할 수 있다.
- 하나의 Memory에 여러 Compute Resource를 연결할 수 있다.
- Capability, locality, cost 등을 기준으로 Runtime이 Compute Resource를 선택할 수 있다.
- 새로운 PIM/PNM/GPU/NPU backend 추가에 유리하다.
- Memory–Compute topology를 명시적으로 표현할 수 있다.

### Candidate 2 — 단점

- Resource Binding/Topology 관리가 필요하다.
- Compute capability lookup path가 길어진다.
- Candidate filtering 및 planning overhead가 발생할 수 있다.
- 구조와 debugging path가 복잡해진다.
- 실제 HW topology를 Runtime metadata로 정확하게 표현해야 한다.

---

# 5. Recommended One-line Comparison

> **Candidate 1은 Memory에 Compute를 결합하여 낮은 overhead와 예측 가능한 실행 경로를 제공하고, Candidate 2는 Memory와 Compute를 분리하여 다양한 Compute Resource를 Runtime에서 선택·조합할 수 있도록 한다.**

따라서 두 후보의 핵심 Trade-off는:

> **Runtime Compute Efficiency / Predictability ↔ Compute Resource Utilization / Flexibility / Extensibility**

이다.

---

# 6. Evaluation Notes

- 별점은 절대적인 HW 성능 수치가 아니라 **구조적인 상대 평가**이다.
- 실제 runtime overhead는 동일한 HW에서 capability lookup, topology lookup, planning, dispatch 시간을 측정해야 한다.
- Candidate 2가 항상 더 빠르다는 의미가 아니다. Candidate 2의 장점은 추가 control overhead를 감수하면서 **여러 Compute Resource를 활용하고 선택할 수 있다는 점**이다.
- Candidate 1 역시 PNM/PIM처럼 Memory와 Compute가 1:1 또는 강하게 결합된 시스템에서는 더 적합할 수 있다.
