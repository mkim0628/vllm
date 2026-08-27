# 메모리 추상화 Layer — 추상화 수준에 대한 후보 구조 설계

> 선행 문서: `doc-mk/vllm-kv-cache-memory-abstraction-layer.md` (MAL 기본 설계,
> §8 통합 module view)
>
> 본 문서는 위 문서에서 만든 module view를 출발점으로, **메모리 추상화 계층의
> 추상화 수준을 어떻게 가져갈 것인가**라는 설계쟁점에 대해 두 후보 구조
> (범용성 강조 / 하드웨어 특화 강조)를 설계하고 비교합니다.

## 0. 배경 재정리

- 차세대 이기종 메모리(CXL, Custom HBM, HBF 등)를 지원해야 함
- 이기종 메모리가 혼재된 시스템에서 **개별 자원만 관리하는 게 아니라 자원 간
  상호 인지 기반의 통합 관리**가 필요함
- **상위 모듈(Scheduler, ModelLoader, GPUModelRunner 등) 변경을 최소화**하기 위한
  공통 추상화 interface가 필요함

## 1. 설계쟁점 검토

### 1.1 제시하신 설계쟁점(DP-1)

> 메모리 추상화 layer의 추상화 수준을 어떻게 가져갈 것인가?

**타당한 쟁점입니다.** HAL(Hardware Abstraction Layer) 설계에서 가장 고전적이고
근본적인 축이고, 배경의 두 목표에 직접 연결됩니다.

- 추상화 수준이 낮을수록(범용) → 신규 메모리 온보딩이 쉽고 상위 모듈이 안정적
  (배경의 세 번째 목표에 유리)
- 추상화 수준이 높을수록(특화 반영) → 하드웨어 고유 기능을 살릴 수 있음(배경의
  첫 번째 목표에 유리)

즉 이 쟁점은 **배경의 목표 1(이기종 지원)과 목표 3(상위 모듈 안정성)이 서로
당기는 힘**을 어떻게 배분할지의 문제이고, 두 후보 구조로 스펙트럼의 양 끝을
탐색하는 건 합리적인 접근입니다.

### 1.2 별도로 봐야 할 가능성이 있는 쟁점(DP-2) — 참고용

배경의 목표 2("자원 간 상호 인지 기반의 통합 관리")는 사실 DP-1과는 **독립적인
축**일 수 있습니다. DP-1은 "인터페이스가 얼마나 범용적인가"의 문제이고, 목표 2는
"여러 티어의 상태를 **누가, 어디서** 종합적으로 판단하는가"의 문제이기 때문입니다
— 예를 들면:

- 중앙집중형: `TierPlacementPolicy` 하나가 모든 티어의 상태를 모아서 판단 (지금
  §8까지 그린 구조가 이쪽)
- 분산 자율형: 티어들끼리 서로의 상태를 프로토콜로 주고받으며 자율적으로 데이터를
  재배치 (예: 티어 A가 자기 용량이 부족해지면 티어 B에게 직접 이관을 제안)

이 축은 DP-1(범용 vs 특화)과 직교하기 때문에, "범용 인터페이스 + 중앙집중 조정",
"특화 인터페이스 + 분산 자율 조정" 등 4가지 조합이 모두 가능합니다. 이번 문서는
요청하신 대로 **DP-1에 대한 두 후보 구조**에 집중하고, DP-2(조정 주체의 위치)는
필요하시면 별도 문서로 다루는 걸 제안드립니다.

---

## 2. 두 후보의 공통 전제

두 후보 모두 다음은 동일하게 유지합니다 (`vllm-kv-cache-memory-abstraction-layer.md`
§8과 동일):

- 상위 스택: `Scheduler`(KV cache) / `ModelLoader`(Weight) / `GPUModelRunner`(Activation)
  → 각 도메인별 배치 정책 → `MemoryTierRegistry`
- 지원 메모리: GPU HBM(로컬, Tier 0, 필수) + CPU DRAM / Custom HBM / CXL Memory /
  HBF(원격, 선택적)
- 평가 기준: ① 신규 메모리 온보딩 난이도, ② 상위 모듈 변경량, ③ 하드웨어 고유
  기능 활용도, ④ 구현/유지보수 복잡도, ⑤ 성능 상한

두 후보는 `MemoryTierRegistry` **아래쪽**(플러그인 인터페이스가 얼마나 균일한가)
에서만 갈라집니다.

---

## 3. 후보 1 — 범용성 강조 구조 (Uniform Capability Model)

