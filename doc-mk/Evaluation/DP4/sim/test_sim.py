"""DP4 simulator tests (stdlib unittest):  uv run --no-project python -m unittest test_sim -v"""
from __future__ import annotations

import json
import math
import unittest
from types import SimpleNamespace
from unittest import mock

import dp1_bridge
import params as params_mod
import qa_eval as q
import scenarios as sc
import simulator as sm
from arms import ABLATION_NAMES, ARM_CLASSES, BASE, C1, C2, C1_NOBATCH, C2_NOSCAN, C1Central

SYS = dp1_bridge.load_dp1_system("SYS-H100")
P = params_mod.load_params().with_overrides(n_req_base=400)
CB1 = sc.common_benchmark()[0].resolved()
TWO = sc.dp4_benchmark()[1].resolved()  # d4_hot_prefix_fanout (n_p=n_d=2)


def run(knobs, arm, seed=11, load=1.0, p=P, **kw):
    return sm.run_sim(SYS, p, knobs, arm, seed, load, **kw)


class ConfigTest(unittest.TestCase):
    def test_config_matches_dataclass_and_has_provenance(self):
        raw = params_mod.load_raw()
        for k, v in raw.items():
            self.assertIn("value", v, k)
            self.assertIn("range", v, k)
            self.assertIn(v["provenance"], params_mod.PROVENANCE_OK, k)
        params_mod.load_params()  # raises on mismatch

    def test_spec_table_values(self):
        raw = params_mod.load_raw()
        self.assertEqual(raw["rpc_rtt_us"]["value"], 2.11)
        self.assertEqual(raw["server_thread_mops"]["value"], 12.13)
        self.assertEqual(raw["eta_rdma"]["value"], 0.85)
        self.assertEqual(raw["eta_rdma"]["provenance"], "ASSUMED")
        self.assertEqual(raw["lock_stripes"]["range"], [1, 8, 64, 512])
        self.assertEqual(raw["probe_us"]["value"], 0.35)
        self.assertEqual(raw["lease_s"]["provenance"], "ASSUMED")  # not found in the paper -> never PAPER

    def test_derived_bandwidth(self):
        self.assertAlmostEqual(P.cxl_node_bw, 2 * 63e9 * 0.5)
        self.assertAlmostEqual(P.rdma_node_bw, 100e9 * 0.85)

    def test_dp1_physics_is_reused(self):
        self.assertEqual(type(SYS).__module__, "model")
        self.assertGreater(SYS.prefill_s(8192), 0.1)
        self.assertAlmostEqual(SYS.model.kv_bytes_per_token, 327680)


class ScenarioTest(unittest.TestCase):
    def test_names_exact(self):
        names = {r[0] for s in sc.dp4_benchmark() for r in s.rows()}
        for n in ["d4_agent_multiturn", "d4_hot_prefix_fanout", "d4_small_prompt_highqps", "d4_node_scale_n4", "d4_node_scale_n8",
                  "d4_node_scale_n16", "d4_block16", "d4_block256", "d4_pool_full_eviction", "d4_lock_stripes_1", "d4_lock_stripes_8",
                  "d4_lock_stripes_512", "d4_server_threads_2", "d4_server_threads_4", "d4_fail_server[restart]",
                  "d4_fail_lockholder[as_published]", "d4_fail_lockholder[lease]"]:
            self.assertIn(n, names)
        self.assertEqual([s.name for s in sc.common_benchmark()], ["cb_kv_8k_b32", "cb_kv_8k_b32_ramp", "cb_mixed_8k_b32"])

    def test_brief_and_exposes(self):
        for s in sc.common_benchmark() + sc.dp4_benchmark():
            self.assertLessEqual(len(s.brief), 60)
            self.assertTrue(s.exposes)


