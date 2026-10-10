# DP2 Evaluation

> 상태: **draft** (simulator 구현·첫 평가 완료, 결과: [`results/2026-10-06_dp2-qa-evaluation.md`](results/2026-10-06_dp2-qa-evaluation.md), 덱: `doc-mk/DP2/DP2-appendix-qa-result.pptx`). 소유자 결정 O1~O11 미확정, 별 경계·선택 규칙은 제안 상태)

## 범위

DP2: **Cost-based Prefill/Decode Execution Planning** — Turn 단위로 Prefill 실행 위치(n_p)와 Decode 시작 위치(n_d)를 정한다. Decode 실행 중 Tier 간 KV 이동은 DP1 소관이다.

설계 근거 문서: `doc-mk/DP2/dp2-prefill-decode-execution-planning-decision-timing.md`, `doc-mk/DP2/dp2-qa-evaluation-rationale.md`, `doc-mk/DP2/vllm-cost-model-prefill-decode-execution-planning-architecture.md`

> 범위 확정 제안: 기존 README는 "DP 번호 정의가 문서마다 다르므로 DP2 착수 시 범위를 확정한다"고 했다. 위 범위를 제안하며 소유자 확인이 필요하다. QA 문서는 DP2를 llm-d + vLLM worker, Prefill/Decode node 구조로 가정한다 (`qa-evaluation-criteria.md` 6, 8장). `doc-mk/vllm-dp2-candidate-qa-tradeoff-v2.md`는 DP2를 "Compute-Capable Memory Abstraction"으로 서술하는데 이는 이 평가의 범위가 아니다.

## 폴더

| 파일 | 내용 |
|---|---|
| `qa-criteria-dp2.md` | DP2 QA 정의 (QA3 임시 정의, QA5 Scalability 신규, 진단 지표) — proposal |
| `simulation-plan.md` | 평가 방법, 환경(SYS-H100/B200 + 노드 간 링크 신규 profile), simulator 확장 항목 — draft |
| `m0-spec.md` | M0 사양 (물리 모델 규칙, Planner·Cost 정의, workload, 메트릭, 평가 규격, 가정 레지스터, 소유자 결정 O1~O11) — draft |
| `sim/` | M0 산출물: `configs/`(파라미터, 링크 profile, 시나리오, 결과 스키마), `m0_check.py`, `m0_reference_values.json`. simulator 코드(M1~)는 아직 없음 |
| `sim-extension-scope.md` | DP2 simulator 확장 범위 (접근 대안, 모듈 구성, 모델링 요구사항, 단계 M0~M6, 테스트 계획) — draft |
| `benchmark.md` | CB-1~3 실현, Baseline-PD-fixed 정의, DP2 Stress 12 / Dynamic 4 / Scalability / QA4 변경 시나리오 — draft |
| `results/` | 결과 문서 (`YYYY-MM-DD_<topic>.md`, `../result-template.md`) |
| `arch-styles-plan.md`, `qa4-preregistration-arch.md` | **2026-10-10 재정의 평가**(노드 내 attention 실행 위치, 후보 축 = 아키텍처 스타일: A 중앙 Dispatcher 대 B Blackboard) 사전 등록. 시나리오는 `benchmark.md` §11, 코드는 `sim/dp2sim/{nodeint,arch_dispatcher,arch_blackboard,scenarios_node}.py`, 실행 `sim/{node_control,qa_eval_node,sens_arch,qa4_arch,qa4_apply}.py`, 결과 `results/data/arch/`, 로그 `results/iterations/loop-log.md` §3 |
| (작성 예정) | `qa4-preregistration.md`, `qa_priority.json`, `sim/` |

## 작성 시 따를 문서

- `../qa-evaluation-criteria.md` — QA 정의 / 별점 / Evidence
- `../common-benchmark.md` — 공통 benchmark
- `../system-specs.md` — SYS-id
- `.claude/skills/evaluation/SKILL.md` — 평가 작업 규칙 (필수)
- DP1 참고 사례: `../DP1/`
