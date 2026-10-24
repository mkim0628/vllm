from __future__ import annotations

import unittest

from events import EventType, MigrationEvent, MigrationScheduler
from registry import C1DataObjectRegistry, C2DataObjectRegistry


class RegistryBoundaryTest(unittest.TestCase):
    def test_c1_record_is_type_agnostic(self):
        r = C1DataObjectRegistry()
        r.add(1, 1024, "hbm")
        rec = r.get(1)
        self.assertFalse(hasattr(rec, "data_type"))
        self.assertEqual(rec.size_bytes, 1024)
        self.assertEqual(rec.tier, "hbm")

    def test_c2_record_is_type_aware(self):
        r = C2DataObjectRegistry()
        r.add(
            1,
            "KV_CACHE",
            1024,
            "hbm",
            {"hotness": 0.9},
        )
        rec = r.get(1)
        self.assertEqual(rec.data_type, "KV_CACHE")
        self.assertEqual(
            rec.class_metadata["hotness"], 0.9
        )

    def test_scheduler_coalesces_telemetry_only(self):
        s = MigrationScheduler()
        s.push(
            MigrationEvent(
                EventType.ACCESSED,
                0,
                1,
                count=1,
            )
        )
        s.push(
            MigrationEvent(
                EventType.TELEMETRY,
                0,
                metadata={"telemetry": {}},
            )
        )
        s.push(
            MigrationEvent(
                EventType.TELEMETRY,
                1,
                metadata={"telemetry": {}},
            )
        )
        self.assertEqual(s.stats.coalesced, 1)
        self.assertEqual(len(s._q), 2)


class DropActionTest(unittest.TestCase):
    def test_registry_drop_promotes_replica(self):
        for reg, args in (
            (C1DataObjectRegistry(), (1, 1024, "hbm")),
            (C2DataObjectRegistry(), (1, "KV_CACHE", 1024, "hbm")),
        ):
            reg.add(*args, replica_tier="dram")
            reg.drop_to_replica(1)
            rec = reg.get(1)
            self.assertEqual(rec.tier, "dram")
            self.assertIsNone(rec.replica_tier)

    def test_c1_replica_field_is_not_a_type_field(self):
        r = C1DataObjectRegistry()
        r.add(1, 1024, "hbm", replica_tier="dram")
        self.assertFalse(hasattr(r.get(1), "data_type"))

    def test_move_onto_replica_tier_clears_replica(self):
        r = C1DataObjectRegistry()
        r.add(1, 1024, "hbm", replica_tier="dram")
        r.move(1, "dram")
        self.assertIsNone(r.get(1).replica_tier)

    def _run(self, cand, drop, frac=0.5):
        from model import DATA_PRIORS, load_system
        from pathlib import Path
        from scenarios import scenarios
        from simulator import run_sim

        system = load_system(Path(__file__).resolve().parent / "configs")
        sc = next(s for s in scenarios() if s.name == "kv_b16_c32k_burst_chbm")
        return run_sim(system, sc, 11, cand, DATA_PRIORS, 1.0,
                       replica_fraction=frac, drop_enabled=drop)

    def test_default_has_no_drop(self):
        r = self._run("C1-resource-driven", False, 0.0)
        self.assertEqual(r["drop_count"], 0)
        self.assertEqual(r["replica_gib_created"], 0.0)

    def test_drop_off_never_drops_even_with_replicas(self):
        for cand in ("C1-resource-driven", "C2-behavior-driven"):
            r = self._run(cand, False)
            self.assertEqual(r["drop_count"], 0)
            self.assertGreater(r["replica_gib_created"], 0.0)

    def test_drop_is_not_counted_as_transfer(self):
        for cand in ("C1-resource-driven", "C2-behavior-driven"):
            on = self._run(cand, True)
            self.assertGreater(on["drop_count"], 0, cand)
            self.assertGreater(on["drop_gib_avoided"], 0.0, cand)
            # DROP is a demotion in direction accounting but never a transfer:
            self.assertGreaterEqual(on["demotion_count"], on["drop_count"], cand)
            self.assertLessEqual(
                on["migration_count"] + on["drop_count"],
                on["promotion_count"] + on["demotion_count"] + on["rebalance_count"],
                cand,
            )


# --------------------------------------------------------------------------- loop-iteration tests
CONFIGS = None