class TraceTest(unittest.TestCase):
    def test_deterministic(self):
        a, Ha, _ = sm.make_trace(SYS, P, CB1, 11, 1.0)
        b, Hb, _ = sm.make_trace(SYS, P, CB1, 11, 1.0)
        self.assertEqual([(r.t, r.L, r.u) for r in a], [(r.t, r.L, r.u) for r in b])
        c, _, _ = sm.make_trace(SYS, P, CB1, 23, 1.0)
        self.assertNotEqual([r.t for r in a], [r.t for r in c])

    def test_same_trace_for_all_arms(self):
        sims = [sm.Sim(SYS, P, TWO, a, 11, 1.0) for a in (BASE, C1, C2)]
        sig = [[(r.t, r.L, r.out, r.hot, r.u) for r in s.reqs] for s in sims]
        self.assertEqual(sig[0], sig[1])
        self.assertEqual(sig[1], sig[2])

    def test_load_is_time_scaling(self):
        a, _, _ = sm.make_trace(SYS, P, CB1, 11, 1.0)
        b, _, _ = sm.make_trace(SYS, P, CB1, 11, 2.0)
        for x, y in zip(a[:50], b[:50]):
            self.assertAlmostEqual(x.t, 2 * y.t, places=9)

    def test_base_rate_is_06_of_p_saturation(self):
        self.assertAlmostEqual(sm.base_rate(SYS, P, CB1), 0.6 / SYS.prefill_s(8192))
        two = dict(CB1, n_p=2)
        self.assertAlmostEqual(sm.base_rate(SYS, P, two), 2 * sm.base_rate(SYS, P, CB1))

    def test_multiturn_trace_has_history(self):
        kn = sc.dp4_benchmark()[0].resolved()
        reqs, _, _ = sm.make_trace(SYS, P, kn, 11, 1.0)
        self.assertTrue(any(r.H > 0 for r in reqs))
        self.assertTrue(all(r.L > r.H for r in reqs))


class DeterminismTest(unittest.TestCase):
    def test_same_seed_same_result(self):
        a = run(CB1, C2)
        b = run(CB1, C2)
        self.assertEqual(json.dumps(a, sort_keys=True), json.dumps(b, sort_keys=True))

    def test_c1_c2_data_plane_identical_without_control_plane(self):
        for kn in (CB1, TWO):
            a = run(kn, C1, zero_cp=True)
            b = run(kn, C2, zero_cp=True)
            for k in ("goodput_tps", "ttft_p50_ms", "ttft_p99_ms", "tpot_p99_ms", "kv_resident_gib", "link_util_egress", "pool_util"):
                self.assertEqual(a[k], b[k], k)

    def test_baseline_has_no_pool(self):
        r = run(CB1, BASE)
        self.assertEqual(r["pool_util"], 0.0)
        self.assertEqual(r["resid_gib"]["pool"], 0.0)
        self.assertGreater(run(CB1, C1)["resid_gib"]["pool"], 0.0)


class ConservationTest(unittest.TestCase):
    def check(self, s):
        s.run()
        n = len(s.reqs)
        done = sum(1 for r in s.reqs if r.t_done is not None and not r.dead)
        dead = sum(1 for r in s.reqs if r.dead)
        inc = sum(1 for r in s.reqs if r.t_done is None and not r.dead)
        self.assertEqual(n, done + dead + inc)
        return done, dead, inc

    def test_arrivals_equal_completions_plus_open(self):
        for arm in (BASE, C1, C2):
            done, dead, inc = self.check(sm.Sim(SYS, P, TWO, arm, 11, 1.0))
            self.assertEqual((dead, inc), (0, 0))

    def test_causality_and_littles_law(self):
        s = sm.Sim(SYS, P, TWO, C2, 11, 1.0)
        s.run()
        for r in s.reqs:
            self.assertLessEqual(r.t, r.t_pf_start + 1e-12)
            self.assertLessEqual(r.t_pf_start, r.t_pf_end)
            self.assertLessEqual(r.t_pf_end, r.t_flow_end + 1e-12)
            self.assertLessEqual(r.t_flow_end, r.t_admit + 1e-12)
            self.assertLessEqual(r.t_admit, r.t_first + 1e-12)
            self.assertLessEqual(r.t_first, r.t_done + 1e-9)
        # Little: time-average number in system == lambda * mean sojourn over the whole drained run
        ev = sorted([(r.t, 1) for r in s.reqs] + [(r.t_done, -1) for r in s.reqs])
        area, cur, last = 0.0, 0, ev[0][0]
        for t, d in ev:
            area += cur * (t - last)
            cur += d
            last = t
        T = ev[-1][0] - ev[0][0]
        lam = len(s.reqs) / T
        W = sum(r.t_done - r.t for r in s.reqs) / len(s.reqs)
        self.assertAlmostEqual(area / T, lam * W, delta=1e-6 * lam * W)

    def test_overload_conserves_and_slo_fails(self):
        r = run(CB1, BASE, load=4.0)
        self.assertEqual(r["n_arrived"], r["n_total_done"] + r["n_total_failed"] + r["n_total_incomplete"])
        self.assertLess(r["goodput_tps"], run(CB1, BASE, load=1.0)["goodput_tps"] * 0.5)

    def test_served_tokens_match_completions(self):
        s = sm.Sim(SYS, P, CB1, BASE, 11, 0.5)
        r = s.run()
        coh = [x for x in s.reqs if s.w0 <= x.t < s.w1]
        self.assertEqual(r["served_tokens"], sum(x.out for x in coh if x.t_done is not None))


