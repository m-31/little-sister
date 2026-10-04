"""The engine's limits, what it measures against them as it runs, and the lines
that say so — the engine's own lines on the self-report seam (ADR-0072).

The rule behind every line here: **a limit the engine enforces is a line it can
show, and a limit it cannot compute is one it cannot observe either.** So each
line has three parts — a number that bounds it, a measurement the engine records
as it runs, and the sentence ``/little-sister`` carries while the measurement is
near or past the bound. Nothing here probes (ADR-0072 decision 2): the entry
count is a counter the tree keeps, the pool and the schedule are the engine's own
records read on the tick, and the reads of the process's own resident size — the
process asking the kernel about itself — are local, bounded and answered from what
the kernel already holds. Every line clears when its condition does, like every line
on the seam. The same figures stand on `/system`, in the engine's report and in the
log, and a run's line says what rose while it ran (ADR-0095).

The numbers are constants today, gathered in :class:`Limits` so that turning them
into settings, when a check can declare what it costs, is one construction site.
"""
from __future__ import annotations

import os
import sys
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass
from pathlib import Path

from little_sister.codes import StatusCode
from little_sister.logger import logger
from little_sister.reasons import Entry, slug
from little_sister.self_report import Held
from little_sister.spans import format_duration, format_span

#: Worker threads the pool is built with, unless a deployment says otherwise
#: (``max_workers`` in ``settings.yaml``). The pool is never larger than the
#: number of checks configured, so this is a ceiling and not a size.
DEFAULT_MAX_WORKERS = 8

#: How many reason entries the tree is built to hold, over every node. A default
#: rather than a share of memory: at the measured half kilobyte an entry, the
#: snapshot copied per poll and the envelope sent to every client bind long
#: before memory does, and both grow with this number. ``entry_limit`` in
#: ``settings.yaml`` overrides it.
ENTRY_LIMIT = 100_000

#: How heavy one entry's **record** may be, counted in the bytes of its JSON — the
#: form it costs in, since that is what every client is sent. A record is what a
#: check read about one subject, so the number is drawn where a composed record
#: ends and a payload dump begins: the first records assembled by hand come to a
#: few hundred bytes, while a single raw row from a provider's API is already
#: several kilobytes. Two kilobytes leaves the former room to grow and refuses the
#: latter, which is the line the limit exists to hold.
#:
#: ``record_limit`` in ``settings.yaml`` overrides it. That override costs one
#: thing worth knowing: the limit is enforced inside ``CheckResult`` and
#: ``Measurement``, which a check builds in its own ``measure()`` and ``grade()``,
#: so the seam reads the configuration **late** rather than importing it — a check
#: module that bound the settings at import time would bind them when a *plugin* is
#: imported.
RECORD_LIMIT = 2_048

#: The share of what the machine gives this process that the process may be
#: resident at before the line turns red — one gunicorn worker beside the OS on
#: the smallest instance the family runs on. ``memory_share`` in
#: ``settings.yaml`` overrides it.
MEMORY_SHARE = 0.5

#: What every series together may weigh (ADR-0087), counted as the record limit
#: counts one record: the bytes of the JSON the series file keeps each reading in.
#: A default rather than a share of memory, for the reason the entry limit is one —
#: something else binds first. Here it is the file: the state layer rewrites
#: ``series.json`` whole every interval a series changed, which with any check
#: keeping one is every interval, and a keeper carries each copy. Measured on the
#: device VM, eight mebibytes of kept readings are a file of about thirteen, written
#: in a few hundredths of a second on the scheduler's tick — the time is not what
#: binds, the copy a keeper sends every minute is. Past this the series written to
#: longest ago is evicted. ``series_limit`` in ``settings.yaml`` overrides it.
SERIES_LIMIT = 8 * 1024 ** 2

#: The share of either limit at which its line first stands, at WARN.
AMBER_SHARE = 0.8

#: How often the log carries the process's figures (ADR-0095 decision 3): on the
#: first tick past each mark of this many minutes of the clock the log is stamped
#: in, so the lines of two instances, or of one across a restart, stand at the same
#: minutes. `memory.sh`'s own background cadence, and about one line in a hundred of
#: a busy log. A divisor of sixty, so that every hour begins on a mark.
MEMORY_LINE_MINUTES = 10

#: The smallest rise a run's line, or the tick's own, says (ADR-0095 decisions 4
#: and 5) — of the size and of the peak alike. Below it a rise is pages; a fall is
#: never said, since it is some other run's memory given back; and the ten-minute
#: line carries the drift either way.
RISE_LOGGED = 1024 ** 2

#: How long a check may wait for a pool worker before the pool counts as
#: saturated. Ten poll intervals: a queue that drains within them is the ordinary
#: jitter of a busy pool, one that does not is a pool too small for its schedule.
POOL_WAIT_SECONDS = 10.0

