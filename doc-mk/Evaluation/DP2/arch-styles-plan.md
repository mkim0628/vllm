# DP2 아키텍처 스타일 비교 평가 계획 (사전 등록)

> 날짜: 2026-10-10. 상태: **사전 등록** (후보 평가 실행 전에 작성, 이후 수정 금지; 변경은 맨 아래 '변경 이력'에만 추가).
> 규칙: `.claude/skills/evaluation/SKILL.md`, 공통 QA 정의 `../qa-evaluation-criteria.md`. 기존 DP2 평가(C1 대 C2, `results/2026-10-06_dp2-qa-evaluation.md`)는 **그대로 보존**하며 이 평가는 별도다 (SKILL H9). Evidence는 모두 [B+C]다 (H6).

## 1. 왜 새 평가인가 (범위 변경)

2026-10-10 사용자 결정으로 DP2의 정의가 바뀌었다.

- 이전: Turn마다 Prefill 위치 `n_p`와 Decode 시작 위치 `n_d`를 (노드, Tier)로 결정. 후보 축 = 결정 **시점** (C1 inline / C2 사전 계획).
- 지금: **노드 내**에서 Turn 시작 시 KV 구간의 attention을 어디서 실행할지(GPU에서 staging 후 실행 `GPU_STAGE` 또는 Tier 제자리 실행 `IN_SITU`)를 결정. P/D를 구분하지 않는다. 노드 선택은 DP4 소관이다. 후보 축 = **아키텍처 스타일**: 1안 **중앙 Dispatcher**(Master–Worker) 대 2안 **Blackboard**(공유 Task Board + 자율 Knowledge Source).
- QA: **QA1 Throughput, QA2 Latency, QA3 HBM 점유율(낮을수록 좋음), QA4 Modifiability** (사용자 결정). 기존 QA5(Scalability)는 노드 수 확장이 DP4로 이동해 이 평가에서 제외한다.

## 2. 후보 (같은 입력·같은 출력 값, 다른 아키텍처)

공통: 노드 선택 규칙은 모든 후보가 같다(`assign_node`): History가 있으면 소유 노드, 없으면 snapshot에서 HBM 여유가 가장 큰 노드. 후보는 그 노드 안에서 **Decode attention이 실행될 Tier**(n_d tier)만 정한다. Prefill은 항상 그 노드의 GPU에서 chunked로 실행한다(노드 내 P/D 분리 없음). 장애(`fault`) 구간은 모든 후보가 Baseline 규칙으로 되돌아간다(조정 요소 중단 시 안전 복귀).

| 후보 | 아키텍처 스타일 | 결정 주체와 정보 | 결정 방식 |
|---|---|---|---|
| **Baseline-GPU-local** (T_ref) | 없음 (vLLM As-Is) | — | 모든 attention을 GPU에서. History가 HBM/HBF에 있으면 그대로, 그 밖이면 HBM으로 staging(swap-in). 새 KV는 HBM |
| **A Dispatcher** | Master–Worker. 중앙 Planner가 Turn 시작 시 동기 단일 패스로 확정 | 중앙 / **telemetry snapshot**(갱신 주기 50 ms) + estimator(오차 ε, 기본 0) | 기존 Cost(SLO 분율 합, `policies.py`)에 **HBM 기회비용 항 λ_HBM**을 더해 argmin. 결정은 scheduler에서 직렬(결정 비용 `t_ref × k / 64`, k = Tier 수) |
| **B Blackboard** | 공유 Task Board에 Task를 게시, Tier Admission Agent와 GPU HBM Budget Admission이 자율적으로 claim | 분산 / 각 agent의 **라이브 로컬 측정**(estimator 없음) | 규칙(아래 §2.2). 게시→claim 지연 `t_bb`(병렬, 직렬화 없음) |

### 2.1 A의 Cost와 λ_HBM
기존 Cost(SLO 분율: TTFT_est/SLO + TPOT_est/SLO + handoff stall + 외부효과)에 다음 항을 더한다 (HBM Tier에 decode 시 KV를 상주시키는 후보에만).

```
price = c × u² × Δ / cap        u = min(1.5, (사용 + Δ) / cap),  cap = 0.8 × HBM KV pool,  Δ = 이 plan이 HBM에 더하는 KV 바이트
```
`c = 1.0` (ASSUMED, **한 번 정하고 시나리오별로 조정하지 않는다**). 민감도 c ∈ {0, 0.25, 1, 4}를 보고한다(c = 0은 shadow price 없는 Dispatcher).

