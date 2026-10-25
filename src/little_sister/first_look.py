"""Where a node's first look comes from (ADR-0128): which of its places speaks first.

Three keys decide how the wall first draws a node — ``chips``, whether its children
start as chips; ``fold_ok``, whether its healthy lines and children start folded
behind *✓ +N ok*; ``reason_cap``, its box's line budget — and the claim beside them,
``show_when_quiet``, rides the same addresses. They are stated in four files, each a
layer, and the first statement found wins (§3.4 and §7.9 of the interactive wall's
note):

1. ``nodes.yaml``: the node's path, then its parent's path's ``children:`` — the only
   place a container no check speaks for gets a look of its own;
2. the file of the check that writes the node: the node's name under ``subnodes:``,
   then its parent's name entry's ``children:``; for the check's own node the file's
   top level, and for a child of it the top level's ``children:``;
3. the check's type, the same way: ``subnode_defaults`` by name and ``node_defaults``
   for its own node — a proposal, which the deployment takes back in the file;
4. ``settings.yaml``, for everything nobody spoke for;
5. built in: open, its healthy ones shown — but a level that, opened, would draw more
   than :data:`BIG_LEVEL` boxes, counted all the way down, starts as chips.

A node a run names takes nothing declared for its name, since the names a file and a
type speak of are the ones a type always emits (ADR-0118); it takes its parent's
``children:``, which is how a look reaches a level of accounts, queues or
repositories. **This is a view rule, as** :mod:`little_sister.titles` **is**: the keys
are the web page's settings, read from the files when a page renders, and they are
never put on the snapshot, so the envelope does not carry them (ADR-0080) and the
snapshot stays free of where a value came from (ADR-0025). The claim is the
exception, a statement on the snapshot the contract publishes: the engine asks
:func:`statement` for it as it writes a node.

Two things are not in the tree, and this module is told them: which check writes a
path — the check whose path the node's is or lies beneath, the deepest mount on its
line, where a mount two checks share speaks for neither, though beneath it the one
whose subtree a node is in does, and each of its children starts as the check that
writes it says of the children of its own node — and which paths a run named, which
the status tree keeps beside its mounts as runs write them
(``StatusTree.named_by_run``). The built-in look counts what a level would draw, so
here it is *nobody said* and :func:`draw` decides it for the page it draws.

**What the server draws** (:func:`draw`, §7.5 and §7.9 of the note) is the second
half: the looks of a page's nodes turned into the faces it renders as it arrives.
The cards a page shows start open — the wall's root and a page's node take no
``chips`` — and beneath them a node starts closed where its parent's ``chips`` says
so and it claims no ``show_when_quiet``, where a ``depth=`` closes its level, and,
where nobody spoke, where its level is big: opened, more than :data:`BIG_LEVEL`
boxes, counted all the way down, the deeper levels deciding first. Then the failure
budget opens, in each card, the first three failures the first look hides — errors
before warnings, in the card's order — with the nodes on their paths
(:func:`~little_sister.tree.own_failure`) — unless the browser's look says *Failures:
stay chips*, where a failure stays as its look drew it, red, and the wall keeps its
size. ``fold_ok`` folds a node's healthy ones, and each box takes its
``reason_cap``. Beside the faces it keeps what the planner
prices (:mod:`little_sister.dashboard_layout`): which nodes the configuration and the
tree's shape close, since the planner reads no status — not what the budget opens.
"""
from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from little_sister.checks.metadata import CHILDREN_KEYS, Statements
from little_sister.status import join_path, leaf_name, parent_path, split_path
from little_sister.tree import own_failure

if TYPE_CHECKING:
    from little_sister.checks import Check
    from little_sister.config import Config
    from little_sister.nodes import NodeMeta
    from little_sister.tree import StatusSnapshot


@dataclass(frozen=True)
class FirstLook:
    """How the wall first draws a node: ``chips``, whether its children start as
    chips, and ``fold_ok``, whether its healthy lines and children start folded —
    ``None`` where nobody spoke, which :func:`draw` draws as the built-in look — and
    ``reason_cap``, its box's line budget, which ``settings.yaml`` always states."""
    chips: bool | None
    fold_ok: bool | None
    reason_cap: int


