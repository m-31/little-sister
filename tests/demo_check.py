"""A scripted ``demo`` check type for the live demo (testing-the-gui.md, Mode 2).

Registered through the public ``CHECK_TYPES`` seam exactly as a deployment
registers its own types (``implementing-checks.md`` §4): the dev WSGI wrapper
(``demo_wsgi.py``) imports this module *before* the app, and the engine schedules
the checks like any other. Each ``run()`` is a **pure function of elapsed time** —
a monotonic start captured at construction — so a check replays its scenario on a
loop with no I/O and no stored state, fast enough that the transitions land on the
dashboard's ~10s poll. ``LITTLE_SISTER_DEMO_OFFSET`` moves that start back, so a
server's start finds every scenario part-way into its cycle
(:data:`OFFSET_VARIABLE`). The scenarios drive the dynamics the static render harness
can't show: poll/swap, a growing reason list, an eruption's layout shift,
server-side staleness, and multi-node roll-up.

They also carry the demo's **member** producers, and they have to: membership is
declared in code (a mapping, or the ``entries`` flag beside a sequence), so no
amount of YAML could express it, and the library deliberately publishes no
member-shaped built-in — a demo type inside the package would be exactly the thing
ADR-0036 says not to ship. Both promises of decision 4 are demonstrated, and each
by the scenario that shows it cheapest:

* **derived** — ``audit`` with ``entries: true`` in its check config. Its finding
  texts are constant across runs and only the *count* grows, so each hash keeps its
  identity and a pin set on finding 7 survives the list swelling to 150 and back.
  That is the ergonomic claim — return a stable string and per-entry pins just work
  — proven by data that does not change at all.
* **declared** — ``reviews``, a mapping keyed by pull-request number, whose text
  re-words on *every run* while the key does not. A pin held across that re-wording
  is the identity claim; under a derived slug the same edit would drop it.

``eruption`` stays prose on purpose, so one dashboard carries a members node and a
prose node whose reason lists look alike and behave differently.

``pipelines`` carries the **coded** entries of ADR-0042: each workflow line
declares its own verdict plus a ``running`` flag, the check emits **no code of its
own** (the seam derives it), healthy lines are emitted on purpose — the per-aspect
choice a deployment makes — and the failed build's retry runs in italic while the
line stays red, which is the whole design in one line. Its build line also carries
its run's **record** (ADR-0082), the way a GitHub ``actions`` line does: the run it
last completed under a nested ``completed.at``, and the run in flight with its
``started`` beside a null ``ended`` — so the leaf page shows a line's times, in the
configured timezone, while the demo runs.

``workflows`` reads **several subjects in one run**, as a provider type does, and is
where the demo shows what a record the seam refuses costs (ADR-0093): twice a cycle
one repository's answer breaks the seam, and it costs that reading and nothing else.

``runs`` is the demo's **subject with a history** (ADR-0106, ADR-0111): four job
names, each handed back as a node of its own, each of their runs a reading with an
identity, so each node draws its runs as marks. Its source lists a job name's newest
few runs, and the grading says how each of them stood in ``for_record`` — but for
one job name, whose older runs so lose their verdict the moment a newer run takes
the line. One job name **comes and goes**, and the node above them says that its
children are complete (ADR-0109): that job name's node leaves the tree with the
first poll that does not find it, and is back with the first that does.

Dev-only: lives under ``tests/`` and never ships in the package.
"""
from __future__ import annotations

import math
import os
import time
from collections.abc import Callable, Sequence
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from little_sister import values
from little_sister.checks import (
    Check,
    CheckError,
    CheckResult,
    Entry,
    Measurement,
    config_markdown,
    parse_duration,
    register,
)
from little_sister.reasons import slug
from little_sister.status import StatusCode

_DEFAULT_PERIOD = 60.0

#: The environment variable that starts every scenario this far into its cycle — a
#: duration, written as a check config writes one (``LITTLE_SISTER_DEMO_OFFSET=36s``),
#: and wrapped by each scenario's own period. A scenario is a function of the time
#: since its check was built, so a start otherwise finds every node at the top of
#: its cycle, where none of them fails. With it a start finds the waiting node red:
#: the one thing the demo could not show was what a restart does to a wait
#: (ADR-0110), because no start of it ever found a failure.
OFFSET_VARIABLE = "LITTLE_SISTER_DEMO_OFFSET"

#: The one scenario whose reading is not the clock but a site's answer (ADR-0092):
#: what `http` records — a status and a response time, both null where the request
#: failed — so its node stands for the site its config names, and the series the
#: check keeps is drawn as a response-time curve. Its cycle carries the three things
#: the curve tells apart: a stretch in which every request fails (a marked break),
#: one run that hangs past the node's tolerance before it answers (a plain break —
#: nothing is read meanwhile, and the node goes stale), and the noise between.
LATENCY = "latency"
#: Where in its cycle the site fails every request, and where the one run hangs.
_LATENCY_FAILING = (0.30, 0.37)
_LATENCY_HANG = (0.60, 0.63)
_LATENCY_HANG_SECONDS = 45.0

