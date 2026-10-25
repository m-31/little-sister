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

import hashlib
import re
import threading
from collections import deque
from collections.abc import Callable, Iterable, Iterator, Mapping, Sequence
from contextlib import contextmanager
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime, timedelta
from typing import Any

from little_sister import details as node_details
from little_sister import instants
from little_sister.aggregation import (
    NO_RULES,
    AggregationRule,
    RuleSet,
    Table,
    day_begins,
)
from little_sister.codes import RANKED, escalates
from little_sister.details import Detail, Details, Row
from little_sister.logger import logger
from little_sister.pins import (
    ACKNOWLEDGMENTS,
    MAINTENANCE,
    NO_NOTE,
    SEEN,
    Pin,
    PinStore,
    PinWrite,
)
from little_sister.reasons import ReasonInput
from little_sister.status import (
    HEARTBEAT_PATH,
    PATH_SEP,
    Status,
    StatusCode,
    effective_code,
    join_path,
    leaf_name,
    on_same_line,
    parent_path,
    split_path,
    worst_of,
)
from little_sister.tags import NO_VOCABULARY, Tags, Vocabulary
from little_sister.tags import union as tags_union

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

#: The rule a **configured rule** is (ADR-0137): a table in
#: ``config/aggregation.yaml`` that changes what a part counts as above it — what a
#: node passes to its parent, how its children count in it, or how its lines count in
#: its own status. One word for every configured rule, whatever its table, the word
#: ``tree.py`` held for the rule since the boundary was named (ADR-0032 decision 2);
#: the rule's own name and its table are the explain view's and the index's.
AGGREGATION_RULE = "aggregation"

#: The rule a person's **seen** is (ADR-0142): the failure of the part it stands on
#: accepted, the part keeping its true color and counting as ``OK`` above — a line in
#: its node's own status, a node in what its parent counts — until it changes. The
#: kind's own word, as maintenance's is.
SEEN_RULE = SEEN

#: What a part a person has seen counts as above it (ADR-0142): ``OK``, whatever
#: failure it reads — and, through :func:`_mapped`, never less than a warning where a
#: reading at or beneath it is past its tolerance, which escalates under every rule.
ACCEPTED = Table(((StatusCode.WARN, StatusCode.OK), (StatusCode.ERROR, StatusCode.OK)))

#: The segment the instance's own branch stands at beneath the root, which no
#: configured rule reaches (ADR-0137).
_OWN_BRANCH = HEARTBEAT_PATH.strip("/")

#: The rules that only ever mark a row their node did **not show** — a change of what
#: its check reports, beneath a pin — as against a row of what it showed and
#: published otherwise. A *seen* is on both sides, as a configured rule is: on a node
#: it keeps a change its node showed from its parent, and on a line one its check
#: reported from its node (ADR-0142), so its rows say which themselves.
#:
#: The distinction earns its own name because :meth:`StatusTree.history` turns on it,
#: and getting it wrong is silent. A pinned node showed `MAINTENANCE` throughout, so a
#: check that went red underneath it did not change what anybody saw and must not chop
#: one maintenance window into phantom periods. A **damped** node is the opposite case:
#: it went red at once, on its card, on its page and in the log — only the escalation
#: waited — so its transition is exactly a period of its own history, and dropping it
#: would break the one claim damping makes. A dependency shield belongs on that side
#: too, for the same reason: it keeps the node's own state and marks it.
#:
#: **A configured rule is on both sides** (ADR-0137): on a node it changes what the
#: node passes up, as damping does, and marks the row of what the node showed; on a
#: node's lines it changes what the node shows, as a line's pin does, and marks the
#: row of a reading the node did not show. So the row says which it is
#: (:attr:`Event.shown`), and this set is what a row that does not say — one read
#: from a log written before it could — is read by.
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
#: A reading gone stale (ADR-0132 decisions 2 and 4): what moves a node above others
#: where a node beneath it is no longer observed within its tolerance, or a shield
#: ends because its dependency went silent. No write makes that change, and no row
#: is written for it: only a branch's period says it.
CAUSE_STALE = "stale"
#: A rule the deployment configures began to count (ADR-0137 decision 11): at the
#: start that brought it, where what it counts moves a branch from what its kept
#: period says, and in a replay of the past where it begins inside the log. No
#: write makes that change either, and only a branch's period says it — naming the
#: node whose count the rule changed and the rule (:attr:`Period.rule`).
CAUSE_RULE = "rule"
#: An acknowledgment set, edited or ended (ADR-0142), on the node or on one of its
#: lines: every one is a row of its node, whatever it does to what the node shows —
#: the kind's own word and the act, ``seen-set``, ``line-seen-ended``
#: (:func:`acknowledgment_cause`). A node's own changes nothing its node shows, and
#: says one status as both, as an edit of a pin does; a line's says what its node
#: showed before and after it. An end says why it ended (:attr:`Event.ended`).
CAUSE_SEEN_SET = "seen-set"
CAUSE_SEEN_EDITED = "seen-edited"
CAUSE_SEEN_ENDED = "seen-ended"
CAUSE_LINE_SEEN_SET = "line-seen-set"
CAUSE_LINE_SEEN_EDITED = "line-seen-edited"
CAUSE_LINE_SEEN_ENDED = "line-seen-ended"

#: The acts on an acknowledgment that a row names (:func:`acknowledgment_cause`).
SET, EDITED, ENDED = "set", "edited", "ended"


def acknowledgment_cause(kind: str, act: str, *, line: bool) -> str:
    """The cause a row of an acknowledgment says (ADR-0142): its kind and the act —
    ``set``, ``edited`` or ``ended`` — and ``line-`` before them where it stands on
    one of its node's lines."""
    return f"{'line-' if line else ''}{kind}-{act}"


#: The causes of every acknowledgment's rows, the node's and the line's.
ACKNOWLEDGMENT_CAUSES = frozenset(
    acknowledgment_cause(kind, act, line=line)
    for kind in ACKNOWLEDGMENTS for act in (SET, EDITED, ENDED)
    for line in (False, True))
#: The causes of the rows of an acknowledgment on a node itself, which a replay
#: reads to say when the node's own part counted as ``OK`` above it.
_NODE_ACKNOWLEDGMENT_CAUSES = frozenset(
    acknowledgment_cause(kind, act, line=False)
    for kind in ACKNOWLEDGMENTS for act in (SET, EDITED, ENDED))

#: Why an acknowledgment ended (ADR-0142), the value :attr:`Event.ended` carries on
#: the row of its end, so that the log answers why an alarm came back: by a person's
#: hand; at the end it was given; its part recovered, or reads a failure worse than
#: the one it was set at; a new occurrence of the failure — a line's identity or the
#: field its type names, where it is bound to one; or its part is no longer reported
#: — its line gone from a reading of its node, its node removed, or reading no status.
ENDED_HAND = "hand"
ENDED_CLOCK = "clock"
ENDED_RECOVERY = "recovery"
ENDED_WORSENING = "worsening"
ENDED_OCCURRENCE = "occurrence"
ENDED_GONE = "gone"
ENDINGS = frozenset({ENDED_HAND, ENDED_CLOCK, ENDED_RECOVERY, ENDED_WORSENING,
                     ENDED_OCCURRENCE, ENDED_GONE})

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
    maintenance: Pin | None = None
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
    #: The form the line was written from, where its grading asked the library for
    #: it (ADR-0126), and empty for a line written as a sentence of its own. The
    #: node's page shows it beside the line: the key a check's ``display:`` block
    #: re-words the line under.
    form: str = ""
    #: The grading that decided the line's code, where one did (ADR-0131 decision 1),
    #: and empty on every other line. The node's page shows it beside the form: the
    #: name a deployment writes the keys of to grade the line differently.
    grading: str = ""
    #: The configured rule that decides how this line counts in its node's own
    #: status (ADR-0137), where one does — what the line reads, what it counts as,
    #: and whether that changes it now — and ``None`` on every other line. The line
    #: keeps its true color under the rule's mark. A line a person has seen is the
    #: person's, and carries none.
    rule: RuleAt | None = None
    #: The acknowledgment on this line, where one stands (ADR-0142): a *seen*, the
    #: line keeping its true color under a ringed check and counting as ``OK`` in its
    #: node's own status. Suspended, as a line's pin is, while its node's lines are no
    #: members — a check error stands in for them.
    acknowledgment: Pin | None = None
    #: What tells this line's failure from the next one (ADR-0142), as its check
    #: wrote it: the field its type names, else its reading's identity; empty where
    #: nothing does.
    occurrence: str = ""

    @property
    def accepted(self) -> bool:
        """Whether a person's acknowledgment decides how this line counts: one
        stands on it, and no pin, which is the louder fact."""
        return self.acknowledgment is not None and not self.quiet

    @property
    def quiet(self) -> bool:
        """Whether this entry is suppressed. Quiet is **shown**, not hidden
        (ADR-0032 rule 5) — the surfaces render it in the maintenance color."""
        return self.maintenance is not None


def failing_first(lines: Iterable[ReasonLine]) -> list[ReasonLine]:
    """A box's lines in the order its line budget shows them (ADR-0127 decision 6):
    the errors, then the warnings, then the rest, each group in the order the check
    wrote them — so what the budget clips is healthy lines, never the reason for the
    box's color, which stood past the sixth line of a roster whose failing name came
    late. A pinned line counts among the rest whatever its code, since what it says
    is silenced (ADR-0041); so does a line with no code of its own, which says
    nothing for itself (ADR-0042). A failure a person has seen comes after the ones
    nobody has, and before the rest (ADR-0142): it keeps its color, and is no longer
    the reason for the box's. Where nothing clips the lines — a node's own on its
    page, the Copy documents — the check's order stands, and this is not asked.
    """
    errors: list[ReasonLine] = []
    warnings: list[ReasonLine] = []
    accepted: list[ReasonLine] = []
    rest: list[ReasonLine] = []
    for line in lines:
        code = None if line.quiet else line.code
        if code in (StatusCode.ERROR, StatusCode.WARN) and line.accepted:
            accepted.append(line)
        elif code is StatusCode.ERROR:
            errors.append(line)
        elif code is StatusCode.WARN:
            warnings.append(line)
        else:
            rest.append(line)
    return errors + warnings + accepted + rest


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
    a reader to infer it from a number that does not add up. ``rule`` names the
    one rule of that kind that decided, where one rule did (ADR-0141 decision 3):
    the id of the node's own pin, or the name of the configured rule — what the
    envelope lists among what handles the node — and empty for the rules that are
    mechanisms rather than anything somebody set or wrote, damping, a shield or a
    node not yet reported, and for a node whose lines are pinned every one.
    """
    code: StatusCode | None
    by: str
    rule: str = ""


@dataclass(frozen=True)
class RuleAt:
    """A configured rule at the place it decides (ADR-0137): what its part reads
    there and what it counts as above — ``None`` where it counts nothing — and
    whether that changes it now, which is the one predicate its mark, its block on
    the wall and the ringed diamond follow (ADR-0135 decision 9). A count says how
    many of the parts it counts report a status the table names (``failing``),
    against the rule's own ``count``; from there on the table does not apply, and
    the rule changes nothing. On a count over children ``reads`` and ``counts`` are
    the node's own children's to say, and ``None`` here."""
    rule: AggregationRule
    reads: StatusCode | None = None
    counts: StatusCode | None = None
    failing: int = 0
    changes: bool = False


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
    round (ADR-0080), like ``reported_code`` before it.
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
    update belongs to the node where the check is named — unless a **unit** of
    the check answers for that node (ADR-0130): then it carries the unit's own
    facts, and so does every container between it and the mount, with the
    earliest slot armed beneath it.

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
    #: Whether the node has a handbook (ADR-0133 decision 3), which is what its
    #: *Handbook* tab and its hover card read. The text stays on the node, for the
    #: tab (:meth:`StatusTree.handbook`): a snapshot says only that there is one,
    #: so a surface that copies a snapshot copies no runbook.
    has_handbook: bool = False
    #: The node's own details (ADR-0133 decision 6), each key with its Markdown and
    #: who gave it, in their order: the type's first, then the deployment's, each as
    #: given — a key both name standing once for each. What the deployment gives holds
    #: for every node beneath, so a node's *About* card shows more than its own — the
    #: rows :meth:`StatusTree.details` resolves. The type's are withheld on a node two
    #: checks mount, as ``report`` is: two runs write them and the last writer cannot
    #: be believed there.
    details: tuple[Detail, ...] = ()
    #: Every tag the node carries (ADR-0139 decision 2): those written for it and for
    #: every node above it, added up, in the order its *About* card lists them — the
    #: known tags in their files' order, the rest by name. The JSON envelope publishes
    #: them as ``tags`` (decision 6), and the wall's filter reads them.
    tags: tuple[str, ...] = ()
    #: The declared sibling rank this node was sorted by (ADR-0055), ``0`` where
    #: nobody declared one. Carried so a surface can *see* the order it was handed
    #: rather than infer it; the JSON envelope publishes it as ``order`` (ADR-0080).
    order: int = 0
    #: "This node's quiet lines are still information" (ADR-0063). ``None`` where
    #: nobody said, and a stated ``False`` is a declaration rather than a silence —
    #: the tri-state the seed and the fill both turn on. The web reads it, and the
    #: JSON envelope publishes it as the same tri-state (ADR-0080); a client drawing
    #: its own chips decides for itself how to honour it.
    show_when_quiet: bool | None = None
    maintenance: bool = False
    maintenance_entry: Pin | None = None
    #: The acknowledgment on the node itself, where one stands (ADR-0142): a *seen*
    #: of a failure its own reading says, the node keeping its color under a ringed
    #: check while its parent counts its own part as ``OK`` — ``contribution`` says
    #: so, where that changes what is counted.
    acknowledgment: Pin | None = None
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

    #: The configured rule that decides what this node passes to its parent
    #: (ADR-0137) — the first rule on a node whose part begins here — with what the
    #: node passes up there and what its parent counts of it, or ``None``. The node
    #: keeps its color: only its parent's count changes, and ``contribution`` says so.
    rule: RuleAt | None = None
    #: The configured rule that counts this node's children, where one does: how
    #: many of them report a status its table names, and whether it changes how any
    #: of them counts here.
    children_rule: RuleAt | None = None
    #: The rule this node's parent counts its children by, where it names this one:
    #: what this node passes up, what is counted of it, and whether that is a change.
    parent_rule: RuleAt | None = None

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

    #: **The period of what the node shows** (ADR-0132): since when it has shown
    #: ``code``, how that began and the node whose change began it — the period the
    #: tree keeps for a node above others, here only where it is of ``code``. Until
    #: the units beneath it have run after a restart, and between a change no write
    #: makes and the comparison that dates it, the tree's period can be of a code
    #: the node does not show, and no surface says such a period as the node's
    #: (decision 3): so the snapshot decides it once, and the envelope, the Time
    #: card, History and the Copy document read this. ``None`` on a leaf too, whose
    #: one period is :attr:`own_period`.
    period: Period | None = None

    #: **When the node's own status began** (ADR-0110 decision 5): the beginning of
    #: the period ``own_code`` is in, as the tree keeps it. ``None`` on a node that
    #: declares nothing above nodes beneath it — its own code ``UNDEFINED``, with
    #: children — whether it never declared or has stopped: it has no status of its
    #: own for a period to name (ADR-0094 decision 5), which the Time card and History
    #: say of it too, and the envelope leaves the period out (ADR-0132 decision 7).
    #: Decided here once, as :attr:`period` is. A leaf's ``UNDEFINED`` is its own
    #: reading, and keeps its period.
    own_period: Beginning | None = None

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
        return _counted_code(self.code, self.contribution)

    @property
    def own_counted(self) -> StatusCode:
        """The code this node counts **for itself** in what it rolls up to: its own
        status — or, where its own reading is past its tolerance, that reading
        degraded, which is what the tree counts for it whichever rule is holding
        the reading back (ADR-0005, ADR-0032 rule 6).

        It is the expression the snapshot rolls the node up with
        (:func:`_counts_for_itself`), read off the fields that expression was
        handed. A surface that asks **whose** a status is asks here: comparing
        ``own_code`` with ``code`` answers it wrongly for a node whose own reading
        went stale, which shows a warning that is nobody's but its own.
        """
        return _counts_for_itself(self.reported_code, self.own_code, self.own_stale)

    @property
    def derived(self) -> bool:
        """Whether what this node shows comes **from beneath it** (ADR-0123): its
        ``code`` is not the code it counts for itself. A node with nothing beneath
        it never is, and neither is one that counts for itself what it rolls up to
        — a failure of its own above nodes that are well, or above one that fails
        too.

        One answer for every surface that draws a node pale where its color is a
        child's — the head of its page, its card, its box — and for every sentence
        that says a status is rolled up.
        """
        return self.code is not self.own_counted

    @property
    def counts_beneath(self) -> bool:
        """Whether what this node shows **counts the nodes beneath it**: it has
        some, and what it counts for itself does not cancel them — ``MAINTENANCE``
        by a pin on the node or by its check's word for it (ADR-0039 rule 3), and
        not by lines that are all silenced, which cancel nothing (ADR-0124). Its
        own status is then one part of what it shows, and a surface that states a
        period of the node — which is the own status's, as every event is
        (ADR-0107 decision 1) — names it as that (ADR-0123).

        It is the roll-up's own answer (:func:`_cancels_beneath`), read off the
        fields that expression was handed. Read it off the snapshot the tree made:
        a filter that takes a node's children away for a view takes this with them.
        """
        return bool(self.children) and not _cancels_beneath(
            self.own_counted, self.reported_code, self.maintenance)

    @property
    def lines_silenced(self) -> bool:
        """Whether this node counts nothing for itself because **every line of its
        own is silenced** (ADR-0124): its own status reads ``MAINTENANCE`` by its
        lines' pins, and not by a pin on the node or its check's word, so it
        cancels nothing beneath it (:func:`_cancels_beneath`). A surface that says
        where what a node shows comes from says so, rather than *rolled up from its
        own reading* — which, with every line silenced, counts for nothing.
        """
        return (self.own_counted is StatusCode.MAINTENANCE
                and not _cancels_beneath(self.own_counted, self.reported_code,
                                         self.maintenance))

    @property
    def quiet_reasons(self) -> int:
        """How many of this node's entries are pinned. The card clamps its reasons
        to ``reason_cap``, so the pinned line may sit below the fold and this count
        is the only thing that always shows (ADR-0032 rule 5)."""
        return sum(1 for line in self.reasons if line.quiet)


# --- what each node contributes to the wall's tree (ADR-0127) -----------------------
#
# One vocabulary over what a node counts for itself, which the chip's counts, the
# healthy fold and, from stage 4, the failure budget read — so that the round on
# maintenance and aggregation changes them once (backlog #91, §7.9).

#: The states a chip counts, in the order its glyphs are drawn: ● ▲ ‖ ✓ ○.
COUNTED_STATES: tuple[str, ...] = ("error", "warn", "maintenance", "ok", "idle")
_STATE_OF: dict[StatusCode, str] = {
    StatusCode.ERROR: "error", StatusCode.WARN: "warn",
    StatusCode.MAINTENANCE: "maintenance", StatusCode.OK: "ok",
    StatusCode.UNDEFINED: "idle",
}
#: The code a counted state's glyph is drawn with — a chip's counts reuse the
#: status cue's shapes, so ● ▲ ‖ ✓ ○ look as the cues beside them do.
STATE_CODE: dict[str, StatusCode] = {state: code for code, state in _STATE_OF.items()}
_PLURAL: dict[str, tuple[str, str]] = {
    "error": ("error", "errors"), "warn": ("warning", "warnings"),
    "maintenance": ("in maintenance", "in maintenance"), "ok": ("ok", "ok"),
    "idle": ("idle", "idle"),
}


def counts_as(node: StatusSnapshot) -> str:
    """The state a node counts **for itself**, as a chip counts it: ``error``,
    ``warn``, ``maintenance``, ``ok`` or ``idle`` — its :attr:`own_counted`, under
    which a stale leaf is the warning it counts as and a pinned node is in
    maintenance (ADR-0127 decision 2)."""
    return _STATE_OF[node.own_counted]


def line_counts_as(node: StatusSnapshot, line: ReasonLine) -> str:
    """The state a line counts for: its own code (ADR-0042), or, having none, the
    code its node rolls up to; a pinned line is in maintenance (ADR-0041). A line a
    configured rule decides keeps its true color (ADR-0137): having no code of its
    own, it is the reading the rule read, which its node may no longer show."""
    if line.quiet:
        return "maintenance"
    if line.code is not None:
        return _STATE_OF[line.code]
    if line.rule is not None and line.rule.reads is not None:
        return _STATE_OF[line.rule.reads]
    return _STATE_OF[node.code]


def failing(node: StatusSnapshot) -> bool:
    """Whether a node is drawn as an error or a warning — a stale leaf among them,
    whatever pins stand beneath it — which a close's incident reads (ADR-0127
    decision 9)."""
    return node.code in (StatusCode.ERROR, StatusCode.WARN)


def pin_beneath(node: StatusSnapshot) -> bool:
    """Whether a person's rule stands on this node or beneath it: a pin or an
    acknowledgment on the node, on one of its lines, or on any node of its
    subtree."""
    if (node.maintenance or node.maintenance_entry is not None
            or node.acknowledgment is not None):
        return True
    if any(line.quiet or line.acknowledgment is not None for line in node.reasons):
        return True
    return any(pin_beneath(child) for child in node.children)


def _acts(rule: RuleAt | None) -> bool:
    """Whether a configured rule changes what its part counts as now (ADR-0137) —
    the one predicate its mark, its block on the wall and the ringed diamond
    follow."""
    return rule is not None and rule.changes


def _lowers(rule: RuleAt | None) -> bool:
    """Whether a configured rule makes its part count for less than it reads now: a
    cap, healing, or the part left out — not a floor, under which a warning counts
    as the error it is to be taken for."""
    if rule is None or not rule.changes or rule.reads is None:
        return False
    return _counts_for_less(rule.counts, rule.reads)


def _counts_for_less(counted: StatusCode | None, reads: StatusCode) -> bool:
    """Whether a part its parent counts as ``counted`` counts for less than it
    reads: left out, or below its own failure — a cap, healing, a part left out, a
    count while it holds — and not a floor's, which makes it count for more."""
    return counted is None or (
        counted in _SEVERITY_ORDER and reads in _SEVERITY_ORDER
        and _SEVERITY_ORDER[counted] < _SEVERITY_ORDER[reads])


