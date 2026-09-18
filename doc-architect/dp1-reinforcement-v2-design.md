# DP1 Reinforcement V2 Design — C1-R2 / C2-R2

> 이 문서는 `dp1-reinforcement-evaluation.md`에서 남은 문제를 대상으로 하는 **2차 보완 설계안**이다.
>
> 아직 baseline을 덮어쓰지 않는다. V2는 다음 실험 후보로 정의한다.

---

# 1. V1 결과에서 남은 문제

## C1-R

좋아진 점:

- Migration 16.27 → 1.87/run
- Heavy Goodput 0.9999 → 1.0644
- RUI 0.7854 → 0.8101

남은 문제:

- HBM pressure violation 0.1294 → **0.1773**

즉 migration hold가 너무 강하면 pressure relief가 늦어진다.

## C2-R

좋아진 점:

- Fallback 75.81 → 14.27/run
- Migration 48.00 → 11.29/run
- Heavy Goodput 0.8604 → 0.9482
- Throughput ★☆☆ → ★★☆

남은 문제:

- HBM pressure violation 0.1889 → **0.2096**
- Goodput target 0.95를 근소하게 미달
- RUI target 0.78을 근소하게 미달
- 남은 fallback 대부분이 `hard_feasibility_empty`

---

# 2. C1-R2 — Stable + Emergency Pressure Escape

## 2.1 핵심 아이디어

C1-R의 hold/hysteresis는 유지하되, **near-future pressure가 실제 danger zone으로 들어갈 때만 강제로 migration gate를 우회**한다.

```text
Normal Region
  predicted pressure < Emergency Threshold
      ↓
  C1-R hysteresis / residency 유지

Emergency Region
  predicted pressure >= Emergency Threshold
      ↓
  residency bypass
      ↓
  최소 개수 object만 이동
```

## 2.2 Emergency Trigger

예:

```text
predicted_capacity >= 0.90
OR
predicted_bw >= 0.90
OR
time_to_saturation <= 2 decision windows
```

## 2.3 Relief Efficiency

아무 object나 내리지 않는다.

```text
Relief Efficiency =
    Expected Pressure Reduction
    / Migration Cost
```

C1은 Data semantics를 사용하지 않으므로 다음 resource-only 요소만 사용한다.

- object size
- source/target bandwidth
- target headroom
- source pressure contribution proxy

가장 relief-efficiency가 높은 object부터 필요한 만큼만 옮긴다.

## 2.4 목표

- Migration은 C1-R 수준에 가깝게 유지
- HBM pressure violation을 C1 baseline(≈0.13)에 근접
- Goodput 1.0× As-Is 이상 유지

---

# 3. C2-R2 — Explicit Feasibility State

## 3.1 핵심 아이디어

C2-R에서 `hard_feasibility_empty`는 더 이상 “fallback failure”가 아니라 **명시적 system state**로 관리한다.

```text
FEASIBLE
TEMPORARILY_INFEASIBLE
STRUCTURALLY_INFEASIBLE
```

## 3.2 FEASIBLE

하나 이상의 tier가:

- capacity
- required operation
- TTFT/TPOT budget

을 만족.

정상 C2 affinity ranking 수행.

## 3.3 TEMPORARILY_INFEASIBLE

현재 resource pressure 때문에 가능한 tier가 없지만 resource state 변화로 회복 가능.

예:

- HBM pressure가 높음
- Custom HBM link contention
- DRAM stage 후 HBM relief가 예상됨

이 경우:

```text
Best-effort Tier 고정
      ↓
condition-based retry 등록
      ↓
Telemetry event가 변할 때만 재평가
```

tick마다 retry하지 않는다.

## 3.4 STRUCTURALLY_INFEASIBLE

현재 HW capability / batch / context / SLO 조합에서 어떤 tier도 budget을 만족할 수 없음.

예:

- B256 × 512K KV
- 현재 CXL-PNM BW로 TPOT 50 ms 불가능
- 모든 tier에서 required operation latency 초과

이 경우 Placement Planner가 억지로 해결하려 하지 않고:

