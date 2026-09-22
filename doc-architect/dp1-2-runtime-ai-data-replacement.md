# DP1-2. Runtime AI Data Re-placement

> Scope: 이미 Memory Hierarchy에 존재하는 AI Data의 Runtime 상태를 기반으로 **Re-placement 필요 여부와 Destination Tier**를 결정한다.
>
> 실제 Data Copy/Migration은 DP4가 수행한다.

## 1. 문제 정의

AI Serving Runtime에서는 최초 Placement 이후에도 workload와 access pattern이 변한다. DP1-2의 질문은 **이미 배치된 AI Data를 Runtime 중 언제, 어느 Memory Tier로 Re-place할 것인가?**이다.

    Existing AI Data
          ↓
    Runtime Monitoring
          ↓
    Placement Re-evaluation
          ↓
    KEEP / PROMOTE / DEMOTE
          ↓
    Re-placement Decision
          ↓
    DP4 Migration Execution

## 2. Target Data와 실제 Placement Object

### 2.1 LoRA Adapter

대상은 **LoRA Adapter Weight 자체의 Residency 위치**이다.

    Backing/Capacity Tier: SSD / Host DRAM / CXL
                         ↕
    Fast Resident Tier: HBM / Custom HBM
                         ↓
                    GPU inference

- Hot LoRA: CXL/DRAM → HBM
- Cold LoRA: HBM → CXL/DRAM
- Behavior signal: adapter request frequency, reuse interval, tenant/domain popularity, active/idle duration, hotness trend

### 2.2 MoE Expert Weight

대상은 **MoE Expert Weight의 Runtime Residency 위치**이다. Expert selection 자체는 Router의 책임이며 DP1-2는 Weight를 어느 Tier에 resident시킬지 결정한다.

    Capacity Tier: DRAM / CXL
                   ↕
    Fast Tier: HBM / Custom HBM
                   ↓
              Expert Compute

- High-activation Expert: CXL/DRAM → HBM
- Low-activation Expert: HBM → CXL/DRAM
- Behavior signal: expert activation frequency, routing probability, token volume, activation skew, hotness trend

### 2.3 RAG Embedding / Vector Index Cache

**전체 Vector DB/Persistent Index는 DP1-2 대상이 아니다.** 대상은 Runtime에 cache/resident된 **Embedding Vector 또는 Index Block의 위치**이다.

    Persistent Vector DB / Index
                 ↓
       Runtime Cached Region
          ↙      ↓      ↘
        HBM     DRAM     CXL

- Frequently accessed embedding/index region: DRAM/CXL → HBM
- Cold cached region: HBM → CXL/DRAM
- 장기 cold data의 cache eviction/backing-store 정책은 별도 cache/eviction policy와 연계
- Behavior signal: query hit frequency, index-block access frequency, reuse interval, semantic/domain locality, working-set transition

**Retrieval Request 자체는 Placement Request가 아니다.** Retrieval은 기존 Data를 찾고 읽는 Access Event이며, DP1-2는 그 Access History를 Behavior signal로 사용할 뿐이다.

## 3. Common Output

두 Candidate 모두 Existing Data에 대해 object_id, current_tier, destination_tier, action(KEEP/PROMOTE/DEMOTE), reason, priority를 포함하는 Re-placement Decision을 만든다.

## 4. C1 — Resource-driven Re-placement

> **Memory Resource State 변화/Pressure**를 기준으로 Existing Data의 Placement를 재평가한다.

    Telemetry Collector
            ↓
    Resource State Monitor
            ↓
    Capacity / BW / Contention / Pressure
            ↓
    Resource-driven Policy
            ↓
    Victim + Destination Selection
            ↓
    Re-placement Decision → DP4

대표 Trigger는 HBM capacity pressure, bandwidth saturation, contention 증가, tier load imbalance, Fast Tier headroom 회복 등이다. C1의 1차 원인은 Data Behavior가 아니라 **Resource 상태 변화**이다.

## 5. C2 — Behavior-driven Re-placement

> **실제 Runtime Data Behavior와 변화 추세**를 관찰하고 향후 Behavior를 예측하여 선제적으로 Re-place한다.

    Runtime Access Events
            ↓
    Data Behavior Monitor
            ↓
    Behavior Interpretation
            ↓
    Trend / Future Behavior Prediction
            ↓
    Behavior-driven Policy
            ↓
    KEEP / PROMOTE / DEMOTE
            ↓
    Re-placement Decision → DP4

Resource Pressure가 없어도 Data Behavior 변화 자체가 Re-evaluation을 유발할 수 있다.

예: LoRA request frequency 2→5→15→40 req/s이면 hotness 상승을 감지/예측하여 CXL/DRAM→HBM promotion. Expert activation share가 증가하면 해당 Expert Weight를 Fast Tier로 promotion. 특정 RAG index block의 hit/access frequency가 증가하면 해당 cached region을 Fast Tier로 promotion한다.

## 6. C1 vs C2

| 구분 | C1 Resource-driven | C2 Behavior-driven |
|---|---|---|
| 공통 문제 | Runtime Re-placement | Runtime Re-placement |
| 대상 | Existing AI Data | Existing AI Data |
| 핵심 Monitor | Resource State Monitor | Data Behavior Monitor |
| 1차 판단 근거 | Memory Resource State | Data Runtime Behavior |
| 대표 Trigger | Pressure / contention / imbalance | Hotness / reuse / access trend |
| 성격 | Reactive 중심 | Proactive 가능 |
| 결과 | KEEP / PROMOTE / DEMOTE | KEEP / PROMOTE / DEMOTE |
| 실제 이동 | DP4 | DP4 |

## 7. Data별 Placement Object 명세

| Data Type | 실제 Re-placement Object | Fast Tier 예 | Capacity Tier 예 |
|---|---|---|---|
| LoRA | Adapter Weight | HBM / Custom HBM | DRAM / CXL |
| MoE | Expert Weight | HBM / Custom HBM | DRAM / CXL |
| RAG | Runtime-cached Embedding Vector / Index Block | HBM | DRAM / CXL |
| RAG Persistent Source | 전체 Vector DB / Persistent Index — DP1-2 대상 아님 | - | SSD / Vector Store |

Retrieval, Expert Routing, Adapter Selection 같은 **Access/Selection Event 자체를 Placement와 혼동하지 않는다.**

## 8. Boundary

- DP1-2: Existing Data의 KEEP/PROMOTE/DEMOTE 및 Destination Tier 결정
- DP3: Long-context KV Capacity Pressure에서 Eviction 대상 선정
- DP4: source→destination Migration 실제 수행 및 copy/synchronization/consistency 처리

**DP1-2 = Policy: 옮길 것인가, 어디로 옮길 것인가?**

**DP4 = Mechanism: 실제로 어떻게 옮길 것인가?**