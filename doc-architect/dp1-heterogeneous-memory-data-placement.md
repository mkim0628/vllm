# DP1. 이기종 메모리 기반 KV Cache 배치 구조

## 1. Design Point 개요

### 목적

LLM/Agent 추론 시스템 내에서 HBM, Custom HBM, DRAM, CXL Memory, HBF, SSD-PIM 등 서로 다른 저장/연산 특성을 가진 메모리가 혼재할 때, **활성 실행에서 벗어난 KV Cache를 어느 메모리에 둘 것인지**를 어떤 기준으로 결정할지 설계한다.

### 핵심 설계 질문

> **메모리 및 KV Cache의 어떤 특성을 기반으로 KV의 배치·이동을 결정할 것인가?**

### 결정 시점 — 이 DP가 다루는 순간

**KV가 비활성으로 전환되는 순간**이다. 활성 Decode 중인 KV는 대상이 아니다.

```text
       Prefill ──► Decode  ◄── 활성 구간: KV는 GPU-reachable 메모리에 있어야 한다
                     │           (본 DP의 결정 대상 아님)
                     ▼
              ┌─────────────┐
              │  비활성 전환 │  ◄── 본 DP의 결정 시점
              └──────┬──────┘
                     │  "이 KV를 어디에 둘 것인가?"
         ┌───────────┼───────────┐
         ▼           ▼           ▼
    HBM 유지    CXL/DRAM     HBF/SSD    (+ Compute-capable Memory)
                     │
                     ▼
              ┌─────────────┐
              │   재활성    │  ◄── 복원 비용 또는 in-place 처리
              └─────────────┘
```

비활성 전환의 계기는 넷이다.

| 계기 | 언제 | 다시 필요해지는 시점 | 재접근 확률 |
|---|---|---|---|
| **턴 종료 (Agent Multi-turn)** | Turn N Decode 완료, Tool 실행 대기 진입 | Turn N+1의 Incremental Prefill | 높음 (세션이 계속되면) |
| **재사용분 보존** | Block 완성 시 (Prefix Cache 후보) | 다른 Request의 Prefix Cache Hit | 중간 (공유도에 따라) |
| **선점 (Preemption)** | HBM 부족으로 Request가 밀려남 | 재개 시 | 매우 높음 |
| **세션 종료 후 보관** | Request 완료 | 이후 세션의 Prefix Cache Hit | 낮음 |

네 계기의 공통점이 이 DP의 성립 근거다.

> **지금 Decode 중이 아니고, 언제 다시 필요해질지 불확실한 KV.**
> 그래서 "어디에 둘 것인가"가 자명하지 않고 정책이 필요하다.

### 대상 범위

| | |
|---|---|
| **대상** | 비활성 전환 시점의 KV Cache Block 배치 및 이후의 재배치 |
| **대상 아님** | **활성 Decode 중인 KV** — GPU-reachable 메모리에 있어야 하므로 선택지가 없다. 예외는 §9.2.1 Mode C(memory-side compute)이며, 그 경우에도 결정은 비활성 시점에 내려진다 |
| **대상 아님** | Model Weight, MoE Expert Weight, LoRA Adapter, Activation, Embedding/RAG Index |
| **대상 아님** | **어떤 KV를 회수(Evict)할 것인가** — DP3의 쟁점. 경계는 §12 참조 |
| **대상 아님** | **Prefill 연산을 어디서 수행할 것인가** — DP2의 쟁점 |

> **왜 "할당 시점 배치"가 아닌가.** Prefill 직후 곧바로 Decode가 시작되므로, 갓 생성된 KV를 GPU가 직접 읽을 수 없는 메모리에 쓰는 것은 즉시 되가져와야 하는 순손실이다. 실제 vLLM의 offloading 경로도 활성 KV를 옮기지 않는다 — 블록이 완성될 때 하위 매체에 **사본**을 만들고, 그 사본은 이후 Prefix Cache Hit 시점에 다시 로드된다. **계층화 결정은 비활성 KV에 대해서만 실재한다.**

---

## 2. 배경 / 문제 정의

### ① Agent Multi-turn 실행으로 "점유하지만 접근하지 않는" KV가 구조적으로 발생한다

Agent workload는 **LLM 추론 → Tool Call → Tool Result → LLM 추론**을 반복한다. Tool 실행 구간에서 해당 세션의 KV는 **접근되지 않으면서 용량은 계속 점유**한다.

```text
Turn N                Tool 실행 대기                Turn N+1
 Decode ───────────► (수 초 ~ 수십 초) ──────────► Incremental Prefill ──► Decode
   │                        │                              │
   ▼                        ▼                              ▼
KV 활성                 KV 유휴                       KV 재활성
접근 있음              접근 없음, 점유 있음           전량 재접근
                             │
                             └─► 이 구간이 배치 결정의 기회이자 필요다
```

Turn이 반복될수록 누적 History KV는 커지고, 이 "유휴 점유"의 규모도 함께 커진다. 동시에 **유휴 구간이 길다는 것은 KV를 옮길 시간적 여유가 있다는 뜻**이기도 하다 — 활성 Decode 중에는 없는 여유다.

### ② KV Cache가 추론 메모리의 지배적·가변 소비자다

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

유휴 KV가 HBM을 점유하면 그만큼 활성 Request를 받을 수 없다. **비활성 KV를 어디에 두는가가 곧 시스템의 수용량을 결정한다.**

### ③ 이기종 메모리가 혼재하며, 일부는 연산 기능과 유한한 Write Endurance를 갖는다

1. 메모리 병목 해소를 위해 단일 시스템 내 용량·대역폭·지연시간 특성이 상이한 이기종 메모리가 혼재할 수 있다 (CXL Memory, Custom HBM, HBF, PIM/PNM 계열 등).

