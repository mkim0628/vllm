# vLLM Heterogeneous-Memory AI Data Migration — Architecture Design

> 기준 브랜치: claude/vllm-call-path-analysis-qxulkr  
> 기준 문서: doc-mk/vllm-cost-model-prefill-placement-architecture.md, doc-mk/vllm-call-path-analysis.md, doc-mk/vllm-kv-cache-memory-abstraction-layer.md, doc-mk/vllm-kv-cache-memory-tiering.md  
> 설계 범위: **HBM / DRAM / CXL Memory / Custom HBM / SSD 등 이기종 메모리 사이에서 AI data를 안전하게 이동시키는 runtime 구조를 vLLM V1 위에 구현**
>
> 이 문서는 migration policy 후보 비교가 아니라, **migration decision이 이미 내려졌다고 가정했을 때 그 결정을 실제 data movement로 변환하고, vLLM의 logical data state와 physical memory state를 일관되게 유지하는 구조**를 정의한다.
>
> 1차 구현 대상은 KV cache block이다. 다만 migration core는 KV 전용으로 고정하지 않고, 향후 model weight / LoRA / prefix data / activation 등으로 확장할 수 있도록 AI Data Adapter 경계를 둔다.

---

# 0. 현재 vLLM에서 삽입해야 할 위치

현재 V1의 핵심 실행 경로는 다음과 같다.

~~~text
EngineCore.step()
    │
    ├─ Scheduler.schedule()
    │      ├─ KVCacheManager.allocate_slots()
    │      └─ SchedulerOutput
    │
    ├─ Executor.execute_model(SchedulerOutput)
    │
    └─ Scheduler.update_from_output()
             │
             ▼
Worker.execute_model()
    │
    ▼
GPUModelRunner.execute_model()
    │
    ▼
model.forward()
~~~

현재 branch에는 KV data를 외부 medium으로 load/store하기 위한 실험적 offloading 인프라가 이미 존재한다.

~~~text
Scheduler side
  OffloadingManager
    ├─ lookup()
    ├─ prepare_load()
    ├─ complete_load()
    ├─ prepare_store()
    └─ complete_store()

Worker side
  OffloadingWorker
    ├─ register_handler(src_spec, dst_spec)
    ├─ transfer_async()
    └─ get_finished()

Transfer
  TransferSpec = (src LoadStoreSpec, dst LoadStoreSpec)
~~~

이 구조는 migration architecture의 좋은 출발점이다. 특히 다음 두 책임 분리가 이미 존재한다.

1. **Scheduler/EngineCore 측은 logical state와 transfer intent를 관리**
2. **Worker 측은 실제 asynchronous copy를 수행**

다만 heterogeneous-memory migration을 일반화하려면 기존 offloading보다 추가로 다음이 필요하다.

1. **AI Data Identity** — physical block id가 아니라 이동 전후에도 유지되는 logical object identity
2. **Location Metadata** — source / destination / replica / authoritative location / in-flight state
3. **Migration Planning** — direct copy인지 multi-hop staged copy인지, 어떤 path를 사용할지
4. **Consistency / Atomic Commit** — copy 중 source가 계속 유효하고, 성공 후에만 location을 전환
5. **Migration Scheduling** — foreground promotion과 background demotion을 구분하고 bandwidth를 조절
6. **Execution Dependency** — forward 전에 반드시 완료되어야 하는 migration과 background migration을 구분
7. **Data-Type Adapter** — KV cache 외 AI data도 같은 migration core를 사용할 수 있도록 logical data model 분리

핵심 원칙은 다음과 같다.

> **Policy decides WHAT and WHERE. Migration subsystem decides HOW, WHEN, and COMMIT.**

즉 migration policy는 다음 정도의 의사결정을 만든다.

~~~text
Migrate KV block B
  source = CXL0
  target = HBM0
  reason = hot-data promotion
~~~

Migration subsystem은 이를 다음 실행 계획으로 바꾼다.

~~~text
reserve target
  ↓
pin source
  ↓
select transfer path
  ↓
copy
  ↓
verify completion
  ↓
atomic location commit
  ↓
release old source
~~~

---

# 1. Architectural Drivers

## 1.1 Functional Requirements

Migration subsystem은 최소한 다음 기능을 제공해야 한다.

### Migration input

~~~text
MigrationIntent
 ├─ data_objects[]
 ├─ source_resource_id
 ├─ target_resource_id
 ├─ reason
 ├─ priority
 ├─ deadline / execution_dependency
 └─ policy_metadata
~~~

Migration decision의 생성 주체는 이 문서의 핵심 범위가 아니다. 다음 모두 가능하다.

- memory pressure 기반 demotion policy
- access frequency 기반 promotion policy
- cost-model-based placement 결과
- prefetch predictor
- explicit operator request
- failure / maintenance evacuation

### Migration output

~~~text
MigrationResult
 ├─ job_id
 ├─ migrated_objects[]
 ├─ final_locations[]
 ├─ bytes_transferred
 ├─ transfer_path
 ├─ queue_delay
 ├─ transfer_latency
 ├─ status
 └─ failure_reason
~~~

### Required behavior

- source와 target memory resource를 식별
- target capacity reservation
- direct / staged / multi-hop transfer path 선택
- asynchronous copy dispatch
- foreground / background 우선순위 처리
- copy completion 추적
- data version / mutability 검증
- successful copy 이후 location metadata atomic commit
- commit 이후 source free 또는 replica 유지
- failure 시 rollback
- transfer statistics 수집

## 1.2 Quality Attributes

- **Correctness**: migration 중에도 실행 중인 request가 stale / partially copied data를 참조하면 안 됨.
- **Low Stall**: background migration은 model execution을 불필요하게 block하지 않아야 함.
- **Bounded Foreground Latency**: promotion이 critical path에 들어갈 경우 queue delay가 무제한 증가하면 안 됨.
- **Transfer-path Extensibility**: HBM↔DRAM, HBM↔CXL, HBM↔Custom HBM, DRAM↔SSD 등 추가 시 coordinator 수정 최소화.
- **Data-type Extensibility**: KV-specific state machine이 migration core에 섞이지 않아야 함.
- **Observability**: 어떤 data가 왜, 어디서 어디로, 얼마나 오래 걸려 이동했는지 추적 가능해야 함.
- **Failure Safety**: target write 실패 시 source를 authoritative copy로 유지.
- **No Thrashing Amplification**: migration scheduler가 짧은 시간에 같은 object를 왕복 이동시키지 않도록 cooldown/budget 제공.
- **Execution Consistency**: scheduler가 보는 data location과 worker가 실제 접근하는 physical location이 어긋나지 않아야 함.

