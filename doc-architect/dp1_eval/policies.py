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

    def observe_runtime(self,obj,access_count,now_s=None):
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
    """C2: online observation of *actual* object accesses, not hidden workload truth.

    The evaluator samples once per simulated second. Production can use the same
    counters at a finer interval (for example 100 ms~1 s).
    """
    def __init__(self,alpha_rate=.18,alpha_reuse=.25):
        self.alpha_rate=alpha_rate
        self.alpha_reuse=alpha_reuse
        self.rate_ewma=defaultdict(float)
        self.samples=defaultdict(int)
        self.last_access_s={}
        self.reuse_interval_ewma={}
        self.first_seen_s={}
        self.clock_s=0.0

    def observe(self,obj:DataObject,access_count:float,now_s:float|None=None):
        k=obj.oid
        now=float(self.clock_s+1 if now_s is None else now_s)
        self.clock_s=max(self.clock_s,now)
        self.first_seen_s.setdefault(k,now)

        sample_rate=max(0.0,float(access_count))
        if self.samples[k]==0:
            self.rate_ewma[k]=sample_rate
        else:
            a=self.alpha_rate
            self.rate_ewma[k]=(1-a)*self.rate_ewma[k]+a*sample_rate

        if sample_rate>0:
            if k in self.last_access_s:
                interval=max(1e-3,now-self.last_access_s[k])
                if k not in self.reuse_interval_ewma:
                    self.reuse_interval_ewma[k]=interval
                else:
                    a=self.alpha_reuse
                    self.reuse_interval_ewma[k]=(1-a)*self.reuse_interval_ewma[k]+a*interval
            self.last_access_s[k]=now
        self.samples[k]+=1

    def stats(self,obj:DataObject):
        k=obj.oid
        last=self.last_access_s.get(k)
        first=self.first_seen_s.get(k,self.clock_s)
        return {
            "rate":self.rate_ewma[k],
            "samples":self.samples[k],
            "reuse_interval_s":self.reuse_interval_ewma.get(k,float("inf")),
            "idle_s":float("inf") if last is None else max(0.0,self.clock_s-last),
            "age_s":max(0.0,self.clock_s-first),
        }


class DataCharacteristicInterpreter:
    """Fuse DataClass prior with online observed behavior.

    Cold start is prior-dominated. As samples accumulate, the prior weight decays
    and object-level observations dominate.
    """
    def __init__(self,monitor:RuntimeStateMonitor,reuse_horizon_s=5.0):
        self.monitor=monitor
        self.reuse_horizon_s=reuse_horizon_s

    def interpret(self,cls:str,obj:DataObject):
        p=DATA_PRIORS.get(cls,DATA_PRIORS["TOOL_RESULT"]).copy()
        st=self.monitor.stats(obj)
        n=st["samples"]
        if n:
            observed_hotness=clamp(st["rate"]/.35)
            p["observed_hotness"]=observed_hotness
            prior_w=max(.15,math.exp(-n/6.0))
            p["hotness"]=clamp(prior_w*p["hotness"]+(1-prior_w)*observed_hotness)

            interval=st["reuse_interval_s"]
            if math.isfinite(interval):
                reuse_prob=1-math.exp(-self.reuse_horizon_s/max(1e-3,interval))
                p["reuse"]=clamp(prior_w*p["reuse"]+(1-prior_w)*reuse_prob)
                p["next_reuse_s"]=interval
            else:
                p["next_reuse_s"]=float("inf")

            # Surviving for a long time is direct evidence that lifetime is not short.
            lifetime_obs=clamp(st["age_s"]/60.0)
            p["lifetime"]=clamp(prior_w*p["lifetime"]+(1-prior_w)*max(p["lifetime"],lifetime_obs))
            p["idle_s"]=st["idle_s"]
        else:
            p["observed_hotness"]=p["hotness"]
            p["next_reuse_s"]=float("inf")
            p["idle_s"]=float("inf")

        if cls==obj.data_class:
            p["latency"]=obj.latency_sensitivity
            p["write"]=obj.write_ratio
        return p