def _held_below(shows: StatusCode, *readings: StatusCode) -> bool:
    """Whether a node that shows ``shows`` holds back a reading it does not show
    (ADR-0137 decision 11): where it shows less than either end of the change —
    nothing counted, or less than a failure — so that a change's end is held back
    where its start was; and not where a floor on its lines raised it, so that it
    shows at least as much as both, which reached whoever looked."""
    if shows not in _SEVERITY_ORDER:
        return True
    return any(reading in _SEVERITY_ORDER
               and _SEVERITY_ORDER[shows] < _SEVERITY_ORDER[reading]
               for reading in readings)


_SEVERITY_ORDER: Mapping[StatusCode, int] = {
    StatusCode.OK: 0, StatusCode.WARN: 1, StatusCode.ERROR: 2}


def ruled_beneath(node: StatusSnapshot) -> bool:
    """Whether a configured rule changes how something counts on this node or
    beneath it now (ADR-0137): what the node passes up, what its parent counts of
    it, one of its lines, or anything of its subtree."""
    stack = [node]
    while stack:
        current = stack.pop()
        if (_acts(current.rule) or _acts(current.parent_rule)
                or any(_acts(line.rule) for line in current.reasons)):
            return True
        stack.extend(current.children)
    return False


def healthy(node: StatusSnapshot) -> bool:
    """What the healthy fold folds (ADR-0127 decision 4): a node whose code is
    ``OK``, nothing beneath it stale, no pin on it or beneath it, and no configured
    rule changing a count on it or beneath it — only what is truly OK (ADR-0135
    decision 9, ADR-0137)."""
    return (node.code is StatusCode.OK and not node.stale and not pin_beneath(node)
            and not ruled_beneath(node))


def line_healthy(node: StatusSnapshot, line: ReasonLine) -> bool:
    """A line is healthy when its own code is ``OK``, or, having none, when the code
    its node rolls up to is, no pin covers it — the node's own, or the line's — and
    no configured rule changes how it counts."""
    if line.quiet or node.maintenance or node.maintenance_entry is not None:
        return False
    if _acts(line.rule):
        return False
    code = line.code if line.code is not None else node.code
    return code is StatusCode.OK


def own_failure(node: StatusSnapshot) -> str | None:
    """What a node fails with **for itself**, as the failure budget reads it
    (backlog #91 §3.3, §7.9): ``error`` or ``warn``, by what it counts for itself — a
    leaf's reading, a stale one as the warning it counts as, and a branch's own,
    whatever its children say — or ``None``. A node a damping counter still holds
    back from its parent is no failure until it escalates, and a pinned one counts as
    maintenance, so neither spends the budget; nor does one a configured rule makes
    count for less above, a handled failure (ADR-0135 decision 9, ADR-0137) — where
    a floor makes it count for more, it is the failure it is to be taken for — nor
    one whose own failure a person has seen, unless its reading went stale, which
    escalates whatever stands on it (ADR-0142)."""
    state = counts_as(node)
    if state not in ("error", "warn") or node.damping is not None:
        return None
    if _lowers(node.rule) or _lowers(node.parent_rule):
        return None
    if node.acknowledgment is not None and not node.own_stale:
        return None
    return state


#: What rules handle beneath a closed node that its counts do not show as such, in
#: the order a chip's words say them, each as one part and as many (ADR-0135
#: decision 6): a pinned branch, which the counts pass over, a line's pin, a part a
#: person has seen (ADR-0142), and a part a configured rule changes the count of
#: (ADR-0137) — a node, or a line, which keeps its true color among the counts as a
#: seen one does. *Done* and *silenced* come with their kinds.
HANDLED_ORDER: tuple[str, ...] = ("node", "line", SEEN, "rule")
_HANDLED_WORDS: dict[str, tuple[str, str]] = {
    "node": ("node in maintenance", "nodes in maintenance"),
    "line": ("line in maintenance", "lines in maintenance"),
    SEEN: ("seen", "seen"),
    "rule": ("by a rule", "by a rule"),
}


@dataclass(frozen=True)
class ChipCounts:
    """What a chip says beneath its name (ADR-0127 decision 2): a count per state,
    what rules handle beneath it that the counts do not show as such, by job
    (ADR-0135 decision 6), how many lines are running, and the damped escalations
    beneath it as *(seen, needed)* pairs."""

    counts: dict[str, int]
    handled_by: dict[str, int] = field(default_factory=dict)
    running: int = 0
    damped: tuple[tuple[int, int], ...] = ()

    @property
    def handled(self) -> int:
        """How many parts beneath a rule handles that the counts do not show as
        such — the number beside the ringed diamond."""
        return sum(self.handled_by.values())

    @property
    def handled_words(self) -> str:
        """The diamond in words: *3 handled: 1 node in maintenance, 2 lines in
        maintenance*, each kind of part handled, in :data:`HANDLED_ORDER`; empty
        where nothing is."""
        said = []
        for kind in HANDLED_ORDER:
            count = self.handled_by.get(kind, 0)
            if count:
                one, many = _HANDLED_WORDS[kind]
                said.append(f"{count:,} {one if count == 1 else many}")
        if not said:
            return ""
        return f"{self.handled:,} handled: " + ", ".join(said)

    @property
    def total(self) -> int:
        return sum(self.counts.values())

    @property
    def states(self) -> tuple[str, ...]:
        """The states counted, in glyph order, those with a count."""
        return tuple(state for state in COUNTED_STATES if self.counts.get(state))

    @property
    def mixed(self) -> bool:
        """Whether the chip draws each state's glyph and count rather than one total."""
        return len(self.states) > 1

    @property
    def words(self) -> str:
        """The counts in words, the chip's tooltip and accessible name: *2 errors, 1
        warning, 119 ok*, a damped count with how near it is to escalating, a running
        line, and what is handled beneath — *3 handled: 3 lines in maintenance*."""
        said: list[str] = []
        damped = iter(self.damped)
        for state in self.states:
            count = self.counts[state]
            one, many = _PLURAL[state]
            phrase = f"{count:,} {one if count == 1 else many}"
            if state in ("error", "warn"):
                held = [f"{seen} of {needed} to escalate" for seen, needed in damped]
                if held:
                    phrase += ", damped: " + "; ".join(held)
            said.append(phrase)
        if self.running:
            said.append(f"{self.running:,} running")
        if self.handled:
            said.append(self.handled_words)
        return ", ".join(said)


def handled_beneath(node: StatusSnapshot) -> dict[str, int]:
    """What rules handle beneath a closed node, the node itself among it, that its
    chip's counts do not show as such (ADR-0135 decision 6), by kind of part.

    A chip counts a leaf by what it counts for itself and a branch only where it
    fails for itself (ADR-0127 decision 2), so a pinned leaf — or one whose every
    line is pinned — is ‖ among the counts already, its lines with it; a **pinned
    branch** is not, whatever stands beneath it, and is one node in maintenance
    here, its own lines' pins with it. A **line's pin** is one line in maintenance
    wherever its node is not ‖ among the counts. A leaf's own chip counts its lines,
    a pinned one as ‖, so nothing of a leaf's pins is handled out of sight.

    **A part a configured rule changes the count of** (ADR-0137) is one handled by
    a rule wherever it stands, the chip's own node and a leaf's own lines among
    them: it keeps its true color among the counts, and the color it passes up is
    what the counts do not show — a node whose parent counts it otherwise, by its
    own rule or by its parent's count over children, and a line its node counts
    otherwise. **A part a person has seen** (ADR-0142) is the same, a node or a line
    wherever it stands, while its acknowledgment stands."""
    nodes = lines = ruled = seen = 0
    stack = [node]
    while stack:
        current = stack.pop()
        if _acts(current.rule) or _acts(current.parent_rule):
            ruled += 1
        ruled += sum(1 for line in current.reasons if _acts(line.rule))
        if current.acknowledgment is not None:
            seen += 1
        seen += sum(1 for line in current.reasons if line.accepted)
        if current.children:
            if current.maintenance_entry is not None:
                nodes += 1
            else:
                lines += sum(1 for line in current.reasons if line.quiet)
            stack.extend(current.children)
        elif current is not node and counts_as(current) != "maintenance":
            lines += sum(1 for line in current.reasons if line.quiet)
    handled = {"node": nodes, "line": lines, SEEN: seen, "rule": ruled}
    return {kind: count for kind, count in handled.items() if count}


@dataclass(frozen=True)
class HandledRule:
    """A rule that stands beneath a node, as the node's *why* card and its Copy
    document list it under its job (ADR-0135 decision 7): the node it stands on and
    that node's path beneath the one it is listed for, the stored pin, and for a
    line's pin the line's slug and text. ``reads`` is what its part reads under it
    where that is a failure — what the part would count as without it.

    A configured rule (ADR-0137) is listed once for each part it changes the count
    of now, with ``rule`` where it stands on that part, in place of a pin: a node
    whose parent counts it otherwise, or one of its lines. An acknowledgment
    (ADR-0142) is a pin of its kind, on a node or one of its lines."""

    path: str
    name: str
    entry: Pin | None = None
    slug: str = ""
    line: str = ""
    reads: StatusCode | None = None
    rule: RuleAt | None = None

    @property
    def job(self) -> str:
        """Its job, as the *why* card groups it and the mark it is drawn with: the
        pin's kind — ``maintenance``, ``seen`` — or ``aggregation`` for a configured
        rule."""
        if self.rule is not None:
            return AGGREGATION_RULE
        return self.entry.kind if self.entry is not None else MAINTENANCE_RULE


def _failure(code: StatusCode | None) -> StatusCode | None:
    return code if code in (StatusCode.WARN, StatusCode.ERROR) else None


def rules_beneath(node: StatusSnapshot) -> tuple[HandledRule, ...]:
    """Every rule that stands beneath ``node``, the node's own aside (ADR-0135
    decision 7): a node's pin and a line's, whatever stands above it, and each part
    a configured rule changes the count of now (ADR-0137), in the tree's order, a
    node's own before its lines'. A branch's own reading under its pin is the
    check's reported code; a branch that declares nothing reads nothing, and says
    what it holds beneath in its own rows. A rule on a node, or a count over its
    parent's children, reads what the node passes up."""
    rules: list[HandledRule] = []
    stack = list(reversed(node.children))
    while stack:
        current = stack.pop()
        name = current.path[len(node.path):].lstrip("/")
        if current.maintenance_entry is not None:
            rules.append(HandledRule(current.path, name, current.maintenance_entry,
                                     reads=_failure(current.reported_code)))
        if current.acknowledgment is not None:
            rules.append(HandledRule(current.path, name, current.acknowledgment,
                                     reads=_failure(current.own_code)))
        for at in (current.rule, current.parent_rule):
            if _acts(at):
                assert at is not None
                rules.append(HandledRule(current.path, name, rule=at,
                                         reads=_failure(at.reads)))
        for line in current.reasons:
            if line.quiet and line.maintenance is not None:
                rules.append(HandledRule(current.path, name, line.maintenance,
                                         slug=line.slug, line=line.text,
                                         reads=_failure(line.code)))
            elif line.accepted:
                assert line.acknowledgment is not None
                rules.append(HandledRule(
                    current.path, name, line.acknowledgment, slug=line.slug,
                    line=line.text, reads=_failure(
                        line.code if line.code is not None
                        else current.reported_code)))
            elif _acts(line.rule):
                assert line.rule is not None
                rules.append(HandledRule(current.path, name, slug=line.slug,
                                         line=line.text, rule=line.rule,
                                         reads=_failure(line.rule.reads)))
        stack.extend(reversed(current.children))
    return tuple(rules)


@dataclass(frozen=True)
class Acceptable:
    """A part a ringed check would accept as it stands (ADR-0142): its node's path,
    its line's slug — empty for the node itself — and what it says, the line's text
    or the node's path."""
    path: str
    slug: str
    said: str


def acknowledgeable_parts(node: StatusSnapshot, *,
                          covered: bool = False) -> tuple[Acceptable, ...]:
    """The parts at and beneath ``node`` that a ringed check on it accepts, one
    acknowledgment each, as they stand (ADR-0142 decision 5): every line that fails
    now, of a node whose lines are members, and every node that fails by its own
    reading and has no such lines — and none in maintenance, under a pin on it or
    above it (``covered``: one above ``node`` holds it) or under its check's own word
    for maintenance; none a person accepted already; and none failing only because
    its reading went stale, which is no failure a reading says. In the order the
    tree draws them."""
    parts: list[Acceptable] = []
    stack = [(node, covered)]
    while stack:
        current, held = stack.pop()
        held = (held or current.maintenance or current.maintenance_entry is not None
                or current.reported_code is StatusCode.MAINTENANCE)
        if not held:
            if current.members and current.reasons:
                for line in current.reasons:
                    if line.quiet or line.acknowledgment is not None:
                        continue
                    code = line.code if line.code is not None else current.reported_code
                    if code in _FAILURES:
                        parts.append(Acceptable(current.path, line.slug, line.text))
            elif current.acknowledgment is None and current.own_code in _FAILURES:
                parts.append(Acceptable(current.path, "", current.path))
        stack.extend((child, held) for child in reversed(current.children))
    return tuple(parts)


def parts_digest(parts: Iterable[Acceptable | tuple[str, str]]) -> str:
    """A short digest of a set of parts (ADR-0142): what a ringed check's editor
    carries of the parts it listed, so that a set that finds others failing beneath
    the node — one more, or one less — is refused and shows them, rather than
    accepting a failure nobody was shown. The same parts in any order are one
    digest."""
    keys = sorted(f"{part.path}|{part.slug}" if isinstance(part, Acceptable)
                  else f"{part[0]}|{part[1]}" for part in parts)
    return hashlib.sha256("\n".join(keys).encode()).hexdigest()[:16]


def lines_rules(node: StatusSnapshot) -> tuple[RuleAt, ...]:
    """The configured rules that decide how ``node``'s lines count in it, once each
    in the order its lines first name it (ADR-0137): with how many of the lines it
    decides fail where it counts, and whether it changes how any of them counts now —
    what its block on the node says."""
    found: dict[str, RuleAt] = {}
    for line in node.reasons:
        at = line.rule
        if at is None:
            continue
        held = found.get(at.rule.key)
        if held is None:
            found[at.rule.key] = RuleAt(at.rule, failing=at.failing,
                                        changes=at.changes)
        elif at.changes and not held.changes:
            found[at.rule.key] = replace(held, changes=True)
    return tuple(found.values())


def chip_counts(node: StatusSnapshot) -> ChipCounts:
    """What a closed node's chip counts (ADR-0127 decision 2): each leaf beneath it
    by what it counts for itself, each branch beneath that fails for itself — the
    chip's own node among them — by that; a leaf's chip its lines; and beside the
    counts what rules handle beneath that they do not show as such
    (:func:`handled_beneath`). Taken on the snapshot before *hide ok* and *hide
    idle* drop nodes, as the page's containers are."""
    counts = dict.fromkeys(COUNTED_STATES, 0)
    damped: list[tuple[int, int]] = []
    running = 0
    if not node.children:
        if node.reasons:
            for line in node.reasons:
                counts[line_counts_as(node, line)] += 1
                running += 1 if line.running else 0
        else:
            counts[counts_as(node)] += 1
        if node.damping is not None:
            damped.append((node.damping.seen, node.damping.needed))
    else:
        # A stack in the order the page draws, and no closure that calls itself,
        # which would hold what it counted for the cycle collector at every page.
        stack = [node]
        while stack:
            branch = stack.pop()
            if not branch.children:
                counts[counts_as(branch)] += 1
                running += sum(1 for line in branch.reasons if line.running)
                if branch.damping is not None:
                    damped.append((branch.damping.seen, branch.damping.needed))
                continue
            if counts_as(branch) in ("error", "warn"):
                counts[counts_as(branch)] += 1
                if branch.damping is not None:
                    damped.append((branch.damping.seen, branch.damping.needed))
            stack.extend(reversed(branch.children))
    return ChipCounts(counts=counts, handled_by=handled_beneath(node),
                      running=running, damped=tuple(damped))


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

    ``shown`` says which kind of row this is: a change of what the node **showed**,
    or of what its check reports where the node did not show it — beneath a pin, or
    where a configured rule on its lines keeps it from the node (ADR-0137). It is the
    mark's to say where the mark says it, maintenance marking only a reading the node
    did not show; a configured rule marks both kinds, so its rows say it themselves,
    and so does a *seen* (ADR-0142).

    ``ended`` says why an acknowledgment ended, on the row of its end — one of the
    ``ENDED_`` words — and is empty on every other row (ADR-0142).
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
    #: Set from the mark where the row does not say it (:meth:`__post_init__`).
    shown: bool | None = None
    ended: str = ""

    def __post_init__(self) -> None:
        """``timestamp`` is an instant, held in UTC (ADR-0120): an event cannot be
        built with a time without a zone. A row that does not say whether its node
        showed it is read by its mark (:data:`HIDES_THE_READING`)."""
        object.__setattr__(self, "timestamp", instants.utc(
            self.timestamp, "an event's timestamp"))
        if self.shown is None:
            object.__setattr__(self, "shown",
                               self.suppressed_by not in HIDES_THE_READING)

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
        if self.shown is not (self.suppressed_by not in HIDES_THE_READING):
            # Only where the mark does not say it: a configured rule's row of a
            # reading the node did not show (ADR-0137).
            raw["shown"] = self.shown
        if self.ended:
            raw["ended"] = self.ended
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
                   cause=str(data.get("cause", "")), reported=reported,
                   shown=shown if isinstance(shown := data.get("shown"), bool)
                   else None, ended=str(data.get("ended", "")))


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
    file written before the key.

    ``period`` is the period of what the node shows where it stands above others
    (ADR-0132 decision 1), in a key of its own, which a release before it passes
    over: it reads the keys it knows. ``None`` for a leaf, whose one period is
    ``began``, and for every node of a file written before the key. The root and a
    container that declares nothing have an entry for it alone, their two codes
    ``UNDEFINED`` — the two every entry carries, since a release before requires
    them."""
    shows: StatusCode
    reported: StatusCode
    began: Beginning | None = None
    publishes: StatusCode | None = None
    period: Period | None = None

    def to_dict(self) -> dict[str, Any]:
        """The entry as the state file carries it: the two codes by name, what the
        node publishes where it is waiting, its own period's beginning where one is
        known, and under ``period`` the period of what it shows where it has one."""
        return {"shows": self.shows.name, "reported": self.reported.name,
                **({} if self.publishes is None
                   else {"publishes": self.publishes.name}),
                **({} if self.began is None else self.began.to_dict()),
                **({} if self.period is None
                   else {"period": self.period.to_dict()})}


@dataclass(frozen=True)
class Period:
    """The period of what a node above others shows (ADR-0132): ``code``, what the
    node rolls up to — staleness included — and when that began, in the words a
    node's own period is kept in (``began``: the instant, and either ``before``, a
    bound, or how it began, ``was`` and ``cause``); and ``by``, the path of the node
    whose change began it (decision 4).

    ``by`` is empty where the beginning is a bound: nothing says how it began. It is
    the branch's own path where its own change began the period, and a dependency's
    where a shield moved the branch — which need not stand beneath it. Where a rule
    the deployment configures began it (:data:`CAUSE_RULE`), ``by`` is the node whose
    count the rule changed and ``rule`` the rule's name (ADR-0137 decision 11); empty
    everywhere else.

    Every node above others has one once it has shown a status — the root included,
    and a node that declares nothing of its own. It is kept beside the log and changed
    whenever what the node rolls up to changes, at a write or at a tick, and never
    written as a row (decision 1); a node with nothing beneath it has none, its one
    period being its own."""
    code: StatusCode
    began: Beginning
    by: str = ""
    rule: str = ""

    def to_dict(self) -> dict[str, Any]:
        """The period as a branch's entry keeps it under ``period`` (ADR-0132
        decision 4): ``code``, then ``since`` and either ``before``, a bound, or
        ``was`` and ``cause`` where they are said — the words of a node's own
        (:meth:`Beginning.to_dict`) — then ``by`` where a node is named, and ``rule``
        where a rule began it. A bound has no ``was``, ``cause`` or ``by``; a
        difference a tick found that no change explains has ``was`` and neither of
        the other two."""
        return {"code": self.code.name, **self.began.to_dict(),
                **({"by": self.by} if self.by else {}),
                **({"rule": self.rule} if self.rule else {})}


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


def _period_of(raw: object) -> Period:
    """The period a branch's entry keeps under ``period`` (ADR-0132).
    :class:`ValueError` where it is not the shape :meth:`Period.to_dict` writes: not
    a mapping, a code that is none, a beginning without ``since`` or of a shape a
    node's own may not take (:func:`_beginning_of`), a ``by`` or a ``rule`` that is no
    text, a bound that names the node that began it, or a rule named where no rule
    began it."""
    if not isinstance(raw, Mapping):
        raise ValueError("a branch's period is not a mapping")
    code = raw.get("code")
    if not isinstance(code, str) or code not in StatusCode.__members__:
        raise ValueError(f"a branch's period says no code it shows: {code!r}")
    began = _beginning_of(raw)
    if began is None:
        raise ValueError("a branch's period says not when it began")
    by, rule = raw.get("by", ""), raw.get("rule", "")
    if not isinstance(by, str):
        raise ValueError(f"a branch's period names no node: {by!r}")
    if not isinstance(rule, str):
        raise ValueError(f"a branch's period names no rule: {rule!r}")
    if began.before and by:
        raise ValueError("a branch's period bounds its beginning, and names the "
                         "node that began it")
    if rule and began.cause != CAUSE_RULE:
        raise ValueError("a branch's period names a rule, and no rule began it")
    return Period(StatusCode[code], began, by=join_path(by) if by else "", rule=rule)


def nodes_from_payload(payload: object) -> dict[str, LastShown] | None:
    """What a state file's payload says every node last showed and last reported
    (ADR-0110 decision 2), by path — with its own period's beginning, what it
    publishes while it waits, and for a branch the period of what it shows (ADR-0132)
    — or ``None`` where it carries no such table: a
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
        period = raw.get("period")
        kept[join_path(str(path))] = LastShown(
            codes[0], codes[1], _beginning_of(raw),
            None if waits is None else StatusCode[waits],
            None if period is None else _period_of(period))
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
        if event.shown:
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
    (:meth:`StatusTree.restore_maintenance`).

    ``accepted`` are lines whose acknowledgment to count as still standing, by slug:
    those a reading has just ended, which is how the row of what the node shows tells
    whether their end is what changed it (ADR-0142)."""
    node: bool = False
    lines: frozenset[str] = frozenset()
    accepted: frozenset[str] = frozenset()


@dataclass(frozen=True)
class _Ended:
    """An acknowledgment a write ended (ADR-0142): the line it stood on by its slug,
    empty for its node's own, the pin, and why — one of the ``ENDED_`` words."""
    slug: str
    pin: Pin
    why: str