def _system(profile="SYS-4"):
    from pathlib import Path
    from model import load_profile

    return load_profile(Path(__file__).resolve().parent / "configs", profile)[0]


def _find(name):
    from scenarios import common_benchmark, dynamic_benchmark, dynamic_controls, scenarios

    for f in (common_benchmark, scenarios, dynamic_benchmark, dynamic_controls):
        for sc in f():
            if sc.name == name:
                return sc
    raise KeyError(name)


class BaselineTest(unittest.TestCase):
    def test_baseline_never_migrates(self):
        from model import DATA_PRIORS
        from simulator import run_sim

        sys_ = _system()
        for name in ("cb_kv_8k_b32", "dyn_cold_resident_chat_wave", "dyn_host_path_contention_kv", "rag_1tib_b16"):
            r = run_sim(sys_, _find(name), 11, "Baseline-static", DATA_PRIORS, 1.0)
            self.assertEqual(r["migration_count"], 0, name)
            self.assertEqual(r["promotion_count"] + r["demotion_count"] + r["rebalance_count"], 0, name)
            self.assertEqual(r["decision_overhead_ms"], 0.0, name)


class TypeBoundaryTest(unittest.TestCase):
    def test_c1_code_path_has_no_data_type_branching(self):
        import inspect

        import policies

        forbidden = ("data_type", "data_class", "KV_CACHE", "RAG_DATA", "AGENT_MEMORY", "TOOL_RESULT",
                     "LORA_ADAPTER", "MOE_EXPERT", "TYPE_TIER_PREFERENCE", "class_metadata")
        for cls in (
            policies.C1ResourceDrivenMigration, policies.DestinationTierSelectorC1, policies.DataEvictionManager,
            policies.DataMemoryAffinityMapper, policies.MigrationDataSelectorC1, policies.ResourceStateMonitor,
            policies.ResourceBasedTrendAnalyzer, policies.AccessCostEstimator, policies.MigrationBudget,
        ):
            src = inspect.getsource(cls)
            for token in forbidden:
                self.assertNotIn(token, src, f"{cls.__name__} mentions {token}")

    def test_hint_channel_carries_operation_class_not_type(self):
        from scenarios import generate_trace
        from simulator import static_hints

        sc = _find("mixed_all_ai_data_b64")
        for h in static_hints(generate_trace(sc, 11)).values():
            self.assertIn(h["op"], ("attention", "index_scan", "context_fetch", "weight_fetch"))
            self.assertNotIn("data_type", h)


