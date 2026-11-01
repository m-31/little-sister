"""The schedule's text is standard, and this proves it: every text the subset writes
here is read by ``recurring-ical-events`` (over ``icalendar``), and the windows it finds
are the ones :mod:`little_sister.schedule` works out, both clock-change nights of 2026
and of 2027 included (ADR-0150).

``recurring-ical-events`` is a dependency of the dev group alone, never of the library —
it is LGPL-3.0-or-later and brings three dependencies of its own — so the library's
windows stay its own implementation on ``zoneinfo``, and this file is the check that it
reads its own text as any calendar does. A difference is either a fix there, or a case
the record names (ADR-0150) — and there is one: ``recurring-ical-events`` ends a window
of hours its length after the wall time its start is written as, on the wall clock, as
Python adds a ``timedelta`` to an aware time, so a window of hours that crosses a clock
change ends an hour off there — or, from a start the night skips, before it begins.
RFC 5545 makes hours exact (section 3.3.6), and so does the walk-through's decision 3:
*22:00, eight hours* ends at 07:00 the night the clock springs forward and at 05:00 the
night it falls back. Where the windows start the two agree, a start the night skips
after the jump and one it repeats at its first pass (RFC 5545 section 3.3.5); the
comparison holds the calendar to that one difference in their ends, and to no other.
"""
from __future__ import annotations

from datetime import UTC, datetime
from unittest import TestCase, skipIf
from zoneinfo import ZoneInfo

from little_sister.schedule import Schedule

try:
    import icalendar
    import recurring_ical_events
except ImportError:  # pragma: no cover — the dev group carries both
    icalendar = recurring_ical_events = None

#: Each schedule the subset writes that the comparison reads, by what it is.
TEXTS: dict[str, str] = {
    "eight hours nightly, across both nights of 2026": (
        "DTSTART;TZID=Europe/Berlin:20260325T220000\nDURATION:PT8H\n"
        "RRULE:FREQ=DAILY;UNTIL=20261030T000000Z"),
    "eight hours nightly, across both nights of 2027": (
        "DTSTART;TZID=Europe/Berlin:20270324T220000\nDURATION:PT8H\n"
        "RRULE:FREQ=DAILY;UNTIL=20271104T000000Z"),
    "a day every other day, the short and the long Sunday": (
        "DTSTART;TZID=Europe/Berlin:20260327T000000\nDURATION:P1D\n"
        "RRULE:FREQ=DAILY;INTERVAL=2;UNTIL=20261101T000000Z"),
    "an hour at 01:30, both nights": (
        "DTSTART;TZID=Europe/Berlin:20260326T013000\nDURATION:PT1H\n"
        "RRULE:FREQ=DAILY;UNTIL=20261028T000000Z"),
    "half an hour at 02:30, the night that skips it and the night that repeats it": (
        "DTSTART;TZID=Europe/Berlin:20260326T023000\nDURATION:PT30M\n"
        "RRULE:FREQ=DAILY;UNTIL=20261028T000000Z"),
    "the weekend, two hours in the morning": (
        "DTSTART;TZID=Europe/Berlin:20261003T090000\nDURATION:PT2H\n"
        "RRULE:FREQ=WEEKLY;BYDAY=SA,SU;UNTIL=20270403T225959Z"),
    "every second Thursday": (
        "DTSTART;TZID=Europe/Berlin:20261105T220000\nDURATION:PT6H\n"
        "RRULE:FREQ=WEEKLY;INTERVAL=2;BYDAY=TH;UNTIL=20271104T225959Z"),
    "the thirty-first of a month": (
        "DTSTART;TZID=Europe/Berlin:20261031T220000\nDURATION:PT8H\n"
        "RRULE:FREQ=MONTHLY;BYMONTHDAY=31;UNTIL=20271031T225959Z"),
    "the last day of a month": (
        "DTSTART;TZID=Europe/Berlin:20261130T230000\nDURATION:PT4H\n"
        "RRULE:FREQ=MONTHLY;BYMONTHDAY=-1;UNTIL=20271130T225959Z"),
    "the last Sunday of a month, the nights the clock changes among them": (
        "DTSTART;TZID=Europe/Berlin:20261129T010000\nDURATION:PT3H\n"
        "RRULE:FREQ=MONTHLY;BYDAY=-1SU;UNTIL=20271128T225959Z"),
    "the second Tuesday, every other month": (
        "DTSTART;TZID=Europe/Berlin:20261110T220000\nDURATION:PT8H\n"
        "RRULE:FREQ=MONTHLY;INTERVAL=2;BYDAY=2TU;UNTIL=20271109T225959Z"),
    "starts and intervals added, starts left out": (
        "DTSTART;TZID=Europe/Berlin:20261107T220000\nDURATION:PT8H\n"
        "RRULE:FREQ=WEEKLY;BYDAY=SA;UNTIL=20270130T225959Z\n"
        "RDATE;TZID=Europe/Berlin:20261224T100000,20261231T100000\n"
        "RDATE;VALUE=PERIOD:20261124T090000Z/20261124T110000Z\n"
        "EXDATE;TZID=Europe/Berlin:20261226T220000,20270102T220000"),
    "one window": (
        "DTSTART;TZID=Europe/Berlin:20261025T013000\nDTEND:20261025T053000Z"),
}

