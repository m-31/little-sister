"""A measure's curve over its subject's series: the geometry a page draws (ADR-0092
decisions 4 and 5, as ADR-0096 decisions 3 and 4 amend them).

Pure arithmetic over the readings a series keeps. The page writes it as SVG, on the
server, with no script of its own; everything here is a number or a word that
drawing puts where it says.

**Where a reading goes.** On the time axis, at the instant its series places it —
its own ``at``, or when it was first observed (:class:`~little_sister.series.Placed`)
— to scale, so a night without readings is a night wide. On the value axis, to
scale from a baseline at zero, in the measure's unit; a size steps in powers of two
of a unit, so a tick lands on a whole one (ADR-0096 decision 3). The axis spans what
the series keeps, or the window the Series view's URL names (ADR-0098 decisions 1
and 2) — or, on a page that stands several curves one above the other, the page's
span, so that they share one time axis (ADR-0097 decision 1).

**Where the line breaks, and what says why.** A reading that **failed** — its
record carries an ``error`` that is not null — breaks the line and is **marked** at
its instant in a lane beneath the baseline: a failure is a reading, and it says the
object did not answer (ADR-0096 decision 4). It is never drawn as a zero, and the
lane is below the axis so that it cannot be read as one. A reading that answered but
gives the measure no number — a null, a field the record does not have, anything
that is not a number — breaks the line with no mark: a field a release added, or a
sensor a model does not have, is not a failure. Two neighboring readings further
apart than the freshness tolerance their check's own period implies have a **hole**
between them — a restart, a pause, a machine asleep — and the line breaks there with
no mark either; one missed poll is not a hole, as it does not make the node stale
either. The line crosses none of them: across them there is nothing that was read. A
window that holds more readings than the plot has columns is drawn column by column
(ADR-0098 decision 5): the line breaks at a hole at least a column wide and at a
column none of whose readings has a number, and a column that holds a failed reading
carries one mark.

**What it says in words.** Each reading's time and value where the pointer is —
the whole height of the plot between two readings' midpoints belongs to the nearer
one, so the pointer finds a date and never has to land on a two-pixel line — and a
summary beside the title. The readings table beneath carries every value too, so
nothing is only a tooltip. The times read in the configured timezone and
``time_format`` (ADR-0120 decision 7), as every time the page shows does.

**A run is a mark, and no line joins two** (ADR-0106 decision 5, ADR-0111). A
series' **runs** are its records with an identity — an event its source keeps: a
workflow's run, a job's, a load test's — and :func:`draw_runs` draws each at its own
instant on the same time axis. With a measure a run is a **stem** from the baseline
to its value; without one a **tick**, whose height says how the run stood. What
says that is the code its reading kept: a run that passed has a filled head, one
that warned the warning's triangle, one that failed a hollow ring in the failure ink
and a mark in the lane, and one that kept no verdict a bare mark in the muted ink,
which claims nothing. Every run is drawn where it stands, so nothing is merged
where runs crowd; a passing run's head gives way where it would run into another
head. A record with a state is not a run and is not drawn: it says how an object
stood from then on, which a mark at one instant cannot.
"""
from __future__ import annotations

import math
from bisect import bisect_left, bisect_right
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta, tzinfo
from itertools import pairwise
from typing import Any

from little_sister.codes import StatusCode
from little_sister.measures import SIZE_UNITS, SPAN_UNITS, Measure
from little_sister.series import Placed
from little_sister.spans import local_time

#: The drawing's size, in the user units the page shows it at one to one; it
#: scales down to fit a narrow card and never up, so its words keep their size. The
#: time axis is a drawing of its own beneath it, as wide, so that its labels and the
#: stretches between them can be links while the plot stays one picture.
WIDTH = 760
HEIGHT = 158
AXIS_HEIGHT = 22
#: The plot, where the readings are drawn.
LEFT = 72.0
RIGHT = 744.0
TOP = 16.0
BOTTOM = 136.0
#: The lane a reading without a value is marked in: beneath the baseline, so a mark
#: can never be read as a value, and least of all as zero.
LANE_TOP = 142.0
LANE_BOTTOM = 152.0
#: Where a time label stands in the axis beneath the plot, and a free-text unit above
#: the value ticks.
TIME_BASELINE = 15.0
UNIT_BASELINE = 10.0
#: The columns a plot is drawn in where a window holds more readings than that: two
#: units each (ADR-0098 decision 5).
COLUMNS = 336

#: And of a curve seen small (ADR-0114 decision 1): the strip is 120 pixels wide, two
#: to a column.
SPARK_COLUMNS = 60
#: The most labels a time axis carries (ADR-0098 decision 4).
_MOST_LABELS = 6
#: The steps a time axis is labeled at, smallest first, with about how long each is,
#: so a step that would put far too many labels on the axis is passed over unwalked.
_TIME_STEPS: tuple[tuple[str, int, float], ...] = (
    ("minute", 1, 60), ("minute", 2, 120), ("minute", 5, 300), ("minute", 15, 900),
    ("minute", 30, 1800),
    ("hour", 1, 3600), ("hour", 3, 10800), ("hour", 6, 21600), ("hour", 12, 43200),
    ("day", 1, 86400), ("day", 2, 172800), ("week", 1, 604800),
    ("month", 1, 2629746), ("month", 3, 7889238),
    ("year", 1, 31556952), ("year", 2, 63113904), ("year", 5, 157784760))

