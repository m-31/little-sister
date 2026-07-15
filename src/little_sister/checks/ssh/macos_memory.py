"""macOS memory-health check (``macos-memory``): the early-warning signals.

Pipes the bundled ``memory-macos.sh`` to a Mac and reports the signs that RAM
trouble is *building* — before the host slows down or panics — as leaves **on
the host node**, beside the host metrics:

- ``pressure`` — the kernel's VM memory-pressure level (1 normal → OK,
  2 warning → WARN, 4 critical → ERROR), with the system-wide free percentage
  in the reason.
- ``swap`` — swap space in use (MB), graded by ``thresholds.swap``.
- ``compressor`` — memory occupied by the compressor as a percentage of
  physical RAM, graded by ``thresholds.compressor``. Compressor exhaustion is
  the kernel-panic signature on a small-RAM machine; ``host-metrics`` folds
  these pages into its single "used" number but can't see them specifically.
- ``processes`` (when configured) — one leaf per watched process pattern:
  RSS in MB summed over matching processes (graded per process) plus the
  oldest match's uptime. A slow leak shows as monotonic RSS growth here long
  before ``pressure`` moves, and a scheduled app restart shows as the uptime
  resetting. A process that isn't running reports **OK** — liveness belongs
  to other checks (e.g. a ``file`` heartbeat), this aspect only watches
  memory.

The SSH transport is shared with the ``host-metrics`` check
(:class:`SshScriptCheck`); this check carries no host description, so it sits
beside the host-metrics leaves on the same host node without overwriting it
(ADR-0015). The connection's advisory notices are surfaced by ``host-metrics``
on the shared node, not duplicated here.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, NamedTuple

from little_sister.checks.base import (
    CheckError,
    CheckResult,
    config_markdown,
    plain,
    register,
)
from little_sister.checks.ssh.base import SshScriptCheck, parse_descriptions
from little_sister.checks.ssh.metrics import (
    grade,
    human_duration,
    human_kb,
    oneline,
    parse_metrics,
    unavailable,
)
from little_sister.checks.ssh.transport import RemoteResult
from little_sister.status import StatusCode, join_path

DEFAULT_SCRIPT = "memory-macos.sh"

# (warn, error) — a value at or above the bound takes that status.
DEFAULT_THRESHOLDS: dict[str, tuple[float, float]] = {
    "swap": (4096.0, 8192.0),        # MB in use
    "compressor": (35.0, 50.0),      # percent of physical RAM
    "process": (1024.0, 2048.0),     # MB RSS per watched process
}

# The kernel's memorystatus levels; `grade(level, 2, 4)` maps them directly.
PRESSURE_WARN_LEVEL = 2.0
PRESSURE_ERROR_LEVEL = 4.0
PRESSURE_LABELS = {1: "normal", 2: "warning", 4: "critical"}

PRESSURE_DESCRIPTION = "Kernel VM memory-pressure level"
SWAP_DESCRIPTION = "Swap space in use"
COMPRESSOR_DESCRIPTION = "Memory occupied by the compressor, as % of RAM"
PROCESSES_DESCRIPTION = "Resident memory of watched processes"


class ProcessSpec(NamedTuple):
    """One watched process: a leaf name, the command-line substring to match,
    and its RSS thresholds in MB."""

    name: str
    pattern: str
    warn_mb: float
    error_mb: float


@register("macos-memory")
class MacosMemoryCheck(SshScriptCheck):
    """macOS memory pressure / swap / compressor / process RSS, reported beside
    the host metrics."""

    def __init__(self, *, thresholds: dict[str, tuple[float, float]],
                 processes: tuple[ProcessSpec, ...] = (),
                 descriptions: dict[str, str] | None = None,
                 **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.thresholds = thresholds
        self.processes = processes
        self.descriptions = descriptions or {}

    @classmethod
    def _extra_from_config(cls, config: dict[str, Any],
                           base_dir: Path) -> dict[str, Any]:
        thresholds = _parse_thresholds(config.get("thresholds"))
        return {
            **cls._connection_from_config(config, base_dir, DEFAULT_SCRIPT),
            "thresholds": thresholds,
            "processes": _parse_processes(config.get("processes"),
                                          thresholds["process"]),
            "descriptions": parse_descriptions(config.get("descriptions")),
        }

    def owned_nodes(self) -> set[str]:
        # Owns its aspect leaves beneath the host node, not the shared
        # container — so it sits beside the host-metrics leaves (ADR-0015).
        return {join_path(self.path, name) for name in self._aspects()}

    def _aspects(self) -> tuple[str, ...]:
        base = ("pressure", "swap", "compressor")
        return (*base, "processes") if self.processes else base

    def _describe(self, leaf: str, default: str) -> str:
        """A leaf's description: the ``descriptions:`` override or the built-in
        default (ADR-0012)."""
        return self.descriptions.get(leaf, default)

    def _threshold_md(self, aspect: str, unit: str) -> str:
        """Config Markdown for a graded leaf — its thresholds (ADR-0013)."""
        warn, error = self.thresholds[aspect]
        return config_markdown({"warn at": f"{warn:g}{unit}",
                                "error at": f"{error:g}{unit}"})

    def _script_args(self) -> list[str]:
        # $1 = the watch patterns, newline-separated (empty → none; the
        # placeholder keeps the debug flag in $2).
        if self.processes or self.debug:
            return ["\n".join(spec.pattern for spec in self.processes)]
        return []

    def run(self) -> CheckResult:
        result = self._run()
        failure = self._connection_failure(result)
        if failure is not None:
            return self._failed(plain(failure), result)
        metrics = parse_metrics(result.stdout)
        mismatch = metrics.get("profile_error")
        if mismatch:
            # the remote guard rejected the host (not Darwin) — a config error,
            # surfaced as a visible WARN rather than silent bad metrics.
            return self._failed(
                f"profile mismatch on {plain(self._target)}: {plain(mismatch)}",
                result, code=StatusCode.WARN)
        if not any(key in metrics for key in
                   ("pressure_level", "swap_used_mb", "compressor_pct")):
            return self._failed(
                f"connected, but no memory data from {plain(self._target)}: "
                f"{plain(oneline(result.stdout)) or 'empty output'}", result)
        children = [self._pressure(metrics), self._swap(metrics),
                    self._compressor(metrics)]
        if self.processes:
            children.append(self._processes(metrics))
        if self.debug:
            children.append(CheckResult(
                StatusCode.OK, self._debug_reason(result, metrics),
                name="debug", description="ssh / memory-script diagnostics"))
        return CheckResult(StatusCode.UNDEFINED, children=tuple(children))

    def _failed(self, reason: str, result: RemoteResult, *,
                code: StatusCode = StatusCode.ERROR) -> CheckResult:
        """Collection failed: every aspect leaf carries the reason — ERROR for
        a dead transport or no data, WARN for a config problem — so the host
        surfaces it (the shared ``ssh`` leaf belongs to ``host-metrics``)."""
        reasons = [reason, *self._debug_reason(result, {})]
        defaults = {"pressure": PRESSURE_DESCRIPTION, "swap": SWAP_DESCRIPTION,
                    "compressor": COMPRESSOR_DESCRIPTION,
                    "processes": PROCESSES_DESCRIPTION}
        return CheckResult(StatusCode.UNDEFINED, children=tuple(
            CheckResult(code, list(reasons), name=name,
                        description=self._describe(name, defaults[name]))
            for name in self._aspects()))

    # --- aspects ---

    def _pressure(self, metrics: dict[str, str]) -> CheckResult:
        description = self._describe("pressure", PRESSURE_DESCRIPTION)
        try:
            level = int(metrics["pressure_level"])
        except (KeyError, ValueError):
            return unavailable("pressure", description)
        label = PRESSURE_LABELS.get(level, f"level {level}")
        reason = label
        free = metrics.get("free_pct")
        if free:
            reason += f" — {plain(free)}% of memory free system-wide"
        config = config_markdown({
            "levels": "1 normal → OK, 2 warning → WARN, 4 critical → ERROR"})
        return CheckResult(
            grade(float(level), PRESSURE_WARN_LEVEL, PRESSURE_ERROR_LEVEL),
            [reason], name="pressure", description=description, config=config)

    def _swap(self, metrics: dict[str, str]) -> CheckResult:
        description = self._describe("swap", SWAP_DESCRIPTION)
        try:
            used = float(metrics["swap_used_mb"])
        except (KeyError, ValueError):
            return unavailable("swap", description)
        warn, error = self.thresholds["swap"]
        reason = f"{used:.0f} MB used"
        total = metrics.get("swap_total_mb")
        if total:
            reason += f" of {plain(total)} MB allocated"
        return CheckResult(grade(used, warn, error), [reason], name="swap",
                           description=description,
                           config=self._threshold_md("swap", " MB"))

    def _compressor(self, metrics: dict[str, str]) -> CheckResult:
        description = self._describe("compressor", COMPRESSOR_DESCRIPTION)
        try:
            pct = float(metrics["compressor_pct"])
        except (KeyError, ValueError):
            return unavailable("compressor", description)
        warn, error = self.thresholds["compressor"]
        compressed = human_kb(metrics.get("compressor_kb"))
        total = human_kb(metrics.get("mem_total_kb"))
        detail = f" — {compressed} of {total} RAM" if compressed and total else ""
        return CheckResult(grade(pct, warn, error),
                           [f"{pct:.0f}% compressed{detail}"],
                           name="compressor", description=description,
                           config=self._threshold_md("compressor", "%"))

    def _processes(self, metrics: dict[str, str]) -> CheckResult:
        description = self._describe("processes", PROCESSES_DESCRIPTION)
        children = tuple(
            self._process_leaf(i, spec, metrics)
            for i, spec in enumerate(self.processes, 1))
        return CheckResult(StatusCode.UNDEFINED, name="processes",
                           description=description, children=children)

    def _process_leaf(self, index: int, spec: ProcessSpec,
                      metrics: dict[str, str]) -> CheckResult:
        description = f"Resident memory of processes matching `{spec.pattern}`"
        config = config_markdown({"pattern": spec.pattern,
                                  "warn at": f"{spec.warn_mb:g} MB",
                                  "error at": f"{spec.error_mb:g} MB"})
        try:
            count = int(metrics[f"proc{index}_count"])
        except (KeyError, ValueError):
            return unavailable(spec.name, description)
        if count == 0:
            # Not running is OK here by design: this aspect watches memory
            # growth; liveness is another check's job (e.g. a file heartbeat).
            return CheckResult(StatusCode.OK, ["not running"], name=spec.name,
                               description=description, config=config)
        try:
            rss_mb = float(metrics[f"proc{index}_rss_kb"]) / 1024.0
        except (KeyError, ValueError):
            return unavailable(spec.name, description)
        noun = "process" if count == 1 else "processes"
        reason = f"{rss_mb:.0f} MB RSS over {count} {noun}"
        # Uptime of the oldest match — informative even when OK: a scheduled
        # restart/recycle shows up as the uptime resetting instead of growing.
        try:
            up = float(metrics[f"proc{index}_elapsed_seconds"])
        except (KeyError, ValueError):
            up = None
        if up is not None:
            reason += f", oldest up {human_duration(up)}"
        return CheckResult(grade(rss_mb, spec.warn_mb, spec.error_mb),
                           [reason], name=spec.name, description=description,
                           config=config)


def _parse_thresholds(raw: Any) -> dict[str, tuple[float, float]]:
    """Merge per-aspect ``{warn, error}`` overrides over the defaults
    (``swap`` in MB, ``compressor`` in %, ``process`` = the default RSS MB
    bounds for watched processes without their own)."""
    if raw is None:
        return dict(DEFAULT_THRESHOLDS)
    if not isinstance(raw, dict):
        raise CheckError("'thresholds' must be a mapping")
    parsed: dict[str, tuple[float, float]] = {}
    for aspect, (default_warn, default_error) in DEFAULT_THRESHOLDS.items():
        spec = raw.get(aspect) or {}
        if not isinstance(spec, dict):
            raise CheckError(f"thresholds.{aspect} must be a mapping")
        try:
            warn = float(spec.get("warn", default_warn))
            error = float(spec.get("error", default_error))
        except (TypeError, ValueError) as exc:
            raise CheckError(
                f"thresholds.{aspect}: warn/error must be numbers") from exc
        parsed[aspect] = (warn, error)
    return parsed


def _parse_processes(raw: Any,
                     default: tuple[float, float]) -> tuple[ProcessSpec, ...]:
    """Parse ``processes:`` — a list of ``{name, pattern, warn_mb, error_mb}``
    entries. ``name`` (the leaf) and ``pattern`` (the command-line substring)
    are required; the MB thresholds default to ``thresholds.process``."""
    if raw is None:
        return ()
    if not isinstance(raw, list):
        raise CheckError("'processes' must be a list of mappings")
    default_warn, default_error = default
    specs: list[ProcessSpec] = []
    names: set[str] = set()
    for i, item in enumerate(raw, 1):
        if not isinstance(item, dict):
            raise CheckError(f"processes[{i}] must be a mapping")
        name = str(item.get("name") or "").strip()
        pattern = str(item.get("pattern") or "").strip()
        if not name or not pattern:
            raise CheckError(
                f"processes[{i}] needs both 'name' (the leaf) and 'pattern' "
                "(the command-line substring to match)")
        if name in names:
            raise CheckError(f"processes[{i}]: duplicate name {name!r}")
        names.add(name)
        try:
            warn = float(item.get("warn_mb", default_warn))
            error = float(item.get("error_mb", default_error))
        except (TypeError, ValueError) as exc:
            raise CheckError(
                f"processes[{i}]: warn_mb/error_mb must be numbers") from exc
        specs.append(ProcessSpec(name, pattern, warn, error))
    return tuple(specs)
