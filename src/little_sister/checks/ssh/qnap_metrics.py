"""QNAP hardware health check (``qnap-metrics``): temperatures + per-drive SMART.

Pipes the bundled ``qnap-health.sh`` (which calls QTS's ``getsysinfo``) to the host
and reports two branches **on the host node**, beside the host metrics:

- ``temperature`` — ``system``, ``cpu`` (where the model exposes them) and one
  ``drive<bay>`` child per populated bay, in °C, graded by ``max_temperature``.
- ``smart`` — one ``drive<bay>`` child per populated bay: ``GOOD`` → OK,
  ``Warning`` → WARN, anything else → ERROR.

Each branch ships what its card says to do and a handbook, a Markdown file in
``handbook/qnap-metrics/`` beside this module, that says it at length (ADR-0133); a
drive, a node a run names, takes neither and carries its bay among its details.

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

from little_sister.checks.base import (
    CheckResult,
    Measurement,
    config_markdown,
    plain,
    register,
)
from little_sister.checks.ssh.base import SshScriptCheck, parse_descriptions
from little_sister.checks.ssh.metrics import (
    code_span,
    parse_metrics,
    reading,
    readings,
    refuse_thresholds,
    unavailable,
)
from little_sister.status import StatusCode, join_path

DEFAULT_SCRIPT = "qnap-health.sh"

#: What each node reads, in a sentence (ADR-0133 decision 2). A branch's is the default
#: its entry in the ``descriptions:`` block replaces (ADR-0012); a drive's names its
#: bay.
TEMPERATURE_DESCRIPTION = ("The NAS's system, processor and drive temperatures in °C, "
                           "as QTS's `getsysinfo` reads them.")
SYSTEM_TEMPERATURE_DESCRIPTION = ("The NAS's system temperature in °C, as `getsysinfo` "
                                  "reads it.")
CPU_TEMPERATURE_DESCRIPTION = ("The NAS's processor temperature in °C, as `getsysinfo` "
                               "reads it.")
DRIVE_TEMPERATURE_DESCRIPTION = ("The temperature of the drive in bay {bay}, in °C, as "
                                 "`getsysinfo` reads it.")
SMART_DESCRIPTION = "Each drive's SMART verdict, as QTS's `getsysinfo` words it."
DRIVE_SMART_DESCRIPTION = ("The SMART verdict of the drive in bay {bay}, as "
                           "`getsysinfo` words it.")

SMART_OK = {"GOOD", "OK", "PASSED", "NORMAL"}
SMART_WARN = {"WARNING", "WARN"}

#: What this type grades (ADR-0131): how hot the system, its processor and each
#: drive may run, a maximum in °C, each level the last temperature that passes; and
#: a drive's SMART verdict, a judgment this type makes from the NAS's own word — OK
#: where it says so, a warning where it warns, an error for any other word, so that a
#: word nobody named is never quieter than a failing drive — to which a deployment
#: may give a sentence.
GRADINGS: dict[str, object] = {
    "max_temperature": {
        "sentence": "How hot the system, its processor and each drive may run, in "
                    "°C.",
        "kind": "pair", "field": "sys_temp_c", "unit": "number",
        "warn": 50, "error": 60},
    "smart": {
        "sentence": "A drive's SMART verdict, as the NAS words it.",
        "kind": "judgment", "field": "drives.*.smart"},
}

#: What this type's nodes are graded on, each on the node that grades it — the
#: curves it draws by default (ADR-0096 decision 6). A drive is keyed by its node's
#: name, so one declaration is a curve for each bay (decision 2); SMART is a word
#: and draws none.
MEASURES: dict[str, object] = {
    "sys_temp_c": {"unit": "°C", "label": "System temperature",
                   "node": "temperature/system"},
    "cpu_temp_c": {"unit": "°C", "label": "CPU temperature",
                   "node": "temperature/cpu"},
    "drives.*.temp_c": {"unit": "°C", "label": "Temperature of *",
                        "node": "temperature/*"},
}


#: What each branch's card says to do (ADR-0133 decision 2), leading into the section
#: of its handbook that says it at length (decision 4) — the branch's, since a drive is
#: a node a run names and takes nothing declared for its name (ADR-0118). Declared, as
#: a type's labels are (ADR-0025): a deployment's ``subnodes:`` block replaces one or
#: places it with ``{default}``.
ABOUT: dict[str, str] = {
    "temperature": (
        "{warn}: look at the fans and the air around the NAS. {error}: cool it now, or "
        "shut it down before its drives suffer. "
        "[What to do](handbook#when-it-runs-hot)"),
    "smart": (
        "{warn}: make sure the backup is current, and order a replacement drive. "
        "{error}: replace the drive now, after a backup where it holds the only copy. "
        "[What to do](handbook#when-a-drive-fails)"),
}

#: Each branch's handbook (ADR-0133 decision 3): a Markdown file this package ships,
#: named relative to this module's directory.
HANDBOOK: dict[str, str] = {
    name: f"handbook/qnap-metrics/{name}.md" for name in ABOUT}

#: How the NAS's levels first look on the wall (ADR-0128): its drives' SMART verdicts
#: and its temperature sensors as chips, a drive a bay and a few words each, a failure
#: opened by the card's budget, while the two branches stand open. A proposal, which
#: the deployment's file takes back in its ``subnodes:`` block, as it does the labels
#: beside it.
SUBNODE_DEFAULTS: dict[str, dict[str, object]] = {
    name: {"about": text, "handbook": HANDBOOK[name], "chips": True}
    for name, text in ABOUT.items()}


@register("qnap-metrics")
class QnapMetricsCheck(SshScriptCheck):
    """QNAP temperatures + per-drive SMART, reported beside the host metrics."""

    def __init__(self, *, descriptions: dict[str, str] | None = None,
                 **kwargs: Any) -> None:
        super().__init__(subnode_defaults=SUBNODE_DEFAULTS, measure_defaults=MEASURES,
                         gradings=GRADINGS, **kwargs)
        self.descriptions = descriptions or {}

    @classmethod
    def _extra_from_config(cls, config: dict[str, Any],
                           base_dir: Path) -> dict[str, Any]:
        refuse_thresholds(config.get("thresholds"),
                          {"temperature": ("max_temperature", "")})
        return {
            **cls._connection_from_config(config, base_dir, DEFAULT_SCRIPT),
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
        """Config Markdown for a temperature leaf — the °C levels it was graded by
        (ADR-0013)."""
        return config_markdown({
            "graded (°C)": self.grading_summary("max_temperature") or "not graded"})

    # --- the two halves (ADR-0086) -------------------------------------------

    #: What a drive's own entry in the record holds, under `drives`, keyed by
    #: its node's name (ADR-0096 decision 2): its `bay`, which is its identity; its
    #: `smart`, a word the NAS chose (`GOOD`, `Warning`) that stays a string; and
    #: `temp_c`, a number whose key names its unit.
    DRIVE_KEYS = ("bay", "temp_c", "smart")

    def measure(self) -> Measurement:
        """One SSH call, one `getsysinfo` script, one flat reading of this NAS —
        temperatures as numbers, SMART verdicts as the words the NAS uses, and a
        key it did not give standing as `None`."""
        result = self._run()
        record = self._transport_record(result)
        metrics = parse_metrics(result.stdout)
        record.update(readings(metrics, "sys_temp_c", "cpu_temp_c"))
        record["drives"] = _drive_readings(metrics)
        self._say_it_failed(record, result.stdout,
                            readable=self._has_readings(record),
                            nothing="connected, but no QNAP data")
        record.update({key: value for key, value in metrics.items()
                       if key.startswith("debug")})
        return Measurement(record=record)

    def _has_readings(self, record: Mapping[str, Any]) -> bool:
        """Did `getsysinfo` give us anything worth grading?"""
        return bool(record.get("drives")) or any(
            record.get(key) is not None for key in ("sys_temp_c", "cpu_temp_c"))

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
        return CheckResult(StatusCode.UNDEFINED, children=tuple(children),
                           details=self._host_details)

    @property
    def _host_details(self) -> dict[str, str]:
        """The details of the object the host node stands for (ADR-0133 decision 6):
        the NAS, as this check reaches it — withheld on the node it shares with
        ``host-metrics``, as every text one check's run writes there is."""
        return {"host": code_span(self.host)}

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
        ), details=self._host_details)

    # --- aspects ---

    def _temperature(self, record: Mapping[str, Any]) -> CheckResult:
        children: list[CheckResult] = []
        for key, name, desc in (
                ("sys_temp_c", "system", SYSTEM_TEMPERATURE_DESCRIPTION),
                ("cpu_temp_c", "cpu", CPU_TEMPERATURE_DESCRIPTION)):
            if record.get(key) is not None:
                children.append(self._temp_leaf(name, record[key], desc))
        for name, sub in _drives(record):
            if sub.get("temp_c") is not None:
                children.append(self._temp_leaf(
                    name, sub["temp_c"],
                    DRIVE_TEMPERATURE_DESCRIPTION.format(bay=_bay_of(name, sub)),
                    details=_bay(sub)))
        temp_desc = self._describe("temperature", TEMPERATURE_DESCRIPTION)
        if not children:
            return unavailable("temperature", temp_desc)
        return CheckResult(StatusCode.UNDEFINED, name="temperature",
                           description=temp_desc,
                           config=self._temp_threshold_md(),
                           children=tuple(children))

    def _temp_leaf(self, name: str, value: object, description: str, *,
                   details: Mapping[str, str] | None = None) -> CheckResult:
        if not isinstance(value, (int, float)):
            return unavailable(name, description, details=details)
        celsius = float(value)
        verdict = self.verdict("max_temperature", value=celsius)
        return CheckResult(verdict.code, [verdict.entry(f"{celsius:.0f} °C")],
                           name=name,
                           description=description,
                           config=self._temp_threshold_md(),
                           details=dict(details or {}))

    def _smart(self, record: Mapping[str, Any]) -> CheckResult:
        children: list[CheckResult] = []
        for name, sub in _drives(record):
            status = str(sub.get("smart") or "")
            if status and status != "--":
                children.append(self._smart_leaf(name, status, sub))
        smart_desc = self._describe("smart", SMART_DESCRIPTION)
        if not children:
            return unavailable("smart", smart_desc)
        return CheckResult(StatusCode.UNDEFINED, name="smart",
                           description=smart_desc, children=tuple(children))

    def _smart_leaf(self, name: str, status: str,
                    drive: Mapping[str, Any]) -> CheckResult:
        """A drive's SMART leaf: the judgment this type makes from the NAS's word,
        with the sentence a deployment wrote for it where it fired (ADR-0131), and
        its bay among its details (ADR-0133 decision 6)."""
        upper = status.upper()
        if upper in SMART_OK:
            code = StatusCode.OK
        elif upper in SMART_WARN:
            code = StatusCode.WARN
        else:
            code = StatusCode.ERROR
        verdict = self.verdict("smart", code=code)
        return CheckResult(verdict.code, [verdict.entry(plain(status))], name=name,
                           description=DRIVE_SMART_DESCRIPTION.format(
                               bay=_bay_of(name, drive)),
                           details=_bay(drive))


