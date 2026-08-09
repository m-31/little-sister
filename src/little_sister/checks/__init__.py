"""Checks: the built-in check types, their base class and the config loader.

Importing this package registers the built-in check types — ``http``, ``file``,
``command`` and the SSH family (``ssh-connect``, ``ssh-command``, ``ssh-script``,
``host-metrics``, ``qnap-metrics``, ``macos-memory``) — in ``CHECK_TYPES``.

This package **is** the import point a check type outside the library writes
against: ``__all__`` below is the check-authoring half of the version contract
(architecture.md §11, ADR-0049), and the modules it re-exports from are free to
move beneath it. The library's own built-ins import ``.base`` directly — they
are imported *by* this module, so the facade is not available to them yet.
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
from little_sister.checks.metadata import (
    expand_tokens,
    parse_subnodes,
    resolve_text,
)

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
    "expand_tokens",
    "load_checks",
    "parse_duration",
    "parse_secret_refs",
    "parse_subnodes",
    "plain",
    "register",
    "require_api",
    "resolve_text",
]
