"""What the library's host types say of their nodes (ADR-0133): each node's description
says what is read, in a sentence; each aspect's about says what to do, in a few, and
leads into a handbook the type ships beside its module, a file an aspect, which says
how to read the value and what to do at length — and a node a run names, a volume, a
drive or a watched process, takes none of either but carries its object's details —
the about round's sixth slice, a handbook an aspect.

Each type is built from the mapping a deployment's file holds and run once by the
engine over a captured reading, so what is tested is what a deployment gets — and the
startup record, which names a text past its length and a link into a handbook that
leads nowhere, says nothing of any of it.
"""
from __future__ import annotations

import re
from pathlib import Path
from types import ModuleType
from typing import Any
from unittest import TestCase, mock

from little_sister import handbooks, self_report
from little_sister.checks import Check
from little_sister.checks.ssh import (
    HostMetricsCheck,
    MacosMemoryCheck,
    QnapMetricsCheck,
    host_metrics,
    macos_memory,
    qnap_metrics,
)
from little_sister.engine import Engine
from little_sister.nodes import ABOUT_NOTED_PAST, DESCRIPTION_NOTED_PAST
from little_sister.render import anchors_of, short_links
from little_sister.tree import StatusTree
from tests.running import SSH_RUN, finished

#: The three types and the modules that declare their texts.
TYPES: tuple[ModuleType, ...] = (host_metrics, qnap_metrics, macos_memory)

#: Every link a Markdown text writes, by its target.
_LINK = re.compile(r"\]\(([^)\s]+)\)")

#: Nothing is read from a configuration's directory: each type pipes the script it
#: ships.
_NOWHERE = Path("/nonexistent")

HOST_READING = """\
os=Linux
hostname=alpha
ncpu=4
uptime_seconds=90061
disk_count=2
disk1_path=/
disk1_total_kb=1000000
disk1_used_kb=520000
disk1_avail_kb=480000
disk1_pct=52
disk2_path=/srv/data
disk2_total_kb=4000000
disk2_used_kb=3800000
disk2_avail_kb=200000
disk2_pct=95
mem_total_kb=16000000
mem_used_kb=8000000
mem_pct=50
cpu_pct=7
load1=0.40
"""

NAS_READING = """\
model=TS-453D
sys_temp_c=41
cpu_temp_c=55
drive_count=2
drive1_bay=1
drive1_temp_c=38
drive1_smart=GOOD
drive2_bay=3
drive2_temp_c=40
drive2_smart=Warning
"""

MAC_READING = """\
os=Darwin
pressure_level=1
free_pct=42
swap_total_mb=2048
swap_used_mb=512
mem_total_kb=8388608
compressor_kb=1048576
compressor_pct=12
proc_count=1
proc1_pattern=Mail.app
proc1_count=2
proc1_rss_kb=204800
proc1_elapsed_seconds=3600
"""


def _shipped(module: ModuleType, name: str) -> str:
    """The handbook a type ships for an aspect, as its file holds it."""
    return (Path(str(module.__file__)).parent / module.HANDBOOK[name]).read_text(
        encoding="utf-8")


def _run(check: Check, reading: str) -> StatusTree:
    """One engine tick of ``check`` over a captured reading."""
    tree = StatusTree()
    with mock.patch(SSH_RUN, return_value=finished(reading, 0, "")):
        Engine([check], tree).run_once()
    return tree


def _host(**said: Any) -> HostMetricsCheck:
    return HostMetricsCheck.from_config(
        {"type": "host-metrics", "path": "/hosts/alpha", "host": "alpha",
         "disk_path": "all", **said}, _NOWHERE)


def _nas(**said: Any) -> QnapMetricsCheck:
    return QnapMetricsCheck.from_config(
        {"type": "qnap-metrics", "path": "/hosts/nas", "host": "nas", **said}, _NOWHERE)


def _mac(**said: Any) -> MacosMemoryCheck:
    return MacosMemoryCheck.from_config(
        {"type": "macos-memory", "path": "/hosts/mac", "host": "mac",
         "processes": [{"name": "mail", "pattern": "Mail.app"}], **said}, _NOWHERE)


class _Recorded(TestCase):
    """Each case starts with nothing on the startup record, and nothing named."""

    def setUp(self) -> None:
        handbooks.forget()
        self_report.startup.forget()
        self.addCleanup(handbooks.forget)
        self.addCleanup(self_report.startup.forget)


