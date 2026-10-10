---
date: 2026-10-10
dp: DP2
candidates: [A-Dispatcher, B-Blackboard]   # Baseline-GPU-local 포함, 참고: Ref-Dispatcher-with-board-rules
sys_ids: [SYS-H100, SYS-B200]
git_rev: 2ee7eb5 (dirty)
evidence: { QA1: "[B+C]", QA2: "[B+C]", QA3: "[B+C]", QA4: "[B+C]" }
status: draft
---

# DP2 QA Evaluation — 중앙 Dispatcher(A) vs Blackboard(B) (노드 내 attention 실행 위치 결정, 아키텍처 스타일 비교)

> 기준 문서: `qa-evaluation-criteria.md`, `common-benchmark.md`, `system-specs.md`, `DP2/benchmark.md` §11, `DP2/arch-styles-plan.md`(사전 등록), `DP2/qa4-preregistration-arch.md`
> 이 문서의 모든 simulation 수치는 Evidence [B+C]이며 [A] 실측이 아니다. 후보(A, B)는 같은 노드 내 simulator 위에 구현한 proxy이고 vLLM 구현이 아니다.

# 0. 최종 요약

## 0.1 QA x 후보

| QA | 평가 metric | Baseline-GPU-local | A 중앙 Dispatcher | B Blackboard | 참고 (별 미부여) |
|---|---|---:|---|---|---|
| **QA1 Throughput** | Max SLO goodput (tok/s) ↑ | 1,075 | ★★  1,155 (x1.07) | ★★  1,081 (x1.00) | 1,063 (x0.99) |
| **QA2 Latency — TTFT** | P99 · P50 (ms) ↓ | P99 3,529 · P50 327 | P99 1,995 (x0.57) · P50 283 (x0.87) | P99 4,053 (x1.15) · P50 313 (x0.96) | P99 4,104 (x1.16) |
| **QA2 Latency — TPOT** | P99 · P50 (ms) ↓ | P99 14.5 · P50 8.3 | P99 19.5 (x1.34) · P50 8.6 (x1.03) | P99 15.1 (x1.05) · P50 8.4 (x1.00) | P99 14.2 (x0.98) |
| **QA2 별점** | 6개 지표 개선 배수(Baseline÷후보) geomean | x1.00 | ★★  x1.11 (TTFT x1.50 · TPOT x0.83) | ★  x0.95 (TTFT x0.92 · TPOT x0.97) | x0.95 |
| **QA3 HBM KV 점유** | 시간 평균 점유 (GiB, 노드 합) ↓ , iso-load | 631 | ★★  586 GiB (x0.94) [20쌍] | ★★  692 GiB (x1.05) [14쌍] | ★★  544 GiB (x1.00) |
| **QA4 Modifiability** | module · 공수(MM) · 에이전트 비용(T1) ↓ | — | ★★★  1.75 · 0.31 · $1.17 [B+C] | ★★★  1.25 · 0.22 · $0.96 [B+C] | — |
| **별 합계 (QA1~QA4)** | | — | 9 | 8 | — |

평가 시스템: SYS-H100(HBM3, PCIe5), SYS-B200(HBM3e, PCIe5) 통합, Llama-70B급 GQA(8) BF16 가정, 집계 쌍 32개 중 comparison-valid 21개(별점 집계 대상), saturated 11개, infeasible 0개. QA3는 SLO 달성률이 Baseline-1pp 이상인 iso-load 쌍만 쓴다(A 20쌍 / B 14쌍, 제외 1 / 7쌍). 메모리 구성(용량, 대역폭, 연산)은 `system-specs.md` 참조, 모델링하지 않은 것: HBF endurance, 노드 간 이동(이 비교는 노드 내부 결정만 다룬다).

## 0.2 Trade-off의 특징과 이유

**A(중앙 Dispatcher)는 TTFT와 HBM을 얻고 TPOT 꼬리를 쓴다.** Dispatcher는 telemetry snapshot과 Cost 모델(이동 시간, 예상 TPOT, HBM 기회비용 lambda_HBM)로 후보 Tier를 argmin한다. 그래서 History가 큰 turn이나 decode가 몰린 노드에서 ScHBM으로 attention을 보내는 결정을 한다(A의 Decode 중 ScHBM 비율 16.5%). 결과: TTFT P99 x0.57(Baseline 대비, 낮을수록 좋음), HBM 점유 x0.94, goodput x1.07. 대가로 TPOT P99가 x1.34이다. Cost 모델이 SLO(50 ms) 안의 TPOT 여유를 소비하도록 설계되어 있기 때문이며(TPOT P99 19.5 ms, SLO 이내) 쌍별로는 11승 3무 7패(TPOT 꼬리 패배가 대부분)다.

