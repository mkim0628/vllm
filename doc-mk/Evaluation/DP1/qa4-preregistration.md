---
date: 2026-10-03
dp: DP1
candidates: [C1, C2]
status: preregistered (측정 전 작성, 이후 수정 금지; 변경 시 아래 '변경 이력'에 추가)
evidence: [B+C] (proxy 구현 + 가정 기반 추정)
---

# QA4 Modifiability 사전 등록 (pre-registration)

QA4를 **세 sub-metric**으로 본다: (M1) 변경 module 수, (M2) 개발 공수(man-month), (M3) code-agent 토큰 **비용(달러)**. 이 문서는 측정 전에 작성했고, 임계값은 결과를 보지 않고 추론으로 정했다 (H5, H16).
기존 정의(qa-evaluation-criteria.md §7: module 수 기준 ★★★ <=2 / ★★ 3~5 / ★ >=6)는 M1에 그대로 쓴다. M2, M3와 집계는 **임시 정의**(H8)다.

## 1. 변경 시나리오 (각 시나리오를 C1, C2 각각에 실제로 구현한다)

| ID | 시나리오 | 구체 spec | "동작한다"의 합격 기준 (smoke) |
|---|---|---|---|
| S1 | 신규 memory | `cxl_mem`: CXL.mem DRAM expander (1 TiB, ext 63 GB/s, int 200 GB/s, 지연 600 ns, PNM primitive 없음). 새 profile `SYS-QA4` = {hbm, cxl_mem}. | HBM pressure가 있는 동일 시나리오에서 C1, C2 모두 `cxl_mem`을 목적지로 하는 committed migration이 >= 1건 |
| S2 | 신규 AI data class | `SPARSE_EMBED` (추천/희소 embedding table): 크기 8~64 GiB, 접근 시 일부만 읽음(touch 2%), op class는 기존 `weight_fetch`, hotness .60 / lifetime .92 / reuse .70 / latency .70 / write .05. | 새 class 객체가 trace에 생성되고, 정책이 그 객체에 대해 class를 인식한 결정을 한다: C1은 op hint가 estimator에 도달(비용 추정 not None), C2는 class prior가 registry에 들어가고 class별 tier preference가 쓰임 |
| S3 | 정책 교체 | 같은 pipeline 안에서 "배치 선호 점수"를 만드는 module 하나를 대체: C1은 Data-Memory Affinity Mapper를 latency-first 점수로, C2는 Future Behavior Predictor를 "관측 rate만 쓰는" 예측기로. 교체는 생성자 주입 방식으로 한다. | 교체한 구현의 호출 횟수 > 0 이고 기존 구현 호출 0 (spy로 확인), 결정 수가 변화 |
| S4 | 신규 event type | `SLO_ALERT`: Event Source가 HBM capacity_util >= 0.94이면 telemetry와 함께 발행, 두 후보 모두 이 이벤트로 즉시 decision cycle을 한 번 더 시작. | 이벤트가 Scheduler를 거쳐 정책에 dispatch되고 decision cycle이 실제로 시작됨 (spy count > 0) |

시나리오 선택 의존성: 기존 QA4 표(4개)를 그대로 유지했다. 한 후보에 유리한 시나리오를 추가하거나 삭제하지 않는다 (H4).

## 2. Module 정의 (설계 문서 component 이름 기준)

세는 단위는 **파일이 아니라 설계 문서의 component**다 (한 파일에 여러 component가 있어도 구분한다). 한 component에서 코드/표/config를 1줄이라도 바꾸면 변경 module 1개이다.

| 구분 | Component |
|---|---|
| 공통 | Event Source, Event/Migration Scheduler(이벤트 schema), Memory Backend I/F plug-in (descriptor/telemetry/binding), TransferHandler, Migration Executor, Access-cost Estimator + 입력 hint 표(op class), Decision pipeline 조립부 |
| C1 | Resource State Monitor, Resource-based Trend Analyzer, Data Eviction Manager, Data-Memory Affinity Mapper (+ 그 hint 표), Destination Tier Selector (C1), Migration Data Selector, Type-agnostic Registry |
| C2 | Data Behavior Monitor, Behavior-based Trend Analyzer, Future Behavior Predictor, Destination Tier Selector (C2), Type-aware Registry (class metadata 포함) |

