"""Check abstraction: the base class, result type, config parsing and registry.

A check determines the status of one thing and returns a :class:`CheckResult`.
Subclasses register a ``type`` name; the loader instantiates them from YAML
(see ``loader.py``). Config fields common to every check: ``path``, ``name``,
``description``, ``frequency``, ``timeout`` (project.md §2.5), plus the
optional failure retry — ``retry_interval`` / ``retry_attempts`` (ADR-0033) —
the series' retention, ``series_keep`` (ADR-0087), and what the series is drawn by
and how much of it the node shows, ``measures`` / ``reading_cap`` (ADR-0092).
"""
from __future__ import annotations

import abc
import inspect
import sys
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any, ClassVar

from little_sister import secrets
from little_sister.checks.metadata import (
    parse_show_when_quiet,
    parse_subnodes,
    resolve_text,
)
from little_sister.checks.output import failure_text
from little_sister.errors import CheckError as CheckError
from little_sister.errors import ConfigError
from little_sister.limits import RECORD_LIMIT
from little_sister.measures import (
    Measure,
    MeasureError,
    read_measures,
    resolve_measures,
)
from little_sister.origins import release_of
from little_sister.reasons import (
    ReasonEntry,
    ReasonError,
    ReasonInput,
    RecordRefused,
    check_subject,
    derive_code,
    for_the_record,
    marked,
    normalize,
    normalize_record,
)
from little_sister.reasons import (
    plain as _plain,
)
from little_sister.status import StatusCode, join_path, leaf_name, split_path
from little_sister.values import number, strict_flag

if TYPE_CHECKING:
    from little_sister.series import SeriesRecord

DEFAULT_FREQUENCY_SECONDS = 900   # 15 minutes — most checks run infrequently
DEFAULT_TIMEOUT_SECONDS = 30.0


