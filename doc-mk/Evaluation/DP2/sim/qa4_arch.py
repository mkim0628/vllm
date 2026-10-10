#!/usr/bin/env python3
"""QA4 measurement for the architecture-style evaluation (qa4-preregistration-arch.md 2-3).

Builds a pristine copy (`base`) of DP2/sim and, per (candidate, scenario), a working copy with the minimal working change (the patch
tables below), runs the smoke criterion and the existing tests in the working copy, then counts added lines per design component.
Every added line must match an attribution rule (unmatched -> error). Candidate keys follow tools/qa4_modifiability.py:
"C1" = A-Dispatcher, "C2" = B-Blackboard (documented in the output).

    python qa4_arch.py --work <scratch dir> --out ../results/data/arch/qa4_measured_counts.json
"""
from __future__ import annotations

import argparse
import ast
import difflib
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
EVAL = HERE.parent.parent
SRC = "DP2/sim/dp2sim/"
PY = sys.executable
CAND_KEY = {"A": "C1", "B": "C2"}

# ---------------------------------------------------------------------------------------------------------- patches
# (candidate, scenario) -> list of (file, old, new). Minimal working change; harness code (smoke scripts) is not counted.
SYSTEM_OLD = '''    if sys_id not in _SYS:
        _SYS[sys_id] = load_profile(DP1_SIM / "configs", sys_id)[0]
'''
SYSTEM_NEW = SYSTEM_OLD + '''        pn = _SYS[sys_id].memories["cxl_pnm"]
        _SYS[sys_id].memories["cxl_pnm2"] = dataclasses.replace(pn, name="cxl_pnm2", capacity_bytes=512 * 2**30, int_bw=2 * pn.int_bw)
'''
P = {}
P[("A", "S1")] = [
    ("physics.py", "import json\n", "import dataclasses\nimport json\n"),
    ("physics.py", 'DECODE_TIERS = ("hbm", "custom_hbm", "cxl_pnm", "hbf")', 'DECODE_TIERS = ("hbm", "custom_hbm", "cxl_pnm", "cxl_pnm2", "hbf")'),
    ("physics.py", SYSTEM_OLD, SYSTEM_NEW),
    ("engine.py", '("hbm", "custom_hbm", "cxl_pnm", "hbf", "dram")}', '("hbm", "custom_hbm", "cxl_pnm", "cxl_pnm2", "hbf", "dram")}'),
]
P[("B", "S1")] = [
    ("physics.py", "import json\n", "import dataclasses\nimport json\n"),
    ("physics.py", 'OFFLOAD = ("custom_hbm", "cxl_pnm")', 'OFFLOAD = ("custom_hbm", "cxl_pnm", "cxl_pnm2")'),
    ("physics.py", SYSTEM_OLD, SYSTEM_NEW),
    ("engine.py", '("hbm", "custom_hbm", "cxl_pnm", "hbf", "dram")}', '("hbm", "custom_hbm", "cxl_pnm", "cxl_pnm2", "hbf", "dram")}'),   # shared snapshot tier list (engine.commit updates it)
]
P[("A", "S2")] = [
    ("policies.py", "SLO_TPOT = 0.050\n", 'SLO_TPOT = 0.050\nENERGY = {"hbm": 1.0, "custom_hbm": 0.8, "cxl_pnm": 0.5, "hbf": 0.4}   # relative energy per decoded token (ASSUMED)\n'),
    ("policies.py", "        self.eps = eps\n", '        self.eps = eps\n        self.w_e = sim.o.get("w_energy", 0.0)\n'),
    ("policies.py", "                fd = tpot / SLO_TPOT + x3 + ", "                fd = tpot / SLO_TPOT + x3 + self.w_e * ENERGY.get(t, 1.0) + "),
]
ENERGY_B = 'ENERGY = {"hbm": 1.0, "custom_hbm": 0.8, "cxl_pnm": 0.5, "hbf": 0.4}   # relative energy per decoded token (ASSUMED)\n'
ARB_OLD = "            return claimants[0]                      # arbitration: first claimant in AGENT_ORDER\n"
ARB_ENERGY = '            return min(claimants, key=lambda t: (self.sim.o.get("w_energy", 0.0) * ENERGY[t], AGENT_ORDER.index(t)))\n'
P[("B", "S2")] = [      # minimal working change (passes the smoke criterion): energy-aware arbitration only
    ("arch_blackboard.py", "AGENT_ORDER = OFFLOAD            # arbitration priority: custom_hbm, then cxl_pnm\n",
     "AGENT_ORDER = OFFLOAD            # arbitration priority: custom_hbm, then cxl_pnm\n" + ENERGY_B),
    ("arch_blackboard.py", ARB_OLD, ARB_ENERGY),
]
P[("B", "S2full")] = P[("B", "S2")] + [      # sensitivity: energy also enters every Tier agent's headroom and the HBM budget threshold
    ("arch_blackboard.py", '        return self.node_iter(nd, ctx, view) <= self.sim.o["theta"] * SLO_TPOT\n',
     '        w_e = self.sim.o.get("w_energy", 0.0)\n        return self.node_iter(nd, ctx, view) <= self.sim.o["theta"] * SLO_TPOT * (1.0 + w_e * (ENERGY["hbm"] - ENERGY.get(self.tier, 1.0)))\n'),
    ("arch_blackboard.py", '        return (cap - free - idle + delta) / cap <= sim.o["rho_hi"]\n',
     '        return (cap - free - idle + delta) / cap <= sim.o["rho_hi"] / (1.0 + sim.o.get("w_energy", 0.0) * ENERGY["hbm"])\n'),
]
P[("A", "S3")] = [
    ("policies.py", "    def __init__(self, sim, eps=0.0):\n", "    def __init__(self, sim, eps=0.0, selector=None):\n"),
    ("policies.py", "        self.eps = eps\n", "        self.eps = eps\n        self.select_key = selector or (lambda r: r[0])        # Resource Selector: rank key over (cost, n_p, n_d, ttft, tpot)\n"),
    ("policies.py", "        results.sort(key=lambda x: x[0])\n", "        results.sort(key=self.select_key)\n"),
    ("engine.py", 'self.est = Estimator(self, o["eps"])', 'self.est = Estimator(self, o["eps"], o.get("selector"))'),
]
P[("B", "S3")] = [
    ("arch_blackboard.py", "    def __init__(self, sim):\n        self.sim = sim\n        self.posted = set()\n",
     "    def __init__(self, sim, arbitrate=None):\n        self.sim = sim\n        self.posted = set()\n        self.arbitrate = arbitrate or (lambda claimants: claimants[0])\n"),
    ("arch_blackboard.py", "            return claimants[0]                      # arbitration: first claimant in AGENT_ORDER\n", "            return self.arbitrate(claimants)\n"),
    ("nodeint.py", "        elif cand == N_BBRD:\n            self.board = TaskBoard(self)\n", '        elif cand == N_BBRD:\n            self.board = TaskBoard(self, self.o.get("arbitrate"))\n'),
]
P[("A", "S4")] = [
    ("policies.py", '"free", "evictable", "alive")', '"free", "evictable", "alive", "degraded")'),
    ("policies.py", "        self.free, self.evictable, self.alive = free, evictable, True\n", "        self.free, self.evictable, self.alive, self.degraded = free, evictable, True, frozenset()\n"),
    ("policies.py", '                if t == "hbf" and "hbf" not in P.mem:\n                    continue\n',
     '                if t == "hbf" and "hbf" not in P.mem:\n                    continue\n                if t in nv.degraded:\n                    continue\n'),
    ("engine.py", "        self.net_ver = 0\n", "        self.net_ver = 0\n        self.degraded_tiers = set()\n"),
    ("engine.py", "        return NodeView(i, nd.role, len(nd.dec), groups, nd.outstanding_prefill_tokens() + self.pending_tokens[i], len(nd.pf), free, ev)\n",
     "        nv = NodeView(i, nd.role, len(nd.dec), groups, nd.outstanding_prefill_tokens() + self.pending_tokens[i], len(nd.pf), free, ev)\n        nv.degraded = frozenset(self.degraded_tiers)\n        return nv\n"),
    ("arch_dispatcher.py", "            c.alive = nv.idx == node\n", "            c.alive = nv.idx == node\n            c.degraded = nv.degraded\n"),
]
P[("B", "S4")] = [
    ("arch_blackboard.py", "        self.sim, self.tier, self.board = sim, tier, board\n", "        self.sim, self.tier, self.board = sim, tier, board\n        self.degraded = False\n"),
    ("arch_blackboard.py", "        if free < delta:\n            return False\n        return self.headroom(sim.nodes[node], ctx, view)\n",
     "        if self.degraded or free < delta:\n            return False\n        return self.headroom(sim.nodes[node], ctx, view)\n"),
]
TITLES = {"S1": "new Tier (cxl_pnm2, CXL-PNM-class device with 2x internal BW)",
          "S2": "new objective term (relative energy per decoded token, weight w_E)",
          "S3": "policy swap (A: Selector argmin Cost -> min TTFT among TPOT-feasible; B: Task Board arbitration first claimant -> least-loaded claimant; constructor-injected)",
          "S4": "new telemetry signal (Tier degraded flag as hard constraint on the Decode attention tier)"}

