# DP1 Simulation & Evaluation Plan

> 대상: **DP1 — AI Data Migration**
>
> 이 문서는 DP1의 실제 평가/시뮬레이션 방법만 정의한다.
> QA 정의와 별점 기준은 별도 문서
> **doc-mk/Evaluation/qa-evaluation-criteria.md**를 따른다.
>
> **문서 범위 (Evaluation 폴더 통합 후)**: 이 문서는 DP1의 평가/시뮬레이션 *방법*만 다룬다.
> 공통 규칙은 [QA 기준](../qa-evaluation-criteria.md), [Common Benchmark](../common-benchmark.md), [System Spec (SYS-id)](../system-specs.md),
> DP1 시나리오 정의는 [benchmark.md](benchmark.md), 결과는 [results/](results/), 폴더 안내는 [README](../README.md)를 본다.
>
> DP2/DP3/DP4의 실행 환경과 simulation methodology는 각각 별도 문서로 작성한다.
> 특히 DP2는 llm-d 기반 scheduling/execution 구조를 사용하므로 본 DP1 simulation 구조를 그대로 재사용하지 않는다.

---

# 1. DP1 Evaluation Goal

현재 DP1은 **initial placement**가 아니라 runtime의 **AI Data Migration Decision**을 다룬다.

따라서 평가의 핵심 질문은 다음과 같다.

### C1 — Resource State-driven Migration + Data-Memory Affinity

~~~text
Memory resource pressure / trend를 보고
언제 migration이 필요한지 판단하고,

type-agnostic Data Object Registry에서
위치 / 크기 / tier를 조회하여

generic eviction policy로 victim을 선택했을 때
성능과 resource utilization이 어떻게 달라지는가?
~~~

### C2 — AI Data Behavior-driven Migration

~~~text
type-aware Data Object Registry와
runtime access / reuse / lifetime behavior를 분석하여

future behavior를 예측하고
promotion / demotion을 수행했을 때
성능과 resource utilization이 어떻게 달라지는가?
~~~

C1/C2는 반드시 동일 workload, 동일 initial state, 동일 runtime trace, 동일 HW configuration에서 비교한다.

---

# 2. DP1 Evaluation Architecture

가능한 부분은 standalone synthetic simulator가 아니라 **실제 vLLM runtime을 measurement anchor로 사용**한다.

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
      DP1 Evaluation Harness
          │
      ┌───┴────┐
      ▼        ▼
     C1        C2
Resource   Behavior
Driven     Driven
      │        │
      └───┬────┘
          ▼
 Migration Decision
          │
   ┌──────┴────────┐
   ▼               ▼
Real Executor    Sim Executor
[A]              [B/C]
   │               │
   └───────┬───────┘
           ▼
      QA Evaluator
~~~

---

# 3. Evidence Strategy for DP1

DP1은 하나의 실험에서도 A/B/C가 혼합될 수 있다.

~~~text
vLLM request/scheduler trace          [A]
H100/A100 HBM usage                   [A]
HBM <-> Host DRAM transfer            [A]
SSD / Host path                       [A]

CXL BW / latency                      [B]
HBF parameter                         [B]
Custom HBM parameter                  [B]

CXL migration impact                  [B+C]
Custom HBM execution impact           [B+C]
future heterogeneous-memory result    [B+C]

DP1 policy decision overhead          [A]
~~~

A/B/C의 정의와 최종 표기 방식은 공통 QA Evaluation Criteria 문서를 따른다.

---

# 4. Common Initial Placement

DP1은 migration 구조이므로 C1/C2가 각자 initial placement를 결정하면 안 된다.

공통 allocator 또는 동일한 recorded initial state를 사용한다.

~~~text
Common Initial Placement
        ↓
vLLM Runtime / Recorded Trace
        ↓
Runtime Event
        ↓
Migration Scheduler
        │
   ┌────┴────┐
   ▼         ▼
  C1         C2
        ↓
Migration Decision
~~~

Initial placement 결과는 DP1 score에 포함하지 않는다.

---

# 5. vLLM Actual Measurement