---

# 2. Architectural Boundary

Migration architecture를 세 개의 역할로 분리한다.

~~~text
Decision Plane
  "무엇을 / 어디로 옮길 것인가?"
        │
        │ MigrationIntent
        ▼
Migration Control Plane
  "어떻게 옮기며, 언제 commit할 것인가?"
        │
        │ MigrationCommand
        ▼
Transfer Data Plane
  "실제 bytes를 복사한다"
~~~

이 세 역할을 섞지 않는 것이 가장 중요하다.

## 2.1 Decision Plane

다음 컴포넌트가 MigrationIntent를 만들 수 있다.

- PlacementManager
- MemoryPressurePolicy
- DataBehaviorPolicy
- PrefetchPredictor
- FailureRecoveryManager

Migration subsystem은 이 정책들을 직접 구현하지 않는다.

## 2.2 Migration Control Plane

EngineCore 쪽에 위치하며 다음을 담당한다.

- logical data/location state
- migration job lifecycle
- target reservation
- path planning
- migration ordering
- foreground/background priority
- copy completion commit
- failure rollback

## 2.3 Transfer Data Plane

Worker/device 쪽에 위치하며 다음을 담당한다.

- DMA / memcpy / vendor API 호출
- stream/event management
- direct P2P
- staged transfer
- chunked copy
- completion notification

---

# 3. Layered Architecture

~~~mermaid
graph TB
    subgraph L1["L1. Serving / Request Layer — 기존"]
        API["OpenAI API / LLM"]
        ASYNC["AsyncLLM / LLMEngine"]
    end

    subgraph L2["L2. Engine & Scheduling Layer — 기존 + 확장"]
        CORE["EngineCore"]
        SCHED["Scheduler"]
        KVM["KVCacheManager"]
        POLICY["Placement / Migration Policy<br/>outside migration core"]
    end

    subgraph L3["L3. AI Data Migration Control Plane — 신규"]
        MC["MigrationCoordinator"]
        MP["MigrationPlanner"]
        MQ["MigrationScheduler / Queue"]
        MS["MigrationStateStore"]
        CG["MigrationConsistencyGuard"]
        CR["CompletionReconciler"]
    end

    subgraph L4["L4. Data & Resource Intelligence Layer — 신규/확장"]
        ADR["AIDataRegistry"]
        DLS["DataLocationStore"]
        ADAPTER["AIDataAdapter Registry"]
        MREG["MemoryResourceRegistry"]
        TOPO["MemoryTopology"]
        TEL["Memory / Transfer Telemetry"]
    end

    subgraph L5["L5. Transfer Data Plane — 기존 offload 확장"]
        EXEC["MigrationExecutor"]
        TR["TransferRouter"]
        HR["TransferHandlerRegistry"]
        OFFW["OffloadingWorker adapter"]
        H1["HBM↔HBM Handler"]
        H2["HBM↔DRAM Handler"]
        H3["HBM↔CXL Handler"]
        H4["DRAM/CXL↔SSD Handler"]
    end

    subgraph L6["L6. Memory / Hardware Layer"]
        HBM["GPU HBM"]
        DRAM["Host DRAM"]
        CXL["CXL Memory"]
        CHBM["Custom HBM / HBF"]
        SSD["NVMe SSD"]
    end

    API --> ASYNC --> CORE
    CORE --> SCHED
    SCHED --> KVM
    POLICY --> MC
    SCHED --> MC

    MC --> MP
    MC --> MQ
    MC --> MS
    MC --> CG
    MC --> CR

    MP --> ADR
    MP --> DLS
    MP --> MREG
    MP --> TOPO
    MC --> ADAPTER
    TEL --> MS

    MQ --> EXEC
    EXEC --> TR
    TR --> HR
    HR --> OFFW
    HR --> H1
    HR --> H2
    HR --> H3
    HR --> H4

    H1 --> HBM
    H2 --> HBM
    H2 --> DRAM
    H3 --> HBM
    H3 --> CXL
    H3 --> CHBM
    H4 --> DRAM
    H4 --> CXL
    H4 --> SSD

    classDef new fill:#d8f5d0,stroke:#2f9e44,color:#1b4332,stroke-width:2px;
    classDef modified fill:#fff3bf,stroke:#f08c00,color:#5c3c00,stroke-width:2px;
    classDef existing fill:#eef1f4,stroke:#8d99ae,color:#22303e,stroke-width:1px;

    class MC,MP,MQ,MS,CG,CR,ADR,DLS,ADAPTER,MREG,TOPO,TEL,EXEC,TR,HR,H1,H2,H3,H4 new;
    class SCHED,KVM,OFFW modified;
    class API,ASYNC,CORE,HBM,DRAM,CXL,CHBM,SSD existing;
~~~

### Layer 책임

| Layer | 책임 | Migration 관점 |
|---|---|---|
| Serving/API | request ingress/egress | migration을 모름 |
| Engine/Scheduling | request/token scheduling, KV lifecycle | migration trigger 또는 execution dependency 생성 |
| Migration Control Plane | plan / queue / lifecycle / commit | **migration의 중심 제어부** |
| Data & Resource Intelligence | data identity, location, memory/topology/state | control plane에 표준 정보 제공 |
| Transfer Data Plane | 실제 bytes 이동 | decision을 재해석하지 않고 command 실행 |
| Hardware | 실제 memory/fabric | handler 뒤에 숨김 |

---

# 4. Module View

기존 vLLM 구조를 최대한 유지하면서 신규 코드는 vllm/v1/data_migration 아래에 모은다.

