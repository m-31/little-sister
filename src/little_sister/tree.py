"""The single, in-memory, thread-safe status tree, its transition log and its
per-node status history.

One process owns one :class:`StatusTree` (ADR-0001). Writers and readers share a
single ``RLock``; reads copy an immutable snapshot under the lock and render it
outside (ADR-0002). Roll-up follows ADR-0004 via ``Status.get_status_code``.

Two histories are kept:
- the **event log** — every status transition, newest appended (the source); and
- per-node **status history** — derived from the event log for one path
  (:meth:`StatusTree.history`).
"""
from __future__ import annotations

import re
import threading
from collections import deque
from dataclasses import dataclass
from datetime import datetime

from little_sister.maintenance import MaintenanceEntry, MaintenanceStore
from little_sister.status import (
    Status,
    StatusCode,
    effective_code,
    join_path,
    on_same_line,
    split_path,
    worst_of,
)

DEFAULT_ROOT_NAME = "overall"
DEFAULT_EVENT_LOG_SIZE = 1000

# Freshness (ADR-0005): a node not observed within roughly two of its intervals is
# "stale", and its status is shown degraded to at least WARN (worse-of, so a real
# ERROR is never softened). Computed at snapshot time; never an event.
STALE_DEGRADE = StatusCode.WARN
STALE_MIN_GRACE_SECONDS = 30.0


@dataclass(frozen=True)
class StatusSnapshot:
    """Immutable copy of a node and its subtree, safe to read outside the lock.

    ``own_code`` is the node's reported code; ``code`` is the effective, rolled-up
    status (ADR-0004). ``description`` and ``frequency_seconds`` are inherited from
    the check; ``config`` is the curated parameters it ran with (Markdown, ADR-0013);
    ``maintenance`` marks an admin override.
    """
    path: str
    name: str
    own_code: StatusCode
    code: StatusCode
    reason: tuple[str, ...]
    timestamp: str
    description: str = ""
    frequency_seconds: int | None = None
    config: str = ""
    about: str = ""
    title: str = ""
    maintenance: bool = False
    maintenance_entry: MaintenanceEntry | None = None
    stale: bool = False
    age_seconds: float = 0.0
    children: tuple[StatusSnapshot, ...] = ()


@dataclass(frozen=True)
class Event:
    """A recorded transition of a node's own status code."""
    path: str
    name: str
    old: StatusCode
    new: StatusCode
    reason: tuple[str, ...]
    timestamp: str


@dataclass(frozen=True)
class StatusPeriod:
    """One stretch of time a node held a given status (status history)."""
    code: StatusCode
    since: str
    until: str
    reason: tuple[str, ...]


