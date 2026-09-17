from __future__ import annotations

import json
import math
import random
from dataclasses import dataclass
from pathlib import Path


ATTN_OPS = {"QK_GEMM", "SOFTMAX", "AV_GEMM", "CAUSAL_MASK"}
GIB = 1024 ** 3
TIB = 1024 ** 4


def clamp(x: float, lo: float = 0.0, hi: float = 1.0) -> float:
    return max(lo, min(hi, x))


def weighted_quantile(samples: list[tuple[float, float]], q: float) -> float:
    if not samples:
        return 0.0
    data = sorted((v, w) for v, w in samples if w > 0)
    total = sum(w for _, w in data)
    target = total * q
    acc = 0.0
    for v, w in data:
        acc += w
        if acc >= target:
            return v
    return data[-1][0]


def poisson(rng: random.Random, lam: float) -> int:
    if lam <= 0:
        return 0
    if lam < 30:
        L = math.exp(-lam)
        k, p = 0, 1.0
        while p > L:
            k += 1
            p *= rng.random()
        return k - 1
    return max(0, int(round(rng.gauss(lam, math.sqrt(lam)))))


@dataclass(frozen=True)
class MemorySpec:
    name: str
    medium: str
    capacity_bytes: float
    ext_bw: float
    int_bw: float
    latency_s: float
    gpu_reachable: bool
    primitives: frozenset[str]
    compute_flops: float | None
    attn_bw_eff: float
    write_amp: float
    write_bw: float
    tdp_watts: float

    @property
    def attention_capable(self) -> bool:
        return ATTN_OPS <= self.primitives and self.compute_flops is not None


@dataclass(frozen=True)
class ModelSpec:
    name: str
    layers: int
    hidden: int
    heads: int
    kv_heads: int
    head_dim: int
    dtype_bytes: int
    active_params: int

    @property
    def kv_bytes_per_token(self) -> int:
        return 2 * self.layers * self.kv_heads * self.head_dim * self.dtype_bytes

    def attention_flops(self, context: int, query: int) -> float:
        return 4.0 * self.heads * self.head_dim * context * query * self.layers


@dataclass(frozen=True)
class SystemSpec:
    memories: dict[str, MemorySpec]
    gpu_hbm_bw: float
    gpu_compute_flops: float
    gpu_tdp_watts: float
    model: ModelSpec
    gpu_bw_eff: float = 0.9
    gpu_compute_eff: float = 0.5

    def prefill_s(self, context: int, query: int | None = None) -> float:
        q = context if query is None else query
        attn = self.model.attention_flops(context, q)
        ffn = 2.0 * self.model.active_params * q
        return (attn + ffn) / (self.gpu_compute_flops * self.gpu_compute_eff)

    def base_tpot_s(self, context: int) -> float:
        weight = self.model.active_params * self.model.dtype_bytes / (self.gpu_hbm_bw * self.gpu_bw_eff)
        kv = self.model.kv_bytes_per_token * context / (self.gpu_hbm_bw * self.gpu_bw_eff)
        return weight + kv


def load_system(config_dir: Path, cluster_name: str = "b200_8gpu", model_name: str = "llama_3_1_70b") -> SystemSpec:
    memories_raw = json.loads((config_dir / "memories_default.json").read_text())
    clusters_raw = json.loads((config_dir / "clusters.json").read_text())
    models_raw = json.loads((config_dir / "models.json").read_text())
    cluster = clusters_raw["clusters"][cluster_name]
    gpu = clusters_raw["gpus"][cluster["gpu"]]
    ngpu = cluster["gpus_per_scaleup_domain"]

    mems: dict[str, MemorySpec] = {}
    for m in memories_raw["memories"]:
        capacity = float(m["capacity_bytes"])
        ext = float(m["ext_bw_bytes_per_s"])
        internal = float(m["int_bw_bytes_per_s"])
        if m["name"] == "hbm":
            capacity = float(gpu["hbm_capacity_bytes"]) * ngpu
            ext = float(gpu["hbm_bw_bytes_per_s"]) * ngpu
            internal = ext
        mems[m["name"]] = MemorySpec(
            name=m["name"], medium=m["medium"], capacity_bytes=capacity,
            ext_bw=ext, int_bw=internal, latency_s=float(m["latency_s"]),
            gpu_reachable=bool(m.get("gpu_reachable", False)),
            primitives=frozenset(m.get("supported_primitives", [])),
            compute_flops=m.get("compute_tflops_fp16"),
            attn_bw_eff=float(m.get("attention_bw_efficiency") or 0.7),
            write_amp=float(m.get("write_amplification", 1.0)),
            write_bw=float(m.get("write_bw_bytes_per_s") or m["ext_bw_bytes_per_s"]),
            tdp_watts=float(m.get("tdp_watts", 0.0)),
        )

    mr = models_raw["models"][model_name]
    model = ModelSpec(
        name=model_name, layers=int(mr["num_layers"]), hidden=int(mr["hidden"]),
        heads=int(mr["num_heads"]), kv_heads=int(mr.get("num_kv_heads") or 8),
        head_dim=int(mr.get("head_dim") or 128), dtype_bytes=int(mr["dtype_bytes"]),
        active_params=int(mr["active_params"]),
    )
    return SystemSpec(
        memories=mems,
        gpu_hbm_bw=float(gpu["hbm_bw_bytes_per_s"]) * ngpu,
        gpu_compute_flops=float(gpu["dense_fp16_flops"]) * ngpu,
        gpu_tdp_watts=float(gpu["tdp_watts"]) * ngpu,
        model=model,
    )


