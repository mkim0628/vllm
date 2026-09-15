# doc-architect

이기종 메모리 기반 LLM/Agent 서빙을 위한 설계 문서 모음. 세 개의 Design Point로 나뉜다.

| DP | 결정하는 것 | 핵심 질문 |
|---|---|---|
| **DP1** | KV Cache **배치** | 활성 실행에서 벗어난 KV를 어느 Memory에 둘 것인가? |
| **DP2** | Prefill **실행 위치** | 어느 Compute Node에서 수행할 것인가? |
| **DP3** | KV Cache **회수** | 용량이 부족할 때 무엇을 먼저 내릴 것인가? |

```text
                    Agent / LLM Runtime
                            │
          ┌─────────────────┼─────────────────┐
          ▼                 ▼                 ▼

         DP1               DP2               DP3
    Data Placement   Compute Placement    Eviction

   "어디에 둘까?"     "어디서 실행할까?"   "무엇을 내릴까?"
          │                 ▲                 │
          │                 │                 │
          └── KV Location ──┘                 │
          │                                   │
          └──────── HBM Pressure ─────────────┘
```

DP1의 배치 결과가 DP2의 Data Movement Cost를 결정하고, DP1이 배치한 KV가 쌓여 생기는
HBM Pressure를 DP3가 회수로 해소한다. 세 DP는 독립적인 최적화 문제가 아니다.

DP1과 DP3는 둘 다 KV를 하위 계층으로 보내지만 같은 결정이 아니다 — **DP1은 수요 소멸(이 KV가 지금 안 쓰인다)이 트리거이고 재접근 시점이 기준**이며, **DP3는 공급 부족(HBM이 모자란다)이 트리거이고 Attention Importance가 기준**이다.

---

## 문서 목록

### DP1. 이기종 메모리 기반 KV Cache 배치 구조

| 문서 | 내용 |
|---|---|
| [`dp1-heterogeneous-memory-data-placement.md`](dp1-heterogeneous-memory-data-placement.md) | **설계 문서** — 문제 정의, 후보 구조 C1/C2, QA별 평가 Metric |
| [`dp1-implementation-uml.md`](dp1-implementation-uml.md) | **구현 UML** — Module View, Class Diagram, Sequence Diagram |
| [`configs/`](configs/) | **시뮬레이션 Configuration** — 6종 메모리 스펙 (값마다 단위·출처 등급 주석) |

**후보 구조**

결정 시점은 **KV가 비활성으로 전환되는 순간**이다 — 턴 종료(Agent Tool 대기), Prefix 재사용분 보존, 선점, 세션 종료. 활성 Decode 중인 KV는 GPU-reachable 메모리에 있어야 하므로 대상이 아니다.

- **C1. 메모리 특성 중심** — Memory 특성(Capacity / BW / Compute Capability / Load)이 배치 후보를 형성
- **C2. Data 특성 중심** — KV 캐시 특성(Next-access Time / Reuse Probability / Expected Remaining Lifetime / Agent Tool Info)이 후보를 형성하고, Memory State가 그 안에서 보정

대상 메모리는 **HBM / Custom HBM / CXL-PNM / DRAM / HBF / SSD-PIM** 6종이며, 이 중 **CXL-PNM · Custom HBM · SSD-PIM**이 연산 가능하다. 설계 문서 §3에 각 메모리의 interconnect 탐색 결과와 시뮬레이션 Configuration(공개값/가정값 구분 포함)이, §4에 **Attention은 메모리에서, FFN은 GPU에서** 수행하는 분리 실행 구조가 있다.

### DP2. 이기종 메모리 환경의 Agent Prefill 실행 위치 결정 구조

