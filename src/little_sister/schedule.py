"""A maintenance entry's schedule: a recurrence set in RFC 5545 text, the subset this
library writes and reads, and the one implementation of its windows (ADR-0150).

A schedule is a first start, a length, and at most a rule, extra dates and intervals,
and dates left out — iCalendar's recurrence set, kept as its text, so that a later feed
reads it in any calendar. A one-off window is the same thing with one interval::

    DTSTART;TZID=Europe/Berlin:20261031T221500
    DTEND:20261101T061500Z

and a series a rule with its last date, its length nominal in days or exact in hours::

    DTSTART;TZID=Europe/Berlin:20261107T220000
    DURATION:PT8H
    RRULE:FREQ=WEEKLY;BYDAY=SA;UNTIL=20271030T215959Z
    RDATE;TZID=Europe/Berlin:20261224T220000
    RDATE;VALUE=PERIOD:20261124T090000Z/20261124T110000Z
    EXDATE;TZID=Europe/Berlin:20261226T220000

**The subset, and nothing else.** ``DTSTART`` with a ``TZID``, an IANA name — the
zone written once, the only zone of the text — and either ``DTEND``, for one interval,
or ``DURATION``: ``PnD``, days that follow the calendar, or ``PTnHnMnS``, real time. A
rule is ``FREQ=DAILY``, ``WEEKLY`` or ``MONTHLY``, with ``INTERVAL``; ``BYDAY`` for a
week's days, and for a month one ``BYMONTHDAY`` counted from either end or one weekday
of it, the first to the fourth or the last; and ``UNTIL``, which is required, in UTC,
at most a year after the first start. ``RDATE`` adds a start, with the length, or an
interval of its own (``VALUE=PERIOD``, its two instants in UTC); ``EXDATE`` leaves out
the window that starts at a time it names. Every local time is in the ``TZID`` of
``DTSTART``. A ``DTSTART`` the rule would not produce is refused — RFC 5545 leaves such
a set undefined (section 3.8.5.3) — and so is everything else: ``COUNT``, another
frequency, a property or a part the subset has no use for, a zone that is not one, a
last date past a year. A reader that refuses a schedule fails toward alarming.

**A window** is worked out from its own date, never by adding a period to the last
(ZBX-20162): its local start is the date at the first start's time of day, read as
``zoneinfo`` reads a wall time — a start a night skips lands after the jump, one a night
repeats takes its first pass (RFC 5545 section 3.3.5); its end is that many days later
at the same time of day, or that much real time later. A window belongs to the day it
starts on. The days a holiday list names leave out the rule's windows that start on
them, and a year the list is not complete for leaves out the rule's windows of that
year; a start or an interval added by hand stands whatever the list says. A window
changed alone (``changed``, keyed by its start) ends where it was changed to. Windows
that overlap or touch are one.
"""
from __future__ import annotations

import re
from bisect import bisect_right
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from typing import Protocol
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

#: The frequencies the subset knows.
DAILY, WEEKLY, MONTHLY = "DAILY", "WEEKLY", "MONTHLY"

#: The weekdays as RFC 5545 spells them, Monday first, as the weeks are counted.
WEEKDAYS = ("MO", "TU", "WE", "TH", "FR", "SA", "SU")

#: The longest an interval added to a series may be. One window alone — a one-off — is
#: bounded where it is set, as a pin's end is (ADR-0014 decision 13), and not here.
LONGEST_INTERVAL = timedelta(days=365)

_LOCAL = "%Y%m%dT%H%M%S"
_STAMP = re.compile(r"\d{8}T\d{6}")
_LENGTH = re.compile(r"P(?:(?P<days>\d+)D|T(?:(?P<hours>\d+)H)?(?:(?P<minutes>\d+)M)?"
                     r"(?:(?P<seconds>\d+)S)?)")
_ORDINAL_DAY = re.compile(r"(?P<n>[+-]?\d)?(?P<day>MO|TU|WE|TH|FR|SA|SU)")


class DaysOff(Protocol):
    """What a schedule asks of a holiday list
    (:class:`little_sister.holidays.HolidayList`): whether it is complete for a year,
    and whether it names a day."""

    def covers(self, year: int) -> bool: ...

    def holiday(self, day: date) -> str: ...


@dataclass(frozen=True)
class Length:
    """How long each window of a rule is: ``days`` that follow the calendar, or an exact
    ``span`` of real time — RFC 5545's nominal and exact durations."""

    days: int = 0
    span: timedelta = timedelta(0)

    def text(self) -> str:
        if self.days:
            return f"P{self.days}D"
        hours, rest = divmod(int(self.span.total_seconds()), 3600)
        minutes, seconds = divmod(rest, 60)
        return ("PT" + (f"{hours}H" if hours else "")
                + (f"{minutes}M" if minutes else "")
                + (f"{seconds}S" if seconds else ""))

    def words(self) -> str:
        """The length as a sentence says it: *8 hours*, *1 day*."""
        return _length_said(self)