규칙:
- **Shared module**: 두 후보 모두 바꿔야 하는 component. 각 후보의 module 수에 **모두 포함**한다(후보를 단독 도입한다고 가정). 표에는 shared 수를 따로 표시해 후보 간 차이(differential)를 보인다.
- **Harness는 module이 아니다**: workload 생성기(`scenarios.py`), 접근 비용 physics(`simulator.py`의 `ttft_s`/`tpot_s`), 초기 배치 순서, 테스트. 실제 시스템에서는 "측정 대상 workload/HW"에 해당하며 DP1 설계 component가 아니다. harness 변경은 LOC에도 넣지 않고 별도로 기록만 한다. 단 Event Source 발행 코드는 실제 vLLM 쪽 hook이므로 module로 센다.
- `DATA_PRIORS`의 새 class 항목은 C2에서는 Type-aware Registry의 class metadata(module), C1에서는 harness(물리 모델)로 본다. 이 귀속은 판단이며 한계에 적는다.
- major interface 변경(설계 문서 5.8 Backend I/F 또는 Event schema의 기존 필드 의미 변경)이 필요하면 module 수와 무관하게 M1 = ★. 필드/enum **추가**는 interface 변경이 아니다 (append-only).

## 3. 측정 프로토콜

1. pristine 복사본(`scratchpad/agentD/sim`)을 기준으로, 시나리오별로 **작동하는 최소 변경**을 후보마다 구현한다 (C1 전용 / C2 전용 / shared로 hunk를 나눈다).
2. 합격 기준(1장 smoke)을 실제 실행으로 확인한다. 통과하지 못한 변경은 수정해 다시 확인하며, 통과 전 수치는 쓰지 않는다. 기존 test_sim.py 통과 확인.
3. `diff -u` 기준으로 hunk별 **추가된 비공백·비주석 줄 수(LOC)**를 센다 (삭제 줄은 교체의 일부이므로 별도 합산하지 않고 `loc_deleted`로만 기록). 각 hunk를 component에 귀속한다.
4. 각 touched component의 **현재 크기(LOC)** = 해당 class/함수/표의 AST 줄 수를 pristine 소스에서 잰다 (agent가 읽어야 하는 양의 근거).
5. 측정값은 `results/data/qa4_measured_counts.json`에 기록하고, `tools/qa4_modifiability.py`가 이 JSON에서 아래 공식으로 `qa4_modifiability.json`을 만든다.

## 4. 공식 (모두 ASSUMED 상수, 2026-10-03 기준. 범위로 민감도를 보인다)

기호: n = 변경 module 수, L = 추가 LOC(sim 기준), S = touched module 크기 합(sim LOC).

**M2 man-month**

```
engineer_days = n * c_mod  +  (L * k_real / P) * f_ovh
MM = engineer_days / 21
```

| 상수 | 값(범위) | 의미 |
|---|---|---|
| c_mod | 3일 (2~5) | module당 고정 비용: interface 파악, 설계 리뷰, 통합 테스트 |
| k_real | 5 (3~10) | proxy(sim) LOC -> 실제 vLLM 통합 LOC 배율. 두 후보에 동일 |
| P | 40 LOC/일 (25~80) | 순 생산성 |
| f_ovh | 2.0 (1.5~3.0) | test + review overhead |

**M3 agent 토큰 비용** (model tier별)

```
T_read  = a_read * tpl * k_real * S                      # touched module을 읽는 양
Cbar    = C0 + T_read                                    # 세션 평균 context
N_turns = n0 + n_m * n
T_out   = tpl * k_real * L * n_iter + o_turn * N_turns   # 작성 + 수정 반복 + 턴당 출력
tokens  = mult_tier * (Cbar + N_turns*Cbar + T_out)      # 입력(fresh) + cache read + 출력의 합 (표시용)
cost$   = mult_tier * ( Cbar*p_in + N_turns*Cbar*p_cache + T_out*p_out ) / 1e6
```

| 상수 | 값 | 의미 |
|---|---|---|
| tpl | 12 token/LOC (8~16) | Python 코드 |
| C0 | 25k | system prompt + tool 정의 |
| a_read | 1.5 | 인접 코드/grep 결과 포함 배율 |
| n0, n_m | 10, 5 | 기본 턴 수, module당 추가 턴 |
| n_iter | 2 | 작성 + 수정 |
| o_turn | 300 | 턴당 reasoning/호출 출력 |

가격 (**ASSUMED, 2026-10-03 기준 예시이며 실제 가격표가 아님. 가격은 자주 바뀌므로 `qa4_modifiability.py` 상수만 바꿔 재계산한다**):

| tier | p_in | p_cache | p_out ($/Mtok) | mult_tier (토큰 배율) |
|---|---|---|---|---|
| T1 frontier | 15 | 1.5 | 75 | 0.6 (더 똑똑해 탐색/재시도 감소, ASSUMED) |
| T2 mid-size | 3 | 0.3 | 15 | 1.0 |

