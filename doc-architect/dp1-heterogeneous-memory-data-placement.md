# DP1. 이기종 메모리 기반 KV Cache 배치 구조

## 1. Design Point 개요

### 목적

LLM 추론 시스템 내에서 HBM, Custom HBM, DRAM, CXL Memory, HBF, SSD-PIM 등 서로 다른 저장/연산 특성을 가진 메모리가 혼재할 때, **KV Cache Block을 어느 메모리에 배치하고 언제 이동시킬 것인지**를 어떤 기준으로 결정할지 설계한다.

### 핵심 설계 질문

> **메모리 및 KV Cache의 어떤 특성을 기반으로 KV Block의 배치·이동을 결정할 것인가?**

### 대상 범위

| | |
|---|---|
| **대상** | Attention KV Cache Block (Prefill에서 생성되어 Decode 동안 반복 read되는 Key/Value tensor block) |
| **대상 아님** | Model Weight, MoE Expert Weight, LoRA Adapter, Activation, Embedding/RAG Index — 배치 대상이지만 본 DP의 쟁점이 아니다 |
| **대상 아님** | **어떤 KV를 회수(Evict)할 것인가** — DP3의 쟁점이다. DP1은 "어디에 둘 것인가"만 다룬다 |
| **대상 아님** | **Prefill 연산을 어디서 수행할 것인가** — DP2의 쟁점이다 |

KV Cache로 범위를 좁히는 이유는 §2에서 다룬다. 요지는 **KV Cache가 추론 메모리의 지배적 소비자이면서, 동시에 block마다 수명과 재사용 특성이 크게 다른 유일한 데이터**라는 점이다.

---

## 2. 배경 / 문제 정의

### ① KV Cache가 추론 메모리의 지배적·가변 소비자다

Model Weight는 서빙 시작 시점에 크기가 고정되지만, KV Cache는 **Context Length × Concurrency에 비례해 런타임에 증가**한다.

```text
Context Length ↑          Concurrency ↑
        │                       │
        └───────────┬───────────┘
                    ▼
            KV Cache Size ↑
                    │
                    ▼
        HBM Capacity Pressure ↑
                    │
        ┌───────────┴───────────┐
        ▼                       ▼
  신규 Request 수용 제한     Preemption / 재계산
```

Weight는 "어디에 둘지"가 한 번 결정되면 끝나는 문제지만, KV Cache는 **매 Request·매 Step마다 반복해서 발생하는 배치 결정**이다. 따라서 배치 정책의 품질이 누적되어 나타난다.

### ② 이기종 메모리가 혼재하며, 일부는 연산 기능과 유한한 Write Endurance를 갖는다

1. 메모리 병목 해소를 위해 단일 시스템 내 용량·대역폭·지연시간 특성이 상이한 이기종 메모리가 혼재할 수 있다 (CXL Memory, Custom HBM, HBF, PIM/PNM 계열 등).

2. 일부 메모리는 데이터 저장뿐 아니라 **연산 기능(Compute Capability)** 까지 제공한다. Decode 단계의 Attention은 단일 Query token과 전체 KV 간의 **GEMV 성향 연산**이고 arithmetic intensity가 낮아, memory-side compute로 처리할 여지가 상대적으로 큰 연산이다.

3. 일부 메모리는 **Read/Write 비대칭성**과 **유한한 Write Endurance**를 갖는다. HBF, SSD-PIM 등은 Write 비용이 Read 대비 현저히 높고 누적 Write 량이 소자 수명을 제한한다. KV Cache는 Prefill 시 write-once지만, **하위 Tier로의 Offload와 재사용 시의 Restore가 반복되면 write 트래픽이 누적**된다. Capacity / BW / Latency만으로 배치 적합성을 판단하면, offload가 잦은 KV를 저내구성 메모리에 배치하여 성능 저하와 수명 소모를 동시에 유발할 수 있다.

4. 기존 HBM–DRAM–SSD 구조에서는 Attention 연산 대상 KV가 최종적으로 HBM에 위치해야 했으므로 **HBM 우선 할당**과 같은 단순한 배치 정책이 합리적이었다. 그러나 연산 기능을 포함해 역할이 서로 다른 메모리가 추가되면, 단순히 GPU에 가까운 메모리를 우선하는 방식만으로는 각 자원의 특성을 충분히 활용하기 어렵다.

### ③ 모든 KV Block이 동일한 배치 요구를 갖지 않는다

KV Cache는 **균질한 데이터 덩어리가 아니다.** Block 단위로 보면 다음이 크게 다르다.

```text
KV Block A                    KV Block B                    KV Block C
System Prompt 구간            중간 Turn의 Tool Result        마지막 Turn의 생성 구간

여러 Request가 공유           단일 Request 전용             단일 Request 전용
(Prefix Cache Hit 다수)       재사용 없음                   매 Decode Step read
수 시간 잔류                  Request 종료 시 해제          Request 종료 시 해제
     │                             │                             │
     ▼                             ▼                             ▼
재사용 가치 높음              점유만 하고 접근 드묾          가장 Hot
```

동일한 크기의 Block이라도 **재사용 가능성(Hotness), 생존 기간(Lifetime), Offload 왕복 빈도(Write Intensity)** 가 자릿수 단위로 다르다. 이 차이를 반영하지 않으면 재사용 가치가 높은 Prefix Block이 느린 Tier로 밀려나고, 접근이 드문 Block이 HBM을 점유하는 상황이 발생한다.

### As-Is

**KV 특성을 고려하지 않은 단순 정책 (HBM 우선 할당, 부족 시 하위 Tier로 순차 Spill)**
→ 신규 메모리 도입 시 저장 용량으로만 활용되고, 연산 기능과 Tier별 특성이 사용되지 않음

### To-Be

**메모리 특성 및 KV Cache 특성·Attention 연산 특성을 고려한 KV Block 배치·이동 정책**
→ 신규 메모리의 저장·연산 특성을 활용하여 HBM Pressure 완화 및 Attention 실행 효율 향상

---

## 3. 배치 결정에 사용할 수 있는 정보

C1/C2 모두 동일한 Allocation Request를 받는다. 차이는 요청 정보의 차이가 아니라 **그 중 무엇을 1차 기준으로 삼는가**이므로, 먼저 사용 가능한 정보와 그 **관측 가능성**을 정리한다.

### 3.1 KV Cache Property

