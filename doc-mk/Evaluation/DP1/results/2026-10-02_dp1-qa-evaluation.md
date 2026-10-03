---
date: 2026-10-02
dp: DP1
candidates: [C1-resource-driven, C2-behavior-driven]   # Baseline-static 포함
sys_ids: [SYS-H100, SYS-B200]
git_rev: 6b57846 (dirty)
evidence: { QA1: "[B+C]", QA2: "[B+C]", QA3: "[B+C]", QA4: "[B+C]" }
status: draft
---

# DP1 QA Evaluation — C1 vs C2 (Common + DP1 Stress + DP1 Dynamic, Baseline-regression loop 반영)

> 기준 문서: [`qa-evaluation-criteria.md`](../../qa-evaluation-criteria.md), [`common-benchmark.md`](../../common-benchmark.md), [`system-specs.md`](../../system-specs.md), [`DP1/benchmark.md`](../benchmark.md), [`DP1/simulation-plan.md`](../simulation-plan.md)
> 절차: `.claude/skills/evaluation/SKILL.md`
> 이 문서의 모든 simulation 수치는 Evidence [B+C]이며 [A] 실측이 아니다. 표는 `tools/gen_dp1_result.py`가 `results/data/SYS-*/qa_result.json`에서 생성했다.
> 이 문서는 [`2026-10-02_first-pass_superseded.md`](2026-10-02_first-pass_superseded.md)를 대체한다.

# 0. 최종 요약

> 발표용 요약이다. 근거는 4장, 한계는 6장. 별점은 **DP1 기준 별점**(`qa-criteria-dp1.md`)이고, Common+Stress+Dynamic 통합(comparison-valid만)을 **메모리 세대별 2개 시스템**에 대해 각각 계산했다. 공통 기준 별점은 4.1a.

## 0.1 QA별 후보 비교 (세대별)

| QA | SYS-H100 | SYS-B200 |
|---|---|---|
| QA1 Throughput [B] | C1 ★★ / C2 ★★★ | C1 ★★ / C2 ★★★ |
| QA2 Latency [B] | C1 ★★★ / C2 ★★★ | C1 ★★★ / C2 ★★★ |
| QA3 Utilization [B] | C1 ★★ / C2 ★★ | C1 ★★ / C2 ★★★ |
| QA4 Modifiability [B+C] | C1 ★★★ / C2 ★★ | C1 ★★★ / C2 ★★ |
| **별 합계** | **10 / 10** | **10 / 11** |
| **선택 (우선순위 규칙)** | **C2** (priority-QA1) | **C2** (total) |

| 값 | SYS-H100 | SYS-B200 |
|---|---|---|
| QA1 goodput 배수 (vs Baseline) | C1 x1.29 / C2 x1.34 | C1 x1.26 / C2 x1.44 |
| QA2 latency 개선 배수 | C1 x1.39 / C2 x1.67 | C1 x1.41 / C2 x1.65 |
| QA3 U 상대값 (vs Baseline) | C1 x1.11 / C2 x1.01 | C1 x1.20 / C2 x1.25 |
| comparison-valid 시나리오 수 | 10 | 13 |

## 0.2 Trade-off

- **별이 갈리는 칸:** C2가 앞서는 칸 QA1@SYS-H100, QA1@SYS-B200, QA3@SYS-B200, C1이 앞서는 칸 QA4@SYS-H100, QA4@SYS-B200. QA4는 평균 집계에서 C1 ★★★ 대 C2 ★★이다: 변경 module 평균 C1 1.75 대 C2 2.50, 공수 0.38 대 0.51 man-month, 에이전트 비용(frontier tier) $1.16 대 $1.49 (QA4 장 참조, 모두 추정).
- C2의 비용(SYS-B200, combined 평균): migration 1,239 GiB (C1 110), 링크 점유 9.5% (C1 1.3%), decision overhead 105 ms/run (C1 3 ms).
- 이득은 static 배치가 stale해지는 Dynamic 시나리오와 H100/B200에 집중된다.

## 0.3 선택과 근거

1. **QA 우선순위:** QA1 > QA2 > QA3 > QA4 (confirmed by owner 2026-10-03). 근거: DP1의 1차 목적은 이기종 메모리에서 SLO를 만족하는 처리량(QA1)과 지연(QA2)을 높이는 것이다. 활용률(QA3)은 그 결과 지표이고, 확장성(QA4)은 구조 비용이다.
2. **시스템별 선택:** 별 합계가 높은 후보. **합계가 같을 때만** 우선순위 위에서부터 처음으로 별이 갈리는 QA가 결정한다 (`tools/dp_selection.py`). 결과는 0.1 표의 마지막 행이다.
3. **전체 선택:** 시스템별 별 합계를 더해 C1 20, C2 21 -> **C2** (별 합계가 높은 후보).
4. **결정 민감도:** 우선순위는 합계가 같은 시스템에서만 쓰인다(SYS-H100). 우선순위를 뒤집으면(QA4 > QA3 > QA2 > QA1) 전체 선택은 C1이다.
5. **별점 경계 취약성:** QA1 ★★★ 경계(1.30), QA3 상대 경계(1.25)는 결과를 본 뒤 정했거나(QA1) QA2와 같은 값을 유추로 가져온 것(QA3)이다. 경계 근처 값은 4.1b와 QA3 민감도에서 확인한다. QA4는 평균 집계(v2)로 C1이 한 단계 높지만 C2의 M2 값이 경계(0.5 man-month)를 0.006 넘은 수준이라 경계에 민감하다(`qa4-modifiability.md`).

## 0.4 선택한 구조의 부족한 부분과 보완 설계

택틱 상세는 `DP1/DP1-complement-design-tactics.pptx`. 선택 구조가 C2이면 아래를, C1이면 대응 약점(성능 이득 한계)에 대한 보완을 적용한다.

| # | 약점 (평가 근거) | 보완 택틱 | 개선 대상 | 검증 상태 |
|---|---|---|---|---|
| W1 | QA4: C2는 신규 data class에 module 3개, 신규 memory는 선호 목록에 명시해야 쓰임(C1은 1개, 코드 변경 없이 사용) | type 특성/선호를 descriptor로 외부화, descriptor 없는 class는 type-agnostic 경로 | QA4 | [C], 미구현 |
| W2 | migration 비용: C2 1,239 GiB, 링크 점유 9.5% | link-time budget + 이득/비용 gating(simulator 적용), traffic class 우선순위, replica 있으면 DROP 우선 | QA1·QA3 | budget/gating [B] 적용, 나머지 [C] |
| W3 | 예측 의존: 오차 e=0.6까지 C2 우위 유지(4.6, lognormal 한 종류) | 신뢰도 gating(낮으면 C1 트리거로 대체), do-no-harm guard, hysteresis | QA1 안정성 | [C], 미구현 |
| W4 | decision overhead 105 ms/run (C1 3 ms) | event coalescing(구현), 점진 갱신, 비동기 판단 | QA2 | coalescing [B], 나머지 [C] |

## 0.5 대표 benchmark (SYS-B200 기준)

전체 32개 중 아래만 본문에서 설명한다. 선택 규칙: Common은 첫 시나리오, Stress는 C2-C1 goodput 격차가 가장 큰 시나리오(격차가 모두 0이면 이름순 첫 시나리오), Dynamic은 격차가 가장 큰/가장 작은 시나리오 (comparison-valid만). 나머지는 4.2.

| Set | 시나리오 | 무엇인가 | C1 goodput (vs Baseline) | C2 goodput (vs Baseline) |
|---|---|---|---|---|
| Common | `cb_kv_8k_b32` | KV만, 8K/256, batch 32, HBM 빠듯 | x1.00 (tie) | x1.00 (tie) |
| DP1 Stress | `agent_memory_long_lived` | 장기 보존 Agent Memory, 드문 재사용 | x1.00 (tie) | x1.00 (tie) |
| DP1 Dynamic | `dyn_kv_hotset_recency_shift` | hot 대화가 초기 세션에서 최근 세션으로 이동 | x1.11 (tie) | x2.62 (win) |
| DP1 Dynamic | `dyn_cold_resident_chat_wave` | idle Agent Memory가 HBM 선점 후 chat 폭주 | x1.83 (win) | x1.70 (win) |

