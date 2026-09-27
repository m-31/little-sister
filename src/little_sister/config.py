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
from little_sister.limits import (
    DEFAULT_MAX_WORKERS,
    ENTRY_LIMIT,
    MEMORY_SHARE,
    RECORD_LIMIT,
    SERIES_LIMIT,
)
from little_sister.logger import logger
from little_sister.state import DEFAULT_STATE_INTERVAL

DEFAULT_TIMEZONE = "Europe/Berlin"
DEFAULT_TIME_FORMAT = "%Y-%m-%d %H:%M:%S"
DEFAULT_MAINTENANCE_EXPIRY = "7d"
DEFAULT_REASON_CAP = 6
DEFAULT_BRANCH_CAP = 3
DEFAULT_MAINTENANCE_CAP = 5
DEFAULT_READING_CAP = 10

#: Consecutive worse readings before a node escalates, unless somebody says
#: otherwise. **One** is deliberate: it is exactly today's behavior, so the counter
#: arrives switched off and a deployment turns it on where it has a flapping subject
#: rather than everywhere at once.
DEFAULT_ESCALATE_AFTER = 1
DEFAULT_RETRY_ATTEMPTS = 2
DEFAULT_CARD_STATUS_LINE = "beside"
CARD_STATUS_LINES = ("beside", "below")
DEFAULT_DASHBOARD_COLUMNS = "flow"
DASHBOARD_COLUMNS = ("flow", "plain")
SETTINGS_ASPECT = "settings"
# The engine's three sizing numbers keep their defaults in `limits.py`, where the
# measurement that reads each of them lives; this module only lets a deployment
# state one of its own.
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
    # What this instance is called, on `/system` and in whatever a package writes
    # down about the process it is running in (ADR-0074). Empty means the
    # hostname, which in a container is already the task or pod name. Validated
    # in `little_sister.instance`, not here, because what a name may contain is a
    # fact about the *mark* it becomes and not about this file — and because this
    # module may not import that one, which reads this.
    instance: str = ""
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
    # A subject's newest readings the node that stands for it shows, beneath its
    # curves (ADR-0092): the count-cap sibling of the three above, and the one a
    # check may state for itself (`reading_cap` in its own YAML wins). A
    # non-negative int; 0 shows the curves alone and leaves every reading to the
    # node's History page, which always lists them all.
    reading_cap: int = DEFAULT_READING_CAP
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
    # How often the kept state files — the event log, and what joins it — are
    # written under `var/state/` (ADR-0071), in seconds: at most once per
    # interval on the scheduler tick, and once more at graceful shutdown, so an
    # unclean shutdown loses at most this much. Maintenance pins are written
    # through as they change and never wait on it. A positive integer; default 60.
    state_interval: int = DEFAULT_STATE_INTERVAL
    # Worker threads the engine's pool is built with (ADR-0075): the ceiling, not
    # the size — a pool is never larger than the number of checks configured. It
    # is also the number startup measures the checks' *declared* cost against, so
    # raising it is how a deployment answers a refusal it disagrees with. A
    # positive integer; default 8.
    max_workers: int = DEFAULT_MAX_WORKERS
    # How many reason entries the tree may hold, over every node (ADR-0072): the
    # number the engine's `entries` line watches, and the one the declared entry
    # sums are refused against at startup. A positive integer; default 100,000,
    # which at the measured half kilobyte an entry is about fifty megabytes held.
    entry_limit: int = ENTRY_LIMIT
    # The share of what the machine gives this process that the process may be
    # resident at before the engine's `memory` line turns red — amber at 80 % of
    # that. A fraction above 0 and at most 1; default 0.5, one gunicorn worker
    # beside the OS. There is no line at all where the machine cannot say what it
    # gives the process.
    memory_share: float = MEMORY_SHARE
    # How heavy one entry's record may be, in the bytes of its JSON — the form it
    # costs in, since that is what every client is sent. Refused at the
    # `CheckResult` seam, whole: a check shapes the record it hands over to fit; and
    # refused at startup for a type that declares more than this (ADR-0075).
    # A positive integer; default 2,048, which leaves a composed record room to
    # grow and refuses a raw row from a provider's API.
    record_limit: int = RECORD_LIMIT
    # What every series together may weigh, in the bytes of the JSON the series
    # file keeps their readings in (ADR-0087): past it the series written to
    # longest ago is evicted and the engine's `series` line is red, from 80 % of
    # it that line is amber, and a configuration whose series would need more at
    # today's estate is the `series.projection` line. A positive integer;
    # default 8 MiB, since the series file a keeper carries every interval binds
    # long before memory does.
    series_limit: int = SERIES_LIMIT
    # How many consecutive readings of a worse code a node needs before it
    # publishes that code to its parent (backlog #38 B). A positive integer;
    # default 1, which publishes at once and is what every deployment had before
    # there was a counter. A check may override it for itself.
    escalate_after: int = DEFAULT_ESCALATE_AFTER

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


