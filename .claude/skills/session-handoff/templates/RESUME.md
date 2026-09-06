# 재개 진입점

다른 환경(사내 on-prem 등)에서 이 저장소를 pull해 작업을 이어받을 때
**가장 먼저 읽는 파일**이다. 절차는 `.claude/skills/session-handoff/references/resume-protocol.md`.

## 지금 이어받을 세션

> **`sessions/<최신 세션 디렉터리>/handoff.md`**

- 작업: <한 줄>
- 브랜치: `<branch>` @ `<commit>`
- 다음 한 수: <handoff.md 8절 첫 문장 그대로>

## 인계 체인

| # | 세션 | 방향 | 기간 | 편입 여부 |
|---|---|---|---|---|
| 1 | `<YYYY-MM-DD>-<slug>` | 외부 → 사내 | | — |

- **방향**: `외부 → 사내`는 git push로 전달된다. `사내 → 외부`는 사람이 나른다(`reverse-handoff.md`).
- **편입 여부**: 사내에서 한 작업이 외부 기록에 다시 들어왔는지. `미편입`이 남아 있으면 체인이 끊긴 것이다.

## 읽는 순서

```text
RESUME.md → sessions/<최신>/handoff.md → stats.md
   → (근거가 필요할 때만) prompts.md → dialogue.md
```

## 재개하는 세션이 지킬 것

1. 기각 이력(4절)의 안을 다시 제안하지 않는다.
2. 정정 이력(5절)에서 취소선 그어진 주장을 쓰지 않는다.
3. 확정 사실(2절) 중 이 저장소에서 확인 가능한 것은 첫 턴에 한 번 확인한다.
4. "다음 한 수"(8절)부터 시작한다.