| 특성 | KV Cache에서의 구체적 의미 | 할당 시점에 |
|---|---|---|
| **Access Pattern** | Prefill에서 write-once, 이후 해당 Request의 매 Decode Step마다 전체 KV를 read. Block 단위 순차 접근 | **선언 가능** (Request 상태에서 직접 도출) |
| **Hotness** | 이 Block이 다른 Request에서 Prefix Cache Hit로 재사용될 빈도. System Prompt·공통 Instruction 구간은 높고, 사용자 고유 구간은 낮음 | **추정 필요** — 미래의 Prefix Hit는 원리적으로 미지 |
| **Lifetime** | Block이 해제될 때까지의 Step 수 = 해당 Request의 **남은 Decode 길이** (+ Prefix Cache로 잔류하는 기간) | **추정 필요** — 출력 길이는 생성 전에 알 수 없음 |
| **Operation** | Attention. Decode = GEMV 성향(단일 Query token), Prefill/Chunked Prefill = GEMM 성향 | **선언 가능** (Scheduler가 아는 실행 단계) |
| **Write Intensity** | Prefill write 1회 + 하위 Tier Offload/Restore 왕복 + 선점 후 재계산 시 재작성 | **부분 추정** |

### 3.2 이 DP에서 특히 중요한 두 가지 제약

**(1) Lifetime과 Hotness는 원리적으로 할당 시점에 알 수 없다.**

KV Block을 할당하는 시점에 그 Request가 20 token을 생성할지 2000 token을 생성할지 알 수 없고, 이 Prefix가 이후 다른 Request에서 재사용될지도 알 수 없다. 따라서 **C2의 오분류 Risk는 구현 품질로 제거할 수 있는 것이 아니라 문제의 성질에서 오는 구조적 비용**이다. §9.2.1의 Mode 선택 부등식과 §9.2의 추정 오차 민감도(M-P8)는 이 전제 위에서 읽어야 한다.

**(2) Block 크기가 균일하다.**

일반 데이터 배치와 달리 KV Block은 `block_size × num_layers × num_kv_heads × head_dim × dtype`으로 크기가 고정된다. 따라서 배치 결정의 변수는 "이 큰 객체를 어디에 둘까"가 아니라 **"균일한 Block 다수를 Tier 간에 어떻게 분배할까"** 이며, 같은 Request의 Block들은 **함께 해제된다**(수명 상관관계가 Request 단위로 묶임). 이는 Migration 단위와 단편화 양상에 직접 영향을 준다.

### 3.3 Memory State

두 후보 모두 관측 가능하다.

- Available Capacity
- Bandwidth / Latency
- Attention Compute Capability (해당 Tier가 GEMV/GEMM을 in-place로 처리 가능한가)
- Current Load
- Write Cost (Write Amplification) / Endurance Headroom

---

## 4. 설계 쟁점

- 메모리별 상이한 특성과 KV Block별 상이한 특성을 고려한 **KV Cache 배치·이동 의사결정 기준 설계 필요**

> **메모리 및 KV Cache의 어떤 특성을 기반으로 배치·이동을 결정할 것인가?**

본 DP의 핵심은 Allocation Request 자체의 차이가 아니라, **동일한 요청 정보 중 어떤 정보를 Placement의 1차 기준으로 삼는가**에 있다.

공통 KV Allocation Request 예시:

```text
KV Block Allocation Request
(block hash, num_blocks, block size, attention op, request id, ...)
```

---

## 5. 후보 구조

## Candidate 1. Memory-centric KV Placement

### 한 줄 정의

> **메모리 특성(Capacity / BW / Attention Compute Capability / Load / Write Endurance)을 기준으로 KV Block을 배치**

### 구조

```text
KV Block Allocation Request
(block hash, num_blocks, size, attention op, request id)
        |
        v
Memory State / Capability
- Available Capacity
- Bandwidth / Latency
- Attention Compute Capability
- Current Load
- Write Cost / Endurance Headroom
        |
        v
Tier Scoring / Selection
        |
        v
Placement / Migration
        |
        v
HBM / Custom HBM / DRAM / CXL Memory / HBF / SSD-PIM
```

### 특징

- 메모리의 현재 상태 및 Capability가 KV 배치의 1차 의사결정 기준이다.
- Capacity, BW, Load 등의 변화에 따라 배치 정책을 동적으로 변경하기 쉽다. HBM Pressure가 급증하면 **즉시** 하위 Tier로 분산된다.
- KV Block의 세부 특성(Hotness/Lifetime)을 별도로 분류하지 않아 구조가 상대적으로 단순하고, Scheduler Critical Path에 추가되는 비용이 작다.
- Attention Operation 정보는 실행 가능성 확인(이 Tier에서 in-place 처리가 가능한가)에 사용할 수 있으나, KV 특성이 Placement의 주 기준은 아니다.
- Write Endurance Headroom은 관측 가능한 Memory State이므로 직접 반영할 수 있다. 다만 **어떤 Block이 이후 Offload/Restore를 반복해 내구성을 소모할지는 사전에 판단하지 않는다.**

### 한계가 드러나는 지점

동일 시점에 도착한 System Prompt Block(재사용 다수 예상)과 사용자 고유 Block(재사용 없음)이 **동일하게 취급**된다. 두 Block은 Memory State 관점에서 구별되지 않으므로 같은 Tier로 간다.

---

## Candidate 2. Data-centric KV Placement

### 한 줄 정의

> **KV 특성(Access Pattern / Hotness / Lifetime / Attention Operation / Write Intensity)을 기준으로 배치**

### 구조

```text
KV Block Allocation Request
(block hash, num_blocks, size, attention op, request id)
        |
        v
KV Profiling / Classification
- Access Pattern (Decode Step별 재접근)
- Hotness (Prefix 공유 / 재사용 빈도)
- Lifetime (Request 잔여 Decode 길이, Prefix Cache 잔류)
- Operation (Decode GEMV / Prefill GEMM)
- Write Intensity (Prefill write, Offload/Restore 왕복)
        |
        v
Candidate Tier / Preferred Tier
        |
        v
Memory State Check
- Available Capacity
- Load
- BW / Latency
- Capability
- Write Cost / Endurance Headroom
        |
        v
Final Placement / Migration
        |
        v
HBM / Custom HBM / DRAM / CXL Memory / HBF / SSD-PIM
```

### 특징