@dataclass(frozen=True)
class Rule:
    """Which days a series starts on: every ``interval`` days, weeks on ``weekdays``
    (indexes into :data:`WEEKDAYS`), or months on ``month_day`` (from either end) or on
    the ``nth`` ``weekday`` (1 to 4, or -1 for the last) — up to ``until``, an
    instant."""

    frequency: str
    interval: int
    until: datetime
    weekdays: tuple[int, ...] = ()
    month_day: int = 0
    nth: int = 0
    weekday: int = -1

    def text(self) -> str:
        parts = [f"FREQ={self.frequency}"]
        if self.interval != 1:
            parts.append(f"INTERVAL={self.interval}")
        if self.weekdays:
            parts.append("BYDAY=" + ",".join(WEEKDAYS[i] for i in self.weekdays))
        if self.month_day:
            parts.append(f"BYMONTHDAY={self.month_day}")
        if self.nth:
            parts.append(f"BYDAY={self.nth}{WEEKDAYS[self.weekday]}")
        parts.append(f"UNTIL={self.until.astimezone(UTC).strftime(_LOCAL)}Z")
        return ";".join(parts)


@dataclass(frozen=True)
class Window:
    """One span the schedule covers, its two ends instants in UTC, and the starts of the
    windows it is made of, one unless windows that overlap or touch joined."""

    start: datetime
    end: datetime
    starts: tuple[datetime, ...]

    def covers(self, moment: datetime) -> bool:
        return self.start <= moment < self.end


