#!/usr/bin/env python3
"""Build the DP2 evaluation appendix deck (same format as DP1-appendix-qa-result.pptx) from DP2 result data.

    python tools/gen_dp2_pptx.py --out-dir doc-mk/DP2 [--preview-dir DIR]

Numbers come from DP2/results/data/{qa_result.json,qa5_result.json,qa4_modifiability.json} through tools/gen_dp2_result.py
(the same function feeds the result document, so slide and document cannot diverge).
Slide frame/rendering helpers are DP1's (gen_dp_pptx.py); only the header string is replaced.
"""
from __future__ import annotations

import argparse
import inspect
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import gen_dp_pptx as base  # noqa: E402
import gen_dp2_result as R  # noqa: E402

Slide, preview = base.Slide, base.preview
HEADER = "DP2. Cost 기반 Prefill/Decode 실행 계획 - Appendix"
_src = inspect.getsource(base.build).replace("DP1. 이기종 메모리 기반 Data Migration 구조 - Appendix", HEADER)
exec(compile(_src, "gen_dp_pptx.build", "exec"), base.__dict__, base.__dict__)   # rebinding build inside the module namespace
build = base.__dict__["build"]


def slides():
    return R.deck_slides(Slide)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out-dir", type=Path, default=HERE.parent.parent / "DP2")
    ap.add_argument("--preview-dir", type=Path, default=None)
    a = ap.parse_args()
    tmpl = HERE.parent.parent / "DP1" / "DP-memory-backend-if.pptx"
    a.out_dir.mkdir(parents=True, exist_ok=True)
    sls = slides()
    out = a.out_dir / "DP2-appendix-qa-result.pptx"
    build(sls, out, tmpl)
    print("wrote", out, len(sls), "slide(s)")
    if a.preview_dir:
        a.preview_dir.mkdir(parents=True, exist_ok=True)
        for i, sl in enumerate(sls):
            preview(sl, a.preview_dir / f"DP2-appendix-qa-result-{i + 1}.png")


if __name__ == "__main__":
    main()