- KV 특성을 기준으로 적합한 메모리 후보를 먼저 결정한다. 재사용 가치가 높은 Prefix Block과 접근이 드문 Block이 **후보 형성 단계에서 이미 갈라진다.**
- 이후 실제 배치 시 Available Capacity, Load 등의 Memory State를 확인하여 feasibility를 보정한다. 단 이는 1차 후보가 정해진 뒤의 필터이므로, **자원 상태가 후보 형성 자체에 미치는 영향은 C1보다 간접적**이다.
- Attention Operation과 Memory Compute Capability 간 매칭이 가능해 연산 기능을 가진 메모리 활용에 유리하다. Decode의 GEMV 성향 Attention을 memory-side compute로 보낼 후보 선택이 자연스럽게 표현된다.
- Hotness/Lifetime은 §3.2에서 밝혔듯 **원리적으로 추정 대상**이므로 Profiling/Classification 비용과 오분류 가능성이 존재한다.
- Write Intensity를 분류에 포함하면 Offload 왕복이 잦을 KV를 저내구성 메모리에서 회피할 수 있다. 다만 Write 집약도 역시 추정 대상이므로, 오분류는 성능 저하뿐 아니라 수명 소모로 직결된다.

### 한계가 드러나는 지점

HBM Pressure가 급변할 때, 후보 집합이 이미 데이터 특성으로 고정된 상태에서 Memory State는 그 안에서만 선택할 수 있다. **자원 혼잡 회피의 즉시성이 C1보다 낮다.**

---

## 6. C1 vs C2 핵심 차이

```text
            Same KV Block Allocation Request
        (block hash, num_blocks, size, op, request id)
                        |
              +---------+---------+
              |                   |
              v                   v
       C1 Memory-centric     C2 Data-centric
              |                   |
       Memory 특성이          KV 특성이
       1차 배치 기준          1차 배치 기준
              |                   |
              |             Memory State로
              |              최종 feasibility
              |                / 보정 확인
              +---------+---------+
                        |
                        v
                 Placement / Migration
```

즉, 두 후보 모두 Memory State를 확인할 수 있다. 차이는 **실시간 상태를 볼지 여부가 아니라 어떤 특성을 우선하여 Placement 후보를 형성하느냐**이다.

### 직교 축: Reactivity (본 DP의 쟁점이 아님)

**정적 배치(1회 결정 후 유지) vs 반응적 재배치(상태 변화에 따라 Migration)** 는 본 DP의 쟁점과 **직교하는 별개 설계 축**이다.

```text
              static            reactive
memory-first  C1-static         C1-reactive
data-first    C2-static         C2-reactive
```

두 후보 모두 static/reactive 어느 쪽으로도 구현할 수 있다. 따라서 "동적 자원 변화에 대응 가능한가"를 C1 또는 C2의 고유 장점으로 기술하면 두 변수가 교란되어 후보 비교가 성립하지 않는다.

> **본 DP의 쟁점은 오직 "1차 배치 기준을 Memory 특성으로 둘지 KV 특성으로 둘지"이며, 후보 비교는 동일한 Reactivity 수준 내에서만 수행한다.**

---

## 7. 장단점

| 구분 | C1. Memory-centric | C2. Data-centric |
|---|---|---|
| 주요 기준 | Capacity / BW / Attention Compute Capability / Load / Write Endurance Headroom | Access Pattern / Hotness / Lifetime / Attention Operation / Write Intensity |
| 장점 1 | 자원 혼잡·포화가 후보 형성 단계에서 직접 반영되므로 HBM Pressure 급증 시 회피가 즉각적 | KV Block 특성에 적합한 맞춤형 Placement 가능 (Prefix Block 우대, Cold Block 강등) |
| 장점 2 | KV Profiling/Classification이 불필요하여 Scheduler Critical Path 비용이 작음 | Attention Operation–Compute Capability 매칭을 통해 연산형 메모리 활용에 유리 |
| 장점 3 | 정책 구현/분석/검증이 상대적으로 단순 | 장기적인 재사용/Lifetime 특성을 고려한 Placement 최적화 가능 |
| 단점 1 | KV Block별 요구 특성을 직접 반영하지 않아 Placement Quality 한계 | KV 특성 수집·분석 및 Classification Overhead 발생 |
| 단점 2 | 미래 재사용·잔여 Decode 길이를 반영하기 어려움 | Hotness/Lifetime은 §3.2에 따라 원리적 미지값이므로 예측·분류 오류가 불가피 |
| 단점 3 | 어떤 KV가 Compute-capable Memory에 적합한지 판단에 한계 | 잘못된 분류 시 부적절한 Tier 선택 및 불필요한 Migration/Restore 발생 |

### 핵심 Trade-off

**C1**
> 단순성·자원 상태 반영의 즉시성 ↑ / KV Block별 Placement 최적화 수준 ↓

**C2**
> KV·연산 특성 기반 Placement 최적화 및 연산형 메모리 활용도 ↑ / 분석 복잡도·오분류 Risk ↑

---## 8. SW Quality Attribute 관점 비교

DP 후보 구조의 차이를 설명하는 데 직접적인 QA만 선별한다.

> **아래 등급은 정성적 가설이며 §9의 Metric으로 정량 검증할 대상이다.** 측정 결과가 등급과 다를 수 있으며, 그 경우 측정 결과를 따른다.

| QA | 평가 관점 | C1 (가설) | C2 (가설) |
|---|---|:---:|:---:|
| **Performance Efficiency** | KV/Attention 특성에 적합한 메모리 배치로 서빙 처리량과 자원 활용을 높일 수 있는가 | ★★☆ | ★★★ |
| **Maintainability** | Placement 정책의 구현·분석·검증·변경이 용이한가 | ★★★ | ★★☆ |
| **Flexibility** | 새로운 Memory를 배치 대상으로 편입할 수 있는가 | ★★☆ | ★★★ |

### Performance Efficiency

- C2는 KV의 재사용/Lifetime 특성과 Attention Operation을 Memory Capability와 직접 매칭할 수 있어 적합한 Placement 및 Compute-capable Memory 활용에 유리하다.
- 반대로 C2는 Profiling/Classification이 `allocate_slots` 경로에 추가되므로 **Placement Decision Latency는 불리**하다. 이 QA 안에서 상반된 두 힘이 작용한다.
- C2의 오분류(§3.2에 따라 불가피하다)도 결국 이 QA로 나타난다 — 잘못 배치된 KV는 Decode 내내 비싼 접근으로 청구되거나, 불필요한 Staging/Migration을 유발한다.

### Maintainability

