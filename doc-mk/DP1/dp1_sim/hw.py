"""Evidence-tagged HW description for the DP1 serving simulation.

``build_hw()`` combines
  * configs/hw_catalog.json            (B: literature / spec / assumptions)
  * measured/<gpu>/*.json (optional)   (A: produced by measure/ scripts)
into a ``ServingHW``. Any A value overrides the B value of the same key and
the substitution is recorded in ``ServingHW.trail`` so the QA table can print
the evidence label of every result.
"""

from __future__ import annotations

import bisect
import json
import os
from dataclasses import dataclass, field
from pathlib import Path

from evidence import Evidenced, EvidenceTrail, ev

HERE = Path(__file__).resolve().parent
CATALOG = HERE / "configs" / "hw_catalog.json"
# A-evidence directory; overridable for tests / alternative result sets
MEASURED = Path(os.environ.get("DP1_MEASURED_DIR", HERE / "measured"))


@dataclass(frozen=True)
class ModelShape:
    name: str
    hf_id: str
    params: float
    layers: int
    hidden: int
    heads: int
    kv_heads: int
    head_dim: int
    dtype_bytes: int

    @property
    def weight_bytes(self) -> float:
        return self.params * self.dtype_bytes

    @property
    def kv_bytes_per_token(self) -> float:
        # K and V, all layers, all KV heads (summed over TP ranks).
        return 2 * self.layers * self.kv_heads * self.head_dim * self.dtype_bytes


class TransferCurve:
    """t(size) = alpha + size / bw(chunk).

    With A data the bandwidth is interpolated from the measured
    chunk-size sweep (log-linear), otherwise it is a constant (B).
    """

    def __init__(
        self, alpha_s: float, bw: float, points: list[tuple[float, float]] | None = None
    ):
        self.alpha_s = alpha_s
        self.bw = bw
        self.points = sorted(points or [])

    def bw_at(self, chunk_bytes: float) -> float:
        if not self.points:
            return self.bw
        xs = [p[0] for p in self.points]
        i = bisect.bisect_left(xs, chunk_bytes)
        if i <= 0:
            return self.points[0][1]
        if i >= len(xs):
            return self.points[-1][1]
        (x0, y0), (x1, y1) = self.points[i - 1], self.points[i]
        import math

        f = (math.log(chunk_bytes) - math.log(x0)) / (math.log(x1) - math.log(x0))
        return y0 + f * (y1 - y0)

    def time(self, size_bytes: float, chunk_bytes: float = 2 * 1024**2) -> float:
        if size_bytes <= 0:
            return 0.0
        return self.alpha_s + size_bytes / max(1.0, self.bw_at(chunk_bytes))


@dataclass
class TierSpec:
    """Memory tier as seen from the GPU scale-up domain.

    Attribute names ``capacity_bytes``/``ext_bw``/``latency_s`` are kept so the
    existing C1 DataMemoryAffinityMapper (policies.py) can score TierSpec as-is.
    """

    name: str
    capacity_bytes: float
    ext_bw: float  # to-GPU (promotion) bandwidth, bytes/s
    write_bw: float  # from-GPU (demotion) bandwidth, bytes/s
    latency_s: float
    lane: str  # tiers on the same lane share bandwidth ("pcie" / "hbf")
    attention_capable: bool = False
    promote: TransferCurve | None = None
    demote: TransferCurve | None = None