class LinkTest(unittest.TestCase):
    def test_baseline_pure_rdma_move_time(self):
        p = P.with_overrides(overlap_ratio=0.0)
        s = sm.Sim(SYS, p, dict(CB1, bg0=0.0, bg1=0.0), BASE, 11, 1.0)
        r = sm.Req(0, 1.0, 8192, 0, 256, 0, 0, True, False, (0.5,) * 6)
        s.reqs = [r]
        s.run()
        expect = 8192 * 327680 / (100e9 * 0.85)
        self.assertAlmostEqual(r.t_flow_end - r.t_pf_end, expect, delta=1e-9)

    def test_candidate_move_uses_cxl_rate(self):
        p = P.with_overrides(overlap_ratio=0.0)
        s = sm.Sim(SYS, p, dict(CB1, bg0=0.0, bg1=0.0), C1, 11, 1.0)
        r = sm.Req(0, 1.0, 8192, 0, 256, 0, 0, True, False, (0.5,) * 6)
        s.reqs = [r]
        s.run()
        by = 8192 * 327680
        expect = by / (2 * 63e9 * 0.5) + p.gpu_cxl_write_16KB_us * 1e-6
        self.assertAlmostEqual(r.t_flow_end - r.t_pf_end, expect, delta=1e-9)

    def test_link_fifo_and_background(self):
        lk = sm.Link(100.0, 0.0, 0.0, 1000.0, 0.0, 1000.0)
        self.assertEqual(lk.reserve(0.0, 100.0), (0.0, 1.0))
        self.assertEqual(lk.reserve(0.5, 100.0), (1.0, 2.0))  # FIFO
        busy = sm.Link(100.0, 0.5, 0.5, 1000.0, 0.0, 1000.0)
        self.assertAlmostEqual(busy.reserve(0.0, 100.0)[1], 2.0)  # half the bandwidth

    def test_move_time_grows_when_link_capacity_is_exceeded(self):
        lo = run(dict(CB1, bg0=0.0, bg1=0.0), C1, load=1.0)
        hi = run(dict(CB1, bg0=0.95, bg1=0.95), C1, load=1.0)
        self.assertGreater(hi["ttft_p50_ms"], lo["ttft_p50_ms"] * 1.5)
        self.assertGreater(hi["link_util_egress"], lo["link_util_egress"])


