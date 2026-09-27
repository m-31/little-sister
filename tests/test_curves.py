"""A measure's curve over its series (ADR-0092 decisions 4 and 5): where each
reading is drawn, where the line breaks, and what the two axes say.

The sentences under test are the plan's: a point sits on its series' own clock,
to scale, in the configured timezone; a reading without a value breaks the line and
is marked at its instant; two neighbors further apart than the node's freshness
tolerance have a hole between them, which breaks the line without a mark; one
missed poll is not a hole; and the line never crosses a hole. The geometry is read
off :func:`little_sister.curves.draw`, which the page renders as it is.
"""
from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from itertools import pairwise
from typing import Any
from unittest import TestCase, mock

from little_sister import config as config_module
from little_sister.curves import BOTTOM, LEFT, RIGHT, TOP, Curve, draw
from little_sister.measures import Measure
from little_sister.series import Placed, SeriesRecord
from little_sister.status import StatusCode

T0 = datetime(2026, 9, 26, 15, 0, tzinfo=UTC)
RESPONSE = Measure("response_ms", "ms", "Response time")
#: An `http` check every three minutes: its node goes stale after six (ADR-0079).
TOLERANCE = 360.0


def _placed(minute: float, response_ms: Any = 412, **extra: Any) -> Placed:
    """One `http` reading, taken ``minute`` minutes after T0 and placed there."""
    data: dict[str, Any] = {"status": None if response_ms is None else 200,
                            "response_ms": response_ms, **extra}
    moment = T0 + timedelta(minutes=minute)
    return Placed(SeriesRecord(data, moment, code=StatusCode.OK,
                               texts=(f"HTTP 200 in {response_ms} ms",)), moment)


def _series(*minutes: float, missing: tuple[float, ...] = ()) -> list[Placed]:
    return [_placed(minute, None if minute in missing else 400 + minute)
            for minute in minutes]


def _x(minute: float, first: float, last: float) -> float:
    return LEFT + (minute - first) / (last - first) * (RIGHT - LEFT)


def _run_minutes(curve: Curve) -> list[list[float]]:
    """Each unbroken stretch of line, as the minutes of the readings it joins."""
    return [[(point.at - T0).total_seconds() / 60 for point in run]
            for run in curve.runs]


class PlacementTests(TestCase):
    """A point sits where its series places the reading, and the axis is
    proportional to time, so a night without readings is a night wide."""

    def test_a_point_sits_where_its_reading_was_taken_to_scale(self) -> None:
        curve = draw(RESPONSE, _series(0, 1, 4), tolerance=None)
        run, = curve.runs
        for point, minute in zip(run, (0, 1, 4), strict=True):
            self.assertAlmostEqual(point.x, _x(minute, 0, 4), places=1)

    def test_the_place_is_the_series_clock_not_when_we_looked(self) -> None:
        # a run finished at 03:00 and read at 03:20 sits at 03:00: its series
        # orders it by its own `at`, and the curve reads the same place
        early, late = _placed(0), _placed(10)
        moved = Placed(replace(late.record, observed_at=T0 + timedelta(minutes=30)),
                       late.at)
        run, = draw(RESPONSE, [early, moved], tolerance=None).runs
        self.assertAlmostEqual(run[1].x, RIGHT, places=1)
        self.assertEqual(run[1].at, T0 + timedelta(minutes=10))

    def test_a_value_sits_to_scale_from_the_baseline(self) -> None:
        curve = draw(RESPONSE, [_placed(0, 0), _placed(1, 1000), _placed(2, 2000)],
                     tolerance=None)
        low, middle, high = curve.runs[0]
        self.assertAlmostEqual(low.y, BOTTOM, places=1)
        self.assertAlmostEqual(high.y, TOP, places=1)
        self.assertAlmostEqual(middle.y, (TOP + BOTTOM) / 2, places=1)

    def test_a_single_reading_is_a_dot_at_the_newest_end(self) -> None:
        curve = draw(RESPONSE, [_placed(0)], tolerance=TOLERANCE)
        self.assertEqual(curve.runs, ())
        dot, = curve.dots
        self.assertAlmostEqual(dot.x, RIGHT, places=1)
        self.assertEqual(curve.first, curve.last)


