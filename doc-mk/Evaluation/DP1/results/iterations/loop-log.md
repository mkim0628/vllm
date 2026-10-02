# DP1 Baseline-regression Loop — 반복 로그

> 작성 규칙: 각 iteration은 **(a) 진단과 원인 분류 -> (b) 실행 전 가설/변경 사전 등록 -> (c) 한 종류(class)의 변경 -> (d) 전체 benchmark 재실행 -> (e) 결과 전부 기록(나빠진 것 포함) -> (f) 계속/중단 판단** 순서로 쓴다.
> 사전 등록(b) 절은 해당 iteration의 코드를 실행하기 **전에** 작성했고, 이후 수정하지 않는다. 결과 절만 실행 후에 추가한다.
> 모든 수치는 `python3 qa_eval.py` / `loop_run.py` 출력이며 Evidence는 전부 **[B+C] (simulation)** 이다. [A] 실측이 아니다.

## 0. 배경과 프로토콜

사용자 지시: "candidate가 baseline보다 낮으면 이 architecture를 설계할 이유가 없다. 시나리오를 다시 설계하거나 설정을 바꿔 loop를 돌려라."

### 0.1 원인 분류 (class)

| class | 의미 | 허용되는 변경 |
|---|---|---|
| P | Policy / architecture defect | `policies.py`의 설계-일관 수정. 상수는 전역 설계 파라미터 하나로만, 근거를 로그에 기록 |
| B | Benchmark가 의도한 failure mode(As-Is의 static placement가 stale해지는 상황)를 실행하지 않음 | `dynamic_benchmark()`에 **baseline이 feasible한** 시나리오 추가 (기존 시나리오 유지) |
| S | System profile | 새 profile(SYS-6..)만, provenance와 함께. 기존 값 수정 금지 |
| M | Simulator cost-model gap | 물리적 근거가 있을 때만, 별도 표시 |
| N | Noise (95% CI 이내) | 변경 없음 |

금지: threshold/SLO 변경, 지는 시나리오/이전 iteration 삭제·은닉, 시나리오별 상수 튜닝, Baseline-static 약화, baseline을 infeasible로 만든 뒤 승리 주장, 최고 iteration만 보고.

### 0.2 평가 정의 (iteration 0에서 고정, 이후 불변)

- 후보: Baseline-static (Common Reference Baseline, As-Is proxy: 고정 initial placement, migration 없음), C1, C2.
- 세 benchmark set: `common_benchmark`(cb_*, 3), `dp1_stress_benchmark`(23), `dp1_dynamic_benchmark`(dyn_*, 이 loop에서 추가).
- Load sweep x0.5/1.0/1.5/2.0, seed 5개(11,23,37,53,71), t=2.776 (95% CI).
- 시나리오 label (`fit`): **infeasible** = baseline Max SLO Goodput 0 / **saturated** = feasible이지만 세 후보가 goodput·TTFT P99·TPOT P99 모두 95% CI 안에서 구분 불가 / **comparison_valid** = feasible하고 하나 이상의 후보가 baseline과 유의하게 다름.
- 시나리오별 win/tie/loss: seed paired 차이의 95% CI. 차이가 baseline 값의 1% 미만이면 tie (`MATERIAL_REL`; QA1 최소 구간 10%의 1/10). 시나리오 verdict는 goodput verdict이며, QA2 별 등급이 baseline과 다르고 latency 차이가 유의할 때만 latency verdict가 덮어쓴다.
- QA 표는 baseline goodput > 0인 시나리오(`qa_feasible` = comparison_valid + saturated)로 계산한다. QA1 = per-seed geometric mean ratio (95% CI), QA2 = max-goodput load point에서의 worst-case TTFT/TPOT P99, QA3 = useful HBM util (first-pass 임시 정의 유지, 변경하지 않음).
- "candidate >= Baseline" 판정: QA1은 ratio + CI >= 1.0 (CI parity), QA2/QA3는 별 등급 >= baseline 별 등급.
- **중단 조건**: (i) SYS-4에서 comparison-valid(+saturated) 시나리오 전부와 집계 QA1/2/3에서 candidate >= Baseline이고 통계적으로 유의한 win이 3개 이상, 또는 (ii) 6 iteration 후 (이 경우 더 튜닝하지 않고 "no benefit" 결론 + 시도 목록).

### 0.3 Iteration 0 이전 기록 (수정하지 않음)

first-pass(`2026-10-02_first-pass_superseded.md`)의 결과: SYS-4 Common Benchmark에서 C1 QA1 x0.905, TPOT P99 311 ms, C2 x0.998.

---

## Iteration 0 — 계측 확장과 원인 검증 (policy 변경 없음)

**범위**: loop의 시작점을 고정한다. `qa_eval.py`를 세 set + fit label + win/tie/loss + combined 표로 확장하고, `diagnose.py`/`loop_run.py`/`loop_tables.py`를 추가했다. 유일한 시뮬레이터 변경은 **M-class** 한 건이다.

- **M0 (flag)**: `transfer_time_s`가 destination의 `write_bw`를 무시했다 (HBF write 50 GB/s, config에 값이 있음). 물리적으로 쓰기 BW가 전송 상한이므로 `min(src.ext_bw, min(dst.ext_bw, dst.write_bw))`로 수정. Baseline은 migration을 하지 않으므로 baseline 수치는 불변. 수정 전후 SYS-4 first-pass 요약 수치 차이는 표시 자릿수에서 관측되지 않았다.

### 0.a 원인 검증 (SYS-4, seed 11, load 1.0, `python3 diagnose.py run <scenario>`)

| 가설(first-pass) | 검증 결과 | 분류 |
|---|---|---|
| (1) C1 Destination Selector가 destination의 serving cost를 보지 않는다 | **확인.** `cb_kv_8k_b32`에서 C1 access는 HBM 334, DRAM 213, HBF 428, **CXL-PNM 147**, cHBM 82, SSD-PIM 19. KV가 CXL-PNM에 있으면 TPOT 310.6 ms(`diagnose.py cost`로 확인: batch 32 attention offload). 105건 전부 rebalance(demotion 0). HBM util은 0.38이라 HBM relief가 아니라 DRAM(초기 배치 90%) pressure에 반응. SYS-2(HBM+DRAM+CXL-PNM)에서 C1 x0.850, C2 x0.544로 더 심하고, PNM이 없는 SYS-1에서는 C1 x1.000 (해로움이 PNM 경로에서 온다는 증거) | **P** |
| (2) C2는 churn하고 byte budget이 없다 | **확인.** `cb_kv_8k_b32`: promotion 167 / demotion 155 / rebalance 20, 3,784 GiB, decision overhead 139 ms/run. SYS-1(PNM 없음)에서도 387건 / 3.7 TiB를 옮기고 **이득은 0** (QA1 x1.000, TTFT만 약간 악화). `rag_1tib_b16`: C2가 34건 / 3,494 GiB / 전송 174 s를 옮기고 TTFT P99 34.3 s (baseline 83 ms): executor가 전송 시간의 20%를 다음 access TTFT에 부과하는데 대형 object에는 상한이 없다. 코드 확인: C2의 demotion은 HBM pressure와 무관하게 predicted hotness <= 0.35면 발생한다 (설계 §17.3은 "future reuse 하락 **+ upper-tier pressure**"를 요구하므로 설계 이탈) | **P** |
| (3) Common Benchmark가 steady-state라 baseline이 이미 최적에 가깝다 | **확인, 더 강하게.** cb 3개 시나리오 모두 **baseline SLO 만족률 = 1.00**. goodput = SLO를 만족한 access의 output token이므로 baseline이 100%를 만족하면 어떤 candidate도 QA1 ratio 1.0을 **넘을 수 없다** (상한 = tie). 즉 이 set에서 가능한 결과는 tie 또는 loss뿐이며 gain을 보일 수 없다 (benchmark가 As-Is failure mode를 실행하지 않음) | **B** |
| (4) stress 23개 중 14개가 baseline에서 infeasible | **확인.** SYS-4: infeasible 14 / saturated 2 / comparison_valid 7. (SYS-5는 infeasible 5 / SYS-1~3은 14) | **B** |