2. 일부 메모리는 **연산 기능(Compute Capability)** 까지 제공한다. 이것이 이 DP에서 특히 중요한 이유는 재활성 시점의 연산 모양 때문이다. Turn N+1의 Incremental Prefill은 **작은 Query(Tool Result 수백 tokens) × 거대한 History KV(수 GB)** 이고, 이어지는 Decode는 **Query 1개 × 거대한 KV**다. 양쪽 모두 KV가 압도적으로 크므로, **데이터를 연산 쪽으로 옮기는 것보다 연산을 데이터 쪽으로 보내는 것이 유리한 형태**다. History 전체를 읽어 올리는 대신 메모리 안에서 처리하고 출력만 돌려받을 수 있다면 복원 비용 자체가 사라진다 (§9.2.1 Mode C).

3. 일부 메모리는 **Read/Write 비대칭성**과 **유한한 Write Endurance**를 갖는다. HBF, SSD-PIM 등은 Write 비용이 Read 대비 현저히 높고 누적 Write 량이 소자 수명을 제한한다. **비활성 전환마다 하위 매체에 쓰고 재활성마다 되읽는 왕복이 반복되면 write 트래픽이 턴 수에 비례해 누적**된다. Capacity / BW / Latency만으로 판단하면 왕복이 잦을 KV를 저내구성 메모리에 배치하여 성능 저하와 수명 소모를 동시에 유발할 수 있다.

4. 기존 HBM–DRAM–SSD 구조에서는 계층이 사실상 용량 확장 수단이었으므로 **HBM 우선 할당 + 부족 시 순차 Spill**이 합리적이었다. 그러나 연산 기능을 포함해 역할이 서로 다른 메모리가 추가되면, 단순히 GPU에 가까운 순서로 밀어내는 방식만으로는 각 자원의 특성을 활용할 수 없다.

### ④ 모든 KV Block이 동일한 배치 요구를 갖지 않는다

비활성 KV는 **균질한 덩어리가 아니다.** Block 단위로 보면 다음이 크게 다르다.

```text
KV Block A                    KV Block B                    KV Block C
System Prompt 구간            중간 Turn의 Tool Result        직전 Turn의 생성 구간

여러 세션이 공유              단일 세션 전용                단일 세션 전용
(Prefix Cache Hit 다수)       재사용 없음                   다음 턴에 즉시 재접근
수 시간 잔류                  세션 종료 시 해제             수 초 내 재활성
     │                             │                             │
     ▼                             ▼                             ▼
재사용 가치 높음              가장 먼저 내릴 후보           빠른 계층 유지 가치 높음
```

동일한 크기의 Block이라도 **재접근 시점, 재접근 확률, 공유도**가 자릿수 단위로 다르다. 이 차이를 반영하지 않으면 다음 턴에 즉시 쓰일 Block이 SSD로 내려가고, 세션이 끝난 Block이 HBM을 점유하는 상황이 발생한다.

### As-Is

**KV 특성을 고려하지 않은 단순 정책 (HBM 우선 유지, 부족 시 하위 계층으로 순차 Spill)**
→ 신규 메모리가 용량 확장 수단으로만 쓰이고, 연산 기능과 계층별 특성이 활용되지 않음

### To-Be

**메모리 특성 및 KV의 재접근 특성·Attention 연산 특성을 고려한 비활성 KV 배치·이동 정책**
→ HBM Pressure를 완화하면서 재활성 비용을 최소화

---

## 3. 배치 결정에 사용할 수 있는 정보

C1/C2 모두 동일한 정보를 받는다. 차이는 정보의 차이가 아니라 **그 중 무엇을 1차 기준으로 삼는가**이므로, 먼저 사용 가능한 정보와 그 **관측 가능성**을 정리한다.

### 3.1 KV Cache Property

| 특성 | 비활성 KV에서의 구체적 의미 | 결정 시점에 |
|---|---|---|
| **Access Pattern** | 재활성 시 **전량 일괄 재접근**(Incremental Prefill이 History 전체에 attend). 부분 접근이 아니라 all-or-nothing | **선언 가능** |
| **재접근 시점 (Recency Horizon)** | 다음 접근까지의 유휴 시간. 턴 종료면 Tool 실행 시간, 선점이면 재개까지, Prefix 보존이면 다음 Hit까지 | **추정 필요** — 계기별로 분포가 다름 |
| **재접근 확률** | 이 KV가 다시 쓰이긴 하는가. 세션이 계속될 확률, Prefix가 재사용될 확률 | **추정 필요** |
| **공유도 (Hotness)** | 몇 개의 세션이 이 Block을 Prefix로 공유하는가. System Prompt·공통 Instruction 구간은 높음 | **부분 관측 가능** (현재 참조 수는 관측, 미래는 추정) |
| **Operation** | 재활성 시 받을 연산. Incremental Prefill = 작은 Q × 큰 KV, Decode = Q 1개 × 큰 KV. **둘 다 memory-side compute 적합 형태** | **선언 가능** |
| **Write Intensity** | 비활성 전환마다 하위 매체 write 1회 + 재활성마다 read. **턴 수에 비례해 왕복 누적** | **추정 필요** (왕복 횟수 = 남은 턴 수) |

### 3.2 이 DP에서 특히 중요한 세 가지 제약

**(1) 미지값은 "언제·다시 쓰이는가"이며, 이는 부분적으로 추정 가능하다.**

결정 시점에 알 수 없는 것은 **재접근 시점과 재접근 확률**이다. 다만 이 값들은 출력 길이 같은 원리적 미지값과 성질이 다르다 — **Tool 실행 시간 분포, 세션당 턴 수 분포, Prefix 재사용률은 워크로드 통계로 상당 부분 잡힌다.** 따라서 C2의 추정은 원리적으로 불가능한 예측이 아니라 **추정 품질의 문제**이며, 이 점이 §8의 QA 가설과 §9.2의 민감도 측정(M-P8)을 읽는 전제다.

계기별로 추정 난이도가 다르다는 점도 중요하다.

| 계기 | 재접근 시점 추정 | 재접근 확률 추정 |
|---|---|---|
| 선점 | 쉬움 (Scheduler가 재개 예정을 안다) | 거의 1.0 |
| 턴 종료 | 중간 (Tool 유형별 실행 시간 분포) | 중간 (세션 지속률) |
| 재사용분 보존 | 어려움 | 어려움 (공유도로 근사) |
| 세션 종료 후 보관 | 어려움 | 낮음 |

