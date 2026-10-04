"""The single, in-memory, thread-safe status tree, its transition log and its
per-node status history.

One process owns one :class:`StatusTree` (ADR-0001). Writers and readers share a
single ``RLock``; reads copy an immutable snapshot under the lock and render it
outside (ADR-0002). Roll-up follows ADR-0039 via ``Status.get_status_code``.

Two histories are kept:
- the **event log** — every change of what a node shows, and every change of
  what its check reports that the node did not show (ADR-0107), newest appended
  (the source), a state file the layer keeps across restarts
  (:meth:`StatusTree.events_payload` / :meth:`StatusTree.restore_events`,
  ADR-0071); and
- per-node **status history** — derived from the event log for one path
  (:meth:`StatusTree.history`), the beginning of the period a node is in kept
  beside the log, where it outlives the row that began it (:class:`Beginning`,
  ADR-0110 decision 5).

**A restart is no transition** (ADR-0094): a node's first write after one is compared
with what the node last showed and what its check last reported, not with the
``UNDEFINED`` a restart leaves — the kept file says both for every node, beside the log
(:func:`nodes_from_payload`, ADR-0110), and the wait before an escalation counts from
the first. The instance's own node alone records the gap
(:meth:`StatusTree.close_unobserved`), from when the old process was last alive
(:func:`last_alive`) — which the stop's one save writes into the log
(:meth:`StatusTree.note_stop`).

**Every time here is an instant** (ADR-0120): a node's stamp, an event's, a
period's beginning and its two ends, a pin's three times, and the moment a method
is asked at. Each knows its zone and is held in UTC; none can be built without
one. The clock is :func:`little_sister.instants.now`, and the state file spells a
time through :func:`~little_sister.instants.stamp` and reads it back strictly.
"""
from __future__ import annotations

import re
import threading
from collections import deque
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from typing import Any

from little_sister import instants
from little_sister.codes import RANKED, escalates
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
    leaf_name,
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

#: The rule a **damping counter** is, when it holds an escalation back (backlog
#: #38 B). The second member of the vocabulary above; `aggregation` joins it when
#: that lands.
DAMPING_RULE = "damping"

#: The rule a **dependency shield** is: this node is reached through a check that is
#: failing, so its reading is not believed and its parent counts nothing of it
#: (backlog #38 A). *We could not get there* rather than *it is broken*.
DEPENDENCY_RULE = "dependency"

#: What a node contributes when its parent counted **nothing** of it because it had
#: not reported. Named for the envelope, where the rule has to have a word
#: (ADR-0080 decision 2).
UNDEFINED_RULE = "undefined"

#: The rules that change what a node **showed**, as against what it published.
#:
#: The distinction earns its own name because :meth:`StatusTree.history` turns on it,
#: and getting it wrong is silent. A pinned node showed `MAINTENANCE` throughout, so a
#: check that went red underneath it did not change what anybody saw and must not chop
#: one maintenance window into phantom periods. A **damped** node is the opposite case:
#: it went red at once, on its card, on its page and in the log — only the escalation
#: waited — so its transition is exactly a period of its own history, and dropping it
#: would break the one claim damping makes. A dependency shield will belong on this
#: side too, for the same reason: it keeps the node's own state and marks it.
HIDES_THE_READING = frozenset({MAINTENANCE_RULE})

#: What moved a node — the value :attr:`Event.cause` carries (ADR-0107 decision 3).
#: These are the kept log's words; a surface says each cause in its own.
#:
#: A **reading** is a check's run. A node's **pin** is written when it is set, when
#: it is edited and when it ends — cleared, expired or reaped — whatever that does
#: to what the node shows. A **line's pin** is written only where it changes what
#: its node shows, set or ended: nothing is written for a line by itself. A
#: **removal** is written for each node that leaves the tree. And a wait that ends
#: by its count writes that the node's status **reached** the level above.
CAUSE_READING = "reading"
CAUSE_PIN_SET = "pin-set"
CAUSE_PIN_EDITED = "pin-edited"
CAUSE_PIN_ENDED = "pin-ended"
CAUSE_LINE_PIN_SET = "line-pin-set"
CAUSE_LINE_PIN_ENDED = "line-pin-ended"
#: A node left the tree: its check said that its children are complete and no
#: longer returned it (ADR-0109 decision 5).
CAUSE_REMOVED = "removed"
#: A node's wait ended by its count (ADR-0119 decision 1): the reading that showed
#: the held status for the ``escalate_after``-th time in a row. The one row a
#: reading writes that is no change of what its node shows — the node has shown the
#: status since the row the wait held back, and what changed is what the level above
#: counts.
CAUSE_REACHED = "reached"

#: What a removal's row says for its reason: nothing about the node changed but
#: that it is gone, and this is why.
NO_LONGER_REPORTED = "no longer reported by its check"

#: How far back a node's **status changes** are counted, for the number its own page
#: shows. An hour, because that is the span an operator asking *is this thing
#: flapping?* has in mind, and because the event log is bounded: a window long enough
#: to outrun the log would report *what is still in the deque* rather than what
#: happened, and the number would quietly mean something different on a busy estate
#: than on a quiet one.
CHANGE_WINDOW_SECONDS = 3600.0
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
    #: What this line is about, as the provider's own identifier, or empty where
    #: the check did not say. Carried for the views that **group** by it; never an
    #: address, because a pin holds an identifier and only a line has one.
    subject: str = ""
    #: The **record** — what the check read about that subject, beside the sentence
    #: it wrote. Plain JSON types, validated and bounded at the ``CheckResult``
    #: seam, and ``None`` where the check carried none. Nothing on a card reads it;
    #: the node's own page renders it, and the line template, the grading seam and
    #: the series are each built on it later.
    data: dict[str, Any] | None = None
    #: Why the seam refused this line's record, where it did — ``data`` is then
    #: ``None`` — and empty everywhere else (ADR-0093). The line itself stands as its
    #: grading wrote it; the node's page says this where the record would be.
    refused: str = ""

    @property
    def quiet(self) -> bool:
        """Whether this entry is suppressed. Quiet is **shown**, not hidden
        (ADR-0032 rule 5) — the surfaces render it in the maintenance color."""
        return self.maintenance is not None


@dataclass(frozen=True)
class Contribution:
    """What a node's parent actually counted, where that is not the node's own
    effective code, and the rule that made it so (ADR-0032 rule 5, ADR-0080
    decision 2).

    ``code`` is **None** when the node was not counted at all, which is what
    *contributes nothing* has always meant for a pinned or unreported node. A rule
    that **delays** or **caps** a contribution puts a real code here instead: a
    damped node is counted, at the code it was publishing before the escalation it
    is holding back.

    ``by`` names the rule, so a surface can say which one acted rather than leaving
    a reader to infer it from a number that does not add up.
    """
    code: StatusCode | None
    by: str


@dataclass(frozen=True)
class Damping:
    """A node's confidence counter, while it is holding an escalation back.

    ``pending`` is the code the node is showing and not yet publishing, ``seen`` how
    many consecutive readings have said so, and ``needed`` how many this node was
    configured to want. Present on the snapshot **only while a hold is in force** —
    a node counting toward an escalation it has already made, or one whose
    ``escalate_after`` is 1, has nothing to show.

    It exists because a red leaf under a green parent is what a broken roll-up looks
    like: the node has to be able to say *2 of 3* on its card and its page, or the
    mechanism reads as the defect it is there to prevent.
    """
    pending: StatusCode
    seen: int
    needed: int


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
    round (ADR-0008), like ``reported_code`` before it.
    """
    wall_seconds: float | None
    next_run_at: datetime | None

    def __post_init__(self) -> None:
        if self.next_run_at is not None:
            object.__setattr__(self, "next_run_at", instants.utc(
                self.next_run_at, "a run's next_run_at"))


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
    node (ADR-0027) — and ``age_seconds`` always measures the node's **own** stamp.
    ``stale`` says that a reading is past its tolerance here **or beneath**: the
    node's own, or that of any node under it, so a branch is stale while one of its
    nodes is; ``own_stale`` says it of the node's own reading alone. A node its
    check stopped returning is such a node for as long as it stays in the tree; one
    whose parent says that its children are complete is removed instead
    (ADR-0109), and takes its staleness with it.

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
    timestamp: datetime | None
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
    #: How old this node's own reading may get before ``stale`` turns true — the
    #: tolerance :func:`node_stale_after` actually applied, in seconds, and ``None``
    #: where the node has neither a stated tolerance nor a period to imply one and
    #: can therefore never be stale by its own stamp (ADR-0079, ADR-0081). Carried
    #: rather than left to be re-derived: the rule has two branches now, and a reader
    #: that computes freshness from a frequency would hold a copy of neither.
    stale_after_seconds: float | None = None
    age_seconds: float = 0.0
    children: tuple[StatusSnapshot, ...] = ()
    reasons: tuple[ReasonLine, ...] = ()
    members: bool = False
    run: RunFacts | None = None
    #: What this node's **parent counted**, where that is not this node's ``code``,
    #: and the rule that made it so — ``None`` in the ordinary case, which is most
    #: nodes of a healthy tree. It is the one value a parent accumulates, so the
    #: roll-up reads it rather than ``code``.
    contribution: Contribution | None = None
    #: The hold a damping counter has on this node right now, or ``None``. Display
    #: only: what it holds back is already in ``contribution``.
    damping: Damping | None = None
    #: **What this node's check measured, and the object it measured** (ADR-0085):
    #: the run's own record, and the object's own identifier rather than this
    #: node's path. Empty and ``None`` on a node no check measures.
    subject: str = ""
    record: dict[str, Any] | None = None

    #: The path of the dependency shielding this node, or ``None``. ``contribution``
    #: already says *a dependency withheld this*; this says **which**, because one
    #: dependency shields dozens of dependents and a reader who cannot see which is
    #: left to guess what to go and look at.
    shielded_by: str | None = None

    #: How many times this node's own status **changed** within the last
    #: :data:`CHANGE_WINDOW_SECONDS`, counting only moves between `OK`, `WARN` and
    #: `ERROR`. Derived from the event log at snapshot time and stored nowhere: the
    #: transitions are already kept, and a second record of them would be a second
    #: thing to keep true.
    changes: int = 0

    #: Whether this node's **own** reading is past its tolerance. ``stale`` says
    #: that of the node *or of one beneath it*, which is the alarm a card carries;
    #: a surface that states a fact about this node's own reading — how long ago it
    #: was observed, or that it counts degraded — reads this one, and on a node
    #: with nothing beneath it the two are one.
    own_stale: bool = False

    @property
    def counted(self) -> StatusCode:
        """The code this node's parent accumulates.

        A rule that **transforms** the contribution — a damping counter holding an
        escalation — puts its value here. A rule that **withholds** the node names
        itself and carries no code, and then this is where the withholding actually
        happens: the parent accumulates `UNDEFINED`, which the roll-up skips
        (ADR-0039), because *nothing was counted* has no other spelling in a closed
        vocabulary (ADR-0032 decision 4).

        The two oldest withholding rules need no help from that: a pin and an
        unreported node already **are** `MAINTENANCE` and `UNDEFINED`, and the
        roll-up reads the difference between them (children that are all pinned make
        their parent `MAINTENANCE`, not `UNDEFINED`), so those two must pass their
        own code through untouched. Shielding is the first rule that withholds a node
        still holding a ranked reading of its own — which is precisely why it cannot
        be left to the roll-up.
        """
        if self.contribution is None:
            return self.code
        if self.contribution.code is not None:
            return self.contribution.code
        if self.code in (StatusCode.MAINTENANCE, StatusCode.UNDEFINED):
            return self.code
        return StatusCode.UNDEFINED

    @property
    def quiet_reasons(self) -> int:
        """How many of this node's entries are pinned. The card clamps its reasons
        to ``reason_cap``, so the pinned line may sit below the fold and this count
        is the only thing that always shows (ADR-0032 rule 5)."""
        return sum(1 for line in self.reasons if line.quiet)


@dataclass(frozen=True)
class Event:
    """A recorded change of what a node shows — or of what its check reports, where
    the node did not show it (ADR-0107).

    ``old`` and ``new`` are the node's **own status** before and after, as the
    snapshot derives it from the reading, the node's pin and its lines' pins. An
    event that a rule in :data:`HIDES_THE_READING` marks is the other kind of row:
    a change of the **reading** that the node did not show, with the reading's own
    codes. One run can write both, at one instant — the node's change, and beside
    it the reading's, where a line's pin hides part of what the check reports.

    Two kinds of row change nothing the node shows, and carry one status as both:
    an edit of a pin (ADR-0107 decision 1), and the row that ends a wait by its
    count, whose cause is :data:`CAUSE_REACHED` (ADR-0119). Neither begins a period.

    ``cause`` says what moved the node, one of the ``CAUSE_`` words, and
    ``reported`` what its check reported at that moment — which a restart reads
    where the kept file carries no table of its nodes (:func:`_last_readings`),
    and the count of a node's changes. An event read
    from a log written before them carries neither, ``""`` and ``None``; and the
    gap the instance's own node records (:meth:`StatusTree.close_unobserved`)
    names no cause, since none of these is one.

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
    timestamp: datetime
    suppressed_by: str = ""
    cause: str = ""
    reported: StatusCode | None = None

    def __post_init__(self) -> None:
        """``timestamp`` is an instant, held in UTC (ADR-0120): an event cannot be
        built with a time without a zone."""
        object.__setattr__(self, "timestamp", instants.utc(
            self.timestamp, "an event's timestamp"))

    def to_dict(self) -> dict[str, Any]:
        """The event as the state file carries it (ADR-0071): codes by name,
        the reason texts as a list, its instant in UTC as
        :func:`~little_sister.instants.stamp` spells one. The cause and what the
        check reported are keys only where the event says them, so an event read
        from a log written before them is written back as it was (ADR-0107
        decision 6)."""
        raw: dict[str, Any] = {
            "path": self.path, "name": self.name, "old": self.old.name,
            "new": self.new.name, "reason": list(self.reason),
            "timestamp": instants.stamp(self.timestamp),
            "suppressed_by": self.suppressed_by}
        if self.cause:
            raw["cause"] = self.cause
        if self.reported is not None:
            raw["reported"] = self.reported.name
        return raw

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> Event:
        """One event back from the state file. Raises :class:`ValueError` on a
        shape this reader does not know — a code name it has no member for, a
        reason that is not a list of text, a time that is not an instant with an
        offset — so the layer can report the file rather than half-read it."""
        said = data.get("reported")
        try:
            old = StatusCode[str(data.get("old", ""))]
            new = StatusCode[str(data.get("new", ""))]
            reported = None if said is None else StatusCode[str(said)]
        except KeyError as error:
            raise ValueError(f"an event carries an unknown code: {error}") from error
        reason = data.get("reason", [])
        if not isinstance(reason, list) or not all(
                isinstance(text, str) for text in reason):
            raise ValueError("an event's reason is not a list of text")
        return cls(path=str(data.get("path", "")), name=str(data.get("name", "")),
                   old=old, new=new, reason=tuple(reason),
                   timestamp=instants.instant(data.get("timestamp"),
                                              "an event's timestamp"),
                   suppressed_by=str(data.get("suppressed_by", "")),
                   cause=str(data.get("cause", "")), reported=reported)


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
class Beginning:
    """When the period a node is in began, as far as the tree knows (ADR-0110
    decision 5, ADR-0099 decisions 1 and 9).

    ``at`` is an instant as the tree stamps its events. Where the tree saw the
    period begin — a row that changed what the node shows — ``was`` is what the
    node showed before and ``cause`` what moved it: the two things a surface reads
    how a period began off (ADR-0099 decision 8). Where it did not, ``before`` says
    the instant is a **bound** — the period began before it, and nothing says how:
    a node's first reading with nothing kept of it, the oldest edit of a pin whose
    set had left the log, or the log's oldest event for a node the log held no row
    of. A bound is taken once and kept until the node changes."""
    at: datetime
    before: bool = False
    was: StatusCode | None = None
    cause: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(self, "at", instants.utc(
            self.at, "a period's beginning"))

    def to_dict(self) -> dict[str, Any]:
        """The keys an entry carries beside its two codes: ``since``, the instant
        spelled in UTC, and either ``before`` or how the period began — ``was``,
        and ``cause`` where the row that began it said one."""
        since = instants.stamp(self.at)
        if self.before:
            return {"since": since, "before": True}
        raw: dict[str, Any] = {"since": since}
        if self.was is not None:
            raw["was"] = self.was.name
        if self.cause:
            raw["cause"] = self.cause
        return raw