DATA_PRIORS = {
    "KV_CACHE": dict(hotness=0.90, lifetime=0.35, reuse=0.95, latency=1.00, write=0.05),
    "RAG_DATA": dict(hotness=0.55, lifetime=0.75, reuse=0.65, latency=0.80, write=0.10),
    "AGENT_MEMORY": dict(hotness=0.30, lifetime=0.95, reuse=0.45, latency=0.55, write=0.30),
    "TOOL_RESULT": dict(hotness=0.45, lifetime=0.50, reuse=0.55, latency=0.65, write=0.25),
    "LOG_DATA": dict(hotness=0.10, lifetime=1.00, reuse=0.10, latency=0.15, write=0.90),
    "LORA_ADAPTER": dict(hotness=0.65, lifetime=0.85, reuse=0.80, latency=0.85, write=0.02),
    "MOE_EXPERT": dict(hotness=0.70, lifetime=0.90, reuse=0.85, latency=0.90, write=0.02),
    "GENERIC": dict(hotness=0.50, lifetime=0.60, reuse=0.50, latency=0.50, write=0.20),
}

CLASS_SIZE_GIB = {
    "KV_CACHE": (6.0, 20.0), "RAG_DATA": (2.0, 12.0), "AGENT_MEMORY": (1.0, 8.0),
    "TOOL_RESULT": (0.5, 4.0), "LOG_DATA": (2.0, 12.0), "LORA_ADAPTER": (0.2, 1.5),
    "MOE_EXPERT": (0.5, 3.0),
}
CLASS_RATE = {
    "KV_CACHE": 3.5, "RAG_DATA": 0.65, "AGENT_MEMORY": 0.18, "TOOL_RESULT": 0.45,
    "LOG_DATA": 0.08, "LORA_ADAPTER": 0.8, "MOE_EXPERT": 1.0,
}
CLASS_LIFETIME = {
    "KV_CACHE": 55, "RAG_DATA": 130, "AGENT_MEMORY": 220, "TOOL_RESULT": 70,
    "LOG_DATA": 300, "LORA_ADAPTER": 180, "MOE_EXPERT": 180,
}
CLASS_ACCESS_FRAC = {
    "KV_CACHE": 1.0, "RAG_DATA": 0.012, "AGENT_MEMORY": 0.004, "TOOL_RESULT": 0.01,
    "LOG_DATA": 0.003, "LORA_ADAPTER": 0.08, "MOE_EXPERT": 0.15,
}
CLASS_CONTEXT = {
    "KV_CACHE": 32768, "RAG_DATA": 16384, "AGENT_MEMORY": 16384, "TOOL_RESULT": 8192,
    "LOG_DATA": 8192, "LORA_ADAPTER": 16384, "MOE_EXPERT": 16384,
}
CLASS_OUTPUT = {
    "KV_CACHE": 64, "RAG_DATA": 96, "AGENT_MEMORY": 96, "TOOL_RESULT": 64,
    "LOG_DATA": 32, "LORA_ADAPTER": 64, "MOE_EXPERT": 64,
}


@dataclass
class DataObject:
    object_id: int
    data_class: str
    size_bytes: float
    arrival_s: int
    death_s: int
    base_rate: float
    access_bytes: float
    context_tokens: int
    output_tokens: int
    read_ratio: float
    latency_sensitivity: float
    type_hint: str | None = None
    phase_time: int | None = None
    phase_multiplier: float = 1.0
    noisy: float = 0.0

    def rate_at(self, t: int, rng: random.Random) -> float:
        r = self.base_rate
        if self.phase_time is not None and t >= self.phase_time:
            r *= self.phase_multiplier
        if self.noisy:
            r *= max(0.02, math.exp(rng.gauss(-0.5 * self.noisy ** 2, self.noisy)))
        return r

    def true_hotness(self, t: int) -> float:
        base = CLASS_RATE.get(self.data_class, 0.5)
        r = self.base_rate * (self.phase_multiplier if self.phase_time is not None and t >= self.phase_time else 1.0)
        return clamp(r / max(0.05, base * 1.5))