**(2) 재접근이 all-or-nothing이다.**

비활성 KV는 재활성 시 **History 전체가 한꺼번에** 필요하다. 절반만 복원해서 시작할 수 없다. 따라서 배치 결정의 단위가 개별 Block이 아니라 **세션 단위 Block 집합**이고, 한 집합을 여러 계층에 흩으면 재활성 비용이 가장 느린 계층에 지배된다. 이는 Migration 단위와 단편화 양상에 직접 영향을 준다.

**(3) Block 크기가 균일하다.**

KV Block은 `block_size × num_layers × num_kv_heads × head_dim × dtype`으로 크기가 고정된다. 따라서 결정 변수는 "이 큰 객체를 어디 둘까"가 아니라 **"균일한 Block 집합을 계층 간에 어떻게 분배할까"** 이다.

### 3.3 Memory State

두 후보 모두 관측 가능하다.

- Available Capacity
- Bandwidth / Latency (양방향 — 내릴 때의 write, 복원할 때의 read)
- **Attention Compute Capability** — 이 메모리가 재활성 시 attention을 in-place로 처리할 수 있는가
- Current Load
- Write Cost (Write Amplification) / Endurance Headroom

---

## 4. 설계 쟁점

- 메모리별 상이한 특성과 비활성 KV별 상이한 재접근 특성을 고려한 **배치·이동 의사결정 기준 설계 필요**

> **메모리 및 KV Cache의 어떤 특성을 기반으로 배치·이동을 결정할 것인가?**

본 DP의 핵심은 입력 정보의 차이가 아니라, **동일한 정보 중 어떤 것을 Placement의 1차 기준으로 삼는가**에 있다.

공통 Placement Request 예시:

```text
KV Placement Request
(session id, block set, total bytes, trigger, next operation, ...)

  trigger        = TURN_END | PREFIX_RETAIN | PREEMPTION | SESSION_DONE
  next operation = INCREMENTAL_PREFILL_ATTENTION | DECODE_ATTENTION
```

---

## 5. 후보 구조

## Candidate 1. Memory-centric Placement

### 한 줄 정의

> **메모리 특성(Capacity / BW / Attention Compute Capability / Load / Write Endurance)을 기준으로 비활성 KV를 배치**

### 구조

```text
KV Placement Request
(session id, block set, bytes, trigger, next op)
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

- 메모리의 현재 상태 및 Capability가 배치의 1차 의사결정 기준이다.
- HBM Pressure가 급증하면 **즉시** 더 깊은 계층으로 내려보낸다. 자원 혼잡 회피가 즉각적이다.
- KV의 재접근 특성(언제·다시 쓰일 것인가)을 별도로 추정하지 않아 구조가 단순하고, 비활성 전환 경로에 추가되는 비용이 작다.
- Attention Compute Capability는 실행 가능성 확인(이 메모리에서 in-place 처리가 가능한가)에 사용할 수 있으나, **KV 특성이 배치의 주 기준은 아니다.**
- Write Endurance Headroom은 관측 가능한 Memory State이므로 직접 반영할 수 있다. 다만 **어떤 KV가 이후 왕복을 반복해 내구성을 소모할지는 사전에 판단하지 않는다.**

### 한계가 드러나는 지점

같은 시점에 비활성으로 전환된 두 세션 — 하나는 3초 뒤 Tool Result가 돌아오고, 다른 하나는 이미 종료됐다 — 이 **Memory State 관점에서 구별되지 않는다.** 둘 다 같은 계층으로 가고, 3초 뒤 첫 번째 세션은 복원 비용을 지불한다.

---

## Candidate 2. Data-centric Placement

### 한 줄 정의

> **KV 특성(재접근 시점 / 재접근 확률 / 공유도 / 재활성 연산 / Write Intensity)을 기준으로 배치**

### 구조

```text
KV Placement Request
(session id, block set, bytes, trigger, next op)
        |
        v
KV Profiling / Classification
- 재접근 시점 (Recency Horizon)
- 재접근 확률
- 공유도 (Prefix 참조 수)
- 재활성 연산 (Incremental Prefill / Decode Attention)
- Write Intensity (예상 왕복 횟수)
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

- KV 특성을 기준으로 적합한 메모리 후보를 먼저 결정한다. **곧 돌아올 세션과 이미 끝난 세션이 후보 형성 단계에서 갈라진다.**
- 이후 Memory State를 확인하여 feasibility를 보정한다. 단 이는 1차 후보가 정해진 뒤의 필터이므로, **자원 상태가 후보 형성 자체에 미치는 영향은 C1보다 간접적**이다.
- **재활성 연산을 후보 형성에 쓸 수 있다는 것이 C2의 고유한 이점**이다. "이 KV는 다음에 작은 Q × 큰 KV attention을 받는다"는 판단이 곧 Compute-capable Memory(§9.2.1 Mode C) 선택의 근거가 되며, C1의 Memory State 기준으로는 이 판단이 나오지 않는다.
- 재접근 시점·확률은 §3.2에 따라 추정 대상이므로 Profiling/Classification 비용과 오분류 가능성이 존재한다.
- Write Intensity(예상 왕복 횟수)를 분류에 포함하면 왕복이 잦을 KV를 저내구성 메모리에서 회피할 수 있다.

### 한계가 드러나는 지점

HBM Pressure가 급변할 때, 후보 집합이 이미 데이터 특성으로 고정된 상태에서 Memory State는 그 안에서만 선택할 수 있다. **자원 혼잡 회피의 즉시성이 C1보다 낮다.**

---
## 6. C1 vs C2 핵심 차이

