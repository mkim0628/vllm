# DP1-1. Allocation-time KV Cache Placement

> Scope: Runtime에서 새로 생성되는 **KV Cache**의 최초 Allocation 시 Target Memory Tier를 결정한다.
>
> Allocation = 새 KV Cache block/page의 최초 저장 공간 확보. Access와 Migration은 본 DP의 Allocation과 구분한다.

## 1. 문제 정의

LLM Serving에서 새로운 K/V가 생성될 때 KV Cache block/page Allocation이 필요하다. DP1-1의 질문은 **새 KV Cache를 처음 어느 Memory Tier에 만들 것인가?**이다.

    Token Processing
          ↓
    New K/V 생성 필요
          ↓
    KV Cache Allocation Request
          ↓
    DP1-1 Placement Decision
          ↓
    HBM / Custom HBM / DRAM / CXL
          ↓
    Allocate → K/V Write

## 2. Target Data

DP1-1은 **KV Cache만** 대상으로 한다. LoRA, MoE Expert, RAG Embedding/Index는 기존 Data의 Load/Access/Residency 문제가 중심이므로 Allocation-time Target에서 제외한다.

## 3. Common Trigger

두 Candidate 모두 동일한 **KV Cache Allocation Request**에서 시작한다. 입력은 block id, size, request/session id, model/layer 정보, QoS/priority, required operation 등이다. Candidate 차이는 Trigger가 아니라 Target Tier 선택 Policy이다.

## 4. C1 — Resource-driven Initial Placement

> Allocation 시점의 **현재 Memory Resource State**를 중심으로 Target Tier를 선택한다.

    KV Allocation Request
             +
    Memory Registry
             +
    Resource State Monitor ← Telemetry Collector
             ↓
    Resource Candidate Builder
             ↓
    Resource-driven Policy
             ↓
    Target Tier → Allocate

주요 입력은 available capacity, bandwidth utilization, memory pressure, contention, latency state와 정적 Memory capability이다. 예를 들어 HBM headroom이 충분하면 HBM, HBM pressure가 threshold 이상이면 Custom HBM/CXL/DRAM 후보를 선택한다.

C1은 KV의 미래 Access Behavior를 별도로 예측하지 않는다.

## 5. C2 — KV-aware Initial Placement

> 동일한 Allocation Request에 대해 **Allocation 시점에 이미 알 수 있는 KV/request 특성**을 Resource State와 함께 사용한다.

    KV Allocation Request
             ↓
    KV / Request Descriptor
    - context length
    - current sequence position
    - expected output budget (if available)
    - request priority / QoS
    - KV size / growth
             +
    Current Resource State
             ↓
    KV-aware Policy
             ↓
    Target Tier → Allocate

예: latency-critical active KV는 Fast Tier 우선, large-context request에서 HBM capacity risk가 크면 Capacity Tier 고려, 낮은 QoS와 높은 HBM pressure가 함께 존재하면 lower tier 허용.

C2 역시 아직 발생하지 않은 Runtime Behavior를 관찰/예측하지 않는다. Runtime Behavior 기반 Re-placement는 DP1-2의 범위이다.

## 6. C1 vs C2

| 구분 | C1 Resource-driven | C2 KV-aware |
|---|---|---|
| 공통 Trigger | KV Allocation Request | KV Allocation Request |
| Target | KV Cache | KV Cache |
| 시점 | 최초 Allocation | 최초 Allocation |
| 핵심 정보 | Current Resource State | KV/Request Property + Resource State |
| Runtime Behavior Monitoring | 없음 | 없음 |
| 결과 | Initial Target Tier | Initial Target Tier |

## 7. Boundary

- DP1-1: 새 KV Cache의 Initial Placement
- DP1-2: Existing AI Data의 Runtime Re-placement
- DP3: Long-context KV Capacity Pressure에서 Eviction 대상 결정
- DP4: 실제 Tier 간 Migration 실행

**DP1-1 = 새 KV Cache를 처음 어디에 만들 것인가?**