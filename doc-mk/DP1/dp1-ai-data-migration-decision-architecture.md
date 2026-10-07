# DP1 — Heterogeneous-Memory AI Data Migration Decision Architecture

> 대상 브랜치: **claude/vllm-call-path-analysis-qxulkr**  
> 배경 Architecture: **doc-mk/vllm-ai-data-migration-architecture.md**
>
> **목적:** HBM / DRAM / CXL Memory / HBF / Custom HBM / SSD 등 이기종 메모리가 혼재하는 AI Serving Runtime에서,
> 이미 존재하는 AI Data를 **언제, 무엇을, 어느 memory tier로 이동할지** 결정하는 DP1 구조를 정의한다.
>
> DP1은 **initial placement**가 아니라 **runtime data migration decision**이 대상이다.
>
> 설계 쟁점은 두 가지다.
> - **쟁점 1:** 메모리 특성 · 데이터 특성을 aware한 migration decision (C1 / C2, §6~§19)
> - **쟁점 2:** 신규 메모리 확장 시 기존 구조 변경 최소화 — **공통 Memory Backend I/F (Plug-in)** (§5.8)

---

# 1. Background / Problem

AI Serving Runtime의 메모리 계층은 단순한 HBM 단일 계층이 아니라 다음과 같이 확장될 수 있다.

~~~text
GPU HBM
  ↕
Host DRAM
  ↕
CXL Memory / HBF / Custom HBM
  ↕
SSD
~~~

각 memory resource는 Capacity, Bandwidth, Access latency, Current load/utilization,
Transfer path/cost, Compute capability 등의 특성이 다르다.

동시에 runtime이 관리하는 AI Data도 서로 다른 특성을 가진다.

- KV Cache
- Agent Memory
- LoRA Adapter
- MoE Expert
- Vector Index Cache
- 기타 runtime-managed AI data

AI Data마다 reuse pattern, lifetime, access frequency, bandwidth sensitivity, latency sensitivity가 다르기 때문에
단순히 "HBM이 부족하면 아무 data나 내린다"는 방식만으로는 장기적인 memory efficiency를 확보하기 어렵다.

따라서 DP1의 핵심 질문은 다음과 같다.

> **Runtime 중 memory state와 AI Data 특성이 변할 때,
> migration decision을 어떤 정보를 중심으로 내릴 것인가?**

본 설계에서는 두 후보를 비교한다.

1. **C1 — Resource State-driven Migration + Static Data-Memory Affinity**
2. **C2 — AI Data Behavior-driven Migration**

그리고 두 후보 모두 공통적으로 **Event-driven Migration Scheduler**를 entry point로 사용한다.

## 1.0 As-Is: vLLM의 기존 한계 (슬라이드 8)

| # | 한계 | 근거 / 정확한 표현 |
|---|---|---|
| ① | **Data Migration Layer 부재** | data object의 위치 registry도, 이동을 결정·실행하는 scheduler/executor도 없다. 이동은 KV 전용 offload 경로(HBM ↔ CPU)에 내장되어 있고 데이터 타입(KV·Weight·LoRA·Expert)을 구분하지 않는다. |
| ② | **Memory tier / Backend가 정적으로 고정** | tier별 backend가 설정으로 고정되고 정책이 tier 구성·순서에 결합되어 있다. 신규 memory마다 타입별 코드 수정이 필요하다. 예: `vllm/v1/kv_offload`의 `OffloadingSpec`은 `medium()` 하나(현재 CPU)를 가지며, 다중 tier는 `MultiConnector`의 **정적 connector 리스트**로 구성된다 (load는 먼저 hit를 알린 connector, store는 전체 fan-out). |
| ③ | **이동은 반응형, 사전 예측 없음** | 부족할 때 evict / preempt / miss 조회로 대응한다. eviction은 tier **내부** 정책(LRU/ARC)이며 하위 tier로 **내려보내는(demote) 동작이 아니다**. memory 특성(BW·latency·용량)과 data 특성을 고려한 배치·사전 이동이 없다. |

정확성 주석:

- "Allocation Backend가 고정된 tier 순서로 호출된다"는 표현은 **allocation(할당)** 보다 **store/load 경로가 설정된 backend 순서로 고정**된다는 의미로 쓰는 것이 정확하다. 순서는 data나 memory 상태와 무관하다.
- 슬라이드의 `LocalCPUBackend / LocalDiskBackend`는 이 repository에 소스가 없고 LMCache 계열 storage backend 이름이다. LMCache 경로(`lmcache_connector`)에서는 설정된 storage backend 순서로 조회/저장하는 구조로 알려져 있으나, 해당 외부 코드로 확인이 필요하다.
- vLLM 자체의 `CPUOffloadingManager`는 tier 내부 eviction(LRU/ARC)과 ref-counting만 수행하고 tier 간 이동은 하지 않는다.

## 1.1 두 가지 설계 쟁점

| 쟁점 | 질문 | 해결 구조 | 문서 위치 |
|---|---|---|---|
| **쟁점 1** | 메모리 특성 / 데이터 특성을 aware한 migration으로 추론 성능을 어떻게 최적화할 것인가 | C1 / C2 Decision Pipeline | §6 ~ §19 |
| **쟁점 2** | ScHBM, CXL-PNM, HBF, SSD-PIM 등 신규 메모리가 들어와도 기존 구조 변경을 어떻게 최소화할 것인가 | **공통 Memory Backend I/F (Plug-in)** | **§5.8** |

쟁점 1만 다루면 decision plane이 memory 종류를 직접 알게 되어,
신규 memory가 추가될 때마다 Selector/Monitor/Eviction 로직을 수정해야 한다.
따라서 DP1은 **"Data Migration 알고리즘"(C1/C2)과 "Memory 추상화 I/F"(§5.8)를 분리된 두 축**으로 설계한다.

~~~text
              Decision Plane (C1 / C2)           ← 쟁점 1: 무엇을/언제/어디로
                       │
         ┌─────────────▼─────────────┐
         │ Common Memory Backend I/F │            ← 쟁점 2: 신규 memory는 plug-in으로 편입
         └─────────────┬─────────────┘
   HBM · ScHBM · DRAM · CXL-PNM · HBF · SSD · SSD-PIM · + New
~~~

---

# 2. DP1과 공통 Migration Architecture의 관계

배경 문서 **doc-mk/vllm-ai-data-migration-architecture.md**는
migration decision 이후의 실제 data movement 구조를 정의한다.

현재 DP1의 상위 흐름은 다음처럼 본다.

~~~text
Runtime Event
    │
    ▼
DP1 Migration Scheduler
    │  asynchronous event dispatch
    ▼
C1 or C2 Decision Pipeline
    │
    │ MigrationDecision / MigrationIntent
    ▼
Migration Control Plane
    │
    ▼
Transfer Data Plane
~~~

C1/C2 decision pipeline이 memory를 참조하는 경로는 **공통 Memory Backend I/F** 하나다.

~~~text
C1 or C2 Decision Pipeline
    │ MemoryDescriptor / MemoryTelemetry / MemoryTransferBinding
    ▼
Common Memory Backend I/F (Plug-in)  ◄── 신규 memory 등록 지점 (§5.8)
    │ handler_key
    ▼
TransferHandlerRegistry (공통 migration subsystem)
~~~

DP1의 책임은 다음과 같다.

~~~text
WHEN to evaluate migration?
  → Event + Migration Scheduler

WHAT to move?
WHERE to move?
  → C1 / C2 decision pipeline
~~~

반면 공통 migration subsystem의 책임은 다음과 같다.

~~~text
HOW to move?
HOW to order / execute transfer?
HOW to keep consistency?
HOW to commit / rollback?
~~~

따라서 DP1이 생성한 decision은 최종적으로 다음과 같은 MigrationIntent로 변환된다.

~~~text
MigrationIntent
 ├─ action                    # MOVE | REPLICATE | DROP | REMAP | RECLASSIFY  (§2.1)
 ├─ data_refs[]
 ├─ source_resource_id
 ├─ target_resource_id?       # DROP / RECLASSIFY에서는 생략 가능
 ├─ reason
 ├─ priority
 ├─ dependency_type
 └─ policy_metadata
~~~

### 2.1 MigrationAction — "이동"은 항상 copy가 아니다

DP1 decision이 byte copy를 동반하지 않는 선택지도 표현할 수 있도록 `action`을 둔다.
이는 transfer 비용이 큰 이기종 환경에서 **"복사하지 않는 것"도 decision의 선택지**가 되게 한다.

| action | 의미 | byte copy | 비용 특성 | 대표 사용 |
|---|---|---|---|---|
| `MOVE` | target에 복사 후 source 해제 | ✅ | 전송 + commit | 일반 demotion/promotion |
| `REPLICATE` | target에 복사, source 유지 | ✅ | 전송 (source 해제 없음) | hot 데이터의 상위 tier 복제 (예: LoRA) |
| `DROP` | source만 해제 (복제본/재계산 경로 존재) | ❌ | 없음 (+ 이후 miss 시 recompute/refetch) | 하위 tier 복제본이 있는 데이터 demotion |
| `REMAP` | 주소 매핑/소유권만 변경 | ❌ | metadata 갱신 | CXL shared pool 소유권 이전, page remap |
| `RECLASSIFY` | 위치 그대로 hotness/eviction priority/pin 상태만 변경 | ❌ | metadata 갱신 | 위치 변경 없이 다음 decision 입력만 갱신 |

- `REPLICATE`로 만든 복제본은 이후 demotion 시 `DROP`으로 끝나므로 **write 비용이 큰 매체(HBF/SSD-PIM, §5.9.5)에 유리**하다.
- `DROP`은 데이터를 재현 가능한 경우(복제본 존재, KV recompute 등)에만 허용한다. 재현 불가능 데이터의 `DROP`은 금지하며, 이 판정은 Registry의 replica/recomputable 정보에 의존한다 (C1: generic `replica_count`, C2: type별 recomputability).
- near-data compute(compute-to-data)와 in-place transform(quantization 등)은 data 이동이 아니므로 DP1 action이 아니다 (DP2/DP4, KV compression은 §3.2 out of scope). 단 destination 후보 제약으로 `near_data_compute` flag만 사용한다 (§5.8.3).
- 공통 migration architecture의 `MigrationIntent`에도 동일한 `action` field가 반영되어 있으며(§1.1, state machine 경로는 §7.1), 생략 시 `MOVE`로 해석된다.

DP1은 실제 DMA / P2P / CXL / NVMe transfer를 수행하지 않는다.
그 부분은 공통 **MigrationCoordinator → MigrationPlanner → execution-side scheduler/queue → MigrationExecutor → TransferHandler** 구조가 담당한다.

> **주의:** 본 문서의 **DP1 Migration Scheduler**는 Event를 받아 migration decision cycle을 시작하는 orchestration component다.  
> 배경 architecture의 execution-side scheduler/queue와 역할이 다르다.

---

# 3. Design Scope

## 3.1 In Scope

- runtime event 기반 migration decision trigger
- Migration Scheduler를 통한 비동기 decision pipeline 호출
- memory resource state monitoring
- resource pressure / trend 분석
- Data Object Registry 기반 object 위치/크기/tier 조회
- **공통 Memory Backend I/F 정의** — MemoryDescriptor / MemoryTelemetry / MemoryTransferBinding / plug-in 등록 규약 (§5.8)
- 신규 memory 편입 시 decision plane 무변경 원칙 및 편입 절차
- **MigrationAction 선택** (MOVE / REPLICATE / DROP / REMAP / RECLASSIFY) — copy 없는 선택지 포함 (§2.1)
- DP1이 Transfer Handler에 요구하는 설계 포인트와 노출 정보 정의 (§5.9)
- migration 대상 data 후보 선택
- destination memory tier 선택
- AI Data별 static affinity 반영
- AI Data runtime behavior monitoring
- behavior trend 분석 / future behavior prediction
- migration decision 생성
- 공통 migration subsystem으로 MigrationIntent 전달

## 3.2 Out of Scope

- initial data placement
- 실제 byte transfer mechanism
- 개별 memory backend 구현체(vendor driver) 및 TransferHandler **구현** — 공통 migration architecture 소관 (설계 포인트는 §5.9)
- allocation reserve/release, source pin / version check / atomic location commit
- migration failure rollback
- Prefill execution resource 선택 — DP2
- Agent tool-call lifecycle에 따른 KV residency 관리 — 별도 DP
- KV compression / recompute policy
- **노드 간(inter-node) data 이동** — 서버 밖(다른 노드, 원격 메모리)으로의 이동·전송 결정은 DP0 소관이다 (아래 §3.3)

특히 **Agent-aware KV 관리**는 DP1의 data movement policy와 구분한다.

~~~text
DP1
  resource/data behavior를 보고
  "어떤 KV를 어느 tier로 이동할지" 결정

Agent Tool-aware KV Residency
  tool call / tool wait lifecycle을 보고
  "언제 KV를 유지/회수/복구할지" 관리
~~~

따라서 C1에서 동적 Agent lifecycle을 직접 해석하지 않더라도,
대표적인 KV 특성은 static affinity hint로 반영하고,
tool-call 시점의 세밀한 KV lifecycle 제어는 별도 구조에서 보완한다.

## 3.3 설계 제약 (Constraints)

- **C-S1. 이동 범위는 단일 노드(한 서버) 내부로 한정한다.** DP1의 migration은 한 서버 안의 메모리 계층(HBM, Custom HBM, DRAM, CXL-PNM, HBF, SSD/SSD-PIM) 사이의 data 이동만 결정한다. 다른 노드나 원격 메모리를 tier로 보는 이동은 DP1이 결정하지 않는다.
- **C-S2. 노드 간 이동은 DP0의 결정이며, DP1과는 접점 계약(DP0 C5: vLLM KV 이벤트의 `medium` 필드, 메트릭, `kv_transfer_params`, NIXL 전송)으로만 연결한다.** DP1은 노드 간 전송 결과로 들어온 data를 노드 안 tier에 배치·재배치할 뿐, 노드 간 전송 여부를 정하지 않는다.
- **C-S3. 평가(Evaluation/DP1)도 단일 노드 시스템(GPU 8장 서버 1대, SYS profile)만 모델링한다.** 노드 간 전송 비용과 원격 tier는 시뮬레이터에 없다.
- **C-M. 실행·일관성·이동 중 접근 hazard 제약**(copy-then-commit, 부분 복사/해제 슬롯/이동 중 쓰기/이동 중 prefix hit 금지, 다중 rank, endurance 등)은 [`dp1-constraints-and-invariants.md`](dp1-constraints-and-invariants.md)에 목록으로 정리했다 (근거 태그: 문서/vLLM 코드/제안/가정).

---

# 4. Candidate Overview

| 구분 | C1 | C2 |
|---|---|---|
| 구조명 | Resource State-driven Migration + Data-Memory Affinity | AI Data Behavior-driven Migration |
| 공통 trigger | Event → Migration Scheduler | Event → Migration Scheduler |
| 핵심 decision signal | Memory resource state | Per-data runtime behavior |
| 동적 관찰 대상 | Capacity / BW / Load / pressure trend | Reuse / access / lifetime / tool-related behavior |
| Data Object Registry 사용 | **Type-agnostic placement metadata**: object ID, 위치, 크기, 현재 tier 등만 관리 | **Type-aware data registry**: object ID + data type별 metadata/특징 관리 |
| AI Data 정보 활용 | Registry는 data type을 모르며, eviction policy는 generic placement metadata로 대상 선택. Static affinity는 별도 Mapper에서 반영 | Registry 자체가 KV/Agent Memory/LoRA/MoE/Vector Index 등 data type별 특징을 관리하고 behavior 분석에 활용 |
| 주요 목적 | 빠른 pressure 대응과 전체 pool utilization | Fine-grained data-tier matching |
| 대표 비용 | 낮은 decision overhead | Monitoring / characterization / prediction overhead |

가장 중요한 차이는 다음과 같다.

> **C1은 "메모리 상태가 어떻게 변하는가"를 중심으로 결정하고,  
> C2는 "데이터가 앞으로 어떻게 사용될 것인가"를 중심으로 결정한다.**

Data Object Registry는 두 후보에 모두 존재하지만 **registry의 역할과 schema 자체가 다르다.**

- **C1 Registry:** data type을 모르는 type-agnostic placement registry. 위치·크기·현재 tier 등 generic metadata만 관리한다.
- **C2 Registry:** data type별 특징을 관리하는 type-aware AI Data registry. KV Cache / Agent Memory / LoRA / MoE / Vector Index 등 class별 metadata를 가진다.

즉 C1/C2 차이는 단순히 "같은 Registry를 다르게 사용"하는 수준이 아니라, **Registry abstraction 자체의 정보 모델이 다르다.**

---

# 5. Common Components

C1/C2는 Event, Migration Scheduler, Resource Manager, Selector/Executor boundary를 공통으로 사용한다.  
단, **Data Object Registry는 이름만 공통이며 C1/C2의 schema와 책임은 다르다.**

## 5.1 Event Source

migration 판단이 필요한 runtime state change를 Event로 전달한다.

구체적인 Event type은 구현에 따라 달라질 수 있지만,
DP1 관점에서는 다음처럼 추상화한다.

~~~text
MigrationEvent
 ├─ event_type
 ├─ timestamp
 ├─ related_resource
 ├─ related_data_ref
 └─ optional_metadata
~~~

Event는 policy logic을 직접 수행하지 않는다.

## 5.2 Migration Scheduler

Migration Scheduler는 DP1 decision plane의 **entry / orchestration component**다.

역할:

- Event 수신
- Event를 비동기로 처리
- C1 또는 C2의 monitoring / analysis pipeline을 실행하도록 trigger
- 중복/과도한 decision invocation을 조정할 수 있는 entry point 제공
- 최종 migration decision이 생성되면 공통 migration subsystem으로 넘김

핵심 흐름:

~~~text
Event
  ↓
Migration Scheduler
  ↓ async event push
C1 Resource State Monitor
or
C2 Data Behavior Monitor
~~~

Migration Scheduler가 resource/data 특성을 직접 분석하지는 않는다.

## 5.3 Data Object Registry — C1/C2에서 abstraction이 다름

C1과 C2 모두 "Data Object Registry"라는 이름의 저장소가 있지만,
동일한 schema를 공유하는 것으로 보지 않는다.

### C1 — Type-agnostic Placement Registry

C1 Registry는 **data type을 해석하지 않는다.**
eviction에 필요한 generic placement metadata만 관리한다.

~~~text
C1DataObjectRecord
 ├─ object_id
 ├─ size_bytes
 ├─ current_tier
 ├─ current_resource / location
 ├─ pin / movable state
 └─ basic lifecycle state
~~~

핵심적으로 다음 질문에만 답한다.

~~~text
"어디에 있는가?"
"얼마나 큰가?"
"지금 이동 가능한가?"
~~~

Data Eviction Manager는 이 정보를 조회한 뒤
LRU / age / size / pressure-relief 같은 **generic eviction policy**로 victim을 선택한다.

