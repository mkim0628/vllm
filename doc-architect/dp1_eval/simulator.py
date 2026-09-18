from __future__ import annotations

import math
import random
from collections import Counter, defaultdict

from model import SystemSpec, DataObject
from policies import Telemetry, AsIsHBMFirst, C1MemoryCentric, C2DataCentric
from scenarios import Scenario, generate_trace

FIRST_RESPONSE_SLO_S=2.0
TPOT_SLO_S=0.050

def weighted_quantile(samples,q):
    data=sorted((v,w) for v,w in samples if w>0)
    if not data: return 0.0
    total=sum(w for _,w in data); target=total*q; acc=0.0
    for v,w in data:
        acc+=w
        if acc>=target: return v
    return data[-1][0]

def poisson(rng,lam):
    if lam<=0:return 0
    if lam<30:
        L=math.exp(-lam); k=0; p=1.0
        while p>L:
            k+=1; p*=rng.random()
        return k-1
    return max(0,int(round(rng.gauss(lam,math.sqrt(lam)))))

def effective_limits(sc,t,name):
    if name in sc.disabled_tiers:
        return 0.0, 0.01
    cap_mult=sc.capacity_mult*(sc.hbm_capacity_mult if name=="hbm" else 1.0)
    bw_mult=1.0
    if sc.phase=="capacity_ramp" and name=="hbm":
        frac=t/max(1,sc.horizon_s-1)
        cap_mult=max(.42,1-.58*frac)
    if sc.phase=="hbm_bw_shock" and t>=sc.horizon_s//2 and name=="hbm":
        bw_mult=sc.hbm_bw_mult
    if sc.phase=="host_bw_shock" and t>=sc.horizon_s//2 and name in ("custom_hbm","cxl_pnm","dram","ssd_pim"):
        bw_mult=sc.host_bw_mult
    return cap_mult,bw_mult

def _rag_score_bytes(system:SystemSpec,obj:DataObject):
    vec_bytes=obj.retrieval_dim*system.model.dtype_bytes
    nvec=max(1.0,obj.size_bytes/vec_bytes)
    return 4.0*nvec*obj.batch_size

def operation_external_bytes(system:SystemSpec,obj:DataObject,tier:str,candidate:str):
    m=system.memories[tier]
    if obj.data_class=="RAG_DATA":
        if m.retrieval_dot_capable:
            # Current registry has no TOPK primitive: return all scores, not whole vectors.
            return _rag_score_bytes(system,obj)
        return obj.size_bytes
    if obj.data_class=="KV_CACHE":
        if tier=="hbm":
            return 0.0
        if candidate!="As-Is-HBM-first" and m.attention_capable:
            return system.model.activation_roundtrip_bytes_per_token*obj.batch_size
        return obj.size_bytes  # restore path
    if obj.data_class in ("LORA_ADAPTER","MOE_EXPERT"):
        return 0.0 if tier=="hbm" else min(obj.size_bytes,obj.access_bytes*obj.batch_size)
    return min(obj.size_bytes,obj.access_bytes*obj.batch_size)

def service_interval_s(system:SystemSpec,obj:DataObject,tier:str,candidate:str,link_bw_mult:float=1.0):
    """Steady-state batch service interval for throughput.

    Latency remains sequential Attention+FFN. For memory-side Attention, however,
    different batches can pipeline remote Attention with GPU FFN, so throughput
    uses max(remote-attention, GPU-non-attention) rather than their sum.
    """
    if obj.data_class=="KV_CACHE":
        m=system.memories[tier]
        if tier=="hbm" or candidate=="As-Is-HBM-first" or not m.attention_capable:
            return system.decode_step_s(obj.context_tokens,obj.batch_size,"hbm",link_bw_mult)
        non_attn=system.gpu_non_attention_decode_s(obj.batch_size)
        remote_attn=system.offloaded_attention_s(m,obj.context_tokens,obj.batch_size,link_bw_mult)
        return max(non_attn,remote_attn)
    return tpot_s(system,obj,tier,candidate,link_bw_mult)

