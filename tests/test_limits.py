"""The engine's own lines (ADR-0072): what the engine measures against its limits
as it runs, and the sentences the heartbeat carries — tested from the claims
``architecture.md`` §4.6 makes, with the values the claims are about. The engine's
side of it — what it records on the tick — is in ``test_engine.py``."""
from __future__ import annotations

from datetime import datetime, timedelta
from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import patch

from little_sister import limits as limits_module
from little_sister.config import config
from little_sister.engine import FAILURE_RECORD_BYTES
from little_sister.limits import (
    AMBER_SHARE,
    ENTRY_LIMIT,
    LAG_MEMORY_SECONDS,
    LAG_SECONDS,
    MEMORY_HOLD_SECONDS,
    MEMORY_SHARE,
    NAMED_IN_A_LINE,
    POOL_WAIT_SECONDS,
    Capacity,
    EngineReport,
    LateRun,
    Limits,
    Resident,
    Waiting,
    capacity,
    declared_costs,
    format_size,
    format_weight,
    machine_memory,
    may_run_late,
)
from little_sister.status import StatusCode

GIB = 1024 ** 3
MIB = 1024 ** 2


def _check(path: str, *, timeout: float = 30.0, frequency: int = 900):
    return SimpleNamespace(path=path, timeout_seconds=timeout,
                           frequency_seconds=frequency)


def _report(checks=(), *, limits: Limits | None = None, workers: int = 8,
            poll_interval: float = 1.0, resident=lambda: None,
            capacity: Capacity | None = None) -> EngineReport:
    return EngineReport(checks, workers=workers, poll_interval=poll_interval,
                        limits=limits or Limits(entry_limit=100),
                        capacity=capacity, resident=resident)


def _declaring(path: str, *, cost=None, entries=None, record=None,
               frequency: int = 60):
    """A check that declares what it costs — the three methods `Check` grew, which
    is all `declared_costs` reads."""
    return SimpleNamespace(path=path, timeout_seconds=30.0,
                           frequency_seconds=frequency,
                           expected_cost=lambda: cost,
                           expected_entries=lambda: entries,
                           expected_record=lambda: record)


def _slugs(report: EngineReport) -> list[str]:
    return [line.slug for line in report.lines()]


def _line(report: EngineReport, slug: str):
    found = [line for line in report.lines() if line.slug == slug]
    assert len(found) == 1, f"{slug!r} not exactly once in {_slugs(report)}"
    return found[0]


class EntryCountTests(TestCase):
    """The tree's entry count against its limit: WARN at 80 % of it, ERROR at it,
    nothing below."""

    def test_below_the_amber_share_says_nothing(self):
        report = _report()
        report.observe(0.0, entries=79, waiting=[], late=[])
        self.assertNotIn("entries", _slugs(report))

    def test_the_amber_share_is_a_warn_with_the_percentage(self):
        report = _report()
        report.observe(0.0, entries=80, waiting=[], late=[])
        line = _line(report, "entries")
        self.assertIs(line.code, StatusCode.WARN)
        self.assertEqual(line.text, "the tree holds 80 entries, 80 % of its limit "
                                    "of 100")

    def test_the_limit_is_an_error(self):
        report = _report()
        report.observe(0.0, entries=100, waiting=[], late=[])
        line = _line(report, "entries")
        self.assertIs(line.code, StatusCode.ERROR)
        self.assertEqual(line.text, "the tree holds 100 entries, past its limit "
                                    "of 100")

    def test_the_line_clears_when_the_count_falls_back(self):
        report = _report()
        report.observe(0.0, entries=120, waiting=[], late=[])
        report.observe(1.0, entries=10, waiting=[], late=[])
        self.assertNotIn("entries", _slugs(report))

    def test_the_default_limit_is_a_hundred_thousand_with_thousands_separators(self):
        report = _report(limits=Limits())
        report.observe(0.0, entries=ENTRY_LIMIT, waiting=[], late=[])
        self.assertEqual(_line(report, "entries").text,
                         "the tree holds 100,000 entries, past its limit of "
                         "100,000")


def _at(hour: int, minute: int, second: int = 0) -> datetime:
    """The instant at which the clock a line's time is written on — the configured
    zone's, through ``spans.local_time`` — reads that time of 10 October 2026."""
    return datetime(2026, 10, 10, hour, minute, second, tzinfo=config.tzinfo)


class _Process:
    """A process whose resident size a test scripts, observed tick by tick. A tick
    is one second of the engine's clock and of the wall's, so that none comes late;
    the first is observed when the configured zone's clock reads 09:12:00. The peak
    is the high-water mark a kernel keeps: the largest size so far, or ``peak``
    where a test says the process had once been larger."""

    def __init__(self, limits: Limits, *, peak: int = 0,
                 peak_only: bool = False) -> None:
        self._size: int | None = None
        self._peak = peak
        self._peak_only = peak_only
        self._unread = False
        self._clock = -1.0
        self._wall = _at(9, 12) - timedelta(seconds=1)
        self.report = EngineReport((), workers=1, poll_interval=1.0, limits=limits,
                                   resident=self._read, wall=lambda: self._wall)

    def _read(self) -> Resident | None:
        if self._size is None:
            return None
        self._peak = max(self._peak, self._size)
        if self._peak_only or self._unread:
            return Resident(peak=self._peak)
        return Resident(peak=self._peak, now=self._size)

    def tick(self, size: int | None, *, times: int = 1, unread: bool = False):
        """Observe ``times`` ticks at ``size`` bytes — ``None`` for a tick at which
        nothing can say what the process holds, and ``unread`` for one at which
        the size now cannot be read and the peak can — and answer the `memory`
        line as it stands after the last of them, or ``None`` where there is
        none."""
        self._size, self._unread = size, unread
        for _ in range(times):
            self._clock += 1.0
            self._wall += timedelta(seconds=1)
            self.report.observe(self._clock, entries=0, waiting=[], late=[])
        found = [line for line in self.report.lines() if line.slug == "memory"]
        assert len(found) <= 1, found
        return found[0] if found else None