# 1. 시스템 환경

| 항목 | 값 |
|---|---|
| SYS id | **메모리 세대별 2개 profile** (모두 6종 메모리 포함): SYS-H100 (HBM3, PCIe 5.0), SYS-B200 (HBM3e, PCIe 5.0). SYS-A100(HBM2e, PCIe 4.0)과 SYS-VR(HBM4, PCIe 6.0)은 profile만 정의하고 이 평가에서는 **제외**했다(소유자 결정, 2026-10-03). 이전 문서의 A100/VR 결과는 `results/data/SYS-A100`, `SYS-VR`에 보존된다. 기존 SYS-1~5는 legacy(메모리 부분집합 ablation)이며 이 문서의 주 결과가 아니다 |
| Model / precision | Llama-3.1-70B, BF16 (`models.json`) |
| Git revision | 6b57846 (dirty) |
| Seeds / loads | seeds 11, 23, 37, 53, 71 (5회) / load x0.5, x1.0, x1.5, x2.0, 95% CI t=2.776 |
| Tie 판정 | goodput 상대 차이 < 1% 또는 95% CI 이내이면 tie ("material" 임계 1%는 이 평가의 임시 상수) |
| 재현 command | `cd doc-mk/Evaluation/DP1/sim && python3 test_sim.py && python3 loop_run.py --final` (SYS-H100/B200; 제외 SYS는 --systems로 실행 가능), 단일: `python3 qa_eval.py --system SYS-B200` |
| 표 생성 | `python3 doc-mk/Evaluation/tools/gen_dp1_result.py` |
| Raw data | `DP1/results/data/SYS-{H100,B200}/qa_result.json`, `epsilon_SYS-B200.json`, `qa4_modifiability.json`, `sensitivity_SYS-4.json`(legacy, SYS-B200과 동일 수치) |

시스템 profile 상세: [system-specs.md](../../system-specs.md). 세대별 profile의 H100 규격과 link 스케일링은 ASSUMED/PUBLIC(확인 필요)이며, CXL-PNM/HBF/SSD-PIM/Custom HBM 같은 신규 memory는 과거 세대가 없어 link 대역 스케일로만 세대를 표현했다(ASSUMED). 구 SYS-4 = SYS-B200(수치 동일), 구 SYS-5와 SYS-VR은 PCIe 6.0 반영으로 다르다.

# 2. 평가 항목

| 항목 | 정의 / formula | 출처 |
|---|---|---|
| QA1 Max SLO Goodput | load sweep(x0.5~2.0) 중 SLO를 만족한 output token/s의 최대값. 시나리오별 Baseline 대비 비율의 **geometric mean**. **DP1 별점:** < 0.97 ★ / 0.97~1.30 ★★ / >= 1.30 ★★★. 공통 별점(참고): criteria §4.3 (0.90 / 1.10) | criteria §4 + `DP1/qa-criteria-dp1.md` |
| QA2 Latency | Max goodput load point의 TTFT/TPOT P50/P95/P99. **DP1 별점:** 6개 improvement factor(Baseline / 후보)의 geometric mean, < 0.95 ★ / 0.95~1.25 ★★ / >= 1.25 ★★★. 공통 별점(참고): P99 worst-case, criteria §5 (≤2 s & ≤50 ms ★★★ / ≤4 s & ≤100 ms ★★) | criteria §5 + DP1 criteria |
| QA3 Useful Utilization | **v4: 시스템의 모든 메모리 기준.** `U = (sum_m 평균 점유 byte / sum_m 용량) x (SLO 만족 token / served token) x (1 - migration 링크 점유율)`. **DP1 별점:** Baseline 대비 상대값 U_후보/U_Baseline < 0.95 ★ / 0.95~1.25 ★★ / >= 1.25 ★★★ (QA2 개선 배수와 같은 경계). 공통 별점(참고): criteria §6 (65% / 85%) — 풀 점유가 낮아 모두 ★ | **임시 정의** + `DP1/qa-criteria-dp1.md` §A.1 |
| QA4 Modifiability | 변경 시나리오 4개(신규 memory / data type / policy / event)에 대해 (M1) 변경 module 수, (M2) 개발 공수(man-month), (M3) 코드 에이전트 토큰 비용(USD, 모델 tier 2종). 시나리오별 최악값으로 sub-star를 정하고 QA4 = 세 sub-star의 중앙값 | `DP1/qa4-modifiability.md` (사전 등록: `qa4-preregistration.md`) |
| 집계 범위 | **DP1 별점은 comparison-valid만** 집계. 공통 별점(참고)은 "feasible" = Baseline goodput > 0 (comparison-valid + saturated). Combined는 3개 set 합산 | 본 평가 정의 |
| Diagnostic | migration 횟수/bytes/time, decision overhead, tier별 access, SLO 만족률 | DP1 전용 |

# 3. 벤치마크 / 시나리오

최종 결과는 **Common Benchmark + DP1 Stress Benchmark + DP1 Dynamic Benchmark**를 모두 합친 것이다.

- **Common**: 공통 profile(8K in / 256 out, Llama-3.1-70B BF16)의 DP1 realization 3개. HBM을 줄여 계층이 영향을 주게 했다.
- **DP1 Stress**: 기존 23개 (resource pressure / data behavior / mixed AI data / stability).
- **DP1 Dynamic**: Baseline-regression loop(iteration 2)에서 추가한 시나리오와 controls. **Baseline은 SLO를 만족하지만 static 배치가 runtime에 stale해지는** 패턴을 대상으로 한다.

Fit label: **V** = comparison-valid (Baseline이 SLO 만족), **I** = infeasible (Baseline도 SLO 불가, 비교 제외하되 목록 유지), **S** = saturated (모든 후보가 CI 안에서 동일, 판별 불가). SYS별로 label이 달라질 수 있다.

