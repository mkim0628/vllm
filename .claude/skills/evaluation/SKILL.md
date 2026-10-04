---
name: evaluation
description: "Use whenever evaluating, benchmarking, simulating or scoring a Design Point candidate (DP1~DP4), writing or updating an evaluation result, running QA1~QA4 scoring, 평가 / 벤치마크 / 시뮬레이션 / QA 별점 work, or touching doc-mk/Evaluation. MANDATORY: follow this skill exactly."
---

# Evaluation Skill (DP1~DP4 공통, 필수 준수)

규칙의 원천: `doc-mk/Evaluation/qa-evaluation-criteria.md` (QA 정의/별점/Evidence). 이 skill은 그 규칙을 바꾸지 않고 **절차와 문서 형식**만 고정한다. 충돌하면 qa-evaluation-criteria.md가 우선.

## Quick start
1. `doc-mk/Evaluation/README.md`와 아래 [사전 체크리스트](#3-평가-전-체크리스트)의 문서를 읽는다.
2. 후보와 DP, 평가할 세대별 SYS 집합(`system-specs.md`, DP1 기본 SYS-H100/B200)을 정하고 Baseline(T_ref)을 확인한다.
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
- H11. 공통 룰 문서는 바꾸지 않는다. 공통 별점이 후보를 구분하지 못하면 `DPn/qa-criteria-dpn.md`에 세부 tier·집계·직접 비교를 두는 것까지는 자유지만, **DP 전용 별점을 공식으로 쓰는 것은 사용자가 결정했을 때만** 허용한다(criteria rule 2의 의도적 예외). 이 경우 (a) 공통 별점을 항상 병기, (b) 경계 값 sensitivity 표 필수, (c) 결과를 본 뒤 정의했으면 `defined_after_first_look`로 공개, (d) 한계·결론에 '별점 차이가 경계 선택에 의존함'을 명시한다. 별점이 같아도 값은 항상 병기한다.
- H12. **결과 문서는 §0 최종 요약으로 시작한다**(발표용). 시스템은 **통합 결과 하나**로 낸다(H19). 순서: (0.1) **QA별 x 후보(C1, C2) 표** — 칸마다 별점 + 그 QA의 정량 평가 지표 값(Baseline 대비 배수/승무패, 지연 P50/P95/P99, 활용률·링크 점유, module·공수·에이전트 비용 등) + Evidence 라벨, (0.2) **trade-off의 특징과 왜 그렇게 나오는지**(메커니즘과 근거 수치, 서술형), (0.3) 선택과 근거, (0.4) 선택 구조의 부족한 부분과 보완 설계, (0.5) **어떤 시나리오를 고려했는지를 도메인을 모르는 사람이 이해하도록 서술형으로**(예: hotness가 쏠린/고른 경우, 데이터 종류 KV/LoRA/MoE/RAG별, 자원 조건 변화, 시나리오 수·비교 불가 쌍 수, 아직 없는 시나리오 명시). 분류표로 나열하지 않고 대표 예만 든다. 전체 시나리오는 4장에 두고 0장에서 나열하지 않는다. 0장은 생성기가 데이터에서 만든다.
- H13. **선택 로직(필수 명시).** DP별 QA 우선순위를 `DPn/qa_priority.json`에 둔다(사용자 확정 전에는 status를 "proposal"로 표시하고 결과에도 그대로 쓴다). 규칙(`tools/dp_selection.py`, 소유자 결정): **별 합계가 높은 후보**가 선택되고, **합계가 같을 때만** 우선순위 위에서부터 처음으로 별이 갈리는 QA가 결정한다. 여러 시스템은 통합 결과(H19)에 같은 규칙을 쓴다. 우선순위를 뒤집었을 때의 결과(결정 민감도)와, 별점 경계가 결과를 좌우하는 곳(경계 근처 값)을 함께 적는다. 점수가 아니라 선택 근거를 문장으로 쓴다.
- H14. **보완 설계.** 선택한 후보의 약점(QA별 별점·비용·리스크 근거 수치 포함)마다 보완 택틱을 표로 제안하고 각 택틱의 검증 상태([B] 구현·측정됨 / [C] 논증·미구현)를 적는다. 미구현 택틱의 효과를 수치로 주장하지 않는다. 택틱 제안은 별도 PPT 1장으로 낸다.
- H15. **PPT 산출물.** (a) DP별 결과 deck(`DPn/DPn-appendix-qa-result.pptx`): ① 결과 표(H24 형식) + 시스템 간략 정보 + 선택 근거, ② QA별 **왜 그런 값이 나왔나**(수치 · 이유 · 근거 시나리오/측정값; 2장 이내), ③ 커버한 시나리오(서술형, 비교 가능/포화/불가 쌍 수). 이유는 데이터에서 직접 뽑은 수치로 쓰고, 한 시나리오 진단에서 일반화한 것은 그렇게 표기한다. (b) 보완 설계 택틱 슬라이드 1장. `tools/gen_dp_pptx.py`로 데이터에서 생성하고 `doc-mk/DPn/`에 둔다. 슬라이드의 숫자는 결과 문서와 같은 소스(생성기)를 쓴다.
- H16. **수치를 원하는 결론에 맞춰 조정하지 않는다.** 사용자가 "조금 조작해도 된다"고 해도 따르지 않는다. 결과가 마음에 안 들 때 허용되는 것은 (i) 평가 정의의 누락·오류 수정(예: 비용 항목 추가, 사유와 이전 정의를 문서에 기록), (ii) 공개된 가정의 변경과 그 민감도 보고, (iii) 시나리오 추가(실패한 것도 유지)뿐이다. 비용 항목을 넣었는데도 후보가 지배(dominate)하면 그것이 결론이다 — trade-off는 QA4·비용 쪽에 있다고 쓴다. 정의를 바꾸면 이전 값과 바뀐 별점을 결과 문서 한계에 적는다.
- H17. **모델 오차 sweep.** 후보가 estimator/predictor에 의존하면 오차 e(lognormal sigma) 0/0.2/0.4/0.6 sweep을 보고한다(`DP1/sim/epsilon_sweep.py`, 정책 상수 재조정 금지). break-even이 없으면 "이 오차 모델에서는 없음"으로, 오차 모델이 한 종류뿐임을 한계에 적는다.
- H18. **Benchmark 문서 구조.** Common Benchmark의 시나리오(CB-n)는 `doc-mk/Evaluation/common-benchmark.md`에 정의한다(workload 수준: ID, 한 줄 설명, 노브). DP 전용 시나리오는 `DPn/benchmark.md`에만 둔다. 모든 benchmark 문서는 **시나리오당 한 줄**(이름 | 무엇인가 60자 이내 | 드러내는 As-Is 약점 | 핵심 파라미터 짧게)이며 상세 config는 코드/생성 데이터를 가리킨다. 시나리오 한 줄 설명은 `Scenario.brief`, 결과 문서 §3도 이를 쓴다.
- H19. **시스템은 메모리 세대 축으로 평가한다.** 6종 메모리가 모두 있는 profile을 세대별로 둔다(정의 SYS-A100: HBM2e/PCIe4, SYS-H100: HBM3/PCIe5, SYS-B200: HBM3e/PCIe5, SYS-VR: HBM4/PCIe6; `system-specs.md`). 한 시스템만의 결과를 주 결과로 쓰지 않는다: 여러 시스템은 **통합 결과 하나**로 낸다(`DP1/sim/merge_systems.py`: (시나리오, 시스템) 쌍이 집계 단위, 별점·선택은 통합 결과 기준). 시스템별 단독 결과는 일관성 확인용으로 4장에 두고 0장에는 매트릭스로 내지 않는다. DP1의 평가 시스템은 **SYS-H100, SYS-B200**(통합)이다(SYS-A100, SYS-VR은 소유자 결정으로 제외, profile은 유지). 구 SYS-1~5는 legacy(메모리 부분집합 ablation). 규격은 SPEC/PUBLIC/ASSUMED를 필드별로 표기하고, 확인하지 못한 값은 ASSUMED로 둔다. 신규 memory는 과거 세대가 없으므로 link 세대 스케일로만 표현하고 그 가정을 적는다.
- H24. **결과 표 형식은 룰 문서 §10을 따른다.** QA별 **정량 metric 값**을 쓰고 괄호에 **Baseline 대비 배수(후보 ÷ Baseline)**를 적는다. 열은 `QA | 평가 metric(↑/↓ 좋음) | Baseline | 후보들`, **Latency는 TTFT와 TPOT를 별도 행**으로 보고하고(P99와 P50), 별점은 별도 행이나 값 옆에 둔다. 여러 시나리오·시스템을 합칠 때는 쌍별 값의 **기하평균**(절대값과 배수가 모순되지 않음)을 쓴다. **표 바로 아래에 평가한 시스템**(SYS id, GPU/HBM 세대, model/precision, 집계 쌍 수)을 적고, **메모리 구성**(각 메모리의 용량, host 연결 방식과 PCIe/CXL 세대, 대역폭, 연산 능력(TFLOPS)과 지원 연산)을 결과 문서와 PPT에 함께 싣는다. 시뮬레이터가 반영한 것과 반영하지 않은 것(예: HBF endurance)을 명시한다. 이름은 **Samsung Custom HBM(ScHBM)**으로 쓴다(`custom_hbm`은 내부 id). QA4처럼 Baseline이 없는 metric은 `—`. 이 형식은 결과 문서 §0.1, §4.1, 발표 PPT 모두에 같게 적용한다(생성기 `final_qa_table`).
- H20. **QA3(자원)는 자원 사용량만 잰다 — 성능을 섞지 않는다.** DP1: QA3 = **HBM 사용량**(시간 평균 점유 GiB)의 Baseline 대비 비율(낮을수록 좋음), 별은 절감 배수(1/비율)로 0.95/1.25 경계. 성능÷비용 같은 효율 지표는 QA1/QA2와 겹치므로 별점에 쓰지 않는다. 풀(전 메모리 합) 활용률은 이동이 총량을 바꾸지 않아 후보 간 같고(DP1: 처리량과 상관 0.99) 진단으로만 둔다. 어느 tier로 보냈는지는 보조로 비용 가중 점유(`sim/cost_model.py`, DRAM 대비 상대 $/GiB, ASSUMED, HBM 가중 3배/5배/10배 민감도)를 병기한다. 자원 지표는 '비우되 성능이 나빠지는 정책'이 유리하므로 QA1/QA2와 함께 읽고, 지표 정의를 결과를 본 뒤 바꾸면 선택이 바뀌는지 문서에 명시한다. 공통 QA 문서는 바꾸지 않는다. 이동 비용은 H22의 간섭 모델로 지연·처리량에 반영한다.
- H23. **QA2는 TTFT와 TPOT를 따로 보고한다**(P50/P95/P99 개선 배수의 geomean을 각각). 별점은 6개를 합친 값을 쓰되 두 값을 항상 병기하고, 데이터 종류별로 어느 쪽이 영향을 받는지(RAG/Agent/Tool은 TTFT, LoRA/MoE는 TPOT, KV는 둘 다) 설명한다.
- H21. **QA4는 세 sub-metric이다.** (M1) 변경 module 수, (M2) 개발 공수(man-month), (M3) 코드 에이전트 토큰 **비용(금액)** — 모델 tier에 따라 토큰 수와 금액의 순위가 달라질 수 있으므로 금액으로 비교한다. 변경 시나리오(신규 memory / data type / policy / event)를 실제로 구현해 module/LOC를 측정하고, 공수·비용은 가정 상수로 계산하되 **측정 전에 사전 등록**(`DPn/qa4-preregistration.md`: 시나리오, 공식, 별 경계, 집계 규칙)한다. QA4 별 = 세 sub-star의 중앙값, 세 값을 모두 보인다. sub-star는 **시나리오 평균값**에 기준을 적용한다(최악값 집계는 공유 module 시나리오 하나가 결과를 정해 신호를 가리므로 쓰지 않는다. 소유자 결정, 결과를 본 뒤 변경이라 `defined_after_first_look`). 가정 상수 민감도(낙관/비관)와 구조 대안을 함께 보고한다. 증거는 [B+C]이며 실제 에이전트 세션 측정이 아님을 한계에 적는다.
- H22. **이동 비용은 시뮬레이터에서 지연·처리량에 반영한다(링크 간섭 모델).** 이동이 쓴 링크 시간만큼 해당 tier의 서빙 대역폭을 줄인다(HBM 제외, 상한 90%, `simulator.py` `link_interference`). 이동량이 큰 후보의 비용이 QA1/QA2에 드러나지 않으면 모델 결함으로 보고 수정한다. 모델을 수정하면 H16(i)에 따라 사유와 수정 전후 값을 `qa-criteria-dpn.md`에 기록하고 수정 전 결과를 `results/data/pre_<이름>/`에 보존한다(H9).

## 1. 폴더 구조 (single source of truth)
```
doc-mk/Evaluation/                 # 공통 문서
  qa-evaluation-criteria.md        # QA 정의 (DP1~DP4)
  common-benchmark.md              # Common Benchmark 정의
  system-specs.md                  # 시스템 profile SYS-n (코드: DP1/sim/configs/systems.json)
  result-template.md               # 결과 문서 template
  README.md, CLAUDE.md
  tools/                           # gen_*_result.py, gen_dp_pptx.py, dp_selection.py
  DPn/                             # DP별 폴더 (n=1..4)
    simulation-plan.md             # (또는 evaluation plan)
    benchmark.md                   # DP 전용 benchmark
    qa-criteria-dpn.md, qa_priority.json   # DP 전용 별점 기준(사용자 결정 시), QA 우선순위
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
- [ ] `system-specs.md` 읽음, 세대별 SYS 집합 확인 (H19), 추가/제외 SYS는 이유 기록
- [ ] `DPn/benchmark.md` 읽음
- [ ] `DPn/simulation-plan.md` 읽음 (후보 정의, N_win 지정 여부 확인, 기본값 3)
- [ ] 각 숫자의 Evidence Level을 정함
- [ ] simulator/test suite 통과 (실패 상태에서 평가 실행 금지)
- [ ] git revision 기록 (`git rev-parse --short HEAD`, working tree가 dirty면 명시)
- [ ] 기존 results/ 확인: 같은 topic 결과가 있으면 덮어쓰지 말고 `_superseded` 처리

## 4. 결과 문서 형식 (result-template.md)
Front-matter: `date, dp, candidates, sys_ids, git_rev, evidence, status(draft|final|superseded)`.
섹션은 아래 번호와 제목을 그대로 쓴다 (0번은 DP 결과 문서에 필수).

| # | 제목 | 반드시 들어갈 내용 |
|---|---|---|
| 0 | 최종 요약 | H12 형식(QA 표, trade-off, 선택 근거, 보완 설계, 대표 benchmark). 생성기가 데이터에서 만든다 |
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

**Trigger** (세대별 SYS 중 어느 하나라도, 하나라도 해당): comparison-valid 시나리오 중 후보 < Baseline / 집계 QA1 ratio < 1.00 / QA2 별점 또는 값이 Baseline보다 나쁨 / QA3 Baseline보다 낮음. 95% CI 안이면 N(noise)으로 분류한다.

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
- 명령 예: `cd doc-mk/Evaluation/DP1/sim && python qa_eval.py --system SYS-B200`
- seed >= 5 (DP1 기본 11, 23, 37, 53, 71), load sweep (예: x0.5 / 1.0 / 1.5 / 2.0), 95% CI, CV 기록.
- git revision(dirty 여부 포함)과 raw 출력(json/csv)을 `DPn/results/data/`에 저장하고 결과 문서가 파일명을 참조한다.
- 같은 명령 + 같은 revision이면 같은 숫자가 나와야 한다. 아니면 결과를 final로 하지 않는다.

## 8. 작성 관례
- 한국어, 기술 용어는 영어. 간결하고 정확하게.
- 숫자에는 단위와 Evidence 표기. "~정도" 같은 모호한 표현 대신 값과 CI.
- 원인 분석은 diagnostic(tier별 access, migration 횟수/bytes, decision overhead 등)을 인용한다.
- 새 QA가 필요하면 결과 문서가 아니라 qa-evaluation-criteria.md §9 형식으로 먼저 추가한다 (결과 보기 전에).

## 9. Ablation(구성요소 제거) 규칙
- 선정된 구조의 핵심 구성요소(예: C1 Data-Memory Affinity)는 제거 변형을 같은 시나리오·시스템·seed로 실행해 비교한다 (`DP1_C1_AFFINITY=full|none|no_score|no_promo`, `loop_run.py --final --tag ablation/<mode>`, `merge_systems.py --tag`).
- 대조군(`full`)은 본 결과와 수치가 일치해야 한다. 불일치하면 ablation 결과를 쓰지 않는다.
- 제거 변형의 별 합계와 선정 결과를 함께 보고한다 ("제거 시 순위가 바뀌는가"가 보완 설계 근거). 효과가 어느 하위 메커니즘에서 오는지(score vs promotion) 분해해 적는다.
- 시스템 슬라이드에는 GPU FP16 dense 연산량(GPU 1개당)을 참고로 병기해 PNM/ScHBM 연산량과 비교 가능하게 한다.

## 10. 별점 경계의 근거와 꼬리 지표 점검
- 별점 경계마다 근거를 문서화한다(`DPn/qa-criteria-dpn.md`의 "별점 경계의 근거" 절). **하한(★/★★)은 Baseline-vs-Baseline 잡음 측정**(겹치지 않는 seed 묶음, 같은 집계; DP1: `sim/star_basis.py`)으로, **상한(★★/★★★)은 환산**(GPU 수/HBM GiB/ms)으로 의미를 붙이고 정책 선택으로 남는 부분을 그대로 적는다. 측정이 안 되는 근거를 측정된 것처럼 쓰지 않는다. 상한을 바꿨을 때 선택이 어디서 바뀌는지(민감도)를 함께 싣는다. 경계는 결과를 본 뒤 바꾸지 않으며, 바꾸려면 소유자 결정 후 새 rating 버전으로 기록한다.
- 평균/중앙값 개선과 함께 **P99 꼬리를 쌍별로 점검**한다(Baseline보다 나쁜 쌍 수와 최악 쌍). 평균이 좋아도 꼬리가 나쁘면 Baseline-regression loop를 돈다. 사전 등록한 판정 규칙이 "이득이 0인 퇴화 해"를 허용하는지 등록 시점에 검토한다.
- **Oracle 달성률 기준(DP1 QA1):** 상한 대신 시나리오별 Oracle 대비 이득 달성률 `(후보-Baseline)/(Oracle-Baseline)`을 쓸 수 있다(`sim/oracle_run.py --ideal`, `sim/capture_analysis.py --ideal`). Oracle은 후보와 같은 제약에서 구현하되 **후보가 Oracle을 넘는 쌍 수를 반드시 보고**하고(넘으면 상한이 아님), 개선 여지가 잡음 이하인 쌍은 집계에서 뺀다. 경계 x는 문헌의 달성률에서 정하되 포함 기준을 수치 수집 전에 문서에 등록하고, 원문에서 직접 확인한 수치만 쓴다(검색 요약 문장 금지). 집계 방식(pooled/쌍별 평균)은 두 값을 보기 전에 정한다.
