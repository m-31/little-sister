"""A unit has a period of its own, and a run stamps only what it answered for
(ADR-0130).

A type declares its units — a key, a period, the node each answers for — and
measures one at a time; a check that declares none is the one-unit check. The
engine releases units on their own slots, grades the whole check over the newest
reading of every unit, and writes the unit's own path: the containers above it and
the node it answers for, and nothing beside it. Run facts, the tolerance, the retry
episode, the engine's `late` line, the declared cost and the pin's floor are per
unit. Each test here is written from one sentence of the record, with the values the
sentence is about.
"""
from __future__ import annotations

import os
import re
import threading
import time
from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from unittest import TestCase, mock

os.environ.setdefault("SECRET_KEY", "test-key")

from little_sister import app as app_module
from little_sister import instants
from little_sister.checks import (
    Check,
    CheckError,
    CheckResult,
    Measurement,
    Unit,
)
from little_sister.engine import (
    ENGINE_REPORT,
    HEARTBEAT_PATH,
    STAGGER_WINDOW_SECONDS,
    CheckInfo,
    Engine,
    EngineInfo,
    _stagger,
)
from little_sister.limits import Limits
from little_sister.series import SeriesRecord
from little_sister.status import StatusCode
from little_sister.tree import StatusTree

FAST = 60
SLOW = 86_400


def _wait_for(predicate, timeout: float = 3.0) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        if predicate():
            return True
        time.sleep(0.01)
    return predicate()


class _Plain(Check):
    """A check that declares no units: the one-unit case."""

    type_name = "plain"

    def measure(self) -> Sequence[Measurement]:
        return [Measurement(record={"n": 1})]

    def grade(self, measurements: Sequence[Measurement],
              now: datetime) -> CheckResult:
        return CheckResult(StatusCode.OK, ["fine"])


class _TwoTempo(Check):
    """A check that reads two things on two tempos — ``fast`` every minute and
    ``slow`` once a day — each answering for the node of its name beneath the
    mount, or beneath a container between (``level``)."""

    type_name = "two-tempo"

    def __init__(self, *, fast: int = FAST, slow: int = SLOW, level: str = "",
                 slow_cost: float | None = None, fast_cost: float | None = None,
                 **kwargs: object) -> None:
        super().__init__(**kwargs)   # type: ignore[arg-type]
        self._fast, self._slow, self._level = fast, slow, level
        self._costs = {"fast": fast_cost, "slow": slow_cost}
        #: The keys measured, in order; what the grading was handed last.
        self.measured: list[str] = []
        self.graded: tuple[Measurement, ...] = ()
        #: What each unit reads now — a test moves it between runs.
        self.readings: dict[str, dict[str, object]] = {
            "fast": {"n": 1}, "slow": {"size": 10}}
        #: The code each unit's node grades to, and how the slow one's text runs.
        self.codes: dict[str, StatusCode] = {
            "fast": StatusCode.OK, "slow": StatusCode.OK}
        self.gradings = 0
        self.raises: dict[str, Exception | None] = {"fast": None, "slow": None}
        self.block: dict[str, threading.Event | None] = {"fast": None, "slow": None}
        self.kept_seen: dict[str, tuple[SeriesRecord, ...]] = {}

    def _node(self, key: str) -> str:
        return f"{self._level}/{key}" if self._level else key

    def units(self) -> tuple[Unit, ...]:
        return (Unit("fast", self._fast, self._node("fast"), self._costs["fast"]),
                Unit("slow", self._slow, self._node("slow"), self._costs["slow"]))

    def measure(self) -> Sequence[Measurement]:
        return [*self.measure_unit("fast"), *self.measure_unit("slow")]

    def measure_unit(self, key: str) -> Sequence[Measurement]:
        gate = self.block[key]
        if gate is not None:
            gate.wait(timeout=5)
            gate.clear()
        self.measured.append(key)
        self.kept_seen[key] = self.kept(key)
        error = self.raises[key]
        if error is not None:
            raise error
        reading = self.readings[key]
        if reading is None:
            return []
        return [Measurement(record={"unit": key, **reading}, subject=key)]

    def grade(self, measurements: Sequence[Measurement],
              now: datetime) -> CheckResult:
        self.graded = tuple(measurements)
        self.gradings += 1
        by_key: dict[str, CheckResult] = {}
        for reading in measurements:
            key = str(reading.record["unit"])
            text = f"{key} graded in run {self.gradings} of {reading.record}"
            by_key[key] = CheckResult(self.codes[key], [text], name=key)
        children = tuple(by_key[key] for key in ("fast", "slow") if key in by_key)
        if self._level:
            level = CheckResult(StatusCode.UNDEFINED, [f"{self._level} container"],
                                name=self._level, children=children,
                                children_complete=True)
            children = (level,)
        return CheckResult(StatusCode.UNDEFINED, ["two tempos"],
                           children=children, children_complete=True)


