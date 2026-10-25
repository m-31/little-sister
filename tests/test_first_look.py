"""Where a node's first look comes from (ADR-0128): the resolver, layer by layer and
key by key, in the order §3.4 and §7.9 of the interactive wall's note give — and what
the server draws of it (§7.5), the failure budget among it.

The viewer is the first layer and the browser's; these are the other five — a
node's ``nodes.yaml`` entry, the file of the check that writes it, that check's
type, ``settings.yaml`` and the built-in look — each tried at the node's own address
and then at its parent's ``children:``. The checks here are built from the mapping a
file holds, through the reader every type's construction runs, so the file layer is
read as a deployment's is.
"""
from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime
from typing import Any
from unittest import TestCase

from little_sister.checks import Check, CheckResult, Measurement
from little_sister.checks.base import _parse_common
from little_sister.checks.metadata import Stated
from little_sister.config import DEFAULT_REASON_CAP, Config
from little_sister.first_look import BIG_LEVEL, FirstLook, FirstLooks, draw, statement
from little_sister.nodes import NodeMeta
from little_sister.status import StatusCode, join_path
from little_sister.tree import StatusSnapshot, StatusTree


class _Writes(Check):
    """A check that writes where its file says, owning what it is told to own."""

    type_name = "first-look-test"

    def __init__(self, *, owns: Sequence[str] = (), **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._owns = tuple(owns)

    def owned_nodes(self) -> set[str]:
        return ({join_path(self.path, name) for name in self._owns} if self._owns
                else super().owned_nodes())

    def measure(self) -> Sequence[Measurement]:
        return ()

    def grade(self, measurements: Sequence[Measurement],
              now: datetime) -> CheckResult:
        return CheckResult(StatusCode.OK)


def _check(path: str = "/hosts/alpha", **said: Any) -> _Writes:
    """A check at ``path`` whose file says ``said`` — beside the type's declarations,
    ``declared`` (``subnode_defaults``) and ``own`` (``node_defaults``)."""
    declared = said.pop("declared", None)
    own = said.pop("own", None)
    owns = said.pop("owns", ())
    return _Writes(**_parse_common({"path": path, **said}), subnode_defaults=declared,
                   node_defaults=own, owns=owns)


def _looks(*checks: Check, nodes: dict[str, NodeMeta] | None = None,
           config: Config | None = None,
           named: Sequence[str] = ()) -> FirstLooks:
    return FirstLooks(checks, nodes or {}, config or Config(),
                      named_by_run=lambda path: path in named)


class EachLayerBeatsTheNextTests(TestCase):
    """For each key, every layer speaks for one node, a different word each: the
    first answers, and taking it away lets the next one speak."""

    def _layers(self, key: str, words: Sequence[object]) -> list[object]:
        nodes_word, file_word, type_word, settings_word = words
        nodes = {"/hosts/alpha/disk": NodeMeta(look=Stated(**{key: nodes_word}))}
        settings = Config(**{key: settings_word})
        heard = []
        for layers in range(4, -1, -1):
            file = {"subnodes": {"disk": {key: file_word}}} if layers >= 3 else {}
            declared = {"disk": {key: type_word}} if layers >= 2 else None
            check = _check(**file, declared=declared)
            look = _looks(check, nodes=nodes if layers >= 4 else {},
                          config=settings if layers >= 1 else Config())
            heard.append(getattr(look.look("/hosts/alpha/disk"), key))
        return heard

    def test_chips(self) -> None:
        self.assertEqual(self._layers("chips", (True, False, True, False)),
                         [True, False, True, False, None])

    def test_fold_ok(self) -> None:
        self.assertEqual(self._layers("fold_ok", (False, True, False, True)),
                         [False, True, False, True, None])

    def test_reason_cap(self) -> None:
        self.assertEqual(self._layers("reason_cap", (1, 2, 3, 4)),
                         [1, 2, 3, 4, DEFAULT_REASON_CAP])

    def test_a_node_nobody_speaks_for_is_left_to_the_page(self) -> None:
        # the built-in look, open but for a big level, is the page's to draw, since
        # it counts what a level would draw: the resolver says nobody spoke
        self.assertEqual(_looks(_check()).look("/hosts/alpha/disk"),
                         FirstLook(chips=None, fold_ok=None,
                                   reason_cap=DEFAULT_REASON_CAP))


class OwnAddressBeforeTheParentsChildrenTests(TestCase):
    """Within a layer the node's own address speaks first, then its parent's
    ``children:`` — and that ``children:`` still beats every later layer."""

    def test_in_nodes_yaml(self) -> None:
        nodes = {"/hosts/alpha": NodeMeta(look=Stated(children=Stated(chips=True))),
                 "/hosts/alpha/disk": NodeMeta(look=Stated(chips=False))}
        check = _check(subnodes={"disk": {"chips": False}})
        looks = _looks(check, nodes=nodes)
        self.assertIs(looks.look("/hosts/alpha/disk").chips, False)
        self.assertIs(looks.look("/hosts/alpha/raid").chips, True)
        # a parent's `children:` in nodes.yaml beats the file's own name entry
        del nodes["/hosts/alpha/disk"]
        self.assertIs(_looks(check, nodes=nodes).look("/hosts/alpha/disk").chips, True)

    def test_in_the_file_for_a_child_of_the_checks_own_node(self) -> None:
        check = _check(children={"fold_ok": True},
                       subnodes={"disk": {"fold_ok": False}})
        looks = _looks(check)
        self.assertIs(looks.look("/hosts/alpha/disk").fold_ok, False)
        self.assertIs(looks.look("/hosts/alpha/raid").fold_ok, True)
        # and it reaches no deeper than the check's own children
        self.assertIsNone(looks.look("/hosts/alpha/raid/one").fold_ok)

    def test_in_the_file_for_the_children_of_a_name(self) -> None:
        check = _check(subnodes={"raid": {"children": {"reason_cap": 2}},
                                 "one": {"reason_cap": 7}})
        looks = _looks(check)
        self.assertEqual(looks.look("/hosts/alpha/raid/two").reason_cap, 2)
        self.assertEqual(looks.look("/hosts/alpha/raid/one").reason_cap, 7)
        # the same name elsewhere reaches its own children too
        self.assertEqual(looks.look("/hosts/alpha/backup/raid/two").reason_cap, 2)

    def test_the_files_children_beat_the_types_own_name(self) -> None:
        check = _check(children={"chips": False}, declared={"disk": {"chips": True}})
        self.assertIs(_looks(check).look("/hosts/alpha/disk").chips, False)

    def test_in_the_type_by_name_and_for_its_own_node(self) -> None:
        check = _check(declared={"raid": {"chips": True, "children": {"chips": False}}},
                       own={"fold_ok": True, "children": {"reason_cap": 4}})
        looks = _looks(check)
        self.assertIs(looks.look("/hosts/alpha/raid").chips, True)
        self.assertIs(looks.look("/hosts/alpha/raid/one").chips, False)
        self.assertIs(looks.look("/hosts/alpha").fold_ok, True)
        self.assertEqual(looks.look("/hosts/alpha/disk").reason_cap, 4)

    def test_the_file_takes_back_what_the_type_proposes(self) -> None:
        check = _check(chips=False, declared={"disk": {"chips": True}},
                       subnodes={"disk": {"chips": False}}, own={"chips": True})
        looks = _looks(check)
        self.assertIs(looks.look("/hosts/alpha").chips, False)
        self.assertIs(looks.look("/hosts/alpha/disk").chips, False)


class ANameAtAnyDepthTests(TestCase):
    def test_a_name_reaches_every_node_of_that_name_beneath_the_check(self) -> None:
        looks = _looks(_check(subnodes={"disk": {"chips": True}}))
        for path in ("/hosts/alpha/disk", "/hosts/alpha/raid/disk",
                     "/hosts/alpha/a/b/c/disk"):
            self.assertIs(looks.look(path).chips, True, path)
        self.assertIsNone(looks.look("/hosts/alpha/disks").chips)


class WhatARunNamesTests(TestCase):
    """A node a run names takes nothing declared for its name (ADR-0118), and its
    parent's ``children:`` speaks for it."""

    def test_a_named_child_takes_its_parents_children(self) -> None:
        check = _check(subnodes={"queues": {"children": {"chips": True}},
                                 "batch": {"chips": False}})
        looks = _looks(check, named=("/hosts/alpha/queues/q-17",
                                     "/hosts/alpha/queues/batch"))
        self.assertIs(looks.look("/hosts/alpha/queues/q-17").chips, True)
        # a run named it, so the entry for that name is not its
        self.assertIs(looks.look("/hosts/alpha/queues/batch").chips, True)

    def test_a_childs_own_name_entry_beats_its_parents_children(self) -> None:
        check = _check(subnodes={"queues": {"children": {"chips": True}},
                                 "batch": {"chips": False}})
        self.assertIs(_looks(check).look("/hosts/alpha/queues/batch").chips, False)

    def test_a_named_node_takes_nothing_declared_for_its_name(self) -> None:
        check = _check(subnodes={"batch": {"chips": True}},
                       declared={"batch": {"fold_ok": True}})
        looks = _looks(check, named=("/hosts/alpha/batch",))
        self.assertEqual(looks.look("/hosts/alpha/batch"),
                         FirstLook(chips=None, fold_ok=None,
                                   reason_cap=DEFAULT_REASON_CAP))

    def test_nor_do_its_children_take_its_name_entrys_children(self) -> None:
        check = _check(subnodes={"batch": {"children": {"chips": True}}})
        looks = _looks(check, named=("/hosts/alpha/batch",))
        self.assertIsNone(looks.look("/hosts/alpha/batch/q").chips)
        self.assertIs(_looks(check).look("/hosts/alpha/batch/q").chips, True)

    def test_nodes_yaml_speaks_for_a_named_node_by_its_path(self) -> None:
        nodes = {"/hosts/alpha/batch": NodeMeta(look=Stated(chips=True))}
        looks = _looks(_check(), nodes=nodes, named=("/hosts/alpha/batch",))
        self.assertIs(looks.look("/hosts/alpha/batch").chips, True)


class WhichCheckWritesANodeTests(TestCase):
    def test_a_mount_two_checks_share_takes_only_what_nodes_yaml_says(self) -> None:
        one = _check(chips=True, owns=("cpu",))
        two = _check(chips=True, declared={"raid": {"chips": True}}, owns=("raid",),
                     own={"fold_ok": True})
        looks = _looks(one, two)
        self.assertEqual(looks.look("/hosts/alpha"),
                         FirstLook(chips=None, fold_ok=None,
                                   reason_cap=DEFAULT_REASON_CAP))
        nodes = {"/hosts/alpha": NodeMeta(look=Stated(chips=False))}
        self.assertIs(_looks(one, two, nodes=nodes).look("/hosts/alpha").chips, False)

    def test_beneath_it_the_check_whose_subtree_a_node_is_in_speaks(self) -> None:
        one = _check(subnodes={"cpu": {"chips": True}}, owns=("cpu",))
        two = _check(declared={"raid": {"chips": True}}, owns=("raid",))
        looks = _looks(one, two)
        self.assertIs(looks.writer("/hosts/alpha/cpu"), one)
        self.assertIs(looks.writer("/hosts/alpha/raid/one"), two)
        self.assertIs(looks.look("/hosts/alpha/cpu").chips, True)
        self.assertIs(looks.look("/hosts/alpha/raid").chips, True)
        self.assertIsNone(looks.writer("/hosts/alpha/memory"))

    def test_each_child_of_a_shared_mount_starts_as_its_own_check_says(self) -> None:
        # decision 5 as amended: the mount's own look stays nobody's but nodes.yaml's,
        # and each child starts as the check whose subtree it is says of the children
        # of the node it is mounted on — its file before its type — with nodes.yaml's
        # word on the mount first and settings.yaml's last
        one = _check(chips=True, owns=("cpu",))
        two = _check(own={"chips": False}, owns=("raid",))
        three = _check(owns=("notes",))
        looks = _looks(one, two, three)
        self.assertIsNone(looks.look("/hosts/alpha").chips)
        self.assertIs(looks.children_chips("/hosts/alpha", "/hosts/alpha/cpu"), True)
        self.assertIs(looks.children_chips("/hosts/alpha", "/hosts/alpha/raid"), False)
        self.assertIsNone(looks.children_chips("/hosts/alpha", "/hosts/alpha/notes"))
        self.assertIsNone(looks.children_chips("/hosts/alpha", "/hosts/alpha/other"))
        nodes = {"/hosts/alpha": NodeMeta(look=Stated(chips=False))}
        self.assertIs(_looks(one, two, nodes=nodes).children_chips(
            "/hosts/alpha", "/hosts/alpha/cpu"), False)
        self.assertIs(_looks(one, three, config=Config(chips=True)).children_chips(
            "/hosts/alpha", "/hosts/alpha/notes"), True)
        # a mount one check writes alone answers as its own look does, for a child
        # that is another check's mount too: a share is two checks on one path
        solo = _looks(_check("/solo", chips=True), _check("/solo/site", chips=False))
        self.assertIs(solo.children_chips("/solo", "/solo/x"), True)
        self.assertIs(solo.children_chips("/solo", "/solo/site"), True)

    def test_the_deepest_mount_writes_what_lies_beneath_it(self) -> None:
        host = _check("/macmini", subnodes={"website": {"chips": True}})
        site = _check("/macmini/website", chips=False)
        looks = _looks(host, site)
        self.assertIs(looks.writer("/macmini/website/http"), site)
        self.assertIs(looks.writer("/macmini/disk"), host)
        self.assertIs(looks.look("/macmini/website").chips, False)

    def test_a_container_no_check_writes_takes_nodes_yaml_and_settings(self) -> None:
        nodes = {"/network": NodeMeta(look=Stated(chips=True))}
        looks = _looks(_check("/network/vpn"), nodes=nodes,
                       config=Config(fold_ok=True))
        self.assertIsNone(looks.writer("/network"))
        self.assertEqual(looks.look("/network"),
                         FirstLook(chips=True, fold_ok=True,
                                   reason_cap=DEFAULT_REASON_CAP))


class TheClaimRidesTheSameAddressesTests(TestCase):
    """``show_when_quiet`` is asked of the same layers by the engine, as it writes a
    node; nodes.yaml's own path is seeded instead, and so answers first."""

    def test_the_claim_from_each_place_in_its_order(self) -> None:
        check = _check(subnodes={"queues": {"children": {"show_when_quiet": False}},
                                 "batch": {"show_when_quiet": True}},
                       declared={"q-1": {"show_when_quiet": True}})

        def claim(path: str, nodes: dict[str, NodeMeta] | None = None) -> object:
            return statement("show_when_quiet", path, check=check, nodes=nodes or {},
                             named_by_run=lambda _path: False)

        self.assertIs(claim("/hosts/alpha/queues/batch"), True)   # its own name
        self.assertIs(claim("/hosts/alpha/queues/q-1"), False)    # file before type
        self.assertIsNone(claim("/hosts/alpha/other/q-2"))
        above = {"/hosts/alpha/queues": NodeMeta(
            look=Stated(children=Stated(show_when_quiet=False)))}
        self.assertIs(claim("/hosts/alpha/queues/batch", above), False)

    def test_a_key_no_layer_knows_is_refused(self) -> None:
        with self.assertRaises(KeyError):
            statement("chip", "/x", check=None, nodes={},
                      named_by_run=lambda _path: False)


def _said(**looks: Stated) -> dict[str, NodeMeta]:
    """``nodes.yaml`` as loaded: each path's look."""
    return {path: NodeMeta(look=look) for path, look in looks.items()}


def _root(tree: StatusTree, path: str = "") -> StatusSnapshot:
    node = tree.snapshot(path)
    assert node is not None
    return node


class WhatTheServerDrawsTests(TestCase):
    """How each node starts as the page arrives (§7.5's *What the server draws*):
    closed where its parent's ``chips`` says, open where nobody spoke but for a big
    level (:class:`TheNetForABigLevelTests`), a ``depth=`` level closed — and, beside
    it, what the planner prices."""

    def setUp(self) -> None:
        self.tree = StatusTree()
        for leaf in ("disk", "raid", "notes"):
            self.tree.upsert(f"/c/host/{leaf}", StatusCode.OK)
        self.tree.set_show_when_quiet("/c/host/notes", True)

    def _draw(self, nodes: dict[str, NodeMeta] | None = None,
              config: Config | None = None, **how: Any):
        return draw(_root(self.tree), _looks(nodes=nodes, config=config), **how)

    def test_a_level_whose_node_says_chips_starts_closed_but_for_a_claim(self) -> None:
        drawn = self._draw(_said(**{"/c/host": Stated(chips=True)}))
        self.assertEqual(drawn.closed, {"/c/host/disk", "/c/host/raid"})
        # and the planner prices what the configuration closes
        self.assertEqual(drawn.priced, {"/c/host/disk", "/c/host/raid"})

    def test_a_level_whose_node_says_no_chips_starts_open(self) -> None:
        drawn = self._draw(_said(**{"/c/host": Stated(chips=False)}))
        self.assertEqual(drawn.closed, frozenset())
        self.assertEqual(drawn.priced, frozenset())

    def test_where_nobody_spoke_every_node_starts_open_its_healthy_shown(self) -> None:
        # the built-in look (§3.4): a quiet leaf, a failing one, a claim and every
        # branch open, and nothing folded
        self.tree.upsert("/c/host/raid", StatusCode.WARN, "degraded")
        drawn = self._draw()
        self.assertEqual((drawn.closed, drawn.priced, drawn.folded),
                         (frozenset(), frozenset(), frozenset()))

    def test_the_cards_start_open_whatever_is_said(self) -> None:
        # the wall's root takes no key: `chips: true` in settings.yaml closes every
        # level beneath the cards and none of the cards — nor does the built-in look
        # close a card that is a quiet leaf
        self.tree.upsert("/leafcard", StatusCode.OK)
        drawn = self._draw(config=Config(chips=True))
        self.assertNotIn("/c", drawn.closed)
        self.assertEqual(drawn.closed, {"/c/host", "/c/host/disk", "/c/host/raid"})
        self.assertNotIn("/leafcard", self._draw().closed)

    def test_a_depth_closes_its_level_whatever_is_said(self) -> None:
        said = _said(**{"/c/host": Stated(chips=False)})
        drawn = self._draw(said, depth_closed=3)
        self.assertEqual(drawn.closed, {"/c/host/disk", "/c/host/raid",
                                        "/c/host/notes"})
        self.assertEqual(drawn.priced, drawn.closed)
        drawn = self._draw(said, depth_closed=1)
        self.assertEqual(drawn.closed, {"/c"})
        self.assertEqual(drawn.priced, {"/c"})

    def test_each_node_takes_its_fold_and_its_line_budget(self) -> None:
        said = _said(**{"/c/host": Stated(fold_ok=True, reason_cap=2)})
        drawn = self._draw(said)
        self.assertEqual(drawn.folded, {"/c/host"})
        self.assertEqual(drawn.caps["/c/host"], 2)
        self.assertEqual(drawn.caps["/c/host/disk"], DEFAULT_REASON_CAP)
        # the wall's root is nobody's node and folds nothing; a page's node does
        everywhere = Config(fold_ok=True)
        self.assertNotIn("/", self._draw(config=everywhere).folded)
        page = draw(_root(self.tree, "c/host"), _looks(nodes=said))
        self.assertIn("/c/host", page.folded)


class TheNetForABigLevelTests(TestCase):
    """Where nobody spoke, a level whose children, opened, would draw more than
    :data:`BIG_LEVEL` boxes starts as chips, as ``chips: true`` would start it: the
    net for the level nobody expected to be big (§3.4; §2, 2026-10-24). The boxes are
    counted all the way down, the deeper levels deciding first, so a child counts what
    it draws once it has decided; no status counts, so the planner prices what it
    decides, and every statement wins over it."""

    def setUp(self) -> None:
        self.tree = StatusTree()

    def _leaves(self, parent: str, count: int,
                code: StatusCode = StatusCode.OK) -> set[str]:
        paths = {f"{parent}/n{index:02d}" for index in range(count)}
        for path in sorted(paths):
            if code is StatusCode.OK:
                self.tree.upsert(path, code)
            else:
                self.tree.upsert(path, code, "down")
        return paths

    def _draw(self, nodes: dict[str, NodeMeta] | None = None,
              config: Config | None = None, *checks: Check, **how: Any):
        looks = _looks(*checks, nodes=nodes, config=config)
        return draw(_root(self.tree), looks, **how)

    def test_the_notes_four_levels(self) -> None:
        # sixty pods stand as chips, and so do thirty repositories with two workflows
        # each, ninety boxes; ten hosts of ten leaves each stand as ten chips with
        # their counts; seven repositories with their build and deploy, twenty-one
        # boxes, stand open
        pods = self._leaves("/k/pods", 60)
        repositories = {f"/g/actions/r{index:02d}" for index in range(30)}
        for repository in repositories:
            self._leaves(repository, 2)
        hosts = {f"/m/host{index}" for index in range(10)}
        for host in hosts:
            self._leaves(host, 10)
        for index in range(7):
            self._leaves(f"/s/actions/r{index}", 2)
        drawn = self._draw()
        self.assertEqual(drawn.closed, pods | repositories | hosts)
        # the tree's shape decides it, so the planner prices it as configured
        self.assertEqual(drawn.priced, drawn.closed)

    def test_a_level_is_big_past_its_boxes_not_at_them(self) -> None:
        self._leaves("/at", BIG_LEVEL)
        past = self._leaves("/past", BIG_LEVEL + 1)
        self.assertEqual(self._draw().closed, past)

    def test_the_deeper_levels_decide_first(self) -> None:
        # three hosts of forty leaves: each host's leaves are chips, so each host
        # counts its own box alone and the card's level of three stands open, where
        # counted before they decided the hosts were 123 boxes, and chips too
        leaves: set[str] = set()
        for index in range(3):
            leaves |= self._leaves(f"/m/host{index}", 40)
        self.assertEqual(self._draw().closed, leaves)

    def test_a_level_counts_everything_its_children_draw(self) -> None:
        # one child of a card holding thirty leaves is thirty-one boxes: the card's
        # level is big, and its child starts as a chip with the leaves beneath it
        self._leaves("/c/at", BIG_LEVEL)
        self.assertEqual(self._draw().closed, {"/c/at"})

    def test_a_claim_stays_open_and_counts_what_it_draws(self) -> None:
        # opened, x's level draws its 25 leaves and y with its 20, 46 boxes: chips, but
        # for y, which claims the room it takes and keeps its leaves open; so x counts
        # its own box and y's twenty-one, and beside w's ten the card's level draws 32
        # and starts as chips too
        quiet = self._leaves("/c/x", 25)
        self._leaves("/c/x/y", 20)
        self.tree.set_show_when_quiet("/c/x/y", True)
        self._leaves("/c/w", 9)
        self.assertEqual(self._draw().closed, quiet | {"/c/x", "/c/w"})

    def test_a_status_decides_nothing_and_the_budget_opens_its_way(self) -> None:
        # a failure turns no level into chips nor one out of them: thirty failing
        # leaves stand open, and of thirty-one the failure budget opens three
        self._leaves("/at", BIG_LEVEL, StatusCode.ERROR)
        failing = self._leaves("/past", BIG_LEVEL + 1, StatusCode.ERROR)
        drawn = self._draw()
        opened = set(sorted(failing)[:3])
        self.assertEqual(drawn.budget, opened)
        self.assertEqual(drawn.closed, failing - opened)
        self.assertEqual(drawn.priced, failing)
        # kept shut, the budget opens nothing, and the net's chips stay chips
        self.assertEqual(self._draw(failures_open=False).closed, failing)

    def test_every_statement_wins_over_it(self) -> None:
        pods = self._leaves("/pods", 60)
        few = self._leaves("/few", 3)
        # settings.yaml's `chips: false` for every level nobody else spoke for, and
        # nodes.yaml's for one, open what the net would close
        self.assertEqual(self._draw(config=Config(chips=False)).closed, frozenset())
        self.assertEqual(self._draw(_said(**{"/pods": Stated(chips=False)})).closed,
                         frozenset())
        # and `chips: true` closes a level the net leaves open
        self.assertEqual(self._draw(_said(**{"/few": Stated(chips=True)})).closed,
                         pods | few)

    def test_a_level_a_statement_opens_counts_what_it_opens(self) -> None:
        # a statement speaks for its own level: the one above, which nobody spoke
        # for, counts the sixty boxes it opened, and starts as chips
        self._leaves("/k/pods", 60)
        drawn = self._draw(_said(**{"/k/pods": Stated(chips=False)}))
        self.assertEqual(drawn.closed, {"/k/pods"})

    def test_neither_the_cards_nor_a_pages_cards_are_its(self) -> None:
        # the wall's root takes no key and no net: forty cards stand open, and so do a
        # page's cards, its node's children, sixty of them
        for index in range(40):
            self.tree.upsert(f"/card{index:02d}", StatusCode.OK)
        self.assertEqual(self._draw().closed, frozenset())
        self._leaves("/k/pods", 60)
        self.assertEqual(draw(_root(self.tree, "k/pods"), _looks()).closed, frozenset())

    def test_beneath_a_shared_mount_it_closes_only_what_nobody_spoke_for(self) -> None:
        # each child of a mount two checks share starts as its own check says: one
        # says its twenty leaves start open, the other says nothing of its twenty;
        # opened, the level is forty boxes, and only the second's start as chips
        said = _check(own={"chips": False}, owns=tuple(f"c{i:02d}" for i in range(20)))
        silent = _check(owns=tuple(f"d{i:02d}" for i in range(20)))
        for index in range(20):
            self.tree.upsert(f"/hosts/alpha/c{index:02d}", StatusCode.OK)
            self.tree.upsert(f"/hosts/alpha/d{index:02d}", StatusCode.OK)
        drawn = self._draw(None, None, said, silent)
        self.assertEqual(drawn.closed,
                         {f"/hosts/alpha/d{index:02d}" for index in range(20)})


class TheFailureBudgetTests(TestCase):
    """In each card the first three failures the first look hides open their way,
    errors before warnings and in the card's order (§3.3, §7.9)."""

    def setUp(self) -> None:
        self.tree = StatusTree()
        self.said = _said(**{"/c": Stated(chips=True, children=Stated(chips=True))})

    def _draw(self, **how: Any):
        return draw(_root(self.tree), _looks(nodes=self.said), **how)

    def test_three_open_with_their_paths_errors_first_in_the_cards_order(self) -> None:
        self.tree.upsert("/c/a/x", StatusCode.ERROR, "x")
        self.tree.upsert("/c/a/y", StatusCode.OK)
        self.tree.upsert("/c/b/z", StatusCode.WARN, "z")
        self.tree.upsert("/c/b/w", StatusCode.ERROR, "w")
        self.tree.upsert("/c/d", StatusCode.ERROR, "d")
        drawn = self._draw()
        # x, w and d are the errors in the card's order; z, a warning, waits
        self.assertEqual(drawn.budget, {"/c/a", "/c/a/x", "/c/b", "/c/b/w", "/c/d"})
        self.assertEqual(drawn.closed, {"/c/a/y", "/c/b/z"})
        # status decides it, so the planner prices the configured look whole
        self.assertEqual(drawn.priced, {"/c/a", "/c/a/x", "/c/a/y", "/c/b",
                                        "/c/b/z", "/c/b/w", "/c/d"})

    def test_each_card_has_a_budget_of_its_own(self) -> None:
        self.said |= _said(**{"/e": Stated(chips=True)})
        for name in ("n1", "n2", "n3", "n4"):            # the card's order, by name
            self.tree.upsert(f"/c/{name}", StatusCode.ERROR, "x")
            self.tree.upsert(f"/e/{name}", StatusCode.WARN, "x")
        drawn = self._draw()
        self.assertEqual(drawn.closed, {"/c/n4", "/e/n4"})
        self.assertEqual(drawn.budget, {"/c/n1", "/c/n2", "/c/n3",
                                        "/e/n1", "/e/n2", "/e/n3"})

    def test_kept_shut_the_budget_opens_nothing_and_the_wall_keeps_its_size(self):
        # the browser's look *Failures: stay chips*: what the budget would open stays as
        # the look drew it, and nothing else moves
        for name in ("n1", "n2", "n3", "n4"):
            self.tree.upsert(f"/c/{name}", StatusCode.ERROR, "x")
        opened = self._draw()
        shut = self._draw(failures_open=False)
        self.assertEqual(shut.budget, frozenset())
        self.assertEqual(shut.closed, opened.closed | opened.budget)
        self.assertEqual((shut.priced, shut.folded, shut.caps),
                         (opened.priced, opened.folded, opened.caps))

    def test_a_branch_that_fails_for_itself_opens_and_its_healthy_children_wait(self):
        self.tree.upsert("/c/repo", StatusCode.ERROR, "the webhook is gone")
        self.tree.upsert("/c/repo/build", StatusCode.OK)
        self.tree.upsert("/c/repo/test", StatusCode.OK)
        drawn = self._draw()
        self.assertEqual(drawn.budget, {"/c/repo"})
        self.assertEqual(drawn.closed, {"/c/repo/build", "/c/repo/test"})

    def test_a_damped_failure_is_passed_over_until_it_escalates(self) -> None:
        self.tree.upsert("/c/api", StatusCode.OK, escalate_after=2)
        self.tree.upsert("/c/api", StatusCode.ERROR, "down")
        self.assertEqual(self._draw().closed, {"/c/api"})
        self.tree.upsert("/c/api", StatusCode.ERROR, "down")
        drawn = self._draw()
        self.assertEqual((drawn.closed, drawn.budget), (frozenset(), {"/c/api"}))

    def test_a_failure_in_sight_spends_none(self) -> None:
        # nobody spoke for /f: the built-in look keeps its failure open, and the
        # budget has nothing to open
        self.tree.upsert("/f/x", StatusCode.ERROR, "x")
        self.assertEqual(self._draw().budget, frozenset())
        # nor does it take a hidden one's place: a claim keeps /c/a1 open, and the
        # three errors after it in the card's order all open
        self.tree.upsert("/c/a1", StatusCode.ERROR, "in sight", show_when_quiet=True)
        for name in ("n1", "n2", "n3"):
            self.tree.upsert(f"/c/{name}", StatusCode.ERROR, "x")
        drawn = self._draw()
        self.assertEqual(drawn.budget, {"/c/n1", "/c/n2", "/c/n3"})
        self.assertEqual(drawn.closed, frozenset())

    def test_failures_past_a_depth_open_within_their_cards_budget(self) -> None:
        self.said = {}
        self.tree.upsert("/f/host/disk", StatusCode.ERROR, "full")
        self.tree.upsert("/f/host/cpu", StatusCode.OK)
        drawn = self._draw(depth_closed=2)
        self.assertEqual(drawn.budget, {"/f/host"})
        self.assertEqual(drawn.closed, frozenset())       # the host's leaves open
        drawn = self._draw(depth_closed=1)
        self.assertEqual(drawn.budget, {"/f"})            # the card, in its place
