---
date: 2026-10-06
dp: DP2
candidates: [C1-scheduling-time, C2-pre-planned]   # Baseline-PD-fixed 포함, 참고 정책 D-local-always / P-retain / Oracle
sys_ids: [SYS-H100, SYS-B200]
git_rev: 5e8d3d904 (dirty)
evidence: { QA1: "[B+C]", QA2: "[B+C]", QA3: "[B+C]", QA4: "[B+C]", QA5: "[B+C]" }
status: draft
---

# DP2 QA Evaluation — C1 스케줄링 시점 결정 vs C2 사전 계획 결정 (Cost 기반 Prefill/Decode 실행 계획)

> 기준 문서: [`qa-evaluation-criteria.md`](../../qa-evaluation-criteria.md), [`common-benchmark.md`](../../common-benchmark.md), [`system-specs.md`](../../system-specs.md), [`benchmark.md`](../benchmark.md), [`simulation-plan.md`](../simulation-plan.md), [`qa-criteria-dp2.md`](../qa-criteria-dp2.md), [`m0-spec.md`](../m0-spec.md)
> 이 문서의 모든 simulation 수치는 Evidence [B+C]이며 [A] 실측이 아니다. 표는 `tools/gen_dp2_result.py`가 `results/data/*.json`에서 생성했다. 노드 간 링크 대역폭과 결정 비용은 ASSUMED다.
> 첫 평가이며 DP1과 달리 이전 first-pass 문서는 없다. 평가 전 사전 등록과 변경 이력은 [`iterations/loop-log.md`](iterations/loop-log.md).

# 0. 최종 요약

## 0.1 QA별 비교

| QA | 평가 metric | Baseline-PD-fixed | C1 스케줄링 시점 | C2 사전 계획 |
|---|---|---:|---|---|
| **QA1 Throughput** | Max SLO goodput (tok/s) ↑ | 575 | ★★★  954 (x1.66) | ★★★  956 (x1.66) |
| **QA2 Latency — TTFT** | P99 · P50 (ms) ↓ | P99 2,461 · P50 627 | P99 984 (x0.40) · P50 206 (x0.33) | P99 1,015 (x0.41) · P50 208 (x0.33) |
| **QA2 Latency — TPOT** | P99 · P50 (ms) ↓ | P99 8.9 · P50 5.8 | P99 12.0 (x1.34) · P50 5.3 (x0.91) | P99 12.0 (x1.35) · P50 5.3 (x0.91) |
| **QA2 별점** | 6개 지표 개선 배수 geomean | x1.00 | ★★★  x1.58 (TTFT x2.83 · TPOT x0.89) | ★★★  x1.56 (TTFT x2.77 · TPOT x0.88) |
| **QA3 Resource utilization** | useful GPU 사용률 (%) ↑ | 43.7 | ★★★  67.0 (x1.52) | ★★★  66.8 (x1.51) |
| **QA4 Modifiability** | module · 공수(MM) · 에이전트 비용 ↓ | — | ★★★  1.50 · 0.27 · $1.03 | ★★★  1.75 · 0.31 · $1.10 |
| **QA5 Scalability** | η (N=32 노드), 결정 지연 ↑ | η 1.00 | ★  η 0.00 · 결정 64.0 ms(임계 경로) | ★  η 0.56 · 결정 0.0 ms(임계 경로) |
| **별 합계 (QA1~QA5)** |  | — | 13 | 13 |

**평가한 시스템:** SYS-H100 (H100x8, HBM3, PCIe 5.0, DDR5-4800)과 SYS-B200 (B200x8, HBM3e, PCIe 5.0, DDR5-6400)을 통합했다. 노드 = 8-GPU, 6종 메모리, Llama-3.1-70B BF16, 노드 간 링크 RDMA 50 GB/s(ASSUMED). 집계 단위는 (시나리오, 시스템) 쌍 38개이며 모두 Baseline이 SLO를 일부 만족하는 비교 가능 쌍(38쌍, 포화 0, 불가 0)이다. 값은 쌍별 값의 기하평균(QA3는 평균), 괄호는 **후보 ÷ Baseline**이다. QA2/QA3는 Baseline의 최적 부하(iso-load)에서 비교했다.

별 경계는 DP1 값을 DP2 후보 실행 전에 그대로 고정했다(`qa-criteria-dp2.md` §6). 공통 기준 별점(참고): QA1 ★★★/★★★, QA2 ★★★/★★★, QA3 ★★/★★ (C1/C2).

## 0.2 요약과 그 이유

1. **두 후보 모두 Baseline보다 처리량이 높다.** Max SLO goodput이 C1 x1.66(95% CI ±0.03), C2 x1.66이고 진 쌍은 없다. 단 이 배수는 Baseline이 SLO를 거의 못 지키도록 설계된 시나리오(링크 경합 x6~8, 긴 History x3~4)가 끌어올린다. 중앙에 가까운 시나리오는 x1.0~1.7이다(4.2).
2. **이득의 출처는 둘이다.** (a) 고정 역할 낭비: Baseline은 Decode 노드의 Prefill 능력을 쓰지 않는다. Planner는 여유 노드에서 Prefill한다. 공통 시나리오에서도 x1.3~2.1이 나온 이유다(사전 가설 "공통은 saturated"는 틀렸다). (b) History 위치를 모르고 왕복 전송하는 낭비: 링크 경합, 긴 History, 대형 세션 쏠림에서 TTFT P99가 크게 준다.
3. **C1과 C2는 구분되지 않는다.** goodput 비 C2/C1 = x1.002(범위 0.97~1.06), QA2·QA3도 같다. Oracle(실시간 정확 상태, 결정 비용 0)과도 거의 같다(x1.66). 이 평가의 노드 수(5~6)와 결정 비용 가정(1 ms @ 64 후보)에서 결정 시점·지연은 성능을 바꾸지 못한다. C2의 plan age 평균 0.0 ms 대비 1.2 ms, Late Validation 실패로 인한 재계획은 공통 시나리오에서 약 31%, 그 외 대부분 0%다.
4. **Baseline보다 나쁜 곳이 있다.** TPOT P99는 x1.34(나쁨, 단 12.0 ms로 SLO 50 ms 이내). Common 3개 집합에서는 TTFT P99도 x1.50로 나쁘고 QA2 개선 배수가 x0.78로 1 미만이다. Cost가 TPOT 여유를 TTFT와 맞바꾸고, Baseline 최적 부하에서는 TTFT가 이미 짧아 이득이 없기 때문이다(5.2). 또한 각자 최적 부하에서 비교하면 QA2 개선 배수는 x1.12(C1)로 별이 ★★로 내려간다. QA2 ★★★은 iso-load 정의(결과를 본 뒤 정함)에 의존한다.
5. **단순한 참고 정책 P-retain(Prefill을 History가 있던 노드에서 유지)이 QA2에서 더 높다**(x1.80 대 C1 x1.58). 처리량은 낮다(x1.43). Cost Model의 TTFT/TPOT 가중 구조가 개선 여지다. D-local-always는 Prefill을 한 노드에 몰아 처리량이 x0.16로 무너진다.