@dataclass(frozen=True)
class _Damped:
    """One node's damping state, in terms of what the node **shows** (ADR-0108):
    what it published upward, the worse status it is holding back (``None`` when it
    is holding nothing), and how many consecutive readings have shown it."""
    published: StatusCode
    pending: StatusCode | None
    seen: int


@dataclass(frozen=True)
class _Inputs:
    """What the bookkeeping reads of one node (ADR-0132): what its check reported,
    its own status, whether its reading is past its tolerance, whether a pin on it —
    or its check's word — cancels what is beneath it, its damping counter and how
    many readings that waits for. A node no check has written in this process, whose
    unit has not run, is read off its kept entry and is not weighed stale (decision
    3); ``carried`` says so, where that entry says it showed something."""
    reported: StatusCode
    own: StatusCode
    stale: bool = False
    pinned: bool = False
    damped: _Damped | None = None
    escalate_after: int = 1
    carried: bool = False
    #: Whether a person's acknowledgment stands on the node itself (ADR-0142), which
    #: makes its parent count its own part as ``OK``.
    accepted: bool = False


#: What a container on the way to a node the tree does not hold yet holds itself.
_NOTHING = _Inputs(StatusCode.UNDEFINED, StatusCode.UNDEFINED)


@dataclass(frozen=True)
class _Part:
    """What one node is, for the bookkeeping (ADR-0132): what it rolls up to
    (``code``), what its parent counts of it (``counted``), what it counts for itself
    (``own``), the dependency that shields it (``shield``), and the code a damping
    counter publishes for it while a wait holds (``held``) — the last three being its
    **own part**, which is what a change moves. ``beneath`` names the nodes beneath it
    in the order the tree draws them, and ``order`` sorts it where the tree draws it:
    a node before its children, siblings by their declared rank and name (ADR-0055).
    ``carried`` says the node counts at its kept entry, its unit not yet run in this
    process, and ``carrying`` that it or a node beneath it does (decision 3)."""
    code: StatusCode
    counted: StatusCode
    own: StatusCode
    shield: str | None
    held: StatusCode | None
    beneath: tuple[str, ...]
    order: tuple[tuple[int, str], ...]
    carried: bool = False
    carrying: bool = False
    #: What its parent counts of it and the rule that made that something else —
    #: the snapshot's :attr:`StatusSnapshot.contribution` — and whether a reading at
    #: or beneath it is past its tolerance, which a configured rule's table never
    #: counts for less than a warning (ADR-0137).
    contribution: Contribution | None = None
    stale: bool = False
    #: Whether a person's acknowledgment stands on it (ADR-0142): part of its own
    #: part, which a change moves, since its set and its end move what its parent
    #: counts without moving what it counts for itself.
    accepted: bool = False


@dataclass(frozen=True)
class ShownPeriod:
    """One period of what a node above others showed, which ended (ADR-0132 decision
    6): ``code``, ``began`` — the instant, and either a bound or what came before and
    what moved it — ``until``, when the next began, and ``by``, the node whose change
    began it; empty where the beginning is a bound. ``rule`` names the rule the
    deployment configures where one began it, as :attr:`Period.rule` does."""
    code: StatusCode
    began: Beginning
    until: datetime
    by: str = ""
    rule: str = ""