class AccessCostTest(unittest.TestCase):
    def test_estimator_matches_simulator_cost(self):
        """The estimator is a descriptor-derived copy of the serving cost model: it must agree with the
        simulator for every operation class and tier (no per-scenario constants)."""
        from policies import AccessCostEstimator
        from scenarios import generate_trace
        from simulator import static_hints, tpot_s, ttft_s

        sys_ = _system()
        est = AccessCostEstimator(sys_)
        for name in ("mixed_all_ai_data_b64", "cb_kv_8k_b32"):
            sc = _find(name)
            objs = generate_trace(sc, 11)
            hints = static_hints(objs)
            seen = set()
            for o in objs:
                if o.data_class in seen:
                    continue
                seen.add(o.data_class)
                for tier in sys_.memories:
                    e_ttft, e_tpot = est.estimate(tier, hints[o.oid], o.size_bytes)
                    self.assertAlmostEqual(e_ttft, ttft_s(sys_, o, tier, "C", 1.0, 0.0, 0.0), delta=1e-9 + 1e-9 * e_ttft, msg=(o.data_class, tier))
                    self.assertAlmostEqual(e_tpot, tpot_s(sys_, o, tier, "C", 1.0), delta=1e-12 + 1e-9 * e_tpot, msg=(o.data_class, tier))

    def test_c1_selector_rejects_slo_violating_destination(self):
        """cb_kv_8k_b32: KV on CXL-PNM would take ~311 ms/token (batch 32) - the first-pass C1 chose it."""
        from policies import (AccessCostEstimator, DataMemoryAffinityMapper, DestinationTierSelectorC1,
                              ResourceState)
        from registry import C1DataObjectRegistry
        from scenarios import generate_trace
        from simulator import static_hints

        sys_ = _system()
        sc = _find("cb_kv_8k_b32")
        o = generate_trace(sc, 11)[0]
        hint = static_hints([o])[o.oid]
        reg = C1DataObjectRegistry()
        reg.add(o.oid, o.size_bytes, "dram")
        rec = reg.get(o.oid)
        est = AccessCostEstimator(sys_)
        self.assertGreater(est.estimate("cxl_pnm", hint, o.size_bytes)[1], 0.050)
        sel = DestinationTierSelectorC1(sys_, DataMemoryAffinityMapper(), est)
        states = {n: ResourceState(0.1, 0.0, 0.1, 0.0, 0.9) for n in sys_.memories}
        states["dram"] = ResourceState(0.95, 0.0, 0.95, 0.0, 0.05)
        occ = {n: 0.0 for n in sys_.memories}
        caps = {n: m.capacity_bytes for n, m in sys_.memories.items()}
        dst = sel.select(rec, "dram", states, occ, caps, hint)
        self.assertNotIn(dst, ("cxl_pnm", "custom_hbm", "ssd_pim"))
        self.assertIsNotNone(dst)

    def test_c1_selector_no_cost_info_falls_back(self):
        """Without an operation hint the selector behaves as in the first pass (cost unknown -> no filter)."""
        from policies import DataMemoryAffinityMapper, DestinationTierSelectorC1, ResourceState
        from registry import C1DataObjectRegistry

        sys_ = _system()
        reg = C1DataObjectRegistry()
        reg.add(1, 1024**3, "dram")
        states = {n: ResourceState(0.1, 0.0, 0.1, 0.0, 0.9) for n in sys_.memories}
        states["dram"] = ResourceState(0.95, 0.0, 0.95, 0.0, 0.05)
        sel = DestinationTierSelectorC1(sys_, DataMemoryAffinityMapper())
        occ = {n: 0.0 for n in sys_.memories}
        caps = {n: m.capacity_bytes for n, m in sys_.memories.items()}
        self.assertIsNotNone(sel.select(reg.get(1), "dram", states, occ, caps, {}))


class MigrationBudgetTest(unittest.TestCase):
    def test_bucket_refill_cap_and_reserve(self):
        from policies import MigrationBudget

        b = MigrationBudget(share=0.25, window_s=8.0)  # cap 2.0 s
        b.refill(0.0)
        self.assertFalse(b.try_spend(2.5))  # larger than the bucket: never admitted
        self.assertTrue(b.try_spend(2.0))
        self.assertFalse(b.try_spend(0.1))
        b.refill(4.0)  # +1.0 s
        self.assertAlmostEqual(b.tokens, 1.0)
        b.reserved = 0.8
        self.assertFalse(b.try_spend(0.5))  # would eat the reserved part
        self.assertTrue(b.try_spend(0.8, use_reserved=True))
        b.refill(1000.0)
        self.assertLessEqual(b.tokens, b.cap + 1e-9)

    def test_budget_respected_in_runs(self):
        """Committed migration link time never exceeds capacity + share * elapsed (per run)."""
        from model import DATA_PRIORS
        from simulator import run_sim

        sys_ = _system()
        for name in ("cb_kv_8k_b32", "dyn_kv_rotating_hotset", "dyn_cold_resident_chat_wave"):
            sc = _find(name)
            for cand in ("C1-resource-driven", "C2-behavior-driven"):
                r = run_sim(sys_, sc, 11, cand, DATA_PRIORS, 1.0)
                limit = r["budget_cap_s"] + r["budget_share"] * sc.horizon_s
                self.assertLessEqual(r["budget_spent_s"], limit + 1e-6, (name, cand))
                self.assertGreater(r["budget_share"], 0.0)

    def test_c2_demotion_requires_hbm_pressure(self):
        """Design 17.3: demotion = reuse decline AND upper-tier pressure. With ample HBM there is no demotion."""
        from dataclasses import replace

        from model import DATA_PRIORS
        from simulator import run_sim

        sc = replace(_find("cb_kv_8k_b32"), hbm_capacity_mult=1.0)
        r = run_sim(_system(), sc, 11, "C2-behavior-driven", DATA_PRIORS, 1.0)
        self.assertEqual(r["demotion_count"], 0)


