"""The pins (ADR-0141): what a person set on a node or on one of its lines, one file of
the state layer.

A **pin** is one thing with a kind (ADR-0141 decision 1): a target — a node by its
path, or one of its lines by the path and the line's slug (ADR-0036) — a note, who set
it and when and who first did, its end where it has one, an id of its own and the token
a form carries back. What differs by kind is what it does at the node's boundary, what
ends it and what it is bound to. This release knows four kinds: **maintenance**
(ADR-0014), down on purpose and bound to a window in time; **seen** (ADR-0142), a
failure accepted until it changes and bound to the occurrence it was set on;
**silenced** (ADR-0144), a failure that flaps held at a level until a deadline, and
bound to the two; and **done** (ADR-0146), an event looked into and over, its line
showing OK, bound to the occurrence it closed and to nothing else. The last three are
the **acknowledgments**, of which a part holds one at a time beside its maintenance.

The tree holds the pins and writes them through this store on every change, so a
restart restores them. The file is ``var/state/pins.json`` (ADR-0071), written through,
atomically, by the layer's own discipline: a list of pins, each with its target
beside it. It took the place of ``maintenance.json`` with a **clean break**: the old
file is not read, and the state layer names it once at the first start that finds it
without its successor (``state.RETIRED_FILES``). This module knows the file's *shape*
and nothing about where or how it is written.

**A file this release cannot read takes every pin with it** — a shape it does not
know, a time that is no instant, a pin without an id or a kind, two pins of one kind on
one place, two acknowledgments on one place, or a maintenance entry's schedule outside
the subset (ADR-0150) — which fails toward alarming, and the layer reports it. **A pin
of a kind this release does not know is skipped and named once** (ADR-0032 rule 7): an
older standby adopting a newer holder's file keeps every pin it understands, and its
next write drops the rest.

**A maintenance entry holds its schedule** (ADR-0150): the windows it covers as RFC 5545
text, its holiday list (``not_on``) and the windows changed alone (``changed``), and no
``expires_at``, so that no older release takes a series for one pin in force until its
last date — it refuses the file whole instead. **One in the shape before schedules is
dropped, and nothing says so**: a clean break, with no line at the start and no import,
which the release's notes say once (#35's note, the landings' corrections).
"""
from __future__ import annotations

import secrets
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import TYPE_CHECKING, Any, NamedTuple

from little_sister import instants, self_report, values
from little_sister.codes import StatusCode
from little_sister.reasons import plain
from little_sister.schedule import Schedule, last_end
from little_sister.state import PINS_FILE, StateLayer

if TYPE_CHECKING:
    from little_sister.tree import StatusTree

#: The kind a maintenance pin is (ADR-0014): down on purpose, painted blue, counting
#: nothing, ending by the clock. Its name is the word every surface says it in, the
#: value ``contribution.by`` carries and the permission its acts ask for.
MAINTENANCE = "maintenance"

#: The kind that accepts a failure as it stands (ADR-0142): its part keeps its true
#: color under a ringed check and counts as OK above, until it changes — a recovery, a
#: worsening, a new occurrence, the part no longer reported, the end it may be given,
#: or a person's hand. Its name is its word on every surface, the value
#: ``contribution.by`` carries and the permission its act asks for.
SEEN = "seen"

#: The kind that holds a failure that flaps (ADR-0144): its part keeps its true color
#: and counts above at most at the level the silence holds it at — ``OK``, or ``WARN``
#: — through every recovery, until its deadline, which it always has, or a person's
#: hand. Its name is its word on every surface, the value ``contribution.by`` carries
#: and the permission its act asks for.
SILENCED = "silenced"

#: The kind that closes an event looked into and over (ADR-0146): a line's failed run
#: or held error, the line showing OK with the failure it closed beside it and
#: counting as OK above, until the line reads anything other than that failure — a
#: new occurrence, the same one recovered or worse, or no line at all — or a person's
#: hand; never by the clock. Set only on a line whose failure has an occurrence of
#: its own. Its name is its word on every surface, the value ``contribution.by``
#: carries and the permission its act asks for.
DONE = "done"

#: The levels a silence holds its part at above it (ADR-0144): counting as ``OK``, or
#: at most as ``WARN``.
SILENCE_LEVELS: frozenset[StatusCode] = frozenset({StatusCode.OK, StatusCode.WARN})