# ---------------------------------------------------------------------------------------------- attribution rules
# (file, scope regex, added-line regex, component); first match wins. Scope = "Class.method" / "function" / "<module>".
RULES = [
    ("physics.py", r"<module>", r"DECODE_TIERS", "Candidate Generator"),
    ("physics.py", r"<module>", r"OFFLOAD", "Tier Admission Agents"),
    ("physics.py", r"<module>|system", r".*", "Tier Descriptors"),
    ("engine.py", r"Sim\._nodeview", r".*", "Tier Descriptors"),
    ("engine.py", r"Sim\.__init__", r"Estimator\(", "Resource Selector"),
    ("engine.py", r"Sim\.__init__", r"degraded_tiers", "Tier Descriptors"),
    ("policies.py", r"NodeView.*", r".*", "Tier Descriptors"),
    ("policies.py", r"<module>", r"ENERGY", "Cost Model"),
    ("policies.py", r"Estimator\.__init__", r"select_key|selector", "Resource Selector"),
    ("policies.py", r"Estimator\.__init__", r"w_e", "Cost Model"),
    ("policies.py", r"Estimator\.evaluate", r"select_key", "Resource Selector"),
    ("policies.py", r"Estimator\.evaluate", r"degraded", "Candidate Generator"),
    ("policies.py", r"Estimator\.evaluate", r"^\s*continue$", "Candidate Generator"),       # body of the degraded-tier skip (S4)
    ("policies.py", r"Estimator\.evaluate", r"w_e|ENERGY", "Cost Model"),
    ("arch_dispatcher.py", r"PendingLedger.*", r".*", "Tier Descriptors"),
    ("arch_dispatcher.py", r"DispatcherPlanner.*", r".*", "Dispatcher"),
    ("arch_dispatcher.py", r"HbmOpportunityCost.*", r".*", "Cost Model"),
    ("arch_blackboard.py", r"<module>", r"ENERGY", "Task Board"),
    ("arch_blackboard.py", r"TierAdmissionAgent.*|<module>", r".*", "Tier Admission Agents"),
    ("arch_blackboard.py", r"HbmBudgetAdmission.*", r".*", "HBM Budget Admission"),
    ("arch_blackboard.py", r"TaskBoard.*", r".*", "Task Board"),
    ("arch_blackboard.py", r"Poster.*", r".*", "Poster"),
    ("nodeint.py", r"NodeSim\.__init__", r"TaskBoard\(", "Task Board"),
]
# component -> [(file, spec)] sizes measured on the pristine copy (AST lines, blank/comment lines excluded)
SIZE = {
    "Tier Descriptors": [("physics.py", "func:system"), ("engine.py", "meth:Sim._nodeview"), ("policies.py", "class:NodeView"), ("arch_dispatcher.py", "class:PendingLedger")],
    "Candidate Generator": [("policies.py", "span:for nv in ndec_nodes:|results.append((cost, i, (d, t), ttft_p[i], tpot))")],
    "Cost Model": [("policies.py", "class:Estimator"), ("arch_dispatcher.py", "class:HbmOpportunityCost")],
    "Resource Selector": [("policies.py", "span:results.sort(key=lambda x: x[0])|return plan, ranked")],
    "Dispatcher": [("arch_dispatcher.py", "class:DispatcherPlanner")],
    "Task Board": [("arch_blackboard.py", "class:TaskBoard")],
    "Tier Admission Agents": [("arch_blackboard.py", "class:TierAdmissionAgent")],
    "HBM Budget Admission": [("arch_blackboard.py", "class:HbmBudgetAdmission")],
    "Poster": [("arch_blackboard.py", "class:Poster")],
}


