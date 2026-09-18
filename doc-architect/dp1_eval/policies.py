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
    def __init__(self, window=5, horizon=2):
        self.window=window; self.horizon=horizon
        self.hist=defaultdict(lambda: deque(maxlen=window))
    def observe(self, telemetry:dict[str,Telemetry]):
        for name,t in telemetry.items(): self.hist[name].append((t.capacity_util,t.bw_util))
    def state(self,name:str,current:Telemetry):
        h=self.hist[name]
        if len(h)>=2:
            dc=(h[-1][0]-h[0][0])/max(1,len(h)-1)
            db=(h[-1][1]-h[0][1])/max(1,len(h)-1)
        else: dc=db=0.0
        return ResourceState(current.capacity_util,current.bw_util,
            clamp(current.capacity_util+dc*self.horizon,0,1.5),
            clamp(current.bw_util+db*self.horizon,0,2.0),
            max(0.0,1-current.capacity_util))

class CandidateBuilder:
    """Memory Registry static info + monitored/predicted state -> Memory State View."""
    def build(self, system:SystemSpec, states:dict[str,ResourceState], obj:DataObject, cap_mult:float):
        out=[]
        for m in system.memories.values():
            st=states[m.name]
            headroom=m.capacity_bytes*cap_mult*(1-min(1,st.current_pressure))
            if headroom+1e-6 < obj.size_bytes: continue
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
        self.system=system; self.monitor=ResourceStateMonitor(); self.builder=CandidateBuilder(); self.decision_ops=0
    def observe_telemetry(self,telemetry): self.monitor.observe(telemetry)
    def observe_runtime(self,obj,rate): pass
    def place(self,obj:DataObject,telemetry:dict[str,Telemetry],cap_mult:float):
        states={n:self.monitor.state(n,t) for n,t in telemetry.items()}
        cands=self.builder.build(self.system,states,obj,cap_mult)
        best=None; bestscore=-1e9
        ext_logs=[math.log10(max(1,(m.int_bw if obj.data_class=="KV_CACHE" and m.attention_capable else m.ext_bw))) for m,_ in cands]
        lo=min(ext_logs); hi=max(ext_logs); den=max(.1,hi-lo)
        for m,st in cands:
            speed=(math.log10(max(1,(m.int_bw if obj.data_class=="KV_CACHE" and m.attention_capable else m.ext_bw)))-lo)/den
            cap=max(0,1-st.predicted_pressure)
            bw=max(0,1-st.predicted_bw)
            latency=1/(1+m.latency_s/2e-6)
            sizecap=min(1,math.log2(max(2,m.capacity_bytes/obj.size_bytes))/8)
            score=.30*cap+.24*bw+.32*speed+.09*latency+.05*sizecap
            if obj.data_class=="KV_CACHE" and m.attention_capable: score+=.03
            self.decision_ops+=1
            if score>bestscore: bestscore=score; best=m.name
        return best

class DataClassifier:
    def classify(self,obj:DataObject): return obj.type_hint or obj.data_class

class RuntimeStateMonitor:
    """C2: class/object behavior history, not HW telemetry."""
    def __init__(self): self.rate_ewma=defaultdict(float); self.samples=defaultdict(int)
    def observe(self,obj:DataObject,rate:float):
        k=obj.data_class; a=.18
        self.rate_ewma[k]=(1-a)*self.rate_ewma[k]+a*rate
        self.samples[k]+=1
    def stats(self,k): return self.rate_ewma[k],self.samples[k]

class DataCharacteristicInterpreter:
    def __init__(self,monitor:RuntimeStateMonitor): self.monitor=monitor
    def interpret(self,cls:str,obj:DataObject):
        p=DATA_PRIORS.get(cls,DATA_PRIORS["TOOL_RESULT"]).copy()
        rate,n=self.monitor.stats(cls)
        if n:
            observed=clamp(rate/0.45)
            p["hotness"]=clamp(.55*p["hotness"]+.45*observed)
            p["reuse"]=clamp(.70*p["reuse"]+.30*observed)
        p["latency"]=obj.latency_sensitivity if cls==obj.data_class else p["latency"]
        p["write"]=obj.write_ratio if cls==obj.data_class else p["write"]
        return p

