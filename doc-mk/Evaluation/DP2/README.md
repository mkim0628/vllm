# DP2 Evaluation

> 상태: **TBD**

## 범위

DP2: **Cost-based Prefill Execution Planning (prefill 실행 resource 결정 시점 구조)**

설계 근거 문서: `doc-mk/DP2/dp2-prefill-execution-planning-decision-timing.md`, `doc-mk/DP2/vllm-cost-model-prefill-execution-planning-architecture.md`

> 참고: QA 문서는 DP2를 llm-d + vLLM worker, Prefill/Decode node 구조로 가정한다 (`qa-evaluation-criteria.md` 6, 8장). 또한 `doc-mk/vllm-dp2-candidate-qa-tradeoff-v2.md`는 DP2를 "Compute-Capable Memory Abstraction"으로 서술한다. DP 번호 정의가 문서마다 다르므로 DP2 착수 시 범위를 확정한다.

## 폴더

| 파일 | 내용 |
|---|---|
| `benchmark.md` | DP2 benchmark (TBD) |
| `simulation-plan.md` | 평가 방법 (미작성) |
| `results/` | 결과 문서 (`YYYY-MM-DD_<topic>.md`, `../result-template.md`) |

## 작성 시 따를 문서

- `../qa-evaluation-criteria.md` — QA 정의 / 별점 / Evidence
- `../common-benchmark.md` — 공통 benchmark
- `../system-specs.md` — SYS-id
- `.claude/skills/evaluation/SKILL.md` — 평가 작업 규칙 (필수)
- DP1 참고 사례: `../DP1/`
