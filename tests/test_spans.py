"""How a span of time is written — `little_sister.spans`.

The tests are written from the module's claims, not from its branches: each one
names a sentence the docstrings make and uses the values that sentence is about.
"""
import time
import unittest
from collections.abc import Sequence
from datetime import UTC, datetime, timedelta, timezone
from unittest import mock

from little_sister.checks import Measurement
from little_sister.checks.base import CheckResult
from little_sister.engine import Engine
from little_sister.spans import (
    coarse_span,
    format_duration,
    format_span,
    format_tolerance,
    local_time,
)
from little_sister.status import StatusCode
from little_sister.tree import StatusTree
from tests.test_engine import _FakeCheck
from tests.test_stored_instants import _zone


class FormatSpanTests(unittest.TestCase):
    """`format_span` — a measured span, ~3 significant figures at every scale."""

    def test_the_reported_defect_no_longer_reproduces(self):
        """The two readings from the system page that started this: a run of
        115 seconds and a wait of 812. Neither may render as bare seconds."""
        self.assertEqual(format_span(115), "1m 55s")
        self.assertEqual(format_span(812), "13m 32s")

    def test_the_ladder_changes_units_so_the_number_stays_small(self):
        for seconds, expected in ((0.412, "412 ms"),
                                  (3.14159, "3.1 s"),
                                  (42.7, "43 s"),
                                  (115, "1m 55s"),
                                  (7620, "2h 7m"),
                                  (97200, "1d 3h")):
            with self.subTest(seconds=seconds):
                self.assertEqual(format_span(seconds), expected)

    def test_no_rendering_is_wider_than_a_column(self):
        """The claim the ladder is *for*: a millisecond run and a two-day run
        occupy about the same width, so a table column does not jump."""
        for seconds in (0.412, 3.14159, 42.7, 115, 7620, 97200, 8 * 86400):
            with self.subTest(seconds=seconds):
                self.assertLessEqual(len(format_span(seconds)), 7)

    def test_a_zero_lower_unit_is_dropped(self):
        """`2m 0s` says nothing the `2m` does not."""
        self.assertEqual(format_span(120), "2m")
        self.assertEqual(format_span(7200), "2h")
        self.assertEqual(format_span(172800), "2d")
        # …and it appears again as soon as it carries information
        self.assertEqual(format_span(121), "2m 1s")
        self.assertEqual(format_span(7260), "2h 1m")
        self.assertEqual(format_span(176400), "2d 1h")

    def test_the_boundaries_belong_to_the_larger_unit(self):
        self.assertEqual(format_span(59.4), "59 s")
        self.assertEqual(format_span(60), "1m")
        self.assertEqual(format_span(3599), "59m 59s")
        self.assertEqual(format_span(3600), "1h")
        self.assertEqual(format_span(86399), "23h 59m")
        self.assertEqual(format_span(86400), "1d")

    def test_rounding_never_shows_a_value_the_rung_below_denied(self):
        """119.6 s renders `2m`, not `1m 59s`: every rung above the minute
        already displays whole seconds, so the seconds are rounded first."""
        self.assertEqual(format_span(119.6), "2m")
        self.assertEqual(format_span(59.6), "60 s")

    def test_nothing_below_the_second_survives_past_a_minute(self):
        self.assertEqual(format_span(115.37), "1m 55s")

    def test_an_absent_measurement_is_not_a_zero(self):
        """Before the first run there is no number, and `0 s` would be a claim."""
        self.assertEqual(format_span(None), "—")
        self.assertEqual(format_span(None, none="never run"), "never run")

    def test_a_negative_span_reads_as_a_moment_not_as_a_bug(self):
        """A countdown read just past its deadline, or a clock that stepped
        back. `-3 s` on a dashboard reads as a broken page."""
        self.assertEqual(format_span(-3), "0 s")
        self.assertEqual(format_span(0), "0 s")

    def test_a_fast_check_is_milliseconds_rather_than_no_time_at_all(self):
        self.assertEqual(format_span(0.0004), "0 ms")
        self.assertEqual(format_span(0.9996), "1000 ms")


