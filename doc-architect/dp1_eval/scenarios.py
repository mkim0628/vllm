from __future__ import annotations
import random
from dataclasses import dataclass, field
from model import DataObject, DATA_PRIORS, GIB, TIB

@dataclass(frozen=True)
class Scenario:
    name:str
    description:str
    data_mix:dict[str,float]
    context_tokens:int
    output_tokens:int
    object_count:int=28
    demand_scale:float=1.15
    size_scale:float=1.0
    horizon_s:int=180
    phase:str|None=None
    misclass_rate:float=0.0
    capacity_mult:float=1.0
    hbm_bw_mult:float=1.0
    host_bw_mult:float=1.0
    target_tiers:tuple[str,...]=()
    primary_data:tuple[str,...]=()

SIZE_GIB={
 "KV_CACHE":(4,18),"RAG_DATA":(8,48),"AGENT_MEMORY":(4,32),"TOOL_RESULT":(1,12),
 "LOG_DATA":(8,64),"LORA_ADAPTER":(.3,2.0),"MOE_EXPERT":(.8,5.0),
}
ACCESS_FRAC={"KV_CACHE":.45,"RAG_DATA":.025,"AGENT_MEMORY":.012,"TOOL_RESULT":.03,"LOG_DATA":.006,"LORA_ADAPTER":.18,"MOE_EXPERT":.22}
LIFE={"KV_CACHE":90,"RAG_DATA":220,"AGENT_MEMORY":300,"TOOL_RESULT":120,"LOG_DATA":360,"LORA_ADAPTER":300,"MOE_EXPERT":300}
BASE_RATE={"KV_CACHE":.45,"RAG_DATA":.15,"AGENT_MEMORY":.07,"TOOL_RESULT":.11,"LOG_DATA":.03,"LORA_ADAPTER":.22,"MOE_EXPERT":.26}

def scenarios():
    S=[]
    add=S.append
    add(Scenario("steady_hot_kv","Hot KV cache, stable load; HBM vs attention-capable offload.",{"KV_CACHE":1},32768,64,24,1.20,target_tiers=("hbm","custom_hbm","cxl_pnm"),primary_data=("KV_CACHE",)))
    add(Scenario("mixed_kv_rag","Interactive generation plus hot/cold retrieval corpus.",{"KV_CACHE":.58,"RAG_DATA":.42},32768,80,30,1.25,target_tiers=("hbm","hbf","dram","cxl_pnm"),primary_data=("KV_CACHE","RAG_DATA")))
    add(Scenario("rag_hot_cold_index","Large read-mostly RAG index with skewed query locality.",{"RAG_DATA":1},16384,96,36,1.15,1.8,phase="hotness_flip",target_tiers=("hbm","hbf","dram","ssd_pim"),primary_data=("RAG_DATA",)))
    add(Scenario("agent_memory_long_lived","Long-retained agent episodic/semantic memory with sparse re-use.",{"AGENT_MEMORY":1},16384,96,34,1.05,1.6,target_tiers=("dram","cxl_pnm","ssd_pim","hbf"),primary_data=("AGENT_MEMORY",)))
    add(Scenario("tool_result_bursty","Bursty tool results reused over several agent steps.",{"TOOL_RESULT":1},8192,64,32,1.35,phase="arrival_burst",target_tiers=("hbm","dram","hbf","ssd_pim"),primary_data=("TOOL_RESULT",)))
    add(Scenario("runtime_log_append","AI runtime/agent execution logs: append-heavy, long retention, rarely reread. Not SST/SSTable.",{"LOG_DATA":1},8192,32,36,.95,2.0,target_tiers=("dram","ssd_pim"),primary_data=("LOG_DATA",)))
    add(Scenario("lora_multi_tenant","Multi-LoRA serving with Zipf-like adapter popularity.",{"LORA_ADAPTER":1},16384,64,38,1.25,phase="bimodal",target_tiers=("hbm","hbf","dram"),primary_data=("LORA_ADAPTER",)))
    add(Scenario("moe_expert_skew","MoE experts with routed hot/cold skew.",{"MOE_EXPERT":1},16384,64,42,1.30,phase="bimodal",target_tiers=("hbm","hbf","dram"),primary_data=("MOE_EXPERT",)))
    add(Scenario("mixed_all_ai_data","All DP1 AI Runtime Data classes coexist.",{"KV_CACHE":.28,"RAG_DATA":.18,"AGENT_MEMORY":.14,"TOOL_RESULT":.10,"LOG_DATA":.08,"LORA_ADAPTER":.10,"MOE_EXPERT":.12},32768,72,52,1.30,1.2,target_tiers=("hbm","custom_hbm","cxl_pnm","dram","hbf","ssd_pim"),primary_data=tuple(DATA_PRIORS)))
    add(Scenario("hbm_pressure_ramp","HBM capacity progressively tightens while KV/LoRA/MoE stay active.",{"KV_CACHE":.55,"LORA_ADAPTER":.20,"MOE_EXPERT":.25},32768,64,44,1.35,1.3,phase="capacity_ramp",target_tiers=("hbm","custom_hbm","hbf","dram")))
    add(Scenario("hbm_bw_shock","Sudden HBM bandwidth shock tests C1 resource prediction/reaction.",{"KV_CACHE":.75,"MOE_EXPERT":.25},32768,64,32,1.35,phase="hbm_bw_shock",hbm_bw_mult=.28,target_tiers=("hbm","custom_hbm","cxl_pnm","hbf")))
    add(Scenario("host_path_pressure","CPU/PCIe path contention while RAG/agent/tool data are active.",{"RAG_DATA":.40,"AGENT_MEMORY":.35,"TOOL_RESULT":.25},24576,80,40,1.25,phase="host_bw_shock",host_bw_mult=.35,target_tiers=("hbf","dram","cxl_pnm","ssd_pim")))
    add(Scenario("resource_oscillation","Alternating HBM and host-path pressure.",{"KV_CACHE":.45,"RAG_DATA":.25,"AGENT_MEMORY":.15,"LORA_ADAPTER":.15},32768,72,42,1.30,phase="resource_oscillation",target_tiers=("hbm","custom_hbm","hbf","dram","cxl_pnm")))
    add(Scenario("hotness_flip","Previously cold data becomes hot and vice versa.",{"RAG_DATA":.35,"AGENT_MEMORY":.25,"LORA_ADAPTER":.20,"MOE_EXPERT":.20},24576,72,44,1.20,phase="hotness_flip",target_tiers=("hbm","hbf","dram","ssd_pim")))
    add(Scenario("data_mix_shift","Workload shifts from KV/LoRA to RAG/Agent halfway through.",{"KV_CACHE":.35,"RAG_DATA":.20,"AGENT_MEMORY":.15,"LORA_ADAPTER":.15,"TOOL_RESULT":.15},32768,72,48,1.25,phase="data_mix_shift",target_tiers=("hbm","custom_hbm","hbf","dram","cxl_pnm","ssd_pim")))
    add(Scenario("classifier_error","40% wrong DataDescriptor type hints; tests C2 mis-characterization risk.",{"KV_CACHE":.30,"RAG_DATA":.25,"AGENT_MEMORY":.20,"TOOL_RESULT":.10,"LORA_ADAPTER":.15},32768,72,42,1.25,misclass_rate=.40,target_tiers=("hbm","hbf","dram","cxl_pnm","ssd_pim")))
    add(Scenario("capacity_crunch","Artificially reduces all usable capacity to induce spill decisions.",{"KV_CACHE":.30,"RAG_DATA":.22,"AGENT_MEMORY":.18,"LOG_DATA":.10,"LORA_ADAPTER":.10,"MOE_EXPERT":.10},32768,72,60,1.20,2.4,capacity_mult=.32,target_tiers=("hbm","custom_hbm","cxl_pnm","dram","hbf","ssd_pim")))
    add(Scenario("long_context","Long-context KV plus RAG raises capacity and decode-read pressure.",{"KV_CACHE":.65,"RAG_DATA":.35},65536,96,36,1.20,1.5,target_tiers=("hbm","custom_hbm","cxl_pnm","hbf","dram")))
    add(Scenario("cold_archive_reactivation","Cold agent memories, tool results and logs are archived then sporadically reactivated.",{"AGENT_MEMORY":.45,"TOOL_RESULT":.25,"LOG_DATA":.30},16384,64,48,1.05,2.5,phase="reactivate",target_tiers=("dram","hbf","ssd_pim","cxl_pnm")))
    add(Scenario("six_tier_stress","Capacity ladder and mixed data intentionally create useful roles for all six target memories.",{"KV_CACHE":.22,"RAG_DATA":.20,"AGENT_MEMORY":.16,"TOOL_RESULT":.10,"LOG_DATA":.12,"LORA_ADAPTER":.10,"MOE_EXPERT":.10},32768,72,84,1.30,6.0,capacity_mult=.38,target_tiers=("hbm","custom_hbm","cxl_pnm","dram","hbf","ssd_pim"),primary_data=tuple(DATA_PRIORS)))
    return S

