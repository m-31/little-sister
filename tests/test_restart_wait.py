"""What every node last showed is kept beside the log, and a wait counts from it
(ADR-0110).

A node may wait before it escalates (ADR-0083), and its counter is memory. A node's
first reading in a new process met no counter and was published at once, so every
failure a restart found skipped its wait (backlog #89's B17). And the log is bounded:
a node whose last change had left it had nothing for its first reading to be compared
with, so a restart wrote it *undefined → …*, the transition ADR-0094 meant a restart
not to be.

* The count starts from what the node last showed. A failure a restart finds waits
  like any other, one that stood before it stays published, and a wait under way at a
  stop goes on: the kept entry says what a waiting node publishes (ADR-0119).
* The kept log carries, beside its rows, what every node shows and what its check last
  reported, and a restart compares each first reading with that entry, row or no row.
* An entry goes when no configured check covers its node.
"""
from __future__ import annotations

import json
import os
import tempfile
from datetime import UTC, datetime, timedelta
from typing import Any
from unittest import TestCase

os.environ.setdefault("SECRET_KEY", "test-key")

from little_sister import instants
from little_sister import tree as tree_module
from little_sister.pins import Pin
from little_sister.reasons import Entry
from little_sister.state import EVENTS_FILE, StateLayer
from little_sister.status import HEARTBEAT_PATH, StatusCode, worst_of
from little_sister.tree import (
    DAMPING_RULE,
    MAINTENANCE_RULE,
    Contribution,
    Damping,
    Event,
    StatusTree,
    events_from_payload,
)
from tests.state_files import on_disk
from tests.test_branch_periods import as_before_the_key

OK, WARN, ERROR = StatusCode.OK, StatusCode.WARN, StatusCode.ERROR
MAINTENANCE, UNDEFINED = StatusCode.MAINTENANCE, StatusCode.UNDEFINED

PATH = "/site/probe"
PARENT = "/site"
NEEDED = 3
_SOON = timedelta(hours=1)

#: Two rows as an older file may hold them alone for a node: a change of the reading
#: beneath a pin, which says what the check reported and not what the node showed,
#: and a pin's edit from a log written before an event said what the check reported,
#: which says what the node showed and nothing of its check.
_BENEATH_A_PIN = Event(path="/site/beneath", name="beneath", old=OK, new=ERROR,
                       reason=("it reads error",),
                       timestamp=datetime(2026, 9, 26, 10, 0, tzinfo=UTC),
                       suppressed_by=MAINTENANCE_RULE, cause="reading",
                       reported=ERROR)
_AN_EDIT = Event(path="/site/edited", name="edited", old=MAINTENANCE,
                 new=MAINTENANCE, reason=("until Monday",),
                 timestamp=datetime(2026, 9, 26, 10, 5, tzinfo=UTC))


class _Pins:
    """The pins file, as a store that remembers the last table saved."""

    def __init__(self) -> None:
        self.nodes: dict[str, Pin] = {}
        self.lines: dict[tuple[str, str], Pin] = {}

    def load(self) -> dict[str, Pin]:
        return {}

    def load_entries(self) -> dict[tuple[str, str], Pin]:
        return {}

    def save(self, entries: dict[str, Pin],
             entry_pins: dict[tuple[str, str], Pin] | None = None,
             acknowledged: dict[str, Pin] | None = None,
             lines_acknowledged: dict[tuple[str, str], Pin] | None = None
             ) -> None:
        self.nodes = dict(entries)
        self.lines = dict(entry_pins or {})


def _read(tree: StatusTree, code: StatusCode, *, path: str = PATH,
          needed: int = NEEDED) -> bool:
    """One reading of a node that waits ``needed`` readings before it escalates;
    whether it wrote an event."""
    return tree.upsert(path, code, f"it reads {code.name.lower()}",
                       escalate_after=needed)


def _lines(tree: StatusTree, *, needed: int = NEEDED, **codes: StatusCode) -> None:
    """One run of a check whose lines carry codes: the lines, and the worst of them as
    the node's — what the engine stores for such a node (ADR-0042)."""
    lines = [Entry(slug, f"{slug}: {code.name.lower()}", code=code)
             for slug, code in codes.items()]
    tree.upsert(PATH, worst_of(codes.values()), lines, members=True,
                escalate_after=needed)