def scope_at(tree, lineno):
    """Innermost 'Class.method' / 'function' containing `lineno` (1-based) or '<module>'."""
    best = "<module>"
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef):
            for m in node.body:
                if isinstance(m, ast.FunctionDef) and m.lineno <= lineno <= m.end_lineno:
                    return f"{node.name}.{m.name}"
            if node.lineno <= lineno <= node.end_lineno:
                best = node.name
        elif isinstance(node, ast.FunctionDef) and node.lineno <= lineno <= node.end_lineno and best == "<module>":
            best = node.name
    return best


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


def added_lines(base, work, file):
    a = (base / SRC / file).read_text().splitlines()
    new_src = (work / SRC / file).read_text()
    b = new_src.splitlines()
    tree = ast.parse(new_src)
    out = []
    sm = difflib.SequenceMatcher(None, a, b, autojunk=False)
    for tag, i1, i2, j1, j2 in sm.get_opcodes():
        if tag in ("insert", "replace"):
            for j in range(j1, j2):
                s = b[j]
                if s.strip() and not s.strip().startswith("#"):
                    out.append((scope_at(tree, j + 1), s))
    return out


def attribute(file, scope, line):
    for f, sc_rx, ln_rx, comp in RULES:
        if f == file and re.fullmatch(sc_rx, scope) and re.search(ln_rx, line):
            return comp
    raise SystemExit(f"unattributed added line in {file} [{scope}]: {line!r}")