~~~text
vllm/
└── v1/
    ├── engine/
    │   └── core.py                              # modified: subsystem lifecycle
    │
    ├── core/
    │   ├── sched/
    │   │   ├── scheduler.py                     # modified: migration trigger/dependency
    │   │   └── output.py                        # modified: migration_commands/dependencies
    │   │
    │   ├── kv_cache_manager.py                  # modified through KV adapter hooks
    │   └── block_pool.py                        # minimal pin/eviction cooperation
    │
    ├── data_migration/                          # NEW
    │   ├── coordinator.py                       # MigrationCoordinator
    │   ├── planner.py                           # MigrationPlanner
    │   ├── scheduler.py                         # MigrationScheduler / priority queue
    │   ├── state.py                             # MigrationStateStore / job state
    │   ├── consistency.py                       # pin/version/commit guard
    │   ├── completion.py                        # CompletionReconciler
    │   ├── types.py                             # intents/plans/jobs/results
    │   │
    │   ├── data/
    │   │   ├── base.py                          # AIDataAdapter interface
    │   │   ├── registry.py                      # AIDataRegistry
    │   │   ├── location.py                      # DataLocationStore
    │   │   └── kv_cache.py                      # KVDataAdapter
    │   │
    │   ├── resource/
    │   │   ├── registry.py                      # MemoryResourceRegistry
    │   │   ├── topology.py                      # MemoryTopology
    │   │   └── telemetry.py                     # memory/transfer telemetry
    │   │
    │   └── worker/
    │       ├── executor.py                      # MigrationExecutor
    │       ├── router.py                        # TransferRouter
    │       ├── registry.py                      # TransferHandlerRegistry
    │       └── handlers/
    │           ├── cuda_p2p.py
    │           ├── host_dma.py
    │           ├── cxl.py
    │           └── nvme.py
    │
    ├── kv_offload/
    │   ├── base.py                              # existing, Phase 1 reuse
    │   └── worker/worker.py                     # existing async transfer engine reuse
    │
    └── worker/
        ├── gpu_worker.py                        # modified: migration data-plane lifecycle
        └── gpu_model_runner.py                  # minimal dependency wait hook
~~~

~~~mermaid
graph TD
    CORE["vllm.v1.engine.core"]
    SCHED["vllm.v1.core.sched"]
    KVC["vllm.v1.core.kv_cache_manager"]
    MIG["vllm.v1.data_migration"]
    DATA["vllm.v1.data_migration.data"]
    RES["vllm.v1.data_migration.resource"]
    MW["vllm.v1.data_migration.worker"]
    OFF["vllm.v1.kv_offload"]
    WORK["vllm.v1.worker"]
    ATTN["vllm.v1.attention"]

    CORE --> SCHED
    CORE --> MIG
    SCHED --> KVC
    SCHED --> MIG

    MIG --> DATA
    MIG --> RES
    MIG --> MW

    DATA --> KVC
    MW --> OFF
    MW --> WORK
    WORK --> ATTN

    classDef new fill:#d8f5d0,stroke:#2f9e44,color:#1b4332,stroke-width:2px;
    class MIG,DATA,RES,MW new;
~~~

### 의존성 규칙

1. Scheduler는 구체적인 DMA/CXL/NVMe handler를 import하지 않는다.
2. Migration policy는 TransferHandler를 직접 호출하지 않는다.
3. Worker는 migration target을 다시 선택하지 않는다.
4. DataLocationStore는 physical copy 성공 전 authoritative location을 변경하지 않는다.
5. AIDataAdapter만 KV-specific block semantics를 안다.
6. Transfer handler는 KV/request semantics를 모른다.
7. MemoryTopology와 MemoryResourceRegistry는 data type을 모른다.
8. 기존 kv_offload는 Phase 1에서 low-level transfer primitive로 재사용 가능하지만, generic location/commit semantics는 data_migration layer가 소유한다.

---

# 5. Core Domain Model / Class Diagram

~~~mermaid
classDiagram
    class MigrationIntent {
        +intent_id
        +data_refs
        +source_resource_id
        +target_resource_id
        +reason
        +priority
        +deadline
        +dependency_type
    }

    class MigrationCoordinator {
        -MigrationPlanner planner
        -MigrationScheduler scheduler
        -MigrationStateStore state_store
        -MigrationConsistencyGuard guard
        -CompletionReconciler reconciler
        +submit(intent) MigrationHandle
        +poll()
        +cancel(handle)
    }

    class MigrationPlanner {
        +build_plan(intent, snapshot) MigrationPlan
        +revalidate(plan, snapshot) bool
    }

    class MigrationPlan {
        +job_id
        +objects
        +source_locations
        +target_allocations
        +transfer_steps
        +consistency_mode
        +commit_actions
        +cleanup_actions
    }

    class MigrationScheduler {
        +enqueue(plan)
        +next_ready_jobs()
        +reserve_bandwidth(job)
        +complete(job)
    }

    class MigrationJob {
        +job_id
        +state
        +priority
        +dependency_type
        +created_at
        +started_at
        +completed_at
    }

    class MigrationState {
        <<enumeration>>
        PENDING
        PREPARING
        COPYING
        VERIFYING
        COMMITTING
        COMPLETED
        FAILED
        CANCELLED
    }

    class AIDataRef {
        +object_id
        +data_type
        +logical_range
        +version
    }

    class AIDataDescriptor {
        +size_bytes
        +mutability
        +owner
        +alignment
        +transfer_constraints
    }

    class AIDataAdapter {
        <<interface>>
        +describe(data_ref) AIDataDescriptor
        +pin(data_ref)
        +unpin(data_ref)
        +build_source_spec(data_ref, location)
        +commit_location(data_ref, new_location)
        +can_migrate_now(data_ref) bool
    }

    class KVDataAdapter {
        +map_block_ids()
        +check_sealed_block()
        +pin_against_eviction()
        +update_kv_location()
    }

    class DataLocationStore {
        +get(data_ref) LocationRecord
        +begin_migration(data_ref, job_id)
        +commit(data_ref, location, version)
        +abort(data_ref, job_id)
    }

    class LocationRecord {
        +authoritative_location
        +replicas
        +version
        +inflight_job
    }

    class MemoryResourceRegistry {
        +get(resource_id)
        +reserve(resource_id, bytes)
        +release(allocation)
    }

    class MemoryTopology {
        +find_paths(src, dst)
        +select_path(src, dst, constraints)
    }

    class TransferStep {
        +src_spec
        +dst_spec
        +bytes
        +path_segment
        +ordering
    }

    class MigrationExecutor {
        +submit(job, transfer_steps)
        +poll_completions()
    }

    class TransferRouter {
        +route(step) TransferHandler
    }

    class TransferHandler {
        <<interface>>
        +supports(src, dst)
        +transfer_async(step) TransferHandle
        +poll(handle)
    }

    class CompletionReconciler {
        +on_copy_complete(job, result)
        +commit(job)
        +rollback(job)
    }

    MigrationCoordinator --> MigrationPlanner
    MigrationCoordinator --> MigrationScheduler
    MigrationCoordinator --> MigrationStateStore
    MigrationCoordinator --> MigrationConsistencyGuard
    MigrationCoordinator --> CompletionReconciler

    MigrationPlanner --> MigrationIntent
    MigrationPlanner --> MigrationPlan
    MigrationPlan --> TransferStep
    MigrationScheduler --> MigrationJob
    MigrationJob --> MigrationState

    MigrationIntent --> AIDataRef
    AIDataAdapter --> AIDataDescriptor
    KVDataAdapter --|> AIDataAdapter
    AIDataAdapter --> DataLocationStore
    DataLocationStore --> LocationRecord

    MigrationPlanner --> MemoryResourceRegistry
    MigrationPlanner --> MemoryTopology

    MigrationCoordinator --> MigrationExecutor
    MigrationExecutor --> TransferRouter
    TransferRouter --> TransferHandler
