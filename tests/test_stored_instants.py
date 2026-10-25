"""Every stored time is an instant (ADR-0120).

The tests are written from the record's claims, with the values the claims are
about. A node's, an event's and a pin's times know their zone and are held in UTC;
a time without one cannot be built into any of them. Both state files spell a time
in UTC with a ``Z``, through the one function, and a file that carries a time
without a zone is refused whole — the log and the pins of the version before
included.

The first three classes are the three cases the wall clock used to decide: a state
that travels to a machine in another zone, the hour a clock repeats and the hour it
skips. Each runs on a machine set to a zone that is not the configured one, with
the clock held at instants either side of the change, and asks what a page, the
API and the tree then say.
"""
from __future__ import annotations

import json
import os
import tempfile
import time
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from typing import Any
from unittest import TestCase, mock, skipUnless
from zoneinfo import ZoneInfo

from little_sister import api, instants
from little_sister import app as app_module
from little_sister.keeper import forget_keeper, register_keeper
from little_sister.pins import MAINTENANCE as PIN_MAINTENANCE
from little_sister.pins import Pin, PinStore, PinTables
from little_sister.state import EVENTS_FILE, PINS_FILE, StateLayer
from little_sister.status import HEARTBEAT_PATH, Status, StatusCode
from little_sister.tree import (
    Beginning,
    Event,
    StatusTree,
    events_from_payload,
    last_alive,
    nodes_from_payload,
    stopped_at_of,
)
from tests.state_files import encoded, tables
from tests.test_keeper import _TakeoverStore

OK, ERROR = StatusCode.OK, StatusCode.ERROR
MAINTENANCE, UNDEFINED = StatusCode.MAINTENANCE, StatusCode.UNDEFINED

#: Two machines' zones, neither the one the tests' settings name for the pages
#: where it matters: a page is written in ``Europe/Berlin``.
NEW_YORK = "America/New_York"
BERLIN = "Europe/Berlin"

PATH = "/db"


@contextmanager
def _zone(name: str) -> Iterator[None]:
    """Run the block on a machine whose own clock is in the zone ``name``."""
    try:
        with mock.patch.dict(os.environ, {"TZ": name}):
            time.tzset()
            yield
    finally:
        time.tzset()          # back to whatever the real environment says


def _instant(spelled: str) -> datetime:
    return instants.instant(spelled, "a test's instant")


@contextmanager
def _at(spelled: str) -> Iterator[None]:
    """Hold the one clock at the instant ``spelled``."""
    with mock.patch.object(instants, "now", return_value=_instant(spelled)):
        yield


def _shown(value: Any) -> str:
    """A stored time as a page writes it: in the configured zone, which the tests'
    settings name as ``Europe/Berlin``."""
    return str(app_module._localtime(value))


class _Roots:
    """What the start asks an engine for: the roots its checks write to."""

    def __init__(self, *roots: str) -> None:
        self._roots = list(roots)

    def check_roots(self) -> list[str]:
        return self._roots


class _Started(TestCase):
    """A test that starts an instance on a directory of state: the application's
    own tree is a fresh one for it, as a new process's is."""

    def setUp(self) -> None:
        self._original = app_module.status_tree
        self.tree = StatusTree()
        app_module.status_tree = self.tree
        self.addCleanup(setattr, app_module, "status_tree", self._original)

    def start(self, directory: str) -> StateLayer:
        state = StateLayer(directory)
        app_module._restore_state(_Roots(PATH), state)  # type: ignore[arg-type]
        return state


def _rows(tree: StatusTree, path: str) -> list[str]:
    """When each event of ``path`` happened, as the Events page writes it."""
    return [_shown(event.timestamp) for event in tree.recent_events()
            if event.path == path]