#: The kinds that accept, silence or close a failure (ADR-0142, ADR-0144, ADR-0146),
#: of which a part holds **one at a time** beside any maintenance.
ACKNOWLEDGMENTS: frozenset[str] = frozenset({DONE, SEEN, SILENCED})

#: Every kind of pin this release knows. A pin of any other kind in the file is
#: skipped and named once (ADR-0032 rule 7).
KINDS: frozenset[str] = frozenset({MAINTENANCE, *ACKNOWLEDGMENTS})

#: What a maintenance pin set without a note holds as its note: the honest
#: placeholder, which no surface shows as a note and the notes' history never takes
#: (ADR-0047). An acknowledgment set without one holds none.
NO_NOTE = "maintenance"


def _status(said: str, key: str) -> StatusCode | None:
    """The status a pin's file says under ``key``, or ``None`` where it says none.

    :raises ValueError: it says one that is no status."""
    try:
        return StatusCode[said] if said else None
    except KeyError:
        raise ValueError(f"a pin's {key} {said!r}, which is no status") from None


@dataclass(frozen=True)
class Changed:
    """One window of a maintenance entry changed alone (#35's note, decision 2): the
    ``start`` that keys it, as iCalendar's ``RECURRENCE-ID`` keys one instance, the
    ``end`` it was changed to, the words why (``note``), and who changed it and when —
    what an extension and an early end write, three instants in UTC."""

    start: datetime
    end: datetime
    note: str = ""
    by: str = ""
    at: datetime | None = None

    def to_dict(self) -> dict[str, str]:
        said = {"start": instants.stamp(self.start), "end": instants.stamp(self.end)}
        if self.note:
            said["note"] = self.note
        if self.by:
            said["by"] = self.by
        if self.at is not None:
            said["at"] = instants.stamp(self.at)
        return said

    @classmethod
    def from_dict(cls, data: object) -> Changed:
        if not isinstance(data, Mapping):
            raise ValueError("a window changed alone that is not a mapping")
        at = data.get("at")
        return cls(start=instants.instant(data.get("start"),
                                          "a changed window's start"),
                   end=instants.instant(data.get("end"), "a changed window's end"),
                   note=values.text(data, "note"), by=values.text(data, "by"),
                   at=None if at is None
                   else instants.instant(at, "a changed window's at"))


def _zone() -> str:
    """The configured zone (ADR-0120 decision 7), which a window set with an end alone
    is written in — read where it is asked for, the configuration importing what imports
    this module."""
    from little_sister.config import config as settings
    return settings.timezone


def _schedule_end(schedule: Schedule, changed: Iterable[Changed]) -> datetime:
    """Where ``schedule``'s last window ends, as written — a one-off's end, or the last
    of a series' windows, each changed alone where ``changed`` says, and no holiday
    list applied: the tree's windows apply it.

    :raises ValueError: the schedule has no window."""
    ends = {each.start: each.end for each in changed}
    end = last_end(schedule.windows(changed=ends))
    if end is None:
        raise ValueError("a maintenance pin whose schedule has no window")
    return end


def _same_schedule(one: Schedule | None, other: Schedule | None) -> bool:
    """Whether two schedules say the same: one window each from the same start to the
    same end, or every part alike — read as instants, so that a one-off's start
    written as a wall time in another zone is the same start."""
    if one is None or other is None:
        return one is other
    if one.end is not None and other.end is not None:
        return (one.end == other.end and one.starts_at == other.starts_at
                and one.zone == other.zone)
    return one == other


def new_id() -> str:
    """A pin's id, made when it is first set and kept through every edit: sixteen
    random hex digits, which two pins never share in practice, and nothing a reader
    should parse (ADR-0141 decision 2). Asked for here alone, so that a test that
    needs ids it can name replaces this one function."""
    return secrets.token_hex(8)


