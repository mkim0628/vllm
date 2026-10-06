# QA Evaluation Criteria

> 적용 범위: **DP1 ~ DP4 공통**
>
> 목적: 각 Design Point의 후보 구조를 동일한 기준으로 비교할 수 있도록 공통 QA 정의, 별점 기준, Evidence Level을 관리한다.
>
> DP2/DP3/DP4 설계가 진행되면서 기존 QA로 설명하기 어려운 품질 속성이 확인되면 **새 QA를 이 문서에 추가**한다. 현재 QA1~QA4는 출발점이며 최종 고정 집합은 아니다.

---

# 1. Evaluation Principle

현재 공통 QA는 다음 다섯 가지다.

1. **QA1 — Performance / Throughput**
2. **QA2 — Performance / Latency**
3. **QA3 — Resource Utilization**
4. **QA4 — Modifiability**
5. **QA5 — Reliability** (§12, 2026-10-06 추가. 정의 위치가 §12인 것은 기존 §번호 참조를 유지하기 위해서다)

향후 필요하면 Scalability, Functional Correctness, Decision Latency, Implementation Complexity 등의 QA를 추가할 수 있다. Availability·Robustness 성격의 평가는 QA5의 sub-characteristic으로 다룬다.

각 QA 결과는 QA Score와 Evidence Level을 분리한다.

~~~text
QA Score        Evidence Level
★★★             [A]
★★              [B]
★★★             [B+C]
~~~

- **별점 = 결과가 얼마나 좋은가**
- **A/B/C = 그 결과를 어떤 종류의 근거로 산출했는가**

Evidence Level이 C라고 해서 별점을 자동으로 낮추지 않는다. 대신 projection uncertainty와 validation 범위를 함께 명시한다.

---

# 2. Evidence Level

## 2.1 A — Actual Measurement

실제 보유 HW와 실제 SW runtime에서 직접 측정한 값.

예:
- A100 / H100
- Host DRAM / SSD
- PCIe / NVLink
- 실제 vLLM / llm-d execution
- 실제 migration / communication microbenchmark
- 실제 decision overhead

가능한 경우 A를 가장 우선한다.

권장 측정 원칙:

~~~text
동일 SW revision
동일 model / precision
동일 workload
동일 parallelism / deployment configuration
고정 warm-up
Runs >= 5
Median
P95 / P99
95% CI
CV
~~~

## 2.2 B — Literature / Published Value

실제 HW나 시스템을 보유하지 않을 때 논문, 공개 benchmark, vendor specification 등에서 얻은 값.

대상 예:
- 미보유 GPU
- CXL Memory
- PIM / PNM
- HBF
- Custom HBM

문헌값 우선순위:

~~~text
B1: 동일 HW + 동일/유사 model + 동일/유사 workload의 공개 benchmark
B2: 동일 HW의 다른 LLM / 다른 workload benchmark
B3: Vendor / paper의 HW specification
~~~

B 값은 source와 측정 조건을 반드시 함께 기록한다.

## 2.3 C — Projection / Analytical Argument

직접 실측할 수 없는 configuration을 A/B 값을 입력으로 모델링하거나 논증하여 얻은 값.

~~~text
Measured runtime trace [A]
+
Published target-HW parameter [B]
+
Analytical / simulation model
        ↓
Projected result [C]
~~~

C 결과에는 사용한 model, input source, calibration 대상, validation error, sensitivity range, uncertainty를 기록한다.

---

# 3. QA Score and Evidence are Independent

예:

~~~text
Throughput       ★★★ [A]
Latency          ★★  [A]
Resource Util.   ★★★ [A+C]
Modifiability    ★★  [C]
~~~

Projection uncertainty가 있으면:

~~~text
Throughput       ★★★ [C, ±8%]
~~~

처럼 표기한다.

---

# 4. QA1 — Performance / Throughput

## 4.1 Metric: Max SLO Goodput

단위는 **output token/s**.

각 load / concurrency point에서:

~~~text
SLO Goodput(load)
=
SLO를 만족한 request의 output tokens
/ measurement time
~~~

그리고:

~~~text
Max SLO Goodput
=
load / concurrency sweep에서 측정한
SLO Goodput의 최대값
~~~

