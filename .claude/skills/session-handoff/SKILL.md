---
name: session-handoff
description: 지금까지의 작업 기록을 git에 남겨 다른 Claude Code 세션이 이어받게 한다. 외부(claude.ai/code) 세션에서 인계 문서를 만들어 push하고, 사내(on-prem) 세션이 pull해서 재개하는 단방향 인계 흐름을 강제한다. 사용자가 기록 저장, 작업 기록, 인계, 핸드오프, handoff, 세션 저장, 이어서 작업, 작업 재개, resume, on-prem, 온프렘, 사내 Claude, 다른 환경에서 계속을 언급할 때 사용한다. 재개하는 쪽에서 RESUME.md·handoff.md를 읽고 컨텍스트를 복원할 때도 사용한다.
---

# 세션 인계 (외부 ↔ 사내)

## 무엇을 푸는 스킬인가

```text
  외부 Claude Code (여기)                        사내 on-prem Claude Code
  ─────────────────────                          ────────────────────────
  작업 → 인계 문서 작성 → git push   ──────►     git pull → 인계 문서 읽고 재개
                                                          │
                                     ◄── push 불가 ───────┘
                                        (사람이 텍스트/패치로 옮긴다)
```

전제: **사내는 외부 git을 pull만 할 수 있고 push는 못 한다.** 그래서
정방향(외부→사내)은 git이 나르고, 역방향(사내→외부)은 사람이 나른다.
이 비대칭을 문서 형식이 흡수해야 한다 — 역방향 인계도 같은 형식으로 쓰되
전달 수단만 다르다(`references/reverse-handoff.md`).

## 저장 위치 (고정)

```text
doc-mk/handoff/
├── RESUME.md                    ← 재개하는 세션이 가장 먼저 읽는 단 하나의 진입점
├── README.md                    ← 사람이 읽는 규약 설명
├── tools/export_session.py      ← 전사(jsonl) → prompts/dialogue/stats 추출기
└── sessions/
    └── <YYYY-MM-DD>-<slug>/
        ├── handoff.md           ← ★ 핵심. 이것만 읽어도 재개 가능해야 한다
        ├── prompts.md           ← 사용자 발화 원문 (자동 생성)
        ├── dialogue.md          ← 도구 호출 뺀 대화 원문 (자동 생성)
        ├── stats.md             ← 기간·커밋·도구 통계 (자동 생성)
        └── transcript.jsonl.gz  ← 원문 전사 (선택, `--raw`)
```

`.claude/`가 `.gitignore`에 걸려 있는 저장소라면 **스킬도 함께 넘겨야** 사내에서
같은 규약이 돈다. `git add -f .claude/skills/` 로 강제 추가한다.

## 실행 순서

| Phase | 하는 일 | 참조 |
|---|---|---|
| 0 | 세션 디렉터리 이름 정하기 `<YYYY-MM-DD>-<slug>` | 아래 |
| 1 | `tools/export_session.py` 로 원문 추출 | 아래 |
| 2 | `handoff.md` 작성 — 이 스킬의 본체 | `references/handoff-format.md` |
| 3 | `RESUME.md` 갱신 (최신 세션 포인터 + 인계 체인) | `templates/RESUME.md` |
| 4 | 커밋 · 지정 브랜치로 push (`.claude/skills`는 `-f`) | 아래 |

### Phase 1 — 원문 추출

```bash
python3 doc-mk/handoff/tools/export_session.py \
    --out doc-mk/handoff/sessions/<YYYY-MM-DD>-<slug> [--raw]
```

- `--raw`는 도구 출력까지 포함한 전사를 gzip으로 남긴다(세션당 ~1MB).
  **사내에서 "왜 그렇게 판단했나"를 파고들 여지를 남기고 싶을 때만** 켠다.
- `--since <ISO>`로 증분 인계가 된다. 같은 세션을 두 번째로 인계할 때 쓴다.
- 원문은 **요약하지 않는다.** 요약은 `handoff.md`의 일이고, 원문은 그 요약이
  틀렸을 때 되짚을 근거다. 둘을 섞지 마라.

### Phase 4 — 커밋 · push

```bash
git add doc-mk/handoff
git add -f .claude/skills            # .claude/ 가 gitignore 된 저장소인 경우
git commit -m "Hand off <slug> for the on-prem session"
git push -u origin <지정 브랜치>
```

## 이 스킬의 핵심 규칙

> **인계 문서의 합격 기준은 "요약이 잘 됐는가"가 아니라
> "원문 전사를 못 읽는 세션이 이것만으로 다음 한 수를 둘 수 있는가"다.**

그래서 `handoff.md`에는 결과뿐 아니라 **결과에 이르지 못한 것**이 들어가야 한다.

| 반드시 남긴다 | 남기지 않으면 생기는 일 |
|---|---|
| 기각한 대안과 기각 이유 | 사내 세션이 같은 대안을 다시 제안하고 같은 반박을 다시 받는다 |
| 사용자가 정정한 내 주장 | 이미 철회된 주장이 사내에서 되살아나 문서에 다시 들어간다 |
| 세션 안에서 정의한 용어 | 같은 단어가 다른 뜻으로 쓰여 논의가 어긋난다 |
| 확정된 수치·코드 위치 | 사내가 같은 조사를 처음부터 반복한다 (외부 저장소 접근이 없으면 아예 못 한다) |
| 재현 명령 | 빌드·테스트를 복원하지 못해 검증 없이 문서만 고친다 |
| 미결 항목과 **다음 한 수** | 재개 지점이 없어 "무엇부터?"로 한 턴을 낭비한다 |

### 하지 말 것

- **진행 서사를 쓰지 마라.** "먼저 A를 조사하고 그다음 B를 고쳤다"는 재개에 쓸모가 없다.
  현재 상태와 남은 일만 쓴다. 서사가 필요하면 `dialogue.md`가 이미 갖고 있다.
- **불확실한 것을 확정처럼 쓰지 마라.** 검증 안 된 항목은 `[미검증]`을 붙인다.
  사내 세션은 이 문서를 사실로 취급하므로, 여기의 과장은 그대로 증폭된다.
- **파일 목록만 나열하지 마라.** 파일마다 *무엇을 담고 있고 어느 상태인지*를 붙인다.
- **원문 추출을 건너뛰지 마라.** 큐레이션은 반드시 무언가를 버린다. 원문이 그 보험이다.

## 재개하는 쪽(사내)일 때

사용자가 "인계받아 재개해줘" / "RESUME.md 읽고 이어서" 라고 하면
`references/resume-protocol.md`를 따른다. 요지:

1. `doc-mk/handoff/RESUME.md` → 최신 세션 → `handoff.md` 순으로 읽는다.
2. `handoff.md`의 **확정 사실을 그대로 신뢰하지 말고**, 저장소 안에서 확인 가능한
   것(코드 위치, 테스트 통과 여부)은 재개 첫 턴에 한 번 확인한다.
3. 기각 이력에 있는 대안은 **다시 제안하지 않는다.** 뒤집으려면 기각 이유가
   무효가 된 근거를 먼저 제시한다.
4. 사내 작업 결과는 push할 수 없다 → 같은 형식으로 `handoff.md`를 새로 쓰고
   `references/reverse-handoff.md`의 전달 방식을 사용자에게 안내한다.