@dataclass
class _Write:
    """One write, compared whole (ADR-0132 decision 2): a stored run, or a change
    outside one. ``at`` is its one instant, ``before`` what every node was when it
    began, and ``rows`` the rows it logged, which say what moved each node."""
    at: datetime
    before: dict[str, _Part]
    rows: list[Event] = field(default_factory=list)


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
                 pin_store: PinStore | None = None) -> None:
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
        # The period of what each node above others shows (ADR-0132): what it rolls
        # up to, since when, how that began and the node whose change began it —
        # compared with what the tree rolls up to at every write and every tick
        # (:meth:`_compare`), seeded at a first start from the log it restores, and
        # never written as a row.
        self._periods: dict[str, Period] = {}
        # The nodes whose unit has run once in this process, by their segments: what
        # each stored run answered for (:meth:`storing`). Beneath one, a node counts
        # for the bookkeeping as the tree has it; elsewhere one no check has written
        # yet counts at its kept entry (ADR-0132 decision 3).
        self._ran: set[tuple[str, ...]] = set()
        # The write in progress (ADR-0132 decision 2) — a stored run, or a change
        # outside one — compared whole when it ends.
        self._writing: _Write | None = None
        # When the bookkeeping last compared: how far back a comparison looks for the
        # readings that have gone stale since.
        self._compared_at: datetime | None = None
        # Whether entries were adopted since the last tick (ADR-0077): what the next
        # tick then finds that no change explains is the takeover's, and anywhere
        # else a change the bookkeeping missed, which the log says (ADR-0132
        # decision 3).
        self._adopted = False
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
        # ``maintenance`` bool and written through to ``pin_store`` on every
        # change (ADR-0014). No store (the default) means in-memory only. A pin is
        # held against its **path**, whether or not the tree holds a node there
        # (ADR-0109 decision 4): none is made for it, and one the tree makes at
        # the path takes it (:meth:`_furnish`).
        self._maintenance: dict[str, Pin] = {}
        # Per-entry pins (ADR-0036): the same side-table, keyed one level deeper —
        # ``(path, slug)``. Deliberately **outside** the check's output: the check
        # emits `slug -> text` and nothing else, and the snapshot joins the two, so
        # the next run cannot destroy a pin and nothing derived is written into the
        # tree (ADR-0032 rule 3).
        self._entry_maintenance: dict[tuple[str, str], Pin] = {}
        # A person's acknowledgments (ADR-0142): one per node, and one per line by
        # its node's path and its slug, beside the pins and kept in the same file.
        # Each is bound to what it accepted, which the readings check: a node's own
        # changes what its parent counts of it, a line's what its node shows.
        self._acknowledged: dict[str, Pin] = {}
        self._entry_acknowledged: dict[tuple[str, str], Pin] = {}
        self._pin_store = pin_store
        # Check mounts: the nodes a check writes its result root to, seeded at
        # startup. Read only by the snapshot's timestamp roll-up (ADR-0027); the
        # tree itself stays check-agnostic and derives nothing into the nodes.
        # Mount path -> how many checks write there (ADR-0027 as amended by
        # ADR-0044): the count is what tells a sole-check mount, whose stamp an
        # unwritten ancestor may inherit, from a shared one, whose two run times
        # must not be attributed upward as if they were one.
        self._check_mounts: dict[str, int] = {}
        # The nodes a run named (ADR-0118) — a result that says ``dynamic``: the
        # first look's resolver and the engine read it, since such a node takes
        # nothing declared for its name, only its parent's ``children:`` (ADR-0128).
        # Beside the mounts and for their reason: what the check behind a node says
        # of it, kept off the nodes, so the snapshot and the envelope do not grow
        # (ADR-0025, ADR-0080). It fills as runs write and starts empty after a
        # restart, so no node is read as named before its run has said; a node a
        # run removes leaves it.
        self._named_by_run: set[str] = set()
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
        # The configured rules (ADR-0137), read once at the start: static for the
        # life of the process, as the configuration is, and read by the snapshot and
        # the bookkeeping alike, so that what a branch's period is of is what its
        # snapshot says.
        self._rules: RuleSet = NO_RULES
        # The tags (ADR-0139): the known ones, which order what a node lists, and
        # those the configuration writes for a path — a check's file and
        # `nodes.yaml`, added up — read once at the start, before the rules, which
        # may pick by them. What a check's `subnodes:` block gives an aspect's name
        # the engine writes on the node itself (`named_tags`).
        self._tag_vocabulary: Vocabulary = NO_VOCABULARY
        self._declared_tags: dict[str, Tags] = {}
        self._written_tags: frozenset[str] = frozenset()
        self._tag_orders: dict[frozenset[str], Tags] = {}

    def use_pin_store(self, store: PinStore) -> None:
        """Attach the pins' store (once, at startup, before restore)."""
        self._pin_store = store

    def use_aggregation(self, rules: RuleSet) -> None:
        """Take the configured rules (ADR-0137) — once, at startup, before the log
        and the pins are restored, so that the periods a restart seeds are of what
        the tree rolls up to under them."""
        with self._lock:
            # bound to what this tree's nodes carry, which a rule with `tag:` picks
            # by (ADR-0139 decision 7)
            self._rules = rules.bound(self._carried_tags) if rules else rules

    @property
    def rules(self) -> RuleSet:
        """The configured rules the tree rolls up by (ADR-0137), for the index."""
        return self._rules

    def use_tags(self, vocabulary: Vocabulary,
                 declared: Mapping[str, Iterable[str]],
                 written: Iterable[str] = ()) -> None:
        """Take the known tags and the tags the configuration writes for each path —
        a check's file for its own node and ``nodes.yaml``, added up (ADR-0139
        decision 2) — once, at startup, before the rules are read. A path no node
        stands at yet keeps its tags for the node a run makes there. ``written`` is
        every tag the configuration writes anywhere, an aspect's name's among them,
        which the wall's filter offers beside the known ones (decision 5)."""
        with self._lock:
            self._tag_vocabulary = vocabulary
            self._declared_tags = {join_path(path): tuple(given)
                                   for path, given in declared.items() if given}
            self._written_tags = frozenset(written).union(
                *self._declared_tags.values())
            self._tag_orders = {}
            self._rules.forget()

    @property
    def offered_tags(self) -> Tags:
        """The tags the wall's filter offers (ADR-0139 decision 5): the known ones in
        their order, then any other the configuration writes, by name."""
        with self._lock:
            return self._tag_vocabulary.ordered(
                self._written_tags.union(self._tag_vocabulary.lines))

    @property
    def written_tags(self) -> frozenset[str]:
        """Every tag the configuration writes for a node, which a selector's
        ``tag:`` is held to (decision 7)."""
        with self._lock:
            return self._written_tags

    def _carried_tags(self, path: str) -> frozenset[str]:
        """What a node at ``path`` carries — what the rules pick by (decision 7):
        every tag written for its path or a path above it, and those an aspect's
        name gives the nodes along it that the tree holds. A path no node stands
        at yet carries what is written for it, as the node a run makes there will
        (decision 2), so that an answer worked out before the node stands — the
        past a restart reads, an event of a node gone — is the one after it."""
        with self._lock:
            node: Status | None = self._root
            carried = set(self._own_tags(self._root))
            walked = ""
            for segment in split_path(path):
                walked = f"{walked}{PATH_SEP}{segment}"
                node = None if node is None else _child_by_name(node, segment)
                carried.update(self._own_tags(node) if node is not None
                               else self._declared_tags.get(walked, ()))
            return frozenset(carried)

    @property
    def tag_vocabulary(self) -> Vocabulary:
        """The known tags (ADR-0139 decision 3), each with what it means, in the
        order the wall's filter offers them."""
        return self._tag_vocabulary

    def tags_given(self, path: str) -> tuple[tuple[str, str], ...]:
        """Every tag the node at ``path`` carries, in the order its *About* card
        lists them, each with the node it is written on: the node itself where it is
        written for it, else the nearest node above it that is (ADR-0139 decision 4).
        None where no node stands there. Resolved down the live tree on demand, as a
        card's details are."""
        with self._lock:
            node = self._root
            at: dict[str, str] = dict.fromkeys(self._own_tags(node), node.path)
            for segment in split_path(path):
                child = _child_by_name(node, segment)
                if child is None:
                    return ()
                node = child
                for tag in self._own_tags(node):
                    at[tag] = node.path
            return tuple((tag, at[tag]) for tag in self._ordered_tags(frozenset(at)))

    def tags_of(self, path: str) -> Tags:
        """The tags a node at ``path`` carries, in their order — its own and every
        one written above it — and, where no node stands there, every tag written
        for its path or above it and those an aspect's name gives the nodes above
        it that the tree holds, every one of which a node at ``path`` carried too
        (ADR-0139 decision 7): what an event of a node gone is matched by."""
        with self._lock:
            return self._ordered_tags(self._carried_tags(path))

    def _own_tags(self, node: Status) -> Tags:
        """The tags written for ``node`` itself: those its path is given and those
        its name is given under its check's ``subnodes:`` block, added up."""
        declared = self._declared_tags.get(node.path, ())
        if not node.named_tags:
            return declared
        return tags_union(declared, node.named_tags)

    def _ordered_tags(self, carried: frozenset[str]) -> Tags:
        """``carried`` in the order a node lists its tags — the known ones in their
        files' order, the rest by name — worked out once for each set."""
        if not carried:
            return ()
        ordered = self._tag_orders.get(carried)
        if ordered is None:
            ordered = self._tag_orders[carried] = self._tag_vocabulary.ordered(carried)
        return ordered

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
               handbook: str | None = None,
               type_details: Details | None = None,
               named_details: Details | None = None,
               named_tags: Tags | None = None,
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
        never rewrites it). Metadata, so no event either. ``handbook`` is a label
        too (ADR-0133 decision 3) and fills the same way, which is what keeps a
        node's *Handbook* tab from coming and going with a reading.

        ``type_details`` and ``named_details`` are no labels (ADR-0133 decision 6)
        and write through, like ``description``: what the type gave the node's object
        with this run, and what the deployment gives the node's name under its
        check's ``subnodes:`` block. The deployment's by path are seeded
        (:meth:`set_details`) and kept apart, so that neither write touches them.
        ``named_tags`` write through the same way (ADR-0139 decision 2): the tags the
        deployment gives the node's name there, those its path is given being the
        tree's (:meth:`use_tags`).

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

        **A reading is one write** (ADR-0132 decision 2), and inside a stored run
        (:meth:`storing`) part of the run's: the node is stamped with the write's one
        instant, and the bookkeeping compares the branches above it when the write
        ends.
        """
        with self._lock, self._one_write() as moment:
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
            if handbook and not node.handbook:
                node.handbook = handbook
            if type_details is not None:
                node.type_details = type_details
            if named_details is not None:
                node.named_details = named_details
            if named_tags is not None and named_tags != node.named_tags:
                node.named_tags = named_tags
                # what the node carries changed, which a rule may pick by
                self._rules.forget()
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
            node.update(code, reason, members, at=moment)
            self._entry_count += len(node.reason_entries) - held
            # What the reading ends of what a person accepted on the node and its
            # lines (ADR-0142), before anything counts what the node shows now.
            ended = self._ended_by(node)
            # Every reading advances the counter, including one that changed
            # nothing: *three consecutive readings of ERROR* is three readings, and
            # only the first of them is a transition.
            reached = self._damp(node)
            wrote = self._record_reading(node, shown, reported, ran_out, ended)
            if ended:
                self._persist()
            if reached and self._shields(moment).get(node.path) is None:
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

    def about(self, path: str) -> str:
        """The ``about`` the node at ``path`` carries, or ``""`` where it carries
        none or no node stands there — so whether a run's label would fill it
        (ADR-0025), which the engine asks before it names a long one (backlog #91
        §3.5). Thread-safe."""
        with self._lock:
            node = self._find_node(path)
            return node.about if node is not None else ""

    def set_title(self, path: str, title: str) -> None:
        """Seed a node's ``title`` (a short display label; ADR-0017) — like
        :meth:`set_about`, metadata only, no event. Thread-safe."""
        self._seed(path, "title", title)

    def set_handbook(self, path: str, handbook: str) -> None:
        """Seed a node's ``handbook`` (ADR-0133 decision 3) — the text, a stated
        file having been read where it was stated — like :meth:`set_about`,
        metadata only, no event. Thread-safe."""
        self._seed(path, "handbook", handbook)

    def handbook(self, path: str) -> str:
        """The handbook the node at ``path`` carries, or ``""`` where it carries
        none or no node stands there: what its *Handbook* tab reads, the snapshot
        saying only that there is one (ADR-0133 decision 3), and what a run's
        label would fill. Thread-safe."""
        with self._lock:
            node = self._find_node(path)
            return node.handbook if node is not None else ""

    def set_details(self, path: str, details: Details) -> None:
        """Seed the details the deployment declares for a node's path (ADR-0133
        decision 6) — ``nodes.yaml`` over the check's own file, merged key by key —
        like :meth:`set_about`, metadata only, no event. Thread-safe."""
        self._seed(path, "declared_details", details)

    def details(self, path: str) -> tuple[Row, ...]:
        """The rows of the *About* card of the node at ``path`` (ADR-0133 decision 6),
        or none where no node stands there: its own details and what the deployment
        gives every node above it, which holds for every node beneath, key by key, the
        nearest winning — in the card's order, each row saying the node it is given on
        (:func:`little_sister.details.rows`). Resolved down the live tree on demand,
        since only a node's own page and its Copy document show them; the snapshot
        holds a node's own. Thread-safe."""
        with self._lock:
            node = self._root
            above: list[tuple[str, Details]] = []
            for segment in split_path(path):
                if given := _given_details(node):
                    above.append((node.path, given))
                child = _child_by_name(node, segment)
                if child is None:
                    return ()
                node = child
            return node_details.rows(node.path, self._type_details(node),
                                     _given_details(node), above)

    def own_details(self, path: str) -> tuple[Detail, ...]:
        """The node's own details as its snapshot holds them, or none where no node
        stands there: what the startup record looks for a link into the handbook in
        that leads nowhere, once a run has first filled the node (ADR-0133 decision
        4). Thread-safe."""
        with self._lock:
            node = self._find_node(path)
            return () if node is None else _own_details(node, self._type_details(node))

    def _type_details(self, node: Status) -> Details:
        """What the type gave ``node``, or nothing on a node two checks mount, where
        two runs write it (ADR-0044 decision 1)."""
        return () if self._check_mounts.get(node.path, 0) > 1 else node.type_details

    def texts(self, path: str) -> dict[str, str]:
        """What the node at ``path`` says of itself in Markdown — its ``about``,
        ``title``, ``description`` and ``handbook``, by those names — or nothing where
        no node stands there: what the startup record looks for a link into the
        handbook in that leads nowhere, once a run has first filled the node (ADR-0133
        decision 4). Thread-safe."""
        with self._lock:
            node = self._find_node(path)
            if node is None:
                return {}
            return {"about": node.about, "title": node.title,
                    "description": node.description, "handbook": node.handbook}

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

    def note_named_by_run(self, path: str, named: bool) -> None:
        """Keep whether the run that wrote the node at ``path`` named it — said
        ``dynamic`` (ADR-0118) — as the engine writes each node. Registry-only, like
        :meth:`set_check_mount`: nothing is written onto a node. Thread-safe."""
        with self._lock:
            key = join_path(path)
            if named:
                self._named_by_run.add(key)
            else:
                self._named_by_run.discard(key)

    def named_by_run(self, path: str) -> bool:
        """Whether the last run that wrote the node at ``path`` named it. A node no
        run has written since the start is not, until one says. Thread-safe."""
        with self._lock:
            return join_path(path) in self._named_by_run

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
        the run's wall time and the engine's **armed next slot** (ADR-0044) — or
        a unit's for the node it answers for, and a container's between that node
        and the mount (ADR-0130 decision 5).

        Registry-only, like :meth:`set_check_mount`: no node is created, nothing
        is stored on one, and the snapshot resolves the facts onto exactly the
        nodes whose subtree holds **one** check — never a shared mount, never
        its ancestors — and onto every node the engine set facts for by this
        call. ``next_run_at`` must come from the engine's schedule,
        already projected onto the wall clock: under the budgeted retry
        (ADR-0033) the armed slot is pulled in, which is why it is never
        computed from ``timestamp + frequency``.
        """
        with self._lock:
            self._run_facts[join_path(path)] = RunFacts(wall_seconds,
                                                        next_run_at)

    def set_maintenance(self, path: str, note: str | None = None, *,
                        expires_at: datetime, set_by: str = "",
                        expected_set_at: str | None = None) -> PinWrite:
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
        (:attr:`Pin.token`), or ``""`` for *"I believe nothing is
        pinned"*. When it does not match what the table holds,
        **nothing is written** and the refusal carries the stored entry. ``None``
        — the default, and what the startup replay uses — writes unguarded.

        A set that says what the stored pin says — the same note, the same
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
                return PinWrite(False, stored, refused=True)
            # Taken under the lock, so the log stays in the order it was written.
            moment = instants.now()
            entry = Pin(
                MAINTENANCE,
                note=note or NO_NOTE,
                set_at=moment,
                expires_at=expires_at,
                set_by=set_by,
                created_at=stored.created_at if stored else moment,
                created_by=stored.created_by if stored else set_by,
                id=stored.id if stored else "")
            if stored is not None and stored.same_pin_as(entry):
                return PinWrite(False, stored)
            # A pin set or edited is one write, at that instant (ADR-0132 decision 2).
            with self._one_write(moment):
                self._apply_maintenance(key, entry, when=moment)
            self._persist()
            return PinWrite(True, entry)

    def clear_maintenance(self, path: str, *,
                          expected_set_at: str | None = None) -> PinWrite:
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
                return PinWrite(False, stored, refused=True)
            with self._one_write():
                cleared = self._clear_node(path)
            if cleared:
                self._persist()
            return PinWrite(cleared, None)

    @staticmethod
    def _token_matches(stored: Pin | None,
                       expected_set_at: str | None) -> bool:
        """Whether a guarded write may proceed. ``None`` means unguarded; otherwise
        the token must equal the stored entry's ``set_at`` as it is spelled
        (:attr:`Pin.token`), with ``""`` standing for *"nothing is
        pinned"*."""
        if expected_set_at is None:
            return True
        return (stored.token if stored is not None else "") == expected_set_at

    def restore_maintenance(self, entries: dict[str, Pin],
                            now: datetime | None = None,
                            entry_pins: dict[tuple[str, str],
                                             Pin] | None = None
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
            # Each pin is one write (ADR-0132 decision 2): a replay at this start, and
            # the end of a branch's pin dated at its own expiry, as its row is.
            for entry_path, entry in entries.items():
                key = join_path(entry_path)
                if not entry.is_expired(moment):
                    with self._one_write(moment):
                        self._apply_maintenance(entry_path, entry, replay=True)
                elif (self._restored_shown.get(key) is StatusCode.MAINTENANCE
                      and self._restored_reading.get(key, StatusCode.UNDEFINED)
                      is StatusCode.UNDEFINED):
                    # A maintenance pin always has an end, which it reached.
                    assert entry.expires_at is not None
                    with self._one_write(entry.expires_at):
                        self._log(Event(
                            path=key, name=leaf_name(key),
                            old=StatusCode.MAINTENANCE, new=StatusCode.UNDEFINED,
                            reason=(), timestamp=entry.expires_at,
                            cause=CAUSE_PIN_ENDED, reported=StatusCode.UNDEFINED))
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

    def adopt_maintenance(self, entries: dict[str, Pin],
                          entry_pins: dict[tuple[str, str],
                                           Pin] | None = None,
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
        # An adopted table is one write (ADR-0132 decision 2).
        with self._lock, self._one_write():
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
            expired = [path for path, entry in self._maintenance.items()
                       if entry.is_expired(moment)]
            # An acknowledgment given an end ends there too (ADR-0142), each its row.
            accepted_out: dict[str, list[_Ended]] = {}
            for (path, slug), pin in self._entry_acknowledged.items():
                if pin.is_expired(moment):
                    accepted_out.setdefault(path, []).append(
                        _Ended(slug, pin, ENDED_CLOCK))
            for path, pin in self._acknowledged.items():
                if pin.is_expired(moment):
                    accepted_out.setdefault(path, []).append(
                        _Ended("", pin, ENDED_CLOCK))
            if not (stale_entries or expired or accepted_out):
                return []
            # **The pins a sweep finds run out are one write together**, a node's
            # and a line's alike (ADR-0132 decision 2): a branch whose pinned
            # children both end at 18:00 goes from maintenance to what they show,
            # and never through what one of them shows alone.
            with self._one_write():
                if stale_entries:
                    showing = self._showing(path for path, _slug in stale_entries)
                    for key in stale_entries:
                        del self._entry_maintenance[key]
                    self._emit_line_pins(showing, lambda node: CAUSE_LINE_PIN_ENDED)
                for path in sorted(accepted_out):
                    self._end_acknowledgments(path, accepted_out[path])
                for path in expired:
                    self._clear_node(path)
            self._persist()
            return expired

    def reap_uncovered(self, roots: list[str]) -> list[str]:
        """Drop maintenance whose path **none of ``roots`` covers** — the configured
        checks' roots and the instance's own, segment-wise on one root-to-leaf line
        (:func:`on_same_line`). Run once at startup against the static check set
        (ADR-0014/0015); expiry is the backstop. Returns the reaped paths."""
        with self._lock, self._one_write():
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
            # An acknowledgment no check covers is on a part nothing reports now,
            # and ends so (ADR-0142).
            orphans: dict[str, list[_Ended]] = {}
            for path, pin in self._acknowledged.items():
                if not covered(path):
                    orphans.setdefault(path, []).append(_Ended("", pin, ENDED_GONE))
            for (path, slug), pin in self._entry_acknowledged.items():
                if not covered(path):
                    orphans.setdefault(path, []).append(_Ended(slug, pin, ENDED_GONE))
            for path in sorted(orphans):
                self._end_acknowledgments(path, orphans[path])
            if uncovered or orphan_entries or orphans:
                self._persist()
            return uncovered

    def forget_uncovered(self, roots: Iterable[str]) -> list[str]:
        """Drop what was restored of every node on none of ``roots``' lines — the
        configured checks' and the instance's own — as a pin no check covers is
        reaped (ADR-0110 decision 4, ADR-0014): nothing will read such a node, and
        its entry would be carried in the kept file for good. Run once at startup,
        after the pins' replay, which reads what was restored. Returns the paths
        forgotten, in their order — of the nodes that showed or reported something,
        or whose period began, and not of a branch whose entry kept the period of
        what it shows alone (ADR-0132), which goes with them."""
        lines = list(roots)
        nothing = StatusCode.UNDEFINED
        # A node the configuration no longer has is one write (ADR-0132 decision 2):
        # what it counted for the bookkeeping, at its kept entry, it counts no more.
        with self._lock, self._one_write():
            gone = sorted(
                path for path in {*self._restored_shown, *self._restored_reading}
                if not any(on_same_line(path, root) for root in lines))
            said = [path for path in gone
                    if self._restored_shown.get(path, nothing) is not nothing
                    or self._restored_reading.get(path, nothing) is not nothing
                    or path in self._beginnings]
            for path in gone:
                self._restored_shown.pop(path, None)
                self._restored_reading.pop(path, None)
                self._beginnings.pop(path, None)
                self._periods.pop(path, None)
            return said

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
        nothing, by the cause *removed*, every row of one call at one instant — the
        stored run's, where a run removes it (ADR-0132 decision 2) — and a node's
        children before it. A node no check ever wrote, of which nothing
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

        with self._lock, self._one_write() as when:
            parent = self._find_node(path)
            if parent is None:
                return []
            base = split_path(parent.path)
            leaving: dict[str, tuple[StatusCode, bool]] = {}
            # What each leaving node's check last reported and its lines' words, for
            # the rows of what a person accepted there (ADR-0142).
            readings: dict[str, StatusCode] = {}
            words: dict[str, dict[str, str]] = {}
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
                    readings[node.path] = self._reported(node)
                    words[node.path] = {entry.slug: entry.text
                                        for entry in node.reason_entries}
                    self._entry_count -= len(node.reason_entries)
                    self._damping.pop(node.path, None)
                    self._named_by_run.discard(node.path)
                    if node.named_tags:
                        # what the paths beneath it carry changed, which a rule
                        # may pick by (ADR-0139 decision 7)
                        self._rules.forget()
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
            gone = sorted(leaving, key=lambda left: (
                split_path(left)[len(base)], -len(split_path(left)), left))
            accepted = False
            for left in gone:
                showed, written = leaving[left]
                # What a person accepted on the node, or on a line of it, ends with
                # the node, its row before the removal's (ADR-0142).
                for item in self._acknowledgments_on(left):
                    accepted = True
                    said = words.get(left, {}).get(item.slug, item.slug)
                    self._log(Event(
                        path=left, name=leaf_name(left), old=showed, new=showed,
                        reason=(said,) if item.slug else (), timestamp=when,
                        cause=acknowledgment_cause(item.pin.kind, ENDED,
                                                   line=bool(item.slug)),
                        reported=readings.get(left, self._restored_reading.get(
                            left, StatusCode.UNDEFINED)),
                        ended=ENDED_GONE))
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
            if accepted:
                self._persist()
            return gone

    def pins(self) -> tuple[dict[str, Pin],
                            dict[tuple[str, str], Pin]]:
        """Every pin held: a node's own by its path, and a line's by its path and
        its slug. A snapshot carries the pins of the nodes and lines it holds; this
        is the table whole, with the ones **no node stands for** (ADR-0109 decision
        4) — its node was removed, or no check has written it yet in this process.
        Such a pin silences nothing now, holds again the moment a node returns at
        its path, and ends by its own expiry. Thread-safe."""
        with self._lock:
            return dict(self._maintenance), dict(self._entry_maintenance)

    def maintenance_entry(self, path: str) -> Pin | None:
        """The maintenance entry pinned at ``path``, if any — the path read as
        every write here reads it, with or without its leading slash, so a
        form's ``branch`` finds the pin its own post made."""
        with self._lock:
            return self._maintenance.get(join_path(path))

    # --- per-entry pins (ADR-0036) ---

    def set_entry_maintenance(self, path: str, slug: str,
                              note: str | None = None, *,
                              expires_at: datetime, set_by: str = "",
                              expected_set_at: str | None = None
                              ) -> PinWrite:
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
                return PinWrite(False, stored, refused=True)
            entry = Pin(
                MAINTENANCE,
                note=note or NO_NOTE,
                set_at=moment,
                expires_at=expires_at,
                set_by=set_by,
                created_at=stored.created_at if stored else moment,
                created_by=stored.created_by if stored else set_by,
                id=stored.id if stored else "")
            if stored is not None and stored.same_pin_as(entry):
                return PinWrite(False, stored)
            # A line's pin set is one write, at that instant (ADR-0132 decision 2).
            with self._one_write(moment):
                showing = self._showing([key[0]])
                self._entry_maintenance[key] = entry
                self._emit_line_pins(
                    showing, lambda node: CAUSE_LINE_PIN_SET,
                    lambda node: (*(line.text for line in node.reason_entries
                                    if line.slug == slug), entry.note))
            self._persist()
            return PinWrite(True, entry)

    def clear_entry_maintenance(self, path: str, slug: str, *,
                                expected_set_at: str | None = None
                                ) -> PinWrite:
        """Release a per-entry pin. ``applied`` is ``False`` when there was none.
        An event where the node shows something else without it, as its set was
        (ADR-0107 decision 1), with the node's lines for its reason."""
        with self._lock:
            key = (join_path(path), slug)
            stored = self._entry_maintenance.get(key)
            if not self._token_matches(stored, expected_set_at):
                return PinWrite(False, stored, refused=True)
            with self._one_write():
                showing = self._showing([key[0]])
                existed = self._entry_maintenance.pop(key, None) is not None
                if existed:
                    self._emit_line_pins(showing,
                                         lambda node: CAUSE_LINE_PIN_ENDED)
            if existed:
                self._persist()
            return PinWrite(existed, None)

    def entry_maintenance(self, path: str, slug: str) -> Pin | None:
        """The pin on one reason of ``path``, if any."""
        with self._lock:
            return self._entry_maintenance.get((join_path(path), slug))

    def entry_maintenance_at(self, path: str) -> dict[str, Pin]:
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

    # --- acknowledgments (ADR-0142) ---

    def acknowledgment(self, path: str, slug: str = "") -> Pin | None:
        """The acknowledgment on the node at ``path``, or on its line ``slug`` — the
        path read as every write here reads it. Thread-safe."""
        key = join_path(path)
        with self._lock:
            if slug:
                return self._entry_acknowledged.get((key, slug))
            return self._acknowledged.get(key)

    def acknowledgments(self) -> tuple[dict[str, Pin], dict[tuple[str, str], Pin]]:
        """Every acknowledgment held: a node's own by its path, and a line's by its
        path and its slug — those suspended with them, on a node whose lines are no
        members now. Thread-safe."""
        with self._lock:
            return dict(self._acknowledged), dict(self._entry_acknowledged)

    def acknowledgeable(self, path: str, slug: str = "") -> str:
        """Why the node at ``path``, or its line ``slug``, cannot take a new
        acknowledgment now, in a sentence a refusal says — and empty where it can: it
        fails now, by its own reading or its line's, and nothing on it or above it
        holds it in maintenance, nor accepts it already (ADR-0142). A node whose lines
        are members fails through them, and they take one each. Thread-safe."""
        with self._lock:
            return self._refusal(join_path(path), slug)

    def set_acknowledgment(self, path: str, slug: str, kind: str, note: str, *,
                           expires_at: datetime | None, set_by: str = "",
                           expected_set_at: str | None = None) -> PinWrite:
        """Accept the failure of the node at ``path``, or of its line ``slug``, as
        ``kind`` — or edit the acknowledgment that stands there (ADR-0142). A
        **compare-and-set** write as a pin's is (ADR-0014): ``expected_set_at`` is the
        token of the acknowledgment the caller believes it replaces, ``""`` for none,
        and a mismatch refuses the write whole.

        A new one is taken only where its part fails now (:meth:`acknowledgeable`),
        and is bound to what it accepted, read here: the status it is set at and the
        line's occurrence — its type's field, else its reading's identity — or the
        failing stretch where nothing tells occurrences apart. Its ``problem`` says why
        where it is not taken. An edit keeps what it was bound to, its creation and
        its id, and changes its note and its end; one that changes neither writes
        nothing. Every set and edit is a row of its node, the kind's word and the act
        (:func:`acknowledgment_cause`) — a line's from what its node showed to what
        it shows, a node's own changing nothing its node shows. Thread-safe."""
        moment = instants.now()
        with self._lock:
            key = join_path(path)
            stored = (self._entry_acknowledged.get((key, slug)) if slug
                      else self._acknowledged.get(key))
            if not self._token_matches(stored, expected_set_at):
                return PinWrite(False, stored, refused=True)
            if stored is None:
                problem = self._refusal(key, slug)
                if problem:
                    return PinWrite(False, None, problem=problem)
                status, occurrence = self._accepting(key, slug)
                entry = Pin(kind, note, moment, expires_at, set_by,
                            occurrence=occurrence, status=status)
            else:
                if stored.kind != kind:
                    return PinWrite(False, stored, problem=(
                        f"it is {stored.kind} already, and an edit keeps its kind"))
                entry = Pin(kind, note, moment, expires_at, set_by,
                            stored.created_at, stored.created_by, stored.id,
                            occurrence=stored.occurrence, status=stored.status)
                if stored.same_pin_as(entry):
                    return PinWrite(False, stored)
            # One write, at that instant (ADR-0132 decision 2).
            with self._one_write(moment):
                self._place(key, slug, entry, edited=stored is not None, when=moment)
            self._persist()
            return PinWrite(True, entry)

    def set_acknowledgments(self, parts: Iterable[tuple[str, str]], kind: str,
                            note: str, *, expires_at: datetime | None,
                            set_by: str = "") -> list[tuple[str, str, Pin | None, str]]:
        """Accept each of ``parts`` — a node's path, and a line's slug or empty for
        the node itself — as ``kind``, every one an acknowledgment of its own sharing
        ``note`` and ``expires_at``, each bound to its own failure as it stands and
        ending by itself (ADR-0142): what a ringed check on a node that fails from
        its lines or from beneath it sets. A part that cannot take one now is passed
        over with the sentence why — it recovered since it was listed, or holds one
        already. One write for them all, at one instant. Answers each part with the
        acknowledgment set on it, or ``None`` and why. Thread-safe."""
        moment = instants.now()
        answers: list[tuple[str, str, Pin | None, str]] = []
        with self._lock:
            with self._one_write(moment):
                for path, slug in parts:
                    key = join_path(path)
                    problem = self._refusal(key, slug)
                    if problem:
                        answers.append((key, slug, None, problem))
                        continue
                    status, occurrence = self._accepting(key, slug)
                    entry = Pin(kind, note, moment, expires_at, set_by,
                                occurrence=occurrence, status=status)
                    self._place(key, slug, entry, edited=False, when=moment)
                    answers.append((key, slug, entry, ""))
            if any(pin is not None for _path, _slug, pin, _problem in answers):
                self._persist()
        return answers

    def clear_acknowledgment(self, path: str, slug: str = "", *,
                             expected_set_at: str | None = None) -> PinWrite:
        """End the acknowledgment on the node at ``path``, or on its line ``slug``,
        by hand — a row of its node saying so, as every end says why (ADR-0142).
        Guarded by the same token as a set; ``applied`` is ``False`` where none
        stood. Thread-safe."""
        with self._lock:
            key = join_path(path)
            stored = (self._entry_acknowledged.get((key, slug)) if slug
                      else self._acknowledged.get(key))
            if not self._token_matches(stored, expected_set_at):
                return PinWrite(False, stored, refused=True)
            if stored is None:
                return PinWrite(False, None)
            with self._one_write():
                self._end_acknowledgments(key, [_Ended(slug, stored, ENDED_HAND)])
            self._persist()
            return PinWrite(True, None)

    def restore_acknowledgments(self, nodes: Mapping[str, Pin],
                                lines: Mapping[tuple[str, str], Pin],
                                now: datetime | None = None) -> None:
        """Replay the acknowledgments the pins file kept, at startup (ADR-0142): each
        that has not reached its end stands again, bound to what it accepted, which
        the node's first reading checks. **One that reached its end while the
        instance was down ends there**: its row is dated at its end, and what its
        branch counted moves there, its node counting at its kept entry until it is
        read. What its node shows without it, a line's, the node's first reading
        says."""
        moment = _asked_at(now)
        with self._lock:
            for path, pin in nodes.items():
                self._acknowledged[join_path(path)] = pin
            for (path, slug), pin in lines.items():
                self._entry_acknowledged[join_path(path), slug] = pin
            ran_out = sorted(
                [(join_path(path), "", pin) for path, pin in nodes.items()
                 if pin.is_expired(moment)]
                + [(join_path(path), slug, pin) for (path, slug), pin in lines.items()
                   if pin.is_expired(moment)],
                key=lambda item: (item[2].expires_at or moment, item[0], item[1]))
            for key, slug, pin in ran_out:
                with self._one_write(pin.expires_at):
                    self._end_acknowledgments(key, [_Ended(slug, pin, ENDED_CLOCK)])
            if ran_out:
                self._persist()

    def adopt_acknowledgments(self, nodes: Mapping[str, Pin],
                              lines: Mapping[tuple[str, str], Pin],
                              now: datetime | None = None) -> None:
        """Replace the acknowledgments in a **running** process with those of an
        adopted file (ADR-0077, ADR-0142), as the pins are replaced
        (:meth:`adopt_maintenance`): one this process holds and the file does not, or
        holds ended, ends here with a row that says no why — the holder ended it —
        and one the file holds that this process does not is set, or edited where it
        holds another word of it, each with its row. Nothing is written through: the
        file on disk is the copy being adopted. Thread-safe."""
        moment = _asked_at(now)
        with self._lock, self._one_write():
            kept_nodes = {join_path(path): pin for path, pin in nodes.items()
                          if not pin.is_expired(moment)}
            kept_lines = {(join_path(path), slug): pin
                          for (path, slug), pin in lines.items()
                          if not pin.is_expired(moment)}
            went: dict[str, list[_Ended]] = {}
            for path, pin in self._acknowledged.items():
                held = kept_nodes.get(path)
                if held is None or held.id != pin.id:
                    went.setdefault(path, []).append(_Ended("", pin, ""))
            for (path, slug), pin in self._entry_acknowledged.items():
                held = kept_lines.get((path, slug))
                if held is None or held.id != pin.id:
                    went.setdefault(path, []).append(_Ended(slug, pin, ""))
            for path in sorted(went):
                self._end_acknowledgments(path, went[path])
            when = self._instant()
            for path, pin in sorted(kept_nodes.items()):
                stored = self._acknowledged.get(path)
                if stored is None or not stored.same_pin_as(pin):
                    self._place(path, "", pin, edited=stored is not None, when=when)
            for (path, slug), pin in sorted(kept_lines.items()):
                stored = self._entry_acknowledged.get((path, slug))
                if stored is None or not stored.same_pin_as(pin):
                    self._place(path, slug, pin, edited=stored is not None, when=when)

    def _refusal(self, path: str, slug: str) -> str:
        """:meth:`acknowledgeable`, under the lock."""
        node = self._find_node(path)
        if node is None or node.timestamp is None:
            return f"nothing reports {path} now"
        if node.maintenance:
            return f"{path} is in maintenance"
        above = next((at for at in _ancestors(path) if at in self._maintenance), None)
        if above is not None:
            return f"{path} is in maintenance from {above}"
        if slug:
            line = f"its line {slug}"
            if not node.members:
                return f"{path} reports no line {slug} of its own now"
            entry = next((entry for entry in node.reason_entries
                          if entry.slug == slug), None)
            if entry is None:
                return f"{path} reports no line {slug} now"
            if (path, slug) in self._entry_maintenance:
                return f"{line} is in maintenance"
            if (path, slug) in self._entry_acknowledged:
                return f"{line} is {self._entry_acknowledged[path, slug].kind} already"
            code = entry.code if entry.code is not None else node.code
            if code not in _FAILURES:
                return f"{line} reads {code.name.lower()} now: nothing fails there"
            return ""
        if node.members and node.reason_entries:
            return f"{path} fails by its lines, and each is accepted on its own"
        if path in self._acknowledged:
            return f"{path} is {self._acknowledged[path].kind} already"
        code = self._own(node, accepted=False)
        if code not in _FAILURES:
            return f"{path} reads {code.name.lower()} now: nothing fails there"
        return ""

    def _accepting(self, path: str, slug: str) -> tuple[StatusCode, str]:
        """What a new acknowledgment on the node at ``path``, or on its line
        ``slug``, is bound to (ADR-0142): the failure it reads now, and the line's
        occurrence — empty for a node's own, which is its failing stretch. Asked once
        :meth:`_refusal` said it fails."""
        node = self._find_node(path)
        assert node is not None
        if slug:
            entry = next(entry for entry in node.reason_entries if entry.slug == slug)
            return (entry.code if entry.code is not None else node.code,
                    entry.occurrence)
        return self._own(node, accepted=False), ""

    def _place(self, path: str, slug: str, entry: Pin, *, edited: bool,
               when: datetime) -> None:
        """Hold ``entry`` on the node at ``path``, or on its line ``slug``, and write
        its row (ADR-0142): a line's from what its node showed to what it shows now,
        naming the line and the note; a node's own, which changes nothing its node
        shows, with its note."""
        node = self._find_node(path)
        cause = acknowledgment_cause(entry.kind, EDITED if edited else SET,
                                     line=bool(slug))
        note = (entry.note,) if entry.note else ()
        before = self._shows_at(path, node)
        if slug:
            self._entry_acknowledged[path, slug] = entry
            text = next((line.text for line in node.reason_entries
                         if line.slug == slug), slug) if node is not None else slug
            self._emit_at(path, node, before, self._shows_at(path, node),
                          cause=cause, reason=(text, *note), when=when)
        else:
            self._acknowledged[path] = entry
            self._emit_at(path, node, before, before, cause=cause, reason=note,
                          when=when)

    def _end_acknowledgments(self, path: str, ended: Sequence[_Ended], *,
                             when: datetime | None = None) -> None:
        """Drop the acknowledgments ``ended`` of the node at ``path`` and write the
        row of each, saying why it ended (ADR-0142): the lines' first, the first of
        them from what the node showed to what it shows without them, the rest
        changing nothing more, and the node's own changing nothing its node shows.
        A write that read the node writes its ends with its own rows instead
        (:meth:`_record_reading`)."""
        node = self._find_node(path)
        before = self._shows_at(path, node)
        for item in ended:
            if item.slug:
                self._entry_acknowledged.pop((path, item.slug), None)
            else:
                self._acknowledged.pop(path, None)
        after = self._shows_at(path, node)
        moment = when or self._instant()
        shown = before
        for item in sorted(ended, key=lambda item: item.slug == ""):
            cause = acknowledgment_cause(item.pin.kind, ENDED, line=bool(item.slug))
            now_shows = after if item.slug else shown
            self._emit_at(path, node, shown, now_shows, cause=cause,
                          reason=self._ended_reason(node, item), when=moment,
                          ended=item.why)
            shown = now_shows

    @staticmethod
    def _ended_reason(node: Status | None, item: _Ended) -> tuple[str, ...]:
        """What the row of an acknowledgment's end says it is about: its line, by
        its text where the node holds it — and for a node's own, the node's lines,
        as the end of a pin says them."""
        if item.slug:
            text = next((line.text for line in node.reason_entries
                         if line.slug == item.slug), item.slug) if node else item.slug
            return (text,)
        return tuple(node.reason) if node is not None else ()

    def _acknowledgments_on(self, path: str) -> list[_Ended]:
        """The acknowledgments on the node at ``path`` and on its lines, dropped from
        the tables as ended because the node is no longer reported (ADR-0142): its
        lines' first, then its own."""
        ended = [_Ended(slug, pin, ENDED_GONE)
                 for (at, slug), pin in sorted(self._entry_acknowledged.items())
                 if at == path]
        for item in ended:
            del self._entry_acknowledged[path, item.slug]
        own = self._acknowledged.pop(path, None)
        if own is not None:
            ended.append(_Ended("", own, ENDED_GONE))
        return ended

    def _ended_by(self, node: Status) -> list[_Ended]:
        """The acknowledgments on ``node`` and its lines that the reading it was
        just written with ends (ADR-0142), dropped from the tables: one whose part
        recovered, reads a failure worse than it was set at, or no status, or — a
        line's — whose occurrence is a new one, or which this reading no longer
        reports. A reading whose lines are no members — a check's error, prose —
        says nothing of the lines, whose acknowledgments it leaves suspended, as it
        leaves their pins (ADR-0036 decision 6)."""
        ended: list[_Ended] = []
        own = self._acknowledged.get(node.path)
        if own is not None:
            why = _ending(own, self._own(node, accepted=False, node_pin=False), None)
            if why:
                del self._acknowledged[node.path]
                ended.append(_Ended("", own, why))
        if node.members and self._entry_acknowledged:
            entries = {entry.slug: entry for entry in node.reason_entries}
            for (path, slug), pin in list(self._entry_acknowledged.items()):
                if path != node.path:
                    continue
                entry = entries.get(slug)
                why = ENDED_GONE if entry is None else _ending(
                    pin, entry.code if entry.code is not None else node.code,
                    entry.occurrence)
                if why:
                    del self._entry_acknowledged[path, slug]
                    ended.append(_Ended(slug, pin, why))
        return ended

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
        ADR-0110 decision 2), and for a branch the period of what it shows (ADR-0132).
        The events change only with a row, and the table with a row or with a
        branch's period, which a reading gone stale moves with none.

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
        file without the table — what the rows say (:meth:`_restore_beginnings`).

        **The period of what each branch shows comes back with its entry** (ADR-0132,
        :meth:`_restore_periods`) and goes on from it; on the first start on a file
        written before the key it is seeded from the log restored: its beginning
        where the rows at and beneath it say it, a bound at the log's oldest row
        where they do not."""
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
            self._restore_periods(nodes)
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
            # One write, dated as its row is (ADR-0132 decision 2).
            with self._one_write(since):
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
                      and event.shown]
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
                current: tuple[str, ...] = (pin.note,) if pin.note else ()
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

    @contextmanager
    def storing(self, answers_for: str) -> Iterator[None]:
        """A run's store, seen whole (ADR-0132 decision 2, ADR-0002): the tree's lock
        held from the first node a run writes to the last — the run's node, the nodes
        beneath it, what it no longer returns, and a unit's failure over its node —
        each of those writes re-entering it, so no page, no API call and no tick sees
        half a run. Every node and every row the run writes takes the run's one
        instant, taken as the store takes the lock; and the bookkeeping compares
        every branch above what the run moved once, when the store ends, and dates a
        change by that instant (:meth:`_compare`).

        ``answers_for`` is the node the unit that ran answers for — a check's mount, a
        declared unit's own node, the instance's own branch for the tick's beat. The
        store's end says that unit has run once in this process: a node beneath it
        that the run did not write counts for the bookkeeping as the tree has it, no
        longer at its kept entry (decision 3).

        A store that raises halfway ends all the same, and what it wrote is
        compared. Inside another write it is part of that one, compared when that one
        ends, and its unit has run all the same. Thread-safe."""
        with self._lock:
            outer = self._writing is None
            if outer:
                self._begin(instants.now())
            try:
                yield
            finally:
                self._ran.add(tuple(split_path(answers_for)))
                if outer:
                    self._end()

    def compare_periods(self, now: datetime | None = None) -> None:
        """The tick's comparison (ADR-0132 decision 2): what time alone moved since
        the bookkeeping last compared — a node beneath a branch gone stale, which
        counts at least WARN (ADR-0005), and a shield ended because its dependency
        went silent (ADR-0084) — each dated when that reading went stale, its last
        observation and its tolerance after it (ADR-0079), and not when the tick saw
        it; then every branch against its kept period. ``now`` is an instant, the
        clock's by default. The engine asks it once a tick, after the beat and the
        sweep. Thread-safe."""
        moment = _asked_at(now)
        with self._lock:
            if self._writing is not None:
                return
            current = self._catch_up(moment)
            self._settle(current, moment)
            self._mark_compared(moment)

    def shown_history(self, path: str) -> tuple[list[ShownPeriod], Period | None]:
        """The periods of what the node at ``path`` showed, where it stands above
        others (ADR-0132 decision 6): those that ended, newest first, and the period
        that holds — the one the tree keeps (:meth:`period`), from its entry, so it
        is said past the log's reach. Whether that one is said is the snapshot's to
        decide (:attr:`StatusSnapshot.period`).

        The periods that ended are derived from the rows at and beneath the node,
        and of each dependency a shield there is reached through, as far back as the
        log holds them, replayed through the roll-up as the seed replays them
        (:func:`_replayed`): a write's rows carry its one instant, so a write is
        read whole, as the bookkeeping reads it. The oldest is a bound at the log's
        oldest row. One that the rows say began after the period that holds began is
        no period of the node's — staleness writes no row, so the rows can say
        otherwise of a period it made — and the last before it ends where it began.
        A rule the deployment configures counts in them from where it began (ADR-0137
        decision 11): the start that brought it, where a period the tree keeps says
        so, and the start of the day its ``since:`` names everywhere else.

        **What it reads is copied under the lock, and replayed outside it**
        (ADR-0002), as :meth:`events_payload` copies the log and serializes it
        outside: the rows, what every node shows and reported, the beginnings and
        the dependencies. A replay takes tens of milliseconds on a deployment's log,
        and under the lock every store, the tick and every page would wait it out.
        Thread-safe."""
        key = join_path(path)
        with self._lock:
            current = self._periods.get(key)
            logged = tuple(self._events)
            kept = self._last_shown()
            began = dict(self._beginnings)
            dependencies = dict(self._dependencies)
            rules = self._rules
            starts = self._rule_starts()
            accepted = frozenset(self._acknowledged)
        if not logged:
            return [], current
        scope = _scope_of(key, dependencies)
        events = [event for event in logged
                  if any(_at_or_beneath(event.path, top) for top in scope)]
        if not events:
            return [], current
        entries = {entry_path: entry for entry_path, entry in kept.items()
                   if any(_at_or_beneath(entry_path, top) for top in scope)}
        shows = {at: entry.shows for at, entry in entries.items()}
        reads = {at: entry.reported for at, entry in entries.items()}
        waits = {at: entry.publishes for at, entry in entries.items()
                 if entry.publishes is not None}
        timeline: list[Period] = []
        _replayed(events, shows, reads, waits, began, dependencies,
                  oldest=logged[0].timestamp, watch=key, timeline=timeline,
                  rules=rules, starts=starts, accepted=accepted)
        cut = None if current is None else current.began.at
        ended: list[ShownPeriod] = []
        for index, period in enumerate(timeline):
            following = (timeline[index + 1].began.at if index + 1 < len(timeline)
                         else None)
            if cut is not None:
                if period.began.at >= cut:
                    break
                following = cut if following is None else min(following, cut)
            if following is None:
                break
            ended.append(ShownPeriod(period.code, period.began, following,
                                     period.by, period.rule))
        return ended[::-1], current

    def _rule_starts(self) -> dict[str, datetime]:
        """Where each rule the deployment configures began to count, as far as the
        periods the tree keeps say it (ADR-0137 decision 11): a rule a start brought,
        at that start, by its key — the earliest where several periods say it. A
        replay reads the rest from the day their ``since:`` names. Called under the
        lock."""
        starts: dict[str, datetime] = {}
        for period in self._periods.values():
            if period.began.cause != CAUSE_RULE or not period.rule:
                continue
            rule = self._rules.named(period.rule)
            if rule is not None and (rule.key not in starts
                                     or period.began.at < starts[rule.key]):
                starts[rule.key] = period.began.at
        return starts

    def period(self, path: str) -> Period | None:
        """The period of what the node at ``path`` shows, where it stands above
        others (ADR-0132) — or ``None``: a node with nothing beneath it, whose one
        period is its own (:meth:`history`), and one no status has been seen for.
        Thread-safe."""
        with self._lock:
            return self._periods.get(join_path(path))

    # --- the bookkeeping of what each branch shows (ADR-0132); call only while
    #     holding the lock ---

    @contextmanager
    def _one_write(self, at: datetime | None = None) -> Iterator[datetime]:
        """A change outside a run is one write (ADR-0132 decision 2) — a reading
        written on its own, a pin set, edited or ended, a node the configuration no
        longer has: at its one instant, ``at`` or the clock's, the bookkeeping
        comparing the branches above what it moved when it ends. Inside a stored run
        it is part of the run's, at the run's instant."""
        if self._writing is not None:
            yield self._writing.at
            return
        self._begin(instants.now() if at is None
                    else instants.utc(at, "a write's instant"))
        try:
            assert self._writing is not None
            yield self._writing.at
        finally:
            self._end()

    def _instant(self) -> datetime:
        """The one instant of the write in progress — a stored run's — or the
        clock's outside one."""
        return instants.now() if self._writing is None else self._writing.at

    def _begin(self, at: datetime) -> None:
        """Open a write at ``at``: what time alone moved before it is compared first,
        so a reading that went stale since the last comparison is dated when it went
        stale and not by this write; then what every node is as the write begins."""
        before = self._catch_up(at)
        self._mark_compared(at)
        self._writing = _Write(at, before)

    def _end(self) -> None:
        """Close the write in progress, and compare what it moved by its one
        instant. A row of what a node showed that a configured rule kept from its
        parent is marked by it first (:meth:`_mark_held`)."""
        write, self._writing = self._writing, None
        assert write is not None
        after = self._parts(write.at)
        self._mark_held(write.rows, after)
        self._compare(write.before, after, write.at, rows=write.rows)
        self._mark_compared(write.at)

    def _mark_held(self, rows: list[Event], after: Mapping[str, _Part]) -> None:
        """Mark each row of what a node showed that a configured rule kept from its
        parent (ADR-0137 decision 11): its node's part names the rule as what its
        parent counts of it, and counts for less than it shows — a cap, healing, the
        part left out, a count while it holds — once the write is whole, since a rule
        on a node or a count over its parent's children reads the roll-up and the
        node's siblings, which no row of a run has before the run is stored. A floor
        holds nothing back: what it raised reached its parent, as more. A row a rule
        before it marked keeps that mark — the shield and damping say what they hold
        as they always have — and a row its node did not show is the pins' and the
        lines' rules' (:meth:`_record_reading`).

        **A reading's row a person's acknowledgment kept from the node's parent** is
        marked by its kind the same way (ADR-0142), and only a reading's: the rows of
        the acknowledgment's own set, edit and end are its record, not a change it
        held back."""
        for index, row in enumerate(rows):
            part = after.get(row.path)
            if (not row.shown or row.suppressed_by or part is None
                    or part.contribution is None
                    or not _counts_for_less(part.contribution.code, part.code)):
                continue
            by = part.contribution.by
            if not (by == AGGREGATION_RULE or (
                    by == SEEN_RULE
                    and row.cause in ("", CAUSE_READING, CAUSE_REACHED))):
                continue
            marked = replace(row, suppressed_by=by)
            rows[index] = marked
            for at in range(len(self._events) - 1, -1, -1):
                if self._events[at] is row:
                    self._events[at] = marked
                    break

    def _mark_compared(self, at: datetime) -> None:
        if self._compared_at is None or at > self._compared_at:
            self._compared_at = at

    def _catch_up(self, now: datetime) -> dict[str, _Part]:
        """Compare what time alone moved since the bookkeeping last compared, and
        answer what every node is at ``now`` (ADR-0132 decision 2).

        Each moment a node written in this process went stale in between — its last
        observation and its tolerance after it — is one change, every node gone
        stale at that instant together, compared at that moment by the cause
        *stale*: a node beneath a branch now counts at least WARN, and a shield whose
        dependency went silent ends. Nothing else moves without a write.

        A moment at the instant of the last comparison is one of them: a reading is
        stale only once its age is *past* its tolerance (:func:`_is_stale`), so that
        comparison saw it fresh; one at ``now`` is the next comparison's."""
        since = self._compared_at
        if since is None:
            return self._parts(now)
        moments = sorted({moment for moment in self._stale_moments()
                          if since <= moment < now})
        if not moments:
            return self._parts(now)
        previous = self._parts(since)
        for moment in moments:
            current = self._parts(moment + _JUST_AFTER)
            self._compare(previous, current, moment, cause=CAUSE_STALE)
            previous = current
        return self._parts(now)

    def _stale_moments(self) -> Iterator[datetime]:
        """When each node written in this process goes stale unless it is read
        again — its last observation and its tolerance after it (ADR-0079) — for
        every node :func:`_is_stale` weighs."""
        nodes = [self._root]
        while nodes:
            node = nodes.pop()
            nodes.extend(node.get_children())
            if node.timestamp is None or node.code in (StatusCode.UNDEFINED,
                                                       StatusCode.MAINTENANCE):
                continue
            tolerance = node_stale_after(node)
            if tolerance is not None:
                yield node.timestamp + timedelta(seconds=tolerance)

    def _parts(self, now: datetime, *,
               rules: RuleSet | None = None) -> dict[str, _Part]:
        """What every node is at ``now``, for the bookkeeping (ADR-0132): the tree as
        the snapshot reads it, and beside it every node no check has written in this
        process whose unit has not run, at what its kept entry says it showed and
        not weighed stale (decision 3) — beneath the containers on the way to it,
        which hold nothing of their own. ``rules`` stands in for the configured
        rules, which is how a start tells what they make of the kept entries
        (:meth:`_rules_began`)."""
        beneath: dict[str, list[str]] = {}
        keys: dict[str, tuple[int, str]] = {}
        given: dict[str, _Inputs] = {}
        nodes = [self._root]
        while nodes:
            node = nodes.pop()
            children = node.get_children()
            nodes.extend(children)
            beneath[node.path] = [child.path for child in children]
            keys[node.path] = _sibling_key(node)
            if node.timestamp is None and self._carries(node.path):
                given[node.path] = self._carried(node.path)
            else:
                given[node.path] = _Inputs(
                    node.code, self._own(node),
                    _is_stale(node, _age_seconds(node.timestamp, now)),
                    node.maintenance, self._damping.get(node.path),
                    node.escalate_after,
                    accepted=node.path in self._acknowledged)
        for path, shows in self._restored_shown.items():
            if (path in given or shows is StatusCode.UNDEFINED
                    or not self._carries(path)):
                continue
            _link(path, beneath, keys)
            given[path] = self._carried(path)
        return _evaluate(beneath, keys, given, self._dependencies,
                         self._rules if rules is None else rules)

    def _carries(self, path: str) -> bool:
        """Whether the node at ``path`` counts for the bookkeeping at its kept entry:
        the kept file says what it showed, and the unit that answers for it has not
        run in this process (ADR-0132 decision 3). Asked of a node no check has
        written in this process."""
        if path not in self._restored_shown:
            return False
        segments = tuple(split_path(path))
        return not any(segments[:length] in self._ran
                       for length in range(len(segments) + 1))

    def _carried(self, path: str) -> _Inputs:
        """A node as its kept entry has it (ADR-0132 decision 3): what it showed and
        what its check reported, the status it published while it waited
        (ADR-0119), and a pin that cancels what is beneath it — one in the table, or,
        before the pins are replayed, the one its entry says began its period. Not
        weighed stale: its last observation is from before the gap."""
        shows = self._restored_shown.get(path, StatusCode.UNDEFINED)
        published = self._restored_published.get(path)
        began = self._beginnings.get(path)
        pinned = path in self._maintenance or (
            shows is StatusCode.MAINTENANCE and began is not None
            and began.cause in (CAUSE_PIN_SET, CAUSE_PIN_EDITED))
        return _Inputs(
            self._restored_reading.get(path, StatusCode.UNDEFINED), shows,
            pinned=pinned,
            damped=(_Damped(published, shows, 1) if published is not None
                    and escalates(published, shows) else None),
            carried=shows is not StatusCode.UNDEFINED,
            accepted=path in self._acknowledged)

    def _compare(self, before: Mapping[str, _Part], after: Mapping[str, _Part],
                 at: datetime, *, cause: str | None = None,
                 rows: Sequence[Event] = ()) -> None:
        """Weigh every branch above a node one change moved — its own part: what it
        counts for itself, the shield on it, what a wait publishes for it, or that it
        counted at its kept entry and no longer does, its unit having run (decision
        3) — and keep a new period where what the branch rolls up to is not what its
        period says (ADR-0132 decisions 1, 2 and 4). ``at`` dates the change: a
        write's one instant, or the moment readings went stale. ``cause`` says what
        moved it where one word says it for the whole change; otherwise each
        branch's is read off ``rows``, those the write logged."""
        moved = sorted(
            (path for path in before.keys() | after.keys()
             if _own_part(before.get(path)) != _own_part(after.get(path))
             or _carry_ended(before.get(path), after.get(path))),
            key=lambda path: (after.get(path) or before[path]).order)
        weighed: set[str] = set()
        for path in moved:
            for branch in (path, *_ancestors(path)):
                if branch not in weighed:
                    weighed.add(branch)
                    self._weigh(branch, before, after, moved, at, cause, rows)

    def _weigh(self, branch: str, before: Mapping[str, _Part],
               after: Mapping[str, _Part], moved: Sequence[str], at: datetime,
               cause: str | None, rows: Sequence[Event]) -> None:
        """One branch against its kept period, after a change (ADR-0132)."""
        kept = self._periods.get(branch)
        part = after.get(branch)
        if part is None or not part.beneath:
            # Nothing beneath it now, or the tree has it no more: a node with
            # nothing beneath it keeps the one period it has, its own (decision 1).
            # A branch its check removed keeps that it shows nothing since its
            # removal, as its entry does (ADR-0110 decision 4), so that its return is
            # a change the tree saw.
            if part is None and kept is not None and self._was_removed(branch):
                if kept.code is not StatusCode.UNDEFINED:
                    self._periods[branch] = Period(
                        StatusCode.UNDEFINED,
                        Beginning(at, was=kept.code, cause=CAUSE_REMOVED),
                        by=branch)
            else:
                self._periods.pop(branch, None)
            return
        code = part.code
        if kept is None:
            kept = self._inherited(branch, before)
            if kept is None:
                if code is not StatusCode.UNDEFINED:
                    self._periods[branch] = self._first_period(
                        branch, code, before, after, moved, at, cause, rows)
                return
            self._periods[branch] = kept
        if kept.code is code:
            return
        prior = before.get(branch)
        if part.carrying and prior is not None and prior.code is code:
            # Nodes beneath it still count at their entries, and this change did
            # not move what it rolls up to: its period goes on from the entries
            # until the units beneath it have run (decision 3). A carried node is
            # not weighed stale, so where staleness made the period, the entries
            # cannot say it, and a reading that moved nothing is not what ended it.
            return
        by = _by(branch, kept.code, code, before, after, moved)
        self._periods[branch] = Period(
            code, Beginning(at, was=kept.code,
                            cause=cause if cause is not None
                            else _cause_in(by, rows)),
            by=by)

    def _inherited(self, branch: str,
                   before: Mapping[str, _Part]) -> Period | None:
        """The period a node had while nothing stood beneath it — its own (ADR-0132
        decision 1) — for one that has just come to stand above others."""
        prior = before.get(branch)
        began = self._beginnings.get(branch)
        if (prior is None or prior.beneath or prior.code is StatusCode.UNDEFINED
                or began is None):
            return None
        return Period(prior.code, began, by="" if began.before else branch)

    def _first_period(self, branch: str, code: StatusCode,
                      before: Mapping[str, _Part], after: Mapping[str, _Part],
                      moved: Sequence[str], at: datetime, cause: str | None,
                      rows: Sequence[Event]) -> Period:
        """The period of a branch first seen showing a status: a bound at that
        change, since it was already what it shows when it was first seen (ADR-0099
        decision 9) — except on the instance's own branch, which begins with its
        process, where the tree saw it begin."""
        if not self._begins_with_process(branch):
            return Period(code, Beginning(at, before=True))
        by = _by(branch, StatusCode.UNDEFINED, code, before, after, moved)
        return Period(code, Beginning(
            at, was=StatusCode.UNDEFINED,
            cause=cause if cause is not None else _cause_in(by, rows)), by=by)

    def _settle(self, current: Mapping[str, _Part], at: datetime) -> None:
        """Every branch against its kept period, at a tick (ADR-0132 decision 2): a
        node the tree holds no more, or that has nothing beneath it now, keeps none
        — but a branch its check removed, which shows nothing since its removal; a
        branch seen showing a status for the first time is bounded at the tick; and
        one whose period says another code than it rolls up to, which no change of a
        node explains, begins one there, with no cause and no ``by`` (decision 3).
        After a takeover that is what the adopted entries said and this process's
        tree does not; anywhere else it is a change the bookkeeping missed, and the
        log says so. A branch above a node that still counts at its kept entry is
        passed over: its period goes on from the entries until the units beneath it
        have run (decision 3)."""
        adopted, self._adopted = self._adopted, False
        for path in list(self._periods):
            part = current.get(path)
            if part is None and self._was_removed(path):
                continue
            if part is None or not part.beneath:
                del self._periods[path]
        for path, part in current.items():
            if not part.beneath:
                continue
            kept = self._periods.get(path)
            if kept is None:
                if part.code is not StatusCode.UNDEFINED:
                    self._periods[path] = Period(part.code,
                                                 Beginning(at, before=True))
            elif kept.code is not part.code and not part.carrying:
                if not adopted:
                    logger.warning(
                        "tree: %s rolls up to %s where its period says %s since "
                        "%s, and no change seen moved it; a period begins at this "
                        "tick (ADR-0132 decision 3)", path,
                        part.code.name.lower(), kept.code.name.lower(),
                        instants.stamp(kept.began.at))
                self._periods[path] = Period(part.code,
                                             Beginning(at, was=kept.code))

    def _restore_periods(self, nodes: Mapping[str, LastShown] | None) -> None:
        """Put back the period of what each branch shows with the log just restored
        (ADR-0132). A file that keeps them is taken at its word: at a start each goes
        on from its entry until the units beneath it have run (decision 3), and a
        file adopted in a running process (ADR-0077) is merged in: the holder's
        period replaces this process's where the file keeps one, and this process's
        stays where it keeps none, and the next tick compares them with what this
        process's tree rolls up to. A file written before the key keeps none: on a
        first start each is seeded from its log (:meth:`_seed_periods`), and adopted
        it leaves every one of this process's as it is."""
        kept = {path: entry.period for path, entry in (nodes or {}).items()
                if entry.period is not None}
        if self._compared_at is not None:
            self._periods.update(kept)
            self._adopted = True
        elif kept:
            self._periods = kept
            self._rules_began(instants.now())
        else:
            self._periods = self._seed_periods()

    def _rules_began(self, at: datetime) -> None:
        """A start on the periods a kept file says, where the rules the deployment
        configures now count a branch otherwise than its period says (ADR-0137
        decision 11): what they make of the kept entries, each node counting at its
        entry, against what the entries count without them. Where they make the
        difference, the rules this start brought — new, or a table edited — began the
        branch's period at this start, its cause the rule's beginning, by the node
        whose count it changed, naming the rule, rather than at the run that ends the
        entries' count, named by whichever unit ran last (decision 3). A difference
        the rules do not make is left to the units' runs, as before."""
        if not self._rules:
            return
        ruled = self._parts(at)
        plain = self._parts(at, rules=NO_RULES)
        for branch, kept in list(self._periods.items()):
            part, bare = ruled.get(branch), plain.get(branch)
            if (part is None or bare is None or not part.beneath
                    or part.code is kept.code or bare.code is part.code):
                continue
            by = _rule_moved(branch, kept.code, part.code, plain, ruled)
            rule = _deciding_rule(self._rules, by) if by else None
            if rule is None:
                continue
            self._periods[branch] = Period(
                part.code, Beginning(at, was=kept.code, cause=CAUSE_RULE), by=by,
                rule=rule.name)

    def _seed_periods(self) -> dict[str, Period]:
        """The period of what each branch shows on the first start that keeps one,
        from the log it restores (ADR-0132): the rows replayed through the roll-up
        (:func:`_replayed`) say where a branch's period began — the change into what
        it rolls up to now — and where they say nothing of it, it is a bound at the
        log's oldest row. A log with no rows bounds nothing, and the first comparison
        takes each branch's bound."""
        events = list(self._events)
        if not events:
            return {}
        current = self._parts(instants.now())
        replayed = _replayed(events, self._restored_shown, self._restored_reading,
                             self._restored_published, self._beginnings,
                             self._dependencies, rules=self._rules,
                             accepted=frozenset(self._acknowledged))
        oldest = events[0].timestamp
        seeded: dict[str, Period] = {}
        for path, part in current.items():
            if not part.beneath:
                continue
            found = replayed.get(path)
            if found is not None and found.code is part.code:
                seeded[path] = found
            elif part.code is not StatusCode.UNDEFINED:
                seeded[path] = Period(part.code, Beginning(oldest, before=True))
        return seeded

    # --- internals; call only while holding the lock ---

    def _own(self, node: Status, ran_out: _RanOut | None = None, *,
             ruled: bool = True, accepted: bool = True, line_pins: bool = True,
             node_pin: bool = True) -> StatusCode:
        """What the node shows: its **own** status, by the one transform the
        snapshot applies to it (:func:`_own_code`, ADR-0032 rule 3) — the reading,
        the node's pin, its lines' pins, the configured rules on its lines
        (ADR-0137) and the acknowledgments on its lines (ADR-0142).

        ``ran_out`` are pins to count as still in force: the ones a restart found
        expired, which is how a node's first reading tells whether their end is
        what changed it (ADR-0107 decision 5), and the lines' acknowledgments a
        reading has just ended. ``ruled``, ``accepted`` and ``line_pins`` false leave
        the configured rules, the lines' acknowledgments or the lines' pins out,
        which is how a reading the node did not show is told to be one of theirs
        (:meth:`_hiding_rule`); ``node_pin`` false leaves the node's own pin out,
        which is what its own acknowledgment reads (:meth:`_ended_by`).
        """
        held = ran_out or _RanOut()
        pins = self._entry_maintenance if line_pins else {}
        acknowledged = self._entry_acknowledged if accepted else {}
        lines = [((node.path, entry.slug) in pins
                  or (line_pins and entry.slug in held.lines), entry.code)
                 for entry in node.reason_entries]
        tables: tuple[Table | None, ...] = ()
        if node.members:
            if ruled:
                tables, _marks = _lines_ruled(
                    self._rules.on_lines(node.path),
                    [(entry.slug, quiet, entry.code) for entry, (quiet, _code)
                     in zip(node.reason_entries, lines, strict=True)], node.code)
            if accepted and (acknowledged or held.accepted):
                tables = _accepted_tables(
                    tables, [(node.path, entry.slug) in acknowledged
                             or entry.slug in held.accepted
                             for entry in node.reason_entries])
        return _own_code(node.code, lines, node.members,
                         (node.maintenance and node_pin) or held.node, tables)

    def _last_shown(self) -> dict[str, LastShown]:
        """What every node shows and what its check last reported, as the kept file
        says it beside the log (ADR-0110 decision 2). For a node a check has written
        in this process that is its own status, by the one derivation the snapshot
        and the log read (:meth:`_own`), and its reading; for one not written yet,
        what was restored. With them, when the node's period began (decision 5). A
        node that shows nothing and whose check reported nothing has no entry —
        unless the tree saw it begin to show nothing, which is a period like any
        other — so a node's entry changes only where a row is written.

        **A branch's entry keeps the period of what it shows** under ``period``
        (ADR-0132 decision 1): the root's and a container's too, which have an entry
        for it alone, their two codes ``UNDEFINED``. It changes wherever the period
        does, a reading gone stale among them, which writes no row.

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
        for path, period in self._periods.items():
            entry = kept.get(path)
            kept[path] = (LastShown(nothing, nothing, period=period)
                          if entry is None else replace(entry, period=period))
        return {path: entry for path, entry in kept.items()
                if entry.shows is not nothing or entry.reported is not nothing
                or entry.began is not None or entry.period is not None}

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
            self._periods.pop(path, None)

    def _log(self, event: Event) -> None:
        """Append ``event`` to the log, and keep the beginning of the period it
        begins (ADR-0110 decision 5). A row that changes what its node shows begins
        one: at its instant, from what the node showed before, by its cause. An
        edit of a pin and the end of a wait show what the node showed already, and
        a row that a rule hid from the display is the reading's and not the node's:
        none of them begins a period (ADR-0099 decision 6, ADR-0119 decision 1)."""
        self._events.append(event)
        if self._writing is not None:
            self._writing.rows.append(event)
        if event.new is not event.old and event.shown:
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
            if not event.shown:
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
                        reported: StatusCode, ran_out: _RanOut | None,
                        ended: Sequence[_Ended] = ()) -> bool:
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
        always was, and now also where a line's pin hides it. Only a pin can, or a
        configured rule on the node's lines (ADR-0137) — a node's own status is its
        reading unless one is in force (:func:`_own_code`) — and the row names
        which, and says that its node did not show it. A floor on the lines holds
        nothing back: where it raised what the node shows to at least the reading,
        the row carries no mark, kept for what the check said — a replay reads it,
        a shield on a dependency among others — and listed nowhere (decision 11).
        One run writes both rows where it changes what the node shows and,
        differently, what its check reports.

        **What the reading ended of what a person accepted** (``ended``, ADR-0142)
        is a row each, saying why: where the end of a line's is what changed what
        the node shows, the row of that change is its end's, and every other end is
        a row of its own that changes nothing more — a node's own acknowledgment
        never changes what its node shows — after the row of what the node shows,
        so that the change of a branch above is the end's.
        """
        shows = self._own(node)
        wrote = moved = False
        pending = list(ended)
        if shows is not shown:
            cause, why = CAUSE_READING, ""
            lines = [item for item in pending if item.slug]
            if ran_out is not None and self._own(node, ran_out) is shown:
                cause = CAUSE_PIN_ENDED if ran_out.node else CAUSE_LINE_PIN_ENDED
            elif lines and self._own(node, _RanOut(accepted=frozenset(
                    item.slug for item in lines))) is shown:
                cause = acknowledgment_cause(lines[0].pin.kind, ENDED, line=True)
                why = lines[0].why
                pending.remove(lines[0])
            self._emit(node, shown, shows, cause=cause,
                       mark=self._withholding_rule(node), ended=why)
            wrote = moved = True
        for item in sorted(pending, key=lambda item: item.slug == ""):
            self._emit(node, shows, shows, cause=acknowledgment_cause(
                item.pin.kind, ENDED, line=bool(item.slug)),
                reason=self._ended_reason(node, item), ended=item.why)
            wrote = True
        if node.code is not reported and (
                not moved or (reported, node.code) != (shown, shows)):
            self._emit(node, reported, node.code, cause=CAUSE_READING,
                       mark=self._hiding_rule(node, reported), shown=False)
            wrote = True
        return wrote

    def _hiding_rule(self, node: Status, reported: StatusCode) -> str:
        """Which rule keeps a reading from what the node shows — the mark of the row
        :meth:`_record_reading` writes for a reading the node did not show, the
        change from ``reported`` to the node's code: a pin, on the node or on a line,
        or a configured rule on its lines (ADR-0137). Where only one kind stands on
        the node it is that one; where both do, the rule where the pins alone would
        show the reading and the node does not, and the pin otherwise — which is
        also where the reading the node did not show was the one before this, and
        nothing hides the one now. A rule holds back only what it lowered: where a
        floor raised what the node shows to at least both ends of the change, the
        row is no rule's (:func:`_held_below`)."""
        if node.maintenance or not node.members:
            return MAINTENANCE_RULE
        pins, acknowledged = self._entry_maintenance, self._entry_acknowledged
        keys = [(node.path, entry.slug) for entry in node.reason_entries]
        pinned = any(key in pins for key in keys)
        accepted = any(key in acknowledged and key not in pins for key in keys)
        ruled = bool(self._rules.on_lines(node.path))
        if not (pinned or accepted or ruled):
            return MAINTENANCE_RULE
        shows = self._own(node)
        lowered = AGGREGATION_RULE if _held_below(shows, reported, node.code) else ""
        if shows is not node.code:
            # The kind without which the node would show its reading hides it: a
            # configured rule, then an acknowledgment (ADR-0142), the pins otherwise.
            if ruled and self._own(node, ruled=False) is node.code:
                return lowered
            if accepted and self._own(node, accepted=False) is node.code:
                return SEEN_RULE
        if pinned:
            return MAINTENANCE_RULE
        if accepted:
            return SEEN_RULE
        return lowered

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
        when = self._instant()
        for node, shown in showing:
            shows = self._own(node)
            if shows is not shown:
                self._emit(node, shown, shows, cause=cause(node),
                           reason=None if reason is None else reason(node),
                           when=when)

    def _emit(self, node: Status, old: StatusCode, new: StatusCode, *,
              cause: str, mark: str = "",
              reason: tuple[str, ...] | None = None,
              when: datetime | None = None, shown: bool = True,
              ended: str = "") -> None:
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
            timestamp=stamp, suppressed_by=mark, cause=cause, reported=reported,
            shown=shown, ended=ended))
        if node.timestamp is None:
            # Only a pin writes about a node no check has written yet, and a pin's
            # row is what the node shows.
            self._restored_shown[node.path] = new
        if cause != CAUSE_READING and not (cause in ACKNOWLEDGMENT_CAUSES
                                           and new is old):
            # An acknowledgment's row that changes nothing the node shows publishes
            # nothing either: what a wait holds back, it still holds (ADR-0142).
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
        if self._shields(self._instant()).get(node.path) is not None:
            return DEPENDENCY_RULE
        state = self._damping.get(node.path)
        if state is not None and state.pending is not None:
            return DAMPING_RULE
        return ""

    def _apply_maintenance(self, path: str, entry: Pin, *,
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
                          reason=(entry.note,) if entry.note else (),
                          when=when or self._instant())
        if previous is None and when is None and not suspended:
            self._date_pin(key, entry, old, prior)

    def _date_pin(self, path: str, entry: Pin, shown: StatusCode,
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
                              when=self._instant())
            return existed
        if not node.maintenance:
            return existed
        node.maintenance = False
        self._emit(node, StatusCode.MAINTENANCE, self._own(node),
                   cause=CAUSE_PIN_ENDED, when=self._instant())
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
                 when: datetime, ended: str = "") -> None:
        """Record a pin's event at ``path``, dated ``when`` — the act's instant:
        through the node where the tree holds one (:meth:`_emit`), and otherwise as
        a row of the path alone, which moves what is kept of it as an unwritten
        node's row does."""
        if node is not None:
            self._emit(node, old, new, cause=cause, reason=reason, when=when,
                       ended=ended)
            return
        self._log(Event(
            path=path, name=leaf_name(path), old=old, new=new, reason=reason,
            timestamp=when, cause=cause,
            reported=self._restored_reading.get(path, StatusCode.UNDEFINED),
            ended=ended))
        self._restored_shown[path] = new

    def _persist(self) -> None:
        if self._pin_store is not None:
            self._pin_store.save(self._maintenance, self._entry_maintenance,
                                 self._acknowledged, self._entry_acknowledged)

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
        """``node``'s subtree, as the snapshot reads it. Where a configured rule
        counts the children of the node above it (ADR-0137), what that node counts
        of this one turns on its siblings, so it is taken out of the snapshot of the
        node above: ``contribution`` says the same wherever the node is read, its
        own page and the API's subtree among them (ADR-0123)."""
        if node is not self._root and self._rules.counting_children(
                parent_path(node.path)) is not None:
            above = self._find_node(parent_path(node.path))
            if above is not None:
                for child in self._snapshot_of(above, now).children:
                    if child.path == node.path:
                        return child
        return self._snapshot_of(node, now)

    def _snapshot_of(self, node: Status, now: datetime) -> StatusSnapshot:
        snapshot, _mounts, _mount_stamp, _mount_run = (
            self._snapshot_subtree(node, now, self._change_counts(now),
                                   self._shields(now), self._tags_above(node)))
        return snapshot

    def _tags_above(self, node: Status) -> frozenset[str]:
        """Every tag written for a node above ``node`` (ADR-0139 decision 2), which
        it and every node beneath it carry: what the snapshot of a subtree starts
        from, so that a node's tags are the same wherever it is read."""
        carried: set[str] = set()
        above = self._root
        for segment in split_path(node.path)[:-1]:
            carried.update(self._own_tags(above))
            child = _child_by_name(above, segment)
            if child is None:
                break
            above = child
        else:
            if node is not self._root:
                carried.update(self._own_tags(above))
        return frozenset(carried)

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
        def seen(path: str) -> tuple[StatusCode, bool] | None:
            node = self._find_node(path)
            if node is None:
                return None
            return node.code, _is_stale(node, _age_seconds(node.timestamp, now))

        return _shields_over(self._dependencies, seen)

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
                          changes: dict[str, int], shields: dict[str, str],
                          above: frozenset[str] = frozenset()
                          ) -> tuple[StatusSnapshot, int, datetime | None,
                                     RunFacts | None]:
        """``node``'s snapshot, plus the values its parent needs to resolve its
        own observation time (ADR-0027) and run facts (ADR-0044): how many
        **checks** this subtree holds and, when that count is exactly one, the
        sole mount's own stamp and its check's last-run facts. ``above`` is every
        tag written for a node above it, which it carries with its own and hands
        down (ADR-0139 decision 2).

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
        own_tags = self._own_tags(node)
        carried = above.union(own_tags) if own_tags else above
        results = tuple(
            self._snapshot_subtree(child, now, changes, shields, carried)
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
        # A node a **unit** answers for carries that unit's own facts (ADR-0130
        # decision 5), whether it is the mount or stands beneath it — and so does
        # a container between a unit's node and the mount, with the earliest slot
        # armed beneath it: the engine sets the facts on exactly those nodes and
        # on no other. Never a shared mount, whose facts no one check can claim
        # (ADR-0044); the unwritten ancestors above a sole mount inherit as before.
        own_run = self._run_facts.get(node.path)
        if own_run is not None and not shared:
            mount_run = own_run
        # Own stamp when a check has written this node; otherwise the sole mount's,
        # if the subtree holds exactly one. Staleness and `age_seconds` deliberately
        # keep reading the **own** stamp — an inherited time is a display value, not
        # an observation of this node (ADR-0005 stays untouched).
        age = _age_seconds(node.timestamp, now)
        stale_self = _is_stale(node, age)
        timestamp = node.timestamp if node.timestamp is not None else mount_stamp
        # The reasons, joined with whatever is pinned on them (ADR-0036 decision 5)
        # and whatever a person accepted of them (ADR-0142). A pin whose slug this
        # run did not report simply does not appear — it is suspended, not deleted
        # (decision 6, ADR-0032 rule 7) — and an acknowledgment is suspended the same
        # way while the node's lines are no members.
        pins = self._entry_maintenance
        acknowledged = self._entry_acknowledged
        lines = tuple(
            ReasonLine(entry.slug, entry.text,
                       pins.get((node.path, entry.slug)) if node.members else None,
                       code=entry.code, running=entry.running,
                       subject=entry.subject, data=entry.data,
                       refused=entry.refused, form=entry.form,
                       grading=entry.grading,
                       acknowledgment=(acknowledged.get((node.path, entry.slug))
                                       if node.members else None),
                       occurrence=entry.occurrence)
            for entry in node.reason_entries)
        # The configured rules on the node's lines (ADR-0137): each line counts as
        # the rule that decides it makes it, and keeps its true color under its mark
        # — but a line a person accepted, which counts as they said, and carries
        # their mark alone (ADR-0142).
        tables: tuple[Table | None, ...] = ()
        if node.members and lines:
            tables, marks = _lines_ruled(
                self._rules.on_lines(node.path),
                [(line.slug, line.quiet, line.code) for line in lines], node.code)
            if marks:
                lines = tuple(line if mark is None or line.accepted
                              else replace(line, rule=mark)
                              for line, mark in zip(lines, marks, strict=True))
            if any(line.accepted for line in lines):
                tables = _accepted_tables(tables, [line.accepted for line in lines])
        # Own status is now a **derived** value: the entries are virtual children,
        # and a node whose members are all pinned has nothing left reporting.
        own = _own_code(node.code, [(line.quiet, line.code) for line in lines],
                        node.members, node.maintenance, tables)
        stale = stale_self or any(child.stale for child in children)
        # A configured rule counting the node's children (ADR-0137) changes what the
        # node counts of each, and says so on the child it changes.
        children_rule: RuleAt | None = None
        counting = self._rules.counting_children(node.path) if children else None
        if counting is not None:
            counted_now, failing, named = _counting(
                counting, [(child.name, child.code, child.contribution, child.stale)
                           for child in children], root=node.path == "/")
            restated: list[StatusSnapshot] = []
            for child, after, picked in zip(children, counted_now, named,
                                            strict=True):
                if not picked:
                    restated.append(child)
                    continue
                restated.append(replace(
                    child, contribution=after, parent_rule=_ruled_at(
                        counting, child.code, child.contribution, after, failing)))
            children = tuple(restated)
            children_rule = RuleAt(counting, failing=failing, changes=any(
                _acts(child.parent_rule) for child in children))
        # What the node counts for itself, what it rolls up to, what its parent
        # counts of it and the hold a damping counter has on it: the one derivation
        # the bookkeeping reads too (`_derive`), so what a branch's period is of is
        # what its snapshot says (ADR-0132 decision 2).
        counted = tuple(child.counted for child in children)
        shielded_by = shields.get(node.path)
        own_acknowledgment = self._acknowledged.get(node.path)
        _rollup, code, contribution, damping = _derive(
            node.code, own, stale_self, node.maintenance, counted, shielded_by,
            self._damping.get(node.path), node.escalate_after,
            accepted=own_acknowledgment is not None)
        # The pin that withholds the node is named beside its kind, where its own
        # pin is what does (ADR-0141 decision 3): not where every line of it is
        # pinned, nor where its check reports maintenance itself. An acknowledgment
        # that decided is named the same way (ADR-0142).
        own_pin = self._maintenance.get(node.path)
        if (own_pin is not None and contribution is not None
                and contribution.by == MAINTENANCE_RULE):
            contribution = replace(contribution, rule=own_pin.id)
        elif (own_acknowledgment is not None and contribution is not None
                and contribution.by == SEEN_RULE):
            contribution = replace(contribution, rule=own_acknowledgment.id)
        # The configured rule on what the node passes up, last at its boundary: on
        # what damping publishes, and never beneath what a stale reading counts.
        rule: RuleAt | None = None
        boundary = self._rules.boundary(node.path)
        if boundary is not None:
            prior = contribution
            contribution = _through(boundary.table, code, prior, stale,
                                    boundary.name)
            rule = _ruled_at(boundary, code, prior, contribution)
        snapshot = StatusSnapshot(
            path=node.path, name=node.name, own_code=own, code=code,
            reported_code=node.code,
            reason=tuple(node.reason), timestamp=timestamp,
            description=node.description, frequency_seconds=node.frequency_seconds,
            config="" if shared else node.config,
            report="" if shared else node.report,
            about=node.about, title=node.title, order=node.order or 0,
            has_handbook=bool(node.handbook),
            details=_own_details(node, () if shared else node.type_details),
            tags=self._ordered_tags(carried),
            # Carried as the tri-state it is: `order` collapses to 0 because the
            # sort needs a number, while nothing downstream needs a boolean here —
            # and flattening `None` to `False` would throw away the one difference
            # the fill rule turns on (ADR-0063).
            show_when_quiet=node.show_when_quiet,
            maintenance=node.maintenance,
            maintenance_entry=own_pin, acknowledgment=own_acknowledgment,
            stale=stale,
            own_stale=stale_self,
            stale_after_seconds=node_stale_after(node),
            age_seconds=age, children=children,
            reasons=lines, members=node.members, run=mount_run,
            contribution=contribution, damping=damping,
            rule=rule, children_rule=children_rule,
            # The measurement, withheld on a shared mount for the same reason the
            # text and the run facts are: two checks write that node and the last
            # writer cannot be believed there (ADR-0044 decision 1).
            subject="" if shared else node.subject,
            record=None if shared else node.record,
            shielded_by=shielded_by,
            changes=changes.get(node.path, 0),
            # The period of what it shows only where it is of what it shows
            # (ADR-0132 decision 3), decided here once for every surface.
            period=(kept if (kept := self._periods.get(node.path)) is not None
                    and kept.code is code else None),
            # and the period of its own status only where it has one to name
            own_period=(None if own is StatusCode.UNDEFINED and children
                        else self._beginnings.get(node.path)))
        return snapshot, mounts, mount_stamp, mount_run


def _given_details(node: Status) -> Details:
    """What the deployment gives ``node`` (ADR-0133 decision 6): under its name in its
    check's ``subnodes:`` block, and by its path — ``nodes.yaml`` over the check's own
    file — which wins key by key. It holds for every node beneath."""
    return node_details.merged(node.named_details, node.declared_details)


def _own_details(node: Status, by_type: Details) -> tuple[Detail, ...]:
    """``node``'s own details as its snapshot holds them: ``by_type``, what its type
    gave it, first, then what the deployment gives it (:func:`_given_details`)."""
    given = _given_details(node)
    if not by_type and not given:
        return ()
    return node_details.own(by_type, given)


def _own_code(reported: StatusCode,
              lines: Sequence[tuple[bool, StatusCode | None]],
              members: bool, pinned: bool,
              tables: Sequence[Table | None] = ()) -> StatusCode:
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
    every line turns it ``MAINTENANCE``, exactly as with real children — and as
    with real children, that cancels nothing beneath the node, which is the
    roll-up's to say (:func:`_cancels_beneath`, ADR-0124). Two kinds
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

    ``tables`` are the configured rules' (ADR-0137), one beside each line: the
    table that decides how that line counts here now, or ``None``. A line counts as
    its table makes it — healed, capped, floored, or nothing, as a line that has not
    reported counts nothing — and keeps its true color on every surface: a rule on
    lines changes what their node shows, as a line's pin does, and what the line
    shows never. A pinned line is the pin's.
    """
    if pinned:
        return StatusCode.MAINTENANCE
    if not members or not lines:
        return reported
    counted: list[StatusCode] = []
    silenced = False
    for index, (quiet, declared) in enumerate(lines):
        if quiet:
            silenced = True
            continue
        code = declared if declared is not None else reported
        if code is StatusCode.MAINTENANCE:
            silenced = True
            continue
        table = tables[index] if index < len(tables) else None
        if table is not None:
            mapped = table.counts(code)
            if mapped is None:
                continue
            code = mapped
        if code is StatusCode.UNDEFINED:
            continue
        counted.append(code)
    if counted:
        return worst_of(counted)
    return StatusCode.MAINTENANCE if silenced else StatusCode.UNDEFINED


