# DP1 Monitoring & Prediction Methodology

> **문서 목적:** DP1의 C1/C2가 “무엇을 모니터링하고, 어떤 방식으로 예측해서 Placement에 사용하는가”를 구현 수준에서 설명한다.
>
> - C1: **Memory Resource 상태의 near-future prediction**
> - C2: **Data behavior의 online characterization / prediction**
>
> 이 문서는 `dp1-data-placement-design.md`의 구조 설명보다 한 단계 아래의 **방법론 문서**다.

---

# 1. 공통 원칙

DP1의 prediction은 장기 forecasting이 아니라 **Placement decision window 안에서의 online prediction**이다.

두 후보 모두 다음 원칙을 사용한다.

1. 미래 workload의 정답을 미리 보지 않는다.
2. Runtime에서 실제로 관찰된 sample/event만 사용한다.
3. Cold-start에서는 prior/default profile을 사용한다.
4. 관찰 sample이 쌓일수록 prior 비중을 줄이고 runtime observation 비중을 높인다.
5. prediction이 틀리면 재평가 / promotion / fallback을 수행한다.

현재 evaluator의 simulation tick은 1초다. 실제 runtime에서는 동일 구조를 100 ms~1 s 수준의 configurable interval로 사용할 수 있다.

---

# 2. C1 — Resource State Monitoring / Prediction

## 2.1 무엇을 관찰하는가

C1 Resource State Monitor의 입력은 Data access가 아니라 **Memory/HW telemetry**다.

```text
TelemetrySample
├── capacity_utilization
├── bandwidth_utilization
├── queue/load              # production target
├── pressure
├── contention              # production target
└── latency_state           # production target
```

현재 evaluator에서 직접 사용하는 핵심 signal은 Capacity utilization과 Bandwidth utilization이다. 즉 C1은 “이 KV가 hot한가?”를 보지 않고, “HBM이 지금 얼마나 차 있고 곧 더 차는가?”를 본다.

## 2.2 Sliding Window

각 Memory Tier별 최근 sample을 ring buffer로 유지한다.

현재 evaluator:

```text
Window W = 5 samples
Prediction Horizon H = 2 samples
```

## 2.3 Trend와 Near-future Prediction

현재 evaluator는 복잡한 forecasting model 대신 window 내 선형 trend를 사용한다.

```text
slope_capacity =
    (capacity[t] - capacity[t-W+1]) / (W - 1)

slope_bw =
    (bw[t] - bw[t-W+1]) / (W - 1)

predicted_capacity =
    clamp(current_capacity + H × slope_capacity)

predicted_bw =
    clamp(current_bw + H × slope_bw)
```

예를 들어 현재 HBM pressure가 0.86이고 최근 slope가 +0.06/sample이면 H=2에서 약 0.98을 예측한다. 현재는 공간이 있어도 Candidate Builder가 HBM priority를 낮출 수 있다.

DP1에서 필요한 것은 수십 분 뒤의 forecasting이 아니라 “지금 배치하면 다음 decision window 안에 saturation될 가능성이 높은가?”이므로 baseline predictor는 short-window trend extrapolation으로 둔다. 이후 Kalman filter나 AR/learned predictor로 교체할 수 있다.

---

# 3. C2 — Runtime Data Monitoring

## 3.1 무엇을 관찰하는가

C2는 Memory pressure가 아니라 **Data Object의 실제 runtime event**를 본다.

```text
DataRuntimeEvent
├── object_id
├── timestamp
├── access_count
├── bytes_read / bytes_written
├── operation
├── active / idle transition
└── release / lifetime end
```

현재 evaluator는 object별로 다음 online state를 유지한다.

```text
PerObjectRuntimeState
├── access_rate_EWMA
├── last_access_time
├── reuse_interval_EWMA
├── idle_time
├── object_age
└── sample_count
```

중요한 점은 synthetic workload generator의 hidden true rate를 Placement 전에 읽지 않는다는 것이다. **실제로 발생한 access event를 관찰하고 다음 decision부터 사용한다.**

---

# 4. C2 Hotness Prediction

1초 sampling 기준 observed access count를 a_t라고 하면:

```text
r_t = (1 - α) r_(t-1) + α a_t
α = 0.18
```

최근 access가 많아지면 hotness가 올라가고, access가 사라지면 시간이 지나면서 내려간다.

