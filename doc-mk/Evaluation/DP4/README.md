# DP4 Evaluation

> 상태: **사전 등록 완료, 구현 진행 중** (2026-10-04)

## 범위

DP4: **비일관(non-coherent) CXL 공유 메모리에서 서버 간 KV 블록·메타데이터의 일관성을 소프트웨어로 보장하는 구조** — C1 중앙 직렬화(Beluga류) vs C2 분산 락(TraCT류).

> 이전 README의 "Compute Placement / Scheduling" 범위(구세대 DP4, `doc-mk/vllm-dp4-compute-placement-scheduling-candidates.md`)는 현세대 DP 구성에서 DP4가 아니다. 설계 근거: [`../../DP4/dp4-inter-node-kv-sharing-structure-draft.md`](../../DP4/dp4-inter-node-kv-sharing-structure-draft.md).

**평가 방식(사용자 결정 2026-10-04):** 시뮬레이션 + 구조 논증. CXL 공유 풀 하드웨어가 없어 실측 [A]는 없다. 시뮬레이션은 [B+C], 구조 논증·model check는 [C].

## 폴더

| 파일 | 내용 |
|---|---|
| `simulation-plan.md` | 평가 계획 (사전 등록) |
| `qa-criteria-dp4.md` | DP4 QA 정의(QA3), Scalability 제안, 직접 비교, 민감도 |
| `qa4-preregistration.md` | QA4 변경 시나리오·공식·경계 (측정 전 등록) |
| `qa_priority.json` | QA 우선순위 (**proposal**) |
| `benchmark.md` | DP4 benchmark (시나리오당 한 줄, 코드가 단일 소스) |
| `sim/` | 시뮬레이터와 `protocol_check/` |
| `results/` | 결과 문서 (`YYYY-MM-DD_<topic>.md`), `data/`, `iterations/` |

## 작성 시 따를 문서

- `../qa-evaluation-criteria.md`, `../common-benchmark.md`, `../system-specs.md`
- `.claude/skills/evaluation/SKILL.md` (필수)
- DP1 참고: `../DP1/`