def _kept(tree: StatusTree) -> dict[str, Any]:
    """What the tree writes to its file, through the file's own shape — its table as
    this record keeps it, without the period of what a branch shows, which is
    ADR-0132's and ``tests/test_branch_period_kept.py``'s
    (:func:`as_before_the_key`)."""
    kept: dict[str, Any] = json.loads(json.dumps(tree.events_payload()))
    kept["nodes"] = as_before_the_key(kept["nodes"])
    return kept


def _two_codes(table: dict[str, Any]) -> dict[str, dict[str, str]]:
    """What a table says each node shows and its check reported: the two codes of
    every entry, without when its period began, which is decision 5's and
    ``tests/test_kept_periods.py``'s."""
    return {path: {key: entry[key] for key in ("shows", "reported")}
            for path, entry in table.items()}


def _without_rows(payload: dict[str, Any]) -> dict[str, Any]:
    """The file once every row has left the bounded log: the table alone."""
    return {**payload, "events": []}


def _before_the_table(payload: dict[str, Any]) -> dict[str, Any]:
    """The file as a tree wrote it before it kept the table."""
    return {name: value for name, value in payload.items() if name != "nodes"}


def _started(payload: dict[str, Any], pins: _Pins | None = None, *,
             after: timedelta = timedelta(minutes=1)) -> StatusTree:
    """A new process on what the old one kept: its file — the table where the file
    carries one — and its pins, started ``after`` the old one stopped."""
    new = StatusTree() if pins is None else StatusTree(pin_store=pins)
    events = events_from_payload(payload)
    if "nodes" in payload:
        new.restore_events(events, tree_module.nodes_from_payload(payload))
    else:
        new.restore_events(events)
    if pins is not None:
        new.restore_maintenance(dict(pins.nodes), now=datetime.now(UTC) + after,
                                entry_pins=dict(pins.lines))
    return new


def _hold(tree: StatusTree, path: str = PATH) -> tuple[StatusCode, int] | None:
    """The hold the node states: the status it waits to publish, and how many
    readings of it are in."""
    node = tree.snapshot(path)
    assert node is not None
    return None if node.damping is None else (node.damping.pending,
                                              node.damping.seen)


def _above(tree: StatusTree) -> StatusCode:
    """What the level above the node shows."""
    parent = tree.snapshot(PARENT)
    assert parent is not None
    return parent.code


def _rows(tree: StatusTree, path: str = PATH) -> list[Event]:
    return [event for event in tree.recent_events() if event.path == path]


def _was(tree: StatusTree, *codes: StatusCode, needed: int = NEEDED) -> StatusTree:
    for code in codes:
        _read(tree, code, needed=needed)
    return tree