class _Clocked(TestCase):
    """An engine on a clock the test moves: the monotonic one the schedule runs
    on, and the wall one every stamp is taken from."""

    def setUp(self) -> None:
        self.now = 1000.0
        self.wall = datetime(2026, 10, 17, 9, 0, tzinfo=UTC)
        patched = mock.patch.object(instants, "now", lambda: self.wall)
        patched.start()
        self.addCleanup(patched.stop)

    def _engine(self, *checks: Check, **kwargs: object) -> tuple[Engine, StatusTree]:
        tree = StatusTree()
        engine = Engine(list(checks), tree, clock=lambda: self.now,
                        wall=lambda: self.wall, poll_interval=0.02,
                        limits=Limits(memory_limit=None), **kwargs)  # type: ignore[arg-type]
        for item in engine._scheduled:
            item.stagger = 0.0
        return engine, tree

    @staticmethod
    def _item(engine: Engine, key: str):
        return next(item for item in engine._scheduled if item.unit.key == key)

    def _run(self, engine: Engine, key: str) -> None:
        """One scheduled run of a unit, inline, armed as the tick arms it."""
        item = self._item(engine, key)
        item.next_due = self.now + item.unit.period_seconds
        item.retrying = False
        engine._execute(item)

    def _advance(self, seconds: float) -> None:
        self.now += seconds
        self.wall += timedelta(seconds=seconds)


class TheSurfaceTests(TestCase):
    """Decision 1: a type declares its units with a period each, and measures one
    at a time; a check that declares none is the one-unit check."""

    def test_a_check_that_declares_no_units_is_the_one_unit_check(self):
        check = _Plain(path="/a", frequency_seconds=120)
        self.assertEqual(check.units(), (Unit("", 120, ""),))

    def test_the_one_unit_is_measured_through_measure(self):
        check = _Plain(path="/a")
        reading, = check.measure_unit("")
        self.assertEqual(reading.record, {"n": 1})

    def test_a_key_the_check_does_not_declare_is_refused(self):
        with self.assertRaises(CheckError) as caught:
            _Plain(path="/a").measure_unit("disk")
        self.assertIn("'disk'", str(caught.exception))
        self.assertIn("declares no unit", str(caught.exception))

    def test_a_units_node_is_relative_to_the_mount_and_its_period_positive(self):
        self.assertEqual(Unit("s3", 86_400, "/live/s3/").node, "live/s3")
        with self.assertRaises(CheckError):
            Unit("s3", 0)
        with self.assertRaises(CheckError):
            Unit("s3", 60, "../other")