6. **확장성(QA5)에서 두 후보 모두 N=32에서 무너진다**: η(N=32)는 Baseline 1.00, C1 0.00(결정 64 ms/건으로 단일 scheduler 포화, SLO 만족 goodput 0), C2(worker 4) 0.56(worker 16 0.64). top-k=8 pruning을 쓰면 C1 1.00, C2 0.94. 결정 비용이 후보 수에 선형이라는 ASSUMED 가정의 결과이며 4.7에 0.1/1/10 ms 민감도를 둔다. 노드당 부하 grid 끝에서 peak가 나온 경우가 있고 seed가 2개(확장 부하는 1개)라 η에는 ±0.1 정도의 잡음이 있다.

## 0.3 선택

별 합계(QA1~QA5): C1 13, C2 13. QA 우선순위(`qa_priority.json`)는 소유자 확정 전(제안)이라 **선택은 보류**한다. 두 후보의 별 합계가 같아 이 평가는 선택을 가르지 못한다. QA5의 차이(worker 수별 η)는 결정 비용 가정(ASSUMED)에 의존한다. QA1~QA4만으로는 C1과 C2는 동점이고, QA5는 둘 다 ★이다(N=32, pruning 없음).

## 0.4 부족한 부분

| # | 약점 (근거) | 보완 방향 | 상태 |
|---|---|---|---|
| T1 | Cost = SLO 분율 합이 TTFT와 TPOT를 맞바꾼다. 공통 시나리오에서 TTFT·TPOT P99가 Baseline보다 나쁘다. P-retain보다 QA2가 낮다 | TPOT 실현 가능 후보 중 TTFT 최소 선택(Selector 교체). QA4 S3 smoke에서 공통 TTFT P99 3.7 s → 0.7 s로 줄었다(1회 실행, 평가 아님) | [C] 평가 미실시 |
| T2 | Baseline이 SLO를 못 맞추는 시나리오가 배수를 키운다 | 대조군·경계 시나리오 확대 | 한계로 기록 |
| T3 | 후보 수 선형 결정 비용에서 N=32 이상이면 C1은 scheduler 포화, C2는 plan 처리량 부족 (QA5) | 후보 pruning(top-k)을 설계에 포함. 4.7에서 top-k=8이면 η 약 1.0 | [B+C] 4.7 |

## 0.5 어떤 상황을 평가했나

Common 3(8K→256 대화), Stress 12(History Tier별 멀티턴, 부하 모양, 링크 경합 등), Dynamic 4(처음엔 문제없다가 나빠지는 경우). 상세는 3장.

# 1. 시스템 환경

| 항목 | 값 |
|---|---|
| SYS id | SYS-H100, SYS-B200 (통합). 값은 [system-specs.md](../../system-specs.md) |
| Model / precision | Llama-3.1-70B BF16 (KV 327,680 B/token), SLO TTFT P99 ≤ 2 s, TPOT P99 ≤ 50 ms |
| 노드 간 링크 | RDMA 400G 1 rail = 50 GB/s, 지연 100 us (**ASSUMED**), sweep 12.5/50/200/400 GB/s |
| 토폴로지 | 노드 = 8-GPU TP8 인스턴스 1개. Common 4P+1D, 대부분 2P+2D, long_ctx 1P+2D, skew 2P+4D |
| Git revision | 5e8d3d904 (dirty) |
| Seeds / loads | seed 11/23/37/53/71, 시나리오별 부하 grid |
| 재현 | `cd doc-mk/Evaluation/DP2/sim && python3 qa_eval.py run --workers 4 && python3 qa_eval.py agg`, QA5: `qa5_scale.py`, 민감도: `sens.py`, 문서: `tools/gen_dp2_result.py` |
| Raw data | `results/data/SYS-*/runs.jsonl`, `qa_result.json`, `qa5_result.json`, `sens_result.json`, `qa4_*.json` |

# 2. 평가 항목