#: How late a scheduler tick may come — beyond the poll interval — before it is a
#: line. A tick's own work is inside this: a slow sweep, a lock held by a large
#: snapshot, a state flush, or the machine starving the process all look alike
#: from here, and all of them are what the line exists to say.
LAG_SECONDS = 5.0

#: How long a late tick stays on the report. A single measurement that vanished
#: on the next tick would flicker the node WARN and back within a second, which is
#: two events and no information; a window makes the line say "recently".
LAG_MEMORY_SECONDS = 600.0

#: How long a sweep that evicted a series stays on the report. The lag line's
#: window, for the lag line's reason: a series evicted on one tick has shortened a
#: curve for good, and a line that vanished on the next tick would say so for one
#: second.
EVICTION_MEMORY_SECONDS = 600.0

#: Where a cgroup says how much memory this process may use, when one does — v2
#: first, then v1. Read once, at :meth:`Limits.from_machine`.
_CGROUP_LIMITS = (Path("/sys/fs/cgroup/memory.max"),
                  Path("/sys/fs/cgroup/memory/memory.limit_in_bytes"))


@dataclass(frozen=True)
class Limits:
    """The numbers the engine measures against. ``memory_limit`` is ``None`` where
    the machine could not say what it gives the process, and then there is no
    memory line — a limit that cannot be computed is not observed either."""

    entry_limit: int = ENTRY_LIMIT
    #: Bytes one entry's record may weigh — what a declaration is refused against
    #: at startup, and what the `CheckResult` seam refuses against at run time.
    record_limit: int = RECORD_LIMIT
    #: Bytes the process may be resident at before the line is red.
    memory_limit: int | None = None
    #: What the machine gives the process, in bytes — the number the memory
    #: line names beside its limit.
    machine_memory: int | None = None
    amber_share: float = AMBER_SHARE
    pool_wait_seconds: float = POOL_WAIT_SECONDS
    lag_seconds: float = LAG_SECONDS
    lag_memory_seconds: float = LAG_MEMORY_SECONDS
    #: Bytes every series together may hold before the oldest is evicted
    #: (ADR-0087), and what a projection is measured against.
    series_limit: int = SERIES_LIMIT
    eviction_memory_seconds: float = EVICTION_MEMORY_SECONDS

    @classmethod
    def from_machine(cls, *, entry_limit: int = ENTRY_LIMIT,
                     memory_share: float = MEMORY_SHARE,
                     record_limit: int = RECORD_LIMIT,
                     series_limit: int = SERIES_LIMIT) -> Limits:
        """The limits a deployment stated (``settings.yaml``, defaulting to the
        constants above), with the memory limit derived from this machine:
        ``memory_share`` of what it gives the process."""
        given = machine_memory()
        return cls(entry_limit=entry_limit, record_limit=record_limit,
                   memory_limit=int(given * memory_share) if given else None,
                   machine_memory=given, series_limit=series_limit)


@dataclass(frozen=True)
class Resident:
    """The process's resident size as its platform can say it (ADR-0095 decision
    1): the **peak**, the high-water mark ``getrusage`` keeps, and the size **now**
    where the kernel keeps one — Linux's ``/proc/self/statm`` — or ``None`` where it
    does not, as on macOS. The peak is never below the size now."""

    peak: int
    now: int | None = None

    @property
    def graded(self) -> int:
        """What the ``memory`` line grades: the size now where there is one, the
        peak where it is all there is. A line that graded a high-water mark could
        never clear once it had stood."""
        return self.peak if self.now is None else self.now


@dataclass(frozen=True)
class Waiting:
    """A check submitted to the pool and not yet started, and for how long."""

    path: str
    seconds: float


@dataclass(frozen=True)
class LateRun:
    """A run longer than its check's period — the one in flight, measured so far,
    or the last completed one."""

    path: str
    seconds: float
    frequency_seconds: int
    in_flight: bool


@dataclass(frozen=True)
class SeriesHeld:
    """What the series hold at a tick, against their ceiling, and what this
    configuration would need at today's estate — both in bytes, both measured and
    neither declared (ADR-0087).

    ``projection`` is, summed over every check that keeps a series, its
    ``series_keep`` times the series it holds times what one of its kept readings
    weighs on average; ``needs`` is each check's share of it, ``(path, bytes)``, so
    a line can name the largest. ``evicted`` names the series this tick's sweep gave
    up to stay within the ceiling, in the order they went, already worded, and
    ``evicted_bytes`` is what they weighed together.
    """

    held: int
    projection: int = 0
    needs: tuple[tuple[str, int], ...] = ()
    evicted: tuple[str, ...] = ()
    evicted_bytes: int = 0