@dataclass(frozen=True)
class LastShown:
    """What the kept log says of one node, beside its rows (ADR-0110 decision 2):
    what the node last showed and what its check last reported — the two things its
    first reading in a new process is compared with. ``UNDEFINED`` where there was
    nothing — a node no check reports to — and where the rows of a file written
    before the table say only one of the two.

    ``began`` is when the period the node is in began (decision 5), ``None`` where
    the entry says nothing of it: a file written before an entry did, or a node no
    beginning is known of yet.

    ``publishes`` is what the node publishes to the level above while it **waits**
    before it escalates (ADR-0119 decision 4): the status it published before the
    one it shows. ``None`` for a node that is not waiting — which is every node of a
    file written before the key."""
    shows: StatusCode
    reported: StatusCode
    began: Beginning | None = None
    publishes: StatusCode | None = None

    def to_dict(self) -> dict[str, Any]:
        """The entry as the state file carries it: the two codes by name, what the
        node publishes where it is waiting, and the period's beginning where one
        is known."""
        return {"shows": self.shows.name, "reported": self.reported.name,
                **({} if self.publishes is None
                   else {"publishes": self.publishes.name}),
                **({} if self.began is None else self.began.to_dict())}


def _beginning_of(raw: Mapping[str, Any]) -> Beginning | None:
    """The beginning an entry carries, or ``None`` where it carries none.
    :class:`ValueError` where its keys are not what :meth:`Beginning.to_dict`
    writes: a time that is not an instant with an offset, a code or a flag that is
    none, how a period began without when, or a bound that says how."""
    since, was = raw.get("since"), raw.get("was")
    before, cause = raw.get("before", False), raw.get("cause", "")
    if since is None:
        if was is not None or "before" in raw or "cause" in raw:
            raise ValueError("a node's entry says how its period began, and not when")
        return None
    at = instants.instant(since, "a node's since")
    if not isinstance(before, bool) or not isinstance(cause, str):
        raise ValueError("a node's entry says how its period began in no way known")
    if was is not None and (not isinstance(was, str)
                            or was not in StatusCode.__members__):
        raise ValueError(f"a node's entry says no code it showed before: {was!r}")
    if before and (was is not None or cause):
        raise ValueError("a node's entry bounds its period, and says how it began")
    return Beginning(at, before=before,
                     was=None if was is None else StatusCode[was], cause=cause)


def nodes_from_payload(payload: object) -> dict[str, LastShown] | None:
    """What a state file's payload says every node last showed and last reported
    (ADR-0110 decision 2), by path — or ``None`` where it carries no such table: a
    file written before it, which a restart reads by its rows. :class:`ValueError`
    where the table is not the shape :meth:`StatusTree.events_payload` writes: like
    an event this reader cannot use, one entry refuses the whole file, and the layer
    reports it."""
    if not isinstance(payload, Mapping) or "nodes" not in payload:
        return None
    table = payload["nodes"]
    if not isinstance(table, Mapping):
        raise ValueError("the table of nodes is not a mapping")
    kept: dict[str, LastShown] = {}
    for path, raw in table.items():
        if not isinstance(raw, Mapping):
            raise ValueError("a node's entry is not a mapping")
        codes: list[StatusCode] = []
        for key in ("shows", "reported"):
            name = raw.get(key)
            if not isinstance(name, str) or name not in StatusCode.__members__:
                raise ValueError(f"a node's entry says no code it {key}: {name!r}")
            codes.append(StatusCode[name])
        waits = raw.get("publishes")
        if waits is not None and (not isinstance(waits, str)
                                  or waits not in StatusCode.__members__):
            raise ValueError(f"a node's entry says no code it publishes: {waits!r}")
        kept[join_path(str(path))] = LastShown(
            codes[0], codes[1], _beginning_of(raw),
            None if waits is None else StatusCode[waits])
    return kept


def stopped_at_of(payload: object) -> datetime | None:
    """The moment the stop's one save stamped into a state file's payload
    (:meth:`StatusTree.note_stop`), or ``None`` where it carries none — a log an
    interval wrote, a process that crashed (ADR-0094 decision 4).
    :class:`ValueError` where it carries one that is not an instant with an offset:
    like an event this reader cannot use, it refuses the whole file."""
    if not isinstance(payload, Mapping) or "stopped_at" not in payload:
        return None
    return instants.instant(payload["stopped_at"], "the log's stopped_at")


def last_alive(stopped_at: datetime | None,
               lease_beat: float | None) -> datetime | None:
    """When the old process was **last alive**, the start of the gap the instance's
    own node records (ADR-0094 decision 4): the later of the stop's stamp and the
    lease's last write before this process took it, as an instant — or ``None``
    where neither is known.

    The later wins because each can be the stale one: a stop's stamp stays in the
    log until the next process's first save, so a process that crashed before that
    left an older stop's stamp behind; and the lease is not carried by a keeper, so
    a fresh disk has none. The log's own last save is not asked at all — a kept
    file is written only when it changed, so on a quiet night it is hours old.
    """
    moments = [] if stopped_at is None else [stopped_at]
    if lease_beat is not None:
        moments.append(datetime.fromtimestamp(lease_beat, UTC))
    return max(moments) if moments else None


def _reported_after(event: Event, before: StatusCode | None) -> StatusCode | None:
    """What a node's check had last reported once ``event`` was written, given what
    it had reported ``before`` it.

    The event says so itself (ADR-0107 decision 4). One read from a log written
    before it could is worked out from its codes, as ADR-0094 decision 1 described:
    its ``new`` — passing over an admin's pin set, an unmarked event to
    ``MAINTENANCE``, which moves what a node shows and not what it read, and taking
    the reading the set left under it instead. A check that itself reported
    ``MAINTENANCE`` looks the same in such a log, and its first reading after a
    restart is then a change from the reading before, where none was owed: those
    rows do not tell the two apart, which is one of the things the field is for.
    """
    if event.reported is not None:
        return event.reported
    if event.new is StatusCode.MAINTENANCE and not event.suppressed_by:
        return before if event.old is StatusCode.MAINTENANCE else event.old
    return event.new


def _last_readings(events: Iterable[Event]
                   ) -> tuple[dict[str, StatusCode], dict[str, StatusCode]]:
    """What a restored log last recorded per path: what the node's check last
    **reported** and what the node last **showed** — the two things its first write
    after the restart is compared with, and a replayed pin with the second
    (ADR-0094 decisions 1 and 2, ADR-0107 decision 5).

    What a node showed is the code of its current period, as
    :meth:`StatusTree.history` reads it: the last event no rule hid from the
    display. What its check reported is what its last event says
    (:func:`_reported_after`).
    """
    read: dict[str, StatusCode] = {}
    shown: dict[str, StatusCode] = {}
    for event in events:
        if event.suppressed_by not in HIDES_THE_READING:
            shown[event.path] = event.new
        reported = _reported_after(event, read.get(event.path))
        if reported is not None:
            read[event.path] = reported
    return read, shown


@dataclass(frozen=True)
class _RanOut:
    """The pins of one node that a restart found expired in the pins file: its own,
    and its lines' by slug. They ran out while the instance was down, and nothing
    wrote their end; the node's first reading does (ADR-0107 decision 5). A node
    nothing reports to is not kept here: the restart writes its pin's end itself
    (:meth:`StatusTree.restore_maintenance`)."""
    node: bool = False
    lines: frozenset[str] = frozenset()


