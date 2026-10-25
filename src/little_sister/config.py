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
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
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
from little_sister.logger import logger, stamp_in
from little_sister.looks import LOOKS, Look
from little_sister.notes import DEFAULT_CAP as DEFAULT_NOTES_CAP
from little_sister.notes import DEFAULT_KEEP as DEFAULT_NOTES_KEEP
from little_sister.notes import DEFAULT_MAX_AGE as DEFAULT_NOTES_MAX_AGE
from little_sister.notes import DEFAULT_MIN_AGE as DEFAULT_NOTES_MIN_AGE
from little_sister.notes import Retention, parse_age
from little_sister.state import DEFAULT_KEEPER_INTERVAL, DEFAULT_STATE_INTERVAL

DEFAULT_TIMEZONE = "Europe/Berlin"
DEFAULT_TIME_FORMAT = "%Y-%m-%d %H:%M:%S"
DEFAULT_MAINTENANCE_EXPIRY = "7d"
DEFAULT_REASON_CAP = 6
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
    # rest (the reason-overflow budget, ADR-0056 decision 1): the collapsed reason
    # block is clamped to this many lines, so short reasons show that many reasons
    # while a wrapped reason uses more of the budget.
    # A non-negative int (0 shows none up front); the _status_grid.html reason macro
    # passes it through as the block's --reason-lines. Not tree.js's CLIP_SLOP.
    reason_cap: int = DEFAULT_REASON_CAP
    # How the wall first looks wherever nobody else speaks for a node (ADR-0128):
    # `chips`, whether a node's children start as chips, and `fold_ok`, whether its
    # healthy lines and children start folded behind *✓ +N ok* — `true` the more
    # compact look for both. The fourth of the first look's layers: a node's
    # `nodes.yaml` entry, the file of the check that writes it and that check's type
    # speak first (`little_sister.first_look`). Unset is `None`, nobody said, and the
    # built-in look decides: open, its healthy shown, but a big level as chips.
    chips: bool | None = None
    fold_ok: bool | None = None
    # What this instance is called, on `/system` and in whatever a package writes
    # down about the process it is running in (ADR-0074). Empty means the
    # hostname, which in a container is already the task or pod name. Validated
    # in `little_sister.instance`, not here, because what a name may contain is a
    # fact about the *mark* it becomes and not about this file — and because this
    # module may not import that one, which reads this.
    instance: str = ""
    # Maintenance pins the strip pill's popover shows before a "+N more" links to the
    # full list, *Handled* at /handled (ADR-0056): the count-cap sibling of
    # reason_cap, plumbed to the full page and the ?fragment swap. A non-negative int
    # (0 sends every pin straight to /handled).
    maintenance_cap: int = DEFAULT_MAINTENANCE_CAP
    # A subject's newest readings the node that stands for it shows, beneath its
    # curves (ADR-0092): the count-cap sibling of the two above, and the one a
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
    # The budgeted failure retry (ADR-0033, ADR-0125): while what a check's last
    # run rolls up to is not OK, run it again after this interval instead of
    # waiting out its frequency — at most `retry_attempts` times per failure
    # episode, then back to the nominal frequency until what the run rolls up to
    # changes. A duration string or bare seconds, kept as text and parsed where
    # used (the maintenance_default_expiry pattern); empty or 0 = off, which is
    # the default — nothing changes until a deployment opts in. A check config
    # can override either field.
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
    # How often the observed state — the event log and the series — goes to a
    # keeper while no other instance stands by (ADR-0134 decision 6), in seconds:
    # met at the first write of the kept files after it falls due, so never more
    # often than ``state_interval``, which is its cadence while one does. The pins
    # go at the next scheduler tick after they change, and the local files keep
    # ``state_interval``. Without a keeper it does nothing. A positive integer;
    # default 900.
    keeper_interval: int = DEFAULT_KEEPER_INTERVAL
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
    # A positive integer; default 3,072, which leaves a composed record room to
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
    # How long a node's notes are kept (ADR-0047 decisions 9 to 11): never one of
    # the last ``notes_keep`` on a node; past ``notes_max_age`` by its age alone;
    # past ``notes_min_age`` while its node holds more than ``notes_cap``, the
    # oldest first. The two ages are written ``13mo``, ``400d`` — a bare ``m`` is
    # minutes everywhere else, and refused here. Defaults 10, 50, 13mo and 25mo:
    # more than a year, so that a yearly problem is recognizable when it recurs,
    # and more than two.
    notes_keep: int = DEFAULT_NOTES_KEEP
    notes_cap: int = DEFAULT_NOTES_CAP
    notes_min_age: str = DEFAULT_NOTES_MIN_AGE
    notes_max_age: str = DEFAULT_NOTES_MAX_AGE
    # The deployment's default for each look a browser may choose for itself
    # (`looks.py`, ADR-0029): its theme, how a run of chips is drawn, whether a pause
    # on a node's name opens its card, how a row and a chip answer the pointer. Read
    # from the key the look is named by; a
    # value the look does not have warns and gives way to the library's own. A
    # browser that has chosen keeps its choice in the presentation cookie.
    looks: Mapping[str, str] = field(
        default_factory=lambda: {look.key: look.default for look in LOOKS})

    @property
    def tzinfo(self) -> ZoneInfo:
        """The configured timezone (validated at load time)."""
        return ZoneInfo(self.timezone)

    @property
    def notes_retention(self) -> Retention:
        """The four keys as the notes' retention reads them (ADR-0047 decision 9),
        each validated at load."""
        return Retention(keep=self.notes_keep, cap=self.notes_cap,
                         min_age=parse_age(self.notes_min_age),
                         max_age=parse_age(self.notes_max_age))