Raw Throughput과 달리 **SLO를 위반한 request의 output token은 Goodput 계산에서 제외**한다.

## 4.2 Why Goodput?

| Offered Load | Raw Throughput | SLO 만족 비율 | SLO Goodput |
|---:|---:|---:|---:|
| 낮음 | 500 tok/s | 100% | 500 tok/s |
| 중간 | 1,000 tok/s | 100% | 1,000 tok/s |
| 높음 | 1,400 tok/s | 98% | 1,372 tok/s |
| 과부하 | 1,700 tok/s | 50% | 850 tok/s |

Raw Throughput만 보면 과부하 상태가 가장 높지만, 절반의 request가 latency SLO를 만족하지 못한다. 따라서 사용자 요구 latency를 지키면서 제공 가능한 처리량인 SLO Goodput을 사용한다.

Goodput도 load에 따라 증가하다 saturation 이후 감소할 수 있으므로 그 중 최대값인 **Max SLO Goodput**을 사용한다.

## 4.3 Rating Criterion

Common Reference Baseline의 Max SLO Goodput을 T_ref라 한다.

| Score | Criterion |
|---|---|
| ★ | < 0.90 × T_ref |
| ★★ | 0.90 × T_ref ~ 1.10 × T_ref |
| ★★★ | >= 1.10 × T_ref |

Common Benchmark 실측 후 absolute TPS 경계도 기록한다. Threshold는 결과를 본 뒤 임의 조정하지 않는다.

---

# 5. QA2 — Performance / Latency

Latency는 **TTFT와 TPOT을 분리**해서 평가한다.

| Score | TTFT P99 | TPOT P99 |
|---|---:|---:|
| ★ | > 4 s 또는 > 100 ms | |
| ★★ | <= 4 s | <= 100 ms |
| ★★★ | <= 2 s | <= 50 ms |

두 metric 중 하나만 높은 등급을 만족하면 더 낮은 등급을 적용한다.

결과 표에서는 TTFT와 TPOT를 **별도 행**으로 보고하고 각각 Baseline 대비 배수를 병기한다(§10).

DP별 queue delay, decision latency, migration stall, prefill latency, KV restore latency, tool-resume latency 등은 diagnostic metric으로 추가할 수 있다.

---

# 6. QA3 — Resource Utilization

공통 원칙:

> **SLO를 만족시키면서 사용 가능한 heterogeneous resource를 얼마나 효율적으로 활용하는가**

| Score | Useful Resource Utilization |
|---|---:|
| ★ | < 65% |
| ★★ | 65 ~ 85% |
| ★★★ | >= 85% |

SLO violation이나 과도한 migration/communication으로 얻은 높은 utilization은 useful utilization으로 보지 않는다.

DP별 세부 metric 예:

### DP1
- HBM / DRAM / CXL / HBF occupancy
- aggregate memory-pool utilization
- pressure relief efficiency
- migration BW / bytes

### DP2
- Prefill node utilization
- Decode node utilization
- GPU idle ratio
- inter-node KV transfer utilization

DP3/DP4도 해당 DP가 제어하는 resource pool에 맞는 세부 metric을 정의한다.

---

# 7. QA4 — Modifiability

신규 Memory / Data Type / Policy / Device가 추가되었을 때 기존 구조에 필요한 변경 범위를 평가한다.

| Score | Change Impact |
|---|---|
| ★ | >= 6 modules 또는 major interface 변경 |
| ★★ | 3 ~ 5 modules 변경 |
| ★★★ | <= 2 modules, 기존 주요 interface 유지 |

보조 측정:
- modified modules
- modified interfaces
- LOC / token change
- new dependency
- existing test impact
- new type-specific branch 수

Modifiability는 주로 **C — architecture argument / static analysis**로 평가하며, 실제 prototype이 있으면 A evidence를 보조적으로 사용할 수 있다.

---

# 8. Common Benchmark Profile

QA1/QA2의 absolute 기준을 calibration하기 위한 공통 Reference Benchmark Profile 초기안:

~~~text
Model        : Llama-3.1-70B
Precision    : BF16
Input        : 8K tokens
Output       : 256 tokens
Prefix reuse : baseline에서는 제거 / 통제
Workload     : deterministic distribution
Load         : request-rate / concurrency sweep
~~~

