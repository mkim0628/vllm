# 메모리 추상화 Layer — 자원 간 상호 인지 통합 관리의 조정 주체(DP-2) 후보 구조

> 선행 문서: `doc-mk/vllm-memory-abstraction-level-candidates.md` (DP-1: 추상화
> 수준 범용 vs 특화)
>
> DP-1 문서 §1.2에서 "자원 간 상호 인지 기반의 통합 관리"는 DP-1(추상화 수준)과는
> 독립적인 축이라고 짚었습니다. 본 문서는 그 축을 별도 설계쟁점(DP-2)으로 정식화하고,
> 두 후보 구조(중앙집중형 오케스트레이션 / 분산 자율 협상)를 설계·비교합니다.

## 0. 설계쟁점 정의

### 0.1 DP-2

> 이기종 메모리 티어 간 상호 인지 기반의 통합 관리를 **누가, 어디서** 수행할
> 것인가?

배경(`vllm-memory-abstraction-level-candidates.md` §0)의 목표를 다시 인용하면:

> 이기종 메모리가 혼재된 시스템에서 개별 자원만 관리하는 게 아니라 **자원 간
> 상호 인지 기반의 통합 관리**가 필요하다

이 문장이 실제로 요구하는 건 "티어 A가 가득 찼을 때, 티어 B의 상태를 고려해서
결정한다"는 능력입니다. 이 능력을 구현하는 방식은 크게 두 갈래로 갈립니다.

- **중앙집중형**: 모든 티어의 상태를 한 곳에 모아서, 그 한 곳이 전역적으로 최적의
  결정을 내림
- **분산 자율형**: 각 티어가 이웃 티어와 직접 정보를 주고받으며, 중앙 없이
  스스로 결정함

### 0.2 DP-1과의 관계

DP-1(추상화 수준: 범용 vs 특화)은 "**인터페이스에 무엇을 노출할지**"의 문제였고,
DP-2는 "**그 인터페이스로 얻은 정보를 누가 종합해서 판단할지**"의 문제입니다.
서로 다른 질문이라 원칙적으로 직교하지만, §4에서 다루듯 실제로는 서로 잘 맞는
조합과 마찰이 있는 조합이 있습니다.

---

## 1. 공통 전제

- `MemoryTierRegistry`/`MemoryTier`(DP-1 문서에서 정의)는 두 후보 모두에서 최소
  "티어 디스커버리"용으로는 유지됩니다 — 차이는 **디스커버리 이후의 조정 로직**이
  어디에 있는가입니다.
- **`MemoryTier`는 두 후보 모두에서 항상 수동적 자원 객체입니다.** `capabilities()`,
  `allocate()`/`free()`, `copy_out()`/`copy_in()`만 가지고 있고, 스스로 판단해서
  먼저 행동을 개시하는 로직은 없습니다 — 이건 DP-1에서 정한 역할 그대로이고,
  DP-2가 어느 후보로 정해지든 바뀌지 않습니다.
- **"판단"은 `MemoryTier`가 아니라 별도의 능동적 객체(Agent)가 담당합니다.**
  두 후보의 차이는 정확히 **이 Agent가 몇 개 존재하고, 각각 얼마나 넓은 정보를
  보고 판단하는가**입니다 — 후보 A는 Agent가 **1개**(`GlobalMemoryOrchestrator`)이고
  전체 티어의 전역 상태를 봅니다. 후보 B는 Agent가 **티어 개수만큼(N개)**
  존재하고(`TierAgent`, 티어당 1개), 각자 자기 티어와 일부 이웃의 국소 정보만
  봅니다.
- **실제 물리적 데이터 이동은 두 후보 공통의 `TierDataMover`가 수행합니다.**
  Agent가 "이 블록을 A에서 B로 옮겨라"라고 결정한 뒤에는, 두 후보 모두 동일하게
  `TierDataMover.transfer(src, dst, block_ids)`를 호출합니다 — 이 컴포넌트가
  두 티어의 `capabilities()`를 보고 host DRAM 경유 여부·direct 연결 여부·네트워크
  경유 여부를 판단해서 각 티어의 `copy_out()`/`copy_in()`을 호출합니다. Agent는
  "누구에게 옮길지"만 결정하고, "어떻게 물리적으로 옮길지"는 알 필요가 없습니다.