class DynamicBenchmarkTest(unittest.TestCase):
    def test_dynamic_scenarios_are_deterministic(self):
        from scenarios import dynamic_benchmark, generate_trace

        for sc in dynamic_benchmark():
            a = [(o.oid, o.size_bytes, o.base_rate, o.arrival_s, o.rate_schedule) for o in generate_trace(sc, 11)]
            b = [(o.oid, o.size_bytes, o.base_rate, o.arrival_s, o.rate_schedule) for o in generate_trace(sc, 11)]
            self.assertEqual(a, b, sc.name)
            self.assertTrue(sc.description and "As-Is" in sc.description, sc.name)

    def test_run_is_deterministic(self):
        from model import DATA_PRIORS
        from simulator import run_sim

        sc = _find("dyn_kv_rotating_hotset")
        for cand in ("Baseline-static", "C1-resource-driven", "C2-behavior-driven"):
            a = run_sim(_system(), sc, 23, cand, DATA_PRIORS, 1.0)
            b = run_sim(_system(), sc, 23, cand, DATA_PRIORS, 1.0)
            self.assertEqual(a, b, cand)

    def test_baseline_feasible_on_controls_and_stale_on_dynamic(self):
        """Feasibility proof: with the staleness removed the baseline meets the SLO (>= 0.99 of served tokens);
        in the dynamic scenario it serves some traffic within the SLO (goodput > 0) but not all."""
        from model import DATA_PRIORS
        from scenarios import dynamic_benchmark, dynamic_controls
        from simulator import run_sim

        sys_ = _system()
        for sc in dynamic_controls():
            r = run_sim(sys_, sc, 11, "Baseline-static", DATA_PRIORS, 1.0)
            self.assertGreaterEqual(r["slo_goodput_tokens"] / r["served_tokens"], 0.99, sc.name)
        for sc in dynamic_benchmark():
            r = run_sim(sys_, sc, 11, "Baseline-static", DATA_PRIORS, 1.0)
            ratio = r["slo_goodput_tokens"] / r["served_tokens"]
            self.assertGreater(ratio, 0.0, sc.name)
            self.assertLess(ratio, 0.9, sc.name)

    def test_existing_scenarios_keep_their_traces(self):
        """The B-class additions (Scenario.plan, DataObject.rate_schedule) must not change old scenarios."""
        from scenarios import common_benchmark, generate_trace, scenarios

        for sc in scenarios() + common_benchmark():
            self.assertEqual(sc.plan, ())
            for o in generate_trace(sc, 11):
                self.assertEqual(o.rate_schedule, ())


class C1PromotionTest(unittest.TestCase):
    def test_c1_promotes_slo_violating_object_when_hbm_has_room(self):
        from model import DATA_PRIORS
        from simulator import run_sim

        sc = _find("dyn_cold_resident_chat_wave")
        r = run_sim(_system(), sc, 11, "C1-resource-driven", DATA_PRIORS, 1.0)
        self.assertGreater(r["promotion_count"], 0)

    def test_c1_promotion_needs_static_slo_violation(self):
        """C1 promotes only objects whose static estimate violates the SLO where they sit. In the steady
        Common Benchmark (DRAM residents meet the SLO) there is nothing to promote."""
        from model import DATA_PRIORS
        from simulator import run_sim

        for name in ("cb_kv_8k_b32", "cb_mixed_8k_b32"):
            r = run_sim(_system(), _find(name), 11, "C1-resource-driven", DATA_PRIORS, 1.0)
            self.assertEqual(r["promotion_count"], 0, name)


class QaEvalTest(unittest.TestCase):
    def test_paired_verdicts(self):
        import qa_eval

        base = [100.0, 102.0, 98.0, 101.0, 99.0]
        self.assertEqual(qa_eval.paired(base, [150.0] * 5, True)[0], "win")
        self.assertEqual(qa_eval.paired(base, [50.0] * 5, True)[0], "loss")
        self.assertEqual(qa_eval.paired(base, [100.5, 101.0, 99.0, 100.0, 100.5], True)[0], "tie")
        self.assertEqual(qa_eval.paired(base, [50.0] * 5, False)[0], "win")  # lower latency is better
        self.assertEqual(qa_eval.paired([0.0] * 5, [0.0] * 5, True)[0], "tie")

    def test_fit_labels(self):
        import qa_eval

        def cell(g, ttft=100.0, tpot=10.0):
            return dict(max_goodput_tps=sum(g) / 5, seeds_goodput=g, seeds_ttft=[ttft] * 5, seeds_tpot=[tpot] * 5,
                        ttft_p99_ms=ttft, tpot_p99_ms=tpot, slo_ratio=1.0)

        same = [10.0] * 5
        ps = {
            "inf": {c: cell([0.0] * 5) for c in qa_eval.CANDS},
            "sat": {c: cell(same) for c in qa_eval.CANDS},
            "val": {qa_eval.BASE: cell(same), qa_eval.CANDS[1]: cell([20.0] * 5), qa_eval.CANDS[2]: cell(same)},
        }
        lab = qa_eval.label_scenarios(ps)
        self.assertEqual(lab["inf"]["fit"], "infeasible")
        self.assertEqual(lab["sat"]["fit"], "saturated")
        self.assertEqual(lab["val"]["fit"], "comparison_valid")
        self.assertEqual(lab["val"]["vs_baseline"][qa_eval.CANDS[1]]["verdict"], "win")


