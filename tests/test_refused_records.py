"""A record the seam refuses costs its line, not the run (ADR-0093).

The seam stays strict by default — a refusal raises wherever a record is built, so a
check author meets it in the tests — and marks a refused record instead of raising
only inside a run the engine drives. There a line whose record is refused stands and
says so beside a null record, a reading whose record is refused is kept out of the
grading and reported by the engine, and the instance holds a WARN for each.
"""
from __future__ import annotations

import json
import sys
import threading
from collections.abc import Callable, Sequence
from datetime import datetime
from typing import Any
from unittest import TestCase

from little_sister import self_report
from little_sister.checks import Check, CheckError, CheckResult, Entry, Measurement
from little_sister.checks.base import _record_limit
from little_sister.checks.output import FAILURE_CHARS
from little_sister.engine import Engine
from little_sister.reasons import Refusal, lenient_records, slug
from little_sister.series import SeriesKey
from little_sister.status import StatusCode
from little_sister.tree import StatusSnapshot, StatusTree


def _heavy() -> dict[str, Any]:
    """A record past this deployment's `record_limit` by a hundred bytes."""
    return {"blob": "x" * (_record_limit() + 100)}


def _weight(record: object) -> int:
    return len(json.dumps(record).encode("utf-8"))


#: One record per refusal the seam makes (ADR-0082 decision 3), with a word the
#: sentence saying why has to carry.
REFUSED: dict[str, tuple[Callable[[], Any], str]] = {
    "not a mapping": (lambda: ["a", "list"], "mapping"),
    "an object JSON cannot hold": (lambda: {"when": object()}, "JSON"),
    "a float that is not a number": (lambda: {"load": float("nan")}, "JSON"),
    "too heavy": (_heavy, "limit"),
    "a time without its offset": (
        lambda: {"completed": {"at": "2026-09-27T10:00:00"}}, "'completed.at'"),
    "a time past the calendar in UTC": (
        lambda: {"at": "0001-01-01T00:30:00+01:00"}, "'at'"),
}


class StrictByDefaultTests(TestCase):
    """Outside a run the engine drives, the seam raises exactly as it did — which is
    how a check author still meets a refusal in the tests (decision 5)."""

    def test_every_refusal_raises_outside_a_run(self) -> None:
        for name, (record, _) in REFUSED.items():
            with self.subTest(name):
                with self.assertRaises(CheckError):
                    CheckResult(StatusCode.OK, [Entry("a", "t", data=record())])
                with self.assertRaises(CheckError):
                    Measurement(record=record())

    def test_the_message_still_names_the_bytes_and_the_limit(self) -> None:
        with self.assertRaises(CheckError) as caught:
            Measurement(record=_heavy())
        self.assertIn(f"{_weight(_heavy()):,} bytes", str(caught.exception))
        self.assertIn(f"the limit is {_record_limit():,}", str(caught.exception))

    def test_the_seam_is_strict_again_once_a_run_is_over(self) -> None:
        with lenient_records():
            Measurement(record=_heavy())
        with self.assertRaises(CheckError):
            Measurement(record=_heavy())

    def test_a_thread_a_check_starts_itself_is_judged_strictly(self) -> None:
        # the cost decision 5 states: a new thread starts with a context of its
        # own, unless the interpreter starts it from its starter's
        if getattr(sys.flags, "thread_inherit_context", False):
            self.skipTest("this interpreter starts a thread from its starter's "
                          "context")
        caught: list[BaseException] = []

        def build() -> None:
            try:
                Measurement(record=_heavy())
            except CheckError as error:
                caught.append(error)

        with lenient_records():
            worker = threading.Thread(target=build)
            worker.start()
            worker.join(timeout=5)
        self.assertEqual(len(caught), 1)


