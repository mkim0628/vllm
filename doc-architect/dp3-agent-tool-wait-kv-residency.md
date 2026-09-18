# DP3. Agent Tool-wait KV Residency 관리 구조

## 1. Design Point 정의

### 목적

Agent 실행에서는 LLM이 Tool Call을 생성한 뒤 외부 Tool, Sub-agent, 사용자 승인 등의 결과를 기다리는 동안 LLM 실행이 중단된다. 이때 해당 Session의 KV Cache는 즉시 사용되지 않지만, Tool Result가 도착한 뒤 기존 Context를 이어서 처리하기 위해 계속 유지되어야 한다.

다수의 Agent가 동시에 Tool Wait 상태에 들어가면, 연산에는 사용되지 않는 Session KV가 HBM을 장시간 점유하여 신규 Request Admission과 활성 Agent의 실행을 제한할 수 있다.

본 DP는 Tool 완료 시점을 예측하지 않는다. 대신 Runtime이 정확히 관찰할 수 있는 다음 Event를 이용한다.

- `TOOL_CALL_ISSUED`: Agent가 LLM 실행을 중단하고 Tool Wait에 진입
- `MEMORY_PRESSURE_HIGH`: 상위 Memory에서 추가 용량 확보 필요
- `TOOL_RESULT_READY`: Tool Result가 도착하여 Agent 실행 재개 필요

### 핵심 설계 질문

> **Agent가 Tool Wait 상태에 진입했을 때 Session KV의 HBM Residency 권한을 어떻게 변경하고, Tool Result가 도착했을 때 Resume Latency를 최소화하면서 어떻게 재활성화할 것인가?**

### 한 줄 정의

> **Tool Call과 Tool Result라는 명시적 Agent Lifecycle Event를 이용해 Session KV를 Active·Reclaimable·Reactivating 상태로 관리하는 구조를 설계한다.**

---

## 2. 배경 / 문제 정의

### 2.1 Agent 실행에서는 LLM 연산과 Tool Wait가 반복됨

일반적인 단일 LLM 요청은 `Prefill → Decode → 종료`로 끝나지만, Agent 실행은 다음 과정을 반복한다.

```text
User / Agent Input
        │
        ▼
Incremental Prefill
        │
        ▼
      Decode
        │
        ▼
    Tool Call
        │
        ▼
    Tool 실행  ─────────────┐
        │                   │ LLM 실행 중단
        ▼                   │ Session KV 유휴
  Tool Result               │
        │                   │
        └───────────────────┘
        │
        ▼
Incremental Prefill
        │
        ▼
      Decode
```

Tool 실행 시간은 수 ms의 Local Function부터 수 초 이상의 Web Search, Database Query, Code Execution, Sub-agent 실행까지 다양하다. Tool Wait 중 LLM Compute는 발생하지 않지만 기존 Context의 KV는 이후 실행을 위해 남아 있다.

### 2.2 Tool Wait 중 Session KV는 사용되지 않지만 HBM Residency를 유지할 수 있음

Agent $a$가 Tool Wait 상태에 머무는 동안 유휴 KV 점유량은 다음과 같이 표현할 수 있다.

$$
I_a = S_{\mathrm{KV}}(a) \times T_{\mathrm{wait}}(a)
$$

- $S_{\mathrm{KV}}(a)$: Agent Session KV 크기
- $T_{\mathrm{wait}}(a)$: Tool Wait 지속 시간
- $I_a$: 해당 Agent의 Idle KV Residency, 단위는 byte·second

전체 Waiting Agent가 만드는 유휴 점유량은 다음과 같다.

$$
I_{\mathrm{total}}
= \sum_{a \in \mathcal{W}}
S_{\mathrm{KV}}(a) \times T_{\mathrm{wait}}(a)
$$

- $\mathcal{W}$: 현재 Tool Wait 상태인 Agent 집합

Long Context와 높은 Agent Concurrency가 결합되면 다음 현상이 발생한다.

```text
Context Length 증가
        +
Tool Wait Agent 증가
        +
Tool Wait 시간 다변화
        │
        ▼
Idle KV HBM Residency 증가
        │
        ▼
신규 Request Admission 감소
Active Agent용 HBM 부족
HBM Pressure 및 Preemption 증가
```

### 2.3 일반적인 Hotness/LRU만으로는 Agent의 유휴 전환을 즉시 알기 어려움

일반적인 Memory Policy는 최근 접근 시점이나 관측된 Hotness를 이용해 Data가 Cold해졌는지를 판단한다. 그러나 이 방식은 Tool Call 직후에도 일정 시간 동안 해당 KV를 Hot 또는 Warm으로 볼 수 있다.