실제 보유 GPU에서는 가능한 범위를 최대한 **vLLM 위에서 A evidence로 측정**한다.

## 5.1 Target HW

우선순위:

~~~text
A100
H100
~~~

보유하지 않은 GPU / memory device는 B/C로 확장한다.

## 5.2 vLLM Baseline

공통 benchmark profile은 qa-evaluation-criteria.md를 따른다.

DP1 실행환경 예:

~~~text
Serving      : vLLM
Model        : Llama-3.1-70B
Precision    : BF16
GPU          : A100 / H100
Input        : Common Benchmark Profile
Output       : Common Benchmark Profile
Load         : request-rate / concurrency sweep
~~~

측정:

- request throughput
- output token throughput
- Max SLO Goodput
- TTFT P50/P99
- TPOT P50/P99
- running requests
- waiting requests
- KV cache usage
- HBM usage
- GPU utilization

---

# 6. vLLM Runtime Trace

DP1 simulator가 synthetic event만 보는 것이 아니라 가능하면 실제 vLLM trace를 replay하게 한다.

수집 후보:

~~~text
timestamp
request_id
prompt_tokens
output_tokens
request arrival / completion
scheduler running/waiting
KV allocation / release
KV block / object identity
prefix cache event
HBM occupancy
GPU utilization
resource pressure
TTFT
TPOT
~~~

DP1-specific data object가 vLLM 내부에서 직접 표현되지 않는 경우 trace schema에서 logical object로 mapping한다.

---

# 7. Event-driven DP1 Shadow Mode

전체 heterogeneous-memory migration을 vLLM에 즉시 구현하기 어렵기 때문에 1차 단계는 **Shadow Mode**로 수행한다.

~~~text
Actual vLLM Execution
        │
        ├──────── actual serving
        │
        └──────── runtime event copy
                         │
                         ▼
                 Migration Scheduler
                         │
                   ┌─────┴─────┐
                   ▼           ▼
                  C1           C2
                   │           │
                   └─────┬─────┘
                         ▼
                Migration Decision
                         │
                   no real action
~~~

예:

~~~text
Actual:
KV/object B17 stays in HBM

Shadow C1:
B17 HBM -> DRAM demotion

Shadow C2:
B24 DRAM -> HBM promotion
~~~

이 decision을 실제 trace에 overlay하고 migration cost는 A 또는 B/C 모델로 계산한다.

---

# 8. C1 Simulation Model

~~~text
Event
  ↓
Migration Scheduler
  ↓
Resource State Monitor
  ↓
Resource-based Trend Analyzer
  ↓
Data Eviction Manager
  ↔
Type-agnostic Data Object Registry
(location / size / tier)
  ↓
Eviction Policy
  ↓
Data-Memory Affinity Mapper
  ↓
Destination Tier Selector
  ↓
Migration Data Selector
  ↓
Migration
~~~

## C1 Registry Constraint

C1 Registry는 다음만 안다.

~~~text
object_id
size
location
tier
movable/pin state
~~~

다음 정보는 C1 Registry에 넣지 않는다.

- KV / LoRA / MoE / Agent Memory 같은 data type
- hotness
- reuse probability
- lifetime prediction

Victim 선택은 generic eviction policy로 수행한다.

예:
- LRU
- age
- size
- pressure relief efficiency

Static Data-Memory Affinity는 Registry가 아니라 별도 Mapper / configuration hint로 취급한다.

---

# 9. C2 Simulation Model

~~~text
Event
  ↓
Migration Scheduler
  ↓
Data Behavior Monitor
  ↔
Type-aware Data Object Registry
  ↓
Behavior-based Trend Analyzer
  ↓
Future Behavior Predictor
  ↓
Destination Tier Selector
  ↓
Migration Data Selector
  ↓
Promotion / Demotion
~~~

C2 Registry는 다음과 같은 data class별 metadata를 관리할 수 있다.

- KV Cache
- RAG Data
- Agent Memory
- Tool Result
- LoRA Adapter
- MoE Expert
- Vector Index Cache

Behavior Monitor는 실제 runtime event를 이용해:

- access frequency
- reuse interval
- idle time
- lifetime stage
- hotness trend