@dataclass(frozen=True)
class CheckResult:
    """The outcome of running a check: a code and, when not OK, a reason.

    A result is a small **tree of values**, mirroring the shape of the status
    tree without being one. Most checks return a single leaf
    (``CheckResult(code, reason)``); a check that reports several aspects returns
    ``children`` — each a named ``CheckResult`` the engine upserts beneath the
    check's node (e.g. ``host.disk``, ``host.memory``). It stays a pure value:
    identity (the full path), observation time, maintenance and event-on-change
    are the tree's to set, not the check's (see ADR-0007). ``name`` identifies a
    child relative to its parent and is ignored on the root (the engine places the
    root at ``check.path``); ``description`` is inherited metadata for the
    node, and ``config`` is the parameters the check ran with — display metadata
    (Markdown) carried onto the node like ``description`` (ADR-0013).

    ``report`` is **what the run found**, as against ``config``'s what it ran
    *with* (ADR-0044): Markdown, written through on every run, shown on the
    node's page and never on a card. It is **never a status claim** — anything
    that should alarm is a reason, and this field must not become a second,
    quieter reason channel. What separates the two is status, not volume: a list
    whose items each carry a verdict is entries (capped on the card); a list
    whose items carry none is scope, and belongs here — the roster is presence,
    an entry is a claim. Unlike ``config``, whose root value comes from
    :meth:`Check.config_summary`, ``report`` rides the result on the root as on
    every child: it is an output of *this* run, so only the run can produce it.

    ``reason`` is **keyed** (ADR-0036): a check may hand over a plain string, a
    list of strings, a ``{slug: text}`` mapping, a list of ``(slug, text)``
    pairs or a list of :class:`~little_sister.reasons.Entry`, and
    ``__post_init__`` normalizes them all into ``reason_entries``.
    A mapping or a pairs list declares its entries **members** — individually
    suppressible, so an operator can pin the one finding they are working on; a
    sequence of strings needs ``entries=True`` to say the same, which exists so a
    check whose strings already carry identity (``f"{issue_id} {text}"``) gets
    per-entry pins without restructuring its return. Everything else is **prose**:
    keyed like all reasons, but one condition in several paragraphs, whose unit of
    suppression stays the node pin.

    **An entry may carry its own code** (ADR-0042), and then the *node's* code is
    derived rather than declared: hand over ``Entry(slug, text, code=…)`` lines
    and **omit ``code``** — declaring both is refused here, loudly, because a
    silently ignored code would be believed. The stored code is the worst of the
    entries' own codes (``UNDEFINED`` ignored; an **empty** entry set reads
    ``OK`` — the check ran, enumerated, and found nothing). ``Entry.running``
    marks a line whose subject has work in flight — display only, never severity.
    A result with prose, or with entries that all carry the node's code, keeps
    declaring ``code`` exactly as before; the engine's failure path is prose and
    is untouched (ADR-0040). ``stored_code`` is always the concrete code the
    engine upserts — declared or derived.

    **An entry may also carry what it is about and what was read.**
    ``Entry.subject`` is the provider's identifier for the entity the line stands
    for — a repository, a host — which several lines commonly share and which no
    slug can be split back into; ``Entry.data`` is the **record**, the material the
    check read and would otherwise throw away once it had written its sentence.
    Neither moves anything: ``text`` is what every surface still shows, and neither
    declares members, because data about a claim is not a claim.

    The record is validated **here**, at this seam: it must be a mapping that
    serializes to JSON, its JSON must weigh no more than this deployment's
    ``record_limit`` bytes (``settings.yaml``, defaulting to
    :data:`~little_sister.limits.RECORD_LIMIT`), and a value under a name the
    surfaces read as a time
    (:data:`~little_sister.reasons.RECORD_TIMESTAMP_KEYS`) must be an ISO-8601
    string with an offset, or null. A check hands over a record it read; shaping it
    to fit is the check's job, and a refusal says the size and names the field.

    **A refusal raises here**, as a :class:`CheckError`, wherever a result is built
    — a check's own tests, a fixture, a script — so an author meets it where the
    record is built. Only inside a run the engine drives is it marked instead
    (ADR-0093): the line keeps its text and its code, its ``data`` is ``None`` and
    ``Entry.refused`` says why, and the rest of the result stands.

    (``subject`` here is the *entity a line is about*, which is not the node-level
    ``about`` below — that one is prose describing what a node *is*.)

    ``about`` (subject metadata — what the node *is*) and ``title`` (a short
    display label) are labels for the subnodes a branch check emits (ADR-0025) —
    e.g. a metrics check captioning its ``disk`` / ``memory`` aspects. Like
    ``name`` they are **ignored on the root** (whose labels keep their
    ``nodes.yaml`` / inline-check sources), and unlike ``description`` /
    ``config`` they **fill an empty node field only**: a ``nodes.yaml``
    declaration seeded at startup always wins, and the label freezes at its
    first fill (stable identity, not live status — text that changes with the
    observation belongs in ``reason``).

    They are the **fallback** channel, not the first one (ADR-0025). A label a
    type ships for a subnode it always emits is
    **declared**, not stamped — ``subnode_defaults`` on the constructor — and the
    library resolves it against the deployment's ``subnodes:`` block and stores it
    per child *name*. What is left for these two fields is the child whose name
    nothing could have declared: the **dynamic** one, a volume or a repository the
    run discovered. A stamped label is read per field: where the resolved map says
    nothing for that name, and — whatever the map says — on a child that says
    ``dynamic`` (below).

    ``order`` is a **declared rank** among a node's siblings (ADR-0055). Siblings
    render alphabetically, which destroys the one order a severity band set has:
    `wiz` puts ``informational`` between ``high`` and ``low``, and `github` puts
    ``low`` before ``medium``, which is a wrong statement about severity. A check
    that knows better says so — ``order=1`` pushes a child down, a negative value
    pulls one up — and the snapshot sorts by ``(order, name)``. **The default `0`
    is exactly today's behavior**, so a check that never thought about order
    cannot accidentally publish its loop: the rank is declared, never incidental.

    Unlike ``name`` / ``about`` / ``title`` it is read on the **root as well as on
    children**, because a rank is not identity: ignoring it on the root would leave
    a check unable to rank the node it owns from its own code, which is half the
    point. It fills an unset field only, so both configured sources — a
    ``nodes.yaml`` ``order:`` and an inline ``order:`` on the check — still win.

    Where a check and a configuration file differ is what ``0`` means. A **check**
    writing ``0`` is saying nothing, because ``0`` is what saying nothing looks
    like; a configuration file naming ``order: 0`` has stated a rank, which is the
    only way a deployment can overrule what a check declared by naming the default
    value. **That is not the same as asking for alphabetical.** ``0`` is the rank
    the unranked carry, so a node at ``0`` sorts with them — after every negative
    rank, before every positive one. Zeroing one child of a set the check ranked
    ``1..5`` moves it to the **front**; handing that whole set back to the alphabet
    means stating ``order: 0`` on every sibling.

    ``show_when_quiet`` says **this node's quiet lines are still information**
    (ADR-0063), and a surface's density mechanisms must not hide them for being
    quiet. It is for the *inventory*-shaped aspect — one line per instance, per
    volume, per account — whose reading is the list itself and is therefore read
    precisely while everything is fine; the opposite claim, that a node's quiet
    lines are noise, a check already makes by not emitting them. Like ``about`` /
    ``title`` it is **ignored on the root**, whose declaration is the
    ``show_when_quiet:`` key in the check's own YAML, and read on **children** —
    where, exactly like them, it is the **dynamic-child channel**: the aspect a
    type always emits declares the flag in its ``subnode_defaults`` entry beside
    its label, and what is left for this field is the child only the run can name.
    The two declarations above it — the deployment's ``subnodes:`` block first,
    the type's map beneath — are merged in ``Check.__init__`` and applied by the
    engine per child name, so a type never reads the config key and a deployment
    never needs a type release to state it.

    It is a **tri-state**, unlike every other flag a result carries: ``None`` is
    "this check said nothing", and ``False`` is a check saying the node's quiet
    lines are ordinary. Both leave today's painting, so the distinction never
    shows here — it matters one layer down, where a stated ``false`` — the
    deployment's ``subnodes:`` or a ``nodes.yaml`` entry — must be able to
    overrule a shipped ``true``.

    ``for_record`` holds the lines a grading writes **for the record alone**
    (ADR-0111): what it says of a reading it does not show. A check that reads
    every run of a job name on each poll shows one line, the newest run's, and
    says how each older run stood here — ``for_record=[Entry(slug, text, code=…,
    subject=…, data=…), …]`` — so that every kept run carries its code and its
    sentence, and a run that failed last week still says so in its series. Each
    line carries its own code and the record of the reading it is said of, and is
    refused without either. **No node sees it**: it is no entry of ``reason``, so
    it reaches neither the node's code nor its line cap, the envelope or a pin, and
    it may be written on any node of the result. A shown line that carries the same
    reading is what stood, and wins.

    ``children_complete`` says that the ``children`` of this node are **all of
    them** (ADR-0109): the run read every one, so a child an earlier run wrote and
    this one does not return is gone, and the engine removes it. It is a statement
    about this node's direct children alone, as far as this check writes them, and
    each node of a result makes it for itself. A result that says nothing — the
    default — removes nothing: a child it leaves out stays, which is what a run
    that could not read it wants (ADR-0060 decision 3). So say it where the run
    listed every child, and leave it unsaid in a run that could not.

    ``dynamic`` says that this child is one **a run names** (ADR-0118): a volume,
    a repository, a function — named by what its source calls it, or by what a
    deployment's configuration does, and not by the type's own code. Nothing
    declared for a *name* reaches such a node: neither the label and the
    ``show_when_quiet`` a type declares in ``subnode_defaults`` nor a deployment's
    ``subnodes:`` block, both of which are keyed by a subnode's name and mean the
    child the type always emits under it. A function called ``batch`` is not the
    ``batch`` aspect. Its labels are the ones this result carries — ``title``,
    ``about``, ``show_when_quiet`` — and a ``nodes.yaml`` entry for its path still
    beats them. It is said of this node alone: a child beneath it that says
    nothing is read by its name, as every node is that says nothing — the
    default. Like ``name`` and the labels it is **ignored on the root**, which a
    check's ``path:`` names.
    """
    code: StatusCode | None = None
    reason: ReasonInput = field(default_factory=list)
    name: str = ""
    description: str = ""
    children: tuple[CheckResult, ...] = ()
    config: str = ""
    report: str = ""
    about: str = ""
    title: str = ""
    order: int = 0
    show_when_quiet: bool | None = None
    entries: bool = False
    for_record: Sequence[ReasonEntry] = ()
    children_complete: bool = False
    dynamic: bool = False
    #: Derived in :meth:`__post_init__` — the one internal form (ADR-0036).
    reason_entries: tuple[ReasonEntry, ...] = field(
        init=False, default=(), repr=False, compare=False)
    members: bool = field(init=False, default=False, repr=False, compare=False)
    #: The concrete code the engine stores — the declared ``code``, or the one
    #: derived from coded entries (ADR-0042). Always a ``StatusCode``.
    stored_code: StatusCode = field(
        init=False, default=StatusCode.UNDEFINED, repr=False, compare=False)

    def __post_init__(self) -> None:
        for child in self.children:
            if not child.name:
                raise CheckError("a child CheckResult must have a 'name'")
        # A statement the engine removes nodes on: it is said, or it is not, and a
        # value that merely reads as true would be believed (ADR-0109).
        if not isinstance(self.children_complete, bool):
            raise CheckError(
                "children_complete is True or False: a node says that its children "
                f"are complete, or says nothing — not {self.children_complete!r} "
                "(ADR-0109)")
        # A statement the engine reads a node's labels by, so it is refused the way
        # a quoted flag is: `"false"` reads as true (ADR-0118).
        if not isinstance(self.dynamic, bool):
            raise CheckError(
                "dynamic is True or False: a child says that a run names it, or "
                f"says nothing — not {self.dynamic!r} (ADR-0118)")
        # Normalize where the outside world enters (ADR-0026): five accepted input
        # forms, one internal one. A malformed slug is the check author's error and
        # surfaces as a failing check, not as a silent re-key.
        try:
            entries, members = normalize(self.reason, self.entries,
                                         record_limit=_record_limit())
            kept = for_the_record(self.for_record, record_limit=_record_limit())
        except ReasonError as error:
            raise CheckError(str(error)) from error
        object.__setattr__(self, "reason_entries", entries)
        object.__setattr__(self, "members", members)
        object.__setattr__(self, "for_record", kept)
        # The ADR-0042 seam: a node with coded entries declares no code of its
        # own — every claim it makes is attributable to a line — and declaring
        # both is refused rather than silently resolved, the way a check YAML
        # naming `name:` is refused (ADR-0016).
        coded = any(entry.code is not None for entry in entries)
        if self.code is not None:
            if coded:
                raise CheckError(
                    "a result may declare a code or code its entries, never "
                    "both — a silently ignored code would be believed "
                    "(ADR-0042)")
            object.__setattr__(self, "stored_code", self.code)
            return
        if coded:
            object.__setattr__(self, "stored_code", derive_code(entries))
            return
        # No code and nothing to derive one from. The one legal shape is the
        # *entry-bearing empty set* — the check enumerated and found nothing,
        # said by an empty mapping or by `entries=True` beside an empty list —
        # which reads OK (ADR-0042: "nothing to report" is not "nothing
        # reported"). Anything else is a result that made claims with no
        # severity anywhere, and is the check author's error.
        if not entries and (self.entries or isinstance(self.reason, Mapping)):
            object.__setattr__(self, "stored_code", StatusCode.OK)
            return
        raise CheckError(
            "a result must declare a code, or hand over entries that carry "
            "their own (an empty entry-bearing set — an empty mapping, or "
            "entries=True beside an empty list — reads OK) (ADR-0042)")

    @property
    def reason_texts(self) -> list[str]:
        """The reason texts in the check's order, whatever form was handed over."""
        return [entry.text for entry in self.reason_entries]