| 문서 | 내용 |
|---|---|
| [`dp2-agent-prefill-placement.md`](dp2-agent-prefill-placement.md) | **설계 문서** — 문제 정의, 후보 구조 C1/C2, Cost Model |
| [`dp2-c1-c2-scenario-comparison.md`](dp2-c1-c2-scenario-comparison.md) | **시나리오 비교** — 동일 Workload에서 Runtime State/KV 위치가 바뀔 때 두 후보의 결정이 어떻게 갈리는가 |
| [`dp2-implementation-uml.md`](dp2-implementation-uml.md) | **구현 UML** — Module View, Class Diagram, Sequence Diagram, Activity/State Diagram |
| [`dp2-prototype-spec.md`](dp2-prototype-spec.md) | **프로토타입 명세** — 무엇을 어떻게 재는가 (목적함수, 시나리오, sweep, 판정 규칙) |
| [`dp2-prototype-results.md`](dp2-prototype-results.md) | **프로토타입 결과** — 수치, 유효 범위, 설계 문서에 반영할 것 |

**후보 구조**

- **C1. Workload & Memory-aware Rule-based** — 사전 정의 Rule/Threshold로 결정. Runtime State 미반영
- **C2. Runtime Cost-aware Dynamic** — Candidate Node별 Cost를 계산해 `argmin` 선택

### DP3. Long Context를 위한 KV Cache Eviction 구조

| 문서 | 내용 |
|---|---|
| [`dp3-long-context-kv-cache-eviction.md`](dp3-long-context-kv-cache-eviction.md) | **설계 문서** — 문제 정의, 후보 구조 C1/C2, 평가 방향 |

**후보 구조**

- **C1. Offline Attention-based** — Representative Query로 사전에 KV Importance를 산출
- **C2. Online Attention-based** — Actual Query의 Attention 결과로 Runtime에 판단

---

## 문서 유형

같은 DP 안에서도 문서마다 **증거의 성격이 다르다.** 섞어 읽으면 안 된다.

| 유형 | 무엇인가 | 주의 |
|---|---|---|
| **설계 문서** | 문제 정의, 후보 구조, 평가 Metric의 명세 | QA 등급은 **정성적 가설**이며 정량 검증 대상이다 |
| **구현 UML** | 후보를 구현할 때의 모듈·클래스·호출 구조 | 설계 문서의 주장을 구조 수준에서 재확인한 것 |
| **시나리오 비교** | 조건을 바꿔가며 두 후보의 결정이 갈리는 지점을 서술 | 예시이며 측정이 아니다 |
| **프로토타입 명세/결과** | 실제로 측정한 수치와 그 유효 범위 | **유효 범위와 한계 절을 반드시 함께 읽을 것** |

---

## 공통 원칙

세 DP의 설계 문서가 공유하는 규칙이다.

**후보를 선정하지 않는다.** 각 설계 문서는 Design Point의 정의와 후보 구조 제시까지를
범위로 한다. 선정은 정량 Trade-off 결과를 근거로 별도 문서에서 다루며,
**"조건 X 범위에서는 C_i, 조건 Y 범위에서는 C_j"** 형태의 조건부 선정 + 유효 범위로
기술한다. 선정 근거를 먼저 고정하면 이후 측정이 그 결론을 확인하는 방향으로 편향된다.

**Metric은 증거의 종류를 밝힌다.** 측정 / 대리 지표 / 실험은 신뢰 수준이 다르므로
같은 표에서 비교하지 않는다.

**판정 규칙을 실행 전에 고정한다.** 동일 seed 쌍으로 반복하고 신뢰구간이 0을 지나면
"차이 없음"으로 판정한다. 점 추정의 부호로 판정하지 않으며 사후에 규칙을 바꾸지 않는다.

**단일 수치 대신 곡선으로 보고한다.** 후보의 우열이 바뀔 수 있는 파라미터를 Sweep하고
교차 지점을 Band로 보고한다. Sweep 해상도 이상의 정밀도를 주장하지 않는다.

---

## 읽는 순서

처음이라면 설계 문서 세 개를 DP1 → DP2 → DP3 순으로 읽는다. DP2는 DP1의 배치 결과를
입력으로 받고, DP3는 DP1이 만든 HBM Pressure를 전제하므로 이 순서가 의존 방향과 맞는다.

구현을 검토한다면 각 DP의 설계 문서를 읽은 뒤 해당 UML 문서로 넘어간다.