Agent Runtime은 `TOOL_CALL_ISSUED` Event를 통해 다음 사실을 즉시 알 수 있다.

> **이 Session의 KV는 Tool Result가 도착할 때까지 LLM Compute에서 사용되지 않는다.**

Tool 완료 시각은 알 수 없더라도, 현재 LLM 실행이 중단되었다는 사실은 예측이 아니라 확정된 Runtime State다. 따라서 Tool Call Event를 KV Residency 권한의 전환점으로 사용할 수 있다.

### 2.4 문제 정의

Tool Call 시 모든 KV를 즉시 하위 Tier로 내리면 HBM을 빠르게 확보할 수 있지만, 짧은 Tool Call에서도 불필요한 Demote/Restore가 발생한다. 반대로 모든 Waiting KV를 HBM에 유지하면 Resume는 빠르지만 유휴 KV가 HBM을 계속 점유한다.

> **Tool Wait Agent의 유휴 KV가 차지하는 HBM을 줄이면서도, Tool Result 도착 후 Resume Latency와 불필요한 Data Movement를 제한하는 Residency 관리 구조가 필요하다.**

본 DP의 핵심 Trade-off는 다음과 같다.

$$
\text{Idle KV HBM Residency 감소}
\quad \leftrightarrow \quad
\text{Resume Latency + Migration Traffic}
$$

---

## 3. 대상 Data 범위

### 3.1 핵심 대상: Agent Session KV Cache

일반적인 Transformer 기반 Text Agent에서 Tool Call 이전에 생성되었고, Tool Result 이후 LLM 실행을 이어가기 위해 필요한 대용량 Session 전용 Accelerator State는 KV Cache다.

본 DP의 핵심 최적화 대상은 다음과 같다.

- **Private Session KV**: 특정 Agent Session만 사용하는 Context KV
- **필요한 경우의 확장 KV**: Draft Model KV, Multimodal Cross-Attention KV
- **최소 Runtime Metadata**: KV 위치와 복원을 추적하기 위한 Block Table, Sequence Position, Version

여기서 최소 Runtime Metadata는 용량 최적화 대상이 아니라 KV를 정확하게 Resume하기 위한 Control State다.

### 3.2 Shared Prefix KV

System Prompt 또는 공통 Instruction에 대한 Prefix KV는 여러 Session이 공유할 수 있다. 하나의 Agent가 Tool Wait에 들어갔다는 이유로 공유 Block을 Demote하거나 해제하면 다른 Active Session에 영향을 줄 수 있다.

따라서 다음 규칙을 적용한다.

- Tool-wait Reclaim의 기본 대상은 `Private Session KV`
- Shared Prefix KV는 Reference Count와 다른 Consumer의 상태를 확인
- 다른 Active Consumer가 존재하면 Session 단위 Reclaim 대상에서 제외
- 공유 Block의 별도 Residency Policy는 DP1 또는 Prefix Cache Policy가 담당

### 3.3 기본 대상이 아닌 Data

| Data | 제외 이유 |
|---|---|
| Dense Model Weight | 모든 Request가 공유하며 Tool Wait에 의해 유휴 전환되는 Session State가 아님 |
| 일반 Activation | 수명이 짧고 Tool Wait까지 유지되지 않음 |
| 원본 Conversation Token | 필요하지만 크기가 작고 주로 CPU Memory에 존재 |
| Tool Call Argument | 복원에 필요할 수 있으나 크기가 작음 |
| Tool Result | Tool Wait 중 존재하는 기존 State가 아니라 완료 시 새로 유입되는 입력 |
| Agent Episodic/Semantic Memory | 보통 Vector DB·DRAM·SSD에 있으며 Tool Wait HBM 문제의 직접 대상이 아님 |
| 원본 RAG Document/Embedding | 일반적으로 CPU/Storage에 존재하고 Prompt에 반영된 내용은 KV로 표현됨 |
| LoRA Adapter | Session 실행에 필요할 수 있지만 공유·Cache 정책이 별도로 필요하며 DP1 Data Type으로 다룸 |

### 3.4 용어 정의

본 문서에서 `Agent KV Working Set`은 다음을 의미한다.

> **Agent가 LLM 실행을 재개할 때 필요한 Private Session KV와, 그 위치·Version을 추적하기 위한 최소 Runtime Metadata의 집합**

`Agent Working Set`이라는 표현을 KV, RAG, Agent Memory, Tool Result 전체를 포괄하는 의미로 사용하지 않는다.

---

## 4. DP1 / DP2 / DP4와의 경계

### 4.1 DP1: Physical Data Placement

