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

from pathlib import Path
from typing import Any

from little_sister.checks.base import (
    CheckError,
    CheckResult,
    config_markdown,
    plain,
    register,
)
from little_sister.checks.ssh.base import SshScriptCheck, parse_descriptions
from little_sister.checks.ssh.metrics import grade, oneline, parse_metrics, unavailable
from little_sister.checks.ssh.transport import RemoteResult
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

    def run(self) -> CheckResult:
        result = self._run()
        failure = self._connection_failure(result)
        if failure is not None:
            return self._failed(plain(failure), result)
        metrics = parse_metrics(result.stdout)
        if not any(key in metrics
                   for key in ("sys_temp_c", "cpu_temp_c", "drive_count")):
            return self._failed(
                f"connected, but no QNAP data from {plain(self._target)}: "
                f"{plain(oneline(result.stdout)) or 'empty output'}", result)
        children = [self._temperature(metrics), self._smart(metrics)]
        if self.debug:
            children.append(CheckResult(
                StatusCode.OK, self._debug_reason(result, metrics),
                name="debug", description="ssh / getsysinfo diagnostics"))
        return CheckResult(StatusCode.UNDEFINED, children=tuple(children))

    def _failed(self, reason: str,
                result: RemoteResult | None = None) -> CheckResult:
        """A transport failure marks both aspects ERROR so the host reddens."""
        debug = self._debug_reason(result, {}) if result is not None else []
        return CheckResult(StatusCode.UNDEFINED, children=(
            CheckResult(StatusCode.ERROR, [reason, *debug], name="temperature",
                        description=self._describe(
                            "temperature", TEMPERATURE_DESCRIPTION)),
            CheckResult(StatusCode.ERROR, [reason], name="smart",
                        description=self._describe("smart", SMART_DESCRIPTION)),
        ))

    # --- aspects ---

    def _temperature(self, metrics: dict[str, str]) -> CheckResult:
        children: list[CheckResult] = []
        for key, name, desc in (
                ("sys_temp_c", "system", "System temperature"),
                ("cpu_temp_c", "cpu", "CPU temperature")):
            if key in metrics:
                children.append(self._temp_leaf(name, metrics[key], desc))
        for bay, sub in _drives(metrics):
            if "temp_c" in sub:
                children.append(self._temp_leaf(
                    f"drive{bay}", sub["temp_c"], f"Drive {bay} temperature"))
        temp_desc = self._describe("temperature", TEMPERATURE_DESCRIPTION)
        if not children:
            return unavailable("temperature", temp_desc)
        return CheckResult(StatusCode.UNDEFINED, name="temperature",
                           description=temp_desc,
                           config=self._temp_threshold_md(),
                           children=tuple(children))

    def _temp_leaf(self, name: str, value: str, description: str) -> CheckResult:
        try:
            celsius = float(value)
        except ValueError:
            return unavailable(name, description)
        return CheckResult(grade(celsius, self.temp_warn, self.temp_error),
                           [f"{celsius:.0f} °C"], name=name,
                           description=description,
                           config=self._temp_threshold_md())

    def _smart(self, metrics: dict[str, str]) -> CheckResult:
        children: list[CheckResult] = []
        for bay, sub in _drives(metrics):
            status = sub.get("smart", "")
            if status and status != "--":
                children.append(_smart_leaf(f"drive{bay}", status))
        smart_desc = self._describe("smart", SMART_DESCRIPTION)
        if not children:
            return unavailable("smart", smart_desc)
        return CheckResult(StatusCode.UNDEFINED, name="smart",
                           description=smart_desc, children=tuple(children))


def _drives(metrics: dict[str, str]) -> list[tuple[str, dict[str, str]]]:
    """``(bay, fields)`` for each reported drive (``drive{i}_*`` → fields)."""
    try:
        count = int(metrics["drive_count"])
    except (KeyError, ValueError):
        return []
    drives = []
    for i in range(1, count + 1):
        prefix = f"drive{i}_"
        sub = {key[len(prefix):]: value for key, value in metrics.items()
               if key.startswith(prefix)}
        drives.append((sub.get("bay", str(i)), sub))
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
    try:
        return float(spec.get("warn", warn)), float(spec.get("error", error))
    except (TypeError, ValueError) as exc:
        raise CheckError(
            "thresholds.temperature: warn/error must be numbers") from exc
