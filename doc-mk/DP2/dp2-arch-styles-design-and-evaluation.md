# DP2 설계와 평가 정리: 중앙 Dispatcher 대 Blackboard (노드 내 attention 실행 위치 결정)

> 작성: 2026-10-10. 상태: **초안**. 모든 수치는 시뮬레이션 **[B+C]** 이며 실측 [A]가 아니다. 숫자의 원천은 `../Evaluation/DP2/results/2026-10-10_dp2-arch-styles.md`(생성기 출력)이고 이 문서는 그 요약이다.
> 관련: 후보 구조 논의 [`dp2-decision-structure-candidates-A-B-C.md`](dp2-decision-structure-candidates-A-B-C.md), 재설계 메모 [`../Requirements/memo-dp2-redesign-ideation.md`](../Requirements/memo-dp2-redesign-ideation.md), 발표 덱 [`../slides/dp2-arch-styles-dispatcher-vs-blackboard.pptx`](../slides/dp2-arch-styles-dispatcher-vs-blackboard.pptx)
> 표기: **[사용자 결정] / [Claude 제안] / [추정] / [가설] / [문서 근거]**

## 1. 한 장 요약

| 항목 | 내용 |
|---|---|
| 결정 | Turn(대화 턴) 시작 시, 한 노드 안에서 KV 구간별 attention을 어디서 실행할지: `GPU_STAGE`(KV를 HBM으로 옮겨 GPU attention) 또는 `IN_SITU(tier)`(KV가 있는 Tier에서 fused attention, `(m,l,o)` LSE 병합) |
| 비교 축 | **아키텍처 스타일**: 1안 중앙 Dispatcher(Master–Worker) 대 2안 Blackboard(공유 Task Board + 자율 Knowledge Source) |
| 평가 | Q1 처리량, Q2 지연, Q3 HBM KV 점유, Q4 변경 용이성. Baseline-GPU-local 대비, SYS-H100 + SYS-B200 통합, seed 5개 |
| 선택 | **1안 Dispatcher** (별 합계 9 대 8). 우선순위를 뒤집어도 같음 |
| 약점과 보완 | Dispatcher의 TPOT 꼬리(P99 ×1.34)와 Cost 추정 오차 의존 → **Hybrid C**(중앙 선택 + Tier 로컬 live 거부권), 미구현 [C] |

## 2. 설계

### 2.1 DP2의 범위 [사용자 결정]
- P/D 구분 없는 노드 내부 결정. 연산은 항상 GPU에서 시작하고 **attention만** 위치를 옮길 수 있다.
- DP1이 정한 KV 배치(Tier별 위치)는 입력이다. DP1 = 이동 후 데이터가 남는 배치, DP2 = 실행을 위한 일시적 staging. DP1과 DP2는 따로 평가한다.
- DP4는 이를 멀티 노드로 확장해 P/D 노드 역할을 가른다(이 문서 범위 밖).

### 2.2 왜 선택이 갈리는가 [추정]
- attention 연산 강도는 약 Tq×8 FLOP/B(Llama-70B급, GQA 8, BF16). H100 ridge ≈ 300이므로 Decode는 memory-bound, Prefill은 compute-bound다.
- KV는 약 320 KB/token(128K ≈ 43 GB, PCIe 64 GB/s에서 ≈ 0.67 s). Decode는 같은 KV를 출력 길이만큼 반복해 읽으므로 대역폭이 큰 Tier에서 제자리 실행이 유리하고, Prefill은 GPU가 유리하다. break-even Tq는 ScHBM ≲ 390, CXL-PNM ≲ 6.
- 동시 요청이 많으면 KV를 HBM으로 끌어오는 비용(HBM 용량, 쓰기 대역폭, 링크)이 처리량을 깎는다. 따라서 실행 위치 결정은 HBM 기회비용을 알아야 한다.

### 2.3 후보 구조 (같은 입력, 같은 출력 값)
공통: 노드 선택 규칙(`assign_node`)은 같고, 후보는 그 노드 안에서 **Decode attention이 실행될 Tier**만 정한다. Prefill은 항상 그 노드 GPU에서 chunked로 실행한다. 장애 구간은 모두 Baseline 규칙으로 복귀한다.

