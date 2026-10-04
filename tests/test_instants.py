"""An instant, the clock that answers one, and its one spelling —
`little_sister.instants`.

The tests are written from the module's claims, with the values the claims are
about. The clock answers an instant in UTC, and nothing else in the application
asks the system what time it is. What holds an instant keeps it in UTC, and a time
without a zone is refused where it would be held. An instant is spelled in UTC with
a ``Z``, whatever zone it was built in, and a time without a zone is not spelled at
all. A time is read back strictly: one without an offset is refused, in words that
name where it stood. Every module reaches the four, because this one imports none
of the others — and the places that wrote the spelling out themselves spell through
it, as the engine observes a reading, and dates a run, on the clock it was handed.
"""
from __future__ import annotations

import ast
import subprocess
import sys
from collections.abc import Sequence
from datetime import UTC, datetime, timedelta, timezone
from email.message import Message
from inspect import signature
from pathlib import Path
from typing import Any
from unittest import TestCase, mock
from zoneinfo import ZoneInfo

from little_sister import api, instants, reasons
from little_sister import app as app_module
from little_sister.checks import Check, CheckResult, Measurement
from little_sister.engine import Engine
from little_sister.fetch import retry_after
from little_sister.instance import resolve
from little_sister.series import MemoryStore, Placed, SeriesKey, SeriesRecord
from little_sister.status import StatusCode
from little_sister.tree import StatusTree
from tests.running import subprocess_env

#: One instant, which three clocks show three ways: 12:51:48 in Berlin, 06:51:48
#: four hours behind UTC, 16:36:48 in Kathmandu.
SEEN = datetime(2026, 10, 4, 10, 51, 48, tzinfo=UTC)
SPELLED = "2026-10-04T10:51:48Z"

KEY = SeriesKey("reader", "/web", "web01")

#: The application's modules: the library's package without the release tooling,
#: which is no part of what an instance runs.
PACKAGE = Path(instants.__file__).resolve().parent
MODULES = sorted(path for path in PACKAGE.rglob("*.py")
                 if "release" not in path.relative_to(PACKAGE).parts)


#: The ways ``datetime`` and ``date`` are asked what time it is.
_ASKED = {("datetime", "now"), ("datetime", "utcnow"), ("datetime", "today"),
          ("date", "today")}


def _clock_reads(source: str) -> list[int]:
    """The lines of ``source`` that ask the system what time it is."""
    return [node.lineno for node in ast.walk(ast.parse(source))
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and (ast.unparse(node.func.value).split(".")[-1],
                 node.func.attr) in _ASKED]


class ClockTests(TestCase):
    """`now` — the clock, as an instant in UTC."""

    def test_the_clock_answers_an_instant_in_utc(self) -> None:
        before = datetime.now(UTC)
        moment = instants.now()
        after = datetime.now(UTC)
        self.assertIs(moment.tzinfo, UTC)
        self.assertLessEqual(before, moment)
        self.assertLessEqual(moment, after)

    def test_nothing_else_asks_the_system_what_time_it_is(self) -> None:
        # the finder finds one where one is — the clock itself — and each way of
        # asking, with a zone and without
        own = Path(instants.__file__).read_text(encoding="utf-8")
        self.assertEqual(len(_clock_reads(own)), 1)
        for asked in ("datetime.now()", "datetime.now(UTC)",
                      "datetime.datetime.now(tz=zone)", "datetime.utcnow()",
                      "datetime.today()", "date.today()"):
            with self.subTest(asked=asked):
                self.assertEqual(_clock_reads(f"moment = {asked}"), [1])
        self.assertEqual(_clock_reads("moment = instants.now()"), [])
        self.assertGreater(len(MODULES), 50)
        asking = {str(path.relative_to(PACKAGE)): lines for path in MODULES
                  if (lines := _clock_reads(path.read_text(encoding="utf-8")))}
        self.assertEqual(list(asking), ["instants.py"], asking)


