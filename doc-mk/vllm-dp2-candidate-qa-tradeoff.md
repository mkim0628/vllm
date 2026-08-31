# DP2 Candidate QA / Trade-off Evaluation

> DP2: Compute-Capable Memory Abstraction
>
> 설계 질문: **Data Location과 Compute Capability의 관계를 Runtime에서 어떻게 표현하고 활용할 것인가?**
>
> 본 문서는 DP2의 두 후보 구조를 QA 관점에서 비교한다.

---

## 1. Candidate Definition

### Candidate 1 — Memory-Coupled

`MemoryResource`가 Memory operation뿐 아니라 해당 Memory에서 지원하는 Compute capability와 `execute_op()`까지 함께 소유한다.

```text
Block
  ↓
BlockTable
  ↓
MemoryResource[CXL-PNM]
  ↓
supported_ops = {GEMM}
  ↓
execute_op(GEMM)
```

**한 문장 특징**

> **MemoryResource가 Data Location과 Compute Capability를 함께 캡슐화하여, 짧고 예측 가능한 Compute execution path를 제공하는 구조.**

### Candidate 2 — Decoupled

`MemoryResource`와 `ComputeResource`를 분리하고, `ResourceBinding/Topology`를 통해 관계를 등록한 뒤 Runtime의 `ComputePlanner`가 적절한 Compute Resource를 선택한다.

```text
Block
  ↓
MemoryResource[CXL-PNM]
  ↓
ResourceBinding / Topology
  ↓
{PNM0, PNM1, ...}
  ↓
Capability filtering
  ↓
Compute Planner
  ↓
Selected ComputeResource
```

**한 문장 특징**

> **Memory와 Compute를 독립적으로 추상화하고 Runtime이 둘을 동적으로 binding하여, 다양한 Compute Resource를 선택·확장할 수 있는 구조.**

---

# 2. QA Criteria

DP2에서는 DP1의 QA를 그대로 재사용하기보다 **Memory–Compute coupling의 차이**가 드러나는 다음 네 가지를 사용한다.

### QA1. Runtime Compute Efficiency

> Compute request를 실제 연산으로 dispatch하기까지의 Runtime control/lookup/planning overhead가 얼마나 작은가?

### QA2. Compute Resource Utilization

> 여러 Compute Resource 중 workload와 상황에 적합한 Resource를 얼마나 효율적으로 활용할 수 있는가?

### QA3. Memory–Compute Flexibility

> 하나의 Memory와 여러 Compute Resource의 관계, 또는 다양한 Memory–Compute 조합을 얼마나 유연하게 지원할 수 있는가?

### QA4. Maintainability & Extensibility

> 새로운 Memory Resource, Compute Resource 또는 Compute capability가 추가될 때 기존 abstraction의 변경을 얼마나 최소화할 수 있는가?

---

# 3. QA Evaluation — 3-Star Scale

> ★★★ = 매우 우수 / ★★☆ = 보통 / ★☆☆ = 상대적으로 불리

| QA | Candidate 1: Memory-Coupled | Candidate 2: Decoupled | 주요 이유 |
|---|:---:|:---:|---|
| **Runtime Compute Efficiency** | ★★★ | ★★☆ | C1은 direct dispatch path, C2는 binding/capability lookup 및 planning 필요 |
| **Compute Resource Utilization** | ★★☆ | ★★★ | C1은 MemoryResource에 연결된 capability 중심, C2는 여러 ComputeResource 중 선택 가능 |
| **Memory–Compute Flexibility** | ★★☆ | ★★★ | C1은 coupling이 강하고 C2는 Memory–Compute 관계를 별도 binding으로 표현 |
| **Maintainability & Extensibility** | ★★☆ | ★★★ | C1은 Compute 기능 확장 시 MemoryResource coupling 증가, C2는 ComputeResource 독립 확장 가능 |

### Summary

```text
                         Candidate 1       Candidate 2
Runtime Compute Efficiency    ★★★               ★★☆
Compute Resource Utilization  ★★☆               ★★★
Memory–Compute Flexibility   ★★☆               ★★★
Maintainability/Extensibility ★★☆              ★★★
```

**결과적으로 어느 한 후보가 모든 QA에서 우세하지 않으며, 명확한 Trade-off 관계를 갖는다.**

---

# 4. QA별 상세 비교

## QA1. Runtime Compute Efficiency

### Candidate 1 — ★★★

