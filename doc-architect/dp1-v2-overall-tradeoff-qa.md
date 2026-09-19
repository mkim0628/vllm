# DP1 C1 vs C2 Overall Trade-off QA — Final

> Source run: GitHub Actions 35445200136 — SUCCESS
>
> 8 representative scenarios × 5 seeds × 5 loads × 3 candidates = **600 cells**.
>
> Overall only. C1-favorable / C2-favorable subgroup scoring은 사용하지 않는다.
>
> Architecture-level simulation이며 실제 B200/vLLM hardware benchmark가 아니다.
>
> Monitoring / prediction의 상세 방법론은 기존 문서 **dp1-monitoring-prediction-methodology.md**에서 정리했던 내용을 현재 C1/C2 정의에 맞게 이 문서에도 포함한다.

---

# 1. Candidate Boundary

## C1 — Resource-centric Placement

C1의 핵심 질문은:

> **"각 Memory Resource가 지금 어떤 상태이고, 가까운 미래에 어디가 먼저 pressure에 걸릴 것인가?"**

이다.

- Primary signal: **Memory Resource State**
- Runtime monitoring: Capacity / BW / Pressure / trend / near-future Resource prediction
- Data-Memory Affinity Registry: deterministic Data↔Memory / Operation knowledge
- 예: RAG→SSD-PIM GEMV, MoE→HBF spill, KV의 HBM-direct / near-memory Attention / restore path 비교
- Data Object의 Hotness / Reuse / Lifetime은 추적하지 않는다.

## C2 — Data-centric Placement

C2의 핵심 질문은:

> **"이 Data Object가 실제 Runtime에서 어떻게 사용되고 있으며, 다음에는 어떤 behavior를 보일 것인가?"**

이다.

- Primary signal: **Data-object Runtime State**
- Runtime monitoring: Access / Reuse / Idle / Lifetime
- Data Type은 Data Descriptor에서 deterministic하게 사용
- Resource 정보는 current capacity / operation capability의 **feasibility check**로 사용
- C1의 Resource State Monitor를 포함하는 superset 구조가 아니다.

즉 두 후보의 차이는:

~~~text
C1: Memory Resource의 시간 변화 관찰
C2: Data Object의 시간 변화 관찰
~~~

이다.

---

# 2. C1 — Resource Monitoring / Prediction / Placement

## 2.1 무엇을 Monitoring 하는가

C1의 Resource State Monitor는 외부 Telemetry Collector로부터 **Memory Tier별 HW telemetry**를 받는다.

현재 evaluator의 핵심 signal:

~~~text
Per-Memory Telemetry
├── Capacity Utilization
└── Bandwidth Utilization
~~~

Production에서는 Queue Depth, Contention, Observed Latency, Read/Write BW, Device Busy, Link Utilization 등으로 확장할 수 있다.

중요한 점은 C1은 **"이 KV가 hot한가?"**를 보지 않고, **"HBM/CXL/HBF/DRAM의 pressure가 어떻게 변하고 있는가?"**를 본다는 것이다.

## 2.2 최근 Resource Trend를 어떻게 Prediction 하는가

각 Memory Tier마다 최근 sample을 ring buffer로 유지한다.

현재 evaluator:

~~~text
Window W = 5 samples
Prediction Horizon H = 2 samples
~~~

Capacity와 BW 각각에 대해 최근 기울기를 계산한다.

~~~text
capacity_slope =
    (capacity[t] - capacity[t-W+1]) / (W - 1)

bw_slope =
    (bw[t] - bw[t-W+1]) / (W - 1)

predicted_capacity =
    current_capacity + H × capacity_slope

predicted_bw =
    current_bw + H × bw_slope
~~~

예를 들어:

~~~text
HBM Capacity Utilization

t-4   0.72
t-3   0.76
t-2   0.80
t-1   0.84
t     0.88

최근 slope ≈ +0.04 / sample

