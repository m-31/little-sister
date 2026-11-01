"""A maintenance entry's schedule: the RFC 5545 subset and its windows (ADR-0150).

The text is read and written in the subset and nothing else; each window is worked out
from its own date in the entry's zone, a start a night skips landing after the jump and
one it repeats taking its first pass, days following the calendar and hours real time;
the holiday list leaves out the rule's windows on its days and in the years it is not
complete for; a window changed alone ends where it was changed to; windows that overlap
or touch are one. Both clock-change nights of 2026 and of 2027 in Europe/Berlin are
crossed. Its sentence, the one every surface says it in, is written once here, its
instants as the page writes them; and the years a list must state are its rule's.
"""
from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from unittest import TestCase
from zoneinfo import ZoneInfo

from little_sister.schedule import (
    DAILY,
    MONTHLY,
    WEEKLY,
    Length,
    Rule,
    Schedule,
    Window,
    first_start,
    last_end,
    next_after,
    open_at,
    sentence,
)

BERLIN = ZoneInfo("Europe/Berlin")


def utc(*parts: int) -> datetime:
    return datetime(*parts, tzinfo=UTC)


def wall(*parts: int) -> datetime:
    """A wall time, with no zone: what the text writes beside its TZID."""
    return datetime(*parts)  # noqa: DTZ001 — a wall time, read in the schedule's zone


def local(*parts: int) -> datetime:
    """A wall time in Berlin, as the instant it is (its first pass where it repeats)."""
    return datetime(*parts, tzinfo=BERLIN).astimezone(UTC)


def series(rule: str, start: str = "20261107T220000", length: str = "PT8H",
           *more: str) -> Schedule:
    return Schedule.parse("\n".join([f"DTSTART;TZID=Europe/Berlin:{start}",
                                     f"DURATION:{length}", f"RRULE:{rule}", *more]))


def starts(schedule: Schedule, **given: object) -> list[datetime]:
    return [window.start for window in schedule.windows(**given)]  # type: ignore[arg-type]


class _Off:
    """A holiday list for a test: the days it names, the years it is complete for."""

    def __init__(self, days: dict[date, str], complete: set[int]) -> None:
        self.days, self.complete = days, complete

    def covers(self, year: int) -> bool:
        return year in self.complete

    def holiday(self, day: date) -> str:
        return self.days.get(day, "")


