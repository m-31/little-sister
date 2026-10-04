"""An event is a change of what a node shows (ADR-0107).

The log followed the code a check reports, and what a node shows is worked out from its
lines and their pins. So a line's pin, which wrote no event, left the log, History and
the Time card saying what the wall did not show (backlog #89's B15):

* Pinning a node's one failing line turned it ok and wrote nothing, and so did the
  pin's end.
* A pinned line that failed again wrote *ok → error*, unmarked, over a green node.
* A new failing line beside a pinned one turned the node red and wrote nothing.
* A pin that ran out while the instance was down left History saying *maintenance*,
  *current*, over a node that showed *warn*.

An event is written for every change of what a node shows, and none for a line by
itself; a change of the reading that the node does not show is a row of its own, held
back; an event carries its cause and what the check reported; and a restart replays
nothing — the first reading is compared with what the log last showed and reported.
"""
from __future__ import annotations

import json
import os
from datetime import UTC, datetime, timedelta
from unittest import TestCase

os.environ.setdefault("SECRET_KEY", "test-key")

from little_sister import app as app_module
from little_sister.copy_status import TimeStyle
from little_sister.maintenance import MaintenanceEntry
from little_sister.reasons import Entry
from little_sister.status import StatusCode, worst_of
from little_sister.tree import Event, StatusTree, events_from_payload
from tests.page_tree import Element, parse

OK, WARN, ERROR = StatusCode.OK, StatusCode.WARN, StatusCode.ERROR
MAINTENANCE, UNDEFINED = StatusCode.MAINTENANCE, StatusCode.UNDEFINED

PATH = "/ci/actions"
_SOON = timedelta(hours=1)


class _Kept:
    """The pins file, as a store that remembers the last table saved."""

    def __init__(self) -> None:
        self.nodes: dict[str, MaintenanceEntry] = {}
        self.lines: dict[tuple[str, str], MaintenanceEntry] = {}

    def load(self) -> dict[str, MaintenanceEntry]:
        return {}

    def load_entries(self) -> dict[tuple[str, str], MaintenanceEntry]:
        return {}

    def save(self, entries, entry_pins=None) -> None:
        self.nodes = dict(entries)
        self.lines = dict(entry_pins or {})


def _tree() -> tuple[StatusTree, _Kept]:
    kept = _Kept()
    return StatusTree(maintenance_store=kept), kept


def _write(tree: StatusTree, path: str = PATH, **codes: StatusCode) -> bool:
    """One run of a check whose lines carry codes: the lines, and the worst of them as
    the node's — what the engine stores for such a node (ADR-0042)."""
    lines = [Entry(slug, f"{slug}: {code.name.lower()}", code=code)
             for slug, code in codes.items()]
    return tree.upsert(path, worst_of(codes.values()), lines, members=True)


def _pin(tree: StatusTree, slug: str, note: str = "being reworked",
         path: str = PATH, lasts: timedelta = _SOON):
    return tree.set_entry_maintenance(
        path, slug, note, expires_at=datetime.now(UTC) + lasts, set_by="lex")


def _events(tree: StatusTree, path: str = PATH) -> list[Event]:
    return [event for event in tree.recent_events() if event.path == path]


def _moved(event: Event) -> tuple[StatusCode, StatusCode]:
    return event.old, event.new


def _shows(tree: StatusTree, path: str = PATH) -> StatusCode:
    node = tree.snapshot(path)
    assert node is not None
    return node.own_code


def _restarted(old: StatusTree, kept: _Kept, *,
               after: timedelta = timedelta(minutes=1)) -> StatusTree:
    """A new process on what the old one kept — its log, through the file's own
    shape, and its pins — started ``after`` the old one stopped."""
    new = StatusTree()
    new.restore_events(events_from_payload(
        json.loads(json.dumps(old.events_payload()))))
    new.restore_maintenance(dict(kept.nodes), now=datetime.now(UTC) + after,
                            entry_pins=dict(kept.lines))
    return new