H = 2
→ predicted ≈ 0.96
~~~

현재 HBM이 아직 88%라도 **다음 decision window에서 saturation에 가까워질 것**으로 보고 선제적으로 HBM의 Resource Utility를 낮춘다.

## 2.3 Prediction 결과를 Placement에 어떻게 사용하는가

각 Candidate Memory의 Resource Utility는 현재 구현에서 다음 요소를 사용한다.

~~~text
Resource Utility
=
0.30 × Capacity Headroom
+ 0.24 × BW Headroom
+ 0.32 × Effective Memory Speed
+ 0.09 × Latency Score
+ 0.05 × Size/Capacity Fit
- Migration Cost
+ 0.22 × Static Data-Memory Affinity
~~~

Static Data-Memory Affinity는 Runtime prediction이 아니다.

예:

~~~text
RAG + Vector Similarity
→ SSD-PIM GEMV affinity

MoE Expert
→ HBM / HBF affinity

KV Cache
→ HBM Direct / Near-memory Attention /
   Restore-to-HBM path의 deterministic cost
~~~

즉 C1의 배치 논리는:

~~~text
Telemetry
   ↓
Resource State Monitor
   ↓
Current + Predicted Resource Pressure
   ↓
Resource Utility
   +
Data-Memory Affinity Registry
   ↓
Candidate Tier
   ↓
Performance Guard
   ↓
Placement / Rebalancing
~~~

이다.

## 2.4 어떻게 선제적 Rebalancing을 하는가

HBM pressure가 증가 중이면 C1은 saturation이 실제 발생하기 전에 HBM score를 낮추고 다른 Memory Tier의 score를 높인다.

예:

~~~text
HBM Capacity/BW 증가 추세
        ↓
2 decision-window 뒤 High Pressure 예측
        ↓
RAG → SSD-PIM
MoE → HBF
일부 KV → statically safe한 alternative path
        ↓
HBM Pressure 완화
~~~

현재 R2에서는 High Watermark **0.90**, Relief Target **0.85**를 사용하며, Emergency에서도 Performance Guard를 우회하지 않는다.

따라서 C1의 장점과 비용은 자연스럽게 연결된다.

> **Resource saturation은 잘 피하지만, pressure relief를 위한 migration/rebalancing 자체가 request critical path에 추가 비용을 만들 수 있다.**

---

# 3. C2 — Data Monitoring / Prediction / Placement

## 3.1 Data Type은 무엇인가

C2의 Data Type은 classifier가 추측하는 값이 아니다. Data Descriptor에서 deterministic하게 주어진다.

예:

~~~text
KV block        → KV_CACHE
Vector index    → RAG_DATA
Agent state     → AGENT_MEMORY
Tool output     → TOOL_RESULT
LoRA weights    → LORA_ADAPTER
MoE weights     → MOE_EXPERT
~~~

C2에서 prediction 대상은 **Data Type 자체가 아니라 그 Data Object의 Runtime Behavior**다.

## 3.2 무엇을 Monitoring 하는가

C2의 Runtime State Monitor는 실제로 발생한 Data access event를 object별로 관찰한다.

~~~text
Per-Object Runtime State
├── Access Rate EWMA
├── Last Access Time
├── Reuse Interval EWMA
├── Idle Time
├── Object Age
└── Sample Count
~~~

현재 evaluator는 synthetic workload의 숨겨진 true rate를 미리 읽지 않는다.

~~~text
실제 access 발생
    ↓
Runtime State Monitor observe()
    ↓
다음 Placement decision부터 사용
~~~

한다.

## 3.3 Hotness를 어떻게 Prediction 하는가

1초 sample에서 관찰한 access count를 a_t라고 하면:

~~~text
r_t = (1 - α) × r_(t-1) + α × a_t

α = 0.18
~~~

그리고:

~~~text
observed_hotness = clamp(r_t / 0.35)
~~~

