"""A restart is no transition, and the instance's own node records the gap (ADR-0094).

A restart restores the event log and not the nodes. A node's first write after one is
compared with what the restored log last recorded for it, so the same reading keeps its
period and any other one — `UNDEFINED` included — changes from the old code; a pin the
log already holds writes nothing at its replay. `/little-sister` alone records the gap,
from when the old process was last alive to its first beat.
"""
from __future__ import annotations

import json
import tempfile
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest import TestCase

from little_sister import instants
from little_sister.codes import StatusCode
from little_sister.engine import Engine
from little_sister.state import EVENTS_FILE, StateLayer
from little_sister.status import HEARTBEAT_PATH
from little_sister.tree import (
    MAINTENANCE_RULE,
    Event,
    StatusTree,
    events_from_payload,
    last_alive,
    stopped_at_of,
)
from tests.state_files import on_disk

#: Yesterday, as a restored log dates it: every event restored below lies before
#: anything the restarted tree writes.
_BEFORE = (datetime.now(UTC) - timedelta(days=1)).replace(microsecond=0)


def _at(minutes: int) -> datetime:
    return _BEFORE + timedelta(minutes=minutes)


def _event(path: str, old: StatusCode, new: StatusCode, minutes: int, *,
           reason: tuple[str, ...] = (), suppressed_by: str = "") -> Event:
    return Event(path=path, name=path.rsplit("/", 1)[-1], old=old, new=new,
                 reason=reason, timestamp=_at(minutes), suppressed_by=suppressed_by)


def _restarted(*events: Event) -> StatusTree:
    tree = StatusTree()
    tree.restore_events(events)
    return tree


def _new(tree: StatusTree, count: int) -> list[Event]:
    """The last ``count`` events the tree holds — what the restart wrote."""
    return list(tree.recent_events())[-count:] if count else []


class FirstReadingTests(TestCase):
    """The first reading after a restart is compared with what the log last recorded
    (decision 1)."""

    def test_the_same_reading_keeps_its_period_across_the_restart(self) -> None:
        tree = _restarted(_event("/web", StatusCode.UNDEFINED, StatusCode.OK, 0))
        self.assertFalse(tree.upsert("/web", StatusCode.OK))
        self.assertEqual(len(tree.recent_events()), 1, "no event for the restart")
        period, = tree.history("/web")
        self.assertEqual((period.code, period.since), (StatusCode.OK, _at(0)))

    def test_a_first_reading_of_undefined_ends_the_restored_period(self) -> None:
        # the case that showed it: an `aws` root that declared OK declares nothing
        tree = _restarted(_event("/aws/account", StatusCode.UNDEFINED,
                                 StatusCode.OK, 0, reason=("scope: 1 account",)))
        self.assertTrue(tree.upsert("/aws/account", StatusCode.UNDEFINED,
                                    "scope: 1 account"))
        ok, undefined = tree.history("/aws/account")
        self.assertEqual((ok.code, ok.since), (StatusCode.OK, _at(0)))
        self.assertEqual(undefined.code, StatusCode.UNDEFINED)
        self.assertEqual(ok.until, undefined.since,
                         "the restored period ends where the reading said otherwise")

    def test_a_change_across_the_restart_transitions_from_the_old_code(self) -> None:
        tree = _restarted(_event("/db", StatusCode.UNDEFINED, StatusCode.OK, 0))
        self.assertTrue(tree.upsert("/db", StatusCode.ERROR, "down"))
        event, = _new(tree, 1)
        self.assertEqual((event.old, event.new), (StatusCode.OK, StatusCode.ERROR))
        self.assertEqual(event.suppressed_by, "", "not marked (decision 3)")

    def test_a_node_the_log_does_not_hold_reads_as_a_first_reading(self) -> None:
        tree = _restarted(_event("/web", StatusCode.UNDEFINED, StatusCode.OK, 0))
        self.assertTrue(tree.upsert("/db", StatusCode.OK))
        event, = _new(tree, 1)
        self.assertEqual((event.path, event.old), ("/db", StatusCode.UNDEFINED))

    def test_the_log_s_last_reading_is_the_one_compared(self) -> None:
        tree = _restarted(_event("/db", StatusCode.UNDEFINED, StatusCode.OK, 0),
                          _event("/db", StatusCode.OK, StatusCode.ERROR, 5),
                          _event("/web", StatusCode.UNDEFINED, StatusCode.OK, 6))
        self.assertFalse(tree.upsert("/db", StatusCode.ERROR, "down"))
        self.assertEqual([period.code for period in tree.history("/db")],
                         [StatusCode.OK, StatusCode.ERROR])

    def test_only_a_nodes_first_write_reads_the_restored_code(self) -> None:
        tree = _restarted(_event("/db", StatusCode.UNDEFINED, StatusCode.OK, 0))
        tree.upsert("/db", StatusCode.ERROR, "down")
        tree.upsert("/db", StatusCode.OK)
        self.assertEqual([(event.old, event.new) for event in _new(tree, 2)],
                         [(StatusCode.OK, StatusCode.ERROR),
                          (StatusCode.ERROR, StatusCode.OK)])

    def test_an_adopted_log_changes_nothing_for_a_written_node(self) -> None:
        # a log adopted in a running process arrives where the nodes are written
        tree = StatusTree()
        tree.upsert("/db", StatusCode.OK)
        tree.adopt_events({"events": [
            _event("/db", StatusCode.OK, StatusCode.ERROR, 0).to_dict()]})
        self.assertFalse(tree.upsert("/db", StatusCode.OK))


