# QA Evaluation Criteria

> 적용 범위: **DP1 ~ DP4 공통**
>
> 목적: 각 Design Point의 후보 구조를 동일한 기준으로 비교할 수 있도록 공통 QA 정의, 별점 기준, Evidence Level을 관리한다.
>
> DP2/DP3/DP4 설계가 진행되면서 기존 QA로 설명하기 어려운 품질 속성이 확인되면 **새 QA를 이 문서에 추가**한다. 현재 QA1~QA4는 출발점이며 최종 고정 집합은 아니다.

---

# 1. Evaluation Principle

현재 공통 QA는 다음 여섯 가지다.

1. **QA1 — Performance / Throughput**
2. **QA2 — Performance / Latency**
3. **QA3 — Resource Utilization**
4. **QA4 — Modifiability**
5. **QA5 — Reliability** (§12, Fault tolerance 측정. 2026-10-06 추가)
6. **QA6 — Scalability** (§13, Scaling Efficiency. 2026-10-06 추가)

QA5·QA6의 정의가 §12·§13에 있는 것은 기존 §번호 참조를 유지하기 위해서다.

향후 필요하면 Functional Correctness, Decision Latency, Implementation Complexity 등의 QA를 추가할 수 있다.

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

> 상태: **추가(결과 확인 전 사전 정의, 2026-10-06), 같은 날 단일 sub-characteristic으로 재정의**. §9 형식을 따른다. 별점 경계는 **임시 정의**(H8)이며 사용자 확정 전까지 proposal이다. 결과를 본 뒤 바꾸지 않는다(§11-1).
> 재정의 이유: 첫 판의 Fault-injection Pass Rate는 Faultlessness·Fault tolerance·Recoverability·Availability를 한 값에 섞어 어떤 sub를 재는지 불분명했다. 이전 판은 git history에 있다.
> 기준: ISO/IEC 25010:2023의 Reliability. Functional Correctness(AI 모델 정확도, 예: KV 압축의 F1)와는 **별개의 QA**이며 섞어 쓰지 않는다.

## 12.1 QA Name

**Reliability** — 이 과제에서는 sub-characteristic **Fault tolerance**를 측정한다. 구성요소 실패나 장애가 있어도 시스템이 의도한 대로 서비스를 계속하는 정도.

## 12.2 Motivation

일부 DP는 평상시 성능이 아니라 **장애가 났을 때 서비스가 얼마나 유지되는가**가 구조 선택의 핵심이다. 예를 들어 이기종 메모리 간 migration 실행에서는 복사 실패, 목적지 할당 실패, Worker 중단이 일어나도 서빙이 멈추지 않아야 한다. 이는 정상 상태 성능(QA1~QA3)으로 드러나지 않는다.

## 12.3 Sub-characteristic 선택

| Sub-characteristic | 이 QA에서의 취급 |
|---|---|
| **Fault tolerance** | **선택 — 점수의 대상.** 장애 중에도 서비스가 유지되는 정도를 재는 것이 QA5의 metric(§12.4)이다 |
| Recoverability | 별점에 쓰지 않음. 관측 구간(§12.4의 W)에 복구 시간이 포함되어 FTR에 반영되고, 복구 시간·손실은 진단으로 보고한다 |
| Faultlessness | 별점에 쓰지 않음. **선결 조건(제약)** 으로 처리한다(§12.7). 선언한 불변식을 위반하는 후보는 점수가 낮은 것이 아니라 평가에서 탈락한다. DP0가 정확도 불변을 QA가 아닌 제약 C3으로 둔 것과 같은 방식이다 |
| Availability | 선택하지 않음. 장애 구간의 SLO 만족 처리량은 FTR이 이미 포함한다 |

Faultlessness를 점수로 두지 않는 이유: 올바르게 구현한 후보는 모두 위반 0건이라 후보를 구분하지 못하고, 위반이 있는 후보는 점수와 무관하게 선택할 수 없기 때문이다.

## 12.4 Metric: Fault-tolerance Retention (FTR)

DP별 **장애 시나리오 집합 FS**를 결과 전에 사전 등록한다. 각 시나리오 s에 대해 장애를 주입한 실행과 장애 없는 실행을 같은 부하·같은 구간 길이로 짝지어 측정한다.

~~~text
FTR(s) = SLO Goodput(장애 주입 후 관측 구간 W)
         / SLO Goodput(장애 없는 같은 구간)

FTR    = FTR(s)의 기하평균 (§10 규칙 2)
~~~