로 현재 workload에서의 hotness를 얻는다.

Object가 처음 생성됐을 때는 history가 없으므로 Data Type별 prior를 사용한다.

~~~text
w_prior = max(0.15, exp(-n / 6))

predicted_hotness
=
w_prior × Data-Class Prior
+
(1 - w_prior) × Observed Hotness
~~~

즉 처음에는 "KV는 보통 hot/reuse-high", "Agent Memory는 보통 long-lived" 같은 prior를 쓰고, sample이 쌓이면 **실제 object behavior가 판단을 지배**한다.

## 3.4 Reuse를 어떻게 Prediction 하는가

실제 access 사이 간격을 측정한다.

~~~text
Δreuse =
    current_access_time - previous_access_time
~~~

Reuse interval EWMA:

~~~text
I_t =
0.75 × I_(t-1)
+
0.25 × Δreuse
~~~

현재 5초 horizon에서:

~~~text
P(reuse within 5 sec)
=
1 - exp(-5 / I_t)
~~~

로 next-reuse 성향을 근사한다.

따라서 같은 KV_CACHE라도:

~~~text
KV-A
Access Rate 높음
Reuse Interval 짧음
Idle Time 짧음
→ Hot / Reuse-high

KV-B
Access Rate 낮음
Reuse Interval 김
Idle Time 증가
→ Cold / Reuse-low
~~~

로 서로 다른 Runtime Characteristic을 갖는다.

## 3.5 Lifetime을 어떻게 Prediction 하는가

Object가 아직 release되지 않고 오래 살아남으면 long-lived 가능성을 높인다.

현재 evaluator:

~~~text
lifetime_observation =
    clamp(object_age / 60 sec)
~~~

Data Class prior와 현재 age를 합쳐 lifetime characteristic을 갱신한다.

## 3.6 Prediction 결과를 Placement에 어떻게 사용하는가

Data Characteristic Interpreter가 최종적으로 다음 characteristic을 만든다.

~~~text
Data Characteristics
├── Hotness
├── Reuse
├── Next Reuse
├── Lifetime
├── Idle
├── Latency Sensitivity
└── Write Ratio
~~~

MemoryTierAffinityEvaluator가 이 Data 특성과 Memory 특성을 매칭한다.

| Data | Runtime Characteristic | Placement 방향 |
|---|---|---|
| KV Cache | Hot / Reuse-high / latency-sensitive | HBM 또는 static cost가 좋은 Attention-capable tier 선호 |
| KV Cache | 상대적으로 Cold / Reuse-low | HBM 고정 선호를 낮추고 가능한 near-memory path와 비교 |
| RAG Data | Long-lived / read-mostly | SSD-PIM/HBF 같은 capacity·read-oriented tier affinity 증가 |
| Agent Memory | Cold / long-lived | DRAM/CXL/SSD 계층 affinity 증가 |
| LoRA / MoE | Hot | HBM affinity 증가 |
| LoRA / MoE | Cold / read-mostly | HBF/DRAM affinity 상대적 증가 |

단, **KV decode를 어디에서 수행하는 것이 빠른지 자체는 C1/C2 공통의 deterministic Data-Memory knowledge**다.

C2의 추가 정보는:

> **"같은 KV/MoE/Agent Data Type이라도 현재 이 object가 실제로 hot한가, 다시 곧 쓰이는가, 오래 idle한가"**

이다.

C2의 전체 흐름은:

~~~text
Data Descriptor
    ↓
Deterministic Data Type
    ↓
Runtime State Monitor
    ↓
Access / Reuse / Idle / Lifetime History
    ↓
Data Characteristic Interpreter
    ↓
Hotness / Reuse / Lifetime Prediction
    ↓
Data-Memory Affinity + Operation Cost
    ↓
Current Resource Feasibility Check
    ↓
Performance Guard
    ↓
Placement
~~~

이다.

