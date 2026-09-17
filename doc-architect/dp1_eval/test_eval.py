"""Fast unit tests for the DP1 C1/C2 architecture evaluator."""

from __future__ import annotations

import unittest
from pathlib import Path

import run_eval as ev


CONFIG_DIR = Path(__file__).resolve().parents[1] / "configs"


class DP1EvalTests(unittest.TestCase):
    def test_reference_config_loads(self):
        system = ev.load_system(CONFIG_DIR)
        self.assertEqual(system.model.name, "llama_3_1_70b")
        self.assertIn("hbm", system.memories)
        self.assertEqual(system.memories["hbm"].capacity_bytes, 206158430208 * 8)
        self.assertAlmostEqual(system.memories["hbm"].ext_bw, 8e12 * 8)

    def test_scenario_suite_is_broad(self):
        names = {s.name for s in ev.scenarios()}
        self.assertGreaterEqual(len(names), 18)
        for required in {
            "mixed_hot_cold",
            "hbm_pressure_ramp",
            "behavior_noise",
            "classifier_error",
            "capacity_crunch",
            "long_context",
        }:
            self.assertIn(required, names)

    def test_resource_monitor_predicts_trend(self):
        m = ev.ResourceStateMonitor(window=5, horizon=2)
        for p in (0.2, 0.3, 0.4):
            m.observe({"hbm": ev.Telemetry(capacity_util=p)})
        pred = m.state("hbm", ev.Telemetry(capacity_util=0.4))
        self.assertGreater(pred.predicted_pressure, pred.current_pressure)

    def test_c2_classifier_uses_descriptor_hint(self):
        c = ev.DataClassifier()
        obj = ev.DataObject(
            object_id=1,
            data_class="KV_CACHE",
            size_bytes=1.0,
            arrival_s=0,
            death_s=10,
            base_rate=1.0,
            access_bytes=1.0,
            context_tokens=2048,
            output_tokens=16,
            read_ratio=1.0,
            latency_sensitivity=1.0,
            type_hint="RAG_DATA",
        )
        self.assertEqual(c.classify(obj), "RAG_DATA")

    def test_same_seed_generates_same_trace(self):
        sc = next(s for s in ev.scenarios() if s.name == "steady_hot_kv")
        a = ev.generate_trace(sc, 11)
        b = ev.generate_trace(sc, 11)
        self.assertEqual([(x.data_class, x.size_bytes, x.arrival_s, x.base_rate) for x in a],
                         [(x.data_class, x.size_bytes, x.arrival_s, x.base_rate) for x in b])

    def test_modifiability_audit_does_not_fabricate_ai_tokens(self):
        audit = ev.modifiability_audit()
        for candidate in audit.values():
            self.assertIn("N/A", candidate["ai_token_consumption"])


if __name__ == "__main__":
    unittest.main()
