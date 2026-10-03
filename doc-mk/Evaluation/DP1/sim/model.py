from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

ATTN_OPS=frozenset({"QK_GEMM","SOFTMAX","AV_GEMM","CAUSAL_MASK"})
RETRIEVAL_DOT_OP="GEMV"
GIB=1024**3
TIB=1024**4

def clamp(x,lo=0.0,hi=1.0): return max(lo,min(hi,x))

@dataclass(frozen=True)
class MemorySpec:
    name:str
    medium:str
    capacity_bytes:float
    ext_bw:float
    int_bw:float
    latency_s:float
    gpu_reachable:bool
    primitives:frozenset[str]
    compute_flops:float|None
    attn_bw_eff:float
    write_amp:float
    write_bw:float
    tdp_watts:float

    @property
    def attention_capable(self):
        return ATTN_OPS <= self.primitives and self.compute_flops is not None

    @property
    def retrieval_dot_capable(self):
        return RETRIEVAL_DOT_OP in self.primitives and self.compute_flops is not None

@dataclass(frozen=True)
class ModelSpec:
    name:str
    layers:int
    hidden:int
    heads:int
    kv_heads:int
    head_dim:int
    dtype_bytes:int
    active_params:int

    @property
    def kv_bytes_per_token(self):
        return 2*self.layers*self.kv_heads*self.head_dim*self.dtype_bytes

    def attention_flops(self,context:int,query:int=1):
        return 4.0*self.heads*self.head_dim*context*query*self.layers

    @property
    def activation_roundtrip_bytes_per_token(self):
        # Q/attention-input direction + attention-output direction, every layer.
        return 2*self.hidden*self.dtype_bytes*self.layers

@dataclass(frozen=True)
class SystemSpec:
    memories:dict[str,MemorySpec]
    gpu_hbm_bw:float
    gpu_compute_flops:float
    gpu_tdp_watts:float
    model:ModelSpec
    gpu_bw_eff:float=0.9
    gpu_compute_eff:float=0.5

    def prefill_s(self,context:int,query:int|None=None):
        q=context if query is None else query
        attn=self.model.attention_flops(context,q)
        ffn=2.0*self.model.active_params*q
        return (attn+ffn)/(self.gpu_compute_flops*self.gpu_compute_eff)

    def gpu_non_attention_decode_s(self,batch:int):
        # Weight traffic is shared by the batch; FFN compute grows with batch.
        weight=self.model.active_params*self.model.dtype_bytes/(self.gpu_hbm_bw*self.gpu_bw_eff)
        ffn_flops=2.0*self.model.active_params*batch
        compute=ffn_flops/(self.gpu_compute_flops*self.gpu_compute_eff)
        return max(weight,compute)

    def hbm_attention_s(self,context:int,batch:int,bw_mult:float=1.0):
        kv=self.model.kv_bytes_per_token*context*batch
        bw=kv/(self.gpu_hbm_bw*self.gpu_bw_eff*max(.05,bw_mult))
        flops=self.model.attention_flops(context,1)*batch
        comp=flops/(self.gpu_compute_flops*self.gpu_compute_eff)
        return max(bw,comp)

    def offloaded_attention_s(self,mem:MemorySpec,context:int,batch:int,link_bw_mult:float=1.0):
        if not mem.attention_capable:
            return float("inf")
        kv=self.model.kv_bytes_per_token*context*batch
        mem_bw=kv/(mem.int_bw*max(0.3,mem.attn_bw_eff))
        flops=self.model.attention_flops(context,1)*batch
        comp=flops/max(1.0,float(mem.compute_flops))
        # Attention is remote, FFN remains on GPU. Activations cross the external link.
        xfer=self.model.activation_roundtrip_bytes_per_token*batch/max(1.0,mem.ext_bw*link_bw_mult)
        layer_rtt=self.model.layers*mem.latency_s
        return max(mem_bw,comp)+xfer+layer_rtt

    def decode_step_s(self,context:int,batch:int,tier:str,link_bw_mult:float=1.0):
        non_attn=self.gpu_non_attention_decode_s(batch)
        if tier=="hbm":
            attn=self.hbm_attention_s(context,batch,link_bw_mult)
        else:
            attn=self.offloaded_attention_s(self.memories[tier],context,batch,link_bw_mult)
        return non_attn+attn

    def rag_retrieval_s(self,index_bytes:float,batch:int,tier:str,embedding_dim:int=1024):
        """Vector-DB retrieval cost with SSD-PIM GEMV used only for similarity.

        Baseline path:
          SSD/Memory -> transfer full vectors -> GPU/host similarity GEMV -> ranking/top-k

        SSD-PIM path:
          vectors stay in SSD -> local GEMV similarity -> return similarity scores ->
          controller/host ranking/top-k.

        Ranking/top-k compute itself is treated as a small post-process; the main modeled
        benefit is avoiding full-vector transfer and accelerating the similarity GEMV.
        """
        m=self.memories[tier]
        vec_bytes=embedding_dim*self.model.dtype_bytes
        nvec=max(1.0,index_bytes/vec_bytes)

        # SSD-PIM supports GEMV only, so concurrent queries are modeled as repeated GEMVs.
        flops=2.0*nvec*embedding_dim*batch
        full_vector_bytes=index_bytes*batch
        score_bytes=4.0*nvec*batch  # one FP32 similarity score per stored vector/query.

        if m.retrieval_dot_capable:
            internal_scan=index_bytes*batch/max(1.0,m.int_bw)
            compute=flops/max(1.0,float(m.compute_flops))
            score_return=score_bytes/max(1.0,m.ext_bw)
            # top-k/ranking runs after score generation; its compute is not the acceleration target.
            return max(internal_scan,compute)+score_return+m.latency_s

        # Without in-storage GEMV, full vectors must cross the external path before similarity.
        data_path=full_vector_bytes/max(1.0,m.ext_bw)
        gpu_compute=flops/(self.gpu_compute_flops*self.gpu_compute_eff)
        return data_path+gpu_compute+m.latency_s