def _valid_timezone(name: str,
                    read: Callable[[ZoneInfo], None] | None = None) -> str:
    """The zone ``name``, or the default where it names none — handed to ``read``
    the moment it is known, which is before the warning that a name was not
    understood: the warning is then stamped in the zone that is used (ADR-0120
    decision 9)."""
    try:
        zone = ZoneInfo(name)
    except (ZoneInfoNotFoundError, ValueError):
        if read is not None:
            read(ZoneInfo(DEFAULT_TIMEZONE))
        logger.warning("config: unknown timezone %r; using %s", name,
                       DEFAULT_TIMEZONE)
        return DEFAULT_TIMEZONE
    if read is not None:
        read(zone)
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


def _valid_switch(name: str, value: object) -> bool | None:
    """A tri-state switch of the first look (ADR-0128): ``None`` where the key is
    absent, else a real boolean. Anything else is logged and left unset, as the caps
    beside it are replaced by their defaults — ``values.flag`` would read a quoted
    ``"false"`` as true, and ``values.strict_flag`` would raise at import, where
    nothing catches it and no instance would start."""
    if value is None or isinstance(value, bool):
        return value
    logger.warning("config: %s %r is not true or false; leaving it unset", name, value)
    return None


def _valid_maintenance_cap(value: object) -> int:
    """Coerce the maintenance popover cap to a non-negative int; a bad or negative
    value falls back to the default (``0`` sends every pin to *Handled*)."""
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


def _valid_look(look: Look, value: object) -> str:
    """The deployment's default for ``look``: one of its values, or the library's own
    with a warning naming the choices — a look only ever changes how a page is
    drawn, so a bad value costs that look and nothing else.

    YAML 1.1 reads an unquoted ``off`` as false, and ``on`` as true, so
    ``inspection_card: off`` arrives as a boolean: it is read back as the word it
    was written as."""
    if isinstance(value, bool):
        value = "on" if value else "off"
    choice = str(value).strip().lower()
    if choice not in look.values:
        logger.warning("config: %s %r is not one of %s; using %r", look.key, value,
                       "/".join(look.values), look.default)
        return look.default
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