~~~text
Data Eviction Manager
  → C1 Data Object Registry 조회
  → 위치 / 크기 / tier / movable state 확인
  → eviction policy 적용
  → victim candidate 생성
~~~

C1 Registry는 KV Cache인지 LoRA인지 MoE Expert인지 구분하지 않는다.
C1의 Data-Memory Affinity는 Registry가 아니라 **별도의 Data-Memory Affinity Mapper**에서
대표적인 operation/data characteristic을 static hint로 반영한다.

### C2 — Type-aware AI Data Registry

C2 Registry는 object identity뿐 아니라 **data type별 의미와 특징을 관리한다.**

~~~text
C2DataObjectRecord
 ├─ object_id
 ├─ data_type
 ├─ current_tier / location
 ├─ size_bytes
 ├─ class_metadata
 └─ behavior_metadata_ref
~~~

예:

~~~text
Data Object Registry
 ├─ KV Cache
 │   └─ KV-specific metadata
 ├─ Agent Memory
 │   └─ lifetime / session metadata
 ├─ LoRA Adapter
 │   └─ adapter metadata
 ├─ MoE Expert
 │   └─ expert metadata
 ├─ Vector Index Cache
 │   └─ index metadata
 └─ Data Class Metadata
~~~

따라서 C2에서는 Data Behavior Monitor가
Registry의 type-specific metadata와 runtime event를 함께 사용해
각 data class의 access/reuse/lifetime behavior를 해석한다.

## 5.4 Resource Manager

전체 memory resource에 대한 공통 정보를 관리한다.

~~~text
Resource Manager
 ├─ Telemetry Collector            # Backend의 MemoryTelemetry 집계
 └─ Memory Registry                # MemoryBackend plug-in 등록부 (§5.8)
~~~

Resource Manager는 개별 memory를 직접 알지 않고,
**공통 Memory Backend I/F(§5.8)로 등록된 plug-in**을 통해서만 memory 정보를 얻는다.
신규 memory가 추가되어도 Resource Manager 자체는 변경하지 않는다.

### Telemetry Collector

runtime dynamic state를 수집한다.

- free / used capacity
- bandwidth utilization
- queue / load
- transfer bandwidth
- contention
- memory pressure
- moving average / trend

### Memory Registry

resource의 relatively static capability를 관리한다.
각 항목은 Backend plug-in이 제공하는 **MemoryDescriptor**(§5.8.3)에서 채워지며,
Memory Registry는 이를 등록·조회하는 **MemoryBackendRegistry** 역할을 한다.

- capacity
- nominal bandwidth
- nominal latency
- topology / connectivity
- memory type
- compute capability
- transfer capability
- granularity / access path / write BW / endurance / shared link (§5.8.3)

## 5.5 Destination Tier Selector

주어진 migration candidate에 대해 destination memory resource/tier를 결정한다.
memory 후보는 **Memory Backend I/F의 capability_flags / telemetry / transfer binding**으로만 조회·필터링한다 (§5.8).

## 5.6 Migration Data Selector

실제로 이동할 data object를 선택한다.

## 5.7 Migration Executor Boundary

슬라이드의 Migration Executor는 DP1 decision plane의 **출구**다.
Destination Tier Selector와 Migration Data Selector가 결정한 source / target / data object를
공통 migration architecture로 넘기는 execution boundary로 본다.

~~~text
Destination Tier Selector  ┐
                           ├─► Migration Executor (boundary) ─► 공통 Migration subsystem
Migration Data Selector    ┘
~~~

상세 구현에서는 boundary 뒤에서 다음 순서로 처리된다.

~~~text
MigrationDecision → MigrationIntent → MigrationCoordinator → MigrationExecutor → TransferHandler
~~~

- 슬라이드의 단순 구조에서는 Selector 다음에 Migration Executor를 직접 그리지만, 실제 transfer는 공통 Migration Control Plane을 거쳐 수행된다.
- **Migration Executor는 Memory Backend I/F와 직접 연결하지 않는다.** Memory Backend I/F는 Resource Manager 아래에 붙는다 (§5.8.2).
  실제 전송 시 binding(③)과 staging primitive를 쓰는 것은 공통 subsystem의 TransferHandler이며 DP1 범위 밖이다 (§5.9).

---

## 5.8 Common Memory Backend Interface (Plug-in) — 설계 쟁점 2

> **설계 쟁점 2:** 신규 메모리(ScHBM, CXL-PNM, HBF, SSD-PIM 등)가 확장될 때 **기존 구조 변경을 최소화**한다.

### 5.8.1 문제: As-Is는 Tier가 코드에 고정되어 있다

기존 vLLM/KV Offload 구조는 memory를 `HBM / CPU DRAM / Disk SSD` 세 tier로 가정하고,
tier마다 backend가 별도로 고정되어 있다 (예: `LocalCPUBackend`, `LocalDiskBackend`).

~~~text
As-Is
  data type별 정책 ──(tier 이름 직접 참조)──► CPU backend / Disk backend
  신규 memory 추가 = 정책·backend·transfer 경로를 data type마다 수정
~~~

이 상태에서 C1/C2의 Selector, Monitor, Eviction Manager가 `if tier == "CXL"` 식으로 memory를 직접 알면,
**Migration Layer를 도입해도 신규 memory마다 decision plane 전체를 수정**하게 되어 쟁점 2를 해결하지 못한다.

따라서 DP1은 "무엇을 어디로 옮길지"의 decision 구조(C1/C2)와 별개로,
**decision plane이 memory를 바라보는 유일한 창구인 공통 Memory Backend I/F**를 정의한다.

### 5.8.2 위치와 책임 — Component View (슬라이드 8~10 기준)

Common Memory Backend I/F는 **Resource Manager 아래**에 붙고, decision 모듈은 I/F를 직접 호출하지 않는다.
슬라이드와 동일하게 decision plane에서 Resource Manager와 직접 연결되는 모듈은 **Resource State Monitor(C1)** 와 **Destination Tier Selector(C1/C2)** 뿐이다.

#### 5.8.2.1 Component Diagram

~~~text
  Memory plug-in:  HBM · ScHBM · DRAM · CXL-PNM · HBF · SSD · SSD-PIM · +New
                                    │ implements
  ┌─────────────────────────────────▼───────────────────────────────────┐
  │ 공통 Memory Backend I/F (Plug-in)                                   │
  │   ② Telemetry         ① Descriptor          ③ Binding               │
  │   (used/free, BW,      (capacity, BW,        (handler_key,          │
  │    queue, link util)    latency, flags)       est. transfer cost)   │
  └───────┬──────────────────────┬───────────────────┬──────────────────┘
          │ collect()            │ register()        │ get_binding()
  ┌───────▼──────────┐   ┌───────▼───────────────────▼──────┐
  │ Telemetry        │   │ Memory Registry                  │   ← Resource Manager
  │ Collector        │   │ (descriptor·binding 캐시)         │
  └───────┬──────────┘   └───────────────┬──────────────────┘
          │ ② capacity·BW·load           │ ①③ capability·transfer cost
          ▼                              ▼
  ┌──────────────────┐            ┌───────────────────────┐
  │ Resource State   │            │ Destination Tier      │
  │ Monitor (C1)     │            │ Selector (C1, C2)     │
  └──────────────────┘            └───────────────────────┘
~~~

C2에는 Resource State Monitor가 없으므로 Telemetry Collector의 출력도 Destination Tier Selector로 간다.

~~~text
  Telemetry Collector ──② capacity·BW·load────┐
                                              ▼
  Memory Registry ──────①③ capability·cost──► Destination Tier Selector (C2)
~~~

슬라이드 10(Affinity 반영안)의 C1은 Resource Manager가 두 박스로 나뉘어 있다
(Telemetry Collector 쪽 → Resource State Monitor, Memory Registry 쪽 → Destination Tier Selector).
I/F의 면(②, ①③)과 연결 관계는 동일하며 그림에서만 분리된 것이다.

#### 5.8.2.2 어떤 I/F 면을 누가 언제 호출하고, 무엇을 누구에게 전달하는가

| I/F 면 | 호출하는 Resource Manager 기능 | 호출 시점 | 전달 대상 | 전달 정보 |
|---|---|---|---|---|
| ① Descriptor | Memory Registry `register()` → `backend.descriptor()` | boot / memory hot-plug (이후 캐시, 변경 시에만 재조회) | **Destination Tier Selector** | **capability**: capacity, ext/int BW, latency, gpu_reachable, primitives, capability_flags (§5.8.3) |
| ③ Binding | Memory Registry `get_binding()` → `backend.transfer_binding()` | `register()` 시 캐시, Selector 조회 시 반환 | **Destination Tier Selector** | **transfer cost**: est_transfer_bw / est_setup_cost, hop 수, shared link (§5.8.5) |
| ② Telemetry | Telemetry Collector `collect()` → `backend.telemetry()` | 상시 (주기 pull 또는 backend push), decision 경로 밖 | **Resource State Monitor** (C1), **Destination Tier Selector** (C2) | **capacity·BW·load**: used/free, BW util, queue, shared_link_util (§5.8.4) |

- `register()`, `get_binding()`, `collect()`는 Resource Manager 내부 기능의 **제안 명칭**이다. 실제 이름은 구현에서 확정한다.
- ④ health/lifecycle은 슬라이드에 그리지 않았다. health가 변하면 Resource Manager가 `RESOURCE_CHANGED` event를 Migration Scheduler로 보낸다 (§5.8.2.3 규칙 5).
- Data Eviction Manager, Data-Memory Affinity Mapper, Migration Data Selector는 Resource Manager와 직접 연결되지 않는다.
  victim 선정 단위와 전송 제약 같은 memory 정보는 **Destination Tier Selector의 feasibility 판단**으로 반영된다.

#### 5.8.2.3 호출 규칙

1. **Decision 모듈은 Backend를 직접 호출하지 않는다.** Resource Manager(Memory Registry, Telemetry Collector)만 본다.
2. **Descriptor / Binding은 캐시한다.** `register()` 시 1회 읽고, `REGISTERED / UNREGISTERED / HEALTH_CHANGED` event로만 갱신한다. decision cycle마다 backend를 재조회하지 않는다.
3. **Telemetry는 decision 경로 밖에서 수집한다.** Telemetry Collector가 비동기로 수집하고, decision cycle은 시작 시점의 snapshot을 읽는다. cycle 도중 값이 바뀌어도 한 번의 decision은 일관된 입력을 본다.
4. **Staleness를 명시한다.** snapshot에는 수집 시각이 있고, 허용 age를 넘은 metric은 `None`으로 취급한다 (§5.8.4).
5. **상태 변화는 event로 통지한다.** backend `health()`가 변하면(thermal throttle, 링크 열화, memory 제거) Resource Manager가 `RESOURCE_CHANGED` event를 Migration Scheduler로 보내 재평가를 일으킨다.
6. **쓰기 권한은 control plane만 가진다.** `reserve/release`, location commit, transfer 시작은 공통 Migration subsystem이 수행한다. decision plane은 읽기 전용이다 (§5.8.7 원칙 7).
7. **Memory 이름 분기 금지.** Selector는 `capability_flags`와 수치 field로만 memory를 고른다 (§5.8.7 원칙 1).
8. **실제 전송은 DP1 범위 밖이다.** 공통 Migration subsystem의 TransferHandler가 binding(③)의 `handler_key`로 직접/staged 경로를 선택한다 (§5.9). 슬라이드 8의 To-Be 그림에서 I/F는 Resource Manager에 연결된다.

#### 5.8.2.4 Decision Cycle에서의 사용 흐름 (C1 예)

~~~text
[boot / hot-plug]
  Memory Registry.register(backend)
    → backend.descriptor() / transfer_binding()  → ①③ 캐시

[상시, decision 경로 밖]
  Telemetry Collector.collect()
    → backend.telemetry()                        → ② 최신값 + 이력 보관

[Event 발생 → Migration Scheduler → async push]
  Resource State Monitor
    ← Telemetry Collector : ② capacity·BW·load  → ResourceState, pressure, trend
  ...(C1 pipeline: Trend Analyzer / Eviction Manager / Affinity Mapper)...
  Destination Tier Selector
    ← Memory Registry     : ①③ capability · transfer cost
    ⇒ feasible memory ∩ affinity ∩ 여유 용량(upstream ResourceState) → target tier
  Migration Data Selector → MigrationDecision → MigrationIntent
    → 공통 Migration subsystem (reserve · transfer · commit)
~~~

C2는 Resource State Monitor → Trend Analyzer 구간을 `Behavior Monitor → Behavior Trend → Future Predictor`로 대체하고,
Destination Tier Selector가 Telemetry Collector(②)와 Memory Registry(①③)를 모두 읽는다.

#### 5.8.2.5 책임 경계

| 구분 | Memory Backend I/F가 하는 일 | 하지 않는 일 |
|---|---|---|
| **Memory 정보 제공** | 자신의 capability / 현재 상태 / transfer 방식을 표준 형식으로 노출 | 어떤 data를 둘지 판단 (→ C1/C2) |
| **Memory 이름 은닉** | decision plane에 `memory_type` 분기를 요구하지 않음 | data type(KV/LoRA/MoE) 해석 |
| **Transfer 연결** | 공통 TransferHandler를 선택할 수 있는 binding 정보 제공 | byte copy 자체 수행 (→ 공통 migration subsystem) |
| **Allocation 단위 노출** | 이동 가능한 최소 단위(granularity)와 정렬 제약 제공 | 신규 data placement 결정 (initial placement는 out of scope) |

> 공통 Migration architecture의 의존성 규칙 7 — "MemoryTopology와 MemoryResourceRegistry는 data type을 모른다" — 와 일치한다.
> Memory Backend I/F는 **memory를 data-type-agnostic하게 기술**하고,
> data type 인지는 C1의 Affinity Mapper 또는 C2의 Type-aware Registry가 담당한다.

### 5.8.3 ① MemoryDescriptor — 정적 capability

Memory Registry가 기존에 관리하던 relatively static 정보를 plug-in이 **자기 기술(self-describing)** 하도록 표준화한다.

~~~text
MemoryDescriptor
 ├─ resource_id                  # e.g. "hbm", "custom_hbm", "cxl_pnm", "ssd_pim"
 ├─ medium                       # 분류 라벨 (정보용; decision 분기에는 사용 금지)
 ├─ capacity_bytes
 ├─ ext_bw / int_bw              # 외부(GPU/Host 방향) BW vs 메모리 내부 BW — 비대칭이 핵심
 ├─ write_bw?                    # read와 다를 때만 (e.g. HBF)
 ├─ latency
 ├─ access_path[]                # hop 목록: "gpu->host:pcie5_x16", "host->dev:cxl" ...
 ├─ gpu_reachable                # GPU 직접 접근 가능 여부
 ├─ shared_link_group?           # 같은 물리 링크를 공유하는 memory/GPU 묶음 (contention domain)
 ├─ scope                        # per_gpu | per_scaleup_domain  (용량/BW 합산 단위)
 ├─ granularity? / alignment?    # 이동/할당 최소 단위 (config에는 아직 없음 — 확장 field)
 ├─ supported_primitives[]       # near-data compute: QK_GEMM, SOFTMAX, AV_GEMM, GEMV ...
 ├─ compute_flops? / attn_bw_eff?
 ├─ write_amplification / endurance_budget?
 ├─ tdp_watts
 ├─ capability_flags             # 아래 참조 (위 수치에서 파생 가능한 분류 어휘)
 ├─ provenance                   # SPEC | PUBLIC | ASSUMED  + 근거
 └─ tier_rank_hint?              # optional: 운영자 override
~~~

> field 정의는 `Evaluation/DP1/sim/configs/memories_default.json`, `clusters.json`의 실제 항목에서 역으로 도출했다 (§5.8.10 참조).
> 즉 시뮬레이터가 이미 쓰는 memory spec schema가 곧 MemoryDescriptor의 초안이다.

`capability_flags`는 **Selector가 사용하는 어휘**다. memory 이름 대신 flag로 후보를 거른다.

| capability flag | 의미 | 파생 규칙(config 기준) | 해당 memory (Evaluation/DP1/sim) |
|---|---|---|---|
| `gpu_direct_access` | GPU가 직접 load/store 가능 | `gpu_reachable == true` | HBM, HBF |
| `host_staged_only` | Host/CPU를 경유해야 접근 | `gpu_reachable == false` | DRAM, Custom HBM, CXL-PNM, SSD-PIM |
| `high_bw` | 외부 BW가 상위 구간 | `ext_bw` 기준 | HBM (8 TB/s), HBF (1 TB/s) |
| `large_capacity` | 용량 우선 tier | `capacity` 기준 | DRAM 1 TiB, HBF 2 TiB, SSD-PIM 16 TiB |
| `bw_asymmetric` | 내부 BW ≫ 외부 BW | `int_bw / ext_bw` ≥ 임계 | Custom HBM (254x), SSD-PIM (12x), DRAM/CXL-PNM (6x) |
| `write_limited` | write BW/endurance 제약 | `write_bw` 또는 `endurance_budget` 존재 | HBF (50 GB/s, 100 PB), SSD-PIM (10 PB) |
| `near_data_compute` | memory 측 연산 가능 | `supported_primitives` ≠ ∅ | Custom HBM, CXL-PNM (attention), SSD-PIM (GEMV) |
| `shared_link` | 물리 링크를 다른 자원과 공유 | `shared_link_group` 존재 | Custom HBM (도메인 8 GPU가 PCIe5 x16 1가닥 공유) |

> flag는 가능한 한 **수치 field에서 파생**한다 (수동 지정 최소화). 수치가 없을 때만 plug-in이 직접 선언한다.

> `near_data_compute`는 DP1에서 **"존재 여부"만 노출**한다.
> 해당 memory에서 연산을 수행할지(compute placement)는 DP2/DP4의 책임이며,
> DP1은 이 flag를 destination 후보 제약 정보로만 쓴다.

**Tier rank는 hard-coded enum이 아니라 descriptor에서 파생한다.**

~~~text
tier_rank(resource)
  = f(ext_bw, latency, capacity, gpu_reachable)   # 기본 derivation (GPU 관점 접근 BW = ext_bw)
    overridden by tier_rank_hint (있을 때만)
~~~

주의: **tier order는 total order가 아니다.** Evaluation/DP1/sim 값 기준으로
DRAM(64 GB/s, 200 ns)과 CXL-PNM(63 GB/s, 300 ns), Custom HBM(63 GB/s, 2 µs)은 `ext_bw`가 사실상 같고,
HBF(1 TB/s, 5 µs)는 BW는 높지만 latency가 DRAM보다 25배 나쁘다.
따라서 `tier_order()`는 단일 순서가 아니라 **partial order + 동순위 그룹**을 반환하고,
동순위 그룹 안의 선택은 Selector가 capability/affinity로 결정한다.

이를 통해 "Promotion/Demotion" (§17)의 방향 판단도 `HBM > DRAM > SSD` 고정 순서가 아니라
`MemoryBackendRegistry.tier_order()`를 사용한다. 신규 memory는 descriptor 값에 따라 자동으로 순서에 삽입된다.

