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
