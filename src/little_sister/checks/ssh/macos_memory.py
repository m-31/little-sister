"""macOS memory-health check (``macos-memory``): the early-warning signals.

Pipes the bundled ``memory-macos.sh`` to a Mac and reports the signs that RAM
trouble is *building* — before the host slows down or panics — as leaves **on
the host node**, beside the host metrics:

- ``pressure`` — the kernel's VM memory-pressure level (1 normal → OK,
  2 warning → WARN, 4 critical → ERROR), with the system-wide free percentage
  in the reason.
- ``swap`` — swap space in use, graded by ``max_swap``.
- ``compressor`` — memory occupied by the compressor as a percentage of
  physical RAM, graded by ``max_compressor``. Compressor exhaustion is
  the kernel-panic signature on a small-RAM machine; ``host-metrics`` folds
  these pages into its single "used" number but can't see them specifically.
- ``processes`` (when configured) — one leaf per watched process pattern:
  RSS summed over matching processes (graded per process, ``max_rss``) plus the
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

import json
from collections.abc import Mapping, Sequence
from datetime import datetime
from pathlib import Path
from typing import Any, NamedTuple

from little_sister import values
from little_sister.checks.base import (
    CheckError,
    CheckResult,
    Measurement,
    config_markdown,
    plain,
    register,
)
from little_sister.checks.ssh.base import (
    TRANSPORT_TEXT_BYTES,
    TRANSPORT_TEXT_CHARS,
    SshScriptCheck,
    parse_descriptions,
)
from little_sister.checks.ssh.metrics import (
    human_duration,
    human_kb,
    parse_metrics,
    reading,
    readings,
    refuse_thresholds,
    unavailable,
)
from little_sister.grading import Graded
from little_sister.limits import format_weight
from little_sister.reasons import clip
from little_sister.status import StatusCode, join_path

DEFAULT_SCRIPT = "memory-macos.sh"

#: What one reading costs beside the transport half, in the bytes the seam counts
#: (ADR-0075): seven numbers under their own key names, and three more per watched
#: process. Ceilings — every value here is a number, and the only strings in this
#: record are clipped.
BASE_RECORD_BYTES = 256
PROCESS_RECORD_BYTES = 96

#: What this type's nodes are graded on, each on the node that grades it — the
#: curves it draws by default (ADR-0096 decision 6). A watched process is keyed by
#: its configured name, so one declaration is a curve for each (decision 2): the
#: slow leak its RSS shows long before pressure moves.
MEASURES: dict[str, dict[str, object]] = {
    "pressure_level": {"unit": "", "label": "Memory pressure level",
                       "node": "pressure"},
    # a percent of physical memory: its axis reaches 100 (ADR-0117)
    "compressor_pct": {"unit": "%", "label": "Compressed memory",
                       "node": "compressor", "axis_to": 100},
    "swap_used_mb": {"unit": "MiB", "label": "Swap used", "node": "swap"},
    "processes.*.rss_kb": {"unit": "KiB", "label": "Resident memory of *",
                           "node": "processes/*"},
}

#: What this type grades (ADR-0131), each a maximum and each level the last value
#: that passes: the kernel's memory-pressure level — 1 normal, 2 warning, 4
#: critical, so the defaults pass a normal level, warn at a warning and err at a
#: critical one — swap in use, the compressor's share of the RAM, and, in each
#: watched process's own entry, the resident memory of what matches it.
GRADINGS: dict[str, object] = {
    "max_pressure": {
        "sentence": "The kernel's memory-pressure level: 1 normal, 2 warning, 4 "
                    "critical.",
        "kind": "pair", "field": "pressure_level", "unit": "count",
        "warn": 1, "error": 2},
    "max_swap": {
        "sentence": "How much swap may be in use.",
        "kind": "pair", "field": "swap_used_mb", "unit": "size",
        "warn": "4 GiB", "error": "8 GiB"},
    "max_compressor": {
        "sentence": "How much of the RAM the compressor may occupy.",
        "kind": "pair", "field": "compressor_pct", "unit": "share",
        "warn": "35%", "error": "50%"},
    "processes.max_rss": {
        "sentence": "How much resident memory what a watched process's pattern "
                    "matches may hold, summed.",
        "kind": "pair", "field": "processes.*.rss_kb", "unit": "size",
        "warn": "1 GiB", "error": "2 GiB"},
}

#: What replaced each aspect of the retired `thresholds:` block, and the unit its
#: level is written with; a process's levels moved into its own entry.
RETIRED_THRESHOLDS = {"swap": ("max_swap", " MiB"),
                      "compressor": ("max_compressor", "%")}

PRESSURE_LABELS = {1: "normal", 2: "warning", 4: "critical"}

PRESSURE_DESCRIPTION = "Kernel VM memory-pressure level"
SWAP_DESCRIPTION = "Swap space in use"
COMPRESSOR_DESCRIPTION = "Memory occupied by the compressor, as % of RAM"
PROCESSES_DESCRIPTION = "Resident memory of watched processes"


class ProcessSpec(NamedTuple):
    """One watched process: a leaf name, the command-line substring to match, and
    what its own entry grades its resident memory with (ADR-0131)."""

    name: str
    pattern: str
    graded: Graded


@register("macos-memory")
class MacosMemoryCheck(SshScriptCheck):
    """macOS memory pressure / swap / compressor / process RSS, reported beside
    the host metrics."""

    def __init__(self, *,
                 processes: tuple[tuple[str, str, Mapping[str, Any]], ...] = (),
                 descriptions: dict[str, str] | None = None,
                 **kwargs: Any) -> None:
        super().__init__(measure_defaults=MEASURES, gradings=GRADINGS, **kwargs)
        # Each watched process's levels stand in its own entry, the block its
        # resident memory is graded in, read here so that a level that does not fit
        # stops the start naming the entry.
        block = self.grading_block("processes")
        self.processes = tuple(
            ProcessSpec(name, pattern, block.read(entry, f"processes[{index}]"))
            for index, (name, pattern, entry) in enumerate(processes, 1))
        self.descriptions = descriptions or {}

    @classmethod
    def _extra_from_config(cls, config: dict[str, Any],
                           base_dir: Path) -> dict[str, Any]:
        refuse_thresholds(
            config.get("thresholds"), RETIRED_THRESHOLDS,
            also="— and a watched process's levels, thresholds.process, are "
                 "max_rss_warn and max_rss_error in its own entry")
        return {
            **cls._connection_from_config(config, base_dir, DEFAULT_SCRIPT),
            "processes": _parse_processes(config.get("processes")),
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

    def _threshold_md(self, aspect: str) -> str:
        """Config Markdown for a graded leaf — the levels it was graded by
        (ADR-0013)."""
        return config_markdown({
            "graded": self.grading_summary(f"max_{aspect}") or "not graded"})

    def _script_args(self) -> list[str]:
        # $1 = the watch patterns, newline-separated (empty → none; the
        # placeholder keeps the debug flag in $2).
        if self.processes or self.debug:
            return ["\n".join(spec.pattern for spec in self.processes)]
        return []

    # --- the two halves (ADR-0086) -------------------------------------------

    #: The numbers this check reads, whatever it is configured to watch. The
    #: record's keys are its contract with whatever draws a curve over it later.
    BASE_KEYS = ("pressure_level", "free_pct", "swap_used_mb", "swap_total_mb",
                 "compressor_pct", "compressor_kb", "mem_total_kb")
    #: And, per watched process, what the script reports about it — under
    #: `processes`, keyed by the name the configuration gives the process, which
    #: is its node's (ADR-0096 decision 2).
    PROCESS_KEYS = ("count", "rss_kb", "elapsed_seconds")

    def measure(self) -> Measurement:
        """One SSH call, one script, one flat reading of this Mac's memory —
        with the script's `key=value` strings turned into the numbers a record
        holds and a key it did not give standing as `None`."""
        result = self._run()
        record = self._transport_record(result)
        metrics = parse_metrics(result.stdout)
        record.update(readings(metrics, *self.BASE_KEYS))
        if self.processes:
            # The script numbers them in the order the configuration lists them;
            # the name is the process's node, and its curve's (decision 2).
            record["processes"] = {
                spec.name: {key: reading(metrics.get(f"proc{index}_{key}"))
                            for key in self.PROCESS_KEYS}
                for index, spec in enumerate(self.processes, 1)}
        if metrics.get("profile_error"):
            record["profile_error"] = clip(metrics["profile_error"],
                                           chars=TRANSPORT_TEXT_CHARS,
                                           budget=TRANSPORT_TEXT_BYTES)
        self._say_it_failed(record, result.stdout,
                            readable=self._has_readings(record),
                            nothing="connected, but no memory data")
        record.update({key: value for key, value in metrics.items()
                       if key.startswith("debug")})
        return Measurement(record=record)

    def _has_readings(self, record: Mapping[str, Any]) -> bool:
        """Did the script give us a single memory number worth grading?"""
        return any(record.get(key) is not None for key in
                   ("pressure_level", "swap_used_mb", "compressor_pct"))

    def grade(self, measurements: Sequence[Measurement],
              now: datetime) -> CheckResult:
        """The aspect leaves, derived from that one reading and this check's own
        thresholds. They sit **beside** the host-metrics leaves on a shared host
        node, which this check does not own (ADR-0015)."""
        record = measurements[0].record
        failure = self._connection_failure(record)
        if failure is not None:
            return self._failed(plain(failure), record)
        mismatch = record.get("profile_error")
        if mismatch:
            # the remote guard rejected the host (not Darwin) — a config error,
            # surfaced as a visible WARN rather than silent bad metrics.
            return self._failed(
                f"profile mismatch on {plain(self._target)}: "
                f"{plain(str(mismatch))}", record, code=StatusCode.WARN)
        if not self._has_readings(record):
            said = plain(str(record.get("output") or "")) or "empty output"
            return self._failed(
                f"connected, but no memory data from {plain(self._target)}: "
                f"{said}", record)
        children = [self._pressure(record), self._swap(record),
                    self._compressor(record)]
        if self.processes:
            children.append(self._processes(record))
        if self.debug:
            children.append(CheckResult(
                StatusCode.OK, self._debug_lines(record),
                name="debug", description="ssh / memory-script diagnostics"))
        return CheckResult(StatusCode.UNDEFINED, children=tuple(children))

    def expected_record(self) -> int:
        """Seven numbers plus three per watched process under its configured
        name, beside the transport half — all of them countable from this check's
        own configuration (ADR-0075)."""
        return (self._transport_record_bytes() + BASE_RECORD_BYTES
                + sum(PROCESS_RECORD_BYTES + len(json.dumps(spec.name))
                      for spec in self.processes))

    def _failed(self, reason: str, record: Mapping[str, Any], *,
                code: StatusCode = StatusCode.ERROR) -> CheckResult:
        """Collection failed: every aspect leaf carries the reason — ERROR for
        a dead transport or no data, WARN for a config problem — so the host
        surfaces it (the shared ``ssh`` leaf belongs to ``host-metrics``)."""
        reasons = [reason, *self._debug_lines(record)]
        defaults = {"pressure": PRESSURE_DESCRIPTION, "swap": SWAP_DESCRIPTION,
                    "compressor": COMPRESSOR_DESCRIPTION,
                    "processes": PROCESSES_DESCRIPTION}
        return CheckResult(StatusCode.UNDEFINED, children=tuple(
            CheckResult(code, list(reasons), name=name,
                        description=self._describe(name, defaults[name]))
            for name in self._aspects()))

    # --- aspects ---

    def _pressure(self, record: Mapping[str, Any]) -> CheckResult:
        description = self._describe("pressure", PRESSURE_DESCRIPTION)
        value = record.get("pressure_level")
        if value is None:
            return unavailable("pressure", description)
        level = int(value)
        label = PRESSURE_LABELS.get(level, f"level {level}")
        reason = label
        free = record.get("free_pct")
        if free is not None:
            reason += f" — {_number(free)}% of memory free system-wide"
        config = config_markdown({
            "levels": "1 normal, 2 warning, 4 critical",
            "graded": self.grading_summary("max_pressure") or "not graded"})
        verdict = self.verdict("max_pressure", value=level)
        return CheckResult(verdict.code, [verdict.entry(reason)], name="pressure",
                           description=description, config=config)

    def _swap(self, record: Mapping[str, Any]) -> CheckResult:
        description = self._describe("swap", SWAP_DESCRIPTION)
        value = record.get("swap_used_mb")
        if value is None:
            return unavailable("swap", description)
        used = float(value)
        # In the units the swap curve is written in, so the node and its curve
        # write one figure one way (ADR-0096 decision 6), and graded as a size.
        verdict = self.verdict("max_swap", value=used * 1024 ** 2)
        reason = f"{_mib(used)} used"
        total = record.get("swap_total_mb")
        if isinstance(total, (int, float)):
            reason += f" of {_mib(float(total))} allocated"
        return CheckResult(verdict.code, [verdict.entry(reason)], name="swap",
                           description=description,
                           config=self._threshold_md("swap"))

    def _compressor(self, record: Mapping[str, Any]) -> CheckResult:
        description = self._describe("compressor", COMPRESSOR_DESCRIPTION)
        value = record.get("compressor_pct")
        if value is None:
            return unavailable("compressor", description)
        pct = float(value)
        verdict = self.verdict("max_compressor", value=pct)
        compressed = human_kb(record.get("compressor_kb"))
        total = human_kb(record.get("mem_total_kb"))
        detail = f" — {compressed} of {total} RAM" if compressed and total else ""
        return CheckResult(verdict.code,
                           [verdict.entry(f"{pct:.0f}% compressed{detail}")],
                           name="compressor", description=description,
                           config=self._threshold_md("compressor"))

    def _processes(self, record: Mapping[str, Any]) -> CheckResult:
        description = self._describe("processes", PROCESSES_DESCRIPTION)
        children = tuple(self._process_leaf(spec, record)
                         for spec in self.processes)
        return CheckResult(StatusCode.UNDEFINED, name="processes",
                           description=description, children=children)

    def _process_leaf(self, spec: ProcessSpec,
                      record: Mapping[str, Any]) -> CheckResult:
        description = f"Resident memory of processes matching `{spec.pattern}`"
        config = config_markdown({
            "pattern": spec.pattern,
            "graded": self.grading_summary("processes.max_rss", spec.graded)
            or "not graded"})
        watched = record.get("processes")
        sub = watched.get(spec.name) if isinstance(watched, Mapping) else None
        if not isinstance(sub, Mapping):
            sub = {}
        found = sub.get("count")
        if found is None:
            return unavailable(spec.name, description)
        count = int(found)
        if count == 0:
            # Not running is OK here by design: this aspect watches memory
            # growth; liveness is another check's job (e.g. a file heartbeat).
            return CheckResult(StatusCode.OK, ["not running"], name=spec.name,
                               description=description, config=config)
        rss_kb = sub.get("rss_kb")
        if rss_kb is None:
            return unavailable(spec.name, description)
        rss_mb = float(rss_kb) / 1024.0
        verdict = self.verdict("processes.max_rss", value=float(rss_kb) * 1024,
                               graded=spec.graded)
        noun = "process" if count == 1 else "processes"
        reason = f"{_mib(rss_mb)} RSS over {count} {noun}"
        # Uptime of the oldest match — informative even when OK: a scheduled
        # restart/recycle shows up as the uptime resetting instead of growing.
        up = sub.get("elapsed_seconds")
        if up is not None:
            reason += f", oldest up {human_duration(float(up))}"
        return CheckResult(verdict.code, [verdict.entry(reason)], name=spec.name,
                           description=description, config=config)


def _mib(size: float) -> str:
    """A size the script reports in MiB, as the curve beside it writes it."""
    return format_weight(round(size * 1024 ** 2))


def _number(value: object) -> str:
    """One of the record's numbers, folded into a reason.

    `reading` already hands back an `int` where the value is integral, so this is
    mostly `str` — but a record read back out of a series is data from outside
    this process, and a reason is Markdown (ADR-0018)."""
    if isinstance(value, float) and value.is_integer():
        return plain(str(int(value)))
    return plain(str(value))


def _parse_processes(
        raw: Any) -> tuple[tuple[str, str, Mapping[str, Any]], ...]:
    """Parse ``processes:`` — a list of ``{name, pattern}`` entries, each with its
    own ``max_rss_warn`` and ``max_rss_error`` where it re-sets them. ``name`` (the
    leaf) and ``pattern`` (the command-line substring) are required, and the entry is
    handed on whole, for the library to read its levels in (ADR-0131)."""
    if raw is None:
        return ()
    if not isinstance(raw, list):
        raise CheckError("'processes' must be a list of mappings")
    specs: list[tuple[str, str, Mapping[str, Any]]] = []
    names: set[str] = set()
    for i, item in enumerate(raw, 1):
        if not isinstance(item, dict):
            raise CheckError(f"processes[{i}] must be a mapping")
        name = values.text(item, "name").strip()
        pattern = values.text(item, "pattern").strip()
        if not name or not pattern:
            raise CheckError(
                f"processes[{i}] needs both 'name' (the leaf) and 'pattern' "
                "(the command-line substring to match)")
        if name in names:
            raise CheckError(f"processes[{i}]: duplicate name {name!r}")
        names.add(name)
        retired = [key for key in ("warn_mb", "error_mb") if key in item]
        if retired:
            write = ", ".join(
                f"max_rss_{key[:-3]}: {item[key]} MiB" for key in retired)
            raise CheckError(
                f"processes[{i}] {' and '.join(repr(key) for key in retired)} "
                f"{'is' if len(retired) == 1 else 'are'} retired: a process's "
                f"levels are a pair in its entry now, its level the last value that "
                f"passes — write {write} (ADR-0131)")
        specs.append((name, pattern, item))
    return tuple(specs)
