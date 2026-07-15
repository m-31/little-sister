"""Host-metrics check (``host-metrics``): disk / memory / CPU / load over SSH.

One SSH connection per run pipes a bundled metrics script to the host's shell and
parses its ``key=value`` output. The host's ``profile`` (``linux`` / ``macos`` /
``busybox``) selects both the script and the interpreter it's piped to — ``bash``
for linux/macos, ``sh`` for busybox (ADR-0009). The script only *measures* (it
emits raw numbers); this check applies the OK/WARN/ERROR thresholds and reports one
**branch**: a peer ``ssh`` transport leaf plus a node per aspect (``disk``,
``memory``, ``cpu``, ``load``), all siblings, each carrying its number even when OK
(project.md §2.7). The host node itself is OK once the host is reachable; the worst
aspect rolls up to it (ADR-0004).

The basic metrics need no elevated rights; ``sudo: true`` runs the script under
``sudo -n`` for deployments that extend it with root-only insights.
"""
from __future__ import annotations

from collections.abc import Callable
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
from little_sister.checks.ssh.metrics import (
    grade,
    human_duration,
    human_kb,
    oneline,
    parse_metrics,
    unavailable,
    volume_name,
)
from little_sister.checks.ssh.transport import RemoteResult
from little_sister.status import StatusCode, join_path

SSH_NODE_DESCRIPTION = "SSH connection used to collect the metrics"

# A host's ``profile`` selects the remote metrics script and the interpreter it's
# piped to. macOS still ships bash 3.2; a busybox host (a QNAP, an ASUS/ash
# router) often has no real bash at all — its ``/bin/bash`` is a symlink to
# busybox — so that profile is piped to ``sh`` and the scripts split by what
# userland each can rely on (ADR-0009).
PROFILES: dict[str, tuple[str, str]] = {
    # profile → (default script filename, remote interpreter) — resolved from the
    # packaged scripts unless overridden or shadowed (ADR-0021)
    "linux":   ("host-metrics-linux.sh", "bash"),
    "macos":   ("host-metrics-macos.sh", "bash"),
    "busybox": ("host-metrics-busybox.sh", "sh"),
}
DEFAULT_PROFILE = "linux"

# (warn, error) — a value at or above the bound takes that status. Disk/memory/cpu
# are percentages; load is the 1-minute average per CPU core. Sensible defaults;
# override per aspect in the check's YAML.
DEFAULT_THRESHOLDS: dict[str, tuple[float, float]] = {
    "disk": (80.0, 90.0),
    "memory": (85.0, 95.0),
    "cpu": (85.0, 95.0),
    "load": (0.8, 1.0),
}

# The leaf nodes this check owns beneath the host node: the peer ``ssh`` transport
# leaf plus one per metric. ``disk`` may itself fan out per-filesystem, but owning
# the ``disk`` subtree covers that. The host node itself is a shared container this
# check does not own — a peer (e.g. ``qnap-metrics``) adds its own leaves (ADR-0015).
METRIC_NODES = ("ssh", "disk", "memory", "cpu", "load")


