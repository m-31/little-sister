"""The pins and their file (ADR-0141): one pin with a kind, and ``pins.json``, which
took ``maintenance.json``'s place with a clean break."""
import json
import tempfile
import unittest
from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path
from unittest import TestCase, mock

from little_sister import self_report
from little_sister.codes import StatusCode
from little_sister.pins import (
    KINDS,
    MAINTENANCE,
    NO_NOTE,
    SEEN,
    Pin,
    PinStore,
    PinTables,
)
from little_sister.state import PINS_FILE, StateLayer


def _utc(*moment: int) -> datetime:
    """An instant, by its date and its time in UTC."""
    return datetime(*moment, tzinfo=UTC)


def _pin(note: str = "planned", by: str = "ada", **fields) -> Pin:
    return Pin(MAINTENANCE, note, _utc(2026, 1, 1), _utc(2026, 1, 8), by, **fields)


class PinTests(TestCase):
    def test_round_trips_through_dict(self):
        pin = Pin(MAINTENANCE, note="planned", set_at=_utc(2026, 1, 1),
                  expires_at=_utc(2026, 1, 8), set_by="ada")
        self.assertEqual(Pin.from_dict(pin.to_dict()), pin)

    def test_a_pin_is_of_a_kind_this_release_knows(self):
        self.assertEqual(KINDS, {MAINTENANCE, SEEN})
        self.assertEqual(_pin().kind, MAINTENANCE)
        with self.assertRaisesRegex(ValueError, "does not know"):
            Pin("snoozed", "r", _utc(2026, 1, 1), _utc(2026, 1, 8))

    def test_a_new_pin_is_given_an_id_and_an_edit_keeps_it(self):
        first, second = _pin(), _pin()
        self.assertRegex(first.id, "^[0-9a-f]{16}$")
        self.assertNotEqual(first.id, second.id)
        # an edit is a new pin built with the stored one's id, as its creation is
        edited = Pin(MAINTENANCE, "longer", _utc(2026, 1, 2), _utc(2026, 1, 9), "ben",
                     created_at=first.created_at, created_by=first.created_by,
                     id=first.id)
        self.assertEqual(edited.id, first.id)
        self.assertEqual(Pin.from_dict(edited.to_dict()).id, first.id)

    def test_a_pin_without_an_id_in_its_file_is_refused(self):
        raw = _pin().to_dict()
        del raw["id"]
        with self.assertRaisesRegex(ValueError, "without an id"):
            Pin.from_dict(raw)

    def test_is_expired_compares_to_now(self):
        now = _utc(2026, 6, 1, 12, 0, 0)
        past = Pin(MAINTENANCE, "r", now, now - timedelta(hours=1))
        future = Pin(MAINTENANCE, "r", now, now + timedelta(hours=1))
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
        pin = Pin(MAINTENANCE, "r", now, datetime(2026, 6, 1, 21, 30, tzinfo=ahead))
        self.assertFalse(pin.is_expired(now.astimezone(ahead)))
        self.assertTrue(pin.is_expired(datetime(2026, 6, 1, 21, 30, tzinfo=ahead)))