| 항목 | 정의 / formula | 출처 |
|---|---|---|
| QA1 | 시나리오별 부하 sweep 중 SLO(TTFT·TPOT 모두 만족)를 만족한 요청의 output token/s 최대값(후보별 자기 최적 부하). 후보÷Baseline 비의 기하평균. 별 < 0.97 / 0.97~1.30 / ≥ 1.30 | criteria §4 + `qa-criteria-dp2.md` §6 |
| QA2 | **Baseline의 최적 부하**에서 TTFT·TPOT × P50/P95/P99 6개 지표의 개선 배수(Baseline÷후보)의 기하평균. 별 < 0.95 / 0.95~1.25 / ≥ 1.25. 표의 (x)는 후보÷Baseline 값 | criteria §5. iso-load는 **첫 결과를 본 뒤 정의**(`defined_after_first_look`) |
| QA3 | `U_useful`(SLO 만족 토큰 비중을 곱한 iteration GPU 시간 ÷ 노드 수×측정 시간), Baseline 최적 부하에서. 별은 후보÷Baseline 비율 < 0.95 / 0.95~1.25 / ≥ 1.25 | **임시 정의** |
| QA4 | module 수 · 공수 · 에이전트 비용, 변경 시나리오 4종 평균. 별은 세 sub-star의 중앙값 | `qa4-preregistration.md` (사전 등록) |
| QA5 | η(N) = Max SLO goodput(N) ÷ (N/2 × Max SLO goodput(N=2)), N=32. 별 < 0.70 / 0.70~0.90 / ≥ 0.90. 단일 시스템(H100), seed 2개 | `qa-criteria-dp2.md` §3 (제안값) |
| Diagnostic | 결정 지연, plan age, 재계획 수, regret, 풀 사용률, 노드 간 KV 이동량 | `qa-criteria-dp2.md` §4 |
| 판정 | 쌍별 paired-by-seed, 95% CI t(0.975,4)=2.776, 물질성 1% | DP1과 동일 |

# 3. 벤치마크 / 시나리오

Fit label: comparison_valid = Baseline이 SLO를 일부 만족해 비교 가능. 모든 쌍이 comparison_valid이지만 다음을 주의한다: Baseline의 goodput이 매우 작은 쌍(예: 링크 경합 53 tok/s)은 비율이 크게 나온다.

| Set | 시나리오 | H100 | B200 | 설명 |
|---|---|---|---|---|
| Common | `cb_kv_8k_b32` | comp | comp | 공통. 8K→256, 동시성 sweep, KV만, D 노드 HBM x0.12 (4P+1D) |
| Common | `cb_kv_8k_b32_ramp` | comp | comp | 공통. 위와 같고 D 노드 HBM 압박이 점진 증가 |
| Common | `cb_mixed_8k_b32` | comp | comp | 공통. KV + 다른 데이터가 D 노드 HBM 30% 점유 |
| DP2 Stress | `dp2_turn_hbm_small_tool` | comp | comp | History 32K가 D의 HBM, Tool 결과 0.5K인 멀티턴 (2P+2D) |
| DP2 Stress | `dp2_turn_dram_small_tool` | comp | comp | History 64K가 DRAM으로 내려간 뒤 재개 |
| DP2 Stress | `dp2_turn_hbf_hist` | comp | comp | History 128K가 HBF(GPU 직접 읽기)에 있는 재개 |
| DP2 Stress | `dp2_turn_ssd_hist` | comp | comp | History 64K가 SSD-PIM에 있는 재개 (대조군) |
| DP2 Stress | `dp2_tool_large_result` | comp | comp | Tool 결과 16K로 큰 턴 (대조군, P 경로가 최적일 것) |
| DP2 Stress | `dp2_prefill_burst_p_saturated` | comp | comp | Prefill burst(MMPP)로 P 포화, D 여유 |
| DP2 Stress | `dp2_decode_heavy_p_idle` | comp | comp | 출력 2K 위주로 D 포화, P 유휴 |
| DP2 Stress | `dp2_long_ctx_decode_offload` | comp | comp | 128~256K History, D HBM x0.3, ScHBM 오프로드 (1P+2D) |
| DP2 Stress | `dp2_session_size_skew` | comp | comp | 5% 256K 대형 세션 + 95% 8K 채팅 (2P+4D) |
| DP2 Stress | `dp2_internode_link_contention` | comp | comp | P↔D 링크를 다른 트래픽과 공유(BW x0.25) |
| DP2 Stress | `dp2_stale_telemetry` | comp | comp | Telemetry 갱신 지연(지연 sweep 기준점) |
| DP2 Stress | `dp2_planner_fault_fallback` | comp | comp | T/2에 Planner 중단, fallback = Baseline 규칙 |
| DP2 Dynamic | `dyn_turn_demotion_wave` | comp | comp | 세션 idle 후 History가 DRAM→CXL-PNM으로 내려간 뒤 재개 |
| DP2 Dynamic | `dyn_load_ramp_burst` | comp | comp | 도착률 0.4→1.1 포화 ramp + burst |
| DP2 Dynamic | `dyn_p_node_degrade` | comp | comp | T/2에 P 노드 처리량 x0.5 |
| DP2 Dynamic | `dyn_decode_phase_shift` | comp | comp | 출력 길이 256→2K 전환 |

참고 정책(별 미부여): D-local-always(항상 KV가 있는 D에서 Prefill), P-retain(Prefill을 직전 P 노드에서 유지, 더 강한 As-Is), Oracle(실시간 정확 상태, 결정 비용 0, 상한).

# 4. 결과

## 4.1 최종 QA 표

| QA | metric | Baseline | C1 | C2 |
|---|---|---|---|---|
| **QA1 Throughput** | Max SLO goodput (tok/s) ↑ | 575 | ★★★  954 (x1.66) | ★★★  956 (x1.66) |
| **QA2 Latency — TTFT** | P99 · P50 (ms) ↓ | P99 2,461 · P50 627 | P99 984 (x0.40) · P50 206 (x0.33) | P99 1,015 (x0.41) · P50 208 (x0.33) |
| **QA2 Latency — TPOT** | P99 · P50 (ms) ↓ | P99 8.9 · P50 5.8 | P99 12.0 (x1.34) · P50 5.3 (x0.91) | P99 12.0 (x1.35) · P50 5.3 (x0.91) |
| **QA2 별점** | 6개 지표 개선 배수 geomean | x1.00 | ★★★  x1.58 (TTFT x2.83 · TPOT x0.89) | ★★★  x1.56 (TTFT x2.77 · TPOT x0.88) |
| **QA3 Resource utilization** | useful GPU 사용률 (%) ↑ | 43.7 | ★★★  67.0 (x1.52) | ★★★  66.8 (x1.51) |
| **QA4 Modifiability** | module · 공수(MM) · 에이전트 비용 ↓ | — | ★★★  1.50 · 0.27 · $1.03 | ★★★  1.75 · 0.31 · $1.10 |
| **QA5 Scalability** | η (N=32 노드), 결정 지연 ↑ | η 1.00 | ★  η 0.00 · 결정 64.0 ms(임계 경로) | ★  η 0.56 · 결정 0.0 ms(임계 경로) |
| **별 합계 (QA1~QA5)** |  | — | 13 | 13 |