현재 evaluator의 normalization:

```text
observed_hotness = clamp(r_t / 0.35)
```

0.35는 현재 trace generator의 reference access-rate scale이며 절대적인 시스템 상수가 아니다. 실제 runtime에서는 workload calibration으로 정한다.

---

# 5. Cold-start Prior와 Runtime Observation 결합

처음 object가 생기면 history가 없으므로 Data Class prior를 사용한다. 예를 들어 KV Cache는 hot/reuse-high prior를, Agent Memory는 long-lived/cold prior를 가진다.

sample 수를 n이라고 할 때 prior weight는 현재 다음처럼 감소한다.

```text
w_prior = max(0.15, exp(-n / 6))

predicted_hotness =
    w_prior × class_prior_hotness
  + (1 - w_prior) × observed_hotness
```

초기에는 class prior를 신뢰하고, runtime observation이 쌓이면 실제 object behavior가 더 큰 비중을 갖는다.

---

# 6. Reuse Prediction

access가 발생할 때 이전 access와의 시간 차이를 측정한다.

```text
Δreuse = current_access_time - previous_access_time

I_t = 0.75 × I_(t-1) + 0.25 × Δreuse
```

다음 H_r초 안에 다시 접근될 가능성은 단순 exponential inter-arrival model로 근사한다.

현재 evaluator:

```text
H_r = 5 sec

P(reuse within H_r)
    = 1 - exp(-H_r / I_t)
```

이 값은 KV의 immediate reuse 여부와 DRAM staging 가능 여부에 사용한다.

---

# 7. Lifetime Prediction

정확한 lifetime은 object가 release될 때까지 알 수 없다. 따라서 Data Class lifetime prior와 **현재까지 실제로 살아남은 object age**를 결합한다.

```text
lifetime_observation = clamp(object_age / 60 sec)
```

object가 오래 살아남을수록 “short-lived일 가능성”을 낮추는 방향으로 lifetime score를 갱신한다. Production runtime에서는 release event가 충분히 쌓이면 class/object-group별 survival distribution 또는 hazard model로 확장할 수 있다.

---

# 8. Mis-prediction Detection

Prediction은 항상 맞는다고 가정하지 않는다. 다음 경우를 mis-prediction / low-confidence 상태로 본다.

- Classifier confidence가 낮음
- 예상 hotness와 실제 EWMA hotness의 차이가 큼
- predicted reuse와 실제 idle/reuse interval이 크게 다름
- 선택 Tier가 required operation을 지원하지 않음
- 선택 Tier에서 예상 TTFT / TPOT budget을 만족하지 못함

예를 들어 초기에는 active KV로 보였지만 10초 이상 idle이고 reuse interval이 계속 길어지면 hotness/reuse prediction을 하향하고 tier affinity를 다시 계산한다.

---

# 9. C2 Fallback — DRAM에서 HBM을 기다리는 경우

Prediction이 틀렸고 HBM pressure가 높은 경우 **즉시 PNM/cHBM으로 실행하는 것만이 정답은 아니다.**

C2는 다음 세 경로를 비교한다.

```text
A. Immediate HBM

B. Remote Attention
   Custom HBM / CXL-PNM

C. Deferred HBM Promotion
   DRAM에 임시 배치
       ↓
   HBM pressure가 내려갈 때까지 대기
       ↓
   DRAM → HBM promotion
       ↓
   HBM에서 실행
```

## 9.1 HBM Relief Estimator

C2의 primary predictor는 Data behavior predictor지만, fallback에서만 작은 resource trend predictor를 사용한다.

```text
slope = (pressure[t] - pressure[t-W+1]) / (W - 1)

T_relief =
    (pressure[t] - low_watermark) / (-slope)
```

현재 evaluator의 기준:

```text
HBM low watermark = 0.72
HBM normal-placement guard ≈ 0.88
```

두 threshold를 다르게 두어 promotion/demotion oscillation을 막는다.

## 9.2 DRAM wait가 유리한 조건

```text
T_wait_path =
    T_HBM_relief
  + T_DRAM_to_HBM

T_next_reuse =
    predicted reuse interval
```

만약:

```text
T_next_reuse > T_wait_path + guard
```