class StatusTree:
    """A thread-safe status tree plus a bounded log of status transitions."""

    def __init__(self, root_name: str = DEFAULT_ROOT_NAME,
                 event_log_size: int = DEFAULT_EVENT_LOG_SIZE,
                 maintenance_store: MaintenanceStore | None = None) -> None:
        self._lock = threading.RLock()
        self._root = Status(path="/", name=root_name)
        self._events: deque[Event] = deque(maxlen=event_log_size)
        # Maintenance side-table: path -> entry, kept in sync with each node's
        # ``maintenance`` bool and written through to ``maintenance_store`` on every
        # change (ADR-0014). No store (the default) means in-memory only.
        self._maintenance: dict[str, MaintenanceEntry] = {}
        self._maintenance_store = maintenance_store

    def use_maintenance_store(self, store: MaintenanceStore) -> None:
        """Attach the persistence store (once, at startup, before restore)."""
        self._maintenance_store = store

    def upsert(self, path: str, code: StatusCode | str,
               reason: list[str] | str | None = None, *,
               description: str | None = None,
               frequency_seconds: int | None = None,
               config: str | None = None) -> bool:
        """Create-or-update the node at ``path`` and record a transition event if
        its own code changed. ``description`` / ``frequency_seconds`` / ``config``
        (inherited from the check) are stored when given — ``config`` is static
        display metadata, never a transition (ADR-0013). A node under
        **maintenance** keeps its admin-set status — only its check time is
        refreshed. Thread-safe.
        """
        with self._lock:
            node = self._ensure_node(path)
            if description is not None:
                node.description = description
            if frequency_seconds is not None:
                node.frequency_seconds = frequency_seconds
            if config is not None:
                node.config = config
            if node.maintenance:
                node.touch()
                return False
            old = node.code
            node.update(code, reason)
            if node.code == old:
                return False
            self._emit(node, old)
            return True

    def set_about(self, path: str, about: str) -> None:
        """Seed a node's ``about`` (subject metadata; ADR-0012). Auto-creates the
        node — `about` may target a container the tree hasn't built yet — and sets
        the field only; it is not status, so no event. Thread-safe."""
        with self._lock:
            self._ensure_node(path).about = about

    def set_title(self, path: str, title: str) -> None:
        """Seed a node's ``title`` (a short display label; ADR-0017) — like
        :meth:`set_about`, metadata only, no event. Thread-safe."""
        with self._lock:
            self._ensure_node(path).title = title

    def set_maintenance(self, path: str, reason: str | None = None, *,
                        expires_at: datetime, set_by: str = "") -> None:
        """Pin the node at ``path`` to maintenance (a sticky admin override) until
        ``expires_at``, recording who set it. Stores the entry and writes it through
        (ADR-0014). Thread-safe."""
        entry = MaintenanceEntry(
            reason=reason or "maintenance",
            set_at=datetime.now().isoformat(),
            expires_at=expires_at.isoformat(),
            set_by=set_by)
        with self._lock:
            self._apply_maintenance(path, entry)
            self._persist()

    def clear_maintenance(self, path: str) -> bool:
        """Release maintenance; the node reverts to ``UNDEFINED`` until the next
        check. Returns ``False`` if it wasn't in maintenance."""
        with self._lock:
            cleared = self._clear_node(path)
            if cleared:
                self._persist()
            return cleared

    def restore_maintenance(self, entries: dict[str, MaintenanceEntry],
                            now: datetime | None = None) -> None:
        """Replay persisted maintenance at startup (single worker, so once —
        ADR-0001): re-pin each **non-expired** entry, preserving its original
        ``set_at`` / ``expires_at``, and drop the rest, rewriting the file once.
        Replaying before any check has run is safe — the ``upsert`` guard keeps the
        pin (ADR-0014)."""
        moment = now or datetime.now()
        with self._lock:
            for entry_path, entry in entries.items():
                if not entry.is_expired(moment):
                    self._apply_maintenance(entry_path, entry)
            self._persist()

    def sweep_expired(self, now: datetime | None = None) -> list[str]:
        """Clear every entry past its ``expires_at`` — a real
        ``MAINTENANCE -> UNDEFINED`` transition and event; the next check refills the
        node (ADR-0014). Returns the cleared paths. Called each scheduler tick."""
        moment = now or datetime.now()
        with self._lock:
            expired = [path for path, entry in self._maintenance.items()
                       if entry.is_expired(moment)]
            for path in expired:
                self._clear_node(path)
            if expired:
                self._persist()
            return expired

    def reap_uncovered(self, check_roots: list[str]) -> list[str]:
        """Drop maintenance whose path **no check root covers** — segment-wise on one
        root-to-leaf line (:func:`on_same_line`). Run once at startup against the
        static check set (ADR-0014/0015); expiry is the backstop. Returns the reaped
        paths."""
        with self._lock:
            uncovered = [path for path in self._maintenance
                         if not any(on_same_line(path, root)
                                    for root in check_roots)]
            for path in uncovered:
                self._clear_node(path)
            if uncovered:
                self._persist()
            return uncovered

    def maintenance_entry(self, path: str) -> MaintenanceEntry | None:
        """The maintenance entry pinned at ``path``, if any."""
        with self._lock:
            return self._maintenance.get(path)

    def snapshot(self, path: str = "",
                 now: datetime | None = None) -> StatusSnapshot | None:
        """An immutable snapshot of the subtree at ``path`` (root by default), or
        ``None`` if no such node exists. Staleness is computed against ``now``
        (defaults to the current time). Thread-safe.
        """
        moment = now or datetime.now()
        with self._lock:
            node = self._find_node(path)
            return None if node is None else self._snapshot(node, moment)

    def effective(self, path: str = "") -> StatusCode | None:
        """The rolled-up status at ``path`` (root by default), or ``None``."""
        with self._lock:
            node = self._find_node(path)
            return None if node is None else node.get_status_code()

    def recent_events(self, limit: int | None = None) -> tuple[Event, ...]:
        """Recorded transitions, oldest first (optionally only the last
        ``limit``)."""
        with self._lock:
            events = tuple(self._events)
        return events if limit is None else events[-limit:]

    def history(self, path: str) -> list[StatusPeriod]:
        """The status history of the node at ``path`` — one period per status it
        has held, oldest first — derived from the event log. The current period's
        ``until`` is the last check time and its reason is the current one.
        """
        with self._lock:
            node = self._find_node(path)
            if node is None:
                return []
            events = [event for event in self._events if event.path == node.path]
            periods: list[StatusPeriod] = []
            for index, event in enumerate(events):
                is_current = index == len(events) - 1
                until = node.timestamp if is_current else events[index + 1].timestamp
                reason = tuple(node.reason) if is_current else event.reason
                periods.append(StatusPeriod(
                    code=event.new, since=event.timestamp, until=until,
                    reason=reason))
            return periods

    # --- internals; call only while holding the lock ---

    def _emit(self, node: Status, old: StatusCode) -> None:
        self._events.append(Event(
            path=node.path, name=node.name, old=old, new=node.code,
            reason=tuple(node.reason), timestamp=node.timestamp))

    def _apply_maintenance(self, path: str, entry: MaintenanceEntry) -> None:
        """Pin a node and record its entry, emitting a transition on change."""
        node = self._ensure_node(path)
        old = node.code
        node.maintenance = True
        node.update(StatusCode.MAINTENANCE, entry.reason)
        self._maintenance[node.path] = entry
        if node.code != old:
            self._emit(node, old)

    def _clear_node(self, path: str) -> bool:
        """Unpin a node and drop its entry. Returns whether anything was cleared."""
        node = self._find_node(path)
        key = node.path if node is not None else join_path(path)
        existed = self._maintenance.pop(key, None) is not None
        if node is None or not node.maintenance:
            return existed
        old = node.code
        node.maintenance = False
        node.update(StatusCode.UNDEFINED, None)
        if node.code != old:
            self._emit(node, old)
        return True

    def _persist(self) -> None:
        if self._maintenance_store is not None:
            self._maintenance_store.save(self._maintenance)

    def _ensure_node(self, path: str) -> Status:
        node = self._root
        for segment in split_path(path):
            child = _child_by_name(node, segment)
            if child is None:
                child = Status(join_path(node.path, segment))
                node.add_child(child)
            node = child
        return node

    def _find_node(self, path: str) -> Status | None:
        node = self._root
        for segment in split_path(path):
            child = _child_by_name(node, segment)
            if child is None:
                return None
            node = child
        return node

    def _snapshot(self, node: Status, now: datetime) -> StatusSnapshot:
        # Siblings render in natural, case-insensitive name order at every level —
        # deterministic, independent of check/discovery order (decisions.md). The
        # live tree keeps insertion order; only the snapshot is sorted.
        children = tuple(
            self._snapshot(child, now)
            for child in sorted(node.get_children(), key=lambda c: _sort_key(c.name))
        )
        age = _age_seconds(node.timestamp, now)
        stale_self = _is_stale(node, age)
        # A stale status degrades to at least WARN (worse-of) before rolling up.
        own = worst_of((node.code, STALE_DEGRADE)) if stale_self else node.code
        code = effective_code(own, (child.code for child in children))
        stale = stale_self or any(child.stale for child in children)
        return StatusSnapshot(
            path=node.path, name=node.name, own_code=node.code, code=code,
            reason=tuple(node.reason), timestamp=node.timestamp,
            description=node.description, frequency_seconds=node.frequency_seconds,
            config=node.config, about=node.about, title=node.title,
            maintenance=node.maintenance,
            maintenance_entry=self._maintenance.get(node.path), stale=stale,
            age_seconds=age, children=children)


