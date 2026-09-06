# 세션 인계 기록

외부 Claude Code(claude.ai/code)에서 한 작업을 **사내 on-prem Claude Code에서 이어서**
하기 위한 기록이다. 재개하려면 [`RESUME.md`](RESUME.md)부터 읽는다.

## 왜 이런 구조인가

사내는 외부 git을 **pull만 할 수 있고 push는 못 한다.** 그래서 흐름이 비대칭이다.

```text
  외부 Claude Code                                사내 on-prem Claude Code
  ────────────────                                ────────────────────────
  작업 → 인계 문서 → git push       ──────►        git pull → 재개
                                                          │
                                    ◄── push 불가 ────────┘
                                       (사람이 번들/패치/복붙으로 나른다)
```

정방향은 git이 나르고, 역방향은 사람이 나른다. 형식은 양방향이 같다.

## 디렉터리

```text
doc-mk/handoff/
├── RESUME.md                    재개 진입점 — 최신 세션 포인터 + 인계 체인
├── README.md                    이 파일
├── tools/export_session.py      전사(jsonl) → prompts / dialogue / stats 추출기
└── sessions/<YYYY-MM-DD>-<slug>/
    ├── handoff.md               ★ 현재 참인 것. 이것만 읽어도 재개 가능해야 한다
    ├── prompts.md               사용자 발화 원문 (자동 생성)
    ├── dialogue.md              도구 호출을 뺀 대화 원문 (자동 생성)
    ├── stats.md                 기간·커밋·도구 통계 (자동 생성)
    └── transcript.jsonl.gz      원문 전사 — 도구 출력 포함 (선택, `--raw`)
```

## 원문과 인계 문서의 역할이 다르다

| | 담는 것 | 언제 읽나 |
|---|---|---|
| `handoff.md` | **지금 무엇이 참인가** — 확정 사실, 결정, 기각, 정정, 다음 한 수 | 항상 먼저 |
| `prompts.md` / `dialogue.md` | **무엇이 있었는가** — 철회된 주장과 버려진 설계까지 그대로 | 근거를 캘 때만 |

원문을 먼저 읽으면 이미 폐기된 결론을 되살린다. 순서를 지킬 것.

## 새 인계를 만들 때

Claude Code에서 `session-handoff` 스킬을 쓴다("기록 저장해줘" / "인계 문서 만들어줘").
수동으로 한다면:

```bash
python3 doc-mk/handoff/tools/export_session.py \
    --out doc-mk/handoff/sessions/<YYYY-MM-DD>-<slug> [--raw] [--since <ISO>]
# handoff.md 를 .claude/skills/session-handoff/references/handoff-format.md 형식으로 작성
# RESUME.md 의 "지금 이어받을 세션" 과 "인계 체인" 갱신

git add doc-mk/handoff
git add -f .claude/skills                    # .claude/ 는 gitignore 되어 있다
git commit -m "Hand off <slug> for the on-prem session"
git push -u origin <브랜치>
```

`--raw`는 세션당 약 1 MB를 더한다. 사내에서 "왜 그렇게 판단했나"를 파고들 여지를
남기고 싶을 때만 켠다.

## 사내에서 되돌릴 때

`.claude/skills/session-handoff/references/reverse-handoff.md` 참고. 손실이 적은 순서로:

1. `git bundle` — 파일 반출이 되는 경우. 코드 변경까지 그대로 온다.
2. `git format-patch` — 파일 반출 가능, 커밋 단위 검토가 필요할 때.
3. `handoff.md` 본문 복붙 — 파일 반출 불가. **코드 변경은 오지 않는다**;
   그래서 이 경우 사내 세션은 diff를 `handoff.md` 안에 직접 넣어야 한다.
