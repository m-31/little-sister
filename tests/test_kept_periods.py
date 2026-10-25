"""An entry of the kept table says when its node's period began (ADR-0110 decision 5),
and what a period says of its beginning where the tree did not see it (ADR-0099
decisions 1, 9 and 10).

A period was read off the log's rows, and the log is bounded. Once the row that began
a node's period had left it, nothing said when the period began: the Time card read
*since before* the log's oldest event, a later instant with every row the log dropped.
And a node's first reading began its period, which is false of the row a restart wrote
for a node whose history had left the log — *ok since* the restart.

* The table beside the log keeps, for each node, when its period began and how: the
  instant, what the node showed before, and the cause. The surfaces read it where the
  log no longer holds the row.
* Where no beginning is known the entry keeps a bound, taken once and kept until the
  node changes.
* A first reading is a bound: the node was already what it shows when it was first
  seen. The instance's own branch begins with its process.
* No gap ends a period.
* A pin the tree did not see set — a start replays it, a store is adopted — begins at
  its creation, which the store keeps (decision 6); the row stays dated when it was
  written.
"""
from __future__ import annotations

import json
import os
import tempfile
from datetime import UTC, datetime, timedelta, timezone
from typing import Any
from unittest import TestCase

os.environ.setdefault("SECRET_KEY", "test-key")

from little_sister import app as app_module
from little_sister import instants
from little_sister import tree as tree_module
from little_sister.checks.base import Check, CheckResult, Measurement
from little_sister.copy_status import TimeStyle
from little_sister.engine import Engine
from little_sister.pins import MAINTENANCE as PIN_MAINTENANCE
from little_sister.pins import Pin, PinStore
from little_sister.reasons import Entry
from little_sister.state import EVENTS_FILE, StateLayer
from little_sister.status import HEARTBEAT_PATH, StatusCode
from little_sister.tree import (
    MAINTENANCE_RULE,
    Event,
    StatusPeriod,
    StatusTree,
    events_from_payload,
)
from tests.page_tree import Element, parse
from tests.test_branch_periods import as_before_the_key

OK, WARN, ERROR = StatusCode.OK, StatusCode.WARN, StatusCode.ERROR
MAINTENANCE, UNDEFINED = StatusCode.MAINTENANCE, StatusCode.UNDEFINED

PATH = "/site/probe"
BUSY = "/site/busy"

#: Yesterday, to the second: a kept file is written at instants a page shows apart,
#: where two writes of one test stand microseconds from each other.
_DAY = (datetime.now(UTC) - timedelta(days=1)).replace(microsecond=0)
_SOON = datetime.now(UTC) + timedelta(days=2)


def _at(minutes: int) -> datetime:
    return _DAY + timedelta(minutes=minutes)


def _spelled(minutes: int) -> str:
    """That instant as a kept file writes it."""
    return instants.stamp(_at(minutes))


def _row(path: str, old: StatusCode, new: StatusCode, minutes: int, *,
         cause: str = "reading", mark: str = "",
         reason: str = "") -> Event:
    """A row as a kept log holds one; ``cause=""`` is a log written before a row
    said what moved its node."""
    return Event(path=path, name=path.rsplit("/", 1)[-1], old=old, new=new,
                 reason=(reason,) if reason else (), timestamp=_at(minutes),
                 suppressed_by=mark, cause=cause)


def _file(*rows: Event, nodes: dict[str, dict[str, Any]] | None = None
          ) -> dict[str, Any]:
    """A kept file: its rows, and its table where it carries one."""
    payload: dict[str, Any] = {"events": [row.to_dict() for row in rows]}
    if nodes is not None:
        payload["nodes"] = nodes
    return payload


def _codes(shows: StatusCode, reported: StatusCode | None = None
           ) -> dict[str, Any]:
    """An entry as a tree wrote it before an entry said when a period began."""
    return {"shows": shows.name, "reported": (reported or shows).name}


def _kept(tree: StatusTree) -> dict[str, Any]:
    """What the tree writes to its file, through the file's own shape — its table as
    this record keeps it, without the period of what a branch shows, which is
    ADR-0132's and ``tests/test_branch_period_kept.py``'s
    (:func:`as_before_the_key`)."""
    kept: dict[str, Any] = json.loads(json.dumps(tree.events_payload()))
    kept["nodes"] = as_before_the_key(kept["nodes"])
    return kept


def _before_the_keys(payload: dict[str, Any]) -> dict[str, Any]:
    """The file as a tree wrote it when an entry held the two codes alone."""
    return {**payload, "nodes": {
        path: {key: entry[key] for key in ("shows", "reported")}
        for path, entry in payload["nodes"].items()}}


def _started(payload: dict[str, Any], *, size: int = 1000,
             own: str | None = None) -> StatusTree:
    """A new process on what the old one kept."""
    new = StatusTree(event_log_size=size)
    if own is not None:
        new.set_process_branch(own)
    events = events_from_payload(payload)
    if "nodes" in payload:
        new.restore_events(events, tree_module.nodes_from_payload(payload))
    else:
        new.restore_events(events)
    return new


def _flood(tree: StatusTree, rows: int = 8, path: str = BUSY) -> None:
    """Another node changing its mind often enough to push older rows out."""
    for index in range(rows):
        tree.upsert(path, ERROR if index % 2 else OK, f"reading {index}")


def _last_row(tree: StatusTree, path: str = PATH) -> Event:
    return [event for event in tree.recent_events() if event.path == path][-1]


def _rows_of(tree: StatusTree, path: str = PATH) -> list[Event]:
    return [event for event in tree.recent_events() if event.path == path]


def _current(tree: StatusTree, path: str = PATH) -> StatusPeriod:
    """The period the node is in."""
    return tree.history(path)[-1]


def _said(period: StatusPeriod) -> tuple[StatusCode, datetime, bool]:
    """What a surface states of a period: its status, its instant, and whether the
    instant is a bound."""
    return period.code, period.since, period.before


def _pin(note: str) -> Pin:
    """A pin as the store holds one."""
    tree = StatusTree()
    tree.set_maintenance("/any", note, expires_at=_SOON, set_by="lex")
    entry = tree.maintenance_entry("/any")
    assert entry is not None
    return entry


def _pin_from(minutes: int, note: str = "planned") -> Pin:
    """A pin as the store holds one that was set at ``minutes``, and not edited."""
    return Pin(PIN_MAINTENANCE, note=note, set_at=_at(minutes),
                            expires_at=_SOON, set_by="lex")


