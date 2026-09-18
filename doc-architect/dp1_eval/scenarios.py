from __future__ import annotations

import random
from dataclasses import dataclass
from model import DataObject, DATA_PRIORS, GIB, TIB

@dataclass(frozen=True)
class Scenario:
    name:str
    description:str
    data_mix:dict[str,float]
    context_tokens:int
    output_tokens:int
    batch_size:int
    object_count:int=24
    demand_scale:float=1.0
    size_scale:float=1.0
    horizon_s:int=180
    phase:str|None=None
    misclass_rate:float=0.0
    capacity_mult:float=1.0
    hbm_bw_mult:float=1.0
    host_bw_mult:float=1.0
    hbm_capacity_mult:float=1.0
    disabled_tiers:tuple[str,...]=()
    rag_index_total_gib:float|None=None
    latency_sensitivity_override:float|None=None
    target_tiers:tuple[str,...]=()

SIZE_GIB={
 "KV_CACHE":(4,18),
 "RAG_DATA":(16,96),
 "AGENT_MEMORY":(4,32),
 "TOOL_RESULT":(1,12),
 "LORA_ADAPTER":(.3,2.0),
 "MOE_EXPERT":(.8,5.0),
}
ACCESS_FRAC={
 "KV_CACHE":.45,"RAG_DATA":.025,"AGENT_MEMORY":.012,
 "TOOL_RESULT":.03,"LORA_ADAPTER":.18,"MOE_EXPERT":.22,
}
LIFE={
 "KV_CACHE":90,"RAG_DATA":300,"AGENT_MEMORY":360,
 "TOOL_RESULT":120,"LORA_ADAPTER":300,"MOE_EXPERT":300,
}
BASE_RATE={
 "KV_CACHE":.35,"RAG_DATA":.12,"AGENT_MEMORY":.06,
 "TOOL_RESULT":.10,"LORA_ADAPTER":.18,"MOE_EXPERT":.22,
}