DP1은 Data Object를 실제 어느 Memory Tier에 둘 것인지 결정한다.

```text
DP3 Output
Residency State = RECLAIMABLE
        │
        ▼
DP1 Decision
HBM 유지 / DRAM Demote / CXL Demote / HBF Demote
```

DP3는 `HBM → CXL`과 같은 물리 Target을 직접 결정하지 않는다. DP3가 결정하는 것은 Agent Lifecycle에 따른 Residency 상태와 Reclaim Priority다.

### 4.2 DP2: Loss-aware KV Drop

DP3의 Hibernation과 DP1의 Demotion은 KV 내용을 보존하는 무손실 동작이다. 하위 Tier까지 활용해도 Capacity/SLO 제약을 만족할 수 없을 때만 DP2가 Importance에 기반한 KV Drop을 검토한다.

```text
DP3: Tool-wait KV를 Reclaimable로 전환
        │
        ▼
DP1: 무손실 Demotion 가능한가?
        │
    ┌───┴───┐
   Yes      No
    │        │
    ▼        ▼
 Demote   DP2 Drop 판단
```

### 4.3 DP4: Migration Execution

DP1이 Target Memory를 결정하면 DP4가 실제 Data Copy, Metadata Commit, Source Release를 수행한다.

| 결정 | 담당 DP |
|---|---|
| Tool Wait 진입에 따라 KV Residency 권한을 바꿀 것인가 | **DP3** |
| Reclaimable KV를 어느 Memory Tier에 둘 것인가 | **DP1** |
| Loss를 허용해 어떤 KV를 Drop할 것인가 | **DP2** |
| KV를 Tier 간 어떻게 이동할 것인가 | **DP4** |

### 4.4 DP3 출력 Interface

```text
AgentKvResidencyIntent
- session_id
- lifecycle_state
- private_kv_blocks
- shared_kv_refs
- residency_class
- reclaim_priority
- resume_priority
- version
```

DP3가 출력하는 `residency_class`는 다음 중 하나다.

- `GUARANTEED`: Active 실행을 위해 상위 Memory Residency 필요
- `REVOCABLE`: 현재 사용되지 않으며 Pressure 발생 시 회수 가능
- `RECLAIM_REQUESTED`: 실제 용량 확보를 위해 DP1 Placement 재평가 필요
- `RESUME_REQUIRED`: Tool Result가 도착하여 상위 Memory 접근성 회복 필요

---

## 5. Lifecycle Event와 상태 모델

### 5.1 관찰 Event

| Event | 의미 | 예측 여부 |
|---|---|---|
| `TOOL_CALL_ISSUED` | LLM 실행이 중단되고 Tool Wait 진입 | 실제 관찰 Event |
| `MEMORY_PRESSURE_HIGH` | 상위 Memory 추가 확보 필요 | 실제 Resource Event |
| `TOOL_RESULT_READY` | Agent가 실행 재개 가능 | 실제 관찰 Event |
| `MIGRATION_COMMITTED` | DP4가 Target Memory 반영 완료 | 실제 완료 Event |
| `RESUME_ADMITTED` | Resume 실행 Resource 확보 | 실제 Scheduler Event |

본 DP는 Tool 완료 시각이나 다음 사용 시각을 예측값으로 사용하지 않는다.

### 5.2 Residency 상태

```text
ACTIVE_GUARANTEED
        │ TOOL_CALL_ISSUED
        ▼
WAIT_RECLAIMABLE
        │ MEMORY_PRESSURE_HIGH
        ▼
RECLAIM_REQUESTED
        │ DP1 Target 결정 + DP4 실행
        ▼
WAIT_DEMOTED
        │ TOOL_RESULT_READY
        ▼
RESUME_REQUIRED
        │ Restore / Remote Access 준비
        ▼
REACTIVATING
        │ RESUME_ADMITTED
        ▼
ACTIVE_GUARANTEED
```

`WAIT_RECLAIMABLE` 상태에서 Tool Result가 먼저 도착하면 KV 이동 없이 바로 `ACTIVE_GUARANTEED`로 복귀할 수 있다.

### 5.3 Event 경합 처리

| 상황 | 처리 원칙 | 성능 영향 |
|---|---|---|
| Tool Result가 Demote 시작 전에 도착 | Reclaim 요청 취소, HBM Residency 복원 | 거의 없음 |
| Tool Result가 Demote 중 도착 | Commit 전이면 Source 사용 또는 Copy 취소, Commit 후면 Restore 우선순위 상승 | Resume 지연 가능 |
| Tool Result가 Demote 완료 후 도착 | `RESUME_REQUIRED`로 전환, DP1/DP4에 Restore 요청 | Restore/Remote Access 비용 |
| Tool Wait 중 Session 종료 | Private KV 해제, Shared KV Reference만 감소 | 해제 처리 비용 |
| Shared Prefix만 Pressure 대상에 포함 | 다른 Consumer 확인 후 제외 또는 별도 정책에 위임 | Candidate 탐색 비용 |