를 계산한다.

---

# 10. Partial Real Execution

실제 HW에서 지원 가능한 migration path는 projection보다 직접 측정한다.

예:

~~~text
HBM <-> Host DRAM
GPU <-> Host
SSD <-> Host
~~~

측정 후보:

- transfer BW
- transfer latency
- size sensitivity
- concurrent transfer interference
- CPU overhead
- allocation/free overhead

가능한 경우 Migration Cost [A]로 사용한다.

---

# 11. Unsupported Memory Projection

실제 장치가 없는 경우:

- CXL
- HBF
- Custom HBM
- PIM / PNM
- future memory

는 다음처럼 평가한다.

~~~text
Published Parameter [B]
      +
Calibrated Transfer/Execution Model
      ↓
Projected DP1 Impact [C]
~~~

필요한 입력:

- capacity
- effective BW
- latency
- topology
- GPU reachability
- supported primitive
- compute capability
- contention
- write behavior

---

# 12. A100 / H100 Calibration & Cross-validation

Projection model을 실제 HW에 맞춰 calibration한다.

## Step 1 — A100 Actual

~~~text
A100 vLLM Actual Measurement
        ↓
model calibration
~~~

## Step 2 — H100 Blind Projection

H100 실측 결과를 사용하지 않고:

~~~text
A100 calibrated model
+
H100 HW parameter
        ↓
H100 prediction
~~~

을 수행한다.

## Step 3 — H100 Validation

~~~text
H100 prediction
        vs
H100 actual
~~~

비교:

- Max SLO Goodput
- TTFT
- TPOT
- transfer cost
- utilization

Projection error를 기록한다.

## Step 4 — Unsupported HW

검증된 model로:

~~~text
H100 Actual [A]
+
Target HW Parameter [B]
        ↓
Target HW Projection [C]
~~~

을 수행한다.

---

# 13. DP1 Workload Set

DP1 평가는 두 층으로 구성한다.

## 13.1 Common Benchmark

공통 QA Rating을 위한 benchmark.

목적:

- QA1 Max SLO Goodput
- QA2 TTFT/TPOT
- QA3 Resource Utilization

## 13.2 DP1-specific Stress Benchmark

DP1의 trade-off와 failure mode를 보기 위한 workload.

### Resource-pressure scenarios

- HBM capacity ramp
- HBM BW pressure
- Host path pressure
- memory tier saturation

### Data-behavior scenarios

- hotness flip
- reuse pattern shift
- long-lived cold object
- suddenly hot object
- promotion/demotion

### Mixed AI Data

- KV Cache
- RAG Data
- Agent Memory
- Tool Result
- LoRA
- MoE Expert
- Vector Index Cache

### Stability

- migration storm
- repeated promotion/demotion
- prediction lag
- tier imbalance

---

# 14. DP1 Metrics

## 14.1 Common QA Metrics

공통 QA 문서 기준:

- Max SLO Goodput
- TTFT P99
- TPOT P99
- Resource Utilization
- Modifiability

## 14.2 DP1 Diagnostic Metrics

### Migration
- migration count
- migration bytes
- migration BW
- migration time
- migration-induced stall
- promotion count
- demotion count

### C1 Diagnostic
- resource pressure detection
- pressure relief bytes
- victim size
- eviction churn
- event-to-decision latency

### C2 Diagnostic
- predictor accuracy
- prediction lag
- hot object upper-tier residency
- unnecessary promotion
- unnecessary demotion
- migration thrashing
- predictor overhead

Diagnostic metric은 QA Score의 직접 대체가 아니라 후보 구조 차이의 원인을 설명하는 데 사용한다.

---

# 15. Current Simulator Assets

현재 branch:

~~~text
claude/vllm-call-path-analysis-qxulkr
~~~

DP1 simulator:

~~~text
doc-mk/Evaluation/DP1/sim/
├── README.md
├── events.py
├── registry.py
├── policies.py
├── simulator.py
├── run_eval.py
├── test_sim.py
├── model.py
├── scenarios.py          # benchmark scenario 단일 소스 (benchmark.md 참조)
├── qa_eval.py            # QA1~QA3 산출 (Common Reference Baseline 대비 별점)
└── configs/              # systems.json (SYS-1..5), clusters.json, memories_default.json, models.json
~~~

