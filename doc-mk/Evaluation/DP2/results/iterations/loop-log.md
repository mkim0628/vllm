# DP2 loop log

SKILL §5 Baseline-regression loop와 사전 등록 기록. 실행 전에 가설을 적고, 실행 후 가설을 고쳐 쓰지 않는다.

# 0회차 — 사전 등록 (Baseline-only 제어와 개발 점검, 후보 vs Baseline 평가 전)

**언제:** M0 사양 초안 이후, 공식 후보 평가 실행 전. 이 기록이 올라간 커밋이 사전 등록 시점이다.

## 0.1 후보 평가 전에 한 변경 (모두 Baseline-only 실행 또는 단위 점검에서 발견)

| class | 변경 | 이유 |
|---|---|---|
| M | Prefill attention을 DP1 `attention_flops(ctx, q)`와 같이 전체 컨텍스트로 계산 | DP1 `prefill_s`와 일치(테스트로 고정) |
| M | Router가 자기 dispatch를 snapshot에 즉시 반영 (local bookkeeping) | 반영 전에는 4개 클라이언트가 같은 P 노드로 몰려 TTFT가 2배(herding). Baseline JSQ와 Planner 모두 같은 정보를 쓴다 |
| M | `node.advance`가 완료 임계(EPS) 이하 항목에서 무한 미세 스텝으로 빠지는 버그 수정 | D-local 실행이 멈춤 |
| B | CB 토폴로지 1P+1D → 4P+1D, 동시성 grid {8..64} | 1P는 8K를 0.34 s에 Prefill해 동시 32가 TTFT 2 s를 못 지킴 (Baseline infeasible) |
| B | `dp2_tool_large_result` turns 8 → 3 | Tool 결과 누적으로 후반 Turn의 Prefill이 단독 2 s 초과 |
| B | 시나리오 grid 확장·하향 (peak가 grid 끝) | 공통 규칙 5.2 |
| P | **Cost 정의 v1 → v2 (초 → SLO 분율)** | 개발 점검에서 Oracle이 D-local보다 TTFT가 나쁜 선택을 했다. v1이 TTFT 초와 Decode 초를 같은 무게로 더해 TPOT 외부효과를 과대평가했기 때문. 평가 전에 수정 |

개발 점검으로 후보를 돌린 실행(결과는 평가에 쓰지 않음): `dp2_turn_dram_small_tool` load 18/24, `dp2_turn_hbf_hist` load 8, seed 11, H100, Baseline·D-local·Oracle·C1·C2 각 1회. Cost v2 이후 **정책 상수나 시나리오별 조정은 하지 않았다.**

## 0.2 사전 등록 가설 (실행 전)

1. CB-1~3: 후보 ≈ Baseline (saturated 또는 소폭 차이). Planner가 Baseline보다 나빠지지 않는다.
2. `dp2_turn_hbm_small_tool`, `dp2_turn_hbf_hist`: 후보가 TTFT를 개선한다 (History 왕복 전송 제거).
3. `dp2_turn_dram_small_tool`: Tier·부하에 따라 D 로컬과 P 경로가 갈려 후보가 Baseline 이상.
4. `dp2_turn_ssd_hist`, `dp2_tool_large_result`: Tier BW 또는 연산이 병목이라 이득이 작다 (대조군).
5. `dp2_prefill_burst_p_saturated`: TTFT P99 개선. `dp2_decode_heavy_p_idle`: 풀 사용률 상승.
6. `dp2_long_ctx_decode_offload`: Baseline이 용량 때문에 대기해 후보(오프로드 Tier 사용)가 개선.
7. `dp2_internode_link_contention`, `dyn_p_node_degrade`: Baseline TTFT 악화, 후보는 로컬/다른 노드로 회피.
8. C1 대 C2: C1은 최신 정보(plan age 0)라 QA3·TPOT에서 앞서고, C2는 결정 지연을 숨겨 확장성(QA5)에서 앞선다. TTFT와 Throughput은 불확실.
9. Oracle ≥ C1, C2 (상한). D-local-always는 일부 시나리오에서 Planner와 비슷하거나 앞설 수 있다 (Cost 모델 한계).

## 0.3 중단 조건

