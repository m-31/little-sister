"""Load check configs from one or more directories and instantiate the checks."""
from __future__ import annotations

import os
from pathlib import Path

import yaml

from little_sister.checks.base import CHECK_TYPES, Check, CheckError
from little_sister.status import on_same_line

DEFAULT_CHECKS_DIR = os.environ.get("LITTLE_SISTER_CHECKS_DIR", "checks")

# Node metadata, not a check — it shares the checks directory but `load_checks`
# skips it (ADR-0012); ``nodes`` loads it.
NODES_FILENAME = "nodes.yaml"


def load_checks(directory: str | Path | None = None) -> list[Check]:
    """Load every ``*.yaml`` / ``*.yml`` config across one or more directories.

    ``directory`` is a **path-list**: a string of directories joined by
    ``os.pathsep`` (e.g. ``"base:hosts/alpha"``), a single :class:`~pathlib.Path`,
    or ``None`` to use ``LITTLE_SISTER_CHECKS_DIR`` (default ``checks``). Every
    directory loads and the checks form a **union** (ADR-0015); a single directory
    is the common case — a union of one. Each listed directory must exist.

    Each file is a mapping with a ``type`` plus the common and type-specific
    fields; relative paths inside it (e.g. a ``script``) resolve against that
    file's own directory. Sub-directories (e.g. ``scripts/``) are ignored. Two
    checks that own **overlapping** nodes (:meth:`Check.owned_nodes`) are a hard
    error — no override, no merge, no precedence. Raises :class:`CheckError` on a
    bad or unknown config, a missing directory, or an ownership conflict.
    """
    loaded: list[tuple[Check, Path]] = []
    for base in resolve_dirs(directory):
        if not base.is_dir():
            raise CheckError(f"checks directory not found: {base}")
        for config_path in sorted([*base.glob("*.yaml"), *base.glob("*.yml")]):
            if config_path.name == NODES_FILENAME:
                continue   # node metadata, loaded by `nodes`, not a check
            loaded.append((_load_one(config_path), config_path))
    _reject_overlapping_owners(loaded)
    return [check for check, _ in loaded]


def resolve_dirs(directory: str | Path | None) -> list[Path]:
    """Resolve the path-list into directories, in order.

    A :class:`~pathlib.Path` is a single directory; a string is split on
    ``os.pathsep`` (blank segments dropped); ``None`` falls back to
    ``DEFAULT_CHECKS_DIR``.
    """
    if isinstance(directory, Path):
        return [directory]
    spec = DEFAULT_CHECKS_DIR if directory is None else directory
    return [Path(segment) for segment in
            (raw.strip() for raw in spec.split(os.pathsep)) if segment]


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
        return check_cls.from_config(config, config_path.parent)
    except CheckError as error:
        raise CheckError(f"{config_path.name}: {error}") from error


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
