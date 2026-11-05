#!/usr/bin/env python3
"""DP3 sensitivity (not part of the star evaluation): vary r (and rho for the ST-06 diagnosis) at load x1.0.
Baseline numbers come from results/data/<SYS>/dp3_results.json (same seeds, same rate).  Output: results/data/dp3_sensitivity.json
"""
import json, math, statistics as st, sys
from pathlib import Path
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import dp3sim as D, dp3_scenarios as SC
DATA = HERE.parent / "results" / "data"
SYSTEMS = ("SYS-H100", "SYS-B200")
VARS = [("C1 r=0.15", "offline", 0.15, 0.15), ("C1 r=0.30", "offline", 0.30, 0.15), ("C1 r=0.50", "offline", 0.50, 0.15),
        ("C2 r=0.15", "online", 0.15, 0.15), ("C2 r=0.30", "online", 0.30, 0.15), ("C2 r=0.50", "online", 0.50, 0.15),
        ("C1 r=0.30 rho=0 (diag)", "offline", 0.30, 0.0), ("C2 r=0.30 rho=0 (diag)", "online", 0.30, 0.0)]
def gm(x): x=[v for v in x if v>0 and math.isfinite(v)]; return math.exp(sum(map(math.log,x))/len(x))
res = {}
for sysid in SYSTEMS:
    system = D.load_system(sysid); d = json.loads((DATA/sysid/"dp3_results.json").read_text())
    for name, mode, r, rho in VARS:
        pol = D.Policy(name, mode, r, rho); tt=[]; hb=[]; st06=None
        for sid, ent in d["scenarios"].items():
            base = {x["seed"]: x for x in ent["runs"] if x["policy"]=="Baseline-As-Is" and x["load"]==1.0}
            if any(b["unfinished"] or b["ttft_p99"] is None or b["n"]<10 for b in base.values()): continue
            rt=[]; rh=[]
            for sd in d["seeds"]:
                s = D.summarize(D.run(SC.BY_ID[sid], system, pol, sd, ent["rate_used"]))
                rt.append(base[sd]["ttft_p99"]/s["ttft_p99"]); rh.append(base[sd]["hbm_gib"]/s["hbm_gib"])
            tt.append(st.mean(rt)); hb.append(st.mean(rh))
            if sid=="ST-06": st06=st.mean(rt)
        res[f"{sysid}|{name}"] = dict(ttft_ratio=gm(tt), hbm_ratio=gm(hb), n=len(tt), st06_ttft_ratio=st06)
        print(sysid, name, {k:(round(v,3) if v else v) for k,v in res[f'{sysid}|{name}'].items()})
(DATA/"dp3_sensitivity.json").write_text(json.dumps(res, indent=1))
