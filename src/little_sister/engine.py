"""The monitoring engine: schedule checks and write their results to the tree.

One process runs one engine (ADR-0001). A scheduler thread submits *due* checks
to a bounded thread pool. A run is **two steps** (ADR-0086): the check
:meth:`~little_sister.checks.Check.measure`\\ s its object and hands back a
record, then :meth:`~little_sister.checks.Check.grade`\\ s that record into the
result this module upserts into the shared status tree. What is released is a
**unit** (ADR-0078, ADR-0130): one schedule entry per unit a check declares, each on
its own period, measured alone through
:meth:`~little_sister.checks.Check.measure_unit`; the check is then graded whole
over the newest reading of every unit, and the unit's own path — the containers
above it and the node it answers for — is written and stamped, nothing beside it.
A check that declares no units is one unit, released once per period, which is the
check as it always ran. A check that raises or
times out becomes ``ERROR`` (ADR-0040) — and where the *measurement* is what
raised, the engine writes the failure record itself, so no author can forget to
record a reading that failed. One whose secret references failed to resolve at
construction is **pinned** to ERROR without running (ADR-0023). A reading that
names its subject is then kept in that subject's series, where the check keeps
one (ADR-0087). Threads are daemons; ``start``/``stop`` are idempotent.

**A stop ends at its save** (ADR-0088). The pool is the engine's own, of daemon
threads the interpreter does not join — the standard pool's exit hook joins every
thread it started, whatever its flag, and held the process for the check in flight.
A stop abandons the runs in flight, drops what they deliver afterwards, ends every
process they started, says once what it abandoned, and makes the one final save.
"""
from __future__ import annotations

import copy
import gc
import json
import threading
import time
import traceback
import zlib
from collections import Counter
from collections.abc import Callable, Iterator, Mapping, Sequence
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field, replace
from datetime import date, datetime, timedelta
from functools import partial
from typing import Any

from little_sister import first_look, instants, process, self_report
from little_sister.checks import (
    Check,
    CheckError,
    CheckResult,
    Measurement,
    Unit,
    checks_dirs,
    code,
    load_checks,
    parse_duration,
    plain,
)
from little_sister.checks.output import FAILURE_BYTES, failure_text
from little_sister.codes import RANKED, worst_of
from little_sister.config import config
from little_sister.grading import Grading
from little_sister.limits import (
    COLLECTION_SPACING,
    MEMORY_LINE_MINUTES,
    RISE_LOGGED,
    EngineReport,
    LateRun,
    Left,
    Limits,
    Resident,
    SeriesHeld,
    Waiting,
    capacity,
    collection_text,
    killed_text,
    machine_left,
    resident_size,
    rise_text,
    stall_text,
)
from little_sister.line_template import Declarations
from little_sister.logger import logger
from little_sister.nodes import ABOUT_NOTED_PAST, NodeMeta, note_long_about
from little_sister.pool import DaemonPool
from little_sister.readiness import Outcomes
from little_sister.reasons import Entry, Refusal, derive_code, lenient_records, slug
from little_sister.series import (
    MemoryStore,
    Placed,
    SeriesKey,
    SeriesRecord,
    Swept,
)
from little_sister.spans import format_duration
from little_sister.state import StateLayer
from little_sister.status import (
    HEARTBEAT_PATH,
    StatusCode,
    effective_code,
    join_path,
    leaf_name,
    split_path,
)
from little_sister.tree import StatusTree, stale_after_seconds, status_tree

# Innermost frames kept when a failing check's trace goes onto its node
# (`stacktrace` in config/settings.yaml). The cause is almost always in the last
# few, and a node reason is not a log file — the whole trace stays in the log.
TRACEBACK_FRAMES = 5

#: How much of a run's reasons the per-run log line carries.
#:
#: It used to be the **first reason, cut at 120 characters**, and both halves of
#: that were wrong at the one moment the line is read. A check that could not
#: measure at all words its refusal in two reasons on purpose — what went wrong,
#: then what to do about it — because the second half is the actionable one and a
#: cloud provider's error is long enough to push it off the edge of a card. The
#: log kept the first and dropped the second, then cut the first mid-sentence: a
#: real `AssumeRole` refusal ended at "…when calling the AssumeRole operation:",
#: exactly before the part naming who was refused and for what.
#:
#: So: every reason, and a cap generous enough that a provider's message arrives
#: whole. It is still a cap — a check with a hundred coded lines must not put all
#: of them on one line — and what it truncates now is a *roster*, where the first
#: entries are representative, rather than a single sentence's tail.
DETAIL_LIMIT = 1200

#: What joins the reasons of one run into that line. Not a newline: one run is
#: one record, and a log a reader greps by check path must not have its answer
#: split across lines that no longer carry it.
DETAIL_SEPARATOR = " | "

#: The most the **failure record** the engine builds for a check that raised can
#: weigh, in the bytes the seam counts: the `{"error": …}` skeleton as `json.dumps`
#: writes it, less the empty string's own quotes — which `FAILURE_BYTES` already
#: counts — plus the message at the most :func:`failure_text` lets it cost. The
#: message is clipped by that helper, to the budget `http`, `file` and `command`
#: clip their own failures to (ADR-0086 decisions 5 and 7), so this is a ceiling
#: and not a measurement. It is also the **floor** under every record size a type
#: declares (`capacity(record_floor=…)`, ADR-0086 decision 5): any check that
#: declares a record may raise, and the record it then leaves is this one.
FAILURE_RECORD_BYTES = (len(json.dumps({"error": ""})) - len('""')
                        + FAILURE_BYTES)

# The worker ceiling is `DEFAULT_MAX_WORKERS` in `limits`, beside the other
# numbers the engine measures itself against and beside the setting that
# overrides it; `Engine` reads it through `config` like the rest of them.
DEFAULT_POLL_INTERVAL = 1.0
# The period a schedule entry built without a unit carries: the library's own
# default frequency, so a bare `_Scheduled(check, now)` in a test is the one-unit
# check it was before units existed.
DEFAULT_PERIOD = 900
# The spread window for check start times: every check still runs in the first
# sweep, but its schedule is phase-shifted once, at the first re-arm, by a
# stable per-check offset within min(frequency, this) — so equal-frequency
# checks don't fire in one tick forever (all SSH sessions at once, every LCM
# beat), and a fast check never waits longer than its own period.
STAGGER_WINDOW_SECONDS = 60.0

# The engine's self-monitoring node: it heartbeats HEARTBEAT_PATH (reserved —
# see status.py; the dashboard renders it as the status strip, ADR-0024) every
# scheduler tick, so a dead scheduler shows up stale and degraded (ADR-0005).
# The beat carries what the instance says about itself — the engine's own lines
# and every registered contributor's (ADR-0072) — as pinnable entries whose
# codes derive the node's own (ADR-0042).
HEARTBEAT_DESCRIPTION = "little-sister monitoring engine — beats every scheduler tick"
# The engine's own lines live on this child of the heartbeat, as a contributor's
# live on the child that carries its name (ADR-0076).
ENGINE_REPORT = "engine"
ENGINE_TITLE = "Engine"
ENGINE_ABOUT = (
    "What the engine measures about itself against its limits as it runs — the "
    "entries held, the resident size, the pool, the scheduler's lag, a run that "
    "outgrew its period — and the configuration it could not serve. Recorded on "
    "its side and read on the tick, never probed (ADR-0072)."
)
# What every child of the heartbeat says on its hover card, after its own `about`.
CHILD_DESCRIPTION = "what this instance says about itself — one contributor's report"
# Default `about` for the heartbeat, so the dashboard strip explains itself in
# the hover card (ADR-0019) out of the box. Seeded at engine construction —
# before the startup nodes.yaml pass, whose declaration simply overwrites it
# (ADR-0012 precedence).
HEARTBEAT_ABOUT = (
    "The engine's own heartbeat — re-asserted every scheduler tick. "
    "**Stale** here means the scheduler itself has stalled (ADR-0005)."
)


def _stagger(check: Check, unit: Unit | None = None) -> float:
    """The check's personal schedule phase within
    ``min(frequency, STAGGER_WINDOW_SECONDS)``, applied once at the first
    re-arm. Derived from a digest of path *and* type — two checks may share a
    root node (e.g. host-metrics + macos-memory on one host) and those want
    separating most — and deterministic across restarts (crc32, not the
    per-process-salted ``hash``), so the relative spread is reproducible.

    A declared unit has a phase of its own (ADR-0130): the window is its own
    period's, and its key joins the digest, so two units of one check spread as two
    checks do. The anonymous unit of a one-unit check digests what the check always
    did, so nothing moves for it."""
    period = check.frequency_seconds if unit is None else unit.period_seconds
    window = min(float(period), STAGGER_WINDOW_SECONDS)
    text = f"{check.path}\0{check.type_name}"
    if unit is not None and unit.key:
        text += f"\0{unit.key}"
    digest = zlib.crc32(text.encode())
    return (digest % 1000) / 1000.0 * window


def _units_of(check: Check) -> tuple[Unit, ...]:
    """What ``check`` declares it reads on slots of its own (ADR-0130 decision 1),
    checked as the engine needs it — a declaration the schedule could not honor is
    a refusal to start naming the check (ADR-0051), never a degraded page.

    A check that declares none answers one anonymous unit, and that is every check
    that existed before units did. A check that declares its own gives every unit a
    key, overrides ``measure_unit`` to read one, declares each node once and none
    beneath another's — a node written by two units' runs would carry two stamps of
    one look, which is what decision 4 refuses."""
    try:
        units = tuple(check.units())
    except Exception as error:
        raise CheckError(
            f"check {check.path}: units() raised ({error!r})") from error
    if not units:
        raise CheckError(
            f"check {check.path}: declares no unit at all — a check that declares "
            f"none answers one, so an empty declaration is a defect of the type")
    anonymous = len(units) == 1 and units[0].key == "" and units[0].node == ""
    if anonymous:
        return units
    for unit in units:
        if not unit.key:
            raise CheckError(
                f"check {check.path}: a declared unit needs a key of its own; one "
                f"answering for {unit.node!r} has none")
    if type(check).measure_unit is Check.measure_unit:
        raise CheckError(
            f"check {check.path}: declares {len(units)} unit(s) and no "
            f"measure_unit() that reads one")
    seen_keys: dict[str, Unit] = {}
    seen_nodes: dict[str, Unit] = {}
    for unit in units:
        if unit.key in seen_keys:
            raise CheckError(
                f"check {check.path}: declares the unit {unit.key!r} twice")
        seen_keys[unit.key] = unit
        if unit.node in seen_nodes:
            raise CheckError(
                f"check {check.path}: the units {seen_nodes[unit.node].key!r} and "
                f"{unit.key!r} both answer for the node {unit.node!r}")
        seen_nodes[unit.node] = unit
    for unit in units:
        for other in units:
            if other is unit or other.node == unit.node:
                continue
            if other.node == "" or unit.node.startswith(other.node + "/"):
                raise CheckError(
                    f"check {check.path}: the unit {unit.key!r} answers for "
                    f"{unit.node!r}, beneath the node {other.node!r} the unit "
                    f"{other.key!r} answers for — a node is written by one unit's "
                    f"run")
    return units


@dataclass(frozen=True)
class _UnitView:
    """A declared unit as the limits' arithmetic reads a check
    (:mod:`little_sister.limits` is duck-typed on these names): its node's path,
    its own period, the check's timeout, and what one run of it costs. The check's
    entries and record are declared once, on its first unit's view, so the sums
    count them once; a one-unit check is handed to the arithmetic as itself."""

    path: str
    frequency_seconds: int
    timeout_seconds: float
    cost_seconds: float | None
    check: Check | None

    def expected_cost(self) -> float | None:
        return self.cost_seconds

    def expected_entries(self) -> int | None:
        return None if self.check is None else self.check.expected_entries()

    def expected_record(self) -> int | None:
        return None if self.check is None else self.check.expected_record()


def _views(check: Check, units: Sequence[Unit]) -> list[object]:
    """What the limits read of ``check``: the check itself where it is one unit,
    and otherwise one view per declared unit (ADR-0130 decision 5 — the startup
    sum takes each unit's cost over its own period, and a timeout longer than a
    unit's period is that unit's warning)."""
    if len(units) == 1 and units[0].key == "":
        return [check]
    return [_UnitView(join_path(check.path, unit.node), unit.period_seconds,
                      check.timeout_seconds, unit.cost_seconds,
                      check if index == 0 else None)
            for index, unit in enumerate(units)]


def _retry_settings(check: Check) -> tuple[int, int]:
    """The effective failure-retry settings for ``check`` (ADR-0033): the
    per-check fields when set, else the ``settings.yaml`` defaults. The
    settings-level interval is a duration string parsed here, where a bad value
    can fall back with a warning instead of failing engine construction —
    ``config.py`` stays free of the duration parser on purpose."""
    interval = check.retry_interval_seconds
    if interval is None:
        try:
            interval = parse_duration(config.retry_interval or None, 0)
        except CheckError:
            self_report.startup.note(
                "retry-interval",
                plain(f"retry_interval {config.retry_interval!r} is not a duration; "
                      f"the failure retry stays off"))
            interval = 0
    attempts = (check.retry_attempts if check.retry_attempts is not None
                else config.retry_attempts)
    return max(0, interval), max(0, attempts)


def _escalate_after(check: Check) -> int:
    """How many consecutive worse readings the nodes this check writes need before
    they publish upward — the check's own value where it stated one, the
    deployment's default where it did not.

    Resolved here rather than in the tree, which reads no configuration, and per
    write rather than once, so a reload that changes the setting is picked up the
    way every other per-run field is.
    """
    stated = check.escalate_after
    return config.escalate_after if stated is None else stated


