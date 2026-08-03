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

Dev-only: lives under ``tests/`` and never ships in the package.
"""
from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import replace
from pathlib import Path
from typing import Any

from little_sister import values
from little_sister.checks.base import (
    Check,
    CheckError,
    CheckResult,
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


@_scenario("children")
def _children(t: float, period: float) -> CheckResult:
    """A host with disk/memory/load children in a shifting mix — a multi-node card
    whose roll-up moves as the children change."""
    f = t / period
    memory = (CheckResult(StatusCode.WARN, ["memory at 84%"], name="memory")
              if 0.4 <= f < 0.7 else CheckResult(StatusCode.OK, name="memory"))
    load = (CheckResult(StatusCode.ERROR, ["load average 14.2 (8 cores)"], name="load")
            if 0.6 <= f < 0.9 else CheckResult(StatusCode.OK, name="load"))
    return CheckResult(StatusCode.OK, children=(
        CheckResult(StatusCode.OK, name="disk"), memory, load))


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
