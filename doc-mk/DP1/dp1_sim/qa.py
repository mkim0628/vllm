"""QA rating per doc-mk/Evaluation/qa-evaluation-criteria.md (thresholds frozen there)."""

from __future__ import annotations

import math
import statistics


def weighted_pct(xs: list[float], q: float) -> float:
    if not xs:
        return float("nan")
    s = sorted(xs)
    k = max(0, min(len(s) - 1, math.ceil(q * len(s)) - 1))
    return s[k]


def stars(n: int) -> str:
    return "★" * n


def qa1_throughput(max_goodput: float, t_ref: float) -> int:
    if t_ref <= 0:
        return 0
    r = max_goodput / t_ref
    return 1 if r < 0.90 else (3 if r >= 1.10 else 2)


def qa2_latency(ttft_p99_s: float, tpot_p99_s: float) -> int:
    def ttft(v):
        return 3 if v <= 2.0 else (2 if v <= 4.0 else 1)

    def tpot(v):
        return 3 if v <= 0.050 else (2 if v <= 0.100 else 1)

    return min(ttft(ttft_p99_s), tpot(tpot_p99_s))


def qa3_utilization(useful_util: float) -> int:
    return 3 if useful_util >= 0.85 else (2 if useful_util >= 0.65 else 1)


def useful_utilization(r: dict) -> float:
    """QA3 metric (§6: utilisation bought with SLO violations / churn is not useful).

    useful_hbm_util = time-avg of (running-request KV + retained KV that is
    accessed again later, in hindsight) / HBM KV capacity, multiplied by the
    SLO attainment of the run. Lower-tier occupancy is a diagnostic
    (pool_util_mean), not the QA3 score, because it does not serve tokens.
    """
    return r["useful_hbm_util"] * r["slo_attainment"]


def max_slo_goodput(sweep: list[dict]) -> dict:
    """sweep: rows with 'load' and 'slo_goodput_tok_s' (averaged over seeds)."""
    best = max(sweep, key=lambda r: r["slo_goodput_tok_s"])
    return best


def aggregate_seeds(rows: list[dict]) -> dict:
    """Median over seeds + 95% CI half-width + CV (criteria §2.1)."""
    out = {}
    keys = [
        k
        for k, v in rows[0].items()
        if isinstance(v, (int, float)) and not isinstance(v, bool)
    ]
    for k in keys:
        vals = [
            r[k]
            for r in rows
            if isinstance(r.get(k), (int, float)) and not math.isnan(r[k])
        ]
        if not vals:
            out[k] = float("nan")
            continue
        out[k] = statistics.median(vals)
        if len(vals) > 1:
            sd = statistics.stdev(vals)
            out[k + "_ci95"] = 1.96 * sd / math.sqrt(len(vals))
            m = statistics.mean(vals)
            out[k + "_cv"] = sd / m if m else float("nan")
    for k, v in rows[0].items():
        if not isinstance(v, (int, float)) or isinstance(v, bool):
            out[k] = v
    return out


def qa_table(
    results: dict[str, dict],
    t_ref: float,
    evidence: dict[str, str],
    unc: float | None = None,
) -> str:
    """results[policy] = {max_goodput, ttft_p99_s, tpot_p99_s, useful_util} at the max-goodput load."""
    band = f", ±{unc * 100:.0f}%" if unc else ""
    lines = [
        "| QA | " + " | ".join(results) + " |",
        "|---|" + "---|" * len(results),
    ]
    row = []
    for p, r in results.items():
        row.append(
            f"{stars(qa1_throughput(r['max_goodput'], t_ref))} {r['max_goodput']:.0f} tok/s {evidence[p]}{band}"
        )
    lines.append("| QA1 Max SLO Goodput | " + " | ".join(row) + " |")
    row = []
    for p, r in results.items():
        row.append(
            f"{stars(qa2_latency(r['ttft_p99_s'], r['tpot_p99_s']))} TTFT {r['ttft_p99_s']:.2f}s / TPOT {r['tpot_p99_s'] * 1e3:.0f}ms {evidence[p]}{band}"
        )
    lines.append("| QA2 Latency (P99) | " + " | ".join(row) + " |")
    row = []
    for p, r in results.items():
        row.append(
            f"{stars(qa3_utilization(r['useful_util']))} {r['useful_util'] * 100:.0f}% {evidence[p]}"
        )
    lines.append("| QA3 Useful Resource Util. | " + " | ".join(row) + " |")
    lines.append(
        f"\nT_ref (B0 vLLM default Max SLO Goodput) = {t_ref:.0f} tok/s. "
        "QA2/QA3 at B0's max-goodput load for every candidate."
    )
    return "\n".join(lines)