#: How many intervals the value axis aims at.
_INTERVALS = 4
#: The steps a span's axis takes, in seconds: each one a span somebody would name.
_SPAN_STEPS = (0.001, 0.002, 0.005, 0.01, 0.02, 0.05, 0.1, 0.2, 0.25, 0.5, 1, 2, 5,
               10, 15, 30, 60, 120, 300, 600, 900, 1800, 3600, 7200, 10800, 21600,
               43200, 86400, 172800, 604800)
#: The multiples a plain number's axis steps in, within each power of ten.
_MULTIPLES = (1, 2, 2.5, 5, 10)


#: How a run stood, as its mark says it (ADR-0111 decisions 1 and 3): the code its
#: reading kept — ``OK``, ``WARN``, ``ERROR`` — or none of them, where no line
#: carried the reading or the line stood ``UNDEFINED``.
PASSED = "passed"
WARNED = "warned"
FAILED = "failed"
UNJUDGED = "unjudged"

#: A plot of runs without a measure has no value axis, so it is only as tall as its
#: tallest mark: the baseline, and how far above it each verdict's tick ends — a run
#: without a verdict half as tall as one that passed, and a warning between a pass
#: and a failure. Where a tick has a head, that is the head's middle.
TICKS_HEIGHT = 64
TICKS_TOP = 6.0
TICKS_BOTTOM = 48.0
_TICK = {UNJUDGED: 6.0, PASSED: 12.0, WARNED: 24.0, FAILED: 36.0}

#: What a plot of runs is titled where its check declares no measure for them.
RUNS_LABEL = "Runs"

#: How wide a head is: two heads whose middles are nearer than this run into each
#: other (ADR-0111 decision 4).
HEAD = 8.0


@dataclass(frozen=True)
class Stem:
    """A run, where it is drawn: a mark at its own instant, from the baseline to
    ``y`` — its value on a measure's plot, the height its verdict gives a tick on a
    plot without one. ``verdict`` is how its reading stood, and ``head`` whether a
    head is drawn at ``y``: every run that warned or failed has one, a run without a
    verdict none, and a run that passed one where it has room for it."""

    x: float
    y: float
    at: datetime
    verdict: str
    head: bool


@dataclass(frozen=True)
class Point:
    """A reading with a value, where it is drawn."""

    x: float
    y: float
    at: datetime
    value: float


@dataclass(frozen=True)
class Mark:
    """A reading that failed, marked at its instant in the lane."""

    x: float
    at: datetime


@dataclass(frozen=True)
class Tick:
    """One step of the value axis: where its gridline runs, and what it reads."""

    y: float
    text: str


@dataclass(frozen=True)
class TimeTick:
    """One label of the time axis: the round time it stands at, where, and what it
    reads."""

    x: float
    text: str
    at: datetime


@dataclass(frozen=True)
class Stretch:
    """The stretch of the time axis between two of its labels — or an end and the
    label nearest it — which leads into the window it spans where the page says
    so."""

    x: float
    width: float
    start: datetime
    end: datetime


@dataclass(frozen=True)
class Strip:
    """The stretch of the plot that belongs to one reading under the pointer."""

    x: float
    width: float
    title: str


@dataclass(frozen=True)
class Curve:
    """One measure over one series, ready to be drawn.

    ``runs`` are the unbroken stretches of line, each of two readings or more, and
    ``dots`` the readings that stand alone between two breaks; ``end`` is the newest
    reading where it has a value. ``marks`` are the readings that failed. The
    counts and the three values are the summary the title stands beside:
    ``valued`` readings gave the measure a number, ``failed`` ones did not answer,
    ``unvalued`` ones answered without a number for it — and a measure with nothing
    ``valued`` has no curve to draw (ADR-0096 decision 4).

    A plot **of runs** (``of_runs``, :func:`draw_runs`) has ``stems`` in place of a
    line: no stretch, no dot and no end. Its ``readings`` are its runs, ``failed``
    the ones whose reading stood ``ERROR``, ``warned`` the ones that stood ``WARN``
    and ``unjudged`` the ones that kept no verdict; ``marks`` are the columns of the
    lane that hold a run that failed.
    """

    label: str
    unit_label: str
    runs: tuple[tuple[Point, ...], ...]
    dots: tuple[Point, ...]
    end: Point | None
    marks: tuple[Mark, ...]
    ticks: tuple[Tick, ...]
    first: str
    last: str
    hover: tuple[Strip, ...]
    readings: int
    unvalued: int
    holes: int
    failed: int
    valued: int
    newest: str
    lowest: str
    highest: str
    time_ticks: tuple[TimeTick, ...] = ()
    stretches: tuple[Stretch, ...] = ()
    width: int = WIDTH
    height: int = HEIGHT
    axis_height: int = AXIS_HEIGHT
    left: float = LEFT
    right: float = RIGHT
    top: float = TOP
    bottom: float = BOTTOM
    lane_top: float = LANE_TOP
    lane_bottom: float = LANE_BOTTOM
    time_baseline: float = TIME_BASELINE
    unit_baseline: float = UNIT_BASELINE
    stems: tuple[Stem, ...] = ()
    of_runs: bool = False
    warned: int = 0
    unjudged: int = 0

    @property
    def paths(self) -> tuple[str, ...]:
        """Each run as the ``d`` of an SVG path."""
        return tuple("M" + " L".join(f"{point.x:.1f} {point.y:.1f}" for point in run)
                     for run in self.runs)

    def stem_path(self, verdict: str) -> str:
        """Every stem of one verdict as the ``d`` of one SVG path, each from the
        baseline to where it ends — empty where no run stood so."""
        return "".join(f"M{stem.x:.1f} {self.bottom:.1f}V{stem.y:.1f}"
                       for stem in self.stems if stem.verdict == verdict)

    def heads(self, verdict: str) -> tuple[Stem, ...]:
        """The stems of one verdict whose head is drawn, in the order they ran."""
        return tuple(stem for stem in self.stems
                     if stem.head and stem.verdict == verdict)


