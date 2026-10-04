# DP2 Simulation Plan

> 상태: **draft** (구현 전). DP1 평가 환경(`../DP1/simulation-plan.md`, `../DP1/sim/`)을 재사용하고 DP2에 필요한 부분만 추가한다. 규칙은 `.claude/skills/evaluation/SKILL.md`를 따른다.

# 1. 목적과 평가 질문

DP2 후보(C1 스케줄링 시점 결정, C2 사전 계획 결정)를 Common Reference Baseline(Baseline-PD-fixed)과 비교한다.

| 질문 | 대응 |
|---|---|
| Q-A. 고정 P/D 규칙 대비 Tier 인지 (n_p, n_d) 결정이 이득인가 | Stress/Dynamic 시나리오, QA1~QA3 |
| Q-B. 결정 시점(C1/C2)에 따라 어떤 조건에서 어느 쪽이 유리한가 | `dyn_load_ramp_burst`, `dp2_stale_telemetry`, Scalability sweep |
| Q-C. 새 Tier·Cost 항 추가 시 변경이 작은가 | QA4 변경 시나리오 |

# 2. 구조 정의

- **결정 대상**: `ExecutionPlan = (n_p, n_d)`, n은 `(node, {GPU/HBM, GPU/HBF, ScHBM·CXL-PNM attention 오프로드})`.
- **Cost**: `Cost(n_p,n_d) = Tmove(KV→n_p) + Tprefill(n_p) + Tqueue/간섭(n_p) + Tmove(KV n_p→n_d) + ΔTPOT(n_d)`, n_d의 KV 용량·SLO feasible 제약. **C1과 C2는 같은 Cost Model을 쓴다**(차이는 결정 시점과 plan lifecycle).
- **C1**: scheduler가 request와 token budget을 확정한 시점에 최신 Resource State로 결정한다.
- **C2**: waiting 중 Planner가 비동기로 plan을 만들어 Plan Cache에 두고, dispatch 직전 Late Validation(자원 health, 용량, queue guardrail, plan age, 경로)을 한 뒤 사용한다. 실패 시 backup 후보 또는 re-plan.
- 자세한 구조는 `doc-mk/DP2/dp2-prefill-decode-execution-planning-decision-timing.md`.

# 3. 평가 환경

| 항목 | 내용 |
|---|---|
| 시스템 | **SYS-H100, SYS-B200 통합** (DP1과 동일, SKILL H19). 노드 = 8-GPU HGX, 6종 메모리(HBM, ScHBM, CXL-PNM, DRAM, HBF, SSD-PIM). 값은 `../system-specs.md` |
| 모델 / SLO | Llama-3.1-70B BF16, TTFT P99 ≤ 2 s, TPOT P99 ≤ 50 ms (공통 고정) |
| 토폴로지 | P 노드 + D 노드, 노드당 TP8 인스턴스 1개 (llm-d + vLLM worker 가정, 공통 criteria §8). 기본 1P+1D, 확장성은 최대 64 노드 |
| **노드 간 링크 (신규)** | RDMA 기본 **50 GB/s (ASSUMED)**. sweep 12.5 / 50 / 200 / 400 GB/s. 값 출처가 없으므로 **새 profile로 추가**하고 provenance를 기록한다 (SKILL H10). `system-specs.md`의 기존 profile은 수정하지 않는다 |
| Tier 배치 | DP1 **Baseline-static**(공통 initial placement 후 migration 없음)을 모든 후보가 공유한다. DP1 효과를 빼고 DP2만 본다. DP1-C1 on은 민감도로 한 번 더 돌린다 |
| 통계 | seed 11/23/37/53/71 이상, load sweep(x0.5 / 1.0 / 1.5 / 2.0 등 grid 끝 확인), 95% CI, CV |
| Evidence | simulation 출력은 [B+C]. 링크·결정 비용 가정은 ASSUMED로 표기 |

# 4. Simulator 확장 필요 항목

DP1 simulator(`DP1/sim/`)는 1초 time-step의 데이터 객체 모델이고 요청 큐가 없으며, 단일 노드 가정이라 노드 간 전송을 다루지 않는다. 그래서 C1/C2의 차이(결정 지연, plan age, stale telemetry, 큐)를 표현하지 못한다.

**결론: Turn 단위 이산 사건 simulator를 새로 만들고, DP1의 `model.py`·`configs/`·통계 규칙을 재사용한다. DP1 코드는 수정하지 않는다.** 모듈 구성, 모델링 요구사항(F1~F13), 시나리오별 필요 기능, 단계(M0~M6)와 종료 기준, 테스트 계획, 소유자 결정 사항은 [`sim-extension-scope.md`](sim-extension-scope.md)에 둔다.

# 5. 민감도와 오차

| 축 | 값 | 이유 |
|---|---|---|
| 노드 간 링크 BW | 12.5 / 50 / 200 / 400 GB/s | 결정이 이 값에 민감 (D 로컬 대 P 경로 격차) |
| Telemetry 갱신 주기 | 10 ms ~ 1 s | stale plan 영향 |
| 결정 비용 (결정 1건, 후보 64개 기준, 후보 수에 선형) | 0.1 / 1 / 10 ms | C1/C2 결론이 이 가정에 의존 |
| Cost Model 오차 ε (lognormal σ) | 0 / 0.2 / 0.4 / 0.6 | Planner가 estimator에 의존 (SKILL H17). 정책 상수는 재조정하지 않는다 |
| 노드 수, Tier 수, planner worker | `benchmark.md` §6 | QA5 |
| DP1-C1 on/off | — | DP1 상호작용 |

# 6. 절차

1. SKILL §3 체크리스트를 수행하고 simulator test suite를 통과시킨다.
2. `dp2_controls()`로 Baseline만 돌려 시나리오별 fit label을 **후보 실행 전에** 고정한다.
3. Common + DP2 전용 benchmark를 SYS-H100/B200에서 실행한다 (seed ≥ 5, load sweep).
4. raw 출력을 `DP2/results/data/`에 저장하고 `result-template.md` 형식으로 결과 문서를 쓴다. 숫자는 코드 출력으로만 옮긴다.
5. Baseline보다 나쁜 후보·시나리오는 Baseline-regression loop(SKILL §5)를 따르고 지는 시나리오를 숨기지 않는다. 대조군에서 후보가 Baseline보다 나쁘면 P(정책 결함) 또는 M(cost model gap)으로 진단한다.

# 7. 열린 결정 사항

- simulator 확장 범위와 일정, Planner 프로토타입으로 결정 비용을 [A] 측정할지.
- 노드 간 링크 profile의 근거(NIC 구성, 실측 또는 문헌).
- QA3 임시 정의와 QA5 threshold 확정 (`qa-criteria-dp2.md`).
- SSD Tier의 History에 대한 "재계산" 후보를 ExecutionPlan 후보 집합에 넣을지.
- `qa_priority.json`(선택 규칙 우선순위) 확정.
