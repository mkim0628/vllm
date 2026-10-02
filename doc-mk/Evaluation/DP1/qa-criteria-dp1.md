# DP1 QA Criteria (DP1 보조 평가 기준)

> 이 문서는 [`../qa-evaluation-criteria.md`](../qa-evaluation-criteria.md)(공통 QA1~4, 별점, Evidence)를 **대체하지 않는다.**
> 공통 별점은 그대로 산출하고 결과에 계속 표기한다. 이 문서는 (1) DP1의 집계 규칙과 (2) 같은 공통 별점 안에 있는 후보를 구분하기 위한 **세부 tier**, (3) C1 vs C2 직접 비교 방법을 정의한다.
> 구간 값은 `sim/dp1_rating.json`(version `dp1-rating-v1`), 계산은 `sim/dp1_rating.py`이다.

## 0. 왜 만들었나

공통 별점은 구간이 거칠다. 예: QA1은 ratio ≥ 1.10이면 전부 ★★★이고, QA3는 < 65%이면 전부 ★이다. 첫 통합 결과에서 C1(x1.18, 39%)과 C2(x1.33, 50%)가 같은 별로 보였다. 또 QA2를 시나리오 간 worst-case로 집계하면 "Baseline도 SLO를 못 맞추는 시나리오" 하나가 값을 정해 후보 차이가 사라졌다.

**공통 룰은 DP2~DP4에 영향을 주므로 바꾸지 않는다.** DP1 안에서만 보조 척도를 둔다.

> **공개해야 할 사실:** 이 구간은 첫 통합 결과(공통 별점)를 본 뒤에 정의했다 (`defined_after_first_look: true`). 즉 blind하게 정한 값이 아니다. 그래서 (a) 별점 산정에는 쓰지 않고 보조로만 쓰며, (b) 새 benchmark나 다른 DP에서 구간이 타당한지 재확인하기 전까지 탐색적(exploratory) 지표로 취급한다. 구간을 바꾸면 version을 올리고 이전 결과를 다시 계산한다.

## 1. 집계 규칙

| 항목 | 규칙 |
|---|---|
| 집계 대상 | **comparison-valid** 시나리오만 (Baseline이 SLO를 만족). infeasible / saturated는 목록에는 남기되 집계에서 제외 |
| 집계 단위 | set별(Common / Stress / Dynamic)과 **combined** (3개 set의 comparison-valid 합) |
| QA1 ratio | 시나리오별 (후보 Max SLO goodput) / (Baseline)의 **geometric mean**. 95% CI는 같은 seed·trace끼리 paired한 per-seed geometric mean의 t 구간 (공통 QA1과 같은 점 추정) |
| QA2 | 시나리오별 TTFT/TPOT percentile을 구한 뒤 시나리오 간 **median**(대표값)과 worst-case(보조)를 모두 표기. 공통 별점의 worst-case 집계도 계속 병기 |
| QA3 | comparison-valid 시나리오 평균 (임시 정의: `HBM occupancy x SLO 만족 비율`) |
| 유의성 | 후보 간 차이가 CI 이내이거나 1% 미만이면 tie |

## 2. 세부 tier (공통 별점의 하위 구간)

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

## 3. C1 vs C2 직접 비교 (head-to-head)

지금까지의 모든 값은 "Baseline 대비 몇 배"였다. 직접 비교는 **같은 시나리오·같은 seed·같은 trace에서 C2와 C1을 서로 비교**한 값이다.

- **Goodput ratio (C2 / C1)**: 시나리오별. per-seed paired 비율의 평균과 95% CI. CI 밖이고 1% 이상 차이나면 우열, 아니면 tie. combined에서는 시나리오 간 geometric mean(+CI)과 C2 우세 / tie / C1 우세 개수를 표기.
- **Latency 우열**: 위 §2의 P99 -> P95 -> P50 규칙.
- **Utilization 차이 (pp)**: C2 - C1.
- **Migration bytes 비율**: 이득의 비용 (C1 vs C2).

직접 비교가 필요한 이유: 두 후보가 모두 Baseline을 이기면 같은 별로 보여도, 서로의 우열은 이 비교로만 보인다.

## 4. 결과 문서 표기 규칙

- 공통 최종 QA 표(별점 + 값)는 그대로 둔다.
- 그 아래에 "DP1 세부 평가" 표를 추가한다: 세부 tier + 값 + (comparison-valid n) + C1 vs C2 직접 비교.
- 별점이 같아도 값이 다르면 **항상 값을 병기**한다.
- 세부 tier는 별점 산정에 쓰지 않는다 (보조). 결론에서 후보 우열을 말할 때는 직접 비교 결과를 근거로 쓰고, 이 문서의 한계(§0 공개 사항)를 함께 적는다.

## 5. 재현

~~~text
cd doc-mk/Evaluation/DP1/sim
python3 loop_run.py --final                                   # SYS-1~5 qa_result.json (P50/P95 포함)
python3 dp1_rating.py ../results/data/SYS-4/qa_result.json    # 세부 tier + head-to-head -> dp1_rating.json
python3 ../../tools/gen_dp1_result.py                         # 결과 문서 생성
~~~