def _drive_readings(metrics: Mapping[str, str]) -> dict[str, dict[str, Any]]:
    """The script's drives, each keyed by the name of the node it becomes —
    ``drive<bay>`` — and holding its bay, its temperature and its SMART word
    (ADR-0096 decision 2). The script numbers them in the order it found them; the
    bay is the drive's identity, and the index would move a curve from one drive to
    the next the day a bay stands empty."""
    drives: dict[str, dict[str, Any]] = {}
    count = reading(metrics.get("drive_count")) or 0
    for index in range(1, int(count) + 1):
        prefix = f"drive{index}_"
        bay = metrics.get(f"{prefix}bay") or str(index)
        drives[f"drive{bay}"] = {"bay": bay,
                                 "temp_c": reading(metrics.get(f"{prefix}temp_c")),
                                 "smart": metrics.get(f"{prefix}smart") or None}
    return drives


def _bay(drive: Mapping[str, Any]) -> dict[str, str]:
    """A drive's details (ADR-0133 decision 6): the bay it stands in, its
    identity."""
    bay = drive.get("bay")
    return {"bay": plain(str(bay))} if bay else {}


def _bay_of(name: str, drive: Mapping[str, Any]) -> str:
    """The bay a drive's description names — its bay, or its node's name where the
    record kept none — written so that it reads as text."""
    return plain(str(drive.get("bay") or name))


def _drives(record: Mapping[str, Any]) -> list[tuple[str, Mapping[str, Any]]]:
    """``(node name, fields)`` for each drive the record holds."""
    drives = record.get("drives")
    if not isinstance(drives, Mapping):
        return []
    return [(str(name), sub) for name, sub in drives.items()
            if isinstance(sub, Mapping)]