```text
PlacementDecision
  tier = least-violation tier
  status = STRUCTURALLY_INFEASIBLE
  reason = TPOT_CAPABILITY_LIMIT
```

형태로 upper scheduler/autoscaler에 전달한다.

이 상태는 policy quality와 HW capability boundary를 구분하기 위해 필요하다.

---

# 4. C2-R2 — Low-confidence Envelope

현재 low classifier confidence fallback 2,365건을 줄이기 위한 설계다.

하나의 class를 강제로 선택하지 않고 top plausible classes를 유지한다.

```text
Classifier

KV_CACHE       0.55
AGENT_MEMORY   0.30
TOOL_RESULT    0.15
```

각 class에 대해 feasible set을 계산한다.

```text
F_KV
F_AGENT
F_TOOL
```

가능하면:

```text
Safe Set = intersection(F_KV, F_AGENT, F_TOOL)
```

intersection이 비면 expected/worst-case cost가 가장 낮은 tier를 선택한다.

Runtime history가 충분히 쌓이면 class posterior를 좁히고 정상 C2 path로 전환한다.

---

# 5. C2-R2 — Resource-pressure Override

C2-R의 migration hold 때문에 HBM pressure violation이 증가했다.

따라서 다음 경우 current-tier hold를 무시할 수 있다.

```text
HBM predicted pressure > 0.90
AND
candidate migration relieves HBM
AND
migration budget available
```

단, C2 baseline처럼 migration storm이 재발하지 않도록 interval당 migration budget을 둔다.

예:

```text
MAX_MIGRATIONS_PER_WINDOW = 2~4
WINDOW = 5 sec
```

실제 값은 sensitivity test로 결정한다.

---

# 6. C2-R2 — DRAM Deferred Promotion State

DRAM wait은 V1에서 이미 동작했지만 V2에서는 infeasible-state와 통합한다.

```text
TEMPORARILY_INFEASIBLE
   ↓
next reuse > HBM relief + promotion
   ↓
DRAM_STAGED
   ↓
HBM low watermark
   ↓
PROMOTE_PENDING
   ↓
HBM
```

DRAM_STAGED 동안은 일반 affinity ranking에서 제외한다.

---

# 7. RAG Evaluation Refinement

현재 8 TiB RAG는 stress 관점에서 전체 또는 매우 큰 candidate set을 scan하는 모델이다.

Vector DB 환경을 더 현실적으로 분리하기 위해 다음 축을 추가한다.

```text
INDEX_SIZE
  1 TiB / 8 TiB

QUERY_CONCURRENCY
  16 / 64 / 256

SCAN_FRACTION
  0.1% / 1% / 10% / 100%
```

SSD-PIM의 역할은 계속 하나다.

> **SSD resident vector와 query vector의 similarity GEMV**

비교:

```text
CPU/GPU path
  candidate vectors transfer
  → similarity GEMV

SSD-PIM path
  local similarity GEMV
  → similarity score transfer
```

이 sweep을 통해 policy 문제와 “8 TiB full-scan 자체가 SLO 불가능한 문제”를 분리한다.

---

# 8. V2 실험 가설

## C1-R2

- Heavy Goodput / As-Is ≥ 1.00
- Migration ≤ 5/run
- HBM pressure violation ≤ 0.14
- RUI ≥ 0.80

## C2-R2

- Heavy Goodput / As-Is ≥ 0.95
- Migration ≤ 15/run
- Fallback ≤ 10/run
- HBM pressure violation ≤ 0.19
- RUI ≥ 0.78
- `hard_feasibility_empty`를 fallback count가 아닌 feasibility-state count로 별도 보고

목표를 맞추기 위해 threshold를 사후 조정하지 않고, 동일 trace/sweep에서 검증한다.

---

# 9. 최종 비교 흐름

```text
Stage 0
C1 vs C2
    ↓
최초 trade-off 확인

Stage 1
C1-R vs C2-R
    ↓
instability 제거 후 비교

Stage 2
C1-R2 vs C2-R2
    ↓
pressure / infeasibility 처리까지 보완

Final
남아 있는 구조적 trade-off를 근거로 후보 선택
```