class HBMReliefEstimator:
    """Small resource-only predictor used *only* by C2 fallback/deferred promotion.

    This does not become C2's primary placement signal; it answers one question:
    "if I stage in DRAM, is HBM likely to become safe before the next reuse?"
    """
    def __init__(self,window=8,low_watermark=.72):
        self.hist=deque(maxlen=window)
        self.low=low_watermark

    def observe(self,telemetry:dict[str,Telemetry]):
        h=telemetry["hbm"]
        self.hist.append(max(h.capacity_util,h.bw_util))

    def seconds_to_relief(self):
        if not self.hist:
            return float("inf")
        current=self.hist[-1]
        if current<=self.low:
            return 0.0
        if len(self.hist)<3:
            return float("inf")
        slope=(self.hist[-1]-self.hist[0])/max(1,len(self.hist)-1)
        if slope>=-0.005:
            return float("inf")
        return max(0.0,(current-self.low)/(-slope))


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
    """Conservative C2 recovery including deferred HBM promotion through DRAM."""
    def __init__(self,system:SystemSpec):
        self.system=system

    def _headroom(self,m:MemorySpec,t:Telemetry,cap_mult:float):
        return m.capacity_bytes*cap_mult*(1-min(1,t.capacity_util))

    def decide(self,obj:DataObject,telemetry:dict[str,Telemetry],cap_mult:float,
               characteristics:dict|None=None,seconds_to_hbm_relief:float=float("inf")):
        feasible=[m for m in self.system.memories.values()
                  if self._headroom(m,telemetry[m.name],cap_mult)>=obj.size_bytes]
        if not feasible:
            feasible=list(self.system.memories.values())

        if obj.data_class=="KV_CACHE":
            hbm=self.system.memories["hbm"]
            hbm_healthy=(hbm in feasible and telemetry["hbm"].capacity_util<.88
                         and telemetry["hbm"].bw_util<.88)
            if hbm_healthy:
                return "hbm","immediate_hbm"

            # Option A: stage cold/non-imminent KV in DRAM and wait for HBM relief.
            dram=self.system.memories["dram"]
            ch=characteristics or {}
            next_reuse=float(ch.get("next_reuse_s",float("inf")))
            promote_s=obj.size_bytes/max(1.0,min(dram.ext_bw,self.system.gpu_hbm_bw))
            wait_path_s=seconds_to_hbm_relief+promote_s
            dram_feasible=(dram in feasible)

            # If promotion is expected to finish before the next reuse, waiting in DRAM
            # adds no predicted critical-path delay and can beat remote execution.
            if (dram_feasible and math.isfinite(seconds_to_hbm_relief)
                    and seconds_to_hbm_relief<=30.0
                    and next_reuse>wait_path_s+0.05):
                return "dram","deferred_hbm_promotion"

            # Option B: execute Attention where KV resides, if TPOT budget allows.
            off=[]
            for m in feasible:
                if not m.attention_capable:
                    continue
                step=self.system.decode_step_s(obj.context_tokens,obj.batch_size,m.name)
                if step<=.050:
                    off.append((step,m.name))
            if off:
                return min(off)[1],"remote_attention"

            # Option C: storage/staging tier; restore to HBM on next use.
            # DRAM is preferred over flash because its restore path is predictable.
            if dram_feasible:
                return "dram","restore_on_access"
            return max(feasible,key=lambda m:m.ext_bw).name,"restore_on_access"

        if obj.data_class=="RAG_DATA":
            ranked=[(self.system.rag_retrieval_s(obj.size_bytes,obj.batch_size,m.name,obj.retrieval_dim),m.name)
                    for m in feasible]
            return min(ranked)[1],"rag_cost_min"

        preferred=["hbm","hbf","dram","cxl_pnm","ssd_pim","custom_hbm"]
        for name in preferred:
            if any(m.name==name for m in feasible):
                return name,"generic_safe"
        return feasible[0].name,"generic_safe"


class C2DataCentric:
    name="C2-data-centric"
    def __init__(self,system:SystemSpec):
        self.system=system
        self.classifier=DataClassifier()
        self.runtime=RuntimeStateMonitor()
        self.interpreter=DataCharacteristicInterpreter(self.runtime)
        self.aff=MemoryTierAffinityEvaluator(system)
        self.fallback=SafeFallbackSelector(system)
        self.hbm_relief=HBMReliefEstimator()
        self.deferred_hbm=set()
        self.fallback_watch=set()
        self.deferred_stage_count=0
        self.deferred_promotion_count=0
        self.decision_ops=0
        self.fallback_count=0
        self.fallback_reason=defaultdict(int)

    def observe_telemetry(self,telemetry):
        self.hbm_relief.observe(telemetry)

    def observe_runtime(self,obj,access_count,now_s=None):
        self.runtime.observe(obj,access_count,now_s)

    def should_reevaluate(self,obj:DataObject,telemetry:dict[str,Telemetry]):
        h=telemetry["hbm"]
        if obj.oid in self.deferred_hbm:
            return h.capacity_util<=.72 and h.bw_util<=.72

        # A prediction-error object stays on a short watch list while HBM is
        # pressured. Re-evaluate every 5 observed samples so that a later
        # "wait in DRAM" opportunity is not missed.
        if obj.oid in self.fallback_watch:
            st=self.runtime.stats(obj)
            return (st["samples"]>0 and st["samples"]%5==0
                    and max(h.capacity_util,h.bw_util)>.72)
        return False

    def _fallback_place(self,obj,telemetry,cap_mult,ch,reason):
        self.fallback_count+=1
        self.fallback_reason[reason]+=1
        self.fallback_watch.add(obj.oid)
        tier,mode=self.fallback.decide(
            obj,telemetry,cap_mult,ch,self.hbm_relief.seconds_to_relief())
        if mode=="deferred_hbm_promotion":
            if obj.oid not in self.deferred_hbm:
                self.deferred_stage_count+=1
            self.deferred_hbm.add(obj.oid)
        elif tier!="dram":
            self.deferred_hbm.discard(obj.oid)
        return tier

    def place(self,obj:DataObject,telemetry:dict[str,Telemetry],cap_mult:float):
        # A staged object is promoted once HBM crosses the low watermark.
        if obj.oid in self.deferred_hbm and self.should_reevaluate(obj,telemetry):
            hbm=self.system.memories["hbm"]
            headroom=hbm.capacity_bytes*cap_mult*(1-min(1,telemetry["hbm"].capacity_util))
            if headroom>=obj.size_bytes:
                self.deferred_hbm.discard(obj.oid)
                self.fallback_watch.discard(obj.oid)
                self.deferred_promotion_count+=1
                return "hbm"

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
            return self._fallback_place(obj,telemetry,cap_mult,ch,"no_capacity_candidate")

        scored.sort(reverse=True)
        _,best=scored[0]
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
            if self.system.rag_retrieval_s(obj.size_bytes,obj.batch_size,best,obj.retrieval_dim)>2.0:
                reason="predicted_first_response_violation"

        st=self.runtime.stats(obj)
        prior=DATA_PRIORS.get(cls,DATA_PRIORS["TOOL_RESULT"])["hotness"]
        if confidence<.90 and st["samples"]>=4 and abs(ch["observed_hotness"]-prior)>.45:
            reason=reason or "runtime_behavior_mismatch"

        if reason:
            return self._fallback_place(obj,telemetry,cap_mult,ch,reason)

        if best!="dram":
            self.deferred_hbm.discard(obj.oid)
        self.fallback_watch.discard(obj.oid)
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

    def observe_runtime(self,obj,access_count,now_s=None):
        pass

    def place(self,obj:DataObject,telemetry:dict[str,Telemetry],cap_mult:float):
        for name in self.spill_order:
            m=self.system.memories[name]
            headroom=m.capacity_bytes*cap_mult*(1-min(1,telemetry[name].capacity_util))
            self.decision_ops+=1
            if headroom>=obj.size_bytes:
                return name
        return "ssd_pim"