@dataclass(frozen=True)
class MayRunLate:
    """A check whose ``timeout`` is longer than its ``frequency``: a configuration
    that can run late, which is warned about at load and never refused."""

    path: str
    timeout_seconds: float
    frequency_seconds: int


def machine_memory() -> int | None:
    """What this machine gives the process, in bytes: its physical memory, or the
    cgroup's memory limit where one is set and smaller — a container's limit is
    the number that kills the process, and the host's memory is not. ``None``
    where neither can be read."""
    known = [value for value in (_physical_memory(), _cgroup_memory_limit())
             if value]
    return min(known) if known else None


def _physical_memory() -> int | None:
    try:
        pages = os.sysconf("SC_PHYS_PAGES")
        page = os.sysconf("SC_PAGE_SIZE")
    except (AttributeError, OSError, ValueError):
        return None
    return pages * page if pages > 0 and page > 0 else None


def _cgroup_memory_limit() -> int | None:
    for path in _CGROUP_LIMITS:
        try:
            text = path.read_text(encoding="ascii").strip()
        except (OSError, ValueError):
            continue
        # v2 says ``max`` for no limit; anything that is not a number reads the
        # same way. v1 says a very large number, which the caller's ``min`` drops.
        return int(text) if text.isdigit() else None
    return None


def resident_size() -> Resident | None:
    """The process's resident size (ADR-0095 decision 1): the size now where the
    kernel keeps one, and the peak on every platform that has one — raised to the
    size now where the two, read a moment apart, disagree, and the size now itself
    where no peak can be read. ``None`` where nothing can say."""
    now = _statm_resident()
    peak = peak_resident()
    if peak is None:
        return None if now is None else Resident(peak=now, now=now)
    return Resident(peak=peak if now is None else max(peak, now), now=now)


def peak_resident() -> int | None:
    """The process's high-water mark as ``getrusage`` keeps it — in bytes on
    macOS, in kilobytes on every other platform — or ``None`` where the platform
    keeps none."""
    try:
        import resource
        peak = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    except (ImportError, OSError, ValueError):
        return None
    return peak if sys.platform == "darwin" else peak * 1024


def _statm_resident() -> int | None:
    """The process's resident size now, from ``/proc/self/statm`` where the
    kernel keeps one (Linux), or ``None``."""
    try:
        with open("/proc/self/statm", encoding="ascii") as handle:
            resident_pages = int(handle.read().split()[1])
        return resident_pages * os.sysconf("SC_PAGE_SIZE")
    except (OSError, ValueError, IndexError):
        return None


def may_run_late(checks: Iterable[object]) -> tuple[MayRunLate, ...]:
    """The checks among ``checks`` whose timeout is longer than their frequency.
    Duck-typed on the two fields: the check base pulls in every built-in type,
    and this module sits beneath the engine."""
    found: list[MayRunLate] = []
    for check in checks:
        timeout = float(getattr(check, "timeout_seconds", 0.0))
        frequency = int(getattr(check, "frequency_seconds", 0))
        if frequency > 0 and timeout > frequency:
            found.append(MayRunLate(str(getattr(check, "path", "")),
                                    timeout, frequency))
    return tuple(found)


#: How many checks a capacity sentence names before it says how many more there
#: are. A refusal is read once and has to carry enough to act on; two hundred
#: paths in one sentence carry less than five and a count do.
NAMED_IN_A_LINE = 5


@dataclass(frozen=True)
class Declared:
    """What one check declared it costs, from its own configuration.

    ``cost_seconds`` is worker time one run is expected to occupy and
    ``entries`` the reason entries it expects to hold in the tree; either may be
    ``None``, which is a check that did not say. Both are estimates and both
    decay, which is why the measurement stands beside them on ``/system``.
    """

    path: str
    frequency_seconds: int
    cost_seconds: float | None
    entries: int | None
    #: Bytes one of this check's records is expected to need, or ``None`` where
    #: the type did not say. Unlike the two above it is never summed: the limit it
    #: answers to bounds a single record, so the question is whether this type's
    #: largest fits, not what every type wants together. It is the **effective**
    #: size — what the type declared, raised to the record floor where it
    #: declared less (:func:`declared_costs`).
    record_bytes: int | None = None
    #: What the type itself declared, where the floor raised it; ``None`` where
    #: the effective size is the type's own number, or where it declared none.
    record_stated: int | None = None

    @property
    def workers(self) -> float:
        """The share of one worker thread this check's declared cost occupies at
        its frequency — its term in the utilization sum. Zero where it declared
        no cost, and where it has no period to divide by."""
        if self.cost_seconds is None or self.frequency_seconds <= 0:
            return 0.0
        return self.cost_seconds / self.frequency_seconds