### 5.8.4 ② MemoryTelemetry — 동적 상태

Telemetry Collector는 backend별 telemetry를 **동일 schema**로 집계한다 (§5.4, §8.2의 `ResourceState` 입력).

~~~text
MemoryTelemetry
 ├─ resource_id
 ├─ timestamp
 ├─ used_bytes / free_bytes
 ├─ read_bw_util / write_bw_util
 ├─ queue_depth
 ├─ observed_latency (optional)
 ├─ transfer_inflight_bytes
 ├─ shared_link_util             # shared_link_group의 현재 점유율 (e.g. PCIe5 x16 공유 링크)
 ├─ error / throttle state       # thermal throttle, wear, link degrade
 └─ extension: dict              # vendor-specific metric (decision plane은 무시 가능)
~~~

- **Pull**(`telemetry()`)과 **Push**(`subscribe()`)를 모두 허용하되, 지원하지 않는 metric은 `None`으로 둔다.
- Resource State Monitor는 `None` metric을 **graceful degradation** (사용 가능한 metric만으로 pressure 계산) 한다.
  → 신규 memory가 일부 metric만 제공해도 C1 pipeline이 동작한다.
- `extension` field는 vendor 고유 metric 전달용이며, core decision logic은 의존하지 않는다.

### 5.8.5 ③ MemoryTransferBinding — 공통 Transfer Handler 연결

DP1은 transfer를 수행하지 않지만, **"이 memory와 저 memory 사이를 옮길 수 있는가 / 비용이 어떤가"**는
Destination Tier Selector의 feasibility 판단에 필요하다.

~~~text
MemoryTransferBinding
 ├─ resource_id
 ├─ supported_peers[]            # 직접/경유 가능한 상대 resource
 ├─ path_type                    # direct | staged(via host)  ← descriptor.access_path / gpu_reachable에서 파생
 ├─ handler_key                  # TransferHandlerRegistry.resolve(src_type, dst_type) 용 key
 ├─ est_transfer_bw / est_setup_cost
 └─ constraints                  # alignment, max transfer size, async 지원 여부
~~~

- `handler_key`로 **공통 migration subsystem의 TransferHandler**(CudaP2P / HostDMA / CXL / NVMe / VendorCustom)에 연결된다.
- 신규 memory에 기존 handler로 처리 불가한 경로가 있으면 **VendorCustomMemoryHandler 1개만 추가**하고 `handler_key`로 등록한다.
- Selector는 `est_transfer_bw / est_setup_cost`를 feasibility와 cost 계산에만 사용한다.

### 5.8.6 신규 Memory 편입 절차 — 변경 범위

예: **ScHBM** 또는 **CXL-PNM**을 신규 도입하는 경우.

~~~text
추가하는 것
  1. resource/backends/<new_memory>.py   # MemoryBackend 구현 (descriptor/telemetry/binding)
  2. (필요 시) TransferHandler 1개        # 기존 handler로 불가한 경로가 있을 때만
  3. 운영 config: resource 등록, (선택) tier_rank_hint

변경하지 않는 것
  - C1: Resource State Monitor, Trend Analyzer, Eviction Manager, Affinity Mapper, Selector
  - C2: Behavior Monitor, Predictor, Selector, Type-aware Registry
  - Migration Scheduler / Event 구조
  - Affinity Table (capability class key 사용 시)
~~~

조건부로 수정이 필요한 경우 (**예외**이며 설계 리뷰 대상):

| 상황 | 필요한 변경 | 이유 |
|---|---|---|
| 기존 flag로 표현 불가한 capability | capability flag vocabulary에 **추가** (기존 flag 의미 변경 금지) | vocabulary는 append-only |
| 신규 memory의 새로운 접근 경로(hop) 유형 | `access_path` hop 종류 추가 + Selector feasibility 규칙 1줄 | feasibility 판단 입력 부족 |
| Affinity Table이 memory 이름을 key로 가짐 | capability class key로 마이그레이션 | §8.7 규칙 위반 |

### 5.8.7 Backend I/F의 설계 원칙

1. **Capability-driven**: Destination Tier Selector는 `resource_id`/`memory_class` 문자열이 아니라 `capability_flags`와 수치 field로 후보를 거른다.
2. **Self-describing**: memory 특성은 plug-in이 선언한다. 중앙 enum/if-else에 memory를 열거하지 않는다.
3. **Data-type-agnostic**: Backend는 KV/LoRA/MoE를 모른다 (공통 migration 의존성 규칙 7).
4. **Append-only vocabulary**: capability flag와 telemetry field는 추가만 허용해 기존 plug-in 호환성을 유지한다.
5. **Graceful degradation**: optional metric/flag 부재 시 보수적 기본값으로 동작한다.
6. **Resource Manager 단일 창구**: I/F는 Resource Manager 아래에 붙고, decision 모듈은 Backend를 직접 호출하지 않는다.
   Resource Manager를 통해 memory 정보를 받는 모듈은 **Resource State Monitor(②)** 와 **Destination Tier Selector(①②③)** 뿐이다 (§5.8.2, §5.8.8). `decision/`은 `resource/backends/`를 import하지 않는다 (§21).
7. **Read-only for decision plane**: decision plane은 Resource Manager가 제공하는 값을 조회만 한다. `reserve/release`와 location commit은 공통 migration control plane 소유다.

### 5.8.8 C1/C2 공통 적용 방식

슬라이드 9~10과 동일하게, Resource Manager를 통해 memory 정보를 받는 decision 모듈은 두 개다.

| 소비 모듈 | 받는 I/F 정보 | 경로 |
|---|---|---|
| Resource State Monitor (C1) | ② Telemetry: capacity·BW·load → `ResourceState` 정규화 | Telemetry Collector |
| Destination Tier Selector (C1) | ①③ capability · transfer cost (feasibility ∩ affinity ∩ 여유 용량) | Memory Registry |
| Destination Tier Selector (C2) | ② capacity·BW·load + ①③ capability · transfer cost | Telemetry Collector, Memory Registry |

- Data Eviction Manager, Data-Memory Affinity Mapper, Migration Data Selector, C2 Behavior Monitor/Predictor는 Resource Manager와 직접 연결되지 않는다.
  Affinity Mapper의 static hint(capability class key)와 이동 단위·전송 제약은 **Destination Tier Selector가 capability와 결합**해 반영한다.
- Resource State Monitor의 pressure·trend 결과는 Trend Analyzer와 Eviction Manager로 전달된다 (§8.2~8.4).

→ Memory I/F는 **C1/C2 후보 선택(Q1/Q2)과 독립적으로** 확정 가능한 공통 설계 요소다.

### 5.8.9 Data Object Registry와의 관계

~~~text
Memory Backend I/F (Memory 측 추상화)       Data Object Registry (Data 측 추상화)
  "각 memory는 어떤 capability를 가지고        "각 data object는 어디에 있고,
   지금 어떤 상태인가"                          (C2) 어떤 종류이며 어떻게 쓰이는가"
        └────────── Selector에서 결합: data ↔ memory matching ──────────┘
~~~

- 두 추상화는 **서로를 직접 참조하지 않는다.** 결합은 Selector(Destination Tier / Migration Data)에서만 일어난다.
- Registry의 `current_tier`/`current_location`은 Backend I/F의 `resource_id`를 가리키는 opaque key이며,
  tier 의미(rank, capability)는 항상 Backend I/F를 통해 해석한다.
- 이 분리로 "신규 memory 추가"(memory 축)와 "신규 data type 추가"(data 축)가 서로 영향을 주지 않는 **직교 확장성**을 확보한다.

~~~text
          memory 축 (쟁점 2)                         data 축 (쟁점 1)
신규 memory → Backend plug-in               신규 data type → C1: Registry meta + Affinity
                                                         C2: class metadata + behavior plugin
~~~

### 5.8.10 Reference Instance — `Evaluation/DP1/sim/configs` 매핑

시뮬레이터의 `memories_default.json` / `clusters.json`이 이미 memory별 spec을 보유하므로,
이를 MemoryDescriptor의 **reference instance**로 사용한다 (B200 8-GPU 도메인 기준, 값은 config 원문).

| resource_id | capacity | ext_bw | int_bw | latency | gpu_reachable | access_path | primitives | write 제약 | capability_flags |
|---|---|---|---|---|---|---|---|---|---|
| `hbm` | 192 GiB/GPU (도메인 ×8) | 8 TB/s/GPU | = ext | 300 ns | ✅ | on-package | — | — | `gpu_direct_access` `high_bw` |
| `custom_hbm` | 384 GiB | 63 GB/s | 16 TB/s | 2 µs | ❌ | gpu→host:pcie5_x16, host→dev:pcie5_x16 | QK_GEMM, SOFTMAX, AV_GEMM, CAUSAL_MASK | — | `host_staged_only` `bw_asymmetric(254x)` `near_data_compute` `shared_link` |
| `cxl_pnm` | 512 GiB | 63 GB/s | 400 GB/s | 300 ns | ❌ | gpu→cpu:pcie, cpu→dev:cxl | 위와 동일 (3.28 TFLOPS) | — | `host_staged_only` `bw_asymmetric(6x)` `near_data_compute` |
| `dram` | 1 TiB | 64 GB/s | 400 GB/s | 200 ns | ❌ | gpu→cpu:pcie | — | — | `host_staged_only` `large_capacity` `bw_asymmetric(6x)` |
| `hbf` | 2 TiB | 1 TB/s | 1 TB/s | 5 µs | ✅ | direct | — | write_bw 50 GB/s, WA 3.0, endurance 100 PB | `gpu_direct_access` `high_bw` `large_capacity` `write_limited` |
| `ssd_pim` | 16 TiB | 16 GB/s | 200 GB/s | 60 µs | ❌ | gpu→cpu:pcie, cpu→dev:nvme | GEMV (2 TFLOPS) | WA 4.0, endurance 10 PB | `host_staged_only` `large_capacity` `bw_asymmetric(12x)` `write_limited` `near_data_compute` |

이 표에서 얻은 설계 시사점:

1. **`ext_bw`와 `int_bw`를 분리해야 한다.** Custom HBM은 내부 16 TB/s지만 외부 63 GB/s(254배 차)라서,
   단일 `bandwidth` 값으로 tier를 정렬하면 Selector가 오판한다.
   migration 비용은 `ext_bw`, near-data 실행은 `int_bw` 기준이다.
2. **`gpu_reachable`과 `access_path`가 transfer feasibility를 결정한다.**
   GPU 직접 접근이 불가한 4종은 모두 Host 경유이며, 이동 경로(hop)와 비용은 descriptor에서 파생된다.
3. **Read/Write 비대칭과 endurance는 별도 field다.** HBF는 read 1 TB/s이지만 write 50 GB/s(20배 차)이고,
   HBF/SSD-PIM은 write amplification과 endurance budget이 있어 **demotion 대상 선택 시 write 비용**을 반영해야 한다 (§17.1).
4. **공유 링크(`shared_link_group`)가 1급 개념이다.** `clusters.json`의 topology note처럼
   Custom HBM은 GPU 8장당 1대이며 PCIe5 x16 한 가닥을 도메인 전체가 공유한다.
   → Telemetry에 `shared_link_util`이 필요하고, 동시 migration은 같은 link group 안에서 budget을 공유해야 한다.
5. **`scope`(per_gpu vs per_scaleup_domain)** 로 합산 단위를 표현한다. DP1의 단위는 scale-up 도메인 1개이며
   (`clusters.json` note), HBM은 GPU 수만큼 합산(8×B200 = 1.5 TiB / 64 TB/s)되는 반면 Custom HBM은 도메인당 1대다.
   `apply_cluster()`가 하는 "GPU 스펙으로 HBM/Custom HBM 값 재계산"은
   Backend 쪽에서 `descriptor()`가 **cluster context로 재계산**하는 책임으로 옮겨진다.
6. **Descriptor만 바꿔 memory를 교체/추가할 수 있다.** 같은 시스템에 B200→Vera Rubin(HBM4, 384 GB / 28 TB/s)을
   적용하면 `hbm`과 `custom_hbm`(페어링 GPU 상대 스펙: 용량 ×2, 내부 BW ×2, 연산 ×20%)의 descriptor 값만 달라지고
   decision plane 코드는 그대로다 — 쟁점 2의 수용 기준이 된다.
7. **`provenance`(SPEC/PUBLIC/ASSUMED)를 descriptor에 유지한다.** config에 이미 값마다 근거 태그가 있으며,
   ASSUMED 값으로 내린 decision은 신뢰도를 낮춰 해석해야 한다.

> **ScHBM 주의:** 슬라이드의 ScHBM(scale-attached HBM)은 현재 config에 별도 항목이 없다.
> `clusters.json`의 `scale_attached: false` flag와 `custom_hbm`이 가장 가까운 대응이며,
> ScHBM은 scale-up fabric에 붙어 GPU 도메인 간 공유될 수 있어 `scope`/`shared_link_group` 표현이 필요할 가능성이 있다.
> 이는 **"신규 memory = plug-in 1개"** 원칙의 첫 검증 대상이며, config에 항목을 추가해도 decision plane이 바뀌지 않는지 `test_sim.py`로 확인한다 (§26 follow-up).

---

### 5.8.11 Backend I/F의 Staging Primitive — N² handler 방지

신규 memory가 추가될 때마다 모든 상대 memory와의 pairwise handler를 만들면 확장 비용이 O(N)이다 (§5.9.2).
이를 피하기 위해 MemoryBackend는 descriptor/telemetry 외에 **최소 data-movement primitive**를 노출한다 (§22.8).

~~~text
MemoryBackend (data-movement primitive)
  export_async(region, staging_buf) -> handle      # 이 memory → host/공통 staging
  import_async(staging_buf, region) -> handle      # host/공통 staging → 이 memory
~~~

- 모든 memory 쌍은 `export → staging → import`의 **staged path로 기본 지원**된다. 신규 memory는 이 두 primitive만 구현하면 즉시 모든 기존 memory와 이동 가능하다.
- direct path(P2P, GPUDirect, CXL direct 등)는 **fast-path override**로 `TransferHandlerRegistry`에 선택적으로 등록한다 (§5.9.2).

---

## 5.9 Transfer Handler Design Considerations (이기종 환경)

DP1은 transfer를 수행하지 않지만(§2), 이기종 memory 환경에서 **handler 설계가 DP1 decision의 실현 가능성과 비용 모델을 결정**한다.
본 절은 handler 구현 자체가 아니라, DP1이 handler에 요구하는 설계 포인트와 DP1에 노출되어야 하는 정보를 정리한다.
구현 상세는 공통 migration architecture(doc-mk/vllm-ai-data-migration-architecture.md §17)에서 확정한다.

### 5.9.1 이동 경로가 대부분 multi-hop이다

`Evaluation/DP1/sim/configs` 기준 6종 memory 중 4종(Custom HBM, CXL-PNM, DRAM, SSD-PIM)이 `gpu_reachable=false`이며 Host를 경유한다 (§5.8.10).

~~~text
HBM → DRAM         : gpu→cpu:pcie                       (1 hop)
HBM → CXL-PNM      : gpu→cpu:pcie → cpu→dev:cxl         (2 hop)
HBM → Custom HBM   : gpu→host:pcie5_x16 → host→dev:pcie5_x16   (2 hop, 공유 링크)
HBM → SSD-PIM      : gpu→cpu:pcie → cpu→dev:nvme        (2 hop)
~~~

설계 포인트:
- **store-and-forward vs chunk pipelining:** hop 간 pipelining이 없으면 전송 시간이 hop 수에 비례해 늘어난다. 최소 chunk 크기와 bounce buffer 크기가 설계 파라미터다.
- **bounce buffer 소유권:** staging buffer 풀을 handler 공통 자원으로 관리하고 budget을 둔다 (host DRAM 자체가 migration 대상 tier이기도 하므로 pressure 연동 필요).
- **DP1 노출 정보:** 경로의 hop 수와 병목 hop BW는 `MemoryTransferBinding.est_transfer_bw / est_setup_cost`로 Selector에 전달된다 (§5.8.5).

### 5.9.2 Handler 확장성 — pairwise 폭발 방지

| 방식 | 신규 memory 1종 추가 시 | 비고 |
|---|---|---|
| Pairwise handler (src,dst 쌍마다) | N개 handler 추가 (O(N)) | 쟁점 2와 충돌 |
| **Staging primitive 기반 (§5.8.11) + direct override** | **primitive 2개 (export/import)** + 필요한 direct 경로만 | 권장 |

~~~text
TransferHandlerRegistry.resolve(src, dst)
  1. direct handler가 등록되어 있으면 사용 (P2P / GDS / CXL direct)
  2. 없으면 staged handler로 합성: src.export_async → staging → dst.import_async
~~~

direct path가 없어도 기능은 항상 보장되고(correctness), direct path는 성능 최적화로만 추가된다.

### 5.9.3 공유 링크 대역폭 중재

Custom HBM은 GPU 8장당 1대이며 PCIe5 x16 한 가닥(63 GB/s)을 도메인 전체가 공유한다 (`clusters.json`).

- **traffic class 구분:** `demand fetch`(critical path) > `promotion prefetch` > `demotion / background`. serving 대역폭을 migration이 잠식하지 않도록 class별 priority와 rate limit을 둔다.
- **link group 단위 budget:** `shared_link_group` 안의 inflight migration 총량에 상한을 둔다 (execution-side scheduler 소관, DP1은 budget 소진 시 decision 억제 또는 지연 가능).
- **DP1 노출 정보:** Telemetry의 `shared_link_util` (§5.8.4).

### 5.9.3.1 Copy engine 선택과 compute 간섭

| engine | 특성 | 간섭 |
|---|---|---|
| GPU copy engine (DMA) | SM 점유 없음 | HBM BW만 경쟁 |
| SM copy kernel | gather/scatter 유연 | SM, HBM BW 모두 경쟁 (decode와 충돌) |
| CPU memcpy | host 경유 경로 | CPU/DRAM BW 경쟁 |
| NVMe / GDS | storage 경로 | PCIe 경쟁 |

handler는 engine을 선택할 때 decode/prefill의 HBM BW·SM 사용량을 고려해야 하며,
engine 선택 결과는 migration cost(`est_transfer_bw`)와 serving 간섭에 모두 영향을 준다.

### 5.9.4 Granularity / Layout 변환

- paged KV는 작고 비연속적인 block 집합이다. 소 block 단위 전송은 BW를 못 채우므로 **batching(gather/scatter)** 이 필요하다.
- memory별 정렬/단위 제약(SSD page, HBF page/erase block 등)을 `MemoryDescriptor.granularity / alignment`에서 받아
  handler가 **coalescing과 패딩**을 수행한다 (§5.8.3).
- granularity / alignment 정보는 Memory Registry(①)에 있고 Destination Tier Selector가 target 선택 시 반영한다.
  object를 granularity 배수로 묶는 일은 DP1이 아니라 공통 Planner / handler가 수행한다 (Migration Data Selector는 Resource Manager를 직접 읽지 않는다, §8.8).

### 5.9.5 Write-limited 매체 보호