def draw(measure: Measure, readings: Sequence[Placed], *,
         tolerance: float | None,
         span: tuple[datetime, datetime] | None = None,
         times: Callable[[datetime], str] | None = None,
         small: bool = False) -> Curve:
    """``measure`` over ``readings`` — a series' window, each where its series
    places it — with a hole wherever two neighbors are further apart than
    ``tolerance`` seconds; ``None`` is a node that cannot go stale, which has none.
    ``span`` is the page's time axis where several curves share one; the series'
    own first and last reading otherwise.

    ``times`` writes every instant the curve says — a hover strip's title, the axis
    ends — and is :func:`~little_sister.spans.local_time`, the configured zone and
    format, unless the caller hands another: a page drawing several curves over one
    series' readings hands them all one that remembers what it wrote, since a curve
    writes the time of every reading it is drawn over.

    ``small`` is the curve to be seen small (ADR-0114 decision 1): the same scale and
    the same breaks, drawn over :data:`SPARK_COLUMNS` columns where it holds more
    readings than that, with no axis, no step and nothing under a pointer — and so
    with no instant written."""
    if small:
        times = _unsaid
    times = times or local_time
    columns = SPARK_COLUMNS if small else COLUMNS
    ordered = sorted(readings, key=lambda reading: reading.at)
    failures = [_failed(reading.record.data) for reading in ordered]
    values = [None if failed else _value(measure.read(reading.record.data))
              for reading, failed in zip(ordered, failures, strict=True)]
    numbers = [value for value in values if value is not None]
    if not ordered and span is None:
        return Curve(label=measure.label, unit_label=measure.axis_unit, runs=(),
                     dots=(), end=None, marks=(), ticks=(), first="", last="",
                     hover=(), readings=0, unvalued=0, holes=0, failed=0, valued=0,
                     newest="", lowest="", highest="")
    # In UTC: two instants of one zone subtract as their clocks read.
    first_at, last_at = (moment.astimezone(UTC) for moment
                         in (span or (ordered[0].at, ordered[-1].at)))
    seconds, x_of, time_ticks, stretches = _time_axis(first_at, last_at)
    if not ordered:
        # A window with nothing in it: the axis stands, and the curve says so.
        return Curve(label=measure.label, unit_label=measure.axis_unit, runs=(),
                     dots=(), end=None, marks=(), ticks=(), first=times(first_at),
                     last=times(last_at), hover=(), readings=0, unvalued=0, holes=0,
                     failed=0, valued=0, newest="", lowest="", highest="",
                     time_ticks=time_ticks, stretches=stretches)

    low, high, step = (_scale(numbers, measure.unit, measure.axis_to)
                       if numbers else (0.0, 1.0, 1.0))

    def y_of(value: float) -> float:
        return BOTTOM - (value - low) / (high - low) * (BOTTOM - TOP)

    ticks: tuple[Tick, ...] = ()
    if numbers and not small:
        steps = round((high - low) / step)
        ticks = tuple(Tick(y_of(value), measure.write(value, bare=True))
                      for value in (round(low + index * step, 9)
                                    for index in range(steps + 1)))

    holes = sum(1 for before, after in pairwise(ordered)
                if tolerance is not None
                and (after.at - before.at).total_seconds() > tolerance)
    if len(ordered) > columns:
        runs, dots, marks, hover = _by_column(
            ordered, values, failures, measure, times,
            column_of=lambda at: _column(at, first_at, seconds, columns),
            x_of=x_of, y_of=y_of, tolerance=tolerance, seconds=seconds,
            columns=columns, said=not small)
    else:
        runs, dots, marks = _by_reading(ordered, values, failures, x_of=x_of,
                                        y_of=y_of, tolerance=tolerance)
        hover = (() if small
                 else _hover(ordered, values, failures, measure, x_of, times))
    newest = ordered[-1]
    end = (Point(x_of(newest.at), y_of(values[-1]), newest.at, values[-1])
           if values[-1] is not None else None)
    failed = sum(failures)

    return Curve(
        label=measure.label, unit_label=measure.axis_unit, runs=tuple(runs),
        dots=tuple(dots), end=end, marks=tuple(marks), ticks=ticks,
        first=times(first_at), last=times(last_at), hover=hover,
        readings=len(ordered), failed=failed, valued=len(numbers),
        unvalued=len(ordered) - len(numbers) - failed, holes=holes,
        newest=_said(values[-1], failures[-1], measure),
        lowest=measure.write(min(numbers)) if numbers else "",
        highest=measure.write(max(numbers)) if numbers else "",
        time_ticks=() if small else time_ticks,
        stretches=() if small else stretches)