class WriteTests(TestCase):
    """The tree keeps a period's beginning as it writes, and it outlives the row."""

    def setUp(self) -> None:
        self.tree = StatusTree(event_log_size=4)

    def test_a_change_begins_a_period_at_its_row(self) -> None:
        self.tree.upsert(PATH, OK, "fine")
        self.tree.upsert(PATH, ERROR, "down")
        change = _last_row(self.tree)
        period = _current(self.tree)
        self.assertEqual(_said(period), (ERROR, change.timestamp, False))
        self.assertEqual((period.previous, period.cause), (OK, "reading"))

    def test_a_first_reading_is_a_bound(self) -> None:
        # the node was already ok when it was first seen
        self.tree.upsert(PATH, OK, "fine")
        first = _last_row(self.tree)
        self.assertEqual((first.old, first.new), (UNDEFINED, OK))
        self.assertEqual(_said(_current(self.tree)), (OK, first.timestamp, True))

    def test_a_first_reading_that_shows_nothing_begins_no_period(self) -> None:
        # there is no status to bound: the node says when it was observed
        self.tree.upsert(PATH, UNDEFINED)
        self.assertEqual(_rows_of(self.tree), [])
        self.assertEqual(self.tree.history(PATH), [])

    def test_a_node_that_begins_to_show_nothing_has_a_period(self) -> None:
        self.tree.upsert(PATH, OK, "fine")
        self.tree.upsert(PATH, UNDEFINED)
        change = _last_row(self.tree)
        _flood(self.tree)
        (period,) = self.tree.history(PATH)
        self.assertEqual(_said(period), (UNDEFINED, change.timestamp, False))
        self.assertEqual(period.previous, OK)

    def test_on_the_instances_own_branch_a_first_reading_is_a_beginning(
            self) -> None:
        # the instance's own node begins with its process: nothing of it was
        # there to be seen before
        self.tree.set_process_branch(HEARTBEAT_PATH)
        for path in (HEARTBEAT_PATH, f"{HEARTBEAT_PATH}/engine"):
            with self.subTest(path=path):
                self.tree.upsert(path, OK)
                period = _current(self.tree, path)
                self.assertEqual(
                    _said(period),
                    (OK, _last_row(self.tree, path).timestamp, False))
                self.assertEqual(period.previous, UNDEFINED)
        # and only there
        self.tree.upsert("/little-sisters/x", OK)
        self.assertTrue(_current(self.tree, "/little-sisters/x").before)

    def test_a_pin_begins_a_period_and_its_edit_none(self) -> None:
        self.tree.upsert(PATH, OK, "fine")
        self.tree.set_maintenance(PATH, "planed", expires_at=_SOON, set_by="lex")
        the_set = _last_row(self.tree)
        self.tree.set_maintenance(PATH, "planned", expires_at=_SOON, set_by="lex")
        period = _current(self.tree)
        self.assertEqual(_said(period), (MAINTENANCE, the_set.timestamp, False))
        self.assertEqual((period.previous, period.cause), (OK, "pin-set"))

    def test_a_pins_end_begins_one_that_says_what_went_before(self) -> None:
        self.tree.upsert(PATH, OK, "fine")
        self.tree.set_maintenance(PATH, "planned", expires_at=_SOON, set_by="lex")
        self.tree.clear_maintenance(PATH)
        period = _current(self.tree)
        self.assertEqual(_said(period),
                         (OK, _last_row(self.tree).timestamp, False))
        self.assertEqual((period.previous, period.cause),
                         (MAINTENANCE, "pin-ended"))

    def test_a_reading_the_node_does_not_show_begins_none(self) -> None:
        self.tree.upsert(PATH, OK, "fine")
        self.tree.set_maintenance(PATH, "planned", expires_at=_SOON, set_by="lex")
        the_set = _last_row(self.tree)
        self.tree.upsert(PATH, ERROR, "down")
        self.assertEqual(_last_row(self.tree).suppressed_by, MAINTENANCE_RULE)
        self.assertEqual(_said(_current(self.tree)),
                         (MAINTENANCE, the_set.timestamp, False))

    def test_a_pin_set_before_the_first_reading_keeps_its_beginning(
            self) -> None:
        # the reading beneath the pin is not shown, and bounds nothing
        self.tree.set_maintenance(PATH, "planned", expires_at=_SOON, set_by="lex")
        the_set = _last_row(self.tree)
        self.tree.upsert(PATH, OK, "fine")
        period = _current(self.tree)
        self.assertEqual(_said(period), (MAINTENANCE, the_set.timestamp, False))
        self.assertEqual((period.previous, period.cause),
                         (UNDEFINED, "pin-set"))

    def test_a_first_reading_after_a_pin_came_and_went_is_a_change(self) -> None:
        # something was kept of the node: the tree saw it show nothing, from the
        # pin's end, and then this
        self.tree.set_maintenance(PATH, "planned", expires_at=_SOON, set_by="lex")
        self.tree.clear_maintenance(PATH)
        self.tree.upsert(PATH, OK, "fine")
        period = _current(self.tree)
        self.assertEqual(_said(period),
                         (OK, _last_row(self.tree).timestamp, False))
        self.assertEqual(period.previous, UNDEFINED)

    def test_and_where_it_reads_nothing_the_pin_s_end_stands(self) -> None:
        self.tree.set_maintenance(PATH, "planned", expires_at=_SOON, set_by="lex")
        self.tree.clear_maintenance(PATH)
        the_end = _last_row(self.tree)
        self.tree.upsert(PATH, UNDEFINED)
        _flood(self.tree)
        (period,) = self.tree.history(PATH)
        self.assertEqual(_said(period), (UNDEFINED, the_end.timestamp, False))
        self.assertEqual((period.previous, period.cause),
                         (MAINTENANCE, "pin-ended"))

    def test_a_lines_pin_begins_one_where_it_changes_what_the_node_shows(
            self) -> None:
        lines = [Entry("build", "build: failed", code=ERROR),
                 Entry("tests", "tests: passed", code=OK)]
        self.tree.upsert(PATH, ERROR, lines, members=True)
        self.tree.set_entry_maintenance(PATH, "build", "known", expires_at=_SOON,
                                        set_by="lex")
        period = _current(self.tree)
        self.assertEqual(_said(period),
                         (OK, _last_row(self.tree).timestamp, False))
        self.assertEqual((period.previous, period.cause),
                         (ERROR, "line-pin-set"))

    def test_a_period_outlives_its_row(self) -> None:
        self.tree.upsert(PATH, OK, "fine")
        self.tree.upsert(PATH, ERROR, "down")
        change = _last_row(self.tree)
        _flood(self.tree)
        self.assertEqual(_rows_of(self.tree), [], "the log holds no row of it")
        (period,) = self.tree.history(PATH)
        self.assertEqual(_said(period), (ERROR, change.timestamp, False))
        self.assertEqual((period.previous, period.cause), (OK, "reading"))
        # what it says now is what the node says now
        self.assertEqual(period.reason, ("down",))
        node = self.tree.snapshot(PATH)
        assert node is not None
        self.assertEqual(period.until, node.timestamp)

    def test_a_pins_period_outlives_its_set(self) -> None:
        self.tree.upsert(PATH, OK, "fine")
        self.tree.set_maintenance(PATH, "planed", expires_at=_SOON, set_by="lex")
        the_set = _last_row(self.tree)
        _flood(self.tree, rows=3)
        self.tree.set_maintenance(PATH, "planned", expires_at=_SOON, set_by="lex")
        self.assertEqual([(row.old, row.new) for row in _rows_of(self.tree)],
                         [(MAINTENANCE, MAINTENANCE)],
                         "the edit is the node's oldest row")
        (period,) = self.tree.history(PATH)
        self.assertEqual(_said(period), (MAINTENANCE, the_set.timestamp, False))
        self.assertEqual((period.previous, period.cause), (OK, "pin-set"))
        self.assertEqual(period.reason, ("planned",))
        # and with no row of it left at all
        _flood(self.tree)
        (period,) = self.tree.history(PATH)
        self.assertEqual(_said(period), (MAINTENANCE, the_set.timestamp, False))

    def test_a_bound_outlives_its_row_and_does_not_move(self) -> None:
        self.tree.upsert(PATH, OK, "fine")
        first = _last_row(self.tree)
        _flood(self.tree)
        oldest = self.tree.recent_events()[0]
        self.assertGreater(oldest.timestamp, first.timestamp)
        (period,) = self.tree.history(PATH)
        self.assertEqual(_said(period), (OK, first.timestamp, True))

    def test_the_same_reading_again_moves_nothing(self) -> None:
        self.tree.upsert(PATH, OK, "fine")
        self.tree.upsert(PATH, ERROR, "down")
        change = _last_row(self.tree)
        for _ in range(3):
            self.tree.upsert(PATH, ERROR, "still down")
        self.assertEqual(_said(_current(self.tree)),
                         (ERROR, change.timestamp, False))

    def test_an_earlier_period_that_a_first_reading_began_says_before(
            self) -> None:
        tree = StatusTree()
        tree.upsert(PATH, OK, "fine")
        tree.upsert(PATH, ERROR, "down")
        tree.upsert(PATH, OK, "fine again")
        first, failure, current = tree.history(PATH)
        self.assertEqual([period.before for period in (first, failure, current)],
                         [True, False, False])

    def test_and_only_that_one(self) -> None:
        # a period out of an `UNDEFINED` the node showed is a change the tree saw,
        # also once it lies in the past
        tree = StatusTree()
        for code in (OK, UNDEFINED, OK, ERROR):
            tree.upsert(PATH, code)
        self.assertEqual([(period.code, period.before)
                          for period in tree.history(PATH)],
                         [(OK, True), (UNDEFINED, False), (OK, False),
                          (ERROR, False)])

    def test_a_node_first_seen_with_every_line_silenced_is_bounded_like_any(
            self) -> None:
        # what the node shows decides, not what its check reported
        self.tree.set_entry_maintenance(PATH, "build", "known", expires_at=_SOON,
                                        set_by="lex")
        self.tree.upsert(PATH, UNDEFINED,
                         [Entry("build", "build: no data", code=UNDEFINED)],
                         members=True)
        node = self.tree.snapshot(PATH)
        assert node is not None and node.timestamp is not None
        self.assertIs(node.own_code, MAINTENANCE)
        self.assertEqual(_kept(self.tree)["nodes"][PATH], {
            "shows": "MAINTENANCE", "reported": "UNDEFINED",
            "since": instants.stamp(node.timestamp), "before": True})

    def test_and_none_on_the_instances_own_branch(self) -> None:
        tree = StatusTree()
        tree.set_process_branch(HEARTBEAT_PATH)
        tree.upsert(HEARTBEAT_PATH, OK)
        tree.upsert(HEARTBEAT_PATH, WARN, "a tick came late")
        first, current = tree.history(HEARTBEAT_PATH)
        self.assertEqual((first.before, current.before), (False, False))