@dataclass(frozen=True)
class Measurement:
    """One reading of one object: what was read, and the object it was read from.

    This is what :meth:`Check.measure` hands back and what :meth:`Check.grade`
    reads, and it is the **only** place an object and its reading live. A check
    run reads one object and the result is one record; the node, the children and
    the lines the grading then writes are *derived* from that reading, never
    beside it (ADR-0085 as ADR-0086 restates it).

    ``record`` is what was read — validated and bounded here, through the same
    seam and the same ``record_limit`` as a line's, because a record is a record
    wherever it hangs and an author who learns one rule should not meet a second.
    It is **data and never a claim**: anything that should alarm is the grading's
    to say. A value the check could not read stands as ``None`` rather than being
    left out, so every reading of one check has one shape and a curve draws a real
    gap from a null instead of inferring one from an absence (ADR-0085 decision 3).
    What must **not** cross into it is the check's working state: the raw answer —
    a 150-finding page, an unshortened log — stays inside the check, and what is
    kept is what is worth keeping.

    ``subject`` is the object's own identifier. A check declares its object at
    construction out of its own configuration (:attr:`Check.subject`), and the
    engine falls back to that only for the **one** measurement it places — a run
    that handed back exactly one. Among several, an empty subject means *no
    subject*: a reading of no named object, which has no series (ADR-0085
    decision 2, ADR-0086 decision 4). A check states it here where the
    object is known only from an **answer** — a rate-limit check that asks the API
    whose token it holds, because the rate-limit endpoint never says, and names one
    account's budget for one resource. It is deliberately not the node's path:
    the path is the deployment's label for where a node hangs and may be renamed
    or moved, while the reading is about a thing in the world, and an identity not
    written down at the reading cannot be added to the history afterwards.

    ``identity`` says whether this reading is a **new record** of its subject or
    one the subject's series already keeps (ADR-0087). Empty — the common case —
    appends: every reading of a response time or a load average really is a new
    one. Set, it names the **event** the reading is of, where the source keeps the
    history — the run that was read, a job's id — and a record of that identity
    already in the kept window is replaced wherever it stands, so the same
    finished run re-read on the next poll stays one record. It is a field beside
    the subject rather than a key in the record for the reason the subject is one:
    the record is the check's own vocabulary, and a reserved name would take one
    away from it. It counts only where there is a series, and a reading with no
    subject has none; like the subject it is bounded and free of control
    characters, because the series keeps it.

    ``state`` is the other answer, for an object whose source keeps no event for
    it — a workflow switched off, a queue, a finding that stands — and no
    *last-changed* field that moves with its state either: the state the object
    is in, spelled from the few fields that constitute it, the switch or the
    status, and never from the whole record. It is compared with the **newest**
    record of the series alone, where an identity is found anywhere in the
    window: the same state replaces that record, and a different one appends — a
    return to an earlier state included — so an unchanged state is one record,
    every change is the next, and the newest record is the state the object is
    in. A measurement names an identity or a state, never both, and a state is
    bounded and free of control characters as an identity is.

    ``refused`` is the seam's, never the check's. A record the seam refuses raises
    a :class:`CheckError` wherever a measurement is built — so an author meets it in
    the tests — except inside a run the engine drives (ADR-0093). There the reading
    is marked instead: ``refused`` says why, and ``record`` is the failure record the
    engine writes for a check that raised, naming the refusal, because that is what
    its series keeps. The engine keeps a marked reading out of the grading and says
    on the node which subject's record was refused. A refused subject, identity or
    state still raises everywhere: they name a reading rather than carry one.
    """
    record: Mapping[str, Any]
    subject: str = ""
    identity: str = ""
    state: str = ""
    refused: str = ""

    def __post_init__(self) -> None:
        try:
            check_subject(self.subject, "a measurement's subject")
            check_subject(self.identity, "a measurement's identity")
            check_subject(self.state, "a measurement's state")
        except ReasonError as error:
            raise CheckError(str(error)) from error
        try:
            record = normalize_record(self.record, limit=_record_limit())
        except RecordRefused as error:
            refusal = marked(error)
            if refusal is None:
                raise CheckError(str(error)) from error
            record = {"error": failure_text(f"record refused: {refusal.why}")}
            object.__setattr__(self, "refused", refusal.why)
        object.__setattr__(self, "record", record)
        if self.identity and self.state:
            raise CheckError(
                "a measurement names the event it is of or the state it is in, "
                f"never both: identity {self.identity!r}, state {self.state!r}")


CHECK_TYPES: dict[str, type[Check]] = {}

#: The **check API epoch** (ADR-0051). It bumps only when the check-authoring
#: surface of architecture.md §11 changes in a way a check type can notice — a name
#: removed or renamed, a documented behavior changed. Adding a name does not bump
#: it, and neither does anything else in a release: a plugin should not have to
#: follow the library's version, only the part of it that is its own contract.
#:
#: **v2** opened when the subnode-metadata helpers left the surface — the library
#: reads the whole ``subnodes:`` block now and a type only declares (ADR-0025), so
#: ``parse_subnodes`` / ``resolve_text`` / ``expand_tokens`` have no external
#: caller left.
#:
#: **v3** opened when ``run()`` was split into :meth:`Check.measure` and
#: :meth:`Check.grade` (ADR-0086). No name left the surface — :class:`Measurement`
#: joined it — but the one method every check type implements was replaced by two,
#: and ``CheckResult`` lost ``subject`` and ``record``, which a measurement now
#: carries alone. A type written for v2 cannot be adapted at runtime: it would
#: still declare a code from a world it re-reads inside the grading, which is the
#: one failure the split exists to make impossible. Every plugin says
#: ``require_api(3)``.
API_VERSION = 3


def require_api(version: int, *, by: str = "") -> None:
    """Refuse at import unless this library speaks the check API ``version``.

    What a package built against a tag actually depends on is the *surface*, not
    the release — so it declares the epoch it was written for, from its
    ``__init__`` beside its `@register` imports, and a mismatch stops the process
    at startup with both numbers in the message instead of at the first run of one
    check, inside a name that moved.

    The install-time floor (``little-sister >= x`` in the package's metadata) is
    still the first line: it keeps a *too old* library from being installed at all.
    This is the second, for the upgrade the floor cannot see — a library that moved
    past the epoch the plugin was built for.

    ``by`` names the package in the message; the calling module's name is used when
    it is not given, which is right for the ordinary one-line call site.
    """
    if version == API_VERSION:
        return
    who = by or _calling_module()
    direction = ("newer than" if version > API_VERSION else "older than")
    raise CheckError(
        f"{who} was built for little-sister check API v{version}, which is "
        f"{direction} the v{API_VERSION} this little-sister ({_library_version()}) "
        f"speaks. Install a build of {who} for v{API_VERSION}, or a little-sister "
        f"that speaks v{version} (ADR-0051).")


def _calling_module() -> str:
    """The module that called into here — the package to name in a refusal."""
    frame = sys._getframe(2) if hasattr(sys, "_getframe") else None
    name = frame.f_globals.get("__name__", "") if frame is not None else ""
    return str(name) or "a dependent package"


#: Whether a configuration was found the first time one was looked for. ``None``
#: until then. It is remembered because the answer cannot change within a process
#: — a deployment either has a configuration directory or does not — and because
#: the lookup is a failed import, which Python does not cache.
_CONFIGURED: bool | None = None