class PinStoreTests(TestCase):
    """The pins as a state file (ADR-0071): read and written through the layer,
    under its directory, by the file's fixed name."""

    def test_save_then_load_round_trips(self):
        with tempfile.TemporaryDirectory() as directory:
            state = StateLayer(Path(directory) / "sub" / "state")
            store = PinStore(state)
            pins = {"/db": _pin()}
            store.save(pins)       # also creates the missing directory
            self.assertEqual(store.load(), pins)
            self.assertTrue((state.path(PINS_FILE)).exists())

    def test_the_file_is_one_list_each_pin_beside_its_target(self):
        # the same pins are the same bytes: in the order of their targets
        with tempfile.TemporaryDirectory() as directory:
            state = StateLayer(directory)
            node, line = _pin(), _pin("on it", "ben")
            PinStore(state).save({"/zz": node, "/db": node}, {("/db", "slow"): line})
            written = json.loads(state.path(PINS_FILE).read_text())["pins"]
        self.assertEqual([(row["path"], row["slug"]) for row in written],
                         [("/db", ""), ("/db", "slow"), ("/zz", "")])
        self.assertEqual(written[1], {"path": "/db", "slug": "slow",
                                      **line.to_dict()})
        self.assertEqual(set(written[0]),
                         {"path", "slug", "id", "kind", "note", "set_at",
                          "expires_at", "set_by", "created_at", "created_by"})

    def test_missing_file_loads_empty_and_reports_nothing(self):
        # a first start is not a failure
        with tempfile.TemporaryDirectory() as directory:
            state = StateLayer(directory)
            self.assertEqual(PinStore(state).load(), {})
            self.assertEqual(state.lines(), ())

    def test_corrupt_file_loads_empty_and_is_a_load_failure(self):
        with tempfile.TemporaryDirectory() as directory:
            state = StateLayer(directory)
            state.path(PINS_FILE).write_text("{not valid json")
            with self.assertLogs(level="ERROR"):
                self.assertEqual(PinStore(state).load(), {})
            self.assertEqual([(line.slug, line.code) for line in state.lines()],
                             [(f"load.{PINS_FILE}", StatusCode.ERROR)])

    def test_non_mapping_file_loads_empty_and_is_a_load_failure(self):
        with tempfile.TemporaryDirectory() as directory:
            state = StateLayer(directory)
            state.path(PINS_FILE).write_text(json.dumps([1, 2, 3]))
            with self.assertLogs(level="ERROR"):
                self.assertEqual(PinStore(state).load(), {})
            self.assertEqual([line.slug for line in state.lines()],
                             [f"load.{PINS_FILE}"])

    def test_one_pin_it_cannot_take_refuses_every_pin_beside_it(self):
        # a time that is no instant, a path that is none, a pin without a kind,
        # two of one kind on one place: the file fails toward alarming, and the
        # layer says so — a pin without a kind is no pin of a kind it does not know
        good = {"path": "/db", "slug": "", **_pin().to_dict()}
        for bad, words in (
                (dict(good, path="/web", set_at="2026-01-01T00:00:00"), "set_at"),
                (dict(good, path="db"), "not one"),
                (dict(good, path="/web", kind=""), "without a kind"),
                ({key: value for key, value in good.items() if key != "kind"},
                 "without a kind"),
                (dict(good, note="again"), "two maintenance pins on /db")):
            with self.subTest(words), tempfile.TemporaryDirectory() as directory:
                state = StateLayer(directory)
                state.path(PINS_FILE).write_text(json.dumps({"pins": [good, bad]}))
                with self.assertLogs(level="ERROR"):
                    self.assertEqual(PinStore(state).load_all(),
                                     PinTables({}, {}, {}, {}))
                (line,) = state.lines()
                self.assertIn(words, line.text)

    def test_a_pin_of_a_kind_this_release_does_not_know_is_skipped_and_named(self):
        # ADR-0032 rule 7: an older standby adopting a newer holder's file keeps
        # every pin it understands, and says once what it did not take
        good = {"path": "/db", "slug": "", **_pin().to_dict()}
        newer = dict(good, path="/web", kind="snoozed", id="0123456789abcdef")
        self_report.startup.forget()
        self.addCleanup(self_report.startup.forget)
        with tempfile.TemporaryDirectory() as directory:
            state = StateLayer(directory)
            state.path(PINS_FILE).write_text(json.dumps({"pins": [good, newer]}))
            held = PinStore(state).load_all()
            self.assertEqual(list(held.nodes), ["/db"])
            self.assertEqual(held.lines, {})
            self.assertEqual(state.lines(), ())
        (said,) = [line.text for line in self_report.startup.lines()
                   if line.slug == "pins.unknown-kind"]
        self.assertIn("1 pin(s) of a kind this release does not know", said)

    def test_tables_reads_a_payload_in_the_files_shape_for_an_adoption(self):
        # ADR-0077: the same reader the startup uses, on a payload the layer
        # hands over at a takeover, answering the two tables — and how many pins
        # it skipped — or refusing in the words the startup read reports.
        pin = _pin()
        with tempfile.TemporaryDirectory() as directory:
            state = StateLayer(directory)
            PinStore(state).save({"/db": pin}, {("/db", "slow"): pin})
            payload = state.read(PINS_FILE)
        self.assertEqual(PinStore.tables(payload),
                         PinTables({"/db": pin}, {("/db", "slow"): pin}, {}, {}))
        self.assertEqual(PinStore.tables({}), PinTables({}, {}, {}, {}))
        with self.assertRaisesRegex(ValueError, "not a mapping"):
            PinStore.tables([1, 2, 3])
        # maintenance.json's own shape is not this file's
        with self.assertRaisesRegex(ValueError, "no 'pins' list"):
            PinStore.tables({"nodes": {"/db": pin.to_dict()}, "entries": {}})

    def test_a_store_built_with_a_tree_registers_the_way_back_at_construction(self):
        # ADR-0077: the file's other direction is registered where its shape is
        # known — here — and hands the tables to the tree that holds the pins.
        from little_sister.state import BACKUP_SUFFIX
        from little_sister.tree import StatusTree
        far = datetime.now(UTC) + timedelta(days=1)
        with tempfile.TemporaryDirectory() as directory:
            state = StateLayer(directory)
            tree = StatusTree()
            store = PinStore(state, tree=tree)
            tree.use_pin_store(store)
            store.save({})
            aside = Pin(MAINTENANCE, "set aside", _utc(2026, 1, 1), far, "ada")
            state.path(PINS_FILE + BACKUP_SUFFIX).write_text(json.dumps(
                {"pins": [{"path": "/db", "slug": "", **aside.to_dict()}]}))
            state.take_stock()
            state.take_backups()
            self.assertEqual(tree.maintenance_entry("/db").note, "set aside")
            self.assertEqual(tree.maintenance_entry("/db").id, aside.id)
        with tempfile.TemporaryDirectory() as directory:
            # without a tree there is nothing to hand the tables to: not registered
            state = StateLayer(directory)
            PinStore(state).save({})
            state.path(PINS_FILE + BACKUP_SUFFIX).write_text("{}")
            state.take_stock()
            self.assertEqual(state.take_backups(), "no backup to take")

    def test_save_replaces_atomically(self):
        with tempfile.TemporaryDirectory() as directory:
            state = StateLayer(directory)
            PinStore(state).save({})
            self.assertTrue(state.path(PINS_FILE).exists())
            self.assertEqual(list(Path(directory).glob("*.tmp")), [])  # tmp replaced


