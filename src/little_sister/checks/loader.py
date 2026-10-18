"""Load check configs from the ``checks`` aspect of the configuration directory
and instantiate the checks."""
from __future__ import annotations

import logging
from pathlib import Path

import yaml

from little_sister.checks.base import CHECK_TYPES, Check, CheckError
from little_sister.checks.metadata import (
    CHILDREN_KEYS,
    SUBNODE_KEYS,
    unknown_check_keys,
)
from little_sister.config_dir import (
    CONFIG_DIR_ENV,
    aspect_files,
    config_roots,
    fatal,
)
from little_sister.status import HEARTBEAT_PATH, on_same_line

logger = logging.getLogger(__name__)

# The aspect this module reads (ADR-0031). Always a directory: the unit of data is
# the file — one check per *.yaml — so there is no single document to hold it.
CHECKS_ASPECT = "checks"


def load_checks(config_dir: str | Path | None = None) -> list[Check]:
    """Load every ``*.yaml`` / ``*.yml`` config across the ``checks`` aspect of
    every configuration root.

    ``config_dir`` is the configuration **path-list** (ADR-0031): a string of roots
    joined by ``os.pathsep`` (e.g. ``"base:sites/alpha"``), a single
    :class:`~pathlib.Path`, or ``None`` to use ``LITTLE_SISTER_CONFIG_DIR``
    (default ``config``). Each root's ``checks/`` loads and the checks form a
    **union** (ADR-0015); a single root is the common case — a union of one.

    Each file is a mapping with a ``type`` plus the common and type-specific
    fields; relative paths inside it (e.g. a ``script``) resolve against that
    file's own directory, so a check that moved one level deeper with the rest of
    the tree needs no edit. Sub-directories (``scripts/``, ``examples/``) are
    ignored — and nothing has to be skipped by name any more, because
    ``config/checks/`` holds checks and nothing else.

    Raises :class:`ConfigError` — fatal, never caught — when the configuration tree
    itself is unusable, and :class:`CheckError` on a bad or unknown config, an
    ownership conflict, or a check owning nodes on the reserved ``/little-sister``
    line (ADR-0005). An **empty** checks aspect is neither: watching nothing yet is
    a real, temporary state (see :func:`little_sister.engine.create_engine`).
    """
    loaded: list[tuple[Check, Path]] = []
    for base in checks_dirs(config_dir):
        for config_path in sorted([*base.glob("*.yaml"), *base.glob("*.yml")]):
            loaded.append((_load_one(config_path), config_path))
    _reject_reserved_paths(loaded)
    _reject_overlapping_owners(loaded)
    _reject_broken_dependencies(loaded)
    return [check for check, _ in loaded]


def checks_dirs(config_dir: str | Path | None = None) -> list[Path]:
    """Every root's ``checks/`` directory, in path-list order.

    **One** root providing it is enough — a site root carrying only its own node
    metadata is normal, and demanding checks in every root would defeat the
    layering this exists for. **None** providing it is fatal: an instance with
    nowhere to look for checks is misconfigured, not empty, and the page it would
    serve is a reassuring green one about nothing (ADR-0031 §7).
    """
    roots = config_roots(config_dir)
    directories = aspect_files(CHECKS_ASPECT, config_dir)
    if not directories:
        raise fatal(
            f"no {CHECKS_ASPECT}/ directory in any configuration root — searched "
            f"{', '.join(str(root.resolve()) for root in roots)} "
            f"({CONFIG_DIR_ENV}). At least one root must provide {CHECKS_ASPECT}/,"
            f" even if it is still empty (ADR-0031)")
    return directories