def _valid_keeper_interval(value: object) -> int:
    """Coerce the keeper's interval (ADR-0134) to a positive int; a bad or
    non-positive value falls back to the default with a warning, as
    ``state_interval`` does — a typo must not send every interval, or never."""
    try:
        seconds = int(str(value).strip())
    except ValueError:
        logger.warning("config: keeper_interval %r is not an integer; using %d",
                       value, DEFAULT_KEEPER_INTERVAL)
        return DEFAULT_KEEPER_INTERVAL
    if seconds < 1:
        logger.warning("config: keeper_interval %d is not positive; using %d",
                       seconds, DEFAULT_KEEPER_INTERVAL)
        return DEFAULT_KEEPER_INTERVAL
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


def _valid_notes_count(key: str, value: object, default: int) -> int:
    """``notes_keep`` or ``notes_cap``: a whole number, at least 1; anything else
    warns and gives way to the default."""
    try:
        count = int(str(value).strip())
    except ValueError:
        logger.warning("config: %s %r is not an integer; using %d", key, value,
                       default)
        return default
    if count < 1:
        logger.warning("config: %s %d is not positive; using %d", key, count,
                       default)
        return default
    return count


def _valid_notes_age(key: str, value: object, default: str) -> str:
    """``notes_min_age`` or ``notes_max_age`` as the notes read it (ADR-0047 decision
    10): an age, ``13mo`` or ``400d``; one that is none — a bare ``m`` among them,
    which is minutes — warns and gives way to the default."""
    try:
        parse_age(value)
    except ValueError as error:
        logger.warning("config: %s: %s; using %s", key, error, default)
        return default
    return str(value).strip()


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


#: Every key ``settings.yaml`` has, which :func:`load_config` reads: anything else in
#: the file is named at load, since a misspelt key would otherwise do nothing and
#: say nothing (backlog #91 §7.10).
SETTINGS_KEYS: tuple[str, ...] = (
    "timezone", "time_format", "maintenance_default_expiry", "instance",
    "reason_cap", "chips", "fold_ok", "maintenance_cap", "reading_cap",
    "retry_interval", "retry_attempts", "stacktrace", "card_status_line",
    "dashboard_columns", "state_interval", "keeper_interval", "max_workers",
    "entry_limit",
    "memory_share", "record_limit", "series_limit", "escalate_after",
    "notes_keep", "notes_cap", "notes_min_age", "notes_max_age",
    *(look.key for look in LOOKS),
)


#: Keys ``settings.yaml`` had, which nothing reads any longer, each with what took
#: its place: named at load in a line of their own rather than ignored in silence,
#: so a deployment that still states one learns what it does now.
RETIRED_SETTINGS: Mapping[str, str] = {
    "branch_cap": ("a level nobody configured starts open now, and a big one as chips; "
                   "state `chips:` for a level that should start otherwise (ADR-0128)"),
}


