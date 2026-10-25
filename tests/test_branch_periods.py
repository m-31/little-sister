"""A branch keeps the period of what it shows beside the log (ADR-0132): the tree's
bookkeeping.

* Every node above others — the root included, and a node that declares nothing of
  its own — keeps the period of what it rolls up to: since when, what it showed
  before, what moved it and the node whose change it was (decisions 1 and 4). No row
  is written for it.
* A write is a stored run, seen whole: the store holds the tree's lock from its first
  write to its last, every node and row it writes takes the run's one instant, and
  every branch above what it moved is compared once, when it ends (decision 2). A
  change outside a run — a pin set or edited, a node the configuration no longer
  has — is one write, and the pins a sweep finds run out are one write together.
* Staleness moves a branch too, dated when the reading went stale — its last
  observation and its tolerance after it — and not when a tick saw it; so does a
  shield that ends with its dependency's silence (decision 2).
* A restart counts every node at its kept entry until its unit has run, and does not
  weigh it stale; the first start seeds each branch's period from the log (decision
  3). A difference a tick finds that no change explains begins a period at the tick,
  with no cause and no ``by``; outside a takeover the log says a change was missed.
* Where one change moves several nodes, ``by`` is the first in the tree's order that
  answers for the new period: where the branch shows a worse failure — maintenance
  and undefined counting as none — a node that now counts the new code for itself;
  where it shows less, one that counted the old code for itself; otherwise the first
  whose own part moved — and the dependency, where a shield moved it (decision 4).
"""
from __future__ import annotations

import gc
import json
import threading
import types
from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from unittest import TestCase, mock

from little_sister import instants
from little_sister import tree as tree_module
from little_sister.checks import Check, CheckResult, Measurement, Unit
from little_sister.engine import Engine
from little_sister.limits import Limits
from little_sister.reasons import Entry
from little_sister.status import HEARTBEAT_PATH, StatusCode
from little_sister.tree import (
    CAUSE_PIN_ENDED,
    CAUSE_PIN_SET,
    CAUSE_READING,
    CAUSE_REMOVED,
    CAUSE_STALE,
    Beginning,
    Period,
    StatusTree,
    events_from_payload,
    nodes_from_payload,
)

OK, WARN, ERROR = StatusCode.OK, StatusCode.WARN, StatusCode.ERROR
MAINTENANCE, UNDEFINED = StatusCode.MAINTENANCE, StatusCode.UNDEFINED

#: A Saturday morning, the clock every test starts on.
T0 = datetime(2026, 10, 17, 9, 0, tzinfo=UTC)
SOON = T0 + timedelta(days=30)


class _Clocked(TestCase):
    """A tree on a wall clock the test moves: every stamp the tree takes is read off
    it."""

    def setUp(self) -> None:
        self.wall = T0
        self.mono = 1000.0
        patched = mock.patch.object(instants, "now", lambda: self.wall)
        patched.start()
        self.addCleanup(patched.stop)
        self.tree = StatusTree()

    def advance(self, seconds: float) -> datetime:
        self.wall += timedelta(seconds=seconds)
        self.mono += seconds
        return self.wall

    def period(self, path: str, tree: StatusTree | None = None) -> Period:
        found = (tree or self.tree).period(path)
        assert found is not None, f"{path} keeps no period"
        return found

    def said(self, path: str, tree: StatusTree | None = None
             ) -> tuple[StatusCode, datetime, bool, StatusCode | None, str, str]:
        """What a branch's period says: its code, since when, whether that is a
        bound, what came before, what moved it and the node whose change it was."""
        found = self.period(path, tree)
        began = found.began
        return (found.code, began.at, began.before, began.was, began.cause,
                found.by)

    def engine(self, *checks: Check, tree: StatusTree | None = None) -> Engine:
        engine = Engine(list(checks), tree or self.tree, clock=lambda: self.mono,
                        wall=lambda: self.wall, poll_interval=0.02,
                        limits=Limits(memory_limit=None))
        for item in engine._scheduled:
            item.stagger = 0.0
        return engine

    def restarted(self, *, tree: StatusTree | None = None,
                  before_the_key: bool = False) -> StatusTree:
        """A new process on what this one kept — or, ``before_the_key``, on that file
        as a release before ADR-0132 holds it (:func:`as_before_the_key`)."""
        payload = json.loads(json.dumps((tree or self.tree).events_payload()))
        if before_the_key:
            payload["nodes"] = as_before_the_key(payload["nodes"])
        new = StatusTree()
        new.restore_events(events_from_payload(payload),
                           nodes_from_payload(payload))
        return new


def as_before_the_key(nodes: dict[str, dict[str, object]]
                      ) -> dict[str, dict[str, object]]:
    """A kept file's table of nodes as a release before ADR-0132 writes it: no
    ``period`` in any entry, and no entry of the two ``UNDEFINED`` codes alone — the
    root's and a container's, which it writes none of."""
    held: dict[str, dict[str, object]] = {}
    for path, entry in nodes.items():
        kept = {key: value for key, value in entry.items() if key != "period"}
        if kept != {"shows": "UNDEFINED", "reported": "UNDEFINED"}:
            held[path] = kept
    return held


