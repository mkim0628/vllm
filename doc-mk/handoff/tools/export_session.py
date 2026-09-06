#!/usr/bin/env python3
"""Claude Code 세션 전사(jsonl)에서 인계용 원문을 뽑는다.

외부 Claude Code 세션에서 실행해 doc-mk/handoff/sessions/<id>/ 아래에
prompts.md / dialogue.md / transcript.jsonl.gz 를 남기는 것이 목적이다.
사내(on-prem) 세션은 이 파일들을 git pull 로 받아 작업을 재개한다.

사용법:
    python3 doc-mk/handoff/tools/export_session.py --out doc-mk/handoff/sessions/2026-09-06-dp1
    python3 doc-mk/handoff/tools/export_session.py --out <dir> --transcript <path.jsonl> --raw
"""

import argparse
import gzip
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

PROJECTS = Path.home() / ".claude" / "projects"


def find_transcript(explicit: str | None) -> Path:
    if explicit:
        return Path(explicit)
    cwd = Path.cwd().resolve()
    slug = str(cwd).replace("/", "-")
    candidates: list[Path] = []
    for d in (PROJECTS / slug, PROJECTS):
        if d.is_dir():
            candidates += sorted(d.glob("*.jsonl"))
    if not candidates:
        sys.exit(
            f"전사 파일을 찾지 못했다. --transcript 로 직접 지정하라. (탐색: {PROJECTS/slug})"
        )
    return max(candidates, key=lambda p: p.stat().st_mtime)


def load(path: Path) -> list[dict]:
    out = []
    with path.open(encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return out


def user_prompts(records: list[dict]) -> list[tuple[str, str]]:
    """사용자 발화 원문. queue-operation(enqueue)이 가장 깨끗하고,
    없으면 type=user 중 문자열 content 를 쓴다."""
    out = []
    for rec in records:
        if rec.get("type") == "queue-operation" and rec.get("operation") == "enqueue":
            content = rec.get("content")
            if isinstance(content, str) and content.strip():
                out.append((rec.get("timestamp", ""), content.strip()))
    if out:
        return out
    for rec in records:
        if rec.get("type") != "user" or rec.get("isSidechain") or rec.get("isMeta"):
            continue
        content = rec.get("message", {}).get("content")
        if isinstance(content, str) and content.strip():
            out.append((rec.get("timestamp", ""), content.strip()))
    return out


def dialogue(records: list[dict]) -> list[tuple[str, str, str]]:
    """(role, timestamp, text) — 도구 호출·도구 결과는 버리고 대화만 남긴다."""
    out = []
    for rec in records:
        if rec.get("isSidechain"):
            continue
        ts = rec.get("timestamp", "")
        if rec.get("type") == "queue-operation" and rec.get("operation") == "enqueue":
            content = rec.get("content")
            if isinstance(content, str) and content.strip():
                out.append(("user", ts, content.strip()))
        elif rec.get("type") == "assistant":
            content = rec.get("message", {}).get("content")
            if not isinstance(content, list):
                continue
            for block in content:
                if block.get("type") == "text" and block.get("text", "").strip():
                    out.append(("assistant", ts, block["text"].strip()))
    return out


def tool_usage(records: list[dict]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for rec in records:
        if rec.get("type") != "assistant":
            continue
        content = rec.get("message", {}).get("content")
        if not isinstance(content, list):
            continue
        for block in content:
            if block.get("type") == "tool_use":
                name = block.get("name", "?")
                counts[name] = counts.get(name, 0) + 1
    return counts


def git(*args: str) -> str:
    try:
        return subprocess.run(
            ["git", *args], capture_output=True, text=True, check=False
        ).stdout.strip()
    except OSError:
        return ""


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True, help="출력 디렉터리")
    ap.add_argument("--transcript", help="전사 jsonl 경로 (기본: cwd 기준 자동 탐색)")
    ap.add_argument(
        "--raw",
        action="store_true",
        help="원문 전사를 transcript.jsonl.gz 로 함께 저장 (도구 출력까지 전부 포함)",
    )
    ap.add_argument("--since", help="이 ISO 타임스탬프 이후만 (증분 인계용)")
    args = ap.parse_args()

    src = find_transcript(args.transcript)
    records = load(src)
    if args.since:
        records = [r for r in records if r.get("timestamp", "") >= args.since]

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)

    prompts = user_prompts(records)
    convo = dialogue(records)
    tools = tool_usage(records)
    stamps = [r.get("timestamp") for r in records if r.get("timestamp")]
    span = f"{min(stamps)} ~ {max(stamps)}" if stamps else "(unknown)"
    branch = git("rev-parse", "--abbrev-ref", "HEAD")
    head = git("rev-parse", "--short", "HEAD")

    header = (
        f"<!-- 자동 생성: doc-mk/handoff/tools/export_session.py -->\n"
        f"<!-- 원본 전사: {src.name} -->\n\n"
        f"- 기간: `{span}`\n"
        f"- 브랜치: `{branch}` @ `{head}`\n"
        f"- 사용자 발화: {len(prompts)}건 / 어시스턴트 응답: "
        f"{sum(1 for r, _, _ in convo if r == 'assistant')}건\n\n"
    )

    with (out / "prompts.md").open("w", encoding="utf-8") as fh:
        fh.write("# 사용자 발화 원문 (시간순)\n\n")
        fh.write(header)
        fh.write(
            "> 요약하지 않은 원문이다. 재개하는 세션은 **여기서 의도를 읽고**, "
            "해석은 `handoff.md` 를 참고한다.\n\n---\n\n"
        )
        for i, (ts, text) in enumerate(prompts, 1):
            fh.write(f"## {i:02d}. `{ts}`\n\n{text}\n\n---\n\n")

    with (out / "dialogue.md").open("w", encoding="utf-8") as fh:
        fh.write("# 대화 기록 (도구 호출 제외)\n\n")
        fh.write(header)
        for role, ts, text in convo:
            tag = "사용자" if role == "user" else "Claude"
            fh.write(f"### {tag} · `{ts}`\n\n{text}\n\n")

    with (out / "stats.md").open("w", encoding="utf-8") as fh:
        fh.write("# 세션 통계\n\n")
        fh.write(header)
        fh.write("## 도구 사용\n\n| 도구 | 횟수 |\n|---|---|\n")
        for name, count in sorted(tools.items(), key=lambda kv: -kv[1]):
            fh.write(f"| `{name}` | {count} |\n")
        fh.write("\n## 이 브랜치의 커밋\n\n```\n")
        fh.write(git("log", "--oneline", "-40") + "\n```\n")

    if args.raw:
        with src.open("rb") as fin, gzip.open(out / "transcript.jsonl.gz", "wb") as fout:
            shutil.copyfileobj(fin, fout)

    for name in ("prompts.md", "dialogue.md", "stats.md", "transcript.jsonl.gz"):
        path = out / name
        if path.exists():
            print(f"  {path}  ({path.stat().st_size:,} bytes)")


if __name__ == "__main__":
    main()
