# DP2 Benchmark (DP2 맞춤형)

> 상태: **draft** (시나리오 정의만 있고 simulator 구현 전). 최종 결과 = **Common Benchmark (`../common-benchmark.md`) + 이 문서의 DP2 전용 benchmark**.
>
> 공통 시나리오 CB-1~CB-3은 `../common-benchmark.md` 2.1장에 정의되어 있어 여기서는 **DP2에서의 실현 방식**만 적는다. QA 정의는 [`qa-criteria-dp2.md`](qa-criteria-dp2.md), 평가 방법은 [`simulation-plan.md`](simulation-plan.md), 시스템은 [`../system-specs.md`](../system-specs.md).

# 1. 구성과 범위

> **범위:** DP2는 **Turn 단위로 Prefill 실행 위치(n_p)와 Decode 시작 위치(n_d)**를 정한다. Decode 실행 중 Tier 간 KV 이동은 DP1 소관이라 이 benchmark에서 평가하지 않는다. 노드 간 KV 전송은 idealized executor와 링크 모델로 반영한다.

시나리오의 단일 소스는 구현 후 `DP2/sim/scenarios.py`로 두고 아래 표는 생성한다(DP1 방식). 그 전까지는 이 표와 `sim/configs/scenario_params.json`(시작 파라미터, [`m0-spec.md`](m0-spec.md) §5.3)이 원천이며 이름 일치를 `sim/m0_check.py --verify`로 검사한다.

| Set | 수 | 목적 |
|---|---:|---|
| Common (CB-1~3) | 3 | 공통 QA1~QA3 별점, 회귀(no-harm) 확인 |
| DP2 Stress | 12 | trade-off / failure mode 관찰 (diagnostic). 이 중 2개는 후보 안전성 확인 |
| DP2 Dynamic | 4 | Baseline이 처음엔 SLO를 만족하다 runtime에 고정 규칙이 stale해지는 패턴 |
| Scalability sweep | 노드·Tier·worker 격자 | QA5 |
| QA4 change scenarios | 4 | QA4 (module · 공수 · 에이전트 비용) |

# 2. Common Benchmark 실현

| 항목 | DP2 실현 |
|---|---|
| Serving 구조 | P 노드 + D 노드 (llm-d + vLLM worker 가정), 노드당 TP8 인스턴스 1개, P:D = 1:1 |
| 고정 파라미터 | Llama-3.1-70B BF16, 입력 8K, 출력 256, 동시 32 요청, SLO TTFT P99 ≤ 2 s / TPOT P99 ≤ 50 ms, 단일 턴(History 없음) |
| CB-1 `cb_kv_8k_b32` | KV만. **D 노드 HBM 용량 ×0.12**(DP1 CB-1과 같은 비율, KV가 D에 상주하므로 D에 적용) |
| CB-2 `cb_kv_8k_b32_ramp` | CB-1과 같은 KV, D 노드 HBM 압박이 시간에 따라 점진 증가 (DP1 CB-2와 같은 ramp) |
| CB-3 `cb_mixed_8k_b32` | KV + LoRA + MoE + Agent/Tool 혼합. KV 외 데이터는 DP2 대상이 아니므로 고정 배치, KV 관련 Prefill/Decode 위치만 DP2가 결정 |
| sweep | 동시성/요청률 sweep. grid는 Baseline과 후보에 동일, peak가 grid 끝이면 확장 |
| 반복 | seed 11/23/37/53/71 이상, 95% CI, CV |

공통 시나리오는 단일 턴이라 DP2 Planner의 이득이 나오지 않는 것이 정상이다(saturated 예상). 이 결과는 **Planner가 Baseline보다 나빠지지 않음**과 **결정 오버헤드**를 확인하는 용도다.

# 3. Common Reference Baseline (T_ref)