> **개정 노트**: 최초 버전의 후보 1은 "연산 가능 메모리의 연산 기능은 아예
> 지원하지 못함"으로 정의되어 있었습니다. 그러나 연산 가능 메모리 지원이
> 기능 요구사항(FR)이라면, 두 후보 모두 이 FR을 만족해야 하고 후보 1과 후보 2는
> "지원하느냐 마느냐"가 아니라 "**어떻게** 지원하느냐"로 비교되어야 합니다.
> 아래는 이를 반영한 정의입니다.

### 3.1 설계 철학

모든 티어가 **정확히 하나의 인터페이스**(`MemoryTier`)만 구현합니다. 하드웨어
고유 기능(연산, pooling, batch-read 등)을 위한 **별도 인터페이스는 만들지
않습니다** — 대신 `MemoryTierCapabilities`에 `supported_ops`라는 데이터
필드로 "이 티어가 어떤 연산을 지원하는지"를 선언하고, 실행은 모든 티어가
공유하는 단일 진입점 `execute_op(op)` 하나로 이뤄집니다.

`op`의 타입 `ComputeOp`는 **코어 모듈에 정의된 닫힌 클래스 계층(sealed class
hierarchy)**입니다 — `PartialSumOp`, `ArgmaxOp`처럼 정해진 서브클래스들만
존재하고, 이 서브클래스 목록은 `ComputeOp`가 정의된 그 코어 모듈 파일 안에서만
늘어날 수 있습니다. 즉 "연산이 존재한다"는 사실 자체는 어떤 티어든 알릴 수 있어
FR은 만족되지만, **새 서브클래스를 이 계층에 추가하는 건 항상 코어 모듈 수정을
필요로 합니다.** 이게 후보 1과 후보 2를 가르는 유일하고 핵심적인 차이입니다 —
뒤에서 다시 정리합니다(§3.5, §5).

### 3.2 Module View

```mermaid
graph TD
    TPP["TierPlacementPolicy<br/>KV Cache / Weight 공통 배치 정책"]
    REGISTRY["MemoryTierRegistry"]
    IFACE["MemoryTier 단일 공통 인터페이스<br/>capacity · latency · bandwidth ·<br/>supported_ops 데이터 필드 ·<br/>execute_op 단일 진입점"]

    subgraph OPHIER["ComputeOp 클래스 계층 — 코어 모듈에 정의, 서브클래스 목록 고정"]
        COMPUTEOP["ComputeOp<br/>최상위 클래스"]
        PARTIALSUM["PartialSumOp<br/>서브클래스"]
        ARGMAX["ArgmaxOp<br/>서브클래스"]
        COMPUTEOP --> PARTIALSUM
        COMPUTEOP --> ARGMAX
    end

    subgraph PLUGINS["MemoryTier 구현체 — 모두 동일한 계약, 동일한 모양"]
        GPUHBM["GPUHBMTier<br/>supported_ops = 없음"]
        DRAMT["CPUDRAMTier<br/>supported_ops = 없음"]
        CUSTOMT["CustomHBMTier<br/>supported_ops = partial_sum"]
        CXLT["CXLTier<br/>supported_ops = 없음"]
        HBFT["HBFTier<br/>supported_ops = 없음"]
    end

    subgraph PHYS_LOCAL["로컬, Tier 0"]
        HBM_PHYS[("GPU HBM")]
    end
    subgraph PHYS_REMOTE["원격, 선택적"]
        DRAM_PHYS[("CPU DRAM")]
        CUSTOM_PHYS[("Custom HBM")]
        CXL_PHYS[("CXL Memory")]
        HBF_PHYS[("HBF")]
    end

    NEWOP["새 서브클래스예 PoolingOp 를 추가하려면<br/>OPHIER 가 정의된 코어 모듈 파일을<br/>직접 수정해야 함<br/>벤더가 코어 승인 없이 단독 추가 불가"]

    TPP --> REGISTRY --> IFACE
    IFACE -.-> OPHIER
    IFACE --> GPUHBM --> HBM_PHYS
    IFACE --> DRAMT --> DRAM_PHYS
    IFACE --> CUSTOMT --> CUSTOM_PHYS
    IFACE --> CXLT --> CXL_PHYS
    IFACE --> HBFT --> HBF_PHYS
    OPHIER -. "코어 모듈 수정 필요" .-> NEWOP

    classDef localMem fill:#dbe7ff,stroke:#3b5bdb,color:#1c2b5e,stroke-width:2px;
    classDef remoteMem fill:#eef1f4,stroke:#8d99ae,color:#22303e,stroke-width:1px;
    classDef hierBox fill:#fff3bf,stroke:#f08c00,color:#5c3c00,stroke-width:2px;
    classDef warnBox fill:#ffe3e3,stroke:#e03131,color:#5c1a1a,stroke-width:1px,stroke-dasharray: 4 3;
    class HBM_PHYS,GPUHBM localMem
    class DRAM_PHYS,CUSTOM_PHYS,CXL_PHYS,HBF_PHYS,DRAMT,CUSTOMT,CXLT,HBFT remoteMem
    class COMPUTEOP,PARTIALSUM,ARGMAX hierBox
    class NEWOP warnBox
```

