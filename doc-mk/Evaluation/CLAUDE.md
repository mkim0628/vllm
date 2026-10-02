# doc-mk/Evaluation 작업 규칙

이 폴더(DP1~DP4 평가, benchmark, simulation, 결과 문서, sim 코드)에서 일하는 모든 agent는 다음을 따른다.

1. **`.claude/skills/evaluation/SKILL.md`의 규칙은 필수**다. 작업 전 반드시 읽고 그대로 따른다.
2. 먼저 `doc-mk/Evaluation/README.md`를 읽는다 (폴더 구조, 문서 목록, 도구).
3. 결과 문서는 `result-template.md`의 7개 섹션 형식을 사용하고, 위치는 `DPn/results/YYYY-MM-DD_<topic>.md`다.
4. QA 정의/threshold는 `qa-evaluation-criteria.md`가 원천이며 결과를 본 뒤 바꾸지 않는다.
5. 후보가 Baseline보다 낮으면 SKILL.md의 Baseline-regression loop를 따른다. 지는 시나리오를 숨기지 않는다.
6. simulation 출력은 [B+C]이며 [A]로 쓰지 않는다. 숫자는 코드(`qa_eval.py`)로 재생성한다.
7. commit/push는 orchestrator만 한다. 병렬 작업은 파일 소유권을 분리한다.
