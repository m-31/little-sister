"""Node metadata: the ``nodes`` aspect's declarations + the startup consistency pass.

A node's display metadata — ``about`` (subject metadata, what it *is*; ADR-0012),
``title`` (a short display label; ADR-0017), ``order`` (its declared rank among
its siblings; ADR-0055) and ``show_when_quiet`` (this node's quiet lines are still
information; ADR-0063) — is fed by precedence: a ``nodes.yaml``
declaration keyed by path **>** the inline value on the owning check **>** unstated.
All four are seeded onto the tree here, at startup, before the first tick — which
is what puts them ahead of the fourth source ``order`` and the labels also have: the
values a running ``CheckResult`` carries, which fill an unset field and no more.
The file is optional and is the ``nodes`` aspect of the configuration directory —
``config/nodes.yaml`` in each root of the path-list (ADR-0031) — so it can reach
container / host nodes no single check owns. The consistency pass flags declarations
no check feeds.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from little_sister import self_report
from little_sister.checks import Check, CheckError
from little_sister.config_dir import aspect_files
from little_sister.logger import logger
from little_sister.reasons import plain, slug
from little_sister.status import (
    HEARTBEAT_PATH,
    join_path,
    on_same_line,
    split_path,
)
from little_sister.values import number, strict_flag


@dataclass(frozen=True)
class NodeMeta:
    """Per-node display metadata seeded at startup: ``about``, ``title``, ``order``
    and ``show_when_quiet``.

    ``order`` is the declared sibling rank (ADR-0055) and is ``None`` when neither
    source mentions it — **not** ``0``, which is a rank an author may state on
    purpose, and the only way a declaration can overrule a check's rank by naming
    the default value. It is not a request for alphabetical: ``0`` is the rank the
    unranked carry, so it sorts a node *with* them, ahead of every positive rank,
    rather than back at its alphabetical place — putting a whole ranked set back to
    the alphabet takes an ``order: 0`` per sibling.

    ``show_when_quiet`` (ADR-0063) is ``None`` for the same reason and the same way:
    ``false`` is a value an author may state on purpose — it is how a deployment
    takes back a declaration a check made — so it has to occupy the field where a
    check's ``true`` cannot fill over it. The two labels use the empty string for
    "nobody said", which works there because no author ever means an empty label.
    """
    about: str = ""
    title: str = ""
    order: int | None = None
    show_when_quiet: bool | None = None

    @property
    def declares(self) -> bool:
        """Whether this entry says anything at all. An entry that does not is
        dropped at parse time, so a stray key cannot become a node declaration."""
        return (bool(self.about) or bool(self.title) or self.order is not None
                or self.show_when_quiet is not None)

    def merged_over(self, base: NodeMeta) -> NodeMeta:
        """This entry's fields, each falling back to ``base`` where unstated."""
        return NodeMeta(about=self.about or base.about,
                        title=self.title or base.title,
                        order=base.order if self.order is None else self.order,
                        show_when_quiet=(
                            base.show_when_quiet if self.show_when_quiet is None
                            else self.show_when_quiet))


NODES_ASPECT = "nodes"


def load_nodes(config_dir: str | Path | None = None) -> dict[str, NodeMeta]:
    """Load node metadata from the ``nodes`` aspect of every configuration root, in
    path-list order (ADR-0031). Returns ``path -> NodeMeta``.

    The aspect is **optional** — no root need carry it. Where two roots declare the
    same node path, the **later** root wins, per field: that is what the layering is
    for (a site root retitles one node the shared base declares) and it matches the
    settings rule one table row up. Declaring only ``title`` leaves the base's
    ``about`` standing, exactly as a ``nodes.yaml`` entry layers over a check's
    inline value. An override is **logged with both files named**, because a silent
    winner decided by root order is indistinguishable from a bug.
    """
    meta: dict[str, NodeMeta] = {}
    source: dict[str, Path] = {}
    for node_file in aspect_files(NODES_ASPECT, config_dir):
        for node_path, entry in _read_nodes_file(node_file).items():
            if node_path in meta:
                logger.info(
                    "node metadata for %r overridden by a later configuration "
                    "root: %s wins over %s (ADR-0031)",
                    node_path, node_file, source[node_path])
                meta[node_path] = entry.merged_over(meta[node_path])
            else:
                meta[node_path] = entry
            source[node_path] = node_file
    return meta