class _Units(Check):
    """Two units, ``fast`` and ``slow``, each answering for the node of its name
    beneath the mount. A unit whose measurement raises is an ERROR on its own node,
    written over what the grading says of it, which grades its last good reading
    (ADR-0078 decision 4)."""

    type_name = "two-units"

    def __init__(self, **kwargs: object) -> None:
        super().__init__(**kwargs)   # type: ignore[arg-type]
        self.raises: dict[str, Exception | None] = {"fast": None, "slow": None}

    def units(self) -> tuple[Unit, ...]:
        return (Unit("fast", 3600, "fast"), Unit("slow", 7200, "slow"))

    def measure(self) -> Sequence[Measurement]:
        return [*self.measure_unit("fast"), *self.measure_unit("slow")]

    def measure_unit(self, key: str) -> Sequence[Measurement]:
        error = self.raises[key]
        if error is not None:
            raise error
        return [Measurement(record={"unit": key}, subject=key)]

    def grade(self, measurements: Sequence[Measurement],
              now: datetime) -> CheckResult:
        return CheckResult(UNDEFINED, ["two units"], children=tuple(
            CheckResult(OK, [f"{reading.record['unit']} read"],
                        name=str(reading.record["unit"]))
            for reading in measurements), children_complete=True)


class _Three(Check):
    """One unit, three nodes beneath it that turn together."""

    type_name = "three"

    def __init__(self, **kwargs: object) -> None:
        super().__init__(**kwargs)   # type: ignore[arg-type]
        self.code = OK

    def measure(self) -> Sequence[Measurement]:
        return [Measurement(record={"n": 1})]

    def grade(self, measurements: Sequence[Measurement],
              now: datetime) -> CheckResult:
        return CheckResult(UNDEFINED, ["three"], children=tuple(
            CheckResult(self.code, [f"{name}: {self.code.name}"], name=name)
            for name in ("a", "b", "c")), children_complete=True)