~~~

---

# 6. AI Data Abstraction

Migration engine이 KV block id에 직접 의존하면 weight / LoRA / activation 지원 시 구조를 다시 만들어야 한다.

따라서 logical identity와 physical location을 분리한다.

~~~text
AIDataRef
   │ logical identity
   ▼
AIDataRegistry / Adapter
   │
   ├─ descriptor
   ├─ current location
   ├─ version
   └─ physical storage spec
~~~

## 6.1 Data type examples

| Data Type | 1차 지원 | Mutability | Migration 특성 |
|---|---:|---|---|
| KV cache sealed block | Yes | immutable | 가장 안전한 migration 대상 |
| KV cache active tail block | Limited | mutable | write barrier/pin 필요 |
| Model weight | Future | read-only | large, long-lived, replica-friendly |
| LoRA adapter weight | Future | read-only | smaller, request-dependent |
| Prefix cache object | Through KV | immutable | reuse-aware migration 가능 |
| Activation | Future | short-lived mutable | strict synchronization 필요 |

## 6.2 KV block은 왜 first-class adapter가 필요한가?

KV cache block은 단순 byte buffer가 아니다.

- Scheduler의 BlockPool과 lifecycle이 연결되어 있음
- prefix caching hash와 연결될 수 있음
- request가 참조 중이면 eviction/free 불가
- active tail block은 write 중일 수 있음
- Worker에서 block id가 실제 KV tensor offset으로 해석됨

따라서 KV-specific logic은 KVDataAdapter에 둔다.

~~~text
Migration Core
    │
    │ generic AIDataRef
    ▼
KVDataAdapter
    ├─ KVCacheManager / BlockPool lookup
    ├─ block pin
    ├─ sealed / mutable validation
    ├─ source/destination spec generation
    └─ logical location commit
~~~

---

# 7. Migration State Machine

Migration correctness의 핵심은 **copy와 location commit을 분리**하는 것이다.

~~~mermaid
stateDiagram-v2
    [*] --> PENDING
    PENDING --> PREPARING: dequeue
    PREPARING --> COPYING: reserve target + pin source
    PREPARING --> FAILED: validation/reservation fail

    COPYING --> VERIFYING: all transfer steps done
    COPYING --> FAILED: transfer failure

    VERIFYING --> COMMITTING: version/source still valid
    VERIFYING --> FAILED: stale / mismatch

    COMMITTING --> COMPLETED: atomic location commit + source release
    COMMITTING --> FAILED: commit failure

    PENDING --> CANCELLED: cancelled before start
    PREPARING --> CANCELLED: safe cancel
    FAILED --> [*]
    CANCELLED --> [*]
    COMPLETED --> [*]
~~~

### 중요한 규칙

~~~text
잘못된 순서
location = target
copy source -> target

권장 순서
reserve target
pin source
copy source -> target
verify
atomic location = target
free/unpin source
~~~

copy가 끝나기 전 source는 authoritative location이다.

---

# 8. Migration Planning View

MigrationPlanner는 target을 선택하는 policy가 아니다.

이미 주어진 source/target을 바탕으로 **실행 가능한 copy plan**을 만든다.

~~~mermaid
flowchart LR
    INT["MigrationIntent<br/>CXL0 → HBM0"]
    LOC["Current Data Location"]
    MEM["Memory Resource Capability"]
    TOP["Memory Topology"]
    DESC["AI Data Descriptor"]

    PLAN["MigrationPlanner"]

    OUT["MigrationPlan<br/>reservation<br/>path<br/>chunks<br/>sync mode<br/>commit/cleanup"]

    INT --> PLAN
    LOC --> PLAN
    MEM --> PLAN
    TOP --> PLAN
    DESC --> PLAN
    PLAN --> OUT
~~~

## 8.1 Direct path

~~~text
HBM0
  │ GPU P2P / DMA
  ▼
HBM1
~~~

## 8.2 Staged path

~~~text
HBM0
  │ D2H
  ▼
Pinned DRAM
  │ host/CXL copy
  ▼
CXL Memory
~~~

## 8.3 Multi-hop plan

~~~text
TransferStep[0] HBM0 -> Pinned DRAM
TransferStep[1] Pinned DRAM -> CXL0
Commit        authoritative_location = CXL0
Cleanup       free temporary staging
~~~

MemoryTopology는 path를 제공하고 MigrationPlanner가 data constraints와 target reservation을 결합한다.

---

# 9. Migration Scheduling View

모든 migration이 같은 urgency를 갖지 않는다.

두 종류를 최소한 분리해야 한다.

## 9.1 Foreground migration

현재 또는 다음 model execution이 target data를 필요로 한다.

예:

- CXL의 hot KV를 HBM으로 promotion
- prefill placement가 선택한 memory로 required KV 이동
- request resume 전에 offloaded KV restore

~~~text
Priority: high
Execution dependency: BLOCKING
Goal: forward 전에 완료
~~~

## 9.2 Background migration

현재 model execution의 즉시 dependency가 아니다.

예:

- HBM pressure 해소를 위한 cold KV demotion
- proactive rebalance
- SSD archival
- replica creation

~~~text
Priority: low
Execution dependency: NON_BLOCKING
Goal: compute와 overlap
~~~

~~~mermaid
graph TD
    IN["MigrationIntent"]
    CLASS["Classify dependency"]

    FG["Foreground Queue<br/>deadline / request critical"]
    BG["Background Queue<br/>bandwidth budgeted"]

    ARB["MigrationScheduler<br/>bandwidth + concurrency arbiter"]
    EXEC["MigrationExecutor"]

    IN --> CLASS
    CLASS --> FG
    CLASS --> BG
    FG --> ARB
    BG --> ARB
    ARB --> EXEC