class HoldingTests(TestCase):
    """`utc` — an instant as what holds one keeps it."""

    def test_an_instant_is_held_in_utc_whatever_zone_it_was_built_in(self) -> None:
        for built in (SEEN, SEEN.astimezone(ZoneInfo("Europe/Berlin")),
                      SEEN.astimezone(timezone(timedelta(hours=-4))),
                      SEEN.astimezone(ZoneInfo("Asia/Kathmandu"))):
            with self.subTest(offset=built.utcoffset()):
                held = instants.utc(built, "a time")
                self.assertEqual(held, SEEN)
                self.assertIs(held.tzinfo, UTC)

    def test_a_time_without_a_zone_is_refused_naming_where_it_was_to_stand(
            self) -> None:
        bare = SEEN.astimezone(ZoneInfo("Europe/Berlin")).replace(tzinfo=None)
        with self.assertRaises(ValueError) as refused:
            instants.utc(bare, "an event's timestamp")
        self.assertEqual(str(refused.exception),
                         "an event's timestamp is a time without a zone, and no "
                         "instant: '2026-10-04T12:51:48'")


class StampTests(TestCase):
    """`stamp` — an instant as a file and the API spell it."""

    def test_an_instant_is_spelled_in_utc_with_a_z(self) -> None:
        self.assertEqual(instants.stamp(SEEN), SPELLED)
        self.assertEqual(instants.stamp(SEEN + timedelta(milliseconds=500)),
                         "2026-10-04T10:51:48.500000Z")

    def test_whatever_zone_it_was_built_in(self) -> None:
        for built in (SEEN.astimezone(ZoneInfo("Europe/Berlin")),
                      SEEN.astimezone(timezone(timedelta(hours=-4))),
                      SEEN.astimezone(ZoneInfo("Asia/Kathmandu"))):
            with self.subTest(offset=built.utcoffset()):
                self.assertNotEqual(built.utcoffset(), timedelta(0))
                self.assertEqual(instants.stamp(built), SPELLED)

    def test_a_time_without_a_zone_is_not_spelled(self) -> None:
        # which instant it is depends on whose clock wrote it, and it does not say
        with self.assertRaises(ValueError) as refused:
            instants.stamp(SEEN.astimezone(ZoneInfo("Europe/Berlin")).replace(
                tzinfo=None))
        self.assertIn("2026-10-04T12:51:48", str(refused.exception))


class InstantTests(TestCase):
    """`instant` — one time a file holds, read strictly."""

    def test_a_spelled_instant_reads_back_in_utc(self) -> None:
        moment = instants.instant(SPELLED, "a time")
        self.assertEqual(moment, SEEN)
        self.assertIs(moment.tzinfo, UTC)

    def test_an_offset_is_read_into_utc(self) -> None:
        for text in ("2026-10-04T12:51:48+02:00", "2026-10-04T06:51:48-04:00",
                     "2026-10-04T16:36:48+05:45"):
            with self.subTest(text=text):
                moment = instants.instant(text, "a time")
                self.assertEqual(moment, SEEN)
                self.assertIs(moment.tzinfo, UTC)

    def test_a_time_without_an_offset_is_refused_naming_where_it_stood(self) -> None:
        with self.assertRaises(ValueError) as refused:
            instants.instant("2026-10-04T12:51:48", "a node's since")
        self.assertEqual(str(refused.exception),
                         "a node's since is not an instant with an offset: "
                         "'2026-10-04T12:51:48'")

    def test_what_is_no_time_at_all_is_refused_the_same_way(self) -> None:
        for value in (None, 1759575108, "yesterday", "", SEEN):
            with self.subTest(value=value):
                with self.assertRaises(ValueError) as refused:
                    instants.instant(value, "a pin's expiry")
                self.assertIn("a pin's expiry is not an instant with an offset",
                              str(refused.exception))

    def test_an_offset_that_carries_it_past_the_calendar_is_refused(self) -> None:
        # the first hour of the year 1 at +01:00 is the year 0 in UTC: converting it
        # raises OverflowError, which nothing that reads a file catches
        with self.assertRaises(ValueError) as refused:
            instants.instant("0001-01-01T00:00:00+01:00", "a time")
        self.assertIn("a time lies outside the years 1 to 9999 once it is read in "
                      "UTC", str(refused.exception))

    def test_what_was_spelled_reads_back_as_the_same_instant(self) -> None:
        for moment in (SEEN, SEEN + timedelta(microseconds=1),
                       SEEN.astimezone(ZoneInfo("Europe/Berlin")),
                       datetime(1, 1, 1, tzinfo=UTC),
                       datetime(9999, 12, 31, 23, 59, 59, 999999, tzinfo=UTC)):
            with self.subTest(moment=moment):
                self.assertEqual(
                    instants.instant(instants.stamp(moment), "a time"), moment)