class AWriteIsAStoredRunTests(_Clocked):
    """Decision 2: the stored run, seen whole."""

    def test_a_runs_nodes_and_rows_take_its_one_instant_and_date_its_change(self):
        self.tree.upsert("/b/x", OK)
        self.tree.upsert("/b/y", OK)
        start = self.advance(300)
        clock = iter(range(1, 100))
        # A clock that moves at every reading of it: the run is stamped once.
        with mock.patch.object(instants, "now",
                               lambda: start + timedelta(seconds=next(clock))):
            with self.tree.storing("/b"):
                self.tree.upsert("/b/x", ERROR, "down")
                self.tree.upsert("/b/y", WARN, "slow")
        run = start + timedelta(seconds=1)
        self.assertEqual([self.tree.snapshot(path).timestamp
                          for path in ("/b/x", "/b/y")], [run, run])
        self.assertEqual({row.timestamp for row in self.tree.recent_events()
                          if row.timestamp > T0}, {run})
        self.assertEqual(self.said("/b"),
                         (ERROR, run, False, OK, CAUSE_READING, "/b/x"))

    def test_a_branch_red_throughout_above_a_failing_unit_keeps_its_period(self):
        check = _Units(path="/x")
        engine = self.engine(check)
        engine.run_once()
        check.raises["slow"] = RuntimeError("no route to the bucket")
        slow = next(item for item in engine._scheduled if item.unit.key == "slow")
        began = self.advance(600)
        engine._execute(slow)
        self.assertEqual(self.said("/x"),
                         (ERROR, began, False, OK, CAUSE_READING, "/x/slow"))
        # Its grading is written first, from the last good reading, and its
        # failure over its node second: the branch is red before and after.
        self.advance(600)
        engine._execute(slow)
        self.assertIs(self.tree.snapshot("/x/slow").own_code, ERROR)
        self.assertEqual(self.said("/x"),
                         (ERROR, began, False, OK, CAUSE_READING, "/x/slow"))
        self.assertEqual(self.period("/").began.at, began)

    def test_a_reader_sees_a_run_whole_or_not_at_all(self):
        check = _Three(path="/m")
        engine = self.engine(check)
        engine.run_once()
        check.code = ERROR
        first_written, read = threading.Event(), threading.Event()
        seen: list[tuple[StatusCode, ...]] = []
        upsert = self.tree.upsert

        def slowed(path: str, code: StatusCode, *args: object,
                   **kwargs: object) -> bool:
            wrote = upsert(path, code, *args, **kwargs)  # type: ignore[arg-type]
            if path == "/m/a":
                first_written.set()
                # a reader that nothing held off would read now
                read.wait(timeout=0.3)
            return wrote

        def reader() -> None:
            first_written.wait(timeout=5)
            node = self.tree.snapshot("/m")
            assert node is not None
            seen.append(tuple(child.code for child in node.children))
            read.set()

        thread = threading.Thread(target=reader)
        thread.start()
        with mock.patch.object(self.tree, "upsert", slowed):
            engine.run_once()
        thread.join(timeout=5)
        self.assertTrue(first_written.is_set(), "the reader read during the store")
        self.assertIn(seen, [[(OK, OK, OK)], [(ERROR, ERROR, ERROR)]])

    def test_a_branch_red_from_one_node_then_another_keeps_the_first_since(self):
        # the plan's own case: the failure handed from one node to another in one
        # run, the one that recovers written first
        with self.tree.storing("/p"):
            self.tree.upsert("/p/a", OK)
            self.tree.upsert("/p/b", OK)
        first = self.advance(600)
        with self.tree.storing("/p"):
            self.tree.upsert("/p/a", ERROR, "a broke")
            self.tree.upsert("/p/b", OK)
        self.advance(600)
        with self.tree.storing("/p"):
            self.tree.upsert("/p/a", OK)
            self.tree.upsert("/p/b", ERROR, "b broke")
        self.assertEqual(self.said("/p"),
                         (ERROR, first, False, OK, CAUSE_READING, "/p/a"))
        ended = self.advance(600)
        with self.tree.storing("/p"):
            self.tree.upsert("/p/a", OK)
            self.tree.upsert("/p/b", OK)
        self.assertEqual(self.said("/p"),
                         (OK, ended, False, ERROR, CAUSE_READING, "/p/b"))

    def test_a_pin_set_is_one_write_at_its_instant(self):
        self.tree.upsert("/b/a", ERROR, "down")
        pinned = self.advance(60)
        self.tree.set_maintenance("/b/a", "on it", expires_at=SOON, set_by="lex")
        self.assertEqual(self.said("/b"),
                         (MAINTENANCE, pinned, False, ERROR, CAUSE_PIN_SET, "/b/a"))

    def test_the_pins_a_sweep_finds_run_out_are_one_write_together(self):
        # both children pinned until 18:00, the branch in maintenance: it goes to
        # what they show, and never through what one of them shows alone — "error
        # since 18:00, was ok", an ok period of no length
        evening = T0.replace(hour=18)
        with self.tree.storing("/b"):
            self.tree.upsert("/b/fine", OK)
            self.tree.upsert("/b/down", ERROR, "down")
        for path in ("/b/fine", "/b/down"):
            self.tree.set_maintenance(path, "planned", expires_at=evening,
                                      set_by="lex")
        self.assertIs(self.period("/b").code, MAINTENANCE)
        self.advance((evening - self.wall).total_seconds())
        self.assertEqual(self.tree.sweep_expired(), ["/b/fine", "/b/down"])
        self.assertEqual(self.said("/b"), (ERROR, evening, False, MAINTENANCE,
                                           CAUSE_PIN_ENDED, "/b/down"))
        # and the rows it wrote carry its one instant, as History will read them
        self.assertEqual([event.timestamp for event in self.tree.recent_events()
                          if event.cause == CAUSE_PIN_ENDED], [evening, evening])

    def test_a_nodes_pin_and_a_lines_that_run_out_together_are_one_write(self):
        evening = T0.replace(hour=18)
        with self.tree.storing("/b"):
            self.tree.upsert("/b/x", ERROR, "down")
            self.tree.upsert("/b/y", WARN, [Entry("disk", "disk 91 %", code=WARN)],
                             members=True)
        self.tree.set_maintenance("/b/x", "planned", expires_at=evening,
                                  set_by="lex")
        self.tree.set_entry_maintenance("/b/y", "disk", "cleaning up",
                                        expires_at=evening, set_by="lex")
        self.assertIs(self.period("/b").code, MAINTENANCE)
        self.advance((evening - self.wall).total_seconds())
        self.tree.sweep_expired()
        # the line's pin ends first, and still the branch never reads warn
        self.assertEqual(self.said("/b"), (ERROR, evening, False, MAINTENANCE,
                                           CAUSE_PIN_ENDED, "/b/x"))

    def test_a_node_a_run_no_longer_returns_moves_its_branch_as_a_removal(self):
        with self.tree.storing("/r"):
            self.tree.upsert("/r/a", ERROR, "down")
            self.tree.upsert("/r/b", OK)
        run = self.advance(60)
        with self.tree.storing("/r"):
            self.tree.upsert("/r/b", OK)
            self.tree.prune("/r", {"b"})
        self.assertEqual(self.said("/r"),
                         (OK, run, False, ERROR, CAUSE_REMOVED, "/r/a"))

    def test_a_branch_its_check_removed_returns_as_a_change_the_tree_saw(self):
        # it shows nothing since its removal, as its own entry says (ADR-0110
        # decision 4), so its return is no first sight
        with self.tree.storing("/m"):
            self.tree.upsert("/m/g", OK, "a group")
            self.tree.upsert("/m/g/x", ERROR, "down")
        removed = self.advance(60)
        with self.tree.storing("/m"):
            self.tree.upsert("/m/k", OK)
            self.tree.prune("/m", {"k"})
        self.assertEqual(self.said("/m/g"),
                         (UNDEFINED, removed, False, ERROR, CAUSE_REMOVED, "/m/g"))
        back = self.advance(60)
        with self.tree.storing("/m"):
            self.tree.upsert("/m/g", OK, "a group")
            self.tree.upsert("/m/g/x", OK)
            self.tree.upsert("/m/k", OK)
        self.assertEqual(self.said("/m/g"),
                         (OK, back, False, UNDEFINED, CAUSE_READING, "/m/g"))