**B(Blackboard)는 Baseline과 거의 같다.** Task Board의 규칙은 "HBM budget이 허용하면 HBM, 거절될 때만 offload"이다. board에 HBM과 offload의 비용 차이를 볼 신호가 없으므로 HBM 압박이 없으면 Baseline과 같은 결정을 한다(goodput x1.00, 쌍별 3승 11무 7패). HBM 압박이 있는 시나리오에서는 admission margin(rho_hi 0.85)이 요청을 큐에 잡아 TTFT 꼬리가 늘어난다(TTFT P99 x1.15). 같은 규칙 집합을 중앙에서 실행한 참고 후보(Ref)도 비슷한 값이므로 B의 약점은 분산 결정 자체보다 **cost 신호가 없는 규칙 집합**에서 온다. 반대로 B는 live 측정값으로 결정하므로 telemetry 지연에 둔감하다(`n_dp2_stale_telemetry` B200에서 B가 x1.36 승, H100에서는 패).

**Modifiability(QA4)는 둘 다 ★★★이고 B가 조금 낫다.** 시나리오 평균 module A 1.75 / B 1.25, 공수 0.31 / 0.22 MM, 비용 $1.17 / $0.96. 차이는 S4(telemetry 신호 추가)에서 크다: A는 Tier Descriptors, Candidate Generator, Dispatcher 3개 module을 건드리고 B는 Tier Admission Agents 1개만 바꾼다(agent가 자기 Tier의 상태를 스스로 판단하기 때문). 반대로 S2(목적 항 추가)는 A가 Cost Model 1곳이고 B는 Task Board 중재 1곳(최소 변경)이나 agent와 budget까지 반영하면 3곳이다. 별이 같아 선택에는 영향이 없다.

## 0.3 선택과 근거

선택 규칙(`tools/dp_selection.py`, 우선순위 QA1 > QA3 > QA2 > QA4, status=proposal): 별 합계 A 9, B 8 -> **A-Dispatcher** (규칙: total). 우선순위를 뒤집어도 A-Dispatcher이 선택된다. 선택을 가르는 것은 QA2 한 개의 별이다(A ★★, B ★). **전제**: A의 값은 Cost 추정 오차 sigma = 0에서의 값이며, sigma 0.4부터 Baseline 아래로 내려간다(6장 민감도). **경계 의존성**: B의 QA3 절감비는 0.952로 ★★ 하한 0.95에 거의 붙어 있어, 경계 아래이면 B는 ★이고 합계 차이가 2가 된다. 선택은 같다. 이 결과는 QA2의 TPOT 꼬리를 "개선 배수 geomean"에 반영한 별점 규칙 하에서 유효하며, A의 TPOT 꼬리 악화(x1.34)는 별점에 상쇄된 채 숨어 있다.

## 0.4 선택 구조(A)의 부족한 부분과 보완 설계

| 약점 (근거 수치) | 보완 택틱 | 검증 상태 |
|---|---|---|
| QA2 TPOT 꼬리 (P99 x1.34, 비교 가능 쌍 7패, 대부분 TPOT verdict) — snapshot 주기(기본 50 ms) 사이에 Cost 모델이 보지 못한 부하가 쌓여 SLO 여유를 소비 | **Hybrid C**: Dispatcher의 후보 선택은 유지하되, Tier 쪽에 Blackboard식 **live admission guard**(Tier agent가 자기 노드의 현재 iteration 시간과 claim backlog를 직접 보고 거부권 행사). 결정은 중앙, 거부는 로컬 | [C] 논증, 미구현. 효과 수치 주장 없음 |
| Cost 추정 오차 의존 (sigma 0.4에서 goodput x0.91, 0.6에서 x0.75) | 추정 오차 보정 또는 live guard로 오추정 비용 상한(Hybrid C와 같은 택틱) | [C] |
| QA1 이득 크기 (goodput x1.07, ★★) — 직렬 결정과 telemetry 지연이 상한 | 결정 batch화, Cost 캐시 | [C] |
| 구조 비용: Dispatcher 단일 지점, S4류 변경이 3 module에 걸침 | Tier 사양/상태를 Tier agent가 소유하는 인터페이스 도입(Blackboard의 장점) | [C] |

## 0.5 고려한 시나리오 (서술)

노드 하나 안에서 "이 turn의 attention을 어디서 돌릴까"가 의미 있는 상황 16가지를 만들었다. 가장 쉬운 경우는 History가 이미 HBM에 있는 짧은 대화(`n_dp2_turn_hbm_small_tool`)다. 여기서는 어느 후보든 차이가 거의 없다. 어려운 경우는 History가 DRAM/SSD/HBF에 내려가 있는 대화(`n_dp2_turn_dram_small_tool`, `n_dp2_turn_hbf_hist`, `n_dp2_turn_ssd_hist`)와 128K급 긴 컨텍스트가 decode를 지배하는 경우(`n_dp2_long_ctx_decode_offload`), 한 노드에 decode가 몰려 HBM이 압박받는 경우(`n_dp2_decode_heavy_p_idle`)다. 동적 시나리오로 부하가 갑자기 치솟는 경우(`n_dyn_load_ramp_burst`), decode 단계가 시간에 따라 바뀌는 경우(`n_dyn_decode_phase_shift`), telemetry가 오래된 경우(`n_dp2_stale_telemetry`), Dispatcher가 죽어 fallback하는 경우(`n_dp2_planner_fault_fallback`)도 넣었다. 공통 벤치마크 3개(KV 8K, ramp, mixed)는 단일 노드에서 baseline이 이미 가득 찬 쉬운 경우다. 아직 없는 시나리오: 노드 간 이동을 포함한 경우(DP4 몫, 이 평가에서 제외), 실제 trace 기반 부하, 실측 HW. 전체 목록은 3장.