(QA1~QA3는 SYS-H100 + SYS-B200 통합 19x2쌍. QA5는 SYS-H100만, seed 2개. QA4는 시뮬레이터 복사본에서 측정, 공수·비용은 가정 상수.)

### 집합별 (후보÷Baseline, 기하평균)

**C1-scheduling-time**

| 집합 | 쌍 | QA1 goodput | TTFT P99 | TPOT P99 | QA2 개선 | QA3 U |
|---|---|---|---|---|---|---|
| Common | 6 | x1.69 | x1.50 | x1.75 | x0.78 | x1.62 |
| DP2 Stress | 24 | x1.80 | x0.29 | x1.38 | x1.73 | x1.48 |
| DP2 Dynamic | 8 | x1.29 | x0.41 | x1.01 | x2.06 | x1.55 |

**C2-pre-planned**

| 집합 | 쌍 | QA1 goodput | TTFT P99 | TPOT P99 | QA2 개선 | QA3 U |
|---|---|---|---|---|---|---|
| Common | 6 | x1.70 | x1.57 | x1.76 | x0.76 | x1.60 |
| DP2 Stress | 24 | x1.80 | x0.30 | x1.39 | x1.70 | x1.48 |
| DP2 Dynamic | 8 | x1.29 | x0.39 | x1.01 | x2.08 | x1.55 |

### 시스템별

| SYS | 후보 | QA1 | TTFT P99 | TPOT P99 | QA2 개선 | QA3 U | 별(QA1/2/3) |
|---|---|---|---|---|---|---|---|
| SYS-H100 | C1 | x1.56 | x0.50 | x1.47 | x1.35 | x1.56 | ★★★/★★★/★★★ |
| SYS-H100 | C2 | x1.56 | x0.52 | x1.49 | x1.32 | x1.55 | ★★★/★★★/★★★ |
| SYS-B200 | C1 | x1.77 | x0.32 | x1.23 | x1.85 | x1.48 | ★★★/★★★/★★★ |
| SYS-B200 | C2 | x1.77 | x0.33 | x1.22 | x1.84 | x1.48 | ★★★/★★★/★★★ |

## 4.1a 참고 정책 대비 (통합)

| 정책 | QA1 비 | TTFT P99 | TPOT P99 | QA2 개선 | QA3 U | Baseline 대비 승/무/패 |
|---|---|---|---|---|---|---|
| C1 | x1.66 | x0.40 | x1.34 | x1.58 | x1.52 | 38/0/0 |
| C2 | x1.66 | x0.41 | x1.35 | x1.56 | x1.51 | 38/0/0 |
| Oracle | x1.66 | x0.41 | x1.35 | x1.56 | x1.52 | 38/0/0 |
| P-retain | x1.43 | x0.41 | x0.97 | x1.80 | x1.06 | 23/12/3 |
| D-local-always | x0.16 | x0.51 | x1.47 | x1.21 | x0.10 | 18/0/20 |

승/무/패는 쌍별 paired-by-seed(goodput, TTFT P99, TPOT P99 종합, 95% CI, 1% 물질성). TPOT가 나쁜 쌍이 많아 'loss' 성분은 4.4에서 따로 센다.

## 4.2 시나리오별 결과 (Baseline의 최적 부하, goodput 비는 각자 최적 부하)

