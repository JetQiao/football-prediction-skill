import tempfile
import unittest
from pathlib import Path

from football_prediction.snapshots import SnapshotEnvelope, SnapshotStore


class SnapshotTests(unittest.TestCase):
    def test_rejects_observation_after_cutoff(self):
        with self.assertRaisesRegex(ValueError, "observed_at"):
            SnapshotEnvelope(
                dataset="fixtures",
                business_date="2026-07-16",
                as_of="2026-07-16T10:00:00+08:00",
                observed_at="2026-07-16T10:01:00+08:00",
                source="test",
                source_event_id="event-1",
                payload={"matches": []},
            )

    def test_identical_payload_at_different_cutoffs_keeps_two_snapshots(self):
        payload = {"matches": [{"id": "1"}]}
        first = SnapshotEnvelope(
            dataset="fixtures",
            business_date="2026-07-16",
            as_of="2026-07-16T10:00:00+08:00",
            observed_at="2026-07-16T10:00:00+08:00",
            source="test",
            source_event_id="event-1",
            payload=payload,
        )
        second = SnapshotEnvelope(
            dataset="fixtures",
            business_date="2026-07-16",
            as_of="2026-07-16T11:00:00+08:00",
            observed_at="2026-07-16T11:00:00+08:00",
            source="test",
            source_event_id="event-1",
            payload=payload,
        )
        self.assertEqual(first.payload_hash, second.payload_hash)
        self.assertNotEqual(first.snapshot_id, second.snapshot_id)

        with tempfile.TemporaryDirectory() as temp:
            store = SnapshotStore(Path(temp))
            store.write(first)
            store.write(second)
            store.write(second)
            rows = store.catalog("fixtures")

        self.assertEqual(len(rows), 2)
        self.assertEqual({row["snapshot_id"] for row in rows}, {first.snapshot_id, second.snapshot_id})


if __name__ == "__main__":
    unittest.main()
