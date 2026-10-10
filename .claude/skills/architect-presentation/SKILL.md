---
name: architect-presentation
description: Create or revise editable Korean SW Architect review presentations using the attached 정한웅 and 유상욱 BP PowerPoint styles and the Architect 심사 준비 특강 checklist. Use for Architect 심사 발표자료, BP 스타일 PPT, 설계 대안 비교, QA 평가 발표, and requests to turn architecture or DP documents into slides matching these references.
---

# Architect 발표자료

첨부 BP의 시각적 형식과 심사 논증 흐름을 적용해 편집 가능한 PPTX를 제작한다. 한국어를 기본으로 하되 기술 용어와 코드 식별자는 유지한다. 사용자 지정 분량·스타일·대상 독자를 우선한다.

## 자료를 먼저 확인한다

0. **DP1~DP4 설계 PPT는 먼저 `doc-mk/slides/README.md`와 `doc-mk/slides/reference/DP-PPT-style-reference.pptx`를 확인한다.** 사용자가 지정한 프로젝트 스타일이며 아래 BP 스타일보다 우선한다(새 덱은 다른 파일명으로 저장).
1. [스타일 규칙](references/style-guide.md)을 읽는다. 기본은 정한웅 스타일이며 유상욱의 대안 비교·Coverage 표현을 활용한다. 사용자가 유상욱 스타일을 지정하면 그 스타일을 일관되게 적용한다.
2. [심사 준비 체크리스트](references/review-checklist.md)를 읽는다. 이 자료는 내용·논리 지침이다. 특강 PDF의 파란 배경을 발표 디자인으로 혼합하지 않는다.
3. [슬라이드 설계 양식](references/slide-patterns.md)에서 필요한 구성을 선택한다.
4. 원본 위치와 사용 페이지는 [출처 목록](references/sources.md), 크기·색상 수치는 [style-tokens.json](assets/style-tokens.json)을 확인한다.
5. 먼저 저장소의 Python 실행 규칙에 맞춰 `scripts/restore_references.py`를 실행한다. GitHub 배포본은 전송 크기 제한 때문에 정한웅 PPT를 `doc-mk/BP/.parts/`에 두 조각으로 보존한다. 이 스크립트는 SHA-256을 확인하며 원래 파일명과 `assets/jung-reference.pptx`로 복원한다. 완전한 스킬 패키지에는 원본이 이미 들어 있다. 이후 `assets/jung-reference.pptx`, `assets/yoo-reference.pptx`를 복사해 참고한다. 원본과 `assets/review-tips.pdf`는 수정하지 않는다. BP의 성과·수치·저자·제품 이미지를 새 과제의 사실로 가져오지 않는다.

## 제작 순서

1. 제공된 설계 문서를 읽고 과제 목적, 범위, FR/QA/제약, DP, 대안, 선택 근거, 검증 상태를 추출한다. 이전 대화보다 최신 파일 내용을 우선한다. 명시된 내용이 충분하면 되묻지 않고 진행한다.
2. 요구된 장수에 맞춰 각 장의 제목·핵심 메시지·도식·근거·발표 노트를 정한다. 한 장 요청이면 표지 없이 그 한 장을 만든다. 발표 시간이 없으면 분량을 임의로 크게 늘리지 않는다.
3. FR/QA/제약 → Architecture Driver → DP/대안 → 선택 → 검증의 연결표를 먼저 만든다. 원문에 없는 인터페이스나 모듈은 제안/가정으로 표시한다.
4. 전체 심사 자료는 과제 배경·필요성·목표, 요구사항, 설계, 구현·검증, 성과·교훈, Appendix 순서를 기본으로 한다. 부분 발표는 해당 부분만 구성한다.
5. 생성 환경의 프레젠테이션 제작 도구를 이용한다. ChatGPT에서는 제공된 Presentations 스킬의 제작·검증 절차를 따른다. Claude Code에서는 사용 가능한 PPTX 편집 도구로 원본의 마스터·레이아웃을 재사용하고, 정확한 재사용이 불가능하면 측정한 토큰을 이용해 편집 가능한 도형으로 재구성한다. 특정 런타임의 절대 경로나 비공개 도구를 필수 의존성으로 넣지 않는다.
6. 표·텍스트·핵심 구조도·QA 비교는 편집 가능한 객체로 만든다. 원본 슬라이드 전체를 배경 이미지로 붙이지 않는다. 원본에서 가져온 부가 이미지의 비율과 출처를 유지한다.
7. 한글 폰트를 확인한다. 원본은 주로 맑은 고딕이다. 미설치 환경에서는 사용 가능한 한글 폰트를 명시적으로 적용하고 줄바꿈을 다시 검사한다. 글자가 누락된 렌더를 정상 결과로 판정하지 않는다.
8. 모든 슬라이드를 렌더링해 확인하고, 스타일 비교·텍스트 잘림·겹침·한글 누락·연결선·범례·단위·출처·노트·링크를 수정한다. 렌더링 도구가 없으면 그 한계를 알리고 시각 검증 완료라고 말하지 않는다.

## 설계 발표 규칙

- DP마다 무엇을 결정하는지와 관련 QA를 명시한다. 같은 문제·동일한 추상화 수준·동일한 조건으로 후보를 비교한다.
- 책임 분리, 호출 경계, 결정 시점, 프로세스/배포, 데이터 흐름처럼 실제 구조 차이를 그림으로 보인다. 패턴 이름만으로 대안을 설명하지 않는다.
- 대안마다 장점과 비용을 함께 적고 채택 이유·감수한 불이익을 명시한다. 비교 대안을 의도적으로 약하게 만들지 않는다.
- Module View, C&C View, Deployment View, Sequence Diagram을 구분한다. 선에는 uses/call/event/data 등 의미를 붙이고 프로세스 경계·동기/비동기 여부를 필요한 곳에 표시한다.
- QA에는 측정 지표·단위·환경·목표·선정 이유·검증 근거를 연결한다. 처리량·TTFT·TPOT·Goodput 등은 정의와 집계 방법이 다르면 별도 지표로 분리한다.
- 별점은 정량 구간이나 명시적 논증 기준을 정의한 후 사용한다. 실측·문헌·시뮬레이션·추정은 구분한다. 근거가 없으면 미검증으로 표시하고 숫자나 성공 판정을 만들지 않는다.
- 발표 노트는 핵심 주장 → 근거 → 선택의 의미 순서로 짧게 쓴다. 상세 수식·로그·긴 배경·전체 후보 목록은 Appendix로 옮긴다.

## 보조 점검

`scripts/inspect_deck.py <deck.pptx>`로 슬라이드 크기, 텍스트, 명시된 폰트/크기/색, 노트, 캔버스 밖 객체를 JSON으로 확인한다. XML 점검은 시각 검증을 대체하지 않는다. 저장소의 Python 실행 규칙을 준수한다.

## 완료 기준

- 요청된 내용과 장수를 충족한다.
- 선택한 BP 스타일의 화면비·헤더·내비게이션·표·비교 레이아웃을 일관되게 적용한다.
- 설계 결정과 요구사항·QA·검증 결과가 연결된다.
- 확인되지 않은 결과는 분명히 표시하고 출처를 찾을 수 있다.
- 결과 PPTX와 필요한 발표 노트를 전달한다. 원본을 덮어쓰거나 요청 없이 외부로 발송하지 않는다.
