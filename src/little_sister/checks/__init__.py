"""Checks: the built-in check types, their base class and the config loader.

Importing this package registers the built-in check types — ``http``, ``file``,
``command`` and the SSH family (``ssh-connect``, ``ssh-command``, ``ssh-script``,
``host-metrics``, ``qnap-metrics``, ``macos-memory``) — in ``CHECK_TYPES``.

This package **is** the import point a check type outside the library writes
against: ``__all__`` below is the check-authoring half of the version contract
(architecture.md §11, ADR-0049), and the modules it re-exports from are free to
move beneath it. The library's own built-ins import ``.base`` directly — they
are imported *by* this module, so the facade is not available to them yet.

Nothing from ``checks.metadata`` is re-exported here any more. Its three helpers
were the reader and the layering a branch check ran over its own ``subnodes:``
block; the library reads that block itself now and a type only **declares** its
defaults and tokens (ADR-0025), so the names left the surface
with the callers that needed them — the check API epoch moving with them
(ADR-0051).
"""
# Import the built-in checks for their registration side effects. The SSH family
# (incl. qnap-metrics / macos-memory) registers via the ``ssh`` package.
from little_sister.checks import command, file, http, ssh  # noqa: F401
from little_sister.checks.base import (
    API_VERSION,
    CHECK_TYPES,
    Check,
    CheckError,
    CheckResult,
    code,
    coerce_code,
    config_markdown,
    parse_duration,
    parse_secret_refs,
    plain,
    register,
    require_api,
)
from little_sister.checks.loader import CHECKS_ASPECT, checks_dirs, load_checks

# The check-facing entry value object (ADR-0042), re-exported so a check type
# imports its whole vocabulary from one place.
from little_sister.reasons import Entry

__all__ = [
    "API_VERSION",
    "CHECKS_ASPECT",
    "CHECK_TYPES",
    "Check",
    "CheckError",
    "CheckResult",
    "Entry",
    "checks_dirs",
    "code",
    "coerce_code",
    "config_markdown",
    "load_checks",
    "parse_duration",
    "parse_secret_refs",
    "plain",
    "register",
    "require_api",
]
