"""Host-metrics check (``host-metrics``): disk / memory / CPU / load over SSH.

One SSH connection per run pipes a bundled metrics script to the host's shell and
parses its ``key=value`` output. The host's ``profile`` (``linux`` / ``macos`` /
``busybox``) selects both the script and the interpreter it's piped to — ``bash``
for linux/macos, ``sh`` for busybox (ADR-0009). The script only *measures* (it
emits raw numbers); this check applies the OK/WARN/ERROR thresholds and reports one
**branch**: a peer ``ssh`` transport leaf plus a node per aspect (``disk``,
``memory``, ``cpu``, ``load``), all siblings, each carrying its number even when OK
(project.md §2.7). The host node itself is OK once the host is reachable; the worst
aspect rolls up to it (ADR-0039). Each aspect ships what its card says to do and a
handbook, a Markdown file in ``handbook/host-metrics/`` beside this module, that says
it at length (ADR-0133).

The basic metrics need no elevated rights; ``sudo: true`` runs the script under
``sudo -n`` for deployments that extend it with root-only insights.
"""
from __future__ import annotations

import json
from collections.abc import Callable, Mapping, Sequence
from datetime import datetime
from pathlib import Path
from typing import Any

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
    code_span,
    human_duration,
    human_kb,
    parse_metrics,
    reading,
    readings,
    refuse_thresholds,
    unavailable,
    volume_name,
)
from little_sister.reasons import clip
from little_sister.status import StatusCode, join_path

#: What each node reads, in a sentence (ADR-0133 decision 2): the default of the
#: ``descriptions:`` block, leaf by leaf (ADR-0012), and a volume's, whose node a run
#: names.
SSH_DESCRIPTION = ("Whether the host answers this check's SSH connection and runs its "
                   "metrics script.")
DISK_DESCRIPTION = ("The share of a filesystem's space in use, as the host's own `df` "
                    "reports it.")
VOLUMES_DESCRIPTION = ("The share of each filesystem's space in use, as the host's own "
                       "`df` reports it.")
VOLUME_DESCRIPTION = ("The share of this filesystem's space in use, as the host's own "
                      "`df` reports it.")
MEMORY_DESCRIPTION = ("The share of the host's memory in use, from `/proc/meminfo`, or "
                      "`vm_stat` on a Mac.")
CPU_DESCRIPTION = ("How busy the processor was over about a second: 100% less its idle "
                   "time.")
LOAD_DESCRIPTION = ("The one-minute load average, divided by the number of the host's "
                    "cores.")

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
#: (ADR-0075): eight numbers and two short strings under their own key names, with
#: room — and, per filesystem of a `disk_path` list, three numbers under their keys
#: beside the volume's name and its mount point, which the configuration gives and
#: `expected_record` counts. Both are ceilings: every string in this record is
#: either clipped or one the configuration names.
BASE_RECORD_BYTES = 416
VOLUME_RECORD_BYTES = 96

#: What this type's nodes are graded on, each on the node that grades it — the
#: curves it draws by default (ADR-0096 decision 6). A volume is keyed by its
#: node's name, so one declaration is a curve for each (decision 2).
# Each percent here is of a whole — memory of what is installed, CPU as 100 % less
# idle over all cores, space of a filesystem — so its axis reaches 100 and two hosts'
# curves compare (ADR-0117). Load per core has no such end: it passes 1.
MEASURES: dict[str, dict[str, object]] = {
    "mem_pct": {"unit": "%", "label": "Memory in use", "node": "memory",
                "axis_to": 100},
    "cpu_pct": {"unit": "%", "label": "CPU busy", "node": "cpu", "axis_to": 100},
    "load1_per_core": {"unit": "per core", "label": "Load per core", "node": "load"},
    "disk_pct": {"unit": "%", "label": "Disk space used", "node": "disk",
                 "axis_to": 100},
    "volumes.*.pct": {"unit": "%", "label": "Disk space used on *",
                      "node": "disk/*", "axis_to": 100},
}

