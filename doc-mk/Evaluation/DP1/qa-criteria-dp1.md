# DP1 QA Criteria (DP1 별점 기준)

> **DP1의 공식 별점은 이 문서의 기준(§A)으로 산정한다.** 공통 기준(`../qa-evaluation-criteria.md`)의 별점도 **참고용으로 항상 함께 표기**한다 (DP 간 비교 가능성 유지).
> 공통 문서는 수정하지 않았다. 공통 문서의 규칙 2("같은 QA에는 DP 간 동일한 rating rule")와 달라지므로 이 편차는 **의도된 DP1 전용 결정**이며, 별점 옆에 어느 기준의 별점인지 표기한다.
> 구간 값은 `sim/dp1_rating.json`(version `dp1-rating-v2`), 계산은 `sim/dp1_rating.py`이다.

## A. DP1 별점 기준 (공식)

**기준점:** DP1 Common Reference Baseline (Baseline-static: As-Is proxy, migration 없음). DP1은 "Baseline보다 얼마나 나은가"가 설계 정당화의 핵심이므로 **절대 threshold가 아니라 Baseline 대비 효과 크기**로 별점을 매긴다. 별점 척도는 공통과 같은 ★~★★★이다. 집계 대상은 **comparison-valid 시나리오**(Baseline이 SLO를 만족)이다.

| QA | 지표 | ★ | ★★ | ★★★ |
|---|---|---|---|---|
| QA1 Throughput | Max SLO Goodput의 Baseline 대비 ratio (시나리오 간 geometric mean) | < 0.97 | 0.97 ~ 1.30 | >= 1.30 |
| QA2 Latency | Baseline 대비 latency improvement factor: (TTFT, TPOT) x (P50, P95, P99) 6개 improvement(= Baseline / 후보)의 geometric mean | < 0.95 | 0.95 ~ 1.25 | >= 1.25 |
| QA3 Utilization | Useful utilization의 Baseline 대비 변화 (pp, 임시 정의 v3: `HBM occupancy x SLO 만족 비율 x (1 - migration 링크 점유율)`) | < -5 pp | -5 ~ +15 pp | >= +15 pp |
| QA4 Modifiability | 공통 기준 그대로 (변경 module 수) | 공통 | 공통 | 공통 |

**근거 (이 구간을 고른 이유):**

- ★★ 구간이 "Baseline과 같은 수준"이다. 하한 0.97 / 0.95 / -5pp는 측정 잡음(seed 5개 paired CI 약 ±2~10%)보다 작은 열세는 열세로 보지 않는다는 뜻이다.
- ★★★ 상한 1.30은 **migration layer의 설계·운영 복잡도를 정당화하려면 static Baseline 대비 30% 이상의 goodput 이득이 있어야 한다**는 DP1의 판단이다. 공통 기준의 1.10(10%)은 시스템 구성(SYS-1~5)에 따라 같은 후보의 ratio가 1.01~1.26으로 흔들리는 범위 안에 있어 DP1에서는 "robust한 이득"으로 보기 어렵다. QA2 1.25 / QA3 +15pp도 같은 취지의 "눈에 띄는 개선" 수준이다.
- 공통 기준의 절대 threshold(QA2 ≤2 s/≤50 ms, QA3 65%/85%)는 DP1 simulation에서 모든 후보가 SLO 안에 들어가거나 HBM 점유가 workload 크기로 정해져 후보를 가르지 못했다. 그래서 DP1은 Baseline 대비 상대 효과로 본다.

**공개해야 할 사실 (필수 표기):**

1. 이 구간은 **첫 결과를 본 뒤에 정했다** (`defined_after_first_look`). 특히 QA1 상단 1.30은 결과(C1 x1.26, C2 x1.44) 사이에 놓여 별점을 가르는 값이므로, **별점 차이는 이 경계 선택에 의존한다.** 결과 문서에 경계 민감도(§C)를 반드시 함께 싣는다.
2. 별점 경계를 바꾸면 version을 올리고 모든 결과를 재계산한다.
3. QA2의 상대 latency는 모든 후보가 SLO 안에 있어도 개선 비율이 크게 보일 수 있다 (예: P50 99 ms -> 51 ms). 절대값을 반드시 병기한다.
4. 새 benchmark / 다른 DP에서 같은 구간이 타당한지 재확인하기 전까지 **탐색적 기준**이다.