| Set | 시나리오 | SYS | Baseline goodput | B 최적 부하 | C1 | C2 | Oracle | P-retain | TTFT P99 s (B/C1/C2) | TPOT P99 ms (B/C1/C2) |
|---|---|---|---|---|---|---|---|---|---|---|
| Common | `cb_kv_8k_b32` | H100 | 1,157 | 24 | x1.39 | x1.48 | x1.37 | x1.00 | 3.14 / 3.82 / 3.69 | 12.1 / 34.7 / 34.5 |
| Common | `cb_kv_8k_b32` | B200 | 2,574 | 12 | x2.08 | x2.08 | x1.99 | x1.00 | 0.44 / 0.74 / 0.68 | 5.3 / 6.5 / 5.2 |
| Common | `cb_kv_8k_b32_ramp` | H100 | 1,136 | 12 | x1.48 | x1.46 | x1.44 | x1.00 | 1.02 / 1.87 / 2.38 | 9.6 / 17.0 / 19.7 |
| Common | `cb_kv_8k_b32_ramp` | B200 | 2,625 | 12 | x2.04 | x2.07 | x1.96 | x1.00 | 0.44 / 0.66 / 0.71 | 5.2 / 5.5 / 5.9 |
| Common | `cb_mixed_8k_b32` | H100 | 1,258 | 20 | x1.29 | x1.31 | x1.28 | x1.00 | 2.82 / 3.22 / 3.43 | 8.5 / 29.3 / 29.5 |
| Common | `cb_mixed_8k_b32` | B200 | 2,658 | 12 | x2.02 | x2.02 | x1.95 | x1.00 | 0.41 / 0.75 / 0.76 | 5.0 / 6.4 / 6.5 |
| DP2 Stress | `dp2_turn_hbm_small_tool` | H100 | 1,545 | 96 | x1.33 | x1.33 | x1.33 | x1.28 | 3.51 / 1.04 / 1.08 | 15.4 / 20.5 / 20.0 |
| DP2 Stress | `dp2_turn_hbm_small_tool` | B200 | 1,571 | 84 | x1.62 | x1.62 | x1.62 | x1.60 | 3.23 / 0.12 / 0.15 | 4.1 / 4.9 / 5.0 |
| DP2 Stress | `dp2_turn_dram_small_tool` | H100 | 415 | 24 | x1.51 | x1.50 | x1.51 | x1.57 | 2.75 / 1.86 / 1.80 | 19.7 / 18.4 / 17.6 |
| DP2 Stress | `dp2_turn_dram_small_tool` | B200 | 459 | 24 | x1.68 | x1.68 | x1.70 | x1.67 | 2.39 / 1.40 / 1.42 | 13.2 / 7.6 / 7.8 |
| DP2 Stress | `dp2_turn_hbf_hist` | H100 | 157 | 12 | x1.37 | x1.40 | x1.39 | x1.73 | 5.29 / 4.35 / 4.22 | 12.5 / 36.5 / 37.5 |
| DP2 Stress | `dp2_turn_hbf_hist` | B200 | 189 | 12 | x1.25 | x1.26 | x1.24 | x2.83 | 3.55 / 4.16 / 4.02 | 5.5 / 22.7 / 23.2 |
| DP2 Stress | `dp2_turn_ssd_hist` | H100 | 57 | 6 | x1.70 | x1.70 | x1.70 | x2.40 | 4.48 / 3.81 / 4.06 | 26.3 / 20.4 / 20.5 |
| DP2 Stress | `dp2_turn_ssd_hist` | B200 | 55 | 6 | x1.76 | x1.77 | x1.74 | x2.69 | 4.62 / 3.88 / 3.88 | 21.1 / 15.6 / 14.6 |
| DP2 Stress | `dp2_tool_large_result` | H100 | 149 | 12 | x1.71 | x1.73 | x1.74 | x0.86 | 5.45 / 3.96 / 3.99 | 12.7 / 27.5 / 26.8 |
| DP2 Stress | `dp2_tool_large_result` | B200 | 523 | 24 | x1.10 | x1.10 | x1.07 | x0.99 | 2.98 / 2.26 / 2.36 | 6.5 / 14.5 / 14.9 |
| DP2 Stress | `dp2_prefill_burst_p_saturated` | H100 | 295 | 2 | x1.27 | x1.27 | x1.29 | x1.00 | 8.57 / 3.71 / 3.79 | 11.5 / 20.6 / 20.6 |
| DP2 Stress | `dp2_prefill_burst_p_saturated` | B200 | 768 | 1.5 | x1.83 | x1.84 | x1.79 | x1.00 | 8.37 / 2.43 / 2.44 | 6.6 / 20.7 / 20.1 |
| DP2 Stress | `dp2_decode_heavy_p_idle` | H100 | 5,636 | 96 | x1.20 | x1.18 | x1.19 | x1.00 | 0.26 / 0.24 / 0.31 | 15.3 / 11.8 / 15.1 |
| DP2 Stress | `dp2_decode_heavy_p_idle` | B200 | 10,369 | 96 | x1.10 | x1.11 | x1.11 | x1.00 | 0.31 / 0.12 / 0.14 | 5.2 / 4.5 / 4.6 |
| DP2 Stress | `dp2_long_ctx_decode_offload` | H100 | 40 | 4 | x3.20 | x3.12 | x3.19 | x2.11 | 6.43 / 1.88 / 1.73 | 14.9 / 15.7 / 15.7 |
| DP2 Stress | `dp2_long_ctx_decode_offload` | B200 | 54 | 4 | x3.83 | x3.81 | x3.81 | x3.44 | 4.66 / 0.29 / 0.30 | 5.1 / 5.4 / 5.4 |
| DP2 Stress | `dp2_session_size_skew` | H100 | 3,126 | 1.5 | x1.70 | x1.70 | x1.69 | x1.63 | 24.54 / 0.41 / 0.54 | 28.1 / 23.9 / 25.8 |
| DP2 Stress | `dp2_session_size_skew` | B200 | 3,256 | 1.5 | x1.72 | x1.72 | x1.72 | x1.72 | 34.97 / 0.11 / 0.15 | 4.7 / 5.3 / 5.5 |
| DP2 Stress | `dp2_internode_link_contention` | H100 | 54 | 6 | x6.64 | x6.66 | x6.65 | x6.40 | 4.74 / 0.76 / 0.75 | 12.0 / 15.2 / 14.9 |
| DP2 Stress | `dp2_internode_link_contention` | B200 | 53 | 4 | x7.67 | x7.68 | x7.68 | x7.43 | 3.68 / 0.66 / 0.65 | 6.0 / 3.7 / 3.7 |
| DP2 Stress | `dp2_stale_telemetry` | H100 | 355 | 2 | x1.15 | x1.15 | x1.14 | x1.00 | 4.00 / 1.47 / 1.44 | 7.3 / 23.2 / 21.4 |
| DP2 Stress | `dp2_stale_telemetry` | B200 | 798 | 1 | x1.94 | x2.00 | x1.91 | x1.00 | 3.21 / 0.58 / 0.59 | 3.6 / 8.9 / 9.6 |
| DP2 Stress | `dp2_planner_fault_fallback` | H100 | 286 | 2 | x1.29 | x1.29 | x1.28 | x1.00 | 8.39 / 6.16 / 6.16 | 11.3 / 20.3 / 20.3 |
| DP2 Stress | `dp2_planner_fault_fallback` | B200 | 768 | 1.25 | x1.59 | x1.58 | x1.79 | x1.00 | 6.16 / 4.98 / 4.98 | 6.7 / 11.8 / 10.6 |
| DP2 Dynamic | `dyn_turn_demotion_wave` | H100 | 147 | 24 | x1.01 | x1.01 | x1.01 | x1.01 | 0.51 / 0.24 / 0.23 | 7.6 / 7.7 / 7.7 |
| DP2 Dynamic | `dyn_turn_demotion_wave` | B200 | 151 | 24 | x1.00 | x1.00 | x1.00 | x1.00 | 0.49 / 0.20 / 0.20 | 3.4 / 3.0 / 3.0 |
| DP2 Dynamic | `dyn_load_ramp_burst` | H100 | 1,132 | 1.5 | x1.46 | x1.46 | x1.46 | x1.17 | 4.68 / 0.93 / 0.92 | 18.2 / 17.6 / 18.3 |
| DP2 Dynamic | `dyn_load_ramp_burst` | B200 | 1,220 | 1.5 | x1.44 | x1.44 | x1.44 | x1.44 | 3.07 / 0.23 / 0.16 | 4.0 / 4.6 / 4.6 |
| DP2 Dynamic | `dyn_p_node_degrade` | H100 | 367 | 24 | x1.59 | x1.61 | x1.61 | x1.78 | 3.35 / 1.84 / 1.93 | 19.3 / 34.2 / 33.2 |
| DP2 Dynamic | `dyn_p_node_degrade` | B200 | 399 | 24 | x1.84 | x1.81 | x1.85 | x1.93 | 3.11 / 1.66 / 1.85 | 12.9 / 10.9 / 11.2 |
| DP2 Dynamic | `dyn_decode_phase_shift` | H100 | 4,394 | 96 | x1.12 | x1.13 | x1.13 | x1.00 | 0.15 / 0.25 / 0.23 | 10.4 / 9.2 / 9.0 |
| DP2 Dynamic | `dyn_decode_phase_shift` | B200 | 7,104 | 96 | x1.07 | x1.06 | x1.07 | x1.00 | 0.21 / 0.13 / 0.13 | 4.5 / 3.8 / 3.8 |