def _declaration(check: object, name: str) -> float | None:
    """One declaration, read defensively.

    A type's estimate is code the library does not own (ADR-0049), so a
    declaration that raises, or answers something that is not a non-negative
    number, is a warning and an undeclared check — never a reason a monitoring
    process cannot start. What *is* declared and does not fit is refused; what
    cannot be read is not a declaration at all.
    """
    method = getattr(check, name, None)
    if not callable(method):
        return None
    path = str(getattr(check, "path", "?"))
    try:
        value = method()
    except Exception:
        logger.warning("check %s: %s() raised; treating it as undeclared",
                       path, name, exc_info=True)
        return None
    if value is None:
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        logger.warning("check %s: %s() answered %r, which is not a number; "
                       "treating it as undeclared", path, name, value)
        return None
    if not number >= 0:  # negative, and NaN, which no comparison makes true
        logger.warning("check %s: %s() answered %r, which is not a non-negative "
                       "number; treating it as undeclared", path, name, value)
        return None
    return number


def declared_costs(checks: Iterable[object], *,
                   record_floor: int = 0) -> tuple[Declared, ...]:
    """What each check declares it costs — the checks that declare anything, in
    configuration order. Duck-typed on the two methods, as :func:`may_run_late`
    is on the two fields: the check base pulls in every built-in type, and this
    module sits beneath the engine.

    ``record_floor`` is the most a record the **engine** writes for a check can
    weigh — the failure record of a check that raised (ADR-0086 decision 5) — and
    a declared record size is raised to it: any check may raise, so the largest
    record a declaring check can leave is never smaller. The engine passes its
    number in because this module sits beneath it. Only a type that **declared**
    a size is raised; one that declared none stays ``None``, because the library
    makes no claim a type did not make.
    """
    found: list[Declared] = []
    for check in checks:
        cost = _declaration(check, "expected_cost")
        entries = _declaration(check, "expected_entries")
        record = _declaration(check, "expected_record")
        if cost is None and entries is None and record is None:
            continue
        stated = None if record is None else int(record)
        effective = None if stated is None else max(stated, record_floor)
        found.append(Declared(str(getattr(check, "path", "")),
                              int(getattr(check, "frequency_seconds", 0)),
                              cost, None if entries is None else int(entries),
                              effective,
                              stated if stated != effective else None))
    return tuple(found)


