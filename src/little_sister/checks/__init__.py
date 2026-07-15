"""Checks: the built-in check types, their base class and the config loader.

Importing this package registers the built-in check types — ``http``, ``file``,
``command`` and the SSH family (``ssh-connect``, ``ssh-command``, ``ssh-script``,
``host-metrics``, ``qnap-metrics``, ``macos-memory``) — in ``CHECK_TYPES``.
"""
# Import the built-in checks for their registration side effects. The SSH family
# (incl. qnap-metrics / macos-memory) registers via the ``ssh`` package.
from little_sister.checks import command, file, http, ssh  # noqa: F401
from little_sister.checks.base import (
    CHECK_TYPES,
    Check,
    CheckError,
    CheckResult,
    code,
    parse_duration,
    plain,
)
from little_sister.checks.loader import DEFAULT_CHECKS_DIR, load_checks

__all__ = [
    "CHECK_TYPES",
    "DEFAULT_CHECKS_DIR",
    "Check",
    "CheckError",
    "CheckResult",
    "code",
    "load_checks",
    "parse_duration",
    "plain",
]
