"""The self-report seam: what this instance says about itself (ADR-0071).

``/little-sister`` is the engine's own node — the heartbeat the dashboard draws as
its status strip (ADR-0056) — and until this seam it could say exactly one thing,
fixed at construction: that no checks are configured. Everything else the process
knows about its own state stayed in the log. Now anything with something to say
registers a **contributor** here, every scheduler tick asks each one for its
current lines, and the beat carries the worst of them.

Four rules, which are the whole design risk because this runs on the scheduler
thread:

* **A report is recorded state, read — never a probe.** A contributor returns what
  it already knows; it does not open a socket, touch a bucket or stat a file to
  find out. A contributor that measures would make the heartbeat wait on the
  thing it is reporting about.
* **A contributor that raises is caught and named.** The beat still lands, with a
  line saying which report could not be read; one broken contributor cannot stall
  or crash a tick.
* **Every line carries a stable slug**, namespaced by the contributor —
  ``<name>.<slug>`` — so it is pinnable like any other entry (ADR-0036) and
  re-wording a line does not move the pin.
* **A report clears.** A line is a condition that holds now; a contributor that
  stops returning it has said so, and the node's own status follows its lines
  (ADR-0042). Nothing here is remembered on behalf of a contributor.

Registration happens in the same import-before-app slot the check types, the slot
fillers and the secret resolvers use, and follows the resolver's rules (ADR-0064): the
registering package is inferred from the call site, a name is claimed once, and a
second claim from another package refuses at startup unless it says
``replace=True``. Nothing here depends on that timing — the engine reads the
registry on every tick, so a late registration (a test's) is honored too.

**Two records, for the two shapes a warning about this process takes**, so that
the log and the node cannot drift apart: each records the line and writes the log
entry in one call, and a call site that has one has the other. :class:`Standing`
is for what the process learned at startup and cannot undo — a setting it could
not honor, a door that is shut — which stands for the life of the process, and
:data:`startup` is the one the library keeps for that. :class:`Held` is for what
recurs — a renderer that raised, a probe that timed out — kept for a window after
each occurrence, so the line stands while the condition does and clears when it
stops, with a count instead of a repetition. Nobody reads the log unless something
says there is something to read; the node is that something.
"""
from __future__ import annotations

import logging
import re
import threading
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass, replace

from little_sister.codes import StatusCode
from little_sister.logger import logger
from little_sister.origins import calling_package
from little_sister.reasons import Entry, plain
from little_sister.secrets import UNIDENTIFIED

#: A contributor answers with its current lines — recorded state, never a probe.
#: Each line's text is Markdown (ADR-0018): a contributor folding in external text
#: (a path, an error message) escapes it with :func:`little_sister.checks.plain`.
#: **Every line carries a code** (ADR-0076): a line is a claim about this process.
#: What carries none — who holds a lease, what was set aside, what was searched —
#: is a fact, and a fact is the contributor's **report** below.
Contributor = Callable[[], Sequence[Entry]]

#: A contributor's report: what it *knows*, as Markdown, shown on its child's page
#: and never on a card, and never a status claim (ADR-0044 decision 6) — anything
#: that should alarm is a line. Recorded state, never a probe, like the lines.
ContributorReport = Callable[[], str]

#: A contributor's name is one slug segment: it is joined to each line's slug with a
#: dot, so it carries none itself.
_NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]*\Z")

#: The slug of the line that stands in for a contributor's report when the
#: contributor raised or answered with something that is not a line.
RAISED_SLUG = "raised"


class ContributorConflictError(RuntimeError):
    """Two packages claim one contributor name, and neither said it meant to
    replace the other. Raised from :func:`register_contributor` — that is, from the
    application's import-before-app block, so the process does not start, the way
    a second claim on a secret scheme does not (ADR-0064)."""


@dataclass(frozen=True)
class Registration:
    """One claimed contributor name: who answers for it, and whom that displaced."""
    name: str
    contributor: Contributor
    #: The package that registered it, inferred from the call site — ``""`` where
    #: the caller could not be identified.
    package: str
    #: The package this claim deliberately replaced, or ``""``.
    replaced: str = ""
    #: What the contributor's node is called and what it is about — the labels the
    #: child of ``/little-sister`` wears (ADR-0076), filled the way a check type's
    #: subnode prose is (C2): a ``nodes.yaml`` declaration for the path still wins.
    title: str = ""
    about: str = ""
    #: The contributor's report — its facts, as Markdown — or ``None`` for a
    #: contributor with nothing but lines to say (ADR-0076).
    report: ContributorReport | None = None

    @property
    def owner(self) -> str:
        """The registering package as a page or a message should say it."""
        return self.package or UNIDENTIFIED