이 단계형 비교를 유지하면 “처음부터 특정 후보가 이기도록 설계했다”는 해석을 피하고, **문제 발견 → 원인 분석 → 보완 설계 → 재평가**의 의사결정 근거를 남길 수 있다.


---

# 10. C1-R2 전체 구조도

C1-R2는 C1/C1-R의 Resource-centric 구조를 유지하면서 **Emergency Pressure Escape**만 추가한다. Data Classifier나 Data Characteristic Interpreter를 추가하지 않는다.

```mermaid
flowchart LR
    TC[Telemetry Collector]
    MR[Memory Registry]

    subgraph MRM[Memory Resource Manager]
        RSM[Resource State Monitor]
        CB[Candidate Builder]
        RSV[Resource State View]
    end

    subgraph RPP[Resource-aware Placement Planner]
        RUE[Resource Utility Evaluator]
        BTS[Best Tier Scoring]

        subgraph SG[Placement Stability Guard]
            RT[Minimum Residency Tracker]
            HG[Hysteresis Gate]
            MBC[Migration Benefit / Cost Gate]
        end

        subgraph EP[NEW: Emergency Pressure Escape]
            ED[Emergency Detector]
            RE[Relief Efficiency Evaluator]
            MB[Migration Budget]
        end
    end

    PD[Placement Decision]
    DP4[DP4 Migration Executor]

    TC --> RSM
    RSM --> RSV
    MR --> CB
    RSV --> CB
    CB --> RUE
    RUE --> BTS

    BTS --> RT
    RT --> HG
    HG --> MBC

    RSV --> ED
    ED -->|Normal| MBC
    ED -->|Emergency| RE
    RE --> MB
    MB --> PD

    MBC -->|migrate| PD
    MBC -->|hold current tier| PD
    PD --> DP4
```

## 10.1 추가 설계 요소

### Emergency Detector

C1-R의 minimum residency / hysteresis가 너무 강하게 동작하면 HBM pressure relief가 늦어질 수 있다. Emergency Detector는 다음 near-future signal을 본다.

```text
predicted_capacity >= emergency_high_watermark
OR
predicted_bw >= emergency_high_watermark
OR
time_to_saturation <= configured_horizon
```

Normal region에서는 C1-R의 기존 stability gate가 그대로 적용된다. Emergency region에서만 residency/hysteresis를 제한적으로 우회한다.

### Relief Efficiency Evaluator

Emergency라고 해서 많은 object를 무조건 이동시키지 않는다.

```text
Relief Efficiency =
    Estimated Source Pressure Reduction
    / Estimated Migration Cost
```

C1은 Data semantics를 사용하지 않으므로 object size, source contribution, source/target BW, target headroom 같은 resource-only 정보만 사용한다.

### Migration Budget

한 decision window에서 이동 가능한 object 수 또는 bytes를 제한한다. 목적은 emergency escape가 다시 migration storm으로 변하는 것을 막는 것이다.

---

# 11. C2-R2 전체 구조도

C2-R2에서는 **Fallback State Manager를 별도 시스템으로 떼는 것이 아니라 기존 Data-aware Placement Planner에 붙인다.**

정상 경로는 기존 C2의:

```text
Data Classifier
→ Runtime State Monitor
→ Data Characteristic Interpreter
→ Tier Affinity
→ Tier Selector
```

를 유지한다.

V2에서 추가되는 것은:

1. Affinity 이전의 **Feasibility State Evaluator**
2. 불확실한 classification을 처리하는 **Low-confidence Safe Envelope**
3. selector 이후의 **Placement Stability Guard**
4. selector/feasibility failure를 처리하는 **Fallback State Manager**
5. 구조적으로 해결 불가능한 경우 upper scheduler에 전달하는 **Infeasibility Feedback**

이다.

