"""The single, in-memory, thread-safe status tree, its transition log and its
per-node status history.

One process owns one :class:`StatusTree` (ADR-0001). Writers and readers share a
single ``RLock``; reads copy an immutable snapshot under the lock and render it
outside (ADR-0002). Roll-up follows ADR-0039 via ``Status.get_status_code``.

Two histories are kept:
- the **event log** — every status transition, newest appended (the source), a
  state file the layer keeps across restarts (:meth:`StatusTree.events_payload`
  / :meth:`StatusTree.restore_events`, ADR-0071); and
- per-node **status history** — derived from the event log for one path
  (:meth:`StatusTree.history`).
"""
from __future__ import annotations

import re
import threading
from collections import deque
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from little_sister.maintenance import (
    MaintenanceEntry,
    MaintenanceStore,
    MaintenanceWrite,
)
from little_sister.reasons import ReasonInput
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

#: The contribution rule that maintenance is — the value :attr:`Event.suppressed_by`
#: carries when a pin (on the node, or on every one of its entries) is what kept a
#: transition from alarming. The first member of a vocabulary ADR-0032 rule 2
#: anticipates: `aggregation`, `dependency` and `damping` join it as those land.
MAINTENANCE_RULE = "maintenance"
STALE_MIN_GRACE_SECONDS = 30.0


@dataclass(frozen=True)
class ReasonLine:
    """One of a node's reasons, with its key and whatever is pinned on it.

    The **virtual child** of [ADR-0036] decision 7 and the ADR-0032: an
    entry with a pin contributes nothing to its node; the rest contribute their
    **own** ``code`` where the check declared one (ADR-0042), and the node's
    reported status where it did not — which is every entry that predates coded
    ones, unchanged. ``running`` marks a line whose subject has work in flight;
    it is display only (an ``is-running`` class and an italic — the words still
    say it) and never touches the roll-up: a red line whose job is re-running
    stays red.
    """
    slug: str
    text: str
    maintenance: MaintenanceEntry | None = None
    code: StatusCode | None = None
    running: bool = False

    @property
    def quiet(self) -> bool:
        """Whether this entry is suppressed. Quiet is **shown**, not hidden
        (ADR-0032 rule 5) — the surfaces render it in the maintenance color."""
        return self.maintenance is not None


@dataclass(frozen=True)
class RunFacts:
    """The last run's facts for the check that owns a node **alone** (ADR-0044):
    how long the run took, and when the next is due.

    ``wall_seconds`` is ``None`` for a secret-pinned check — it never runs
    (ADR-0023), so there is no honest duration. ``next_run_at`` is the engine's
    **armed slot**, projected onto the wall clock once, at write time — under the
    budgeted retry (ADR-0033) a failing check's slot is pulled in, which is why
    it is never computed from ``timestamp + frequency``; it is ``None`` for a
    one-shot run, which has no live schedule. Web-only until the client contract
    round (ADR-0008's batched revision), like ``reported_code`` before it.
    """
    wall_seconds: float | None
    next_run_at: str | None


@dataclass(frozen=True)
class StatusSnapshot:
    """Immutable copy of a node and its subtree, safe to read outside the lock.

    ``own_code`` is the node's own status; ``code`` is the effective, rolled-up
    status (ADR-0039). ``description`` and ``frequency_seconds`` are inherited from
    the check; ``config`` is the curated parameters it ran with (Markdown, ADR-0013);
    ``maintenance`` marks an admin override.

    ``own_code`` is a **derived** value, not simply what the check reported: an
    admin pin on the node reads ``MAINTENANCE`` (ADR-0014), and so does a node whose
    reasons are individually suppressible ``members`` and every one of them is
    pinned (ADR-0036). ``reported_code`` is what the check actually said, kept
    beside it — the row [ADR-0032](../docs/adr/0032-status-contribution-boundary.md)
    names as *the value the tree stores*, promoted to a field the moment ``own_code``
    stopped being it. Without it a silenced node's real answer would have nowhere to
    live, and "we are silencing an **error**" is exactly the transform rule 5 says a
    surface must show. ``reason`` stays the plain texts every existing surface reads;
    ``reasons`` carries the same lines with their keys and pins.

    ``timestamp`` is the observation time — ``None`` when no check has written this
    node (ADR-0027), while ``stale`` and ``age_seconds`` always measure the node's
    **own** stamp.

    ``run`` carries the owning check's last-run facts (ADR-0044) and resolves
    under the same condition as the inherited stamp: it is present exactly where
    the subtree holds **one** check — the sole mount itself and the unwritten
    ancestors above it — and ``None`` on a mount two checks share, on that
    mount's ancestors, and on the leaves *below* a branch mount, whose next
    update belongs to the node where the check is named.

    ``report`` is what the run **found** (ADR-0044), beside ``config``'s what it
    ran **with**. Both are the owning check's own text, so both answer to the
    same ownership rule as the run facts — one rule over four facts (decision 1)
    — and are **withheld on a node two or more checks mount**: two checks writing
    one field give it no single answer, and a value that flips between them is
    worse than none. The condition is local (this node's own mount count), so a
    child *below* a shared container keeps its own per-child text, which is where
    that shape's material belongs anyway.
    """
    path: str
    name: str
    own_code: StatusCode
    code: StatusCode
    reported_code: StatusCode
    reason: tuple[str, ...]
    timestamp: str | None
    description: str = ""
    frequency_seconds: int | None = None
    config: str = ""
    report: str = ""
    about: str = ""
    title: str = ""
    #: The declared sibling rank this node was sorted by (ADR-0055), ``0`` where
    #: nobody declared one. Carried so a surface can *see* the order it was handed
    #: rather than infer it; the JSON envelope does not emit it yet — that field
    #: rides the client contract round with the others held back for it.
    order: int = 0
    #: "This node's quiet lines are still information" (ADR-0063). ``None`` where
    #: nobody said, and a stated ``False`` is a declaration rather than a silence —
    #: the tri-state the seed and the fill both turn on. The web reads it; the JSON
    #: envelope does not carry it, and a client drawing its own chips is entitled to
    #: its own decision until the field joins the contract deliberately.
    show_when_quiet: bool | None = None
    maintenance: bool = False
    maintenance_entry: MaintenanceEntry | None = None
    stale: bool = False
    age_seconds: float = 0.0
    children: tuple[StatusSnapshot, ...] = ()
    reasons: tuple[ReasonLine, ...] = ()
    members: bool = False
    run: RunFacts | None = None

    @property
    def quiet_reasons(self) -> int:
        """How many of this node's entries are pinned. The card clamps its reasons
        to ``reason_cap``, so the pinned line may sit below the fold and this count
        is the only thing that always shows (ADR-0032 rule 5)."""
        return sum(1 for line in self.reasons if line.quiet)