추가 관찰: (a) stress의 `rag_8tib_b64_ssd_pim`은 baseline goodput > 0이지만 SLO 만족률이 0.12다 (label은 saturated). 엄밀히는 거의 infeasible이며 QA2 worst-case(TTFT 793 s)를 이 시나리오가 지배한다. 정의(goodput 0 = infeasible)는 바꾸지 않고 `baseline_slo_attainment`를 함께 기록한다. (b) 시뮬레이터에서 HBM capacity가 줄어도(capacity ramp) 이미 배치된 object는 HBM에 남고 penalty가 없다. 그래서 capacity ramp는 baseline을 해치지 못한다 (M-class 후보이나 baseline을 약화시키는 방향이므로 건드리지 않는다).

### 0.b Iteration 0 결과 (policy = first-pass 그대로, 신규 계측)

`results/iterations/it0/` 에 SYS-1~5 요약 저장. SYS-4:

| set (feasible n) | Baseline | C1 | C2 | C1 w/t/l | C2 w/t/l |
|---|---|---|---|---|---|
| common_benchmark (3) | QA1 ★★ x1.000 / QA2 ★★★ (337ms,5ms) / QA3 ★ 44% | QA1 ★★ x0.905±0.016 / QA2 ★ (568ms,311ms) / QA3 ★ 37% | QA1 ★★ x0.998±0.002 / QA2 ★★ (449ms,71ms) / QA3 ★ 50% | 0/0/3 | 0/3/0 |
| dp1_stress_benchmark (9) | QA1 ★★ x1.000 / QA2 ★ / QA3 ★ 31% | QA1 ★★ x0.975±0.041 / QA2 ★ (…,617ms) / QA3 ★ 31% | QA1 ★★ x0.949±0.073 / QA2 ★ (…,497ms) / QA3 ★ 27% | 0/7/2 | 0/5/4 |
| combined (12) | QA1 ★★ x1.000 / QA2 ★ / QA3 ★ 34% | QA1 ★★ x0.957±0.032 / QA2 ★ / QA3 ★ 33% | QA1 ★★ x0.961±0.055 / QA2 ★ / QA3 ★ 33% | 0/7/5 | 0/8/4 |

SYS-4 loss 시나리오 — C1: cb_kv_8k_b32 (x0.864), cb_kv_8k_b32_ramp (x0.927), cb_mixed_8k_b32 (x0.924), kv_b16_c32k_burst_chbm (x0.944), kv_hbm_relief_behavior_recovery (x0.945). C2: agent_memory_long_lived (x0.948), behavior_flip_stress (x0.982), kv_hbm_relief_behavior_recovery (x0.984), rag_1tib_b16 (x0.921).
Win: **0 / 0** (두 candidate 모두).

다른 system (combined QA1 ratio, C1 / C2): SYS-1 1.000 / 0.992, SYS-2 0.947 / 0.816, SYS-3 0.993 / 0.991, SYS-5 0.995 / 0.979.

**판단**: 계속. 원인 (1)(2)는 P-class(후보 선택과 무관한 공통 결함), (3)(4)는 B-class. 순서: 먼저 P(candidate가 "해롭지 않은" 상태가 되도록), 그 다음 B.

---

## Iteration 1 — [사전 등록] P-class: destination access-cost, SLO 필터, do-no-harm, migration budget, benefit-vs-cost gating

> 이 절은 iteration 1 코드를 실행하기 전에 작성했다.

**진단 요약**: (1) C1 destination 선택에 serving cost가 없고, (2) 두 candidate 모두 migration budget / cooldown(C1) / benefit-vs-cost gating이 없으며, (3) C2 demotion이 upper-tier pressure 없이 발생한다.

**변경 (P-class, 설계 근거)**

1. **Access Cost Estimator** (Resource Manager 쪽, Memory Registry의 descriptor 정보만 사용: ext_bw, write_bw, latency, near-data compute 여부, int_bw, compute): `est(tier, hint, size)` -> (TTFT 추가, TPOT). C1/C2 Destination Tier Selector가 공통으로 사용한다. 설계 문서 §8.7의 입력 "memory capability, transfer cost (Memory Registry)"를 destination의 **serving cost**로 확장하는 것이다. hint는 type 이름이 아닌 operation class(`attention`/`weight_fetch`/`context_fetch`/`index_scan`)와 shape(`ctx_tokens`, `concurrency`, `out_tokens`, `touch_bytes`)로 구성하며 C1의 static affinity hint 채널(기존 `static_affinity_hints`)로 전달한다. **C1 registry는 type-agnostic 유지, C1 코드에 data type 분기 없음.**
2. **C1 Destination Selector**: 후보 필터에 (i) SLO feasibility(destination에서 추정 TTFT <= SLO, TPOT <= SLO), (ii) **do-no-harm**: source가 HBM이 아니면 destination의 추정 service time이 source보다 나쁘지 않을 것. 점수 = affinity score - (SLO 예산 대비 추가 서비스 비용). 비용은 SLO로 정규화한 무차원 값이라 별도 가중치 상수가 없다.
3. **Migration budget (C1, C2 공통)**: 전송 시간 기준 token bucket. tick당 `link_share`(=0.25)만큼 충전, 용량 = link_share x window(=8 s, cooldown과 동일). 한 migration의 추정 전송 시간 > 용량이면 DP1 loop에서 실행하지 않는다 (대형 bulk 이동은 background/staged 경로 몫). 설계 follow-up #8(anti-thrashing: hysteresis, cooldown, migration budget)과 #11(shared_link_group 단위 migration budget)에 해당.
4. **Cooldown**: C1에도 object별 cooldown 8 s 추가 (C2는 first-pass부터 8 s).
5. **C2 benefit-vs-cost gating**: 예상 이득 = r̂ x H x (현재 tier의 추가 서비스 시간 - destination의 추가 서비스 시간), 예상 비용 = 전송 시간 x executor 노출 계수(0.20). 이득 > 비용일 때만 promotion/rebalance. r̂ = Behavior Monitor의 EWMA rate(젊은 object는 class prior와 혼합: 기존 trend 식과 같은 가중). **C2 demotion은 source tier(HBM) capacity util >= 0.82(기존 high watermark)일 때만** (설계 §17.3: "reuse 하락 + upper-tier pressure"), destination은 SLO feasible.

**전역 설계 파라미터 (각 1개, 이후 튜닝하지 않음)**

| 파라미터 | 값 | 근거 |
|---|---|---|
| `MIGRATION_EXPOSURE` | 0.20 | 기존 executor가 이미 쓰는 값(`migration_debt += 0.20*dt`)을 policies.py 한 곳으로 단일화. 값 변경 없음 |
| `LINK_SHARE` | 0.25 | migration이 공유 link 시간의 최대 25%만 쓴다. 나머지 75%는 serving 트래픽 몫 (설계 §5.9.3 link 중재 취지). 시뮬레이터에 근거 데이터가 없는 **설계 선택**이며 sensitivity는 후속 과제 |
| `BUDGET_WINDOW_S` = `COOLDOWN_S` | 8 s | first-pass C2 cooldown 값 재사용 |
| `BENEFIT_HORIZON_S` (H) | 30 s | C2 behavior look-ahead. KV 평균 lifetime 90 s의 1/3. 설계 선택 |
| SLO | 2 s / 50 ms | `simulator.py` 상수(변경 없음)를 `SimContext`로 전달 |

**가설과 반증 조건 (SYS-4)**

- H1.1: C1이 cb 3개에서 baseline과 CI parity (QA1 ratio + CI >= 1.0)이고 TPOT P99 <= 50 ms (CXL-PNM attention 경로 선택이 사라짐). 반증: cb에서 C1 ratio < 0.97 이거나 TPOT P99 > 50 ms.
- H1.2: C2의 migration 건수가 cb에서 first-pass 대비 80% 이상 감소하고 QA1 parity, `rag_1tib_b16` TTFT P99 < 2 s. 반증: 건수 감소 < 50% 또는 TTFT P99 >= 2 s.
- H1.3 (음성 예측): benchmark가 steady-state이므로 **유의한 win은 생기지 않는다.** 따라서 중단 조건(i)은 충족되지 않고 iteration 2(B-class)가 필요하다.
- 실패 시: 결과를 그대로 기록하고 상수를 조정하지 않는다. 다음 iteration에서 원인을 다시 분류한다.

