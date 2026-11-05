# DP2 — Cost Model 구성과 C2 Late Validation (설계 보충)

> 슬라이드: [`DP2-cost-model-late-validation.pptx`](DP2-cost-model-late-validation.pptx) (2장, `Evaluation/tools/gen_dp2_design_slides.py`로 생성). 이 문서는 슬라이드 내용을 글로 정리한 것이다. 구현 기준은 `Evaluation/DP2/sim/dp2sim/policies.py`(Cost)와 `engine.py`(`c2_validate`), 아키텍처는 [`vllm-cost-model-prefill-decode-execution-planning-architecture.md`](vllm-cost-model-prefill-decode-execution-planning-architecture.md).
> 수치 근거는 simulation [B+C]이며, 검증 비용(20 us)·큐 한도·tol은 ASSUMED다.

# 1. Cost Model

## 1.1 정의

`Cost(n_p, n_d)` = 이 plan이 **이 요청**에 주는 SLO 소모량 + **다른 요청**에 주는 SLO 소모량. 모든 항을 SLO 분율(무차원)로 맞춰 TTFT와 TPOT를 같은 척도로 더한다. n_p는 Prefill 실행 노드, n_d는 Decode 시작 위치(노드, Tier). 후보 (n_p, n_d) 쌍 전체의 Cost를 계산해 최소를 고른다.

(초 단위로 더하면 TTFT 초와 Decode 초가 같은 무게가 되어 TPOT 외부효과를 과대평가했기 때문에 v1에서 v2로 바꿨다. 평가 전 변경, `loop-log.md` 0.1.)

## 1.2 구성 항

| 구분 | 항 | 의미 | 입력 상태 |
|---|---|---|---|
| 이 요청의 TTFT | `TTFT_est / SLO_TTFT` | 대기(wait) + History 전송·승격(stage) + Prefill 시간 (chunk 단위 iteration 시간 x 횟수) | n_p의 대기 Prefill 토큰·작업 수, 실행 중 Decode, History KV 위치(Tier), Tier·링크 BW |
| 이 요청의 TPOT | `TPOT_est / SLO_TPOT` | n_d에 합류한 뒤 iteration 시간. Tier별 attention 경로가 다름(GPU HBM, HBF 직접 읽기, ScHBM·CXL-PNM 오프로드) | n_d의 Tier별 Decode 수·컨텍스트 합, Tier descriptor |
| KV 이동 | `T_handoff / (N_out-1) / SLO_TPOT` (+ HBM evict 시 내리는 시간 / SLO_TTFT) | Prefill 결과 KV를 n_p에서 n_d로 보내는 시간을 출력 토큰에 나눠 반영 | 노드 간 링크·Tier 읽기 동시 흐름 수(공정 분배 BW), KV 크기 |
| 외부효과 X1 | n_p의 실행 중 Decode 지연 / SLO_TPOT | 이 Prefill 때문에 n_p의 기존 Decode iteration이 늘어난 만큼 | n_p의 Decode 수·컨텍스트 |
| 외부효과 X2 | 이후 도착 요청의 TTFT 지연 / SLO_TTFT | n_p 점유로 뒤따르는 요청이 기다리는 시간 (도착률 x Prefill 시간^2 / 2) | n_p의 최근 도착률(EWMA) |
| 외부효과 X3 | n_d의 resident Decode 지연 / SLO_TPOT | 이 요청이 합류해 n_d의 기존 Decode들이 느려지는 만큼 | n_d의 Decode 수·컨텍스트 |

## 1.3 제약과 선택

