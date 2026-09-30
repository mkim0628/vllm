# Common QA Evaluation Criteria & Simulation Plan

> 적용 범위: **DP1 ~ DP4 공통**
>
> 목적: 각 Design Point의 후보 구조를 동일한 QA 기준으로 비교하고,
> 실제 HW가 존재하는 경우에는 **실측(A)**,
> HW/시스템을 직접 보유하지 않는 경우에는 **문헌(B)** 및 **Projection/논증(C)** 을 조합하여
> 일관된 방식으로 평가한다.
>
> 본 문서의 별점 기준과 benchmark profile은 **결과를 보기 전에 먼저 정의하고 freeze**하는 것을 원칙으로 한다.

---

# 1. Evaluation Principle

DP1~DP4의 후보 구조는 다음 네 QA를 공통으로 사용한다.

1. **Performance Efficiency — Throughput**
2. **Performance Efficiency — Latency**
3. **Resource Utilization**
4. **Modifiability**

각 QA 결과는 두 개의 정보를 분리해서 표현한다.

~~~text
QA Score        Evidence Level
★★★             [A]
★★              [B]
★★★             [B+C]
~~~

즉,

- **별점 = 결과가 얼마나 좋은가**
- **A/B/C = 그 결과의 근거가 얼마나 직접적인가**

를 의미한다.

Evidence Level이 C라고 해서 별점을 자동으로 낮추지 않는다.
대신 결과 옆에 Evidence Level과 projection uncertainty를 명시한다.

---

# 2. Evidence Level

## 2.1 A — Actual Measurement

실제 보유 HW와 실제 SW runtime에서 직접 측정한 값.

예:

- A100 / H100
- Host DRAM
- SSD
- PCIe / NVLink
- 실제 vLLM serving
- 실제 migration microbenchmark
- 실제 DP decision overhead

가능한 경우 가장 우선한다.

### 측정 원칙

- 동일 SW revision
- 동일 model / precision
- 동일 prompt/output distribution
- 동일 parallelism
- 동일 warm-up
- 반복 측정
- 평균/중앙값뿐 아니라 tail latency와 변동성 기록

권장:

~~~text
Runs >= 5
Median
P95 / P99
95% CI
CV (Coefficient of Variation)
~~~

---

## 2.2 B — Literature / Published Value

실제 HW를 보유하지 않을 때 공개 문헌 또는 제품 specification에서 얻는 값.

대상 예:

- B100 등 미보유 GPU
- CXL Memory
- PNM / PIM
- HBF
- Custom HBM

문헌값은 가능한 한 다음 순서로 신뢰도를 구분한다.

~~~text
B1
동일 HW + 동일/유사 model + 동일/유사 serving workload의 공개 benchmark

B2
동일 HW의 다른 LLM / 다른 serving benchmark

B3
Vendor / paper의 HW specification
(BW, latency, capacity, FLOPS 등)
~~~

B 값은 source와 조건을 반드시 함께 기록한다.

---

## 2.3 C — Projection / Analytical Argument

직접 실측할 수 없는 configuration을
A/B 값을 입력으로 하여 모델링하거나 analytical projection한 값.

예:

~~~text
Measured H100 runtime trace [A]
+
Published B100 HW parameter [B]
+
Analytical model
        ↓
B100 projected throughput / latency [C]
~~~

C 결과에는 반드시 다음을 함께 기록한다.

- 사용한 식/model
- A/B input source
- calibration 대상
- validation error
- sensitivity range / uncertainty

---

# 3. QA Score and Evidence are Independent

최종 표기는 다음처럼 한다.

~~~text
Throughput       ★★★ [A]
Latency          ★★  [A]
Resource Util.   ★★★ [A+C]
Modifiability    ★★  [C]
~~~

또는 projection error가 있으면:

~~~text
Throughput       ★★★ [C, ±8%]
~~~

Evidence Level은 QA Score와 독립적으로 표현한다.

---

# 4. Common QA Criteria

아래 기준은 **초기 기준안**이다.

Throughput의 절대 TPS 경계는 H100 vLLM baseline을 실측한 뒤
Common Benchmark Profile 기준으로 최종 숫자를 freeze한다.

## 4.1 QA1 — Performance / Throughput

### Metric

**Max SLO Goodput**

단위:

~~~text
output token/s
~~~

정의:

~~~text
각 load / concurrency point에서

