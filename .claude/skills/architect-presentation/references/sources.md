# 출처와 원본 위치

저장소: `mkim0628/vllm`, 브랜치: `claude/vllm-call-path-analysis-qxulkr`, 원본 폴더: `doc-mk/BP/`.

첨부 원본의 바이트를 그대로 보존했다. 이 자료들은 스타일·발표 방법의 참고이며 새 과제의 실적이나 성능 근거가 아니다.

| 원본 | 역할 | 스킬 내부 복사본 |
|---|---|---|
| 2024_SW_Architect_인증_사례_윤종훈님(2024)_공유(1).pdf | 추가 교육·인증 사례. 새 작업에서 관련 내용을 사용할 때 해당 원문 확인 | `doc-mk/BP/`의 원본 참조 |
| 26년 Architect 양성과정 1주차 - 이자윤 Architect(1).pdf | 추가 교육·인증 사례. 새 작업에서 관련 내용을 사용할 때 해당 원문 확인 | `doc-mk/BP/`의 원본 참조 |
| Architect 심사 준비 특강(1).pdf | 심사 논리·내용·발표 팁 | `assets/review-tips.pdf` |
| Architect 양성과정 1주차_서지환님(2024)(1).pdf | 추가 교육·인증 사례. 새 작업에서 관련 내용을 사용할 때 해당 원문 확인 | `doc-mk/BP/`의 원본 참조 |
| Architect 양성과정 개인과제_정한웅(1).pptx | 기본 시각 스타일, 구조/평가 패턴 | `assets/jung-reference.pptx` |
| 유상욱_메모리사업부(1).pptx | 보조 시각 스타일, 대안 비교/Coverage | `assets/yoo-reference.pptx` |

페이지 번호는 1-based 물리 슬라이드/PDF 페이지다. 원본 하단의 본문 장수 표기와 다를 수 있다.

기본 PPT는 55장, 보조 PPT는 39장이다. 전체를 렌더링해 레이아웃을 확인하고 OOXML에서 화면비·색·폰트·좌표를 추출했다. 검사 환경에서는 맑은 고딕이 없어 일부 한글 렌더가 누락되었으므로 폰트와 문구는 원본 XML도 대조했다. 미리보기 이미지를 원본 대용으로 배포하지 않는다.

해시와 보존 목록은 `assets/source-manifest.json`에 있다. 로컬 원본은 수정하지 않는다. GitHub 연결의 16MiB 요청 제한으로 정한웅 PPT의 GitHub 배포본만 `doc-mk/BP/.parts/jung-reference.pptx.part001`과 `.part002`에 분할 보관한다. `scripts/restore_references.py`로 원본 바이트를 복원한다. 이 두 조각을 직접 PowerPoint로 열지 않는다. 완전한 스킬 패키지에는 원래 PPTX가 포함되어 있다.