def _record_limit() -> int:
    """How heavy a record this deployment allows — ``record_limit`` in
    ``settings.yaml``, defaulting to :data:`~little_sister.limits.RECORD_LIMIT`
    where there is no deployment to ask.

    **Imported late**, the way :func:`_library_version` is: ``little_sister.config``
    reads the settings files when the module is imported, and this module is
    imported by every check type — including a plugin's, at ``import`` time — so
    binding the configuration at module scope would bind a deployment's settings at
    a moment that has nothing to do with that deployment being ready.

    **And the import may fail, which is an answer rather than an error.** Importing
    the configuration *resolves a configuration directory*, and refuses when there
    is none (ADR-0031). A ``CheckResult`` is built in plenty of places where there
    is none and should be: a plugin's own test suite is the common one, and a type
    that could not construct a result without a deployment beside it would be a
    type nobody can unit-test. So a missing configuration reads as *no deployment
    has an opinion*, and the default stands. A deployment cannot reach that branch
    — ``little_sister.app`` resolves its configuration at import and refuses to come
    up without it, long before any check runs.
    """
    global _CONFIGURED
    if _CONFIGURED is False:
        return RECORD_LIMIT
    try:
        from little_sister.config import config
    except ConfigError:
        _CONFIGURED = False
        return RECORD_LIMIT
    _CONFIGURED = True
    return config.record_limit


def _library_version() -> str:
    """little-sister's own version, for a message. Imported late: ``little_sister``
    imports nothing from here, and this keeps it that way."""
    from little_sister import __version__
    return __version__


def register(type_name: str) -> Callable[[type[Check]], type[Check]]:
    """Class decorator registering a check under its ``type`` name.

    A name is claimed **once** (ADR-0051). Type names stay bare — `type: github`,
    not a namespaced spelling — so two packages can now claim one, and the registry
    has no answer: import order would pick the winner and every check of the losing
    package would silently run somebody else's code, against the losing package's
    configuration. So the second claim **refuses**, naming both classes.

    Re-registering the *same* class is not a conflict — a module re-imported under
    a reloading server re-runs its decorators, and refusing that would refuse the
    server.
    """
    def decorator(cls: type[Check]) -> type[Check]:
        claimed = CHECK_TYPES.get(type_name)
        if claimed is not None and not _same_class(claimed, cls):
            raise CheckError(
                f"two packages claim check type {type_name!r}: "
                f"{_where(claimed)} registered it and {_where(cls)} claims it too. "
                f"A type name answers for exactly one class — rename one of them, "
                f"or install only one of the packages (ADR-0051).")
        cls.type_name = type_name
        CHECK_TYPES[type_name] = cls
        return cls
    return decorator


def _same_class(claimed: type[Check], cls: type[Check]) -> bool:
    """Whether these are one class — by identity, or the same name in the same
    module, which is what a reload produces.

    The name match is deliberately restricted to **module-level** classes. A class
    built inside a function carries ``<locals>`` in its qualified name, and a factory
    called twice produces two genuinely different classes that share both names —
    accepting those as "a reload" would silently let the second overwrite the first,
    which is the whole failure this refusal exists to prevent.
    """
    if claimed is cls:
        return True
    if "." in cls.__qualname__ or "." in claimed.__qualname__:
        return False
    return ((claimed.__module__, claimed.__qualname__)
            == (cls.__module__, cls.__qualname__))


def _where(cls: type[Check]) -> str:
    """Where a check class comes from, for a refusal message."""
    return f"{cls.__module__}.{cls.__qualname__}"


@dataclass(frozen=True)
class TypeOrigin:
    """Where one registered check type came from — what ``/system`` shows.

    Once a type can arrive from a separately released package, "which code is
    answering for `type: github`, at which version" stops being derivable from this
    repository at all. An operator diagnosing a check has to be able to read it off
    the running instance, the way the slot fillers and the assembled policy already
    are (ADR-0051).
    """
    type_name: str
    module: str
    package: str
    distribution: str
    version: str
    #: Where the module was actually **loaded from**. The version beside it is the
    #: installed *metadata's* claim, and the two can disagree — a source copy on the
    #: path shadows an installed distribution of the same name, and the metadata
    #: keeps answering for code that is not running. That case is the one an
    #: operator comes to this page for, so the page shows both.
    path: str

    @property
    def builtin(self) -> bool:
        """Whether the library itself registered this type."""
        return self.package == "little_sister"


def registered_types() -> list[TypeOrigin]:
    """Every registered check type with its origin, by type name."""
    origins: list[TypeOrigin] = []
    for type_name, cls in sorted(CHECK_TYPES.items()):
        package = cls.__module__.split(".")[0]
        distribution, release = release_of(package)
        module = sys.modules.get(cls.__module__)
        origins.append(TypeOrigin(type_name=type_name, module=cls.__module__,
                                  package=package, distribution=distribution,
                                  version=release,
                                  path=getattr(module, "__file__", "") or ""))
    return origins


