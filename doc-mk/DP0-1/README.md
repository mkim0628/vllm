# DP0-1 — 서버 간 요청 조율 계층의 구조 (S1 중앙 결정형 대 S2 2단계 위임형)

DP0을 둘로 나눈 것 중 **구조 결정**이다. 이전 `../DP0/`의 "OSS 확장 대 직접 개발"은 구현 방식 비교여서 **DP0-2**로 내리고, DP0-1에서 구조를 고른 뒤 그 구조에 대해 2차로 결정한다.

| 문서 | 내용 |
|---|---|
| [`dp0-1-structure-design.md`](dp0-1-structure-design.md) | 설계 문서. 임원용 요약 → 후보 구조(S1/S2 컴포넌트 뷰, 대치) → 평가(변경 시나리오 M1~M6, QA 별점, 제약·리스크, 선택과 근거) → **보완 설계(DP1~DP4 연결)** → Evidence 계획 |
| `DP0-1-slides.pptx` | 발표자료 7장. 4 구조(같은 좌표 대치 도식), 5 변경 시나리오 M1~M6, 6 Tradeoff, 7 S2 보완 설계 |
| [`../DP0/dp0-requirements.md`](../DP0/dp0-requirements.md) | 요구사항(F1~F6, Q1~Q4, C1~C6, P1~P5). DP0-1이 그대로 쓴다 |
| [`../DP0/dp0-request-orchestration-framework.md`](../DP0/dp0-request-orchestration-framework.md) | 이전 DP0 설계 문서. DP0-2(구현 방식)가 승계한다 |

- 근거 수준: **[A]** 실행·빌드 검증 · **[B]** 문헌 · **[C]** 구조 논증. 별점·우열은 모두 가설이다.
- 공통 QA 기준 문서(`../Evaluation/qa-evaluation-criteria.md`)는 바꾸지 않았다.
