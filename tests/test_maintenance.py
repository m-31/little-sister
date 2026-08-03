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


class BothDatesTests(TestCase):
    """`created_at` / `created_by` beside `set_at` / `set_by` (ADR-0014 amendment)."""

    def test_an_absent_creation_defaults_to_the_set(self):
        entry = MaintenanceEntry(reason="planned", set_at="2026-01-01T00:00:00",
                                 expires_at="2026-01-08T00:00:00", set_by="ada")
        self.assertEqual(entry.created_at, "2026-01-01T00:00:00")
        self.assertEqual(entry.created_by, "ada")

    def test_an_entry_without_the_creation_fields_reads_as_its_own_creation(self):
        # the shape an entry dict had before the amendment: it is still a valid
        # entry, and it means "pinned once, never edited"
        old = {"reason": "planned", "set_at": "2026-01-01T00:00:00",
               "expires_at": "2026-01-08T00:00:00", "set_by": "ada"}
        entry = MaintenanceEntry.from_dict(old)
        self.assertEqual(entry.reason, "planned")
        self.assertEqual(entry.created_at, "2026-01-01T00:00:00")
        self.assertEqual(entry.created_by, "ada")

    def test_an_edited_entry_keeps_both_apart(self):
        entry = MaintenanceEntry(reason="planned", set_at="2026-01-02T09:00:00",
                                 expires_at="2026-01-08T00:00:00", set_by="ben",
                                 created_at="2026-01-01T00:00:00",
                                 created_by="ada")
        self.assertEqual(MaintenanceEntry.from_dict(entry.to_dict()), entry)

    def test_same_pin_as_compares_reason_and_expiry_only(self):
        base = MaintenanceEntry("planned", "2026-01-01T00:00:00",
                                "2026-01-08T00:00:00", "ada")
        # a later write by someone else, saying the same thing, is a no-op
        same = MaintenanceEntry("planned", "2026-01-02T00:00:00",
                                "2026-01-08T00:00:00", "ben",
                                created_at="2026-01-01T00:00:00",
                                created_by="ada")
        self.assertTrue(base.same_pin_as(same))
        self.assertFalse(base.same_pin_as(
            MaintenanceEntry("planned", "2026-01-02T00:00:00",
                             "2026-01-09T00:00:00", "ben")))
        self.assertFalse(base.same_pin_as(
            MaintenanceEntry("other", "2026-01-02T00:00:00",
                             "2026-01-08T00:00:00", "ben")))



class EntryPinFileTests(TestCase):
    """The file's two tables, and the clean break with the shape it used to have
    (ADR-0036)."""

    def _store(self, directory):
        return MaintenanceStore(Path(directory) / "maintenance.json")

    def test_node_and_entry_pins_round_trip(self):
        with tempfile.TemporaryDirectory() as directory:
            store = self._store(directory)
            nodes = {"/db": MaintenanceEntry("planned", "2026-01-01T00:00:00",
                                             "2026-01-08T00:00:00", "ada")}
            pins = {("/wiz", "acme/pr-412"):
                    MaintenanceEntry("on it", "2026-01-02T00:00:00",
                                     "2026-01-09T00:00:00", "ben")}
            store.save(nodes, pins)
            self.assertEqual(store.load(), nodes)
            self.assertEqual(store.load_entries(), pins)

    def test_a_file_with_no_entry_pins_loads_an_empty_table(self):
        with tempfile.TemporaryDirectory() as directory:
            store = self._store(directory)
            store.save({"/db": MaintenanceEntry("planned", "2026-01-01T00:00:00",
                                                "2026-01-08T00:00:00")})
            self.assertEqual(store.load_entries(), {})

    def test_the_old_flat_shape_is_a_clean_break(self):
        # runtime state the program owns, every pin bounded by a finite expiry —
        # so the old shape is ignored rather than carried in the read path forever
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "maintenance.json"
            path.write_text(json.dumps({"/db": {"reason": "planned",
                                                "set_at": "2026-01-01T00:00:00",
                                                "expires_at": "2026-01-08T00:00:00",
                                                "set_by": "ada"}}))
            store = MaintenanceStore(path)
            self.assertEqual(store.load(), {})
            self.assertEqual(store.load_entries(), {})

    def test_a_slug_with_a_slash_survives_the_file(self):
        with tempfile.TemporaryDirectory() as directory:
            store = self._store(directory)
            key = ("/wiz", "acme/api-pr-412")
            store.save({}, {key: MaintenanceEntry("on it", "2026-01-02T00:00:00",
                                                  "2026-01-09T00:00:00")})
            self.assertIn(key, store.load_entries())

if __name__ == '__main__':
    unittest.main()