class WhatABranchFirstShowsTests(_Clocked):
    """A branch first seen showing a status is a bound, as a node's first reading
    is (ADR-0099 decision 9); the instance's own branch begins with its process."""

    def test_a_branch_first_seen_is_a_bound(self):
        with self.tree.storing("/new"):
            self.tree.upsert("/new/x", ERROR, "down")
            self.tree.upsert("/new/y", OK)
        self.assertEqual(self.said("/new"), (ERROR, T0, True, None, "", ""))
        self.assertIsNone(self.tree.period("/new/x"), "a leaf's period is its own")

    def test_on_the_instances_own_branch_the_first_beat_is_a_beginning(self):
        self.tree.set_process_branch(HEARTBEAT_PATH)
        with self.tree.storing(HEARTBEAT_PATH):
            self.tree.upsert(HEARTBEAT_PATH, OK)
            self.tree.upsert(f"{HEARTBEAT_PATH}/engine", WARN, "late")
        # warn after undefined is a worse failure: the node that now warns
        self.assertEqual(self.said(HEARTBEAT_PATH),
                         (WARN, T0, False, UNDEFINED, CAUSE_READING,
                          f"{HEARTBEAT_PATH}/engine"))

    def test_a_node_that_comes_to_stand_above_others_keeps_its_own_period(self):
        self.tree.upsert("/a", OK)
        self.tree.upsert("/c", OK)
        changed = self.advance(60)
        self.tree.upsert("/a/b", ERROR, "down")
        self.tree.upsert("/c/d", OK)
        self.assertEqual(self.said("/a"),
                         (ERROR, changed, False, OK, CAUSE_READING, "/a/b"))
        # where it shows what it showed, the period it had goes on: its own, a
        # bound at its first reading
        self.assertEqual(self.said("/c"), (OK, T0, True, None, "", ""))

    def test_a_container_that_declares_nothing_keeps_one_too(self):
        self.tree.upsert("/host", UNDEFINED)
        self.tree.upsert("/host/disk", OK)
        broke = self.advance(60)
        self.tree.upsert("/host/disk", ERROR, "full")
        self.assertEqual(self.said("/host"),
                         (ERROR, broke, False, OK, CAUSE_READING, "/host/disk"))


class ByTests(_Clocked):
    """Decision 4: the node whose change began the period, where one change moved
    several."""

    def test_two_pipelines_failing_in_one_run_name_the_first_in_the_trees_order(self):
        self.tree.upsert("/ci/alpha", OK)
        self.tree.upsert("/ci/beta", OK)
        self.advance(60)
        with self.tree.storing("/ci"):
            # written in the other order: the tree's order decides, not the write's
            self.tree.upsert("/ci/beta", ERROR, "failed")
            self.tree.upsert("/ci/alpha", ERROR, "failed")
        self.assertEqual(self.period("/ci").by, "/ci/alpha")

    def test_a_branch_that_got_worse_names_a_node_that_now_counts_its_code(self):
        # alpha turns warn and beta error in one run: the branch is red because of
        # beta, though alpha comes first in the tree's order
        self.tree.upsert("/ci/alpha", OK)
        self.tree.upsert("/ci/beta", OK)
        run = self.advance(60)
        with self.tree.storing("/ci"):
            self.tree.upsert("/ci/alpha", WARN, "slow")
            self.tree.upsert("/ci/beta", ERROR, "failed")
        self.assertEqual(self.said("/ci"),
                         (ERROR, run, False, OK, CAUSE_READING, "/ci/beta"))

    def test_a_branch_that_got_better_names_the_node_whose_recovery_ended_it(self):
        # red from z, orange from x, which nothing touches; one run turns z ok and
        # y warn — the branch goes orange because z recovered, y made no difference
        self.tree.upsert("/b/x", WARN, "slow")
        self.tree.upsert("/b/y", OK)
        self.tree.upsert("/b/z", ERROR, "down")
        run = self.advance(60)
        with self.tree.storing("/b"):
            self.tree.upsert("/b/z", OK)
            self.tree.upsert("/b/y", WARN, "slow too")
        self.assertEqual(self.said("/b"),
                         (WARN, run, False, ERROR, CAUSE_READING, "/b/z"))

    def test_an_improvement_to_ok_names_the_node_that_recovered(self):
        self.tree.upsert("/b/a", ERROR, "down")
        self.tree.upsert("/b/c", OK)
        run = self.advance(60)
        with self.tree.storing("/b"):
            self.tree.upsert("/b/a", OK)
            self.tree.upsert("/b/c", OK)
        self.assertEqual(self.said("/b"),
                         (OK, run, False, ERROR, CAUSE_READING, "/b/a"))

    def test_a_pin_on_a_branch_names_the_branch(self):
        self.tree.upsert("/b", OK)
        self.tree.upsert("/b/a", ERROR, "down")
        pinned = self.advance(60)
        self.tree.set_maintenance("/b", "planned", expires_at=SOON, set_by="lex")
        self.assertEqual(self.said("/b"),
                         (MAINTENANCE, pinned, False, ERROR, CAUSE_PIN_SET, "/b"))

    def test_a_pin_on_the_last_node_beneath_it_names_that_node(self):
        # its children all silenced, a branch reads maintenance (ADR-0039 rule 5):
        # the move to maintenance names the first node whose own part moved
        self.tree.upsert("/b/a", OK)
        self.tree.set_maintenance("/b/a", "planned", expires_at=SOON, set_by="lex")
        self.tree.upsert("/b/c", WARN, "slow")
        pinned = self.advance(60)
        self.tree.set_maintenance("/b/c", "planned", expires_at=SOON, set_by="lex")
        self.assertEqual(self.said("/b"),
                         (MAINTENANCE, pinned, False, WARN, CAUSE_PIN_SET, "/b/c"))

    def test_from_maintenance_to_error_names_the_node_that_now_fails(self):
        # maintenance says no failure, so error after it is worse: the node that now
        # counts error for itself, and not the first the run moved
        self.tree.upsert("/b/k", OK)
        self.tree.set_maintenance("/b/k", "planned", expires_at=SOON, set_by="lex")
        self.assertIs(self.period("/b").code, MAINTENANCE)
        run = self.advance(60)
        with self.tree.storing("/b"):
            self.tree.upsert("/b/a", OK)
            self.tree.upsert("/b/m", ERROR, "down")
        self.assertEqual(self.said("/b"),
                         (ERROR, run, False, MAINTENANCE, CAUSE_READING, "/b/m"))

    def test_a_shield_names_its_dependency_which_need_not_stand_beneath_it(self):
        self.tree.set_dependency("/services/cache", "/net/vpn")
        self.tree.upsert("/services/web", OK)
        self.tree.upsert("/services/cache", ERROR, "no route to host")
        self.tree.upsert("/net/vpn", OK)
        failed = self.advance(60)
        with self.tree.storing("/net/vpn"):
            self.tree.upsert("/net/vpn", ERROR, "the tunnel is down")
        self.assertEqual(self.tree.snapshot("/services/cache").shielded_by,
                         "/net/vpn")
        self.assertEqual(self.said("/services"),
                         (OK, failed, False, ERROR, CAUSE_READING, "/net/vpn"))
        answered = self.advance(60)
        with self.tree.storing("/net/vpn"):
            self.tree.upsert("/net/vpn", OK)
        self.assertEqual(self.said("/services"),
                         (ERROR, answered, False, OK, CAUSE_READING, "/net/vpn"))

    def test_two_nodes_gone_stale_at_one_instant_are_one_change(self):
        with self.tree.storing("/s"):
            self.tree.upsert("/s/b", OK, stale_after=300.0)
            self.tree.upsert("/s/a", OK, stale_after=300.0)
        self.tree.compare_periods(T0 + timedelta(minutes=10))
        self.assertEqual(self.said("/s"),
                         (WARN, T0 + timedelta(minutes=5), False, OK, CAUSE_STALE,
                          "/s/a"))


