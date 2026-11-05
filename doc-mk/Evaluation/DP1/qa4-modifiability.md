---
date: 2026-10-03
dp: DP1
candidates: [C1, C2]
evidence: "[B+C] proxy 구현(simulator) 기반 측정 + 가정 기반 추정"
status: draft
---

# DP1 QA4 Modifiability — module 수, 공수, agent 토큰 비용

사전 등록: [`qa4-preregistration.md`](qa4-preregistration.md) (측정 전 작성, 임계값은 결과를 보지 않고 결정).
데이터: `results/data/qa4_measured_counts.json`(측정), `results/data/qa4_modifiability.json`(파생), 재생성: `python3 doc-mk/Evaluation/tools/qa4_modifiability.py`.

## 1. 방법 (요약)

1. 변경 시나리오 4개(S1 신규 memory `cxl_mem`, S2 신규 AI data class `SPARSE_EMBED`, S3 정책 교체, S4 신규 event `SLO_ALERT`)를 **C1, C2 각각 simulator 복사본에 실제로 구현**했다. 각 변경은 smoke로 "실제로 쓰이는지" 확인했고(예: S1에서 `cxl_mem`으로 committed migration 발생, S4는 이벤트를 안 고치면 dispatch되어도 무시됨을 negative control로 확인) test_sim.py 26개가 통과한다.
2. 측정: 변경된 **설계 component 수**(M1), 추가 LOC, 건드린 component의 크기. 두 후보가 모두 바꿔야 하는 component는 shared로 표시하고 양쪽에 모두 센다.
3. **M2 man-month** = (n x 3일 + LOC x 5 / 40 x 2.0) / 21. (n = module 수, LOC 5배 = sim -> 실제 통합 배율, 40 LOC/일, test+review 2배.) 모두 **ASSUMED**, 범위로 민감도 확인.
4. **M3 agent 비용(달러)** = 읽은 context + 턴별 cache read + 작성 출력 토큰 x 가격. 토큰 = 측정한 module 크기와 LOC에 12 token/LOC 적용. 가격은 **ASSUMED 예시(2026-10-03)**: T1 frontier $15/$75 (입력/출력 per Mtok), T2 mid $3/$15. T1은 더 똑똑해 토큰을 0.6배만 쓴다고 가정(ASSUMED).
5. 별점(v2, 2026-10-03 소유자 결정): sub-metric은 **4개 시나리오 평균값**에 기준 적용. QA4 = **세 sub-star의 중앙값**. (v1은 worst 시나리오였고 결과를 본 뒤 변경, `defined_after_first_look`; v1 결과는 JSON의 `*_worst_case`에 보존.) 기준: M1 <=2 / 3~5 / >=6 module, M2 <=0.5 / <=1.0 / >1.0 MM, M3 <=$3 / <=$10 / >$10 (T1 기준).

## 2. 결과 (mid 상수, 시나리오당 변경 1건)

| 시나리오 | 후보 | module (shared) | 추가 LOC | man-month (범위) | T1 frontier 토큰 / $ | T2 mid 토큰 / $ |
|---|---|---|---|---|---|---|
| S1 신규 memory | C1 | 1 (1) | 23 | 0.42 (0.16~1.55) | 275k / $0.96 | 458k / $0.32 |
| | C2 | 2 (1) | 29 | 0.63 (0.27~2.13) | 441k / $1.36 | 735k / $0.45 |
| S2 신규 data class | C1 | 1 (1) | 1 | 0.16 (0.10~0.30) | 281k / $0.86 | 468k / $0.29 |
| | C2 | 3 (1) | 3 | 0.46 (0.29~0.89) | 661k / $1.68 | 1,102k / $0.56 |
| S3 정책 교체 | C1 | 2 (0) | 8 | 0.38 (0.21~0.93) | 361k / $1.08 | 602k / $0.36 |
| | C2 | 2 (0) | 7 | 0.37 (0.21~0.88) | 350k / $1.05 | 583k / $0.35 |
| S4 신규 event | C1 | 3 (2) | 11 | 0.56 (0.32~1.34) | 677k / $1.75 | 1,129k / $0.58 |
| | C2 | 3 (2) | 11 | 0.56 (0.32~1.34) | 725k / $1.85 | 1,209k / $0.62 |
| **평균** | C1 | 1.75 | | 0.38 | 399k / $1.16 | 664k / $0.39 |
| | C2 | 2.50 | | 0.51 | 544k / $1.49 | 907k / $0.49 |

변경 component: S1 = Backend plug-in(shared) + C2는 Destination Tier Selector(C2)(type 선호 목록이 memory 이름을 가짐). S2 = op-class hint 표(shared) + C2는 Type-aware Registry class metadata + Destination Tier Selector(C2). S3 = Affinity Mapper(C1) 또는 Predictor(C2) + pipeline 조립부(주입점). S4 = Event schema + Event Source(shared) + pipeline event dispatch.

## 3. 별점 (v2 평균 집계)