- **`TierDataMover`는 실행 전에 비용도 미리 알려줍니다.** Agent가 "옮길지 말지,
  옮긴다면 어디로"를 결정하려면 목적지 후보의 여유 용량뿐 아니라 **거기까지
  옮기는 데 걸리는 시간**(경로가 host 경유인지 direct인지 네트워크인지에 따라
  크게 달라짐)도 알아야 이득/손해를 계산할 수 있습니다. 이 경로 판단 지식은
  실행(`transfer`)에 쓰는 것과 완전히 같은 지식이므로, 별도로 복제하지 않고
  `TierDataMover`에 읽기 전용 조회 메서드
  `estimate_transfer_cost(src, dst, block_ids) -> TransferCostEstimate`
  (예상 소요 시간 + DIRECT/STAGED/네트워크 중 어떤 경로인지)를 하나 더
  추가합니다. Agent는 결정 단계에서 이걸 먼저 호출해 보고, 실제 이관을
  실행할 때만 `transfer()`를 호출합니다 — 두 메서드가 같은 경로 지식을
  공유하므로 "견적"과 "실행"이 항상 일치합니다.
- 시나리오: CXL Memory 티어가 용량 임계치를 초과했을 때, 일부 블록을 다른 티어
  (예: HBF)로 이관해야 하는 상황을 두 후보 각각의 sequence diagram으로 그려서
  차이를 비교합니다.
- 평가 기준: ① 전역 최적성, ② 확장성/병목, ③ 장애 격리, ④ 결정 레이턴시,
  ⑤ 구현·운영 복잡도, ⑥ 관측성(디버깅 용이성)

---

## 2. 후보 A — 중앙집중형 오케스트레이션 (Centralized Orchestration)

### 2.1 설계 철학

`TierPlacementPolicy`를 `GlobalMemoryOrchestrator`로 승격시켜, **모든 티어의
상태(부하, 여유 용량, 레이턴시 프로파일)를 주기적으로 수집하는 단일 Agent**로
만듭니다. `MemoryTier`들은 스스로 판단하지 않고 오케스트레이터의 지시
(`migrate_out`, `evict`, `allocate`)를 받는 자원 객체로 그대로 남습니다 —
DP-1 후보 1(범용성 강조)의 "티어는 얇고 수동적"이라는 철학과 자연스럽게
이어집니다. 결정이 내려진 뒤 실제 이관 실행은 §1에서 정한 공통 컴포넌트
`TierDataMover`에 위임합니다 — `GlobalMemoryOrchestrator`도 물리적 전송
경로(host 경유 여부 등)는 알지 못합니다.

### 2.2 Module View

```mermaid
graph TD
    SCHED["Scheduler / ModelLoader / GPUModelRunner"]
    ORCH["GlobalMemoryOrchestrator<br/>유일한 Agent - 1개<br/>모든 티어의 전역 상태 보유<br/>TierPlacementPolicy 의 승격판"]
    REG["MemoryTierRegistry<br/>티어 디스커버리"]
    MOVER["TierDataMover<br/>공통 컴포넌트<br/>실제 물리적 전송 실행"]

    subgraph TIERS["MemoryTier 구현체 — 수동적, 서로 직접 통신하지 않음"]
        GPUHBM["GPUHBMTier"]
        DRAMT["CPUDRAMTier"]
        CUSTOMT["CustomHBMTier"]
        CXLT["CXLTier"]
        HBFT["HBFTier"]
    end

    SCHED --> ORCH
    ORCH --> REG --> GPUHBM
    REG --> DRAMT
    REG --> CUSTOMT
    REG --> CXLT
    REG --> HBFT

    GPUHBM -. "telemetry 보고" .-> ORCH
    DRAMT -. "telemetry 보고" .-> ORCH
    CUSTOMT -. "telemetry 보고" .-> ORCH
    CXLT -. "telemetry 보고" .-> ORCH
    HBFT -. "telemetry 보고" .-> ORCH

    ORCH -- "estimate_transfer_cost 후보들 견적 조회" --> MOVER
    ORCH -- "transfer 결정 확정 후 실행 요청" --> MOVER
    MOVER -. "copy_out copy_in" .-> CXLT
    MOVER -. "copy_out copy_in" .-> HBFT

    classDef orchBox fill:#dbe7ff,stroke:#3b5bdb,color:#1c2b5e,stroke-width:2px;
    classDef tierBox fill:#eef1f4,stroke:#8d99ae,color:#22303e,stroke-width:1px;
    classDef moverBox fill:#fff3bf,stroke:#f08c00,color:#5c3c00,stroke-width:2px;
    class ORCH orchBox
    class GPUHBM,DRAMT,CUSTOMT,CXLT,HBFT tierBox
    class MOVER moverBox
```