class QA3PooledUtilizationTest(unittest.TestCase):  # anchor: qa3-v4-tests (agent B)
    def test_pooled_equals_hand_value(self):
        from simulator import pooled_capacity_util

        # 2 seconds, 3 tiers. hbm cap 100: occ 50,70 ; dram cap 400: occ 100,100 ; ssd cap 1000: occ 0,0
        occ = {"hbm": 50 + 70, "dram": 100 + 100, "ssd": 0.0}
        cap = {"hbm": 200.0, "dram": 800.0, "ssd": 2000.0}
        pooled, per, active = pooled_capacity_util(occ, cap)
        self.assertAlmostEqual(pooled, (120 + 200) / 3000.0)          # 320 / 3000
        self.assertAlmostEqual(per["hbm"], 0.6)
        self.assertAlmostEqual(per["dram"], 0.25)
        self.assertAlmostEqual(per["ssd"], 0.0)
        self.assertAlmostEqual(active, (0.6 + 0.25) / 2)             # ssd holds no data -> excluded from the unweighted mean
        # capacity weighting: the large empty tier dominates pooled but not the unweighted mean
        self.assertLess(pooled, active)

    def test_pooled_empty_and_disabled(self):
        from simulator import pooled_capacity_util

        self.assertEqual(pooled_capacity_util({}, {}), (0.0, {}, 0.0))
        pooled, per, _ = pooled_capacity_util({"a": 10.0}, {"a": 20.0})  # a tier that was disabled is simply absent from the dicts
        self.assertAlmostEqual(pooled, 0.5)

    def test_dp1_relative_star_edges(self):
        import dp1_rating as r

        e = r.CFG["dp1_star"]["qa3_relative_edges"]
        self.assertEqual(e, r.CFG["dp1_star"]["qa2_latency_improvement_edges"])  # fixed by analogy to QA2
        self.assertEqual(r.CFG["version"], "dp1-rating-v5")
        # v5 resource efficiency uses the same edges (chosen by analogy to QA2 before the numbers were seen)
        self.assertEqual(r.CFG["dp1_star"]["qa3_eff_relative_edges"], r.CFG["dp1_star"]["qa2_latency_improvement_edges"])
        # v6 QA3 = HBM usage saving factor (1/ratio), same numeric edges
        self.assertEqual(r.CFG["dp1_star"]["qa3_hbm_saving_edges"], [0.95, 1.25])
        self.assertEqual(r.dp1_star(1.0 / 1.22, r.CFG["dp1_star"]["qa3_hbm_saving_edges"]), "★")      # C2-like: uses 22% more HBM
        self.assertEqual(r.dp1_star(1.0 / 0.97, r.CFG["dp1_star"]["qa3_hbm_saving_edges"]), "★★")     # C1-like
        self.assertEqual(r.dp1_star(0.949, e), "★")
        self.assertEqual(r.dp1_star(0.95, e), "★★")      # edge inclusive-lower
        self.assertEqual(r.dp1_star(1.249, e), "★★")
        self.assertEqual(r.dp1_star(1.25, e), "★★★")