SLO(TTFT, TPOT)를 만족한 request의
output token만 Goodput으로 인정한다.

SLO Goodput(load)
=
SLO를 만족한 request의 output tokens
/ measurement time

Max SLO Goodput
=
load / concurrency sweep에서 측정한
SLO Goodput의 최대값
~~~

즉 단순 Throughput과 달리 SLO를 위반한 request의 output token은
Goodput 계산에서 제외한다.

초기 relative 기준:

| Score | Criterion |
|---|---|
| ★ | < 0.90 × Reference Baseline |
| ★★ | 0.90 ~ 1.10 × Reference Baseline |
| ★★★ | >= 1.10 × Reference Baseline |

### Absolute TPS 기준

Phase 0의 H100 vLLM baseline을 실측한 뒤 다음 식으로 freeze한다.

~~~text
T_ref = H100 Common Benchmark Profile의
        Max SLO Goodput (output token/s)

★      < 0.90 * T_ref
★★     0.90 * T_ref ~ 1.10 * T_ref
★★★    >= 1.10 * T_ref
~~~

즉 별점 표에는 최종적으로 실제 TPS 숫자를 기록한다.

---

# 5. Why "Max SLO Goodput"?

QA1에서는 단순 Throughput이 아니라 **Goodput**을 사용한다.

- **Throughput**: SLO 만족 여부와 관계없이 실제 처리한 전체 output token/s
- **SLO Goodput**: SLO를 만족한 request의 output token만 인정한 token/s
- **Max SLO Goodput**: load / concurrency sweep에서 얻은 SLO Goodput 중 최대값

예:

| Offered Load | Throughput | SLO 만족 비율 | SLO Goodput |
|---:|---:|---:|---:|
| 낮음 | 500 tok/s | 100% | 500 tok/s |
| 중간 | 1,000 tok/s | 100% | 1,000 tok/s |
| 높음 | 1,400 tok/s | 98% | 1,372 tok/s |
| 과부하 | 1,700 tok/s | 50% | 850 tok/s |

단순 Throughput만 보면 과부하 구간의 1,700 tok/s가 가장 높다.
하지만 절반의 request가 SLO를 위반하므로 실제 유효 처리량은 850 tok/s다.

따라서 QA1은 다음을 사용한다.

~~~text
Goodput(load)
=
SLO를 만족한 request의 output tokens
/ measurement time

Max SLO Goodput
=
max_load Goodput(load)
~~~

여기서 **Max**가 필요한 이유는 Goodput도 load / concurrency에 따라 달라지기 때문이다.
낮은 부하에서는 SLO를 잘 만족하지만 처리량 자체가 낮고,
부하를 높이면 Goodput이 증가하다가 saturation 이후 SLO violation 때문에 다시 감소할 수 있다.

따라서 **Max SLO Goodput은 시스템이 실제 SLO를 지키면서 제공할 수 있는 최대 유효 처리량**을 의미한다.

# 6. QA2 — Performance / Latency

Latency는 TTFT와 TPOT을 분리해서 본다.

초기 공통 기준:

| Score | TTFT P99 | TPOT P99 |
|---|---:|---:|
| ★ | > 4 s 또는 > 100 ms | |
| ★★ | <= 4 s | <= 100 ms |
| ★★★ | <= 2 s | <= 50 ms |

후보가 하나의 metric만 만족하는 경우 낮은 등급을 적용한다.

필요 시 DP별 latency decomposition은 별도 보조 metric으로 둔다.

예:

- queue delay
- migration stall
- decision latency
- prefill latency
- restore latency
- tool-resume latency

하지만 **공통 QA Score는 TTFT / TPOT 기준을 유지**한다.

---

# 7. QA3 — Resource Utilization

단순 GPU utilization 하나가 아니라,
**SLO를 만족시키면서 실제로 활용된 heterogeneous resource의 useful utilization**을 평가한다.

초기 기준:

| Score | Useful Resource Utilization |
|---|---:|
| ★ | < 65% |
| ★★ | 65 ~ 85% |
| ★★★ | >= 85% |

DP별 세부 metric은 달라질 수 있다.

예:

### DP1

- HBM occupancy
- DRAM/CXL/HBF occupancy
- aggregate memory-pool utilization
- migration bytes
- migration BW
- pressure relief efficiency

### DP2

