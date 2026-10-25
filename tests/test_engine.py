import json
import subprocess
import sys
import tempfile
import textwrap
import threading
import time
import unittest
from collections.abc import Sequence
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest import TestCase
from unittest.mock import patch

from little_sister import engine as engine_module
from little_sister import self_report
from little_sister.checks import Measurement
from little_sister.checks.base import Check, CheckError, CheckResult
from little_sister.checks.metadata import Stated
from little_sister.config import config
from little_sister.engine import (
    FAILURE_RECORD_BYTES,
    Engine,
    _failure_measurement,
)
from little_sister.limits import Limits
from little_sister.nodes import NodeMeta
from little_sister.reasons import Entry
from little_sister.state import EVENTS_FILE
from little_sister.status import HEARTBEAT_PATH, StatusCode
from little_sister.tree import StatusTree
from tests.running import subprocess_env
from tests.state_files import on_disk


class _FakeCheck(Check):
    """A controllable check for tests."""

    def __init__(self, *, result: CheckResult | None = None,
                 raises: Exception | None = None,
                 ran: threading.Event | None = None,
                 block: threading.Event | None = None,
                 measurements: Sequence[Measurement] = (),
                 raises_grading: Exception | None = None,
                 **kwargs: object) -> None:
        super().__init__(**kwargs)   # type: ignore[arg-type]
        self._result = result or CheckResult(StatusCode.OK)
        self._raises = raises
        self._raises_grading = raises_grading
        self._ran = ran
        self._block = block
        self._measurements = tuple(measurements)
        #: What the grading was handed on the last run, for a test whose subject
        #: is the seam rather than the verdict.
        self.graded: tuple[Measurement, ...] = ()
        self.graded_at: datetime | None = None

    def measure(self) -> Sequence[Measurement]:
        if self._block is not None:
            self._block.wait(timeout=5)
        if self._raises is not None:
            raise self._raises
        if self._ran is not None:
            self._ran.set()
        return self._measurements

    def grade(self, measurements: Sequence[Measurement],
              now: datetime) -> CheckResult:
        self.graded = tuple(measurements)
        self.graded_at = now
        if self._raises_grading is not None:
            raise self._raises_grading
        return self._result


class _CostlyCheck(_FakeCheck):
    """A check type that declares what a run of it costs, the way a type with an
    estate to read computes it from its own configuration (ADR-0075)."""

    def __init__(self, *, cost: float | None = None, entries: int | None = None,
                 **kwargs: object) -> None:
        super().__init__(**kwargs)
        self._cost = cost
        self._entries = entries

    def expected_cost(self) -> float | None:
        return self._cost

    def expected_entries(self) -> int | None:
        return self._entries


class RecordMeasurementTests(TestCase):
    """The largest record the last run carried, beside what the type declared
    (ADR-0075 decision 8): an estimate nobody can compare against a measurement
    decays invisibly."""

    def _info(self, result):
        engine = Engine([_FakeCheck(path="/a", result=result)], StatusTree())
        engine.run_once()
        check, = engine.info().checks
        return check

    def test_a_run_with_no_record_measures_nothing(self):
        # empty is not zero: nothing measured is not the claim that nothing is held
        self.assertIsNone(self._info(CheckResult(StatusCode.OK, ["fine"]))
                          .record_bytes)

    def test_the_largest_record_is_what_is_kept(self):
        info = self._info(CheckResult(reason=[
            Entry("small", "a", StatusCode.OK, data={"a": 1}),
            Entry("big", "b", StatusCode.OK, data={"note": "x" * 100}),
        ]))
        assert info.record_bytes is not None
        self.assertGreater(info.record_bytes, 100)
        self.assertLess(info.record_bytes, 200)

    def test_a_branch_check_is_measured_over_its_children(self):
        # the records sit on the children; the declaration is about the check
        info = self._info(CheckResult(StatusCode.OK, ["host up"], children=(
            CheckResult(reason=[Entry("d", "disk", StatusCode.OK,
                                      data={"note": "y" * 200})], name="disk"),
        )))
        assert info.record_bytes is not None
        self.assertGreater(info.record_bytes, 200)

    def test_the_measurement_is_of_the_last_run_and_is_cleared(self):
        # like `elapsed_seconds` above it: a figure that outlived the run that
        # produced it would be exactly the drift this exists to show
        check = _FakeCheck(path="/a", result=CheckResult(reason=[
            Entry("w", "x", StatusCode.OK, data={"note": "z" * 200})]))
        engine = Engine([check], StatusTree())
        engine.run_once()
        self.assertIsNotNone(engine.info().checks[0].record_bytes)
        check._result = CheckResult(StatusCode.OK, ["nothing to say"])
        engine.run_once()
        self.assertIsNone(engine.info().checks[0].record_bytes)

    def test_the_declaration_travels_beside_the_measurement(self):
        engine = Engine([_RecordingCheck(path="/a", record=1_024,
                                         result=CheckResult(StatusCode.OK))],
                        StatusTree())
        engine.run_once()
        check, = engine.info().checks
        self.assertEqual(check.expected_record, 1_024)
        self.assertEqual(engine.info().record_limit, config.record_limit)


class _RecordingCheck(_FakeCheck):
    """A type that declares how heavy one of its records is (ADR-0075)."""

    def __init__(self, *, record: int | None = None, **kwargs: object) -> None:
        super().__init__(**kwargs)
        self._record = record

    def expected_record(self) -> int | None:
        return self._record


class _ConfiguredCheck(_FakeCheck):
    """A leaf check that reports a config summary (ADR-0013)."""

    def config_summary(self) -> str:
        return "- **url:** http://x"


def _wait_for(predicate, timeout: float = 2.0) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        if predicate():
            return True
        time.sleep(0.01)
    return predicate()