- C1은 Memory State → Scoring → Placement 구조로 비교적 단순하다.
- C2는 Profiling → Classification → Candidate Tier Mapping → Memory State Check가 추가되어 정책 및 테스트 복잡도가 높다.

### Flexibility

- C2는 저장 특성뿐 아니라 KV 및 Attention 연산 특성을 정책에 반영할 수 있어, Compute Capability까지 다변화되는 차세대 메모리 환경에서 더 많은 종류의 Memory를 실제 배치 대상으로 편입할 수 있다.

### QA 선정에서 제외한 것 — Functional Correctness

초기 검토에서는 "입력 정보 및 예측 오차가 존재할 때 적절한 Placement를 결정할 수 있는가"를 Functional Correctness로 두었으나 **제외한다.**

- 이 DP에서 "틀린 배치"는 모델 출력이 틀리는 것이 아니다. **KV는 어느 Memory에 있든 값이 동일**하며, 배치가 틀려도 결과는 정확하다. 달라지는 것은 **비용뿐**이다. 따라서 ISO 관점의 Functional Correctness(의도한 결과를 정확하게 산출하는가)에 해당하지 않는다.
- 배치 오류의 귀결은 전부 시간·용량 비용으로 나타나므로 §9.2의 Performance Efficiency 지표에 이미 포함된다. 별도 QA로 두면 같은 현상을 두 번 세게 된다.
- 다만 "C1은 추정을 쓰지 않아 오차에 노출되지 않는다"는 구조적 차이는 여전히 후보 비교의 핵심이므로, **Performance Efficiency 안의 민감도 축(M-P8)** 으로 유지한다.

> KV Eviction으로 실제 출력 품질이 달라지는 문제는 **DP3의 쟁점**이며, 그쪽에서는 Accuracy가 Functional Correctness로 정당하게 성립한다. DP1에서는 성립하지 않는다.

---

## 9. QA별 평가 Metric

§8의 등급은 가설이므로 QA마다 **무엇을 재면 그 가설이 검증/반증되는지**를 먼저 고정한다. 실제 수치는 Prototype 실측으로 채우며 **본 문서에 가정값을 기재하지 않는다.**

### 9.1 Metric 선정 요약

| QA | 하위 특성 | Metric | 증거 종류 |
|---|---|---|---|
| **Performance Efficiency** | (종합) | **M-P1 Effective Throughput (Goodput)** — 주 지표 | 측정 |
| | Time Behaviour | M-P2 TTFT / M-P3 TPOT / M-P4 KV Staging·Restore·Migration Time / M-P5 Placement Decision Latency | 측정 (**발생 빈도가 서로 달라 각각 측정**) |
| | Resource Utilization | M-P6 HBM KV Footprint & Peak Occupancy / M-P7 Compute-capable Memory Utilization | 측정 |
| | (민감도) | M-P8 추정 오차에 대한 Goodput 민감도 | 측정 (오차 주입) |
| **Maintainability** | Analysability·Modifiability·Testability | M-M1 정책 결정 경로 복잡도 / M-M2 신규 Memory 추가 시 변경 지점 수 / M-M3 Tuning Knob 수 / M-M4 결정 분기 커버리지 비용 | **대리 지표** (소스 정적 분석) |
| **Flexibility** | Adaptability | **M-F1 지원 가능한 신규 Memory 수** | **실험** (신규 Memory 투입 후 실행) |
| (공통 Risk) | | M-E1 Endurance Pressure | 측정 |

### 9.2 Performance Efficiency

#### 9.2.1 먼저 고정할 것 — KV 접근의 두 가지 모드

배치 비용을 시간 지표로 환산하려면, **선택한 Memory가 어떤 접근 모드를 강제하는지**를 먼저 구분해야 한다. 이것이 각 비용 항의 **발생 빈도**를 결정한다.

```text
Mode A. In-place Access
  GPU가 해당 Memory를 직접 읽거나, memory-side compute가 그 Memory에서 Attention을 수행
  → 매 Decode Step마다 전체 KV 접근 비용 발생
  → 해당: HBM, Custom HBM, (GPU가 load/store 가능한) CXL, GEMV 지원 PIM/PNM

Mode B. Staging
  GPU가 직접 읽을 수 없는 Memory. Request 활성화 시 HBM으로 복원한 뒤 Decode
  → 복원 비용 1회(활성화마다) + 이후 Step은 HBM 비용
  → 해당: HBF, SSD-PIM, 기타 storage-class
```

두 모드의 손익분기는 **Residency 길이**에 달려 있다.

```text
Mode B가 유리해지는 조건

  Staging 비용 1회  <  (Mode A의 Step당 비용 − HBM Step당 비용) × 잔여 Decode Step 수
                                                                   └──────────┬──────────┘
                                                                     §3.2에 따라 할당 시점에 미지
```

**이 부등식의 우변이 Lifetime에 비례하고, Lifetime은 원리적으로 예측 대상**이라는 점이 C1/C2 비교의 핵심으로 되돌아온다. C1은 이 항을 추정하지 않고 현재 Memory State로만 판단하며, C2는 추정하되 §3.2의 구조적 오차를 안고 간다.

따라서 **KV Read Time과 Migration Time을 하나의 Step 단위 지표(TPOT)에 합산하지 않는다.** 발생 빈도가 다른 비용을 한 지표에 접으면 정책 간 비교가 워크로드의 Step 수에 좌우된다.

#### 9.2.2 비용 항의 발생 빈도 (측정 단위 고정)

| 비용 항 | 언제 발생하는가 | 곱해지는 횟수 | 지표 |
|---|---|---|---|
| Prefill KV Write | Request당 1회 (Chunked Prefill이면 chunk당) | Request 수 | M-P2 |
| Prefix Cache Hit read | Hit한 Request당 1회 | Hit 수 | M-P2 |
| Attention KV Read (**Mode A**) | **매 Decode Step** | Step 수 | M-P3 |
| Attention KV Read (**Mode B**) | HBM에서 발생 (복원 후) | Step 수 | M-P3 |
| KV Staging / Restore (**Mode B**) | Request **활성화마다 1회** | 활성화 횟수 | M-P4 |
| Migration | 재배치 이벤트 발생 시 | 이벤트 수 | M-P4 |
| Placement Decision | Block 할당 시 (Prefill 1회 + Decode 중 Block 경계마다) | 할당 횟수 | M-P5 |

#### M-P1. Effective Throughput / Goodput (주 지표)

```text
Goodput = SLO를 만족한 Request의 출력 Token 수 / 실행 시간   [tokens/s]

SLO: TTFT ≤ T_ttft  AND  TPOT ≤ T_tpot
```

