"""Run helpers: single runs, Baseline-only calibration/controls, sweeps (multiprocessing)."""
from __future__ import annotations

import json
import math
import statistics
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

from .engine import BASELINE, Sim
from .scenarios import SCENARIOS

SIM = Path(__file__).resolve().parent.parent
CAL = SIM / "configs" / "calibration.json"
SEEDS = (11, 23, 37, 53, 71)
LAM_GRID = tuple(0.02 * (1.35 ** k) for k in range(0, 24))


def run_one(a):
    sysid, scn, cand, seed, load, opts = a
    return Sim(sysid, SCENARIOS[scn], seed, cand, load, opts).run()


def load_cal():
    return json.loads(CAL.read_text()) if CAL.exists() else {}


def lam0_for(sysid, scn, cal=None):
    cal = cal if cal is not None else load_cal()
    return cal.get(f"{sysid}|{scn}", {}).get("lam0")


def calibrate(sysid, scn, seed=11, pool=None):
    """lambda_sat = Baseline goodput peak over an ascending lambda sweep; lambda0 = 0.6 * lambda_sat (A21).
    Stops once goodput falls below 30% of the peak (overload); calibration runs use max_horizon 400 s."""
    curve, gmax = [], 0.0
    for lam in LAM_GRID:
        r = run_one((sysid, scn, BASELINE, seed, 1.0, {"lam0": lam, "max_horizon": 400.0}))
        g = r["qa"]["goodput_tok_s"]
        curve.append((lam, g, r["qa"]["ttft_p99_s"], r["qa"]["tpot_p99_s"]))
        gmax = max(gmax, g)
        if gmax > 0 and g < 0.3 * gmax:
            break
    lam_sat = None
    for lam, g, _, _ in curve:
        if g >= 0.98 * gmax:
            lam_sat = lam
            break
    return dict(lam_sat=lam_sat, lam0=0.6 * lam_sat if lam_sat else None, gmax=gmax, curve=curve)


def _cal_job(a):
    return a, calibrate(*a)