#: The scenario that reads **several subjects in one run** (ADR-0093): the latest CI
#: run of three repositories, each its own reading, each graded into the line that
#: carries it. Twice a cycle a provider's answer breaks the seam for one of them —
#: ``octo/web``'s time comes without its offset, and ``octo/docs`` carries a log past
#: ``record_limit`` — and each costs its own reading and nothing else: the node says
#: which and why at WARN, the instance holds a line on its runtime node, and
#: ``/system`` marks the record it saw *refused*. The two stretches overlap, so for a
#: while both are refused at once and the third repository is graded alone.
WORKFLOWS = "workflows"
_REPOSITORIES = ("octo/api", "octo/web", "octo/docs")
_WORKFLOWS_NAIVE = (0.25, 0.60)
_WORKFLOWS_HEAVY = (0.45, 0.85)

#: The scenario whose subjects have a **history of runs** (ADR-0106, ADR-0111). Each
#: job name runs on the wall clock — its run *n* finishes *n* intervals after the
#: epoch — so a restart finds the runs it left and their series go on, and each
#: reading names the run it is of. Per job name: how many of the check's periods lie
#: between two of its runs; whether a run carries its run time, which the check's
#: ``measures:`` draws as a stem — a job name without one is drawn as ticks; and
#: whether the grading says how each listed run stood, in ``for_record``. `cleanup`
#: says it of its newest run alone, on its line: an older run of it is read again on
#: every poll and stands on no line, so it keeps no verdict.
RUNS = "runs"
_JOBS = (("import", 1, True, True), ("export", 3, True, True),
         ("cleanup", 2, False, False), ("backfill", 1, False, True))
#: The job name that **comes and goes** (ADR-0109): it runs for six intervals and
#: then not for three, and while it does not run its source does not list it. The
#: check hands back a node for each job name the source lists and says that these
#: are all of them, so this one's node is removed and returns — its kept runs
#: staying where they are, on its check's History page while it is gone.
_COMES_AND_GOES = "backfill"
_THERE, _GONE = 6, 3
#: How many of a job name's newest runs its source still lists.
_RUNS_LISTED = 6
#: Past this many seconds a run warns.
_RUNS_SLOW_SECONDS = 60
_RUN_CODES = {"succeeded": StatusCode.OK, "slow": StatusCode.WARN,
              "failed": StatusCode.ERROR}


def _ran(name: str, number: int) -> bool:
    """Whether run ``number`` of a job name took place: every one, but for the job
    name that comes and goes, which runs `_THERE` times and then `_GONE` times
    not."""
    return name != _COMES_AND_GOES or number % (_THERE + _GONE) < _THERE


def _run_record(name: str, number: int, interval: float,
                timed: bool) -> dict[str, Any]:
    """Run ``number`` of a job name as its source answers: how it ended, when, and
    — for a job that says so — how long it took. Every seventh run fails, early; a
    timed one that takes longer than the limit warns."""
    seconds = round(38 + 22 * math.sin(number * 0.9) + 9 * math.sin(number * 0.37))
    failed = number % 7 == 3
    record: dict[str, Any] = {
        "job": name, "run": number,
        "outcome": ("failed" if failed
                    else "slow" if timed and seconds > _RUNS_SLOW_SECONDS
                    else "succeeded"),
        "at": datetime.fromtimestamp(number * interval, UTC).isoformat()}
    if timed:
        record["seconds"] = 4 if failed else seconds
    return record


def _run_line(reading: Measurement) -> Entry:
    """What the grading says of one run, carrying its reading: on the job name's
    node for its newest run, and for the record alone for an older one."""
    record = reading.record
    took = f" in {record['seconds']}s" if "seconds" in record else ""
    return Entry("newest", f"run {record['run']} {record['outcome']}{took}",
                 _RUN_CODES[str(record["outcome"])], subject=reading.subject,
                 data=dict(record))


def _runs_graded(measurements: Sequence[Measurement]) -> CheckResult:
    """A node for each job name the source lists (ADR-0106): its line carries its
    newest run, and each older run the source still lists has a line for the record
    alone (ADR-0111) — where the job name's grading says so. The source was read
    whole, so these are every job name there is, and the node says so: one it no
    longer hands back is removed (ADR-0109)."""
    children: list[CheckResult] = []
    for name, _every, _timed, said in _JOBS:
        lines = [_run_line(reading) for reading in measurements
                 if reading.subject == f"jobs/{name}"]
        if lines:
            children.append(CheckResult(
                name=name, reason=[lines[-1]],
                for_record=lines[:-1] if said else ()))
    return CheckResult(StatusCode.OK, children=tuple(children),
                       children_complete=True,
                       report=f"Read the newest {_RUNS_LISTED} runs of "
                              f"**{len(children)} job names**.")