class TextTests(TestCase):
    """The subset, read and written."""

    def test_a_one_off_is_its_start_in_the_zone_and_its_end_in_utc(self):
        made = Schedule.one_off(utc(2026, 10, 31, 21, 15, 7, 500_000),
                                utc(2026, 11, 1, 5, 15, 7, 900_000), "Europe/Berlin")
        self.assertEqual(made.text(), "DTSTART;TZID=Europe/Berlin:20261031T221507\n"
                                      "DTEND:20261101T051507Z")
        # the end is kept exactly, as a pin's is, and its text says it to the second
        self.assertEqual(made.end, utc(2026, 11, 1, 5, 15, 7, 900_000))
        read = Schedule.parse(made.text())
        self.assertEqual(read.text(), made.text())
        self.assertEqual(read.windows(), (Window(utc(2026, 10, 31, 21, 15, 7),
                                                 utc(2026, 11, 1, 5, 15, 7),
                                                 (utc(2026, 10, 31, 21, 15, 7),)),))

    def test_a_series_reads_back_as_it_was_written(self):
        text = "\n".join([
            "DTSTART;TZID=Europe/Berlin:20261107T220000",
            "DURATION:PT8H",
            "RRULE:FREQ=WEEKLY;INTERVAL=2;BYDAY=TH,SA;UNTIL=20271030T215959Z",
            "RDATE;TZID=Europe/Berlin:20261224T220000",
            "RDATE;VALUE=PERIOD:20261124T090000Z/20261124T110000Z",
            "EXDATE;TZID=Europe/Berlin:20261121T220000"])
        read = Schedule.parse(text)
        self.assertEqual(read.text(), text)
        self.assertEqual(read.rule, Rule(WEEKLY, 2, utc(2027, 10, 30, 21, 59, 59),
                                         weekdays=(3, 5)))
        self.assertEqual(read.length, Length(span=timedelta(hours=8)))
        self.assertEqual(read.extra, (wall(2026, 12, 24, 22),))
        self.assertEqual(read.intervals,
                         ((utc(2026, 11, 24, 9), utc(2026, 11, 24, 11)),))
        self.assertEqual(read.left_out, (wall(2026, 11, 21, 22),))

    def test_every_rule_the_subset_takes_reads_back(self):
        for rule in ("FREQ=DAILY;UNTIL=20270130T225959Z",
                     "FREQ=DAILY;INTERVAL=3;UNTIL=20270130T225959Z",
                     "FREQ=WEEKLY;UNTIL=20270130T225959Z",
                     "FREQ=MONTHLY;BYMONTHDAY=7;UNTIL=20270130T225959Z",
                     "FREQ=MONTHLY;BYMONTHDAY=-24;UNTIL=20270130T225959Z",
                     "FREQ=MONTHLY;BYDAY=1SA;UNTIL=20270130T225959Z",
                     "FREQ=MONTHLY;INTERVAL=2;UNTIL=20270130T225959Z"):
            with self.subTest(rule=rule):
                read = series(rule)
                self.assertEqual(read.text().split("\n")[2], f"RRULE:{rule}")
        self.assertEqual(series("FREQ=DAILY;UNTIL=20270130T225959Z", "20261107T000000",
                                "P1D").length, Length(days=1))
        length = series("FREQ=DAILY;UNTIL=20270130T225959Z", "20261107T000000",
                        "PT1H30M").length
        self.assertEqual(length.text() if length else "", "PT1H30M")

    def test_what_the_subset_does_not_take_is_refused(self):
        start = "DTSTART;TZID=Europe/Berlin:20261107T220000"
        for text, said in (
                ("DURATION:PT8H", "without DTSTART"),
                ("DTSTART:20261107T220000\nDURATION:PT8H", "names no zone"),
                ("DTSTART;TZID=Mars/Olympus:20261107T220000\nDURATION:PT8H",
                 "is none"),
                ("DTSTART;TZID=Europe/Berlin:20261107T220000Z\nDURATION:PT8H",
                 "no local date and time"),
                ("DTSTART;VALUE=DATE;TZID=Europe/Berlin:20261107\nDURATION:P1D",
                 "VALUE"),
                (f"{start}\nDTEND:20261108T060000Z\nDURATION:PT8H",
                 "DTEND or DURATION"),
                (start, "DTEND or DURATION"),
                (f"{start}\nDTEND:20261108T060000Z\n"
                 f"RRULE:FREQ=DAILY;UNTIL=20261130T000000Z", "length from DURATION"),
                (f"{start}\nDURATION:PT8H\nRRULE:FREQ=DAILY", "without UNTIL"),
                (f"{start}\nDURATION:PT8H\nRRULE:FREQ=DAILY;COUNT=3", "without UNTIL"),
                (f"{start}\nDURATION:PT8H\nRRULE:FREQ=DAILY;COUNT=3;"
                 f"UNTIL=20261130T000000Z", "COUNT"),
                (f"{start}\nDURATION:PT8H\nRRULE:FREQ=YEARLY;UNTIL=20261130T000000Z",
                 "not DAILY, WEEKLY or MONTHLY"),
                (f"{start}\nDURATION:PT8H\nRRULE:FREQ=WEEKLY;WKST=SU;"
                 f"UNTIL=20261130T000000Z", "WKST=MO"),
                (f"{start}\nDURATION:PT8H\nRRULE:FREQ=DAILY;INTERVAL=0;"
                 f"UNTIL=20261130T000000Z", "no count"),
                (f"{start}\nDURATION:PT8H\nRRULE:FREQ=DAILY;BYDAY=SA;"
                 f"UNTIL=20261130T000000Z", "picks no days"),
                (f"{start}\nDURATION:PT8H\nRRULE:FREQ=MONTHLY;BYDAY=SA;"
                 f"UNTIL=20261130T000000Z", "the first to the fourth"),
                (f"{start}\nDURATION:PT8H\nRRULE:FREQ=MONTHLY;BYDAY=5SA;"
                 f"UNTIL=20261130T000000Z", "the first to the fourth"),
                (f"{start}\nDURATION:PT8H\nRRULE:FREQ=MONTHLY;BYMONTHDAY=32;"
                 f"UNTIL=20261130T000000Z", "no day"),
                (f"{start}\nDURATION:PT8H\nRRULE:FREQ=WEEKLY;BYSETPOS=1;"
                 f"UNTIL=20261130T000000Z", "BYSETPOS"),
                (f"{start}\nDURATION:PT8H\nRRULE:FREQ=DAILY;UNTIL=20261130T000000",
                 "no time in UTC"),
                (f"{start}\nDURATION:PT8H\nRRULE:FREQ=DAILY;UNTIL=20261101T000000Z",
                 "before its first start"),
                (f"{start}\nDURATION:PT8H\nRRULE:FREQ=WEEKLY;BYDAY=FR;"
                 f"UNTIL=20261130T000000Z", "a day its rule does not pick"),
                (f"{start}\nDURATION:PT8H\nRDATE;TZID=Europe/London:20261124T090000",
                 "another zone"),
                (f"{start}\nDURATION:PT8H\nEXDATE:20261124T090000", "another zone"),
                (f"{start}\nDTEND:20261108T060000Z\nRDATE;TZID=Europe/Berlin:"
                 f"20261124T090000", "RDATE adds to a series"),
                (f"{start}\nDURATION:PT8H\nSUMMARY:backup", "SUMMARY"),
                (f"{start}\nDTEND:20261107T200000Z", "not after its start"),
                (f"{start}\nDURATION:P0D", "no length"),
                (f"{start}\nDURATION:P1DT2H", "neither days nor hours"),
                (f"{start}\nDURATION:PT8H\nnonsense", "no content line"),
                (f"{start}\n{start}\nDURATION:PT8H", "DTSTART twice")):
            with self.subTest(said=said, text=text):
                with self.assertRaises(ValueError) as caught:
                    Schedule.parse(text)
                self.assertIn(said, str(caught.exception))

    def test_one_window_is_bounded_where_it_is_set_not_here(self):
        # as a pin's end is (ADR-0014 decision 13): the form refuses one past a year
        far = Schedule.parse("DTSTART;TZID=Europe/Berlin:20261107T220000\n"
                             "DTEND:29990101T000000Z")
        self.assertEqual(far.end, utc(2999, 1, 1))

    def test_a_schedule_runs_at_most_a_year_from_its_first_start(self):
        # the last start may fall on the same day a year on, to its last second
        self.assertEqual(series("FREQ=DAILY;UNTIL=20271107T225959Z").rule.until,
                         utc(2027, 11, 7, 22, 59, 59))
        with self.assertRaisesRegex(ValueError, "past a year"):
            series("FREQ=DAILY;UNTIL=20271107T230000Z")
        with self.assertRaisesRegex(ValueError, "past a year"):
            series("FREQ=DAILY;UNTIL=20261130T000000Z", "20261107T220000", "PT8H",
                   "RDATE;TZID=Europe/Berlin:20271108T220000")