@dataclass(frozen=True)
class Capacity:
    """The sum of what the configured checks declared, against the two limits
    they have to fit inside: the worker threads this engine runs and the entries
    the tree is built to hold.

    Only what is **declared** is summed. A check that says nothing contributes
    nothing, so the sums are a lower bound — which is exactly what a refusal can
    be built on: a configuration whose declared part alone does not fit cannot
    fit at all. What the sums cannot do is promise that a silent configuration
    does fit, and nothing here claims they do.
    """

    declared: tuple[Declared, ...]
    max_workers: int
    entry_limit: int
    #: The per-record bound declarations are **compared** against, one check at a
    #: time. There is no sum here on purpose: a record limit bounds one record, so
    #: adding two types' declarations together would answer a question nobody asked.
    record_limit: int = RECORD_LIMIT
    amber_share: float = AMBER_SHARE

    @property
    def workers(self) -> float:
        """Worker threads' worth of run time the declared checks want: the sum of
        each one's cost over its period (the utilization of a set of periodic
        tasks, applied loosely — these checks are I/O-bound and overlap)."""
        return sum(item.workers for item in self.declared)

    @property
    def entries(self) -> int:
        """Reason entries the declared checks expect to hold, together."""
        return sum(item.entries or 0 for item in self.declared)

    @property
    def over_record(self) -> tuple[Declared, ...]:
        """The checks declaring a record the limit cannot hold."""
        return tuple(item for item in self.declared
                     if item.record_bytes is not None
                     and item.record_bytes > self.record_limit)

    @property
    def near_record(self) -> tuple[Declared, ...]:
        """The checks declaring a record that fits but is close to not fitting."""
        return tuple(item for item in self.declared
                     if item.record_bytes is not None
                     and (self.record_limit * self.amber_share
                          <= item.record_bytes <= self.record_limit))

    def refusals(self) -> tuple[str, ...]:
        """What cannot be served, one sentence per limit, naming the checks.
        Empty when everything declared fits."""
        said: list[str] = []
        if self.workers > self.max_workers:
            said.append(
                f"the configured checks declare {self.workers:.1f} worker "
                f"threads' worth of run time, past the {self.max_workers} this "
                f"engine runs: {self._worst_cost()}")
        if self.entries > self.entry_limit:
            said.append(
                f"the configured checks declare {self.entries:,} reason entries, "
                f"past the limit of {self.entry_limit:,}: {self._worst_entries()}")
        if over := self.over_record:
            # Named one by one rather than summed: each of these is a type whose
            # every record would be refused at the seam on its first run, and
            # which one it is, is the whole of what an operator can act on —
            # by raising `record_limit`, or by not installing that type.
            said.append(
                f"a declared record does not fit the {self.record_limit:,}-byte "
                f"limit this deployment allows: {self._worst_record(over)}")
        return tuple(said)

    def warnings(self) -> tuple[tuple[str, str], ...]:
        """What fits but is close to not fitting — at or above
        :attr:`amber_share` of a limit and inside it — as ``(limit, sentence)``,
        the limit being ``threads`` or ``entries`` so a caller can address the
        line without reading the sentence. Empty otherwise, and empty for a limit
        that is already refused: a refusal is the louder half of the same
        sentence."""
        said: list[tuple[str, str]] = []
        if self.max_workers * self.amber_share <= self.workers <= self.max_workers:
            said.append(("threads",
                         f"the configured checks declare {self.workers:.1f} of the "
                         f"{self.max_workers} worker threads this engine runs "
                         f"({_percent(self.workers, self.max_workers)}): "
                         f"{self._worst_cost()}"))
        if self.entry_limit * self.amber_share <= self.entries <= self.entry_limit:
            said.append(("entries",
                         f"the configured checks declare {self.entries:,} reason "
                         f"entries, {_percent(self.entries, self.entry_limit)} of "
                         f"the limit of {self.entry_limit:,}: "
                         f"{self._worst_entries()}"))
        if near := self.near_record:
            said.append(("record",
                         f"a declared record is close to the "
                         f"{self.record_limit:,}-byte limit: "
                         f"{self._worst_record(near)}"))
        return tuple(said)

    def _worst_cost(self) -> str:
        return _named([
            (item.workers,
             f"{_plain(item.path)} {item.workers:.1f} "
             f"({format_span(item.cost_seconds or 0.0)} every "
             f"{format_duration(item.frequency_seconds)})")
            for item in self.declared if item.cost_seconds is not None])

    def _worst_record(self, items: Sequence[Declared]) -> str:
        return _named([(float(item.record_bytes or 0),
                        f"{_plain(item.path)} {item.record_bytes:,} bytes")
                       for item in items])

    def _worst_entries(self) -> str:
        return _named([(float(item.entries or 0),
                        f"{_plain(item.path)} {item.entries:,}")
                       for item in self.declared if item.entries is not None])


def capacity(checks: Iterable[object], *, max_workers: int,
             limits: Limits, record_floor: int) -> Capacity:
    """What the configured checks declared, against ``max_workers`` — the pool
    the engine will actually run, not the ceiling a deployment wrote down — and
    against the entry limit. ``record_floor`` is required rather than defaulted:
    it is the engine's failure-record maximum, and a caller that forgot it would
    compare declarations the engine itself can exceed."""
    return Capacity(declared_costs(checks, record_floor=record_floor),
                    max_workers=max_workers,
                    entry_limit=limits.entry_limit,
                    record_limit=limits.record_limit,
                    amber_share=limits.amber_share)


def _named(items: Sequence[tuple[float, str]]) -> str:
    """The largest contributors, worst first, capped at
    :data:`NAMED_IN_A_LINE` with a count for the rest."""
    ordered = [text for _weight, text in sorted(items, key=lambda pair: -pair[0])]
    shown = ordered[:NAMED_IN_A_LINE]
    rest = len(ordered) - len(shown)
    if rest > 0:
        shown.append(f"and {rest} more")
    return ", ".join(shown)