Event 경합으로 Fallback이나 Retry가 발생하더라도 올바른 KV로 실행을 완료하면 그 비용은 Accuracy가 아니라 Performance에 귀속한다.

---

## 6. 설계 쟁점

### 핵심 쟁점

> **Tool Wait 진입 즉시 Session KV를 Hibernation할 것인가, 우선 Reclaimable 상태로만 전환하고 실제 Memory Pressure가 발생할 때 Hibernation할 것인가?**

```text
                 TOOL_CALL_ISSUED
                         │
            ┌────────────┴────────────┐
            ▼                         ▼
     C1. Eager                    C2. Revocable
     Hibernation                   Residency
            │                         │
     즉시 Demote 요청         Reclaimable 표시만 수행
                                      │
                              Memory Pressure 발생 시
                                   Demote 요청
```

두 후보 모두 Tool 완료 시점을 예측하지 않는다. 차이는 실제 Memory Pressure가 발생하기 전에 Data Movement를 선제 수행하는가이다.

---

## 7. C1. Eager Tool-event Hibernation

### 7.1 핵심 아이디어

`TOOL_CALL_ISSUED` Event가 발생하면 해당 Agent의 Private Session KV에 대해 즉시 Hibernation을 요청한다.

```text
TOOL_CALL_ISSUED
        │
        ▼
Private / Shared KV 분리
        │
        ▼
Private KV = RECLAIM_REQUESTED
        │
        ▼
DP1 Target Memory 결정
        │
        ▼
DP4 Demote 실행
        │
        ▼
WAIT_DEMOTED
```

Tool Result가 도착하면 즉시 Restore 또는 허용된 Remote Access 경로로 Agent 실행을 재개한다.

### 7.2 장점

- Tool Wait 진입 직후 HBM Capacity 확보 가능
- Memory Pressure가 급증하기 전에 선제적으로 여유 용량 확보
- Reclaim Candidate 선택 절차가 단순
- Waiting Agent가 많아질수록 확보 가능한 용량이 명확
- Admission 시점의 긴급 Demotion 가능성 감소

### 7.3 단점

- 짧은 Tool Call에서도 Demote/Restore 왕복 발생
- HBM에 여유가 있어도 불필요한 Migration 수행
- Tool Result가 빠르게 도착하면 Resume Latency 증가
- Interconnect, Copy Engine, 하위 Tier BW 사용량 증가
- Tool Call이 반복되는 Agent에서 KV Ping-pong 가능

### 7.4 유리한 환경

- Memory Pressure가 지속적으로 높음
- Waiting Agent의 KV가 크고 동시 Waiting Session이 많음
- 하위 Tier와 Migration BW가 충분함
- Admission Capacity 확보가 Resume Latency보다 중요함

---

## 8. C2. Pressure-triggered Revocable Residency

### 8.1 핵심 아이디어

`TOOL_CALL_ISSUED` 시 Session KV를 즉시 이동하지 않고 HBM Residency 보장만 해제한다. 해당 KV는 `REVOCABLE` Pool에 등록되며 실제 Memory Pressure가 발생할 때 필요한 용량만큼 Reclaim한다.

```text
TOOL_CALL_ISSUED
        │
        ▼
Private KV = REVOCABLE
        │
    ┌───┴─────────────────────┐
    │                         │
Memory Pressure 없음     Memory Pressure 발생
    │                         │
HBM 유지                Reclaim Candidate 선택
    │                         │
Tool Result             필요한 용량만큼 Demote
    │                         │
즉시 Active             WAIT_DEMOTED
```

### 8.2 Residency Lease

Revocable Residency는 Memory Lease로 표현할 수 있다.

| Agent 상태 | Lease | 의미 |
|---|---|---|
| Active | `GUARANTEED` | 실행을 위해 Residency 보장 |
| Tool Wait | `REVOCABLE` | HBM에 남을 수 있지만 필요 시 회수 가능 |
| Reclaim 진행 | `REVOKING` | DP1/DP4가 Demotion 수행 중 |
| Tool Result Ready | `RESUME_REQUIRED` | 상위 Memory 접근성 재확보 요청 |
| Reactivating | `GUARANTEE_PENDING` | Restore 또는 Remote Access 준비 중 |
| Active 복귀 | `GUARANTEED` | Residency 보장 회복 |