별(star) 형태 토폴로지입니다 — 티어끼리 연결된 선이 하나도 없고, 모든 결정이
오케스트레이터(유일한 Agent)를 거칩니다. `TierDataMover`는 결정 단계(후보별
이관 비용 견적)와 실행 단계(확정된 이관 수행) 양쪽에서 등장하는 공통
컴포넌트이고, 후보 B(§3.2)에도 동일하게 등장합니다.

### 2.3 Sequence Diagram — CXL 티어 용량 초과 시나리오

```mermaid
sequenceDiagram
    participant CXLT as CXLTier
    participant HBFT as HBFTier
    participant ORCH as GlobalMemoryOrchestrator
    participant MOVER as TierDataMover

    loop 주기적 telemetry 보고
        CXLT-->>ORCH: 부하 / 여유 용량 보고
        HBFT-->>ORCH: 부하 / 여유 용량 보고
    end

    Note over ORCH: CXLTier 용량 임계치 초과 감지<br/>전역 상태 테이블에서 판단
    ORCH->>ORCH: 여유 있는 후보 티어들 추림<br/>예 HBFTier CustomHBMTier
    ORCH->>MOVER: estimate_transfer_cost dst HBFTier block_ids
    MOVER-->>ORCH: 예상 소요시간 경로종류
    ORCH->>MOVER: estimate_transfer_cost dst CustomHBMTier block_ids
    MOVER-->>ORCH: 예상 소요시간 경로종류
    ORCH->>ORCH: 여유 용량 + 이관 비용 견적 종합해<br/>목적지 HBFTier 로 확정
    ORCH->>MOVER: transfer src CXLTier dst HBFTier block_ids
    Note over MOVER: 견적 때와 같은 경로 판단 로직으로 실행
    MOVER->>CXLT: copy_out block_ids
    CXLT-->>MOVER: bytes
    MOVER->>HBFT: copy_in block_ids bytes
    MOVER-->>ORCH: 이관 완료
    ORCH->>ORCH: 전역 상태 테이블 갱신
```

### 2.4 장단점

| 항목 | 평가 |
|---|---|
| 전역 최적성 | **높음** — 모든 정보가 한 곳에 모이므로 이론상 최적 결정 가능 |
| 확장성/병목 | **낮음** — 티어 수·요청 빈도가 늘수록 오케스트레이터가 병목이 됨. 특히 KV cache처럼 매 스텝 결정이 필요한 경우 부담 |
| 장애 격리 | **낮음** — 오케스트레이터가 단일 장애점(SPOF) |
| 결정 레이턴시 | **높음** — 모든 결정이 중앙을 왕복해야 함 |
| 구현/운영 복잡도 | **낮음** — 로직이 한 곳에 모여 있어 구현·테스트가 단순 |
| 관측성 | **높음** — "왜 이렇게 결정했는지"가 한 곳의 로그로 설명됨 |

---

## 3. 후보 B — 분산 자율 협상 (Distributed Autonomous Negotiation)

### 3.1 설계 철학

`MemoryTier`는 §1의 정의대로 계속 수동적 자원 객체로 남깁니다. 대신 **각
`MemoryTier`마다 그것을 감시·대변하는 별도의 능동적 객체 `TierAgent`를
하나씩 붙입니다.** 이웃 상태를 조회/구독하는 **경량 peer-awareness 프로토콜**
(`query_neighbor_load()`, `propose_migration()`)은 `MemoryTier`가 아니라
이 `TierAgent`가 구현합니다. `MemoryTierRegistry`는 최초 디스커버리
(부트스트랩)에만 관여하고, 이후 재배치 결정은 `TierAgent`들끼리 직접
협상합니다 — 서로 직접 통신하는 mesh는 **티어가 아니라 Agent들의 mesh**입니다.
DP-1 후보 2(하드웨어 특화)의 "티어마다 고유 로직을 가질 수 있다"는 철학과
자연스럽게 이어지는 건 여전히 유효하되, 그 고유 로직은 `TierAgent` 안에 있고
`MemoryTier` 자체는 후보 A와 완전히 같은 수동적 모양을 유지합니다.