class RuleTests(TestCase):
    """Which days a rule picks, each from its own count."""

    def test_every_second_thursday_counts_weeks_from_the_first(self):
        read = series("FREQ=WEEKLY;INTERVAL=2;BYDAY=TH;UNTIL=20261231T225959Z",
                      "20261105T220000")
        self.assertEqual([each.astimezone(BERLIN).date() for each in starts(read)],
                         [date(2026, 11, 5), date(2026, 11, 19), date(2026, 12, 3),
                          date(2026, 12, 17), date(2026, 12, 31)])

    def test_the_weekend_is_saturday_and_sunday(self):
        read = series("FREQ=WEEKLY;BYDAY=SA,SU;UNTIL=20261115T225959Z",
                      "20261107T090000")
        self.assertEqual([each.astimezone(BERLIN).date() for each in starts(read)],
                         [date(2026, 11, 7), date(2026, 11, 8), date(2026, 11, 14),
                          date(2026, 11, 15)])

    def test_a_month_without_the_day_is_skipped(self):
        read = series("FREQ=MONTHLY;BYMONTHDAY=31;UNTIL=20270331T225959Z",
                      "20261031T220000")
        self.assertEqual([each.astimezone(BERLIN).date() for each in starts(read)],
                         [date(2026, 10, 31), date(2026, 12, 31), date(2027, 1, 31),
                          date(2027, 3, 31)])

    def test_the_last_day_and_the_last_and_second_weekday_of_a_month(self):
        last = series("FREQ=MONTHLY;BYMONTHDAY=-1;UNTIL=20270228T225959Z",
                      "20261130T220000")
        self.assertEqual([each.astimezone(BERLIN).date() for each in starts(last)],
                         [date(2026, 11, 30), date(2026, 12, 31), date(2027, 1, 31),
                          date(2027, 2, 28)])
        sunday = series("FREQ=MONTHLY;BYDAY=-1SU;UNTIL=20270131T225959Z",
                        "20261129T220000")
        self.assertEqual([each.astimezone(BERLIN).date() for each in starts(sunday)],
                         [date(2026, 11, 29), date(2026, 12, 27), date(2027, 1, 31)])
        tuesday = series("FREQ=MONTHLY;BYDAY=2TU;UNTIL=20270131T225959Z",
                         "20261110T220000")
        self.assertEqual([each.astimezone(BERLIN).date() for each in starts(tuesday)],
                         [date(2026, 11, 10), date(2026, 12, 8), date(2027, 1, 12)])

    def test_until_is_the_last_start_it_allows(self):
        read = series("FREQ=DAILY;UNTIL=20261109T210000Z")
        self.assertEqual(starts(read)[-1], local(2026, 11, 9, 22))
        read = series("FREQ=DAILY;UNTIL=20261109T205959Z")
        self.assertEqual(starts(read)[-1], local(2026, 11, 8, 22))