class EngineTests(TestCase):
    def test_run_once_upserts_and_rolls_up(self):
        tree = StatusTree()
        checks = [
            _FakeCheck(path="/svc/a", result=CheckResult(StatusCode.OK)),
            _FakeCheck(path="/svc/b",
                       result=CheckResult(StatusCode.ERROR, ["boom"])),
        ]
        Engine(checks, tree).run_once()
        self.assertEqual(tree.effective("/svc"), StatusCode.ERROR)
        node_b = tree.snapshot("/svc/b")
        assert node_b is not None
        self.assertEqual(node_b.own_code, StatusCode.ERROR)
        self.assertEqual(node_b.reason, ("boom",))

    def test_a_runs_measurement_reaches_the_node_it_measured(self):
        """The seam of ADR-0085 under the split (ADR-0086): a check reads an
        object, hands back a measurement, and the **engine** puts it on the node
        that stands for it — the grading never touches it."""
        tree = StatusTree()
        check = _FakeCheck(
            path="/web", subject="http://web01.example",
            result=CheckResult(StatusCode.OK, ["200 in 412 ms"]),
            measurements=[Measurement(record={"status": 200,
                                              "response_ms": 412})])
        Engine([check], tree).run_once()
        node = tree.snapshot("/web")
        assert node is not None
        self.assertEqual(node.subject, "http://web01.example")
        self.assertEqual(node.record["response_ms"], 412)

    def test_a_measurement_may_name_an_object_the_answer_taught_it(self):
        """A check declares its object at construction, out of its configuration —
        but a rate-limit check learns whose budget it read only from the answer, so
        a measurement that names one wins."""
        tree = StatusTree()
        check = _FakeCheck(
            path="/gh", subject="configured",
            measurements=[Measurement(record={"remaining": 4980},
                                      subject="from-the-answer")])
        Engine([check], tree).run_once()
        node = tree.snapshot("/gh")
        assert node is not None
        self.assertEqual(node.subject, "from-the-answer")

    def test_several_objects_are_placed_by_the_grading_and_not_by_the_engine(self):
        """One run, several objects: which node, child or line each stands for is
        what the grading already said in the tree it returned — a record that
        becomes a *line* is an `Entry` the engine has no shape for — so the engine
        places none of them and the check's own node measures nothing."""
        tree = StatusTree()
        check = _FakeCheck(
            path="/hosts", subject="the-estate",
            result=CheckResult(reason=[
                Entry("a", "host-a fine", StatusCode.OK, subject="host-a",
                      data={"cpu_pct": 7}),
                Entry("b", "host-b busy", StatusCode.WARN, subject="host-b",
                      data={"cpu_pct": 91})]),
            measurements=[Measurement(record={"cpu_pct": 7}, subject="host-a"),
                          Measurement(record={"cpu_pct": 91},
                                      subject="host-b")])
        Engine([check], tree).run_once()
        node = tree.snapshot("/hosts")
        assert node is not None
        self.assertEqual(node.subject, "")
        self.assertIsNone(node.record)
        lines = {entry.slug: entry for entry in node.reasons}
        self.assertEqual(lines["b"].data["cpu_pct"], 91)

    def test_a_run_that_measures_nothing_clears_the_last_reading(self):
        """The node's observation time moves with every run, so a kept record
        would not be undated but **wrongly dated** (ADR-0085)."""
        tree = StatusTree()
        check = _FakeCheck(path="/web", subject="web01.example",
                           measurements=[Measurement(record={"status": 200})])
        Engine([check], tree).run_once()
        check._measurements = ()
        Engine([check], tree).run_once()
        node = tree.snapshot("/web")
        assert node is not None
        self.assertEqual(node.subject, "")
        self.assertIsNone(node.record)

    def test_the_grading_is_handed_the_measurements_and_an_aware_clock(self):
        """Both halves of the purity promise, at the one seam that can keep it:
        the grading is given what was measured and what time it is, so nothing in
        it has to reach for either."""
        taken = Measurement(record={"status": 200}, subject="web01.example")
        check = _FakeCheck(path="/web", measurements=[taken])
        Engine([check], StatusTree()).run_once()
        self.assertEqual(check.graded, (taken,))
        assert check.graded_at is not None
        self.assertIsNotNone(check.graded_at.tzinfo)

    def test_a_check_that_raises_while_measuring_still_records_the_attempt(self):
        """The engine writes the failure record itself, so no author can forget to
        record a reading that failed — which is exactly the weakness of doing it by
        hand in one check (ADR-0085 decision 3, ADR-0086)."""
        tree = StatusTree()
        check = _FakeCheck(path="/web", subject="web01.example",
                           raises=RuntimeError("the door is shut"))
        Engine([check], tree).run_once()
        node = tree.snapshot("/web")
        assert node is not None
        self.assertEqual(node.code, StatusCode.ERROR)
        self.assertEqual(node.subject, "web01.example")
        self.assertIn("the door is shut", node.record["error"])

    def test_a_grading_that_raises_does_not_discard_the_reading_it_had(self):
        """A grading that threw over a reading that succeeded has not made that
        reading untrue, and `{"error": …}` in its place would throw away the one
        thing this run did get right."""
        tree = StatusTree()
        check = _FakeCheck(
            path="/web", subject="web01.example",
            measurements=[Measurement(record={"status": 200})],
            raises_grading=RuntimeError("bad threshold"))
        Engine([check], tree).run_once()
        node = tree.snapshot("/web")
        assert node is not None
        self.assertEqual(node.code, StatusCode.ERROR)
        self.assertEqual(node.record["status"], 200)

    def test_the_failure_reading_itself_names_the_object(self):
        """The Done-when of ADR-0086, held at the only place that can hold it.

        The node test above cannot: `_store` resolves a node's subject as
        `measurement.subject or check.subject`, so the node is named correctly
        whether or not the **reading** carries the object — the fallback answers
        for both paths and the two are indistinguishable from outside. Measured:
        drop `subject=check.subject` from `_failure_measurement` and the whole
        suite still passes.

        It has to be on the measurement, because the measurement is what a series
        keeps. A record that reaches a store without its object is a reading about
        nothing, and an identity not written down at the reading cannot be added
        afterwards — which is the entire reason a check declares its object at
        construction rather than per run.
        """
        check = _FakeCheck(path="/web", subject="web01.example")
        taken, = _failure_measurement(check, RuntimeError("the door is shut"))
        self.assertEqual(taken.subject, "web01.example")
        self.assertIn("the door is shut", taken.record["error"])

    def test_a_failure_reading_is_not_built_at_the_cost_of_the_error(self):
        """The guard around it: a record that will not build must never cost the
        `ERROR` that is already decided. A subject too long to travel is refused
        by the seam, and what comes back is no reading rather than no verdict."""
        check = _FakeCheck(path="/web", subject="fine")
        object.__setattr__(check, "subject", "x" * 4096)   # past MAX_SUBJECT_LENGTH
        self.assertEqual(_failure_measurement(check, RuntimeError("boom")), ())

    def test_a_failure_record_is_bounded_so_it_cannot_refuse_itself(self):
        """An exception message routinely carries a page of captured output. The
        reason line keeps it whole; the record is kept per reading and must not be
        what fills a series."""
        tree = StatusTree()
        check = _FakeCheck(path="/web", subject="web01.example",
                           raises=RuntimeError("x" * 5000))
        Engine([check], tree).run_once()
        node = tree.snapshot("/web")
        assert node is not None
        self.assertLessEqual(len(json.dumps(node.record).encode("utf-8")),
                             FAILURE_RECORD_BYTES)
        self.assertIn("x" * 100, node.reasons[0].text)

    def _failure_record(self, message):
        check = _FakeCheck(path="/web", subject="web01.example")
        taken = _failure_measurement(check, RuntimeError(message))
        self.assertEqual(len(taken), 1, "the failure record was lost")
        return taken[0].record

    def test_a_failure_record_in_ascii_fits_the_engines_maximum(self):
        message = "x" * 500
        self.assertEqual(len(message), 500)
        record = self._failure_record(message)
        self.assertLessEqual(len(json.dumps(record).encode("utf-8")),
                             FAILURE_RECORD_BYTES)

    def test_a_failure_record_of_escaping_characters_fits_exactly(self):
        """Every one of these escapes to two bytes, so the clip fills the budget to
        the last byte: the record weighs exactly the maximum — a ceiling that is
        also reached, which is what makes it a derivation and not a guess."""
        message = '"' * 500
        self.assertEqual(len(message), 500)
        record = self._failure_record(message)
        self.assertEqual(len(json.dumps(record).encode("utf-8")),
                         FAILURE_RECORD_BYTES)

    def test_a_failure_record_in_emoji_is_kept(self):
        """The regression. Clipped to 500 **characters** this was 6013 bytes, past
        the 2 KB `record_limit`, so the seam refused it and the engine's guard
        dropped the failure record — the one thing ADR-0086 decision 5 exists to
        prevent. Clipped in bytes it is kept, and inside the maximum."""
        emoji = "\U0001F600"
        self.assertEqual(len(emoji), 1)
        self.assertEqual(len(json.dumps(emoji)), 14)     # 12 bytes and 2 quotes
        message = emoji * 500
        self.assertEqual(len(message), 500)
        record = self._failure_record(message)
        self.assertIn(emoji, record["error"])
        self.assertLessEqual(len(json.dumps(record).encode("utf-8")),
                             FAILURE_RECORD_BYTES)

    def test_a_declared_record_below_the_maximum_is_held_to_it(self):
        """The floor at the engine: a type declaring less than the record the
        engine can write for it is reported at that record's maximum, with its
        own number beside it; one that declares nothing is left undeclared."""
        class Small(_FakeCheck):
            def expected_record(self) -> int:
                return 64

        tree = StatusTree()
        engine = Engine([Small(path="/small"), _FakeCheck(path="/silent")], tree)
        info = {c.path: c for c in engine.info().checks}
        self.assertEqual(info["/small"].expected_record, FAILURE_RECORD_BYTES)
        self.assertEqual(info["/small"].stated_record, 64)
        self.assertIsNone(info["/silent"].expected_record)
        self.assertIsNone(info["/silent"].stated_record)

    def test_a_declared_dependency_reaches_the_tree(self):
        """The declaration is worth nothing until the tree knows about it, and the
        tree is where the rule is evaluated — so this seam is the whole of what
        makes `depends_on` in a check file do anything at all."""
        tree = StatusTree()
        checks = [
            _FakeCheck(path="/net/vpn", result=CheckResult(StatusCode.ERROR)),
            _FakeCheck(path="/svc/api", result=CheckResult(StatusCode.ERROR),
                       depends_on="/net/vpn"),
        ]
        Engine(checks, tree).run_once()
        self.assertEqual(tree.dependents("/net/vpn"), ("/svc/api",))
        node = tree.snapshot("/svc/api")
        assert node is not None
        self.assertEqual(node.shielded_by, "/net/vpn")
        self.assertEqual(tree.effective("/svc"), StatusCode.UNDEFINED)

    def test_a_check_without_one_registers_nothing(self):
        # the guard, not the loop: registering unconditionally would hand the tree
        # a `None` target, and nearly every deployment declares no dependency at all
        tree = StatusTree()
        Engine([_FakeCheck(path="/svc/api")], tree).run_once()
        self.assertEqual(tree.dependents("/svc/api"), ())
        node = tree.snapshot("/svc/api")
        assert node is not None
        self.assertIsNone(node.shielded_by)

    def test_leaf_config_lands_on_its_node(self):
        tree = StatusTree()
        Engine([_ConfiguredCheck(path="/svc/api")], tree).run_once()
        node = tree.snapshot("/svc/api")
        assert node is not None
        self.assertIn("http://x", node.config)

    def test_run_once_writes_wall_time_and_no_next(self):
        # A one-shot run has no live schedule (ADR-0044): the wall time is
        # real, the next slot honestly absent rather than a stale projection.
        tree = StatusTree()
        Engine([_FakeCheck(path="/svc/a")], tree).run_once()
        node = tree.snapshot("/svc/a")
        assert node is not None and node.run is not None
        assert node.run.wall_seconds is not None
        self.assertGreaterEqual(node.run.wall_seconds, 0.0)
        self.assertIsNone(node.run.next_run_at)

    def test_branch_child_config_with_bare_container(self):
        tree = StatusTree()
        # A branch check's container reports no config (its config_summary is
        # empty); each child carries its own slice (ADR-0013).
        result = CheckResult(StatusCode.UNDEFINED, children=(
            CheckResult(StatusCode.OK, name="disk", config="- **warn at:** 80%"),))
        Engine([_FakeCheck(path="/host", result=result)], tree).run_once()
        container = tree.snapshot("/host")
        child = tree.snapshot("/host/disk")
        assert container is not None and child is not None
        self.assertEqual(container.config, "")
        self.assertEqual(child.config, "- **warn at:** 80%")

    def test_report_rides_the_result_onto_root_and_children(self):
        # Unlike `config`, whose root value comes from the *check* object, the
        # report is an output of **this run**, so it rides the result at every
        # level — including the check's own node (ADR-0044 decision 6).
        tree = StatusTree()
        result = CheckResult(StatusCode.OK, report="- 14 repositories",
                             children=(CheckResult(StatusCode.OK, name="disk",
                                                   report="- /dev/sda1"),))
        Engine([_FakeCheck(path="/host", result=result)], tree).run_once()
        container = tree.snapshot("/host")
        child = tree.snapshot("/host/disk")
        assert container is not None and child is not None
        self.assertEqual(container.report, "- 14 repositories")
        self.assertEqual(child.report, "- /dev/sda1")

    def test_a_run_that_finds_nothing_clears_the_last_report(self):
        # The write-through property, end to end: a roster must not outlive the
        # run that found it, or the page states as current what is already gone.
        tree = StatusTree()
        check = _FakeCheck(path="/host",
                           result=CheckResult(StatusCode.OK, report="- alpha"))
        Engine([check], tree).run_once()
        check._result = CheckResult(StatusCode.OK)
        Engine([check], tree).run_once()
        node = tree.snapshot("/host")
        assert node is not None
        self.assertEqual(node.report, "")

    def test_raising_check_becomes_error(self):
        tree = StatusTree()
        check = _FakeCheck(path="/boom", raises=RuntimeError("nope"))
        Engine([check], tree).run_once()
        node = tree.snapshot("/boom")
        assert node is not None
        self.assertEqual(node.own_code, StatusCode.ERROR)
        self.assertIn("check error", node.reason[0])

    def test_exception_message_is_escaped(self):
        # the message carries whatever the failure carried — a captured line, a
        # path, an API error body — so it is folded in like any untrusted text
        # (ADR-0018) rather than rendering as Markdown on the dashboard
        tree = StatusTree()
        check = _FakeCheck(path="/boom",
                           raises=RuntimeError("bad *value* in [x](y)"))
        Engine([check], tree).run_once()
        node = tree.snapshot("/boom")
        assert node is not None
        self.assertIn(r"bad \*value\* in \[x\](y)", node.reason[0])

    def test_stacktrace_is_shown_as_a_code_block(self):
        tree = StatusTree()
        check = _FakeCheck(path="/boom", raises=RuntimeError("nope"))
        with patch.object(engine_module, "config",
                          replace(config, stacktrace=True)):
            Engine([check], tree).run_once()
        node = tree.snapshot("/boom")
        assert node is not None
        self.assertEqual(len(node.reason), 2)
        trace = node.reason[1]
        self.assertTrue(trace.startswith("```"))     # inert, verbatim (ADR-0018)
        self.assertIn("RuntimeError: nope", trace)
        self.assertIn("Traceback (most recent call last)", trace)

    def test_stacktrace_can_be_switched_off(self):
        tree = StatusTree()
        check = _FakeCheck(path="/boom", raises=RuntimeError("nope"))
        with patch.object(engine_module, "config",
                          replace(config, stacktrace=False)):
            Engine([check], tree).run_once()
        node = tree.snapshot("/boom")
        assert node is not None
        self.assertEqual(len(node.reason), 1)
        self.assertNotIn("Traceback", node.reason[0])

    def test_stacktrace_keeps_the_innermost_frames_and_the_cause(self):
        def _boom() -> None:
            try:
                raise ValueError("root cause")
            except ValueError as error:
                raise RuntimeError("wrapped") from error

        tree = StatusTree()
        check = _FakeCheck(path="/boom", raises=None)
        check.measure = _boom                          # type: ignore[method-assign]
        with patch.object(engine_module, "config",
                          replace(config, stacktrace=True)):
            Engine([check], tree).run_once()
        node = tree.snapshot("/boom")
        assert node is not None
        trace = node.reason[1]
        self.assertIn("ValueError: root cause", trace)   # the chained __cause__
        self.assertIn("RuntimeError: wrapped", trace)

    def test_tick_sweeps_expired_maintenance(self):
        tree = StatusTree()
        tree.upsert("/db", StatusCode.OK)
        tree.set_maintenance("/db", "planned",
                             expires_at=datetime.now(UTC) - timedelta(seconds=1))
        self.assertEqual(tree.effective("/db"), StatusCode.MAINTENANCE)
        engine = Engine([_FakeCheck(path="/x")], tree, poll_interval=0.02)
        engine.start()
        try:
            self.assertTrue(_wait_for(
                lambda: tree.effective("/db") == StatusCode.OK))
        finally:
            engine.stop()

    def test_check_roots_lists_full_paths(self):
        tree = StatusTree()
        engine = Engine([_FakeCheck(path="/svc/a"),
                         _FakeCheck(path="/b")], tree)
        self.assertEqual(set(engine.check_roots()), {"/svc/a", "/b"})

    def test_scheduled_run_updates_tree(self):
        tree = StatusTree()
        ran = threading.Event()
        check = _FakeCheck(path="/probe",
                           result=CheckResult(StatusCode.OK), ran=ran)
        engine = Engine([check], tree)
        engine.start()
        try:
            self.assertTrue(ran.wait(timeout=2))
            self.assertTrue(_wait_for(
                lambda: (s := tree.snapshot("/probe")) is not None
                and s.own_code == StatusCode.OK))
        finally:
            engine.stop()

    def test_slow_check_does_not_block_fast_one(self):
        tree = StatusTree()
        block = threading.Event()
        slow = _FakeCheck(path="/slow",
                          result=CheckResult(StatusCode.OK), block=block)
        fast = _FakeCheck(path="/fast", result=CheckResult(StatusCode.OK))
        engine = Engine([slow, fast], tree, max_workers=4)
        engine.start()
        try:
            # fast result must appear while slow is still blocked
            self.assertTrue(_wait_for(
                lambda: (s := tree.snapshot("/fast")) is not None
                and s.own_code == StatusCode.OK))
            self.assertIsNone(tree.snapshot("/slow"))
        finally:
            block.set()
            engine.stop()

    def test_stop_is_clean(self):
        tree = StatusTree()
        engine = Engine([_FakeCheck(path="/x")], tree)
        engine.start()
        engine.stop()
        # a second stop is a no-op
        engine.stop()

    def test_no_checks_is_fine(self):
        engine = Engine([], StatusTree())
        self.assertEqual(engine.check_count, 0)
        engine.start()
        engine.stop()

    def test_info_reports_engine_state(self):
        engine = Engine([_FakeCheck(path="/a"),
                         _FakeCheck(path="/svc/b")], StatusTree())
        info = engine.info()
        self.assertEqual(info.check_count, 2)
        self.assertIsNone(info.started_at)
        self.assertEqual({c.path for c in info.checks}, {"/a", "/svc/b"})

    def test_children_are_written_as_a_branch(self):
        tree = StatusTree()
        result = CheckResult(StatusCode.OK, ["host up"], children=(
            CheckResult(StatusCode.WARN, ["85% used"], name="disk",
                        description="Disk space"),
            CheckResult(StatusCode.OK, ["50% used"], name="memory"),
        ))
        check = _FakeCheck(path="/system/host", result=result,
                           description="Host over SSH", frequency_seconds=120)
        Engine([check], tree).run_once()
        # the worst aspect rolls up to the host node
        self.assertEqual(tree.effective("/system/host"), StatusCode.WARN)
        root = tree.snapshot("/system/host")
        assert root is not None
        self.assertEqual(root.own_code, StatusCode.OK)
        self.assertEqual(root.description, "Host over SSH")
        disk = tree.snapshot("/system/host/disk")
        assert disk is not None
        self.assertEqual(disk.own_code, StatusCode.WARN)
        self.assertEqual(disk.reason, ("85% used",))
        self.assertEqual(disk.description, "Disk space")
        # child inherits the check's frequency, so freshness applies (ADR-0005)
        self.assertEqual(disk.frequency_seconds, 120)

    def test_child_about_and_title_land_on_child_nodes(self):
        # A branch check captions the subnodes it emits (ADR-0025): each child's
        # about/title ride onto its node like description/config.
        tree = StatusTree()
        result = CheckResult(StatusCode.OK, ["host up"], children=(
            CheckResult(StatusCode.OK, name="disk",
                        about="Free space on the data volume.", title="Disk"),))
        Engine([_FakeCheck(path="/host", result=result)], tree).run_once()
        disk = tree.snapshot("/host/disk")
        assert disk is not None
        self.assertEqual(disk.about, "Free space on the data volume.")
        self.assertEqual(disk.title, "Disk")

    def test_root_result_labels_are_ignored(self):
        # The root's labels keep their startup sources (nodes.yaml / inline check),
        # so about/title on the root result are ignored like its name (ADR-0025).
        tree = StatusTree()
        result = CheckResult(StatusCode.OK, about="ignored", title="ignored")
        Engine([_FakeCheck(path="/host", result=result)], tree).run_once()
        root = tree.snapshot("/host")
        assert root is not None
        self.assertEqual((root.about, root.title), ("", ""))

    def test_nodes_yaml_label_beats_check_provided_child(self):
        # A nodes.yaml value is seeded (set_about) before the first tick and wins
        # over the check-provided child label; resolved per field.
        tree = StatusTree()
        tree.set_about("/host/disk", "Declared in nodes.yaml.")
        result = CheckResult(StatusCode.OK, children=(
            CheckResult(StatusCode.OK, name="disk",
                        about="From the check.", title="Disk"),))
        Engine([_FakeCheck(path="/host", result=result)], tree).run_once()
        disk = tree.snapshot("/host/disk")
        assert disk is not None
        self.assertEqual(disk.about, "Declared in nodes.yaml.")   # yaml wins
        self.assertEqual(disk.title, "Disk")                      # yaml left it empty

    def _long_about_notes(self, engine, runs=1):
        """The startup record's notes of a long about across ``runs`` runs, and
        every call that made one."""
        with patch.object(self_report.startup, "note",
                          wraps=self_report.startup.note) as noted:
            for _ in range(runs):
                engine.run_once()
        calls = [call for call in noted.call_args_list
                 if call.args[0].startswith("nodes-long-about")]
        lines = [line for line in self_report.startup.lines()
                 if line.slug.startswith("nodes-long-about")]
        return calls, lines

    def test_a_childs_about_past_400_is_noted_when_it_first_fills_its_node(self):
        # A run hands a child its about (ADR-0025), and one past about 400
        # characters is named as the startup pass names a declared one (backlog
        # #91 §3.5): once, when it first fills its node, which a later run's never
        # does again.
        self_report.startup.forget()
        self.addCleanup(self_report.startup.forget)
        result = CheckResult(StatusCode.OK, children=(
            CheckResult(StatusCode.OK, name="disk", about="d" * 450),))
        engine = Engine([_FakeCheck(path="/host", result=result)], StatusTree())
        calls, lines = self._long_about_notes(engine, runs=3)
        self.assertEqual(len(calls), 1)
        (line,) = lines
        self.assertEqual(line.slug, "nodes-long-about-host-disk")
        self.assertIn("'/host/disk'", line.text)
        self.assertIn("450 characters", line.text)

    def test_a_long_about_that_fills_nothing_is_not_noted(self):
        # nodes.yaml's about, seeded before the first tick, keeps the field: the
        # run's long one never reaches the band, and nothing is said of it
        self_report.startup.forget()
        self.addCleanup(self_report.startup.forget)
        tree = StatusTree()
        tree.set_about("/host/disk", "Declared in nodes.yaml.")
        result = CheckResult(StatusCode.OK, children=(
            CheckResult(StatusCode.OK, name="disk", about="d" * 450),))
        calls, lines = self._long_about_notes(
            Engine([_FakeCheck(path="/host", result=result)], tree))
        self.assertEqual((calls, lines), ([], []))

    def _long_description_notes(self, engine, runs=1):
        """The startup record's notes of a long description across ``runs`` runs,
        and every call that made one."""
        with patch.object(self_report.startup, "note",
                          wraps=self_report.startup.note) as noted:
            for _ in range(runs):
                engine.run_once()
        calls = [call for call in noted.call_args_list
                 if call.args[0].startswith("nodes-long-description")]
        lines = [line for line in self_report.startup.lines()
                 if line.slug.startswith("nodes-long-description")]
        return calls, lines

    def test_a_childs_description_past_160_is_noted_once(self):
        # A run hands a child its description on every run (write-through), and
        # one past about 160 characters is named as the startup pass names a
        # check's own (ADR-0133 decision 2): once, however many runs hand it over.
        self_report.startup.forget()
        self.addCleanup(self_report.startup.forget)
        result = CheckResult(StatusCode.OK, children=(
            CheckResult(StatusCode.OK, name="disk", description="d" * 170),))
        engine = Engine([_FakeCheck(path="/host", result=result)], StatusTree())
        calls, lines = self._long_description_notes(engine, runs=3)
        self.assertEqual(len(calls), 1)
        (line,) = lines
        self.assertEqual(line.slug, "nodes-long-description-host-disk")
        self.assertIn("'/host/disk'", line.text)
        self.assertIn("170 characters", line.text)

    def test_a_checks_own_description_is_the_startup_passs(self):
        # the root's description is the check's, configuration the startup pass
        # names; the engine names only what a run hands a node beneath it
        self_report.startup.forget()
        self.addCleanup(self_report.startup.forget)
        engine = Engine([_FakeCheck(path="/host", description="d" * 170)],
                        StatusTree())
        calls, lines = self._long_description_notes(engine)
        self.assertEqual((calls, lines), ([], []))

    def test_a_childs_description_of_160_is_not_noted(self):
        self_report.startup.forget()
        self.addCleanup(self_report.startup.forget)
        result = CheckResult(StatusCode.OK, children=(
            CheckResult(StatusCode.OK, name="disk", description="d" * 160),))
        calls, lines = self._long_description_notes(
            Engine([_FakeCheck(path="/host", result=result)], StatusTree()))
        self.assertEqual((calls, lines), ([], []))

    def test_a_childs_about_of_400_is_not_noted(self):
        self_report.startup.forget()
        self.addCleanup(self_report.startup.forget)
        result = CheckResult(StatusCode.OK, children=(
            CheckResult(StatusCode.OK, name="disk", about="d" * 400),))
        calls, lines = self._long_about_notes(
            Engine([_FakeCheck(path="/host", result=result)], StatusTree()))
        self.assertEqual((calls, lines), ([], []))

    def test_child_order_ranks_the_subnodes_a_branch_check_emits(self):
        # ADR-0055's motivating case, end to end through the engine.
        tree = StatusTree()
        bands = ("critical", "high", "informational", "low", "medium")
        result = CheckResult(StatusCode.OK, children=tuple(
            CheckResult(StatusCode.OK, name=band,
                        order=1 if band == "informational" else 0)
            for band in bands))
        Engine([_FakeCheck(path="/wiz", result=result)], tree).run_once()
        snap = tree.snapshot("/wiz")
        assert snap is not None
        self.assertEqual([child.name for child in snap.children],
                         ["critical", "high", "low", "medium", "informational"])

    def test_root_result_order_is_honoured_unlike_the_root_labels(self):
        # Deliberately unlike about/title (ADR-0025): a rank is not identity, and
        # the root has no inline `order:` source the way it has for its labels, so
        # ignoring it here would leave a leaf check unable to rank its own node.
        tree = StatusTree()
        Engine([_FakeCheck(path="/svc/b",
                           result=CheckResult(StatusCode.OK, order=-1)),
                _FakeCheck(path="/svc/a", result=CheckResult(StatusCode.OK))],
               tree).run_once()
        snap = tree.snapshot("/svc")
        assert snap is not None
        self.assertEqual([child.name for child in snap.children], ["b", "a"])

    def test_a_root_rank_reaches_past_nodes_another_check_owns(self):
        # The accepted consequence of reading `order` on the root (ADR-0055): ranks
        # compare across the whole sibling set, so one check's rank moves its card
        # relative to cards that belong to other checks. Named here so a change in
        # this behavior is a decision rather than a surprise.
        tree = StatusTree()
        Engine([_FakeCheck(path="/wall/zzz-plugin",
                           result=CheckResult(StatusCode.OK, order=-1)),
                _FakeCheck(path="/wall/aaa", result=CheckResult(StatusCode.OK)),
                _FakeCheck(path="/wall/bbb", result=CheckResult(StatusCode.OK))],
               tree).run_once()
        self.assertEqual([c.name for c in tree.snapshot("/wall").children],
                         ["zzz-plugin", "aaa", "bbb"])

    def test_a_deployment_answers_a_root_rank_from_its_own_config(self):
        # …and the answer is the ordinary one: state the order yourself. The seed
        # runs at startup, so it is already in place when the first tick lands.
        tree = StatusTree()
        for path, rank in (("/wall/zzz-plugin", 0), ("/wall/aaa", 0),
                           ("/wall/bbb", 0)):
            tree.set_order(path, rank)
        Engine([_FakeCheck(path="/wall/zzz-plugin",
                           result=CheckResult(StatusCode.OK, order=-1)),
                _FakeCheck(path="/wall/aaa", result=CheckResult(StatusCode.OK)),
                _FakeCheck(path="/wall/bbb", result=CheckResult(StatusCode.OK))],
               tree).run_once()
        self.assertEqual([c.name for c in tree.snapshot("/wall").children],
                         ["aaa", "bbb", "zzz-plugin"])

    def test_a_result_order_of_zero_leaves_nodes_yaml_free_to_speak(self):
        # `0` is what declaring nothing means, so it must not count as the check
        # having spoken — otherwise every unranked node would shut out nodes.yaml.
        tree = StatusTree()
        tree.set_order("/host/disk", 2)
        result = CheckResult(StatusCode.OK, children=(
            CheckResult(StatusCode.OK, name="disk", order=0),
            CheckResult(StatusCode.OK, name="memory", order=7),))
        Engine([_FakeCheck(path="/host", result=result)], tree).run_once()
        self.assertEqual(tree.snapshot("/host/disk").order, 2)     # yaml wins
        self.assertEqual(tree.snapshot("/host/memory").order, 7)   # check fills

    def test_child_show_when_quiet_lands_on_child_nodes(self):
        # A branch check declares it per aspect (ADR-0063) — the inventory-shaped
        # one says so, its siblings say nothing.
        tree = StatusTree()
        result = CheckResult(StatusCode.OK, children=(
            CheckResult(StatusCode.OK, name="ec2", show_when_quiet=True),
            CheckResult(StatusCode.OK, name="batch"),))
        Engine([_FakeCheck(path="/aws", result=result)], tree).run_once()
        self.assertIs(tree.snapshot("/aws/ec2").show_when_quiet, True)
        self.assertIsNone(tree.snapshot("/aws/batch").show_when_quiet)

    def test_a_child_may_state_false_and_it_reaches_the_node(self):
        # Unlike `order`'s zero, a check's `False` is a statement rather than a
        # silence — nothing coerces it away on the trip through the engine.
        tree = StatusTree()
        result = CheckResult(StatusCode.OK, children=(
            CheckResult(StatusCode.OK, name="ec2", show_when_quiet=False),))
        Engine([_FakeCheck(path="/aws", result=result)], tree).run_once()
        self.assertIs(tree.snapshot("/aws/ec2").show_when_quiet, False)

    def test_root_result_show_when_quiet_is_ignored_like_the_root_labels(self):
        # It rides with about/title, not with order: the root *does* have an inline
        # source of its own — the check's `show_when_quiet:` key — so a result
        # overruling it would put the check's code ahead of the deployment's file.
        tree = StatusTree()
        result = CheckResult(StatusCode.OK, show_when_quiet=True)
        Engine([_FakeCheck(path="/aws", result=result)], tree).run_once()
        self.assertIsNone(tree.snapshot("/aws").show_when_quiet)

    def test_nodes_yaml_show_when_quiet_beats_a_check_provided_child(self):
        # …and beats the deployment's `subnodes:` declaration too — the seed is
        # in place before the first tick, and the engine's write fills empty only.
        tree = StatusTree()
        tree.set_show_when_quiet("/aws/ec2", False)
        result = CheckResult(StatusCode.OK, children=(
            CheckResult(StatusCode.OK, name="ec2", show_when_quiet=True),
            CheckResult(StatusCode.OK, name="batch", show_when_quiet=True),))
        Engine([_FakeCheck(path="/aws", result=result,
                           subnode_show_when_quiet={"ec2": True})],
               tree).run_once()
        self.assertIs(tree.snapshot("/aws/ec2").show_when_quiet, False)  # yaml wins
        self.assertIs(tree.snapshot("/aws/batch").show_when_quiet, True)  # check fills

    def test_a_deployments_subnodes_block_needs_nothing_from_the_type(self):
        # The point of the library reading the block (ADR-0063): the check type
        # here stamps nothing and has never heard of the key — the map arrives
        # through the common-field kwargs every type already forwards — and the
        # deployment's declaration still lands on the child node.
        tree = StatusTree()
        result = CheckResult(StatusCode.OK, children=(
            CheckResult(StatusCode.OK, name="ec2"),
            CheckResult(StatusCode.OK, name="batch"),))
        Engine([_FakeCheck(path="/aws", result=result,
                           subnode_show_when_quiet={"ec2": True})],
               tree).run_once()
        self.assertIs(tree.snapshot("/aws/ec2").show_when_quiet, True)
        self.assertIsNone(tree.snapshot("/aws/batch").show_when_quiet)

    def test_the_deployments_block_beats_the_types_shipped_default(self):
        # Deployment file over check code — the same rule that root-ignores the
        # result: a shipped `True` yields to a configured `False`, and a name
        # the block does not mention keeps the shipped default.
        tree = StatusTree()
        result = CheckResult(StatusCode.OK, children=(
            CheckResult(StatusCode.OK, name="ec2", show_when_quiet=True),
            CheckResult(StatusCode.OK, name="lambda", show_when_quiet=True),))
        Engine([_FakeCheck(path="/aws", result=result,
                           subnode_show_when_quiet={"ec2": False})],
               tree).run_once()
        self.assertIs(tree.snapshot("/aws/ec2").show_when_quiet, False)
        self.assertIs(tree.snapshot("/aws/lambda").show_when_quiet, True)

    def test_the_block_reaches_a_grandchild_by_its_name(self):
        # Keyed by subnode *name*, at any depth — one `disk:` covers every
        # host's `disk` leaf, which is the per-account copy-paste this closes.
        tree = StatusTree()
        result = CheckResult(StatusCode.OK, children=(
            CheckResult(StatusCode.OK, name="host-a", children=(
                CheckResult(StatusCode.OK, name="disk"),)),
            CheckResult(StatusCode.OK, name="host-b", children=(
                CheckResult(StatusCode.OK, name="disk"),)),))
        Engine([_FakeCheck(path="/fleet", result=result,
                           subnode_show_when_quiet={"disk": True})],
               tree).run_once()
        self.assertIs(tree.snapshot("/fleet/host-a/disk").show_when_quiet, True)
        self.assertIs(tree.snapshot("/fleet/host-b/disk").show_when_quiet, True)

    def test_a_resolved_label_lands_on_the_child_node(self):
        # The labels ride the flag's mechanism under ADR-0025: keyed by subnode
        # name, applied by the engine, stamped by
        # nobody. The check here hands over no label at all.
        tree = StatusTree()
        result = CheckResult(StatusCode.OK, children=(
            CheckResult(StatusCode.OK, name="disk"),
            CheckResult(StatusCode.OK, name="memory"),))
        Engine([_FakeCheck(path="/host", result=result,
                           subnode_labels={"disk": {"title": "Disk",
                                                    "about": "The volumes."}})],
               tree).run_once()
        self.assertEqual(tree.snapshot("/host/disk").title, "Disk")
        self.assertEqual(tree.snapshot("/host/disk").about, "The volumes.")
        self.assertEqual(tree.snapshot("/host/memory").about, "")

    def test_the_resolved_label_beats_the_one_the_result_carries(self):
        # Deployment file and type declaration have both already been folded into
        # the map; what is left on the result is the older channel, so the map wins.
        tree = StatusTree()
        result = CheckResult(StatusCode.OK, children=(
            CheckResult(StatusCode.OK, name="disk", about="stamped"),))
        Engine([_FakeCheck(path="/host", result=result,
                           subnode_labels={"disk": {"about": "resolved"}})],
               tree).run_once()
        self.assertEqual(tree.snapshot("/host/disk").about, "resolved")

    def test_a_stamped_label_survives_where_the_map_is_silent(self):
        # Per field, and per name. A child nothing declared or configured — the
        # dynamically named one, a volume this run discovered — keeps the label
        # its check gave it, which is the whole reason the field still exists.
        tree = StatusTree()
        result = CheckResult(StatusCode.OK, children=(
            CheckResult(StatusCode.OK, name="disk", about="stamped about",
                        title="stamped title"),
            CheckResult(StatusCode.OK, name="sda1", about="a volume"),))
        Engine([_FakeCheck(path="/host", result=result,
                           subnode_labels={"disk": {"title": "Disk"}})],
               tree).run_once()
        disk = tree.snapshot("/host/disk")
        self.assertEqual(disk.title, "Disk")             # resolved
        self.assertEqual(disk.about, "stamped about")    # the field it left alone
        self.assertEqual(tree.snapshot("/host/sda1").about, "a volume")

    def test_a_resolved_label_reaches_a_grandchild_by_its_name(self):
        # Keyed by subnode *name*, at any depth — one `disk:` entry labels every
        # host's disk leaf, which is the per-node copy-paste ADR-0025 closes.
        tree = StatusTree()
        result = CheckResult(StatusCode.OK, children=(
            CheckResult(StatusCode.OK, name="host-a", children=(
                CheckResult(StatusCode.OK, name="disk"),)),
            CheckResult(StatusCode.OK, name="host-b", children=(
                CheckResult(StatusCode.OK, name="disk"),)),))
        Engine([_FakeCheck(path="/fleet", result=result,
                           subnode_labels={"disk": {"about": "Volumes."}})],
               tree).run_once()
        self.assertEqual(tree.snapshot("/fleet/host-a/disk").about, "Volumes.")
        self.assertEqual(tree.snapshot("/fleet/host-b/disk").about, "Volumes.")

    def test_nodes_yaml_beats_a_resolved_label(self):
        # Seeded before the first tick, and the engine's write fills empty only —
        # so the declaration in the deployment's *node* file still has the last
        # word, per field.
        tree = StatusTree()
        tree.set_about("/host/disk", "declared in nodes.yaml")
        result = CheckResult(StatusCode.OK, children=(
            CheckResult(StatusCode.OK, name="disk"),))
        Engine([_FakeCheck(path="/host", result=result,
                           subnode_labels={"disk": {"title": "Disk",
                                                    "about": "resolved"}})],
               tree).run_once()
        self.assertEqual(tree.snapshot("/host/disk").about,
                         "declared in nodes.yaml")
        self.assertEqual(tree.snapshot("/host/disk").title, "Disk")   # still fills

    def test_a_resolved_label_does_not_reach_the_root(self):
        # The root's labels keep their startup sources (nodes.yaml / the inline
        # check), so an entry carrying the root's name is a claim about a
        # *subnode* of that name and leaves the root alone.
        tree = StatusTree()
        Engine([_FakeCheck(path="/host", result=CheckResult(StatusCode.OK),
                           subnode_labels={"host": {"about": "not mine"}})],
               tree).run_once()
        self.assertEqual(tree.snapshot("/host").about, "")

    def test_a_declared_flag_lands_on_the_child(self):
        # The type's half of the block (ADR-0063 §2): a roster aspect declares the
        # flag beside its label and every installation inherits it, with no
        # `nodes.yaml` entry and no configuration anywhere. The engine is unchanged
        # — `subnode_show_when_quiet` is the merged map, and it already read that.
        tree = StatusTree()
        result = CheckResult(StatusCode.OK, children=(
            CheckResult(StatusCode.OK, name="ec2"),
            CheckResult(StatusCode.OK, name="batch"),))
        Engine([_FakeCheck(path="/aws", result=result,
                           subnode_defaults={"ec2": {"show_when_quiet": True}})],
               tree).run_once()
        self.assertIs(tree.snapshot("/aws/ec2").show_when_quiet, True)
        self.assertIsNone(tree.snapshot("/aws/batch").show_when_quiet)

    def test_a_declared_flag_reaches_a_grandchild_by_its_name(self):
        # Declared once in the package, applied at any depth — which is the whole
        # of what it replaces: one entry per aspect per account in a nodes.yaml.
        tree = StatusTree()
        result = CheckResult(StatusCode.OK, children=(
            CheckResult(StatusCode.OK, name="live", children=(
                CheckResult(StatusCode.OK, name="ec2"),)),
            CheckResult(StatusCode.OK, name="backup", children=(
                CheckResult(StatusCode.OK, name="ec2"),)),))
        Engine([_FakeCheck(path="/aws", result=result,
                           subnode_defaults={"ec2": {"show_when_quiet": True}})],
               tree).run_once()
        self.assertIs(tree.snapshot("/aws/live/ec2").show_when_quiet, True)
        self.assertIs(tree.snapshot("/aws/backup/ec2").show_when_quiet, True)

    def test_a_declaration_beats_a_stamped_value(self):
        # A declaration — the deployment's file first, the type's map beneath — is
        # what a name *is*; a stamped value is what one run said about a child it
        # had just discovered. For a declared name the declaration answers.
        tree = StatusTree()
        result = CheckResult(StatusCode.OK, children=(
            CheckResult(StatusCode.OK, name="ec2", show_when_quiet=True),))
        Engine([_FakeCheck(path="/aws", result=result,
                           subnode_defaults={"ec2": {"show_when_quiet": False}})],
               tree).run_once()
        self.assertIs(tree.snapshot("/aws/ec2").show_when_quiet, False)

    def test_a_stamped_flag_survives_for_a_name_nothing_declared(self):
        # The dynamic-child channel, kept: a run that names its own child is the
        # one case no declaration could have anticipated.
        tree = StatusTree()
        result = CheckResult(StatusCode.OK, children=(
            CheckResult(StatusCode.OK, name="ec2"),
            CheckResult(StatusCode.OK, name="i-042", show_when_quiet=True),))
        Engine([_FakeCheck(path="/aws", result=result,
                           subnode_defaults={"ec2": {"about": "The instances."}})],
               tree).run_once()
        self.assertIs(tree.snapshot("/aws/i-042").show_when_quiet, True)
        self.assertIsNone(tree.snapshot("/aws/ec2").show_when_quiet)

    def test_nodes_yaml_beats_a_declared_flag_too(self):
        # The top of the lattice does not move: seeded before the first tick, and
        # the engine's write fills an empty field only.
        tree = StatusTree()
        tree.set_show_when_quiet("/aws/ec2", False)
        result = CheckResult(StatusCode.OK, children=(
            CheckResult(StatusCode.OK, name="ec2"),))
        Engine([_FakeCheck(path="/aws", result=result,
                           subnode_defaults={"ec2": {"show_when_quiet": True}})],
               tree).run_once()
        self.assertIs(tree.snapshot("/aws/ec2").show_when_quiet, False)

    def test_the_blocks_root_named_entry_does_not_reach_the_root(self):
        # The root's own source is the inline `show_when_quiet:` key; a
        # `subnodes:` entry that happens to carry the root's name is a claim
        # about a *subnode* of that name, so the root stays untouched.
        tree = StatusTree()
        Engine([_FakeCheck(path="/aws", result=CheckResult(StatusCode.OK),
                           subnode_show_when_quiet={"aws": True})],
               tree).run_once()
        self.assertIsNone(tree.snapshot("/aws").show_when_quiet)

    # The claim under `children:` (ADR-0128): the same addresses the first look's
    # keys ride, so a type or a file says it once for a level a run names, where
    # each run had to stamp it.

    def test_the_files_children_claim_every_child_of_the_checks_node(self):
        tree = StatusTree()
        result = CheckResult(StatusCode.OK, children=(
            CheckResult(StatusCode.OK, name="ec2"),
            CheckResult(StatusCode.OK, name="i-042", dynamic=True),))
        Engine([_FakeCheck(path="/aws", result=result,
                           look=Stated(children=Stated(show_when_quiet=True)))],
               tree).run_once()
        self.assertIs(tree.snapshot("/aws/ec2").show_when_quiet, True)
        self.assertIs(tree.snapshot("/aws/i-042").show_when_quiet, True)
        self.assertIsNone(tree.snapshot("/aws").show_when_quiet)

    def test_a_names_children_claim_the_children_of_that_name(self):
        tree = StatusTree()
        result = CheckResult(StatusCode.OK, children=(
            CheckResult(StatusCode.OK, name="queues", children=(
                CheckResult(StatusCode.OK, name="q-1", dynamic=True),
                CheckResult(StatusCode.OK, name="q-2", dynamic=True),)),
            CheckResult(StatusCode.OK, name="other", children=(
                CheckResult(StatusCode.OK, name="q-3", dynamic=True),)),))
        Engine([_FakeCheck(path="/aws", result=result, subnode_looks={
            "queues": Stated(children=Stated(show_when_quiet=True))})],
               tree).run_once()
        self.assertIs(tree.snapshot("/aws/queues/q-1").show_when_quiet, True)
        self.assertIs(tree.snapshot("/aws/queues/q-2").show_when_quiet, True)
        self.assertIsNone(tree.snapshot("/aws/other/q-3").show_when_quiet)
        self.assertIsNone(tree.snapshot("/aws/queues").show_when_quiet)

    def test_a_childs_own_name_first_and_the_files_children_before_the_type(self):
        tree = StatusTree()
        result = CheckResult(StatusCode.OK, children=(
            CheckResult(StatusCode.OK, name="ec2"),
            CheckResult(StatusCode.OK, name="batch"),))
        Engine([_FakeCheck(path="/aws", result=result,
                           look=Stated(children=Stated(show_when_quiet=False)),
                           subnode_show_when_quiet={"ec2": True},
                           subnode_defaults={"batch": {"show_when_quiet": True}})],
               tree).run_once()
        self.assertIs(tree.snapshot("/aws/ec2").show_when_quiet, True)
        self.assertIs(tree.snapshot("/aws/batch").show_when_quiet, False)

    def test_a_parents_children_claim_beats_what_a_run_stamps(self):
        tree = StatusTree()
        result = CheckResult(StatusCode.OK, children=(
            CheckResult(StatusCode.OK, name="i-042", dynamic=True,
                        show_when_quiet=True),))
        Engine([_FakeCheck(path="/aws", result=result,
                           look=Stated(children=Stated(show_when_quiet=False)))],
               tree).run_once()
        self.assertIs(tree.snapshot("/aws/i-042").show_when_quiet, False)

    def test_the_types_node_defaults_claim_the_children_of_its_own_node(self):
        tree = StatusTree()
        result = CheckResult(StatusCode.OK, children=(
            CheckResult(StatusCode.OK, name="i-042", dynamic=True),))
        Engine([_FakeCheck(path="/aws", result=result,
                           node_defaults={"children": {"show_when_quiet": True}})],
               tree).run_once()
        self.assertIs(tree.snapshot("/aws/i-042").show_when_quiet, True)

    def test_nodes_yaml_childrens_claim_beats_the_file_and_its_own_path_all(self):
        tree = StatusTree()
        tree.set_show_when_quiet("/aws/lambda", True)
        result = CheckResult(StatusCode.OK, children=(
            CheckResult(StatusCode.OK, name="ec2"),
            CheckResult(StatusCode.OK, name="lambda"),))
        engine = Engine([_FakeCheck(path="/aws", result=result,
                                    subnode_show_when_quiet={"ec2": True,
                                                             "lambda": False})],
                        tree)
        engine.declare_nodes({"/aws": NodeMeta(
            look=Stated(children=Stated(show_when_quiet=False)))})
        engine.run_once()
        self.assertIs(tree.snapshot("/aws/ec2").show_when_quiet, False)
        self.assertIs(tree.snapshot("/aws/lambda").show_when_quiet, True)  # seeded

    def test_a_named_nodes_name_entry_does_not_reach_its_children(self):
        tree = StatusTree()
        result = CheckResult(StatusCode.OK, children=(
            CheckResult(StatusCode.OK, name="batch", dynamic=True, children=(
                CheckResult(StatusCode.OK, name="q"),)),))
        Engine([_FakeCheck(path="/aws", result=result, subnode_looks={
            "batch": Stated(children=Stated(show_when_quiet=True))})],
               tree).run_once()
        self.assertIsNone(tree.snapshot("/aws/batch/q").show_when_quiet)

    def test_the_tree_keeps_which_nodes_a_run_named_while_it_names_them(self):
        tree = StatusTree()
        named = CheckResult(StatusCode.OK, children_complete=True, children=(
            CheckResult(StatusCode.OK, name="ec2"),
            CheckResult(StatusCode.OK, name="i-042", dynamic=True, children=(
                CheckResult(StatusCode.OK, name="disk"),)),))
        check = _FakeCheck(path="/aws", result=named)
        engine = Engine([check], tree)
        engine.run_once()
        self.assertTrue(tree.named_by_run("/aws/i-042"))
        self.assertFalse(tree.named_by_run("/aws/ec2"))
        self.assertFalse(tree.named_by_run("/aws/i-042/disk"))
        self.assertFalse(tree.named_by_run("/aws"))
        # a later run that names it no more, and one that no longer returns it
        check._result = CheckResult(StatusCode.OK, children_complete=True, children=(
            CheckResult(StatusCode.OK, name="i-042"),))
        engine.run_once()
        self.assertFalse(tree.named_by_run("/aws/i-042"))
        check._result = named
        engine.run_once()
        self.assertTrue(tree.named_by_run("/aws/i-042"))
        check._result = CheckResult(StatusCode.OK, children_complete=True)
        engine.run_once()
        self.assertFalse(tree.named_by_run("/aws/i-042"))

    def test_a_root_that_says_a_run_named_it_is_not_kept_as_named(self):
        # a root ignores the word, as it ignores what a result says of its name
        tree = StatusTree()
        Engine([_FakeCheck(path="/aws", result=CheckResult(StatusCode.OK,
                                                           dynamic=True))],
               tree).run_once()
        self.assertFalse(tree.named_by_run("/aws"))

    def test_elapsed_none_before_first_run(self):
        engine = Engine([_FakeCheck(path="/a")], StatusTree())
        self.assertIsNone(engine.info().checks[0].elapsed_seconds)

    def test_run_records_elapsed(self):
        engine = Engine([_FakeCheck(path="/a")], StatusTree())
        engine.run_once()
        elapsed = engine.info().checks[0].elapsed_seconds
        assert elapsed is not None
        self.assertGreaterEqual(elapsed, 0.0)

    def test_raising_run_records_elapsed(self):
        # A run that blows up (or times out) still shows how long it took.
        engine = Engine([_FakeCheck(path="/boom", raises=RuntimeError("nope"))],
                        StatusTree())
        engine.run_once()
        self.assertIsNotNone(engine.info().checks[0].elapsed_seconds)

    def test_pinned_check_records_no_elapsed(self):
        # A secret-pinned check never runs (ADR-0023), so it has no runtime.
        check = _FakeCheck(path="/pinned")
        check.secret_errors.append("db-password: store unreachable")
        engine = Engine([check], StatusTree())
        engine.run_once()
        info = engine.info().checks[0]
        self.assertIsNone(info.elapsed_seconds)
        self.assertIsNone(info.last_run_at)

    def test_run_records_last_run_start(self):
        engine = Engine([_FakeCheck(path="/a")], StatusTree())
        engine.run_once()
        info = engine.info().checks[0]
        assert info.last_run_at is not None
        self.assertIs(info.last_run_at.tzinfo, UTC)   # an instant
        # the finished run is no longer reported as in flight
        self.assertIsNone(info.running_since)
        self.assertIsNone(info.running_seconds)

    def test_next_run_at_is_a_timestamp(self):
        engine = Engine([_FakeCheck(path="/a")], StatusTree())
        info = engine.info().checks[0]
        self.assertIs(info.next_run_at.tzinfo, UTC)   # an instant

    def test_info_carries_type_name(self):
        class _TypedCheck(_FakeCheck):
            type_name = "fake"
        engine = Engine([_TypedCheck(path="/t")], StatusTree())
        self.assertEqual(engine.info().checks[0].type_name, "fake")

    def test_running_check_reports_its_start(self):
        tree = StatusTree()
        block = threading.Event()
        slow = _FakeCheck(path="/slow", block=block)
        engine = Engine([slow], tree)
        engine.start()
        try:
            self.assertTrue(_wait_for(
                lambda: engine.info().checks[0].running_since is not None))
            info = engine.info().checks[0]
            self.assertTrue(info.running)
            self.assertIsNotNone(info.running_seconds)
            self.assertIsNone(info.last_run_at)       # first run still in flight
        finally:
            block.set()
            engine.stop()

    def test_stagger_is_stable_and_capped(self):
        from little_sister.engine import STAGGER_WINDOW_SECONDS, _stagger
        check = _FakeCheck(path="/svc/a", frequency_seconds=120)
        first = _stagger(check)
        self.assertEqual(first, _stagger(check))       # deterministic
        self.assertGreaterEqual(first, 0.0)
        self.assertLess(first, STAGGER_WINDOW_SECONDS)
        fast = _FakeCheck(path="/svc/a", frequency_seconds=30)
        self.assertLess(_stagger(fast), 30.0)          # capped by the period

    def test_same_root_different_type_get_distinct_phases(self):
        # two checks may share a root node (host-metrics + macos-memory on one
        # host) — the pair hitting one host must separate most of all
        from little_sister.engine import _stagger

        class _Metrics(_FakeCheck):
            type_name = "host-metrics"

        class _Memory(_FakeCheck):
            type_name = "macos-memory"

        self.assertNotEqual(
            _stagger(_Metrics(path="/host", frequency_seconds=120)),
            _stagger(_Memory(path="/host", frequency_seconds=120)))

    def test_start_lockstep_dissolves_after_first_rearm(self):
        # both checks run in the immediate first sweep, but re-arm onto
        # distinct personal phases (frequency + stagger, once)
        from little_sister.engine import _stagger
        a = _FakeCheck(path="/a", frequency_seconds=120)
        b = _FakeCheck(path="/b", frequency_seconds=120)
        expected = abs(_stagger(a) - _stagger(b))
        self.assertGreater(expected, 0.5)   # these paths do differ clearly
        engine = Engine([a, b], StatusTree())
        engine.start()
        try:
            self.assertTrue(_wait_for(
                lambda: all(c.last_run_at for c in engine.info().checks)))
            nexts = {c.path: c.next_in_seconds for c in engine.info().checks}
            self.assertAlmostEqual(
                abs(nexts["/a"] - nexts["/b"]), expected, delta=1.0)
        finally:
            engine.stop()

    def test_engine_heartbeats_self_node(self):
        from little_sister.engine import HEARTBEAT_PATH
        tree = StatusTree()
        engine = Engine([_FakeCheck(path="/x")], tree)
        engine.start()
        try:
            self.assertTrue(_wait_for(
                lambda: tree.snapshot(HEARTBEAT_PATH) is not None))
        finally:
            engine.stop()

    def test_the_instance_branch_states_a_tolerance_and_carries_no_period(self):
        # ADR-0081: nothing on this branch is checked on an interval
        # — the lines are recorded state read on the tick (ADR-0072) and readiness
        # measured its trust store once, at startup — so the branch carries no
        # `frequency` for a surface to call a check's period. What it carries is
        # the tolerance the tick implies, stated, which is the freshness promise
        # the stamp was always really making.
        from little_sister.engine import HEARTBEAT_PATH
        tree = StatusTree()
        engine = Engine([_FakeCheck(path="/x")], tree, poll_interval=1.0)
        engine.start()
        try:
            self.assertTrue(_wait_for(
                lambda: tree.snapshot(f"{HEARTBEAT_PATH}/engine") is not None))
        finally:
            engine.stop()
        for path in (HEARTBEAT_PATH, f"{HEARTBEAT_PATH}/engine"):
            snap = tree.snapshot(path)
            assert snap is not None, path
            self.assertIsNone(snap.frequency_seconds, path)
            self.assertEqual(snap.stale_after_seconds, 31.0, path)

    def test_a_stopped_scheduler_still_goes_stale_in_the_same_window(self):
        # The detection window the stamp bought is exactly what may not be lost:
        # `frequency + max(frequency, 30s)` at a 1s beat is 31s, and it is 31s
        # whether the number arrives as a period or as a stated tolerance
        # (ADR-0005 decision 3 stands).
        from little_sister.engine import HEARTBEAT_PATH
        tree = StatusTree()
        engine = Engine([_FakeCheck(path="/x")], tree, poll_interval=1.0)
        engine.start()
        try:
            self.assertTrue(_wait_for(
                lambda: tree.snapshot(HEARTBEAT_PATH) is not None))
        finally:
            engine.stop()
        beating = tree.snapshot(HEARTBEAT_PATH,
                                now=datetime.now(UTC) + timedelta(seconds=30))
        assert beating is not None
        self.assertFalse(beating.stale)
        dead = tree.snapshot(HEARTBEAT_PATH,
                             now=datetime.now(UTC) + timedelta(seconds=32))
        assert dead is not None
        self.assertTrue(dead.stale)
        self.assertEqual(dead.code, StatusCode.WARN)

    def test_heartbeat_carries_a_default_about(self):
        # The dashboard strip's hover card explains the self-monitor out of
        # the box (architecture.md §6); a later seed (the startup nodes.yaml
        # pass) overrides.
        from little_sister.engine import HEARTBEAT_ABOUT, HEARTBEAT_PATH
        tree = StatusTree()
        Engine([_FakeCheck(path="/x")], tree)
        snap = tree.snapshot(HEARTBEAT_PATH)
        self.assertIsNotNone(snap)
        self.assertEqual(snap.about, HEARTBEAT_ABOUT)
        self.assertIn("scheduler", snap.about)
        tree.set_about(HEARTBEAT_PATH, "custom note")
        self.assertEqual(tree.snapshot(HEARTBEAT_PATH).about, "custom note")

    def test_construction_registers_each_check_as_a_mount(self):
        # ADR-0027: the engine knows where its checks write, so the containers above
        # a sole check can publish its run time. Registration happens at
        # construction — before the first tick — and creates no nodes (only the
        # heartbeat's `about` seed does, and that is not a mount).
        from little_sister.engine import HEARTBEAT_PATH
        tree = StatusTree()
        Engine([_FakeCheck(path="/system/node_a/host_metrics")], tree)
        root = tree.snapshot()
        assert root is not None
        self.assertEqual([child.path for child in root.children], [HEARTBEAT_PATH])
        self.assertIsNone(tree.snapshot("/system"))   # registration is not a node
        self.assertIsNone(root.timestamp)             # nor an observation

    def test_a_sole_check_stamps_the_root_after_one_sweep(self):
        # End to end: one check, one run — the mount's time climbs to the root.
        tree = StatusTree()
        Engine([_FakeCheck(path="/system/node_a/host_metrics")], tree).run_once()
        mount = tree.snapshot("/system/node_a/host_metrics")
        root = tree.snapshot()
        assert mount is not None and root is not None
        self.assertIsNotNone(mount.timestamp)
        self.assertEqual(root.timestamp, mount.timestamp)

    def test_two_checks_leave_the_root_without_a_timestamp(self):
        tree = StatusTree()
        Engine([_FakeCheck(path="/system/node_a/host_metrics"),
                _FakeCheck(path="/system/node_b/host_metrics")], tree).run_once()
        root = tree.snapshot()
        assert root is not None
        self.assertIsNone(root.timestamp)

    def test_branch_check_children_do_not_count_as_mounts(self):
        # Only the check's own path is a mount; the result subtree it writes below
        # that path is one check's data, so the mount node still answers for it.
        tree = StatusTree()
        result = CheckResult(StatusCode.OK, children=(
            CheckResult(StatusCode.OK, name="disk"),
            CheckResult(StatusCode.OK, name="memory"),
        ))
        Engine([_FakeCheck(path="/system/node_a/host_metrics", result=result)],
               tree).run_once()
        mount = tree.snapshot("/system/node_a/host_metrics")
        root = tree.snapshot()
        assert mount is not None and root is not None
        self.assertEqual(len(mount.children), 2)
        self.assertEqual(root.timestamp, mount.timestamp)