class C1MemoryCentricReinforced(C1MemoryCentric):
    """C1-R: keep resource-centric placement, add migration stability only."""
    name="C1-R-stable-resource"

    def __init__(self,system:SystemSpec,min_residency_s=10,base_margin=.08):
        super().__init__(system)
        self.tick=0
        self.min_residency_s=min_residency_s
        self.base_margin=base_margin
        self.current_tier={}
        self.last_move_tick=defaultdict(lambda:-10**9)
        self.suppressed_migrations=0

    def observe_telemetry(self,telemetry):
        self.tick+=1
        super().observe_telemetry(telemetry)

    def _scores(self,obj,telemetry,cap_mult):
        states={n:self.monitor.state(n,t) for n,t in telemetry.items()}
        cands=self.builder.build(self.system,states,obj,cap_mult)

        # Current placement is already resident and must not be excluded merely
        # because free headroom is smaller than object_size.
        current=self.current_tier.get(obj.oid)
        if current and current not in {m.name for m,_ in cands}:
            m=self.system.memories[current]
            if not (obj.data_class=="KV_CACHE" and current!="hbm" and not m.attention_capable):
                cands.append((m,states[current]))

        rawlogs=[]
        for m,_ in cands:
            if obj.data_class=="KV_CACHE" and m.attention_capable:
                raw=m.int_bw
            elif obj.data_class=="RAG_DATA" and m.retrieval_dot_capable:
                raw=m.int_bw
            else:
                raw=m.ext_bw
            rawlogs.append(math.log10(max(1,raw)))
        lo=min(rawlogs); hi=max(rawlogs); den=max(.1,hi-lo)

        scores={}
        for (m,st),rawlog in zip(cands,rawlogs):
            speed=(rawlog-lo)/den
            cap=max(0,1-st.predicted_pressure)
            bw=max(0,1-st.predicted_bw)
            latency=1/(1+m.latency_s/2e-6)
            sizecap=min(1,math.log2(max(2,m.capacity_bytes/obj.size_bytes))/8)
            scores[m.name]=.30*cap+.24*bw+.32*speed+.09*latency+.05*sizecap
            self.decision_ops+=1
        return states,scores

    def _migration_penalty(self,obj,src,dst):
        if src==dst:
            return 0.0
        a=self.system.memories[src]; b=self.system.memories[dst]
        transfer_s=obj.size_bytes/max(1.0,min(a.ext_bw,b.ext_bw))
        return min(.20,(transfer_s/.5)*.05)

    def place(self,obj:DataObject,telemetry:dict[str,Telemetry],cap_mult:float):
        states,scores=self._scores(obj,telemetry,cap_mult)
        best=max(scores,key=scores.get)
        cur=self.current_tier.get(obj.oid)

        if cur is None or cur not in scores:
            self.current_tier[obj.oid]=best
            self.last_move_tick[obj.oid]=self.tick
            return best

        if best==cur:
            return cur

        cur_state=states[cur]
        hard_pressure=max(cur_state.predicted_pressure,cur_state.predicted_bw)>=.92
        residency=self.tick-self.last_move_tick[obj.oid]

        if not hard_pressure and residency<self.min_residency_s:
            self.suppressed_migrations+=1
            return cur

        low_pressure=max(cur_state.current_pressure,cur_state.current_bw)<=.75
        margin=self.base_margin+(.03 if low_pressure else 0.0)
        required_gain=margin+self._migration_penalty(obj,cur,best)
        gain=scores[best]-scores[cur]

        if not hard_pressure and gain<=required_gain:
            self.suppressed_migrations+=1
            return cur

        self.current_tier[obj.oid]=best
        self.last_move_tick[obj.oid]=self.tick
        return best