### 8.3 Reclaim Candidate 선택

C2는 미래 Tool 완료 시점을 예측하지 않는다. 현재 관측 가능한 다음 값만 사용할 수 있다.

- Session KV Size
- 현재 KV Memory Location
- Demote Cost
- 현재 Memory Pressure와 필요한 확보 용량
- Shared/Private 여부
- 이미 진행 중인 Migration 여부
- 현재 Resume 요청 존재 여부
- Session Priority 또는 SLO Class

Candidate 선택의 목적은 필요한 용량을 최소 Movement Cost로 확보하는 것이다.

$$
R^* = \arg\min_{R \subseteq \mathcal{R}}
\sum_{a \in R} C_{demote}(a)
$$

subject to

$$
\sum_{a \in R} S_{reclaimable}(a) \ge B_{required}
$$

- $\mathcal{R}$: 현재 `REVOCABLE` 상태인 Agent 집합
- $B_{required}$: 현재 Pressure를 해소하기 위해 필요한 용량
- $S_{reclaimable}(a)$: Agent $a$에서 실제 회수 가능한 Private KV 크기

Tool 완료 예상 시간이나 다음 접근 시간은 목적함수에 포함하지 않는다.

### 8.4 장점

- Memory가 실제로 필요할 때만 Data Movement 발생
- 짧은 Tool Call의 불필요한 Demote/Restore 방지
- HBM 여유가 있을 때 빠른 Resume 유지
- Tool Latency Predictor가 필요 없음
- Mixed Tool Duration 환경에서 Migration Traffic 감소 기대

### 8.5 단점

- Pressure 발생 시 Candidate 탐색과 Migration이 Admission 경로에 걸릴 수 있음
- 즉시 확보되는 여유 용량을 보장하지 않음
- Tool Result와 Reclaim Event의 Race 처리 필요
- Waiting Agent가 많으면 Candidate 관리 비용 증가
- 긴급 Pressure에서 C1보다 늦게 용량을 확보할 수 있음

### 8.6 유리한 환경

- 짧고 긴 Tool Call이 혼재
- Memory Pressure가 간헐적으로 발생
- Resume Latency와 Migration Traffic이 중요
- Tool Latency가 크거나 불규칙하여 예측 정책이 불안정

---

## 9. 비교 기준과 Target QA

### 9.1 Functional Correctness를 후보 비교 QA에서 제외

C1과 C2는 KV를 Drop하거나 근사화하지 않고 Memory Location만 변경한다. 따라서 정상 동작한다면 두 후보의 모델 출력 Accuracy는 동일해야 한다.

- Restore/Retry/Fallback 후 올바른 KV로 실행 완료: 추가 비용은 **Performance Efficiency**에 귀속
- 잘못된 KV를 사용하여 Silent Wrong Result 발생: 후보 Trade-off가 아니라 **구현 불변식 위반**
- Accuracy 손실을 허용하는 KV Drop: 본 DP가 아니라 **DP2의 대상**

따라서 본 DP는 Task Accuracy를 후보 선정 Metric으로 사용하지 않는다. 대신 KV byte equality 또는 deterministic replay를 Sanity Check로만 사용한다.

### 9.2 Primary QA: Performance Efficiency

본 DP는 Performance Efficiency 안에서 세 측면을 함께 평가한다.

#### A. Memory / Capacity Efficiency

| Metric | 정의 |
|---|---|
| **M-P1 Idle KV Residency** | Waiting KV의 `bytes × idle duration`, 주 지표 |
| **M-P2 Waiting KV HBM Footprint** | 시점별 Tool-wait Session KV의 HBM 점유량 |
| **M-P3 Reclaimed HBM Capacity** | Agent Lifecycle Signal로 실제 확보한 HBM |
| **M-P4 Admission Goodput** | SLO를 만족하며 수용·완료한 Request/Agent 수 |
| **M-P5 Peak Concurrent Sessions** | 동일 HBM에서 동시에 유지 가능한 Agent Session 수 |

Idle KV Residency는 다음과 같이 측정한다.

$$
M_{\mathrm{P1}}
= \int_{t_0}^{t_1}
B_{\mathrm{waiting\ KV\ in\ HBM}}(t)\,dt
$$

단일 시점의 HBM 사용량이 아니라 유휴 KV가 HBM을 얼마나 오래 점유했는지를 함께 본다.

#### B. Resume / Serving Latency

Tool Result 도착 시각을 $t_{result}$, 이후 첫 Output Token 생성 시각을 $t_{token}$이라 하면:

$$
T_{resume} = t_{token} - t_{result}
$$

| Metric | 정의 |
|---|---|
| **M-P6 Resume Latency** | Tool Result 도착부터 다음 Output Token까지의 시간, p50/p95/p99 |
| **M-P7 Restore Stall** | Resume 경로에서 KV 접근성 회복을 기다린 시간 |
| **M-P8 TTFT Inflation** | Keep-resident Baseline 대비 Resume TTFT 증가 |
| **M-P9 SLO Violation Rate** | Resume 또는 일반 Serving SLO 위반 비율 |
| **M-P10 Active-request Interference** | Reclaim/Restore가 활성 Decode·Prefill에 준 지연 |

#### C. Data Movement / Fallback Cost

| Metric | 정의 |
|---|---|
| **M-P11 Migration Bytes** | Demote + Restore 전체 전송량 |
| **M-P12 Round-trip Ratio** | Demote 후 짧은 시간 안에 Restore된 KV 비율 |
| **M-P13 No-benefit Migration Ratio** | 확보된 용량이 다른 Workload에 사용되기 전에 Restore된 비율 |
| **M-P14 Fallback Rate** | Remote Access, Recompute, Retry 등 Fallback 발생률 |
| **M-P15 Fallback Latency** | Fallback으로 추가된 End-to-End 지연 |
| **M-P16 Decision Overhead** | Lifecycle Event 처리와 Candidate 선택에 든 CPU 시간 |

State 누락이나 Event Race가 검출되어 Retry/Fallback으로 복구된 경우 M-P14와 M-P15에 포함한다.

### 9.3 Secondary QA: Scalability

| Metric | 정의 |
|---|---|
| **M-S1 Event Processing Cost** | 초당 Lifecycle Event 수 증가에 따른 제어 비용 |
| **M-S2 Candidate Lookup Cost** | Waiting Session 수 대비 Reclaim Candidate 선택 시간 |
| **M-S3 State Metadata Footprint** | Session 수 대비 Residency State 관리 Memory |
| **M-S4 Concurrent Resume Handling** | 동시에 Tool Result가 도착할 때 처리 가능한 Resume 수 |
| **M-S5 Node/Tier Scale-out Cost** | Node와 Memory Tier 증가에 따른 State 수집·조정 비용 |

### 9.4 구조적 불변식

다음 항목은 후보별 점수로 비교하지 않고 반드시 만족해야 한다.

1. Drop이 없다면 KV 내용은 보존되어야 한다.
2. Shared Prefix KV는 다른 Consumer가 존재하는 동안 해제하면 안 된다.
3. Metadata가 가리키는 위치에는 읽을 수 있는 완전한 KV 또는 유효한 Fallback 경로가 있어야 한다.
4. Tool Result와 Session KV Version이 일치해야 한다.
5. Reclaim과 Resume가 경합해도 잘못된 KV로 추론을 계속하면 안 된다.
6. Migration 실패 시 검증된 Source 또는 Target으로 복구할 수 있어야 한다.

---

## 10. Baseline과 평가 시나리오

### 10.1 Baseline

| 구성 | 동작 | 목적 |
|---|---|---|
| **B0 Keep-resident** | Tool Wait 중 KV를 계속 HBM에 유지 | 최대 Resume 성능, Memory 비용 상한 |
| **B1 Generic Pressure/LRU** | Agent Lifecycle을 모르고 일반 접근 이력으로 회수 | Agent Event 활용 자체의 기여 분리 |
| **C1 Eager Hibernation** | Tool Call 즉시 Demote | 즉시 Capacity 확보 |
| **C2 Revocable Residency** | Tool Call 시 Mark, Pressure 시 Demote | 불필요한 이동 억제 |

B1이 중요하다. C2가 B1보다 낫지 않다면 `TOOL_CALL_ISSUED`라는 Agent Semantic Signal을 별도로 사용하는 실익이 입증되지 않는다.

### 10.2 평가 시나리오

#### Scenario A. 짧은 Local Tool

- Calculator, Local Function 등 수 ms~수십 ms Tool
- 예상: C1은 Round-trip Traffic과 Resume Latency 증가 가능
- 확인: C2가 KV를 이동하지 않고 빠르게 Active로 복귀하는가

#### Scenario B. 긴 External Tool

- Web Search, Database, Code Execution 등 수백 ms~수 초 Tool
- 예상: Waiting KV의 Idle Residency가 크게 증가
- 확인: C1/C2가 HBM Capacity와 Admission Goodput을 얼마나 개선하는가

#### Scenario C. Mixed Tool Duration