| | 1안 중앙 Dispatcher (Master–Worker) | 2안 Blackboard |
|---|---|---|
| Component | Tier Descriptors · State Repository(snapshot 50 ms + 자기 dispatch 기록) · Candidate Generator · Cost Model · Resource Selector · Dispatcher | Tier Descriptors · Task Board · Tier Admission Agents · HBM Budget Admission · Poster |
| Connector | scheduler → Dispatcher `assign()`, Dispatcher → Worker `plan(cmd)`, Worker → Dispatcher telemetry | Poster → Board `publish(Task)`, Agent ↔ Board `subscribe/claim/write facts` |
| 결정 | 중앙 1곳. 기존 Cost에 **λ_HBM 항**(`c·u²·Δ/cap`, c = 1.0)을 더해 argmin. 직렬(결정 비용 `t_ref·k/64`) | 분산. Agent가 **라이브 로컬 측정**으로 claim, 추정기 없음. 게시→claim 지연 `t_bb`(병렬) |
| 정보 | snapshot(지연) + estimator(오차 ε) | live 측정(지연 없음), 전역 목적 없음 |

**1안의 보정 (loop 1)**: Dispatcher가 snapshot만 보면 한 갱신 구간의 요청이 같은 Tier로 몰린다(herding). Dispatcher가 자기 dispatch를 기록하는 `PendingLedger`를 Resource State에 추가했다.

**2안의 규칙 집합 v2 (loop 2)**: (1) 모든 Tier agent(`hbf` 포함)는 노드 수준 예상 TPOT headroom(`iter_time(live + 모든 claim backlog + 이 Task) ≤ θ·SLO_TPOT`)으로 admit, (2) History가 있는 Task는 HBM staging(budget grant)까지만 시도하고 offload 사다리는 새 KV에만 적용한다. 상수 θ = 0.8, ρ_hi = 0.85, t_bb = 0.5 ms는 사전 등록값이며 바꾸지 않았다.

### 2.4 구조 비교 (평가 전 예상과 평가 후 관찰)
| | 1안 | 2안 |
|---|---|---|
| 장점 | 전역 Cost로 처리량, 지연, HBM을 함께 최적화. 정책 변경 지점이 Cost와 Selector에 모임 | live 측정이라 telemetry 지연에 둔감. 결정 비용 없음. 신규 Tier는 Agent 추가로 국소 확장 |
| 단점 | snapshot 지연과 추정 오차 의존. 단일 결정 지점 | 규칙 집합이 곧 정책이고 cost 신호가 없음. 게시→claim 홉과 재시도 비용 |

## 3. 평가

### 3.1 설정 (사전 등록: `../Evaluation/DP2/arch-styles-plan.md`, `qa4-preregistration-arch.md`)
- 시스템: SYS-H100(HBM3, PCIe5), SYS-B200(HBM3e, PCIe5) 통합. 시나리오 16개 x 2 시스템 = 32쌍, 그중 comparison-valid 21, saturated 11, infeasible 0.
- 시나리오: Common 3(`n_cb_*`) + DP2 노드 내 13(HBM 상주 짧은 대화, History가 DRAM/SSD/HBF에 있는 대화, 128K 긴 컨텍스트 decode, decode 집중, 부하 급증, decode 단계 전환, stale telemetry, Dispatcher 장애 fallback 등). 정의는 `../Evaluation/DP2/benchmark.md` §11.
- 실행: seed 5개(11, 23, 37, 53, 71), 시나리오별 부하 grid, 5,320 run. iso-load로 QA2와 QA3를 비교.
- QA: Q1 Max SLO goodput(경계 0.97/1.30), Q2 TTFT와 TPOT의 P50/P95/P99 개선 배수 geomean(0.95/1.25), Q3 HBM KV 점유 비(절감 0.95/1.25, SLO 달성률이 Baseline-1pp 이상인 쌍만), Q4 변경 시나리오 4종 실제 구현(M1 module, M2 공수, M3 비용). 우선순위(제안) Q1 > Q3 > Q2 > Q4.

### 3.2 결과 (Baseline-GPU-local 대비)

| QA | Baseline | 1안 Dispatcher | 2안 Blackboard |
|---|---:|---|---|
| Q1 goodput (tok/s) | 1,075 | ★★ 1,155 (×1.07) | ★★ 1,081 (×1.00) |
| Q2 TTFT P99 · P50 (ms) | 3,529 · 327 | 1,995 (×0.57) · 283 (×0.87) | 4,053 (×1.15) · 313 (×0.96) |
| Q2 TPOT P99 · P50 (ms) | 14.5 · 8.3 | 19.5 (×1.34) · 8.6 (×1.03) | 15.1 (×1.05) · 8.4 (×1.00) |
| Q2 별 (개선 배수 geomean) | ×1.00 | ★★ ×1.11 | ★ ×0.95 |
| Q3 HBM 점유 (GiB) | 631 | ★★ 586 (×0.94) [20쌍] | ★★ 692 (×1.05) [14쌍] |
| Q4 module · MM · 비용(T1) | — | ★★★ 1.75 · 0.31 · $1.17 | ★★★ 1.25 · 0.22 · $0.96 |
| 별 합계 | | **9** | 8 |