class LinePinTests(TestCase):
    """A line's pin is an event where it changes what its node shows."""

    def setUp(self) -> None:
        self.tree, self.kept = _tree()
        _write(self.tree, deploy=ERROR, tests=OK)

    def test_pinning_the_one_failing_line_writes_the_nodes_change(self):
        before = datetime.now(UTC)
        _pin(self.tree, "deploy", "flaky runner, OPS-12")
        self.assertIs(_shows(self.tree), OK)
        event = _events(self.tree)[-1]
        self.assertEqual(_moved(event), (ERROR, OK))
        self.assertEqual(event.suppressed_by, "", "it is what everybody saw")
        self.assertGreaterEqual(event.timestamp, before,
                                "dated by the act, not by the last observation")

    def test_it_says_which_line_and_why(self):
        # the line by its text: a slug means nothing once the line is gone
        _pin(self.tree, "deploy", "flaky runner, OPS-12")
        self.assertEqual(_events(self.tree)[-1].reason,
                         ("deploy: error", "flaky runner, OPS-12"))

    def test_its_end_writes_the_change_back(self):
        _pin(self.tree, "deploy")
        self.tree.clear_entry_maintenance(PATH, "deploy")
        event = _events(self.tree)[-1]
        self.assertEqual(_moved(event), (OK, ERROR))
        self.assertEqual(event.suppressed_by, "")
        self.assertEqual(event.reason, ("deploy: error", "tests: ok"),
                         "the node's lines again, as a node's pin ends")

    def test_an_expiry_is_an_end(self):
        _write(self.tree, deploy=ERROR, tests=WARN, build=OK)
        _pin(self.tree, "deploy")
        _pin(self.tree, "tests")
        count = len(_events(self.tree))
        self.tree.sweep_expired(now=datetime.now(UTC) + timedelta(hours=2))
        swept = _events(self.tree)[count:]
        self.assertEqual([_moved(event) for event in swept], [(OK, ERROR)],
                         "two pins of one node ran out in one sweep: one row")
        self.assertIs(_shows(self.tree), ERROR)

    def test_the_last_line_pinned_turns_the_node_to_maintenance(self):
        _write(self.tree, deploy=ERROR)
        _pin(self.tree, "deploy")
        self.assertEqual(_moved(_events(self.tree)[-1]), (ERROR, MAINTENANCE))
        self.tree.clear_entry_maintenance(PATH, "deploy")
        self.assertEqual(_moved(_events(self.tree)[-1]), (MAINTENANCE, ERROR))

    def test_a_pin_that_changes_nothing_the_node_shows_writes_nothing(self):
        _write(self.tree, deploy=ERROR, tests=ERROR)
        count = len(_events(self.tree))
        _pin(self.tree, "deploy")                    # one of two failing lines
        _pin(self.tree, "deploy", "a better note")   # an edit of that pin
        _pin(self.tree, "gone")                      # a line no run reports
        self.tree.clear_entry_maintenance(PATH, "gone")
        self.assertEqual(len(_events(self.tree)), count)
        self.assertIs(_shows(self.tree), ERROR)

    def test_an_edit_of_a_line_s_pin_is_no_event_either(self):
        _pin(self.tree, "deploy")
        count = len(_events(self.tree))
        self.assertTrue(_pin(self.tree, "deploy", "one more day",
                             lasts=timedelta(days=1)).applied)
        self.assertEqual(len(_events(self.tree)), count)

    def test_a_pin_on_a_node_no_check_has_written_writes_nothing(self):
        tree, _ = _tree()
        _pin(tree, "deploy", path="/not/yet")
        self.assertEqual(tree.recent_events(), ())

    def test_history_says_what_the_node_showed(self):
        _pin(self.tree, "deploy")
        self.tree.clear_entry_maintenance(PATH, "deploy")
        self.assertEqual([period.code for period in self.tree.history(PATH)],
                         [ERROR, OK, ERROR])

    def test_an_adopted_table_writes_what_it_changed(self):
        # the store's pins at a takeover, in place of this process's (ADR-0077)
        _pin(self.tree, "deploy")
        theirs = dict(self.kept.lines)
        count = len(_events(self.tree))
        self.tree.adopt_maintenance({}, entry_pins={})
        self.assertEqual(
            [(_moved(event), event.cause) for event in _events(self.tree)[count:]],
            [((OK, ERROR), "line-pin-ended")], "a table without the pin: its end")
        self.tree.adopt_maintenance({}, entry_pins=theirs)
        self.assertEqual(
            [(_moved(event), event.cause) for event in _events(self.tree)[count:]],
            [((OK, ERROR), "line-pin-ended"), ((ERROR, OK), "line-pin-set")],
            "and one with it: its set")

    def test_a_reaped_pin_is_an_end(self):
        # a pin no check covers any more, dropped from a tree that is written
        _pin(self.tree, "deploy")
        self.tree.reap_uncovered(["/elsewhere"])
        event = _events(self.tree)[-1]
        self.assertEqual((_moved(event), event.cause),
                         ((OK, ERROR), "line-pin-ended"))

    def test_a_node_s_pin_and_its_line_s_running_out_together_are_one_row(self):
        # the node ends on what it shows without either
        _pin(self.tree, "deploy")
        self.tree.set_maintenance(PATH, "fleet replaced",
                                  expires_at=datetime.now(UTC) + _SOON)
        count = len(_events(self.tree))
        self.tree.sweep_expired(now=datetime.now(UTC) + timedelta(hours=2))
        self.assertEqual(
            [(_moved(event), event.cause) for event in _events(self.tree)[count:]],
            [((MAINTENANCE, ERROR), "pin-ended")])