def statement(key: str, path: str, *, check: Check | None,
              nodes: Mapping[str, NodeMeta],
              named_by_run: Callable[[str], bool]) -> bool | int | None:
    """The first statement layers 1 to 3 make of ``key`` — one of ``chips``,
    ``fold_ok``, ``reason_cap`` and ``show_when_quiet`` — for the node at ``path``,
    or ``None`` where none of them speaks. ``check`` is the check that writes the
    node, or ``None`` where no check alone does; ``nodes`` the deployment's
    ``nodes.yaml`` as loaded; ``named_by_run`` whether a run named a path."""
    if key not in CHILDREN_KEYS:
        raise KeyError(key)
    parent = parent_path(path)
    own = nodes.get(path)
    if own is not None:
        said = own.show_when_quiet if key == "show_when_quiet" else own.look.get(key)
        if said is not None:
            return said
    above = nodes.get(parent)
    if above is not None and above.look.children is not None and path != "/":
        said = above.look.children.get(key)
        if said is not None:
            return said
    if check is None or not _at_or_beneath(path, check.path):
        return None
    for statements in (check.file_statements, check.type_statements):
        said = _said_by(statements, key, path, check.path, named_by_run)
        if said is not None:
            return said
    return None


def _said_by(statements: Statements, key: str, path: str, mount: str,
             named_by_run: Callable[[str], bool]) -> bool | int | None:
    """What one place — a check's file, or its type — says of ``key`` for the node at
    ``path`` beneath the check's ``mount``: the node's own address first, then its
    parent's ``children:``."""
    if path == mount:
        return statements.own.get(key)
    if not named_by_run(path):
        entry = statements.by_name.get(leaf_name(path))
        if entry is not None and entry.get(key) is not None:
            return entry.get(key)
    parent = parent_path(path)
    if parent == mount:
        kids = statements.own.children
    elif named_by_run(parent):
        return None
    else:
        named = statements.by_name.get(leaf_name(parent))
        kids = None if named is None else named.children
    return None if kids is None else kids.get(key)


def _at_or_beneath(path: str, mount: str) -> bool:
    """Whether ``path`` is ``mount`` or lies beneath it, segment by segment."""
    segments, above = split_path(path), split_path(mount)
    return segments[:len(above)] == above


class FirstLooks:
    """Every node's first look, from the loaded checks, the deployment's
    ``nodes.yaml`` and ``settings.yaml``, and what the status tree says of the paths
    a run named. Built once at startup; :meth:`look` reads it per node."""

    def __init__(self, checks: Sequence[Check], nodes: Mapping[str, NodeMeta],
                 config: Config, named_by_run: Callable[[str], bool]) -> None:
        self._nodes = nodes
        self._config = config
        self._named_by_run = named_by_run
        mounts: dict[str, list[Check]] = {}
        for check in checks:
            mounts.setdefault(join_path(check.path), []).append(check)
        self._mounts = mounts

    def writer(self, path: str) -> Check | None:
        """The check that writes the node at ``path``: the check mounted on the
        deepest mount at or above it. A mount two checks share is written by both,
        and so by neither alone; beneath it, the one whose own subtree the node is in
        (:meth:`~little_sister.checks.Check.owned_nodes`, which the loader keeps
        apart), and none where neither's is."""
        segments = split_path(path)
        for depth in range(len(segments), -1, -1):
            mount = join_path(*segments[:depth])
            sharing = self._mounts.get(mount)
            if not sharing:
                continue
            if len(sharing) == 1:
                return sharing[0]
            if mount == join_path(path):
                return None
            owners = [check for check in sharing
                      if any(_at_or_beneath(path, owned)
                             for owned in check.owned_nodes())]
            return owners[0] if len(owners) == 1 else None
        return None

    def shared(self, path: str) -> bool:
        """Whether two checks or more are mounted on ``path``."""
        return len(self._mounts.get(join_path(path), ())) > 1

    def children_chips(self, parent: str, child: str) -> bool | None:
        """Whether ``child`` starts closed: what the look of ``parent`` says of its
        children, its ``chips`` — ``None`` where nobody spoke, which :func:`draw`
        draws as the built-in look. Beneath a mount two checks share, whose own look
        neither speaks for, each child starts as the check that writes it says of the
        children of the node it is mounted on: ``nodes.yaml``'s word on the mount
        first, for every child alike, then that check's file and its type, then
        ``settings.yaml`` (ADR-0128 decision 5, as amended) — so a host's two metrics
        checks each speak for their own leaves."""
        if not self.shared(parent):
            return self.look(parent).chips
        mount = join_path(parent)
        said = statement("chips", mount, check=None, nodes=self._nodes,
                         named_by_run=self._named_by_run)
        if said is None:
            owner = self.writer(child)
            if owner is not None:
                said = statement("chips", mount, check=owner, nodes={},
                                 named_by_run=self._named_by_run)
        return self._config.chips if said is None else bool(said)

    def look(self, path: str) -> FirstLook:
        """The node's first look, each key from the first layer that states it and
        else ``settings.yaml`` — ``None`` for a switch it leaves unset too."""
        check = self.writer(path)

        def first(key: str) -> bool | int | None:
            return statement(key, join_path(path), check=check, nodes=self._nodes,
                             named_by_run=self._named_by_run)

        chips, fold_ok, cap = first("chips"), first("fold_ok"), first("reason_cap")
        return FirstLook(
            chips=self._config.chips if chips is None else bool(chips),
            fold_ok=self._config.fold_ok if fold_ok is None else bool(fold_ok),
            reason_cap=self._config.reason_cap if cap is None else int(cap))