class C2DataCentricReinforced(C2DataCentric):
    """C2-R: feasibility-first selection + stateful fallback/migration stability."""
    name="C2-R-feasibility-stable"

    def __init__(self,system:SystemSpec,min_residency_s=10,base_margin=.08,cooldown_s=10):
        super().__init__(system)
        self.tick=0
        self.min_residency_s=min_residency_s
        self.base_margin=base_margin
        self.cooldown_s=cooldown_s
        self.current_tier={}
        self.last_move_tick=defaultdict(lambda:-10**9)
        self.last_fallback_tick=defaultdict(lambda:-10**9)
        self.mismatch_streak=defaultdict(int)
        self.suppressed_migrations=0
        self.feasibility_filtered=0
        self.infeasible_stable_hold=0

    def observe_telemetry(self,telemetry):
        self.tick+=1
        super().observe_telemetry(telemetry)

    def should_reevaluate(self,obj:DataObject,telemetry:dict[str,Telemetry]):
        # Deferred promotion has priority.
        if obj.oid in self.deferred_hbm:
            h=telemetry["hbm"]
            return h.capacity_util<=.72 and h.bw_util<=.72

        # Retry a fallback only after cooldown and enough new observations.
        if obj.oid in self.fallback_watch:
            if self.tick-self.last_fallback_tick[obj.oid] < self.cooldown_s:
                return False
            st=self.runtime.stats(obj)
            return st["samples"]>=4 and st["samples"]%5==0
        return False

    def _capacity_feasible(self,obj,m,telemetry,cap_mult,current):
        if m.name==current:
            return telemetry[m.name].capacity_util<=1.0
        headroom=m.capacity_bytes*cap_mult*(1-min(1,telemetry[m.name].capacity_util))
        return headroom+1e-6>=obj.size_bytes

    def _hard_feasible(self,cls,obj,m):
        if cls=="KV_CACHE":
            if m.name=="hbm":
                return True
            return m.attention_capable and self.system.decode_step_s(
                obj.context_tokens,obj.batch_size,m.name)<=.050
        return True

    def _score(self,cls,ch,obj,m,telemetry):
        a=self.aff.affinity(cls,ch,obj,m)
        t=telemetry[m.name]
        resource=.58*max(0,1-t.capacity_util)+.42*max(0,1-t.bw_util)
        self.decision_ops+=1
        return .76*a+.24*resource

    def _migration_penalty(self,obj,src,dst):
        if src==dst:
            return 0.0
        a=self.system.memories[src]; b=self.system.memories[dst]
        transfer_s=obj.size_bytes/max(1.0,min(a.ext_bw,b.ext_bw))
        return min(.25,(transfer_s/.5)*.06)

    def _commit(self,obj,tier):
        old=self.current_tier.get(obj.oid)
        if old!=tier:
            self.last_move_tick[obj.oid]=self.tick
        self.current_tier[obj.oid]=tier
        return tier

    def _stable_fallback(self,obj,telemetry,cap_mult,ch,reason):
        cur=self.current_tier.get(obj.oid)
        if (cur is not None and
                self.tick-self.last_fallback_tick[obj.oid] < self.cooldown_s):
            self.suppressed_migrations+=1
            return cur

        self.last_fallback_tick[obj.oid]=self.tick
        tier=super()._fallback_place(obj,telemetry,cap_mult,ch,reason)
        return self._commit(obj,tier)

    def place(self,obj:DataObject,telemetry:dict[str,Telemetry],cap_mult:float):
        # Complete deferred DRAM -> HBM promotion only at the low watermark.
        if obj.oid in self.deferred_hbm:
            h=telemetry["hbm"]
            if h.capacity_util<=.72 and h.bw_util<=.72:
                hbm=self.system.memories["hbm"]
                headroom=hbm.capacity_bytes*cap_mult*(1-min(1,h.capacity_util))
                if headroom>=obj.size_bytes:
                    self.deferred_hbm.discard(obj.oid)
                    self.fallback_watch.discard(obj.oid)
                    self.deferred_promotion_count+=1
                    return self._commit(obj,"hbm")
            cur=self.current_tier.get(obj.oid)
            if cur:
                return cur

        cls,confidence=self.classifier.classify(obj)
        ch=self.interpreter.interpret(cls,obj)
        cur=self.current_tier.get(obj.oid)

        capacity_candidates=[
            m for m in self.system.memories.values()
            if self._capacity_feasible(obj,m,telemetry,cap_mult,cur)
        ]
        if not capacity_candidates:
            return self._stable_fallback(
                obj,telemetry,cap_mult,ch,"no_capacity_candidate")

        hard_candidates=[m for m in capacity_candidates if self._hard_feasible(cls,obj,m)]
        self.feasibility_filtered += len(capacity_candidates)-len(hard_candidates)

        if cls=="RAG_DATA":
            # Distinguish "all options are slower than SLO" from prediction error.
            slo_candidates=[
                m for m in hard_candidates
                if self.system.rag_retrieval_s(
                    obj.size_bytes,obj.batch_size,m.name,obj.retrieval_dim)<=2.0
            ]
            if slo_candidates:
                hard_candidates=slo_candidates
            elif hard_candidates:
                # Stable minimum-cost hold: no repeated fallback storm.
                best=min(
                    hard_candidates,
                    key=lambda m:self.system.rag_retrieval_s(
                        obj.size_bytes,obj.batch_size,m.name,obj.retrieval_dim))
                self.infeasible_stable_hold+=1
                if cur in {m.name for m in hard_candidates}:
                    cur_cost=self.system.rag_retrieval_s(
                        obj.size_bytes,obj.batch_size,cur,obj.retrieval_dim)
                    best_cost=self.system.rag_retrieval_s(
                        obj.size_bytes,obj.batch_size,best.name,obj.retrieval_dim)
                    if cur_cost<=best_cost*1.10:
                        return cur
                return self._commit(obj,best.name)

        if not hard_candidates:
            return self._stable_fallback(
                obj,telemetry,cap_mult,ch,"hard_feasibility_empty")

        scores={m.name:self._score(cls,ch,obj,m,telemetry) for m in hard_candidates}
        best=max(scores,key=scores.get)

        # Low classifier confidence: one conservative fallback, then cooldown.
        if confidence<.65:
            return self._stable_fallback(
                obj,telemetry,cap_mult,ch,"low_classifier_confidence")

        # Runtime mismatch must persist for 3 evaluations before causing a transition.
        st=self.runtime.stats(obj)
        prior=DATA_PRIORS.get(cls,DATA_PRIORS["TOOL_RESULT"])["hotness"]
        mismatch=(confidence<.90 and st["samples"]>=4
                  and abs(ch["observed_hotness"]-prior)>.45)
        self.mismatch_streak[obj.oid] = (
            self.mismatch_streak[obj.oid]+1 if mismatch else 0)
        if self.mismatch_streak[obj.oid]>=3:
            self.mismatch_streak[obj.oid]=0
            return self._stable_fallback(
                obj,telemetry,cap_mult,ch,"runtime_behavior_mismatch")

        if cur is None or cur not in scores:
            self.fallback_watch.discard(obj.oid)
            return self._commit(obj,best)

        if best==cur:
            self.fallback_watch.discard(obj.oid)
            return cur

        current_pressure=max(
            telemetry[cur].capacity_util,telemetry[cur].bw_util)
        hard_pressure=current_pressure>=.92
        residency=self.tick-self.last_move_tick[obj.oid]

        if not hard_pressure and residency<self.min_residency_s:
            self.suppressed_migrations+=1
            return cur

        gain=scores[best]-scores[cur]
        margin=self.base_margin+self._migration_penalty(obj,cur,best)
        if not hard_pressure and gain<=margin:
            self.suppressed_migrations+=1
            return cur

        self.fallback_watch.discard(obj.oid)
        return self._commit(obj,best)