| Set | 시나리오 | SYS-H100 | SYS-B200 | 한 줄 설명 |
|---|---|---|---|---|
| Common | `cb_kv_8k_b32` | V | V | KV만, 8K/256, batch 32, HBM 빠듯 |
| Common | `cb_kv_8k_b32_ramp` | V | V | KV만, 8K/256, HBM 압박이 점진 증가 |
| Common | `cb_mixed_8k_b32` | V | V | KV+LoRA+MoE+Agent/Tool 혼합, HBM 빠듯 |
| DP1 Stress | `kv_b1_c32k_cold_cxl` | S | V | 차가운 32K KV, Custom-HBM 불가 (CXL-PNM 경로) |
| DP1 Stress | `kv_b16_c32k` | S | S | 중간 batch/context KV 기준선 |
| DP1 Stress | `kv_b16_c32k_burst_chbm` | V | V | 32K KV, HBM 여유 적을 때 도착 burst |
| DP1 Stress | `kv_hbm_relief_behavior_recovery` | V | V | HBM 압박 후 회복, hot KV 재승격 |
| DP1 Stress | `kv_b64_c128k_cold` | I | I | 차가운 128K KV, batch 64 (CXL-PNM attention) |
| DP1 Stress | `kv_b256_c128k_burst` | I | I | 128K KV 대형 batch burst, 공유 링크 압박 |
| DP1 Stress | `kv_b64_c512k_long` | I | I | 512K 초장문 KV, batch 64 |
| DP1 Stress | `kv_b256_c512k_stress` | I | I | 512K x batch 256 최대 KV 셀 |
| DP1 Stress | `rag_1tib_b16` | V | S | 1 TiB read-mostly 벡터 인덱스, 지역성 변화 |
| DP1 Stress | `rag_8tib_b64_ssd_pim` | I | S | 8 TiB 벡터 DB, 동시 질의 64 (SSD-PIM) |
| DP1 Stress | `rag_8tib_b256_ssd_pim` | I | I | 8 TiB 벡터 DB, 동시 질의 256 |
| DP1 Stress | `kv_rag_b64_c128k` | I | I | KV decode + 대용량 RAG 인덱스 경합 |
| DP1 Stress | `agent_memory_long_lived` | V | V | 장기 보존 Agent Memory, 드문 재사용 |
| DP1 Stress | `tool_result_bursty` | S | S | Tool 결과가 burst로 생성되어 반복 참조 |
| DP1 Stress | `lora_multi_tenant_b64` | I | I | Multi-LoRA, 인기도 skew |
| DP1 Stress | `moe_expert_skew_b256` | I | I | MoE expert 라우팅 skew, 대형 batch |
| DP1 Stress | `mixed_all_ai_data_b64` | I | I | 6종 AI data class 공존 |
| DP1 Stress | `hbm_pressure_ramp_b64` | I | I | KV/LoRA/MoE, HBM 압박 점진 증가 |
| DP1 Stress | `hbm_bw_shock_b256` | I | I | batch 256 중 HBM 대역폭 급락 |
| DP1 Stress | `host_path_pressure_b64` | I | I | RAG/Agent/Tool + host PCIe/CPU 경합 |
| DP1 Stress | `data_mix_shift_b64` | I | I | 워크로드가 KV/LoRA에서 RAG/Agent로 이동 |
| DP1 Stress | `behavior_flip_stress` | V | S | 객체별 hotness 급반전 (thrashing 유발) |
| DP1 Stress | `six_tier_capacity_stress` | I | I | 용량 사다리로 6개 메모리 전부 사용 |
| DP1 Dynamic | `dyn_cold_resident_chat_wave` | I | V | idle Agent Memory가 HBM 선점 후 chat 폭주 |
| DP1 Dynamic | `dyn_idle_kv_holds_hbm` | I | V | tool 대기 중 idle KV가 HBM 점유, hot 세션 도착 |
| DP1 Dynamic | `dyn_kv_hotset_recency_shift` | I | V | hot 대화가 초기 세션에서 최근 세션으로 이동 |
| DP1 Dynamic | `dyn_kv_rotating_hotset` | I | V | 사용자 그룹이 60 s 주기로 번갈아 활성 |
| DP1 Dynamic | `dyn_rag_shard_hotset_shift` | V | V | 벡터 shard 인기도가 중간에 뒤바뀜 |
| DP1 Dynamic | `dyn_host_path_contention_kv` | V | V | 중간에 host link 대역폭 25%로 저하 |

# 4. 결과

## 4.1 최종 QA 표 — **DP1 기준 별점** (SYS-B200, Common + DP1 Stress + DP1 Dynamic 통합)

DP1 공식 별점이다 (기준: [`qa-criteria-dp1.md`](../qa-criteria-dp1.md) §A, Baseline 대비 효과 크기). 집계는 **comparison-valid 시나리오**(Baseline이 SLO를 만족)만 대상으로 한다. 공통 기준 별점은 4.1a에 참고로 싣는다.

### SYS-H100

| Set (n, comparison-valid) | QA | Baseline (T_ref) | C1 | C2 |
|---|---|---|---|---|
| Common (3) | QA1 Throughput | **★★** x1.000±0.000 [B+C] | **★★** x1.000±0.000 [B+C] | **★★** x1.000±0.000 [B+C] |
| | QA2 Latency | **★★** x1.00 (TTFT P50/P95/P99 214/355/376 ms, TPOT 9.9/10.5/10.6 ms) [B+C] | **★★★** x1.26 (TTFT P50/P95/P99 102/244/312 ms, TPOT 9.5/10.0/10.3 ms) [B+C] | **★★** x1.21 (TTFT P50/P95/P99 94/309/360 ms, TPOT 9.5/10.3/10.5 ms) [B+C] |
| | QA3 Utilization (임시 정의) | **★★** U 1.14% (x1.00) [B+C] | **★★** U 1.10% (x0.97) [B+C] | **★** U 0.99% (x0.87) [B+C] |
| DP1 Stress (5) | QA1 Throughput | **★★** x1.000±0.000 [B+C] | **★★** x1.031±0.028 [B+C] | **★★** x1.091±0.074 [B+C] |
| | QA2 Latency | **★★** x1.00 (TTFT P50/P95/P99 294/707/793 ms, TPOT 15.7/17.4/17.5 ms) [B+C] | **★★★** x1.30 (TTFT P50/P95/P99 135/331/793 ms, TPOT 13.2/15.8/16.7 ms) [B+C] | **★★★** x1.68 (TTFT P50/P95/P99 120/243/572 ms, TPOT 13.0/13.3/15.2 ms) [B+C] |
| | QA3 Utilization (임시 정의) | **★★** U 2.27% (x1.00) [B+C] | **★★** U 2.32% (x1.02) [B+C] | **★** U 2.15% (x0.95) [B+C] |
| DP1 Dynamic (2) | QA1 Throughput | **★★** x1.000±0.000 [B+C] | **★★★** x3.297±1.774 [B+C] | **★★★** x3.472±1.822 [B+C] |
| | QA2 Latency | **★★** x1.00 (TTFT P50/P95/P99 4,879/6,578/6,581 ms, TPOT 29.6/47.8/47.8 ms) [B+C] | **★★★** x1.87 (TTFT P50/P95/P99 537/1,500/5,369 ms, TPOT 24.9/38.8/40.9 ms) [B+C] | **★★★** x2.67 (TTFT P50/P95/P99 504/792/1,694 ms, TPOT 24.2/26.0/29.5 ms) [B+C] |
| | QA3 Utilization (임시 정의) | **★★** U 0.53% (x1.00) [B+C] | **★★★** U 1.30% (x2.44) [B+C] | **★★★** U 1.11% (x2.09) [B+C] |
| **Combined** (10) | QA1 Throughput | **★★** x1.000±0.000 [B+C] | **★★** x1.289±0.107 (CI가 경계에 걸침) [B+C] | **★★★** x1.340±0.095 (CI가 경계에 걸침) [B+C] |
| | QA2 Latency | **★★** x1.00 (TTFT P50/P95/P99 268/559/603 ms, TPOT 13.0/14.2/14.9 ms) [B+C] | **★★★** x1.39 (TTFT P50/P95/P99 133/324/574 ms, TPOT 13.0/14.2/14.8 ms) [B+C] | **★★★** x1.67 (TTFT P50/P95/P99 119/298/477 ms, TPOT 13.0/13.0/13.0 ms) [B+C] |
| | QA3 Utilization (임시 정의) | **★★** U 1.58% (x1.00) [B+C] | **★★** U 1.75% (x1.11) [B+C] | **★★** U 1.60% (x1.01) [B+C] |
| **QA4 Modifiability** | | — | ★★★ [C] | ★★ [C] |

### SYS-B200

