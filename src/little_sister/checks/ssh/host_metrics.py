"""Host-metrics check (``host-metrics``): disk / memory / CPU / load over SSH.

One SSH connection per run pipes a bundled metrics script to the host's shell and
parses its ``key=value`` output. The host's ``profile`` (``linux`` / ``macos`` /
``busybox``) selects both the script and the interpreter it's piped to — ``bash``
for linux/macos, ``sh`` for busybox (ADR-0009). The script only *measures* (it
emits raw numbers); this check applies the OK/WARN/ERROR thresholds and reports one
**branch**: a peer ``ssh`` transport leaf plus a node per aspect (``disk``,
``memory``, ``cpu``, ``load``), all siblings, each carrying its number even when OK
(project.md §2.7). The host node itself is OK once the host is reachable; the worst
aspect rolls up to it (ADR-0039).

The basic metrics need no elevated rights; ``sudo: true`` runs the script under
``sudo -n`` for deployments that extend it with root-only insights.
"""
from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
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
    human_duration,
    human_kb,
    oneline,
    parse_metrics,
    reading,
    readings,
    unavailable,
    volume_name,
)
from little_sister.reasons import clip
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

#: The `disk_path` that means *every real filesystem* — the one shape whose record
#: size the host decides rather than the configuration (see `expected_record`).
ALL_VOLUMES = "all"

#: What one reading costs beside the transport half, in the bytes the seam counts
#: (ADR-0075): seven numbers and two short strings under their own key names, with
#: room — and, per filesystem of a `disk_path` list, three numbers and a mount
#: point. Both are ceilings: every string in this record is either clipped or a
#: mount path the host already keeps short.
BASE_RECORD_BYTES = 384
VOLUME_RECORD_BYTES = 128

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

# Per-aspect ``about`` (ADR-0025): the **type-inherent** subject metadata for the
# subnodes this check emits — what each aspect measures and how it grades — so every
# deployment's hover cards (ADR-0019) explain these leaves out of the box. The grading
# *thresholds* are deliberately not repeated here: they ride each leaf's ``config``
# (ADR-0013). This is the **declared default**, handed to the library as
# ``subnode_defaults`` and resolved there against the deployment's ``subnodes:``
# block (which may override it, or extend it with ``{default}``); ``nodes.yaml``
# still wins above both. This check reads none of that itself — under ADR-0025 the
# declaration *is* the whole of its part in it.
ABOUT: dict[str, str] = {
    "ssh": (
        "The SSH connection this check opens to collect the metrics — transport "
        "health, not a resource on the host. **OK** when the host answers and the "
        "script runs; **WARN** on an SSH advisory (e.g. the post-quantum key-exchange "
        "banner); **ERROR** when the connection or script fails (the metric leaves "
        "then can't be collected)."
    ),
    "disk": (
        "Percentage of a filesystem's space in use, read from the host's own `df`. "
        "Higher is worse — it grades **WARN** then **ERROR** as the volume fills. With "
        "`disk_path: all` it fans out to one graded child per filesystem. The "
        "warn/error thresholds are in this leaf's config."
    ),
    "memory": (
        "Percentage of RAM in use on the host. Higher is worse, grading **WARN** then "
        "**ERROR** as free memory runs low. The thresholds are in this leaf's config."
    ),
    "cpu": (
        "How busy the processor is — 100% minus its idle time. Higher is worse, "
        "grading **WARN** then **ERROR** as it saturates; each run is a one-shot "
        "reading, so a brief spike can read high while a sustained high is the real "
        "signal. The thresholds are in this leaf's config."
    ),
    "load": (
        "The 1-minute load average **normalized per CPU core** (load ÷ cores), so one "
        "number reads the same on a 2-core and a 32-core box. Around **1.0 per core** "
        "the CPUs are fully subscribed; higher means work is queuing. Grades **WARN** "
        "then **ERROR** upward; the thresholds are in this leaf's config."
    ),
}

#: The same map in the shape the library takes — ``name -> {title, about}``. This
#: family ships no ``title`` default (the aspect names read fine on their own), so
#: every entry states the one field.
SUBNODE_DEFAULTS: dict[str, dict[str, str]] = {
    name: {"about": text} for name, text in ABOUT.items()}


