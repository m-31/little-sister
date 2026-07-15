import json
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from unittest import TestCase

from little_sister.maintenance import MaintenanceEntry, MaintenanceStore


class MaintenanceEntryTests(TestCase):
    def test_round_trips_through_dict(self):
        entry = MaintenanceEntry(reason="planned", set_at="2026-01-01T00:00:00",
                                 expires_at="2026-01-08T00:00:00", set_by="ada")
        self.assertEqual(MaintenanceEntry.from_dict(entry.to_dict()), entry)

    def test_is_expired_compares_to_now(self):
        now = datetime(2026, 6, 1, 12, 0, 0)
        past = MaintenanceEntry("r", "", (now - timedelta(hours=1)).isoformat())
        future = MaintenanceEntry("r", "", (now + timedelta(hours=1)).isoformat())
        self.assertTrue(past.is_expired(now))
        self.assertFalse(future.is_expired(now))

    def test_unparseable_expiry_is_kept(self):
        # better to keep a pin than drop it on bad data (reaper/admin are backstops)
        self.assertFalse(MaintenanceEntry("r", "", "not-a-date").is_expired(
            datetime.now()))


class MaintenanceStoreTests(TestCase):
    def test_save_then_load_round_trips(self):
        with tempfile.TemporaryDirectory() as directory:
            store = MaintenanceStore(Path(directory) / "sub" / "maintenance.json")
            entries = {"db": MaintenanceEntry("planned", "2026-01-01T00:00:00",
                                              "2026-01-08T00:00:00", "ada")}
            store.save(entries)       # also creates the missing parent directory
            self.assertEqual(store.load(), entries)

    def test_missing_file_loads_empty(self):
        with tempfile.TemporaryDirectory() as directory:
            self.assertEqual(MaintenanceStore(Path(directory) / "nope.json").load(),
                             {})

    def test_corrupt_file_loads_empty(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "maintenance.json"
            path.write_text("{not valid json")
            self.assertEqual(MaintenanceStore(path).load(), {})

    def test_non_mapping_file_loads_empty(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "maintenance.json"
            path.write_text(json.dumps([1, 2, 3]))
            self.assertEqual(MaintenanceStore(path).load(), {})

    def test_save_replaces_atomically(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "maintenance.json"
            MaintenanceStore(path).save({})
            self.assertTrue(path.exists())
            self.assertEqual(list(Path(directory).glob("*.tmp")), [])  # tmp replaced


if __name__ == '__main__':
    unittest.main()