@dataclass(frozen=True)
class _Damped:
    """One node's damping state, in terms of what the node **shows** (ADR-0108):
    what it published upward, the worse status it is holding back (``None`` when it
    is holding nothing), and how many consecutive readings have shown it."""
    published: StatusCode
    pending: StatusCode | None
    seen: int


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

    ``previous`` is what the node showed before the period, as the event that
    begins it records, and what a surface reads off that a period which came
    after ``MAINTENANCE`` began where the node's maintenance ended (ADR-0099
    decision 8).

    ``cause`` is what that first event says moved the node (ADR-0107 decision 3),
    empty where it says nothing: a period that a line's pin began, set or ended,
    is neither a failure nor a recovery, and a surface says which it was.

    ``before`` says ``since`` is a **bound** and no beginning (ADR-0099 decisions
    1 and 9): the period began before that instant, and nothing says how. A first
    reading is one — the node was already what it showed when it was first seen —
    and so is the oldest edit of a pin whose set has left the log, and the bound
    a kept entry holds for a period whose beginning was lost.
    """
    code: StatusCode
    since: datetime
    until: datetime | None
    reason: tuple[str, ...]
    previous: StatusCode
    cause: str = ""
    before: bool = False


class StatusTree:
    """A thread-safe status tree plus a bounded log of status transitions."""

    def __init__(self, root_name: str = DEFAULT_ROOT_NAME,
                 event_log_size: int = DEFAULT_EVENT_LOG_SIZE,
                 maintenance_store: MaintenanceStore | None = None) -> None:
        self._lock = threading.RLock()
        self._root = Status(path="/", name=root_name)
        self._events: deque[Event] = deque(maxlen=event_log_size)
        # What the kept file last said of each node no check has written in this
        # process yet (ADR-0094, ADR-0107 decision 5): what its check last
        # reported and what the node last showed — its table's entries, or what
        # the rows of a file written before the table say (ADR-0110). Its first
        # write is compared with both and consumes them, and its wait counts from
        # the second; a pin set or ended before that write is written from the
        # second, and moves it. A node its check no longer reports is kept here
        # too, as one that shows nothing since it was removed (ADR-0109 decision
        # 5), until its row has left the log.
        self._restored_reading: dict[str, StatusCode] = {}
        self._restored_shown: dict[str, StatusCode] = {}
        # What each of those nodes published while it **waited** before it
        # escalated, where the kept file says that it was waiting (ADR-0119
        # decisions 4 and 5): its first write resumes the wait. It is read only
        # beside a status the node still shows that is worse than this one, so
        # what a pin or a removal has moved since says nothing, and neither does
        # what is left here of a node whose entry was forgotten.
        self._restored_published: dict[str, StatusCode] = {}
        # When the period each node is in began (ADR-0110 decision 5), for a node
        # a check has written and for one it has not yet: kept as the tree writes
        # (:meth:`_log`), restored from the file's table or worked out from its
        # rows, and written back with the table — so a period's beginning outlives
        # the row that began it.
        self._beginnings: dict[str, Beginning] = {}
        # The branches that begin with this process — the instance's own
        # (ADR-0099 decision 9): a first reading there is a beginning the tree saw.
        self._process_branches: tuple[tuple[str, ...], ...] = ()
        # The pins a restart found expired in their file, per node: nothing wrote
        # their end, and the node's first reading does.
        self._ran_out: dict[str, _RanOut] = {}
        # The moment of the stop, once the stop has come (ADR-0094 decision 4): the
        # log's producer writes it beside the events, so the stop's one save is the
        # one save that carries it.
        self._stopped_at: datetime | None = None
        # Maintenance side-table: path -> entry, kept in sync with each node's
        # ``maintenance`` bool and written through to ``maintenance_store`` on every
        # change (ADR-0014). No store (the default) means in-memory only. A pin is
        # held against its **path**, whether or not the tree holds a node there
        # (ADR-0109 decision 4): none is made for it, and one the tree makes at
        # the path takes it (:meth:`_furnish`).
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
        # The damping counter per path (backlog #38 B): what this node last
        # published upward, the worse status it is holding back, and how many
        # consecutive readings have shown it — the node's **own** status, what it
        # shows, and not the code its check reported (ADR-0108). Side-table for the
        # same reason the pins are one — nothing derived is written into the tree
        # (ADR-0032 rule 3) — and advanced on the **reading**, in `upsert`, because
        # a poll is not a reading and a counter that advanced per snapshot would
        # escalate a node nobody had asked about again.
        self._damping: dict[str, _Damped] = {}
        # What each check is reached **through** (backlog #38 A): the mount path of
        # a check, against the mount path of the check it depends on. Seeded at
        # startup by the engine, which knows its checks, exactly as the mounts are
        # — the tree stays check-agnostic and derives the shield in the snapshot.
        self._dependencies: dict[str, str] = {}
        # The owning check's last-run facts per mount path (ADR-0044), written by
        # the engine after each run and resolved by the snapshot under the same
        # sole-check condition as the inherited stamp. Registry, not node state:
        # the facts belong to the check behind the node, and nothing derived is
        # stored on the nodes.
        self._run_facts: dict[str, RunFacts] = {}
        # How many reason entries the nodes hold between them — the count the
        # engine measures against its entry limit every tick (ADR-0072). Kept
        # here, on the write paths — a reading, and a removal — so reading it
        # never walks the tree.
        self._entry_count = 0
        # What the configuration declared for a node, by path and by the node's
        # field (ADR-0012, ADR-0017, ADR-0055, ADR-0063): seeded once at startup,
        # and kept here because a node can leave the tree and return (ADR-0109) —
        # the node the tree makes then is given these again, before its check's own
        # labels may fill what is empty.
        self._seeded: dict[str, dict[str, Any]] = {}

    def use_maintenance_store(self, store: MaintenanceStore) -> None:
        """Attach the persistence store (once, at startup, before restore)."""
        self._maintenance_store = store

    def set_process_branch(self, path: str) -> None:
        """Say that the branch at ``path`` begins with this process — the
        instance's own (ADR-0099 decision 9). Nothing of it was there to be seen
        before the process, so a first reading at or beneath it is a beginning the
        tree saw, where any other node's is a bound: that node was already what it
        shows when it was first seen. Registration only, as a mount is; the engine
        says it of its own branch, before anything is restored."""
        segments = tuple(split_path(path))
        with self._lock:
            if segments not in self._process_branches:
                self._process_branches += (segments,)

    def upsert(self, path: str, code: StatusCode | str,
               reason: ReasonInput = None, *,
               members: bool = False,
               description: str | None = None,
               frequency_seconds: int | None = None,
               stale_after: float | None = None,
               config: str | None = None,
               report: str | None = None,
               about: str | None = None,
               title: str | None = None,
               order: int | None = None,
               show_when_quiet: bool | None = None,
               escalate_after: int | None = None,
               subject: str | None = None,
               record: dict[str, Any] | None = None) -> bool:
        """Create-or-update the node at ``path`` and record what the reading
        changed: what the node shows, and what its check reports where the node
        does not show it (:meth:`_record_reading`). Answers whether it recorded
        anything. ``description`` / ``frequency_seconds`` / ``config``
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

        ``escalate_after`` is how many consecutive readings of a **worse** code this
        node needs before it publishes that code upward (backlog #38 B). It is
        resolved by the engine — the check's own value, or the deployment's default
        — because the tree reads no configuration; it writes through like
        ``frequency_seconds``, and ``1`` is today's behavior.

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
            if stale_after is not None:
                node.stale_after = stale_after
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
            if escalate_after is not None:
                node.escalate_after = escalate_after
            # The run's measurement, written through on every reading like the
            # report: what was read last is what this node holds, and a run that
            # read nothing clears it rather than leaving yesterday's numbers to be
            # mistaken for today's (ADR-0085).
            if subject is not None:
                node.subject = subject
            if record is not None or subject is not None:
                node.record = record
            # What the node showed and what its check had reported, before this
            # reading. On the node's first write in this process both are what the
            # restored log last recorded for it, not the `UNDEFINED` a restart
            # leaves (ADR-0094 decision 1, ADR-0107 decision 5), and the write
            # consumes them.
            shown, reported = self._shown(node), self._reported(node)
            ran_out: _RanOut | None = None
            first_write = node.timestamp is None
            kept: StatusCode | None = None
            if first_write:
                kept = self._restored_shown.pop(node.path, None)
                self._restored_reading.pop(node.path, None)
                ran_out = self._ran_out.pop(node.path, None)
                # The count starts from what the node last showed (ADR-0110
                # decision 1): the counter takes it as published, so a worse first
                # reading waits like any other and a failure that stood stays
                # published. A node that was **waiting** at the stop goes on
                # waiting (ADR-0119 decision 5): it publishes what it published
                # before, and its count resumes with the one reading its held row
                # records — the readings between that row and the stop are not
                # kept.
                waited = self._restored_published.pop(node.path, None)
                if kept is not None:
                    self._damping[node.path] = (
                        _Damped(waited, kept, 1)
                        if waited is not None and escalates(waited, kept)
                        else _Damped(kept, None, 0))
            held = len(node.reason_entries)
            node.update(code, reason, members)
            self._entry_count += len(node.reason_entries) - held
            # Every reading advances the counter, including one that changed
            # nothing: *three consecutive readings of ERROR* is three readings, and
            # only the first of them is a transition.
            reached = self._damp(node)
            wrote = self._record_reading(node, shown, reported, ran_out)
            if reached and self._shields(instants.now()).get(node.path) is None:
                # The wait ended by its count: the one row a reading writes that
                # is no change of what its node shows (ADR-0119 decision 1).
                # Behind a shield nothing reached, and nothing is written
                # (decision 2).
                shows = self._own(node)
                self._emit(node, shows, shows, cause=CAUSE_REACHED)
                wrote = True
            if first_write:
                self._settle_period(node, first_sight=kept is None)
            return wrote

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
        self._seed(path, "about", about)

    def set_title(self, path: str, title: str) -> None:
        """Seed a node's ``title`` (a short display label; ADR-0017) — like
        :meth:`set_about`, metadata only, no event. Thread-safe."""
        self._seed(path, "title", title)

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
        self._seed(path, "order", order)

    def set_show_when_quiet(self, path: str, show_when_quiet: bool) -> None:
        """Seed a node's ``show_when_quiet`` (ADR-0063) — like :meth:`set_about`,
        metadata only, no event.

        The **configured** half (``nodes.yaml``, or an inline ``show_when_quiet:``
        on the check), run at startup before the first tick, so it beats whatever
        the check's result declares. ``False`` is a **real** declaration here and
        not a no-op: it is the only way a deployment can decline a claim a check
        type ships for every one of its installations. Thread-safe."""
        self._seed(path, "show_when_quiet", show_when_quiet)

    def _seed(self, path: str, field: str, value: Any) -> None:
        """Set one declared field of the node at ``path``, making the node where
        the tree has none, and keep the declaration for a node that leaves and
        returns (:meth:`_furnish`). Thread-safe."""
        with self._lock:
            self._seeded.setdefault(join_path(path), {})[field] = value
            setattr(self._ensure_node(path), field, value)

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

    def set_dependency(self, path: str, on_path: str) -> None:
        """Register that the check mounted at ``path`` is reached **through** the
        check mounted at ``on_path`` (backlog #38 A).

        Registry-only, like :meth:`set_check_mount`: no node is created and nothing
        is written onto one. Whether the shield is *in force* is derived in the
        snapshot, because it depends on what the dependency is reporting right now
        — which is the same rule every other contribution rule here follows
        (ADR-0032 rule 3). Thread-safe."""
        with self._lock:
            self._dependencies[join_path(path)] = join_path(on_path)

    def dependents(self, path: str) -> tuple[str, ...]:
        """The mount paths reached through the check at ``path``, in path order.

        One dependency shields dozens of dependents — that is its payoff and equally
        its risk, so the graph has to be **visible**: a node's page says how many
        checks are reached through it. Thread-safe."""
        with self._lock:
            key = join_path(path)
            return tuple(sorted(dependent for dependent, on
                                in self._dependencies.items() if on == key))

    def set_run_facts(self, path: str, *, wall_seconds: float | None,
                      next_run_at: datetime | None) -> None:
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
        ``expires_at``, an instant, recording who set it. Stores the entry and
        writes it through (ADR-0014). Thread-safe.

        The pin is held against the **path** (ADR-0109 decision 4). Where the tree
        holds no node there, none is made: the pin silences the node from the
        moment a check writes it, and until then it silences nothing.

        Setting a node that is **already pinned** is an edit: it keeps the entry's
        ``created_at`` / ``created_by`` and replaces the rest, so "one more day"
        keeps the original explanation and the original author.

        ``expected_set_at`` is the **compare-and-set token** (ADR-0014):
        the ``set_at`` the caller believes it is replacing, as it is spelled
        (:attr:`MaintenanceEntry.token`), or ``""`` for *"I believe nothing is
        pinned"*. When it does not match what the table holds,
        **nothing is written** and the refusal carries the stored entry. ``None``
        — the default, and what the startup replay uses — writes unguarded.

        A set that says what the stored pin says — the same reason, the same
        expiry — **changes nothing and writes nothing** (ADR-0104 decision 5): the
        pin keeps its ``set_at`` and its ``set_by``, since nobody changed it, and
        with them the token another open form holds. The guard is asked first: a
        stale token is refused whatever the form says.

        The write has **one instant**, the store's and the log's (ADR-0110 decision
        6): the row is dated as the entry's ``set_at`` — for a new pin its
        creation, so a restart finds the period's beginning and the pin's the same.
        """
        with self._lock:
            key = join_path(path)
            stored = self._maintenance.get(key)
            if not self._token_matches(stored, expected_set_at):
                return MaintenanceWrite(False, stored, refused=True)
            # Taken under the lock, so the log stays in the order it was written.
            moment = instants.now()
            entry = MaintenanceEntry(
                reason=reason or "maintenance",
                set_at=moment,
                expires_at=expires_at,
                set_by=set_by,
                created_at=stored.created_at if stored else moment,
                created_by=stored.created_by if stored else set_by)
            if stored is not None and stored.same_pin_as(entry):
                return MaintenanceWrite(False, stored)
            self._apply_maintenance(key, entry, when=moment)
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
        the token must equal the stored entry's ``set_at`` as it is spelled
        (:attr:`MaintenanceEntry.token`), with ``""`` standing for *"nothing is
        pinned"*."""
        if expected_set_at is None:
            return True
        return (stored.token if stored is not None else "") == expected_set_at

    def restore_maintenance(self, entries: dict[str, MaintenanceEntry],
                            now: datetime | None = None,
                            entry_pins: dict[tuple[str, str],
                                             MaintenanceEntry] | None = None
                            ) -> None:
        """Replay persisted maintenance at startup (single worker, so once —
        ADR-0001): re-pin each **non-expired** entry, preserving its original
        ``set_at`` / ``expires_at``, and drop the rest, rewriting the file once.
        Replaying before any check has run makes no node (ADR-0109 decision 4):
        each pin is held against its path, and the node its check then writes is
        pinned from its first reading — or stays away, where its check no longer
        reports it, and the pin with it, suspended.

        **A replayed pin's period begins at the pin's creation** (ADR-0110 decision
        6), which the store keeps: the tree did not see this pin set, and the row a
        replay writes, where the restored log does not hold the pin's period, is
        dated this start (:meth:`_date_pin`).

        ``entry_pins`` are the per-entry pins (ADR-0036). They restore into the
        side-table only — there is no node to pin and no status to write, and a
        slug the next run does not report simply does not apply.

        **Nothing is written for a pin that ran out while the instance was down**,
        where a check reports to the node: there is no reading yet to say what the
        node shows without it. Which pins did is remembered per node, and the
        node's first reading writes their end (ADR-0107 decision 5). A node
        **nothing reports to** — a branch pinned whole — has no reading to come:
        its pin's end is written here, at the pin's own expiry, to the
        ``UNDEFINED`` such a node shows, which claims nothing but that the pin
        ended. No node is made for it."""
        moment = _asked_at(now)
        with self._lock:
            for entry_path, entry in entries.items():
                key = join_path(entry_path)
                if not entry.is_expired(moment):
                    self._apply_maintenance(entry_path, entry, replay=True)
                elif (self._restored_shown.get(key) is StatusCode.MAINTENANCE
                      and self._restored_reading.get(key, StatusCode.UNDEFINED)
                      is StatusCode.UNDEFINED):
                    self._log(Event(
                        path=key, name=leaf_name(key), old=StatusCode.MAINTENANCE,
                        new=StatusCode.UNDEFINED, reason=(),
                        timestamp=entry.expires_at, cause=CAUSE_PIN_ENDED,
                        reported=StatusCode.UNDEFINED))
                    self._restored_shown[key] = StatusCode.UNDEFINED
                else:
                    self._ran_out[key] = _RanOut(node=True)
            for (entry_path, slug), entry in (entry_pins or {}).items():
                if not entry.is_expired(moment):
                    self._entry_maintenance[entry_path, slug] = entry
                else:
                    key = join_path(entry_path)
                    before = self._ran_out.get(key, _RanOut())
                    self._ran_out[key] = _RanOut(before.node, before.lines | {slug})
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
        an edit, with the event each earns, a pin new to this process beginning its
        period at its creation (:meth:`_date_pin`); the per-entry pins are replaced
        whole, first, and a node that shows something else for it gets the event
        of a line's pin that ended, or was set where none of its own went
        (ADR-0107 decision 1). Nothing is written through: the file on disk is
        the copy being adopted, and the sweep drops what is expired from it."""
        moment = _asked_at(now)
        with self._lock:
            adopted = {key: entry for key, entry in (entry_pins or {}).items()
                       if not entry.is_expired(moment)}
            went = {path for path, slug in self._entry_maintenance
                    if (path, slug) not in adopted}
            showing = self._showing(
                path for path, _slug in (*self._entry_maintenance, *adopted))
            self._entry_maintenance = adopted
            self._emit_line_pins(
                showing, lambda node: CAUSE_LINE_PIN_ENDED if node.path in went
                else CAUSE_LINE_PIN_SET)
            keep = {path for path, entry in entries.items()
                    if not entry.is_expired(moment)}
            for path in [path for path in self._maintenance if path not in keep]:
                self._clear_node(path)
            for entry_path, entry in entries.items():
                if entry_path in keep:
                    self._apply_maintenance(entry_path, entry)

    def sweep_expired(self, now: datetime | None = None) -> list[str]:
        """Clear every pin past its ``expires_at``, a node's and a line's — each a
        real transition of what its node shows, with its event (ADR-0014, ADR-0041
        decision 4, ADR-0107 decision 1). Returns the paths whose own pin was
        cleared. Called each scheduler tick."""
        moment = _asked_at(now)
        with self._lock:
            # Expiry is the *only* thing that disposes of a per-entry pin, so this
            # sweep is its whole lifecycle end (ADR-0036 decision 6). It writes no
            # status — the pin was never in the tree, and the node's own code is
            # derived (ADR-0032 rule 3) — and it is an event where the node shows
            # something else for it, one for a node however many of its lines'
            # pins ran out together (ADR-0107 decision 1). The lines go first: a
            # node whose own pin runs out in the same sweep then ends on what it
            # shows without either.
            stale_entries = [key for key, entry in self._entry_maintenance.items()
                             if entry.is_expired(moment)]
            showing = self._showing(path for path, _slug in stale_entries)
            for key in stale_entries:
                del self._entry_maintenance[key]
            self._emit_line_pins(showing, lambda node: CAUSE_LINE_PIN_ENDED)
            expired = [path for path, entry in self._maintenance.items()
                       if entry.is_expired(moment)]
            for path in expired:
                self._clear_node(path)
            if expired or stale_entries:
                self._persist()
            return expired

    def reap_uncovered(self, roots: list[str]) -> list[str]:
        """Drop maintenance whose path **none of ``roots`` covers** — the configured
        checks' roots and the instance's own, segment-wise on one root-to-leaf line
        (:func:`on_same_line`). Run once at startup against the static check set
        (ADR-0014/0015); expiry is the backstop. Returns the reaped paths."""
        with self._lock:
            def covered(path: str) -> bool:
                return any(on_same_line(path, root) for root in roots)

            uncovered = [path for path in self._maintenance if not covered(path)]
            for path in uncovered:
                self._clear_node(path)
            orphan_entries = [key for key in self._entry_maintenance
                              if not covered(key[0])]
            showing = self._showing(path for path, _slug in orphan_entries)
            for key in orphan_entries:
                del self._entry_maintenance[key]
            self._emit_line_pins(showing, lambda node: CAUSE_LINE_PIN_ENDED)
            if uncovered or orphan_entries:
                self._persist()
            return uncovered

    def forget_uncovered(self, roots: Iterable[str]) -> list[str]:
        """Drop what was restored of every node on none of ``roots``' lines — the
        configured checks' and the instance's own — as a pin no check covers is
        reaped (ADR-0110 decision 4, ADR-0014): nothing will read such a node, and
        its entry would be carried in the kept file for good. Run once at startup,
        after the pins' replay, which reads what was restored. Returns the paths
        forgotten, in their order."""
        lines = list(roots)
        with self._lock:
            gone = sorted(
                path for path in {*self._restored_shown, *self._restored_reading}
                if not any(on_same_line(path, root) for root in lines))
            for path in gone:
                self._restored_shown.pop(path, None)
                self._restored_reading.pop(path, None)
                self._beginnings.pop(path, None)
            return gone

    def prune(self, path: str, keep: Iterable[str], *,
              protect: Iterable[str] = ()) -> list[str]:
        """Remove every direct child of the node at ``path`` that ``keep`` does not
        name — what a node that says its children are complete no longer returns
        (ADR-0109 decisions 1 and 2). Answers the paths that left, a node's
        children before it, whether or not each wrote a row. Thread-safe.

        ``protect`` are the nodes other checks own. A child on the line of one —
        that node, one above it or one beneath it — is not this node's to remove:
        a run removes nothing another check wrote. Nothing beneath a child that is
        kept is looked at.

        **A removal takes the node and nothing kept about it** (decision 3). The
        subtree leaves the tree, with its lines and its counter. A pin held against
        a node of it, or against a line, stays in the side table: suspended, until
        a node returns at its path or the pin expires (decision 4). What the
        configuration declared for a node is the node's again when it returns
        (:meth:`_furnish`), and its readings are its check's to keep.

        **Each node removed writes an event** (decision 5): from what it showed to
        nothing, by the cause *removed*, every row of one call at one instant and
        a node's children before it. A node no check ever wrote, of which nothing
        is kept, leaves without one — a label its deployment declared, a container
        the tree made on the way to another node: nothing is removed that was
        never there.

        **The first run after a restart writes the same event.** The tree starts
        empty, so there is no node to remove; a path the kept file says showed
        something (ADR-0110), beneath this node through a child that is not kept,
        is ended by its row all the same, and a node that went while the process
        was down still ends its period. One the file says showed nothing is
        forgotten without a row, as a node that shows nothing leaves.

        What is kept of a removed node says from then on that it shows nothing
        since its removal, so its return is a change the tree saw, across a restart
        too; :meth:`_forget_removed` drops that with the row.
        """
        kept = set(keep)
        owned = [join_path(other) for other in protect]

        def theirs(child: str) -> bool:
            return any(on_same_line(child, other) for other in owned)

        with self._lock:
            parent = self._find_node(path)
            if parent is None:
                return []
            base = split_path(parent.path)
            leaving: dict[str, tuple[StatusCode, bool]] = {}
            for child in parent.get_children():
                if child.name in kept or theirs(child.path):
                    continue
                parent.remove_child(child.name)
                nodes = [child]
                while nodes:
                    node = nodes.pop()
                    nodes.extend(node.get_children())
                    leaving[node.path] = (self._shown(node),
                                          node.timestamp is not None)
                    self._entry_count -= len(node.reason_entries)
                    self._damping.pop(node.path, None)
            # What was restored of nodes the tree does not hold: beneath a child
            # that just left, or one that never came back after the restart. What
            # is kept of a node already removed stays: it is how its return is
            # told from a first sight (:meth:`_forget_removed`).
            for restored in {*self._restored_shown, *self._restored_reading}:
                segments = split_path(restored)
                if (restored in leaving or len(segments) <= len(base)
                        or segments[:len(base)] != base
                        or segments[len(base)] in kept
                        or self._was_removed(restored)
                        or theirs(join_path(*segments[:len(base) + 1]))):
                    continue
                leaving[restored] = (self._restored_shown.get(
                    restored, StatusCode.UNDEFINED), False)
            when = instants.now()
            gone = sorted(leaving, key=lambda left: (
                split_path(left)[len(base)], -len(split_path(left)), left))
            for left in gone:
                showed, written = leaving[left]
                if showed is StatusCode.UNDEFINED:
                    self._restored_shown.pop(left, None)
                    self._restored_reading.pop(left, None)
                    self._beginnings.pop(left, None)
                    if not written:
                        continue
                else:
                    self._restored_shown[left] = StatusCode.UNDEFINED
                    self._restored_reading[left] = StatusCode.UNDEFINED
                self._log(Event(
                    path=left, name=leaf_name(left), old=showed,
                    new=StatusCode.UNDEFINED, reason=(NO_LONGER_REPORTED,),
                    timestamp=when, cause=CAUSE_REMOVED,
                    reported=StatusCode.UNDEFINED))
            return gone

    def pins(self) -> tuple[dict[str, MaintenanceEntry],
                            dict[tuple[str, str], MaintenanceEntry]]:
        """Every pin held: a node's own by its path, and a line's by its path and
        its slug. A snapshot carries the pins of the nodes and lines it holds; this
        is the table whole, with the ones **no node stands for** (ADR-0109 decision
        4) — its node was removed, or no check has written it yet in this process.
        Such a pin silences nothing now, holds again the moment a node returns at
        its path, and ends by its own expiry. Thread-safe."""
        with self._lock:
            return dict(self._maintenance), dict(self._entry_maintenance)

    def maintenance_entry(self, path: str) -> MaintenanceEntry | None:
        """The maintenance entry pinned at ``path``, if any — the path read as
        every write here reads it, with or without its leading slash, so a
        form's ``branch`` finds the pin its own post made."""
        with self._lock:
            return self._maintenance.get(join_path(path))

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
        it. Carries the same compare-and-set token as the node pin (ADR-0014), the
        same expiry rules, and the same answer to a set that changes nothing: it
        writes nothing (:meth:`set_maintenance`). Thread-safe.

        **It is an event where it changes what the node shows** (ADR-0107 decision
        1) — the one failing line silenced turns the node green — and its reason
        is that line, by its text, and the pin's note. A pin that leaves the node
        showing what it showed writes none: one of two failing lines, an edit of
        a pin, a slug no run reports, a node no check has written.
        """
        moment = instants.now()
        with self._lock:
            key = (join_path(path), slug)
            stored = self._entry_maintenance.get(key)
            if not self._token_matches(stored, expected_set_at):
                return MaintenanceWrite(False, stored, refused=True)
            entry = MaintenanceEntry(
                reason=reason or "maintenance",
                set_at=moment,
                expires_at=expires_at,
                set_by=set_by,
                created_at=stored.created_at if stored else moment,
                created_by=stored.created_by if stored else set_by)
            if stored is not None and stored.same_pin_as(entry):
                return MaintenanceWrite(False, stored)
            showing = self._showing([key[0]])
            self._entry_maintenance[key] = entry
            self._emit_line_pins(
                showing, lambda node: CAUSE_LINE_PIN_SET,
                lambda node: (*(line.text for line in node.reason_entries
                                if line.slug == slug), entry.reason))
            self._persist()
            return MaintenanceWrite(True, entry)

    def clear_entry_maintenance(self, path: str, slug: str, *,
                                expected_set_at: str | None = None
                                ) -> MaintenanceWrite:
        """Release a per-entry pin. ``applied`` is ``False`` when there was none.
        An event where the node shows something else without it, as its set was
        (ADR-0107 decision 1), with the node's lines for its reason."""
        with self._lock:
            key = (join_path(path), slug)
            stored = self._entry_maintenance.get(key)
            if not self._token_matches(stored, expected_set_at):
                return MaintenanceWrite(False, stored, refused=True)
            showing = self._showing([key[0]])
            existed = self._entry_maintenance.pop(key, None) is not None
            if existed:
                self._emit_line_pins(showing, lambda node: CAUSE_LINE_PIN_ENDED)
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
        ``None`` if no such node exists. Staleness is computed against ``now``,
        an instant (the clock's by default), and each node's published
        ``timestamp`` is resolved against **this** subtree (ADR-0027) — so a branch
        never inherits from a check outside it. Thread-safe.
        """
        moment = _asked_at(now)
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
        scheduler tick.

        Beside the events it carries ``nodes``: what every node shows and what its
        check last reported, by path and in the paths' order (:meth:`_last_shown`,
        ADR-0110 decision 2). Either changes only with a row, so the table costs no
        write of its own.

        Once the stop has come (:meth:`note_stop`) it carries the moment of the
        stop beside the events, as ``stopped_at`` — new state, so the stop's one
        save writes the log even where no event changed, and the interval writes
        before it still skip an unchanged one (ADR-0094 decision 4)."""
        with self._lock:
            stopped_at = self._stopped_at
            events = tuple(self._events)
            self._forget_removed()
            nodes = self._last_shown()
        payload: dict[str, Any] = {
            "events": [event.to_dict() for event in events],
            "nodes": {path: nodes[path].to_dict() for path in sorted(nodes)}}
        if stopped_at is not None:
            payload["stopped_at"] = instants.stamp(stopped_at)
        return payload

    def note_stop(self, when: datetime | None = None) -> None:
        """Say that the stop has come, before its one save (ADR-0088): the log that
        save writes carries ``when`` — an instant, the clock's by default — so the
        next process knows when this one stopped watching (ADR-0094 decision 4).
        Thread-safe."""
        stopped = (instants.now() if when is None
                   else instants.utc(when, "the moment of the stop"))
        with self._lock:
            self._stopped_at = stopped

    def adopt_events(self, payload: object) -> None:
        """The event log's ``restore`` direction (ADR-0077): an adopted file's
        payload — the store's at a takeover, the backup's on the way back — read
        by :func:`events_from_payload` and put in place of the log, oldest first,
        as at startup, with the table it carries of what every node last showed
        (:func:`nodes_from_payload`). A payload of another shape raises — one time
        in it without a zone is such a shape, the stop's stamp included — and the
        layer reports the adoption as failed: nothing of it is taken."""
        events, nodes = events_from_payload(payload), nodes_from_payload(payload)
        stopped_at_of(payload)
        self.restore_events(events, nodes)

    def restore_events(self, events: Iterable[Event],
                       nodes: Mapping[str, LastShown] | None = None) -> int:
        """Replace the log with ``events`` — the state file's, at startup before
        anything has written — keeping the bound: with more events than the log
        holds, the oldest are dropped. Nodes are untouched; a restored event
        describes a node the next run will write again, and history reads it from
        then on. Returns how many were kept.

        **A restart is no transition** (ADR-0094 decision 1): what the log last
        recorded for each path is kept, and a node's **first** write in this
        process is compared with it rather than with the ``UNDEFINED`` a restart
        leaves — the same reading keeps its period, any other one changes from the
        old code. A node written already keeps comparing with its own code, which
        is what an adopted log in a running process meets (ADR-0077).

        ``nodes`` is the table the kept file carries beside its events (ADR-0110
        decisions 2 and 3): what every node last showed and what its check last
        reported, whether or not the log still holds a row of the node. Where the
        file carries it, it is what a first write is compared with, and a quiet
        node writes no ``UNDEFINED -> …`` at a start; a file written before it is
        read by its rows (:func:`_last_readings`), and a node the log holds no row
        of then has a first reading.

        With the two codes comes **when each node's period began** (decision 5):
        what its entry says, or — for an entry that says nothing of it, and for a
        file without the table — what the rows say (:meth:`_restore_beginnings`)."""
        with self._lock:
            self._events.clear()
            self._events.extend(events)
            told: dict[str, Beginning] = {}
            waited: dict[str, StatusCode] = {}
            if nodes is None:
                read, shown = _last_readings(self._events)
            else:
                read = {path: kept.reported for path, kept in nodes.items()}
                shown = {path: kept.shows for path, kept in nodes.items()}
                told = {path: kept.began for path, kept in nodes.items()
                        if kept.began is not None}
                waited = {path: kept.publishes for path, kept in nodes.items()
                          if kept.publishes is not None}
            self._restored_reading, self._restored_shown = read, shown
            self._restored_published = waited
            self._restore_beginnings(shown, told)
            return len(self._events)

    def close_unobserved(self, path: str, since: datetime, reason: str) -> bool:
        """End the restored period of the node at ``path`` at ``since``, an
        instant, with an event to ``UNDEFINED`` whose reason is ``reason`` — the
        instance's own node, where the old process stopped watching (ADR-0094
        decision 4). Its first write in this process is then a transition from
        ``UNDEFINED``, and its history reads the gap between.

        Writes nothing, and answers ``False``, where the restored log holds no
        reading of the node, or one of ``UNDEFINED`` already: there is no period to
        end. Only the node named is closed — the gap is said once. Thread-safe."""
        key = join_path(path)
        since = instants.utc(since, "the moment a node was last observed")
        with self._lock:
            reading = self._restored_reading.get(key)
            if reading is None or reading is StatusCode.UNDEFINED:
                return False
            self._log(Event(
                path=key, name=leaf_name(key), old=reading,
                new=StatusCode.UNDEFINED, reason=(reason,), timestamp=since,
                reported=StatusCode.UNDEFINED))
            self._restored_reading[key] = StatusCode.UNDEFINED
            self._restored_shown[key] = StatusCode.UNDEFINED
            return True

    def history(self, path: str) -> list[StatusPeriod]:
        """The status history of the node at ``path`` — one period per status it
        has held, oldest first — derived from the event log. The current period's
        ``until`` is the last check time and its reason is the current one.

        **A period is a run of events that show the same status** (ADR-0099
        decision 6). An edit of a pin is an event — a rewritten note or a longer
        window leaves its trace in the log (ADR-0014 decision 9) — and no period:
        the node showed ``MAINTENANCE`` before it and after it, so the period began
        where the pin was set. Every other event changes what the node shows, and a
        run of those is one event long.

        **A period's reason is what it said last** (decision 7). An ended one's is
        its last event's, which for a pin is the note as it stood when the period
        ended. The one that holds says what the node shows now: under a pin the
        stored pin's note as it stands — also on a branch nothing writes — and
        otherwise the node's own lines.

        **A transition that was hidden does not start a period** — but only one that
        was hidden from the *display*. History answers *what did this node show over
        time*, and a check that went red underneath a pin did not change what the node
        showed: it stayed in maintenance, and counting those would chop one window into
        a dozen phantom ERROR periods no surface ever displayed. A **damped**
        transition is not that case and is kept: the node went red immediately and
        everything but its parent's count said so, which is the whole claim damping
        makes (:data:`HIDES_THE_READING`). Every transition stays in the event log
        either way, where it answers the other question: *did it break during the
        window?*

        **The period a node is in begins where the tree kept it** (ADR-0110
        decision 5): the log is bounded, and once the row that began the period
        has left it — or all but the edits of a pin have — the beginning is the
        one the tree kept as it wrote, or restored from its file. So a node the
        log holds no row of still has its current period, from that instant or
        from *before* its bound, and only a node nothing is kept of has none.

        **A first reading is a bound** (ADR-0099 decision 9): a period whose first
        row is the oldest the log holds of what the node showed, from ``UNDEFINED``
        and by a reading, began before that row — the node was already what it
        showed when it was first seen — as one whose first row is an edit of a pin
        did (decision 6).
        """
        with self._lock:
            node = self._find_node(path)
            if node is None:
                return []
            events = [event for event in self._events
                      if event.path == node.path
                      and event.suppressed_by not in HIDES_THE_READING]
            # A check's transition only ever lands on a node it wrote, so a
            # stamp is the usual case — but an **admin pin** lands on a node
            # nobody has written (a container: `_emit` passes its own `when` for
            # exactly that), and then the current period has no observation to
            # end at. This used to be an `assert node.timestamp is not None`,
            # which made `/history/<pinned container>` a 500 and would have made
            # the branch page one the moment it asked for its own history.
            runs: list[list[Event]] = []
            for event in events:
                if runs and runs[-1][-1].new is event.new:
                    runs[-1].append(event)
                else:
                    runs.append([event])
            pin = self._maintenance.get(node.path)
            if pin is not None:
                current: tuple[str, ...] = (pin.reason,) if pin.reason else ()
            else:
                current = tuple(node.reason)
            periods: list[StatusPeriod] = []
            for index, run in enumerate(runs):
                is_current = index == len(runs) - 1
                until = node.timestamp if is_current else runs[index + 1][0].timestamp
                first = run[0]
                periods.append(StatusPeriod(
                    code=first.new, since=first.timestamp, until=until,
                    reason=current if is_current else run[-1].reason,
                    previous=first.old, cause=first.cause,
                    before=self._beginning_of_run(first, index == 0).before))
            began = self._beginnings.get(node.path)
            if began is None:
                return periods
            shows = self._shown(node)
            if not periods:
                # No row of the node is left: the period it is in, from what was
                # kept of its beginning.
                periods.append(StatusPeriod(
                    code=shows, since=began.at, until=node.timestamp,
                    reason=current,
                    previous=shows if began.was is None else began.was,
                    cause=began.cause, before=began.before))
            elif periods[-1].code is shows:
                # The rows hold the period and not its beginning — a pin whose set
                # has left the log — or say of it what the tree knows better. Where
                # they show something else — a log adopted from an instance that
                # read the node otherwise — they stand as they are. The period
                # before it ends where this one began: a pin the tree learned of
                # at a start began at its creation, before the row that start
                # wrote (decision 6). And rows that say the node began something
                # else after that instant stand: a store and a log that do not
                # belong together.
                last = periods[-1]
                if len(periods) > 1:
                    earlier = periods[-2]
                    if began.at < earlier.since:
                        return periods
                    periods[-2] = replace(earlier, until=began.at)
                periods[-1] = replace(
                    last, since=began.at, cause=began.cause, before=began.before,
                    previous=last.previous if began.was is None else began.was)
            return periods

    # --- internals; call only while holding the lock ---

    def _own(self, node: Status, ran_out: _RanOut | None = None) -> StatusCode:
        """What the node shows: its **own** status, by the one transform the
        snapshot applies to it (:func:`_own_code`, ADR-0032 rule 3) — the reading,
        the node's pin and its lines' pins.

        ``ran_out`` are pins to count as still in force: the ones a restart found
        expired, which is how a node's first reading tells whether their end is
        what changed it (ADR-0107 decision 5).
        """
        held = ran_out or _RanOut()
        pins = self._entry_maintenance
        lines = [((node.path, entry.slug) in pins or entry.slug in held.lines,
                  entry.code) for entry in node.reason_entries]
        return _own_code(node.code, lines, node.members,
                         node.maintenance or held.node)

    def _last_shown(self) -> dict[str, LastShown]:
        """What every node shows and what its check last reported, as the kept file
        says it beside the log (ADR-0110 decision 2). For a node a check has written
        in this process that is its own status, by the one derivation the snapshot
        and the log read (:meth:`_own`), and its reading; for one not written yet,
        what was restored. With them, when the node's period began (decision 5). A
        node that shows nothing and whose check reported nothing has no entry —
        unless the tree saw it begin to show nothing, which is a period like any
        other — so the table changes only where a row is written.

        An entry of a node that **waits** before it escalates says also what the
        node publishes meanwhile (ADR-0119 decision 4): from its counter for a node
        written in this process, and for one not written yet what was restored,
        while the node still shows the worse status it was waiting to publish. The
        key stands from the row the wait held back to the row that ends the wait, so
        it changes with a row as well — but for a count that completes behind a
        shield, which writes none."""
        nothing = StatusCode.UNDEFINED

        def waited(path: str) -> StatusCode | None:
            published = self._restored_published.get(path)
            if published is None or not escalates(
                    published, self._restored_shown.get(path, nothing)):
                return None
            return published

        kept = {path: LastShown(self._restored_shown.get(path, nothing),
                                self._restored_reading.get(path, nothing),
                                self._beginnings.get(path), waited(path))
                for path in {*self._restored_shown, *self._restored_reading}}
        nodes = [self._root]
        while nodes:
            node = nodes.pop()
            nodes.extend(node.get_children())
            if node.timestamp is not None:
                state = self._damping.get(node.path)
                kept[node.path] = LastShown(
                    self._own(node), node.code, self._beginnings.get(node.path),
                    state.published if state is not None
                    and state.pending is not None else None)
        return {path: entry for path, entry in kept.items()
                if entry.shows is not nothing or entry.reported is not nothing
                or entry.began is not None}

    def _forget_removed(self) -> None:
        """Drop what is kept of each removed node whose removal has left the log
        (ADR-0110 decision 4, ADR-0109 decision 5). Such an entry says that the
        node shows nothing since it was removed, which makes its return a change
        the tree saw; once the log no longer holds the row, nothing reads it, and
        a deployment whose subjects come and go would carry one for every node
        that ever left. It stays while a pin is held against the path: a replay
        reads from it that the pin is suspended."""
        removed = [path for path in self._restored_shown if self._was_removed(path)]
        if not removed:
            return
        logged = {event.path for event in self._events
                  if event.cause == CAUSE_REMOVED}
        for path in removed:
            if (path in logged or path in self._maintenance
                    or self._find_node(path) is not None):
                continue
            del self._restored_shown[path]
            self._restored_reading.pop(path, None)
            self._beginnings.pop(path, None)

    def _log(self, event: Event) -> None:
        """Append ``event`` to the log, and keep the beginning of the period it
        begins (ADR-0110 decision 5). A row that changes what its node shows begins
        one: at its instant, from what the node showed before, by its cause. An
        edit of a pin and the end of a wait show what the node showed already, and
        a row that a rule hid from the display is the reading's and not the node's:
        none of them begins a period (ADR-0099 decision 6, ADR-0119 decision 1)."""
        self._events.append(event)
        if (event.new is not event.old
                and event.suppressed_by not in HIDES_THE_READING):
            self._beginnings[event.path] = Beginning(
                event.timestamp, was=event.old, cause=event.cause)

    def _begins_with_process(self, path: str) -> bool:
        """Whether ``path`` is at or beneath a branch that begins with this
        process (:meth:`set_process_branch`)."""
        segments = tuple(split_path(path))
        return any(segments[:len(branch)] == branch
                   for branch in self._process_branches)

    def _settle_period(self, node: Status, *, first_sight: bool) -> None:
        """Say when the period began of a node a check has just written for the
        first time in this process, where no row said it.

        A node that shows nothing has no status to bound, and nothing is settled.

        **Nothing was kept of the node**: this is the first sight of it, and it was
        already what it shows (ADR-0099 decision 9). Its period is bounded by this
        reading, which replaces the beginning its row ``UNDEFINED -> …`` has just
        kept. The instance's own branch begins with its process, so there the
        row's beginning stands. A pin set on the node before its first reading is
        something kept of it (:meth:`_emit`), and what the pin began stands too.

        **Something was kept, and no beginning with it** — a file written before
        an entry said one, whose rows held none, read where the log was empty: the
        bound is taken now, once, and is the log's oldest event, or this reading
        where the log still holds none (ADR-0110 decision 5)."""
        path = node.path
        assert node.timestamp is not None
        if self._own(node) is StatusCode.UNDEFINED:
            return
        if first_sight:
            if not self._begins_with_process(path):
                self._beginnings[path] = Beginning(node.timestamp, before=True)
        elif path not in self._beginnings:
            oldest = self._events[0].timestamp if self._events else node.timestamp
            self._beginnings[path] = Beginning(oldest, before=True)

    def _first_sight(self, event: Event) -> bool:
        """Whether ``event``, a node's oldest row in the log, is a first reading of
        the node rather than a change the tree saw (ADR-0099 decision 9): it comes
        from ``UNDEFINED``, a reading wrote it, and the node is not on a branch that
        begins with the process. A row from a log written before a row said its
        cause is a reading's unless it goes to ``MAINTENANCE``, which there is an
        admin's pin set (:func:`_reported_after`)."""
        if (event.old is not StatusCode.UNDEFINED
                or self._begins_with_process(event.path)):
            return False
        if event.cause:
            return event.cause == CAUSE_READING
        return event.new is not StatusCode.MAINTENANCE

    def _beginning_of_run(self, first: Event, oldest: bool) -> Beginning:
        """What ``first``, the first row of a run of rows that show one status,
        says of when that period began; ``oldest`` says it is the node's oldest
        row in the log. An edit of a pin, and a first reading, bound the period;
        every other row began it."""
        if first.new is first.old or (oldest and self._first_sight(first)):
            return Beginning(first.timestamp, before=True)
        return Beginning(first.timestamp, was=first.old, cause=first.cause)

    def _restore_beginnings(self, shown: Mapping[str, StatusCode],
                            told: Mapping[str, Beginning]) -> None:
        """Put back when each node's period began, with the log and the two codes
        just restored (ADR-0110 decision 5).

        An entry that says it is taken at its word. One that does not — a file
        written before an entry did, or before the table — is read by the rows:
        the first row of the node's last period, where the log holds it; and where
        the log holds no row of the node, the bound is the log's oldest event,
        taken here and kept (ADR-0099 decision 1). With an empty log there is
        nothing to bound it by yet, and the node's first write takes it
        (:meth:`_settle_period`). A node that shows nothing has no status to bound,
        and gets none.

        A node a check has written already — an adopted file meets it in a
        running process (ADR-0077) — takes the file's beginning only where the
        file says the node shows what it shows, and says or shows when that began;
        otherwise it keeps what this process saw of it, as it goes on comparing
        with itself. What was kept of a node no check has written yet goes with
        the file it came from."""
        oldest_row: dict[str, Event] = {}
        first_of_run: dict[str, Event] = {}
        showing: dict[str, StatusCode] = {}
        for event in self._events:
            if event.suppressed_by in HIDES_THE_READING:
                continue
            oldest_row.setdefault(event.path, event)
            if showing.get(event.path) is not event.new:
                first_of_run[event.path] = event
            showing[event.path] = event.new
        oldest = self._events[0].timestamp if self._events else None
        began: dict[str, Beginning] = {}
        for path, beginning in self._beginnings.items():
            node = self._find_node(path)
            if node is not None and node.timestamp is not None:
                began[path] = beginning
        for path, showed in shown.items():
            node = self._find_node(path)
            if (node is not None and node.timestamp is not None
                    and showed is not self._own(node)):
                continue
            first = first_of_run.get(path)
            if path in told:
                began[path] = told[path]
            elif first is not None:
                began[path] = self._beginning_of_run(first,
                                                     first is oldest_row[path])
            elif oldest is not None and showed is not StatusCode.UNDEFINED:
                began[path] = Beginning(oldest, before=True)
        self._beginnings = began

    def _shown(self, node: Status) -> StatusCode:
        """What the node shows, as a change of it is measured from: its own status
        — or, for a node no check has written in this process, what the log last
        showed for it, since a restart is no transition (ADR-0094 decision 1)."""
        if node.timestamp is None:
            kept = self._restored_shown.get(node.path)
            if kept is not None:
                return kept
        return self._own(node)

    def _reported(self, node: Status) -> StatusCode:
        """What the node's check last reported: its reading — or, for a node no
        check has written in this process, what the log says it last reported."""
        if node.timestamp is None:
            return self._restored_reading.get(node.path, node.code)
        return node.code

    def _record_reading(self, node: Status, shown: StatusCode,
                        reported: StatusCode, ran_out: _RanOut | None) -> bool:
        """Write what the reading just stored changed, given what the node had
        ``shown`` and what its check had ``reported`` before it (ADR-0107
        decisions 1, 2 and 5). Answers whether it wrote anything.

        **What the node shows** is one row, and it reached: whoever looked saw it.
        It carries a rule's name only where one keeps the change from the node's
        parent (:meth:`_withholding_rule`). On a node's first reading after a
        restart its cause is the end of a pin, where one ran out while the instance
        was down and the node would still show what it showed had that pin held;
        everywhere else a reading moved it.

        **What its check reports, where the node does not show it,** is a row of
        its own with the reading's codes, held back: beneath the node's pin, as it
        always was, and now also where a line's pin hides it. Only a pin can — a
        node's own status is its reading unless one is in force
        (:func:`_own_code`) — so the rule that hid it is maintenance. One run
        writes both rows where it changes what the node shows and, differently,
        what its check reports.
        """
        shows = self._own(node)
        wrote = False
        if shows is not shown:
            cause = CAUSE_READING
            if ran_out is not None and self._own(node, ran_out) is shown:
                cause = CAUSE_PIN_ENDED if ran_out.node else CAUSE_LINE_PIN_ENDED
            self._emit(node, shown, shows, cause=cause,
                       mark=self._withholding_rule(node))
            wrote = True
        if node.code is not reported and (
                not wrote or (reported, node.code) != (shown, shows)):
            self._emit(node, reported, node.code, cause=CAUSE_READING,
                       mark=MAINTENANCE_RULE)
            wrote = True
        return wrote

    def _showing(self, paths: Iterable[str]) -> list[tuple[Status, StatusCode]]:
        """Each node among ``paths`` that the tree holds, with what it shows — taken
        before its lines' pins change, to see afterwards whether that changed it.
        A node no check has written in this process has no lines for a pin to
        act on, so it shows the same after as before, and its first reading
        settles it (ADR-0107 decision 5)."""
        showing: list[tuple[Status, StatusCode]] = []
        for path in sorted(set(paths)):
            node = self._find_node(path)
            if node is not None:
                showing.append((node, self._own(node)))
        return showing

    def _emit_line_pins(self, showing: list[tuple[Status, StatusCode]],
                        cause: Callable[[Status], str],
                        reason: Callable[[Status], tuple[str, ...]] | None = None
                        ) -> None:
        """Write the event of each node in ``showing`` that shows something else
        now that its lines' pins changed (ADR-0107 decision 1): one for a node,
        however many of its lines' pins went together, and none for one that
        shows what it showed. It reached, like a node's own pin (ADR-0041 decision
        8), and it is dated by the act."""
        when = instants.now()
        for node, shown in showing:
            shows = self._own(node)
            if shows is not shown:
                self._emit(node, shown, shows, cause=cause(node),
                           reason=None if reason is None else reason(node),
                           when=when)

    def _emit(self, node: Status, old: StatusCode, new: StatusCode, *,
              cause: str, mark: str = "",
              reason: tuple[str, ...] | None = None,
              when: datetime | None = None) -> None:
        """Record an event of this node (ADR-0107): a change of what it **shows**,
        from ``old`` to ``new`` — or, under a ``mark`` that hides the reading, a
        change of what its check reports that it did not show.

        The reason defaults to the node's lines, which is the whole story for a
        reading and for a pin's end. A pin passes its own — its note is *why* the
        node moved — and stamps the event with the moment the admin acted: it
        moves the derived status without touching the reading (ADR-0032 rule 3),
        and it can land on a container no check has ever written, where there is
        no observation time to borrow.

        Every event says what the check last reported (decision 4). For a node no
        check has written in this process that is what the log said last, and the
        event moves what the node's first reading will be compared with.

        **A row that a pin caused is published at once** (ADR-0108 decision 2): the
        counter that makes a node wait before it escalates takes what the node
        shows now as published. Only a reading starts a wait, so the readings after
        a pin's end start none, and a wait under way ends with the failure its pin
        silences. Every cause but a reading is a pin's here (decision 3) or the end
        of a wait, which has published the status already (ADR-0119): a removal is
        no event of a node the tree holds, and :meth:`prune` writes it.
        """
        stamp = when or node.timestamp
        # A check's event is never about an unobserved node (ADR-0027); an admin's
        # carries its own stamp, so one of the two is always there.
        assert stamp is not None
        reported = self._reported(node)
        self._log(Event(
            path=node.path, name=node.name, old=old, new=new,
            reason=tuple(node.reason) if reason is None else reason,
            timestamp=stamp, suppressed_by=mark, cause=cause, reported=reported))
        if node.timestamp is None:
            # Only a pin writes about a node no check has written yet, and a pin's
            # row is what the node shows.
            self._restored_shown[node.path] = new
        if cause != CAUSE_READING:
            self._damping[node.path] = _Damped(new, None, 0)

    def _damp(self, node: Status) -> bool:
        """Advance this node's confidence counter for the reading just stored, and
        answer whether that reading **ended a wait by its count** — which is the
        one way out of a wait that writes a row of its own (ADR-0119).

        The counter counts **what the node shows** (ADR-0108 decision 1): its own
        status, the one derivation the snapshot and the log read (:meth:`_own`),
        and not the code its check reported. The two differ wherever a line is
        pinned, and there the reported code counted readings the node did not show
        — a pinned line's failure spent the wait, and one that flapped restarted it
        at every reading. Beneath the node's own pin, or with every line pinned, it
        shows ``MAINTENANCE``, which is unranked: nothing is held there.

        It compares that status with what this node **last published**, not with
        what it last showed: while a hold is in force the published value is the
        older, quieter one, and each further reading of the worse status is another
        vote for the escalation being real.

        Four cases, and three of them clear the counter. A status that is equal to
        or better than what is published is published at once — recovery is
        immediate, which is the convention and what was settled. One that is not an
        *escalation* of a ranked code publishes at once too, so a node's very first
        reading, and any move through `UNDEFINED` or `MAINTENANCE`, is never
        delayed. A **different** worse status restarts the count, because it is a
        different claim and two readings that disagree are not two votes for either.
        Only the same worse status, again, advances it — and at ``escalate_after``
        it is published and the counter is done.

        Only a reading comes here. A change of what the node shows that a pin made
        is published as its row is written (:meth:`_emit`, ADR-0108 decision 2).

        The counter is memory, and a restart does not re-arm it: a node's first
        reading in a process is counted from what the node last showed, which the
        kept file says (:meth:`upsert`, ADR-0110 decision 1). A failure a restart
        finds waits, one that stood stays published, and a wait under way at a stop
        goes on, counted from the one reading its held row records (ADR-0119
        decision 5): the kept file says which nodes are waiting, and not how far
        each count had got — a state file for the counter itself would keep a value
        whose whole purpose is to be forgotten within a few minutes.
        """
        shows = self._own(node)
        state = self._damping.get(node.path)
        if state is None or not escalates(state.published, shows):
            self._damping[node.path] = _Damped(shows, None, 0)
            return False
        seen = state.seen + 1 if shows is state.pending else 1
        if seen >= max(1, node.escalate_after):
            self._damping[node.path] = _Damped(shows, None, 0)
            # A status published at its first reading was never held: only one the
            # counter was holding ends a wait.
            return shows is state.pending
        self._damping[node.path] = _Damped(state.published, shows, seen)
        return False

    def _withholding_rule(self, node: Status) -> str:
        """Which contribution rule, if any, keeps a change this node shows from
        reaching its parent right now: a failing dependency, which shields it, or
        a counter still waiting to escalate — the value
        :attr:`Event.suppressed_by` carries on a row that whoever looked at the
        node saw.

        Maintenance is not among them. A pin does not withhold a change the node
        shows: it keeps the node from showing one, at either grain — on the node,
        or on a line (ADR-0036 decision 7) — and that change is the other kind of
        row, which :meth:`_record_reading` marks. A node whose *check* reported
        ``MAINTENANCE`` is not marked at all — nothing suppressed it, it said so
        itself.
        """
        if self._shields(instants.now()).get(node.path) is not None:
            return DEPENDENCY_RULE
        state = self._damping.get(node.path)
        if state is not None and state.pending is not None:
            return DAMPING_RULE
        return ""

    def _apply_maintenance(self, path: str, entry: MaintenanceEntry, *,
                           replay: bool = False,
                           when: datetime | None = None) -> None:
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

        The event is written **from what the node showed** (ADR-0107 decision 1):
        its own status, which with a line pinned is not what its check reports —
        and, for a node no check has written in this process, what the log last
        showed for it. A new pin always writes its set, also over a node that
        showed ``MAINTENANCE`` already — its lines all pinned, or its check
        reporting it — because the pin's note is to leave a trace, as an edit's.

        A **replay** at startup is the one set that may write nothing (ADR-0094
        decision 2): a pin whose `MAINTENANCE` period the restored log holds
        continues it; one the log no longer holds records its set, from what the
        log last showed.

        ``when`` is the instant of a write the tree **sees**: an admin's set or
        edit, whose row is dated as the store dates it. Without it the tree is
        learning of the pin — at a start's replay, or with an adopted table — and
        the row is dated now; a pin new to the tree then begins its period at its
        creation and not at that row (:meth:`_date_pin`, ADR-0110 decision 6).

        **No node is made for a pin** (ADR-0109 decision 4): it is held against a
        path, and a node the tree makes at that path is pinned from its first
        moment (:meth:`_furnish`). So a replay brings back no node, and a pin can
        stand against a node its check no longer reports. That one is
        **suspended**: the path shows nothing with it or without it, so its set
        and its edit are written as rows that change nothing, a replay writes
        none, and it begins no period.
        """
        key = join_path(path)
        node = self._find_node(key)
        previous = self._maintenance.get(key)
        old = self._shows_at(key, node)
        prior = self._beginnings.get(key)
        suspended = node is None and self._was_removed(key)
        if node is not None:
            node.maintenance = True
        self._maintenance[key] = entry
        edited = previous is not None and not previous.same_pin_as(entry)
        continued = replay and (suspended or old is StatusCode.MAINTENANCE)
        if edited or (previous is None and not continued):
            # The event's reason is the pin's own explanation — *why* it moved — not
            # the check's reading, which did not change and is still on the node.
            self._emit_at(key, node, old,
                          old if suspended else StatusCode.MAINTENANCE,
                          cause=CAUSE_PIN_EDITED if edited else CAUSE_PIN_SET,
                          reason=(entry.reason,) if entry.reason else (),
                          when=when or instants.now())
        if previous is None and when is None and not suspended:
            self._date_pin(key, entry, old, prior)

    def _date_pin(self, path: str, entry: MaintenanceEntry, shown: StatusCode,
                  prior: Beginning | None) -> None:
        """Say when the period began of the node at ``path``, whose pin the tree
        has just learned of and did not see set (ADR-0110 decision 6): at the pin's
        creation, which the store keeps. ``shown`` is what the node showed before
        the pin was applied, and ``prior`` what was kept of when that began.

        A node that showed ``MAINTENANCE`` already keeps a beginning no later than
        the pin's creation — it showed that before it was pinned — and gives up a
        later one: the date of an earlier replay, or a bound. One that showed
        something else showed it until the pin was created, whatever instant the
        row just written carries."""
        created = entry.created_at
        was: StatusCode | None = shown
        if shown is StatusCode.MAINTENANCE:
            if prior is not None and prior.at <= created:
                return
            was = None if prior is None else prior.was
        self._beginnings[path] = Beginning(created, was=was, cause=CAUSE_PIN_SET)

    def _clear_node(self, path: str) -> bool:
        """Unpin a node and drop its entry. Returns whether anything was cleared.

        Nothing is restored because nothing was destroyed: the node has been holding
        the check's real reading the whole time, so releasing the pin simply lets it
        show again — immediately, not at the next run. The event ends on **what the
        node shows** without the pin (ADR-0107 decision 1): its reading, less what
        its lines' pins still silence, and ``UNDEFINED`` for a node no check has
        written in this process, which shows nothing until one does.

        A pin the tree holds no node for ends with its row all the same (ADR-0107
        decision 1, ADR-0109 decision 4): to nothing where the path showed
        ``MAINTENANCE`` — a node not written yet since the start — and from
        nothing to nothing where the pin was suspended.
        """
        node = self._find_node(path)
        key = node.path if node is not None else join_path(path)
        existed = self._maintenance.pop(key, None) is not None
        if node is None:
            if existed:
                old = self._shows_at(key, None)
                self._emit_at(key, None, old,
                              StatusCode.UNDEFINED
                              if old is StatusCode.MAINTENANCE else old,
                              cause=CAUSE_PIN_ENDED, reason=(),
                              when=instants.now())
            return existed
        if not node.maintenance:
            return existed
        node.maintenance = False
        self._emit(node, StatusCode.MAINTENANCE, self._own(node),
                   cause=CAUSE_PIN_ENDED, when=instants.now())
        return True

    def _shows_at(self, path: str, node: Status | None) -> StatusCode:
        """What the node at ``path`` shows, as a change of it is measured from
        (:meth:`_shown`) — and, where the tree holds no node there, what was kept
        of one: what the log last showed for it, or nothing."""
        if node is not None:
            return self._shown(node)
        return self._restored_shown.get(path, StatusCode.UNDEFINED)

    def _was_removed(self, path: str) -> bool:
        """Whether what is kept of ``path`` says that its node was removed and has
        not returned (ADR-0109 decision 5): it shows nothing, since a removal."""
        began = self._beginnings.get(path)
        return (began is not None and began.cause == CAUSE_REMOVED
                and self._restored_shown.get(path) is StatusCode.UNDEFINED)

    def _emit_at(self, path: str, node: Status | None, old: StatusCode,
                 new: StatusCode, *, cause: str, reason: tuple[str, ...],
                 when: datetime) -> None:
        """Record a pin's event at ``path``, dated ``when`` — the act's instant:
        through the node where the tree holds one (:meth:`_emit`), and otherwise as
        a row of the path alone, which moves what is kept of it as an unwritten
        node's row does."""
        if node is not None:
            self._emit(node, old, new, cause=cause, reason=reason, when=when)
            return
        self._log(Event(
            path=path, name=leaf_name(path), old=old, new=new, reason=reason,
            timestamp=when, cause=cause,
            reported=self._restored_reading.get(path, StatusCode.UNDEFINED)))
        self._restored_shown[path] = new

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
                self._furnish(child)
                node.add_child(child)
            node = child
        return node

    def _furnish(self, node: Status) -> None:
        """Give a node the tree has just made what is held against its path: the
        labels the configuration declared for it, and the pin on it. Both are kept
        beside the nodes, so a node that left the tree and returns is what it was
        to its deployment and to its admin (ADR-0109 decisions 3 and 4)."""
        for name, value in self._seeded.get(node.path, {}).items():
            setattr(node, name, value)
        node.maintenance = node.path in self._maintenance

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
            self._snapshot_subtree(node, now, self._change_counts(now),
                                   self._shields(now)))
        return snapshot

    def _shields(self, now: datetime) -> dict[str, str]:
        """Which nodes are **shielded** right now, and by which dependency.

        Resolved once for the whole tree, before the recursion, because a
        dependency may sit outside the subtree being rendered — a service inside
        the VPN is snapshotted on its own page while the check that reaches it
        lives somewhere else entirely.

        A dependency shields only when it is **failing** — `ERROR` and nothing
        less. The shape this rule exists for is *a unit that cannot be reached*,
        and a gateway reporting `WARN` has not stopped anybody reaching anything;
        shielding on it would silence a subtree because something was amber, which
        is the direction *fail toward alarming* refuses.

        It applies **whatever the dependent itself is reporting**, its `OK` included.
        The shield is a statement about evidence, not a filter on bad news: letting
        an `OK` through because it alarms nobody would put green on the dashboard for
        a unit nobody could reach, on the strength of a reading taken through a
        broken path. *Nothing here is reporting* is the true sentence, and the
        dependency's own `ERROR` is what the operator is meant to be looking at.

        Three ways a shield does **not** apply, and each is that same invariant:
        a dependency that has never reported or is **stale** does not shield, since
        silence is exactly the state a naive implementation would treat as
        permission; a dependency that is **itself shielded** does not shield on,
        so one red root cannot quiet half a tree through two hops with nothing
        saying why; and a **stale dependent** is not shielded, because a check that
        stopped running must escalate whatever else is true of it (ADR-0032 rule 6).
        """
        resolved: dict[str, str | None] = {}

        def shield_for(path: str) -> str | None:
            if path in resolved:
                return resolved[path]
            # Cycles are refused at startup; this guard is what makes the
            # recursion safe to read rather than safe by argument alone.
            resolved[path] = None
            on = self._dependencies.get(path)
            if on is None:
                return None
            node, gate = self._find_node(path), self._find_node(on)
            if node is None or gate is None:
                return None
            if gate.code is not StatusCode.ERROR:
                return None
            if _is_stale(gate, _age_seconds(gate.timestamp, now)):
                return None
            if _is_stale(node, _age_seconds(node.timestamp, now)):
                return None
            if shield_for(on) is not None:
                return None
            resolved[path] = on
            return on

        shields: dict[str, str] = {}
        for path in self._dependencies:
            on = shield_for(path)
            if on is not None:
                shields[path] = on
        return shields

    def _change_counts(self, now: datetime) -> dict[str, int]:
        """How often each node's own status changed inside the window, from the log
        that already holds every transition.

        One pass for the whole snapshot rather than a walk per node: the deque is
        bounded and the recursion is not, so counting per node would make the cost
        of a poll the product of the two.

        **Only moves between ranked codes count.** A node's first reading is
        `UNDEFINED` to something, which every node does once at startup and which is
        not a change of mind; counting it would put a 1 beside every node on the
        dashboard for an hour after a restart and teach the reader to ignore the
        number. **Suppressed transitions do count**, and that is the difference from
        the history: this number is about the subject's behavior, not about what the
        surface showed, so a check flapping underneath a pin is exactly the thing
        worth seeing.

        So what is counted is a change of **what the check reported**, which every
        event says (ADR-0107 decision 4): a pin's row is none — the node moved and
        its check said what it had said — and a run that wrote two rows is one. An
        event from a log written before it could say so counts by its own codes,
        as it was counted.
        """
        counts: dict[str, int] = {}
        last: dict[str, StatusCode] = {}
        for event in self._events:
            before = last.get(event.path)
            after = _reported_after(event, before)
            if after is not None:
                last[event.path] = after
            if event.reported is None:
                before, after = event.old, event.new
            elif before is None and event.cause == CAUSE_READING:
                # The node's earlier rows have left the bounded log: a reading's
                # row is then counted by its own codes.
                before = event.old
            if before is after or before not in RANKED or after not in RANKED:
                continue
            age = _age_seconds(event.timestamp, now)
            if age > CHANGE_WINDOW_SECONDS:
                continue
            counts[event.path] = counts.get(event.path, 0) + 1
        return counts

    def _snapshot_subtree(self, node: Status, now: datetime,
                          changes: dict[str, int], shields: dict[str, str]
                          ) -> tuple[StatusSnapshot, int, datetime | None,
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
            self._snapshot_subtree(child, now, changes, shields)
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
        mount_stamp: datetime | None = None
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
                       code=entry.code, running=entry.running,
                       subject=entry.subject, data=entry.data,
                       refused=entry.refused)
            for entry in node.reason_entries)
        # Own status is now a **derived** value: the entries are virtual children,
        # and a node whose members are all pinned has nothing left reporting.
        own = _own_code(node.code, [(line.quiet, line.code) for line in lines],
                        node.members, node.maintenance)
        # Staleness judges the **raw** reading and is never suppressed — a check
        # that stopped running escalates whichever policy is holding its result
        # back (ADR-0032 rule 6, ADR-0036 decision 9), so what a stale node gives
        # its parent is its degraded raw code, not its quieted own status.
        rollup = worst_of((node.code, STALE_DEGRADE)) if stale_self else own
        counted = tuple(child.counted for child in children)
        code = effective_code(rollup, counted)
        stale = stale_self or any(child.stale for child in children)
        # What the **parent** counts, and the rule that made it something other than
        # `code` (ADR-0032 rule 5). A damping counter transforms the value; a pin and
        # an unreported node withhold it, which the roll-up already expresses by
        # skipping those codes — so those two name the rule and put no code here.
        damped = self._damping.get(node.path)
        damping: Damping | None = None
        contribution: Contribution | None = None
        shielded_by = shields.get(node.path)
        # **One rule names each node, and the order is the order of specificity.**
        # An admin's pin is the most specific thing anybody said about this node, so
        # it is named first even when something else would also have withheld it.
        # A node that has never reported has nothing to believe or disbelieve, so no
        # shield and no counter can be about it. Only then the two rules that are
        # about a reading: the shield, which withholds it, and the counter, which
        # delays it.
        if code is StatusCode.MAINTENANCE:
            contribution = Contribution(None, MAINTENANCE_RULE)
        elif code is StatusCode.UNDEFINED:
            contribution = Contribution(None, UNDEFINED_RULE)
        elif shielded_by is not None:
            # The node keeps its own state and says what shielded it; what it does
            # not do is reach its parent, because *we could not get there* is not a
            # reading anybody should accumulate (ADR-0039 has no code for it, and
            # ADR-0032 decision 4 closed the vocabulary against inventing one).
            contribution = Contribution(None, DEPENDENCY_RULE)
        elif damped is not None and damped.pending is not None and not stale_self:
            # Staleness bypasses the counter (ADR-0032 rule 6): a check that stopped
            # running produces no new readings, so the count would never advance and
            # the hold would never end. The degraded raw code goes up instead.
            damping = Damping(pending=damped.pending, seen=damped.seen,
                              needed=node.escalate_after)
            publishes = effective_code(damped.published, counted)
            if publishes is not code:
                contribution = Contribution(publishes, DAMPING_RULE)
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
            own_stale=stale_self,
            stale_after_seconds=node_stale_after(node),
            age_seconds=age, children=children,
            reasons=lines, members=node.members, run=mount_run,
            contribution=contribution, damping=damping,
            # The measurement, withheld on a shared mount for the same reason the
            # text and the run facts are: two checks write that node and the last
            # writer cannot be believed there (ADR-0044 decision 1).
            subject="" if shared else node.subject,
            record=None if shared else node.record,
            shielded_by=shielded_by,
            changes=changes.get(node.path, 0))
        return snapshot, mounts, mount_stamp, mount_run


