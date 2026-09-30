"""Tests for the DP1 serving-simulation pipeline (no GPU needed).

python test_dp1.py
"""

from __future__ import annotations

import json
import random
import tempfile
import unittest
from pathlib import Path

import hw as hwmod
from events import EventType, MigrationEvent
from hw import build_hw
from perf_model import FEATURES, LatencyRun, StepModel, fit, run_features
from policies_serving import C1ServingResourceDriven, C2ServingBehaviorDriven
from serving_sim import ServingSim
from shadow import shadow_run
from workload import WorkloadSpec, generate, load, save


def small_turns(kind="multiturn", rate=0.6, horizon=40, seed=0):
    return generate(WorkloadSpec(kind, rate=rate, horizon_s=horizon, seed=seed))


class WorkloadTest(unittest.TestCase):
    def test_deterministic_and_roundtrip(self):
        a, b = small_turns(), small_turns()
        self.assertEqual(a, b)
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "wl.jsonl"
            save(a, p, WorkloadSpec("multiturn", 0.6, 40))
            c, spec = load(p)
        self.assertEqual(a, c)
        self.assertEqual(spec["kind"], "multiturn")

    def test_hotness_flip_inverts(self):
        t = small_turns("hotness_flip", horizon=120)
        by = {}
        for x in t:
            by.setdefault(x.session, []).append(x)
        flipped = [
            v for v in by.values() if len(v) >= 4 and v[0].behavior != v[-1].behavior
        ]
        self.assertTrue(flipped)


class PerfModelTest(unittest.TestCase):
    def test_fit_recovers_synthetic_coefficients(self):
        h = build_hw("a100_sxm4_80g", 4, use_measurements=False)
        truth = StepModel(
            {
                "c0": 0.006,
                "c_w": 1.3,
                "c_d": 2.1,
                "c_kv": 1.6,
                "c_attn": 2.8,
                "c_comm": 1.2,
            }
        )
        runs = []
        rng = random.Random(0)
        for b in (1, 4, 16, 64):
            for i in (512, 2048, 8192):
                for o in (1, 129):
                    f = run_features(h, LatencyRun(b, i, o, 1.0))
                    lat = sum(truth.coef[k] * x for k, x in zip(FEATURES, f)) * (
                        1 + rng.gauss(0, 0.01)
                    )
                    runs.append(LatencyRun(b, i, o, lat))
        sm = fit(h, runs, ridge=1e-4)
        self.assertLess(sm.fit_info["rel_err"]["mape"], 0.03)

    def test_blind_projection_uses_spec_ratio(self):
        sm = StepModel()
        a = build_hw("a100_sxm4_80g", 4, use_measurements=False)
        h = build_hw("h100_sxm5_80g", 4, use_measurements=False)
        # memory-bound decode must speed up by ~ HBM BW ratio (3.35/2.039)
        ra = sm.step_time(a, [], 64 * 4096, 64) - sm.coef["c0"]
        rh = sm.step_time(h, [], 64 * 4096, 64) - sm.coef["c0"]
        self.assertGreater(ra / rh, 1.3)


class HWEvidenceTest(unittest.TestCase):
    def test_measurement_overrides_catalog(self):
        with tempfile.TemporaryDirectory() as d:
            md = Path(d) / "a100_sxm4_80g"
            md.mkdir()
            (md / "transfer.json").write_text(
                json.dumps(
                    {
                        "device_name": "fake",
                        "alpha_s": 8e-6,
                        "h2d_pinned": [
                            {"bytes": 2**20, "bw_Bps": 12e9},
                            {"bytes": 2**28, "bw_Bps": 24.5e9},
                        ],
                        "d2h_pinned": [
                            {"bytes": 2**20, "bw_Bps": 11e9},
                            {"bytes": 2**28, "bw_Bps": 24.0e9},
                        ],
                        "interference": {"decode_like_slowdown": 0.07},
                    }
                )
            )
            (md / "vllm_kv_capacity.json").write_text(
                json.dumps(
                    {"model": "llama_3_1_70b", "tp": 4, "kv_cache_tokens": 400000}
                )
            )
            h = build_hw("a100_sxm4_80g", 4, measured_dir=Path(d))
        self.assertEqual(h.trail.used["gpu.host_link_bw"].level, "A")
        self.assertEqual(h.kv_capacity_tokens, 400000)
        self.assertAlmostEqual(h.copy_interference, 0.07)
        self.assertIn("A", h.trail.label())
        # chunk-size sensitivity of the measured curve
        c = h.tiers["dram"].promote
        self.assertLess(c.bw_at(2**20), c.bw_at(2**28))

    def test_unsupported_tiers_are_b(self):
        h = build_hw(
            "h100_sxm5_80g", 4, tiers=("cxl_mem", "hbf"), use_measurements=False
        )
        self.assertEqual(h.trail.label(), "[B]")
        self.assertIn("hbf.latency", h.trail.assumptions())


