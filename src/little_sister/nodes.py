"""Node metadata: ``nodes.yaml`` declarations + the startup consistency pass.

A node's display metadata — ``about`` (subject metadata, what it *is*; ADR-0012) and
``title`` (a short display label; ADR-0017) — is fed by precedence: a ``nodes.yaml``
declaration keyed by path **>** the inline value on the owning check **>** empty.
``nodes.yaml`` is optional and lives in the checks directory — or each directory of
the path-list union (ADR-0015) — so it can reach container / host nodes no single
check owns. The consistency pass flags declarations no check feeds.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from little_sister.checks import Check, CheckError
from little_sister.checks.loader import NODES_FILENAME, resolve_dirs
from little_sister.logger import logger
from little_sister.status import (
    HEARTBEAT_PATH,
    join_path,
    on_same_line,
    split_path,
)


@dataclass(frozen=True)
class NodeMeta:
    """Per-node display metadata seeded at startup: ``about`` + ``title``."""
    about: str = ""
    title: str = ""

    def merged_over(self, base: NodeMeta) -> NodeMeta:
        """This entry's fields, each falling back to ``base`` when empty."""
        return NodeMeta(about=self.about or base.about,
                        title=self.title or base.title)


def load_nodes(directory: str | Path | None = None) -> dict[str, NodeMeta]:
    """Load node metadata from every ``nodes.yaml`` across the checks directories (a
    path-list union; ADR-0015). Returns ``path -> NodeMeta``. The file is **optional**
    — a missing one is fine; a path declared in two files is a hard error, like a
    duplicate check."""
    meta: dict[str, NodeMeta] = {}
    source: dict[str, Path] = {}
    for base in resolve_dirs(directory):
        node_file = base / NODES_FILENAME
        if not node_file.is_file():
            continue
        for node_path, entry in _read_nodes_file(node_file).items():
            if node_path in meta:
                raise CheckError(
                    f"duplicate node metadata for {node_path!r}: "
                    f"{source[node_path]} and {node_file}")
            meta[node_path] = entry
            source[node_path] = node_file
    return meta


def resolve_metadata(checks: list[Check],
                     nodes: dict[str, NodeMeta]) -> dict[str, NodeMeta]:
    """Merge node metadata by precedence — ``nodes.yaml`` > inline-on-check > empty,
    **per field** (ADR-0012 / ADR-0017) — into one ``path -> NodeMeta`` map."""
    meta: dict[str, NodeMeta] = {
        check.path: NodeMeta(about=check.about, title=check.title)
        for check in checks if check.about or check.title}
    for path, entry in nodes.items():
        meta[path] = entry.merged_over(meta.get(path, NodeMeta()))
    return meta


def run_consistency_pass(checks: list[Check],
                         metadata: dict[str, NodeMeta]) -> None:
    """Surface metadata defects at startup: **warn** for a declared path no check
    covers (an orphan — segment-wise check-root coverage, ADR-0014), and **info** for
    a host / container node that has checks but no ``about`` (ADR-0012)."""
    # The engine's heartbeat is check-less by design (ADR-0005) yet a fair
    # metadata target — a title/about there feeds the status strip and its
    # hover card (#24) — so it counts as covered, never as an orphan.
    roots = [check.path for check in checks] + [HEARTBEAT_PATH]
    for path in sorted(metadata):
        if not any(on_same_line(path, root) for root in roots):
            logger.warning(
                "nodes: metadata declared for %r but no check covers it", path)
    described = {path for path, entry in metadata.items() if entry.about}
    for container in sorted(_containers(checks)):
        if container not in described:
            logger.info("nodes: %r has checks but no 'about'", container)


def _containers(checks: list[Check]) -> set[str]:
    """Nodes that aggregate checks rather than report their own status: every check
    root's proper ancestors, plus a **branch** check's own root (a container its
    leaves roll into — its root is not among the nodes it owns)."""
    containers: set[str] = set()
    for check in checks:
        segments = split_path(check.path)
        for depth in range(1, len(segments)):
            containers.add(join_path(*segments[:depth]))
        if check.path not in check.owned_nodes():
            containers.add(check.path)
    return containers


def _read_nodes_file(node_file: Path) -> dict[str, NodeMeta]:
    """Parse one ``nodes.yaml`` into ``path -> NodeMeta``. Each value is a mapping
    (``{about: …, title: …}``) or a bare-string shorthand for ``about`` alone; an
    entry with neither field is dropped."""
    try:
        with open(node_file, encoding="utf-8") as handle:
            data = yaml.safe_load(handle) or {}
    except yaml.YAMLError as error:
        raise CheckError(f"{node_file.name}: invalid YAML: {error}") from error
    if not isinstance(data, dict):
        raise CheckError(f"{node_file.name}: top-level YAML must be a mapping")
    nodes: dict[str, NodeMeta] = {}
    for node_path, value in data.items():
        entry = _meta_of(value)
        if entry.about or entry.title:
            nodes[join_path(str(node_path))] = entry   # canonical absolute path
    return nodes


def _meta_of(value: Any) -> NodeMeta:
    if isinstance(value, dict):
        return NodeMeta(about=str(value.get("about", "")),
                        title=str(value.get("title", "")))
    return NodeMeta(about=str(value) if value else "")