---

## Iteration 1 — [결과] P-class (실행 후 기록)

구현: `policies.py` — `AccessCostEstimator`, `MigrationBudget`, `est_transfer_s`, C1 Destination Selector(SLO 필터 + do-no-harm + 비용 항), C1 cooldown/budget, C2 benefit-vs-cost gating + demotion pressure 조건 + cost-aware destination(predicted-hot는 가장 싼 feasible tier, 그 외는 가장 싼 non-HBM tier). `simulator.py` — `static_hints`에 operation class/shape 추가, `SimContext`에 SLO 전달, `MIGRATION_EXPOSURE` 단일화. 사전 등록한 파라미터(0.25 / 8 s / 30 s / 0.20) 그대로 사용했고 실행 후 조정하지 않았다. 구현 도중 한 가지를 같은 iteration 안에서 바꿨다: 첫 구현의 C2 demotion destination이 "가장 큰 capacity tier"여서 custom_hbm(TPOT 11.6 ms, 서비스 penalty가 DRAM보다 큼)으로 내려가 promotion/demotion churn이 남았기에 cost-aware destination으로 교체했다. 이 교체는 `cb_kv_8k_b32` 한 시나리오(diagnose) 관찰 후 이루어졌으며, 이후 상수 조정은 없다.

### SYS-4 (`results/iterations/it1/`)

| set (feasible n) | Baseline | C1 | C2 | C1 w/t/l | C2 w/t/l |
|---|---|---|---|---|---|
| common_benchmark (3) | QA1 ★★ x1.000 / QA2 ★★★ (337ms,5ms) / QA3 ★ 44% | QA1 ★★ x1.000±0.000 / QA2 ★★★ (263ms,5ms) / QA3 ★ 41% | QA1 ★★ x1.000±0.000 / QA2 ★★★ (324ms,5ms) / QA3 ★ 59% | 0/3/0 | 0/3/0 |
| dp1_stress_benchmark (9) | QA1 ★★ x1.000 / QA2 ★ / QA3 ★ 31% | QA1 ★★ x1.000±0.000 / QA2 ★ (793052ms,14ms) / QA3 ★ 31% | QA1 ★★ x1.037±0.066 / QA2 ★ (793052ms,14ms) / QA3 ★ 34% | 0/9/0 | 0/9/0 |
| combined (12) | QA1 ★★ x1.000 / QA2 ★ / QA3 ★ 34% | QA1 ★★ x1.000±0.000 / QA2 ★ / QA3 ★ 34% | QA1 ★★ x1.028±0.049 / QA2 ★ / QA3 ★ 40% | 0/12/0 | 0/12/0 |

(stress의 QA2 worst-case는 baseline SLO 만족률 0.12인 `rag_8tib_b64_ssd_pim`이 지배하므로 세 후보가 같다.)

migration 지표(SYS-4, set 평균): cb — C1 110 -> 13건 (1,266 -> 190 GiB), C2 389 -> 182건 (3,767 -> 1,639 GiB); stress(feasible 9) — C1 20 -> 2건, C2 86 -> 26건. `rag_1tib_b16` C2 TTFT P99 34.3 s -> 83.7 ms (baseline 83.5 ms). 전 시나리오 win 0 / loss 0 (C1, C2 모두).

다른 system (combined QA1 ratio C1 / C2, w-t-l): SYS-1 1.000 / 1.000 (0-12-0 / 0-12-0), SYS-2 1.000 / 1.000 (0-12-0 / 0-12-0), SYS-3 1.000 / 1.000 (0-12-0 / 0-12-0), SYS-5 1.000 / 1.027 (0-21-0 / **3**-18-0). SYS-5의 C2 win 3건은 stress의 `rag_8tib_b256_ssd_pim` (x1.296), `rag_8tib_b64_ssd_pim` (x1.318), `six_tier_capacity_stress` (x1.029). SYS-4에서는 같은 시나리오가 CI 안(tie)이다.

### 가설 판정

- **H1.1 확인**: C1이 cb 3개 모두 ratio 1.000 (CI parity), TPOT P99 5 ms, loss 0. SYS-2(CXL-PNM 존재)에서도 C1/C2가 x0.85/x0.54 -> x1.000.
- **H1.2 부분 확인**: C2 migration 건수 감소는 cb 기준 53% (389 -> 182). 사전 등록한 "80% 이상" 기준에는 미달이고 "50% 미만이면 반증" 기준은 넘었다 (즉 확인도 반증도 아님: churn이 줄었지만 남아 있다). `rag_1tib_b16` TTFT P99 < 2 s는 확인(83.7 ms). C2 decision overhead는 불변(cb 169 ms/run): 이번 iteration에서 건드리지 않았다.
- **H1.3 확인 (음성 예측)**: SYS-4에서 유의한 win이 0이다. candidate가 baseline을 이긴 것은 없다. 따라서 중단 조건 (i)의 "유의한 win 3개"는 충족되지 않는다.

### 판단

회귀(candidate < baseline)는 **제거**되었다 (loss 0). 그러나 이는 "candidate가 baseline을 이긴다"가 아니라 "해롭지 않다"는 뜻이다. cb에서는 baseline SLO 만족률이 1.00이므로 이득의 상한이 0이다 (iteration 0 진단 (3)). 계속한다. 다음은 **B-class**: baseline은 feasible하되 static placement가 runtime에 stale해지는 시나리오.

---

## Iteration 2 — [사전 등록] B-class: `dynamic_benchmark()` 추가 (policy 코드 변경 없음)

> 이 절은 iteration 2의 candidate 실행 전에 작성했다. **시나리오 설계 과정에서는 Baseline-static만 실행**했고(`diagnose.py cost`, baseline 단독 run, control run), C1/C2를 dynamic 시나리오에서 돌린 적이 없다. 시나리오는 아래 내용으로 동결하고 실행 후 수정하지 않는다.

**진단 근거**: iteration 0의 (3)(4) — Common/Stress set에서는 baseline이 이미 SLO를 100% 만족하거나(이득 상한 0) 아예 infeasible이어서 As-Is의 의도된 failure mode(static placement가 runtime에 stale)를 아무도 실행하지 않는다.

**변경 (B-class만)**: `scenarios.py`에 `dynamic_benchmark()` 6개 시나리오, `dynamic_controls()`(동일 workload에서 staleness 제거), generator의 `Scenario.plan` 필드(class별 deterministic object plan, rate schedule; 기존 시나리오는 plan이 비어 있어 trace 불변), `DataObject.rate_schedule`(기본 빈 값). 기존 시나리오/결과는 그대로 유지한다.

| 시나리오 | 현실의 serving 패턴 | As-Is failure mode |
|---|---|---|
| `dyn_cold_resident_chat_wave` | start-up에 올라온 장수명 Agent Memory(idle tenant의 episodic state) 9개가 HBM을 선착순으로 채운 뒤 t=20~30 s에 interactive 장문(320K, b16) chat wave(KV 4개)가 도착 | 신규 hot KV가 DRAM에 배치되어 영구히 host link restore 비용을 낸다 |
| `dyn_idle_kv_holds_hbm` | tool call 대기 중인 session KV 4개(rate x0.05, idle)가 HBM을 점유, t=30~40 s에 tool result 복귀/신규 session 4개가 hot set이 됨 (**같은 data class**) | 도착 순서가 HBM 잔류를 결정, hot session은 DRAM 서빙 |
| `dyn_kv_hotset_recency_shift` | working-set drift: 먼저 만든 대화(HBM)가 t=90 s에 cold(x0.1), 나중 대화(DRAM)가 hot(x30 vs 초기 x0.1) | 배치가 옛 working set에 고정 |
| `dyn_kv_rotating_hotset` | 3개 user group이 60 s씩 번갈아 active (교대 근무/시간대 인수인계). HBM은 한 group의 working set 크기 (`hbm_capacity_mult` 0.30) | 첫 window에만 맞는 배치. hot set이 60 s마다 이동하므로 **anti-thrashing 시험** |
| `dyn_rag_shard_hotset_shift` | GPU-resident vector index shard 8개(각 ~32 GiB)의 query popularity가 t=90 s에 이동 (trending topic / 신규 문서) | hot shard가 DRAM에서 scan됨 (index 전체가 host link를 건넘) |
| `dyn_host_path_contention_kv` | host-side 경합(공존 checkpoint/dataloader/NIC 트래픽)으로 t=90 s부터 host link BW 25%. DRAM에 spill된 128K KV는 그 전에는 SLO를 만족 | static tier 순서가 degrade된 경로에 spill session을 고정 |