class ClockChangeTests(TestCase):
    """Both nights the clock changes, in 2026 and in 2027: each window from its own
    date, hours real time and days the calendar's."""

    def test_eight_hours_are_eight_hours_whatever_the_night(self):
        for spring, autumn in (((2026, 3, 28), (2026, 10, 24)),
                               ((2027, 3, 27), (2027, 10, 30))):
            for day, ends_at in ((spring, 7), (autumn, 5)):
                with self.subTest(night=day):
                    first = date(*day) - timedelta(days=1)
                    until = first + timedelta(days=3)
                    read = series(f"FREQ=DAILY;UNTIL={until:%Y%m%d}T000000Z",
                                  f"{first:%Y%m%d}T220000")
                    window = read.windows()[1]
                    self.assertEqual(window.start, local(*day, 22))
                    self.assertEqual(window.end - window.start, timedelta(hours=8))
                    self.assertEqual(window.end.astimezone(BERLIN).hour, ends_at)

    def test_each_start_keeps_its_time_of_day_across_the_change(self):
        # never a day added as 24 hours to the last (ZBX-20162)
        read = series("FREQ=DAILY;UNTIL=20261028T000000Z", "20261023T220000")
        self.assertEqual({each.astimezone(BERLIN).strftime("%H:%M")
                          for each in starts(read)}, {"22:00"})
        # the night of 24 to 25 October gives the clock its hour back
        self.assertEqual(starts(read)[2] - starts(read)[1], timedelta(hours=25))

    def test_a_day_is_the_calendars_day_on_the_short_and_the_long_sunday(self):
        for sunday, hours in (((2026, 3, 29), 23), ((2026, 10, 25), 25),
                              ((2027, 3, 28), 23), ((2027, 10, 31), 25)):
            with self.subTest(sunday=sunday):
                first = date(*sunday)
                read = Schedule.parse("\n".join([
                    f"DTSTART;TZID=Europe/Berlin:{first:%Y%m%d}T000000",
                    "DURATION:P1D",
                    f"RRULE:FREQ=WEEKLY;UNTIL={first:%Y%m%d}T235959Z"]))
                window = read.windows()[0]
                self.assertEqual(window.end - window.start, timedelta(hours=hours))
                after = first + timedelta(days=1)
                self.assertEqual(window.end, local(after.year, after.month, after.day))

    def test_a_start_the_night_skips_lands_after_the_jump(self):
        read = series("FREQ=DAILY;UNTIL=20260330T000000Z", "20260327T023000", "PT1H")
        on_the_night = read.windows()[2]
        self.assertEqual(on_the_night.start, utc(2026, 3, 29, 1, 30))
        self.assertEqual(on_the_night.start.astimezone(BERLIN).strftime("%H:%M"),
                         "03:30")

    def test_a_start_the_night_repeats_takes_its_first_pass(self):
        read = series("FREQ=DAILY;UNTIL=20261027T000000Z", "20261024T023000", "PT1H")
        on_the_night = read.windows()[1]
        self.assertEqual(on_the_night.start, utc(2026, 10, 25, 0, 30))
        self.assertEqual(on_the_night.start.astimezone(BERLIN).utcoffset(),
                         timedelta(hours=2))


