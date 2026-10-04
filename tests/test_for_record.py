"""A grading may write a line for the record alone (ADR-0111 decisions 2 and 7), read
against the record's sentences: the reading whose record the line carries keeps the
line's code and its sentence, and the node never sees it.

The estate is one check of a job name. Its source lists every run of the name that is
still young, so each poll reads all of them, and the grading hands back a node for the
job name: its line carries the newest run, and each older run has a line in
``for_record``.
"""
from __future__ import annotations

from collections.abc import Sequence
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from typing import Any
from unittest import TestCase, mock

from little_sister import app as app_module
from little_sister import self_report
from little_sister.checks.base import (
    Check,
    CheckError,
    CheckResult,
    Measurement,
    _record_limit,
)
from little_sister.engine import Engine
from little_sister.reasons import Entry
from little_sister.series import Placed
from little_sister.status import StatusCode
from little_sister.tree import StatusTree

T0 = datetime(2026, 10, 3, 2, 0, tzinfo=UTC)
CODES = {"succeeded": StatusCode.OK, "slow": StatusCode.WARN,
         "failed": StatusCode.ERROR}
SUBJECT = "job/import"


class _Job(Check):
    """Reads every run of one job name its source still lists."""

    type_name = "job"

    def __init__(self, *, said: str = "for_record", **kwargs: Any) -> None:
        super().__init__(**kwargs)
        #: How the grading says an older run's verdict: in ``for_record``, on the
        #: node's own lines (``shown``), in both, or not at all (``unsaid``) — or
        #: in ``for_record`` beside a record past the limit (``heavy``).
        self.said = said
        self.listed: list[tuple[str, str]] = []

    def ran(self, outcome: str) -> None:
        """One more run of the name, a day after the one before."""
        self.listed.append((f"run-{len(self.listed) + 1}", outcome))

    def measure(self) -> Sequence[Measurement]:
        return [Measurement(
            record={"run": run, "outcome": outcome,
                    "at": (T0 + timedelta(days=index)).isoformat()},
            subject=SUBJECT, identity=run)
            for index, (run, outcome) in enumerate(self.listed)]

    def grade(self, measurements: Sequence[Measurement],
              now: datetime) -> CheckResult:
        def line(reading: Measurement) -> Entry:
            record = reading.record
            return Entry(str(record["run"]), f"{record['run']} {record['outcome']}",
                         code=CODES[str(record["outcome"])], subject=reading.subject,
                         data=dict(record))

        *older, newest = measurements
        shown = [line(newest)]
        kept: list[Entry] = []
        if self.said in ("for_record", "both"):
            kept = [line(reading) for reading in older]
        if self.said == "heavy":
            kept = [replace(line(reading), data={
                **reading.record, "log": "x" * (_record_limit() + 100)})
                for reading in older]
        if self.said in ("shown", "both"):
            shown += [replace(line(reading), text=f"{line(reading).text}, on the wall")
                      for reading in older]
        # the keyword only where a line is written for the record, so that what a
        # grading without one leaves is read as it always was
        written: dict[str, Any] = {"for_record": kept} if kept else {}
        return CheckResult(StatusCode.UNDEFINED, children=(
            CheckResult(name="import", reason=shown, **written),))


class ForRecordAtTheSeamTests(TestCase):
    """What a result takes in ``for_record``, and what it leaves alone."""

    LINE = Entry("run-1", "run-1 failed", code=StatusCode.ERROR, subject=SUBJECT,
                 data={"run": "run-1"})

    def test_a_result_keeps_the_lines_written_for_the_record(self) -> None:
        result = CheckResult(reason=[Entry("now", "run-2 succeeded",
                                           code=StatusCode.OK)],
                             for_record=[self.LINE])
        self.assertEqual([line.text for line in result.for_record], ["run-1 failed"])
        # and they are no lines of the node's: not among its reasons, and its code
        # is the worst of its own lines' alone
        self.assertEqual(result.reason_texts, ["run-2 succeeded"])
        self.assertIs(result.stored_code, StatusCode.OK)
        self.assertTrue(all(entry.text != "run-1 failed"
                            for entry in result.reason_entries))

    def test_a_result_that_writes_none_has_none(self) -> None:
        self.assertEqual(tuple(CheckResult(StatusCode.OK).for_record), ())

    def test_a_line_for_the_record_carries_its_own_code(self) -> None:
        with self.assertRaisesRegex(CheckError, "its own code"):
            CheckResult(StatusCode.OK, for_record=[replace(self.LINE, code=None)])

    def test_a_line_for_the_record_carries_the_record_it_is_said_of(self) -> None:
        with self.assertRaisesRegex(CheckError, "the record"):
            CheckResult(StatusCode.OK, for_record=[replace(self.LINE, data=None)])

    def test_only_a_line_is_written_for_the_record(self) -> None:
        for other in ("run-1 failed", ("run-1", "run-1 failed")):
            with self.subTest(other=other), self.assertRaisesRegex(CheckError,
                                                                    "an Entry"):
                CheckResult(StatusCode.OK, for_record=[other])  # type: ignore[list-item]

    def test_two_lines_for_the_record_may_share_a_slug(self) -> None:
        # a slug is what a pin holds, and nothing pins a line the node does not show
        twice = CheckResult(StatusCode.OK, for_record=[
            self.LINE, replace(self.LINE, data={"run": "run-0"})])
        self.assertEqual([line.slug for line in twice.for_record], ["run-1", "run-1"])

    def test_its_record_goes_through_the_seam_a_shown_lines_goes_through(self) -> None:
        with self.assertRaisesRegex(CheckError, "JSON-serializable"):
            CheckResult(StatusCode.OK,
                        for_record=[replace(self.LINE, data={"run": object()})])
        kept = CheckResult(StatusCode.OK, for_record=[
            replace(self.LINE, data={"run": ("run-1",)})]).for_record[0]
        # what is kept is plain JSON, as a shown line's record is
        self.assertEqual(kept.data, {"run": ["run-1"]})