~~~

### Scheduler 기본 규칙

- foreground는 background보다 우선
- background는 per-link bandwidth budget을 넘지 않음
- 동일 object에 중복 migration job 금지
- source/target pair별 max in-flight 제한
- 최근 migration된 object에는 cooldown 적용 가능
- target free-space watermark 이하에서는 low-priority promotion 제한 가능

---

# 10. Component View — Runtime Process Boundary

vLLM의 현재 process 구조를 유지한다.

**Migration control plane은 EngineCore**, 실제 transfer는 **Worker/device process**에 둔다.

~~~mermaid
graph LR
    CLIENT["HTTP Client"]

    subgraph P1["Process: API Server — 기존"]
        API["FastAPI"]
        ALLM["AsyncLLM"]
        ECC["AsyncMPClient"]
    end

    subgraph P2["Process: EngineCore — migration control plane"]
        EC["EngineCore"]
        SCH["Scheduler"]
        KVM["KVCacheManager"]
        POL["Placement / Migration Policy"]
        MC["MigrationCoordinator"]
        MP["MigrationPlanner"]
        MQ["MigrationScheduler"]
        LS["DataLocationStore"]
        TOPO["MemoryTopology"]
        REC["CompletionReconciler"]
    end

    subgraph P3["Worker Process 0"]
        W0["GPU Worker 0"]
        ME0["MigrationExecutor"]
        TR0["TransferRouter"]
        OH0["OffloadingWorker Adapter"]
        MR0["GPU0 HBM / Host / CXL handles"]
    end

    subgraph P4["Worker Process 1"]
        W1["GPU Worker 1"]
        ME1["MigrationExecutor"]
        TR1["TransferRouter"]
        OH1["OffloadingWorker Adapter"]
        MR1["GPU1 HBM / Host / CXL handles"]
    end

    CLIENT --> API --> ALLM --> ECC
    ECC --> EC
    EC --> SCH
    SCH --> KVM
    POL --> MC
    SCH --> MC

    MC --> MP
    MC --> MQ
    MC --> LS
    MP --> TOPO

    MQ -- "MigrationCommandBatch" --> ME0
    MQ -- "MigrationCommandBatch" --> ME1

    ME0 --> TR0 --> OH0 --> MR0
    ME1 --> TR1 --> OH1 --> MR1

    ME0 -. "MigrationCompletion" .-> REC
    ME1 -. "MigrationCompletion" .-> REC
    REC --> LS

    classDef new fill:#d8f5d0,stroke:#2f9e44,color:#1b4332,stroke-width:2px;
    class MC,MP,MQ,LS,TOPO,REC,ME0,ME1,TR0,TR1 new;
~~~

### 왜 coordinator를 Worker 안에 두지 않는가?

여러 memory resource 사이 이동을 안전하게 관리하려면 다음 전역 정보가 필요하다.

- logical data owner
- source / target location
- request reference state
- duplicate migration 여부
- foreground/background priority
- global memory pressure
- migration history

각 Worker가 독립적으로 decision/commit을 하면 동일 object에 대해 충돌하는 migration을 만들 수 있다.

따라서 Worker는 **copy executor**, EngineCore는 **logical migration authority**로 둔다.

---

# 11. SchedulerOutput Integration

기존 SchedulerOutput은 request 실행 정보와 KV connector metadata를 Worker에 전달한다.

Migration도 같은 step boundary를 이용하되 model execution metadata와 분리한다.

개념적 확장:

~~~text
SchedulerOutput
 ├─ scheduled_new_reqs
 ├─ scheduled_cached_reqs
 ├─ num_scheduled_tokens
 ├─ kv_connector_metadata
 ├─ ...
 ├─ migration_commands
 └─ migration_dependencies
~~~

### migration_commands

이번 step에서 worker가 시작할 수 있는 transfer command.

~~~text
MigrationCommand
 ├─ job_id
 ├─ transfer_steps[]
 ├─ source_specs[]
 ├─ destination_specs[]
 └─ priority
~~~

### migration_dependencies

이번 model execution이 어떤 migration completion을 기다려야 하는지 표현한다.

~~~text
MigrationDependency
 ├─ request_id
 ├─ job_ids[]
 └─ wait_before = MODEL_FORWARD | ATTENTION | NONE
~~~

가능하면 처음 구현은 **MODEL_FORWARD 이전 barrier**로 단순화하고, 이후 layer-wise/attention-wise overlap을 추가한다.

---

# 12. Main Sequence — Background Demotion

예: HBM pressure 때문에 sealed KV block을 HBM에서 CXL로 내리는 경우.

~~~mermaid
sequenceDiagram
    participant POL as Migration Policy
    participant MC as MigrationCoordinator
    participant KV as KVDataAdapter
    participant LS as DataLocationStore
    participant MP as MigrationPlanner
    participant MR as MemoryResourceRegistry
    participant MQ as MigrationScheduler
    participant EX as MigrationExecutor
    participant SRC as HBM
    participant DST as CXL
    participant REC as CompletionReconciler

    POL->>MC: submit(MigrationIntent B1, HBM->CXL, background)

    MC->>KV: can_migrate_now(B1)?
    KV-->>MC: yes, sealed block

    MC->>LS: get(B1)
    LS-->>MC: authoritative = HBM, version = V7

    MC->>MP: build_plan(intent, location)
    MP->>MR: reserve(CXL, size)
    MR-->>MP: target allocation
    MP-->>MC: MigrationPlan

    MC->>KV: pin(B1)
    MC->>LS: begin_migration(B1, job)

    MC->>MQ: enqueue(plan)
    MQ->>EX: dispatch MigrationCommand

    EX->>SRC: async read
    EX->>DST: async write
    DST-->>EX: completion

    EX-->>REC: MigrationCompletion(success)

    REC->>LS: validate source/version still HBM/V7
    LS-->>REC: valid

    REC->>LS: atomic commit(B1 -> CXL, V8)
    REC->>KV: release old HBM block / unpin

    Note over LS: copy가 성공한 뒤에만<br/>authoritative location 변경
~~~

background demotion 중 request가 기존 HBM block을 읽는 것은 허용된다. source는 commit 전까지 유효하기 때문이다.