@register("host-metrics")
class HostMetricsCheck(SshScriptCheck):
    """Collect disk/memory/cpu/load from a host over SSH and report the host node
    with a peer ``ssh`` leaf plus a leaf per metric (all siblings)."""

    def __init__(self, *, thresholds: dict[str, tuple[float, float]],
                 descriptions: dict[str, str] | None = None,
                 disk_path: str | None = None, profile: str = DEFAULT_PROFILE,
                 **kwargs: Any) -> None:
        # The per-aspect labels this type ships (ADR-0025). Declared, not applied:
        # the library resolves them against the deployment's `subnodes:` block and
        # the engine writes the result per child name, so nothing below reads a
        # config key or layers a default.
        super().__init__(subnode_defaults=SUBNODE_DEFAULTS, **kwargs)
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

    def _volume_about(self) -> str:
        """The ``disk`` aspect's resolved ``about``, for the **per-volume** children
        of a ``disk_path: all`` run.

        Every other leaf here is named by the type — ``ssh``, ``disk``, ``memory``
        — so the library labels it from ``SUBNODE_DEFAULTS`` and this check hands
        over nothing. A volume is named by the *host* (``root``, ``data``, whatever
        `df` reported), which no declaration could have anticipated, so it takes
        the one channel left for a dynamic child: the label rides its
        ``CheckResult``. It reads the aspect's **resolved** text — the deployment's
        override included — rather than ``ABOUT``, so a `subnodes: {disk: …}` entry
        reaches the volumes exactly as it reaches the branch above them."""
        return self.subnode_labels.get("disk", {}).get("about", "")

    def _script_args(self) -> list[str]:
        # $1 = disk path to measure (empty → the script's per-OS default).
        if self.disk_path or self.debug:
            return [self.disk_path or ""]
        return []

    # --- the two halves (ADR-0086) -------------------------------------------

    #: The numbers this check reads out of the script, whatever the disk shape.
    #: Named here rather than inline because the record's keys are its contract
    #: with whatever draws a curve over it later, and a key that only exists
    #: inside one expression is a key nobody can find.
    BASE_KEYS = ("mem_pct", "mem_used_kb", "mem_total_kb", "cpu_pct",
                 "load1", "ncpu", "uptime_seconds")
    #: The numbers of a single measured filesystem, where `disk_path` names one.
    DISK_KEYS = ("disk_pct", "disk_avail_kb", "disk_total_kb")
    #: And of each filesystem of a `disk_path: all` (or list) run, per volume.
    VOLUME_KEYS = ("pct", "avail_kb", "total_kb")

    def measure(self) -> Measurement:
        """One SSH call, one script, **one flat reading** — and that is the whole
        point of this type as the case ADR-0085 decision 2 was written against.
        The five nodes the grading builds out of it are five renderings of one
        measurement, not five measurements, so there is one record here and no
        line for it to ride on.

        The script's `key=value` strings become **numbers** on the way in: the key
        already names the unit (`mem_used_kb`, `load1`) and what a curve is drawn
        from is a number, not the text a shell printed. A key the script did not
        give, or gave something unparseable for, stands as `None` rather than
        being left out, so every reading of this check has one shape.
        """
        result = self._run()
        record = self._transport_record(result)
        metrics = parse_metrics(result.stdout)
        record.update(readings(metrics, *self.BASE_KEYS))
        record["os"] = metrics.get("os") or None
        record["hostname"] = metrics.get("hostname") or None
        if "disk_count" in metrics:
            record.update(self._volume_readings(metrics))
        else:
            record.update(readings(metrics, *self.DISK_KEYS))
            record["disk_path"] = metrics.get("disk_path") or None
        # The remote guard's verdict, where it refused: a *configuration* fact
        # the grading turns into a visible WARN rather than silent bad metrics.
        if metrics.get("profile_error"):
            record["profile_error"] = clip(metrics["profile_error"],
                                           chars=TRANSPORT_TEXT_CHARS,
                                           budget=TRANSPORT_TEXT_BYTES)
        # Kept only where nothing parsed, which is the one sentence that needs
        # it: *connected, but no metrics — here is what it said instead*. On
        # every other run the script's own output is working state and stays
        # inside the check.
        if not self._has_readings(record):
            record["output"] = clip(oneline(result.stdout),
                                    chars=TRANSPORT_TEXT_CHARS,
                                    budget=TRANSPORT_TEXT_BYTES)
        # Anything the script labelled `debug*` rides through untouched, so the
        # `debug` lines can be rebuilt from the reading like every other line.
        record.update({key: value for key, value in metrics.items()
                       if key.startswith("debug")})
        return Measurement(record=record)

    def _volume_readings(self, metrics: dict[str, str]) -> dict[str, Any]:
        """The per-filesystem numbers of a `disk_path: all` (or list) run, flat
        and under the script's own names, because a record renders as its keys
        and `disk2_pct` is what a reader of one should see."""
        volumes: dict[str, Any] = {
            "disk_count": reading(metrics.get("disk_count"))}
        count = volumes["disk_count"] or 0
        for index in range(1, int(count) + 1):
            prefix = f"disk{index}_"
            volumes.update({
                f"{prefix}{key}": reading(metrics.get(f"{prefix}{key}"))
                for key in self.VOLUME_KEYS})
            volumes[f"{prefix}path"] = metrics.get(f"{prefix}path") or None
        return volumes

    def _has_readings(self, record: Mapping[str, Any]) -> bool:
        """Did the script give us a single number worth grading?"""
        if record.get("disk_count") is not None:
            return True
        return any(record.get(key) is not None
                   for key in ("disk_pct", "mem_pct", "cpu_pct", "load1"))

    def grade(self, measurements: Sequence[Measurement],
              now: datetime) -> CheckResult:
        """The five nodes, derived from that one reading and from this check's own
        thresholds — and from nothing else, so the same verdict can be reached
        again over a record out of the series.

        ssh is only the helper that fetched the metrics, not their parent: the
        host node aggregates a peer ``ssh`` transport leaf and one leaf per
        metric (all siblings), and the container itself is nobody's (ADR-0015).
        """
        record = measurements[0].record
        failure = self._connection_failure(record)
        if failure is not None:
            return self._failed(plain(failure), record)
        mismatch = record.get("profile_error")
        if mismatch:
            # the remote guard rejected this profile (wrong OS family, or a busybox
            # userland under the linux profile) — a config error, surfaced as a
            # visible WARN rather than silent bad metrics.
            return self._failed(
                f"profile mismatch on {plain(self._target)}: "
                f"{plain(str(mismatch))}", record, code=StatusCode.WARN)
        if not self._has_readings(record):
            said = plain(str(record.get("output") or "")) or "empty output"
            return self._failed(
                f"connected, but no metrics from {plain(self._target)}: {said}",
                record)
        return CheckResult(StatusCode.UNDEFINED, children=(
            self._ssh_node(record), *self._children(record)))

    def expected_record(self) -> int | None:
        """One flat reading, declared where its size is knowable (ADR-0075).

        With `disk_path: all` it is not: the host decides how many filesystems it
        has, and a check that cannot know its estate correctly declares nothing
        rather than guessing — the measured size stands beside this on
        ``/system``, which is the honest mechanic for exactly that case.
        """
        if self.disk_path == ALL_VOLUMES:
            return None
        volumes = (len(self.disk_path.split("\n"))
                   if self.disk_path and "\n" in self.disk_path else 0)
        return (self._transport_record_bytes() + BASE_RECORD_BYTES
                + volumes * VOLUME_RECORD_BYTES)

    def _failed(self, reason: str, record: Mapping[str, Any], *,
                code: StatusCode = StatusCode.ERROR) -> CheckResult:
        """Collection failed: a host node whose only child is the ``ssh`` leaf,
        marked ``code`` — ERROR for a dead transport or no metrics, WARN for a
        config problem like a profile mismatch. No metric leaves this run."""
        reasons = [reason, *self._debug_lines(record)]
        return CheckResult(StatusCode.UNDEFINED, children=(
            CheckResult(code, reasons, name="ssh",
                        description=self._describe("ssh", SSH_NODE_DESCRIPTION),
                        config=self._ssh_config()),))

    def _ssh_node(self, record: Mapping[str, Any]) -> CheckResult:
        """The ``ssh`` transport leaf: OK, or WARN when ssh emitted an advisory
        (e.g. the post-quantum key-exchange notice)."""
        reasons = [self._summary(record)]
        notice = record.get("notice")
        if notice:
            reasons.append(plain(str(notice)))
        reasons += self._debug_lines(record)
        return CheckResult(StatusCode.WARN if notice else StatusCode.OK,
                           reasons, name="ssh",
                           description=self._describe("ssh", SSH_NODE_DESCRIPTION),
                           config=self._ssh_config())

    # --- reading the record into a branch ---

    def _children(self, record: Mapping[str, Any]) -> tuple[CheckResult, ...]:
        return (
            self._disk_aspect(record),
            self._percent_child(
                record, "memory", "mem_pct", "Memory in use",
                self._memory_reason),
            self._percent_child(
                record, "cpu", "cpu_pct", "CPU busy (100% − idle)",
                lambda values, pct: f"{pct:.0f}% busy"),
            self._load_child(record),
        )

    def _disk_aspect(self, record: Mapping[str, Any]) -> CheckResult:
        """The ``disk`` aspect: a single leaf for one filesystem, or — when the
        reading holds ``disk_count`` (``disk_path: all``) — a branch with one
        graded child per real filesystem, each named by its volume."""
        count = record.get("disk_count")
        if count is None:
            return self._percent_child(
                record, "disk", "disk_pct",
                "Disk space used on the monitored filesystem", self._disk_reason)
        used: set[str] = set()
        children = []
        for index in range(1, int(count) + 1):
            prefix = f"disk{index}_"
            sub = {key[len(prefix):]: value for key, value in record.items()
                   if key.startswith(prefix)}
            children.append(
                self._volume_child(volume_name(str(sub.get("path") or ""), used),
                                   sub))
        if not children:
            return unavailable("disk", "Disk space per filesystem")
        return CheckResult(StatusCode.UNDEFINED, name="disk",
                           description=self._describe(
                               "disk", "Disk space used, per filesystem"),
                           config=self._threshold_md("disk"),
                           children=tuple(children))

    def _volume_child(self, name: str, sub: Mapping[str, Any]) -> CheckResult:
        description = "Disk space used"
        pct = sub.get("pct")
        if pct is None:
            return unavailable(name, description, self._volume_about())
        warn, error = self.thresholds["disk"]
        free = human_kb(sub.get("avail_kb"))
        total = human_kb(sub.get("total_kb"))
        mount = str(sub.get("path") or "")
        detail = f" — {free} free of {total}" if free and total else ""
        suffix = f" on {plain(mount)}" if mount else ""
        return CheckResult(grade(float(pct), warn, error),
                           [f"{float(pct):.0f}% used{detail}{suffix}"],
                           name=name, description=description,
                           about=self._volume_about(),
                           config=self._threshold_md("disk"))

    def _percent_child(self, record: Mapping[str, Any], name: str, key: str,
                       description: str,
                       reason: Callable[[Mapping[str, Any], float], str]
                       ) -> CheckResult:
        value = record.get(key)
        if value is None:
            return unavailable(name, description)
        pct = float(value)
        warn, error = self.thresholds[name]
        return CheckResult(grade(pct, warn, error), [reason(record, pct)],
                           name=name, description=self._describe(name, description),
                           config=self._threshold_md(name))

    @staticmethod
    def _disk_reason(record: Mapping[str, Any], pct: float) -> str:
        free = human_kb(record.get("disk_avail_kb"))
        total = human_kb(record.get("disk_total_kb"))
        where = str(record.get("disk_path") or "")
        detail = f" — {free} free of {total}" if free and total else ""
        suffix = f" on {plain(where)}" if where else ""
        return f"{pct:.0f}% used{detail}{suffix}"

    @staticmethod
    def _memory_reason(record: Mapping[str, Any], pct: float) -> str:
        used = human_kb(record.get("mem_used_kb"))
        total = human_kb(record.get("mem_total_kb"))
        detail = f" — {used} of {total}" if used and total else ""
        return f"{pct:.0f}% used{detail}"

    def _load_child(self, record: Mapping[str, Any]) -> CheckResult:
        name = "load"
        description = self._describe("load", "Load average per CPU core")
        load1 = record.get("load1")
        if load1 is None:
            return unavailable(name, description)
        ncpu = max(1, int(record.get("ncpu") or 1))
        per_core = float(load1) / ncpu
        warn, error = self.thresholds["load"]
        reason = (f"{per_core:.2f} per core — load1 {float(load1):.2f} over "
                  f"{ncpu} CPUs")
        return CheckResult(grade(per_core, warn, error), [reason],
                           name=name, description=description,
                           config=self._threshold_md("load"))

    def _summary(self, record: Mapping[str, Any]) -> str:
        bits = []
        if record.get("os"):
            bits.append(plain(str(record["os"])))
        if record.get("ncpu") is not None:
            bits.append(f"{int(record['ncpu'])} CPUs")
        if record.get("uptime_seconds") is not None:
            bits.append("up " + human_duration(float(record["uptime_seconds"])))
        host = str(record.get("hostname") or "") or self.host
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
        where = f"thresholds.{aspect}"
        parsed[aspect] = (
            values.real(spec, "warn", default=default_warn, where=where),
            values.real(spec, "error", default=default_error, where=where))
    return parsed