```text
            Same KV Placement Request
     (session id, block set, bytes, trigger, next op)
                        |
              +---------+---------+
              |                   |
              v                   v
       C1 Memory-centric     C2 Data-centric
              |                   |
       Memory 특성이          KV 재접근 특성이
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

### 직교 축: 유휴 중 재조정 (본 DP의 쟁점이 아님)

본 DP의 배치 결정은 비활성 전환이라는 **이벤트에 의해 트리거**된다. 여기에 더해 **유휴 구간 동안 상태 변화에 따라 배치를 다시 조정할 것인가**는 별개의 설계 축이다.

```text
                  전환 시 1회 결정    유휴 중 재조정
memory-first      C1-static          C1-reactive
data-first        C2-static          C2-reactive
```

유휴 중 재조정이 의미를 갖는 경우는 실재한다 — 예상보다 Tool 실행이 길어져 재접근 시점 추정이 빗나갔거나, 다른 세션의 압력으로 계층 상황이 바뀐 경우다. 그러나 두 후보 모두 static/reactive 어느 쪽으로도 구현할 수 있으므로, "동적 자원 변화에 대응 가능한가"를 C1 또는 C2의 고유 장점으로 기술하면 두 변수가 교란되어 후보 비교가 성립하지 않는다.

> **본 DP의 쟁점은 오직 "1차 배치 기준을 Memory 특성으로 둘지 KV 특성으로 둘지"이며, 후보 비교는 동일한 재조정 수준 내에서만 수행한다.**

---

## 7. 장단점

| 구분 | C1. Memory-centric | C2. Data-centric |
|---|---|---|
| 주요 기준 | Capacity / BW / Attention Compute Capability / Load / Write Endurance Headroom | 재접근 시점 / 재접근 확률 / 공유도 / 재활성 연산 / Write Intensity |
| 장점 1 | 자원 혼잡·포화가 후보 형성 단계에서 직접 반영되므로 HBM Pressure 급증 시 회피가 즉각적 | 재접근 특성에 맞춘 배치 가능 (곧 돌아올 세션은 얕게, 끝난 세션은 깊게) |
| 장점 2 | 재접근 추정이 불필요하여 비활성 전환 경로의 비용이 작음 | **재활성 연산을 후보 형성에 반영**하여 Compute-capable Memory 활용에 유리 |
| 장점 3 | 정책 구현/분석/검증이 상대적으로 단순 | 예상 왕복 횟수를 반영해 Endurance 소모를 사전 회피 가능 |
| 단점 1 | 재접근 특성을 직접 반영하지 않아 재활성 비용 최적화에 한계 | KV 특성 수집·분석 및 Classification Overhead 발생 |
| 단점 2 | 곧 돌아올 KV와 끝난 KV를 구별하지 못함 | 재접근 시점·확률 추정 오류 가능 (§3.2 — 원리적 불가능이 아니라 품질 문제) |
| 단점 3 | 어떤 KV가 Compute-capable Memory에 적합한지 판단에 한계 | 잘못된 분류 시 부적절한 계층 선택 및 불필요한 복원/왕복 발생 |

### 핵심 Trade-off

**C1**
> 단순성·자원 상태 반영의 즉시성 ↑ / 재활성 비용 최적화 및 연산형 메모리 활용 ↓

**C2**
> 재접근·연산 특성 기반 최적화 및 연산형 메모리 활용도 ↑ / 분석 복잡도·오분류 Risk ↑

---

## 8. SW Quality Attribute 관점 비교

DP 후보 구조의 차이를 설명하는 데 직접적인 QA만 선별한다.

> **아래 등급은 정성적 가설이며 §9의 Metric으로 정량 검증할 대상이다.** 측정 결과가 등급과 다를 수 있으며, 그 경우 측정 결과를 따른다.

| QA | 평가 관점 | C1 (가설) | C2 (가설) |
|---|---|:---:|:---:|
| **Performance Efficiency** | 비활성 KV를 적합한 메모리에 두어 서빙 처리량과 자원 활용을 높일 수 있는가 | ★★☆ | ★★★ |
| **Maintainability** | Placement 정책의 구현·분석·검증·변경이 용이한가 | ★★★ | ★★☆ |
| **Flexibility** | 새로운 Memory를 배치 대상으로 편입할 수 있는가 | ★★☆ | ★★★ |

### Performance Efficiency

- C2는 재접근 특성과 재활성 연산을 Memory Capability와 직접 매칭할 수 있어, 재활성 비용 절감과 Compute-capable Memory 활용에 유리하다.
- 반대로 C2는 Profiling/Classification이 비활성 전환 경로에 추가되므로 **Placement Decision Latency는 불리**하다. 이 QA 안에서 상반된 두 힘이 작용한다.
- C2의 오분류도 결국 이 QA로 나타난다 — 곧 쓰일 KV를 깊이 내리면 재활성 시 TTFT를 때리고, 끝난 KV를 얕게 두면 HBM 수용량을 깎는다.

### Maintainability

- C1은 Memory State → Scoring → Placement 구조로 비교적 단순하다.
- C2는 Profiling → Classification → Candidate Tier Mapping → Memory State Check가 추가되어 정책 및 테스트 복잡도가 높다.

### Flexibility

- C2는 저장 특성뿐 아니라 KV 및 재활성 연산 특성을 정책에 반영할 수 있어, Compute Capability까지 다변화되는 차세대 메모리 환경에서 더 많은 종류의 Memory를 실제 배치 대상으로 편입할 수 있다.

### QA 선정에서 제외한 것 — Functional Correctness

초기 검토에서는 "입력 정보 및 예측 오차가 존재할 때 적절한 Placement를 결정할 수 있는가"를 Functional Correctness로 두었으나 **제외한다.**

- 이 DP에서 "틀린 배치"는 모델 출력이 틀리는 것이 아니다. **KV는 어느 메모리에 있든 값이 동일**하며, 배치가 틀려도 결과는 정확하다. 달라지는 것은 **비용뿐**이다. 따라서 ISO 관점의 Functional Correctness(의도한 결과를 정확하게 산출하는가)에 해당하지 않는다.
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
| | Time Behaviour | M-P2 재활성 TTFT / M-P3 TPOT / M-P4 Offload·Restore·Migration Time / M-P5 Placement Decision Latency | 측정 (**발생 빈도가 서로 달라 각각 측정**) |
| | Resource Utilization | M-P6 HBM KV Footprint & Peak Occupancy / M-P7 Compute-capable Memory Utilization | 측정 |
| | (민감도) | M-P8 추정 오차에 대한 Goodput 민감도 | 측정 (오차 주입) |
| **Maintainability** | Analysability·Modifiability·Testability | M-M1 정책 결정 경로 복잡도 / M-M2 신규 Memory 추가 시 변경 지점 수 / M-M3 Tuning Knob 수 / M-M4 결정 분기 커버리지 비용 | **대리 지표** (소스 정적 분석) |
| **Flexibility** | Adaptability | **M-F1 지원 가능한 신규 Memory 수** | **실험** (신규 Memory 투입 후 실행) |
| (공통 Risk) | | M-E1 Endurance Pressure | 측정 |

### 9.2 Performance Efficiency

#### 9.2.1 먼저 고정할 것 — 재활성 방식 세 가지

배치 비용을 시간 지표로 환산하려면, **선택한 메모리가 재활성 시 어떤 방식을 강제하는지**를 먼저 구분해야 한다. 이것이 각 비용 항의 **발생 위치와 빈도**를 결정한다.

```text
Mode A. Resident (GPU-reachable 유지)
  HBM / Custom HBM / GPU가 load-store 가능한 CXL
  → 유휴 중에도 비싼 자리를 점유
  → 재활성 시 복원 비용 0, 이후 Decode는 해당 메모리에서 매 Step 읽음

