"""vLLM engine-step time model, calibratable from A100 measurements.

    t_step = c0
           + c_w    * W / BW_hbm                      (weight read, once per step)
           + c_d    * 2 * P * T_tok / FLOPS           (dense GEMM compute)
           + c_kv   * kvB * ctx_read / BW_hbm         (attention KV read)
           + c_attn * attn_prefill_flops / FLOPS      (causal prefill attention)
           + c_comm * allreduce_bytes / NVLink_BW     (TP all-reduce, 2 per layer)

Features are normalised by HW specs, so the coefficients c_* are
dimensionless inverse efficiencies (c0 in seconds). That is the hypothesis of
Evaluation §12 Step 2: an A100-fitted coefficient vector + H100 spec sheet
gives a *blind* H100 prediction, whose error against H100 actuals is the
projection error band reused for unsupported HW.
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass, field
from pathlib import Path

from hw import ServingHW

FEATURES = ("c0", "c_w", "c_d", "c_kv", "c_attn", "c_comm")

# Uncalibrated prior: typical efficiencies (B/assumed). Replaced by fit().
DEFAULT_COEF = {
    "c0": 0.004,  # scheduler + launch + sampling, s
    "c_w": 1 / 0.80,
    "c_d": 1 / 0.55,
    "c_kv": 1 / 0.70,
    "c_attn": 1 / 0.45,
    "c_comm": 1 / 0.65,
}


def step_features(
    hw: ServingHW,
    prefill: list[tuple[int, int]],
    decode_ctx_sum: int,
    decode_batch: int,
) -> list[float]:
    """prefill: list of (new_tokens q, already-cached context c) chunks in this step."""
    m = hw.model
    q_tot = sum(q for q, _ in prefill)
    tokens = q_tot + decode_batch
    if tokens == 0:
        return [0.0] * len(FEATURES)
    f_w = m.weight_bytes / hw.hbm_bw
    f_d = 2.0 * m.params * tokens / hw.flops
    ctx_read = decode_ctx_sum + sum(c for _, c in prefill)
    f_kv = m.kv_bytes_per_token * ctx_read / hw.hbm_bw
    attn = sum(
        4.0 * m.layers * m.heads * m.head_dim * q * (c + q / 2.0) for q, c in prefill
    )
    f_attn = attn / hw.flops
    if hw.tp > 1:
        ar = 2 * m.layers * tokens * m.hidden * m.dtype_bytes * 2 * (hw.tp - 1) / hw.tp
        f_comm = ar / hw.nvlink_bw
    else:
        f_comm = 0.0
    return [1.0, f_w, f_d, f_kv, f_attn, f_comm]


@dataclass
class StepModel:
    coef: dict[str, float] = field(default_factory=lambda: dict(DEFAULT_COEF))
    evidence: str = "B(assumed efficiencies)"
    fit_info: dict = field(default_factory=dict)

    def step_time(
        self, hw: ServingHW, prefill, decode_ctx_sum: int, decode_batch: int
    ) -> float:
        f = step_features(hw, prefill, decode_ctx_sum, decode_batch)
        if f[0] == 0.0:
            return 0.0
        return sum(self.coef[k] * x for k, x in zip(FEATURES, f))

    def save(self, p: Path) -> None:
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(
            json.dumps(
                {
                    "coef": self.coef,
                    "evidence": self.evidence,
                    "fit_info": self.fit_info,
                },
                indent=2,
            )
        )

    @classmethod
    def load(cls, p: Path) -> StepModel:
        d = json.loads(p.read_text())
        return cls(d["coef"], d.get("evidence", "A-calibrated"), d.get("fit_info", {}))


# ----------------------------------------------------------------------------
# Offline-latency runs ("vllm bench latency") -> features
# ----------------------------------------------------------------------------


@dataclass(frozen=True)
class LatencyRun:
    batch: int
    input_len: int
    output_len: int
    latency_s: float  # measured avg end-to-end latency of one batch (A)
    source: str = ""


def run_features(hw: ServingHW, r: LatencyRun) -> list[float]:
    """Sum of step features of one offline batch run (prefill chunks + decode)."""
    budget = hw.max_num_batched_tokens
    acc = [0.0] * len(FEATURES)
    # Prefill: B prompts, chunked with the token budget, FCFS.
    remaining = [r.input_len] * r.batch
    done = [0] * r.batch
    i = 0
    while i < r.batch:
        chunks, left = [], budget
        while i < r.batch and left > 0:
            q = min(remaining[i], left)
            chunks.append((q, done[i]))
            remaining[i] -= q
            done[i] += q
            left -= q
            if remaining[i] == 0:
                i += 1
        for k, x in enumerate(step_features(hw, chunks, 0, 0)):
            acc[k] += x
    # The first output token is sampled in the last prefill step.
    for s in range(1, r.output_len):
        ctx = r.input_len + s
        for k, x in enumerate(step_features(hw, [], ctx * r.batch, r.batch)):
            acc[k] += x
    return acc


def nnls(A: list[list[float]], y: list[float], iters: int = 5000) -> list[float]:
    """Non-negative least squares by projected coordinate descent (no numpy)."""
    n = len(A[0])
    AtA = [[sum(a[i] * a[j] for a in A) for j in range(n)] for i in range(n)]
    Aty = [sum(a[i] * yy for a, yy in zip(A, y)) for i in range(n)]
    x = [0.0] * n
    for _ in range(iters):
        delta = 0.0
        for j in range(n):
            if AtA[j][j] <= 0:
                continue
            g = sum(AtA[j][k] * x[k] for k in range(n)) - Aty[j]
            nx = max(0.0, x[j] - g / AtA[j][j])
            delta = max(delta, abs(nx - x[j]))
            x[j] = nx
        if delta < 1e-12:
            break
    return x


def fit(
    hw: ServingHW,
    runs: list[LatencyRun],
    prior: StepModel | None = None,
    ridge: float = 0.05,
) -> StepModel:
    """Relative-error NNLS with a weak ridge toward the prior coefficients.

    Rows are divided by the measured latency, so each run contributes its
    relative error. Features that the design does not excite (e.g. c_comm when
    tp=1) stay near the prior thanks to the ridge rows.
    """
    prior = prior or StepModel()
    A, y = [], []
    for r in runs:
        f = run_features(hw, r)
        A.append([x / r.latency_s for x in f])
        y.append(1.0)
    # ridge rows: sqrt(ridge) * (c_k - prior_k) scaled so that it is relative
    for k, name in enumerate(FEATURES):
        row = [0.0] * len(FEATURES)
        row[k] = math.sqrt(ridge) / max(1e-9, prior.coef[name])
        A.append(row)
        y.append(math.sqrt(ridge))
    x = nnls(A, y)
    model = StepModel(dict(zip(FEATURES, x)), evidence="A-calibrated")
    model.fit_info = {
        "gpu": hw.gpu,
        "tp": hw.tp,
        "n_runs": len(runs),
        "ridge": ridge,
        "rel_err": evaluate(hw, model, runs),
    }
    return model


def evaluate(hw: ServingHW, model: StepModel, runs: list[LatencyRun]) -> dict:
    errs = []
    rows = []
    for r in runs:
        pred = sum(model.coef[k] * v for k, v in zip(FEATURES, run_features(hw, r)))
        e = (pred - r.latency_s) / r.latency_s
        errs.append(e)
        rows.append(
            {
                "batch": r.batch,
                "in": r.input_len,
                "out": r.output_len,
                "meas_s": r.latency_s,
                "pred_s": pred,
                "rel_err": e,
            }
        )
    if not errs:
        return {}
    ae = sorted(abs(e) for e in errs)
    return {
        "mape": sum(ae) / len(ae),
        "p90_abs_err": ae[min(len(ae) - 1, int(0.9 * len(ae)))],
        "max_abs_err": ae[-1],
        "bias": sum(errs) / len(errs),
        "rows": rows,
    }


def load_latency_runs(d: Path) -> list[LatencyRun]:
    """Parse measure/02_step_profile.sh outputs: b{B}_i{I}_o{O}.json."""
    runs = []
    for p in sorted(d.glob("b*_i*_o*.json")):
        try:
            j = json.loads(p.read_text())
            stem = p.stem
            b = int(stem.split("_")[0][1:])
            i = int(stem.split("_")[1][1:])
            o = int(stem.split("_")[2][1:])
            lat = j["latencies"]
            lat = (
                sorted(lat)[len(lat) // 2] if lat else float(j["avg_latency"])
            )  # median
            runs.append(LatencyRun(b, i, o, float(lat), str(p)))
        except (KeyError, ValueError, IndexError, json.JSONDecodeError):
            continue
    return runs