# 1. 시스템 환경

| 항목 | 값 |
|---|---|
| SYS id | SYS-H100 (primary), SYS-B200 — 통합 결과 |
| Model / precision | Llama-70B급 GQA(8), BF16, KV 약 320 KB/token (가정) |
| Git revision | 2ee7eb5 (dirty) |
| Seeds / loads | seeds 11, 23, 37, 53, 71 (5개) / 시나리오별 부하 grid(`sim/configs/grids_node.json`), iso-load 비교 |
| 재현 command | `cd doc-mk/Evaluation/DP2/sim && python qa_eval_node.py run --workers 4 && python qa_eval_node.py agg` |
| Raw data | `DP2/results/data/arch/SYS-*/runs.jsonl`, `qa_result.json`, `qa4_*.json`, `SYS-H100/sens*.json*` |

시스템 profile 상세: [system-specs.md](../../system-specs.md)

# 2. 평가 항목

| 항목 | 정의 / formula | 출처 |
|---|---|---|
| QA1 Max SLO goodput | SLO(TTFT 2 s, TPOT 50 ms) 만족 토큰/s의 부하 sweep 최대, 쌍별 비율의 geomean. 별 경계 0.97 / 1.30 | criteria §4 |
| QA2 Latency | TTFT, TPOT의 P50/P95/P99 개선 배수 geomean(6개), 별 경계 0.95 / 1.25. TTFT와 TPOT를 따로 병기 | criteria §5, H23 |
| QA3 HBM KV 점유 | 시간 평균 점유(GiB)의 Baseline 대비 비율, iso-load, SLO 달성률 Baseline-1pp 이상인 쌍만. 별 경계 절감 0.95 / 1.25 | H20, **임시 정의**(DP2 노드 내용) |
| QA4 Modifiability | 변경 시나리오 4종(신규 Tier, 신규 목적 항, 정책 교체, 신규 telemetry 신호) 실제 구현, M1 module / M2 공수 / M3 비용 시나리오 평균, 별 = 중앙값 | H21, `qa4-preregistration-arch.md` |

# 3. 벤치마크 / 시나리오

Common 3개 + DP2 노드 내 13개 = 16개 시나리오 x 2 시스템 = 32쌍. 노드 수는 1노드 3개(Common), 2노드 12개, 4노드 1개이며 노드 배정은 후보가 아닌 평가 하네스의 고정 라우팅이다(6장). 시나리오당 한 줄 설명은 `DP2/benchmark.md` §11. fit label:

| fit | 쌍 수 |
|---|---:|
| comparison_valid | 21 |
| saturated | 11 |

saturated: SYS-B200|n_dp2_planner_fault_fallback, SYS-B200|n_dp2_session_size_skew, SYS-B200|n_dp2_tool_large_result, SYS-B200|n_dp2_turn_hbm_small_tool, SYS-B200|n_dp2_turn_ssd_hist, SYS-B200|n_dyn_turn_demotion_wave, SYS-H100|n_cb_kv_8k_b32, SYS-H100|n_cb_kv_8k_b32_ramp, SYS-H100|n_dp2_planner_fault_fallback, SYS-H100|n_dp2_tool_large_result, SYS-H100|n_dyn_turn_demotion_wave

# 4. 결과

## 4.1 최종 QA 표

| QA | 평가 metric | Baseline-GPU-local | A 중앙 Dispatcher | B Blackboard | 참고 (별 미부여) |
|---|---|---:|---|---|---|
| **QA1 Throughput** | Max SLO goodput (tok/s) ↑ | 1,075 | ★★  1,155 (x1.07) | ★★  1,081 (x1.00) | 1,063 (x0.99) |
| **QA2 Latency — TTFT** | P99 · P50 (ms) ↓ | P99 3,529 · P50 327 | P99 1,995 (x0.57) · P50 283 (x0.87) | P99 4,053 (x1.15) · P50 313 (x0.96) | P99 4,104 (x1.16) |
| **QA2 Latency — TPOT** | P99 · P50 (ms) ↓ | P99 14.5 · P50 8.3 | P99 19.5 (x1.34) · P50 8.6 (x1.03) | P99 15.1 (x1.05) · P50 8.4 (x1.00) | P99 14.2 (x0.98) |
| **QA2 별점** | 6개 지표 개선 배수(Baseline÷후보) geomean | x1.00 | ★★  x1.11 (TTFT x1.50 · TPOT x0.83) | ★  x0.95 (TTFT x0.92 · TPOT x0.97) | x0.95 |
| **QA3 HBM KV 점유** | 시간 평균 점유 (GiB, 노드 합) ↓ , iso-load | 631 | ★★  586 GiB (x0.94) [20쌍] | ★★  692 GiB (x1.05) [14쌍] | ★★  544 GiB (x1.00) |
| **QA4 Modifiability** | module · 공수(MM) · 에이전트 비용(T1) ↓ | — | ★★★  1.75 · 0.31 · $1.17 [B+C] | ★★★  1.25 · 0.22 · $0.96 [B+C] | — |
| **별 합계 (QA1~QA4)** | | — | 9 | 8 | — |