모든 `MemoryTier` 구현체 박스가 **같은 크기, 같은 모양**인 게 핵심입니다 — 인터페이스
계약이 하나뿐이라 플러그인 사이에 구조적 차이가 없습니다. `CustomHBMTier`처럼 연산을
지원하는 티어도 `supported_ops`라는 데이터만 다를 뿐, 별도 인터페이스를 구현하지
않습니다. 대신 "새 연산 종류 자체"는 노란 박스(`ComputeOp` 클래스 계층 — 최상위
클래스 하나에 정해진 서브클래스들만 매달린 구조)에 중앙집중되어 있고, 이 계층에
새 서브클래스를 추가하려면 코어 모듈을 직접 수정해야 한다는 제약이 남습니다 —
빨간 점선 박스가 그 제약을 보여줍니다.

### 3.3 Class Diagram

```mermaid
classDiagram
    class MemoryTierCapabilities {
        <<dataclass>>
        +str tier_id
        +int capacity_bytes
        +bool byte_addressable
        +bool gpu_direct_access
        +bool cache_coherent
        +float read_latency_ns
        +float write_bandwidth_GBps
        +list~str~ supported_ops
    }

    class MemoryTier {
        <<interface>>
        +capabilities() MemoryTierCapabilities
        +allocate(nbytes) TierBuffer
        +free(buf) void
        +as_torch_storage(buf) Tensor
        +execute_op(op) PartialResult
    }
    MemoryTier <|.. GPUHBMTier
    MemoryTier <|.. CPUDRAMTier
    MemoryTier <|.. CustomHBMTier
    MemoryTier <|.. CXLTier
    MemoryTier <|.. HBFTier

    class ComputeOp {
        <<코어 모듈 소유, sealed hierarchy>>
    }
    class PartialSumOp
    class ArgmaxOp
    ComputeOp <|-- PartialSumOp
    ComputeOp <|-- ArgmaxOp
    MemoryTier ..> ComputeOp : execute_op 인자

    note for CustomHBMTier "MemoryTier 하나만 구현<br/>supported_ops = partial_sum<br/>연산도 execute_op 안에서 처리"
    note for GPUHBMTier "MemoryTier 하나만 구현<br/>supported_ops = 없음<br/>나머지 티어와 클래스 구조는 동일"

    class MemoryTierRegistry {
        <<factory>>
        +register(name, module_path, class_name) void
        +create(name, config) MemoryTier
        +list_tiers() list
    }
    MemoryTierRegistry --> MemoryTier : creates

    class TierPlacementPolicy {
        +decide_tier(data_meta, tiers) str
    }
    TierPlacementPolicy --> MemoryTierRegistry : capabilities 조회<br/>supported_ops 포함
```

모든 구현체가 `MemoryTier` **단 하나만** 실현(realize)한다는 게 후보 1의
클래스 구조에서 가장 뚜렷한 특징입니다 — 연산 지원 여부와 무관하게 인터페이스가
여러 개로 갈라지지 않습니다. `CustomHBMTier`와 `GPUHBMTier`의 차이는 오직
`capabilities()`가 반환하는 **데이터**(`supported_ops`)뿐이고, 실행 경로는
`execute_op(op)` 하나로 공유됩니다. `ComputeOp`(및 그 서브클래스들)는 이
인터페이스가 참조하는 유일한 "외부" 클래스 계층이며, 이게 §3.5에서 다룰
트레이드오프의 핵심입니다.

### 3.4 Sequence Diagram — 배치 결정 + 연산 실행 흐름