설계 근거와 파라미터: (a) KV 320K/b16/64 token cell은 HBM 서빙(TPOT 32 ms)은 SLO를 만족하지만 DRAM 서빙(TPOT 51~64 ms, host link 64 GB/s로 ~107 GiB restore)은 TPOT SLO 50 ms를 넘는 구성이다 (stress set이 이미 512K까지 사용). (b) `hbm_capacity_mult`는 "HBM이 초기 hot working set을 담을 크기"로 시나리오마다 한 번 정했다 (0.40 / 0.30 / 0.12 / 0.12, baseline만 실행해 확인). (c) 모든 planned object는 horizon 동안 생존한다 (설계 중 non-plan 경로에서 KV lifetime이 ~90 s라 post-shock 구간이 비는 버그를 baseline 단독 실행으로 발견해 plan 경로로 전환).

**Baseline feasibility 증거 (SYS-4, seed 11/23/37, baseline-only 실행)**

| 시나리오 | baseline SLO 만족률 | 같은 workload의 control(`__control`: HBM ample / BW shock 없음) |
|---|---|---|
| dyn_cold_resident_chat_wave | 0.55 / 0.50 / 0.50 | 1.00 / 1.00 / 1.00 |
| dyn_idle_kv_holds_hbm | 0.51 / 0.26 / 0.24 | 1.00 |
| dyn_kv_hotset_recency_shift | 0.18 / 0.43 / 0.30 | 1.00 |
| dyn_kv_rotating_hotset | 0.39 / 0.30 / 0.34 | 1.00 |
| dyn_rag_shard_hotset_shift | 0.27 / 0.22 / 0.26 | 1.00 |
| dyn_host_path_contention_kv | 0.76 / 0.69 / 0.71 | 1.00 |

주의: baseline 만족률이 0.2~0.8이다. 즉 baseline은 **전체 구간에서 SLO를 만족하지 못한다**. control(staleness 제거)에서 1.00이고 stale 이전 구간에서는 만족하므로 "feasible하나 stale해지는" 시나리오로 정의하지만, 이 set에서의 이득은 **"static placement가 stale해지는 workload"라는 조건**에서만 의미가 있다. `test_sim.py`가 control에서 baseline 만족률 >= 0.99를 검사한다.

**사전 예측 (SYS-4)**

- P2.1: C2는 hot object의 이동 이득을 rate로 예측하므로 `dyn_idle_kv_holds_hbm`, `dyn_kv_hotset_recency_shift`, `dyn_rag_shard_hotset_shift`, `dyn_cold_resident_chat_wave`, `dyn_host_path_contention_kv`에서 유의한 win 4개 이상. 단 object당 ~100 GiB 이동은 budget(link 시간 25%, 용량 2 s)에 걸려 한 번에 ~1건씩만 가능하므로 이득은 부분적일 것이다.
- P2.2: C1은 resource pressure(HBM util >= 0.82)에만 반응하는데 이 시나리오들의 HBM 초기 util은 ~0.80이라 trigger가 약하고, **C1에는 promotion 경로 자체가 구현되어 있지 않다** (설계 §17.2는 허용). 따라서 `dyn_host_path_contention_kv`(DRAM의 BW util이 trigger)를 제외하면 tie일 것이다. win 0~1개. loss는 예측하지 않는다 (iteration 1의 do-no-harm).
- P2.3: C2 loss/QA 회귀 없음, 단 `dyn_kv_rotating_hotset`은 hot set이 60 s마다 이동하므로 migration churn으로 이득이 작거나 TTFT 악화가 있을 수 있다 (anti-thrashing 시험).
- 중단 조건 (i) 예상: C2는 충족 가능, C1은 win 부족으로 미충족 -> iteration 3 (P: C1 promotion/affinity 경로)로 진행.
- 반증: C2 win < 3 이면 "dynamic benchmark에서도 C2 이득 없음"으로 기록하고 원인을 재분류한다.

---

## Iteration 2 — [결과] B-class (실행 후 기록)

policy 코드는 iteration 1과 동일하다 (Common/Stress set의 결과는 iteration 1과 비트 단위로 같음 — 아래 표 참조). `results/iterations/it2/` 에 SYS-1~5 요약 저장.

### SYS-4

| set (feasible n) | Baseline | C1 | C2 | C1 w/t/l | C2 w/t/l |
|---|---|---|---|---|---|
| common_benchmark (3) | QA1 ★★ x1.000 / QA2 ★★★ (337ms,5ms) / QA3 ★ 44% | QA1 ★★ x1.000 / QA2 ★★★ / QA3 ★ 41% | QA1 ★★ x1.000 / QA2 ★★★ / QA3 ★ 59% | 0/3/0 | 0/3/0 |
| dp1_stress_benchmark (9) | QA1 ★★ x1.000 / QA2 ★ / QA3 ★ 31% | QA1 ★★ x1.000 / QA2 ★ / QA3 ★ 31% | QA1 ★★ x1.037±0.066 / QA2 ★ / QA3 ★ 34% | 0/9/0 | 0/9/0 |
| **dp1_dynamic_benchmark (6)** | QA1 ★★ x1.000 / QA2 ★ (9567ms,63ms) / QA3 ★ 30% | QA1 ★★★ x1.106±0.064 / QA2 ★ (9567ms,62ms) / QA3 ★ 35% | QA1 ★★★ **x2.211±0.078** / QA2 ★★ (2160ms,62ms) / QA3 ★★ 69% | **1**/5/0 | **6**/0/0 |
| combined (18) | QA1 ★★ x1.000 / QA2 ★ / QA3 ★ 33% | QA1 ★★ x1.034±0.020 / QA2 ★ / QA3 ★ 34% | QA1 ★★★ x1.327±0.042 / QA2 ★ / QA3 ★ 50% | 1/17/0 | 6/12/0 |

dynamic 시나리오별 (SYS-4, goodput ratio vs baseline, 95% CI verdict):

| 시나리오 | baseline SLO 만족률 | C1 | C2 | TTFT P99 B/C1/C2 (ms) | TPOT P99 B/C1/C2 (ms) |
|---|---|---|---|---|---|
| dyn_cold_resident_chat_wave | 0.47 | x1.323 (tie, CI 안) | x1.701 (**win**) | 2200/2047/2160 | 63/61/62 |
| dyn_host_path_contention_kv | 0.71 | x1.380 (**win**) | x1.378 (**win**) | 3176/1386/1393 | 62/34/33 |
| dyn_idle_kv_holds_hbm | 0.29 | x1.000 (tie) | x2.823 (**win**) | 2104/2104/2104 | 62/62/62 |
| dyn_kv_hotset_recency_shift | 0.31 | x1.000 (tie) | x2.618 (**win**) | 2148/2148/2120 | 62/62/62 |
| dyn_kv_rotating_hotset | 0.38 | x1.000 (tie) | x1.701 (**win**) | 2127/2127/2120 | 62/62/62 |
| dyn_rag_shard_hotset_shift | 0.26 | x1.000 (tie) | x3.967 (**win**) | 9567/9567/813 | 5/5/5 |

(P99는 baseline이 이미 위반하는 구간이 1% 이상이라 baseline/C1에서 위반 상태로 남는다. C2가 위반을 줄이는 시나리오에서만 TTFT P99가 내려간다: `rag_shard` 9.6 s -> 0.8 s.)

