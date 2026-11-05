"""Node-internal DP2 scenarios (arch-styles-plan.md 3): the existing DP2 scenarios without the inter-node (P/D pool, link) ones, on
unified nodes (no P nodes; each node does Prefill + Decode). Node counts = the original D-node counts; load grids are frozen after
the Baseline-only control (results/iterations/loop-log.md 3.2)."""
from __future__ import annotations

import json
from dataclasses import replace

from .scenarios import CFGDIR, SCENARIOS

NODES = {
    "cb_kv_8k_b32": 1, "cb_kv_8k_b32_ramp": 1, "cb_mixed_8k_b32": 1,
    "dp2_turn_hbm_small_tool": 2, "dp2_turn_dram_small_tool": 2, "dp2_turn_hbf_hist": 2, "dp2_turn_ssd_hist": 2,
    "dp2_tool_large_result": 2, "dp2_decode_heavy_p_idle": 2, "dp2_long_ctx_decode_offload": 2, "dp2_session_size_skew": 4,
    "dp2_stale_telemetry": 2, "dp2_planner_fault_fallback": 2,
    "dyn_turn_demotion_wave": 2, "dyn_load_ramp_burst": 2, "dyn_decode_phase_shift": 2,
}
EXCLUDED = ("dp2_prefill_burst_p_saturated", "dp2_internode_link_contention", "dyn_p_node_degrade")
GRIDS_FILE = CFGDIR / "grids_node.json"        # frozen after the Baseline-only control


def build_node():
    grids = json.loads(GRIDS_FILE.read_text()) if GRIDS_FILE.exists() else {}
    S = {}
    for name, n in NODES.items():
        sc = SCENARIOS[name]
        g = tuple(grids.get(name, sc.grid))
        S["n_" + name] = replace(sc, name="n_" + name, nP=0, nD=n, grid=g, note=(sc.note + " [node-internal, unified nodes]").strip())
    return S


NODE_SCENARIOS = build_node()