def _valid_reading_cap(value: object) -> int:
    """Coerce the readings cap (ADR-0092) to a non-negative int; a bad or
    negative value falls back to the default (``0`` shows the curves alone). A
    check's own ``reading_cap`` is read by the check, and refuses the load instead."""
    try:
        cap = int(str(value).strip())
    except ValueError:
        logger.warning("config: reading_cap %r is not an integer; using %d",
                       value, DEFAULT_READING_CAP)
        return DEFAULT_READING_CAP
    if cap < 0:
        logger.warning("config: reading_cap %d is negative; using 0", cap)
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


def _valid_state_interval(value: object) -> int:
    """Coerce the kept-file write interval (ADR-0071) to a positive int; a bad or
    non-positive value falls back to the default with a warning — a typo must not
    make the writer spin, or stop."""
    try:
        seconds = int(str(value).strip())
    except ValueError:
        logger.warning("config: state_interval %r is not an integer; using %d",
                       value, DEFAULT_STATE_INTERVAL)
        return DEFAULT_STATE_INTERVAL
    if seconds < 1:
        logger.warning("config: state_interval %d is not positive; using %d",
                       seconds, DEFAULT_STATE_INTERVAL)
        return DEFAULT_STATE_INTERVAL
    return seconds


def _valid_max_workers(value: object) -> int:
    """Coerce the worker ceiling (ADR-0075) to a positive int; a bad or
    non-positive value falls back to the default with a warning — a typo must not
    leave the engine with no thread to run a check on."""
    try:
        workers = int(str(value).strip())
    except ValueError:
        logger.warning("config: max_workers %r is not an integer; using %d",
                       value, DEFAULT_MAX_WORKERS)
        return DEFAULT_MAX_WORKERS
    if workers < 1:
        logger.warning("config: max_workers %d is not positive; using %d",
                       workers, DEFAULT_MAX_WORKERS)
        return DEFAULT_MAX_WORKERS
    return workers


def _valid_entry_limit(value: object) -> int:
    """Coerce the tree's entry limit (ADR-0072) to a positive int; a bad or
    non-positive value falls back to the default with a warning — a limit of zero
    would put the engine's own line past it before a check has run."""
    try:
        entries = int(str(value).strip())
    except ValueError:
        logger.warning("config: entry_limit %r is not an integer; using %d",
                       value, ENTRY_LIMIT)
        return ENTRY_LIMIT
    if entries < 1:
        logger.warning("config: entry_limit %d is not positive; using %d",
                       entries, ENTRY_LIMIT)
        return ENTRY_LIMIT
    return entries


def _valid_escalate_after(value: object) -> int:
    """Coerce the escalation count to a positive int; a bad or non-positive value
    falls back to the default with a warning. Zero would mean *never publish*, which
    is a silence no deployment can have meant and the one direction ADR-0032 rule 7
    refuses outright."""
    try:
        count = int(str(value).strip())
    except ValueError:
        logger.warning("config: escalate_after %r is not an integer; using %d",
                       value, DEFAULT_ESCALATE_AFTER)
        return DEFAULT_ESCALATE_AFTER
    if count < 1:
        logger.warning("config: escalate_after %d is not positive; using %d",
                       count, DEFAULT_ESCALATE_AFTER)
        return DEFAULT_ESCALATE_AFTER
    return count


def _valid_record_limit(value: object) -> int:
    """Coerce the per-record byte limit to a positive int; a bad or non-positive
    value falls back to the default with a warning. Zero would refuse every record
    a check offers, including the ones this deployment configured a check to
    gather, which is a limit that only looks like caution."""
    try:
        limit = int(str(value).strip())
    except ValueError:
        logger.warning("config: record_limit %r is not an integer; using %d",
                       value, RECORD_LIMIT)
        return RECORD_LIMIT
    if limit < 1:
        logger.warning("config: record_limit %d is not positive; using %d",
                       limit, RECORD_LIMIT)
        return RECORD_LIMIT
    return limit