class Check(abc.ABC):
    """Base class for all checks.

    A check knows where it writes in the tree (``path``), how often it runs
    (``frequency_seconds``), how long to wait (``timeout_seconds``), how to read
    the world (:meth:`measure`) and what that reading means (:meth:`grade`).
    """

    type_name: ClassVar[str] = ""

    def __init__(self, *, path: str, description: str = "",
                 about: str = "", title: str = "", order: int | None = None,
                 show_when_quiet: bool | None = None,
                 subnode_show_when_quiet: Mapping[str, bool] | None = None,
                 subnode_labels: Mapping[str, Mapping[str, str]] | None = None,
                 subnode_defaults: Mapping[str, Mapping[str, object]] | None = None,
                 label_tokens: Mapping[str, str] | None = None,
                 frequency_seconds: int = DEFAULT_FREQUENCY_SECONDS,
                 timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
                 retry_interval_seconds: int | None = None,
                 retry_attempts: int | None = None,
                 escalate_after: int | None = None,
                 depends_on: str | None = None,
                 series_keep: int = 0,
                 reading_cap: int | None = None,
                 measures: Mapping[str, object] | None = None,
                 measure_defaults: Mapping[str, object] | None = None,
                 subject: str = "") -> None:
        # The check's full, absolute node path (ADR-0016); `name` is the last segment.
        self.path = join_path(path)
        self.description = description
        # Inline node metadata (nodes.yaml overrides each): `about` is subject
        # metadata (ADR-0012), `title` a short display label (ADR-0017), `order`
        # the node's rank among its siblings (ADR-0055). `order` is the one that
        # is `None` rather than empty when unstated, because `0` is a rank an
        # author may mean; the two labels have no such value. `show_when_quiet`
        # (ADR-0063) is nullable for the same reason `order` is: a stated `false`
        # is a declaration, not a silence.
        self.about = about
        self.title = title
        self.order = order
        self.show_when_quiet = show_when_quiet
        # The per-subnode `show_when_quiet` map the engine applies by child
        # *name*, at any depth (ADR-0063 §2-§3), merged here from the two
        # declarations that can carry it: what this **type** declared, in the
        # same `subnode_defaults` entries that declare its labels, and what the
        # **deployment** stated in the `subnodes:` block of the check's YAML,
        # which `_parse_common` parsed for every type. The deployment's value
        # wins per name, because a file somebody edits beats a map somebody
        # released; both beat the value a child result stamps — unless that child
        # says that a run names it, and the map is not asked (ADR-0118) — and
        # `nodes.yaml` beats all three by being seeded before the first tick.
        #
        # One merge, no layering: unlike a label there is nothing to extend, so
        # a stated value replaces a declared one outright.
        self.subnode_show_when_quiet: dict[str, bool] = {
            **_declared_show_when_quiet(subnode_defaults),
            **(subnode_show_when_quiet or {})}
        # The same block's **labels**, resolved here and once (ADR-0025). Three
        # inputs meet: `subnode_labels` is the deployment's `subnodes:` block as
        # `_parse_common` read it, `subnode_defaults` is
        # what this *type* declares it ships for the subnodes it always emits,
        # and `label_tokens` are the values its own text may reuse. The library
        # resolves them per field — configured text over declared default, with
        # `{default}` and `{token}` — and the engine writes the result per child
        # *name*, at any depth, so a type never reads the block and a deployment
        # never needs a type release to retune a label.
        #
        # Resolving in the constructor is what **pins the tokens to construction
        # time**: a label freezes at the node's first fill (ADR-0025 decision 3),
        # so a token whose value could change between runs was never legal in one.
        # A structure that resolves once cannot express the illegal thing.
        self.subnode_labels: dict[str, dict[str, str]] = _resolve_subnode_labels(
            subnode_labels, subnode_defaults, label_tokens)
        self.frequency_seconds = frequency_seconds
        self.timeout_seconds = timeout_seconds
        # The budgeted failure retry (ADR-0033): while the last result is not
        # OK the engine schedules this check at `retry_interval_seconds`
        # instead of its frequency, at most `retry_attempts` times per failure
        # episode. ``None`` inherits the settings-level default; ``0`` switches
        # the retry off for this check.
        self.retry_interval_seconds = retry_interval_seconds
        self.retry_attempts = retry_attempts
        # How many consecutive readings of a worse code the nodes this check writes
        # need before they publish it upward (backlog #38 B). ``None`` inherits the
        # settings-level default; the engine resolves the two and hands the answer
        # to the tree, which reads no configuration of its own.
        self.escalate_after = escalate_after
        # The check this one is reached **through** (backlog #38 A): while that
        # check reports a failure, this check's reading is not believed and its
        # node is shielded — *we could not get there* rather than *it is broken*.
        # A check path, because a check is the configured unit and the declaration
        # then covers every node this check writes; `tag:` selectors are a later
        # shape. `None` is every check today: nothing is shielded unless somebody
        # says what reaches it.
        self.depends_on = None if depends_on is None else join_path(depends_on)
        # How many readings of each subject this check keeps as its **series**,
        # oldest out (ADR-0087). A count and only a count, from the check's own
        # YAML: where a history is wanted is an editorial choice per check, so
        # there is no deployment-wide default to inherit, and `0` — the default —
        # is no series at all. The engine reads it per run; a type never sets it.
        self.series_keep = series_keep
        # **What those readings are drawn by** (ADR-0092): the measures this type
        # declares — `measure_defaults`, what a field of its record means and in
        # which unit — with the deployment's `measures:` block, which
        # `_parse_common` read for every type, merged over them per field. Resolved
        # here and once, like the subnode labels above, so the page reads the
        # answer and never the two blocks. A declaration of another shape refuses
        # the load like any configuration error, though it comes from code.
        try:
            self.measures: dict[str, Measure] = resolve_measures(
                read_measures(measures, where="measures"),
                read_measures(measure_defaults, where="measure_defaults",
                              removals=False))
        except MeasureError as error:
            raise CheckError(str(error)) from error
        # How many of a subject's readings the node that stands for it shows
        # (ADR-0092 decision 7): this check's own answer, or `None` to leave
        # `settings.yaml`'s `reading_cap` in force — resolved by the page, the way
        # the engine resolves the retry fields.
        self.reading_cap = reading_cap
        # **The object this check reads**, declared here and not later (ADR-0086).
        # Unlike every other field above it is not parsed from the YAML by
        # `_parse_common`: it comes out of the *type's* own configuration — a
        # `url`, a `host`, a file path — so the type passes it up, and a type
        # whose object is knowable only from the answer leaves it empty and states
        # it on the `Measurement` instead.
        #
        # At construction, because the engine needs a name for the object when the
        # check **raises**: there is no measurement then, and an identity not
        # written down at the reading cannot be added to the history afterwards.
        # It is also why this cannot be a per-run value — a subject that moved
        # between runs would silently split one series in two.
        try:
            check_subject(subject, "a check's subject")
        except ReasonError as error:
            raise CheckError(str(error)) from error
        self.subject = subject
        # Failures from resolve-at-construction secret references (ADR-0023):
        # non-empty ⇒ the engine pins this check to ERROR and never calls
        # measure().
        self.secret_errors: list[str] = []
        # The read of this check's own series (ADR-0113), which whoever runs the
        # check hands it (:meth:`bind_kept`) — the engine, or a type's own test;
        # ``None`` where nobody did.
        self._kept_reader: Callable[[str], tuple[SeriesRecord, ...]] | None = None

    @property
    def name(self) -> str:
        """This check's node name — the last segment of its path (ADR-0016)."""
        return leaf_name(self.path)

    def owned_nodes(self) -> set[str]:
        """The tree nodes this check gives a definite status to, each the root of
        the subtree it owns (ADR-0015). The loader rejects a union in which two
        checks own overlapping nodes. A leaf check owns just its own node; a
        **branch** check overrides this to own its child subtrees and **not** the
        shared container node it merely rolls up — so peers (e.g. ``host-metrics``
        + ``qnap-metrics``) coexist on one host node, while a duplicate or a leaf
        placed on that container is caught."""
        return {self.path}

    def expected_cost(self) -> float | None:
        """Worker time one run of this check is expected to occupy, in **seconds**
        — an estimate a type computes from its own configuration, or ``None``,
        the default, for a type that will not estimate.

        Fifty repositories at two requests each is a different number from one,
        and only the type can say which it has; the library never guesses one.
        This is an estimate and not a bound — ``timeout_seconds`` is the bound —
        and the difference is why the default is silence: startup **sums what is
        declared** over the checks that declare, against the worker threads the
        engine runs, and refuses a configuration whose declared part alone cannot
        fit, naming the checks. A type that declared its timeout here would refuse
        configurations that work.

        The sum is a lower bound on what the deployment costs, which is all a
        refusal needs; what it cannot do is promise that a silent configuration
        fits. The estimate decays as an estate grows, so the measured wall time
        stands beside it on ``/system``.
        """
        return None

    def expected_entries(self) -> int | None:
        """Reason entries this check expects to hold in the tree at once, over
        every node it owns — again from its own configuration, and ``None``, the
        default, for a type that will not estimate.

        Summed at startup against the tree's entry limit exactly as
        :meth:`expected_cost` is against the worker threads, with the same
        lower-bound reading and the same refusal naming the checks.
        """
        return None

    def expected_record(self) -> int | None:
        """Bytes **one** of this check's records is expected to need, in the JSON
        it is measured in — again from the type's own configuration, and ``None``,
        the default, for a type that carries no record or will not estimate.

        The third declaration beside the two above, and the one that is **compared
        rather than summed**: the worker ceiling and the entry limit are shared by
        every check, so what matters there is the total, while ``record_limit`` is
        a bound on a single record, so what matters here is whether this type's
        largest fits. Startup refuses a type declaring more than the deployment
        allows, naming it — instead of the first run doing it fifteen minutes
        later, in a package the deployment did not write.

        It does **not** raise the limit, and nothing here should be read as asking
        for room: the limit exists against the check, and a bound its subject can
        lift is not one. A type aims at the default, because a package cannot see
        which deployment it is installed into.

        The measured largest record of the last run stands beside it on
        ``/system``, for the reason every declaration here has one: an estimate
        nobody can compare against a measurement decays invisibly.
        """
        return None

    def config_summary(self) -> str:
        """The curated parameters this check ran with, as Markdown, for its detail
        page (ADR-0013). Operator-authored and safe for all viewers — secrets stay
        in ``.env`` (ADR-0003). Override to declare a small allow-list (see
        :func:`config_markdown`); the default is empty.

        Where it goes for a **branch** check depends on **who owns the container**
        (ADR-0044 decision 1), not on the check being a branch check: own that
        node alone and its whole-check text belongs there; **share** it with
        another check — the ``host-metrics`` + ``qnap-metrics`` shape — and this
        stays empty, with each child result's ``config`` tagged instead. A shared
        container withholds the text either way (two checks have no one answer,
        the rule that already withholds its timestamp and run facts), so a check
        with whole-check information to publish should own its own node. The same
        rule governs ``CheckResult.report``."""
        return ""

    def resolve_secret(self, reference: str) -> str:
        """Resolve a secret reference **at construction time** (ADR-0023).

        Every reference is ``scheme://address``: ``env://NAME`` reads that
        environment variable (``.env``, ADR-0003), and any other scheme goes
        through the resolver the application registered
        (``little_sister.secrets``). There is deliberately **no bare-name form** —
        a credential pasted where its reference belongs must fail the grammar
        rather than be looked up and echoed. Call this from
        ``__init__`` / ``_extra_from_config`` and keep the value — never
        resolve during :meth:`measure` (cloud stores bill per read; rotation is a
        restart).

        A **malformed** reference raises :class:`CheckError`, so the load fails
        loudly like any config typo — an empty value, no ``scheme://`` at all, a
        scheme with no address, or a scheme no resolver is registered for. A
        well-formed reference
        that **fails to resolve** (store unreachable, secret absent) is
        recorded in ``secret_errors`` and returns ``""`` — the engine then pins
        this check to a visible ERROR without ever calling :meth:`measure`.
        """
        try:
            return secrets.resolve(reference)
        except secrets.UnknownSchemeError as error:
            raise CheckError(str(error)) from error
        except secrets.SecretError as error:
            self.secret_errors.append(str(error))
            return ""

    def bind_kept(self,
                  reader: Callable[[str], tuple[SeriesRecord, ...]]) -> None:
        """Hand this check the read of its own series: ``reader(subject)`` answers
        what is kept of that subject, for this check and for no other (ADR-0113
        decision 1). Whoever runs the check calls it: the engine, once for every
        check it runs, with a read that answers only while that check measures —
        and a type's own test, which stands in the engine's place and binds what
        it wants the type to find. A check nothing bound is answered nothing."""
        self._kept_reader = reader

    def kept(self, subject: str = "") -> tuple[SeriesRecord, ...]:
        """**What this check kept of a subject** (ADR-0113): the window of one of
        its own series as the store holds it — every kept record, oldest first,
        each with its record (``data``), its own time (``at``), the moment it was
        observed, its identity or its state, and the code and the texts that stood
        where it landed. With no argument, of the object this check declares.

        **It is for deciding what to ask, and for nothing else.** A type that reads
        a history from its source asks from where its own history ends, instead of
        asking for the whole of it on every poll; what it hands back is still what
        the source said. A record stays a fact about the world: what a type derived
        from its history is not written into one, because two instances would then
        keep different records of one world.

        The records are copies — writing to one changes nothing that is kept. The
        answer is empty where this check keeps no series (``series_keep``), where
        nothing of the subject is kept yet, and outside an engine; a type asks for
        its whole window then.

        **Under an engine it answers only inside** :meth:`measure`, on the thread
        the engine called that on, and raises :class:`CheckError` anywhere else. A
        grading reads the records, the configuration and the clock it is handed
        (ADR-0086 decision 6); one that read the store would grade an old reading
        differently when it is graded again. A thread this check starts carries no
        such mark, so read before fanning out.
        """
        reader = self._kept_reader
        if reader is None:
            return ()
        return reader(subject or self.subject)

    @abc.abstractmethod
    def measure(self) -> Measurement | Sequence[Measurement]:
        """**Read the world.** One :class:`Measurement` per object this run read —
        one of them, or a sequence where the run reads several (ADR-0086).

        This half touches the world and nothing else: it makes the request, runs
        the command, parses the answer into numbers, and hands back what is worth
        keeping. It decides **no** status and writes **no** text — those are
        :meth:`grade`'s, and the split exists so that they can be decided again
        later over a record this process did not produce.

        A run that **failed** to read its object still measured something — that it
        could not get there, and why — so it records the attempt, with the values
        it could not get standing as ``None`` beside the reason (ADR-0085
        decision 3). A run that measured nothing at all returns an empty sequence,
        and the node's last reading is cleared rather than left to be read as
        today's.

        The engine does **not** bound this: Python cannot kill a thread, so a hung
        `measure()` occupies a pool worker until it returns, and
        ``self.timeout_seconds`` is a budget you enforce. An exception out of here
        becomes an `ERROR` on the node **and** a failure record naming this check's
        object, which the engine builds itself (ADR-0040 as ADR-0086 extends it).
        """

    @abc.abstractmethod
    def grade(self, measurements: Sequence[Measurement],
              now: datetime) -> CheckResult:
        """**Say what it means.** The codes and the texts, as one
        :class:`CheckResult` — the same tree a check has always returned.

        ``measurements`` is what :meth:`measure` handed back, normalized to a
        sequence: **the objects of one run**, one entry per object and never one
        object twice. Mapping each record to the node, the child or the line that
        stands for it is this method's work, because a record that becomes a line
        is an ``Entry`` under a node and nothing the engine could place for you.

        **It must be pure over ``(record, configuration, now)``.** Read the
        records, read the fields this type parsed at construction, read the clock
        it is given — and nothing else. Not an attribute :meth:`measure` left
        behind, not the clock directly, not the world again. The reason is not
        tidiness: a later phase grades **old** records out of a series, when the
        process that took them is long gone, and a grading that leans on anything
        else returns something quietly wrong rather than failing.

        ``now`` is an aware UTC instant, given rather than taken for the same
        reason: a grading that called the clock itself could not be replayed.
        """

    # --- construction from config ---

    @classmethod
    def from_config(cls, config: dict[str, Any], base_dir: Path) -> Check:
        """Build the check this config describes.

        The construction is guarded because the **common fields grow**. A check
        type written outside this repository is promised a list of *names*
        (ADR-0049), not a frozen constructor signature, so a type that spells the
        common keywords out instead of taking ``**kwargs`` stops binding the day
        one is added — which is what happened when ``order`` arrived (ADR-0055).
        Unguarded that surfaces as a bare ``TypeError`` from deep inside the
        loader, naming neither the file nor the type; a `CheckError` naming both
        is the difference between a five-minute fix and an afternoon.
        """
        common = _parse_common(config)
        extra = cls._extra_from_config(config, base_dir)
        try:
            return cls(**common, **extra)
        except TypeError as error:
            raise _construction_refused(cls, {**common, **extra}, error) from error

    @classmethod
    def _extra_from_config(cls, config: dict[str, Any],
                           base_dir: Path) -> dict[str, Any]:
        """Subclass hook: parse type-specific config into constructor kwargs."""
        return {}


