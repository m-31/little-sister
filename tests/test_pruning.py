"""What a run no longer reports is removed (ADR-0109).

The tree removed no node. A child a later run stopped returning stayed, went stale
and degraded everything above it until the process restarted — which a subject that
has a node of its own (ADR-0106) and comes and goes cannot live with.

* A node in a result may say that its children are complete, and only then is a
  direct child it no longer returns removed, at once. Silence keeps.
* The statement covers the node's direct children as far as its own check writes
  them, and nothing beneath a child it kept.
* A removal takes the node and nothing kept about it: its readings stay, its history
  is the log's, and a pin on it is suspended until the node returns or the pin
  expires.
* Each node removed writes an event, from what it showed to nothing, with the cause
  *removed* — the first run after a restart too.
"""
from __future__ import annotations

import json
import os
from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from typing import Any
from unittest import TestCase

os.environ.setdefault("SECRET_KEY", "test-key")

from little_sister import instants
from little_sister.checks.base import Check, CheckError, CheckResult, Measurement
from little_sister.engine import Engine
from little_sister.pins import Pin
from little_sister.reasons import Entry
from little_sister.series import SeriesKey
from little_sister.status import HEARTBEAT_PATH, StatusCode
from little_sister.tree import (
    CAUSE_PIN_EDITED,
    CAUSE_PIN_ENDED,
    CAUSE_READING,
    CAUSE_REMOVED,
    Event,
    StatusTree,
    events_from_payload,
    nodes_from_payload,
)

OK, WARN, ERROR = StatusCode.OK, StatusCode.WARN, StatusCode.ERROR
MAINTENANCE, UNDEFINED = StatusCode.MAINTENANCE, StatusCode.UNDEFINED

JOBS = "/ci/jobs"
IMPORT, EXPORT = "/ci/jobs/import", "/ci/jobs/export"
EU, US = "/ci/jobs/export/eu", "/ci/jobs/export/us"
GONE = ("no longer reported by its check",)
_SOON = timedelta(hours=1)


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


def _grown(tree: StatusTree | None = None) -> StatusTree:
    """A check's branch as its runs left it: a container that declares nothing, a
    job that passes, and one that fails above two regions of its own."""
    tree = tree if tree is not None else StatusTree(pin_store=_Pins())
    tree.upsert(JOBS, UNDEFINED, "watches two jobs")
    tree.upsert(IMPORT, OK, "run 7 succeeded")
    tree.upsert(EXPORT, ERROR, {"newest": "run 3 failed", "queued": "run 4 waits"})
    tree.upsert(EU, OK, "eu is fine")
    tree.upsert(US, WARN, "us is slow")
    return tree


def _rows(tree: StatusTree, path: str | None = None) -> list[Event]:
    return [event for event in tree.recent_events()
            if path is None or event.path == path]


def _removals(tree: StatusTree) -> list[Event]:
    return [event for event in tree.recent_events() if event.cause == CAUSE_REMOVED]


def _kept(tree: StatusTree) -> dict[str, Any]:
    """What the tree writes to its file, through the file's own shape."""
    kept: dict[str, Any] = json.loads(json.dumps(tree.events_payload()))
    return kept


def _restarted(old: StatusTree, **options: Any) -> StatusTree:
    """A new process's tree, with the log the old one kept."""
    payload = _kept(old)
    tree = StatusTree(pin_store=_Pins(), **options)
    tree.restore_events(events_from_payload(payload), nodes_from_payload(payload))
    return tree


def _suspended(tree: StatusTree) -> tuple[
        dict[str, Pin], dict[tuple[str, str], Pin]]:
    """The pins held against a path the tree holds no node at: the nodes' own, and
    their lines'."""
    nodes, lines = tree.pins()
    return ({path: pin for path, pin in nodes.items()
             if tree.snapshot(path) is None},
            {key: pin for key, pin in lines.items()
             if tree.snapshot(key[0]) is None})


def _pin(tree: StatusTree, path: str, note: str = "being moved",
         lasts: timedelta = _SOON) -> Pin:
    write = tree.set_maintenance(path, note, expires_at=datetime.now(UTC) + lasts,
                                 set_by="lex")
    assert write.current is not None
    return write.current


class SeamTests(TestCase):
    """A node of a result says that its children are complete (decision 1)."""

    def test_a_result_says_nothing_unless_it_is_told_to(self) -> None:
        self.assertIs(CheckResult(OK).children_complete, False)

    def test_a_node_says_its_children_are_complete(self) -> None:
        result = CheckResult(UNDEFINED, children=(CheckResult(OK, name="import"),),
                             children_complete=True)
        self.assertIs(result.children_complete, True)
        # and a node with none may say so: every child it had is gone
        self.assertIs(CheckResult(OK, children_complete=True).children_complete, True)

    def test_the_statement_is_true_or_false_and_nothing_else(self) -> None:
        for said in ("yes", 1, None):
            with self.subTest(said=said), self.assertRaisesRegex(
                    CheckError, "children_complete"):
                CheckResult(OK, children_complete=said)  # type: ignore[arg-type]