def tpot_s(system:SystemSpec,obj:DataObject,tier:str,candidate:str,link_bw_mult:float=1.0):
    # RAG/Agent/Tool data influence first-response; decode itself remains on GPU.
    if obj.data_class not in ("KV_CACHE","LORA_ADAPTER","MOE_EXPERT"):
        return system.decode_step_s(obj.context_tokens,obj.batch_size,"hbm")

    if obj.data_class=="KV_CACHE":
        m=system.memories[tier]
        if tier=="hbm":
            return system.decode_step_s(obj.context_tokens,obj.batch_size,"hbm")
        if candidate!="As-Is-HBM-first" and m.attention_capable:
            # Attention on PNM/cHBM, FFN/model-weight path remains on GPU.
            return system.decode_step_s(obj.context_tokens,obj.batch_size,tier,link_bw_mult)
        # Storage-only tier: restore before decode, then decode from HBM.
        return system.decode_step_s(obj.context_tokens,obj.batch_size,"hbm")

    # LoRA / MoE: model step on GPU + remote weight/adaptor access penalty.
    base=system.decode_step_s(obj.context_tokens,obj.batch_size,"hbm")
    if tier=="hbm":
        return base
    m=system.memories[tier]
    remote=min(obj.size_bytes,obj.access_bytes*obj.batch_size)/max(1.0,m.ext_bw*link_bw_mult)
    return base+remote/max(1,obj.output_tokens)

def first_response_s(system:SystemSpec,obj:DataObject,tier:str,candidate:str,
                     link_bw_mult:float=1.0,migration_debt:float=0.0,decision_us:float=0.0):
    # Incremental prefill proxy. Network/HTTP transport is NOT modeled: this is TTFT, not literal TTFB.
    q=min(2048,obj.context_tokens)
    base=system.prefill_s(obj.context_tokens,q)
    m=system.memories[tier]
    extra=0.0

    if obj.data_class=="RAG_DATA":
        extra=system.rag_retrieval_s(obj.size_bytes,obj.batch_size,tier,obj.retrieval_dim)
    elif obj.data_class in ("AGENT_MEMORY","TOOL_RESULT"):
        extra=min(obj.size_bytes,obj.access_bytes*obj.batch_size)/max(1.0,m.ext_bw*link_bw_mult)+m.latency_s
    elif obj.data_class in ("LORA_ADAPTER","MOE_EXPERT") and tier!="hbm":
        extra=min(obj.size_bytes,obj.access_bytes*obj.batch_size)/max(1.0,m.ext_bw*link_bw_mult)
    elif obj.data_class=="KV_CACHE" and tier!="hbm":
        if candidate=="As-Is-HBM-first" or not m.attention_capable:
            extra=obj.size_bytes/max(1.0,m.ext_bw*link_bw_mult)

    return base+extra+migration_debt+decision_us*1e-6

def _policy(system,candidate):
    if candidate=="As-Is-HBM-first":
        return AsIsHBMFirst(system)
    if candidate=="C1-memory-centric":
        return C1MemoryCentric(system)
    if candidate=="C2-data-centric":
        return C2DataCentric(system)
    raise ValueError(candidate)