class CoarseSpanTests(unittest.TestCase):
    """`coarse_span` — a bound, deliberately lossy, for a page that is not
    re-rendered while somebody reads it."""

    def test_it_states_the_largest_one_or_two_units(self):
        for seconds, expected in ((2 * 86400 + 3 * 3600, "2d 3h"),
                                  (5 * 3600, "5h"),
                                  (12 * 60, "12m"),
                                  (30, "< 1m")):
            with self.subTest(seconds=seconds):
                self.assertEqual(coarse_span(seconds), expected)

    def test_it_never_names_a_second(self):
        """A bound that names seconds is out of date before the sentence ends,
        which is the whole reason this is not `format_span`."""
        for seconds in (61, 3661, 90061, 59):
            with self.subTest(seconds=seconds):
                self.assertNotIn("s", coarse_span(seconds).replace("< 1m", ""))

    def test_it_rounds_down_so_the_bound_stays_true(self):
        """`> 2m ago` must not become a lie by rounding up to 3m."""
        self.assertEqual(coarse_span(179), "2m")
        self.assertEqual(coarse_span(7199), "1h 59m")


if __name__ == "__main__":   # pragma: no cover
    unittest.main()


class FormatDurationTests(unittest.TestCase):
    """`format_duration` — a *configured* interval, in the units it was written in."""

    def test_it_writes_back_what_somebody_typed(self):
        for seconds, expected in ((900, "15m"), (3600, "1h"), (86400, "1d"),
                                  (90, "90s"), (300, "5m"), (172800, "2d"),
                                  (604800, "1w"), (1209600, "2w")):
            with self.subTest(seconds=seconds):
                self.assertEqual(format_duration(seconds), expected)

    def test_a_week_is_the_largest_unit_and_days_stay_days(self):
        """`1w` is what `parse_duration` reads, so it is what this writes back;
        eight days are `8d`, never `1w 1d`, by the same one-unit rule as below."""
        self.assertEqual(format_duration(7 * 86400), "1w")
        self.assertEqual(format_duration(8 * 86400), "8d")
        self.assertEqual(format_duration(14 * 86400), "2w")

    def test_it_is_the_other_reading_of_the_same_number(self):
        """The distinction the module exists to keep: 90 seconds is how a config
        says `90s` and how a *measurement* says `1m 30s`. Picking the wrong one is
        how a page claims a check runs every `1m 30s`."""
        self.assertEqual(format_duration(90), "90s")
        self.assertEqual(format_span(90), "1m 30s")
        self.assertEqual(format_duration(3660), "61m")
        self.assertEqual(format_span(3660), "1h 1m")

    def test_the_largest_exact_unit_wins_and_there_is_never_a_second_one(self):
        """`2h 1m` is not what anybody typed. An interval no larger unit divides
        exactly stays whole in the largest one that does — 7260 seconds is `121m`,
        never `2h 1m` and never `7260s` — and seconds are the floor, not the
        fallback for anything awkward."""
        self.assertEqual(format_duration(7200), "2h")
        self.assertEqual(format_duration(7260), "121m")
        self.assertEqual(format_duration(3660), "61m")
        self.assertEqual(format_duration(91), "91s")

    def test_a_frequency_of_zero_is_not_an_interval(self):
        self.assertEqual(format_duration(0), "—")
        self.assertEqual(format_duration(None), "—")
        self.assertEqual(format_duration(None, none="never"), "never")


