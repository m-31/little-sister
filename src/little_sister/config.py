"""General application configuration, loaded once from the ``settings`` aspect.

Defaults apply when the file or a key is missing. Settings are the ``settings``
aspect of the configuration directory — ``config/settings.yaml`` in each root of the
path-list, **shallow-merged per key** with the later root winning (ADR-0031); the
file is a flat mapping of scalars, so that is well defined.
``LITTLE_SISTER_CONFIG`` names a single file instead and **bypasses layering
entirely**, which is what an override should mean. Add new options by giving them a
field and a default here and reading them in :func:`load_config`.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import yaml

from little_sister import values
from little_sister.config_dir import aspect_files
from little_sister.logger import logger

DEFAULT_TIMEZONE = "Europe/Berlin"
DEFAULT_TIME_FORMAT = "%Y-%m-%d %H:%M:%S"
DEFAULT_MAINTENANCE_EXPIRY = "7d"
DEFAULT_REASON_CAP = 6
DEFAULT_BRANCH_CAP = 3
DEFAULT_MAINTENANCE_CAP = 5
DEFAULT_RETRY_ATTEMPTS = 2
DEFAULT_CARD_STATUS_LINE = "beside"
CARD_STATUS_LINES = ("beside", "below")
DEFAULT_DASHBOARD_COLUMNS = "flow"
DASHBOARD_COLUMNS = ("flow", "plain")
SETTINGS_ASPECT = "settings"
# An explicit single-file override, read at import so a wrapper can set it before
# importing the app. Empty (the normal case) means "use the aspect and its layering".
CONFIG_PATH_OVERRIDE = os.environ.get("LITTLE_SISTER_CONFIG", "")


@dataclass(frozen=True)
class Config:
    """General display/runtime options."""
    timezone: str = DEFAULT_TIMEZONE
    time_format: str = DEFAULT_TIME_FORMAT
    # Default maintenance window if an admin gives no explicit duration (ADR-0014);
    # a duration string parsed where used (kept off this module to stay dependency
    # free). No indefinite — there is always an expiry.
    maintenance_default_expiry: str = DEFAULT_MAINTENANCE_EXPIRY
    # Reason *lines* a dashboard card shows before its header chevron reveals the
    # rest (the reason-overflow budget, ADR-0024): the collapsed reason block is
    # clamped to this many lines, so short reasons show that many reasons while a
    # wrapped reason uses more of the budget.
    # A non-negative int (0 shows none up front); the _status_grid.html reason macro
    # passes it through as the block's --reason-lines. Not reasons.js's CLIP_SLOP.
    reason_cap: int = DEFAULT_REASON_CAP
    # Quiet (non-warn/error) child *boxes* a branch shows in dense mode before a
    # "+N more" control reveals the rest (extends ADR-0024): the count-cap sibling
    # of reason_cap. A non-negative int (0 collapses every quiet box behind
    # the control); warn/error boxes are never capped, so nothing urgent hides.
    # Ignored when the density ("chips") switch is off — everything is spelled out.
    branch_cap: int = DEFAULT_BRANCH_CAP
    # Maintenance pins the strip pill's popover shows before a "+N more" links to the
    # full /maintenance page (extends ADR-0024): the count-cap sibling of reason_cap /
    # branch_cap, plumbed to the full page and the ?fragment swap. A non-negative int
    # (0 sends every pin straight to the /maintenance page).
    maintenance_cap: int = DEFAULT_MAINTENANCE_CAP
    # Show a failing check's **stack trace** on its node, not just the exception
    # message (ADR-0040). On by default: this is an operator dashboard, and
    # a deployment where the log is awkward to reach — a container, someone else's
    # cloud — should not have to go looking for the one thing that explains the
    # failure. Set false where the dashboard has a wider audience than its logs.
    stacktrace: bool = True
    # The budgeted failure retry (ADR-0033): while a check's last result is not
    # OK, run it again after this interval instead of waiting out its frequency
    # — at most `retry_attempts` times per failure episode, then back to the
    # nominal frequency until it recovers. A duration string or bare seconds,
    # kept as text and parsed where used (the maintenance_default_expiry
    # pattern); empty or 0 = off, which is the default — nothing changes until
    # a deployment opts in. A check config can override either field.
    retry_interval: str = ""
    # Fast attempts per failure episode (the budget); a non-negative int, 0
    # disables the retry even where an interval is set. The later damping work
    # ties its escalation count here.
    retry_attempts: int = DEFAULT_RETRY_ATTEMPTS
    # Where a dashboard card's status cluster (time, cue, status word) sits
    # relative to its title row: ``beside`` (the default) keeps the compact
    # one-line head, dropping the cluster to its own line only when it cannot
    # fit; ``below`` gives every card a standing second line — a calmer, more
    # uniform grid that spends vertical space for it. Display only, a sibling
    # of reason_cap's budget family; a per-viewer override is a later step.
    card_status_line: str = DEFAULT_CARD_STATUS_LINE
    # How dashboard cards spend a wide grid's columns (ADR-0056): ``flow``
    # (the default) lets a large root take useful spare tracks from the
    # stable width-priced plan; ``plain`` skips the plan entirely, so every
    # card keeps one ordinary auto-fill track — the same grid a browser
    # without JavaScript shows. One enum, display only; a per-viewer value
    # and a possible ``packed`` mode are later steps of the same control,
    # never a second switch.
    dashboard_columns: str = DEFAULT_DASHBOARD_COLUMNS

    @property
    def tzinfo(self) -> ZoneInfo:
        """The configured timezone (validated at load time)."""
        return ZoneInfo(self.timezone)


def _valid_timezone(name: str) -> str:
    try:
        ZoneInfo(name)
    except (ZoneInfoNotFoundError, ValueError):
        logger.warning("config: unknown timezone %r; using %s", name,
                       DEFAULT_TIMEZONE)
        return DEFAULT_TIMEZONE
    return name


def _valid_reason_cap(value: object) -> int:
    """Coerce the reason-overflow cap to a non-negative int; a bad or negative
    value falls back to the default (``0`` shows none before *show all*)."""
    try:
        cap = int(str(value).strip())
    except ValueError:
        logger.warning("config: reason_cap %r is not an integer; using %d",
                       value, DEFAULT_REASON_CAP)
        return DEFAULT_REASON_CAP
    if cap < 0:
        logger.warning("config: reason_cap %d is negative; using 0", cap)
        return 0
    return cap


def _valid_branch_cap(value: object) -> int:
    """Coerce the branch box-cap to a non-negative int; a bad or negative value
    falls back to the default (``0`` collapses every quiet box behind *+N more*)."""
    try:
        cap = int(str(value).strip())
    except ValueError:
        logger.warning("config: branch_cap %r is not an integer; using %d",
                       value, DEFAULT_BRANCH_CAP)
        return DEFAULT_BRANCH_CAP
    if cap < 0:
        logger.warning("config: branch_cap %d is negative; using 0", cap)
        return 0
    return cap


def _valid_maintenance_cap(value: object) -> int:
    """Coerce the maintenance popover cap to a non-negative int; a bad or negative
    value falls back to the default (``0`` sends every pin to the /maintenance page)."""
    try:
        cap = int(str(value).strip())
    except ValueError:
        logger.warning("config: maintenance_cap %r is not an integer; using %d",
                       value, DEFAULT_MAINTENANCE_CAP)
        return DEFAULT_MAINTENANCE_CAP
    if cap < 0:
        logger.warning("config: maintenance_cap %d is negative; using 0", cap)
        return 0
    return cap


def _valid_card_status_line(value: object) -> str:
    """Coerce the card status-line placement to a known value; anything else
    falls back to the compact default with a warning naming the choices."""
    choice = str(value).strip().lower()
    if choice not in CARD_STATUS_LINES:
        logger.warning("config: card_status_line %r is not one of %s; using %r",
                       value, "/".join(CARD_STATUS_LINES),
                       DEFAULT_CARD_STATUS_LINE)
        return DEFAULT_CARD_STATUS_LINE
    return choice


def _valid_dashboard_columns(value: object) -> str:
    """Coerce the dashboard column mode to a known value; anything else falls
    back to the flowing default with a warning naming the choices."""
    choice = str(value).strip().lower()
    if choice not in DASHBOARD_COLUMNS:
        logger.warning("config: dashboard_columns %r is not one of %s; using %r",
                       value, "/".join(DASHBOARD_COLUMNS),
                       DEFAULT_DASHBOARD_COLUMNS)
        return DEFAULT_DASHBOARD_COLUMNS
    return choice


def _valid_retry_attempts(value: object) -> int:
    """Coerce the failure-retry budget (ADR-0033) to a non-negative int; a bad
    or negative value falls back safely (``0`` disables the fast retry)."""
    try:
        attempts = int(str(value).strip())
    except ValueError:
        logger.warning("config: retry_attempts %r is not an integer; using %d",
                       value, DEFAULT_RETRY_ATTEMPTS)
        return DEFAULT_RETRY_ATTEMPTS
    if attempts < 0:
        logger.warning("config: retry_attempts %d is negative; using 0",
                       attempts)
        return 0
    return attempts


def settings_files(config_dir: str | Path | None = None) -> list[Path]:
    """The settings layers, in path-list order.

    ``LITTLE_SISTER_CONFIG`` (or an explicit ``path``) short-circuits to that one
    file and never consults the configuration directory — the override bypasses
    layering. Otherwise the ``settings`` aspect of every root, lowest first.
    """
    if CONFIG_PATH_OVERRIDE:
        return [Path(CONFIG_PATH_OVERRIDE)]
    return aspect_files(SETTINGS_ASPECT, config_dir)


def _read_settings(source: Path) -> dict[str, Any]:
    """One settings file as a mapping. Every problem — absent, unparsable, not a
    mapping — logs and yields ``{}``, so a bad layer costs its own keys and not the
    whole configuration."""
    try:
        with open(source, encoding="utf-8") as handle:
            data = yaml.safe_load(handle) or {}
    except FileNotFoundError:
        logger.info("config: no file at %s; using defaults (reason_cap=%d)",
                    source.resolve(), DEFAULT_REASON_CAP)
        return {}
    except yaml.YAMLError as error:
        logger.warning("config: invalid YAML in %s: %s; using defaults",
                       source, error)
        return {}
    if not isinstance(data, dict):
        logger.warning("config: %s must be a mapping; using defaults", source)
        return {}
    return data


def load_config(path: str | Path | None = None, *,
                config_dir: str | Path | None = None) -> Config:
    """Load the settings; on any problem, fall back to defaults.

    ``path`` names a single file and bypasses layering (as
    ``LITTLE_SISTER_CONFIG`` does). Otherwise the ``settings`` aspect of every
    configuration root in ``config_dir`` (default ``LITTLE_SISTER_CONFIG_DIR``) is
    shallow-merged **per key**, later root winning. Logs (INFO) the resolved
    absolute path of every layer and the values they yield, so a deployment can see
    exactly which file and which cap took effect.
    """
    sources = [Path(path)] if path is not None else settings_files(config_dir)
    data: dict[str, Any] = {}
    for source in sources:
        data.update(_read_settings(source))
    if not sources:
        logger.info("config: no settings file in any configuration root; "
                    "using defaults (reason_cap=%d)", DEFAULT_REASON_CAP)
    cfg = Config(
        timezone=_valid_timezone(
            values.text(data, "timezone", default=DEFAULT_TIMEZONE)),
        time_format=values.text(data, "time_format",
                                default=DEFAULT_TIME_FORMAT),
        maintenance_default_expiry=values.text(
            data, "maintenance_default_expiry",
            default=DEFAULT_MAINTENANCE_EXPIRY),
        reason_cap=_valid_reason_cap(data.get("reason_cap", DEFAULT_REASON_CAP)),
        branch_cap=_valid_branch_cap(data.get("branch_cap", DEFAULT_BRANCH_CAP)),
        maintenance_cap=_valid_maintenance_cap(
            data.get("maintenance_cap", DEFAULT_MAINTENANCE_CAP)),
        retry_interval=values.text(data, "retry_interval", default=""),
        retry_attempts=_valid_retry_attempts(
            data.get("retry_attempts", DEFAULT_RETRY_ATTEMPTS)),
        stacktrace=values.flag(data, "stacktrace", default=True),
        card_status_line=_valid_card_status_line(
            data.get("card_status_line", DEFAULT_CARD_STATUS_LINE)),
        dashboard_columns=_valid_dashboard_columns(
            data.get("dashboard_columns", DEFAULT_DASHBOARD_COLUMNS)),
    )
    if sources:
        logger.info(
            "config: loaded %s — timezone=%s, time_format=%r, reason_cap=%d, "
            "branch_cap=%d, maintenance_cap=%d, maintenance_default_expiry=%s, "
            "retry_interval=%s, retry_attempts=%d, card_status_line=%s, "
            "dashboard_columns=%s",
            ", ".join(str(source.resolve()) for source in sources),
            cfg.timezone, cfg.time_format, cfg.reason_cap, cfg.branch_cap,
            cfg.maintenance_cap, cfg.maintenance_default_expiry,
            cfg.retry_interval or "off", cfg.retry_attempts,
            cfg.card_status_line, cfg.dashboard_columns)
    return cfg


# The single shared configuration for this process.
config = load_config()