# scenario name -> phase function: (elapsed-within-period, period) -> CheckResult.
Scenario = Callable[[float, float], CheckResult]
SCENARIOS: dict[str, Scenario] = {}


def _scenario(name: str) -> Callable[[Scenario], Scenario]:
    def add(fn: Scenario) -> Scenario:
        SCENARIOS[name] = fn
        return fn
    return add


@_scenario("escalate")
def _escalate(t: float, period: float) -> CheckResult:
    """OK → WARN → ERROR with a *growing* reason list → recover, on a loop."""
    f = t / period
    if f < 0.25:
        return CheckResult(StatusCode.OK)
    if f < 0.5:
        return CheckResult(StatusCode.WARN, ["p95 latency climbing — 320ms"])
    if f < 0.9:
        # the reason list grows across the error window (1 → 6 entries)
        count = 1 + int((f - 0.5) / 0.4 * 5)
        reasons = [f"worker `api-{i:02d}` unreachable — last heartbeat {i * 7}s ago"
                   for i in range(1, count + 1)]
        return CheckResult(StatusCode.ERROR, reasons)
    return CheckResult(StatusCode.OK)          # recovered


@_scenario("eruption")
def _eruption(t: float, period: float) -> CheckResult:
    """Mostly OK, then a periodic eruption of 12 linked failures, then recover."""
    if t / period < 0.7:
        return CheckResult(StatusCode.OK)
    reasons = [
        f"[nightly / job {i:02d} (shard {i}/12)]"
        f"(https://ci.example.com/andro-meda/little-sister/actions/runs/{9000 + i}) "
        f"failed"
        for i in range(1, 13)
    ]
    return CheckResult(StatusCode.ERROR, reasons)


@_scenario("flap")
def _flap(t: float, period: float) -> CheckResult:
    """Flip OK/ERROR each half-period — stresses the fragment swap and event log."""
    if t < period / 2:
        return CheckResult(StatusCode.OK)
    return CheckResult(StatusCode.ERROR, ["health probe failed — connection reset"])


@_scenario("silent")
def _silent(t: float, period: float) -> CheckResult:
    """A branch whose ``cache`` child *falls silent* mid-cycle: it is dropped from
    the result, so the tree stops re-observing it and it ages past the freshness
    threshold and shows **stale** (ADR-0005). It reappears fresh next cycle. This
    is the faithful, non-blocking way to demo staleness: the result says nothing
    of whether its children are complete, so the engine keeps the child it leaves
    out and lets it age (ADR-0109 decision 1) — where `runs` says so, and its
    missing child is removed."""
    f = t / period
    children = [CheckResult(StatusCode.OK, name="db")]
    if not (0.3 <= f < 0.8):
        children.append(CheckResult(StatusCode.OK, name="cache"))
    return CheckResult(StatusCode.OK, children=tuple(children))


@_scenario("audit")
def _audit(t: float, period: float) -> CheckResult:
    """A security-audit leaf that stays **OK** while its findings list swells
    from a handful to ~150 long lines across the cycle, then clears — the
    live twin of the ``security_findings_150`` fixture (``ui_fixtures.py``):
    a skyscraper card growing under the ~10s poll without ever leaving OK."""
    f = t / period
    if f >= 0.9:
        return CheckResult(StatusCode.OK)          # audit passed, list clears
    count = 5 + int(f / 0.9 * 145)
    reasons = [
        f"Resource Running End of Life Software — AWS SDK for Go (v1) "
        f"(little-sister-test-{1_700_000_000 + i * 137}-BIGBROTHER-{3000 + i})"
        for i in range(1, count + 1)
    ]
    return CheckResult(StatusCode.OK, reasons)


#: The review queue ``reviews`` replays: ``slug -> (title, hours already waited at
#: the top of the cycle)``. The slug is the pull request's own number, which is what
#: makes it a **declared** identity rather than a hash of the sentence: the line is
#: rebuilt with a new waiting time on every run and the key does not move.
_QUEUE: tuple[tuple[str, str, int], ...] = (
    ("pr-4821", "Bump ruff to 0.6.9", 5),
    ("pr-4830", "Retry budget: cap the fast attempts", 19),
    ("pr-4833", "Kiosk: keep the exit control reachable", 31),
    ("pr-4841", "Vendor Bootstrap for the render matrix", 52),
)

