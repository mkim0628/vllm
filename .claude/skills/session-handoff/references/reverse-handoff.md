# 역방향 인계 (사내 → 외부)

사내(on-prem)는 외부 git에 **push할 수 없다.** 그래서 사내에서 한 작업을
외부 세션으로 되돌리려면 사람이 나른다. 전달 수단만 다르고 **형식은 같다.**

## 사내 세션이 할 일

정방향과 똑같이 인계 디렉터리를 만든다. 이름만 구분한다:

```bash
python3 doc-mk/handoff/tools/export_session.py \
    --out doc-mk/handoff/sessions/<YYYY-MM-DD>-onprem-<slug>
# handoff.md 를 references/handoff-format.md 형식으로 작성
git add doc-mk/handoff && git commit -m "Hand back <slug> from the on-prem session"
```

커밋은 **사내 로컬 브랜치에만** 남는다. push하지 않는다(못 한다).

## 되돌리는 방법 세 가지

사용자에게 환경 제약을 물어 하나를 고른다. 위에서부터 손실이 적다.

| 방법 | 명령 | 조건 |
|---|---|---|
| **패치 번들** | `git bundle create handoff.bundle <외부HEAD>..HEAD` | 사내→밖으로 **파일 반출**이 되는 경우. 코드 변경까지 그대로 온다 |
| **패치 파일** | `git format-patch <외부HEAD>..HEAD -o out/` | 파일 반출 가능. 커밋 단위로 검토가 필요할 때 |
| **본문 복붙** | `handoff.md` 내용을 외부 세션 프롬프트에 붙여넣기 | 파일 반출이 안 되는 경우. **코드 변경은 못 온다 — 인계 문서만 온다** |

복붙만 가능한 환경이라면 사내 세션은 그 사실을 알고 써야 한다:

- 코드 변경 내용을 `handoff.md` 안에 **diff 블록으로 직접 포함**한다.
  외부 세션이 그걸 보고 다시 적용할 수 있어야 한다.
- 새로 만든 파일은 전문을 넣는다. "파일을 추가했다"만 적으면 외부에서 복원이 안 된다.
- 분량이 커지면 8절 형식을 유지한 채 `handoff.md`를 파트로 쪼개고,
  1절 요약에 파트 목록을 적는다.

## 외부 세션이 되돌려 받을 때

```bash
git bundle verify handoff.bundle && git pull handoff.bundle <브랜치>   # 번들
git am out/*.patch                                                     # 패치
```

복붙으로 받았다면 외부 세션은 그 내용을 **새 인계 디렉터리로 커밋해서 기록에 편입**한다.
그러지 않으면 다음 인계 때 사내 작업분이 통째로 빠진다.

```bash
mkdir -p doc-mk/handoff/sessions/<YYYY-MM-DD>-onprem-<slug>
# 받은 본문을 handoff.md 로 저장 → RESUME.md 체인에 추가 → commit → push
```

## 순환이 성립하려면

```text
외부 세션 N   ──push──►  git  ──pull──►  사내 세션 N
                                              │
외부 세션 N+1 ◄──사람───────────────────────────┘
      │
      └── 사내분을 인계 기록에 편입해서 push → 사내 세션 N+1 이 이어받음
```

외부 세션 N+1이 사내분을 편입하지 않으면 체인이 끊긴다.
**RESUME.md의 인계 체인 표가 그 끊김을 드러내는 유일한 장치다** — 반드시 갱신한다.