class RemovalTests(TestCase):
    """A direct child a complete node no longer returns leaves the tree (decisions
    1 and 2)."""

    def test_a_child_that_is_not_kept_is_removed(self) -> None:
        tree = _grown()
        self.assertEqual(tree.prune(JOBS, {"import"}), [EU, US, EXPORT])
        self.assertIsNone(tree.snapshot(EXPORT))
        self.assertIsNone(tree.snapshot(EU))
        jobs = tree.snapshot(JOBS)
        assert jobs is not None
        self.assertEqual([child.name for child in jobs.children], ["import"])

    def test_every_child_goes_where_none_is_kept(self) -> None:
        tree = _grown()
        tree.prune(JOBS, ())
        jobs = tree.snapshot(JOBS)
        assert jobs is not None
        self.assertEqual(jobs.children, ())

    def test_nothing_beneath_a_kept_child_is_looked_at(self) -> None:
        tree = _grown()
        self.assertEqual(tree.prune(JOBS, {"import", "export"}), [])
        self.assertIsNotNone(tree.snapshot(US))
        self.assertEqual(_removals(tree), [])

    def test_a_child_on_another_checks_line_stays(self) -> None:
        # what another check owns, here or beneath, is not this node's to remove
        tree = _grown()
        self.assertEqual(tree.prune(JOBS, (), protect=[EU]), [IMPORT])
        self.assertIsNotNone(tree.snapshot(EXPORT))
        self.assertIsNotNone(tree.snapshot(US))
        tree = _grown()
        self.assertEqual(tree.prune(JOBS, (), protect=["/ci"]), [])

    def test_a_node_the_tree_does_not_hold_has_no_children_to_remove(self) -> None:
        self.assertEqual(StatusTree().prune("/nowhere", ()), [])

    def test_what_the_node_rolled_up_to_leaves_with_it(self) -> None:
        tree = _grown()
        self.assertIs(tree.effective(JOBS), ERROR)
        tree.prune(JOBS, {"import"})
        self.assertIs(tree.effective(JOBS), OK)

    def test_its_lines_are_no_longer_counted(self) -> None:
        tree = _grown()
        held = tree.entry_count
        tree.prune(JOBS, {"import"})
        # export held two lines, and its regions one each
        self.assertEqual(tree.entry_count, held - 4)


class EventTests(TestCase):
    """A removal is an event, one for each node removed (decision 5)."""

    def test_each_node_removed_writes_a_row_from_what_it_showed_to_nothing(
            self) -> None:
        tree = _grown()
        tree.prune(JOBS, {"import"})
        self.assertEqual(
            [(row.path, row.name, row.old, row.new, row.reason, row.suppressed_by,
              row.reported) for row in _removals(tree)],
            [(EU, "eu", OK, UNDEFINED, GONE, "", UNDEFINED),
             (US, "us", WARN, UNDEFINED, GONE, "", UNDEFINED),
             (EXPORT, "export", ERROR, UNDEFINED, GONE, "", UNDEFINED)])

    def test_the_rows_of_one_removal_are_written_at_one_instant(self) -> None:
        tree = _grown()
        tree.prune(JOBS, {"import"})
        stamps = {row.timestamp for row in _removals(tree)}
        self.assertEqual(len(stamps), 1)
        self.assertIs(stamps.pop().tzinfo, UTC)

    def test_a_node_that_showed_nothing_has_its_row_too(self) -> None:
        # a container a check wrote: its children are the eleventh row's ten
        tree = _grown()
        tree.upsert("/ci/jobs/nightly", UNDEFINED, "holds two regions")
        tree.upsert("/ci/jobs/nightly/eu", OK, "fine")
        tree.prune(JOBS, {"import", "export"})
        self.assertEqual(
            [(row.path, row.old, row.new) for row in _removals(tree)],
            [("/ci/jobs/nightly/eu", OK, UNDEFINED),
             ("/ci/jobs/nightly", UNDEFINED, UNDEFINED)])

    def test_a_node_no_check_ever_wrote_leaves_without_a_row(self) -> None:
        # a label a deployment declared for a node its check does not report:
        # nothing is removed that was never there
        tree = _grown()
        tree.set_about("/ci/jobs/planned", "runs from next month")
        self.assertEqual(tree.prune(JOBS, {"import", "export"}), ["/ci/jobs/planned"])
        self.assertIsNone(tree.snapshot("/ci/jobs/planned"))
        self.assertEqual(_removals(tree), [])

    def test_the_row_survives_the_file(self) -> None:
        tree = _grown()
        tree.prune(JOBS, {"import"})
        read = events_from_payload(_kept(tree))
        self.assertEqual([row.cause for row in read if row.path == EXPORT][-1],
                         CAUSE_REMOVED)

    def test_a_removal_ends_the_nodes_last_period_and_its_return_begins_one(
            self) -> None:
        tree = _grown()
        tree.prune(JOBS, {"import"})
        tree.upsert(EXPORT, OK, "run 5 succeeded")
        periods = tree.history(EXPORT)
        self.assertEqual(
            [(period.code, period.before, period.cause) for period in periods],
            [(ERROR, True, CAUSE_READING), (UNDEFINED, False, CAUSE_REMOVED),
             (OK, False, CAUSE_READING)])
        # the absence is the gap between the two
        absent = periods[1]
        self.assertEqual((absent.reason, absent.previous), (GONE, ERROR))
        self.assertEqual(absent.until, periods[2].since)
        self.assertIs(periods[2].previous, UNDEFINED)

    def test_a_returning_nodes_first_reading_does_not_wait(self) -> None:
        # nothing is counted from a node that was not there
        tree = _grown()
        tree.prune(JOBS, {"import"})
        tree.upsert(EXPORT, ERROR, "run 5 failed", escalate_after=3)
        node = tree.snapshot(EXPORT)
        assert node is not None
        self.assertIsNone(node.damping)
        self.assertIs(tree.effective(JOBS), ERROR)

    def test_nor_does_one_whose_removal_the_log_no_longer_holds(self) -> None:
        # nothing is kept of it then, its count least of all: it is seen for the
        # first time, and a first reading is published at once (ADR-0083)
        tree = StatusTree(event_log_size=4, pin_store=_Pins())
        tree.upsert(JOBS, UNDEFINED, "watches two jobs")
        tree.upsert(IMPORT, OK, "fine")
        tree.upsert(EXPORT, OK, "run 2 succeeded", escalate_after=3)
        tree.prune(JOBS, {"import"})
        for code in (WARN, OK, WARN, OK):
            tree.upsert(IMPORT, code, "flaps")
        self.assertNotIn(EXPORT, _kept(tree)["nodes"])
        tree.upsert(EXPORT, ERROR, "run 5 failed", escalate_after=3)
        node = tree.snapshot(EXPORT)
        assert node is not None
        self.assertIsNone(node.damping)
        self.assertIs(tree.effective(JOBS), ERROR)