## B. 보조 지표 (같은 별 안의 차이를 보기 위한 세부 tier와 직접 비교)

아래는 §A 별점을 대체하지 않는 진단 지표이다.

### B.0 왜 만들었나

공통 별점은 구간이 거칠다. 예: QA1은 ratio ≥ 1.10이면 전부 ★★★이고, QA3는 < 65%이면 전부 ★이다. 첫 통합 결과에서 C1(x1.18, 39%)과 C2(x1.33, 50%)가 같은 별로 보였다. 또 QA2를 시나리오 간 worst-case로 집계하면 "Baseline도 SLO를 못 맞추는 시나리오" 하나가 값을 정해 후보 차이가 사라졌다.

**공통 룰은 DP2~DP4에 영향을 주므로 바꾸지 않는다.** DP1 안에서만 별도 기준을 둔다.

> 아래 세부 tier 구간도 첫 통합 결과(공통 별점)를 본 뒤에 정의했다 (`defined_after_first_look: true`). 즉 blind하게 정한 값이 아니다. 그래서 (a) 별점 산정에는 쓰지 않고 보조로만 쓰며, (b) 새 benchmark나 다른 DP에서 구간이 타당한지 재확인하기 전까지 탐색적(exploratory) 지표로 취급한다. 구간을 바꾸면 version을 올리고 이전 결과를 다시 계산한다.

### B.1 집계 규칙

| 항목 | 규칙 |
|---|---|
| 집계 대상 | **comparison-valid** 시나리오만 (Baseline이 SLO를 만족). infeasible / saturated는 목록에는 남기되 집계에서 제외 |
| 집계 단위 | set별(Common / Stress / Dynamic)과 **combined** (3개 set의 comparison-valid 합) |
| QA1 ratio | 시나리오별 (후보 Max SLO goodput) / (Baseline)의 **geometric mean**. 95% CI는 같은 seed·trace끼리 paired한 per-seed geometric mean의 t 구간 (공통 QA1과 같은 점 추정) |
| QA2 | 시나리오별 TTFT/TPOT percentile을 구한 뒤 시나리오 간 **median**(대표값)과 worst-case(보조)를 모두 표기. 공통 별점의 worst-case 집계도 계속 병기 |
| QA3 | comparison-valid 시나리오 평균 (임시 정의 v3: `HBM occupancy x SLO 만족 비율 x (1 - migration 링크 점유율)`) |
| 유의성 | 후보 간 차이가 CI 이내이거나 1% 미만이면 tie |

### B.2 세부 tier (공통 별점의 하위 구간)

### QA1 — ratio (vs Baseline)

| Tier | ratio | 공통 별점 | 의미 |
|---|---|---|---|
| 0 | < 0.80 | ★ | 크게 열세 |
| 1 | 0.80 ~ 0.90 | ★ | 열세 |
| 2 | 0.90 ~ 0.97 | ★★ | 소폭 열세 |
| 3 | 0.97 ~ 1.03 | ★★ | parity |
| 4 | 1.03 ~ 1.10 | ★★ | 소폭 우세 |
| 5 | 1.10 ~ 1.25 | ★★★ | 우세 |
| 6 | 1.25 ~ 1.50 | ★★★ | 크게 우세 |
| 7 | >= 1.50 | ★★★ | 매우 크게 우세 |

### QA2 — latency (절대 구간, P99)

| | TTFT P99 | TPOT P99 |
|---|---|---|
| Tier 0 | > 4 s | > 100 ms |
| Tier 1 | <= 4 s | <= 100 ms |
| Tier 2 | <= 2 s | <= 50 ms |
| Tier 3 | <= 1 s | <= 25 ms |
| Tier 4 | <= 0.5 s | <= 10 ms |
| Tier 5 | <= 0.25 s | — |

공통 별점과의 대응: TTFT/TPOT 중 낮은 쪽이 기준 (TTFT Tier 2 & TPOT Tier 2 이상 = ★★★, Tier 1 = ★★, Tier 0 = ★).