class EmptyConfigurationTests(TestCase):
    """A configured deployment with no checks in it *yet* is a real, temporary
    state — so the engine runs and the heartbeat says so (ADR-0031 §7 / ADR-0005).
    Having nowhere to look for checks is a different thing and refuses to start;
    that lives in the loader's tests."""

    def _root(self, directory: str) -> Path:
        (Path(directory) / "checks").mkdir()
        return Path(directory)

    def test_empty_checks_aspect_starts_and_warns_on_the_heartbeat(self):
        from little_sister.engine import HEARTBEAT_PATH, create_engine
        tree = StatusTree()
        with tempfile.TemporaryDirectory() as directory:
            root = self._root(directory)
            with self.assertLogs(level="WARNING"):
                engine = create_engine(str(root), tree=tree)
            # The scheduler runs with nothing scheduled — the heartbeat is the
            # one thing it still has to publish.
            engine.start()
            try:
                self.assertTrue(_wait_for(
                    lambda: tree.snapshot(HEARTBEAT_PATH) is not None
                    and tree.snapshot(HEARTBEAT_PATH).code is StatusCode.WARN))
            finally:
                engine.stop()
            snap = tree.snapshot(HEARTBEAT_PATH)
            assert snap is not None
            # WARN, not OK: with zero checks the tree is *only* the heartbeat, so
            # an OK here would roll up to an all-green root while nothing at all is
            # being watched. The line is the engine's, on its own child
            # (ADR-0076), and the root's WARN is the roll-up.
            engine_node = tree.snapshot(f"{HEARTBEAT_PATH}/engine")
            assert engine_node is not None
            self.assertIn("no checks configured", " ".join(engine_node.reason))
            # The searched paths are the engine's report, not a second line, and
            # ride there in a code block: a report is Markdown and a path with
            # underscores would italicize (ADR-0076).
            self.assertIn(str(root.resolve()), engine_node.report)
            self.assertIn("```", engine_node.report)
            root_snap = tree.snapshot()
            assert root_snap is not None
            self.assertEqual(root_snap.code, StatusCode.WARN)

    def test_a_configured_check_keeps_the_heartbeat_ok(self):
        from little_sister.engine import HEARTBEAT_PATH
        tree = StatusTree()
        engine = Engine([_FakeCheck(path="/web")], tree)
        engine.start()
        try:
            self.assertTrue(_wait_for(
                lambda: tree.snapshot(HEARTBEAT_PATH) is not None))
        finally:
            engine.stop()
        snap = tree.snapshot(HEARTBEAT_PATH)
        assert snap is not None
        self.assertEqual(snap.code, StatusCode.OK)
        self.assertEqual(snap.reason, ())