class NodePinTests(TestCase):
    """A node's pin is set from what the node showed, and ends on what it shows."""

    def setUp(self) -> None:
        self.tree, _ = _tree()
        _write(self.tree, deploy=ERROR, tests=OK)
        _pin(self.tree, "deploy")

    def test_it_is_set_from_what_the_node_showed(self):
        # the node showed ok, its failing line silenced; its check reports error
        self.tree.set_maintenance(PATH, "runner fleet replaced",
                                  expires_at=datetime.now(UTC) + _SOON)
        self.assertEqual(_moved(_events(self.tree)[-1]), (OK, MAINTENANCE))

    def test_it_ends_on_what_the_node_shows(self):
        self.tree.set_maintenance(PATH, "runner fleet replaced",
                                  expires_at=datetime.now(UTC) + _SOON)
        self.tree.clear_maintenance(PATH)
        self.assertEqual(_moved(_events(self.tree)[-1]), (MAINTENANCE, OK))
        self.assertEqual([period.code for period in self.tree.history(PATH)],
                         [ERROR, OK, MAINTENANCE, OK])

    def test_over_lines_that_are_all_silenced_it_still_leaves_its_trace(self):
        # the node shows maintenance before and after: the pin's note is the news
        _write(self.tree, deploy=ERROR)
        self.tree.set_maintenance(PATH, "fleet replaced",
                                  expires_at=datetime.now(UTC) + _SOON)
        event = _events(self.tree)[-1]
        self.assertEqual((_moved(event), event.cause, event.reason),
                         ((MAINTENANCE, MAINTENANCE), "pin-set",
                          ("fleet replaced",)))
        self.assertEqual([period.code for period in self.tree.history(PATH)],
                         [ERROR, OK, MAINTENANCE], "and it begins no period")

    def test_an_adopted_table_that_carries_the_same_pins_writes_nothing(self):
        tree, kept = _tree()
        _write(tree, deploy=ERROR, tests=OK)
        _pin(tree, "deploy")
        tree.set_maintenance(PATH, "fleet replaced",
                             expires_at=datetime.now(UTC) + _SOON)
        count = len(_events(tree))
        tree.adopt_maintenance(dict(kept.nodes), entry_pins=dict(kept.lines))
        self.assertEqual(len(_events(tree)), count)

    def test_without_a_line_pinned_it_is_as_it_was(self):
        tree, _ = _tree()
        tree.upsert("/db", ERROR, "down")
        tree.set_maintenance("/db", "planned", expires_at=datetime.now(UTC) + _SOON)
        tree.clear_maintenance("/db")
        self.assertEqual([_moved(event) for event in _events(tree, "/db")][1:],
                         [(ERROR, MAINTENANCE), (MAINTENANCE, ERROR)])


class ReadingTests(TestCase):
    """A reading beside pinned lines: what the node shows is one row, and what its
    check reports and the node does not show is another, held back."""

    def setUp(self) -> None:
        self.tree, _ = _tree()
        _write(self.tree, deploy=OK, tests=OK)
        _pin(self.tree, "deploy")
        self.count = len(_events(self.tree))

    def _new(self) -> list[Event]:
        return _events(self.tree)[self.count:]

    def test_a_change_beneath_a_line_s_pin_is_held_back(self):
        self.assertTrue(_write(self.tree, deploy=ERROR, tests=OK),
                        "a row was written")
        event, = self._new()
        self.assertEqual(_moved(event), (OK, ERROR), "the reading's own codes")
        self.assertEqual(event.suppressed_by, "maintenance")
        self.assertIs(_shows(self.tree), OK)
        self.assertEqual([period.code for period in self.tree.history(PATH)], [OK],
                         "History leaves out what the node did not show")

    def test_and_so_is_its_recovery(self):
        _write(self.tree, deploy=ERROR, tests=OK)
        _write(self.tree, deploy=OK, tests=OK)
        self.assertEqual([(*_moved(event), event.suppressed_by)
                          for event in self._new()],
                         [(OK, ERROR, "maintenance"), (ERROR, OK, "maintenance")])

    def test_a_run_a_pin_hides_part_of_writes_two_rows(self):
        # a pinned line fails while an unpinned one turns slow
        _write(self.tree, deploy=ERROR, tests=WARN)
        shown, hidden = self._new()
        self.assertEqual((*_moved(shown), shown.suppressed_by), (OK, WARN, ""))
        self.assertEqual((*_moved(hidden), hidden.suppressed_by),
                         (OK, ERROR, "maintenance"))
        self.assertEqual(shown.timestamp, hidden.timestamp, "at one instant")
        self.assertEqual([period.code for period in self.tree.history(PATH)],
                         [OK, WARN])

    def test_a_change_only_the_node_shows_is_one_row_that_reached(self):
        # the unpinned line recovers; the check goes on reporting the pinned one
        _write(self.tree, deploy=ERROR, tests=WARN)
        self.count = len(_events(self.tree))
        self.assertTrue(_write(self.tree, deploy=ERROR, tests=OK))
        event, = self._new()
        self.assertEqual((*_moved(event), event.suppressed_by), (WARN, OK, ""))

    def test_a_line_that_comes_beside_a_pinned_one_is_the_nodes_change(self):
        _write(self.tree, deploy=ERROR, tests=OK)
        self.count = len(_events(self.tree))
        _write(self.tree, deploy=ERROR, tests=OK, lint=ERROR)
        event, = self._new()
        self.assertEqual((*_moved(event), event.suppressed_by), (OK, ERROR, ""))

    def test_a_reading_that_changes_neither_writes_nothing(self):
        self.assertFalse(_write(self.tree, deploy=OK, tests=OK))
        self.assertEqual(self._new(), [])

    def test_the_last_unpinned_line_going_leaves_maintenance(self):
        # every line that is left is pinned: nothing is left reporting
        _write(self.tree, deploy=OK)
        event, = self._new()
        self.assertEqual((*_moved(event), event.suppressed_by),
                         (OK, MAINTENANCE, ""))

    def test_without_a_pin_a_change_is_one_row_as_it_was(self):
        tree, _ = _tree()
        _write(tree, deploy=OK, tests=OK)
        _write(tree, deploy=ERROR, tests=OK)
        first, broke = _events(tree)
        self.assertEqual((_moved(first), _moved(broke)),
                         ((UNDEFINED, OK), (OK, ERROR)))
        self.assertEqual(broke.suppressed_by, "")

    def test_beneath_a_node_s_pin_a_change_is_held_back_as_it_was(self):
        tree, _ = _tree()
        tree.upsert("/db", OK, "in step")
        tree.set_maintenance("/db", "planned", expires_at=datetime.now(UTC) + _SOON)
        tree.upsert("/db", ERROR, "down")
        event = _events(tree, "/db")[-1]
        self.assertEqual((*_moved(event), event.suppressed_by),
                         (OK, ERROR, "maintenance"))

    def test_a_waiting_escalation_is_still_marked_as_one(self):
        # a rule that delays what a node publishes hides nothing the node shows
        tree, _ = _tree()
        tree.upsert("/db", OK, "in step", escalate_after=3)
        tree.upsert("/db", ERROR, "down", escalate_after=3)
        event = _events(tree, "/db")[-1]
        self.assertEqual((*_moved(event), event.suppressed_by),
                         (OK, ERROR, "damping"))


