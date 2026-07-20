"""A scripted ``demo`` check type for the live-demo harness (backlog #25, Mode 2).

Registered through the public ``CHECK_TYPES`` seam exactly as a deployment
registers its own types (``implementing-checks.md`` §4): the dev WSGI wrapper
(``demo_wsgi.py``) imports this module *before* the app, and the engine schedules
the checks like any other. Each ``run()`` is a **pure function of elapsed time** —
a monotonic start captured at construction — so a check replays its scenario on a
loop with no I/O and no stored state, fast enough that the transitions land on the
dashboard's ~10s poll. The scenarios drive the dynamics the static render harness
can't show: poll/swap, a growing reason list, an eruption's layout shift,
server-side staleness, and multi-node roll-up.

Dev-only: lives under ``tests/`` and never ships in the package.
"""
from __future__ import annotations

import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

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
                 period: float = _DEFAULT_PERIOD, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.scenario = scenario
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
        return {"scenario": scenario, "period": float(period)}

    def config_summary(self) -> str:
        return config_markdown(
            {"scenario": self.scenario, "period": f"{int(self._period)}s"})

    def run(self) -> CheckResult:
        elapsed = (time.monotonic() - self._start) % self._period
        return SCENARIOS[self.scenario](elapsed, self._period)