#: A real refusal, kept whole because its length is the point: the old log line
#: cut at 120 characters, which lands inside "…AssumeRole operation:" — before
#: the half naming who was refused and for what.
ASSUME_ROLE_REFUSAL = (
    "role cannot be assumed: An error occurred (AccessDenied) when calling the "
    "AssumeRole operation: User: arn:aws:sts::000000000000:assumed-role/"
    "ExampleSSO_admin-access_0123456789abcdef/someone@example.org is not "
    "authorized to perform: sts:AssumeRole on resource: "
    "arn:aws:iam::000000000001:role/example-service-role")


class RunDetailTests(TestCase):
    """What one run's log line carries after the code and the elapsed time.

    A check that could not measure at all says so in **two** reasons on purpose —
    what went wrong, then what to do about it. The line used to keep the first
    and cut it at 120 characters, so the actionable half never appeared anywhere
    and the first ended mid-sentence.
    """

    def _detail(self, *reasons: str) -> str:
        return engine_module._detail(CheckResult(StatusCode.ERROR, list(reasons)))

    def test_no_reasons_says_nothing(self):
        self.assertEqual(self._detail(), "")

    def test_a_refusal_arrives_whole(self):
        detail = self._detail(ASSUME_ROLE_REFUSAL)
        self.assertIn("is not authorized to perform: sts:AssumeRole", detail)
        self.assertTrue(detail.endswith("example-service-role"), detail)

    def test_the_old_cut_would_have_lost_the_principal(self):
        """The regression this exists for, stated as the fact it turns on: the
        message is long enough that 120 characters end before it says anything
        about *who* was refused."""
        self.assertNotIn("is not authorized", ASSUME_ROLE_REFUSAL[:120])

    def test_the_actionable_second_reason_is_there_too(self):
        detail = self._detail("AWS credentials have expired: ExpiredToken",
                              "renew it with `aws sso login --profile live`")
        self.assertIn("expired", detail)
        self.assertIn("aws sso login --profile live", detail)

    def test_reasons_are_separated_so_two_do_not_read_as_one(self):
        self.assertIn(engine_module.DETAIL_SEPARATOR, self._detail("first", "second"))

    def test_newlines_are_flattened_into_the_one_record(self):
        detail = self._detail("first line\nsecond line")
        self.assertNotIn("\n", detail)
        self.assertIn("first line second line", detail)

    def test_a_roster_is_capped_and_says_that_it_was(self):
        """Still a cap: a check with a hundred coded lines must not put all of
        them on one line. What it truncates is a roster, and it says so rather
        than stopping where a reader would take the end for the message's own."""
        detail = self._detail(*[f"line {number}" for number in range(400)])
        self.assertLessEqual(len(detail), engine_module.DETAIL_LIMIT + 8)
        self.assertTrue(detail.endswith(" …"), detail[-40:])

    def test_an_empty_reason_is_not_a_separator_with_nothing_round_it(self):
        self.assertEqual(self._detail("", "only this"), " — only this")


