"""Persistence for the maintenance side-table (ADR-0014).

Maintenance is a sticky admin override (`project.md` §2.6). The status tree owns
the side-table — `path -> `:class:`MaintenanceEntry` — and writes it through this
store on every change, so a restart restores it. The file is exactly that table
serialized, and it is one file of the state layer (:mod:`~little_sister.state`,
ADR-0071): ``var/state/maintenance.json``, written through, atomically, by the
layer's own discipline — this module knows the file's *shape* and nothing about
where or how it is written.
"""
from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

from little_sister import instants, self_report, values
from little_sister.reasons import plain
from little_sister.state import MAINTENANCE_FILE, StateLayer

if TYPE_CHECKING:
    from little_sister.tree import StatusTree

#: Where the file lived before the state layer (ADR-0014 as first written). It is
#: **not read** — the move is a clean break, like the shape change before it — but
#: a file still sitting there is named once at startup, because pins that quietly
#: stopped being in force are the failure this layer exists to prevent.
RETIRED_PATH = "var/maintenance.json"


@dataclass(frozen=True, init=False)
class MaintenanceEntry:
    """One maintenance pin: why, when, until, and by whom.

    The entry carries **both dates** (ADR-0014). ``set_at`` / ``set_by``
    mean *the last write* — which is what the code always stored, since every set
    rebuilds the entry — and ``created_at`` / ``created_by`` mean *the first*, the
    one piece of history kept without a history. Clearing drops the entry, so a
    clear-and-re-pin (and an expiry sweep followed by a new pin) honestly starts a
    new creation.

    ``set_at`` does double duty as the **concurrency token**: a write names the
    ``set_at`` it believes it is replacing, as :attr:`token` spells it, and the
    tree refuses the write when that no longer matches
    (:meth:`StatusTree.set_maintenance`).

    The three times are instants, held in UTC (ADR-0120): an entry cannot be built
    with a time without a zone, and its file carries none (:meth:`from_dict`).
    """
    reason: str
    set_at: datetime
    expires_at: datetime
    set_by: str
    created_at: datetime
    created_by: str

    def __init__(self, reason: str, set_at: datetime, expires_at: datetime,
                 set_by: str = "", created_at: datetime | None = None,
                 created_by: str = "") -> None:
        """An absent creation **is** the set, and then its author the set's unless
        one is named: the plain reading of a pin nobody has edited yet. Said here
        rather than at the read, so it is one rule in one place and no entry
        anywhere is without its creation.

        :raises ValueError: one of the times carries no zone.
        """
        set_at = instants.utc(set_at, "a pin's set_at")
        if created_at is None:
            created_at = set_at
            created_by = created_by or set_by
        for name, value in (
                ("reason", reason), ("set_at", set_at),
                ("expires_at", instants.utc(expires_at, "a pin's expires_at")),
                ("set_by", set_by),
                ("created_at", instants.utc(created_at, "a pin's created_at")),
                ("created_by", created_by)):
            object.__setattr__(self, name, value)

    @property
    def token(self) -> str:
        """The concurrency token a form carries and sends back: ``set_at`` as it is
        spelled, which is the same text before a restart and after it."""
        return instants.stamp(self.set_at)

    def to_dict(self) -> dict[str, str]:
        """The entry as its file carries it: each time in UTC, as
        :func:`~little_sister.instants.stamp` spells one."""
        return {"reason": self.reason, "set_at": instants.stamp(self.set_at),
                "expires_at": instants.stamp(self.expires_at),
                "set_by": self.set_by,
                "created_at": instants.stamp(self.created_at),
                "created_by": self.created_by}

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> MaintenanceEntry:
        """Read one entry, its times strictly
        (:func:`~little_sister.instants.instant`): :class:`ValueError` for one that
        is not an instant with an offset — a time without a zone, which is every
        time the versions before ADR-0120 wrote — and the store reports the file.
        An entry that names no creation was created when it was set."""
        created = data.get("created_at")
        return cls(
            reason=values.text(data, "reason"),
            set_at=instants.instant(data.get("set_at"), "a pin's set_at"),
            expires_at=instants.instant(data.get("expires_at"),
                                        "a pin's expires_at"),
            set_by=values.text(data, "set_by"),
            created_at=(None if created is None
                        else instants.instant(created, "a pin's created_at")),
            created_by=values.text(data, "created_by"))

    def same_pin_as(self, other: MaintenanceEntry) -> bool:
        """Whether ``other`` says the same thing this entry does — same reason, same
        expiry. A set that changes neither is no write at all: the tree keeps the
        stored entry, its token and its authors (ADR-0104 decision 5), and has
        nothing to announce (ADR-0014). Anything else is a real edit."""
        return (self.reason == other.reason
                and self.expires_at == other.expires_at)

    def is_expired(self, now: datetime) -> bool:
        """True once ``now`` reaches ``expires_at`` — two instants, so the answer
        is the same on every machine and through every change of a clock."""
        return self.expires_at <= now