### 2.2 B의 규칙 (Tier Admission Agent + HBM Budget Admission)
1. History가 `hbm`이면 `hbm`, `hbf`이면 `hbf`(GPU 직접 읽기)로 실행한다 (KV가 있는 곳에서 실행).
2. History가 attention 가능한 Tier(`custom_hbm`, `cxl_pnm`)에 있으면 해당 Tier agent가 **측정된 headroom** 조건에서 claim한다: 그 Tier의 현재 offload attention 시간 ≤ θ × SLO_TPOT. 만족하면 `IN_SITU`, 아니면 `GPU_STAGE`로 거절.
3. History가 `dram`/`ssd_pim`에 있거나 새 KV이면 `hbm`을 시도한다. **HBM Budget Admission**: (여유 + 축출 가능) ≥ 필요량이고 HBM 사용률 ≤ ρ_hi이면 허용.
4. 3이 거절되면 offload Tier agent를 `custom_hbm`, `cxl_pnm` 순으로 시도한다(같은 headroom 조건과 용량 조건). 모두 거절이면 Task는 대기한다.

상수: **θ = 0.8, ρ_hi = 0.85, t_bb = 0.5 ms** (ASSUMED, 시나리오별 조정 금지). 민감도: θ ∈ {0.6, 0.8, 1.0}, ρ_hi ∈ {0.7, 0.85, 0.95}, t_bb ∈ {0.1, 0.5, 2} ms.

## 3. 시나리오 (benchmark.md §11)

기존 DP2 시나리오에서 **노드 간(P/D 풀, 링크) 현상을 다루는 것을 제외**하고, 토폴로지를 **통합 노드**(P 노드 없음, 노드 = Prefill + Decode, 노드 수 = 기존 D 노드 수)로 바꾼다. 노드 수·부하 grid의 변경은 **Baseline만 돌려 정해** 후보 실행 전에 고정한다(`results/iterations/loop-log.md` §3).

| 구분 | 시나리오 (이름 앞에 `n_`) | 비고 |
|---|---|---|
| Common (3) | `cb_kv_8k_b32`, `cb_kv_8k_b32_ramp`, `cb_mixed_8k_b32` | 노드 1개 |
| Stress (10) | `dp2_turn_hbm_small_tool`, `dp2_turn_dram_small_tool`, `dp2_turn_hbf_hist`, `dp2_turn_ssd_hist`(대조군), `dp2_tool_large_result`(대조군), `dp2_decode_heavy_p_idle`, `dp2_long_ctx_decode_offload`, `dp2_session_size_skew`, `dp2_stale_telemetry`, `dp2_planner_fault_fallback`(안전성) | |
| Dynamic (3) | `dyn_turn_demotion_wave`, `dyn_load_ramp_burst`, `dyn_decode_phase_shift` | |
| 제외 (범위 밖, 노드 간) | `dp2_prefill_burst_p_saturated`, `dp2_internode_link_contention`, `dyn_p_node_degrade` | DP4 소관 |

시스템: **SYS-H100, SYS-B200 통합** (H19). seed 11/23/37/53/71, 모델·SLO는 공통(Llama-3.1-70B BF16, TTFT P99 ≤ 2 s, TPOT P99 ≤ 50 ms).

## 4. QA 정의 (결과를 보기 전 고정)

| QA | 정의 | 별 경계 |
|---|---|---|
| QA1 | 시나리오별 부하 sweep의 Max SLO goodput(각 후보 자기 최적 부하). 후보÷Baseline 비의 기하평균 (comparison_valid 쌍) | `qa-criteria-dp2.md` §6 값 그대로: ★ < 0.97 / ★★ 0.97~1.30 / ★★★ ≥ 1.30. 공통 기준(0.90/1.10) 병기 |
| QA2 | Baseline의 최적 부하(iso-load)에서 (TTFT, TPOT) × (P50, P95, P99) 6개 개선 배수(Baseline÷후보)의 기하평균. TTFT·TPOT 별도 행 | ★ < 0.95 / ★★ 0.95~1.25 / ★★★ ≥ 1.25. 공통 기준(P99 2 s / 50 ms) 병기 |
| QA3 (**임시 정의, 사용자 결정 2026-10-10**) | **HBM KV 점유율**: 측정 구간에서 시간 평균 HBM KV 점유(GiB, 노드 합, 예약 포함, 배경·상주 점유 포함)를 Baseline 최적 부하(iso-load)에서 비교. 비율 = 후보÷Baseline, **낮을수록 좋음**. **후보의 `slo_met_frac`이 Baseline보다 1%p 이상 낮은 쌍은 "같은 성능" 조건을 만족하지 못하므로 QA3 집계에서 제외하고 개수를 보고**한다 | 절감 배수 = 1/비율. ★ < 0.95 / ★★ 0.95~1.25 / ★★★ ≥ 1.25 (DP1 QA3 경계와 같은 값). 요청에 귀속되는 점유(순증)와 풀 대비 비율은 진단 |
| QA4 | 변경 시나리오 4종을 후보마다 simulator 복사본에 구현해 module 수·공수·에이전트 비용을 측정 (`qa4-preregistration-arch.md`) | 공통 (M1 ≤ 2 / ≤ 5, M2 ≤ 0.5 / ≤ 1.0 MM, M3 ≤ $3 / ≤ $10) |
| 진단 | 결정 지연, Tier 선택 분포, 거절(claim 실패) 수, 폴백 수, 점유 peak, U_useful(기존 QA3, 진단으로 병기) | |