class RunLogLineTests(TestCase):
    """The line itself, through a real run."""

    def test_the_line_carries_the_whole_refusal(self):
        check = _FakeCheck(path="/svc", result=CheckResult(
            StatusCode.ERROR, [ASSUME_ROLE_REFUSAL]))
        with self.assertLogs("little_sister.logger", level="INFO") as caught:
            Engine([check], StatusTree()).run_once()
        lines = [line for line in caught.output if "check /svc" in line]
        self.assertEqual(len(lines), 1, caught.output)
        self.assertIn("is not authorized to perform: sts:AssumeRole", lines[0])

    def _line(self, path: str, result: CheckResult) -> str:
        check = _FakeCheck(path=path, result=result)
        with self.assertLogs("little_sister.logger", level="INFO") as caught:
            Engine([check], StatusTree()).run_once()
        lines = [line.split(":", 2)[2] for line in caught.output
                 if f"check {path}:" in line]
        self.assertEqual(len(lines), 1, caught.output)
        return lines[0]

    def test_a_container_run_says_what_it_rolls_up_to(self):
        # A root that declares nothing above children that grade — host metrics' —
        # was logged `UNDEFINED` on every run, whether its disk was full or not.
        line = self._line("/host", CheckResult(StatusCode.UNDEFINED, children=(
            CheckResult(StatusCode.ERROR, "disk full", name="disk"),
            CheckResult(StatusCode.OK, name="cpu"))))
        self.assertRegex(
            line, r"^check /host: UNDEFINED, rolls up to ERROR \(\d+ ms\)$")

    def test_a_root_that_declares_ok_above_a_failing_child_says_so_too(self):
        line = self._line("/repos", CheckResult(StatusCode.OK, children=(
            CheckResult(StatusCode.ERROR, "red", name="actions"),)))
        self.assertRegex(
            line, r"^check /repos: OK, rolls up to ERROR \(\d+ ms\)$")

    def test_a_run_whose_own_code_is_its_roll_up_says_only_that(self):
        # A leaf, and a container whose children are no worse than its own code:
        # the line as it always was.
        for path, result in (
                ("/web", CheckResult(StatusCode.OK)),
                ("/svc", CheckResult(StatusCode.ERROR, "down", children=(
                    CheckResult(StatusCode.OK, name="a"),)))):
            with self.subTest(path=path):
                line = self._line(path, result)
                self.assertRegex(
                    line, rf"^check {path}: {result.stored_code.name} \(\d+ ms\)")
                self.assertNotIn("rolls up", line)


