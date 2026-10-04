"""Parameter loading for the DP4 simulator. Every number comes from configs/cluster_dp4.json."""
from __future__ import annotations

import json
from dataclasses import dataclass, fields, replace
from pathlib import Path

HERE = Path(__file__).resolve().parent
DEFAULT_CONFIG = HERE / "configs" / "cluster_dp4.json"
PROVENANCE_OK = {"PAPER", "SPEC", "ASSUMED", "PAPER/ASSUMED"}


@dataclass(frozen=True)
class Params:
    cxl_latency_ns: float
    pool_capacity_bytes: float
    pool_bw_Bps: float
    cxl_adapters_per_node: int
    cxl_adapter_bw_Bps: float
    eta_cxl: float
    block_tokens: int
    gpu_cxl_write_16KB_us: float
    gpu_cxl_write_flush_16KB_us: float
    overlap_ratio: float
    rpc_rtt_us: float
    server_threads: int
    server_thread_mops: float
    rpc_hash_batch: int
    client_ntstore_us: float
    server_restart_s: float
    server_rebuild_s: float
    meta_read_us: float
    meta_write_flush_us: float
    lock_stripes: int
    probe_us: float
    local_lock_us: float
    cs_per_request: int
    lookup_probe_mult: float
    lease_s: float
    nic_bw_Bps: float
    eta_rdma: float
    index_lookup_us: float
    batch_cap: int
    slo_ttft_s: float
    slo_tpot_s: float
    warmup_frac: float
    base_load_frac: float
    n_req_base: int
    node_recovery_s: float
    meta_entries_per_line: int
    evict_threshold: float
    turn_gap_s: float
    turn_new_tokens: int
    shared_prefix_tokens: int
    shared_prefix_frac: float

    # derived
    @property
    def cxl_node_bw(self):  # effective per-direction node CXL bandwidth, B/s
        return self.cxl_adapters_per_node * self.cxl_adapter_bw_Bps * self.eta_cxl

    @property
    def rdma_node_bw(self):
        return self.nic_bw_Bps * self.eta_rdma

    @property
    def server_service_s(self):
        return 1.0 / (self.server_thread_mops * 1e6)

    def with_overrides(self, **kw):
        names = {f.name for f in fields(self)}
        bad = set(kw) - names
        if bad:
            raise KeyError(f"unknown params: {sorted(bad)}")
        return replace(self, **kw)


def load_raw(path=None):
    return json.loads(Path(path or DEFAULT_CONFIG).read_text())["params"]


def load_params(path=None, overrides=None):
    raw = load_raw(path)
    names = {f.name for f in fields(Params)}
    if set(raw) != names:
        raise ValueError(f"config/dataclass mismatch: {sorted(set(raw) ^ names)}")
    for k, v in raw.items():
        if v["provenance"] not in PROVENANCE_OK:
            raise ValueError(f"{k}: bad provenance {v['provenance']}")
    p = Params(**{k: v["value"] for k, v in raw.items()})
    return p.with_overrides(**overrides) if overrides else p
