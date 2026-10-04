"""DP2 simulator tests (m0-spec section 8). Run: python -m unittest test_sim -v   (from this directory)"""
import json
import math
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from dp2sim.engine import BASELINE, C1, C2, DLOCAL, ORACLE, Sim  # noqa: E402
from dp2sim.net import FlowNet  # noqa: E402
from dp2sim.physics import Phys, system  # noqa: E402
from dp2sim.scenarios import SCENARIOS, check_against_json  # noqa: E402

REF = json.loads((Path(__file__).resolve().parent / "m0_reference_values.json").read_text())["systems"]


def run(scn, cand, load, sysid="SYS-H100", seed=11, opts=None):
    return Sim(sysid, SCENARIOS[scn], seed, cand, load, opts).run()


class Physics(unittest.TestCase):
    def test_single_path_reference_values(self):
        for sid in ("SYS-H100", "SYS-B200"):
            P = Phys(system(sid))
            r = REF[sid]["decode_step_s"]
            for ctx in (65536, 131072, 200000):
                for tier in ("hbm", "custom_hbm", "cxl_pnm", "hbf"):
                    self.assertAlmostEqual(P.decode_step(tier, ctx), r[f"ctx_{ctx}"][tier], places=9)
            s = system(sid)
            for q, h in ((8192, 0), (16384, 0), (512, 32768)):
                self.assertAlmostEqual(P.prefill_time_alone(q, h), s.prefill_s(h + q, q), places=9)   # identical to DP1 prefill_s

    def test_scenarios_match_json(self):
        self.assertTrue(check_against_json())


class Net(unittest.TestCase):
    def test_max_min_fair_and_conservation(self):
        n = FlowNet({"a": 100.0, "b": 60.0})
        done = []
        f1 = n.add(1000, ["a"], lambda: done.append(1))
        f2 = n.add(1000, ["a", "b"], lambda: done.append(2))
        n.recompute()
        self.assertAlmostEqual(f2.rate, 50.0 if 60.0 / 1 >= 50 else 60.0)       # a shared: 50/50 (b allows 60)
        self.assertAlmostEqual(f1.rate, 50.0)
        n.set_scale("a", 0.5)
        n.recompute()
        self.assertAlmostEqual(f1.rate + f2.rate, 50.0)                          # capacity of a halved

    def test_single_flow_rate_is_bottleneck(self):
        n = FlowNet({"a": 100.0, "b": 10.0})
        f = n.add(100, ["a", "b"], lambda: None)
        n.recompute()
        self.assertAlmostEqual(f.rate, 10.0)


class Engine(unittest.TestCase):
    def test_single_request_ttft_and_tpot(self):
        for sid in ("SYS-H100", "SYS-B200"):
            r = run("cb_kv_8k_b32", BASELINE, 1.0, sid, opts={"horizon": 60.0, "min_turns": 5, "max_horizon": 120.0})
            P = Phys(system(sid))
            self.assertAlmostEqual(r["qa"]["ttft_p50_s"], P.prefill_time_alone(8192, 0), delta=2e-4)
            self.assertAlmostEqual(r["qa"]["tpot_p50_s"], P.decode_step("hbm", 8192 + 128), delta=3e-4)

    def test_deterministic(self):
        a = run("dp2_turn_hbm_small_tool", C1, 12.0, opts={"horizon": 60.0, "min_turns": 50, "max_horizon": 120.0})
        b = run("dp2_turn_hbm_small_tool", C1, 12.0, opts={"horizon": 60.0, "min_turns": 50, "max_horizon": 120.0})
        self.assertEqual(json.dumps(a, sort_keys=True, default=float), json.dumps(b, sort_keys=True, default=float))

    def test_planner_down_equals_baseline(self):
        o = {"horizon": 80.0, "min_turns": 50, "max_horizon": 160.0}
        base = run("dp2_turn_dram_small_tool", BASELINE, 6.0, opts=o)
        s = Sim("SYS-H100", SCENARIOS["dp2_turn_dram_small_tool"], 11, C1, 6.0, o)
        s.fault = True                                                  # planner down for the whole run -> fallback rule
        r = s.run()
        for k in ("ttft_p50_s", "ttft_p99_s", "tpot_p50_s", "goodput_tok_s"):
            self.assertAlmostEqual(r["qa"][k], base["qa"][k], places=9)

    def test_c2_equals_c1_without_decision_cost_and_staleness(self):
        o = {"horizon": 80.0, "min_turns": 50, "max_horizon": 160.0, "t_ref": 0.0, "tel": 1e-3, "c_val": 0.0}
        a = run("dp2_turn_dram_small_tool", C1, 6.0, opts=o)
        b = run("dp2_turn_dram_small_tool", C2, 6.0, opts=o)
        for k in ("ttft_p50_s", "ttft_p99_s", "tpot_p50_s", "tpot_p99_s", "goodput_tok_s"):
            self.assertAlmostEqual(a["qa"][k], b["qa"][k], delta=1e-6 + 1e-6 * abs(a["qa"][k]))

    def test_no_capacity_violation(self):
        s = Sim("SYS-H100", SCENARIOS["cb_kv_8k_b32"], 11, C1, 32.0, {"horizon": 80.0, "min_turns": 10, "max_horizon": 120.0})
        s.run()
        for (n, t), occ in s.kv.occ.items():
            self.assertGreaterEqual(s.kv.pool[(n, t)] * 1.0001, occ - 1.0, (n, t))   # never above pool (targets are below 1.0)

    def test_link_bandwidth_monotonic(self):
        o = {"horizon": 80.0, "min_turns": 50, "max_horizon": 160.0}
        lo = run("dp2_turn_hbm_small_tool", BASELINE, 12.0, opts=dict(o, link="rdma_100g"))
        hi = run("dp2_turn_hbm_small_tool", BASELINE, 12.0, opts=dict(o, link="rdma_400g_8rail"))
        self.assertGreater(lo["qa"]["ttft_p50_s"], hi["qa"]["ttft_p50_s"])

    def test_d_local_moves_no_internode_bytes(self):
        r = run("dp2_turn_hbm_small_tool", DLOCAL, 12.0, opts={"horizon": 80.0, "min_turns": 50, "max_horizon": 160.0})
        self.assertEqual(r["transfers"]["internode_bytes"], 0.0)

    def test_oracle_has_zero_regret_and_decision_cost(self):
        r = run("dp2_turn_dram_small_tool", ORACLE, 6.0, opts={"horizon": 80.0, "min_turns": 50, "max_horizon": 160.0})
        self.assertEqual(r["planner"]["t_dec_mean_s"], 0.0)


if __name__ == "__main__":
    unittest.main()