@dataclass(frozen=True)
class Report:
    """One contributor's current lines and report, as its node carries them: the
    slugs are the contributor's own, because the path carries the name, and every
    line carries a code (ADR-0076); ``report`` is the contributor's facts as
    Markdown, the node's `report` field (ADR-0044 decision 6), ``""`` for none."""

    name: str
    title: str
    about: str
    lines: tuple[Entry, ...]
    report: str = ""


_contributors: dict[str, Registration] = {}


def register_contributor(name: str, contributor: Contributor, *,
                         title: str = "", about: str = "",
                         report: ContributorReport | None = None,
                         replace: bool = False) -> None:
    """Register ``contributor`` under ``name`` — the child of ``/little-sister``
    its lines appear on (ADR-0076), and the prefix of every slug in
    :func:`current_lines`.

    ``title`` and ``about`` are the node's labels, declared here the way a check
    type declares its subnode prose (C2), and a deployment's ``nodes.yaml`` still
    wins for the path. ``report`` answers the contributor's **facts** as Markdown
    — the child's `report` field, shown on its page and never on a card
    (ADR-0044 decision 6) — so that its lines can be what a line is: a claim with
    a code. A line without one is refused on the tick into a WARN that says so.

    A name is claimed **once**. Re-registering from the *same* package replaces
    the contributor silently, because a registration module may be imported more
    than once and refusing that would refuse a reloading server. A claim on a name
    **another** package holds raises :class:`ContributorConflictError` naming both:
    a line's path and slug are what a pin is written against, and two contributors
    behind one name would let import order decide what a pin silences.
    ``replace=True`` is how a replacement is done on purpose, and it is recorded
    and shown rather than silently indistinguishable from a first claim.
    """
    if not _NAME.match(name):
        raise ValueError(
            f"a contributor name is one slug segment (letters, digits, '_' and "
            f"'-'), not {name!r}")
    package = calling_package()
    claimed = _contributors.get(name)
    replaced = ""
    if claimed is not None:
        if claimed.package == package:
            replaced = claimed.replaced
        elif not replace:
            raise ContributorConflictError(
                f"two packages claim the self-report name '{name}': "
                f"{claimed.owner} registered it and {package or UNIDENTIFIED} "
                f"claims it too. The name prefixes every slug a pin is written "
                f"against, so import order must not be what decides it — rename "
                f"it in one of them, or pass replace=True where replacing the "
                f"other is the point (ADR-0071).")
        else:
            replaced = claimed.package
    _contributors[name] = Registration(name=name, contributor=contributor,
                                       package=package, replaced=replaced,
                                       title=title, about=about, report=report)


def registered_contributors() -> tuple[Registration, ...]:
    """Every claimed name with the package that answers for it, in registration
    order — which is the order their lines appear in on the node."""
    return tuple(_contributors.values())


def forget_contributors() -> None:
    """Empty the registry (tests)."""
    _contributors.clear()


def current_reports() -> tuple[Report, ...]:
    """Every contributor's current lines, one :class:`Report` per contributor in
    registration order, the slugs the contributor's own — what the engine writes
    onto ``/little-sister/<name>`` every tick (ADR-0076).

    Called on the scheduler tick, so it never lets a contributor take the tick
    down: one that raises, or answers with something that is not a sequence of
    lines, is logged and stands in its report as one WARN line saying so — a report
    that could not be read is not a report that said nothing. The contributor's
    ``report`` is read the same way, and a report that raised is the same stand-in
    beside the lines that were read, with an empty report.

    **Every line carries a code.** A line without one is a fact that belongs in the
    report, and it arrives on the child as a WARN under its own slug saying so —
    a defect made visible where somebody looks, rather than a fact that would
    silently carry the node's code into the roll-up (ADR-0076 decision 1).
    """
    reports: list[Report] = []
    for registration in tuple(_contributors.values()):
        name = registration.name
        try:
            reported = list(registration.contributor())
        except Exception as error:
            logger.exception("self-report: the %s contributor raised", name)
            reported = [_stand_in(name, f"raised {error!r}")]
        else:
            if not all(isinstance(entry, Entry) for entry in reported):
                logger.error("self-report: the %s contributor answered with "
                             "something that is not a sequence of lines", name)
                reported = [_stand_in(name, "answered with something that is not "
                                            "a sequence of lines")]
            else:
                reported = [_coded(name, entry) for entry in reported]
        text = ""
        if registration.report is not None:
            try:
                answer = registration.report()
            except Exception as error:
                logger.exception("self-report: the %s report raised", name)
                reported.append(_stand_in(name, f"report raised {error!r}"))
            else:
                if isinstance(answer, str):
                    text = answer
                else:
                    logger.error("self-report: the %s report answered with "
                                 "something that is not text", name)
                    reported.append(_stand_in(
                        name, "report answered with something that is not text"))
        reports.append(Report(name=name, title=registration.title,
                              about=registration.about, lines=tuple(reported),
                              report=text))
    return tuple(reports)