_FORGE = "https://forge.example.org/andro-meda/little-sister/pulls"


def _waiting(number: str, title: str, hours: int) -> str:
    """One queue line: waiting on a **reviewer**, and so actionable."""
    return f"[#{number}]({_FORGE}/{number}) {title} — waiting {hours}h for a reviewer"


@_scenario("reviews")
def _reviews(t: float, period: float) -> CheckResult:
    """A review queue with **declared** slugs — the identity half of ADR-0036
    decision 4, and the one thing no other scenario can show.

    Every line is rebuilt with a fresh waiting time each run, so the *text* changes
    on more or less every poll while the *key* — the pull request's number — stays
    put. A pin set on ``pr-4833`` holds straight through that; under a derived slug
    it could not, because there the slug **is** the wording. ``audit`` proves the
    other half from the other side (see the module docstring).

    Two more things are deliberate. The queue is **never empty**, because a per-line
    control that vanishes between polls is not clickable; and the set churns anyway
    — one entry arrives mid-cycle, another is merged near the end — so an entry pin
    can be watched through both. It is small enough (five or six lines) to pin every
    member and see what the node does then.
    """
    f = t / period
    aged = int(f * 24)
    reason = {slug: _waiting(slug.removeprefix("pr-"), title, hours + aged)
              for slug, title, hours in _QUEUE}
    if f < 0.85:            # merged near the end of the cycle, back next time
        # Not waiting on a *reviewer* — the demo extension's per-line provider
        # declines this one line and fills the rest, which is placement policy no
        # configured action could express (ADR-0034).
        reason["pr-4846"] = (f"[#4846]({_FORGE}/4846) Docs: name the two slug "
                             f"promises — changes requested, waiting on the author")
    if f >= 0.55:           # …and one opened mid-cycle
        reason["pr-4852"] = _waiting(
            "4852", "Demo: a members-declaring scenario", 1 + aged)
    return CheckResult(StatusCode.WARN, reason)


@_scenario("pipelines")
def _pipelines(t: float, period: float,
               at: datetime | None = None) -> CheckResult:
    """Coded entry lines (ADR-0042): each workflow carries its own verdict and the
    node derives — this scenario returns **no code of its own**, dogfooding the
    seam. ``web-build`` walks the design's one-line arc across the cycle: passed →
    a run in flight on a passing job (ok, italic) → failed (red, upright) → the
    retry running while the verdict stays red → recovered. ``api-tests`` stays
    green so the mixed list is mixed, ``deploy-gate`` waits mid-cycle (warn), and
    ``nightly-audit`` has never concluded (UNDEFINED: ignored by the derivation,
    ring cue). Healthy lines are emitted deliberately — the per-aspect choice
    ADR-0042 leaves to a deployment — and the list obeys the three-tier ordering
    rule (non-OK, then in-flight, then healthy and idle), so the failures stay
    above the ``reason_cap`` fold.

    ``at`` is the reading's own time. Given it, the build line carries its run's
    record, its times counted from it — a completed run at the point of the cycle
    its text says, a run in flight started where its *running …s* began — so the
    grading stays a function of the reading. Without it the lines carry none."""
    f = t / period

    def run(number: int, completed: float, running: int | None = None,
            started: float = 0.0) -> dict[str, Any] | None:
        """The build's record: run ``number`` completed at that fraction of the
        cycle, and run ``running`` in flight since ``started``."""
        if at is None:
            return None
        # whole seconds, as a source's own clock would write them
        cycle = (at - timedelta(seconds=t)).replace(microsecond=0)
        record: dict[str, Any] = {
            "workflow": "build", "branch": "main", "run_number": number,
            "completed": {"at": (cycle + timedelta(
                seconds=round(completed * period))).isoformat()}}
        if running is not None:
            record["running"] = {
                "run_number": running,
                "started": (cycle + timedelta(
                    seconds=round(started * period))).isoformat(),
                "ended": None}
        return record

    if f < 0.2:
        build = Entry("web-build",
                      "web (main) / build: passed in 8m14s (#4215)",
                      StatusCode.OK, data=run(4215, -0.1))
    elif f < 0.35:
        build = Entry("web-build",
                      f"web (main) / build: passed in 8m14s \u00b7 #4216 "
                      f"running {int((f - 0.2) * period)}s",
                      StatusCode.OK, running=True,
                      data=run(4215, -0.1, running=4216, started=0.2))
    elif f < 0.5:
        build = Entry("web-build",
                      "web (main) / build: failed after 8m21s (#4216)",
                      StatusCode.ERROR, data=run(4216, 0.35))
    elif f < 0.8:
        build = Entry("web-build",
                      f"web (main) / build: failed after 8m21s \u00b7 #4217 "
                      f"running {int((f - 0.5) * period)}s",
                      StatusCode.ERROR, running=True,
                      data=run(4216, 0.35, running=4217, started=0.5))
    else:
        build = Entry("web-build",
                      "web (main) / build: passed in 9m01s (#4217)",
                      StatusCode.OK, data=run(4217, 0.8))
    gate = (Entry("deploy-gate", "deploy (main) / gate: waiting for approval",
                  StatusCode.WARN)
            if 0.3 <= f < 0.9 else
            Entry("deploy-gate", "deploy (main) / gate: approved in 12s",
                  StatusCode.OK))
    lines = [build, gate,
             Entry("api-tests", "api (main) / tests: passed in 2m01s",
                   StatusCode.OK),
             Entry("nightly-audit", "nightly / audit: has never completed",
                   StatusCode.UNDEFINED)]

    def tier(entry: Entry) -> int:
        if entry.code in (StatusCode.ERROR, StatusCode.WARN):
            return 0
        return 1 if entry.running else 2

    lines.sort(key=tier)        # stable: emission order survives within a tier
    return CheckResult(reason=lines)


