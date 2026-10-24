"""DP2 M0 check: reproduces the reference values used in m0-spec.md from the DP1 physical model (read-only import).

    python m0_check.py            # print tables, write m0_reference_values.json
    python m0_check.py --verify   # also fail if the written JSON differs from a fresh computation

Nothing here is a simulation result. Values are closed-form single-path numbers from DP1 `model.py` + configs
(Evidence: SPEC/PUBLIC/ASSUMED per field in configs/dp2_params.json) and the DP2-new formulas defined in m0-spec.md.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
DP1_SIM = HERE.parent.parent / "DP1" / "sim"
sys.path.insert(0, str(DP1_SIM))
from model import load_profile  # noqa: E402  (DP1, read-only)

PARAMS = json.loads((HERE / "configs" / "dp2_params.json").read_text())
LINK = json.loads((HERE / "configs" / "internode_links.json").read_text())
SYSTEMS = ("SYS-H100", "SYS-B200")
TIERS = ("hbm", "custom_hbm", "cxl_pnm", "dram", "hbf", "ssd_pim")
GIB = 2**30


def p(key):
    return PARAMS["params"][key]["value"]


def gpu_direct_attention_s(system, mem, context, batch=1):
    """DP2-new (A12): decode attention on the GPU reading KV from a GPU-reachable non-HBM tier (HBF)."""
    kv = system.model.kv_bytes_per_token * context * batch
    bw = kv / (mem.ext_bw * system.gpu_bw_eff)
    comp = system.model.attention_flops(context, 1) * batch / (system.gpu_compute_flops * system.gpu_compute_eff)
    return max(bw, comp) + system.model.layers * mem.latency_s


def decode_step_s(system, tier, context, batch=1):
    """DP2 decode step time for KV resident in `tier` (None if the tier cannot host decode directly)."""
    mem = system.memories[tier]
    if tier == "hbm":
        return system.decode_step_s(context, batch, "hbm")
    if mem.attention_capable:                       # custom_hbm (ScHBM), cxl_pnm: DP1 offloaded attention, unchanged (A13)
        return system.decode_step_s(context, batch, tier)
    if mem.gpu_reachable:                           # hbf: GPU-direct read (A12)
        return system.gpu_non_attention_decode_s(batch) + gpu_direct_attention_s(system, mem, context, batch)
    return None                                     # dram, ssd_pim: blocking swap-in to HBM first (A14)


def hbm_write_bw(system):
    m = system.memories["hbm"]
    return min(m.ext_bw, m.write_bw)


def tier_to_hbm_s(system, tier, nbytes):
    """Intra-node promotion tier -> HBM (A11): pipelined, bottleneck min(tier ext BW, HBM write BW) + tier latency."""
    m = system.memories[tier]
    return nbytes / min(m.ext_bw, hbm_write_bw(system)) + m.latency_s


def tier_to_remote_hbm_s(system, tier, nbytes, link_gbps):
    """Inter-node tier -> remote HBM (A05): bottleneck min(tier ext BW, NIC egress, NIC ingress, HBM write) + link latency."""
    m = system.memories[tier]
    bw = min(m.ext_bw, link_gbps * 1e9, hbm_write_bw(system))
    return nbytes / bw + LINK["profiles"]["rdma_400g_1rail"]["base_latency_s"] + m.latency_s


def compute():
    out = {"_note": "closed-form single-path reference values; not simulation results",
           "_dp1_configs_rev": subprocess.run(["git", "log", "-1", "--format=%h", "--", str(DP1_SIM / "configs")],
                                              capture_output=True, text=True, cwd=HERE).stdout.strip(),
           "systems": {}}
    link_default = LINK["profiles"]["rdma_400g_1rail"]["bw_bytes_per_s"] / 1e9
    for sid in SYSTEMS:
        s = load_profile(DP1_SIM / "configs", sid)[0]
        m = s.model
        kvb = m.kv_bytes_per_token
        weights = m.active_params * m.dtype_bytes
        r = {"kv_bytes_per_token": kvb, "weights_bytes": weights,
             "hbm_kv_pool_gib_full": s.memories["hbm"].capacity_bytes / GIB,
             "cb_hbm_pool_gib": {"cb1_x0.12": 0.12 * s.memories["hbm"].capacity_bytes / GIB,
                                 "cb2_x0.20": 0.20 * s.memories["hbm"].capacity_bytes / GIB},
             "prefill_s": {"8k_single_turn(ctx8192,q8192)": s.prefill_s(8192),
                           "tool512_on_hist32k": s.prefill_s(32768 + 512, 512),
                           "tool512_on_hist64k": s.prefill_s(65536 + 512, 512),
                           "tool2k_on_hist128k": s.prefill_s(131072 + 2048, 2048),
                           "tool16k_on_hist16k": s.prefill_s(16384 + 16384, 16384),
                           "tool2k_on_hist256k": s.prefill_s(262144 + 2048, 2048),
                           "single_turn_12k": s.prefill_s(12288), "single_turn_16k": s.prefill_s(16384),
                           "single_turn_32k_infeasible_check": s.prefill_s(32768)},
             "history_move_s": {}, "decode_step_s": {}, "decode_kv_read_idealized_s": {}}
        for hist_tokens in (32768, 65536, 131072):
            nbytes = hist_tokens * kvb
            row = {}
            for tier in TIERS:
                if tier == "hbm":
                    row[tier] = {"d_local": 0.0, "p_path": tier_to_remote_hbm_s(s, tier, nbytes, link_default)}
                elif s.memories[tier].gpu_reachable:     # hbf: read in place by the GPU, no promotion
                    row[tier] = {"d_local": 0.0, "p_path": tier_to_remote_hbm_s(s, tier, nbytes, link_default),
                                 "d_local_read_overlap_s": nbytes / (s.memories[tier].ext_bw * s.gpu_bw_eff)}
                else:
                    row[tier] = {"d_local": tier_to_hbm_s(s, tier, nbytes),
                                 "p_path": tier_to_remote_hbm_s(s, tier, nbytes, link_default)}
            r["history_move_s"][f"hist_{hist_tokens // 1024}k"] = row
        for ctx in (65536, 131072, 200000):
            r["decode_step_s"][f"ctx_{ctx}"] = {t: decode_step_s(s, t, ctx) for t in TIERS}
            kvctx = ctx * kvb
            ide = {}
            for t in TIERS:
                mem = s.memories[t]
                bw = {"hbm": mem.ext_bw, "custom_hbm": mem.int_bw, "cxl_pnm": mem.int_bw}.get(t, mem.ext_bw)
                ide[t] = kvctx / bw
            r["decode_kv_read_idealized_s"][f"ctx_{ctx}"] = ide
            r.setdefault("blocking_swap_in_s", {})[f"ctx_{ctx}"] = {
                t: (kvctx / min(s.memories[t].ext_bw, hbm_write_bw(s)) + s.memories[t].latency_s) for t in ("dram", "ssd_pim")}
        def max_ctx(tier, slo=0.050, batch=1):
            lo, hi = 1024, 4_000_000
            f = lambda c: decode_step_s(s, tier, c, batch)
            if f(lo) is None or f(lo) > slo:
                return 0
            while hi - lo > 256:
                mid = (lo + hi) // 2
                (lo, hi) = (mid, hi) if f(mid) <= slo else (lo, mid)
            return lo
        r["max_context_tokens_for_tpot_slo_batch1"] = {t: max_ctx(t) for t in ("hbm", "custom_hbm", "cxl_pnm", "hbf")}
        out["systems"][sid] = r
    return out


def main():
    res = compute()
    path = HERE / "m0_reference_values.json"
    text = json.dumps(res, indent=1, sort_keys=True, default=float) + "\n"
    if "--verify" in sys.argv:
        assert path.exists() and path.read_text() == text, "m0_reference_values.json is stale; run m0_check.py"
        import re
        names = {x["name"] for x in json.loads((HERE / "configs" / "scenario_params.json").read_text())["scenarios"]}
        bench = set(re.findall(r"`((?:cb_|dp2_|dyn_)[a-z0-9_]+)`", (HERE.parent / "benchmark.md").read_text()))
        assert names == bench, (sorted(names ^ bench))
        json.loads((HERE / "configs" / "result_schema.json").read_text())
        print("verify OK: reference values current, scenario names match benchmark.md, schema loads")
        return
    path.write_text(text)
    for sid, r in res["systems"].items():
        print(f"== {sid}  kv/token={r['kv_bytes_per_token']}  weights={r['weights_bytes']/1e9:.1f} GB  "
              f"HBM={r['hbm_kv_pool_gib_full']:.0f} GiB")
        for k, v in r["history_move_s"].items():
            print(" ", k, {t: (round(x['d_local'], 3), round(x['p_path'], 3)) for t, x in v.items()})
        for k, v in r["decode_step_s"].items():
            print(" ", k, {t: (None if x is None else round(x * 1e3, 1)) for t, x in v.items()}, "ms")
    print("wrote", path)


if __name__ == "__main__":
    main()
