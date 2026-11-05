"""Sanity tests for the DP3 simulator (must pass before any evaluation run).   python test_dp3sim.py"""
import math
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import dp3sim as D  # noqa: E402
import dp3_scenarios as SC  # noqa: E402

SYS = D.load_system("SYS-H100")
SC1 = SC.BY_ID["ST-02"]


def same(a, b, tol=1e-9):
    return all(abs(a[k] - b[k]) <= tol * max(1.0, abs(a[k])) for k in ("ttft_p50", "ttft_p99", "tpot_p50", "tpot_p99", "hbm_gib"))


def test_identity_policies_equal_baseline():
    """offline with r=1, rho=0 and online with r=1, rho=0 must not beat/lose to baseline except online's scoring cost."""
    base = D.summarize(D.run(SC1, SYS, D.BASELINE, 11, 0.6))
    off = D.summarize(D.run(SC1, SYS, D.Policy("c1id", "offline", 1.0, 0.0), 11, 0.6))
    assert same(base, off), (base, off)


def test_deterministic():
    a = D.summarize(D.run(SC1, SYS, D.C1, 23, 0.6))
    b = D.summarize(D.run(SC1, SYS, D.C1, 23, 0.6))
    assert same(a, b)


def test_footprint_decreases_with_keep_ratio():
    f = [D.summarize(D.run(SC1, SYS, D.Policy("c", "offline", r, 0.15), 11, 0.6))["hbm_gib"] for r in (1.0, 0.5, 0.3, 0.1)]
    assert all(x > y for x, y in zip(f, f[1:])), f


def test_online_scoring_adds_ttft_vs_offline_same_ratio():
    on = D.summarize(D.run(SC1, SYS, D.C2, 11, 0.3))
    off = D.summarize(D.run(SC1, SYS, D.C1, 11, 0.3))
    assert on["ttft_p50"] > off["ttft_p50"]


def test_slower_tier_slower_ttft():
    fast = SC.BY_ID["ST-03"]
    slow = SC.BY_ID["ST-05"]
    a = D.summarize(D.run(fast, SYS, D.BASELINE, 11, 0.2))["ttft_p99"]
    b = D.summarize(D.run(slow, SYS, D.BASELINE, 11, 0.2))["ttft_p99"]
    assert b > a


def test_all_requests_complete_at_low_load():
    for pol in (D.BASELINE, D.C1, D.C2):
        s = D.summarize(D.run(SC1, SYS, pol, 11, 0.05))
        assert s["unfinished"] == 0, (pol.name, s)


def test_b200_not_slower_than_h100():
    b = D.load_system("SYS-B200")
    a = D.summarize(D.run(SC1, SYS, D.BASELINE, 11, 0.3))
    c = D.summarize(D.run(SC1, b, D.BASELINE, 11, 0.3))
    assert c["tpot_p50"] <= a["tpot_p50"] and c["ttft_p50"] <= a["ttft_p50"] + 1e-9


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for f in fns:
        f()
        print("ok", f.__name__)
    print(len(fns), "tests passed")