@dataclass(frozen=True)
class Event:
    """A recorded transition of a node's own status code.

    ``suppressed_by`` names the **contribution rule** that kept this transition from
    reaching anybody, and is empty when nothing did. One crisp sentence defines it,
    and it is worth holding the field to: *an unmarked event is one that alarmed; a
    marked one is one that didn't.* If an event ever falsifies that, the marker is
    wrong rather than the sentence.

    It is a **name, not a boolean**. `maintenance: bool` would have been smaller
    today and wrong by the third policy: the aggregation clamp, the dependency shield
    and the damping counter each withhold a transition too, and four booleans would
    be four spellings of one property (ADR-0032 rule 2 puts them all at one point,
    and rule 5 says a surface names the rule that acted). One nullable string is also
    the shape the client-contract round will publish.

    Before the keystone this could not exist at all: a pinned node was not written,
    so there was no transition to mark. Recording them is what makes *did it break
    during the window?* answerable.
    """
    path: str
    name: str
    old: StatusCode
    new: StatusCode
    reason: tuple[str, ...]
    timestamp: str
    suppressed_by: str = ""

    def to_dict(self) -> dict[str, Any]:
        """The event as the state file carries it (ADR-0071): codes by name,
        the reason texts as a list."""
        return {"path": self.path, "name": self.name, "old": self.old.name,
                "new": self.new.name, "reason": list(self.reason),
                "timestamp": self.timestamp, "suppressed_by": self.suppressed_by}

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> Event:
        """One event back from the state file. Raises :class:`ValueError` on a
        shape this reader does not know — a code name it has no member for, a
        reason that is not a list of text — so the layer can report the file
        rather than half-read it."""
        try:
            old = StatusCode[str(data.get("old", ""))]
            new = StatusCode[str(data.get("new", ""))]
        except KeyError as error:
            raise ValueError(f"an event carries an unknown code: {error}") from error
        reason = data.get("reason", [])
        if not isinstance(reason, list) or not all(
                isinstance(text, str) for text in reason):
            raise ValueError("an event's reason is not a list of text")
        return cls(path=str(data.get("path", "")), name=str(data.get("name", "")),
                   old=old, new=new, reason=tuple(reason),
                   timestamp=str(data.get("timestamp", "")),
                   suppressed_by=str(data.get("suppressed_by", "")))


def events_from_payload(payload: object) -> list[Event]:
    """The events in a state file's payload, oldest first, or
    :class:`ValueError` when the payload is not the shape
    :meth:`StatusTree.events_payload` writes. Nothing is half-read: one event this
    reader cannot use refuses the whole file, and the layer reports it."""
    if not isinstance(payload, Mapping) or not isinstance(
            payload.get("events"), list):
        raise ValueError("no 'events' list")
    events: list[Event] = []
    for raw in payload["events"]:
        if not isinstance(raw, Mapping):
            raise ValueError("an event is not a mapping")
        events.append(Event.from_dict(raw))
    return events