**후보 간 latency 비교는 percentile을 P99 → P95 → P50 순으로 본다.** 각 percentile에서 후보의 improvement factor(= Baseline / 후보, TTFT와 TPOT 각각의 geometric mean)를 구하고, `sqrt(TTFT factor x TPOT factor)`의 후보 간 비율이 **5% 이상** 다르면 그 percentile에서 우열을 결정한다. 같으면 다음 percentile로 내려간다. P99 tail이 SLO 안에서 같아도 P95/P50 차이를 드러내기 위한 규칙이다.

### QA3 — useful utilization

| Tier | util | 공통 별점 |
|---|---|---|
| 0 | < 20% | ★ |
| 1 | 20 ~ 30% | ★ |
| 2 | 30 ~ 40% | ★ |
| 3 | 40 ~ 50% | ★ |
| 4 | 50 ~ 65% | ★ |
| 5 | 65 ~ 75% | ★★ |
| 6 | 75 ~ 85% | ★★ |
| 7 | 85 ~ 95% | ★★★ |
| 8 | >= 95% | ★★★ |

Baseline 대비 차이는 pp(percentage point)로 병기한다.

### B.3 C1 vs C2 직접 비교 (head-to-head)

지금까지의 모든 값은 "Baseline 대비 몇 배"였다. 직접 비교는 **같은 시나리오·같은 seed·같은 trace에서 C2와 C1을 서로 비교**한 값이다.

- **Goodput ratio (C2 / C1)**: 시나리오별. per-seed paired 비율의 평균과 95% CI. CI 밖이고 1% 이상 차이나면 우열, 아니면 tie. combined에서는 시나리오 간 geometric mean(+CI)과 C2 우세 / tie / C1 우세 개수를 표기.
- **Latency 우열**: 위 §2의 P99 -> P95 -> P50 규칙.
- **Utilization 차이 (pp)**: C2 - C1.
- **Migration bytes 비율**: 이득의 비용 (C1 vs C2).

직접 비교가 필요한 이유: 두 후보가 모두 Baseline을 이기면 같은 별로 보여도, 서로의 우열은 이 비교로만 보인다.

## C. 결과 문서 표기 규칙

- 최종 QA 표는 **DP1 기준 별점(§A)** 이다. 값(ratio, 개선 배율, pp)과 집계 n을 병기한다.
- **공통 기준 별점**은 별도 표로 항상 함께 싣는다 (참고, DP 간 비교용).
- 별점 경계 **민감도 표**(QA1 상단 경계를 1.10~1.50으로 움직였을 때 별점)를 함께 싣는다.
- 세부 tier와 C1 vs C2 직접 비교(§B)는 보조 진단이다. 결론에서 후보 우열을 말할 때 직접 비교를 근거로 쓰고 §A의 한계를 함께 적는다.

## D. 재현

~~~text
cd doc-mk/Evaluation/DP1/sim
python3 loop_run.py --final                                   # SYS-1~5 qa_result.json (P50/P95 포함)
python3 dp1_rating.py ../results/data/SYS-4/qa_result.json    # DP1 별점 + 세부 tier + head-to-head + 민감도 -> dp1_rating.json
python3 ../../tools/gen_dp1_result.py                         # 결과 문서 생성
~~~


---

# E. QA 우선순위와 후보 선택 (사용자 확정 필요)

[`qa_priority.json`](qa_priority.json): **QA1 > QA2 > QA3 > QA4** (status: proposal). 근거: DP1의 1차 목적은 SLO를 만족하는 처리량·지연이고, 활용률은 그 결과, 확장성은 구조 비용이다.

선택 규칙 (`tools/dp_selection.py`): 별 합계 차이가 2 이상이면 합계가 높은 후보. 차이가 1 이하(동점 포함)이면 우선순위 위에서부터 처음으로 별이 갈리는 QA가 결정한다. 우선순위를 뒤집은 결과도 함께 보고한다.

# F. QA3 정의 변경 이력

- v2: `avg HBM occupancy x (SLO 만족 token / served token)`.
- v3 (2026-10-02): 위 값에 `(1 - migration 링크 점유율)`을 곱한다. 이유: migration에 쓰인 링크 시간은 serving에 쓰이지 않으므로 useful 활용에서 빼는 것이 정의상 맞다. 영향: SYS-4 combined에서 C2 +15pp -> +14pp (DP1 ★★★ 경계 +15pp 아래로, 별 ★★★ -> ★★), C1 +7pp 유지. 변경은 결과를 본 뒤에 이루어졌으므로 `defined_after_first_look`에 해당한다.