SKILL §5: 모든 comparison_valid 쌍·집계 QA에서 후보 ≥ Baseline(CI 내 parity 포함)이고 최소 N_win=3개 시나리오에서 유의한 이득이면 결과 문서를 쓴다. 최대 6회차까지.

## 0.4 실행 전 추가 변경 (사전 등록, 최종 실행 전에 기록)

| class | 변경 | 이유 / 공개 |
|---|---|---|
| M | **C2의 queue guardrail이 C1의 2배(`2×node_queue_cap`)였던 비대칭 제거** | 개발 점검(`cb_kv_8k_b32` load 24, H100, seed 11)에서 C2 goodput 800 대 C1 1213. 원인은 C2만 노드 큐를 2배 깊게 허용해 Prefill이 직렬 대기(prefill 성분 1.8 s 대 1.24 s)한 것. 명세에 근거 없는 비대칭이라 제거 후 C2 1267 / C1 1213. 두 후보는 같은 큐 한도를 쓴다 |
| M | C2 planner 자체 ledger(자기가 계획한 대기 Prefill을 plan_view에 반영) | 같은 시점에 계획된 요청들이 한 노드로 쏠리는 것을 막는 planner의 로컬 bookkeeping (Router의 local bookkeeping과 같은 위상) |
| M | closed-loop client 재발행 jitter U(0, 0.2 s), 초기 offset U(0, 2 s) | lock-step convoy 인공물(P50 = P99) 제거. 모든 후보 동일 |
| A | **QA2/QA3 집계를 iso-load로 정의**: Baseline의 최대 SLO goodput 부하점에서 후보와 비교. 각자의 최적 부하는 민감도로 병기 | CB 2쌍을 본 뒤 정의했다. **`defined_after_first_look`로 공개** (SKILL H16). QA1은 원래 정의(각자 최적 부하의 Max SLO Goodput) 유지 |

개발 점검 공개: 위 변경을 찾는 과정에서 `cb_kv_8k_b32`(load 24), `link_contention`, `long_ctx`, `turn_hbf_hist` 등을 seed 11로 1회씩 돌려 보았다. 평가 데이터(5 seed 전체 grid)는 이 변경들 이후에 새로 생성한다. 정책 상수·시나리오별 조정은 하지 않았다.

## 1. 최종 실행 (2026-10-04~06)

- Main: 2 SYS × 19 시나리오 × 후보 6(Baseline, C1, C2, D-local, Oracle, P-retain) × grid × seed 5 = 6,660 job. 위 0.4 변경 이후 코드로 처음부터 실행. 중간에 `git stash -u`가 데이터 파일을 잠시 치워 일부 행이 유실되어 resume으로 보충했다(중복 11행, 집계에 영향 없음).
- 집계 결과: 38쌍 전부 comparison_valid. Baseline-regression 항목: Common TTFT/TPOT P99, TPOT P99 전반(문서 5.2). 정책 상수·시나리오는 바꾸지 않고 진단만 했다. 변경 후 재실행(iteration 2)은 하지 않았다(새 사전 등록이 필요한 Selector 교체는 다음 단계로 남김).
- QA5(`qa5_scale.py`): 노드당 부하 grid를 처음 (4,8,12,16) → (2..6) → (2..12, 16/20/24)로 두 번 넓혔다(peak가 grid 끝). 처음 두 grid의 결과는 폐기했고 마지막 grid만 쓴다. seed 2개(확장 부하는 1개), H100 단일.
- 민감도(`sens.py`): 6시나리오, seed 3개, Baseline 최적 부하 고정. 처음 실행은 open-loop lam0 누락으로 중단해 수정 후 재실행했다.
- QA4: 사전 등록 후 측정(`qa4_count.py`). S1 fixture 편차와 S4 최소 변경 기록은 `qa4-preregistration.md` 변경 이력.
- 가설 판정: H1(CB 후보≈Baseline) 기각(x1.3~2.1), H2 부분 지지(HBM/HBF), H3·H4: 후보 ≥ Baseline은 지지, 단 DRAM·SSD·tool_large에서 P-retain이 후보와 같거나 높아 Tier 인지의 추가 이득은 확인 안 됨, H5 지지(burst TTFT), H8(C1이 QA3·TPOT 우위, C2가 확장성 우위) QA1~QA4에서 확인 안 됨, H9 일부(D-local-always는 Dynamic에서 Planner와 비슷하거나 앞섬).