def _counts_for_itself(reported: StatusCode, own: StatusCode,
                       stale: bool) -> StatusCode:
    """What a node counts **for itself** in what it rolls up to (ADR-0039, with the
    one transform that is applied on top): its ``own`` status — or, where its own
    reading is ``stale``, what its check ``reported``, degraded to at least
    :data:`STALE_DEGRADE`.

    Staleness judges the **raw** reading and is never suppressed — a check that
    stopped running escalates whichever policy is holding its result back (ADR-0032
    rule 6, ADR-0036 decision 9), so what a stale node counts is its degraded raw
    code, not its quieted own status.

    The roll-up comes here for every node, and the snapshot comes here again when
    a surface asks whose a status is (:attr:`StatusSnapshot.own_counted`): one
    expression, so the two cannot answer differently.
    """
    return worst_of((reported, STALE_DEGRADE)) if stale else own


def _cancels_beneath(counts_for_itself: StatusCode, reported: StatusCode,
                     pinned: bool) -> bool:
    """Whether what a node counts for itself **cancels what is beneath it**
    (ADR-0039 rule 3): ``MAINTENANCE`` by a pin on the node, or by its check's word
    for it — a ``reported`` ``MAINTENANCE``, the uncoded lines that carry it
    included.

    Not ``MAINTENANCE`` because every line of its own is pinned. The lines are the
    node's children too (ADR-0036 decision 7), and silenced they count nothing and
    cancel nothing, as a child in maintenance cancels nothing but itself (ADR-0124
    decision 1). A line's pin is set on a leaf's page, *for this line only*; the
    node it stands on may have nodes beneath it by the time it applies.

    The roll-up asks this for every node (:func:`_rolls_up`), and the snapshot asks
    it again of the fields it was handed (:attr:`StatusSnapshot.counts_beneath`,
    :attr:`StatusSnapshot.lines_silenced`): one expression, so a surface cannot say
    that a node counts what is beneath it where the roll-up did not.
    """
    return (counts_for_itself is StatusCode.MAINTENANCE
            and (pinned or reported is StatusCode.MAINTENANCE))