LINK_BOUND_MEMORIES=("custom_hbm","cxl_pnm","dram","ssd_pim")

def load_system(config_dir:Path,cluster_name="b200_8gpu",model_name="llama_3_1_70b",memory_names=None,
                link_scale=1.0,mem_overrides=None):
    """link_scale / mem_overrides: generation-profile hooks (systems.json 'link' / 'overrides').
    link_scale multiplies ext BW of host-link-bound tiers (LINK_BOUND_MEMORIES); 1.0 and None leave every value
    exactly as in memories_default.json (legacy SYS-1..5 unchanged)."""
    mem_overrides=mem_overrides or {}
    mr=json.loads((config_dir/"memories_default.json").read_text())
    cr=json.loads((config_dir/"clusters.json").read_text())
    mod=json.loads((config_dir/"models.json").read_text())
    cluster=cr["clusters"][cluster_name]
    gpu=cr["gpus"][cluster["gpu"]]
    ngpu=cluster["gpus_per_scaleup_domain"]

    mems={}
    for m in mr["memories"]:
        if memory_names is not None and m["name"] not in memory_names:
            continue
        cap=float(m["capacity_bytes"])
        ext=float(m["ext_bw_bytes_per_s"])
        internal=float(m["int_bw_bytes_per_s"])
        comp=m.get("compute_tflops_fp16")
        tdp=float(m.get("tdp_watts",0.0))
        if m["name"]=="hbm":
            cap=float(gpu["hbm_capacity_bytes"])*ngpu
            ext=float(gpu["hbm_bw_bytes_per_s"])*ngpu
            internal=ext
        elif m["name"]=="custom_hbm":
            # Paired-GPU relative spec (memories_default.json provenance): capacity = GPU HBM x2,
            # internal BW = GPU HBM BW x2, compute = GPU dense FP16 x20%, TDP = GPU TDP / 3.
            # Identical to the static B200 values; differs for other GPUs (e.g. Vera Rubin).
            cap=float(gpu["hbm_capacity_bytes"])*2
            internal=float(gpu["hbm_bw_bytes_per_s"])*2
            comp=float(gpu["dense_fp16_flops"])*0.20
            tdp=float(gpu["tdp_watts"])/3.0
        if m["name"] in LINK_BOUND_MEMORIES and link_scale!=1.0:
            ext=ext*link_scale
        ov=mem_overrides.get(m["name"],{})
        if "capacity_bytes" in ov: cap=float(ov["capacity_bytes"])
        if "ext_bw_bytes_per_s" in ov: ext=float(ov["ext_bw_bytes_per_s"])
        if "int_bw_bytes_per_s" in ov: internal=float(ov["int_bw_bytes_per_s"])
        lat_s=float(ov.get("latency_s",m["latency_s"]))
        wbw=m.get("write_bw_bytes_per_s")
        # legacy: write BW fell back to the JSON ext BW (not the cluster-overridden one); keep that, link-scaled.
        wbw=float(wbw) if wbw else float(m["ext_bw_bytes_per_s"])*(link_scale if m["name"] in LINK_BOUND_MEMORIES else 1.0)
        if "ext_bw_bytes_per_s" in ov and not m.get("write_bw_bytes_per_s"): wbw=ext
        mems[m["name"]]=MemorySpec(
            m["name"],m["medium"],cap,ext,internal,lat_s,
            bool(m.get("gpu_reachable",False)),frozenset(m.get("supported_primitives",[])),
            comp,float(m.get("attention_bw_efficiency") or 0.7),
            float(m.get("write_amplification",1.0)),
            wbw,tdp)

    mm=mod["models"][model_name]
    model=ModelSpec(
        model_name,int(mm["num_layers"]),int(mm["hidden"]),int(mm["num_heads"]),
        int(mm.get("num_kv_heads") or 8),int(mm.get("head_dim") or 128),
        int(mm["dtype_bytes"]),int(mm["active_params"]))

    return SystemSpec(
        mems,float(gpu["hbm_bw_bytes_per_s"])*ngpu,
        float(gpu["dense_fp16_flops"])*ngpu,float(gpu["tdp_watts"])*ngpu,model)