class FieldTests(TestCase):
    """An event carries its cause and what the check reported."""

    def setUp(self) -> None:
        self.tree, _ = _tree()
        _write(self.tree, deploy=ERROR, tests=OK)

    def _last(self) -> Event:
        return _events(self.tree)[-1]

    def test_a_reading_is_a_cause(self):
        self.assertEqual((self._last().cause, self._last().reported),
                         ("reading", ERROR))

    def test_a_line_s_pin_is_one_set_and_ended(self):
        _pin(self.tree, "deploy")
        self.assertEqual((self._last().cause, self._last().reported),
                         ("line-pin-set", ERROR), "the check reports what it did")
        self.tree.clear_entry_maintenance(PATH, "deploy")
        self.assertEqual((self._last().cause, self._last().reported),
                         ("line-pin-ended", ERROR))

    def test_an_expiry_ends_a_line_s_pin_too(self):
        _pin(self.tree, "deploy")
        self.tree.sweep_expired(now=datetime.now(UTC) + timedelta(hours=2))
        self.assertEqual(self._last().cause, "line-pin-ended")

    def test_a_node_s_pin_is_one_set_edited_and_ended(self):
        soon = datetime.now(UTC) + _SOON
        self.tree.set_maintenance(PATH, "planed", expires_at=soon)
        self.assertEqual((self._last().cause, self._last().reported),
                         ("pin-set", ERROR))
        self.tree.set_maintenance(PATH, "planned", expires_at=soon)
        self.assertEqual((self._last().cause, _moved(self._last())),
                         ("pin-edited", (MAINTENANCE, MAINTENANCE)))
        self.assertEqual(self.tree.history(PATH)[-1].cause, "pin-set",
                         "a period's cause is that of the event that began it")
        self.tree.clear_maintenance(PATH)
        self.assertEqual((self._last().cause, self._last().reported),
                         ("pin-ended", ERROR))

    def test_an_expired_node_s_pin_ended(self):
        self.tree.set_maintenance(PATH, "planned",
                                  expires_at=datetime.now(UTC) + _SOON)
        self.tree.sweep_expired(now=datetime.now(UTC) + timedelta(hours=2))
        self.assertEqual(self._last().cause, "pin-ended")

    def test_a_pinned_container_reports_nothing(self):
        tree, _ = _tree()
        tree.set_maintenance("/hosts", "kernel", expires_at=datetime.now(UTC) + _SOON)
        event, = tree.recent_events()
        self.assertEqual((event.cause, event.reported), ("pin-set", UNDEFINED))

    def test_both_rows_of_one_run_say_what_it_reported(self):
        _write(self.tree, deploy=OK, tests=OK)
        _pin(self.tree, "deploy")
        _write(self.tree, deploy=ERROR, tests=WARN)
        shown, hidden = _events(self.tree)[-2:]
        self.assertEqual([(event.cause, event.reported) for event in (shown, hidden)],
                         [("reading", ERROR), ("reading", ERROR)])

    def test_the_kept_log_carries_both(self):
        _pin(self.tree, "deploy")
        raw = self.tree.events_payload()["events"][-1]
        self.assertEqual((raw["cause"], raw["reported"]), ("line-pin-set", "ERROR"))
        self.assertEqual(Event.from_dict(json.loads(json.dumps(raw))), self._last())

    def test_an_event_written_before_them_reads_as_it_did(self):
        raw = {"path": "/db", "name": "db", "old": "OK", "new": "ERROR",
               "reason": ["down"], "timestamp": "2026-09-26T10:00:00Z",
               "suppressed_by": ""}
        event = Event.from_dict(raw)
        self.assertEqual((event.cause, event.reported), ("", None))
        self.assertEqual(event.to_dict(), raw, "and is written back as it was")
        self.assertEqual(Event(path="/db", name="db", old=OK, new=ERROR,
                               reason=("down",),
                               timestamp=datetime(2026, 9, 26, 10, 0, tzinfo=UTC)),
                         event, "and an event is still built without them")

    def test_a_reported_code_nobody_knows_refuses_the_file(self):
        raw = {**self._last().to_dict(), "reported": "NOPE"}
        with self.assertRaises(ValueError):
            events_from_payload({"events": [raw]})