Mode B. Staging (storage-class 보관)
  HBF / SSD-PIM / GPU가 직접 못 읽는 매체
  → 유휴 중 가장 싸게 보관
  → 재활성 시 History 전량을 HBM으로 복원 (§3.2(2) all-or-nothing) → TTFT 타격
  → 복원 후 Decode는 HBM에서 읽음

Mode C. In-place Compute (연산형 메모리)
  Attention을 in-place로 처리 가능한 PIM/PNM 계열
  → 유휴 중 중간 비용으로 보관
  → 재활성 시 복원 없이 메모리 안에서 attention 수행, 출력만 GPU로 전송
  → Incremental Prefill: 큰 KV 읽기 대신 (ΔToken × d) 크기 출력만 이동
```

**Mode A와 B의 손익분기는 유휴 시간에 달려 있다.**

```text
Mode B가 유리해지는 조건

  복원 비용 1회  <  (Mode A 점유 기회비용/시간) × 유휴 시간
                                                  └────┬────┘
                                             §3.2에 따라 추정 대상
```

**Mode C는 이 부등식 자체를 무력화한다.** 유휴 중 HBM을 비워주면서 재활성 복원 비용도 내지 않기 때문이다. §2③이 "일부 메모리는 연산 기능을 제공한다"고 깔아둔 전제가 실제로 값을 하는 유일한 지점이며, **Mode C를 고르려면 "이 KV가 다음에 어떤 연산을 받는가"를 알아야 하므로 C2(data-centric)의 고유 강점이 걸리는 자리**이기도 하다.

**Mode C의 제약을 함께 명시한다 — 무상은 아니다.**

| 제약 | 내용 |
|---|---|
| **Split Attention 필요** | 재활성 시 새 토큰의 KV는 GPU에서 생성되고 History KV는 연산형 메모리에 있다. Attention을 두 조각으로 나눠 계산하고 **partial softmax를 log-sum-exp로 병합**해야 한다(flash-decoding 방식). 가능하지만 구현 제약이다 |
| **"GEMV 지원" ≠ "Attention 지원"** | Softmax, causal masking, GQA head 매핑, RoPE가 in-place로 처리되는지는 장치마다 다르다. `supported_ops`를 연산 단위가 아니라 **attention 커널이 요구하는 원시 연산 집합 단위**로 선언해야 과대평가를 피한다 |
| **용량 제약** | 연산형 메모리는 대체로 DRAM 용량대이므로 모든 세션의 History를 담을 수 없다. **선택받은 일부만 갈 수 있다** — 이것이 오히려 배치 정책이 필요한 이유를 강화한다 |
| **다음 턴이 안 올 수 있다** | 세션이 종료되면 연산형 메모리 자리를 낭비한 것이다. **재접근 확률 추정**이 필요하다 |

따라서 **비용 항을 하나의 Step 단위 지표에 합산하지 않는다.** 발생 빈도와 발생 위치가 다른 비용을 한 지표에 접으면 정책 간 비교가 워크로드의 Step 수에 좌우된다.

#### 9.2.2 비용 항의 발생 빈도 (측정 단위 고정)

| 비용 항 | 언제 발생하는가 | 곱해지는 횟수 | 지표 |
|---|---|---|---|
| Offload Write (Mode B/C로 내림) | **비활성 전환마다 1회** | 전환 횟수 | M-P4 |
| Restore Read (**Mode B**) | **재활성마다 1회, History 전량** | 재활성 횟수 | M-P2, M-P4 |
| 재활성 Attention (**Mode C**) | 재활성마다, 복원 없이 in-place | 재활성 횟수 | M-P2 |
| Prefix Cache Hit 시 복원 | Hit한 Request당 1회 | Hit 수 | M-P2 |
| Decode Attention (**Mode A**) | 매 Decode Step, 해당 메모리에서 | Step 수 | M-P3 |
| Decode Attention (Mode B 복원 후) | 매 Decode Step, HBM에서 | Step 수 | M-P3 |
| Decode Attention (**Mode C**) | 매 Decode Step, in-place | Step 수 | M-P3 |
| 유휴 중 재조정 Migration | 재조정 이벤트 발생 시 | 이벤트 수 | M-P4 |
| Placement Decision | **비활성 전환마다 1회** (+ 재조정 시) | 결정 횟수 | M-P5 |

> **활성 Decode 중인 KV의 최초 배치 비용은 이 표에 없다.** §1에서 밝혔듯 그것은 이 DP의 결정 대상이 아니며, 모든 정책에 공통이므로 후보 비교에서 상쇄된다.

#### M-P1. Effective Throughput / Goodput (주 지표)

```text
Goodput = SLO를 만족한 Request의 출력 Token 수 / 실행 시간   [tokens/s]