class AddedAndLeftOutTests(TestCase):
    """Starts and intervals added, starts left out, the holidays, a window changed."""

    RULE = "FREQ=DAILY;UNTIL=20270103T000000Z"

    def test_a_start_left_out_is_no_window(self):
        read = series(self.RULE, "20261230T220000", "PT8H",
                      "EXDATE;TZID=Europe/Berlin:20261231T220000")
        self.assertNotIn(local(2026, 12, 31, 22), starts(read))
        self.assertIn(local(2027, 1, 1, 22), starts(read))

    def test_an_added_start_takes_the_length_and_an_interval_its_own(self):
        read = series("FREQ=WEEKLY;UNTIL=20261121T225959Z", "20261107T220000", "PT8H",
                      "RDATE;TZID=Europe/Berlin:20261111T220000",
                      "RDATE;VALUE=PERIOD:20261112T090000Z/20261112T093000Z")
        windows = read.windows()
        self.assertEqual([(w.start, w.end - w.start) for w in windows], [
            (local(2026, 11, 7, 22), timedelta(hours=8)),
            (local(2026, 11, 11, 22), timedelta(hours=8)),
            (utc(2026, 11, 12, 9), timedelta(minutes=30)),
            (local(2026, 11, 14, 22), timedelta(hours=8)),
            (local(2026, 11, 21, 22), timedelta(hours=8))])

    def test_the_holidays_leave_out_the_rules_windows_on_their_days(self):
        off = _Off({date(2026, 12, 31): "New Year's Eve"}, {2026})
        read = series("FREQ=DAILY;UNTIL=20261231T225959Z", "20261229T220000", "PT1H",
                      "RDATE;TZID=Europe/Berlin:20261231T100000")
        self.assertEqual(starts(read, days_off=off), [
            local(2026, 12, 29, 22), local(2026, 12, 30, 22),
            # a start added by hand stands on a listed day
            local(2026, 12, 31, 10)])

    def test_a_year_the_list_is_not_complete_for_leaves_out_its_windows(self):
        off = _Off({}, {2026})
        read = series(self.RULE, "20261230T220000", "PT1H")
        self.assertEqual(starts(read, days_off=off),
                         [local(2026, 12, 30, 22), local(2026, 12, 31, 22)])

    def test_a_window_belongs_to_the_day_it_starts_on(self):
        off = _Off({date(2026, 12, 25): "Christmas Day"}, {2026})
        read = series("FREQ=DAILY;UNTIL=20261226T225959Z", "20261224T220000", "PT8H")
        self.assertEqual(starts(read, days_off=off),
                         [local(2026, 12, 24, 22), local(2026, 12, 26, 22)])

    def test_a_window_changed_alone_ends_where_it_was_changed_to(self):
        read = series(self.RULE, "20261230T220000", "PT8H")
        first = local(2026, 12, 30, 22)
        longer = read.windows(changed={first: first + timedelta(hours=9)})
        self.assertEqual(longer[0].end, first + timedelta(hours=9))
        ended = read.windows(changed={first: first})
        self.assertNotIn(first, [window.start for window in ended])

    def test_windows_that_overlap_or_touch_are_one(self):
        read = series(self.RULE, "20261230T220000", "PT8H")
        first, second = local(2026, 12, 30, 22), local(2026, 12, 31, 22)
        joined = read.windows(changed={first: second + timedelta(hours=1)})
        self.assertEqual(joined[0], Window(first, second + timedelta(hours=8),
                                           (first, second)))
        days = series("FREQ=DAILY;UNTIL=20261202T225959Z", "20261130T000000", "P1D")
        self.assertEqual(len(days.windows()), 1)
        self.assertEqual(days.windows()[0].starts[-1], local(2026, 12, 2))


class QueryTests(TestCase):
    """What a reader asks of the windows."""

    def test_open_next_and_last(self):
        read = series("FREQ=DAILY;UNTIL=20261102T225959Z", "20261031T220000", "PT8H")
        windows = read.windows()
        self.assertEqual(open_at(windows, local(2026, 11, 1, 3)).start,
                         local(2026, 10, 31, 22))
        self.assertIsNone(open_at(windows, local(2026, 11, 1, 12)))
        self.assertEqual(open_at(windows, local(2026, 10, 31, 22)).start,
                         local(2026, 10, 31, 22))
        self.assertIsNone(open_at(windows, local(2026, 11, 1, 6)))
        self.assertEqual(next_after(windows, local(2026, 11, 1, 12)).start,
                         local(2026, 11, 1, 22))
        self.assertIsNone(next_after(windows, local(2026, 11, 2, 23)))
        self.assertEqual(last_end(windows), local(2026, 11, 3, 6))
        self.assertIsNone(last_end(()))

    def test_frequencies_are_the_three(self):
        self.assertEqual((DAILY, WEEKLY, MONTHLY), ("DAILY", "WEEKLY", "MONTHLY"))


def page(moment: datetime) -> str:
    """An instant as a page in Berlin with the default time format writes it."""
    return moment.astimezone(BERLIN).strftime("%Y-%m-%d %H:%M:%S")


def said(schedule: Schedule, *, zone: str = "Europe/Berlin", not_on: str = "") -> str:
    windows = schedule.windows()
    return sentence(schedule, until=windows[-1].end, at=page, zone=zone,
                    not_on=not_on)