C2는 C1처럼 Capacity/BW trend를 forecasting해서 Resource balancing을 하는 구조가 아니다. 현재 Resource 정보는 **"이 Tier에 실제로 들어갈 수 있는가?"**를 확인하는 feasibility 용도로 사용한다.

---

# 4. Monitoring 관점에서 본 C1 vs C2

| 항목 | C1 — Resource-centric | C2 — Data-centric |
|---|---|---|
| Monitoring 대상 | **Memory Tier** | **Data Object** |
| 관찰 Signal | Capacity / BW / Pressure | Access / Reuse / Idle / Age |
| History 단위 | Tier별 time-series | Object별 behavior history |
| Prediction | **Near-future Resource Pressure** | **Hotness / Reuse / Lifetime** |
| Data Type | Static Affinity lookup | Runtime behavior 해석의 context |
| 대표 질문 | **"HBM이 곧 찰까?"** | **"이 Object가 곧 다시 쓰일까?"** |
| 행동 | 선제적 Rebalancing | Data behavior에 맞는 Tier/Path 선택 |
| 주요 장점 | Resource utilization / pressure relief | Request performance / object-level adaptation |
| 주요 비용 | Rebalance / migration overhead | Monitoring state / complexity |

이 표가 QA 결과를 설명하는 핵심이다.

---

# 5. Overall QA

## 5.1 Comparative Star Rule

별점은 절대 성능 등급이 아니라 **C1/C2 Architecture trade-off를 시각화하는 comparative score**다.

- **Throughput:** 후보 차이가 1% 이내이면 practical tie → 둘 다 ★★☆
- **TTFT / TPOT / Resource Utilization:** 0.5% 이내이면 tie
- tie band를 넘으면 더 좋은 후보 ★★★, 다른 후보 ★★☆
- 뒤지는 후보가 As-Is 대비 severe regression까지 보이면 ★☆☆
- Modifiability: average changed modules가 작은 후보 ★★★; 25% 이상 큰 후보 ★☆☆

Throughput은 현재 C1/C2 차이가 **0.6%**에 불과하고 두 95% CI가 크게 겹치므로 **동점 처리**한다.

## 5.2 QA Table

| QA | C1 Resource-centric | C2 Data-centric | Quantitative Basis |
|---|:---:|:---:|---|
| **Performance Throughput** | **★★☆** | **★★☆** | C1 **0.999×** [0.985, 1.014], C2 **1.005×** [0.991, 1.019] — **Practical Tie** |
| **Performance TTFT** | **★★☆** | **★★★** | C1 **0.757×** [0.571, 1.005], C2 **0.658×** [0.501, 0.863] — C2 **15.2% lower** |
| **Performance TPOT** | **★☆☆** | **★★★** | C1 **1.176×** [1.025, 1.350], C2 **0.999×** [0.999, 1.000] — C2 **17.7% lower** |
| **Resource Utilization** | **★★★** | **★★☆** | C1 **1.034×** [0.974, 1.098], C2 **0.989×** [0.956, 1.023] — C1 **4.4% better** |
| **Modifiability** | **★★★** | **★☆☆** | Avg changed modules: C1 **2.5**, C2 **4.0**; object behavior state fields: C1 **0**, C2 **5** |

---

# 6. 왜 이런 QA 결과가 나오는가

## Throughput — Practical Tie

C1과 C2 모두 KV decode path, RAG SSD-PIM 등 **deterministic Data-Memory Affinity와 Performance Guard**를 사용하므로 steady-state service capacity가 크게 무너지지 않는다.

C2가 수치상 0.6% 높지만 CI가 크게 겹치고 1% practical band 안이므로 Architecture 수준에서는 **동점**으로 본다.

## TTFT — C2 우세

C1은 Resource trend를 예측해 saturation 전에 선제적으로 migration/rebalancing을 수행한다. 이 방식은 Resource pressure에는 유리하지만, Data가 다음에 언제 다시 쓰일지는 모르기 때문에 first access 시 migration/restore cost가 critical path에 들어갈 수 있다.