def current_lines() -> tuple[Entry, ...]:
    """Every contributor's current lines in one sequence, each slug prefixed with
    the contributor's name — the shape one node carried before the contributors
    had nodes of their own. Kept for a reader that wants the whole report flat."""
    return tuple(replace(entry, slug=f"{report.name}.{entry.slug}")
                 for report in current_reports() for entry in report.lines)


def _stand_in(name: str, what: str) -> Entry:
    return Entry(RAISED_SLUG,
                 plain(f"the {name} report could not be read: it {what}"),
                 code=StatusCode.WARN)


def _coded(name: str, entry: Entry) -> Entry:
    """The entry as the child carries it: as it is where it carries a code, and
    a WARN under its own slug saying what is wrong where it does not — the slug
    kept so a pin written against it still holds."""
    if entry.code is not None:
        return entry
    logger.error("self-report: the %s contributor wrote the line %r without a "
                 "code; a fact belongs in its report (ADR-0076)", name, entry.slug)
    # The line's own text is Markdown already; only the slug is folded in.
    return replace(entry, code=StatusCode.WARN, text=(
        f"the {name} contributor wrote `{plain(entry.slug)}` without a code — "
        f"\u201c{entry.text}\u201d — a line is a claim and carries one; a fact "
        f"belongs in its report"))


# --- actions ---

#: What an action does when an admin asks: runs, and answers with the sentence
#: the page shows afterwards — ``""`` for nothing worth saying. Whatever it raises
#: is caught by the route and shown as the sentence instead. A handler runs between
#: two flushes of the state layer (ADR-0076 decision 6, ADR-0134 decision 6): the one
#: before it sends what the process holds while a keeper's lease is still its own, so
#: a handler may give the lease up; the one after a handler that returned sends what
#: it changed, now, so its sentence may say so.
ActionHandler = Callable[[], str | None]


@dataclass(frozen=True)
class Action:
    """One thing an admin may do to a contributor's node — *take over the lease*,
    *release it* — offered as a button on ``/little-sister/<contributor>`` and run
    by ``POST /little-sister/<contributor>/act/<slug>`` (ADR-0076)."""

    contributor: str
    slug: str
    label: str
    handler: ActionHandler
    #: The package that registered it, inferred from the call site.
    package: str

    @property
    def owner(self) -> str:
        return self.package or UNIDENTIFIED


class ActionConflictError(RuntimeError):
    """Two packages register one action on one contributor, and neither said it
    meant to replace the other. Raised from the import-before-app block."""


_actions: dict[tuple[str, str], Action] = {}


def register_action(contributor: str, slug: str, label: str,
                    handler: ActionHandler, *, replace: bool = False) -> None:
    """Offer ``handler`` as a button labelled ``label`` on the ``contributor``'s
    node, run by an admin. The contributor need not be registered yet — a package
    registers both in its import-before-app block, in either order — but the
    button appears only on a node that exists. Claimed once, under the same rules
    as a contributor name."""
    if not _NAME.match(contributor):
        raise ValueError(f"a contributor name is one slug segment, not "
                         f"{contributor!r}")
    if not _NAME.match(slug):
        raise ValueError(f"an action slug is one slug segment, not {slug!r}")
    if not label.strip():
        raise ValueError("an action needs a label")
    package = calling_package()
    key = (contributor, slug)
    claimed = _actions.get(key)
    if claimed is not None and claimed.package != package and not replace:
        raise ActionConflictError(
            f"two packages register the action '{slug}' on '{contributor}': "
            f"{claimed.owner} registered it and {package or UNIDENTIFIED} claims it "
            f"too — rename it in one of them, or pass replace=True where replacing "
            f"the other is the point.")
    _actions[key] = Action(contributor=contributor, slug=slug, label=label.strip(),
                           handler=handler, package=package)


def actions_for(contributor: str) -> tuple[Action, ...]:
    """The actions offered on ``contributor``'s node, in registration order."""
    return tuple(action for action in _actions.values()
                 if action.contributor == contributor)


def find_action(contributor: str, slug: str) -> Action | None:
    """The action the route was asked for, or ``None``."""
    return _actions.get((contributor, slug))