| Set (n, comparison-valid) | QA | Baseline (T_ref) | C1 | C2 |
|---|---|---|---|---|
| Common (3) | QA1 Throughput | **★★** x1.000±0.000 [B+C] | **★★** x1.000±0.000 [B+C] | **★★** x1.000±0.000 [B+C] |
| | QA2 Latency | **★★** x1.00 (TTFT P50/P95/P99 99/299/329 ms, TPOT 4.1/5.0/5.1 ms) [B+C] | **★★★** x1.27 (TTFT P50/P95/P99 51/197/250 ms, TPOT 4.0/4.6/4.8 ms) [B+C] | **★★★** x1.44 (TTFT P50/P95/P99 37/108/263 ms, TPOT 3.9/4.0/4.8 ms) [B+C] |
| | QA3 Utilization (임시 정의) | **★★** U 1.12% (x1.00) [B+C] | **★★** U 1.10% (x0.98) [B+C] | **★** U 0.99% (x0.89) [B+C] |
| DP1 Stress (4) | QA1 Throughput | **★★** x1.000±0.000 [B+C] | **★★** x1.000±0.000 [B+C] | **★★** x1.000±0.000 [B+C] |
| | QA2 Latency | **★★** x1.00 (TTFT P50/P95/P99 52/176/192 ms, TPOT 5.9/9.6/9.9 ms) [B+C] | **★★** x1.10 (TTFT P50/P95/P99 52/116/146 ms, TPOT 5.5/8.3/9.1 ms) [B+C] | **★★★** x1.32 (TTFT P50/P95/P99 52/65/108 ms, TPOT 5.4/5.6/6.6 ms) [B+C] |
| | QA3 Utilization (임시 정의) | **★★** U 1.52% (x1.00) [B+C] | **★★** U 1.52% (x1.00) [B+C] | **★★** U 1.48% (x0.97) [B+C] |
| DP1 Dynamic (6) | QA1 Throughput | **★★** x1.000±0.000 [B+C] | **★★★** x1.643±0.285 [B+C] | **★★★** x2.211±0.078 [B+C] |
| | QA2 Latency | **★★** x1.00 (TTFT P50/P95/P99 1,721/2,174/2,174 ms, TPOT 50.3/62.1/62.1 ms) [B+C] | **★★★** x1.75 (TTFT P50/P95/P99 669/1,686/2,023 ms, TPOT 39.0/54.2/60.3 ms) [B+C] | **★★★** x2.03 (TTFT P50/P95/P99 230/1,696/2,112 ms, TPOT 32.3/53.8/61.7 ms) [B+C] |
| | QA3 Utilization (임시 정의) | **★★** U 1.17% (x1.00) [B+C] | **★★★** U 1.74% (x1.49) [B+C] | **★★★** U 1.95% (x1.67) [B+C] |
| **Combined** (13) | QA1 Throughput | **★★** x1.000±0.000 [B+C] | **★★** x1.258±0.098 (CI가 경계에 걸침) [B+C] | **★★★** x1.442±0.023 [B+C] |
| | QA2 Latency | **★★** x1.00 (TTFT P50/P95/P99 159/338/343 ms, TPOT 6.4/9.9/10.0 ms) [B+C] | **★★★** x1.41 (TTFT P50/P95/P99 57/296/330 ms, TPOT 5.5/9.3/9.8 ms) [B+C] | **★★★** x1.65 (TTFT P50/P95/P99 52/244/324 ms, TPOT 5.4/5.7/6.9 ms) [B+C] |
| | QA3 Utilization (임시 정의) | **★★** U 1.27% (x1.00) [B+C] | **★★** U 1.52% (x1.20) [B+C] | **★★★** U 1.59% (x1.25) [B+C] |
| **QA4 Modifiability** | | — | ★★★ [C] | ★★ [C] |

> QA1 = Baseline 대비 goodput ratio(± 95% CI), 별 경계 0.97 / 1.30. QA2 = TTFT/TPOT x P50/P95/P99 6개 improvement factor의 geometric mean (>1이면 Baseline보다 빠름), 경계 0.95 / 1.25. QA3 = Baseline 대비 변화(pp), 경계 -5 / +15.
> **이 경계는 첫 결과를 본 뒤 정한 값이다.** 아래 4.1b에서 경계에 따른 별점 변화를 확인할 수 있다.

## 4.1a 공통 기준 별점 (참고, DP 간 비교용)

[`qa-evaluation-criteria.md`](../../qa-evaluation-criteria.md)의 기준 그대로이다. 집계는 Baseline goodput > 0인 시나리오(V + S)이고 QA2는 worst-case이다. Baseline 자체가 SLO를 못 맞추는 시나리오가 worst-case를 지배하면 별점이 모두 ★로 나올 수 있다.

| Set (n) | QA | Baseline (T_ref) | C1 | C2 |
|---|---|---|---|---|
| **Common** (3) | QA1 Throughput | ★★ 3,272 tps (x1.000) [B+C] | ★★ x1.000 [B+C] | ★★ x1.000 [B+C] |
| | QA2 Latency (worst) | ★★★ 337 ms / 5 ms [B+C] | ★★★ 263 ms / 5 ms [B+C] | ★★★ 324 ms / 5 ms [B+C] |
| | QA3 Util. (v4 풀 U, 임시 정의) | ★ 1.12% [B+C] | ★ 1.10% [B+C] | ★ 0.99% [B+C] |
| **DP1 Stress** (9) | QA1 Throughput | ★★ 370 tps (x1.000) [B+C] | ★★ x1.000 [B+C] | ★★ x1.037±0.066 [B+C] |
| | QA2 Latency (worst) | ★ 793,052 ms / 14 ms [B+C] | ★ 793,052 ms / 14 ms [B+C] | ★ 793,052 ms / 14 ms [B+C] |
| | QA3 Util. (v4 풀 U, 임시 정의) | ★ 2.18% [B+C] | ★ 2.18% [B+C] | ★ 2.37% [B+C] |
| **DP1 Dynamic** (6) | QA1 Throughput | ★★ 120 tps (x1.000) [B+C] | ★★★ x1.643±0.285 [B+C] | ★★★ x2.211±0.078 [B+C] |
| | QA2 Latency (worst) | ★ 9,567 ms / 63 ms [B+C] | ★★ 2,138 ms / 62 ms [B+C] | ★★ 2,160 ms / 62 ms [B+C] |
| | QA3 Util. (v4 풀 U, 임시 정의) | ★ 1.17% [B+C] | ★ 1.74% [B+C] | ★ 1.95% [B+C] |
| **Combined (3 set 통합)** (18) | QA1 Throughput | ★★ 770 tps (x1.000) [B+C] | ★★★ x1.180±0.066 [B+C] | ★★★ x1.327±0.042 [B+C] |
| | QA2 Latency (worst) | ★ 793,052 ms / 63 ms [B+C] | ★ 793,052 ms / 62 ms [B+C] | ★ 793,052 ms / 62 ms [B+C] |
| | QA3 Util. (v4 풀 U, 임시 정의) | ★ 1.67% [B+C] | ★ 1.85% [B+C] | ★ 2.00% [B+C] |
| **QA4 Modifiability** | 3 sub-metric 중앙값 | — | ★★★ [B+C] | ★★ [B+C] |

(n = 집계된 시나리오 수. ratio의 ± 값은 95% CI)

## 4.1b QA1 별점 경계 민감도 (SYS-B200, Combined)

DP1 별점의 차이가 경계 선택에 얼마나 의존하는지 보인다. 하한(0.97)은 고정하고 ★★★ 경계만 움직였다.

| QA1 ★★★ 경계 (하한 0.97 고정) | C1 (x1.258) | C2 (x1.442) | C1과 C2가 구분되는가 |
|---|---|---|---|
| >= 1.10 | ★★★ | ★★★ | 동일 |
| >= 1.20 | ★★★ | ★★★ | 동일 |
| >= 1.25 | ★★★ | ★★★ | 동일 |
| >= 1.30 **(채택)** | ★★ | ★★★ | 구분됨 |
| >= 1.40 | ★★ | ★★★ | 구분됨 |
| >= 1.50 | ★★ | ★★ | 동일 |

C1(x1.258)과 C2(x1.442) 사이에 경계가 있을 때(약 1.26~1.44)에만 둘의 QA1 별점이 갈린다. 경계가 1.25 이하이면 둘 다 ★★★, 1.45 이상이면 둘 다 ★★이다.

## 4.1c DP1 세부 평가 (보조 진단, [`qa-criteria-dp1.md`](../qa-criteria-dp1.md) §B)

아래는 별점이 아니라 같은 별 안의 차이를 보기 위한 **진단** 지표이다 (구간은 첫 결과를 본 뒤 정의, 문서 §B.0 참조). 집계는 **comparison-valid 시나리오만** 대상으로 한다 (Baseline도 SLO를 못 맞추는 시나리오 제외).

