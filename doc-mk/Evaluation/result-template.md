---
date: YYYY-MM-DD
dp: DPn
candidates: [Candidate A, Candidate B]      # Baseline은 항상 포함
sys_ids: [SYS-n]                            # primary SYS를 첫 번째로
git_rev: <short sha> (clean|dirty)
evidence: { QA1: "[B+C]", QA2: "[B+C]", QA3: "[B+C]", QA4: "[C]" }
status: draft                               # draft | final | superseded
---

# DPn QA Evaluation — <Candidate A> vs <Candidate B> (<topic>)

> 기준 문서: `qa-evaluation-criteria.md`, `common-benchmark.md`, `system-specs.md`, `DPn/benchmark.md`, `DPn/simulation-plan.md`
> 이 문서의 모든 simulation 수치는 Evidence [B+C]이며 [A] 실측이 아니다. (실측이 있으면 해당 수치에만 [A] 표기)

# 1. 시스템 환경

<!-- 작성 가이드: SYS id(primary + 추가), model, precision, git revision(dirty 여부), 재현 command를 적는다. system-specs.md 링크 필수. profile provenance가 ASSUMED인 항목은 표시한다. -->

| 항목 | 값 |
|---|---|
| SYS id | SYS-n (primary), SYS-m |
| Model / precision | |
| Git revision | |
| Seeds / loads | seeds: 11, 23, 37, 53, 71 (>=5) / load x0.5, 1.0, 1.5, 2.0 |
| 재현 command | `cd doc-mk/Evaluation/DPn/sim && python qa_eval.py --system SYS-n` |
| Raw data | `DPn/results/data/<file>` |

시스템 profile 상세: [system-specs.md](../system-specs.md)

# 2. 평가 항목

<!-- 작성 가이드: QA1~QA4와 diagnostic metric을 나열하고 실제 사용한 formula/정의를 적는다. qa-evaluation-criteria.md에 없는 formula는 "임시 정의"로 명시한다. 집계 규칙(geometric mean, worst-case 등)도 적는다. -->

| 항목 | 정의 / formula | 출처 |
|---|---|---|
| QA1 Max SLO Goodput | | criteria §4 |
| QA2 TTFT P99 / TPOT P99 | | criteria §5 |
| QA3 Useful Utilization | | **임시 정의** (해당 시) |
| QA4 Modifiability | | criteria §7 |
| Diagnostic: migration 횟수/bytes, decision overhead, tier occupancy 등 | | DP 전용 |

# 3. 벤치마크 / 시나리오

<!-- 작성 가이드: Common Benchmark와 DP 전용 benchmark(Stress, dynamic 등)를 모두 포함한다. 모든 시나리오를 나열하고 fit label을 부여한다. 제외한 시나리오도 이유와 함께 남긴다. Common만으로 최종 결과를 내지 않는다. -->

| Benchmark set | 시나리오 | 실제 serving 패턴 | Fit label (comparison-valid / infeasible / saturated) | 비고 |
|---|---|---|---|---|
| Common | | | | |
| DP-specific: <name> | | | | |

# 4. 결과

<!-- 작성 가이드: criteria §10 형식(별점 + 값 + Evidence). Baseline 열 필수. 후보 이름은 실제 이름으로 바꾼다. 모든 benchmark set의 시나리오별 표를 포함하고 seed 수, 95% CI, CV를 적는다. 표 숫자는 qa_eval.py 출력에서만 가져온다. -->

## 4.1 최종 QA 표 (Common + DP-specific 통합)

`qa-evaluation-criteria.md` §10 형식: 정량 metric 값 + (Baseline 대비 배수) + 표 아래 시스템 표기.

| QA | 평가 metric | Baseline (T_ref) | Candidate A | Candidate B |
|---|---|---:|---|---|
| QA1 Throughput | Max SLO Goodput (tok/s) ↑ | xxxx | ★★ xxxx (x1.00) [B+C] | |
| QA2 Latency (TTFT) | TTFT P99 (ms) ↓ | xxxx | xxxx (x1.00) | |
| QA2 Latency (TPOT) | TPOT P99 (ms) ↓ | xx | xx (x1.00) | |
| QA2 별점 | TTFT/TPOT 반영 | — | ★★ [B+C] | |
| QA3 Resource Util. | DP별 metric (예: HBM 사용량 GiB ↓) | xxx | ★★ xxx (x1.00) [B+C] | |
| QA4 Modifiability | module / 공수 / 에이전트 비용 | — | ★★ x / x / $x [C] | |

