import contextlib
import json
import tempfile
import unittest
from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path
from unittest import TestCase

from little_sister.codes import StatusCode
from little_sister.maintenance import RETIRED_PATH, MaintenanceEntry, MaintenanceStore
from little_sister.state import MAINTENANCE_FILE, StateLayer


def _utc(*moment: int) -> datetime:
    """An instant, by its date and its time in UTC."""
    return datetime(*moment, tzinfo=UTC)


class MaintenanceEntryTests(TestCase):
    def test_round_trips_through_dict(self):
        entry = MaintenanceEntry(reason="planned", set_at=_utc(2026, 1, 1),
                                 expires_at=_utc(2026, 1, 8), set_by="ada")
        self.assertEqual(MaintenanceEntry.from_dict(entry.to_dict()), entry)

    def test_is_expired_compares_to_now(self):
        now = _utc(2026, 6, 1, 12, 0, 0)
        past = MaintenanceEntry("r", now, now - timedelta(hours=1))
        future = MaintenanceEntry("r", now, now + timedelta(hours=1))
        self.assertTrue(past.is_expired(now))
        self.assertFalse(future.is_expired(now))
        # it is expired once now reaches the instant, and not a moment before
        self.assertTrue(future.is_expired(now + timedelta(hours=1)))
        self.assertFalse(future.is_expired(
            now + timedelta(hours=1) - timedelta(microseconds=1)))

    def test_is_expired_compares_instants_whatever_zone_they_were_built_in(self):
        now = _utc(2026, 6, 1, 12, 0, 0)
        ahead = timezone(timedelta(hours=9))
        # 21:30 nine hours ahead is 12:30Z: half an hour from now, not nine past
        entry = MaintenanceEntry("r", now, datetime(2026, 6, 1, 21, 30, tzinfo=ahead))
        self.assertFalse(entry.is_expired(now.astimezone(ahead)))
        self.assertTrue(entry.is_expired(datetime(2026, 6, 1, 21, 30, tzinfo=ahead)))


