# Common Benchmark (DP1~DP4 공통)

> 적용 범위: **DP1 ~ DP4 공통**
>
> 이 문서는 `qa-evaluation-criteria.md` 8장의 Common Benchmark Profile을 실행 가능한 규칙으로 확장한다. **별점 threshold와 QA 정의는 여기서 다시 정의하지 않는다** (`qa-evaluation-criteria.md` 참조).

---

# 1. 목적

- QA1(Max SLO Goodput), QA2(TTFT/TPOT), QA3(Resource Utilization)의 **absolute 기준을 calibration**하고, DP 간 / 후보 간 결과를 같은 workload에서 비교 가능하게 한다.
- DP별 특수 workload(stress, 동적 시나리오 등)와 분리한다. Common Benchmark는 "모든 DP가 반드시 한 번은 통과시켜야 하는 공통 입구"다.

# 2. 고정 파라미터

| 항목 | 값 | 비고 |
|---|---|---|
| Model | Llama-3.1-70B (`llama_3_1_70b`) | `system-specs.md` G.5 |
| Precision | BF16 | dtype_bytes = 2 |
| Input length | 8K tokens (8192) | |
| Output length | 256 tokens | |
| Prefix reuse | baseline에서는 제거 / 통제 | 아래 3장 |
| Workload | deterministic distribution | 동일 seed, 동일 request 시퀀스 |
| Load | request-rate / concurrency sweep | 5장 |
| SLO | TTFT P99 <= 2 s, TPOT P99 <= 50 ms | QA2 ★★★ 경계와 동일 |
| System | **SYS-id 필수** | 6장 |

위 값은 결과를 본 뒤 조정하지 않는다. 변경이 필요하면 새 버전의 Common Benchmark로 취급하고 이전 결과와 비교하지 않는다.

## 2.1 Common scenarios (CB-1 ~ CB-3)

위 고정 파라미터(Llama-3.1-70B BF16, 8K in / 256 out, batch 32, SLO)를 공유하고 **메모리 압박 양상과 데이터 종류만** 다른 공통 시나리오 집합이다. 모든 DP가 자기 구조에서 이 3개를 실현하고 같은 SLO / T_ref 규칙으로 측정한다. 공통 별점(QA1~QA3)은 이 집합에서만 산출한다.

| ID | 시나리오 (DP1 코드명) | 무엇인가 | 왜 필요한가 (탐지하는 As-Is 약점) | workload knob |
|---|---|---|---|---|
| CB-1 | `cb_kv_8k_b32` | KV만, 정상 상태, 용량 압박 고정 | 정적 배치가 fast tier 초과분을 느린 tier로 흘릴 때의 TPOT 악화 | KV 100%, ctx 8K, out 256, batch 32, 40 objs, 압박 = tight (DP1: HBM x0.12) |
| CB-2 | `cb_kv_8k_b32_ramp` | CB-1과 같은 KV, 압박이 시간에 따라 점진 증가 | 시간에 따라 필요한 배치가 바뀌는데 정적 배치는 따라가지 못함 | KV 100%, 8K/256, batch 32, 40 objs, 압박 = ramp (DP1: HBM x0.2, phase = capacity_ramp) |
| CB-3 | `cb_mixed_8k_b32` | KV + LoRA + MoE + Agent/Tool 데이터 혼합, 용량 압박 고정 | data type을 구분하지 않는 관리의 한계 (QA4 근거) | KV 50 / LoRA 15 / MoE 15 / Agent 10 / Tool 10 %, 8K/256, batch 32, 48 objs, phase = bimodal, 압박 = tight (DP1: HBM x0.12) |

- 위 표는 **workload 수준 정의**다. "압박"을 만드는 방법(DP1은 `hbm_capacity_mult`로 HBM 축소)은 3장에 따라 각 DP가 정하고 자기 benchmark.md에 비율을 명시한다.
- 시나리오 ID와 코드명 대응은 DP별 realization 표(8장)에 둔다. DP1 정의 단일 소스는 `DP1/sim/scenarios.py::common_benchmark()`.
- 시나리오 추가는 허용하되 기존 CB-n을 삭제/수정하지 않는다 (SKILL H4, H5). 아직 어떤 DP도 실현하지 않은 제안은 "proposed (not yet realized by any DP)"로 표기한다. 현재 제안 없음.

# 3. 각 DP가 바꿀 수 있는 것 / 없는 것

| 구분 | 항목 |
|---|---|
| **고정 (변경 불가)** | model, precision, input/output length, deterministic workload, SLO, sweep 방식, 반복/통계 규칙, baseline의 prefix reuse 통제 |
| **DP가 정의 (자유)** | serving framework / deployment topology (DP1: vLLM 중심, DP2: llm-d + vLLM worker, DP3: 해당 DP runtime, DP4: Agent framework + serving runtime), SYS-id 선택, load sweep의 구체적 grid, 후보 구조, Common Reference Baseline의 구현 |
| **DP가 실현 시 추가 가능** | 메모리 계층이 의미를 갖도록 하는 자원 제약 (예: DP1은 HBM 용량을 축소해 계층이 드러나게 함. 축소 비율은 benchmark 문서에 명시) |
| **금지** | SLO 완화, 입출력 길이 변경, baseline에만 유리한/후보에만 유리한 prefix reuse 설정, 결과 확인 후 파라미터 조정 |

Prefix reuse는 baseline에서 제거/통제한다. 후보가 prefix reuse 계열 기능을 쓰는 경우 baseline과 같은 조건으로 통제하거나, 켠 결과를 **별도 행**으로 분리 보고한다.