def _rolls_up(counts_for_itself: StatusCode, children: Sequence[StatusCode],
              cancels: bool) -> StatusCode:
    """What a node rolls up to (ADR-0039): what it counts for itself and what each
    child contributes, by :func:`~little_sister.status.effective_code` — with the
    one case that function cannot tell from a pin.

    A node whose lines are all silenced counts ``MAINTENANCE`` for itself and
    cancels nothing (``cancels`` false, :func:`_cancels_beneath`): its own part is
    skipped as a silenced child is, the nodes beneath it count, and it reads
    ``MAINTENANCE`` whole only where nothing beneath it counts either — rule 5,
    which is also what a leaf with every line pinned reads (ADR-0124 decision 1).
    """
    if counts_for_itself is StatusCode.MAINTENANCE and not cancels:
        return effective_code(StatusCode.UNDEFINED,
                              (*children, StatusCode.MAINTENANCE))
    return effective_code(counts_for_itself, children)


def _counted_code(code: StatusCode,
                  contribution: Contribution | None) -> StatusCode:
    """The code a node's parent accumulates, given what the node rolls up to and what
    a rule made of it — :attr:`StatusSnapshot.counted`, which says why, and the
    bookkeeping's reading of the same (ADR-0132)."""
    if contribution is None:
        return code
    if contribution.code is not None:
        return contribution.code
    if code in (StatusCode.MAINTENANCE, StatusCode.UNDEFINED):
        return code
    return StatusCode.UNDEFINED