class StalenessTests(_Clocked):
    """Decision 2: a branch moves where a node beneath goes stale, and where a
    shield ends with its dependency's silence — dated when the reading went stale."""

    def test_a_branch_orange_from_a_silent_leaf_is_dated_when_it_went_stale(self):
        # *warn since 10:45*, the leaf *stale, last observed 10:40*
        self.wall = datetime(2026, 10, 17, 10, 40, tzinfo=UTC)
        self.tree.upsert("/b/leaf", OK, stale_after=300.0)
        self.tree.upsert("/b/other", OK)
        self.tree.compare_periods(datetime(2026, 10, 17, 10, 50, tzinfo=UTC))
        self.assertEqual(self.said("/b"),
                         (WARN, datetime(2026, 10, 17, 10, 45, tzinfo=UTC), False,
                          OK, CAUSE_STALE, "/b/leaf"))

    def test_a_shield_that_ends_with_its_dependencys_silence(self):
        self.tree.set_dependency("/svc/cache", "/net/vpn")
        self.tree.upsert("/svc/web", OK)
        self.tree.upsert("/svc/cache", ERROR, "no route to host")
        self.tree.upsert("/net/vpn", ERROR, "the tunnel is down", stale_after=300.0)
        self.assertIs(self.period("/svc").code, OK)
        self.tree.compare_periods(T0 + timedelta(minutes=10))
        self.assertEqual(self.said("/svc"),
                         (ERROR, T0 + timedelta(minutes=5), False, OK, CAUSE_STALE,
                          "/net/vpn"))

    def test_staleness_that_came_due_before_a_write_is_not_the_writes(self):
        self.tree.upsert("/b/leaf", OK, stale_after=300.0)
        self.tree.upsert("/b/other", OK)
        # no tick since the leaf went stale: the next write finds it
        self.advance(480)
        with self.tree.storing("/b/other"):
            self.tree.upsert("/b/other", OK)
        self.assertEqual(self.said("/b"),
                         (WARN, T0 + timedelta(minutes=5), False, OK, CAUSE_STALE,
                          "/b/leaf"))

    def test_a_reading_that_goes_stale_at_a_writes_instant_is_dated_then(self):
        # at that instant its age is its tolerance, not past it: the write saw it
        # fresh, and the next comparison dates the change there
        with self.tree.storing("/s"):
            self.tree.upsert("/s/a", OK, stale_after=300.0)
            self.tree.upsert("/s/b", OK)
        due = self.advance(300)
        self.tree.set_maintenance("/elsewhere", "planned", expires_at=SOON,
                                  set_by="lex")
        self.assertIs(self.period("/s").code, OK)
        with self.assertNoLogs("little_sister.logger", level="WARNING"):
            self.tree.compare_periods(T0 + timedelta(minutes=10))
        self.assertEqual(self.said("/s"),
                         (WARN, due, False, OK, CAUSE_STALE, "/s/a"))

    def test_a_reading_after_the_silence_ends_it_by_that_reading(self):
        self.tree.upsert("/b/leaf", OK, stale_after=300.0)
        self.tree.upsert("/b/other", OK)
        self.tree.compare_periods(T0 + timedelta(minutes=10))
        read = self.advance(660)
        with self.tree.storing("/b/leaf"):
            self.tree.upsert("/b/leaf", OK, stale_after=300.0)
        self.assertEqual(self.said("/b"),
                         (OK, read, False, WARN, CAUSE_READING, "/b/leaf"))

    def test_a_tick_with_nothing_gone_stale_moves_nothing(self):
        self.tree.upsert("/b/leaf", OK, stale_after=300.0)
        self.tree.upsert("/b/other", OK)
        kept = self.period("/b")
        self.tree.compare_periods(T0 + timedelta(minutes=4))
        self.assertEqual(self.period("/b"), kept)


