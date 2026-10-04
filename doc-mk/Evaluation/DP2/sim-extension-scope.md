# DP2 Simulator 확장 범위

> 상태: **draft** (소유자 결정 전). 근거는 `Evaluation/DP1/sim/` 코드(커밋 e83c92e 기준)와 `benchmark.md`, `qa-criteria-dp2.md`다.
> 규칙은 `.claude/skills/evaluation/SKILL.md`를 따른다 (H1: 산출물은 `doc-mk/Evaluation/DP2/` 안에, H6: simulation 출력은 [B+C]).

# 1. 결론

- **DP1 simulator를 확장하는 것이 아니라, 요청(Turn) 단위 이산 사건(discrete-event) simulator를 새로 만들고 DP1의 물리 모델·설정·통계 규칙을 재사용한다.**
- 이유는 DP1 simulator의 구조가 DP2의 핵심 비교(C1 대 C2)를 표현하지 못하기 때문이다 (§2).
- DP1 코드는 수정하지 않는다 (DP1 결과 재현성, SKILL H7/H9).
- 신규 코드는 `doc-mk/Evaluation/DP2/sim/`에 두고, DP1의 flat module 이름(`model`, `scenarios`, `simulator`, `policies`)과 충돌하지 않도록 패키지 `dp2sim`으로 만든다.

# 2. DP1 simulator에서 확인한 사실과 DP2에 미치는 영향

| 항목 | DP1 현재 | DP2에 미치는 영향 |
|---|---|---|
| 시간 모델 | `for t in range(sc.horizon_s)` — **1초 time-step** (`simulator.py` `run_sim`) | 결정 지연(µs~ms), plan age, Telemetry 지연을 표현할 수 없다 |
| 단위 | **데이터 객체**(`DataObject`: 도착, 수명, 접근 rate) 중심. TTFT/TPOT은 객체의 배치 Tier로부터 `ttft_s()`/`tpot_s()`가 계산 | 요청·Turn·세션 단위 이벤트가 없다 |
| 큐/포화 | **요청 큐와 포화 모델이 없다** (SKILL §4: "simulator에 queueing/saturation 모델이 없어") | C2의 stale plan(대기 중 상태 변화), herding, 노드 큐 대기를 표현할 수 없다 |
| 토폴로지 | 8-GPU **단일 scale-up domain**. `clusters.json`에 `domain_interconnect`(NVLink)만 있고 **노드 간 링크가 없다** | P/D 노드 간 KV 전송과 경합을 표현할 수 없다 |
| 세션 | 멀티턴·Tool 대기 개념 없음 | History KV, Turn 재개 시점의 Tier 상태가 없다 |
| 정책 입력 | 1초 단위 `Telemetry` snapshot, `set_model_error(eps, seed)`로 오차 sweep, 이동의 `link_interference` | 오차 sweep과 링크 간섭의 **아이디어**는 재사용 가능 |
| 물리 모델 | `model.py`: `SystemSpec.prefill_s`, `decode_step_s`, `offloaded_attention_s`, `gpu_non_attention_decode_s`, `MemorySpec`, `ModelSpec`, `configs/*.json`(6종 메모리, H100/B200) | **그대로 재사용** |
| 통계/QA | `qa_eval.py`(별점, `mean_ci`, `paired`, fit label, `qa_table`), `merge_systems.py`, `epsilon_sweep.py`, `sensitivity.py`, `loop_run.py` | 규칙·절차 재사용, DP2 지표용 확장 |
| 규모 | `simulator.py` 783줄, `policies.py` 940줄, `qa_eval.py` 428줄, `model.py` 268줄, `scenarios.py` 362줄, `test_sim.py` 513줄 (전체 약 5,000줄) | 규모 감 참고용 |

# 3. 접근 대안

| 대안 | 내용 | 장점 | 한계 | 판단 |
|---|---|---|---|---|
| A | DP1 time-step 루프에 P/D 노드와 링크만 추가 (유체 모델) | 재사용 많음, 구현 작음 | 큐·plan age·결정 지연이 없어 **C1/C2를 구분할 수 없다**. Q-B(결정 시점 비교)에 답하지 못함 | 비권장 |
| **B** | **Turn 단위 이산 사건 simulator 신규 + DP1 모델·설정·통계 규칙 재사용** | C1/C2, stale plan, 큐, 링크 경합을 직접 표현. DP1 평가 체계와 일관 | 신규 구현량이 큼, 검증 필요 | **권고** |
| C | 실제 llm-d + vLLM 프로토타입 | 실측 [A] | HBF·ScHBM·CXL-PNM이 없어 이기종 평가 불가, 구축 비용 큼 | 보정(calibration)용으로만 |

