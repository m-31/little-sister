"""The series (ADR-0087): a subject's readings over time, kept by the check that
took them — in memory first, the last *n* of each, oldest out.

Each class holds one part of the record to its own sentence: the count a
deployment writes in a check's YAML, for every type; the key a reading's series is
found by; the identity that keeps one event in it once, and the state that keeps
one spell; the two clocks and the order they give; and the engine writing each
run's readings through all of it.
"""
from __future__ import annotations

import itertools
import json
import tempfile
from collections.abc import Callable, Sequence
from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from unittest import TestCase

import yaml

from little_sister import self_report
from little_sister.checks import (
    CHECK_TYPES,
    Check,
    CheckError,
    CheckResult,
    Entry,
    Measurement,
)
from little_sister.engine import Engine
from little_sister.reasons import slug
from little_sister.series import MemoryStore, Placed, SeriesKey, SeriesRecord
from little_sister.status import StatusCode, worst_of
from little_sister.tree import StatusTree

TEMPLATES = Path(__file__).resolve().parent.parent / "config" / "checks" / "examples"

#: The line every template carries, commented out, and what it reads as once a
#: deployment takes the comment off.
TEMPLATE_LINE = "# series_keep: 60"

T0 = datetime(2026, 9, 20, 12, 0, tzinfo=UTC)


def _at(minutes: int) -> datetime:
    return T0 + timedelta(minutes=minutes)


def _record(minutes: int, identity: str = "", **data: Any) -> SeriesRecord:
    """A record observed ``minutes`` after T0."""
    return SeriesRecord(data, _at(minutes), identity)


class _Probe(Check):
    """A check whose YAML is only the common fields."""

    def measure(self) -> Sequence[Measurement]:
        return ()

    def grade(self, measurements: Sequence[Measurement],
              now: datetime) -> CheckResult:
        return CheckResult(StatusCode.OK)