def _construction_refused(cls: type[Check], kwargs: dict[str, Any],
                          error: TypeError) -> BaseException:
    """Turn a constructor that would not bind into a :class:`CheckError` naming
    the type and the keywords it refused — or hand the original error back
    untouched when it came from *inside* the constructor.

    That second case is the whole reason this is a function rather than three
    lines. A ``TypeError`` raised by the check's own body (``int(None)`` in an
    ``__init__``, say) is a real defect in that check, and relabelling it *"your
    constructor refuses a keyword"* would send its author looking in exactly the
    wrong place. The two are told apart by the traceback: a binding failure is
    raised by the call itself, so its traceback stops at this frame, while
    anything raised inside the callee has a frame below it.
    """
    if error.__traceback__ is not None and error.__traceback__.tb_next is not None:
        return error
    refused = _keywords_refused_by(cls, kwargs)
    if not refused:
        return error
    names = ", ".join(repr(key) for key in refused)
    return CheckError(
        f"check type {cls.type_name!r} ({cls.__module__}.{cls.__qualname__}) "
        f"does not accept {names}. The fields every check shares grow over time, "
        f"so a check type must take **kwargs and hand them to super().__init__() "
        f"rather than spelling them out — see the check-authoring surface "
        f"(ADR-0049)")


def _keywords_refused_by(cls: type[Check], kwargs: dict[str, Any]) -> list[str]:
    """Which of ``kwargs`` this constructor has no parameter for. Empty when it
    takes ``**kwargs`` (it refuses nothing) or when the signature cannot be read,
    in which case the caller keeps the original error rather than guessing."""
    try:
        parameters = inspect.signature(cls).parameters
    except (TypeError, ValueError):     # pragma: no cover - exotic callables only
        return []
    if any(parameter.kind is inspect.Parameter.VAR_KEYWORD
           for parameter in parameters.values()):
        return []
    return sorted(key for key in kwargs if key not in parameters)


