"""Explicit-state BFS checker + CLI.

  uv run --no-project python check.py --nodes 2 [--max-states N] [--variants a,b] [--out file]
"""
import argparse
import json
import os
import sys
import time
from collections import deque

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import invariants as inv  # noqa: E402
import protocols  # noqa: E402

DEFAULT_OUT = {2: "protocol_check.json", 3: "protocol_check_n3.json"}
DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "results", "data")


def explore(system, max_states=2_000_000):
    init = system.initial()
    visited = {init: 0}
    parent = [(-1, None)]
    found = {}
    q = deque([init])
    capped = False
    for iv, msg in system.check_state(init):
        found.setdefault(iv, (0, None, msg))
    transitions = 0
    while q:
        s = q.popleft()
        i = visited[s]
        for a, s2, viols in system.successors(s):
            transitions += 1
            for iv, msg in viols:
                if iv not in found:
                    found[iv] = (i, a, msg)
            j = visited.get(s2)
            if j is None:
                if len(visited) >= max_states:
                    capped = True
                    continue
                j = len(parent)
                visited[s2] = j
                parent.append((i, a))
                q.append(s2)
                for iv, msg in system.check_state(s2):
                    if iv not in found:
                        found[iv] = (j, None, msg)
    cex = {}
    for iv, (idx, last, msg) in found.items():
        acts = []
        while idx > 0:
            idx, a = parent[idx][0], parent[idx][1]
            acts.append(a)
        acts.reverse()
        if last is not None:
            acts.append(last)
        cex[iv] = (acts, msg)
    return dict(states=len(visited), transitions=transitions, capped=capped, cex=cex)


def replay(system, actions):
    """Re-execute an action list from the initial state; returns (trace, final violations)."""
    s = system.initial()
    trace, viols = [], []
    for k, a in enumerate(actions):
        if a not in system.enabled(s):
            raise ValueError("action %r not enabled at step %d" % (a, k))
        det, s, v = system.describe(s, a)
        trace.append(det)
        viols = v
        if k == len(actions) - 1:
            viols = v + system.check_state(s)
    return trace, viols


def run_variant(name, nodes, max_states, prefetch=True):
    t0 = time.time()
    sysm = protocols.build(name, nodes, prefetch)
    r = explore(sysm, max_states)
    el = time.time() - t0
    meta = protocols.VARIANTS[name]
    invs = {}
    for iv in inv.ALL:
        if iv in r["cex"]:
            acts, msg = r["cex"][iv]
            trace, _ = replay(sysm, acts)
            invs[iv] = dict(result="violated", message=msg, cex_length=len(acts), trace=trace)
        else:
            invs[iv] = dict(result="pass" if not r["capped"] else "no_violation_found_exploration_capped")
    return dict(variant=name, kind=meta["kind"], description=meta["description"] if "description" in meta else meta["desc"],
                expected_violations=meta["expected"], invariants=invs, states=r["states"],
                transitions=r["transitions"], capped=r["capped"], complete=not r["capped"],
                seconds=round(el, 2),
                params=dict(nodes=nodes, prefetch=prefetch, max_states=max_states))


LIMITATIONS = [
    "Design-level abstract model of non-coherent caches; not a verification of real CPU/CXL hardware memory models.",
    "A pass means 'no counterexample inside this model and this explored scope', not correctness of an implementation.",
    "Safety only (I1..I4); liveness/progress (e.g. spinning forever on a stale line) is not checked.",
    "Scope: one block lifetime with one re-allocation, 2 (or 3) nodes + lock manager host / metadata server host, one global lock stripe, single-word cells, bounded request counts.",
    "DMA read is modeled as synchronous per word; allocator state is folded into the entry cell (single region).",
    "Lock manager placement, slot layout/reuse rules, stale slot-body assumption: author assumptions, see README.",
]


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--nodes", type=int, choices=(2, 3), default=2)
    ap.add_argument("--max-states", type=int, default=1_500_000)
    ap.add_argument("--variants", default="")
    ap.add_argument("--no-prefetch", action="store_true")
    ap.add_argument("--out", default="")
    ap.add_argument("--no-write", action="store_true")
    a = ap.parse_args(argv)
    names = [v for v in a.variants.split(",") if v] or list(protocols.VARIANTS)
    results = []
    print("%-32s %-8s %10s %6s %8s  %s" % ("variant", "kind", "states", "capped", "time(s)", "invariants"))
    for n in names:
        r = run_variant(n, a.nodes, a.max_states, not a.no_prefetch)
        results.append(r)
        s = " ".join("%s:%s" % (k, "CEX(len %d)" % v["cex_length"] if v["result"] == "violated" else "ok"
                              if v["result"] == "pass" else "ok?") for k, v in r["invariants"].items())
        print("%-32s %-8s %10d %6s %8.1f  %s" % (n, r["kind"], r["states"], r["capped"], r["seconds"], s))
        sys.stdout.flush()
    out = a.out or os.path.join(DATA_DIR, DEFAULT_OUT[a.nodes])
    doc = dict(model="DP4 protocol model check (abstract non-coherent CXL shared memory)",
               evidence="[C] design-level model", params=dict(nodes=a.nodes, max_states=a.max_states,
               prefetch=not a.no_prefetch), invariant_definitions=inv.DESCRIPTION,
               limitations=LIMITATIONS, results=results)
    if not a.no_write:
        os.makedirs(os.path.dirname(os.path.abspath(out)), exist_ok=True)
        with open(out, "w") as f:
            json.dump(doc, f, indent=1, ensure_ascii=False)
        print("wrote", os.path.abspath(out))
    return doc


if __name__ == "__main__":
    main()