@register("host-metrics")
class HostMetricsCheck(SshScriptCheck):
    """Collect disk/memory/cpu/load from a host over SSH and report the host node
    with a peer ``ssh`` leaf plus a leaf per metric (all siblings)."""

    def __init__(self, *, thresholds: dict[str, tuple[float, float]],
                 descriptions: dict[str, str] | None = None,
                 disk_path: str | None = None, profile: str = DEFAULT_PROFILE,
                 **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.thresholds = thresholds
        self.descriptions = descriptions or {}
        self.disk_path = disk_path
        self.profile = profile

    @classmethod
    def _extra_from_config(cls, config: dict[str, Any],
                           base_dir: Path) -> dict[str, Any]:
        profile = _parse_profile(config.get("profile"))
        default_script, interpreter = PROFILES[profile]
        return {
            **cls._connection_from_config(config, base_dir, default_script),
            "interpreter": interpreter,
            "profile": profile,
            "thresholds": _parse_thresholds(config.get("thresholds")),
            "descriptions": parse_descriptions(config.get("descriptions")),
            "disk_path": _parse_disk_path(config.get("disk_path")),
        }

    def owned_nodes(self) -> set[str]:
        return {join_path(self.path, node) for node in METRIC_NODES}

    def _ssh_config(self) -> str:
        """Config Markdown for the ``ssh`` transport leaf (ADR-0013)."""
        fields: dict[str, str | None] = {**self._connection_fields(),
                                         "profile": self.profile}
        return config_markdown(fields)

    def _threshold_md(self, aspect: str) -> str:
        """Config Markdown for a metric leaf — the grading thresholds it ran with
        (ADR-0013). ``load`` is a per-core average; the rest are percentages."""
        warn, error = self.thresholds[aspect]
        unit = "" if aspect == "load" else "%"
        return config_markdown({"warn at": f"{warn:g}{unit}",
                                "error at": f"{error:g}{unit}"})

    def _describe(self, leaf: str, default: str) -> str:
        """A leaf's description: the ``descriptions:`` override or the built-in
        default (ADR-0012)."""
        return self.descriptions.get(leaf, default)

    def _script_args(self) -> list[str]:
        # $1 = disk path to measure (empty → the script's per-OS default).
        if self.disk_path or self.debug:
            return [self.disk_path or ""]
        return []

    def run(self) -> CheckResult:
        result = self._run()
        failure = self._connection_failure(result)
        if failure is not None:
            return self._failed(failure, result, {})
        metrics = parse_metrics(result.stdout)
        mismatch = metrics.get("profile_error")
        if mismatch:
            # the remote guard rejected this profile (wrong OS family, or a busybox
            # userland under the linux profile) — a config error, surfaced as a
            # visible WARN rather than silent bad metrics.
            return self._failed(
                f"profile mismatch on {plain(self._target)}: {plain(mismatch)}",
                result, metrics, code=StatusCode.WARN)
        if not any(key in metrics
                   for key in ("disk_pct", "mem_pct", "cpu_pct", "load1")):
            return self._failed(
                f"connected, but no metrics from {plain(self._target)}: "
                f"{plain(oneline(result.stdout)) or 'empty output'}",
                result, metrics)
        # ssh is only the helper that fetches the metrics, not their parent: the
        # host node aggregates a peer ``ssh`` transport leaf and one leaf per
        # metric (all siblings).
        return CheckResult(StatusCode.UNDEFINED, children=(
            self._ssh_node(metrics, result), *self._children(metrics)))

    def _failed(self, reason: str, result: RemoteResult,
                metrics: dict[str, str], *,
                code: StatusCode = StatusCode.ERROR) -> CheckResult:
        """Collection failed: a host node whose only child is the ``ssh`` leaf,
        marked ``code`` — ERROR for a dead transport or no metrics, WARN for a
        config problem like a profile mismatch. No metric leaves this run."""
        reasons = [reason, *self._debug_reason(result, metrics)]
        return CheckResult(StatusCode.UNDEFINED, children=(
            CheckResult(code, reasons, name="ssh",
                        description=self._describe("ssh", SSH_NODE_DESCRIPTION),
                        config=self._ssh_config()),))

    def _ssh_node(self, metrics: dict[str, str],
                  result: RemoteResult) -> CheckResult:
        """The ``ssh`` transport leaf: OK, or WARN when ssh emitted an advisory
        (e.g. the post-quantum key-exchange notice)."""
        reasons = [self._summary(metrics)]
        notice = result.notice
        if notice:
            reasons.append(notice)
        reasons += self._debug_reason(result, metrics)
        return CheckResult(StatusCode.WARN if notice else StatusCode.OK,
                           reasons, name="ssh",
                           description=self._describe("ssh", SSH_NODE_DESCRIPTION),
                           config=self._ssh_config())

    # --- parsing the script output into a branch ---

    def _children(self, metrics: dict[str, str]) -> tuple[CheckResult, ...]:
        return (
            self._disk_aspect(metrics),
            self._percent_child(
                metrics, "memory", "mem_pct", "Memory in use",
                self._memory_reason),
            self._percent_child(
                metrics, "cpu", "cpu_pct", "CPU busy (100% − idle)",
                lambda values, pct: f"{pct:.0f}% busy"),
            self._load_child(metrics),
        )

    def _disk_aspect(self, metrics: dict[str, str]) -> CheckResult:
        """The ``disk`` aspect: a single leaf for one filesystem, or — when the
        script reported ``disk_count`` (``disk_path: all``) — a branch with one
        graded child per real filesystem, each named by its volume."""
        if "disk_count" not in metrics:
            return self._percent_child(
                metrics, "disk", "disk_pct",
                "Disk space used on the monitored filesystem", self._disk_reason)
        try:
            count = int(metrics["disk_count"])
        except ValueError:
            count = 0
        used: set[str] = set()
        children = []
        for i in range(1, count + 1):
            prefix = f"disk{i}_"
            sub = {key[len(prefix):]: value for key, value in metrics.items()
                   if key.startswith(prefix)}
            children.append(
                self._volume_child(volume_name(sub.get("path", ""), used), sub))
        if not children:
            return unavailable("disk", "Disk space per filesystem")
        return CheckResult(StatusCode.UNDEFINED, name="disk",
                           description=self._describe(
                               "disk", "Disk space used, per filesystem"),
                           config=self._threshold_md("disk"),
                           children=tuple(children))

    def _volume_child(self, name: str, sub: dict[str, str]) -> CheckResult:
        description = "Disk space used"
        try:
            pct = float(sub["pct"])
        except (KeyError, ValueError):
            return unavailable(name, description)
        warn, error = self.thresholds["disk"]
        free = human_kb(sub.get("avail_kb"))
        total = human_kb(sub.get("total_kb"))
        mount = sub.get("path", "")
        detail = f" — {free} free of {total}" if free and total else ""
        suffix = f" on {plain(mount)}" if mount else ""
        return CheckResult(grade(pct, warn, error),
                           [f"{pct:.0f}% used{detail}{suffix}"],
                           name=name, description=description,
                           config=self._threshold_md("disk"))

    def _percent_child(self, metrics: dict[str, str], name: str, key: str,
                       description: str,
                       reason: Callable[[dict[str, str], float], str]
                       ) -> CheckResult:
        try:
            pct = float(metrics[key])
        except (KeyError, ValueError):
            return unavailable(name, description)
        warn, error = self.thresholds[name]
        return CheckResult(grade(pct, warn, error), [reason(metrics, pct)],
                           name=name, description=self._describe(name, description),
                           config=self._threshold_md(name))

    @staticmethod
    def _disk_reason(metrics: dict[str, str], pct: float) -> str:
        free = human_kb(metrics.get("disk_avail_kb"))
        total = human_kb(metrics.get("disk_total_kb"))
        where = metrics.get("disk_path", "")
        detail = f" — {free} free of {total}" if free and total else ""
        suffix = f" on {plain(where)}" if where else ""
        return f"{pct:.0f}% used{detail}{suffix}"

    @staticmethod
    def _memory_reason(metrics: dict[str, str], pct: float) -> str:
        used = human_kb(metrics.get("mem_used_kb"))
        total = human_kb(metrics.get("mem_total_kb"))
        detail = f" — {used} of {total}" if used and total else ""
        return f"{pct:.0f}% used{detail}"

    def _load_child(self, metrics: dict[str, str]) -> CheckResult:
        name = "load"
        description = self._describe("load", "Load average per CPU core")
        try:
            load1 = float(metrics["load1"])
            ncpu = max(1, int(metrics.get("ncpu", "1")))
        except (KeyError, ValueError):
            return unavailable(name, description)
        per_core = load1 / ncpu
        warn, error = self.thresholds["load"]
        reason = (f"{per_core:.2f} per core — load1 {load1:.2f} over "
                  f"{ncpu} CPUs")
        return CheckResult(grade(per_core, warn, error), [reason],
                           name=name, description=description,
                           config=self._threshold_md("load"))

    def _summary(self, metrics: dict[str, str]) -> str:
        bits = []
        if metrics.get("os"):
            bits.append(plain(metrics["os"]))
        if metrics.get("ncpu"):
            bits.append(f"{plain(metrics['ncpu'])} CPUs")
        if metrics.get("uptime_seconds"):
            try:
                bits.append("up " + human_duration(float(metrics["uptime_seconds"])))
            except ValueError:
                pass
        host = metrics.get("hostname") or self.host
        return f"{plain(host)} reachable" + (" — " + ", ".join(bits) if bits else "")


def _parse_profile(value: Any) -> str:
    """The host's OS/userland ``profile`` → the metrics script + interpreter to
    use (see ``PROFILES``). Defaults to ``linux``; an unknown value is a config
    error so a typo can't silently fall back to the wrong script."""
    if value is None:
        return DEFAULT_PROFILE
    profile = str(value).strip().lower()
    if profile not in PROFILES:
        raise CheckError(
            f"unknown ssh profile {value!r}; choose one of "
            f"{', '.join(sorted(PROFILES))}")
    return profile


def _parse_disk_path(value: Any) -> str | None:
    """The disk target passed to the script: a single path, the literal ``all``,
    or a **list** of paths joined by newline (the script splits a multi-line value
    into one volume per line and reports a ``disk`` branch). A 1-item list is the
    same as that single path."""
    if isinstance(value, list):
        return "\n".join(str(item) for item in value if str(item)) or None
    return str(value) if value else None


def _parse_thresholds(raw: Any) -> dict[str, tuple[float, float]]:
    """Merge per-aspect ``{warn, error}`` overrides over the defaults."""
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
