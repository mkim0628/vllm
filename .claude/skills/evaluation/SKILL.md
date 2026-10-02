---
name: evaluation
description: "Use whenever evaluating, benchmarking, simulating or scoring a Design Point candidate (DP1~DP4), writing or updating an evaluation result, running QA1~QA4 scoring, 평가 / 벤치마크 / 시뮬레이션 / QA 별점 work, or touching doc-mk/Evaluation. MANDATORY: follow this skill exactly."
---

# Evaluation Skill (DP1~DP4 공통, 필수 준수)

규칙의 원천: `doc-mk/Evaluation/qa-evaluation-criteria.md` (QA 정의/별점/Evidence). 이 skill은 그 규칙을 바꾸지 않고 **절차와 문서 형식**만 고정한다. 충돌하면 qa-evaluation-criteria.md가 우선.

## Quick start
1. `doc-mk/Evaluation/README.md`와 아래 [사전 체크리스트](#3-평가-전-체크리스트)의 문서를 읽는다.
2. 후보와 DP, primary SYS id(`system-specs.md`)를 정하고 Baseline(T_ref)을 확인한다.
3. simulator/test suite가 통과하는지 먼저 확인한다 (`DP1/sim/test_sim.py`).
4. Common Benchmark + DP 전용 benchmark **둘 다** `qa_eval.py`로 실행한다 (seed >= 5, load sweep).
5. raw 출력을 `DPn/results/data/`에 저장한다. 숫자는 손으로 쓰지 않고 코드 출력에서 옮긴다.
6. 어떤 후보든 Baseline 미만이면 [Baseline-regression loop](#5-baseline-regression-loop)를 돈다.
7. `result-template.md`로 `DPn/results/YYYY-MM-DD_<topic>.md`를 작성한다 (7개 섹션 고정).
8. 마지막 체크리스트(template 말미)를 통과시킨 뒤 status를 final로 한다. commit은 orchestrator만 한다.

## Hard rules (비협상)
- H1. 모든 평가 산출물은 아래 폴더 구조 안에만 만든다. 밖에 만들지 않는다.
- H2. 모든 결과 문서는 `result-template.md`의 7개 섹션을 **순서와 제목 그대로** 사용한다.
- H3. DP의 최종 결과는 **Common Benchmark + DP 전용 benchmark를 합친** 결과다. Common만으로 최종 결론을 내지 않는다.
- H4. 모든 후보를 Common Reference Baseline(T_ref)과 비교한다. 후보가 지는 시나리오는 삭제/숨김/가중치 조정 금지.
- H5. QA 별점 threshold와 SLO는 결과를 본 뒤 바꾸지 않는다.
- H6. config parameter 기반 simulation 출력은 **[B+C]**이다. 실측([A]) 없이 [A]를 주장하거나 sim 숫자를 실측처럼 쓰지 않는다.
- H7. 결과 표의 숫자는 `qa_eval.py` 등 코드로 재생성한 것만 쓴다. 명령, seed(>=5), load, git revision을 반드시 적는다.
- H8. qa-evaluation-criteria.md에 없는 formula는 **임시 정의**로 표시한다.
- H9. 이전 결과/iteration을 덮어쓰거나 지우지 않는다. 대체된 결과는 파일명에 `_superseded`를 붙여 보존한다.
- H10. 시스템 profile 값을 조용히 수정하지 않는다. 새 profile을 추가하고 provenance를 적는다.
- H11. 공통 별점이 거칠어 후보를 구분하지 못할 때 **공통 룰은 바꾸지 않고** `DPn/qa-criteria-dpn.md`에 DP 전용 보조 기준(세부 tier, 집계 규칙, 후보 간 직접 비교)을 둔다. 보조 기준은 별점 산정에 쓰지 않으며, 결과를 본 뒤 정의했으면 `defined_after_first_look`로 공개하고 탐색적 지표로만 취급한다. 별점이 같아도 값이 다르면 항상 값을 병기한다.

## 1. 폴더 구조 (single source of truth)
```
doc-mk/Evaluation/                 # 공통 문서
  qa-evaluation-criteria.md        # QA 정의 (DP1~DP4)
  common-benchmark.md              # Common Benchmark 정의
  system-specs.md                  # 시스템 profile SYS-n (코드: DP1/sim/configs/systems.json)
  result-template.md               # 결과 문서 template
  README.md, CLAUDE.md, tools/
  DPn/                             # DP별 폴더 (n=1..4)
    simulation-plan.md             # (또는 evaluation plan)
    benchmark.md                   # DP 전용 benchmark
    results/
      YYYY-MM-DD_<topic>.md        # 결과 문서 (대체 시 *_superseded.md)
      data/                        # raw json/csv
      iterations/loop-log.md       # Baseline-regression loop 로그
    sim/                           # sim 코드가 있으면 (DP1/sim/)
```

## 2. Evidence 규칙 요약
- [A] 실제 HW/runtime 직접 측정. [B] 문헌/vendor spec (source + 조건 기록). [C] 모델/분석 projection (model, 입력, calibration, validation error, sensitivity 기록).
- Simulator 출력(config parameter 입력)은 [B+C]. 별점과 Evidence는 독립이며 Evidence가 낮다고 별점을 자동으로 낮추지 않는다. 대신 uncertainty와 validation 범위를 적는다.
- 모든 수치 옆에 Evidence Level을 표기한다. 실측 trace/calibration이 있는 입력만 [A]로 쓴다.

## 3. 평가 전 체크리스트
- [ ] `qa-evaluation-criteria.md` 읽음 (QA1~QA4 threshold, §10 최종 표 형식)
- [ ] `common-benchmark.md` 읽음
- [ ] `system-specs.md` 읽음, primary SYS와 추가 SYS id 선택 (이유 기록)
- [ ] `DPn/benchmark.md` 읽음
- [ ] `DPn/simulation-plan.md` 읽음 (후보 정의, N_win 지정 여부 확인, 기본값 3)
- [ ] 각 숫자의 Evidence Level을 정함
- [ ] simulator/test suite 통과 (실패 상태에서 평가 실행 금지)
- [ ] git revision 기록 (`git rev-parse --short HEAD`, working tree가 dirty면 명시)
- [ ] 기존 results/ 확인: 같은 topic 결과가 있으면 덮어쓰지 말고 `_superseded` 처리

## 4. 결과 문서 형식 (result-template.md)
Front-matter: `date, dp, candidates, sys_ids, git_rev, evidence, status(draft|final|superseded)`.
섹션은 아래 번호와 제목을 그대로 쓴다.

| # | 제목 | 반드시 들어갈 내용 |
|---|---|---|
| 1 | 시스템 환경 | SYS id(들), model, git revision, 재현 command. `system-specs.md` 링크 |
| 2 | 평가 항목 | QA1~QA4 + diagnostic metric. 실제 사용한 formula/정의. 룰 문서에 없는 formula는 "임시 정의" 표기 |
| 3 | 벤치마크 / 시나리오 | Common Benchmark와 DP 전용 benchmark(예: DP1 Stress Benchmark, dynamic benchmark) **모두**. 모든 시나리오를 나열하고 fit label(comparison-valid / infeasible / saturated) 부여 |
| 4 | 결과 | §10 형식 최종 QA 표(별점 + 값 + Evidence, **Baseline 열 포함**), 모든 benchmark set의 시나리오별 표, seed 수 / 95% CI / CV, Iteration summary |
| 5 | 결과 분석 | diagnostic에 근거한 원인 분석(추측 금지). 후보가 Baseline 미만인 **모든 시나리오**의 root cause |
| 6 | 한계 | Evidence level, simulator가 모델링하지 않는 것, 임시 정의, 시나리오 선택 의존성 |
| 7 | 결론 | 의사결정에 필요한 진술, 이득이 특정 benchmark 조건에만 있는지(어느 조건인지), 다음 단계 |

Fit label 정의: **comparison-valid** = Baseline이 SLO를 만족(feasible)하고 후보와 비교 가능. **infeasible** = Baseline도 SLO 불가(goodput 0 등), 비교에서 제외하되 목록에는 남김. **saturated** = Baseline은 feasible하지만 **모든 후보(Baseline 포함)가 95% CI 이내로 동일**하여 시나리오가 후보를 판별하지 못함 (집계에는 포함, 이득 근거로는 쓰지 않음). 별개로, simulator에 queueing/saturation 모델이 없어 QA1이 load에 비례할 때는 결과 문서의 '한계'에 적는다 (fit label이 아니다).
별점 집계 규칙은 해당 DP의 plan 문서를 따른다 (DP1: QA1 = 시나리오별 ratio의 geometric mean, QA2 = worst-case, QA3 = 임시 정의 사용 시 표기). 집계는 comparison-valid 시나리오 기준이며 제외한 시나리오와 이유를 적는다.

## 5. Baseline-regression loop
**Baseline**: DP별 Common Reference Baseline(T_ref). DP1 = **Baseline-static** (As-Is proxy, 공통 initial placement 후 migration 없음, tier 순서 고정). Baseline보다 낮은 후보는 구조 도입 근거가 없다.

**Trigger** (primary SYS 기준, 하나라도 해당): comparison-valid 시나리오 중 후보 < Baseline / 집계 QA1 ratio < 1.00 / QA2 별점 또는 값이 Baseline보다 나쁨 / QA3 Baseline보다 낮음. 95% CI 안이면 N(noise)으로 분류한다.

**각 iteration**
1. (a) 진단: diagnostic으로 root cause를 하나로 분류.
   - **P** policy/architecture 결함, **B** benchmark가 As-Is의 의도된 failure mode를 건드리지 않음(benchmark-fit), **S** system profile/config 비현실적, **M** simulator cost-model gap, **N** noise(95% CI 내).
2. (b) **실행 전에** 가설과 계획 변경을 `DPn/results/iterations/loop-log.md`에 기록(pre-registration). 실행 후 가설을 고쳐 쓰지 않는다.
3. (c) **한 class의 변경만** 적용한다.
4. (d) **전체 benchmark set**(Common + DP 전용)을 관련 **모든 SYS**에서 재실행한다. 실패 시나리오만 재실행 금지.
5. (e) 나쁜 결과를 포함해 전부 loop-log에 기록한다.
6. (f) 계속/중단 결정을 기록한다.

**Class별 허용 변경**
| Class | 허용 | 조건 |
|---|---|---|
| P | policy/architecture 수정 | design 문서와 일치. 특정 시나리오 special-case 금지 |
| B | 시나리오 추가/재설계 | 현실 serving 패턴을 명시하고, **Baseline이 FEASIBLE(SLO 만족)**이면서 static placement가 suboptimal해지는 workload. 기존 시나리오와 결과는 유지 |
| S | `systems.json`에 profile 추가/수정 | provenance 기록. profile 내부 값 무기록 수정 금지 |
| M | cost model 수정 | 물리적/실측 근거 + Evidence level 표기 |
| N | seed 추가 | 기존 seed 결과 유지 |

**금지 (anti-cherry-picking)**
- QA threshold 변경 / SLO 변경
- 지는 시나리오나 이전 iteration 삭제/숨김
- 시나리오별 policy 상수 tuning
- Baseline-static을 약하게 변경
- Baseline에게 infeasible한 시나리오를 만든 뒤 승리 주장
- 최고 iteration만 보고
- 한 iteration에서 여러 class를 섞어 변경

**중단 조건**
- (i) 모든 comparison-valid 시나리오와 집계 QA에서 후보 >= Baseline (CI 내 = parity) **그리고** 최소 N_win개(plan이 정함, 기본 3) 시나리오에서 통계적으로 유의한 이득(> 95% CI) → 결과 문서 작성.
- (ii) 최대 6 iteration 도달 → **중단하고 user에게 escalate**. 문장: "under the tested conditions the architecture shows no benefit over the baseline". 시도한 변경 목록을 함께 제시하고 조용히 계속 반복하지 않는다.

**결과 문서 요구**: §4에 'Iteration summary' 표(iteration, class, change, effect)와 loop-log.md 링크. §7에 이득이 특정 benchmark 조건에만 존재하는지, 어떤 조건인지 명시. loop를 돌지 않았다면 "loop 미발동: 모든 후보 >= Baseline"이라고 쓴다.

## 6. Multi-agent / 병렬 작업
- 파일 소유권을 **겹치지 않게** 분할한다 (docs / sim code / skill 등). 같은 파일을 두 agent가 수정하지 않는다.
- **commit/push는 orchestrator만** 한다. 하위 agent는 commit하지 않는다.
- 결과 숫자는 `qa_eval.py`로 재생성한다. 손으로 입력하지 않는다.
- 병렬 작업 후 orchestrator가 코드 변경 -> 전체 재실행 -> 문서 순서로 통합한다 (문서가 오래된 코드 결과를 인용하지 않게).

## 7. 재현성
- 명령 예: `cd doc-mk/Evaluation/DP1/sim && python qa_eval.py --system SYS-4`
- seed >= 5 (DP1 기본 11, 23, 37, 53, 71), load sweep (예: x0.5 / 1.0 / 1.5 / 2.0), 95% CI, CV 기록.
- git revision(dirty 여부 포함)과 raw 출력(json/csv)을 `DPn/results/data/`에 저장하고 결과 문서가 파일명을 참조한다.
- 같은 명령 + 같은 revision이면 같은 숫자가 나와야 한다. 아니면 결과를 final로 하지 않는다.

## 8. 작성 관례
- 한국어, 기술 용어는 영어. 간결하고 정확하게.
- 숫자에는 단위와 Evidence 표기. "~정도" 같은 모호한 표현 대신 값과 CI.
- 원인 분석은 diagnostic(tier별 access, migration 횟수/bytes, decision overhead 등)을 인용한다.
- 새 QA가 필요하면 결과 문서가 아니라 qa-evaluation-criteria.md §9 형식으로 먼저 추가한다 (결과 보기 전에).
