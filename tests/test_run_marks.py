"""A run is a mark at its own time (ADR-0106 decision 5, as ADR-0111 completes it):
where each run of a series is drawn, what its mark says of how it stood, what gives
way where runs crowd, and what the plot says in words.

The sentences under test: a run is a record with an identity; without a measure it is
a tick whose height says how its reading stood, with a measure a stem from the
baseline to its value; a run that failed has a hollow ring for a head and is marked in
the lane, one that warned has the warning's triangle, one that passed a filled head
and one that kept no verdict none; no line joins two runs; a passing run's head gives
way where it would run into another head, and the newest run keeps its own; a column's
strip names what the column holds; and the summary counts every run in the window. The
geometry is read off :func:`little_sister.curves.draw_runs`, which the page renders as
it is.
"""
from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from typing import Any
from unittest import TestCase, mock
from zoneinfo import ZoneInfo

from little_sister import config as config_module
from little_sister.curves import (
    BOTTOM,
    COLUMNS,
    FAILED,
    HEAD,
    LEFT,
    PASSED,
    RIGHT,
    TICKS_BOTTOM,
    TICKS_HEIGHT,
    UNJUDGED,
    WARNED,
    draw_runs,
    runs_drawable,
    runs_of,
)
from little_sister.measures import Measure
from little_sister.series import Placed, SeriesRecord
from little_sister.status import StatusCode

T0 = datetime(2026, 9, 2, 12, 0, tzinfo=UTC)
RUN_TIME = Measure("seconds", "s", "Run time")
WIDTH = RIGHT - LEFT
COLUMN = WIDTH / COLUMNS


def _run(hour: float, code: StatusCode | None = StatusCode.OK,
         seconds: Any = 600, **extra: Any) -> Placed:
    """One run that finished ``hour`` hours after T0, as its series keeps it."""
    moment = T0 + timedelta(hours=hour)
    data: dict[str, Any] = {"seconds": seconds, **extra}
    return Placed(SeriesRecord(data, moment, identity=f"run-{hour}", code=code,
                               texts=() if code is None else (f"ran {seconds}s",)),
                  moment)


def _x(hour: float, last: float) -> float:
    return LEFT + hour / last * WIDTH


def _stems(curve: Any) -> dict[float, Any]:
    """A plot's stems by the hour its run finished at."""
    return {(stem.at - T0).total_seconds() / 3600: stem for stem in curve.stems}


class _InBerlin(TestCase):
    """Every time the plot says is written in the configured zone and format."""

    def setUp(self) -> None:
        settings = mock.patch.object(
            config_module, "config",
            replace(config_module.config, timezone="Europe/Berlin",
                    time_format="%Y-%m-%d %H:%M"))
        settings.start()
        self.addCleanup(settings.stop)
        self.assertEqual(config_module.config.tzinfo, ZoneInfo("Europe/Berlin"))


class RunsOfTests(TestCase):
    """Which of a series' readings are runs (ADR-0111 decision 5)."""

    def test_a_run_is_a_record_with_an_identity(self) -> None:
        moment = T0
        state = Placed(SeriesRecord({"open": True}, moment, state="open"), moment)
        plain = Placed(SeriesRecord({"load": 1.5}, moment), moment)
        run = _run(1)
        self.assertEqual(runs_of([state, plain, run]), [run])

    def test_a_series_of_states_has_no_runs(self) -> None:
        moment = T0
        self.assertEqual(
            runs_of([Placed(SeriesRecord({}, moment, state="expired"), moment)]), [])


