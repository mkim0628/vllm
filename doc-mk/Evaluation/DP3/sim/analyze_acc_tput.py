#!/usr/bin/env python3
"""DP3 accuracy x throughput joint analysis -> results/data/dp3_acc_tput_joint.json (+ tables on stdout).

    python analyze_acc_tput.py
Inputs : results/data/dp3_acc_tput.json (accuracy_throughput.py), accuracy/results/accuracy_summary.json + accuracy_raw.jsonl,
         results/data/dp3_summary.json (scenario mismatch m of the comparison-valid pairs).
Definitions (registered here before the numbers were looked at; the formulas are NOT in qa-evaluation-criteria.md -> 임시 정의):
  G(c, r)        = geometric mean over comparison-valid pairs of  Max-SLO-goodput(c, r) / Max-SLO-goodput(Baseline)   (QA1 definition)
  drop(c, r)     = F1 relative drop vs full KV.  C2 = aware(r).  C1 = (1-m)*repB(r) + m*repC(r), m = mean mismatch of the valid pairs.
  star_F1(drop)  = deck p.67: <=1% 3 stars, <=2% 2 stars, <=3% 1 star, else unmet  (point estimate)
  certified(X)   = upper 95% CI of drop <= X  (C1: linear sum of half-widths, same conservative rule as accuracy.py)
  R_acc(c, X)    = max G(c, r) over r in {1.0 (= Baseline, G=1, drop=0)} U {measured r} subject to drop(c, r) <= X   [iso-accuracy goodput]
  R_acc_cert     = same, but the constraint is on the upper CI bound.
  QGP(c, r)      = G(c, r) * (1 - drop(c, r)/100) with drop floored at 0     [F1-weighted goodput, provisional]
  n_required     = (1.96 * sd_paired / (0.01 * F1_full))^2  examples for a +-1% (relative) 95% half-width.
"""
import json
import math
import statistics as st
from pathlib import Path

HERE = Path(__file__).resolve().parent
DATA = HERE.parent / "results" / "data"
ACC = HERE.parent / "accuracy" / "results"
BOUNDS = (1.0, 2.0, 3.0)


def gm(x):
    # pairs whose candidate goodput is 0 (SLO never met) cannot enter a geometric mean; they are counted in n_zero and make the true G lower
    x = [v for v in x if v > 0]
    return math.exp(sum(map(math.log, x)) / len(x))


def stars(d):
    return 3 if d <= 1 else 2 if d <= 2 else 1 if d <= 3 else 0


def main():
    tp = json.loads((DATA / "dp3_acc_tput.json").read_text())
    summ = json.loads((DATA / "dp3_summary.json").read_text())
    acc = json.loads((ACC / "accuracy_summary.json").read_text())
    valid = tp["valid_pairs"]
    m = st.mean(summ["pairs"][k]["mismatch"] if "mismatch" in summ["pairs"][k] else 0 for k in valid)
    q5 = json.loads((DATA / "dp3_qa5.json").read_text())["_meta"]["mean_mismatch"]
    m = q5      # identical to accuracy.py (same pair set definition for the accuracy mapping)
    rows = {"C1": [], "C2": []}
    for r in map(str, tp["ratios"]):
        br = acc["by_ratio"][r]
        hw = lambda k: (br[k]["f1"]["ci95"][1] - br[k]["f1"]["ci95"][0]) / 2
        d = {k: br[k]["f1"]["rel_drop_pct"] for k in ("aware", "repB", "repC")}
        for c in ("C1", "C2"):
            g_pairs = [tp["pairs"][k][c][r] / tp["pairs"][k]["Baseline"] for k in valid]
            if c == "C2":
                drop, h = d["aware"], hw("aware")
            else:
                drop = (1 - m) * d["repB"] + m * d["repC"]
                h = (1 - m) * hw("repB") + m * hw("repC")
            G = gm(g_pairs)
            rows[c].append(dict(r=float(r), G=G, n_pairs=len(valid), n_zero=sum(v <= 0 for v in g_pairs), pairs_gt1=sum(v > 1.02 for v in g_pairs), pairs_lt1=sum(v < 0.98 for v in g_pairs),
                                drop=drop, ci_hw=h, upper=drop + h, star=stars(drop), qgp=G * (1 - max(drop, 0) / 100)))
    out = {"mean_mismatch": m, "rows": rows, "R_acc": {}, "control": tp["control_r0.3_vs_dp3_qa1"]}
    for c in rows:
        out["R_acc"][c] = {}
        for X in BOUNDS:
            ok = [x for x in rows[c] if x["drop"] <= X]
            okc = [x for x in rows[c] if x["upper"] <= X]
            out["R_acc"][c][str(X)] = dict(point=max([1.0] + [x["G"] for x in ok]), point_r=(max(ok, key=lambda x: x["G"])["r"] if ok and max(x["G"] for x in ok) > 1.0 else 1.0),
                                          certified=max([1.0] + [x["G"] for x in okc]))
    # required sample size (paired, per-example F1 differences vs full)
    raw = [json.loads(l) for l in (ACC / "accuracy_raw.jsonl").read_text().splitlines()]
    full = [next(c["f1"] for c in e["conds"] if c["cond"] == "full") for e in raw]
    F = st.mean(full)
    nreq = {}
    for cond in ("aware", "repB", "repC"):
        for r in map(str, tp["ratios"]):
            x = [next(c["f1"] for c in e["conds"] if c["cond"] == cond and str(c["r"]) == r) for e in raw]
            sd = st.stdev([a - b for a, b in zip(full, x)])
            nreq[f"{cond}@{r}"] = dict(sd=sd, n=len(raw), halfwidth_pct=1.96 * sd / math.sqrt(len(raw)) / F * 100, n_required_1pct=(1.96 * sd / (0.01 * F)) ** 2)
    out["n_required"] = nreq
    (DATA / "dp3_acc_tput_joint.json").write_text(json.dumps(out, indent=1))
    for c in rows:
        print(c)
        for x in rows[c]:
            print(f"  r={x['r']:.1f} G={x['G']:.3f} (pairs >1.02: {x['pairs_gt1']}/{x['n_pairs']}, <0.98: {x['pairs_lt1']}, zero-goodput pairs excluded from G: {x['n_zero']}) drop={x['drop']:.2f}% +-{x['ci_hw']:.2f} star={x['star']} QGP={x['qgp']:.3f}")
        print("  R_acc", json.dumps(out["R_acc"][c]))
    print("control", out["control"], "m", m)
    for k, v in nreq.items():
        print(k, {a: round(b, 2) for a, b in v.items()})


if __name__ == "__main__":
    main()
