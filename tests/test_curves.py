"""A measure's curve over its series (ADR-0092 decisions 4 and 5, as ADR-0096
decisions 3 and 4 amend them): where each reading is drawn, where the line breaks,
and what the two axes say.

The sentences under test: a point sits on its series' own clock, to scale, in the
configured timezone; a reading that failed — its record carries an `error` — breaks
the line and is marked at its instant; one that answered but gives the measure no
number breaks it with no mark, as two neighbors further apart than the node's
freshness tolerance do; one missed poll is not a hole; the line crosses none of them;
and a size steps in powers of two of a unit. The geometry is read off
:func:`little_sister.curves.draw`, which the page renders as it is.
"""
from __future__ import annotations

import functools
from collections.abc import Iterator
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from itertools import pairwise
from typing import Any, ClassVar
from unittest import TestCase, mock
from zoneinfo import ZoneInfo

from little_sister import config as config_module
from little_sister.curves import (
    BOTTOM,
    COLUMNS,
    LEFT,
    RIGHT,
    TOP,
    Curve,
    Point,
    draw,
    drawable,
    time_labels,
)
from little_sister.measures import Measure
from little_sister.series import Placed, SeriesRecord
from little_sister.spans import local_time
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


def _failed(minute: float) -> Placed:
    """A request that never answered, as the `http` check records one: its numbers
    null, and why beside them (ADR-0085 decision 3)."""
    return _placed(minute, None, error="request failed: timed out")