class TableTests(TestCase):
    """What the kept file says of a period, beside the two codes."""

    def test_an_entry_says_when_its_period_began_and_how(self) -> None:
        tree = StatusTree()
        tree.upsert(PATH, OK, "fine")
        tree.upsert(PATH, ERROR, "down")
        change = _last_row(tree)
        self.assertEqual(_kept(tree)["nodes"][PATH], {
            "shows": "ERROR", "reported": "ERROR",
            "since": instants.stamp(change.timestamp),
            "was": "OK", "cause": "reading"})

    def test_a_bound_says_since_and_before_and_nothing_of_how(self) -> None:
        tree = StatusTree()
        tree.upsert(PATH, OK, "fine")
        self.assertEqual(_kept(tree)["nodes"][PATH], {
            "shows": "OK", "reported": "OK",
            "since": instants.stamp(_last_row(tree).timestamp), "before": True})

    def test_a_pin_s_entry_says_its_set(self) -> None:
        tree = StatusTree()
        tree.upsert(PATH, WARN, "lagging")
        tree.set_maintenance(PATH, "planned", expires_at=_SOON, set_by="lex")
        the_set = _last_row(tree)
        tree.set_maintenance(PATH, "planned, a day more",
                             expires_at=_SOON + timedelta(days=1), set_by="lex")
        self.assertEqual(_kept(tree)["nodes"][PATH], {
            "shows": "MAINTENANCE", "reported": "WARN",
            "since": instants.stamp(the_set.timestamp), "was": "WARN",
            "cause": "pin-set"})

    def test_the_keys_are_read_back_as_they_were_written(self) -> None:
        read = tree_module.nodes_from_payload(_file(nodes={
            "/a": {**_codes(ERROR), "since": _spelled(3), "was": "OK",
                   "cause": "reading"},
            "/b": {**_codes(OK), "since": _spelled(1), "before": True},
            "/c": {**_codes(OK), "since": _spelled(2), "was": "MAINTENANCE"},
            "/d": _codes(WARN)}))
        assert read is not None
        began = tree_module.Beginning
        self.assertEqual({path: entry.began for path, entry in read.items()}, {
            "/a": began(_at(3), was=OK, cause="reading"),
            "/b": began(_at(1), before=True),
            "/c": began(_at(2), was=MAINTENANCE),
            "/d": None})
        self.assertEqual((read["/a"].shows, read["/a"].reported), (ERROR, ERROR))

    def test_a_table_of_another_shape_is_refused(self) -> None:
        entries: dict[str, dict[str, Any]] = {
            "a since that is no text": {"since": 5},
            "a since that is no time": {"since": "yesterday"},
            "a since without an offset": {"since": "2026-10-03T10:00:00"},
            "a before that is no flag": {"since": _spelled(1), "before": "yes"},
            "a was that is no code": {"since": _spelled(1), "was": "FINE"},
            "a cause that is no text": {"since": _spelled(1), "was": "OK", "cause": 7},
            "a was without a since": {"was": "OK"},
            "a cause without a since": {"cause": "reading"},
            "a before without a since": {"before": True},
            "a bound that says what was shown": {"since": _spelled(1), "before": True,
                                                 "was": "OK"},
            "a bound that says a cause": {"since": _spelled(1), "before": True,
                                          "cause": "reading"},
        }
        for what, keys in entries.items():
            with self.subTest(what), self.assertRaises(ValueError):
                tree_module.nodes_from_payload(
                    _file(nodes={PATH: {**_codes(OK), **keys}}))

    def test_a_node_that_shows_and_reported_nothing_has_no_entry_still(
            self) -> None:
        tree = StatusTree()
        tree.upsert(PATH, UNDEFINED)
        self.assertEqual(_kept(tree)["nodes"], {})

    def test_unless_the_tree_saw_it_begin_to_show_nothing(self) -> None:
        tree = StatusTree()
        tree.upsert(PATH, OK, "fine")
        tree.upsert(PATH, UNDEFINED)
        change = _last_row(tree)
        self.assertEqual(_kept(tree)["nodes"][PATH], {
            "shows": "UNDEFINED", "reported": "UNDEFINED",
            "since": instants.stamp(change.timestamp), "was": "OK", "cause": "reading"})

    def test_a_reading_that_changes_nothing_leaves_the_file_as_it_is(
            self) -> None:
        tree = StatusTree()
        tree.upsert(PATH, OK, "fine")
        tree.upsert(PATH, ERROR, "down")
        before = _kept(tree)
        tree.upsert(PATH, ERROR, "still down")
        self.assertEqual(_kept(tree), before)