class LenientSeamTests(TestCase):
    """Inside a run, a refused record is marked rather than raised, and what was
    marked is collected for the engine (decisions 1, 2 and 6)."""

    def test_a_line_whose_record_is_refused_stands_without_it(self) -> None:
        for name, (record, word) in REFUSED.items():
            with self.subTest(name), lenient_records() as refusals:
                result = CheckResult(reason=[
                    Entry("build", "CI: failed", StatusCode.ERROR, subject="ci",
                          data=record())])
                entry, = result.reason_entries
                self.assertEqual(
                    (entry.slug, entry.text, entry.code, entry.subject),
                    ("build", "CI: failed", StatusCode.ERROR, "ci"))
                self.assertIsNone(entry.data)
                self.assertIn(word, entry.refused)
                self.assertEqual(result.stored_code, StatusCode.ERROR)
                self.assertEqual([refusal.why for refusal in refusals],
                                 [entry.refused])

    def test_a_record_that_passes_is_stored_as_before(self) -> None:
        with lenient_records() as refusals:
            result = CheckResult(StatusCode.OK, [
                Entry("a", "t",
                      data={"completed": {"at": "2026-09-27T10:00:00+02:00"}})])
        entry, = result.reason_entries
        self.assertEqual(entry.data, {"completed": {"at": "2026-09-27T08:00:00Z"}})
        self.assertEqual(entry.refused, "")
        self.assertEqual(refusals, [])

    def test_the_sentence_says_the_size_against_the_limit(self) -> None:
        with lenient_records() as refusals:
            reading = Measurement(record=_heavy(), subject="web01")
        self.assertEqual(reading.refused,
                         f"it is {_weight(_heavy()):,} bytes and the limit is "
                         f"{_record_limit():,}")
        self.assertEqual(refusals, [Refusal(reading.refused, _weight(_heavy()),
                                            heavy=True)])

    def test_the_sentence_names_the_field_whose_time_had_no_offset(self) -> None:
        with lenient_records():
            reading = Measurement(record={"completed": {"at": "2026-09-27T10:00:00"}})
        self.assertIn("'completed.at'", reading.refused)
        self.assertIn("offset", reading.refused)

    def test_a_long_value_does_not_make_a_long_sentence(self) -> None:
        with lenient_records():
            reading = Measurement(record={"at": "z" * 1_500})
        self.assertLess(len(reading.refused), 200)

    def test_a_refused_reading_carries_the_engines_failure_record(self) -> None:
        with lenient_records():
            reading = Measurement(record=_heavy(), subject="web01")
        self.assertEqual(reading.subject, "web01")
        self.assertEqual(reading.record,
                         {"error": f"record refused: {reading.refused}"})

    def test_a_record_refused_for_its_time_counts_at_its_size(self) -> None:
        record = {"at": "2026-09-27T10:00:00", "pad": "y" * 50}
        with lenient_records() as refusals:
            Measurement(record=record)
        self.assertEqual(refusals, [Refusal(refusals[0].why, _weight(record),
                                            heavy=False)])

    def test_a_record_that_does_not_serialize_has_no_size(self) -> None:
        with lenient_records() as refusals:
            Measurement(record={"when": object()})
        refusal, = refusals
        self.assertIsNone(refusal.size)
        self.assertFalse(refusal.heavy)

    def test_a_name_the_seam_refuses_still_raises(self) -> None:
        # a subject, an identity or a state names a reading and carries no record:
        # not this decision's (ADR-0093, consequences)
        with lenient_records(), self.assertRaises(CheckError):
            Measurement(record={}, subject="x" * 300)

    def test_a_run_may_collect_into_a_list_it_already_holds(self) -> None:
        # the engine opens the lenient seam twice per run, around measure() and
        # around grade(), and keeps one list of what both marked
        held: list[Refusal] = []
        with lenient_records(held):
            Measurement(record=_heavy())
        with lenient_records(held):
            CheckResult(StatusCode.OK,
                        [Entry("a", "t", data=["no"])])  # type: ignore[arg-type]
        self.assertEqual(len(held), 2)