def _choice(rng,mix):
    x=rng.random(); acc=0
    for k,w in mix.items():
        acc+=w
        if x<=acc: return k
    return next(reversed(mix))

def generate_trace(sc:Scenario, seed:int):
    rng=random.Random(seed*1009+sum(map(ord,sc.name)))
    objs=[]
    classes=list(DATA_PRIORS)
    for i in range(sc.object_count):
        dc=_choice(rng,sc.data_mix)
        lo,hi=SIZE_GIB[dc]
        size=(lo+(hi-lo)*rng.random())*GIB*sc.size_scale
        if dc=="KV_CACHE":
            size=max(size,327680*sc.context_tokens*(.45+.55*rng.random()))
        base=BASE_RATE[dc]*(.55+.9*rng.random())*sc.demand_scale
        phase_time=None; phase_mult=1.0; hotmult=.7+0.6*rng.random()
        if sc.phase in ("hotness_flip","data_mix_shift","reactivate"):
            phase_time=sc.horizon_s//2
            if sc.phase=="reactivate": phase_mult=5.0 if i%3==0 else .7
            else: phase_mult=3.0 if i%2==0 else .28
        elif sc.phase=="bimodal":
            hotmult=2.0 if i%5==0 else .35
        arrival=0
        if sc.phase=="arrival_burst":
            arrival=(sc.horizon_s//2)+rng.randint(-5,5) if i>=sc.object_count//2 else rng.randint(0,10)
        life=max(60,int(LIFE[dc]*(.7+.7*rng.random())))
        if dc in ("AGENT_MEMORY","LOG_DATA","LORA_ADAPTER","MOE_EXPERT"): life=max(life,sc.horizon_s+30)
        prior=DATA_PRIORS[dc]
        hint=dc
        if rng.random()<sc.misclass_rate:
            hint=rng.choice([x for x in classes if x!=dc])
        access_frac=ACCESS_FRAC[dc]*(.7+.6*rng.random())
        objs.append(DataObject(
            oid=i,data_class=dc,size_bytes=size,base_rate=base,access_bytes=max(4096,size*access_frac),
            context_tokens=sc.context_tokens,output_tokens=sc.output_tokens,lifetime_s=life,arrival_s=arrival,
            type_hint=hint,hotness_mult=hotmult,phase_time=phase_time,phase_mult=phase_mult,
            latency_sensitivity=prior["latency"],write_ratio=prior["write"]))
    return objs
