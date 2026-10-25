"""How the library's host types propose their levels first look (ADR-0128): a host's
leaves start as chips, and so do a disk's filesystems, a NAS's drives and sensors and
a Mac's memory signals and watched processes — backlog #91's fourth stage, its third
slice (the note's §2).

Each type is built from the mapping a deployment's file holds, through the reader
every type's construction runs, so what is tested is what a deployment gets: what the
type proposes, a file and ``nodes.yaml`` taking it back, and a host node two of the
types share — whose own look neither speaks for, while each of its leaves starts as
the check that writes it proposes (ADR-0128 decision 5, as amended the same day) — then
what the server draws of it, the levels nobody speaks for open as the built-in look has
them.
"""
from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Any, ClassVar
from unittest import TestCase

from little_sister.checks import Check
from little_sister.checks.metadata import Stated
from little_sister.checks.ssh import (
    HostMetricsCheck,
    MacosMemoryCheck,
    QnapMetricsCheck,
    host_metrics,
    macos_memory,
    qnap_metrics,
)
from little_sister.config import Config
from little_sister.first_look import FirstLooks, draw
from little_sister.nodes import NodeMeta
from little_sister.status import StatusCode
from little_sister.tree import StatusSnapshot, StatusTree

#: Nothing is read from a configuration's directory at construction: each type pipes
#: the script it ships.
_NOWHERE = Path("/nonexistent")


def _host(path: str = "/hosts/alpha", **said: Any) -> HostMetricsCheck:
    return HostMetricsCheck.from_config(
        {"type": "host-metrics", "path": path, "host": "alpha", **said}, _NOWHERE)


def _qnap(path: str = "/hosts/nas/qnap", **said: Any) -> QnapMetricsCheck:
    return QnapMetricsCheck.from_config(
        {"type": "qnap-metrics", "path": path, "host": "nas", **said}, _NOWHERE)


def _memory(path: str = "/hosts/mac", **said: Any) -> MacosMemoryCheck:
    return MacosMemoryCheck.from_config(
        {"type": "macos-memory", "path": path, "host": "mac",
         "processes": [{"name": "syncer", "pattern": "syncer"},
                       {"name": "mail", "pattern": "Mail.app"}], **said}, _NOWHERE)


def _looks(*checks: Check, nodes: Mapping[str, NodeMeta] | None = None) -> FirstLooks:
    return FirstLooks(checks, nodes or {}, Config(), named_by_run=lambda _path: False)


class WhatEachTypeProposesTests(TestCase):
    """The declarations themselves: the levels each type knows are big, and nothing
    else — no fold, no line budget, no claim."""

    def test_host_metrics_proposes_a_hosts_leaves_and_a_disks_filesystems(self):
        statements = _host().type_statements
        self.assertEqual(statements.own, Stated(chips=True))
        self.assertEqual(statements.by_name, {"disk": Stated(chips=True)})

    def test_qnap_metrics_proposes_its_drives_and_sensors(self):
        statements = _qnap().type_statements
        self.assertEqual(statements.own, Stated())
        self.assertEqual(statements.by_name, {"smart": Stated(chips=True),
                                              "temperature": Stated(chips=True)})

    def test_macos_memory_proposes_its_leaves_and_its_watched_processes(self):
        statements = _memory().type_statements
        self.assertEqual(statements.own, Stated(chips=True))
        self.assertEqual(statements.by_name, {"processes": Stated(chips=True)})

    def test_the_labels_beside_them_are_each_aspects_about_and_handbook(self):
        # an entry carries its look beside its labels, its about and its handbook
        # (ADR-0133) — what they say is test_host_types_texts.py's
        for check, module in ((_host(), host_metrics), (_qnap(), qnap_metrics),
                              (_memory(), macos_memory)):
            with self.subTest(type=module.__name__):
                labels = check.subnode_labels
                self.assertEqual({name: set(said) for name, said in labels.items()},
                                 {name: {"about", "handbook"} for name in module.ABOUT})