쌍별 판정(comparison-valid 21쌍): 1안 Dispatcher는 승·무·패가 개선 쌍이 우세하나 패의 대부분이 TPOT 꼬리이고(SLO 이내), 2안은 3승 11무 7패.

### 3.3 왜 이렇게 나왔나
- **1안**: Cost에 HBM 기회비용이 있어 History가 큰 turn이나 decode가 몰린 노드에서 ScHBM으로 보낸다(Decode의 16.5%). 그래서 TTFT 꼬리와 HBM 점유를 얻고, Cost가 SLO 안의 TPOT 여유를 소비하므로 TPOT 꼬리가 커진다(P99 19.5 ms, SLO 50 ms 이내).
- **2안**: 규칙이 "HBM budget이 허용하면 HBM, 거절될 때만 offload"이고 board에 HBM 대 offload의 비용 차이를 볼 신호가 없다. 압박이 없으면 Baseline과 같은 결정을 하고(예: `n_dp2_long_ctx_decode_offload` H100에서 1안은 ScHBM 1,066 turn, 2안은 0), 압박이 있으면 admission margin(ρ_hi)이 요청을 큐에 잡아 TTFT 꼬리가 늘어난다. 같은 규칙을 중앙에서 돌린 참고 후보(Ref)가 비슷한 값(goodput ×0.99, TTFT P99 ×1.16)이므로 원인은 아키텍처보다 **규칙 집합**이다.
- **Q4**: 둘 다 ★★★. 시나리오별 변경 module 수(A / B): 신규 Tier 2/2, 신규 목적 항 1/1, 정책 교체 1/1, 신규 telemetry 신호 3/1. 신호 추가에서 B가 국소적이다(Agent 1곳). B의 목적 항 확장판(agent와 budget까지 반영)은 3 module.

### 3.4 민감도 (사전 등록값 주변, 6개 시나리오, SYS-H100, seed 3개)
- Cost 추정 오차 σ: 0 / 0.2 / 0.4 / 0.6에서 1안 goodput ×1.02 / ×1.01 / ×0.91 / ×0.75, TTFT P99 ×0.74 / ×0.72 / ×1.41 / ×2.14. **break-even은 σ 0.2와 0.4 사이**. 본 평가는 σ = 0으로 돌렸다.
- λ_HBM, t_ref, telemetry 주기(0.01~1 s)는 1안 결과를 거의 바꾸지 않는다(goodput ×1.01~×1.04).
- 2안은 θ에 둔감(0.6~1.0에서 동일)하고 ρ_hi에 민감하나(0.7에서 goodput ×0.85), 어느 값에서도 Baseline을 넘지 못한다.

### 3.5 Baseline-regression loop 이력 (`../Evaluation/DP2/results/iterations/loop-log.md` §3)
| 단계 | 내용 |
|---|---|
| Baseline control | Baseline-GPU-local을 Decode 항상 HBM으로 정의(초기 정의는 TPOT infeasible), grid 끝 peak 확장 |
| loop 1 (A, class P) | herding(decode_heavy 1,882 대 8,382)을 `PendingLedger`로 수정 → 9,102 |
| loop 2 (B, class P) | `hbf_hist` ×0.00, `dram_small_tool` ×0.72의 파국을 규칙 v2로 수정 → ×0.96, ×0.93 |
| loop 3 | 남은 B 퇴화는 cost 신호 부재라는 구조적 성질이라 판단, **중단**(최대 6회 전). 사용자가 되돌릴 수 있음 |
중단된 1, 2회차 부분 데이터는 `run1_aborted`, `run2_aborted`로 보존했고 평가에 쓰지 않았다.

### 3.6 사전 등록 가설의 결과
1. HBM 여유 시나리오에서 후보가 Baseline보다 나쁘지 않다 → 1안 대체로 성립, 2안은 일부 시나리오에서 0.93~0.98×.
2. 압박 시나리오에서 두 후보가 offload를 써서 Q1과 Q3가 좋아진다 → **1안만** 성립. 2안은 offload를 쓰지 않거나 큐 대기로 오히려 TTFT 꼬리가 늘었다.
3. 2안이 stale telemetry와 큰 ε에서 덜 나빠진다 → 부분 성립(B200 `n_dp2_stale_telemetry`에서 2안 ×1.36, H100에서는 패). ε 민감도는 1안이 크게 취약함을 확인.
4. Q4에서 A는 교차 관심사, B는 국소 확장이 유리 → 신호 추가만 B가 유리, 나머지는 같았다.
5. 장애 fallback에서 Baseline 수준 유지 → saturated로 판별력 없음.