권고는 **B를 주 수단으로 하고, C는 결정 비용·전송·Prefill/Decode 시간을 보정하는 소규모 측정으로 한정**하는 것이다.

# 4. 모듈 구성

```text
doc-mk/Evaluation/DP2/sim/
  dp2sim/
    engine.py         # 이벤트 큐, 시뮬레이션 시계, seed 관리
    topology.py       # 노드(P/D 역할), 노드 내 자원, 노드 간 링크
    link.py           # 링크 대역폭 공유·경합
    node.py           # 노드 큐, continuous batching, Prefill–Decode 간섭, KV 용량 회계
    kvstore.py        # 세션별 KV 위치(노드, Tier), 외부 배치/demotion schedule
    workload.py       # 세션·Turn 생성기 (open/closed loop)
    execmodel.py      # 실제 실행 비용(ground truth) — DP1 model.py 호출
    estimator.py      # Planner용 추정 비용 + 오차 ε
    telemetry.py      # Resource State snapshot (갱신 주기, 지연, 손실)
    decision_cost.py  # 결정 비용 모델 (후보당 비용, worker, critical path 여부)
    planner/
      candidates.py cost_eval.py selector.py router.py fallback.py
      c1.py                      # 스케줄링 시점 결정
      c2.py plan_cache.py validator.py replanner.py   # 사전 계획
    policies_ref.py   # Baseline-PD-fixed, D-local-always, Oracle
    scenarios.py      # dp2_* 정의 (benchmark.md의 단일 소스, brief 포함)
    metrics.py        # 요청 로그 → QA 지표, 진단 지표
  qa_eval.py  merge_systems.py  epsilon_sweep.py  sensitivity.py  test_sim.py
  configs/
    internode_links.json      # 신규 profile (ASSUMED, provenance 기록)
    workload_defaults.json
```

| 구분 | DP1에서 가져오는 것 | 새로 만드는 것 |
|---|---|---|
| 재사용 (read-only) | `model.py`, `configs/*.json` | — |
| 규칙 재사용 | `qa_eval.py`의 통계 규칙(fit label, paired verdict, 95% CI), `merge_systems`, `epsilon_sweep`, `sensitivity`의 절차 | 위 모듈을 DP2 지표용으로 별도 구현 |
| 신규 | — | 위 목록의 나머지 전부 |

# 5. 모델링 요구사항

| ID | 기능 | 요구 | 근거 | 미반영 |
|---|---|---|---|---|
| F1 | 요청 라이프사이클 | arrival → 결정(C1: scheduler 시점, C2: waiting 중 plan) → History 전송 → Prefill → 결과 KV 전달 → Decode step들 → 완료. 각 단계가 이벤트 | 전 시나리오 | preemption, recompute |
| F2 | 노드 모델 | 노드당 TP8 인스턴스 1개. 큐, continuous batching(최대 batch 파라미터), iteration 시간 = Decode step + Prefill chunk의 합에 **간섭 계수 κ** 적용 | `prefill_burst`, `decode_heavy`, C2 stale | chunked prefill 세부, TP 병렬 효율 |
| F3 | KV/Tier 회계 | 노드·Tier별 용량(HBM은 weight 제외), 세션 KV 점유, 승격 시 다른 세션 eviction 비용. 압박은 DP1 `effective_capacity_mult` 방식(HBM x0.12 등) | CB, `turn_dram`, `long_ctx_decode_offload` | HBF endurance, write amp |
| F4 | 링크 모델 | 활성 전송 수에 따른 대역폭 공정 분할, 전송 병목 = min(Tier BW, 링크 BW, 대상 BW)의 파이프라인. 전송이 Tier 서빙 BW를 줄이는 간섭(DP1 `link_interference`와 같은 원리) | `link_contention`, 사례 A | 프로토콜 오버헤드 |
| F5 | 멀티턴 세션 | History 길이·Tier, Tool 결과 크기, Tool 대기 시간, 외부 demotion schedule | `turn_*`, `dyn_turn_demotion_wave` | prefix cache 공유 |
| F6 | Decode 모델 | n_d = (node, Tier)에서 시작. step 시간은 `decode_step_s(context, batch, tier)`로, context가 늘며 변화. **Decode 중 재결정과 Tier 이동은 없음(DP1 소관)** | 사례 B, `long_ctx_decode_offload` | — |
| F7 | Planner | C1/C2가 **같은 Cost Model**을 사용. C1은 결정 시간이 critical path에 포함(해당 요청 지연, 선택적으로 step 시간 증가). C2는 background worker, Plan Cache, plan age, Late Validation, backup, re-plan | Q-B 전체 | — |
| F8 | Estimator 대 실제 분리 | Planner는 estimator(오차 ε, stale 상태)를 쓰고 실행은 `execmodel`로 계산. regret은 Oracle(같은 시점의 ground truth 상태)과 비교 | Decision Quality 진단 | — |
| F9 | Telemetry와 결정 비용 | 갱신 주기, 지연, 손실. 후보당 결정 비용 c, worker 수 | `stale_telemetry`, Scalability | c는 가정 |
| F10 | 장애·변화 주입 | Planner 중단, Cost 오류, 노드 처리량·링크 저하(시점 지정) | `planner_fault_fallback`, `dyn_p_node_degrade` | — |
| F11 | 부하 모델 | open loop(도착률 sweep, Poisson·on/off burst·ramp·heavy-tail), closed loop(CB는 동시 32 요청 고정) | CB, `dyn_load_ramp_burst` | — |
| F12 | 메트릭 | 요청 로그(도착, 결정, 대기, 전송, TTFT 분해 5항, TPOT 샘플, 노드·Tier, 이동 bytes), 노드별 busy/idle, 링크 사용률, 결정 지연, regret, plan age, re-plan 수 | QA1~QA5, 진단 | — |
| F13 | 재현성 | 같은 `(scenario, seed, load)`에서 모든 후보가 **같은 trace**를 본다 (DP1과 동일) | SKILL H7 | — |

