"""Oracle-capture stars for QA1/QA2/QA3 (DP1 rating v6, proposal): star 3 iff pooled capture >= X (literature, qa-capture-literature.md),
star 1 iff the aggregate is worse than Baseline beyond noise (same lower edges as before), else star 2.

capture per pair  = ln(gain_cand) / ln(gain_oracle)  over pairs whose Oracle gain exceeds the null-noise band
  QA1: gain = goodput ratio vs Baseline, Oracle = Oracle-ideal       (free migration, perfect future rate)
  QA2: gain = 6-metric latency improvement geomean, Oracle = Oracle-lean   (free migration, accessed objects on HBM)
  QA3: gain = HBM saving factor (Baseline GiB / GiB),  Oracle = Oracle-lean (only the per-tick active set in HBM)
pooled capture = sum ln(gain_cand) / sum ln(gain_oracle)  (ratio of mean log gains, the convention of the literature point values)

    python capture_stars.py  -> results/data/oracle/capture_stars.json
"""
import json, math, random, statistics
from pathlib import Path
DATA = Path(__file__).resolve().parent.parent / "results" / "data"
SYS = ("SYS-H100", "SYS-B200"); LAB = ("common_benchmark", "dp1_stress_benchmark", "dp1_dynamic_benchmark")
B, C1, C2 = "Baseline-static", "C1-resource-driven", "C2-behavior-driven"
M6 = ("ttft_p50_ms", "ttft_p95_ms", "ttft_p99_ms", "tpot_p50_ms", "tpot_p95_ms", "tpot_p99_ms")
NOISE = json.load(open(DATA / "star_basis.json"))["summary"]
BAND = {"qa1": NOISE["qa1_ratio"]["p95_band"][1], "qa2": NOISE["qa2_improvement"]["p95_band"][1], "qa3": NOISE["qa3_saving"]["p95_band"][1]}
LOW = {"qa1": 0.97, "qa2": 0.95, "qa3": 0.95}   # unchanged lower edges (noise based, star 1 below)
X = 0.80
gm = lambda xs: math.exp(sum(math.log(max(1e-9, x)) for x in xs) / len(xs))


def load(root=None):
    """pairs with Baseline/C1/C2 from root/<SYS>/qa_result.json (default: main results; ablation: results/data/ablation/<tag>)."""
    root = Path(root) if root else DATA
    R = {s: json.load(open(root / s / "qa_result.json")) for s in SYS}
    OI = {s: json.load(open(DATA / "oracle" / s / "oracle_ideal.json")) for s in SYS}
    OL = {s: json.load(open(DATA / "oracle" / s / "oracle_lean.json")) for s in SYS}
    rows = []
    for s in SYS:
        for l in LAB:
            for k, f in R[s][l]["fit"].items():
                if f == "comparison_valid":
                    ps = R[s][l]["per_scenario"][k]
                    rows.append(dict(sys=s, sc=k, B=ps[B], C1=ps[C1], C2=ps[C2], OI=OI[s][l][k], OL=OL[s][l][k]))
    return rows


def gain(r, who, qa):
    x = r[who]
    if qa == "qa1": return x["max_goodput_tps"] / r["B"]["max_goodput_tps"]
    if qa == "qa2": return gm([r["B"][m] / x[m] for m in M6])
    return r["B"]["tier_occ_gib"]["hbm"] / x["tier_occ_gib"]["hbm"]


def per_qa(rows, qa):
    ref = "OI" if qa == "qa1" else "OL"
    pairs = []
    for r in rows:
        go = gain(r, ref, qa)
        pairs.append(dict(sys=r["sys"], sc=r["sc"], oracle=go, c1=gain(r, "C1", qa), c2=gain(r, "C2", qa), head=go > BAND[qa]))
    h = [p for p in pairs if p["head"]]
    out = dict(n_pairs=len(pairs), n_head=len(h), oracle_geo=gm([p["oracle"] for p in h]) if h else None)
    for w in ("c1", "c2"):
        agg_all = gm([p[w] for p in pairs])                      # Baseline-relative aggregate over all valid pairs (star-1 test)
        cap = (sum(math.log(p[w]) for p in h) / sum(math.log(p["oracle"]) for p in h)) if h else None
        mean = statistics.mean(max(-1.0, min(1.0, math.log(p[w]) / math.log(p["oracle"]))) for p in h) if h else None
        bs = []
        random.seed(7)
        for _ in range(4000):
            s = [random.choice(h) for _ in h]
            bs.append(sum(math.log(p[w]) for p in s) / sum(math.log(p["oracle"]) for p in s))
        bs.sort()
        star = 1 if agg_all < LOW[qa] else (3 if (cap is not None and cap >= X) else 2)
        out[w] = dict(capture=cap, mean=mean, ci=[bs[100], bs[3900]], agg_vs_baseline=agg_all, star=star,
                      over_oracle=sum(1 for p in h if p[w] > p["oracle"] * 1.01))
    out["pairs"] = pairs
    return out


def stars_all():
    """{system id or INT-H100-B200: {qa: per_qa result}} (per-system uses only that system's pairs)."""
    rows = load()
    out = {"INT-H100-B200": {qa: per_qa(rows, qa) for qa in ("qa1", "qa2", "qa3")}}
    for sid in SYS:
        rs = [r for r in rows if r["sys"] == sid]
        out[sid] = {qa: per_qa(rs, qa) for qa in ("qa1", "qa2", "qa3")}
    return out


if __name__ == "__main__":
    rows = load()
    res = {qa: per_qa(rows, qa) for qa in ("qa1", "qa2", "qa3")}
    json.dump(res, open(DATA / "oracle" / "capture_stars.json", "w"), indent=1)
    json.dump(stars_all(), open(DATA / "oracle" / "capture_stars_by_system.json", "w"), indent=1)
    for qa, v in res.items():
        print(f"{qa}: pairs {v['n_pairs']} headroom {v['n_head']} oracle geo {v['oracle_geo']:.3f}")
        for w in ("c1", "c2"):
            a = v[w]; print(f"   {w}: capture {a['capture']:.2f} (mean {a['mean']:.2f}, 95% {a['ci'][0]:.2f}~{a['ci'][1]:.2f}) agg vs Baseline {a['agg_vs_baseline']:.3f} over-oracle {a['over_oracle']} star {a['star']}")