---

# 13. Main Sequence — Foreground Promotion Before Forward

예: Scheduler가 다음 step에서 CXL의 KV를 사용해야 하며 HBM materialization이 필요한 경우.

~~~mermaid
sequenceDiagram
    participant S as Scheduler
    participant MC as MigrationCoordinator
    participant KV as KVDataAdapter
    participant MP as MigrationPlanner
    participant MQ as MigrationScheduler
    participant SO as SchedulerOutput
    participant W as Worker
    participant EX as MigrationExecutor
    participant MR as GPUModelRunner

    S->>KV: required KV locations for scheduled requests
    KV-->>S: B1 located on CXL

    S->>MC: submit promotion(B1, CXL->HBM, BLOCKING)
    MC->>MP: build_plan()
    MP-->>MC: plan
    MC->>MQ: enqueue high priority

    MC-->>S: MigrationHandle(job=42)
    S->>SO: add migration command + dependency(job=42)

    S-->>W: execute_model(SchedulerOutput)

    W->>EX: launch migration job 42
    EX-->>W: async handle

    W->>W: wait required migration dependency
    EX-->>W: job 42 complete

    W->>MR: execute_model()
    Note over MR: forward 진입 시점에는<br/>required KV가 HBM에 존재

    MR-->>W: model output
~~~

Phase 1에서는 forward 전체 앞에서 wait한다.

고급 구현에서는 다음처럼 overlap 범위를 줄일 수 있다.

~~~text
launch transfer
  ↓
prepare inputs / metadata
  ↓
wait only before first layer that needs migrated KV
  ↓
attention
~~~

하지만 이 경우 backend/layer dependency가 migration engine에 더 많이 노출되므로 별도 최적화 단계로 둔다.

---

# 14. Mutable Data / Consistency Rules

## 14.1 Sealed KV block

가장 안전한 migration 대상이다.

~~~text
KV block full
   ↓
no more writes
   ↓
pin against eviction
   ↓
copy safely
~~~

1차 구현은 sealed KV block 중심으로 제한하는 것이 좋다.

## 14.2 Active tail KV block

현재 decode/prefill이 write 중일 수 있다.

가능한 전략:

~~~text
A. migration defer
   active tail은 migrate하지 않음

B. write barrier
   current step completion 후 freeze → migrate

C. copy + delta synchronization
   initial copy 후 dirty region replay
~~~

Phase 1은 A 또는 B를 사용한다.

## 14.3 Version validation

copy 시작 시 version을 기록한다.

~~~text
source version = V7
copy
verify current version == V7
  ├─ yes -> commit target as V8
  └─ no  -> abort / recopy
~~~

이 검증으로 migration 도중 data가 변경된 경우 stale target commit을 막는다.

---

# 15. KV Cache Integration View

KV cache migration에서 가장 중요한 점은 **logical block identity를 유지하면서 physical memory location만 바꾸는 것**이다.

~~~mermaid
graph TD
    S["Scheduler"]
    KVM["KVCacheManager"]
    BP["BlockPool"]
    KVA["KVDataAdapter"]
    LOC["DataLocationStore"]
    MC["MigrationCoordinator"]
    WBT["Worker Block Mapping"]
    MEM["HBM / CXL / DRAM"]

    S --> KVM
    KVM --> BP
    KVM --> KVA

    KVA --> LOC
    KVA --> MC

    MC --> WBT
    WBT --> MEM
~~~

### 권장 identity model

~~~text
Logical KV Block ID = stable identity

PhysicalLocation
 ├─ memory_resource_id
 ├─ local_allocation_id
 ├─ offset
 └─ generation/version
~~~

logical block id 자체를 HBM-local address처럼 해석하지 않는다.

이 separation이 되어야 같은 B1이 다음처럼 이동 가능하다.

~~~text
B1
 ├─ t0: HBM0 block 120
 ├─ t1: CXL0 allocation 9921
 └─ t2: HBM1 block 88
~~~

상위 Scheduler는 B1이라는 logical identity를 유지한다.

---

# 16. Reuse of Existing vLLM Offloading Infrastructure

현재 branch의 kv_offload는 migration data plane의 상당 부분을 재사용할 수 있다.

## 16.1 재사용 가능한 부분

### Scheduler-side pattern

OffloadingManager가 이미 다음 lifecycle을 갖는다.

~~~text
prepare
  ↓
transfer
  ↓
complete
~~~

이 pattern은 generic migration의 prepare / copy / commit lifecycle과 잘 맞는다.

### Worker-side pattern

OffloadingWorker는 src/dst medium pair에 따라 handler를 dispatch한다.

~~~text
(src medium, dst medium)
      ↓
TransferHandler
      ↓
transfer_async()
~~~

이는 TransferRouter / TransferHandlerRegistry의 초기 구현으로 재사용할 수 있다.

### LoadStoreSpec

기존 LoadStoreSpec은 source/destination storage 위치를 opaque metadata로 넘기는 역할을 한다.

이를 Phase 1에서 TransferStep의 source_spec / destination_spec으로 그대로 사용할 수 있다.

## 16.2 그대로 재사용하면 부족한 부분

현재 offloading abstraction은 주로 **KV cache store/load** semantics다.

generic migration에는 추가로 다음이 필요하다.

- object-level logical identity
- authoritative location
- same object의 replica state
- target reservation
- direct memory-to-memory migration
- source pin
- atomic location commit
- migration priority / bandwidth budget
- multi-hop path
- version validation
- generic AI data adapter

따라서 권장 방향은 **kv_offload를 제거하는 것이 아니라, low-level transfer primitive로 감싸서 data_migration control plane 아래에서 재사용**하는 것이다.

~~~text
MigrationCoordinator
      ↓
MigrationExecutor
      ↓
TransferRouter
      ↓
Existing OffloadingWorker / Handler
~~~

---

# 17. Transfer Handler Architecture

~~~mermaid
classDiagram
    class TransferHandlerRegistry {
        +register(src_type, dst_type, handler)
        +resolve(src_type, dst_type) TransferHandler
    }

    class TransferHandler {
        <<interface>>
        +supports(src, dst) bool
        +transfer_async(step) TransferHandle
        +poll(handle) TransferResult
        +cancel(handle)
    }

    class CudaP2PTransferHandler
    class HostDMATransferHandler
    class CXLTransferHandler
    class NVMeTransferHandler
    class VendorCustomMemoryHandler

    TransferHandler <|.. CudaP2PTransferHandler
    TransferHandler <|.. HostDMATransferHandler
    TransferHandler <|.. CXLTransferHandler
    TransferHandler <|.. NVMeTransferHandler
    TransferHandler <|.. VendorCustomMemoryHandler

    TransferHandlerRegistry --> TransferHandler