`query_neighbor_load()`만으로는 "이웃이 얼마나 여유가 있는지"만 알 뿐,
"거기까지 옮기는 데 얼마나 걸리는지"는 알 수 없습니다 — 그건 이웃 자신의
상태가 아니라 나와 그 이웃 **사이의 경로**에 대한 지식이고, §1에서 정했듯
이 지식은 `TierDataMover`에만 있습니다. 그래서 협상 중에는
`query_neighbor_load()`(이웃 상태)와 `TierDataMover.estimate_transfer_cost()`
(경로 비용) 둘을 함께 조회해서 "여유는 있지만 옮기는 데 너무 오래 걸리는
이웃"을 걸러낼 수 있어야 합니다.

### 3.2 Module View

```mermaid
graph TD
    SCHED["Scheduler / ModelLoader / GPUModelRunner"]
    IPOLICY["초기 배치 정책<br/>단순/국소적 — 최초 배치만 담당"]
    REG["MemoryTierRegistry<br/>최초 디스커버리 부트스트랩 전용"]
    MOVER["TierDataMover<br/>공통 컴포넌트<br/>실제 물리적 전송 실행"]

    subgraph AGENTS["TierAgent — 티어당 1개, 서로 직접 통신 mesh"]
        GPUHBMA["GPUHBMTier 의 Agent"]
        DRAMA["CPUDRAMTier 의 Agent"]
        CUSTOMA["CustomHBMTier 의 Agent"]
        CXLA["CXLTier 의 Agent"]
        HBFA["HBFTier 의 Agent"]
    end

    subgraph TIERS["MemoryTier 구현체 — 여전히 수동적, 서로 직접 통신하지 않음"]
        GPUHBM["GPUHBMTier"]
        DRAMT["CPUDRAMTier"]
        CUSTOMT["CustomHBMTier"]
        CXLT["CXLTier"]
        HBFT["HBFTier"]
    end

    SCHED --> IPOLICY --> REG
    REG -. "최초 등록만" .-> GPUHBM
    REG -. "최초 등록만" .-> DRAMT
    REG -. "최초 등록만" .-> CUSTOMT
    REG -. "최초 등록만" .-> CXLT
    REG -. "최초 등록만" .-> HBFT

    GPUHBMA --> GPUHBM
    DRAMA --> DRAMT
    CUSTOMA --> CUSTOMT
    CXLA --> CXLT
    HBFA --> HBFT

    CXLA <--> HBFA
    CXLA <--> CUSTOMA
    HBFA <--> CUSTOMA
    HBFA <--> DRAMA
    CUSTOMA <--> DRAMA

    CXLA -. "estimate_transfer_cost 협상 중 견적 조회" .-> MOVER
    CXLA -. "transfer 결정 확정 후 실행 요청" .-> MOVER
    MOVER -. "copy_out copy_in" .-> CXLT
    MOVER -. "copy_out copy_in" .-> HBFT

    classDef tierBox fill:#eef1f4,stroke:#8d99ae,color:#22303e,stroke-width:1px;
    classDef agentBox fill:#d8f5d0,stroke:#2f9e44,color:#1b4332,stroke-width:1px;
    classDef regBox fill:#eef1f4,stroke:#8d99ae,color:#22303e,stroke-width:1px;
    classDef moverBox fill:#fff3bf,stroke:#f08c00,color:#5c3c00,stroke-width:2px;
    class GPUHBM,DRAMT,CUSTOMT,CXLT,HBFT tierBox
    class GPUHBMA,DRAMA,CUSTOMA,CXLA,HBFA agentBox
    class REG regBox
    class MOVER moverBox
```

메시(mesh) 형태 토폴로지는 **`TierAgent`들 사이**에만 존재합니다 — `MemoryTier`
구현체들은 후보 A와 마찬가지로 여전히 서로 직접 연결되어 있지 않습니다(아래쪽
줄, 서로 연결선 없음). 각 `TierAgent`는 자신이 대변하는 `MemoryTier`
하나에만 실선으로 연결되고, 실제 물리적 전송은 후보 A와 동일한 공통
컴포넌트 `TierDataMover`에 위임합니다.