def _unsaid(at: datetime) -> str:
    """An instant a drawing does not say."""
    return ""


def _time_axis(first_at: datetime, last_at: datetime
               ) -> tuple[float, Callable[[datetime], float], tuple[TimeTick, ...],
                          tuple[Stretch, ...]]:
    """The time axis from ``first_at`` to ``last_at``, both in UTC: how many seconds
    it spans, where an instant stands on it, its labels at round times and the
    stretches between them (ADR-0098 decisions 3 and 4) — the one axis a curve and a
    plot of runs are drawn on."""
    seconds = (last_at - first_at).total_seconds()

    def x_of(at: datetime) -> float:
        if seconds <= 0:
            return RIGHT
        return LEFT + (at - first_at).total_seconds() / seconds * (RIGHT - LEFT)

    labels = time_labels(first_at, last_at)
    time_ticks = tuple(TimeTick(x_of(at), text, at) for at, text in labels)
    bounds = [first_at, *(at for at, _text in labels), last_at] if labels else []
    stretches = tuple(Stretch(x_of(start), x_of(end) - x_of(start), start, end)
                      for start, end in pairwise(bounds) if end > start)
    return seconds, x_of, time_ticks, stretches


def runs_of(readings: Iterable[Placed]) -> list[Placed]:
    """The runs among a series' readings: its records with an identity — the event
    a reading is of, which its source keeps (ADR-0087 decision 3). A record with a
    state is no run, and neither is a reading that names nothing (ADR-0111 decision
    5)."""
    return [reading for reading in readings if reading.record.identity]


def verdict_of(code: StatusCode | None) -> str:
    """How a run stood, from the code its reading kept (ADR-0087 decision 8): no
    verdict where it kept none, or one that is no claim."""
    if code is None:
        return UNJUDGED
    return {StatusCode.OK: PASSED, StatusCode.WARN: WARNED,
            StatusCode.ERROR: FAILED}.get(code, UNJUDGED)


def runs_drawable(measure: Measure | None, runs: Iterable[Placed]) -> bool:
    """Whether ``runs`` have a plot: under a measure, where a run gives it a number,
    as :func:`drawable` asks of a curve; and without one wherever there is a run,
    every run being a tick."""
    if measure is None:
        return any(True for _run in runs)
    return drawable(measure, runs)