- 짧고 긴 Tool Call을 동일 Trace에 혼합
- 본 DP의 대표 시나리오
- 확인: C1의 즉시 확보 이점과 C2의 Movement 절감 간 교차점

#### Scenario D. Parallel Tool Calls

- 하나의 Agent가 복수 Tool Result를 기다리는 Fan-out/Fan-in 구조
- 확인: 부분 Result 도착과 최종 Resume Event를 정확하게 구분하는가

#### Scenario E. Parent / Sub-agent Wait

- Parent Agent가 Sub-agent 결과를 기다리는 구조
- 확인: Parent KV를 Tool Wait와 동일한 Lifecycle로 관리할 수 있는가

#### Scenario F. Human-in-the-loop / Long Suspension

- 사용자 승인 또는 외부 Event를 장시간 대기
- 확인: 장기 유휴 Session의 HBM 점유 제거 효과

#### Scenario G. Reclaim–Resume Race

- Demote 시작 전, 진행 중, Commit 직후에 Tool Result 도착
- 확인: 불변식 준수 및 Fallback Latency

### 10.3 Sweep 축

- Session KV Size
- Context Length
- Concurrent Active / Waiting Agent 수
- Tool Duration Distribution
- Memory Pressure Level
- HBM Capacity
- Tier 간 Bandwidth와 Latency
- Shared Prefix 비율
- 동시 Tool Result 도착 Burst 크기

Tool Duration은 정책 입력으로 예측하는 값이 아니라, 평가 Trace를 다양화하기 위한 Sweep 축으로만 사용한다.

---

## 11. C1 / C2 예상 Trade-off

| 항목 | C1. Eager Hibernation | C2. Revocable Residency |
|---|---|---|
| HBM Capacity 선제 확보 | **높음** | Pressure 발생 전에는 제한적 |
| 짧은 Tool Call Resume | 불리할 수 있음 | **유리** |
| Migration Traffic | 높음 | **낮음 기대** |
| Admission 시 긴급 Reclaim | **적음** | 발생 가능 |
| 구현 단순성 | **높음** | Event Race 및 Lease 관리 필요 |
| Tool Duration 예측 의존 | 없음 | 없음 |
| Mixed Workload 적응성 | 제한적 | **높음** |
| Candidate 관리 비용 | 낮음 | Waiting Session 증가 시 높아짐 |

후보 우열은 단일 점수로 결론 내지 않는다.

- 동일 Resume SLO에서 Idle KV Residency와 Admission Goodput 비교
- 동일 Admission Goodput에서 Resume Latency와 Migration Bytes 비교
- Memory Pressure와 Tool Duration 분포를 Sweep하여 후보가 교차하는 구간 보고

---

## 12. Runtime 전체 동작 예시

### 12.1 Pressure가 없는 짧은 Tool Call — C2

```text
1. Agent A가 Calculator Tool 호출
2. TOOL_CALL_ISSUED
3. Agent A KV Lease: GUARANTEED → REVOCABLE
4. HBM Pressure 없음 → KV는 HBM에 유지
5. TOOL_RESULT_READY
6. Lease: REVOCABLE → GUARANTEED
7. Migration 없이 Incremental Prefill 재개
```

### 12.2 Pressure가 있는 Tool Wait — C2

```text
1. Agent A가 External Tool 호출
2. Agent A KV = REVOCABLE
3. 신규 Request B 도착, HBM 6 GB 부족
4. ReclaimCoordinator가 Waiting Agent 후보 탐색
5. Agent A Private KV 6 GB를 RECLAIM_REQUESTED로 전환
6. DP1이 Target CXL을 선택
7. DP4가 HBM → CXL Demote
8. Request B Admission
9. Tool Result 도착
10. Agent A = RESUME_REQUIRED
11. DP1/DP4가 CXL → HBM Restore 또는 허용된 Remote Access 준비
12. Agent A 실행 재개
```

### 12.3 Tool Result가 Demote 중 도착

```text
1. Agent A KV Demote 진행 중
2. TOOL_RESULT_READY 발생
3. Residency Manager가 DP4 Migration 상태 확인
4-A. Commit 전: Source HBM이 유효하면 Reclaim 취소 후 Source 사용
4-B. Commit 후: Restore 요청을 High Priority로 등록
5. Retry/Restore로 추가된 시간은 Resume Latency와 Fallback Latency에 집계
6. 올바른 KV가 준비된 뒤 실행 재개
```

---

## 13. 구조적 구성 요소

