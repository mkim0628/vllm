"""Candidate selection logic shared by the result generator and the PPT builder (all DPs).

Rule (codified in .claude/skills/evaluation/SKILL.md, H12):
  1. Star totals over QA1..QA4 per candidate (DP-official stars).
  2. Total gap >= 2 stars -> higher total wins, unless it is behind on the top-priority QA (then priority rule).
  3. Gap <= 1 star (tie or near tie) -> walk down the QA priority list; the first QA where stars differ decides.
  4. Report the outcome under the reversed priority too (decision sensitivity).
"""
from __future__ import annotations


def n(s: str) -> int:
    return s.count("★")


def select(stars: dict[str, dict[str, str]], priority: list[str]) -> dict:
    """stars: {cand: {"QA1": "★★", ...}}; priority: ["QA1", ...] (highest first)."""
    cands = list(stars)
    totals = {c: sum(n(stars[c][q]) for q in priority) for c in cands}

    def by_priority(order):
        for q in order:
            vals = {c: n(stars[c][q]) for c in cands}
            if len(set(vals.values())) > 1:
                best = max(vals.values())
                w = [c for c, v in vals.items() if v == best]
                if len(w) == 1:
                    return w[0], q
        return None, None

    ranked = sorted(cands, key=lambda c: -totals[c])
    gap = totals[ranked[0]] - totals[ranked[1]] if len(ranked) > 1 else 99
    top_p = priority[0]
    if gap >= 2 and n(stars[ranked[0]][top_p]) >= max(n(stars[c][top_p]) for c in cands):
        winner, why = ranked[0], "total"
        deciding = None
    else:
        winner, deciding = by_priority(priority)
        why = "priority" if winner else "undecided"
    rev, rev_q = by_priority(list(reversed(priority)))
    return dict(totals=totals, gap=gap, winner=winner, rule=why, deciding_qa=deciding,
                reversed_winner=rev, reversed_deciding_qa=rev_q)