def draw_runs(measure: Measure | None, runs: Sequence[Placed], *,
              span: tuple[datetime, datetime] | None = None,
              times: Callable[[datetime], str] | None = None) -> Curve:
    """``runs`` — a series' records with an identity, each where its series places
    it — as marks on the time axis (ADR-0106 decision 5, ADR-0111): under
    ``measure`` a stem from the baseline to each run's value, and without one a tick
    whose height says how the run stood. ``span`` is the page's time axis where
    several plots share one, and ``times`` writes every instant the plot says, as
    for :func:`draw`.

    Every run is drawn at its own instant and its own value, the worse painted over
    the better by the page; a passing run's head is left out where it would run into
    another head, and the newest run keeps its own (decision 4). The lane marks each
    column that holds a run that failed, under a measure, where a short failure
    near the baseline could be missed; a tick says it by its height alone. What the
    summary counts is counted over every run handed in (decision 6)."""
    times = times or local_time
    ordered = sorted(runs, key=lambda run: run.at)
    label = RUNS_LABEL if measure is None else measure.label
    unit_label = "" if measure is None else measure.axis_unit
    frame: dict[str, Any] = {"of_runs": True}
    if measure is None:
        frame.update(height=TICKS_HEIGHT, top=TICKS_TOP, bottom=TICKS_BOTTOM,
                     lane_top=TICKS_BOTTOM + 8.0, lane_bottom=TICKS_BOTTOM + 8.0)
    if not ordered and span is None:
        return Curve(label=label, unit_label=unit_label, runs=(), dots=(),
                     end=None, marks=(), ticks=(), first="", last="", hover=(),
                     readings=0, unvalued=0, holes=0, failed=0, valued=0,
                     newest="", lowest="", highest="", **frame)
    # In UTC: two instants of one zone subtract as their clocks read.
    first_at, last_at = (moment.astimezone(UTC) for moment
                         in (span or (ordered[0].at, ordered[-1].at)))
    seconds, x_of, time_ticks, stretches = _time_axis(first_at, last_at)
    if not ordered:
        # A window with no run in it: the axis stands, and the plot says so.
        return Curve(label=label, unit_label=unit_label, runs=(), dots=(),
                     end=None, marks=(), ticks=(), first=times(first_at),
                     last=times(last_at), hover=(), readings=0, unvalued=0, holes=0,
                     failed=0, valued=0, newest="", lowest="", highest="",
                     time_ticks=time_ticks, stretches=stretches, **frame)

    verdicts = [verdict_of(run.record.code) for run in ordered]
    values = [None if measure is None or _failed(run.record.data)
              else _value(measure.read(run.record.data)) for run in ordered]
    numbers = [value for value in values if value is not None]
    ticks: tuple[Tick, ...] = ()
    marks: list[Mark] = []
    if measure is None:
        stems = tuple(
            Stem(x_of(run.at), TICKS_BOTTOM - _TICK[verdict], run.at, verdict,
                 head=verdict in (WARNED, FAILED))
            for run, verdict in zip(ordered, verdicts, strict=True))
    else:
        low, high, step = (_scale(numbers, measure.unit, measure.axis_to)
                           if numbers else (0.0, 1.0, 1.0))

        def y_of(value: float) -> float:
            return BOTTOM - (value - low) / (high - low) * (BOTTOM - TOP)

        if numbers:
            steps = round((high - low) / step)
            ticks = tuple(Tick(y_of(value), measure.write(value, bare=True))
                          for value in (round(low + index * step, 9)
                                        for index in range(steps + 1)))
        stems = _with_room(
            [Stem(x_of(run.at), y_of(value), run.at, verdict,
                  head=verdict != UNJUDGED)
             for run, verdict, value in zip(ordered, verdicts, values, strict=True)
             if value is not None], newest=ordered[-1].at)
        marked: set[int] = set()
        for run, verdict in zip(ordered, verdicts, strict=True):
            column = _column(run.at, first_at, seconds)
            if column not in marked and (verdict == FAILED
                                         or _failed(run.record.data)):
                marked.add(column)
                marks.append(Mark(x_of(run.at), run.at))
    return Curve(
        label=label, unit_label=unit_label, runs=(), dots=(), end=None,
        marks=tuple(marks), ticks=ticks, first=times(first_at),
        last=times(last_at),
        hover=_runs_hover(ordered, values, verdicts, measure, times,
                          column_of=lambda at: _column(at, first_at, seconds),
                          x_of=x_of),
        readings=len(ordered), unvalued=len(ordered) - len(numbers), holes=0,
        failed=verdicts.count(FAILED), valued=len(numbers),
        newest=("" if measure is None or not numbers
                else "no value" if values[-1] is None
                else measure.write(values[-1])),
        lowest=(measure.write(min(numbers))
                if measure is not None and numbers else ""),
        highest=(measure.write(max(numbers))
                 if measure is not None and numbers else ""),
        time_ticks=time_ticks, stretches=stretches, stems=stems,
        warned=verdicts.count(WARNED), unjudged=verdicts.count(UNJUDGED), **frame)


def _with_room(stems: Sequence[Stem], *, newest: datetime) -> tuple[Stem, ...]:
    """``stems`` with a passing run's head left out where it would run into another
    head — one whose middle is nearer than a head is wide (ADR-0111 decision 4). A
    run that warned or failed keeps its head, being what the plot is read for, and
    so does the run that finished at ``newest``, as a curve's newest reading keeps
    its dot. Each stem stays where it is: nothing is merged."""
    heads = sorted((stem.x, stem.y) for stem in stems if stem.head)
    xs = [x for x, _y in heads]
    fitted: list[Stem] = []
    for stem in stems:
        if stem.verdict != PASSED or stem.at == newest:
            fitted.append(stem)
            continue
        near = heads[bisect_left(xs, stem.x - HEAD):bisect_right(xs, stem.x + HEAD)]
        # its own head is among them, once
        crowded = sum(1 for x, y in near
                      if math.hypot(x - stem.x, y - stem.y) < HEAD) > 1
        fitted.append(replace(stem, head=False) if crowded else stem)
    return tuple(fitted)


def _runs_hover(ordered: Sequence[Placed], values: Sequence[float | None],
                verdicts: Sequence[str], measure: Measure | None,
                times: Callable[[datetime], str], *,
                column_of: Callable[[datetime], int],
                x_of: Callable[[datetime], float]) -> tuple[Strip, ...]:
    """The plot, cut between the middles of each two neighboring columns that hold a
    run: the strip a column owns under the pointer, and what it says there — a run
    alone its time, its value and how it stood, and several their range, their
    count, their times, and how many of them failed or warned (ADR-0098 decision 5,
    as ADR-0111 decision 4 has it for runs)."""
    held: dict[int, list[int]] = {}
    for index, run in enumerate(ordered):
        held.setdefault(column_of(run.at), []).append(index)
    groups = [held[column] for column in sorted(held)]
    xs = [x_of(ordered[indexes[0]].at) for indexes in groups]
    edges = [LEFT, *((before + after) / 2 for before, after in pairwise(xs)), RIGHT]
    return tuple(
        Strip(edges[index], edges[index + 1] - edges[index],
              _runs_say(ordered, values, verdicts, indexes, measure, times))
        for index, indexes in enumerate(groups))