#: What this type grades (ADR-0131), each a maximum among the check's own keys: how
#: full a filesystem may be — each volume's alike, where `disk_path` names several —
#: how much of the memory may be in use, how busy the processor, and the one-minute
#: load per core. Each level is the last value that passes; the defaults are the
#: levels this type has always shipped, and a deployment re-sets any of them, or
#: switches one off with `max_cpu: null`, in the check's own YAML.
GRADINGS: dict[str, object] = {
    "max_disk": {
        "sentence": "How full a filesystem may be, each volume's alike where "
                    "several are read.",
        "kind": "pair", "field": "disk_pct", "unit": "share",
        "warn": "80%", "error": "90%"},
    "max_memory": {
        "sentence": "How much of the host's memory may be in use.",
        "kind": "pair", "field": "mem_pct", "unit": "share",
        "warn": "85%", "error": "95%"},
    "max_cpu": {
        "sentence": "How busy the processor may be: 100% less its idle time.",
        "kind": "pair", "field": "cpu_pct", "unit": "share",
        "warn": "85%", "error": "95%"},
    "max_load": {
        "sentence": "The one-minute load average per CPU core.",
        "kind": "pair", "field": "load1_per_core", "unit": "number",
        "warn": 0.8, "error": 1.0},
}

#: What replaced each aspect of the retired `thresholds:` block, and the unit its
#: level is written with.
RETIRED_THRESHOLDS = {"disk": ("max_disk", "%"), "memory": ("max_memory", "%"),
                      "cpu": ("max_cpu", "%"), "load": ("max_load", "")}

# The leaf nodes this check owns beneath the host node: the peer ``ssh`` transport
# leaf plus one per metric. ``disk`` may itself fan out per-filesystem, but owning
# the ``disk`` subtree covers that. The host node itself is a shared container this
# check does not own — a peer (e.g. ``qnap-metrics``) adds its own leaves (ADR-0015).
METRIC_NODES = ("ssh", "disk", "memory", "cpu", "load")

#: What each aspect's card says to do (ADR-0133 decision 2): the first steps that hold
#: on every host, each leading into the section of the aspect's handbook that says them
#: at length (decision 4). How to read a value is the description's and the handbook's,
#: never the about's, and the levels ride each leaf's configuration (ADR-0013).
#: Declared, as a type's labels are (ADR-0025): the library resolves them against the
#: deployment's ``subnodes:`` block, which replaces one or places it with
#: ``{default}``, and ``nodes.yaml`` still wins above both — so this check reads none
#: of it itself. A volume a run names takes none of it (ADR-0118): what holds for every
#: volume of a host reaches it as the details given down to it.
ABOUT: dict[str, str] = {
    "ssh": (
        "{error}: try `ssh -o BatchMode=yes` to the host from the monitor's machine, "
        "as the user it runs as, and fix what stops it there — "
        "[what to try](handbook#when-it-fails). {warn}: update the host's SSH, or set "
        "the check's `profile` to the host's kind, as its line says — "
        "[what to do](handbook#when-it-warns)."),
    "disk": (
        "{warn}: find what grows and clean it up, or plan more space. {error}: free "
        "space now, before writes start to fail. [What to do](handbook#when-it-fills)"),
    "memory": (
        "{warn} and {error}: find what holds the memory and restart it, or give the "
        "host more. [What to do](handbook#when-it-fills)"),
    "cpu": (
        "A {warn} or {error} that stays: find the process that keeps the processor "
        "busy. [What to do](handbook#when-it-stays-high)"),
    "load": (
        "{warn} and {error}: find what the work waits for — the processor, as the CPU "
        "beside it says, or a disk. [What to do](handbook#when-it-climbs)"),
}

#: Each aspect's handbook (ADR-0133 decision 3): a Markdown file this package ships,
#: named relative to this module's directory, its sections the ones the abouts above
#: lead into.
HANDBOOK: dict[str, str] = {
    name: f"handbook/host-metrics/{name}.md" for name in ABOUT}