class EngineReport:
    """What the engine has recorded about itself, and the lines that say so.

    The engine calls :meth:`observe` once per scheduler tick with what its own
    records show — the tree's entry count, the checks waiting for a worker, the
    runs that outgrew their period — and this object measures the one thing the
    engine does not record, the resident size, and keeps what needs remembering
    between ticks: when the last tick was, so a late one can be seen, and the
    late ticks of the last :data:`LAG_MEMORY_SECONDS`. :meth:`lines` then reads
    that record into entries; it touches nothing else.
    """

    def __init__(self, checks: Iterable[object], *, workers: int,
                 poll_interval: float, limits: Limits,
                 capacity: Capacity | None = None,
                 resident: Callable[[], Resident | None] = resident_size) -> None:
        self._may_run_late = may_run_late(checks)
        self._capacity = capacity
        self._workers = max(1, workers)
        self._poll_interval = poll_interval
        self._limits = limits
        self._resident = resident
        self._last_tick: float | None = None
        #: The late ticks still inside the window — a held record (ADR-0072), so a
        #: late tick is logged and recorded in one call and the line is written
        #: from the worst inside the window.
        self._lag = Held(limits.lag_memory_seconds)
        #: The sweeps that evicted a series, held for their window (ADR-0087):
        #: an eviction has shortened a curve for good, so the line says
        #: *recently* rather than *this second*.
        self._evictions = Held(limits.eviction_memory_seconds)
        self._entries = 0
        self._memory: Resident | None = None
        self._series: SeriesHeld | None = None
        self._waiting: tuple[Waiting, ...] = ()
        self._late: tuple[LateRun, ...] = ()

    @property
    def limits(self) -> Limits:
        return self._limits

    @property
    def may_run_late(self) -> tuple[MayRunLate, ...]:
        """The checks that were warned about at load."""
        return self._may_run_late

    @property
    def capacity(self) -> Capacity | None:
        """What the configured checks declared they cost, summed at load, or
        ``None`` where nothing did the arithmetic."""
        return self._capacity

    @property
    def series(self) -> SeriesHeld | None:
        """What the series held at the last tick, and what this configuration
        would need at that tick's estate — ``None`` before the first tick."""
        return self._series

    @property
    def memory(self) -> Resident | None:
        """What the process held at the last tick — ``None`` before the first,
        and where nothing could say."""
        return self._memory

    def memory_figures(self, resident: Resident | None) -> str | None:
        """The log's memory line after its prefix (ADR-0095 decision 3): the
        process's figures as ``resident`` gives them, then what the series hold and
        the tree's entry count as the last tick recorded them — the card's figures in
        one line. ``None`` where nothing can say what the process holds."""
        if resident is None:
            return None
        held = self._series.held if self._series is not None else 0
        entries = self._entries
        noun = "entry" if entries == 1 else "entries"
        return (f"{resident_text(resident, self._limits)}; the series hold "
                f"{format_weight(held)}, the tree {entries:,} {noun}")

    def observe(self, now: float, *, entries: int, waiting: Sequence[Waiting],
                late: Sequence[LateRun], series: SeriesHeld | None = None) -> None:
        """Record one tick: ``now`` is the engine's clock at the tick, the rest is
        what the engine's own records show at that moment — ``series`` what the
        series hold after this tick's sweep, and what it evicted."""
        if self._last_tick is not None:
            lag = now - self._last_tick - self._poll_interval
            if lag > self._limits.lag_seconds:
                self._lag.see("lag", self._lag_text(lag), measure=lag, now=now)
        self._last_tick = now
        self._lag.prune(now)
        if series is not None and series.evicted:
            self._evictions.see("series", self._eviction_text(series),
                                code=StatusCode.ERROR,
                                measure=float(series.evicted_bytes), now=now)
        self._evictions.prune(now)
        self._entries = entries
        self._memory = self._resident()
        self._series = series
        self._waiting = tuple(waiting)
        self._late = tuple(late)

    def _eviction_text(self, series: SeriesHeld) -> str:
        """What one sweep that evicted says — the line's sentence while it is the
        latest inside the window, and the log entry for every one."""
        count = len(series.evicted)
        named = list(series.evicted[:NAMED_IN_A_LINE])
        if count > len(named):
            named.append(f"and {count - len(named)} more")
        which = ("the series written to longest ago was" if count == 1 else
                 f"{count} series were, the one written to longest ago first")
        return (f"the series outgrew their ceiling of "
                f"{format_weight(self._limits.series_limit)}: {which} evicted "
                f"({format_weight(series.evicted_bytes)}) — {', '.join(named)} — so "
                f"their curves are shortened")

    def _lag_text(self, lag: float) -> str:
        """What one late tick says — the sentence the line carries for the worst
        tick inside the window, and the log entry for every one."""
        return (f"the scheduler came late within the last "
                f"{format_span(self._limits.lag_memory_seconds)}: a tick came "
                f"{format_span(lag + self._poll_interval)} after the one before, "
                f"against an interval of "
                f"{format_duration(max(1, round(self._poll_interval)))}")

    def lines(self) -> tuple[Entry, ...]:
        """The engine's own lines, from the record and nothing else: each with a
        stable slug of its own on the engine's node, `/little-sister/engine` —
        the path carries the engine's name, not the slug (ADR-0072 decision 4,
        ADR-0076 decision 3) — coded where it claims something and uncoded where
        it only informs."""
        limits = self._limits
        lines: list[Entry] = []
        entries, entry_limit = self._entries, limits.entry_limit
        if entries >= entry_limit:
            lines.append(Entry("entries", f"the tree holds {entries:,} entries, past "
                                          f"its limit of {entry_limit:,}",
                               code=StatusCode.ERROR))
        elif entries >= entry_limit * limits.amber_share:
            lines.append(Entry("entries", f"the tree holds {entries:,} entries, "
                                          f"{_percent(entries, entry_limit)} of its "
                                          f"limit of {entry_limit:,}",
                               code=StatusCode.WARN))
        memory, memory_limit = self._memory, limits.memory_limit
        if memory is not None and memory_limit:
            what = "peak resident size" if memory.now is None else "resident size"
            size = memory.graded
            given = (f" (of the {format_size(limits.machine_memory)} the machine "
                     f"gives the process)" if limits.machine_memory else "")
            if size >= memory_limit:
                lines.append(Entry("memory", f"{what} {format_size(size)}, past "
                                             f"the limit of "
                                             f"{format_size(memory_limit)}{given}",
                                   code=StatusCode.ERROR))
            elif size >= memory_limit * limits.amber_share:
                lines.append(Entry("memory", f"{what} {format_size(size)}, "
                                             f"{_percent(size, memory_limit)} "
                                             f"of the limit of "
                                             f"{format_size(memory_limit)}{given}",
                                   code=StatusCode.WARN))
        lines.extend(self._series_lines())
        if self._waiting:
            longest = max(item.seconds for item in self._waiting)
            if longest > limits.pool_wait_seconds:
                count = len(self._waiting)
                checks = "1 check is" if count == 1 else f"{count} checks are"
                workers = ("its 1 worker" if self._workers == 1
                           else f"one of its {self._workers} workers")
                lines.append(Entry(
                    "pool",
                    f"the pool is saturated: {checks} waiting for {workers}, the "
                    f"longest for {format_span(longest)}",
                    code=StatusCode.WARN))
        worst = self._lag.worst("lag", now=self._last_tick)
        if worst is not None:
            lines.append(Entry("lag", worst.text, code=StatusCode.WARN))
        for run in self._late:
            verb = ("has been running for" if run.in_flight else "ran for")
            lines.append(Entry(
                f"late.{slug(run.path)}",
                f"{_plain(run.path)} {verb} {format_span(run.seconds)}, longer than "
                f"its frequency of {format_duration(run.frequency_seconds)} — it "
                f"runs late",
                code=StatusCode.WARN))
        return tuple(lines)

    def _series_lines(self) -> list[Entry]:
        """The ceiling's two lines (ADR-0087). ``series`` is what the series
        hold: ERROR while a sweep inside the window has evicted — curves are being
        shortened now — and WARN from the amber share of the ceiling. And
        ``series.projection`` is what this configuration would need at today's
        estate: WARN when that is past the ceiling, on the first tick the checks'
        series exist, long before a slowly filling series reaches it."""
        limits, series = self._limits, self._series
        ceiling = limits.series_limit
        lines: list[Entry] = []
        evicted = self._evictions.latest("series", now=self._last_tick)
        if evicted is not None:
            seen = self._evictions.count("series", now=self._last_tick)
            text = evicted.text
            if seen > 1:
                window = format_duration(
                    max(1, round(self._evictions.hold_seconds)))
                text = f"{text} — {seen} times in the last {window}"
            lines.append(Entry("series", text, code=StatusCode.ERROR))
        elif series is not None and series.held >= ceiling * limits.amber_share:
            lines.append(Entry("series",
                               f"the series hold {format_weight(series.held)}, "
                               f"{_percent(series.held, ceiling)} of their "
                               f"ceiling of {format_weight(ceiling)}",
                               code=StatusCode.WARN))
        if series is not None and series.projection > ceiling:
            largest = _named([(float(need), f"{_plain(path)} {format_weight(need)}")
                              for path, need in series.needs])
            lines.append(Entry(
                "series.projection",
                f"this configuration cannot be honored at this estate: its "
                f"series would need {format_weight(series.projection)}, past their "
                f"ceiling of {format_weight(ceiling)}: {largest}",
                code=StatusCode.WARN))
        return lines

    def report(self) -> str:
        """What the engine **knows** about its configuration and says as a fact,
        not a claim — the engine child's `report` (ADR-0044 decision 6, ADR-0076):
        a check whose timeout is longer than its frequency *may* run late, and a
        declared load close to a limit *may* not fit. Neither is a line: a
        declaration is about what *will* happen, and the coded line for what did
        is `late.<check>` or `entries` above — a configuration that fits must not
        make the node amber for the life of the process. Markdown; ``""`` where
        there is nothing to say."""
        facts: list[str] = []
        for check in self._may_run_late:
            facts.append(
                f"- {_plain(check.path)} may run late: its timeout of "
                f"{format_duration(int(check.timeout_seconds))} is longer than its "
                f"frequency of {format_duration(check.frequency_seconds)}")
        if self._capacity is not None:
            for _limit, said in self._capacity.warnings():
                facts.append(f"- {_plain(said)}")
        series = self._series
        if series is not None and (series.held or series.projection):
            facts.append(
                f"- the series hold {format_weight(series.held)} of their ceiling of "
                f"{format_weight(self._limits.series_limit)}; at today's estate this "
                f"configuration would need {format_weight(series.projection)}")
        # The process's own figures, beside the series' (ADR-0095 decision 2): a
        # fact every tick, in the `memory` line's words, and never a line — below
        # the amber share they claim nothing.
        if self._memory is not None:
            facts.append(
                f"- {resident_text(self._memory, self._limits, machine=True)}")
        return "\n".join(facts)