집계: comparison_valid 쌍(Baseline이 SLO를 일부 만족하고 후보와 구분 가능). saturated·infeasible은 별도 표기. 쌍별 paired-by-seed 판정, 95% CI t(0.975, 4) = 2.776, 물질성 1% (기존과 동일).

## 5. 선택 규칙과 우선순위

별 합계(QA1~QA4)가 높은 후보를 선택한다. 합계가 같을 때만 우선순위 위에서부터 처음 갈리는 QA가 결정한다. 우선순위 **제안: QA1 > QA3 > QA2 > QA4** (소유자 확정 전 = proposal, `qa_priority.json`). 우선순위를 뒤집었을 때의 결과(결정 민감도)와 별 경계 근처 값을 함께 보고한다 (H13).

## 6. 오차·민감도 (H17)

- A는 estimator에 의존한다: 오차 ε(lognormal σ) 0 / 0.2 / 0.4 / 0.6 sweep, 정책 상수 재조정 금지. B는 estimator를 쓰지 않고 측정값만 쓰므로 ε 영향이 없다고 가설을 둔다(측정 노이즈 모델은 없음, 한계로 기재).
- telemetry 갱신 주기 {0.01, 0.05, 0.5, 1.0} s (A는 snapshot 의존, B는 라이브).
- 결정 비용 `t_ref` {0.1, 1, 10} ms (A의 직렬 결정), 게시→claim 지연 `t_bb` (B).
- λ_HBM `c`, B의 θ, ρ_hi (위 §2).
- 민감도는 대표 6개 시나리오, seed 3개, Baseline 최적 부하 고정으로 실행한다 (`sens.py`와 같은 방식).

## 7. 사전 등록 가설 (실행 전)

1. HBM이 넉넉한 시나리오(`dp2_turn_hbm_small_tool`, `dp2_tool_large_result`): A, B ≈ Baseline (saturated 가능). 후보가 Baseline보다 나빠지지 않는다.
2. HBM 압박 시나리오(`cb_*`의 x0.12 풀, `dp2_turn_dram_small_tool`, `dp2_long_ctx_decode_offload`): 두 후보 모두 offload Tier를 써서 Baseline보다 QA1이 높거나 같고 QA3(HBM 점유)가 낮다.
3. A 대 B: A는 전역 Cost로 QA1·QA3에서 B와 같거나 앞서고, B는 telemetry가 stale한 시나리오(`dp2_stale_telemetry`)와 ε가 큰 조건에서 A보다 덜 나빠진다. (가설이며 결과가 반대일 수 있다.)
4. QA4: A는 새 Cost 항·정책 교체(교차 관심사)에서, B는 새 Tier·새 신호(국소 확장)에서 변경 module이 적다.
5. `dp2_planner_fault_fallback`: 두 후보 모두 장애 중 Baseline 수준(≥ 0.97 ×)을 유지한다.

## 8. 절차

1. test suite 통과(`test_sim.py`) + 기존 결과 한 점 재현(수치 일치). 새 후보·metric 추가 후에도 기존 후보 결과가 같음을 대조군으로 확인.
2. **Baseline-only 제어 실행**으로 시나리오 grid와 lam0를 정해 `loop-log.md` §3에 기록(후보 실행 전).
3. 후보 코드는 기능 점검용 소규모 실행만 하고(평가에 쓰지 않음, loop-log에 공개), 상수는 §2 값으로 고정.
4. Common + DP2 시나리오를 SYS-H100/B200에서 seed 5개로 실행, raw를 `results/data/arch/`에 저장.
5. Baseline보다 나쁜 후보·시나리오는 Baseline-regression loop(SKILL §5)를 따른다. 지는 시나리오를 숨기지 않는다.
6. QA4, 민감도, 결과 문서(`results/2026-10-10_dp2-arch-styles.md`, 7개 섹션)를 작성한다.

## 변경 이력
- 2026-10-10 최초 작성(사전 등록).
