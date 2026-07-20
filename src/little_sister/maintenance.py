"""Persistence for the maintenance side-table (ADR-0014).

Maintenance is a sticky admin override (`project.md` §2.6). The status tree owns
the side-table — `path -> `:class:`MaintenanceEntry` — and writes it through this
store on every change, so a restart restores it. The file at
``var/maintenance.json`` is exactly that table serialized; the path is fixed
runtime state (not env-configurable). A durable store in a later Phase (`plan.md`)
subsumes this file — :class:`MaintenanceStore` is the seam.
"""
from __future__ import annotations

import json
import os
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from little_sister.logger import logger

# Fixed runtime path (git-ignored ``var/``); not env-overridable (ADR-0014).
MAINTENANCE_PATH = "var/maintenance.json"


@dataclass(frozen=True)
class MaintenanceEntry:
    """One maintenance pin: why, when, until, and by whom.

    Timestamps are ISO-8601 strings (naive server-local, like the tree's; ADR-0006).
    """
    reason: str
    set_at: str
    expires_at: str
    set_by: str = ""

    def to_dict(self) -> dict[str, str]:
        return {"reason": self.reason, "set_at": self.set_at,
                "expires_at": self.expires_at, "set_by": self.set_by}

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> MaintenanceEntry:
        return cls(
            reason=str(data.get("reason", "")),
            set_at=str(data.get("set_at", "")),
            expires_at=str(data.get("expires_at", "")),
            set_by=str(data.get("set_by", "")))

    def is_expired(self, now: datetime) -> bool:
        """True once ``now`` reaches ``expires_at``. An unparseable bound is treated
        as not-expired — better to keep a pin than drop it on bad data; the startup
        reaper and an admin remain backstops."""
        try:
            return datetime.fromisoformat(self.expires_at) <= now
        except ValueError:
            return False


class MaintenanceStore:
    """Atomic JSON persistence for the maintenance side-table.

    The file is the table serialized — ``{path: {reason, set_at, expires_at,
    set_by}}``. Saves are atomic (temp file + :func:`os.replace`); a failed read
    yields an empty table and a failed write is logged, leaving the in-memory state
    intact for the session (no flush-on-shutdown, so a crash never loses a just-set
    pin — ADR-0014).
    """

    def __init__(self, path: str | Path = MAINTENANCE_PATH) -> None:
        self._path = Path(path)

    def load(self) -> dict[str, MaintenanceEntry]:
        """Read the table, or an empty one if the file is missing or unreadable."""
        try:
            with open(self._path, encoding="utf-8") as handle:
                data = json.load(handle)
        except FileNotFoundError:
            return {}
        except (json.JSONDecodeError, OSError) as error:
            logger.warning("maintenance: cannot read %s: %s; ignoring",
                           self._path, error)
            return {}
        if not isinstance(data, dict):
            logger.warning("maintenance: %s is not a mapping; ignoring", self._path)
            return {}
        return {str(path): MaintenanceEntry.from_dict(raw)
                for path, raw in data.items() if isinstance(raw, dict)}

    def save(self, entries: Mapping[str, MaintenanceEntry]) -> None:
        """Rewrite the whole table atomically. A write failure is logged, not raised
        (the in-memory table stays authoritative for the session)."""
        payload = {path: entry.to_dict() for path, entry in entries.items()}
        tmp = self._path.with_name(self._path.name + ".tmp")
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            with open(tmp, "w", encoding="utf-8") as handle:
                json.dump(payload, handle, indent=2, sort_keys=True)
            os.replace(tmp, self._path)
        except OSError as error:
            logger.warning("maintenance: cannot write %s: %s; keeping in memory",
                           self._path, error)