| 항목 | 내용 |
|---|---|
| Baseline 구조 | **Baseline-PD-fixed**: 모든 Turn의 Prefill은 P 노드, Decode는 D 노드(역할 고정, KV Tier 미고려). History는 D에 있으므로 P가 필요한 만큼 D→P 전송하고 결과 KV는 P→D 전송 |
| Tier 배치 | DP1 Baseline-static(공통 initial placement 후 migration 없음)을 모든 후보와 공유. DP1 효과와 DP2 효과를 분리 |
| 사용 SYS | SYS-H100, SYS-B200 (후보와 같은 노드 구성) |
| prefix reuse | 공통 규칙대로 Baseline에서 통제. 켠 결과는 별도 행으로 분리 |
| T_ref | TBD (구현 후 측정, [B+C]) |
| SLO 충족 여부 | 못 맞추는 시나리오는 `infeasible`로 flag, 조용히 제외하지 않음 |

별점 산출에 쓰이지 않는 **참고 행**을 함께 보고한다: (1) D-local-always 휴리스틱(항상 KV가 있는 D에서 Prefill), (2) Oracle(실행 시점 최적 선택, 상한). 이는 "단순 휴리스틱과 무엇이 다른가"에 답하기 위한 것이며 Common Reference Baseline을 바꾸지 않는다.

# 4. DP2 Stress Benchmark (12)

멀티턴 시나리오의 `hist`는 Turn 시작 시점의 History 길이와 그 KV가 놓인 Tier(Tier 분포는 모든 후보에 같은 외부 배치로 주어진다).

| 시나리오 | 무엇인가 | 드러내는 As-Is 약점 | 핵심 파라미터 |
|---|---|---|---|
| `dp2_turn_hbm_small_tool` | 멀티턴 Agent, History가 D의 HBM, Tool 결과 작음 | 작은 증분에도 History 전체를 P로 왕복 | hist 32K, tool 0.5K, tier HBM, 16 sessions |
| `dp2_turn_dram_small_tool` | History가 D의 DRAM에 내려간 상태에서 재개 | Tier별 승격·전송 비용 차이를 모름 | hist 64K, tool 0.5K, tier DRAM |
| `dp2_turn_hbf_hist` | History가 HBF(GPU 직접 읽기)에 있는 재개 | 직접 읽을 수 있는 KV도 P로 전송 | hist 128K, tool 2K, tier HBF |
| `dp2_turn_ssd_hist` | History가 SSD-PIM에 있는 재개 (대조군) | Tier BW가 병목일 때의 전송 낭비 | hist 64K, tool 0.5K, tier SSD-PIM |
| `dp2_tool_large_result` | Tool 결과가 큰 턴 (대조군, P가 최적 예상) | — (Planner가 Baseline과 같아야 함) | hist 16K HBM, tool 16K |
| `dp2_prefill_burst_p_saturated` | Prefill burst로 P 포화, D는 여유 | P 큐 대기로 TTFT 악화, D 유휴 | arrival burst, prompt 8~16K, P:D 1:1 |
| `dp2_decode_heavy_p_idle` | 긴 출력 위주로 D 포화, P 유휴 | D 병목, P GPU idle | out 2K, P:D 1:1 |
| `dp2_long_ctx_decode_offload` | 128K~256K History 세션 재개, D의 HBM 용량 부족 | HBM 초과분을 DRAM에서 swap-in 하며 TTFT/TPOT 악화 | hist 128~256K, tool 2K, D hbm x0.3, ScHBM 오프로드 on |
| `dp2_session_size_skew` | 소수 256K 대형 세션 + 다수 8K 채팅 | 대형 세션이 한 D 노드에 쏠림 | heavy-tail, N_D=4 |
| `dp2_internode_link_contention` | P↔D 링크를 다른 트래픽과 공유 (BW 25%) | 왕복 전송 지연이 TTFT에 직접 반영 | link x0.25 (DP1 host-link 경합과 같은 비율) |
| `dp2_stale_telemetry` | Telemetry 갱신 지연 (10 ms~1 s sweep) | — (후보 견고성: C2 plan age 포함) | interval sweep |
| `dp2_planner_fault_fallback` | Planner 중단·Cost 오류 주입 | — (후보 안전성: Baseline 수준 복귀 확인) | fault at T/2, fallback = Baseline |

# 5. DP2 Dynamic Benchmark (4)