## 4.2 시나리오별 결과

| 시나리오 | 시스템 | fit | Baseline goodput (부하) | A goodput (부하) | B goodput (부하) | A TTFT/TPOT P99 비 | B TTFT/TPOT P99 비 | HBM 점유 비 A / B |
|---|---|---|---|---|---|---|---|---|
| `n_cb_kv_8k_b32` | B200 | comparison_valid | 1,194 (12) | 1,197 (12) | 1,187 (12) | x0.99 / x2.32 | x1.00 / x1.00 | x0.97 / x1.00 |
| `n_cb_kv_8k_b32` | H100 | saturated | 342 (4) | 342 (4) | 342 (4) | x1.00 / x1.00 | x1.00 / x1.00 | x1.00 / x1.00 |
| `n_cb_kv_8k_b32_ramp` | B200 | comparison_valid | 1,191 (12) | 1,193 (12) | 1,188 (12) | x1.00 / x1.70 | x1.00 / x1.00 | x0.94 / x1.00 |
| `n_cb_kv_8k_b32_ramp` | H100 | saturated | 342 (4) | 342 (4) | 342 (4) | x1.00 / x1.00 | x1.00 / x1.00 | x1.00 / x1.00 |
| `n_cb_mixed_8k_b32` | B200 | comparison_valid | 1,194 (12) | 1,197 (12) | 1,194 (12) | x1.05 / x1.28 | x1.00 / x1.00 | x0.97 / x1.00 |
| `n_cb_mixed_8k_b32` | H100 | comparison_valid | 342 (4) | 379 (6) | 341 (4) | x1.00 / x1.19 | x1.00 / x1.00 | x1.00 / x1.00 |
| `n_dp2_decode_heavy_p_idle` | B200 | comparison_valid | 20,773 (512) | 22,490 (512) | 20,148 (512) | x0.13 / x0.96 | x4.02 / x0.89 | x0.93 / x1.00 |
| `n_dp2_decode_heavy_p_idle` | H100 | comparison_valid | 8,417 (320) | 9,157 (320) | 8,251 (384) | x0.19 / x1.54 | x1.87 / x0.91 | x0.95 / x1.00 |
| `n_dp2_long_ctx_decode_offload` | B200 | comparison_valid | 236 (12) | 291 (16) | 233 (12) | x0.39 / x2.45 | x1.03 / x1.01 | x1.00 / x1.00 |
| `n_dp2_long_ctx_decode_offload` | H100 | comparison_valid | 86 (4) | 106 (8) | 86 (4) | x0.46 / x2.31 | x1.10 / x1.00 | x1.01 / x1.01 |
| `n_dp2_planner_fault_fallback` | B200 | saturated | 731 (1) | 732 (1) | 735 (1) | x0.99 / x0.99 | x1.01 / x0.98 | x0.92 / x1.00 |
| `n_dp2_planner_fault_fallback` | H100 | saturated | 292 (1.5) | 292 (1.5) | 291 (1.5) | x0.98 / x1.00 | x1.00 / x1.01 | x0.93 / x1.00 |
| `n_dp2_session_size_skew` | B200 | saturated | 10,687 (2.5) | 13,379 (3) | 10,277 (2.5) | x0.04 / x0.68 | x1.88 / x1.94 | x0.89 / x1.00 |
| `n_dp2_session_size_skew` | H100 | comparison_valid | 4,053 (2) | 4,753 (2) | 4,332 (2) | x0.34 / x1.81 | x0.79 / x1.09 | x0.94 / x0.99 |
| `n_dp2_stale_telemetry` | B200 | comparison_valid | 629 (2) | 634 (2) | 857 (2) | x1.02 / x1.03 | x0.35 / x3.80 | x0.99 / x1.98 |
| `n_dp2_stale_telemetry` | H100 | comparison_valid | 315 (2) | 315 (2) | 301 (2) | x1.01 / x0.98 | x1.22 / x0.99 | x0.91 / x1.01 |
| `n_dp2_tool_large_result` | B200 | saturated | 451 (24) | 449 (24) | 449 (24) | x0.98 / x1.05 | x1.05 / x1.01 | x0.90 / x1.00 |
| `n_dp2_tool_large_result` | H100 | saturated | 117 (12) | 113 (12) | 116 (12) | x0.98 / x0.99 | x1.00 / x1.00 | x0.91 / x1.00 |
| `n_dp2_turn_dram_small_tool` | B200 | comparison_valid | 961 (48) | 951 (48) | 945 (48) | x0.97 / x1.14 | x1.10 / x1.02 | x0.92 / x1.01 |
| `n_dp2_turn_dram_small_tool` | H100 | comparison_valid | 637 (36) | 639 (36) | 593 (36) | x0.66 / x2.35 | x1.27 / x0.93 | x0.90 / x0.98 |
| `n_dp2_turn_hbf_hist` | B200 | comparison_valid | 199 (16) | 197 (16) | 196 (16) | x1.11 / x0.99 | x1.09 / x0.93 | x0.94 / x1.00 |
| `n_dp2_turn_hbf_hist` | H100 | comparison_valid | 122 (12) | 130 (12) | 117 (12) | x0.70 / x2.22 | x1.09 / x1.00 | x0.90 / x0.99 |
| `n_dp2_turn_hbm_small_tool` | B200 | saturated | 4,602 (240) | 5,161 (240) | 4,389 (240) | x0.09 / x0.94 | x1.45 / x0.94 | x0.95 / x0.99 |
| `n_dp2_turn_hbm_small_tool` | H100 | comparison_valid | 1,872 (108) | 2,020 (132) | 1,886 (108) | x0.26 / x0.95 | x0.88 / x1.00 | x0.98 / x1.00 |
| `n_dp2_turn_ssd_hist` | B200 | saturated | 96 (8) | 96 (8) | 94 (8) | x1.00 / x1.00 | x0.93 / x0.99 | x1.00 / x1.00 |
| `n_dp2_turn_ssd_hist` | H100 | comparison_valid | 93 (8) | 91 (12) | 90 (8) | x0.98 / x1.01 | x0.97 / x1.00 | x1.00 / x1.00 |
| `n_dyn_decode_phase_shift` | B200 | comparison_valid | 23,806 (1024) | 24,568 (1024) | 24,172 (1024) | x0.06 / x1.10 | x1.76 / x0.94 | x0.91 / x1.00 |
| `n_dyn_decode_phase_shift` | H100 | comparison_valid | 11,110 (512) | 11,518 (512) | 11,131 (512) | x0.14 / x1.01 | x1.87 / x0.96 | x0.89 / x1.00 |
| `n_dyn_load_ramp_burst` | B200 | comparison_valid | 3,260 (1.5) | 4,090 (2) | 3,256 (1.5) | x4.82 / x0.90 | x1.02 / x0.95 | x0.90 / x1.00 |
| `n_dyn_load_ramp_burst` | H100 | comparison_valid | 1,249 (1.5) | 1,602 (2) | 1,252 (1.5) | x0.73 / x0.96 | x1.30 / x0.99 | x0.89 / x1.00 |
| `n_dyn_turn_demotion_wave` | B200 | saturated | 151 (24) | 151 (24) | 151 (24) | x1.00 / x1.00 | x1.00 / x1.00 | x1.00 / x1.00 |
| `n_dyn_turn_demotion_wave` | H100 | saturated | 147 (24) | 147 (24) | 147 (24) | x1.00 / x1.00 | x1.00 / x0.99 | x1.00 / x1.00 |