## 2. 상태 유사도 기반 Late Validation (설계 변경, 2026-10-08 사전 등록)

소유자 결정: plan 저장 시 의존 상태(핵심값 위주)를 함께 저장하고, dispatch 직전 현재 상태와 비교한다. soft 임계값은 Cost 변화율 10%를 기본으로 5/10/20%를 본다.

- 구현(`val_tol` 옵션, 기본 None = 기존 검증 유지): plan에 상태 요약(n_p의 pf_tokens·njobs·ndec, n_d의 free·ndec)과 백업 후보별 저장 Cost를 함께 저장한다. 검증은 (hard) 큐 한도, History 위치/용량이 현재 상태에서 plan이 feasible한지(`cost_of`가 None이 아님), (soft) 현재 상태에서 다시 계산한 Cost가 저장 Cost의 (1+tol) 이내인지. Cost가 줄어든 변화는 허용한다. plan age 한도(2 s)는 이 모드에서 쓰지 않는다. 현재 상태 = telemetry snapshot(갱신 주기 그대로).
- 검증 비용 c_val = 20 µs는 그대로(ASSUMED, 비용 재계산 포함이라 과소일 수 있음).
- 가설(실행 전): H-V1 기본 조건(plan age ≈ 4 ms)에서는 기존 검증과 goodput 차이가 CI 안이다. H-V2 telemetry 1 s 또는 결정이 느린 조건(N≥16, worker 4)에서 state 검증이 기존보다 재계획은 늘고 TTFT P99는 같거나 낫다. tol이 작을수록 재계획이 늘어 결정 비용이 커진다.
- 실행: (E1) 6 시나리오 × telemetry {0.05, 1.0 s} × {기존, 5%, 10%, 20%} × C2, SYS-H100, Baseline 최적 부하, seed 3개. (E2) QA5 workload N=16/32, C2 worker 4·16, 노드당 부하 5·8, seed 11/23, 같은 4조건. 평가 데이터(qa_result.json)는 바꾸지 않는다(기본 None).

### 2.1 결과 (`results/data/SYS-H100/val_sweep_result.json`, 기본 평가 데이터는 변경 없음)

| 조건 | 기존(age·큐·용량) | 5% | 10% | 20% |
|---|---|---|---|---|
| E1 telemetry 0.05 s, goodput 비(x Baseline, 6시나리오) | x1.425 | x1.419 | x1.410 | x1.427 |
| E1 telemetry 1.0 s | x1.349 | x1.346 | x1.345 | x1.348 |
| E2 N=16/32, worker 4 | x1.418 | x0.788 | x1.434 | x1.340 |
| E2 N=16/32, worker 16 | x1.494 | x0.748 | x0.826 | x0.843 |

- H-V1 지지: 기본 조건에서 차이가 없다(±1%).
- **H-V2 기각**: 결정이 느린 조건(N≥16)에서 상태 유사도 검증이 기존보다 낫지 않고, 임계가 엄격할수록(worker 16 전 구간, worker 4 5%) goodput이 x0.75~0.84로 떨어진다. 무효 판정이 늘면 동기 재계획 경로로 들어가고(재계획 비율 0.01 → 0.27~0.37), 이 경로는 C1과 같은 직렬 결정 비용(N=32에서 건당 수십 ms)을 내므로 C2의 이점(결정 지연 숨김)이 사라진다.
- 해석 한계: 현재 상태 = telemetry snapshot이라 telemetry 1 s에서는 상태 변화를 못 본다(E1 1.0 s에서 차이 없음). Cost 재계산 비용을 c_val = 20 µs로 가정(과소일 수 있음). E2는 seed 2개, 노드당 부하 2점이라 잡음이 있다. `val_tol` 기본값은 None이라 본 평가는 기존 검증을 쓴 결과다.
- 시사점: 상태 유사도 검증은 정확도를 올리지만 재계획 비용이 비싼 환경에서는 오히려 해롭다. 재계획을 C1식 직렬 결정이 아니라 backup 후보 확대나 top-k 재평가 같은 싼 경로로 두거나 임계(20% 이상)를 넓혀야 한다. 이 변형은 평가하지 않았다.