class MaintenanceStoreTests(TestCase):
    """The side-table as a state file (ADR-0071): read and written through the
    layer, under its directory, by the file's fixed name."""

    def test_save_then_load_round_trips(self):
        with tempfile.TemporaryDirectory() as directory:
            state = StateLayer(Path(directory) / "sub" / "state")
            store = MaintenanceStore(state)
            entries = {"db": MaintenanceEntry("planned", _utc(2026, 1, 1),
                                              _utc(2026, 1, 8), "ada")}
            store.save(entries)       # also creates the missing directory
            self.assertEqual(store.load(), entries)
            self.assertTrue((state.path(MAINTENANCE_FILE)).exists())

    def test_missing_file_loads_empty_and_reports_nothing(self):
        # a first start is not a failure
        with tempfile.TemporaryDirectory() as directory:
            state = StateLayer(directory)
            self.assertEqual(MaintenanceStore(state).load(), {})
            self.assertEqual(state.lines(), ())

    def test_corrupt_file_loads_empty_and_is_a_load_failure(self):
        with tempfile.TemporaryDirectory() as directory:
            state = StateLayer(directory)
            state.path(MAINTENANCE_FILE).write_text("{not valid json")
            with self.assertLogs(level="ERROR"):
                self.assertEqual(MaintenanceStore(state).load(), {})
            self.assertEqual([(line.slug, line.code) for line in state.lines()],
                             [(f"load.{MAINTENANCE_FILE}", StatusCode.ERROR)])

    def test_non_mapping_file_loads_empty_and_is_a_load_failure(self):
        with tempfile.TemporaryDirectory() as directory:
            state = StateLayer(directory)
            state.path(MAINTENANCE_FILE).write_text(json.dumps([1, 2, 3]))
            with self.assertLogs(level="ERROR"):
                self.assertEqual(MaintenanceStore(state).load(), {})
            self.assertEqual([line.slug for line in state.lines()],
                             [f"load.{MAINTENANCE_FILE}"])

    def test_tables_reads_a_payload_in_the_files_shape_for_an_adoption(self):
        # ADR-0077: the same reader the startup uses, on a payload the layer
        # hands over at a takeover, answering the two tables or refusing in the
        # words the startup read reports.
        entry = MaintenanceEntry("planned", _utc(2026, 1, 1),
                                 _utc(2026, 1, 8), "ada")
        with tempfile.TemporaryDirectory() as directory:
            state = StateLayer(directory)
            MaintenanceStore(state).save({"/db": entry}, {("/db", "slow"): entry})
            payload = state.read(MAINTENANCE_FILE)
        nodes, entry_pins = MaintenanceStore.tables(payload)
        self.assertEqual(nodes, {"/db": entry})
        self.assertEqual(entry_pins, {("/db", "slow"): entry})
        self.assertEqual(MaintenanceStore.tables({}), ({}, {}))
        with self.assertRaisesRegex(ValueError, "not a mapping"):
            MaintenanceStore.tables([1, 2, 3])
        with self.assertRaisesRegex(ValueError, "no 'nodes' table"):
            MaintenanceStore.tables({"/db": entry.to_dict()})

    def test_a_store_built_with_a_tree_registers_the_way_back_at_construction(self):
        # ADR-0077: the file's other direction is registered where its shape is
        # known — here — and hands the tables to the tree that holds the pins.
        from datetime import datetime, timedelta

        from little_sister.state import BACKUP_SUFFIX
        from little_sister.tree import StatusTree
        far = datetime.now(UTC) + timedelta(days=1)
        with tempfile.TemporaryDirectory() as directory:
            state = StateLayer(directory)
            tree = StatusTree()
            store = MaintenanceStore(state, tree=tree)
            tree.use_maintenance_store(store)
            store.save({})
            state.path(MAINTENANCE_FILE + BACKUP_SUFFIX).write_text(json.dumps({
                "nodes": {"/db": MaintenanceEntry("set aside", _utc(2026, 1, 1),
                                                  far, "ada").to_dict()},
                "entries": {}}))
            state.take_stock()
            state.take_backups()
            self.assertEqual(tree.maintenance_entry("/db").reason, "set aside")
        with tempfile.TemporaryDirectory() as directory:
            # without a tree there is nothing to hand the tables to: not registered
            state = StateLayer(directory)
            MaintenanceStore(state).save({})
            state.path(MAINTENANCE_FILE + BACKUP_SUFFIX).write_text("{}")
            state.take_stock()
            self.assertEqual(state.take_backups(), "no backup to take")

    def test_save_replaces_atomically(self):
        with tempfile.TemporaryDirectory() as directory:
            state = StateLayer(directory)
            MaintenanceStore(state).save({})
            self.assertTrue(state.path(MAINTENANCE_FILE).exists())
            self.assertEqual(list(Path(directory).glob("*.tmp")), [])  # tmp replaced

    def test_the_retired_path_is_named_once_at_startup(self):
        # The move from var/maintenance.json is a clean break: the old file is not
        # read, and a pin that quietly stopped being in force is the failure the
        # layer exists to prevent — so the file still sitting there is named.
        with (tempfile.TemporaryDirectory() as directory,
              contextlib.chdir(directory)):
            Path(RETIRED_PATH).parent.mkdir()
            Path(RETIRED_PATH).write_text(json.dumps({"nodes": {}, "entries": {}}))
            store = MaintenanceStore(StateLayer(Path(directory) / "var" / "state"))
            with self.assertLogs(level="WARNING") as captured:
                self.assertEqual(store.load_all(), ({}, {}))
            self.assertTrue(any(RETIRED_PATH in line and "no longer read" in line
                                for line in captured.output))

    def test_the_retired_path_is_not_named_once_the_new_file_exists(self):
        with (tempfile.TemporaryDirectory() as directory,
              contextlib.chdir(directory)):
            Path(RETIRED_PATH).parent.mkdir()
            Path(RETIRED_PATH).write_text("{}")
            store = MaintenanceStore(StateLayer(Path(directory) / "var" / "state"))
            store.save({})
            with self.assertNoLogs(level="WARNING"):
                store.load_all()