_LABEL_FIELDS = ("title", "about")


def _resolve_subnode_labels(
        configured: Mapping[str, Mapping[str, str]] | None,
        declared: Mapping[str, Mapping[str, object]] | None,
        tokens: Mapping[str, str] | None) -> dict[str, dict[str, str]]:
    """One subnode label map: the text each named subnode's ``title`` / ``about``
    finally reads (ADR-0025).

    ``configured`` is the deployment's ``subnodes:`` block, ``declared`` what the
    check type ships for the subnodes it always emits, ``tokens`` the values its
    text may reuse. A ``declared`` entry may also carry ``show_when_quiet``, which
    is not a label and is not read here — the two halves of one entry are resolved
    by the reader each belongs to (:func:`_declared_show_when_quiet` for the flag),
    which is what lets the type's map be shaped like the block itself.
    Resolution is **per field**, by :func:`resolve_text`: the
    configured text when it says something, the declared default otherwise, with
    ``{default}`` substituted (so a deployment can extend rather than replace) and
    ``{token}`` expanded by a plain replace that leaves Markdown intact.

    A field that resolves to **nothing is left out** rather than stored empty, and
    the two are different things one layer up: the engine reads a child result's
    own label where this map is silent for that name, which is what keeps a
    dynamically named child — a volume, a repository the run discovered — labeled
    by the check that discovered it. A child that says so is read from its own
    result whatever this map holds (ADR-0118).
    """
    configured = configured or {}
    declared = declared or {}
    tokens = dict(tokens or {})
    resolved: dict[str, dict[str, str]] = {}
    for name in sorted({*configured, *declared}):
        stated = configured.get(name) or {}
        default = declared.get(name) or {}
        labels = {field_name: text
                  for field_name in _LABEL_FIELDS
                  if (text := resolve_text(str(stated.get(field_name, "")),
                                           str(default.get(field_name, "")),
                                           tokens))}
        if labels:
            resolved[name] = labels
    return resolved


def _declared_show_when_quiet(
        declared: Mapping[str, Mapping[str, object]] | None) -> dict[str, bool]:
    """The ``show_when_quiet`` a check **type** declares per subnode, read out of
    the same ``subnode_defaults`` entries that declare its labels (ADR-0063 §2).

    The type's half of the block is therefore one map shaped like the block
    itself — ``name -> {title, about, show_when_quiet}`` — and an aspect that is a
    roster *by construction* is declared once in the package instead of once per
    account per installation in somebody's ``nodes.yaml``.

    **Only for the names that state it**, like the configuration reader beside it:
    absence is the tri-state's third value and has to stay absent, or a type
    declaring a label would be declaring `false` for the flag by accident and
    would shut out the value a run stamps. A non-boolean raises
    :class:`CheckError` naming the subnode — the same refusal the config key gets,
    for the same reason (``bool("false")`` is ``True``), and a declaration is
    read at load like any other config error even though it comes from code.
    """
    flags: dict[str, bool] = {}
    for name, entry in (declared or {}).items():
        if not isinstance(entry, Mapping) or entry.get("show_when_quiet") is None:
            continue
        flags[str(name)] = strict_flag(
            entry, "show_when_quiet", where=f"subnode_defaults.{name}")
    return flags


def _parse_common(config: dict[str, Any]) -> dict[str, Any]:
    """Parse the fields every check shares.

    A node is addressed by one **absolute, slash-separated** ``path`` — e.g.
    ``/system/alpha`` — whose last segment is the node's name (ADR-0016).
    """
    if "name" in config:
        raise CheckError(
            "'name' was merged into 'path' (ADR-0016); give one absolute path "
            "such as '/system/alpha'")
    path = join_path(str(config.get("path", "")))
    if not split_path(path):
        raise CheckError("check config must define a non-empty 'path'")
    return {
        "path": path,
        "description": str(config.get("description", "")),
        "about": str(config.get("about", "")),
        "title": str(config.get("title", "")),
        # A rank beside the labels it sits with (ADR-0055). Read only when the key
        # is *present*, so an absent one stays "nobody said" while a stated `0`
        # reaches the tree; a non-numeric one fails the load rather than being
        # dropped, because a silently ignored rank would leave the row in an order
        # nobody chose.
        "order": (number(config, "order", where="check config")
                  if config.get("order") is not None else None),
        # The root's own `show_when_quiet:` (ADR-0063) — this node's quiet lines
        # are still information. Read only when present, like the rank beside it,
        # because a stated `false` is what a deployment writes to take back a
        # declaration; a non-boolean fails the load rather than being coerced,
        # since `bool("false")` would switch the node on while the file says off.
        "show_when_quiet": (
            strict_flag(config, "show_when_quiet", where="check config")
            if config.get("show_when_quiet") is not None else None),
        # The same field per subnode, from the `subnodes:` block (ADR-0063).
        # Parsed here — by the library, for every type — so a deployment can
        # state it for any installed branch check without the type knowing the
        # key; the engine applies it per child, over the result's shipped
        # default.
        "subnode_show_when_quiet": parse_show_when_quiet(config),
        # The **labels** out of that same block, read by the same library for
        # the same reason (ADR-0025). They were the type's to
        # read while its defaults lived as code it applied; once a type declares
        # them (`subnode_defaults`) there is nothing left for it to mediate, and
        # a `subnodes:` label written against a type that never read the block
        # stops being a silent no-op.
        "subnode_labels": parse_subnodes(config),
        "frequency_seconds": parse_duration(
            config.get("frequency"), DEFAULT_FREQUENCY_SECONDS),
        "timeout_seconds": float(parse_duration(
            config.get("timeout"), int(DEFAULT_TIMEOUT_SECONDS))),
        # the budgeted failure retry (ADR-0033): absent (None) inherits the
        # settings-level default; a present junk value fails the load, like a
        # bad frequency would
        "retry_interval_seconds": (
            None if config.get("retry_interval") is None
            else parse_duration(config.get("retry_interval"), 0)),
        "retry_attempts": _parse_retry_attempts(config.get("retry_attempts")),
        "escalate_after": _parse_escalate_after(config.get("escalate_after")),
        "depends_on": _parse_depends_on(config.get("depends_on")),
        # The series' retention (ADR-0087), read for every type like the fields
        # above: a count, `0` when absent. Junk and a negative number fail the
        # load, because a history silently switched off is found out a week later.
        "series_keep": _parse_series_keep(config.get("series_keep")),
        # What the series is drawn by and how much of it the node shows (ADR-0092),
        # beside the count they are about. A block of another shape and a cap that
        # is not a whole number fail the load, as a bad count does.
        "measures": _parse_measures(config.get("measures")),
        "reading_cap": _parse_reading_cap(config.get("reading_cap")),
    }


def _parse_depends_on(value: object) -> str | None:
    """The path of the check this one is reached through (backlog #38 A), or
    ``None``. A blank string is the author's typo rather than *no dependency*, and
    fails the load: a declaration that silently means nothing is worse than none."""
    if value is None:
        return None
    path = str(value).strip()
    if not path:
        raise CheckError("depends_on must name a check path, not an empty value")
    if path.startswith("tag:"):
        raise CheckError(
            f"depends_on does not take a selector yet, only a check path: "
            f"{path!r}")
    return path