class RefusedAtStartTests(TestCase):
    """What the engine refuses at construction, naming the check: a declaration
    the schedule could not honor is a refusal to start, never a degraded page."""

    class _Declares(_Plain):
        def __init__(self, declared: tuple[Unit, ...], **kwargs: object) -> None:
            super().__init__(**kwargs)
            self._declared = declared

        def units(self) -> tuple[Unit, ...]:
            return self._declared

        def measure_unit(self, key: str) -> Sequence[Measurement]:
            return []

    class _OnlyDeclares(_Plain):
        def units(self) -> tuple[Unit, ...]:
            return (Unit("a", 60, "a"), Unit("b", 60, "b"))

    def _refusal(self, *declared: Unit) -> str:
        check = self._Declares(declared, path="/svc/a")
        with self.assertRaises(CheckError) as caught:
            Engine([check], StatusTree())
        said = str(caught.exception)
        self.assertIn("/svc/a", said)
        return said

    def test_declaring_units_without_measure_unit_is_refused(self):
        with self.assertRaises(CheckError) as caught:
            Engine([self._OnlyDeclares(path="/svc/a")], StatusTree())
        self.assertIn("/svc/a", str(caught.exception))
        self.assertIn("measure_unit()", str(caught.exception))

    def test_two_units_of_one_key_are_refused(self):
        said = self._refusal(Unit("a", 60, "a"), Unit("a", 60, "b"))
        self.assertIn("'a'", said)

    def test_two_units_answering_for_one_node_are_refused(self):
        said = self._refusal(Unit("a", 60, "x"), Unit("b", 60, "x"))
        self.assertIn("x", said)

    def test_a_unit_beneath_another_units_node_is_refused(self):
        said = self._refusal(Unit("a", 60, "live"), Unit("b", 60, "live/s3"))
        self.assertIn("live/s3", said)

    def test_a_declared_unit_without_a_key_is_refused(self):
        said = self._refusal(Unit("", 60, "a"), Unit("b", 60, "b"))
        self.assertIn("key", said)

    def test_declaring_no_unit_at_all_is_refused(self):
        said = self._refusal()
        self.assertIn("no unit", said)


class ReleasedUnitsTests(_Clocked):
    """Decision 3: the engine releases units — one schedule entry per unit, armed
    on its period — and grades the whole check after each."""

    def test_each_unit_has_a_schedule_entry_of_its_own(self):
        engine, _tree = self._engine(_TwoTempo(path="/x"))
        rows = engine.info().checks
        self.assertEqual([(row.path, row.node, row.unit, row.frequency_seconds)
                          for row in rows],
                         [("/x", "/x/fast", "fast", FAST),
                          ("/x", "/x/slow", "slow", SLOW)])
        self.assertEqual(engine.info().check_count, 1)
        self.assertEqual(engine.info().unit_count, 2)
        self.assertEqual(engine.check_roots(), ["/x"])
        self.assertEqual(len(engine.checks), 1)

    def test_the_one_unit_check_keeps_its_row_as_it_was(self):
        engine, _tree = self._engine(_Plain(path="/a", frequency_seconds=120))
        row, = engine.info().checks
        self.assertEqual((row.path, row.node, row.unit, row.frequency_seconds),
                         ("/a", "/a", "", 120))
        self.assertEqual(engine.info().unit_count, 1)

    def test_a_unit_runs_at_start_and_then_on_its_own_period(self):
        check = _TwoTempo(path="/x")
        engine, _tree = self._engine(check)
        engine.start()
        try:
            self.assertTrue(_wait_for(lambda: sorted(check.measured)
                                      == ["fast", "slow"]))
            self._advance(FAST + 1)
            self.assertTrue(_wait_for(lambda: check.measured.count("fast") == 2))
            time.sleep(0.1)
            self.assertEqual(check.measured.count("slow"), 1)
            self._advance(SLOW)
            self.assertTrue(_wait_for(lambda: check.measured.count("slow") == 2))
        finally:
            engine.stop()

    def test_a_units_run_measures_it_and_grades_the_whole_check(self):
        check = _TwoTempo(path="/x")
        engine, _tree = self._engine(check)
        engine.run_once()
        check.readings["fast"] = {"n": 2}
        self._run(engine, "fast")
        self.assertEqual(check.measured, ["fast", "slow", "fast"])
        # the newest reading of every unit: this one's new, the other's as it was
        self.assertEqual([dict(reading.record) for reading in check.graded],
                         [{"unit": "fast", "n": 2}, {"unit": "slow", "size": 10}])

    def test_a_unit_that_measured_nothing_clears_what_the_engine_held_of_it(self):
        check = _TwoTempo(path="/x")
        engine, tree = self._engine(check)
        engine.run_once()
        self.assertIsNotNone(tree.snapshot("/x/slow"))
        check.readings["slow"] = None    # type: ignore[assignment]
        self._run(engine, "slow")
        self.assertEqual([dict(reading.record) for reading in check.graded],
                         [{"unit": "fast", "n": 1}])
        self.assertIsNone(tree.snapshot("/x/slow"))

    def test_units_of_one_check_run_one_at_a_time(self):
        check = _TwoTempo(path="/x")
        gate = threading.Event()
        check.block["fast"] = gate
        engine, _tree = self._engine(check)
        engine.start()
        try:
            self.assertTrue(_wait_for(
                lambda: self._item(engine, "fast").run_started_mono is not None))
            time.sleep(0.1)
            self.assertEqual(check.measured, [])          # fast waits at its gate
            self.assertFalse(self._item(engine, "slow").running)
            gate.set()
            self.assertTrue(_wait_for(lambda: check.measured == ["fast", "slow"]))
        finally:
            gate.set()
            engine.stop()

    def test_the_stagger_is_the_units_own_and_capped_by_its_period(self):
        check = _TwoTempo(path="/x", fast=30)
        fast, slow = check.units()
        self.assertNotEqual(_stagger(check, fast), _stagger(check, slow))
        self.assertLess(_stagger(check, fast), 30.0)
        self.assertLess(_stagger(check, slow), STAGGER_WINDOW_SECONDS)
        plain = _Plain(path="/a", frequency_seconds=120)
        self.assertEqual(_stagger(plain, plain.units()[0]), _stagger(plain))