@dataclass(frozen=True)
class Schedule:
    """A recurrence set in the subset (the module's docstring): the ``zone``, the first
    start as a wall time in it, and either the one interval's ``end``, an instant, or a
    ``length`` with at most a ``rule``, ``extra`` starts (wall times), ``intervals`` of
    their own (instants) and starts ``left_out`` (wall times)."""

    zone: str
    start: datetime
    end: datetime | None = None
    length: Length | None = None
    rule: Rule | None = None
    extra: tuple[datetime, ...] = ()
    intervals: tuple[tuple[datetime, datetime], ...] = ()
    left_out: tuple[datetime, ...] = ()

    # --- making one -------------------------------------------------------------

    @classmethod
    def one_off(cls, start: datetime, end: datetime, zone: str) -> Schedule:
        """One interval from ``start`` to ``end``, two instants, its start written as a
        wall time in ``zone``: a window set now, or later.

        :raises ValueError: the zone is none, or the end is not after the start."""
        tz = _zone(zone)
        # the end kept exactly, as a pin's end is; its text says it to the second
        made = cls(zone=zone, start=_wall(start, tz), end=end.astimezone(UTC))
        made.check()
        return made

    @property
    def is_one_off(self) -> bool:
        """Whether it is one window alone, ``DTEND``'s — set as a pin's end is."""
        return self.end is not None

    @property
    def starts_at(self) -> datetime:
        """Its first start, an instant: a one-off's start, or a series' ``DTSTART``."""
        return _at(self.start, _zone(self.zone))

    def year_begins(self, year: int) -> datetime:
        """When ``year`` begins in its zone, an instant: where a window of that year
        starts from, a window belonging to the day it starts on."""
        return _at(datetime.combine(date(year, 1, 1), time()), _zone(self.zone))

    def rule_years(self) -> Mapping[int, datetime]:
        """Each year a window of its rule starts in — by the day it starts on, in its
        zone — with the last such start, an instant: the years a holiday list must
        state for the rule's windows to apply (ADR-0149 decision 3). A start left out
        is none, and a start or an interval added stands whatever the list says, so
        neither counts. Empty without a rule."""
        if self.rule is None:
            return {}
        tz = _zone(self.zone)
        left_out = set(self.left_out)
        years: dict[int, datetime] = {}
        for day in _days(self.rule, self.start.date(),
                         self.rule.until.astimezone(tz).date()):
            wall = datetime.combine(day, self.start.time())
            begin = _at(wall, tz)
            if wall not in left_out and begin <= self.rule.until:
                years[day.year] = begin
        return years

    # --- reading and writing ----------------------------------------------------

    @classmethod
    def parse(cls, text: str) -> Schedule:
        """The schedule ``text`` writes, or :class:`ValueError` saying what of it the
        subset does not take."""
        found: dict[str, tuple[dict[str, str], str]] = {}
        extra: list[datetime] = []
        intervals: list[tuple[datetime, datetime]] = []
        left_out: list[datetime] = []
        zone = ""
        lines = [line for line in text.replace("\r\n", "\n").split("\n") if line]
        for line in lines:
            name, params, value = _content_line(line)
            if name in ("DTSTART", "DTEND", "DURATION", "RRULE"):
                if name in found:
                    raise ValueError(f"a schedule writes {name} twice")
                found[name] = (params, value)
                if name == "DTSTART":
                    zone = params.get("TZID", "")
            elif name in ("RDATE", "EXDATE"):
                found.setdefault(name, (params, ""))
            else:
                raise ValueError(f"a schedule writes {name}, which the subset does "
                                 f"not take")
        if "DTSTART" not in found:
            raise ValueError("a schedule without DTSTART")
        params, value = found["DTSTART"]
        _only(params, {"TZID"}, "DTSTART")
        if not zone:
            raise ValueError("a schedule's DTSTART names no zone (TZID)")
        tz = _zone(zone)
        start = _local(value, "DTSTART")
        end = length = rule = None
        if "DTEND" in found:
            params, value = found["DTEND"]
            end = _instant(params, value, zone, "DTEND")
        if "DURATION" in found:
            params, value = found["DURATION"]
            _only(params, set(), "DURATION")
            length = _length(value)
        if (end is None) == (length is None):
            raise ValueError("a schedule writes DTEND or DURATION, and one of them")
        if "RRULE" in found:
            params, value = found["RRULE"]
            _only(params, set(), "RRULE")
            if length is None:
                raise ValueError("a rule's windows take their length from DURATION")
            rule = _rule(value)
        for line in lines:
            name, params, value = _content_line(line)
            if name == "RDATE":
                if length is None:
                    raise ValueError("RDATE adds to a series, and DTEND makes one "
                                     "window")
                if params.get("VALUE") == "PERIOD":
                    _only(params, {"VALUE"}, "RDATE")
                    for period in value.split(","):
                        begin, _, finish = period.partition("/")
                        intervals.append((_utc(begin, "RDATE"), _utc(finish, "RDATE")))
                else:
                    _only(params, {"TZID"}, "RDATE")
                    _same_zone(params, zone, "RDATE")
                    extra.extend(_local(each, "RDATE") for each in value.split(","))
            elif name == "EXDATE":
                _only(params, {"TZID"}, "EXDATE")
                _same_zone(params, zone, "EXDATE")
                left_out.extend(_local(each, "EXDATE") for each in value.split(","))
        made = cls(zone=zone, start=start, end=end, length=length, rule=rule,
                   extra=tuple(extra), intervals=tuple(intervals),
                   left_out=tuple(left_out))
        made.check(tz)
        return made

    def text(self) -> str:
        """The schedule as its text, in the order and the spelling it is always
        written in, so that the same schedule is the same text."""
        lines = [f"DTSTART;TZID={self.zone}:{self.start.strftime(_LOCAL)}"]
        if self.end is not None:
            lines.append(f"DTEND:{self.end.astimezone(UTC).strftime(_LOCAL)}Z")
        if self.length is not None:
            lines.append(f"DURATION:{self.length.text()}")
        if self.rule is not None:
            lines.append(f"RRULE:{self.rule.text()}")
        if self.extra:
            lines.append(f"RDATE;TZID={self.zone}:"
                         + ",".join(each.strftime(_LOCAL) for each in self.extra))
        if self.intervals:
            lines.append("RDATE;VALUE=PERIOD:" + ",".join(
                f"{a.astimezone(UTC).strftime(_LOCAL)}Z/"
                f"{b.astimezone(UTC).strftime(_LOCAL)}Z" for a, b in self.intervals))
        if self.left_out:
            lines.append(f"EXDATE;TZID={self.zone}:"
                         + ",".join(each.strftime(_LOCAL) for each in self.left_out))
        return "\n".join(lines)

    def check(self, tz: ZoneInfo | None = None) -> None:
        """Refuse what the subset does not take, beyond its spelling: an end not after
        its start, an added interval longer than :data:`LONGEST_INTERVAL`, a last start
        past a year, a first start the rule would not produce.

        :raises ValueError: naming which."""
        tz = tz or _zone(self.zone)
        first = _at(self.start, tz)
        if self.end is not None and not first < self.end:
            raise ValueError("a window's DTEND is not after its start")
        if self.length is not None and not (self.length.days or self.length.span):
            raise ValueError("a schedule's DURATION is no length")
        for begin, finish in self.intervals:
            if not begin < finish <= begin + LONGEST_INTERVAL:
                raise ValueError("an interval's end is not after its start, or more "
                                 "than a year after it")
        starts = [self.start, *self.extra]
        origin = min([_at(each, tz) for each in starts]
                     + [begin for begin, _ in self.intervals])
        bound = _at(datetime.combine(_a_year_on(origin.astimezone(tz).date()),
                                     time(23, 59, 59)), tz)
        latest = [_at(each, tz) for each in starts] + [b for b, _ in self.intervals]
        if self.rule is not None:
            if self.rule.until < first:
                raise ValueError("a rule's UNTIL is before its first start")
            latest.append(self.rule.until)
        if max(latest) > bound:
            raise ValueError("a schedule runs past a year from its first start")
        if self.rule is not None and self.start.date() not in set(
                _days(self.rule, self.start.date(), self.start.date())):
            raise ValueError("a schedule's DTSTART is a day its rule does not pick")

    # --- what it covers ---------------------------------------------------------

    def spans(self, *, days_off: DaysOff | None = None
              ) -> tuple[tuple[datetime, datetime], ...]:
        """Every window as its text writes it, before any is changed alone or joined
        to another: each start, an instant, with the end its text gives it — the
        rule's, less those ``days_off`` leaves out, the starts and intervals added,
        less the starts left out — in order of their starts."""
        tz = _zone(self.zone)
        if self.end is not None:
            return ((_at(self.start, tz), self.end),)
        assert self.length is not None
        found: list[tuple[datetime, datetime]] = []
        left_out = set(self.left_out)
        local_starts: list[tuple[datetime, bool]] = [(self.start, False)]
        if self.rule is not None:
            last = self.rule.until.astimezone(tz).date()
            local_starts = [(datetime.combine(day, self.start.time()), True)
                            for day in _days(self.rule, self.start.date(), last)]
        local_starts += [(each, False) for each in self.extra]
        for wall, by_rule in local_starts:
            if wall in left_out:
                continue
            if by_rule and days_off is not None and _off(days_off, wall.date()):
                continue
            begin = _at(wall, tz)
            if self.rule is not None and by_rule and begin > self.rule.until:
                continue
            found.append((begin, _end(wall, self.length, tz)))
        found += self.intervals
        return tuple(sorted(found))

    def windows(self, *, days_off: DaysOff | None = None,
                changed: Mapping[datetime, datetime] | None = None
                ) -> tuple[Window, ...]:
        """Every window, in order, windows that overlap or touch joined: the rule's,
        less those ``days_off`` leaves out, the starts and intervals added, less the
        starts left out (:meth:`spans`), each changed alone ending where ``changed``
        says — a start, an instant, to the end it was changed to."""
        changed = changed or {}
        return _joined((begin, changed.get(begin, end))
                       for begin, end in self.spans(days_off=days_off))