def _largest_record(result: CheckResult, measurements: Sequence[Measurement],
                    refusals: Sequence[Refusal] = ()) -> tuple[int | None, bool]:
    """The biggest record this run **produced**, in the bytes of its JSON — the
    measurement ADR-0075 decision 8 puts beside a declaration — and whether the
    seam refused that one for its weight.

    Two places hold one, and both are weighed against the one per-record limit:
    what :meth:`Check.measure` read, and what the grading hung on a line for an
    object with no node of its own. ``None`` where the run carried neither, which
    is every check that has not adopted a record; an empty column is not the same
    claim as a zero. The walk goes through the **children** too, because a branch
    check's lines sit on them while the declaration is about the check.

    **The records the seam refused count too** (ADR-0093 decision 6): one refused
    for its weight is the declaration failing, which is what this column exists to
    show, and it is marked. One refused for a bad time counts at the size it was
    handed over at, unmarked, and one that does not serialize has no size. A refused
    reading's stand-in — the failure record naming the refusal — is the engine's
    words and not the check's, so it is not what the run produced.

    The bytes are the seam's: everything here has already been through
    `normalize_record`, so this re-serializes plain JSON types and counts the same
    length that was measured against the limit when it was built.
    """
    largest: int | None = None
    heavy = False
    records: list[Mapping[str, Any]] = [
        measurement.record for measurement in measurements
        if not measurement.refused]
    pending: list[CheckResult] = [result]
    while pending:
        current = pending.pop()
        pending.extend(current.children)
        records.extend(entry.data for entry in current.reason_entries
                       if entry.data is not None)
    for record in records:
        size = len(json.dumps(record).encode("utf-8"))
        if largest is None or size > largest:
            largest, heavy = size, False
    for refusal in refusals:
        if refusal.size is not None and (largest is None or refusal.size > largest):
            largest, heavy = refusal.size, refusal.heavy
    return largest, heavy


def _measured(answer: Measurement | Sequence[Measurement]
              ) -> tuple[Measurement, ...]:
    """What :meth:`Check.measure` handed back, as the sequence the grading is
    promised — one measurement or several, never the difference.

    One record is the common case and deliberately **not** the signature: a type
    that reads one object says so by handing back one value, and every type that
    reads several says it the same way, so nothing downstream branches on shape.
    Anything else is the author's error and raises here, inside the run's own
    `try`, where it becomes this check's `ERROR` and its failure record rather
    than an exception in the scheduler.
    """
    if isinstance(answer, Measurement):
        return (answer,)
    if isinstance(answer, (str, bytes, Mapping)) or not isinstance(
            answer, Sequence):
        raise CheckError(
            f"measure() must return a Measurement or a sequence of them, "
            f"not {type(answer).__name__}")
    for item in answer:
        if not isinstance(item, Measurement):
            raise CheckError(
                f"measure() returned a sequence holding "
                f"{type(item).__name__}, not a Measurement")
    return tuple(answer)


def _at_or_beneath(path: str, above: str) -> bool:
    """Whether the node at ``path`` is ``above`` or one of its descendants — every
    node is beneath the root, whose path is empty."""
    return not above.strip("/") or path == above or path.startswith(
        above.rstrip("/") + "/")


def _beneath(path: str, above: str) -> str:
    """``path`` relative to ``above``, which it is at or beneath: empty for the
    node itself."""
    return path[len(above):].strip("/")


def _names_a_node_at_or_beneath(node: str, relative: str) -> bool:
    """Whether a measure's ``node`` — relative to its check's node, a ``*`` for any
    one segment — names a node at or beneath ``relative``, the node in question
    relative to that same check's node."""
    named = [segment for segment in node.split("/") if segment]
    there = [segment for segment in relative.split("/") if segment]
    return len(named) >= len(there) and all(
        mine in (theirs, "*") for mine, theirs in zip(named, there, strict=False))


def _child_on(result: CheckResult, segments: Sequence[str]
              ) -> tuple[CheckResult | None, int]:
    """The child of ``result`` that stands first on the path ``segments`` names,
    and how many segments its name takes — a child may be named by several
    (:meth:`Engine._store`) — or ``None`` and nothing where no child does."""
    for child in result.children:
        parts = split_path(child.name)
        if parts and list(segments[:len(parts)]) == parts:
            return child, len(parts)
    return None, 0


def _subtree(result: CheckResult, node: str) -> CheckResult | None:
    """What ``result`` returned for the node ``node`` names, relative to its
    root — the root itself for ``""`` — or ``None`` where the grading returned
    no such node (ADR-0130)."""
    segments = split_path(node)
    current = result
    while segments:
        child, taken = _child_on(current, segments)
        if child is None:
            return None
        current, segments = child, segments[taken:]
    return current


def _failure_measurement(check: Check,
                         error: BaseException) -> tuple[Measurement, ...]:
    """The reading a check that **raised** leaves behind: that it could not get
    there, and why, against the object the check declared at construction.

    The engine builds it rather than the check, for the reason every
    engine-assigned failure exists (ADR-0040): the check is precisely the party
    that cannot act now. Doing it by hand in each type is the weakness ADR-0085
    decision 3 found — the one check that recorded a failed reading did it
    because somebody remembered to, and eight did not.

    Guarded, because a record that will not build must never cost the `ERROR`
    that is already decided: the reading is the thing we are trying not to lose,
    and a failure to record the failure is worth a log line and nothing more.
    """
    # Whitespace folded first, as a log line's is — one value, not a document —
    # and then clipped **once, in bytes**, by the helper every type's own failure
    # goes through. A clip in characters let a message of emoji weigh twelve times
    # its length and be refused by the seam, which is the one way this record was
    # still lost. The reason line on the node carries the whole message.
    message = failure_text(" ".join(str(error).split()))
    try:
        return (Measurement(record={"error": message}, subject=check.subject),)
    except Exception:
        logger.exception("engine: could not record the failure of %s",
                         check.path)
        return ()


def _refused_lines(check: Check,
                   measurements: Sequence[Measurement]) -> dict[int, Entry]:
    """One line per reading whose record the seam refused, keyed by where the
    reading stands among the run's (ADR-0093 decision 3).

    The line is the engine's and not the grading's, which never saw the reading. It
    names the subject — the reading's own, or the check's object for the one reading
    a run handed back alone, as wherever the engine places a reading — and why. Its
    slug is declared, ``refused-`` and the subject, so that a pin holds across runs
    where the node's lines are members; its code is the node's form to decide
    (:func:`_with_lines`).
    """
    alone = len(measurements) == 1
    lines: dict[int, Entry] = {}
    for index, reading in enumerate(measurements):
        if not reading.refused:
            continue
        subject = reading.subject or (check.subject if alone else "")
        about = f"the record of {subject}" if subject else "a record with no subject"
        lines[index] = Entry(
            slug("refused", subject),
            plain(f"{about} was refused, and not graded: {reading.refused}"),
            subject=subject)
    return lines


def _with_lines(result: CheckResult, lines: Sequence[Entry],
                code: StatusCode = StatusCode.WARN) -> CheckResult:
    """``result`` with the engine's lines added to its root, in the node's own form
    (ADR-0093 decision 3, ADR-0042).

    A node whose lines carry their own codes derives its code from them, so each
    line added here carries ``code`` itself — ``WARN`` for the engine's own, the
    window's for its line (ADR-0131 decision 7). A node that declares its code keeps
    its lines uncoded — a prose node stays prose, and members that carry the node's
    code stay members — and its code is raised to ``code`` where it was better,
    never lowered. Either way the verdict says it is incomplete: something the node
    reads was not read, or was not read as it should have been, and green over it
    would be a false all-clear.

    **They stand after the grading's own failing lines and ahead of the rest** —
    the leading run of lines at ``ERROR`` or ``WARN``, each by its own code or the
    node's — because a card shows a node's lines in order under a line budget, and
    the reason for a node's color must not be what the budget folds away. A grading
    that put its failures first keeps them first.
    """
    if not lines:
        return result
    graded = result.reason_entries
    lead = 0
    for entry in graded:
        claim = entry.code if entry.code is not None else result.stored_code
        if claim not in (StatusCode.ERROR, StatusCode.WARN):
            break
        lead += 1
    if result.code is None:
        coded = [replace(line, code=code) for line in lines]
        return replace(result, reason=[*graded[:lead], *coded, *graded[lead:]],
                       entries=result.members)
    raised = worst_of((result.code, code)) if result.code in RANKED else code
    prose = [replace(line, code=None) for line in lines]
    return replace(result, code=raised,
                   reason=[*graded[:lead], *prose, *graded[lead:]],
                   entries=result.members)


def _with_line_beneath(result: CheckResult, segments: Sequence[str],
                       line: Entry) -> CheckResult:
    """``result`` with ``line`` added, at the line's own code, to the node
    ``segments`` names beneath its root — the root itself where they are none — in
    that node's own form, as :func:`_with_lines` adds a line; and unchanged where the
    grading returned no such node."""
    if not segments:
        return _with_lines(result, [line], line.code or StatusCode.WARN)
    child, taken = _child_on(result, segments)
    if child is None:
        return result
    changed = _with_line_beneath(child, segments[taken:], line)
    return replace(result, children=tuple(changed if one is child else one
                                          for one in result.children),
                   reason=list(result.reason_entries), entries=result.members)


def _lines_at(result: CheckResult
              ) -> list[tuple[Entry, StatusCode, tuple[str, ...]]]:
    """Every line a grading wrote, as :func:`_lines_of` lists them and in its order,
    each beside the code of the node it hangs on and that node's path beneath the
    root — the path the window's line for the reading the line carries is added at
    (ADR-0131 decision 7)."""
    shown: list[tuple[Entry, StatusCode, tuple[str, ...]]] = []
    kept: list[tuple[Entry, StatusCode, tuple[str, ...]]] = []
    pending: list[tuple[CheckResult, tuple[str, ...]]] = [(result, ())]
    while pending:
        node, at = pending.pop()
        shown.extend((entry, node.stored_code, at) for entry in node.reason_entries)
        kept.extend((entry, node.stored_code, at) for entry in node.for_record)
        pending.extend((child, (*at, *split_path(child.name)))
                       for child in reversed(node.children))
    return shown + kept


def _stands_at(measurement: Measurement,
               lines: Sequence[tuple[Entry, StatusCode, tuple[str, ...]]],
               taken: set[int]) -> tuple[tuple[str, ...] | None, StatusCode | None]:
    """Where a reading among several stands, and at which code: the node the line it
    became hangs on, found as :func:`_line_of` finds the line — by the record it
    carries and the subject it names, the first not yet claimed — or nowhere."""
    record = dict(measurement.record)
    for index, (entry, node_code, at) in enumerate(lines):
        if index in taken or entry.data is None:
            continue
        if entry.subject == measurement.subject and entry.data == record:
            taken.add(index)
            return at, entry.code if entry.code is not None else node_code
    return None, None


def _refused_entries(path: str, result: CheckResult, *, for_record: bool = False
                     ) -> Iterator[tuple[str, Entry]]:
    """Every line of a result whose record the seam refused, beside the path of
    the node it hangs on — the root's first, then each child's, depth first:
    the lines the nodes show, or, ``for_record``, the ones written for the record
    alone (ADR-0111)."""
    for entry in result.for_record if for_record else result.reason_entries:
        if entry.refused:
            yield path, entry
    for child in result.children:
        yield from _refused_entries(join_path(path, child.name), child,
                                    for_record=for_record)


def _say_refused(check: Check, lines: Mapping[int, Entry],
                 result: CheckResult) -> None:
    """The instance says what the seam refused in this run, as a held ``WARN`` on
    its runtime node (ADR-0093 decisions 2 and 3, ADR-0072).

    A line that lost its record looks as healthy as it did, and the refusal is the
    check author's to fix, so it is said where the instance says what keeps going
    wrong: one line per check and reading, or per check and line, each counted over
    its window rather than repeated, and logged as it is seen.
    """
    for line in lines.values():
        self_report.runtime.see(
            slug("refused", check.path, "reading", line.subject),
            f"{plain(check.path)}: {line.text}")
    for path, entry in _refused_entries(check.path, result):
        self_report.runtime.see(
            slug("refused", path, "line", entry.slug),
            plain(f"{path}: the record of the line {entry.slug} was refused: "
                  f"{entry.refused}"))
    # A line written for the record alone is said of the reading whose record it
    # carries (ADR-0111 decision 2): without the record it is said of none, no node
    # shows it, and this is the one place that says so.
    for path, entry in _refused_entries(check.path, result, for_record=True):
        self_report.runtime.see(
            slug("refused", path, "for-record", entry.slug),
            plain(f"{path}: the record of the line {entry.slug}, written for the "
                  f"record, was refused: {entry.refused}"))


def _lines_of(result: CheckResult) -> list[tuple[Entry, StatusCode]]:
    """Every line a grading wrote, each beside the code of the node it hangs on —
    the root's first, then each child's, depth first, in the order written. A
    line that declares no code of its own carries that node's (ADR-0042).

    The lines written **for the record alone** follow, in the same order
    (ADR-0111 decision 2): each carries its own code, which the seam saw to, and
    stands behind every shown line, so that a reading both carry keeps what stood
    on the node."""
    shown: list[tuple[Entry, StatusCode]] = []
    kept: list[tuple[Entry, StatusCode]] = []
    pending = [result]
    while pending:
        node = pending.pop()
        shown.extend((entry, node.stored_code) for entry in node.reason_entries)
        kept.extend((entry, node.stored_code) for entry in node.for_record)
        pending.extend(reversed(node.children))
    return shown + kept