class WhereEachTypeSpeaksTests(TestCase):
    """Each proposal reaches its level, and a deployment takes it back."""

    def test_a_hosts_leaves_and_its_disks_filesystems_start_as_chips(self):
        looks = _looks(_host(disk_path="all"))
        self.assertIs(looks.look("/hosts/alpha").chips, True)
        self.assertIs(looks.look("/hosts/alpha/disk").chips, True)

    def test_a_nas_drives_and_sensors_but_not_its_own_two_branches(self):
        looks = _looks(_qnap())
        self.assertIsNone(looks.look("/hosts/nas/qnap").chips)
        self.assertIs(looks.look("/hosts/nas/qnap/smart").chips, True)
        self.assertIs(looks.look("/hosts/nas/qnap/temperature").chips, True)

    def test_a_macs_leaves_and_its_watched_processes(self):
        looks = _looks(_memory())
        self.assertIs(looks.look("/hosts/mac").chips, True)
        self.assertIs(looks.look("/hosts/mac/processes").chips, True)

    def test_a_deployments_file_takes_each_back(self):
        looks = _looks(
            _host(chips=False, disk_path="all", subnodes={"disk": {"chips": False}}),
            _qnap(subnodes={"smart": {"chips": False}}),
            _memory(subnodes={"processes": {"chips": False}}))
        self.assertIs(looks.look("/hosts/alpha").chips, False)
        self.assertIs(looks.look("/hosts/alpha/disk").chips, False)
        self.assertIs(looks.look("/hosts/nas/qnap/smart").chips, False)
        self.assertIs(looks.look("/hosts/nas/qnap/temperature").chips, True)
        self.assertIs(looks.look("/hosts/mac/processes").chips, False)

    def test_nodes_yaml_takes_it_back_by_path(self):
        nodes = {"/hosts/alpha": NodeMeta(look=Stated(chips=False))}
        self.assertIs(_looks(_host(), nodes=nodes).look("/hosts/alpha").chips, False)


class AHostNodeTwoTypesShareTests(TestCase):
    """Beside ``host-metrics`` on one host node, as the configuration's README shows
    them: neither type speaks for that node's own look, each of its leaves starts as
    the check that writes it proposes, and each check speaks for what lies in its own
    subtree beneath it (ADR-0128 decision 5, as amended)."""

    def test_its_own_look_is_neithers_and_each_leaf_starts_as_its_check_says(self):
        host, memory = _host("/hosts/mac"), _memory("/hosts/mac")
        looks = _looks(host, memory)
        self.assertIsNone(looks.look("/hosts/mac").chips)
        self.assertIs(looks.writer("/hosts/mac/cpu"), host)
        self.assertIs(looks.writer("/hosts/mac/processes/syncer"), memory)
        for leaf in ("cpu", "disk", "ssh", "swap", "pressure", "processes"):
            self.assertIs(looks.children_chips("/hosts/mac", f"/hosts/mac/{leaf}"),
                          True, leaf)
        self.assertIs(looks.look("/hosts/mac/processes").chips, True)

    def test_a_file_takes_back_its_own_leaves_only(self):
        looks = _looks(_host("/hosts/mac", chips=False), _memory("/hosts/mac"))
        self.assertIs(looks.children_chips("/hosts/mac", "/hosts/mac/cpu"), False)
        self.assertIs(looks.children_chips("/hosts/mac", "/hosts/mac/swap"), True)

    def test_the_same_with_a_nas_whose_two_branches_stand_open(self):
        looks = _looks(_host("/hosts/nas", disk_path="all"), _qnap("/hosts/nas"))
        self.assertIsNone(looks.look("/hosts/nas").chips)
        self.assertIs(looks.children_chips("/hosts/nas", "/hosts/nas/cpu"), True)
        self.assertIsNone(looks.children_chips("/hosts/nas", "/hosts/nas/smart"))
        self.assertIs(looks.look("/hosts/nas/disk").chips, True)
        self.assertIs(looks.look("/hosts/nas/smart").chips, True)

    def test_nodes_yaml_speaks_for_it_and_for_every_leaf(self):
        nodes = {"/hosts/mac": NodeMeta(look=Stated(chips=False))}
        looks = _looks(_host("/hosts/mac"), _memory("/hosts/mac"), nodes=nodes)
        self.assertIs(looks.look("/hosts/mac").chips, False)
        self.assertIs(looks.children_chips("/hosts/mac", "/hosts/mac/cpu"), False)
        self.assertIs(looks.children_chips("/hosts/mac", "/hosts/mac/swap"), False)