class SentenceTests(TestCase):
    """The schedule in one sentence (ADR-0150), every shape the subset takes: its
    instants through the writer the page writes every instant with, never a date of
    its own beside them, and the entry's zone named only where it is not the page's."""

    def test_a_one_off_is_once_from_until(self):
        once = Schedule.one_off(local(2026, 11, 7, 22), local(2026, 11, 8, 6),
                                "Europe/Berlin")
        self.assertEqual(said(once), "Once, from 2026-11-07 22:00:00 until "
                                     "2026-11-08 06:00:00")

    def test_until_is_the_end_it_is_handed(self):
        # the entry's end — a window changed alone moves it — and never the rule's
        once = Schedule.one_off(local(2026, 11, 7, 22), local(2026, 11, 8, 6),
                                "Europe/Berlin")
        self.assertEqual(
            sentence(once, until=local(2026, 11, 8, 7, 30), at=page,
                     zone="Europe/Berlin"),
            "Once, from 2026-11-07 22:00:00 until 2026-11-08 07:30:00")

    def test_a_week_s_day(self):
        weekly = series("FREQ=WEEKLY;BYDAY=SA;UNTIL=20271030T215959Z")
        self.assertEqual(said(weekly, not_on="holidays in Bavaria"),
                         "Every Saturday from 22:00 for 8 hours, until "
                         "2027-10-31 05:00:00, not on holidays in Bavaria")

    def test_weeks_apart_and_several_days(self):
        self.assertEqual(
            said(series("FREQ=WEEKLY;INTERVAL=2;BYDAY=TH;UNTIL=20261231T225959Z",
                        "20261105T220000", "PT6H")),
            "Every second Thursday from 22:00 for 6 hours, until 2027-01-01 04:00:00")
        self.assertEqual(
            said(series("FREQ=WEEKLY;BYDAY=MO,TU,WE,TH,FR;UNTIL=20261231T225959Z",
                        "20261102T220000", "PT1H30M")),
            "Every working day from 22:00 for 1 hour 30 minutes, until "
            "2026-12-31 23:30:00")
        self.assertEqual(
            said(series("FREQ=WEEKLY;INTERVAL=3;BYDAY=SA,SU;UNTIL=20261231T225959Z")),
            "Every third week on Saturday and Sunday from 22:00 for 8 hours, until "
            "2026-12-21 06:00:00")
        self.assertEqual(
            said(series("FREQ=WEEKLY;BYDAY=TU,TH,SA;UNTIL=20261231T225959Z",
                        "20261107T220000")),
            "Every Tuesday, Thursday and Saturday from 22:00 for 8 hours, until "
            "2027-01-01 06:00:00")

    def test_days_and_months(self):
        self.assertEqual(
            said(series("FREQ=DAILY;INTERVAL=2;UNTIL=20261231T225959Z",
                        "20261031T220000", "P1D")),
            "Every second day from 22:00 for 1 day, until 2026-12-31 22:00:00")
        self.assertEqual(
            said(series("FREQ=DAILY;UNTIL=20261102T225959Z", "20261031T220000",
                        "PT3M")),
            "Every day from 22:00 for 3 minutes, until 2026-11-02 22:03:00")
        self.assertEqual(
            said(series("FREQ=MONTHLY;INTERVAL=2;BYDAY=2TU;UNTIL=20271109T225959Z",
                        "20261110T220000")),
            "Every second month on its second Tuesday from 22:00 for 8 hours, until "
            "2027-11-10 06:00:00")
        self.assertEqual(
            said(series("FREQ=MONTHLY;BYMONTHDAY=-1;UNTIL=20270131T225959Z",
                        "20261130T230000", "PT4H")),
            "Every month on its last day from 23:00 for 4 hours, until "
            "2027-02-01 03:00:00")
        self.assertEqual(
            said(series("FREQ=MONTHLY;BYMONTHDAY=-2;UNTIL=20270131T225959Z",
                        "20261129T230000", "PT4H")),
            "Every month on its second-to-last day from 23:00 for 4 hours, until "
            "2027-01-31 03:00:00")
        self.assertEqual(
            said(series("FREQ=MONTHLY;BYMONTHDAY=15;UNTIL=20270131T225959Z",
                        "20261115T020000", "PT2H")),
            "Every month on the 15th from 02:00 for 2 hours, until "
            "2027-01-15 04:00:00")
        self.assertEqual(
            said(series("FREQ=MONTHLY;BYDAY=-1FR;UNTIL=20270131T225959Z",
                        "20261127T220000")),
            "Every month on its last Friday from 22:00 for 8 hours, until "
            "2027-01-30 06:00:00")

    def test_what_was_added_and_left_out(self):
        weekly = series("FREQ=WEEKLY;BYDAY=SA;UNTIL=20270130T225959Z",
                        "20261107T220000", "PT8H",
                        "RDATE;TZID=Europe/Berlin:20261224T100000,20261231T100000",
                        "RDATE;VALUE=PERIOD:20261124T090000Z/20261124T110000Z",
                        "EXDATE;TZID=Europe/Berlin:20261226T220000")
        self.assertEqual(said(weekly, not_on="ACME's company holidays"),
                         "Every Saturday from 22:00 for 8 hours, until "
                         "2027-01-31 06:00:00, 3 more windows, 1 left out, not on "
                         "ACME's company holidays")
        one_more = series("FREQ=WEEKLY;BYDAY=SA;UNTIL=20261121T225959Z",
                          "20261107T220000", "PT8H",
                          "RDATE;TZID=Europe/Berlin:20261124T100000")
        self.assertIn(", 1 more window,", said(one_more) + ",")

    def test_a_start_and_a_length_with_no_rule(self):
        alone = Schedule.parse("DTSTART;TZID=Europe/Berlin:20261107T220000\n"
                               "DURATION:PT8H\n"
                               "RDATE;TZID=Europe/Berlin:20261114T220000")
        self.assertEqual(said(alone), "From 2026-11-07 22:00:00 for 8 hours, until "
                                      "2026-11-15 06:00:00, 1 more window")

    def test_the_entry_s_zone_is_named_beside_its_time_of_day_where_it_differs(self):
        weekly = series("FREQ=WEEKLY;BYDAY=SA;UNTIL=20271030T215959Z")
        self.assertEqual(
            said(weekly, zone="America/New_York"),
            "Every Saturday from 22:00 (Europe/Berlin) for 8 hours, until "
            "2027-10-31 05:00:00")
        # a one-off says two instants, each as the page writes it, and no zone
        once = Schedule.one_off(local(2026, 11, 7, 22), local(2026, 11, 8, 6),
                                "Europe/Berlin")
        self.assertNotIn("Europe/Berlin", said(once, zone="America/New_York"))

    def test_seconds_where_the_start_has_them(self):
        odd = series("FREQ=DAILY;UNTIL=20261102T225959Z", "20261031T221530", "PT1H")
        self.assertTrue(said(odd).startswith("Every day from 22:15:30 for 1 hour"))

    def test_the_instants_are_the_writer_s(self):
        weekly = series("FREQ=WEEKLY;BYDAY=SA;UNTIL=20271030T215959Z")
        written = sentence(weekly, until=utc(2027, 10, 31, 5), zone="Europe/Berlin",
                           at=lambda moment: f"<{moment.isoformat()}>")
        self.assertTrue(written.endswith("until <2027-10-31T05:00:00+00:00>"))