HBF(write 50 GB/s, endurance 100 PB, WA 3.0), SSD-PIM(WA 4.0, endurance 10 PB)은 write 비용이 크다.

- handler는 write 대상 memory에 대해 **write coalescing / throttle**을 적용한다.
- DP1은 anti-thrashing(§26 항목 8)과 함께 **write budget**을 decision 입력으로 고려한다 (Destination Tier Selector가 `write_limited` capability로 반영).
  특히 `DROP`/`REPLICATE` action(§2.1)으로 write를 피할 수 있으면 우선한다.

### 5.9.6 측정–추정 closed loop

~~~text
Selector가 est_transfer_bw 사용 → migration 수행 → handler가 실측 BW/latency 보고
→ Telemetry(observed_latency, transfer BW) → Binding의 estimate 보정
~~~

nominal 값과 실측 값이 다를 수 있으므로 (공유 링크 contention, thermal throttle 등),
handler는 완료 시 실측 값을 Telemetry로 보고하고, Selector는 이를 반영한 estimate를 사용한다.
이 loop가 없으면 C1/C2의 destination 선택이 nominal spec에 고정된다.

### 5.9.7 일관성 / 실패 처리 (공통 subsystem 소관)

copy-then-commit, source pin, version check, partial failure rollback은
공통 migration architecture가 정의한다 (§3.2 out of scope). DP1은 다음 두 가정만 한다.

- `MOVE`/`REPLICATE` 완료 전에는 location이 바뀌지 않는다 (Registry는 commit 결과로만 갱신, §22.3).
- 실패한 migration은 **결과(failure reason)가 DP1에 이벤트로 되돌아와** 동일 object의 재시도/억제 판단에 쓰인다.

### 5.9.8 DP1 ↔ Handler 책임 요약

| 항목 | DP1 (decision) | Handler / execution subsystem |
|---|---|---|
| 이동 action 선택 | MOVE / REPLICATE / DROP / REMAP / RECLASSIFY (§2.1) | action 실행 |
| 경로 선택 | feasibility/cost 추정에 binding 사용 | 실제 path 선택·합성 (direct/staged) |
| 대역폭 관리 | budget 소진 시 decision 억제 | traffic class / rate limit 집행 |
| granularity | object를 granularity 배수로 선택 | batching / coalescing / padding |
| write 보호 | write budget을 decision 입력에 반영 | throttle / coalescing |
| 비용 모델 | estimate 사용 | 실측 보고로 estimate 보정 |
| 일관성 | commit 결과로 Registry 동기화 | pin / version / commit / rollback |

---

# 6. Candidate 1 — Resource State-driven Migration + Data-Memory Affinity

## 6.1 Design Intent

C1의 기본 원칙은 다음과 같다.

> **Data object별 runtime behavior를 지속적으로 추적하지 않고,
> memory resource의 Capacity / Bandwidth / Load 변화와 pressure를 중심으로 migration을 결정한다.**

다만 순수 resource-only 구조는
"어떤 data를 어느 memory에 두는 것이 기본적으로 적합한가"를 전혀 구분하지 못한다.

이를 보완하기 위해 **Data-Memory Affinity Mapper**를 둔다.

~~~text
Dynamic signal
  = Resource State / Pressure / Trend

Static hint
  = Data Type / Operation ↔ Memory Affinity

Generic placement metadata
  = Type-agnostic Data Object Registry
~~~

중요한 점은 static affinity가 C2의 behavior prediction과 다르다는 것이다.

- C1: data class / operation에 대한 **미리 정의된 특성**
- C2: 실제 runtime에서 관찰한 **object별 동적 behavior**

---

# 7. C1 Component Architecture

~~~mermaid
flowchart TD
    EV["Event"]
    MS["Migration Scheduler"]

    RSM["Resource State Monitor"]
    RTA["Resource-based<br/>Trend Analyzer"]
    DEM["Data Eviction<br/>Manager"]
    DMA["Data-Memory<br/>Affinity Mapper"]
    DTS["Destination Tier<br/>Selector"]
    MDS["Migration Data<br/>Selector"]
    ME["Migration Executor<br/>(common migration boundary)"]

    DOR["Data Object Registry<br/>location / size / tier"]

    RM["Resource Manager"]
    TC["Telemetry Collector"]
    MR["Memory Registry<br/>(Backend Registry)"]
    MBI["Common Memory Backend I/F<br/>(Plug-in)"]
    MEMS["HBM / ScHBM / DRAM / CXL-PNM<br/>HBF / SSD / SSD-PIM / + New"]

    EV --> MS
    MS -. "Event push (async)" .-> RSM

    RM --> TC
    RM --> MR
    MR --> MBI
    MBI -->|"plug-in"| MEMS
    MBI -->|"MemoryTelemetry"| TC
    TC -->|"② capacity / BW / load"| RSM

    RSM --> RTA
    RSM --> DEM

    DEM -->|"object metadata query"| DOR
    DOR -->|"location / size / tier"| DEM

    RTA -->|"resource trend<br/>(tier별 여유 용량 포함)"| DMA
    DEM -->|"victim candidates<br/>(type-agnostic eviction)"| DMA

    DMA -->|"tier affinity hint"| DTS
    DMA -->|"data affinity hint"| MDS

    MR -->|"①③ capability ·<br/>transfer cost"| DTS

    DTS --> ME
    MDS --> ME
~~~

구조의 핵심 path는 다음과 같다.

~~~text
Event
  → Migration Scheduler
  → Resource State Monitor
  → Resource-based Trend Analyzer / Data Eviction Manager
  → Data-Memory Affinity Mapper
  → Destination Tier Selector / Migration Data Selector
  → Migration Executor boundary
~~~

Data Eviction Manager는 별도로 **type-agnostic Data Object Registry**를 조회하여
실제 object의 위치·크기·현재 tier 정보를 얻고,
그 generic metadata 위에서 eviction policy를 적용한다.

---

# 8. C1 Component Responsibilities

## 8.1 Migration Scheduler

C1에서 Event를 받으면 Resource State Monitor의 evaluation cycle을 비동기로 시작한다.

~~~text
Event arrives
  ↓
Migration Scheduler
  ↓ async
Resource State Monitor refresh/evaluate
~~~

이렇게 하면 resource monitoring/decision logic이
request execution path에서 직접 동기 호출되는 구조를 피할 수 있다.

## 8.2 Resource State Monitor

Telemetry Collector(② Telemetry: capacity·BW·load)의 정보를 사용해 현재 resource state를 normalized state로 만든다.
Resource Manager에서 Resource State Monitor로 들어오는 입력은 이 경로 하나다 (슬라이드: Resource State Monitor ↔ Telemetry Collector).

~~~text
ResourceState
 ├─ resource_id
 ├─ free_capacity
 ├─ capacity_pressure
 ├─ read_bw_util
 ├─ write_bw_util
 ├─ queue_depth
 ├─ load
 ├─ transfer_pressure
 └─ health
~~~

단순 순간값뿐 아니라 짧은 시간 범위의 state 변화도 볼 수 있다.

~~~text
HBM free capacity
80 GB → 55 GB → 30 GB → 12 GB

=> rapidly increasing pressure
~~~

따라서 C1은 현재 pressure뿐 아니라 near-future pressure에 선제적으로 반응할 수 있다.

## 8.3 Resource-based Trend Analyzer

Resource State의 시간 변화와 pending demand를 보고
resource pressure가 어느 방향으로 변할지를 분석한다.

~~~text
Current HBM free = 20 GB
Expected near-term demand = +14 GB
Recent allocation rate = +3 GB/s

=> near-term HBM pressure expected
=> background demotion trigger
~~~

이 component의 출력은 data semantics가 아니라
**resource-side migration need**다.

~~~text
MigrationNeed
 ├─ source_tier = HBM
 ├─ required_free_bytes = 16 GB
 ├─ urgency = MEDIUM
 └─ reason = projected capacity pressure
~~~

## 8.4 Data Eviction Manager

pressure를 해소하기 위해 source tier에서
이동 가능한 data candidate set을 만든다.

이때 Data Object Registry를 조회한다.

~~~text
HBM pressure
   ↓
Data Object Registry
  location / size / tier
   ↓
evictable objects
   ├─ KV block B1
   ├─ KV block B4
   ├─ LoRA A2
   └─ Expert E17
~~~

Data Eviction Manager는 최종 target tier를 정하지 않는다.
역할은 **source-side candidate generation**이다.

Data Eviction Manager가 조회하는 곳은 **Data Object Registry뿐**이다. Resource Manager / Memory Backend I/F를 직접 읽지 않는다.
memory 쪽 제약(tier 순서, 이동 단위, 전송 비용 등)은 뒤의 Destination Tier Selector가 capability(①③)로 반영한다.

기본 정책은 LRU / age / size / pin state / migration eligibility 등
낮은 비용의 heuristic을 사용할 수 있다.

## 8.5 Data Object Registry — Type-agnostic

C1의 Data Object Registry는 **AI Data type을 모르는 generic placement bookkeeping**이다.

어떤 object를 eviction 대상으로 검토하려면 최소한 다음 정보만 있으면 된다.

~~~text
object_id
size
current location
current tier
pin / movable state
basic lifecycle state
~~~

의도적으로 다음 정보는 C1 Registry에 넣지 않는다.

- KV Cache / Agent Memory / LoRA / MoE / Vector Index 같은 data type
- type-specific reuse characteristic
- lifetime characteristic
- hotness / future reuse prediction

따라서 C1의 victim 선택은 **data type과 무관하게 eviction policy**로 다음처럼 동작한다.

~~~text
Resource pressure
  ↓
C1 Data Object Registry
  위치 / 크기 / tier 조회
  ↓
Eviction Policy
  LRU / age / size / pressure relief
  ↓
Victim selection
~~~

즉 C1의 Registry는 **"무슨 종류의 AI Data인가?"를 판단하는 곳이 아니라
"어디에 있고 얼마나 큰 object인가?"를 알려주는 곳**이다.

## 8.6 Data-Memory Affinity Mapper

C1에서 AI Data 특성을 보완하는 핵심 component다.

Data Object Registry의 type 정보를 사용하는 것이 아니라,
별도의 configuration / function / operation hint를 통해
대표적인 data/operation 특성을 static metadata로 제공한다.

즉 C1의 Registry는 type-agnostic이고,
**Data-Memory Affinity Mapper만 별도로 static affinity hint를 안다.**

~~~text
DataMemoryAffinity
 ├─ data_type
 ├─ operation_class
 ├─ latency_sensitivity
 ├─ bandwidth_sensitivity
 ├─ capacity_preference
 ├─ mutability
 ├─ expected_access_granularity
 ├─ preferred_capability_classes[]   # memory 이름이 아닌 capability class (§8.7)
 ├─ disallowed_capability_classes[]
 └─ migration_cost_class
~~~

예를 들어 다음과 같은 **class-level hint**를 둘 수 있다.

| Data class | Static characteristic 예 | Affinity hint 예 |
|---|---|---|
| KV Cache | attention에서 반복 접근, latency/BW sensitive | active KV는 upper tier 선호 |
| Agent Memory | 상대적으로 long-lived, large-capacity 가능 | capacity-rich tier 허용 |
| LoRA Adapter | read-mostly | 자주 쓰이는 deployment profile은 upper tier 선호 가능 |
| MoE Expert | weight footprint가 크고 access가 selective | bandwidth-rich tier 우선순위 부여 가능 |
| Vector Index Cache | large footprint, lookup-oriented | capacity와 lookup latency trade-off 반영 |

위 표는 **runtime hotness prediction 결과가 아니라 static policy hint**다.

따라서 같은 KV Cache class 안에서
B1과 B2의 실제 future reuse 차이까지 C1이 직접 예측하지 않는다.

> 이 component가 **어떤 순서로 누구와 무엇을 주고받는지**, 그리고 simulator를 실제로 호출한 worked example은 **§10A**를 본다.

## 8.7 Destination Tier Selector

다음 정보를 결합해 target tier를 선택한다. 입력은 출처가 서로 다르다.

| 입력 | 출처 | 내용 |
|---|---|---|
| resource trend, 후보 tier별 available capacity | Resource State Monitor / Trend Analyzer → Affinity Mapper (upstream ResourceState) | ② capacity·BW·load에서 만든 tier별 pressure와 여유 용량 |
| **memory capability, transfer cost** | **Memory Registry** (Resource Manager) | ① Descriptor(capacity, BW, latency, gpu_reachable, capability_flags), ③ Binding(est_transfer_bw/setup, hop, shared link) |
| static data-memory affinity | Data-Memory Affinity Mapper | capability class 기준 hint |

슬라이드에서 C1의 Destination Tier Selector가 Resource Manager와 직접 연결되는 곳은 **Memory Registry**다.
Telemetry Collector 값은 Resource State Monitor를 거쳐 upstream으로 들어온다 (C2는 Selector가 Telemetry Collector도 직접 읽는다).

**Serving cost 항(평가 loop에서 도출된 개정, `Evaluation/DP1/results/iterations/loop-log.md`):**
첫 평가에서 C1은 destination의 **서빙 비용**(그 tier에서 접근할 때의 TPOT)을 보지 않아 CXL-PNM attention 경로(TPOT 311 ms)를 고르는 문제가 있었다.
Destination Tier Selector는 Memory Registry의 capability(① gpu_reachable, ext/int BW, latency, near_data_compute)와 transfer cost(③)에서
destination의 **서빙 비용 추정치**를 계산해 (a) SLO를 만족하지 못하는 tier를 후보에서 제외하고 (b) 후보 간 비교에 penalty로 반영한다.
Resource Manager와의 연결은 추가되지 않는다 (같은 Memory Registry 입력의 파생값). 입력에는 operation hint(operation class, shape: context, concurrency, output tokens, touch bytes)가 필요하며 C1에서는 static hint 채널(Affinity Mapper)로 전달된다.
또한 **link-time migration budget**(공유 링크 점유 시간 기준 token bucket)과 per-object cooldown으로 migration 총량을 제한한다 (§26 항목 8).

개념적으로:

~~~text
candidate target tier
  = feasible(capability ∩ transfer cost ∩ available capacity)
  ∩ preferred(data-memory affinity)
~~~

여기서 "tier"와 "memory capability"는 **Memory Registry(MemoryDescriptor, §5.8)** 로만 조회한다.
Affinity Table도 `HBM`, `CXL` 같은 memory 이름이 아니라
`capability class`(예: `high_bw`, `large_capacity`, `persistent`, `near_data_compute`)를 key로 갖는다.
따라서 신규 memory는 Descriptor가 해당 capability class에 매핑되기만 하면 Affinity Table 수정 없이 후보에 포함된다.

## 8.8 Migration Data Selector

Eviction candidate 중 실제 migration object를 결정한다.

고려 정보:

- migration eligibility
- object size
- current tier/location
- pin state
- basic age/LRU
- source pressure relief 효과
- static data-memory affinity (Affinity Mapper의 candidate ranking hint)
- target feasibility

Migration Data Selector도 Resource Manager와 직접 연결되지 않는다 (슬라이드: Resource Manager ↔ Destination Tier Selector만).
(source object, target tier)는 Executor boundary에서 `MigrationDecision`으로 결합되고,
target 용량 부족이나 전송 제약 위반은 공통 Planner가 reject / replan한다 (§19).

C1에서는 runtime per-object future behavior prediction을 하지 않으므로
selection logic은 상대적으로 단순하게 유지한다.

---

# 9. C1 Main Sequence

~~~mermaid
sequenceDiagram
    participant E as Event Source
    participant MS as Migration Scheduler
    participant TC as Telemetry Collector
    participant MR as Memory Registry
    participant RSM as Resource State Monitor
    participant RTA as Resource Trend Analyzer
    participant DEM as Data Eviction Manager
    participant DOR as Data Object Registry
    participant AM as Data-Memory Affinity Mapper
    participant DTS as Destination Tier Selector
    participant MDS as Migration Data Selector
    participant MC as MigrationCoordinator

    E->>MS: Migration Event
    MS-->>RSM: async event push / evaluate

    TC->>RSM: ② capacity / BW / load telemetry
    RSM->>RTA: normalized resource state
    RSM->>DEM: pressure state

    RTA->>RTA: detect current / projected pressure

    DEM->>DOR: query candidate object metadata
    DOR-->>DEM: location / size / tier / movable state
    DEM->>DEM: generate eviction candidates

    RTA->>AM: resource-side migration need
    DEM->>AM: candidate data objects
    AM->>AM: apply static data-memory affinity

    AM->>DTS: target-tier hints
    AM->>MDS: candidate ranking hints

    DTS->>MR: query capability / transfer cost (①③)
    MR-->>DTS: feasible memories + est. transfer cost

    DTS-->>MC: target resource
    MDS-->>MC: selected data objects
    MC->>MC: build MigrationIntent
~~~

---

# 10. C1 Strengths / Limitations

## 장점

- **낮은 Decision Overhead**
  - per-object behavior history와 predictor가 없어 decision pipeline이 단순함.
- **Event 기반 비동기 처리**
  - runtime event 발생 시 Migration Scheduler가 decision cycle을 시작하고 request path와 결합도를 낮출 수 있음.
- **Resource State 변화에 즉시 반응**
  - capacity/BW/load pressure가 발생하면 migration evaluation trigger 가능.
- **전체 Memory Pool Utilization 관리에 유리**
  - 특정 tier pressure를 빠르게 해소하고 idle capacity를 활용하기 쉬움.
- **Modifiability가 상대적으로 높음**
  - 새로운 memory resource 추가 시 Registry / affinity mapping 확장으로 대응 가능.
- **Registry와 Affinity 역할 분리**
  - Registry는 위치/크기/tier만 관리하고, 대표적인 Data/Operation 특성은 별도의 Affinity Mapper가 static hint로 반영.

## 한계

- **Data별 실제 접근 특성 반영 한계**
  - 같은 data class 내부 object별 hot/cold 차이를 직접 예측하지 않음.
- **동일 Resource State에서 서로 다른 Data Access Pattern 구분 한계**
  - 동일한 HBM pressure라도 어떤 object가 곧 다시 사용될지는 알기 어려움.
- **Static hint의 granularity 한계**
  - workload phase 변화나 request-specific reuse 변화를 빠르게 반영하기 어려움.

Agent tool-call에 따른 KV lifetime/residency는
DP1 C1에 동적 behavior predictor를 추가하기보다
별도의 Agent-aware KV management 구조로 보완한다.

---

# 10A. C1 Data-Memory Affinity Mapper — 동작 순서와 Worked Examples

