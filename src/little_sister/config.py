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


def load_config(path: str | Path | None = None) -> Config:
    """Load the config from ``path`` (default ``config.yaml``); on any problem,
    fall back to defaults."""
    source = Path(path) if path is not None else Path(DEFAULT_CONFIG_PATH)
    try:
        with open(source, encoding="utf-8") as handle:
            data = yaml.safe_load(handle) or {}
    except FileNotFoundError:
        return Config()
    except yaml.YAMLError as error:
        logger.warning("config: invalid YAML in %s: %s; using defaults",
                       source, error)
        return Config()
    if not isinstance(data, dict):
        logger.warning("config: %s must be a mapping; using defaults", source)
        return Config()
    return Config(
        timezone=_valid_timezone(str(data.get("timezone", DEFAULT_TIMEZONE))),
        time_format=str(data.get("time_format", DEFAULT_TIME_FORMAT)),
        maintenance_default_expiry=str(
            data.get("maintenance_default_expiry", DEFAULT_MAINTENANCE_EXPIRY)),
    )


# The single shared configuration for this process.
config = load_config()