@_scenario("children")
def _children(t: float, period: float) -> CheckResult:
    """A host with disk/memory/load children in a shifting mix — a multi-node card
    whose roll-up moves as the children change, and the demo's **branch head**: it
    owns its container alone, so that container carries the run facts, its
    ``config`` and a ``report`` (ADR-0044), and `/status/hosts/nas` is where the
    node-facts block shows them.

    It is also where a **declared sibling rank** is visible (ADR-0055): these three
    read *disk, memory, load* — the order somebody walking a host thinks in — and
    the name sort would file `load` in the middle. Each child says its rank, so the
    row is the check's to arrange; delete the ``order=`` arguments and the card
    falls back to alphabetical, which is the whole demonstration."""
    f = t / period
    memory = (CheckResult(StatusCode.WARN, ["memory at 84%"], name="memory", order=2)
              if 0.4 <= f < 0.7
              else CheckResult(StatusCode.OK, name="memory", order=2))
    load = (CheckResult(StatusCode.ERROR, ["load average 14.2 (8 cores)"],
                        name="load", order=3)
            if 0.6 <= f < 0.9 else CheckResult(StatusCode.OK, name="load", order=3))
    # What the run **found**, and nothing that alarms: a roster is presence, an
    # entry is a claim (ADR-0044 decision 6). The volume list moves with the loop
    # so the write-through is visible on the page — a report is an output of this
    # run, not a caption that was true once. The child reports are the shape a
    # *shared* container's checks are told to use.
    volumes = 2 if f < 0.5 else 3
    mounts = "\n".join(f"- `/vol{index + 1}` — 3.6 TB, ext4"
                       for index in range(volumes))
    return CheckResult(StatusCode.OK, children=(
        CheckResult(StatusCode.OK, name="disk", order=1,
                    report=f"Volumes in scope:\n\n{mounts}"), memory, load),
        report=(f"Enumerated **{volumes + 2} devices** on this host: "
                f"{volumes} volume{'s' if volumes != 1 else ''}, one memory "
                f"bank, one load average.\n\nNothing here carries a verdict — "
                f"what would is a reason."))


#: The severity bands a cloud-posture scanner reports, in the order they mean
#: something — which is *not* their alphabetical order, and is the reason
#: ADR-0055 exists. Each entry is `(name, rank, about)`; the **title** is the
#: capitalized name, added deliberately so this one card demonstrates both halves
#: of its phase at once: the bands sort by rank, and none of them draws a title
#: that only repeats the name it sits beside.
#:
#: The two **labels** are declared rather than stamped (ADR-0025):
#: `_BAND_LABELS` below goes to the library as `subnode_defaults`, which
#: resolves it against any `subnodes:` block in `demo_config/checks/security_wiz.yaml`
#: and lets the engine write the result per band name. Add a `subnodes:` entry
#: there and the hover card changes with no code edit at all — that is the path
#: Mode 2 is showing.
_BANDS = (
    ("critical", 1, "Exploitable now, from outside. Page somebody."),
    ("high", 2, "Exploitable, or trivially chained into something that is."),
    ("medium", 3, "Worth a ticket this sprint."),
    ("low", 4, "Worth knowing. Not worth an interrupt."),
    ("informational", 5, "Nothing to do — inventory, posture notes, "
                         "an unused key that is nonetheless recorded."),
)

#: The band that **declines the density trade** (ADR-0063). `informational` is the
#: demo's inventory-shaped node: it never alarms however many lines it carries, so
#: under the ordinary rule its lines would show only while a *sibling* was red —
#: visibility by accident of an error, for the one band whose lines are read
#: because everything is fine. It says so, and keeps its box beside four siblings
#: that still chip. Point this at `"low"` and the box moves; set it to `""` and the
#: whole card chips again, which is the demonstration.
_SHOW_WHEN_QUIET = "informational"