class BreakTests(TestCase):
    """A failure is marked; a hole is left plain; the line never crosses either."""

    def test_a_reading_without_a_value_breaks_the_line_and_is_marked(self) -> None:
        curve = draw(RESPONSE, _series(0, 3, 6, 9, 12, missing=(6,)),
                     tolerance=TOLERANCE)
        self.assertEqual(_run_minutes(curve), [[0, 3], [9, 12]])
        mark, = curve.marks
        self.assertAlmostEqual(mark.x, _x(6, 0, 12), places=1)
        self.assertEqual(mark.at, T0 + timedelta(minutes=6))
        self.assertEqual((curve.unvalued, curve.holes), (1, 0))

    def test_a_field_the_record_lacks_is_marked_as_a_null_is(self) -> None:
        # a projection reads a missing key as an empty one (ADR-0085): the reading
        # was taken, and it gave this measure no value
        readings = _series(0, 3, 6)
        readings[1] = Placed(SeriesRecord({"error": "check raised"},
                                          readings[1].at), readings[1].at)
        curve = draw(RESPONSE, readings, tolerance=TOLERANCE)
        self.assertEqual(len(curve.marks), 1)
        self.assertEqual(curve.runs, ())
        self.assertEqual(len(curve.dots), 2)

    def test_a_value_that_is_not_a_number_is_marked_too(self) -> None:
        for value in ("slow", True, [412], {"ms": 412}):
            with self.subTest(value=value):
                curve = draw(RESPONSE, [_placed(0), _placed(3, value), _placed(6)],
                             tolerance=TOLERANCE)
                self.assertEqual(len(curve.marks), 1)

    def test_a_stretch_longer_than_the_tolerance_is_a_plain_break(self) -> None:
        curve = draw(RESPONSE, _series(0, 3, 6, 30, 33), tolerance=TOLERANCE)
        self.assertEqual(_run_minutes(curve), [[0, 3, 6], [30, 33]])
        self.assertEqual(curve.marks, ())
        self.assertEqual((curve.unvalued, curve.holes), (0, 1))

    def test_one_missed_poll_is_not_a_hole(self) -> None:
        # six minutes apart is exactly the tolerance, which does not make the node
        # stale either
        curve = draw(RESPONSE, _series(0, 3, 9, 12), tolerance=TOLERANCE)
        self.assertEqual(_run_minutes(curve), [[0, 3, 9, 12]])
        self.assertEqual(curve.holes, 0)

    def test_a_hole_beside_a_failure_is_counted_as_a_hole(self) -> None:
        curve = draw(RESPONSE, _series(0, 3, 6, 40, 43, missing=(6,)),
                     tolerance=TOLERANCE)
        self.assertEqual(_run_minutes(curve), [[0, 3], [40, 43]])
        self.assertEqual((curve.unvalued, curve.holes), (1, 1))

    def test_the_line_never_crosses_a_hole_or_a_failure(self) -> None:
        minutes = [0, 3, 6, 9, 20, 23, 26, 29, 32, 60, 61, 62, 63, 90]
        missing = (9, 26, 61)
        curve = draw(RESPONSE, _series(*minutes, missing=missing),
                     tolerance=TOLERANCE)
        for run in curve.runs:
            for before, after in pairwise(run):
                self.assertLessEqual((after.at - before.at).total_seconds(),
                                     TOLERANCE)
        drawn = {point.at for run in curve.runs for point in run}
        drawn |= {dot.at for dot in curve.dots}
        self.assertFalse(drawn & {T0 + timedelta(minutes=m) for m in missing})
        self.assertEqual(len(drawn) + len(curve.marks), len(minutes))

    def test_a_reading_alone_between_breaks_is_a_dot(self) -> None:
        curve = draw(RESPONSE, _series(0, 3, 6, missing=(0, 6)),
                     tolerance=TOLERANCE)
        self.assertEqual(curve.runs, ())
        dot, = curve.dots
        self.assertEqual(dot.at, T0 + timedelta(minutes=3))

    def test_without_a_tolerance_nothing_is_a_hole(self) -> None:
        curve = draw(RESPONSE, _series(0, 3, 600), tolerance=None)
        self.assertEqual(_run_minutes(curve), [[0, 3, 600]])
        self.assertEqual(curve.holes, 0)

    def test_no_value_at_all_draws_the_marks_alone(self) -> None:
        curve = draw(RESPONSE, _series(0, 3, 6, missing=(0, 3, 6)),
                     tolerance=TOLERANCE)
        self.assertEqual((curve.runs, curve.dots, curve.ticks), ((), (), ()))
        self.assertEqual(len(curve.marks), 3)
        self.assertIsNone(curve.end)

    def test_the_newest_valued_reading_carries_the_end_dot(self) -> None:
        curve = draw(RESPONSE, _series(0, 3, 6), tolerance=TOLERANCE)
        self.assertEqual(curve.end.at, T0 + timedelta(minutes=6))
        failed_last = draw(RESPONSE, _series(0, 3, 6, missing=(6,)),
                           tolerance=TOLERANCE)
        self.assertIsNone(failed_last.end)