세트별 요약 (Baseline 대비 개선 배수, 높을수록 좋음):

**Common**

| 후보 | 쌍 | QA1 goodput | TTFT P99 | TPOT P99 | QA2 개선 | HBM 점유 비 |
|---|---:|---|---|---|---|---|
| A 중앙 Dispatcher | 4 | x1.03 | x0.99 | x0.64 | x0.86 | x0.97 |
| B Blackboard | 4 | x1.00 | x1.00 | x1.00 | x1.00 | x1.00 |
| 참고: Dispatcher + Blackboard 규칙 | 4 | x1.00 | x1.00 | x1.00 | x1.00 | x1.00 |

**DP2 Stress**

| 후보 | 쌍 | QA1 goodput | TTFT P99 | TPOT P99 | QA2 개선 | HBM 점유 비 |
|---|---:|---|---|---|---|---|
| A 중앙 Dispatcher | 13 | x1.07 | x1.93 | x0.71 | x1.18 | x0.94 |
| B Blackboard | 13 | x1.01 | x0.90 | x0.92 | x0.94 | x1.12 |
| 참고: Dispatcher + Blackboard 규칙 | 13 | x0.98 | x0.83 | x1.02 | x0.94 | x1.00 |

**DP2 Dynamic**

| 후보 | 쌍 | QA1 goodput | TTFT P99 | TPOT P99 | QA2 개선 | HBM 점유 비 |
|---|---:|---|---|---|---|---|
| A 중앙 Dispatcher | 4 | x1.15 | x2.38 | x1.01 | x1.19 | x0.90 |
| B Blackboard | 4 | x1.00 | x0.69 | x1.04 | x0.90 | x1.00 |
| 참고: Dispatcher + Blackboard 규칙 | 4 | x1.00 | x0.83 | x1.01 | x0.91 | x1.00 |

