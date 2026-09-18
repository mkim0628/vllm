from __future__ import annotations

FIRST_RESPONSE_SLO_MS = 2000.0
TPOT_SLO_MS = 50.0

def p99_slo_feasible(row: dict) -> bool:
    """A load point is sustainable only when both tail-latency SLOs hold."""
    return (
        row.get("ttft_p99_ms", float("inf")) <= FIRST_RESPONSE_SLO_MS
        and row.get("tpot_p99_ms", float("inf")) <= TPOT_SLO_MS
    )

def best_sustainable_rows(rows, candidate, names):
    """Max-goodput row per (scenario, seed), restricted to p99-SLO-feasible loads.

    Missing key means the candidate has no sustainable operating point for that
    scenario/seed under the current load sweep.
    """
    best = {}
    for r in rows:
        if r["candidate"] != candidate or r["scenario"] not in names:
            continue
        if not p99_slo_feasible(r):
            continue
        k = (r["scenario"], r["seed"])
        if k not in best or r["slo_goodput"] > best[k]["slo_goodput"]:
            best[k] = r
    return best

def all_keys(rows, names):
    return {
        (r["scenario"], r["seed"])
        for r in rows
        if r["scenario"] in names
    }
