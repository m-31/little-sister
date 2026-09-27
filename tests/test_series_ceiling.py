"""The series' ceiling and its projection (ADR-0087), said by the process on its
own node: a bound on what every series weighs together, in the shape
``entry_limit`` has — amber at a share, red while series are being evicted, the
one written to longest ago first — and beside it what this configuration would
need at today's estate, which is a WARN on the first tick it is past the ceiling,
long before a slowly filling series reaches it."""
from __future__ import annotations

import json
import logging
import tempfile
import time
from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from unittest import TestCase

from little_sister.checks import Check, CheckResult, Measurement
from little_sister.config import load_config
from little_sister.engine import ENGINE_REPORT, Engine
from little_sister.limits import (
    SERIES_LIMIT,
    EngineReport,
    Limits,
    SeriesHeld,
    format_weight,
)
from little_sister.logger import logger
from little_sister.series import MemoryStore, SeriesKey, SeriesRecord
from little_sister.status import HEARTBEAT_PATH, StatusCode
from little_sister.tree import StatusTree

T0 = datetime(2026, 9, 20, 12, 0, tzinfo=UTC)


def _record(minutes: int, **data: Any) -> SeriesRecord:
    return SeriesRecord(data, T0 + timedelta(minutes=minutes))


def _weight(store: MemoryStore) -> int:
    """What the series file would keep, weighed the way the seam weighs a record:
    the JSON of every kept reading, one at a time."""
    return sum(len(json.dumps(item).encode("utf-8"))
               for series in store.payload()["series"]
               for item in series["records"])


