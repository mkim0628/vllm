# DP4 Evaluation

> 상태: **TBD**

## 범위

DP4: **Compute Placement / Scheduling (연산을 어느 Compute/Memory resource에서, 언제 실행할 것인가)**

설계 근거 문서: `doc-mk/vllm-dp4-compute-placement-scheduling-candidates.md`

> 참고: Agent framework + serving runtime 구조를 가정한다 (`qa-evaluation-criteria.md` 8장).

## 폴더

| 파일 | 내용 |
|---|---|
| `benchmark.md` | DP4 benchmark (TBD) |
| `simulation-plan.md` | 평가 방법 (미작성) |
| `results/` | 결과 문서 (`YYYY-MM-DD_<topic>.md`, `../result-template.md`) |

## 작성 시 따를 문서

- `../qa-evaluation-criteria.md` — QA 정의 / 별점 / Evidence
- `../common-benchmark.md` — 공통 benchmark
- `../system-specs.md` — SYS-id
- `.claude/skills/evaluation/SKILL.md` — 평가 작업 규칙 (필수)
- DP1 참고 사례: `../DP1/`