```mermaid
sequenceDiagram
    participant CALLER as Scheduler / ModelLoader
    participant TPP as TierPlacementPolicy
    participant REG as MemoryTierRegistry
    participant TIER as 선택된 MemoryTier 구현체<br/>예 CustomHBMTier

    CALLER->>TPP: decide_tier(data_meta)
    TPP->>REG: list_tiers()
    REG-->>TPP: MemoryTierCapabilities 목록<br/>supported_ops 포함
    TPP->>TPP: capacity/latency 비교 +<br/>필요 연산이 supported_ops 에 있는지 확인
    TPP-->>CALLER: tier_id
    CALLER->>REG: create(tier_id)
    REG-->>CALLER: TIER 인스턴스
    CALLER->>TIER: allocate(nbytes)
    TIER-->>CALLER: TierBuffer

    Note over CALLER,TIER: 이후 연산 실행 시점 - forward pass
    CALLER->>TIER: execute_op(PartialSumOp(block_ids, axis))
    TIER-->>CALLER: PartialResult

    Note over TPP,TIER: 모든 티어가 동일한 인터페이스(execute_op 포함)로<br/>응답하므로 TierPlacementPolicy/호출부는<br/>티어 종류별 분기 코드를 전혀 갖지 않음<br/>단, "어떤 연산이 존재하는가"(ComputeOp 클래스 계층)는<br/>여전히 코어 모듈에 고정되어 있음
```

배치 결정과 연산 실행이 **같은 인터페이스, 같은 진입점**으로 이어지는 게
핵심입니다 — 후보 2(§4.4, §4.6)처럼 "확장 인터페이스를 인지하는 별도 상위
모듈(`ComputeDispatcher`)"이 따로 필요하지 않습니다. 대신 `execute_op`가
받는 `op`의 타입(`ComputeOp`의 서브클래스)은 코어 모듈에 정의된 클래스
계층 안에 있어야 합니다.

### 3.5 장단점

| 항목 | 평가 |
|---|---|
| 연산 가능 메모리 지원 (FR) | **만족** — `supported_ops` 데이터 필드 + `execute_op` 공통 진입점으로 커버 |
| 신규 메모리(티어) 온보딩 난이도 | **낮음** — `MemoryTier` 하나만 구현, `supported_ops`에 지원 연산만 나열하면 됨 |
| 상위 모듈 변경량 | **거의 없음** — `TierPlacementPolicy`/호출부는 항상 같은 진입점(`execute_op`)만 사용, 티어별 분기 없음 |
| 신규 연산(하드웨어 고유 기능) 확장 자유도 | **낮음** — 새 연산 종류는 `ComputeOp` 클래스 계층에 서브클래스로 추가되어야 등장 가능. 이 계층은 코어 모듈에 정의되어 있어, 벤더가 코어 승인 없이 독자적으로 새 연산을 추가할 수 없음 |
| 구현/유지보수 복잡도 | **낮음** — 인터페이스가 하나뿐이고, `ComputeOp` 서브클래스도 한 모듈에 모여 있어 "이 시스템에 어떤 연산이 존재하는지" 파악하기 쉬움 |

---

## 4. 후보 2 — 하드웨어 특화 구조 (Extensible Capability Model)

### 4.1 설계 철학

모든 티어가 구현해야 하는 **얇은 공통 베이스**(identity + 범용 capability 최소셋)는
유지하되, 하드웨어가 고유 기능을 가진 경우 **선택적 확장 인터페이스**를 추가로
구현할 수 있게 합니다. 상위 모듈은 기본적으로 공통 베이스만 보고 동작하지만,
특정 확장 인터페이스를 인지하는 상위 모듈(예: `ComputeDispatcher`)은 그 확장을
활용해 하드웨어 고유 기능을 끌어냅니다.

이건 사실 `vllm-kv-cache-memory-abstraction-layer.md` §7에서 이미 축소판으로
설계한 패턴입니다 — `ComputeCapableTier`가 PIM 하나를 위한 선택적 확장이었습니다.
**후보 2는 그 패턴을 PIM 하나가 아니라 모든 하드웨어 고유 기능으로 일반화한
것**입니다.

### 4.2 Module View