def _mapped(table: Table, code: StatusCode, stale: bool) -> StatusCode | None:
    """What a part reporting ``code`` counts as under ``table`` (ADR-0137) —
    ``None`` where it counts nothing — and never less than a warning where a
    reading at or beneath it is past its tolerance and the part fails: a check that
    stopped running escalates whatever rule holds its result back (ADR-0032 rule 6),
    so healing or leaving out a part over a dead check still escalates."""
    counted = table.counts(code)
    if stale and code in (StatusCode.WARN, StatusCode.ERROR) and (
            counted is None or counted is StatusCode.OK):
        return StatusCode.WARN
    return counted


def _through(table: Table, code: StatusCode, prior: Contribution | None,
             stale: bool, name: str) -> Contribution | None:
    """What a part's parent counts of it once a configured rule's table has had its
    say (ADR-0137), given what the part rolls up to and what the rule before it made
    of that — the table maps what damping publishes, and leaves alone what a pin, a
    shield or a part not reported withholds.

    ``by`` names the first rule whose change still reaches the parent (decision 5):
    a rule before it keeps the name where the parent would count something else
    without it, and the table takes it where it would not — an ERROR held at WARN
    counts OK under ``{WARN: OK}`` by damping, since without the hold it would count
    ERROR, and WARN under ``{ERROR: WARN}`` by the table, which would count WARN
    without the hold."""
    if prior is not None and prior.code is None:
        return prior
    after = _mapped(table, _counted_code(code, prior), stale)
    if after is code:
        return None
    if prior is None or _mapped(table, code, stale) is after:
        return Contribution(after, AGGREGATION_RULE, name)
    return Contribution(after, prior.by, prior.rule)


def _ruled_at(rule: AggregationRule, code: StatusCode, prior: Contribution | None,
              after: Contribution | None, failing: int = 0) -> RuleAt:
    """Where a rule on a node, or one counting its parent's children, stands on it:
    what the node passes up there, what its parent counts of it — ``None`` for
    nothing — and whether that is a change."""
    reads = _counted_code(code, prior)
    counts = (None if after is not None and after.code is None and reads in RANKED
              else _counted_code(code, after))
    return RuleAt(rule, reads, counts, failing, counts is not reads)


def _counting(rule: AggregationRule,
              children: Sequence[tuple[str, StatusCode, Contribution | None, bool]],
              *, root: bool
              ) -> tuple[list[Contribution | None], int, list[bool]]:
    """Each child's contribution once the rule counting a node's children has had
    its say (ADR-0137), with how many of the children it names report a status its
    table names: the table applies while fewer than its count do, and from there on
    every child counts as it is. ``children`` are each child's name, what it rolls
    up to, what its parent counted of it before the rule and whether a reading at
    or beneath it is past its tolerance. The instance's own branch is no child of
    the root's that any rule counts. With them, which of the children the rule
    names."""
    named = [rule.names_child(name) and not (root and name == _OWN_BRANCH)
             for name, _code, _prior, _stale in children]
    failing = sum(1 for (_name, code, prior, _stale), picked in zip(children, named,
                                                                    strict=True)
                  if picked and rule.table.names(_counted_code(code, prior)))
    if rule.count is not None and failing >= rule.count:
        return [prior for _name, _code, prior, _stale in children], failing, named
    return [_through(rule.table, code, prior, stale, rule.name) if picked
            else prior
            for (_name, code, prior, stale), picked
            in zip(children, named, strict=True)], failing, named


#: The statuses an acknowledgment accepts (ADR-0142): a part reading anything else
#: has nothing for one to stand on.
_FAILURES = frozenset({StatusCode.WARN, StatusCode.ERROR})


def _ending(pin: Pin, code: StatusCode, occurrence: str | None) -> str:
    """Why a reading of ``code`` ends the acknowledgment ``pin`` (ADR-0142), one of
    the ``ENDED_`` words — or empty where it holds: through an improvement, a failure
    no worse than the one it was set at, and the same occurrence. A part that reads no
    status is no longer reported; one that reads ``OK``, or that its check says is in
    maintenance, recovered; a line whose ``occurrence`` is not the one it was bound to
    failed anew; and one worse than it was set at got worse. A part bound to its
    failing stretch, a node's own among them, has no occurrence to compare."""
    if code is StatusCode.UNDEFINED:
        return ENDED_GONE
    if code not in _FAILURES:
        return ENDED_RECOVERY
    if occurrence is not None and pin.occurrence and occurrence != pin.occurrence:
        return ENDED_OCCURRENCE
    if pin.status is not None and escalates(pin.status, code):
        return ENDED_WORSENING
    return ""


def _accepted_tables(tables: Sequence[Table | None],
                     accepted: Sequence[bool]) -> tuple[Table | None, ...]:
    """The table each of a node's lines counts by in its own status once a person's
    acknowledgments have had their say (ADR-0142): :data:`ACCEPTED` on a line one
    stands on, over whatever a configured rule makes of it, and the configured
    rule's on every other line. A pinned line is the pin's whatever it holds."""
    return tuple(ACCEPTED if flag else (tables[index] if index < len(tables) else None)
                 for index, flag in enumerate(accepted))


def _lines_ruled(rules: Sequence[AggregationRule],
                 lines: Sequence[tuple[str, bool, StatusCode | None]],
                 reported: StatusCode
                 ) -> tuple[tuple[Table | None, ...], tuple[RuleAt | None, ...]]:
    """The table that decides how each of a node's lines counts in its own status
    now, and where each rule stands on its line (ADR-0137): ``rules`` are the rules
    on lines that pick the node, in order, and a line is decided by the first whose
    ``lines:`` names it. ``lines`` are each line's address, whether it is pinned and
    the code it declared, the node's reported code standing in where it declared
    none. A rule with a count counts the lines it decides that report a status its
    table names, and from its count on none of them is changed. A pinned line is the
    pin's: no rule's mark stands on it, and it counts toward no rule's count."""
    if not rules:
        return (), ()
    deciding = [None if quiet else next(
        (rule for rule in rules if rule.names_line(slug_)), None)
        for slug_, quiet, _declared in lines]
    failing: dict[str, int] = {}
    for rule, (_slug, _quiet, declared) in zip(deciding, lines, strict=True):
        if rule is not None and rule.table.names(
                declared if declared is not None else reported):
            failing[rule.key] = failing.get(rule.key, 0) + 1
    tables: list[Table | None] = []
    marks: list[RuleAt | None] = []
    for rule, (_slug, _quiet, declared) in zip(deciding, lines, strict=True):
        if rule is None:
            tables.append(None)
            marks.append(None)
            continue
        code = declared if declared is not None else reported
        count = failing.get(rule.key, 0)
        applies = rule.count is None or count < rule.count
        counts = rule.table.counts(code) if applies else code
        tables.append(rule.table if applies else None)
        marks.append(RuleAt(rule, code, counts, count, counts is not code))
    return tuple(tables), tuple(marks)


def _derive(reported: StatusCode, own: StatusCode, stale: bool, pinned: bool,
            counted: Sequence[StatusCode], shielded_by: str | None,
            damped: _Damped | None, escalate_after: int, *, accepted: bool = False
            ) -> tuple[StatusCode, StatusCode, Contribution | None, Damping | None]:
    """What one node rolls up to, from what it holds and what its children
    contribute: what it counts for itself (:func:`_counts_for_itself`), what it rolls
    up to (:func:`_rolls_up`, with what that cancels beneath it), what its parent
    counts of it and the rule that made that something else (ADR-0032 rule 5), and
    the hold a damping counter has on it. The one derivation the snapshot and the
    bookkeeping read, so what a branch's period is of is what its snapshot says
    (ADR-0132 decision 2).

    **One rule names each node, and the order is the order of specificity.** An
    admin's pin is the most specific thing anybody said about a node, so it is named
    first even when something else would also have withheld it. A node that has
    never reported has nothing to believe or disbelieve, so no shield and no counter
    can be about it. Only then the two rules that are about a reading: the shield,
    which withholds it — the node keeps its own state, but *we could not get there*
    is not a reading anybody should accumulate (ADR-0039 has no code for it, and
    ADR-0032 decision 4 closed the vocabulary against inventing one) — and the
    counter, which delays it. Staleness bypasses the counter (ADR-0032 rule 6): a
    check that stopped running produces no new readings, so the count would never
    advance and the hold would never end; the degraded raw code goes up instead.

    **A person's acknowledgment on the node** (``accepted``, ADR-0142) comes last,
    and changes what its parent counts of its own part alone: ``OK`` — at least a
    warning where its reading went stale — beside what its children contribute, so
    that a failure beneath it still climbs. It names itself over the counter it
    outranks, and never over a rule that withholds the node.
    """
    rollup = _counts_for_itself(reported, own, stale)
    cancels = _cancels_beneath(rollup, reported, pinned)
    code = _rolls_up(rollup, counted, cancels)
    contribution: Contribution | None = None
    damping: Damping | None = None
    if code is StatusCode.MAINTENANCE:
        contribution = Contribution(None, MAINTENANCE_RULE)
    elif code is StatusCode.UNDEFINED:
        contribution = Contribution(None, UNDEFINED_RULE)
    elif shielded_by is not None:
        contribution = Contribution(None, DEPENDENCY_RULE)
    else:
        if damped is not None and damped.pending is not None and not stale:
            damping = Damping(pending=damped.pending, seen=damped.seen,
                              needed=escalate_after)
            publishes = effective_code(damped.published, counted)
            if publishes is not code:
                contribution = Contribution(publishes, DAMPING_RULE)
        if accepted:
            itself = _mapped(ACCEPTED, rollup, stale)
            seen = _rolls_up(rollup if itself is None else itself, counted, cancels)
            if seen is not code:
                contribution = Contribution(seen, SEEN_RULE)
    return rollup, code, contribution, damping