```mermaid
flowchart LR
    DD[Data Descriptor]
    EVT[Runtime Data Events]
    TC[Telemetry Collector]
    MR[Memory Registry]

    subgraph DPM[Data Placement Manager]
        DC[Data Classifier]
        RSM[Runtime State Monitor]
        DCI[Data Characteristic Interpreter]
        LCE[NEW: Low-confidence Safe Envelope]
    end

    subgraph DPP[Data-aware Placement Planner]
        FSE[NEW: Feasibility State Evaluator]

        subgraph FS[Feasibility State]
            F[FEASIBLE]
            TI[TEMPORARILY_INFEASIBLE]
            SI[STRUCTURALLY_INFEASIBLE]
        end

        AFF[Memory Tier Affinity Evaluator]
        SEL[Memory Tier Selector]

        subgraph PSG[Placement Stability Guard]
            CH[Current-tier Hold]
            RT[Minimum Residency]
            MBC[Migration Benefit / Cost Gate]
        end

        subgraph FSM[NEW: Fallback State Manager]
            CD[Reason-specific Cooldown / Retry Trigger]
            HRE[HBM Relief Estimator]
            DPC[DRAM Deferred Promotion Controller]
            PO[Pressure Override]
            MB[Migration Budget]
            BS[Best-effort / Safe-tier Selector]
        end

        IFB[NEW: Infeasibility Feedback Builder]
    end

    PD[Placement Decision]
    US[Upper Scheduler / Autoscaler]
    DP4[DP4 Migration Executor]

    DD --> DC
    EVT --> RSM
    DC --> DCI
    RSM --> DCI

    DC -->|class probabilities| LCE
    DCI --> LCE

    LCE --> FSE
    DCI --> FSE
    TC --> FSE
    MR --> FSE

    FSE -->|at least one feasible tier| F
    FSE -->|resource state may recover| TI
    FSE -->|HW/SLO capability limit| SI

    F --> AFF
    DCI --> AFF
    MR --> AFF
    TC --> AFF

    AFF --> SEL
    SEL --> CH
    CH --> RT
    RT --> MBC

    MBC -->|stable decision| PD
    MBC -->|pressure override needed| PO

    TI --> FSM
    SEL -->|low confidence / no stable choice| FSM
    RSM --> FSM
    TC --> HRE
    HRE --> DPC
    CD --> DPC
    PO --> MB
    DPC --> MB
    BS --> MB
    MB --> PD

    SI --> IFB
    IFB -->|least-violation placement| PD
    IFB -->|capability/SLO hint| US

    PD --> DP4
```

## 11.1 정상 C2-R2 경로

```text
Data Descriptor + Runtime History
        ↓
Data Characteristics
        ↓
Low-confidence Envelope
        ↓
Feasibility State Evaluator
        ↓ FEASIBLE
Affinity Ranking
        ↓
Tier Selector
        ↓
Placement Stability Guard
        ↓
Placement Decision
```

Fallback State Manager는 정상 request마다 지나가는 mandatory stage가 아니다. **정상 selector 옆에 붙는 recovery/state-management path**다.

---

# 12. C2-R2 추가 요소 상세 설명

## 12.1 Low-confidence Safe Envelope

Classifier confidence가 낮을 때 하나의 Data Class를 강제로 확정하지 않는다.

예:

```text
KV_CACHE       0.55
AGENT_MEMORY   0.30
TOOL_RESULT    0.15
```

상위 plausible class 각각의 feasible tier set을 계산한다.

```text
F_KV
F_AGENT
F_TOOL
```

가능하면 교집합을 safe set으로 사용한다.

```text
Safe Set = intersection(F_KV, F_AGENT, F_TOOL)
```

교집합이 없으면 expected cost 또는 worst-case cost가 가장 낮은 tier를 고른다. Runtime history가 충분히 쌓이면 posterior가 좁아지고 정상 class-specific path로 복귀한다.

## 12.2 Feasibility State Evaluator

기존 C2 baseline의 가장 큰 문제는 **Affinity로 tier를 고른 뒤 operation/latency violation으로 fallback**한 것이었다.

V2에서는 ranking 전에 각 tier를 다음 조건으로 검사한다.

- Capacity feasibility
- Required operation support
- Predicted TTFT budget
- Predicted TPOT budget
- Link/resource constraint