class SeriesKeepFieldTests(TestCase):
    """`series_keep` is a common field of the check's own YAML beside `frequency`
    and `timeout`, parsed for every type, default 0 — no series."""

    def _probe(self, **extra: object) -> Check:
        return _Probe.from_config({"path": "/svc", **extra}, Path("."))

    def test_absent_is_zero_which_is_no_series(self) -> None:
        self.assertEqual(self._probe().series_keep, 0)

    def test_a_count_is_read_as_a_count(self) -> None:
        self.assertEqual(self._probe(series_keep=60).series_keep, 60)
        self.assertEqual(self._probe(series_keep="200").series_keep, 200)
        self.assertEqual(self._probe(series_keep=0).series_keep, 0)

    def test_junk_fails_the_load(self) -> None:
        for junk in (-1, "many", True, 2.5, ""):
            with self.subTest(series_keep=junk), self.assertRaises(CheckError):
                self._probe(series_keep=junk)

    def test_every_template_carries_the_line_commented_out(self) -> None:
        for template in sorted(TEMPLATES.glob("*.yaml")):
            with self.subTest(template=template.name):
                lines = template.read_text(encoding="utf-8").splitlines()
                line, = (line for line in lines if line.startswith(TEMPLATE_LINE))
                comment = line[len(TEMPLATE_LINE):].strip()
                self.assertTrue(comment.startswith("# "), line)
                self.assertIn("default 0", comment)

    def test_every_built_in_type_has_a_template(self) -> None:
        # the sentence is about every type, so a type without a template is a
        # type nobody was shown the line for
        shipped = {yaml.safe_load(template.read_text(encoding="utf-8"))["type"]
                   for template in TEMPLATES.glob("*.yaml")}
        built_in = {name for name, cls in CHECK_TYPES.items()
                    if cls.__module__.startswith("little_sister.")}
        self.assertEqual(shipped, built_in)

    def test_every_type_reads_it_from_its_own_yaml(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            (base / "my-check.sh").write_text("true\n")   # ssh-script's script
            for template in sorted(TEMPLATES.glob("*.yaml")):
                text = template.read_text(encoding="utf-8")
                for body, expected in ((text, 0),
                                       (text.replace(TEMPLATE_LINE,
                                                     TEMPLATE_LINE[2:]), 60)):
                    config = yaml.safe_load(body)
                    with self.subTest(template=template.name, expected=expected):
                        check = CHECK_TYPES[config["type"]].from_config(config, base)
                        self.assertEqual(check.series_keep, expected)


class MeasurementIdentityTests(TestCase):
    """`Measurement` gains an optional identity beside its subject."""

    def test_empty_by_default(self) -> None:
        self.assertEqual(Measurement(record={"a": 1}, subject="s").identity, "")

    def test_it_travels_like_a_subject(self) -> None:
        self.assertEqual(Measurement(record={}, identity="run-41").identity,
                         "run-41")
        for bad in ("x" * 201, "run\n41"):
            with self.subTest(identity=bad[:12]), self.assertRaises(CheckError):
                Measurement(record={}, subject="s", identity=bad)


class MeasurementStateTests(TestCase):
    """`Measurement` gains an optional state beside its identity, and names one of
    the two at most."""

    def test_empty_by_default(self) -> None:
        self.assertEqual(Measurement(record={"a": 1}, subject="s").state, "")

    def test_it_travels_like_an_identity(self) -> None:
        self.assertEqual(Measurement(record={}, state="disabled_manually").state,
                         "disabled_manually")
        for bad in ("x" * 201, "disabled\nmanually"):
            with self.subTest(state=bad[:12]), self.assertRaises(CheckError):
                Measurement(record={}, subject="s", state=bad)

    def test_an_event_or_a_state_never_both(self) -> None:
        with self.assertRaises(CheckError):
            Measurement(record={}, subject="s", identity="run-41", state="active")

    def test_a_kept_record_is_of_an_event_or_a_state_never_both(self) -> None:
        with self.assertRaises(ValueError):
            SeriesRecord({}, T0, "run-41", state="active")


class RetentionTests(TestCase):
    """The memory tier keeps the last *n* records of a series, oldest out."""

    KEY = SeriesKey("http", "/website", "https://example.com")

    def test_the_oldest_goes_at_the_count(self) -> None:
        store = MemoryStore()
        for minute in range(5):
            store.add(self.KEY, _record(minute, response_ms=minute), keep=3)
        self.assertEqual([record.data["response_ms"]
                          for record in store.window(self.KEY)], [2, 3, 4])

    def test_up_to_the_count_nothing_goes(self) -> None:
        store = MemoryStore()
        for minute in range(3):
            store.add(self.KEY, _record(minute, response_ms=minute), keep=3)
        self.assertEqual(len(store.window(self.KEY)), 3)

    def test_a_count_below_one_is_no_series(self) -> None:
        store = MemoryStore()
        for keep in (0, -1):
            with self.subTest(keep=keep), self.assertRaises(ValueError):
                store.add(self.KEY, _record(0), keep=keep)
        self.assertEqual(store.window(self.KEY), ())

    def test_an_unknown_series_is_an_empty_window(self) -> None:
        self.assertEqual(MemoryStore().window(self.KEY), ())

    def test_a_sweep_holds_each_series_to_its_count_now(self) -> None:
        store = MemoryStore()
        other = SeriesKey("file", "/nightly", "/srv/app.done")
        for minute in range(4):
            store.add(self.KEY, _record(minute, n=minute), keep=4)
            store.add(other, _record(minute, n=minute), keep=4)
        swept = store.sweep(lambda key: 2 if key == self.KEY else 0)
        self.assertEqual([r.data["n"] for r in store.window(self.KEY)], [2, 3])
        self.assertEqual(store.window(other), ())
        self.assertEqual((swept.trimmed, swept.dropped), (2, (other,)))
        self.assertEqual(swept.evicted, ())


class IdentityTests(TestCase):
    """Empty appends; a record whose identity is already in the kept window is
    replaced — by identity anywhere in the window, not only the newest."""

    KEY = SeriesKey("jobs", "/ci/jobs", "staging")

    def test_empty_identities_append(self) -> None:
        store = MemoryStore()
        store.add(self.KEY, _record(0, response_ms=40), keep=10)
        store.add(self.KEY, _record(1, response_ms=40), keep=10)
        self.assertEqual(len(store.window(self.KEY)), 2)

    def test_a_reread_run_is_one_record_updated(self) -> None:
        store = MemoryStore()
        store.add(self.KEY, _record(0, "run-41", state="running"), keep=10)
        store.add(self.KEY, _record(7, "run-41", state="finished"), keep=10)
        record, = store.window(self.KEY)
        self.assertEqual(record.data["state"], "finished")
        self.assertEqual(record.observed_at, _at(7))

    def test_an_older_run_reread_is_replaced_where_it_stands(self) -> None:
        store = MemoryStore()
        for minute, run in enumerate(("run-40", "run-41", "run-42")):
            store.add(self.KEY, _record(minute, run, seen=1), keep=10)
        store.add(self.KEY, _record(9, "run-40", seen=2), keep=10)
        window = store.window(self.KEY)
        self.assertEqual([record.identity for record in window],
                         ["run-40", "run-41", "run-42"])
        self.assertEqual(window[0].data["seen"], 2)

    def test_an_identity_is_one_record_only_within_its_series(self) -> None:
        store = MemoryStore()
        other = SeriesKey("jobs", "/ci/jobs", "production")
        store.add(self.KEY, _record(0, "run-41"), keep=10)
        store.add(other, _record(0, "run-41"), keep=10)
        self.assertEqual(len(store.window(self.KEY)), 1)
        self.assertEqual(len(store.window(other)), 1)

    def test_an_identity_already_gone_is_a_new_record(self) -> None:
        # "already in the kept window": once out, a re-read comes back as new
        store = MemoryStore()
        for minute, run in enumerate(("run-40", "run-41")):
            store.add(self.KEY, _record(minute, run), keep=1)
        store.add(self.KEY, _record(5, "run-40"), keep=1)
        record, = store.window(self.KEY)
        self.assertEqual(record.identity, "run-40")


class StateTests(TestCase):
    """A state is compared with the newest record alone: the same state replaces
    it, and any other appends — a return to an earlier state included."""

    KEY = SeriesKey("aws", "/aws/ec2", "i-0abc")

    def _add(self, store: MemoryStore, minutes: int, state: str,
             **data: Any) -> None:
        store.add(self.KEY, SeriesRecord(data, _at(minutes), state=state), keep=10)

    def test_an_unchanged_state_is_one_record_updated(self) -> None:
        store = MemoryStore()
        self._add(store, 0, "running", cpu=10)
        self._add(store, 5, "running", cpu=12)
        record, = store.window(self.KEY)
        self.assertEqual((record.data["cpu"], record.observed_at), (12, _at(5)))

    def test_a_change_appends_the_next(self) -> None:
        store = MemoryStore()
        self._add(store, 0, "running")
        self._add(store, 5, "stopped")
        self.assertEqual([record.state for record in store.window(self.KEY)],
                         ["running", "stopped"])

    def test_a_return_to_an_earlier_state_is_a_new_spell(self) -> None:
        # found anywhere, the third spell would rewrite the first where it stands,
        # and the newest record would say *stopped* of an instance that runs
        store = MemoryStore()
        for minute, state in enumerate(("running", "running", "stopped",
                                        "stopped", "running", "running")):
            self._add(store, minute, state, minute=minute)
        window = store.window(self.KEY)
        self.assertEqual([(record.state, record.data["minute"]) for record in window],
                         [("running", 1), ("stopped", 3), ("running", 5)])

    def test_a_state_continues_no_event_and_an_event_no_state(self) -> None:
        # one spelling on both sides: each kind is matched against its own
        store = MemoryStore()
        self._add(store, 0, "running", n=1)
        store.add(self.KEY, SeriesRecord({"n": 2}, _at(1), identity="running"),
                  keep=10)
        self._add(store, 2, "running", n=3)
        self.assertEqual([(record.identity, record.state, record.data["n"])
                          for record in store.window(self.KEY)],
                         [("", "running", 1), ("running", "", 2),
                          ("", "running", 3)])

    def test_a_continued_spell_weighs_what_it_holds_now(self) -> None:
        store = MemoryStore()
        self._add(store, 0, "running", note="x" * 200)
        self._add(store, 1, "running", note="y")
        restored = MemoryStore()
        restored.restore(store.payload())
        self.assertEqual(store.held(), restored.held())
        self.assertEqual(store.usage()[("aws", "/aws/ec2")].bytes, store.held())


class ClockTests(TestCase):
    """`observed_at` is ours; a record's own times are the source's, never
    re-stamped; a series orders by the record's own time when it has one."""

    KEY = SeriesKey("batch", "/aws/batch", "nightly-export")

    def test_the_series_orders_by_the_records_own_time(self) -> None:
        store = MemoryStore()
        # read newest first, as a source that lists its runs tends to answer
        for minute, finished in enumerate(("2026-09-19T03:00:00Z",
                                           "2026-09-18T03:00:00Z",
                                           "2026-09-17T03:00:00Z")):
            store.add(self.KEY, _record(minute, finished, at=finished), keep=10)
        self.assertEqual([record.data["at"] for record in store.window(self.KEY)],
                         ["2026-09-17T03:00:00Z", "2026-09-18T03:00:00Z",
                          "2026-09-19T03:00:00Z"])

    def test_a_record_older_than_a_full_window_is_not_kept(self) -> None:
        store = MemoryStore()
        store.add(self.KEY, _record(0, "b", at="2026-09-18T03:00:00Z"), keep=1)
        store.add(self.KEY, _record(1, "a", at="2026-09-17T03:00:00Z"), keep=1)
        record, = store.window(self.KEY)
        self.assertEqual(record.identity, "b")

    def test_a_nested_time_is_a_value_not_the_records_own(self) -> None:
        # a file's modification time is what the file check measured, not the
        # instant its reading is of: the series stands on when we looked
        store = MemoryStore()
        store.add(self.KEY, _record(0, modified={"at": "2026-09-19T00:00:00Z"}),
                  keep=10)
        store.add(self.KEY, _record(1, modified={"at": "2026-09-01T00:00:00Z"}),
                  keep=10)
        self.assertEqual([record.observed_at for record in store.window(self.KEY)],
                         [_at(0), _at(1)])

    def test_an_at_that_is_not_an_instant_is_no_time_of_its_own(self) -> None:
        # the seam refuses these; a record read back from anywhere else may not
        # have been through it, and a time without an offset is nobody's instant
        for value in ("yesterday", "2026-09-19T03:00:00", 1758250800, None):
            with self.subTest(at=value):
                self.assertIsNone(_record(0, at=value).at)

    def test_both_clocks_are_kept_and_neither_is_restamped(self) -> None:
        store = MemoryStore()
        store.add(self.KEY, _record(0, "run-7", at="2026-09-19T03:00:00Z"),
                  keep=10)
        record, = store.window(self.KEY)
        self.assertEqual(record.data["at"], "2026-09-19T03:00:00Z")
        self.assertEqual(record.at, datetime(2026, 9, 19, 3, 0, tzinfo=UTC))
        self.assertEqual(record.observed_at, _at(0))

    def test_without_a_time_of_its_own_readings_keep_the_order_handed_back(
            self) -> None:
        store = MemoryStore()
        for name in ("first", "second", "third"):
            store.add(self.KEY, _record(0, name), keep=10)
        self.assertEqual([record.identity for record in store.window(self.KEY)],
                         ["first", "second", "third"])

    def test_each_record_is_placed_where_its_series_orders_it(self) -> None:
        # the instant a curve draws a reading at and its table lists it under
        # (ADR-0092 decision 4): its own `at`, or when it was first observed —
        # which a re-read that replaces it does not move
        store = MemoryStore()
        store.add(self.KEY, _record(0, "run-7", at="2026-09-19T03:00:00Z"), keep=10)
        store.add(self.KEY, _record(1, "run-8"), keep=10)
        store.add(self.KEY, _record(5, "run-8", note="re-read"), keep=10)
        placed = store.placed(self.KEY)
        self.assertEqual([(kept.record.identity, kept.at) for kept in placed],
                         [("run-7", datetime(2026, 9, 19, 3, 0, tzinfo=UTC)),
                          ("run-8", _at(1))])
        self.assertEqual(placed[1].record.observed_at, _at(5))
        self.assertEqual([kept.record for kept in placed],
                         list(store.window(self.KEY)))

    def test_a_place_survives_the_series_file(self) -> None:
        store = MemoryStore()
        store.add(self.KEY, _record(1, "run-8"), keep=10)
        store.add(self.KEY, _record(5, "run-8", note="re-read"), keep=10)
        restored = MemoryStore()
        restored.restore(json.loads(json.dumps(store.payload())))
        self.assertEqual(restored.placed(self.KEY), store.placed(self.KEY))

    def test_an_unknown_series_places_nothing(self) -> None:
        self.assertEqual(MemoryStore().placed(self.KEY), ())

    def test_a_place_is_a_record_and_an_instant(self) -> None:
        record = _record(0)
        self.assertEqual(Placed(record, _at(0)), Placed(record, _at(0)))

    def test_observed_at_is_an_aware_instant_held_in_utc(self) -> None:
        berlin = timezone(timedelta(hours=2))
        record = SeriesRecord({}, datetime(2026, 9, 20, 14, 0, tzinfo=berlin))
        self.assertEqual(record.observed_at, T0)
        self.assertIs(record.observed_at.tzinfo, UTC)
        with self.assertRaises(ValueError):
            SeriesRecord({}, T0.replace(tzinfo=None))


class _Reader(Check):
    """A check that hands back whatever measurements the test gives it."""

    type_name = "reader"

    def __init__(self, *, measurements: Sequence[Measurement] = (),
                 raises: Exception | None = None, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.measurements = tuple(measurements)
        self.raises = raises
        self.graded_at: datetime | None = None

    def measure(self) -> Sequence[Measurement]:
        if self.raises is not None:
            raise self.raises
        return self.measurements

    def grade(self, measurements: Sequence[Measurement],
              now: datetime) -> CheckResult:
        self.graded_at = now
        return CheckResult(StatusCode.OK)


class _OtherReader(_Reader):
    """The same shape under another type — two methods on one mount."""

    type_name = "other-reader"


def _ticking() -> Callable[[], datetime]:
    """A wall clock that moves one second every time it is read."""
    reads = itertools.count()
    return lambda: T0 + timedelta(seconds=next(reads))


def _reading(subject: str = "", identity: str = "", **data: Any) -> Measurement:
    return Measurement(record=data, subject=subject, identity=identity)


class EngineSeriesTests(TestCase):
    """The engine keeps each run's readings in their subjects' series, keyed by
    the check — its type and its mount — and the subject."""

    def _run(self, *checks: Check, times: int = 1) -> Engine:
        engine = Engine(list(checks), StatusTree())
        for _ in range(times):
            engine.run_once()
        return engine

    def test_a_check_that_keeps_none_has_no_series(self) -> None:
        check = _Reader(path="/web", subject="web01",
                        measurements=[_reading(load=0.4)])
        engine = self._run(check)
        self.assertEqual(engine.series.window(
            SeriesKey("reader", "/web", "web01")), ())

    def test_a_node_finds_the_series_kept_at_it_beneath_it_and_above_it(self) -> None:
        # the engine answers for the pages (ADR-0097 decision 1): every check that
        # keeps a series mounted at the node, beneath it or above it, with its
        # subject's readings, oldest first and each where its series places it
        check = _Reader(path="/web", subject="web01", series_keep=5,
                        measurements=[_reading(load=0.4)])
        engine = self._run(check, times=2)
        for path in ("/web", "/", "/web/child"):
            with self.subTest(path=path):
                kept, = engine.series_near(path)
                self.assertIs(kept.check, check)
                self.assertEqual(kept.subject, "web01")
                self.assertEqual(kept.readings, engine.series.placed(
                    SeriesKey("reader", "/web", "web01")))
                self.assertEqual(len(kept.readings), 2)

    def test_every_subject_a_check_keeps_a_series_of(self) -> None:
        check = _Reader(path="/web", series_keep=5,
                        measurements=[_reading("web01", load=0.4),
                                      _reading("web02", load=0.7)])
        engine = self._run(check)
        self.assertEqual(sorted(kept.subject for kept in engine.series_near("/web")),
                         ["web01", "web02"])

    def test_no_series_near_another_node(self) -> None:
        check = _Reader(path="/web", subject="web01", series_keep=5,
                        measurements=[_reading(load=0.4)])
        engine = self._run(check)
        for path in ("/other", "/webshop"):
            with self.subTest(path=path):
                self.assertEqual(engine.series_near(path), ())

    def test_no_series_where_the_check_keeps_none(self) -> None:
        # whatever an older series file left behind: the next sweep drops it, and
        # nothing shows it meanwhile
        check = _Reader(path="/web", subject="web01",
                        measurements=[_reading(load=0.4)])
        engine = Engine([check], StatusTree())
        engine.series.add(SeriesKey("reader", "/web", "web01"),
                          SeriesRecord({"load": 0.4}, T0), keep=5)
        self.assertEqual(engine.series_near("/web"), ())

    def test_a_check_with_series_keep_holds_its_readings_bounded(self) -> None:
        check = _Reader(path="/web", subject="web01", series_keep=3,
                        measurements=[_reading(load=0.4)])
        engine = self._run(check, times=5)
        self.assertEqual(len(engine.series.window(
            SeriesKey("reader", "/web", "web01"))), 3)

    def test_one_reading_alone_joins_the_checks_own_object(self) -> None:
        check = _Reader(path="/web", subject="web01", series_keep=5,
                        measurements=[_reading(load=0.4)])
        engine = self._run(check)
        record, = engine.series.window(SeriesKey("reader", "/web", "web01"))
        self.assertEqual(record.data, {"load": 0.4})

    def test_a_reading_that_names_its_subject_joins_that_one(self) -> None:
        check = _Reader(path="/rate", subject="", series_keep=5,
                        measurements=[_reading("octocat:core", remaining=4999)])
        engine = self._run(check)
        self.assertEqual(len(engine.series.window(
            SeriesKey("reader", "/rate", "octocat:core"))), 1)

    def test_among_several_a_reading_with_no_subject_has_no_series(self) -> None:
        check = _Reader(path="/gh", subject="the-org", series_keep=5,
                        measurements=[_reading(kind="estate"),
                                      _reading("1:2:main", verdict="passed")])
        engine = self._run(check)
        self.assertEqual(engine.series.window(
            SeriesKey("reader", "/gh", "the-org")), ())
        self.assertEqual(len(engine.series.window(
            SeriesKey("reader", "/gh", "1:2:main"))), 1)

    def test_two_subjects_are_two_series(self) -> None:
        check = _Reader(path="/gh", series_keep=5,
                        measurements=[_reading("1:2:main", verdict="passed"),
                                      _reading("1:3:main", verdict="failed")])
        engine = self._run(check)
        for subject, verdict in (("1:2:main", "passed"), ("1:3:main", "failed")):
            with self.subTest(subject=subject):
                record, = engine.series.window(SeriesKey("reader", "/gh", subject))
                self.assertEqual(record.data["verdict"], verdict)

    def test_two_types_on_one_mount_are_two_series(self) -> None:
        # one host node carries host-metrics and macos-memory by design, and
        # the container belongs to neither
        first = _Reader(path="/macmini/system", subject="macmini", series_keep=5,
                        measurements=[_reading(load=0.4)])
        second = _OtherReader(path="/macmini/system", subject="macmini",
                              series_keep=5,
                              measurements=[_reading(wired_gb=3.1)])
        engine = self._run(first, second)
        one, = engine.series.window(SeriesKey("reader", "/macmini/system",
                                              "macmini"))
        two, = engine.series.window(SeriesKey("other-reader", "/macmini/system",
                                              "macmini"))
        self.assertEqual((one.data, two.data), ({"load": 0.4}, {"wired_gb": 3.1}))

    def test_one_type_on_two_mounts_is_two_series(self) -> None:
        system = _Reader(path="/nas1/system", subject="nas1", series_keep=5,
                         measurements=[_reading(load=0.4)])
        qnap = _Reader(path="/nas1/qnap", subject="nas1", series_keep=5,
                       measurements=[_reading(load=0.9)])
        engine = self._run(system, qnap)
        for mount, load in (("/nas1/system", 0.4), ("/nas1/qnap", 0.9)):
            with self.subTest(mount=mount):
                record, = engine.series.window(SeriesKey("reader", mount, "nas1"))
                self.assertEqual(record.data["load"], load)

    def test_a_reread_run_is_one_record_across_polls(self) -> None:
        check = _Reader(path="/ci/jobs", series_keep=10,
                        measurements=[_reading("staging", "run-41", ok=True)])
        engine = self._run(check, times=3)
        key = SeriesKey("reader", "/ci/jobs", "staging")
        self.assertEqual(len(engine.series.window(key)), 1)
        check.measurements = (_reading("staging", "run-42", ok=False),
                              _reading("staging", "run-41", ok=True))
        engine.run_once()
        self.assertEqual([record.identity for record in engine.series.window(key)],
                         ["run-41", "run-42"])

    def test_a_state_is_one_record_per_spell_across_polls(self) -> None:
        def disabled(state: str) -> Measurement:
            return Measurement(record={"state": state}, subject="deploy",
                               state=state)

        check = _Reader(path="/ci/workflows", series_keep=10,
                        measurements=[disabled("disabled_manually")])
        engine = self._run(check, times=3)
        key = SeriesKey("reader", "/ci/workflows", "deploy")
        self.assertEqual(len(engine.series.window(key)), 1)
        for state in ("active", "disabled_manually", "disabled_manually"):
            check.measurements = (disabled(state),)
            engine.run_once()
        self.assertEqual([record.state for record in engine.series.window(key)],
                         ["disabled_manually", "active", "disabled_manually"])

    def test_a_failed_reading_is_kept_against_the_declared_object(self) -> None:
        check = _Reader(path="/web", subject="web01", series_keep=5,
                        raises=RuntimeError("connection refused"))
        engine = self._run(check)
        record, = engine.series.window(SeriesKey("reader", "/web", "web01"))
        self.assertEqual(record.data, {"error": "connection refused"})

    def test_a_pinned_check_never_went_and_keeps_nothing(self) -> None:
        check = _Reader(path="/web", subject="web01", series_keep=5,
                        measurements=[_reading(load=0.4)])
        check.secret_errors.append("env://TOKEN is not set")
        engine = self._run(check)
        self.assertEqual(engine.series.window(
            SeriesKey("reader", "/web", "web01")), ())

    def test_observed_at_is_the_instant_the_grading_was_handed(self) -> None:
        # on a clock that moves a second each time it is read, so two readings of
        # it cannot pass for one at the resolution of a fast machine
        check = _Reader(path="/web", subject="web01", series_keep=5,
                        measurements=[_reading(load=0.4)])
        engine = Engine([check], StatusTree(), wall=_ticking())
        engine.run_once()
        record, = engine.series.window(SeriesKey("reader", "/web", "web01"))
        self.assertIsNotNone(check.graded_at)
        self.assertEqual(record.observed_at, check.graded_at)


class _Refusing(MemoryStore):
    """A store that cannot keep anything — a full disk, a service gone."""

    def add(self, key: SeriesKey, record: SeriesRecord, *, keep: int) -> None:
        raise OSError("no space left on device")


class SeriesFailureTests(TestCase):
    """A history that could not be kept costs a line on the instance's own node,
    and never the reading the node already shows."""

    def test_the_reading_stands_and_the_instance_says_so(self) -> None:
        self_report.runtime.forget()
        self.addCleanup(self_report.runtime.forget)
        check = _Reader(path="/web", subject="web01", series_keep=5,
                        measurements=[_reading(load=0.4)])
        tree = StatusTree()
        engine = Engine([check], tree, series=_Refusing())
        with self.assertLogs("little_sister", level="ERROR"):
            engine.run_once()
        node = tree.snapshot("/web")
        assert node is not None
        self.assertEqual(node.record, {"load": 0.4})
        (line,) = self_report.runtime.lines()
        self.assertEqual(line.slug, slug("series", "/web"))
        self.assertIn("no space left on device", line.text)


class OneSubjectTwiceTests(TestCase):
    """A run may read one subject several times where the identities differ
    (ADR-0087 decision 3): each is kept by its own rule. The same identity twice is
    one record, the later, and so is the same state twice; neither twice is two
    points at one instant."""

    KEY = SeriesKey("reader", "/ci/jobs", "staging")

    def _kept(self, *readings: Measurement) -> tuple[SeriesRecord, ...]:
        engine = Engine([_Reader(path="/ci/jobs", series_keep=10,
                                 measurements=readings)], StatusTree())
        engine.run_once()
        return engine.series.window(self.KEY)

    def test_distinct_identities_are_distinct_records(self) -> None:
        kept = self._kept(_reading("staging", "run-41", ok=True),
                          _reading("staging", "run-42", ok=False))
        self.assertEqual([record.identity for record in kept],
                         ["run-41", "run-42"])

    def test_the_same_identity_twice_is_one_record_the_later(self) -> None:
        kept = self._kept(_reading("staging", "run-41", state="running"),
                          _reading("staging", "run-41", state="finished"))
        record, = kept
        self.assertEqual(record.data["state"], "finished")

    def test_the_same_state_twice_is_one_record_the_later(self) -> None:
        record, = self._kept(
            Measurement(record={"n": 1}, subject="staging", state="idle"),
            Measurement(record={"n": 2}, subject="staging", state="idle"))
        self.assertEqual(record.data["n"], 2)

    def test_no_identity_twice_is_two_points_at_one_instant(self) -> None:
        first, second = self._kept(_reading("staging", load=0.4),
                                   _reading("staging", load=0.5))
        self.assertEqual(first.observed_at, second.observed_at)
        self.assertEqual([first.data["load"], second.data["load"]], [0.4, 0.5])


class _Grading(_Reader):
    """A check whose grading the test writes: ``grading`` turns the readings into
    the result, so the line or node a reading stood on is the test's to shape."""

    def __init__(self, *, grading: Any = None, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.grading = grading

    def grade(self, measurements: Sequence[Measurement],
              now: datetime) -> CheckResult:
        self.graded_at = now
        result: CheckResult = self.grading(measurements)
        return result


def _line(measurement: Measurement, text: str,
          code: StatusCode | None = None) -> Entry:
    """The line a grading writes for a reading, carrying it the way ADR-0086
    decision 2 says: the record as its data, the reading's subject as its own."""
    return Entry(f"line-{measurement.subject}-{len(text)}", text, code,
                 subject=measurement.subject, data=dict(measurement.record))


class _Host(_Reader):
    """A branch check on a host node that two checks share, as `host-metrics` and
    `macos-memory` do: a silent root, and children that carry the codes — the worst
    of them a level down, under a container of its own, so a roll-up that stops at
    the first level misses it. ``usb`` adds a red child while it is true."""

    type_name = "host"

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(path="/macmini/system", subject="macmini", series_keep=5,
                         measurements=[_reading(disk_pct=91, load=0.4)], **kwargs)
        self.usb = False

    def grade(self, measurements: Sequence[Measurement],
              now: datetime) -> CheckResult:
        children = [
            CheckResult(StatusCode.UNDEFINED, name="disks", children=(
                CheckResult(StatusCode.WARN, ["91 % used"], name="data"),)),
            CheckResult(StatusCode.OK, ["load 0.4"], name="load")]
        if self.usb:
            children.append(CheckResult(StatusCode.ERROR, ["unplugged"],
                                        name="usb"))
        return CheckResult(StatusCode.UNDEFINED, children=tuple(children))


def _leaf_codes(result: CheckResult) -> list[StatusCode]:
    """The codes of a result's leaves at any depth — what a page shows of a record
    it grades again."""
    if not result.children:
        return [result.stored_code]
    return [code for child in result.children for code in _leaf_codes(child)]


class _Scoped(_Host):
    """The same branch check with a root that says what it watches and grades
    nothing — `UNDEFINED` and one sentence, the shape of `little-sister-aws`'s
    root."""

    def grade(self, measurements: Sequence[Measurement],
              now: datetime) -> CheckResult:
        silent = super().grade(measurements, now)
        return CheckResult(StatusCode.UNDEFINED, ["2 volumes in scope"],
                           children=silent.children)


class StoodTests(TestCase):
    """A kept reading carries the sentence and the code as they stood (ADR-0087
    decision 8): the line it became keeps its text and code; the node it was placed
    on keeps its code and texts; a branch check's root that grades nothing keeps
    what its own result rolls up to, beside whatever it says — never what the node
    holds besides."""

    HOST = SeriesKey("host", "/macmini/system", "macmini")

    def _kept(self, check: Check, key: SeriesKey,
              tree: StatusTree | None = None) -> SeriesRecord:
        engine = Engine([check], tree or StatusTree())
        engine.run_once()
        kept = engine.series.window(key)
        self.assertEqual(len(kept), 1, kept)
        return kept[0]

    def test_a_placed_reading_keeps_the_nodes_code_and_texts(self) -> None:
        check = _Grading(path="/web", subject="https://example.org", series_keep=5,
                         measurements=[_reading(response_ms=912)],
                         grading=lambda _m: CheckResult(
                             StatusCode.WARN, ["slow: 912 ms", "twice the usual"]))
        record = self._kept(check, SeriesKey("reader", "/web",
                                             "https://example.org"))
        self.assertIs(record.code, StatusCode.WARN)
        self.assertEqual(record.texts, ("slow: 912 ms", "twice the usual"))

    def test_a_silent_branch_root_keeps_what_its_own_result_rolls_up_to(
            self) -> None:
        # the WARN is a level down, under a container of its own
        record = self._kept(_Host(), self.HOST)
        self.assertIs(record.code, StatusCode.WARN)
        self.assertEqual(record.texts, ())

    def test_a_root_that_grades_nothing_and_speaks_keeps_its_roll_up_and_its_text(
            self) -> None:
        # a sentence is not a code: the root claims no more than a silent one
        record = self._kept(_Scoped(), self.HOST)
        self.assertIs(record.code, StatusCode.WARN)
        self.assertEqual(record.texts, ("2 volumes in scope",))

    def test_another_check_on_the_mount_is_not_what_this_reading_says(
            self) -> None:
        # the other check's red memory is what the shared host node shows, and
        # nothing this reading read
        tree = StatusTree()
        tree.upsert("/macmini/system/memory", StatusCode.ERROR, "swapping")
        record = self._kept(_Host(), self.HOST, tree)
        self.assertIs(tree.effective("/macmini/system"), StatusCode.ERROR)
        self.assertIs(record.code, StatusCode.WARN)

    def test_a_child_an_earlier_run_left_is_not_what_this_reading_says(
            self) -> None:
        # the tree keeps a child a later run no longer writes (ADR-0007)
        check = _Host()
        check.usb = True
        tree = StatusTree()
        engine = Engine([check], tree)
        engine.run_once()
        check.usb = False
        engine.run_once()
        self.assertIs(tree.effective("/macmini/system"), StatusCode.ERROR)
        first, second = engine.series.window(self.HOST)
        self.assertEqual((first.code, second.code),
                         (StatusCode.ERROR, StatusCode.WARN))

    def test_grading_the_record_again_gives_the_code_it_kept(self) -> None:
        tree = StatusTree()
        tree.upsert("/macmini/system/memory", StatusCode.ERROR, "swapping")
        check = _Host()
        record = self._kept(check, self.HOST, tree)
        again = check.grade([Measurement(record=dict(record.data))],
                            record.observed_at)
        shown = [code for code in _leaf_codes(again)
                 if code is not StatusCode.UNDEFINED]
        self.assertEqual(sorted(code.name for code in shown), ["OK", "WARN"])
        self.assertIs(record.code, worst_of(shown))

    def test_a_pin_is_not_what_the_reading_carries(self) -> None:
        tree = StatusTree()
        tree.upsert("/macmini/system", StatusCode.UNDEFINED)
        tree.set_maintenance("/macmini/system", "planned",
                             expires_at=datetime(2999, 1, 1, tzinfo=UTC))
        self.assertIs(tree.effective("/macmini/system"), StatusCode.MAINTENANCE)
        record = self._kept(_Host(), self.HOST, tree)
        self.assertIs(record.code, StatusCode.WARN)

    def test_one_of_several_keeps_the_line_it_became(self) -> None:
        def grading(readings: Sequence[Measurement]) -> CheckResult:
            return CheckResult(reason=[
                _line(readings[0], "build: failed (#41)", StatusCode.ERROR),
                _line(readings[1], "tests: passed (#7)", StatusCode.OK)])
        check = _Grading(path="/gh", series_keep=5, grading=grading,
                         measurements=[_reading("1:2:main", verdict="failed"),
                                       _reading("1:3:main", verdict="passed")])
        engine = Engine([check], StatusTree())
        engine.run_once()
        failed, = engine.series.window(SeriesKey("reader", "/gh", "1:2:main"))
        passed, = engine.series.window(SeriesKey("reader", "/gh", "1:3:main"))
        self.assertEqual((failed.code, failed.texts),
                         (StatusCode.ERROR, ("build: failed (#41)",)))
        self.assertEqual((passed.code, passed.texts),
                         (StatusCode.OK, ("tests: passed (#7)",)))

    def test_a_line_without_a_code_carries_its_nodes(self) -> None:
        def grading(readings: Sequence[Measurement]) -> CheckResult:
            return CheckResult(StatusCode.WARN, [
                _line(reading, f"{reading.subject} is stale")
                for reading in readings], entries=True)
        check = _Grading(path="/gh", series_keep=5, grading=grading,
                         measurements=[_reading("a", age_h=30),
                                       _reading("b", age_h=31)])
        engine = Engine([check], StatusTree())
        engine.run_once()
        record, = engine.series.window(SeriesKey("reader", "/gh", "a"))
        self.assertEqual((record.code, record.texts),
                         (StatusCode.WARN, ("a is stale",)))

    def test_the_line_is_found_by_its_record_not_its_subject_alone(self) -> None:
        # two runs of one environment, each on a line of its own
        def grading(readings: Sequence[Measurement]) -> CheckResult:
            return CheckResult(reason=[
                _line(readings[1], "run 42: failed", StatusCode.ERROR),
                _line(readings[0], "run 41: passed", StatusCode.OK)])
        check = _Grading(path="/ci/jobs", series_keep=5, grading=grading,
                         measurements=[_reading("staging", "run-41", run=41),
                                       _reading("staging", "run-42", run=42)])
        engine = Engine([check], StatusTree())
        engine.run_once()
        kept = engine.series.window(SeriesKey("reader", "/ci/jobs", "staging"))
        self.assertEqual([(record.identity, record.code, record.texts)
                          for record in kept],
                         [("run-41", StatusCode.OK, ("run 41: passed",)),
                          ("run-42", StatusCode.ERROR, ("run 42: failed",))])

    def test_a_reading_no_line_carried_stood_nowhere(self) -> None:
        # a healthy run a check chose not to show
        def grading(readings: Sequence[Measurement]) -> CheckResult:
            return CheckResult(reason=[
                _line(readings[0], "build: failed (#41)", StatusCode.ERROR)])
        check = _Grading(path="/gh", series_keep=5, grading=grading,
                         measurements=[_reading("1:2:main", verdict="failed"),
                                       _reading("1:3:main", verdict="passed")])
        engine = Engine([check], StatusTree())
        engine.run_once()
        record, = engine.series.window(SeriesKey("reader", "/gh", "1:3:main"))
        self.assertEqual((record.code, record.texts), (None, ()))

    def _estate(self, grading: Any) -> Engine:
        """A check that declared its object — the estate — and reads it beside two
        objects it found, a failed run and a passed one, the way `github` does."""
        check = _Grading(path="/gh", subject="example-org", series_keep=5,
                         grading=grading,
                         measurements=[_reading("example-org", repositories=2),
                                       _reading("1:2:main", verdict="failed"),
                                       _reading("1:3:main", verdict="passed")])
        engine = Engine([check], StatusTree())
        engine.run_once()
        return engine

    def _stood(self, engine: Engine,
               subject: str) -> tuple[StatusCode | None, tuple[str, ...]]:
        record, = engine.series.window(SeriesKey("reader", "/gh", subject))
        return record.code, record.texts

    def test_the_checks_own_object_among_several_stands_on_the_node(self) -> None:
        """The object the check declared, read beside the ones it found, stood
        where the one placed reading stands — on the node, with the node's code
        and texts — although no line carries it; a found object no line carried
        still stood nowhere."""
        def grading(readings: Sequence[Measurement]) -> CheckResult:
            return CheckResult(StatusCode.WARN, ["2 in scope, 1 could not be read"],
                               children=(CheckResult(reason=[_line(
                                   readings[1], "build: failed (#41)",
                                   StatusCode.ERROR)], name="actions"),))
        engine = self._estate(grading)
        self.assertEqual(self._stood(engine, "example-org"),
                         (StatusCode.WARN, ("2 in scope, 1 could not be read",)))
        self.assertEqual(self._stood(engine, "1:2:main"),
                         (StatusCode.ERROR, ("build: failed (#41)",)))
        self.assertEqual(self._stood(engine, "1:3:main"), (None, ()))

    def test_a_line_that_carried_the_checks_own_object_still_wins(self) -> None:
        def grading(readings: Sequence[Measurement]) -> CheckResult:
            # the node is WARN, from its second line; the estate's line is OK
            return CheckResult(reason=[
                _line(readings[0], "estate: 2 repositories", StatusCode.OK),
                Entry("unread", "1 could not be read", StatusCode.WARN)])
        engine = self._estate(grading)
        self.assertEqual(self._stood(engine, "example-org"),
                         (StatusCode.OK, ("estate: 2 repositories",)))

    def test_the_checks_own_object_on_a_silent_root_keeps_the_roll_up(
            self) -> None:
        """Where the root is a branch check's silent container, the object the check
        declared keeps what its own result rolls up to and no text — the same that
        the one placed reading would keep there."""
        def grading(readings: Sequence[Measurement]) -> CheckResult:
            return CheckResult(StatusCode.UNDEFINED, children=(
                CheckResult(reason=[_line(readings[1], "build: failed (#41)",
                                          StatusCode.ERROR)], name="actions"),
                CheckResult(StatusCode.WARN, ["one repository unread"],
                            name="coverage")))
        engine = self._estate(grading)
        self.assertEqual(self._stood(engine, "example-org"), (StatusCode.ERROR, ()))

    def test_the_checks_own_object_on_a_root_that_only_speaks_keeps_the_roll_up(
            self) -> None:
        """A root that grades nothing but says what it watches — `UNDEFINED`, and a
        sentence — stood as what its result rolls up to, with that sentence."""
        def grading(readings: Sequence[Measurement]) -> CheckResult:
            return CheckResult(StatusCode.UNDEFINED, ["2 accounts in scope"],
                               children=(
                CheckResult(reason=[_line(readings[1], "build: failed (#41)",
                                          StatusCode.ERROR)], name="actions"),
                CheckResult(StatusCode.WARN, ["one repository unread"],
                            name="coverage")))
        engine = self._estate(grading)
        self.assertEqual(self._stood(engine, "example-org"),
                         (StatusCode.ERROR, ("2 accounts in scope",)))

    def test_a_failed_reading_keeps_the_error_that_stood(self) -> None:
        check = _Reader(path="/web", subject="web01", series_keep=5,
                        raises=RuntimeError("connection refused"))
        record = self._kept(check, SeriesKey("reader", "/web", "web01"))
        self.assertIs(record.code, StatusCode.ERROR)
        self.assertIn("check error: connection refused", record.texts[0])