| | M1 module (평균) | M2 man-month (평균) | M3 agent 비용 (평균, T1) | **QA4 (중앙값)** |
|---|---|---|---|---|
| C1 | ★★★ (1.75) | ★★★ (0.38 MM) | ★★★ ($1.16) | **★★★** |
| C2 | ★★ (2.50) | ★★ (0.51 MM) | ★★★ ($1.49) | **★★** |

v1(시나리오 최악값 집계)에서는 두 후보 모두 ★★였다. 최악 시나리오가 S4(신규 event)로, Event schema와 Event Source가 두 후보 공유 module이라 둘 다 3개가 되어 차이가 있는 S1, S2의 신호가 사라졌기 때문이다. 이를 결과를 본 뒤 평균 집계로 바꿨다(`defined_after_first_look`). **민감도:** C2의 M2 평균 0.506 MM은 경계 0.5를 0.006 넘은 값이다. 가정 상수를 낙관으로 두면 두 후보 모두 ★★★, 비관으로 두면 C1 ★★★ / C2 ★★이다(구조 대안은 JSON `sensitivity_*`).

## 4. 해석

- **후보 간 차이는 있으나 별점 경계를 넘지 않는다.** 평균으로 C2가 module 2.50 대 1.75, 공수 0.51 대 0.38 MM, T1 비용 $1.49 대 $1.16(약 1.3배)이다. 차이의 원인은 C2가 **type-aware**라 새 memory(S1)와 새 data class(S2)에서 type별 선호 목록과 class metadata를 추가로 고쳐야 하는 것이다. S3(정책 교체), S4(event)는 같다.
- 설계 문서의 기존 논증(S2에서 C2는 Monitor feature + Predictor input까지 4개)은 과대였다. 실제로 Behavior Monitor와 Predictor는 class metadata dict를 일반적으로 읽으므로 **3개**였다.
- S1은 설계 문서 5.8.6의 약속("선호를 capability class로 두면 selector 무변경")이 **sim의 C2 구현에서는 지켜지지 않았다**(memory 이름 목록). 설계대로 capability class로 바꾸면 C2의 S1은 1 module이 된다(분석값, 미측정).
- **토큰과 달러의 순위는 모델 tier 사이에서 갈린다.** T1은 토큰이 T2의 0.6배(예: 평균 399k 대 664k)인데 달러는 약 3.0배($1.16 대 $0.39). T1이 달러로도 싸려면 토큰을 T2의 0.2배 이하로 써야 한다 (모든 시나리오에서 break-even 0.20). 같은 tier 안에서 C1 대 C2 순위는 토큰이든 달러든 같다.
- **M3는 이 규모에서는 후보를 구분하지 못한다.** 모든 변경이 $3 이하이고 두 후보 ★★★이다. 상수가 pessimistic(k_real 10, tpl 16, T1 토큰 0.8배)일 때만 ★★로 내려간다.

## 5. 민감도

| 상수 조합 | C1 (M1/M2/M3 -> QA4) | C2 (M1/M2/M3 -> QA4) |
|---|---|---|
| optimistic | ★★/★★★/★★★ -> ★★★ | ★★/★★★/★★★ -> ★★★ |
| **mid (채택)** | ★★/★★/★★★ -> ★★ | ★★/★★/★★★ -> ★★ |
| pessimistic | ★★/★/★★ -> ★★ | ★★/★/★★ -> ★★ |

별점은 공수 상수에 의존한다(★★★ ~ ★★). 그러나 **어느 조합에서도 C1과 C2의 QA4 별점은 같다.** 구조 정의 민감도: S4의 Event schema를 Event Source에 포함하고 S1에서 C2의 선호를 capability class로 두면 QA4는 C1 ★★★ / C2 ★★★이다(C2의 M1은 S2 때문에 ★★ 유지). 즉 별점은 module 경계 정의에 의존한다.

## 6. 한계

- **proxy 구현**: simulator 안의 변경이며 실제 vLLM 통합이 아니다. LOC는 5배 배율(범위 3~10)로 환산했고 이 배율이 절대 공수를 좌우한다. 배율은 두 후보에 동일하므로 후보 간 순위에는 영향이 작다.
- 공수 상수(3일/module, 40 LOC/일, 2배), 토큰 상수, 가격, T1 토큰 배율 0.6은 모두 **가정**이다. agent 세션을 실제로 돌린 측정이 아니라 추정이다.
- module 귀속에는 판단이 들어간다(예: `DATA_PRIORS`를 C2에서만 module로 셈, Event schema와 Event Source 분리, config LOC를 코드와 같게 셈). 한 시나리오씩 한 가지 구현만 했고 같은 목적의 다른 구현은 시도하지 않았다.
- S2의 C1 smoke는 estimator 입력 도달까지만 확인했다(해당 trace에서 C1 migration 0건).
- Evidence는 [B+C]이며 QA4는 기존 기준대로 architecture argument가 주 근거이다. 위 별점은 그 보조 정량화이다.