## 4.3 Diagnostic

| 지표 | Baseline | A | B |
|---|---:|---:|---:|
| ScHBM으로 시작한 Decode 비율 | 0 | 16.5% | 0.0% |
| HBF/CXL-PNM 비율 | 0 | 0.4% | 0.0% |

## 4.4 Iteration summary

| Iteration | Class | Change | Effect |
|---|---|---|---|
| 0 (Baseline control) | B + 정의 | Baseline-GPU-local 정의/grid 정리(3.2) | Baseline feasible |
| 1 | P (A) | Dispatcher의 pending 배정 ledger 추가(herding, 3.4) | decode_heavy 1,882 -> 9,102 (x4.8) |
| 2 | P (B) | 규칙 v2: 노드 TPOT headroom, History는 HBM staging만(3.5) | hbf_hist 0.00x -> 0.96x, dram_small_tool 0.72x -> 0.93x |
| 3 | — | 중단 결정(3.6): 남은 B 퇴화는 cost 신호 부재라는 구조적 성질 | B QA2 ★, HBM 절감 없음 그대로 보고 |

상세 로그: [loop-log.md](iterations/loop-log.md). 부분 실행 데이터(`run1_aborted`, `run2_aborted`)는 보존했고 평가에 쓰지 않았다.

# 5. 결과 분석

Baseline보다 나쁜 비교 가능 쌍(쌍별 verdict loss가 있는 항목, 총 21건):

| 시나리오 | 후보 | goodput / TTFT / TPOT verdict | Root cause |
|---|---|---|---|
| `n_cb_kv_8k_b32` (B200) | A 중앙 Dispatcher | tie / tie / loss | TPOT 꼬리: Cost 모델이 SLO 이내 TPOT 여유를 TTFT/HBM과 교환 (설계 의도, SLO 위반 아님) |
| `n_cb_kv_8k_b32_ramp` (B200) | A 중앙 Dispatcher | tie / tie / loss | TPOT 꼬리: Cost 모델이 SLO 이내 TPOT 여유를 TTFT/HBM과 교환 (설계 의도, SLO 위반 아님) |
| `n_cb_mixed_8k_b32` (B200) | A 중앙 Dispatcher | tie / tie / loss | TPOT 꼬리: Cost 모델이 SLO 이내 TPOT 여유를 TTFT/HBM과 교환 (설계 의도, SLO 위반 아님) |
| `n_dp2_decode_heavy_p_idle` (B200) | B Blackboard | loss / loss / win | admission margin(rho_hi)과 cost 신호 부재로 HBM 압박 구간에서 큐 대기 |
| `n_dp2_long_ctx_decode_offload` (B200) | A 중앙 Dispatcher | win / win / loss | TPOT 꼬리: Cost 모델이 SLO 이내 TPOT 여유를 TTFT/HBM과 교환 (설계 의도, SLO 위반 아님) |
| `n_dp2_stale_telemetry` (B200) | B Blackboard | win / win / loss | admission margin(rho_hi)과 cost 신호 부재로 HBM 압박 구간에서 큐 대기 |
| `n_dp2_turn_dram_small_tool` (B200) | A 중앙 Dispatcher | tie / tie / loss | TPOT 꼬리: Cost 모델이 SLO 이내 TPOT 여유를 TTFT/HBM과 교환 (설계 의도, SLO 위반 아님) |
| `n_dyn_decode_phase_shift` (B200) | A 중앙 Dispatcher | win / win / loss | TPOT 꼬리: Cost 모델이 SLO 이내 TPOT 여유를 TTFT/HBM과 교환 (설계 의도, SLO 위반 아님) |
| `n_dyn_decode_phase_shift` (B200) | B Blackboard | win / loss / win | admission margin(rho_hi)과 cost 신호 부재로 HBM 압박 구간에서 큐 대기 |
| `n_dyn_load_ramp_burst` (B200) | A 중앙 Dispatcher | win / loss / tie | TPOT 꼬리: Cost 모델이 SLO 이내 TPOT 여유를 TTFT/HBM과 교환 (설계 의도, SLO 위반 아님) |
| `n_dp2_decode_heavy_p_idle` (H100) | A 중앙 Dispatcher | win / win / loss | TPOT 꼬리: Cost 모델이 SLO 이내 TPOT 여유를 TTFT/HBM과 교환 (설계 의도, SLO 위반 아님) |
| `n_dp2_decode_heavy_p_idle` (H100) | B Blackboard | loss / loss / win | admission margin(rho_hi)과 cost 신호 부재로 HBM 압박 구간에서 큐 대기 |
| `n_dp2_long_ctx_decode_offload` (H100) | A 중앙 Dispatcher | win / win / loss | TPOT 꼬리: Cost 모델이 SLO 이내 TPOT 여유를 TTFT/HBM과 교환 (설계 의도, SLO 위반 아님) |
| `n_dp2_session_size_skew` (H100) | A 중앙 Dispatcher | tie / win / loss | TPOT 꼬리: Cost 모델이 SLO 이내 TPOT 여유를 TTFT/HBM과 교환 (설계 의도, SLO 위반 아님) |
| `n_dp2_stale_telemetry` (H100) | B Blackboard | loss / loss / tie | admission margin(rho_hi)과 cost 신호 부재로 HBM 압박 구간에서 큐 대기 |
| `n_dp2_turn_dram_small_tool` (H100) | A 중앙 Dispatcher | tie / win / loss | TPOT 꼬리: Cost 모델이 SLO 이내 TPOT 여유를 TTFT/HBM과 교환 (설계 의도, SLO 위반 아님) |
| `n_dp2_turn_dram_small_tool` (H100) | B Blackboard | loss / loss / win | admission margin(rho_hi)과 cost 신호 부재로 HBM 압박 구간에서 큐 대기 |
| `n_dp2_turn_hbf_hist` (H100) | A 중앙 Dispatcher | tie / win / loss | TPOT 꼬리: Cost 모델이 SLO 이내 TPOT 여유를 TTFT/HBM과 교환 (설계 의도, SLO 위반 아님) |
| `n_dp2_turn_hbf_hist` (H100) | B Blackboard | tie / loss / tie | admission margin(rho_hi)과 cost 신호 부재로 HBM 압박 구간에서 큐 대기 |
| `n_dp2_turn_ssd_hist` (H100) | B Blackboard | loss / tie / tie | admission margin(rho_hi)과 cost 신호 부재로 HBM 압박 구간에서 큐 대기 |
| `n_dyn_decode_phase_shift` (H100) | B Blackboard | tie / loss / win | admission margin(rho_hi)과 cost 신호 부재로 HBM 압박 구간에서 큐 대기 |