토큰은 T1이 적고 달러는 T1이 비싸다. T1이 달러로도 싸려면 mult_tier가 (가격비 역수 =) 0.2 이하여야 한다 (민감도로 보고). 후보 간 순위는 같은 모델 안에서는 가격에 따라 바뀌지 않는다 (같은 공식, 같은 mult). 가격이 바꾸는 것은 절대 크기와 별점 경계 통과 여부다.

## 5. 별점 threshold (결과를 보지 않고 추론으로 정함)

시나리오별로 별점을 매기고, **sub-metric 별점 = 4개 시나리오 중 worst**로 한다 (기존 C1 ★★★ / C2 ★★ 도출과 같은 worst-case 방식). 평균값도 병기한다.

| sub-metric | ★★★ | ★★ | ★ | 근거 |
|---|---|---|---|---|
| M1 module 수 | <= 2 | 3~5 | >= 6 (또는 major interface 변경) | qa-evaluation-criteria §7 그대로 |
| M2 man-month / 변경 1건 | <= 0.5 MM | <= 1.0 MM | > 1.0 MM | 0.5 MM ~ 엔지니어 1명 2주 sprint 안에 흡수, 1 MM = 한 달 전담이면 로드맵 항목이 됨 |
| M3 agent 비용 / 변경 1건 (T1 기준, 더 비싼 tier) | <= $3 | <= $10 | > $10 | $3 ~ 1시간 내외 통상 PR 세션, $10 초과 = 장시간/반복 세션이라 예산 검토 필요 |

**QA4 별점 = 세 sub-metric 별점의 중앙값** (세 값을 항상 병기). 한 sub-metric만 낮은 경우 QA4가 그 값을 따르지 않는 것이 규칙이므로, 어느 sub-metric이 차이를 만드는지 결과 문서에 쓴다.

## 6. 민감도와 보고 규칙

- 상수 low/high 조합(공수는 모두 낮게/높게, 토큰은 tpl, k_real, mult)에서 별점이 바뀌는지 보고한다. 별점이 상수에 의존하면 그렇게 쓴다.
- 결과가 C2에 유리하든 불리하든 그대로 보고한다. 구현 중 합격 기준 때문에 불가피하게 바꾼 부분은 '변경 이력'에 쓴다.
- 한계: proxy(sim) 구현이며 실제 vLLM 통합이 아님, 공수/가격/배율은 가정, agent 세션을 실제로 실행한 측정이 아니라 추정, Evidence는 [B+C] 이하.

## 변경 이력 (측정 중 발생한 구체화. 임계값, 공식, 상수는 바꾸지 않았다)
- 2026-10-03 S1 smoke 시나리오 미지정 -> `dyn_cold_resident_chat_wave` + profile `SYS-QA4`로 구체화. 선택 근거는 pristine control(SYS-1, 기존 dram)에서 두 후보 모두 dram으로 migration이 발생하는 시나리오이며, 새 memory 결과를 보고 고르지 않았다 (처음 시도한 `dyn_idle_kv_holds_hbm`은 control에서도 migration 0이라 제외).
- S1 harness: As-Is 초기 배치 순서 목록에 `cxl_mem`을 추가했다(harness, LOC 미포함, 2줄).
- S2 smoke: 해당 class를 쓰는 기존 시나리오가 없어 `dyn_cold_resident_chat_wave`의 AGENT_MEMORY를 SPARSE_EMBED로 바꾼 임시 trace를 사용. C1은 이 trace에서 migration이 0건이라 합격 기준을 "op hint가 estimator에 도달"(사전 기준 그대로)까지만 확인했다.
- S3, S4 smoke 시나리오: `dyn_cold_resident_chat_wave` (SYS-4).


## 변경 이력 (v2, 2026-10-03, 소유자 결정, **결과를 본 뒤 변경**)

- **집계: 시나리오 최악값 -> 시나리오 평균.** sub-metric 별 = 4개 시나리오 평균값에 위 threshold 적용. 이유: 최악값이 두 후보가 module을 공유하는 한 시나리오(S4, 신규 event)로 정해져 차이가 있는 S1, S2의 신호가 별에서 사라졌다. 변경은 이전 결과(C1 ★★ / C2 ★★)를 본 뒤에 이루어졌으므로 `defined_after_first_look`이다.
- threshold, 공식, 가정 상수, 시나리오는 변경하지 않았다. 이전 최악값 방식 결과는 `qa4_modifiability.json`의 `*_worst_case`에 보존한다.
- 평균 집계 결과: C1 ★★★ / C2 ★★. C2의 M2 평균 0.506 MM은 경계 0.5를 0.006 넘은 값이라 상수에 민감하다(낙관 상수에서는 둘 다 ★★★, 비관 상수에서도 C1 ★★★ / C2 ★★).