class SelfReportOnTheBeatTests(TestCase):
    """The heartbeat is a branch (ADR-0076): the engine's own lines on
    `/little-sister/engine`, every contributor's on `/little-sister/<name>`, each
    line a pinnable entry with the contributor's own slug, each child's code the
    worst of its lines, and the root's the roll-up."""

    def _beat(self, engine: Engine, tree: StatusTree):
        from little_sister.engine import HEARTBEAT_PATH
        engine.start()
        try:
            self.assertTrue(_wait_for(
                lambda: tree.snapshot(HEARTBEAT_PATH) is not None))
        finally:
            engine.stop()
        snap = tree.snapshot(HEARTBEAT_PATH)
        assert snap is not None
        return snap

    def _child(self, tree: StatusTree, name: str):
        from little_sister.engine import HEARTBEAT_PATH
        snap = tree.snapshot(f"{HEARTBEAT_PATH}/{name}")
        assert snap is not None, f"no /little-sister/{name}"
        return snap

    def test_a_contributor_is_a_child_carrying_its_lines_at_their_worst_code(self):
        from little_sister.reasons import Entry
        from little_sister.self_report import register_contributor
        register_contributor("state", lambda: [
            Entry("load.pins.json", "not in force", code=StatusCode.ERROR),
            Entry("save.events.json", "behind", code=StatusCode.WARN)],
            title="State", about="what a restart keeps")
        tree = StatusTree()
        root = self._beat(Engine([_FakeCheck(path="/x")], tree), tree)
        child = self._child(tree, "state")
        self.assertTrue(child.members)
        self.assertEqual([line.slug for line in child.reasons],
                         ["load.pins.json", "save.events.json"])
        self.assertEqual([line.code for line in child.reasons],
                         [StatusCode.ERROR, StatusCode.WARN])
        self.assertEqual(child.own_code, StatusCode.ERROR)
        self.assertEqual(child.title, "State")
        self.assertEqual(child.about, "what a restart keeps")
        # the root carries the beat and nothing of its own; its code is the roll-up
        self.assertEqual(root.own_code, StatusCode.OK)
        self.assertEqual(root.code, StatusCode.ERROR)

    def test_a_contributor_s_report_is_the_child_s_and_its_facts_are_no_lines(self):
        # A contributor's facts are its report (ADR-0044 decision 6, ADR-0076):
        # written on the child's `report` every tick, shown on its page, never a
        # line — so nothing uncoded carries the child's worst code, and pinning
        # the one warning leaves a child that reads MAINTENANCE, as pinning every
        # line of a coded set does.
        from datetime import datetime, timedelta

        from little_sister.reasons import Entry
        from little_sister.self_report import register_contributor
        register_contributor("aws-keeper", lambda: [
            Entry("standby", "somebody else is here", code=StatusCode.WARN)],
            report=lambda: "this instance stands by on `s3://b/p`")
        tree = StatusTree()
        self._beat(Engine([_FakeCheck(path="/x")], tree), tree)
        child = self._child(tree, "aws-keeper")
        self.assertEqual([line.slug for line in child.reasons], ["standby"])
        self.assertEqual(child.report, "this instance stands by on `s3://b/p`")
        self.assertEqual(child.own_code, StatusCode.WARN)
        tree.set_entry_maintenance(
            "/little-sister/aws-keeper", "standby", "a test with two instances",
            expires_at=datetime.now(UTC) + timedelta(days=1), set_by="pan",
            expected_set_at=None)
        self.assertEqual(self._child(tree, "aws-keeper").own_code,
                         StatusCode.MAINTENANCE)

    def test_a_report_that_clears_leaves_no_report_on_the_child(self):
        from little_sister.self_report import register_contributor
        texts = ["the lease is held here"]
        register_contributor("aws-keeper", lambda: [], report=lambda: texts[0])
        tree = StatusTree()
        self._beat(Engine([_FakeCheck(path="/x")], tree), tree)
        self.assertEqual(self._child(tree, "aws-keeper").report,
                         "the lease is held here")
        texts[0] = ""
        self._beat(Engine([_FakeCheck(path="/x")], tree), tree)
        self.assertEqual(self._child(tree, "aws-keeper").report, "")

    def test_an_uncoded_line_arrives_as_a_warn_that_says_so(self):
        # Every line on a child carries a code; a fact written as a line is a
        # defect, and it shows where somebody looks rather than counting silently.
        from little_sister.reasons import Entry
        from little_sister.self_report import register_contributor
        register_contributor("aws-keeper", lambda: [
            Entry("holder", "this instance holds the lease")])
        tree = StatusTree()
        with self.assertLogs("little_sister", level="ERROR"):
            self._beat(Engine([_FakeCheck(path="/x")], tree), tree)
        child = self._child(tree, "aws-keeper")
        self.assertEqual([(line.slug, line.code) for line in child.reasons],
                         [("holder", StatusCode.WARN)])
        self.assertIn("without a code", child.reasons[0].text)

    def test_the_engine_s_searched_paths_are_its_report_beside_the_no_checks_line(self):
        from little_sister.engine import ENGINE_REPORT
        from little_sister.reasons import Entry
        tree = StatusTree()
        warning = [Entry("no-checks", "nothing is watched", code=StatusCode.WARN)]
        self._beat(Engine([_FakeCheck(path="/x")], tree, heartbeat_warning=warning,
                          heartbeat_report="Searched:\n\n    /srv/config/checks"),
                   tree)
        child = self._child(tree, ENGINE_REPORT)
        self.assertEqual([(line.slug, line.code) for line in child.reasons],
                         [("no-checks", StatusCode.WARN)])
        self.assertIn("/srv/config/checks", child.report)

    def test_a_contributor_with_nothing_to_say_is_still_a_child_and_it_is_ok(self):
        from little_sister.self_report import register_contributor
        register_contributor("runtime", lambda: [])
        tree = StatusTree()
        root = self._beat(Engine([_FakeCheck(path="/x")], tree), tree)
        child = self._child(tree, "runtime")
        self.assertEqual(child.own_code, StatusCode.OK)
        self.assertEqual(child.reasons, ())
        self.assertIn("/little-sister/runtime", [c.path for c in root.children])

    def test_a_raising_contributor_does_not_stop_the_beat(self):
        from little_sister.self_report import register_contributor

        def broken():
            raise RuntimeError("no")

        register_contributor("keeper", broken)
        tree = StatusTree()
        with self.assertLogs(level="ERROR"):
            root = self._beat(Engine([_FakeCheck(path="/x")], tree), tree)
        child = self._child(tree, "keeper")
        self.assertEqual(child.own_code, StatusCode.WARN)
        self.assertEqual([line.slug for line in child.reasons], ["raised"])
        self.assertEqual(root.code, StatusCode.WARN)

    def test_a_report_clears_and_the_child_and_the_roll_up_follow(self):
        from little_sister.engine import HEARTBEAT_PATH
        from little_sister.reasons import Entry
        from little_sister.self_report import register_contributor
        holding = [Entry("late", "a run outgrew its period", code=StatusCode.WARN)]
        register_contributor("engine2", lambda: list(holding))
        child_path = f"{HEARTBEAT_PATH}/engine2"
        tree = StatusTree()
        engine = Engine([_FakeCheck(path="/x")], tree, poll_interval=0.02)
        engine.start()
        try:
            self.assertTrue(_wait_for(
                lambda: tree.snapshot(HEARTBEAT_PATH) is not None
                and tree.snapshot(HEARTBEAT_PATH).code is StatusCode.WARN))
            holding.clear()
            self.assertTrue(_wait_for(
                lambda: tree.snapshot(HEARTBEAT_PATH).code is StatusCode.OK))
        finally:
            engine.stop()
        self.assertEqual(tree.snapshot(child_path).reasons, ())
        # Both movements are transitions of the child the log records.
        codes = [(event.old, event.new) for event in tree.recent_events()
                 if event.path == child_path]
        self.assertIn((StatusCode.WARN, StatusCode.OK), codes)

    def test_a_line_is_pinnable_on_its_child_by_its_own_slug(self):
        from little_sister.engine import HEARTBEAT_PATH
        from little_sister.reasons import Entry
        from little_sister.self_report import register_contributor
        register_contributor("state", lambda: [
            Entry("load.pins.json", "not in force", code=StatusCode.ERROR)])
        tree = StatusTree()
        self._beat(Engine([_FakeCheck(path="/x")], tree), tree)
        child_path = f"{HEARTBEAT_PATH}/state"
        self.assertEqual(tree.snapshot(child_path).own_code, StatusCode.ERROR)
        tree.set_entry_maintenance(child_path, "load.pins.json",
                                   "re-pinned by hand",
                                   expires_at=datetime.now(UTC) + timedelta(days=1),
                                   set_by="ada")
        pinned = tree.snapshot(child_path)
        self.assertEqual(pinned.own_code, StatusCode.MAINTENANCE)
        self.assertEqual(pinned.reported_code, StatusCode.ERROR)

    def test_the_engines_own_lines_are_its_own_child(self):
        from little_sister.engine import ENGINE_REPORT, create_engine
        from little_sister.reasons import Entry
        from little_sister.self_report import register_contributor
        register_contributor("state", lambda: [Entry("x", "y", code=StatusCode.OK)])
        tree = StatusTree()
        with tempfile.TemporaryDirectory() as directory:
            (Path(directory) / "checks").mkdir()
            with self.assertLogs(level="WARNING"):
                engine = create_engine(directory, tree=tree)
            root = self._beat(engine, tree)
        engine_node = self._child(tree, ENGINE_REPORT)
        self.assertEqual([line.slug for line in engine_node.reasons], ["no-checks"])
        # the searched paths are the engine's report, not a second line
        self.assertIn("checks", engine_node.report)
        self.assertEqual(engine_node.title, "Engine")
        self.assertEqual([line.slug for line in self._child(tree, "state").reasons],
                         ["x"])
        self.assertEqual(root.code, StatusCode.WARN)


class _Gate(_FakeCheck):
    """A check that blocks on every run until the gate is opened for it — each
    ``set()`` lets exactly one run through."""

    def __init__(self, **kwargs: object) -> None:
        super().__init__(**kwargs)
        self.gate = threading.Event()

    def measure(self) -> Sequence[Measurement]:
        self.gate.wait(timeout=5)
        self.gate.clear()
        return self._measurements