def run_sim(system:SystemSpec,sc:Scenario,seed:int,candidate:str,load_scale:float=1.0):
    rng=random.Random(seed*7919+sum(map(ord,sc.name)))
    objs=generate_trace(sc,seed)
    policy=_policy(system,candidate)
    placements={}
    migration_debt=defaultdict(float)
    prev_ext_bytes={n:0.0 for n in system.memories}

    ttft_samples=[]; tpot_samples=[]; e2e_samples=[]
    placement_decisions=Counter(); class_tier=Counter()
    migration_bytes=0.0; migration_count=0
    total_offered_tokens=0.0; total_served_tokens=0.0; total_goodput_tokens=0.0
    total_served_requests=0.0; total_good_requests=0.0
    bw_sat_seconds=0; hbm_pressure_seconds=0
    decision_count=0
    decision_us_per={"As-Is-HBM-first":3.0,"C1-memory-centric":12.2,"C2-data-centric":34.0}[candidate]

    for t in range(sc.horizon_s):
        alive=[o for o in objs if o.alive(t)]
        occupancy=Counter()
        for o in alive:
            if o.oid in placements:
                occupancy[placements[o.oid]]+=o.size_bytes

        telemetry={}
        for name,m in system.memories.items():
            capm,bwm=effective_limits(sc,t,name)
            telemetry[name]=Telemetry(
                capacity_util=occupancy[name]/max(1.0,m.capacity_bytes*capm),
                bw_util=prev_ext_bytes[name]/max(1.0,m.ext_bw*bwm))

        policy.observe_telemetry(telemetry)
        for o in alive:
            policy.observe_runtime(o,o.rate_at(t)*load_scale)

        dynamic_tick=sc.phase is not None and t in {sc.horizon_s//2,sc.horizon_s//2+10}
        pressured=any(x.capacity_util>.88 or x.bw_util>.88 for x in telemetry.values())
        decision_objs=[o for o in alive if o.oid not in placements or (t%20==0 and pressured) or dynamic_tick]

        for o in decision_objs:
            old=placements.get(o.oid)
            new=policy.place(o,telemetry,sc.capacity_mult)
            decision_count+=1
            placement_decisions[new]+=1
            class_tier[(o.data_class,new)]+=1
            if old!=new:
                if old is not None:
                    occupancy[old]-=o.size_bytes
                placements[o.oid]=new
                occupancy[new]+=o.size_bytes

                # Capacity state must change immediately within the same placement batch.
                # Otherwise every object sees stale empty capacity and HBM/HBF can overcommit.
                for tier in {x for x in (old,new) if x is not None}:
                    capm,_=effective_limits(sc,t,tier)
                    telemetry[tier].capacity_util=occupancy[tier]/max(
                        1.0,system.memories[tier].capacity_bytes*capm)

                if old is not None:
                    migration_count+=1; migration_bytes+=o.size_bytes
                    src=system.memories[old]; dst=system.memories[new]
                    _,sm=effective_limits(sc,t,old); _,dm=effective_limits(sc,t,new)
                    path=min(src.ext_bw*sm,dst.ext_bw*dm)
                    migration_debt[o.oid]+=0.20*o.size_bytes/max(1.0,path)

        # Generate this second's batch-events.
        events=[]
        ext_bytes=Counter()
        for o in alive:
            n=poisson(rng,o.rate_at(t)*load_scale)
            if n<=0: continue
            tier=placements[o.oid]
            _,bwm=effective_limits(sc,t,tier)
            fr=first_response_s(system,o,tier,candidate,bwm,migration_debt[o.oid],decision_us_per)
            tp=tpot_s(system,o,tier,candidate,bwm)
            event_tokens=o.batch_size*o.output_tokens
            events.append((o,n,tier,fr,tp,event_tokens))
            ext_bytes[tier]+=operation_external_bytes(system,o,tier,candidate)*n
            migration_debt[o.oid]=0.0

        # Link saturation and pressure accounting.
        for name,m in system.memories.items():
            _,bwm=effective_limits(sc,t,name)
            if ext_bytes[name]/max(1.0,m.ext_bw*bwm)>.90:
                bw_sat_seconds+=1
        if telemetry["hbm"].capacity_util>.90:
            hbm_pressure_seconds+=1

        # Throughput capacity is modeled as independent resource pools.
        # Remote Attention can consume Custom-HBM/CXL-PNM while GPU FFN keeps running;
        # therefore their capacities add through parallel resource usage rather than a
        # single harmonic-mean bottleneck.
        if events:
            offered_tokens=sum(n*tok for _,n,_,_,_,tok in events)
            total_offered_tokens+=offered_tokens
            demand_s=Counter()

            for o,n,tier,fr,tp,tok in events:
                steps=n*o.output_tokens
                _,bwm=effective_limits(sc,t,tier)

                # Every generated token still executes the model's non-Attention path on GPU.
                demand_s["gpu_non_attention"] += steps*system.gpu_non_attention_decode_s(o.batch_size)

                if o.data_class=="KV_CACHE":
                    m=system.memories[tier]
                    if tier!="hbm" and candidate!="As-Is-HBM-first" and m.attention_capable:
                        demand_s[f"remote_attention:{tier}"] += (
                            steps*system.offloaded_attention_s(
                                m,o.context_tokens,o.batch_size,bwm))
                    else:
                        demand_s["hbm_attention"] += (
                            steps*system.hbm_attention_s(
                                o.context_tokens,o.batch_size,bwm))
                else:
                    # RAG/Agent/Tool/LoRA/MoE still decode on GPU after their data access.
                    demand_s["hbm_attention"] += (
                        steps*system.hbm_attention_s(
                            o.context_tokens,o.batch_size,1.0))

            # External-link traffic is a separate shared-resource constraint.
            for name,m in system.memories.items():
                _,bwm=effective_limits(sc,t,name)
                demand_s[f"link:{name}"] += ext_bytes[name]/max(1.0,m.ext_bw*bwm)

            peak=max(demand_s.values(),default=0.0)
            service_fraction=min(1.0,1.0/max(1e-9,peak))
        else:
            service_fraction=1.0

        for o,n,tier,fr,tp,event_tokens in events:
            served_batches=n*service_fraction
            served_tokens=served_batches*event_tokens
            served_requests=served_batches*o.batch_size
            total_served_tokens+=served_tokens
            total_served_requests+=served_requests

            # Queueing penalty only after offered load exceeds modeled generation capacity.
            qmult=1.0+max(0.0,1.0-service_fraction)*3.0
            frq=fr*qmult; tpq=tp*qmult
            e2e=frq+o.output_tokens*tpq
            ttft_samples.append((frq,served_requests))
            tpot_samples.append((tpq,served_requests))
            e2e_samples.append((e2e,served_requests))

            if frq<=FIRST_RESPONSE_SLO_S and tpq<=TPOT_SLO_S:
                total_goodput_tokens+=served_tokens
                total_good_requests+=served_requests

        prev_ext_bytes={name:float(ext_bytes[name]) for name in system.memories}

    pressure_safe=1-hbm_pressure_seconds/max(1,sc.horizon_s)
    bw_safe=1-min(1,bw_sat_seconds/max(1,sc.horizon_s*len(system.memories)))
    migration_eff=1-min(1,migration_bytes/max(1.0,total_served_tokens*4096.0))
    tiers_used={placements[o.oid] for o in objs if o.oid in placements}
    tier_coverage=len(tiers_used)/len(system.memories)
    resource_index=.40*pressure_safe+.35*bw_safe+.15*migration_eff+.10*tier_coverage

    out={
      "scenario":sc.name,"seed":seed,"candidate":candidate,"load_scale":load_scale,
      "batch_size":sc.batch_size,"context_tokens":sc.context_tokens,
      "request_throughput":total_served_requests/sc.horizon_s,
      "token_throughput":total_served_tokens/sc.horizon_s,
      "slo_goodput":total_goodput_tokens/sc.horizon_s,
      "slo_good_request_throughput":total_good_requests/sc.horizon_s,
      "ttft_p99_ms":weighted_quantile(ttft_samples,.99)*1000,
      "tpot_p99_ms":weighted_quantile(tpot_samples,.99)*1000,
      "e2e_p99_ms":weighted_quantile(e2e_samples,.99)*1000,
      "resource_index":resource_index,
      "hbm_pressure_violation_rate":1-pressure_safe,
      "bw_saturation_rate":1-bw_safe,
      "migration_bytes":migration_bytes,"migration_count":migration_count,
      "decision_us_avg":decision_us_per,"decision_count":decision_count,
      "active_tiers":";".join(sorted(tiers_used)),
      "placement_decisions":dict(placement_decisions),
      "class_tier":{f"{k[0]}@{k[1]}":v for k,v in class_tier.items()},
    }
    if candidate=="C2-data-centric":
        out["fallback_count"]=policy.fallback_count
        out["fallback_reason"]=dict(policy.fallback_reason)
    else:
        out["fallback_count"]=0
        out["fallback_reason"]={}
    return out