| Set (n, comparison-valid) | 항목 | Baseline | C1 | C2 | C2 / C1 직접 비교 |
|---|---|---|---|---|---|
| **Common** (3) | QA1 tier / ratio | T3/7 x1.000 | T3/7 x1.000±0.000 | T3/7 x1.000±0.000 | x1.000±0.000 (C2 0 / tie 3 / C1 0) |
| | QA2 median P50/P95/P99 | TTFT P50/P95/P99 99/299/329 ms; TPOT 4.1/5.0/5.1 ms | TTFT P50/P95/P99 51/197/250 ms; TPOT 4.0/4.6/4.8 ms | TTFT P50/P95/P99 37/108/263 ms; TPOT 3.9/4.0/4.8 ms | P99 x1.00 (tie), P95 x1.31 (C2), P50 x1.11 (C2) → **C2** |
| | QA3 tier / util | T0/8 1% | T0/8 1% (-0pp) | T0/8 1% (-0pp) | -0pp |
| **DP1 Stress** (4) | QA1 tier / ratio | T3/7 x1.000 | T3/7 x1.000±0.000 | T3/7 x1.000±0.000 | x1.000±0.000 (C2 0 / tie 4 / C1 0) |
| | QA2 median P50/P95/P99 | TTFT P50/P95/P99 52/176/192 ms; TPOT 5.9/9.6/9.9 ms | TTFT P50/P95/P99 52/116/146 ms; TPOT 5.5/8.3/9.1 ms | TTFT P50/P95/P99 52/65/108 ms; TPOT 5.4/5.6/6.6 ms | P99 x1.23 (C2), P95 x1.39 (C2), P50 x1.01 (tie) → **C2** |
| | QA3 tier / util | T0/8 2% | T0/8 2% (-0pp) | T0/8 1% (-0pp) | -0pp |
| **DP1 Dynamic** (6) | QA1 tier / ratio | T3/7 x1.000 | T7/7 x1.643±0.285 | T7/7 x2.211±0.078 | x1.346±0.240 (C2 2 / tie 4 / C1 0) |
| | QA2 median P50/P95/P99 | TTFT P50/P95/P99 1,721/2,174/2,174 ms; TPOT 50.3/62.1/62.1 ms | TTFT P50/P95/P99 669/1,686/2,023 ms; TPOT 39.0/54.2/60.3 ms | TTFT P50/P95/P99 230/1,696/2,112 ms; TPOT 32.3/53.8/61.7 ms | P99 x0.98 (tie), P95 x0.97 (tie), P50 x1.65 (C2) → **C2** |
| | QA3 tier / util | T0/8 1% | T0/8 2% (+1pp) | T0/8 2% (+1pp) | +0pp |
| **Combined** (13) | QA1 tier / ratio | T3/7 x1.000 | T6/7 x1.258±0.098 | T6/7 x1.442±0.023 | x1.147±0.096 (C2 2 / tie 11 / C1 0) |
| | QA2 median P50/P95/P99 | TTFT P50/P95/P99 159/338/343 ms; TPOT 6.4/9.9/10.0 ms | TTFT P50/P95/P99 57/296/330 ms; TPOT 5.5/9.3/9.8 ms | TTFT P50/P95/P99 52/244/324 ms; TPOT 5.4/5.7/6.9 ms | P99 x1.06 (C2), P95 x1.16 (C2), P50 x1.30 (C2) → **C2** |
| | QA3 tier / util | T0/8 1% | T0/8 2% (+0pp) | T0/8 2% (+0pp) | +0pp |

읽는 법: `T3/7`은 7단계 중 3번째 tier (QA1 T3 = parity, T5~T7 = 공통 ★★★). QA3 tier는 8단계. QA2는 시나리오 간 median의 P50/P95/P99. 직접 비교의 ratio는 C2 / C1이다.

## 4.2 시나리오별 결과 (SYS-B200)

n_seeds = 5, 95% CI는 t 분포, V/I/S = Fit, ratio = 후보 / Baseline (Baseline goodput = 0이면 n/a).

### 4.2.1 Common

| 시나리오 | Fit | Baseline (±CI) tok/s | C1 (ratio) | C2 (ratio) | TTFT P99 B/C1/C2 (ms) | TPOT P99 B/C1/C2 (ms) | C1 / C2 vs Baseline |
|---|---|---:|---:|---:|---|---|---|
| cb_kv_8k_b32 | V | 3,578 (±192) | 3,578 (x1.00) | 3,578 (x1.00) | 337 / 250 / 324 | 5 / 5 / 5 | tie / tie |
| cb_kv_8k_b32_ramp | V | 3,595 (±41) | 3,595 (x1.00) | 3,595 (x1.00) | 318 / 239 / 183 | 5 / 5 / 4 | tie / tie |
| cb_mixed_8k_b32 | V | 2,641 (±308) | 2,641 (x1.00) | 2,641 (x1.00) | 329 / 263 / 263 | 5 / 5 / 5 | tie / tie |

### 4.2.2 DP1 Stress

| 시나리오 | Fit | Baseline (±CI) tok/s | C1 (ratio) | C2 (ratio) | TTFT P99 B/C1/C2 (ms) | TPOT P99 B/C1/C2 (ms) | C1 / C2 vs Baseline |
|---|---|---:|---:|---:|---|---|---|
| agent_memory_long_lived | V | 297 (±19) | 297 (x1.00) | 297 (x1.00) | 52 / 52 / 53 | 14 / 14 / 14 | tie / tie |
| behavior_flip_stress | S | 774 (±81) | 774 (x1.00) | 774 (x1.00) | 67 / 67 / 67 | 5 / 5 / 5 | tie / tie |
| data_mix_shift_b64 | I | 0 (±0) | 0 (n/a) | 0 (n/a) | 84,131 / 82,959 / 81,009 | 61 / 61 / 53 | n/a / n/a |
| hbm_bw_shock_b256 | I | 0 (±0) | 0 (n/a) | 0 (n/a) | 110 / 110 / 111 | 686 / 686 / 686 | n/a / n/a |
| hbm_pressure_ramp_b64 | I | 0 (±0) | 0 (n/a) | 0 (n/a) | 110 / 110 / 111 | 50 / 50 / 50 | n/a / n/a |
| host_path_pressure_b64 | I | 0 (±0) | 0 (n/a) | 0 (n/a) | 67,014 / 67,014 / 18,856 | 50 / 50 / 50 | n/a / n/a |
| kv_b16_c32k | S | 539 (±53) | 539 (x1.00) | 539 (x1.00) | 52 / 52 / 52 | 5 / 5 / 5 | tie / tie |
| kv_b16_c32k_burst_chbm | V | 954 (±59) | 954 (x1.00) | 954 (x1.00) | 331 / 240 / 162 | 10 / 8 / 6 | tie / tie |
| kv_b1_c32k_cold_cxl | V | 29 (±3) | 29 (x1.00) | 29 (x1.00) | 52 / 52 / 53 | 3 / 3 / 3 | tie / tie |
| kv_b256_c128k_burst | I | 0 (±0) | 0 (n/a) | 0 (n/a) | 110 / 110 / 111 | 195 / 195 / 195 | n/a / n/a |
| kv_b256_c512k_stress | I | 0 (±0) | 0 (n/a) | 0 (n/a) | 13,406 / 13,406 / 13,406 | 125,863 / 125,863 / 125,863 | n/a / n/a |
| kv_b64_c128k_cold | I | 0 (±0) | 0 (n/a) | 0 (n/a) | 110 / 110 / 111 | 50 / 50 / 50 | n/a / n/a |
| kv_b64_c512k_long | I | 0 (±0) | 0 (n/a) | 0 (n/a) | 3,344 / 3,344 / 3,344 | 39,273 / 39,273 / 39,273 | n/a / n/a |
| kv_hbm_relief_behavior_recovery | V | 192 (±15) | 192 (x1.00) | 192 (x1.00) | 343 / 330 / 173 | 10 / 10 / 7 | tie / tie |
| kv_rag_b64_c128k | I | 0 (±0) | 0 (n/a) | 0 (n/a) | 168,798 / 168,798 / 168,798 | 5,917 / 5,917 / 52 | n/a / n/a |
| lora_multi_tenant_b64 | I | 0 (±0) | 0 (n/a) | 0 (n/a) | 110 / 110 / 112 | 50 / 50 / 50 | n/a / n/a |
| mixed_all_ai_data_b64 | I | 0 (±0) | 0 (n/a) | 0 (n/a) | 110,027 / 108,859 / 82,159 | 61 / 61 / 54 | n/a / n/a |
| moe_expert_skew_b256 | I | 0 (±0) | 0 (n/a) | 0 (n/a) | 110 / 110 / 112 | 195 / 195 / 195 | n/a / n/a |
| rag_1tib_b16 | S | 268 (±26) | 268 (x1.00) | 268 (x1.00) | 83 / 83 / 83 | 5 / 5 / 5 | tie / tie |
| rag_8tib_b256_ssd_pim | I | 0 (±0) | 0 (n/a) | 0 (n/a) | 3,028,506 / 3,028,506 / 3,028,506 | 52 / 52 / 52 | n/a / n/a |
| rag_8tib_b64_ssd_pim | S | 38 (±25) | 38 (x1.00) | 52 (x1.39) | 793,052 / 793,052 / 793,052 | 14 / 14 / 14 | tie / tie |
| six_tier_capacity_stress | I | 0 (±0) | 0 (n/a) | 0 (n/a) | 168,617 / 168,617 / 168,617 | 7,881 / 5,938 / 2,083 | n/a / n/a |
| tool_result_bursty | S | 242 (±20) | 242 (x1.00) | 242 (x1.00) | 52 / 52 / 52 | 14 / 14 / 14 | tie / tie |