- Prefill node utilization
- Decode node utilization
- idle GPU capacity
- cross-node KV transfer

### DP3 / DP4

해당 DP의 실제 resource pool을 동일 원칙으로 측정한다.

공통 원칙은 다음과 같다.

> **높은 utilization 자체가 목적이 아니라,
> SLO를 유지하면서 사용 가능한 자원을 얼마나 효율적으로 활용하는가를 본다.**

---

# 8. QA4 — Modifiability

신규 Memory / Data Type / Policy / Device가 추가되었을 때
기존 구조에 필요한 변경 범위를 평가한다.

초기 기준:

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
- new data-type-specific branch 수

Modifiability는 HW 성능과 달리 대부분 **C — architecture argument / static analysis**로 평가한다.

실제 prototype을 구현한 경우 A 성격의 구현 증거를 함께 기록할 수 있다.

---

# 9. Common Benchmark Profile

DP1~DP4의 공통 별점 기준을 calibration하기 위해
고정된 Reference Benchmark를 사용한다.

초기안:

~~~text
Model        : Llama-3.1-70B
Precision    : BF16
Serving      : vLLM
GPU          : H100 / A100 실제 보유 HW
Parallelism  : HW에 맞는 동일한 TP policy
Input        : 8K token reference profile
Output       : 256 tokens
Prefix reuse : baseline에서는 제거/통제
Workload     : fixed deterministic distribution
Load         : request-rate / concurrency sweep
~~~

SLO:

~~~text
TTFT P99 <= 2 s
TPOT P99 <= 50 ms
~~~

Phase 0에서 H100 실측 후
Throughput 별점의 absolute TPS threshold를 freeze한다.

> QA1의 TPS는 raw Throughput이 아니라 **Max SLO Goodput의 output token/s**를 의미한다.

---

# 10. vLLM-based Evaluation Strategy

가능한 영역은 standalone simulator가 아니라
**실제 vLLM runtime을 measurement anchor로 사용**한다.

전체 구조:

~~~text
                    vLLM
                      │
              EngineCore / Scheduler
                      │
          ┌───────────┴────────────┐
          │                        │
   Runtime Event Tap          Metrics Collector
          │                        │
          │                 TPS / TTFT / TPOT
          │                 request state
          │                 KV usage
          │
          ▼
     DP Evaluation Harness
          │
      ┌───┴────┐
      ▼        ▼
     C1        C2
      │        │
      └───┬────┘
          ▼
 Migration Decision
          │
   ┌──────┴───────┐
   ▼              ▼
Real Executor   Sim Executor
[A]             [B/C]
   │              │
   └──────┬───────┘
          ▼
 Common QA Evaluator
~~~

---

# 11. vLLM Measurement Boundary

실제 vLLM에서 가능한 부분은 최대한 A로 가져온다.

## 11.1 Actual Runtime Trace

- request arrival
- prompt tokens
- output tokens
- running / waiting requests
- scheduler queue state
- KV allocation / usage
- prefix-cache information
- request completion
- TTFT / TPOT

## 11.2 Actual HW Metrics

- GPU utilization
- HBM occupancy
- HBM bandwidth proxy / profiler metric
- PCIe/NVLink transfer BW
- Host DRAM usage
- storage IO
- actual memcpy latency/bandwidth

## 11.3 DP Decision Overhead

DP policy 자체는 실제 Python/C++ implementation을 실행하여
decision time을 A로 측정할 수 있다.

---

# 12. Shadow Mode

DP 기능 전체를 vLLM에 바로 구현하지 못하는 경우
먼저 **Shadow Mode**로 평가한다.

~~~text
Actual vLLM Execution
        │
        ├──────────── actual serving
        │
        └──────────── event copy
                         │
                         ▼
                  DP Shadow Policy
                         │
                         ▼
              hypothetical decision
~~~

실제 runtime trace [A] 위에
DP decision을 overlay하고,
지원하지 않는 migration path의 cost는 B/C model로 계산한다.

---

# 13. Partial Real Execution

실제 HW로 가능한 경로는 simulation하지 않고 직접 측정한다.

예:

~~~text
HBM <-> Host DRAM
GPU <-> Host transfer
SSD <-> Host
~~~

가능하다면 Migration cost [A] 로 사용한다.

실제 장치가 없는 경우:

~~~text
CXL / HBF / Custom HBM / PNM

Published HW parameter [B]
        +