# --- windows, as a reader asks them ----------------------------------------------


def open_at(windows: Sequence[Window], moment: datetime) -> Window | None:
    """The window open at ``moment``, or ``None`` where none is."""
    index = bisect_right([window.start for window in windows], moment) - 1
    if index >= 0 and windows[index].covers(moment):
        return windows[index]
    return None


def next_after(windows: Sequence[Window], moment: datetime) -> Window | None:
    """The first window that starts after ``moment``, or ``None`` where none does."""
    index = bisect_right([window.start for window in windows], moment)
    return windows[index] if index < len(windows) else None


def last_end(windows: Sequence[Window]) -> datetime | None:
    """When the last window ends — the schedule's end — or ``None`` where it has
    none."""
    return windows[-1].end if windows else None


def first_start(rule: Rule, wall: datetime, zone: str) -> datetime | None:
    """Where a series whose windows start at ``wall``'s time of day, a wall time in
    ``zone``, on the days ``rule`` picks, starts first: the first day on or after
    ``wall``'s that the rule picks, at that time of day (#35's note, decision 4's
    correction) — what its text writes as ``DTSTART``, which RFC 5545 leaves undefined
    where the rule would not pick it (section 3.8.5.3), and what the editor shows as
    its first window before it is set. ``None`` where the rule picks no day by its
    ``UNTIL``."""
    tz = _zone(zone)
    wall = wall.replace(microsecond=0)
    for day in _days(rule, wall.date(), rule.until.astimezone(tz).date()):
        begin = datetime.combine(day, wall.time())
        return begin if _at(begin, tz) <= rule.until else None
    return None


# --- the month --------------------------------------------------------------------


@dataclass(frozen=True)
class Day:
    """One day as the editor's month draws it (ADR-0150, landing 5), in the schedule's
    zone: the ``windows`` that start on it — a window belongs to the day it starts on —
    and what the text says of it: ``ruled``, the start its rule, or its one window, has
    on the day, a wall time, whether or not it applies; whether that start is
    ``left_out`` by hand, where no window starts at it all the same, as an edit's kept
    window does (#35's note, decision 5); ``listed``, the name the holiday list gives
    the day, where it names it; ``uncovered``, where the list is not complete for the
    day's year, which leaves its rule's window missing; a start (``extra``) or an
    interval (``added``) added by hand on it; ``clock``, the minutes the clocks move in
    it — sixty forward, minus sixty back, none where they keep still — and
    ``clock_at``, what the clock reads as they move."""
    day: date
    windows: tuple[Window, ...] = ()
    ruled: datetime | None = None
    left_out: bool = False
    listed: str = ""
    uncovered: bool = False
    extra: bool = False
    added: bool = False
    clock: int = 0
    clock_at: time | None = None