class RestartTests(TestCase):
    """A restart carries a period's beginning, as it carries the two codes."""

    def _stopped(self) -> tuple[dict[str, Any], Event]:
        """A node that failed, and whose rows the log has dropped since."""
        old = StatusTree(event_log_size=4)
        old.upsert(PATH, OK, "fine")
        old.upsert(PATH, ERROR, "down")
        change = _last_row(old)
        _flood(old)
        self.assertEqual(_rows_of(old), [])
        return _kept(old), change

    def test_a_period_is_carried_across_a_restart_whose_log_lost_its_row(
            self) -> None:
        payload, change = self._stopped()
        new = _started(payload)
        self.assertFalse(new.upsert(PATH, ERROR, "down"))
        (period,) = new.history(PATH)
        self.assertEqual(_said(period), (ERROR, change.timestamp, False))
        self.assertEqual((period.previous, period.cause), (OK, "reading"))

    def test_a_bound_is_carried_unmoved(self) -> None:
        old = StatusTree(event_log_size=4)
        old.upsert(PATH, OK, "fine")
        first = _last_row(old)
        _flood(old)
        new = _started(_kept(old), size=4)
        self.assertFalse(new.upsert(PATH, OK, "fine"))
        _flood(new, path="/site/other")
        self.assertEqual(_said(_current(new)), (OK, first.timestamp, True))
        # and across the next restart too
        again = _started(_kept(new))
        again.upsert(PATH, OK, "fine")
        self.assertEqual(_said(_current(again)), (OK, first.timestamp, True))

    def test_a_node_no_check_has_written_yet_passes_its_keys_on(self) -> None:
        payload, _change = self._stopped()
        new = _started(payload)
        self.assertEqual(_kept(new)["nodes"][PATH], payload["nodes"][PATH])

    def test_a_node_not_read_yet_has_the_period_its_file_kept(self) -> None:
        payload, change = self._stopped()
        new = _started(payload)
        new.set_about(PATH, "Described, and not read yet.")
        (period,) = new.history(PATH)
        self.assertEqual(_said(period), (ERROR, change.timestamp, False))
        self.assertIsNone(period.until)

    def test_a_first_reading_that_changed_begins_a_period_then(self) -> None:
        payload, _change = self._stopped()
        new = _started(payload)
        self.assertTrue(new.upsert(PATH, OK, "fine again"))
        recovery = _last_row(new)
        period = _current(new)
        self.assertEqual(_said(period), (OK, recovery.timestamp, False))
        self.assertEqual(period.previous, ERROR)

    def test_a_node_nothing_is_kept_of_is_first_seen_by_the_new_process(
            self) -> None:
        payload, _change = self._stopped()
        new = _started(payload)
        new.upsert("/site/new", OK, "fine")
        self.assertEqual(
            _said(_current(new, "/site/new")),
            (OK, _last_row(new, "/site/new").timestamp, True))

    def test_the_instances_own_gap_begins_its_periods(self) -> None:
        new = _started(_file(
            _row(HEARTBEAT_PATH, UNDEFINED, OK, 0),
            nodes={HEARTBEAT_PATH: {**_codes(OK), "since": _spelled(0),
                                    "was": "UNDEFINED", "cause": "reading"}}),
            own=HEARTBEAT_PATH)
        self.assertTrue(new.close_unobserved(HEARTBEAT_PATH, _at(600),
                                             "the instance was not running"))
        self.assertEqual(_kept(new)["nodes"][HEARTBEAT_PATH], {
            "shows": "UNDEFINED", "reported": "UNDEFINED", "since": _spelled(600),
            "was": "OK"}, "the gap is a period the tree saw begin")
        new.upsert(HEARTBEAT_PATH, OK)
        ok, gap, current = new.history(HEARTBEAT_PATH)
        self.assertEqual(_said(ok), (OK, _at(0), False))
        self.assertEqual(_said(gap), (UNDEFINED, _at(600), False))
        self.assertEqual(_said(current),
                         (OK, _last_row(new, HEARTBEAT_PATH).timestamp, False))
        self.assertEqual(_kept(new)["nodes"][HEARTBEAT_PATH]["was"], "UNDEFINED")

    def test_a_node_that_showed_nothing_and_reads_again_changed_then(
            self) -> None:
        # an `UNDEFINED` the tree saw begin is a status it showed: the reading
        # that ends it is a change, also across a restart
        old = StatusTree()
        old.upsert(PATH, OK, "fine")
        old.upsert(PATH, UNDEFINED)
        new = _started(_kept(old))
        self.assertTrue(new.upsert(PATH, OK, "fine again"))
        period = _current(new)
        self.assertEqual(_said(period), (OK, _last_row(new).timestamp, False))
        self.assertEqual(period.previous, UNDEFINED)

    def test_a_replayed_pin_keeps_its_period(self) -> None:
        old = StatusTree(event_log_size=4)
        old.upsert(PATH, WARN, "lagging")
        old.set_maintenance(PATH, "planned", expires_at=_SOON, set_by="lex")
        the_set = _last_row(old)
        pin = old.maintenance_entry(PATH)
        assert pin is not None
        _flood(old)
        new = _started(_kept(old))
        new.restore_maintenance({PATH: pin})
        self.assertEqual(_rows_of(new), [], "a replay writes nothing")
        new.upsert(PATH, WARN, "lagging")
        self.assertEqual(_said(_current(new)),
                         (MAINTENANCE, the_set.timestamp, False))

    def test_a_pin_that_ran_out_meanwhile_begins_a_period_at_the_first_reading(
            self) -> None:
        old = StatusTree()
        old.upsert(PATH, OK, "fine")
        old.set_maintenance(PATH, "planned",
                            expires_at=datetime.now(UTC) + timedelta(seconds=30),
                            set_by="lex")
        pin = old.maintenance_entry(PATH)
        assert pin is not None
        new = _started(_kept(old))
        new.restore_maintenance({PATH: pin},
                                now=datetime.now(UTC) + timedelta(minutes=5))
        new.upsert(PATH, OK, "fine")
        period = _current(new)
        self.assertEqual(_said(period),
                         (OK, _last_row(new).timestamp, False))
        self.assertEqual((period.previous, period.cause),
                         (MAINTENANCE, "pin-ended"))

    def test_a_branch_s_pin_that_ran_out_meanwhile_ends_its_period_at_its_expiry(
            self) -> None:
        # nothing reports to the branch, so the restart writes its pin's end
        pin = _pin("kernel")
        new = _started(_file(
            _row("/hosts/a", UNDEFINED, MAINTENANCE, 4, cause="pin-set"),
            nodes={"/hosts/a": {**_codes(MAINTENANCE, UNDEFINED), "since": _spelled(4),
                                "was": "UNDEFINED", "cause": "pin-set"}}))
        new.restore_maintenance({"/hosts/a": pin},
                                now=datetime.now(UTC) + timedelta(days=3))
        self.assertEqual(_kept(new)["nodes"]["/hosts/a"], {
            "shows": "UNDEFINED", "reported": "UNDEFINED",
            "since": instants.stamp(pin.expires_at), "was": "MAINTENANCE",
            "cause": "pin-ended"})

    def test_forgetting_a_node_forgets_its_period(self) -> None:
        payload, _change = self._stopped()
        new = _started(payload)
        self.assertEqual(new.forget_uncovered(["/elsewhere"]), [BUSY, PATH])
        self.assertEqual(_kept(new)["nodes"], {})
        new.set_about(PATH, "Described, and not read yet.")
        self.assertEqual(new.history(PATH), [], "nothing is kept of it")
        new.upsert(PATH, ERROR, "down")
        self.assertTrue(_current(new).before, "and it is first seen then")