def _series(*minutes: float, failed: tuple[float, ...] = (),
            empty: tuple[float, ...] = ()) -> list[Placed]:
    """Readings ``minutes`` apart: those in ``failed`` did not answer, and those in
    ``empty`` answered without a number for the measure."""
    return [_failed(minute) if minute in failed
            else _placed(minute, None if minute in empty else 400 + minute)
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
    """A reading that failed is marked; one that answered without a number, and a
    hole, are left plain; the line crosses none of them (ADR-0096 decision 4)."""

    def test_a_reading_that_failed_breaks_the_line_and_is_marked(self) -> None:
        curve = draw(RESPONSE, _series(0, 3, 6, 9, 12, failed=(6,)),
                     tolerance=TOLERANCE)
        self.assertEqual(_run_minutes(curve), [[0, 3], [9, 12]])
        mark, = curve.marks
        self.assertAlmostEqual(mark.x, _x(6, 0, 12), places=1)
        self.assertEqual(mark.at, T0 + timedelta(minutes=6))
        self.assertEqual((curve.failed, curve.unvalued, curve.holes), (1, 0, 0))

    def test_the_engine_s_record_of_a_check_that_raised_is_marked(self) -> None:
        # `{"error": …}` and nothing else: every field is missing, and it failed
        readings = _series(0, 3, 6)
        readings[1] = Placed(SeriesRecord({"error": "check raised"},
                                          readings[1].at), readings[1].at)
        curve = draw(RESPONSE, readings, tolerance=TOLERANCE)
        self.assertEqual(len(curve.marks), 1)
        self.assertEqual(curve.runs, ())
        self.assertEqual(len(curve.dots), 2)

    def test_an_error_that_is_null_is_no_failure(self) -> None:
        readings = [_placed(0, error=None), _placed(3, None, error=None),
                    _placed(6, error=None)]
        curve = draw(RESPONSE, readings, tolerance=TOLERANCE)
        self.assertEqual(curve.marks, ())
        self.assertEqual((curve.failed, curve.unvalued), (0, 1))

    def test_a_reading_that_answered_without_a_number_breaks_it_plainly(
            self) -> None:
        curve = draw(RESPONSE, _series(0, 3, 6, 9, 12, empty=(6,)),
                     tolerance=TOLERANCE)
        self.assertEqual(_run_minutes(curve), [[0, 3], [9, 12]])
        self.assertEqual(curve.marks, ())
        self.assertEqual((curve.failed, curve.unvalued, curve.holes), (0, 1, 0))

    def test_a_field_the_reading_lacks_breaks_it_plainly(self) -> None:
        # a field a release added, missing from every reading kept before it
        readings = _series(0, 3, 6)
        before = Placed(SeriesRecord({"status": 200}, T0 - timedelta(minutes=3)),
                        T0 - timedelta(minutes=3))
        curve = draw(RESPONSE, [before, *readings], tolerance=TOLERANCE)
        self.assertEqual(curve.marks, ())
        self.assertEqual(_run_minutes(curve), [[0, 3, 6]])

    def test_a_value_that_is_not_a_number_breaks_it_plainly(self) -> None:
        for value in ("slow", True, [412], {"ms": 412}):
            with self.subTest(value=value):
                curve = draw(RESPONSE, [_placed(0), _placed(3, value), _placed(6)],
                             tolerance=TOLERANCE)
                self.assertEqual(curve.marks, ())
                self.assertEqual(curve.runs, ())

    def test_a_failed_reading_is_marked_on_every_curve_of_its_series(self) -> None:
        readings = _series(0, 3, 6, failed=(3,))
        status = Measure("status", "", "Status code")
        for measure in (RESPONSE, status):
            with self.subTest(measure=measure.field):
                self.assertEqual(len(draw(measure, readings,
                                          tolerance=TOLERANCE).marks), 1)

    def test_a_stretch_longer_than_the_tolerance_is_a_plain_break(self) -> None:
        curve = draw(RESPONSE, _series(0, 3, 6, 30, 33), tolerance=TOLERANCE)
        self.assertEqual(_run_minutes(curve), [[0, 3, 6], [30, 33]])
        self.assertEqual(curve.marks, ())
        self.assertEqual((curve.failed, curve.holes), (0, 1))

    def test_one_missed_poll_is_not_a_hole(self) -> None:
        # six minutes apart is exactly the tolerance, which does not make the node
        # stale either
        curve = draw(RESPONSE, _series(0, 3, 9, 12), tolerance=TOLERANCE)
        self.assertEqual(_run_minutes(curve), [[0, 3, 9, 12]])
        self.assertEqual(curve.holes, 0)

    def test_a_hole_beside_a_failure_is_counted_as_a_hole(self) -> None:
        curve = draw(RESPONSE, _series(0, 3, 6, 40, 43, failed=(6,)),
                     tolerance=TOLERANCE)
        self.assertEqual(_run_minutes(curve), [[0, 3], [40, 43]])
        self.assertEqual((curve.failed, curve.holes), (1, 1))

    def test_the_line_never_crosses_a_hole_a_failure_or_an_empty_reading(
            self) -> None:
        minutes = [0, 3, 6, 9, 20, 23, 26, 29, 32, 60, 61, 62, 63, 90]
        failed, empty = (9, 61), (26,)
        curve = draw(RESPONSE, _series(*minutes, failed=failed, empty=empty),
                     tolerance=TOLERANCE)
        for run in curve.runs:
            for before, after in pairwise(run):
                self.assertLessEqual((after.at - before.at).total_seconds(),
                                     TOLERANCE)
        drawn = {point.at for run in curve.runs for point in run}
        drawn |= {dot.at for dot in curve.dots}
        self.assertFalse(drawn & {T0 + timedelta(minutes=m) for m in failed + empty})
        self.assertEqual(len(drawn) + len(curve.marks) + curve.unvalued, len(minutes))

    def test_a_reading_alone_between_breaks_is_a_dot(self) -> None:
        curve = draw(RESPONSE, _series(0, 3, 6, failed=(0,), empty=(6,)),
                     tolerance=TOLERANCE)
        self.assertEqual(curve.runs, ())
        dot, = curve.dots
        self.assertEqual(dot.at, T0 + timedelta(minutes=3))

    def test_without_a_tolerance_nothing_is_a_hole(self) -> None:
        curve = draw(RESPONSE, _series(0, 3, 600), tolerance=None)
        self.assertEqual(_run_minutes(curve), [[0, 3, 600]])
        self.assertEqual(curve.holes, 0)

    def test_failures_alone_draw_their_marks_alone(self) -> None:
        curve = draw(RESPONSE, _series(0, 3, 6, failed=(0, 3, 6)),
                     tolerance=TOLERANCE)
        self.assertEqual((curve.runs, curve.dots, curve.ticks), ((), (), ()))
        self.assertEqual(len(curve.marks), 3)
        self.assertIsNone(curve.end)
        self.assertEqual(curve.valued, 0)

    def test_how_many_readings_have_a_number_is_counted(self) -> None:
        # what says whether a measure has anything to draw at all
        curve = draw(RESPONSE, _series(0, 3, 6, 9, failed=(3,), empty=(6,)),
                     tolerance=TOLERANCE)
        self.assertEqual((curve.readings, curve.valued), (4, 2))
        nothing = draw(RESPONSE, _series(0, 3, empty=(0, 3)), tolerance=TOLERANCE)
        self.assertEqual((nothing.valued, nothing.marks), (0, ()))

    def test_the_newest_valued_reading_carries_the_end_dot(self) -> None:
        curve = draw(RESPONSE, _series(0, 3, 6), tolerance=TOLERANCE)
        self.assertEqual(curve.end.at, T0 + timedelta(minutes=6))
        failed_last = draw(RESPONSE, _series(0, 3, 6, failed=(6,)),
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

    def test_a_size_steps_in_powers_of_two_of_a_unit(self) -> None:
        # ADR-0096 decision 3: every tick lands on a whole unit and names it, and
        # the axis carries no label
        rss = Measure("rss_kb", "KiB", "Resident memory")
        curve = draw(rss, [_placed(0, rss_kb=331_200), _placed(3, rss_kb=665_232)],
                     tolerance=TOLERANCE)
        self.assertEqual([tick.text for tick in curve.ticks],
                         ["0 B", "256 MiB", "512 MiB", "768 MiB"])
        self.assertEqual(curve.unit_label, "")
        used = Measure("mem_used_kb", "KiB", "Memory used")
        curve = draw(used, [_placed(0, mem_used_kb=19_169_728)], tolerance=TOLERANCE)
        self.assertEqual([tick.text for tick in curve.ticks],
                         ["0 B", "8 GiB", "16 GiB", "24 GiB"])

    def test_the_page_s_span_puts_every_curve_on_one_time_axis(self) -> None:
        # ADR-0097 decision 1: curves read by different checks stand one above the
        # other, each placed on the page's span rather than on its own
        span = (T0, T0 + timedelta(minutes=40))
        curve = draw(RESPONSE, _series(10, 20), tolerance=None, span=span)
        run, = curve.runs
        self.assertAlmostEqual(run[0].x, _x(10, 0, 40), places=1)
        self.assertAlmostEqual(run[1].x, _x(20, 0, 40), places=1)
        self.assertEqual((curve.first, curve.last),
                         ("2026-09-26 17:00:00", "2026-09-26 17:40:00"))

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
        curve = draw(RESPONSE, _series(0, 3, 6, 9, failed=(3,), empty=(6,)),
                     tolerance=TOLERANCE)
        self.assertEqual([strip.title for strip in curve.hover],
                         ["2026-09-26 17:00:00 · 400 ms",
                          "2026-09-26 17:03:00 · failed",
                          "2026-09-26 17:06:00 · no value",
                          "2026-09-26 17:09:00 · 409 ms"])

    def test_the_pointer_finds_the_nearest_reading_anywhere_across_the_plot(
            self) -> None:
        curve = draw(RESPONSE, _series(0, 1, 4), tolerance=None)
        self.assertAlmostEqual(curve.hover[0].x, LEFT, places=1)
        self.assertAlmostEqual(sum(strip.width for strip in curve.hover),
                               RIGHT - LEFT, places=1)
        boundary = curve.hover[1].x
        self.assertAlmostEqual(boundary, (_x(0, 0, 4) + _x(1, 0, 4)) / 2, places=1)

    def test_the_summary_names_the_newest_the_lowest_and_the_highest(self) -> None:
        curve = draw(RESPONSE, [_placed(0, 98), _placed(3, 1850), _failed(6),
                                _placed(40, 412)], tolerance=TOLERANCE)
        self.assertEqual((curve.newest, curve.lowest, curve.highest),
                         ("412 ms", "98 ms", "1.9 s"))
        self.assertEqual((curve.readings, curve.failed, curve.holes), (4, 1, 1))

    def test_a_newest_reading_that_failed_or_had_no_value_says_which(self) -> None:
        self.assertEqual(draw(RESPONSE, _series(0, 3, failed=(3,)),
                              tolerance=TOLERANCE).newest, "failed")
        self.assertEqual(draw(RESPONSE, _series(0, 3, empty=(3,)),
                              tolerance=TOLERANCE).newest, "no value")


class DrawableTests(TestCase):
    """Whether a measure has a curve over a series, answered without drawing it
    (plan item 0d): by the rules the curve itself is drawn by, and reading no further
    than the first reading that gives the measure a number."""

    CASES: ClassVar[dict[str, list[Placed]]] = {
        "a number": [_placed(0, 412)],
        "zero": [_placed(0, 0)],
        "a fraction": [_placed(0, 0.5)],
        "no reading": [],
        "null": [_placed(0, None)],
        "a field the record lacks": [
            Placed(SeriesRecord({"status": 200}, T0, code=StatusCode.OK), T0)],
        "text": [_placed(0, "412")],
        "a boolean": [_placed(0, True)],
        "not finite": [_placed(0, float("nan")), _placed(1, float("inf"))],
        "a number in a reading that failed": [_placed(0, 412, error="timed out")],
        "a number beside a null error": [_placed(0, 412, error=None)],
        "a number after a failure and a null": [_failed(0), _placed(1, None),
                                                _placed(2, 7)],
    }

    def test_it_answers_as_the_curve_does(self) -> None:
        for name, readings in self.CASES.items():
            with self.subTest(case=name):
                self.assertEqual(
                    drawable(RESPONSE, readings),
                    draw(RESPONSE, readings, tolerance=TOLERANCE).valued > 0)

    def test_a_number_that_did_not_fail_is_a_curve_and_nothing_else_is(self) -> None:
        self.assertEqual(
            {name for name, readings in self.CASES.items()
             if drawable(RESPONSE, readings)},
            {"a number", "zero", "a fraction", "a number beside a null error",
             "a number after a failure and a null"})

    def test_it_reads_no_further_than_the_first_number(self) -> None:
        def readings() -> Iterator[Placed]:
            yield _placed(0, None)
            yield _placed(1, 412)
            raise AssertionError("read past the first reading with a number")
        self.assertTrue(drawable(RESPONSE, readings()))


class WrittenTimesTests(TestCase):
    """How a curve writes an instant — a hover strip's title and the axis ends — is
    its caller's to hand it (plan item 0e): the configured zone and format unless the
    caller says otherwise, and a page drawing several curves over one series' readings
    hands them all one writer that remembers what it wrote."""

    def test_every_instant_it_writes_is_written_by_the_writer_it_is_given(self) -> None:
        written: list[datetime] = []

        def times(at: datetime) -> str:
            written.append(at)
            return f"<{at.minute}>"
        curve = draw(RESPONSE, _series(0, 3, 6, failed=(3,)), tolerance=TOLERANCE,
                     times=times)
        self.assertEqual((curve.first, curve.last), ("<0>", "<6>"))
        self.assertEqual([strip.title for strip in curve.hover],
                         ["<0> · 400 ms", "<3> · failed", "<6> · 406 ms"])
        self.assertEqual(sorted({at.minute for at in written}), [0, 3, 6])

    def test_one_that_remembers_draws_the_curve_the_configured_one_does(self) -> None:
        readings = _series(0, 3, 6, 9, 30, failed=(6,), empty=(3,))
        remembering = functools.cache(local_time)
        for span in (None, (T0 - timedelta(minutes=5), T0 + timedelta(minutes=40))):
            with self.subTest(span=span):
                self.assertEqual(
                    draw(RESPONSE, readings, tolerance=TOLERANCE, span=span,
                         times=remembering),
                    draw(RESPONSE, readings, tolerance=TOLERANCE, span=span))


BERLIN = ZoneInfo("Europe/Berlin")


def _local(text: str) -> datetime:
    """An instant as a clock in the configured zone read it."""
    return datetime.fromisoformat(text).replace(tzinfo=BERLIN)


class TimeLabelTests(TestCase):
    """The time axis is labeled at round times in the configured timezone (ADR-0098
    decision 4): the smallest step of the ladder that puts at most six labels on it,
    stepped in local time, each label as short as its step allows."""

    def setUp(self) -> None:
        settings = mock.patch.object(
            config_module, "config",
            replace(config_module.config, timezone="Europe/Berlin",
                    time_format="%Y-%m-%d %H:%M:%S"))
        settings.start()
        self.addCleanup(settings.stop)

    def _labels(self, first: str, last: str) -> list[str]:
        return [text for _at, text in time_labels(_local(first), _local(last))]

    def test_six_hours_are_labeled_by_the_hour(self) -> None:
        self.assertEqual(self._labels("2026-09-30T14:07", "2026-09-30T20:07"),
                         ["15:00", "16:00", "17:00", "18:00", "19:00", "20:00"])

    def test_a_day_by_six_hours_with_the_date_at_midnight(self) -> None:
        self.assertEqual(self._labels("2026-09-29T15:25", "2026-09-30T15:25"),
                         ["18:00", "09-30", "06:00", "12:00"])

    def test_a_label_falls_on_a_round_time_of_the_configured_zone(self) -> None:
        # 15:00 in Berlin is 13:00 in UTC: the clock the page reads is the zone's
        for at, _text in time_labels(_local("2026-09-30T14:07"),
                                     _local("2026-09-30T20:07")):
            with self.subTest(at=at):
                local = at.astimezone(BERLIN)
                self.assertEqual((local.minute, local.second), (0, 0))

    def test_a_month_by_the_week_on_mondays(self) -> None:
        labels = time_labels(_local("2026-09-01T00:00"), _local("2026-09-30T00:00"))
        self.assertEqual([text for _at, text in labels],
                         ["09-07", "09-14", "09-21", "09-28"])
        self.assertEqual({at.astimezone(BERLIN).weekday() for at, _text in labels}, {0})

    def test_a_year_by_the_quarter_and_seven_by_two_years(self) -> None:
        self.assertEqual(self._labels("2025-10-01T00:00", "2026-09-30T00:00"),
                         ["2026-01", "2026-04", "2026-07"])
        self.assertEqual(self._labels("2019-10-01T00:00", "2026-09-30T00:00"),
                         ["2020", "2022", "2024", "2026"])

    def test_the_day_the_clocks_go_back_is_labeled_as_the_clock_read_it(self) -> None:
        # 25 hours on 2026-10-25 in Berlin: six-hourly labels at the local hours, the
        # first two seven real hours apart
        labels = time_labels(_local("2026-10-24T23:00"), _local("2026-10-25T23:00"))
        self.assertEqual([text for _at, text in labels],
                         ["10-25", "06:00", "12:00", "18:00"])
        first, second = (at for at, _text in labels[:2])
        self.assertEqual((second - first).total_seconds(), 7 * 3600)

    def test_an_hour_the_clocks_skip_is_not_labeled(self) -> None:
        # 2026-03-29 in Berlin: 02:00 never happened
        self.assertEqual(self._labels("2026-03-29T00:30", "2026-03-29T05:30"),
                         ["01:00", "03:00", "04:00", "05:00"])

    def test_a_window_of_eight_minutes_is_labeled_every_two(self) -> None:
        # A minute apart, seven labels would be one too many, and the next step
        # used to be five minutes: one label on the whole axis.
        self.assertEqual(self._labels("2026-10-03T19:12", "2026-10-03T19:20"),
                         ["19:14", "19:16", "19:18"])

    def test_a_short_window_carries_at_least_three_labels(self) -> None:
        start = _local("2026-10-03T19:12")
        for minutes in range(4, 13):
            for offset in (0, 20, 59):
                first = start + timedelta(seconds=offset)
                with self.subTest(minutes=minutes, offset=offset):
                    labels = time_labels(first, first + timedelta(minutes=minutes))
                    self.assertGreaterEqual(len(labels), 3)
                    self.assertLessEqual(len(labels), 6)

    def test_six_minutes_are_still_labeled_by_the_minute(self) -> None:
        self.assertEqual(self._labels("2026-10-03T19:12", "2026-10-03T19:18"),
                         ["19:13", "19:14", "19:15", "19:16", "19:17"])

    def test_two_minutes_apart_a_label_falls_on_an_even_minute(self) -> None:
        for at, _text in time_labels(_local("2026-10-03T19:11:30"),
                                     _local("2026-10-03T19:22:10")):
            with self.subTest(at=at):
                local = at.astimezone(BERLIN)
                self.assertEqual((local.minute % 2, local.second), (0, 0))

    def test_never_more_than_six(self) -> None:
        start = _local("2026-09-30T00:00")
        for minutes in (3, 17, 50, 95, 400, 1300, 3000, 9000, 50000, 400000, 4000000):
            with self.subTest(minutes=minutes):
                labels = time_labels(start, start + timedelta(minutes=minutes))
                self.assertLessEqual(len(labels), 6)
                self.assertTrue(labels)


def _minute_series(values: list[float | None]) -> list[Placed]:
    """A reading a minute from T0 for each value; ``None`` a failed reading."""
    return [_failed(minute) if value is None else _placed(minute, value)
            for minute, value in enumerate(values)]


class ColumnTests(TestCase):
    """A window with more readings than a plot has columns is drawn column by column:
    each column's first, last, lowest and highest reading (ADR-0098 decision 5)."""

    def test_no_more_readings_than_columns_are_drawn_one_by_one(self) -> None:
        curve = draw(RESPONSE, _minute_series([400.0] * COLUMNS), tolerance=TOLERANCE)
        self.assertEqual(sum(len(run) for run in curve.runs), COLUMNS)
        self.assertEqual(len(curve.hover), COLUMNS)

    def test_a_column_draws_its_first_last_lowest_and_highest(self) -> None:
        values = [float(400 + (minute * 37) % 11) for minute in range(3000)]
        curve = draw(RESPONSE, _minute_series(values), tolerance=TOLERANCE)
        points = [point for run in curve.runs for point in run]
        self.assertLessEqual(len(points), 4 * COLUMNS)
        self.assertLessEqual(len(curve.hover), COLUMNS)

        def column(at: datetime) -> int:
            # the column a reading falls in: its share of the window, in columns
            return min(COLUMNS - 1,
                       int((at - T0).total_seconds() / (2999 * 60.0) * COLUMNS))
        held: dict[int, list[float]] = {}
        for minute, value in enumerate(values):
            held.setdefault(column(T0 + timedelta(minutes=minute)), []).append(value)
        drawn: dict[int, list[Point]] = {}
        for point in points:
            drawn.setdefault(column(point.at), []).append(point)
        self.assertEqual(set(drawn), set(held))
        for index, kept in held.items():
            with self.subTest(column=index):
                ats = sorted(point.at for point in drawn[index])
                values_drawn = {point.value for point in drawn[index]}
                self.assertIn(min(kept), values_drawn)
                self.assertIn(max(kept), values_drawn)
                self.assertEqual(values_drawn - set(kept), set())
                self.assertEqual(len(ats), len(set(ats)))

    def test_no_spike_is_lost(self) -> None:
        values = [400.0] * 3000
        values[1234] = 9000.0
        values[2345] = 3.0
        curve = draw(RESPONSE, _minute_series(values), tolerance=TOLERANCE)
        drawn = {point.value for run in curve.runs for point in run}
        self.assertIn(9000.0, drawn)
        self.assertIn(3.0, drawn)
        self.assertEqual((curve.lowest, curve.highest), ("3 ms", "9.0 s"))

    def test_a_column_says_what_it_holds(self) -> None:
        values = [float(400 + minute % 10) for minute in range(3000)]
        curve = draw(RESPONSE, _minute_series(values), tolerance=TOLERANCE,
                     times=lambda at: f"{at.hour:02d}:{at.minute:02d}")
        strip = curve.hover[1]
        self.assertRegex(strip.title, r"^\d+ ms–\d+ ms over \d+ readings, "
                                      r"\d\d:\d\d–\d\d:\d\d$")

    def test_a_column_whose_readings_read_alike_says_their_value_once(self) -> None:
        # 400.1 ms and 400.4 ms are both written 400 ms: a range between two values
        # that read the same is that one value
        values: list[float | None] = [400.1 if minute % 2 else 400.4
                                      for minute in range(3000)]
        curve = draw(RESPONSE, _minute_series(values), tolerance=TOLERANCE,
                     times=lambda at: f"{at.hour:02d}:{at.minute:02d}")
        self.assertRegex(curve.hover[1].title,
                         r"^400 ms over \d+ readings, \d\d:\d\d–\d\d:\d\d$")

    def test_a_failed_reading_marks_its_column_and_counts(self) -> None:
        values: list[float | None] = [400.0] * 3000
        for minute in (100, 101, 2500):
            values[minute] = None
        curve = draw(RESPONSE, _minute_series(values), tolerance=TOLERANCE)
        self.assertEqual(curve.failed, 3)
        self.assertEqual(len(curve.marks), 2)      # the two first share a column
        self.assertTrue(any(" failed" in strip.title for strip in curve.hover))

    def test_a_stretch_without_readings_breaks_it_where_a_column_wide(self) -> None:
        # three thousand minutes are about nine a column: an eight-minute stretch is
        # longer than the six the tolerance allows and narrower than a column — this
        # one across the edge between two columns — and a two-hundred-minute one far
        # wider
        minutes = [minute for minute in range(3000)
                   if not 1005 < minute < 1013 and not 2000 < minute < 2200]
        readings = [_placed(minute, 400) for minute in minutes]
        curve = draw(RESPONSE, readings, tolerance=TOLERANCE)
        self.assertEqual(curve.holes, 2)                  # both are counted
        self.assertEqual(len(curve.runs), 2)              # only the wide one breaks it
