"""Capture ratio vs Oracle-approx: (cand - base) / (oracle - base), per (scenario, system) pair, per QA metric."""
import json, math, statistics, sys
from pathlib import Path
DATA = Path(__file__).resolve().parent.parent / "results" / "data"
SYS = ("SYS-H100", "SYS-B200"); LAB = ("common_benchmark", "dp1_stress_benchmark", "dp1_dynamic_benchmark")
B, C1, C2 = "Baseline-static", "C1-resource-driven", "C2-behavior-driven"
M6 = ("ttft_p50_ms", "ttft_p95_ms", "ttft_p99_ms", "tpot_p50_ms", "tpot_p95_ms", "tpot_p99_ms")
NOISE = {"qa1": 0.033, "qa2": 0.028, "qa3": 0.016}   # 95% null bands from star_basis.json (Baseline vs Baseline)

def load():
    R = {s: json.load(open(DATA / s / "qa_result.json")) for s in SYS}
    import sys
    FN = "oracle_ideal.json" if "--ideal" in sys.argv else "oracle.json"
    O = {s: json.load(open(DATA / "oracle" / s / FN)) for s in SYS}
    rows = []
    for s in SYS:
        for l in LAB:
            for k, f in R[s][l]["fit"].items():
                if f == "comparison_valid":
                    ps = R[s][l]["per_scenario"][k]
                    rows.append(dict(sys=s, lab=l, sc=k, B=ps[B], C1=ps[C1], C2=ps[C2], O=O[s][l][k]))
    return rows

gm = lambda xs: math.exp(sum(math.log(max(1e-9, x)) for x in xs) / len(xs))
def metric(r, who, qa):
    x = r[who]
    if qa == "qa1": return x["max_goodput_tps"]                       # higher better
    if qa == "qa2": return gm([r["B"][m] / x[m] for m in M6]) if who != "B" else 1.0   # improvement vs Baseline, higher better
    if qa == "qa3": return r["B"]["tier_occ_gib"]["hbm"] / x["tier_occ_gib"]["hbm"] if who != "B" else 1.0  # saving, higher better

def table(qa):
    out = []
    for r in rows:
        b = 1.0 if qa != "qa1" else metric(r, "B", qa)
        o, c1, c2 = (metric(r, w, qa) for w in ("O", "C1", "C2"))
        rel = (o / b) if qa == "qa1" else o   # oracle gain as a ratio vs Baseline
        head = rel - 1.0
        cap = lambda c: ((c - b) / (o - b)) if abs(o - b) > 1e-9 else None
        out.append(dict(sys=r["sys"], sc=r["sc"], base=b, o=o, c1=c1, c2=c2, ratio_o=rel, head=head,
                        has_headroom=head > NOISE[qa], cap1=cap(c1), cap2=cap(c2), c1_over=c1 > o * 1.01, c2_over=c2 > o * 1.01))
    return out

rows = load()
if __name__ == "__main__":
    res = {}
    for qa in ("qa1", "qa2"):
        t = table(qa); hv = [x for x in t if x["has_headroom"]]
        def agg(key):
            v = [x[key] for x in hv if x[key] is not None]
            return dict(n=len(v), mean=statistics.mean(v), median=statistics.median(v))
        # pooled capture on the geomean scale: log(cand/base) / log(oracle/base)
        def pooled(w):
            num = sum(math.log(max(1e-9, x[w] / (x["base"] if qa == "qa1" else 1.0))) for x in hv); den = sum(math.log(max(1e-9, x["o"] / (x["base"] if qa == "qa1" else 1.0))) for x in hv)
            return num / den if den else None
        res[qa] = dict(n_pairs=len(t), n_headroom=len(hv), oracle_geo_ratio=gm([x["ratio_o"] for x in t]), oracle_geo_ratio_headroom=gm([x["ratio_o"] for x in hv]) if hv else None,
                       C1=dict(**agg("cap1"), pooled=pooled("c1"), over_oracle=sum(x["c1_over"] for x in t)), C2=dict(**agg("cap2"), pooled=pooled("c2"), over_oracle=sum(x["c2_over"] for x in t)), pairs=t)
    json.dump(res, open(DATA / "oracle" / ("capture_ideal.json" if "--ideal" in sys.argv else "capture.json"), "w"), indent=1)
    for qa, v in res.items():
        print(f"{qa}: pairs {v['n_pairs']} with headroom(>{NOISE[qa]:.1%}) {v['n_headroom']} | Oracle geo ratio all {v['oracle_geo_ratio']:.3f} headroom-only {v['oracle_geo_ratio_headroom']:.3f}")
        for c in ("C1", "C2"):
            a = v[c]; print(f"   {c}: capture mean {a['mean']:.2f} median {a['median']:.2f} pooled {a['pooled']:.2f} | exceeds oracle (>1%) in {a['over_oracle']} pairs")