#: The same bands in the shape the library takes — one entry per name, shaped like
#: the `subnodes:` block a deployment would write: the two labels, and the flag on
#: the one band that declines the density trade (ADR-0063 §2). One map is the
#: type's whole half of that block.
_BAND_LABELS: dict[str, dict[str, object]] = {
    name: {"title": name.capitalize(), "about": about,
           **({"show_when_quiet": True} if name == _SHOW_WHEN_QUIET else {})}
    for name, _, about in _BANDS}

#: What each band has found, per fifth of the loop. A row is one band's counts as
#: the cycle turns, so the whole arc is legible here rather than assembled out of
#: five sets of thresholds: quiet, an `informational`-only tree, a `medium`
#: finding, a `high` one on top, and finally the `critical` that turns the card red
#: — then everything clears at once, the way a scanner's next pass reads after a
#: fix lands.
_BAND_COUNTS: dict[str, tuple[int, ...]] = {
    "critical":      (0, 0, 0, 0, 1),
    "high":          (0, 0, 0, 2, 2),
    "medium":        (0, 0, 3, 3, 3),
    "low":           (0, 1, 1, 1, 1),
    "informational": (4, 4, 4, 4, 4),
}

#: The findings each band can be carrying, taken from the front as the count grows.
#: Distinct texts rather than one line repeated: a card showing the same sentence
#: three times reads as a bug in the harness, and every scenario here has to be
#: plausible enough that a reviewer trusts what it is demonstrating. They are also
#: **constant across runs**, like `audit`'s, so a derived slug would keep its
#: identity if this node were ever switched to members.
_BAND_FINDINGS: dict[str, tuple[str, ...]] = {
    "critical": (
        "`api-gw-prod` — bucket is public **and** writable on the deploy path",
    ),
    "high": (
        "`vpc-default` — security group allows `0.0.0.0/0` on port 22",
        "`ci-runner` — long-lived access key, last rotated 14 months ago",
    ),
    "medium": (
        "`billing-worker` — instance role is wider than the calls it makes",
        "`assets-cdn` — TLS policy still permits TLS 1.0",
        "`pg-main` — automated snapshots retained 3 days, policy says 14",
    ),
    "low": (
        "`nas-backup` — encryption at rest uses the account default key",
    ),
    "informational": (
        "`eu-central-1` — 41 resources inventoried, no posture change",
        "`sandbox` — account is untagged; owner unknown, nothing running",
        "`iam` — 2 unused roles recorded, neither reachable",
        "`billing` — reserved-instance coverage 61%",
    ),
}


def _band_code(name: str, count: int) -> StatusCode:
    """What a band's own findings make it. Deliberately not one rule for all five:
    a band's *name* is a severity, so `informational` is never an alarm however
    many lines it carries, and `low` says its piece at WARN at most. This is the
    mapping a real scanner plugin owns; the demo only has to be plausible."""
    if not count:
        return StatusCode.OK
    if name in ("informational", "low"):
        return StatusCode.OK
    if name == "medium":
        return StatusCode.WARN
    return StatusCode.ERROR


@_scenario("severity")
def _severity(t: float, period: float) -> CheckResult:
    """A cloud-posture scanner reporting into **severity bands** — the demo's
    ADR-0055 node, and the shape the `wiz` plugin publishes.

    Five children, each declaring its `order`, so the row reads
    *critical high medium low informational* rather than the alphabetical
    *critical high informational low medium* that files **nothing to do** third and
    puts **low before medium**. Delete the `order=` argument below and the row
    falls back to alphabetical on the next poll: that is the demonstration, and
    also the proof that a check declaring nothing is unaffected.

    Each band also carries a `title` that is only its own name capitalized — what a
    check hands back when it has nothing better to say — so the chips must read
    `critical`, never `critical Critical`. Both rules on one card. That title and
    the band's `about` are **declared** (`_BAND_LABELS` -> `subnode_defaults`) and
    resolved by the library, so nothing here stamps a label onto a child.

    It is also the demo's ADR-0063 node. `informational` declares
    `show_when_quiet` — in `_BAND_LABELS`, beside its label, which is where a type
    says a thing is a roster *by construction* — so in the dense view it keeps its
    box and its four inventory lines while its quiet siblings collapse to chips:
    the one band whose text is read *because* nothing is wrong, no longer visible
    only when something is (`_SHOW_WHEN_QUIET`). The counts below leave it holding
    four lines in every phase, so the box is never empty and the difference is on
    screen the whole cycle. Nothing here stamps the flag on a result — a band this
    check can name is declared, and the stamped channel is for a child only a run
    could name.

    The counts turn over five phases (`_BAND_COUNTS`), so the roll-up climbs
    green → amber → red and clears, with the *order of the chips never moving* —
    which is the property the rank has and a sort by live grade would not.
    """
    phase = min(int(t / period * len(_BAND_COUNTS["critical"])),
                len(_BAND_COUNTS["critical"]) - 1)
    children = []
    for name, rank, _ in _BANDS:
        count = _BAND_COUNTS[name][phase]
        children.append(CheckResult(
            _band_code(name, count),
            list(_BAND_FINDINGS[name][:count]),
            name=name, order=rank,
            report=f"{count} open finding{'' if count == 1 else 's'} "
                   f"in this band."))
    return CheckResult(StatusCode.OK, children=tuple(children),
                       report=f"Scanned **41 resources** across 3 accounts; "
                              f"{sum(_BAND_COUNTS[n][phase] for n, _, _ in _BANDS)} "
                              f"open finding(s) in total.")