SLO: 재활성 TTFT ≤ T_ttft  AND  TPOT ≤ T_tpot
```

**왜 Throughput을 주 지표로 두는가.**

1. **DP1의 본질이 Capacity ↔ 재활성 비용 교환이기 때문이다.** 비활성 KV를 깊은 계층으로 내리면 HBM이 비어 동시 수용 Request가 늘지만 재활성 비용을 낸다. **Latency 단독 지표는 "전부 HBM에 두라"고만 답하며, 계층을 쓰는 이유 자체를 볼 수 없다.** Throughput은 양쪽을 동시에 본다.
2. **세션마다 턴 수·유휴 시간·History 크기가 모두 다르다.** 어느 한 Request의 Latency를 대표값으로 쓰면 워크로드 구성이 결론을 지배한다.
3. **발생 빈도가 다른 비용 항(§9.2.2)을 공통 단위로 합산한다.** 전환당·재활성당·Step당 비용이 각각 몇 번 발생하는지가 실행 안에서 결정되므로, 가중치를 사람이 정하지 않아도 된다.

> **반드시 SLO 제약을 걸어야 한다.** 제약 없는 raw Throughput은 **모든 Request를 느리게 만들고 Batch만 키워도 올라간다.** 그러면 "전부 가장 싼 계층으로 내리기"가 최적해가 되어 지표가 무의미해진다. Goodput(SLO 만족분만 계수)이 이 퇴화를 막는다.

**보고 형태:** 단일 수치가 아니라 **Throughput–SLO 곡선**으로 보고한다. `T_ttft`를 훑으면서 각 SLO 수준의 Goodput을 그리면 후보 간 우열이 바뀌는 구간이 드러난다 — §11의 조건부 선정에 필요한 형태다.

**정규화:** As-Is(HBM 우선 유지 + 순차 Spill) = 1.0.

> **Scheduler가 이 지표에 개입한다.** Goodput은 배치 정책만의 함수가 아니며, Admission/Batching/Preemption 설정이 같은 배치 결과에서도 값을 바꾼다. 비교 조건은 **§9.6.1의 Scheduler 고정 규칙**을 따른다.

#### M-P2. 재활성 TTFT

**비활성 KV가 다시 필요해진 시점부터 첫 Token이 나오기까지의 시간.** 이 DP의 배치 결정이 가장 직접적으로 지불하는 대가다.

```text
Mode A → 복원 없음.  재활성 TTFT = Incremental Prefill 연산 시간

Mode B → 복원 있음.  재활성 TTFT = History 전량 복원 시간 (all-or-nothing)
                                  + Incremental Prefill 연산 시간
                     ※ 세션의 Block이 여러 계층에 흩어져 있으면
                       가장 느린 계층이 이 항을 지배한다 (§3.2(2))

Mode C → 복원 없음.  재활성 TTFT = in-place Attention 시간
                                  + 출력(ΔToken × d) 전송 시간
                                  + Split Attention 병합 오버헤드
```

**측정 구분:** 계기별로 분리해서 보고한다 — 턴 재개 / Prefix Cache Hit / 선점 재개는 History 크기와 빈도가 다르므로 한 수치로 합치면 해석이 불가능하다.

**보조:** Prefix Cache Hit Rate, Hit / Miss 분리 TTFT, p50 / p99, 최초 Request의 TTFT(배치 결정 이전이므로 **대조군**으로만 사용).

#### M-P3. TPOT

Decode Token 1개당 생성 시간. **Mode A와 Mode C에서 배치된 메모리가 직접 지배**하며, Mode B는 복원 이후이므로 HBM 비용으로 수렴한다.

```text
TPOT = Attention KV Read Time (Mode A: 배치 메모리 / Mode B: HBM / Mode C: in-place)
     + 그 외 Decode 연산 시간 (정책 간 공통, 후보 비교에서 상쇄)
```

Offload/Restore와 Migration은 **여기에 포함하지 않는다** — Step 단위로 발생하지 않으므로 M-P4로 분리한다.

각 접근 시간 항의 형태:

```text
시간 = 지연(경합 보정) + bytes / 유효대역폭(경합 보정)

해당 메모리가 Attention을 in-place 처리 가능  → 내부 대역폭 (Mode C)
GPU가 이 메모리를 직접 읽을 수 있음            → 외부 대역폭 (Mode A)
둘 다 아님                                     → Mode B (복원 비용은 M-P4/M-P2)
```

마지막 분기가 **연산-Capability 매칭이 성능으로 환산되는 유일한 경로**이므로 반드시 Cost Model에 포함한다.

> **이 지표가 재지 않는 것:** GPU Occupancy와 에너지 항이 없다. Mode C에서 memory-side compute가 GPU 연산 유닛을 비워주는 이득이 보이지 않으므로, **Compute-capable Memory에 관한 모든 수치는 이득의 하한**이다. Mode C를 도입할수록 이 하한 성격이 강해진다.

#### M-P4. Offload / Restore / Migration Time

**Step 단위가 아닌 이벤트 단위 비용.** 따로 측정한다.

```text
Offload Time   = Σ over 비활성 전환 (내린 bytes / 유효대역폭 + 지연)
Restore Time   = Σ over 재활성      (복원 bytes / 유효대역폭 + 지연)   ※ Mode B만
Migration Time = Σ over 재조정 이벤트 (이동 bytes / 유효대역폭 + 지연)

보고 시 반드시 함께 낸다:
  - 총 시간
  - 이벤트 횟수 (전환 / 재활성 / 재조정)
  - 이벤트당 평균 비용
  - 왕복 횟수 분포 (세션당 offload-restore 반복 수)
