from __future__ import annotations
import math, random, statistics
from collections import Counter, defaultdict
from model import SystemSpec, DataObject, clamp
from policies import Telemetry, C1MemoryCentric, C2DataCentric
from scenarios import Scenario, generate_trace

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
            k+=1;p*=rng.random()
        return k-1
    return max(0,int(round(rng.gauss(lam,math.sqrt(lam)))))

def effective_limits(sc,t,name,system):
    cap_mult=sc.capacity_mult
    bw_mult=1.0
    host_mult=1.0
    if sc.phase=="capacity_ramp" and name=="hbm":
        frac=t/max(1,sc.horizon_s-1); cap_mult=max(.42,1-.58*frac)
    if sc.phase=="hbm_bw_shock" and t>=sc.horizon_s//2 and name=="hbm":
        bw_mult=sc.hbm_bw_mult
    if sc.phase=="host_bw_shock" and t>=sc.horizon_s//2 and name in ("custom_hbm","cxl_pnm","dram","ssd_pim"):
        host_mult=sc.host_bw_mult
    if sc.phase=="resource_oscillation":
        slot=(t//30)%2
        if slot==0 and name=="hbm": bw_mult=.38
        if slot==1 and name in ("custom_hbm","cxl_pnm","dram","ssd_pim"): host_mult=.40
    return cap_mult,bw_mult*host_mult

def data_access_bytes(obj:DataObject):
    if obj.data_class=="KV_CACHE": return obj.access_bytes*obj.output_tokens
    if obj.data_class in ("LORA_ADAPTER","MOE_EXPERT"): return obj.access_bytes*obj.output_tokens*.45
    return obj.access_bytes

def object_tpot(system:SystemSpec,obj:DataObject,tier:str,bw_util:float,bw_mult:float):
    m=system.memories[tier]
    base=system.base_tpot_s(obj.context_tokens,16)
    overload=min(20.0,max(1.0,(bw_util/.85)**1.45))
    if obj.data_class=="KV_CACHE":
        kvread=min(obj.size_bytes,system.model.kv_bytes_per_token*obj.context_tokens)
        weight=system.model.active_params*system.model.dtype_bytes/(system.gpu_hbm_bw*system.gpu_bw_eff)
        if tier=="hbm":
            attn=kvread*16/(system.gpu_hbm_bw*system.gpu_bw_eff)
            return (weight+attn)*overload
        if m.attention_capable:
            attn=kvread/(m.int_bw*max(.3,m.attn_bw_eff))
            activation=2*system.model.hidden*system.model.dtype_bytes/max(1,m.ext_bw*bw_mult)
            return (weight+attn+activation)*overload
        restore=obj.size_bytes/max(1,m.ext_bw*bw_mult)
        return (base+restore/max(1,obj.output_tokens))*overload
    if obj.data_class in ("LORA_ADAPTER","MOE_EXPERT"):
        extra=obj.access_bytes/max(1,m.ext_bw*bw_mult)/max(1,obj.output_tokens)
        return (base+extra)*overload
    return base

def object_ttft(system:SystemSpec,obj:DataObject,tier:str,bw_util:float,bw_mult:float,migration_debt:float,decision_us:float):
    m=system.memories[tier]
    q=min(2048,obj.context_tokens)
    base=system.prefill_s(obj.context_tokens,q)
    overload=min(20.0,max(1.0,(bw_util/.85)**1.35))
    data=0.0
    if obj.data_class!="KV_CACHE":
        bw=m.write_bw if obj.write_ratio>.55 else m.ext_bw
        data=obj.access_bytes/max(1,bw*bw_mult)+m.latency_s*4
    elif tier!="hbm" and not m.attention_capable:
        data=obj.size_bytes/max(1,m.ext_bw*bw_mult)
    return (base+data*overload+migration_debt+decision_us*1e-6)

def run_sim(system:SystemSpec,sc:Scenario,seed:int,candidate:str):
    rng=random.Random(seed*7919+sum(map(ord,candidate+sc.name)))
    objs=generate_trace(sc,seed)
    policy=C1MemoryCentric(system) if candidate.startswith("C1") else C2DataCentric(system)
    placements={}
    migration_debt=defaultdict(float)
    prev_bw={n:0.0 for n in system.memories}
    latency_ttft=[]; latency_tpot=[]; latency_e2e=[]
    placement_decisions=Counter(); placement_bytes=Counter(); class_tier=Counter()
    migration_bytes=0.0; migration_count=0; bw_sat_seconds=0; hbm_pressure_seconds=0
    offered_tokens=0.0; served_tokens=0.0; served_requests=0.0
    useful_access_bytes=Counter(); total_access_bytes=0.0
    ref_acc=0.0
    base_offer=sum(o.rate_at(0)*o.output_tokens for o in objs if o.arrival_s==0)
    ref=system.reference_tps(sc.context_tokens,16)
    rate_scale=(sc.demand_scale*ref)/max(1e-9,base_offer)
    decision_us_per=12.2 if candidate.startswith("C1") else 34.0
    decision_count=0
    for t in range(sc.horizon_s):
        alive=[o for o in objs if o.alive(t)]
        occupancy=Counter()
        for o in alive:
            if o.oid in placements: occupancy[placements[o.oid]]+=o.size_bytes
        telemetry={}
        for n,m in system.memories.items():
            capm,bwm=effective_limits(sc,t,n,system)
            telemetry[n]=Telemetry(
                capacity_util=occupancy[n]/max(1,m.capacity_bytes*capm),
                bw_util=prev_bw[n]/max(1,m.ext_bw*bwm if n!="custom_hbm" and n!="cxl_pnm" else max(m.ext_bw*bwm,m.int_bw*.15))
            )
        policy.observe_telemetry(telemetry)
        rates={}
        for o in alive:
            r=o.rate_at(t)*rate_scale
            rates[o.oid]=r
            policy.observe_runtime(o,r)
        dynamic_tick = sc.phase is not None and t in {sc.horizon_s//2, sc.horizon_s//2+10}
        pressured = any(x.capacity_util>.88 or x.bw_util>.88 for x in telemetry.values())
        decision_objs=[o for o in alive if o.oid not in placements or (t%20==0 and pressured) or dynamic_tick]
        if decision_objs:
            for o in decision_objs:
                old=placements.get(o.oid)
                capm,_=effective_limits(sc,t,"hbm",system)
                new=policy.place(o,telemetry,capm if sc.phase!="capacity_ramp" else 1.0)
                decision_count+=1; placement_decisions[new]+=1
                if old!=new:
                    if old is not None: occupancy[old]-=o.size_bytes
                    placements[o.oid]=new; occupancy[new]+=o.size_bytes
                    placement_bytes[new]+=o.size_bytes; class_tier[(o.data_class,new)]+=1
                    for tier in {x for x in (old,new) if x is not None}:
                        capx,_=effective_limits(sc,t,tier,system)
                        telemetry[tier].capacity_util=occupancy[tier]/max(1,system.memories[tier].capacity_bytes*capx)
                    if old is not None:
                        migration_count+=1; migration_bytes+=o.size_bytes
                        src=system.memories[old]; dst=system.memories[new]
                        _,sm=effective_limits(sc,t,old,system); _,dm=effective_limits(sc,t,new,system)
                        path=min(src.ext_bw*sm,dst.ext_bw*dm)
                        migration_debt[o.oid]+=0.20*o.size_bytes/max(1,path)
            occupancy=Counter()
            for o in alive: occupancy[placements[o.oid]]+=o.size_bytes
        tier_bytes=Counter(); access_rows=[]
        second_offered_tokens=0.0
        for o in alive:
            r=rates[o.oid]; n=poisson(rng,r)
            if n<=0: continue
            tier=placements[o.oid]
            b=data_access_bytes(o)*n
            tier_bytes[tier]+=b; total_access_bytes+=b; useful_access_bytes[tier]+=b
            second_offered_tokens+=n*o.output_tokens
            access_rows.append((o,n,tier))
        offered_tokens+=second_offered_tokens
        bwutil={}
        max_over=1.0
        for n,m in system.memories.items():
            _,bwm=effective_limits(sc,t,n,system)
            cap=m.ext_bw*bwm
            kv_internal=sum(data_access_bytes(o)*cnt for o,cnt,tr in access_rows if tr==n and o.data_class=="KV_CACHE" and m.attention_capable)
            normal=tier_bytes[n]-kv_internal
            util=normal/max(1,cap)+kv_internal/max(1,m.int_bw*max(.3,m.attn_bw_eff))
            bwutil[n]=util
            if util>.90: bw_sat_seconds+=1
            max_over=max(max_over,(util/.90)**1.3 if util>.90 else 1.0)
        if telemetry["hbm"].capacity_util>.90: hbm_pressure_seconds+=1
        if access_rows:
            weighted_pen=0.0; weight=0.0
            for o,n,tier in access_rows:
                _,bwm=effective_limits(sc,t,tier,system)
                tp=object_tpot(system,o,tier,bwutil[tier],bwm)
                base=system.base_tpot_s(o.context_tokens,16)
                weighted_pen+=n*o.output_tokens*max(1.0,tp/max(1e-9,base)); weight+=n*o.output_tokens
            mem_pen=weighted_pen/max(1,weight)
        else: mem_pen=1.0
        cap_tps=ref/max(1.0,mem_pen)
        second_served=min(second_offered_tokens,cap_tps)
        service_frac=second_served/max(1e-9,second_offered_tokens) if second_offered_tokens else 1.0
        served_tokens+=second_served
        for o,n,tier in access_rows:
            _,bwm=effective_limits(sc,t,tier,system)
            debt=migration_debt[o.oid]
            tt=object_ttft(system,o,tier,bwutil[tier],bwm,debt,decision_us_per)
            tp=object_tpot(system,o,tier,bwutil[tier],bwm)
            queue=1.0+max(0.0,1-service_frac)*3.2
            tt*=queue; tp*=queue
            e2e=tt+o.output_tokens*tp
            latency_ttft.append((tt,n)); latency_tpot.append((tp,n)); latency_e2e.append((e2e,n))
            served_requests+=n*service_frac
            migration_debt[o.oid]=0.0
        prev_bw={n:float(tier_bytes[n]) for n in system.memories}
        ref_acc+=ref
    active_tiers=set(placements.values())
    raw_tps=served_tokens/sc.horizon_s
    raw_rps=served_requests/sc.horizon_s
    throughput_ratio=clamp(raw_tps/(ref_acc/sc.horizon_s),0,1.05)
    pressure_safe=1-hbm_pressure_seconds/max(1,sc.horizon_s)
    bw_safe=1-min(1,bw_sat_seconds/max(1,sc.horizon_s*len(system.memories)))
    migration_eff=1-min(1,migration_bytes/max(1,total_access_bytes))
    tier_use=min(1,len([n for n,b in useful_access_bytes.items() if b>0])/max(1,len(sc.target_tiers) or 3))
    resource_index=.35*pressure_safe+.35*bw_safe+.20*migration_eff+.10*tier_use
    return {
      "scenario":sc.name,"seed":seed,"candidate":candidate,
      "request_throughput":raw_rps,"token_throughput":raw_tps,"throughput_ratio":throughput_ratio,
      "ttft_p99_ms":weighted_quantile(latency_ttft,.99)*1000,
      "tpot_p99_ms":weighted_quantile(latency_tpot,.99)*1000,
      "e2e_p99_ms":weighted_quantile(latency_e2e,.99)*1000,
      "resource_index":resource_index,"hbm_pressure_violation_rate":1-pressure_safe,
      "bw_saturation_rate":1-bw_safe,"migration_bytes":migration_bytes,"migration_count":migration_count,
      "decision_us_avg":decision_us_per,"decision_count":decision_count,
      "active_tiers":";".join(sorted(active_tiers)),
      "placement_decisions":dict(placement_decisions),
      "placement_bytes":dict(placement_bytes),
      "class_tier":{f"{k[0]}@{k[1]}":v for k,v in class_tier.items()},
      "reference_tps":ref_acc/sc.horizon_s,
    }
