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
    # Deterministic object plan (dynamic benchmark). Each entry:
    #   (data_class, count, arrival_lo_s, arrival_hi_s, rate_mult, rate_schedule)
    # rate_schedule = ((t0, mult), ...). When non-empty it replaces the random data_mix draw and
    # object_count (existing scenarios leave it empty and keep their exact traces).
    plan:tuple=()
    # Short Korean one-line summary (<=60 chars) for docs/tables. Documentation only: never read by the
    # simulator. Empty -> looked up by name in BRIEFS (below) in __post_init__.
    brief:str=""

    def __post_init__(self):
        if not self.brief:
            object.__setattr__(self,"brief",BRIEFS.get(self.name,""))

BRIEFS={
 # Common benchmark realization (CB-1..CB-3, doc-mk/Evaluation/common-benchmark.md)
 "cb_kv_8k_b32":"KV만, 8K/256, batch 32, HBM 빠듯",
 "cb_kv_8k_b32_ramp":"KV만, 8K/256, HBM 압박이 점진 증가",
 "cb_mixed_8k_b32":"KV+LoRA+MoE+Agent/Tool 혼합, HBM 빠듯",
 # DP1 stress benchmark
 "kv_b1_c32k_cold_cxl":"차가운 32K KV, ScHBM 불가 (CXL-PNM 경로)",
 "kv_b16_c32k":"중간 batch/context KV 기준선",
 "kv_b16_c32k_burst_chbm":"32K KV, HBM 여유 적을 때 도착 burst",
 "kv_hbm_relief_behavior_recovery":"HBM 압박 후 회복, hot KV 재승격",
 "kv_b64_c128k_cold":"차가운 128K KV, batch 64 (CXL-PNM attention)",
 "kv_b256_c128k_burst":"128K KV 대형 batch burst, 공유 링크 압박",
 "kv_b64_c512k_long":"512K 초장문 KV, batch 64",
 "kv_b256_c512k_stress":"512K x batch 256 최대 KV 셀",
 "rag_1tib_b16":"1 TiB read-mostly 벡터 인덱스, 지역성 변화",
 "rag_8tib_b64_ssd_pim":"8 TiB 벡터 DB, 동시 질의 64 (SSD-PIM)",
 "rag_8tib_b256_ssd_pim":"8 TiB 벡터 DB, 동시 질의 256",
 "kv_rag_b64_c128k":"KV decode + 대용량 RAG 인덱스 경합",
 "agent_memory_long_lived":"장기 보존 Agent Memory, 드문 재사용",
 "tool_result_bursty":"Tool 결과가 burst로 생성되어 반복 참조",
 "lora_multi_tenant_b64":"Multi-LoRA, 인기도 skew",
 "moe_expert_skew_b256":"MoE expert 라우팅 skew, 대형 batch",
 "mixed_all_ai_data_b64":"6종 AI data class 공존",
 "hbm_pressure_ramp_b64":"KV/LoRA/MoE, HBM 압박 점진 증가",
 "hbm_bw_shock_b256":"batch 256 중 HBM 대역폭 급락",
 "host_path_pressure_b64":"RAG/Agent/Tool + host PCIe/CPU 경합",
 "data_mix_shift_b64":"워크로드가 KV/LoRA에서 RAG/Agent로 이동",
 "behavior_flip_stress":"객체별 hotness 급반전 (thrashing 유발)",
 "six_tier_capacity_stress":"용량 사다리로 6개 메모리 전부 사용",
 # DP1 dynamic benchmark
 "dyn_cold_resident_chat_wave":"idle Agent Memory가 HBM 선점 후 chat 폭주",
 "dyn_idle_kv_holds_hbm":"tool 대기 중 idle KV가 HBM 점유, hot 세션 도착",
 "dyn_kv_hotset_recency_shift":"hot 대화가 초기 세션에서 최근 세션으로 이동",
 "dyn_kv_rotating_hotset":"사용자 그룹이 60 s 주기로 번갈아 활성",
 "dyn_rag_shard_hotset_shift":"벡터 shard 인기도가 중간에 뒤바뀜",
 "dyn_host_path_contention_kv":"중간에 host link 대역폭 25%로 저하",
}

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
    add(Scenario("kv_b1_c32k_cold_cxl","Cold latency-tolerant KV while ScHBM is reserved/unavailable; validates CXL-PNM Attention path.",{"KV_CACHE":1},32768,64,1,24,.15,
                 phase="cold_kv",disabled_tiers=("custom_hbm",),latency_sensitivity_override=.35,target_tiers=("hbm","cxl_pnm")))
    add(Scenario("kv_b16_c32k","KV baseline: moderate batch/context.",{"KV_CACHE":1},32768,64,16,24,1.0,
                 target_tiers=("hbm","custom_hbm","cxl_pnm")))
    add(Scenario("kv_b16_c32k_burst_chbm","Burst at a batch/context where HBM headroom is tight and ScHBM Attention can still meet TPOT.",{"KV_CACHE":1},32768,64,16,30,1.45,
                 phase="arrival_burst",hbm_capacity_mult=.12,latency_sensitivity_override=.75,target_tiers=("hbm","custom_hbm","cxl_pnm")))
    add(Scenario("kv_hbm_relief_behavior_recovery","HBM starts pressured and then recovers; tests whether C2 can promote behaviorally hot KV while C1 remains resource-triggered.",{"KV_CACHE":1},32768,64,16,24,.35,
                 phase="hbm_relief",hbm_capacity_mult=.12,
                 latency_sensitivity_override=.55,target_tiers=("dram","hbm","custom_hbm","cxl_pnm")))
    add(Scenario("kv_b64_c128k_cold","Cold/latency-tolerant KV; CXL-PNM attention offload can be useful.",{"KV_CACHE":1},131072,64,64,24,.85,
                 phase="cold_kv",target_tiers=("hbm","cxl_pnm","custom_hbm")))
    add(Scenario("kv_b256_c128k_burst","Large-batch burst; tests ScHBM attention offload and shared-link pressure.",{"KV_CACHE":1},131072,64,256,28,1.35,
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

    # Current-architecture robustness: C2 is type-aware, so old classifier-error
    # injection is obsolete. Use an abrupt behavior shift to stress prediction lag.
    add(Scenario("behavior_flip_stress","Abrupt per-object hotness inversion; stresses C2 prediction lag/thrashing while C1 reacts only to resource pressure.",{
        "KV_CACHE":.35,"RAG_DATA":.25,"AGENT_MEMORY":.20,"TOOL_RESULT":.10,"LORA_ADAPTER":.10},
        32768,72,16,40,.9,phase="hotness_flip",rag_index_total_gib=512,
        target_tiers=("hbm","custom_hbm","cxl_pnm","dram","hbf","ssd_pim")))
    add(Scenario("six_tier_capacity_stress","Capacity ladder intentionally exercises all six memories.",{
        "KV_CACHE":.30,"RAG_DATA":.25,"AGENT_MEMORY":.20,"TOOL_RESULT":.10,"LORA_ADAPTER":.08,"MOE_EXPERT":.07},
        131072,72,64,68,1.1,4.0,capacity_mult=.35,rag_index_total_gib=4096,
        target_tiers=("hbm","custom_hbm","cxl_pnm","dram","hbf","ssd_pim")))
    return S

def common_benchmark():
    """Common Benchmark Profile (qa-evaluation-criteria.md section 8): Llama-3.1-70B, BF16,
    8K input / 256 output, deterministic trace, load sweep. HBM is shrunk (hbm_capacity_mult)
    so that the memory hierarchy actually matters; with ample HBM every candidate is identical."""
    S=[]; add=S.append
    add(Scenario("cb_kv_8k_b32","Common benchmark: KV only, 8K/256, batch 32, tight HBM.",{"KV_CACHE":1},8192,256,32,40,1.0,
                 hbm_capacity_mult=.12,target_tiers=("hbm","dram","cxl_pnm","hbf")))
    add(Scenario("cb_kv_8k_b32_ramp","Common benchmark: KV only, progressive HBM pressure.",{"KV_CACHE":1},8192,256,32,40,1.0,
                 phase="capacity_ramp",hbm_capacity_mult=.2,target_tiers=("hbm","dram","cxl_pnm","hbf")))
    add(Scenario("cb_mixed_8k_b32","Common benchmark: KV + LoRA + MoE + Agent/Tool data, tight HBM.",{
        "KV_CACHE":.5,"LORA_ADAPTER":.15,"MOE_EXPERT":.15,"AGENT_MEMORY":.1,"TOOL_RESULT":.1},8192,256,32,48,1.0,
                 hbm_capacity_mult=.12,phase="bimodal",target_tiers=("hbm","dram","cxl_pnm","hbf")))
    return S

def dynamic_benchmark():
    """DP1 dynamic benchmark (B-class, loop iteration 2): the baseline's static placement is feasible when the
    scenario starts and goes stale at run time. Every scenario states the serving behavior it models and the
    As-Is failure mode it probes. Feasibility is verified with dynamic_controls() (same workload, no
    staleness) in test_sim.py: the baseline must meet the SLO there.

    Long-context KV cells (320K tokens, batch 16, 64 output tokens) are used where host-DRAM residency must
    cost enough to matter: restoring a ~107 GiB session over the 64 GB/s host link takes 1.3-2.1 s, i.e. the
    TPOT SLO (50 ms) is missed from DRAM but met from HBM (the stress set already uses 512K contexts).
    """
    S=[]; add=S.append
    KV320=dict(context_tokens=327680,output_tokens=64,batch_size=16)
    add(Scenario("dyn_cold_resident_chat_wave",
        "Serving pattern: long-lived Agent Memory (episodic state kept warm for idle tenants) is loaded at start-up and "
        "fills HBM first-come-first-served; at t=20-30 s an interactive long-context chat wave arrives. "
        "As-Is failure mode: the new hot KV sessions land in host DRAM (HBM is full of cold data) and are never "
        "promoted, so every turn pays the host-link restore.",
        {"AGENT_MEMORY":.7,"KV_CACHE":.3},KV320["context_tokens"],64,16,13,1.0,2.7,
        hbm_capacity_mult=.40,
        plan=(("AGENT_MEMORY",9,0,0,1.0,()),("KV_CACHE",4,20,30,1.0,())),
        target_tiers=("hbm","dram","hbf")))
    add(Scenario("dyn_idle_kv_holds_hbm",
        "Serving pattern: agent sessions blocked on slow tool calls keep their KV resident (idle, rate x0.05) and "
        "hold HBM; at t=30-40 s the tool results return / new sessions arrive and become the hot set. "
        "As-Is failure mode: arrival order decided HBM residency; hot sessions are served from DRAM while idle "
        "sessions sit in HBM. All objects are the same data class, so only per-object behavior tells them apart.",
        {"KV_CACHE":1},KV320["context_tokens"],64,16,8,1.0,
        hbm_capacity_mult=.40,
        plan=(("KV_CACHE",4,0,0,.05,()),("KV_CACHE",4,30,40,1.0,())),
        target_tiers=("hbm","dram")))
    add(Scenario("dyn_kv_hotset_recency_shift",
        "Serving pattern: working-set drift. Conversations created first are hot in the first half (HBM residents by "
        "first-come placement); at t=90 s users move on: the early sessions go cold (x0.1) and the later sessions "
        "(resident in DRAM) become hot (x3). "
        "As-Is failure mode: placement frozen at the old working set; post-shift traffic is served from DRAM.",
        {"KV_CACHE":1},KV320["context_tokens"],64,16,8,1.0,
        hbm_capacity_mult=.40,
        plan=(("KV_CACHE",4,0,0,1.0,((0,1.0),(90,.1))),("KV_CACHE",4,0,0,.1,((0,1.0),(90,30.0)))),
        target_tiers=("hbm","dram")))
    add(Scenario("dyn_kv_rotating_hotset",
        "Serving pattern: three user groups active in turn (60 s windows, e.g. shift/time-zone hand-over); the active "
        "group is hot (x3), the others near idle (x0.1). "
        "As-Is failure mode: placement fits only the first window; in later windows the active group is in DRAM. "
        "Also probes anti-thrashing: the hot set moves every 60 s.",
        {"KV_CACHE":1},KV320["context_tokens"],64,16,9,1.0,
        hbm_capacity_mult=.30,
        plan=(("KV_CACHE",3,0,0,1.0,((0,3.0),(60,.1))),
              ("KV_CACHE",3,0,0,1.0,((0,.1),(60,3.0),(120,.1))),
              ("KV_CACHE",3,0,0,1.0,((0,.1),(120,3.0)))),
        target_tiers=("hbm","dram")))
    add(Scenario("dyn_rag_shard_hotset_shift",
        "Serving pattern: GPU-resident vector-index shards (8 x ~32 GiB). Query popularity shifts at t=90 s "
        "(trending topic / newly ingested documents): the first shards (HBM residents) cool down, the later "
        "shards (host DRAM) become hot. "
        "As-Is failure mode: the hot shards are scanned from DRAM (full index crosses the host link per query).",
        {"RAG_DATA":1},32768,96,16,8,1.0,
        rag_index_total_gib=256,hbm_capacity_mult=.12,
        plan=(("RAG_DATA",4,0,0,1.0,((0,1.0),(90,.1))),("RAG_DATA",4,0,0,.1,((0,1.0),(90,30.0)))),
        target_tiers=("hbm","dram")))
    add(Scenario("dyn_host_path_contention_kv",
        "Serving pattern: host-side contention (co-located checkpoint / dataloader / NIC traffic on the shared PCIe "
        "root) cuts host-link bandwidth to 25% from t=90 s. 128K-context KV that spilled to DRAM was fine before. "
        "As-Is failure mode: static tier order keeps the spilled sessions on the degraded path.",
        {"KV_CACHE":1},131072,64,16,8,1.0,
        phase="host_bw_shock",host_bw_mult=.25,hbm_capacity_mult=.12,
        plan=(("KV_CACHE",8,0,0,1.0,()),),
        target_tiers=("hbm","dram","hbf")))
    return S


def dynamic_controls():
    """Feasibility controls: the same workloads with the staleness removed (ample HBM, no BW shock).
    The baseline must meet the SLO on every control (test_sim.py) - proof that the dynamic scenarios are
    feasible for the baseline and fail only because the placement goes stale."""
    from dataclasses import replace
    out=[]
    for sc in dynamic_benchmark():
        out.append(replace(sc,name=sc.name+"__control",hbm_capacity_mult=1.0,
                           phase=None if sc.phase=="host_bw_shock" else sc.phase,host_bw_mult=1.0))
    return out

def _choice(rng,mix):
    x=rng.random(); acc=0.0
    for k,w in mix.items():
        acc+=w
        if x<=acc: return k
    return next(reversed(mix))

def _generate_planned(sc:Scenario,seed:int):
    rng=random.Random(seed*1009+sum(map(ord,sc.name.removesuffix("__control"))))
    rag_count=sum(e[1] for e in sc.plan if e[0]=="RAG_DATA")
    rag_each_gib=(sc.rag_index_total_gib/rag_count) if (sc.rag_index_total_gib and rag_count) else None
    objs=[]; i=0
    for dc,count,lo,hi,rate_mult,sched in sc.plan:
        for _ in range(count):
            slo,shi=SIZE_GIB[dc]
            size=(slo+(shi-slo)*rng.random())*GIB*sc.size_scale
            if dc=="KV_CACHE":
                size=max(size,327680*sc.context_tokens*(.75+.5*rng.random()))
            elif dc=="RAG_DATA" and rag_each_gib:
                size=rag_each_gib*GIB*(.85+.30*rng.random())
            base=BASE_RATE[dc]*(.65+.7*rng.random())*sc.demand_scale*rate_mult
            hotmult=.75+.5*rng.random()
            arrival=rng.randint(lo,hi) if hi>lo else lo
            life=max(60,int(LIFE[dc]*(.75+.5*rng.random())))
            life=max(life,sc.horizon_s+30)   # planned objects live through the whole horizon
            prior=DATA_PRIORS[dc]
            objs.append(DataObject(
                oid=i,data_class=dc,size_bytes=size,base_rate=base,
                access_bytes=max(4096,size*ACCESS_FRAC[dc]),
                context_tokens=sc.context_tokens,output_tokens=sc.output_tokens,
                lifetime_s=life,arrival_s=arrival,batch_size=sc.batch_size,
                type_hint=dc,classification_confidence=.95,
                hotness_mult=hotmult,phase_time=None,phase_mult=1.0,
                latency_sensitivity=(sc.latency_sensitivity_override if sc.latency_sensitivity_override is not None else prior["latency"]),
                write_ratio=prior["write"],retrieval_dim=1024,
                rate_schedule=tuple(tuple(x) for x in sched)))
            i+=1
    return objs

def generate_trace(sc:Scenario,seed:int):
    if sc.plan: return _generate_planned(sc,seed)
    rng=random.Random(seed*1009+sum(map(ord,sc.name.removesuffix("__control"))))
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