class PinReplayTests(TestCase):
    """A pin in force before the restart writes nothing at its replay (decision 2)."""

    def _pin(self, tree: StatusTree, path: str) -> None:
        entry_tree = StatusTree()
        entry_tree.set_maintenance(path, "planned",
                                   expires_at=datetime.now(UTC) + timedelta(days=1))
        entry = entry_tree.maintenance_entry(path)
        assert entry is not None
        tree.restore_maintenance({path: entry})

    def test_a_pin_the_log_holds_continues_its_period(self) -> None:
        tree = _restarted(
            _event("/db", StatusCode.UNDEFINED, StatusCode.OK, 0),
            _event("/db", StatusCode.OK, StatusCode.MAINTENANCE, 5,
                   reason=("planned",)))
        self._pin(tree, "/db")
        self.assertEqual(len(tree.recent_events()), 2, "the replay wrote nothing")
        self.assertFalse(tree.upsert("/db", StatusCode.OK),
                         "the reading under the pin was OK before and is OK now")
        self.assertEqual([period.code for period in tree.history("/db")],
                         [StatusCode.OK, StatusCode.MAINTENANCE])

    def test_a_change_under_a_replayed_pin_is_marked(self) -> None:
        tree = _restarted(
            _event("/db", StatusCode.UNDEFINED, StatusCode.OK, 0),
            _event("/db", StatusCode.OK, StatusCode.MAINTENANCE, 5))
        self._pin(tree, "/db")
        tree.upsert("/db", StatusCode.ERROR, "down")
        event, = _new(tree, 1)
        self.assertEqual((event.old, event.new), (StatusCode.OK, StatusCode.ERROR))
        self.assertEqual(event.suppressed_by, MAINTENANCE_RULE)

    def test_a_pin_the_log_no_longer_holds_records_its_set(self) -> None:
        tree = _restarted(_event("/db", StatusCode.UNDEFINED, StatusCode.OK, 0))
        self._pin(tree, "/db")
        event, = _new(tree, 1)
        self.assertEqual((event.old, event.new),
                         (StatusCode.OK, StatusCode.MAINTENANCE))


class GapTests(TestCase):
    """The instance's own node records the gap (decision 4)."""

    def test_the_instances_period_closes_when_it_was_last_alive(self) -> None:
        tree = _restarted(
            _event(HEARTBEAT_PATH, StatusCode.UNDEFINED, StatusCode.OK, 0))
        self.assertTrue(tree.close_unobserved(HEARTBEAT_PATH, _at(90),
                                              "the instance was not running"))
        tree.upsert(HEARTBEAT_PATH, StatusCode.OK)
        running, down, again = tree.history(HEARTBEAT_PATH)
        self.assertEqual((running.code, running.until), (StatusCode.OK, _at(90)))
        self.assertEqual((down.code, down.since, down.reason),
                         (StatusCode.UNDEFINED, _at(90),
                          ("the instance was not running",)))
        self.assertEqual(again.code, StatusCode.OK)
        self.assertEqual(down.until, again.since, "until its first beat")

    def test_nothing_is_closed_without_a_restored_reading(self) -> None:
        tree = StatusTree()
        self.assertFalse(tree.close_unobserved(HEARTBEAT_PATH, _at(90), "down"))
        self.assertEqual(tree.recent_events(), ())
        tree = _restarted(_event(HEARTBEAT_PATH, StatusCode.OK,
                                 StatusCode.UNDEFINED, 0))
        self.assertFalse(tree.close_unobserved(HEARTBEAT_PATH, _at(90), "down"))
        self.assertEqual(len(tree.recent_events()), 1)

    def test_only_the_node_named_is_closed(self) -> None:
        # the gap is said once: the heartbeat's children keep their periods
        engine_path = f"{HEARTBEAT_PATH}/engine"
        tree = _restarted(
            _event(HEARTBEAT_PATH, StatusCode.UNDEFINED, StatusCode.OK, 0),
            _event(engine_path, StatusCode.UNDEFINED, StatusCode.OK, 0))
        tree.close_unobserved(HEARTBEAT_PATH, _at(90), "down")
        self.assertFalse(tree.upsert(engine_path, StatusCode.OK))