@dataclass(frozen=True)
class StatusPeriod:
    """One stretch of time a node held a given status (status history).

    ``until`` is the observation that bounds the period — the next transition's
    stamp, or for the current one the node's own last check time. It is ``None``
    on the current period of a node **no check has ever written**: an admin pin
    can land on a container that never reported (``_emit`` says so outright), and
    that transition is real while the observation bounding it does not exist. The
    surfaces render the absence as ``—``, which is the honest reading; inventing
    the moment the admin acted would date the period by an act, not a check.
    """
    code: StatusCode
    since: str
    until: str | None
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
        # Per-entry pins (ADR-0036): the same side-table, keyed one level deeper —
        # ``(path, slug)``. Deliberately **outside** the check's output: the check
        # emits `slug -> text` and nothing else, and the snapshot joins the two, so
        # the next run cannot destroy a pin and nothing derived is written into the
        # tree (ADR-0032 rule 3).
        self._entry_maintenance: dict[tuple[str, str], MaintenanceEntry] = {}
        self._maintenance_store = maintenance_store
        # Check mounts: the nodes a check writes its result root to, seeded at
        # startup. Read only by the snapshot's timestamp roll-up (ADR-0027); the
        # tree itself stays check-agnostic and derives nothing into the nodes.
        # Mount path -> how many checks write there (ADR-0027 as amended by
        # ADR-0044): the count is what tells a sole-check mount, whose stamp an
        # unwritten ancestor may inherit, from a shared one, whose two run times
        # must not be attributed upward as if they were one.
        self._check_mounts: dict[str, int] = {}
        # The owning check's last-run facts per mount path (ADR-0044), written by
        # the engine after each run and resolved by the snapshot under the same
        # sole-check condition as the inherited stamp. Registry, not node state:
        # the facts belong to the check behind the node, and nothing derived is
        # stored on the nodes.
        self._run_facts: dict[str, RunFacts] = {}
        # How many reason entries the nodes hold between them — the count the
        # engine measures against its entry limit every tick (ADR-0072). Kept
        # here, on the one write path, so reading it never walks the tree.
        self._entry_count = 0

    def use_maintenance_store(self, store: MaintenanceStore) -> None:
        """Attach the persistence store (once, at startup, before restore)."""
        self._maintenance_store = store

    def upsert(self, path: str, code: StatusCode | str,
               reason: ReasonInput = None, *,
               members: bool = False,
               description: str | None = None,
               frequency_seconds: int | None = None,
               config: str | None = None,
               report: str | None = None,
               about: str | None = None,
               title: str | None = None,
               order: int | None = None,
               show_when_quiet: bool | None = None) -> bool:
        """Create-or-update the node at ``path`` and record a transition event if
        its own code changed. ``description`` / ``frequency_seconds`` / ``config``
        / ``report`` (inherited from the check) are stored when given — ``config``
        is static display metadata, never a transition (ADR-0013), and ``report``
        is per-run display metadata, equally never one (ADR-0044: what the run
        found is not a status claim; anything that alarms is a reason).

        ``report`` writes through **including the empty string**, which is how a
        run that found nothing clears what the last one found — a roster that
        outlives its run is a lie by the next tick. Nothing has to guard a shared
        container here: the snapshot withholds the text of a node two checks
        mount, so the last writer can no longer be believed there.

        ``reason`` is keyed (ADR-0036) and accepts any of the check-facing forms —
        a string, a list of strings, a ``{slug: text}`` mapping, ``(slug, text)``
        pairs, or already-normalized ``ReasonEntry`` values, which is what the
        engine passes. ``members`` marks the entries individually suppressible; a
        mapping or pairs list says so by its shape.

        ``about`` / ``title`` are the check-provided subnode labels (ADR-0025) and
        differ from the three above: where those write through, these **fill an
        empty field only** — a non-empty value seeds the node when its field is
        blank, but never overwrites one already set. A ``nodes.yaml`` declaration
        is seeded at startup (``set_about`` / ``set_title``) before the first tick,
        so it always wins; and once a label is filled it stays put (a later tick
        never rewrites it). Metadata, so no event either.

        ``order`` is the check's declared sibling rank (ADR-0055) and fills the
        same way — an **unset** field only, so ``set_order``'s startup seed from
        the configuration wins and a later tick never rewrites it. "Unset" here is
        ``None`` rather than a falsy value, which is the whole reason the node's
        field is nullable: ``0`` is a rank a configuration may state on purpose,
        and a deployment overruling what a check declared must be able to name the
        default value like any other.

        ``show_when_quiet`` (ADR-0063) fills the same way and reads "unset" the
        same way: ``None`` is nobody-said, and a ``False`` already on the node is a
        **statement** that a check's ``True`` must not fill over. That is the whole
        reason the field is nullable rather than a plain ``bool`` defaulting to
        false — the deployment's way of declining a declaration the check type
        ships is to write ``show_when_quiet: false`` in ``nodes.yaml``, and a
        falsy-means-empty fill would let the next tick overwrite it.

        A node under **maintenance** is written like any other: the pin is a
        contribution rule evaluated in the snapshot (ADR-0032 rule 3), not a value
        stamped into the tree, so the check keeps reporting and the tree keeps
        remembering. Thread-safe.
        """
        with self._lock:
            node = self._ensure_node(path)
            if description is not None:
                node.description = description
            if frequency_seconds is not None:
                node.frequency_seconds = frequency_seconds
            if config is not None:
                node.config = config
            if report is not None:
                node.report = report
            if about and not node.about:
                node.about = about
            if title and not node.title:
                node.title = title
            if order is not None and node.order is None:
                node.order = order
            if show_when_quiet is not None and node.show_when_quiet is None:
                node.show_when_quiet = show_when_quiet
            old = node.code
            held = len(node.reason_entries)
            node.update(code, reason, members)
            self._entry_count += len(node.reason_entries) - held
            if node.code == old:
                return False
            self._emit(node, old)
            return True

    @property
    def entry_count(self) -> int:
        """How many reason entries the tree holds, over every node — what the
        engine measures against its entry limit (ADR-0072). Maintained on
        :meth:`upsert`, the one path that writes entries, so the read is a
        number and never a walk. Thread-safe."""
        with self._lock:
            return self._entry_count

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

    def set_order(self, path: str, order: int) -> None:
        """Seed a node's declared sibling rank (ADR-0055) — like
        :meth:`set_about`, metadata only, no event.

        This is the **configured** half (``nodes.yaml``, or an inline ``order:`` on
        the check), run at startup before the first tick, so it beats whatever the
        check's result declares. ``0`` is a **real** declaration here and not a
        no-op: it is the only way a deployment can overrule a rank a check set by
        naming the default value.

        What it does *not* do is put that one node back where the alphabet would
        have it. ``0`` is the rank the unranked carry, so a node seeded with it
        sorts ahead of every positively-ranked sibling: in a set the check ranked
        ``1..5``, zeroing one child moves it to the **front**. Restoring plain
        alphabetical order across a ranked set means seeding ``0`` on **every**
        sibling. Thread-safe."""
        with self._lock:
            self._ensure_node(path).order = order

    def set_show_when_quiet(self, path: str, show_when_quiet: bool) -> None:
        """Seed a node's ``show_when_quiet`` (ADR-0063) — like :meth:`set_about`,
        metadata only, no event.

        The **configured** half (``nodes.yaml``, or an inline ``show_when_quiet:``
        on the check), run at startup before the first tick, so it beats whatever
        the check's result declares. ``False`` is a **real** declaration here and
        not a no-op: it is the only way a deployment can decline a claim a check
        type ships for every one of its installations. Thread-safe."""
        with self._lock:
            self._ensure_node(path).show_when_quiet = show_when_quiet

    def set_check_mount(self, path: str) -> None:
        """Register ``path`` as a **check mount** — the node a check writes its
        result root to, re-stamped on every run. Seeded at startup (the engine knows
        its checks; the tree stays check-agnostic) and read only by the snapshot's
        timestamp roll-up: an unwritten container above exactly one mount publishes
        that mount's observation time (ADR-0027).

        Unlike :meth:`set_about` this is **registry-only** — deliberately no
        ``_ensure_node``, so the tree's visible shape still grows only with results.
        The registry **counts checks per path** (ADR-0044, which amends
        ADR-0027): two checks legitimately sharing one mount register a count of
        two, so an ancestor above them inherits **no** stamp — the shared node's
        own last write answers for itself (rule 2), but attributed upward it would
        present one check's run time as both checks', which is rule 4's ambiguity.
        A set used to collapse the pair into a "sole" mount. Thread-safe."""
        with self._lock:
            key = join_path(path)
            self._check_mounts[key] = self._check_mounts.get(key, 0) + 1

    def set_run_facts(self, path: str, *, wall_seconds: float | None,
                      next_run_at: str | None) -> None:
        """Record the owning check's last-run facts for the mount at ``path`` —
        the run's wall time and the engine's **armed next slot** (ADR-0044).

        Registry-only, like :meth:`set_check_mount`: no node is created, nothing
        is stored on one, and the snapshot resolves the facts onto exactly the
        nodes whose subtree holds **one** check — never a shared mount, never
        its ancestors. ``next_run_at`` must come from the engine's schedule,
        already projected onto the wall clock: under the budgeted retry
        (ADR-0033) the armed slot is pulled in, which is why it is never
        computed from ``timestamp + frequency``.
        """
        with self._lock:
            self._run_facts[join_path(path)] = RunFacts(wall_seconds,
                                                        next_run_at)

    def set_maintenance(self, path: str, reason: str | None = None, *,
                        expires_at: datetime, set_by: str = "",
                        expected_set_at: str | None = None) -> MaintenanceWrite:
        """Pin the node at ``path`` to maintenance (a sticky admin override) until
        ``expires_at``, recording who set it. Stores the entry and writes it through
        (ADR-0014). Thread-safe.

        Setting a node that is **already pinned** is an edit: it keeps the entry's
        ``created_at`` / ``created_by`` and replaces the rest, so "one more day"
        keeps the original explanation and the original author.

        ``expected_set_at`` is the **compare-and-set token** (ADR-0014):
        the ``set_at`` the caller believes it is replacing, or ``""`` for *"I
        believe nothing is pinned"*. When it does not match what the table holds,
        **nothing is written** and the refusal carries the stored entry. ``None``
        — the default, and what the startup replay uses — writes unguarded.
        """
        moment = datetime.now().isoformat()
        with self._lock:
            key = join_path(path)
            stored = self._maintenance.get(key)
            if not self._token_matches(stored, expected_set_at):
                return MaintenanceWrite(False, stored, refused=True)
            entry = MaintenanceEntry(
                reason=reason or "maintenance",
                set_at=moment,
                expires_at=expires_at.isoformat(),
                set_by=set_by,
                created_at=stored.created_at if stored else moment,
                created_by=stored.created_by if stored else set_by)
            self._apply_maintenance(key, entry)
            self._persist()
            return MaintenanceWrite(True, entry)

    def clear_maintenance(self, path: str, *,
                          expected_set_at: str | None = None) -> MaintenanceWrite:
        """Release maintenance; the node shows the check's preserved reading again
        **at once**, not at the next run — nothing was destroyed while it was pinned
        (ADR-0041; see :meth:`_clear_node`). ``applied`` is ``False`` when it wasn't
        in maintenance.

        Clearing carries the same ``expected_set_at`` token as
        :meth:`set_maintenance` — clearing someone else's pin should not be the one
        write that stays silent (ADR-0014).
        """
        with self._lock:
            stored = self._maintenance.get(join_path(path))
            if not self._token_matches(stored, expected_set_at):
                return MaintenanceWrite(False, stored, refused=True)
            cleared = self._clear_node(path)
            if cleared:
                self._persist()
            return MaintenanceWrite(cleared, None)

    @staticmethod
    def _token_matches(stored: MaintenanceEntry | None,
                       expected_set_at: str | None) -> bool:
        """Whether a guarded write may proceed. ``None`` means unguarded; otherwise
        the token must equal the stored entry's ``set_at``, with ``""`` standing for
        *"nothing is pinned"*."""
        if expected_set_at is None:
            return True
        return (stored.set_at if stored is not None else "") == expected_set_at

    def restore_maintenance(self, entries: dict[str, MaintenanceEntry],
                            now: datetime | None = None,
                            entry_pins: dict[tuple[str, str],
                                             MaintenanceEntry] | None = None
                            ) -> None:
        """Replay persisted maintenance at startup (single worker, so once —
        ADR-0001): re-pin each **non-expired** entry, preserving its original
        ``set_at`` / ``expires_at``, and drop the rest, rewriting the file once.
        Replaying before any check has run is safe — the ``upsert`` guard keeps the
        pin (ADR-0014).

        ``entry_pins`` are the per-entry pins (ADR-0036). They restore into the
        side-table only — there is no node to pin and no status to write, and a
        slug the next run does not report simply does not apply."""
        moment = now or datetime.now()
        with self._lock:
            for entry_path, entry in entries.items():
                if not entry.is_expired(moment):
                    self._apply_maintenance(entry_path, entry)
            for key, entry in (entry_pins or {}).items():
                if not entry.is_expired(moment):
                    self._entry_maintenance[key] = entry
            self._persist()

    def adopt_maintenance(self, entries: dict[str, MaintenanceEntry],
                          entry_pins: dict[tuple[str, str],
                                           MaintenanceEntry] | None = None,
                          now: datetime | None = None) -> None:
        """Replace the side-table in a **running** process with ``entries`` and
        ``entry_pins`` — the store's at a takeover, the backup's on the way back
        (ADR-0077): the ``restore`` direction of the maintenance file. Under the
        one lock: every node pin the new table lacks, or carries expired, is
        cleared — a real ``MAINTENANCE -> reading`` transition with its event, as
        a sweep makes — and every non-expired pin it carries is applied, a set or
        an edit, with the event each earns; the per-entry pins are replaced
        whole. Nothing is written through: the file on disk is the copy being
        adopted, and the sweep drops what is expired from it."""
        moment = now or datetime.now()
        with self._lock:
            keep = {path for path, entry in entries.items()
                    if not entry.is_expired(moment)}
            for path in [path for path in self._maintenance if path not in keep]:
                self._clear_node(path)
            for entry_path, entry in entries.items():
                if entry_path in keep:
                    self._apply_maintenance(entry_path, entry)
            self._entry_maintenance = {
                key: entry for key, entry in (entry_pins or {}).items()
                if not entry.is_expired(moment)}

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
            # Expiry is the *only* thing that disposes of a per-entry pin, so this
            # sweep is its whole lifecycle end (ADR-0036 decision 6). It writes no
            # status and emits no event: the pin was never in the tree, and the
            # node's own code is derived at snapshot time (ADR-0032 rule 3).
            stale_entries = [key for key, entry in self._entry_maintenance.items()
                             if entry.is_expired(moment)]
            for key in stale_entries:
                del self._entry_maintenance[key]
            if expired or stale_entries:
                self._persist()
            return expired

    def reap_uncovered(self, check_roots: list[str]) -> list[str]:
        """Drop maintenance whose path **no check root covers** — segment-wise on one
        root-to-leaf line (:func:`on_same_line`). Run once at startup against the
        static check set (ADR-0014/0015); expiry is the backstop. Returns the reaped
        paths."""
        with self._lock:
            def covered(path: str) -> bool:
                return any(on_same_line(path, root) for root in check_roots)

            uncovered = [path for path in self._maintenance if not covered(path)]
            for path in uncovered:
                self._clear_node(path)
            orphan_entries = [key for key in self._entry_maintenance
                              if not covered(key[0])]
            for key in orphan_entries:
                del self._entry_maintenance[key]
            if uncovered or orphan_entries:
                self._persist()
            return uncovered

    def maintenance_entry(self, path: str) -> MaintenanceEntry | None:
        """The maintenance entry pinned at ``path``, if any."""
        with self._lock:
            return self._maintenance.get(path)

    # --- per-entry pins (ADR-0036) ---

    def set_entry_maintenance(self, path: str, slug: str,
                              reason: str | None = None, *,
                              expires_at: datetime, set_by: str = "",
                              expected_set_at: str | None = None
                              ) -> MaintenanceWrite:
        """Pin **one reason** of the node at ``path`` — the finding somebody is
        working on — leaving its siblings alarming, which is the entire point
        (ADR-0036).

        No status is written: the pin lives in the side-table under ``(path,
        slug)`` and the snapshot joins it, so the check's next run cannot destroy
        it. Carries the same compare-and-set token as the node pin (ADR-0014), and
        the same expiry rules. Thread-safe.
        """
        moment = datetime.now().isoformat()
        with self._lock:
            key = (join_path(path), slug)
            stored = self._entry_maintenance.get(key)
            if not self._token_matches(stored, expected_set_at):
                return MaintenanceWrite(False, stored, refused=True)
            entry = MaintenanceEntry(
                reason=reason or "maintenance",
                set_at=moment,
                expires_at=expires_at.isoformat(),
                set_by=set_by,
                created_at=stored.created_at if stored else moment,
                created_by=stored.created_by if stored else set_by)
            self._entry_maintenance[key] = entry
            self._persist()
            return MaintenanceWrite(True, entry)

    def clear_entry_maintenance(self, path: str, slug: str, *,
                                expected_set_at: str | None = None
                                ) -> MaintenanceWrite:
        """Release a per-entry pin. ``applied`` is ``False`` when there was none."""
        with self._lock:
            key = (join_path(path), slug)
            stored = self._entry_maintenance.get(key)
            if not self._token_matches(stored, expected_set_at):
                return MaintenanceWrite(False, stored, refused=True)
            existed = self._entry_maintenance.pop(key, None) is not None
            if existed:
                self._persist()
            return MaintenanceWrite(existed, None)

    def entry_maintenance(self, path: str, slug: str) -> MaintenanceEntry | None:
        """The pin on one reason of ``path``, if any."""
        with self._lock:
            return self._entry_maintenance.get((join_path(path), slug))

    def entry_maintenance_at(self, path: str) -> dict[str, MaintenanceEntry]:
        """Every per-entry pin held against ``path``, by slug — including slugs the
        current run did not report. **Absence suspends a pin; only expiry disposes
        of it** (ADR-0036 decision 6): a failed check replaces its whole reason map
        with ``check error: …``, so a delete-on-absence rule would throw away every
        pin on the node the moment the check has a bad minute."""
        node = join_path(path)
        with self._lock:
            return {slug: entry
                    for (entry_path, slug), entry in self._entry_maintenance.items()
                    if entry_path == node}

    def snapshot(self, path: str = "",
                 now: datetime | None = None) -> StatusSnapshot | None:
        """An immutable snapshot of the subtree at ``path`` (root by default), or
        ``None`` if no such node exists. Staleness is computed against ``now``
        (defaults to the current time), and each node's published ``timestamp`` is
        resolved against **this** subtree (ADR-0027) — so a branch never inherits
        from a check outside it. Thread-safe.
        """
        moment = now or datetime.now()
        with self._lock:
            node = self._find_node(path)
            return None if node is None else self._snapshot(node, moment)

    def effective(self, path: str = "") -> StatusCode | None:
        """The **effective** status at ``path`` (root by default), or ``None`` — what
        the node *is*, given its own status and its subtree.

        That is [ADR-0032](../docs/adr/0032-status-contribution-boundary.md)'s own
        definition, and its table names the field that holds it: ``StatusSnapshot``'s
        ``code``. So this reads the snapshot, and the contribution rules apply.

        Until the keystone that was a distinction without a difference — a pin was
        written into ``Status.code``, so the pure ADR-0039 walk and the effective
        status agreed by construction and this method could take the cheaper one. Now
        that a pin is *derived*, they answer different questions, and the two names
        the ADR gave them turn out to have been the right ones all along:
        :meth:`Status.get_status_code` stays the pure roll-up over stored readings
        (rule 3 requires exactly that of it), and this is what the node shows.
        """
        snapshot = self.snapshot(path)
        return None if snapshot is None else snapshot.code

    def recent_events(self, limit: int | None = None) -> tuple[Event, ...]:
        """Recorded transitions, oldest first (optionally only the last
        ``limit``)."""
        with self._lock:
            events = tuple(self._events)
        return events if limit is None else events[-limit:]

    def events_payload(self) -> dict[str, Any]:
        """The event log as the state layer keeps it (ADR-0071): copied under the
        lock, serialized outside it. The producer the layer calls on the
        scheduler tick."""
        return {"events": [event.to_dict() for event in self.recent_events()]}

    def adopt_events(self, payload: object) -> None:
        """The event log's ``restore`` direction (ADR-0077): an adopted file's
        payload — the store's at a takeover, the backup's on the way back — read
        by :func:`events_from_payload` and put in place of the log, oldest first,
        as at startup. A payload of another shape raises, and the layer reports
        the adoption as failed."""
        self.restore_events(events_from_payload(payload))

    def restore_events(self, events: Iterable[Event]) -> int:
        """Replace the log with ``events`` — the state file's, at startup before
        anything has written — keeping the bound: with more events than the log
        holds, the oldest are dropped. Nodes are untouched; a restored event
        describes a node the next run will write again, and history reads it from
        then on. Returns how many were kept."""
        with self._lock:
            self._events.clear()
            self._events.extend(events)
            return len(self._events)

    def history(self, path: str) -> list[StatusPeriod]:
        """The status history of the node at ``path`` — one period per status it
        has held, oldest first — derived from the event log. The current period's
        ``until`` is the last check time and its reason is the current one.

        **Suppressed transitions do not start a period.** History answers *what did
        this node show over time*, and a check that went red underneath a pin did not
        change what the node showed — it stayed in maintenance. Counting those would
        chop one maintenance window into a dozen phantom ERROR periods that no
        surface ever displayed. They stay in the event log, where they are exactly
        the answer to the other question: *did it break during the window?*
        """
        with self._lock:
            node = self._find_node(path)
            if node is None:
                return []
            events = [event for event in self._events
                      if event.path == node.path and not event.suppressed_by]
            if not events:
                return []
            # A check's transition only ever lands on a node it wrote, so a
            # stamp is the usual case — but an **admin pin** lands on a node
            # nobody has written (a container: `_emit` passes its own `when` for
            # exactly that), and then the current period has no observation to
            # end at. This used to be an `assert node.timestamp is not None`,
            # which made `/history/<pinned container>` a 500 and would have made
            # the branch page one the moment it asked for its own history.
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

    def _emit(self, node: Status, old: StatusCode,
              new: StatusCode | None = None, *,
              reason: tuple[str, ...] | None = None,
              when: str | None = None) -> None:
        """Record a transition of what this node **shows**.

        ``new`` defaults to the node's reported code, which is the whole story for a
        check's own write. An admin pin needs the other two: it moves the *derived*
        status without touching the reading (ADR-0032 rule 3), and it can land on a
        container no check has ever written — so it passes ``new`` explicitly and
        stamps the event with the moment the admin acted rather than with an
        observation time that may not exist.
        """
        stamp = when or node.timestamp
        # A check's event is never about an unobserved node (ADR-0027); an admin's
        # carries its own stamp, so one of the two is always there.
        assert stamp is not None
        self._events.append(Event(
            path=node.path, name=node.name, old=old,
            new=node.code if new is None else new,
            reason=tuple(node.reason) if reason is None else reason,
            timestamp=stamp,
            # An admin's own write (`new` given) is never suppressed: setting or
            # clearing a pin *is* the change, and it is what everyone sees.
            suppressed_by="" if new is not None else self._suppressing_rule(node)))

    def _suppressing_rule(self, node: Status) -> str:
        """Which contribution rule, if any, keeps this node's reading from reaching
        anybody right now — the value :attr:`Event.suppressed_by` carries.

        Both flavors of maintenance answer to the same name, because they are the
        same rule at two grains: a pin on the node, and a pin on every one of its
        entries so that nothing is left reporting (ADR-0036 decision 7). A node whose
        *check* reported ``MAINTENANCE`` is **not** marked — nothing suppressed it,
        it said so itself — and neither is a partly pinned node, whose unpinned
        entries still alarm.
        """
        if node.maintenance:
            return MAINTENANCE_RULE
        if node.members and node.reason_entries and all(
                (node.path, entry.slug) in self._entry_maintenance
                for entry in node.reason_entries):
            return MAINTENANCE_RULE
        return ""

    def _apply_maintenance(self, path: str, entry: MaintenanceEntry) -> None:
        """Pin a node and record its entry, emitting a transition on change — and on
        an **edit**, which the code alone cannot see.

        The pin is **recorded, never written** (ADR-0032 rule 3): the node keeps the
        check's reading and ``snapshot`` derives ``MAINTENANCE`` from the side table,
        exactly as it already does for a node whose entries are all pinned. That is
        what lets a silenced node still say what it is doing, lets clearing restore
        the last known state with nothing to restore, and lets the freshness path
        keep working underneath a pin.

        Editing a pin is ``MAINTENANCE -> MAINTENANCE``, so the code test is silent
        and an extended window or a rewritten reason would leave no trace anywhere.
        A changed reason or expiry therefore emits too; a re-submit that changes
        neither does not, so a double-click is not history (ADR-0014).
        """
        node = self._ensure_node(path)
        previous = self._maintenance.get(node.path)
        # What the node was showing: its existing pin, or the reading it reported.
        old = StatusCode.MAINTENANCE if previous is not None else node.code
        node.maintenance = True
        self._maintenance[node.path] = entry
        edited = previous is not None and not previous.same_pin_as(entry)
        if old != StatusCode.MAINTENANCE or edited:
            # The event's reason is the pin's own explanation — *why* it moved — not
            # the check's reading, which did not change and is still on the node.
            self._emit(node, old, StatusCode.MAINTENANCE,
                       reason=(entry.reason,) if entry.reason else (),
                       when=datetime.now().isoformat())

    def _clear_node(self, path: str) -> bool:
        """Unpin a node and drop its entry. Returns whether anything was cleared.

        Nothing is restored because nothing was destroyed: the node has been holding
        the check's real reading the whole time, so releasing the pin simply lets it
        show again — immediately, not at the next run.
        """
        node = self._find_node(path)
        key = node.path if node is not None else join_path(path)
        existed = self._maintenance.pop(key, None) is not None
        if node is None or not node.maintenance:
            return existed
        node.maintenance = False
        self._emit(node, StatusCode.MAINTENANCE, node.code,
                   when=datetime.now().isoformat())
        return True

    def _persist(self) -> None:
        if self._maintenance_store is not None:
            self._maintenance_store.save(self._maintenance,
                                         self._entry_maintenance)

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
        snapshot, _mounts, _mount_stamp, _mount_run = (
            self._snapshot_subtree(node, now))
        return snapshot

    def _snapshot_subtree(self, node: Status, now: datetime
                          ) -> tuple[StatusSnapshot, int, str | None,
                                     RunFacts | None]:
        """``node``'s snapshot, plus the values its parent needs to resolve its
        own observation time (ADR-0027) and run facts (ADR-0044): how many
        **checks** this subtree holds and, when that count is exactly one, the
        sole mount's own stamp and its check's last-run facts.

        One recursion computes all the roll-ups — effective code, staleness, the
        published timestamp and the run facts — under the one lock (ADR-0002).
        Nothing derived is stored on the nodes, so a topology change can never
        leave a stale roll-up behind.
        """
        # Siblings render by `(declared rank, natural case-insensitive name)` at
        # every level — deterministic and independent of check/discovery order
        # (ADR-0055). Nobody declaring a rank is the common case and leaves pure
        # alphabetical, exactly as before; the live tree keeps insertion order and
        # only the snapshot is sorted.
        results = tuple(
            self._snapshot_subtree(child, now)
            for child in sorted(node.get_children(), key=_sibling_key)
        )
        children = tuple(result[0] for result in results)
        # Count the *checks* below (per mount path — ADR-0044, which amends
        # ADR-0027) and keep the candidate stamp of the mount that is alone in its
        # own subtree; a second check anywhere — a second mount, or a second check
        # on one shared mount — makes any single value an attribution of one
        # check's run time to another check's data, so the candidate is dropped
        # rather than chosen.
        mounts = 0
        mount_stamp: str | None = None
        mount_run: RunFacts | None = None
        for _child, child_mounts, child_stamp, child_run in results:
            mounts += child_mounts
            if child_mounts == 1:
                mount_stamp = child_stamp
                mount_run = child_run
        own_checks = self._check_mounts.get(node.path, 0)
        if own_checks:
            mounts += own_checks
            mount_stamp = node.timestamp
            mount_run = self._run_facts.get(node.path)
        # The owning check's own **text** answers to the same rule as its run
        # facts (ADR-0044 decision 1): `config` and `report` belong to the check
        # that owns this node alone, so a node **two or more checks mount** has
        # no single answer and publishes neither. The condition is this node's
        # own count, not the subtree's: a child below a shared container keeps
        # its own per-child text, which is where that shape's material belongs.
        shared = own_checks > 1
        if mounts != 1:
            mount_stamp = None
            mount_run = None
        # Own stamp when a check has written this node; otherwise the sole mount's,
        # if the subtree holds exactly one. Staleness and `age_seconds` deliberately
        # keep reading the **own** stamp — an inherited time is a display value, not
        # an observation of this node (ADR-0005 stays untouched).
        age = _age_seconds(node.timestamp, now)
        stale_self = _is_stale(node, age)
        timestamp = node.timestamp if node.timestamp is not None else mount_stamp
        # The reasons, joined with whatever is pinned on them (ADR-0036 decision 5).
        # A pin whose slug this run did not report simply does not appear — it is
        # suspended, not deleted (decision 6, ADR-0032 rule 7).
        pins = self._entry_maintenance
        lines = tuple(
            ReasonLine(entry.slug, entry.text,
                       pins.get((node.path, entry.slug)) if node.members else None,
                       code=entry.code, running=entry.running)
            for entry in node.reason_entries)
        # Own status is now a **derived** value: the entries are virtual children,
        # and a node whose members are all pinned has nothing left reporting.
        own = _own_code(node.code, lines, node.members, node.maintenance)
        # Staleness judges the **raw** reading and is never suppressed — a check
        # that stopped running escalates whichever policy is holding its result
        # back (ADR-0032 rule 6, ADR-0036 decision 9), so what a stale node gives
        # its parent is its degraded raw code, not its quieted own status.
        rollup = worst_of((node.code, STALE_DEGRADE)) if stale_self else own
        code = effective_code(rollup, (child.code for child in children))
        stale = stale_self or any(child.stale for child in children)
        snapshot = StatusSnapshot(
            path=node.path, name=node.name, own_code=own, code=code,
            reported_code=node.code,
            reason=tuple(node.reason), timestamp=timestamp,
            description=node.description, frequency_seconds=node.frequency_seconds,
            config="" if shared else node.config,
            report="" if shared else node.report,
            about=node.about, title=node.title, order=node.order or 0,
            # Carried as the tri-state it is: `order` collapses to 0 because the
            # sort needs a number, while nothing downstream needs a boolean here —
            # and flattening `None` to `False` would throw away the one difference
            # the fill rule turns on (ADR-0063).
            show_when_quiet=node.show_when_quiet,
            maintenance=node.maintenance,
            maintenance_entry=self._maintenance.get(node.path), stale=stale,
            age_seconds=age, children=children,
            reasons=lines, members=node.members, run=mount_run)
        return snapshot, mounts, mount_stamp, mount_run