class RetiredFileTests(TestCase):
    """``maintenance.json`` is a clean break (ADR-0141 decision 1): it is not read,
    and the first start that finds it without ``pins.json`` says so once, on its
    ``load.`` slug, as a retired name of ADR-0134's is."""

    def _state(self, directory, *, with_pins: bool):
        old = {"nodes": {"/db": {"note": "planned"}}, "entries": {}}
        Path(directory, "maintenance.json").write_text(json.dumps(old))
        if with_pins:
            Path(directory, PINS_FILE).write_text(json.dumps({"pins": []}))
        return StateLayer(directory)

    def test_the_old_file_is_named_and_its_pins_are_not_in_force(self):
        with tempfile.TemporaryDirectory() as directory:
            state = self._state(directory, with_pins=False)
            with self.assertLogs(level="WARNING") as captured:
                state.take_stock()
            self.assertEqual(PinStore(state).load_all(), PinTables({}, {}, {}, {}))
            (line,) = [line for line in state.lines()
                       if line.slug == "load.maintenance.json"]
            self.assertEqual(line.code, StatusCode.WARN)
            self.assertIn("maintenance.json is no longer read", line.text)
            self.assertIn("pins.json (ADR-0141)", line.text)
            self.assertIn("until it is set again", line.text)
            self.assertTrue(any("no longer read" in said for said in captured.output))

    def test_the_old_file_is_not_named_once_pins_json_exists(self):
        with tempfile.TemporaryDirectory() as directory:
            state = self._state(directory, with_pins=True)
            with self.assertNoLogs(level="WARNING"):
                state.take_stock()
            self.assertEqual(state.lines(), ())


class BothDatesTests(TestCase):
    """`created_at` / `created_by` beside `set_at` / `set_by` (ADR-0014)."""

    def test_an_absent_creation_defaults_to_the_set(self):
        pin = _pin()
        self.assertEqual(pin.created_at, _utc(2026, 1, 1))
        self.assertEqual(pin.created_by, "ada")

    def test_a_pin_without_the_creation_fields_reads_as_its_own_creation(self):
        raw = {"id": "0123456789abcdef", "kind": MAINTENANCE, "note": "planned",
               "set_at": "2026-01-01T00:00:00Z",
               "expires_at": "2026-01-08T00:00:00Z", "set_by": "ada"}
        pin = Pin.from_dict(raw)
        self.assertEqual(pin.note, "planned")
        self.assertEqual(pin.created_at, _utc(2026, 1, 1))
        self.assertEqual(pin.created_by, "ada")

    def test_a_pin_without_a_note_holds_the_placeholder(self):
        raw = dict(_pin().to_dict(), note="")
        self.assertEqual(Pin.from_dict(raw).note, NO_NOTE)

    def test_an_edited_pin_keeps_both_apart(self):
        pin = Pin(MAINTENANCE, note="planned", set_at=_utc(2026, 1, 2, 9, 0),
                  expires_at=_utc(2026, 1, 8), set_by="ben",
                  created_at=_utc(2026, 1, 1), created_by="ada")
        self.assertEqual(Pin.from_dict(pin.to_dict()), pin)

    def test_same_pin_as_compares_note_and_expiry_only(self):
        base = _pin()
        # a later write by someone else, saying the same thing, is a no-op
        same = Pin(MAINTENANCE, "planned", _utc(2026, 1, 2), _utc(2026, 1, 8), "ben",
                   created_at=_utc(2026, 1, 1), created_by="ada")
        self.assertTrue(base.same_pin_as(same))
        self.assertFalse(base.same_pin_as(
            Pin(MAINTENANCE, "planned", _utc(2026, 1, 2), _utc(2026, 1, 9), "ben")))
        self.assertFalse(base.same_pin_as(
            Pin(MAINTENANCE, "other", _utc(2026, 1, 2), _utc(2026, 1, 8), "ben")))