@dataclass(frozen=True, init=False)
class Pin:
    """One pin: its kind, its note, when it was last written and until when, by
    whom, when and by whom it was first set, and its id — and for an acknowledgment
    what it is bound to.

    ``note`` is what the person wrote — why, a ticket, what was found — Markdown, as
    every note is (ADR-0047 decision 1); a maintenance pin set without one holds
    :data:`NO_NOTE`, and an acknowledgment set without one holds none.

    ``schedule`` is what a maintenance entry covers (ADR-0150): one window from its
    start to its end — what a pin built with an ``expires_at`` alone holds, from its
    creation, written in the configured zone — or a series, with ``not_on``, the key
    of the holiday list whose days its rule leaves out, and ``changed``, its windows
    changed alone. ``expires_at`` is when the pin ends by the clock: for maintenance
    where its schedule's last window ends, as written — derived, never stored; the
    tree's windows apply the holiday list — and for a silence, its deadline; for
    *seen* only where the person gave it an end — it ends by itself first, as what it
    accepted changes (ADR-0142).
    ``occurrence`` is what a *seen* is bound to: the line's occurrence as it was set
    — its type's field, or its reading's identity — and empty where it is bound to
    the failing stretch it was set in, which is every node's own and every line
    nothing tells apart. ``status`` is the status a *seen* was set at, which a worse
    one ends. A *done* is bound to both (ADR-0146): the occurrence it closed, which
    it always has, and ``status``, the failure it closed. ``level`` is the most a
    silence lets its part count as above it, ``OK`` or ``WARN`` (ADR-0144): a silence
    is bound to its deadline and its level, and to no failure, holding through every
    recovery.

    The pin carries **both dates** (ADR-0014). ``set_at`` / ``set_by`` mean *the
    last write*, and ``created_at`` / ``created_by`` *the first*, the one piece of
    history kept without a history. Clearing drops the pin, so a clear-and-re-pin
    (and an expiry sweep followed by a new pin) honestly starts a new creation — and
    a new id.

    ``set_at`` does double duty as the **concurrency token**: a write names the
    ``set_at`` it believes it is replacing, as :attr:`token` spells it, and the tree
    refuses the write when that no longer matches. ``id`` is what names the pin
    where it is listed beside others — the envelope's ``handled``, and the rule that
    decided what its part counts (ADR-0141 decision 3) — made when the pin is first
    set and kept through every edit, as its creation is.

    The three times are instants, held in UTC (ADR-0120): a pin cannot be built with
    a time without a zone, and its file carries none (:meth:`from_dict`).
    """
    kind: str
    note: str
    set_at: datetime
    expires_at: datetime | None
    set_by: str
    created_at: datetime
    created_by: str
    id: str
    occurrence: str
    status: StatusCode | None
    level: StatusCode | None
    schedule: Schedule | None
    not_on: str
    changed: tuple[Changed, ...]

    def __init__(self, kind: str, note: str, set_at: datetime,
                 expires_at: datetime | None = None, set_by: str = "",
                 created_at: datetime | None = None, created_by: str = "",
                 id: str = "", *, occurrence: str = "",
                 status: StatusCode | None = None,
                 level: StatusCode | None = None,
                 schedule: Schedule | None = None, not_on: str = "",
                 changed: Iterable[Changed] = ()) -> None:
        """An absent creation **is** the set, and then its author the set's unless
        one is named: the plain reading of a pin nobody has edited yet. An absent id
        is a new pin's, made here (:func:`new_id`).

        :raises ValueError: ``kind`` is not one this release knows, one of the times
            carries no zone, a maintenance pin or a silence has no end, a *done* has
            one, a *seen* or a *done* names no failure it was set at, a *done* no
            occurrence it closed, a silence no level it holds its part at, or a pin
            names what its kind is not bound to.
        """
        if kind not in KINDS:
            raise ValueError(f"a pin of kind {kind!r}, which this release does "
                             f"not know")
        set_at = instants.utc(set_at, "a pin's set_at")
        windows_changed = tuple(sorted(changed, key=lambda each: each.start))
        if kind == MAINTENANCE:
            if occurrence or status is not None or level is not None:
                raise ValueError("a maintenance pin is bound to its window alone")
            if schedule is None:
                if expires_at is None:
                    raise ValueError("a maintenance pin without an end")
                expires_at = instants.utc(expires_at, "a pin's expires_at")
                # one window from its creation to its end — what it has covered
                # since it was first set, whatever edits moved its end — or, where
                # the end is not after that, the second before it: a window that has
                # run out
                began = (set_at if created_at is None
                         else instants.utc(created_at, "a pin's created_at"))
                schedule = Schedule.one_off(
                    min(began, expires_at - timedelta(seconds=1)), expires_at, _zone())
            expires_at = _schedule_end(schedule, windows_changed)
        elif schedule is not None or not_on or windows_changed:
            raise ValueError(f"a {kind} pin has no schedule")
        elif kind == SILENCED:
            if expires_at is None:
                raise ValueError("a silence without a deadline")
            if occurrence or status is not None:
                raise ValueError("a silence is bound to its deadline and its level "
                                 "alone")
            if level not in SILENCE_LEVELS:
                raise ValueError(f"a silence holds its part at ok or at most warn, "
                                 f"not at {'nothing' if level is None else level.name}")
        elif status not in (StatusCode.WARN, StatusCode.ERROR):
            raise ValueError(f"a {kind} pin is set at a failure, not at "
                             f"{'nothing' if status is None else status.name}")
        elif level is not None:
            raise ValueError(f"a {kind} pin holds its part at no level")
        if kind == DONE:
            if expires_at is not None:
                raise ValueError("a done has no end: it ends as its line reads "
                                 "anything other than the failure it closed")
            if not occurrence:
                raise ValueError("a done closes an event, and names no occurrence")
        if created_at is None:
            created_at = set_at
            created_by = created_by or set_by
        for name, value in (
                ("kind", kind), ("note", note), ("set_at", set_at),
                ("expires_at", None if expires_at is None
                 else instants.utc(expires_at, "a pin's expires_at")),
                ("set_by", set_by),
                ("created_at", instants.utc(created_at, "a pin's created_at")),
                ("created_by", created_by), ("id", id or new_id()),
                ("occurrence", occurrence), ("status", status), ("level", level),
                ("schedule", schedule), ("not_on", not_on),
                ("changed", windows_changed)):
            object.__setattr__(self, name, value)

    @property
    def acknowledgment(self) -> bool:
        """Whether this pin is an acknowledgment (:data:`ACKNOWLEDGMENTS`): a seen, a
        silence or a done, one on a part at a time."""
        return self.kind in ACKNOWLEDGMENTS

    @property
    def token(self) -> str:
        """The concurrency token a form carries and sends back: ``set_at`` as it is
        spelled, which is the same text before a restart and after it."""
        return instants.stamp(self.set_at)

    def to_dict(self) -> dict[str, Any]:
        """The pin as its file carries it, without its target: each time in UTC, as
        :func:`~little_sister.instants.stamp` spells one. A maintenance entry writes its
        schedule, its holiday list and its windows changed alone, and never an end; an
        end, an occurrence, a status and a level are keys only where the pin has
        them."""
        said: dict[str, Any] = {"id": self.id, "kind": self.kind, "note": self.note,
                "set_at": instants.stamp(self.set_at),
                "set_by": self.set_by,
                "created_at": instants.stamp(self.created_at),
                "created_by": self.created_by}
        if self.schedule is not None:
            said["schedule"] = self.schedule.text()
            if self.not_on:
                said["not_on"] = self.not_on
            if self.changed:
                said["changed"] = [each.to_dict() for each in self.changed]
        elif self.expires_at is not None:
            said["expires_at"] = instants.stamp(self.expires_at)
        if self.occurrence:
            said["occurrence"] = self.occurrence
        if self.status is not None:
            said["status"] = self.status.name
        if self.level is not None:
            said["level"] = self.level.name
        return said

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> Pin:
        """Read one pin, its times strictly
        (:func:`~little_sister.instants.instant`): :class:`ValueError` for one that
        is not an instant with an offset, for a pin without an id or a kind, for a
        status or a level that is none, and for anything :class:`Pin` refuses. A pin
        that names no creation was created when it was set."""
        created = data.get("created_at")
        ident = values.text(data, "id")
        if not ident:
            raise ValueError("a pin without an id")
        kind = values.text(data, "kind")
        ends = data.get("expires_at")
        status, level = (_status(values.text(data, key), key)
                         for key in ("status", "level"))
        note = values.text(data, "note")
        schedule: Schedule | None = None
        changed: tuple[Changed, ...] = ()
        if kind == MAINTENANCE:
            text = data.get("schedule")
            if not isinstance(text, str):
                raise ValueError("a maintenance pin without a schedule")
            schedule = Schedule.parse(text)
            said = data.get("changed") or []
            if not isinstance(said, list):
                raise ValueError("a maintenance pin's changed windows are no list")
            changed = tuple(Changed.from_dict(each) for each in said)
        return cls(
            kind=kind,
            note=note or NO_NOTE if kind == MAINTENANCE else note,
            set_at=instants.instant(data.get("set_at"), "a pin's set_at"),
            expires_at=(None if (ends is None and kind != SILENCED)
                        or kind == MAINTENANCE
                        else instants.instant(ends, "a pin's expires_at")),
            set_by=values.text(data, "set_by"),
            created_at=(None if created is None
                        else instants.instant(created, "a pin's created_at")),
            created_by=values.text(data, "created_by"),
            id=ident, occurrence=values.text(data, "occurrence"), status=status,
            level=level, schedule=schedule, not_on=values.text(data, "not_on"),
            changed=changed)

    def same_pin_as(self, other: Pin) -> bool:
        """Whether ``other`` says the same thing this pin does — same kind, same
        note, same end, same level. A set that changes none of them is no write at
        all: the tree keeps the stored pin, its token and its authors (ADR-0104
        decision 5), and has nothing to announce (ADR-0014). Anything else is a real
        edit. What a *seen* is bound to is taken where it is set, and an edit keeps
        it."""
        return (self.kind == other.kind and self.note == other.note
                and self.expires_at == other.expires_at and self.level == other.level
                and _same_schedule(self.schedule, other.schedule)
                and self.not_on == other.not_on and self.changed == other.changed)

    def is_expired(self, now: datetime) -> bool:
        """True once ``now`` reaches ``expires_at`` — two instants, so the answer
        is the same on every machine and through every change of a clock. A pin
        with no end never is."""
        return self.expires_at is not None and self.expires_at <= now