def _own_code(reported: StatusCode, lines: tuple[ReasonLine, ...],
              members: bool, pinned: bool) -> StatusCode:
    """A node's **own** status: the one transform that turns a stored reading into
    what the node shows (ADR-0032 rule 3). Both suppressions live here, which is the
    point — they are one model at one evaluation point, not two mechanisms.

    A **node pin** wins outright. It is an admin saying *do not count this node*,
    and it covers the node whole, so nothing below the pin can change the answer.

    Otherwise the node's entries are its **virtual children** (ADR-0036 decision 7;
    the ADR-0032), and the walk over them is the roll-up one level down
    (ADR-0039, made literal by ADR-0042): each unsuppressed entry contributes its
    **own** code where the check declared one, and the node's reported status where
    it did not; ``UNDEFINED`` contributions are ignored; the worst of what is
    counted wins. With nothing counted the answer depends on why — entries skipped
    because they are *pinned* (or carrying ``MAINTENANCE`` from a direct upsert)
    leave the node ``MAINTENANCE``, entries that merely have not reported leave it
    ``UNDEFINED`` — the ADR-0039 rule-5 tiebreak, unchanged. So pinning the one
    red line of an otherwise healthy coded set turns the node ``OK``, and pinning
    every line turns it ``MAINTENANCE``, exactly as with real children. Two kinds
    of node stay outside the rule entirely and read what they reported: one with
    **no** reasons (a check with a code and nothing to say), and one whose reasons
    are **prose**, which has no individually suppressible parts.

    What this function must never do is *lose* ``reported``. It is the check's real
    answer, it stays on the node, and it travels to the surfaces beside the derived
    value — so a silenced node can still say what it is silencing.
    """
    if pinned:
        return StatusCode.MAINTENANCE
    if not members or not lines:
        return reported
    counted: list[StatusCode] = []
    silenced = False
    for line in lines:
        if line.quiet:
            silenced = True
            continue
        code = line.code if line.code is not None else reported
        if code is StatusCode.MAINTENANCE:
            silenced = True
            continue
        if code is StatusCode.UNDEFINED:
            continue
        counted.append(code)
    if counted:
        return worst_of(counted)
    return StatusCode.MAINTENANCE if silenced else StatusCode.UNDEFINED