#: How a run stood, in the words a strip says it with; a pass under a measure is the
#: value alone.
_STOOD = {PASSED: "passed", WARNED: "warned", FAILED: "failed",
          UNJUDGED: "no verdict"}


def _runs_say(ordered: Sequence[Placed], values: Sequence[float | None],
              verdicts: Sequence[str], indexes: Sequence[int],
              measure: Measure | None, times: Callable[[datetime], str]) -> str:
    """What a column of runs says under the pointer."""
    if len(indexes) == 1:
        index = indexes[0]
        said = [times(ordered[index].at)]
        if measure is not None:
            value = values[index]
            said.append("no value" if value is None else measure.write(value))
        if measure is None or verdicts[index] != PASSED:
            said.append(_STOOD[verdicts[index]])
        return " · ".join(said)
    numbers = [value for index in indexes if (value := values[index]) is not None]
    head = f"{len(indexes)} runs"
    if measure is not None and numbers:
        low, high = measure.write(min(numbers)), measure.write(max(numbers))
        head = f"{low if low == high else f'{low}–{high}'} over {head}"
    text = (f"{head}, {times(ordered[indexes[0]].at)}–"
            f"{times(ordered[indexes[-1]].at)}")
    for verdict in (FAILED, WARNED):
        count = sum(1 for index in indexes if verdicts[index] == verdict)
        if count:
            text += f" · {count} {verdict}"
    return text


def _by_reading(ordered: Sequence[Placed], values: Sequence[float | None],
                failures: Sequence[bool], *, x_of: Callable[[datetime], float],
                y_of: Callable[[float], float], tolerance: float | None
                ) -> tuple[list[tuple[Point, ...]], list[Point], list[Mark]]:
    """Every reading where it stands: the line broken at each reading without a
    value and at each stretch without readings longer than ``tolerance``, and a mark
    for each reading that failed (ADR-0092 decision 5, as ADR-0096 amends it)."""
    runs: list[tuple[Point, ...]] = []
    dots: list[Point] = []
    marks: list[Mark] = []
    current: list[Point] = []
    previous: Placed | None = None
    for reading, value, failed in zip(ordered, values, failures, strict=True):
        hole = (previous is not None and tolerance is not None
                and (reading.at - previous.at).total_seconds() > tolerance)
        if hole or value is None:
            _close(current, runs, dots)
            current = []
        if failed:
            marks.append(Mark(x_of(reading.at), reading.at))
        if value is not None:
            current.append(Point(x_of(reading.at), y_of(value), reading.at, value))
        previous = reading
    _close(current, runs, dots)
    return runs, dots, marks


def _column(at: datetime, first_at: datetime, seconds: float,
            columns: int = COLUMNS) -> int:
    """The column of the plot ``at`` falls in: its share of the window, in columns."""
    if seconds <= 0:
        return columns - 1
    share = (at - first_at).total_seconds() / seconds
    return min(columns - 1, max(0, int(share * columns)))


def _by_column(ordered: Sequence[Placed], values: Sequence[float | None],
               failures: Sequence[bool], measure: Measure,
               times: Callable[[datetime], str], *,
               column_of: Callable[[datetime], int],
               x_of: Callable[[datetime], float], y_of: Callable[[float], float],
               tolerance: float | None, seconds: float,
               columns: int = COLUMNS, said: bool = True
               ) -> tuple[list[tuple[Point, ...]], list[Point], list[Mark],
                          tuple[Strip, ...]]:
    """A window with more readings than the plot has columns, drawn column by column
    (ADR-0098 decision 5): each column's first, last, lowest and highest reading, so
    the line is the one every reading would draw and no spike is lost. A stretch
    without readings longer than ``tolerance`` breaks the line where it is at least
    a column wide, and so does a column none of whose readings has a value; a column
    holding a reading that failed carries one mark; each column's strip says what it
    holds — unless nothing is ``said``, as under a curve seen small, which is drawn
    over fewer ``columns``."""
    held: dict[int, list[int]] = {}
    for index, reading in enumerate(ordered):
        held.setdefault(column_of(reading.at), []).append(index)
    runs: list[tuple[Point, ...]] = []
    dots: list[Point] = []
    marks: list[Mark] = []
    strips: list[Strip] = []
    current: list[Point] = []
    width = (RIGHT - LEFT) / columns
    last_index: int | None = None
    for column in sorted(held):
        indexes = held[column]
        if last_index is not None and tolerance is not None:
            gap = (ordered[indexes[0]].at - ordered[last_index].at).total_seconds()
            if gap > tolerance and seconds > 0 and gap / seconds * columns >= 1:
                _close(current, runs, dots)
                current = []
        valued = [index for index in indexes if values[index] is not None]
        if valued:
            lowest = min(valued, key=lambda index: values[index] or 0.0)
            highest = max(valued, key=lambda index: values[index] or 0.0)
            for index in sorted({valued[0], valued[-1], lowest, highest}):
                value = values[index]
                assert value is not None
                at = ordered[index].at
                current.append(Point(x_of(at), y_of(value), at, value))
        else:
            _close(current, runs, dots)
            current = []
        failed = [index for index in indexes if failures[index]]
        if failed:
            marks.append(Mark(x_of(ordered[failed[0]].at), ordered[failed[0]].at))
        if said:
            strips.append(Strip(LEFT + column * width, width,
                                _column_says(ordered, values, failures, indexes,
                                             measure, times)))
        last_index = indexes[-1]
    _close(current, runs, dots)
    return runs, dots, marks, tuple(strips)


