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


if __name__ == "__main__":
    unittest.main()