### 다른 system (dynamic set, win/tie/loss)

| SYS | baseline 평균 SLO 만족률 | C1 | C2 | 비고 |
|---|---|---|---|---|
| SYS-1 (HBM+DRAM) | 0.26~0.71 | 0/6/0 (QA1 x1.040) | **6**/0/0 (x1.519) | |
| SYS-2 (+CXL-PNM) | SYS-1과 동일 | 0/6/0 | 6/0/0 | CXL-PNM이 선택되지 않아 SYS-1과 같은 값 |
| SYS-3 (+HBF) | SYS-4와 동일 | 1/5/0 (x1.106) | 6/0/0 (x2.211) | SYS-3 = SYS-4 (HBF가 있으면 cHBM/PNM/SSD-PIM은 쓰이지 않음) |
| SYS-5 (Vera Rubin) | 0.91~1.00 | 1/5/0 (x1.016) | 1/5/0 (x1.023) | **baseline이 거의 포화**: HBM 3 TB(x8)가 시나리오의 object를 대부분 담아 stale 구간이 사라짐. win은 `dyn_host_path_contention_kv`뿐 |

SYS-5의 결과는 중요한 한계다: dynamic 시나리오의 크기(object ~100 GiB, `hbm_capacity_mult`)는 B200 x8 기준으로 설계되었다. HBM이 2배 큰 Vera Rubin에서는 같은 workload가 HBM에 들어가므로 baseline이 stale해지지 않는다. 시나리오를 SYS-5에 맞춰 다시 조정하지 않았다 (결과를 본 뒤 조정은 금지).

### Common/Stress set 회귀 확인

SYS-4 Common QA1 C1/C2 = x1.000/x1.000, stress = x1.000/x1.037, loss 0건 (iteration 1과 동일). SYS-1~5 모두 loss 0.

### 가설 판정

- **P2.1 확인**: C2 win 6/6 (예측 >= 4). 단 `dyn_kv_rotating_hotset`에서도 x1.701 win이어서 "churn으로 이득이 작거나 TTFT 악화" 예측(P2.3)은 **반증**되었다 (60 s마다 hot set이 이동해도 cooldown 8 s + budget이 thrashing을 막고 이득이 남음).
- **P2.2 확인**: C1 win 1 (`dyn_host_path_contention_kv`, DRAM BW util trigger) + 나머지 tie, loss 0. 예측 "0~1개"와 일치.
- 중단 조건 (i) 판정 (SYS-4): **C2는 충족** (comparison-valid 18개 중 loss 0, 집계 QA1/QA2/QA3 >= baseline, 유의한 win 6개). **C1은 미충족** (유의한 win 1개).

### 판단

C2는 (i)을 충족했으므로 C2 코드는 더 바꾸지 않는다. C1은 win이 부족한 원인이 진단된다: 코드를 보면 C1에는 **promotion 경로가 아예 없다**(demotion/rebalance만 구현). 설계 §17.2는 C1 promotion trigger로 "static affinity상 upper tier 선호 object가 lower tier에 존재"를 명시적으로 허용한다. 이는 policy 구현이 설계보다 빈약한 **P-class 결함**이다. iteration 3에서 C1에 한해 이 경로를 구현하고(설계 일관), C2는 불변으로 두어 회귀 확인에 쓴다.

---

## Iteration 3 — [사전 등록] P-class: C1 promotion path (설계 §17.2: static affinity + upper tier 여유/교환)

> 이 절은 iteration 3 코드를 실행하기 전에 작성했다. C2 코드는 변경하지 않는다.

**진단**: iteration 2에서 C1이 `dyn_cold_resident_chat_wave`(Agent Memory가 HBM 점유, 신규 KV는 DRAM)에서 tie인 이유: HBM util 0.80 < 0.82라 trigger가 없고, 설령 trigger가 있어도 C1 코드는 DRAM의 KV를 HBM으로 올리는 경로가 없다.

**변경 (P-class, C1만)**

1. **Promotion pass** (telemetry event마다 demotion pass 뒤에 실행). 후보 = 하위 tier에 있고 **static 추정으로 SLO를 위반**하지만(AccessCostEstimator, hint) HBM에서는 SLO를 만족하는 object (design 17.2 trigger: "static affinity상 upper tier 선호 object가 lower tier에 존재"). rate/behavior는 사용하지 않는다 (C1은 per-object behavior를 추적하지 않음). type 이름도 쓰지 않고 operation-class hint와 descriptor만 사용한다.
2. HBM에 자리가 있고 이동 후 util <= high watermark(0.82)이면 직접 promotion. 자리가 없으면 **교환(swap)**: HBM 거주자 중 demotion했을 때의 static serving penalty가 가장 작은 것부터 victim으로 고르고(destination은 기존 Destination Selector, SLO feasible), **promotee의 penalty 감소가 victim의 penalty 증가의 `AFFINITY_MARGIN`배 이상**일 때만 실행. 같은 class끼리(예: KV 대 KV)는 static 신호가 구분되지 않아 교환이 일어나지 않는다. 이것이 C1의 설계상 한계(같은 class 내부 object별 hot/cold를 모름, §10)다.
3. 같은 budget(link 시간 25%), cooldown 8 s 적용. victim demotion과 promotion 모두 budget을 쓴다.

**전역 설계 파라미터**: `AFFINITY_MARGIN` = 2.0 (hysteresis: static 신호가 2배 이상 차이 날 때만 "구분 가능"으로 본다. C1은 rate를 모르므로 같은 class 내 크기 차이 정도의 잡음 교환을 막기 위한 설계 선택. 사전 등록 후 조정하지 않는다).

**가설과 반증 조건 (SYS-4)**

- H3.1: C1이 `dyn_cold_resident_chat_wave`에서 유의한 win (CI 하한 > baseline), 다른 dynamic 시나리오는 tie 유지 (같은 class 교환 금지). 반증: chat_wave가 여전히 tie이거나 다른 시나리오에서 loss.
- H3.2: C1의 유의한 win은 총 2개(chat_wave + host_path)로 3개에 못 미친다 (idle/recency/rotating/rag_shard는 같은 class라 구분 불가). 이 경우 C1의 최종 결론은 "win은 이 두 조건에서만, 나머지는 parity"이며 더 튜닝하지 않는다.
- H3.3: Common/Stress/다른 dynamic에서 C1 loss 0 유지, C2 결과는 iteration 2와 동일(회귀 확인).

---

## Iteration 3 — [결과] P-class: C1 promotion path (실행 후 기록)

구현 (`policies.py`): `C1ResourceDrivenMigration._promotion_pass` — static 추정으로 SLO를 위반하는 하위 tier object를 HBM으로 promotion, 자리가 없으면 `AFFINITY_MARGIN`(=2.0) 조건의 swap. 사전 등록한 파라미터를 그대로 썼다. **같은 iteration 안에서 구현을 두 번 고쳤다** (diagnose 한 시나리오 `dyn_cold_resident_chat_wave` 관찰 후): (1) swap 전체 전송 시간(~3.8 s)이 budget bucket 용량(2 s)을 넘어 한 번도 실행되지 않아 단계별 budget 소비로 변경, (2) 단계별 소비에서는 victim demotion이 budget을 먼저 소진해 promotion이 굶으므로, victim이 비워진 뒤 promotion 전송 시간을 budget에 reserve하고 swap은 한 번에 하나만 진행하도록 변경. budget 파라미터(0.25 / 8 s)는 바꾸지 않았다. C2 코드는 변경 없음 (아래 표에서 C2 수치가 iteration 2와 동일함을 확인).

### SYS-4 (`results/iterations/it3/`)