기본 SLO:

~~~text
TTFT P99 <= 2 s
TPOT P99 <= 50 ms
~~~

Serving framework와 deployment topology는 DP마다 달라질 수 있으므로 **각 DP Simulation/Evaluation 문서에서 정의**한다.

예:

~~~text
DP1 : vLLM 중심
DP2 : llm-d + vLLM worker 중심
DP3 : 해당 DP runtime
DP4 : Agent framework + serving runtime
~~~

---

# 9. Adding a New QA

새 QA를 추가할 때 최소한 다음을 정의한다.

~~~text
QA Name
1. Motivation
2. Metric
3. Unit
4. ★ / ★★ / ★★★ threshold
5. Measurement methodology
6. Applicable DP
7. Evidence type: A / B / C
8. Diagnostic metrics
~~~

특정 DP에만 필요한 QA라면 Applicable DP를 명시한다.

---

# 10. Final Result Format

최종 결과는 **QA별 정량 metric 값**으로 표현하고, 괄호 안에 **Baseline 대비 배수**를 적는다. 별점은 값 옆에 병기하며 Evidence 등급을 붙인다.

| QA | 평가 metric | Baseline (T_ref) | Candidate 1 | Candidate 2 |
|---|---|---:|---|---|
| QA1 Throughput | Max SLO Goodput (tok/s) ↑ | xxxx | ★★ xxxx (x1.30) [B+C] | ★★★ xxxx (x1.42) [B+C] |
| QA2 Latency (TTFT) | TTFT P99 (ms) ↓ | xxxx | xxxx (x0.80) | xxxx (x0.60) |
| QA2 Latency (TPOT) | TPOT P99 (ms) ↓ | xx | xx (x1.00) | xx (x0.95) |
| QA2 별점 | TTFT와 TPOT를 모두 반영한 별점 | — | ★★★ [B+C] | ★★★ [B+C] |
| QA3 Resource Utilization | DP별 metric (예: DP1 HBM 사용량 GiB ↓) | xxx | ★★ xxx (x0.97) [B+C] | ★ xxx (x1.21) [B+C] |
| QA4 Modifiability | 변경 module 수 / 공수 / 에이전트 비용 | — | ★★★ x / x / $x [C] | ★★ x / x / $x [C] |

표 아래에 **평가한 시스템**을 반드시 적는다: SYS id, GPU/HBM 세대, host link, 탑재 메모리, model/precision, 집계 단위(시나리오 수, 비교 가능 쌍 수).

규칙:
1. **괄호 = 후보 값 ÷ Baseline 값**(배수)이다. ↑는 높을수록 좋은 metric, ↓는 낮을수록 좋은 metric이다. 괄호를 "개선 배수"로 바꿔 쓰면 안 되며, 필요하면 별도 행에 "개선 배수(Baseline ÷ 후보)"라고 명시한다.
2. 여러 시나리오나 시스템을 합칠 때는 **쌍별 값의 기하평균(geometric mean)**을 쓴다. 기하평균은 값의 비가 곱셈으로 보존되므로 표의 절대값과 괄호의 배수가 서로 모순되지 않는다.
3. **Latency는 TTFT와 TPOT를 별도 행으로 보고**한다(§5). 별점은 별도 행에 둘 수 있다.
4. QA별 metric이 DP마다 다를 수 있으나(QA3 등) 표 형식(metric 열, Baseline 열, 괄호 배수, 시스템 표기)은 모든 DP에 같다.
5. Baseline이 정의되지 않는 metric(QA4 등)은 `—`로 표기한다.

---

# 11. Key Rules

1. **평가 기준을 결과보다 먼저 정의한다.**
2. **같은 QA에는 DP 간 동일한 의미와 rating rule을 적용한다.**
3. **새로운 품질 속성이 필요하면 QA를 추가한다.**
4. **A/B/C Evidence는 별점과 분리한다.**
5. **실측 가능한 값은 최대한 A를 사용한다.**
6. **B 값은 source와 measurement condition을 기록한다.**
7. **C projection은 calibration / validation / uncertainty를 기록한다.**
8. **Common QA와 DP-specific diagnostic metric을 구분한다.**
9. **Common Benchmark와 DP-specific experiment methodology를 구분한다.**
10. **구체적인 simulation/runtime 구조는 각 DP 문서에서 관리한다.**
11. **결과는 정량 metric 값 + (Baseline 대비 배수) + 평가 시스템 표기로 보고한다(§10).**