def scenarios():
    S=[]; add=S.append

    # Explicit batch/context cells for KV decode placement.
    add(Scenario("kv_b1_c32k_cold_cxl","Cold latency-tolerant KV while Custom-HBM is reserved/unavailable; validates CXL-PNM Attention path.",{"KV_CACHE":1},32768,64,1,24,.75,
                 phase="cold_kv",disabled_tiers=("custom_hbm",),latency_sensitivity_override=.35,target_tiers=("hbm","cxl_pnm")))
    add(Scenario("kv_b16_c32k","KV baseline: moderate batch/context.",{"KV_CACHE":1},32768,64,16,24,1.0,
                 target_tiers=("hbm","custom_hbm","cxl_pnm")))
    add(Scenario("kv_b16_c32k_burst_chbm","Burst at a batch/context where HBM headroom is tight and Custom-HBM Attention can still meet TPOT.",{"KV_CACHE":1},32768,64,16,30,1.45,
                 phase="arrival_burst",hbm_capacity_mult=.28,latency_sensitivity_override=.75,target_tiers=("hbm","custom_hbm","cxl_pnm")))
    add(Scenario("kv_b64_c128k_cold","Cold/latency-tolerant KV; CXL-PNM attention offload can be useful.",{"KV_CACHE":1},131072,64,64,24,.85,
                 phase="cold_kv",target_tiers=("hbm","cxl_pnm","custom_hbm")))
    add(Scenario("kv_b256_c128k_burst","Large-batch burst; tests Custom-HBM attention offload and shared-link pressure.",{"KV_CACHE":1},131072,64,256,28,1.35,
                 phase="arrival_burst",target_tiers=("hbm","custom_hbm","cxl_pnm")))
    add(Scenario("kv_b64_c512k_long","Long-context KV pressure at large batch.",{"KV_CACHE":1},524288,64,64,24,1.0,1.15,
                 target_tiers=("hbm","custom_hbm","cxl_pnm")))
    add(Scenario("kv_b256_c512k_stress","Heavy cell: batch 256 × 512K context.",{"KV_CACHE":1},524288,64,256,30,1.2,1.2,
                 capacity_mult=.55,target_tiers=("hbm","custom_hbm","cxl_pnm","hbf")))

    # RAG index placement and in-memory / in-storage dot-product scenarios.
    add(Scenario("rag_1tib_b16","1 TiB read-mostly vector index; retrieval locality changes.",{"RAG_DATA":1},32768,96,16,10,.9,
                 rag_index_total_gib=1024,phase="hotness_flip",
                 target_tiers=("hbm","hbf","dram","ssd_pim")))
    add(Scenario("rag_8tib_b64_ssd_pim","8 TiB cold/long-lived vector DB, 64 concurrent queries; SSD-PIM dot-product path.",{"RAG_DATA":1},32768,96,64,12,1.0,
                 rag_index_total_gib=8192,target_tiers=("hbf","dram","ssd_pim")))
    add(Scenario("rag_8tib_b256_ssd_pim","Heavy RAG: 8 TiB vector DB, 256 concurrent queries.",{"RAG_DATA":1},32768,96,256,12,1.15,
                 rag_index_total_gib=8192,target_tiers=("hbf","dram","ssd_pim")))
    add(Scenario("kv_rag_b64_c128k","KV decode plus large RAG index at batch/query concurrency 64.",{"KV_CACHE":.55,"RAG_DATA":.45},131072,80,64,30,1.1,
                 rag_index_total_gib=2048,target_tiers=("hbm","custom_hbm","cxl_pnm","hbf","ssd_pim")))

    # Other AI runtime data.
    add(Scenario("agent_memory_long_lived","Long-lived episodic/semantic Agent Memory with sparse reuse.",{"AGENT_MEMORY":1},32768,96,64,28,.9,1.7,
                 target_tiers=("dram","cxl_pnm","hbf","ssd_pim")))
    add(Scenario("tool_result_bursty","Bursty tool/agent-state results reused over multiple steps.",{"TOOL_RESULT":1},32768,64,64,28,1.15,
                 phase="arrival_burst",target_tiers=("hbm","dram","hbf","ssd_pim")))
    add(Scenario("lora_multi_tenant_b64","Multi-LoRA serving with popularity skew.",{"LORA_ADAPTER":1},131072,64,64,32,1.05,
                 phase="bimodal",target_tiers=("hbm","hbf","dram")))
    add(Scenario("moe_expert_skew_b256","MoE routing skew under large batch.",{"MOE_EXPERT":1},131072,64,256,36,1.15,
                 phase="bimodal",target_tiers=("hbm","hbf","dram")))

    # Mixed resource dynamics.
    add(Scenario("mixed_all_ai_data_b64","All primary DP1 AI data classes coexist.",{
        "KV_CACHE":.32,"RAG_DATA":.22,"AGENT_MEMORY":.16,
        "TOOL_RESULT":.10,"LORA_ADAPTER":.10,"MOE_EXPERT":.10},
        131072,72,64,48,1.1,1.2,rag_index_total_gib=1024,
        target_tiers=("hbm","custom_hbm","cxl_pnm","dram","hbf","ssd_pim")))
    add(Scenario("hbm_pressure_ramp_b64","Progressive HBM pressure with KV/LoRA/MoE.",{"KV_CACHE":.55,"LORA_ADAPTER":.20,"MOE_EXPERT":.25},
        131072,64,64,42,1.15,1.2,phase="capacity_ramp",
        target_tiers=("hbm","custom_hbm","cxl_pnm","hbf","dram")))
    add(Scenario("hbm_bw_shock_b256","Sudden HBM bandwidth shock at batch 256.",{"KV_CACHE":.75,"MOE_EXPERT":.25},
        131072,64,256,32,1.25,phase="hbm_bw_shock",hbm_bw_mult=.28,
        target_tiers=("hbm","custom_hbm","cxl_pnm","hbf")))
    add(Scenario("host_path_pressure_b64","CPU/PCIe contention with RAG/Agent/Tool data.",{"RAG_DATA":.40,"AGENT_MEMORY":.35,"TOOL_RESULT":.25},
        131072,80,64,36,1.05,phase="host_bw_shock",host_bw_mult=.35,rag_index_total_gib=1024,
        target_tiers=("hbf","dram","cxl_pnm","ssd_pim")))
    add(Scenario("data_mix_shift_b64","Workload shifts from KV/LoRA to RAG/Agent.",{"KV_CACHE":.35,"RAG_DATA":.25,"AGENT_MEMORY":.20,"LORA_ADAPTER":.10,"TOOL_RESULT":.10},
        131072,72,64,44,1.1,phase="data_mix_shift",rag_index_total_gib=1024,
        target_tiers=("hbm","custom_hbm","cxl_pnm","dram","hbf","ssd_pim")))

    # Robustness/coverage: excluded from normal QA scoring by run_eval.
    add(Scenario("classifier_error","40% wrong type hints; validates C2 fallback/recovery.",{
        "KV_CACHE":.35,"RAG_DATA":.25,"AGENT_MEMORY":.20,"TOOL_RESULT":.10,"LORA_ADAPTER":.10},
        131072,72,64,40,1.1,misclass_rate=.40,rag_index_total_gib=1024,
        target_tiers=("hbm","custom_hbm","cxl_pnm","dram","hbf","ssd_pim")))
    add(Scenario("six_tier_capacity_stress","Capacity ladder intentionally exercises all six memories.",{
        "KV_CACHE":.30,"RAG_DATA":.25,"AGENT_MEMORY":.20,"TOOL_RESULT":.10,"LORA_ADAPTER":.08,"MOE_EXPERT":.07},
        131072,72,64,68,1.1,4.0,capacity_mult=.35,rag_index_total_gib=4096,
        target_tiers=("hbm","custom_hbm","cxl_pnm","dram","hbf","ssd_pim")))
    return S