def _shields_over(dependencies: Mapping[str, str],
                  seen: Callable[[str], tuple[StatusCode, bool] | None]
                  ) -> dict[str, str]:
    """Which nodes are shielded, and by which dependency (ADR-0084), given what is
    seen of each node — what its check reported, and whether that reading is stale —
    or ``None`` for a node there is none of. The snapshot's view
    (:meth:`StatusTree._shields`, which says the rule) and the bookkeeping's, which
    counts a node no check has written yet at its kept entry (ADR-0132 decision 3),
    read it through this one function."""
    resolved: dict[str, str | None] = {}
    shields: dict[str, str] = {}
    for path in dependencies:
        on = _shield_for(path, dependencies, seen, resolved)
        if on is not None:
            shields[path] = on
    return shields


def _shield_for(path: str, dependencies: Mapping[str, str],
                seen: Callable[[str], tuple[StatusCode, bool] | None],
                resolved: dict[str, str | None]) -> str | None:
    """The dependency that shields the node at ``path``, or ``None``
    (:func:`_shields_over`): an ``ERROR`` it is reached through, fresh, beside a
    reading of its own that is fresh too, and no shield on the dependency itself.
    ``resolved`` holds what is answered already. A function of the module that takes
    what it reads, and no closure over itself, which would hold all it sees for the
    cycle collector (ADR-0132's consequence on cost)."""
    if path in resolved:
        return resolved[path]
    # Cycles are refused at startup; this guard is what makes the recursion safe to
    # read rather than safe by argument alone.
    resolved[path] = None
    on = dependencies.get(path)
    if on is None:
        return None
    node, gate = seen(path), seen(on)
    if node is None or gate is None:
        return None
    if gate[0] is not StatusCode.ERROR or gate[1] or node[1]:
        return None
    if _shield_for(on, dependencies, seen, resolved) is not None:
        return None
    resolved[path] = on
    return on


#: How far past the moment a reading's tolerance ran out the bookkeeping weighs it:
#: a reading is stale once its age is *past* its tolerance (:func:`_is_stale`), and
#: the change is dated at the moment itself (ADR-0132 decision 2).
_JUST_AFTER = timedelta(microseconds=1)


def _evaluate(beneath: Mapping[str, Sequence[str]],
              keys: Mapping[str, tuple[int, str]], given: Mapping[str, _Inputs],
              dependencies: Mapping[str, str],
              rules: RuleSet = NO_RULES) -> dict[str, _Part]:
    """What every node of a tree is, for the bookkeeping (ADR-0132): ``beneath`` names
    each node's children, ``keys`` sorts siblings as the tree draws them (ADR-0055),
    and ``given`` holds what each node holds itself — a container on the way to
    others holding nothing. Read by the snapshot's own derivation
    (:func:`_derive`), with the configured ``rules`` on a node's children and on what
    it passes up as the snapshot applies them (ADR-0137); a rule on lines is in what
    each node holds, its own status.

    **A loop over a stack, and no closure that calls itself**: a closure that
    reaches itself is a reference cycle, and it would hold every part it built for
    the cycle collector after each roll-up, three a tick (ADR-0132's consequence on
    cost). Each node is taken twice — first to stand its children above it on the
    stack, then, once they are weighed, to weigh it."""
    shields = _shields_over(dependencies, lambda path: (
        (given[path].reported, given[path].stale) if path in given else None))
    parts: dict[str, _Part] = {}
    stack: list[tuple[str, tuple[tuple[int, str], ...],
                      tuple[str, ...] | None]] = [("/", (), None)]
    while stack:
        path, order, children = stack.pop()
        if children is None:
            children = tuple(sorted(beneath.get(path, ()), key=keys.__getitem__))
            stack.append((path, order, children))
            stack.extend((child, (*order, keys[child]), None)
                         for child in reversed(children))
            continue
        held = given.get(path, _NOTHING)
        shield = shields.get(path)
        stale = held.stale or any(parts[child].stale for child in children)
        counting = rules.counting_children(path) if children else None
        if counting is not None:
            counted_now, _failing, _named = _counting(
                counting, [(leaf_name(child), parts[child].code,
                            parts[child].contribution, parts[child].stale)
                           for child in children], root=path == "/")
            for child, after in zip(children, counted_now, strict=True):
                if after is not parts[child].contribution:
                    parts[child] = replace(
                        parts[child], contribution=after,
                        counted=_counted_code(parts[child].code, after))
        own, code, contribution, _damping = _derive(
            held.reported, held.own, held.stale, held.pinned,
            [parts[child].counted for child in children], shield, held.damped,
            held.escalate_after, accepted=held.accepted)
        boundary = rules.boundary(path)
        if boundary is not None:
            contribution = _through(boundary.table, code, contribution, stale,
                                    boundary.name)
        parts[path] = _Part(
            code=code, counted=_counted_code(code, contribution), own=own,
            shield=shield,
            held=(contribution.code if contribution is not None
                  and contribution.by == DAMPING_RULE else None),
            beneath=children, order=order, carried=held.carried,
            carrying=held.carried or any(parts[child].carrying
                                         for child in children),
            contribution=contribution, stale=stale, accepted=held.accepted)
    return parts


def _link(path: str, beneath: dict[str, list[str]],
          keys: dict[str, tuple[int, str]]) -> None:
    """Stand the node at ``path`` in the tree ``beneath`` describes, with every
    container on the way to it that the tree does not hold yet, each holding nothing
    of its own; ``keys`` sorts each as the tree draws it. The root stands in it
    already. A loop up the ancestors, not a closure that calls itself (ADR-0132's
    consequence on cost)."""
    below: str | None = None
    while path not in beneath:
        beneath[path] = [] if below is None else [below]
        keys[path] = (0, _sort_key(leaf_name(path)))
        below, path = path, parent_path(path)
    if below is not None:
        beneath[path].append(below)


def _own_part(part: _Part | None
              ) -> tuple[StatusCode, str | None, StatusCode | None, bool]:
    """What a change moves of a node (ADR-0132 decision 4): what it counts for
    itself, the shield on it, what a wait publishes for it and whether a person has
    accepted its own failure (ADR-0142) — the four a node the tree does not hold has
    none of."""
    if part is None:
        return StatusCode.UNDEFINED, None, None, False
    return part.own, part.shield, part.held, part.accepted


def _scope_of(branch: str, dependencies: Mapping[str, str]) -> list[str]:
    """What the periods of what ``branch`` showed are derived from (ADR-0132 decision
    6): the branch, and every dependency a node at or beneath it is reached through,
    and theirs in turn — a shield there can move it from outside."""
    scope = [branch]
    index = 0
    while index < len(scope):
        top = scope[index]
        index += 1
        for path, on in dependencies.items():
            if _at_or_beneath(path, top) and not any(
                    _at_or_beneath(on, held) for held in scope):
                scope.append(on)
    return scope


def _carry_ended(before: _Part | None, after: _Part | None) -> bool:
    """Whether a node that counted at its kept entry before a change no longer does
    after it — its unit has run in this process (ADR-0132 decision 3)."""
    return before is not None and before.carried and (
        after is None or not after.carried)


def _ancestors(path: str) -> list[str]:
    """The nodes above ``path``, the nearest first and the root last."""
    segments = split_path(path)
    return [join_path(*segments[:length])
            for length in range(len(segments) - 1, -1, -1)]


def _at_or_beneath(path: str, branch: str) -> bool:
    """Whether ``path`` is ``branch`` or stands beneath it, segment by segment."""
    above = split_path(branch)
    return split_path(path)[:len(above)] == above


def _makers(parts: Mapping[str, _Part], branch: str,
            code: StatusCode) -> list[str]:
    """The nodes that make ``branch`` show ``code`` (ADR-0123 decision 3), in the
    order the tree draws them: each counts the code for itself, and every node
    between it and the branch counts it on — the branch first, where it counts the
    code for itself."""
    top = parts.get(branch)
    if top is None:
        return []
    found = [branch] if top.own is code else []
    stack = list(reversed(top.beneath))
    while stack:
        child = stack.pop()
        part = parts[child]
        if part.counted is not code:
            continue
        if part.own is code:
            found.append(child)
        stack.extend(reversed(part.beneath))
    return found


#: How much failure a code says, for which way a branch moved (ADR-0132 decision 4):
#: warn some and error more, and ok, maintenance and undefined none — so a branch
#: from maintenance to error got worse, and one from error to maintenance better.
_FAILURE: Mapping[StatusCode, int] = {StatusCode.WARN: 1, StatusCode.ERROR: 2}


def _by(branch: str, old: StatusCode, new: StatusCode,
        before: Mapping[str, _Part], after: Mapping[str, _Part],
        moved: Sequence[str]) -> str:
    """The node whose change began a branch's new period (ADR-0132 decision 4): the
    first, in the order the tree draws them, of the nodes one change moved at or
    beneath the branch that answers for the period. Where the branch now shows a
    worse failure than it did (:data:`_FAILURE`) — warn or error after ok,
    maintenance or undefined, or error after warn — a node that now counts the new
    code for itself, ADR-0123 decision 3's maker; where it shows less failure than
    before, a node that counted the old code for itself, whose recovery ended it;
    where no moved node is such a one, and where the branch moved between ok,
    maintenance and undefined, the first whose own part moved. A node only a shield
    moved stands for the dependency it is reached through (ADR-0084), which need not
    stand beneath the branch. Empty where nothing at or beneath the branch moved."""
    candidates = [path for path in moved if _at_or_beneath(path, branch)]
    if not candidates:
        return ""

    def named(path: str) -> str:
        was, now = _own_part(before.get(path)), _own_part(after.get(path))
        if (was[0], was[2]) == (now[0], now[2]) and was[1] != now[1]:
            return now[1] or was[1] or path
        return path

    makers: set[str] = set()
    worse = _FAILURE.get(new, 0) - _FAILURE.get(old, 0)
    if worse > 0:
        makers = set(_makers(after, branch, new))
    elif worse < 0:
        makers = set(_makers(before, branch, old))
    for path in candidates:
        if path in makers:
            return named(path)
    return named(candidates[0])


def _cause_in(by: str, rows: Sequence[Event]) -> str:
    """What moved the node ``by`` in one write (ADR-0132 decision 4), as its row
    says it — a reading, a pin set or ended, a line's, a removal, the end of a wait
    — and a reading for a node that moved without a row of its own: read again, and
    fresh where it had gone stale, or a dependency read beside the nodes it
    shields."""
    for row in reversed(rows):
        if row.path == by and row.shown:
            return row.cause
    return CAUSE_READING


def _replayed(events: Sequence[Event], shown: Mapping[str, StatusCode],
              reported: Mapping[str, StatusCode],
              published: Mapping[str, StatusCode],
              began: Mapping[str, Beginning],
              dependencies: Mapping[str, str], *,
              oldest: datetime | None = None, watch: str = "",
              timeline: list[Period] | None = None,
              rules: RuleSet = NO_RULES,
              starts: Mapping[str, datetime] | None = None,
              accepted: frozenset[str] = frozenset()) -> dict[str, Period]:
    """The period of what each branch showed at the end of a log, replayed from its
    rows through the roll-up (ADR-0132): what each node showed — the ``old`` of its
    first row, or its kept entry where the log holds none of it — moved by every row
    as the tree moved it, a pin's, a removal's and the end of a wait's among them,
    the rows of one instant together as one change; and at each change every branch
    above what it moved compared as the bookkeeping compares a write. A branch's
    period at the log's oldest row — ``oldest``, the first of ``events`` unless said
    — is a bound there. Staleness writes no row, and is not replayed.

    ``timeline``, where given, gathers every period the branch ``watch`` went
    through, oldest first: what History lists of a node above others (decision
    6). ``rules`` are the configured rules (ADR-0137 decision 11), each read from
    where it began to count and not before it — ``starts``, by its key, where a
    period the tree keeps says which start brought it, and else the start of the day
    its ``since:`` names, in the configured zone: a row says what its node showed,
    which a rule on its lines decided as it was written, and a rule on a node or its
    children is applied as the roll-up applies it, by the rules that stood at each
    change. Where a rule begins inside the log, the tree is read again there, no row
    moving anything: a branch it moves begins a period there, its cause the rule's
    beginning (:data:`CAUSE_RULE`), by the node whose count it changed, naming it. A
    rule since removed, or whose table was edited, is read as the file has it now,
    since nothing keeps what it was.

    **A person's acknowledgment on a node** (ADR-0142) counts from its set to its
    end, as its rows say them; where the log holds no row of one, whether it stands
    on the node now — ``accepted``, the paths it stands on — says whether it stood
    throughout. One on a line needs nothing: the rows say what its node showed."""
    first: dict[str, Event] = {}
    shown_first: dict[str, Event] = {}
    pin_first: dict[str, Event] = {}
    acknowledged_first: dict[str, Event] = {}
    for event in events:
        first.setdefault(event.path, event)
        if event.shown:
            shown_first.setdefault(event.path, event)
        if event.cause in (CAUSE_PIN_SET, CAUSE_PIN_EDITED, CAUSE_PIN_ENDED):
            pin_first.setdefault(event.path, event)
        if event.cause in _NODE_ACKNOWLEDGMENT_CAUSES:
            acknowledged_first.setdefault(event.path, event)
    nothing = StatusCode.UNDEFINED
    paths = {*shown, *reported, *first}
    shows: dict[str, StatusCode] = {}
    reads: dict[str, StatusCode] = {}
    pins: dict[str, bool] = {}
    accepts: dict[str, bool] = {}
    publishes: dict[str, StatusCode] = {}
    for path in paths:
        row = shown_first.get(path)
        shows[path] = row.old if row is not None else shown.get(path, nothing)
        earliest = first.get(path)
        if earliest is None:
            reads[path] = reported.get(path, shows[path])
        elif earliest.cause in ("", CAUSE_READING):
            reads[path] = earliest.old
        else:
            reads[path] = (shows[path] if earliest.reported is None
                           else earliest.reported)
        pin_row = pin_first.get(path)
        start = began.get(path)
        pins[path] = (pin_row.cause != CAUSE_PIN_SET if pin_row is not None
                      else shows[path] is StatusCode.MAINTENANCE
                      and start is not None
                      and start.cause in (CAUSE_PIN_SET, CAUSE_PIN_EDITED))
        publishes[path] = (shows[path] if path in first
                           else published.get(path, shows[path]))
        said = acknowledged_first.get(path)
        accepts[path] = (not said.cause.endswith(f"-{SET}") if said is not None
                         else path in accepted)

    beneath: dict[str, list[str]] = {"/": []}
    keys: dict[str, tuple[int, str]] = {"/": (0, "")}
    for path in paths:
        _link(path, beneath, keys)

    def evaluate(standing: RuleSet) -> dict[str, _Part]:
        return _evaluate(beneath, keys, {
            path: _Inputs(reads[path], shows[path], pinned=pins[path],
                          damped=(_Damped(publishes[path], shows[path], 1)
                                  if escalates(publishes[path], shows[path])
                                  else None),
                          accepted=accepts[path])
            for path in paths}, dependencies, standing)

    def apply(event: Event) -> None:
        path = event.path
        if not event.shown:
            reads[path] = event.new
            return
        if event.cause == CAUSE_REMOVED:
            shows[path] = reads[path] = publishes[path] = nothing
            return
        shows[path] = event.new
        read = _reported_after(event, reads.get(path))
        if read is not None:
            reads[path] = read
        if event.cause in (CAUSE_PIN_SET, CAUSE_PIN_EDITED):
            pins[path] = True
        elif event.cause == CAUSE_PIN_ENDED:
            pins[path] = False
        elif event.cause in _NODE_ACKNOWLEDGMENT_CAUSES:
            accepts[path] = not event.cause.endswith(f"-{ENDED}")
        elif not event.cause and not event.suppressed_by:
            # A log written before a row said what moved its node: an unmarked row
            # to MAINTENANCE is an admin's pin set, and one from it the pin's end
            # (:func:`_reported_after`).
            if event.new is StatusCode.MAINTENANCE:
                pins[path] = True
            elif event.old is StatusCode.MAINTENANCE:
                pins[path] = False
        if event.suppressed_by != DAMPING_RULE:
            publishes[path] = event.new

    # Where each rule begins to count: the start that brought it, where a period
    # the tree keeps says so, and the start of the day its ``since:`` names else.
    begins = {rule.key: (starts or {}).get(rule.key) or day_begins(rule.since)
              for rule in rules.rules}

    def standing(at: datetime) -> RuleSet:
        return rules.standing(key for key, start in begins.items() if start <= at)

    bound = events[0].timestamp if oldest is None else oldest
    before = evaluate(standing(bound))
    periods: dict[str, Period] = {
        path: Period(part.code, Beginning(bound, before=True))
        for path, part in before.items()
        if part.beneath and part.code is not nothing}
    if timeline is not None and watch in periods:
        timeline.append(periods[watch])
    openings = sorted({start for start in begins.values() if start > bound})

    def begin(start: datetime, prior: Mapping[str, _Part]) -> dict[str, _Part]:
        """The tree read again where a rule begins to count, no row moving anything:
        each branch whose roll-up it moves begins a period there, its cause the
        rule's beginning, by the node whose count it changed, naming the rule."""
        now = standing(start)
        after = evaluate(now)
        for branch in sorted((path for path, part in after.items() if part.beneath),
                             key=lambda path: after[path].order):
            code, kept = after[branch].code, periods.get(branch)
            if kept is None:
                if code is nothing:
                    continue
                periods[branch] = Period(code, Beginning(start, before=True))
            elif kept.code is not code:
                by = _rule_moved(branch, kept.code, code, prior, after)
                rule = _deciding_rule(now, by) if by else None
                periods[branch] = Period(
                    code, Beginning(start, was=kept.code, cause=CAUSE_RULE), by=by,
                    rule=rule.name if rule is not None else "")
            else:
                continue
            if timeline is not None and branch == watch:
                timeline.append(periods[branch])
        return after

    index = upcoming = 0
    while index < len(events):
        at = events[index].timestamp
        while upcoming < len(openings) and openings[upcoming] <= at:
            before = begin(openings[upcoming], before)
            upcoming += 1
        group: list[Event] = []
        while index < len(events) and events[index].timestamp == at:
            group.append(events[index])
            index += 1
        for event in group:
            apply(event)
        after = evaluate(standing(at))
        moved = sorted((path for path in after
                        if _own_part(before[path]) != _own_part(after[path])),
                       key=lambda path: after[path].order)
        weighed: set[str] = set()
        for path in moved:
            for branch in (path, *_ancestors(path)):
                if branch in weighed or not after[branch].beneath:
                    continue
                weighed.add(branch)
                code, kept = after[branch].code, periods.get(branch)
                if kept is None:
                    # A branch that shows nothing still has no period, and gains
                    # none: a node beneath it moved and gave it no status — a shield
                    # on a node not read yet that ended — so nothing began.
                    if code is nothing:
                        continue
                    periods[branch] = Period(code, Beginning(at, before=True))
                elif kept.code is not code:
                    by = _by(branch, kept.code, code, before, after, moved)
                    periods[branch] = Period(
                        code, Beginning(at, was=kept.code,
                                        cause=_cause_in(by, group)), by=by)
                else:
                    continue
                if timeline is not None and branch == watch:
                    timeline.append(periods[branch])
        before = after
    for opening in openings[upcoming:]:
        before = begin(opening, before)
    return periods


def _rule_moved(branch: str, old: StatusCode, new: StatusCode,
                before: Mapping[str, _Part], after: Mapping[str, _Part]) -> str:
    """The node whose count a rule the deployment configures changed, and so moved
    ``branch`` from ``old`` to ``new``: :attr:`Period.by` of a period a rule's
    beginning began (ADR-0137 decision 11). Of the nodes beneath the branch that
    their parent counts otherwise ``after`` than ``before``, by a rule, the first in
    the order the tree draws them that counts the new code where the branch now
    shows a worse failure, or counted the old one where it shows less — and the first
    of them all where none does. Empty where no rule changed a count beneath it."""
    candidates = sorted(
        (path for path, part in after.items()
         if path != branch and _at_or_beneath(path, branch) and path in before
         and before[path].counted is not part.counted
         and part.contribution is not None
         and part.contribution.by == AGGREGATION_RULE),
        key=lambda path: after[path].order)
    if not candidates:
        return ""
    worse = _FAILURE.get(new, 0) - _FAILURE.get(old, 0)
    for path in candidates:
        if (worse > 0 and after[path].counted is new) or (
                worse < 0 and before[path].counted is old):
            return path
    return candidates[0]


def _deciding_rule(rules: RuleSet, path: str) -> AggregationRule | None:
    """The rule the deployment configures that decides what the parent of the node
    at ``path`` counts of it: the one at its own boundary, or a count over its
    parent's children."""
    rule = rules.boundary(path)
    if rule is not None or path == "/":
        return rule
    return rules.counting_children(parent_path(path))


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