**시스템:** SYS id, GPU/HBM 세대, host link, 탑재 메모리, model/precision, 집계 단위(시나리오 수, 비교 가능 쌍 수). 괄호는 후보 ÷ Baseline, 여러 쌍은 기하평균.

## 4.2 시나리오별 결과 (benchmark set마다 1개 표)

n_seeds = , 95% CI = (t 분포), CV = 

| 시나리오 | Fit | Baseline (±CI) | A (ratio) | B (ratio) | TTFT P99 Base/A/B (ms) | TPOT P99 Base/A/B (ms) | CI 밖 여부 |
|---|---|---:|---:|---:|---|---|---|
| | | | | | | | |

## 4.3 Diagnostic

| 지표 | Baseline | A | B |
|---|---:|---:|---:|
| migration 횟수 | | | |
| migration bytes | | | |
| decision overhead (ms/run) | | | |

## 4.4 Iteration summary

<!-- 작성 가이드: loop가 발동하지 않았으면 "loop 미발동: 모든 후보 >= Baseline"이라고 쓴다. 발동했으면 모든 iteration(나쁜 결과 포함)을 적는다. -->

상세 로그: [iterations/loop-log.md](iterations/loop-log.md)

| Iteration | Class (P/B/S/M/N) | Change | Effect (전체 benchmark 기준) |
|---|---|---|---|
| 0 (initial) | — | — | |
| 1 | | | |

# 5. 결과 분석

<!-- 작성 가이드: diagnostic에 근거한 원인 분석만 쓴다(추측 금지). 후보가 Baseline 미만인 모든 시나리오에 대해 root cause를 적고, 가능하면 P/B/S/M/N class로 분류한다. 이득이 있는 시나리오도 원인을 적는다. -->

| 시나리오 | 후보 < Baseline? | Root cause | Class | 근거 diagnostic |
|---|---|---|---|---|
| | | | | |

# 6. 한계

<!-- 작성 가이드: Evidence level, simulator가 모델링하지 않는 것, 임시 정의, 시나리오 선택 의존성, projection uncertainty를 솔직하게 적는다. -->

1. Evidence: 
2. 미모델링 항목: 
3. 임시 정의: 
4. 시나리오/profile 의존성: 

# 7. 결론

<!-- 작성 가이드: 의사결정에 필요한 진술(채택/보류/재설계), 이득이 특정 benchmark 조건에만 존재하는지와 그 조건, Baseline 미만 결과 포함. max 6 iteration에 도달했으면 "under the tested conditions the architecture shows no benefit over the baseline"를 그대로 쓰고 시도 목록을 적는다. -->

- 결정 관련 진술: 
- 이득이 존재하는 조건 / 존재하지 않는 조건: 
- 다음 단계: 

---

# Checklist before marking final

- [ ] 섹션 1~7이 순서와 제목 그대로 있다
- [ ] front-matter(date, dp, candidates, sys_ids, git_rev, evidence, status)가 채워져 있다
- [ ] 재현 command, seeds(>=5), loads, git revision, raw data 경로가 있다
- [ ] Common Benchmark와 DP 전용 benchmark 결과가 모두 포함되고 최종 QA 표가 둘을 통합했다
- [ ] 모든 시나리오에 fit label이 있고 제외 사유가 적혀 있다
- [ ] 최종 QA 표가 criteria §10 형식이며 Baseline 열이 있다
- [ ] 모든 숫자가 qa_eval.py 출력에서 왔고 Evidence Level이 표기되어 있다 (sim 수치에 [A] 없음)
- [ ] 룰 문서에 없는 formula는 "임시 정의"로 표기했다
- [ ] Baseline 미만 시나리오를 모두 보고하고 root cause를 적었다
- [ ] Baseline-regression loop 발동 여부와 Iteration summary, loop-log.md가 일치한다
- [ ] 중단 조건 (i) 또는 (ii)가 충족되었다 (N_win 포함)
- [ ] QA threshold/SLO/Baseline을 변경하지 않았다
- [ ] 결론이 이득의 benchmark 조건 의존성을 명시한다
