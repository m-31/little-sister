"""The instance's memory in its own words (ADR-0095), tested from the record's
sentences with the values they are about: the two figures a platform has, where they
stand — `/system` and the engine's report — the ten-minute line, and what a run's
line, and the tick's own, says rose while it was in flight. The `memory` line that
grades the figures is ``test_limits.py``'s."""
from __future__ import annotations

import builtins
import os
import re
import tempfile
import threading
import time
from collections.abc import Callable, Sequence
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from unittest import TestCase, skipIf
from unittest.mock import patch

from little_sister import engine as engine_module
from little_sister import limits as limits_module
from little_sister.checks import Check, CheckResult, Measurement
from little_sister.config import config
from little_sister.engine import Engine
from little_sister.limits import (
    MEMORY_LINE_MINUTES,
    RISE_LOGGED,
    EngineReport,
    Limits,
    Resident,
    resident_size,
    rise_text,
)
from little_sister.series import MemoryStore
from little_sister.state import StateLayer
from little_sister.status import StatusCode
from little_sister.tree import StatusTree

MIB = 1024 ** 2
GIB = 1024 ** 3
LOGGER = "little_sister.logger"


class _Meter:
    """What the process holds, as a test scripts it: the size now — ``None`` on a
    platform that has none, as macOS — and the peak. Called from the engine's worker
    and scheduler threads alike, so it answers under a lock."""

    def __init__(self, *, now: int | None, peak: int) -> None:
        self._lock = threading.Lock()
        self.now = now
        self.peak = peak

    def __call__(self) -> Resident:
        with self._lock:
            return Resident(peak=self.peak, now=self.now)

    def move(self, *, now: int | None = None, peak: int | None = None) -> None:
        with self._lock:
            if now is not None:
                self.now = now
            if peak is not None:
                self.peak = peak