class StampTests(_Clocked):
    """Decision 4: a stamp belongs to whoever took the look — a unit's run writes
    its own path and nothing beside it."""

    def _stamps(self, tree: StatusTree, *paths: str) -> dict[str, datetime | None]:
        return {path: (snap.timestamp if (snap := tree.snapshot(path)) else None)
                for path in paths}

    def test_a_units_run_moves_the_stamp_on_its_own_path_alone(self):
        check = _TwoTempo(path="/x", level="live")
        engine, tree = self._engine(check)
        engine.run_once()
        before = self._stamps(tree, "/x", "/x/live", "/x/live/fast", "/x/live/slow")
        self.assertEqual(set(before.values()), {self.wall})
        self._advance(FAST)
        self._run(engine, "fast")
        after = self._stamps(tree, "/x", "/x/live", "/x/live/fast", "/x/live/slow")
        self.assertEqual(after["/x"], self.wall)
        self.assertEqual(after["/x/live"], self.wall)
        self.assertEqual(after["/x/live/fast"], self.wall)
        self.assertEqual(after["/x/live/slow"], before["/x/live/slow"])

    def test_a_sibling_keeps_what_its_own_unit_wrote(self):
        check = _TwoTempo(path="/x")
        engine, tree = self._engine(check)
        engine.run_once()
        slow_text = tree.snapshot("/x/slow").reason
        self.assertEqual(check.gradings, 2)
        self._run(engine, "fast")
        self.assertEqual(check.gradings, 3)          # graded whole again
        self.assertEqual(tree.snapshot("/x/slow").reason, slow_text)
        self.assertIn("run 3", tree.snapshot("/x/fast").reason[0])

    def test_a_siblings_wait_counts_its_own_readings_alone(self):
        # a node that needs three readings of a worse code before it publishes
        # (escalate_after) counts the readings of its own unit, never a neighbor's
        check = _TwoTempo(path="/x", escalate_after=3)
        engine, tree = self._engine(check)
        engine.run_once()                      # the slow node publishes OK
        check.codes["slow"] = StatusCode.ERROR
        self._run(engine, "slow")              # one reading of ERROR, held
        held = tree.snapshot("/x/slow")
        assert held.damping is not None
        self.assertEqual((held.damping.pending, held.damping.seen),
                         (StatusCode.ERROR, 1))
        for _ in range(4):
            self._run(engine, "fast")
        held = tree.snapshot("/x/slow")
        assert held.damping is not None
        self.assertEqual(held.damping.seen, 1)
        self.assertIs(tree.snapshot("/x").code, StatusCode.OK)   # still held back
        self._run(engine, "slow")
        self._run(engine, "slow")
        self.assertIsNone(tree.snapshot("/x/slow").damping)
        self.assertIs(tree.snapshot("/x").code, StatusCode.ERROR)

    def test_no_event_is_written_for_a_sibling(self):
        check = _TwoTempo(path="/x")
        engine, tree = self._engine(check)
        engine.run_once()
        rows = len(tree.recent_events())
        self._run(engine, "fast")
        self.assertEqual(len(tree.recent_events()), rows)
        check.codes["slow"] = StatusCode.WARN
        self._run(engine, "fast")                  # the slow grading changed, but
        self.assertEqual(len(tree.recent_events()), rows)   # its unit did not run
        self._run(engine, "slow")
        self.assertEqual([event.path for event in tree.recent_events()[rows:]],
                         ["/x/slow"])

    def test_a_one_unit_check_writes_the_whole_tree_as_before(self):
        class _Branch(_Plain):
            def grade(self, measurements, now):
                return CheckResult(StatusCode.OK, ["host"], children=(
                    CheckResult(StatusCode.OK, ["disk"], name="disk"),))
        engine, tree = self._engine(_Branch(path="/h"))
        engine.run_once()
        self._advance(5)
        engine.run_once()
        self.assertEqual(tree.snapshot("/h/disk").timestamp, self.wall)

    def test_one_reading_of_a_unit_is_placed_on_its_node(self):
        check = _TwoTempo(path="/x")
        engine, tree = self._engine(check)
        engine.run_once()
        slow = tree.snapshot("/x/slow")
        self.assertEqual((slow.subject, slow.record),
                         ("slow", {"unit": "slow", "size": 10}))
        self.assertIsNone(tree.snapshot("/x").record)