그 결과를 세 상태로 나눈다.

### FEASIBLE

하나 이상의 tier가 hard constraint를 만족한다.

→ 정상 Affinity Evaluator / Tier Selector로 전달.

### TEMPORARILY_INFEASIBLE

현재 resource pressure나 contention 때문에 candidate가 없지만 resource 상태가 바뀌면 회복 가능하다.

→ Fallback State Manager로 전달.

### STRUCTURALLY_INFEASIBLE

현재 batch/context/HW capability/SLO 조합 자체가 불가능하다.

→ 반복 fallback하지 않고 least-violation tier와 infeasibility reason을 upper scheduler/autoscaler에 전달한다.

## 12.3 Placement Stability Guard

Feasible best tier가 현재 tier와 다르다고 바로 migration하지 않는다.

```text
Target Feasible?
        ↓
Current Tier still feasible?
        ↓
Minimum Residency satisfied?
        ↓
Expected Benefit > Migration Cost + Margin?
        ↓
Migration
```

작은 affinity fluctuation으로 tier가 바뀌는 것을 막는다.

## 12.4 Fallback State Manager

Fallback State Manager는 기존 C2 구조의 **Memory Tier Selector / Feasibility State Evaluator에 연결되는 stateful recovery block**이다.

주요 입력:

- Feasibility state
- Classifier confidence
- Runtime hotness / reuse / idle prediction
- Current/Predicted HBM pressure
- Current tier
- Previous fallback reason/state

주요 출력:

- Safe tier
- DRAM stage decision
- HBM promotion trigger
- Retry condition
- Pressure override migration
- No-retry / structural infeasibility indication

### Reason-specific Cooldown / Retry Trigger

같은 이유로 매 tick fallback하지 않는다.

예:

| Reason | Retry condition |
|---|---|
| low classifier confidence | runtime sample 추가 |
| temporary HBM pressure | pressure low watermark |
| link contention | contention/BW state 변화 |
| no capacity | target tier headroom 회복 |
| operation capability mismatch | config/capability 변경 전까지 retry 금지 |

## 12.5 HBM Relief Estimator

최근 HBM pressure trend로 HBM이 low watermark 아래로 내려갈 예상 시간을 계산한다.

```text
T_relief =
    (current_pressure - low_watermark)
    / (-pressure_slope)
```

Data Runtime Monitor가 예측한 next reuse와 결합한다.

```text
if T_next_reuse > T_relief + T_DRAM_to_HBM + guard:
    DRAM_STAGE
else:
    remote execution / safe tier
```

## 12.6 DRAM Deferred Promotion Controller

TEMPORARILY_INFEASIBLE 상태에서 다음 access가 충분히 늦으면:

```text
DRAM_STAGE
   ↓
wait
   ↓ HBM <= low watermark
PROMOTE_PENDING
   ↓
HBM
```

DRAM_STAGED 동안에는 매 tick 전체 affinity ranking을 반복하지 않는다. HBM relief event 또는 predicted reuse event가 transition trigger가 된다.

## 12.7 Pressure Override + Migration Budget

C2-R에서는 stability gate가 강해져 HBM pressure violation이 증가했다. V2에서는:

```text
predicted HBM pressure > emergency threshold
AND
candidate migration actually relieves HBM
AND
migration budget remains
```

일 때 current-tier hold를 우회할 수 있다.

단, window당 migration count/bytes를 제한하여 C2 baseline의 migration storm이 재발하지 않도록 한다.

## 12.8 Infeasibility Feedback Builder

STRUCTURALLY_INFEASIBLE은 Placement Planner가 반복 시도해서 해결할 문제가 아니다.

예:

```text
B256 × 512K
TPOT SLO = 50 ms
현재 HBM / CXL-PNM / Custom HBM capability 모두 불충족
```

이때:

```text
PlacementDecision
  tier   = least-violation tier
  status = STRUCTURALLY_INFEASIBLE
  reason = TPOT_CAPABILITY_LIMIT
```

을 생성하고, upper scheduler/autoscaler에는 다음과 같은 hint를 보낼 수 있다.