class OlderFileTests(TestCase):
    """A file written before an entry said when a period began is read by its rows,
    and where they hold no beginning the entry takes a bound and keeps it."""

    def test_the_rows_give_the_beginning_where_they_hold_it(self) -> None:
        new = _started(_file(
            _row(PATH, UNDEFINED, OK, 0), _row(PATH, OK, ERROR, 5),
            nodes={PATH: _codes(ERROR)}))
        new.upsert(PATH, ERROR, "down")
        period = _current(new)
        self.assertEqual(_said(period), (ERROR, _at(5), False))
        self.assertEqual((period.previous, period.cause), (OK, "reading"))

    def test_the_next_save_writes_the_keys(self) -> None:
        new = _started(_file(
            _row(PATH, UNDEFINED, OK, 0), _row(PATH, OK, ERROR, 5),
            nodes={PATH: _codes(ERROR)}))
        self.assertEqual(_kept(new)["nodes"][PATH], {
            **_codes(ERROR), "since": _spelled(5), "was": "OK", "cause": "reading"})

    def test_a_first_reading_s_row_is_read_as_a_bound(self) -> None:
        # the row a restart wrote for a node whose history had left the log, and
        # the row of a node that was new: the log does not tell them apart
        for cause in ("reading", ""):
            with self.subTest(cause=cause):
                new = _started(_file(_row(PATH, UNDEFINED, OK, 7, cause=cause),
                                     nodes={PATH: _codes(OK)}))
                new.upsert(PATH, OK, "fine")
                self.assertEqual(_said(_current(new)), (OK, _at(7), True))
                self.assertEqual(_kept(new)["nodes"][PATH], {
                    **_codes(OK), "since": _spelled(7), "before": True})

    def test_so_is_the_first_reading_of_a_check_that_reports_maintenance(
            self) -> None:
        # a reading wrote it, and its row says so: no admin's pin set
        new = _started(_file(_row(PATH, UNDEFINED, MAINTENANCE, 7),
                             nodes={PATH: _codes(MAINTENANCE)}))
        new.upsert(PATH, MAINTENANCE, "draining")
        self.assertEqual(_said(_current(new)), (MAINTENANCE, _at(7), True))

    def test_a_pin_s_set_is_its_beginning_whatever_edits_followed(self) -> None:
        new = _started(_file(
            _row(PATH, OK, MAINTENANCE, 5, cause="pin-set", reason="planed"),
            _row(PATH, MAINTENANCE, MAINTENANCE, 9, cause="pin-edited",
                 reason="planned"),
            nodes={PATH: _codes(MAINTENANCE, OK)}))
        self.assertEqual(_kept(new)["nodes"][PATH], {
            **_codes(MAINTENANCE, OK), "since": _spelled(5), "was": "OK",
            "cause": "pin-set"})

    def test_a_reading_a_pin_hid_begins_no_period_in_the_rows(self) -> None:
        # beneath its pin the check began to fail, and the pin's end showed it
        new = _started(_file(
            _row(PATH, OK, MAINTENANCE, 3, cause="pin-set", reason="planned"),
            _row(PATH, OK, ERROR, 5, mark=MAINTENANCE_RULE),
            _row(PATH, MAINTENANCE, ERROR, 8, cause="pin-ended"),
            nodes={PATH: _codes(ERROR)}))
        self.assertEqual(_kept(new)["nodes"][PATH], {
            **_codes(ERROR), "since": _spelled(8), "was": "MAINTENANCE",
            "cause": "pin-ended"})

    def test_a_change_out_of_an_undefined_the_log_saw_begin_is_exact(
            self) -> None:
        new = _started(_file(
            _row(PATH, OK, UNDEFINED, 3), _row(PATH, UNDEFINED, OK, 7),
            nodes={PATH: _codes(OK)}))
        new.upsert(PATH, OK, "fine")
        period = _current(new)
        self.assertEqual(_said(period), (OK, _at(7), False))
        self.assertEqual(period.previous, UNDEFINED)

    def test_a_pin_set_on_a_node_nothing_had_written_is_exact(self) -> None:
        for cause in ("pin-set", ""):
            with self.subTest(cause=cause):
                new = _started(_file(
                    _row("/hosts/a", UNDEFINED, MAINTENANCE, 4, cause=cause,
                         reason="kernel"),
                    nodes={"/hosts/a": _codes(MAINTENANCE, UNDEFINED)}))
                new.restore_maintenance({"/hosts/a": _pin("kernel")})
                # the branch is there again with the first node written beneath
                # it, pinned from that moment (ADR-0109 decision 4)
                new.upsert("/hosts/a/cpu", OK, "fine")
                (period,) = new.history("/hosts/a")
                self.assertEqual(_said(period), (MAINTENANCE, _at(4), False))

    def test_a_change_as_the_node_s_oldest_row_is_exact(self) -> None:
        # the first reading's row has left the log, and the change after it has not
        new = _started(_file(_row(PATH, OK, ERROR, 5), nodes={PATH: _codes(ERROR)}))
        new.upsert(PATH, ERROR, "down")
        period = _current(new)
        self.assertEqual(_said(period), (ERROR, _at(5), False))
        self.assertEqual(period.previous, OK)

    def test_a_node_that_shows_nothing_takes_no_bound(self) -> None:
        # beneath a pin whose set had left the log its check went on reporting;
        # the pin is gone, and the node reads nothing: there is no status to bound
        entry = {"shows": "UNDEFINED", "reported": "ERROR"}
        files = {"where the log holds rows": _file(_row(BUSY, OK, ERROR, 2),
                                                   nodes={PATH: entry}),
                 "where the log is empty": _file(nodes={PATH: entry})}
        for what, payload in files.items():
            with self.subTest(what):
                new = _started(payload)
                new.upsert(PATH, UNDEFINED)
                self.assertEqual(new.history(PATH), [])
                self.assertNotIn("since", _kept(new)["nodes"].get(PATH, {}))

    def test_an_edit_as_the_node_s_oldest_row_is_the_bound(self) -> None:
        new = _started(_file(
            _row(BUSY, UNDEFINED, OK, 0),
            _row(PATH, MAINTENANCE, MAINTENANCE, 9, cause="pin-edited",
                 reason="planned"),
            nodes={PATH: _codes(MAINTENANCE, OK), BUSY: _codes(OK)}))
        new.restore_maintenance({PATH: _pin("planned")})
        new.upsert(PATH, OK, "fine")
        self.assertEqual(_said(_current(new)), (MAINTENANCE, _at(9), True))
        self.assertEqual(_kept(new)["nodes"][PATH], {
            **_codes(MAINTENANCE, OK), "since": _spelled(9), "before": True})

    def test_without_a_row_the_entry_takes_the_log_s_oldest_event_and_keeps_it(
            self) -> None:
        new = _started(_file(
            _row(BUSY, OK, ERROR, 2), _row(BUSY, ERROR, OK, 6),
            nodes={PATH: _codes(OK), BUSY: _codes(OK)}), size=4)
        self.assertEqual(_kept(new)["nodes"][PATH], {
            **_codes(OK), "since": _spelled(2), "before": True},
            "taken where the tree first meets the node without a beginning")
        self.assertFalse(new.upsert(PATH, OK, "fine"))
        _flood(new, path="/site/other")
        self.assertGreater(new.recent_events()[0].timestamp, _at(6))
        self.assertEqual(_said(_current(new)), (OK, _at(2), True))
        self.assertEqual(_kept(new)["nodes"][PATH], {
            **_codes(OK), "since": _spelled(2), "before": True})

    def test_with_an_empty_log_the_bound_is_taken_at_the_first_write(
            self) -> None:
        new = _started(_file(nodes={PATH: _codes(OK), BUSY: _codes(OK)}))
        self.assertEqual(_kept(new)["nodes"][PATH], _codes(OK),
                         "nothing to bound it by yet")
        self.assertFalse(new.upsert(PATH, OK, "fine"))
        node = new.snapshot(PATH)
        assert node is not None and node.timestamp is not None
        self.assertEqual(_said(_current(new)), (OK, node.timestamp, True))
        # the first row written meanwhile is the log's oldest event, and bounds
        # the next
        new.upsert("/site/other", ERROR, "down")
        new.upsert("/site/other", OK, "up again")
        oldest, newest = new.recent_events()
        self.assertLess(oldest.timestamp, newest.timestamp)
        self.assertFalse(new.upsert(BUSY, OK, "fine"))
        self.assertEqual(_said(_current(new, BUSY)), (OK, oldest.timestamp, True))
        # and the first keeps what it took
        self.assertEqual(_current(new).since, node.timestamp)

    def test_a_file_written_before_the_table_is_read_the_same_way(self) -> None:
        new = _started(_file(
            _row(PATH, UNDEFINED, OK, 0, cause=""),
            _row("/site/db", UNDEFINED, OK, 1, cause=""),
            _row("/site/db", OK, ERROR, 5, cause="")))
        new.upsert(PATH, OK, "fine")
        new.upsert("/site/db", ERROR, "down")
        self.assertEqual(_said(_current(new)), (OK, _at(0), True))
        self.assertEqual(_said(_current(new, "/site/db")),
                         (ERROR, _at(5), False))
        first, _failure = new.history("/site/db")
        self.assertTrue(first.before, "History's oldest row of it says before")

    def test_on_the_instance_s_own_branch_such_a_row_is_a_beginning(
            self) -> None:
        new = _started(_file(_row(HEARTBEAT_PATH, UNDEFINED, OK, 0),
                             nodes={HEARTBEAT_PATH: _codes(OK)}),
                       own=HEARTBEAT_PATH)
        new.upsert(HEARTBEAT_PATH, OK)
        self.assertEqual(_said(_current(new, HEARTBEAT_PATH)),
                         (OK, _at(0), False))


class AdoptTests(TestCase):
    """A file adopted in a running process brings its periods for the nodes no check
    has written yet, and for one written already where it says the node shows what
    it shows (ADR-0077)."""

    def _adopted(self) -> dict[str, Any]:
        return _file(nodes={
            PATH: {**_codes(ERROR), "since": _spelled(3), "was": "OK",
                   "cause": "reading"},
            "/site/later": {**_codes(WARN), "since": _spelled(4), "was": "OK",
                            "cause": "reading"}})

    def test_a_node_no_check_has_written_takes_the_file_s_beginning(
            self) -> None:
        tree = StatusTree()
        tree.adopt_events(self._adopted())
        self.assertFalse(tree.upsert("/site/later", WARN, "slow"))
        self.assertEqual(_said(_current(tree, "/site/later")),
                         (WARN, _at(4), False))

    def test_so_does_one_that_is_described_and_not_read_yet(self) -> None:
        # the engine describes its nodes before their checks run
        tree = StatusTree()
        tree.set_about("/site/later", "Described, and not read yet.")
        tree.adopt_events(self._adopted())
        (period,) = tree.history("/site/later")
        self.assertEqual(_said(period), (WARN, _at(4), False))

    def test_a_written_node_the_file_agrees_with_takes_it_too(self) -> None:
        tree = StatusTree()
        tree.upsert(PATH, ERROR, "down")
        self.assertTrue(_current(tree).before, "first seen by this process")
        tree.adopt_events(self._adopted())
        self.assertEqual(_said(_current(tree)), (ERROR, _at(3), False))

    def test_a_written_node_the_file_disagrees_with_keeps_its_own(self) -> None:
        tree = StatusTree()
        tree.upsert(PATH, OK, "fine")
        mine = _current(tree)
        tree.adopt_events(self._adopted())
        self.assertEqual(_said(_current(tree)), _said(mine))
        self.assertEqual(_kept(tree)["nodes"][PATH]["shows"], "OK")

    def test_and_so_does_one_the_file_says_nothing_of_the_beginning_of(
            self) -> None:
        # the file agrees on what the node shows, and neither its entry nor its
        # log says when that began
        tree = StatusTree()
        tree.upsert(PATH, OK, "fine")
        tree.upsert(PATH, ERROR, "down")
        mine = _current(tree)
        tree.adopt_events(_file(nodes={PATH: _codes(ERROR)}))
        self.assertEqual(_current(tree), mine)

    def test_what_was_kept_of_a_node_not_written_yet_goes_with_its_file(
            self) -> None:
        tree = _started(self._adopted())
        tree.adopt_events(_file(nodes={PATH: {**_codes(ERROR), "since": _spelled(3),
                                              "was": "OK", "cause": "reading"}}))
        tree.set_about("/site/later", "Described, and not read yet.")
        self.assertEqual(tree.history("/site/later"), [])
        self.assertEqual(sorted(_kept(tree)["nodes"]), [PATH])

    def test_the_adopted_log_s_own_rows_are_read_as_they_were(self) -> None:
        # this process read the node ok since minute 0, the file's log says it
        # failed at minute 5 and its table that it shows that: what the adopted
        # rows say stands, and the node goes on from what this process saw
        tree = _started(_file(nodes={PATH: {**_codes(OK), "since": _spelled(0),
                                            "was": "WARN", "cause": "reading"}}))
        tree.upsert(PATH, OK, "fine")
        tree.adopt_events(_file(_row(PATH, OK, ERROR, 5),
                                nodes={PATH: {**_codes(ERROR), "since": _spelled(5),
                                              "was": "OK", "cause": "reading"}}))
        self.assertEqual(_said(_current(tree)), (ERROR, _at(5), False))
        self.assertEqual(_kept(tree)["nodes"][PATH], {
            **_codes(OK), "since": _spelled(0), "was": "WARN", "cause": "reading"})


