from __future__ import annotations

from collections import defaultdict, deque
from dataclasses import dataclass
import math

from model import MemorySpec, SystemSpec, DataObject, DATA_PRIORS, clamp

@dataclass
class Telemetry:
    capacity_util:float=0.0
    bw_util:float=0.0

@dataclass
class ResourceState:
    current_pressure:float
    current_bw:float
    predicted_pressure:float
    predicted_bw:float
    capacity_headroom:float

class ResourceStateMonitor:
    """C1: external Telemetry -> current/trend/near-future Resource State."""
    def __init__(self,window=5,horizon=2):
        self.window=window; self.horizon=horizon
        self.hist=defaultdict(lambda:deque(maxlen=window))

    def observe(self,telemetry:dict[str,Telemetry]):
        for name,t in telemetry.items():
            self.hist[name].append((t.capacity_util,t.bw_util))

    def state(self,name:str,current:Telemetry):
        h=self.hist[name]
        if len(h)>=2:
            dc=(h[-1][0]-h[0][0])/max(1,len(h)-1)
            db=(h[-1][1]-h[0][1])/max(1,len(h)-1)
        else:
            dc=db=0.0
        return ResourceState(
            current.capacity_util,current.bw_util,
            clamp(current.capacity_util+dc*self.horizon,0,1.5),
            clamp(current.bw_util+db*self.horizon,0,2.0),
            max(0.0,1-current.capacity_util))

class CandidateBuilder:
    """Memory Registry static info + monitored/predicted state -> Memory State View."""
    def build(self,system:SystemSpec,states:dict[str,ResourceState],obj:DataObject,cap_mult:float):
        out=[]
        for m in system.memories.values():
            st=states[m.name]
            headroom=m.capacity_bytes*cap_mult*(1-min(1,st.current_pressure))
            if headroom+1e-6<obj.size_bytes:
                continue
            # C1 does not characterize hotness/lifetime, but required operation is a hard constraint.
            if obj.data_class=="KV_CACHE" and m.name!="hbm" and not m.attention_capable:
                continue
            out.append((m,st))
        if not out:
            out=[max(((m,states[m.name]) for m in system.memories.values()),
                     key=lambda x:x[0].capacity_bytes*cap_mult*(1-min(1,x[1].current_pressure)))]
        return out

class C1MemoryCentric:
    name="C1-memory-centric"
    def __init__(self,system:SystemSpec):
        self.system=system
        self.monitor=ResourceStateMonitor()
        self.builder=CandidateBuilder()
        self.decision_ops=0

    def observe_telemetry(self,telemetry):
        self.monitor.observe(telemetry)

    def observe_runtime(self,obj,rate):
        pass

    def place(self,obj:DataObject,telemetry:dict[str,Telemetry],cap_mult:float):
        states={n:self.monitor.state(n,t) for n,t in telemetry.items()}
        cands=self.builder.build(self.system,states,obj,cap_mult)
        best=None; bestscore=-1e9
        speeds=[]
        for m,_ in cands:
            if obj.data_class=="KV_CACHE" and m.attention_capable:
                raw=m.int_bw
            elif obj.data_class=="RAG_DATA" and m.retrieval_dot_capable:
                raw=m.int_bw
            else:
                raw=m.ext_bw
            speeds.append(math.log10(max(1,raw)))
        lo=min(speeds); hi=max(speeds); den=max(.1,hi-lo)

        for (m,st),rawlog in zip(cands,speeds):
            speed=(rawlog-lo)/den
            cap=max(0,1-st.predicted_pressure)
            bw=max(0,1-st.predicted_bw)
            latency=1/(1+m.latency_s/2e-6)
            sizecap=min(1,math.log2(max(2,m.capacity_bytes/obj.size_bytes))/8)
            score=.30*cap+.24*bw+.32*speed+.09*latency+.05*sizecap
            self.decision_ops+=1
            if score>bestscore:
                bestscore=score; best=m.name
        return best

class DataClassifier:
    def classify(self,obj:DataObject):
        return (obj.type_hint or obj.data_class,obj.classification_confidence)

class RuntimeStateMonitor:
    """C2: object/class behavior history, independent of HW Telemetry."""
    def __init__(self):
        self.rate_ewma=defaultdict(float)
        self.samples=defaultdict(int)

    def observe(self,obj:DataObject,rate:float):
        k=obj.oid; a=.18
        self.rate_ewma[k]=(1-a)*self.rate_ewma[k]+a*rate
        self.samples[k]+=1

    def stats(self,obj:DataObject):
        return self.rate_ewma[obj.oid],self.samples[obj.oid]