```mermaid
graph TD
    TPP["TierPlacementPolicy"]
    REGISTRY["MemoryTierRegistry"]
    BASE["MemoryTier 공통 얇은 베이스<br/>identity · capacity ·<br/>범용 capability 최소셋<br/>모든 티어 필수"]

    subgraph EXT["선택적 확장 인터페이스 — 티어별로 유무가 다름"]
        POOLEXT["CXLPoolingExtension<br/>fabric 공유/풀링"]
        COMPUTEEXT["ComputeCapableTier<br/>PIM 연산 §7"]
        BATCHEXT["HBFBatchReadExtension<br/>배치 순차읽기 최적화"]
    end

    subgraph PLUGINS["MemoryTier 구현체 — 베이스+확장 조합이 제각각"]
        GPUHBM["GPUHBMTier<br/>base only"]
        DRAMT["CPUDRAMTier<br/>base only"]
        CUSTOMT["CustomHBMTier<br/>base + Compute"]
        CXLT["CXLTier<br/>base + Pooling"]
        HBFT["HBFTier<br/>base + BatchRead"]
    end

    subgraph UPPER["확장을 인지하는 상위 모듈 — 존재할 때만 사용"]
        DISPATCHER["ComputeDispatcher §7"]
        WPLACE["Weight/KV 배치 로직<br/>확장 인지 확장판"]
    end

    subgraph PHYS_LOCAL["로컬, Tier 0"]
        HBM_PHYS[("GPU HBM")]
    end
    subgraph PHYS_REMOTE["원격, 선택적"]
        DRAM_PHYS[("CPU DRAM")]
        CUSTOM_PHYS[("Custom HBM")]
        CXL_PHYS[("CXL Memory")]
        HBF_PHYS[("HBF")]
    end

    TPP --> REGISTRY --> BASE
    BASE --> GPUHBM --> HBM_PHYS
    BASE --> DRAMT --> DRAM_PHYS
    BASE --> CUSTOMT --> CUSTOM_PHYS
    BASE --> CXLT --> CXL_PHYS
    BASE --> HBFT --> HBF_PHYS

    CUSTOMT --> COMPUTEEXT
    CXLT --> POOLEXT
    HBFT --> BATCHEXT

    DISPATCHER -. "확장 인지 시에만 사용" .-> COMPUTEEXT
    WPLACE -. "확장 인지 시에만 사용" .-> POOLEXT
    WPLACE -. "확장 인지 시에만 사용" .-> BATCHEXT

    classDef localMem fill:#dbe7ff,stroke:#3b5bdb,color:#1c2b5e,stroke-width:2px;
    classDef remoteMem fill:#eef1f4,stroke:#8d99ae,color:#22303e,stroke-width:1px;
    classDef extBox fill:#d8f5d0,stroke:#2f9e44,color:#1b4332,stroke-width:2px;
    classDef upperBox fill:#fff3bf,stroke:#f08c00,color:#5c3c00,stroke-width:1px;
    class HBM_PHYS,GPUHBM localMem
    class DRAM_PHYS,CUSTOM_PHYS,CXL_PHYS,HBF_PHYS,DRAMT,CUSTOMT,CXLT,HBFT remoteMem
    class POOLEXT,COMPUTEEXT,BATCHEXT extBox
    class DISPATCHER,WPLACE upperBox
```

`GPUHBMTier`/`CPUDRAMTier`는 확장이 없는 "평범한" 티어로, `CustomHBMTier`/
`CXLTier`/`HBFTier`는 각자 다른 확장을 가진 "특화" 티어로 **의도적으로 비대칭
모양**으로 그렸습니다 — 후보 1과 달리 플러그인마다 구조가 달라지는 게 이 설계의
본질입니다.

### 4.3 Class Diagram — 후보 2 자체 (§3.3과 나란히 비교)

§3.3(후보 1)과 동일한 범위 — `MemoryTier` 베이스, `MemoryTierRegistry`,
`TierPlacementPolicy` — 에 확장 인터페이스 3종을 더한 버전입니다. 후보 1에서는
모든 구현체가 `MemoryTier` 하나만 realize 했지만, 여기서는 티어마다 realize하는
인터페이스 수가 다릅니다.

```mermaid
classDiagram
    class MemoryTierCapabilities {
        <<dataclass>>
        +str tier_id
        +int capacity_bytes
        +bool byte_addressable
        +bool gpu_direct_access
        +bool cache_coherent
        +float read_latency_ns
        +float write_bandwidth_GBps
    }

    class MemoryTier {
        <<interface>>
        +capabilities() MemoryTierCapabilities
        +allocate(nbytes) TierBuffer
        +free(buf) void
        +as_torch_storage(buf) Tensor
    }
    MemoryTier <|.. GPUHBMTier
    MemoryTier <|.. CPUDRAMTier
    MemoryTier <|.. CustomHBMTier
    MemoryTier <|.. CXLTier
    MemoryTier <|.. HBFTier

    class ComputeCapableTier {
        <<interface>>
        +compute_capabilities() ComputeCapabilities
        +supported_ops() list
        +execute_partial(op, query, block_ids, meta) PartialResult
    }
    class CXLPoolingExtension {
        <<interface>>
        +pool_id() str
        +request_pooled_capacity(bytes) bool
    }
    class HBFBatchReadExtension {
        <<interface>>
        +batch_read(block_ids) Tensor
    }
    ComputeCapableTier <|.. CustomHBMTier
    CXLPoolingExtension <|.. CXLTier
    HBFBatchReadExtension <|.. HBFTier

    note for GPUHBMTier "MemoryTier 만 구현 - base only"
    note for CPUDRAMTier "MemoryTier 만 구현 - base only"
    note for CustomHBMTier "MemoryTier + ComputeCapableTier"
    note for CXLTier "MemoryTier + CXLPoolingExtension"
    note for HBFTier "MemoryTier + HBFBatchReadExtension"

    class MemoryTierRegistry {
        <<factory>>
        +register(name, module_path, class_name) void
        +create(name, config) MemoryTier
        +list_tiers() list
    }
    MemoryTierRegistry --> MemoryTier : creates
    MemoryTierRegistry --> ComputeCapableTier : creates 동일 tier_id
    MemoryTierRegistry --> CXLPoolingExtension : creates 동일 tier_id
    MemoryTierRegistry --> HBFBatchReadExtension : creates 동일 tier_id

    class TierPlacementPolicy {
        +decide_tier(data_meta, tiers) str
    }
    TierPlacementPolicy --> MemoryTierRegistry : capabilities 조회<br/>확장 유무 포함
```