## 4.3 Diagnostic (통합, Baseline 최적 부하 평균)

| 지표 | Baseline | C1 | C2 |
|---|---:|---:|---:|
| 결정 지연 평균 (ms) | 0 | 1.10 | 0.04 |
| plan age 평균 (ms) | — | — | 1.2 |
| regret 평균 (Cost, SLO 분율) | — | 0.067 | 0.069 |
| mis-selection 비율 | — | 0.37 | 0.36 |
| P 풀 / D 풀 useful 사용률 | 20% / 85% | 65% / 82% | 65% / 81% |
| P 노드 간 부하 CV | 0.24 | 0.07 | 0.07 |
| Turn당 노드 간 KV 이동 (GiB) | 14.6 | 4.7 | 4.9 |

## 4.4 승/무/패 성분 (Baseline 대비, 38쌍)

| 후보 | goodput 승/무/패 | TTFT P99 승/무/패 | TPOT P99 승/무/패 |
|---|---|---|---|
| C1 | 36/2/0 | 26/9/3 | 10/9/19 |
| C2 | 36/2/0 | 25/10/3 | 10/9/19 |

TTFT·TPOT는 Baseline의 최적 부하에서의 paired 비교다. **TPOT P99가 유의하게 나쁜 쌍이 절반**이다(전부 SLO 이내). 이 값은 Baseline-regression loop 대상이며 5.2에서 진단한다.

## 4.5 민감도 (SYS-H100, 6개 시나리오, Baseline 최적 부하, goodput 비의 기하평균, seed 3개)

| 축 | 값 | C1 | C2 | Oracle | 집계에 쓴 시나리오 |
|---|---|---|---|---|---|
| 노드 간 링크 | rdma_100g | x1.40 | x1.42 | x1.36 | 1/6 |
| 노드 간 링크 | rdma_400g_1rail | x1.42 | x1.42 | x1.42 | 6/6 |
| 노드 간 링크 | rdma_400g_4rail | x1.04 | x1.04 | x1.04 | 6/6 |
| 노드 간 링크 | rdma_400g_8rail | x1.02 | x1.03 | x1.02 | 6/6 |
| Cost Model 오차 ε | 0.0 | x1.42 | x1.42 | x1.42 | 6/6 |
| Cost Model 오차 ε | 0.2 | x1.44 | x1.43 | x1.42 | 6/6 |
| Cost Model 오차 ε | 0.4 | x1.44 | x1.44 | x1.42 | 6/6 |
| Cost Model 오차 ε | 0.6 | x1.45 | x1.45 | x1.42 | 6/6 |
| Telemetry 주기(s) | 0.01 | x1.41 | x1.40 | x1.41 | 6/6 |
| Telemetry 주기(s) | 0.05 | x1.42 | x1.42 | x1.42 | 6/6 |
| Telemetry 주기(s) | 0.25 | x1.40 | x1.40 | x1.38 | 6/6 |
| Telemetry 주기(s) | 1.0 | x1.35 | x1.35 | x1.33 | 6/6 |
| 결정 비용 T_ref(s) | 0.0001 | x1.42 | x1.43 | x1.42 | 6/6 |
| 결정 비용 T_ref(s) | 0.001 | x1.42 | x1.42 | x1.42 | 6/6 |
| 결정 비용 T_ref(s) | 0.01 | x1.48 | x1.43 | x1.42 | 6/6 |

비는 같은 축 값의 Baseline 대비다(링크 축에서는 Baseline도 함께 바뀐다). Baseline goodput이 Oracle의 10% 미만인 시나리오는 비가 발산하므로 집계에서 뺐고 마지막 열에 남은 수를 적었다. 측정 부하는 50 GB/s에서 정한 Baseline 최적 부하로 고정했으므로 링크가 빠른 행(200, 400 GB/s)은 Baseline이 더 높은 부하를 받을 수 있는데도 같은 부하에서 비교한 값이라 비가 줄어든다(Max SLO goodput 비교가 아니다). 이득이 링크 대역폭에 의존한다는 것은 확인되지만 크기는 과소평가일 수 있다. ε와 결정 비용은 이 범위에서 영향이 없다(ε 증가에도 이득이 줄지 않음). Telemetry 1 s에서만 x1.35로 소폭 감소한다. 링크가 12.5 GB/s이면 Baseline이 SLO를 못 맞추는 시나리오가 많아 후보의 상대 이득이 실제로는 더 크다.