class PinTests(TestCase):
    """Absence suspends a pin, and only its expiry disposes of it (decision 4)."""

    def test_a_pin_on_a_removed_node_stays_suspended(self) -> None:
        tree = _grown()
        pin = _pin(tree, EXPORT)
        tree.prune(JOBS, {"import"})
        self.assertEqual(tree.maintenance_entry(EXPORT), pin)
        nodes, lines = _suspended(tree)
        self.assertEqual((nodes, lines), ({EXPORT: pin}, {}))

    def test_a_pin_on_a_node_the_tree_holds_is_not_suspended(self) -> None:
        tree = _grown()
        _pin(tree, EXPORT)
        self.assertEqual(_suspended(tree), ({}, {}))

    def test_the_removal_of_a_pinned_node_is_written_from_its_maintenance(
            self) -> None:
        tree = _grown()
        _pin(tree, EXPORT)
        tree.prune(JOBS, {"import"})
        row = _rows(tree, EXPORT)[-1]
        self.assertEqual((row.old, row.new, row.cause),
                         (MAINTENANCE, UNDEFINED, CAUSE_REMOVED))

    def test_it_holds_again_the_moment_the_node_returns(self) -> None:
        tree = _grown()
        _pin(tree, EXPORT)
        tree.prune(JOBS, {"import"})
        tree.upsert(EXPORT, ERROR, "run 5 failed")
        node = tree.snapshot(EXPORT)
        assert node is not None
        self.assertIs(node.own_code, MAINTENANCE)
        self.assertTrue(node.maintenance)
        self.assertIs(tree.effective(JOBS), OK)
        self.assertEqual(_suspended(tree), ({}, {}))
        shown = [row for row in _rows(tree, EXPORT) if not row.suppressed_by][-1]
        self.assertEqual((shown.old, shown.new), (UNDEFINED, MAINTENANCE))

    def test_a_pin_on_a_node_beneath_the_removed_one_stays_too(self) -> None:
        tree = _grown()
        pin = _pin(tree, US)
        tree.prune(JOBS, {"import"})
        self.assertEqual(_suspended(tree)[0], {US: pin})

    def test_a_lines_pin_stays_and_silences_the_line_when_it_returns(self) -> None:
        tree = _grown()
        write = tree.set_entry_maintenance(
            EXPORT, "newest", "known", expires_at=datetime.now(UTC) + _SOON,
            set_by="lex")
        tree.prune(JOBS, {"import"})
        self.assertEqual(_suspended(tree),
                         ({}, {(EXPORT, "newest"): write.current}))
        tree.upsert(EXPORT, ERROR, {"newest": "run 3 failed"})
        node = tree.snapshot(EXPORT)
        assert node is not None
        self.assertTrue(node.reasons[0].quiet)

    def test_a_suspended_pin_ends_by_its_own_expiry(self) -> None:
        tree = _grown()
        _pin(tree, EXPORT)
        tree.prune(JOBS, {"import"})
        self.assertEqual(tree.sweep_expired(datetime.now(UTC) + timedelta(hours=2)),
                         [EXPORT])
        self.assertIsNone(tree.maintenance_entry(EXPORT))
        self.assertEqual(_suspended(tree), ({}, {}))
        self.assertIsNone(tree.snapshot(EXPORT))
        # its end is written, as every pin's is, and changes nothing a node shows
        row = _rows(tree, EXPORT)[-1]
        self.assertEqual((row.old, row.new, row.cause),
                         (UNDEFINED, UNDEFINED, CAUSE_PIN_ENDED))

    def test_a_suspended_pin_is_edited_and_cleared_without_making_its_node(
            self) -> None:
        tree = _grown()
        pin = _pin(tree, EXPORT)
        tree.prune(JOBS, {"import"})
        edit = tree.set_maintenance(
            EXPORT, "until the move is done",
            expires_at=datetime.now(UTC) + timedelta(days=2), set_by="anna",
            expected_set_at=pin.token)
        self.assertTrue(edit.applied)
        self.assertIsNone(tree.snapshot(EXPORT))
        row = _rows(tree, EXPORT)[-1]
        self.assertEqual((row.old, row.new, row.cause, row.reason),
                         (UNDEFINED, UNDEFINED, CAUSE_PIN_EDITED,
                          ("until the move is done",)))
        assert edit.current is not None
        cleared = tree.clear_maintenance(EXPORT,
                                         expected_set_at=edit.current.token)
        self.assertTrue(cleared.applied)
        self.assertIsNone(tree.snapshot(EXPORT))
        self.assertEqual(_suspended(tree), ({}, {}))

    def test_the_pins_file_keeps_a_suspended_pin(self) -> None:
        pins = _Pins()
        tree = _grown(StatusTree(pin_store=pins))
        pin = _pin(tree, EXPORT)
        tree.prune(JOBS, {"import"})
        tree.sweep_expired()
        self.assertEqual(pins.nodes, {EXPORT: pin})


