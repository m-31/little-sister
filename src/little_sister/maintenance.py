"""Persistence for the maintenance side-table (ADR-0014).

Maintenance is a sticky admin override (`project.md` §2.6). The status tree owns
the side-table — `path -> `:class:`MaintenanceEntry` — and writes it through this
store on every change, so a restart restores it. The file at
``var/maintenance.json`` is exactly that table serialized; the path is fixed
runtime state (not env-configurable). A durable store in a later phase subsumes
this file — :class:`MaintenanceStore` is the seam.
"""
from __future__ import annotations

import json
import os
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from little_sister import values
from little_sister.logger import logger

# Fixed runtime path (git-ignored ``var/``); not env-overridable (ADR-0014).
MAINTENANCE_PATH = "var/maintenance.json"


@dataclass(frozen=True)
class MaintenanceEntry:
    """One maintenance pin: why, when, until, and by whom.

    The entry carries **both dates** (ADR-0014 amendment). ``set_at`` / ``set_by``
    mean *the last write* — which is what the code always stored, since every set
    rebuilds the entry — and ``created_at`` / ``created_by`` mean *the first*, the
    one piece of history kept without a history. Clearing drops the entry, so a
    clear-and-re-pin (and an expiry sweep followed by a new pin) honestly starts a
    new creation.

    ``set_at`` does double duty as the **concurrency token**: a write names the
    ``set_at`` it believes it is replacing, and the tree refuses the write when
    that no longer matches (:meth:`StatusTree.set_maintenance`).

    Timestamps are ISO-8601 strings (naive server-local, like the tree's; ADR-0006).
    """
    reason: str
    set_at: str
    expires_at: str
    set_by: str = ""
    created_at: str = ""
    created_by: str = ""

    def __post_init__(self) -> None:
        """An absent creation **is** the set — which is both the upgrade rule for a
        file written before these two fields existed and the plain reading of a pin
        nobody has edited yet. Normalizing here rather than at the read makes it one
        rule in one place, and no entry anywhere carries an empty creation."""
        if not self.created_at:
            object.__setattr__(self, "created_at", self.set_at)
            if not self.created_by:
                object.__setattr__(self, "created_by", self.set_by)

    def to_dict(self) -> dict[str, str]:
        return {"reason": self.reason, "set_at": self.set_at,
                "expires_at": self.expires_at, "set_by": self.set_by,
                "created_at": self.created_at, "created_by": self.created_by}

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> MaintenanceEntry:
        """Read one entry. A file written before the two creation fields existed has
        neither; they arrive empty and :meth:`__post_init__` defaults them to the set
        values, so the file loads unchanged and no pin is lost on upgrade."""
        return cls(
            reason=values.text(data, "reason"),
            set_at=values.text(data, "set_at"),
            expires_at=values.text(data, "expires_at"),
            set_by=values.text(data, "set_by"),
            created_at=values.text(data, "created_at"),
            created_by=values.text(data, "created_by"))

    def same_pin_as(self, other: MaintenanceEntry) -> bool:
        """Whether ``other`` says the same thing this entry does — same reason, same
        expiry. A re-submit that changes neither is a no-op the tree writes but does
        not announce (ADR-0014 amendment); anything else is a real edit."""
        return (self.reason == other.reason
                and self.expires_at == other.expires_at)

    def is_expired(self, now: datetime) -> bool:
        """True once ``now`` reaches ``expires_at``. An unparseable bound is treated
        as not-expired — better to keep a pin than drop it on bad data; the startup
        reaper and an admin remain backstops."""
        try:
            return datetime.fromisoformat(self.expires_at) <= now
        except ValueError:
            return False


@dataclass(frozen=True)
class MaintenanceWrite:
    """The outcome of a guarded write to the maintenance side-table.

    ``applied`` says whether the table changed. ``refused`` says the **guard**
    rejected the write — a different thing from a clear that found nothing to clear,
    which changes nothing and is nobody's conflict. ``current`` is what the table
    holds afterwards: the new entry on a set, ``None`` on a clear, and on a refusal
    the entry that was actually there (``None`` when the pin the admin meant to
    replace is already gone). One process holds one lock (ADR-0001/0002), so the
    comparison is exact rather than best-effort.
    """
    applied: bool
    current: MaintenanceEntry | None = None
    refused: bool = False