DATA_PRIORS={
 "KV_CACHE":dict(hotness=.92,lifetime=.35,reuse=.95,latency=.98,write=.08),
 "RAG_DATA":dict(hotness=.55,lifetime=.88,reuse=.65,latency=.78,write=.03),
 "AGENT_MEMORY":dict(hotness=.30,lifetime=.96,reuse=.48,latency=.55,write=.30),
 "TOOL_RESULT":dict(hotness=.42,lifetime=.55,reuse=.52,latency=.65,write=.25),
 "LORA_ADAPTER":dict(hotness=.68,lifetime=.88,reuse=.82,latency=.88,write=.02),
 "MOE_EXPERT":dict(hotness=.72,lifetime=.90,reuse=.88,latency=.92,write=.01),
}
DATA_CLASSES=tuple(DATA_PRIORS)

@dataclass
class DataObject:
    oid:int
    data_class:str
    size_bytes:float
    base_rate:float
    access_bytes:float
    context_tokens:int
    output_tokens:int
    lifetime_s:int
    arrival_s:int=0
    batch_size:int=16
    type_hint:str|None=None
    classification_confidence:float=0.95
    hotness_mult:float=1.0
    phase_time:int|None=None
    phase_mult:float=1.0
    latency_sensitivity:float=0.5
    write_ratio:float=0.1
    retrieval_dim:int=1024
    # ((t0, mult), ...): from t0 on the access rate is multiplied by mult (last entry with t0<=t wins).
    rate_schedule:tuple=()

    def alive(self,t): return self.arrival_s<=t<self.arrival_s+self.lifetime_s

    def rate_at(self,t):
        r=self.base_rate*self.hotness_mult
        if self.phase_time is not None and t>=self.phase_time:
            r*=self.phase_mult
        if self.rate_schedule:
            mult=1.0
            for t0,m in self.rate_schedule:   # last entry with t0 <= t wins
                if t>=t0: mult=m
            r*=mult
        return max(.001,r)

    def true_hotness(self,t):
        p=DATA_PRIORS[self.data_class]["hotness"]
        v=p*self.hotness_mult*(self.phase_mult if self.phase_time is not None and t>=self.phase_time else 1.0)
        return clamp(v)


def load_profile(config_dir:Path,profile_id:str|None=None,model_name="llama_3_1_70b"):
    """Load an evaluation system profile (configs/systems.json): cluster + memory subset."""
    sp=json.loads((config_dir/"systems.json").read_text())
    pid=profile_id or sp["default"]
    prof=sp["profiles"][pid]
    link=prof.get("link") or {}
    return load_system(config_dir,prof["cluster"],model_name,memory_names=set(prof["memories"]),
                       link_scale=float(link.get("ext_bw_scale",1.0)),mem_overrides=prof.get("overrides")),pid,prof