class CountTests(TestCase):
    """The count starts from what the node last showed (decision 1)."""

    def test_a_failure_a_restart_finds_waits(self) -> None:
        new = _started(_kept(_was(StatusTree(), OK, OK)))
        _read(new, ERROR)
        self.assertEqual((_hold(new), _above(new)), ((ERROR, 1), OK))
        _read(new, ERROR)
        self.assertEqual((_hold(new), _above(new)), ((ERROR, 2), OK))
        _read(new, ERROR)
        self.assertEqual((_hold(new), _above(new)), (None, ERROR))

    def test_the_wait_is_stated_and_its_row_is_marked(self) -> None:
        new = _started(_kept(_was(StatusTree(), OK)))
        _read(new, ERROR)
        row = _rows(new)[-1]
        self.assertEqual((row.old, row.new, row.suppressed_by, row.cause),
                         (OK, ERROR, DAMPING_RULE, "reading"))
        node = new.snapshot(PATH)
        assert node is not None
        self.assertEqual(node.damping, Damping(pending=ERROR, seen=1, needed=NEEDED))
        # what the parent counts meanwhile is what the node showed before the stop
        self.assertEqual(node.contribution, Contribution(OK, DAMPING_RULE))
        self.assertEqual((node.code, node.counted), (ERROR, OK))

    def test_a_failure_that_stood_stays_published(self) -> None:
        old = _was(StatusTree(), OK, ERROR, ERROR, ERROR, ERROR)
        self.assertEqual((_hold(old), _above(old)), (None, ERROR))
        new = _started(_kept(old))
        self.assertFalse(_read(new, ERROR), "the same reading writes nothing")
        self.assertEqual((_hold(new), _above(new)), (None, ERROR))

    def test_a_wait_under_way_at_the_stop_goes_on(self) -> None:
        # ADR-0119 decision 5. The entry says what the waiting node publishes, and
        # the count resumes with the reading its held row records as the first.
        old = _was(StatusTree(), OK, ERROR)
        self.assertEqual((_hold(old), _above(old)), ((ERROR, 1), OK))
        for name, kept in (("its rows", _kept(old)),
                           ("the entry alone", _without_rows(_kept(old)))):
            with self.subTest(read_from=name):
                new = _started(kept)
                self.assertFalse(_read(new, ERROR), "the second reading of three")
                self.assertEqual((_hold(new), _above(new)), ((ERROR, 2), OK))
                self.assertTrue(_read(new, ERROR), "the third completes the count")
                self.assertEqual((_hold(new), _above(new)), (None, ERROR))
                row = _rows(new)[-1]
                self.assertEqual((row.old, row.new, row.suppressed_by, row.cause),
                                 (ERROR, ERROR, "", "reached"))

    def test_a_wait_of_two_ends_at_the_first_reading_afterwards(self) -> None:
        # one reading on each side of the restart
        old = _was(StatusTree(), OK, ERROR, needed=2)
        self.assertEqual((_hold(old), _above(old)), ((ERROR, 1), OK))
        new = _started(_kept(old))
        self.assertTrue(_read(new, ERROR, needed=2))
        self.assertEqual((_hold(new), _above(new)), (None, ERROR))
        self.assertEqual(_rows(new)[-1].cause, "reached")

    def test_the_readings_between_the_held_row_and_the_stop_are_not_kept(
            self) -> None:
        # the counter is memory still: three readings in, the next process knows of
        # the one its row records
        old = _was(StatusTree(), OK, ERROR, ERROR, ERROR, needed=5)
        self.assertEqual(_hold(old), (ERROR, 3))
        new = _started(_kept(old))
        _read(new, ERROR, needed=5)
        self.assertEqual((_hold(new), _above(new)), ((ERROR, 2), OK))

    def test_a_recovery_ends_a_wait_the_restart_found_under_way(self) -> None:
        new = _started(_kept(_was(StatusTree(), OK, ERROR)))
        self.assertTrue(_read(new, OK))
        row = _rows(new)[-1]
        self.assertEqual((row.old, row.new, row.suppressed_by, row.cause),
                         (ERROR, OK, "", "reading"))
        self.assertEqual((_hold(new), _above(new)), (None, OK))
        self.assertNotIn("publishes", _kept(new)["nodes"][PATH])

    def test_a_worse_status_than_the_one_held_waits_from_what_was_published(
            self) -> None:
        old = _was(StatusTree(), OK, WARN)
        self.assertEqual((_hold(old), _above(old)), ((WARN, 1), OK))
        new = _started(_kept(old))
        _read(new, ERROR)
        self.assertEqual((_hold(new), _above(new)), ((ERROR, 1), OK))
        self.assertEqual(_kept(new)["nodes"][PATH]["publishes"], "OK")

    def test_a_second_stop_before_the_nodes_first_reading_keeps_the_wait(
            self) -> None:
        once = _started(_kept(_was(StatusTree(), OK, ERROR)))
        self.assertEqual(_kept(once)["nodes"][PATH]["publishes"], "OK")
        twice = _started(_kept(once))
        _read(twice, ERROR)
        self.assertEqual((_hold(twice), _above(twice)), ((ERROR, 2), OK))

    def test_a_pin_set_before_the_first_reading_ends_the_wait(self) -> None:
        # a change that a pin made is published at once (ADR-0108 decision 2)
        pins = _Pins()
        new = _started(_kept(_was(StatusTree(pin_store=pins), OK, ERROR)),
                       pins)
        new.set_maintenance(PATH, "planned", set_by="ada",
                            expires_at=datetime.now(UTC) + _SOON)
        self.assertNotIn("publishes", _kept(new)["nodes"][PATH])
        new.clear_maintenance(PATH)
        self.assertNotIn("publishes", _kept(new)["nodes"][PATH])
        _read(new, ERROR)
        self.assertEqual((_hold(new), _above(new)), (None, ERROR))

    def test_a_file_written_before_the_key_takes_no_alarm_back(self) -> None:
        # Such a file says of no node that it waits, and is read as it was: a row
        # held by the wait as an escalation made (ADR-0110 decision 1).
        kept = _kept(_was(StatusTree(), OK, ERROR, ERROR, ERROR))
        self.assertNotIn("publishes", kept["nodes"][PATH])
        kept["events"] = [row for row in kept["events"] if row["cause"] != "reached"]
        new = _started(kept)
        self.assertFalse(_read(new, ERROR))
        self.assertEqual((_hold(new), _above(new)), (None, ERROR))

    def test_it_is_what_the_node_showed_and_not_what_its_check_reported(self) -> None:
        # A silenced line was failing: the node showed ok, its check reported error.
        pins = _Pins()
        old = StatusTree(pin_store=pins)
        _lines(old, deploy=ERROR, tests=OK)
        old.set_entry_maintenance(PATH, "deploy", "being reworked", set_by="ada",
                                  expires_at=datetime.now(UTC) + _SOON)
        self.assertEqual(_two_codes(_kept(old)["nodes"])[PATH],
                         {"shows": "OK", "reported": "ERROR"})
        new = _started(_kept(old), pins)
        _lines(new, deploy=ERROR, tests=ERROR)      # the other line's first failure
        self.assertEqual((_hold(new), _above(new)), ((ERROR, 1), OK))

    def test_a_recovery_is_published_at_once(self) -> None:
        new = _started(_kept(_was(StatusTree(), OK, ERROR, ERROR, ERROR)))
        _read(new, OK)
        self.assertEqual((_hold(new), _above(new)), (None, OK))
        row = _rows(new)[-1]
        self.assertEqual((row.old, row.new, row.suppressed_by), (ERROR, OK, ""))

    def test_a_lesser_failure_is_published_at_once(self) -> None:
        new = _started(_kept(_was(StatusTree(), ERROR, ERROR, ERROR)))
        _read(new, WARN)
        self.assertEqual((_hold(new), _above(new)), (None, WARN))

    def test_a_node_nothing_is_kept_of_is_published_at_once(self) -> None:
        for payload in ({"events": []}, {"events": [], "nodes": {}}):
            with self.subTest(payload=payload):
                new = _started(payload)
                _read(new, ERROR)
                self.assertEqual((_hold(new), _above(new)), (None, ERROR))

    def test_a_node_that_does_not_wait_is_published_at_once(self) -> None:
        new = _started(_kept(_was(StatusTree(), OK, needed=1)))
        _read(new, ERROR, needed=1)
        self.assertEqual((_hold(new), _above(new)), (None, ERROR))

    def test_only_the_first_reading_is_counted_from_what_was_kept(self) -> None:
        new = _started(_kept(_was(StatusTree(), ERROR, ERROR, ERROR)))
        _was(new, OK, ERROR)           # a recovery, and then a failure of this process
        self.assertEqual((_hold(new), _above(new)), ((ERROR, 1), OK))

    def test_a_pin_that_ran_out_meanwhile_ends_at_once(self) -> None:
        # The failure stood beneath the pin, which ran out while the instance was
        # down: its end uncovers it, and that is no new reading to doubt (ADR-0108
        # decision 2).
        pins = _Pins()
        old = _was(StatusTree(pin_store=pins), OK, ERROR)
        old.set_maintenance(PATH, "planned", set_by="ada",
                            expires_at=datetime.now(UTC) + _SOON)
        new = _started(_kept(old), pins, after=timedelta(hours=2))
        _read(new, ERROR)
        row = _rows(new)[-1]
        self.assertEqual((row.old, row.new, row.cause, row.suppressed_by),
                         (MAINTENANCE, ERROR, "pin-ended", ""))
        self.assertEqual((_hold(new), _above(new)), (None, ERROR))

    def test_a_failure_found_where_a_pin_ran_out_is_published_with_its_end(
            self) -> None:
        pins = _Pins()
        old = _was(StatusTree(pin_store=pins), OK)
        old.set_maintenance(PATH, "planned", set_by="ada",
                            expires_at=datetime.now(UTC) + _SOON)
        new = _started(_kept(old), pins, after=timedelta(hours=2))
        _read(new, ERROR)
        self.assertIn((MAINTENANCE, ERROR, "pin-ended", ""),
                      [(row.old, row.new, row.cause, row.suppressed_by)
                       for row in _rows(new)])
        self.assertEqual((_hold(new), _above(new)), (None, ERROR))