@dataclass(frozen=True)
class MaintenanceWrite:
    """The outcome of a guarded write to the maintenance side-table.

    ``applied`` says whether the table changed. ``refused`` says the **guard**
    rejected the write — a different thing from a clear that found nothing to clear
    or a set that says what the stored pin says, which change nothing and are
    nobody's conflict. ``current`` is what the table holds afterwards: the new entry
    on a set, the entry that stood on a set that changed nothing, ``None`` on a
    clear, and on a refusal the entry that was actually there (``None`` when the pin
    the admin meant to replace is already gone). One process holds one lock
    (ADR-0001/0002), so the comparison is exact rather than best-effort.
    """
    applied: bool
    current: MaintenanceEntry | None = None
    refused: bool = False


class MaintenanceStore:
    """The maintenance side-table as a state file, written through.

    The file holds two tables — ``nodes`` (``{path: entry}``) and ``entries``
    (``{path: {slug: entry}}``, ADR-0036). An entry is ``{reason, set_at,
    expires_at, set_by, created_at, created_by}``, its three times in UTC
    (ADR-0120). The bare node table this file used to be is a **clean break**, not
    a migration: it is not read, and the layer reports it as a load failure — as it
    does a file whose times carry no zone, which is what the versions before
    ADR-0120 wrote. Reading and writing — atomic, and never a
    refusal to start — are the state layer's (ADR-0071); a failed write leaves the
    in-memory table authoritative for the session and stands as a line on the
    heartbeat until a write succeeds. There is no flush-on-shutdown, because
    write-through is what makes a crash never lose a just-set pin (ADR-0014).
    """

    def __init__(self, state: StateLayer, *, tree: StatusTree | None = None) -> None:
        self._state = state
        self._tree = tree
        # The file's other direction (ADR-0077), registered here at construction
        # because this is where the file's shape is known: an adopted copy — the
        # store's at a takeover, the backup's on the way back — is read into its
        # two tables and handed to the tree that holds the pins. A store built
        # without a tree (a test's, a reader's) has nothing to hand them to.
        if tree is not None:
            state.restore_with(MAINTENANCE_FILE, self._adopt)

    def _adopt(self, payload: object) -> None:
        """Hand an adopted file's two tables to the tree, under its lock, with a
        transition for every node that changes (:meth:`StatusTree.adopt_maintenance`).
        A payload of another shape raises, in the words the startup read reports,
        and the layer reports the adoption as failed."""
        assert self._tree is not None
        nodes, entry_pins = self.tables(payload)
        self._tree.adopt_maintenance(nodes, entry_pins=entry_pins)

    def load_all(self) -> tuple[dict[str, MaintenanceEntry],
                                dict[tuple[str, str], MaintenanceEntry]]:
        """Both tables in one read — the startup restore's call. A file still
        sitting at the retired ``var/maintenance.json`` is named once here."""
        if (not self._state.path(MAINTENANCE_FILE).exists()
                and Path(RETIRED_PATH).exists()):
            self_report.startup.note(
                "maintenance.moved",
                plain(f"{RETIRED_PATH} is no longer read — the file moved to "
                      f"{self._state.path(MAINTENANCE_FILE)} (ADR-0071); move it "
                      f"there before the next restart if its pins are still "
                      f"wanted"))
        return self._read()

    def load(self) -> dict[str, MaintenanceEntry]:
        """The node table, or an empty one if the file is missing or unusable.
        Per-entry pins come from :meth:`load_entries`."""
        return self._read()[0]

    def load_entries(self) -> dict[tuple[str, str], MaintenanceEntry]:
        """The per-entry pins (ADR-0036), keyed ``(path, slug)``. Empty for a file
        written before they existed."""
        return self._read()[1]

    def _read(self) -> tuple[dict[str, MaintenanceEntry],
                             dict[tuple[str, str], MaintenanceEntry]]:
        """The file's two tables — node pins and per-entry pins — as the startup
        read finds them: a file that is not there is two empty tables, and so is
        one :meth:`tables` refuses — a shape it does not know, a time that is no
        instant — which is a load failure the layer reports. Nothing of such a
        file is in force: one pin it cannot take refuses every pin beside it."""
        data = self._state.read(MAINTENANCE_FILE)
        if data is None:
            return {}, {}
        try:
            return self.tables(data)
        except ValueError as error:
            self._state.report_load_failure(MAINTENANCE_FILE, str(error))
            return {}, {}

    @staticmethod
    def tables(payload: object) -> tuple[dict[str, MaintenanceEntry],
                                         dict[tuple[str, str], MaintenanceEntry]]:
        """Both tables out of a payload in the file's shape — what an adoption at
        runtime hands to the tree (ADR-0077) — or :class:`ValueError` naming what
        is wrong with it, in the words the startup read reports."""
        nodes, entries = _split(payload)
        return _node_pins(nodes), _entry_pins(entries)

    def save(self, entries: Mapping[str, MaintenanceEntry],
             entry_pins: Mapping[tuple[str, str], MaintenanceEntry] | None = None
             ) -> None:
        """Rewrite the whole table, atomically, through the layer. A write
        failure is recorded there, not raised (the in-memory table stays
        authoritative for the session)."""
        by_path: dict[str, dict[str, dict[str, str]]] = {}
        for (path, slug), entry in (entry_pins or {}).items():
            by_path.setdefault(path, {})[slug] = entry.to_dict()
        self._state.write(MAINTENANCE_FILE, {
            "nodes": {path: entry.to_dict() for path, entry in entries.items()},
            "entries": by_path,
        })