class ReachTests(TestCase):
    """Every module reaches it, because it imports none of them."""

    def test_importing_it_loads_nothing_else_of_the_library(self) -> None:
        done = subprocess.run(
            [sys.executable, "-c",
             "import sys, little_sister.instants; "
             "print(' '.join(sorted(name for name in sys.modules "
             "if name.split('.')[0] == 'little_sister')))"],
            env=subprocess_env(), capture_output=True, text=True, timeout=60)
        self.assertEqual(done.stdout.split(),
                         ["little_sister", "little_sister.instants"],
                         done.stderr[-3000:])


class OneSpellingTests(TestCase):
    """The places that wrote the spelling out themselves spell through `stamp`, and
    the series' file is read through `instant`."""

    ONE = "as the one function spells it"

    def setUp(self) -> None:
        spelling = mock.patch.object(instants, "stamp", return_value=self.ONE)
        self.stamp = spelling.start()
        self.addCleanup(spelling.stop)

    def test_the_series_file(self) -> None:
        store = MemoryStore()
        store.add(KEY, SeriesRecord({}, SEEN), keep=5)
        record, = store.payload()["series"][0]["records"]
        self.assertEqual(record["observed_at"], self.ONE)
        self.stamp.assert_called_with(SEEN)

    def test_the_api_s_envelope_and_a_node_s_times_in_it(self) -> None:
        tree = StatusTree()
        tree.upsert("/db", StatusCode.OK)
        snapshot = tree.snapshot("/db")
        assert snapshot is not None
        envelope = api.status_envelope(snapshot, now=SEEN)
        self.assertEqual(envelope["generated_at"], self.ONE)
        self.assertEqual(envelope["status"]["run"]["observed_at"], self.ONE)

    def test_a_reading_s_row_on_a_page(self) -> None:
        row = app_module._reading_row(Placed(SeriesRecord({}, SEEN), SEEN))
        self.assertEqual(row.stored, self.ONE)
        self.stamp.assert_called_with(SEEN)

    def test_the_seam_a_record_s_time_passes(self) -> None:
        record = reasons.normalize_record({"at": "2026-10-04T12:51:48+02:00"},
                                          limit=4096)
        self.assertEqual(record["at"], self.ONE)
        self.stamp.assert_called_with(SEEN)

    def test_the_series_file_is_read_through_the_one_reader(self) -> None:
        payload = {"series": [{
            "type": "reader", "mount": "/web", "subject": "web01",
            "records": [{"data": {}, "observed_at": SPELLED, "identity": "",
                         "code": None, "texts": []}]}]}
        reading = mock.patch.object(
            instants, "instant", side_effect=ValueError("as the one function reads it"))
        with reading, self.assertRaises(ValueError) as refused:
            MemoryStore().restore(payload)
        self.assertEqual(str(refused.exception), "as the one function reads it")