DP1 Dynamic과 같은 원칙: Baseline이 feasible한 초기 상태에서 시작하고 runtime에 workload가 바뀌는 패턴만 쓴다. Baseline만 돌려 설계하고 후보 실행 전에 고정한다. 실패 모드를 알고 설계했으므로 이득은 "고정 규칙이 stale해지는 경우"에 한정해 읽는다.

| 시나리오 | 무엇인가 | 드러내는 As-Is 약점 | 핵심 파라미터 |
|---|---|---|---|
| `dyn_turn_demotion_wave` | 세션이 idle 되며 History가 하위 Tier로 내려간 뒤 재개 | 처음엔 HBM 상주라 문제없다가 재개 때 Tier 변화를 반영 못함 | idle 30~120 s, 외부 demotion schedule(모든 후보 동일) |
| `dyn_load_ramp_burst` | 도착률이 0.4→1.1 x 포화로 상승 + burst | 고정 P/D 용량이 부하 변화를 못 따라감. C1/C2 plan age 차이 | ramp + burst on/off |
| `dyn_p_node_degrade` | 중간에 P 노드 처리량·링크 저하 | 저하된 P를 계속 사용 | P 처리량 x0.5 at T/2 |
| `dyn_decode_phase_shift` | 출력 길이가 256에서 2K로 전환 (채팅→추론) | Decode 풀 병목, P 유휴 | out 256→2K phase |

# 6. Scalability sweep (QA5)

| 축 | 값 |
|---|---|
| 노드 수 (P+D) | 2, 4, 8, 16, 32, 64 (노드당 offered load 동일) |
| 노드당 Tier 수 | 1, 2, 4 (후보 수 `\|N_p\|×\|N_d\|×Tier` 증가) |
| planner worker (C2) | 1, 4, 16 |
| top-k pruning | off / on (품질 regret 영향 보고) |

# 7. QA4 변경 시나리오

DP1의 4종(신규 memory / data type / policy / event)에 대응한다. 시뮬레이터 복사본에 실제 구현해 module/LOC를 측정하며, 공식·별 경계는 **측정 전에 사전 등록**한다(`qa4-preregistration.md`, 작성 예정).

| 변경 | 내용 |
|---|---|
| 신규 Tier | Pluggable Memory Tier I/F로 새 Tier(예: 새 CXL pool) 추가 |
| 신규 Cost 항 | 새 비용 항(예: 전력) 추가 |
| 정책 교체 | Selector 교체 (argmin → SLO 제약형 선택) 또는 Cost Model 교체 |
| 신규 telemetry event | 새 Resource State 신호 추가 |

# 8. Benchmark-fit 분류

- **comparison-valid / infeasible / saturated** 정의는 `.claude/skills/evaluation/SKILL.md` §4를 따른다.
- 분류는 SYS별로, **결과를 보기 전** Baseline만 돌린 feasibility control로 한다.
- 대조군(CB-1~3, `dp2_tool_large_result`, `dp2_turn_ssd_hist`)은 `saturated`가 예상되며 이득 근거로 쓰지 않는다. 집계에는 포함한다.

# 9. 설계 원칙 점검 (SKILL §5 금지 사항 대비)

- Baseline이 infeasible한 시나리오를 만들고 승리를 주장하지 않는다. `dp2_long_ctx_decode_offload`는 Baseline이 SLO를 못 맞출 수 있어 feasibility control 결과에 따라 flag한다.
- 후보에 유리한 시나리오만 두지 않는다. 대조군을 포함했고 지는 시나리오도 유지한다.
- 시나리오별 policy 상수 tuning을 하지 않는다. Cost Model 오차 sweep(ε 0/0.2/0.4/0.6)은 `simulation-plan.md`에 둔다.

# 10. 아직 모델링하지 못하는 것

- DP2 simulator는 구현 전이다 (`simulation-plan.md` §4 참조).
- prefix cache 공유, chunked prefill의 세부 스케줄, NIXL 프로토콜 오버헤드, GPU 내 Prefill/Decode 간섭의 정밀 모델(단순 간섭 계수로 근사 예정)은 미반영이다.