@skipUnless(hasattr(time, "tzset"), "no tzset on this platform")
class TravelTests(_Started):
    """A state written on a machine in one zone and read on a machine in another
    reads as the same instants: its events, the gap its instance was not running,
    and its pins."""

    def _written(self, directory: str, zone: str) -> None:
        """One instance's state, written on a machine in ``zone``: a node that
        went red, a pin set on it at ``12:00Z`` for two hours, and the stop."""
        state = StateLayer(directory)
        with _zone(zone):
            tree = StatusTree()
            tree.use_pin_store(PinStore(state))
            with _at("2026-10-04T10:51:48Z"):
                tree.upsert(HEARTBEAT_PATH, OK)
                tree.upsert(PATH, OK)
            with _at("2026-10-04T11:00:00Z"):
                tree.upsert(PATH, ERROR, "down")
            with _at("2026-10-04T12:00:00Z"):
                tree.set_maintenance(
                    PATH, "planned", set_by="ada",
                    expires_at=app_module._maintenance_expiry("2h"))
            with _at("2026-10-04T12:10:00Z"):
                tree.note_stop()
            state.write(EVENTS_FILE, tree.events_payload())

    def test_an_event_reads_as_the_instant_it_was_written_at(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            self._written(directory, NEW_YORK)
            with _zone(BERLIN), _at("2026-10-04T12:30:00Z"):
                self.start(directory)
                self.assertEqual(_rows(self.tree, PATH),
                                 ["2026-10-04 12:51:48", "2026-10-04 13:00:00",
                                  "2026-10-04 14:00:00"])

    def test_the_gap_begins_when_the_instance_stopped(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            self._written(directory, NEW_YORK)
            with _zone(BERLIN), _at("2026-10-04T12:30:00Z"):
                self.start(directory)
                self.assertEqual(_rows(self.tree, HEARTBEAT_PATH),
                                 ["2026-10-04 12:51:48", "2026-10-04 14:10:00"])

    def test_a_pin_holds_for_as_long_as_it_was_set_for(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            self._written(directory, NEW_YORK)
            with _zone(BERLIN):
                with _at("2026-10-04T12:30:00Z"):
                    self.start(directory)
                    entry = self.tree.maintenance_entry(PATH)
                    assert entry is not None, "the pin was expired where it arrived"
                    self.assertEqual(api._pin(entry), {
                        "id": entry.id, "kind": "maintenance", "source": "person",
                        "note": "planned", "set_by": "ada",
                        "set_at": "2026-10-04T12:00:00Z",
                        "expires_at": "2026-10-04T14:00:00Z",
                        "created_by": "ada",
                        "created_at": "2026-10-04T12:00:00Z",
                        "counts_as": "nothing"})
                with _at("2026-10-04T13:59:59Z"):
                    self.assertEqual(self.tree.sweep_expired(), [])
                with _at("2026-10-04T14:00:00Z"):
                    self.assertEqual(self.tree.sweep_expired(), [PATH])

    def test_and_no_longer_the_other_way_round(self) -> None:
        # written six hours ahead of where it is read: the pin has run out at
        # 14:00Z, and does not hold until the reading machine's clock says 16:00
        with tempfile.TemporaryDirectory() as directory:
            self._written(directory, BERLIN)
            with _zone(NEW_YORK), _at("2026-10-04T14:00:01Z"):
                self.start(directory)
                self.assertIsNone(self.tree.maintenance_entry(PATH))


@skipUnless(hasattr(time, "tzset"), "no tzset on this platform")
class RepeatedHourTests(TestCase):
    """The hour a clock repeats — for ``America/New_York`` the one that ends at
    ``2026-11-01T06:00Z`` and begins again — is an hour like any other."""

    def setUp(self) -> None:
        self.tree = StatusTree()

    def test_a_nodes_age_is_the_time_since_it_was_observed(self) -> None:
        with _zone(NEW_YORK):
            with _at("2026-11-01T05:59:50Z"):          # 01:59:50, the first pass
                self.tree.upsert(PATH, OK, frequency_seconds=120)
            for now, age in (("2026-11-01T06:00:10Z", 20.0),     # 01:00:10
                             ("2026-11-01T06:58:50Z", 3540.0),   # 01:58:50
                             ("2026-11-01T07:00:10Z", 3620.0)):  # 02:00:10
                with self.subTest(now=now), _at(now):
                    node = self.tree.snapshot(PATH)
                    assert node is not None
                    self.assertEqual(node.age_seconds, age)

    def test_a_check_that_stopped_reporting_is_stale_within_that_hour(self) -> None:
        # every two minutes, so stale after four: noticed in the hour, not after it
        with _zone(NEW_YORK):
            with _at("2026-11-01T05:59:50Z"):
                self.tree.upsert(PATH, OK, frequency_seconds=120)
            with _at("2026-11-01T06:04:00Z"):
                node = self.tree.snapshot(PATH)
                assert node is not None
                self.assertTrue(node.stale)

    def test_an_event_of_the_second_pass_is_read_at_its_own_instant(self) -> None:
        with _zone(NEW_YORK):
            with _at("2026-11-01T05:30:00Z"):          # 01:30, the first pass
                self.tree.upsert(PATH, OK)
            with _at("2026-11-01T06:30:00Z"):          # 01:30, the second
                self.tree.upsert(PATH, ERROR, "down")
            kept = json.loads(json.dumps(self.tree.events_payload()))
            first, second = events_from_payload(kept)
            # an hour apart, and in the order they were written
            self.assertEqual([_shown(first.timestamp), _shown(second.timestamp)],
                             ["2026-11-01 06:30:00", "2026-11-01 07:30:00"])
            node = self.tree.snapshot(PATH)
            assert node is not None
            self.assertEqual(api.snapshot_to_dict(node)["run"]["observed_at"],
                             "2026-11-01T06:30:00Z")

    def test_a_pin_set_for_a_duration_ends_when_the_duration_has_passed(
            self) -> None:
        with _zone(NEW_YORK):
            self.tree.upsert(PATH, ERROR, "down")
            with _at("2026-11-01T05:50:00Z"):          # 01:50, the first pass
                self.tree.set_maintenance(
                    PATH, "planned",
                    expires_at=app_module._maintenance_expiry("30m"))
                entry = self.tree.maintenance_entry(PATH)
                assert entry is not None
                self.assertEqual(app_module._time_left(entry.expires_at),
                                 "30m left")
            for now in ("2026-11-01T05:50:01Z",        # 01:50:01
                        "2026-11-01T06:19:59Z"):       # 01:19:59, the second pass
                with self.subTest(now=now), _at(now):
                    self.assertEqual(self.tree.sweep_expired(), [])
                    self.assertIs(self.tree.effective(PATH), MAINTENANCE)
            with _at("2026-11-01T06:20:00Z"):
                self.assertEqual(self.tree.sweep_expired(), [PATH])


@skipUnless(hasattr(time, "tzset"), "no tzset on this platform")
class SkippedHourTests(TestCase):
    """The hour a clock skips — for ``America/New_York`` from ``2027-03-14T07:00Z``
    — adds nothing to a node's age and nothing to what is left of a pin."""

    def setUp(self) -> None:
        self.tree = StatusTree()

    def test_a_nodes_age_is_the_time_since_it_was_observed(self) -> None:
        with _zone(NEW_YORK):
            with _at("2027-03-14T06:59:50Z"):          # 01:59:50
                self.tree.upsert(PATH, OK, frequency_seconds=120)
            with _at("2027-03-14T07:00:10Z"):          # 03:00:10
                node = self.tree.snapshot(PATH)
                assert node is not None
                self.assertEqual(node.age_seconds, 20.0)
                self.assertFalse(node.stale)

    def test_what_is_left_of_a_pin_is_what_is_left(self) -> None:
        with _zone(NEW_YORK):
            self.tree.upsert(PATH, ERROR, "down")
            with _at("2027-03-14T06:50:00Z"):          # 01:50
                self.tree.set_maintenance(
                    PATH, "planned",
                    expires_at=app_module._maintenance_expiry("30m"))
                entry = self.tree.maintenance_entry(PATH)
                assert entry is not None
                # it ends at 03:20 on that clock, half an hour and not ninety
                # minutes after 01:50
                self.assertEqual(app_module._time_left(entry.expires_at),
                                 "30m left")
            with _at("2027-03-14T07:19:59Z"):
                self.assertEqual(self.tree.sweep_expired(), [])
            with _at("2027-03-14T07:20:00Z"):
                self.assertEqual(self.tree.sweep_expired(), [PATH])


#: An event log as the version before wrote it: every time the machine's wall
#: clock, without a zone.
OLD_LOG: dict[str, Any] = {
    "events": [
        {"cause": "reading", "name": "little-sister", "new": "OK",
         "old": "UNDEFINED", "path": "/little-sister", "reason": [],
         "reported": "OK", "suppressed_by": "",
         "timestamp": "2026-10-04T14:18:20.122985"},
        {"cause": "reading", "name": "db", "new": "OK", "old": "UNDEFINED",
         "path": "/db", "reason": [], "reported": "OK", "suppressed_by": "",
         "timestamp": "2026-10-04T14:18:20.123016"},
        {"cause": "reading", "name": "db", "new": "ERROR", "old": "OK",
         "path": "/db", "reason": ["down"], "reported": "ERROR",
         "suppressed_by": "", "timestamp": "2026-10-04T14:18:20.123071"},
        {"cause": "pin-set", "name": "db", "new": "MAINTENANCE", "old": "ERROR",
         "path": "/db", "reason": ["planned"], "reported": "ERROR",
         "suppressed_by": "", "timestamp": "2026-10-04T14:18:20.123086"},
    ],
    "nodes": {
        "/db": {"cause": "pin-set", "reported": "ERROR", "shows": "MAINTENANCE",
                "since": "2026-10-04T14:18:20.123086", "was": "ERROR"},
        "/little-sister": {"before": True, "reported": "OK", "shows": "OK",
                           "since": "2026-10-04T14:18:20.122985"},
    },
    "stopped_at": "2026-10-04T14:18:20.123392",
}

#: And its pins, a node's and a line's, each set for ten years — in
#: ``maintenance.json``, which this release does not read (ADR-0141).
OLD_PINS: dict[str, Any] = {
    "entries": {"/db": {"line": {
        "created_at": "2026-10-04T14:18:20.123255", "created_by": "ben",
        "expires_at": "2036-10-01T14:18:20.123254", "reason": "on it",
        "set_at": "2026-10-04T14:18:20.123255", "set_by": "ben"}}},
    "nodes": {"/db": {
        "created_at": "2026-10-04T14:18:20.123086", "created_by": "ada",
        "expires_at": "2036-10-01T14:18:20.123082", "reason": "planned",
        "set_at": "2026-10-04T14:18:20.123086", "set_by": "ada"}},
}


def _failures(state: StateLayer) -> list[tuple[str, StatusCode | None]]:
    """The load failures the layer reports on ``/little-sister/state``."""
    return [(line.slug, line.code) for line in state.lines()
            if line.slug.startswith("load.")]


class VersionBeforeTests(_Started):
    """A state file as the version before wrote it carries times without a zone.
    It is a load failure and an ERROR line on ``/little-sister/state``; that state
    starts empty, and nothing is migrated. Its pins were in ``maintenance.json``,
    which this release does not read at all (ADR-0141): a retired name, said once."""

    def _directory(self, directory: str, *, log: object = None,
                   pins: object = None) -> None:
        for name, payload in ((EVENTS_FILE, log), ("maintenance.json", pins)):
            if payload is not None:
                StateLayer(directory).path(name).write_bytes(encoded(name, payload))

    def test_its_event_log_is_a_load_failure_and_the_log_starts_empty(
            self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            self._directory(directory, log=OLD_LOG)
            with self.assertLogs(level="ERROR"):
                state = self.start(directory)
            self.assertEqual(_failures(state), [(f"load.{EVENTS_FILE}", ERROR)])
            self.assertEqual(self.tree.recent_events(), ())
            # nothing is kept of what a node last showed either, nor of when the
            # instance stopped: the first reading is a first reading
            self.assertEqual(self.tree.events_payload(),
                             {"events": [], "nodes": {}})
            # the first save rewrites the file: the old log is gone from the
            # directory
            self.assertEqual(state.read(EVENTS_FILE), OLD_LOG)
            state.flush()
            self.assertEqual(state.read(EVENTS_FILE), {"events": [], "nodes": {}})

    def test_its_pins_file_is_retired_and_no_pin_is_in_force(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            self._directory(directory, pins=OLD_PINS)
            with self.assertLogs(level="WARNING"):
                state = self.start(directory)
            self.assertEqual(_failures(state),
                             [("load.maintenance.json", StatusCode.WARN)])
            self.assertEqual(self.tree.pins(), ({}, {}))
            # the start writes the pins' own file, and leaves the old one be
            self.assertEqual(state.read(PINS_FILE), {"pins": []})
            self.assertTrue(state.path("maintenance.json").exists())

    def test_both_files_are_two_lines_and_the_start_is_not_refused(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            self._directory(directory, log=OLD_LOG, pins=OLD_PINS)
            with self.assertLogs(level="ERROR"):
                state = self.start(directory)
            self.assertEqual(sorted(_failures(state)),
                             [(f"load.{EVENTS_FILE}", ERROR),
                              ("load.maintenance.json", StatusCode.WARN)])
            self.assertEqual(self.tree.recent_events(), ())

    def test_the_line_names_the_time_it_could_not_take(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            self._directory(directory, log=OLD_LOG, pins=OLD_PINS)
            with self.assertLogs(level="ERROR"):
                state = self.start(directory)
            said = {line.slug: line.text for line in state.lines()}
            self.assertIn("an event's timestamp is not an instant with an offset",
                          said[f"load.{EVENTS_FILE}"])
            self.assertIn("maintenance.json is no longer read",
                          said["load.maintenance.json"])

    def test_a_takeover_from_a_holder_still_on_it_takes_neither_file(self) -> None:
        # an instance of this version stood by while a holder on the version before
        # wrote both files to the store, and then takes the lease
        store = _TakeoverStore()
        register_keeper("s3", store)
        self.addCleanup(forget_keeper)
        with tempfile.TemporaryDirectory() as directory:
            state = StateLayer(directory, interval_seconds=3600)
            app_module._restore_state(_Roots(PATH), state)  # type: ignore[arg-type]
            self.tree.upsert(PATH, ERROR, "down")
            self.tree.set_maintenance(
                PATH, "mine", expires_at=datetime.now(UTC) + timedelta(days=1))
            store.wanted = False
            state.flush()
            store.held.update({EVENTS_FILE: encoded(EVENTS_FILE, OLD_LOG),
                               PINS_FILE: encoded(PINS_FILE, OLD_PINS)})
            store.changed = [PINS_FILE, EVENTS_FILE]
            store.wanted = True
            with self.assertLogs(level="ERROR"):
                state.flush()
            said = {line.slug: line.text for line in state.lines()}
            for name in (EVENTS_FILE, PINS_FILE):
                with self.subTest(name=name):
                    self.assertIn("could not be adopted", said[f"load.{name}"])
                    self.assertIn("held out of the mirror", said[f"load.{name}"])
            # what the process holds stands, and none of it reaches the store
            entry = self.tree.maintenance_entry(PATH)
            assert entry is not None
            self.assertEqual(entry.note, "mine")
            self.assertEqual([event.new for event in self.tree.recent_events()],
                             [ERROR, MAINTENANCE])
            self.assertEqual(store.saved, [])
            self.assertEqual(tables(EVENTS_FILE, store.held[EVENTS_FILE]), OLD_LOG)
            # and the next interval fetches both and refuses them again
            self.tree.upsert(PATH, OK)
            with self.assertLogs(level="ERROR") as again:
                state.flush()
            refused = [line for line in again.output
                       if "could not be adopted" in line]
            self.assertEqual(len(refused), 2, again.output)
            self.assertEqual(store.saved, [])


#: One instant, and what a clock in Berlin showed at it with no zone to say whose
#: clock it was: 12:51:48.5.
SEEN = datetime(2026, 10, 4, 10, 51, 48, 500000, tzinfo=UTC)
SPELLED = "2026-10-04T10:51:48.500000Z"
BARE = SEEN.astimezone(ZoneInfo(BERLIN)).replace(tzinfo=None)
LATER = SEEN + timedelta(hours=2)


def _stop_the_clock_at(moment: datetime) -> Any:
    return mock.patch.object(instants, "now", return_value=moment)


def _a_log() -> dict[str, Any]:
    """A log as this version writes it, read back from its JSON: a node that went
    red and was pinned, and the stop."""
    tree = StatusTree()
    with _stop_the_clock_at(SEEN):
        tree.upsert(PATH, OK)
        tree.upsert(PATH, ERROR, "down")
        tree.set_maintenance(PATH, "planned", expires_at=LATER)
        tree.note_stop()
    kept: dict[str, Any] = json.loads(json.dumps(tree.events_payload()))
    return kept


def _pins_file(directory: str) -> dict[str, Any]:
    """A pins file as this version writes it: a node's pin and a line's."""
    state = StateLayer(directory)
    tree = StatusTree()
    tree.use_pin_store(PinStore(state))
    with _stop_the_clock_at(SEEN):
        tree.set_maintenance(PATH, "planned", expires_at=LATER, set_by="ada")
        tree.set_entry_maintenance(PATH, "line", "on it", expires_at=LATER,
                                   set_by="ben")
    kept: dict[str, Any] = state.read(PINS_FILE)
    return kept


def _row(pins: dict[str, Any], slug: str = "") -> dict[str, Any]:
    """The pin a pins file holds on ``PATH``, or on its line ``slug``."""
    return next(row for row in pins["pins"]
                if row["path"] == PATH and row["slug"] == slug)


class SpelledInTheFilesTests(TestCase):
    """Both state files carry every time in UTC, spelled by the one function."""

    def test_the_log_spells_an_events_a_nodes_and_the_stops_time(self) -> None:
        kept = _a_log()
        self.assertEqual([raw["timestamp"] for raw in kept["events"]],
                         [SPELLED, SPELLED, SPELLED])
        self.assertEqual(kept["nodes"][PATH]["since"], SPELLED)
        self.assertEqual(kept["stopped_at"], SPELLED)

    def test_the_pins_file_spells_a_pins_three_times(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            kept = _pins_file(directory)
        for raw in (_row(kept), _row(kept, "line")):
            with self.subTest(pin=raw["note"]):
                self.assertEqual(
                    (raw["set_at"], raw["created_at"], raw["expires_at"]),
                    (SPELLED, SPELLED, "2026-10-04T12:51:48.500000Z"))

    def test_both_files_spell_through_the_one_function(self) -> None:
        with tempfile.TemporaryDirectory() as directory, \
                mock.patch.object(instants, "stamp", return_value="spelled"):
            log, pins = _a_log(), _pins_file(directory)
        self.assertEqual({raw["timestamp"] for raw in log["events"]}, {"spelled"})
        self.assertEqual((log["nodes"][PATH]["since"], log["stopped_at"]),
                         ("spelled", "spelled"))
        self.assertEqual({_row(pins)[key]
                          for key in ("set_at", "created_at", "expires_at")},
                         {"spelled"})

    def test_what_is_read_back_is_the_instant_that_was_written(self) -> None:
        kept = _a_log()
        events = events_from_payload(kept)
        self.assertEqual([event.timestamp for event in events], [SEEN] * 3)
        nodes = nodes_from_payload(kept)
        assert nodes is not None
        began = nodes[PATH].began
        assert began is not None
        self.assertEqual(began.at, SEEN)
        self.assertEqual(stopped_at_of(kept), SEEN)
        with tempfile.TemporaryDirectory() as directory:
            node_pins, line_pins, *_rest = PinStore.tables(_pins_file(directory))
        for entry in (node_pins[PATH], line_pins[PATH, "line"]):
            self.assertEqual((entry.set_at, entry.created_at, entry.expires_at),
                             (SEEN, SEEN, LATER))

    def test_an_offset_other_than_utc_is_read_into_utc(self) -> None:
        # the same instant, spelled as a machine two hours ahead would
        kept = _a_log()
        kept["events"][0]["timestamp"] = "2026-10-04T12:51:48.500000+02:00"
        first = events_from_payload(kept)[0]
        self.assertEqual(first.timestamp, SEEN)
        self.assertIs(first.timestamp.tzinfo, UTC)


class OneTimeWithoutAZoneTests(_Started):
    """A file is refused whole over one time without a zone, wherever it stands:
    nothing of it is half-read."""

    WITHOUT = "2026-10-04T12:51:48.500000"

    def _each_place_in_the_log(self) -> Iterator[tuple[str, dict[str, Any]]]:
        log = _a_log()
        log["events"][1]["timestamp"] = self.WITHOUT
        yield "an event's timestamp", log
        log = _a_log()
        log["nodes"][PATH]["since"] = self.WITHOUT
        yield "a node's since", log
        log = _a_log()
        log["stopped_at"] = self.WITHOUT
        yield "the log's stopped_at", log

    def test_in_the_log_it_refuses_the_log(self) -> None:
        for where, log in self._each_place_in_the_log():
            with self.subTest(where=where), self.assertRaises(ValueError) as said:
                events_from_payload(log)
                nodes_from_payload(log)
                stopped_at_of(log)
            self.assertEqual(
                str(said.exception),
                f"{where} is not an instant with an offset: {self.WITHOUT!r}")

    def test_a_start_takes_nothing_of_such_a_log(self) -> None:
        for where, log in self._each_place_in_the_log():
            with self.subTest(where=where), \
                    tempfile.TemporaryDirectory() as directory:
                StateLayer(directory).write(EVENTS_FILE, log)
                self.tree = app_module.status_tree = StatusTree()
                with self.assertLogs(level="ERROR"):
                    state = self.start(directory)
                self.assertEqual(_failures(state),
                                 [(f"load.{EVENTS_FILE}", ERROR)])
                self.assertEqual(self.tree.events_payload(),
                                 {"events": [], "nodes": {}})

    def test_a_takeover_takes_nothing_of_such_a_log_either(self) -> None:
        for where, log in self._each_place_in_the_log():
            with self.subTest(where=where):
                tree = StatusTree()
                tree.upsert(PATH, OK)
                before = tree.events_payload()
                with self.assertRaises(ValueError):
                    tree.adopt_events(log)
                self.assertEqual(tree.events_payload(), before)

    def test_a_stop_stamp_that_is_no_time_refuses_the_log_too(self) -> None:
        for value in (1759575108, "yesterday", "", None):
            with self.subTest(value=value):
                log = _a_log()
                log["stopped_at"] = value
                with self.assertRaises(ValueError):
                    stopped_at_of(log)

    def test_a_log_that_says_no_stop_says_none(self) -> None:
        log = _a_log()
        del log["stopped_at"]
        self.assertIsNone(stopped_at_of(log))
        self.assertIsNone(stopped_at_of(["not", "a", "log"]))

    def test_in_the_pins_file_it_refuses_the_pins(self) -> None:
        for slug, key in (("", "set_at"), ("", "expires_at"), ("", "created_at"),
                          ("line", "set_at"), ("line", "expires_at"),
                          ("line", "created_at")):
            with self.subTest(slug=slug, key=key), \
                    tempfile.TemporaryDirectory() as directory:
                pins = _pins_file(directory)
                _row(pins, slug)[key] = self.WITHOUT
                with self.assertRaises(ValueError) as said:
                    PinStore.tables(pins)
                self.assertEqual(
                    str(said.exception),
                    f"a pin's {key} is not an instant with an offset: "
                    f"{self.WITHOUT!r}")
                state = StateLayer(directory)
                state.write(PINS_FILE, pins)
                with self.assertLogs(level="ERROR"):
                    self.assertEqual(PinStore(state).load_all(),
                                     PinTables({}, {}, {}, {}))
                self.assertEqual(_failures(state),
                                 [(f"load.{PINS_FILE}", ERROR)])

    def test_a_pin_that_says_no_creation_was_created_when_it_was_set(self) -> None:
        # an absent creation is the set, as for a pin built without one; it is a
        # time that is there and has no zone that refuses the file
        with tempfile.TemporaryDirectory() as directory:
            pins = _pins_file(directory)
        del _row(pins)["created_at"]
        del _row(pins)["created_by"]
        entry = PinStore.tables(pins)[0][PATH]
        self.assertEqual((entry.created_at, entry.created_by), (SEEN, "ada"))


class BuiltWithAZoneTests(TestCase):
    """An instant without a zone cannot be built: what holds one refuses it where
    it is made, and holds the instant in UTC."""

    def _event(self, timestamp: datetime) -> Event:
        return Event(path=PATH, name="db", old=OK, new=ERROR, reason=(),
                     timestamp=timestamp)

    def test_an_event_refuses_a_time_without_a_zone(self) -> None:
        with self.assertRaises(ValueError) as said:
            self._event(BARE)
        self.assertEqual(
            str(said.exception),
            "an event's timestamp is a time without a zone, and no instant: "
            "'2026-10-04T12:51:48.500000'")

    def test_a_beginning_refuses_one(self) -> None:
        with self.assertRaises(ValueError) as said:
            Beginning(BARE)
        self.assertIn("a period's beginning is a time without a zone",
                      str(said.exception))

    def test_a_pin_refuses_one_in_each_of_its_three_times(self) -> None:
        for where, times in (
                ("set_at", {"set_at": BARE, "expires_at": LATER}),
                ("expires_at", {"set_at": SEEN, "expires_at": BARE}),
                ("created_at", {"set_at": SEEN, "expires_at": LATER,
                                "created_at": BARE})):
            with self.subTest(where=where), self.assertRaises(ValueError) as said:
                Pin(PIN_MAINTENANCE, note="planned", **times)
            self.assertIn(f"a pin's {where} is a time without a zone",
                          str(said.exception))

    def test_each_holds_its_instant_in_utc(self) -> None:
        there = SEEN.astimezone(ZoneInfo("Asia/Kathmandu"))
        self.assertNotEqual(there.utcoffset(), timedelta(0))
        entry = Pin(PIN_MAINTENANCE, "planned", there, there, created_at=there)
        for held in (self._event(there).timestamp, Beginning(there).at,
                     entry.set_at, entry.expires_at, entry.created_at):
            self.assertEqual(held, SEEN)
            self.assertIs(held.tzinfo, UTC)

    def test_a_node_is_stamped_by_the_clock_alone(self) -> None:
        node = Status(PATH)
        self.assertIsNone(node.timestamp)
        with _stop_the_clock_at(SEEN):
            node.update(OK)
        self.assertEqual(node.timestamp, SEEN)
        with _stop_the_clock_at(LATER):
            node.touch()
        self.assertEqual(node.timestamp, LATER)

    def test_the_tree_dates_its_own_rows_by_the_clock(self) -> None:
        tree = StatusTree()
        tree.upsert(PATH, OK)
        tree.upsert(f"{PATH}/gone", OK)
        with _stop_the_clock_at(SEEN):
            tree.set_entry_maintenance(PATH, "line", expires_at=LATER)
            tree.set_maintenance(PATH, "planned", expires_at=LATER)
            tree.clear_maintenance(PATH)
            tree.prune(PATH, keep=())
            tree.note_stop()
        rows = [event for event in tree.recent_events()
                if event.cause != "reading"]
        self.assertEqual([event.cause for event in rows],
                         ["pin-set", "pin-ended", "removed"])
        self.assertEqual({event.timestamp for event in rows}, {SEEN})
        self.assertEqual(json.loads(json.dumps(tree.events_payload()))
                         ["stopped_at"], SPELLED)

    def test_a_moment_the_tree_is_asked_at_is_an_instant(self) -> None:
        tree = StatusTree()
        entry = Pin(PIN_MAINTENANCE, "planned", SEEN, LATER)
        for asked in (lambda: tree.snapshot("", now=BARE),
                      lambda: tree.sweep_expired(now=BARE),
                      lambda: tree.restore_maintenance({PATH: entry}, now=BARE),
                      lambda: tree.adopt_maintenance({PATH: entry}, now=BARE)):
            with self.assertRaises(ValueError) as said:
                asked()
            self.assertIn("is a time without a zone", str(said.exception))
        # and nothing was taken of what it was asked with
        self.assertEqual(tree.pins(), ({}, {}))

    def test_a_stop_and_a_gap_are_dated_by_instants(self) -> None:
        tree = StatusTree()
        for refused in (lambda: tree.note_stop(BARE),
                        lambda: tree.close_unobserved(PATH, BARE, "not running")):
            with self.assertRaises(ValueError):
                refused()

    def test_the_last_moment_alive_is_an_instant(self) -> None:
        beat = SEEN.timestamp()
        self.assertEqual(last_alive(None, beat), SEEN)
        self.assertEqual(last_alive(SEEN, (SEEN - timedelta(minutes=5)).timestamp()),
                         SEEN)
        self.assertEqual(last_alive(SEEN, LATER.timestamp()), LATER)
        self.assertIsNone(last_alive(None, None))
        alive = last_alive(None, beat)
        assert alive is not None
        self.assertIs(alive.tzinfo, UTC)


class TokenTests(TestCase):
    """A pin's ``set_at`` is also the token its form sends back, compared as it is
    spelled — and it is the same text before a restart and after."""

    def test_the_token_is_the_set_spelled(self) -> None:
        entry = Pin(PIN_MAINTENANCE, "planned", SEEN, LATER)
        self.assertEqual(entry.token, SPELLED)

    def test_a_write_that_names_the_token_is_taken_and_any_other_refused(
            self) -> None:
        tree = StatusTree()
        with _stop_the_clock_at(SEEN):
            first = tree.set_maintenance(PATH, "planned", expires_at=LATER,
                                         expected_set_at="")
        self.assertTrue(first.applied)
        for stale in ("", "2026-10-04T10:51:48Z", str(SEEN), SEEN.isoformat()):
            with self.subTest(token=stale):
                refused = tree.set_maintenance(PATH, "mine", expires_at=LATER,
                                               expected_set_at=stale)
                self.assertTrue(refused.refused)
        taken = tree.set_maintenance(PATH, "mine", expires_at=LATER,
                                     expected_set_at=SPELLED)
        self.assertTrue(taken.applied)

    def test_the_token_a_form_holds_survives_a_restart(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            pins = _pins_file(directory)
            node_pins, line_pins, *_rest = PinStore.tables(pins)
        tree = StatusTree()
        tree.restore_maintenance(node_pins, now=SEEN, entry_pins=line_pins)
        self.assertTrue(tree.clear_entry_maintenance(
            PATH, "line", expected_set_at=SPELLED).applied)
        self.assertTrue(tree.clear_maintenance(
            PATH, expected_set_at=SPELLED).applied)


@skipUnless(hasattr(time, "tzset"), "no tzset on this platform")
class EdgeTests(_Started):
    """A page, a copied document and a line of the log write an instant in the
    configured zone — ``Europe/Berlin`` in the tests' settings — and the machine's
    own clock has no say in it."""

    def test_an_instant_reads_alike_on_any_machines_clock(self) -> None:
        for zone in ("UTC", NEW_YORK, "Asia/Kathmandu"):
            with self.subTest(zone=zone), _zone(zone):
                self.assertEqual(app_module._localtime(SEEN), "2026-10-04 12:51:48")
                self.assertEqual(app_module._localtime(SEEN, "%H:%M"), "12:51")
                self.assertEqual(app_module._expiry_input(SEEN),
                                 "2026-10-04 12:51:48")
                self.assertEqual(app_module._copy_style().at(SEEN),
                                 "2026-10-04 12:51:48 +02:00")

    def test_how_long_is_left_is_measured_on_the_one_clock(self) -> None:
        with _zone(NEW_YORK), _at("2026-10-04T10:54:00Z"):
            self.assertEqual(app_module._time_left(LATER), "1h 57m left")

    def test_where_there_is_no_instant_each_says_so(self) -> None:
        self.assertEqual(app_module._localtime(None), "—")
        self.assertEqual(app_module._expiry_input(None), "")
        self.assertEqual(app_module._time_left(None), "expired")
        self.assertEqual(app_module._copy_style().at(None), "—")

    def test_the_start_says_in_the_log_since_when_nothing_watched(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            state = StateLayer(directory)
            tree = StatusTree()
            tree.upsert(HEARTBEAT_PATH, OK)
            tree.note_stop(SEEN)
            state.write(EVENTS_FILE, tree.events_payload())
            with _zone(NEW_YORK), self.assertLogs(level="INFO") as logged:
                self.start(directory)
        self.assertIn(
            "INFO:little_sister.logger:state: /little-sister was not running from "
            "2026-10-04 12:51:48 until this start", logged.output)


class RunFactsTests(TestCase):
    """What a run says of its next slot is an instant like the rest."""

    def test_the_next_slot_is_held_in_utc_and_refused_without_a_zone(self) -> None:
        tree = StatusTree()
        tree.set_check_mount(PATH)
        tree.upsert(PATH, OK)
        there = LATER.astimezone(ZoneInfo("Asia/Kathmandu"))
        tree.set_run_facts(PATH, wall_seconds=0.4, next_run_at=there)
        node = tree.snapshot(PATH)
        assert node is not None and node.run is not None
        due = node.run.next_run_at
        assert due is not None
        self.assertEqual(due, LATER)
        self.assertIs(due.tzinfo, UTC)
        self.assertEqual(api.snapshot_to_dict(node)["run"]["next_at"],
                         "2026-10-04T12:51:48.500000Z")
        with self.assertRaises(ValueError) as said:
            tree.set_run_facts(PATH, wall_seconds=0.4, next_run_at=BARE)
        self.assertIn("a run's next_run_at is a time without a zone",
                      str(said.exception))
        # a one-shot run arms no slot, and says none
        tree.set_run_facts(PATH, wall_seconds=0.4, next_run_at=None)
        node = tree.snapshot(PATH)
        assert node is not None and node.run is not None
        self.assertIsNone(node.run.next_run_at)