이면 object는 HBM이 회복되기 전에는 쓰이지 않을 가능성이 높으므로 DRAM에 잠시 두는 것이 합리적이다. 이 경우 remote Attention을 억지로 실행하거나 pressure가 높은 HBM에 즉시 넣는 것보다 빠를 수 있다.

반대로 다음 access가 임박하면 DRAM wait를 선택하지 않는다.

```text
reuse imminent
    ↓
TPOT budget을 만족하는 Custom HBM / CXL-PNM
    ↓
불가능하면 restore-on-access path
```

이 DRAM wait 경로는 **C2의 정상 placement rule이 아니라 prediction failure에 대한 temporal fallback**이다.

한 번 prediction error/fallback이 발생한 object는 짧은 watch list에 넣고, 현재 evaluator에서는 5개의 observed sample마다 다시 평가한다. 그래서 첫 fallback 시점에는 HBM relief가 불확실해서 Custom HBM/CXL-PNM을 선택했더라도, 이후 HBM pressure가 실제로 내려가는 trend가 보이면 DRAM stage-and-wait 경로로 전환할 수 있다.

---

# 10. SSD-PIM Operation Boundary

SSD-PIM의 연산 기능은 **GEMV 하나로 제한**한다.

사용 목적:

```text
Vector DB is stored on SSD
        ↓
Query Vector
        ↓
SSD-PIM GEMV
Stored Vector × Query Vector
        ↓
Similarity Score Vector
        ↓
Controller / Host ranking & top-k
        ↓
Selected Vector / Document IDs
```

Baseline은 SSD의 vector data를 GPU/CPU로 읽어온 뒤 similarity GEMV를 수행한다. SSD-PIM path는 vector data를 SSD에 둔 채 **similarity GEMV만 SSD-PIM에서 수행하고 score result를 가져온다.**

Top-k 자체를 SSD-PIM primitive라고 가정하지 않고, Top-k 계산 비용을 SSD-PIM의 핵심 이득으로 보지도 않는다. 핵심은 full-vector transfer가 score transfer로 바뀌는 것과 similarity GEMV가 data-near compute로 이동하는 것이다.

```text
Baseline external traffic ≈ N × D × dtype_bytes

SSD-PIM external traffic ≈ N × score_bytes
```

예를 들어 D=1024, BF16이면 vector 하나는 2048 B이고 FP32 similarity score는 4 B이므로 score path의 외부 traffic은 full-vector path보다 약 512배 작다.

SSD-PIM은 다음 용도로 사용하지 않는다.

- KV Decode Attention
- Softmax
- Causal Mask
- FFN
- 일반 GEMM

---

# 11. C1과 C2의 방법론 차이

| 항목 | C1 | C2 |
|---|---|---|
| 관찰 대상 | Memory/HW | Data Object |
| 입력 | capacity/BW/pressure telemetry | actual access/reuse/idle events |
| History | resource time-series | per-object behavior history |
| Prediction | near-future resource pressure | hotness/reuse/lifetime |
| Cold-start | 거의 없음 | Data Class prior 필요 |
| Error recovery | resource state 재평가 | mis-prediction 감지 + fallback/promotion |
| 대표 질문 | “HBM이 곧 찰까?” | “이 Data가 곧 다시 쓰일까?” |

C2의 DRAM wait fallback에서 HBM relief trend를 보는 것은 **fallback 실행 가능성을 판단하기 위한 보조 resource prediction**이며, C2의 1차 placement 기준을 Resource-centric으로 바꾸는 것은 아니다.

---

# 12. Evaluator와 Production Runtime의 차이

현재 evaluator는 architecture trade-off를 재현하기 위한 경량 online model이다.

현재 구현:

- C1: 5-sample linear trend + 2-sample horizon
- C2 access rate: EWMA α=0.18
- C2 reuse interval: EWMA α=0.25
- C2 reuse probability: exponential inter-arrival approximation
- Cold-start prior decay: `max(0.15, exp(-n/6))`
- HBM deferred-promotion low watermark: 0.72

Production에서 교체 가능한 부분:

- EWMA → histogram / quantile sketch / learned predictor
- linear trend → Kalman filter
- reuse exponential model → empirical CDF
- lifetime heuristic → survival/hazard model
- fixed threshold → workload-adaptive threshold

Architecture에서 중요한 것은 특정 ML predictor가 아니라 **monitor → prediction → affinity/selector → feedback/recovery**의 responsibility boundary다.
