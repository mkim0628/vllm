#!/usr/bin/env python3
"""QA4 measured counts for DP2 (qa4-preregistration.md 3). Compares pristine base copy and the per-scenario working copies
(scratchpad copies of sim/ with the minimal working change) and attributes each added line to a design component.

    python3 qa4_count.py --work <dir containing base/ s1/ s2/ s3/ s4c/> --out ../results/data/qa4_measured_counts.json

LOC rule: added (+) lines in `diff -u` that are neither blank nor comment-only (a modified line counts once as its + line).
Every added line must match an attribution rule below (unmatched line -> error), so attribution is explicit and reviewable.
"""
from __future__ import annotations

import argparse
import ast
import difflib
import json
import re
from pathlib import Path

SRC = "DP2/sim/dp2sim/"
# scenario -> list of (file, regex on the added line, component, scope) ; scope: shared | C2
RULES = {
    "S1": [("physics.py", r"DECODE_TIERS = ", "Candidate Generator", "shared"),
           ("physics.py", r"import dataclasses|cxl_pnm2|pn = ", "Resource Intelligence", "shared"),
           ("engine.py", r"cxl_pnm2", "Resource Intelligence", "shared")],
    "S2": [("policies.py", r"ENERGY|w_e|w_energy", "Cost Model", "shared")],
    "S3": [("policies.py", r"selector|select_key", "Resource Selector", "shared"),
           ("engine.py", r"selector", "Resource Selector", "shared")],
    "S4": [("node.py", r"degraded", "Resource Intelligence", "shared"),
           ("policies.py", r"degraded", "Resource Intelligence", "shared"),
           ("engine.py", r"nv = NodeView|nv\.degraded = nd\.degraded|return nv", "Resource Intelligence", "shared"),
           ("engine.py", r"not nv\.degraded and", "Candidate Generator", "shared"),
           ("engine.py", r"c\.degraded = nv\.degraded", "Plan Cache (planner ledger view)", "C2")],
}
# component -> list of (file, ast qualified name or line-marker span) for module_size_loc (pristine base)
SIZE = {
    "Resource Intelligence": [("physics.py", "func:system"), ("engine.py", "meth:Sim._nodeview"), ("engine.py", "meth:Sim.make_view"), ("policies.py", "class:NodeView"), ("node.py", "meth:Node.__init__")],
    "Candidate Generator": [("engine.py", "meth:Sim.plan_with"), ("engine.py", "meth:Sim.cand_nodes_for")],
    "Cost Model": [("policies.py", "class:Estimator")],
    "Resource Selector": [("policies.py", "span:results.sort(key=lambda x: x[0])|return plan, ranked")],
    "Plan Cache (planner ledger view)": [("engine.py", "meth:Sim.plan_view"), ("engine.py", "meth:Sim.ledger_add"), ("engine.py", "meth:Sim.ledger_release")],
}
TITLES = {
    "S1": "new Tier (cxl_pnm2, CXL-PNM-class device with 2x internal BW)",
    "S2": "new Cost term (relative energy per decoded token, weight w_E)",
    "S3": "policy swap (Selector: argmin Cost -> min TTFT among TPOT-feasible, constructor-injected)",
    "S4": "new telemetry signal (node health/degraded flag as hard constraint on n_p)",
}


def code_lines(path):
    return path.read_text().splitlines()


def span_loc(base, file, spec):
    src = (base / SRC / file).read_text()
    lines = src.splitlines()
    kind, _, name = spec.partition(":")
    if kind == "span":
        a, b = name.split("|")
        i = next(k for k, l in enumerate(lines) if a in l)
        j = next(k for k in range(i, len(lines)) if b in lines[k])
        seg = lines[i:j + 1]
    else:
        tree = ast.parse(src)
        node = None
        if kind == "func":
            node = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == name)
        elif kind == "class":
            node = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == name)
        else:
            cls, meth = name.split(".")
            c = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == cls)
            node = next(n for n in c.body if isinstance(n, ast.FunctionDef) and n.name == meth)
        seg = lines[node.lineno - 1:node.end_lineno]
    return sum(1 for l in seg if l.strip() and not l.strip().startswith("#"))


def added(base, work, file):
    a = (base / SRC / file).read_text().splitlines()
    b = (work / SRC / file).read_text().splitlines()
    out = []
    for l in difflib.unified_diff(a, b, lineterm="", n=0):
        if l.startswith("+") and not l.startswith("+++"):
            s = l[1:]
            if s.strip() and not s.strip().startswith("#"):
                out.append(s)
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--work", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--dirs", default="S1=s1,S2=s2,S3=s3,S4=s4c")
    a = ap.parse_args()
    W = Path(a.work)
    base = W / "base"
    res = {"schema": "qa4_measured_counts v1", "date": "2026-10-04", "preregistration": "doc-mk/Evaluation/DP2/qa4-preregistration.md",
           "evidence": "[B+C] proxy implementation in the DP2 simulator, not vLLM", "scenarios": {}}
    for item in a.dirs.split(","):
        sid, d = item.split("=")
        per = {}
        for file in sorted({r[0] for r in RULES[sid]} | {p.name for p in (W / d / SRC).glob("*.py")}):
            for s in added(base, W / d, file):
                for (f, rx, comp, scope) in RULES[sid]:
                    if f == file and re.search(rx, s):
                        per.setdefault((comp, scope), []).append((file, s))
                        break
                else:
                    raise SystemExit(f"{sid}: unattributed added line in {file}: {s!r}")
        changes = {}
        for (comp, scope), ls in per.items():
            changes[(comp, scope)] = dict(module=comp, shared=(scope == "shared"), files=sorted({f for f, _ in ls}), loc_added=len(ls),
                                          module_size_loc=sum(span_loc(base, f, sp) for f, sp in SIZE[comp]))
        c1 = [v for (c, sc), v in changes.items() if sc == "shared"]
        c2 = [v for (c, sc), v in changes.items()]
        res["scenarios"][sid] = {"title": TITLES[sid], "C1": {"changes": c1}, "C2": {"changes": c2}}
    Path(a.out).parent.mkdir(parents=True, exist_ok=True)
    Path(a.out).write_text(json.dumps(res, indent=1))
    for sid, d in res["scenarios"].items():
        print(sid, {c: [(x["module"], x["loc_added"], x["module_size_loc"]) for x in d[c]["changes"]] for c in ("C1", "C2")})


if __name__ == "__main__":
    main()