| set (feasible n) | Baseline | C1 | C2 | C1 w/t/l | C2 w/t/l |
|---|---|---|---|---|---|
| common_benchmark (3) | QA1 ★★ x1.000 / QA2 ★★★ (337ms,5ms) / QA3 ★ 44% | QA1 ★★ x1.000 / QA2 ★★★ (263ms,5ms) / QA3 ★ 41% | QA1 ★★ x1.000 / QA2 ★★★ (324ms,5ms) / QA3 ★ 59% | 0/3/0 | 0/3/0 |
| dp1_stress_benchmark (9) | QA1 ★★ x1.000 / QA2 ★ / QA3 ★ 31% | QA1 ★★ x1.000 / QA2 ★ / QA3 ★ 31% | QA1 ★★ x1.037±0.066 / QA2 ★ / QA3 ★ 34% | 0/9/0 | 0/9/0 |
| **dp1_dynamic_benchmark (6)** | QA1 ★★ x1.000 / QA2 ★ (9567ms,63ms) / QA3 ★ 30% | QA1 ★★★ **x1.643±0.285** / QA2 ★★ (2138ms,62ms) / QA3 ★ 48% | QA1 ★★★ **x2.211±0.078** / QA2 ★★ (2160ms,62ms) / QA3 ★★ 69% | **3**/3/0 | **6**/0/0 |
| combined (18) | QA1 ★★ x1.000 / QA2 ★ / QA3 ★ 33% | QA1 ★★★ x1.180±0.066 / QA2 ★ / QA3 ★ 39% | QA1 ★★★ x1.327±0.042 / QA2 ★ / QA3 ★ 50% | 3/15/0 | 6/12/0 |

dynamic 시나리오별 (SYS-4):

| 시나리오 | baseline SLO 만족률 | C1 | C2 | TTFT P99 B/C1/C2 (ms) | TPOT P99 B/C1/C2 (ms) | migration C1 / C2 (건, GiB) |
|---|---|---|---|---|---|---|
| dyn_cold_resident_chat_wave | 0.47 | x1.830 (**win**) | x1.701 (**win**) | 2200/1964/2160 | 63/59/62 | 5, 401 / 66, 3224 |
| dyn_host_path_contention_kv | 0.71 | x1.380 (**win**) | x1.378 (**win**) | 3176/1386/1393 | 62/34/33 | 4, 175 / 64, 2474 |
| dyn_idle_kv_holds_hbm | 0.29 | x1.480 (tie) | x2.823 (**win**) | 2104/2104/2104 | 62/62/62 | 1, 106 / 30, 2568 |
| dyn_kv_hotset_recency_shift | 0.31 | x1.115 (tie) | x2.618 (**win**) | 2148/2138/2120 | 62/62/62 | 1, 70 / 27, 2210 |
| dyn_kv_rotating_hotset | 0.38 | x1.192 (tie) | x1.701 (**win**) | 2127/2082/2120 | 62/61/62 | 2, 153 / 21, 1807 |
| dyn_rag_shard_hotset_shift | 0.26 | x3.962 (**win**) | x3.967 (**win**) | 9567/740/813 | 5/5/5 | 8, 265 / 55, 1789 |

### 다른 system (win/tie/loss; 전 set에서 **loss 0**)

| SYS | dynamic: C1 | dynamic: C2 | combined QA1 ratio C1 / C2 |
|---|---|---|---|
| SYS-1 | 1/5/0 | 6/0/0 | 1.049 / 1.149 |
| SYS-2 | 1/5/0 | 6/0/0 | 1.049 / 1.149 |
| SYS-3 | 3/3/0 | 6/0/0 | 1.182 / 1.303 (dynamic set은 SYS-4와 같고 stress 일부가 다름) |
| SYS-4 | 3/3/0 | 6/0/0 | 1.180 / 1.327 |
| SYS-5 | 1/5/0 | 1/5/0 | 1.005 / 1.026 (stress에서 C2 win 3) |

(SYS-1/2의 C1 win 1개는 `dyn_cold_resident_chat_wave`다. HBF가 없으면 `dyn_host_path_contention_kv`(DRAM -> HBF rebalance 대상 없음)와 `dyn_rag_shard_hotset_shift`(swap victim이 갈 곳이 DRAM뿐인데 DRAM은 SLO 위반)에서 C1 win이 사라진다. SYS-5는 baseline이 거의 포화라 win이 `dyn_host_path_contention_kv` 1개다.)

### 가설 판정

- **H3.1 확인**: C1이 `dyn_cold_resident_chat_wave`에서 유의한 win (x1.830). 다른 dynamic 시나리오 loss 0.
- **H3.2 반증 (예측 과소)**: C1 win은 2개가 아니라 **3개**다. 예측하지 못한 `dyn_rag_shard_hotset_shift` (x3.962)에서도 이긴다. 원인 분석: C1은 rate를 모르지만 이 시나리오의 DRAM shard는 **전부 static 추정상 SLO 위반**(index scan 8.6 s)이고 victim(HBM의 cold shard)은 HBF로 내려가도 SLO를 만족한다. 그래서 위반 object를 차례로 promotion하는 static 규칙이 우연히 hot shard 이동과 맞아떨어진다. shard가 수십 개이고 hot이 소수인 상황에서는 같은 규칙이 불필요한 이동을 만들 것이다 (이 benchmark에서는 관측되지 않음). KV 시나리오 3개(idle/recency/rotating)에서는 C1이 x1.1~1.5로 개선하지만 CI 안이라 tie다 (같은 class라 hot/cold를 구분하지 못하는 §10의 한계가 그대로 나타남).
- **H3.3 확인**: Common/Stress/다른 dynamic에서 C1 loss 0, C2 수치는 iteration 2와 동일.
- migration 비용: C1은 1~8건 (70~400 GiB), C2는 21~66건 (1.8~3.2 TiB)으로 비슷한 방향의 이득을 C1이 약 10배 적은 byte로 얻는다 (단 C2의 이득이 더 큰 시나리오가 있음: idle/recency x2.6~2.8).
- QA3 (임시 정의, HBM useful util): dynamic set에서 baseline 30% -> C1 48%, C2 69%. Common set에서는 C1 41% < baseline 44% (C1이 cold 데이터를 HBM 밖으로 내려 HBM occupancy가 줄어든다; 별 등급은 같은 ★이다).

### 판단: 중단 조건 (i) 충족 (SYS-4, iteration 3)

- comparison-valid(+saturated) 18개 시나리오 모두에서 C1, C2 >= Baseline (loss 0).
- 집계 QA1 combined: C1 x1.180±0.066, C2 x1.327±0.042 (둘 다 CI 하한 > 1). QA2/QA3 별 등급은 combined에서 Baseline과 같거나 높다 (QA2 ★ = ★ — stress의 baseline 자체 위반 시나리오가 worst-case를 지배, QA3 ★ = ★).
- 통계적으로 유의한 win: C1 3개, C2 6개 (>= 3).
- 사전 등록한 "6 iteration 이내 중단" 규칙에 따라 **여기서 loop를 중단한다. 추가 튜닝은 하지 않는다.** 사용한 iteration은 3개 (0 = 계측, 1 = P, 2 = B, 3 = P).

---

## 최종 요약 (iteration 3에서 중단)

재현: `cd doc-mk/Evaluation/DP1/sim && python3 test_sim.py && python3 loop_run.py --final` (SYS-1~5, 3 set, seed 11/23/37/53/71, load x0.5/1.0/1.5/2.0, 95% CI t=2.776). 코드 revision: `git rev-parse --short HEAD` = `cfa8e6d` + **working tree dirty** (이 loop의 변경이 아직 commit 전). 최종 raw 출력: `results/data/SYS-{1..5}/qa_result.json` (seed별 벡터, fit label, win/tie/loss 포함). 최종 코드의 결과는 iteration 3 요약(`it3/`)과 SYS-4에서 일치함을 확인했다 (이후 코드 변경은 테스트/문서/보조 스크립트뿐).

### Iteration 표 (SYS-4, QA1 = geometric-mean ratio, 집계는 baseline goodput > 0 시나리오)

