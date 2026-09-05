"""The engine's own lines (ADR-0072): what the engine measures against its limits
as it runs, and the sentences the heartbeat carries — tested from the claims
``architecture.md`` §4.6 makes, with the values the claims are about. The engine's
side of it — what it records on the tick — is in ``test_engine.py``."""
from __future__ import annotations

import builtins
from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import patch

from little_sister import limits as limits_module
from little_sister.limits import (
    AMBER_SHARE,
    ENTRY_LIMIT,
    LAG_SECONDS,
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
    machine_memory,
    may_run_late,
    resident_size,
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


def _declaring(path: str, *, cost=None, entries=None, frequency: int = 60):
    """A check that declares what it costs — the two methods `Check` grew, which
    is all `declared_costs` reads."""
    return SimpleNamespace(path=path, timeout_seconds=30.0,
                           frequency_seconds=frequency,
                           expected_cost=lambda: cost,
                           expected_entries=lambda: entries)


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


class MemoryTests(TestCase):
    """The resident size against the memory limit, the same shape; no line where
    the machine could not say; a high-water mark is called the peak it is."""

    def _limits(self) -> Limits:
        return Limits(memory_limit=GIB, machine_memory=2 * GIB)

    def test_below_the_amber_share_says_nothing(self):
        report = _report(limits=self._limits(),
                         resident=lambda: Resident(700 * MIB, peak=False))
        report.observe(0.0, entries=0, waiting=[], late=[])
        self.assertNotIn("memory", _slugs(report))

    def test_the_amber_share_names_the_size_the_limit_and_the_machine(self):
        report = _report(limits=self._limits(),
                         resident=lambda: Resident(int(GIB * 0.85), peak=False))
        report.observe(0.0, entries=0, waiting=[], late=[])
        line = _line(report, "memory")
        self.assertIs(line.code, StatusCode.WARN)
        self.assertEqual(line.text, "resident size 870 MiB, 85 % of the limit of "
                                    "1.0 GiB (of the 2.0 GiB the machine gives "
                                    "the process)")

    def test_the_limit_is_an_error(self):
        report = _report(limits=self._limits(),
                         resident=lambda: Resident(GIB, peak=False))
        report.observe(0.0, entries=0, waiting=[], late=[])
        line = _line(report, "memory")
        self.assertIs(line.code, StatusCode.ERROR)
        self.assertTrue(line.text.startswith(
            "resident size 1.0 GiB, past the limit of 1.0 GiB"), line.text)

    def test_a_peak_is_named_as_one(self):
        report = _report(limits=self._limits(),
                         resident=lambda: Resident(GIB, peak=True))
        report.observe(0.0, entries=0, waiting=[], late=[])
        self.assertTrue(_line(report, "memory").text.startswith(
            "peak resident size 1.0 GiB"))

    def test_no_limit_means_no_line_however_large_the_process(self):
        report = _report(limits=Limits(memory_limit=None),
                         resident=lambda: Resident(64 * GIB, peak=False))
        report.observe(0.0, entries=0, waiting=[], late=[])
        self.assertNotIn("memory", _slugs(report))

    def test_no_measurement_means_no_line(self):
        report = _report(limits=self._limits(), resident=lambda: None)
        report.observe(0.0, entries=0, waiting=[], late=[])
        self.assertNotIn("memory", _slugs(report))


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


class ResidentSizeTests(TestCase):
    """The resident size is read from the kernel's own record of the process:
    ``/proc/self/statm`` where it exists, else the high-water mark ``getrusage``
    keeps, marked as the peak it is."""

    def test_this_machine_answers_with_a_positive_size(self):
        measured = resident_size()
        assert measured is not None
        self.assertGreater(measured.bytes, 0)

    def test_without_proc_the_high_water_mark_is_the_answer(self):
        real_open = builtins.open

        def no_proc(path, *args, **kwargs):
            if str(path) == "/proc/self/statm":
                raise OSError("no /proc here")
            return real_open(path, *args, **kwargs)

        with patch.object(builtins, "open", no_proc):
            measured = resident_size()
        assert measured is not None
        self.assertTrue(measured.peak)
        self.assertGreater(measured.bytes, 0)


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
                        limits=Limits(entry_limit=entry_limit))

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


class CapacityLineTests(TestCase):
    """What the declared sums say on `/little-sister`: an uncoded line per limit
    in the amber band, and nothing below it — a sum that fits must not make the
    node amber for the life of the process."""

    def _near_the_workers(self):
        return capacity([_declaring("/a", cost=210.0, frequency=60)],
                        max_workers=4, limits=Limits(entry_limit=100))

    def test_a_load_that_fits_quietly_says_nothing(self):
        report = _report(capacity=capacity(
            [_declaring("/a", cost=60.0, frequency=60)],
            max_workers=4, limits=Limits(entry_limit=100)))
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