class MemoryTests(TestCase):
    """The resident size against the memory limit, the same shape; no line where
    the machine could not say; the size now graded where there is one and a
    high-water mark, where it is all there is, called the peak it is (ADR-0095
    decision 1). What the platform reads is ``test_memory_figures.py``'s, and how
    the line holds what it saw is :class:`MemoryHoldTests`'s."""

    def _limits(self) -> Limits:
        return Limits(memory_limit=GIB, machine_memory=2 * GIB)

    def test_below_the_amber_share_says_nothing(self):
        self.assertIsNone(_Process(self._limits()).tick(700 * MIB))

    def test_the_amber_share_names_the_size_the_limit_and_the_machine(self):
        line = _Process(self._limits()).tick(int(GIB * 0.85))
        self.assertIs(line.code, StatusCode.WARN)
        self.assertEqual(line.text, "resident size 870 MiB at 09:12, 85 % of the "
                                    "limit of 1.0 GiB (now 870 MiB of the 2.0 GiB "
                                    "the machine gives the process)")

    def test_the_line_begins_at_the_amber_share_itself(self):
        process = _Process(Limits(memory_limit=GIB, amber_share=0.5))
        self.assertIsNone(process.tick(GIB // 2 - 1))
        self.assertIs(process.tick(GIB // 2).code, StatusCode.WARN)

    def test_the_limit_is_an_error(self):
        line = _Process(self._limits()).tick(GIB)
        self.assertIs(line.code, StatusCode.ERROR)
        self.assertTrue(line.text.startswith(
            "resident size 1.0 GiB at 09:12, past the limit of 1.0 GiB"), line.text)

    def test_a_peak_is_named_as_one_and_has_no_when_and_no_now(self):
        """A high-water mark is all macOS keeps: the process cannot say when it
        reached it, and there is no size now to stand beside it."""
        line = _Process(self._limits(), peak_only=True).tick(GIB)
        self.assertIs(line.code, StatusCode.ERROR)
        self.assertEqual(line.text, "peak resident size 1.0 GiB, past the limit of "
                                    "1.0 GiB (of the 2.0 GiB the machine gives the "
                                    "process)")

    def test_a_peak_past_a_limit_it_is_written_as_says_how_far(self):
        """The distance is said of a peak as it is of a size now: 41 MiB past a
        limit of 8 GiB is written `8.0 GiB`, as the limit is."""
        process = _Process(Limits(memory_limit=8 * GIB, machine_memory=16 * GIB),
                           peak_only=True)
        line = process.tick(8 * GIB + 41 * MIB)
        self.assertIs(line.code, StatusCode.ERROR)
        self.assertEqual(line.text, "peak resident size 8.0 GiB, 41.0 MiB past the "
                                    "limit of 8.0 GiB (of the 16.0 GiB the machine "
                                    "gives the process)")

    def test_the_size_now_is_graded_and_not_the_peak_beside_it(self):
        """A high-water mark past the limit would stand ERROR for the life of the
        process; the size now is in the amber band, and the line says what it
        is."""
        line = _Process(self._limits(), peak=GIB).tick(int(GIB * 0.85))
        self.assertIs(line.code, StatusCode.WARN)
        self.assertTrue(line.text.startswith("resident size 870 MiB at 09:12, 85 % "
                                             "of the limit"), line.text)

    def test_no_limit_means_no_line_however_large_the_process(self):
        self.assertIsNone(_Process(Limits(memory_limit=None)).tick(64 * GIB))

    def test_no_measurement_means_no_line(self):
        self.assertIsNone(_Process(self._limits()).tick(None))


class MemoryHoldTests(TestCase):
    """The `memory` line holds what it saw, as the `lag` line does (ADR-0095): it
    is written from the worst reading of the last ten minutes, says what that was,
    when it was and what the size is now, and steps down — ERROR to WARN to nothing
    — only when the whole window stood below. The values are the deployment's the
    line was held for: a limit of 504 MiB on a machine that gives the process 917,
    so the amber share is 403.2 MiB."""

    LIMIT = 504 * MIB

    def _process(self, **limits) -> _Process:
        return _Process(Limits(memory_limit=self.LIMIT, **limits))

    def test_the_window_is_the_lag_lines(self):
        self.assertEqual(MEMORY_HOLD_SECONDS, LAG_MEMORY_SECONDS)
        self.assertEqual(Limits().memory_hold_seconds, 600.0)

    def test_the_text_names_the_worst_reading_when_it_was_and_the_size_now(self):
        process = self._process()
        process.tick(514 * MIB)                         # at 09:12:00
        line = process.tick(481 * MIB, times=90)        # through 09:13:30
        self.assertIs(line.code, StatusCode.ERROR)
        self.assertEqual(line.text, "resident size 514 MiB at 09:12, past the limit "
                                    "of 504 MiB (now 481 MiB)")

    def test_what_the_machine_gives_stands_beside_the_size_now(self):
        process = self._process(machine_memory=917 * MIB)
        process.tick(514 * MIB)
        self.assertEqual(process.tick(481 * MIB).text,
                         "resident size 514 MiB at 09:12, past the limit of 504 MiB "
                         "(now 481 MiB of the 917 MiB the machine gives the process)")

    def test_a_size_past_the_limit_on_one_tick_and_below_it_on_the_next_stays_red(
            self):
        """The flicker the line was held for: a process that sits on its limit is
        past it on one tick and below it on the next, tick after tick."""
        process = self._process()
        codes = [process.tick(size).code
                 for size in (self.LIMIT + MIB, self.LIMIT - MIB) * 5]
        self.assertEqual(codes, [StatusCode.ERROR] * 10)

    def test_the_worst_reading_inside_the_window_is_what_it_says(self):
        process = self._process()
        process.tick(514 * MIB)                         # at 09:12:00
        process.tick(481 * MIB, times=59)
        process.tick(519 * MIB)                         # at 09:13:00, the worst
        process.tick(481 * MIB, times=59)
        process.tick(510 * MIB)                         # at 09:14:00
        self.assertEqual(process.tick(481 * MIB).text,
                         "resident size 519 MiB at 09:13, past the limit of 504 MiB "
                         "(now 481 MiB)")

    def test_of_two_readings_alike_the_later_is_when_it_was(self):
        process = self._process()
        process.tick(514 * MIB)                         # at 09:12:00
        process.tick(481 * MIB, times=59)
        process.tick(514 * MIB)                         # at 09:13:00, as large
        self.assertIn("514 MiB at 09:13,", process.tick(481 * MIB).text)

    def test_the_error_stands_for_the_window_and_then_steps_down_to_the_warn(self):
        process = self._process(memory_hold_seconds=90.0)
        process.tick(514 * MIB)                         # past the limit, at 09:12:00
        line = process.tick(481 * MIB, times=90)        # 90 s on, 09:13:30: inside
        self.assertIs(line.code, StatusCode.ERROR)
        self.assertIn("514 MiB at 09:12, past the limit", line.text)
        line = process.tick(481 * MIB)                  # 91 s on: the whole window
        self.assertIs(line.code, StatusCode.WARN)       # stood below the limit
        self.assertEqual(line.text, "resident size 481 MiB at 09:13, 95 % of the "
                                    "limit of 504 MiB (now 481 MiB)")

    def test_the_warn_stands_for_the_window_and_then_the_line_clears(self):
        process = self._process(memory_hold_seconds=30.0)
        process.tick(481 * MIB)                         # in the amber band, second 0
        line = process.tick(300 * MIB, times=30)        # 30 s on: still inside
        self.assertIs(line.code, StatusCode.WARN)
        self.assertEqual(line.text, "resident size 481 MiB at 09:12, 95 % of the "
                                    "limit of 504 MiB (now 300 MiB)")
        self.assertIsNone(process.tick(300 * MIB))      # 31 s on: gone

    def test_a_reading_below_the_amber_share_holds_nothing(self):
        """Only a reading at or past the amber share is recorded: one below it
        neither begins the line nor keeps it standing."""
        process = self._process(memory_hold_seconds=30.0)
        self.assertIsNone(process.tick(403 * MIB, times=40))
        process.tick(404 * MIB)                         # past 403.2 MiB, second 40
        self.assertIsNotNone(process.tick(403 * MIB, times=30))
        self.assertIsNone(process.tick(403 * MIB))

    def test_an_older_worst_ages_out_and_leaves_the_younger_one(self):
        process = self._process(memory_hold_seconds=120.0)
        process.tick(519 * MIB)                         # second 0, 09:12:00
        process.tick(481 * MIB, times=69)
        process.tick(510 * MIB)                         # second 70, 09:13:10
        line = process.tick(481 * MIB, times=50)        # second 120: both inside
        self.assertIn("519 MiB at 09:12, past the limit", line.text)
        line = process.tick(481 * MIB)                  # second 121: the first is out
        self.assertIs(line.code, StatusCode.ERROR)
        self.assertIn("510 MiB at 09:13, past the limit", line.text)
        line = process.tick(481 * MIB, times=70)        # second 191: the second too
        self.assertIs(line.code, StatusCode.WARN)
        self.assertIn("481 MiB at 09:15, 95 % of the limit", line.text)

    def test_a_reading_is_recorded_without_a_log_line_of_its_own(self):
        """The reading comes every tick; the log has its ten-minute line and a
        run's rise (ADR-0095 decisions 3 and 4), and neither is this."""
        process = self._process()
        with self.assertNoLogs("little_sister", level="INFO"):
            process.tick(514 * MIB, times=3)
            process.tick(481 * MIB, times=3)

    def test_a_tick_that_cannot_say_leaves_the_line_and_names_no_size_now(self):
        process = self._process()
        process.tick(514 * MIB)
        line = process.tick(None)
        self.assertIs(line.code, StatusCode.ERROR)
        self.assertEqual(line.text, "resident size 514 MiB at 09:12, past the limit "
                                    "of 504 MiB")

    def test_a_tick_that_cannot_read_the_size_now_is_not_graded_on_the_peak(self):
        """Where the platform keeps a size now, a tick that could not read it has
        the high-water mark alone — 600 MiB here, reached once by a process that
        holds 300 — and that is not what the process holds: graded and held, it
        would stand ERROR for the whole window."""
        process = _Process(Limits(memory_limit=self.LIMIT), peak=600 * MIB)
        self.assertIsNone(process.tick(300 * MIB, times=5))
        self.assertIsNone(process.tick(300 * MIB, unread=True))
        self.assertIsNone(process.tick(300 * MIB, times=2))

    def test_a_tick_that_cannot_read_the_size_now_leaves_the_line_as_it_stood(self):
        process = self._process()
        process.tick(514 * MIB)                         # at 09:12:00
        process.tick(481 * MIB, times=59)
        line = process.tick(481 * MIB, unread=True)     # at 09:13:00, the peak alone
        self.assertIs(line.code, StatusCode.ERROR)
        self.assertEqual(line.text, "resident size 514 MiB at 09:12, past the limit "
                                    "of 504 MiB")
        self.assertEqual(process.tick(481 * MIB).text,
                         "resident size 514 MiB at 09:12, past the limit of 504 MiB "
                         "(now 481 MiB)")

    def test_where_the_peak_is_all_there_is_it_is_graded_on_every_tick(self):
        """A platform that keeps no size now has the high-water mark for its
        reading, tick after tick; it never falls, so the line never clears."""
        process = _Process(Limits(memory_limit=self.LIMIT, memory_hold_seconds=30.0),
                           peak_only=True)
        process.tick(514 * MIB)
        line = process.tick(300 * MIB, times=31)        # the window, and a tick more
        self.assertIs(line.code, StatusCode.ERROR)
        self.assertEqual(line.text, "peak resident size 514 MiB, past the limit of "
                                    "504 MiB")

    def test_the_slug_is_memory_and_the_line_is_the_only_one(self):
        """A pin holds the line by its slug (ADR-0036), which no wording moves, and
        what the hold added — when it was, the size now — is in that one line."""
        process = self._process(memory_hold_seconds=30.0)
        for size in (514 * MIB, 481 * MIB):
            process.tick(size)
            self.assertEqual(_slugs(process.report), ["memory"])
        process.tick(481 * MIB, times=31)               # stepped down to the WARN
        self.assertEqual(_slugs(process.report), ["memory"])
        process.tick(300 * MIB, times=31)               # and cleared
        self.assertEqual(_slugs(process.report), [])


def _quantity(figure: str) -> float:
    """The bytes a written size names: `504 MiB`, `1,024 MiB`, `1.0 GiB`."""
    number, unit = figure.split()
    return float(number.replace(",", "")) * {"MiB": MIB, "GiB": GIB}[unit]


class MemoryFiguresApartTests(TestCase):
    """A size past the limit never reads as equal to it — nor one below it. The
    size is compared with the limit in bytes, and where the sentence would read as
    though the size were the limit — the two figures, as the line writes them, name
    one quantity, or a size below the limit comes to 100 % of it — it says how far
    apart they are."""

    def _line(self, limit: int, size: int):
        return _Process(Limits(memory_limit=limit)).tick(size)

    def test_one_byte_past_the_limit_does_not_read_as_the_limit(self):
        line = self._line(504 * MIB, 504 * MIB + 1)
        self.assertIs(line.code, StatusCode.ERROR)
        self.assertEqual(line.text, "resident size 504 MiB at 09:12, 1 B past the "
                                    "limit of 504 MiB (now 504 MiB)")

    def test_the_deployments_two_sentences_no_longer_name_one_number(self):
        """`memory_share: 0.55` of 917 MiB is a limit of 504.35 MiB, and the process
        sat on it: 504 MiB past a limit of 504 MiB on one tick, 504 MiB and 100 %
        of it on the next."""
        limit = int(917 * MIB * 0.55)
        self.assertEqual(format_size(limit), "504 MiB")
        past = self._line(limit, limit + 100 * 1024)
        self.assertIs(past.code, StatusCode.ERROR)
        self.assertEqual(past.text, "resident size 504 MiB at 09:12, 100.0 KiB past "
                                    "the limit of 504 MiB (now 504 MiB)")
        below = self._line(limit, limit - 100 * 1024)
        self.assertIs(below.code, StatusCode.WARN)
        self.assertEqual(below.text, "resident size 504 MiB at 09:12, 100.0 KiB "
                                     "below the limit of 504 MiB (now 504 MiB)")

    def test_one_byte_below_the_limit_is_a_warn_that_says_so(self):
        line = self._line(504 * MIB, 504 * MIB - 1)
        self.assertIs(line.code, StatusCode.WARN)
        self.assertEqual(line.text, "resident size 504 MiB at 09:12, 1 B below the "
                                    "limit of 504 MiB (now 504 MiB)")

    def test_a_size_just_below_the_limit_does_not_read_as_all_of_it(self):
        """503 MiB of a limit of 504 is 99.8 % of it, which rounds to the `100 %`
        that says the size is the limit; the distance says what it is. So it is
        said down to half a percent below the limit, and from there the share."""
        for size, said in ((503, "1.0 MiB below the limit of 504 MiB"),
                           (502, "2.0 MiB below the limit of 504 MiB"),
                           (501, "99 % of the limit of 504 MiB")):
            with self.subTest(size=size):
                line = self._line(504 * MIB, size * MIB)
                self.assertIs(line.code, StatusCode.WARN)
                self.assertEqual(line.text, f"resident size {size} MiB at 09:12, "
                                            f"{said} (now {size} MiB)")

    def test_two_figures_apart_below_the_limit_are_no_100_percent_either(self):
        """504.4 MiB below a limit of 504.6 is written `504 MiB` beside `505 MiB`,
        and is 99.96 % of it."""
        line = self._line(int(504.6 * MIB), int(504.4 * MIB))
        self.assertIs(line.code, StatusCode.WARN)
        self.assertEqual(line.text, "resident size 504 MiB at 09:12, 204.8 KiB "
                                    "below the limit of 505 MiB (now 504 MiB)")

    def test_at_the_limit_to_the_byte_the_figures_are_equal_and_read_so(self):
        line = self._line(504 * MIB, 504 * MIB)
        self.assertIs(line.code, StatusCode.ERROR)
        self.assertEqual(line.text, "resident size 504 MiB at 09:12, past the limit "
                                    "of 504 MiB (now 504 MiB)")

    def test_figures_that_read_apart_say_nothing_more(self):
        """504.6 MiB past a limit of 504.4: a fifth of a mebibyte apart, and written
        `505 MiB` and `504 MiB`, which no reader takes for one figure. Nor does one
        take 481 MiB for a limit of 504."""
        line = self._line(int(504.4 * MIB), int(504.6 * MIB))
        self.assertIs(line.code, StatusCode.ERROR)
        self.assertEqual(line.text, "resident size 505 MiB at 09:12, past the limit "
                                    "of 504 MiB (now 505 MiB)")
        line = self._line(504 * MIB, 481 * MIB)
        self.assertIs(line.code, StatusCode.WARN)
        self.assertEqual(line.text, "resident size 481 MiB at 09:12, 95 % of the "
                                    "limit of 504 MiB (now 481 MiB)")

    def test_a_gibibyte_and_1024_mebibytes_are_one_figure(self):
        """The two units meet at `1,024 MiB` and `1.0 GiB`: one quantity written two
        ways, by a size and a limit one byte apart, whichever of them is the
        larger."""
        limit = GIB - 1
        self.assertEqual((format_size(limit), format_size(GIB)),
                         ("1,024 MiB", "1.0 GiB"))
        self.assertEqual(self._line(limit, GIB).text,
                         "resident size 1.0 GiB at 09:12, 1 B past the limit of "
                         "1,024 MiB (now 1.0 GiB)")
        self.assertEqual(self._line(GIB, limit).text,
                         "resident size 1,024 MiB at 09:12, 1 B below the limit of "
                         "1.0 GiB (now 1,024 MiB)")

    def test_a_tenth_of_a_gibibyte_hides_more_and_the_line_says_how_much(self):
        """On either side of the limit: 46 MiB below 8 GiB is written `8.0 GiB`
        too, and at 99.4 % of it the share would be a `99 %` beside two figures
        that read alike."""
        line = self._line(8 * GIB, 8 * GIB + 41 * MIB)
        self.assertEqual(line.text, "resident size 8.0 GiB at 09:12, 41.0 MiB past "
                                    "the limit of 8.0 GiB (now 8.0 GiB)")
        line = self._line(8 * GIB, 8 * GIB - 46 * MIB)
        self.assertEqual(line.text, "resident size 8.0 GiB at 09:12, 46.0 MiB below "
                                    "the limit of 8.0 GiB (now 8.0 GiB)")

    def test_no_size_beside_a_limit_reads_as_the_limit(self):
        """The sentence, over the limits a machine may give and the sizes around
        each, on both sides: wherever the size is not the limit, the line names the
        distance, or writes two figures a reader holds apart — and below the limit
        a share of it that is not 100 %."""
        for limit in (int(917 * MIB * 0.55), 504 * MIB, GIB - 1, GIB, GIB + 1,
                      int(1.95 * GIB), 8 * GIB):
            for apart in (1, 1023, 1024, 512 * 1024, MIB - 1, MIB, 2 * MIB,
                          3 * MIB, 60 * MIB):
                for side, code in (("past", StatusCode.ERROR),
                                   ("below", StatusCode.WARN)):
                    size = limit + apart if side == "past" else limit - apart
                    with self.subTest(limit=limit, size=size):
                        line = self._line(limit, size)
                        self.assertIs(line.code, code)
                        named, said = line.text.split(" at 09:12, ")
                        figure = named.removeprefix("resident size ")
                        written = format_size(limit)
                        said = said.split(" (now ")[0]
                        if said == (f"{format_weight(apart)} {side} the limit of "
                                    f"{written}"):
                            continue
                        self.assertNotEqual(_quantity(figure), _quantity(written),
                                            line.text)
                        if side == "past":
                            self.assertEqual(said, f"past the limit of {written}")
                        else:
                            share, percent, rest = said.split(" ", 2)
                            self.assertEqual((percent, rest),
                                             ("%", f"of the limit of {written}"))
                            self.assertLess(int(share), 100, line.text)


class PoolTests(TestCase):
    """The pool is saturated once a check has waited for a worker longer than the
    grace; the line names how many are waiting and the longest wait, and clears
    when nothing waits."""

    def test_a_wait_within_the_grace_is_not_saturation(self):
        report = _report()
        report.observe(0.0, entries=0, late=[],
                       waiting=[Waiting("/a", POOL_WAIT_SECONDS)])
        self.assertNotIn("pool", _slugs(report))

    def test_a_wait_past_the_grace_is_the_line_with_count_and_longest(self):
        report = _report(workers=8)
        report.observe(0.0, entries=0, late=[],
                       waiting=[Waiting("/a", 3.0), Waiting("/b", 25.0),
                                Waiting("/c", 12.0)])
        line = _line(report, "pool")
        self.assertIs(line.code, StatusCode.WARN)
        self.assertEqual(line.text, "the pool is saturated: 3 checks are waiting "
                                    "for one of its 8 workers, the longest for "
                                    "25 s")

    def test_one_check_on_one_worker_reads_in_the_singular(self):
        report = _report(workers=1)
        report.observe(0.0, entries=0, late=[], waiting=[Waiting("/a", 11.0)])
        self.assertEqual(_line(report, "pool").text,
                         "the pool is saturated: 1 check is waiting for its 1 "
                         "worker, the longest for 11 s")

    def test_the_line_clears_when_nothing_waits(self):
        report = _report()
        report.observe(0.0, entries=0, late=[], waiting=[Waiting("/a", 30.0)])
        report.observe(1.0, entries=0, late=[], waiting=[])
        self.assertNotIn("pool", _slugs(report))


class SchedulerLagTests(TestCase):
    """A tick that came more than the threshold late, beyond the poll interval, is
    a line for the length of the window, saying the worst lag inside it; then it
    clears."""

    def test_the_first_tick_and_a_punctual_one_say_nothing(self):
        report = _report(poll_interval=1.0)
        report.observe(100.0, entries=0, waiting=[], late=[])
        report.observe(101.0 + LAG_SECONDS, entries=0, waiting=[], late=[])
        self.assertNotIn("lag", _slugs(report))

    def test_a_late_tick_is_the_line(self):
        report = _report(poll_interval=1.0)
        report.observe(100.0, entries=0, waiting=[], late=[])
        report.observe(113.0, entries=0, waiting=[], late=[])
        line = _line(report, "lag")
        self.assertIs(line.code, StatusCode.WARN)
        self.assertEqual(line.text, "the scheduler came late within the last 10m: "
                                    "a tick came 13 s after the one before, "
                                    "against an interval of 1s")

    def test_a_late_tick_is_logged_in_the_same_call_that_records_it(self):
        report = _report(poll_interval=1.0)
        report.observe(100.0, entries=0, waiting=[], late=[])
        with self.assertLogs("little_sister", level="WARNING") as logged:
            report.observe(113.0, entries=0, waiting=[], late=[])
        self.assertIn("lag: the scheduler came late", logged.output[0])

    def test_the_worst_lag_inside_the_window_is_what_it_says(self):
        report = _report(poll_interval=1.0)
        report.observe(100.0, entries=0, waiting=[], late=[])
        report.observe(130.0, entries=0, waiting=[], late=[])   # 29 s late
        report.observe(140.0, entries=0, waiting=[], late=[])   # 9 s late
        self.assertIn("a tick came 30 s after", _line(report, "lag").text)

    def test_the_line_outlives_the_tick_for_the_window_and_then_clears(self):
        # A short window, and punctual ticks through it: a clock jumped past the
        # window would itself be a late tick, which is the point of the line.
        report = _report(poll_interval=1.0,
                         limits=Limits(entry_limit=100, lag_memory_seconds=30.0))
        report.observe(100.0, entries=0, waiting=[], late=[])
        report.observe(120.0, entries=0, waiting=[], late=[])   # 19 s late, at 120
        for second in range(121, 151):
            report.observe(float(second), entries=0, waiting=[], late=[])
        self.assertIn("lag", _slugs(report))                   # 30 s on: still
        report.observe(151.0, entries=0, waiting=[], late=[])
        self.assertNotIn("lag", _slugs(report))                # 31 s on: gone

    def test_an_older_worst_ages_out_and_leaves_the_younger_one(self):
        report = _report(poll_interval=1.0,
                         limits=Limits(entry_limit=100, lag_memory_seconds=30.0))
        report.observe(100.0, entries=0, waiting=[], late=[])
        report.observe(120.0, entries=0, waiting=[], late=[])   # 19 s late, at 120
        for second in range(121, 130):
            report.observe(float(second), entries=0, waiting=[], late=[])
        report.observe(140.0, entries=0, waiting=[], late=[])   # 10 s late, at 140
        self.assertIn("a tick came 20 s after", _line(report, "lag").text)
        for second in range(141, 152):
            report.observe(float(second), entries=0, waiting=[], late=[])
        self.assertIn("a tick came 11 s after", _line(report, "lag").text)


class LateRunTests(TestCase):
    """A run longer than its period is a late run, not a broken one: one WARN
    line per check, for the run in flight or the last one, under a slug from the
    path."""

    def test_a_run_in_flight_past_its_period(self):
        report = _report()
        report.observe(0.0, entries=0, waiting=[],
                       late=[LateRun("/aws/prod", 130.0, 60, in_flight=True)])
        line = _line(report, "late.aws-prod")
        self.assertIs(line.code, StatusCode.WARN)
        self.assertEqual(line.text, "/aws/prod has been running for 2m 10s, longer "
                                    "than its frequency of 1m — it runs late")

    def test_the_last_run_past_its_period(self):
        report = _report()
        report.observe(0.0, entries=0, waiting=[],
                       late=[LateRun("/backup", 1000.5, 900, in_flight=False)])
        self.assertEqual(_line(report, "late.backup").text,
                         "/backup ran for 16m 40s, longer than its frequency of "
                         "15m — it runs late")

    def test_a_path_with_markdown_in_it_renders_literally(self):
        report = _report()
        report.observe(0.0, entries=0, waiting=[],
                       late=[LateRun("/hosts/*star*", 70.0, 60, in_flight=True)])
        self.assertIn(r"/hosts/\*star\* has been", _line(
            report, "late.hosts-star").text)

    def test_the_line_clears_with_the_next_run_that_fits(self):
        report = _report()
        report.observe(0.0, entries=0, waiting=[],
                       late=[LateRun("/x", 70.0, 60, in_flight=False)])
        report.observe(1.0, entries=0, waiting=[], late=[])
        self.assertEqual(_slugs(report), [])


class MayRunLateTests(TestCase):
    """A timeout longer than the frequency is a configuration that can run late:
    a fact in the engine's report for the life of the process (ADR-0044 §6,
    ADR-0076), never a line, so the node stays OK until a run actually does."""

    def test_only_a_timeout_past_the_frequency_counts(self):
        found = may_run_late([_check("/equal", timeout=60.0, frequency=60),
                              _check("/over", timeout=120.0, frequency=60),
                              _check("/under", timeout=30.0, frequency=60)])
        self.assertEqual([late.path for late in found], ["/over"])

    def test_it_is_a_fact_in_the_report_and_no_line_names_both_numbers(self):
        report = _report([_check("/aws/prod", timeout=120.0, frequency=60)])
        report.observe(0.0, entries=0, waiting=[], late=[])
        self.assertEqual(_slugs(report), [])
        self.assertIn("/aws/prod may run late: its timeout of 2m is longer than "
                      "its frequency of 1m", report.report())

    def test_it_stands_before_the_first_tick_is_observed(self):
        report = _report([_check("/aws/prod", timeout=120.0, frequency=60)])
        self.assertIn("may run late", report.report())

    def test_nothing_to_say_is_an_empty_report(self):
        report = _report([_check("/aws/prod", timeout=30.0, frequency=60)])
        self.assertEqual(report.report(), "")


class LimitsFromTheMachineTests(TestCase):
    """The memory limit is half of what the machine gives the process; none where
    the machine cannot say."""

    def test_half_of_what_the_machine_gives(self):
        with patch.object(limits_module, "machine_memory", return_value=4 * GIB):
            limits = Limits.from_machine()
        self.assertEqual(limits.memory_limit, int(4 * GIB * MEMORY_SHARE))
        self.assertEqual(limits.machine_memory, 4 * GIB)
        self.assertEqual(limits.entry_limit, ENTRY_LIMIT)
        self.assertEqual(limits.amber_share, AMBER_SHARE)

    def test_none_where_the_machine_cannot_say(self):
        with patch.object(limits_module, "machine_memory", return_value=None):
            limits = Limits.from_machine()
        self.assertIsNone(limits.memory_limit)
        self.assertIsNone(limits.machine_memory)

    def test_a_cgroup_limit_smaller_than_physical_memory_is_what_counts(self):
        with patch.object(limits_module, "_physical_memory", return_value=16 * GIB), \
                patch.object(limits_module, "_cgroup_memory_limit",
                             return_value=512 * MIB):
            self.assertEqual(machine_memory(), 512 * MIB)

    def test_a_cgroup_without_a_limit_leaves_physical_memory(self):
        with patch.object(limits_module, "_physical_memory", return_value=16 * GIB), \
                patch.object(limits_module, "_cgroup_memory_limit",
                             return_value=None):
            self.assertEqual(machine_memory(), 16 * GIB)

    def test_a_cgroup_v1_no_limit_is_a_huge_number_and_loses_to_physical(self):
        with patch.object(limits_module, "_physical_memory", return_value=16 * GIB), \
                patch.object(limits_module, "_cgroup_memory_limit",
                             return_value=9223372036854771712):
            self.assertEqual(machine_memory(), 16 * GIB)

    def test_nothing_readable_is_none(self):
        with patch.object(limits_module, "_physical_memory", return_value=None), \
                patch.object(limits_module, "_cgroup_memory_limit",
                             return_value=None):
            self.assertIsNone(machine_memory())


class DeclaredCostTests(TestCase):
    """What a check declares it costs, read from the two methods and nothing else
    (ADR-0075). A type's estimate is code the library does not own, so a
    declaration it cannot read is a warning and a silence — never a refusal."""

    def test_a_check_that_declares_nothing_is_not_in_the_sum(self):
        self.assertEqual(declared_costs([_check("/a"), _check("/b")]), ())

    def test_a_check_that_answers_none_declares_nothing(self):
        self.assertEqual(declared_costs([_declaring("/a")]), ())

    def test_a_cost_is_the_share_of_a_worker_it_wants_over_its_period(self):
        declared, = declared_costs([_declaring("/a", cost=30.0, frequency=60)])
        self.assertEqual(declared.cost_seconds, 30.0)
        self.assertEqual(declared.workers, 0.5)

    def test_a_check_with_no_period_asks_for_no_worker_time(self):
        # nothing divides by zero here: a check with no period is run once
        declared, = declared_costs([_declaring("/a", cost=30.0, frequency=0)])
        self.assertEqual(declared.workers, 0.0)

    def test_entries_are_declared_without_a_cost_and_the_other_way_round(self):
        entries_only, = declared_costs([_declaring("/a", entries=40)])
        self.assertIsNone(entries_only.cost_seconds)
        self.assertEqual(entries_only.entries, 40)
        cost_only, = declared_costs([_declaring("/b", cost=1.0)])
        self.assertIsNone(cost_only.entries)

    def test_a_declaration_that_raises_is_undeclared_and_warns(self):
        def boom():
            raise RuntimeError("no idea")
        check = SimpleNamespace(path="/a", frequency_seconds=60,
                                expected_cost=boom, expected_entries=lambda: None)
        with self.assertLogs(level="WARNING") as caught:
            self.assertEqual(declared_costs([check]), ())
        self.assertIn("/a", "".join(caught.output))

    def test_a_declaration_that_is_not_a_non_negative_number_is_undeclared(self):
        for value in ("soon", -1, float("nan")):
            with self.subTest(value=value), self.assertLogs(level="WARNING"):
                self.assertEqual(declared_costs([_declaring("/a", cost=value)]), ())


class CapacityTests(TestCase):
    """The sums startup measures a configuration against: worker threads and
    reason entries, refused past a limit and warned about at 80 % of one."""

    def _capacity(self, checks, *, workers=4, entry_limit=100):
        return capacity(checks, max_workers=workers,
                        limits=Limits(entry_limit=entry_limit),
                        record_floor=FAILURE_RECORD_BYTES)

    def test_a_declared_load_that_fits_refuses_and_warns_nothing(self):
        fits = self._capacity([_declaring("/a", cost=30.0, frequency=60, entries=10)])
        self.assertEqual(fits.workers, 0.5)
        self.assertEqual(fits.entries, 10)
        self.assertEqual(fits.refusals(), ())
        self.assertEqual(fits.warnings(), ())

    def test_a_load_past_the_worker_count_is_refused_naming_the_worst_first(self):
        refused = self._capacity([
            _declaring("/small", cost=60.0, frequency=60),      # 1.0 worker
            _declaring("/big", cost=900.0, frequency=180),      # 5.0 workers
        ])
        said, = refused.refusals()
        self.assertEqual(
            said,
            "the configured checks declare 6.0 worker threads' worth of run time, "
            "past the 4 this engine runs: /big 5.0 (15m every 3m), "
            "/small 1.0 (1m every 1m)")

    def test_a_load_equal_to_the_worker_count_fits(self):
        exactly = self._capacity([_declaring("/a", cost=240.0, frequency=60)])
        self.assertEqual(exactly.workers, 4.0)
        self.assertEqual(exactly.refusals(), ())

    def test_declared_entries_past_the_limit_are_refused_naming_the_checks(self):
        refused = self._capacity([_declaring("/a", entries=60),
                                  _declaring("/b", entries=80)])
        said, = refused.refusals()
        self.assertEqual(
            said,
            "the configured checks declare 140 reason entries, past the limit of "
            "100: /b 80, /a 60")

    def test_a_refusal_names_five_checks_and_counts_the_rest(self):
        refused = self._capacity(
            [_declaring(f"/c{index}", entries=30) for index in range(7)])
        said, = refused.refusals()
        self.assertEqual(said.count("/c"), NAMED_IN_A_LINE)
        self.assertTrue(said.endswith("and 2 more"), said)

    def test_the_amber_band_warns_per_limit_and_says_which(self):
        near = self._capacity([_declaring("/a", cost=210.0, frequency=60,
                                          entries=85)])
        threads, entries = near.warnings()
        self.assertEqual(threads[0], "threads")
        self.assertEqual(
            threads[1],
            "the configured checks declare 3.5 of the 4 worker threads this "
            "engine runs (88 %): /a 3.5 (3m 30s every 1m)")
        self.assertEqual(entries[0], "entries")
        self.assertEqual(
            entries[1],
            "the configured checks declare 85 reason entries, 85 % of the limit "
            "of 100: /a 85")

    def test_below_the_amber_share_says_nothing(self):
        quiet = self._capacity([_declaring("/a", cost=60.0, frequency=60,
                                           entries=50)])
        self.assertEqual(quiet.warnings(), ())

    def test_a_refused_limit_does_not_also_warn(self):
        # the refusal is the louder half of the same sentence
        refused = self._capacity([_declaring("/a", cost=600.0, frequency=60,
                                             entries=400)])
        self.assertEqual(len(refused.refusals()), 2)
        self.assertEqual(refused.warnings(), ())


class DeclaredRecordTests(TestCase):
    """The third declaration, and the one that is compared rather than summed: a
    record limit bounds one record, so what matters is whether a type's largest
    fits — not what every type wants together."""

    def _capacity(self, checks, *, record_limit=2_048):
        return capacity(checks, max_workers=4,
                        limits=Limits(entry_limit=100,
                                      record_limit=record_limit),
                        record_floor=FAILURE_RECORD_BYTES)

    def test_a_record_declaration_alone_is_read(self):
        # a type that estimates nothing else still declares something
        declared, = declared_costs([_declaring("/a", record=900)])
        self.assertEqual(declared.record_bytes, 900)
        self.assertIsNone(declared.cost_seconds)
        self.assertIsNone(declared.entries)

    def test_a_declaration_over_the_limit_refuses_and_names_the_check(self):
        refused = self._capacity([_declaring("/a", record=4_096)],
                                 record_limit=2_048)
        said, = refused.refusals()
        self.assertIn("/a", said)
        self.assertIn("4,096", said)
        self.assertIn("2,048", said)

    def test_a_declaration_at_the_limit_fits(self):
        # the limit is what a record may weigh, not what it must stay under
        exactly = self._capacity([_declaring("/a", record=2_048)],
                                 record_limit=2_048)
        self.assertEqual(exactly.refusals(), ())

    def test_declarations_are_not_summed(self):
        # the decisive difference from the two limits above it: three checks each
        # holding 1.5 kB of record are three checks that fit, not 4.5 kB that does
        # not. Sum them and every deployment with a few record-bearing types would
        # be refused for a bound none of them crosses.
        fits = self._capacity([_declaring("/a", record=1_500),
                               _declaring("/b", record=1_500),
                               _declaring("/c", record=1_500)],
                              record_limit=2_048)
        self.assertEqual(fits.refusals(), ())

    def test_near_the_limit_is_a_line_under_its_own_key(self):
        near = self._capacity([_declaring("/a", record=1_700)],
                              record_limit=2_048)
        self.assertEqual(near.refusals(), ())
        (limit, said), = near.warnings()
        self.assertEqual(limit, "record")
        self.assertIn("/a", said)
        self.assertIn("1,700", said)

    def test_comfortably_inside_the_limit_says_nothing(self):
        quiet = self._capacity([_declaring("/a", record=200)],
                               record_limit=2_048)
        self.assertEqual(quiet.refusals(), ())
        self.assertEqual(quiet.warnings(), ())

    # --- the engine's failure record is a floor (ADR-0086 decision 5) --------

    def test_a_declaration_below_the_floor_is_compared_at_the_floor(self):
        """Any check may raise, and the record the engine then writes for it can
        weigh `FAILURE_RECORD_BYTES`; a type declaring less is held to that, and
        what it said itself is kept beside it for the page."""
        self.assertLess(64, FAILURE_RECORD_BYTES)
        declared, = declared_costs([_declaring("/a", record=64)],
                                   record_floor=FAILURE_RECORD_BYTES)
        self.assertEqual(declared.record_bytes, FAILURE_RECORD_BYTES)
        self.assertEqual(declared.record_stated, 64)

    def test_the_floor_is_what_the_limit_is_compared_against(self):
        # a record_limit between the two numbers: the type's own 64 would fit,
        # the record the engine can write for it does not
        refused = self._capacity([_declaring("/a", record=64)],
                                 record_limit=FAILURE_RECORD_BYTES - 1)
        said, = refused.refusals()
        self.assertIn("/a", said)
        self.assertIn(f"{FAILURE_RECORD_BYTES:,}", said)

    def test_a_declaration_above_the_floor_is_unchanged(self):
        declared, = declared_costs([_declaring("/a", record=900)],
                                   record_floor=FAILURE_RECORD_BYTES)
        self.assertEqual(declared.record_bytes, 900)
        self.assertIsNone(declared.record_stated)

    def test_a_declaration_at_the_floor_is_the_types_own(self):
        declared, = declared_costs([_declaring("/a", record=FAILURE_RECORD_BYTES)],
                                   record_floor=FAILURE_RECORD_BYTES)
        self.assertEqual(declared.record_bytes, FAILURE_RECORD_BYTES)
        self.assertIsNone(declared.record_stated)

    def test_a_type_that_declares_no_record_stays_undeclared(self):
        """The library makes no claim a type did not make: a check declaring a
        cost but no record is not given the floor as a record size."""
        declared, = declared_costs([_declaring("/a", cost=5.0)],
                                   record_floor=FAILURE_RECORD_BYTES)
        self.assertIsNone(declared.record_bytes)
        self.assertIsNone(declared.record_stated)

    def test_a_declaration_the_library_cannot_read_is_a_silence(self):
        # a type's estimate is code the library does not own (ADR-0075 decision 4):
        # never a reason a monitoring process cannot start
        raising = SimpleNamespace(
            path="/a", timeout_seconds=30.0, frequency_seconds=60,
            expected_cost=lambda: None, expected_entries=lambda: None,
            expected_record=lambda: (_ for _ in ()).throw(RuntimeError("boom")))
        with self.assertLogs(level="WARNING"):
            self.assertEqual(declared_costs([raising]), ())


class CapacityLineTests(TestCase):
    """What the declared sums say on `/little-sister`: an uncoded line per limit
    in the amber band, and nothing below it — a sum that fits must not make the
    node amber for the life of the process."""

    def _near_the_workers(self):
        return capacity([_declaring("/a", cost=210.0, frequency=60)],
                        max_workers=4, limits=Limits(entry_limit=100),
                        record_floor=FAILURE_RECORD_BYTES)

    def test_a_load_that_fits_quietly_says_nothing(self):
        report = _report(capacity=capacity(
            [_declaring("/a", cost=60.0, frequency=60)],
            max_workers=4, limits=Limits(entry_limit=100),
            record_floor=FAILURE_RECORD_BYTES))
        report.observe(0.0, entries=0, waiting=[], late=[])
        self.assertEqual(_slugs(report), [])

    def test_the_amber_band_is_a_fact_in_the_report_and_no_line(self):
        report = _report(capacity=self._near_the_workers())
        report.observe(0.0, entries=0, waiting=[], late=[])
        self.assertEqual(_slugs(report), [])
        self.assertIn(
            "the configured checks declare 3.5 of the 4 worker threads this "
            "engine runs (88 %): /a 3.5 (3m 30s every 1m)", report.report())

    def test_it_stands_before_the_first_tick_is_observed(self):
        report = _report(capacity=self._near_the_workers())
        self.assertIn("88 %", report.report())

    def test_no_arithmetic_at_all_is_no_line(self):
        report = _report(capacity=None)
        report.observe(0.0, entries=0, waiting=[], late=[])
        self.assertEqual(_slugs(report), [])


class WeightTests(TestCase):
    """A weight in bytes at the resolution a series line needs — and, since the
    binary sizes became units a curve is written in, a volume of terabytes too:
    `format_weight` gains TiB (ADR-0096 decision 3)."""

    def test_each_binary_unit_where_it_begins(self) -> None:
        self.assertEqual(format_weight(1023), "1,023 B")
        self.assertEqual(format_weight(1024), "1.0 KiB")
        self.assertEqual(format_weight(1024 ** 2), "1.0 MiB")
        self.assertEqual(format_weight(1024 ** 3), "1.0 GiB")
        self.assertEqual(format_weight(1024 ** 4), "1.0 TiB")

    def test_a_volume_reads_in_tib_and_not_in_thousands_of_gib(self) -> None:
        self.assertEqual(format_weight(1023 * 1024 ** 3), "1,023.0 GiB")
        self.assertEqual(format_weight(5_835_678_284 * 1024), "5.4 TiB")