class _Estate(Check):
    """A check that reads as many subjects as the test says, each one reading of
    about a hundred bytes, and grades each onto a line of its own."""

    type_name = "estate"

    def __init__(self, *, subjects: int = 3, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.subjects = subjects

    def measure(self) -> Sequence[Measurement]:
        return [Measurement(record={"repository": f"repo-{number:03d}",
                                    "verdict": "passed", "padding": "x" * 40},
                            subject=f"repo-{number:03d}")
                for number in range(self.subjects)]

    def grade(self, measurements: Sequence[Measurement],
              now: datetime) -> CheckResult:
        from little_sister.checks import Entry
        return CheckResult(reason=[
            Entry(f"line-{number}", f"{m.subject}: passed", StatusCode.OK,
                  subject=m.subject, data=dict(m.record))
            for number, m in enumerate(measurements)])


class CeilingTests(TestCase):
    """What the memory tier holds is weighed, and past a ceiling whole series go —
    the one written to longest ago first — until what is left fits."""

    A = SeriesKey("http", "/web", "https://example.org/a")
    B = SeriesKey("http", "/web", "https://example.org/b")
    C = SeriesKey("http", "/web", "https://example.org/c")

    def _three(self) -> MemoryStore:
        """Three series: A created first and written last, B written longest ago,
        C in between — so *oldest* by last write, by creation and by oldest
        record are three different answers."""
        store = MemoryStore()
        store.add(self.A, _record(0, n=1), keep=10)
        store.add(self.B, _record(1, n=1), keep=10)
        store.add(self.C, _record(2, n=1), keep=10)
        store.add(self.C, _record(5, n=2), keep=10)
        store.add(self.A, _record(10, n=2), keep=10)
        return store

    def test_what_is_held_is_what_the_file_would_keep(self) -> None:
        store = self._three()
        self.assertEqual(store.held(), _weight(store))
        # and a replaced record is weighed once, as it is now
        store.add(self.B, SeriesRecord({"n": 1, "more": "y" * 50},
                                       T0 + timedelta(minutes=20), "same"), keep=10)
        store.add(self.B, SeriesRecord({"n": 2}, T0 + timedelta(minutes=21),
                                       "same"), keep=10)
        self.assertEqual(store.held(), _weight(store))

    def test_under_the_ceiling_nothing_goes(self) -> None:
        store = self._three()
        swept = store.sweep(lambda key: 10, ceiling=store.held())
        self.assertEqual(swept.evicted, ())
        self.assertEqual(len(store.window(self.B)), 1)

    def test_without_a_ceiling_nothing_goes(self) -> None:
        store = self._three()
        self.assertEqual(store.sweep(lambda key: 10).evicted, ())

    def test_the_series_written_to_longest_ago_goes_first(self) -> None:
        store = self._three()
        weight_b = _series_weight(store, self.B)
        swept = store.sweep(lambda key: 10, ceiling=store.held() - 1)
        self.assertEqual(swept.evicted, (self.B,))
        self.assertEqual(swept.evicted_bytes, weight_b)
        self.assertEqual(store.window(self.B), ())
        self.assertEqual((len(store.window(self.A)), len(store.window(self.C))),
                         (2, 2))

    def test_whole_series_go_in_that_order_until_what_is_left_fits(self) -> None:
        store = self._three()
        ceiling = _series_weight(store, self.A)
        swept = store.sweep(lambda key: 10, ceiling=ceiling)
        self.assertEqual(swept.evicted, (self.B, self.C))
        self.assertLessEqual(store.held(), ceiling)
        self.assertEqual(len(store.window(self.A)), 2)

    def test_a_series_heavier_than_the_ceiling_goes_too(self) -> None:
        store = MemoryStore()
        store.add(self.A, _record(0, blob="z" * 500), keep=10)
        swept = store.sweep(lambda key: 10, ceiling=100)
        self.assertEqual((swept.evicted, store.held()), ((self.A,), 0))


def _series_weight(store: MemoryStore, key: SeriesKey) -> int:
    return sum(len(json.dumps(item).encode("utf-8"))
               for series in store.payload()["series"]
               if (series["type"], series["mount"], series["subject"])
               == (key.type_name, key.mount, key.subject)
               for item in series["records"])


def _report(ceiling: int) -> EngineReport:
    return EngineReport((), workers=1, poll_interval=1.0,
                        limits=Limits(memory_limit=None, series_limit=ceiling),
                        resident=lambda: None)


def _lines(report: EngineReport) -> dict[str, tuple[StatusCode | None, str]]:
    return {line.slug: (line.code, line.text) for line in report.lines()}


class SeriesLineTests(TestCase):
    """The two lines' sentences and codes, from the claims: over the ceiling is
    ERROR — curves are being shortened now — and amber from 80 % of it; a
    projection past it is WARN — *this configuration cannot be honored at this
    estate*."""

    def test_below_the_amber_share_nothing_is_said(self) -> None:
        report = _report(2000)
        report.observe(0.0, entries=0, waiting=[], late=[],
                       series=SeriesHeld(held=1599, projection=2000))
        self.assertEqual(_lines(report), {})

    def test_the_amber_share_is_a_warn_with_the_percentage(self) -> None:
        report = _report(2000)
        report.observe(0.0, entries=0, waiting=[], late=[],
                       series=SeriesHeld(held=1600))
        self.assertEqual(_lines(report)["series"],
                         (StatusCode.WARN, "the series hold 1.6 KiB, 80 % of "
                                           "their ceiling of 2.0 KiB"))

    def test_an_eviction_is_an_error_naming_what_went(self) -> None:
        report = _report(2048)
        report.observe(0.0, entries=0, waiting=[], late=[],
                       series=SeriesHeld(held=1900, evicted=("/web (a)",),
                                         evicted_bytes=812))
        self.assertEqual(_lines(report)["series"], (
            StatusCode.ERROR,
            "the series outgrew their ceiling of 2.0 KiB: the series written to "
            "longest ago was evicted (812 B) — /web (a) — so their curves are "
            "shortened"))

    def test_an_eviction_is_logged_as_the_error_its_line_is(self) -> None:
        """The log entry says what the line says: ERROR — curves are being shortened
        now — and not a warning, so the log read without the page does not make an
        eviction sound like less than the node does."""
        report = _report(2048)
        with self.assertLogs(logger, level=logging.INFO) as logs:
            report.observe(0.0, entries=0, waiting=[], late=[],
                           series=SeriesHeld(held=1900, evicted=("/web (a)",),
                                             evicted_bytes=812))
        (record,) = [record for record in logs.records
                     if record.getMessage().startswith("series: the series outgrew")]
        self.assertEqual(logging.getLevelName(record.levelno), "ERROR")

    def test_the_eviction_line_outlives_its_tick_for_the_window(self) -> None:
        report = _report(2048)
        report.observe(0.0, entries=0, waiting=[], late=[],
                       series=SeriesHeld(held=1000, evicted=("/web (a)",),
                                         evicted_bytes=812))
        report.observe(1.0, entries=0, waiting=[], late=[],
                       series=SeriesHeld(held=1000))
        self.assertIs(_lines(report)["series"][0], StatusCode.ERROR)
        report.observe(599.0, entries=0, waiting=[], late=[],
                       series=SeriesHeld(held=1000, evicted=("/web (b)",),
                                         evicted_bytes=700))
        code, text = _lines(report)["series"]
        self.assertEqual(code, StatusCode.ERROR)
        self.assertTrue(text.endswith("— 2 times in the last 10m"), text)
        report.observe(1300.0, entries=0, waiting=[], late=[],
                       series=SeriesHeld(held=1000))
        self.assertNotIn("series", _lines(report))

    def test_many_evicted_are_named_five_and_counted(self) -> None:
        report = _report(2048)
        evicted = tuple(f"/web ({letter})" for letter in "abcdefg")
        report.observe(0.0, entries=0, waiting=[], late=[],
                       series=SeriesHeld(held=1000, evicted=evicted,
                                         evicted_bytes=4096))
        text = _lines(report)["series"][1]
        self.assertIn("7 series were, the one written to longest ago first", text)
        self.assertIn("/web (e), and 2 more", text)

    def test_a_projection_past_the_ceiling_is_a_warn_naming_the_largest(
            self) -> None:
        report = _report(2048)
        report.observe(0.0, entries=0, waiting=[], late=[],
                       series=SeriesHeld(held=300, projection=30_000,
                                         needs=(("/gh (estate)", 29_000),
                                                ("/web (http)", 1_000))))
        self.assertEqual(_lines(report)["series.projection"], (
            StatusCode.WARN,
            "this configuration cannot be honored at this estate: its series "
            "would need 29.3 KiB, past their ceiling of 2.0 KiB: /gh (estate) "
            "28.3 KiB, /web (http) 1,000 B"))

    def test_a_projection_at_the_ceiling_is_honored(self) -> None:
        report = _report(2048)
        report.observe(0.0, entries=0, waiting=[], late=[],
                       series=SeriesHeld(held=300, projection=2048))
        self.assertNotIn("series.projection", _lines(report))

    def test_what_the_series_hold_is_a_fact_in_the_report(self) -> None:
        report = _report(8 * 1024 ** 2)
        report.observe(0.0, entries=0, waiting=[], late=[],
                       series=SeriesHeld(held=1536, projection=3 * 1024 ** 2))
        self.assertIn("the series hold 1.5 KiB of their ceiling of 8.0 MiB; at "
                      "today's estate this configuration would need 3.0 MiB",
                      report.report())


class EngineCeilingTests(TestCase):
    """What the engine feeds those lines from its own records, on its own tick."""

    def _engine(self, check: Check, ceiling: int,
                clock: Any = time.monotonic) -> tuple[Engine, StatusTree]:
        tree = StatusTree()
        engine = Engine([check], tree, poll_interval=0.02, clock=clock,
                        limits=Limits(memory_limit=None, series_limit=ceiling))
        return engine, tree

    @staticmethod
    def _tick_series(engine: Engine, now: float) -> None:
        # the series half of one tick: the sweep, then the observation it feeds
        engine._observe(now, engine._sweep_series())

    def test_too_large_says_so_on_the_first_tick_before_a_curve_shortens(
            self) -> None:
        check = _Estate(path="/gh", series_keep=100, subjects=3)
        engine, tree = self._engine(check, ceiling=4096)
        engine.start()
        try:
            found = _wait_for(lambda: "series.projection" in _engine_lines(tree))
        finally:
            engine.stop()
        self.assertTrue(found, _engine_lines(tree))
        code, text = _engine_lines(tree)["series.projection"]
        self.assertIs(code, StatusCode.WARN)
        self.assertIn("/gh (estate)", text)
        # nothing was shortened: every series still holds what it was given
        self.assertNotIn("series", _engine_lines(tree))
        for number in range(3):
            self.assertEqual(len(engine.series.window(
                SeriesKey("estate", "/gh", f"repo-{number:03d}"))), 1)

    def test_an_estate_that_grows_past_it_says_so_on_the_next_tick(self) -> None:
        check = _Estate(path="/gh", series_keep=10, subjects=1)
        engine, _tree = self._engine(check, ceiling=4096, clock=lambda: 0.0)
        engine.run_once()
        self._tick_series(engine, 1.0)
        self.assertNotIn("series.projection", _lines(engine._report))
        check.subjects = 40
        engine.run_once()
        self._tick_series(engine, 2.0)
        self.assertIn("series.projection", _lines(engine._report))

    def test_past_the_ceiling_the_oldest_series_goes_and_the_line_is_red(
            self) -> None:
        check = _Estate(path="/gh", series_keep=10, subjects=5)
        engine, _tree = self._engine(check, ceiling=10**6, clock=lambda: 0.0)
        engine.run_once()
        weight = engine.series.held()
        # a later run reads only the first two: the other three stop being written
        check.subjects = 2
        engine.run_once()
        # the same series, under a ceiling of what the first run weighed
        engine = Engine([check], StatusTree(), clock=lambda: 0.0,
                        series=engine.series,
                        limits=Limits(memory_limit=None, series_limit=weight))
        self._tick_series(engine, 1.0)
        code, text = _lines(engine._report)["series"]
        self.assertIs(code, StatusCode.ERROR)
        self.assertIn("so their curves are shortened", text)
        self.assertLessEqual(engine.series.held(), weight)
        # the two still written keep their history; a stopped one is gone first
        self.assertEqual(len(engine.series.window(
            SeriesKey("estate", "/gh", "repo-000"))), 2)
        self.assertEqual(engine.series.window(
            SeriesKey("estate", "/gh", "repo-002")), ())

    def test_a_sweep_that_raises_costs_a_line_and_never_the_beat(self) -> None:
        from little_sister import self_report

        class _Broken(MemoryStore):
            def sweep(self, keep: Any, *, ceiling: int | None = None) -> Any:
                raise OSError("disk full")

        self_report.runtime.forget()
        self.addCleanup(self_report.runtime.forget)
        tree = StatusTree()
        engine = Engine([_Estate(path="/gh", series_keep=10)], tree,
                        poll_interval=0.02, series=_Broken(),
                        limits=Limits(memory_limit=None))
        with self.assertLogs(level="ERROR"):
            engine.start()
            try:
                self.assertTrue(_wait_for(lambda: tree.snapshot(
                    f"{HEARTBEAT_PATH}/{ENGINE_REPORT}") is not None))
            finally:
                engine.stop()
        self.assertIn("series.sweep",
                      [line.slug for line in self_report.runtime.lines()])


class SystemPageTests(TestCase):
    """`/system` carries the series as the third line beside the declared load and
    the entries held: what they hold against their ceiling, and beside it what this
    configuration would need at today's estate — both as the last tick measured
    them, so the page and the engine's own lines name the same figures."""

    @staticmethod
    def _render(info: Any) -> str:
        from flask import render_template

        from little_sister import app as app_module
        with app_module.app.test_request_context():
            return render_template("_system_info.html", info=info)

    def test_the_series_stand_beside_their_ceiling_and_the_projection(
            self) -> None:
        engine = Engine([_Estate(path="/gh", series_keep=100, subjects=3)],
                        StatusTree(), clock=lambda: 0.0,
                        limits=Limits(memory_limit=None, series_limit=4096))
        engine.run_once()
        engine._observe(1.0, engine._sweep_series())
        info = engine.info()
        self.assertEqual((info.series_held, info.series_limit),
                         (engine.series.held(), 4096))
        self.assertGreater(info.series_projection, 4096)
        card = self._render(info).split("Series held")[1]
        self.assertIn(format_weight(info.series_held), card)
        self.assertIn("of 4.0 KiB", card)
        self.assertIn(f"{format_weight(info.series_projection)} at this estate",
                      card)

    def test_before_the_first_tick_nothing_is_projected(self) -> None:
        engine = Engine([_Estate(path="/gh", series_keep=100)], StatusTree(),
                        limits=Limits(memory_limit=None, series_limit=4096))
        info = engine.info()
        self.assertEqual((info.series_held, info.series_projection), (0, 0))
        card = self._render(info).split("Series held")[1]
        self.assertIn("0 B", card)
        self.assertNotIn("at this estate", card)


class SeriesLimitSettingTests(TestCase):
    """``series_limit`` in ``settings.yaml``: a positive whole number of bytes,
    the constant where the deployment says nothing, and the constant again, with a
    warning, where what it says cannot be a ceiling."""

    def _load(self, text: str) -> Any:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "settings.yaml"
            path.write_text(text)
            return load_config(path)

    def test_reads_the_limit_and_defaults_to_eight_mebibytes(self) -> None:
        self.assertEqual(self._load("series_limit: 1048576\n").series_limit,
                         1_048_576)
        self.assertEqual(self._load("timezone: UTC\n").series_limit, SERIES_LIMIT)
        self.assertEqual(SERIES_LIMIT, 8 * 1024 ** 2)

    def test_a_bad_limit_falls_back_with_a_warning(self) -> None:
        for value in ("plenty", "0", "-1"):
            with self.subTest(value=value), self.assertLogs(level="WARNING"):
                self.assertEqual(
                    self._load(f"series_limit: {value}\n").series_limit,
                    SERIES_LIMIT)


def _engine_lines(tree: StatusTree) -> dict[str, tuple[StatusCode | None, str]]:
    snap = tree.snapshot(f"{HEARTBEAT_PATH}/{ENGINE_REPORT}")
    if snap is None:
        return {}
    return {line.slug: (line.code, line.text) for line in snap.reasons}


def _wait_for(predicate: Any, timeout: float = 3.0) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        if predicate():
            return True
        time.sleep(0.01)
    return bool(predicate())