**왜 Throughput을 주 지표로 두는가.**

1. **DP1의 본질이 Capacity ↔ Speed 교환이기 때문이다.** KV를 크고 느린 Memory에 두면 Token당 속도는 떨어지지만 동시 수용 Request 수가 늘어난다. **Latency 단독 지표는 "무조건 HBM"이라고만 답하며, 이기종 메모리를 도입하는 이유 자체를 볼 수 없다.** Throughput은 양쪽을 동시에 본다.
2. **Request마다 Context Length·출력 길이·Prefix 공유 정도가 모두 다르다.** 어느 한 Request의 Latency를 대표값으로 쓰면 워크로드 구성이 결론을 지배한다. Throughput은 이 이질성을 자연스럽게 집계한다.
3. **발생 빈도가 다른 비용 항(§9.2.2)을 공통 단위로 합산한다.** Step당 비용, 활성화당 비용, 할당당 비용이 각각 몇 번 발생하는지가 실행 안에서 결정되므로, 가중치를 사람이 정하지 않아도 된다.

> **반드시 SLO 제약을 걸어야 한다.** 제약 없는 raw Throughput은 **모든 Request를 느리게 만들고 Batch만 키워도 올라간다.** 그러면 "가장 싼 Memory에 전부 밀어넣기"가 최적해가 되어 지표가 무의미해진다. Goodput(SLO 만족분만 계수)이 이 퇴화를 막는다.

**보고 형태:** 단일 수치가 아니라 **Throughput–SLO 곡선**으로 보고한다. `T_tpot`를 훑으면서 각 SLO 수준에서의 Goodput을 그리면, 후보 간 우열이 바뀌는 SLO 구간이 드러난다 — 이것이 §11의 조건부 선정에 필요한 형태다.

**정규화:** As-Is(HBM 우선 할당) = 1.0.

> **Scheduler가 이 지표에 개입한다.** Goodput은 배치 정책만의 함수가 아니며, Admission/Batching/Preemption 설정이 같은 배치 결과에서도 값을 바꾼다. 비교 조건은 **§9.6.1의 Scheduler 고정 규칙**을 따른다.

#### M-P2. TTFT

Request 도착부터 첫 Token 생성까지의 시간. **배치 결정이 직접 좌우한다.**

배치가 TTFT에 영향을 주는 경로는 세 가지다.

```text
(1) Prefill KV Write
    배치 결정은 allocate_slots에서 Prefill이 KV를 쓰기 전에 일어난다.
    Prefill은 선택된 Memory에 직접 write하므로 그 Memory의 write 대역폭·
    write amplification이 Prefill 완료 시각에 직접 들어간다.

(2) Prefix Cache Hit read
    이전에 배치된 KV를 Prefill 단계에서 읽는다.
    그 KV가 어느 Memory에 있는지가 Hit의 이득 크기를 결정한다.
    (하위 Memory에 있으면 Hit이어도 복원 비용을 지불한다)

(3) Placement Decision Latency (M-P5)
    Prefill 직전 allocate_slots 경로에 있다.
```

**보조:** Prefix Cache Hit Rate, Hit / Miss 분리 TTFT (경로 (2)의 기여를 분리해서 보기 위함), p50 / p99.

#### M-P3. TPOT

Decode Token 1개당 생성 시간. **Mode A에서 배치 Tier가 직접 지배**하며, Mode B에서는 복원 이후이므로 HBM 비용으로 수렴한다.

```text
TPOT = Attention KV Read Time (Mode A면 배치 Memory, Mode B면 HBM)
     + 그 외 Decode 연산 시간 (정책 간 공통, 후보 비교에서 상쇄)
```

Staging/Restore와 Migration은 **여기에 포함하지 않는다** — Step 단위로 발생하지 않으므로 M-P4로 분리한다. 다만 복원 중 Request가 멈춰 있었다면 그 Stall은 M-P1(Goodput)과 End-to-End Latency에 나타난다.

각 접근 시간 항의 형태:

```text
시간 = 지연(경합 보정) + bytes / 유효대역폭(경합 보정)

해당 Memory가 Attention을 in-place 처리 가능  → 내부 대역폭
GPU가 이 Memory를 직접 읽을 수 있음            → 외부 대역폭
둘 다 아님                                     → Mode B (M-P4로 계상)
```

마지막 분기가 **연산-Capability 매칭이 성능으로 환산되는 유일한 경로**이므로 반드시 Cost Model에 포함한다.

**보조:** p50 / p99, Attention Kernel Execution Time.

> **이 지표가 재지 않는 것:** GPU Occupancy와 에너지 항이 없다. Memory-side compute가 GPU 연산 유닛을 비워주는 이득이 보이지 않으므로, **Compute-capable Memory에 관한 모든 수치는 이득의 하한**이다.

#### M-P4. KV Staging / Restore / Migration Time

**Step 단위가 아닌 이벤트 단위 비용.** 따로 측정한다.

```text
Staging/Restore Time = Σ over 활성화 이벤트 (복원 bytes / 유효대역폭 + 지연)
Migration Time       = Σ over 재배치 이벤트 (이동 bytes / 유효대역폭 + 지연)

보고 시 반드시 함께 낸다:
  - 총 시간
  - 이벤트 횟수 (활성화 횟수 / 재배치 횟수)
  - 이벤트당 평균 비용
```

**횟수를 함께 보고하지 않으면 해석할 수 없다.** 총 시간이 같아도 "드물게 크게" 와 "자주 조금씩"은 Goodput에 미치는 영향이 다르다(전자는 p99 Latency를 때린다).

재배치를 아예 하지 않는 정적 정책은 Migration Time이 0이므로, **이 지표 단독으로 정책을 평가하면 안 된다** — 반드시 M-P1과 함께 읽는다.

#### M-P5. Placement Decision Latency

Placement 요청 1건 처리를 위한 정책 실행 비용.

```text
Decision Cost = 정책 실행 연산 수 또는 CPU 시간 / Placement 건수
```

- C1: Memory State Read → Tier Scoring → Placement
- C2: KV Profiling/Classification → Candidate Tier → Memory State Check → Placement
- **정규화 기준을 As-Is로 둔다.** C1 = 1.0으로 정규화하면 "C1 자신이 As-Is 대비 몇 배인가"가 감춰진다.
- 이 경로는 Scheduler Critical Path(`allocate_slots`)에 있으므로 **M-P1과 M-P2에 되먹여 합산한다.** 독립적으로만 보고하면 "C2의 Decision 비용이 언제부터 배치 이득을 상쇄하는가"라는 Crossover 질문에 구조적으로 답할 수 없다.

