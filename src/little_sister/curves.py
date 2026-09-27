"""A measure's curve over its subject's series: the geometry the node's page draws
(ADR-0092 decisions 4 and 5).

Pure arithmetic over the readings a series keeps. The page writes it as SVG, on the
server, with no script of its own; everything here is a number or a word that
drawing puts where it says.

**Where a reading goes.** On the time axis, at the instant its series places it —
its own ``at``, or when it was first observed (:class:`~little_sister.series.Placed`)
— to scale, so a night without readings is a night wide. On the value axis, to
scale from a baseline at zero, in the measure's unit. The axis spans the whole
kept window: ``series_keep`` is its one span.

**Where the line breaks, and what says why.** A reading whose measure has no value
— a null, a field the record does not have, which a projection reads as a null, or
anything that is not a number — breaks the line, and is **marked** at its instant
in a lane beneath the baseline: a failure is a reading, and it says the object did
not answer. It is never drawn as a zero, and the lane is below the axis so that it
cannot be read as one. Two neighboring readings further apart than the node's
freshness tolerance have a **hole** between them — a restart, a pause, a machine
asleep — and the line breaks there with no mark; one missed poll is not a hole, as
it does not make the node stale either. The line never crosses either: across them
there is nothing that was read.

**What it says in words.** Each reading's time and value where the pointer is —
the whole height of the plot between two readings' midpoints belongs to the nearer
one, so the pointer finds a date and never has to land on a two-pixel line — and a
summary beside the title. The readings table beneath carries every value too, so
nothing is only a tooltip. The times read in the configured timezone and
``time_format`` (ADR-0006), as every time the page shows does.
"""
from __future__ import annotations

import math
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import datetime
from itertools import pairwise

from little_sister.measures import SPAN_UNITS, Measure
from little_sister.series import Placed
from little_sister.spans import local_time

#: The drawing's size, in the user units the page shows it at one to one; it
#: scales down to fit a narrow card and never up, so its words keep their size.
WIDTH = 760
HEIGHT = 178
#: The plot, where the readings are drawn.
LEFT = 72.0
RIGHT = 744.0
TOP = 16.0
BOTTOM = 136.0
#: The lane a reading without a value is marked in: beneath the baseline, so a mark
#: can never be read as a value, and least of all as zero.
LANE_TOP = 142.0
LANE_BOTTOM = 152.0
#: Where the oldest and the newest time stand, and a free-text unit above the ticks.
TIME_BASELINE = 170.0
UNIT_BASELINE = 10.0

#: How many intervals the value axis aims at.
_INTERVALS = 4
#: The steps a span's axis takes, in seconds: each one a span somebody would name.
_SPAN_STEPS = (0.001, 0.002, 0.005, 0.01, 0.02, 0.05, 0.1, 0.2, 0.25, 0.5, 1, 2, 5,
               10, 15, 30, 60, 120, 300, 600, 900, 1800, 3600, 7200, 10800, 21600,
               43200, 86400, 172800, 604800)
#: The multiples a plain number's axis steps in, within each power of ten.
_MULTIPLES = (1, 2, 2.5, 5, 10)


@dataclass(frozen=True)
class Point:
    """A reading with a value, where it is drawn."""

    x: float
    y: float
    at: datetime
    value: float


@dataclass(frozen=True)
class Mark:
    """A reading without a value, marked at its instant in the lane."""

    x: float
    at: datetime


@dataclass(frozen=True)
class Tick:
    """One step of the value axis: where its gridline runs, and what it reads."""

    y: float
    text: str


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
    reading where it has a value. ``marks`` are the readings without one. The
    counts and the three values are the summary the title stands beside.
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
    newest: str
    lowest: str
    highest: str
    width: int = WIDTH
    height: int = HEIGHT
    left: float = LEFT
    right: float = RIGHT
    top: float = TOP
    bottom: float = BOTTOM
    lane_top: float = LANE_TOP
    lane_bottom: float = LANE_BOTTOM
    time_baseline: float = TIME_BASELINE
    unit_baseline: float = UNIT_BASELINE

    @property
    def paths(self) -> tuple[str, ...]:
        """Each run as the ``d`` of an SVG path."""
        return tuple("M" + " L".join(f"{point.x:.1f} {point.y:.1f}" for point in run)
                     for run in self.runs)