## 4. 선택과 보완 설계

### 4.1 선택 (`tools/dp_selection.py`, 우선순위 proposal)
별 합계 1안 9, 2안 8로 **1안 Dispatcher** 선택, 우선순위를 뒤집어도 동일. 차이는 Q2의 별 하나다. 2안의 Q3 절감비 0.952는 ★★ 하한 0.95에 거의 붙어 있어 경계 의존적이나 선택은 같다. 단 **1안의 값은 σ = 0 전제**다.

### 4.2 보완 설계: Hybrid C (중앙 선택 + Tier 로컬 거부권) [Claude 제안, 미구현 [C]]
| 약점 (근거) | 택틱 | 상태 |
|---|---|---|
| TPOT 꼬리 P99 ×1.34 (snapshot 사이 부하를 Cost가 못 봄) | Tier Guard가 live 측정(노드 iteration 시간 + claim backlog)으로 거부하고 Dispatcher가 다음 후보 선택 | [C] |
| Cost 추정 오차 의존 (σ 0.4에서 ×0.91) | 오추정이 SLO를 넘기 전에 Guard가 최악 경계 역할 | [C] |
| 신호 추가 시 3 module | Tier 상태·한도를 Guard가 소유해 변경을 국소화 | [C] 가설 |

**왜 처음부터 C를 두지 않았나**: 혼합안은 이득이 Cost 모델에서 오는지 live 측정에서 오는지 분리할 수 없고, component와 인터페이스가 늘어 Q4에서 손해를 보는 것이 예상되므로 각 스타일의 장단을 먼저 측정해야 했다. 어떤 부분을 빌려 올지는 측정 후에 알 수 있었다(1안의 약점은 TPOT 꼬리와 추정 오차, 2안의 강점은 live 측정이고 약점은 cost 신호 부재). 그래서 C는 2안 전체가 아니라 admission 거부권만 빌린다. 이는 평가 후 정리한 이유이며 C의 효과는 검증되지 않았다.

## 5. 한계
- Evidence [B+C]: 같은 사람이 같은 simulator에서 구현한 proxy이고 vLLM 구현이 아니다. QA4의 공수와 비용은 가정 상수다.
- A와 B는 아키텍처와 규칙 집합이 함께 다르다. 2안의 결과는 "cost 신호 없는 Blackboard 규칙 집합"에 대한 것이며 cost 신호를 넣은 Blackboard 변형은 평가하지 않았다.
- 1안은 σ = 0에서 평가했고 오차 모델은 lognormal 한 종류다. QA3의 2안 값은 SLO 조건으로 7쌍이 제외된 14쌍 기준이다.
- 1안의 TPOT 꼬리 악화(×1.34)는 별점 geomean에서 TTFT 개선과 상쇄된다. TPOT 꼬리가 중요하면 그대로 쓸 수 없다.
- 노드 간 결정(DP4), 실제 trace, 실측 HW, endurance는 다루지 않았다. QA 우선순위는 제안 상태다.

## 6. 다음 단계
1. Hybrid C 구현 후 같은 benchmark로 Baseline-regression 평가.
2. board에 cost 신호를 넣은 Blackboard 변형 평가, 1안의 σ ≥ 0.4 대응.
3. QA 우선순위 확정, DP4(노드 간)로 확장.

## 7. 파일 지도
| 종류 | 경로 |
|---|---|
| 결과 문서 | `../Evaluation/DP2/results/2026-10-10_dp2-arch-styles.md` (생성기 `../Evaluation/tools/gen_dp2_arch_result.py`) |
| 사전 등록 | `../Evaluation/DP2/arch-styles-plan.md`, `qa4-preregistration-arch.md`, `benchmark.md` §11 |
| 반복 로그 | `../Evaluation/DP2/results/iterations/loop-log.md` §3 |
| 원자료 | `../Evaluation/DP2/results/data/arch/` |
| 코드 | `../Evaluation/DP2/sim/dp2sim/{nodeint,arch_dispatcher,arch_blackboard,scenarios_node}.py`, 실행 `sim/{node_control,qa_eval_node,sens_arch,qa4_arch,qa4_apply}.py` |
| 발표 | `../slides/dp2-arch-styles-dispatcher-vs-blackboard.pptx` (+ 설명 `.md`) |
