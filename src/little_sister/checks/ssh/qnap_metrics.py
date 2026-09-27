"""QNAP hardware health check (``qnap-metrics``): temperatures + per-drive SMART.

Pipes the bundled ``qnap-health.sh`` (which calls QTS's ``getsysinfo``) to the host
and reports two branches **on the host node**, beside the host metrics:

- ``temperature`` — ``system``, ``cpu`` (where the model exposes them) and one
  ``drive<bay>`` child per populated bay, in °C, graded by ``warn`` / ``error``
  thresholds.
- ``smart`` — one ``drive<bay>`` child per populated bay: ``GOOD`` → OK,
  ``Warning`` → WARN, anything else → ERROR.

The SSH transport is shared with the ``host-metrics`` check (:class:`SshScriptCheck`,
over a common :class:`SshConnection`); this check carries no host description, so it
sits beside the host-metrics check on the same host node without overwriting it.
The connection's non-PQ key-exchange warning is surfaced by ``host-metrics`` /
``ssh-connect`` on the shared node, not duplicated here.
"""
from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import datetime
from pathlib import Path
from typing import Any

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
    grade,
    oneline,
    parse_metrics,
    reading,
    readings,
    unavailable,
)
from little_sister.reasons import clip
from little_sister.status import StatusCode, join_path

DEFAULT_SCRIPT = "qnap-health.sh"
DEFAULT_TEMP_THRESHOLDS = (50.0, 60.0)   # °C (warn, error)
TEMPERATURE_DESCRIPTION = "Temperature (°C)"
SMART_DESCRIPTION = "Drive SMART status"

SMART_OK = {"GOOD", "OK", "PASSED", "NORMAL"}
SMART_WARN = {"WARNING", "WARN"}