def forget_actions() -> None:
    """Empty the action registry (tests)."""
    _actions.clear()


# --- the two records ---

_LEVELS = {StatusCode.ERROR: logging.ERROR, StatusCode.WARN: logging.WARNING}


def _log(slug: str, text: str, code: StatusCode) -> None:
    """The log half of a record: the line's own severity, INFO below WARN."""
    logger.log(_LEVELS.get(code, logging.INFO), "%s: %s", slug, text)


class Standing:
    """Lines that stand for the life of the process.

    What the process learned at startup and cannot undo: a setting written and not
    honored, a credential reference that did not resolve, a door nobody can enter.
    Each is a condition that holds until a restart — the seam's own test — and each
    used to be one log line, read by nobody. :meth:`note` records it and logs it in
    the same call, so a call site that has the one has the other.

    One line per slug: a second note with the same slug replaces the first, which
    is what a condition that was re-measured wants and what a condition that
    repeats does not — that one is :class:`Held`. Slugs are stable keys, pinnable
    as ``<contributor>.<slug>``; a re-worded text does not move a pin.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._lines: dict[str, Entry] = {}

    def note(self, slug: str, text: str, *, code: StatusCode = StatusCode.WARN,
             log: bool = True) -> None:
        """Record ``text`` under ``slug`` for the life of the process, and log it
        at the line's own severity. A line is a claim and carries a code; a fact
        that colours nothing is the contributor's report, not a note (ADR-0076)."""
        with self._lock:
            self._lines[slug] = Entry(slug, text, code=code)
        if log:
            _log(slug, text, code)

    def lines(self) -> tuple[Entry, ...]:
        """Every note, in the order it was taken. Recorded state, read."""
        with self._lock:
            return tuple(self._lines.values())

    def forget(self) -> None:
        """Empty the record (tests)."""
        with self._lock:
            self._lines.clear()


@dataclass(frozen=True)
class Occurrence:
    """One time a held condition was seen."""

    slug: str
    text: str
    code: StatusCode
    #: What was measured when it was seen, where the condition has a size — how
    #: late a tick came, how long a probe took — so the worst inside the window can
    #: be the one the line reports. ``None`` where it has none.
    measure: float | None
    #: The clock's reading when it was seen.
    at: float


class Held:
    """Occurrences of conditions that recur, each held for a window after it was
    seen, so a line stands while the condition does and clears when it stops.

    The shape the engine's own *late tick* line already had, made shareable: a
    renderer that raises on every request, a login that fails — each is one
    :meth:`see` per occurrence, logged and recorded
    in the same call, and one line while any occurrence is inside the window,
    carrying a count rather than a repetition. What the line says is the
    contributor's: :meth:`lines` writes a plain one — the latest text, and *n
    times in the last …* where there was more than one — and a contributor that
    wants its own sentence reads :meth:`worst`, :meth:`latest` and :meth:`count`
    and writes it.

    The clock is monotonic and injectable, and every method takes ``now`` so a
    caller that has the engine's clock in hand gives it rather than reading a
    second one.
    """

    def __init__(self, hold_seconds: float, *,
                 clock: Callable[[], float] = time.monotonic) -> None:
        self._hold = max(0.0, float(hold_seconds))
        self._clock = clock
        self._lock = threading.Lock()
        self._seen: list[Occurrence] = []

    @property
    def hold_seconds(self) -> float:
        return self._hold

    def see(self, slug: str, text: str, *,
            code: StatusCode = StatusCode.WARN,
            measure: float | None = None, now: float | None = None,
            log: bool = True) -> None:
        """One occurrence: recorded under ``slug`` for the window, and logged at
        the line's own severity. A line is a claim and carries a code; a fact is
        the contributor's report (ADR-0076)."""
        at = self._clock() if now is None else now
        with self._lock:
            self._seen.append(Occurrence(slug, text, code, measure, at))
            self._prune(at)
        if log:
            _log(slug, text, code)

    def prune(self, now: float | None = None) -> None:
        """Drop what has left the window."""
        with self._lock:
            self._prune(self._clock() if now is None else now)

    def _prune(self, now: float) -> None:
        # Call only while holding the lock. A clock that went backwards keeps
        # everything: the alternative is a window that empties on a clock step.
        self._seen = [seen for seen in self._seen if now - seen.at <= self._hold]

    def _inside(self, slug: str, now: float | None) -> list[Occurrence]:
        at = self._clock() if now is None else now
        with self._lock:
            self._prune(at)
            return [seen for seen in self._seen if seen.slug == slug]

    def count(self, slug: str, now: float | None = None) -> int:
        """How many occurrences of ``slug`` are inside the window."""
        return len(self._inside(slug, now))

    def latest(self, slug: str, now: float | None = None) -> Occurrence | None:
        """The most recent occurrence inside the window, or ``None``."""
        inside = self._inside(slug, now)
        return inside[-1] if inside else None

    def worst(self, slug: str, now: float | None = None) -> Occurrence | None:
        """The occurrence with the largest measure inside the window — the latest
        of them on a tie, and the latest of all where none has a measure."""
        inside = self._inside(slug, now)
        if not inside:
            return None
        measured = [seen for seen in inside if seen.measure is not None]
        if not measured:
            return inside[-1]
        best = max(seen.measure for seen in measured if seen.measure is not None)
        return [seen for seen in measured if seen.measure == best][-1]

    def slugs(self, now: float | None = None) -> tuple[str, ...]:
        """Every slug with an occurrence inside the window, first seen first."""
        at = self._clock() if now is None else now
        with self._lock:
            self._prune(at)
            ordered: dict[str, None] = {}
            for seen in self._seen:
                ordered.setdefault(seen.slug, None)
            return tuple(ordered)

    def lines(self, now: float | None = None) -> tuple[Entry, ...]:
        """The plain line per slug: the latest text, with the count where there
        was more than one occurrence in the window. Recorded state, read."""
        from little_sister.spans import format_duration
        lines: list[Entry] = []
        for slug in self.slugs(now):
            latest = self.latest(slug, now)
            if latest is None:
                continue
            seen = self.count(slug, now)
            text = latest.text
            if seen > 1:
                text = (f"{text} — {seen} times in the last "
                        f"{format_duration(max(1, round(self._hold)))}")
            lines.append(Entry(slug, text, code=latest.code))
        return tuple(lines)

    def forget(self) -> None:
        """Empty the record (tests)."""
        with self._lock:
            self._seen.clear()


