"""The pins (ADR-0141): what a person set on a node or on one of its lines, one file of
the state layer.

A **pin** is one thing with a kind (ADR-0141 decision 1): a target — a node by its
path, or one of its lines by the path and the line's slug (ADR-0036) — a note, who set
it and when and who first did, its end where it has one, an id of its own and the token
a form carries back. What differs by kind is what it does at the node's boundary, what
ends it and what it is bound to. This release knows two kinds: **maintenance**
(ADR-0014), down on purpose and bound to a window in time, and **seen** (ADR-0142), a
failure accepted until it changes and bound to the occurrence it was set on — the first
of the kinds a ringed check sets, the **acknowledgments**, of which a part holds one at
a time beside its maintenance.

The tree holds the pins and writes them through this store on every change, so a
restart restores them. The file is ``var/state/pins.json`` (ADR-0071), written through,
atomically, by the layer's own discipline: a list of pins, each with its target
beside it. It took the place of ``maintenance.json`` with a **clean break**: the old
file is not read, and the state layer names it once at the first start that finds it
without its successor (``state.RETIRED_FILES``). This module knows the file's *shape*
and nothing about where or how it is written.

**A file this release cannot read takes every pin with it** — a shape it does not
know, a time that is no instant, a pin without an id or a kind, two pins of one kind on
one place, or two acknowledgments on one place — which fails toward alarming, and the
layer reports it. **A pin of a kind
this release does not know is skipped and named once** (ADR-0032 rule 7): an older
standby adopting a newer holder's file keeps every pin it understands, and its next
write drops the rest.
"""
from __future__ import annotations

import secrets
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import TYPE_CHECKING, Any, NamedTuple

from little_sister import instants, self_report, values
from little_sister.codes import StatusCode
from little_sister.reasons import plain
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

#: What a ringed check sets (ADR-0142): the kinds that accept or silence a failure, of
#: which a part holds **one at a time** beside any maintenance. *Done* and *silenced*
#: join *seen* here with their kinds.
ACKNOWLEDGMENTS: frozenset[str] = frozenset({SEEN})

#: Every kind of pin this release knows. A pin of any other kind in the file is
#: skipped and named once (ADR-0032 rule 7).
KINDS: frozenset[str] = frozenset({MAINTENANCE, *ACKNOWLEDGMENTS})

#: What a maintenance pin set without a note holds as its note: the honest
#: placeholder, which no surface shows as a note and the notes' history never takes
#: (ADR-0047). An acknowledgment set without one holds none.
NO_NOTE = "maintenance"


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

    ``expires_at`` is when the pin ends by the clock: always for maintenance, a
    window in time, and for *seen* only where the person gave it an end — it ends by
    itself first, as what it accepted changes (ADR-0142). ``occurrence`` is what an
    acknowledgment is bound to: the line's occurrence as it was set — its type's
    field, or its reading's identity — and empty where it is bound to the failing
    stretch it was set in, which is every node's own and every line nothing tells
    apart. ``status`` is the status a *seen* was set at, which a worse one ends.

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

    def __init__(self, kind: str, note: str, set_at: datetime,
                 expires_at: datetime | None, set_by: str = "",
                 created_at: datetime | None = None, created_by: str = "",
                 id: str = "", *, occurrence: str = "",
                 status: StatusCode | None = None) -> None:
        """An absent creation **is** the set, and then its author the set's unless
        one is named: the plain reading of a pin nobody has edited yet. An absent id
        is a new pin's, made here (:func:`new_id`).

        :raises ValueError: ``kind`` is not one this release knows, one of the times
            carries no zone, a maintenance pin has no end, or a *seen* names no
            failure it was set at, or one of maintenance names one, or an
            occurrence.
        """
        if kind not in KINDS:
            raise ValueError(f"a pin of kind {kind!r}, which this release does "
                             f"not know")
        if kind == MAINTENANCE:
            if expires_at is None:
                raise ValueError("a maintenance pin without an end")
            if occurrence or status is not None:
                raise ValueError("a maintenance pin is bound to its window alone")
        elif status not in (StatusCode.WARN, StatusCode.ERROR):
            raise ValueError(f"a {kind} pin is set at a failure, not at "
                             f"{'nothing' if status is None else status.name}")
        set_at = instants.utc(set_at, "a pin's set_at")
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
                ("occurrence", occurrence), ("status", status)):
            object.__setattr__(self, name, value)

    @property
    def acknowledgment(self) -> bool:
        """Whether this pin is one a ringed check sets (:data:`ACKNOWLEDGMENTS`)."""
        return self.kind in ACKNOWLEDGMENTS

    @property
    def token(self) -> str:
        """The concurrency token a form carries and sends back: ``set_at`` as it is
        spelled, which is the same text before a restart and after it."""
        return instants.stamp(self.set_at)

    def to_dict(self) -> dict[str, str]:
        """The pin as its file carries it, without its target: each time in UTC, as
        :func:`~little_sister.instants.stamp` spells one. An end, an occurrence and a
        status are keys only where the pin has them."""
        said = {"id": self.id, "kind": self.kind, "note": self.note,
                "set_at": instants.stamp(self.set_at),
                "set_by": self.set_by,
                "created_at": instants.stamp(self.created_at),
                "created_by": self.created_by}
        if self.expires_at is not None:
            said["expires_at"] = instants.stamp(self.expires_at)
        if self.occurrence:
            said["occurrence"] = self.occurrence
        if self.status is not None:
            said["status"] = self.status.name
        return said

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> Pin:
        """Read one pin, its times strictly
        (:func:`~little_sister.instants.instant`): :class:`ValueError` for one that
        is not an instant with an offset, for a pin without an id or a kind, for a
        status that is none, and for anything :class:`Pin` refuses. A pin that names
        no creation was created when it was set."""
        created = data.get("created_at")
        ident = values.text(data, "id")
        if not ident:
            raise ValueError("a pin without an id")
        kind = values.text(data, "kind")
        ends = data.get("expires_at")
        said = values.text(data, "status")
        try:
            status = StatusCode[said] if said else None
        except KeyError:
            raise ValueError(f"a pin set at {said!r}, which is no status") from None
        note = values.text(data, "note")
        return cls(
            kind=kind,
            note=note or NO_NOTE if kind == MAINTENANCE else note,
            set_at=instants.instant(data.get("set_at"), "a pin's set_at"),
            expires_at=(None if ends is None and kind != MAINTENANCE
                        else instants.instant(ends, "a pin's expires_at")),
            set_by=values.text(data, "set_by"),
            created_at=(None if created is None
                        else instants.instant(created, "a pin's created_at")),
            created_by=values.text(data, "created_by"),
            id=ident, occurrence=values.text(data, "occurrence"), status=status)

    def same_pin_as(self, other: Pin) -> bool:
        """Whether ``other`` says the same thing this pin does — same kind, same
        note, same end. A set that changes none of them is no write at all: the tree
        keeps the stored pin, its token and its authors (ADR-0104 decision 5), and
        has nothing to announce (ADR-0014). Anything else is a real edit. What an
        acknowledgment is bound to is taken where it is set, and an edit keeps it."""
        return (self.kind == other.kind and self.note == other.note
                and self.expires_at == other.expires_at)

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