class LocalTimeTests(unittest.TestCase):
    """`local_time` — one instant, in the settings' zone and format."""

    def _settings(self, zone: str, fmt: str):
        from zoneinfo import ZoneInfo
        return mock.patch("little_sister.config.config",
                          mock.Mock(tzinfo=ZoneInfo(zone), time_format=fmt))

    def test_an_aware_instant_is_written_in_the_configured_zone(self):
        moment = datetime(2026, 9, 4, 20, 32, 39, tzinfo=UTC)
        with self._settings("Europe/Berlin", "%Y-%m-%d %H:%M:%S"):
            self.assertEqual(local_time(moment), "2026-09-04 22:32:39")

    def test_a_fixed_offset_is_converted_too(self):
        moment = datetime(2026, 9, 4, 16, 38, 43, tzinfo=timezone(timedelta(hours=-4)))
        with self._settings("Europe/Berlin", "%H:%M:%S"):
            self.assertEqual(local_time(moment), "22:38:43")

    def test_the_format_may_be_overridden_and_the_zone_may_not(self):
        moment = datetime(2026, 9, 4, 20, 32, 39, tzinfo=UTC)
        with self._settings("Europe/Berlin", "%Y-%m-%d %H:%M:%S"):
            self.assertEqual(local_time(moment, "%H:%M"), "22:32")

    #: A time without a zone, on purpose: what a clock in Berlin showed, with
    #: nothing to say whose clock it was — the time `local_time` refuses.
    BARE = datetime(2026, 9, 4, 22, 32, 39)  # noqa: DTZ001

    def test_a_time_without_a_zone_is_refused_in_words_that_name_the_call(self):
        with self._settings("Europe/Berlin", "%Y-%m-%d %H:%M:%S"):
            with self.assertRaises(ValueError) as refused:
                local_time(self.BARE)
        self.assertEqual(
            str(refused.exception),
            "the moment handed to local_time is a time without a zone, and no "
            "instant: '2026-09-04T22:32:39'")

    @unittest.skipUnless(hasattr(time, "tzset"), "no tzset on this platform")
    def test_it_is_read_as_no_machines_clock(self):
        # what it was read as before: the clock of the machine the process runs
        # on — an answer for every machine, and a different one on each
        for machine in ("UTC", "America/New_York", "Europe/Berlin"):
            with self.subTest(machine=machine), _zone(machine), \
                    self._settings("Europe/Berlin", "%H:%M:%S"):
                with self.assertRaises(ValueError):
                    local_time(self.BARE)
                with self.assertRaises(ValueError):
                    local_time(self.BARE, "%H:%M")

    def test_a_check_type_that_hands_it_one_is_an_error_on_its_node(self):
        # a type writes a time into a line through this function: where it hands
        # it a time without a zone its run is an ERROR, and the node says what
        # was refused
        bare = self.BARE

        class _WritesABareTime(_FakeCheck):
            def grade(self, measurements: Sequence[Measurement],
                      now: datetime) -> CheckResult:
                return CheckResult(StatusCode.OK,
                                   [f"the lease was renewed at {local_time(bare)}"])

        tree = StatusTree()
        with self._settings("Europe/Berlin", "%Y-%m-%d %H:%M:%S"), \
                self.assertLogs(level="ERROR"):
            Engine([_WritesABareTime(path="/lease")], tree).run_once()
        node = tree.snapshot("/lease")
        assert node is not None
        self.assertEqual(node.own_code, StatusCode.ERROR)
        self.assertIn("check error", node.reason[0])
        self.assertIn("is a time without a zone, and no instant", node.reason[0])


class FormatToleranceTests(unittest.TestCase):
    """A freshness tolerance is an interval and is written like one — the rounding
    is the whole of what this adds over `format_duration` (ADR-0081)."""

    def test_a_derived_tolerance_is_rounded_to_an_interval(self):
        # `frequency + max(frequency, 30s)` arrives as a float, and the raw filter
        # would spell it `31.0s`.
        self.assertEqual(format_tolerance(31.0), "31s")
        self.assertEqual(format_tolerance(120.4), "2m")

    def test_a_stated_tolerance_keeps_the_units_it_was_written_in(self):
        self.assertEqual(format_tolerance(3600), "1h")
        self.assertEqual(format_tolerance(90), "90s")

    def test_nothing_stated_is_the_em_dash_like_every_other_interval(self):
        self.assertEqual(format_tolerance(None), "—")
        self.assertEqual(format_tolerance(0), "—")


if __name__ == "__main__":
    unittest.main()