## 4.6 QA4 Modifiability

| 시나리오 | C1 module·LOC·MM | C2 module·LOC·MM |
|---|---|---|
| S1 | 2 · 5 · 0.345 | 2 · 5 · 0.345 |
| S2 | 1 · 3 · 0.179 | 1 · 3 · 0.179 |
| S3 | 1 · 4 · 0.19 | 1 · 4 · 0.19 |
| S4 | 2 · 7 · 0.369 | 3 · 8 · 0.524 |

평균: C1 1.50 module · 0.27 MM · $1.03, C2 1.75 · 0.31 · $1.10. 시나리오: S1 신규 Tier(`cxl_pnm2`), S2 신규 Cost 항(에너지), S3 Selector 교체, S4 신규 telemetry 신호(health). 사전 등록 [`qa4-preregistration.md`](../qa4-preregistration.md), 측정 [`results/data/qa4_measured_counts.json`](data/qa4_measured_counts.json), 패치 `results/data/qa4_patches/`. `qa4_modifiability.json`의 `sensitivity_structure_alternatives` 항목은 DP1/DP4 구조용 분석식이라 **DP2에는 해당하지 않는다.** 이 simulator는 C1/C2가 Cost Model·Selector·Resource State를 공유해 차이가 작다. 실제 vLLM 통합과 다르며 module 귀속은 판단이다(주입 wiring을 별도 module로 세면 두 후보 모두 +1).

## 4.7 QA5 Scalability (SYS-H100, seed 2개, 노드당 부하 grid 2~24 clients, 확장 부하 16/20/24는 seed 11만)

| variant | N=2 | N=4 | N=8 | N=16 | N=32 | N=64 |
|---|---|---|---|---|---|---|
| Baseline | 760 (η 1.00) | 1,521 (η 1.00) | 3,057 (η 1.01) | 6,083 (η 1.00) | 12,174 (η 1.00) | 26,681 (η 1.10) |
| C1 | 1,765 (η 1.00) | 3,208 (η 0.91) | 6,155 (η 0.87) | 12,645 (η 0.90) | 0 (η 0.00) | 0 (η 0.00) |
| C1+topk8 | 1,716 (η 1.00) | 3,164 (η 0.92) | 6,361 (η 0.93) | 14,075 (η 1.03) | 27,431 (η 1.00) | 48,553 (η 0.88) |
| C2(w=4) | 1,750 (η 1.00) | 3,123 (η 0.89) | 4,920 (η 0.70) | 9,806 (η 0.70) | 15,638 (η 0.56) | 0 (η 0.00) |
| C2(w=1) | 1,765 (η 1.00) | 3,257 (η 0.92) | 5,922 (η 0.84) | 12,775 (η 0.90) | 0 (η 0.00) | 0 (η 0.00) |
| C2(w=16) | 1,750 (η 1.00) | 3,229 (η 0.92) | 5,642 (η 0.81) | 9,430 (η 0.67) | 17,814 (η 0.64) | 15,535 (η 0.28) |
| C2+topk8 | 1,879 (η 1.00) | 3,284 (η 0.87) | 5,486 (η 0.73) | 13,102 (η 0.87) | 28,260 (η 0.94) | 51,836 (η 0.86) |

결정 지연 평균(ms)과 TTFT P99(s), N=32:

| variant | 결정 지연 | TTFT P99 | 재계획 |
|---|---|---|---|
| Baseline | 0.00 | 1.89 | 0 |
| C1 | 64.00 | 2.58 | 0 |
| C1+topk8 | 5.06 | 1.30 | 0 |
| C2(w=4) | 0.02 | 0.88 | 0 |
| C2(w=1) | 0.02 | 2.58 | 0 |
| C2(w=16) | 0.02 | 1.60 | 0 |
| C2+topk8 | 0.05 | 1.29 | 3068 |

후보 공간(노드당 Tier 수) 및 결정 비용 민감도, N=32 (Max SLO goodput tok/s):

| 조건 | C1 | C2(w=4) |
|---|---|---|
| Tier 수 1 | 15,623 | 17,307 |
| Tier 수 2 | 7,850 | 19,969 |
| Tier 수 4 | 0 | 15,638 |
| T_ref 0.1 ms | 20,244 | 17,059 |
| T_ref 1 ms | 0 | 15,638 |
| T_ref 10 ms | 0 | 0 |

# 5. 결과 분석

## 5.1 이득이 나는 이유
- **고정 역할의 낭비.** 공통 시나리오(4P+1D, 8K→256)에서 Baseline은 P 4개만 Prefill한다. Planner는 D 노드와 P 노드를 가리지 않고 Prefill해 H100에서 x1.39, B200에서 x2.08다. P-retain은 x1.00(역할 고정과 같은 결정)이라 이 이득은 "D 노드 Prefill 활용"에서 온다.
- **전송 낭비.** 링크 경합(BW 25%): Baseline은 History를 왕복해 TTFT P99 3.7 s, Planner는 History가 있는 노드에서 Prefill해 0.66 s(B200). 이 경우 D-local-always도 같은 이득이다 — **단순 휴리스틱으로 충분한 영역**이다.
- **쏠림 회피.** 대형 세션 쏠림에서 Baseline TTFT P99 35.0 s → C1 0.11 s(B200). P-retain도 0.12 s로 비슷하다.
- **Tier 인지가 필요한 영역.** HBF·SSD-PIM History(`dp2_turn_hbf_hist`, `dp2_turn_ssd_hist`)에서는 P-retain이 C1/C2보다 높다(HBF B200 x2.83 대 C1 x1.25). **이기종 Tier 정보를 쓰는 Cost Model이 가장 단순한 규칙보다 낫다는 주장은 이 평가에서 성립하지 않는다**(HBF/SSD에서 더 낮음, 원인은 5.2).