class ControlPlaneTest(unittest.TestCase):
    def cp(self, knobs, arm, rate, p=P, seed=11):
        return sm.run_sim(SYS, p, knobs, arm, seed, 1.0, cp_only=True, with_fail=False, abs_rate=rate, n_req=3000)

    def test_c1_wait_diverges_above_server_capacity(self):
        kn = dict(TWO, hot=False)
        k_rpc = 4 * math.ceil((8192 / 64) / 8) + 1  # approx RPCs per request (lookup 1 + 3 ops x 16)
        cap = 12.13e6 / (3 * 16 + 1)
        under = self.cp(kn, C1, 0.2 * cap)["cp_chain_p99_us"]
        over = self.cp(kn, C1, 3.0 * cap)["cp_chain_p99_us"]
        self.assertLess(under, 20.0)
        self.assertGreater(over, 50 * under)
        self.assertGreater(self.cp(kn, C1, 3.0 * cap)["arm_stats"]["server_util"], 0.95)

    def test_more_server_threads_reduce_overload_wait(self):
        kn = dict(TWO, hot=False)
        rate = 3.0 * 12.13e6 / 49
        t1 = self.cp(kn, C1, rate)["cp_chain_p99_us"]
        t4 = self.cp(dict(kn, server_threads=4), C1, rate)["cp_chain_p99_us"]
        self.assertLess(t4, t1 / 5)

    def test_c1_no_batch_issues_more_rpcs(self):
        kn = dict(TWO, hot=False)
        a = self.cp(kn, C1, 1000.0)["arm_stats"]["rpc_count"]
        b = self.cp(kn, C1_NOBATCH, 1000.0)["arm_stats"]["rpc_count"]
        self.assertGreater(b, 5 * a)

    def test_c2_grant_delay_proportional_to_S_N_tprobe(self):
        kn = dict(TWO, hot=False)
        waits = {}
        for S in (8, 64, 512):
            r = self.cp(dict(kn, lock_stripes=S), C2, 500.0)
            waits[S] = r["arm_stats"]["lock_wait_mean_ms"]
            self.assertAlmostEqual(r["arm_stats"]["lock_scan_period_us"], S * 4 * 0.35, places=6)
        self.assertGreater(waits[64], 5 * waits[8])
        self.assertGreater(waits[512], 5 * waits[64])
        # mean wait ~ half a scan period (the slot of the waiting node is probed once per period)
        self.assertAlmostEqual(waits[512] * 1e3 / (512 * 4 * 0.35), 0.5, delta=0.12)

    def test_c2_grant_delay_grows_with_node_count(self):
        w = {}
        for n in (2, 8):
            kn = dict(TWO, n_p=n, n_d=n, hot=False)
            w[n] = self.cp(kn, C2, 500.0)["arm_stats"]["lock_wait_mean_ms"]
        self.assertGreater(w[8], 2.5 * w[2])

    def test_c2_no_scan_has_no_scan_wait(self):
        kn = dict(TWO, hot=False)
        full = self.cp(kn, C2, 500.0)
        ns = self.cp(kn, C2_NOSCAN, 500.0)
        self.assertLess(ns["arm_stats"]["lock_wait_mean_ms"], full["arm_stats"]["lock_wait_mean_ms"] / 20)
        self.assertLess(ns["cp_chain_p50_us"], full["cp_chain_p50_us"])
        self.assertEqual(ns["arm_stats"]["lock_scan_period_us"], 0.0)

    def test_c2_single_stripe_serializes_and_saturates(self):
        kn = dict(TWO, hot=False, lock_stripes=1)
        low = self.cp(kn, C2, 1000.0)["cp_chain_p99_us"]
        high = self.cp(kn, C2, 2.0e5)["cp_chain_p99_us"]
        self.assertGreater(high, 20 * low)

    def test_hot_prefix_pins_use_hot_stripe(self):
        s = sm.Sim(SYS, P, TWO, C2, 11, 1.0)
        hot = next(r for r in s.reqs if r.hot)
        self.assertEqual(s.arm.stripe_of("pin", hot), 0)
        self.assertEqual(s.arm.stripe_of("unpin", hot), 0)
        cold = next(r for r in s.reqs if not r.hot)
        self.assertEqual(s.arm.stripe_of("pin", cold), min(63, int(cold.u[1] * 64)))

    def test_c1_latency_floor_is_rpc_rtt(self):
        r = self.cp(dict(TWO, hot=False, in_tokens=512), C1, 100.0)
        self.assertGreaterEqual(r["cp_lat"]["lookup"]["p50_us"], 2.11 - 1e-6)
        self.assertLess(r["cp_lat"]["lookup"]["p50_us"], 3.0)

    def test_pool_full_adds_evict_sections(self):
        kn = sc.dp4_benchmark()[9].resolved()
        self.assertEqual(kn["pool_occ"], 0.95)
        self.assertIn("evict", run(kn, C2)["cp_lat"])
        self.assertNotIn("evict", run(TWO, C2)["cp_lat"])


class MonotoneTest(unittest.TestCase):
    def test_lookup_cost_scales_with_blocks(self):
        small = run(dict(TWO, block_tokens=256), C1)["cp_lat"]["publish"]["p50_us"]
        big = run(dict(TWO, block_tokens=16), C1)["cp_lat"]["publish"]["p50_us"]
        self.assertGreater(big, small)

    def test_c2_publish_latency_rises_with_stripes(self):
        a = run(dict(TWO, lock_stripes=8), C2)["cp_lat"]["publish"]["p50_us"]
        b = run(dict(TWO, lock_stripes=512), C2)["cp_lat"]["publish"]["p50_us"]
        self.assertGreater(b, 5 * a)