# --- what the server draws ------------------------------------------------------------

#: How many failures the first look hides that each card opens, with the nodes on
#: their paths (backlog #91 §3.3): the failure budget, which holds the wall's shape
#: in an outage — a card grows by at most this many paths.
FAILURE_BUDGET = 3
#: How many boxes a level nobody configured may draw opened before it starts as
#: chips: the net for the level nobody expected to be big, a run that suddenly
#: names a great many children (backlog #91 §2, 2026-10-24). Counted all the way
#: down, each child as it has decided, and never by a status — the same on every
#: screen, the planner pricing what it decides. The library's, not a setting: a
#: deployment that wants a level otherwise states its ``chips``.
BIG_LEVEL = 30
#: The order the budget takes the failures it finds in: errors before warnings.
_SEVERITY = {"error": 0, "warn": 1}


@dataclass(frozen=True)
class Drawn:
    """What the server draws of a page's nodes as they arrive (:func:`draw`): which
    start closed, and which of those the failure budget opened instead; whose healthy
    ones start folded; and each box's line budget. Beside them, ``priced``: the nodes
    the configuration and the tree's shape close — a statement, a ``depth=``, the net
    for a big level — what the planner prices, since it reads no status and so not
    what the budget opens."""

    closed: frozenset[str] = frozenset()
    priced: frozenset[str] = frozenset()
    budget: frozenset[str] = frozenset()
    folded: frozenset[str] = frozenset()
    caps: Mapping[str, int] = field(default_factory=dict)

    def faces(self, children: Sequence[StatusSnapshot]) -> list[bool]:
        """For each child of a level, whether it is drawn closed, a chip."""
        return [child.path in self.closed for child in children]