```

**왕복 횟수를 함께 보고하지 않으면 해석할 수 없다.** 턴이 많은 세션은 같은 History를 여러 번 내렸다 올리므로, 총 시간이 같아도 "많은 세션이 한 번씩"과 "적은 세션이 여러 번"은 M-E1(Endurance)에 미치는 영향이 전혀 다르다.

재조정을 하지 않는 정적 정책은 Migration Time이 0이므로, **이 지표 단독으로 정책을 평가하면 안 된다** — 반드시 M-P1과 함께 읽는다.

#### M-P5. Placement Decision Latency

Placement 결정 1건 처리를 위한 정책 실행 비용.

```text
Decision Cost = 정책 실행 연산 수 또는 CPU 시간 / 결정 건수
```

- C1: Memory State Read → Tier Scoring → Placement
- C2: KV Profiling/Classification → Candidate Tier → Memory State Check → Placement
- **정규화 기준을 As-Is로 둔다.** C1 = 1.0으로 정규화하면 "C1 자신이 As-Is 대비 몇 배인가"가 감춰진다.
- 이 경로는 비활성 전환 처리에 있으므로 **M-P1에 되먹여 합산한다.** 독립적으로만 보고하면 "C2의 Decision 비용이 언제부터 배치 이득을 상쇄하는가"라는 Crossover 질문에 구조적으로 답할 수 없다.
- 활성 Decode의 Critical Path에는 없다는 점이 §9.2.2 프레이밍의 귀결이다 — 할당 시점 배치였다면 `allocate_slots`에 걸려 TTFT를 직접 때렸겠지만, 비활성 전환 경로는 상대적으로 여유가 있다. **이 여유가 C2의 Profiling 비용을 감당할 수 있게 만드는 구조적 이유**이므로 결과 해석에 명시한다.

#### M-P6. HBM KV Footprint & Peak Occupancy

```text
HBM KV Footprint          = Step별 HBM에 상주하는 KV bytes (평균 / 최대)
  그 중 유휴 KV 비중       = 접근되지 않으면서 HBM을 점유하는 bytes 비율   ← 핵심
HBM Peak Occupancy        = max(HBM 사용량) / HBM Capacity
Memory Tier Utilization   = 메모리별 점유 bytes 비중
```

**"유휴 KV가 HBM을 점유하는 비율"이 이 DP의 직접적인 개선 대상**이다. HBM Pressure 완화가 To-Be의 핵심 목표이며, M-P1(Goodput)이 올라간 이유가 "동시 수용량이 늘어서"인지 설명한다. **DP3와 공유하는 지표**이므로 동일한 정의를 쓴다.

**보조:** Max Concurrent Sessions / 유효 Batch Size, KV 부족으로 인한 Preemption 발생률.

#### M-P7. Compute-capable Memory Utilization

Memory-side Compute에서 처리 가능한 Attention 연산 중 실제 해당 자원에서 처리된 비율 (Mode C 채택률).

```text
Compute Memory Utilization
= # 재활성 Attention Ops processed in-place
  / # 재활성 Attention Ops eligible for in-place processing