```text
Block
 ↓
MemoryResource
 ↓
Capability
 ↓
execute_op()
```

- Location lookup 이후 Capability 확인 경로가 짧다.
- 별도의 Memory–Compute binding traversal이나 Compute planning이 필요하지 않다.
- 반복적인 Memory-side Compute에 대해 dispatch path가 단순하고 예측 가능하다.

### Candidate 2 — ★★☆

```text
Block
 ↓
MemoryResource
 ↓
Topology / Binding
 ↓
ComputeResource candidates
 ↓
Capability filtering
 ↓
Planner
 ↓
Execute
```

- 추가적인 binding lookup 및 capability filtering이 필요하다.
- 여러 Compute Resource를 비교하는 경우 planning overhead가 발생할 수 있다.
- 대신 이 overhead를 통해 더 나은 Compute Resource를 선택할 수 있다.

**Trade-off:**

> **Low dispatch overhead & predictability ↔ Dynamic compute selection**

---

## QA2. Compute Resource Utilization

### Candidate 1 — ★★☆

MemoryResource가 자신의 Compute capability를 함께 소유하므로 구조적으로 단순하지만, 여러 Compute Resource 중 선택하는 구조를 표현하기 어렵다.

예:

```text
CXL-PNM MemoryResource
 └── supported_ops = {GEMM}
```

Compute가 사실상 MemoryResource에 종속된다.

### Candidate 2 — ★★★

```text
CXL-PNM
 ├── PNM0 : {GEMM, Reduce}
 └── PNM1 : {GEMM}
```

또는:

```text
CXL Memory
 ├── PNM0
 ├── GPU0
 └── NPU0
```

처럼 여러 Compute Resource를 표현하고 Runtime policy에 따라 선택할 수 있다.

**Trade-off:**

> **Fixed/simple execution ↔ Better resource utilization through selection**

---

## QA3. Memory–Compute Flexibility

### Candidate 1 — ★★☆

MemoryResource 내부에 Compute capability가 포함되므로:

```text
MemoryResource
 └── Compute capability
```

라는 강한 coupling이 생긴다.

Memory와 Compute가 1:1로 강하게 결합된 PNM/PIM 구조에는 자연스럽지만, 하나의 Memory에 여러 Compute Resource가 연결되는 N:M topology를 표현하기에는 불리하다.

### Candidate 2 — ★★★

Memory와 Compute를 분리하고 관계를 별도의 topology/binding으로 표현한다.

```text
MemoryResource
       │
       ├──── PNM0
       ├──── PNM1
       └──── GPU0
```

따라서 HW topology가 복잡해져도 abstraction 자체를 변경하지 않고 binding 정보를 변경할 수 있다.

**Trade-off:**

> **Tight HW coupling & simplicity ↔ Flexible Memory–Compute composition**

---

## QA4. Maintainability & Extensibility

### Candidate 1 — ★★☆

새로운 Compute capability가 추가될 때 MemoryResource abstraction이 해당 capability와 execution interface까지 책임질 가능성이 있다.

예:

```text
MemoryResource
 ├── GEMM
 ├── GEMV
 ├── Reduce
 └── NewOp
```

Compute 기능이 증가할수록 Memory abstraction의 책임 범위가 커질 수 있다.

### Candidate 2 — ★★★

Compute Resource를 독립적으로 추가할 수 있다.

```text
ComputeResource[PNM2]
 └── supported_ops = {GEMM, Reduce, NewOp}
```

MemoryResource의 interface를 변경하지 않고 Compute Resource 및 capability를 확장할 수 있다.

**Trade-off:**

> **Simple integrated abstraction ↔ Independent component evolution**

---

# 5. Candidate 1 — Advantages / Disadvantages

## Advantages

1. **낮은 Runtime overhead**
   - Location → Capability → Execution path가 짧다.
2. **예측 가능한 Compute dispatch**
   - MemoryResource가 capability와 execution entry point를 직접 소유한다.
3. **구현 단순성**
   - 별도의 ResourceBinding/Topology와 Planner가 최소화된다.
4. **강결합 PNM/PIM HW에 자연스럽다**
   - 특정 Memory에 특정 Compute capability가 고정된 구조에서 적합하다.

## Disadvantages

1. **Memory–Compute coupling 증가**
   - Memory abstraction이 Compute 기능까지 책임진다.