### 4.2.3 DP1 Dynamic

| 시나리오 | Fit | Baseline (±CI) tok/s | C1 (ratio) | C2 (ratio) | TTFT P99 B/C1/C2 (ms) | TPOT P99 B/C1/C2 (ms) | C1 / C2 vs Baseline |
|---|---|---:|---:|---:|---|---|---|
| dyn_cold_resident_chat_wave | V | 107 (±18) | 197 (x1.83) | 183 (x1.70) | 2,200 / 1,964 / 2,160 | 63 / 59 / 62 | win / win |
| dyn_host_path_contention_kv | V | 245 (±37) | 338 (x1.38) | 337 (x1.38) | 3,176 / 1,386 / 1,393 | 62 / 34 / 33 | win / win |
| dyn_idle_kv_holds_hbm | V | 46 (±19) | 68 (x1.48) | 130 (x2.82) | 2,104 / 2,104 / 2,104 | 62 / 62 / 62 | tie / win |
| dyn_kv_hotset_recency_shift | V | 109 (±44) | 122 (x1.11) | 285 (x2.62) | 2,148 / 2,138 / 2,120 | 62 / 62 / 62 | tie / win |
| dyn_kv_rotating_hotset | V | 167 (±30) | 199 (x1.19) | 284 (x1.70) | 2,127 / 2,082 / 2,120 | 62 / 61 / 62 | tie / win |
| dyn_rag_shard_hotset_shift | V | 48 (±8) | 189 (x3.96) | 190 (x3.97) | 9,567 / 740 / 813 | 5 / 5 / 5 | win / win |

## 4.3 Diagnostic

| 지표 (SYS-B200, combined 평균) | Baseline | C1 | C2 |
|---|---:|---:|---:|
| migration 횟수 | 0 | 4 | 58 |
| migration bytes (GiB) | 0 | 110 | 1,239 |
| migration 링크 점유율 (migration 시간 / horizon) | 0.0% | 1.3% | 9.5% |
| decision overhead (ms/run) | 0.0 | 2.8 | 105.3 |
| dynamic set 평균 migration bytes (GiB) | 0 | 195 | 2,345 |

## 4.4 시스템 간 비교 (combined, win/tie/loss는 95% CI 유의성 기준)

| SYS | 구성 | 공통 QA1 combined C1 / C2 | **DP1 별점 (QA1/QA2/QA3) C1** | **DP1 별점 C2** | C1 win/tie/loss | C2 win/tie/loss | dynamic: C1 / C2 win |
|---|---|---|---|---|---|---|---|
| SYS-H100 | H100x8 (Hopper-class): HBM3 + PCIe5 + DDR5-4800 + six memory kinds | ★★★ x1.216±0.077 / ★★★ x1.253±0.068 | ★★ / ★★★ / ★★ | ★★★ / ★★★ / ★★ | 3/10/0 | 4/9/0 | 2 / 2 (of 6) |
| SYS-B200 | B200x8 (Blackwell-class): HBM3e + PCIe5 + DDR5-6400 + six memory kinds | ★★★ x1.180±0.066 / ★★★ x1.327±0.042 | ★★ / ★★★ / ★★ | ★★★ / ★★★ / ★★★ | 3/15/0 | 6/12/0 | 3 / 6 (of 6) |

## 4.5 Iteration summary

Baseline-regression loop가 발동했다 (first-pass에서 두 후보 모두 Baseline 이하). iteration 3에서 중단 조건 (i) 충족. 상세 로그: [iterations/loop-log.md](iterations/loop-log.md).

| Iteration | Class | Change | Effect (SYS-B200, 전체 benchmark 기준) |
|---|---|---|---|
| 0 (initial) | 계측 + M | `qa_eval.py` 확장(3 set, fit label, win/tie/loss), 전송이 destination write BW를 따르도록 수정 | C1 combined x0.957 (5 loss, Common TPOT 311 ms), C2 x0.961 (4 loss) |
| 1 | P | 공통 access-cost estimator, SLO filter와 do-no-harm(C1 destination 선택), link-time migration budget, cooldown, C2 benefit-vs-cost gating, C2 demotion은 HBM pressure일 때만 | C1 x1.000 / C2 x1.028, **loss 0**, win 0 (Common/Stress는 parity) |
| 2 | B | `dynamic_benchmark()` 6개 + controls 추가 (policy 불변) | dynamic: C1 x1.106 (win 1), C2 x2.211 (win 6) |
| 3 | P | C1 promotion path (설계 §17.2): static 추정으로 SLO를 위반하는 object를 HBM으로 승격, HBM 거주 object와 swap, budget 예약 | dynamic: C1 x1.643 (win 3), C2 불변 |

## 4.6 모델 오차 e sweep (SYS-B200, Combined, comparison-valid, 보고용)

access-cost 추정(두 후보 공통, 시스템적 편향)과 C2의 predicted hotness(C2만, 호출마다)에 lognormal 오차(sigma=e)를 넣고 같은 benchmark를 다시 돌렸다. 정책 상수는 바꾸지 않았다 (`DP1/sim/epsilon_sweep.py`).

| 오차 e (lognormal sigma) | C1 QA1 | C2 QA1 | C2/C1 | C1 win/tie/loss | C2 win/tie/loss | C1 QA3 | C2 QA3 |
|---|---|---|---|---|---|---|---|
| 0.0 | x1.258±0.098 | x1.442±0.023 | x1.147 | (3, 15, 0) | (6, 12, 0) | 42% | 49% |
| 0.2 | x1.351±0.077 | x1.573±0.059 | x1.164 | (5, 13, 0) | (6, 12, 0) | 44% | 51% |
| 0.4 | x1.334±0.055 | x1.621±0.062 | x1.215 | (4, 14, 0) | (6, 12, 0) | 42% | 50% |
| 0.6 | x1.315±0.090 | x1.519±0.043 | x1.155 | (3, 15, 0) | (6, 12, 0) | 40% | 46% |

e를 올려도 C2의 이득이 사라지는 지점(break-even)은 이 오차 모델에서는 나타나지 않았다. 오차가 커질수록 두 후보의 절대 이득이 오히려 e=0 일 때보다 커지는 구간이 있는데, 이는 e=0의 cost 추정식이 최적이 아님을 의미하며 오차가 정책을 개선한다는 뜻이 아니다. 이 결과는 lognormal 한 종류, 5 seed 기준이며 실제 workload 분포 이동에 대한 robustness는 확인하지 않았다.

# 5. 결과 분석

## 5.1 first-pass에서 Baseline보다 낮았던 이유 (iteration 0 진단, SYS-B200)