```

> **주의 1 — Pool 의존성.** 이 지표는 **Memory Pool의 연산 커버리지에 강하게 의존**한다. Pool 내에 attention을 받을 수 있는 메모리가 없으면 어느 정책을 쓰든 0이며, 이는 정책의 실패가 아니라 Pool 구성의 귀결이다. **"이 Pool의 어느 메모리가 attention의 어느 원시 연산을 지원하는가"를 함께 명시**해야 해석 가능하다.
>
> **주의 2 — eligible의 정의.** §9.2.1의 Mode C 제약에 따라, "GEMV를 지원한다"가 곧 "attention을 처리할 수 있다"가 아니다. eligible 판정은 **attention 커널이 요구하는 원시 연산 집합을 그 메모리가 모두 지원하는가**로 내려야 하며, 그렇지 않으면 이 지표가 과대평가된다.

#### M-P8. 추정 오차에 대한 Goodput 민감도

C2의 재접근 시점·확률 추정에 **알려진 크기의 오차를 주입**하고, 그것이 M-P1에 얼마나 전달되는지 잰다.

```text
증폭률 = (해당 오차에서의 Goodput / 오차 0에서의 Goodput − 1) / 입력 오차
```

- **추정을 사용하지 않는 정책은 증폭률이 정확히 0이다** — 정의상 그렇고 검증 가능하다. C1의 강점은 여기서 수치로 나타난다.
- 추정하는 정책은 전달 함수를 갖고, **그 함수가 C2 채택의 전제 조건**이 된다.
- **오차 종류를 분리해서 훑는다.** 세 가지가 서로 다른 경로로 비용을 만든다.

| 오차 축 | 틀렸을 때 나타나는 곳 |
|---|---|
| **재접근 시점** | Mode A/B 손익분기 오판 → 곧 쓸 KV를 깊이 내려 M-P2 폭증, 또는 안 쓸 KV를 얕게 둬 M-P6 악화 |
| **재접근 확률** | Mode C 자리 낭비 → 안 돌아올 세션이 연산형 메모리를 점유해 M-P7의 분자는 늘지만 Goodput은 안 오름 |
| **예상 왕복 횟수** | 저내구성 메모리 선택 오판 → M-E1 폭증 |

- 무작위 노이즈(ε)와 **계통 편향(bias)** 을 분리한다. 계통 편향은 평균해서 사라지지 않으므로 같은 크기의 무작위 노이즈보다 해로울 수 있다.
- **계기별로 나눠 훑는다.** §3.2의 표대로 선점은 추정이 쉽고 Prefix 보존은 어렵다. 전체 평균 오차만 보면 어느 계기에서 C2가 무너지는지 드러나지 않는다.
- Profiling 표본율(Coverage)도 같은 축에서 훑는다.

**원인 분해용 보조 지표 (독립 QA가 아님).** Goodput이 왜 나빠졌는지 설명하기 위해서만 사용한다.

| 보조 지표 | 정의 | 주의 |
|---|---|---|
| KV–Memory Matching Rate | 배치된 메모리가 해당 세션의 재접근 시점·연산 요구를 만족하는가 | **절대 기준으로 정의할 것.** "가장 싼 메모리 대비 허용오차 내"로 정의하면 가장 싼 쪽이 거의 항상 HBM이라 지표가 정책 판단이 아니라 Pool의 희소성을 재게 된다 |
| Mis-placement Rate | 사후 관측된 실제 재접근 이력 기준으로 배치가 틀린 세션 비율 | 세션 수 기준과 바이트 기준 모두 보고 |
| 불필요 Migration 비율 | 이득이 없던 재조정 / **Mis-placement 건수** | 분모를 Migration 건수로 두면 재조정을 안 하는 정적 정책이 "0건 중 0%"로 만점을 받는다 |
| Mode 오판율 | Mode B로 내렸으나 유휴 시간이 짧아 복원 비용을 회수하지 못한 비율 / Mode C에 뒀으나 재접근이 없었던 비율 | §9.2.1 부등식과 Mode C 제약의 사후 검증 |

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

비활성 전환마다 하위 매체에 write하고 재활성마다 되읽으므로, **왕복 횟수가 세션당 턴 수에 비례해 누적**된다. 턴이 많은 Agent 세션 하나가 짧은 세션 수십 개보다 특정 매체의 수명을 더 소모할 수 있으므로, M-P4의 왕복 횟수 분포와 함께 읽는다. 시간 계열 지표만으로는 드러나지 않는 배치 오류(지금은 빠르지만 수명을 태우는 배치)를 포착하므로 **별도로** 측정한다.

### 9.6 보고 원칙

단일 수치 비교는 파라미터 선택에 취약하므로, **조건에 따른 곡선과 유효 범위**로 보고한다.

- **정규화 지표 사용** — As-Is(HBM 우선 할당)를 1.0 기준선으로 삼는다. 절대 시간값의 스케일 의존성을 제거한다.
- **Scheduler를 고정하고 병기한다** — M-P1(Goodput)은 배치 정책만의 함수가 아니다. Admission Control, Batching 구성 규칙, Preemption 방식, Chunked Prefill 설정이 **같은 배치 결과에서도** Goodput을 바꾼다. 아래 §9.6.1의 규칙을 따른다.
- **Sweep 필수** — 재접근 시점·확률 추정 오차, Profiling 표본율, **유휴 시간 분포**, **세션당 턴 수**, Context Length, Concurrency, Memory Pool의 연산 커버리지 등 후보의 우열이 바뀔 수 있는 파라미터를 범위로 훑고 **교차 지점의 위치**를 결과로 보고한다. 교차점은 단일 지점이 아니라 **Band**로 보고하며 Sweep 해상도 이상의 정밀도를 주장하지 않는다.
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

해당 문서는 vLLM v1의 실제 통합 지점 — 비활성 전환 이벤트(`KVCacheManager.free()` / 선점 경로 / `BlockPool.cache_full_blocks()`), 재활성 경로(`get_computed_blocks()`), 그리고 `kv_offload`의 `OffloadingManager`/`LoadStoreSpec` — 에 정착시켜 다음을 명세한다.

- C1/C2가 **동일한 `TierScorer`와 `TierStateView`를 공유**하고, 다른 것은 후보 집합 형성 방식뿐임을 구조로 강제
- **C1이 `profiler` 모듈에 의존 간선을 갖지 않음** — M-P8의 증폭률이 C1에서 0인 것이 구현 구조에서 보장된다
- **채점 모듈이 정책을 import하지 않음** — 정책이 자기 답을 채점하면 §9의 Metric이 의미를 잃는다
- **결정이 활성 Decode의 Critical Path 밖에 있음** — §9.2.2의 프레이밍이 구조로 드러나는 지점이며, C2의 Profiling 비용을 감당 가능하게 만드는 이유다
- 유휴 중 재조정(§6의 직교 축)이 정책 교체 없이 두 후보에 동일하게 얹히는 구조

---

## 11. 후보 선정 (본 문서 범위 밖)

본 문서는 **Design Point의 정의, 후보 구조의 제시, 평가 Metric의 명세**까지를 범위로 한다. 후보 선정은 §9의 Metric으로 산출한 정량 Trade-off 분석 결과를 근거로 **별도 문서에서 다룬다.**

이 시점에 어느 후보도 선정하지 않는 이유:

- §8의 QA 등급과 §9의 Metric은 모두 정량 검증 이전의 가설 수준이다.
- 두 후보의 우열은 재접근 추정 오차, Profiling 표본율, **유휴 시간 분포와 세션당 턴 수**, Context Length·Concurrency, Memory Pool의 연산 커버리지 등 **운용 조건에 따라 역전될 수 있다.** 따라서 선정은 단일 결론이 아니라 적용 조건이 명시된 형태여야 한다.
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
- **DP3**와의 경계는 **트리거와 판단 기준**으로 구분한다. 둘 다 KV를 하위 계층으로 보내지만 같은 결정이 아니다.

| | DP1 (본 문서) | DP3 |
|---|---|---|
| **트리거** | **수요 소멸** — 이 KV가 지금 안 쓰인다 | **공급 부족** — HBM이 모자란다 |
| **판단 기준** | **언제 다시 쓰이는가** (재접근 시점·확률) | **결과에 얼마나 중요한가** (Attention Importance) |
| **대상 단위** | 세션 단위 Block 집합 (§3.2(2)) | 개별 Token/Block |
| **되돌릴 수 있는가** | 예 — 재활성 시 복원 또는 in-place 처리 | 손실 가능 — 회수한 KV는 출력 품질에 영향 |

  DP1이 유휴 KV를 제때 내려주면 DP3가 발동할 상황 자체가 줄어든다. 반대로 DP1이 실패하면 HBM이 차서 DP3가 **활성 세션의 KV를 중요도 기준으로 깎아야** 한다. **M-P6(HBM KV Footprint, 특히 유휴 KV 점유 비중)을 공유 지표로 사용**하여 이 관계를 관측한다.
- DP3는 Eviction이 모델 출력 품질을 바꾸므로 Accuracy가 Functional Correctness로 성립하지만, **DP1은 어느 Memory에 두든 KV 값이 동일하므로 성립하지 않는다**(§8).