def _own_code(reported: StatusCode,
              lines: Sequence[tuple[bool, StatusCode | None]],
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

    ``lines`` are the node's entries as this rule reads them: whether each is
    pinned, and the code it declared. The snapshot and the event log both come
    here (:meth:`StatusTree._own`), so what a node shows and what its events say
    it showed are one derivation.
    """
    if pinned:
        return StatusCode.MAINTENANCE
    if not members or not lines:
        return reported
    counted: list[StatusCode] = []
    silenced = False
    for quiet, declared in lines:
        if quiet:
            silenced = True
            continue
        code = declared if declared is not None else reported
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


def _asked_at(now: datetime | None) -> datetime:
    """The moment a method of the tree is asked at: the instant it was handed, or
    the clock's where it was handed none (ADR-0120). :class:`ValueError` for a
    time without a zone — it would be compared with instants, and is none."""
    if now is None:
        return instants.now()
    return instants.utc(now, "the moment the tree is asked at")


def _age_seconds(timestamp: datetime | None, now: datetime) -> float:
    """Seconds from ``timestamp`` to ``now``, never negative: the time between two
    instants, which a change of no clock adds to or takes from. An unobserved node
    (``None``, ADR-0027) has no age — 0.0, and ``_is_stale`` exempts it anyway,
    since a node with a real code was necessarily stamped."""
    if timestamp is None:
        return 0.0
    return max(0.0, (now - timestamp).total_seconds())


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
    tolerance = node_stale_after(node)
    if tolerance is None or node.code in (StatusCode.UNDEFINED,
                                          StatusCode.MAINTENANCE):
        return False
    return age > tolerance


def stale_after_seconds(frequency: int | None) -> float | None:
    """The tolerance a **period** implies: ``frequency + max(frequency, 30s)``,
    roughly two intervals (ADR-0005 decision 1).

    One function so that the arithmetic has one copy — the engine reads it too, to
    state the tolerance its own tick implies (ADR-0081). It is not the whole rule:
    :func:`node_stale_after` is, and is what :func:`_is_stale` and the snapshot both
    go through, so the verdict and the number a client is shown cannot disagree
    (ADR-0079 decision 5). ``None`` where there is no period to measure against —
    which is not by itself a node that cannot go stale, since it may have stated a
    tolerance instead.
    """
    if not frequency:
        return None
    return frequency + max(float(frequency), STALE_MIN_GRACE_SECONDS)


def node_stale_after(node: Status) -> float | None:
    """The tolerance this node's freshness is actually judged against — the
    **stated** one where somebody stated it, and otherwise the one its period
    implies (ADR-0079 decision 1, both branches in one place).

    One resolution, two callers — :func:`_is_stale` decides with it and the
    snapshot carries the number it used — so *what the tolerance is* and *what the
    client is told it is* cannot disagree.

    The stated branch is what lets a node be read on no check's schedule and still
    go stale (ADR-0081): the engine re-asserts its own branch every tick and states
    the tick's tolerance, rather than stamping the tick as a period and having a
    surface report it as a check's. The cycle ceiling a paced check
    declares arrives on the same field.
    """
    if node.stale_after is not None:
        return node.stale_after
    return stale_after_seconds(node.frequency_seconds)


# The single shared status tree for this process (ADR-0001).
status_tree = StatusTree()