- **SLO Goodput**은 QA1 정의(SLO를 위반한 request의 output token 제외)를 따른다.
- **W**는 장애를 주입한 시점부터 사전 등록한 고정 길이이며 복구 완료 여부와 무관하다. 복구가 늦으면 W 안의 degraded 시간이 길어져 FTR이 낮아지므로 Recoverability의 영향이 자연스럽게 반영된다.
- FS의 시나리오는 결과를 본 뒤 삭제·추가하지 않으며, 실패한 시나리오도 모두 보고한다(H4와 같은 원칙). 시나리오별 FTR과 **최소값(min FTR)** 을 함께 보고한다. 한 시나리오에서 서비스가 완전히 멈추면(FTR = 0) 기하평균이 0이 되어 그대로 드러난다.
- **Baseline**은 같은 장애를 As-Is 구조에 주입한 FTR이며 결과표에 Baseline 열로 둔다(§10).
- 같은 QA는 같은 metric이어야 하므로 DP가 달라도 FTR 정의는 같다. DP별로 달라지는 것은 FS(장애 종류)와 W뿐이다.

## 12.5 Unit

% (0~100).

## 12.6 ★ / ★★ / ★★★ Threshold (임시 정의)

| Score | FTR |
|---|---|
| ★ | < 70% |
| ★★ | 70% ~ 90% |
| ★★★ | >= 90% |

근거: 환산이다. 장애 구간에서 SLO를 만족하는 처리량의 손실이 10% 이내인지(★★★), 30%를 넘는지(★)로 구분한 것이며 정책 선택으로 남는 부분이다. 측정에 근거한 경계가 아니므로 확정 전에 Baseline 대 Baseline 잡음(같은 장애 시나리오를 겹치지 않는 seed 묶음으로 반복)을 측정해 하한이 잡음보다 큰지 확인한다(evaluation skill §10).

## 12.7 선결 조건 (Faultlessness, 점수 아님)

- 각 DP가 **불변식 목록**을 결과 전에 사전 등록한다(예: migration 실행이라면 stale read 없음, use-after-free 없음, 단일 authoritative location, 복사 중 lost update 없음).
- 모든 FS 시나리오와 정상 실행에서 위반 **0건**이어야 FTR을 평가한다.
- 위반이 있으면 그 후보는 "선택 불가"로 결과 문서에 기록하고 FTR 별점을 매기지 않는다. 위반 사실과 재현 시나리오는 삭제하지 않는다.
- 확인 방법: protocol model check(추상 모델에서 interleaving 탐색, 결함 변종을 심어 검출 확인)와 fault-injected stress.

## 12.8 Measurement Methodology

1. 장애 종류와 주입 시점을 FS로 사전 등록한다(예: 복사 전, 복사 중, commit 직전, commit 직후 source 해제 전, 목적지 할당 실패, 전송 타임아웃, coordinator·Worker 중단).
2. 시뮬레이션 또는 실제 runtime에서 장애 주입 실행과 장애 없는 실행을 같은 seed·부하로 짝지어 측정한다(seed >= 5, 중앙값과 95% CI).
3. 성능 비용(일관성 보장으로 늘어난 지연 등)은 QA1·QA2에서 따로 보고한다. QA5 값에 섞지 않는다(H20과 같은 원칙).

## 12.9 Applicable DP

| DP | 적용 | 비고 |
|---|---|---|
| Migration 실행 DP (번호 개편 후 DP2) | **적용** | FS: 복사·할당 실패, Worker·coordinator 중단 등 |
| DP0 (서버 간 요청 조율) | 검토 대상 | 조율 계층 장애 시 서비스 유지. 현재 장애 규약을 QA 목록 밖으로 두었음. OSS 확장(HA 제공) vs 자체 구현이 후보를 가를 수 있음 |
| Prefill/Decode 실행 계획 DP (번호 개편 후 DP3) | 검토 대상 | plan 실패·stale 시 기본 실행으로 fallback. C2에만 있는 invalidation/re-plan 경로가 후보를 가를 수 있음 |
| Data migration 결정 DP (DP1) | 비적용 | 결정 품질이 대상. 실행 중 장애는 Migration 실행 DP의 책임 |
| KV 압축·재사용 DP | 비적용 | 품질 손실은 Functional Correctness(정확도)로 다룸 |

적용 여부는 각 DP의 `qa-criteria-dpn.md`에서 사용자 결정으로 확정한다.

## 12.10 Evidence type

- 시뮬레이션 기반 장애 주입, model check: **[C]** (시뮬레이터 입력이 config parameter이면 [B+C])
- 실제 runtime 장애 주입: **[A]**
- 현재 DP1 시뮬레이터에는 장애 모델이 없다. 사용하려면 시뮬레이터에 장애 주입 기능을 추가해야 하며(M class 변경, 근거와 수정 전후 값 기록), 추가 전까지 FTR은 산출하지 않는다.

