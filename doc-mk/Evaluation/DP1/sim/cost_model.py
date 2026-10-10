"""Relative memory cost weights for the resource-efficiency QA (QA3 v5, owner decision 2026-10-03).

cost-weighted occupancy = sum_m  w_m * (average occupied GiB in tier m)   [unit: DRAM-GiB-equivalent in use]
resource efficiency     = SLO goodput (tok/s) / cost-weighted occupancy

Migration only moves bytes between tiers, so the plain sum of occupancy is identical for every candidate; the weights make
the *distribution* across tiers visible (moving a byte into an expensive tier costs more). Weights are RELATIVE $/GiB
(DRAM = 1) and ASSUMED from public price ranges (server DDR5 ~ a few $/GB; HBM3e several times that; NAND ~ 1/50 of DRAM).
Replace with real quotes when available; the star must be reported together with the scheme sensitivity below.
"""
from __future__ import annotations

PROVENANCE = "ASSUMED relative $/GiB (DRAM = 1) from public price ranges; not vendor quotes"

SCHEMES: dict[str, dict[str, float]] = {
    "registered": {"hbm": 5.0, "custom_hbm": 5.0, "cxl_pnm": 1.2, "dram": 1.0, "hbf": 0.3, "ssd_pim": 0.05},
    "hbm_3x": {"hbm": 3.0, "custom_hbm": 3.0, "cxl_pnm": 1.2, "dram": 1.0, "hbf": 0.3, "ssd_pim": 0.05},
    "hbm_10x": {"hbm": 10.0, "custom_hbm": 10.0, "cxl_pnm": 1.2, "dram": 1.0, "hbf": 0.3, "ssd_pim": 0.05},
}
REGISTERED = "registered"


def cost_occupancy(tier_occ_gib: dict[str, float], scheme: str = REGISTERED) -> float:
    w = SCHEMES[scheme]
    return sum(w.get(name, 1.0) * gib for name, gib in tier_occ_gib.items())