class ChangeCountTests(TestCase):
    """The count of a node's changes counts what its check reported."""

    def _changes(self, tree: StatusTree) -> int:
        node = tree.snapshot(PATH)
        assert node is not None
        return node.changes

    def test_a_pin_s_row_is_no_change(self):
        tree, _ = _tree()
        _write(tree, deploy=ERROR, tests=OK)
        _pin(tree, "deploy")                           # error → ok, and no reading
        tree.clear_entry_maintenance(PATH, "deploy")   # ok → error
        self.assertEqual(len(_events(tree)), 3)
        self.assertEqual(self._changes(tree), 0)

    def test_a_run_that_wrote_two_rows_is_one(self):
        tree, _ = _tree()
        _write(tree, deploy=OK, tests=OK)
        _pin(tree, "deploy")
        _write(tree, deploy=ERROR, tests=WARN)
        self.assertEqual(self._changes(tree), 1)

    def test_a_change_beneath_a_pin_counts_as_it_did(self):
        tree, _ = _tree()
        _write(tree, deploy=OK, tests=OK)
        _pin(tree, "deploy")
        _write(tree, deploy=ERROR, tests=OK)
        _write(tree, deploy=OK, tests=OK)
        self.assertEqual(self._changes(tree), 2)

    def test_a_change_only_the_node_shows_is_none_of_the_reading_s(self):
        tree, _ = _tree()
        _write(tree, deploy=ERROR, tests=OK)
        _pin(tree, "deploy")
        _write(tree, deploy=ERROR, tests=OK, lint=ERROR)   # ok → error on the wall
        self.assertEqual(self._changes(tree), 0)

    def test_a_reading_whose_earlier_rows_left_the_log_counts_by_its_own(self):
        tree = StatusTree(event_log_size=1)
        _write(tree, deploy=OK)
        _write(tree, deploy=ERROR)
        self.assertEqual(len(tree.recent_events()), 1)
        self.assertEqual(self._changes(tree), 1)

    def test_a_pin_s_row_alone_in_the_log_is_no_change_either(self):
        tree = StatusTree(event_log_size=1)
        _write(tree, deploy=ERROR, tests=OK)
        _pin(tree, "deploy")
        tree.clear_entry_maintenance(PATH, "deploy")     # ok → error, kept alone
        self.assertEqual([_moved(event) for event in tree.recent_events()],
                         [(OK, ERROR)])
        self.assertEqual(self._changes(tree), 0)

    def test_a_row_written_before_the_field_counts_by_its_own_codes(self):
        tree = StatusTree()
        tree.restore_events([Event(
            path=PATH, name="actions", old=OK, new=ERROR, reason=(),
            timestamp=datetime.now(UTC) - timedelta(minutes=5))])
        tree.upsert(PATH, ERROR, "down")
        self.assertEqual(self._changes(tree), 1)

    def test_a_log_written_before_the_field_counts_as_it_did(self):
        now = datetime.now(UTC).replace(microsecond=0)
        tree = StatusTree()
        tree.restore_events([
            Event(path=PATH, name="actions", old=old, new=new, reason=(),
                  timestamp=now - timedelta(minutes=minutes),
                  suppressed_by=held)
            for old, new, minutes, held in (
                (UNDEFINED, OK, 50, ""), (OK, ERROR, 40, ""),
                (ERROR, MAINTENANCE, 30, ""), (ERROR, WARN, 20, "maintenance"),
                (MAINTENANCE, WARN, 10, ""))])
        tree.upsert(PATH, WARN, "slow")
        self.assertEqual(self._changes(tree), 2,
                         "ok → error, and error → warn beneath the pin")