---

# 12. QA5 — Reliability

> 상태: **추가(결과 확인 전 사전 정의, 2026-10-06)**. §9 형식을 따른다. 별점 경계는 **임시 정의**(H8)이며 사용자 확정 전까지 proposal이다. 결과를 본 뒤 바꾸지 않는다(§11-1).
> 기준: ISO/IEC 25010:2023의 Reliability. Functional Correctness(AI 모델 정확도, 예: KV 압축의 F1)와는 **별개의 QA**이며 섞어 쓰지 않는다.

## 12.1 QA Name

**Reliability** — 결함·장애·동시성 경쟁이 있어도 시스템이 상태를 올바르게 유지하고, 장애 후 정상 상태로 돌아오는 정도.

## 12.2 Motivation

일부 DP는 성능이 아니라 **상태 일관성과 장애 처리**가 구조 선택의 핵심이다. 대표적으로 이기종 메모리 간 data migration 실행은 이동 중 접근, 복사 실패, 부분 commit이 있어도 stale read·use-after-free·이중 소유가 없어야 한다. 이 속성은 QA1~QA4로 표현되지 않으며, 위반은 "낮은 점수"가 아니라 **선택 불가**에 해당한다.

## 12.3 Sub-characteristic 선택

QA5는 ISO의 네 sub-characteristic을 공통 어휘로 쓰고, **DP마다 해당하는 것만 선택**해 결과 전에 `DPn/qa-criteria-dpn.md`에 등록한다.

| Sub-characteristic | 이 QA에서의 의미 | 측정 (진단) | 선택 가능한 DP |
|---|---|---|---|
| **Faultlessness** | 정상 동작과 동시성 경쟁 하에서 선언한 불변식 위반이 없다 | 불변식 위반 건수(유형별) | 일관성 상태를 가지는 DP |
| **Fault tolerance** | 복사·할당·전송 실패나 구성요소 장애가 있어도 의도한 대로 계속 동작하고 영향이 선언한 범위에 머문다 | 장애 영향 범위(영향 받은 request 수), 오답 응답 수 | 장애 경로를 설계한 DP |
| **Recoverability** | 중단·실패 후 일관된 상태로 복귀하고 직접 영향받은 data를 복구한다 | 복구 시간 P50/P99, 복구 불가능한 손실(recomputable 여부 구분) | rollback/재계획 경로가 있는 DP |
| **Availability** | 필요할 때 서비스가 사용 가능하다 | 장애 구간에서 SLO를 만족한 request 비율(%) | 단일 장애점이 후보 차이를 만드는 DP |

Availability는 다른 sub와 겹치기 쉽다. 장애 중 서비스 지속은 Fault tolerance가, 이동·대기로 인한 지연은 QA2가 다루므로, **구성요소 중단이 서비스 중단으로 이어지는 구조(예: 단일 장애점, HA 유무)가 후보를 가르는 DP에서만** 선택한다.

## 12.4 Metric: Fault-injection Pass Rate (FPR)

DP별 **장애·경쟁 시나리오 집합 FS**를 결과 전에 사전 등록한다. 각 시나리오 s는 아래를 **모두** 만족하면 통과(pass)다. 선택하지 않은 sub-characteristic의 조건은 적용하지 않는다.

~~~text
P1 (Faultlessness)   선언한 불변식 위반 0건
P2 (Fault tolerance) 장애 영향이 사전 선언한 범위 안이고, 범위 밖 request는 정상 처리되며 오답 응답이 없다
P3 (Recoverability)  사전 선언한 복구 bound 이내에 일관된 정상 상태로 복귀하고, 복구 불가능한 손실이 0이다
P4 (Availability)    장애 구간의 SLO 만족 request 비율 >= 사전 선언한 하한
~~~

~~~text
FPR = 통과한 시나리오 수 / FS의 전체 시나리오 수
~~~