class OneClockTests(TestCase):
    """What reads the time of day reads it from `now`: the instant an envelope was
    generated at, a wait measured against this machine's clock, the moment an
    instance began."""

    def setUp(self) -> None:
        clock = mock.patch.object(instants, "now", return_value=SEEN)
        clock.start()
        self.addCleanup(clock.stop)

    def test_an_envelope_is_generated_at_the_clock_s_instant(self) -> None:
        tree = StatusTree()
        tree.upsert("/db", StatusCode.OK)
        snapshot = tree.snapshot("/db")
        assert snapshot is not None
        self.assertEqual(api.status_envelope(snapshot)["generated_at"], SPELLED)

    def test_a_wait_until_a_date_is_measured_from_it(self) -> None:
        headers = Message()
        headers["Retry-After"] = "Sun, 04 Oct 2026 10:53:48 GMT"
        self.assertEqual(retry_after(headers), 120.0)

    def test_an_instance_began_at_it(self) -> None:
        self.assertEqual(resolve().started, "20261004T105148Z")

    def test_a_page_reads_its_now_from_it(self) -> None:
        self.assertEqual(app_module._now(), SEEN)


class _Reader(Check):
    """A check that reads one number, or fails to, and remembers the instant its
    grading was handed."""

    type_name = "reader"

    def __init__(self, *, raises: Exception | None = None, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.raises = raises
        self.graded_at: datetime | None = None

    def measure(self) -> Sequence[Measurement]:
        if self.raises is not None:
            raise self.raises
        return (Measurement(record={"load": 0.4}),)

    def grade(self, measurements: Sequence[Measurement],
              now: datetime) -> CheckResult:
        self.graded_at = now
        return CheckResult(StatusCode.OK)


class EngineClockTests(TestCase):
    """The engine's clock is the one clock unless it was handed another, and a test
    holds it still by handing one in: a reading is observed on it, and a run begins
    and the next one is due on it."""

    def _run(self, check: Check) -> SeriesRecord:
        engine = Engine([check], StatusTree(), wall=lambda: SEEN)
        engine.run_once()
        record, = engine.series.window(KEY)
        return record

    def test_the_engine_s_clock_defaults_to_the_one(self) -> None:
        self.assertIs(signature(Engine.__init__).parameters["wall"].default,
                      instants.now)

    def test_a_reading_is_observed_at_the_instant_of_the_clock_handed_in(self) -> None:
        check = _Reader(path="/web", subject="web01", series_keep=5)
        self.assertEqual(self._run(check).observed_at, SEEN)
        self.assertEqual(check.graded_at, SEEN)

    def test_and_so_is_the_record_of_a_run_that_read_nothing(self) -> None:
        check = _Reader(path="/web", subject="web01", series_keep=5,
                        raises=RuntimeError("the host did not answer"))
        record = self._run(check)
        self.assertIn("error", record.data)
        self.assertEqual(record.observed_at, SEEN)

    def test_a_run_began_and_the_next_is_due_by_the_clock_handed_in(self) -> None:
        tree = StatusTree()
        engine = Engine([_Reader(path="/web", frequency_seconds=300)], tree,
                        wall=lambda: SEEN)
        before, = engine.info().checks
        self.assertIsNone(before.last_run_at)
        self.assertEqual(before.next_run_at,
                         SEEN + timedelta(seconds=before.next_in_seconds))
        engine.run_once()
        after, = engine.info().checks
        self.assertEqual(after.last_run_at, SEEN)
        self.assertIs(after.last_run_at.tzinfo, UTC)

    def test_the_slot_a_run_arms_is_an_instant_of_that_clock(self) -> None:
        tree = StatusTree()
        engine = Engine([_Reader(path="/web", frequency_seconds=300)], tree,
                        wall=lambda: SEEN.astimezone(ZoneInfo("Asia/Kathmandu")))
        item, = engine._scheduled
        engine._execute(item)
        node = tree.snapshot("/web")
        assert node is not None and node.run is not None
        due = node.run.next_run_at
        assert due is not None
        self.assertIs(due.tzinfo, UTC)
        self.assertLessEqual(SEEN, due)
        self.assertLessEqual(due, SEEN + timedelta(seconds=300))

    def test_a_clock_that_answers_a_time_without_a_zone_is_refused(self) -> None:
        bare = SEEN.replace(tzinfo=None)
        engine = Engine([_Reader(path="/web")], StatusTree(), wall=lambda: bare)
        with self.assertRaises(ValueError) as refused:
            engine.info()
        self.assertIn("the engine's wall clock is a time without a zone",
                      str(refused.exception))