@dataclass(frozen=True)
class PinWrite:
    """The outcome of a guarded write to the pins.

    ``applied`` says whether the pins changed. ``refused`` says the **guard**
    rejected the write — a different thing from a clear that found nothing to clear
    or a set that says what the stored pin says, which change nothing and are
    nobody's conflict, and from a ``problem``, an acknowledgment its part cannot
    take now. ``current`` is what is held afterwards: the new pin on a set,
    the pin that stood on a set that changed nothing, ``None`` on a clear, and on a
    refusal the pin that was actually there (``None`` when the pin the person meant
    to replace is already gone). One process holds one lock (ADR-0001/0002), so the
    comparison is exact rather than best-effort.
    """
    applied: bool
    current: Pin | None = None
    refused: bool = False
    #: Why a new acknowledgment was not set, where its part could not take one now —
    #: nothing fails there, or it is in maintenance (ADR-0142) — and empty on every
    #: other outcome.
    problem: str = ""


#: A node's pins by its path, and a line's by its path and its slug: the tables the
#: tree holds, one for maintenance and one for the acknowledgments of each, which the
#: file carries as one list.
NodePins = dict[str, Pin]
LinePins = dict[tuple[str, str], Pin]


class PinTables(NamedTuple):
    """Every pin a file holds, in the four tables the tree holds them in: a node's
    maintenance by its path, a line's by its path and its slug, and the same two for
    the acknowledgments (ADR-0142) — and how many pins of a kind this release does not
    know it skipped."""
    nodes: NodePins
    lines: LinePins
    acknowledged: NodePins
    lines_acknowledged: LinePins
    unknown: int = 0