class BothDatesTests(TestCase):
    """`created_at` / `created_by` beside `set_at` / `set_by` (ADR-0014)."""

    def test_an_absent_creation_defaults_to_the_set(self):
        entry = MaintenanceEntry(reason="planned", set_at=_utc(2026, 1, 1),
                                 expires_at=_utc(2026, 1, 8), set_by="ada")
        self.assertEqual(entry.created_at, _utc(2026, 1, 1))
        self.assertEqual(entry.created_by, "ada")

    def test_an_entry_without_the_creation_fields_reads_as_its_own_creation(self):
        # the shape an entry dict had before the amendment: it is still a valid
        # entry, and it means "pinned once, never edited"
        old = {"reason": "planned", "set_at": "2026-01-01T00:00:00Z",
               "expires_at": "2026-01-08T00:00:00Z", "set_by": "ada"}
        entry = MaintenanceEntry.from_dict(old)
        self.assertEqual(entry.reason, "planned")
        self.assertEqual(entry.created_at, _utc(2026, 1, 1))
        self.assertEqual(entry.created_by, "ada")

    def test_an_edited_entry_keeps_both_apart(self):
        entry = MaintenanceEntry(reason="planned", set_at=_utc(2026, 1, 2, 9, 0),
                                 expires_at=_utc(2026, 1, 8), set_by="ben",
                                 created_at=_utc(2026, 1, 1),
                                 created_by="ada")
        self.assertEqual(MaintenanceEntry.from_dict(entry.to_dict()), entry)

    def test_same_pin_as_compares_reason_and_expiry_only(self):
        base = MaintenanceEntry("planned", _utc(2026, 1, 1),
                                _utc(2026, 1, 8), "ada")
        # a later write by someone else, saying the same thing, is a no-op
        same = MaintenanceEntry("planned", _utc(2026, 1, 2),
                                _utc(2026, 1, 8), "ben",
                                created_at=_utc(2026, 1, 1),
                                created_by="ada")
        self.assertTrue(base.same_pin_as(same))
        self.assertFalse(base.same_pin_as(
            MaintenanceEntry("planned", _utc(2026, 1, 2),
                             _utc(2026, 1, 9), "ben")))
        self.assertFalse(base.same_pin_as(
            MaintenanceEntry("other", _utc(2026, 1, 2),
                             _utc(2026, 1, 8), "ben")))



class EntryPinFileTests(TestCase):
    """The file's two tables, and the clean break with the shape it used to have
    (ADR-0036)."""

    def _store(self, directory):
        return MaintenanceStore(StateLayer(directory))

    def test_node_and_entry_pins_round_trip(self):
        with tempfile.TemporaryDirectory() as directory:
            store = self._store(directory)
            nodes = {"/db": MaintenanceEntry("planned", _utc(2026, 1, 1),
                                             _utc(2026, 1, 8), "ada")}
            pins = {("/wiz", "acme/pr-412"):
                    MaintenanceEntry("on it", _utc(2026, 1, 2),
                                     _utc(2026, 1, 9), "ben")}
            store.save(nodes, pins)
            self.assertEqual(store.load(), nodes)
            self.assertEqual(store.load_entries(), pins)

    def test_a_file_with_no_entry_pins_loads_an_empty_table(self):
        with tempfile.TemporaryDirectory() as directory:
            store = self._store(directory)
            store.save({"/db": MaintenanceEntry("planned", _utc(2026, 1, 1),
                                                _utc(2026, 1, 8))})
            self.assertEqual(store.load_entries(), {})

    def test_the_old_flat_shape_is_a_clean_break(self):
        # runtime state the program owns, every pin bounded by a finite expiry —
        # so the old shape is not read rather than carried in the read path
        # forever; what it held is not in force, and the layer says so (ADR-0071)
        with tempfile.TemporaryDirectory() as directory:
            state = StateLayer(directory)
            state.path(MAINTENANCE_FILE).write_text(json.dumps(
                {"/db": {"reason": "planned", "set_at": "2026-01-01T00:00:00",
                         "expires_at": "2026-01-08T00:00:00", "set_by": "ada"}}))
            store = MaintenanceStore(state)
            with self.assertLogs(level="ERROR"):
                self.assertEqual(store.load_all(), ({}, {}))
            (line,) = state.lines()
            self.assertEqual(line.slug, f"load.{MAINTENANCE_FILE}")
            self.assertIn("not in force", line.text)

    def test_a_slug_with_a_slash_survives_the_file(self):
        with tempfile.TemporaryDirectory() as directory:
            store = self._store(directory)
            key = ("/wiz", "acme/api-pr-412")
            store.save({}, {key: MaintenanceEntry("on it", _utc(2026, 1, 2),
                                                  _utc(2026, 1, 9))})
            self.assertIn(key, store.load_entries())

if __name__ == '__main__':
    unittest.main()