class TickTests(_InBerlin):
    """Without a measure a run is a tick, and its height says how it stood."""

    RUNS = (_run(0, None), _run(10), _run(20, StatusCode.WARN),
            _run(30, StatusCode.ERROR))

    def test_a_run_is_a_mark_at_its_own_instant_to_scale(self) -> None:
        curve = draw_runs(None, [_run(0), _run(6), _run(24)])
        for hour, stem in _stems(curve).items():
            self.assertAlmostEqual(stem.x, _x(hour, 24), places=1)

    def test_a_ticks_height_says_how_its_run_stood(self) -> None:
        stems = _stems(draw_runs(None, self.RUNS))
        self.assertEqual([stem.verdict for stem in stems.values()],
                         [UNJUDGED, PASSED, WARNED, FAILED])
        # half as tall as a passing run's where nothing says how it stood; a
        # warning between a pass and a failure
        self.assertEqual([TICKS_BOTTOM - stem.y for stem in stems.values()],
                         [6.0, 12.0, 24.0, 36.0])

    def test_only_a_run_that_warned_or_failed_has_a_head(self) -> None:
        stems = _stems(draw_runs(None, self.RUNS))
        self.assertEqual([stem.head for stem in stems.values()],
                         [False, False, True, True])

    def test_the_plot_is_as_tall_as_its_marks_and_has_no_value_axis(self) -> None:
        curve = draw_runs(None, self.RUNS)
        self.assertEqual((curve.height, curve.bottom), (TICKS_HEIGHT, TICKS_BOTTOM))
        self.assertEqual(curve.ticks, ())
        self.assertEqual(curve.label, "Runs")
        self.assertTrue(curve.of_runs)

    def test_a_failure_is_told_by_its_tick_and_not_in_a_lane(self) -> None:
        self.assertEqual(draw_runs(None, self.RUNS).marks, ())

    def test_no_line_joins_two_runs(self) -> None:
        for measure in (None, RUN_TIME):
            with self.subTest(measure=measure):
                curve = draw_runs(measure, self.RUNS)
                self.assertEqual((curve.runs, curve.dots, curve.paths, curve.end),
                                 ((), (), (), None))

    def test_a_code_that_is_no_verdict_is_none(self) -> None:
        undefined = _stems(draw_runs(None, [_run(0, StatusCode.UNDEFINED), _run(9)]))
        self.assertEqual(undefined[0.0].verdict, UNJUDGED)


class StemTests(_InBerlin):
    """With a measure a run is a stem from the baseline to its value."""

    def test_a_stem_ends_at_its_runs_value(self) -> None:
        # 0 s at the baseline; the axis ends on a whole step past the highest
        curve = draw_runs(RUN_TIME, [_run(0, seconds=600), _run(10, seconds=1200),
                                     _run(20, seconds=300)])
        top = max(tick.y for tick in curve.ticks)
        self.assertEqual(top, BOTTOM)
        stems = _stems(curve)
        self.assertLess(stems[10.0].y, stems[0.0].y)
        self.assertLess(stems[0.0].y, stems[20.0].y)
        self.assertLess(stems[20.0].y, BOTTOM)
        # to scale: twice the value is twice the stem
        self.assertAlmostEqual(BOTTOM - stems[10.0].y, 2 * (BOTTOM - stems[0.0].y),
                               places=3)

    def test_a_head_says_how_the_run_stood(self) -> None:
        stems = _stems(draw_runs(RUN_TIME, [
            _run(0, None), _run(10), _run(20, StatusCode.WARN),
            _run(30, StatusCode.ERROR)]))
        self.assertEqual([(stem.verdict, stem.head) for stem in stems.values()],
                         [(UNJUDGED, False), (PASSED, True), (WARNED, True),
                          (FAILED, True)])

    def test_a_run_that_failed_keeps_its_value(self) -> None:
        stems = _stems(draw_runs(RUN_TIME, [
            _run(0, seconds=600), _run(10, StatusCode.ERROR, seconds=60),
            _run(20, seconds=600)]))
        self.assertGreater(stems[10.0].y, stems[0.0].y)
        self.assertLess(stems[10.0].y, BOTTOM)

    def test_a_run_that_failed_is_marked_in_the_lane_as_well(self) -> None:
        curve = draw_runs(RUN_TIME, [
            _run(0), _run(10, StatusCode.ERROR), _run(20, StatusCode.WARN),
            _run(30, None)])
        self.assertEqual([round(mark.x, 1) for mark in curve.marks],
                         [round(_x(10, 30), 1)])

    def test_a_run_without_a_value_has_no_stem_and_is_counted(self) -> None:
        curve = draw_runs(RUN_TIME, [
            _run(0), _run(10, StatusCode.ERROR, seconds=None), _run(20)])
        self.assertEqual(sorted(_stems(curve)), [0.0, 20.0])
        self.assertEqual((curve.readings, curve.valued, curve.failed), (3, 2, 1))
        # it failed, and the lane says so where no stem can
        self.assertEqual(len(curve.marks), 1)

    def test_the_lane_marks_a_column_once(self) -> None:
        # two failures a minute apart share a column of a month's window
        curve = draw_runs(RUN_TIME, [
            _run(0), _run(301, StatusCode.ERROR), _run(301.02, StatusCode.ERROR),
            _run(720)])
        self.assertEqual(len(curve.marks), 1)
        self.assertEqual(curve.failed, 2)


