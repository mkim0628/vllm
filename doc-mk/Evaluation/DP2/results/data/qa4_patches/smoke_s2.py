import sys, collections, dataclasses
root=sys.argv[1]; sys.path.insert(0, root+"/DP2/sim")
from dp2sim.engine import *
from dp2sim.scenarios import SCENARIOS
sc=SCENARIOS["dp2_long_ctx_decode_offload"]; load=sc.grid[len(sc.grid)//2]
for w in (0.0, 5.0):
  for cand in (C1,C2):
    o={"lam0":None,"horizon":120.0,"warmup":15.0,"max_horizon":200.0}
    if w: o["w_energy"]=w
    s=Sim("SYS-H100",sc,11,cand,load,o); r=s.run()
    c=collections.Counter(x.n_d[1] for x in s.reqs if x.n_d is not None)
    print(root.split("/")[-1],"w_E",w,cand,dict(c))