class LabelTests(TestCase):
    """What a deployment declared for a node is the node's again when it returns."""

    def test_a_returning_node_has_the_labels_its_deployment_declared(self) -> None:
        tree = StatusTree()
        tree.set_about(EXPORT, "the nightly export")
        tree.set_title(EXPORT, "Export")
        tree.set_order(EXPORT, 3)
        tree.set_show_when_quiet(EXPORT, False)
        tree.set_handbook(EXPORT, "## When it fails\n\nRun it again.")
        _grown(tree)
        tree.prune(JOBS, {"import"})
        self.assertEqual(tree.handbook(EXPORT), "")
        # the check's own labels fill an empty field only, as on a first reading
        tree.upsert(EXPORT, OK, "run 5 succeeded", about="a job", title="export job",
                    handbook="a run's", order=9, show_when_quiet=True)
        node = tree.snapshot(EXPORT)
        assert node is not None
        self.assertEqual((node.about, node.title, node.order, node.show_when_quiet),
                         ("the nightly export", "Export", 3, False))
        self.assertEqual(tree.handbook(EXPORT), "## When it fails\n\nRun it again.")


class KeptTests(TestCase):
    """What the kept file says of a removed node (ADR-0110 decisions 4 and 5)."""

    def test_the_table_says_the_node_shows_nothing_since_its_removal(self) -> None:
        tree = _grown()
        tree.prune(JOBS, {"import"})
        removed = _removals(tree)[-1]
        self.assertEqual(_kept(tree)["nodes"][EXPORT],
                         {"shows": "UNDEFINED", "reported": "UNDEFINED",
                          "since": instants.stamp(removed.timestamp),
                          "was": "ERROR",
                          "cause": CAUSE_REMOVED,
                          # a branch: so does the period of what it shows (ADR-0132)
                          "period": {"code": "UNDEFINED",
                                     "since": instants.stamp(removed.timestamp),
                                     "was": "ERROR", "cause": CAUSE_REMOVED,
                                     "by": EXPORT}})

    def test_the_entry_goes_when_its_row_has_left_the_log(self) -> None:
        tree = StatusTree(event_log_size=4, pin_store=_Pins())
        tree.upsert(JOBS, UNDEFINED, "watches two jobs")
        tree.upsert(IMPORT, OK, "fine")
        tree.upsert(EXPORT, ERROR, "run 3 failed")
        tree.prune(JOBS, {"import"})
        self.assertIn(EXPORT, _kept(tree)["nodes"])
        for code in (WARN, OK, WARN, OK):
            tree.upsert(IMPORT, code, "flaps")
        self.assertEqual(_removals(tree), [])
        self.assertNotIn(EXPORT, _kept(tree)["nodes"])
        # and what returns then is seen for the first time
        tree.upsert(EXPORT, OK, "run 5 succeeded")
        self.assertTrue(tree.history(EXPORT)[-1].before)

    def test_each_entry_goes_with_its_own_row(self) -> None:
        # the log still holds the removal of one node and no longer that of another
        cleanup = "/ci/jobs/cleanup"
        tree = StatusTree(event_log_size=3, pin_store=_Pins())
        tree.upsert(JOBS, UNDEFINED, "watches three jobs")
        tree.upsert(IMPORT, OK, "fine")
        tree.upsert(EXPORT, ERROR, "run 3 failed")
        tree.upsert(cleanup, WARN, "slow")
        tree.prune(JOBS, {"import", "cleanup"})
        tree.upsert(IMPORT, WARN, "flaps")
        tree.upsert(IMPORT, OK, "flaps")
        tree.prune(JOBS, {"import"})
        self.assertEqual([row.path for row in _removals(tree)], [cleanup])
        kept = _kept(tree)["nodes"]
        self.assertNotIn(EXPORT, kept)
        self.assertEqual(kept[cleanup]["cause"], CAUSE_REMOVED)

    def test_the_entry_stays_while_a_pin_is_held_against_the_node(self) -> None:
        tree = StatusTree(event_log_size=4, pin_store=_Pins())
        tree.upsert(JOBS, UNDEFINED, "watches two jobs")
        tree.upsert(IMPORT, OK, "fine")
        tree.upsert(EXPORT, ERROR, "run 3 failed")
        _pin(tree, EXPORT)
        tree.prune(JOBS, {"import"})
        for code in (WARN, OK, WARN, OK):
            tree.upsert(IMPORT, code, "flaps")
        self.assertEqual(_kept(tree)["nodes"][EXPORT]["cause"], CAUSE_REMOVED)
        tree.sweep_expired(datetime.now(UTC) + timedelta(hours=2))
        for code in (WARN, OK, WARN, OK):
            tree.upsert(IMPORT, code, "flaps")
        self.assertNotIn(EXPORT, _kept(tree)["nodes"])