def _percent(part: float, whole: float) -> str:
    return f"{round(100 * part / whole)} %"


def format_weight(size: int) -> str:
    """A weight in bytes at the resolution a series line needs — from a few
    hundred bytes, a test's ceiling, to the mebibytes a deployment's is, and since a
    curve writes its sizes through it too, the tebibytes a volume holds (ADR-0096
    decision 3). Named without an underscore for the system page's `weight`
    filter, which writes the figures the engine's own lines write: one figure
    spelled two ways is two figures to a reader comparing them."""
    if size < 1024:
        return f"{size:,} B"
    if size < 1024 ** 2:
        return f"{size / 1024:,.1f} KiB"
    if size < 1024 ** 3:
        return f"{size / 1024 ** 2:,.1f} MiB"
    if size < 1024 ** 4:
        return f"{size / 1024 ** 3:,.1f} GiB"
    return f"{size / 1024 ** 4:,.1f} TiB"


def format_size(size: int | None) -> str:
    """A process's size in binary units, at the resolution a memory line needs:
    ``312 MiB``, ``8.0 GiB``. Named for the system page's `size` filter, which
    writes the figures the engine's `memory` line writes — one figure spelled two
    ways is two figures to a reader comparing them."""
    if size is None:
        return "?"
    if size < 1024 ** 3:
        return f"{size / 1024 ** 2:,.0f} MiB"
    return f"{size / 1024 ** 3:,.1f} GiB"