def draw(measure: Measure, readings: Sequence[Placed], *,
         tolerance: float | None) -> Curve:
    """``measure`` over ``readings`` — a series' window, each where its series
    places it — with a hole wherever two neighbors are further apart than
    ``tolerance`` seconds; ``None`` is a node that cannot go stale, which has none.
    """
    ordered = sorted(readings, key=lambda reading: reading.at)
    values = [_value(measure.read(reading.record.data)) for reading in ordered]
    numbers = [value for value in values if value is not None]
    if not ordered:
        return Curve(measure.label, measure.axis_unit, (), (), None, (), (), "",
                     "", (), 0, 0, 0, "", "", "")
    first_at, last_at = ordered[0].at, ordered[-1].at
    span = (last_at - first_at).total_seconds()

    def x_of(at: datetime) -> float:
        if span <= 0:
            return RIGHT
        return LEFT + (at - first_at).total_seconds() / span * (RIGHT - LEFT)

    low, high, step = _scale(numbers, measure.unit) if numbers else (0.0, 1.0, 1.0)

    def y_of(value: float) -> float:
        return BOTTOM - (value - low) / (high - low) * (BOTTOM - TOP)

    ticks: tuple[Tick, ...] = ()
    if numbers:
        steps = round((high - low) / step)
        ticks = tuple(Tick(y_of(value), measure.write(value, bare=True))
                      for value in (round(low + index * step, 9)
                                    for index in range(steps + 1)))

    runs: list[tuple[Point, ...]] = []
    dots: list[Point] = []
    marks: list[Mark] = []
    current: list[Point] = []
    holes = 0
    end: Point | None = None
    previous: Placed | None = None
    for reading, value in zip(ordered, values, strict=True):
        hole = (previous is not None and tolerance is not None
                and (reading.at - previous.at).total_seconds() > tolerance)
        if hole:
            holes += 1
        if hole or value is None:
            _close(current, runs, dots)
            current = []
        if value is None:
            marks.append(Mark(x_of(reading.at), reading.at))
            end = None
        else:
            end = Point(x_of(reading.at), y_of(value), reading.at, value)
            current.append(end)
        previous = reading
    _close(current, runs, dots)

    return Curve(
        label=measure.label, unit_label=measure.axis_unit, runs=tuple(runs),
        dots=tuple(dots), end=end, marks=tuple(marks), ticks=ticks,
        first=local_time(first_at), last=local_time(last_at),
        hover=_hover(ordered, values, measure, x_of),
        readings=len(ordered), unvalued=len(ordered) - len(numbers), holes=holes,
        newest=("no value" if values[-1] is None else measure.write(values[-1])),
        lowest=measure.write(min(numbers)) if numbers else "",
        highest=measure.write(max(numbers)) if numbers else "")


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


def _scale(numbers: Sequence[float], unit: str) -> tuple[float, float, float]:
    """The value axis: its low and high end and its step. It starts at zero —
    below it where a value is — and ends on a whole step past the highest value."""
    low, high = min(0.0, min(numbers)), max(0.0, max(numbers))
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
    for a span unit — 500 ms, 15m, 2h — and 1, 2, 2.5 or 5 of a power of ten for
    every other number."""
    raw = size / _INTERVALS
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
           measure: Measure, x_of: Callable[[datetime], float]) -> tuple[Strip, ...]:
    """The plot, cut between each two neighbors' midpoints: the strip a reading
    owns under the pointer, and what it says there."""
    xs = [x_of(reading.at) for reading in ordered]
    edges = [LEFT, *((before + after) / 2 for before, after in pairwise(xs)), RIGHT]
    return tuple(
        Strip(edges[index], edges[index + 1] - edges[index],
              f"{local_time(reading.at)} · "
              f"{'no value' if value is None else measure.write(value)}")
        for index, (reading, value) in enumerate(zip(ordered, values, strict=True)))