class MemoryTierAffinityEvaluator:
    def __init__(self,system:SystemSpec): self.system=system
    def affinity(self,cls:str,ch:dict,obj:DataObject,m:MemorySpec):
        speed=clamp((math.log10(m.ext_bw)-math.log10(16e9))/(math.log10(64e12)-math.log10(16e9)))
        capacity=clamp((math.log10(m.capacity_bytes)-math.log10(192*(1024**3)))/(math.log10(16*(1024**4))-math.log10(192*(1024**3))))
        lat=1/(1+m.latency_s/3e-6)
        write_ok=1/(1+max(0,m.write_amp-1)*ch["write"])
        h=ch["hotness"]; life=ch["lifetime"]; ls=ch["latency"]
        score=(.38*h+.20*ls)*speed + .24*life*capacity + .10*lat + .08*write_ok
        if cls=="KV_CACHE":
            if m.name=="hbm": score+=.22
            elif m.attention_capable:
                attn_speed=clamp((math.log10(m.int_bw)-math.log10(4e11))/(math.log10(16e12)-math.log10(4e11)))
                score+=.10+.18*attn_speed
            else: score-=.75
        elif cls=="RAG_DATA":
            if m.name=="hbf": score+=.18*(1-ch["write"])
            if m.name in ("dram","cxl_pnm"): score+=.10
            if m.name=="ssd_pim" and h<.35: score+=.14
        elif cls=="AGENT_MEMORY":
            if m.name in ("dram","cxl_pnm"): score+=.15
            if m.name=="ssd_pim": score+=.20*(1-h)
            if m.name=="hbm" and h<.5: score-=.18
        elif cls=="TOOL_RESULT":
            if m.name in ("dram","hbf"): score+=.12
            if m.name=="ssd_pim" and h<.3: score+=.12
        elif cls=="LOG_DATA":
            if m.name=="ssd_pim": score+=.34
            if m.name=="dram": score+=.16
            if m.name in ("hbm","hbf"): score-=.30
        elif cls in ("LORA_ADAPTER","MOE_EXPERT"):
            if m.name=="hbm": score+=.20*h
            if m.name=="hbf": score+=.16
            if m.name=="dram" and h<.5: score+=.08
        return score

class C2DataCentric:
    name="C2-data-centric"
    def __init__(self,system:SystemSpec):
        self.system=system; self.classifier=DataClassifier(); self.runtime=RuntimeStateMonitor()
        self.interpreter=DataCharacteristicInterpreter(self.runtime); self.aff=MemoryTierAffinityEvaluator(system)
        self.decision_ops=0
    def observe_telemetry(self,telemetry): pass
    def observe_runtime(self,obj,rate): self.runtime.observe(obj,rate)
    def place(self,obj:DataObject,telemetry:dict[str,Telemetry],cap_mult:float):
        cls=self.classifier.classify(obj); ch=self.interpreter.interpret(cls,obj)
        best=None; bestscore=-1e9
        for m in self.system.memories.values():
            headroom=m.capacity_bytes*cap_mult*(1-min(1,telemetry[m.name].capacity_util))
            if headroom+1e-6<obj.size_bytes: continue
            a=self.aff.affinity(cls,ch,obj,m)
            t=telemetry[m.name]
            resource=.58*max(0,1-t.capacity_util)+.42*max(0,1-t.bw_util)
            score=.76*a+.24*resource
            self.decision_ops+=1
            if score>bestscore: bestscore=score; best=m.name
        if best is None:
            best=max(self.system.memories.values(),key=lambda m:m.capacity_bytes*cap_mult*(1-min(1,telemetry[m.name].capacity_util))).name
        return best