| Component | 책임 |
|---|---|
| `AgentLifecycleObserver` | Tool Call, Tool Result, Session 종료 Event 수집 |
| `AgentKvRegistry` | Session별 Private/Shared KV 및 Version 추적 |
| `ResidencyLeaseManager` | GUARANTEED/REVOCABLE/RESUME_REQUIRED 상태 관리 |
| `ReclaimCoordinator` | Pressure 발생 시 필요한 용량과 Candidate 결정 |
| `ResumeCoordinator` | Tool Result 이후 Restore/Remote Access/Admission 조정 |
| `Dp1PlacementAdapter` | Residency Intent를 DP1 Placement 요청으로 변환 |
| `Dp4MigrationAdapter` | DP4 Migration 상태와 완료 Event 수신 |

### Candidate별 차이

- C1은 `TOOL_CALL_ISSUED` 시 `ReclaimCoordinator`를 즉시 호출한다.
- C2는 `TOOL_CALL_ISSUED` 시 `ResidencyLeaseManager`만 갱신하고, `MEMORY_PRESSURE_HIGH`에서 `ReclaimCoordinator`를 호출한다.
- 나머지 DP1/DP4 연동과 Resume 경로는 동일하게 유지한다.

---

## 14. 실패 처리의 QA 귀속

| 상황 | 정상 처리 | QA 귀속 |
|---|---|---|
| KV가 이미 Demote되어 Resume 대기 | Restore 또는 Remote Access | Resume Latency, Performance Efficiency |
| Reclaim과 Tool Result Race | Cancel/Retry/우선 Restore | Fallback Rate·Latency, Performance Efficiency |
| Target Capacity 부족 | 다른 Tier 재선택 또는 Admission 대기 | Queue/Resume Latency, Performance Efficiency |
| Migration 실패 | Source 유지 또는 Rollback 후 Retry | Fallback Latency, Performance Efficiency |
| KV를 찾지 못했지만 Token History 존재 | Full/Partial Recompute | Recompute Cost, Performance Efficiency |
| 잘못된 KV로 추론 계속 | 허용하지 않음 | 구조적 불변식 위반, 비교 대상 제외 |

Fallback으로 정확한 결과를 복원한 실행은 Accuracy 손실로 집계하지 않는다. 대신 Fallback이 추가한 시간과 Resource Cost를 Performance Metric에 포함한다.

---

## 15. 평가 및 판정 원칙

1. 모든 정책은 동일한 Request Arrival, Tool Call, Tool Result Trace를 사용한다.
2. 정책이 미래 Tool Duration이나 Result Arrival Time을 보지 못하게 한다.
3. Accuracy는 후보 비교 지표로 사용하지 않되, KV 보존 여부를 Sanity Check한다.
4. `B0 Keep-resident`는 Resume Latency 하한과 Memory 사용량 상한으로 사용한다.
5. `B1 Generic Pressure/LRU`와 비교하여 Agent Lifecycle Signal 자체의 효과를 분리한다.
6. 평균뿐 아니라 Resume Latency p95/p99와 Tool Result Burst 상황을 보고한다.
7. 신뢰구간이 0을 지나면 후보 차이가 없다고 판정한다.
8. 단일 Tool Duration이나 단일 Pressure 값으로 후보를 선정하지 않고 Sweep 교차 구간을 보고한다.

### 조건부 선정 예시

- Memory Pressure가 지속적이고 Admission Capacity가 최우선인 구간: C1이 유리할 수 있음
- 짧고 긴 Tool이 혼재하고 Pressure가 간헐적인 구간: C2가 유리할 수 있음
- 두 후보 모두 B1보다 개선되지 않는 구간: Agent Lifecycle 전용 정책을 도입할 근거 없음

---

## 16. 최종 연구 가설

> **Tool Call Event를 Session KV의 Residency Lease 전환점으로 사용하면, Tool 완료 시간을 예측하지 않고도 일반적인 Hotness/LRU 정책보다 Waiting Agent의 Idle KV HBM Residency를 줄일 수 있다. 또한 실제 Memory Pressure가 발생할 때만 KV를 회수하는 Revocable Residency는 즉시 Hibernation보다 불필요한 Migration과 Resume Latency를 줄일 수 있으며, 그 대가로 Pressure 발생 시점의 Candidate 선택 및 긴급 Reclaim 비용을 지불한다.**

본 가설은 다음 세 질문으로 검증한다.

1. Agent Tool Wait의 KV Idle Residency가 전체 HBM 점유에서 유의미한 비중을 차지하는가?
2. Tool Lifecycle Event를 활용하는 정책이 일반 Pressure/LRU보다 SLO-constrained Goodput을 높이는가?
3. Eager Hibernation과 Revocable Residency의 우열이 Memory Pressure와 Tool Duration 분포에 따라 어느 구간에서 교차하는가?