## 3. 아키텍처 스타일 비교 (A Dispatcher / B Blackboard) — 사전 등록 (2026-10-10)

**이 기록이 올라간 커밋이 사전 등록 시점이다.** 이전 평가(§0~§2, C1 대 C2)는 바꾸지 않는다 (H9). 사용자 결정(2026-10-10)으로 DP2가 노드 내 attention 실행 위치 결정으로 재정의되어, 후보 축이 결정 시점에서 아키텍처 스타일로 바뀌었다. 정의·상수·시나리오·QA 정의·가설은 [`../../arch-styles-plan.md`](../../arch-styles-plan.md), QA4 변경 시나리오는 [`../../qa4-preregistration-arch.md`](../../qa4-preregistration-arch.md)에 있다.

### 3.0 이 시점에 이미 한 것 (후보 결과 없음)
- `test_sim.py` 12개 통과 (revision `92995f7`, 작업 트리 clean). 기존 결과 2점 재현(`Baseline-PD-fixed cb_kv_8k_b32` load 16 seed 11 goodput 1012.6222, `C1 dp2_turn_dram_small_tool` load 12 seed 11 goodput 234.9163): 저장된 값과 소수 4자리까지 일치.
- 새 후보·metric은 기존 `engine.py`를 수정하지 않고 서브클래스(`dp2sim/nodeint.py`)로 추가한다. `policies.py`에는 기본값이 no-op인 hook(`Estimator.price_fn`) 한 줄만 추가한다(기존 후보 결과 불변을 대조군으로 확인).

### 3.1 다음 단계 (이 기록 이후)
1. Baseline-only 제어 실행으로 시나리오 grid·lam0 확정 후 아래 §3.2에 추가.
2. 후보는 기능 점검용 소규모 실행만 하고 공개한다. 그 뒤 전체 실행.

### 3.2 Baseline-only 제어 실행 (후보 실행 전, 2026-10-10)
`sim/node_control.py` (Baseline-GPU-local만, seed 11/23, SYS-H100/B200). 원자료: `results/data/arch/control_baseline.json`(최종), `results/data/arch/iterations/`(1~2회차 요약, 2회차 JSON).

| 회차 | class | 변경 | 이유 (Baseline 결과) |
|---|---|---|---|
| 1 | — | 기존 grid로 실행 | `n_cb_*` Baseline이 거의 모든 부하에서 goodput 0 (단일 통합 노드가 동시 8 이상에서 TTFT 2 s 불가), `n_dp2_turn_hbf_hist` 전 부하 goodput 0, 여러 시나리오에서 peak가 grid 끝 |
| 2 | B + 정의 수정 | (a) **Baseline-GPU-local의 Decode를 항상 HBM으로** (History가 HBF에 있으면 HBM으로 이동 후 Decode; Baseline-PD-fixed의 Decode 의미). 처음 정의(D-local-always: History가 HBF면 HBF에서 직접 Decode)는 128K 컨텍스트 TPOT가 SLO를 넘어 infeasible (b) CB 동시성 grid를 (2..24)로 하향 확장 (c) 시나리오별로 peak가 grid 끝이면 상향 확장 | 사전 등록된 규칙(공통 5.2 grid 끝 확장, Baseline infeasible 시나리오로 승리 주장 금지). Baseline을 약하게 바꾼 것이 아니라 feasible하게 정의했다 |
| 3 | B | `n_dp2_decode_heavy_p_idle`, `n_dyn_decode_phase_shift` grid를 768까지, `n_dp2_stale_telemetry`, `n_dp2_session_size_skew` open 부하 배수를 3.0까지 확장 | peak가 grid 끝 |
| 3b | B | `n_dyn_decode_phase_shift` grid를 1536까지 (SYS-B200 peak 1024) | peak가 grid 끝 (`results/data/arch/control_baseline_extra.json`) |

최종 grid는 `sim/configs/grids_node.json`, open-loop lam0는 `sim/configs/calibration_node.json`(Baseline 교정, 2 시스템 × 4 시나리오, seed 11). **이 시점까지 후보(A, B)의 평가 데이터는 없다.** `n_dyn_turn_demotion_wave`는 원 시나리오처럼 단일 부하(24)다.

