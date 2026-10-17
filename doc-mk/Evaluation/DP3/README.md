# DP3 Evaluation

> 상태: **TBD**

## 범위

DP3: **Long Context를 위한 KV Cache Eviction 구조**

설계 근거 문서: `doc-mk/DP3/dp3-long-context-kv-cache-eviction.md`

> 참고: `doc-mk/vllm-dp3-memory-placement-abstraction-candidates.md`는 DP3를 "Memory Placement / Migration Abstraction"으로 서술한다. DP 번호 정의가 문서마다 다르므로 DP3 착수 시 범위를 확정한다.

## 폴더

| 파일 | 내용 |
|---|---|
| `benchmark.md` | DP3 benchmark (TBD) |
| `simulation-plan.md` | 평가 방법 (미작성) |
| `results/` | 결과 문서 (`YYYY-MM-DD_<topic>.md`, `../result-template.md`) |

## 작성 시 따를 문서

- `../qa-evaluation-criteria.md` — QA 정의 / 별점 / Evidence
- `../common-benchmark.md` — 공통 benchmark
- `../system-specs.md` — SYS-id
- `.claude/skills/evaluation/SKILL.md` — 평가 작업 규칙 (필수)
- DP1 참고 사례: `../DP1/`