~~~

### Handler 책임

Handler는 다음만 안다.

~~~text
source storage spec
destination storage spec
bytes/ranges
stream/order constraints
~~~

Handler는 다음을 몰라야 한다.

- request priority
- hot/cold policy
- why migration happened
- KV prefix semantics
- model layer semantics

---

# 18. Multi-Hop Transfer Sequence

예: GPU에서 CXL direct DMA가 불가능해서 pinned DRAM을 거치는 경우.

~~~mermaid
sequenceDiagram
    participant MP as MigrationPlanner
    participant EX as MigrationExecutor
    participant GPU as GPU HBM
    participant HOST as Pinned DRAM
    participant CXL as CXL Memory
    participant REC as CompletionReconciler

    MP-->>EX: step0 HBM->PinnedDRAM<br/>step1 PinnedDRAM->CXL

    EX->>GPU: D2H async copy
    GPU-->>HOST: step0 complete

    EX->>HOST: host/CXL transfer
    HOST-->>CXL: step1 complete

    EX-->>REC: all steps complete
    REC->>REC: validate + atomic commit
    REC->>HOST: free staging buffer
~~~

multi-hop 중 중간 staging memory는 authoritative location이 아니다.

---

# 19. Failure / Rollback Path

~~~mermaid
flowchart TD
    A["MigrationIntent"]
    B{"source/location valid?"}
    C{"target reservation success?"}
    D["pin source"]
    E["dispatch copy"]
    F{"copy success?"}
    G{"version/source unchanged?"}
    H["atomic commit target"]
    I["release/free source"]
    DONE["COMPLETED"]

    R1["reject / replan"]
    R2["free target reservation"]
    R3["rollback target<br/>keep source authoritative"]
    R4["abort stale plan<br/>keep source"]

    A --> B
    B -- no --> R1
    B -- yes --> C

    C -- no --> R1
    C -- yes --> D --> E --> F

    F -- no --> R3
    F -- yes --> G

    G -- no --> R4
    G -- yes --> H --> I --> DONE

    R3 --> R2
    R4 --> R2
~~~

### Failure semantics

| Failure | 처리 |
|---|---|
| target allocation fail | source 유지, 다른 target 또는 retry |
| handler unavailable | alternate topology path 탐색 |
| copy fail | source 유지, target discard |
| plan stale | abort 후 재계획 |
| version mismatch | target discard 또는 recopy |
| Worker crash | source authoritative 유지, in-flight job timeout 처리 |
| completion lost | idempotent status query / reconciliation |
| source pressure during copy | source pin 때문에 premature free 금지 |

---

# 20. Deployment View

~~~mermaid
graph TB
    subgraph NODE["Serving Node"]
        subgraph HOST["Host"]
            API["API Server"]
            CORE["EngineCore<br/>Scheduler + Migration Control Plane"]
            DRAM["Host DRAM / Pinned Pool"]
            SSD["NVMe SSD"]
        end

        subgraph GPU0["GPU 0"]
            W0["Worker 0 / MigrationExecutor"]
            HBM0["HBM0"]
        end

        subgraph GPU1["GPU 1"]
            W1["Worker 1 / MigrationExecutor"]
            HBM1["HBM1"]
        end

        subgraph FAB["Extended Memory Fabric"]
            CXL0["CXL Memory 0"]
            CHBM["Custom HBM / HBF"]
        end
    end

    API --> CORE

    CORE -- "MigrationCommand" --> W0
    CORE -- "MigrationCommand" --> W1

    W0 -- "DMA/P2P" --> HBM0
    W1 -- "DMA/P2P" --> HBM1

    HBM0 <-. "P2P if available" .-> HBM1

    HBM0 -. "D2H/H2D" .-> DRAM
    HBM1 -. "D2H/H2D" .-> DRAM

    DRAM -. "CXL path" .-> CXL0
    DRAM -. "vendor path" .-> CHBM
    DRAM -. "I/O" .-> SSD

    W0 -. "completion/telemetry" .-> CORE
    W1 -. "completion/telemetry" .-> CORE
~~~

---

# 21. Observability View

각 migration에 다음 record를 남긴다.

~~~text
MigrationDecisionRecord
 ├─ job_id
 ├─ intent_id
 ├─ data_type
 ├─ object_ids[]
 ├─ reason
 ├─ source_resource
 ├─ target_resource
 ├─ transfer_path[]
 ├─ total_bytes
 ├─ queue_wait_us
 ├─ reservation_us
 ├─ transfer_us
 ├─ commit_us
 ├─ achieved_bandwidth
 ├─ foreground_stall_us
 ├─ overlap_us
 ├─ source_version
 ├─ final_version
 ├─ status
 └─ failure_reason
~~~

중요 metric:

- migration bytes/sec
- migration queue depth
- foreground migration p50/p95/p99 latency
- background bandwidth utilization
- effective transfer bandwidth
- migration failure rate
- stale-plan abort rate
- source/target allocation failure rate
- promotion wait time
- compute-transfer overlap ratio
- migration amplification
- migration thrashing count
- migrated object useful lifetime
- HBM pressure relief achieved
- target residency hit rate

---

# 22. Existing vLLM Code Change Points