class WhatNoChangeExplainsTests(_Clocked):
    """Decision 3: a difference a tick finds that no change explains begins a period
    at the tick, with no cause and no ``by`` — after a takeover, what the adopted
    entries said and this tree does not; anywhere else a change the bookkeeping
    missed, which the log says."""

    def test_a_difference_no_change_explains_is_logged(self):
        with self.tree.storing("/b"):
            self.tree.upsert("/b/a", OK)
        # what a missed change leaves behind: a period that is not what the tree
        # rolls up to
        self.tree._periods["/b"] = Period(
            WARN, Beginning(T0, was=OK, cause=CAUSE_READING), by="/b/a")
        tick = self.advance(5)
        with self.assertLogs("little_sister.logger", level="WARNING") as logged:
            self.tree.compare_periods()
        self.assertEqual(self.said("/b"), (OK, tick, False, WARN, "", ""))
        self.assertIn("/b rolls up to ok", logged.output[0])

    def test_after_a_takeover_the_tick_says_what_the_adopted_entries_moved(self):
        # the holder saw /b/a fail; this process, standing by, read it ok itself
        holder = StatusTree()
        with holder.storing("/b"):
            holder.upsert("/b/a", OK)
        tree = self.restarted(tree=holder)
        self.advance(60)
        with tree.storing("/b"):
            tree.upsert("/b/a", OK)
        failed = self.advance(60)
        with holder.storing("/b"):
            holder.upsert("/b/a", ERROR, "down")
        tree.adopt_events(json.loads(json.dumps(holder.events_payload())))
        # the holder's period comes with its entry (ADR-0077) ...
        self.assertEqual(self.said("/b", tree),
                         (ERROR, failed, False, OK, CAUSE_READING, "/b/a"))
        tick = self.advance(1)
        with self.assertNoLogs("little_sister.logger", level="WARNING"):
            tree.compare_periods()
        # ... and the next tick says what this process's tree rolls up to
        self.assertEqual(self.said("/b", tree), (OK, tick, False, ERROR, "", ""))
        # the takeover's tick is the one that is not logged
        tree._periods["/b"] = Period(ERROR, Beginning(T0, before=True))
        with self.assertLogs("little_sister.logger", level="WARNING"):
            tree.compare_periods()


class ARestartCarriesTheEntriesTests(_Clocked):
    """Decision 3, and the seed of a first start."""

    def _broken(self) -> datetime:
        """A branch that turned red from one node an hour ago."""
        with self.tree.storing("/b"):
            self.tree.upsert("/b/ok", OK)
            self.tree.upsert("/b/bad", OK, stale_after=120.0)
        broke = self.advance(60)
        with self.tree.storing("/b"):
            self.tree.upsert("/b/ok", OK)
            self.tree.upsert("/b/bad", ERROR, "down", stale_after=120.0)
        self.advance(3600)
        return broke

    def test_the_first_start_seeds_the_period_from_the_rows(self):
        broke = self._broken()
        new = self.restarted(before_the_key=True)
        self.assertEqual(self.said("/b", new),
                         (ERROR, broke, False, OK, CAUSE_READING, "/b/bad"))
        self.assertEqual(self.said("/", new)[:2], (ERROR, broke))

    def test_a_restart_begins_no_period_where_the_first_readings_say_what_was_kept(
            self):
        broke = self._broken()
        new = self.restarted()
        self.advance(60)
        with new.storing("/b"):
            new.upsert("/b/ok", OK)
            new.upsert("/b/bad", ERROR, "down", stale_after=120.0)
        self.assertEqual(self.said("/b", new),
                         (ERROR, broke, False, OK, CAUSE_READING, "/b/bad"))

    def test_until_its_unit_has_run_a_node_counts_at_its_entry_and_is_not_stale(
            self):
        broke = self._broken()
        new = self.restarted()
        self.advance(60)
        with new.storing("/elsewhere"):
            new.upsert("/elsewhere/x", OK)
        new.compare_periods(self.advance(3600))
        self.assertIsNone(new.snapshot("/b"), "nothing has written it yet")
        self.assertEqual(self.said("/b", new)[:2], (ERROR, broke))
        self.assertEqual(self.said("/", new)[:2], (ERROR, broke))

    def test_once_its_unit_has_run_a_node_it_no_longer_writes_counts_no_more(self):
        self._broken()
        new = self.restarted()
        run = self.advance(60)
        with new.storing("/b"):
            new.upsert("/b/ok", OK)
        self.assertEqual(self.said("/b", new),
                         (OK, run, False, ERROR, CAUSE_READING, "/b/bad"))

    def test_a_store_inside_another_write_says_its_unit_has_run_too(self):
        # part of the write around it, at that write's instant — and its unit has run
        # all the same, so what it no longer writes counts no more
        self._broken()
        new = self.restarted()
        run = self.advance(60)
        with new.storing("/other"):
            new.upsert("/other/x", OK)
            with new.storing("/b"):
                new.upsert("/b/ok", OK)
        self.assertEqual(self.said("/b", new),
                         (OK, run, False, ERROR, CAUSE_READING, "/b/bad"))

    def test_the_seed_goes_back_past_a_node_that_recovered(self):
        self.tree.upsert("/b/a", OK)
        self.tree.upsert("/b/c", OK)
        broke = self.advance(60)
        self.tree.upsert("/b/a", ERROR, "a broke")
        self.advance(60)
        self.tree.upsert("/b/c", ERROR, "c broke")
        self.advance(60)
        self.tree.upsert("/b/a", OK)
        new = self.restarted(before_the_key=True)
        self.assertEqual(self.said("/b", new),
                         (ERROR, broke, False, OK, CAUSE_READING, "/b/a"))

    def test_the_seed_reads_one_instants_rows_as_one_change(self):
        self.tree.upsert("/h/a", OK)
        self.tree.upsert("/h/b", OK)
        broke = self.advance(60)
        self.tree.upsert("/h/a", ERROR, "a broke")
        self.advance(60)
        with self.tree.storing("/h"):
            self.tree.upsert("/h/a", OK)
            self.tree.upsert("/h/b", ERROR, "b broke")
        new = self.restarted(before_the_key=True)
        self.assertEqual(self.said("/h", new),
                         (ERROR, broke, False, OK, CAUSE_READING, "/h/a"))

    def test_where_the_rows_say_nothing_the_seed_is_a_bound_at_the_oldest_row(self):
        old = StatusTree(event_log_size=4)
        old.upsert("/q/x", OK)
        self.advance(60)
        for index in range(6):
            self.advance(60)
            old.upsert("/busy", ERROR if index % 2 else OK, f"reading {index}")
        oldest = old.recent_events()[0].timestamp
        new = self.restarted(tree=old, before_the_key=True)
        self.assertEqual(self.said("/q", new), (OK, oldest, True, None, "", ""))

    def test_the_beat_ends_the_carry_of_the_instances_own_nodes(self):
        old = StatusTree()
        old.set_process_branch(HEARTBEAT_PATH)
        old.upsert(HEARTBEAT_PATH, OK)
        old.upsert(f"{HEARTBEAT_PATH}/gone", ERROR, "a contributor this start lacks")
        new = StatusTree()
        engine = self.engine(tree=new)
        payload = json.loads(json.dumps(old.events_payload()))
        new.restore_events(events_from_payload(payload),
                           nodes_from_payload(payload))
        self.assertIs(self.period(HEARTBEAT_PATH, new).code, ERROR)
        beat = self.advance(60)
        engine._publish(self.mono)
        period = self.period(HEARTBEAT_PATH, new)
        self.assertNotEqual(period.code, ERROR)
        self.assertEqual((period.began.at, period.by),
                         (beat, f"{HEARTBEAT_PATH}/gone"))