def resolve_metadata(checks: list[Check],
                     nodes: dict[str, NodeMeta]) -> dict[str, NodeMeta]:
    """Merge node metadata by precedence — ``nodes.yaml`` > inline-on-check >
    unstated, **per field** (ADR-0012 / ADR-0017 / ADR-0055) — into one
    ``path -> NodeMeta`` map.

    ``order`` joins the labels here rather than being a ``nodes.yaml``-only key: a
    deployment writes ``title:`` and ``about:`` for a node in its check file, and a
    rank that had to move to a second file — with the *same* precedence and the
    *same* per-field merge — would be a rule with no reason behind it. It is only
    the check's **root** that an inline key can reach, which is exactly the node
    that file is about; a branch's subnodes are ranked from the ``CheckResult``,
    where their names exist.
    """
    meta: dict[str, NodeMeta] = {
        check.path: NodeMeta(about=check.about, title=check.title,
                             order=check.order,
                             show_when_quiet=check.show_when_quiet)
        for check in checks
        if (check.about or check.title or check.order is not None
            or check.show_when_quiet is not None)}
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
    # hover card (ADR-0024) — so it counts as covered, never as an orphan.
    roots = [check.path for check in checks] + [HEARTBEAT_PATH]
    for path in sorted(metadata):
        if not any(on_same_line(path, root) for root in roots):
            self_report.startup.note(
                slug("nodes", "orphan", path),
                plain(f"nodes.yaml declares metadata for {path!r} but no check "
                      f"covers it"))
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
    (``{about: …, title: …, order: …, show_when_quiet: …}``) or a bare-string
    shorthand for ``about`` alone; an entry stating none of the four is dropped."""
    try:
        with open(node_file, encoding="utf-8") as handle:
            data = yaml.safe_load(handle) or {}
    except yaml.YAMLError as error:
        raise CheckError(f"{node_file.name}: invalid YAML: {error}") from error
    if not isinstance(data, dict):
        raise CheckError(f"{node_file.name}: top-level YAML must be a mapping")
    nodes: dict[str, NodeMeta] = {}
    for node_path, value in data.items():
        entry = _meta_of(value, f"{node_file.name}: {node_path}")
        if entry.declares:
            nodes[join_path(str(node_path))] = entry   # canonical absolute path
    return nodes


def _meta_of(value: Any, where: str) -> NodeMeta:
    if isinstance(value, dict):
        # `order` is read only when the key is *present*: `values.number` cannot
        # tell an absent key from a stated `0`, and that difference is the whole
        # point of the field (ADR-0055). A non-numeric rank raises CheckError —
        # a silently ignored one would leave the row in an order nobody chose.
        order = (number(value, "order", where=where)
                 if value.get("order") is not None else None)
        # `show_when_quiet` is read the same way and for the same reason: an
        # absent key is "nobody said", while a stated `false` is a deployment
        # taking back what a check declared (ADR-0063). A non-boolean raises —
        # `bool("false")` is True, so a quoted YAML boolean would switch the node
        # *on* while the file says off, and nothing downstream could notice.
        quiet = (strict_flag(value, "show_when_quiet", where=where)
                 if value.get("show_when_quiet") is not None else None)
        return NodeMeta(about=str(value.get("about", "")),
                        title=str(value.get("title", "")),
                        order=order, show_when_quiet=quiet)
    return NodeMeta(about=str(value) if value else "")