## 12.11 Diagnostic metrics

- min FTR과 시나리오별 FTR
- 복구 시간 P50/P99 (장애 주입부터 정상 처리량 복귀까지)
- 복구 불가능한 손실량(recomputable 여부 구분)
- 장애 영향 범위(영향 받은 request 수)
- 선결 조건 점검 결과(불변식 위반 건수와 유형)
- 장애 구간 가용성(SLO 만족 request 비율, 참고용)

---

# 13. QA6 — Scalability

> 상태: **추가(결과 확인 전 사전 정의, 2026-10-06)**. §9 형식을 따른다. 별점 경계는 DP4 초안과 DP0 요구사항이 사용한 값을 가져온 **임시 정의**이며 사용자 확정 전까지 proposal이다.
> 기준: ISO/IEC 25010:2023의 Flexibility / Scalability. 과제 공통 정의 Scaling Efficiency(DP0 요구사항 Q4, DP4 초안)를 그대로 사용한다.

## 13.1 QA Name

**Scalability** — 자원 규모와 부하를 함께 늘렸을 때 처리량이 선형에 얼마나 가깝게 늘어나는가.

## 13.2 Motivation

일부 DP는 중앙 제어 지점(직렬화된 commit, 단일 authority, 락)이 규모가 커질 때 병목이 되는지가 구조 선택을 가른다. 이는 작은 규모의 QA1·QA2 결과에서는 보이지 않는다.

## 13.3 Metric: Scaling Efficiency

~~~text
SE(N) = Goodput(N) / ( (N / N0) × Goodput(N0) )
~~~

- **Goodput**은 QA1의 Max SLO Goodput이다(각 N에서 load sweep으로 구한 최대값).
- **N**은 DP가 사전 등록하는 **확장 축**(확장하는 자원의 수)이고 **N0**는 기준 규모다. 확장 단위당 부하는 고정하고 N에 비례해 총 부하를 늘린다.
- 대표값은 **측정한 최대 규모의 SE(N_max)** 이다. 전체 곡선 SE(N)도 함께 보고한다.
- 같은 QA는 같은 metric이어야 하므로 DP가 달라도 식은 같다. DP별로 달라지는 것은 N의 축과 범위뿐이다.

## 13.4 Unit

% (100%가 선형 확장).

## 13.5 ★ / ★★ / ★★★ Threshold (임시 정의)

| Score | SE(N_max) |
|---|---|
| ★ | < 70% |
| ★★ | 70% ~ 90% |
| ★★★ | >= 90% |

DP4 초안의 제안 경계와 같다. 근거는 환산이며 측정된 근거가 아니다. 경계 근처 값은 결과 문서에 민감도로 보고한다.

## 13.6 Measurement Methodology

1. DP가 확장 축 N과 범위를 사전 등록한다.
2. N마다 단위당 부하를 고정하고 load sweep으로 Max SLO Goodput을 구한다(seed >= 5, 중앙값과 95% CI).
3. 곡선이 꺾이는 지점의 병목(제어 지점 점유율, 큐 대기)을 진단 지표로 보고한다.
4. 보유 규모를 넘는 N은 외삽이며 [C]로 표기한다.

## 13.7 Applicable DP

| DP | 적용 | 확장 축 N (제안) |
|---|---|---|
| Migration 실행 DP (번호 개편 후 DP2) | **적용** | GPU Worker 수 1, 2, 4, 8 (단일 노드 한계, DP1 제약 C-S1). 보조 진단 축: 동시 in-flight migration 수, 관리 object 수 |
| DP0 (서버 간 요청 조율) | 적용 | 서버·노드 수 (DP0 요구사항 Q4가 이미 같은 정의 사용) |
| Prefill/Decode 실행 계획 DP (번호 개편 후 DP3) | 검토 대상 | 노드 수. DP4 초안이 적용 DP로 기재했던 항목 |
| Data migration 결정 DP (DP1) | 비적용 | — |
| KV 압축·재사용 DP | 비적용 | — |

## 13.8 Evidence type

- Migration 실행 DP는 단일 서버의 GPU 8장 범위에서 N = 1~8을 실제로 측정할 수 있다. migration 실행 prototype이 있으면 **[A]**, 시뮬레이션이면 **[B+C]**.
- 보유 규모를 넘는 N(다중 노드 등)은 외삽이므로 **[C]**.

## 13.9 Diagnostic metrics

- N별 Max SLO Goodput와 SE 곡선
- 제어 지점(EngineCore authority, location store commit)의 CPU 점유율과 큐 대기 시간 P99
- 제어 지점이 SLO를 깨기 시작하는 offered load(포화 지점)
- N별 migration commit 처리량(commits/s)