class YearsTests(TestCase):
    """The years a holiday list must state for a rule's windows (ADR-0149 decision
    3): each year a window of the rule starts in, by its day in the entry's zone, with
    its last start; and when a year begins there."""

    def test_each_year_and_its_last_start(self):
        weekly = series("FREQ=WEEKLY;BYDAY=SA;UNTIL=20270130T225959Z")
        self.assertEqual(weekly.rule_years(), {2026: local(2026, 12, 26, 22),
                                               2027: local(2027, 1, 30, 22)})

    def test_a_year_by_the_day_a_window_starts_on(self):
        # 23:30 on New Year's Eve in Berlin is 2026 there, whatever UTC says
        late = series("FREQ=DAILY;UNTIL=20261231T225959Z", "20261230T233000", "PT1H")
        self.assertEqual(set(late.rule_years()), {2026})

    def test_a_start_left_out_or_added_counts_no_year(self):
        weekly = series("FREQ=WEEKLY;BYDAY=SA;UNTIL=20270102T225959Z",
                        "20261226T220000", "PT8H",
                        "EXDATE;TZID=Europe/Berlin:20270102T220000",
                        "RDATE;TZID=Europe/Berlin:20270101T100000")
        self.assertEqual(weekly.rule_years(), {2026: local(2026, 12, 26, 22)})

    def test_none_without_a_rule(self):
        once = Schedule.one_off(local(2026, 11, 7, 22), local(2026, 11, 8, 6),
                                "Europe/Berlin")
        self.assertEqual(once.rule_years(), {})

    def test_when_a_year_begins_and_the_first_start(self):
        weekly = series("FREQ=WEEKLY;BYDAY=SA;UNTIL=20270130T225959Z")
        self.assertEqual(weekly.year_begins(2027), utc(2026, 12, 31, 23))
        self.assertEqual(weekly.starts_at, local(2026, 11, 7, 22))


