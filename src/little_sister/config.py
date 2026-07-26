"""General application configuration, loaded once from a YAML file.

Defaults apply when the file or a key is missing. The path defaults to
``config.yaml`` in the working directory (override with ``LITTLE_SISTER_CONFIG``).
Add new options by giving them a field and a default here and reading them in
:func:`load_config`.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import yaml

from little_sister.logger import logger

DEFAULT_TIMEZONE = "Europe/Berlin"
DEFAULT_TIME_FORMAT = "%Y-%m-%d %H:%M:%S"
DEFAULT_MAINTENANCE_EXPIRY = "7d"
DEFAULT_REASON_CAP = 6
DEFAULT_BRANCH_CAP = 3
DEFAULT_MAINTENANCE_CAP = 5
DEFAULT_CONFIG_PATH = os.environ.get("LITTLE_SISTER_CONFIG", "config.yaml")


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
    # rest (#9): the collapsed reason block is clamped to this many lines, so short
    # reasons show that many reasons while a wrapped reason uses more of the budget.
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


def load_config(path: str | Path | None = None) -> Config:
    """Load the config from ``path`` (default ``config.yaml``); on any problem,
    fall back to defaults. Logs (INFO) the resolved absolute path and the values it
    yields, so a deployment can see exactly which file and cap took effect."""
    source = Path(path) if path is not None else Path(DEFAULT_CONFIG_PATH)
    try:
        with open(source, encoding="utf-8") as handle:
            data = yaml.safe_load(handle) or {}
    except FileNotFoundError:
        logger.info("config: no file at %s; using defaults (reason_cap=%d)",
                    source.resolve(), DEFAULT_REASON_CAP)
        return Config()
    except yaml.YAMLError as error:
        logger.warning("config: invalid YAML in %s: %s; using defaults",
                       source, error)
        return Config()
    if not isinstance(data, dict):
        logger.warning("config: %s must be a mapping; using defaults", source)
        return Config()
    cfg = Config(
        timezone=_valid_timezone(str(data.get("timezone", DEFAULT_TIMEZONE))),
        time_format=str(data.get("time_format", DEFAULT_TIME_FORMAT)),
        maintenance_default_expiry=str(
            data.get("maintenance_default_expiry", DEFAULT_MAINTENANCE_EXPIRY)),
        reason_cap=_valid_reason_cap(data.get("reason_cap", DEFAULT_REASON_CAP)),
        branch_cap=_valid_branch_cap(data.get("branch_cap", DEFAULT_BRANCH_CAP)),
        maintenance_cap=_valid_maintenance_cap(
            data.get("maintenance_cap", DEFAULT_MAINTENANCE_CAP)),
    )
    logger.info(
        "config: loaded %s — timezone=%s, time_format=%r, reason_cap=%d, "
        "branch_cap=%d, maintenance_cap=%d, maintenance_default_expiry=%s",
        source.resolve(), cfg.timezone, cfg.time_format, cfg.reason_cap,
        cfg.branch_cap, cfg.maintenance_cap, cfg.maintenance_default_expiry)
    return cfg


# The single shared configuration for this process.
config = load_config()