#### M-P6. HBM KV Footprint & Peak Occupancy

```text
HBM KV Footprint        = Step별 HBM에 상주하는 KV bytes (평균 / 최대)
HBM Peak Occupancy      = max(HBM 사용량) / HBM Capacity
Memory Tier Utilization = Memory별 점유 bytes 비중
```

HBM Pressure 완화가 To-Be의 핵심 목표이며, **M-P1(Goodput)이 올라간 이유가 "동시 수용량이 늘어서"인지 설명하는 지표**다. **DP3와 공유하는 지표**이므로 동일한 정의를 쓴다.

**보조:** Max Concurrent Requests / 유효 Batch Size, KV 부족으로 인한 Preemption 및 재계산 발생률.

#### M-P7. Compute-capable Memory Utilization

Memory-side Compute에서 처리 가능한 Attention 연산 중 실제 해당 자원으로 배치되어 처리된 비율.

```text
Compute Memory Utilization
= # Attention Ops assigned to compatible compute-memory
  / # Attention Ops eligible for compute-memory
```

> **주의:** 이 지표는 **Memory Pool의 연산 커버리지에 강하게 의존**한다. Pool 내에 Decode의 GEMV를 받아줄 Memory가 하나도 없으면 어느 정책을 쓰든 0이 되며, 이는 정책의 실패가 아니라 Pool 구성의 귀결이다. **"이 Pool의 어느 Memory가 어느 연산을 지원하는가"를 함께 명시**해야 해석 가능하다.

#### M-P8. 추정 오차에 대한 Goodput 민감도

C2의 Hotness/Lifetime 추정에 **알려진 크기의 오차를 주입**하고, 그것이 M-P1에 얼마나 전달되는지 잰다.

```text
증폭률 = (해당 오차에서의 Goodput / 오차 0에서의 Goodput − 1) / 입력 오차
```

- **추정을 사용하지 않는 정책은 증폭률이 정확히 0이다** — 정의상 그렇고 검증 가능하다. C1의 강점은 여기서 수치로 나타난다.
- 추정하는 정책은 전달 함수를 갖고, **그 함수가 C2 채택의 전제 조건**이 된다.
- **Lifetime 추정 오차를 별도 축으로 훑는다.** §9.2.1에서 보였듯 Mode A/B 선택의 손익분기가 Lifetime에 직접 걸려 있으므로, Lifetime 오차는 Hotness 오차와 다른 방식으로 비용을 만든다(잘못된 Staging 판단 → M-P4 폭증).
- 무작위 노이즈(ε)와 **계통 편향(bias)** 을 분리한다. 계통 편향은 평균해서 사라지지 않으므로 같은 크기의 무작위 노이즈보다 해로울 수 있다.
- Profiling 표본율(Coverage)도 같은 축에서 훑는다 — 전수 추적은 실제 시스템에서 성립하지 않는다.

**원인 분해용 보조 지표 (독립 QA가 아님).** Goodput이 왜 나빠졌는지 설명하기 위해서만 사용한다.

| 보조 지표 | 정의 | 주의 |
|---|---|---|
| KV–Memory Matching Rate | 배치된 Memory가 해당 Block의 실제 트래픽을 감당하고, 그 Attention 연산이 in-memory 처리되거나 GPU가 직접 읽을 수 있는 위치인가 | **절대 기준으로 정의할 것.** "가장 싼 Memory 대비 허용오차 내"로 정의하면 가장 싼 쪽이 거의 항상 HBM이라 지표가 정책 판단이 아니라 Pool의 희소성을 재게 된다 |
| Mis-placement Rate | 사후 관측된 실제 접근 이력 기준으로 배치가 틀린 Block 비율 | 개수 기준과 바이트 기준 모두 보고 |
| 불필요 Migration 비율 | 이득이 없던 Migration / **Mis-placement 건수** | 분모를 Migration 건수로 두면 재배치를 안 하는 정적 정책이 "0건 중 0%"로 만점을 받는다 |
| Mode 오판율 | Staging으로 보냈으나 Residency가 짧아 복원 비용을 회수하지 못한 비율 | §9.2.1 부등식의 사후 검증 |

### 9.3 Maintainability

> **이하 4개는 모두 대리 지표(proxy)다.** 변경 비용과 상관은 있지만 그것을 직접 측정하지 않는다. **논증의 방향으로 읽어야 하고 결론으로 읽으면 안 된다.**

| Metric | 정의 | 무엇을 대리하는가 |
|---|---|---|
| **M-M1** 정책 결정 경로 복잡도 | 결정 경로의 분기·루프 수, 정책 내부 state 수, 정의된 method 수, 유효 LoC | Analysability — 다음 사람이 이 정책을 읽고 이해하는 비용 |
| **M-M2** 신규 Memory 추가 시 변경 지점 수 | 새 Memory 하나를 추가할 때 수정이 필요한 파일/클래스/enum 수 | Modifiability — 하드웨어 구성이 바뀔 때의 변경 비용 |
| **M-M3** Tuning Knob 수 | 동작을 바꾸는 정책 파라미터/Threshold 수 (공유 협력자·Reactivity 축 제외) | Analysability — 튜닝해야 할 자유도 |
| **M-M4** 결정 분기 커버리지 비용 | 모든 결정 분기를 커버하는 데 필요한 테스트 케이스 수 | Testability |

**대조군으로 As-Is를 함께 측정한다.** C1–C2 간 격차보다 "정책이 있는가 없는가"의 격차가 훨씬 클 가능성이 높고, 그 경우 이 QA에서 의미 있는 대비가 무엇인지가 결과로 드러난다.

M-M2는 §9.4의 M-F1과 짝을 이룬다 — **M-F1은 "쓸 수 있는가"(동적), M-M2는 "쓰게 만드는 데 얼마가 드는가"(정적)** 이다.

### 9.4 Flexibility

#### M-F1. 지원 가능한 신규 Memory 수 (단일 주 지표)

```text
Flexibility = # 정책이 실제로 배치에 활용한 신규 Memory 종류
              / # 투입한 신규 Memory 종류
```

**투입 세트는 실행 전에 고정하고 사후에 바꾸지 않는다.** 기존 Pool에 없던 특성 조합의 Memory를 N종 준비하여 하나씩 Pool에 추가하고, 그 Memory로 **실제 배치가 발생하는지**를 관찰한다.

