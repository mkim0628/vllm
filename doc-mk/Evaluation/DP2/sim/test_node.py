"""Functional tests for the node-internal architecture-style candidates (not an evaluation; thresholds are invariants only)."""
import unittest

from dp2sim.engine import C1, DLOCAL, Sim
from dp2sim.nodeint import GIB, N_BASE, N_BBRD, N_DISP, NodeSim
from dp2sim.runner import load_cal
from dp2sim.scenarios import SCENARIOS
from dp2sim.scenarios_node import NODE_SCENARIOS

SHORT = dict(horizon=60.0, warmup=10.0, min_turns=50, max_horizon=120.0)


def run(cand, scn="n_cb_kv_8k_b32", load=8.0, seed=11, sysid="SYS-H100", **o):
    sc = NODE_SCENARIOS[scn]
    return NodeSim(sysid, sc, seed, cand, load, dict(SHORT, **o)).run()


class NodeTests(unittest.TestCase):
    def test_scenarios_built(self):
        self.assertEqual(len(NODE_SCENARIOS), 16)
        for sc in NODE_SCENARIOS.values():
            self.assertEqual(sc.nP, 0)
            self.assertGreaterEqual(sc.nD, 1)

    def test_baseline_equals_dlocal_when_history_not_in_hbf(self):
        # D-local-always decodes at the History tier when it is HBM/HBF; Baseline-GPU-local always decodes in HBM -> identical unless HBF
        for scn, load in (("n_cb_kv_8k_b32", 8.0), ("n_dp2_turn_dram_small_tool", 6.0)):
            sc = NODE_SCENARIOS[scn]
            a = NodeSim("SYS-H100", sc, 11, N_BASE, load, SHORT).run()["qa"]
            b = Sim("SYS-H100", sc, 11, DLOCAL, load, SHORT).run()["qa"]
            for k in ("goodput_tok_s", "ttft_p99_s", "tpot_p99_s", "useful_utilization"):
                self.assertAlmostEqual(a[k], b[k], places=9, msg=(scn, k))

    def test_baseline_decodes_in_hbm(self):
        r = NodeSim("SYS-H100", NODE_SCENARIOS["n_dp2_turn_hbf_hist"], 11, N_BASE, 2.0, SHORT).run()
        self.assertEqual({k for k, v in r["arch"]["tiers"].items() if v}, {"hbm"})

    def test_existing_candidate_unchanged(self):
        from dp2sim.physics import DECODE_TIERS
        if "cxl_pnm2" in DECODE_TIERS:       # QA4 S1 working copy: a new decode tier legitimately changes the planner's choices
            self.skipTest("new tier present")
        sc = SCENARIOS["dp2_turn_dram_small_tool"]
        r = Sim("SYS-H100", sc, 11, C1, 12.0, None).run()
        self.assertAlmostEqual(r["qa"]["goodput_tok_s"], 234.9163, places=3)

    def test_occupancy_bounds(self):
        r = run(N_BASE)
        h = r["hbm"]
        self.assertGreater(h["avg_gib"], 0.0)
        self.assertLessEqual(h["avg_frac"], 1.5)
        self.assertGreaterEqual(h["peak_frac"], h["avg_frac"] - 1e-9)

    def test_candidates_complete(self):
        for cand in (N_DISP, N_BBRD):
            r = run(cand)
            self.assertGreater(r["requests"]["served"], 0, cand)
            self.assertGreater(sum(r["arch"]["tiers"].values()), 0, cand)

    def test_fault_falls_back(self):
        lam0 = 0.05
        for cand in (N_DISP, N_BBRD):
            r = NodeSim("SYS-H100", NODE_SCENARIOS["n_dp2_planner_fault_fallback"], 11, cand, 1.0,
                        dict(SHORT, lam0=lam0, horizon=300.0, max_horizon=320.0, min_turns=1)).run()
            self.assertGreater(r["planner"]["fallbacks"], 0, cand)

    def test_lambda_zero_has_no_price(self):
        sim = NodeSim("SYS-H100", NODE_SCENARIOS["n_cb_kv_8k_b32"], 11, N_DISP, 8.0, dict(SHORT, lam_hbm=0.0))
        self.assertIsNone(sim.est.price_fn)


if __name__ == "__main__":
    unittest.main()