후보 1의 클래스 다이어그램(§3.3)과 나란히 놓고 보면, `MemoryTier <|.. X` 관계
자체는 다섯 티어 모두 동일하지만 **그 외에 realize하는 인터페이스 수가
0개(후보 1은 항상 0개, 즉 추가 없음) vs 0~1개(후보 2)로 갈린다**는 게 유일하고
결정적인 구조 차이입니다.

### 4.4 Sequence Diagram — 후보 2 자체, 배치 결정 흐름 (§3.4와 나란히 비교)

§3.4(후보 1)와 같은 종류의 흐름 — "데이터를 어느 티어에 배치할지 결정"하는
장면 — 을 후보 2 버전으로 그린 것입니다. 여기서 `tier_id`가 어떻게
결정되고, 이후 forward pass 시점에 `AttentionImpl`이 그걸 어떻게 다시
읽어오는지(질문하신 부분)까지 이어서 표시했습니다.

```mermaid
sequenceDiagram
    participant CALLER as Scheduler / ModelLoader
    participant TPP as TierPlacementPolicy
    participant REG as MemoryTierRegistry
    participant TIER as 선택된 MemoryTier 구현체<br/>예 CustomHBMTier
    participant BT as TieredBlockTable

    CALLER->>TPP: decide_tier(data_meta)
    TPP->>REG: list_tiers()
    REG-->>TPP: capabilities 목록<br/>base 필드 + 어떤 확장을 구현하는지 여부
    TPP->>TPP: base 필드 비교 + 확장 유무까지 고려<br/>예 연산이 필요한 워크로드면<br/>ComputeCapableTier 구현 티어를 우대
    TPP-->>CALLER: tier_id
    CALLER->>REG: create(tier_id)
    REG-->>CALLER: TIER 인스턴스<br/>base + 해당 확장까지 구현된 객체
    CALLER->>TIER: allocate(nbytes)
    TIER-->>CALLER: TierBuffer
    CALLER->>BT: block_locations block_id = tier_id local_block_id 기록

    Note over BT: 이렇게 기록된 tier_id 가 §4.6 sequence diagram 에서<br/>AttentionImpl 이 should_dispatch 호출 시 넘기는 값의 출처입니다.<br/>forward pass 시점에 AttentionImpl 은 attn_metadata.block_table 을 통해<br/>BT 에서 tier_id 를 조회만 하고, 새로 계산하지 않습니다.

    Note over TPP,TIER: 후보 1과의 차이: TierPlacementPolicy 가 base 필드뿐 아니라<br/>확장 인터페이스 유무까지 알아야 최선의 배치를 할 수 있음<br/>→ §4.7 장단점의 상위 모듈 변경량 항목과 직결
```

### 4.5 Class Diagram — ComputeDispatcher가 Worker와 어떻게 연결되는가

아래 다이어그램은 §4.2의 확장 인터페이스 3종(pooling/compute/batch-read) 중
**연산(compute) 확장 하나만** 떼어내서, 그게 실제 모델 실행 경로(Worker 프로세스,
`GPUModelRunner`/`AttentionImpl`)와 어떻게 이어지는지를 명확히 합니다.