def _line_of(measurement: Measurement, lines: Sequence[tuple[Entry, StatusCode]],
             taken: set[int]) -> tuple[StatusCode | None, tuple[str, ...]]:
    """The code and the text of the line a reading became, or nothing where no
    line carries it (ADR-0087).

    A grading carries a reading onto the line it produced as that line's ``data``,
    and the line's subject is the reading's (ADR-0086 decision 2), so the line is
    found by both. The first line not yet claimed wins, which pairs two readings
    that carry the same record with two lines in the order both were written.
    """
    record = dict(measurement.record)
    for index, (entry, node_code) in enumerate(lines):
        if index in taken or entry.data is None:
            continue
        if entry.subject == measurement.subject and entry.data == record:
            taken.add(index)
            return (entry.code if entry.code is not None else node_code,
                    (entry.text,))
    return None, ()


def _placed(result: CheckResult) -> tuple[StatusCode | None, tuple[str, ...]]:
    """What stood on the check's node, for the one reading the engine placed there
    and for a reading among several that names the object the check declared and
    that no line carried: the root's own code and its texts — or, where the root
    grades nothing, a branch check's `UNDEFINED` container, what the result rolls up
    to, beside whatever the root says (ADR-0087 decision 8). A root that says what
    it watches claims no more than a silent one: a sentence is not a code."""
    texts = tuple(result.reason_texts)
    if result.stored_code is StatusCode.UNDEFINED:
        return _rolled_up(result), texts
    return result.stored_code, texts


def _rolled_up(result: CheckResult) -> StatusCode:
    """What a result rolls up to: its root's code and every child it returned, by
    ADR-0039's rules — :func:`~little_sister.status.effective_code`, the function
    the tree rolls a node up with, applied to what this run wrote instead of what
    the node holds.

    The node would also answer with what does not belong to this reading: the
    children another check on the same mount wrote (ADR-0015), and a child an
    earlier run wrote and this one did not, which the tree does not prune
    (ADR-0007) — and it would answer differently depending on which check stored
    last. From the result, the code is the one grading the record again gives, and
    a pin cannot reach it.
    """
    return effective_code(result.stored_code,
                          (_rolled_up(child) for child in result.children))


def _detail(result: CheckResult) -> str:
    """What one run's log line says after the code and the elapsed time.

    Every reason, joined, bounded by :data:`DETAIL_LIMIT` — see that constant for
    why it is no longer the first reason cut at 120. Newlines are flattened
    because this is one log record, and truncation says so with an ellipsis
    rather than stopping silently: a line that ends mid-word looks exactly like a
    message that ended there, which is how a refusal was read as truncated by AWS
    rather than by us.
    """
    texts = [text.replace("\n", " ") for text in result.reason_texts if text]
    if not texts:
        return ""
    joined = DETAIL_SEPARATOR.join(texts)
    if len(joined) > DETAIL_LIMIT:
        joined = joined[:DETAIL_LIMIT] + " …"
    return " — " + joined


def _asks_for_a_collection(before: Resident | None,
                           after: Resident | None) -> bool:
    """Whether a run rose enough to be followed by a collection (ADR-0095 decision
    8): by :data:`~little_sister.limits.RISE_LOGGED` or more — the size's rise where
    both reads have a size now, the peak's where neither has, as on macOS, where a
    collection follows a run that raised the high-water mark. A peak that rose on
    Linux while the size did not is a spike the run gave back before it ended, and a
    read that failed says nothing: neither asks for one."""
    if before is None or after is None:
        return False
    if before.now is not None and after.now is not None:
        return after.now - before.now >= RISE_LOGGED
    if before.now is None and after.now is None:
        return after.peak - before.peak >= RISE_LOGGED
    return False


def _fell(before: Resident | None, after: Resident | None) -> int:
    """How far the size fell between two reads — ``0`` where either has no size
    now, and negative where it rose."""
    if before is None or after is None or before.now is None or after.now is None:
        return 0
    return before.now - after.now


def _rose(before: Resident | None, after: Resident | None) -> tuple[int, int]:
    """How far the size and the peak rose between two reads (ADR-0095): the size
    only where both reads have one, nothing where either read failed. A fall is a
    negative number here, and :func:`~little_sister.limits.rise_text` says none of
    it."""
    if before is None or after is None:
        return 0, 0
    size = (after.now - before.now
            if after.now is not None and before.now is not None else 0)
    return size, after.peak - before.peak


def _abandoned(paths: Sequence[str], ended: int) -> str:
    """What the stop's one INFO line says about what it left behind (ADR-0088
    decision 4)."""
    if not paths:
        said = "no run was in flight"
    else:
        runs = "run" if len(paths) == 1 else "runs"
        said = f"abandoned the {runs} of {', '.join(sorted(paths))}"
    if ended:
        groups = "process group" if ended == 1 else "process groups"
        said += f", and ended {ended} {groups} they had started"
    return said


@dataclass
class _Scheduled:
    check: Check
    next_due: float
    running: bool = False
    #: The unit this entry releases (ADR-0130) — the check's one anonymous unit, or
    #: one it declared — and the absolute path of the node it answers for, the
    #: mount for the anonymous one. `latest` is the newest reading the unit handed
    #: back, what the check is graded over beside its siblings' newest; `None`
    #: before its first measurement, `()` where it measured nothing. Under the
    #: engine lock.
    unit: Unit = field(default_factory=lambda: Unit("", DEFAULT_PERIOD, ""))
    node: str = ""
    latest: tuple[Measurement, ...] | None = None
    # One-time schedule offset (see _stagger), spent at the first re-arm.
    stagger: float = 0.0
    # The budgeted failure retry (ADR-0033, amended by ADR-0060 and ADR-0125),
    # resolved per check at engine construction: the fast interval (0 = off) and
    # the per-episode budget. `retry_used` counts the fast attempts of the current
    # episode and `last_code` is what ends one — **any** change of what the run
    # rolls up to, not only an OK, because a check whose ordinary state is non-OK
    # would otherwise spend its budget once and never get it back. It starts at
    # `UNDEFINED` because that is the code a node carries before its first run —
    # nothing observable turns on the choice, since a first reading either matches
    # it or is news, but any other value would be a lie to whoever reads it in a
    # debugger. `retrying` marks that the currently armed slot is a retry slot,
    # for the system page. In-memory only — a restart forgets an episode, like the
    # rest of the schedule.
    retry_interval_seconds: int = 0
    retry_attempts: int = 0
    retry_used: int = 0
    last_code: StatusCode = StatusCode.UNDEFINED
    retrying: bool = False
    # When the scheduler handed the check to the pool (the engine's clock), so
    # the tick can see how long it has waited for a worker (ADR-0072).
    submitted_mono: float | None = None
    # The in-flight run: the instant it started and the monotonic mate, set when
    # execution begins (queue wait excluded), cleared when it finishes.
    run_started_at: datetime | None = None
    run_started_mono: float | None = None
    # The last completed run attempt: when it started and how long it took —
    # a raising (or timed-out) run records its full wait; a secret-pinned check
    # never runs, so both stay None. Read under the engine lock.
    last_run_at: datetime | None = None
    elapsed_seconds: float | None = None
    # The biggest record the last run carried, in the bytes of its JSON — the
    # measurement that stands beside `expected_record()` (ADR-0075 decision 8).
    # `None` for a run that carried none, which is every check that has not
    # adopted a record: nothing measured is not the same claim as nothing held.
    record_bytes: int | None = None
    # Whether the seam refused that biggest record for its weight (ADR-0093
    # decision 6) — the declaration failing, which is what the pair is shown for.
    record_refused: bool = False
    # The code of the **last result this check stored**, `None` until the first
    # one lands — including the ERROR a secret-pinned check stores without ever
    # calling measure(). Deliberately not `last_code` above, which the retry block
    # moves only when an episode ends and leaves at UNDEFINED for a check with no
    # retry configured: what the readiness report needs is what every check last
    # said, on every completion (ADR-0073). Read under the engine lock.
    last_stored: StatusCode | None = None
    # What this check's runs are called in another run's log line (ADR-0095
    # decision 4): its path, and its type beside it where another check shares the
    # mount (ADR-0015). Set once, at construction.
    name: str = ""
    # Every other run in flight at any point of the current one, by name — what its
    # log line names beside a rise (ADR-0095 decision 4). Written under the engine
    # lock, by this run's start and by every run that starts while it is in flight.
    beside: set[str] = field(default_factory=set)


@dataclass(frozen=True)
class CheckInfo:
    """A check's scheduling state, for the system page.

    ``running_since`` / ``running_seconds`` describe the in-flight run (``None``
    while idle, and while a submitted run still waits for a pool worker);
    ``next_run_at`` / ``next_in_seconds`` the armed next slot (a running check's
    next slot is already scheduled); ``last_run_at`` / ``elapsed_seconds`` the
    last completed run — ``None`` until one finishes, and always for a
    secret-pinned check (it never runs). ``retrying`` marks a check whose armed
    slot is a failure-retry slot (ADR-0033) — fast attempt ``retry_attempt`` of
    ``retry_attempts`` — so the system page can explain a next run that
    contradicts the frequency column.
    """
    path: str
    type_name: str
    frequency_seconds: int
    running: bool
    running_since: datetime | None
    running_seconds: float | None
    next_run_at: datetime
    next_in_seconds: float
    last_run_at: datetime | None
    elapsed_seconds: float | None
    retrying: bool = False
    retry_attempt: int = 0
    retry_attempts: int = 0
    #: The row is a **unit's** (ADR-0130): the path of the node it answers for —
    #: the mount, for a check that declares no units — and its key, empty for the
    #: anonymous unit. ``frequency_seconds`` above is the unit's own period. A
    #: check's units stand beneath it, in the order it declared them.
    node: str = ""
    unit: str = ""
    #: What this check declared it costs (ADR-0075): worker seconds per run and
    #: reason entries held, or ``None`` where the type did not estimate. They sit
    #: beside ``elapsed_seconds`` — the measurement — on purpose: an estimate
    #: decays as an estate grows, and the page is where that becomes visible.
    expected_cost: float | None = None
    expected_entries: int | None = None
    #: Bytes one record of this check is declared to need, and the biggest one its
    #: last run actually carried. The same estimate-beside-measurement pairing as
    #: the two above, in one column because there is nothing else about records to
    #: put in another.
    expected_record: int | None = None
    record_bytes: int | None = None
    #: Whether the seam refused that biggest record for its weight (ADR-0093
    #: decision 6): the page marks the figure *refused*, because a declaration
    #: failing is what the pair is shown for.
    record_refused: bool = False
    #: What the type itself declared, where the engine's failure-record floor
    #: raised it — so the page can say both — and ``None`` where the two agree.
    stated_record: int | None = None
    #: The check this one is reached **through**, or ``None``. Here rather than
    #: only on the node page because the graph is the thing a reader wants whole:
    #: one failing dependency withholds every check that names it, and a page that
    #: could only be read one node at a time would make that count an exercise.
    depends_on: str | None = None
    #: What its type declares of its lines (ADR-0126): the forms, the words and the
    #: fields a check's ``display:`` block may name — which ``/system/installed``
    #: lists for every type this configuration runs, as the page a deployment writes
    #: a template against.
    line_declarations: Declarations = field(default_factory=Declarations)
    #: What its type declares it grades (ADR-0131 decision 1): each value with its
    #: sentence, its kind, its default and the keys a deployment writes it under —
    #: which ``/system/installed`` lists for every type this configuration runs,
    #: beside what the library grades on every check.
    gradings: tuple[Grading, ...] = ()


@dataclass(frozen=True)
class EngineInfo:
    """A snapshot of the engine's runtime state.

    ``declared_workers`` / ``declared_entries`` are the sums startup measured the
    configuration against (ADR-0075) and ``entries_held`` is what the tree holds
    now, so the page can show the estimate and the measurement in one place. The
    series are the third such pair (ADR-0087): ``series_held`` is what they weigh,
    ``series_projection`` what this configuration would need at today's estate,
    both as the last tick measured them, against ``series_limit``.
    """
    started_at: datetime | None
    uptime_seconds: float
    max_workers: int
    check_count: int
    running: int
    checks: tuple[CheckInfo, ...]
    #: How many units the schedule releases (ADR-0130) — ``check_count`` where no
    #: check declares any, and one row of ``checks`` each.
    unit_count: int = 0
    declared_workers: float = 0.0
    declared_entries: int = 0
    entries_held: int = 0
    entry_limit: int = 0
    #: The per-record bound this deployment set, so the page can name what a
    #: declared or measured record is being read against. Never a sum.
    record_limit: int = 0
    series_held: int = 0
    series_projection: int = 0
    series_limit: int = 0
    #: What the process held at the last tick (ADR-0095 decision 2): the size now,
    #: ``None`` where the platform keeps none, and the peak, ``None`` before the
    #: first tick — against the ``memory`` line's limit and what the machine gives
    #: the process, each ``None`` where the machine could not say.
    resident: int | None = None
    resident_peak: int | None = None
    memory_limit: int | None = None
    machine_memory: int | None = None
    #: What the machine had left at the last tick (ADR-0095 decision 7), ``None``
    #: where it could not say; and beside it, in the words every surface says them,
    #: how long the machine stalled on memory and, under a memory limit, how often
    #: the kernel has ended a process of this cgroup — each ``""`` where there is
    #: nothing to say. All three are nothing where the platform says none of it.
    machine_left: int | None = None
    machine_stalled: str = ""
    machine_killed: str = ""


@dataclass(frozen=True)
class SubjectSeries:
    """A subject's series as a page shows it (ADR-0092, ADR-0097): the check that
    keeps it — whose ``measures`` its curves are drawn by and whose
    ``reading_cap`` may say how many rows show — its readings, oldest first, each
    where its series places it, and the subject they were read of."""

    check: Check
    readings: tuple[Placed, ...]
    subject: str = ""


#: The check whose measuring half this thread is in, or ``None`` — which is
#: everywhere but inside a ``measure()`` the engine called (ADR-0113 decision 4). A
#: context variable, as the lenient seam's is (ADR-0093 decision 5): the mark stands
#: on the run's own thread, and a thread a check starts itself begins without it.
_MEASURING: ContextVar[Check | None] = ContextVar(
    "little_sister_measuring", default=None)