class FactsPerUnitTests(_Clocked):
    """Decision 5: run facts, tolerance, retry and cost are per unit; a container
    says the newest write beneath it, the shortest period and the earliest slot."""

    def test_a_units_node_says_its_period_and_goes_stale_by_it(self):
        engine, tree = self._engine(_TwoTempo(path="/x", level="live"))
        engine.run_once()
        self.assertEqual(tree.snapshot("/x/live/slow").frequency_seconds, SLOW)
        self.assertEqual(tree.snapshot("/x/live/slow").stale_after_seconds, 2 * SLOW)
        self.assertEqual(tree.snapshot("/x/live/fast").frequency_seconds, FAST)
        self.assertEqual(tree.snapshot("/x/live/fast").stale_after_seconds, 2 * FAST)
        # the containers: the shortest period beneath them
        self.assertEqual(tree.snapshot("/x/live").frequency_seconds, FAST)
        self.assertEqual(tree.snapshot("/x").frequency_seconds, FAST)
        self._advance(3 * FAST)
        self._run(engine, "fast")
        self.assertFalse(tree.snapshot("/x/live/slow").stale)
        self._advance(2 * SLOW)
        self._run(engine, "fast")
        self.assertTrue(tree.snapshot("/x/live/slow").own_stale)
        self.assertFalse(tree.snapshot("/x/live/fast").own_stale)

    def test_run_facts_stand_on_the_units_node_and_on_the_containers(self):
        engine, tree = self._engine(_TwoTempo(path="/x", level="live"))
        engine.start()
        try:
            self.assertTrue(_wait_for(
                lambda: all(row.last_run_at for row in engine.info().checks)))
        finally:
            engine.stop()
        slow, fast = tree.snapshot("/x/live/slow"), tree.snapshot("/x/live/fast")
        assert slow.run is not None and fast.run is not None
        self.assertEqual(slow.run.next_run_at, self.wall + timedelta(seconds=SLOW))
        self.assertEqual(fast.run.next_run_at, self.wall + timedelta(seconds=FAST))
        self.assertIsNotNone(slow.run.wall_seconds)
        for container in ("/x", "/x/live"):
            run = tree.snapshot(container).run
            assert run is not None, container
            self.assertEqual(run.next_run_at, self.wall + timedelta(seconds=FAST))
        # the envelope's shape: the unit's node carries its own facts
        self.assertEqual(tree.snapshot("/x/live/slow").run.next_run_at,
                         self.wall + timedelta(seconds=SLOW))

    def test_the_retry_pulls_in_the_failing_units_slot_alone(self):
        check = _TwoTempo(path="/x", retry_interval_seconds=30, retry_attempts=2)
        check.codes["slow"] = StatusCode.ERROR
        engine, _tree = self._engine(check)
        self._run(engine, "fast")
        self._run(engine, "slow")
        self.assertEqual(self._item(engine, "slow").next_due, self.now + 30)
        self.assertTrue(self._item(engine, "slow").retrying)
        self.assertEqual(self._item(engine, "fast").next_due, self.now + FAST)
        self.assertFalse(self._item(engine, "fast").retrying)

    def test_the_retry_reads_what_the_units_own_subtree_rolls_up_to(self):
        # the fast node is red; the slow unit's run grades the whole check and
        # sees it — but its own subtree is well, so its slot is not pulled in
        check = _TwoTempo(path="/x", retry_interval_seconds=30, retry_attempts=2)
        check.codes["fast"] = StatusCode.ERROR
        engine, _tree = self._engine(check)
        self._run(engine, "fast")
        self._run(engine, "slow")
        self.assertEqual(self._item(engine, "fast").next_due, self.now + 30)
        self.assertEqual(self._item(engine, "slow").next_due, self.now + SLOW)

    def test_late_names_the_unit(self):
        check = _TwoTempo(path="/x")
        engine, tree = self._engine(check)
        engine.start()
        try:
            self.assertTrue(_wait_for(
                lambda: all(row.last_run_at for row in engine.info().checks)))
            with engine._lock:
                self._item(engine, "fast").elapsed_seconds = 100.0
            def late_lines():
                snap = tree.snapshot(f"{HEARTBEAT_PATH}/{ENGINE_REPORT}")
                return [line for line in (snap.reasons if snap else ())
                        if line.slug.startswith("late.")]
            self.assertTrue(_wait_for(lambda: bool(late_lines())))
        finally:
            engine.stop()
        line, = late_lines()
        self.assertIn("/x/fast ran for", line.text)
        self.assertIn("its frequency of 1m", line.text)

    def test_the_startup_sum_takes_each_units_cost_over_its_period(self):
        engine, _tree = self._engine(_TwoTempo(path="/x", fast_cost=30.0,
                                               slow_cost=3600.0))
        self.assertAlmostEqual(engine.info().declared_workers,
                               30.0 / FAST + 3600.0 / SLOW)
        rows = engine.info().checks
        self.assertEqual([row.expected_cost for row in rows], [30.0, 3600.0])

    def test_a_declared_load_that_cannot_fit_is_refused_naming_the_unit(self):
        with self.assertRaises(CheckError) as caught:
            self._engine(_TwoTempo(path="/x", fast_cost=600.0), max_workers=4)
        self.assertIn("/x/fast", str(caught.exception))

    def test_the_timeout_above_a_units_period_is_warned_for_that_unit(self):
        with self.assertLogs("little_sister.logger", level="WARNING") as caught:
            self._engine(_TwoTempo(path="/x", fast=30, timeout_seconds=45.0))
        self.assertEqual(len(caught.records), 1)
        self.assertIn("/x/fast", caught.output[0])
        self.assertIn("longer than its frequency 30s", caught.output[0])

    def test_the_pin_floor_at_a_units_node_is_its_period(self):
        engine, _tree = self._engine(_TwoTempo(path="/x", level="live"))
        with mock.patch.object(app_module, "engine", engine):
            self.assertEqual(app_module._interval_floor("/x/live/slow").seconds, SLOW)
            self.assertEqual(app_module._interval_floor("/x/live/slow/deep").seconds,
                             SLOW)
            self.assertEqual(app_module._interval_floor("/x/live/fast").seconds, FAST)
            # above the units, a pin covers the fastest of them
            self.assertEqual(app_module._interval_floor("/x/live").seconds, FAST)
            self.assertEqual(app_module._interval_floor("/x").seconds, FAST)
            self.assertIsNone(app_module._interval_floor("/elsewhere"))

    def test_the_one_unit_checks_floor_is_its_frequency(self):
        engine, _tree = self._engine(_Plain(path="/a", frequency_seconds=120))
        with mock.patch.object(app_module, "engine", engine):
            self.assertEqual(app_module._interval_floor("/a/x").seconds, 120)