class DataCharacteristicInterpreter:
    def __init__(self,monitor:RuntimeStateMonitor):
        self.monitor=monitor

    def interpret(self,cls:str,obj:DataObject):
        p=DATA_PRIORS.get(cls,DATA_PRIORS["TOOL_RESULT"]).copy()
        rate,n=self.monitor.stats(obj)
        if n:
            observed=clamp(rate/.35)
            p["observed_hotness"]=observed
            # Class prior dominates cold-start, then decays as Runtime State history accumulates.
            prior_w=max(.15,math.exp(-n/6.0))
            p["hotness"]=clamp(prior_w*p["hotness"]+(1-prior_w)*observed)
            p["reuse"]=clamp(max(.25,prior_w)*p["reuse"]+(1-max(.25,prior_w))*observed)
        else:
            p["observed_hotness"]=p["hotness"]
        if cls==obj.data_class:
            p["latency"]=obj.latency_sensitivity
            p["write"]=obj.write_ratio
        return p

class MemoryTierAffinityEvaluator:
    def __init__(self,system:SystemSpec):
        self.system=system

    def affinity(self,cls:str,ch:dict,obj:DataObject,m:MemorySpec):
        speed=clamp((math.log10(m.ext_bw)-math.log10(16e9))/(math.log10(64e12)-math.log10(16e9)))
        capacity=clamp((math.log10(m.capacity_bytes)-math.log10(192*(1024**3)))/
                       (math.log10(16*(1024**4))-math.log10(192*(1024**3))))
        lat=1/(1+m.latency_s/3e-6)
        write_ok=1/(1+max(0,m.write_amp-1)*ch["write"])
        h=ch["hotness"]; life=ch["lifetime"]; ls=ch["latency"]
        score=(.28*h+.14*ls)*speed+.20*life*capacity+.08*lat+.06*write_ok

        if cls=="KV_CACHE":
            if m.name=="hbm":
                step=self.system.decode_step_s(obj.context_tokens,obj.batch_size,"hbm")
                score+=.34/(1+step/.05)
                if h<.40 and ls<.60:
                    score-=.22
            elif m.attention_capable:
                step=self.system.decode_step_s(obj.context_tokens,obj.batch_size,m.name)
                # Cold / latency-tolerant KV can trade latency for HBM headroom as long as TPOT is feasible.
                cold_bonus=.28*(1-h)+.16*(1-ls) if step<=.050 else 0.0
                score+=.30/(1+step/.05)+cold_bonus
            else:
                score-=1.0

        elif cls=="RAG_DATA":
            # Operation-aware: compare end-to-end vector retrieval cost for this index/batch.
            cost=self.system.rag_retrieval_s(obj.size_bytes,obj.batch_size,m.name,obj.retrieval_dim)
            op_utility=1/(1+cost/.25)
            score+=.42*op_utility
            if m.name=="ssd_pim" and m.retrieval_dot_capable:
                score+=.12*(1-h)+.10*life
            if m.name=="hbf":
                score+=.10

        elif cls=="AGENT_MEMORY":
            if m.name in ("dram","cxl_pnm"):
                score+=.18
            if m.name=="ssd_pim":
                score+=.24*(1-h)
            if m.name=="hbm" and h<.5:
                score-=.20

        elif cls=="TOOL_RESULT":
            if m.name in ("dram","hbf"):
                score+=.14
            if m.name=="ssd_pim" and h<.3:
                score+=.10

        elif cls in ("LORA_ADAPTER","MOE_EXPERT"):
            if m.name=="hbm":
                score+=.22*h
            if m.name=="hbf":
                score+=.18
            if m.name=="dram" and h<.5:
                score+=.08
        return score

class SafeFallbackSelector:
    """Conservative path used when C2 classification/prediction is uncertain or infeasible."""
    def __init__(self,system:SystemSpec):
        self.system=system

    def _headroom(self,m:MemorySpec,t:Telemetry,cap_mult:float):
        return m.capacity_bytes*cap_mult*(1-min(1,t.capacity_util))

    def choose(self,obj:DataObject,telemetry:dict[str,Telemetry],cap_mult:float):
        feasible=[m for m in self.system.memories.values()
                  if self._headroom(m,telemetry[m.name],cap_mult)>=obj.size_bytes]
        if not feasible:
            feasible=list(self.system.memories.values())

        if obj.data_class=="KV_CACHE":
            hbm=self.system.memories["hbm"]
            if hbm in feasible and telemetry["hbm"].capacity_util<.88 and telemetry["hbm"].bw_util<.88:
                return "hbm"
            off=[]
            for m in feasible:
                if not m.attention_capable:
                    continue
                step=self.system.decode_step_s(obj.context_tokens,obj.batch_size,m.name)
                if step<=.050:
                    off.append((step,m.name))
            if off:
                return min(off)[1]
            # Storage-only fallback: choose fastest path; simulator restores before decode.
            return max(feasible,key=lambda m:m.ext_bw).name

        if obj.data_class=="RAG_DATA":
            ranked=[(self.system.rag_retrieval_s(obj.size_bytes,obj.batch_size,m.name,obj.retrieval_dim),m.name)
                    for m in feasible]
            return min(ranked)[1]

        # Generic safe path for long-lived state.
        preferred=["hbm","hbf","dram","cxl_pnm","ssd_pim","custom_hbm"]
        for name in preferred:
            if any(m.name==name for m in feasible):
                return name
        return feasible[0].name