```mermaid
classDiagram
    class MemoryTier {
        <<interface>>
        +capabilities() MemoryTierCapabilities
        +allocate(nbytes) TierBuffer
        +as_torch_storage(buf) Tensor
    }
    MemoryTier <|.. GPUHBMTier
    MemoryTier <|.. CustomHBMTier

    class ComputeCapableTier {
        <<interface>>
        +compute_capabilities() ComputeCapabilities
        +supported_ops() list
        +execute_partial(op, query, block_ids, meta) PartialResult
    }
    ComputeCapableTier <|.. CustomHBMTier
    note for CustomHBMTier "MemoryTier 와 ComputeCapableTier<br/>둘 다 구현 - base + 확장"
    note for GPUHBMTier "MemoryTier 만 구현<br/>compute 확장 없음"

    class PartialResult {
        <<dataclass>>
        +Tensor partial_output
        +Tensor partial_lse
        +str tier_id
    }
    ComputeCapableTier --> PartialResult : returns

    class ComputeDispatcher {
        <<신규>>
        +should_dispatch(op, tier_id) bool
        +dispatch(op, query, tier_id, block_ids) Future
    }
    ComputeDispatcher --> ComputeCapableTier : compute 확장이 있을 때만 호출
    ComputeDispatcher --> PartialResultMerger

    class PartialResultMerger {
        <<신규>>
        +merge(results) Tensor
    }

    class GPUModelRunner {
        <<Worker 프로세스, 기존>>
        +execute_model(scheduler_output) ModelRunnerOutput
    }
    class AttentionImpl {
        <<attention 백엔드, 기존>>
        +forward(query, kv_cache, attn_metadata) Tensor
        +do_kv_cache_update(key, value, kv_cache, slot_mapping) void
    }
    GPUModelRunner --> AttentionImpl : 레이어별 forward 호출<br/>call-path-analysis.md §3
    AttentionImpl --> ComputeDispatcher : compute-capable tier 감지 시에만 질의
```

**여기서 확인해야 할 관계 하나**: `ComputeDispatcher`는 `GPUModelRunner`를 대체하는
새 실행 경로가 아니라, 기존 `AttentionImpl.forward()` **내부에서 호출되는 하나의
추가 분기**입니다. `GPUModelRunner.execute_model()` → `AttentionImpl.forward()`로
이어지는 기존 흐름(`call-path-analysis.md` §3)은 그대로 유지되고,
`ComputeDispatcher`는 그 안에서 "이번 배치의 KV 블록이 연산 가능한 티어에 있는지"만
추가로 확인하는 위치에 끼어듭니다.

### 4.6 Sequence Diagram — ComputeDispatcher의 호출 순서 (연결 구조만)

```mermaid
sequenceDiagram
    participant RUNNER as GPUModelRunner<br/>Worker 프로세스, 기존
    participant ATTN as AttentionImpl<br/>attention 백엔드, 기존
    participant DISP as ComputeDispatcher<br/>신규
    participant PIM as CustomHBMTier<br/>ComputeCapableTier 구현
    participant MERGE as PartialResultMerger<br/>신규

    Note over RUNNER,ATTN: 기존 forward pass 흐름 - call-path-analysis.md §3
    RUNNER->>ATTN: forward(query, kv_cache, attn_metadata)
    ATTN->>DISP: should_dispatch(op=attention, tier_id)
    alt tier_id 가 ComputeCapableTier 이고 op 지원
        DISP->>PIM: execute_partial(op, query, block_ids, meta)
        PIM-->>DISP: PartialResult
        DISP-->>ATTN: PartialResult 전달
        ATTN->>MERGE: merge GPU 결과 + PartialResult
        MERGE-->>ATTN: 최종 attention 출력
    else 미지원 또는 확장 없음
        DISP-->>ATTN: 폴백 신호만 반환
        Note over ATTN: 이후는 기존 GPU 전용 forward 와 동일
    end
    ATTN-->>RUNNER: attention 출력 반환
```

**의도적으로 생략한 부분**: 이 다이어그램은 "누가 누구를 호출하는가"라는 연결
구조만 보여줍니다. 다음과 같은 질문들은 답하지 않습니다 — PIM 연산이 GPU 연산과
동시에(비동기로) 진행되는지 순차적으로 기다리는지, `execute_partial()`이 레이어
단위로 매번 호출되는지 스텝 단위로 한 번만 호출되는지, PIM이 느려서 타임아웃되면
언제 어떻게 재시도/폴백하는지, CUDA stream/이벤트로 어떻게 동기화하는지. 이런
질문은 "MAL의 추상화 수준"(DP-1)이 아니라 **"연산 실행 모델을 어떻게 통합할
것인가"**라는 별개의 설계쟁점(DP-3 후보)에 속합니다 — §7.6에서 나열한 실행 단위
불일치/정밀도 정합성/동시 슬롯 큐잉/연산 실패 폴백 같은 제약들이 바로 그 DP-3가
풀어야 할 문제들의 예고편입니다. 이 문서에서는 "그런 분기점이 존재한다"까지만
보여주고, 더 깊이 들어가지 않습니다.