| 현재 파일/영역 | 변경 | 이유 |
|---|---|---|
| vllm/v1/engine/core.py | 소폭 수정 | MigrationCoordinator lifecycle/init/poll |
| vllm/v1/core/sched/scheduler.py | 수정 | migration trigger, foreground dependency 생성 |
| vllm/v1/core/sched/output.py | 수정 | MigrationCommand / Dependency Worker 전달 |
| vllm/v1/core/kv_cache_manager.py | hook 추가 | KVDataAdapter와 logical block lifecycle 연동 |
| vllm/v1/core/block_pool.py | 최소 수정 | migration 중 block pin / eviction protection |
| vllm/v1/data_migration/* | 신규 | generic control plane |
| vllm/v1/data_migration/data/kv_cache.py | 신규 | KV-specific adapter |
| vllm/v1/data_migration/worker/* | 신규 | generic transfer data plane |
| vllm/v1/kv_offload/base.py | Phase 1 재사용/확장 | LoadStoreSpec, transfer metadata |
| vllm/v1/kv_offload/worker/worker.py | Phase 1 재사용 | asynchronous transfer + handler dispatch |
| vllm/v1/worker/gpu_worker.py | 수정 | migration executor init / command execution |
| vllm/v1/worker/gpu_model_runner.py | 최소 수정 | blocking dependency wait hook |

---

# 23. Recommended Initial API

## 23.1 Control-plane API

~~~text
MigrationCoordinator.submit(
    MigrationIntent(
        data_refs=[...],
        source_resource_id="cxl0",
        target_resource_id="gpu0_hbm",
        reason="promotion",
        priority=HIGH,
        dependency_type=BLOCKING,
    )
) -> MigrationHandle
~~~

## 23.2 Data-plane command

~~~text
MigrationCommand(
    job_id=42,
    transfer_steps=[
        TransferStep(
            src_spec=...,
            dst_spec=...,
            bytes=...,
            ordering=0,
        )
    ],
)
~~~

## 23.3 Completion

~~~text
MigrationCompletion(
    job_id=42,
    success=True,
    bytes_transferred=...,
    transfer_time_us=...,
)
~~~

---

# 24. Implementation Phases

## Phase 1 — KV-only, reuse current offloading data plane

목표: architecture boundary 검증.

- MigrationIntent / MigrationPlan / MigrationJob 도입
- MigrationCoordinator / StateStore 추가
- KVDataAdapter 추가
- sealed KV block만 지원
- HBM ↔ Host DRAM 이동
- 기존 LoadStoreSpec + OffloadingWorker transfer path 재사용
- source pin + copy-success-after-commit semantics 구현
- background demotion + foreground restore 구현
- migration logging

이 단계에서는 generic memory topology를 최소화한다.

## Phase 2 — Multiple heterogeneous memory resources

- MemoryResourceRegistry
- MemoryTopology
- CXL / Custom HBM handler
- HBM↔HBM P2P
- direct/staged path capability
- multi-hop plan
- target reservation
- per-link bandwidth budget

## Phase 3 — Overlap and proactive migration

- foreground/background priority queue
- asynchronous overlap with model execution
- prefetch-triggered promotion
- pressure-triggered demotion
- cooldown / anti-thrashing
- transfer cost telemetry feedback

## Phase 4 — Other AI data types

- WeightDataAdapter
- LoRADataAdapter
- optional activation adapter
- replica-aware read-only data placement
- shared migration core validation

---

# 25. Recommended Phase-1 Runtime Flow

~~~text
Scheduler / Policy
    │
    │ MigrationIntent
    ▼
MigrationCoordinator
    │
    ├─ KVDataAdapter.can_migrate_now()
    ├─ source location lookup
    ├─ target reserve
    ├─ source pin
    │
    ▼
MigrationPlan
    │
    ▼
MigrationScheduler
    │
    ▼
MigrationExecutor
    │
    ▼
Existing OffloadingWorker
    │
    ▼
HBM / Host DRAM transfer
    │
    ▼
MigrationCompletion
    │
    ▼
CompletionReconciler
    │
    ├─ validate version
    ├─ commit new location
    └─ release old allocation
~~~

이 흐름은 현재 vLLM offloading 인프라를 최대한 재사용하면서도, generic migration을 위해 필요한 **location authority / consistency / lifecycle**을 별도 계층으로 추가한다.

---

# 26. Final Architecture Summary

~~~text
                 ┌──────────────────────────────┐
                 │ Placement / Migration Policy │
                 │    WHAT / WHERE to move      │
                 └──────────────┬───────────────┘
                                │ MigrationIntent
                                ▼
                 ┌──────────────────────────────┐
                 │    MigrationCoordinator      │
                 │    lifecycle authority       │
                 └──────┬─────────┬─────────────┘
                        │         │
                        │         └──────────────┐
                        ▼                        ▼
              ┌─────────────────┐      ┌───────────────────┐
              │ MigrationPlanner│      │ Consistency Guard │
              │ HOW to move     │      │ pin/version/commit│
              └───────┬─────────┘      └─────────┬─────────┘
                      │                          │
             ┌────────┼─────────┐                │
             ▼        ▼         ▼                ▼
        DataLocation Memory   Topology       AIDataAdapter
        / Registry  Resource
             └────────┬─────────┘
                      ▼
              ┌─────────────────┐
              │ MigrationQueue  │
              │ FG / BG / budget│
              └───────┬─────────┘
                      ▼
              ┌─────────────────┐
              │MigrationExecutor│
              │ Worker data plane│
              └───────┬─────────┘
                      ▼
              ┌─────────────────┐
              │ TransferRouter  │
              └───┬────┬────┬───┘
                  │    │    │
                  ▼    ▼    ▼
                P2P   CXL  NVMe
                DMA   DMA  I/O
                  │    │    │
                  └────┼────┘
                       ▼
              ┌─────────────────┐
              │ Completion      │
              │ Reconciler      │
              └───────┬─────────┘
                      ▼
              atomic location commit
~~~

가장 중요한 경계는 다음 다섯 문장으로 정리된다.

1. **Policy decides what/where; MigrationCoordinator owns lifecycle.**
2. **MigrationPlanner decides the transfer path, not the migration target.**
3. **TransferExecutor moves bytes; it does not reinterpret policy.**
4. **Data location changes only after successful copy and validation.**
5. **KV-specific lifecycle is isolated behind KVDataAdapter; migration core stays data-type agnostic.**

이 구조를 사용하면 현재 vLLM의 scheduler/worker separation과 kv_offload asynchronous transfer pattern을 활용하면서, HBM/DRAM/CXL/SSD를 아우르는 범용 migration runtime으로 확장할 수 있다.

---

# 27. Reference Documents

본 설계는 해당 브랜치의 다음 문서를 기준으로 작성했다.

- doc-mk/vllm-cost-model-prefill-placement-architecture.md
- doc-mk/vllm-call-path-analysis.md
- doc-mk/vllm-kv-cache-analysis.md
- doc-mk/vllm-kv-cache-memory-abstraction-layer.md
- doc-mk/vllm-kv-cache-memory-tiering.md
- doc-mk/vllm-memory-access-timing-candidates.md
- doc-mk/vllm-memory-coordination-locus-candidates.md
- doc-mk/vllm-dp3-memory-placement-abstraction-candidates.md