> **목적:** §6~§10에 나뉘어 있는 Affinity Mapper의 역할을 "**어떤 순서로, 어떤 module과, 무엇을 주고받는가**" 관점으로 한곳에 정리하고,
> `Evaluation/DP1/sim`을 실제로 호출해서 얻은 수치로 5개 상황을 단계별로 따라간다.
>
> - **번호:** §11 이후의 번호와 cross-reference를 유지하기 위해 §10 바로 뒤에 **§10A**로 둔다.
> - **수치의 출처:** 본 절의 모든 수치는 `doc-mk/Evaluation/DP1/sim`(`policies.py`, `simulator.py`, `model.py`)을 **`SYS-B200` profile**(`model.load_profile(configs, 'SYS-B200')`)로 직접 호출한 결과다. 호출 방법은 §10A.4 서두에 있다. simulation 출력이므로 실측 [A]가 아니라 [B+C]이며, 코드는 working tree의 현재 상태(미커밋 수정 포함)를 기준으로 했다.
> - **예시의 한계:** 예시 1~5는 policy 객체(`C1ResourceDrivenMigration.on_event`, `DestinationTierSelectorC1.select`)를 직접 호출하는 **작은 harness**다. 전체 시나리오 run(`run_sim`)의 결과가 아니다. 전체 run의 효과는 §10A.5에서 평가 결과 문서의 값을 인용한다.

## 10A.1 역할과 경계

**Affinity Mapper가 하는 일.** object의 *정적* 특성을 memory 선택에 쓸 수 있는 형태로 제공한다.

~~~text
static hint (object 단위, allocation 시점에 선언)
 ├─ latency_sensitivity / bandwidth_sensitivity / capacity_sensitivity   # 0~1, class-level 선언값
 ├─ op                : attention | weight_fetch | context_fetch | index_scan   # operation class
 └─ shape             : ctx_tokens, concurrency, out_tokens, touch_bytes, vec_dim
~~~

- hint에는 **data type 이름이 없다.** `KV_CACHE`, `RAG_DATA` 같은 이름 → operation class 변환은 hint를 만드는 쪽(sim에서는 `simulator.OPERATION_CLASS`, 설계상 §26-3의 Affinity Table)에만 있다.
  C1의 Registry·Eviction·Selector 코드는 `op` 문자열과 숫자만 본다 (§5.3, §8.5, §24).
- hint는 **object별 runtime behavior가 아니다.** 접근 횟수, 재사용 간격, hotness를 추적하지 않는다. shape 필드(`ctx_tokens`, `concurrency` 등)도 호출자가 allocation 때 **선언한 값**이지 관측값이 아니다. 이것이 C1 정체성의 fence다 (§24, `dp1-c1-qa1-complement-design.md` §6.2).
- Mapper가 **하지 않는 일:** victim 선택(Eviction Manager), pressure 판단(Resource State Monitor / Trend Analyzer), 서빙 비용 계산(AccessCostEstimator), 예산 관리(MigrationBudget), 실제 이동(Planner/Executor).

**누가 무엇을 소유하는가**

| 역할 | 소유 module | sim 대응 | 생산 / 소비 |
|---|---|---|---|
| hint 생산 | data를 만든 runtime 쪽(allocation 호출자) + Affinity Table(configuration) | `simulator.static_hints(objs)`, `OPERATION_CLASS` | 생산: allocation 시점 1회. 소비: DTS, promotion pass |
| hint 보관 | Affinity Mapper (object_id → hint). **Registry와 분리** | `SimContext.static_affinity_hints` | Registry는 location/size/tier/movable만 가짐 (`registry.C1ObjectRecord`에 type 필드 없음) |
| affinity 점수 | Affinity Mapper | `DataMemoryAffinityMapper.score(mem, state, hint)` | DTS가 호출 |
| 서빙 비용 추정 | Resource Manager 쪽 공유 module (Memory Registry descriptor만 입력) | `AccessCostEstimator` (`estimate`, `service_extra_s`, `slo_ok`, `budget_fraction`) | DTS와 promotion pass가 호출. **C2도 같은 module을 공유** |
| victim 후보 | Data Eviction Manager (+ Registry) | `DataEvictionManager.candidates` | type 무관 |
| 목적지 결정 | Destination Tier Selector | `DestinationTierSelectorC1.select` | hint + ResourceState + descriptor 결합 |
| 정적 승격/교환 | C1 policy 내부 pass (설계 §17.2) | `C1ResourceDrivenMigration._promotion_pass` | hint + estimator만 사용 |

**설계 문서와 sim의 차이 (읽을 때 주의):**

1. §8.8은 Affinity Mapper가 Migration Data Selector에 "candidate ranking hint"를 준다고 적었지만, sim의 `MigrationDataSelectorC1.select`는 Eviction Manager가 정렬한 후보의 **앞에서부터 required bytes만큼** 자를 뿐 affinity를 쓰지 않는다. 즉 현재 구현에서 hint의 소비처는 DTS와 promotion pass 두 곳이다.
2. 설계상 "Mapper"는 hint 보관 + 점수 + (shape 전달) 묶음이지만, sim에서는 `static_hints`(생산), `DataMemoryAffinityMapper.score`(점수), `AccessCostEstimator`(비용)로 나뉘어 있다.
3. 설계 문서의 ScHBM은 sim config에 별도 항목이 없고 `custom_hbm`이 가장 가까운 대응이다 (§5.8.10). 아래 예시의 `custom_hbm` 값은 "ScHBM 대용" 값이다.

## 10A.2 동작 순서

C1에서 Mapper가 관여하는 시점은 **등록 시점(1회)**, **tick마다의 목적지 결정**, **tick마다의 정적 승격 pass** 세 곳이다. 나머지 단계에서는 hint를 쓰지 않는다.

| # | 시점 / 주기 | actor → receiver | 주고받는 data | Mapper의 기여 | sim 코드 |
|---|---|---|---|---|---|
| 0 | object 등록 (`ALLOCATED`, 1회) | Runtime(data 소유자) → Affinity Mapper | `object_id`, `op`, shape, 민감도 3종 | **hint 도출·보관**. object가 생길 때 한 번만 | `static_hints`, `SimContext.static_affinity_hints` |
| 0' | 같은 event | Migration Scheduler → Data Object Registry | `object_id`, `size`, `tier`, `movable` (type 없음) | 없음 (Registry는 hint를 모름) | `on_event(ALLOCATED)` → `registry.add` |
| 1 | `ACCESSED` event | Event Source → C1 | `object_id`, count | **없음. C1은 폐기** (`return [], 0.2`) | `on_event` |
| 2 | telemetry tick (sim 1 s) | Telemetry Collector → Migration Scheduler → Resource State Monitor | tier별 `capacity_util`, `bw_util` (미처리 `TELEMETRY`는 최신 것만 남기고 coalesce) | 없음 | `MigrationScheduler.push`, `ResourceStateMonitor.observe` |
| 3 | 같은 tick | Resource State Monitor → Trend Analyzer | `ResourceState` (current / predicted = 현재 + 기울기 × horizon 2) → `score = max(current_pressure, current_bw, predicted_pressure, predicted_bw)`, **0.82 이상**이면 pressure source | 없음. 단, 이 `ResourceState`는 4단계 DTS가 **목적지의 여유 용량 항**으로 받는다 | `ResourceStateMonitor.states`, `ResourceBasedTrendAnalyzer.pressure_sources` |
| 4 | pressure source마다 | Trend Analyzer → Eviction Manager → Registry → Migration Data Selector | `required = occupancy − 0.72 × capacity` (≤ 0이고 score ≥ 0.94면 `0.05 × capacity`), 후보 = Registry의 `objects_in_tier`를 `size × (1 + min(age/60, 1))` 내림차순, cooldown 8 s 통과분. MDS는 앞에서부터 `required`를 채울 때까지 자름 | 없음 (설계 §8.8의 ranking hint는 미구현) | `DataEvictionManager.candidates`, `MigrationDataSelectorC1.select` |
| 5 | victim마다 | DTS → Affinity Mapper → DTS | `hint(object_id)` 조회, `score(mem, ResourceState, hint)` | **affinity 점수**: `0.35 × (1 − 목적지 predicted_pressure) + 0.25 × bw_sens × bw + 0.20 × lat_sens × latency + 0.20 × cap_sens × capacity` | `DataMemoryAffinityMapper.score` |
| 5' | 같은 호출 | DTS → AccessCostEstimator (← Memory Registry descriptor) | `estimate(tier, hint, size) → (TTFT, TPOT)`, `service_extra_s`, `budget_fraction` | **hint의 `op`+shape가 입력**. SLO 위반 tier 제거, 후보 비교 penalty | `AccessCostEstimator` |
| 5'' | 같은 호출 | DTS 내부 | filter: 용량 부족, 목적지 predicted_pressure ≥ source, SLO 위반, (source가 HBM이 아니면) do-no-harm. 결과 `argmax(affinity − budget_fraction)` | 위 두 입력의 결합 | `DestinationTierSelectorC1.select` |
| 6 | 목적지 확정 직후 | DTS → MigrationBudget | `est_transfer_s = size / min(src.ext_bw, dst.ext_bw, dst.write_bw)` | 없음. 거부되면 object는 그대로 | `MigrationBudget.try_spend` (token bucket: 채움률 0.25 s/s, 용량 0.25 × 8 s = 2.0 s) |
| 7 | 같은 tick 끝 | C1 → Planner/Executor → Registry | `MigrationDecision(object, src, dst, reason, direction)` → 검증(source tier 일치, 목적지 용량) → 전송 → `on_migration_committed` → `registry.move`, `last_migration` 갱신, 전송 시간의 20%를 다음 접근에 노출 | 없음 | simulator 본 loop, `MIGRATION_EXPOSURE` |
| 8 | **별도 pass**: 매 tick 4~7 뒤 | C1 → Affinity Mapper(hint) + AccessCostEstimator → Budget | "지금 tier에서는 SLO 위반인데 HBM이면 만족"하는 object를 찾고, HBM이 가득하면 정적 손실이 훨씬 작은 HBM 거주 object와 교환. `gain ≥ AFFINITY_MARGIN(2.0) × loss`일 때만 | **hint + 비용 추정만으로 promotion trigger 생성** (설계 §17.2). resource pressure와 무관 | `_promotion_pass` |

~~~mermaid
sequenceDiagram
    participant RT as Runtime (data 소유자)
    participant MS as Migration Scheduler
    participant TC as Telemetry Collector
    participant RSM as Resource State Monitor
    participant RTA as Trend Analyzer
    participant DEM as Data Eviction Manager
    participant DOR as Data Object Registry
    participant MDS as Migration Data Selector
    participant AM as Affinity Mapper
    participant ACE as AccessCostEstimator
    participant DTS as Destination Tier Selector
    participant BG as MigrationBudget
    participant MC as Planner / Executor

    Note over RT,DOR: 단계 0 등록 시점, object당 1회
    RT->>AM: hint 등록 (object_id, op, shape, 민감도)
    RT->>MS: ALLOCATED (object_id, size, tier)
    MS->>DOR: add (object_id, size, tier, movable) 단, type과 hint는 없음
    Note over RT,MS: 단계 1 ACCESSED event는 C1이 폐기

    loop 매 telemetry tick
        TC->>MS: TELEMETRY (tier별 capacity_util, bw_util)
        MS-->>RSM: 비동기 evaluate
        RSM->>RTA: ResourceState (current, predicted)
        RTA->>RTA: pressure source 판정 (0.82 이상)
        RTA->>DEM: source tier, required_free_bytes
        DEM->>DOR: objects_in_tier (source)
        DOR-->>DEM: object_id, size, tier, movable
        DEM->>MDS: 후보 (size x age 순, cooldown 통과)
        MDS-->>DTS: victim 목록 (required를 채울 때까지)

        loop 각 victim
            DTS->>AM: hint 조회 (object_id)
            AM-->>DTS: op, shape, 민감도
            DTS->>ACE: estimate / service_extra_s / budget_fraction (tier별)
            ACE-->>DTS: TTFT, TPOT, SLO 여부, penalty
            DTS->>AM: score (descriptor, ResourceState, hint)
            AM-->>DTS: affinity 점수
            DTS->>DTS: SLO filter, do-no-harm, argmax (affinity - budget_fraction)
            DTS->>BG: try_spend (est_transfer_s)
            alt 예산 통과
                BG-->>MC: MigrationDecision (object, src, dst, reason)
            else 예산 부족
                BG-->>DTS: 이번 tick은 이동 안 함
            end
        end

        Note over AM,BG: 단계 8 정적 승격 pass, pressure와 무관
        AM-->>MC: hint + ACE로 SLO 위반 object 탐지, swap 계획 (gain 대 loss, margin 2.0)
        MC->>MC: 검증 (source tier, 목적지 용량), 전송, commit
        MC->>DOR: move (object_id, target tier)
    end
~~~

**시간 규약 요약**

- Mapper의 hint는 **등록 시 1회** 만들어지고 이후 바뀌지 않는다. tick마다 달라지는 것은 `ResourceState`(목적지 여유 용량)뿐이다.
- 한 tick의 처리 비용은 policy가 `decision_cost_us = 14 µs × max(1, decision 수)`로 보고한다 (예: 7개 이동이면 98 µs).
- per-object cooldown 8 s와 budget window 8 s는 같은 상수(`COOLDOWN_S`)다. 방금 옮긴 object는 8 s 동안 4단계 후보와 8단계 후보에서 모두 빠진다.
- 8단계 swap은 **한 번에 하나만** 진행한다. victim 강등이 끝나면 승격에 필요한 전송 시간을 budget에서 `reserved`로 잡아, 다른 이동이 승격을 굶기지 못하게 한다.

## 10A.3 평가 harness와 공통 전제

**시스템:** `SYS-B200` (B200 x8, 6개 memory). 아래 값은 `model.load_profile`이 올린 `MemorySpec`이다.

| tier | 용량 | ext BW | int BW | latency | attention 오프로드 | 비고 |
|---|---:|---:|---:|---:|:---:|---|
| `hbm` | 1536 GiB | 64,000 GB/s | 64,000 GB/s | 300 ns | - | GPU 8장 합산 |
| `custom_hbm` (ScHBM 대용) | 384 GiB | 63 GB/s | 16,000 GB/s | 2 µs | 가능 | GPU가 직접 못 읽음 |
| `cxl_pnm` | 512 GiB | 63 GB/s | 400 GB/s | 300 ns | 가능 | |
| `dram` | 1024 GiB | 64 GB/s | 400 GB/s | 200 ns | 불가 | |
| `hbf` | 2048 GiB | 1,000 GB/s | 1,000 GB/s | 5 µs | 불가 | write 50 GB/s |
| `ssd_pim` | 16384 GiB | 16 GB/s | 200 GB/s | 60 µs | 불가 | GEMV(similarity)만 |

SLO는 `FIRST_RESPONSE_SLO_S = 2.0 s`, `TPOT_SLO_S = 0.050 s`다 (`simulator.py`).

**호출 방법 (모든 예시 공통)**

~~~python
import sys; sys.path.insert(0, "doc-mk/Evaluation/DP1/sim")
from pathlib import Path
import model, policies as P
from simulator import static_hints
sysm, pid, prof = model.load_profile(Path("doc-mk/Evaluation/DP1/sim/configs"), "SYS-B200")
est = P.AccessCostEstimator(sysm)          # Memory Registry descriptor 기반
am  = P.DataMemoryAffinityMapper()
sel = P.DestinationTierSelectorC1(sysm, am, est)
slo = (2.0, 0.050)

# object: model.DataObject(oid, class, size, base_rate, access_bytes, ctx, out_tokens, lifetime, batch_size=..., latency_sensitivity=DATA_PRIORS[class]["latency"])
#   KV 크기 = 327680 B/token x ctx (scenarios.py의 KV 크기식, Llama-3.1-70B GQA), access_bytes = size x ACCESS_FRAC[class]
hint = static_hints([o])[o.oid]            # 등록 시점의 hint (단계 0)
est.estimate(tier, hint, size)             # -> (TTFT s, TPOT s)
est.service_extra_s(tier, hint, size)      # HBM 대비 접근 1회의 추가 서빙 시간 s
est.slo_ok(tier, hint, size, *slo); est.budget_fraction(tier, hint, size, *slo)
am.score(sysm.memories[tier], state, hint) # affinity 점수
sel.select(rec, "hbm", states, occupancy, capacity_by_tier, hint, slo)   # 목적지, 없으면 None
~~~

- `state`는 `P.ResourceState`. 아래 예시 1의 표는 source `hbm`의 predicted_pressure 0.88, 나머지 tier는 0.2로 둔 상태다.
- `policy.on_event(MigrationEvent(TELEMETRY, t, metadata={"telemetry": ...}), ctx)`로 policy를 직접 구동한 경우(예시 1, 4, 5)는 `ctx`를 `SimContext`와 같은 필드(`occupancy`, `effective_capacity`, `static_affinity_hints`, `slo_*`)를 가진 stub으로 만들고, 반환된 decision을 `on_migration_committed`로 commit했다. 예시 4, 5의 HBM 용량 400 GiB는 시나리오의 `hbm_capacity_mult`(HBM이 빠듯한 상황)를 흉내 낸 값이다.

## 10A.4 Worked Examples

### 예시 1. HBM 압박 중인 KV block은 어디로 가는가

**초기 상태.** HBM effective capacity 330 GiB, KV 30개(각 10 GiB = 327680 B × 32768 ctx, batch 16, out 64)가 모두 HBM에 있다 (occupancy 300 GiB). 다른 tier는 비어 있고 telemetry `capacity_util`은 0.2다. HBM `capacity_util`은 1 s tick마다 0.70, 0.76, 0.82, 0.88, 0.91로 증가한다 (harness가 주입한 값).

**hint (등록 시점, 단계 0).**
`{op: attention, ctx_tokens: 32768, concurrency: 16, out_tokens: 64, touch_bytes: 10 GiB, latency_sensitivity 0.98, bandwidth_sensitivity 0.85, capacity_sensitivity 0.8}`

**단계별 진행 (실제 `on_event` 호출 결과).**

| 단계 | actor | 입력 → 결과 |
|---|---|---|
| tick t=1 (3) | Resource State Monitor / Trend Analyzer | util 0.70, 기울기 없음 → predicted 0.700 < 0.82. **pressure source 없음**, decision 0건. budget 토큰 2.000 s |
| tick t=2 (2~3) | Resource State Monitor | util 0.76. 기울기 (0.76 − 0.70)/1 = 0.06/tick → **predicted = 0.76 + 0.06 × 2 = 0.880**. 현재값은 0.82 미만인데도 projected 값으로 pressure source가 된다 (선제 대응, §8.2) |
| (4) | Eviction Manager → MDS | `required = 300 − 0.72 × 330 = 62.4 GiB`. 후보는 크기·age가 같아 object_id 내림차순(30, 29, …). MDS는 **7개(70 GiB)** 를 자른다 |
| (5) | DTS (+ Affinity Mapper, AccessCostEstimator) | victim 30에 대해 아래 표를 계산 → **dram** |
| (6) | MigrationBudget | `est_transfer_s = 10 GiB / 64 GB/s = 0.168 s` × 7 = 1.176 s. 토큰 2.000 → 0.826 s. 전부 통과 |
| (7) | Planner/Executor → Registry | 7개 모두 `hbm → dram`, reason `resource_pressure`, direction `demotion`, score 0.880. commit 후 `registry.move`, cooldown 시작. policy 비용 98 µs |
| tick t=3 | Trend Analyzer | util 0.82, predicted 0.940 (emergency 0.94 이상). 남은 occupancy 230 GiB < 0.72 × 330라 `required ≤ 0` → `0.05 × 330 = 16.5 GiB` → 2개 추가 이동 |