# 4. Common Reference Baseline (T_ref)

- **Common Reference Baseline** = 해당 DP가 개선 대상으로 삼는 현재(As-Is) 구조. 후보와 **같은 SYS-id, 같은 workload, 같은 SLO**에서 측정한다.
- **T_ref = Common Reference Baseline의 Max SLO Goodput** (QA1 별점의 분모, `qa-evaluation-criteria.md` 4.3).
- 각 DP는 benchmark.md에 다음을 정의해야 한다.

| 항목 | 내용 |
|---|---|
| Baseline 구조 | 무엇이 As-Is인가 (예: DP1 = vLLM HBM + 정적 DRAM swap/offload) |
| Baseline 구현 | 코드/설정 위치, revision |
| 사용 SYS | baseline과 후보가 같은 SYS-id를 쓰는지 (후보 전용 메모리가 baseline에 없는 경우 baseline은 해당 메모리를 사용하지 않는 것으로 명시) |
| T_ref | 값, 단위(output token/s), 측정 조건, Evidence |
| SLO 충족 여부 | Baseline이 SLO를 만족하지 못하면 해당 시나리오는 `infeasible`로 flag (DP1 benchmark.md 3장 규칙을 따른다). 조용히 제외하지 않는다 |

# 5. Load sweep과 반복 규칙

1. **Load sweep**: offered load(request-rate 또는 concurrency)를 낮은 값에서 saturation 이후까지 증가시킨다. 각 point에서 SLO를 만족한 request의 output token만 세어 SLO Goodput을 구하고, **sweep 최대값을 Max SLO Goodput**으로 한다 (QA1).
2. sweep grid는 baseline과 후보에 **동일**하게 적용한다. peak가 grid 끝에 있으면 grid를 확장한다 (peak를 놓친 결과는 무효).
3. **측정(Evidence A)**: 동일 SW revision, 동일 model/precision/workload/parallelism, 고정 warm-up, **Runs >= 5**, Median, P95/P99, 95% CI, CV를 보고한다.
4. **Simulation(Evidence B+C)**: seed를 바꿔 >= 5 runs, 같은 통계를 보고한다. 단일 seed 결과로 별점을 매기지 않는다. 결정론적 시뮬레이터라도 seed 간 분산(workload 생성)은 보고한다.
5. CV가 크거나 95% CI가 ★ 경계(0.90 / 1.10 x T_ref)를 걸치면 별점을 확정하지 말고 "경계 불확실"로 표기한다.
6. 별점 threshold는 결과를 본 뒤 조정하지 않는다. Common Benchmark 실측 후 absolute TPS 경계도 함께 기록한다 (`qa-evaluation-criteria.md` 4.3).

# 6. SYS-id 요구

- 모든 Common Benchmark 결과는 **SYS id + model + config 파일 git revision**을 명시한다 (`system-specs.md` 1장).
- SYS 값은 Evidence [B]이므로 SYS 기반 simulation 결과는 [B+C]이며 [A]로 쓰지 않는다.
- 결과 비교는 같은 SYS-id 안에서만 한다. 다른 SYS 간 비교는 "시스템 민감도"로 별도 제시한다.

# 7. DP-specific benchmark와의 관계

~~~text
최종 결과 = Common Benchmark + DP-specific Benchmark
~~~

| 구분 | 위치 | 목적 | 산출 |
|---|---|---|---|
| Common Benchmark | 이 문서 | 공통 QA rating, DP 간 calibration | QA1~QA3 별점 (T_ref 기준) |
| DP-specific Benchmark | `DPn/benchmark.md` | 해당 DP의 trade-off / failure mode 관찰 (공통 시나리오는 여기 다시 정의하지 않음) | diagnostic metric, QA4 근거 |

공통 별점은 Common Benchmark에서만 산출한다. DP-specific 결과는 diagnostic으로 보고하며 공통 별점 계산에 섞지 않는다 (`qa-evaluation-criteria.md` 11장 규칙 8, 9).

# 8. How a DP realizes the common profile

| DP | 실현 문서 | Serving 구조 | 상태 |
|---|---|---|---|
| DP1 | CB-1~3 = `cb_kv_8k_b32`, `cb_kv_8k_b32_ramp`, `cb_mixed_8k_b32` (`scenarios.common_benchmark()`). DP 전용 시나리오: `DP1/benchmark.md` | vLLM 중심 (simulator) | 실현됨 (3/3) |
| DP2 | CB-1~3 실현 계획: `DP2/benchmark.md` 2장. DP 전용: `DP2/benchmark.md` | P/D 노드 (llm-d + vLLM worker, simulator 확장 필요: `DP2/simulation-plan.md`) | 계획 (미실현) |
| DP3 | CB-1~3 실현 TBD. DP 전용: `DP3/benchmark.md` | TBD | TBD |
| DP4 | CB-1~3 실현 TBD. DP 전용: `DP4/benchmark.md` | TBD | TBD |

각 DP 문서는 2.1장의 CB-1~3을 모두 실현해야 하며(못 하면 사유 명시), 최소한 다음을 포함해야 한다: (1) 2장 고정 파라미터를 어떻게 구현했는지, (2) 3장의 자유 항목 선택, (3) 4장 Baseline 정의와 T_ref, (4) 사용 SYS-id, (5) sweep grid와 반복 횟수.

# 9. 관련 문서

- `qa-evaluation-criteria.md` — QA 정의, 별점, Evidence
- `system-specs.md` — SYS-id, model spec
- `README.md` — 폴더 안내
