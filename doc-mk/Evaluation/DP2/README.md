# DP2 Evaluation

> 상태: **draft** (평가 설계 초안: 범위·QA·시나리오 정의, simulator 구현 전)

## 범위

DP2: **Cost-based Prefill/Decode Execution Planning** — Turn 단위로 Prefill 실행 위치(n_p)와 Decode 시작 위치(n_d)를 정한다. Decode 실행 중 Tier 간 KV 이동은 DP1 소관이다.

설계 근거 문서: `doc-mk/DP2/dp2-prefill-execution-planning-decision-timing.md`, `doc-mk/DP2/dp2-qa-evaluation-rationale.md`, `doc-mk/DP2/vllm-cost-model-prefill-execution-planning-architecture.md`

> 범위 확정 제안: 기존 README는 "DP 번호 정의가 문서마다 다르므로 DP2 착수 시 범위를 확정한다"고 했다. 위 범위를 제안하며 소유자 확인이 필요하다. QA 문서는 DP2를 llm-d + vLLM worker, Prefill/Decode node 구조로 가정한다 (`qa-evaluation-criteria.md` 6, 8장). `doc-mk/vllm-dp2-candidate-qa-tradeoff-v2.md`는 DP2를 "Compute-Capable Memory Abstraction"으로 서술하는데 이는 이 평가의 범위가 아니다.

## 폴더

| 파일 | 내용 |
|---|---|
| `qa-criteria-dp2.md` | DP2 QA 정의 (QA3 임시 정의, QA5 Scalability 신규, 진단 지표) — proposal |
| `simulation-plan.md` | 평가 방법, 환경(SYS-H100/B200 + 노드 간 링크 신규 profile), simulator 확장 항목 — draft |
| `benchmark.md` | CB-1~3 실현, Baseline-PD-fixed 정의, DP2 Stress 12 / Dynamic 4 / Scalability / QA4 변경 시나리오 — draft |
| `results/` | 결과 문서 (`YYYY-MM-DD_<topic>.md`, `../result-template.md`) |
| (작성 예정) | `qa4-preregistration.md`, `qa_priority.json`, `sim/` |

## 작성 시 따를 문서

- `../qa-evaluation-criteria.md` — QA 정의 / 별점 / Evidence
- `../common-benchmark.md` — 공통 benchmark
- `../system-specs.md` — SYS-id
- `.claude/skills/evaluation/SKILL.md` — 평가 작업 규칙 (필수)
- DP1 참고 사례: `../DP1/`