class RestartTests(TestCase):
    """A restart replays nothing, and the first reading settles it."""

    def _since(self, tree: StatusTree, count: int) -> list[Event]:
        return list(tree.recent_events())[count:]

    def test_a_line_s_pin_in_force_across_it_writes_nothing(self):
        old, kept = _tree()
        _write(old, deploy=ERROR, tests=OK)
        _pin(old, "deploy")
        new = _restarted(old, kept)
        self.assertEqual(len(new.recent_events()), len(old.recent_events()),
                         "the pins' return wrote nothing")
        self.assertFalse(_write(new, deploy=ERROR, tests=OK))
        self.assertEqual(len(new.recent_events()), len(old.recent_events()))
        self.assertIs(_shows(new), OK)

    def test_a_line_s_pin_that_ran_out_ends_at_the_first_reading(self):
        old, kept = _tree()
        _write(old, deploy=ERROR, tests=OK)
        _pin(old, "deploy")                               # for an hour
        new = _restarted(old, kept, after=timedelta(hours=5))
        count = len(new.recent_events())
        self.assertEqual(count, len(old.recent_events()), "nothing at the restart")
        self.assertTrue(_write(new, deploy=ERROR, tests=OK))
        event, = self._since(new, count)
        self.assertEqual((_moved(event), event.cause, event.suppressed_by),
                         ((OK, ERROR), "line-pin-ended", ""))
        node = new.snapshot(PATH)
        assert node is not None
        self.assertEqual(event.timestamp, node.timestamp,
                         "dated by the reading that saw it (ADR-0094 decision 3)")

    def test_what_the_reading_changed_is_the_reading_s(self):
        # the pin ran out, and had it held the node would not show what it showed
        old, kept = _tree()
        _write(old, deploy=ERROR, tests=OK)
        _pin(old, "deploy")
        new = _restarted(old, kept, after=timedelta(hours=5))
        count = len(new.recent_events())
        _write(new, deploy=OK, tests=ERROR)
        event, = self._since(new, count)
        self.assertEqual((_moved(event), event.cause), ((OK, ERROR), "reading"))

    def test_a_node_s_pin_that_ran_out_ends_at_the_first_reading(self):
        # it wrote nothing, and History said maintenance over a node showing warn
        old, kept = _tree()
        old.upsert("/db", WARN, "lagging")
        old.set_maintenance("/db", "resync", expires_at=datetime.now(UTC) + _SOON)
        new = _restarted(old, kept, after=timedelta(hours=5))
        count = len(new.recent_events())
        self.assertIsNone(new.maintenance_entry("/db"))
        self.assertTrue(new.upsert("/db", WARN, "lagging"))
        event, = self._since(new, count)
        self.assertEqual((_moved(event), event.cause, event.suppressed_by),
                         ((MAINTENANCE, WARN), "pin-ended", ""))
        self.assertEqual([period.code for period in new.history("/db")],
                         [WARN, MAINTENANCE, WARN])

    def test_a_branch_s_pin_that_ran_out_ends_at_its_own_expiry(self):
        # nothing reports to a branch, so no reading will come to end its pin
        old, kept = _tree()
        old.upsert("/hosts/a/cpu", OK, "fine")
        old.set_maintenance("/hosts/a", "kernel",
                            expires_at=datetime.now(UTC) + _SOON)
        pin = old.maintenance_entry("/hosts/a")
        assert pin is not None
        new = _restarted(old, kept, after=timedelta(hours=5))
        event = new.recent_events()[-1]
        self.assertEqual(
            (event.path, _moved(event), event.cause, event.reported),
            ("/hosts/a", (MAINTENANCE, UNDEFINED), "pin-ended", UNDEFINED))
        self.assertEqual(event.timestamp, pin.expires_at,
                         "the pin's own end: nothing else is claimed")
        self.assertIsNone(new.snapshot("/hosts/a"), "and no node is made for it")
        new.upsert("/hosts/a/cpu", OK, "fine")
        self.assertEqual(_events(new, "/hosts/a")[-1], event,
                         "a reading beneath it adds nothing")

    def test_a_branch_pinned_again_is_set_from_what_its_end_left(self):
        old, kept = _tree()
        old.set_maintenance("/hosts/a", "kernel",
                            expires_at=datetime.now(UTC) + _SOON)
        new = _restarted(old, kept, after=timedelta(hours=5))
        new.set_maintenance("/hosts/a", "again",
                            expires_at=datetime.now(UTC) + timedelta(days=1))
        self.assertEqual(_moved(new.recent_events()[-1]),
                         (UNDEFINED, MAINTENANCE))

    def test_a_ran_out_pin_the_log_does_not_hold_writes_nothing(self):
        # the pins file names a node the kept log says nothing of
        now = datetime.now(UTC)
        new = StatusTree()
        new.restore_maintenance({"/hosts/a": MaintenanceEntry(
            "kernel", now - timedelta(hours=3),
            now - timedelta(hours=1))})
        self.assertEqual(new.recent_events(), ())

    def test_two_lines_pins_that_ran_out_end_together(self):
        old, kept = _tree()
        _write(old, deploy=ERROR, tests=WARN, build=OK)
        _pin(old, "deploy")
        _pin(old, "tests")
        self.assertIs(_shows(old), OK)
        new = _restarted(old, kept, after=timedelta(hours=5))
        count = len(new.recent_events())
        _write(new, deploy=ERROR, tests=WARN, build=OK)
        event, = self._since(new, count)
        self.assertEqual((_moved(event), event.cause),
                         ((OK, ERROR), "line-pin-ended"))

    def test_a_node_s_pin_and_a_line_s_that_ran_out_end_as_the_node_s(self):
        old, kept = _tree()
        _write(old, deploy=ERROR, tests=OK)
        _pin(old, "deploy")
        old.set_maintenance(PATH, "fleet replaced",
                            expires_at=datetime.now(UTC) + _SOON)
        new = _restarted(old, kept, after=timedelta(hours=5))
        count = len(new.recent_events())
        _write(new, deploy=ERROR, tests=OK)
        event, = self._since(new, count)
        self.assertEqual((_moved(event), event.cause),
                         ((MAINTENANCE, ERROR), "pin-ended"))

    def test_a_branch_s_pin_in_force_across_it_writes_nothing(self):
        old, kept = _tree()
        old.set_maintenance("/hosts/a", "kernel",
                            expires_at=datetime.now(UTC) + _SOON)
        new = _restarted(old, kept)
        self.assertEqual(len(new.recent_events()), len(old.recent_events()))

    def test_a_node_s_pin_in_force_across_it_writes_nothing(self):
        old, kept = _tree()
        old.upsert("/db", WARN, "lagging")
        old.set_maintenance("/db", "resync", expires_at=datetime.now(UTC) + _SOON)
        new = _restarted(old, kept)
        count = len(new.recent_events())
        self.assertEqual(count, len(old.recent_events()))
        self.assertFalse(new.upsert("/db", WARN, "lagging"))
        self.assertEqual(self._since(new, count), [])

    def test_a_change_beneath_a_pin_still_in_force_is_held_back(self):
        old, kept = _tree()
        _write(old, deploy=OK, tests=OK)
        _pin(old, "deploy")
        new = _restarted(old, kept)
        count = len(new.recent_events())
        self.assertTrue(_write(new, deploy=ERROR, tests=OK))
        event, = self._since(new, count)
        self.assertEqual((_moved(event), event.suppressed_by, event.cause),
                         ((OK, ERROR), "maintenance", "reading"))

    def test_what_a_check_last_reported_is_read_and_not_worked_out(self):
        # the one shape the rows' codes get wrong: a pinned line takes over the
        # status an unpinned line drops, so the node moves and the reading does not
        old, kept = _tree()
        _write(old, deploy=OK, tests=WARN)
        _pin(old, "deploy")
        _write(old, deploy=WARN, tests=OK)
        last = _events(old)[-1]
        self.assertEqual((_moved(last), last.reported), ((WARN, OK), WARN))
        new = _restarted(old, kept)
        count = len(new.recent_events())
        self.assertFalse(_write(new, deploy=WARN, tests=OK),
                         "the check reports what it reported")
        self.assertEqual(self._since(new, count), [])

    def test_a_pin_set_before_the_first_reading_is_set_from_what_the_log_showed(self):
        old, kept = _tree()
        old.upsert("/db", OK, "in step")
        new = _restarted(old, kept)
        new.set_maintenance("/db", "planned", expires_at=datetime.now(UTC) + _SOON)
        event = new.recent_events()[-1]
        self.assertEqual((_moved(event), event.reported), ((OK, MAINTENANCE), OK))
        self.assertFalse(new.upsert("/db", OK, "in step"),
                         "and the reading beneath it is what it was")

    def test_a_pin_cleared_before_the_first_reading_shows_nothing_until_it(self):
        old, kept = _tree()
        old.upsert("/db", WARN, "lagging")
        old.set_maintenance("/db", "resync", expires_at=datetime.now(UTC) + _SOON)
        new = _restarted(old, kept)
        new.clear_maintenance("/db")
        cleared = new.recent_events()[-1]
        self.assertEqual((_moved(cleared), cleared.reported),
                         ((MAINTENANCE, UNDEFINED), WARN))
        self.assertTrue(new.upsert("/db", WARN, "lagging"))
        event = new.recent_events()[-1]
        self.assertEqual((_moved(event), event.cause, event.suppressed_by),
                         ((UNDEFINED, WARN), "reading", ""))
        self.assertEqual([period.code for period in new.history("/db")],
                         [WARN, MAINTENANCE, UNDEFINED, WARN])

    def test_the_gap_s_row_names_no_cause_and_reports_nothing(self):
        # the instance's own node, closed where the old process stopped watching
        old, kept = _tree()
        old.upsert("/little-sister", OK)
        new = _restarted(old, kept)
        self.assertTrue(new.close_unobserved(
            "/little-sister", datetime.now(UTC), "not running"))
        event = new.recent_events()[-1]
        self.assertEqual((event.cause, event.reported), ("", UNDEFINED))
        self.assertTrue(new.upsert("/little-sister", OK))
        beat = new.recent_events()[-1]
        self.assertEqual((_moved(beat), beat.cause), ((UNDEFINED, OK), "reading"))

    def test_a_log_without_the_fields_is_worked_out_as_it_was(self):
        # an admin's pin, written before the fields: the reading is the one its set
        # left under it, and a change of it across the restart is held back
        now = datetime.now(UTC).replace(microsecond=0)
        entry = MaintenanceEntry("planned", now,
                                 now + _SOON)
        new = StatusTree()
        new.restore_events([
            Event(path="/db", name="db", old=UNDEFINED, new=OK, reason=(),
                  timestamp=now - timedelta(minutes=9)),
            Event(path="/db", name="db", old=OK, new=MAINTENANCE,
                  reason=("planned",),
                  timestamp=now - timedelta(minutes=5))])
        new.restore_maintenance({"/db": entry})
        self.assertEqual(len(new.recent_events()), 2)
        self.assertTrue(new.upsert("/db", ERROR, "down"))
        event = new.recent_events()[-1]
        self.assertEqual((_moved(event), event.suppressed_by, event.reported),
                         ((OK, ERROR), "maintenance", ERROR))