class _Many(Check):
    """A check that reads several subjects. ``raw`` is ``(subject, record)`` pairs,
    made into readings inside :meth:`measure` — where a type makes them, and where
    the engine's run is lenient — and each passed reading is graded into a line that
    carries it (ADR-0086 decision 2), at ``code`` or at its subject's in ``codes``,
    failures first. ``prose`` grades a declared code over plain lines instead;
    ``line_data`` makes the record a line carries something other than its
    reading."""

    type_name = "many"

    def __init__(self, *, raw: Sequence[tuple[str, Any]], prose: bool = False,
                 code: StatusCode = StatusCode.OK,
                 codes: dict[str, StatusCode] | None = None,
                 line_data: Callable[[Measurement], Any] | None = None,
                 **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.raw = tuple(raw)
        self.prose = prose
        self.code = code
        self.codes = codes or {}
        self.line_data = line_data
        #: What the grading was handed; ``None`` until it is called at all.
        self.graded: tuple[Measurement, ...] | None = None

    def measure(self) -> Sequence[Measurement]:
        return [Measurement(record=record, subject=subject)
                for subject, record in self.raw]

    def grade(self, measurements: Sequence[Measurement],
              now: datetime) -> CheckResult:
        self.graded = tuple(measurements)
        if self.prose:
            return CheckResult(self.code, [f"{reading.subject} was read"
                                           for reading in measurements])
        lines = [
            Entry(slug(reading.subject), f"{reading.subject}: fine",
                  self.codes.get(reading.subject, self.code),
                  subject=reading.subject,
                  data=(self.line_data(reading) if self.line_data is not None
                        else dict(reading.record)))
            for reading in measurements]
        # failures first, as a type orders its lines for the card's budget
        lines.sort(key=lambda line: line.code not in (StatusCode.ERROR,
                                                      StatusCode.WARN))
        return CheckResult(reason=lines)


class EngineTests(TestCase):
    """What the engine does with what the seam marked (decisions 2, 3 and 6)."""

    def setUp(self) -> None:
        self_report.runtime.forget()
        self.addCleanup(self_report.runtime.forget)

    def _run(self, check: Check) -> tuple[Engine, StatusSnapshot]:
        tree = StatusTree()
        engine = Engine([check], tree)
        engine.run_once()
        node = tree.snapshot(check.path)
        assert node is not None
        return engine, node

    def _held(self, path: str) -> list[Entry]:
        return [line for line in self_report.runtime.lines() if path in line.text]

    def test_one_refused_reading_costs_itself_and_the_rest_lands(self) -> None:
        check = _Many(path="/gh", raw=[("octo/api", {"n": 1}), ("octo/web", _heavy()),
                                       ("octo/db", {"n": 3})])
        _, node = self._run(check)
        assert check.graded is not None
        self.assertEqual([reading.subject for reading in check.graded],
                         ["octo/api", "octo/db"])
        lines = {line.slug: line for line in node.reasons}
        self.assertEqual(set(lines), {"octo-api", "octo-db", "refused-octo-web"})
        self.assertEqual((lines["octo-api"].data, lines["octo-db"].data),
                         ({"n": 1}, {"n": 3}))

    def test_the_node_says_which_record_was_refused_and_why(self) -> None:
        check = _Many(path="/gh", raw=[("octo/api", {"n": 1}), ("octo/web", _heavy())])
        _, node = self._run(check)
        line = {line.slug: line for line in node.reasons}["refused-octo-web"]
        self.assertEqual(line.code, StatusCode.WARN)
        self.assertEqual(line.subject, "octo/web")
        self.assertIsNone(line.data)
        self.assertIn("octo/web", line.text)
        self.assertIn(f"{_weight(_heavy()):,} bytes", line.text)
        self.assertEqual(node.reported_code, StatusCode.WARN,
                         "green over a subject nobody could read")

    def test_the_refused_readings_series_keeps_the_failure_record(self) -> None:
        check = _Many(path="/gh", series_keep=5,
                      raw=[("octo/api", {"n": 1}), ("octo/web", _heavy())])
        engine, node = self._run(check)
        line = {line.slug: line for line in node.reasons}["refused-octo-web"]
        kept, = engine.series.window(SeriesKey("many", "/gh", "octo/web"))
        self.assertTrue(kept.data["error"].startswith("record refused: it is "))
        self.assertLessEqual(len(kept.data["error"]), FAILURE_CHARS)
        self.assertEqual((kept.code, kept.texts), (StatusCode.WARN, (line.text,)))
        other, = engine.series.window(SeriesKey("many", "/gh", "octo/api"))
        self.assertEqual((other.data, other.code), ({"n": 1}, StatusCode.OK))

    def test_the_instance_holds_a_warn_naming_the_check_and_the_subject(
            self) -> None:
        self._run(_Many(path="/gh",
                        raw=[("octo/api", {"n": 1}), ("octo/web", _heavy())]))
        held, = self._held("/gh")
        self.assertEqual(held.code, StatusCode.WARN)
        self.assertIn("octo/web", held.text)
        self.assertIn("bytes", held.text)

    def test_a_prose_node_stays_prose_and_its_code_is_raised(self) -> None:
        check = _Many(path="/svc", prose=True,
                      raw=[("octo/api", {"n": 1}), ("octo/web", _heavy())])
        _, node = self._run(check)
        self.assertEqual(node.reported_code, StatusCode.WARN)
        self.assertTrue(all(line.code is None for line in node.reasons))
        self.assertEqual(len(node.reasons), 2)
        self.assertIn("octo/web", node.reasons[0].text,
                      "the reason for the color comes first")

    def test_the_engines_line_follows_the_gradings_failures(self) -> None:
        # a card folds a node's lines under a budget, in order: the grading's own
        # failures stay first, and the refusal stands ahead of the healthy lines
        check = _Many(path="/gh", codes={"octo/db": StatusCode.ERROR},
                      raw=[("octo/api", {"n": 1}), ("octo/web", _heavy()),
                           ("octo/db", {"n": 3})])
        _, node = self._run(check)
        self.assertEqual([line.slug for line in node.reasons],
                         ["octo-db", "refused-octo-web", "octo-api"])

    def test_a_worse_declared_code_is_never_lowered(self) -> None:
        check = _Many(path="/svc", prose=True, code=StatusCode.ERROR,
                      raw=[("octo/api", {"n": 1}), ("octo/web", _heavy())])
        _, node = self._run(check)
        self.assertEqual(node.reported_code, StatusCode.ERROR)

    def test_where_no_reading_passed_the_run_stands_as_one_that_raised(
            self) -> None:
        # every check that reads one object is in this case
        check = _Many(path="/web", subject="https://www.example.org",
                      series_keep=5, raw=[("", _heavy())])
        engine, node = self._run(check)
        self.assertIsNone(check.graded, "there was nothing to grade")
        self.assertEqual(node.reported_code, StatusCode.ERROR)
        reason, = node.reason
        self.assertIn("refused", reason)
        self.assertIn(f"{_weight(_heavy()):,} bytes", reason)
        self.assertNotIn("Traceback", reason)
        assert node.record is not None
        self.assertTrue(node.record["error"].startswith("record refused: "))
        kept, = engine.series.window(SeriesKey("many", "/web",
                                               "https://www.example.org"))
        self.assertEqual((kept.data, kept.code), (node.record, StatusCode.ERROR))

    def test_several_readings_all_refused_name_each(self) -> None:
        check = _Many(path="/gh", raw=[("octo/api", _heavy()),
                                       ("octo/web", ["no", "mapping"])])
        _, node = self._run(check)
        self.assertIsNone(check.graded)
        self.assertEqual(node.reported_code, StatusCode.ERROR)
        self.assertEqual(len(node.reason), 2)
        self.assertIn("octo/api", node.reason[0])
        self.assertIn("mapping", node.reason[1])
        self.assertIsNone(node.record, "several readings: the engine places none")

    def test_a_line_whose_record_is_refused_stands_as_graded(self) -> None:
        check = _Many(path="/gh", raw=[("octo/api", {"n": 1}), ("octo/web", {"n": 2})],
                      line_data=lambda reading: {**reading.record, **_heavy()})
        _, node = self._run(check)
        self.assertEqual([(line.slug, line.text, line.code) for line in node.reasons],
                         [("octo-api", "octo/api: fine", StatusCode.OK),
                          ("octo-web", "octo/web: fine", StatusCode.OK)])
        for line in node.reasons:
            self.assertIsNone(line.data)
            self.assertIn("bytes", line.refused)
        self.assertEqual(node.reported_code, StatusCode.OK,
                         "the lines' claims were made on readings that passed")
        held = self._held("/gh")
        self.assertEqual(len(held), 2)
        self.assertTrue(all(line.code is StatusCode.WARN for line in held))

    def test_system_counts_the_refused_record_it_saw(self) -> None:
        engine, _ = self._run(_Many(
            path="/gh", raw=[("octo/api", {"n": 1}), ("octo/web", _heavy())]))
        info, = engine.info().checks
        self.assertEqual(info.record_bytes, _weight(_heavy()))
        self.assertTrue(info.record_refused)

    def test_a_record_refused_for_its_time_counts_unmarked(self) -> None:
        record = {"at": "2026-09-27T10:00:00", "pad": "y" * 500}
        engine, _ = self._run(_Many(
            path="/gh", raw=[("octo/api", {"n": 1}), ("octo/web", record)]))
        info, = engine.info().checks
        self.assertEqual(info.record_bytes, _weight(record))
        self.assertFalse(info.record_refused)

    def test_a_heavier_record_that_passed_is_the_figure_unmarked(self) -> None:
        passed = {"pad": "p" * (_record_limit() - 20)}
        engine, _ = self._run(_Many(path="/gh",
                                    raw=[("octo/api", passed), ("octo/web", ["no"])]))
        info, = engine.info().checks
        self.assertEqual(info.record_bytes, _weight(passed))
        self.assertFalse(info.record_refused)

    def test_the_seam_is_strict_again_after_a_run(self) -> None:
        self._run(_Many(path="/gh", raw=[("octo/web", _heavy())]))
        with self.assertRaises(CheckError):
            Measurement(record=_heavy())