@register("demo")
class DemoCheck(Check):
    """Replays a named ``scenario`` on a loop of ``period`` seconds — synthetic
    status for the live-demo harness. See the module docstring."""

    def __init__(self, *, scenario: str = "escalate",
                 period: float = _DEFAULT_PERIOD, entries: bool = False,
                 offset: float = 0.0, **kwargs: Any) -> None:
        # The band labels this type ships, declared for the library to resolve
        # (ADR-0025). Every scenario declares them, and only the `severity` one
        # emits children by those names — a declaration for a name a run never
        # produces is inert, which is what lets one type declare for all of them.
        super().__init__(subnode_defaults=_BAND_LABELS, **kwargs)
        self.scenario = scenario
        # `entries: true` reads a prose scenario's reason list as **members**
        # instead (ADR-0036) — a harness knob, not a model change: it exists so one
        # node can be compared both ways without editing code, and a real check
        # decides this where it builds its result. It cannot make a scenario that
        # already hands over a mapping any more member-shaped than it is.
        self.entries = entries
        self._period = period
        # `offset` seconds into the cycle already, as the environment said when
        # this check was built (OFFSET_VARIABLE).
        self._start = time.monotonic() - offset

    @classmethod
    def _extra_from_config(cls, config: dict[str, Any],
                           base_dir: Path) -> dict[str, Any]:
        scenario = str(config.get("scenario", "escalate"))
        if scenario not in SCENARIOS and scenario not in (LATENCY, WORKFLOWS, RUNS):
            known = ", ".join(sorted({*SCENARIOS, LATENCY, WORKFLOWS, RUNS}))
            raise CheckError(
                f"unknown demo scenario {scenario!r} (known: {known})")
        period = parse_duration(config.get("period"), int(_DEFAULT_PERIOD))
        if period <= 0:
            raise CheckError("demo 'period' must be positive")
        # Where the cycle starts is the environment's to say, not a config's: it
        # is one start's, and a walk asks for it without editing a committed file.
        # Read here, so that what is no duration is refused as a bad `period` is.
        offset = parse_duration(os.environ.get(OFFSET_VARIABLE), 0)
        # `subject` is this type's to read, as a URL is `http`'s: the object a
        # scenario that reads one names, so its readings have a series (ADR-0087).
        return {"scenario": scenario, "period": float(period),
                "offset": float(offset),
                "entries": values.flag(config, "entries"),
                "subject": str(config.get("subject", ""))}

    def config_summary(self) -> str:
        summary = {"scenario": self.scenario, "period": f"{int(self._period)}s"}
        if self.entries:
            summary["entries"] = "true"
        return config_markdown(summary)

    def measure(self) -> Measurement | Sequence[Measurement]:
        """Where this check is in its cycle — which is the whole of what it
        reads, because the world it watches is the clock (ADR-0086).

        No `subject`: this check has no object out there to name, and a made-up
        one would be worse than none. `at` is when it read the clock — the
        reading's own time, which the page shows in the configured timezone and the
        `pipelines` lines take their own times from.
        """
        if self.scenario == LATENCY:
            return self._answer()
        if self.scenario == WORKFLOWS:
            return self._workflows()
        if self.scenario == RUNS:
            return self._runs()
        return Measurement(record={
            "elapsed_seconds": round(
                (time.monotonic() - self._start) % self._period, 3),
            "period_seconds": self._period,
            "at": datetime.now(UTC).isoformat()})

    def _answer(self) -> Measurement:
        """The `latency` scenario's reading: a site's status and response time at
        this point of its cycle — or none of either where every request fails, and,
        once a cycle, after a hang no reading is taken through."""
        elapsed = (time.monotonic() - self._start) % self._period
        phase = elapsed / self._period
        if _LATENCY_HANG[0] <= phase < _LATENCY_HANG[1]:
            time.sleep(_LATENCY_HANG_SECONDS)
        if _LATENCY_FAILING[0] <= phase < _LATENCY_FAILING[1]:
            return Measurement(record={"status": None, "response_ms": None,
                                       "error": "timed out"})
        response_ms = round(190 + 70 * math.sin(2 * math.pi * phase)
                            + 18 * math.sin(elapsed * 1.7))
        return Measurement(record={"status": 200, "response_ms": response_ms})

    def _workflows(self) -> list[Measurement]:
        """The `workflows` scenario's readings: one per repository, its latest CI
        run and when it completed, as a provider answers — including, at two
        stretches of the cycle, the two ways that answer breaks the seam."""
        elapsed = (time.monotonic() - self._start) % self._period
        phase = elapsed / self._period
        now = datetime.now(UTC).replace(microsecond=0)
        readings: list[Measurement] = []
        for index, repository in enumerate(_REPOSITORIES):
            completed = now - timedelta(minutes=3 + 7 * index)
            record: dict[str, Any] = {
                "repository": repository, "workflow": "CI", "branch": "main",
                "run_number": 120 + index, "conclusion": "success",
                "completed": {"at": completed.isoformat()}}
            if (repository == "octo/web"
                    and _WORKFLOWS_NAIVE[0] <= phase < _WORKFLOWS_NAIVE[1]):
                record["completed"] = {
                    "at": completed.replace(tzinfo=None).isoformat()}
            if (repository == "octo/docs"
                    and _WORKFLOWS_HEAVY[0] <= phase < _WORKFLOWS_HEAVY[1]):
                record["log"] = "\n".join(
                    f"step {step}: uploaded artifact {step} of 90"
                    for step in range(1, 91))
            readings.append(Measurement(record=record, subject=repository))
        return readings

    def _runs(self) -> list[Measurement]:
        """The `runs` scenario's readings: every run of each job name its source
        still lists, each naming the run it is of — so a run read again on the next
        poll stays one record (ADR-0087 decision 3). The period is how long the
        fastest job name takes from one run to the next.

        A job name that is not running now is not listed, and has no reading. When
        it is listed again, its newest runs are: the ones of its last stretch among
        them, read again as the records they were."""
        now = time.time()
        readings: list[Measurement] = []
        for name, every, timed, _said in _JOBS:
            interval = every * self._period
            newest = int(now // interval)
            if not _ran(name, newest):
                continue
            listed: list[int] = []
            number = newest
            while number >= 0 and len(listed) < _RUNS_LISTED:
                if _ran(name, number):
                    listed.append(number)
                number -= 1
            for number in reversed(listed):
                readings.append(Measurement(
                    record=_run_record(name, number, interval, timed),
                    subject=f"jobs/{name}", identity=f"{name}-{number}"))
        return readings

    def grade(self, measurements: Sequence[Measurement],
              now: datetime) -> CheckResult:
        """The scenario, read off that one number — and so a demonstration of the
        seam as well as of a dashboard: hand this grading yesterday's record and
        it answers what it answered yesterday."""
        if self.scenario == RUNS:
            return _runs_graded(measurements)
        if self.scenario == WORKFLOWS:
            # one line per repository that was read, carrying its reading
            return CheckResult(reason=[
                Entry(slug(reading.subject, "ci"),
                      f"{reading.subject} (main) / CI: passed "
                      f"(#{reading.record['run_number']})",
                      StatusCode.OK, subject=reading.subject,
                      data=dict(reading.record))
                for reading in measurements])
        record = measurements[0].record
        if self.scenario == LATENCY:
            # graded as `http` grades its answer: from the record alone
            if record.get("status") is None:
                reason = record.get("error") or "no answer"
                return CheckResult(StatusCode.ERROR, [Entry(
                    "response", f"request failed: {reason}")])
            return CheckResult(StatusCode.OK, [Entry(
                "response",
                f"HTTP {record['status']} in {record['response_ms']} ms")])
        elapsed = float(record.get("elapsed_seconds") or 0.0)
        if self.scenario == "pipelines":
            # The one scenario whose lines carry records with times of their own,
            # counted from the reading's so that yesterday's record still grades
            # to yesterday's answer.
            stamp = record.get("at")
            result = _pipelines(elapsed, self._period,
                                datetime.fromisoformat(stamp)
                                if isinstance(stamp, str) else None)
        else:
            result = SCENARIOS[self.scenario](elapsed, self._period)
        if self.entries and not result.members:
            # `replace` re-runs `__post_init__`, which is where the reason list is
            # keyed — so this is the same normalization the check would have got by
            # passing `entries=True` in the first place, not a second code path.
            result = replace(result, entries=True)
        return result