| 시나리오 | 후보 < Baseline? | Root cause | Class | 근거 diagnostic |
|---|---|---|---|---|
| Common (`cb_*`) | C1 (x0.86~0.93), C2 (x1.00) | C1 Destination Tier Selector가 destination의 **serving 비용을 보지 않아** CXL-PNM attention 경로(TPOT 311 ms)를 선택, HBM이 아니라 DRAM pressure에 반응해 6개 tier로 rebalance | P | `diagnose.py`: HBM util 0.38인데 migration 105건 전부 rebalance, CXL-PNM access 147 |
| Common, RAG 시나리오 | C2 | **migration budget 없음**. 대형 object(RAG 3.4 TiB) 이동이 stall을 만들어 TTFT P99 34 s. demotion이 upper-tier pressure를 확인하지 않음(설계 §17.3 위반) | P | migration 342~389건, 3.7 TiB, decision overhead 약 140 ms/run |
| Common 전체 | 둘 다 이득 불가 | Baseline SLO 만족률이 3개 시나리오 모두 1.00이라 후보가 tie 이상을 낼 수 없음 | B | baseline slo_ratio = 1.00 |
| Stress 14/23 (SYS-B200) | 비교 불가 | Baseline도 SLO 불가 (512K context, 8 TiB RAG, batch 256 등) | B | Fit = I |

## 5.2 Dynamic Benchmark에서 이득이 나는 이유 (SYS-B200, 최종)

| 시나리오 | C1 / C2 vs Baseline | Baseline SLO 만족률 | 후보 migration GiB (C1 / C2) | 원인 (시나리오가 재현하는 As-Is 약점) | Class |
|---|---|---:|---|---|---|
| dyn_cold_resident_chat_wave | win (x1.83) / win (x1.70) | 0.47 | 401 / 3,224 | Serving pattern: long-lived Agent Memory (episodic state kept warm for idle tenants) is loaded at start-up and fills HBM first-come-first-served; at t=20-30 s an interactive long-context chat wave arrives. As-Is failure mode: the new hot KV sessions land in host DRAM (HBM is full of cold data) and are never promoted, so every turn pays the host-link restore. | B (벤치마크가 As-Is 약점을 드러냄) |
| dyn_host_path_contention_kv | win (x1.38) / win (x1.38) | 0.71 | 175 / 2,474 | Serving pattern: host-side contention (co-located checkpoint / dataloader / NIC traffic on the shared PCIe root) cuts host-link bandwidth to 25% from t=90 s. 128K-context KV that spilled to DRAM was fine before. As-Is failure mode: static tier order keeps the spilled sessions on the degraded path. | B (벤치마크가 As-Is 약점을 드러냄) |
| dyn_idle_kv_holds_hbm | tie (x1.48) / win (x2.82) | 0.29 | 106 / 2,568 | Serving pattern: agent sessions blocked on slow tool calls keep their KV resident (idle, rate x0.05) and hold HBM; at t=30-40 s the tool results return / new sessions arrive and become the hot set. As-Is failure mode: arrival order decided HBM residency; hot sessions are served from DRAM while idle sessions sit in HBM. All objects are the same data class, so only per-object behavior tells them apart. | B (벤치마크가 As-Is 약점을 드러냄) |
| dyn_kv_hotset_recency_shift | tie (x1.11) / win (x2.62) | 0.31 | 70 / 2,210 | Serving pattern: working-set drift. Conversations created first are hot in the first half (HBM residents by first-come placement); at t=90 s users move on: the early sessions go cold (x0.1) and the later sessions (resident in DRAM) become hot (x3). As-Is failure mode: placement frozen at the old working set; post-shift traffic is served from DRAM. | B (벤치마크가 As-Is 약점을 드러냄) |
| dyn_kv_rotating_hotset | tie (x1.19) / win (x1.70) | 0.38 | 153 / 1,807 | Serving pattern: three user groups active in turn (60 s windows, e.g. shift/time-zone hand-over); the active group is hot (x3), the others near idle (x0.1). As-Is failure mode: placement fits only the first window; in later windows the active group is in DRAM. Also probes anti-thrashing: the hot set moves every 60 s. | B (벤치마크가 As-Is 약점을 드러냄) |
| dyn_rag_shard_hotset_shift | win (x3.96) / win (x3.97) | 0.26 | 265 / 1,789 | Serving pattern: GPU-resident vector-index shards (8 x ~32 GiB). Query popularity shifts at t=90 s (trending topic / newly ingested documents): the first shards (HBM residents) cool down, the later shards (host DRAM) become hot. As-Is failure mode: the hot shards are scanned from DRAM (full index crosses the host link per query). | B (벤치마크가 As-Is 약점을 드러냄) |

- C2는 object별 behavior(access rate, reuse, idle)를 쓰므로 같은 data class 안의 hot/cold를 구분한다. 그래서 6개 전부에서 유의하게 이긴다.
- C1은 data type을 모르고 static hint(operation class, shape)와 resource 상태만 쓴다. **object별 hot/cold를 구분해야 하는 KV-only 시나리오 3개(idle / recency / rotating)에서는 tie**이다 (ratio가 1.1~1.5배로 보이나 95% CI 이내). 같은 data class 안의 object를 C1이 구분할 근거가 없기 때문이다.
- C1이 이기는 3개는 Agent Memory + KV 혼합(`dyn_cold_resident_chat_wave`), 단일 class RAG shard(`dyn_rag_shard_hotset_shift`), host path 경합(`dyn_host_path_contention_kv`)이다. 이 세 시나리오에서 이기는 정확한 메커니즘은 loop-log iteration 3 진단을 따른다 (본 문서는 추측하지 않는다).
- C1은 훨씬 적게 옮긴다 (dynamic 평균 migration bytes는 4.3의 표 참조).

## 5.3 Baseline 미만 시나리오 (최종 코드)

세대별 2개 시스템, 3개 set 전체에서 **어느 후보도 Baseline 미만(loss)인 시나리오가 없다** (4.4의 loss 열). Dynamic에서 유의하게 이긴 시나리오 수(C1 / C2, 전체): SYS-H100 2 / 2 (of 6), SYS-B200 3 / 6 (of 6).

## 5.4 Sensitivity (iteration 3 이후 보고, 파라미터 재조정 아님; `results/data/sensitivity_SYS-4.json`)

- migration budget이 가장 민감하다. link share 0.10 또는 bucket window 4 s이면 후보당 win이 1~2개로 줄어 중단 조건 (i)이 충족되지 않는다. 0.50 또는 16 s이면 6개 모두 win이다.
- benefit horizon, C1 affinity margin은 거의 영향이 없다.
- 어느 변형에서도 loss는 나오지 않았다.

# 6. 한계

1. **Evidence가 [A]가 아니다.** 모든 수치는 config parameter(SPEC/PUBLIC/ASSUMED 혼재) 기반 simulation이다. vLLM trace replay, H100/B200 calibration이 없다.
2. **비용 추정이 완벽하다.** 정책의 access-cost estimator가 simulator와 같은 식을 쓴다 (테스트로 일치 확인). 실제 [A] 측정으로 보정한 추정은 오차가 있어 이득은 **상한에 가깝다.**
3. **Dynamic 시나리오는 실패 모드를 알고 설계했다.** Baseline만 돌려 설계하고 후보 실행 전에 고정했지만, 시나리오 선택이 결과를 좌우한다. 이득은 "static 배치가 stale해지는 경우"에 한정된 결과이며 일반 이득이 아니다. KV dynamic은 320K context, batch 16 셀(DRAM serving이 TPOT SLO를 못 맞추는 구성)이라 Llama-3.1 공식 context(128K)를 넘는다.
4. **정책 상수는 근거 데이터가 없는 설계 선택이다.** LINK_SHARE 0.25, window 8 s, horizon 30 s, affinity margin 2.0. sensitivity에서 budget이 결과를 크게 바꾼다 (5.4).
5. **미모델링:** capacity ramp(hard capacity limit 없음), HBM BW shock(offload가 건강한 HBM을 이길 수 없음), migration 간섭(단일 0.20 계수), HBF endurance, queueing/saturation(QA1이 load에 거의 비례). 개정된 **Memory Backend I/F 구조는 구현하지 않았다** (decision 로직은 기존 C1/C2, 개정 구조는 QA4에만 반영). DROP action은 이 평가에 포함하지 않았다.
6. **임시 정의:** QA3 formula, tie 판정의 1% material 임계, "saturated" fit label(모든 후보 CI 이내 동일).
7. **QA2 집계가 worst-case**라 Baseline 자체가 SLO를 못 맞추는 시나리오가 있는 set에서는 모든 후보가 ★로 나온다 (Stress set).
8. **세대별 profile의 규격은 일부 ASSUMED**: H100 HBM·연산 값은 PUBLIC(확인 필요), PCIe 세대별 link 스케일은 가정이다(제외된 SYS-A100의 CXL-PNM은 가상 구성). 신규 memory(CXL-PNM, HBF, SSD-PIM, Custom HBM)는 과거 세대가 없어 link 대역으로만 세대를 표현했다.
9. **DP1 별점 기준(4.1)은 공통 룰(criteria rule 2: 같은 QA는 DP 간 같은 룰)과 의도적으로 다르며, 첫 결과를 본 뒤 정의했다** (`defined_after_first_look`). 공통 별점은 4.1a에 병기한다. 후보 간 ★ 차이는 QA1 ★★★ 경계(1.30)에 의존한다. 4.1b의 sensitivity에서 경계가 약 1.26~1.44일 때만 C1/C2가 갈리고 1.25 이하에서는 같으며 1.50이면 둘 다 ★★이다. 새 benchmark로 같은 경계를 재확인해야 한다. 집계는 comparison-valid 시나리오만 대상으로 하므로 feasible 전체 기준 값과 n이 다르다.