#: The library's standing record: what this process learned at startup and cannot
#: undo, reported under the contributor name ``startup``. A call site anywhere in
#: the library notes into it; the application registers it beside the state layer
#: and the readiness answer.
startup = Standing()

#: How long a recurring failure is held after it was last seen, and a security
#: event with it. Ten minutes is the engine's own window for a late tick: long
#: enough that a condition recurring every few minutes reads as one line, short
#: enough that one that stopped is gone before anybody stops believing the page.
HOLD_SECONDS = 600.0

#: The library's held record for what recurs at runtime — a renderer that raised,
#: a probe that failed, an upsert that did not land — reported under ``runtime``.
runtime = Held(HOLD_SECONDS)

#: The library's held record for security events — a failed login, the
#: system-admin account used, a policy violation reported — under ``security``,
#: graded by :func:`security_lines` rather than by the plain line, because one
#: failed login is nothing and a burst of them is a line.
security = Held(HOLD_SECONDS)

#: Failed logins inside the window at which the ``security`` report grades WARN.
FAILED_LOGINS_WARN = 5

#: The slug every failed login is seen under, whichever door refused it.
FAILED_LOGIN = "login.failed"


def security_lines() -> tuple[Entry, ...]:
    """The ``security`` contributor's lines: failed logins as a **rate** — a WARN
    line from :data:`FAILED_LOGINS_WARN` inside the window, and below that no
    line at all but :func:`security_report` — and every other event as the line
    the record writes. Recorded state, read."""
    lines: list[Entry] = []
    failed = security.count(FAILED_LOGIN)
    if failed >= FAILED_LOGINS_WARN:
        lines.append(Entry(FAILED_LOGIN, _failed_logins(failed), code=StatusCode.WARN))
    lines.extend(line for line in security.lines() if line.slug != FAILED_LOGIN)
    return tuple(lines)


def security_report() -> str:
    """The ``security`` contributor's report (ADR-0044 decision 6, ADR-0076): a
    few failed logins are a fact worth knowing and not a claim — below the rate
    they are said here, on the child's page, and not as a line."""
    failed = security.count(FAILED_LOGIN)
    if not failed or failed >= FAILED_LOGINS_WARN:
        return ""
    return _failed_logins(failed)


def _failed_logins(failed: int) -> str:
    latest = security.latest(FAILED_LOGIN)
    last = f" — the last {latest.text}" if latest is not None else ""
    from little_sister.spans import format_duration
    window = format_duration(max(1, round(security.hold_seconds)))
    return (f"{failed} failed login{'s' if failed != 1 else ''} in the last "
            f"{window}{last}")