# --------------------------------------------------------------------------- generation profiles (agent C)
class GenerationProfileTests(unittest.TestCase):
    GEN = ("SYS-A100", "SYS-H100", "SYS-B200", "SYS-VR")
    SIX = {"hbm", "custom_hbm", "cxl_pnm", "dram", "hbf", "ssd_pim"}

    def test_all_six_memories_present(self):
        for sid in self.GEN:
            self.assertEqual(set(_system(sid).memories), self.SIX, sid)

    def test_hbm_bw_monotonic(self):
        bws = [_system(s).memories["hbm"].ext_bw for s in self.GEN]
        self.assertEqual(bws, sorted(bws))
        self.assertEqual(len(set(bws)), 4)

    def test_link_bw_monotonic(self):
        # PCIe 4 < 5 < 6 on every host-link-bound tier (H100 and B200 are both PCIe 5.0 -> equal)
        for mem in ("custom_hbm", "cxl_pnm", "dram", "ssd_pim"):
            v = [_system(s).memories[mem].ext_bw for s in self.GEN]
            self.assertLess(v[0], v[1], mem)
            self.assertEqual(v[1], v[2], mem)
            self.assertLess(v[2], v[3], mem)

    def test_hbf_not_link_scaled(self):
        v = {_system(s).memories["hbf"].ext_bw for s in self.GEN}
        self.assertEqual(len(v), 1)

    def test_legacy_equivalence(self):
        import dataclasses

        def flat(s):
            d = {"bw": s.gpu_hbm_bw, "fl": s.gpu_compute_flops, "tdp": s.gpu_tdp_watts}
            for n, m in s.memories.items():
                d.update({f"{n}.{f.name}": getattr(m, f.name) for f in dataclasses.fields(m)})
            return d

        self.assertEqual(flat(_system("SYS-4")), flat(_system("SYS-B200")))
        diff = {k for k, v in flat(_system("SYS-5")).items() if v != flat(_system("SYS-VR"))[k]}
        self.assertTrue(diff and all(k.split(".")[0] in ("custom_hbm", "cxl_pnm", "dram", "ssd_pim") for k in diff), diff)


class LinkInterferenceTests(unittest.TestCase):
    """v2 model fix: migration link time is taken from serving bandwidth of the same tier."""

    def _run(self, cand, on):
        import qa_eval as q
        from simulator import run_sim
        sc = next(x for x in q.SET_FUNCS["dp1_dynamic_benchmark"]() if x.name == "dyn_kv_hotset_recency_shift")
        return run_sim(q._system("SYS-B200"), sc, 11, cand, q.DATA_PRIORS, 1.0, link_interference=on)

    def test_baseline_unaffected(self):
        a, b = self._run("Baseline-static", False), self._run("Baseline-static", True)
        self.assertEqual(a["ttft_p99_ms"], b["ttft_p99_ms"])
        self.assertEqual(a["slo_goodput_tokens"], b["slo_goodput_tokens"])

    def test_migrating_candidate_pays(self):
        a, b = self._run("C2-behavior-driven", False), self._run("C2-behavior-driven", True)
        self.assertGreater(b["migration_link_frac"], 0.0)
        self.assertGreaterEqual(b["ttft_p99_ms"], a["ttft_p99_ms"])
        self.assertGreater(b["ttft_p99_ms"], a["ttft_p99_ms"] * 1.05)


class CostModelTests(unittest.TestCase):
    def test_cost_occupancy_hand_value(self):
        import cost_model
        occ = {"hbm": 10.0, "dram": 20.0, "hbf": 100.0}
        self.assertAlmostEqual(cost_model.cost_occupancy(occ, "registered"), 10 * 5.0 + 20 * 1.0 + 100 * 0.3)

    def test_moving_bytes_to_expensive_tier_raises_cost_not_total(self):
        import cost_model
        a = {"hbm": 10.0, "dram": 30.0}
        b = {"hbm": 20.0, "dram": 20.0}
        self.assertEqual(sum(a.values()), sum(b.values()))
        self.assertGreater(cost_model.cost_occupancy(b), cost_model.cost_occupancy(a))

    def test_run_reports_cost_occupancy(self):
        import qa_eval as q
        from simulator import run_sim
        sc = next(x for x in q.SET_FUNCS["common_benchmark"]() if x.name == "cb_kv_8k_b32")
        r = run_sim(q._system("SYS-B200"), sc, 11, "Baseline-static", q.DATA_PRIORS, 1.0)
        self.assertEqual(set(r["cost_occ"]), {"registered", "hbm_3x", "hbm_10x"})
        self.assertGreater(r["cost_occ"]["registered"], 0.0)


if __name__ == "__main__":
    unittest.main()