class MaintenanceStore:
    """Atomic JSON persistence for the maintenance side-table.

    The file holds two tables — ``nodes`` (``{path: entry}``) and ``entries``
    (``{path: {slug: entry}}``, ADR-0036). An entry is ``{reason, set_at,
    expires_at, set_by, created_at, created_by}``. The bare node table this file
    used to be is a **clean break**, not a migration: it is ignored with a warning.
    Saves are atomic (temp file + :func:`os.replace`); a failed read
    yields an empty table and a failed write is logged, leaving the in-memory state
    intact for the session (no flush-on-shutdown, so a crash never loses a just-set
    pin — ADR-0014).
    """

    def __init__(self, path: str | Path = MAINTENANCE_PATH) -> None:
        self._path = Path(path)

    def load(self) -> dict[str, MaintenanceEntry]:
        """Read the node table, or an empty one if the file is missing or
        unreadable. Per-entry pins come from :meth:`load_entries`."""
        return {str(path): MaintenanceEntry.from_dict(raw)
                for path, raw in self._sections()[0].items()
                if isinstance(raw, dict)}

    def load_entries(self) -> dict[tuple[str, str], MaintenanceEntry]:
        """The per-entry pins (ADR-0036), keyed ``(path, slug)``. Empty for a file
        written before they existed."""
        pins: dict[tuple[str, str], MaintenanceEntry] = {}
        for path, by_slug in self._sections()[1].items():
            if not isinstance(by_slug, dict):
                continue
            for slug, raw in by_slug.items():
                if isinstance(raw, dict):
                    pins[(str(path), str(slug))] = MaintenanceEntry.from_dict(raw)
        return pins

    def _sections(self) -> tuple[dict[str, Any], dict[str, Any]]:
        """The file's two tables — node pins and per-entry pins.

        The file is ``{"nodes": {path: entry}, "entries": {path: {slug: entry}}}``.
        When per-entry pins arrived it was a bare node table, and that shape is a
        **clean break**: there is no reader for it and no migration, in the same
        spirit as the `config/` move (ADR-0031). A file in the old shape is ignored
        with a warning and the next save rewrites it — the cost is a pin or two on
        one upgrade, against a compatibility branch that would sit in the read path
        forever. This is runtime state the program owns, never hand-authored, and
        every pin in it is bounded by a finite expiry anyway.
        """
        try:
            with open(self._path, encoding="utf-8") as handle:
                data = json.load(handle)
        except FileNotFoundError:
            return {}, {}
        except (json.JSONDecodeError, OSError) as error:
            logger.warning("maintenance: cannot read %s: %s; ignoring",
                           self._path, error)
            return {}, {}
        if not isinstance(data, dict):
            logger.warning("maintenance: %s is not a mapping; ignoring", self._path)
            return {}, {}
        nodes = data.get("nodes")
        if not isinstance(nodes, dict):
            if data:
                logger.warning(
                    "maintenance: %s has no 'nodes' table (the pre-ADR-0036 shape "
                    "is not read); ignoring %d entr(y/ies)", self._path, len(data))
            return {}, {}
        entries = data.get("entries")
        return nodes, entries if isinstance(entries, dict) else {}

    def save(self, entries: Mapping[str, MaintenanceEntry],
             entry_pins: Mapping[tuple[str, str], MaintenanceEntry] | None = None
             ) -> None:
        """Rewrite the whole table atomically. A write failure is logged, not raised
        (the in-memory table stays authoritative for the session)."""
        by_path: dict[str, dict[str, dict[str, str]]] = {}
        for (path, slug), entry in (entry_pins or {}).items():
            by_path.setdefault(path, {})[slug] = entry.to_dict()
        payload = {
            "nodes": {path: entry.to_dict() for path, entry in entries.items()},
            "entries": by_path,
        }
        tmp = self._path.with_name(self._path.name + ".tmp")
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            with open(tmp, "w", encoding="utf-8") as handle:
                json.dump(payload, handle, indent=2, sort_keys=True)
            os.replace(tmp, self._path)
        except OSError as error:
            logger.warning("maintenance: cannot write %s: %s; keeping in memory",
                           self._path, error)
