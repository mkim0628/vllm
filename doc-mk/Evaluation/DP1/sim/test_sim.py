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


if __name__ == "__main__":
    unittest.main()