def make_base(work):
    base = work / "base"
    if base.exists():
        shutil.rmtree(base)
    (base / "DP2").mkdir(parents=True)
    shutil.copytree(HERE, base / "DP2" / "sim", ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
    (base / "DP1").symlink_to(EVAL / "DP1")
    return base


def make_work(base, work, name, edits):
    d = work / name
    if d.exists():
        shutil.rmtree(d)
    shutil.copytree(base, d, symlinks=True)
    for file, old, new in edits:
        p = d / SRC / file
        t = p.read_text()
        if t.count(old) != 1:
            raise SystemExit(f"{name}: patch anchor not unique/missing in {file}: {old[:60]!r} (count {t.count(old)})")
        p.write_text(t.replace(old, new))
    return d


def run(cmd, cwd, env=None):
    import os
    e = dict(os.environ)
    e["PYTHONPATH"] = str(cwd)
    return subprocess.run(cmd, cwd=cwd, env=e, capture_output=True, text=True)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--work", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--no-smoke", action="store_true")
    a = ap.parse_args()
    work = Path(a.work)
    work.mkdir(parents=True, exist_ok=True)
    base = make_base(work)
    res = {"schema": "qa4_measured_counts v1", "date": "2026-10-10", "preregistration": "doc-mk/Evaluation/DP2/qa4-preregistration-arch.md",
           "evidence": "[B+C] proxy implementation in the DP2 simulator, not vLLM",
           "candidate_keys": {"C1": "A-Dispatcher", "C2": "B-Blackboard"}, "scenarios": {}}
    smoke = {}
    base_sim = base / "DP2" / "sim"
    if not a.no_smoke:
        smoke["base"] = json.loads(run([PY, str(HERE / "qa4_smoke_arch.py"), "--tree", str(base_sim), "--scenario", "BASE", "--cand", "A"], base_sim).stdout or "{}")
    variants = {}
    for sid, cands in (("S1", "AB"), ("S2", "AB"), ("S3", "AB"), ("S4", "AB"), ("S2full", "B")):
        row = {"title": TITLES.get(sid, TITLES["S2"] + " [variant: energy in every agent + budget]")}
        for cand in cands:
            d = make_work(base, work, f"{cand.lower()}_{sid.lower()}", P[(cand, sid)])
            per = {}
            for file in sorted(p.name for p in (d / SRC).glob("*.py")):
                for scope, line in added_lines(base, d, file):
                    comp = attribute(file, scope, line)
                    per.setdefault(comp, []).append((file, line))
            changes = []
            for comp, ls in per.items():
                changes.append(dict(module=comp, shared=comp in ("Tier Descriptors",), files=sorted({f for f, _ in ls}), loc_added=len(ls),
                                    module_size_loc=sum(span_loc(base, f, sp) for f, sp in SIZE[comp])))
            row[CAND_KEY[cand]] = {"changes": changes}
            if not a.no_smoke:
                dsim = d / "DP2" / "sim"
                t1 = run([PY, "test_node.py"], dsim)
                t2 = run([PY, "test_sim.py"], dsim)
                sm = run([PY, str(HERE / "qa4_smoke_arch.py"), "--tree", str(dsim), "--scenario", sid.replace("full", ""), "--cand", cand], dsim)
                try:
                    out = json.loads(sm.stdout)
                except Exception:
                    out = {"error": sm.stdout[-400:] + sm.stderr[-400:]}
                out["tests"] = {"test_node": "OK" if t1.returncode == 0 else "FAIL", "test_sim": "OK" if t2.returncode == 0 else "FAIL"}
                row.setdefault("smoke", {})[CAL_NAME[cand]] = out
        (variants if sid == "S2full" else res["scenarios"])[sid] = row
    res["variants"] = variants
    res["smoke_base"] = smoke.get("base")
    Path(a.out).parent.mkdir(parents=True, exist_ok=True)
    Path(a.out).write_text(json.dumps(res, indent=1))
    for sid, d in list(res["scenarios"].items()) + list(res["variants"].items()):
        print(sid, {c: [(x["module"], x["loc_added"], x["module_size_loc"]) for x in d[c]["changes"]] for c in ("C1", "C2") if c in d})


CAL_NAME = {"A": "A-Dispatcher", "B": "B-Blackboard"}

if __name__ == "__main__":
    main()