class EngineOwnLinesTests(TestCase):
    """The engine's own lines on the beat (ADR-0072): what it records about
    itself as it runs, read on the tick — the entry count against its limit, a
    run that outgrew its period, a wait for a worker, a tick that came late, and
    a timeout above the frequency warned at load and never refused. The
    sentences themselves are tested in ``test_limits.py``; here is what the
    engine feeds them from its own records, on its own clock."""

    def setUp(self):
        from little_sister.limits import Limits
        self.now = 1000.0
        # No memory line, whatever this test process weighs; the pool grace
        # and the lag threshold are the defaults.
        self.limits = Limits(memory_limit=None)

    def _engine(self, checks, **kwargs) -> tuple[Engine, StatusTree]:
        tree = StatusTree()
        engine = Engine(checks, tree, poll_interval=0.02,
                        clock=lambda: self.now, limits=self.limits, **kwargs)
        return engine, tree

    def _lines(self, tree: StatusTree) -> dict[str, tuple]:
        # The engine's own lines live on /little-sister/engine (ADR-0076), with
        # their own slugs — the path carries the name.
        from little_sister.engine import ENGINE_REPORT, HEARTBEAT_PATH
        snap = tree.snapshot(f"{HEARTBEAT_PATH}/{ENGINE_REPORT}")
        if snap is None:
            return {}
        return {line.slug: (line.code, line.text) for line in snap.reasons}

    def _report(self, tree: StatusTree) -> str:
        from little_sister.engine import ENGINE_REPORT, HEARTBEAT_PATH
        snap = tree.snapshot(f"{HEARTBEAT_PATH}/{ENGINE_REPORT}")
        return snap.report if snap is not None else ""

    def _check(self, engine: Engine, path: str):
        return next(c for c in engine.info().checks if c.path == path)

    def test_the_entry_count_the_tree_holds_is_measured_against_the_limit(self):
        from little_sister.limits import Limits
        self.limits = Limits(entry_limit=3, memory_limit=None)
        check = _FakeCheck(path="/x", result=CheckResult(
            StatusCode.OK, {"a": "one", "b": "two", "c": "three"}))
        engine, tree = self._engine([check])
        engine.start()
        try:
            self.assertTrue(_wait_for(
                lambda: "entries" in self._lines(tree)))
        finally:
            engine.stop()
        code, text = self._lines(tree)["entries"]
        self.assertIs(code, StatusCode.ERROR)
        self.assertEqual(text, "the tree holds 3 entries, past its limit of 3")

    def test_a_timeout_above_the_frequency_warns_at_load_and_is_not_refused(self):
        from little_sister.engine import HEARTBEAT_PATH
        check = _FakeCheck(path="/aws/prod", timeout_seconds=120.0,
                           frequency_seconds=60)
        with self.assertLogs("little_sister.logger", level="WARNING") as caught:
            engine, tree = self._engine([check])
        self.assertEqual(len(caught.records), 1)
        self.assertIn("check /aws/prod: timeout 2m is longer than its frequency "
                      "1m", caught.output[0])
        self.assertIn("will run late, not be refused", caught.output[0])
        engine.start()
        try:
            self.assertTrue(_wait_for(
                lambda: "may run late" in self._report(tree)))
        finally:
            engine.stop()
        # A configuration that *may* run late claims nothing: it is a fact in the
        # engine's report (ADR-0076), no line, so the node stays OK until a run
        # actually does.
        self.assertNotIn("may-run-late.aws-prod", self._lines(tree))
        self.assertIn("/aws/prod may run late: its timeout of 2m is longer than "
                      "its frequency of 1m", self._report(tree))
        self.assertIs(tree.snapshot(HEARTBEAT_PATH).code, StatusCode.OK)

    def test_a_timeout_within_the_frequency_says_nothing(self):
        check = _FakeCheck(path="/x", timeout_seconds=60.0, frequency_seconds=60)
        engine, _tree = self._engine([check])
        self.assertEqual(engine._report.may_run_late, ())

    def test_a_run_past_its_period_is_a_line_while_it_runs_and_until_one_fits(self):
        check = _FakeCheck(path="/slow", frequency_seconds=60,
                           block=(block := threading.Event()))
        engine, tree = self._engine([check])
        engine.start()
        try:
            self.assertTrue(_wait_for(
                lambda: self._check(engine, "/slow").running_since is not None))
            self.assertNotIn("late.slow", self._lines(tree))
            self.now += 100                       # in flight for 1m 40s of a 1m period
            self.assertTrue(_wait_for(
                lambda: "late.slow" in self._lines(tree)))
            code, text = self._lines(tree)["late.slow"]
            self.assertIs(code, StatusCode.WARN)
            self.assertEqual(text, "/slow has been running for 1m 40s, longer than "
                                   "its frequency of 1m — it runs late")
            block.set()                           # the run completes, at 1m 40s
            self.assertTrue(_wait_for(
                lambda: "ran for 1m 40s" in self._lines(tree).get(
                    "late.slow", (None, ""))[1]))
            # The next run fits its period (the clock does not move while it
            # runs), and the line clears with it.
            self.now += 100
            self.assertTrue(_wait_for(
                lambda: "late.slow" not in self._lines(tree)
                and self._check(engine, "/slow").elapsed_seconds == 0.0))
        finally:
            block.set()
            engine.stop()

    def test_a_wait_for_a_worker_is_saturation_after_the_first_sweep_not_in_it(self):
        a = _Gate(path="/a", frequency_seconds=60)
        b = _FakeCheck(path="/b", frequency_seconds=60)
        engine, tree = self._engine([a, b], max_workers=1)
        engine.start()
        try:
            # The first sweep: a holds the one worker, b is queued behind it.
            self.assertTrue(_wait_for(
                lambda: self._check(engine, "/a").running_since is not None
                and self._check(engine, "/b").running
                and self._check(engine, "/b").running_since is None))
            self.now += 30
            time.sleep(0.1)                       # several ticks at that clock
            self.assertNotIn("pool", self._lines(tree))
            a.gate.set()
            self.assertTrue(_wait_for(
                lambda: all(c.last_run_at for c in engine.info().checks)))
            # The second sweep, after both have run once: the same queue is now
            # a pool too small for its schedule.
            self.now += 200
            self.assertTrue(_wait_for(
                lambda: self._check(engine, "/a").running_since is not None
                and self._check(engine, "/b").running
                and self._check(engine, "/b").running_since is None))
            self.now += 30
            self.assertTrue(_wait_for(
                lambda: "pool" in self._lines(tree)))
            code, text = self._lines(tree)["pool"]
            self.assertIs(code, StatusCode.WARN)
            self.assertEqual(text, "the pool is saturated: 1 check is waiting for "
                                   "its 1 worker, the longest for 30 s")
            a.gate.set()
            self.assertTrue(_wait_for(
                lambda: "pool" not in self._lines(tree)))
        finally:
            a.gate.set()
            engine.stop()

    def test_a_tick_that_came_late_is_a_line(self):
        engine, tree = self._engine([_FakeCheck(path="/x")])
        engine.start()
        try:
            self.assertTrue(_wait_for(lambda: self._lines(tree) == {}
                                      and tree.snapshot("/little-sister") is not None))
            self.now += 30
            self.assertTrue(_wait_for(lambda: "lag" in self._lines(tree)))
        finally:
            engine.stop()
        code, text = self._lines(tree)["lag"]
        self.assertIs(code, StatusCode.WARN)
        self.assertEqual(text, "the scheduler came late within the last 10m: a "
                               "tick came 30 s after the one before, against an "
                               "interval of 1s")

    def test_a_run_is_measured_on_the_engines_clock(self):
        # The one clock: the tick reads a run's start back against the clock the
        # engine was given, so an injected clock sees an in-flight run age.
        check = _FakeCheck(path="/x", block=(block := threading.Event()))
        engine, _tree = self._engine([check])
        engine.start()
        try:
            self.assertTrue(_wait_for(
                lambda: self._check(engine, "/x").running_since is not None))
            self.now += 7
            self.assertEqual(self._check(engine, "/x").running_seconds, 7.0)
            block.set()
            self.assertTrue(_wait_for(
                lambda: self._check(engine, "/x").elapsed_seconds is not None))
            self.assertEqual(self._check(engine, "/x").elapsed_seconds, 7.0)
        finally:
            block.set()
            engine.stop()


class MemoryLineOnTheBeatTests(TestCase):
    """The engine's `memory` line holds what it saw, as its `lag` line does
    (ADR-0095), and the tree's log is where that shows: `/little-sister/engine`
    changes when the line's code does, so a process that sits on its limit writes
    an event when it crosses it and none for every tick it wavers there. The
    sentences are ``test_limits.py``'s; here is what the engine feeds them — the
    size its ``resident`` reads on the tick, the instant its ``wall`` answers — and
    what a reader of the events is left with. The values are the deployment's the
    line was held for: a limit of 504 MiB of the 917 MiB a machine gives, and the
    window the ten minutes it is."""

    MIB = 1024 ** 2

    def setUp(self):
        from little_sister.limits import Limits, Resident
        self.mono = 1000.0
        # One second before the configured zone's clock reads 09:12:00: the first
        # tick is observed then, and every tick after it a second later on both
        # clocks, so that none comes late.
        self.wall = (datetime(2026, 10, 10, 9, 12, tzinfo=config.tzinfo)
                     - timedelta(seconds=1))
        self.size = 0
        self.unread = False
        self.tree = StatusTree()
        self.engine = Engine(
            [], self.tree, clock=lambda: self.mono, wall=lambda: self.wall,
            limits=Limits(memory_limit=504 * self.MIB,
                          machine_memory=917 * self.MIB),
            resident=lambda: Resident(
                peak=600 * self.MIB, now=None if self.unread else self.size))

    def _tick(self, mib: float, *, times: int = 1, unread: bool = False) -> None:
        """``times`` ticks at ``mib`` — with ``unread``, ticks on which the size now
        cannot be read and the high-water mark, 600 MiB, can."""
        self.size, self.unread = round(mib * self.MIB), unread
        for _ in range(times):
            self.mono += 1.0
            self.wall += timedelta(seconds=1)
            self.engine._guarded_tick(submit=False)

    def _path(self) -> str:
        from little_sister.engine import ENGINE_REPORT
        return f"{HEARTBEAT_PATH}/{ENGINE_REPORT}"

    def _line(self) -> tuple[StatusCode, str] | None:
        snap = self.tree.snapshot(self._path())
        assert snap is not None
        found = [(line.code, line.text) for line in snap.reasons
                 if line.slug == "memory"]
        self.assertEqual([line.slug for line in snap.reasons],
                         ["memory"] * len(found))
        return found[0] if found else None

    def _changes(self) -> list[tuple[StatusCode, StatusCode]]:
        """Every event the tree wrote for the engine's node, oldest first."""
        return [(event.old, event.new) for event in self.tree.recent_events()
                if event.path == self._path()]

    def test_a_size_past_the_limit_on_one_tick_and_below_it_on_the_next_is_one_event(
            self):
        self._tick(450)                       # the amber band, at 09:12:00
        self._tick(505)                       # past the limit
        self._tick(498)                       # and below it again
        self.assertEqual(self._changes(),
                         [(StatusCode.UNDEFINED, StatusCode.WARN),
                          (StatusCode.WARN, StatusCode.ERROR)])
        self.assertEqual(self._line(), (
            StatusCode.ERROR,
            "resident size 505 MiB at 09:12, past the limit of 504 MiB (now 498 MiB "
            "of the 917 MiB the machine gives the process)"))

    def test_a_size_that_crosses_the_limit_twice_inside_the_window_writes_no_second(
            self):
        self._tick(450)
        self._tick(505)
        written = self._changes()
        self.assertEqual(written, [(StatusCode.UNDEFINED, StatusCode.WARN),
                                   (StatusCode.WARN, StatusCode.ERROR)])
        for mib in (498, 506, 498, 505, 498):
            self._tick(mib)
        self.assertEqual(self._changes(), written)
        code, text = self._line()
        self.assertIs(code, StatusCode.ERROR)
        self.assertIn("resident size 506 MiB at 09:12, past the limit", text)

    def test_a_size_below_the_limit_for_the_whole_window_steps_the_line_down(self):
        self._tick(450)
        self._tick(505)                       # past the limit, at 09:12:01
        self._tick(498, times=600)            # ten minutes on: still in the window
        self.assertIs(self._line()[0], StatusCode.ERROR)
        self.assertEqual(len(self._changes()), 2)
        self._tick(498)                       # the whole window stood below the limit
        self.assertEqual(self._changes()[2:],
                         [(StatusCode.ERROR, StatusCode.WARN)])
        self.assertEqual(self._line(), (
            StatusCode.WARN,
            "resident size 498 MiB at 09:22, 99 % of the limit of 504 MiB (now 498 "
            "MiB of the 917 MiB the machine gives the process)"))
        self._tick(300, times=600)            # below the amber share for ten minutes
        self.assertIs(self._line()[0], StatusCode.WARN)
        self.assertEqual(len(self._changes()), 3)
        self._tick(300)                       # the whole window below it: gone
        self.assertEqual(self._changes()[3:], [(StatusCode.WARN, StatusCode.OK)])
        self.assertIsNone(self._line())

    def test_a_tick_that_cannot_read_the_size_now_writes_no_event(self):
        """The process holds 300 MiB and reached 600 once. On one tick the size now
        cannot be read, and what that tick has is the high-water mark: taken for
        the size, graded and held, it would turn the node ERROR for ten minutes
        over a process at three fifths of its limit."""
        self._tick(300, times=3)
        before = self._changes()
        self.assertEqual(before, [(StatusCode.UNDEFINED, StatusCode.OK)])
        self._tick(300, unread=True)
        self.assertIsNone(self._line())
        self._tick(300, times=3)
        self.assertIsNone(self._line())
        self.assertEqual(self._changes(), before)

    def test_a_process_that_sits_on_its_limit_writes_the_one_event(self):
        """Twenty minutes of what the deployment's instance did for a day and a
        half: a tenth of a mebibyte past the limit on one tick and as far below it
        on the next. Graded on the tick's own figure, that was an event a
        second."""
        self._tick(450)                       # at 09:12:00
        for second in range(1200):            # through 09:32:00
            self._tick(504.1 if second % 2 == 0 else 503.9)
        self.assertEqual(self._changes(),
                         [(StatusCode.UNDEFINED, StatusCode.WARN),
                          (StatusCode.WARN, StatusCode.ERROR)])
        self.assertEqual(self._line(), (
            StatusCode.ERROR,
            "resident size 504 MiB at 09:31, 102.4 KiB past the limit of 504 MiB "
            "(now 504 MiB of the 917 MiB the machine gives the process)"))


class StateOnTheTickTests(TestCase):
    """The engine drives the state layer (ADR-0071): the kept files on the tick,
    once more at stop."""

    def test_the_tick_writes_the_kept_files_after_an_interval(self):
        from little_sister.state import StateLayer
        with tempfile.TemporaryDirectory() as directory:
            state = StateLayer(directory, interval_seconds=1)
            state.keep("a.json", lambda: {"a": 1})
            tree = StatusTree()
            engine = Engine([_FakeCheck(path="/x")], tree, poll_interval=0.02,
                            state=state)
            engine.start()
            try:
                self.assertTrue(_wait_for(lambda: state.path("a.json").exists(),
                                          timeout=3.0))
            finally:
                engine.stop()

    def test_stop_flushes_what_changed(self):
        from little_sister.state import StateLayer
        with tempfile.TemporaryDirectory() as directory:
            state = StateLayer(directory, interval_seconds=3600)
            payload = {"events": []}
            state.keep(EVENTS_FILE, lambda: payload)
            tree = StatusTree()
            engine = Engine([_FakeCheck(path="/x")], tree, state=state)
            engine.start()
            self.assertTrue(_wait_for(lambda: engine.info().started_at is not None))
            payload["events"].append({"path": "/x"})
            engine.stop()
            self.assertEqual(on_disk(state.path(EVENTS_FILE)),
                             {"events": [{"path": "/x"}]})