class RestartTests(TestCase):
    """The first run after a restart writes the same event (decision 5)."""

    def _first_run(self, tree: StatusTree) -> list[str]:
        """The check's first run in the new process: it returns `import` alone and
        says that its children are complete."""
        tree.upsert(JOBS, UNDEFINED, "watches two jobs")
        tree.upsert(IMPORT, OK, "run 8 succeeded")
        return tree.prune(JOBS, {"import"})

    def test_a_node_that_went_while_the_process_was_down_ends_its_period(
            self) -> None:
        tree = _restarted(_grown())
        self.assertEqual(self._first_run(tree), [EU, US, EXPORT])
        self.assertEqual(
            [(row.path, row.old, row.new, row.reason) for row in _removals(tree)],
            [(EU, OK, UNDEFINED, GONE), (US, WARN, UNDEFINED, GONE),
             (EXPORT, ERROR, UNDEFINED, GONE)])
        # and what is kept of it says so, as of a node removed while it was watched
        removed = instants.stamp(_removals(tree)[-1].timestamp)
        self.assertEqual(_kept(tree)["nodes"][EXPORT], {
            "shows": "UNDEFINED", "reported": "UNDEFINED",
            "since": removed,
            "was": "ERROR",
            "cause": CAUSE_REMOVED,
            "period": {"code": "UNDEFINED", "since": removed, "was": "ERROR",
                       "cause": CAUSE_REMOVED, "by": EXPORT}})

    def test_nothing_is_written_for_a_node_that_showed_nothing(self) -> None:
        old = _grown()
        old.upsert("/ci/jobs/nightly", UNDEFINED, "holds two regions")
        tree = _restarted(old)
        tree.upsert(EXPORT, ERROR, {"newest": "run 3 failed", "queued": "run 4 waits"})
        tree.upsert(EU, OK, "eu is fine")
        tree.upsert(US, WARN, "us is slow")
        tree.upsert(JOBS, UNDEFINED, "watches two jobs")
        tree.upsert(IMPORT, OK, "run 8 succeeded")
        self.assertEqual(tree.prune(JOBS, {"import", "export"}), [])
        self.assertEqual(_removals(tree), [])

    def test_what_was_kept_of_a_node_that_showed_nothing_goes_without_a_row(
            self) -> None:
        # the old process saw it begin to show nothing, which is a period the
        # table keeps (ADR-0110 decision 5); gone at the first run, the entry
        # would stand for a node nobody reports, for good
        old = _grown()
        old.upsert("/ci/jobs/nightly", OK, "fine")
        old.upsert("/ci/jobs/nightly", UNDEFINED)
        tree = _restarted(old)
        self.assertEqual(_kept(tree)["nodes"]["/ci/jobs/nightly"]["shows"],
                         "UNDEFINED")
        tree.upsert(JOBS, UNDEFINED, "watches two jobs")
        tree.upsert(IMPORT, OK, "run 8 succeeded")
        tree.upsert(EXPORT, ERROR, {"newest": "run 3 failed", "queued": "run 4 waits"})
        self.assertEqual(tree.prune(JOBS, {"import", "export"}),
                         ["/ci/jobs/nightly"])
        self.assertEqual(_removals(tree), [])
        self.assertNotIn("/ci/jobs/nightly", _kept(tree)["nodes"])
        # beneath a child that is kept nothing is looked at
        self.assertIn(US, _kept(tree)["nodes"])

    def test_what_is_kept_of_a_node_elsewhere_is_no_business_of_this_one(
            self) -> None:
        old = _grown()
        old.upsert("/services/web/eu", ERROR, "down")
        tree = _restarted(old)
        self._first_run(tree)
        self.assertEqual({row.path for row in _removals(tree)}, {EU, US, EXPORT})
        self.assertEqual(_kept(tree)["nodes"]["/services/web/eu"]["shows"], "ERROR")

    def test_nor_is_what_is_kept_of_the_node_itself(self) -> None:
        # a branch pinned whole, which no check writes: the tree makes it on the
        # way to its child, and what the file said of it stands
        old = _grown()
        pin = _pin(old, JOBS)
        tree = _restarted(old)
        tree.restore_maintenance({JOBS: pin})
        tree.upsert(IMPORT, OK, "run 8 succeeded")
        self.assertEqual(tree.prune(JOBS, {"import"}), [EU, US, EXPORT])
        self.assertEqual(_kept(tree)["nodes"][JOBS]["shows"], "MAINTENANCE")
        self.assertIs(tree.effective(JOBS), MAINTENANCE)

    def test_the_run_after_that_writes_nothing_more(self) -> None:
        tree = _restarted(_grown())
        self._first_run(tree)
        written = len(tree.recent_events())
        self.assertEqual(tree.prune(JOBS, {"import"}), [])
        self.assertEqual(len(tree.recent_events()), written)

    def test_a_removed_node_stays_removed_across_a_restart(self) -> None:
        old = _grown()
        old.prune(JOBS, {"import"})
        tree = _restarted(old)
        written = len(tree.recent_events())
        self.assertEqual(self._first_run(tree), [])
        self.assertEqual(len(tree.recent_events()), written)
        # and its return is a change the tree saw, as before the restart
        tree.upsert(EXPORT, OK, "run 5 succeeded")
        self.assertFalse(tree.history(EXPORT)[-1].before)

    def test_a_node_another_check_owns_is_not_ended(self) -> None:
        tree = _restarted(_grown())
        tree.upsert(JOBS, UNDEFINED, "watches two jobs")
        self.assertEqual(tree.prune(JOBS, (), protect=[EXPORT]), [IMPORT])

    def test_a_replayed_pin_makes_no_node(self) -> None:
        # a restart that brings the pins back no longer brings back a node for each
        old = _grown()
        pin = _pin(old, EXPORT)
        tree = _restarted(old)
        written = len(tree.recent_events())
        tree.restore_maintenance({EXPORT: pin})
        self.assertIsNone(tree.snapshot(EXPORT))
        self.assertEqual(tree.maintenance_entry(EXPORT), pin)
        self.assertEqual(len(tree.recent_events()), written)
        # the node's first reading finds it pinned, as it was
        tree.upsert(EXPORT, ERROR, {"newest": "run 3 failed", "queued": "run 4 waits"})
        node = tree.snapshot(EXPORT)
        assert node is not None
        self.assertIs(node.own_code, MAINTENANCE)
        self.assertEqual(len(tree.recent_events()), written)

    def test_a_suspended_pin_is_suspended_after_a_restart_too(self) -> None:
        old = _grown()
        pin = _pin(old, EXPORT)
        old.prune(JOBS, {"import"})
        tree = _restarted(old)
        written = len(tree.recent_events())
        tree.restore_maintenance({EXPORT: pin})
        self.assertEqual(len(tree.recent_events()), written)
        self.assertEqual(_suspended(tree)[0], {EXPORT: pin})
        self.assertEqual(self._first_run(tree), [])
        self.assertEqual(len(tree.recent_events()), written)

    def test_a_pin_on_a_node_that_went_while_down_is_suspended_by_the_first_run(
            self) -> None:
        old = _grown()
        pin = _pin(old, EXPORT)
        tree = _restarted(old)
        tree.restore_maintenance({EXPORT: pin})
        self._first_run(tree)
        row = _rows(tree, EXPORT)[-1]
        self.assertEqual((row.old, row.new, row.cause),
                         (MAINTENANCE, UNDEFINED, CAUSE_REMOVED))
        self.assertEqual(_suspended(tree)[0], {EXPORT: pin})


