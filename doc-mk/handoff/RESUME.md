# 재개 진입점

다른 환경(사내 on-prem 등)에서 이 저장소를 pull해 작업을 이어받을 때
**가장 먼저 읽는 파일**이다. 절차 전문은 `.claude/skills/session-handoff/references/resume-protocol.md`.

## 지금 이어받을 세션

> **[`sessions/2026-09-06-dp-structure-design/handoff.md`](sessions/2026-09-06-dp-structure-design/handoff.md)**

- 작업: vLLM 이기종 메모리 DP(설계포인트) — 설계 규칙 스킬 + DP1/DP2 문서 + 프로토타입 + PPT 덱 3종
- 브랜치: `claude/dp-structure-design-rules-hoyf13` @ `32a6fcf`
- 다음 한 수: `doc-mk/vllm-dp1-placement-decision-basis.md` **§1.3**을 고쳐 쓴다 —
  "DIP는 지켜져 있다"를 **오늘 이미 존재하는 구조적 결함** 서술로 교체 (근거는 handoff.md 2.1의 [핵심] 3항목)

## 인계 체인

| # | 세션 | 방향 | 기간 | 편입 여부 |
|---|---|---|---|---|
| 1 | `2026-09-06-dp-structure-design` | 외부 → 사내 | 2026-09-02 ~ 09-06 | — |

- **방향**: `외부 → 사내`는 git push로 전달된다. `사내 → 외부`는 사내에서 push할 수 없으므로
  사람이 나른다 (`.claude/skills/session-handoff/references/reverse-handoff.md`).
- **편입 여부**: 사내에서 한 작업이 외부 기록에 다시 들어왔는지.
  `미편입`이 남아 있으면 체인이 끊긴 것이고, 다음 인계에서 그 작업분이 통째로 빠진다.

## 읽는 순서

```text
RESUME.md → sessions/<최신>/handoff.md → stats.md
   → (근거가 필요할 때만) prompts.md → dialogue.md → transcript.jsonl.gz
```

**원문(`prompts.md` / `dialogue.md`)을 먼저 읽지 마라.** 원문에는 세션 중간에 철회된 주장과
버려진 설계가 그대로 남아 있다. 문맥 없이 읽으면 그것들을 되살린다.
`handoff.md`가 현재 상태이고, 원문은 그 근거를 캘 때만 연다.

## 재개하는 세션이 지킬 것

1. **기각 이력(4절)** 의 안을 다시 제안하지 않는다. 뒤집으려면 기각 이유가 무효가 된 근거를 먼저 댄다.
2. **정정 이력(5절)** 에서 취소선 그어진 주장을 쓰지 않는다. 사용자가 직접 틀렸다고 한 문장들이다.
3. **확정 사실(2절)** 중 이 저장소에서 확인 가능한 것은 첫 턴에 한 번만 확인한다.
   (`git log --oneline -10`, `cd doc-mk/prototype && python3 -m unittest discover -s . -q`)
4. **다음 한 수(8절)** 부터 시작한다. 재개 지점은 이미 지목돼 있다.

## 함께 넘어온 스킬

`.claude/`는 upstream `.gitignore`에 걸려 있어 `git add -f`로 강제 추가돼 있다.
pull한 쪽에서도 그대로 동작한다.

| 스킬 | 용도 |
|---|---|
| `.claude/skills/dp-design/` | DP 문서 작성 규칙 (9 Phase, Gate A~I). DP 작업 시 반드시 로드 |
| `.claude/skills/session-handoff/` | 이 인계 규약. 사내에서 되돌릴 때도 같은 형식을 쓴다 |
