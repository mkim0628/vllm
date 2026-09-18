# DP1 Reinforcement Design — C1-R / C2-R

> 목적: `dp1-c1-c2-baseline-assessment.md`에서 발견된 문제를 바탕으로 **C1과 C2의 기본 철학은 유지하면서** 각각 한 단계 보완 설계를 정의한다.
>
> - C1-R = Resource-centric + Decision Stability
> - C2-R = Data-centric + Feasibility-first + Recovery Stability

---

# 1. 설계 원칙

보완 설계의 목적은 C1을 C2처럼 만들거나 C2를 C1처럼 만드는 것이 아니다.

각 후보의 정체성을 유지한다.

```text
C1-R
Memory Resource State가 1차 기준
+ migration/hysteresis 안정화

C2-R
Data Characteristics가 1차 기준
+ hard feasibility filter
+ migration/fallback 안정화
```

즉 최종 비교는 다음 질문에 답하는 것이 목적이다.

> “각 접근법을 합리적으로 한 번 더 보완했을 때도 어떤 trade-off가 남는가?”

---

# 2. C1-R — Stable Resource-centric Placement

## 2.1 Baseline C1 문제

Baseline C1은:

- Heavy Goodput ≈ As-Is
- Resource pressure 대응은 안정적
- Migration 16.27/run

으로 C2보다 안정적이지만, 현재 tier를 계속 유지할지 새 tier로 옮길지를 판단할 때 **migration cost와 hysteresis가 없다.**

## 2.2 보완 1 — Score-delta Migration Gate

현재:

```text
Best Score Tier != Current Tier
        ↓
Migration
```

보완:

```text
Best Score Tier != Current Tier
        ↓
Score Gain 계산
        +
Migration Cost 계산
        ↓
Gain > Cost + Margin ?
 ├─ Yes → Migration
 └─ No  → Current Tier 유지
```

현재 baseline evaluator에서는 다음 형태의 normalized gate를 사용한다.

```text
migration_transfer_time =
    object_size / min(src_ext_bw, dst_ext_bw)

migration_penalty =
    min(0.20, migration_transfer_time / 0.5 × 0.05)

required_gain =
    base_margin + migration_penalty
```

기본 base margin은 약 0.08로 둔다.

## 2.3 보완 2 — Minimum Residency

한 번 이동한 object가 짧은 시간 안에 다시 반대 방향으로 이동하지 않도록 한다.

```text
MIN_RESIDENCY = 10 sec
```

단, current tier가 hard pressure threshold를 넘으면 residency를 무시하고 탈출 가능하다.

## 2.4 보완 3 — High/Low Watermark

Resource pressure가 threshold 주변에서 흔들릴 때 oscillation을 줄인다.

```text
High Watermark = 0.90
Low  Watermark = 0.75
```

- High 이상: migration 허용/촉진
- Low 이하: 현재 tier 유지 성향 강화

## 2.5 C1-R의 기대 효과

- Migration 감소
- Resource oscillation 감소
- C1의 낮은 decision overhead 유지
- Data Characterization 없이도 resource stability 향상

---

# 3. C2-R — Feasibility-first Data-centric Placement

## 3.1 Baseline C2 문제

Baseline C2:

- Heavy Goodput / As-Is = 0.860
- Migration = 48/run
- Fallback = 75.81/run

Fallback 원인의 97.8%가 다음 세 가지다.

1. predicted_first_response_violation
2. operation_infeasible
3. predicted_tpot_violation

즉 Data prediction의 품질보다 **선택 순서 자체가 문제**다.

## 3.2 보완 1 — Hard Feasibility Filter Before Affinity

Baseline:

```text
All Tiers
  ↓
Affinity score
  ↓
Best Tier
  ↓
Operation / latency check
  ↓
Fallback
```

C2-R:

```text
All Tiers
  ↓
Capacity feasibility
  ↓
Operation feasibility
  ↓
Latency feasibility
  ↓
Feasible Tier Set
  ↓
Affinity score
  ↓
Best Tier
```

### KV Cache

Non-HBM tier는 다음을 모두 만족해야 candidate가 된다.

- full Attention primitive 지원
- predicted TPOT ≤ configured decode budget
- capacity headroom 존재

### RAG

RAG는 “2초 초과하면 무조건 fallback”처럼 반복적으로 처리하지 않는다.

각 tier의 retrieval cost를 먼저 계산하고:

- SLO를 만족하는 후보가 있으면 그 후보들만 ranking
- 전부 SLO를 못 맞추면 **minimum-cost infeasible tier를 stable hold**하고 같은 이유로 반복 fallback하지 않음

즉 SLO 불가능 영역을 “prediction error”와 구분한다.

## 3.3 보완 2 — Current-tier Hold + Migration Benefit Gate

C2도 다음 조건을 만족할 때만 이동한다.

```text
Affinity/Resource Improvement
    >
Migration Cost
  + Hysteresis Margin
```

Current Tier가 여전히 feasible하면 작은 score 변화만으로 이동하지 않는다.

## 3.4 보완 3 — Reason-specific Cooldown

Fallback reason별 retry 조건을 다르게 한다.

| Reason | Retry Trigger |
|---|---|
| low_classifier_confidence | 새로운 runtime sample N개 축적 |
| predicted_tpot_violation | batch/context/resource condition 변화 |
| operation_infeasible | capability/config 변화 또는 target tier 변경 |
| predicted_first_response_violation | resource/load 또는 retrieval size 변화 |
| no_capacity_candidate | capacity pressure가 low watermark 아래로 감소 |

같은 이유로 매 tick fallback하지 않는다.

기본 cooldown:

```text
FALLBACK_COOLDOWN = 10 sec
```

## 3.5 보완 4 — Deferred HBM Promotion을 State Machine으로 고정

Baseline에서 DRAM wait path는 들어갔지만 fallback re-evaluation과 섞여 있었다.

C2-R에서는 상태를 명확히 분리한다.

```text
NORMAL
  ↓ prediction error + HBM pressure
WATCH
  ↓ HBM relief soon & next reuse later
DRAM_STAGED
  ↓ HBM <= low watermark
PROMOTE_PENDING
  ↓ migration complete
NORMAL@HBM
```

DRAM_STAGED 상태에서는 affinity ranking을 매번 다시 돌리지 않는다.

## 3.6 보완 5 — Confidence Debounce

한두 sample의 변화로 hot/cold 판단이 뒤집히지 않도록 한다.

- 최소 sample 수 이전에는 prior-dominant
- confidence가 threshold를 넘기 전에는 aggressive demotion 금지
- runtime mismatch가 연속해서 관찰될 때만 state transition

이 방식은 classifier error에 민감한 C2의 약점을 줄인다.

---

# 4. C1-R / C2-R 공통 Migration Safety

두 후보 모두 아래 공통 gate를 사용한다.

```text
1. Target feasible?
2. Current tier still feasible?
3. Expected benefit > migration cost?
4. Minimum residency satisfied?
5. Migration budget available?
```

단, C1-R은 benefit을 Resource Utility 변화로 계산하고, C2-R은 Data Affinity + Resource Utility 변화로 계산한다.

---

# 5. 보완 실험 가설

## H1 — C1-R

Baseline C1 대비:

- Goodput: 95% 이상 유지
- Migration: 20% 이상 감소
- Resource Utilization Index: 동일 이상
- Decision overhead 증가는 최소

## H2 — C2-R

Baseline C2 대비:

- Fallback count: 75.81/run → **20/run 이하**
- Migration: 48/run → **24/run 이하**
- Heavy Goodput / As-Is: 0.860 → **0.95 이상**
- Resource Utilization Index: 0.737 → **0.78 이상**
- classifier-error robustness는 baseline보다 악화되지 않음

위 수치는 설계 tuning target이지 별점 기준을 바꾸는 것이 아니다.

---

# 6. 재평가 후보

다음 다섯 후보를 동일 trace에서 비교한다.

```text
As-Is-HBM-first
C1-memory-centric
C1-R stable-resource
C2-data-centric
C2-R feasibility-stable
```

Baseline C1/C2는 그대로 유지하여 “보완 전/후”를 직접 비교한다.

---

# 7. 선택 시 해석 기준

보완 후에도 다음 trade-off는 남을 수 있다.

### C1-R이 유리한 경우

- Data type이 자주 추가됨
- low-overhead가 중요
- workload behavior prediction 신뢰도가 낮음
- Resource pressure가 placement의 지배 변수

### C2-R이 유리한 경우

- KV / RAG / Agent / Adapter 등 data heterogeneity가 큼
- Memory-side compute capability가 다양함
- cold/long-lived data 비중이 큼
- runtime history가 충분히 축적됨

따라서 최종 선택은 단순 “별이 더 많은 후보”가 아니라, **보완 후에도 남는 구조적 trade-off**를 근거로 한다.