class _Pages(TestCase):
    """A tree the pages read, signed in as an admin."""

    def setUp(self) -> None:
        app_module.app.config["TESTING"] = True
        self._saved = app_module.status_tree
        self.addCleanup(self._restore)
        self.client = app_module.app.test_client()
        self.client.post("/login",
                         data={"username": "pan", "password": "12345678"})
        self.tree, self.kept = _tree()
        app_module.status_tree = self.tree

    def _restore(self) -> None:
        app_module.status_tree = self._saved

    def _page(self, url: str) -> Element:
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200, url)
        return parse(response.get_data(as_text=True))

    @staticmethod
    def _shown(stamp: str) -> str:
        """An instant as a page writes it."""
        return str(app_module.app.jinja_env.filters["localtime"](stamp))

    def _period(self, url: str = "/status" + PATH) -> str:
        """The Time card's sentence about the status that holds."""
        for paragraph in self._page(url).all(tag="p"):
            text = paragraph.text()
            if text.startswith("Status "):
                return text
        self.fail(f"no period on {url}")

    def _last(self) -> Event:
        return _events(self.tree)[-1]


class EventsPageTests(_Pages):
    """A row that a pin caused says so, in a chip beside its status."""

    def _rows(self, url: str = "/events") -> list[tuple[str, list[str], list[str]]]:
        """Each row, newest first: its status cell's words, the chips that say what
        caused it and the chips that say what held it back."""
        table = self._page(url).all(tag="table")[0]
        rows = []
        for row in table.one(tag="tbody").all(tag="tr"):
            cell = row.all(tag="td")[1]
            rows.append((cell.text(),
                         [chip.text() for chip in cell.all("event-cause")],
                         [chip.text() for chip in cell.all("event-suppressed")]))
        return rows

    def test_a_row_a_pin_caused_says_so(self):
        soon = datetime.now(UTC) + _SOON
        _write(self.tree, deploy=ERROR, tests=OK)
        _pin(self.tree, "deploy")
        self.tree.clear_entry_maintenance(PATH, "deploy")
        self.tree.set_maintenance(PATH, "planed", expires_at=soon)
        self.tree.set_maintenance(PATH, "planned", expires_at=soon)
        self.tree.clear_maintenance(PATH)
        self.assertEqual(self._rows(), [
            ("error maintenance ended", ["maintenance ended"], []),
            ("maintenance edited", ["edited"], []),
            ("maintenance set", ["set"], []),
            ("error line's maintenance ended", ["line's maintenance ended"], []),
            ("ok line silenced", ["line silenced"], []),
            ("error", [], [])])

    def test_a_held_back_row_keeps_its_mark_and_a_reading_has_no_chip(self):
        _write(self.tree, deploy=OK, tests=OK)
        _pin(self.tree, "deploy")
        _write(self.tree, deploy=ERROR, tests=WARN)
        self.assertEqual(self._rows(), [
            ("error maintenance", [], ["maintenance"]),
            ("warn", [], []),
            ("ok", [], [])])
        self.assertEqual(self._rows("/events?held=yes"),
                         [("error maintenance", [], ["maintenance"])],
                         "what the pin hid, that run included")

    def test_a_row_written_before_the_field_has_no_chip(self):
        self.tree.restore_events([Event(
            path="/db", name="db", old=MAINTENANCE, new=OK, reason=("in step",),
            timestamp=datetime(2026, 9, 26, 10, 0, tzinfo=UTC))])
        self.assertEqual(self._rows(), [("ok", [], [])])