class WhatTheServerDrawsTests(TestCase):
    """A card of two hosts: one ``host-metrics`` reads alone, its disk fanned out to
    two filesystems; on the other, a Mac, ``macos-memory`` shares its node."""

    def setUp(self) -> None:
        self.tree = StatusTree()
        for leaf in ("ssh", "cpu", "memory", "load"):
            self.tree.upsert(f"/hosts/alpha/{leaf}", StatusCode.OK)
            self.tree.upsert(f"/hosts/mac/{leaf}", StatusCode.OK)
        for volume in ("root", "data"):
            self.tree.upsert(f"/hosts/alpha/disk/{volume}", StatusCode.OK)
        self.tree.upsert("/hosts/mac/disk", StatusCode.OK)
        self.tree.upsert("/hosts/mac/swap", StatusCode.OK)
        self.tree.upsert("/hosts/mac/processes/syncer", StatusCode.OK)
        self.looks = _looks(_host(disk_path="all"), _host("/hosts/mac"),
                            _memory("/hosts/mac"))

    def _drawn(self):
        root = self.tree.snapshot("")
        assert isinstance(root, StatusSnapshot)
        return draw(root, self.looks)

    _ALPHA: ClassVar[frozenset[str]] = frozenset({
        "/hosts/alpha/ssh", "/hosts/alpha/cpu", "/hosts/alpha/memory",
        "/hosts/alpha/load", "/hosts/alpha/disk", "/hosts/alpha/disk/root",
        "/hosts/alpha/disk/data"})
    #: The Mac's: host-metrics' leaves and macos-memory's, its processes a chip too,
    #: and the process beneath it.
    _MAC: ClassVar[frozenset[str]] = frozenset({
        "/hosts/mac/ssh", "/hosts/mac/cpu", "/hosts/mac/memory", "/hosts/mac/load",
        "/hosts/mac/disk", "/hosts/mac/swap", "/hosts/mac/processes",
        "/hosts/mac/processes/syncer"})

    def test_what_the_types_propose_is_drawn_and_priced(self):
        drawn = self._drawn()
        # alpha's leaves, its disk and the disk's filesystems are chips; on the Mac
        # each leaf is a chip by what its own check proposes, its processes too; the
        # card's own level, its hosts, nobody speaks for, and it stands open — and
        # the planner prices all of it
        self.assertEqual(drawn.closed, self._ALPHA | self._MAC)
        self.assertEqual(drawn.priced, drawn.closed)

    def test_a_branch_whose_check_proposes_nothing_for_the_node_is_nobodys(self):
        # qnap-metrics beside host-metrics on a NAS's node proposes nothing for that
        # node's children: its two branches stand open beside host-metrics' chips,
        # their drives chips by its own proposal
        self.tree.upsert("/hosts/nas/cpu", StatusCode.OK)
        self.tree.upsert("/hosts/nas/smart/drive1", StatusCode.OK)
        self.looks = _looks(_host("/hosts/nas"), _qnap("/hosts/nas"))
        drawn = self._drawn()
        self.assertIn("/hosts/nas/cpu", drawn.closed)
        self.assertNotIn("/hosts/nas/smart", drawn.closed)
        self.assertIn("/hosts/nas/smart/drive1", drawn.closed)

    def test_a_failing_leaf_opens_within_the_cards_budget(self):
        self.tree.upsert("/hosts/alpha/disk/data", StatusCode.ERROR, "full")
        drawn = self._drawn()
        self.assertEqual(drawn.budget, {"/hosts/alpha/disk", "/hosts/alpha/disk/data"})
        self.assertNotIn("/hosts/alpha/disk/data", drawn.closed)
        self.assertIn("/hosts/alpha/disk/root", drawn.closed)