@contextmanager
def _measuring(check: Check) -> Iterator[None]:
    """The measuring half of ``check``, for the duration: the one stretch in which
    what the engine bound to it as ``kept()`` answers (ADR-0113 decision 4). Opened
    around ``measure()`` and around nothing else — not around ``grade()``, which
    reads what it is handed and fetches nothing (ADR-0086 decision 6)."""
    token = _MEASURING.set(check)
    try:
        yield
    finally:
        _MEASURING.reset(token)


class Engine:
    """Runs a set of checks on their own schedules against a status tree."""

    def __init__(self, checks: list[Check], tree: StatusTree, *,
                 max_workers: int | None = None,
                 poll_interval: float = DEFAULT_POLL_INTERVAL,
                 clock: Callable[[], float] = time.monotonic,
                 heartbeat_warning: Sequence[Entry] | None = None,
                 heartbeat_report: str = "",
                 state: StateLayer | None = None,
                 limits: Limits | None = None,
                 series: MemoryStore | None = None,
                 resident: Callable[[], Resident | None] = resident_size,
                 left: Callable[[], Left | None] = machine_left,
                 wall: Callable[[], datetime] = instants.now,
                 collect: Callable[[], object] | None = gc.collect) -> None:
        # The limits this engine measures itself against: what the deployment
        # stated in `settings.yaml`, or the constants in `limits.py` where it
        # said nothing — unless a caller composed its own and passed them.
        self._limits = limits or Limits.from_machine(
            entry_limit=config.entry_limit, memory_share=config.memory_share,
            record_limit=config.record_limit, series_limit=config.series_limit)
        # The checks, and what each declares it reads on slots of its own
        # (ADR-0130): one unit for a check that declares none. Read first, because
        # a declaration the schedule could not honor refuses the start as a
        # declared load that cannot fit does, below.
        self._checks: list[Check] = list(checks)
        units_of: dict[int, tuple[Unit, ...]] = {
            id(check): _units_of(check) for check in checks}
        # The pool is never larger than the roster: eight workers for three
        # checks are five threads that can never be used. Units of one check run
        # one at a time (`_submit_due`), so the roster is the checks, not the units.
        ceiling = config.max_workers if max_workers is None else max_workers
        self._max_workers = max(1, min(ceiling, max(1, len(checks))))
        # What the configured checks **declared** they cost, summed against the
        # pool this engine will actually run and against the entry limit
        # (ADR-0075). A declared load that cannot fit refuses here — first, before
        # anything is registered on the tree, so a refusal leaves nothing half
        # built — because those checks would still run and still report, without
        # measuring what the operator believes they measure. A check with units of
        # its own is read one view per unit: each unit's cost over its own period
        # (ADR-0130 decision 5).
        views = [view for check in checks
                 for view in _views(check, units_of[id(check)])]
        self._capacity = capacity(views, max_workers=self._max_workers,
                                  limits=self._limits,
                                  record_floor=FAILURE_RECORD_BYTES)
        if refusals := self._capacity.refusals():
            raise CheckError("; ".join(refusals))
        for _limit, said in self._capacity.warnings():
            logger.warning("engine: %s", said)
        self._tree = tree
        # A configured-but-empty deployment: the engine runs, and every beat
        # carries these lines at WARN instead of OK (see _tick / ADR-0031 §7).
        self._heartbeat_warning = tuple(heartbeat_warning or ())
        # What stands beside the warning as a fact — the paths that were searched
        # for checks — is the engine's report, not a second line (ADR-0076).
        self._heartbeat_report = heartbeat_report
        # The state layer (ADR-0071), when the application keeps one: its kept
        # files are written on the tick and once more at stop().
        self._state = state
        # Where the checks' readings are kept as series (ADR-0087): memory, the
        # first tier and always the front, unless a caller composed its own — and
        # what each check keeps, by the two things a series names a check by. A
        # series whose check is not here — gone from the configuration since the
        # series file was written — keeps nothing, and the next sweep drops it.
        self._series: MemoryStore = MemoryStore() if series is None else series
        self._series_keep: dict[tuple[str, str], int] = {
            (check.type_name, check.path): check.series_keep for check in checks}
        # Make the self-monitor legible before it ever beats: the strip's
        # hover card can always say what /little-sister is (the nodes.yaml
        # pass runs later at startup and overrides this default). The children
        # take their labels on the tick, fill-only, so the same pass wins there.
        tree.set_about(HEARTBEAT_PATH, HEARTBEAT_ABOUT)
        # The instance's own branch begins with this process (ADR-0099 decision
        # 9): its first beat is a beginning the tree saw, where a check's first
        # reading finds a node that was already what it shows. Said here, before
        # the application restores anything, so a kept log is read the same way.
        tree.set_process_branch(HEARTBEAT_PATH)
        # Tell the tree where each check writes its result root, so a container above
        # exactly one of them can publish that check's run time as its own observation
        # (ADR-0027). Registration only — a node still appears when its result does.
        # The heartbeat above is deliberately *not* a mount: it is the engine's own
        # liveness rather than a check, so it neither blocks nor feeds that roll-up
        # (and the dashboard lifts it out of the grid anyway, ADR-0024).
        # And, beside it, where a check is reached *through* another one
        # (ADR-0032 rule 3, backlog #38 A). Registration only, exactly like the
        # mount above: whether the shield is in force is derived per snapshot
        # from what the dependency is reporting right now. The loader has
        # already refused an unknown target and any cycle, so every target here
        # names a mount that exists.
        for check in checks:
            tree.set_check_mount(check.path)
            if check.depends_on is not None:
                tree.set_dependency(check.path, check.depends_on)
            # What each check may read of what it kept (ADR-0113): its own series,
            # by its own type and mount, and no other check's.
            check.bind_kept(partial(self._kept, check))
        # What a check's run may never remove (ADR-0109 decision 2): the nodes the
        # other checks own (ADR-0015) — two may share a mount, each owning its own
        # children — and the instance's own branch. Read once: a check's owned
        # nodes are its configuration's.
        self._not_its_own: dict[int, tuple[str, ...]] = {
            id(check): tuple(sorted({HEARTBEAT_PATH, *(
                join_path(owned) for other in checks if other is not check
                for owned in other.owned_nodes())}))
            for check in checks}
        # The deployment's `nodes.yaml` as loaded (ADR-0128), which the start hands
        # over before the first tick (:meth:`declare_nodes`): a node's own entry is
        # seeded onto the tree, and a parent's `children:` is read here as each child
        # is written, since no path names the children it speaks for.
        self._nodes: Mapping[str, NodeMeta] = {}
        self._clock = clock
        self._poll_interval = poll_interval
        now = clock()
        # Every check is due immediately, so the first sweep populates the
        # tree; the stagger then phase-shifts each schedule once so the
        # lockstep doesn't outlive the start. The failure-retry settings
        # (ADR-0033) resolve per check here — the per-check fields first, then
        # the settings defaults — so _execute reads two ints, never the config.
        # One entry per **unit** (ADR-0130 decision 3): a check's units in the
        # order it declared them, each on its own period, each answering for its
        # own node — the mount, for the one anonymous unit of a check that declares
        # none, which is every entry there was before.
        self._scheduled: list[_Scheduled] = []
        self._units: dict[int, tuple[_Scheduled, ...]] = {}
        for check in checks:
            retry_interval, retry_attempts = _retry_settings(check)
            items = tuple(_Scheduled(
                check, now, stagger=_stagger(check, unit), unit=unit,
                node=join_path(check.path, unit.node),
                retry_interval_seconds=retry_interval,
                retry_attempts=retry_attempts) for unit in units_of[id(check)])
            self._units[id(check)] = items
            self._scheduled.extend(items)
        # The checks with a unit in flight: a check's units run one at a time, so
        # a type's measuring half is never in two threads at once and one slow unit
        # costs its check what one slow run did. Under the engine lock.
        self._busy: set[int] = set()
        # What a run is called beside another in the log (ADR-0095 decision 4): its
        # path, and its type too where two checks share the mount (ADR-0015) — and
        # its unit's key, where the check declares units (ADR-0130).
        mounts = Counter(check.path for check in checks)
        for item in self._scheduled:
            item.name = (item.check.path if mounts[item.check.path] == 1
                         else f"{item.check.path} ({item.check.type_name})")
            if item.unit.key:
                item.name += f" [{item.unit.key}]"
        # What the process holds, read by the tick's report, at a run's start and
        # end and around the tick (ADR-0095); and the wall clock, an instant: when
        # the engine started and a run did, when a reading was observed, when a
        # check's next run is due and, read on the clock the log is stamped in, the
        # ten-minute marks the memory line keeps in the log — and, handed to the
        # report, the time of a reading that the `memory` line on the engine's node
        # comes to name. A clock that answers a time without a zone is refused
        # where it is read (ADR-0120).
        self._resident = resident
        self._wall: Callable[[], datetime] = lambda: instants.utc(
            wall(), "the engine's wall clock")
        # The cycle collector a run that rose is followed by (ADR-0095 decision 8),
        # ``None`` for a caller that collects nothing — a test measuring something
        # else — and the engine's clock from which the next may start: none until a
        # hundred times what the last took has passed since it ended, and none at
        # all while one runs. Under the engine lock.
        self._collect = collect
        self._collect_from = float("-inf")
        # The runs in flight at any point of the tick in progress, by name — ``None``
        # between ticks (ADR-0095 decision 5). Under the engine lock.
        self._tick_beside: set[str] | None = None
        # The ten-minute mark the memory line was last written at, ``None`` before
        # the first tick. The scheduler thread's alone.
        self._memory_mark: tuple[date, int] | None = None
        self._lock = threading.Lock()
        self._stop = threading.Event()
        #: Whether :meth:`stop` has run — the second call says nothing.
        self._stopped = False
        self._executor: DaemonPool | None = None
        self._scheduler: threading.Thread | None = None
        self._started_at: datetime | None = None
        self._started_monotonic: float | None = None
        # The engine's own lines (ADR-0072): what it measures against its limits
        # as it runs, recorded on the tick and read there. A `timeout` longer than
        # the `frequency` is a configuration that can run late — a warning here,
        # at load, and an uncoded line on the beat for as long as the process
        # runs; never a refusal, because a run longer than its period is a late
        # run, not a broken one.
        self._report = EngineReport(
            views, workers=self._max_workers, poll_interval=poll_interval,
            limits=self._limits, capacity=self._capacity, resident=resident,
            left=left, wall=self._wall)
        for late in self._report.may_run_late:
            logger.warning(
                "check %s: timeout %s is longer than its frequency %s, so a run "
                "may outgrow its period — it will run late, not be refused",
                late.path, format_duration(int(late.timeout_seconds)),
                format_duration(late.frequency_seconds))

    @property
    def check_count(self) -> int:
        return len(self._checks)

    @property
    def outcomes(self) -> Outcomes:
        """What this engine's checks have done so far (ADR-0073): how many are
        configured, how many have stored a result at least once, and how many
        last stored an ``ERROR``. Recorded state, read under the lock — the
        readiness answer and the instance's own line both come from here, and
        neither asks a check anything. A check with units has stored once any of
        them has, and is erroring while any of them last stored an ``ERROR``."""
        with self._lock:
            stored = [[item.last_stored for item in self._units[id(check)]]
                      for check in self._checks]
        return Outcomes(
            configured=len(stored),
            completed=sum(1 for codes in stored
                          if any(code is not None for code in codes)),
            erroring=sum(1 for codes in stored
                         if any(code is StatusCode.ERROR for code in codes)))

    def check_roots(self) -> list[str]:
        """Each configured check's node path — the static roots the maintenance
        reaper reconciles against at startup (ADR-0014/0015)."""
        return [check.path for check in self._checks]

    @property
    def checks(self) -> list[Check]:
        """The configured checks (for startup node-metadata seeding, ADR-0012)."""
        return list(self._checks)

    def units(self) -> tuple[tuple[Check, Unit, str], ...]:
        """Every unit the schedule releases, with its check and the absolute path
        of the node it answers for (ADR-0130) — what a pin's floor is read from."""
        return tuple((item.check, item.unit, item.node) for item in self._scheduled)

    @property
    def series(self) -> MemoryStore:
        """Where this engine keeps its checks' readings as series (ADR-0087) —
        what the state layer writes to ``series.json`` and restores from it."""
        return self._series

    def _kept(self, check: Check, subject: str) -> tuple[SeriesRecord, ...]:
        """What ``check`` kept of ``subject``, for its measuring half (ADR-0113):
        the window of that one series as the store holds it, oldest first — its
        own, keyed by its type and its mount, so it reads no other check's. Each
        record is handed with a ``data`` of its own: what a type does to what it
        was handed never reaches what is kept. Nothing where the check keeps no
        series, whatever a state file left behind; and nothing for no subject,
        since a reading without one has no series.

        **Only while that check is measuring** (decision 4): anywhere else — its
        grading, another check's run, a thread the check started, no run at all —
        the read is refused, whatever it would have found. A grading reads what it
        is handed (ADR-0086 decision 6), and a refusal there is an exception like
        any other in a grading: the node's ``ERROR`` (ADR-0040)."""
        if _MEASURING.get() is not check:
            raise CheckError(
                "kept() answers only inside this check's measure(), on the thread "
                "the engine called it on: a grading reads the records, the "
                "configuration and the clock it is handed, and fetches nothing "
                "(ADR-0086 decision 6, ADR-0113 decision 4)")
        if check.series_keep < 1:
            return ()
        return tuple(
            replace(record, data=copy.deepcopy(dict(record.data)))
            for record in self._series.window(
                SeriesKey(check.type_name, check.path, subject)))

    def series_near(self, path: str) -> tuple[SubjectSeries, ...]:
        """Every series whose curves may stand at or beneath the node at ``path``
        (ADR-0097 decision 1): each configured check that keeps a series and is
        mounted at that node, beneath it or above it, with every subject its series
        hold — the root's path, ``""``, reaching all of them.

        Found through the checks rather than the tree, so a mount two checks share
        shows both, though its node withholds the one subject a last writer would
        claim for both (ADR-0044). Which curve stands where is the page's: a check
        above the node is here only because one of its measures may name a node at
        or beneath it."""
        where = join_path(path)
        found: list[SubjectSeries] = []
        for check in self._checks:
            if check.series_keep < 1 or not (
                    _at_or_beneath(check.path, where)
                    or _at_or_beneath(where, check.path)):
                continue
            for subject in self._series.subjects(check.type_name, check.path):
                readings = self._series.placed(
                    SeriesKey(check.type_name, check.path, subject))
                if readings:
                    found.append(SubjectSeries(check, readings, subject))
        return tuple(found)

    def curves_may_stand(self, path: str) -> bool:
        """Whether a curve can stand at or beneath the node at ``path``, as the
        configuration says (ADR-0097 decision 3): a check keeps a series there or
        beneath it, or above it with a measure naming a node there — a ``*``
        naming any. Read from the checks and never from the readings, so a view's
        tab does not come and go with them."""
        where = join_path(path)
        for check in self._checks:
            if check.series_keep < 1:
                continue
            if _at_or_beneath(check.path, where):
                return True
            if _at_or_beneath(where, check.path) and any(
                    _names_a_node_at_or_beneath(measure.node,
                                                _beneath(where, check.path))
                    for measure in check.measures.values()):
                return True
        return False

    def series_keep(self, key: SeriesKey) -> int:
        """How many readings the series ``key`` may keep under this configuration:
        its check's ``series_keep``, and none where no configured check is of that
        type on that mount."""
        return self._series_keep.get((key.type_name, key.mount), 0)

    def info(self) -> EngineInfo:
        """A snapshot of the engine's runtime state (for the system page)."""
        now = self._clock()
        # The schedule runs on the monotonic clock; project each next-due onto
        # the wall clock once, here, so the system page can show a time of day.
        wall = self._wall()
        # What each check declared, read once from the load-time arithmetic
        # rather than by asking the checks again: a declaration is computed from
        # configuration and cannot change while the process runs.
        declared_cost = {item.path: item.cost_seconds
                         for item in self._capacity.declared}
        declared_entries = {item.path: item.entries
                            for item in self._capacity.declared}
        declared_record = {item.path: item.record_bytes
                           for item in self._capacity.declared}
        stated_record = {item.path: item.record_stated
                         for item in self._capacity.declared}
        with self._lock:
            checks = tuple(
                CheckInfo(path=item.check.path,
                          type_name=item.check.type_name,
                          frequency_seconds=item.unit.period_seconds,
                          node=item.node, unit=item.unit.key,
                          running=item.running,
                          running_since=item.run_started_at,
                          running_seconds=(now - item.run_started_mono
                                           if item.run_started_mono is not None
                                           else None),
                          next_run_at=wall + timedelta(
                              seconds=max(0.0, item.next_due - now)),
                          next_in_seconds=max(0.0, item.next_due - now),
                          last_run_at=item.last_run_at,
                          elapsed_seconds=item.elapsed_seconds,
                          retrying=item.retrying,
                          retry_attempt=item.retry_used,
                          retry_attempts=item.retry_attempts,
                          expected_cost=declared_cost.get(item.node),
                          expected_entries=declared_entries.get(item.node),
                          expected_record=declared_record.get(item.node),
                          stated_record=stated_record.get(item.node),
                          record_bytes=item.record_bytes,
                          record_refused=item.record_refused,
                          depends_on=item.check.depends_on,
                          line_declarations=item.check.line_declarations,
                          gradings=item.check.grading_declarations)
                for item in self._scheduled)
            running = sum(1 for item in self._scheduled if item.running)
        uptime = (now - self._started_monotonic
                  if self._started_monotonic is not None else 0.0)
        # The series as the last tick measured them, not measured again here: the
        # page then says what the engine's own `series` lines say, and a poll of
        # it walks no store. The process's own figures likewise (ADR-0095).
        series = self._report.series
        memory = self._report.memory
        left, stall = self._report.left, self._report.stalled
        return EngineInfo(
            started_at=self._started_at, uptime_seconds=uptime,
            max_workers=self._max_workers, check_count=len(self._checks),
            unit_count=len(self._scheduled),
            running=running, checks=checks,
            declared_workers=self._capacity.workers,
            declared_entries=self._capacity.entries,
            entries_held=self._tree.entry_count,
            entry_limit=self._limits.entry_limit,
            record_limit=self._limits.record_limit,
            series_held=series.held if series is not None else 0,
            series_projection=series.projection if series is not None else 0,
            series_limit=self._limits.series_limit,
            resident=memory.now if memory is not None else None,
            resident_peak=memory.peak if memory is not None else None,
            memory_limit=self._limits.memory_limit,
            machine_memory=self._limits.machine_memory,
            machine_left=left.available if left is not None else None,
            machine_stalled=stall_text(stall) if stall is not None else "",
            machine_killed=(killed_text(left.killed)
                            if left is not None and left.killed is not None else ""))

    def start(self) -> None:
        """Start the scheduler and worker pool (idempotent).

        Started even with **no checks scheduled**: the scheduler still has its own
        heartbeat to publish, and that beat is the whole point of the empty case —
        a deployment configured to watch nothing yet must say so on the dashboard,
        not only in the log (ADR-0005 / ADR-0031 §7). A loop with nothing due does
        exactly one thing per tick, which is what it is there for.
        """
        if self._scheduler is not None:
            return
        self._started_at = self._wall()
        self._started_monotonic = self._clock()
        # The engine's own pool (ADR-0088 decision 1): daemon threads the
        # interpreter does not join, so a run in flight never holds the exit.
        self._executor = DaemonPool(self._max_workers, "ls-check")
        self._scheduler = threading.Thread(
            target=self._loop, name="ls-scheduler", daemon=True)
        self._scheduler.start()
        logger.info("engine: started %d check(s), %d unit(s), on %d worker(s)",
                    len(self._checks), len(self._scheduled), self._max_workers)

    def stop(self, *, trigger: str = "a call", timeout: float | None = 5.0) -> None:
        """The instance's stop (ADR-0088): idempotent, and a second call says
        nothing.

        The scheduler stops first. The runs in flight are **abandoned** — whatever
        they deliver afterwards is dropped — and every process a run started is
        ended, TERM, a grace, KILL (:func:`little_sister.process.end_all`). One INFO
        line names the runs it abandoned and ``trigger``, what reached the stop.
        Then the **one final save**, after which nothing writes the state directory
        and the directory's lease is let go. The log that save writes carries the
        moment of the stop (ADR-0094 decision 4).
        """
        with self._lock:
            if self._stopped:
                return
            self._stopped = True
        self._stop.set()
        scheduler, self._scheduler = self._scheduler, None
        if scheduler is not None:
            scheduler.join(timeout=timeout)
        with self._lock:
            abandoned = [item.name for item in self._scheduled if item.running]
        ended = process.end_all()
        executor, self._executor = self._executor, None
        if executor is not None:
            executor.shutdown(wait=False, cancel_futures=True)
        logger.info("engine: stopped, reached by %s; %s", trigger,
                    _abandoned(abandoned, ended))
        if self._state is not None:
            # The log the one save writes says when this process stopped watching,
            # so the next one can date the gap on the instance's own node (ADR-0094
            # decision 4).
            self._tree.note_stop()
            self._state.shutdown()
        self._log_memory_at_stop()

    def run_once(self) -> None:
        """Run every check once, synchronously, and upsert results.

        Used for tests and a potential one-shot refresh; the background loop does
        not call this. A one-shot run has no live schedule, so the run facts it
        writes carry no next slot (ADR-0044).
        """
        for item in self._scheduled:
            self._execute(item, once=True)

    def _loop(self) -> None:
        while not self._stop.is_set():
            # A lease taken from this instance ends the loop before the next
            # submission (ADR-0090 decision 7).
            holder = self._state.lost if self._state is not None else None
            if holder is not None:
                self._halt(holder)
                return
            self._guarded_tick()
            self._stop.wait(timeout=self._poll_interval)

    def _guarded_tick(self, *, submit: bool = True) -> None:
        # Harden the loop: a transient fault in one tick must not kill the
        # scheduler thread and stop all monitoring.
        try:
            self._tick(submit=submit)
        except Exception as error:
            logger.exception("engine: scheduler tick failed")
            self_report.runtime.see(
                "tick",
                plain(f"a scheduler tick raised ({error!r}); the scheduler "
                      f"went on to the next"), log=False)

    def _halt(self, holder: str) -> None:
        """The state directory's lease was taken from this instance (ADR-0090
        decision 7), and it runs no more checks: another process holds the directory
        now, and one that went on would spend the same tokens on the same sources
        beside it. A stop without its save — nothing here writes the directory any
        more, and its lease is somebody else's to release — reached from the
        scheduler itself, which ends here. One last tick without a submission
        publishes the instance's own lines, the readiness line that says why among
        them, so what the instance serves from now on is its last view and the
        reason it is the last."""
        with self._lock:
            if self._stopped:
                return
            self._stopped = True
            abandoned = [item.name for item in self._scheduled if item.running]
        self._stop.set()
        ended = process.end_all()
        executor, self._executor = self._executor, None
        if executor is not None:
            executor.shutdown(wait=False, cancel_futures=True)
        logger.error("engine: halted — the state directory's lease is held by %s, so "
                     "this instance runs no more checks and serves the last view it "
                     "had; %s", holder, _abandoned(abandoned, ended))
        self._guarded_tick(submit=False)
        self._log_memory_at_stop()

    def _tick(self, *, submit: bool = True) -> None:
        now = self._clock()
        # The tick is measured as a run is (ADR-0095 decision 5): what rose across
        # it, whether it ran the state layer's interval save, and every run in
        # flight at any point of it — the ones going now, and the ones that start
        # before it ends, which add themselves.
        with self._lock:
            self._tick_beside = {item.name for item in self._scheduled
                                 if item.run_started_mono is not None}
        held_before = self._resident()
        if submit:
            self._submit_due(now)
        saved = self._publish(now)
        held_after = self._resident()
        with self._lock:
            beside, self._tick_beside = tuple(self._tick_beside or ()), None
        during = "during the tick" + (", including a state save" if saved else "")
        rose = rise_text(*_rose(held_before, held_after), beside, during=during)
        if rose:
            logger.info("engine: %s", rose)
        self._log_memory()

    def _collect_after(self, before: Resident | None,
                       after: Resident | None) -> str:
        """The collection after a run that rose (ADR-0095 decision 8), and what it
        says on that run's line: the cycle collector, called where the run rose by
        :data:`~little_sister.limits.RISE_LOGGED` or more
        (:func:`_asks_for_a_collection`), and never for more than a hundredth of the
        time — one that took *p* is followed by none for
        :data:`~little_sister.limits.COLLECTION_SPACING` times *p*, and none starts
        while one runs, whichever run asked first. It walks the whole process, so it
        is the library's to call and no type's. ``""`` where none was called."""
        if self._collect is None or not _asks_for_a_collection(before, after):
            return ""
        with self._lock:
            started = self._clock()
            if started < self._collect_from:
                return ""
            self._collect_from = float("inf")
        try:
            self._collect()
        except Exception:
            # A bare log call and no self-report line: `gc.collect` does not raise,
            # so a collector that does is a caller's own, and the run it followed
            # is recorded and logged all the same — without the clause.
            logger.exception("engine: the collection after a run raised")
            return ""
        finally:
            took = max(0.0, self._clock() - started)
            with self._lock:
                self._collect_from = started + took * (1 + COLLECTION_SPACING)
        return collection_text(took, _fell(after, self._resident()))

    def _log_memory(self) -> None:
        """The process's figures in the log (ADR-0095 decision 3): at the first
        tick, as the baseline, and then on the first tick past each mark of
        :data:`~little_sister.limits.MEMORY_LINE_MINUTES` of the clock the log is
        stamped in, which is the configured zone's (ADR-0120 decision 9): the
        engine's instant is read on it. Read from what this tick's report
        recorded; the scheduler thread's alone, so the mark needs no lock."""
        wall = self._wall().astimezone(config.tzinfo)
        mark = (wall.date(), (wall.hour * 60 + wall.minute) // MEMORY_LINE_MINUTES)
        if mark == self._memory_mark:
            return
        first = self._memory_mark is None
        self._memory_mark = mark
        figures = self._report.memory_figures(self._report.memory)
        if figures is not None:
            logger.info("engine: memory%s — %s", " at the start" if first else "",
                        figures)

    def _log_memory_at_stop(self) -> None:
        """The last memory line (ADR-0095 decision 3), read fresh when the engine
        stops — after the stop's save, so that on a platform that keeps a peak it is
        the highest the process reached."""
        figures = self._report.memory_figures(self._resident())
        if figures is not None:
            logger.info("engine: memory at the stop — %s", figures)

    def _submit_due(self, now: float) -> None:
        executor = self._executor
        assert executor is not None
        with self._lock:
            for item in self._scheduled:
                if item.running or item.next_due > now:
                    continue
                # A check's units run one at a time: a unit due while another of
                # its check is in flight waits for the next tick, and keeps its slot.
                if id(item.check) in self._busy:
                    continue
                self._busy.add(id(item.check))
                item.running = True
                item.submitted_mono = now
                item.next_due = (now + item.unit.period_seconds
                                 + item.stagger)
                item.stagger = 0.0
                # the armed slot is the nominal one again; a non-OK completion
                # may pull it earlier (ADR-0033)
                item.retrying = False
                executor.submit(self._execute, item)

    def _publish(self, now: float) -> bool:
        # Retention on every tick (ADR-0087): each series held to its check's
        # count, a series no configured check keeps dropped — which is how a
        # series file written under another configuration meets this one — and,
        # past the ceiling, whole series evicted, the one written to longest ago
        # first. What it evicted is the `series` line the observation below records.
        swept = self._sweep_series()
        self._observe(now, swept)
        # The engine reports its own liveness as the heartbeat node (the
        # dashboard's status strip); if the scheduler stalls it goes stale and
        # degrades to at least WARN (ADR-0005). With nothing configured to watch,
        # the beat itself carries the WARN: the tree is *only* the heartbeat then,
        # so an OK here would roll up to an all-green root while nothing at all is
        # being monitored — the exact lie ADR-0005 exists to prevent.
        #
        # The beat is a branch (ADR-0076): the root carries the beat itself and
        # nothing else, and every report the instance makes about itself is a
        # child — the engine's own lines on /little-sister/engine, each
        # contributor's on /little-sister/<name> — each line a member entry with
        # the contributor's own slug so it can be pinned there, each child's code
        # the worst of what its lines claim (ADR-0042) and OK when nothing does,
        # and the root's the roll-up, which is what the status strip shows. A
        # child exists whether or not it has something to say: a node that only
        # appears when something is wrong is an absence a reader would have to
        # notice. Reading a contributor is recorded state, never a probe, and one
        # that raises is caught and named by the seam, so this stays a tick.
        #
        # What the branch states is a **tolerance**, not a period (ADR-0081).
        # Nothing on it is checked on an interval — the lines are recorded state
        # read on the tick, and readiness measured its trust store once, at
        # startup — so a `frequency` here would be the tick wearing a check's
        # word, which is what every surface then repeated. The stamp itself is not
        # free to drop: it is what makes a dead scheduler visible (ADR-0005), so
        # the tolerance the tick implies is stated outright and freshness reads
        # that. Same detection window, and no period for a surface to misreport.
        beat = max(1, round(self._poll_interval))
        tolerance = stale_after_seconds(beat)
        self._tree.upsert(
            HEARTBEAT_PATH, StatusCode.OK, (), members=True,
            description=HEARTBEAT_DESCRIPTION, stale_after=tolerance)
        # Every line on a child carries a code; what the speaker merely *knows* is
        # its report, on the child's page and never on a card (ADR-0044 decision
        # 6, ADR-0076 decision 1). Written through every tick, empty included, so
        # a fact the speaker no longer has does not outlive it.
        own = self._heartbeat_warning + tuple(self._report.lines())
        own_report = "\n\n".join(
            part for part in (self._heartbeat_report, self._report.report()) if part)
        self._tree.upsert(
            join_path(HEARTBEAT_PATH, ENGINE_REPORT), derive_code(own), own,
            members=True, description=CHILD_DESCRIPTION, stale_after=tolerance,
            title=ENGINE_TITLE, about=ENGINE_ABOUT, report=own_report)
        for report in self_report.current_reports():
            self._tree.upsert(
                join_path(HEARTBEAT_PATH, report.name), derive_code(report.lines),
                report.lines, members=True, description=CHILD_DESCRIPTION,
                stale_after=tolerance, title=report.title or None,
                about=report.about or None, report=report.report)
        # Expire maintenance pins past their window (ADR-0014); a real transition,
        # so the next check refills the node.
        self._tree.sweep_expired()
        # The kept state files, at most once per interval (ADR-0071) — and whether
        # this tick ran that save, which the tick's own line says (ADR-0095).
        if self._state is not None:
            return self._state.tick()
        return False

    def _sweep_series(self) -> Swept | None:
        """One sweep of the series under this configuration's retention and the
        ceiling (ADR-0087) — guarded, because a sweep that raised must not cost the
        tick its beat: it is a `runtime` line instead, and the series stay as they
        were until the next tick sweeps them."""
        try:
            swept = self._series.sweep(self.series_keep,
                                       ceiling=self._limits.series_limit)
        except Exception as error:
            logger.exception("engine: the series sweep raised")
            self_report.runtime.see(
                "series.sweep",
                plain(f"the series sweep raised ({error!r}); no series was held "
                      f"to its count or to the ceiling this tick"), log=False)
            return None
        if swept.dropped:
            logger.info("engine: dropped %d series no configured check keeps: %s",
                        len(swept.dropped),
                        ", ".join(f"{key.mount} ({key.subject})"
                                  for key in swept.dropped))
        return swept

    def _series_held(self, swept: Swept | None) -> SeriesHeld:
        """What the series hold after this tick's sweep, what it evicted, and the
        **projection**: what this configuration would need at today's estate —
        for every check that keeps a series, its ``series_keep`` times the series
        it holds times what one of its kept readings weighs on average. All of it
        measured and none of it declared, so it exists from the first tick after a
        check's first run and moves with an estate that grows (ADR-0087)."""
        needs: list[tuple[str, int]] = []
        for (type_name, mount), used in sorted(self._series.usage().items()):
            keep = self._series_keep.get((type_name, mount), 0)
            if keep < 1 or used.readings < 1:
                continue
            needs.append((f"{mount} ({type_name})",
                          round(keep * used.series * used.bytes / used.readings)))
        evicted = () if swept is None else tuple(
            f"{plain(key.mount)} ({plain(key.subject)})" for key in swept.evicted)
        return SeriesHeld(held=self._series.held(),
                          projection=sum(need for _path, need in needs),
                          needs=tuple(needs), evicted=evicted,
                          evicted_bytes=0 if swept is None else swept.evicted_bytes)

    def _observe(self, now: float, swept: Swept | None = None) -> None:
        """Record, for the engine's own lines (ADR-0072), what the schedule shows
        about itself at ``now``: the checks the pool has not started — a check
        that has never completed a run excepted, because the first sweep submits
        every check at once by design and a wait there is not saturation — and
        the runs that outgrew their period, the one in flight measured so far or
        the last one completed. The tree's entry count rides along, and so do the
        series — what they hold, what ``swept`` evicted and what they would need;
        the report measures the resident size itself."""
        waiting: list[Waiting] = []
        late: list[LateRun] = []
        with self._lock:
            for item in self._scheduled:
                if (item.running and item.run_started_mono is None
                        and item.submitted_mono is not None
                        and item.last_run_at is not None):
                    waiting.append(Waiting(item.node, now - item.submitted_mono))
                # The unit's own period, and its own node's path in the line
                # (ADR-0130 decision 5): `late.<path>` names the unit.
                period = item.unit.period_seconds
                if period <= 0:
                    continue
                if (item.run_started_mono is not None
                        and now - item.run_started_mono > period):
                    late.append(LateRun(item.node, now - item.run_started_mono,
                                        period, in_flight=True))
                elif (item.elapsed_seconds is not None
                        and item.elapsed_seconds > period):
                    late.append(LateRun(item.node, item.elapsed_seconds,
                                        period, in_flight=False))
        self._report.observe(now, entries=self._tree.entry_count,
                             waiting=waiting, late=late,
                             series=self._series_held(swept))

    def _newest(self, item: _Scheduled) -> tuple[Measurement, ...]:
        """The newest reading of every unit of ``item``'s check, this unit's first
        and the others in the order the check declared them (ADR-0130 decision 3):
        what the check is graded over after this unit's run. A unit that has not
        measured yet contributes nothing. Read under the engine lock."""
        others = [other for other in self._units[id(item.check)] if other is not item]
        return tuple(reading for entry in (item, *others)
                     for reading in (entry.latest or ()))

    def _execute(self, item: _Scheduled, once: bool = False) -> None:
        check = item.check
        unit = item.unit
        # A declared unit answers for a node of its own (ADR-0130): its run writes
        # its own path and is said of that node alone. The anonymous unit of a
        # check that declares none is the check itself, run as it always was. In
        # the log a run is the check's path, with the unit's key beside it where
        # there is one — not `item.name`, whose type suffix is for the rise's line.
        declared = bool(unit.key) or bool(unit.node)
        label = f"{check.path} [{unit.key}]" if unit.key else check.path
        ran = not check.secret_errors
        # The engine's one clock: the tick reads this start back against the
        # same clock to see a run that has outgrown its period while still in
        # flight, which an injected clock could not do against `time.monotonic`.
        started = self._clock()
        with self._lock:
            item.run_started_at = self._wall()
            item.run_started_mono = started
            # Who else is in flight (ADR-0095 decision 4): every run this one
            # overlaps at any point names it, and it names them — here for the runs
            # already going, there for the ones that start after it; and the tick
            # in progress, likewise.
            item.beside = set()
            for other in self._scheduled:
                if other is not item and other.run_started_mono is not None:
                    other.beside.add(item.name)
                    item.beside.add(other.name)
            if self._tick_beside is not None:
                self._tick_beside.add(item.name)
        # What the process holds as the run starts, against what it holds as it
        # ends: what rose across it is its log line's (ADR-0095 decision 4).
        held_before = self._resident()
        # **The two halves, in order** (ADR-0086): the check reads the world, then
        # says what it read means. `measured` is not `measurements` being empty —
        # a run that measured nothing on purpose is a reading too — it is whether
        # `measure_unit()` returned at all, which is what decides who owes the
        # failure record below. What is measured is this unit; what is graded is
        # the check, over the newest reading of every unit (ADR-0130 decision 3).
        measurements: tuple[Measurement, ...] = ()
        measured = False
        # When this run's reading was taken: ours, the one clock the grading is
        # handed and the one a series keeps beside the record's own times
        # (ADR-0087). `None` where nothing was read — a pinned check never went.
        observed_at: datetime | None = None
        # **What the seam refused, and what the engine says about it** (ADR-0093):
        # the records it marked inside this run's two halves, and a line per
        # reading whose record it refused, keyed by where that reading stands —
        # among the newest readings the grading is handed, this unit's first.
        refusals: list[Refusal] = []
        refused: dict[int, Entry] = {}
        # Whether `result` is the check graded whole, to be written on the unit's
        # path — or the check's own error, stored at its root as a check that raised
        # always was. And a declared unit's own failure, written on its node over
        # what the grading says of it (ADR-0078 decision 4: an ERROR for the unit
        # alone, its last reading kept).
        whole = False
        unit_failure: CheckResult | None = None
        try:
            if not ran:
                # Pinned (ADR-0023): a secret reference failed to resolve at
                # construction — report it, never measure, never retry. Nothing
                # was read, so nothing is recorded: this check did not fail to
                # reach its object, it never went.
                result = CheckResult(StatusCode.ERROR, [
                    plain(f"secret unresolvable: {error}")
                    for error in check.secret_errors])
            else:
                # **Lenient around the check's two halves, and nowhere else**
                # (ADR-0093 decision 5): inside them a record the seam refuses is
                # marked rather than raised, and costs its line or its reading
                # instead of the run. The engine's own records — the failure
                # record below among them — are built outside, strictly.
                # The measuring half alone may read what the check kept (ADR-0113
                # decision 4): the mark closes before the grading is called.
                with lenient_records(refusals), _measuring(check):
                    answer = check.measure_unit(unit.key)
                measurements = _measured(answer)
                measured = True
                # The clock is handed over rather than taken, so the grading is
                # replayable over old records: same inputs, same verdict — and
                # the instant it is handed is the reading's own `observed_at`.
                observed_at = self._wall()
                with self._lock:
                    item.latest = measurements
                    newest = self._newest(item)
                result, refused = self._grade(check, newest, observed_at, refusals)
                whole = True
        except Exception as error:  # any failure becomes an ERROR (ADR-0040)
            logger.exception("engine: check %s raised", label)
            # The message is untrusted — it routinely carries a captured line, a
            # path or an API error body — so it is escaped like any other folded-in
            # text (ADR-0018). The trace is a code block: verbatim and inert.
            reason = [plain(f"check error: {error}")]
            if config.stacktrace:
                reason.append(code("".join(traceback.format_exception(
                    error, limit=-TRACEBACK_FRAMES)).rstrip()))
            result = CheckResult(StatusCode.ERROR, reason)
            # A grading that raised over the readings that passed leaves the
            # refused ones refused: the node still says which, and why.
            result = _with_lines(result, list(refused.values()))
            whole = False
            # Only where the **measurement** is what raised. A grading that threw
            # over a reading that succeeded has not made that reading untrue, and
            # replacing it with `{"error": …}` would throw away the one thing this
            # run did get right.
            if not measured:
                measurements = _failure_measurement(check, error)
                observed_at = self._wall()
                if declared:
                    # The unit alone (ADR-0078 decision 4): it keeps its last
                    # reading, the check is graded over the newest readings it has,
                    # and the failure is written on the unit's node over that. A
                    # grading that raises in turn is the check's own error, at its
                    # root, as it always was.
                    unit_failure, refused = result, {}
                    try:
                        with self._lock:
                            newest = self._newest(item)
                        result, refused = self._grade(check, newest, observed_at,
                                                      refusals)
                        whole = True
                    except Exception as again:
                        logger.exception("engine: check %s raised in its grading",
                                         check.path)
                        result = _with_lines(
                            CheckResult(StatusCode.ERROR,
                                        [plain(f"check error: {again}")]),
                            list(refused.values()))
                        unit_failure = None
        finally:
            elapsed = self._clock() - started
            held_after = self._resident()
            with self._lock:
                item.running = False
                self._busy.discard(id(check))
                if ran:
                    # Keep the runtime even when the run raised — a hanging check
                    # that hit its timeout should show the full wait.
                    item.last_run_at = item.run_started_at
                    item.elapsed_seconds = elapsed
                item.run_started_at = None
                item.run_started_mono = None
                beside = tuple(item.beside)
                item.beside = set()
        if self._stop.is_set():
            # Abandoned by the stop (ADR-0088 decision 1): what a run delivers
            # after it is dropped — neither recorded nor saved.
            return
        elapsed_ms = elapsed * 1000
        # What rose while it ran, the process's, inside the parentheses — before
        # the reasons, whose truncation cannot reach it (ADR-0095 decision 4).
        rose = rise_text(*_rose(held_before, held_after), beside,
                         during="while it ran")
        # And after a run that rose, the collection, said on the same line, after
        # the rise (ADR-0095 decision 8).
        collected = self._collect_after(held_before, held_after)
        figures = "".join(f"; {said}" for said in (rose, collected) if said)
        # **The window** (ADR-0131 decisions 7 and 8): `max_since_ok` over what the
        # check kept of each subject and this run's reading of it, its line added
        # where the reading stands — before anything below reads the run, so that
        # the node, its roll-up, the log line and the retry all read its code. A
        # unit's failure is where its one reading stands; otherwise the unit's own
        # node, or the check's root where the unit is the check.
        if observed_at is not None:
            if unit_failure is not None:
                unit_failure = self._with_window(check, measurements, observed_at,
                                                 unit_failure)
            else:
                result = self._with_window(
                    check, measurements, observed_at, result,
                    node=unit.node if whole and declared else "")
        # What this run is **said of**: the check's root where the unit is the
        # check, and otherwise the unit's own node as the grading placed it — its
        # failure where it raised, `UNDEFINED` where the grading returned no node
        # for it. The log line, the retry and the readiness read it; the node's
        # own code, and what it rolls up to beside it wherever the two differ
        # (ADR-0099 decision 5).
        if unit_failure is not None:
            said = unit_failure
        elif whole and declared:
            said = _subtree(result, unit.node) or CheckResult(StatusCode.UNDEFINED)
        else:
            said = result
        rolled = _rolled_up(said)
        logger.info("check %s: %s%s (%.0f ms%s)%s", label,
                    said.stored_code.name,
                    "" if rolled is said.stored_code
                    else f", rolls up to {rolled.name}",
                    elapsed_ms, figures, _detail(said))
        _say_refused(check, refused, result)
        with self._lock:
            # Every completion, whatever it stored: this is what `outcomes` reads
            # to see a first pass finish and an instance whose every check is
            # erroring (ADR-0073). It is set before the retry block below, which
            # may or may not touch `last_code` and means something else by it.
            item.last_stored = said.stored_code
            # The largest record this run carried, written through on every
            # completion including one that carried none — the measurement is of
            # the last run, exactly like `elapsed_seconds` above it, and a figure
            # that outlived the run that produced it would be the drift this
            # measurement exists to make visible.
            item.record_bytes, item.record_refused = _largest_record(
                result, measurements, refusals)
        # A faster second look on failure (ADR-0033): a completion whose run rolls
        # up to a non-OK code pulls the armed slot earlier — never later — to the
        # retry interval, at most `retry_attempts` times per episode. A
        # secret-pinned check (`ran` False) is excluded: it is pinned until
        # restart (ADR-0023), so a fast retry would burn the pool confirming a
        # result that cannot change.
        #
        # **What the run rolls up to is what is read** (ADR-0125): `rolled`, the
        # code the log line above says, and not the root's own. A check that hands
        # back a branch says its failures on the nodes beneath its root —
        # `host-metrics` and `aws` declare nothing on theirs — and a failing disk
        # read by the root's code never pulled the next run in. It is the
        # result's roll-up, not the node's, for the reasons `_rolled_up` gives:
        # what this run read, which a pin cannot reach. For a declared unit it is
        # what the unit's own subtree rolls up to (ADR-0130 decision 5): its slot
        # is pulled in for its own failure, never for a sibling's.
        #
        # **An episode ends on any change of the reading** (ADR-0060 decision 4),
        # not only on an OK as ADR-0033 first had it. That record assumed a non-OK
        # check was a failing one; ADR-0042 then made a node's code derive from its
        # lines, so a check can sit at WARN for weeks as its ordinary state — and
        # under the old rule it spent its retries in the first few cycles and had
        # none left on the day its reading actually changed. Confirmation is worth
        # paying for when there is news, which is what a change is.
        #
        # **A completed UNDEFINED arms nothing.** A line that makes no claim is not
        # a failure to confirm, and the case that reaches here is structural — a
        # resource the provider gives no budget for — where asking again in ten
        # seconds cannot change the answer.
        if ran and item.retry_interval_seconds > 0 and item.retry_attempts > 0:
            with self._lock:
                if rolled is not item.last_code:
                    item.retry_used = 0
                    item.last_code = rolled
                if rolled is StatusCode.OK or rolled is StatusCode.UNDEFINED:
                    pass
                elif item.retry_used < item.retry_attempts:
                    pulled = self._clock() + item.retry_interval_seconds
                    if pulled < item.next_due:
                        item.retry_used += 1
                        item.retrying = True
                        item.next_due = pulled
        # The run's facts ride beside the result (ADR-0044): the wall time this
        # run took, and the armed slot projected onto the wall clock **once,
        # here** — the same projection info() makes, frozen at write time so a
        # failed poll later shows an honest absolute receding into the past.
        # After the retry block above, `next_due` is final for this run —
        # nominal re-arm or pulled-in slot, whichever won (ADR-0033) — never
        # `timestamp + frequency`. A one-shot run has no live schedule and
        # writes no next; a secret-pinned check never ran and writes no wall.
        # A declared unit's facts stand on its own node and on every container
        # between it and the mount, each with the earliest slot armed beneath it
        # (ADR-0130 decision 5).
        self._set_run_facts(item, wall_seconds=elapsed if ran else None,
                            once=once)
        # **Where the run's measurement lands.** One measurement is the run's own
        # reading of its object and belongs on the check's node — on the unit's
        # own node, for a declared unit — which is what every type in this
        # repository has. Several are the objects of one run, and which node,
        # child or line each stands for is the grading's to say — it has already
        # said it, in the tree it returned — so the engine places none of them and
        # the node's own reading is cleared.
        measurement = measurements[0] if len(measurements) == 1 else None
        try:
            if whole and declared:
                self._store_path(check.path, result, check,
                                 split_path(unit.node), is_root=True, unit=unit,
                                 measurement=measurement, failure=unit_failure)
            else:
                self._store(check.path, result, check, is_root=True,
                            measurement=measurement)
        except Exception as error:
            logger.exception("engine: failed to upsert %s", label)
            self_report.runtime.see(
                slug("upsert", item.node),
                plain(f"the result of {label} could not be stored "
                      f"({error!r}); the node shows the run before"), log=False)
        if observed_at is not None:
            self._keep_series(
                check, measurements, observed_at, result,
                refused if measured else None,
                placed=said if declared else None)

    def _with_window(self, check: Check, measurements: Sequence[Measurement],
                     observed_at: datetime, result: CheckResult, *,
                     node: str = "") -> CheckResult:
        """``result`` with the window's line on the node of each subject it fired
        for (ADR-0131 decisions 7 and 8): ``max_since_ok``, judged by the check over
        what it kept of the subject and this run's reading of it — each at its own
        time, the record's ``at`` where it gives one and when the engine took it
        otherwise, and each at the code it stands at — where the check keeps a
        series and its configuration writes a level of the window; ``result``
        unchanged everywhere else.

        A reading stands where :meth:`_keep_series` keeps it as standing: the one a
        run handed back alone, and one of several that names the check's own object
        and that no line carried, on ``node`` — the check's root, or the unit's own
        node, a path beneath it — at what stood there; one a line carried, on the
        node that line hangs on, at the line's code; any other, nowhere, and no
        window is judged for it. The store is read here and never by the check,
        which judges only what it is handed (decision 7).

        Guarded like the series: a window that could not be judged is a line on the
        instance's runtime node, and never the run's own result.
        """
        if check.series_keep < 1 or not check.grades_a_window:
            return result
        stood = _subtree(result, node)
        if stood is None:
            return result
        base = tuple(split_path(node))
        alone = len(measurements) == 1
        lines = [] if alone else _lines_at(result)
        taken: set[int] = set()
        windowed = result
        try:
            for measurement in measurements:
                subject = measurement.subject or (check.subject if alone else "")
                if not subject:
                    continue
                where: tuple[str, ...] | None
                if alone:
                    where, code = base, _placed(stood)[0]
                else:
                    where, code = _stands_at(measurement, lines, taken)
                    if where is None and subject == check.subject:
                        where, code = base, _placed(stood)[0]
                if where is None:
                    continue
                at = SeriesRecord(measurement.record, observed_at).at or observed_at
                kept = [(record.at or record.observed_at, record.code)
                        for record in self._series.window(
                            SeriesKey(check.type_name, check.path, subject))]
                line = check.window_line(at, [*kept, (at, code)], subject=subject)
                if line is not None:
                    windowed = _with_line_beneath(windowed, where, line)
        except Exception as error:
            logger.exception("engine: failed to judge the window of %s",
                             check.path)
            self_report.runtime.see(
                slug("window", check.path),
                plain(f"the window of {check.path} could not be judged "
                      f"({error!r}); its node says this run without it"),
                log=False)
            return result
        return windowed

    def _grade(self, check: Check, newest: Sequence[Measurement],
               observed_at: datetime, refusals: list[Refusal]
               ) -> tuple[CheckResult, dict[int, Entry]]:
        """The check graded whole over ``newest``, the readings it is handed —
        the engine's lines about the readings the seam refused added to its root
        — and those lines, keyed by where each refused reading stands among
        ``newest`` (ADR-0093 decision 3). What the grading raises, it raises."""
        # A reading whose record was refused is kept out of the grading, which
        # may read only records (ADR-0086 decision 6), and is the engine's to
        # report.
        refused = _refused_lines(check, newest)
        graded = tuple(reading for index, reading in enumerate(newest)
                       if index not in refused)
        if refused and not graded:
            # Nothing passed, so there is nothing to grade: the run stands as a
            # check that raised (ADR-0040), the refusals its reason, and each
            # reading keeps the failure record the seam gave it in place of what
            # it refused.
            return CheckResult(StatusCode.ERROR, list(refused.values())), refused
        with lenient_records(refusals):
            result = check.grade(graded, observed_at)
        if not isinstance(result, CheckResult):
            result = CheckResult(StatusCode.ERROR, ["check returned no result"])
        return _with_lines(result, list(refused.values())), refused

    def _set_run_facts(self, item: _Scheduled, *, wall_seconds: float | None,
                       once: bool) -> None:
        """The run facts a unit's run leaves (ADR-0044, ADR-0130 decision 5): on
        the node it answers for, its own armed slot; on every container between
        that node and the mount, and on the mount, the earliest slot armed among
        the check's units beneath it — the one-unit check's mount being the one
        node that is both. A one-shot run has no live schedule and writes no
        next."""
        mount = item.check.path
        segments = split_path(item.unit.node)
        paths = [join_path(mount, *segments[:depth])
                 for depth in range(len(segments) + 1)]
        if once:
            due = dict.fromkeys(paths, None)
        else:
            with self._lock:
                units = self._units[id(item.check)]
                now = self._clock()
                due = {
                    path: self._wall() + timedelta(seconds=max(0.0, min(
                        other.next_due for other in units
                        if _at_or_beneath(other.node, path)) - now))
                    for path in paths}
        for path in paths:
            self._tree.set_run_facts(path, wall_seconds=wall_seconds,
                                     next_run_at=due[path])

    def _period_beneath(self, check: Check, path: str) -> int:
        """The shortest period among ``check``'s units answering at or beneath
        ``path`` — what a container between the mount and a unit's node says it
        is read on (ADR-0130 decision 5)."""
        return min(item.unit.period_seconds for item in self._units[id(check)]
                   if _at_or_beneath(item.node, path))

    def _keep_series(self, check: Check, measurements: Sequence[Measurement],
                     observed_at: datetime, result: CheckResult,
                     refused: Mapping[int, Entry] | None = None, *,
                     placed: CheckResult | None = None) -> None:
        """Keep this run's readings in their subjects' series, where the check
        keeps one at all (ADR-0087).

        Which series is the check — its type and its mount — and the subject. The
        subject is the measurement's own, and falls back to the object the check
        declared only for the **one** measurement a run handed back alone, which
        is the one the engine places on the node (ADR-0086 decision 4); among
        several, an empty subject is no subject, and a reading with none has no
        series. Several readings of one subject are each kept by their own rule,
        in the order they were handed back: an identity replaces its record, a
        state the newest record where that one is in the same state, and a
        reading with neither appends.

        Each is kept with what **stood** where it landed. The one the engine
        placed keeps the node's code and texts as ``result`` wrote them — and
        where that root grades nothing, a branch check's container, what the
        check's own result rolls up to, beside whatever the root says
        (:func:`_placed`). One of
        several keeps the code and the text of the line the grading carried it
        onto, found by the record it carries as its ``data`` and the subject it
        names. One no line carried that names the object the check declared stood
        where the placed one stands, on the node, and keeps the same; any other
        reading no line carried stood nowhere and keeps neither. A reading whose
        record the seam refused keeps the failure record that took its place, beside
        the line the engine wrote about it — ``refused``, by where the reading stands
        — at the code that line carries (ADR-0093 decision 3): its own ``WARN`` on a
        node whose lines are coded, the node's where the node declares one.

        ``placed`` is the node the one reading a declared unit handed back alone
        is placed on — the unit's own, as the grading placed it, or its failure
        (ADR-0130) — and the check's root where it is ``None``.

        Guarded like the upsert before it: a history that could not be kept is
        worth a line, and never the reading the tree already holds.
        """
        if check.series_keep < 1:
            return
        alone = len(measurements) == 1
        lines = [] if alone else _lines_of(result)
        taken: set[int] = set()
        refused = refused or {}
        stood = result if placed is None else placed
        try:
            for index, measurement in enumerate(measurements):
                subject = measurement.subject or (check.subject if alone else "")
                if not subject:
                    continue
                if alone:
                    code, texts = _placed(stood)
                elif index in refused:
                    code = (StatusCode.WARN if result.code is None
                            else result.stored_code)
                    texts = (refused[index].text,)
                else:
                    code, texts = _line_of(measurement, lines, taken)
                    if code is None and subject == check.subject:
                        # No line carried it, and it names the check's own
                        # object: it stood on the node, as the placed one does.
                        code, texts = _placed(stood)
                self._series.add(
                    SeriesKey(check.type_name, check.path, subject),
                    SeriesRecord(measurement.record, observed_at,
                                 measurement.identity, code, texts,
                                 measurement.state),
                    keep=check.series_keep)
        except Exception as error:
            logger.exception("engine: failed to keep the series of %s",
                             check.path)
            self_report.runtime.see(
                slug("series", check.path),
                plain(f"the readings of {check.path} could not be kept in its "
                      f"series ({error!r}); its history misses this run"),
                log=False)

    def declare_nodes(self, nodes: Mapping[str, NodeMeta]) -> None:
        """Keep the deployment's ``nodes.yaml`` as loaded, for the claim a parent's
        ``children:`` makes of each child as it is written (ADR-0128). Called by the
        start, before the first tick, with the map it seeds the tree from."""
        self._nodes = dict(nodes)

    def _store(self, path: str, result: CheckResult, check: Check,
               *, is_root: bool = False,
               measurement: Measurement | None = None,
               period: int | None = None) -> None:
        """Upsert a result and its subtree into the status tree.

        The root node inherits the check's ``description``; child nodes carry
        their own. A root with no description leaves the node's description
        untouched (``None``) so a second check contributing to the same host node
        doesn't clobber it. ``config`` rides the same way (ADR-0013): the root takes
        the check's ``config_summary`` (empty where the container is shared, so it
        stays bare); each child carries its own slice. ``report`` — what the run
        *found*, beside config's what it ran *with* (ADR-0044) — rides the result
        on the root as on **every** child, because only the run can produce it,
        and writes through including the empty string: a roster the current run no
        longer finds must not outlive it. Every node inherits
        the check's ``frequency`` so freshness (ADR-0005) applies uniformly.
        Identity, observation time, maintenance and event-on-change stay the tree's
        concern (ADR-0007).

        ``measurement`` is the run's own reading, and it is the **root's** alone:
        the engine places one where the run read one object, and nothing where it
        read several, because which node, child or line each of those stands for
        is what the grading already said in the tree it returned. A child is
        therefore always stored with its reading cleared, which is the same
        write-through rule ``report`` follows and for the same reason.

        A branch check's ``about`` / ``title`` for its subnodes ride the same way,
        but only on **children** (ADR-0025): the root's labels keep their startup
        sources (``nodes.yaml`` / the inline check), so its result labels are
        ignored like its ``name``; each child's fill an empty node field only, so a
        ``nodes.yaml`` override still wins. Their **first** source is not the
        result at all but ``check.subnode_labels`` — the deployment's ``subnodes:``
        block resolved over what the type declared, keyed by subnode *name* at any
        depth, exactly like the flag below (ADR-0025). Per
        field: a resolved ``title`` and a stamped ``about`` coexist on one node,
        because that is how every other precedence in this pair works. The result's
        label is read where that map is silent for the name — the dynamically named
        child — and, whatever the map holds, for a child that says a run names it
        (the last paragraph).

        ``order`` (ADR-0055) fills an unset field the same way but is read on the
        **root too**, deliberately unlike the labels: a rank is not identity, and
        the reason the labels are root-ignored — the root has its own inline source
        in the check's YAML — does not hold for a rank, which has none. Zero is
        passed as ``None`` because ``0`` *is* what a check declaring nothing means,
        so it must not count as a declaration and shut out ``nodes.yaml``.

        ``show_when_quiet`` (ADR-0063) rides with the **labels**, not with the
        rank: it is root-ignored, because unlike ``order`` it *does* have an
        inline source of its own in the check's YAML — the root's declaration is
        that key, and a result overruling it would put a check's code ahead of the
        file the deployment edits. On a child the claim is the first statement the
        first look's layers make (:func:`little_sister.first_look.statement`, on
        the addresses the look's keys ride, ADR-0128): ``nodes.yaml``, the node's
        path and then its parent's ``children:``; the deployment's file, the node's
        name under ``subnodes:`` and then its parent's name entry's ``children:`` —
        the top level's for a child of the check's own node; then the type's
        ``subnode_defaults`` and ``node_defaults`` the same way. Each beats the
        value the child result carries — what a run stamps — because a declaration
        beats a stamp, as the file beats the check's code (ADR-0063 decision 3).
        What survives fills an unset field only, so a node's own ``nodes.yaml``
        entry, seeded before the first tick, still beats everything. Nothing is
        coerced on the way: a stated ``False`` travels as ``False``, because here
        it is a statement and not the "said nothing" that ``order``'s zero is.

        **A child a run names takes nothing declared for its name** (ADR-0118).
        Both maps are keyed by the names a type always emits, and a subject's node
        is named by its source (ADR-0106): a function called ``batch`` is not the
        ``batch`` aspect. A result that says ``dynamic`` is therefore read from
        itself alone — its own ``title``, ``about`` and ``show_when_quiet`` — and
        neither map is asked for its name, though its parent's ``children:`` speaks
        for it (ADR-0128), and the tree keeps that the run named it, for the first
        look and for its own children. It is said of that node and of none beneath
        it, and ``nodes.yaml``, seeded by path, still beats it.

        ``period`` is what every node of this subtree says it is read on — a
        declared unit's own, where this is the subtree the unit answers for
        (ADR-0130 decision 5) — and the check's ``frequency`` where none is given,
        which is the one-unit check.
        """
        self._store_one(path, result, check, is_root=is_root,
                        measurement=measurement, period=period)
        for child in result.children:
            self._store(join_path(path, child.name), child, check, period=period)
        self._prune_returned(path, result, check)

    def _store_one(self, path: str, result: CheckResult, check: Check,
                   *, is_root: bool, measurement: Measurement | None,
                   period: int | None) -> None:
        """One node of a result, upserted as :meth:`_store` says — the root's
        fields from the check, a child's from the result — with ``period`` as what
        it is read on, or the check's ``frequency`` where none is given."""
        description = (check.description or None) if is_root else result.description
        config = (check.config_summary() or None) if is_root else result.config
        # One guard per field, below: this lookup is harmless on a root (whose
        # name is a node path's last segment like any other) and the root's
        # exemption is stated where it is applied, once per label.
        labels: Mapping[str, str] = (
            {} if result.dynamic
            else check.subnode_labels.get(leaf_name(path), {}))
        about = None if is_root else (labels.get("about") or result.about or None)
        title = None if is_root else (labels.get("title") or result.title or None)
        order = result.order or None
        # Whether this run named the node, kept before anything is asked of it: the
        # claim below, and the first look, read it for this node and its children. A
        # root ignores it, as it ignores what a result says of its name.
        self._tree.note_named_by_run(path, result.dynamic and not is_root)
        declared = None if is_root else first_look.statement(
            "show_when_quiet", path, check=check, nodes=self._nodes,
            named_by_run=self._tree.named_by_run)
        show_when_quiet = None if is_root else (
            bool(declared) if declared is not None else result.show_when_quiet)
        # An about past about 400 characters is named once, when it first fills its
        # node (backlog #91 §3.5): a later run's fills nothing, and one nodes.yaml
        # declared keeps the field, so the run's never reaches the band to be named.
        # The tree is asked only for an about that long.
        long_about = (about if about is not None
                      and len(about.strip()) > ABOUT_NOTED_PAST
                      and not self._tree.about(path) else None)
        # The pre-normalized entries travel, not the raw input: the check has
        # already been through the one normalization (ADR-0036), and re-deriving
        # slugs here would be the same work done twice. `stored_code` is the
        # declared code, or the one derived from coded entries (ADR-0042).
        self._tree.upsert(path, result.stored_code, result.reason_entries,
                          members=result.members,
                          description=description,
                          frequency_seconds=(check.frequency_seconds
                                             if period is None else period),
                          config=config, report=result.report,
                          about=about, title=title, order=order,
                          show_when_quiet=show_when_quiet,
                          escalate_after=_escalate_after(check),
                          # The run's measurement travels with its reading: this
                          # run measured this object, and everything on the node is
                          # derived from it (ADR-0085, ADR-0086). Written through on
                          # every run including the one that measured nothing, which
                          # clears the last reading — the node's observation time
                          # moves with every run, so a kept record would not be
                          # undated but wrongly dated.
                          #
                          # The object is the measurement's where the check stated
                          # one — learned from an answer, as a rate-limit check asks
                          # whose token it holds — and otherwise the one the check
                          # declared at construction. That fallback exists only here,
                          # for the single measurement this places; among several an
                          # empty subject is no subject (ADR-0086 decision 4).
                          subject=("" if measurement is None
                                   else measurement.subject or check.subject),
                          record=(None if measurement is None
                                  else dict(measurement.record)))
        if long_about is not None:
            note_long_about(path, long_about)

    def _prune_returned(self, path: str, result: CheckResult,
                        check: Check) -> None:
        """**What this node no longer returns is removed, where it says that its
        children are complete** (ADR-0109 decisions 1 and 2) — after they are
        written, so the tree holds every child the run returned, and never a
        node another check owns. A result that says nothing leaves every child
        where it is. A child named by several segments stands beneath a node the
        tree made for its first, and that node is what the run returned here. A
        sibling subtree a unit's run did not write (ADR-0130 decision 4) is still
        among what the run returned, and stays."""
        if not result.children_complete:
            return
        returned = {segments[0] for child in result.children
                    if (segments := split_path(child.name))}
        gone = self._tree.prune(
            path, returned, protect=self._not_its_own.get(id(check), ()))
        # One line for each child that went, however much went with it.
        depth = len(split_path(path))
        beneath: dict[str, int] = {}
        for left in gone:
            top = join_path(*split_path(left)[:depth + 1])
            beneath[top] = beneath.get(top, 0) + (left != top)
        for top, count in beneath.items():
            logger.info(
                "check %s: %s is no longer reported, and was removed%s",
                check.path, top,
                f" with {count} node(s) beneath it" if count else "")

    def _store_path(self, path: str, result: CheckResult, check: Check,
                    segments: Sequence[str], *, is_root: bool, unit: Unit,
                    measurement: Measurement | None,
                    failure: CheckResult | None) -> None:
        """**A unit's run writes its own path** (ADR-0130 decision 4): from the
        mount down to the node the unit answers for, and the subtree beneath it —
        and nothing beside it. ``result`` is the check graded whole and ``segments``
        what is left of the unit's node beneath ``path``.

        A container on the way is written with its own lines, as the whole grading
        says them, and with the shortest period among the units beneath it; what it
        says of its children — that they are complete — is applied after the path
        beneath it is written, so a sibling the run returned and did not write
        stays, and one it no longer returns goes (ADR-0109). The unit's node takes
        its subtree whole, its own period, and the one reading the unit handed
        back alone; ``failure`` — the unit's own, where its measurement raised —
        is written over that node last, its children left where they are
        (ADR-0078 decision 4). Where the grading returned no node on the path, the
        containers above the gap are written and the walk ends there: what the
        grading did not return, the run does not write.
        """
        if not segments:
            self._store(path, result, check, is_root=is_root,
                        measurement=measurement, period=unit.period_seconds)
            if failure is not None:
                self._store_one(path, failure, check, is_root=is_root,
                                measurement=measurement,
                                period=unit.period_seconds)
            return
        self._store_one(path, result, check, is_root=is_root, measurement=None,
                        period=self._period_beneath(check, path))
        child, taken = _child_on(result, segments)
        if child is not None:
            self._store_path(join_path(path, child.name), child, check,
                             segments[taken:], is_root=False, unit=unit,
                             measurement=measurement, failure=failure)
        self._prune_returned(path, result, check)


def create_engine(config_dir: str | None = None, *,
                  tree: StatusTree = status_tree,
                  max_workers: int | None = None,
                  state: StateLayer | None = None,
                  limits: Limits | None = None) -> Engine:
    """Load checks from the ``checks`` aspect of ``config_dir`` (default
    ``config``, ADR-0031) into a new engine bound to ``tree`` (the shared
    :data:`status_tree` by default) and to ``state``, the application's state
    layer, when it keeps one (ADR-0071); ``limits`` are the engine's own
    (:mod:`~little_sister.limits`), derived from the machine when not given.

    A configuration tree with **no checks in it yet** is a real and temporary
    state — a fresh install, a deployment mid-bring-up — so the engine starts, a
    warning names the directories it searched, and that same sentence rides the
    heartbeat at WARN so the dashboard says it too, not just the log. (Having
    nowhere to *look* is a different thing entirely and already refused, in
    :func:`~little_sister.checks.loader.checks_dirs`.)
    """
    checks = load_checks(config_dir)
    warning: list[Entry] | None = None
    report = ""
    if not checks:
        searched = [str(directory.resolve())
                    for directory in checks_dirs(config_dir)]
        logger.warning("engine: no checks configured — nothing is being watched. "
                       "Searched: %s", ", ".join(searched))
        # A reason is Markdown (ADR-0018): a path is external text and must not be
        # read as emphasis — `/srv/ls_prod/config_dir/checks` would italicize
        # between its underscores. Same shape the check-error path two functions
        # up uses: the sentence through `plain`, the captured text through `code`.
        # One condition, two places: the sentence is the WARN line, the searched
        # paths are a fact and go in the engine's report (ADR-0076).
        warning = [Entry("no-checks",
                         plain("no checks configured — nothing is being watched; "
                               "the report says where it looked"),
                         code=StatusCode.WARN)]
        report = "Searched for checks in:\n\n" + code("\n".join(searched))
    return Engine(checks, tree, max_workers=max_workers,
                  heartbeat_warning=warning, heartbeat_report=report, state=state,
                  limits=limits)