class C2DataCentric:
    name="C2-data-centric"
    def __init__(self,system:SystemSpec):
        self.system=system
        self.classifier=DataClassifier()
        self.runtime=RuntimeStateMonitor()
        self.interpreter=DataCharacteristicInterpreter(self.runtime)
        self.aff=MemoryTierAffinityEvaluator(system)
        self.fallback=SafeFallbackSelector(system)
        self.decision_ops=0
        self.fallback_count=0
        self.fallback_reason=defaultdict(int)

    def observe_telemetry(self,telemetry):
        pass

    def observe_runtime(self,obj,rate):
        self.runtime.observe(obj,rate)

    def place(self,obj:DataObject,telemetry:dict[str,Telemetry],cap_mult:float):
        cls,confidence=self.classifier.classify(obj)
        ch=self.interpreter.interpret(cls,obj)
        scored=[]

        for m in self.system.memories.values():
            headroom=m.capacity_bytes*cap_mult*(1-min(1,telemetry[m.name].capacity_util))
            if headroom+1e-6<obj.size_bytes:
                continue
            a=self.aff.affinity(cls,ch,obj,m)
            t=telemetry[m.name]
            resource=.58*max(0,1-t.capacity_util)+.42*max(0,1-t.bw_util)
            score=.76*a+.24*resource
            self.decision_ops+=1
            scored.append((score,m.name))

        if not scored:
            self.fallback_count+=1; self.fallback_reason["no_capacity_candidate"]+=1
            return self.fallback.choose(obj,telemetry,cap_mult)

        scored.sort(reverse=True)
        best_score,best=scored[0]
        gap=(best_score-scored[1][0]) if len(scored)>1 else 1.0
        selected=self.system.memories[best]

        reason=None
        if confidence<.65:
            reason="low_classifier_confidence"
        elif cls=="KV_CACHE" and best!="hbm" and not selected.attention_capable:
            reason="operation_infeasible"
        elif cls=="KV_CACHE" and best!="hbm":
            if self.system.decode_step_s(obj.context_tokens,obj.batch_size,best)>.050:
                reason="predicted_tpot_violation"
        elif cls=="RAG_DATA":
            # If retrieval path is extremely slow, use the conservative cost-minimizing path.
            if self.system.rag_retrieval_s(obj.size_bytes,obj.batch_size,best,obj.retrieval_dim)>2.0:
                reason="predicted_first_response_violation"

        # Runtime mismatch catches high-confidence wrong hints after observations accumulate.
        _,samples=self.runtime.stats(obj)
        prior=DATA_PRIORS.get(cls,DATA_PRIORS["TOOL_RESULT"])["hotness"]
        if confidence<.90 and samples>=4 and abs(ch["observed_hotness"]-prior)>.45:
            reason=reason or "runtime_behavior_mismatch"

        if reason:
            self.fallback_count+=1
            self.fallback_reason[reason]+=1
            return self.fallback.choose(obj,telemetry,cap_mult)
        return best


class AsIsHBMFirst:
    """Baseline: HBM first, then fixed capacity spill. No data characterization or PNM compute awareness."""
    name="As-Is-HBM-first"

    def __init__(self,system:SystemSpec):
        self.system=system
        self.decision_ops=0
        self.spill_order=("hbm","hbf","dram","cxl_pnm","custom_hbm","ssd_pim")

    def observe_telemetry(self,telemetry):
        pass

    def observe_runtime(self,obj,rate):
        pass

    def place(self,obj:DataObject,telemetry:dict[str,Telemetry],cap_mult:float):
        for name in self.spill_order:
            m=self.system.memories[name]
            headroom=m.capacity_bytes*cap_mult*(1-min(1,telemetry[name].capacity_util))
            self.decision_ops+=1
            if headroom>=obj.size_bytes:
                return name
        return "ssd_pim"