| iter | class | 변경 | C1 | C2 |
|---|---|---|---|---|
| 0 | (계측) + M0 | qa_eval 확장(3 set, fit label, win/tie/loss), `write_bw` 반영(M) | combined QA1 x0.957, loss 5 (cb x0.905, TPOT 311 ms) | x0.961, loss 4 (cb x0.998) |
| 1 | P | access-cost estimator, SLO 필터, do-no-harm, link-time budget, cooldown, C2 benefit-vs-cost + 압력 조건 demotion | x1.000, loss 0, win 0 (cb TPOT 5 ms) | x1.028, loss 0, win 0 (migration 389 -> 182건 cb) |
| 2 | B | `dynamic_benchmark()` 6개 + controls (policy 불변) | dynamic x1.106, win 1 | dynamic x2.211, win 6 |
| 3 | P | C1 promotion path (static SLO 위반 object를 HBM으로, swap, reserve) | dynamic x1.643, win 3 | 불변 (x2.211, win 6) |

### 최종 set별 QA (SYS-4, [B+C] simulation, baseline goodput > 0 시나리오)

| set (n) | QA | Baseline | C1 | C2 |
|---|---|---|---|---|
| common (3) | QA1 | ★★ 3,272 tps | ★★ x1.000±0.000 | ★★ x1.000±0.000 |
| | QA2 | ★★★ TTFT 337 / TPOT 5 ms | ★★★ 263 / 5 ms | ★★★ 324 / 5 ms |
| | QA3 | ★ 44% | ★ 41% | ★ 59% |
| stress (9 of 23) | QA1 | ★★ 370 tps | ★★ x1.000±0.000 | ★★ x1.037±0.066 |
| | QA2 | ★ 793 s / 14 ms (baseline 자체 위반 시나리오가 지배) | 동일 | 동일 |
| | QA3 | ★ 31% | ★ 31% | ★ 34% |
| dynamic (6) | QA1 | ★★ 120 tps | ★★★ x1.643±0.285 | ★★★ x2.211±0.078 |
| | QA2 | ★ 9,567 ms / 63 ms | ★★ 2,138 / 62 ms | ★★ 2,160 / 62 ms |
| | QA3 | ★ 30% | ★ 48% | ★★ 69% |
| combined (18) | QA1 | ★★ 771 tps | ★★★ x1.180±0.066 | ★★★ x1.327±0.042 |
| | QA2 | ★ 793 s / 63 ms | ★ 793 s / 62 ms | ★ 793 s / 62 ms |
| | QA3 | ★ 33% | ★ 39% | ★ 50% |

QA4 (Modifiability)는 이 loop에서 변경하지 않았다 (first-pass의 architecture argument 유지). 단 아래 "설계 문서 영향"의 새 입력이 QA4 판단에 영향을 줄 수 있다.

### 시나리오별 win/tie/loss (SYS-4, baseline 대비, 95% CI 유의성)

- **C1**: win 3 — `dyn_cold_resident_chat_wave` (x1.830), `dyn_host_path_contention_kv` (x1.380), `dyn_rag_shard_hotset_shift` (x3.962). tie 15 (3 common + 9 stress + dyn idle/recency/rotating; 후자 3개는 x1.48 / x1.12 / x1.19이나 CI 안). **loss 0**.
- **C2**: win 6 — dynamic 6개 전부 (x1.70 / x1.38 / x2.82 / x2.62 / x1.70 / x3.97). tie 12 (3 common + 9 stress). **loss 0**. stress의 `rag_8tib_b64_ssd_pim` x1.389는 baseline SLO 만족률 0.12 시나리오에서 CI 안(tie)이다.
- infeasible 14개(stress)는 baseline goodput 0이라 비교에서 제외하고 목록에 남겼다 (`qa_result.json`의 `fit`).

### Sensitivity (iteration 3 이후 보고용, **파라미터 조정 아님**; `results/data/sensitivity_SYS-4.json`, `sensitivity_console.txt`)

한 번에 하나씩 사전 등록 값에서 움직였다 (SYS-4, 3 set 전부). 모든 변형에서 **loss 0**, Common set은 전부 x1.000 (tie 3).

| 변형 | dynamic C1 QA1 (w/t/l) | dynamic C2 QA1 (w/t/l) |
|---|---|---|
| 등록값 (share 0.25, window 8 s, H 30 s, margin 2) | x1.643 (3/3/0) | x2.211 (6/0/0) |
| LINK_SHARE 0.10 | x1.257 (1/5/0) | x1.293 (2/4/0) |
| LINK_SHARE 0.50 | x2.647 (6/0/0) | x2.642 (6/0/0) |
| window(=cooldown) 4 s | x1.308 (2/4/0) | x1.317 (2/4/0) |
| window(=cooldown) 16 s | x2.628 (6/0/0) | x2.592 (6/0/0) |
| BENEFIT_HORIZON_S 10 / 60 | x1.643 / x1.643 (3/3/0) | x2.219 / x2.211 (6/0/0) |
| AFFINITY_MARGIN 1 / 4 | x1.643 (3/3/0) | x2.211 (6/0/0) |

해석: 이득의 크기와 유의한 win 개수는 **migration budget(link 시간 비율과 bucket 용량)에 가장 민감**하다. 보수적 쪽(share 0.10, window 4 s)에서는 win이 1~2개로 줄어 중단 조건 (i)의 "win >= 3"이 충족되지 않는다. 이유는 시나리오의 object가 ~100 GiB라 한 번 이동에 link 시간 1.7 s가 들기 때문이다. 등록값(0.25 / 8 s)은 두 방향 사이의 중간이며 결과를 보고 고른 값이 아니다 (iteration 1 사전 등록). `BENEFIT_HORIZON_S`와 `AFFINITY_MARGIN`에는 둔감하다.

## 결론

**이 loop의 시험 조건 아래에서 (SYS-4, `dynamic_benchmark()` 6개 + Common 3개 + feasible한 Stress 9개):**

1. **회귀는 제거되었다.** first-pass의 "C1 x0.905, TPOT 311 ms / C2 x0.998"은 policy 결함(P)이었다: C1은 destination serving cost를 몰랐고, 두 candidate 모두 migration budget / 이득-비용 gating이 없었으며 C2 demotion은 설계(§17.3)와 달리 upper-tier pressure 조건이 없었다. 수정 후 **어느 시나리오에서도 baseline보다 유의하게 나쁘지 않다** (SYS-1~5 전부 loss 0).
2. **Common Benchmark와 Stress Benchmark에서는 이득이 없다 (parity).** Common 3개에서 baseline SLO 만족률이 1.00이라 이득의 상한이 0이다. 즉 steady-state workload에서 migration layer는 baseline과 같다 (QA1 ★★ = ★★, QA2 ★★★ = ★★★).
3. **이득은 "static placement가 runtime에 stale해지는" workload에서만 있다.**
   - **C2 wins**: `dyn_cold_resident_chat_wave`, `dyn_host_path_contention_kv`, `dyn_idle_kv_holds_hbm`, `dyn_kv_hotset_recency_shift`, `dyn_kv_rotating_hotset`, `dyn_rag_shard_hotset_shift` (6/6). 다른 시나리오 (Common, feasible Stress)는 parity.
   - **C1 wins**: `dyn_cold_resident_chat_wave`, `dyn_host_path_contention_kv`, `dyn_rag_shard_hotset_shift` (3/6). 같은 data class 안에서 hot/cold를 가르는 시나리오 (`idle_kv`, `recency_shift`, `rotating_hotset`)에서는 C1의 개선(x1.1~1.5)이 CI 안이라 parity다. 이것은 설계 문서 §10이 말하는 C1의 한계와 일치한다.
   - C1은 약 10배 적은 migration byte (70~400 GiB vs 1.8~3.2 TiB)로 3개 시나리오의 이득을 얻는다.
4. **조건부 결과이며 과장하면 안 된다.**
   - dynamic 시나리오는 "baseline이 stale해지는 failure mode"를 알고 설계했다. baseline SLO 만족률이 0.26~0.71이고 control에서는 1.00이다 (feasible하지만 stale). 이득은 이 패턴이 실제 서비스에서 얼마나 흔한지에 의존한다.
   - **SYS-5 (Vera Rubin x8)**: 같은 시나리오 크기에서 baseline이 거의 포화(만족률 0.91~1.00)라 dynamic win은 C1/C2 모두 `dyn_host_path_contention_kv` 1개뿐이다. HBM이 큰 시스템에서는 이득이 사라진다. 이는 시나리오를 SYS-5에 맞춰 조정하지 않은 결과다.
   - SYS-1/2 (HBF 없음)에서는 C2 win 6, C1 win 1. 즉 C1의 이득은 HBF 같은 "중간 비용 tier"의 존재에 의존한다.
   - 이득은 migration budget에 민감하다 (sensitivity 표).