def _valid_series_limit(value: object) -> int:
    """Coerce the series' ceiling (ADR-0087) to a positive int of bytes; a bad or
    non-positive value falls back to the default with a warning. Zero would evict
    every series on the tick after it was written, which is a history switched off
    by a setting that reads like a size."""
    try:
        limit = int(str(value).strip())
    except ValueError:
        logger.warning("config: series_limit %r is not an integer; using %d",
                       value, SERIES_LIMIT)
        return SERIES_LIMIT
    if limit < 1:
        logger.warning("config: series_limit %d is not positive; using %d",
                       limit, SERIES_LIMIT)
        return SERIES_LIMIT
    return limit


def _valid_memory_share(value: object) -> float:
    """Coerce the resident-memory share to a fraction in ``(0, 1]``; anything
    else falls back to the default with a warning. A share above one would be a
    limit the process cannot reach without being killed first, which is a limit
    that says nothing."""
    try:
        share = float(str(value).strip())
    except ValueError:
        logger.warning("config: memory_share %r is not a number; using %s",
                       value, MEMORY_SHARE)
        return MEMORY_SHARE
    if not 0 < share <= 1:
        logger.warning("config: memory_share %s is not in (0, 1]; using %s",
                       share, MEMORY_SHARE)
        return MEMORY_SHARE
    return share


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
        instance=values.text(data, "instance", default=""),
        reason_cap=_valid_reason_cap(data.get("reason_cap", DEFAULT_REASON_CAP)),
        branch_cap=_valid_branch_cap(data.get("branch_cap", DEFAULT_BRANCH_CAP)),
        maintenance_cap=_valid_maintenance_cap(
            data.get("maintenance_cap", DEFAULT_MAINTENANCE_CAP)),
        reading_cap=_valid_reading_cap(
            data.get("reading_cap", DEFAULT_READING_CAP)),
        retry_interval=values.text(data, "retry_interval", default=""),
        retry_attempts=_valid_retry_attempts(
            data.get("retry_attempts", DEFAULT_RETRY_ATTEMPTS)),
        stacktrace=values.flag(data, "stacktrace", default=True),
        card_status_line=_valid_card_status_line(
            data.get("card_status_line", DEFAULT_CARD_STATUS_LINE)),
        dashboard_columns=_valid_dashboard_columns(
            data.get("dashboard_columns", DEFAULT_DASHBOARD_COLUMNS)),
        state_interval=_valid_state_interval(
            data.get("state_interval", DEFAULT_STATE_INTERVAL)),
        max_workers=_valid_max_workers(
            data.get("max_workers", DEFAULT_MAX_WORKERS)),
        entry_limit=_valid_entry_limit(data.get("entry_limit", ENTRY_LIMIT)),
        memory_share=_valid_memory_share(
            data.get("memory_share", MEMORY_SHARE)),
        record_limit=_valid_record_limit(
            data.get("record_limit", RECORD_LIMIT)),
        series_limit=_valid_series_limit(
            data.get("series_limit", SERIES_LIMIT)),
        escalate_after=_valid_escalate_after(
            data.get("escalate_after", DEFAULT_ESCALATE_AFTER)),
    )
    if sources:
        logger.info(
            "config: loaded %s — timezone=%s, time_format=%r, reason_cap=%d, "
            "branch_cap=%d, maintenance_cap=%d, reading_cap=%d, "
            "maintenance_default_expiry=%s, "
            "retry_interval=%s, retry_attempts=%d, card_status_line=%s, "
            "dashboard_columns=%s, state_interval=%d, max_workers=%d, "
            "entry_limit=%d, memory_share=%s, record_limit=%d, "
            "series_limit=%d, escalate_after=%d",
            ", ".join(str(source.resolve()) for source in sources),
            cfg.timezone, cfg.time_format, cfg.reason_cap, cfg.branch_cap,
            cfg.maintenance_cap, cfg.reading_cap, cfg.maintenance_default_expiry,
            cfg.retry_interval or "off", cfg.retry_attempts,
            cfg.card_status_line, cfg.dashboard_columns, cfg.state_interval,
            cfg.max_workers, cfg.entry_limit, cfg.memory_share,
            cfg.record_limit, cfg.series_limit, cfg.escalate_after)
    return cfg


# The single shared configuration for this process.
config = load_config()