CODES = {"succeeded": OK, "slow": WARN, "failed": ERROR}


class _Queue(Check):
    """Reads the job names of one queue and hands back a node for each."""

    type_name = "queue"

    def __init__(self, *, complete: bool = True, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.complete = complete
        self.jobs: dict[str, str] = {}
        self.answers = True

    def measure(self) -> Sequence[Measurement]:
        if not self.answers:
            raise RuntimeError("the queue did not answer")
        return [Measurement(record={"job": name, "outcome": outcome},
                            subject=f"job/{name}")
                for name, outcome in self.jobs.items()]

    def grade(self, measurements: Sequence[Measurement],
              now: datetime) -> CheckResult:
        return CheckResult(StatusCode.UNDEFINED, children=tuple(
            CheckResult(name=str(reading.record["job"]), reason=[Entry(
                "newest", f"{reading.record['job']} {reading.record['outcome']}",
                CODES[str(reading.record["outcome"])], subject=reading.subject,
                data=dict(reading.record))])
            for reading in measurements), children_complete=self.complete)


class _Estate(Check):
    """Reads two queues, each a container above its job names; only a queue that
    answered says that its children are complete."""

    type_name = "estate"

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.queues: dict[str, list[str] | None] = {}

    def measure(self) -> Sequence[Measurement]:
        return [Measurement(record={"queue": name, "jobs": jobs},
                            subject=f"queue/{name}")
                for name, jobs in self.queues.items()]

    def grade(self, measurements: Sequence[Measurement],
              now: datetime) -> CheckResult:
        queues = []
        for reading in measurements:
            jobs = reading.record["jobs"]
            queues.append(CheckResult(
                StatusCode.UNDEFINED, name=str(reading.record["queue"]),
                children=tuple(CheckResult(OK, "fine", name=job)
                               for job in (jobs or ())),
                children_complete=jobs is not None))
        return CheckResult(StatusCode.UNDEFINED, children=tuple(queues),
                           children_complete=True)


class _Aspects(Check):
    """One of two checks on a host's node: it owns the aspects it names and says
    that the host's children are complete, which it can say only of its own."""

    type_name = "aspects"

    def __init__(self, *, names: Sequence[str], kind: str, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.names = list(names)
        self.every = tuple(names)
        self.type_name = kind

    def owned_nodes(self) -> set[str]:
        return {f"{self.path}/{name}" for name in self.every}

    def measure(self) -> Sequence[Measurement]:
        return [Measurement(record={"aspects": list(self.names)})]

    def grade(self, measurements: Sequence[Measurement],
              now: datetime) -> CheckResult:
        return CheckResult(StatusCode.UNDEFINED, children=tuple(
            CheckResult(OK, "fine", name=name) for name in self.names),
            children_complete=True)


class EngineTests(TestCase):
    """What a run that says so removes, and what it leaves (decisions 1 to 3)."""

    def _run(self, *checks: Check) -> tuple[Engine, StatusTree]:
        tree = StatusTree()
        engine = Engine(list(checks), tree)
        engine.run_once()
        return engine, tree

    @staticmethod
    def _names(tree: StatusTree, path: str) -> list[str]:
        node = tree.snapshot(path)
        assert node is not None
        return [child.name for child in node.children]

    def test_a_node_that_says_so_loses_a_child_it_no_longer_returns(self) -> None:
        check = _Queue(path="/batch", subject="queue/live")
        check.jobs = {"import": "succeeded", "export": "failed"}
        engine, tree = self._run(check)
        self.assertIs(tree.effective("/batch"), ERROR)
        del check.jobs["export"]
        engine.run_once()
        self.assertEqual(self._names(tree, "/batch"), ["import"])
        self.assertIs(tree.effective("/batch"), OK)
        row = _rows(tree, "/batch/export")[-1]
        self.assertEqual((row.old, row.new, row.cause, row.reason),
                         (ERROR, UNDEFINED, CAUSE_REMOVED, GONE))

    def test_the_log_names_each_child_that_went_once(self) -> None:
        check = _Estate(path="/aws", subject="estate")
        check.queues = {"live": ["import", "export"], "test": ["import", "export"]}
        engine, _tree = self._run(check)
        check.queues = {"live": ["import"]}
        with self.assertLogs("little_sister", level="INFO") as logged:
            engine.run_once()
        said = [line.split(": ", 2)[-1] for line in logged.output
                if "no longer reported" in line]
        self.assertEqual(said, [
            "/aws/live/export is no longer reported, and was removed",
            "/aws/test is no longer reported, and was removed with 2 node(s) "
            "beneath it"])

    def test_a_result_that_says_nothing_removes_nothing(self) -> None:
        check = _Queue(path="/batch", subject="queue/live", complete=False)
        check.jobs = {"import": "succeeded", "export": "failed"}
        engine, tree = self._run(check)
        del check.jobs["export"]
        engine.run_once()
        self.assertEqual(self._names(tree, "/batch"), ["export", "import"])
        self.assertEqual(_removals(tree), [])

    def test_a_run_that_could_not_read_removes_nothing(self) -> None:
        check = _Queue(path="/batch", subject="queue/live")
        check.jobs = {"import": "succeeded", "export": "failed"}
        engine, tree = self._run(check)
        check.answers = False
        engine.run_once()
        self.assertEqual(self._names(tree, "/batch"), ["export", "import"])
        self.assertEqual(_removals(tree), [])

    def test_a_node_that_returns_is_a_node_again(self) -> None:
        check = _Queue(path="/batch", subject="queue/live")
        check.jobs = {"import": "succeeded", "export": "failed"}
        engine, tree = self._run(check)
        del check.jobs["export"]
        engine.run_once()
        check.jobs["export"] = "succeeded"
        engine.run_once()
        self.assertEqual(self._names(tree, "/batch"), ["export", "import"])
        self.assertEqual([period.code for period in tree.history("/batch/export")],
                         [ERROR, UNDEFINED, OK])

    def test_the_statement_stands_on_the_node_that_makes_it(self) -> None:
        check = _Estate(path="/aws", subject="estate")
        check.queues = {"live": ["import", "export"], "test": ["import", "export"]}
        engine, tree = self._run(check)
        # `live` answers with one job fewer; `test` did not answer, and is handed
        # back without the statement, so its jobs stay as they were
        check.queues = {"live": ["import"], "test": None}
        engine.run_once()
        self.assertEqual(self._names(tree, "/aws/live"), ["import"])
        self.assertEqual(self._names(tree, "/aws/test"), ["export", "import"])
        self.assertEqual([row.path for row in _removals(tree)], ["/aws/live/export"])
        # a queue that is gone leaves with everything beneath it, a row for each
        check.queues = {"live": ["import"]}
        engine.run_once()
        self.assertEqual(self._names(tree, "/aws"), ["live"])
        self.assertEqual([row.path for row in _removals(tree)][1:],
                         ["/aws/test/export", "/aws/test/import", "/aws/test"])

    def test_a_child_named_by_several_segments_is_returned_by_its_first(
            self) -> None:
        # the tree makes a node for `eu` on the way to `eu/import`, and that node
        # is a child the run returned: it must not go with the run that wrote it
        check = _Queue(path="/batch", subject="queue/live")
        check.jobs = {"eu/import": "succeeded", "eu/export": "failed",
                      "us/import": "succeeded"}
        engine, tree = self._run(check)
        self.assertEqual(self._names(tree, "/batch"), ["eu", "us"])
        self.assertEqual(self._names(tree, "/batch/eu"), ["export", "import"])
        self.assertEqual(_removals(tree), [])
        # and a first segment no child names any more is what went
        check.jobs = {"eu/import": "succeeded"}
        engine.run_once()
        self.assertEqual(self._names(tree, "/batch"), ["eu"])
        # nothing beneath a child that is kept is looked at
        self.assertEqual(self._names(tree, "/batch/eu"), ["export", "import"])
        # `us` itself was never written, so it leaves without a row
        self.assertEqual([row.path for row in _removals(tree)],
                         ["/batch/us/import"])

    def test_a_run_removes_nothing_another_check_wrote(self) -> None:
        metrics = _Aspects(path="/host", names=("disk", "memory"), kind="metrics")
        vendor = _Aspects(path="/host", names=("temperature",), kind="vendor")
        engine, tree = self._run(metrics, vendor)
        self.assertEqual(self._names(tree, "/host"), ["disk", "memory", "temperature"])
        metrics.names = ["disk"]
        engine.run_once()
        self.assertEqual(self._names(tree, "/host"), ["disk", "temperature"])
        self.assertEqual([row.path for row in _removals(tree)], ["/host/memory"])

    def test_the_instances_own_branch_is_no_checks_to_remove(self) -> None:
        # the loader keeps every check off that line (ADR-0005); an engine built
        # by hand may hold one above it, and its statement does not reach there
        check = _Queue(path="/", subject="queue/live")
        check.jobs = {"import": "succeeded"}
        tree = StatusTree()
        engine = Engine([check], tree)
        tree.upsert(HEARTBEAT_PATH, OK, "beating")
        tree.upsert("/leftover", OK, "from another time")
        engine.run_once()
        self.assertEqual(self._names(tree, "/"), ["import", "little-sister"])
        self.assertEqual([row.path for row in _removals(tree)], ["/leftover"])

    def test_the_removed_subjects_readings_stay(self) -> None:
        check = _Queue(path="/batch", subject="queue/live", series_keep=5)
        check.jobs = {"import": "succeeded", "export": "failed"}
        engine, _tree = self._run(check)
        del check.jobs["export"]
        engine.run_once()
        kept = engine.series.window(SeriesKey("queue", "/batch", "job/export"))
        self.assertEqual([record.data["outcome"] for record in kept], ["failed"])
        self.assertIs(kept[0].code, ERROR)