class RowsTests(TestCase):
    """A file written before the table is counted from its rows (decisions 1 and 3)."""

    def test_a_failure_a_restart_finds_waits(self) -> None:
        new = _started(_before_the_table(_kept(_was(StatusTree(), OK, OK))))
        _read(new, ERROR)
        self.assertEqual((_hold(new), _above(new)), ((ERROR, 1), OK))
        row = _rows(new)[-1]
        self.assertEqual((row.old, row.new, row.suppressed_by),
                         (OK, ERROR, DAMPING_RULE))

    def test_a_last_row_held_by_the_wait_is_read_as_made(self) -> None:
        new = _started(_before_the_table(_kept(_was(StatusTree(), OK, ERROR))))
        _read(new, ERROR)
        self.assertEqual((_hold(new), _above(new)), (None, ERROR))

    def test_the_same_reading_writes_nothing_and_a_node_without_a_row_is_new(
            self) -> None:
        payload = _before_the_table(_kept(_was(StatusTree(), OK)))
        new = _started(payload)
        self.assertFalse(_read(new, OK))
        new = _started(_without_rows(payload))
        self.assertTrue(_read(new, OK))
        row = _rows(new)[-1]
        self.assertEqual((row.old, row.new), (UNDEFINED, OK))


class TableTests(TestCase):
    """The kept log says what every node last showed, beside its rows (decision 2)."""

    def test_it_says_what_each_node_shows_and_what_its_check_reported(self) -> None:
        tree = StatusTree(pin_store=_Pins())
        soon = datetime.now(UTC) + _SOON
        _read(tree, OK, path="/site/quiet")
        _read(tree, ERROR, path="/site/broken")
        _read(tree, ERROR, path="/site/silenced")
        tree.set_maintenance("/site/silenced", "planned", set_by="ada",
                             expires_at=soon)
        tree.upsert("/site/lines", ERROR, [Entry("a", "a: error", code=ERROR),
                                           Entry("b", "b: ok", code=OK)],
                    members=True)
        tree.set_entry_maintenance("/site/lines", "a", "known", expires_at=soon,
                                   set_by="ada")
        self.assertEqual(_two_codes(_kept(tree)["nodes"]), {
            "/site/broken": {"shows": "ERROR", "reported": "ERROR"},
            "/site/lines": {"shows": "OK", "reported": "ERROR"},
            "/site/quiet": {"shows": "OK", "reported": "OK"},
            "/site/silenced": {"shows": "MAINTENANCE", "reported": "ERROR"},
        })

    def test_its_nodes_stand_in_the_order_of_their_paths(self) -> None:
        tree = StatusTree()
        for path in ("/a/z", "/a/b", "/c"):
            _read(tree, OK, path=path)
        self.assertEqual(list(_kept(tree)["nodes"]), ["/a/b", "/a/z", "/c"])

    def test_a_node_that_shows_and_reported_nothing_has_no_entry(self) -> None:
        tree = StatusTree()
        tree.upsert(PARENT, UNDEFINED)        # a check's root that declares nothing
        _read(tree, OK)
        self.assertEqual(list(_kept(tree)["nodes"]), [PATH])
        # but for the period of what it shows, which a branch keeps (ADR-0132)
        self.assertEqual(tree.events_payload()["nodes"][PARENT].keys(),
                         {"shows", "reported", "period"})

    def test_a_reading_that_changes_nothing_leaves_the_file_as_it_is(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            layer = StateLayer(directory)
            tree = _was(StatusTree(), OK, ERROR)
            layer.keep(EVENTS_FILE, tree.events_payload)
            layer.flush()
            written = on_disk(layer.path(EVENTS_FILE))
            self.assertIn(PATH, written["nodes"])
            layer.path(EVENTS_FILE).write_text("untouched")
            _read(tree, ERROR)                # the second of three: no row, no change
            layer.flush()
            self.assertEqual(layer.path(EVENTS_FILE).read_text(), "untouched")
            _read(tree, OK)                   # a row, and the table with it
            layer.flush()
            kept = on_disk(layer.path(EVENTS_FILE))
            self.assertEqual(_two_codes(kept["nodes"])[PATH],
                             {"shows": "OK", "reported": "OK"})
            self.assertEqual(len(kept["events"]), len(written["events"]) + 1)

    def test_what_was_restored_and_not_read_yet_stays_in_it(self) -> None:
        old = StatusTree()
        _read(old, OK, path="/site/a")
        _read(old, ERROR, path="/site/b", needed=1)
        new = _started(_without_rows(_kept(old)))
        _read(new, WARN, path="/site/a", needed=1)
        self.assertEqual(_two_codes(_kept(new)["nodes"]), {
            "/site/a": {"shows": "WARN", "reported": "WARN"},
            "/site/b": {"shows": "ERROR", "reported": "ERROR"},
        })

    def test_a_pin_set_before_a_node_is_read_is_in_it(self) -> None:
        old = StatusTree()
        _read(old, ERROR, needed=1)
        new = _started(_kept(old), _Pins())
        new.set_maintenance(PATH, "planned", set_by="ada",
                            expires_at=datetime.now(UTC) + _SOON)
        self.assertEqual(_two_codes(_kept(new)["nodes"]),
                         {PATH: {"shows": "MAINTENANCE", "reported": "ERROR"}})

    def test_an_older_reader_passes_over_it(self) -> None:
        payload = _kept(_was(StatusTree(), OK, ERROR))
        self.assertIn("nodes", payload)
        self.assertEqual(len(events_from_payload(payload)), 2)

    def test_a_file_without_it_says_so(self) -> None:
        self.assertIsNone(tree_module.nodes_from_payload({"events": []}))

    def test_what_only_the_rows_of_an_older_file_say_stands_beside_nothing(
            self) -> None:
        # A file written before the table, whose rows say one of the two: a change
        # beneath a pin whose set has left the log, and an edit of a pin whose set
        # has.
        new = _started({"events": [_BENEATH_A_PIN.to_dict(), _AN_EDIT.to_dict()]})
        self.assertEqual(_two_codes(_kept(new)["nodes"]), {
            "/site/beneath": {"shows": "UNDEFINED", "reported": "ERROR"},
            "/site/edited": {"shows": "MAINTENANCE", "reported": "UNDEFINED"}})

    def test_a_table_of_another_shape_is_refused(self) -> None:
        tables: list[object] = [[], "nodes", {PATH: "OK"}, {PATH: ["OK", "OK"]},
                                {PATH: {}}, {PATH: {"shows": "OK"}},
                                {PATH: {"reported": "OK"}},
                                {PATH: {"shows": "NOPE", "reported": "OK"}},
                                {PATH: {"shows": "OK", "reported": 3}},
                                {PATH: {"shows": ["OK"], "reported": "OK"}},
                                {PATH: {"shows": None, "reported": "OK"}}]
        for table in tables:
            with self.subTest(table=table), self.assertRaises(ValueError):
                tree_module.nodes_from_payload({"events": [], "nodes": table})


class RestartTests(TestCase):
    """A restart reads the table (decision 3)."""

    def test_a_quiet_node_writes_nothing_at_a_start(self) -> None:
        new = _started(_without_rows(_kept(_was(StatusTree(), OK))))
        self.assertFalse(_read(new, OK))
        self.assertEqual(new.recent_events(), ())
        self.assertEqual((_hold(new), _above(new)), (None, OK))

    def test_a_change_is_written_from_what_the_entry_says(self) -> None:
        new = _started(_without_rows(_kept(_was(StatusTree(), OK))))
        self.assertTrue(_read(new, ERROR))
        (row,) = new.recent_events()
        self.assertEqual((row.path, row.old, row.new, row.suppressed_by),
                         (PATH, OK, ERROR, DAMPING_RULE))
        self.assertEqual((_hold(new), _above(new)), ((ERROR, 1), OK))

    def test_a_failure_older_than_the_log_reaches_stays_published(self) -> None:
        old = _was(StatusTree(), OK, ERROR, ERROR, ERROR)
        new = _started(_without_rows(_kept(old)))
        self.assertFalse(_read(new, ERROR))
        self.assertEqual(new.recent_events(), ())
        self.assertEqual((_hold(new), _above(new)), (None, ERROR))

    def test_the_table_is_read_where_the_file_carries_it(self) -> None:
        payload = _kept(_was(StatusTree(), OK))
        payload["nodes"][PATH] = {"shows": "WARN", "reported": "WARN"}
        new = _started(payload)
        self.assertFalse(_read(new, WARN), "compared with the entry, not the row")

    def test_a_node_the_table_does_not_name_has_a_first_reading(self) -> None:
        # No file the tree writes holds a row of a node and no entry of it; where one
        # does, the table is what is read.
        payload = _kept(_was(StatusTree(), OK))
        payload["nodes"] = {}
        new = _started(payload)
        self.assertTrue(_read(new, OK))
        row = _rows(new)[-1]
        self.assertEqual((row.old, row.new), (UNDEFINED, OK))

    def test_a_reading_beneath_a_pin_is_compared_with_what_was_reported(self) -> None:
        pins = _Pins()
        old = _was(StatusTree(pin_store=pins), OK)
        old.set_maintenance(PATH, "planned", set_by="ada",
                            expires_at=datetime.now(UTC) + _SOON)
        new = _started(_without_rows(_kept(old)), pins)
        self.assertEqual(new.recent_events(), (), "the pin's replay wrote nothing")
        self.assertFalse(_read(new, OK))
        self.assertTrue(_read(new, ERROR))
        (row,) = new.recent_events()
        self.assertEqual((row.old, row.new, row.suppressed_by),
                         (OK, ERROR, MAINTENANCE_RULE))
        node = new.snapshot(PATH)
        assert node is not None
        self.assertIs(node.own_code, MAINTENANCE)

    def test_the_instances_own_gap_is_closed_from_it(self) -> None:
        old = StatusTree()
        old.upsert(HEARTBEAT_PATH, OK)
        new = _started(_without_rows(_kept(old)))
        since = datetime.now(UTC) - timedelta(minutes=5)
        self.assertTrue(new.close_unobserved(HEARTBEAT_PATH, since,
                                             "the instance was not running"))
        (row,) = new.recent_events()
        self.assertEqual((row.old, row.new, row.timestamp), (OK, UNDEFINED, since))
        # the gap is a period the tree saw begin, and the table says so (decision 5)
        self.assertEqual(_kept(new)["nodes"][HEARTBEAT_PATH], {
            "shows": "UNDEFINED", "reported": "UNDEFINED",
            "since": instants.stamp(since), "was": "OK"})

    def test_an_adopted_file_brings_its_table_for_what_was_not_read_yet(self) -> None:
        running = StatusTree()
        _read(running, OK, path="/site/a", needed=1)
        adopted = {"events": [], "nodes": {
            "/site/a": {"shows": "ERROR", "reported": "ERROR"},
            "/site/b": {"shows": "ERROR", "reported": "ERROR"}}}
        running.adopt_events(adopted)
        self.assertFalse(_read(running, OK, path="/site/a", needed=1),
                         "a node written already goes on comparing with itself")
        self.assertFalse(_read(running, ERROR, path="/site/b", needed=1))
        self.assertEqual(running.recent_events(), ())
        self.assertEqual(_two_codes(_kept(running)["nodes"]), {
            "/site/a": {"shows": "OK", "reported": "OK"},
            "/site/b": {"shows": "ERROR", "reported": "ERROR"}})

    def test_an_adopted_wait_goes_on_for_a_node_not_read_yet(self) -> None:
        running = StatusTree()
        _read(running, OK, path="/site/a")
        _read(running, ERROR, path="/site/a")            # its own wait, one reading in
        waiting = {"shows": "ERROR", "reported": "ERROR", "publishes": "OK"}
        running.adopt_events({"events": [], "nodes": {"/site/a": dict(waiting),
                                                      "/site/b": dict(waiting)}})
        _read(running, ERROR, path="/site/a")
        self.assertEqual(_hold(running, "/site/a"), (ERROR, 2),
                         "a node written already goes on counting for itself")
        _read(running, ERROR, path="/site/b")
        self.assertEqual(_hold(running, "/site/b"), (ERROR, 2),
                         "one not read yet resumes the adopted wait")


class ForgetTests(TestCase):
    """An entry goes when no configured check covers its node (decision 4)."""

    def _restored(self) -> StatusTree:
        return _started({"events": [], "nodes": {
            "/web/a": {"shows": "OK", "reported": "OK"},
            "/web": {"shows": "MAINTENANCE", "reported": "UNDEFINED"},
            "/webs/a": {"shows": "ERROR", "reported": "ERROR"},
            "/gone/x": {"shows": "ERROR", "reported": "ERROR"},
            f"{HEARTBEAT_PATH}/engine": {"shows": "WARN", "reported": "WARN"}}})

    def test_an_entry_no_check_covers_is_dropped(self) -> None:
        tree = self._restored()
        self.assertEqual(tree.forget_uncovered(["/web/a/b", HEARTBEAT_PATH]),
                         ["/gone/x", "/webs/a"])
        self.assertEqual(sorted(_kept(tree)["nodes"]),
                         [f"{HEARTBEAT_PATH}/engine", "/web", "/web/a"])

    def test_a_node_that_was_forgotten_has_a_first_reading(self) -> None:
        tree = self._restored()
        tree.forget_uncovered(["/web/a"])
        self.assertTrue(_read(tree, ERROR, path="/gone/x"))
        (row,) = tree.recent_events()
        self.assertEqual((row.old, row.new, row.suppressed_by), (UNDEFINED, ERROR, ""))

    def test_nothing_goes_where_everything_is_covered(self) -> None:
        tree = self._restored()
        self.assertEqual(tree.forget_uncovered(
            ["/web", "/webs", "/gone", HEARTBEAT_PATH]), [])
        self.assertEqual(len(_kept(tree)["nodes"]), 5)

    def test_what_only_rows_said_of_a_node_is_forgotten_too(self) -> None:
        tree = _started({"events": [_BENEATH_A_PIN.to_dict(), _AN_EDIT.to_dict()]})
        self.assertEqual(tree.forget_uncovered(["/web"]),
                         ["/site/beneath", "/site/edited"])
        self.assertEqual(_kept(tree)["nodes"], {})


class _Roots:
    """Stands in for the engine at startup: the restore asks it one thing."""

    def __init__(self, *roots: str) -> None:
        self._roots = list(roots)

    def check_roots(self) -> list[str]:
        return self._roots


class StartTests(TestCase):
    """``app._restore_state`` hands the tree the table its file carries, and forgets
    what no configured check covers — the instance's own line is none of theirs and
    is kept."""

    def setUp(self) -> None:
        from little_sister import app as app_module
        self._app = app_module
        self._original = app_module.status_tree
        self.tree = StatusTree()
        app_module.status_tree = self.tree

    def tearDown(self) -> None:
        self._app.status_tree = self._original

    def _yesterday(self, directory: str) -> StateLayer:
        state = StateLayer(directory)
        written = StatusTree()
        _read(written, OK, path="/x/probe")
        _read(written, ERROR, path="/gone/probe", needed=1)
        written.upsert(f"{HEARTBEAT_PATH}/engine", WARN, "a tick came late")
        state.write(EVENTS_FILE, _without_rows(_kept(written)))
        return state

    def test_a_start_reads_the_table_and_forgets_what_nothing_covers(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            state = self._yesterday(directory)
            with self.assertLogs(level="INFO") as logged:
                self._app._restore_state(_Roots("/x"), state)  # type: ignore[arg-type]
            self.assertEqual(sorted(_kept(self.tree)["nodes"]),
                             [f"{HEARTBEAT_PATH}/engine", "/x/probe"])
            self.assertTrue(any("/gone/probe" in line for line in logged.output))
            self.assertFalse(_read(self.tree, OK, path="/x/probe"),
                             "compared with what the file said, with no row of it")
            _read(self.tree, ERROR, path="/x/probe")
            node = self.tree.snapshot("/x/probe")
            assert node is not None
            self.assertEqual(node.damping,
                             Damping(pending=ERROR, seen=1, needed=NEEDED))

    def test_a_start_on_a_file_written_before_reads_its_rows(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            state = StateLayer(directory)
            written = _was(StatusTree(), OK, OK)
            state.write(EVENTS_FILE, _before_the_table(_kept(written)))
            self._app._restore_state(_Roots(PARENT), state)  # type: ignore[arg-type]
            self.assertFalse(_read(self.tree, OK), "compared with the node's row")
            self.assertEqual(_two_codes(_kept(self.tree)["nodes"]),
                             {PATH: {"shows": "OK", "reported": "OK"}})
            _read(self.tree, ERROR)
            self.assertEqual(_hold(self.tree), (ERROR, 1))

    def test_a_table_of_another_shape_is_a_line_and_the_start_goes_on(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            state = StateLayer(directory)
            state.write(EVENTS_FILE, {"events": [], "nodes": {"/x": "OK"}})
            with self.assertLogs(level="ERROR"):
                self._app._restore_state(_Roots("/x"), state)  # type: ignore[arg-type]
            (line,) = state.lines()
            self.assertEqual(line.slug, f"load.{EVENTS_FILE}")
            self.assertEqual(self.tree.recent_events(), ())
            self.assertTrue(_read(self.tree, OK, path="/x"))