def _choice(rng,mix):
    x=rng.random(); acc=0.0
    for k,w in mix.items():
        acc+=w
        if x<=acc: return k
    return next(reversed(mix))

def generate_trace(sc:Scenario,seed:int):
    rng=random.Random(seed*1009+sum(map(ord,sc.name)))
    objs=[]; classes=list(DATA_PRIORS)

    rag_count=max(1,round(sc.object_count*sc.data_mix.get("RAG_DATA",0))) if "RAG_DATA" in sc.data_mix else 0
    rag_each_gib=(sc.rag_index_total_gib/rag_count) if (sc.rag_index_total_gib and rag_count) else None

    for i in range(sc.object_count):
        dc=_choice(rng,sc.data_mix)
        lo,hi=SIZE_GIB[dc]
        size=(lo+(hi-lo)*rng.random())*GIB*sc.size_scale
        if dc=="KV_CACHE":
            # Llama-3.1-70B GQA ~= 320 KiB/token; one logical session object.
            size=max(size,327680*sc.context_tokens*(.75+.5*rng.random()))
        elif dc=="RAG_DATA" and rag_each_gib:
            size=rag_each_gib*GIB*(.85+.30*rng.random())

        base=BASE_RATE[dc]*(.65+.7*rng.random())*sc.demand_scale
        phase_time=None; phase_mult=1.0; hotmult=.75+.5*rng.random()

        if sc.phase in ("hotness_flip","data_mix_shift"):
            phase_time=sc.horizon_s//2
            phase_mult=3.0 if i%2==0 else .30
        elif sc.phase=="cold_kv":
            hotmult=.25+.20*rng.random()
        elif sc.phase=="bimodal":
            hotmult=2.0 if i%5==0 else .35

        arrival=0
        if sc.phase=="arrival_burst":
            arrival=(sc.horizon_s//2)+rng.randint(-4,4) if i>=sc.object_count//2 else rng.randint(0,8)

        life=max(60,int(LIFE[dc]*(.75+.5*rng.random())))
        if dc in ("RAG_DATA","AGENT_MEMORY","LORA_ADAPTER","MOE_EXPERT"):
            life=max(life,sc.horizon_s+30)

        prior=DATA_PRIORS[dc]
        hint=dc; confidence=.95
        if rng.random()<sc.misclass_rate:
            hint=rng.choice([x for x in classes if x!=dc])
            confidence=.55+.35*rng.random()

        objs.append(DataObject(
            oid=i,data_class=dc,size_bytes=size,base_rate=base,
            access_bytes=max(4096,size*ACCESS_FRAC[dc]),
            context_tokens=sc.context_tokens,output_tokens=sc.output_tokens,
            lifetime_s=life,arrival_s=arrival,batch_size=sc.batch_size,
            type_hint=hint,classification_confidence=confidence,
            hotness_mult=hotmult,phase_time=phase_time,phase_mult=phase_mult,
            latency_sensitivity=(sc.latency_sensitivity_override if sc.latency_sensitivity_override is not None else prior["latency"]),
            write_ratio=prior["write"],
            retrieval_dim=1024))
    return objs