class WhatEachTypeDeclaresTests(TestCase):
    """The declarations: an about and a handbook an aspect, a description a node."""

    def test_each_aspect_has_an_about_and_a_handbook_its_type_ships(self):
        for module in TYPES:
            for name, about in module.ABOUT.items():
                with self.subTest(module=module.__name__, aspect=name):
                    entry = module.SUBNODE_DEFAULTS[name]
                    self.assertEqual((entry["about"], entry["handbook"]),
                                     (about, module.HANDBOOK[name]))
                    self.assertTrue(_shipped(module, name).startswith("# "))

    def test_every_file_in_the_handbooks_directory_is_one_a_type_names(self):
        # a file no type names is a handbook no page shows
        directory = Path(str(host_metrics.__file__)).parent
        named = {directory / module.HANDBOOK[name]
                 for module in TYPES for name in module.HANDBOOK}
        self.assertEqual(set((directory / "handbook").rglob("*.md")), named)

    def test_an_about_says_what_to_do_in_short_and_leads_into_its_handbook(self):
        for module in TYPES:
            for name, about in module.ABOUT.items():
                with self.subTest(module=module.__name__, aspect=name):
                    self.assertLessEqual(len(about), ABOUT_NOTED_PAST)
                    # what to do is said by the status it is done on
                    self.assertRegex(about, r"\{(warn|error)\}")
                    sections = short_links(about)
                    self.assertTrue(sections)
                    self.assertLessEqual(
                        {section.lstrip("#") for section in sections},
                        anchors_of(_shipped(module, name)))

    def test_a_handbook_links_its_own_sections_and_nothing_relative(self):
        # a handbook is read at /handbook/<path>, where a relative link leads nowhere;
        # a section of its own page it links as GitHub anchors it
        for module in TYPES:
            for name in module.HANDBOOK:
                text = _shipped(module, name)
                anchors = anchors_of(text)
                for target in _LINK.findall(text):
                    with self.subTest(module=module.__name__, aspect=name,
                                      target=target):
                        self.assertTrue(target.startswith("#"))
                        self.assertIn(target[1:], anchors)

    def test_a_description_is_a_sentence_within_its_length(self):
        for module in TYPES:
            for constant, text in vars(module).items():
                if not constant.endswith("_DESCRIPTION"):
                    continue
                said = text.format(bay="12") if "{bay}" in text else text
                with self.subTest(module=module.__name__, constant=constant):
                    self.assertLessEqual(len(said), DESCRIPTION_NOTED_PAST)
                    self.assertTrue(said[:1].isupper() and said.endswith("."))


class WhatADeploymentGetsTests(_Recorded):
    """One run of each type: the texts where they belong, the details of each object,
    and nothing on the startup record."""

    def _labels(self, tree: StatusTree, path: str) -> tuple[str, str]:
        return tree.about(path), tree.handbook(path)

    def test_a_hosts_aspects_carry_their_texts_and_its_volumes_their_mounts(self):
        tree = _run(_host(), HOST_READING)
        for name in host_metrics.ABOUT:
            with self.subTest(aspect=name):
                self.assertEqual(self._labels(tree, f"/hosts/alpha/{name}"),
                                 (host_metrics.ABOUT[name],
                                  _shipped(host_metrics, name)))
        for volume, mount in (("root", "`/`"), ("data", "`/srv/data`")):
            path = f"/hosts/alpha/disk/{volume}"
            with self.subTest(volume=volume):
                self.assertEqual(self._labels(tree, path), ("", ""))
                self.assertEqual(tree.snapshot(path).description,
                                 host_metrics.VOLUME_DESCRIPTION)
                self.assertEqual([(row.key, row.text) for row in tree.details(path)],
                                 [("mount", mount)])
        self.assertEqual(tree.snapshot("/hosts/alpha/disk").description,
                         host_metrics.VOLUMES_DESCRIPTION)
        self.assertEqual(self_report.startup.lines(), ())

    def test_a_nas_branches_carry_their_texts_and_its_drives_their_bays(self):
        tree = _run(_nas(), NAS_READING)
        for name in qnap_metrics.ABOUT:
            with self.subTest(aspect=name):
                self.assertEqual(self._labels(tree, f"/hosts/nas/{name}"),
                                 (qnap_metrics.ABOUT[name],
                                  _shipped(qnap_metrics, name)))
        for path, description in (
                ("/hosts/nas/temperature/drive3",
                 "The temperature of the drive in bay 3, in °C, as `getsysinfo` reads "
                 "it."),
                ("/hosts/nas/smart/drive3",
                 "The SMART verdict of the drive in bay 3, as `getsysinfo` words it.")):
            with self.subTest(path=path):
                self.assertEqual(self._labels(tree, path), ("", ""))
                self.assertEqual(tree.snapshot(path).description, description)
                self.assertEqual([(row.key, row.text) for row in tree.details(path)],
                                 [("bay", "3")])
        # a sensor the NAS has is no object of its own, and has no details
        self.assertEqual(tree.details("/hosts/nas/temperature/system"), ())
        self.assertEqual(self_report.startup.lines(), ())

    def test_a_macs_aspects_carry_their_texts_and_a_process_its_pattern(self):
        tree = _run(_mac(), MAC_READING)
        for name in macos_memory.ABOUT:
            with self.subTest(aspect=name):
                self.assertEqual(self._labels(tree, f"/hosts/mac/{name}"),
                                 (macos_memory.ABOUT[name],
                                  _shipped(macos_memory, name)))
        path = "/hosts/mac/processes/mail"
        self.assertEqual(self._labels(tree, path), ("", ""))
        self.assertEqual(tree.snapshot(path).description,
                         macos_memory.PROCESS_DESCRIPTION)
        self.assertEqual([(row.key, row.text) for row in tree.details(path)],
                         [("pattern", "`Mail.app`")])
        self.assertEqual(self_report.startup.lines(), ())

    def test_a_deployment_places_the_types_handbook_beneath_its_own(self):
        # `{default}` in a deployment's handbook places the type's there (ADR-0133
        # decision 3): a team's sign-in before the package's reference
        tree = _run(_host(subnodes={"disk": {"handbook": "## Sign in\n\nAs yourself."
                                                         "\n\n{default}"}}),
                    HOST_READING)
        self.assertEqual(tree.handbook("/hosts/alpha/disk"),
                         "## Sign in\n\nAs yourself.\n\n"
                         + _shipped(host_metrics, "disk"))
        self.assertEqual(self_report.startup.lines(), ())