class TimeCardTests(_Pages):
    """A period says what kind of beginning it had (ADR-0099 decision 8, one level
    down)."""

    def test_a_period_a_line_s_pin_began_says_so(self):
        _write(self.tree, deploy=ERROR, tests=OK)
        _pin(self.tree, "deploy")
        self.assertEqual(
            self._period(),
            f"Status ok since {self._shown(self._last().timestamp)}, "
            f"when a line was silenced")

    def test_and_so_does_one_its_end_began(self):
        _write(self.tree, deploy=ERROR, tests=OK)
        _pin(self.tree, "deploy")
        self.tree.clear_entry_maintenance(PATH, "deploy")
        self.assertEqual(
            self._period(),
            f"Status error since {self._shown(self._last().timestamp)}, "
            f"when a line's maintenance ended")

    def test_maintenance_says_nothing_more_however_it_began(self):
        _write(self.tree, deploy=ERROR)
        _pin(self.tree, "deploy")
        self.assertEqual(_moved(self._last()), (ERROR, MAINTENANCE))
        self.assertEqual(
            self._period(),
            f"Status maintenance since {self._shown(self._last().timestamp)}")

    def test_the_end_of_every_line_s_silence_is_the_end_of_maintenance(self):
        _write(self.tree, deploy=ERROR)
        _pin(self.tree, "deploy")
        self.tree.clear_entry_maintenance(PATH, "deploy")
        self.assertEqual(
            self._period(),
            f"Status error since {self._shown(self._last().timestamp)}, "
            f"when its maintenance ended")

    def test_a_period_a_line_s_coming_began_says_nothing_more(self):
        _write(self.tree, deploy=ERROR, tests=OK)
        _pin(self.tree, "deploy")
        _write(self.tree, deploy=ERROR, tests=OK, lint=ERROR)
        self.assertEqual(_moved(self._last()), (OK, ERROR))
        self.assertEqual(
            self._period(),
            f"Status error since {self._shown(self._last().timestamp)}")


class CopyTests(_Pages):
    """The Copy document says the same."""

    def _source(self) -> str:
        return self._page("/copy" + PATH).with_id("ls-copy-source").source()

    def test_a_period_a_line_s_pin_began_says_so(self):
        _write(self.tree, deploy=ERROR, tests=OK)
        _pin(self.tree, "deploy")
        style: TimeStyle = app_module._copy_style()
        expected = (f"- **Status ok** since {style.at(self._last().timestamp)}, "
                    f"when a line was silenced\n")
        self.assertIn(expected, self._source())

    def test_and_so_does_one_its_end_began(self):
        _write(self.tree, deploy=ERROR, tests=OK)
        _pin(self.tree, "deploy")
        self.tree.clear_entry_maintenance(PATH, "deploy")
        style: TimeStyle = app_module._copy_style()
        expected = (f"- **Status error** since {style.at(self._last().timestamp)}, "
                    f"when a line's maintenance ended\n")
        self.assertIn(expected, self._source())


class HistoryPageTests(_Pages):
    """History lists what the node showed."""

    def test_a_silenced_line_s_window_is_a_row_between_the_statuses_around_it(self):
        _write(self.tree, deploy=ERROR, tests=OK)
        first = self._last().timestamp
        _pin(self.tree, "deploy", "flaky runner")
        silenced = self._last().timestamp
        self.tree.clear_entry_maintenance(PATH, "deploy")
        ended = self._last().timestamp
        table = self._page("/history" + PATH).all(tag="table")[0]
        rows = [[cell.text() for cell in row.all(tag="td")]
                for row in table.one(tag="tbody").all(tag="tr")]
        self.assertEqual(rows, [
            ["error", self._shown(ended), "current", "deploy: error; tests: ok"],
            ["ok", self._shown(silenced), self._shown(ended),
             "deploy: error; flaky runner"],
            ["error", f"before {self._shown(first)}", self._shown(silenced),
             "deploy: error; tests: ok"]])