class ArchitectureBoundaryTest(unittest.TestCase):
    def test_c1_serving_registry_type_agnostic(self):
        p = C1ServingResourceDriven()
        p.on_event(
            MigrationEvent(
                EventType.ALLOCATED,
                0.0,
                1,
                metadata={"size_bytes": 1e9, "tier": "hbm", "data_type": "KV_CACHE"},
            ),
            None,
        )
        self.assertFalse(hasattr(p.reg.get(1), "data_type"))

    def test_c2_serving_registry_type_aware_and_learns(self):
        p = C2ServingBehaviorDriven()
        p.on_event(
            MigrationEvent(
                EventType.ALLOCATED,
                0.0,
                1,
                metadata={
                    "size_bytes": 1e9,
                    "tier": "hbm",
                    "data_type": "KV_CACHE",
                    "movable": False,
                },
            ),
            None,
        )
        p.on_event(
            MigrationEvent(EventType.PHASE_CHANGE, 1.0, 1, metadata={"movable": True}),
            None,
        )
        p.on_event(MigrationEvent(EventType.ACCESSED, 6.0, 1, count=1), None)
        self.assertEqual(p.reg.get(1).data_type, "KV_CACHE")
        self.assertEqual(list(p.class_model["KV_CACHE"].closed), [5.0])


class ServingSimTest(unittest.TestCase):
    def _run(self, policy, tiers=("dram",), scale=0.08):
        h = build_hw(
            "h100_sxm5_80g", 4, tiers=tiers, hbm_kv_scale=scale, use_measurements=False
        )
        sim = ServingSim(h, StepModel(), policy, small_turns())
        r = sim.run()
        return sim, r

    def test_all_policies_complete_without_leaks(self):
        for pol in (
            "B0-vllm-lru-drop",
            "B1-lru-offload",
            "C1-resource-driven",
            "C2-behavior-driven",
        ):
            sim, r = self._run(pol)
            self.assertEqual(r["requests"], len(small_turns()), pol)
            self.assertEqual(sim.check_invariants(), [], pol)

    def test_lower_tier_reduces_recompute_under_pressure(self):
        _, b0 = self._run("B0-vllm-lru-drop")
        _, c1 = self._run("C1-resource-driven")
        self.assertGreater(b0["recompute_tokens"], 0)
        self.assertLess(c1["reuse_miss_rate"], b0["reuse_miss_rate"])

    def test_shadow_on_sim_generated_trace(self):
        sim, _ = self._run("B0-vllm-lru-drop")
        recs = sim.request_records()
        h = build_hw(
            "h100_sxm5_80g",
            4,
            tiers=("dram",),
            hbm_kv_scale=0.08,
            use_measurements=False,
        )
        for pol in ("C1-resource-driven", "C2-behavior-driven"):
            r = shadow_run(h, StepModel(), pol, recs)
            self.assertEqual(r["requests"], len(recs))
            self.assertGreaterEqual(r["projected"]["slo_goodput_tok_s"], 0.0)


class MeasuredDirTest(unittest.TestCase):
    def test_module_measured_dir_is_patchable(self):
        with tempfile.TemporaryDirectory() as d:
            old = hwmod.MEASURED
            hwmod.MEASURED = Path(d)
            try:
                h = build_hw("a100_sxm4_80g", 4)
                self.assertNotIn("A", h.trail.label())
            finally:
                hwmod.MEASURED = old


if __name__ == "__main__":
    unittest.main()