def _parse_escalate_after(value: object) -> int | None:
    """The per-check escalation count (backlog #38 B): ``None`` (absent) inherits the
    settings-level default; otherwise a positive int. Zero would mean *never
    publish*, so it fails the load rather than silencing a check quietly."""
    if value is None:
        return None
    try:
        count = int(str(value).strip())
    except ValueError as exc:
        raise CheckError(f"invalid escalate_after: {value!r}") from exc
    if count < 1:
        raise CheckError(f"escalate_after must be >= 1, got {value!r}")
    return count


def _parse_retry_attempts(value: object) -> int | None:
    """The per-check fast-retry budget (ADR-0033): ``None`` (absent) inherits
    the settings-level default; otherwise a non-negative int, where ``0``
    switches the retry off for this check. Junk fails the load like any typo."""
    if value is None:
        return None
    try:
        attempts = int(str(value).strip())
    except ValueError as exc:
        raise CheckError(f"invalid retry_attempts: {value!r}") from exc
    if attempts < 0:
        raise CheckError(f"retry_attempts must be >= 0, got {value!r}")
    return attempts


def _parse_series_keep(value: object) -> int:
    """How many readings of each subject this check keeps as its series
    (ADR-0087): ``0`` — no series at all — when absent, otherwise a whole number
    and never a negative one. Junk fails the load like any typo, and a boolean is
    junk: ``true`` is not a count."""
    if value is None:
        return 0
    try:
        count = int(str(value).strip())
    except ValueError as exc:
        raise CheckError(f"invalid series_keep: {value!r}") from exc
    if count < 0:
        raise CheckError(f"series_keep must be >= 0, got {value!r}")
    return count


def _parse_measures(value: object) -> dict[str, Measure | None]:
    """The check's ``measures:`` block (ADR-0092): field name to measure, and
    ``None`` for a field it takes back from the type's defaults. Another shape
    fails the load, naming the field where there is one."""
    try:
        return read_measures(value, where="measures")
    except MeasureError as error:
        raise CheckError(str(error)) from error


def _parse_reading_cap(value: object) -> int | None:
    """How many of a subject's readings this check's node shows (ADR-0092
    decision 7): ``None`` (absent) leaves ``settings.yaml``'s ``reading_cap`` in
    force; otherwise a whole number, ``0`` showing the curves alone. Unlike the
    setting, which is logged and replaced, a bad value here fails the load, as a
    bad ``series_keep`` beside it does — and a boolean is junk."""
    if value is None:
        return None
    try:
        count = int(str(value).strip())
    except ValueError as exc:
        raise CheckError(f"invalid reading_cap: {value!r}") from exc
    if count < 0:
        raise CheckError(f"reading_cap must be >= 0, got {value!r}")
    return count


#: The unit suffixes :func:`parse_duration` reads, each a fixed number of seconds.
#: Lowercase on purpose: a unit is one letter, and the one capital that means
#: something of its own elsewhere (``M``, a month) must not lowercase quietly into
#: its neighbor. A month is not here because it is not a number of seconds — a
#: calendar belongs to the windows work, never to a duration (ADR-0033).
DURATION_UNITS = {"s": 1, "m": 60, "h": 3600, "d": 86400, "w": 604800}


def parse_duration(value: object, default: int) -> int:
    """Parse a duration into whole seconds.

    Accepts a number (seconds) or a string with an optional unit suffix —
    ``s`` seconds, ``m`` minutes, ``h`` hours, ``d`` days, ``w`` weeks (e.g.
    ``"15m"``, ``"2w"``). Units are lowercase: ``5H`` is refused, and ``6M`` is
    refused by name, because it used to read as six *minutes* to somebody who
    meant six months. A missing value returns ``default``.
    """
    if value is None:
        return default
    if isinstance(value, (int, float)):
        return int(value)
    text = str(value).strip()
    if not text:
        return default
    if text[-1] in DURATION_UNITS:
        number, factor = text[:-1], DURATION_UNITS[text[-1]]
    else:
        number, factor = text, 1
    try:
        return int(float(number) * factor)
    except ValueError as exc:
        if text[-1] == "M":
            raise CheckError(
                f"invalid duration: {value!r} — M is not a unit: m is minutes, "
                f"and a month has no fixed length, so write it in weeks or days "
                f"(26w, 180d)") from exc
        raise CheckError(f"invalid duration: {value!r}") from exc


def coerce_code(value: object, default: StatusCode = StatusCode.ERROR) -> StatusCode:
    """Coerce a config value into a StatusCode (case-insensitive name)."""
    if value is None:
        return default
    if isinstance(value, StatusCode):
        return value
    text = str(value).upper()
    if text not in StatusCode.__members__:
        raise CheckError(f"invalid status code: {value!r}")
    return StatusCode[text]


def parse_secret_refs(config: dict[str, Any], *names: str) -> dict[str, str]:
    """Parse a check config's ``secrets:`` block into ``name -> reference``.

    Every credential a check needs is named in this one block, so the references
    sit where a reader looks for them and no ordinary config field ever has to be
    read as "is this a value or the name of one?" (ADR-0023). Each of ``names``
    is **required** — a check that needs a credential says which one, rather than
    inheriting a hard-coded default that quietly ties every instance of the type
    to the same secret; an unrecognized key is a typo and fails the load.

    The values are **references**, not secrets: resolve them with
    :meth:`Check.resolve_secret` from the constructor (this hook is a classmethod;
    resolution needs the instance) and never during a run. No error here quotes a
    value — the field may hold a pasted credential.
    """
    wanted = ", ".join(names)
    block = config.get("secrets")
    if block is None:
        raise CheckError(
            f"check config must define a 'secrets:' block naming: {wanted}")
    if not isinstance(block, dict):
        raise CheckError(
            "'secrets' must be a mapping of name -> secret reference "
            f"(expected: {wanted})")
    unknown = sorted(str(key) for key in block if str(key) not in names)
    if unknown:
        raise CheckError(
            f"unknown key(s) in 'secrets': {', '.join(unknown)} "
            f"(this check takes: {wanted})")
    references: dict[str, str] = {}
    for name in names:
        value = block.get(name)
        if not isinstance(value, str) or not value.strip():
            raise CheckError(
                f"'secrets.{name}' must be a secret reference such as "
                "'env://GITHUB_TOKEN' or 'aws-sm://team/token' — where the "
                "secret lives, never the secret itself")
        references[name] = value.strip()
    return references


# ``plain`` is defined beside the entry it escapes for (``little_sister.reasons``),
# where the modules beneath the check layer can reach it too — a configuration
# loader folding a path into a self-report line needs it as much as a check does.
# The promised name stays this one (architecture.md §11).
plain = _plain


def code(text: object) -> str:
    """Wrap captured output as a Markdown **code block** so it renders verbatim and
    inert (ADR-0018). The fence is longer than any backtick run in ``text``."""
    longest = run = 0
    for ch in str(text):
        run = run + 1 if ch == "`" else 0
        longest = max(longest, run)
    fence = "`" * max(3, longest + 1)
    return f"{fence}\n{text}\n{fence}"


def config_markdown(fields: dict[str, str | None]) -> str:
    """Render an allow-list of ``label -> value`` config fields as a Markdown
    bullet list (ADR-0013), in declaration order. Empty / ``None`` values are
    dropped, so a check can list optional fields without emitting blanks. The
    result is rendered as Markdown (ADR-0018), so a value carrying Markdown
    punctuation is interpreted — fold it through :func:`plain` first where it is
    not operator-authored."""
    lines = [f"- **{label}:** {value}"
             for label, value in fields.items() if value]
    return "\n".join(lines)
