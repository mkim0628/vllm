"""Reuse of the DP1 physics (read-only). DP1/sim/model.py is imported, never copied or modified (H10)."""
from __future__ import annotations

import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
DP1_SIM = HERE.parent.parent / "DP1" / "sim"
DP1_CONFIGS = DP1_SIM / "configs"
if str(DP1_SIM) not in sys.path:
    sys.path.append(str(DP1_SIM))  # appended: DP4 module names (scenarios, simulator, ...) keep priority

import model as dp1_model  # noqa: E402  (DP1/sim/model.py)

SYSTEM_CLUSTER = {"SYS-H100": "h100_8gpu", "SYS-B200": "b200_8gpu"}
_CACHE = {}


def load_dp1_system(sys_id, model_name="llama_3_1_70b"):
    """SystemSpec of one 8-GPU node (TP=8), reused from DP1."""
    if (sys_id, model_name) not in _CACHE:
        _CACHE[(sys_id, model_name)] = dp1_model.load_system(DP1_CONFIGS, SYSTEM_CLUSTER[sys_id], model_name)
    return _CACHE[(sys_id, model_name)]