def _column_says(ordered: Sequence[Placed], values: Sequence[float | None],
                 failures: Sequence[bool], indexes: Sequence[int], measure: Measure,
                 times: Callable[[datetime], str]) -> str:
    """What a column holds, under the pointer: a reading alone as it would read by
    itself, and several as their range, their count and their times."""
    if len(indexes) == 1:
        index = indexes[0]
        return (f"{times(ordered[index].at)} · "
                f"{_said(values[index], failures[index], measure)}")
    numbers = [value for index in indexes if (value := values[index]) is not None]
    if numbers:
        # a range whose two ends read the same is that one value, as written
        low, high = measure.write(min(numbers)), measure.write(max(numbers))
        said = low if low == high else f"{low}–{high}"
    else:
        said = "no value"
    text = (f"{said} over {len(indexes)} readings, "
            f"{times(ordered[indexes[0]].at)}–{times(ordered[indexes[-1]].at)}")
    failed = sum(1 for index in indexes if failures[index])
    return f"{text} · {failed} failed" if failed else text


def time_labels(first: datetime, last: datetime
                ) -> tuple[tuple[datetime, str], ...]:
    """The labels of a time axis from ``first`` to ``last`` (ADR-0098 decision 4):
    round times in the configured timezone strictly between the two, at the smallest
    step of the ladder that puts no more than six on it, stepped in local time — so a
    day with 23 or 25 hours is labeled as the clock read it, and a time the clock
    skipped is not labeled at all — each written as short as its step allows."""
    from little_sister.config import config
    zone = config.tzinfo
    # In UTC throughout: two instants of one zone compare and subtract as their
    # clocks read, and around a change of the clocks that is an hour wrong.
    first, last = first.astimezone(UTC), last.astimezone(UTC)
    seconds = (last - first).total_seconds()
    if seconds <= 0:
        return ()
    for unit, count, length in _TIME_STEPS:
        if seconds / length > _MOST_LABELS + 2:
            continue
        found = _round_times(first, last, zone, unit, count,
                             steps=int(seconds / length) + 4)
        if len(found) <= _MOST_LABELS:
            return tuple((at, _time_label(at.astimezone(zone), unit)) for at in found)
    return ()


def _round_times(first: datetime, last: datetime, zone: tzinfo, unit: str,
                 count: int, *, steps: int) -> list[datetime]:
    """Every round time of the step ``count`` ``unit`` strictly between ``first`` and
    ``last``, walked on the local clock from the round time at or before ``first``."""
    local = first.astimezone(zone).replace(tzinfo=None)
    if unit == "minute":
        wall = local.replace(minute=local.minute - local.minute % count, second=0,
                             microsecond=0)
    elif unit == "hour":
        wall = local.replace(hour=local.hour - local.hour % count, minute=0,
                             second=0, microsecond=0)
    elif unit in ("day", "week"):
        wall = local.replace(hour=0, minute=0, second=0, microsecond=0)
        wall -= timedelta(days=(local.weekday() if unit == "week"
                                else wall.toordinal() % count))
    elif unit == "month":
        # Wall times on purpose (ADR-0120), this one and the next: a round time
        # is one of the zone's own clock, and `_on_the_clock` gives it the zone.
        wall = datetime(  # noqa: DTZ001
            local.year, local.month - (local.month - 1) % count, 1)
    else:
        wall = datetime(local.year - local.year % count, 1, 1)  # noqa: DTZ001
    found: list[datetime] = []
    for _ in range(steps + 2):
        at = _on_the_clock(wall, zone)
        if at is not None:
            if at >= last:
                break
            if at > first:
                found.append(at)
        wall = _next_round(wall, unit, count)
    return found


def _on_the_clock(wall: datetime, zone: tzinfo) -> datetime | None:
    """The instant, in UTC, a local clock read ``wall`` at — the first time, where
    it read it twice — or ``None`` for a time it skipped."""
    at = wall.replace(tzinfo=zone).astimezone(UTC)
    if at.astimezone(zone).replace(tzinfo=None) != wall:
        return None
    return at