### 3.3 Sequence Diagram — CXL 티어 용량 초과 시나리오

```mermaid
sequenceDiagram
    participant CXLA as CXLTier 의 TierAgent
    participant HBFA as HBFTier 의 TierAgent
    participant CUSTOMA as CustomHBMTier 의 TierAgent
    participant MOVER as TierDataMover

    Note over CXLA: 자신의 MemoryTier.capabilities 를<br/>주기적으로 확인, 용량 임계치 초과를 스스로 감지
    CXLA->>HBFA: query_neighbor_load
    CXLA->>CUSTOMA: query_neighbor_load
    HBFA-->>CXLA: 여유 있음, latency 프로파일 회신
    CUSTOMA-->>CXLA: 여유 없음
    CXLA->>MOVER: estimate_transfer_cost dst HBFTier block_ids
    MOVER-->>CXLA: 예상 소요시간 경로종류
    CXLA->>CXLA: 이웃 응답 + 이관 비용 견적<br/>종합해 자율 결정
    CXLA->>HBFA: propose_migration block_ids
    HBFA-->>CXLA: 수락
    CXLA->>MOVER: transfer src CXLTier dst HBFTier block_ids
    Note over MOVER: 견적 때와 같은 경로 판단 로직으로 실행<br/>후보 A 와 동일한 컴포넌트, 동일한 방식
    MOVER-->>CXLA: 완료

    Note over CXLA,HBFA: 중앙 조정자 없이 완결<br/>단, HBFA 가 동시에 CustomHBMTier 의 Agent<br/>로부터도 같은 제안을 받으면 충돌 가능<br/>충돌 해소 프로토콜이 별도로 필요
```

### 3.4 장단점

| 항목 | 평가 |
|---|---|
| 전역 최적성 | **낮음~중간** — 국소 정보만으로 판단하므로 전역 최적을 보장 못 함, 두 티어가 동시에 서로에게 떠넘기다 진동(thrashing)할 위험 |
| 확장성/병목 | **높음** — 중앙 병목이 없어 티어 수가 늘어도 선형적으로 확장 |
| 장애 격리 | **높음** — 한 티어가 느려지거나 죽어도 나머지는 계속 협상 가능 |
| 결정 레이턴시 | **낮음** — 이웃끼리 바로 협상, 중앙 왕복 없음 |
| 구현/운영 복잡도 | **높음** — 합의/충돌 해소 프로토콜(동시 제안 충돌, 순환 이관 방지 등)을 직접 설계해야 하고, `MemoryTier`와 별도로 `TierAgent` N개의 생성·수명주기까지 관리해야 함 |
| 관측성 | **낮음** — 결정이 여러 티어에 분산되어 있어 "왜 이렇게 됐는지" 추적이 어려움 |

---

## 4. 두 후보 비교 및 DP-1과의 상호작용

| 평가 기준 | 후보 A: 중앙집중 | 후보 B: 분산 자율 |
|---|---|---|
| 전역 최적성 | 높음 | 낮음~중간 |
| 확장성/병목 | 낮음 | 높음 |
| 장애 격리 | 낮음 (SPOF) | 높음 |
| 결정 레이턴시 | 높음 | 낮음 |
| 구현/운영 복잡도 | 낮음 | 높음 (합의 프로토콜 필요) |
| 관측성 | 높음 | 낮음 |

### 4.1 DP-1과의 궁합 — "필요조건"이 아니라 "구현 복잡도"의 문제

