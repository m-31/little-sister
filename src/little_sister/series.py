"""The series: a subject's readings over time, and the store that keeps them.

A check run measures an object, and a reading that names its **subject** has a
history: its **series**, that subject's records over time, ordered by time and
bounded by retention (ADR-0087). This module is the seam every tier of that
history is written through — the store protocol — and the first tier behind it,
**memory**: the last *n* records of each series, oldest out, which the state layer
writes to a file of its own so that a restart keeps them.

Three things decide where a reading goes, and none of them is a new word:

* **Which series** is the check and the subject. A check is identified by its
  **type and its mount**, never by a node path alone, because one mount carries
  two checks by design — ``host-metrics`` and ``macos-memory`` share a host node
  (ADR-0015) and the container belongs to neither — and two measurements of a
  different shape must not land in one series. A reading with no subject has no
  series at all.
* **Whether it is a new record** there is the measurement's ``identity`` or its
  ``state``, and a reading with neither appends. An identity replaces the record
  of that identity already in the kept window wherever it stands, and that record
  keeps its place: the same finished run re-read on the next poll stays one
  record, updated if it changed. A state replaces the **newest** record where
  that one is in the same state and appends otherwise, so an unchanged state
  stays one record and a return to an earlier state is a new one, never a
  rewrite of the old.
* **How many** is the check's ``series_keep``, a count and only a count. A check
  that keeps none has no series: the engine never hands a store one of its
  readings, and a store refuses a count below one, so a series of length zero
  cannot exist.

**Two clocks, both kept.** ``observed_at`` is ours — when the engine took the
reading, the same instant its grading was handed. A record's own times are the
source's, converted to UTC where the check handed them over (ADR-0082) and never
re-stamped here. A series orders by the record's own time where it has one — its
top-level ``at`` — and by when the record was first observed where it has none;
records that tie keep the order they were handed back in.

**What stood there, beside what was read.** A kept reading carries the code and
the texts of the place the reading stood — the line it became, or the node it was
placed on — because a threshold that produced a code may have changed since, and
what *OK* meant that day cannot be graded back out of the record alone.

**What all of them weigh together is bounded.** Every kept reading is weighed as
the JSON the series file keeps it in, and a :meth:`MemoryStore.sweep` given a
ceiling evicts whole series — the one written to longest ago first — until what
the tier holds fits. The engine sweeps on every tick and says what it evicted.

The protocol is three operations — *add* a record, read the *window* of one
series, *sweep* by retention — and nothing about a check: a check hands back
measurements and writes to no store, so none of this is on the check-authoring
surface. What a check's measuring half reads of its own subjects (``Check.kept``,
ADR-0113) is the engine's *window* read, bound to the check's type and mount. The
memory tier answers one read more, the window **placed** — each record with the
instant its series orders it by — because that is what the node standing for a
subject draws and lists (ADR-0092), and the page reads this tier.
"""
from __future__ import annotations

import bisect
import itertools
import json
import threading
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, Protocol

from little_sister import instants
from little_sister.codes import StatusCode


@dataclass(frozen=True)
class SeriesKey:
    """Which series a reading joins: the check that took it — its type and its
    mount — and the subject it is of."""

    type_name: str
    mount: str
    subject: str


