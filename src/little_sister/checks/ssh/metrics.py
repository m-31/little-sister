"""Pure SSH-metrics toolkit: parsing, grading and formatting with no I/O.

The deliberate **public** API shared by the SSH-script checks (the system
``ssh`` metrics check and ``qnap``) — replacing the underscore back-door they used
to import from each other. ``parse_metrics`` turns a script's ``key=value`` blob
into a dict; ``grade`` maps a value + thresholds to a :class:`StatusCode`;
``human_kb`` / ``human_duration`` format sizes and uptimes; ``unavailable`` is the
"no data" leaf; ``volume_name`` makes a tree-safe filesystem node name; and the
``*_notices`` / ``oneline`` helpers tidy ssh's stderr. Pure, so it is unit-testable
without SSH: feed a captured busybox ``df`` blob and assert the parse.
"""
from __future__ import annotations

from little_sister.checks.base import CheckResult
from little_sister.status import StatusCode


def parse_metrics(output: str) -> dict[str, str]:
    """Parse a script's ``key=value`` stdout into a dict (last value wins)."""
    metrics: dict[str, str] = {}
    for line in output.splitlines():
        key, sep, value = line.partition("=")
        if sep:
            metrics[key.strip()] = value.strip()
    return metrics


def grade(value: float, warn: float, error: float) -> StatusCode:
    """Higher is worse: ERROR at/above ``error``, WARN at/above ``warn``."""
    if value >= error:
        return StatusCode.ERROR
    if value >= warn:
        return StatusCode.WARN
    return StatusCode.OK


def unavailable(name: str, description: str) -> CheckResult:
    """A WARN leaf for an aspect the script was expected to report but didn't."""
    return CheckResult(StatusCode.WARN, ["unavailable"], name=name,
                       description=description)


def volume_name(mount: str, used: set[str]) -> str:
    """A tree-safe node name for a filesystem: the mount's last path component
    (``/`` → ``root``), sanitised to ``[A-Za-z0-9_-]`` and de-duplicated so
    sibling volumes never collide."""
    base = mount.rstrip("/").rsplit("/", 1)[-1] or "root"
    base = "".join(c if (c.isalnum() or c in "-_") else "_" for c in base) or "root"
    name = base
    counter = 2
    while name in used:
        name = f"{base}_{counter}"
        counter += 1
    used.add(name)
    return name


def human_kb(value: str | None) -> str:
    """Render a kibibyte count as a human size, or ``""`` if not a number."""
    if value is None:
        return ""
    try:
        size = float(value)
    except ValueError:
        return ""
    for unit in ("KiB", "MiB", "GiB", "TiB"):
        if size < 1024 or unit == "TiB":
            return f"{size:.1f} {unit}"
        size /= 1024
    return f"{size:.1f} TiB"


def human_duration(seconds: float) -> str:
    """Render a second count as a coarse ``Nd Nh`` / ``Nh Nm`` / ``Nm`` uptime."""
    total = int(seconds)
    days, hours, minutes = total // 86400, (total % 86400) // 3600, (total % 3600) // 60
    if days:
        return f"{days}d {hours}h"
    if hours:
        return f"{hours}h {minutes}m"
    return f"{minutes}m"


def strip_ssh_notices(text: str) -> str:
    """Drop ssh advisory banner lines (``** … **``) — e.g. the post-quantum
    key-exchange warning — so they don't crowd out the real error in a reason."""
    return "\n".join(line for line in text.splitlines()
                     if not line.lstrip().startswith("**"))


def ssh_notices(text: str) -> str:
    """The text of any ssh advisory banner lines (``** … **``), stripped of their
    decoration and joined — e.g. the post-quantum key-exchange warning. ``""`` if
    there are none."""
    notices = [line.strip().strip("*").strip()
               for line in text.splitlines() if line.lstrip().startswith("**")]
    return " ".join(notice for notice in notices if notice)


def oneline(text: str, limit: int = 300) -> str:
    """Collapse whitespace to single spaces and truncate to ``limit`` chars."""
    return " ".join(text.split())[:limit]
