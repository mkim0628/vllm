"""Iteration 4 summary: BURST_CAP_S sweep (results/data/burst/<cap>/SYS-*/qa_result.json) vs main result."""
import json, math, sys
from pathlib import Path
DATA = Path(__file__).resolve().parent.parent / "results" / "data"
SYS = ("SYS-H100", "SYS-B200"); B, C1, C2 = "Baseline-static", "C1-resource-driven", "C2-behavior-driven"
M6 = ("ttft_p50_ms", "ttft_p95_ms", "ttft_p99_ms", "tpot_p50_ms", "tpot_p95_ms", "tpot_p99_ms")
LAB = ("common_benchmark", "dp1_stress_benchmark", "dp1_dynamic_benchmark")
gm = lambda xs: math.exp(sum(math.log(max(1e-9, x)) for x in xs) / len(xs))

def load(root):
    return {s: json.load(open(root / s / "qa_result.json")) for s in SYS}

main = load(DATA)
pairs = [(s, l, k) for s in SYS for l in LAB for k, f in main[s][l]["fit"].items() if f == "comparison_valid"]

def summarize(R):
    ps = lambda p: R[p[0]][p[1]]["per_scenario"][p[2]]
    out = {}
    for c in (C1, C2):
        r99 = [ps(p)[c]["ttft_p99_ms"] / ps(p)[B]["ttft_p99_ms"] for p in pairs]
        out[c] = dict(
            qa1=gm([ps(p)[c]["max_goodput_tps"] / ps(p)[B]["max_goodput_tps"] for p in pairs]),
            qa2=gm([ps(p)[B][m] / ps(p)[c][m] for p in pairs for m in M6]),
            ttft99_geo=gm(r99), n_worse=sum(x > 1.02 for x in r99), worst=max(r99),
            cb=[ps(p)[c]["ttft_p99_ms"] / ps(p)[B]["ttft_p99_ms"] for p in pairs if p[2] in ("cb_kv_8k_b32", "cb_mixed_8k_b32", "cb_kv_8k_b32_ramp")],
            hbm_saving=1 / gm([ps(p)[c]["tier_occ_gib"]["hbm"] / ps(p)[B]["tier_occ_gib"]["hbm"] for p in pairs]),
            mig_gib=gm([ps(p)[c]["migration_gib"] + 1 for p in pairs]) - 1)
    return out

if __name__ == "__main__":
    rows = {"main": summarize(main)}
    for cap in ("2.0", "1.0", "0.5", "0.25"):
        root = DATA / "burst" / cap
        if all((root / s / "qa_result.json").exists() for s in SYS):
            rows[cap] = summarize(load(root))
    json.dump(rows, open(DATA / "burst" / "summary.json", "w"), indent=1)
    print(f"{'cap':>5} {'cand':>3} | QA1  QA2  HBMsav | TTFT99 geo  worse(n) worst | cb_kv_8k_b32/ramp/mixed")
    for k, v in rows.items():
        for c, x in v.items():
            print(f"{k:>5} {c[:2]:>3} | {x['qa1']:.3f} {x['qa2']:.3f} {x['hbm_saving']:.3f} | {x['ttft99_geo']:.3f} {x['n_worse']:>2} {x['worst']:.2f} | {' '.join(f'{y:.2f}' for y in x['cb'])}")