@register("qnap-metrics")
class QnapMetricsCheck(SshScriptCheck):
    """QNAP temperatures + per-drive SMART, reported beside the host metrics."""

    def __init__(self, *, temp_warn: float, temp_error: float,
                 descriptions: dict[str, str] | None = None,
                 **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.temp_warn = temp_warn
        self.temp_error = temp_error
        self.descriptions = descriptions or {}

    @classmethod
    def _extra_from_config(cls, config: dict[str, Any],
                           base_dir: Path) -> dict[str, Any]:
        warn, error = _parse_temp_thresholds(config.get("thresholds"))
        return {
            **cls._connection_from_config(config, base_dir, DEFAULT_SCRIPT),
            "temp_warn": warn,
            "temp_error": error,
            "descriptions": parse_descriptions(config.get("descriptions")),
        }

    def _describe(self, leaf: str, default: str) -> str:
        """A leaf's description: the ``descriptions:`` override or the built-in
        default (ADR-0012)."""
        return self.descriptions.get(leaf, default)

    def owned_nodes(self) -> set[str]:
        # Owns its two aspect subtrees beneath the host node, not the shared
        # container — so it sits beside the host-metrics leaves (ADR-0015).
        return {join_path(self.path, "temperature"), join_path(self.path, "smart")}

    def _temp_threshold_md(self) -> str:
        """Config Markdown for a temperature leaf — its °C thresholds (ADR-0013)."""
        return config_markdown({"warn at": f"{self.temp_warn:g} °C",
                                "error at": f"{self.temp_error:g} °C"})

    # --- the two halves (ADR-0086) -------------------------------------------

    #: What a drive's own entry in the record holds. `smart` is a word the NAS
    #: chose (`GOOD`, `Warning`) and stays a string; `temp_c` is a number, and the
    #: key names its unit.
    DRIVE_KEYS = ("temp_c",)

    def measure(self) -> Measurement:
        """One SSH call, one `getsysinfo` script, one flat reading of this NAS —
        temperatures as numbers, SMART verdicts as the words the NAS uses, and a
        key it did not give standing as `None`."""
        result = self._run()
        record = self._transport_record(result)
        metrics = parse_metrics(result.stdout)
        record.update(readings(metrics, "sys_temp_c", "cpu_temp_c",
                               "drive_count"))
        # Under the script's own `drive{i}_` numbering, with its `bay` beside
        # each: the bay is the drive's identity, the index is only where it sat
        # in one run's output, and a record keeps both so neither has to be
        # guessed back later.
        for index in range(1, int(record.get("drive_count") or 0) + 1):
            prefix = f"drive{index}_"
            sub = {key[len(prefix):]: value for key, value in metrics.items()
                   if key.startswith(prefix)}
            record[f"{prefix}bay"] = sub.get("bay") or str(index)
            record[f"{prefix}temp_c"] = reading(sub.get("temp_c"))
            record[f"{prefix}smart"] = sub.get("smart") or None
        if not self._has_readings(record):
            record["output"] = clip(oneline(result.stdout),
                                    chars=TRANSPORT_TEXT_CHARS,
                                    budget=TRANSPORT_TEXT_BYTES)
        record.update({key: value for key, value in metrics.items()
                       if key.startswith("debug")})
        return Measurement(record=record)

    def _has_readings(self, record: Mapping[str, Any]) -> bool:
        """Did `getsysinfo` give us anything worth grading?"""
        return any(record.get(key) is not None
                   for key in ("sys_temp_c", "cpu_temp_c", "drive_count"))

    def grade(self, measurements: Sequence[Measurement],
              now: datetime) -> CheckResult:
        """The two aspect branches, derived from that one reading and this
        check's own thresholds. They sit **beside** the host-metrics leaves on a
        shared host node, which this check does not own (ADR-0015)."""
        record = measurements[0].record
        failure = self._connection_failure(record)
        if failure is not None:
            return self._failed(plain(failure), record)
        if not self._has_readings(record):
            said = plain(str(record.get("output") or "")) or "empty output"
            return self._failed(
                f"connected, but no QNAP data from {plain(self._target)}: "
                f"{said}", record)
        children = [self._temperature(record), self._smart(record)]
        if self.debug:
            children.append(CheckResult(
                StatusCode.OK, self._debug_lines(record),
                name="debug", description="ssh / getsysinfo diagnostics"))
        return CheckResult(StatusCode.UNDEFINED, children=tuple(children))

    def expected_record(self) -> int | None:
        """Not declared: how many bays this NAS has is the **estate's** answer and
        not the configuration's, and a check that cannot know its estate declares
        nothing rather than guessing (ADR-0075). The measured size stands beside
        the blank on ``/system``."""
        return None

    def _failed(self, reason: str,
                record: Mapping[str, Any] | None = None) -> CheckResult:
        """A transport failure marks both aspects ERROR so the host reddens."""
        debug = self._debug_lines(record) if record is not None else []
        return CheckResult(StatusCode.UNDEFINED, children=(
            CheckResult(StatusCode.ERROR, [reason, *debug], name="temperature",
                        description=self._describe(
                            "temperature", TEMPERATURE_DESCRIPTION)),
            CheckResult(StatusCode.ERROR, [reason], name="smart",
                        description=self._describe("smart", SMART_DESCRIPTION)),
        ))

    # --- aspects ---

    def _temperature(self, record: Mapping[str, Any]) -> CheckResult:
        children: list[CheckResult] = []
        for key, name, desc in (
                ("sys_temp_c", "system", "System temperature"),
                ("cpu_temp_c", "cpu", "CPU temperature")):
            if record.get(key) is not None:
                children.append(self._temp_leaf(name, record[key], desc))
        for bay, sub in _drives(record):
            if sub.get("temp_c") is not None:
                children.append(self._temp_leaf(
                    f"drive{bay}", sub["temp_c"], f"Drive {bay} temperature"))
        temp_desc = self._describe("temperature", TEMPERATURE_DESCRIPTION)
        if not children:
            return unavailable("temperature", temp_desc)
        return CheckResult(StatusCode.UNDEFINED, name="temperature",
                           description=temp_desc,
                           config=self._temp_threshold_md(),
                           children=tuple(children))

    def _temp_leaf(self, name: str, value: object,
                   description: str) -> CheckResult:
        if not isinstance(value, (int, float)):
            return unavailable(name, description)
        celsius = float(value)
        return CheckResult(grade(celsius, self.temp_warn, self.temp_error),
                           [f"{celsius:.0f} °C"], name=name,
                           description=description,
                           config=self._temp_threshold_md())

    def _smart(self, record: Mapping[str, Any]) -> CheckResult:
        children: list[CheckResult] = []
        for bay, sub in _drives(record):
            status = str(sub.get("smart") or "")
            if status and status != "--":
                children.append(_smart_leaf(f"drive{bay}", status))
        smart_desc = self._describe("smart", SMART_DESCRIPTION)
        if not children:
            return unavailable("smart", smart_desc)
        return CheckResult(StatusCode.UNDEFINED, name="smart",
                           description=smart_desc, children=tuple(children))


def _drives(record: Mapping[str, Any]) -> list[tuple[str, dict[str, Any]]]:
    """``(bay, fields)`` for each reported drive (``drive{i}_*`` → fields).

    Reads a record, which is also the shape the script's parsed output has —
    the measurement keeps the script's own `drive{i}_` numbering for exactly
    that reason, so one walk serves both sides of the seam."""
    count = record.get("drive_count")
    if not isinstance(count, (int, float)):
        return []
    drives = []
    for i in range(1, int(count) + 1):
        prefix = f"drive{i}_"
        sub = {key[len(prefix):]: value for key, value in record.items()
               if key.startswith(prefix)}
        drives.append((str(sub.get("bay") or i), sub))
    return drives


def _smart_leaf(name: str, status: str) -> CheckResult:
    upper = status.upper()
    if upper in SMART_OK:
        code = StatusCode.OK
    elif upper in SMART_WARN:
        code = StatusCode.WARN
    else:
        code = StatusCode.ERROR
    return CheckResult(code, [plain(status)], name=name,
                       description=SMART_DESCRIPTION)


def _parse_temp_thresholds(raw: Any) -> tuple[float, float]:
    """``thresholds: {temperature: {warn, error}}`` over the °C defaults."""
    warn, error = DEFAULT_TEMP_THRESHOLDS
    if raw is None:
        return warn, error
    if not isinstance(raw, dict):
        raise CheckError("'thresholds' must be a mapping")
    spec = raw.get("temperature") or {}
    if not isinstance(spec, dict):
        raise CheckError("thresholds.temperature must be a mapping")
    where = "thresholds.temperature"
    return (values.real(spec, "warn", default=warn, where=where),
            values.real(spec, "error", default=error, where=where))