- feasible 후보: n_d에 이 요청 KV가 들어감(HBM은 evict 가능한 idle KV 포함), `TTFT_est ≤ SLO`, `TPOT_est ≤ SLO`. feasible 후보가 없으면 위반이 가장 작은 후보.
- 선택: argmin Cost. n_p는 분리 가능성을 이용해 세 클래스(History 소유 노드, n_d 자신, 최선의 다른 노드)로 줄여 쌍 전체를 평가한다. 상위 4개를 순위로 보관하고 2~4위를 C2의 백업 후보로 쓴다.
- C1과 C2는 **같은 Cost Model**을 쓴다. 다른 것은 계산 시점, 상태 신선도, plan lifecycle이다. Cost 항 추가는 Cost Evaluator(Strategy) 한 곳이다(QA4 S2: 1 module).
- 추정 오차 ε(lognormal)를 곱해 Cost Model 부정확성에 대한 민감도를 본다(0/0.2/0.4/0.6).

# 2. C2 Late Validation

## 2.1 저장하는 상태값 (plan마다, 후보별: 선택 plan + 백업)

| 구분 | 값 |
|---|---|
| n_p 노드 | `pf_tokens`(대기 Prefill 토큰), `njobs`, `ndec`(실행 중 Decode 수) |
| n_d (노드, Tier) | `free`(Tier 여유 용량), `ndec`(resident Decode 수) |
| 전송 경로 | 경로 자원의 동시 흐름 수 `flows` |
| 후보별 Cost | 저장 시점의 Cost (선택 plan, 백업 각각) |
| 요청·세션 | History KV 위치 (node, tier) |
| 저장하지 않음 | 도착률 EWMA(노이즈가 큼) |

## 2.2 dispatch 직전 검증 (후보를 순서대로)

- **Hard** (하나라도 어긋나면 그 후보 무효): 노드 health, n_d 용량(이 요청 KV가 아직 들어감), History KV 위치가 저장 시점과 같음, n_p 노드 큐가 한도(16,384 토큰) 미만.
- **Soft** (상태 유사도): 현재 상태로 **같은 plan의 Cost를 다시 계산**해 `Cost_now ≤ Cost_저장 x (1 + tol)`이면 유효. 기본 tol 10%, 민감도 5/10/20%. Cost가 줄어든 변화는 허용.
- "현재 상태"는 telemetry snapshot이라 갱신 주기(50 ms)만큼 늦다.
- 한계: 저장한 후보 밖의 노드가 더 좋아진 경우는 잡지 못한다.

## 2.3 mismatch 시 처리

| 단계 | 처리 |
|---|---|
| ① 선택 plan 무효 | 순위 2위 백업 후보로 같은 검증 |
| ② 백업도 무효 | 순위 3, 4위를 차례로 검증 |
| ③ 모두 무효 | Re-planner가 최신 상태로 **동기 재계획**. C1과 같은 결정 비용이 들고 Scheduler 직렬 |
| ④ 재계획도 후보 없음 | 요청을 대기열 앞으로 되돌리고 계획을 다시 요청. 설계상 최종 실패 시 기존 vLLM GPU 실행 경로(안전 경로) |
| 통과 | 해당 plan으로 dispatch. 검증 비용 20 us(ASSUMED) |

## 2.4 평가에서 확인된 것 (`Evaluation/DP2/results/iterations/loop-log.md` §2.1)

- 기본 조건(plan age 평균 약 4 ms): 기존 검증(age 2 s·큐·용량)과 차이 없음(goodput x1.41~1.43).
- N=16/32처럼 결정이 느린 조건: tol이 작을수록 재계획 비율이 0.01에서 0.27~0.37로 늘고 goodput이 x0.75~0.84로 떨어진다. 재계획이 C1과 같은 직렬 결정 비용을 내 C2의 이점이 사라지기 때문이다.
- 시사점: 상태 유사도 검증을 쓰려면 재계획을 싼 경로(백업 후보 확대, top-k 재평가)로 설계해야 한다. 이 변형은 평가하지 않았다.
- 구현은 `val_tol` 옵션(기본 None = 기존 검증)이며 본 평가 결과(`results/2026-10-06_dp2-qa-evaluation.md`)는 기존 검증으로 얻었다.