- 불변식 목록, 영향 범위, 복구 bound, 가용성 하한은 DP별 문서가 결과 전에 정한다. 결과를 본 뒤 바꾸지 않는다.
- 실패한 시나리오를 삭제하거나 숨기지 않는다(H4와 같은 원칙).
- 같은 시나리오 안에서 장애 주입 시점을 바꿔 여러 번 실행한다(예: migration이라면 복사 전, 복사 중, commit 직전, commit 직후 source 해제 전).

## 12.5 Unit

% (통과 시나리오 / 전체 시나리오). 진단 단위는 건수, ms(복구 시간), bytes(손실), request 수(영향 범위), %(가용성).

## 12.6 ★ / ★★ / ★★★ Threshold (임시 정의)

불변식 위반은 정의상 허용 불가이므로 위반 여부를 먼저 가르고, 그 다음에 통과율을 본다.

| Score | Criterion |
|---|---|
| ★ | 불변식 위반 1건 이상 (**gate 탈락**, 결과 문서에 "선택 불가"로 명시) |
| ★★ | 위반 0건, FPR < 100% |
| ★★★ | 위반 0건, FPR = 100% |

경계가 이산적(위반 여부, 전수 통과 여부)이라 Baseline 잡음 기반 하한(evaluation skill §10)을 적용하지 않는다. 대신 FS가 충분한지(주입 시점, 장애 종류의 커버리지)를 결과 문서 한계에 적는다. FS가 좁으면 ★★★은 약한 주장이다.

## 12.7 Measurement Methodology

1. **protocol model check**: 추상 모델에서 가능한 interleaving을 탐색해 불변식을 검증한다. 결함 변종을 심어 검출되는지 확인한다.
2. **fault-injected 시뮬레이션/stress**: 장애 종류와 주입 시점을 바꿔 seed >= 5로 실행한다.
3. **실제 runtime 장애 주입**: 가능한 경로(예: HBM↔host 복사 실패, Worker 중단)는 실제 vLLM에서 주입한다.
4. 성능 영향은 QA1·QA2에서 따로 보고한다. 일관성 보장 비용을 QA5 값에 섞지 않는다(H20과 같은 원칙).

## 12.8 Applicable DP

| DP | 적용 | 선택 sub (제안) | 비고 |
|---|---|---|---|
| Migration 실행 DP (번호 개편 후 DP2) | **적용** | Faultlessness, Fault tolerance, Recoverability | 이동 중 접근 일관성, 복사 실패, rollback. Availability는 제외 |
| DP0 (서버 간 요청 조율) | 검토 대상 | Fault tolerance, Availability | 조율 계층 단일 장애점과 HA 유무가 후보(OSS 확장 vs 자체 구현)를 가를 수 있음. DP0는 현재 장애 규약을 QA 목록 밖으로 두었음 |
| Prefill/Decode 실행 계획 DP (번호 개편 후 DP3) | 검토 대상 | Fault tolerance | stale plan·실패 시 기본 실행으로 fallback하는 경로가 있고 C2에서만 필요한 invalidation/re-plan이 있음 |
| Data migration 결정 DP (DP1) | 비적용 | — | 결정 품질이 대상. 실행 중 일관성은 Migration 실행 DP의 책임 |
| KV 압축·재사용 DP | 비적용 | — | 품질 손실은 Functional Correctness(정확도)로 다룸 |

적용 여부는 각 DP의 `qa-criteria-dpn.md`에서 사용자 결정으로 확정한다.

## 12.9 Evidence type

- model check, fault-injected 시뮬레이션: **[C]** (시뮬레이터 입력이 config parameter이면 [B+C])
- 실제 runtime 장애 주입: **[A]**
- 모델의 한계(추상화 수준, 주입한 장애 종류)는 결과 문서 한계에 명시한다.

## 12.10 Diagnostic metrics

- 불변식 위반 건수(stale read, use-after-free, lost update, 이중 소유, orphan 등 유형별)
- 장애 영향 범위(영향 받은 request 수, 오답 응답 수)
- 복구 시간 P50/P99, 복구 불가능한 손실량(recomputable 여부 구분)
- 장애 구간 가용성(%)
- 시나리오별 통과/실패 목록