class LinePinFileTests(TestCase):
    """A node's pins and its lines' in the one list (ADR-0036)."""

    def _store(self, directory):
        return PinStore(StateLayer(directory))

    def test_node_and_line_pins_round_trip(self):
        with tempfile.TemporaryDirectory() as directory:
            store = self._store(directory)
            nodes = {"/db": _pin()}
            lines = {("/wiz", "acme/pr-412"): _pin("on it", "ben")}
            store.save(nodes, lines)
            self.assertEqual(store.load(), nodes)
            self.assertEqual(store.load_entries(), lines)

    def test_a_file_with_no_line_pins_loads_an_empty_table(self):
        with tempfile.TemporaryDirectory() as directory:
            store = self._store(directory)
            store.save({"/db": _pin()})
            self.assertEqual(store.load_entries(), {})

    def test_a_slug_with_a_slash_survives_the_file(self):
        with tempfile.TemporaryDirectory() as directory:
            store = self._store(directory)
            key = ("/wiz", "acme/api-pr-412")
            store.save({}, {key: _pin("on it")})
            self.assertIn(key, store.load_entries())


class TreeIdTests(TestCase):
    """ADR-0141 decision 2 where the pins are held: an edit keeps a pin's id, as it
    keeps its creation, and a pin set again after a clear is a new one."""

    def test_an_edit_keeps_a_nodes_pin_id_and_a_pin_set_again_is_new(self):
        from little_sister.tree import StatusTree
        tree = StatusTree()
        tree.upsert("/db", StatusCode.ERROR, "down")
        until = datetime.now(UTC) + timedelta(days=1)
        tree.set_maintenance("/db", "planned", expires_at=until, set_by="ada")
        first = tree.maintenance_entry("/db")
        assert first is not None
        tree.set_maintenance("/db", "replanned", expires_at=until, set_by="bob")
        edited = tree.maintenance_entry("/db")
        assert edited is not None
        self.assertEqual((edited.note, edited.id), ("replanned", first.id))
        tree.clear_maintenance("/db")
        tree.set_maintenance("/db", "again", expires_at=until, set_by="ada")
        again = tree.maintenance_entry("/db")
        assert again is not None
        self.assertNotEqual(again.id, first.id)

    def test_an_edit_keeps_a_lines_pin_id_and_a_pin_set_again_is_new(self):
        from little_sister.reasons import Entry
        from little_sister.tree import StatusTree
        tree = StatusTree()
        tree.upsert("/ci", StatusCode.ERROR, [Entry("build", "build failed")],
                    members=True)
        until = datetime.now(UTC) + timedelta(days=1)
        tree.set_entry_maintenance("/ci", "build", "known", expires_at=until,
                                   set_by="ada")
        first = tree.entry_maintenance("/ci", "build")
        assert first is not None
        tree.set_entry_maintenance("/ci", "build", "still known", expires_at=until,
                                   set_by="bob")
        edited = tree.entry_maintenance("/ci", "build")
        assert edited is not None
        self.assertEqual((edited.note, edited.id), ("still known", first.id))
        tree.clear_entry_maintenance("/ci", "build")
        tree.set_entry_maintenance("/ci", "build", "again", expires_at=until,
                                   set_by="ada")
        again = tree.entry_maintenance("/ci", "build")
        assert again is not None
        self.assertNotEqual(again.id, first.id)


class NewIdTests(TestCase):
    def test_new_id_is_the_one_place_ids_are_made(self):
        with mock.patch("little_sister.pins.new_id", return_value="fixed0000000001"):
            self.assertEqual(_pin().id, "fixed0000000001")


if __name__ == '__main__':
    unittest.main()
