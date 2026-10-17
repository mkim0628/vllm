# Architect BP 참고 자료

사용자가 제공한 PDF 4개와 PPTX 2개를 보존한다. 원본 파일명과 내용은 유지한다.

- **정한웅 PPT:** 기본 발표 스타일(남색/진녹색 헤더, 설계 대안, QA/검증 구조).
- **유상욱 PPT:** 대안 비교, FR/QA/제약 추적, Coverage와 검증 표현.
- **Architect 심사 준비 특강:** 심사 논리·내용·발표 팁. 디자인 기준과 구분한다.
- 나머지 PDF 3개: 교육·인증 사례 참고.

## 대용량 PPT 복원

GitHub 연결 도구의 요청당 16MiB 제한으로 약 20MB인 `Architect 양성과정 개인과제_정한웅(1).pptx`만 `.parts/`에 두 조각으로 보관했다. 손실 압축이나 슬라이드 변경은 하지 않았다. 나머지 5개 원본은 이 폴더에서 바로 열 수 있다.

저장소 루트에서 다음을 실행하면 이 폴더에 원래 파일명으로 복원되고, 스킬의 참고 자산에도 복사된다. 기존 `.venv`가 있으면 첫 줄은 생략한다. Python 3.12+의 표준 라이브러리만 사용한다.

```bash
uv venv --python 3.12
.venv/bin/python .claude/skills/architect-presentation/scripts/restore_references.py
```

복원 후 SHA-256은 `56d5584d75ac9c29cfeefc9d83a118e3f97dbb5238fba2d4fe6cd23d22e72e60`이다. 원본과 다른 기존 파일은 덮어쓰지 않는다. 업로드 제한이 없는 Git 클라이언트에서는 복원한 PPTX를 직접 commit/push해도 된다.

## Claude Code에서 사용

이 브랜치를 체크아웃하고 저장소에서 Claude Code를 연 뒤 다음처럼 요청한다.

```text
/architect-presentation doc-mk/DP2의 최신 설계 문서를 참고해
첨부 BP 스타일로 발표자료 5장을 만들어줘. 심사 준비 팁도 적용해줘.
```

스킬 위치: [`.claude/skills/architect-presentation`](../../.claude/skills/architect-presentation)

실제 상대 경로는 저장소 루트 기준 `.claude/skills/architect-presentation/`이다. 스킬은 먼저 대용량 참고 PPT를 자동 복원한 뒤 사용한다. 파일이 없는 환경이나 Python 실행 환경이 준비되지 않은 경우 필요한 위치·의존성을 알린다. 이 브랜치의 기존 스킬은 변경하지 않았다.