### 3.3 후보 코드 점검(평가에 쓰지 않음)과 평가 전 설계 수정 (공개)
후보 점검은 `n_cb_kv_8k_b32`, SYS-H100, seed 11, 동시성 8, HBM 풀 x0.001의 짧은 실행(`qa4_smoke_arch.py`의 squeeze fixture)으로만 했다. 이 실행에서 Baseline 대비 성능은 보지 않았다. 발견한 것과 조치:

| class | 발견 | 조치 |
|---|---|---|
| P (B 설계 결함) | B의 Tier agent가 **이미 claim했지만 아직 Decode가 시작되지 않은 Task**를 보지 못해, claim~Decode 시작(Prefill 포함) 사이에 모든 Task가 같은 Tier로 몰림 (중재 변경 smoke에서 확인) | agent가 **자기 claim backlog를 센다**(queue depth)는 Blackboard의 claim 프로토콜 정의에 맞게 `TierAdmissionAgent.claimed`를 추가. θ, ρ_hi, t_bb 등 **상수는 바꾸지 않았다** |
| 도구 | QA4 smoke S1 fixture에서 B는 ScHBM만 1 B로 줄이면 CXL-PNM이 항상 headroom이 있어 `cxl_pnm2`를 쓰지 않음 | 사전 등록된 fixture 허용 조항에 따라 **ScHBM과 CXL-PNM 둘 다 1 B**로 줄임 (A와 B 모두 같은 fixture). 변경 이력에 공개 |
| QA4 | B의 S2(에너지 항): 처음 구현(agent + budget 임계)은 smoke 실패(분포 불변). 중재(arbitration)가 에너지를 보지 않기 때문 | 사전 등록 규칙(작동하는 **최소** 변경)에 따라 smoke를 통과하는 최소 변경(중재의 에너지 반영)을 주 값으로, agent + budget까지 넣은 확장판은 민감도로 보고 |

### 3.4 1회차 전체 실행 중단과 A 설계 결함 수정 (2026-10-10)
1회차 전체 실행(`qa_eval_node.py run`, 후보 3개)을 시작한 뒤 약 590건(SYS-H100, Common 3 + `n_dp2_turn_hbm_small_tool` 일부)이 끝난 시점에 **중단**했다. 중단 사유는 진행 속도 점검 중 한 번 확인한 진단 실행이다: `n_dp2_decode_heavy_p_idle`, SYS-H100, seed 11, 부하 320에서 **A-Dispatcher goodput 1,882 대 Baseline 8,382 (x0.22), TPOT P99 253 ms, 한 갱신 구간의 요청이 같은 Tier로 몰림**. 이것은 Baseline보다 나쁜 결과이므로 SKILL §5의 Baseline-regression loop를 적용한다.

- **진단 (class P, 정책/아키텍처 결함)**: A의 Dispatcher가 snapshot(갱신 50 ms)만 보고 결정하고, **자기가 방금 dispatch한 Decode 배정**(아직 snapshot에 보이지 않음)을 상태에 반영하지 않았다. 그래서 같은 갱신 구간의 요청이 모두 "비어 보이는" 같은 Tier를 골랐다(herding). B에는 평가 전에 같은 성격의 결함(claim backlog)을 고쳤다(§3.3). 기존 C1과 같은 약점이었지만 Tier 선택지가 많은 노드 내 구성에서 드러났다.
- **수정 (A만, 이 한 가지)**: Dispatcher가 자기 dispatch를 기록하는 `PendingLedger`(Resource State의 일부)를 추가하고 결정 시 snapshot 위에 겹쳐 본다(`arch_dispatcher.py`). 정책 상수(λ_HBM, ε, t_ref, telemetry)와 시나리오는 바꾸지 않았다.
- **수정 후 같은 진단 실행**: A goodput 9,102 (Baseline 8,382, x1.09), TPOT P99 43 ms. 이 한 점만 봤고 다른 시나리오는 수정 전후로 비교하지 않았다.
- 중단된 1회차 부분 데이터는 `results/data/arch/iterations/run1_aborted/`에 보존한다(평가에 쓰지 않음).
- **참고 후보 추가 (평가 전, 별 미부여)**: `Ref-Dispatcher-with-board-rules`(Dispatcher 아키텍처가 Blackboard의 규칙 집합을 snapshot 정보로 중앙에서 실행). A와 B는 아키텍처와 규칙 집합이 함께 다르므로, 같은 규칙 집합에서 아키텍처만 바꾼 비교를 위해 둔다. 1회차 부분 데이터(SYS-H100 Common 3개 시나리오)에서 A가 Baseline보다 높고 B는 같게 나온 것을 본 뒤, 그 차이가 아키텍처가 아니라 규칙 집합 때문일 수 있다고 판단해 추가했다(공개). 별점·선택에 쓰지 않는 참고 행이다.
- 다음: 수정된 코드로 **2회차 전체 실행**(후보 3개 + 참고 1개, 처음부터).