Calibrated model [C]
~~~

로 대체한다.

하나의 DP evaluation 안에서도 evidence가 섞일 수 있다.

~~~text
vLLM scheduling / request trace        [A]
HBM -> DRAM transfer                   [A]
CXL transfer BW                        [B]
CXL migration impact                   [B+C]
Custom HBM attention execution         [B+C]
DP policy decision time                [A]
~~~

---

# 14. Projection Calibration Strategy

Projection model의 신뢰도를 확보하기 위해
**보유한 A100 / H100을 cross-validation에 사용한다.**

## Step A — Calibration

~~~text
A100 Actual Measurement
        ↓
Model parameter calibration
~~~

## Step B — Blind Projection

H100 실측값을 사용하지 않고:

~~~text
A100 calibrated model
+
H100 public HW parameter
        ↓
H100 prediction
~~~

을 계산한다.

## Step C — Validation

~~~text
H100 prediction
       vs
H100 actual measurement
~~~

비교 metric:

- Throughput error
- TTFT error
- TPOT error
- transfer time error
- utilization error

## Step D — Unsupported HW Projection

H100까지 validation한 model을 이용하여:

~~~text
H100 Actual [A]
+
B100 / CXL / HBF / cHBM parameter [B]
        ↓
Calibrated Projection [C]
~~~

을 수행한다.

최종 C 결과에는 H100 validation에서 관찰된 error range를 함께 표기한다.

---

# 15. Simulation / Evaluation Execution Order

## Phase 0 — Common QA Criteria Freeze

1. QA1~QA4 definition 확정
2. A/B/C Evidence definition 확정
3. Common Benchmark Profile 확정
4. SLO 확정
5. 별점 relative threshold 확정

이 단계까지는 **benchmark 결과를 보지 않고 결정**한다.

## Phase 1 — A100 / H100 vLLM Baseline

실제 vLLM에서 baseline serving을 실행한다.

측정:

- request throughput
- output token throughput
- TTFT P50/P99
- TPOT P50/P99
- HBM usage
- GPU utilization
- scheduler state
- KV usage

Load / concurrency sweep으로
**Max SLO Goodput**을 찾는다.

이 결과로 QA1의 TPS absolute threshold를 freeze한다.

## Phase 2 — HW Microbenchmark

Serving benchmark와 별도로 component cost를 측정한다.

~~~text
HBM / GPU
Host DRAM
PCIe
NVLink
SSD
~~~

측정:

- memcpy BW / latency
- transfer size별 BW
- concurrent transfer interference
- CPU overhead
- memory allocation overhead

이 값은 C projection의 calibration input이 된다.

## Phase 3 — vLLM Trace Collection

vLLM runtime에서 DP simulation에 필요한 trace를 수집한다.

~~~text
timestamp
request
prompt/output tokens
scheduler state
data object event
KV allocation
resource state
latency
~~~

Synthetic workload가 아니라
실제 vLLM event를 simulator가 replay할 수 있게 한다.

## Phase 4 — DP Shadow Evaluation

각 DP 후보를 실제 trace에 적용한다.

예: DP1

~~~text
vLLM Actual Trace
       │
       ├──────── C1 Resource-driven Migration
       │
       └──────── C2 Behavior-driven Migration
~~~

실제 지원 가능한 operation은 A,
지원되지 않는 path는 B/C cost model을 사용한다.

## Phase 5 — A100/H100 Projection Cross-validation

A100으로 calibration한 C model이
H100 actual result를 얼마나 잘 예측하는지 검증한다.

허용 error band를 정한다.

예:

~~~text
<= 10% : projection confidence high
10~20% : usable with explicit uncertainty
> 20%  : model refinement required
~~~

이 threshold 역시 실제 결과를 보기 전에 가능하면 먼저 고정한다.

## Phase 6 — Unsupported HW Projection

검증된 model로 다음 target을 평가한다.

- B100
- CXL Memory
- HBF
- Custom HBM
- PIM / PNM
- future heterogeneous memory combination

Evidence는 [B+C] 로 표기한다.

---

# 16. Common Benchmark vs DP-specific Stress Benchmark

DP1~DP4 모두 동일 benchmark만 사용하면
각 DP가 해결하려는 문제를 충분히 노출하지 못한다.

따라서 평가 workload를 두 층으로 나눈다.

## 16.1 Common Benchmark