(t=3 이후 telemetry는 occupancy와 연동되지 않는 주입값이므로 emergency 경로의 동작만 보인 것이다.)

**victim 30의 목적지 평가 (`states`: source hbm 0.88, 나머지 0.2).**

| 후보 tier | 용량 | TTFT / TPOT | SLO(2 s / 50 ms) | affinity | budget_fraction | score = affinity − budget_fraction |
|---|:---:|---|:---:|---:|---:|---:|
| `dram` | O | 0.219 s / 8.06 ms | O | 0.7365 | 0.0839 | **0.6526 (선택)** |
| `hbf` | O | 0.062 s / 5.60 ms | O | 0.6439 | 0.0054 | 0.6385 |
| `custom_hbm` | O | 0.052 s / 18.62 ms | O | 0.6400 | 0.2636 | 0.3764 |
| `ssd_pim` | O | 0.723 s / 15.92 ms | O | 0.6012 | 0.3355 | 0.2657 |
| `cxl_pnm` | O | 0.052 s / **616.71 ms** | **X** | 0.7172 | 12.2255 | −11.5083 (후보 제외) |

호출: `est.estimate(t, hint, 10*GiB)`, `am.score(sysm.memories[t], state[t], hint)`, `est.budget_fraction(t, hint, 10*GiB, *slo)`, `sel.select(rec, "hbm", states, {}, {}, hint, slo)` → `"dram"`.

**왜 이렇게 되는가.**

- **attention 오프로드가 가능한 tier(`custom_hbm`=ScHBM 대용, `cxl_pnm`)도 후보다.** 이 hint의 `op`가 `attention`이므로 estimator는 `offloaded_attention_s`로 TPOT을 계산한다. `custom_hbm`은 내부 BW 16 TB/s라 TPOT 18.62 ms로 SLO를 만족하지만 HBM 대비 접근당 0.844 s의 penalty가 있어 점수가 0.3764로 낮다. `cxl_pnm`은 batch 16 × 32K KV(160 GiB)를 내부 BW 400 GB/s로 읽어야 해 TPOT가 616.71 ms다.
- **오프로드 불가 tier(`dram`, `hbf`, `ssd_pim`)는 "복원 후 HBM attention" 경로다.** TTFT에 `10 GiB / ext_bw`가 더해지고 TPOT는 그 복원 시간을 out_tokens로 나눈 만큼 늘어난다. `dram`은 TTFT +0.168 s, `hbf`는 +0.011 s(ext BW 1 TB/s)이다.
- **dram과 hbf의 차이는 0.014로 작다.** 서빙 penalty만 보면 `hbf`(0.021 s)가 `dram`(0.336 s)보다 0.315 s 유리하지만, penalty는 SLO budget으로 정규화되어(`TTFT 차 / 2.0 s`) 0.0839 대 0.0054로만 반영되고, affinity 점수는 `dram`의 낮은 latency(200 ns)와 용량 항이 앞선다. 또한 `hbf`로의 전송은 write BW 50 GB/s 때문에 0.215 s(`dram` 0.168 s)이고, `hbf`의 write endurance(`write_amp` 3.0)는 `select()`가 참조하지 않는다 (§5.9.5의 write-limited 보호는 별도 계층의 몫이다).

**takeaway.** 같은 pressure 상황에서 "어디로"는 affinity 점수 단독이 아니라 **(hint의 op+shape → 서빙 비용 추정) 로 후보를 거르고, 남은 후보를 affinity − penalty로 정렬**해서 정해진다. "언제/몇 개"는 hint와 무관한 Trend Analyzer, Eviction Manager가 정한다.

### 예시 2. 같은 hint 메커니즘이 RAG shard와 Agent memory를 다른 곳으로 보낸다

**초기 상태.** 예시 1과 같은 pressure(hbm 0.88, 나머지 0.2)에서 HBM에 있는 두 object를 각각 내려야 한다. 두 object 모두 `static_hints()`로 만든 hint를 갖고, Registry에는 `(object_id, size, tier=hbm)`만 있다.

| object | 등록 시 hint (요약) |
|---|---|
| RAG shard 40 GiB, batch 16 | `op=index_scan`, `touch_bytes`=40 GiB(전체), `vec_dim` 1024, latency 0.78, **bandwidth 0.45**, capacity 0.8 |
| Agent memory 16 GiB, batch 16 | `op=context_fetch`, `touch_bytes`=3.30 GB(= min(size, access_bytes × batch)), latency 0.55, bandwidth 0.45, capacity 0.8 |

**단계 (5)~(5'') DTS의 평가.**

| tier | RAG: TTFT | RAG: SLO | RAG: score | Agent: TTFT | Agent: SLO | Agent: score |
|---|---:|:---:|---:|---:|:---:|---:|
| `dram` | 10.775 s | X | −4.7404 | 0.089 s | O | **0.5554 (선택)** |
| `hbf` | **0.724 s** | **O** | **0.2085 (선택)** | 0.040 s | O | 0.5319 |
| `cxl_pnm` | 10.945 s | X | −4.8433 | 0.089 s | O | 0.5391 |
| `custom_hbm` | 10.945 s | X | −4.9057 | 0.089 s | O | 0.4937 |
| `ssd_pim` | 3.557 s | X | −1.2275 | 0.243 s | O | 0.4225 |

호출: `sel.select(rec_rag, "hbm", states, {}, {}, hint_rag, slo)` → `"hbf"`, `sel.select(rec_agent, "hbm", ...)` → `"dram"`.

**왜 갈리는가.**

- RAG는 `index_scan`이라 `rag_retrieval_s`가 쓰인다. 어느 tier에도 GEMV 능력이 없는 경우(`dram`, `hbf`, `custom_hbm`, `cxl_pnm`)에는 `index_bytes × batch / ext_bw`만큼 vector가 링크를 건너야 한다. `dram`은 40 GiB × 16 / 64 GB/s ≈ 10.7 s라 SLO를 넘고, ext BW 1 TB/s인 `hbf`만 0.724 s로 통과한다. `ssd_pim`은 GEMV로 scan은 내부에서 끝나지만 batch 16에서 TTFT 3.557 s로 SLO(2 s)를 넘는다.
- Agent memory는 `touch_bytes`가 3.3 GB뿐이라 모든 tier의 penalty가 0.052 s 이하이고 전부 SLO를 통과한다. 그러면 affinity 점수가 결정하고, `dram`(낮은 latency + 큰 용량)이 `hbf`보다 높다 (0.5554 대 0.5319).
- **정직하게 읽어야 할 점:** 두 object의 민감도 값은 거의 같다 (0.45/0.8 동일, latency만 0.78 대 0.55). RAG를 `hbf`로 보낸 것은 "bandwidth_sensitivity가 높아서"가 아니라 **hint의 op class와 touch_bytes가 estimator를 통해 만든 SLO 필터**다. RAG의 `bandwidth_sensitivity`는 0.45다 (`access_bytes/size`가 0.025로 0.1 미만이라 `static_hints`가 낮은 쪽을 부여).
- 같은 RAG라도 96 GiB shard, batch 64로 키우면 모든 tier가 SLO를 넘고(`hbf`도 TTFT 6.635 s) `select`는 `None`을 돌려준다. **목적지가 없으면 이동하지 않는다.** object는 HBM에 남고 pressure 해소는 다른 victim에 맡겨진다.

**takeaway.** "RAG는 bandwidth, Agent memory는 latency/capacity"라는 설계 서술(§8.6 표)이 sim에서는 **민감도 숫자가 아니라 operation class + shape**로 구현되어 있다. 같은 hint 채널, 같은 `select`가 object마다 다른 destination을 만든다.

### 예시 3. 가장 끌리는 목적지를 서빙 비용 모델이 거부한다

**초기 상태.** 예시 1과 같은 KV(10 GiB, ctx 32768, batch 16, out 64)를 HBM에서 내려야 하는데 **DRAM이 가득 찬 상태**(occupancy = capacity)다. DRAM이 빠지면 affinity가 가장 높은 tier는 `cxl_pnm`이다.

**단계.**