def _sort_key(name: str) -> str:
    """Natural, case-insensitive ordering key for a sibling node's name: each digit
    run is zero-padded so numbers compare numerically (``node2`` before ``node10``,
    not after), and the rest is lower-cased. Used to order children in the
    snapshot (decisions.md)."""
    return re.sub(r"\d+", lambda m: m.group().zfill(12), name.lower())


def _child_by_name(node: Status, name: str) -> Status | None:
    for child in node.get_children():
        if child.name == name:
            return child
    return None


def _age_seconds(timestamp: str, now: datetime) -> float:
    """Seconds since ``timestamp`` (an ISO-8601 string), never negative."""
    try:
        observed = datetime.fromisoformat(timestamp)
    except ValueError:
        return 0.0
    return max(0.0, (now - observed).total_seconds())


def _is_stale(node: Status, age: float) -> bool:
    """A node is stale if it reports a real status on a schedule but hasn't been
    observed within roughly two of its intervals (ADR-0005)."""
    frequency = node.frequency_seconds
    if not frequency or node.maintenance or node.code == StatusCode.UNDEFINED:
        return False
    return age > frequency + max(float(frequency), STALE_MIN_GRACE_SECONDS)


# The single shared status tree for this process (ADR-0001).
status_tree = StatusTree()
