import sys, collections
root=sys.argv[1]; sys.path.insert(0, root+"/DP2/sim")
from dp2sim.engine import *
from dp2sim.scenarios import SCENARIOS
sc=SCENARIOS["cb_kv_8k_b32"]
for cand in (C1,C2):
    s=Sim("SYS-H100",sc,11,cand,24,{"lam0":None,"horizon":120.0,"warmup":15.0,"max_horizon":200.0})
    s.push(60.0,"ext",lambda sim: setattr(sim.nodes[0],"degraded",True))
    r=s.run()
    late=[x for x in s.reqs if x.t_disp is not None and x.t_disp>61.2]
    print(root.split("/")[-1],cand,"dispatched after degrade+1.2s:",len(late),"to node0:",sum(1 for x in late if x.n_p==0))