class PinTests(TestCase):
    """A pin the tree did not see set begins at its creation, which the store keeps
    (ADR-0110 decision 6); the row a replay writes stays dated the start."""

    def test_a_pin_replayed_over_a_log_without_it_began_at_its_creation(
            self) -> None:
        new = _started(_file(nodes={}))
        new.restore_maintenance({PATH: _pin_from(3)})
        (row,) = _rows_of(new)
        self.assertEqual((row.old, row.new, row.cause),
                         (UNDEFINED, MAINTENANCE, "pin-set"))
        self.assertGreater(row.timestamp, _at(3), "the row is dated the start")
        new.upsert(PATH, OK, "fine")
        period = _current(new)
        self.assertEqual(_said(period), (MAINTENANCE, _at(3), False))
        self.assertEqual((period.previous, period.cause), (UNDEFINED, "pin-set"))

    def test_and_the_entry_carries_it(self) -> None:
        new = _started(_file(nodes={}))
        new.restore_maintenance({PATH: _pin_from(3)})
        self.assertEqual(_kept(new)["nodes"][PATH], {
            **_codes(MAINTENANCE, UNDEFINED), "since": _spelled(3), "was": "UNDEFINED",
            "cause": "pin-set"})
        # and the start after it reads that, and writes nothing
        again = _started(_kept(new))
        again.restore_maintenance({PATH: _pin_from(3)})
        self.assertEqual(_kept(again), _kept(new))

    def test_what_the_node_showed_until_then_ends_there(self) -> None:
        # a log older than the pin: it holds the node's failure, and not the pin
        new = _started(_file(
            _row(PATH, UNDEFINED, OK, 0), _row(PATH, OK, ERROR, 1),
            nodes={PATH: {**_codes(ERROR), "since": _spelled(1), "was": "OK",
                          "cause": "reading"}}))
        new.restore_maintenance({PATH: _pin_from(3)})
        replay = _last_row(new)
        self.assertEqual((replay.old, replay.new), (ERROR, MAINTENANCE))
        new.upsert(PATH, ERROR, "down")
        _first, failure, pinned = new.history(PATH)
        self.assertEqual((failure.code, failure.since, failure.until),
                         (ERROR, _at(1), _at(3)))
        self.assertEqual(_said(pinned), (MAINTENANCE, _at(3), False))
        self.assertEqual((pinned.previous, pinned.cause), (ERROR, "pin-set"))

    def test_a_kept_beginning_later_than_the_creation_is_corrected(self) -> None:
        # the date of an earlier replay, as a file says it by its rows or its entry
        row = _row(PATH, UNDEFINED, MAINTENANCE, 7, cause="pin-set",
                   reason="planned")
        files = {
            "a log written before a row said its cause": _file(
                _row(PATH, UNDEFINED, MAINTENANCE, 7, cause="", reason="planned")),
            "a table without the keys": _file(
                row, nodes={PATH: _codes(MAINTENANCE, UNDEFINED)}),
            "an entry that carries the replay's date": _file(nodes={PATH: {
                **_codes(MAINTENANCE, UNDEFINED), "since": _spelled(7),
                "was": "UNDEFINED", "cause": "pin-set"}}),
        }
        for what, payload in files.items():
            with self.subTest(what):
                new = _started(payload)
                rows = len(new.recent_events())
                new.restore_maintenance({PATH: _pin_from(3)})
                self.assertEqual(len(new.recent_events()), rows,
                                 "the replay writes nothing")
                # a replay makes no node (ADR-0109 decision 4): the period is
                # read once the node's check has written it
                new.upsert(PATH, OK, "fine")
                (period,) = new.history(PATH)
                self.assertEqual(_said(period), (MAINTENANCE, _at(3), False))
                self.assertEqual((period.previous, period.cause),
                                 (UNDEFINED, "pin-set"))

    def test_a_kept_bound_later_than_the_creation_gives_way_to_it(self) -> None:
        # the oldest edit the log held of the pin, where its set had left it
        new = _started(_file(nodes={PATH: {
            **_codes(MAINTENANCE, OK), "since": _spelled(9), "before": True}}))
        new.restore_maintenance({PATH: _pin_from(3)})
        self.assertEqual(_kept(new)["nodes"][PATH], {
            **_codes(MAINTENANCE, OK), "since": _spelled(3), "cause": "pin-set"})

    def test_a_pinned_node_whose_entry_says_no_beginning_takes_the_creation(
            self) -> None:
        new = _started(_file(nodes={PATH: _codes(MAINTENANCE, OK)}))
        self.assertNotIn("since", _kept(new)["nodes"][PATH])
        new.restore_maintenance({PATH: _pin_from(3)})
        self.assertEqual(_kept(new)["nodes"][PATH], {
            **_codes(MAINTENANCE, OK), "since": _spelled(3), "cause": "pin-set"})
        self.assertFalse(new.upsert(PATH, OK, "fine"))
        self.assertEqual(_said(_current(new)), (MAINTENANCE, _at(3), False))

    def test_what_began_no_later_than_the_pin_stands(self) -> None:
        # the node showed maintenance before it was pinned, or since its pin's set
        entries = {
            "a beginning the tree saw": {"since": _spelled(1), "was": "OK",
                                         "cause": "reading"},
            "a bound": {"since": _spelled(2), "before": True},
            "a bound at that very instant": {"since": _spelled(3), "before": True},
            "the pin's own set": {"since": _spelled(3), "was": "OK",
                                  "cause": "pin-set"},
        }
        for what, keys in entries.items():
            with self.subTest(what):
                entry = {**_codes(MAINTENANCE, MAINTENANCE), **keys}
                new = _started(_file(nodes={PATH: entry}))
                new.restore_maintenance({PATH: _pin_from(3)})
                self.assertEqual(_kept(new)["nodes"][PATH], entry)

    def test_a_pin_set_while_the_instance_runs_is_dated_as_the_store_dates_it(
            self) -> None:
        tree = StatusTree()
        tree.upsert(PATH, OK, "fine")
        tree.set_maintenance(PATH, "planed", expires_at=_SOON, set_by="lex")
        entry = tree.maintenance_entry(PATH)
        assert entry is not None
        self.assertEqual(_last_row(tree).timestamp, entry.created_at)
        tree.set_maintenance(PATH, "planned", expires_at=_SOON, set_by="lex")
        edited = tree.maintenance_entry(PATH)
        assert edited is not None
        self.assertEqual(edited.created_at, entry.created_at)
        self.assertEqual(_last_row(tree).timestamp, edited.set_at)
        self.assertGreater(edited.set_at, entry.set_at)
        self.assertEqual(_said(_current(tree)),
                         (MAINTENANCE, entry.created_at, False))

    def test_so_a_restart_leaves_its_entry_as_it_was(self) -> None:
        tree = StatusTree()
        tree.upsert(PATH, OK, "fine")
        tree.set_maintenance(PATH, "planned", expires_at=_SOON, set_by="lex")
        entry = tree.maintenance_entry(PATH)
        assert entry is not None
        kept = _kept(tree)
        new = _started(kept)
        new.restore_maintenance({PATH: entry})
        self.assertEqual(_kept(new), kept)

    def test_rows_that_say_otherwise_after_the_creation_stand(self) -> None:
        # a store and a log that do not belong together: the log saw the node
        # recover after the pin is said to have been created
        new = _started(_file(
            _row(PATH, ERROR, OK, 5),
            nodes={PATH: {**_codes(OK), "since": _spelled(5), "was": "ERROR",
                          "cause": "reading"}}))
        new.restore_maintenance({PATH: _pin_from(3)})
        replay = _last_row(new)
        new.upsert(PATH, OK, "fine")
        recovery, pinned = new.history(PATH)
        self.assertEqual((recovery.since, recovery.until),
                         (_at(5), replay.timestamp))
        self.assertEqual(_said(pinned), (MAINTENANCE, replay.timestamp, False))

    def test_and_which_came_first_is_asked_of_the_instants(self) -> None:
        # within one second too: the pin was created on the whole second, and the
        # node recovered half a second after it — which, as the two are spelled,
        # sorts before it
        half = _at(5) + timedelta(milliseconds=500)
        self.assertGreater(instants.stamp(_at(5)), instants.stamp(half))
        recovered = Event(path=PATH, name="probe", old=ERROR, new=OK, reason=(),
                          timestamp=half, cause="reading")
        new = _started(_file(recovered, nodes={PATH: {
            **_codes(OK), "since": instants.stamp(half), "was": "ERROR",
            "cause": "reading"}}))
        new.restore_maintenance({PATH: _pin_from(5)})
        replay = _last_row(new)
        new.upsert(PATH, OK, "fine")
        recovery, pinned = new.history(PATH)
        self.assertEqual((recovery.since, recovery.until),
                         (half, replay.timestamp))
        self.assertEqual(_said(pinned), (MAINTENANCE, replay.timestamp, False))

    def test_a_pin_created_at_the_instant_its_node_last_changed_ends_that_at_once(
            self) -> None:
        # the store says when a pin began, also where that leaves the period
        # before it no time at all
        new = _started(_file(
            _row(PATH, OK, ERROR, 3),
            nodes={PATH: {**_codes(ERROR), "since": _spelled(3), "was": "OK",
                          "cause": "reading"}}))
        new.restore_maintenance({PATH: _pin_from(3)})
        new.upsert(PATH, ERROR, "down")
        failure, pinned = new.history(PATH)
        self.assertEqual((failure.since, failure.until), (_at(3), _at(3)))
        self.assertEqual(_said(pinned), (MAINTENANCE, _at(3), False))

    def test_an_adopted_pin_began_at_its_creation_too(self) -> None:
        # a standby that read the node ok takes over: the holder's log holds the
        # pin's set, and its store the pin
        tree = StatusTree()
        tree.upsert(PATH, OK, "fine")
        tree.adopt_events(_file(
            _row(PATH, OK, MAINTENANCE, 3, cause="pin-set", reason="planned"),
            nodes={PATH: {**_codes(MAINTENANCE, OK), "since": _spelled(3),
                          "was": "OK", "cause": "pin-set"}}))
        tree.adopt_maintenance({PATH: _pin_from(3)})
        adoption = _last_row(tree)
        self.assertEqual((adoption.old, adoption.new, adoption.cause),
                         (OK, MAINTENANCE, "pin-set"))
        self.assertGreater(adoption.timestamp, _at(3))
        self.assertEqual(_said(_current(tree)), (MAINTENANCE, _at(3), False))

    def test_and_one_adopted_before_its_node_is_read(self) -> None:
        # the pin is held against the path, and dates the period of the node
        # its check then writes (ADR-0109 decision 4)
        tree = StatusTree()
        tree.adopt_maintenance({PATH: _pin_from(3)})
        self.assertIsNone(tree.snapshot(PATH))
        tree.upsert(PATH, OK, "fine")
        (period,) = tree.history(PATH)
        self.assertEqual(_said(period), (MAINTENANCE, _at(3), False))

    def test_a_pin_the_process_holds_already_is_not_dated_again(self) -> None:
        tree = StatusTree()
        tree.upsert(PATH, OK, "fine")
        tree.set_maintenance(PATH, "planed", expires_at=_SOON, set_by="lex")
        mine = tree.maintenance_entry(PATH)
        assert mine is not None
        began = _current(tree)
        # the store's copy was edited elsewhere, and says an older creation
        tree.adopt_maintenance({PATH: Pin(PIN_MAINTENANCE,
            note="planned", set_at=_at(8), expires_at=mine.expires_at,
            set_by="ada", created_at=_at(3), created_by="ada")})
        self.assertEqual(_last_row(tree).cause, "pin-edited")
        self.assertEqual(_said(_current(tree)), _said(began))
        self.assertEqual(_kept(tree)["nodes"][PATH]["since"],
                         instants.stamp(began.since))

    def test_a_creation_written_another_way_is_kept_as_the_tree_writes_one(
            self) -> None:
        # a store's file that spells the instant with a space and an offset of
        # its own names the same instant, and the kept log spells it its one way
        there = _at(3).astimezone(timezone(timedelta(hours=2)))
        new = _started(_file(nodes={}))
        new.restore_maintenance({PATH: Pin.from_dict({
            "id": "0123456789abcdef", "kind": "maintenance",
            "note": "planned", "set_at": there.isoformat(sep=" "),
            "expires_at": instants.stamp(_SOON), "set_by": "lex"})})
        self.assertEqual(_kept(new)["nodes"][PATH]["since"], _spelled(3))

    def test_a_pin_the_tree_sees_set_dates_nothing_it_did_not_begin(self) -> None:
        # the node's check reported maintenance, in a file that kept no beginning
        # of it, and an admin pins it before it is read: the pin began no period
        new = _started(_file(nodes={PATH: _codes(MAINTENANCE, MAINTENANCE)}))
        new.set_maintenance(PATH, "planned", expires_at=_SOON, set_by="lex")
        self.assertEqual(_last_row(new).cause, "pin-set")
        self.assertNotIn("since", _kept(new)["nodes"][PATH])

    def test_a_line_s_pin_dates_nothing(self) -> None:
        # what a node shows with its lines silenced is its reading's to say
        new = _started(_file(nodes={}))
        new.restore_maintenance({}, entry_pins={(PATH, "build"): _pin_from(3)})
        new.upsert(PATH, UNDEFINED,
                   [Entry("build", "build: no data", code=UNDEFINED)],
                   members=True)
        node = new.snapshot(PATH)
        assert node is not None and node.timestamp is not None
        self.assertEqual(_said(_current(new)),
                         (MAINTENANCE, node.timestamp, True))