class CrowdTests(_InBerlin):
    """Where runs stand closer than their marks are wide (ADR-0111 decision 4)."""

    def _crowd(self, *runs: Placed) -> dict[float, Any]:
        # a window of 720 hours: an hour is not a pixel wide
        return _stems(draw_runs(RUN_TIME, [_run(0, seconds=1), *runs,
                                           _run(720, seconds=1)]))

    def test_a_passing_runs_head_gives_way_to_a_head_it_would_run_into(self) -> None:
        stems = self._crowd(_run(300), _run(302), _run(304))
        self.assertLess(stems[304.0].x - stems[300.0].x, HEAD)
        self.assertEqual([stems[hour].head for hour in (300.0, 302.0, 304.0)],
                         [False, False, False])
        # each is still drawn where it stands: nothing is merged
        self.assertEqual(len({stems[hour].x for hour in (300.0, 302.0, 304.0)}), 3)

    def test_the_newest_run_keeps_its_head(self) -> None:
        stems = _stems(draw_runs(RUN_TIME, [_run(0, seconds=1), _run(716),
                                            _run(718), _run(720)]))
        self.assertEqual([stems[hour].head for hour in (716.0, 718.0, 720.0)],
                         [False, False, True])

    def test_a_passing_run_keeps_its_head_where_it_has_room(self) -> None:
        # beside a run an hour away on the axis and far away in its value
        stems = self._crowd(_run(300, seconds=600), _run(301, seconds=60))
        self.assertTrue(stems[300.0].head)
        self.assertTrue(stems[301.0].head)
        # and beside nothing at all
        self.assertTrue(self._crowd(_run(300))[300.0].head)

    def test_a_run_that_warned_or_failed_always_keeps_its_head(self) -> None:
        stems = self._crowd(_run(300, StatusCode.ERROR), _run(301, StatusCode.WARN),
                            _run(302, StatusCode.ERROR), _run(303))
        self.assertEqual([stems[hour].head for hour in (300.0, 301.0, 302.0, 303.0)],
                         [True, True, True, False])

    def test_a_run_without_a_verdict_has_no_head_to_run_into(self) -> None:
        stems = self._crowd(_run(300), _run(301, None))
        self.assertTrue(stems[300.0].head)
        self.assertFalse(stems[301.0].head)

    def test_more_runs_than_columns_are_each_still_drawn(self) -> None:
        runs = [_run(hour / 2, StatusCode.ERROR if hour == 400 else StatusCode.OK)
                for hour in range(2 * COLUMNS)]
        curve = draw_runs(RUN_TIME, runs)
        self.assertEqual(len(curve.stems), 2 * COLUMNS)
        self.assertEqual(sum(1 for stem in curve.stems if stem.head), 2)
        self.assertEqual(curve.readings, 2 * COLUMNS)


class StripTests(_InBerlin):
    """What a column says under the pointer (ADR-0098 decision 5, for runs)."""

    def test_a_run_alone_says_its_time_its_value_and_how_it_stood(self) -> None:
        curve = draw_runs(RUN_TIME, [
            _run(0), _run(10, StatusCode.ERROR, seconds=60),
            _run(20, StatusCode.WARN, seconds=4000), _run(30, None)])
        self.assertEqual([strip.title for strip in curve.hover], [
            "2026-09-02 14:00 · 10m",
            "2026-09-03 00:00 · 1m · failed",
            "2026-09-03 10:00 · 1h 6m · warned",
            "2026-09-03 20:00 · 10m · no verdict"])

    def test_without_a_measure_it_says_how_the_run_stood(self) -> None:
        curve = draw_runs(None, [_run(0), _run(10, StatusCode.ERROR),
                                 _run(20, None)])
        self.assertEqual([strip.title for strip in curve.hover], [
            "2026-09-02 14:00 · passed", "2026-09-03 00:00 · failed",
            "2026-09-03 10:00 · no verdict"])

    def test_the_strips_cut_the_plot_between_neighbors(self) -> None:
        curve = draw_runs(None, [_run(0), _run(10), _run(30)])
        first, second, third = curve.hover
        self.assertEqual(first.x, LEFT)
        self.assertAlmostEqual(first.x + first.width, second.x)
        self.assertAlmostEqual(second.x + second.width, third.x)
        self.assertAlmostEqual(third.x + third.width, RIGHT)
        self.assertAlmostEqual(second.x, (_x(0, 30) + _x(10, 30)) / 2, places=3)

    def test_a_column_that_holds_several_runs_names_them_together(self) -> None:
        curve = draw_runs(RUN_TIME, [
            _run(0), _run(301, seconds=3120),
            _run(301.2, StatusCode.ERROR, seconds=60),
            _run(301.4, StatusCode.WARN, seconds=3720), _run(720)])
        self.assertEqual(len(curve.hover), 3)
        self.assertEqual(
            curve.hover[1].title,
            "1m–1h 2m over 3 runs, 2026-09-15 03:00–2026-09-15 03:24 · 1 failed · "
            "1 warned")

    def test_a_column_of_runs_without_a_measure_counts_them(self) -> None:
        curve = draw_runs(None, [_run(0), _run(301), _run(301.2, StatusCode.ERROR),
                                 _run(720)])
        self.assertEqual(curve.hover[1].title,
                         "2 runs, 2026-09-15 03:00–2026-09-15 03:12 · 1 failed")