def resident_text(resident: Resident, limits: Limits, *,
                  machine: bool = False) -> str:
    """The process's figures as every surface names them (ADR-0095): ``resident
    size 312 MiB, peak 369 MiB`` where the platform has both, ``peak resident size
    369 MiB`` where the peak is all it has — then ``of a limit of 8.0 GiB`` where the
    machine said what it gives the process, and, with ``machine``, what that is.
    The `memory` line's own words, so that a figure reads the same wherever it
    stands."""
    if resident.now is None:
        said = f"peak resident size {format_size(resident.peak)}"
    else:
        said = (f"resident size {format_size(resident.now)}, "
                f"peak {format_size(resident.peak)}")
    if limits.memory_limit:
        said += f", of a limit of {format_size(limits.memory_limit)}"
        if machine and limits.machine_memory:
            said += (f" (of the {format_size(limits.machine_memory)} the machine "
                     f"gives the process)")
    return said


def rise_text(size_rise: int, peak_rise: int, beside: Sequence[str], *,
              during: str) -> str:
    """What rose while something was in flight (ADR-0095 decisions 4 and 5):
    ``resident +38.2 MiB, peak +12.1 MiB while it ran, beside /a and /b``. The
    size's rise and the peak's, each only from :data:`RISE_LOGGED` — a fall is
    never said — and ``""`` where neither reaches it. The rises are the process's,
    never a run's, so ``during`` says what was measured and ``beside`` names every
    run that was in flight at any point of it, five and a count."""
    rose = [f"{name} +{format_weight(rise)}"
            for name, rise in (("resident", size_rise), ("peak", peak_rise))
            if rise >= RISE_LOGGED]
    if not rose:
        return ""
    said = f"{', '.join(rose)} {during}"
    if beside:
        said += f", beside {_listed(beside)}"
    return said


def _listed(names: Sequence[str]) -> str:
    """Names in order, joined as prose — ``/a``, ``/a and /b``, ``/a, /b and
    /c`` — capped at :data:`NAMED_IN_A_LINE` with a count for the rest."""
    ordered = sorted(names)
    shown = ordered[:NAMED_IN_A_LINE]
    rest = len(ordered) - len(shown)
    if rest:
        return f"{', '.join(shown)} and {rest} more"
    if len(shown) == 1:
        return shown[0]
    return f"{', '.join(shown[:-1])} and {shown[-1]}"


def _plain(text: str) -> str:
    # Imported here, not at the top: the check helpers pull in every built-in
    # type, and this module sits beneath the engine (as self_report does it).
    from little_sister.checks import plain
    return plain(text)