class _Moving(Check):
    """A check whose run moves the meter the way an allocation would: to ``now``
    and ``peak`` where given, after ``started`` is set and ``release`` opens."""

    def __init__(self, *, meter: _Meter, now: int | None = None,
                 peak: int | None = None, started: threading.Event | None = None,
                 release: threading.Event | None = None, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._meter = meter
        self._now = now
        self._peak = peak
        self._started = started
        self._release = release

    def measure(self) -> Sequence[Measurement]:
        if self._started is not None:
            self._started.set()
        if self._release is not None:
            self._release.wait(timeout=5)
        self._meter.move(now=self._now, peak=self._peak)
        return ()

    def grade(self, measurements: Sequence[Measurement],
              now: datetime) -> CheckResult:
        return CheckResult(StatusCode.OK)


class _Alpha(_Moving):
    type_name = "alpha"


class _Beta(_Moving):
    type_name = "beta"


def _engine(checks: Sequence[Check], meter: _Meter, **kwargs: Any) -> Engine:
    kwargs.setdefault("limits", Limits(memory_limit=None))
    return Engine(list(checks), StatusTree(), resident=meter, **kwargs)


def _messages(caught: Any, prefix: str) -> list[str]:
    return [record.getMessage() for record in caught.records
            if record.getMessage().startswith(prefix)]


def _run_line(caught: Any, path: str) -> str:
    lines = _messages(caught, f"check {path}: ")
    assert len(lines) == 1, lines
    return lines[0]


class ResidentSizeTests(TestCase):
    """`resident_size()` answers the size now where the kernel keeps one and the
    peak on every platform that has it, raised to the size now where the two, read
    a moment apart, disagree; macOS answers with the peak alone."""

    def test_this_machine_answers_with_what_its_platform_keeps(self) -> None:
        measured = resident_size()
        assert measured is not None
        if Path("/proc/self/statm").exists():
            assert measured.now is not None
            self.assertGreater(measured.now, 0)
            self.assertGreaterEqual(measured.peak, measured.now)
        else:
            self.assertIsNone(measured.now)
            self.assertGreater(measured.peak, 0)

    def test_without_proc_the_peak_is_all_there_is(self) -> None:
        real_open = builtins.open

        def no_proc(path: Any, *args: Any, **kwargs: Any) -> Any:
            if str(path) == "/proc/self/statm":
                raise OSError("no /proc here")
            return real_open(path, *args, **kwargs)

        with patch.object(builtins, "open", no_proc):
            measured = resident_size()
        assert measured is not None
        self.assertIsNone(measured.now)
        self.assertGreater(measured.peak, 0)

    def test_the_peak_is_raised_to_the_size_now_where_they_disagree(self) -> None:
        with patch.object(limits_module, "_statm_resident", return_value=200 * MIB), \
                patch.object(limits_module, "peak_resident", return_value=150 * MIB):
            self.assertEqual(resident_size(), Resident(peak=200 * MIB, now=200 * MIB))

    def test_a_size_without_a_peak_is_its_own_peak(self) -> None:
        with patch.object(limits_module, "_statm_resident", return_value=200 * MIB), \
                patch.object(limits_module, "peak_resident", return_value=None):
            self.assertEqual(resident_size(), Resident(peak=200 * MIB, now=200 * MIB))

    def test_nothing_readable_is_none(self) -> None:
        with patch.object(limits_module, "_statm_resident", return_value=None), \
                patch.object(limits_module, "peak_resident", return_value=None):
            self.assertIsNone(resident_size())


class ReportFactTests(TestCase):
    """The engine child's `report` carries the figures as a fact, rewritten every
    tick beside the series', in the `memory` line's own words — and never a line."""

    def _report(self, resident: Resident | None, limits: Limits) -> EngineReport:
        report = EngineReport((), workers=1, poll_interval=1.0, limits=limits,
                              resident=lambda: resident)
        report.observe(0.0, entries=0, waiting=[], late=[])
        return report

    def test_both_figures_against_the_limit_and_the_machine(self) -> None:
        report = self._report(Resident(peak=369 * MIB, now=312 * MIB),
                              Limits(memory_limit=8 * GIB, machine_memory=16 * GIB))
        self.assertIn("- resident size 312 MiB, peak 369 MiB, of a limit of 8.0 GiB "
                      "(of the 16.0 GiB the machine gives the process)",
                      report.report().splitlines())
        self.assertNotIn("memory", [line.slug for line in report.lines()])

    def test_the_peak_alone_is_marked_as_the_peak(self) -> None:
        report = self._report(Resident(peak=369 * MIB),
                              Limits(memory_limit=8 * GIB, machine_memory=16 * GIB))
        self.assertIn("- peak resident size 369 MiB, of a limit of 8.0 GiB (of the "
                      "16.0 GiB the machine gives the process)",
                      report.report().splitlines())

    def test_no_limit_leaves_the_figures_alone(self) -> None:
        report = self._report(Resident(peak=369 * MIB, now=312 * MIB),
                              Limits(memory_limit=None))
        self.assertIn("- resident size 312 MiB, peak 369 MiB",
                      report.report().splitlines())

    def test_before_the_first_tick_there_is_no_figure(self) -> None:
        report = EngineReport((), workers=1, poll_interval=1.0,
                              limits=Limits(memory_limit=None),
                              resident=lambda: Resident(peak=MIB, now=MIB))
        self.assertNotIn("resident", report.report())


class RiseTextTests(TestCase):
    """What a rise says: the size's and the peak's, each only from 1 MiB, a fall
    never, and every run beside it named — five and a count."""

    def test_both_rises_in_one_phrase(self) -> None:
        self.assertEqual(
            rise_text(int(38.2 * MIB), int(12.1 * MIB), (), during="while it ran"),
            "resident +38.2 MiB, peak +12.1 MiB while it ran")

    def test_each_is_said_only_from_the_threshold(self) -> None:
        self.assertEqual(RISE_LOGGED, MIB)
        self.assertEqual(rise_text(MIB - 1, MIB, (), during="while it ran"),
                         "peak +1.0 MiB while it ran")
        self.assertEqual(rise_text(MIB, MIB - 1, (), during="while it ran"),
                         "resident +1.0 MiB while it ran")
        self.assertEqual(rise_text(MIB - 1, MIB - 1, ("/a",), during="while it ran"),
                         "")

    def test_a_fall_is_never_said(self) -> None:
        self.assertEqual(rise_text(-40 * MIB, 0, ("/a",), during="while it ran"), "")

    def test_the_runs_beside_it_are_named_five_and_a_count(self) -> None:
        self.assertEqual(rise_text(2 * MIB, 0, ("/b",), during="while it ran"),
                         "resident +2.0 MiB while it ran, beside /b")
        self.assertEqual(rise_text(2 * MIB, 0, ("/c", "/b"), during="while it ran"),
                         "resident +2.0 MiB while it ran, beside /b and /c")
        self.assertEqual(
            rise_text(2 * MIB, 0, ("/g", "/f", "/e", "/d", "/c", "/b", "/a"),
                      during="while it ran"),
            "resident +2.0 MiB while it ran, beside /a, /b, /c, /d, /e and 2 more")


class RunLineTests(TestCase):
    """A run's log line carries what rose while it ran, inside the parentheses
    beside the elapsed time: on Linux the size's rise and the peak's, on macOS the
    peak's — each from 1 MiB, a fall never."""

    def _line(self, meter: _Meter, **moves: int) -> str:
        check = _Moving(path="/web", meter=meter, **moves)
        with self.assertLogs(LOGGER, level="INFO") as caught:
            _engine([check], meter).run_once()
        return _run_line(caught, "/web")

    def test_a_run_whose_size_rises_beneath_an_earlier_peak_carries_its_figure(
            self) -> None:
        """The Linux case: the process reached its high long ago, and a run that
        still holds 40 MiB when it ends moves no peak at all."""
        line = self._line(_Meter(now=350 * MIB, peak=400 * MIB), now=390 * MIB)
        self.assertRegex(line, r"^check /web: OK \(\d+ ms; resident \+40\.0 MiB "
                               r"while it ran\)$")

    def test_a_run_below_one_mebibyte_adds_nothing_to_its_line(self) -> None:
        line = self._line(_Meter(now=350 * MIB, peak=400 * MIB),
                          now=350 * MIB + RISE_LOGGED - 1)
        self.assertRegex(line, r"^check /web: OK \(\d+ ms\)$")

    def test_a_new_high_on_linux_carries_both(self) -> None:
        line = self._line(_Meter(now=350 * MIB, peak=400 * MIB),
                          now=450 * MIB, peak=450 * MIB)
        self.assertRegex(line, r"\(\d+ ms; resident \+100\.0 MiB, peak \+50\.0 MiB "
                               r"while it ran\)$")

    def test_a_fall_adds_nothing(self) -> None:
        line = self._line(_Meter(now=390 * MIB, peak=400 * MIB), now=350 * MIB)
        self.assertRegex(line, r"^check /web: OK \(\d+ ms\)$")

    def test_on_macos_the_peak_s_rise_is_the_figure(self) -> None:
        line = self._line(_Meter(now=None, peak=400 * MIB),
                          peak=400 * MIB + int(18.4 * MIB))
        self.assertRegex(line, r"\(\d+ ms; peak \+18\.4 MiB while it ran\)$")

    def test_on_macos_a_run_beneath_the_peak_shows_nothing(self) -> None:
        line = self._line(_Meter(now=None, peak=400 * MIB))
        self.assertRegex(line, r"^check /web: OK \(\d+ ms\)$")


class BesideTests(TestCase):
    """The rise is the process's: a run names every other run that was in flight at
    any point of it, and the same step stands on each of their lines."""

    def _overlap(self, first: _Moving, second: _Moving, meter: _Meter,
                 before: Sequence[Check] = ()) -> Callable[[str], str]:
        engine = _engine([*before, first, second], meter)
        items = {id(item.check): item for item in engine._scheduled}
        with self.assertLogs(LOGGER, level="INFO") as caught:
            for check in before:
                engine._execute(items[id(check)], once=True)
            runner = threading.Thread(
                target=engine._execute, args=(items[id(first)],),
                kwargs={"once": True})
            runner.start()
            assert first._started is not None and first._release is not None
            self.assertTrue(first._started.wait(timeout=5))
            engine._execute(items[id(second)], once=True)
            first._release.set()
            runner.join(timeout=5)
        return lambda path: _run_line(caught, path)

    def test_two_runs_in_flight_name_each_other_and_share_the_step(self) -> None:
        meter = _Meter(now=350 * MIB, peak=400 * MIB)
        early = _Moving(path="/early", meter=meter)
        waiting = _Moving(path="/a", meter=meter, started=threading.Event(),
                          release=threading.Event())
        allocating = _Moving(path="/b", meter=meter, now=370 * MIB)
        line = self._overlap(waiting, allocating, meter, before=[early])
        self.assertRegex(line("/b"), r"; resident \+20\.0 MiB while it ran, "
                                     r"beside /a\)$")
        self.assertRegex(line("/a"), r"; resident \+20\.0 MiB while it ran, "
                                     r"beside /b\)$")
        self.assertRegex(line("/early"), r"^check /early: OK \(\d+ ms\)$")

    def test_two_checks_on_one_mount_are_told_apart_by_their_type(self) -> None:
        meter = _Meter(now=350 * MIB, peak=400 * MIB)
        waiting = _Alpha(path="/host", meter=meter, started=threading.Event(),
                         release=threading.Event())
        allocating = _Beta(path="/host", meter=meter, now=370 * MIB)
        engine = _engine([waiting, allocating], meter)
        with self.assertLogs(LOGGER, level="INFO") as caught:
            runner = threading.Thread(target=engine._execute,
                                      args=(engine._scheduled[0],),
                                      kwargs={"once": True})
            runner.start()
            assert waiting._started is not None and waiting._release is not None
            self.assertTrue(waiting._started.wait(timeout=5))
            engine._execute(engine._scheduled[1], once=True)
            waiting._release.set()
            runner.join(timeout=5)
        lines = _messages(caught, "check /host: ")
        self.assertEqual(len(lines), 2, lines)
        self.assertTrue(any(line.endswith("beside /host (alpha))") for line in lines),
                        lines)
        self.assertTrue(any(line.endswith("beside /host (beta))") for line in lines),
                        lines)


class _Sweeping(MemoryStore):
    """A series store whose sweep, on the tick, moves the meter."""

    def __init__(self, meter: _Meter, now: int) -> None:
        super().__init__()
        self._meter = meter
        self._now = now

    def sweep(self, keep: Any, *, ceiling: int | None = None) -> Any:
        self._meter.move(now=self._now)
        return super().sweep(keep, ceiling=ceiling)


class TickLineTests(TestCase):
    """The tick is measured the same way, and a tick that raised either figure by
    1 MiB or more says so on a line of its own — whether it ran the state layer's
    interval save, and which runs were in flight."""

    def test_a_tick_s_state_save_is_said(self) -> None:
        meter = _Meter(now=350 * MIB, peak=400 * MIB)
        clock = [0.0]
        with tempfile.TemporaryDirectory() as directory:
            state = StateLayer(directory, interval_seconds=60,
                               clock=lambda: clock[0])

            def produce() -> object:
                meter.move(now=362 * MIB + int(0.3 * MIB), peak=412 * MIB)
                return {"a": 1}

            state.keep("a.json", produce)
            engine = _engine([], meter, state=state)
            with self.assertLogs(LOGGER, level="INFO") as caught:
                engine._guarded_tick(submit=False)
                clock[0] = 61.0
                engine._guarded_tick(submit=False)
        self.assertEqual(_messages(caught, "engine: resident"),
                         ["engine: resident +12.3 MiB, peak +12.0 MiB during the tick, "
                          "including a state save"])

    def test_a_tick_without_a_save_is_said_as_the_tick(self) -> None:
        meter = _Meter(now=350 * MIB, peak=400 * MIB)
        engine = _engine([], meter, series=_Sweeping(meter, 355 * MIB))
        with self.assertLogs(LOGGER, level="INFO") as caught:
            engine._guarded_tick(submit=False)
        self.assertEqual(_messages(caught, "engine: resident"),
                         ["engine: resident +5.0 MiB during the tick"])

    def test_a_quiet_tick_says_nothing(self) -> None:
        meter = _Meter(now=350 * MIB, peak=400 * MIB)
        engine = _engine([], meter)
        with self.assertLogs(LOGGER, level="INFO") as caught:
            engine._guarded_tick(submit=False)
        self.assertEqual(_messages(caught, "engine: resident"), [])
        self.assertEqual(_messages(caught, "engine: peak"), [])


def _on_the_logs_clock(hour: int, minute: int, second: int = 0) -> datetime:
    """The instant at which the clock the log is stamped in — the configured
    zone's — reads that time of 27 September 2026: the clock whose ten-minute marks
    the line keeps."""
    return datetime(2026, 9, 27, hour, minute, second, tzinfo=config.tzinfo)


class TenMinuteLineTests(TestCase):
    """The log carries the card's figures on the first tick past each ten-minute
    mark of the clock the log is stamped in, once at the first tick as the baseline
    and once at the stop."""

    def test_the_baseline_the_marks_and_the_stop(self) -> None:
        self.assertEqual(MEMORY_LINE_MINUTES, 10)
        meter = _Meter(now=350 * MIB, peak=400 * MIB)
        wall = [_on_the_logs_clock(10, 3, 0)]
        engine = _engine([], meter, wall=lambda: wall[0],
                         limits=Limits(memory_limit=8 * GIB))
        with self.assertLogs(LOGGER, level="INFO") as caught:
            for moment in [(10, 3, 0), (10, 7, 0), (10, 10, 1), (10, 19, 59),
                           (10, 20, 0)]:
                wall[0] = _on_the_logs_clock(*moment)
                engine._guarded_tick(submit=False)
            meter.move(now=360 * MIB)
            engine.stop(trigger="test")
        lines = _messages(caught, "engine: memory")
        expected = ("resident size {} MiB, peak 400 MiB, of a limit of 8.0 GiB; the "
                    "series hold 0 B, the tree ")
        self.assertEqual(len(lines), 4, lines)
        self.assertTrue(lines[0].startswith(
            "engine: memory at the start — " + expected.format(350)), lines[0])
        self.assertTrue(lines[1].startswith(
            "engine: memory — " + expected.format(350)), lines[1])
        self.assertTrue(lines[2].startswith("engine: memory — "), lines[2])
        self.assertTrue(lines[3].startswith(
            "engine: memory at the stop — " + expected.format(360)), lines[3])
        self.assertRegex(lines[0], r"the tree [\d,]+ entr(y|ies)$")

    def _two_ticks(self, *, configured: str, machine: str) -> list[str]:
        """The memory lines of two ticks either side of 04:25:00 UTC, on a machine
        in ``machine`` whose settings name ``configured``."""
        meter = _Meter(now=350 * MIB, peak=400 * MIB)
        wall = [datetime(2026, 9, 27, 4, 24, 59, tzinfo=UTC)]
        engine = _engine([], meter, wall=lambda: wall[0])
        try:
            with patch.dict(os.environ, {"TZ": machine}), \
                    patch.object(engine_module, "config",
                                 replace(config, timezone=configured)):
                time.tzset()
                with self.assertLogs(LOGGER, level="INFO") as caught:
                    engine._guarded_tick(submit=False)
                    wall[0] = datetime(2026, 9, 27, 4, 25, 1, tzinfo=UTC)
                    engine._guarded_tick(submit=False)
        finally:
            time.tzset()          # back to whatever the real environment says
        return _messages(caught, "engine: memory")

    @skipIf(not hasattr(time, "tzset"), "no tzset on this platform")
    def test_the_marks_are_those_of_the_clock_the_log_is_stamped_in(self) -> None:
        """The engine's clock answers an instant, and the marks are those of the
        configured zone, in which the log is stamped (ADR-0120 decision 9) — not of
        the machine's clock.

        **Asserted where the two clocks' marks differ, on purpose**: in a zone whose
        offset is a multiple of ten minutes — UTC, Berlin — a mark of that clock is
        a mark of UTC as well, so reading the instant on any of them would pass
        there. In Kathmandu, at +05:45, 10:09:59 and 10:10:01 are one mark apart,
        and both fall in one ten minutes of UTC: 04:24:59 and 04:25:01.
        """
        lines = self._two_ticks(configured="Asia/Kathmandu", machine="UTC")
        self.assertEqual(len(lines), 2, lines)
        self.assertTrue(lines[0].startswith("engine: memory at the start — "),
                        lines[0])
        self.assertTrue(lines[1].startswith("engine: memory — "), lines[1])
        # and a machine in Kathmandu whose log is stamped in UTC passes no mark
        lines = self._two_ticks(configured="UTC", machine="Asia/Kathmandu")
        self.assertEqual(len(lines), 1, lines)

    def test_macos_begins_with_the_peak(self) -> None:
        meter = _Meter(now=None, peak=369 * MIB)
        engine = _engine([], meter,
                         wall=lambda: datetime(2026, 9, 27, 10, 3, tzinfo=UTC))
        with self.assertLogs(LOGGER, level="INFO") as caught:
            engine._guarded_tick(submit=False)
        lines = _messages(caught, "engine: memory")
        self.assertEqual(len(lines), 1, lines)
        self.assertTrue(lines[0].startswith(
            "engine: memory at the start — peak resident size 369 MiB; the series "
            "hold 0 B"), lines[0])


class SystemRowTests(TestCase):
    """`/system`'s engine block carries the figures as the fourth row of the card
    that holds the entries and the series against their limits."""

    @staticmethod
    def _render(info: Any) -> str:
        from flask import render_template

        from little_sister import app as app_module
        with app_module.app.test_request_context():
            return render_template("_system_info.html", info=info)

    def _row(self, meter: _Meter | None, limits: Limits, label: str) -> str:
        engine = Engine([], StatusTree(), resident=meter or (lambda: None),
                        limits=limits)
        if meter is not None:
            engine._observe(1.0)
        body = self._render(engine.info())
        self.assertIn(label, body)
        return re.sub(r"\s+", " ", body.split(label, 1)[1].split("</div></div>")[0])

    def test_the_size_its_peak_the_limit_and_the_machine(self) -> None:
        row = self._row(_Meter(now=312 * MIB, peak=369 * MIB),
                        Limits(memory_limit=8 * GIB, machine_memory=16 * GIB),
                        "Resident size")
        self.assertIn("312 MiB", row)
        self.assertIn("of 8.0 GiB · peak 369 MiB · the machine gives the process "
                      "16.0 GiB", row)

    def test_the_peak_alone_is_labelled_as_the_peak(self) -> None:
        row = self._row(_Meter(now=None, peak=369 * MIB),
                        Limits(memory_limit=8 * GIB, machine_memory=16 * GIB),
                        "Peak resident size")
        self.assertIn("369 MiB", row)
        self.assertNotIn("peak 369", row)

    def test_before_the_first_tick_the_row_says_nothing_is_known(self) -> None:
        row = self._row(None, Limits(memory_limit=None), "Resident size")
        self.assertIn("—", row)

    def test_the_page_names_what_the_last_tick_measured(self) -> None:
        meter = _Meter(now=312 * MIB, peak=369 * MIB)
        engine = Engine([], StatusTree(), resident=meter,
                        limits=Limits(memory_limit=8 * GIB, machine_memory=16 * GIB))
        engine._observe(1.0)
        meter.move(now=500 * MIB, peak=500 * MIB)
        info = engine.info()
        self.assertEqual((info.resident, info.resident_peak, info.memory_limit,
                          info.machine_memory),
                         (312 * MIB, 369 * MIB, 8 * GIB, 16 * GIB))


class StateTickTests(TestCase):
    """`StateLayer.tick()` says whether it ran the interval save, so the tick's line
    can."""

    def test_only_the_tick_that_saves_says_so(self) -> None:
        clock = [0.0]
        with tempfile.TemporaryDirectory() as directory:
            state = StateLayer(directory, interval_seconds=60,
                               clock=lambda: clock[0])
            state.keep("a.json", lambda: {"a": 1})
            self.assertFalse(state.tick())      # the first only starts the interval
            clock[0] = 30.0
            self.assertFalse(state.tick())
            clock[0] = 61.0
            self.assertTrue(state.tick())
            self.assertFalse(state.tick())