# 6. 한계

- Evidence [B+C]: 물리 모델은 config 기반이며 vLLM 실행 결과가 아니다. 후보는 같은 사람이 같은 simulator에서 구현한 proxy이고, B의 규칙 집합(theta 0.8, rho_hi 0.85, t_bb 0.5 ms)은 사전 등록한 값이다.
- **A와 B는 아키텍처뿐 아니라 규칙 집합이 다르다.** 참고 후보 Ref(Dispatcher + board 규칙)로 분리를 시도했으나 Ref도 B와 비슷해 규칙 집합이 지배적이다. "Blackboard 스타일이 구조적으로 나쁘다"가 아니라 "cost 신호가 없는 Blackboard 규칙 집합은 이득이 없다"로 읽어야 한다. board에 cost 신호를 추가한 Blackboard는 이 비교에 포함되지 않았다.
- QA3의 B 값은 SLO 달성률 조건으로 7쌍이 제외된 14쌍 기준이며 경계(0.95)에 가깝다.
- A의 TPOT P99는 Baseline의 x1.34이다. 별점 geomean이 이를 TTFT 개선과 상쇄한다. TPOT 꼬리가 중요하면 A를 그대로 쓸 수 없다.
- **노드 배정은 평가 하네스의 고정 라우팅이다**(모든 후보 동일, History가 있으면 소유 노드, 없으면 snapshot의 HBM 여유 최대 노드). 시나리오 16개 중 13개가 2~4노드라 결과에 이 라우팅의 노드 간 부하 분산 효과가 섞여 있고 1노드만으로 DP2를 분리한 재평가는 하지 않았다.
- 노드 간 결정(DP4), 장시간 실행, endurance, 실제 trace는 평가하지 않았다. 기본 grid는 Baseline 교정으로 정했고 saturated 11쌍은 후보 판별력이 없다.
- A는 Cost 추정 오차에 민감하다(위 민감도 해석 (1)). **본 평가의 A는 오차 없는 추정(sigma = 0, `dp2_params.json` A18)으로 돌렸으므로 A의 이득은 상한에 가깝다.** 오차 모델은 lognormal 한 종류뿐이다(H17).
- QA4의 공수와 비용은 가정 상수(`qa4_modifiability.py`)이며 실제 에이전트 세션 측정이 아니다.
- loop를 6회 전에 중단했다(3.6). 중단 판단은 사용자가 뒤집을 수 있다.

## 민감도 (상수를 다시 맞춘 것이 아니라 사전 등록값 주변을 본 것, 6개 시나리오, SYS-H100, seed 3개)