class LandingFourTests(TestCase):
    """What a series set on the page needs of the subset (ADR-0150, landing 4): an exact
    length to the second, so that a one-off a window joins keeps its typed end; the
    first start a rule picks on or after *Starts*; and a sentence that says only what
    is still ahead, and never a length's seconds."""

    def test_an_exact_length_takes_seconds_and_says_none(self):
        joined = Schedule.parse(
            "DTSTART;TZID=Europe/Berlin:20261103T100000\nDURATION:PT3H22M48S\n"
            "RDATE;VALUE=PERIOD:20261107T210000Z/20261108T050000Z")
        self.assertEqual(joined.length, Length(span=timedelta(hours=3, minutes=22,
                                                              seconds=48)))
        self.assertIn("DURATION:PT3H22M48S", joined.text())
        self.assertEqual(Schedule.parse(joined.text()), joined)
        self.assertEqual(Length(span=timedelta(seconds=45)).text(), "PT45S")
        # the first window's end, as the person typed it, and never its seconds
        self.assertEqual(said(joined), "From 2026-11-03 10:00:00 to 2026-11-03 "
                                       "13:22:48, until 2026-11-08 06:00:00, 1 more "
                                       "window")
        self.assertEqual(Length(span=timedelta(hours=1, seconds=30)).words(), "1 hour")
        rule = series("FREQ=DAILY;UNTIL=20261110T225959Z", "20261107T220000",
                      "PT1M30S")
        self.assertIn("Every day from 22:00 to 22:01:30, until", said(rule))

    def test_the_first_start_is_the_first_day_on_or_after_it_the_rule_picks(self):
        until = utc(2027, 3, 1)
        saturdays = Rule(WEEKLY, 1, until, weekdays=(5,))
        # a Wednesday's 22:00, the Saturday after it
        self.assertEqual(first_start(saturdays, wall(2026, 11, 4, 22), "Europe/Berlin"),
                         wall(2026, 11, 7, 22))
        self.assertEqual(first_start(saturdays, wall(2026, 11, 7, 22), "Europe/Berlin"),
                         wall(2026, 11, 7, 22), "a day it picks is its own")
        first_sunday = Rule(MONTHLY, 1, until, nth=1, weekday=6)
        self.assertEqual(first_start(first_sunday, wall(2026, 11, 4, 3),
                                     "Europe/Berlin"), wall(2026, 12, 6, 3))
        every_other = Rule(DAILY, 2, until)
        self.assertEqual(first_start(every_other, wall(2026, 11, 3, 22),
                                     "Europe/Berlin"), wall(2026, 11, 3, 22))
        self.assertIsNone(first_start(Rule(WEEKLY, 1, utc(2026, 11, 5), weekdays=(5,)),
                                      wall(2026, 11, 4, 22), "Europe/Berlin"),
                          "no Saturday before its Until")
        # what it gives, the text takes: a first start its rule picks
        made = Schedule(zone="Europe/Berlin", start=wall(2026, 11, 7, 22),
                        length=Length(span=timedelta(hours=8)), rule=saturdays)
        made.check()

    def test_the_sentence_says_only_what_is_still_ahead(self):
        weekly = series("FREQ=WEEKLY;BYDAY=SA;UNTIL=20270130T225959Z",
                        "20261107T220000", "PT8H",
                        "RDATE;VALUE=PERIOD:20261108T210000Z/20261108T230000Z,"
                        "20261208T210000Z/20261208T230000Z",
                        "EXDATE;TZID=Europe/Berlin:20261114T220000,"
                        "20261219T220000")
        until = weekly.windows()[-1].end
        self.assertIn("2 more windows, 2 left out",
                      sentence(weekly, until=until, at=page, zone="Europe/Berlin"),
                      "drawn at no moment: everything")
        after = utc(2026, 11, 20)
        self.assertIn(", 1 more window, 1 left out",
                      sentence(weekly, until=until, at=page, zone="Europe/Berlin",
                               after=after))
        # a window open now, added by hand — the window an edit keeps — is not said:
        # its block's first row says it
        self.assertNotIn("more window",
                         sentence(weekly, until=until, at=page, zone="Europe/Berlin",
                                  after=utc(2026, 12, 8, 22)))
        # a schedule without a rule says its first window only while it is ahead
        joined = Schedule.parse(
            "DTSTART;TZID=Europe/Berlin:20261103T100000\nDURATION:PT2H\n"
            "RDATE;VALUE=PERIOD:20261107T210000Z/20261108T050000Z")
        end = joined.windows()[-1].end
        self.assertEqual(sentence(joined, until=end, at=page, zone="Europe/Berlin",
                                  after=utc(2026, 11, 3, 9, 30)),
                         "1 more window, until 2026-11-08 06:00:00")
        self.assertEqual(sentence(joined, until=end, at=page, zone="Europe/Berlin",
                                  after=utc(2026, 11, 3, 8)),
                         "From 2026-11-03 10:00:00 for 2 hours, until 2026-11-08 "
                         "06:00:00, 1 more window")
