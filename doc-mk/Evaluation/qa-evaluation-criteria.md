# QA Evaluation Criteria

> 적용 범위: **DP1 ~ DP4 공통**
>
> 목적: 각 Design Point의 후보 구조를 동일한 기준으로 비교할 수 있도록 공통 QA 정의, 별점 기준, Evidence Level을 관리한다.
>
> DP2/DP3/DP4 설계가 진행되면서 기존 QA로 설명하기 어려운 품질 속성이 확인되면 **새 QA를 이 문서에 추가**한다. 현재 QA1~QA4는 출발점이며 최종 고정 집합은 아니다.

---

# 1. Evaluation Principle

현재 공통 QA는 다음 네 가지다.

1. **QA1 — Performance / Throughput**
2. **QA2 — Performance / Latency**
3. **QA3 — Resource Utilization**
4. **QA4 — Modifiability**

향후 필요하면 Scalability, Decision Latency, Robustness/Stability, Availability, Implementation Complexity 등의 QA를 추가할 수 있다.

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

| QA | Candidate 1 | Candidate 2 |
|---|---|---|
| Throughput | ★★ xxxx TPS [A] | ★★★ xxxx TPS [A+C] |
| Latency | ★★ TTFT / TPOT [A] | ★★★ TTFT / TPOT [A+C] |
| Resource Utilization | ★★★ xx% [A+C] | ★★ xx% [A+C] |
| Modifiability | ★★★ [C] | ★★ [C] |

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