class FailurePerUnitTests(_Clocked):
    """A unit that raises is an ERROR on its own node alone (ADR-0078 decision 4):
    the containers are graded from the newest readings, the neighbor keeps what
    its unit wrote."""

    def test_a_unit_that_raises_reddens_its_own_node_alone(self):
        check = _TwoTempo(path="/x")
        engine, tree = self._engine(check)
        engine.run_once()
        check.raises["slow"] = RuntimeError("no route to the bucket")
        self._advance(SLOW)
        self._run(engine, "slow")
        slow = tree.snapshot("/x/slow")
        self.assertIs(slow.own_code, StatusCode.ERROR)
        self.assertIn("no route to the bucket", slow.reason[0])
        self.assertEqual(slow.timestamp, self.wall)
        self.assertIs(tree.snapshot("/x/fast").own_code, StatusCode.OK)
        self.assertIs(tree.snapshot("/x").own_code, StatusCode.UNDEFINED)
        self.assertIs(tree.snapshot("/x").code, StatusCode.ERROR)   # by roll-up
        # the grading ran over the unit's last good reading, which it keeps
        self.assertEqual([dict(reading.record) for reading in check.graded],
                         [{"unit": "slow", "size": 10}, {"unit": "fast", "n": 1}])

    def test_a_grading_that_raises_is_the_checks_error(self):
        check = _TwoTempo(path="/x")
        engine, tree = self._engine(check)
        engine.run_once()
        check.grade = mock.Mock(side_effect=ValueError("bad"))   # type: ignore[method-assign]
        self._run(engine, "fast")
        self.assertIs(tree.snapshot("/x").own_code, StatusCode.ERROR)
        self.assertIn("check error: bad", tree.snapshot("/x").reason[0])