class PinStore:
    """The pins as a state file, written through.

    The file is ``{"pins": [pin, …]}``: each pin as :meth:`Pin.to_dict` writes it,
    with its target beside it — ``path``, and ``slug``, empty for the node's own —
    in the order of their targets, so that the same pins are always the same bytes.
    Reading and writing — atomic, and never a refusal to start — are the state
    layer's (ADR-0071); a failed write leaves the tree's pins authoritative for the
    session and stands as a line on the heartbeat until a write succeeds. There is no
    flush-on-shutdown, because write-through is what makes a crash never lose a
    just-set pin (ADR-0014).
    """

    def __init__(self, state: StateLayer, *, tree: StatusTree | None = None) -> None:
        self._state = state
        self._tree = tree
        # The file's other direction (ADR-0077), registered here at construction
        # because this is where the file's shape is known: an adopted copy — the
        # store's at a takeover, the backup's on the way back — is read into its two
        # tables and handed to the tree that holds the pins. A store built without
        # a tree (a test's, a reader's) has nothing to hand them to.
        if tree is not None:
            state.restore_with(PINS_FILE, self._adopt)

    def _adopt(self, payload: object) -> None:
        """Hand an adopted file's tables to the tree, under its lock, with a
        transition for every node that changes (:meth:`StatusTree.adopt_maintenance`,
        :meth:`StatusTree.adopt_acknowledgments`). A payload of another shape raises,
        in the words the startup read reports, and the layer reports the adoption as
        failed."""
        assert self._tree is not None
        held = self._read_payload(payload)
        self._tree.adopt_maintenance(held.nodes, entry_pins=held.lines)
        self._tree.adopt_acknowledgments(held.acknowledged, held.lines_acknowledged)

    def load_all(self) -> PinTables:
        """Every table in one read — the startup restore's call: a file that is not
        there is empty tables, and so is one :meth:`tables` refuses, which is a load
        failure the layer reports. Nothing of such a file is in force: one pin it
        cannot take refuses every pin beside it."""
        data = self._state.read(PINS_FILE)
        if data is None:
            return PinTables({}, {}, {}, {})
        try:
            return self._read_payload(data)
        except ValueError as error:
            self._state.report_load_failure(PINS_FILE, str(error))
            return PinTables({}, {}, {}, {})

    def load(self) -> NodePins:
        """The nodes' maintenance pins, or none where the file is missing or
        unusable."""
        return self.load_all().nodes

    def load_entries(self) -> LinePins:
        """The lines' maintenance pins (ADR-0036), keyed ``(path, slug)``."""
        return self.load_all().lines

    def _read_payload(self, payload: object) -> PinTables:
        """The tables of a payload, a pin of a kind this release does not know
        skipped and named once (ADR-0032 rule 7)."""
        held = self.tables(payload)
        if held.unknown:
            self_report.startup.note(
                "pins.unknown-kind",
                plain(f"{self._state.path(PINS_FILE)} holds {held.unknown} pin(s) of "
                      f"a kind this release does not know: each is skipped, and the "
                      f"next save drops it (ADR-0141)"))
        return held

    @staticmethod
    def tables(payload: object) -> PinTables:
        """Every table out of a payload in the file's shape — what an adoption at
        runtime hands to the tree (ADR-0077) — and how many pins of a kind this
        release does not know it skipped; or :class:`ValueError` naming what is wrong
        with it, in the words the startup read reports. A place holds one
        maintenance pin and one acknowledgment (ADR-0142): a second of either refuses
        the file."""
        if not isinstance(payload, dict):
            raise ValueError("not a mapping")
        raws = payload.get("pins")
        if raws is None and not payload:
            return PinTables({}, {}, {}, {})
        if not isinstance(raws, list):
            raise ValueError("no 'pins' list")
        held = PinTables({}, {}, {}, {})
        unknown = 0
        for raw in raws:
            if not isinstance(raw, dict):
                raise ValueError("a pin that is not a mapping")
            kind = values.text(raw, "kind")
            if not kind:
                raise ValueError("a pin without a kind")
            if kind == MAINTENANCE and "schedule" not in raw:
                # A maintenance pin in the shape before schedules: dropped, and
                # nothing says so — a clean break (ADR-0150), the release's notes
                # saying it once.
                continue
            if kind not in KINDS:
                unknown += 1
                continue
            pin = Pin.from_dict(raw)
            path = values.text(raw, "path")
            if not path.startswith("/"):
                raise ValueError(f"a pin whose path is not one: {path!r}")
            slug = values.text(raw, "slug")
            if pin.acknowledgment:
                table: dict[Any, Pin] = (held.lines_acknowledged if slug
                                         else held.acknowledged)
            else:
                table = held.lines if slug else held.nodes
            key: Any = (path, slug) if slug else path
            if key in table:
                what = ("acknowledgments" if pin.acknowledgment
                        else f"{pin.kind} pins")
                raise ValueError(f"two {what} on {path}"
                                 + (f", line {slug}" if slug else ""))
            table[key] = pin
        return held._replace(unknown=unknown)

    def save(self, nodes: Mapping[str, Pin],
             lines: Mapping[tuple[str, str], Pin] | None = None,
             acknowledged: Mapping[str, Pin] | None = None,
             lines_acknowledged: Mapping[tuple[str, str], Pin] | None = None
             ) -> None:
        """Rewrite the whole file, atomically, through the layer. A write failure
        is recorded there, not raised (the tree's pins stay authoritative for the
        session)."""
        rows = [{"path": path, "slug": "", **pin.to_dict()}
                for table in (nodes, acknowledged or {})
                for path, pin in table.items()]
        rows += [{"path": path, "slug": slug, **pin.to_dict()}
                 for table in (lines or {}, lines_acknowledged or {})
                 for (path, slug), pin in table.items()]
        rows.sort(key=lambda row: (row["path"], row["slug"], row["kind"],
                                   row["created_at"], row["id"]))
        self._state.write(PINS_FILE, {"pins": rows})