투입 세트 예시 (각각 기존 Pool이 갖지 못한 조합을 하나씩 대표한다):

| 신규 Memory | 기존 Pool에 없던 점 |
|---|---|
| PNM 계열 DRAM | 외부 대역폭은 DRAM급이면서 내부 대역폭이 수 배 넓음 |
| GEMV in-place 가능한 CXL | Decode Attention을 직접 처리 가능한 중간 계층 |
| 고용량 저내구성 Flash | 용량은 크지만 Endurance Budget이 작음 |
| 저지연 소용량 SRAM 계층 | HBM보다 빠르지만 용량이 한 자릿수 작음 |

**계수 규칙 (판정 기준)**

| 관찰 | 계수 |
|---|---|
| 해당 Memory에 배치된 bytes = 0 | **미지원.** 존재를 견딘 것이지 적응한 것이 아니다 |
| 배치는 발생했으나 코드 수정이 필요했음 | **미지원.** 단 필요한 변경 지점 수를 M-M2로 별도 보고한다 |
| 코드 수정 없이 배치 발생 | **지원** |
| 지원이지만 objective가 악화 | **지원으로 계수하되 별도 표기** |

> 마지막 행이 중요하다. **"몇 종류의 새 Memory를 쓸 수 있는가"(Flexibility)와 "그래서 Goodput이 좋아지는가"(Performance Efficiency)는 별개의 질문**이며, 이번 구조에서 두 값이 같은 방향으로 움직인다고 가정하면 안 된다. 그래서 M-F1은 **반드시 M-P1(Goodput)과 분리해서 보고**한다.
>
> 또한 신규 Memory를 **기존 Medium의 새 인스턴스**로 구성할 수 있는 경우 그렇게 한다 — 코드 수정 없이 로드되어야 이 실험이 enum 편집이 아니라 **정책의 적응력**을 측정하게 된다.

**보조 관찰:** 새 Memory로 배치된 Block 수·바이트·트래픽 비중(얼마나 적극적으로 쓰는가), Workload Shift 후 배치 재수렴에 걸린 Step 수(Reactive 구성 한정).

### 9.5 공통 Risk 지표

#### M-E1. Write Amplification / Endurance Pressure

Write 비용이 높고 내구성이 유한한 메모리(HBF, SSD-PIM 등)에 Offload 왕복이 잦은 KV가 배치된 정도.

```text
Endurance Pressure
= Σ (배치된 KV의 Write Bytes × 해당 메모리의 Write Amplification)
  / 해당 메모리의 Endurance Budget
```

KV Cache는 Prefill write-once지만 **Offload/Restore 왕복과 선점 후 재계산이 write를 누적**시킨다. 시간 계열 지표만으로는 드러나지 않는 배치 오류(지금은 빠르지만 수명을 태우는 배치)를 포착하므로 **별도로** 측정한다.

### 9.6 보고 원칙

단일 수치 비교는 파라미터 선택에 취약하므로, **조건에 따른 곡선과 유효 범위**로 보고한다.

- **정규화 지표 사용** — As-Is(HBM 우선 할당)를 1.0 기준선으로 삼는다. 절대 시간값의 스케일 의존성을 제거한다.
- **Scheduler를 고정하고 병기한다** — M-P1(Goodput)은 배치 정책만의 함수가 아니다. Admission Control, Batching 구성 규칙, Preemption 방식, Chunked Prefill 설정이 **같은 배치 결과에서도** Goodput을 바꾼다. 아래 §9.6.1의 규칙을 따른다.
- **Sweep 필수** — Classification 오차율, Profiling 표본율, 자원 상태 변동 주기, Context Length, Concurrency 등 후보의 우열이 바뀔 수 있는 파라미터를 범위로 훑고 **교차 지점의 위치**를 결과로 보고한다. 교차점은 단일 지점이 아니라 **Band**로 보고하며 Sweep 해상도 이상의 정밀도를 주장하지 않는다.
- **통계적 판정 규칙을 사전 고정** — 동일 seed 쌍으로 반복하고 **신뢰구간이 0을 지나면 "차이 없음"** 으로 판정한다. 점 추정의 부호로 판정하지 않으며, 사후에 규칙을 바꾸지 않는다.
- **Cost Model 민감도 명시** — 대역폭 혼잡 계수, Latency 가중치 등을 함께 훑어 **결론의 부호가 안정한 구간에서만** 주장한다.
- **개수 편중 보정** — KV Block은 크기가 균일하지만 **트래픽 기여도가 Block마다 자릿수로 다르므로**, 모든 비율 지표를 **개수 기준과 바이트 기준 양쪽으로** 보고한다.
- **Pool 구성 병기** — M-P7과 M-F1은 Memory Pool의 연산 커버리지에 의존하므로, Pool의 어느 Memory가 어느 연산을 지원하는지를 결과와 함께 명시하지 않으면 시나리오 간 비교가 성립하지 않는다.
- **무결성 표시** — Rejection이나 Dropped Migration이 발생한 실행은 **비교 불가**로 표시한다. 목적함수에 페널티를 매기면 정책이 저자가 정한 환율로 "거부"와 "지연"을 맞바꿀 수 있게 된다.

#### 9.6.1 Scheduler 고정 규칙

Goodput을 주 지표로 쓰는 이상, **Scheduler가 결과에 개입한다.** 후보 간 차이보다 Scheduler 설정 차이가 더 클 수 있으므로 다음을 지킨다.

**(1) 동일 Scheduler 구성 내에서만 비교한다.** As-Is 기준선을 포함한 모든 정책이 같은 구성을 쓴다. 정책마다 Scheduler를 조정하면 비교가 "누가 Scheduler를 더 잘 튜닝했는지"를 재게 된다 — §10이 C1/C2에 동일한 `TierScorer`를 강제하는 것과 같은 이유다.

**(2) 구성을 결과와 함께 명시한다.** 최소한 다음을 적는다.

| 항목 | 왜 기록해야 하는가 |
|---|---|
| 최대 동시 시퀀스 수 / Batch Token 예산 | Goodput의 상한을 직접 정한다 |
| Preemption 방식 (Recompute / Swap) | **(4) 참조 — DP1과 직접 상호작용한다** |
| Chunked Prefill on/off 및 chunk 크기 | Prefill KV Write가 한 번에 발생하는지 나뉘는지를 바꿔 M-P2와 §9.2.2의 발생 빈도를 바꾼다 |
| Scheduling Policy (FCFS / Priority 등) | Request 혼합 순서를 바꿔 KV Lifetime 분포를 바꾼다 |
| Prefix Caching on/off | M-P2의 경로 (2)와 Hotness의 의미 자체를 바꾼다 |