#: How a host's levels first look on the wall (ADR-0128): a host's leaves as chips —
#: five short readings on every host of a wall, each in sight with its state, a failure
#: opened by the card's budget — and, where ``disk`` fans out, its filesystems too. A
#: proposal: the deployment's file takes it back, ``chips: false`` at its top level for
#: the leaves and in ``subnodes: {disk: …}`` for a disk's filesystems. On a host node
#: another check shares it speaks for its own leaves alone, and the node's own look is
#: ``nodes.yaml``'s (decision 5).
NODE_DEFAULTS: dict[str, object] = {"chips": True}
SUBNODE_LOOKS: dict[str, dict[str, object]] = {"disk": {"chips": True}}

#: The same maps in the shape the library takes — ``name -> {title, about, handbook}``,
#: a name's look beside its labels. This family ships no ``title`` default (the aspect
#: names read fine on their own).
SUBNODE_DEFAULTS: dict[str, dict[str, object]] = {
    name: {"about": text, "handbook": HANDBOOK[name], **SUBNODE_LOOKS.get(name, {})}
    for name, text in ABOUT.items()}


@register("host-metrics")
class HostMetricsCheck(SshScriptCheck):
    """Collect disk/memory/cpu/load from a host over SSH and report the host node
    with a peer ``ssh`` leaf plus a leaf per metric (all siblings)."""

    def __init__(self, *, descriptions: dict[str, str] | None = None,
                 disk_path: str | None = None, profile: str = DEFAULT_PROFILE,
                 **kwargs: Any) -> None:
        # The per-aspect labels this type ships (ADR-0025). Declared, not applied:
        # the library resolves them against the deployment's `subnodes:` block and
        # the engine writes the result per child name, so nothing below reads a
        # config key or layers a default. What it grades is declared the same way,
        # and the library reads the deployment's levels (ADR-0131), and so is how
        # its levels first look (ADR-0128).
        super().__init__(subnode_defaults=SUBNODE_DEFAULTS, node_defaults=NODE_DEFAULTS,
                         measure_defaults=MEASURES, gradings=GRADINGS, **kwargs)
        self.descriptions = descriptions or {}
        self.disk_path = disk_path
        self.profile = profile

    @classmethod
    def _extra_from_config(cls, config: dict[str, Any],
                           base_dir: Path) -> dict[str, Any]:
        profile = _parse_profile(config.get("profile"))
        default_script, interpreter = PROFILES[profile]
        refuse_thresholds(config.get("thresholds"), RETIRED_THRESHOLDS)
        return {
            **cls._connection_from_config(config, base_dir, default_script),
            "interpreter": interpreter,
            "profile": profile,
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
        """Config Markdown for a metric leaf — the levels it was graded by
        (ADR-0013). ``load`` is a per-core average; the rest are percentages."""
        return config_markdown({
            "graded": self.grading_summary(f"max_{aspect}") or "not graded"})

    def _describe(self, leaf: str, default: str) -> str:
        """A leaf's description: the ``descriptions:`` override or the built-in
        default (ADR-0012)."""
        return self.descriptions.get(leaf, default)

    @property
    def _host_details(self) -> dict[str, str]:
        """The details of the object the host node stands for (ADR-0133 decision 6):
        the host, as this check reaches it. Withheld where another check shares the
        node, as every text one check's run writes there is."""
        return {"host": code_span(self.host)}

    @staticmethod
    def _mount(path: object) -> dict[str, str]:
        """A filesystem's details: its mount point, where the reading names one."""
        return {"mount": code_span(str(path))} if path else {}

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

    @property
    def _counts_volumes(self) -> bool:
        """Whether this check reads several filesystems, so its record keys them by
        name even on a run that read none (one shape per check)."""
        return self.disk_path == ALL_VOLUMES or "\n" in (self.disk_path or "")

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
        record["load1_per_core"] = _per_core(record)
        record["os"] = metrics.get("os") or None
        record["hostname"] = metrics.get("hostname") or None
        if "disk_count" in metrics or self._counts_volumes:
            record["volumes"] = self._volume_readings(metrics)
        else:
            record.update(readings(metrics, *self.DISK_KEYS))
            record["disk_path"] = metrics.get("disk_path") or None
        # The remote guard's verdict, where it refused: a *configuration* fact
        # the grading turns into a visible WARN rather than silent bad metrics.
        if metrics.get("profile_error"):
            record["profile_error"] = clip(metrics["profile_error"],
                                           chars=TRANSPORT_TEXT_CHARS,
                                           budget=TRANSPORT_TEXT_BYTES)
        # Where nothing parsed, the reading failed and says so — with what the
        # host said instead, which is the one sentence that needs the script's
        # output. On every other run that output is working state and stays
        # inside the check.
        self._say_it_failed(record, result.stdout,
                            readable=self._has_readings(record),
                            nothing="connected, but no metrics")
        # Anything the script labelled `debug*` rides through untouched, so the
        # `debug` lines can be rebuilt from the reading like every other line.
        record.update({key: value for key, value in metrics.items()
                       if key.startswith("debug")})
        return Measurement(record=record)

    def _volume_readings(self, metrics: dict[str, str]) -> dict[str, Any]:
        """The filesystems of a `disk_path: all` (or list) run, each keyed by the
        name of the node it becomes and holding its mount point and its numbers
        (ADR-0096 decision 2): the index the script numbered them by is where a
        volume stood in one run's output, and a curve that followed it would swap
        volumes when the order moved."""
        volumes: dict[str, Any] = {}
        used: set[str] = set()
        count = reading(metrics.get("disk_count")) or 0
        for index in range(1, int(count) + 1):
            prefix = f"disk{index}_"
            path = metrics.get(f"{prefix}path") or None
            volumes[volume_name(str(path or ""), used)] = {
                "path": path, **{key: reading(metrics.get(f"{prefix}{key}"))
                                 for key in self.VOLUME_KEYS}}
        return volumes

    def _has_readings(self, record: Mapping[str, Any]) -> bool:
        """Did the script give us a single number worth grading?"""
        if record.get("volumes"):
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
            self._ssh_node(record), *self._children(record)),
            details=self._host_details)

    def expected_record(self) -> int | None:
        """One flat reading, declared where its size is knowable (ADR-0075).

        With `disk_path: all` it is not: the host decides how many filesystems it
        has, and a check that cannot know its estate correctly declares nothing
        rather than guessing — the measured size stands beside this on
        ``/system``, which is the honest mechanic for exactly that case.
        """
        if self.disk_path == ALL_VOLUMES:
            return None
        paths = (self.disk_path or "").split("\n") if self._counts_volumes else []
        used: set[str] = set()
        volumes = sum(VOLUME_RECORD_BYTES + len(json.dumps(path))
                      + len(json.dumps(volume_name(path, used))) for path in paths)
        return self._transport_record_bytes() + BASE_RECORD_BYTES + volumes

    def _failed(self, reason: str, record: Mapping[str, Any], *,
                code: StatusCode = StatusCode.ERROR) -> CheckResult:
        """Collection failed: a host node whose only child is the ``ssh`` leaf,
        marked ``code`` — ERROR for a dead transport or no metrics, WARN for a
        config problem like a profile mismatch. No metric leaves this run."""
        reasons = [reason, *self._debug_lines(record)]
        return CheckResult(StatusCode.UNDEFINED, children=(
            CheckResult(code, reasons, name="ssh",
                        description=self._describe("ssh", SSH_DESCRIPTION),
                        config=self._ssh_config()),), details=self._host_details)

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
                           description=self._describe("ssh", SSH_DESCRIPTION),
                           config=self._ssh_config())

    # --- reading the record into a branch ---

    def _children(self, record: Mapping[str, Any]) -> tuple[CheckResult, ...]:
        return (
            self._disk_aspect(record),
            self._percent_child(
                record, "memory", "mem_pct", MEMORY_DESCRIPTION,
                self._memory_reason),
            self._percent_child(
                record, "cpu", "cpu_pct", CPU_DESCRIPTION,
                lambda values, pct: f"{pct:.0f}% busy"),
            self._load_child(record),
        )

    def _disk_aspect(self, record: Mapping[str, Any]) -> CheckResult:
        """The ``disk`` aspect: a single leaf for one filesystem, or — when the
        reading holds ``disk_count`` (``disk_path: all``) — a branch with one
        graded child per real filesystem, each named by its volume."""
        volumes = record.get("volumes")
        if not isinstance(volumes, Mapping):
            return self._percent_child(
                record, "disk", "disk_pct", DISK_DESCRIPTION, self._disk_reason,
                details=self._mount(record.get("disk_path")))
        children = [self._volume_child(str(name), sub)
                    for name, sub in volumes.items() if isinstance(sub, Mapping)]
        description = self._describe("disk", VOLUMES_DESCRIPTION)
        if not children:
            return unavailable("disk", description)
        return CheckResult(StatusCode.UNDEFINED, name="disk",
                           description=description,
                           config=self._threshold_md("disk"),
                           children=tuple(children))

    def _volume_child(self, name: str, sub: Mapping[str, Any]) -> CheckResult:
        """A filesystem of a `disk_path: all` (or list) run, named by the host — a
        node a run names (ADR-0118), so nothing declared for its name reaches it,
        and it carries the details of its object, its mount point, and no label of
        its own: what holds for every volume of a host reaches it as the details
        given down to it (ADR-0133 decision 6)."""
        description = VOLUME_DESCRIPTION
        mount = str(sub.get("path") or "")
        pct = sub.get("pct")
        if pct is None:
            return unavailable(name, description, dynamic=True,
                               details=self._mount(mount))
        verdict = self.verdict("max_disk", value=float(pct))
        free = human_kb(sub.get("avail_kb"))
        total = human_kb(sub.get("total_kb"))
        detail = f" — {free} free of {total}" if free and total else ""
        suffix = f" on {plain(mount)}" if mount else ""
        return CheckResult(verdict.code,
                           [verdict.entry(f"{float(pct):.0f}% used{detail}{suffix}")],
                           name=name, description=description,
                           config=self._threshold_md("disk"), dynamic=True,
                           details=self._mount(mount))

    def _percent_child(self, record: Mapping[str, Any], name: str, key: str,
                       description: str,
                       reason: Callable[[Mapping[str, Any], float], str], *,
                       details: Mapping[str, str] | None = None) -> CheckResult:
        description = self._describe(name, description)
        value = record.get(key)
        if value is None:
            return unavailable(name, description, details=details)
        pct = float(value)
        verdict = self.verdict(f"max_{name}", value=pct)
        return CheckResult(verdict.code, [verdict.entry(reason(record, pct))],
                           name=name, description=description,
                           config=self._threshold_md(name),
                           details=dict(details or {}))

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
        description = self._describe("load", LOAD_DESCRIPTION)
        per_core = record.get("load1_per_core")
        if not isinstance(per_core, (int, float)):
            return unavailable(name, description)
        per_core = float(per_core)
        load1 = float(record.get("load1") or 0)
        ncpu = max(1, int(record.get("ncpu") or 1))
        verdict = self.verdict("max_load", value=per_core)
        reason = f"{per_core:.2f} per core — load1 {load1:.2f} over {ncpu} CPUs"
        return CheckResult(verdict.code, [verdict.entry(reason)],
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


def _per_core(record: Mapping[str, Any]) -> float | None:
    """The one-minute load over the CPUs the host had at this reading — at least
    one — as the load node grades it (ADR-0096 decision 5): written into the record
    so that the curve, the sentence and the thresholds read one number. Three
    places, which is as fine as `load1`'s two over the cores a host has."""
    load1 = record.get("load1")
    if not isinstance(load1, (int, float)):
        return None
    return round(float(load1) / max(1, int(record.get("ncpu") or 1)), 3)


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