class LastAliveTests(TestCase):
    """When the old process was last alive: the later of the stop's stamp and the
    lease's last beat (decision 4)."""

    def _beat(self, minutes: int) -> float:
        return (_BEFORE + timedelta(minutes=minutes)).timestamp()

    def test_the_later_of_the_two_wins(self) -> None:
        # a crash after a start leaves the stamp of an earlier stop behind, and the
        # lease's beat is later; a stop's stamp and its release are seconds apart
        self.assertEqual(last_alive(_at(90), self._beat(95)), _at(95))
        self.assertEqual(last_alive(_at(99), self._beat(95)), _at(99))

    def test_either_alone_dates_it_and_neither_does_not(self) -> None:
        self.assertEqual(last_alive(None, self._beat(95)), _at(95))
        self.assertEqual(last_alive(_at(90), None), _at(90))
        self.assertIsNone(last_alive(None, None))


class StopStampTests(TestCase):
    """The stop's one save stamps the log, and no other save does (decision 4)."""

    def test_the_log_carries_no_stamp_until_the_stop(self) -> None:
        tree = StatusTree()
        tree.upsert("/web", StatusCode.OK)
        self.assertNotIn("stopped_at", tree.events_payload())
        tree.note_stop(_at(90))
        payload = tree.events_payload()
        self.assertEqual(payload["stopped_at"], instants.stamp(_at(90)))
        self.assertEqual(stopped_at_of(json.loads(json.dumps(payload))), _at(90))
        # a reader that does not know the key passes over it
        self.assertEqual(len(events_from_payload(payload)), 1)

    def test_a_log_that_carries_no_stamp_says_none(self) -> None:
        payloads: list[object] = [{"events": []}, []]
        for payload in payloads:
            with self.subTest(payload=payload):
                self.assertIsNone(stopped_at_of(payload))

    def test_a_stamp_that_is_no_instant_refuses_the_log(self) -> None:
        # a time without a zone is the wall clock of whichever machine wrote it
        for stamp in (5, "yesterday", "2026-09-27T10:00:00", None):
            with self.subTest(stamp=stamp), self.assertRaises(ValueError):
                stopped_at_of({"events": [], "stopped_at": stamp})
        self.assertEqual(
            stopped_at_of({"events": [], "stopped_at": "2026-09-27T12:00:00+02:00"}),
            datetime(2026, 9, 27, 10, 0, tzinfo=UTC))

    def test_the_interval_skips_an_unchanged_log_and_the_stop_writes_it(
            self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            layer = StateLayer(Path(directory) / "state")
            tree = StatusTree()
            tree.upsert("/web", StatusCode.OK)
            layer.keep(EVENTS_FILE, tree.events_payload)
            layer.flush()
            written = on_disk(layer.path(EVENTS_FILE))
            layer.path(EVENTS_FILE).write_text("untouched")
            layer.flush()
            self.assertEqual(layer.path(EVENTS_FILE).read_text(), "untouched",
                             "an unchanged log is not written again")
            tree.note_stop(_at(90))
            layer.flush()
            stamped = on_disk(layer.path(EVENTS_FILE))
            self.assertEqual(stamped["stopped_at"], instants.stamp(_at(90)))
            self.assertEqual(stamped["events"], written["events"])

    def test_the_engines_stop_stamps_the_log_it_saves(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            layer = StateLayer(Path(directory) / "state")
            tree = StatusTree()
            engine = Engine([], tree, state=layer)
            layer.keep(EVENTS_FILE, tree.events_payload)
            before = datetime.now(UTC)
            engine.stop(trigger="the test")
            payload = on_disk(layer.path(EVENTS_FILE))
            stamp = datetime.fromisoformat(payload["stopped_at"])
            self.assertLessEqual(before, stamp)
            self.assertLessEqual(stamp, datetime.now(UTC))