class KeptInsideAUnitTests(_Clocked):
    """`kept()` answers inside `measure_unit`, as inside `measure` (ADR-0113)."""

    def test_kept_answers_inside_measure_unit(self):
        check = _TwoTempo(path="/x", series_keep=3)
        engine, _tree = self._engine(check)
        engine.run_once()
        self.assertEqual(check.kept_seen["slow"], ())
        self._run(engine, "slow")
        kept, = check.kept_seen["slow"]
        self.assertEqual(dict(kept.data), {"unit": "slow", "size": 10})
        with self.assertRaises(CheckError):
            check.kept("slow")


class SystemPageTests(TestCase):
    """`/system` lists a check's units beneath it, each with its period and its
    last run."""

    def setUp(self) -> None:
        app_module.app.config["TESTING"] = True
        self.client = app_module.app.test_client()
        self.client.post("/login",
                         data={"username": "pan", "password": "12345678"})

    def _rows(self, *rows: CheckInfo) -> list[list[str]]:
        info = EngineInfo(started_at=datetime(2026, 10, 17, 9, 0, tzinfo=UTC),
                          uptime_seconds=5.0, max_workers=8, check_count=1,
                          running=0, checks=rows, unit_count=len(rows))
        stub = mock.Mock()
        stub.info.return_value = info
        with mock.patch.object(app_module, "engine", stub):
            body = self.client.get("/system?fragment=1").get_data(as_text=True)
        table = body.split("<table", 1)[1].split("</table>", 1)[0]
        cells = table.split("<tbody>", 1)[1].split("</tr>")[:-1]
        return [re.findall(r"<td[^>]*>(.*?)</td>", row, re.S) for row in cells]

    def _row(self, **facts: object) -> CheckInfo:
        base: dict[str, object] = {
            "path": "/x", "type_name": "two-tempo", "frequency_seconds": FAST,
            "running": False, "running_since": None, "running_seconds": None,
            "next_run_at": datetime(2026, 10, 17, 9, 1, tzinfo=UTC),
            "next_in_seconds": 60.0,
            "last_run_at": datetime(2026, 10, 17, 9, 0, tzinfo=UTC),
            "elapsed_seconds": 0.4}
        return CheckInfo(**(base | facts))   # type: ignore[arg-type]

    def test_a_units_row_names_its_node_and_its_key(self):
        rows = self._rows(
            self._row(node="/x/fast", unit="fast"),
            self._row(node="/x/slow", unit="slow", frequency_seconds=SLOW))
        self.assertIn('href="/status/x/fast">/x/fast</a>', rows[0][0])
        self.assertIn("unit fast", rows[0][0])
        self.assertIn("two-tempo", rows[0][0])
        self.assertIn('href="/status/x/slow">/x/slow</a>', rows[1][0])
        self.assertIn("1d", rows[1][1])

    def test_a_one_unit_row_is_what_it_was(self):
        row, = self._rows(self._row(path="/svc/a", node="/svc/a", type_name="http"))
        self.assertIn('href="/status/svc/a">/svc/a</a>', row[0])
        self.assertNotIn("unit", row[0])