@dataclass(frozen=True)
class SeriesRecord:
    """One record as its series keeps it: what was read, when we looked, the event
    it is of, and what stood where the reading landed.

    ``data`` is the record exactly as the measurement's seam normalized it —
    plain JSON types, bounded by ``record_limit``, its typed times already in UTC
    — and nothing here writes to it. ``observed_at`` is when the engine took the
    reading, an aware instant held in UTC. ``identity`` and ``state`` are the
    measurement's, at most one of them set: both empty for a reading that is
    always a new one.

    ``code`` and ``texts`` are the reading as it **stood** (ADR-0087): the code and
    the text of the line the reading became, or the code and the texts of the node
    the engine placed it on — for a branch check whose own root grades nothing, what
    the check's own result rolls up to, beside whatever that root says. A reading
    among several that
    no line carried stood on that node too where it names the object its check
    declared; ``None`` and empty where it names another and stood nowhere.
    """

    data: Mapping[str, Any]
    observed_at: datetime
    identity: str = ""
    code: StatusCode | None = None
    texts: tuple[str, ...] = ()
    state: str = ""

    def __post_init__(self) -> None:
        if self.observed_at.tzinfo is None:
            raise ValueError(
                "a series record's observed_at must be an aware instant, not "
                f"{self.observed_at.isoformat()!r}")
        if self.identity and self.state:
            raise ValueError(
                "a series record is of an event or of a state, never both: "
                f"identity {self.identity!r}, state {self.state!r}")
        object.__setattr__(self, "observed_at", self.observed_at.astimezone(UTC))
        object.__setattr__(self, "texts", tuple(self.texts))

    @property
    def at(self) -> datetime | None:
        """The record's **own** time: its top-level ``at``, where the check gave
        one. A time nested deeper is a value the record carries — a file's
        modification, a run block's start — and not the instant the record is of,
        so it orders nothing."""
        value = self.data.get("at")
        if not isinstance(value, str):
            return None
        try:
            moment = datetime.fromisoformat(value)
        except ValueError:
            return None
        return moment if moment.tzinfo is not None else None


@dataclass(frozen=True)
class Placed:
    """A kept record where its series places it. ``at`` is the instant the series
    orders it by — the record's own top-level ``at`` where it has one, and
    otherwise when it was **first** observed, which a re-read that replaced it did
    not move — and it is where a curve draws the reading and the instant its row
    is listed under (ADR-0092 decision 4), so the two read the same readings in
    the same order."""

    record: SeriesRecord
    at: datetime


@dataclass(frozen=True)
class Swept:
    """What one sweep let go. ``trimmed`` counts the records beyond their series'
    count; ``dropped`` names the series whose check keeps none any more — a check
    gone from the configuration, or one whose ``series_keep`` became ``0``; and
    ``evicted`` names the series given up to stay within the ceiling, in the order
    they went, with ``evicted_bytes`` what they weighed together."""

    trimmed: int = 0
    dropped: tuple[SeriesKey, ...] = ()
    evicted: tuple[SeriesKey, ...] = ()
    evicted_bytes: int = 0


@dataclass(frozen=True)
class Usage:
    """What one check's series hold: how many series, how many readings in them,
    and what those readings weigh together, in bytes."""

    series: int
    readings: int
    bytes: int


class SeriesStore(Protocol):
    """The seam a series is written through and read back from (ADR-0087)."""

    def add(self, key: SeriesKey, record: SeriesRecord, *, keep: int) -> None:
        """Keep ``record`` in the series ``key``: replace the record of its
        identity where the kept window holds one, or the newest record where
        ``record`` names a state and that one is in the same state; append it
        otherwise; and then hold the series to ``keep`` records, the oldest out.
        A ``keep`` below one is the caller's error — a check that keeps none has
        no series to add to."""

    def window(self, key: SeriesKey) -> tuple[SeriesRecord, ...]:
        """The records the series ``key`` keeps, oldest first — empty where there
        is no such series."""

    def sweep(self, keep: Callable[[SeriesKey], int], *,
              ceiling: int | None = None) -> Swept:
        """Hold every series to the count ``keep`` answers for it now, the oldest
        out, and drop a series whose check keeps none; then, given a ``ceiling`` in
        bytes, evict whole series, the one written to longest ago first, until
        what is held fits under it. A store whose retention is its own business
        may leave the ceiling to the memory in front of it."""


@dataclass(frozen=True)
class _Kept:
    """A record in its place. Where it has no time of its own it stands where it
    was **first** observed — a record replaced by its identity or its state is
    updated in place, never moved to the end — and records that tie stand in the
    order they arrived. ``weight`` is what it costs, in the bytes of the JSON the
    series file keeps it as."""

    record: SeriesRecord
    first_observed: datetime
    arrival: int
    weight: int

    def order(self) -> tuple[datetime, int]:
        own = self.record.at
        return (own if own is not None else self.first_observed, self.arrival)