def days(schedule: Schedule, first: date, last: date, *,
         days_off: DaysOff | None = None,
         windows: Sequence[Window] | None = None) -> tuple[Day, ...]:
    """Each day from ``first`` to ``last`` as the editor's month draws it (ADR-0150,
    landing 5): its windows as a reader has them — ``windows``, a standing entry's with
    its windows changed alone, or else the schedule's own, the list's days left out —
    and what the text and the holiday list say of it (:class:`Day`). The one place a
    month is read from the windows, so that what a day says is what the windows are."""
    tz = _zone(schedule.zone)
    if windows is None:
        windows = schedule.windows(days_off=days_off)
    starting: dict[date, list[Window]] = {}
    for window in windows:
        starting.setdefault(window.start.astimezone(tz).date(), []).append(window)
    ruled: dict[date, datetime] = {}
    if schedule.rule is not None:
        rule = schedule.rule
        for day in _days(rule, schedule.start.date(),
                         min(last, rule.until.astimezone(tz).date())):
            wall = datetime.combine(day, schedule.start.time())
            if day >= first and _at(wall, tz) <= rule.until:
                ruled[day] = wall
    elif first <= schedule.start.date() <= last:
        ruled[schedule.start.date()] = schedule.start
    begun = {window.start for window in windows}
    left_out = {each.date() for each in schedule.left_out if _at(each, tz) not in begun}
    extra = {each.date() for each in schedule.extra}
    added = {begin.astimezone(tz).date() for begin, _ in schedule.intervals}
    found = []
    day = first
    while day <= last:
        begins = datetime.combine(day, time()).replace(tzinfo=tz)
        ends = datetime.combine(day + timedelta(days=1), time()).replace(tzinfo=tz)
        tonight, tomorrow = begins.utcoffset(), ends.utcoffset()
        moved = (0 if tonight is None or tomorrow is None
                 else int((tomorrow - tonight).total_seconds()) // 60)
        found.append(Day(
            day, tuple(starting.get(day, ())), ruled.get(day), day in left_out,
            days_off.holiday(day) if days_off is not None else "",
            days_off is not None and not days_off.covers(day.year),
            day in extra, day in added, moved,
            _moved_at(begins, ends, tz) if moved else None))
        day += timedelta(days=1)
    return tuple(found)


def _moved_at(begins: datetime, ends: datetime, tz: ZoneInfo) -> time | None:
    """The time on the clock at which the clocks move, between ``begins`` and
    ``ends``, a day's two midnights in ``tz`` — sought by the quarter hour, the finest
    any zone moves them by."""
    moment, last = begins.astimezone(UTC), ends.astimezone(UTC)
    was = begins.utcoffset()
    while was is not None and moment < last:
        if moment.astimezone(tz).utcoffset() != was:
            return (moment + was).time()
        moment += timedelta(minutes=15)
    return None


def day_off(days_off: DaysOff, day: date) -> bool:
    """Whether ``days_off`` leaves out a rule's window that starts on ``day``
    (ADR-0149 decision 3): it names the day, or it is not complete for its year."""
    return _off(days_off, day)


def instant(wall: datetime, zone: str) -> datetime:
    """A wall time in ``zone`` as the instant every window reads it (decision 2 of
    ADR-0150): one a night skips after the jump, one it repeats at its first pass."""
    return _at(wall, _zone(zone))


# --- the schedule in words ---------------------------------------------------------

#: The weekdays as a sentence names them, Monday first.
_DAY_NAMES = ("Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday",
              "Sunday")
#: An interval as a sentence counts it, from the second on.
_ORDINALS = ("", "", "second", "third", "fourth", "fifth", "sixth", "seventh",
             "eighth", "ninth", "tenth")
#: A weekday of the month as a rule names it.
_NTH = {1: "first", 2: "second", 3: "third", 4: "fourth", -1: "last"}


def sentence(schedule: Schedule, *, until: datetime,
             at: Callable[[datetime], str], zone: str, not_on: str = "",
             after: datetime | None = None) -> str:
    """The schedule in one sentence, written once for every place that says it — each
    list of an entry, the envelope, and the editor to come (ADR-0150): its rule, the
    time of day its windows start at and how long each is, ``until`` — its last
    window's end, which is the entry's — the windows added and left out by hand, and
    ``not_on``, the name of the holiday list its rule leaves out: *Every Saturday from
    22:00 for 8 hours, until 2027-10-31 05:00:00, not on holidays in Bavaria*. One
    window alone is *Once, from … until …*. ``at`` writes an instant as the page writes
    every instant, in the deployment's zone and time format, and a rule's time of day
    is its own zone's, which is named beside it where it is not the page's ``zone``.

    **It says only what is still ahead** of ``after``, the moment the surface is drawn
    (ADR-0150, landing 4): a window added counts while its start lies after it, and so
    does a start left out, and a schedule without a rule says its own first window only
    while that does too — so that the window open now is said by its block's first row
    alone, and what has passed is History's to say. ``after`` left out counts
    everything. A length that is not whole minutes — a one-off a window joined, its end
    typed to the second — is said by its window's end, never by its seconds: *From
    2026-11-01 14:37:12 to 2026-11-01 18:00:00*."""
    tz = _zone(schedule.zone)
    if schedule.end is not None:
        return f"Once, from {at(_at(schedule.start, tz))} until {at(until)}"
    assert schedule.length is not None
    added = (sum(1 for each in schedule.extra if after is None or _at(each, tz) > after)
             + sum(1 for begin, _ in schedule.intervals
                   if after is None or begin > after))
    more = f"{added} more window" + ("s" if added != 1 else "")
    if schedule.rule is not None:
        clock = _clock(schedule.start)
        if schedule.zone != zone:
            clock += f" ({schedule.zone})"
        said = (f"{_days_said(schedule.rule)} from {clock} "
                f"{_lasting(schedule, tz, at)}, until {at(until)}")
    elif after is None or _at(schedule.start, tz) > after:
        said = (f"From {at(_at(schedule.start, tz))} {_lasting(schedule, tz, at)}, "
                f"until {at(until)}")
    else:
        # its first window has begun: what is ahead is the windows added by hand
        said = (f"{more[:1].upper()}{more[1:]}" if added else "No more windows") \
            + f", until {at(until)}"
        added = 0
    if added:
        said += f", {more}"
    left_out = sum(1 for each in schedule.left_out
                   if after is None or _at(each, tz) > after)
    if left_out:
        said += f", {left_out} left out"
    if not_on:
        said += f", not on {not_on}"
    return said


def _numbered(n: int) -> str:
    """*1st*, *2nd*, *3rd*, *11th*, *21st*."""
    if 10 <= n % 100 <= 20:
        return f"{n}th"
    return f"{n}" + {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th")


def _every(interval: int, what: str) -> str:
    """*Every Saturday*, *Every second day*, *Every 12th month*."""
    if interval == 1:
        return f"Every {what}"
    word = _ORDINALS[interval] if interval < len(_ORDINALS) else _numbered(interval)
    return f"Every {word} {what}"


def _listed(names: Sequence[str]) -> str:
    return (names[0] if len(names) == 1
            else ", ".join(names[:-1]) + " and " + names[-1])


def _days_said(rule: Rule) -> str:
    """Which days a rule's windows start on, in words."""
    if rule.frequency == DAILY:
        return _every(rule.interval, "day")
    if rule.frequency == WEEKLY:
        days = list(rule.weekdays)
        if len(days) == 1:
            return _every(rule.interval, _DAY_NAMES[days[0]])
        if days == [0, 1, 2, 3, 4]:
            named, many = "working day", "working days"
        else:
            named = many = _listed([_DAY_NAMES[day] for day in days])
        if rule.interval == 1:
            return f"Every {named}"
        return f"{_every(rule.interval, 'week')} on {many}"
    if rule.nth:
        on = f"on its {_NTH[rule.nth]} {_DAY_NAMES[rule.weekday]}"
    elif rule.month_day > 0:
        on = f"on the {_numbered(rule.month_day)}"
    elif rule.month_day == -1:
        on = "on its last day"
    else:
        on = f"on its {_ORDINALS[-rule.month_day] or _numbered(-rule.month_day)}" \
             "-to-last day"
    return f"{_every(rule.interval, 'month')} {on}"


def _clock(wall: datetime) -> str:
    """A time of day as a rule's windows start at it, *22:00*, its seconds where it has
    them."""
    return wall.strftime("%H:%M:%S" if wall.second else "%H:%M")


def _lasting(schedule: Schedule, tz: ZoneInfo, at: Callable[[datetime], str]) -> str:
    """How long each window of ``schedule`` lasts, as its sentence says it: *for 8
    hours*, *for 1 day* — or, where its length is not whole minutes, *to* its first
    window's end, as the person typed it, never its seconds (ADR-0150, landing 4): a
    time of day for a rule's windows, an instant for a schedule without one."""
    assert schedule.length is not None
    length = schedule.length
    if length.days or int(length.span.total_seconds()) % 60 == 0:
        return f"for {_length_said(length)}"
    if schedule.rule is not None:
        return f"to {_clock(schedule.start + length.span)}"
    return f"to {at(_end(schedule.start, length, tz))}"


def _length_said(length: Length) -> str:
    """*8 hours*, *1 hour 30 minutes*, *1 day*, *2 days* — never the seconds, which a
    sentence says by an end instead (:func:`_lasting`)."""
    if length.days:
        return f"{length.days} day" + ("s" if length.days != 1 else "")
    hours, rest = divmod(int(length.span.total_seconds()), 3600)
    minutes = rest // 60
    parts = []
    for count, unit in ((hours, "hour"), (minutes, "minute")):
        if count:
            parts.append(f"{count} {unit}" + ("s" if count != 1 else ""))
    return " ".join(parts)


# --- the parts -----------------------------------------------------------------------


def _content_line(line: str) -> tuple[str, dict[str, str], str]:
    head, sep, value = line.partition(":")
    if not sep:
        raise ValueError(f"a schedule's line {line!r} is no content line")
    name, *raw = head.split(";")
    params: dict[str, str] = {}
    for each in raw:
        key, eq, said = each.partition("=")
        if not eq or key.upper() in params:
            raise ValueError(f"a schedule's line {line!r} has a parameter it cannot "
                             f"read")
        params[key.upper()] = said
    return name.upper(), params, value


def _only(params: Mapping[str, str], allowed: set[str], name: str) -> None:
    extra = sorted(set(params) - allowed)
    if extra:
        raise ValueError(f"a schedule's {name} has {', '.join(extra)}, which the "
                         f"subset does not take")


def _same_zone(params: Mapping[str, str], zone: str, name: str) -> None:
    if params.get("TZID") != zone:
        raise ValueError(f"a schedule's {name} is in another zone than DTSTART's")


def _zone(name: str) -> ZoneInfo:
    try:
        return ZoneInfo(name)
    except (ZoneInfoNotFoundError, ValueError):
        raise ValueError(f"a schedule's zone {name!r} is none") from None


def _local(value: str, name: str) -> datetime:
    if not _STAMP.fullmatch(value):
        raise ValueError(f"a schedule's {name} {value!r} is no local date and time")
    return datetime.strptime(value, _LOCAL)  # noqa: DTZ007 — a wall time, read in the TZID


def _utc(value: str, name: str) -> datetime:
    if not (value.endswith("Z") and _STAMP.fullmatch(value[:-1])):
        raise ValueError(f"a schedule's {name} {value!r} is no time in UTC")
    return datetime.strptime(value[:-1], _LOCAL).replace(tzinfo=UTC)


def _instant(params: Mapping[str, str], value: str, zone: str, name: str) -> datetime:
    if value.endswith("Z"):
        _only(params, set(), name)
        return _utc(value, name)
    _only(params, {"TZID"}, name)
    _same_zone(params, zone, name)
    return _at(_local(value, name), _zone(zone))


def _length(value: str) -> Length:
    found = _LENGTH.fullmatch(value)
    if not found or value == "PT":
        raise ValueError(f"a schedule's DURATION {value!r} is neither days nor hours, "
                         f"minutes and seconds")
    if found["days"]:
        return Length(days=int(found["days"]))
    return Length(span=timedelta(hours=int(found["hours"] or 0),
                                 minutes=int(found["minutes"] or 0),
                                 seconds=int(found["seconds"] or 0)))


def _rule(value: str) -> Rule:
    parts: dict[str, str] = {}
    for each in value.split(";"):
        key, eq, said = each.partition("=")
        if not eq or key in parts:
            raise ValueError(f"a rule's part {each!r} cannot be read")
        parts[key] = said
    frequency = parts.pop("FREQ", "")
    if frequency not in (DAILY, WEEKLY, MONTHLY):
        raise ValueError(f"a rule's FREQ {frequency or 'nothing'} is not DAILY, "
                         f"WEEKLY or MONTHLY")
    if "UNTIL" not in parts:
        raise ValueError("a rule without UNTIL, its last date")
    until = _utc(parts.pop("UNTIL"), "UNTIL")
    interval = parts.pop("INTERVAL", "1")
    if not interval.isdigit() or int(interval) < 1:
        raise ValueError(f"a rule's INTERVAL {interval!r} is no count")
    if parts.pop("WKST", "MO") != "MO":
        raise ValueError("a rule's weeks start on Monday (WKST=MO)")
    byday = parts.pop("BYDAY", "")
    monthday = parts.pop("BYMONTHDAY", "")
    if parts:
        raise ValueError(f"a rule writes {', '.join(sorted(parts))}, which the subset "
                         f"does not take")
    if frequency == DAILY:
        if byday or monthday:
            raise ValueError("a daily rule picks no days")
        return Rule(DAILY, int(interval), until)
    if frequency == WEEKLY:
        if monthday:
            raise ValueError("a weekly rule picks weekdays, not days of the month")
        days = (tuple(sorted({_weekday(each) for each in byday.split(",")}))
                if byday else ())
        return Rule(WEEKLY, int(interval), until, weekdays=days)
    if byday and monthday:
        raise ValueError("a monthly rule picks a day of the month or a weekday, not "
                         "both")
    if monthday:
        try:
            day = int(monthday)
        except ValueError:
            raise ValueError(f"a rule's BYMONTHDAY {monthday!r} is no day") from None
        if not (1 <= abs(day) <= 31):
            raise ValueError(f"a rule's BYMONTHDAY {monthday!r} is no day")
        return Rule(MONTHLY, int(interval), until, month_day=day)
    if byday:
        found = _ORDINAL_DAY.fullmatch(byday)
        nth = int(found["n"]) if found and found["n"] else 0
        if not found or nth not in (1, 2, 3, 4, -1):
            raise ValueError(f"a rule's BYDAY {byday!r} is not the first to the fourth "
                             f"or the last of a weekday")
        return Rule(MONTHLY, int(interval), until, nth=nth,
                    weekday=WEEKDAYS.index(found["day"]))
    return Rule(MONTHLY, int(interval), until)


def _weekday(said: str) -> int:
    if said not in WEEKDAYS:
        raise ValueError(f"a rule's BYDAY {said!r} is no weekday")
    return WEEKDAYS.index(said)


def _days(rule: Rule, first: date, last: date) -> Iterable[date]:
    """The days ``rule`` picks from ``first``, the first start's, to ``last``, each
    worked out from its own count of days, weeks or months — never from the one
    before."""
    if rule.frequency == DAILY:
        count = 0
        while (day := first + timedelta(days=rule.interval * count)) <= last:
            yield day
            count += 1
        return
    if rule.frequency == WEEKLY:
        weekdays = rule.weekdays or (first.weekday(),)
        monday = first - timedelta(days=first.weekday())
        count = 0
        while (week := monday + timedelta(weeks=rule.interval * count)) <= last:
            for index in weekdays:
                day = week + timedelta(days=index)
                if first <= day <= last:
                    yield day
            count += 1
        return
    count = 0
    while True:
        months = first.month - 1 + rule.interval * count
        year, month = first.year + months // 12, months % 12 + 1
        if date(year, month, 1) > last:
            return
        picked = _month_day(rule, year, month, first.day)
        if picked is not None and first <= picked <= last:
            yield picked
        count += 1


def _month_day(rule: Rule, year: int, month: int, default: int) -> date | None:
    """The day of ``year``'s ``month`` the rule picks, or ``None`` where the month has
    none — the thirty-first of April is no day, and is skipped (RFC 5545)."""
    length = (date(year + month // 12, month % 12 + 1, 1) - timedelta(days=1)).day
    if rule.nth:
        if rule.nth > 0:
            first = date(year, month, 1)
            offset = (rule.weekday - first.weekday()) % 7
            day = 1 + offset + 7 * (rule.nth - 1)
            return date(year, month, day) if day <= length else None
        last = date(year, month, length)
        return last - timedelta(days=(last.weekday() - rule.weekday) % 7)
    wanted = rule.month_day or default
    day = wanted if wanted > 0 else length + 1 + wanted
    return date(year, month, day) if 1 <= day <= length else None


def _off(days_off: DaysOff, day: date) -> bool:
    """Whether the list leaves out a rule's window that starts on ``day``: it names the
    day, or it is not complete for its year, which leaves the day's window missing."""
    return not days_off.covers(day.year) or bool(days_off.holiday(day))


def _at(wall: datetime, tz: ZoneInfo) -> datetime:
    """A wall time in ``tz`` as the instant ``zoneinfo`` reads it — a time a night skips
    after the jump, one it repeats at its first pass — in UTC."""
    return wall.replace(tzinfo=tz, fold=0).astimezone(UTC)


def _wall(moment: datetime, tz: ZoneInfo) -> datetime:
    """An instant as the wall time ``tz`` shows for it, to the second."""
    return moment.astimezone(tz).replace(tzinfo=None, microsecond=0)


def _end(wall: datetime, length: Length, tz: ZoneInfo) -> datetime:
    """Where a window that starts at ``wall`` ends: as many days later at the same time
    of day, read as a start is, or that much real time after its start."""
    if length.days:
        return _at(wall + timedelta(days=length.days), tz)
    return _at(wall, tz) + length.span


def _a_year_on(day: date) -> date:
    """The same day a year later, the twenty-ninth of February the twenty-eighth."""
    try:
        return day.replace(year=day.year + 1)
    except ValueError:
        return day.replace(year=day.year + 1, day=28)


def _joined(spans: Iterable[tuple[datetime, datetime]]) -> tuple[Window, ...]:
    """The spans in order, those that overlap or touch one window; a span changed to
    end where it began, or before, none."""
    windows: list[Window] = []
    for begin, finish in sorted(spans):
        if finish <= begin:
            continue
        if windows and begin <= windows[-1].end:
            last = windows[-1]
            windows[-1] = Window(last.start, max(last.end, finish),
                                 (*last.starts, begin))
        else:
            windows.append(Window(begin, finish, (begin,)))
    return tuple(windows)