@dataclass
class PlacementPath:
    tier:str
    mode:str
    service_s:float
    ttft_s:float
    tpot_s:float
    slo_feasible:bool
    perf_cost:float


class DataTypeResolver:
    """V2: DataDescriptor -> deterministic runtime data class."""
    def resolve(self,obj:DataObject):
        return obj.data_class


class C1MemoryCentricR2(C1MemoryCentric):
    """C1-R2: resource-centric placement + relative performance guard.

    C1 remains resource-centric: it does not use runtime hotness/reuse/lifetime.
    Required operation capability and static execution-cost estimates are allowed
    as hard/resource cost information.  Emergency pressure relief cannot bypass
    the performance guard.
    """
    name="C1-R2-emergency-resource"

    def __init__(self,system:SystemSpec,emergency_high=.90,relief_target=.85,
                 performance_margin=.02,max_perf_regression=.10):
        super().__init__(system)
        self.current_tier={}
        self.emergency_high=emergency_high
        self.relief_target=relief_target
        self.performance_margin=performance_margin
        self.max_perf_regression=max_perf_regression
        self.emergency_count=0
        self.emergency_migrations=0
        self.performance_bypass_count=0
        self.emergency_blocked_by_perf=0

    def _utility(self,obj,m,st,current):
        if obj.data_class=="KV_CACHE" and m.attention_capable:
            raw=m.int_bw
        elif obj.data_class=="RAG_DATA" and m.retrieval_dot_capable:
            raw=m.int_bw
        else:
            raw=m.ext_bw

        speed=clamp((math.log10(max(1,raw))-math.log10(16e9))/
                    (math.log10(64e12)-math.log10(16e9)))
        cap=max(0,1-st.predicted_pressure)
        bw=max(0,1-st.predicted_bw)
        latency=1/(1+m.latency_s/2e-6)
        sizecap=min(1,math.log2(max(2,m.capacity_bytes/obj.size_bytes))/8)
        utility=.30*cap+.24*bw+.32*speed+.09*latency+.05*sizecap

        # Movement/stability cost is part of resource utility.
        if current and current!=m.name:
            src=self.system.memories[current]
            transfer_s=obj.size_bytes/max(1.0,min(src.ext_bw,m.ext_bw))
            utility-=min(.22,.08+transfer_s*.04)
        return utility

    def _migration_proxy(self,obj,current,target):
        if not current or current==target:
            return 0.0
        a=self.system.memories[current]
        b=self.system.memories[target]
        return .20*obj.size_bytes/max(1.0,min(a.ext_bw,b.ext_bw))

    def _performance_path(self,obj,m,telemetry,current):
        """Static end-to-end path estimate; no runtime data behavior is used."""
        q=min(2048,obj.context_tokens)
        prefill=self.system.prefill_s(obj.context_tokens,q)
        non_attn=self.system.gpu_non_attention_decode_s(obj.batch_size)
        hbm_attn=self.system.hbm_attention_s(obj.context_tokens,obj.batch_size)
        hbm_tpot=non_attn+hbm_attn
        hbm_service=max(non_attn,hbm_attn)
        migration=self._migration_proxy(obj,current,m.name)

        if obj.data_class=="KV_CACHE":
            if m.name=="hbm":
                ttft=prefill+migration
                tpot=hbm_tpot
                service=hbm_service
            elif m.attention_capable:
                attn=self.system.offloaded_attention_s(
                    m,obj.context_tokens,obj.batch_size)
                ttft=prefill+migration
                tpot=non_attn+attn
                service=max(non_attn,attn)
            else:
                restore=obj.size_bytes/max(1.0,m.ext_bw)
                ttft=prefill+restore+migration
                tpot=hbm_tpot
                service=max(hbm_service,restore)
        elif obj.data_class=="RAG_DATA":
            retrieval=self.system.rag_retrieval_s(
                obj.size_bytes,obj.batch_size,m.name,obj.retrieval_dim)
            ttft=prefill+retrieval+migration
            tpot=hbm_tpot
            service=max(hbm_service,retrieval/max(1,obj.output_tokens))
        else:
            transfer=0.0 if m.name=="hbm" else (
                min(obj.size_bytes,obj.access_bytes*obj.batch_size)/
                max(1.0,m.ext_bw))
            ttft=prefill+transfer+migration

            # LoRA/MoE remote accesses are on the decode critical path.
            # Mirror the simulator's execution-cost model so the guard does not
            # mistake resource relief for a free performance win.
            if obj.data_class in ("LORA_ADAPTER","MOE_EXPERT") and m.name!="hbm":
                remote_per_token=transfer/max(1,obj.output_tokens)
                tpot=hbm_tpot+remote_per_token
                service=max(hbm_service,tpot)
            else:
                tpot=hbm_tpot
                service=max(hbm_service,transfer/max(1,obj.output_tokens))

        # Current resource pressure affects effective service cost, but no SLO is used.
        pressure=max(
            telemetry[m.name].capacity_util,
            telemetry[m.name].bw_util)
        pressure_mult=1.0+max(0.0,pressure-.75)*2.0
        return {
            "tier":m.name,
            "service_s":service*pressure_mult,
            "ttft_s":ttft*pressure_mult,
            "tpot_s":tpot*pressure_mult,
        }

    def _relative_cost(self,path,base):
        return max(
            path["service_s"]/max(1e-9,base["service_s"]),
            path["ttft_s"]/max(1e-9,base["ttft_s"]),
            path["tpot_s"]/max(1e-9,base["tpot_s"]),
        )

    def _candidate_beats_baseline(self,cand,base):
        if cand["tier"]==base["tier"]:
            return True
        service_win=(
            cand["service_s"] <=
            base["service_s"]*(1-self.performance_margin))
        ttft_win=(
            cand["ttft_s"] <=
            base["ttft_s"]*(1-self.performance_margin))
        tpot_safe=(
            cand["tpot_s"] <=
            base["tpot_s"]*(1+self.max_perf_regression))
        return tpot_safe and (service_win or ttft_win)

    def place(self,obj:DataObject,telemetry:dict[str,Telemetry],cap_mult:float):
        states={n:self.monitor.state(n,t) for n,t in telemetry.items()}
        current=self.current_tier.get(obj.oid)
        cands=self.builder.build(self.system,states,obj,cap_mult)

        # Current placement remains a legal keep option.
        if current and current not in {m.name for m,_ in cands}:
            m=self.system.memories[current]
            if not (obj.data_class=="KV_CACHE" and
                    current!="hbm" and not m.attention_capable):
                cands.append((m,states[current]))

        if not cands:
            return current or "hbm"

        scored=[]
        paths={}
        for m,st in cands:
            scored.append((self._utility(obj,m,st,current),m.name))
            paths[m.name]=self._performance_path(obj,m,telemetry,current)
            self.decision_ops+=1

        resource_best=max(scored)[1]

        # C1 baseline is current placement when one exists; otherwise HBM if available.
        if current in paths:
            baseline=paths[current]
        elif "hbm" in paths:
            baseline=paths["hbm"]
        else:
            baseline=min(paths.values(),key=lambda p:p["service_s"])

        chosen=resource_best
        cand=paths[chosen]

        # Same no-regret idea as C2-R2, but without C2 runtime data semantics.
        if (chosen!=baseline["tier"] and
                not self._candidate_beats_baseline(cand,baseline)):
            self.performance_bypass_count+=1
            chosen=baseline["tier"]

        h=states["hbm"]
        hbm_now=max(
            telemetry["hbm"].capacity_util,
            telemetry["hbm"].bw_util)
        hbm_pred=max(h.predicted_pressure,h.predicted_bw)
        emergency=(
            hbm_now>=self.emergency_high or
            (hbm_now>=self.relief_target and
             hbm_pred>=self.emergency_high))

        # Emergency changes the objective to pressure relief, but only among
        # candidates that remain performance-safe relative to the current/HBM path.
        if current=="hbm" and emergency and hbm_now>self.relief_target:
            self.emergency_count+=1
            safe=[]
            for score,name in scored:
                if name=="hbm":
                    continue
                p=paths[name]
                rel=self._relative_cost(p,baseline)
                if (self._candidate_beats_baseline(p,baseline) or
                        rel<=1+self.max_perf_regression):
                    safe.append((score-rel*.05,name))

            if safe:
                target=max(safe)[1]
                self.current_tier[obj.oid]=target
                self.emergency_migrations+=1
                return target

            self.emergency_blocked_by_perf+=1
            self.performance_bypass_count+=1
            self.current_tier[obj.oid]=baseline["tier"]
            return baseline["tier"]

        self.current_tier[obj.oid]=chosen
        return chosen