def _warn_unknown_settings(layer: Mapping[str, Any], source: Path) -> None:
    """Name the keys of one settings file that nothing reads, beside the ones that
    are read, as `links.yaml`'s loader does for its own — a key that was retired in a
    line of its own, saying what took its place."""
    for key in sorted(str(key) for key in layer if str(key) in RETIRED_SETTINGS):
        logger.warning("config: %s: %s is no longer read: %s", source, key,
                       RETIRED_SETTINGS[key])
    unknown = sorted(str(key) for key in layer if str(key) not in SETTINGS_KEYS
                     and str(key) not in RETIRED_SETTINGS)
    if unknown:
        logger.warning("config: %s: unknown key(s) %s (known: %s)", source,
                       ", ".join(unknown), ", ".join(SETTINGS_KEYS))


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
                config_dir: str | Path | None = None,
                zone_read: Callable[[ZoneInfo], None] | None = None) -> Config:
    """Load the settings; on any problem, fall back to defaults.

    ``path`` names a single file and bypasses layering (as
    ``LITTLE_SISTER_CONFIG`` does). Otherwise the ``settings`` aspect of every
    configuration root in ``config_dir`` (default ``LITTLE_SISTER_CONFIG_DIR``) is
    shallow-merged **per key**, later root winning. Logs (INFO) the resolved
    absolute path of every layer and the values they yield, so a deployment can see
    exactly which file and which cap took effect.

    ``zone_read`` is told the time zone the moment it has been read, before any
    other setting is looked at: the process's own configuration names the logger
    there, so every line about a setting is stamped in the configured zone (ADR-0120
    decision 9). A load that names nobody — a test's, a tool's — tells nobody.
    """
    sources = [Path(path)] if path is not None else settings_files(config_dir)
    data: dict[str, Any] = {}
    for source in sources:
        layer = _read_settings(source)
        _warn_unknown_settings(layer, source)
        data.update(layer)
    timezone = _valid_timezone(
        values.text(data, "timezone", default=DEFAULT_TIMEZONE), zone_read)
    if not sources:
        logger.info("config: no settings file in any configuration root; "
                    "using defaults (reason_cap=%d)", DEFAULT_REASON_CAP)
    cfg = Config(
        timezone=timezone,
        time_format=values.text(data, "time_format",
                                default=DEFAULT_TIME_FORMAT),
        maintenance_default_expiry=values.text(
            data, "maintenance_default_expiry",
            default=DEFAULT_MAINTENANCE_EXPIRY),
        instance=values.text(data, "instance", default=""),
        reason_cap=_valid_reason_cap(data.get("reason_cap", DEFAULT_REASON_CAP)),
        chips=_valid_switch("chips", data.get("chips")),
        fold_ok=_valid_switch("fold_ok", data.get("fold_ok")),
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
        keeper_interval=_valid_keeper_interval(
            data.get("keeper_interval", DEFAULT_KEEPER_INTERVAL)),
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
        notes_keep=_valid_notes_count(
            "notes_keep", data.get("notes_keep", DEFAULT_NOTES_KEEP),
            DEFAULT_NOTES_KEEP),
        notes_cap=_valid_notes_count(
            "notes_cap", data.get("notes_cap", DEFAULT_NOTES_CAP), DEFAULT_NOTES_CAP),
        notes_min_age=_valid_notes_age(
            "notes_min_age", data.get("notes_min_age", DEFAULT_NOTES_MIN_AGE),
            DEFAULT_NOTES_MIN_AGE),
        notes_max_age=_valid_notes_age(
            "notes_max_age", data.get("notes_max_age", DEFAULT_NOTES_MAX_AGE),
            DEFAULT_NOTES_MAX_AGE),
        looks={look.key: _valid_look(look, data.get(look.key, look.default))
               for look in LOOKS},
    )
    if sources:
        logger.info(
            "config: loaded %s — timezone=%s, time_format=%r, reason_cap=%d, "
            "chips=%s, fold_ok=%s, "
            "maintenance_cap=%d, reading_cap=%d, "
            "maintenance_default_expiry=%s, "
            "retry_interval=%s, retry_attempts=%d, card_status_line=%s, "
            "dashboard_columns=%s, state_interval=%d, keeper_interval=%d, "
            "max_workers=%d, "
            "entry_limit=%d, memory_share=%s, record_limit=%d, "
            "series_limit=%d, escalate_after=%d, notes=%d/%d/%s/%s, looks=%s",
            ", ".join(str(source.resolve()) for source in sources),
            cfg.timezone, cfg.time_format, cfg.reason_cap,
            "unset" if cfg.chips is None else cfg.chips,
            "unset" if cfg.fold_ok is None else cfg.fold_ok,
            cfg.maintenance_cap, cfg.reading_cap, cfg.maintenance_default_expiry,
            cfg.retry_interval or "off", cfg.retry_attempts,
            cfg.card_status_line, cfg.dashboard_columns, cfg.state_interval,
            cfg.keeper_interval, cfg.max_workers, cfg.entry_limit, cfg.memory_share,
            cfg.record_limit, cfg.series_limit, cfg.escalate_after,
            cfg.notes_keep, cfg.notes_cap, cfg.notes_min_age, cfg.notes_max_age,
            ", ".join(f"{key}={value}" for key, value in cfg.looks.items()))
    return cfg


# The single shared configuration for this process, which hands its time zone to
# the logger the moment it has read it.
config = load_config(zone_read=stamp_in)
