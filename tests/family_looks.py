"""What the family's check types propose for the levels they write, stated by path.

The wall cost harness draws two deployments' trees, and neither runs a check: the
hosts tree's host types are the library's own and propose their levels themselves
(``hosts_tree.checks``), but the family's packages — ``little-sister-github``,
``little-sister-aws`` and ``little-sister-wiz`` — are not installed here. Since the
interactive wall's flip a level nobody speaks for starts open, so a tree drawn without
their proposals is a wall no deployment of theirs draws. This states each proposal in
``nodes.yaml``'s form, on the paths it resolves to, as the versions that come out with
the flip declare them (backlog #91's note, §7.5, the family's declarations):

- github 0.1.13: ``actions`` its repositories and each repository's workflows as
  chips (its ADR-0019), and its three banded aspects' bands as chips, a band's box
  ten lines (its ADR-0019 §3);
- aws 0.1.8: an account's aspects as chips — each account's node where every account
  has one, else the check's own node — and the members of ``lambda``,
  ``codepipeline`` and ``s3`` as chips, and each ``batch`` queue's job names (its
  ADR-0023);
- wiz 0.1.5: its bands as chips, a band's box ten lines, and a band the shipped map
  grades OK, ``informational``, with its issues folded (its ADR-0006).

A name is matched on the path's segments, as the type's own declaration matches it
beneath its check; where a deployment's own files say otherwise, they win, as ever.

Dev-only: lives under ``tests/`` and never ships in the package.
"""
from __future__ import annotations

from little_sister.checks.metadata import Stated
from little_sister.nodes import NodeMeta
from little_sister.tree import StatusSnapshot, StatusTree

_CHIPS = Stated(chips=True)
_BOTH = Stated(chips=True, children=Stated(chips=True))
_CHILDREN = Stated(children=Stated(chips=True))
#: Bands as chips, and a band's box ten lines: github's banded aspects', wiz's own.
_BANDS = Stated(chips=True, children=Stated(reason_cap=10))
#: github's banded aspects, whose bands start as chips.
_BANDED = ("code_scanning_quality", "code_scanning_security", "security_advisories")
#: aws's rosters made of nodes, and the one whose members' members are the chips.
_ROSTERS = ("lambda", "codepipeline", "s3")
_QUEUES = "batch"


def declared(tree: StatusTree, *, account_node: bool = True) -> dict[str, NodeMeta]:
    """The family's proposals for ``tree``'s levels, by path. ``account_node`` says
    whether the aws check gives every account a node of its own, as one reading many
    accounts does, or stands for its one account with its own node."""
    said: dict[str, NodeMeta] = {}

    def walk(node: StatusSnapshot) -> None:
        parts = node.path.strip("/").split("/")
        name = parts[-1]
        if "github" in parts[:-1]:
            if name == "actions":
                said[node.path] = NodeMeta(look=_BOTH)
            elif name in _BANDED:
                said[node.path] = NodeMeta(look=_BANDS)
        if name == "wiz":
            said[node.path] = NodeMeta(look=_BANDS)
        elif name == "informational" and "wiz" in parts[:-1]:
            said[node.path] = NodeMeta(look=Stated(fold_ok=True))
        if "aws" in parts:
            # 0 the check's own node, 1 an account or an aspect, 2 an account's aspect
            depth = len(parts) - parts.index("aws") - 1 + (0 if account_node else 1)
            if depth == 1:
                said[node.path] = NodeMeta(look=_CHIPS)
            elif depth == 2 and name in _ROSTERS:
                said[node.path] = NodeMeta(look=_BOTH)
            elif depth == 2 and name == _QUEUES:
                said[node.path] = NodeMeta(look=_CHILDREN)
        for child in node.children:
            walk(child)

    root = tree.snapshot()
    if root is not None:
        walk(root)
    return said