- batch 축소
- request admission control
- context split/chunking
- 다른 HW domain으로 routing
- SLO class 변경

이렇게 해야 **placement policy 실패와 system capability limit를 분리**할 수 있다.

---

# 13. C2-R2 전체 Decision Flow

```mermaid
flowchart TD
    A[Data Descriptor + Runtime History] --> B[Low-confidence Safe Envelope]
    B --> C[Feasibility State Evaluator]

    C -->|FEASIBLE| D[Affinity Evaluator]
    D --> E[Tier Selector]
    E --> F[Placement Stability Guard]

    F -->|hold| G[Keep Current Tier]
    F -->|benefit > migration cost| H[New Tier]
    F -->|Emergency HBM pressure| I[Pressure Override + Migration Budget]

    C -->|TEMPORARILY_INFEASIBLE| J[Fallback State Manager]
    J --> K{Next reuse after HBM relief?}
    K -->|Yes| L[DRAM Stage]
    L --> M[Wait for HBM low watermark]
    M --> N[DRAM → HBM Promotion]
    K -->|No| O{Remote/Safe tier available?}
    O -->|Yes| P[Custom HBM / CXL-PNM / Safe Tier]
    O -->|No| Q[Best-effort Hold + Condition-based Retry]

    C -->|STRUCTURALLY_INFEASIBLE| R[Least-violation Tier]
    R --> S[Infeasibility Feedback to Upper Scheduler]

    G --> T[Placement Decision]
    H --> T
    I --> T
    N --> T
    P --> T
    Q --> T
    R --> T

    T --> U[DP4 Migration / Execution]
```

이 구조에서 Fallback State Manager는 **C2의 기존 selector를 대체하지 않는다.** 정상 FEASIBLE path는 기존 C2처럼 Affinity + Selector가 담당하고, fallback manager는 temporary failure / uncertainty / recovery state만 담당한다.


---

# 14. Performance-first Acceptance Rule

DP1의 후보 구조는 단순히 Resource Utilization이나 Modifiability가 좋아지는 것만으로는 충분하지 않다. **후보 구조를 채택할 당위성은 사전에 정의한 target workload domain에서 As-Is보다 Performance가 좋아지는 데서 출발한다.**

다만 모든 workload에서 항상 As-Is를 이겨야 한다는 의미는 아니다. HBM에 working set이 충분히 들어가고 data-near compute의 이득이 없는 workload에서는 As-Is HBM-first가 이미 강한 baseline이기 때문이다.

따라서 V2부터 다음 원칙을 사용한다.

1. **모든 scenario는 그대로 실행한다.**
2. 후보별 **Target Domain은 결과를 보기 전에 architecture mechanism으로 정의한다.**
3. Target Domain aggregate와 All-scenario aggregate를 둘 다 보고한다.
4. 후보가 Target Domain에서도 Performance improvement를 만들지 못하면 해당 mechanism은 채택하지 않는다.
5. 불리한 scenario를 사후에 제거해서 결과를 만들지 않는다.
6. Neutral workload에서는 가능한 한 As-Is path로 수렴하도록 **Performance Guard / Baseline Bypass**를 둔다.

Performance는 하나의 합성 score로 숨기지 않고 다음 세 항목을 각각 본다.

- Max Sustainable SLO Goodput
- TTFT p99
- TPOT p99

## 14.1 Scenario-level 판정

각 scenario에서 As-Is 대비 다음 형태로 표시한다.

### PERFORMANCE WIN

- Goodput이 의미 있게 증가하거나,
- TTFT/TPOT가 의미 있게 감소하고,
- 다른 critical performance metric의 regression이 허용 범위 안에 있음.

### PERFORMANCE TRADE-OFF

예:

- Goodput -5%, TTFT -60%
- Goodput +8%, TPOT +12%

처럼 throughput/latency 방향이 서로 다름.

### PERFORMANCE NEUTRAL

모든 주요 performance metric이 As-Is와 실질적으로 유사.

### PERFORMANCE LOSS

