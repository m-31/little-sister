"""A scripted ``demo`` check type for the live demo (testing-the-gui.md, Mode 2).

Registered through the public ``CHECK_TYPES`` seam exactly as a deployment
registers its own types (``implementing-checks.md`` §4): the dev WSGI wrapper
(``demo_wsgi.py``) imports this module *before* the app, and the engine schedules
the checks like any other. Each ``run()`` is a **pure function of elapsed time** —
a monotonic start captured at construction — so a check replays its scenario on a
loop with no I/O and no stored state, fast enough that the transitions land on the
dashboard's ~10s poll. The scenarios drive the dynamics the static render harness
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
line stays red, which is the whole design in one line.

Dev-only: lives under ``tests/`` and never ships in the package.
"""
from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import replace
from pathlib import Path
from typing import Any

from little_sister import values
from little_sister.checks import (
    Check,
    CheckError,
    CheckResult,
    Entry,
    config_markdown,
    parse_duration,
    register,
)
from little_sister.status import StatusCode

_DEFAULT_PERIOD = 60.0

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
    is the faithful, non-blocking way to demo staleness — the engine never prunes
    an omitted child, it just lets it age."""
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
def _pipelines(t: float, period: float) -> CheckResult:
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
    above the ``reason_cap`` fold."""
    f = t / period
    if f < 0.2:
        build = Entry("web-build",
                      "web (main) / build: passed in 8m14s (#4215)",
                      StatusCode.OK)
    elif f < 0.35:
        build = Entry("web-build",
                      f"web (main) / build: passed in 8m14s \u00b7 #4216 "
                      f"running {int((f - 0.2) * period)}s",
                      StatusCode.OK, running=True)
    elif f < 0.5:
        build = Entry("web-build",
                      "web (main) / build: failed after 8m21s (#4216)",
                      StatusCode.ERROR)
    elif f < 0.8:
        build = Entry("web-build",
                      f"web (main) / build: failed after 8m21s \u00b7 #4217 "
                      f"running {int((f - 0.5) * period)}s",
                      StatusCode.ERROR, running=True)
    else:
        build = Entry("web-build",
                      "web (main) / build: passed in 9m01s (#4217)",
                      StatusCode.OK)
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
_BANDS = (
    ("critical", 1, "Exploitable now, from outside. Page somebody."),
    ("high", 2, "Exploitable, or trivially chained into something that is."),
    ("medium", 3, "Worth a ticket this sprint."),
    ("low", 4, "Worth knowing. Not worth an interrupt."),
    ("informational", 5, "Nothing to do — inventory, posture notes, "
                         "an unused key that is nonetheless recorded."),
)

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
    `critical`, never `critical Critical`. Both rules on one card.

    The counts turn over five phases (`_BAND_COUNTS`), so the roll-up climbs
    green → amber → red and clears, with the *order of the chips never moving* —
    which is the property the rank has and a sort by live grade would not.
    """
    phase = min(int(t / period * len(_BAND_COUNTS["critical"])),
                len(_BAND_COUNTS["critical"]) - 1)
    children = []
    for name, rank, about in _BANDS:
        count = _BAND_COUNTS[name][phase]
        children.append(CheckResult(
            _band_code(name, count),
            list(_BAND_FINDINGS[name][:count]),
            name=name, title=name.capitalize(), about=about, order=rank,
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
                 **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.scenario = scenario
        # `entries: true` reads a prose scenario's reason list as **members**
        # instead (ADR-0036) — a harness knob, not a model change: it exists so one
        # node can be compared both ways without editing code, and a real check
        # decides this where it builds its result. It cannot make a scenario that
        # already hands over a mapping any more member-shaped than it is.
        self.entries = entries
        self._period = period
        self._start = time.monotonic()

    @classmethod
    def _extra_from_config(cls, config: dict[str, Any],
                           base_dir: Path) -> dict[str, Any]:
        scenario = str(config.get("scenario", "escalate"))
        if scenario not in SCENARIOS:
            known = ", ".join(sorted(SCENARIOS))
            raise CheckError(
                f"unknown demo scenario {scenario!r} (known: {known})")
        period = parse_duration(config.get("period"), int(_DEFAULT_PERIOD))
        if period <= 0:
            raise CheckError("demo 'period' must be positive")
        return {"scenario": scenario, "period": float(period),
                "entries": values.flag(config, "entries")}

    def config_summary(self) -> str:
        summary = {"scenario": self.scenario, "period": f"{int(self._period)}s"}
        if self.entries:
            summary["entries"] = "true"
        return config_markdown(summary)

    def run(self) -> CheckResult:
        elapsed = (time.monotonic() - self._start) % self._period
        result = SCENARIOS[self.scenario](elapsed, self._period)
        if self.entries and not result.members:
            # `replace` re-runs `__post_init__`, which is where the reason list is
            # keyed — so this is the same normalization the check would have got by
            # passing `entries=True` in the first place, not a second code path.
            result = replace(result, entries=True)
        return result