| 단계 | actor | 결과 |
|---|---|---|
| (5) | Affinity Mapper | 용량이 되는 tier 중 affinity 최고 = **`cxl_pnm` 0.7172** (`hbf` 0.6439, `custom_hbm` 0.6400, `ssd_pim` 0.6012). affinity만 쓰면 `cxl_pnm`을 고른다 (`max(rows, key=affinity)`) |
| (5') | AccessCostEstimator | `cxl_pnm`: TTFT 0.052 s, TPOT **616.71 ms** (SLO 50 ms의 12.3배), `service_extra_s` 39.122 s, `budget_fraction` 12.2255 |
| (5'') | DTS | `slo_ok == False` (source `hbm`은 SLO를 만족하므로 "source도 위반이면 더 나은 쪽 허용" 예외에도 해당 없음) → **후보에서 제거**. 남은 후보 중 `argmax(affinity − budget_fraction)` = **`hbf` 0.6385** |
| (6)~(7) | Budget, Executor | `hbf` 전송 `10 GiB / min(64 GB/s, 1 TB/s, write 50 GB/s)` = 0.215 s. 통과 후 commit |

호출: `sel.select(rec, "hbm", states, {"dram": cap_dram}, {}, hint, slo)` → `"hbf"`.

**정확히 무엇이 거부했는가.** SLO 필터를 끄고 `affinity − budget_fraction`만 비교해도 `hbf`가 1위다 (`cxl_pnm`은 −11.5083). 즉 거부의 주체는 affinity 점수가 아니라 **estimator의 penalty 항과 SLO 필터**다 (§8.7의 serving cost 항, 평가 loop iteration 1이 추가). affinity는 오히려 CXL-PNM을 선호했다.

**같은 mechanism, 다른 shape (batch 1).** `concurrency = 1`로 바꾸면 `cxl_pnm`의 TPOT가 40.86 ms로 줄어 SLO를 **통과**한다 (`service_extra_s` 2.447 s). 그래도 score는 −0.0473이라 `hbf`(0.6385)에 진다. 정적 hint의 shape가 바뀌면 같은 tier에 대한 판정이 SLO 위반에서 "허용되지만 불리"로 바뀐다 (시나리오 `kv_b1_c32k_cold_cxl`이 이 경로를 검증하려는 것과 같은 방향).

**takeaway.** affinity는 "선호"를, estimator는 "가능성과 비용"을 말한다. C1이 type-agnostic이어도 CXL-PNM attention 경로 같은 함정을 피할 수 있는 이유는 data type을 아는 게 아니라 **hint의 op+shape + descriptor** 때문이다.

### 예시 4. 정적 affinity 승격 + swap (SLO 위반 object를 HBM으로)

**초기 상태.** HBM effective capacity 400 GiB, 거주 object 27개 합계 322 GiB (util 0.805 < 0.82라 **resource pressure 경로는 동작하지 않는다**).

| HBM 거주 object | 개수 | 크기 | hint의 op |
|---|---:|---:|---|
| KV (ctx 32768, batch 32) | 6 | 10 GiB | attention |
| Agent memory | 8 | 20 GiB | context_fetch |
| MoE expert | 6 | 4 GiB | weight_fetch |
| LoRA adapter | 4 | 1.5 GiB | weight_fetch |
| RAG | 3 | 24 GiB | index_scan |

**promotion 후보 P:** DRAM에 있는 KV 60 GiB (ctx 196608, batch 32, out 64). 상태 판정은 `est.estimate`로 얻는다.

| P의 위치 | TTFT / TPOT | SLO |
|---|---|:---:|
| `dram` | 1.156 s / **53.97 ms** | **X** (TPOT 50 ms 초과) |
| `hbm` | 0.149 s / 38.24 ms | O |

**단계 (8, `_promotion_pass`).**

1. **후보 판정.** `service_extra_s("dram")` = **gain 2.0133 s**. DRAM에서는 SLO 위반, HBM에서는 만족 → 승격 후보. 접근 rate나 type은 보지 않는다.
2. **필요 공간.** `need = max(60 − (400 − 322), 322 + 60 − 0.82 × 400) = 54 GiB`.
3. **victim 평가.** 각 HBM 거주 object에 `select(strict_pressure=False)`로 강등 목적지를 정하고 `loss = service_extra_s(dst)`, 정렬 키 = `loss / size`.

| 거주 object | 강등 목적지 | loss | loss / GiB |
|---|---|---:|---:|
| Agent 20 GiB | `dram` | 0.0644 s | **0.0032** |
| RAG 24 GiB | `hbf` | 0.4059 s | 0.0169 |
| KV 10 GiB | `dram` | 0.3355 s | 0.0336 |
| MoE 4 GiB | `dram` | 0.1342 s | 0.0336 |
| LoRA 1.5 GiB | `dram` | 0.0503 s | 0.0336 |

4. **victim 선택.** loss/GiB가 가장 작은 Agent 20 GiB 3개(id 106, 107, 108) → 60 GiB ≥ 54 GiB. `loss` 합 = 0.1931 s.
5. **margin 검사.** `gain / loss = 2.0133 / 0.1931 = 10.43` ≥ `AFFINITY_MARGIN` 2.0 → **swap 진행**.
6. **budget과 실행 (실제 `on_event` 결과).**
   - t=1: victim 3개 `hbm → dram`, reason `static_affinity_swap`. 각 전송 20 GiB / 64 GB/s = 0.336 s, 합 1.007 s. 토큰 2.000 → 0.993 s. 승격(P: 60 GiB, 1.007 s)은 0.993 s로는 부족해 `budget.reserved = 1.007 s`로 잡고 `pending_promotion`에 계획(deadline = now + 4 × 8 s = 33 s)을 남긴다.
   - t=2: 토큰 +0.25 s → 승격 `dram → hbm`, reason `static_affinity_promotion`, 토큰 0.237 s. reserved 해제.

**takeaway.** promotion trigger는 resource pressure가 아니라 **hint와 descriptor만으로 "이 object는 HBM에서만 SLO를 만족한다"는 정적 판정**에서 나온다 (설계 §17.2). swap의 자리는 "정적 손실이 가장 작은" HBM 거주 object(여기서는 touch_bytes가 작은 Agent memory)가 내준다. gain이 loss의 10.43배라 margin 2.0을 쉽게 넘는다.

### 예시 5. affinity가 구분하지 못하는 경우 (C1의 알려진 한계)

**5a. 같은 hint는 같은 결정이다.** KV 두 개 `a`, `b`(10 GiB, ctx 32768, batch 16)가 있고 실제 접근률은 `a` 3.0/s, `b` 0.15/s(20배 차이, `DataObject.rate_at`)다.

| 확인 항목 | 결과 |
|---|---|
| `static_hints([a])[a] == static_hints([b])[b]` (id 제외) | True |
| `sel.select(rec_a, "hbm", ...)`, `sel.select(rec_b, "hbm", ...)` | 둘 다 `dram` |
| 후보 tier별 (SLO, affinity, penalty) 표 | 완전히 동일 |
| `DataEvictionManager.candidates("hbm", 100.0)` 순서 | `[202, 201]` (크기·age 동률 → object_id 내림차순. 접근률과 무관) |

C1이 가진 입력(hint, size, tier, 마지막 *이동* 후 경과 시간)에는 hot과 cold 차이가 들어 있지 않다. 이것이 §10 한계와 §24의 경계가 말하는 "같은 class 안 object 구분 불가"다.

**5b. 정적 신호가 비슷하면 swap은 margin에 막히거나, 막히지 않아도 엉뚱한 object가 선택된다.** 예시 4의 승격 후보 P(gain 2.0133 s)를 두고, HBM 거주 object를 **모두 같은 class**로 바꾼다: KV 8개(ctx 131072, batch 32, 각 40 GiB, 합 320 GiB, util 0.8). 이 중 4개(id 300~303)는 접근률 0.3/s, 4개(304~307)는 사실상 idle(0.015/s)이다. `need = 52 GiB` → victim 2개 필요.

| 조건 | victim 강등 목적지 | loss(개당) | 2개 합 | gain / loss | margin 2.0 | 결과 |
|---|---|---:|---:|---:|:---:|---|
| **HBF가 가득 참** | `dram` | 1.3422 s | 2.6844 s | **0.75** | 미달 | **swap 안 함** (3 tick 동안 decision 0건. 토큰 2.000 s 유지) |
| HBF에 여유 있음 | `hbf` | 0.0859 s | 0.1718 s | 11.72 | 통과 | swap 진행: t=1에 victim **300, 301**을 `hbm → hbf`, 토큰 0.282 s로 모자라 승격은 reserved 대기, t=4에 승격(토큰 0.025 s) |

- 첫 행: SLO를 어기고 있는 P는 그대로 남는다. 어느 victim이 cold인지 모르는 C1은 "40 GiB KV를 DRAM으로 내렸을 때의 정적 손실"만 볼 수 있고, 그 손실(1.3422 s)이 gain(2.0133 s)과 같은 자릿수라 margin을 넘지 못한다. 같은 class끼리는 gain과 loss가 크기 비례 정도로만 다르다 (`dp1-c1-qa1-complement-design.md` §1.2).
- 둘째 행: swap은 일어나지만 **내려간 victim은 hot한 300, 301**이다. 정렬 키(`loss / size`)가 모두 같으면 object_id 오름차순이 tie-break이기 때문이다. idle인 304~307이 아니다. C2의 `DataBehaviorMonitor`는 이 둘을 구분한다.

**takeaway.** C1의 승격/swap 결과는 **object의 실제 hotness가 아니라 정적 손실과 tie-break에 의해** 정해진다. 이 한계를 줄이려면 관측 신호가 필요하고, 그만큼 C2 쪽으로 이동한다 (§17.2 마지막 문장, complement design §6.2 fence).

## 10A.5 Mapper가 할 수 있는 것 / 없는 것 (측정 결과와 함께)

| 구분 | 내용 | 근거 |
|---|---|---|
| **할 수 있다** | operation class + shape로 "이 tier에서는 SLO를 못 맞춘다"를 type 이름 없이 판정해 목적지를 거르고 (예시 3), shape에 따라 destination을 달리 정한다 (예시 2). | 본 절의 호출 결과 |
| **할 수 있다** | resource pressure가 없어도, SLO를 어기는 낮은 tier object를 HBM으로 올리는 promotion trigger를 만든다 (예시 4). C1의 처리량 이득 대부분이 여기서 나온다. | 아래 ablation |
| **할 수 없다** | 같은 class, 같은 shape인 object 사이의 hot/cold 구분 (예시 5a), 이에 따른 victim 선택과 swap 대상 선택 (예시 5b). | 본 절, complement design §1.2 |
| **할 수 없다** | workload phase 변화나 request-specific reuse 변화의 반영 (hint는 등록 시 고정). | §10 한계 |
| **약하다** | affinity **점수** 자체. SLO-feasible 후보 사이를 가르는 tie-breaker 수준이고 (예시 1의 0.014 차이), 평가에서는 측정 가능한 기여가 없었다. | 아래 ablation |

**평가 결과 인용 (출처: `Evaluation/DP1/results/2026-10-02_dp1-qa-evaluation.md` §4.7, 5 seed, 동일 시나리오, simulation [B+C]).**

| 지표 | Baseline | C1 affinity 제거 | C1 (affinity 포함) | C2 |
|---|---:|---:|---:|---:|
| QA1 goodput (tok/s) | 336 | 354 (x1.05) | 436 (x1.30) | 478 (x1.42) |
| QA2 TTFT P99 (ms) | 1,084 | 1,372 (x1.27) | 1,128 (x1.04) | 785 (x0.72) |
| Baseline 대비 승/무/패 | - | 2/29/0 | 6/25/0 | 10/21/0 |

| C1 변형 | QA1 배수 | TTFT P99 배수 | 승/무/패 |
|---|---:|---:|---|
| affinity 포함 | x1.298 | x1.04 | 6/25/0 |
| affinity **점수**만 제거 (DTS) | x1.299 | x1.04 | 6/25/0 |
| 정적 affinity **승격**만 제거 | x1.053 | x1.27 | 2/29/0 |

- 같은 문서의 결론: "효과의 출처는 정적 affinity 승격 pass다. affinity 점수만 빼면 x1.299로 거의 변화가 없고, 승격 pass를 빼면 x1.053로 떨어진다." 즉 §10A.2의 **단계 8이 성능을 만들고, 단계 5의 점수는 현재 평가에서 측정 가능한 기여가 없다** (예시 4와 예시 1의 차이와 일치한다). 단, 서빙 비용 estimator(단계 5')는 모든 변형에 남겨 둔 공유 module이라 이 ablation으로 그 기여는 분리되지 않았다.
- 같은 문서의 한계 서술: "affinity를 포함해도 C1의 처리량(x1.30)은 C2(x1.42)보다 낮다. affinity는 격차를 대부분 줄이지만 C2를 이기게 하지는 않는다."
- `dp1-c1-qa1-complement-design.md` §1.2의 동적 시나리오(`recency_shift`, `idle_kv`, `rotating`) 진단: C1의 migration은 run당 0.8~1.6회(C2 20.6~30.4회)이고, C1의 `seeds_goodput`이 같은 seed의 Baseline과 **완전히 같은** 경우가 15개 중 10개다. 예시 5가 보이는 "정적 신호로는 움직일 근거가 없다"의 실측 쪽 증거다.
- **caveat:** 위 수치는 simulation [B+C]이며 cost 추정 오차 0 조건이다 (평가 문서 §4.6의 오차 sweep 참고). 별 합계 선택(C1 10 대 C2 9)은 QA2 별 경계(x1.28 대 1.25)에 민감하다고 해당 문서가 적었다.

---

# 11. Candidate 2 — AI Data Behavior-driven Migration

## 11.1 Design Intent

C2의 기본 원칙은 다음과 같다.

> **각 AI Data의 runtime reuse/access/lifetime behavior를 관찰하고,
> 향후 사용 가능성을 예측하여 data별 migration을 결정한다.**

Resource state는 여전히 constraint로 사용하지만,
decision의 중심 signal은 **data behavior**다.

~~~text
Primary signal
  = Data Behavior / Future Behavior

Constraint
  = Resource Capacity / BW / Load

Object identity / class
  = Data Object Registry
~~~

---

# 12. C2 Component Architecture

~~~mermaid
flowchart TD
    EV["Event"]
    MS["Migration Scheduler"]

    DBM["Data Behavior<br/>Monitor"]
    BTA["Behavior-based<br/>Trend Analyzer"]
    FBP["Future Behavior<br/>Predictor"]

    DOR["Data Object Registry"]
    KV["KV Cache"]
    AM["Agent Memory"]
    LA["LoRA Adapter"]
    MOE["MoE Expert"]
    IDX["Vector Index Cache"]
    META["Data Class Metadata"]

    DTS["Destination Tier<br/>Selector"]
    MDS["Migration Data<br/>Selector"]
    ME["Migration Executor<br/>(common migration boundary)"]

    RM["Resource Manager"]
    TC["Telemetry Collector"]
    MR["Memory Registry<br/>(Backend Registry)"]
    MBI["Common Memory Backend I/F<br/>(Plug-in)"]
    MEMS["HBM / ScHBM / DRAM / CXL-PNM<br/>HBF / SSD / SSD-PIM / + New"]

    EV --> MS
    MS -. "Event push (async)" .-> DBM

    DBM -->|"object / behavior association"| DOR
    DBM -->|"data affinity / behavior info"| BTA
    BTA --> FBP

    DOR --> KV
    DOR --> AM
    DOR --> LA
    DOR --> MOE
    DOR --> IDX
    DOR --> META

    RM --> TC
    RM --> MR
    MR --> MBI
    MBI -->|"plug-in"| MEMS
    MBI -->|"MemoryTelemetry"| TC

    FBP -->|"predicted behavior"| DTS
    FBP -->|"predicted behavior"| MDS

    TC -->|"② capacity / BW / load"| DTS
    MR -->|"①③ capability ·<br/>transfer cost"| DTS

    DTS --> ME
    MDS --> ME
~~~

구조의 핵심 path는 다음과 같다.

~~~text
Event
  → Migration Scheduler
  → Data Behavior Monitor
  → Behavior-based Trend Analyzer
  → Future Behavior Predictor
  → Destination Tier Selector / Migration Data Selector
  → Migration Executor boundary
~~~

Data Object Registry는 Data Behavior Monitor가 관찰한 behavior를
stable data object / data class와 연결하는 공통 metadata anchor다.

---

# 13. C2 Component Responsibilities

## 13.1 Migration Scheduler

C2에서 Event를 받으면 Data Behavior Monitor의 evaluation cycle을 비동기로 시작한다.

~~~text
Event
  ↓
Migration Scheduler
  ↓ async
Data Behavior Monitor
~~~

C1과 entry pattern은 동일하다.
후속 pipeline만 resource-driven과 behavior-driven으로 달라진다.

## 13.2 Data Behavior Monitor

각 data object의 runtime behavior signal을 수집한다.

~~~text
DataBehaviorState
 ├─ object_id
 ├─ data_type
 ├─ last_access_time
 ├─ access_count
 ├─ access_interval
 ├─ reuse_distance
 ├─ residency_time
 ├─ lifetime_state
 ├─ request / session relation
 └─ data-specific signals
~~~

Behavior Monitor는 Data Object Registry를 이용해
event를 logical object identity와 data class에 연결한다.

## 13.3 Data Object Registry — Type-aware

C2의 Registry는 C1과 달리 **AI Data type별 특징을 관리하는 type-aware registry**다.

C2의 Registry는 다음 역할을 한다.

- data object identity 관리
- object의 type/class 관리
- 현재 location / tier / size metadata 관리
- KV Cache / Agent Memory / LoRA / MoE / Vector Index 등의 data-class metadata 연결
- Data Behavior Monitor가 수집한 event를 올바른 object에 귀속시키는 lookup 기준 제공

~~~text
Data Object Registry
 ├─ KV Cache objects
 ├─ Agent Memory objects
 ├─ LoRA Adapter objects
 ├─ MoE Expert objects
 ├─ Vector Index Cache objects
 └─ Data Class Metadata
~~~

기존 문서의 별도 **Data Class Adapter**는 현재 PPT 구조에서는
독립 top-level component로 두지 않는다.

필요한 data-class별 normalization/interpretation은
Data Object Registry의 data-class metadata 또는
Data Behavior Monitor 내부 adapter/plugin으로 구현할 수 있다.

즉 architecture view에서는 다음처럼 단순화한다.

~~~text
Data-specific runtime event
        │
        ▼
Data Behavior Monitor
        │
        ├─ Data Object Registry lookup
        └─ data-class metadata reference
        │
        ▼
normalized behavior information
~~~

## 13.4 Behavior-based Trend Analyzer

시간에 따른 behavior 변화를 분석한다.

- access frequency increasing / decreasing
- reuse interval shortening / lengthening
- session/lifetime 변화
- expert activation frequency trend
- adapter popularity trend

~~~text
BehaviorTrend
 ├─ recency_score
 ├─ frequency_score
 ├─ reuse_trend
 ├─ lifetime_stage
 ├─ hotness_trend
 └─ confidence
~~~

## 13.5 Future Behavior Predictor

현재 behavior trend로부터 near-future data value를 예측한다.

~~~text
B1 → HOT, high reuse probability
B2 → WARM
B3 → COLD, low reuse probability
~~~

또는 연속 score:

~~~text
future_reuse_probability(B1) = high
expected_next_access(B1)     = near
expected_remaining_lifetime  = long
~~~

구체적인 predictor algorithm은 DP1 architecture와 분리한다.

가능한 구현:

- rule/threshold
- exponential moving average
- reuse-distance model
- state transition model
- lightweight ML predictor

## 13.6 Destination Tier Selector / Migration Data Selector

예측 결과와 resource state를 함께 사용한다.

~~~text
Predicted Data Behavior
          +
Current Resource State
          +
Memory Capability
          +
Current Object Location
          │
          ▼
Data Object × Memory Tier matching
~~~

C2도 §8.7과 같은 **serving cost 항**과 **link-time migration budget**을 쓰며, 추가로 **benefit-vs-cost gating**을 둔다: 예측된 접근 이득(Predictor가 expected access rate를 출력해야 함)이 전송 비용을 넘을 때만 이동한다.
또한 demotion은 §17.3대로 **upper-tier pressure가 있을 때만** 수행한다 (평가 loop 전에는 이 조건이 구현되지 않아 migration churn이 발생했다).

C2에서 Resource Manager와 직접 연결되는 모듈은 **Destination Tier Selector**이며,
Telemetry Collector(② capacity·BW·load)와 Memory Registry(①③ capability·transfer cost)를 모두 읽는다.
Migration Data Selector는 Resource Manager를 직접 조회하지 않고 Future Behavior Predictor의 결과를 사용한다.

C2는 같은 data class 내부 object들도 서로 다른 tier로 migration할 수 있다.

---

# 14. C2 Main Sequence

~~~mermaid
sequenceDiagram
    participant E as Event Source
    participant MS as Migration Scheduler
    participant DBM as Data Behavior Monitor
    participant DOR as Data Object Registry
    participant BTA as Behavior Trend Analyzer
    participant FBP as Future Behavior Predictor
    participant RM as Resource Manager
    participant DTS as Destination Tier Selector
    participant MDS as Migration Data Selector
    participant MC as MigrationCoordinator

    E->>MS: Migration / data behavior event
    MS-->>DBM: async event push

    DBM->>DOR: lookup object identity / class / current location
    DOR-->>DBM: object metadata + data-class metadata

    DBM->>BTA: normalized behavior / affinity information
    BTA->>FBP: behavior trend
    FBP->>FBP: predict future reuse / lifetime / hotness

    RM-->>DTS: ② resource state + ①③ capability / transfer cost

    FBP->>DTS: predicted behavior
    FBP->>MDS: predicted behavior

    DTS-->>MC: target resource
    MDS-->>MC: selected data objects
    MC->>MC: build MigrationIntent
~~~

---

# 15. C2 Strengths / Limitations

## 장점

- **Data 종류 및 object별 Access 특성에 맞는 Fine-grained migration 가능**
- **같은 class 내부에서도 hot/warm/cold object를 구분 가능**
- **고속 tier의 불필요한 점유 감소 가능**
- **promotion과 demotion 모두 자연스럽게 지원**
  - cold prediction → demotion
  - renewed hotness / reuse prediction → promotion
- **Type-aware Data Object Registry**
  - C1과 동일한 Registry를 공유하는 것이 아니라, C2는 data type/class별 metadata를 관리하는 별도 abstraction을 사용

## 한계

- **Data 종류별 Characterization 비용 증가**
- **Monitoring overhead 증가**
- **Prediction overhead 증가**
- **예측 오류 시 Mis-placement 가능**
- **Thrashing 위험**

따라서 C2는 cooldown, hysteresis, confidence threshold, migration budget 같은
anti-thrashing mechanism이 중요하다.

---

# 16. C1 vs C2 — Decision Flow Comparison

~~~text
Common Entry
Event
  │
  ▼
Migration Scheduler
  │
  ├───────────────────────────────┐
  │                               │
  ▼                               ▼
C1                              C2
Resource State Monitor          Data Behavior Monitor
  │                               │
  ▼                               ├── Data Object Registry
Resource Trend                    │
+ Eviction Manager                ▼
  │                            Behavior Trend
  ├── Data Object Registry        │
  │                               ▼
  ▼                            Future Behavior
Static Data-Memory                Prediction
Affinity                          │
  │                               │
  ▼                               ▼
Data + Target Tier              Data + Target Tier
  │                               │
  └───────────────┬───────────────┘
                  ▼
            MigrationIntent
~~~

정리하면:

> **공통 = Event → Migration Scheduler → candidate-specific decision pipeline**  
> **C1 = Resource pressure가 migration을 주도하고 type-agnostic Registry의 위치/크기 정보에 eviction policy를 적용하며, static affinity는 별도 Mapper가 보정**  
> **C2 = Data의 future behavior가 migration을 주도하고 type-aware Registry가 object를 data class별 특징/metadata와 연결**

---

# 17. Promotion / Demotion Semantics

두 후보 모두 promotion과 demotion을 지원할 수 있지만 trigger 성격이 다르다.

## 17.1 C1 Demotion

~~~text
Event
  → Migration Scheduler
  → HBM pressure rising
  → free capacity required
  → Data Object Registry에서 candidate 조회
  → lower tier selection
  → demotion
~~~

## 17.2 C1 Promotion

resource state만으로는 promotion trigger가 상대적으로 약하다.

가능한 trigger:

- upper-tier capacity/pressure가 충분히 회복된 event
- static affinity상 upper tier 선호 object가 lower tier에 존재
- explicit demand/event로 해당 object가 다시 필요해짐

다만 object별 future reuse를 지속 예측하기 시작하면 C2 영역에 가까워진다.

## 17.3 C2 Demotion / Promotion

~~~text
future reuse probability ↓
+ upper-tier pressure
→ demotion

reuse / access trend ↑
+ expected near-future access
+ upper-tier capacity available
→ promotion
~~~

C2는 data behavior 자체가 promotion/demotion의 강한 signal을 제공한다.

### 17.4 Action 관점

| 방향 | 기본 action | 대안 action |
|---|---|---|
| Demotion | `MOVE` | 하위 tier 복제본/재계산 경로가 있으면 `DROP` (copy 및 write 비용 회피) |
| Promotion | `MOVE` | 하위 tier 복제본을 유지하려면 `REPLICATE` (이후 demotion은 `DROP`) |
| Tier 변경 불필요 | — | `RECLASSIFY` (priority/hotness만 갱신), 공유 pool이면 `REMAP` |

---

# 18. QA Trade-off

현재 PPT의 정성 평가를 문서에 정리하면 다음과 같다.

| QA | C1 Resource State + Affinity | C2 Data Behavior-driven | 해석 |
|---|---:|---:|---|
| Performance Efficiency — Throughput | ●●○ | ●●○ | C1은 decision이 가볍고, C2는 fine-grained migration 이점과 monitoring/prediction overhead가 상쇄 가능 |
| Performance Efficiency — Latency (TTFT, TPOT) | ●●○ | ●●● | C2는 hot data를 적절한 tier에 둘 수 있어 steady-state latency에 유리할 가능성. 단 prediction miss 시 반대 가능 |
| Resource Utilization | ●●● | ●●○ | C1은 pool pressure를 직접 기준으로 전체 memory capacity 활용에 유리. C2는 data-optimal decision이 resource-global optimum과 항상 같지는 않음 |
| Modifiability | ●●● | ●●○ | C1은 static affinity 확장 중심. C2는 behavior feature/predictor 변경 영향이 큼 |

> 위 점수는 **architecture-level qualitative hypothesis**이며 측정 결과가 아니다.
> PPT의 00 TPS / 00 ms / 00%는 아직 simulation/benchmark 값이 들어가지 않은 placeholder이므로
> 실제 수치 평가는 별도의 QA simulation 문서에서 정의해야 한다.

Event-driven Migration Scheduler와 공통 Data Object Registry는
두 후보에 동일하게 추가되므로 **C1/C2 간 QA 차이를 만드는 핵심 요인으로 보지 않는다.**
차이는 Scheduler 이후 decision pipeline에서 발생한다.

---

# 19. QA Measurement Direction

## 19.1 Throughput

관찰 대상:

~~~text
request/s
output token/s
migration decision/s
migration bytes/s
event handling overhead
migration scheduler queue delay
predictor overhead
~~~

C2에서는 behavior event collection overhead와 predictor CPU cost,
metadata footprint를 별도로 측정한다.

## 19.2 Latency

~~~text
TTFT
TPOT
migration-induced stall
promotion wait time
event-to-decision latency
decision latency
~~~

Event 기반 구조에서는 다음 구간을 별도로 보는 것이 좋다.

~~~text
T_event_to_decision
 = T_event_queue
 + T_monitor
 + T_analysis
 + T_selection
~~~

C2에서는 prediction hit/miss를 구분해야 한다.

## 19.3 Resource Utilization

~~~text
HBM occupancy
DRAM/CXL occupancy
aggregate pool utilization
tier imbalance
unused capacity
bandwidth utilization
~~~

C1의 pressure relief 효율:

~~~text
Pressure Relief Efficiency
 = useful freed bytes / migrated bytes
~~~

C2의 hot-tier residency quality:

~~~text
Hot-tier Useful Residency
 = accesses served by correctly promoted data
   / total hot-tier data residency
~~~

## 19.4 Modifiability

변경 시 영향을 받는 module 수와 interface 변경 범위를 본다.

- 신규 event type 추가
- 신규 memory tier 추가
- 신규 AI data class 추가
- Data Object Registry schema 확장
- predictor 변경
- affinity rule 변경
- telemetry metric 추가

**신규 memory tier 추가**는 C1/C2 공통으로 Memory Backend I/F(§5.8)가 흡수한다.
측정 기준은 "신규 memory 1종 추가 시 `decision/` 하위 변경 파일 수 = 0, 추가 파일 = Backend plug-in 1 + Descriptor 1 (+ TransferHandler 1)"이다.
기존 구조(Selector/Monitor/Registry schema) 수정이 필요하면 Memory Interface 추상화가 부족한 것으로 판단한다.

C1은 신규 data type 추가 시
Registry metadata + affinity metadata 추가로 대응 가능한 범위가 넓다.

C2는 신규 data type별
behavior feature / interpretation / predictor input 검토가 필요하다.

---

# 20. vLLM / Migration Architecture Mapping

DP1은 기존 vLLM **Scheduler → Executor → Worker** call path를 대체하지 않는다.

현재 구조에서는 request path의 특정 지점이 migration logic을 동기 호출하는 형태보다,
runtime Event를 DP1 Migration Scheduler에 전달하고
별도의 decision cycle을 비동기로 실행하는 구조를 사용한다.

~~~text
Runtime / vLLM Event
        │
        ▼
DP1 Migration Scheduler
        │
        ├───────────────┬───────────────┐
        │               │
        ▼               ▼
C1 Resource         C2 Behavior
Decision Pipeline   Decision Pipeline
        │               │
        └───────┬───────┘
                │
                ▼
         MigrationDecision
                │
                ▼
         MigrationIntent
                │
                ▼
      MigrationCoordinator
                │
         MigrationPlanner
                │
     execution-side queue/scheduler
                │
       MigrationExecutor
                │
          Worker side
                │
       Transfer Handlers
                │
       HBM/DRAM/CXL/SSD
~~~

Decision plane이 memory를 바라보는 경로는 다음과 같이 공통 Memory Backend I/F 하나로 제한한다.

~~~text
C1/C2 Decision Pipeline
        │  MemoryDescriptor / MemoryTelemetry (capability 기반 조회)
        ▼
Common Memory Backend I/F (Plug-in)      ← 신규 memory는 여기에 등록
        │  MemoryTransferBinding
        ▼
TransferHandlerRegistry (공통 migration subsystem)
~~~

여기서 두 scheduler를 구분한다.

| Component | 역할 |
|---|---|
| **DP1 Migration Scheduler** | Event-driven decision orchestration. C1/C2 monitor/analysis pipeline을 시작 |
| **Execution-side Migration Scheduler/Queue** | 이미 결정된 MigrationPlan의 실행 순서/priority/bandwidth를 관리 |

---

# 21. Recommended Module Boundary

구현 관점에서는 다음 package boundary가 적절하다.

~~~text
vllm/v1/data_migration/
├── coordinator.py
├── planner.py
├── execution_scheduler.py          # execution-side migration queue
├── ...
│
├── decision/                       # DP1 decision layer
│   ├── migration_scheduler.py      # Event-driven DP1 Migration Scheduler
│   ├── events.py
│   ├── base.py
│   │
│   ├── resource_driven/
│   │   ├── data_object_registry.py # type-agnostic: location/size/tier

│   │   ├── state_monitor.py
│   │   ├── trend_analyzer.py
│   │   ├── eviction_manager.py
│   │   ├── affinity_mapper.py
│   │   ├── destination_selector.py
│   │   └── data_selector.py
│   │
│   └── behavior_driven/
│       ├── data_object_registry.py # type-aware: data-class metadata
│       ├── behavior_monitor.py
│       ├── trend_analyzer.py
│       ├── predictor.py
│       ├── destination_selector.py
│       └── data_selector.py
│
├── resource/
│   ├── registry.py                 # MemoryBackendRegistry (plug-in 등록부)
│   ├── descriptor.py               # MemoryDescriptor / capability flags
│   ├── telemetry.py                # MemoryTelemetry / Telemetry Collector
│   ├── backend.py                  # MemoryBackend (abstract plug-in contract)
│   └── backends/                   # memory별 plug-in (신규 memory는 여기에만 추가)
│       ├── hbm.py
│       ├── dram.py
│       ├── cxl.py                  # CXL-PNM 포함 (compute capability flag)
│       ├── hbf.py
│       ├── ssd.py                  # SSD-PIM 포함
│       └── <new_memory>.py
│
└── worker/
    └── executor.py
~~~

`decision/`은 `resource/backends/`를 **import하지 않는다.**
`decision/`이 보는 것은 `resource/backend.py`, `descriptor.py`, `telemetry.py`의 추상 type뿐이다.

Data-class별 세부 logic이 필요하면
Data Object Registry의 metadata provider 또는
Data Behavior Monitor plugin으로 확장할 수 있다.

~~~text
behavior_driven/
└── plugins/
    ├── kv_cache.py
    ├── agent_memory.py
    ├── lora.py
    ├── moe.py
    └── vector_index.py
~~~

중요한 원칙은 다음과 같다.

> **C1과 C2의 Data Object Registry는 이름만 같고 abstraction은 다르다.**  
> **C1 Registry는 type-agnostic placement bookkeeping이고, C2 Registry는 type-aware AI Data metadata registry다.**

---

# 22. Recommended Interfaces

## 22.1 Event Input

~~~text
MigrationEvent
 ├─ event_id
 ├─ event_type
 ├─ timestamp
 ├─ resource_id?
 ├─ data_ref?
 └─ metadata
~~~

## 22.2 Migration Scheduler

~~~text
MigrationScheduler.on_event(event)

  → enqueue / coalesce event
  → select decision pipeline
  → asynchronously trigger evaluate()
~~~

## 22.3 Data Object Registry Interfaces

C1/C2는 Registry interface도 동일하다고 가정하지 않는다.

### C1 Placement Registry

~~~text
C1DataObjectRegistry
  get(object_id) -> C1DataObjectRecord
  get_by_tier(tier) -> list[C1DataObjectRecord]
  get_movable(resource_id) -> list[C1DataObjectRecord]

C1DataObjectRecord
  object_id
  size_bytes
  current_tier
  current_location
  movable / pin state
~~~

C1 Registry는 **data_type field를 요구하지 않는다.**
Eviction Manager는 위 generic metadata에 eviction policy를 적용해 victim을 고른다.

### C2 Type-aware AI Data Registry

~~~text
C2DataObjectRegistry
  get(object_id) -> C2DataObjectRecord
  get_by_type(data_type) -> list[C2DataObjectRecord]
  get_class_metadata(data_type) -> DataClassMetadata

C2DataObjectRecord
  object_id
  data_type
  size_bytes
  current_tier
  current_location
  class_metadata
  behavior_metadata_ref
~~~

C2 Registry는 data type/class별 특징을 Behavior Monitor와 Predictor가 사용할 수 있게 제공한다.

두 Registry 모두 실제 migration 완료 후 location 변경은
공통 migration control plane의 authoritative commit 결과와 동기화되어야 한다.

## 22.4 Common Policy Interface

~~~text
MigrationDecisionPolicy.evaluate(
    event,
    resource_snapshot,
    data_object_registry,
) -> list[MigrationDecision]
~~~

## 22.5 MigrationDecision

~~~text
MigrationDecision
 ├─ action                    # MOVE | REPLICATE | DROP | REMAP | RECLASSIFY (§2.1)
 ├─ data_refs[]
 ├─ source_resource
 ├─ target_resource?
 ├─ direction                 # promotion | demotion | lateral | none(RECLASSIFY)
 ├─ reason
 ├─ priority
 ├─ score
 └─ policy_metadata
~~~

## 22.6 C1 Policy Metadata

~~~text
policy_metadata
 ├─ trigger_event
 ├─ pressure_type
 ├─ pressure_score
 ├─ predicted_pressure
 ├─ affinity_class
 └─ eviction_reason
~~~

## 22.7 C2 Policy Metadata

~~~text
policy_metadata
 ├─ trigger_event
 ├─ behavior_class
 ├─ reuse_score
 ├─ predicted_hotness
 ├─ prediction_confidence
 └─ lifetime_state
~~~

## 22.8 Common Memory Backend Interface

Resource Manager 아래의 plug-in contract다 (슬라이드 8~10, 상세: §5.8). 호출 주체는 Resource Manager의 두 컴포넌트뿐이다.

~~~text
MemoryBackend  (plug-in contract)
  descriptor()       -> MemoryDescriptor         # ① static capability       ← Memory Registry.register()
  transfer_binding() -> MemoryTransferBinding    # ③ 전송 경로/비용 정보       ← Memory Registry.register()
  telemetry()        -> MemoryTelemetry          # ② dynamic state (pull)     ← Telemetry Collector.collect()
  subscribe(cb)                                  # ② dynamic state (push, optional)
  health()           -> HealthState              # ④ 상태 변화 → RESOURCE_CHANGED event
  export_async(region, staging) -> handle        # staging primitive (§5.8.11) ← 공통 TransferHandler
  import_async(staging, region) -> handle
~~~

Resource Manager가 decision 모듈에 제공하는 기능 (제안 명칭):

~~~text
Memory Registry                                   # → Destination Tier Selector (C1, C2)
  register(backend) / unregister(resource_id)     # ①③ 읽어 캐시
  get_descriptor(resource_id) -> MemoryDescriptor # capability
  list(filter: CapabilityFilter) -> list[MemoryDescriptor]
  get_binding(src, dst) -> MemoryTransferBinding  # transfer cost
  tier_order() -> list[resource_id]               # descriptor에서 파생된 rank (partial order, §5.8.3)

Telemetry Collector                               # → Resource State Monitor (C1), Destination Tier Selector (C2)
  collect()                                       # backend.telemetry() 수집, 이력 보관 (decision 경로 밖)
  snapshot() -> ResourceSnapshot                  # cycle 시작 시점의 immutable 값 (capacity·BW·load)
~~~

호출 관계:

| 호출 주체 | 호출 대상 | 시점 |
|---|---|---|
| Memory Registry | `descriptor()`, `transfer_binding()` | boot / hot-plug (이후 캐시) |
| Telemetry Collector | `telemetry()` / `subscribe()` | 상시, 비동기 |
| Resource Manager | `health()` | 상태 변화 시 event 발행 |
| 공통 TransferHandler | `export_async` / `import_async` | migration 실행 (DP1 범위 밖) |
| Resource State Monitor | `Telemetry Collector.snapshot()` | decision cycle |
| Destination Tier Selector | `Memory Registry.list/get_binding/tier_order`, (C2) `Telemetry Collector.snapshot()` | decision cycle |

Decision plane 사용 규칙:

~~~text
Resource State Monitor / Destination Tier Selector
  → Resource Manager (Telemetry Collector / Memory Registry) 로만 memory 정보를 조회
  → MemoryBackend를 직접 호출하지 않는다
  → resource_id / memory_type 문자열 비교(if type == "CXL") 금지
~~~

---

# 23. Important Boundary: C1 Registry vs C2 Registry

C1과 C2 모두 Data Object Registry라는 이름을 사용하지만,
**동일한 Registry abstraction이 아니다.**

## 23.1 C1 Registry — Type-agnostic placement bookkeeping

~~~text
"object B17은 CXL0에 있다"
"크기는 256 MB다"
"현재 movable 상태다"
~~~

- object ID
- location / tier
- size
- movable / pin state
- basic lifecycle

C1 Registry는 다음을 모른다.

~~~text
B17이 KV Cache인지
LoRA인지
MoE Expert인지
future reuse가 높은지
~~~

Victim 선택은 Registry의 generic metadata를 입력으로
Eviction Policy가 수행한다.

## 23.2 C2 Registry — Type-aware AI Data metadata

~~~text
"B17은 KV Cache다"
"KV-specific metadata는 ..."
"A3는 LoRA Adapter다"
"E5는 MoE Expert다"
~~~

그리고 Behavior Monitor가 runtime history를 결합한다.

~~~text
type-specific metadata
+ access / reuse / lifetime history
        ↓
Behavior Trend / Prediction
~~~

따라서 차이는 다음과 같다.

> **C1 Registry = 어디에 있고 얼마나 큰가를 관리**  
> **C2 Registry = 어떤 종류의 AI Data이며 그 type-specific 특징이 무엇인지까지 관리**

C2는 그 위에 runtime behavior prediction까지 추가한다.

---

# 24. Important Boundary: Static Affinity vs Dynamic Behavior

C1과 C2가 비슷해 보이지 않도록 이 경계를 명확히 유지해야 한다.

## C1 static affinity

~~~text
"KV Cache는 generally latency/BW sensitive"
"Agent Memory는 capacity-rich tier도 허용 가능"
"MoE Expert weight는 bandwidth-rich tier가 유리할 수 있음"
~~~

- design-time / configuration-time 지식
- data class / operation 수준
- request마다 다시 학습하지 않음
- runtime access history가 없어도 동작

## C2 dynamic behavior

~~~text
"KV block B17의 최근 reuse가 증가 중"
"Expert E5의 activation frequency가 증가 중"
"LoRA A3의 active session이 종료되어 reuse 가능성이 낮아짐"
~~~

- runtime observation
- object/session 수준
- 시간에 따라 계속 바뀜
- history와 prediction이 필요

따라서 **C1의 type-agnostic Registry + 별도 Affinity Mapper**와
**C2의 type-aware Registry + Behavior Monitor/Predictor**는 구조적으로 구분된다.

---

# 25. Design Decision Summary

## 공통 Entry Structure

~~~text
Event
  ↓
Migration Scheduler
  ↓ asynchronous decision trigger
C1 or C2
~~~

## 공통 Memory Interface Structure (쟁점 2)

~~~text
C1 / C2 decision pipeline
  ↓  (Tier 이름이 아니라 MemoryDescriptor / MemoryTelemetry로만 memory를 본다)
Common Memory Backend I/F  — Descriptor · Telemetry · Transfer Binding
  ↓  plug-in 등록
HBM / ScHBM / DRAM / CXL-PNM / HBF / SSD / SSD-PIM / + New
~~~

- decision plane은 memory 종류를 모르고 capability/telemetry만 소비한다.
- 신규 memory는 Backend plug-in 1개 + Descriptor 1개 + (필요 시) TransferHandler 1개 추가로 편입한다.
- C1/C2 Selector, Monitor, Registry schema는 신규 memory 추가 시 변경하지 않는 것을 목표로 한다.
- 이 I/F는 C1/C2 **공통**이므로 후보 선택(Q1/Q2)과 독립적으로 확정할 수 있다.

## C1 — Resource State-driven + Data-Memory Affinity

~~~text
Resource pressure is the primary signal.
Type-agnostic Data Object Registry provides location/size/tier.
Eviction Policy selects victims from generic metadata.
Static AI Data characteristics are refined separately by the Affinity Mapper.
~~~

주요 특성:

- event-driven / asynchronous entry
- low decision overhead
- fast pressure response
- strong global pool utilization orientation
- type-agnostic placement Registry
- eviction-policy-based victim selection
- static AI data hints are handled separately by Affinity Mapper
- Agent-aware KV lifecycle은 별도 구조에서 보완

## C2 — AI Data Behavior-driven

~~~text
Future data usage is the primary signal.
Type-aware Data Object Registry manages object identity and data-class metadata.
Behavior analysis predicts future usage.
Resource state constrains the decision.
~~~

주요 특성:

- event-driven / asynchronous entry
- data/object-specific migration
- dynamic behavior monitoring
- future behavior prediction
- fine-grained hot-tier usage
- higher overhead / mis-placement risk

공통 migration execution은
**doc-mk/vllm-ai-data-migration-architecture.md**의
MigrationCoordinator / MigrationPlanner / MigrationExecutor 구조를 재사용한다.

---

# 26. Follow-up Items

DP1 상세 설계에서 다음 항목은 별도 페이지/문서로 구체화한다.

1. **Migration Event Model**
   - 어떤 event가 C1/C2 evaluation을 trigger하는지
   - event coalescing / debounce / priority
2. **C1/C2 Data Object Registry Schema**
   - C1: type-agnostic location / size / tier / movable state
   - C2: type-aware data-class metadata + behavior metadata reference
   - location update ownership
3. **C1 Data-Memory Affinity Table**
   - KV / Agent Memory / LoRA / MoE / Vector Index별 static hint 정의
4. **C1 Resource Trend Function**
   - pressure score / threshold / look-ahead window
5. **C1 Eviction Candidate Policy**
   - LRU / size-aware / pressure-relief-aware
6. **C2 Behavior Feature Schema**
   - data class별 observable 정의
7. **C2 Future Behavior Predictor**
   - rule-based vs history-based predictor
8. **C2 Anti-thrashing**
   - confidence / hysteresis / cooldown / migration budget
9. **QA별 quantitative evaluation criteria**
   - TPS, TTFT/TPOT, utilization, event-to-decision latency 기준
10. **Simulation workload**
   - KV reuse skew / LoRA popularity / MoE expert skew / memory pressure 변화 시나리오
11. **Memory Backend I/F 상세 (§5.8, §22.8)**
   - MemoryDescriptor / MemoryTelemetry / MemoryTransferBinding field 확정
   - capability flag vocabulary (v1 필수/선택 분리) 및 version 정책
   - tier ordering(rank) 산정 규칙과 수동 override 정책
   - conformance test suite (신규 memory plug-in 인증 기준)
   - 기존 kv_offload backend(LocalCPUBackend/LocalDiskBackend)의 adapter wrapping 방안
   - `Evaluation/DP1/sim`: `memories_default.json`을 MemoryDescriptor로 로드하는 adapter 추가, ScHBM 항목 추가 시 policy 코드 무변경 검증 (test_sim.py)
   - shared_link_group 단위 migration budget 모델링
12. **MigrationAction 정렬 및 상세**
   - ~~공통 migration architecture의 `MigrationIntent`에 `action` field 추가~~ → 반영 완료 (공통 문서 §1.1, §7.1, §23.1)
   - `DROP` 허용 조건(replica / recomputable)을 C1/C2 Registry schema에 반영
   - `REPLICATE` replica 수명/일관성 정책, `REMAP` 적용 가능 memory(CXL shared pool 등) 정의
   - `Evaluation/DP1/sim`에 `DROP` 반영 완료 (`run_eval.py --drop-study`, replica는 외부 write-through로 생성, 비용 미청구).
     예비 결과(replica 50%, KV 시나리오, 3 seed×3 load): DROP이 발생한 run은 C1 21/135, C2 42/135이며, 발생 시 migration GiB 중앙값 감소 C1 −42 / C2 −178 (전체 migration의 약 1%). latency는 중앙값 변화 없음, 일부 run에서 tail 악화(DROP target이 정책 선호 tier와 다름). 즉 효과는 작고, replica 용량 점유가 dynamics를 바꾸므로 `drop_on` vs `drop_off` 비교만 action 효과로 해석해야 한다.
14. **평가 loop 결과 반영 (2026-10-02, `Evaluation/DP1/results/2026-10-02_dp1-qa-evaluation.md`)**
   - Destination Tier Selector serving-cost 입력 (§8.7, §13.6), link-time migration budget, C2 benefit-vs-cost gating, C1 promotion 경로(§17.2)를 설계 항목으로 확정한다.
   - 확인된 사실: 이득은 static 배치가 stale해지는 dynamic 조건에서만 확인(C2 6/6, C1 3/6 시나리오), 그 외는 Baseline과 parity. 이 simulator의 cost 추정은 오차 0이므로 [A] 실측 기반 보정 후 재평가가 필요하다.
13. **Transfer Handler 설계 (§5.9)**
   - staged 합성(export/import) 기본 경로 + direct override 등록 규약
   - chunk pipelining 크기, bounce buffer budget, traffic class별 rate limit
   - 실측 BW/latency 보고 → estimate 보정 loop 정의
   - `Evaluation/DP1/sim`: multi-hop 전송 시간, 공유 링크 contention, write-limited 매체 비용 모델 반영 여부 검토

---

# 27. References

- **doc-mk/vllm-ai-data-migration-architecture.md**
- **doc-mk/vllm-call-path-analysis.md**
- **doc-mk/vllm-kv-cache-memory-abstraction-layer.md**
- **doc-mk/vllm-kv-cache-memory-tiering.md**