C2는 실제 object access/reuse/idle history를 기반으로 **곧 다시 쓰일 Data와 그렇지 않은 Data를 구분**하므로 first-use critical path를 더 안정적으로 유지한다.

## TPOT — C2 우세

KV decode 실행 위치의 static cost는 C1도 이미 알고 있으므로 이 차이는 **decode affinity 지식의 유무 때문이 아니다.**

C1은 Resource pressure를 낮추기 위해 statically safe한 offload/rebalancing을 수행할 수 있고, 여러 object의 migration/link usage가 겹치면 aggregate contention이 p99 TPOT에 반영될 수 있다. 반면 C2는 Resource balancing 자체를 목표로 하지 않고 **observed hotness/reuse가 높은 active object의 steady-state path를 우선적으로 보존**한다.

## Resource Utilization — C1 우세

이 결과는 C1의 설계 목적과 직접 연결된다.

C1은 Capacity/BW/Pressure의 **현재 값뿐 아니라 증가 trend까지 예측**하고, saturation 전에 다른 Tier로 pressure를 분산한다. C2는 Resource trend를 최적화 signal로 쓰지 않고 current feasibility만 확인하기 때문에 전체 Memory Tier utilization을 균형 있게 만드는 능력은 C1이 더 강하다.

## Modifiability — C1 우세

C1의 Runtime state는 Memory Tier 수에 비례하며 핵심 구조는 **Resource State Monitor + Data-Memory Affinity Registry**다.

C2는 Data Object별 **Access Rate / Last Access / Reuse Interval / Idle / Age** 상태를 유지하고 **Runtime State Monitor → Data Characteristic Interpreter → Placement**가 연결되므로 새로운 behavior policy를 추가할 때 변경 범위가 더 크다.

---

# 7. Review Q&A용 핵심 설명

### Q. C1은 무엇을 예측하는가?

> **Memory Resource의 가까운 미래 상태를 예측한다.** 최근 5개 Capacity/BW sample의 slope를 보고 2 decision-window 뒤 pressure를 추정해 saturation 전에 선제적으로 rebalancing한다.

### Q. C2는 무엇을 예측하는가?

> **Data Object의 가까운 미래 behavior를 예측한다.** 실제 access history로 Hotness, Reuse Interval, Idle, Lifetime을 갱신하고 같은 Data Type 안에서도 object별로 다른 placement affinity를 만든다.

### Q. 왜 C1의 Resource Utilization이 더 좋은가?

> Resource balancing 자체가 C1의 primary objective이기 때문이다. HBM/CXL/HBF 등의 pressure trend를 직접 관찰하고 saturation 전에 부하를 분산한다.

### Q. 왜 C2의 TTFT/TPOT가 더 좋은가?

> Static Data-Memory knowledge가 더 많아서가 아니다. **실제 object behavior를 보고 지금 active/reuse-heavy한 Data와 그렇지 않은 Data를 구분하기 때문**이다. C1은 Resource에는 선제적으로 반응하지만 Data의 next-use timing은 알지 못한다.

### Q. 결국 두 구조의 Trade-off는?

~~~text
                 C1 Resource-centric      C2 Data-centric

Throughput             ★★☆                    ★★☆
TTFT                   ★★☆                    ★★★
TPOT                   ★☆☆                    ★★★
Resource Utilization   ★★★                    ★★☆
Modifiability          ★★★                    ★☆☆
~~~

> **C1은 Resource efficiency / proactive balancing / structural simplicity에 강하다.**
>
> **C2는 object-level Data behavior를 이용한 end-to-end latency optimization에 강하다.**

두 구조 모두 deterministic Data-Memory Affinity는 알고 있으며, 핵심 차이는 **무엇을 Runtime에서 monitoring하고 prediction하느냐**다.