목적:

> **DP1~DP4의 QA 별점을 같은 축에서 비교**

공통 model / request profile / SLO를 사용한다.

## 16.2 DP-specific Stress Benchmark

목적:

> **해당 DP 구조의 trade-off와 failure mode 분석**

예:

### DP1

- HBM capacity pressure
- bandwidth pressure
- data hotness flip
- mixed AI Data
- promotion/demotion
- migration storm

### DP2

- Prefill / Decode imbalance
- previous-turn KV locality
- Prefill-node vs Decode-node execution
- migration cost
- queue congestion
- stale plan

### DP3

- 32K / 128K / 512K long context
- KV eviction
- cache reuse
- context working-set pressure

### DP4

- Agent tool wait
- short / medium / long tool latency
- KV residency
- repeated tool-call lifecycle
- resume latency

DP-specific stress 결과는
공통 QA score를 보조하는 **trade-off evidence**로 사용한다.

---

# 17. DP1-specific Evaluation Adaptation

현재 DP1은 initial placement가 아니라 **runtime migration decision**이다.

따라서:

~~~text
Common Initial Placement
        ↓
Actual vLLM / Trace
        ↓
Event
        ↓
Migration Scheduler
        │
   ┌────┴────┐
   ▼         ▼
  C1         C2
Resource   Behavior
Driven     Driven
   │         │
   └────┬────┘
        ▼
Migration Decision
        ▼
Real / Sim Executor
~~~

C1/C2는 반드시 동일 initial state와 동일 runtime trace를 사용한다.

---

# 18. DP1 Metrics

## Performance

- Max SLO Goodput
- TTFT P99
- TPOT P99
- migration-induced stall
- event-to-decision latency

## Resource

- HBM occupancy
- aggregate memory-pool utilization
- tier imbalance
- migration bytes
- migration BW
- migration count
- promotion count
- demotion count

## C1-specific Diagnostic

- pressure detection
- pressure relief bytes
- victim size
- eviction churn

## C2-specific Diagnostic

- prediction hit / miss
- hot object upper-tier residency
- unnecessary promotion
- unnecessary demotion
- migration thrashing
- predictor overhead

Diagnostic metric은 QA score와 분리해서 원인 분석에 사용한다.

---

# 19. Final Result Format

| QA | C1 | C2 |
|---|---|---|
| Throughput | ★★ xxxx TPS [A] | ★★★ xxxx TPS [A+C] |
| Latency | ★★ TTFT / TPOT [A] | ★★★ TTFT / TPOT [A+C] |
| Resource Utilization | ★★★ xx% [A+C] | ★★ xx% [A+C] |
| Modifiability | ★★★ [C] | ★★ [C] |

Projection 결과 예:

~~~text
B100
Throughput = xxxx TPS
Evidence   = [B+C]
Projection uncertainty = ±x%
~~~

---

# 20. Execution Checklist

1. **Common QA criteria 문서 freeze**
2. **A100/H100 vLLM baseline harness 작성**
3. **Load/concurrency sweep**
4. **H100 Max SLO Goodput 측정**
5. **QA1 absolute TPS 별점 threshold freeze**
6. **HW microbenchmark 작성/실행**
7. **vLLM runtime trace collector 작성**
8. **DP simulator를 trace-replay 구조로 연결**
9. **DP1 C1/C2 Shadow Mode 평가**
10. **A100 -> H100 projection cross-validation**
11. **Projection error range 확정**
12. **B100/CXL/HBF/cHBM B/C projection**
13. **Common Benchmark + DP-specific Stress 결과 정리**
14. **QA Score + Evidence Level 최종 표 작성**

---

# 21. Key Rules

1. **평가 기준을 결과보다 먼저 정의한다.**
2. **DP1~DP4의 Common QA Score 기준은 동일하다.**
3. **A/B/C는 별점과 분리한다.**
4. **실측 가능한 값은 최대한 A를 사용한다.**
5. **Simulation은 가능한 한 실제 vLLM trace를 입력으로 사용한다.**
6. **Initial placement와 runtime migration을 섞지 않는다.**
7. **지원하지 않는 HW는 B+C로 평가한다.**
8. **C model은 A100/H100 cross-validation 후 사용한다.**
9. **Projection에는 uncertainty를 표시한다.**
10. **Common Benchmark와 DP-specific Stress Benchmark를 분리한다.**