# 6. 시나리오별 필요 기능

| 시나리오 | F1 | F2 | F3 | F4 | F5 | F6 | F7 | F9 | F10 | F11 | 실행 가능 단계 |
|---|---|---|---|---|---|---|---|---|---|---|---|
| CB-1~3 | ✓ | ✓ | ✓ | ✓ | | ✓ | (회귀) | | | closed | M1 |
| `dp2_turn_hbm_small_tool` / `dram` / `hbf` / `ssd` | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | | | open | M2 |
| `dp2_tool_large_result` | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | | | open | M2 |
| `dp2_internode_link_contention` | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | | | open | M2 |
| `dp2_prefill_burst_p_saturated` | ✓ | ✓ | | ✓ | ✓ | ✓ | ✓ | ✓ | | burst | M3 |
| `dp2_decode_heavy_p_idle` | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | | | open | M2 |
| `dp2_long_ctx_decode_offload` | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | | | open | M2 |
| `dp2_session_size_skew` | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | | heavy-tail | M3 |
| `dp2_stale_telemetry` | ✓ | ✓ | | ✓ | ✓ | ✓ | ✓ | ✓ | | open | M3 |
| `dp2_planner_fault_fallback` | ✓ | ✓ | | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | open | M3 |
| `dyn_*` 4종 | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ramp/shift | M3 |
| Scalability sweep | ✓ | ✓ | | ✓ | ✓ | ✓ | ✓ | ✓ | | open | M4 |
| QA4 변경 시나리오 | 코드 변경 측정 (실행 아님) | | | | | | | | | | M5 |

# 7. 단계와 종료 기준

| 단계 | 내용 | 종료 기준 |
|---|---|---|
| **M0** 사양 고정 | 본 문서, 링크 profile, 파라미터 기본값(κ, batching), `qa-criteria-dp2.md` 사전 등록 | 소유자 확정 (§10), 모든 가정에 ASSUMED 표기 |
| **M1** 코어 | engine, topology, link, node, kvstore, execmodel, 단일 턴 workload(closed loop), Baseline-PD-fixed, metrics | CB-1~3 실행. 단건 경로가 rationale §2.2·§2.3의 이론값(약 0.39/0.31/1.23 s, 2.4/9.8/65/164 ms)을 허용 오차 내 재현. 결정론 테스트 통과. Baseline의 SLO 충족 여부(fit label)를 SYS별로 확정 |
| **M2** 멀티턴과 C1 | 멀티턴 workload, estimator, D-local-always, Oracle, C1 | `turn_*`, `tool_large_result`, `link_contention`, `decode_heavy`, `long_ctx_decode_offload`. **Planner를 Baseline 규칙으로 설정하면 Baseline과 정확히 일치** (동등성 테스트) |
| **M3** C2와 동적 | Telemetry, decision cost, C2(Plan Cache, validator, re-plan), 장애 주입 | `dyn_*` 4종, `stale_telemetry`, `fault_fallback`, `prefill_burst`, `session_size_skew`. **결정 비용 0과 staleness 0에서 C2 = C1** (분리 테스트) |
| **M4** 확장성 | 64 노드, planner worker, top-k pruning | QA5(η, 결정 지연), 시뮬레이터 자체 실행 시간 확인 |
| **M5** 변경 시나리오 | 4종 구현과 module/LOC 측정 | `qa4-preregistration.md`를 측정 **전**에 작성 |
| **M6** 보정·검증·결과 | 실측 가능한 부분 보정, 민감도 sweep, 결과 문서 | `result-template.md` 7개 섹션, seed ≥ 5, 명령·revision 기록 |