class FailureTest(unittest.TestCase):
    def test_failure_hook_is_noop_without_failure(self):
        a = run(CB1, C2, with_fail=True)
        b = run(CB1, C2, with_fail=False)
        self.assertEqual(json.dumps(a, sort_keys=True, default=str), json.dumps(b, sort_keys=True, default=str))

    def test_server_crash_is_noop_for_arms_without_server(self):
        kn = sc.dp4_benchmark()[-2].resolved(dict(fail_rebuild=True))
        for arm in (BASE, C2):
            a = run(kn, arm, with_fail=True)
            b = run(kn, arm, with_fail=False)
            self.assertEqual(a["goodput_tps"], b["goodput_tps"])
            self.assertEqual(a["ttft_p99_ms"], b["ttft_p99_ms"])

    def test_server_restart_stalls_metadata_ops(self):
        s = SimpleNamespace(w0=0.0, w1=100.0, push=lambda *a, **k: pushed.append(a), N=2)
        pushed = []
        arm = C1Central(s, P, {})
        arm.server_down(10.0, 10.5)
        arm.submit("pin", 10.1, SimpleNamespace(), 8, 1)
        self.assertGreaterEqual(pushed[-1][0], 10.5)
        arm.submit("pin", 20.0, SimpleNamespace(), 8, 1)
        self.assertLess(pushed[-1][0], 20.001)

    def test_lockholder_as_published_sticks_and_lease_heals(self):
        rows = {n: kn for s in sc.dp4_benchmark() for n, kn in s.rows()}
        a = run(rows["d4_fail_lockholder[as_published]"], C2)
        l = run(rows["d4_fail_lockholder[lease]"], C2)
        self.assertGreaterEqual(a["arm_stats"]["stuck_stripes"], 1)
        self.assertGreater(a["n_total_incomplete"], 0)
        self.assertEqual(l["arm_stats"]["stuck_stripes"], 0)
        self.assertEqual(l["n_total_incomplete"], 0)
        self.assertGreater(a["n_slo_viol"], l["n_slo_viol"])
        self.assertEqual(a["fail"]["window_s"], float("inf"))
        self.assertEqual(l["fail"]["window_s"], 1.0)

    def test_lockholder_crash_is_same_node_loss_for_other_arms(self):
        rows = {n: kn for s in sc.dp4_benchmark() for n, kn in s.rows()}
        b = run(rows["d4_fail_lockholder[as_published]"], BASE)
        self.assertEqual(b["n_total_incomplete"], 0)
        self.assertGreater(b["n_total_failed"], 0)  # the node's in-flight requests are lost in every arm