class ForRecordInTheSeriesTests(TestCase):
    """What a run keeps of a line written for the record alone, and what its node
    shows of it."""

    def setUp(self) -> None:
        self._saved = (app_module.status_tree, app_module.engine)
        self.addCleanup(self._restore)
        settings = mock.patch(
            "little_sister.config.config",
            replace(app_module.config, timezone="Europe/Berlin",
                    time_format="%Y-%m-%d %H:%M:%S"))
        settings.start()
        self.addCleanup(settings.stop)
        self.client = app_module.app.test_client()
        self.client.post("/login", data={"username": "pan", "password": "12345678"})

    def _restore(self) -> None:
        app_module.status_tree, app_module.engine = self._saved

    def _deploy(self, *outcomes: str, **options: Any) -> _Job:
        self.tree = StatusTree()
        app_module.status_tree = self.tree
        check = _Job(path="/batch", subject="queue/live", series_keep=10, **options)
        app_module.engine = Engine([check], self.tree)
        for outcome in outcomes:
            check.ran(outcome)
            app_module.engine.run_once()
        return check

    def _kept(self) -> dict[str, Placed]:
        """The job name's kept runs, by the run each is of."""
        (series,) = [series for series in app_module.engine.series_near("/batch")
                     if series.subject == SUBJECT]
        return {placed.record.identity: placed for placed in series.readings}

    def test_a_run_keeps_the_code_and_the_sentence_of_its_line_for_the_record(
            self) -> None:
        self._deploy("failed", "slow", "succeeded")
        kept = self._kept()
        self.assertEqual({run: placed.record.code for run, placed in kept.items()},
                         {"run-1": StatusCode.ERROR, "run-2": StatusCode.WARN,
                          "run-3": StatusCode.OK})
        self.assertEqual(kept["run-1"].record.texts, ("run-1 failed",))
        # the newest run's are its shown line's, as they were
        self.assertEqual(kept["run-3"].record.texts, ("run-3 succeeded",))

    def test_without_one_a_run_that_had_the_line_loses_its_verdict(self) -> None:
        # the trap the record names: a re-read replaces the kept record with what
        # stands then, and after a newer run took the line nothing stands
        self._deploy("failed", "succeeded", said="unsaid")
        kept = self._kept()
        self.assertIsNone(kept["run-1"].record.code)
        self.assertEqual(kept["run-1"].record.texts, ())
        self.assertIs(kept["run-2"].record.code, StatusCode.OK)

    def test_a_run_keeps_its_verdict_on_every_poll_that_reads_it(self) -> None:
        check = self._deploy("failed", "succeeded")
        for _ in range(3):
            assert app_module.engine is not None
            app_module.engine.run_once()
        self.assertEqual(len(check.listed), 2)
        self.assertIs(self._kept()["run-1"].record.code, StatusCode.ERROR)

    def test_the_node_never_sees_a_line_written_for_the_record(self) -> None:
        self._deploy("failed", "failed", "succeeded")
        node = self.tree.snapshot("/batch/import")
        assert node is not None
        # its code is its own line's, the newest run's, though two older runs failed
        self.assertIs(node.code, StatusCode.OK)
        self.assertEqual([line.text for line in node.reasons], ["run-3 succeeded"])
        self.assertIs(self.tree.snapshot("/batch").code, StatusCode.OK)
        page = self.client.get("/status/batch/import").get_data(as_text=True)
        self.assertIn("run-3 succeeded", page)
        self.assertNotIn("run-1 failed", page)
        # and nothing of it is in what the wall is polled with
        self.assertNotIn("run-1 failed",
                         self.client.get("/status/batch").get_data(as_text=True))

    def test_the_instance_says_whose_record_the_seam_refused(self) -> None:
        # a line the seam takes the record from is said of no reading, and the
        # instance says so where it says what keeps going wrong (ADR-0093)
        self_report.runtime.forget()
        self.addCleanup(self_report.runtime.forget)
        self._deploy("failed", "succeeded", said="heavy")
        self.assertIsNone(self._kept()["run-1"].record.code)
        held = [line for line in self_report.runtime.lines()
                if "/batch/import" in line.text]
        self.assertEqual(len(held), 1)
        self.assertIs(held[0].code, StatusCode.WARN)
        for said in ("run-1", "for the record", "bytes"):
            self.assertIn(said, held[0].text)
        # the node is as its own line graded it
        node = self.tree.snapshot("/batch/import")
        assert node is not None
        self.assertIs(node.code, StatusCode.OK)

    def test_a_shown_line_that_carries_the_reading_is_what_stood(self) -> None:
        self._deploy("failed", "succeeded", said="both")
        self.assertEqual(self._kept()["run-1"].record.texts,
                         ("run-1 failed, on the wall",))

    def test_the_readings_table_says_each_runs_sentence(self) -> None:
        self._deploy("failed", "slow", "succeeded")
        page = self.client.get("/history/batch/import").get_data(as_text=True)
        for sentence in ("run-1 failed", "run-2 slow", "run-3 succeeded"):
            self.assertIn(sentence, page)