Goodput과 latency가 모두 As-Is보다 나쁘거나, architecture가 의도한 target mechanism이 실질적인 performance benefit을 만들지 못함.

### SLO-INFEASIBLE STRESS

모든 후보의 SLO Goodput이 0인 영역. 이 경우 policy winner를 정하지 않고 hardware/SLO boundary로 별도 분류한다.

---

# 15. DP1 Target Workload Domain — 결과와 무관하게 사전 정의

아래 분류는 “현재 누가 이겼는가”가 아니라 **어떤 architecture mechanism을 검증하기 위한 scenario인가**를 기준으로 한다.

## 15.1 Neutral / HBM-fit Domain

목적: 후보가 불필요하게 As-Is를 망가뜨리지 않는지 검증.

- `kv_b16_c32k`
- `rag_1tib_b16`
- `tool_result_bursty`

기대 동작:

```text
No meaningful tiering / data-near benefit
        ↓
C1/C2 Performance Guard
        ↓
HBM-first 또는 current-tier hold
        ↓
As-Is에 수렴
```

## 15.2 C1 Target — Resource-pressure Domain

목적: Data semantics 없이 resource prediction만으로 pressure를 피하는 것이 performance에 실제 도움이 되는지 검증.

- `hbm_pressure_ramp_b64`
- `hbm_bw_shock_b256`
- `host_path_pressure_b64`
- `data_mix_shift_b64`
- `mixed_all_ai_data_b64`

주 mechanism:

- near-future capacity/BW prediction
- pressure relief
- stable migration
- emergency pressure escape

## 15.3 C2 Target — Data-near Compute Domain

목적: Data/Operation 특성을 알고 memory-side compute와 매칭했을 때 As-Is보다 performance가 좋아지는지 검증.

- `rag_8tib_b64_ssd_pim`
- `rag_8tib_b256_ssd_pim`
- `kv_b16_c32k_burst_chbm`
- `kv_b1_c32k_cold_cxl`

주 mechanism:

```text
RAG Vector DB
  → SSD-PIM GEMV similarity

KV Cache
  → Custom HBM / CXL-PNM Attention
  → GPU는 FFN/model-weight path 유지
```

중요: “data-near compute가 있다”는 이유만으로 이득이라고 가정하지 않는다. external activation traffic, remote compute throughput, queueing까지 포함한 end-to-end Performance가 As-Is보다 좋아야 한다.

## 15.4 C2 Target — Data-lifecycle / Temporal Domain

목적: hot/cold/reuse/lifetime prediction이 HBM occupancy와 performance를 동시에 개선할 수 있는지 검증.

- `kv_mispredict_dram_wait`
- `agent_memory_long_lived`

주 mechanism:

- runtime access history
- next-reuse prediction
- DRAM stage / wait
- deferred HBM promotion

## 15.5 Robustness / Failure-boundary Domain

후보의 정상 performance claim과 분리한다.

- `classifier_error`
- `six_tier_capacity_stress`
- B64/B256 × 128K/512K 중 모든 후보 SLO Goodput=0인 cell

---

# 16. Performance Guard / Baseline Bypass

V2에서 C1-R2와 C2-R2 모두 **As-Is HBM-first path를 비교 기준으로 내부에 유지**한다.

후보 policy가 non-HBM placement를 선택하기 전에 다음을 비교한다.

```text
Predicted Candidate Performance
vs
Predicted As-Is/HBM-first Performance
```

## 16.1 C1-R2 Performance Guard

C1은 Data semantics를 사용하지 않으므로 resource model만 사용한다.

비교 대상:

- predicted service interval
- predicted HBM saturation/queue penalty
- migration cost
- target-tier resource headroom

```text
Candidate Benefit <= As-Is + Margin
        ↓
Keep HBM / Current Tier

Candidate Benefit > As-Is + Margin
        ↓
Resource-aware placement
```

예외:

As-Is path가 near-future pressure 때문에 SLO-infeasible할 것으로 예측되면 emergency pressure escape가 허용된다.

## 16.2 C2-R2 Performance Guard

C2는 Data/Operation semantics를 알고 있으므로 operation-aware 비교가 가능하다.