5. **QA2는 combined에서 별 등급이 바뀌지 않는다** (★ = ★): worst-case를 baseline 자체가 위반하는 stress 시나리오가 지배한다. dynamic set만 보면 ★ -> ★★ (C1, C2).
6. **QA3(임시 정의: avg HBM occupancy x SLO 만족 비율)**: dynamic에서 baseline 30% -> C1 48% / C2 69%로 오르지만, Common에서는 C1이 41% < baseline 44% (HBM 압력 해소로 occupancy가 줄어드는 것이 이 정의에서는 감점). 정의를 바꾸지 않았다.

**중단 조건 판정**: (i) 충족 (SYS-4, 두 candidate 모두 loss 0, 집계 QA1 CI 하한 > 1, 유의한 win C1 3 / C2 6). 6 iteration 한도 내 3 iteration 사용. "no benefit" 결론은 해당하지 않는다. 다만 위 4번의 조건부 한정과 sensitivity를 함께 보고해야 한다.

### 설계 문서에 미치는 영향 (P-class 수정이 함의하는 것)

1. **Destination Tier Selector 입력 추가 (C1, C2 공통)**: 설계 §8.7 / §13.6의 입력("memory capability, transfer cost")에 **destination의 serving cost(access cost)**를 추가해야 한다. 같은 Memory Registry descriptor(ext_bw, write_bw, latency, near-data primitive, int_bw, compute)와 operation hint(class, shape)에서 도출하며, SLO feasibility 필터 + 서비스 penalty 항으로 쓴다. first-pass의 C1 결함(CXL-PNM attention 경로 TPOT 311 ms 선택)은 이 입력이 없어서 생긴 것이다. Memory Backend I/F(§5.8)에는 "측정-추정 closed loop(§5.9.6)로 보정되는 access-cost 질의"가 필요하다 (현재 simulator는 descriptor만으로 정확한 비용을 안다고 가정: 아래 한계).
2. **Migration budget (C1, C2 공통, §26 항목 8, 11)**: link 시간 기준 token bucket(공유 link의 migration 몫)과 object별 cooldown을 공통 Migration Planner/Scheduler 쪽 요소로 명시해야 한다. bucket 용량보다 큰 단일 이동은 DP1 loop에서 거부되므로, 대형 object(수십~수백 GiB)를 위한 background/staged 이동 경로가 별도로 필요하다.
3. **이득-비용 gating (C2)**: 예상 이득(rate x horizon x 서비스 penalty 감소)이 전송 비용(노출 계수 x 전송 시간)을 넘을 때만 promotion/rebalance. C2 Predictor 출력이 점수(score)가 아니라 **예상 접근 rate**를 내야 한다 (§13.5의 "expected_next_access" 계열).
4. **Demotion의 조건 (C2)**: §17.3대로 "reuse 하락 **+ upper-tier pressure**"를 코드로 강제해야 한다 (first-pass 구현은 pressure 없이 demotion했다).
5. **C1 promotion trigger (§17.2)**: "static affinity상 upper tier 선호 object가 lower tier에 존재" trigger를 구체화한 형태는 "static 추정으로 SLO를 위반하는 residency"다. HBM에 자리가 없으면 static penalty가 큰 차이(hysteresis margin)로 작은 object와 swap한다. Affinity hint에는 sensitivity뿐 아니라 **operation class와 shape(context, concurrency, output tokens, touch bytes)**가 필요하다 (type 이름은 불필요: C1 registry의 type-agnostic 제약은 유지됨).
6. **C1/C2 구분의 재정리**: 이 loop에서 C1과 C2의 실질적 차이는 (a) 같은 class 안에서 hot/cold를 가르는 능력 (C2만), (b) 이동 byte (C1이 ~10배 적음), (c) decision overhead (C1 ~3 ms/run vs C2 ~60~170 ms/run)로 나타났다.

### 한계 / caveat

- 모든 수치는 **[B+C] simulation**이다. [A] 실측이 아니다.
- **Cost estimator가 완전 정보다**: C1/C2의 `AccessCostEstimator`는 simulator의 물리 모델과 같은 식을 descriptor로 계산하므로(테스트로 일치 확인) 추정 오차가 0이다. 실제로는 [A] 측정으로 보정된 추정이며 오차가 있을 것이다. 이득의 상한에 가깝다.
- **dynamic 시나리오는 failure mode를 알고 설계했다** (사용자 지시). 시나리오 설계 중에는 baseline만 실행했고 candidate를 보지 않았으나, 시나리오 선택 자체가 결과를 좌우한다. baseline SLO 만족률이 낮은(0.26~0.71) 시나리오들이며 "baseline feasible"은 goodput > 0과 control 1.00으로 정의했다.
- **long-context cell (320K/b16)**: DRAM 서빙이 TPOT SLO를 넘는 구성을 쓰기 위해 선택했다 (Llama-3.1 공식 128K 초과; stress set은 512K까지 사용).
- **simulator가 모델링하지 않는 것**: hard capacity 제약(HBM이 줄어도 이미 배치된 object는 남음 -> capacity ramp는 baseline을 해치지 못함, M-class 후보이나 baseline에 forced eviction을 넣어야 해서 baseline 약화 금지 규칙과 충돌하여 건드리지 않음), HBM BW shock에서 attention offload가 HBM보다 느려 이득이 없음, link contention의 동시 migration 간섭(노출 계수 0.20 단일 상수), HBF endurance, 완전 simulation 대비 queueing/saturation(QA1이 load에 거의 비례).
- **QA 정의**: QA3는 first-pass 임시 정의 그대로. "saturated"는 사용자 지시("후보 모두 CI 안에서 동일")를 따랐으며 `.claude/skills/evaluation/SKILL.md`의 정의(sweep 최대 load에서 포화)와 다르다. 중단 조건 (i)의 "candidate >= Baseline"은 QA1은 CI parity(비율 + CI >= 1), QA2/QA3는 별 등급 비교로 판정했다. 별 등급이 같아도 수치는 달라질 수 있다 (예: Common QA3 C1 41% < baseline 44%).
- `MATERIAL_REL`(1%)은 평가 쪽 상수다 (tie 판정). 이 값 아래의 일관된 차이는 tie로 본다.
- 전역 정책 파라미터는 모두 설계 선택이며 시뮬레이터 안에 근거 데이터가 없다 (LINK_SHARE 0.25, window 8 s, H 30 s, AFFINITY_MARGIN 2.0). 이득이 가장 민감한 것은 LINK_SHARE/window다.
- 같은 iteration 안에서 구현을 수정한 사례가 두 건 있다 (iteration 1의 C2 demotion destination, iteration 3의 C1 swap 단계화/reserve). 둘 다 해당 시나리오 한 개의 diagnose 관찰에서 나왔고 파라미터 조정이 아니라 로직 결함 수정이다. 로그에 각각 기록했다.

---

## 사후 주석 (orchestrator, loop 종료 후)

- **SYS-5 loader 수정:** loop 종료 후 `model.load_system`이 `custom_hbm`을 paired-GPU 규격(용량 x2, 내부 BW x2, 연산 20%, TDP/3)으로 계산하도록 고쳤다 (SYS-1~4는 값이 동일해 결과 불변). `results/data/SYS-5/qa_result.json`은 수정 후 재생성했다. **`it0`~`it3`의 SYS-5 요약과 console 출력은 수정 전 값**이므로 최종 결과와 직접 비교하지 않는다 (이력 보존).
- 통합 결과 문서: [`../2026-10-02_dp1-qa-evaluation.md`](../2026-10-02_dp1-qa-evaluation.md)