def _of_the_tree(found: object) -> bool:
    """Whether an object the collector found is the bookkeeping's: a part or an input
    of a roll-up, or a function of the tree's module."""
    return isinstance(found, (tree_module._Part, tree_module._Inputs)) or (
        isinstance(found, types.FunctionType)
        and found.__module__ == tree_module.__name__)


class NothingWaitsForTheCycleCollectorTests(_Clocked):
    """ADR-0132's consequence on cost: a roll-up frees what it built as it returns. No
    closure of the tree calls itself — a closure that reaches itself is a
    reference cycle, which would hold every part it built until the collector ran,
    once a tick at the young generation's threshold — so a restore, a stored run, a
    tick and a page leave none of the tree's objects in a cycle. The collector's state
    is the process's, so the test puts it back as it found it."""

    def setUp(self) -> None:
        super().setUp()
        gc.collect()
        gc.disable()
        self.addCleanup(gc.enable)
        self.addCleanup(gc.garbage.clear)
        self.addCleanup(gc.set_debug, 0)

    def _left(self) -> list[object]:
        """What a collection finds of the tree's objects, kept to be looked at."""
        gc.set_debug(gc.DEBUG_SAVEALL)
        gc.collect()
        return [found for found in gc.garbage if _of_the_tree(found)]

    def test_a_restore_a_stored_run_a_tick_and_a_page_leave_nothing(self):
        old = StatusTree()
        old.set_dependency("/svc/cache", "/net/vpn")
        with old.storing("/svc"):
            old.upsert("/svc/web", OK)
            old.upsert("/svc/cache", ERROR, "no route to host")
        with old.storing("/net/vpn"):
            old.upsert("/net/vpn", OK)
        self.advance(60)
        with old.storing("/net/vpn"):
            old.upsert("/net/vpn", ERROR, "the tunnel is down")
        with old.storing("/s"):
            old.upsert("/s/a", OK, stale_after=300.0)
            old.upsert("/s/b", OK)
        self.assertEqual(self._left(), [], "the writes")
        # a start on a file written before the key, seeded from its log, and one
        # on a file that keeps the periods — its dependencies known first, as the
        # engine's construction gives them
        payload = json.loads(json.dumps(old.events_payload()))

        def started(nodes: dict[str, dict[str, object]]) -> StatusTree:
            tree = StatusTree()
            tree.set_dependency("/svc/cache", "/net/vpn")
            tree.restore_events(events_from_payload(payload),
                                nodes_from_payload({"nodes": nodes}))
            return tree

        seeded = started(as_before_the_key(payload["nodes"]))
        kept = started(payload["nodes"])
        self.assertEqual(self.said("/svc", seeded), self.said("/svc", old))
        self.assertEqual(self.said("/svc", kept), self.said("/svc", old))
        self.assertEqual(self._left(), [], "the restores")
        # a stored run beneath nodes that still count at their entries, which moves
        # a branch shielded from beneath, and a tick that finds a reading stale
        for tree in (seeded, kept):
            run = self.advance(60)
            with tree.storing("/svc"):
                tree.upsert("/svc/web", WARN, "slow")
                tree.upsert("/svc/cache", ERROR, "no route to host")
            self.assertEqual(self.said("/svc", tree)[:2], (WARN, run))
            with tree.storing("/s"):
                tree.upsert("/s/a", OK, stale_after=300.0)
                tree.upsert("/s/b", OK)
            tree.compare_periods(self.advance(600))
            self.assertIs(self.period("/s", tree).code, WARN)
            # and a page: the snapshot, and a closed branch's chip
            snapshot = tree.snapshot("/svc")
            assert snapshot is not None
            tree_module.chip_counts(snapshot)
        self.assertEqual(self._left(), [], "a run, a tick and a page")


