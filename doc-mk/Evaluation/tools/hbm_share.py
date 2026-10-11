#!/usr/bin/env python3
"""QA3 display values: HBM occupancy as a share of the HBM KV capacity (per pair, geometric mean over the comparison-valid pairs)
next to the Baseline/candidate reduction multiple that the star uses.  Output: tools/hbm_share.json

  DP1: tier_util.hbm of DP1/results/data/SYS-*/qa_result.json  (time-integrated occupied bytes / effective HBM capacity after the scenario's hbm multiplier)
       pairs = comparison_valid pairs of SYS-H100 and SYS-B200 (21, same set as the reported 146.6 / 142.7 / 178.0 GiB)
  DP2: results/data-hbm/qa_result.json (hbm_share = mean KV bytes resident in D-node HBM / usable HBM KV pool)
  DP3: dp3_summary pairs; share = hbm_gib / hbm_budget (usable HBM minus weights, times the scenario's KV fraction)
"""
import json
import math
import sys
from pathlib import Path

EVAL = Path(__file__).resolve().parent.parent
gm = lambda x: math.exp(sum(math.log(a) for a in x) / len(x))
out = {}

# DP1
C = {"Baseline": "Baseline-static", "C1": "C1-resource-driven", "C2": "C2-behavior-driven"}
sh = {k: [] for k in C}
gib = {k: [] for k in C}
for sysid in ("SYS-H100", "SYS-B200"):
    r = json.load(open(EVAL / "DP1/results/data" / sysid / "qa_result.json"))
    for setn in ("common_benchmark", "dp1_stress_benchmark", "dp1_dynamic_benchmark"):
        for sc, l in (r[setn].get("fit") or {}).items():
            if (l if isinstance(l, str) else l.get("fit")) != "comparison_valid":
                continue
            v = r[setn]["per_scenario"][sc]
            for k, c in C.items():
                sh[k].append(v[c]["tier_util"]["hbm"])
                gib[k].append(v[c]["tier_occ_gib"]["hbm"])
out["DP1"] = {k: dict(share=gm(sh[k]), gib=gm(gib[k]), n=len(sh[k])) for k in C}

# DP3
sys.path.insert(0, str(EVAL / "DP3" / "sim"))
import dp3sim as D  # noqa: E402
import dp3_scenarios as SC  # noqa: E402
summ = json.load(open(EVAL / "DP3/results/data/dp3_summary.json"))
P = {"Baseline": "Baseline-As-Is", "C1": "C1-Offline", "C2": "C2-Online"}
sh = {k: [] for k in P}
gib = {k: [] for k in P}
for key, e in summ["pairs"].items():
    if not e["valid"]:
        continue
    sysid, sid = key.split("/")
    b = D.hbm_budget(D.load_system(sysid), SC.BY_ID[sid], 45.0, 90.0)
    for k, p in P.items():
        sh[k].append(e["pol"][p]["hbm_gib"] * 2 ** 30 / b)
        gib[k].append(e["pol"][p]["hbm_gib"])
out["DP3"] = {k: dict(share=gm(sh[k]), gib=gm(gib[k]), n=len(sh[k])) for k in P}

# DP2 (after the instrumented re-run)
q = EVAL / "DP2/results/data-hbm/qa_result.json"
if q.exists():
    t = json.load(open(q))["tables"]["combined"]
    out["DP2"] = {k: dict(share=t[c]["hbm_share"], gib=t[c]["hbm_gib"], n=t[c]["n"]) for k, c in (("Baseline", "Baseline-PD-fixed"), ("C1", "C1-scheduling-time"), ("C2", "C2-plan-first"))
                  if c in t} if False else {c: dict(share=v.get("hbm_share"), gib=v.get("hbm_gib"), x=v.get("hbm_x"), n=v.get("n")) for c, v in t.items()}
(EVAL / "tools" / "hbm_share.json").write_text(json.dumps(out, indent=1, ensure_ascii=False))
print(json.dumps(out, indent=1, ensure_ascii=False)[:1500])