class StatsTest(unittest.TestCase):
    def test_mean_ci_and_geomean(self):
        m, ci, cv = q.mean_ci([1, 2, 3, 4, 5])
        self.assertAlmostEqual(m, 3.0)
        self.assertAlmostEqual(ci, 2.776 * math.sqrt(2.5) / math.sqrt(5))
        self.assertAlmostEqual(q.geomean([2, 8]), 4.0)

    def test_star_boundaries(self):
        self.assertEqual(q.stars_q1(1.10), "★★★")
        self.assertEqual(q.stars_q1(1.0999), "★★")
        self.assertEqual(q.stars_q1(0.90), "★★")
        self.assertEqual(q.stars_q1(0.8999), "★")
        self.assertEqual(q.stars_q2(2000, 50), "★★★")
        self.assertEqual(q.stars_q2(2001, 50), "★★")
        self.assertEqual(q.stars_q2(4000, 100), "★★")
        self.assertEqual(q.stars_q2(4001, 10), "★")
        self.assertEqual(q.stars_q3(1.25), "★★★")
        self.assertEqual(q.stars_q3(0.95), "★★")
        self.assertEqual(q.stars_q3(0.949), "★")

    def test_paired_verdicts(self):
        base = [100, 101, 99, 100, 100]
        self.assertEqual(q.paired(base, [120, 121, 119, 120, 120], True)[0], "win")
        self.assertEqual(q.paired(base, [80, 81, 79, 80, 80], True)[0], "loss")
        self.assertEqual(q.paired(base, [100.5, 101.5, 99.5, 100.5, 100.5], True)[0], "tie")  # < 1 %
        noisy = [100, 140, 60, 120, 80]
        self.assertEqual(q.paired(base, noisy, True)[0], "tie")  # inside the CI
        self.assertEqual(q.paired(base, [80, 81, 79, 80, 80], False)[0], "win")  # lower is better

    def test_next_load_and_extension(self):
        self.assertEqual([q.next_load(2.0), q.next_load(3.0), q.next_load(7.0)], [3.0, 4.0, 8.0])

    def _fake_runner(self, peak):
        def fake(tasks, jobs):
            out = []
            for (sys_id, label, row, arm, ld, sd, nofail, cfg, ov) in tasks:
                g = 100.0 * ld if ld <= peak else 100.0 * peak - 10.0 * (ld - peak)
                out.append(dict(row=row, arm=arm, load_scale=ld, seed=sd, goodput_tps=g))
            return out
        return fake

    def test_load_sweep_extends_until_peak_is_interior(self):
        with mock.patch.object(q, "run_tasks", self._fake_runner(5.0)):
            _, ran = q.sweep("SYS-H100", "common_benchmark", 1, (BASE, C1), None, None, (11,))
        self.assertEqual(ran["cb_kv_8k_b32"], [0.5, 1.0, 1.5, 2.0, 3.0, 4.0, 5.0, 6.0])

    def test_load_sweep_not_extended_when_peak_inside_grid(self):
        with mock.patch.object(q, "run_tasks", self._fake_runner(1.0)):
            _, ran = q.sweep("SYS-H100", "common_benchmark", 1, (BASE, C1), None, None, (11,))
        self.assertEqual(ran["cb_kv_8k_b32"], [0.5, 1.0, 1.5, 2.0])

    def test_load_sweep_extends_downward_when_peak_at_lowest_point(self):
        def fake(tasks, jobs):  # goodput peaks at load 0.2
            return [dict(row=r[2], arm=r[3], load_scale=r[4], seed=r[5], goodput_tps=1000.0 - abs(r[4] - 0.2) * 100.0) for r in tasks]
        with mock.patch.object(q, "run_tasks", fake):
            _, ran = q.sweep("SYS-H100", "common_benchmark", 1, (BASE, C1), None, None, (11,))
        self.assertEqual(sorted(ran["cb_kv_8k_b32"]), [0.125, 0.25, 0.5, 1.0, 1.5, 2.0])

    def test_load_sweep_capped_at_x8(self):
        with mock.patch.object(q, "run_tasks", self._fake_runner(1e9)):
            _, ran = q.sweep("SYS-H100", "common_benchmark", 1, (BASE, C1), None, None, (11,))
        self.assertEqual(max(ran["cb_kv_8k_b32"]), 8.0)

    def _ps(self, base, c1, c2):
        def entry(g):
            e = dict(max_goodput_tps=g, seeds_goodput_tps=[g] * 5, seeds_ttft_p99_ms=[1000.0] * 5, seeds_tpot_p99_ms=[10.0] * 5,
                     ttft_p99_ms=1000.0, tpot_p99_ms=10.0, n_slo_viol=0.0, n_cohort=100.0)
            return e
        return {BASE: entry(base), C1: entry(c1), C2: entry(c2)}

    def test_fit_labels(self):
        ps = {"inf": self._ps(0, 0, 0), "sat": self._ps(100, 100, 100), "valid": self._ps(100, 130, 100)}
        lab = q.label_scenarios(ps)
        self.assertEqual({k: v["fit"] for k, v in lab.items()}, {"inf": "infeasible", "sat": "saturated", "valid": "comparison_valid"})
        self.assertEqual(lab["valid"]["vs_baseline"][C1]["verdict"], "win")
        t = q.tally(lab, C1)
        self.assertEqual((len(t["win"]), len(t["tie"]), len(t["loss"])), (1, 1, 0))

    def test_scaling_efficiency_formula(self):
        ps = {f"d4_node_scale_n{n}": self._ps(100.0 * n / 2 * (0.9 if n > 2 else 1), 1, 1) for n in (2, 4, 8, 16)}
        eff = q.scaling(ps)
        self.assertAlmostEqual(eff[BASE]["8"], 0.9)

    def test_tail_check_counts_worse_pairs(self):
        a, b = self._ps(100, 100, 100), self._ps(100, 100, 100)
        for ps_ in (a, b):
            for v in ps_.values():
                v["at_base_peak"] = dict(ttft_p99_ms=v["ttft_p99_ms"], tpot_p99_ms=v["tpot_p99_ms"])
        b[C1]["ttft_p99_ms"] = b[C1]["at_base_peak"]["ttft_p99_ms"] = 1500.0
        res = q.tail_check({"a": a, "b": b}, C1, "base_peak")
        self.assertEqual(res["ttft"]["n_worse"], 1)
        self.assertEqual(res["ttft"]["worst_pair"], "b")
        self.assertAlmostEqual(res["ttft"]["worst_ratio"], 1.5)
        self.assertEqual(res["tpot"]["n_worse"], 0)


class AblationRegistryTest(unittest.TestCase):
    def test_variants_registered_and_run(self):
        for a in ABLATION_NAMES:
            self.assertIn(a, ARM_CLASSES)
            self.assertGreater(run(TWO, a)["goodput_tps"], 0)

    def test_full_arms_unchanged_by_variants(self):
        # the control (full C1/C2) is the same code path that produced the main result
        self.assertEqual(run(TWO, C1)["goodput_tps"], run(TWO, C1)["goodput_tps"])