def _split(data: object) -> tuple[dict[str, Any], dict[str, Any]]:
    """The two raw tables of a parsed file, or :class:`ValueError` for a shape
    this reader does not know.

    The file is ``{"nodes": {path: entry}, "entries": {path: {slug: entry}}}``.
    When per-entry pins arrived it was a bare node table, and that shape is a
    **clean break**: there is no reader for it and no migration, in the same
    spirit as the `config/` move (ADR-0031). A file in the old shape is a load
    failure the layer reports — the pins it held are not in force — and the
    next save rewrites it. The cost is a pin or two on one upgrade, against a
    compatibility branch that would sit in the read path forever: this is
    runtime state the program owns, never hand-authored, and every pin in it
    is bounded by a finite expiry anyway. An empty mapping is two empty tables.
    """
    if not isinstance(data, dict):
        raise ValueError("not a mapping")
    nodes = data.get("nodes")
    if not isinstance(nodes, dict):
        if data:
            raise ValueError(
                f"no 'nodes' table — the pre-ADR-0036 shape is not read; "
                f"{len(data)} entr(y/ies) dropped")
        return {}, {}
    entries = data.get("entries")
    return nodes, entries if isinstance(entries, dict) else {}


def _node_pins(nodes: Mapping[str, Any]) -> dict[str, MaintenanceEntry]:
    return {str(path): MaintenanceEntry.from_dict(raw)
            for path, raw in nodes.items() if isinstance(raw, dict)}


def _entry_pins(entries: Mapping[str, Any]
                ) -> dict[tuple[str, str], MaintenanceEntry]:
    pins: dict[tuple[str, str], MaintenanceEntry] = {}
    for path, by_slug in entries.items():
        if not isinstance(by_slug, dict):
            continue
        for slug, raw in by_slug.items():
            if isinstance(raw, dict):
                pins[(str(path), str(slug))] = MaintenanceEntry.from_dict(raw)
    return pins