def _next_round(wall: datetime, unit: str, count: int) -> datetime:
    """The next round time on the local clock."""
    if unit == "minute":
        return wall + timedelta(minutes=count)
    if unit == "hour":
        return wall + timedelta(hours=count)
    if unit == "day":
        return wall + timedelta(days=count)
    if unit == "week":
        return wall + timedelta(weeks=count)
    if unit == "month":
        years, month = divmod(wall.month - 1 + count, 12)
        return wall.replace(year=wall.year + years, month=month + 1)
    return wall.replace(year=wall.year + count)


def _time_label(local: datetime, unit: str) -> str:
    """A time label as short as its step allows, in the ISO style of the family's
    format: the clock within a day, the date at a midnight and for days and weeks,
    the month for months and the year for years."""
    if unit in ("minute", "hour"):
        return local.strftime("%m-%d" if (local.hour, local.minute) == (0, 0)
                              else "%H:%M")
    if unit in ("day", "week"):
        return local.strftime("%m-%d")
    return local.strftime("%Y-%m" if unit == "month" else "%Y")


def drawable(measure: Measure, readings: Iterable[Placed]) -> bool:
    """Whether ``measure`` has a curve over ``readings`` — a reading that did not
    fail gives it a number, which is what :func:`draw` counts ``valued`` (ADR-0096
    decision 4) — answered without drawing one, by the same two rules, and reading
    no further than the first reading that does. A page that only needs to know
    which curves there are asks this, since a curve costs a formatted time and a
    hover strip for every reading it is drawn over."""
    return any(not _failed(reading.record.data)
               and _value(measure.read(reading.record.data)) is not None
               for reading in readings)


def _failed(record: object) -> bool:
    """Whether a reading failed: its record carries an ``error`` that is not null —
    the key the engine writes for a check that raised, the seam for a record it
    refused, and every type for a reading that did not answer (ADR-0096 decision
    4). An ``error: null`` beside a reading that answered is no failure."""
    return isinstance(record, Mapping) and record.get("error") is not None


def _said(value: float | None, failed: bool, measure: Measure) -> str:
    """A reading's value as a reader reads it, or what stood in its place."""
    if failed:
        return "failed"
    return "no value" if value is None else measure.write(value)


def _value(value: object) -> float | None:
    """A reading's measure as a number the curve can draw, or ``None``: a boolean
    is not a number here, and neither is anything that is not finite."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value) if math.isfinite(value) else None


def _close(run: list[Point], runs: list[tuple[Point, ...]],
           dots: list[Point]) -> None:
    """End a stretch of line: two readings or more are a run, one is a dot."""
    if len(run) > 1:
        runs.append(tuple(run))
    elif run:
        dots.append(run[0])


def _scale(numbers: Sequence[float], unit: str,
           axis_to: float | None = None) -> tuple[float, float, float]:
    """The value axis: its low and high end and its step. It starts at zero —
    below it where a value is — and ends on a whole step past the highest value, or
    on the whole step that reaches ``axis_to`` where the measure declares one and no
    value is above it (ADR-0117): the declared end is where the axis reaches, never
    where a reading is cut off."""
    low, high = min(0.0, min(numbers)), max(0.0, max(numbers), axis_to or 0.0)
    if high <= low:
        high = low + 1.0
    step = _step(high - low, unit)
    low = math.floor(round(low / step, 9)) * step
    high = math.ceil(round(high / step, 9)) * step
    if high <= low:
        high = low + step
    return low, high, step


def _step(size: float, unit: str) -> float:
    """The step that divides ``size`` into about four: a span somebody would name
    for a span unit — 500 ms, 15m, 2h — a power of two of a unit for a size unit —
    256 MiB, 512 MiB, 1 GiB, so that a tick lands on a whole one (ADR-0096 decision
    3) — and 1, 2, 2.5 or 5 of a power of ten for every other number."""
    raw = size / _INTERVALS
    if unit in SIZE_UNITS:
        size_per = SIZE_UNITS[unit]
        bytes_step = 1
        while bytes_step < raw * size_per:
            bytes_step *= 2
        return bytes_step / size_per
    if unit in SPAN_UNITS:
        per = SPAN_UNITS[unit]
        for seconds in _SPAN_STEPS:
            step = round(seconds / per, 9)
            if step >= raw:
                return step
    magnitude = 10.0 ** math.floor(math.log10(raw))
    return next(multiple * magnitude for multiple in _MULTIPLES
                if multiple * magnitude >= raw)


def _hover(ordered: Sequence[Placed], values: Sequence[float | None],
           failures: Sequence[bool], measure: Measure,
           x_of: Callable[[datetime], float],
           times: Callable[[datetime], str]) -> tuple[Strip, ...]:
    """The plot, cut between each two neighbors' midpoints: the strip a reading
    owns under the pointer, and what it says there — its time as ``times`` writes
    it."""
    xs = [x_of(reading.at) for reading in ordered]
    edges = [LEFT, *((before + after) / 2 for before, after in pairwise(xs)), RIGHT]
    return tuple(
        Strip(edges[index], edges[index + 1] - edges[index],
              f"{times(reading.at)} · {_said(value, failed, measure)}")
        for index, (reading, value, failed) in enumerate(
            zip(ordered, values, failures, strict=True)))