def _sort_key(name: str) -> str:
    """Natural, case-insensitive ordering key for a sibling node's name: each digit
    run is zero-padded so numbers compare numerically (``node2`` before ``node10``,
    not after), and the rest is lower-cased. Used to order children in the
    snapshot (ADR-0055)."""
    return re.sub(r"\d+", lambda m: m.group().zfill(12), name.lower())


def _sibling_key(node: Status) -> tuple[int, str]:
    """Where a node sorts among its siblings: its **declared rank** first, then the
    natural name order (ADR-0055).

    An undeclared rank reads ``0`` — the same value a check that says nothing
    hands over — so a set of siblings nobody ranked interleaves by name precisely
    as it did before ranks existed, and one ranked node only moves relative to
    that baseline. The rank says what a node is *about* (the severity it collects),
    never what status it happens to carry this minute; ordering by the live grade
    stays rejected, because a row that re-sorts on every poll cannot be read."""
    return (node.order or 0, _sort_key(node.name))


def _child_by_name(node: Status, name: str) -> Status | None:
    for child in node.get_children():
        if child.name == name:
            return child
    return None


def _age_seconds(timestamp: str | None, now: datetime) -> float:
    """Seconds since ``timestamp`` (an ISO-8601 string), never negative. An
    unobserved node (``None``, ADR-0027) has no age — 0.0, and ``_is_stale`` exempts
    it anyway, since a node with a real code was necessarily stamped."""
    if timestamp is None:
        return 0.0
    try:
        observed = datetime.fromisoformat(timestamp)
    except ValueError:
        return 0.0
    return max(0.0, (now - observed).total_seconds())