### 3.5 2회차 전체 실행 중단과 B 규칙 집합 v2 (2026-10-10, 재실행 전 사전 등록)
2회차 전체 실행을 SYS-H100 1,584건(8개 시나리오 분량)에서 **중단**했다. SYS-B200은 0건이다. 부분 데이터는 `results/data/arch/iterations/run2_aborted/`에 보존한다(평가에 쓰지 않음). Baseline 미만 결과가 B에서 나왔으므로 Baseline-regression loop를 적용한다.

- **관찰 (부분 데이터, 사후에 B의 값만 본 것이 아니라 A, Baseline과 함께 본 것)**: `n_dp2_turn_hbf_hist`에서 B goodput 0.00x (TPOT P99 335 ms), `n_dp2_turn_dram_small_tool`에서 B 0.72x (TTFT P99 x10, TPOT x6.6, reject 120k). 같은 규칙 집합을 중앙 Dispatcher로 돌린 참고 후보(Ref)도 B와 비슷했다. 즉 차이의 주된 원인은 아키텍처가 아니라 **규칙 집합**이다.
- **진단 (class P, 정책 결함 2개)**: (1) `hbf`는 용량만 보고 admit했고 TPOT headroom 검사가 없어 128K 컨텍스트가 GPU-direct read로 계속 Decode됨. offload agent의 headroom도 노드 iteration 시간이 아니라 그 Tier의 attention 시간만 봄. (2) 사이클 간 이동 비용을 알 수 없는 board가 DRAM/SSD의 History를 offload 사다리에 올려 이동이 폭증함.
- **가설 (실행 전)**: (1)+(2)를 고치면 B는 위 두 시나리오에서 Baseline 이상(parity 이상)이 된다. 효과는 HBM 점유 절감이 줄어드는 방향일 수 있다. 이 가설이 틀려도 결과를 그대로 보고한다.
- **변경 (B만, class P 한 가지: 규칙 집합 v2)**:
  1. 모든 Tier agent(`hbf` 포함)는 노드 수준 예상 TPOT headroom으로 admit한다: `iter_time(live groups + 노드의 모든 claim backlog(hbm 포함) + 이 Task의 ctx를 해당 Tier에 추가) <= θ·SLO_TPOT`. board가 모든 Tier의 backlog를 관리한다. Task ctx = hist + q + out/2.
  2. History가 있는 Task(`hist > 0`)는 HBM staging(budget grant)까지만 시도하고 offload 사다리는 new-KV Task(`hist == 0`)에만 적용한다(board에 이동 비용 신호가 없다는 Blackboard 정의에 맞춤). 거절되면 큐에 남는다.
  - **상수 θ, ρ_hi, t_bb, 시나리오, grid, Baseline, A는 바꾸지 않았다.** 참고 후보는 같은 규칙 v2를 쓴다(board.decide 공유).
- **재실행**: 2회차와 같은 명령으로 3회차 전체 실행(후보 3개 + 참고 1개, 2 SYS, seed 5개, 모든 시나리오, 처음부터). 단위 테스트 8개 통과 확인.
- QA4 harness의 B 변경 anchor는 v2 코드에 맞게 갱신했고 QA4는 v2 코드로 다시 측정한다(사전 등록 파일 변경 이력에 기록).