class AxisTests(TestCase):
    """The value axis starts at zero and reads in the measure's unit; the time
    axis reads in the configured timezone and `time_format` (decisions 3 and 4)."""

    def setUp(self) -> None:
        settings = mock.patch.object(
            config_module, "config",
            replace(config_module.config, timezone="Europe/Berlin",
                    time_format="%Y-%m-%d %H:%M:%S"))
        settings.start()
        self.addCleanup(settings.stop)

    def test_a_span_unit_writes_every_tick_as_a_span(self) -> None:
        curve = draw(RESPONSE, [_placed(0, 98), _placed(3, 1850), _placed(6, 640)],
                     tolerance=TOLERANCE)
        self.assertEqual([tick.text for tick in curve.ticks],
                         ["0 s", "500 ms", "1.0 s", "1.5 s", "2.0 s"])
        self.assertAlmostEqual(curve.ticks[0].y, BOTTOM, places=1)
        self.assertAlmostEqual(curve.ticks[-1].y, TOP, places=1)
        self.assertEqual(curve.unit_label, "")

    def test_a_long_span_steps_in_minutes(self) -> None:
        took = Measure("took_s", "s", "Backup")
        curve = draw(took, [_placed(0, took_s=600), _placed(3, took_s=2700)],
                     tolerance=TOLERANCE)
        self.assertEqual([tick.text for tick in curve.ticks],
                         ["0 s", "15m", "30m", "45m"])

    def test_a_free_text_unit_labels_the_axis_once(self) -> None:
        rate = Measure("rate", "req/s", "Requests")
        curve = draw(rate, [_placed(0, rate=3), _placed(3, rate=27)],
                     tolerance=TOLERANCE)
        self.assertEqual([tick.text for tick in curve.ticks],
                         ["0", "10", "20", "30"])
        self.assertEqual(curve.unit_label, "req/s")

    def test_values_below_zero_extend_the_axis_below_it(self) -> None:
        offset = Measure("offset_ms", "ms", "Clock offset")
        curve = draw(offset, [_placed(0, offset_ms=-40), _placed(3, offset_ms=90)],
                     tolerance=TOLERANCE)
        texts = [tick.text for tick in curve.ticks]
        self.assertEqual(texts[0], "-50 ms")
        self.assertIn("0 s", texts)

    def test_a_flat_series_still_has_an_axis(self) -> None:
        curve = draw(RESPONSE, [_placed(0, 0), _placed(3, 0)], tolerance=TOLERANCE)
        self.assertGreaterEqual(len(curve.ticks), 2)
        for point in curve.runs[0]:
            self.assertAlmostEqual(point.y, BOTTOM, places=1)

    def test_the_time_axis_reads_in_the_configured_zone(self) -> None:
        curve = draw(RESPONSE, _series(0, 3, 6), tolerance=TOLERANCE)
        self.assertEqual((curve.first, curve.last),
                         ("2026-09-26 17:00:00", "2026-09-26 17:06:00"))

    def test_and_in_the_configured_format(self) -> None:
        with mock.patch.object(
                config_module, "config",
                replace(config_module.config, timezone="America/New_York",
                        time_format="%d.%m. %H:%M")):
            curve = draw(RESPONSE, _series(0, 6), tolerance=TOLERANCE)
        self.assertEqual((curve.first, curve.last), ("26.09. 11:00", "26.09. 11:06"))


class ReadoutTests(TestCase):
    """What the curve says in words: each reading's time and value where the
    pointer is, and the summary beside the title — the table below carries every
    value too, so nothing is only a tooltip."""

    def setUp(self) -> None:
        settings = mock.patch.object(
            config_module, "config",
            replace(config_module.config, timezone="Europe/Berlin",
                    time_format="%Y-%m-%d %H:%M:%S"))
        settings.start()
        self.addCleanup(settings.stop)

    def test_each_reading_says_when_and_what_where_the_pointer_is(self) -> None:
        curve = draw(RESPONSE, _series(0, 3, 6, missing=(3,)), tolerance=TOLERANCE)
        self.assertEqual([strip.title for strip in curve.hover],
                         ["2026-09-26 17:00:00 · 400 ms",
                          "2026-09-26 17:03:00 · no value",
                          "2026-09-26 17:06:00 · 406 ms"])

    def test_the_pointer_finds_the_nearest_reading_anywhere_across_the_plot(
            self) -> None:
        curve = draw(RESPONSE, _series(0, 1, 4), tolerance=None)
        self.assertAlmostEqual(curve.hover[0].x, LEFT, places=1)
        self.assertAlmostEqual(sum(strip.width for strip in curve.hover),
                               RIGHT - LEFT, places=1)
        boundary = curve.hover[1].x
        self.assertAlmostEqual(boundary, (_x(0, 0, 4) + _x(1, 0, 4)) / 2, places=1)

    def test_the_summary_names_the_newest_the_lowest_and_the_highest(self) -> None:
        curve = draw(RESPONSE, [_placed(0, 98), _placed(3, 1850), _placed(6, None),
                                _placed(40, 412)], tolerance=TOLERANCE)
        self.assertEqual((curve.newest, curve.lowest, curve.highest),
                         ("412 ms", "98 ms", "1.9 s"))
        self.assertEqual((curve.readings, curve.unvalued, curve.holes), (4, 1, 1))

    def test_a_newest_reading_without_a_value_says_so(self) -> None:
        curve = draw(RESPONSE, _series(0, 3, missing=(3,)), tolerance=TOLERANCE)
        self.assertEqual(curve.newest, "no value")