def _is_stale(node: Status, age: float) -> bool:
    """A node is stale if it reports a real status on a schedule but hasn't been
    observed within roughly two of its intervals (ADR-0005).

    **A pin does not exempt a node from this.** ADR-0032 rule 6 is explicit that a
    suppression may not also switch off the freshness path, or the pin that was meant
    to quiet a known state silently covers a dead check. This used to test
    ``node.maintenance`` and return ``False``, and that exemption was **load-bearing**
    while a pin still overwrote the reading: the caller degrades a stale node with
    ``worst_of((node.code, WARN))``, and ``worst_of`` knows only OK/WARN/ERROR, so a
    node holding a written-in ``MAINTENANCE`` reached it and raised. The two
    deviations propped each other up — correcting rule 3 is what makes rule 6 free.

    What replaces it is a guard on the **code**, which is what the arithmetic below
    actually requires: a node that never reported (``UNDEFINED``) has nothing to age,
    and one whose *check* reported ``MAINTENANCE`` carries no severity to degrade.
    That second case was never guarded before and could raise the same way.
    """
    frequency = node.frequency_seconds
    if not frequency or node.code in (StatusCode.UNDEFINED, StatusCode.MAINTENANCE):
        return False
    return age > frequency + max(float(frequency), STALE_MIN_GRACE_SECONDS)


# The single shared status tree for this process (ADR-0001).
status_tree = StatusTree()
