import sys, collections, dataclasses
root=sys.argv[1]; sys.path.insert(0, root+"/DP2/sim")
from dp2sim.engine import *
from dp2sim.physics import system
from dp2sim.scenarios import SCENARIOS
# squeeze fixture: HBM pool ~ 1 session, ScHBM unavailable -> remaining decode tiers are cxl_pnm (+ cxl_pnm2 if present) and hbf
m=system("SYS-H100").memories
m["custom_hbm"]=dataclasses.replace(m["custom_hbm"], capacity_bytes=1)
sc=SCENARIOS["cb_kv_8k_b32"]
for cand in (C1,C2):
    s=Sim("SYS-H100",sc,11,cand,16,{"lam0":None,"horizon":120.0,"warmup":15.0,"max_horizon":200.0,"hbm_mult":0.001}); r=s.run()
    c=collections.Counter(x.n_d[1] for x in s.reqs if x.n_d is not None)
    print(root.split("/")[-1],cand,dict(c),"done",sum(1 for x in s.reqs if x.t_done),"gp %.0f"%r["qa"]["goodput_tok_s"])