@dataclass
class _Series:
    """One series in memory: its window, oldest first; when it was last written
    to — the newest ``observed_at`` a reading brought it, which is what *oldest*
    means to the ceiling — and what its readings weigh together."""

    kept: list[_Kept] = field(default_factory=list)
    last_written: datetime | None = None
    bytes: int = 0

    def put(self, kept: _Kept) -> None:
        bisect.insort(self.kept, kept, key=_Kept.order)
        self.bytes += kept.weight
        written = kept.record.observed_at
        if self.last_written is None or written > self.last_written:
            self.last_written = written

    def hold(self, keep: int) -> tuple[int, int]:
        """Hold the window to ``keep`` records, the oldest out; answers how many
        went and what they weighed."""
        excess = len(self.kept) - keep
        if excess <= 0:
            return 0, 0
        freed = sum(kept.weight for kept in self.kept[:excess])
        del self.kept[:excess]
        self.bytes -= freed
        return excess, freed


class MemoryStore:
    """The memory tier: the last *n* records of every series, oldest out.

    One object for the process holding one window per series, because the series
    is the unit that has a bound, an order and records to replace; the check only
    says how many, on every :meth:`add`. It knows what everything it holds weighs,
    which is what the ceiling is measured against, and it is what the state layer
    writes to ``series.json.gz`` (:meth:`payload`) and reads back at startup
    (:meth:`restore`). Thread-safe: the engine adds from its pool's workers and
    sweeps from the scheduler, and a reader copies under the same lock.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._series: dict[SeriesKey, _Series] = {}
        self._arrivals = itertools.count()
        self._held = 0

    def add(self, key: SeriesKey, record: SeriesRecord, *, keep: int) -> None:
        if keep < 1:
            raise ValueError(
                f"a series keeps at least one record, not {keep}: a check that "
                f"keeps none has no series")
        with self._lock:
            series = self._series.setdefault(key, _Series())
            first_observed, arrival = record.observed_at, None
            index = _continued(series.kept, record)
            if index is not None:
                held = series.kept.pop(index)
                series.bytes -= held.weight
                self._held -= held.weight
                first_observed, arrival = held.first_observed, held.arrival
            if arrival is None:
                arrival = next(self._arrivals)
            kept = _Kept(record, first_observed, arrival,
                         _weight(record, first_observed))
            series.put(kept)
            self._held += kept.weight
            _count, freed = series.hold(keep)
            self._held -= freed

    def window(self, key: SeriesKey) -> tuple[SeriesRecord, ...]:
        with self._lock:
            series = self._series.get(key)
            return () if series is None else tuple(
                kept.record for kept in series.kept)

    def placed(self, key: SeriesKey) -> tuple[Placed, ...]:
        """The window of ``key`` with each record's place — what the node that
        stands for the subject draws and lists (ADR-0092). The same records in the
        same order as :meth:`window`; the place is the one thing this tier knows
        that a record does not carry, since when a record was first observed is
        kept beside it rather than in it."""
        with self._lock:
            series = self._series.get(key)
            return () if series is None else tuple(
                Placed(kept.record, kept.order()[0]) for kept in series.kept)

    def sweep(self, keep: Callable[[SeriesKey], int], *,
              ceiling: int | None = None) -> Swept:
        # The counts are asked outside the lock, so a `keep` that reads the store
        # cannot deadlock it; a series added between the two is swept next time.
        with self._lock:
            keys = list(self._series)
        counts = {key: keep(key) for key in keys}
        trimmed = 0
        dropped: list[SeriesKey] = []
        evicted: list[SeriesKey] = []
        evicted_bytes = 0
        with self._lock:
            for key, count in counts.items():
                series = self._series.get(key)
                if series is None:
                    continue
                if count < 1:
                    del self._series[key]
                    self._held -= series.bytes
                    dropped.append(key)
                    continue
                gone, freed = series.hold(count)
                trimmed += gone
                self._held -= freed
            if ceiling is not None and self._held > ceiling:
                # **Oldest** is the series written to longest ago: a subject that
                # stopped reporting — a deleted branch, a job nobody runs — goes
                # before any that still reports, and the tie between two written
                # at one instant is broken by the key, so a sweep is repeatable.
                for key in sorted(self._series, key=self._age_order):
                    if self._held <= ceiling:
                        break
                    series = self._series.pop(key)
                    self._held -= series.bytes
                    evicted.append(key)
                    evicted_bytes += series.bytes
        return Swept(trimmed, tuple(dropped), tuple(evicted), evicted_bytes)

    def _age_order(self, key: SeriesKey) -> tuple[datetime, str, str, str]:
        # Call only while holding the lock.
        written = self._series[key].last_written
        return (written if written is not None else _NEVER,
                key.type_name, key.mount, key.subject)

    def subjects(self, type_name: str, mount: str) -> tuple[str, ...]:
        """The subjects whose series the check of ``type_name`` on ``mount`` keeps,
        in order — what a view that finds a node's series through its checks
        reads (ADR-0097 decision 1)."""
        with self._lock:
            return tuple(sorted(key.subject for key in self._series
                                if key.type_name == type_name
                                and key.mount == mount))

    def held(self) -> int:
        """What every kept reading weighs together, in bytes — what the ceiling is
        measured against."""
        with self._lock:
            return self._held

    def usage(self) -> dict[tuple[str, str], Usage]:
        """What each check's series hold, keyed by the check's type and mount —
        the numbers a projection is made of."""
        found: dict[tuple[str, str], list[int]] = {}
        with self._lock:
            for key, series in self._series.items():
                numbers = found.setdefault((key.type_name, key.mount), [0, 0, 0])
                numbers[0] += 1
                numbers[1] += len(series.kept)
                numbers[2] += series.bytes
        return {check: Usage(*numbers) for check, numbers in found.items()}

    def payload(self) -> dict[str, Any]:
        """Every series as the state layer keeps it in ``series.json.gz``: copied
        under the lock, serialized outside it — the producer the layer calls on
        the scheduler tick. Series in key order and records in window order, so a
        state that did not change has the same content and is not written
        again."""
        with self._lock:
            held = [(key, list(series.kept))
                    for key, series in self._series.items()]
        held.sort(key=lambda item: (item[0].type_name, item[0].mount,
                                    item[0].subject))
        return {"series": [
            {"type": key.type_name, "mount": key.mount, "subject": key.subject,
             "records": [_record_payload(kept.record, kept.first_observed)
                         for kept in kept_records]}
            for key, kept_records in held]}

    def restore(self, payload: object) -> None:
        """Replace everything held with the series in ``payload`` — the file's, at
        startup, or an adopted copy's (ADR-0077). Read whole before anything is
        replaced: a payload of another shape raises :class:`ValueError` and the
        store keeps what it held. The retention of *this* configuration is applied
        by the next sweep, not here, since the file may be older than the
        configuration reading it."""
        restored: dict[SeriesKey, _Series] = {}
        held = 0
        for key, records in _parsed(payload).items():
            series = _Series()
            for record, first_observed in records:
                series.put(_Kept(record, first_observed, next(self._arrivals),
                                 _weight(record, first_observed)))
            restored[key] = series
            held += series.bytes
        with self._lock:
            self._series = restored
            self._held = held


def _continued(kept: list[_Kept], record: SeriesRecord) -> int | None:
    """The place in ``kept`` of the record that ``record`` continues, if any.

    An identity names an event, which recurs only as a re-read, so its record is
    found wherever it stands. A state recurs as a new spell, so only the
    **newest** record continues it: found anywhere, a return to an earlier state
    would rewrite that state's old record in its old place, the spell between
    would vanish, and with no time of its own the newest record would name a
    state the object has left. A record that names neither continues nothing.
    """
    if record.identity:
        return next((index for index, held in enumerate(kept)
                     if held.record.identity == record.identity), None)
    if record.state and kept and kept[-1].record.state == record.state:
        return len(kept) - 1
    return None


#: What stands for *never written* when series are put in age order — only ever
#: reached by a series that holds nothing, which :class:`MemoryStore` never keeps.
_NEVER = datetime.min.replace(tzinfo=UTC)


def _record_payload(record: SeriesRecord,
                    first_observed: datetime) -> dict[str, Any]:
    """One kept reading as the series file keeps it. ``state`` is written only
    where the reading names one, and ``first_observed_at`` only where a
    replacement moved ``observed_at`` past it, since it is what keeps such a
    record in its place across a restart."""
    item: dict[str, Any] = {
        "data": record.data,
        "observed_at": instants.stamp(record.observed_at),
        "identity": record.identity,
        "code": None if record.code is None else record.code.name,
        "texts": list(record.texts),
    }
    if record.state:
        item["state"] = record.state
    if first_observed != record.observed_at:
        item["first_observed_at"] = instants.stamp(first_observed)
    return item


def _weight(record: SeriesRecord, first_observed: datetime) -> int:
    """What one kept reading costs: the bytes of its JSON as the series file keeps
    it, spelled the way the seam weighs a record against ``record_limit``, so that
    the two measures cannot drift."""
    return len(json.dumps(_record_payload(record, first_observed))
               .encode("utf-8"))


def _parsed(payload: object) -> dict[SeriesKey, list[tuple[SeriesRecord, datetime]]]:
    """The series in a file's payload, or :class:`ValueError` naming what is
    wrong. Strict on purpose: the file is written by this module and nothing else,
    so a shape it does not recognize is a damaged file and not a dialect."""
    if not isinstance(payload, Mapping) or not isinstance(payload.get("series"),
                                                          list):
        raise ValueError("a series file is an object holding a 'series' list")
    parsed: dict[SeriesKey, list[tuple[SeriesRecord, datetime]]] = {}
    for index, item in enumerate(payload["series"]):
        where = f"series[{index}]"
        if not isinstance(item, Mapping):
            raise ValueError(f"{where} is not an object")
        names = [item.get(name) for name in ("type", "mount", "subject")]
        if not all(isinstance(name, str) for name in names) or not names[2]:
            raise ValueError(f"{where} does not name its type, mount and subject")
        key = SeriesKey(str(names[0]), str(names[1]), str(names[2]))
        if key in parsed:
            raise ValueError(f"{where} repeats a series already read")
        records = item.get("records")
        if not isinstance(records, list) or not records:
            raise ValueError(f"{where} holds no records")
        parsed[key] = [_parsed_record(raw, f"{where}.records[{number}]")
                       for number, raw in enumerate(records)]
    return parsed


def _parsed_record(raw: object, where: str) -> tuple[SeriesRecord, datetime]:
    if not isinstance(raw, Mapping):
        raise ValueError(f"{where} is not an object")
    data = raw.get("data")
    if not isinstance(data, Mapping):
        raise ValueError(f"{where}.data is not an object")
    observed_at = instants.instant(raw.get("observed_at"),
                                   f"{where}.observed_at")
    identity = raw.get("identity", "")
    if not isinstance(identity, str):
        raise ValueError(f"{where}.identity is not a string")
    state = raw.get("state", "")
    if not isinstance(state, str):
        raise ValueError(f"{where}.state is not a string")
    code_name = raw.get("code")
    if code_name is not None and (not isinstance(code_name, str)
                                  or code_name not in StatusCode.__members__):
        raise ValueError(f"{where}.code is not a status code: {code_name!r}")
    texts = raw.get("texts", [])
    if not isinstance(texts, list) or not all(isinstance(text, str)
                                              for text in texts):
        raise ValueError(f"{where}.texts is not a list of strings")
    first = raw.get("first_observed_at")
    first_observed = (observed_at if first is None
                      else instants.instant(first, f"{where}.first_observed_at"))
    code = None if code_name is None else StatusCode[code_name]
    return (SeriesRecord(dict(data), observed_at, identity, code, tuple(texts),
                         state),
            first_observed)