class SensitivityTest(unittest.TestCase):
    def test_split_overrides_and_bg_scale(self):
        d, bg = q.split_overrides((("bg_scale", 0.5), ("eta_cxl", 0.7)))
        self.assertEqual((d, bg), ({"eta_cxl": 0.7}, 0.5))
        kn = q._knobs("common_benchmark", "cb_kv_8k_b32_ramp", (("bg_scale", 0.5),))
        self.assertAlmostEqual(kn["bg0"], 0.1)
        self.assertAlmostEqual(kn["bg1"], 0.45)
        self.assertEqual(q._knobs("common_benchmark", "cb_kv_8k_b32", None)["bg0"], 0.85)
        self.assertEqual(q._knobs("dp4_benchmark", "d4_block16", (("bg_scale", 0.5),))["bg0"], 0.0)
        self.assertEqual(q._params(None, (("bg_scale", 0.5), ("eta_cxl", 0.7))).eta_cxl, 0.7)

    def test_grid_has_12_registered_combinations(self):
        import sensitivity as sens
        g = sens.configs("grid")
        self.assertEqual(len(g), 12)
        self.assertEqual({(c[2]["eta_cxl"], round(c[2]["bg_scale"] * 0.85, 6)) for c in g},
                         {(e, b) for e in (0.5, 0.7, 0.85, 1.0) for b in (0.0, 0.5, 0.85)})
        self.assertTrue(all(c[3] == ["common_benchmark", "dp4_benchmark"] for c in g))
        self.assertIn(("eta_cxl_bg", "eta0.5_bg0.85"), [(c[0], c[1]) for c in g])  # control cell = main configuration
        labels = [c[1] for c in sens.configs("others")]
        for want in ("eta_rdma0.6", "overlap0.9", "S512", "probe0.7", "T4", "batch16", "cs5"):
            self.assertIn(want, labels)

    def test_control_override_reproduces_main_parameters(self):
        a = run(CB1, C1)
        b = sm.run_sim(SYS, q._params(None, (("eta_cxl", 0.5), ("bg_scale", 1.0))), q._knobs("common_benchmark", "cb_kv_8k_b32", (("bg_scale", 1.0),)), C1, 11, 1.0)
        pa = P.with_overrides(n_req_base=2000)
        ref = sm.run_sim(SYS, pa, CB1, C1, 11, 1.0)
        self.assertEqual(b["goodput_tps"], ref["goodput_tps"])
        self.assertEqual(b["ttft_p99_ms"], ref["ttft_p99_ms"])

    def test_higher_eta_cxl_helps_candidates_not_baseline(self):
        lo = run(CB1, C1)
        hi = run(CB1, C1, p=P.with_overrides(eta_cxl=1.0))
        self.assertLess(hi["ttft_p50_ms"], lo["ttft_p50_ms"])
        self.assertEqual(run(CB1, BASE)["ttft_p50_ms"], run(CB1, BASE, p=P.with_overrides(eta_cxl=1.0))["ttft_p50_ms"])

    def test_crossing_interpolates_and_reports_none(self):
        import sensitivity as sens
        r = sens.crossing([0.5, 0.7, 0.85, 1.0], [0.8, 0.9, 1.1, 1.2], 1.0)
        self.assertEqual(r["status"], "interpolated")
        self.assertAlmostEqual(r["x"], 0.7 + (0.1 / 0.2) * 0.15)
        self.assertEqual(sens.crossing([0.5, 1.0], [0.4, 0.8], 1.0)["status"], "none_in_grid")
        self.assertEqual(sens.crossing([0.5, 1.0], [1.4, 0.8], 1.0)["status"], "met_at_lowest")
        low = sens.crossing([0.5, 0.7, 1.0], [5.0, 3.0, 0.0], 0.0, higher_is_better=False)  # worse-pair count reaching 0
        self.assertEqual(low["status"], "interpolated")
        self.assertAlmostEqual(low["x"], 1.0)
        self.assertEqual(sens.crossing([0.5, 1.0], [5.0, 2.0], 0.0, higher_is_better=False)["status"], "none_in_grid")

    def test_parity_threshold_is_the_material_tie_rule(self):
        import sensitivity as sens
        self.assertAlmostEqual(sens.PARITY, 1.0 - q.MATERIAL_REL)
        self.assertEqual(sens.crossing([0.5, 1.0], [0.9995, 1.0], sens.PARITY)["status"], "met_at_lowest")

    def test_break_even_over_background_scans_from_high_to_low(self):
        import sensitivity as sens
        r = sens.crossing([0.85, 0.5, 0.0], [0.73, 0.945, 1.0], sens.PARITY)
        self.assertEqual(r["status"], "interpolated")
        self.assertAlmostEqual(r["x"], 0.5 + (0.99 - 0.945) * (0.0 - 0.5) / (1.0 - 0.945))
        self.assertEqual(r["bracket"], [0.5, 0.0])

    def test_eta_classification_uses_registered_range_and_provenance(self):
        import sensitivity as sens
        self.assertIn("inside", sens.classify_eta(0.8))
        self.assertIn("outside", sens.classify_eta(0.95))
        self.assertIn("no break-even", sens.classify_eta(None))
        self.assertEqual(sens.provenance_of("eta_cxl")["provenance"], "ASSUMED")

    def test_star_rescoring_pm10(self):
        import sensitivity as sens
        m = dict(qa1_ratio=0.95, ttft_p99_worst_own=2100.0, tpot_p99_worst_own=40.0, qa3_multiplier=1.0)
        self.assertEqual(sens.stars_scaled(m, 1.0), dict(qa1=2, qa2=2, qa3=2, total=6))
        self.assertEqual(sens.stars_scaled(m, 1.1)["qa2"], 3 - 0)  # 2100 <= 2200
        self.assertEqual(sens.stars_scaled(m, 0.9)["qa1"], 2)
        self.assertEqual(sens.stars_scaled(dict(m, qa1_ratio=0.85), 0.9)["qa1"], 2)  # 0.85 >= 0.81
        self.assertEqual(sens.stars_scaled(dict(m, qa1_ratio=0.85), 1.0)["qa1"], 1)

    def test_summary_and_table_generator_from_synthetic_data(self):
        import sensitivity as sens
        import sensitivity_table as tab

        def cm(r, m, tw):
            return dict(qa1_ratio=r, qa1_stars="x", qa1_abs_goodput_tps=1.0, qa1_n_cand_zero=0, ttft_p99_ms_own=1.0, tpot_p99_ms_own=1.0,
                        ttft_p99_ms_common=1.0, ttft_p99_ms_load1=1.0, qa2_stars_own="x", qa2_stars_load1="x", ttft_p99_worst_own=1.0,
                        tpot_p99_worst_own=1.0, ttft_p99_worst_load1=1.0, tpot_p99_worst_load1=1.0, qa3_gib=1.0, qa3_multiplier=m,
                        qa3_stars="x", qa3_load1_multiplier=m, tail_ttft_worse_common=tw, tail_ttft_pairs_common=6,
                        tail_ttft_worst_ratio_common=1.0 + tw, tail_ttft_worse_own=tw, tail_ttft_pairs_own=6, tail_ttft_worst_ratio_own=1.0)
        grid = {}
        for e in sens.ETAS:
            for b in sens.BGS:
                r = 0.5 + e * 0.6 - b * 0.1
                grid[f"eta{e}_bg{b}"] = {s: dict(candidates={"Baseline-RDMA": cm(1.0, 1.0, 0), C1: cm(r, r, int(6 * (1 - e))), C2: cm(r, r, int(6 * (1 - e)))})
                                         for s in (*sens.SYSTEMS, "INT-H100-B200")}
        summary = {"eta_cxl_bg": grid}
        be = sens.break_even(summary)
        r = be["INT-H100-B200"][C1]["bg0.0"]["qa1_ratio_ge_1"]
        self.assertEqual(r["status"], "interpolated")
        self.assertAlmostEqual(r["x"], 0.7 + (1.0 - (0.5 + 0.7 * 0.6)) / ((0.5 + 0.85 * 0.6) - (0.5 + 0.7 * 0.6)) * 0.15)
        self.assertEqual(be["INT-H100-B200"][C1]["bg0.85"]["ttft_worse_pairs_common_eq_0"]["status"], "interpolated")
        S = dict(meta=dict(etas=list(sens.ETAS), backgrounds=list(sens.BGS), eta_bw_parity=0.675), main={"INT-H100-B200": dict(candidates={"Baseline-RDMA": cm(1.0, 1.0, 0), C1: cm(0.7, 0.2, 5), C2: cm(0.7, 0.2, 5)})},
                 configs={"eta_cxl_bg": grid}, break_even=be, one_param_sweeps={}, star_boundary_pm10={})
        text = tab.tables(S)
        self.assertIn("| 0.7 |", text)
        self.assertIn("Break-even over eta_cxl", text)
        self.assertIn("interpolated", text)


if __name__ == "__main__":
    unittest.main()