### 4.7 장단점

| 항목 | 평가 |
|---|---|
| 신규 메모리 온보딩 난이도 | **중간~높음** — 베이스는 쉽지만, 고유 기능을 살리려면 "새 확장 인터페이스를 만들 것인가"를 매번 판단해야 함 |
| 상위 모듈 변경량 | **있음** — 확장을 활용하려는 상위 모듈(`ComputeDispatcher` 등)은 확장별로 분기 코드가 필요, 목표 3(상위 모듈 안정성)과 정면으로 부딪힘 |
| 하드웨어 고유 기능 활용도 | **높음** — CXL pooling, PIM 연산, HBF batch-read를 실제로 활용 가능 |
| 구현/유지보수 복잡도 | **높음** — 확장 인터페이스가 늘어날수록 "어떤 백엔드/상위모듈이 어떤 확장 조합을 지원하는지" 매트릭스가 생김 (§5.4, §7.6에서 이미 지적한 문제) |
| 성능 상한 | **높음** — 하드웨어 투자 대비 이득을 최대로 뽑아낼 수 있음 |

---

## 5. 두 후보 비교

| 평가 기준 | 후보 1: 범용성 강조 | 후보 2: 하드웨어 특화 |
|---|---|---|
| 연산 가능 메모리 지원 (FR) | 만족 — `ComputeOp` 클래스 계층 경유 | 만족 — 확장 인터페이스 경유 |
| 신규 메모리(티어) 온보딩 난이도 | 낮음 | 중간~높음 |
| 신규 연산(하드웨어 고유 기능) 확장 자유도 | **낮음** — 코어 모듈에 정의된 `ComputeOp` 클래스 계층에 서브클래스를 추가해야 함, 벤더 단독 확장 불가 | **높음** — 벤더가 자체 확장 인터페이스를 정의해 코어 승인 없이 독립 배포 가능 |
| 상위 모듈 변경량 (목표 3) | 거의 없음 — 항상 같은 진입점(`execute_op`) | 확장 활용 시 필요 (확장별 분기) |
| 구현/유지보수 복잡도 | 낮음 — 인터페이스 1개, `ComputeOp` 서브클래스도 한 모듈에 모여 있음 | 높음 (확장 조합 매트릭스) |
| 코드 재사용성 | 최대 | 확장 부분은 재사용 어려움 |

두 후보 모두 연산 가능 메모리라는 FR은 만족합니다 — 더 이상 "지원하느냐"의 문제가
아닙니다. 실질적으로 갈리는 지점은 **새로운 연산이 하나 생겼을 때 그걸 시스템에
편입시킬 결정권이 어디에 있는가**입니다: 후보 1은 그 결정권을 코어에 집중시켜
일관성과 상위 모듈 안정성을 지키고(목표 3), 후보 2는 그 결정권을 벤더에게
분산시켜 코어 조율 없이도 하드웨어 고유 기능을 빠르게 반영할 수 있게 합니다
(목표 1). 이건 정량적 가중치를 매겨서 판단할 문제이지 이 문서에서 결론을 내릴
문제는 아닙니다. 다만 참고로, 두 후보가 상호 배타적이지 않다는 점은 짚어둘
만합니다 — **후보 1을 기본 골격으로 채택하고, 특정 티어에 한해서만(예: 처음엔
PIM만) 후보 2의 확장 패턴을 국소적으로 도입**하는 절충도 가능합니다. 실제로 지금
`vllm-kv-cache-memory-abstraction-layer.md` §7의 `ComputeCapableTier`가 정확히
이 절충의 실제 사례입니다 — 후보 1의 얇은 베이스 위에, PIM이라는 한 가지 케이스에만
후보 2 스타일의 확장을 얹은 것입니다.

---

## 6. 관련 문서

- `doc-mk/vllm-kv-cache-memory-abstraction-layer.md` — MAL 기본 설계 (§1 class
  diagram이 후보 1의 원형, §7 `ComputeCapableTier`가 후보 2 패턴의 축소 사례,
  §8이 두 후보 모두의 공통 상위 전제)
- `doc-mk/vllm-kv-cache-memory-tiering.md` — CXL 한정 옵션 A/B
- `doc-mk/vllm-call-path-analysis.md` — 요청 처리 전체 call path, ModelLoader
  위치(§2)