### KV

```text
HBM-first:
  HBM Attention + GPU FFN

Candidate:
  Custom HBM/CXL-PNM Attention
  + activation round-trip
  + GPU FFN
  + migration/staging cost
```

Candidate path가 end-to-end Goodput/TTFT/TPOT 관점에서 HBM-first보다 유리할 때만 offload한다.

### RAG

```text
As-Is:
  vector transfer
  + GPU/CPU similarity GEMV

SSD-PIM:
  local GEMV
  + similarity-score transfer
```

SSD-PIM path가 retrieval latency 또는 sustainable goodput을 실제로 개선할 때만 선택한다.

### Data lifecycle

DRAM stage는 다음 조건을 만족해야 한다.

```text
Expected HBM-wait path cost
<
Immediate As-Is path cost
OR
As-Is path cannot remain SLO-feasible because of pressure
```

이 Performance Guard의 목적은 C2가 “data-aware니까 무조건 다른 tier를 써야 한다”는 식으로 동작하지 않게 하는 것이다.

---

# 17. 현재 결과를 Performance 관점에서 읽는 방법

현재 baseline C1/C2 결과는 V2 설계 전의 문제점을 보여주는 참고점이다.

## 17.1 Baseline C1

현재 feasible workload에서 C1은 대부분 As-Is와 throughput이 비슷하거나 일부 pressure scenario에서 낮다. 즉 **C1 baseline 자체는 아직 명확한 Performance superiority를 입증하지 못했다.**

반면 C1-R에서는 heavy-domain aggregate Goodput이 As-Is 대비 약 **1.064×**까지 올라갔다. 따라서 Resource-centric 접근의 performance justification은 C1-R 이후에서 더 명확해졌다.

## 17.2 Baseline C2

C2 baseline은 heavy-domain aggregate Goodput이 As-Is 대비 약 **0.860×**로 낮다.

그러나 `rag_8tib_b64_ssd_pim`에서는:

- Goodput은 약 0.96× 수준으로 소폭 낮았지만
- TTFT가 As-Is 대비 약 **0.35×**까지 감소

하여 **throughput ↔ retrieval-latency trade-off**가 나타났다.

C2-R에서는 같은 RAG scenario의 Max Sustainable SLO Goodput이 geometric-mean 기준 약 **1.19× As-Is**까지 올라가면서, data-near compute가 throughput/latency 양쪽에서 이득을 만들 수 있는 target domain이 확인되었다.

반대로 `kv_b1_c32k_cold_cxl`처럼 CXL-PNM을 사용할 수 있어도 activation/link/remote-compute 비용 때문에 As-Is보다 느린 경우가 있다. 이 scenario는 V2 Performance Guard가 해당 offload를 **선택하지 않아야 하는 negative-control** 역할을 한다.

---

# 18. 최종 Report 형식

다음 V2 결과부터는 단일 aggregate 표만 보여주지 않는다.

## 18.1 All-scenario Matrix

| Scenario | Domain | Goodput vs As-Is | TTFT vs As-Is | TPOT vs As-Is | Verdict |
|---|---|---:|---:|---:|---|
| ... | C1 Resource-pressure | ... | ... | ... | WIN / TRADE-OFF / LOSS |
| ... | C2 Data-near | ... | ... | ... | ... |

## 18.2 Domain Aggregate

별도로 다음을 계산한다.

- C1 Resource-pressure Domain aggregate
- C2 Data-near Compute Domain aggregate
- C2 Data-lifecycle Domain aggregate
- Neutral/HBM-fit regression aggregate
- All-scenario aggregate

따라서 최종 선택 시 다음 질문에 답할 수 있어야 한다.

```text
1. 이 후보는 어디서 As-Is보다 빨라지는가?
2. 그 workload는 우리가 실제 target으로 하는 workload인가?
3. 어디서 손해를 보는가?
4. 손해 workload에서는 Baseline Bypass로 As-Is에 수렴할 수 있는가?
5. Performance 이득을 위해 Resource/Modifiability에서 무엇을 지불하는가?
```