def draw(page: StatusSnapshot, looks: FirstLooks, *, depth_closed: int | None = None,
         failures_open: bool = True) -> Drawn:
    """The first look of ``page``'s nodes, as the server draws it (§7.5, §7.9 of the
    interactive wall's note): ``page`` is the wall's root or the node a page is about,
    its children the page's cards, level 1, which start open.

    Beneath them a node starts closed where its parent's ``chips`` says so, unless it
    claims ``show_when_quiet``, and open where it says otherwise — beneath a mount two
    checks share, where its own check says so (:meth:`FirstLooks.children_chips`).
    Where nobody spoke, the built-in look: open, its healthy ones shown — but a level
    that, opened, would draw more than :data:`BIG_LEVEL` boxes starts as chips, as
    ``chips: true`` would start it, the deeper levels deciding first
    (:func:`_drawn_beneath`). A ``depth=`` in the address closes its level whatever is
    said, the cards' among them. Then, in each card, the first :data:`FAILURE_BUDGET`
    failures the first look hides — on the node itself or beneath a closed node above
    it — errors before warnings and in the card's order, open with every node on
    their path, and those it opened are its own (``budget``) — unless
    ``failures_open`` is false, the browser's look *Failures: stay chips*
    (``looks.py``), where a failure stays as its look drew it and the wall keeps its
    size. ``fold_ok`` and ``reason_cap`` are each node's, the page's own node's fold
    among them; the wall's root is nobody's node and takes neither."""
    closed: set[str] = set()
    priced: set[str] = set()
    folded: set[str] = set()
    caps: dict[str, int] = {}

    def walk(node: StatusSnapshot, level: int, chips: bool | None) -> int:
        """Draw ``node``'s children, level ``level``, and answer how many boxes they
        draw beneath it once they have decided. ``chips`` is what ``node``'s look
        says of its children, ``None`` for the page's own node, whose cards take no
        key; beneath a mount two checks share, each child's own check says it."""
        shared = level > 1 and looks.shared(node.path)
        said = {child.path: (looks.children_chips(node.path, child.path) if shared
                             else chips)
                for child in node.children}
        beneath: dict[str, int] = {}
        for child in node.children:
            look = looks.look(child.path)
            caps[child.path] = look.reason_cap
            if look.fold_ok:
                folded.add(child.path)
            beneath[child.path] = walk(child, level + 1, look.chips)
        big = _drawn_beneath(node.children, said, beneath, big=False) > BIG_LEVEL
        for child in node.children:
            above = said[child.path]
            if depth_closed == level:
                shut = True
            elif level == 1 or above is False:
                shut = False
            elif above or big:
                shut = not child.show_when_quiet
            else:
                shut = False
            if shut:
                priced.add(child.path)
                closed.add(child.path)
        return _drawn_beneath(node.children, said, beneath, big=big)

    if page.path != "/" and looks.look(page.path).fold_ok:
        folded.add(page.path)
    walk(page, 1, None)
    budget: set[str] = set()
    for card in page.children if failures_open else ():
        for path in _budgeted(card, closed):
            if path in closed:
                closed.discard(path)
                budget.add(path)
    return Drawn(closed=frozenset(closed), priced=frozenset(priced),
                 budget=frozenset(budget), folded=frozenset(folded), caps=caps)


def _drawn_beneath(children: Sequence[StatusSnapshot],
                   said: Mapping[str, bool | None], beneath: Mapping[str, int], *,
                   big: bool) -> int:
    """How many boxes a level draws: each child a box with what it draws beneath it
    where it stands open — as its parent's ``chips`` says, or where nobody spoke and
    the level is not ``big`` — and nothing where it stands a chip, but for a child
    that claims ``show_when_quiet``, which stays open whatever is said. No status
    counts, nor a ``depth=``: the net reads the tree's shape and what is said."""
    boxes = 0
    for child in children:
        above = said[child.path]
        shut = bool(above) or (above is None and big)
        if not shut or child.show_when_quiet:
            boxes += 1 + beneath[child.path]
    return boxes


def _budgeted(card: StatusSnapshot, closed: set[str]) -> list[str]:
    """The paths the failure budget opens in one card: the first
    :data:`FAILURE_BUDGET` of the failures ``closed`` hides there — a node that fails
    for itself and is closed, or stands beneath a closed node — errors before
    warnings, each kind in the card's order, every node on their path with them."""
    hidden: list[tuple[int, int, list[str]]] = []

    def walk(node: StatusSnapshot, path: list[str], hides: bool) -> None:
        line = [*path, node.path]
        hides = hides or node.path in closed
        failure = own_failure(node)
        if hides and failure is not None:
            hidden.append((_SEVERITY[failure], len(hidden), line))
        for child in node.children:
            walk(child, line, hides)

    walk(card, [], False)
    hidden.sort(key=lambda found: found[:2])
    return [path for _rank, _order, line in hidden[:FAILURE_BUDGET] for path in line]
