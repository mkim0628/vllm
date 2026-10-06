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