| 축 | 값 | 후보 | goodput (x Baseline) | TTFT P99 (x) | TPOT P99 (x) | HBM 점유 (x) |
|---|---|---|---|---|---|---|
| eps | 0.0 | A 중앙 Dispatcher | x1.02 | x0.74 | x1.49 | x0.93 |
| eps | 0.2 | A 중앙 Dispatcher | x1.01 | x0.72 | x1.68 | x0.89 |
| eps | 0.4 | A 중앙 Dispatcher | x0.91 | x1.41 | x2.05 | x0.83 |
| eps | 0.6 | A 중앙 Dispatcher | x0.75 | x2.14 | x2.49 | x0.75 |
| lam_hbm | 0.0 | A 중앙 Dispatcher | x1.01 | x0.79 | x1.50 | x0.93 |
| lam_hbm | 0.25 | A 중앙 Dispatcher | x1.01 | x0.79 | x1.51 | x0.93 |
| lam_hbm | 1.0 | A 중앙 Dispatcher | x1.02 | x0.74 | x1.49 | x0.93 |
| lam_hbm | 4.0 | A 중앙 Dispatcher | x1.02 | x0.72 | x1.53 | x0.93 |
| t_ref | 0.0001 | A 중앙 Dispatcher | x1.01 | x0.70 | x1.54 | x0.93 |
| t_ref | 0.001 | A 중앙 Dispatcher | x1.02 | x0.74 | x1.49 | x0.93 |
| t_ref | 0.01 | A 중앙 Dispatcher | x1.02 | x0.70 | x1.50 | x0.93 |
| theta | 0.6 | B Blackboard | x0.98 | x1.16 | x0.99 | x1.00 |
| theta | 0.8 | B Blackboard | x0.98 | x1.16 | x0.99 | x1.00 |
| theta | 1.0 | B Blackboard | x0.98 | x1.16 | x0.99 | x1.00 |
| rho_hi | 0.7 | B Blackboard | x0.85 | x1.39 | x0.92 | x0.97 |
| rho_hi | 0.85 | B Blackboard | x0.98 | x1.16 | x0.99 | x1.00 |
| rho_hi | 0.95 | B Blackboard | x0.98 | x1.10 | x1.00 | x1.00 |
| t_bb | 0.0001 | B Blackboard | x0.97 | x1.13 | x1.00 | x1.00 |
| t_bb | 0.0005 | B Blackboard | x0.98 | x1.16 | x0.99 | x1.00 |
| t_bb | 0.002 | B Blackboard | x0.97 | x1.27 | x1.00 | x1.00 |
| tel | 0.01 | A 중앙 Dispatcher | x1.04 | x0.72 | x1.50 | x0.93 |
| tel | 0.01 | B Blackboard | x0.97 | x1.08 | x0.99 | x1.00 |
| tel | 0.05 | A 중앙 Dispatcher | x1.02 | x0.73 | x1.50 | x0.93 |
| tel | 0.05 | B Blackboard | x0.98 | x1.11 | x0.99 | x1.00 |
| tel | 0.5 | A 중앙 Dispatcher | x1.01 | x0.59 | x1.55 | x0.94 |
| tel | 0.5 | B Blackboard | x0.97 | x1.20 | x0.98 | x1.00 |
| tel | 1.0 | A 중앙 Dispatcher | x1.01 | x0.55 | x1.55 | x0.94 |
| tel | 1.0 | B Blackboard | x1.01 | x0.95 | x1.04 | x1.03 |

**해석.** (1) A의 이득은 Cost 추정 오차에 민감하다: 추정 오차 sigma 0 / 0.2 / 0.4 / 0.6에서 goodput이 x1.02 / x1.01 / x0.91 / x0.75, TTFT P99가 x0.74 / x0.72 / x1.41 / x2.14이다. 즉 이 오차 모델(lognormal, 한 종류)에서 break-even은 sigma 0.2와 0.4 사이이고, sigma 0.4부터 Baseline보다 나쁘다. 상수(lambda_HBM, t_ref)와 telemetry 주기는 A의 결과를 거의 바꾸지 않는다(goodput x1.01~x1.02, telemetry 갱신 0.01~1.0 s에서 x1.04~x1.01). (2) B는 theta에 둔감하고(0.6~1.0에서 결과 동일: HBM이 차야 offload하는 규칙이라 theta가 거의 작동하지 않음) rho_hi에 민감하다: 0.7이면 goodput x0.85, TTFT P99 x1.39, 0.95이면 x0.98, x1.10. 어느 값에서도 Baseline을 넘는 구간은 없다. (3) 한계: 6개 시나리오, seed 3개, 단일 시스템의 점 평가이며 별점이 아니라 방향 확인용이다.

# 7. 결론

- 선택: **A 중앙 Dispatcher**(별 9 vs 8). 이득은 TTFT 꼬리(x0.57)와 HBM 점유(x0.94)에 있고 goodput은 x1.07로 크지 않다. 이득이 나는 조건은 History가 HBM 밖에 있거나 decode가 몰려 HBM이 압박받는 시나리오이며, 쉬운 시나리오에서는 Baseline과 같다.
- B Blackboard(이번 규칙 집합)는 tested condition에서 Baseline 대비 이득이 없다(goodput x1.00, TTFT P99 x1.15, HBM x1.05).
- A의 약점은 TPOT 꼬리(x1.34)이고 보완안은 Hybrid C(중앙 선택 + Tier live guard)이다. [C], 미구현. 다음 단계: C를 구현해 같은 benchmark로 평가, board에 cost 신호를 넣은 Blackboard 변형 평가, DP4(노드 간)로 확장.