# 8. 테스트 계획 (`test_sim.py`)

DP1의 테스트 패턴(결정론, 같은 trace, 추정=시뮬레이션, 단조성, 동등성)을 따른다.

- **결정론**: 같은 seed와 명령이면 같은 숫자.
- **같은 trace**: 후보들이 같은 `(scenario, seed, load)` trace를 본다.
- **단건 이론값**: 단일 요청의 이동·읽기 시간이 계산식과 일치 (rationale §2 표).
- **Baseline 동등성**: Planner가 고정 규칙을 선택하도록 설정하면 Baseline과 같다.
- **C1/C2 분리**: 결정 비용 0, Telemetry 지연 0, plan age 0이면 C2가 C1과 같은 plan을 낸다 (결정 시점 효과만 분리하는 근거).
- **추정 = 실행**: ε = 0이고 상태가 신선하면 estimator가 실행 비용과 일치 (DP1 `test_estimator_matches_simulator_cost` 대응).
- **단조성**: 링크 BW 증가 시 P 경로 TTFT 감소, Tier BW 증가 시 TPOT 감소.
- **보존 법칙**: 전송된 bytes가 보존되고 KV 용량 초과를 허용하지 않는다. Planner가 용량 infeasible한 n_d를 고르지 않는다.
- **저부하 큐 점검**: 단일 노드 저부하에서 M/D/1 해석해와 대기 시간이 일치.
- **통계 규칙 동등성**: DP2로 옮긴 fit label·paired verdict 함수가 DP1 함수와 공유 fixture에서 같은 결과.

# 9. DP1 자산 재사용 방식

| 항목 | 권고 | 이유 |
|---|---|---|
| `model.py`, `configs/` | **read-only import**, 사용한 git revision을 결과에 기록 | 물리 모델의 단일 소스 유지. 값 수정은 새 profile로만(SKILL H10) |
| `qa_eval.py`의 통계 규칙 | DP2에 **복사**하고 동등성 테스트 추가 | `qa_eval.py`가 DP1 `scenarios`/`simulator`에 결합되어 있고, DP1 코드를 건드리면 재현성이 흔들림 |
| 모듈 이름 | `dp2sim` 패키지 | DP1이 flat 이름(`model`, `scenarios` 등)을 쓰므로 충돌 방지 |
| 설정 | `systems.json`을 수정하지 않고 `configs/internode_links.json` 추가 | SKILL H10 |

# 10. 위험과 가정

- **Prefill–Decode 간섭 계수 κ**: 검증된 값이 없다. sweep하고 가정으로 표기한다.
- **결정 비용**: C1/C2 결론이 후보당 비용(0.1/1/10 ms)에 의존한다. 실제 Planner 프로토타입의 [A] 측정이 없으면 민감도로만 결론을 낸다.
- **노드 간 링크**: 50 GB/s는 ASSUMED, sweep 12.5~400 GB/s.
- **미반영**: chunked prefill 세부, prefix cache 공유, NIXL 프로토콜 오버헤드, preemption·recompute, TP 병렬 효율, HBF endurance.
- **실행 시간**: 64 노드 × 세션 × Turn 이벤트 수 × seed 5 × load sweep × 2 SYS × 시나리오 수로 늘어난다. M4에서 simulator 자체 실행 시간을 측정하고 필요하면 이벤트 수를 줄이는 근사를 도입한다.
- **DP1 상호작용**: 주 결과는 DP1 Baseline-static을 고정, DP1-C1 on은 M6 민감도.

# 11. 소유자 결정이 필요한 것

1. 접근 B(이산 사건 simulator 신규) 승인과 `doc-mk/Evaluation/DP2/sim/` 위치.
2. DP1 자산 재사용 방식(§9)과 DP1 코드 비수정 원칙.
3. 노드 간 링크 profile과 값의 근거.
4. κ, continuous batching 파라미터의 기본값과 근거.
5. CB의 동시성 모델(closed loop 동시 32 요청 고정)과 load sweep 방식(open loop 도착률).
6. M0~M6 중 어디까지를 이번 평가 범위로 할지, C(프로토타입)를 보정에 어디까지 쓸지.
7. SSD Tier의 History에 대한 "재계산" 후보를 ExecutionPlan 후보 집합에 넣을지.