@dataclass
class ServingHW:
    gpu: str
    tp: int
    model: ModelShape
    hbm_bw: float  # aggregated over TP
    flops: float  # aggregated BF16 dense
    nvlink_bw: float
    kv_capacity_bytes: float  # HBM bytes vLLM gives to KV (aggregated)
    tiers: dict[str, TierSpec]
    copy_interference: float
    block_size: int = 16
    max_num_seqs: int = 256
    max_num_batched_tokens: int = 8192
    trail: EvidenceTrail = field(default_factory=EvidenceTrail)
    notes: list[str] = field(default_factory=list)

    @property
    def kv_capacity_tokens(self) -> int:
        return int(self.kv_capacity_bytes // self.model.kv_bytes_per_token)

    def summary(self) -> dict:
        return {
            "gpu": self.gpu,
            "tp": self.tp,
            "model": self.model.name,
            "hbm_bw_TBps": self.hbm_bw / 1e12,
            "bf16_TFLOPS": self.flops / 1e12,
            "kv_capacity_GiB": self.kv_capacity_bytes / 2**30,
            "kv_capacity_tokens": self.kv_capacity_tokens,
            "tiers": {
                n: {
                    "capacity_GiB": t.capacity_bytes / 2**30,
                    "to_gpu_GBps": t.ext_bw / 1e9,
                    "from_gpu_GBps": t.write_bw / 1e9,
                    "lane": t.lane,
                }
                for n, t in self.tiers.items()
            },
            "copy_interference": self.copy_interference,
            "evidence": self.trail.label(),
            "assumptions": self.trail.assumptions(),
            "notes": self.notes,
        }


def _load_json(p: Path) -> dict | None:
    try:
        return json.loads(p.read_text())
    except (OSError, json.JSONDecodeError):
        return None


def load_measurements(gpu: str, measured_dir: Path | None = None) -> dict:
    """Collect A-level measurements for one GPU type (all optional)."""
    d = (measured_dir or MEASURED) / gpu
    out = {}
    for name in ("env", "transfer", "vllm_kv_capacity"):
        j = _load_json(d / f"{name}.json")
        if j is not None:
            out[name] = j
    return out


def _curve_from_measured(rows: list[dict], alpha: float) -> TransferCurve:
    pts = [(float(r["bytes"]), float(r["bw_Bps"])) for r in rows if r.get("bw_Bps")]
    peak = max((p[1] for p in pts), default=1.0)
    return TransferCurve(alpha, peak, pts)


def build_hw(
    gpu: str,
    tp: int,
    model: str = "llama_3_1_70b",
    tiers: tuple[str, ...] = ("dram",),
    catalog_path: Path = CATALOG,
    measured_dir: Path | None = None,
    hbm_kv_scale: float = 1.0,
    use_measurements: bool = True,
) -> ServingHW:
    cat = json.loads(catalog_path.read_text())
    g = cat["gpus"][gpu]
    m = cat["models"][model]
    sd = cat["serving_defaults"]
    trail = EvidenceTrail()
    notes: list[str] = []
    meas = load_measurements(gpu, measured_dir) if use_measurements else {}

    shape = ModelShape(
        model,
        m["hf_id"],
        float(m["params"]),
        int(m["layers"]),
        int(m["hidden"]),
        int(m["heads"]),
        int(m["kv_heads"]),
        int(m["head_dim"]),
        int(m["dtype_bytes"]),
    )
    trail.use("model_shape", Evidenced(shape.params, "B3", m["source"]))

    hbm_cap = trail.use("gpu.hbm_capacity", ev(g["hbm_capacity_bytes"]))
    hbm_bw = trail.use("gpu.hbm_bw", ev(g["hbm_bw"]))
    flops = trail.use("gpu.bf16_flops", ev(g["bf16_dense_flops"]))
    nvl = trail.use("gpu.nvlink_bw", ev(g["nvlink_bw_per_dir"]))

    # --- host link (PCIe) : A overrides B ------------------------------------
    link_bw_e = ev(g["host_link_bw_per_dir"], "B2")
    link_lat_e = ev(g["host_link_latency_s"], "B2")
    h2d_curve = d2h_curve = None
    tr = meas.get("transfer")
    if tr:
        src = f"measure/01_transfer_microbench.py on {tr.get('device_name', gpu)}"
        if tr.get("h2d_pinned"):
            peak = max(r["bw_Bps"] for r in tr["h2d_pinned"])
            link_bw_e = Evidenced(peak, "A", src, "pinned H2D, per GPU")
        if tr.get("alpha_s") is not None:
            link_lat_e = Evidenced(
                float(tr["alpha_s"]), "A", src, "fitted launch latency"
            )
        h2d_curve = _curve_from_measured(tr.get("h2d_pinned", []), link_lat_e.value)
        d2h_curve = _curve_from_measured(tr.get("d2h_pinned", []), link_lat_e.value)
        if tr.get("all_gpu_concurrent_h2d_Bps"):
            # Aggregate across GPUs measured concurrently (captures root-complex/UPI limits).
            agg = float(tr["all_gpu_concurrent_h2d_Bps"])
            ngpu = int(tr.get("num_gpus_concurrent", tp))
            link_bw_e = Evidenced(
                agg / max(1, ngpu),
                "A",
                src,
                f"per-GPU share of {ngpu}-GPU concurrent H2D",
            )
    link_bw = trail.use("gpu.host_link_bw", link_bw_e)
    link_lat = trail.use("gpu.host_link_latency", link_lat_e)

    interf_e = ev(sd["copy_interference"])
    if tr and tr.get("interference", {}).get("decode_like_slowdown") is not None:
        interf_e = Evidenced(
            float(tr["interference"]["decode_like_slowdown"]),
            "A",
            "measure/01_transfer_microbench.py",
            "HBM-bound kernel slowdown under concurrent H2D+D2H",
        )
    interference = trail.use("copy_interference", interf_e)

    # --- KV capacity in HBM ----------------------------------------------------
    gmu = float(sd["gpu_memory_utilization"])
    act = trail.use("activation_reserve", ev(sd["activation_reserve_bytes_per_gpu"]))
    kv_cap = hbm_cap * tp * gmu - shape.weight_bytes - act * tp
    kvm = meas.get("vllm_kv_capacity")
    if (
        kvm
        and kvm.get("model") in (None, model)
        and int(kvm.get("tp", tp)) == tp
        and kvm.get("kv_cache_tokens")
    ):
        kv_cap = float(kvm["kv_cache_tokens"]) * shape.kv_bytes_per_token
        trail.use(
            "kv_capacity",
            Evidenced(kv_cap, "A", "vLLM startup log 'GPU KV cache size'", f"tp={tp}"),
        )
        del trail.used["activation_reserve"]
    if kv_cap <= 0:
        notes.append(f"{model} does not fit on {tp}x{gpu} with gmu={gmu}; increase TP.")
        kv_cap = 0.0
    kv_cap *= hbm_kv_scale
    if hbm_kv_scale != 1.0:
        notes.append(f"HBM KV capacity scaled x{hbm_kv_scale} (stress knob)")

    # --- lower tiers -------------------------------------------------------------
    tier_specs: dict[str, TierSpec] = {}
    pcie_total = link_bw * tp
    for name in tiers:
        t = cat["tiers"][name]
        cap = trail.use(f"{name}.capacity", ev(t["capacity_bytes"]))
        lat = trail.use(f"{name}.latency", ev(t["latency_s"]))
        if t["gpu_path"] == "host_link":
            n_dev = ev(t.get("devices"))
            n = n_dev.value if n_dev else 1.0
            if n_dev:
                trail.use(f"{name}.devices", n_dev)
            dbw_e = ev(t["device_bw"])
            if name == "nvme_ssd" and tr and tr.get("nvme_read_Bps"):
                dbw_e = Evidenced(
                    float(tr["nvme_read_Bps"]),
                    "A",
                    "fio seq read (measure/README.md)",
                    "per drive",
                )
            dev_bw = trail.use(f"{name}.device_bw", dbw_e) * (
                1.0 if name == "dram" else n
            )
            if name != "dram":
                cap *= n
            bw = min(pcie_total, dev_bw)
            lane = "pcie"
            pr = (
                h2d_curve
                if (name == "dram" and h2d_curve and h2d_curve.points)
                else TransferCurve(link_lat + lat, bw)
            )
            dm = (
                d2h_curve
                if (name == "dram" and d2h_curve and d2h_curve.points)
                else TransferCurve(link_lat + lat, bw)
            )
            if name == "dram" and h2d_curve and h2d_curve.points:
                # measured per-GPU curve -> scale to TP ranks (each rank has its own link)
                pr = TransferCurve(
                    pr.alpha_s, pr.bw * tp, [(x, y * tp) for x, y in pr.points]
                )
                dm = TransferCurve(
                    dm.alpha_s, dm.bw * tp, [(x, y * tp) for x, y in dm.points]
                )
            if name == "dram" and "env" in meas and meas["env"].get("host_mem_bytes"):
                # keep 50% of host RAM for OS / pinned staging / other processes
                cap = 0.5 * float(meas["env"]["host_mem_bytes"])
                trail.use(
                    "dram.capacity",
                    Evidenced(cap, "A", "00_env_check.sh MemTotal x0.5"),
                )
            tier_specs[name] = TierSpec(
                name,
                cap,
                bw,
                bw,
                lat,
                lane,
                bool(t.get("gpu_attention_capable")),
                pr,
                dm,
            )
        else:  # direct (HBF on package)
            stacks = trail.use(f"{name}.stacks", ev(t["stacks_per_gpu"]))
            rbw = trail.use(f"{name}.read_bw", ev(t["read_bw"])) * stacks * tp
            wbw = trail.use(f"{name}.write_bw", ev(t["write_bw"])) * stacks * tp
            cap = cap * stacks * tp
            tier_specs[name] = TierSpec(
                name,
                cap,
                rbw,
                wbw,
                lat,
                "hbf",
                False,
                TransferCurve(lat, rbw),
                TransferCurve(lat, wbw),
            )

    return ServingHW(
        gpu=gpu,
        tp=tp,
        model=shape,
        hbm_bw=hbm_bw * tp,
        flops=flops * tp,
        nvlink_bw=nvl,
        kv_capacity_bytes=kv_cap,
        tiers=tier_specs,
        copy_interference=interference,
        block_size=int(sd["block_size"]),
        max_num_seqs=int(sd["max_num_seqs"]),
        max_num_batched_tokens=int(sd["max_num_batched_tokens"]),
        trail=trail,
        notes=notes,
    )