## 5.2 Baseline보다 나쁜 곳 (Baseline-regression)
- Common 3개 집합: Baseline 최적 부하에서 TTFT P99 x1.50, TPOT P99 x1.75, QA2 개선 x0.78(< 1). goodput은 x1.69로 높아 **지연을 처리량과 맞바꾼다.**
- TPOT P99가 유의하게 나쁜 쌍이 C1 19/38. 값은 SLO 이내.
- **원인 진단(P/M 분류):** Cost 정의(M, cost model gap). Cost = TTFT/SLO + TPOT/SLO + 외부효과의 합이라 TPOT 여유가 있으면 TTFT를 줄이는 쪽으로 쓰고, 그 결과 TPOT가 SLO까지 올라가도 비용이 같다. 개발 점검(QA4 S3 smoke, 공통 cb_kv_8k_b32 H100 load 24, seed 11, 1회)에서 "TPOT 실현 가능 후보 중 TTFT 최소" Selector로 바꾸면 TTFT P99가 3.7 s → 0.7 s였다. 정책 상수나 시나리오별 조정은 하지 않았고 이 변경은 평가에 반영하지 않았다.
- HBF/SSD History에서 P-retain이 더 높은 이유: 이 시나리오의 History가 HBF에 있을 때 Planner는 HBM으로 승격·전송 비용을 모두 비용으로 보고 다른 노드로 보내는 경우가 있다(추정, 요청 단위 분해는 하지 않았다).

## 5.3 C1과 C2가 같은 이유
결정 비용이 1 ms @ 64 후보이고 노드가 4~6개라 후보 수 K ≈ 16~100, 결정 지연이 C1 1.10 ms로 요청 도착 간격보다 훨씬 짧다. plan age 평균 1.2 ms로 Late Validation이 거의 통과한다. 두 후보는 같은 Cost Model과 같은 Selector를 쓰므로 차이는 결정 시점/지연에서만 생긴다. 이 조건에서는 그 차이가 0에 가깝다. 차이를 가르는 조건은 QA5(노드 수, 결정 비용)에서 본다.

# 6. 한계

1. 모든 수치는 [B+C] simulation이다. 노드 간 링크(50 GB/s), 결정 비용(1 ms @ 64 후보, 후보 수 선형), planner worker 4개, Telemetry 50 ms는 ASSUMED. 민감도는 4.5, 4.7.
2. QA2/QA3의 iso-load 집계는 공통 시나리오 2쌍을 본 뒤 정의했다(`defined_after_first_look`). 각자 최적 부하에서 비교한 값은 QA2 개선 x1.12(C1), x1.11(C2)로 **별이 ★★★에서 ★★로 내려간다**(경계 1.25 아래). QA2 별은 집계 정의에 민감하다. 이 정의는 결과를 본 뒤 정했으므로 ★★★은 확정이 아니다.
3. Baseline이 SLO를 못 맞추도록 설계한 시나리오(링크 경합, 긴 History)가 QA1 배수를 끌어올린다. 설계자가 Baseline의 실패 양상을 알고 만들었다. 공통 3개만의 QA1은 x1.69다.
4. 평가 규모가 노드 6개 이하(QA5 제외)다. QA5는 H100 단일 시스템, seed 2개, 단일 workload(4K→256)다. QA5의 별 경계(0.70/0.90)는 제안값이다.
5. QA3 U_useful은 처리량과 상관이 크다. QA4는 simulator 복사본 기준이고 공수·비용은 ASSUMED 상수다.
6. GPU 내 Prefill/Decode 간섭은 iteration 합산 근사다. NIXL 프로토콜, prefix cache 공유, 전력은 미반영이다. Decode 중 Tier 이동(DP1)은 평가하지 않았다(모든 후보가 같은 초기 배치).
7. 사전 가설 중 틀린 것: 공통 시나리오가 saturated일 것(H1)은 틀렸다(x1.3~2.1). C1이 QA3·TPOT에서 앞서고 C2가 확장성에서 앞설 것(H8)은 QA1~QA4에서 확인되지 않았다.
8. 소유자 결정 O1~O11은 미확정이며 별 경계·선택 규칙도 제안 상태다.

# 7. 결론

- Cost 기반 Prefill/Decode 실행 계획(C1, C2)은 고정 역할 Baseline보다 goodput을 크게 높인다(QA1 x1.66/x1.66, ★★★/★★★). 이득의 상당 부분은 Tier 인지가 아니라 역할 고정을 푸는 것(D 노드 Prefill 활용, 링크 왕복 제거)에서 온다.
- Tier 인지가 단순 규칙보다 낫다는 증거는 이 평가에서 부족하다. P-retain이 QA2에서 더 높고 HBF/SSD History에서도 C1/C2보다 높다.
- TPOT P99와 공통 시나리오의 TTFT P99는 Baseline보다 나쁘다. Cost 정의가 개선 여지다(5.2).
- C1과 C2는 QA1~QA4에서 구분되지 않는다. QA5에서는 비용 가정 하에 둘 다 N=32에서 무너지고(top-k pruning 없이는 ★), C2(worker 16)가 C1보다 낫지만 둘 다 pruning을 넣은 변형(η 약 1.0)보다 못하다. 다음 설계 결정은 C1/C2 선택이 아니라 후보 pruning이다.
- 다음 단계: Selector를 TPOT feasible 후보 중 TTFT 최소로 바꾼 변형 평가(새 사전 등록 필요), 노드 수·결정 비용 확대, [A] 결정 비용 측정, 소유자 결정(별 경계, 선택 규칙) 확정.