class _Pages(TestCase):
    """The pages over a tree."""

    def setUp(self) -> None:
        app_module.app.config["TESTING"] = True
        self._saved = app_module.status_tree
        self.addCleanup(self._restore)
        self.client = app_module.app.test_client()
        self.client.post("/login",
                         data={"username": "pan", "password": "12345678"})

    def _restore(self) -> None:
        app_module.status_tree = self._saved

    def _serve(self, tree: StatusTree) -> StatusTree:
        app_module.status_tree = tree
        return tree

    def _page(self, url: str) -> Element:
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200, url)
        return parse(response.get_data(as_text=True))

    @staticmethod
    def _shown(instant: str) -> str:
        """An instant as a page writes it."""
        return str(app_module.app.jinja_env.filters["localtime"](instant))

    def _period(self, url: str) -> str:
        """The Time card's sentence about the status that holds."""
        for paragraph in self._page(url).all(tag="p"):
            text = paragraph.text()
            if text.startswith("Status "):
                return text
        self.fail(f"no period on {url}")

    def _history(self, url: str) -> list[list[str]]:
        table = self._page(url).all(tag="table")[0]
        return [[cell.text() for cell in row.all(tag="td")]
                for row in table.one(tag="tbody").all(tag="tr")]


class PageTests(_Pages):
    """The Time card, History and the Copy document read the kept beginning."""

    def _quiet(self) -> StatusTree:
        """A node that failed at minute 5 and whose rows the log has dropped."""
        tree = _started(_file(
            _row(BUSY, OK, ERROR, 30), _row(BUSY, ERROR, OK, 40),
            nodes={PATH: {**_codes(ERROR), "since": _spelled(5), "was": "OK",
                          "cause": "reading"},
                   BUSY: {**_codes(OK), "since": _spelled(40), "was": "ERROR",
                          "cause": "reading"}}))
        self.assertFalse(tree.upsert(PATH, ERROR, "down"))
        return self._serve(tree)

    def test_a_quiet_node_s_time_card_says_since_when(self) -> None:
        self._quiet()
        self.assertEqual(self._period("/status/site/probe"),
                         f"Status error since {self._shown(_at(5))}")

    def test_and_history_shows_its_period_from_that_instant(self) -> None:
        self._quiet()
        self.assertEqual(self._history("/history/site/probe"), [
            ["error", self._shown(_at(5)), "current", "down"]])

    def test_and_its_copy_document_says_the_same(self) -> None:
        self._quiet()
        style: TimeStyle = app_module._copy_style()
        expected = f"- **Status error** since {style.at(_at(5))}\n"
        body = self.client.get("/copy/site/probe").get_data(as_text=True)
        self.assertIn(expected.strip(), body.replace("&#39;", "'"))

    def test_how_a_period_began_is_kept_too(self) -> None:
        tree = _started(_file(nodes={
            PATH: {**_codes(OK), "since": _spelled(9), "was": "MAINTENANCE",
                   "cause": "pin-ended"}}))
        tree.upsert(PATH, OK, "in step")
        self._serve(tree)
        self.assertEqual(
            self._period("/status/site/probe"),
            f"Status ok since {self._shown(_at(9))}, when its maintenance ended")

    def test_a_new_node_s_time_card_says_since_before_its_first_reading(
            self) -> None:
        tree = self._serve(StatusTree())
        tree.upsert(PATH, OK, "fine")
        first = self._shown(_last_row(tree).timestamp)
        self.assertEqual(self._period("/status/site/probe"),
                         f"Status ok since before {first}")
        self.assertEqual(self._history("/history/site/probe"), [
            ["ok", f"before {first}", "current", "fine"]])

    def test_a_kept_bound_reads_since_before_and_does_not_move(self) -> None:
        tree = _started(_file(
            _row(BUSY, OK, ERROR, 30), _row(BUSY, ERROR, OK, 40),
            nodes={PATH: {**_codes(OK), "since": _spelled(2), "before": True},
                   BUSY: _codes(OK)}))
        tree.upsert(PATH, OK, "fine")
        self._serve(tree)
        self.assertEqual(self._period("/status/site/probe"),
                         f"Status ok since before {self._shown(_at(2))}")
        self.assertEqual(self._history("/history/site/probe"), [
            ["ok", f"before {self._shown(_at(2))}", "current", "fine"]])

    def test_a_bound_says_nothing_of_how_the_period_began(self) -> None:
        # the oldest row of a pinned node's reading is its pin's end, in a log
        # written before a row said what moved its node
        tree = _started(_file(_row(PATH, UNDEFINED, OK, 7, cause="")))
        tree.upsert(PATH, OK, "fine")
        self._serve(tree)
        self.assertEqual(self._period("/status/site/probe"),
                         f"Status ok since before {self._shown(_at(7))}")

    def test_a_node_nothing_has_written_keeps_its_sentence(self) -> None:
        tree = self._serve(StatusTree())
        tree.set_about("/site/idle", "Not read yet.")
        tree.upsert(PATH, OK, "fine")
        rows = self._history("/history/site/idle")
        self.assertEqual(rows, [["No status changes recorded."]])