2. **Compute Resource 선택의 유연성 제한**
   - 여러 Compute backend 중 동적으로 선택하기 어렵다.
3. **N:M topology 표현에 불리**
   - 하나의 Memory에 여러 Compute Resource가 붙는 구조가 복잡해질 수 있다.
4. **Compute capability 확장에 따른 abstraction 비대화 가능성**
   - Compute 기능이 많아질수록 MemoryResource의 책임 범위가 증가할 수 있다.

---

# 6. Candidate 2 — Advantages / Disadvantages

## Advantages

1. **Compute Resource 독립성**
   - Memory와 Compute의 lifecycle/interface를 독립적으로 설계할 수 있다.
2. **높은 Compute Resource 활용성**
   - 여러 Compute Resource 중 workload에 적합한 Resource를 선택할 수 있다.
3. **높은 Memory–Compute 조합 유연성**
   - ResourceBinding/Topology를 통해 1:N 또는 N:M 관계를 표현할 수 있다.
4. **확장성**
   - 새로운 Compute Resource 및 capability를 MemoryResource 변경 없이 추가할 수 있다.
5. **Runtime optimization 가능성**
   - locality, bandwidth, compute cost, queue 상태 등을 고려한 Compute selection으로 확장할 수 있다.

## Disadvantages

1. **추가 Runtime overhead**
   - Binding lookup, capability filtering, planning 단계가 추가된다.
2. **구조 복잡성 증가**
   - ResourceBinding/Topology, ComputeRegistry, Planner 등의 관리가 필요하다.
3. **Metadata consistency 부담**
   - Memory–Compute 관계가 별도 metadata로 존재하므로 topology 정보의 일관성 관리가 필요하다.
4. **단순한 PNM/PIM 구조에서는 over-engineering 가능성**
   - Memory와 Compute가 항상 1:1로 고정되어 있다면 Candidate 1보다 복잡한 구조가 될 수 있다.

---

# 7. 핵심 Trade-off

```text
Candidate 1                         Candidate 2
Memory-Coupled                      Decoupled
      │                                  │
      ▼                                  ▼
Simple / Predictable           Flexible / Selectable
      │                                  │
Low Runtime Overhead           Higher Planning Overhead
      │                                  │
Strong HW Coupling             Independent Resources
      │                                  │
Fixed Capability Path           Dynamic Resource Selection
```

### 한 줄 비교

> **Candidate 1은 MemoryResource 내부에서 Compute까지 처리하여 낮은 overhead와 예측 가능성을 확보하는 대신 유연성을 희생하고, Candidate 2는 Memory와 Compute를 분리해 Runtime binding을 수행함으로써 유연성과 확장성을 확보하는 대신 planning overhead와 구조 복잡성을 감수한다.**

---

# 8. Recommended Evaluation Point

두 후보 중 어느 것이 절대적으로 우수하다고 결론내리기보다는 **HW topology와 workload 특성에 따라 선택되는 Trade-off 구조**로 보는 것이 적절하다.

### Candidate 1을 선택할 근거

- Memory와 Compute가 강하게 1:1 결합
- 지원 operation이 제한적이고 안정적
- operation당 latency가 작아 control overhead가 중요
- allocation 이후 compute path의 예측 가능성이 중요

### Candidate 2를 선택할 근거

- 하나의 Memory에 여러 Compute Resource가 연결될 수 있음
- PNM/PIM/GPU/NPU 등 heterogeneous Compute backend가 공존
- Runtime이 locality/cost/load를 기반으로 Compute를 선택해야 함
- 향후 새로운 Compute capability의 독립적인 확장이 중요

---

# 9. Final Summary

| | Candidate 1 | Candidate 2 |
|---|---|---|
| **Architecture** | Memory-Coupled | Decoupled Memory / Compute |
| **Core idea** | MemoryResource가 Compute capability까지 소유 | MemoryResource와 ComputeResource를 분리하고 Runtime이 binding |
| **Best at** | Low overhead / Predictability | Flexibility / Resource utilization / Extensibility |
| **Main cost** | Coupling | Planning & metadata complexity |
| **One-line characteristic** | **Memory가 Compute를 품어 빠르고 예측 가능한 실행 경로 제공** | **Memory와 Compute를 분리해 Runtime이 상황에 맞는 Compute를 선택** |

**핵심 Trade-off:**

> **Runtime Compute Efficiency / Predictability ↔ Compute Resource Utilization / Flexibility / Extensibility**