class CheckOutcomesTests(TestCase):
    """What the engine records for the readiness answer (ADR-0073): the code each
    check last stored, counted. The lines made from it are ``test_readiness.py``.
    """

    def test_nothing_has_completed_before_the_first_run(self):
        engine = Engine([_FakeCheck(path="/a"), _FakeCheck(path="/b")],
                        StatusTree())
        self.assertEqual(engine.outcomes.configured, 2)
        self.assertEqual(engine.outcomes.completed, 0)
        self.assertFalse(engine.outcomes.first_pass)

    def test_a_completed_pass_counts_every_check(self):
        engine = Engine([_FakeCheck(path="/a"), _FakeCheck(path="/b")],
                        StatusTree())
        engine.run_once()
        self.assertEqual(engine.outcomes.completed, 2)
        self.assertEqual(engine.outcomes.erroring, 0)
        self.assertTrue(engine.outcomes.first_pass)

    def test_a_check_that_raised_last_stored_an_error(self):
        engine = Engine([_FakeCheck(path="/a", raises=RuntimeError("boom")),
                         _FakeCheck(path="/b")], StatusTree())
        engine.run_once()
        self.assertEqual(engine.outcomes.erroring, 1)

    def test_every_check_erroring_is_visible_as_the_pattern(self):
        engine = Engine([_FakeCheck(path="/a", raises=RuntimeError("boom")),
                         _FakeCheck(path="/b", raises=RuntimeError("boom"))],
                        StatusTree())
        engine.run_once()
        self.assertTrue(engine.outcomes.all_erroring)

    def test_a_recovered_check_is_no_longer_counted(self):
        # `last_stored` is the *last* result, not a tally: a check that errored and
        # then recovered must leave the pattern, or the line would never clear.
        check = _FakeCheck(path="/a", result=CheckResult(StatusCode.ERROR, ["no"]))
        engine = Engine([check, _FakeCheck(
            path="/b", result=CheckResult(StatusCode.ERROR, ["no"]))], StatusTree())
        engine.run_once()
        self.assertTrue(engine.outcomes.all_erroring)
        check._result = CheckResult(StatusCode.OK)
        engine.run_once()
        self.assertEqual(engine.outcomes.erroring, 1)
        self.assertFalse(engine.outcomes.all_erroring)

    def test_a_secret_pinned_check_completes_without_running(self):
        # It never calls run() and stores its ERROR anyway (ADR-0023), so it counts
        # toward the pass — a first pass that waited for it would never finish.
        check = _FakeCheck(path="/a")
        check.secret_errors = ["LITTLE_SISTER_TOKEN is not set"]
        engine = Engine([check], StatusTree())
        engine.run_once()
        self.assertTrue(engine.outcomes.first_pass)
        self.assertEqual(engine.outcomes.erroring, 1)


class DeclaredCapacityTests(TestCase):
    """Startup sums what the configured checks declared against the pool it will
    run and the entry limit, and refuses what cannot fit (ADR-0075). The engine's
    side of it; the arithmetic and its sentences are in `test_limits.py`."""

    def test_a_declared_load_past_the_pool_refuses_naming_the_check(self):
        checks = [_CostlyCheck(path="/big", cost=600.0, frequency_seconds=60),
                  _CostlyCheck(path="/small", cost=1.0, frequency_seconds=60)]
        with self.assertRaises(CheckError) as caught:
            Engine(checks, StatusTree(), max_workers=2)
        self.assertIn("/big 10.0 (10m every 1m)", str(caught.exception))

    def test_declared_entries_past_the_limit_refuse(self):
        check = _CostlyCheck(path="/wide", entries=500, frequency_seconds=60)
        with self.assertRaises(CheckError) as caught:
            Engine([check], StatusTree(), limits=Limits(entry_limit=100))
        self.assertIn("/wide 500", str(caught.exception))

    def test_a_refusal_leaves_nothing_registered_on_the_tree(self):
        # the refusal comes before the mounts and the heartbeat's about text, so a
        # process that cannot serve its configuration has not half-built a tree
        tree = StatusTree()
        with self.assertRaises(CheckError):
            Engine([_CostlyCheck(path="/big", cost=600.0, frequency_seconds=60)],
                   tree, max_workers=2)
        # a successful construction seeds the heartbeat's `about` and with it the
        # node, so its absence is the whole difference
        self.assertIsNone(tree.snapshot(HEARTBEAT_PATH))
        Engine([_FakeCheck(path="/b")], tree)
        self.assertIsNotNone(tree.snapshot(HEARTBEAT_PATH))

    def test_the_pool_it_measures_against_is_the_one_it_will_run(self):
        # eight workers configured, one check, so the pool is one — and 1.5
        # declared workers do not fit in it
        check = _CostlyCheck(path="/big", cost=90.0, frequency_seconds=60)
        with self.assertRaises(CheckError):
            Engine([check], StatusTree(), max_workers=8)

    def test_a_load_inside_the_limits_starts_and_warns_when_it_is_close(self):
        checks = [_CostlyCheck(path="/a", cost=48.0, frequency_seconds=60),
                  _FakeCheck(path="/b")]
        with self.assertLogs(level="WARNING") as caught:
            engine = Engine(checks, StatusTree(), max_workers=1)
        self.assertIn("declare 0.8 of the 1 worker threads", "".join(caught.output))
        self.assertEqual(engine.check_count, 2)

    def test_what_each_check_declared_is_on_the_system_page(self):
        checks = [_CostlyCheck(path="/a", cost=6.0, entries=12,
                               frequency_seconds=60),
                  _FakeCheck(path="/b")]
        info = Engine(checks, StatusTree(), max_workers=4).info()
        declared, silent = info.checks
        self.assertEqual((declared.expected_cost, declared.expected_entries),
                         (6.0, 12))
        self.assertEqual((silent.expected_cost, silent.expected_entries),
                         (None, None))
        self.assertEqual(info.declared_workers, 0.1)
        self.assertEqual(info.declared_entries, 12)

    def test_the_entries_held_stand_beside_the_limit(self):
        tree = StatusTree()
        engine = Engine([_FakeCheck(path="/a", result=CheckResult(
            StatusCode.ERROR, ["one reason"]))], tree,
            limits=Limits(entry_limit=1234))
        engine.run_once()
        info = engine.info()
        self.assertEqual(info.entries_held, tree.entry_count)
        self.assertEqual(info.entry_limit, 1234)


class WorkerCeilingTests(TestCase):
    """`max_workers` is a setting (ADR-0075), read when a caller does not say."""

    def test_the_setting_is_the_ceiling_when_none_is_given(self):
        checks = [_FakeCheck(path=f"/c{index}") for index in range(6)]
        with patch.object(engine_module, "config", replace(config, max_workers=3)):
            self.assertEqual(Engine(checks, StatusTree()).info().max_workers, 3)

    def test_an_explicit_ceiling_wins_over_the_setting(self):
        checks = [_FakeCheck(path=f"/c{index}") for index in range(6)]
        with patch.object(engine_module, "config", replace(config, max_workers=3)):
            engine = Engine(checks, StatusTree(), max_workers=5)
        self.assertEqual(engine.info().max_workers, 5)

    def test_the_pool_is_never_larger_than_the_roster(self):
        with patch.object(engine_module, "config", replace(config, max_workers=8)):
            engine = Engine([_FakeCheck(path="/only")], StatusTree())
        self.assertEqual(engine.info().max_workers, 1)



class StopTests(TestCase):
    """A stop ends at its save (ADR-0088): it abandons what is in flight, says so once,
    and nothing a run delivers afterwards is recorded."""

    def _slow(self, tree: StatusTree) -> tuple[Engine, threading.Event]:
        block = threading.Event()
        slow = _FakeCheck(path="/slow", result=CheckResult(StatusCode.OK), block=block)
        engine = Engine([slow], tree)
        engine.start()
        self.assertTrue(_wait_for(lambda: engine._scheduled[0].running))
        return engine, block

    def test_a_stop_abandons_a_run_in_flight_and_names_it_once(self):
        tree = StatusTree()
        engine, block = self._slow(tree)
        started = time.monotonic()
        with self.assertLogs("little_sister", level="INFO") as logs:
            engine.stop(trigger="worker_exit")
        self.assertLess(time.monotonic() - started, 2.0)
        said = [line for line in logs.output if "abandoned" in line]
        self.assertEqual(len(said), 1, logs.output)
        self.assertIn("/slow", said[0])
        self.assertIn("worker_exit", said[0])
        block.set()

    def test_a_result_delivered_after_the_stop_is_dropped(self):
        tree = StatusTree()
        engine, block = self._slow(tree)
        engine.stop(trigger="test")
        block.set()
        time.sleep(0.3)
        self.assertIsNone(tree.snapshot("/slow"))

    def test_a_second_stop_says_nothing(self):
        engine = Engine([_FakeCheck(path="/x")], StatusTree())
        engine.start()
        engine.stop(trigger="worker_exit")
        with self.assertNoLogs("little_sister", level="INFO"):
            engine.stop(trigger="atexit")

    def test_the_stop_makes_one_save_and_writes_nothing_after_it(self):
        from little_sister.state import StateLayer
        with tempfile.TemporaryDirectory() as directory:
            state = StateLayer(directory, interval_seconds=3600)
            tree = StatusTree()
            block = threading.Event()
            engine = Engine([_FakeCheck(path="/slow", result=CheckResult(StatusCode.OK),
                                        block=block)], tree, state=state)
            engine.start()
            self.assertTrue(_wait_for(lambda: engine._scheduled[0].running))
            engine.stop(trigger="test")
            self.assertFalse(state.write("late.json", {"late": True}))
            block.set()

    def test_a_run_in_flight_does_not_hold_the_interpreter_s_exit(self):
        """The standard pool's exit hook joins every thread it started, whatever its
        daemon flag; the engine's own pool is one the interpreter does not join."""
        script = textwrap.dedent("""
            import threading, time
            from little_sister.checks.base import Check, CheckResult
            from little_sister.engine import Engine
            from little_sister.status import StatusCode
            from little_sister.tree import StatusTree

            class Hangs(Check):
                def measure(self):
                    threading.Event().wait()
                    return ()
                def grade(self, measurements, now):
                    return CheckResult(StatusCode.OK)

            engine = Engine([Hangs(path="/hangs")], StatusTree())
            engine.start()
            time.sleep(1.0)
            print("leaving", flush=True)
            """)
        with tempfile.TemporaryDirectory() as directory:
            started = time.monotonic()
            done = subprocess.run([sys.executable, "-c", script], cwd=directory,
                                  env=subprocess_env(),
                                  capture_output=True, text=True, timeout=20)
        self.assertIn("leaving", done.stdout, done.stderr[-3000:])
        self.assertLess(time.monotonic() - started, 6.0)


class _Counted(_FakeCheck):
    """A check that notes when each of its runs began."""

    def __init__(self, runs: list[float], **kwargs: object) -> None:
        super().__init__(**kwargs)
        self.runs = runs

    def measure(self) -> Sequence[Measurement]:
        self.runs.append(time.monotonic())
        return super().measure()


class LostLeaseTests(TestCase):
    """A holder that loses the state directory's lease stops its engine as well as its
    writes (ADR-0090 decision 7): it runs no more checks, and serves the last view it
    had with the readiness line that says why."""

    THIEF = "thief:2:20260926T000000Z:0b5e55ed"

    def _engine(self, directory: str, runs: list[float]):
        from little_sister import self_report
        from little_sister.lease import Lease
        from little_sister.readiness import Readiness, TrustStore
        from little_sister.state import StateLayer
        where = Path(directory) / "var" / "state"
        state = StateLayer(where, interval_seconds=3600)
        lease = Lease(where, mark="me:1:t:a", kernel="kernel-A", beat_seconds=0.05)
        lease.take()
        self.addCleanup(lease.release)
        state.hold(lease)
        report = Readiness(doors=lambda: True, trust=lambda: TrustStore(usable=True),
                           first_pass=lambda: True, outcomes=lambda: None,
                           lost=lambda: lease.lost)
        self_report.register_contributor("readiness", report.lines)
        tree = StatusTree()
        engine = Engine([_Counted(runs, path="/often", frequency_seconds=1)], tree,
                        state=state, poll_interval=0.02)
        return engine, tree, lease

    def _take(self, directory: str) -> None:
        """Another kernel's process takes the directory over."""
        (Path(directory) / "var" / "state.lease").write_text(json.dumps(
            {"mark": self.THIEF, "host": "elsewhere", "pid": 2}), encoding="utf-8")

    def test_a_lost_lease_halts_the_engine_and_no_check_runs_after_it(self):
        runs: list[float] = []
        with tempfile.TemporaryDirectory() as directory:
            engine, _, _ = self._engine(directory, runs)
            engine.start()
            scheduler = engine._scheduler
            assert scheduler is not None
            self.assertTrue(_wait_for(lambda: len(runs) >= 1))
            with self.assertLogs("little_sister", level="ERROR") as logs:
                self._take(directory)
                self.assertTrue(_wait_for(lambda: not scheduler.is_alive(), 3.0),
                                "the scheduler went on after the lease was lost")
            ran = len(runs)
            time.sleep(1.5)
            self.assertEqual(len(runs), ran, "a check ran after the lease was lost")
            halted = [line for line in logs.output if "engine: halted" in line]
            self.assertEqual(len(halted), 1, logs.output)
            self.assertIn(self.THIEF, halted[0])
            self.assertIn("runs no more checks", halted[0])

    def test_it_serves_its_last_view_with_the_line_that_says_why(self):
        runs: list[float] = []
        with tempfile.TemporaryDirectory() as directory:
            engine, tree, _ = self._engine(directory, runs)
            engine.start()
            self.assertTrue(_wait_for(lambda: len(runs) >= 1))
            with self.assertLogs("little_sister", level="ERROR"):
                self._take(directory)
                self.assertTrue(_wait_for(
                    lambda: engine._scheduler is not None
                    and not engine._scheduler.is_alive(), 3.0))
            node = tree.snapshot(f"{HEARTBEAT_PATH}/readiness")
            assert node is not None
            self.assertEqual(node.code, StatusCode.ERROR)
            self.assertIn(self.THIEF, " ".join(line.text for line in node.reasons))
            self.assertIsNotNone(tree.snapshot("/often"), "the last view is kept")

    def test_the_stop_after_it_says_nothing_and_releases_nothing(self):
        runs: list[float] = []
        with tempfile.TemporaryDirectory() as directory:
            engine, _, _ = self._engine(directory, runs)
            engine.start()
            self.assertTrue(_wait_for(lambda: len(runs) >= 1))
            with self.assertLogs("little_sister", level="ERROR"):
                self._take(directory)
                self.assertTrue(_wait_for(
                    lambda: engine._scheduler is not None
                    and not engine._scheduler.is_alive(), 3.0))
            with self.assertNoLogs("little_sister", level="INFO"):
                engine.stop(trigger="worker_exit")
            holder = json.loads((Path(directory) / "var" / "state.lease").read_text())
            self.assertEqual(holder["mark"], self.THIEF,
                             "the stop wrote over the new holder's lease")


if __name__ == '__main__':
    unittest.main()
