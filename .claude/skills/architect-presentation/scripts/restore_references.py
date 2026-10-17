#!/usr/bin/env python3
"""Restore the byte-identical Jung PPTX from repository parts when needed."""
import hashlib
from pathlib import Path
import shutil
import sys
import tempfile

EXPECTED_SHA256 = "56d5584d75ac9c29cfeefc9d83a118e3f97dbb5238fba2d4fe6cd23d22e72e60"
ORIGINAL_NAME = "Architect 양성과정 개인과제_정한웅(1).pptx"


def digest(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def checked_copy(source, target):
    if target.exists():
        if digest(target) != EXPECTED_SHA256:
            raise RuntimeError(f"Existing file differs; refusing to overwrite: {target}")
        return
    target.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(dir=target.parent, delete=False) as stream:
        temporary = Path(stream.name)
        with source.open("rb") as inp:
            shutil.copyfileobj(inp, stream)
    try:
        if digest(temporary) != EXPECTED_SHA256:
            raise RuntimeError("Source SHA-256 mismatch")
        temporary.replace(target)
    finally:
        temporary.unlink(missing_ok=True)


def restore():
    skill = Path(__file__).resolve().parents[1]
    bundled = skill / "assets/jung-reference.pptx"
    repo = next((p for p in skill.parents if (p / ".git").exists() and (p / "doc-mk/BP").is_dir()), None)
    if bundled.exists():
        if digest(bundled) != EXPECTED_SHA256:
            raise RuntimeError("Bundled reference SHA-256 mismatch")
        if repo is not None:
            checked_copy(bundled, repo / "doc-mk/BP" / ORIGINAL_NAME)
        return bundled
    if repo is None:
        raise RuntimeError("Reference missing: use the complete skill package or a checkout containing doc-mk/BP/.parts")
    original = repo / "doc-mk/BP" / ORIGINAL_NAME
    if not original.exists():
        parts = [repo / "doc-mk/BP/.parts" / f"jung-reference.pptx.part{i:03d}" for i in (1, 2)]
        if not all(p.is_file() for p in parts):
            raise RuntimeError("Both original PPTX parts are required")
        with tempfile.NamedTemporaryFile(dir=original.parent, delete=False) as stream:
            temporary = Path(stream.name)
            for part in parts:
                with part.open("rb") as inp:
                    shutil.copyfileobj(inp, stream)
        try:
            if digest(temporary) != EXPECTED_SHA256:
                raise RuntimeError("Reconstructed PPTX SHA-256 mismatch")
            temporary.replace(original)
        finally:
            temporary.unlink(missing_ok=True)
    checked_copy(original, bundled)
    return bundled


if __name__ == "__main__":
    try:
        print(f"Verified reference: {restore()}")
    except (OSError, RuntimeError) as error:
        print(str(error), file=sys.stderr)
        sys.exit(1)