10. **QA3 정의를 v3(링크 점유 차감)에서 v4(모든 메모리 풀)로 바꿨다.** 이유: HBM만 보는 것은 시스템 전체 사용률이 아니다. v4의 풀 점유는 SSD-PIM(16 TiB, 풀의 약 75%)에 지배되어 U가 1~2%대이고, 풀 점유 자체는 후보 간 같다(migration은 byte를 옮길 뿐이므로). 후보 차이는 SLO 만족 비율과 링크 점유 항에서만 나온다. 배치 품질은 tier별 u_m과 HBM 전용 값에서 보이며 두 값은 서로 반대 방향일 수 있다. cold data를 큰 tier에 두면 점유가 올라가도 이득이 없다는 점도 한계다(SLO 항만이 방어). DP1 QA3 별점 경계(상대 0.95/1.25)는 QA2와 같은 값을 유추로 가져왔으나, 이전 별점을 본 뒤의 정의 변경이라 `defined_after_first_look`이다. 결과 값은 경계 근처(예: SYS-B200 C2 x1.25)에서 별이 갈리므로 값을 같이 읽어야 한다.
11. **비용 항목의 한계:** decision overhead는 TTFT에 이미 가산되지만 run당 50~100 ms라 SLO(초 단위)에는 영향이 거의 없다. migration 링크 점유는 C2 9.5% 대 C1 1.3%로 QA3에만 반영된다. HBF endurance, 다른 workload와의 링크 경합은 모델링하지 않았다.
12. **QA4는 추정이다.** 시뮬레이터 복사본에 변경 4종을 구현해 module/LOC를 측정했으나, 공수(man-month)와 에이전트 비용은 가정 상수(LOC 배율, 생산성, 토큰/LOC, 가격)로 계산한 값이며 실제 에이전트 세션 측정이 아니다. 상수를 낙관/비관으로 바꾸면 QA4는 두 후보 모두 같이 움직이고(★★★ 또는 ★★) 후보 차이는 별로 드러나지 않는다. 실제 vLLM 통합 비용과는 다르다. 오차 sweep(4.6)에서도 C2 우위는 역전되지 않았다. 이를 '예측 오차가 없어서'로 단정할 수는 없다(C2 predictor는 EWMA 추정기이지 oracle이 아니다). 단 access-cost 추정이 simulator와 같은 식을 쓴다는 한계(2번)는 그대로다.

# 7. 결론

- 세대별 2개 시스템, 3개 set 전체에서 **어느 후보도 Baseline 미만(loss)인 시나리오가 없다** (4.4의 loss 열). Dynamic에서 유의하게 이긴 시나리오 수(C1 / C2, 전체): SYS-H100 2 / 2 (of 6), SYS-B200 3 / 6 (of 6). first-pass의 Baseline 미만 결과는 정책 결함(P: serving 비용 무시, migration budget 없음)과 benchmark 부적합(B)에서 왔고 iteration 1~3(당시 SYS-4=SYS-B200)에서 해소되었다.
- **이득은 "static 배치가 runtime에 stale해지는" 조건에서만 확인된다.** Common과 feasible Stress에서는 대부분 동률이다. 이것은 일반 이득 주장이 아니다.
- **세대별 DP1 별점 (QA1 / QA2 / QA3 / QA4):**
  - SYS-H100: C1 ★★ / ★★★ / ★★ / ★★★ | C2 ★★★ / ★★★ / ★★ / ★★ -> C2
  - SYS-B200: C1 ★★ / ★★★ / ★★ / ★★★ | C2 ★★★ / ★★★ / ★★★ / ★★ -> C2
- **전체 선택:** 시스템별 별 합계를 더하면 C1 20, C2 21 -> **C2** (별 합계가 높은 후보). QA 우선순위는 QA1 > QA2 > QA3 > QA4 (confirmed by owner 2026-10-03). 별점 경계 의존성은 6장 9, 10.
- **trade-off는 세대에 따라 달라진다:** H100과 B200에서 C2의 성능 이득(QA1~QA3)이 C1보다 크고, 확장성(QA4)은 C1이 높다. B200에서 성능 이득 차이가 더 크다.
- **다음 단계:** (1) Destination Tier Selector의 serving-cost 입력, link-time migration budget, C2 benefit-vs-cost gating, C1 promotion 경로를 설계 문서에 반영한다 (loop-log '설계 문서에 미치는 영향'). (2) vLLM trace 수집과 HBM↔DRAM 실측으로 access-cost 모델의 오차를 [A]로 확인하고, 오차를 넣은 estimator로 재평가한다. (3) budget 파라미터 근거 확보. (4) 개정 구조(Backend I/F, snapshot)를 simulator에 반영한다.

## QA4 — Modifiability (3 sub-metric, [B+C], [`qa4-modifiability.md`](../qa4-modifiability.md))

| 시나리오 | C1: module / man-month / 에이전트 비용(frontier tier) | C2: module / man-month / 에이전트 비용(frontier tier) |
|---|---|---|
| S1 new memory (cxl_mem, CXL.mem DRAM expander) | 1 / 0.42 / $0.96 | 2 / 0.63 / $1.36 |
| S2 new AI data class (SPARSE_EMBED, op class weight_fetch) | 1 / 0.15 / $0.86 | 3 / 0.46 / $1.68 |
| S3 policy swap (C1: Affinity Mapper latency-first; C2: Predictor observed-only) | 2 / 0.38 / $1.08 | 2 / 0.37 / $1.05 |
| S4 new event type (SLO_ALERT) | 3 / 0.56 / $1.75 | 3 / 0.56 / $1.85 |
| **평균** | 1.75 / 0.38 / $1.16 | 2.50 / 0.51 / $1.49 |
| sub-star (M1 modules / M2 공수 / M3 비용) | ★★★ / ★★★ / ★★★ | ★★ / ★★ / ★★★ |
| **QA4 (sub-star 중앙값, 시나리오 평균 집계)** | **★★★** | **★★** |

측정: 시뮬레이터 복사본에 4개 변경을 C1과 C2 각각 실제로 구현해 module 수와 LOC를 측정했다. 공수와 에이전트 비용은 가정 상수로 계산한 추정이다(사전 등록: `qa4-preregistration.md`). 이전 문서의 '신규 data type에 C2는 module 4개'는 측정 결과 3개였다. C2는 선호 목록에 이름이 없으면 신규 memory를 쓰지 않는다(C1은 코드 변경 없이 사용). 모델 tier에 따라 토큰 수와 금액의 순위가 달라질 수 있어 비용은 금액으로 비교한다.