class WhatABranchShowedTests(_Clocked):
    """Decision 6: the periods of what a node above others showed — those that ended
    derived from the rows at and beneath it, the one that holds from its entry."""

    def _said(self, path: str, tree: StatusTree | None = None
              ) -> list[tuple[StatusCode, datetime, datetime, bool, str]]:
        ended, _current = (tree or self.tree).shown_history(path)
        return [(period.code, period.began.at, period.until, period.began.before,
                 period.by) for period in ended]

    def test_a_branch_red_from_one_node_then_another_lists_one_red_period(self):
        with self.tree.storing("/p"):
            self.tree.upsert("/p/a", OK)
            self.tree.upsert("/p/b", OK)
        first = self.advance(600)
        with self.tree.storing("/p"):
            self.tree.upsert("/p/a", ERROR, "a broke")
            self.tree.upsert("/p/b", OK)
        self.advance(600)
        with self.tree.storing("/p"):
            self.tree.upsert("/p/a", OK)
            self.tree.upsert("/p/b", ERROR, "b broke")
        ended = self.advance(600)
        with self.tree.storing("/p"):
            self.tree.upsert("/p/a", OK)
            self.tree.upsert("/p/b", OK)
        self.assertEqual(self._said("/p"), [
            (ERROR, first, ended, False, "/p/a"),
            (OK, T0, first, True, ""),
        ])
        _ended, current = self.tree.shown_history("/p")
        assert current is not None
        self.assertEqual((current.code, current.began.at, current.by),
                         (OK, ended, "/p/b"))

    def test_the_period_that_holds_comes_from_its_entry_past_the_logs_reach(self):
        tree = StatusTree(event_log_size=4)
        with tree.storing("/p"):
            tree.upsert("/p/a", OK)
        broke = self.advance(60)
        with tree.storing("/p"):
            tree.upsert("/p/a", ERROR, "down")
        for index in range(6):
            self.advance(60)
            tree.upsert("/busy", ERROR if index % 2 else OK, f"reading {index}")
        ended, current = self.restarted(tree=tree).shown_history("/p")
        self.assertEqual(ended, [])
        assert current is not None
        self.assertEqual((current.code, current.began.at), (ERROR, broke))

    def test_a_period_staleness_made_ends_what_the_rows_say_where_it_began(self):
        # the rows say nothing of the leaf going stale: the period they give ends
        # where the one that holds began
        with self.tree.storing("/b"):
            self.tree.upsert("/b/leaf", OK, stale_after=300.0)
            self.tree.upsert("/b/other", OK)
        self.tree.compare_periods(self.advance(600))
        went = T0 + timedelta(seconds=300)
        self.assertEqual(self._said("/b"), [(OK, T0, went, True, "")])

    def test_a_shield_from_outside_is_read_from_its_dependencys_rows(self):
        self.tree.set_dependency("/services/cache", "/net/vpn")
        with self.tree.storing("/services"):
            self.tree.upsert("/services/web", OK)
            self.tree.upsert("/services/cache", ERROR, "no route to host")
        self.tree.upsert("/net/vpn", OK)
        shielded = self.advance(60)
        with self.tree.storing("/net/vpn"):
            self.tree.upsert("/net/vpn", ERROR, "the tunnel is down")
        answered = self.advance(60)
        with self.tree.storing("/net/vpn"):
            self.tree.upsert("/net/vpn", OK)
        self.assertEqual(self._said("/services"), [
            (OK, shielded, answered, False, "/net/vpn"),
            (ERROR, T0, shielded, True, ""),
        ])

    def test_a_branch_that_has_shown_nothing_yet_has_no_period_of_it(self):
        # a node beneath it, reached through /net/vpn, is not read yet when the
        # tunnel answers again: the shield on it ends, and the branch shows nothing
        # still, which is no period of it — the node's first reading is its first
        self.tree.set_dependency("/b/x", "/net/vpn")
        with self.tree.storing("/net/vpn"):
            self.tree.upsert("/net/vpn", ERROR, "the tunnel is down")
        self.advance(60)
        with self.tree.storing("/net/vpn"):
            self.tree.upsert("/net/vpn", OK)
        read = self.advance(60)
        with self.tree.storing("/b"):
            self.tree.upsert("/b/x", OK)
        ended, current = self.tree.shown_history("/b")
        self.assertEqual(ended, [])
        assert current is not None
        self.assertEqual((current.code, current.began.at, current.began.before),
                         (OK, read, True))