class PinPageTests(_Pages):
    """A pinned node's pages state the pin's creation where the tree did not see it
    set."""

    def _replayed(self) -> StatusTree:
        """A start on a log older than the pin: the node's failure, and no pin."""
        tree = _started(_file(
            _row(PATH, UNDEFINED, OK, 0), _row(PATH, OK, ERROR, 1, reason="down"),
            nodes={PATH: {**_codes(ERROR), "since": _spelled(1), "was": "OK",
                          "cause": "reading"}}))
        tree.restore_maintenance({PATH: _pin_from(3, "Disk is being replaced")})
        tree.upsert(PATH, ERROR, "down")
        return self._serve(tree)

    def test_the_time_card_says_since_the_pin_s_creation(self) -> None:
        self._replayed()
        self.assertEqual(self._period("/status/site/probe"),
                         f"Status maintenance since {self._shown(_at(3))}")

    def test_and_history_ends_the_row_before_it_there(self) -> None:
        self._replayed()
        rows = self._history("/history/site/probe")
        self.assertEqual([row[:3] for row in rows], [
            ["maintenance", self._shown(_at(3)), "current"],
            ["error", self._shown(_at(1)), self._shown(_at(3))],
            ["ok", f"before {self._shown(_at(0))}", self._shown(_at(1))]])

    def test_the_events_page_keeps_the_row_where_it_was_written(self) -> None:
        tree = self._replayed()
        replay = _last_row(tree)
        table = self._page("/events?under=/site/probe").all(tag="table")[0]
        first = table.one(tag="tbody").all(tag="tr")[0]
        self.assertIn(self._shown(replay.timestamp), first.text())


class _Quiet(Check):
    """A check that reads ok."""

    def measure(self) -> Measurement:
        return Measurement(record={})

    def grade(self, measurements: Any, now: datetime) -> CheckResult:
        return CheckResult(OK, ["fine"])


class EngineTests(TestCase):
    """The engine says which branch begins with the process: its own."""

    def test_the_instance_s_own_node_begins_with_its_first_beat(self) -> None:
        tree = StatusTree()
        engine = Engine([_Quiet(path="/site/probe")], tree)
        engine.run_once()
        engine._tick(submit=False)
        for path in (HEARTBEAT_PATH, f"{HEARTBEAT_PATH}/engine"):
            with self.subTest(path=path):
                self.assertFalse(_current(tree, path).before)
        self.assertTrue(_current(tree, "/site/probe").before,
                        "a check's node was there before it was seen")


class _Roots:
    """What the restore asks of an engine: the configured checks' roots."""

    def __init__(self, *roots: str) -> None:
        self._roots = list(roots)

    def check_roots(self) -> list[str]:
        return self._roots


class StartTests(TestCase):
    """``app._restore_state`` hands the tree the periods its file carries."""

    def setUp(self) -> None:
        self._original = app_module.status_tree
        self.tree = StatusTree()
        app_module.status_tree = self.tree

    def tearDown(self) -> None:
        app_module.status_tree = self._original

    def test_a_start_reads_the_periods_and_forgets_those_nothing_covers(
            self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            state = StateLayer(directory)
            state.write(EVENTS_FILE, _file(nodes={
                "/x/probe": {**_codes(ERROR), "since": _spelled(5), "was": "OK",
                             "cause": "reading"},
                "/gone/probe": {**_codes(OK), "since": _spelled(1), "before": True}}))
            app_module._restore_state(_Roots("/x"), state)  # type: ignore[arg-type]
            self.assertEqual(_kept(self.tree)["nodes"], {
                "/x/probe": {**_codes(ERROR), "since": _spelled(5), "was": "OK",
                             "cause": "reading"}})
            self.tree.upsert("/x/probe", ERROR, "down")
            self.assertEqual(_said(_current(self.tree, "/x/probe")),
                             (ERROR, _at(5), False))

    def test_a_table_whose_period_cannot_be_read_is_a_line(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            state = StateLayer(directory)
            state.write(EVENTS_FILE, _file(nodes={
                "/x": {**_codes(OK), "since": "yesterday"}}))
            with self.assertLogs(level="ERROR"):
                app_module._restore_state(_Roots("/x"), state)  # type: ignore[arg-type]
            (line,) = state.lines()
            self.assertEqual(line.slug, f"load.{EVENTS_FILE}")

    def test_a_start_dates_a_pin_its_log_does_not_hold_by_the_store(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            state = StateLayer(directory)
            PinStore(state).save({"/x/probe": _pin_from(3)})
            state.write(EVENTS_FILE, _file(nodes={
                "/x/probe": {**_codes(OK), "since": _spelled(1), "before": True}}))
            app_module._restore_state(_Roots("/x"), state)  # type: ignore[arg-type]
            self.assertEqual(_kept(self.tree)["nodes"]["/x/probe"], {
                **_codes(MAINTENANCE, OK), "since": _spelled(3), "was": "OK",
                "cause": "pin-set"})