class C2DataCentricR2:
    """C2-R2: deterministic data type + path-cost comparison + degraded placement.

    There is no classifier-confidence fallback.  A placement path always exists
    as long as at least one memory tier has physical capacity; a path may simply
    be unable to satisfy the requested SLO, in which case it is marked degraded.
    """
    name="C2-R2-path-aware"

    def __init__(self,system:SystemSpec,performance_margin=.02):
        self.system=system
        self.resolver=DataTypeResolver()
        self.runtime=RuntimeStateMonitor()
        self.interpreter=DataCharacteristicInterpreter(self.runtime)
        self.aff=MemoryTierAffinityEvaluator(system)
        self.hbm_relief=HBMReliefEstimator()
        self.performance_margin=performance_margin
        self.current_tier={}
        self.current_mode={}
        self.deferred_hbm=set()

        self.decision_ops=0
        self.degraded_count=0
        self.no_physical_capacity_count=0
        self.performance_bypass_count=0
        self.deferred_stage_count=0
        self.deferred_promotion_count=0
        self.path_mode_count=defaultdict(int)

        # compatibility with existing report fields
        self.fallback_count=0
        self.fallback_reason=defaultdict(int)
        self.suppressed_migrations=0
        self.feasibility_filtered=0
        self.infeasible_stable_hold=0

    def observe_telemetry(self,telemetry):
        self.hbm_relief.observe(telemetry)

    def observe_runtime(self,obj,access_count,now_s=None):
        self.runtime.observe(obj,access_count,now_s)

    def should_reevaluate(self,obj:DataObject,telemetry:dict[str,Telemetry]):
        if obj.oid in self.deferred_hbm:
            h=telemetry["hbm"]
            return h.capacity_util<=.72 and h.bw_util<=.72
        return False

    def _headroom_ok(self,obj,m,telemetry,cap_mult,current):
        if current==m.name:
            return True
        headroom=m.capacity_bytes*cap_mult*(1-min(1,telemetry[m.name].capacity_util))
        return headroom+1e-6>=obj.size_bytes

    def _migration_proxy(self,obj,current,target):
        if not current or current==target:
            return 0.0
        a=self.system.memories[current]; b=self.system.memories[target]
        return .20*obj.size_bytes/max(1.0,min(a.ext_bw,b.ext_bw))

    def _path(self,cls,ch,obj,m,telemetry,current):
        q=min(2048,obj.context_tokens)
        prefill=self.system.prefill_s(obj.context_tokens,q)
        non_attn=self.system.gpu_non_attention_decode_s(obj.batch_size)
        hbm_attn=self.system.hbm_attention_s(obj.context_tokens,obj.batch_size)
        hbm_tpot=non_attn+hbm_attn
        hbm_service=max(non_attn,hbm_attn)
        migration=self._migration_proxy(obj,current,m.name)

        if cls=="KV_CACHE":
            if m.name=="hbm":
                mode="hbm_direct"
                tpot=hbm_tpot
                ttft=prefill+migration
                service=hbm_service
            elif m.attention_capable:
                mode="near_memory_attention"
                attn=self.system.offloaded_attention_s(
                    m,obj.context_tokens,obj.batch_size)
                tpot=non_attn+attn
                ttft=prefill+migration
                service=max(non_attn,attn)
            else:
                mode="restore_on_access"
                restore=obj.size_bytes/max(1.0,m.ext_bw)
                tpot=hbm_tpot
                ttft=prefill+restore+migration
                service=max(hbm_service,restore)

        elif cls=="RAG_DATA":
            mode="local_gemv" if m.retrieval_dot_capable else "transfer_then_gemv"
            retrieval=self.system.rag_retrieval_s(
                obj.size_bytes,obj.batch_size,m.name,obj.retrieval_dim)
            tpot=hbm_tpot
            ttft=prefill+retrieval+migration
            service=max(hbm_service,retrieval/max(1,obj.output_tokens))

        else:
            mode="resident" if m.name=="hbm" else "remote_access"
            transfer=0.0 if m.name=="hbm" else (
                min(obj.size_bytes,obj.access_bytes*obj.batch_size)/max(1.0,m.ext_bw))
            tpot=hbm_tpot
            ttft=prefill+transfer+migration
            service=max(hbm_service,transfer/max(1,obj.output_tokens))

        # Resource pressure is part of end-to-end path cost.
        pressure=max(telemetry[m.name].capacity_util,telemetry[m.name].bw_util)
        pressure_mult=1.0+max(0.0,pressure-.75)*2.0
        ttft_eff=ttft*pressure_mult
        service_eff=service*pressure_mult

        slo=(ttft_eff<=2.0 and tpot<=.050)
        perf=max(ttft_eff/2.0,tpot/.050,service_eff/.050)

        # Data characteristics break close performance ties; performance remains primary.
        affinity=self.aff.affinity(cls,ch,obj,m)
        perf=max(0.0,perf-.08*affinity)
        self.decision_ops+=1
        return PlacementPath(m.name,mode,service_eff,ttft_eff,tpot,slo,perf)

    def _baseline_path(self,paths):
        by={p.tier:p for p in paths}
        for name in ("hbm","hbf","dram","cxl_pnm","custom_hbm","ssd_pim"):
            if name in by:
                return by[name]
        return min(paths,key=lambda p:p.perf_cost)

    def _candidate_beats_baseline(self,cand,base):
        if cand.tier==base.tier and cand.mode==base.mode:
            return True
        throughput_win=cand.service_s <= base.service_s*(1-self.performance_margin)
        ttft_win=cand.ttft_s <= base.ttft_s*(1-self.performance_margin)
        # Never buy a large decode-latency regression for a small throughput gain.
        latency_safe=cand.tpot_s <= max(.050,base.tpot_s*1.10)
        return latency_safe and (throughput_win or ttft_win)

    def _commit(self,obj,path):
        self.current_tier[obj.oid]=path.tier
        self.current_mode[obj.oid]=path.mode
        self.path_mode_count[path.mode]+=1
        return path.tier

    def place(self,obj:DataObject,telemetry:dict[str,Telemetry],cap_mult:float):
        current=self.current_tier.get(obj.oid)

        # Deferred DRAM staging is promoted only when HBM has actually recovered.
        if obj.oid in self.deferred_hbm:
            h=telemetry["hbm"]
            hbm=self.system.memories["hbm"]
            headroom=hbm.capacity_bytes*cap_mult*(1-min(1,h.capacity_util))
            if h.capacity_util<=.72 and h.bw_util<=.72 and headroom>=obj.size_bytes:
                self.deferred_hbm.discard(obj.oid)
                self.deferred_promotion_count+=1
                dummy=PlacementPath("hbm","hbm_direct",0,0,0,True,0)
                return self._commit(obj,dummy)
            if current:
                return current

        cls=self.resolver.resolve(obj)
        ch=self.interpreter.interpret(cls,obj)

        paths=[]
        for m in self.system.memories.values():
            if self._headroom_ok(obj,m,telemetry,cap_mult,current):
                paths.append(self._path(cls,ch,obj,m,telemetry,current))

        if not paths:
            # True all-tier capacity exhaustion: this is an admission/OOM condition,
            # not an ordinary placement fallback.  Keep current data if possible.
            self.no_physical_capacity_count+=1
            if current:
                return current
            best=max(
                self.system.memories.values(),
                key=lambda m:m.capacity_bytes*cap_mult*
                    (1-min(1,telemetry[m.name].capacity_util)))
            self.current_tier[obj.oid]=best.name
            self.current_mode[obj.oid]="oom_best_effort"
            return best.name

        feasible=[p for p in paths if p.slo_feasible]
        baseline=self._baseline_path(paths)

        if feasible:
            best=min(feasible,key=lambda p:p.perf_cost)

            # No-regret guard: if a non-baseline path cannot beat the As-Is path,
            # use the baseline path rather than exercising a tier just because it exists.
            if baseline.slo_feasible and not self._candidate_beats_baseline(best,baseline):
                if best.tier!=baseline.tier or best.mode!=baseline.mode:
                    self.performance_bypass_count+=1
                best=baseline

            # Under high HBM pressure, an SLO-feasible non-HBM path may be chosen
            # even if its point estimate is close, because it relieves the bottleneck.
            hp=max(telemetry["hbm"].capacity_util,telemetry["hbm"].bw_util)
            if hp>=.90 and best.tier=="hbm":
                off=[p for p in feasible if p.tier!="hbm" and p.tpot_s<=.050]
                if off:
                    alt=min(off,key=lambda p:p.perf_cost)
                    if alt.perf_cost<=best.perf_cost*1.10:
                        best=alt

            return self._commit(obj,best)

        # No path can satisfy TTFT+TPOT simultaneously: choose best effort.
        # This is a degraded placement, not a post-hoc fallback.
        self.degraded_count+=1

        # A temporary DRAM stage is useful only when predicted HBM relief occurs
        # before the next reuse.  next_reuse is not a fallback criterion in general.
        if cls=="KV_CACHE":
            dram=next((p for p in paths if p.tier=="dram"),None)
            relief=self.hbm_relief.seconds_to_relief()
            next_reuse=float(ch.get("next_reuse_s",float("inf")))
            if dram is not None and math.isfinite(relief) and relief<=30.0:
                promote_s=obj.size_bytes/max(
                    1.0,min(self.system.memories["dram"].ext_bw,self.system.gpu_hbm_bw))
                if next_reuse>relief+promote_s+.05:
                    dram=PlacementPath(
                        dram.tier,"dram_stage_wait",dram.service_s,
                        dram.ttft_s,dram.tpot_s,False,dram.perf_cost)
                    if obj.oid not in self.deferred_hbm:
                        self.deferred_stage_count+=1
                    self.deferred_hbm.add(obj.oid)
                    return self._commit(obj,dram)

        best=min(paths,key=lambda p:p.perf_cost)
        return self._commit(obj,best)