class SummaryTests(_InBerlin):
    """What the summary beside the title counts (ADR-0111 decision 6)."""

    RUNS = (_run(0, None, seconds=700), _run(10, seconds=600),
            _run(20, StatusCode.ERROR, seconds=60),
            _run(30, StatusCode.WARN, seconds=3840), _run(40, seconds=900))

    def test_it_counts_every_run_and_what_did_not_pass_by_kind(self) -> None:
        curve = draw_runs(RUN_TIME, self.RUNS)
        self.assertEqual((curve.readings, curve.failed, curve.warned, curve.unjudged),
                         (5, 1, 1, 1))

    def test_the_three_values_are_over_every_run_that_has_one(self) -> None:
        curve = draw_runs(RUN_TIME, self.RUNS)
        # the lowest is the run that failed after a minute
        self.assertEqual((curve.newest, curve.lowest, curve.highest),
                         ("15m", "1m", "1h 4m"))

    def test_without_a_measure_there_are_no_values_to_say(self) -> None:
        curve = draw_runs(None, self.RUNS)
        self.assertEqual((curve.newest, curve.lowest, curve.highest), ("", "", ""))
        self.assertEqual((curve.readings, curve.failed, curve.warned, curve.unjudged),
                         (5, 1, 1, 1))

    def test_a_window_without_runs_keeps_its_axis_and_says_so(self) -> None:
        span = (T0, T0 + timedelta(days=30))
        curve = draw_runs(RUN_TIME, [], span=span)
        self.assertEqual((curve.readings, curve.stems), (0, ()))
        self.assertTrue(curve.of_runs)
        self.assertEqual((curve.first, curve.last),
                         ("2026-09-02 14:00", "2026-10-02 14:00"))
        self.assertTrue(curve.time_ticks)

    def test_no_runs_and_no_window_is_a_plot_with_nothing_on_it(self) -> None:
        for measure in (RUN_TIME, None):
            with self.subTest(measure=measure):
                curve = draw_runs(measure, [])
                self.assertTrue(curve.of_runs)
                self.assertEqual((curve.readings, curve.stems, curve.first,
                                  curve.last, curve.time_ticks), (0, (), "", "", ()))

    def test_the_time_axis_is_the_one_a_gauges_curve_has(self) -> None:
        span = (T0, T0 + timedelta(days=30))
        curve = draw_runs(None, self.RUNS, span=span)
        self.assertEqual([tick.text for tick in curve.time_ticks],
                         ["09-07", "09-14", "09-21", "09-28"])
        self.assertEqual(len(curve.stretches), 5)


class DrawableTests(TestCase):
    """Whether a series of runs has a plot at all, answered without drawing it."""

    def test_a_measure_has_one_where_a_run_gives_it_a_number(self) -> None:
        self.assertTrue(runs_drawable(RUN_TIME, [_run(0, seconds=None), _run(1)]))
        self.assertFalse(runs_drawable(RUN_TIME, [_run(0, seconds=None)]))
        self.assertFalse(runs_drawable(RUN_TIME, [_run(0, seconds="long")]))

    def test_without_a_measure_every_run_is_a_tick(self) -> None:
        self.assertTrue(runs_drawable(None, [_run(0, seconds=None)]))
        self.assertFalse(runs_drawable(None, []))