System profile은 `../system-specs.md`, benchmark scenario 정의는 `benchmark.md`, 결과는 `results/`에 둔다.

기존 claude/dp1-ai-data-placement branch의 doc-architect/dp1_eval, doc-architect/dp1_sim, doc-architect/configs에서 재사용 가능한 model / scenario / HW configuration을 가져오고, policy와 event flow는 현재 DP1 구조에 맞게 변경했다.

현재 simulator는 **실행 코드 준비 단계**이며 향후 실제 vLLM trace-replay 구조로 확장한다.

---

# 16. Implementation Roadmap

## Phase 0 — QA Criteria Freeze

별도 QA 문서에서 다음을 확정한다.

- QA definition
- 별점 threshold
- A/B/C Evidence
- Common Benchmark Profile
- SLO

## Phase 1 — A100 / H100 vLLM Baseline

실제 vLLM serving에서 load / concurrency sweep을 수행하고 다음을 측정한다.

- Max SLO Goodput
- TTFT P99
- TPOT P99
- HBM / GPU state

## Phase 2 — HW Microbenchmark

측정:

~~~text
HBM / GPU
Host DRAM
PCIe
NVLink
SSD
~~~

항목:

- memcpy BW / latency
- transfer-size sensitivity
- concurrent transfer interference
- CPU overhead
- memory allocation overhead

## Phase 3 — vLLM Trace Collector

목표:

~~~text
vLLM
  ↓
Actual Trace
  ↓
DP1 Trace Replay
~~~

## Phase 4 — DP1 Shadow Evaluation

동일 trace에 C1/C2를 적용한다.

~~~text
Actual vLLM Trace
        │
   ┌────┴────┐
   ▼         ▼
  C1         C2
   │         │
   └────┬────┘
        ▼
Projected Migration Impact
~~~

## Phase 5 — Partial Real Migration

가능한 경로부터 실제 migration cost를 측정한다.

예:

~~~text
HBM <-> DRAM
~~~

## Phase 6 — A100/H100 Cross-validation

A100 calibration → H100 prediction → H100 actual 비교.

Projection error band를 확정한다.

## Phase 7 — Unsupported HW Projection

대상 예:

- B100
- CXL
- HBF
- Custom HBM
- PIM/PNM

결과는 [B+C]로 표기한다.

## Phase 8 — DP1 Final QA Table

공통 QA Criteria에 따라 C1/C2 결과를 최종 별점과 evidence로 정리한다.

---

# 17. Execution Checklist

1. QA Evaluation Criteria freeze
2. A100 vLLM baseline
3. H100 vLLM baseline
4. Load/concurrency sweep
5. HW microbenchmark
6. vLLM trace schema 정의
7. vLLM trace collector 구현
8. DP1 simulator trace-replay 연결
9. C1/C2 Shadow Mode 실행
10. Partial real migration 측정
11. A100 -> H100 cross-validation
12. Projection error range 확정
13. Unsupported-memory B/C parameter 수집
14. CXL/HBF/cHBM/PIM-PNM projection
15. DP1 stress benchmark
16. QA Score + Evidence Level 정리

---

# 18. Boundary with Other DPs

본 문서는 **DP1 전용**이다.

DP2는 llm-d가 Prefill/Decode 노드 선택과 execution planning을 담당하므로 별도의 실험 구조가 필요하다.

~~~text
DP2
llm-d Scheduler / Routing
        ↓
vLLM Prefill / Decode Workers
        ↓
Execution Planning Evaluation
~~~

따라서 DP2 simulation은 별도 문서로 만든다.

DP3/DP4도 각자의 runtime/control boundary에 맞춰 별도 simulation 문서를 둔다.

공통으로 공유하는 것은:

- QA definition
- rating rule
- A/B/C Evidence convention
- Common Benchmark principle

뿐이며, **실험 시스템과 simulator 구조는 DP별로 분리한다.**
