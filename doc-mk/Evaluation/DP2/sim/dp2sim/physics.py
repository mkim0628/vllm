"""Physical model (M0 spec 4.2-4.5). Wraps DP1 SystemSpec (read-only) and adds the DP2 iteration/transfer rules."""
from __future__ import annotations

import json
import math
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
SIM = HERE.parent
DP1_SIM = SIM.parent.parent / "DP1" / "sim"
if str(DP1_SIM) not in sys.path:
    sys.path.insert(0, str(DP1_SIM))
from model import load_profile  # noqa: E402  (DP1, read-only)

CFG = json.loads((SIM / "configs" / "dp2_params.json").read_text())["params"]
LINKS = json.loads((SIM / "configs" / "internode_links.json").read_text())

TIERS = ("hbm", "custom_hbm", "cxl_pnm", "dram", "hbf", "ssd_pim")
DECODE_TIERS = ("hbm", "custom_hbm", "cxl_pnm", "hbf")
OFFLOAD = ("custom_hbm", "cxl_pnm")
ALLOC_ORDER = ("hbm", "dram", "cxl_pnm", "hbf", "ssd_pim", "custom_hbm")  # DP1 external allocator (A09)
TARGET = {"hbm": 0.80}  # others 0.90


def target(tier):
    return TARGET.get(tier, 0.90)


def cfgv(key):
    return CFG[key]["value"]


_SYS = {}


def system(sys_id):
    if sys_id not in _SYS:
        _SYS[sys_id] = load_profile(DP1_SIM / "configs", sys_id)[0]
    return _SYS[sys_id]


class Phys:
    """Closed-form building blocks, all in seconds / bytes. One instance per (system, kappa)."""

    def __init__(self, sysspec, kappa=1.0):
        self.s = sysspec
        m = sysspec.model
        self.kvb = m.kv_bytes_per_token
        self.layers = m.layers
        self.att_per_ctx = 4.0 * m.heads * m.head_dim * m.layers      # attention_flops(ctx, q) = att_per_ctx * ctx * q
        self.act_bytes = m.activation_roundtrip_bytes_per_token
        self.gpu_bw = sysspec.gpu_hbm_bw * sysspec.gpu_bw_eff
        self.gpu_comp = sysspec.gpu_compute_flops * sysspec.gpu_compute_eff
        self.mem = sysspec.memories
        self.kappa = kappa
        self.budget = int(cfgv("token_budget_per_iteration"))
        self.chunk = int(cfgv("prefill_chunk"))
        self.max_seqs = int(cfgv("max_num_seqs"))
        hbm = self.mem["hbm"]
        self.hbm_w = min(hbm.ext_bw, hbm.write_bw)

    # -- iteration ---------------------------------------------------------------------------------------------
    def nonattn(self, n_tok):
        return self.s.gpu_non_attention_decode_s(max(1, n_tok))

    def decode_att(self, tier, count, ctx_sum):
        """Attention time of `count` decode sequences (total context `ctx_sum` tokens) resident in `tier`."""
        if count <= 0:
            return 0.0, 0.0
        kv = self.kvb * ctx_sum
        flops = self.att_per_ctx * ctx_sum
        if tier == "hbm":
            return max(kv / self.gpu_bw, flops / self.gpu_comp), 0.0           # (gpu, offload)
        m = self.mem[tier]
        if tier == "hbf":                                                      # A12: GPU-direct read
            return max(kv / (m.ext_bw * self.s.gpu_bw_eff), flops / self.gpu_comp) + self.layers * m.latency_s, 0.0
        if m.attention_capable:                                                # A13: DP1 offloaded attention
            mem_bw = kv / (m.int_bw * max(0.3, m.attn_bw_eff))
            comp = flops / max(1.0, float(m.compute_flops))
            xfer = self.act_bytes * count / max(1.0, m.ext_bw)
            return 0.0, max(mem_bw, comp) + xfer + self.layers * m.latency_s
        raise ValueError(f"tier {tier} cannot host decode attention")

    def prefill_att(self, ctx, c, hist_tier="hbm", hist_tokens=0):
        comp = self.att_per_ctx * ctx * c / self.gpu_comp
        if hist_tier == "hbf" and hist_tokens > 0:
            m = self.mem["hbf"]
            return max(comp, self.kvb * hist_tokens / (m.ext_bw * self.s.gpu_bw_eff))
        return comp

    def iter_time(self, groups, pf):
        """groups: {tier: (count, ctx_sum)}; pf: iterable of (c_tokens, ctx, hist_tier, hist_tokens)."""
        n_dec = 0
        gpu_att = 0.0
        off = 0.0
        for tier, (cnt, cs) in groups.items():
            n_dec += cnt
            g, o = self.decode_att(tier, cnt, cs)
            gpu_att += g
            off = max(off, o)
        c_tot = 0
        for (c, ctx, ht, htok) in pf:
            c_tot += c
            gpu_att += self.prefill_att(ctx, c, ht, htok)
        if n_dec + c_tot == 0:
            return 0.0
        return self.kappa * (self.nonattn(n_dec + c_tot) + max(gpu_att, off))

    # -- single-path helpers (closed form, used by estimator and tests) -----------------------------------------
    def decode_step(self, tier, ctx, batch=1):
        return self.iter_time({tier: (batch, ctx * batch)}, ())

    def prefill_time_alone(self, q, ctx_start, hist_tier="hbm"):
        """Chunked prefill of q tokens on an otherwise idle node (no decode)."""
        t, done = 0.0, 0
        while done < q:
            c = min(self.chunk, q - done, self.budget)
            t += self.iter_time({}, [(c, ctx_start + q, hist_tier, ctx_start)])   # ctx = full context, as DP1 attention_flops(ctx, q)
            done += c
        return t