먼저 분명히 해둘 것이 있습니다: 아래에서 다루는 "궁합"은 **DP-2의 어느
후보가 DP-1의 특정 선택 없이는 성립하지 않는다는 뜻이 아닙니다.**
후보A(`GlobalMemoryOrchestrator`)와 후보B(각 티어의 `TierAgent`가 갖는
`query_neighbor_load`/`propose_migration`)는 둘 다 `MemoryTier.capabilities()`라는
DP-1의 **base 인터페이스만으로 완전히 정의되고 동작**합니다 — §2.3/§3.3의
시나리오 어디에도 DP-1 후보2 전용 확장(`ComputeCapableTier` 등)은 등장하지
않습니다. §3.1에서 정리했듯 `MemoryTier` 자체는 DP-2의 두 후보 사이에서
**한 글자도 바뀌지 않습니다** — 바뀌는 건 그 위에 붙는 Agent(1개 vs N개)
뿐이므로, DP-1과의 독립성은 오히려 이 구분으로 더 명확해집니다. DP-1이
어느 쪽으로 결정되든, DP-2의 두 후보는 그 자체로 독립적으로 선택 가능합니다.
DP-2는 DP-1의 단점을 보완하기 위해 존재하는 게 아니라, 배경(`vllm-memory-abstraction-level-candidates.md`
§1.2)에서 확인한 **DP-1과는 별개의 품질 속성**(전역 최적성/확장성/장애격리)을
다루는 독립된 축입니다.

아래는 그 위에 얹히는 부수적 관찰입니다 — 조합했을 때 **구현 복잡도가 늘거나
줄어드는 정도**의 문제이지, 어떤 조합은 되고 어떤 조합은 안 된다는 이야기가
아닙니다.

- **후보 A(중앙집중) + DP-1 후보 1(범용성)**: 구현이 가장 단순해지는
  조합입니다. 오케스트레이터가 모든 티어를 하나의 관점에서 봐야 하므로,
  티어 인터페이스가 범용적일수록 오케스트레이터 구현도 단순해집니다.
- **후보 A(중앙집중) + DP-1 후보 2(특화)**: 이 조합도 문제없이 동작합니다
  — 다만 오케스트레이터가 확장 정보까지 활용해서 더 정교한 결정을 내리려면
  모든 특화 인터페이스를 알아야 하므로, "다양한 하드웨어를 한 곳이 다
  이해해야 하는 비용"이 조정 로직 레이어로 옮겨와 다시 나타날 뿐입니다.
- **후보 B(분산 자율) + DP-1 후보 2(특화)**: 각 티어가 자기 하드웨어 고유
  정보(예: CXL의 pooling 정보)를 협상에 직접 반영할 수 있어, DP-1 후보2의
  이점을 재배치 로직까지 확장하는 조합입니다.
- **후보 B(분산 자율) + DP-1 후보 1(범용)**: 이 조합도 문제없이 동작합니다
  — 다만 협상에 쓸 수 있는 정보가 범용 필드로 제한되어, 분산 협상 특유의
  이점(하드웨어별 국소 판단)을 충분히 살리지 못할 뿐입니다.

정리하면 **"후보A + 후보1", "후보B + 후보2"는 구현이 가장 매끄러운
조합**이고, 반대 조합은 **여전히 유효하게 동작하지만 복잡도나 이점 활용도
면에서 덜 효율적인 조합**입니다 — 이는 두 설계쟁점이 서로의 결과를 전제하지
않고 각자 독립적으로 결정 가능하다는 사실과 완전히 양립합니다.

### 4.2 절충안 — 계층형(Hierarchical) 구조

전부 아니면 전무가 아니라, **초기 배치는 중앙에서, 사후 재조정(migration)은
분산으로** 나누는 절충도 가능합니다 — 신규 데이터가 처음 어느 티어로 갈지는
`TierPlacementPolicy`가 결정하되(후보 A의 예측가능성/관측성 유지), 이미 배치된
데이터를 부하에 따라 재조정하는 건 각 티어의 `TierAgent`들끼리 국소적으로
처리(후보 B의 확장성 확보)하는 방식입니다. KV cache처럼 매 스텝 빈번한 신규
할당엔 후보 A의 결정 레이턴시 부담이 크므로, 실무적으로는 이 절충안이 출발점으로
더 현실적일 수 있습니다.

---

## 5. 관련 문서

- `doc-mk/vllm-memory-abstraction-level-candidates.md` — DP-1: 추상화 수준
  (범용 vs 특화), 본 문서 DP-2의 출발점
- `doc-mk/vllm-kv-cache-memory-abstraction-layer.md` — MAL 기본 설계
- `doc-mk/vllm-kv-cache-analysis.md` — 현재 KV cache 구조 (지금 vLLM은 사실상
  후보 A에 가까운 형태 — `KVCacheManager`/`BlockPool`이 단일 GPU HBM 안에서
  중앙집중적으로 블록을 관리)