def _load_one(config_path: Path) -> Check:
    """Read one config file and instantiate its check (relative paths resolve
    against the file's own directory)."""
    try:
        with open(config_path, encoding="utf-8") as handle:
            config = yaml.safe_load(handle) or {}
    except yaml.YAMLError as error:
        raise CheckError(f"{config_path.name}: invalid YAML: {error}") from error
    if not isinstance(config, dict):
        raise CheckError(f"{config_path.name}: top-level YAML must be a mapping")

    check_cls = CHECK_TYPES.get(str(config.get("type")))
    if check_cls is None:
        known = ", ".join(sorted(CHECK_TYPES)) or "(none)"
        raise CheckError(
            f"{config_path.name}: unknown or missing check 'type' "
            f"{config.get('type')!r} (known: {known})")
    try:
        check = check_cls.from_config(config, config_path.parent)
    except CheckError as error:
        raise CheckError(f"{config_path.name}: {error}") from error
    # One line for the file, for the keys the library reads that it does not know
    # (ADR-0128): a misspelt `chip:` would otherwise do nothing, in silence. The
    # rest of the top level is the type's, which the library cannot judge.
    unknown = unknown_check_keys(config)
    if unknown:
        logger.warning("checks: %s: unknown key(s) %s, not read (a subnodes: entry "
                       "knows %s; a children: block %s)", config_path,
                       ", ".join(unknown), ", ".join(SUBNODE_KEYS),
                       ", ".join(CHILDREN_KEYS))
    return check


def _reject_reserved_paths(loaded: list[tuple[Check, Path]]) -> None:
    """Reject a check that owns nodes on the engine's own line (ADR-0005).

    ``HEARTBEAT_PATH`` is reserved: the engine heartbeats that node itself, and
    the dashboard lifts it out of the card grid into the one-line status strip
    (ADR-0024), which must never have a subtree hiding behind it. Keeping deployment
    checks off the whole line also leaves it free for future engine-owned
    children (connected satellite engines, say).
    """
    for check, source in loaded:
        for node in sorted(check.owned_nodes()):
            if on_same_line(node, HEARTBEAT_PATH):
                raise CheckError(
                    f"{source.name}: node {node!r} is on the reserved "
                    f"{HEARTBEAT_PATH!r} line — the engine's own heartbeat "
                    f"lives there (ADR-0005)")


def _reject_broken_dependencies(loaded: list[tuple[Check, Path]]) -> None:
    """Reject the load when a ``depends_on`` names no configured check, or when the
    dependencies form a **cycle** (backlog #38 A).

    Both are hard errors rather than a shrug, on
    [ADR-0015](../../docs/adr/0015-check-discovery-union.md)'s argument: a
    declaration that quietly does nothing is worse than a refusal, because what it
    quietly does is *not shield*, and nobody finds out until the outage it was
    written for arrives and forty subjects alarm anyway.

    A cycle has no evaluation order at all — each of its members waits for another
    to be believed — so there is no *fail toward alarming* answer available either;
    the only honest one is to refuse the configuration that states it.
    """
    by_path = {check.path: source for check, source in loaded}
    for check, source in loaded:
        if check.depends_on is None:
            continue
        if check.depends_on not in by_path:
            raise CheckError(
                f"check {check.path!r} ({source.name}) depends on "
                f"{check.depends_on!r}, which no configured check writes")
    graph = {check.path: check.depends_on for check, _ in loaded}
    for start in graph:
        seen = [start]
        at = graph[start]
        while at is not None:
            if at in seen:
                seen.append(at)
                raise CheckError(
                    "check dependencies form a cycle: " + " -> ".join(seen))
            seen.append(at)
            at = graph.get(at)


def _reject_overlapping_owners(loaded: list[tuple[Check, Path]]) -> None:
    """Reject the load when two checks own overlapping nodes (ADR-0015).

    Each check declares the node subtrees it owns (:meth:`Check.owned_nodes`).
    Two owned paths overlap when one is equal to, or a (segment-wise) ancestor of,
    the other — the same node, or one inside the other's subtree. The metrics pair
    (``host-metrics`` + ``qnap-metrics``) owns disjoint child subtrees and so
    coexists on one host node; a duplicated check, two same-type branches, or a
    leaf placed on a branch's shared container are caught and named.
    """
    seen: list[tuple[str, Path]] = []
    for check, source in loaded:
        nodes = sorted(check.owned_nodes())
        for node in nodes:
            for other_node, other_source in seen:
                if on_same_line(node, other_node):
                    raise CheckError(
                        f"check ownership conflict: {node!r} ({source.name}) "
                        f"overlaps {other_node!r} ({other_source.name})")
        seen.extend((node, source) for node in nodes)
