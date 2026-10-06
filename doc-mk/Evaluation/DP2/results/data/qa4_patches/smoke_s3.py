import sys, collections
root=sys.argv[1]; sys.path.insert(0, root+"/DP2/sim")
from dp2sim.engine import *
from dp2sim.scenarios import SCENARIOS
sc=SCENARIOS["cb_kv_8k_b32"]
for new in (False, True):
  for cand in (C1,C2):
    calls=[0]
    def sel(r, calls=calls):
        calls[0]+=1
        return r[3]            # TPOT feasibility is enforced by candidate generation; pick min TTFT
    o={"lam0":None,"horizon":120.0,"warmup":15.0,"max_horizon":200.0}
    if new: o["selector"]=sel
    s=Sim("SYS-H100",sc,11,cand,24,o); r=s.run()
    c=collections.Counter(x.n_p for x in s.reqs if x.n_p is not None)
    print(root.split("/")[-1],"new_selector",new,cand,"calls",calls[0],"n_p",dict(c),"ttft99 %.2f"%r["qa"]["ttft_p99_s"])