**(3) Scheduler 설정 하나 이상을 Sweep 축에 넣는다.** 최소한 **동시성 한계(Batch 크기)** 는 훑는다. 배치 정책의 우열이 Scheduler 설정에 따라 뒤집힌다면 **그 사실 자체가 결과**이며, §11의 조건부 선정에 들어가야 한다. 단일 설정에서 얻은 결론을 일반화하지 않는다.

**(4) Preemption 방식은 섞지 않는다.** Swap 기반 Preemption은 선점된 Request의 KV를 하위 Memory로 밀어내므로 **배치 정책과 같은 자원·대역폭을 놓고 경쟁**하고, M-P4(Staging/Migration Time)와 M-E1(Endurance)에 직접 기여한다. Recompute 기반은 KV를 버리고 다시 계산하므로 그 경로가 없는 대신 Prefill 부하로 나타난다. **두 방식은 DP1의 배치 결정과 전혀 다르게 상호작용하므로, 하나를 고정하고 다른 하나는 별도 조건으로 보고한다.** 한 표 안에 섞으면 Migration 관련 수치가 배치 정책의 산물인지 Preemption의 산물인지 분리되지 않는다.

> **Scheduler를 고정해도 남는 한계:** 이 프로토타입 계열의 결론은 "선택한 Scheduler 구성 위에서" 성립한다. 실제 배치 환경의 Scheduler가 크게 다르면 Goodput 서열이 달라질 수 있으며, 이는 §12의 GPU 실측에서 확인할 항목이다.

---

## 10. 구현 구조

두 후보의 구현 구조(Module View, Class Diagram, Sequence Diagram)는 분량 관계로 별도 문서에 둔다.

> **[`dp1-implementation-uml.md`](dp1-implementation-uml.md)**

해당 문서는 vLLM v1의 실제 통합 지점(`KVCacheManager.allocate_slots()`, `BlockPool.get_new_blocks()`, `kv_offload`의 `OffloadingManager`/`LoadStoreSpec`)에 정착시켜 다음을 명세한다.

- C1/C2가 **동일한 `TierScorer`와 `TierStateView`를 공유**하고, 다른 것은 후보 집합 형성 방식뿐임을 구조로 강제
- **C1이 `profiler` 모듈에 의존 간선을 갖지 않음** — M-P8의 증폭률이 C1에서 0인 것이 구현 구조에서 보장된다
- **채점 모듈이 정책을 import하지 않음** — 정책이 자기 답을 채점하면 §9의 Metric이 의미를 잃는다
- Reactivity(§6의 직교 축)가 정책 교체 없이 두 후보에 동일하게 얹히는 구조

---

## 11. 후보 선정 (본 문서 범위 밖)

본 문서는 **Design Point의 정의, 후보 구조의 제시, 평가 Metric의 명세**까지를 범위로 한다. 후보 선정은 §9의 Metric으로 산출한 정량 Trade-off 분석 결과를 근거로 **별도 문서에서 다룬다.**

이 시점에 어느 후보도 선정하지 않는 이유:

- §8의 QA 등급과 §9의 Metric은 모두 정량 검증 이전의 가설 수준이다.
- 두 후보의 우열은 Classification 오차율, Profiling 표본율, 자원 상태 변동 주기, Context Length·Concurrency, Memory Pool의 연산 커버리지 등 **운용 조건에 따라 역전될 수 있다.** 따라서 선정은 단일 결론이 아니라 적용 조건이 명시된 형태여야 한다.
- 선정 근거를 먼저 고정하면 이후 측정이 그 결론을 확인하는 방향으로 편향될 위험이 있다.

### 선정 문서가 갖춰야 할 형태

> **조건부 선정 + 유효 범위(Envelope).** "조건 X 범위에서는 C_i, 조건 Y 범위에서는 C_j" 형태로 기술한다. 단일 후보를 무조건 선정하는 서술은 §9.6의 Sweep 결과가 전 구간에서 일관된 경우에만 허용한다.

---

## 12. 향후 검증 항목

§9에서 정의한 Metric 중 다음은 **GPU 실측 또는 실제 워크로드 확장이 필요**하며 시뮬레이션만으로는 답할 수 없다.

| 항목 | 왜 시뮬레이션으로 부족한가 |
|---|---|
| **Goodput / TTFT / TPOT 실측 (M-P1~M-P3)** | 실제 Attention Kernel, Scheduler, Batching 동작이 필요. 시뮬레이션은 배치 의존 성분만 대리 측정한다 |
| **GPU Occupancy** | Memory-side compute가 GPU 연산 유닛을 비워주는 이득. **이 항이 없으면 Compute-capable Memory에 관한 모든 수치가 이득의 하한**이 된다 |
| **Decision Latency 되먹임 (M-P5)** | Scheduler Critical Path의 실제 CPU 시간 측정이 필요 |
| **Scheduler 구성 의존성** | §9.6.1로 Scheduler를 고정해도 결론은 그 구성 위에서만 성립한다. 실제 배치 환경의 Admission/Batching/Preemption이 다르면 Goodput 서열이 달라질 수 있다 |
| **Energy** | Memory별 전력 특성 데이터 필요 |
| **Endurance Pressure (M-E1)** | 장기 Offload/Restore 왕복이 누적되는 실워크로드 필요 |

### DP2 / DP3와의 관계

- **DP2**는 DP1의 배치 결과를 입력으로 받아 **Prefill 실행 위치**를 결정한다. M-P3·M-P4가 쓰는 Memory별 Access/Transfer Cost가 그대로 DP2 Cost Model의 `C_data` 항이 된다.
- **DP3**는 HBM Capacity Pressure 발생 시 **어떤 KV를 회수할지**를 Attention Importance 기반으로 결정한다. DP1이 "어디에 둘 것인가", DP3가 "무엇을 먼저 내릴 것인가"이므로 **M-P6(HBM KV Footprint)을 공유 지표로 사용**한다.
- DP3는 Eviction이 모델 출력 품질을 바꾸므로 Accuracy가 Functional Correctness로 성립하지만, **DP1은 어느 Memory에 두든 KV 값이 동일하므로 성립하지 않는다**(§8).