_RANGE = (datetime(2026, 1, 1, tzinfo=UTC), datetime(2029, 1, 1, tzinfo=UTC))


def calendar_of(text: str) -> str:
    """``text`` as one event of a calendar, which any calendar reads."""
    return "\r\n".join(["BEGIN:VCALENDAR", "VERSION:2.0",
                        "PRODID:-//little-sister//schedule test//EN", "BEGIN:VEVENT",
                        "UID:schedule@little-sister", "DTSTAMP:20261031T000000Z",
                        *text.split("\n"), "END:VEVENT", "END:VCALENDAR", ""])


def as_read_by_a_calendar(text: str) -> list[tuple[datetime, datetime]]:
    """The windows ``recurring-ical-events`` finds in ``text``, as instants in UTC."""
    calendar = icalendar.Calendar.from_ical(calendar_of(text))
    found = recurring_ical_events.of(calendar).between(*_RANGE)
    return sorted((event["DTSTART"].dt.astimezone(UTC),
                   event["DTEND"].dt.astimezone(UTC)) for event in found)


def by_the_wall_clock(text: str, start: datetime, end: datetime) -> datetime:
    """Where ``recurring-ical-events`` ends a window of ``text`` that the schedule ends
    at ``end``: a window of hours — a rule's, an interval's or the one window's — it
    ends its length after the wall time its start is written as, on the wall clock, as
    Python adds a ``timedelta`` to an aware time; a window of days where the schedule
    does. Across a clock change the two part, which the module's docstring names."""
    schedule = Schedule.parse(text)
    if schedule.length is not None and schedule.length.days:
        return end
    zone = ZoneInfo(schedule.zone)
    shown = start.astimezone(zone)
    written = datetime.combine(shown.date(), schedule.start.time())
    if written.replace(tzinfo=zone).astimezone(UTC) != start:
        written = shown.replace(tzinfo=None)
    return (written + (end - start)).replace(tzinfo=zone).astimezone(UTC)


def as_worked_out_here(text: str) -> list[tuple[datetime, datetime]]:
    """The windows :mod:`little_sister.schedule` works out of ``text``, none joined:
    every text here keeps its windows apart."""
    windows = Schedule.parse(text).windows()
    assert all(len(window.starts) == 1 for window in windows), "windows that join"
    return [(window.start, window.end) for window in windows]


@skipIf(recurring_ical_events is None, "recurring-ical-events is the dev group's")
class StandardTextTests(TestCase):
    """Every text, read here and by a calendar, makes the same windows."""

    def test_a_calendar_finds_the_windows_worked_out_here(self):
        for what, text in TEXTS.items():
            with self.subTest(what):
                self.assertEqual(Schedule.parse(text).text(), text)
                ours, theirs = as_worked_out_here(text), as_read_by_a_calendar(text)
                self.assertTrue(ours)
                self.assertEqual(theirs, [
                    (start, by_the_wall_clock(text, start, end))
                    for start, end in ours])

    def test_the_one_difference_is_met_where_it_is_named(self):
        # the nights the hours cross: the calendar is an hour off, both ways
        crossing = {what: sum(1 for start, end in as_worked_out_here(text)
                              if by_the_wall_clock(text, start, end) != end)
                    for what, text in TEXTS.items()}
        self.assertEqual(crossing["eight hours nightly, across both nights of 2026"], 2)
        self.assertEqual(crossing["one window"], 1)
        days = "a day every other day, the short and the long Sunday"
        self.assertEqual(crossing[days], 0)
