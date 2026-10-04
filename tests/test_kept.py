"""A measurement reads what its check kept (ADR-0113), read against that record's
sentences: ``kept(subject)`` hands the measuring half the window of one of its own
subjects as the store holds it, as copies; it answers nothing where the check keeps
no series or runs outside an engine; and it answers only while its own check is
measuring.

The estate is a check of job names. Its source lists every run of a name, each poll
reads all of them, and before it asks its source the check asks what it kept.
"""
from __future__ import annotations

import threading
from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from typing import Any
from unittest import TestCase

from little_sister.checks.base import Check, CheckError, CheckResult, Measurement
from little_sister.engine import Engine
from little_sister.reasons import Entry
from little_sister.series import MemoryStore, SeriesKey, SeriesRecord
from little_sister.status import StatusCode
from little_sister.tree import StatusTree

T0 = datetime(2026, 10, 3, 2, 0, tzinfo=UTC)


class _Runs(Check):
    """Reads every run of each of its job names, after asking what it kept of them."""

    type_name = "kept-runs"

    def __init__(self, *, names: Sequence[str] = ("import",), read_in: str = "measure",
                 **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.names = tuple(names)
        #: Where the type asks what it kept: in ``measure``, in ``grade``, on a
        #: ``thread`` it starts while measuring, of ``another`` check, or ``never``.
        self.read_in = read_in
        self.other: Check | None = None
        #: Whether the type writes to what it was handed.
        self.spoil = False
        #: Whether a poll hands back the newest run of a name alone, as a type does
        #: that asks its source from where its history ends.
        self.newest_alone = False
        self.listed: dict[str, list[str]] = {name: [] for name in self.names}
        #: What ``kept()`` answered on each poll, by job name.
        self.seen: list[dict[str, tuple[SeriesRecord, ...]]] = []
        #: What a read outside the measuring half raised.
        self.refused: list[CheckError] = []

    def ran(self, name: str = "import") -> None:
        """One more run of the name, an hour after its last."""
        self.listed[name].append(f"run-{len(self.listed[name]) + 1}")

    def _ask(self) -> dict[str, tuple[SeriesRecord, ...]]:
        return {name: self.kept(f"job/{name}") for name in self.names}

    def measure(self) -> Sequence[Measurement]:
        if self.read_in == "measure":
            answer = self._ask()
            self.seen.append(answer)
            if self.spoil:
                for records in answer.values():
                    for record in records:
                        record.data["run"] = "spoiled"  # type: ignore[index]
                        record.data["host"]["name"] = "spoiled"
        elif self.read_in == "thread":
            def ask() -> None:
                try:
                    self._ask()
                except CheckError as error:
                    self.refused.append(error)
            thread = threading.Thread(target=ask)
            thread.start()
            thread.join()
        elif self.read_in == "another":
            assert self.other is not None
            try:
                self.other.kept("job/import")
            except CheckError as error:
                self.refused.append(error)
        return [Measurement(
            record={"run": run, "host": {"name": "a"},
                    "at": (T0 + timedelta(hours=index)).isoformat()},
            subject=f"job/{name}", identity=run)
            for name in self.names
            for index, run in enumerate(self.listed[name])
            if not self.newest_alone or index == len(self.listed[name]) - 1]

    def grade(self, measurements: Sequence[Measurement],
              now: datetime) -> CheckResult:
        if self.read_in == "grade":
            self.kept("job/import")
        return CheckResult(reason=[
            Entry(f"{reading.subject}-{reading.record['run']}",
                  f"{reading.subject} {reading.record['run']} succeeded",
                  code=StatusCode.OK, subject=reading.subject,
                  data=dict(reading.record))
            for reading in measurements])


class _Host(Check):
    """Reads one object, the one it declares, and asks what it kept of it."""

    type_name = "kept-host"

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.seen: list[tuple[tuple[SeriesRecord, ...], tuple[SeriesRecord, ...]]] = []
        self.polls = 0

    def measure(self) -> Measurement:
        self.seen.append((self.kept(), self.kept(self.subject)))
        self.polls += 1
        return Measurement(record={"load": self.polls})

    def grade(self, measurements: Sequence[Measurement],
              now: datetime) -> CheckResult:
        return CheckResult(StatusCode.OK, [f"load {measurements[0].record['load']}"])


def _polled(check: Check, *runs: str, store: MemoryStore | None = None) -> Engine:
    """An engine of ``check`` alone that polled once for each of ``runs``, each poll
    after one more run of that name."""
    engine = Engine([check], StatusTree(), series=store)
    for name in runs:
        assert isinstance(check, _Runs)
        check.ran(name)
        engine.run_once()
    return engine


class KeptTests(TestCase):
    """What the measuring half is handed."""

    def test_the_first_poll_is_answered_nothing(self) -> None:
        check = _Runs(path="/batch", series_keep=5)
        _polled(check, "import")
        self.assertEqual(check.seen, [{"import": ()}])

    def test_a_poll_reads_what_the_polls_before_it_kept(self) -> None:
        # of the subject it names, whatever object the check declares
        check = _Runs(path="/batch", subject="queue/live", series_keep=5)
        before = datetime.now(UTC)
        _polled(check, "import", "import")
        (record,) = check.seen[1]["import"]
        self.assertEqual(record.data["run"], "run-1")
        self.assertEqual(record.identity, "run-1")
        self.assertEqual(record.state, "")
        # its own time, and the moment it was observed
        self.assertEqual(record.at, T0)
        self.assertGreaterEqual(record.observed_at, before)
        self.assertLessEqual(record.observed_at, datetime.now(UTC))
        # and the code and the sentence that stood where it landed
        self.assertIs(record.code, StatusCode.OK)
        self.assertEqual(record.texts, ("job/import run-1 succeeded",))

    def test_the_window_is_the_stores_oldest_first(self) -> None:
        check = _Runs(path="/batch", series_keep=2)
        engine = _polled(check, "import", "import", "import", "import")
        # the fourth poll reads what the third kept: of three runs, the newest two
        self.assertEqual([record.identity for record in check.seen[3]["import"]],
                         ["run-2", "run-3"])
        key = SeriesKey("kept-runs", "/batch", "job/import")
        self.assertEqual([record.identity for record in engine.series.window(key)],
                         ["run-3", "run-4"])

    def test_each_subject_has_its_own_window(self) -> None:
        check = _Runs(path="/batch", names=("import", "export"), series_keep=5)
        _polled(check, "import", "export", "import")
        self.assertEqual({name: [record.identity for record in records]
                          for name, records in check.seen[2].items()},
                         {"import": ["run-1"], "export": ["run-1"]})

    def test_without_an_argument_it_reads_the_object_the_check_declares(self) -> None:
        check = _Host(path="/hosts/a", subject="host/a", series_keep=3)
        engine = Engine([check], StatusTree())
        engine.run_once()
        engine.run_once()
        engine.run_once()
        declared, named = check.seen[2]
        self.assertEqual([record.data["load"] for record in declared], [1, 2])
        self.assertEqual(declared, named)

    def test_a_check_that_declares_no_object_is_answered_nothing_for_none(self) -> None:
        check = _Host(path="/hosts/a", series_keep=3)
        engine = Engine([check], StatusTree())
        engine.run_once()
        engine.run_once()
        self.assertEqual(check.seen[1], ((), ()))

    def test_what_it_is_handed_is_a_copy(self) -> None:
        check = _Runs(path="/batch", series_keep=5)
        # a poll hands back its newest run alone, so an older record is kept as it
        # was kept and no later reading writes over what the type did to its copy
        check.newest_alone = True
        check.spoil = True
        engine = _polled(check, "import", "import", "import")
        key = SeriesKey("kept-runs", "/batch", "job/import")
        kept = engine.series.window(key)
        self.assertEqual([record.data["run"] for record in kept],
                         ["run-1", "run-2", "run-3"])
        self.assertEqual([record.data["host"] for record in kept], [{"name": "a"}] * 3)
        # and the next poll is handed what is kept, not what the last one wrote
        self.assertEqual(check.seen[2]["import"][0].identity, "run-1")

    def test_a_check_reads_no_other_checks_series(self) -> None:
        class _Other(_Runs):
            type_name = "kept-other"

        mine = _Runs(path="/batch", series_keep=5)
        beside = _Runs(path="/nightly", series_keep=5)
        other = _Other(path="/other", series_keep=5)
        engine = Engine([mine, beside, other], StatusTree())
        mine.ran()
        mine.ran()
        other.ran()
        engine.run_once()
        engine.run_once()
        # one subject, three series: each check is handed its own and no other
        self.assertEqual([r.identity for r in mine.seen[1]["import"]],
                         ["run-1", "run-2"])
        self.assertEqual(beside.seen[1]["import"], ())
        self.assertEqual([r.identity for r in other.seen[1]["import"]], ["run-1"])

    def test_after_a_restart_it_reads_what_the_state_file_restored(self) -> None:
        first = _Runs(path="/batch", series_keep=5)
        engine = _polled(first, "import", "import")
        restored = MemoryStore()
        restored.restore(engine.series.payload())
        again = _Runs(path="/batch", series_keep=5)
        again.listed = {"import": list(first.listed["import"])}
        _polled(again, "import", store=restored)
        self.assertEqual([record.identity for record in again.seen[0]["import"]],
                         ["run-1", "run-2"])
        self.assertEqual(again.seen[0]["import"][0].texts,
                         ("job/import run-1 succeeded",))

    def test_a_check_that_keeps_one_reading_reads_it(self) -> None:
        check = _Runs(path="/batch", series_keep=1)
        _polled(check, "import", "import", "import")
        self.assertEqual([[record.identity for record in poll["import"]]
                          for poll in check.seen], [[], ["run-1"], ["run-2"]])

    def test_a_check_that_keeps_nothing_is_answered_nothing(self) -> None:
        check = _Runs(path="/batch")
        _polled(check, "import", "import")
        self.assertEqual(check.seen, [{"import": ()}, {"import": ()}])

    def test_a_check_that_keeps_nothing_is_not_handed_what_a_file_left(self) -> None:
        first = _Runs(path="/batch", series_keep=5)
        engine = _polled(first, "import", "import")
        restored = MemoryStore()
        restored.restore(engine.series.payload())
        # the deployment keeps this check's series no longer; the file still has it
        again = _Runs(path="/batch")
        _polled(again, "import", store=restored)
        self.assertEqual(again.seen, [{"import": ()}])

    def test_outside_an_engine_it_is_answered_nothing(self) -> None:
        check = _Runs(path="/batch", series_keep=5)
        check.ran()
        self.assertEqual(check.kept("job/import"), ())
        self.assertEqual(len(check.measure()), 1)
        self.assertEqual(check.seen, [{"import": ()}])


    def test_a_reader_a_test_binds_answers_the_type_under_test(self) -> None:
        # a type's own test stands in the engine's place: it binds what the type is
        # to find, and calls the measuring half itself
        check = _Runs(path="/batch", subject="queue/live")
        record = SeriesRecord({"run": "run-1", "at": T0.isoformat()}, T0, "run-1")
        asked: list[str] = []

        def reader(subject: str) -> tuple[SeriesRecord, ...]:
            asked.append(subject)
            return (record,)

        check.bind_kept(reader)
        check.ran()
        self.assertEqual(len(check.measure()), 1)
        self.assertEqual(check.seen, [{"import": (record,)}])
        # and with no argument it is asked for the object the check declares
        self.assertEqual(check.kept(), (record,))
        self.assertEqual(asked, ["job/import", "queue/live"])


class GuardTests(TestCase):
    """What an engine binds answers only while its own check is measuring."""

    def _node(self, engine: Engine, path: str = "/batch") -> Any:
        node = engine._tree.snapshot(path)
        assert node is not None
        return node

    def test_the_grading_cannot_read_it(self) -> None:
        check = _Runs(path="/batch", series_keep=5, read_in="grade")
        with self.assertLogs("little_sister", level="ERROR"):
            engine = _polled(check, "import")
        node = self._node(engine)
        self.assertIs(node.code, StatusCode.ERROR)
        # the refusal is the node's first line; the trace, where one is shown, follows
        said = node.reasons[0].text
        self.assertIn("kept()", said)
        self.assertIn("measure()", said)
        self.assertIn("ADR-0086", said)

    def test_a_grading_of_a_check_that_keeps_nothing_cannot_read_it_either(
            self) -> None:
        check = _Runs(path="/batch", read_in="grade")
        with self.assertLogs("little_sister", level="ERROR"):
            engine = _polled(check, "import")
        self.assertIs(self._node(engine).code, StatusCode.ERROR)

    def test_outside_a_run_a_check_of_an_engine_is_refused(self) -> None:
        check = _Runs(path="/batch", series_keep=5)
        _polled(check, "import")
        with self.assertRaises(CheckError) as refused:
            check.kept("job/import")
        self.assertIn("measure()", str(refused.exception))

    def test_a_thread_the_check_starts_is_refused(self) -> None:
        check = _Runs(path="/batch", series_keep=5, read_in="thread")
        engine = _polled(check, "import")
        self.assertEqual(len(check.refused), 1)
        self.assertIs(self._node(engine).code, StatusCode.OK)

    def test_another_checks_measuring_does_not_open_it(self) -> None:
        asked = _Runs(path="/nightly", series_keep=5, read_in="never")
        asking = _Runs(path="/batch", series_keep=5, read_in="another")
        asking.other = asked
        engine = Engine([asked, asking], StatusTree())
        asked.ran()
        asking.ran()
        engine.run_once()
        engine.run_once()
        self.assertEqual(len(asking.refused), 2)

    def test_a_measurement_that_raises_closes_it(self) -> None:
        class _Breaks(_Runs):
            type_name = "kept-breaks"

            def measure(self) -> Sequence[Measurement]:
                self.kept("job/import")
                raise RuntimeError("the source is down")

        check = _Breaks(path="/batch", series_keep=5)
        engine = Engine([check], StatusTree())
        with self.assertLogs("little_sister", level="ERROR"):
            engine.run_once()
        with self.assertRaises(CheckError):
            check.kept("job/import")

    def test_the_next_poll_reads_again_after_a_refusal(self) -> None:
        check = _Runs(path="/batch", series_keep=5, read_in="grade")
        with self.assertLogs("little_sister", level="ERROR"):
            engine = _polled(check, "import")
        check.read_in = "measure"
        check.ran()
        engine.run_once()
        self.assertIs(self._node(engine).code, StatusCode.OK)
        # the poll whose grading was refused had measured, and its reading was kept
        self.assertEqual([[record.identity for record in poll["import"]]
                          for poll in check.seen], [["run-1"]])
