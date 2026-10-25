"""What the wall costs the server on the anonymized tree — today's numbers the baseline.

Backlog #91 grows the wall into a tree, and before it grows the note's §7.1 step 4
takes today's cost on the deployment's own tree of §3.9, its names replaced
(``tests/anonymized_tree.py``): the fragment the ten-second refresh fetches, in bytes
and elements, for a viewer and for an admin, its weight on the wire where the browser
takes gzip, the server's time to render it and the memory the render peaks at. The
numbers here are the baseline each stage states its growth against — stage 3's above
all, where every node gains its box in the fragment and the hover card's data rides
with it (§3.1) — and what the browser pays for the same wall is
``test_wall_cost_browser.py``'s.

The fixture itself is held to what it stands for: the prototype's tree byte for byte,
the shape the note describes, lines of the recorded length, the four shapes made
worse as §3.9 made them, the deployed wall as the deployment that runs mounts one
team's checks, and not a word of the deployment's own (R13). So is the hosts tree
(``tests/hosts_tree.py``), a second deployment's wall of hosts the library's own types
write, whose fragment is held beside them.
"""
from __future__ import annotations

import json
import re
import statistics
import time
import tracemalloc
from dataclasses import dataclass, replace
from html.parser import HTMLParser
from pathlib import Path
from unittest import SkipTest, TestCase

from little_sister import app as app_module
from little_sister.checks.ssh import host_metrics, qnap_metrics
from little_sister.first_look import FirstLooks
from little_sister.status import StatusCode
from little_sister.tree import StatusSnapshot, StatusTree
from tests import anonymized_tree, hosts_tree
from tests.render_ui_fixtures import FIXTURES_BY_NAME, render_page

_REPO_ROOT = Path(__file__).resolve().parent.parent
_PROTOTYPE_SHAPES = (_REPO_ROOT / "docs" / "backlog"
                     / "backlog-0091-the-interactive-wall-assets" / "prototype"
                     / "shapes.json")
_PRIVATE_STRINGS = _REPO_ROOT / "release" / "private_strings.txt"


@dataclass(frozen=True)
class Cost:
    """A response's size: its bytes, and its elements as start tags."""

    bytes: int
    elements: int


#: The fragment of the wall — ``/status?fragment=1`` — for a viewer and for an
#: admin, whose fragment carries the pin's editors, on the recorded tree and on each
#: tree made worse; and two pages the shapes made worse are paid on: the
#: *informational* band's own page with 300 findings, and the workflow runs' page
#: with 100 repositories.
#:
#: Each stage states its growth here. Before stage 2 the recorded wall's fragment was
#: 127,621 bytes for a viewer and 135,036 for an admin, the outage 173,680 and
#: 181,095, every leaf failing 275,239 and 282,654, 100 repositories 298,377 and
#: 305,792, the two pages 258,160 and 259,476 — the elements as below. Stage 2, the
#: tab's map, named the folds' controls for the keyboard's focus, `data-control` on
#: every chevron slot and every *+N more*: 1.2 to 2.0 % more bytes, no element more.
#: Before stage 3 the fragments were 129,446 and 136,861 bytes (1,552 and 1,696
#: elements) on the recorded wall, 176,787 and 184,202 (2,210 and 2,354) in the
#: outage, 280,783 and 288,198 (3,596 and 3,740) in the blackout, 301,966 and
#: 309,381 (3,349 and 3,493) wide, and the workflow runs' page 261,681 (2,275).
#: **Stage 3's first slice, the tree** (ADR-0127 decision 1), draws both faces of
#: every node: a closed leaf's chip and, hidden until found so that a click opens
#: it without a request and a find reaches it, its whole box — its head with the
#: cue, the title, the actions slot, the state and the head's icons, and its lines.
#: The recorded wall, 179 of whose 264 nodes are closed, grew 4.4× in bytes and 5.0×
#: in elements — some 1.3 KB and 25 elements per closed leaf, the lines beyond
#: that — the outage 3.1× and 3.3×, the blackout, whose leaves were open already,
#: 1.8× and 1.9×, and the wide wall 5.7× and 6.7×; the cues' and the icons' shapes
#: are drawn once per page as sprites, which took a third off. gzip takes the
#: recorded fragment to 26 KB and the wide one to 49 KB (backlog #91 §7.1 step 10).
#: The findings page is a leaf's and is unchanged. Before the second slice the
#: fragments were 573,607 and 581,022 bytes (7,692 and 7,836 elements) on the
#: recorded wall, 544,499 and 551,914 (7,326 and 7,470) in the outage, 504,181 and
#: 511,596 (6,793 and 6,937) in the blackout, 1,706,763 and 1,714,178 (22,334 and
#: 22,478) wide, and the workflow runs' page 1,349,193 (16,725).
#: **Stage 3's second slice, the head's row** (decision 3), puts every head's
#: controls in one toolbar named for the node, draws *⌄ all N* after a block whose
#: lines are more than the budget, and takes the chevron slot out of every head and
#: the pin's editor out of every card: a viewer's fragment grew 2.7 % in bytes and
#: 1 % in elements. An admin's grew 14 to 15 %: ‖ stands on every open head of a
#: node with no pin of its own, a box's as well as a card's — some 90 bytes and one
#: element a head, 790 heads on the recorded wall — where three cards' editors
#: stood, which gzip takes to 2.8 KB more than a viewer's on the wire. Then, on
#: 2026-10-16, **the caret left every head**, the row saying itself
#: under the pointer that a press opens or closes it: 54 bytes and one element a
#: node, open or closed, 2.1 to 2.8 % of the bytes and 3.1 to 3.9 % of the
#: elements, and 0.3 to 0.6 % on the wire. Before it the fragments were 589,068
#: and 660,269 bytes (7,775 and 8,567 elements) on the recorded wall, 559,960 and
#: 631,161 (7,409 and 8,201) in the outage, 517,797 and 588,998 (6,847 and 7,639)
#: in the blackout, 1,751,569 and 1,970,823 (22,497 and 24,840) wide, and the
#: workflow runs' page 1,371,527 (16,726). And the same day **a name
#: breaks where its words meet**: a `<wbr>` after each `_`, `.` and `-` of a name
#: in a card's or a box's head — 215 on the recorded wall, 829 on the wide one, a
#: chip's name none — 0.2 % more bytes and 2.6 to 4.3 % more elements, 0.1 to 0.9 %
#: on the wire. Before it the fragments were 574,812 and 646,013 bytes (7,511 and
#: 8,303 elements) on the recorded wall, 545,704 and 616,905 (7,145 and 7,937) in
#: the outage, 503,541 and 574,742 (6,583 and 7,375) in the blackout, 1,709,395 and
#: 1,928,649 (21,716 and 24,059) wide, and the workflow runs' page 1,339,127
#: (16,126). **Stage 3's third slice, the node's page** (backlog #91 §3.5), frames
#: a page's node, a leaf's as a branch's, and leaves the wall's fragments as they
#: were. The workflow runs' page, a branch's, grew 944 bytes and 13 elements: its
#: frame and its head, drawn now for every reader, as a box's row with its toolbar
#: and icons. The findings page, a leaf's, grew 6,946 bytes and 40 elements: the
#: cues' and the icons' shapes its frame's head refers to, 2.1 KB once, and
#: `data-healthy` on the healthy ones of its 300 lines, 3.9 KB, which its funnel
#: folds. Before it they were 1,342,627 (16,826) and 258,221 (2,296).
#: **Stage 3's fourth slice, its first part, the looks and the hover card**
#: (ADR-0019, ADR-0029), carries the card's map in every fragment rather than once
#: with the page, so a node a run names after the load has its card: each `about`'s
#: first block and the count of the blocks after it, one script element, 2,450 bytes
#: on every wall here — 0.1 to 0.5 % of the bytes, 1.2 to 3.0 % on the wire. The
#: workflow runs' page grew 71 bytes and an element, its own map, and the findings
#: page 1,389 bytes and 17 elements, the settings menu's two groups of looks with
#: them, which a page draws and a fragment does not. Before it the fragments were
#: 575,887 and 647,088 bytes (7,726 and 8,518 elements) on the recorded wall,
#: 546,779 and 617,980 (7,360 and 8,152) in the outage, 504,616 and 575,817 (6,798
#: and 7,590) in the blackout, 1,713,540 and 1,932,794 (22,545 and 24,888) wide, the
#: workflow runs' page 1,343,571 (16,839) and the findings page 265,167 (2,336).
#: **Its second part, the chip runs** (ADR-0127 decision 12), lines a run up in its
#: level's columns: each level carries its width's estimate and its branches'
#: largest count of leaves, some 35 bytes a level, and a chip's name breaks where its
#: words meet, as a head's does, a `<wbr>` after each `_`, `.` and `-` — 215 on the
#: recorded wall, 829 on the wide one. The walls' fragments grew 0.6 % in bytes and
#: 2.8 to 3.7 % in elements, the wire's 0.0 to 0.4 %; the workflow runs' page 6,400
#: bytes and 500 elements; the findings page 654 bytes and 8 elements, the settings
#: menu's group of the chips. Before it the fragments were 578,337 and 649,538 bytes
#: (7,727 and 8,519 elements) on the recorded wall, 549,229 and 620,430 (7,361 and
#: 8,153) in the outage, 507,066 and 578,267 (6,799 and 7,591) in the blackout,
#: 1,715,990 and 1,935,244 (22,546 and 24,889) wide, the workflow runs' page
#: 1,343,642 (16,840) and the findings page 266,556 (2,353).
#: **The deployed wall** (backlog #91's note, §2, 2026-10-17), alpha's five checks at
#: the root as the deployment that runs mounts them, is about half the recorded one:
#: 287,068 bytes and 3,949 elements for a viewer, 321,267 and 4,345 for an admin.
#: **The hosts wall** (the note's §7.5, 2026-10-21), the second deployment's, nine
#: hosts of five leaves each and a card of the family's checks, first read at 230,005
#: bytes and 2,837 elements for a viewer and 255,260 and 3,134 for an admin, 11,818 and
#: 12,897 on the wire. The same day its hover card's map came to carry what the
#: packages and the library say of their own nodes, and each filesystem the disk's
#: *about*, as on the wall it was read from — 8,200 bytes, 1.5 KB on the wire — and the
#: library's host types came to propose how their levels first look (the third slice):
#: 18 bytes more and an element fewer. The same day each leaf of a host
#: node two of the types share starts as its own check proposes, and the Mac's watched
#: processes are a chip where their branch stood open: 494 bytes more and an element
#: fewer, 131 and 130 more on the wire. **Every other level of box steps its fill**
#: (the same day, ADR-0028): ``is-stepped`` on the box of every second
#: level, 11 bytes each and no element — 4,399 bytes more on the recorded walls, 9,279
#: on the wide one, 10,500 on the workflow runs' page, 1,639 on the deployed wall and
#: 693 on the hosts wall, 34 to 310 more on the wire. Then the mark moved from
#: the box to its node, so that a chip steps with its level too, and no byte moved:
#: 106 fewer to 11 more on the wire. Then **an open head's buttons stand where
#: the look ``head_buttons`` puts them** (ADR-0127 decision 3), the state outside
#: them: drawn in the look's order, the markup lost some of its whitespace — 3,448
#: bytes on the recorded walls, 10,169 on the wide one, 8,609 on the workflow runs'
#: page, 1,756 on the deployed wall and 1,303 on the hosts wall, no element — and
#: gzip, whose runs the new order breaks, carries 17 to 1,563 bytes more. The
#: findings page grew 986 bytes and 11 elements, the settings menu's group of the
#: head's buttons. Before it the fragments were 586,430 and 657,631 bytes on the
#: recorded wall, 557,322 and 628,523 in the outage, 515,159 and 586,360 in the
#: blackout, 1,735,155 and 1,954,409 wide, 288,707 and 322,906 deployed and 239,410
#: and 264,665 on the hosts wall, the workflow runs' page 1,360,542 and the findings
#: page 267,262 (2,361), the elements as below. On 2026-10-22 **a state
#: wider than its line breaks between its parts** (ADR-0127 decision 3): a card's cue
#: and word are one part, a span of their own, 33 bytes and an element a card — 66
#: bytes on the recorded walls, the wide one and the hosts wall, 165 on the deployed
#: wall, 3,300 and 100 elements on the workflow runs' page — and 6 to 14 bytes more on
#: the wire, a template's small change inside the tolerance, so the numbers below are
#: before it. The same day **the head's own icons stand first in its
#: toolbar**, the node's actions after them, and a fourth look joins
#: ``head_buttons``: no byte and no element of a fragment moved, gzip carries 19 bytes
#: fewer to 870 more of the same markup in its new order, and the findings page grew
#: 285 bytes and 3 elements, the settings menu's fourth place for the head's buttons.
#: On 2026-10-23 **the library's host types say what they do as ADR-0133
#: divides it**, a handbook an aspect: an aspect's *about* draws its signs and a link
#: into its handbook, and the map carries the handbook's address beside it; a
#: filesystem, a sensor, a drive and a watched process, which have no *about*, say
#: their description.
#: All of it rides in the hover card's map: the hosts wall's fragments grew 22,910
#: bytes and no element, 1,189 and 1,209 bytes on the wire — a sign is some 200 bytes
#: of markup as the map escapes it. Before it they were 238,173 and 263,428 bytes,
#: 13,689 and 14,733 on the wire, a card's cue and word one part among them: the hosts
#: wall's numbers below are after both.
#: At **the interactive wall's flip** (backlog #91's note, §7.5, 2026-10-25) a level
#: nobody speaks for starts open, and the trees are drawn with what the family's
#: packages propose, stated by path (``tests/family_looks.py``), as their deployments
#: draw them. Every fragment moved within the tolerance, 93 to 4,320 bytes more, and
#: the findings page grew 8,461 bytes and 17 elements, its 300 findings drawn folded by
#: wiz's ``fold_ok``: it read 268,248 (2,372) before.
#: **Seen** (ADR-0142, 2026-10-25) puts the ringed check after ‖ on every open head
#: where something fails at or beneath its node, for whoever may mark it seen: a link
#: to the node's page, as ‖ is, carrying the digest of the parts it would mark and
#: how many — some 320 bytes and three elements a head on these trees, whose paths
#: are long. An admin's fragment grew 1.0 % on the recorded wall, 5.3 % in the
#: outage, 14.3 % in the blackout, whose 264 failing heads carry one each, 0.5 %
#: wide, 0.9 % deployed and 0.4 % on the hosts wall, and 1.0 to 3.0 % on the wire;
#: a viewer's did not move, and the findings page grew 326 bytes and 3 elements, the
#: ringed check's shape in the page's sprite. Before it an admin's fragments were
#: 655,389 bytes (8,731 elements) on the recorded wall, 627,769 (8,386) in the
#: outage, 587,555 (7,866) in the blackout, 1,948,056 (25,717) wide, 321,617
#: (4,348) deployed and 286,431 (3,129) on the hosts wall.
BASELINE: dict[tuple[str, str, str], Cost] = {
    ("recorded", "viewer", "/status?fragment=1"): Cost(582_982, 7_942),
    ("recorded", "admin", "/status?fragment=1"): Cost(662_019, 8_800),
    ("outage", "viewer", "/status?fragment=1"): Cost(553_874, 7_576),
    ("outage", "admin", "/status?fragment=1"): Cost(661_172, 8_698),
    ("blackout", "viewer", "/status?fragment=1"): Cost(511_711, 7_014),
    ("blackout", "admin", "/status?fragment=1"): Cost(671_368, 8_658),
    ("wide", "viewer", "/status?fragment=1"): Cost(1_724_986, 23_375),
    ("wide", "admin", "/status?fragment=1"): Cost(1_957_246, 25_810),
    ("findings", "viewer", "/status/alpha/wiz/informational"): Cost(276_709, 2_389),
    ("wide", "viewer", "/status/alpha/github/actions?fragment=1"):
        Cost(1_351_933, 17_340),
    ("deployed", "viewer", "/status?fragment=1"): Cost(286_951, 3_949),
    ("deployed", "admin", "/status?fragment=1"): Cost(324_397, 4_378),
    ("hosts", "viewer", "/status?fragment=1"): Cost(261_083, 2_837),
    ("hosts", "admin", "/status?fragment=1"): Cost(287_553, 3_141),
}
#: What the fragments weigh **on the wire**, gzipped where the request takes gzip,
#: which every browser's does (`app._compressed_where_asked`, since
#: 2026-10-16): the recorded wall's, the deployed one's and the wide one's, for a
#: viewer and for an admin, a twentieth to a thirty-fifth of the bytes rendered. The
#: bytes above are what the browser parses; these are what the network carries every
#: ten seconds to every open tab. Before the head's row the viewer's weighed 25,576
#: and 48,583, and
#: before the hover card's map rode in the fragment 26,986 and 51,580, an admin's
#: 29,794 and 58,318, before the chip runs 27,786 and 52,462, 30,551 and 59,044,
#: before every other level of box stepped its fill 27,908 and 52,484, 30,685 and
#: 59,095, and before the head's buttons stood where a look puts them 28,063 and
#: 52,683, 30,870 and 59,312. Before the ringed check an admin's weighed 31,483 on
#: the recorded wall, 61,926 wide, 15,846 deployed and 15,990 on the hosts wall.
WIRE: dict[tuple[str, str, str], int] = {
    ("recorded", "viewer", "/status?fragment=1"): 28_450,
    ("recorded", "admin", "/status?fragment=1"): 32_431,
    ("wide", "viewer", "/status?fragment=1"): 54_246,
    ("wide", "admin", "/status?fragment=1"): 63_271,
    ("deployed", "viewer", "/status?fragment=1"): 14_462,
    ("deployed", "admin", "/status?fragment=1"): 16_263,
    ("hosts", "viewer", "/status?fragment=1"): 14_878,
    ("hosts", "admin", "/status?fragment=1"): 16_150,
}
#: gzip's output moves with the text it is given — a time of day, a name — so the
#: wire's tolerance is wider than the rendering's.
_WIRE_TOLERANCE = 0.05

#: A response may differ from its baseline by this much before the test speaks: a
#: template's small change, never a stage's growth, which raises the number here —
#: an element more on every line of the recorded wall is past it.
_COST_TOLERANCE = 0.02

#: The recorded wall's fragment for a viewer: what one render took in the cloud
#: container on CPython 3.14 — 0.03 s, 1.25 MB at the peak of what it allocated
#: before stage 3, and 0.10 s and 3.6 MB with both faces of every node drawn — and
#: the ceilings, with room for a slower machine and the gate's coverage, that a
#: stage multiplying either again would hit.
_RENDER_CEILING_S = 0.3
_PEAK_CEILING_BYTES = 5_000_000


class _StartTags(HTMLParser):
    """Counts a document's elements by their start tags."""

    def __init__(self) -> None:
        super().__init__()
        self.count = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self.count += 1

    def handle_startendtag(self, tag: str,
                           attrs: list[tuple[str, str | None]]) -> None:
        self.count += 1


def tree_of(variant: str) -> StatusTree:
    """The tree a variant names: the hosts tree's, or the anonymized tree's."""
    if variant == hosts_tree.VARIANT:
        return hosts_tree.build()
    return anonymized_tree.build(variant)


def reason_cap_of(variant: str) -> int:
    """The line budget of the deployment a variant's tree is from."""
    if variant == hosts_tree.VARIANT:
        return hosts_tree.REASON_CAP
    return anonymized_tree.REASON_CAP


def looks_of(variant: str, tree: StatusTree) -> FirstLooks:
    """The first look a variant's wall is drawn with: the hosts tree's from the
    library's host types as its deployment mounts them, and each tree's from what the
    family's packages propose, stated by path since they are not installed here."""
    if variant == hosts_tree.VARIANT:
        return hosts_tree.first_looks(tree, app_module.config)
    return anonymized_tree.first_looks(tree, app_module.config)


def cost(body: bytes) -> Cost:
    parser = _StartTags()
    parser.feed(body.decode("utf-8"))
    return Cost(len(body), parser.count)


def _walk(node: StatusSnapshot) -> list[StatusSnapshot]:
    found = [node]
    for child in node.children:
        found.extend(_walk(child))
    return found


class AnonymizedTreeTests(TestCase):
    """The fixture is the tree the note measured on, and nothing of the deployment's."""

    def test_the_fixture_is_the_prototypes_tree(self):
        # one tree, read by eye once (R13): the sheet's copy and the prototype's
        # are the same bytes while the prototype is in the tree
        if not _PROTOTYPE_SHAPES.is_file():
            raise SkipTest("the prototype is not in this tree")
        self.assertEqual(anonymized_tree.SHAPES.read_bytes(),
                         _PROTOTYPE_SHAPES.read_bytes())

    def test_the_shapes_are_the_ones_the_note_describes(self):
        # §3.9: 265 nodes under two team roots of 98 and 99 leaves, six levels at
        # the deepest, the widest level 20 repositories with 63 workflows; 234
        # lines, half under 56 characters, the informational band's 17 findings on
        # one team, four of them over 1,000 characters
        rows = anonymized_tree.shapes()
        paths = [path for path, _code, _lengths in rows]
        self.assertEqual(len(rows), 265)
        leaves = [path for path in paths
                  if not any(other.startswith(path + "/") for other in paths)]
        self.assertEqual(
            sorted(sum(1 for leaf in leaves if leaf.startswith(team + "/"))
                   for team in ("/alpha", "/beta")), [98, 99])
        self.assertEqual(max(path.count("/") for path in paths), 6)
        runs = anonymized_tree.WORKFLOW_RUNS
        repositories = [path for path in paths
                        if path.startswith(runs + "/") and path.count("/") == 4]
        workflows = [path for path in paths
                     if path.startswith(runs + "/") and path.count("/") == 5]
        self.assertEqual((len(repositories), len(workflows)), (20, 63))
        lengths = [length for _path, _code, lengths in rows for length in lengths]
        self.assertEqual(len(lengths), 234)
        self.assertEqual(statistics.median(lengths), 56)
        findings = next(lengths for path, _code, lengths in rows
                        if path == anonymized_tree.INFORMATIONAL)
        self.assertEqual(len(findings), 17)
        self.assertEqual(sum(1 for length in findings if length > 1000), 4)
        self.assertEqual(
            {code for _path, code, _lengths in rows},
            {StatusCode.OK, StatusCode.WARN, StatusCode.ERROR})

    def test_every_line_has_its_recorded_length(self):
        # made-up text, the recorded length at most and never a word short of it:
        # a cut falls at a word, so a line is at most one filler phrase shorter
        tree = anonymized_tree.build()
        for path, _code, lengths in anonymized_tree.shapes():
            node = tree.snapshot(path)
            self.assertIsNotNone(node, path)
            self.assertEqual(len(node.reasons), len(lengths), path)
            for line, length in zip(node.reasons, lengths, strict=True):
                self.assertLessEqual(len(line.text), length, (path, line.text))
                self.assertGreaterEqual(len(line.text), length - 24, (path, line.text))

    def test_the_text_is_the_same_on_every_build(self):
        first = anonymized_tree.build().snapshot(anonymized_tree.INFORMATIONAL)
        second = anonymized_tree.build().snapshot(anonymized_tree.INFORMATIONAL)
        self.assertEqual([line.text for line in first.reasons],
                         [line.text for line in second.reasons])

    def test_what_the_shapes_do_not_record_is_filled_in(self):
        tree = anonymized_tree.build()
        # titles on the teams, the checks and their first levels; none deeper
        self.assertEqual(tree.snapshot("/alpha").title, "Team alpha")
        self.assertEqual(tree.snapshot("/beta/github/actions").title, "Workflow runs")
        self.assertEqual(tree.snapshot("/beta/aws/live/batch").title,
                         "Batch job queues")
        self.assertEqual(tree.snapshot("/alpha/github/actions/alpha_cache").title, "")
        # an about on a team and on each of its checks
        self.assertTrue(tree.snapshot("/beta").about)
        self.assertTrue(tree.snapshot("/beta/wiz").about)
        self.assertFalse(tree.snapshot("/beta/wiz/low").about)
        # the rosters claim show_when_quiet; a workflow does not
        self.assertTrue(tree.snapshot("/alpha/aws/live/ec2").show_when_quiet)
        self.assertTrue(
            tree.snapshot("/beta/aws/live/batch/ingest-queue").show_when_quiet)
        self.assertFalse(
            tree.snapshot("/alpha/github/actions/alpha_cache/pipeline.yml")
            .show_when_quiet)
        # the severity bands in their declared rank
        self.assertEqual([child.name for child in tree.snapshot("/beta/wiz").children],
                         ["critical", "high", "medium", "low", "informational"])
        # members where a line is one of a roster, prose where it is the node's own
        self.assertTrue(tree.snapshot("/alpha/wiz/informational").members)
        self.assertTrue(tree.snapshot("/beta/github/sbom_check").members)
        self.assertFalse(
            tree.snapshot("/alpha/github/actions/alpha_jenkins/pipeline.yml").members)
        # the checks' nodes carry their run facts
        github = tree.snapshot("/alpha/github")
        self.assertTrue(github.config)
        self.assertTrue(github.report)
        self.assertIsNotNone(github.run)

    def test_the_shapes_made_worse(self):
        recorded = _walk(anonymized_tree.build().snapshot(""))
        runs = anonymized_tree.WORKFLOW_RUNS
        with self.subTest(variant="outage"):
            nodes = _walk(anonymized_tree.build("outage").snapshot(""))
            failing = [node for node in nodes if node.path.startswith(runs + "/")
                       and not node.children and node.code is StatusCode.ERROR]
            self.assertEqual(len(failing), 63)
            self.assertEqual(len(nodes), len(recorded))
        with self.subTest(variant="blackout"):
            nodes = _walk(anonymized_tree.build("blackout").snapshot(""))
            teams = [node for node in nodes if not node.children
                     and (node.path.startswith("/alpha/")
                          or node.path.startswith("/beta/"))]
            self.assertEqual(len(teams), 197)
            self.assertTrue(all(node.code is StatusCode.ERROR and node.reasons
                                for node in teams))
            heartbeat = next(node for node in nodes if node.path == "/little-sister")
            self.assertIs(heartbeat.code, StatusCode.OK)
        with self.subTest(variant="wide"):
            nodes = _walk(anonymized_tree.build("wide").snapshot(""))
            repositories = [node for node in nodes
                            if node.path.startswith(runs + "/")
                            and node.path.count("/") == 4]
            workflows = [node for node in nodes if node.path.startswith(runs + "/")
                         and node.path.count("/") == 5]
            self.assertEqual((len(repositories), len(workflows)), (100, 500))
            self.assertEqual(
                sorted(node.code.name for node in workflows
                       if node.code is not StatusCode.OK),
                ["ERROR"] * 4 + ["WARN"])
        with self.subTest(variant="findings"):
            tree = anonymized_tree.build("findings")
            band = tree.snapshot(anonymized_tree.INFORMATIONAL)
            self.assertEqual(len(band.reasons), 300)
            self.assertEqual(
                len(tree.snapshot("/beta/wiz/informational").reasons), 15)
        with self.assertRaises(ValueError):
            anonymized_tree.build("worse")

    def test_the_deployed_wall_is_alphas_checks_at_the_root(self):
        # the deployment as it runs mounts one team's five checks at its root, each
        # a card (backlog #91's note, §2, 2026-10-17): alpha's, beside the engine's
        # own node, and nothing of beta's — every node of alpha's where it stood
        # beneath the team, with its code, its lines word for word and every fact
        # the recorded tree gives it
        recorded = anonymized_tree.build()
        deployed = anonymized_tree.build("deployed")
        team = anonymized_tree.TEAM
        root = deployed.snapshot("")
        self.assertEqual(
            sorted(child.name for child in root.children),
            ["aws", "github", "github-rate-limit", "little-sister", "loadtest",
             "wiz"])
        # the team is no node of this wall, and the root takes nothing of it
        self.assertEqual((root.title, root.about), ("", ""))
        self.assertIsNone(deployed.snapshot(team))
        self.assertIsNone(deployed.snapshot("/beta"))
        beneath = _walk(recorded.snapshot(team))[1:]
        engine = _walk(recorded.snapshot("/little-sister"))
        self.assertEqual(len(_walk(deployed.snapshot(""))),
                         1 + len(beneath) + len(engine))
        for node in beneath:
            path = node.path[len(team):]
            with self.subTest(path=path):
                mounted = deployed.snapshot(path)
                self.assertIsNotNone(mounted)
                self.assertEqual(
                    (mounted.code, mounted.members, mounted.title, mounted.about,
                     mounted.order, mounted.show_when_quiet, mounted.config,
                     mounted.report, mounted.run is None),
                    (node.code, node.members, node.title, node.about, node.order,
                     node.show_when_quiet, node.config, node.report,
                     node.run is None))
                self.assertEqual(
                    [(line.slug, line.text) for line in mounted.reasons],
                    [(line.slug, line.text) for line in node.reasons])
                self.assertEqual([child.name for child in mounted.children],
                                 [child.name for child in node.children])
        # a check's own node carries its run facts there, as a card's head shows
        self.assertIsNotNone(deployed.snapshot("/github").run)

    def test_the_sheet_shows_the_recorded_wall(self):
        fixture = FIXTURES_BY_NAME["anonymized_tree"]
        self.assertEqual(fixture.reason_cap, anonymized_tree.REASON_CAP)
        html = render_page(fixture)
        self.assertIn('data-path="/alpha"', html)
        self.assertIn('data-path="/beta"', html)
        # nothing declared, the built-in look's net starts alpha's twenty
        # repositories as chips — opened, with their workflows, 83 boxes — and the
        # failure budget opens the one whose workflow fails
        heads = re.findall(r'<div class="tree-node[^>]*'
                           r'data-node="/alpha/github/actions/[^/"]+"[^>]*>', html)
        self.assertEqual(len(heads), 20)
        self.assertEqual(sum('data-state="closed"' in head for head in heads), 19)
        self.assertEqual(sum('data-budget' in head for head in heads), 1)
        # and the page is the sheet's: every stamp pinned, the checks' next slot
        # with them, so two renders are the same bytes
        self.assertEqual(set(re.findall(r"→ (\d\d:\d\d)", html)), {"12:04"})
        self.assertEqual(render_page(fixture), html)

    def test_nothing_of_the_deployment_is_in_the_fixture(self):
        # the scan R13 asks for, run on the shapes, the builder and the rendered
        # wall against the patterns the release refuses
        if not _PRIVATE_STRINGS.is_file():
            raise SkipTest("the release's private strings are not in this tree")
        patterns = [line.strip() for line in
                    _PRIVATE_STRINGS.read_text(encoding="utf-8").splitlines()
                    if line.strip() and not line.startswith("#")]
        self.assertTrue(patterns)
        texts = {
            "the shapes": anonymized_tree.SHAPES.read_text(encoding="utf-8"),
            "the builder": Path(anonymized_tree.__file__).read_text(encoding="utf-8"),
            "the wall": render_page(FIXTURES_BY_NAME["anonymized_tree"]),
        }
        for what, text in texts.items():
            for pattern in patterns:
                self.assertIsNone(re.search(pattern, text, re.IGNORECASE),
                                  f"{pattern!r} in {what}")


class HostsTreeTests(TestCase):
    """The hosts tree is a second deployment's wall, and nothing of its own."""

    def test_the_shapes_are_the_wall_as_it_was_drawn(self):
        # 101 nodes a check wrote, 86 lines; nine hosts that host-metrics writes, each
        # with its five leaves, a filesystem's own beneath one host's disk; the
        # aws, github and API budget checks beside them; the engine's own branch
        rows = hosts_tree.shapes()
        paths = [path for path, _code, _lengths in rows]
        self.assertEqual(len(rows), 101)
        self.assertEqual(len(set(paths)), 101)
        self.assertEqual(sum(len(lengths) for _path, _code, lengths in rows), 86)
        self.assertEqual(len(hosts_tree.HOST_METRICS), 9)
        for host in hosts_tree.HOST_METRICS:
            self.assertEqual(
                sorted(path.rsplit("/", 1)[-1] for path in paths
                       if path.rsplit("/", 1)[0] == host
                       and path.rsplit("/", 1)[-1] in
                       ("cpu", "disk", "load", "memory", "ssh")),
                ["cpu", "disk", "load", "memory", "ssh"], host)
        disks = [path for path in paths
                 if path.startswith("/computer/local/nas01/system/disk/")]
        self.assertEqual(len(disks), 4)
        self.assertEqual({path.split("/")[1] for path in paths},
                         {"computer", "system", "little-sister"})
        self.assertEqual(
            {code for _path, code, _lengths in rows},
            {StatusCode.OK, StatusCode.WARN, StatusCode.ERROR})

    def test_every_line_has_its_recorded_length(self):
        tree = hosts_tree.build()
        for path, _code, lengths in hosts_tree.shapes():
            node = tree.snapshot(path)
            self.assertIsNotNone(node, path)
            self.assertEqual(len(node.reasons), len(lengths), path)
            for line, length in zip(node.reasons, lengths, strict=True):
                self.assertLessEqual(len(line.text), length, (path, line.text))
                self.assertGreaterEqual(len(line.text), length - 24, (path, line.text))

    def test_the_text_is_the_same_on_every_build(self):
        first, second = hosts_tree.build(), hosts_tree.build()
        for path, _code, _lengths in hosts_tree.shapes():
            self.assertEqual([line.text for line in first.snapshot(path).reasons],
                             [line.text for line in second.snapshot(path).reasons])

    def test_what_the_shapes_do_not_record_is_filled_in(self):
        tree = hosts_tree.build()
        # the two cards are containers; the checks' mounts carry their run facts
        self.assertEqual([child.name for child in tree.snapshot("").children],
                         ["computer", "little-sister", "system"])
        self.assertIsNone(tree.snapshot("/computer").run)
        self.assertIsNotNone(tree.snapshot("/computer/local/linux01").run)
        self.assertIsNotNone(tree.snapshot("/computer/local/macmini/system").run)
        self.assertIsNotNone(tree.snapshot("/system/aws").run)
        # the titles the deployment's files give, and a long one
        self.assertEqual(tree.snapshot("/computer/local/nas01").title, "Qnap NAS")
        self.assertEqual(tree.snapshot("/system/aws").title, "AWS")
        self.assertGreater(len(tree.snapshot("/computer/local/linux2").title), 60)
        self.assertEqual(tree.snapshot("/computer/local/linux01/cpu").title, "")
        # the host types' own about and handbook on their aspects, the deployment's
        # about where it wrote one, made-up text of its length, and neither on a
        # filesystem, which a run names (ADR-0133)
        self.assertEqual(tree.snapshot("/computer/local/node2/ssh").about,
                         host_metrics.ABOUT["ssh"])
        self.assertTrue(tree.snapshot("/computer/local/node2/ssh").has_handbook)
        self.assertEqual(len(tree.snapshot("/computer/local/nas01/system/load").about),
                         228)
        self.assertTrue(tree.snapshot("/computer/local/nas01/system/load").has_handbook)
        self.assertEqual(tree.snapshot("/computer/local/nas01/qnap/smart").about,
                         qnap_metrics.ABOUT["smart"])
        for volume in tree.snapshot("/computer/local/nas01/system/disk").children:
            self.assertEqual((volume.about, volume.has_handbook), ("", False))
        self.assertEqual(tree.snapshot("/computer/local/linux01").about, "")
        # aws's rosters claim show_when_quiet, billing and a host's leaf do not
        self.assertTrue(tree.snapshot("/system/aws/ec2").show_when_quiet)
        self.assertTrue(tree.snapshot("/system/aws/s3").show_when_quiet)
        self.assertFalse(tree.snapshot("/system/aws/billing").show_when_quiet)
        self.assertFalse(tree.snapshot("/computer/local/linux01/cpu").show_when_quiet)
        # members where a line is one of a roster, prose where it is the node's own
        self.assertTrue(tree.snapshot("/system/aws/lambda").members)
        self.assertTrue(tree.snapshot("/system/github-rate-limit").members)
        self.assertFalse(tree.snapshot("/computer/local/linux01/disk").members)
        # what fails: the heartbeat file on the Mac that runs it
        self.assertIs(tree.snapshot("/computer/local/macmini/beacon").code,
                      StatusCode.ERROR)
        with self.assertRaises(ValueError):
            hosts_tree.build("recorded")

    def test_the_host_types_stand_where_the_deployment_mounts_them(self):
        # host-metrics on every host, macos-memory beside it on the Mac and
        # qnap-metrics on the NAS, as the deployment's files have them; what each
        # proposes reaches its levels, and on the Mac's node, which two of them share
        # and whose own look neither speaks for, each leaf starts as its own check
        # proposes (ADR-0128 decision 5, as amended)
        checks = hosts_tree.checks()
        self.assertEqual(
            sorted((check.type_name, check.path) for check in checks),
            sorted([("host-metrics", mount) for mount in hosts_tree.HOST_METRICS]
                   + [("macos-memory", "/computer/local/macmini/system"),
                      ("qnap-metrics", "/computer/local/nas01/qnap")]))
        looks = hosts_tree.first_looks(hosts_tree.build(), app_module.config)
        for mount in hosts_tree.HOST_METRICS:
            self.assertIs(looks.look(mount).chips,
                          None if mount == "/computer/local/macmini/system" else True,
                          mount)
        for level in ("/computer/local/nas01/system/disk",
                      "/computer/local/nas01/qnap/smart",
                      "/computer/local/nas01/qnap/temperature",
                      "/computer/local/macmini/system/processes"):
            self.assertIs(looks.look(level).chips, True, level)
        self.assertIsNone(looks.look("/computer/local/nas01/qnap").chips)
        self.assertIsNone(looks.look("/computer/local").chips)
        mac = "/computer/local/macmini/system"
        for leaf in ("cpu", "ssh", "swap", "pressure", "processes"):
            self.assertIs(looks.children_chips(mac, f"{mac}/{leaf}"), True, leaf)

    def test_the_hover_cards_map_says_what_the_packages_and_the_library_say(self):
        # each node's about rides in the fragment as its first block and the count
        # of the blocks after it: the packages' own aspects and the library's own
        # branch say theirs, and the host types' aspects theirs, with their handbooks;
        # a filesystem, which has no about, says its description (ADR-0133)
        app_module.app.config["TESTING"] = True
        saved = app_module.status_tree
        self.addCleanup(setattr, app_module, "status_tree", saved)
        app_module.status_tree = hosts_tree.build()
        client = app_module.app.test_client()
        client.post("/login", data={"username": "pan", "password": "12345678"})
        body = client.get("/status?fragment=1").get_data(as_text=True)
        found = re.search(r'<script type="application/json" id="node-meta">(.*?)'
                          r"</script>", body, re.S)
        assert found is not None
        meta = json.loads(found.group(1))
        self.assertEqual(len(meta), 87)
        self.assertEqual(
            {path: entry["more"] for path, entry in meta.items()
             if path.startswith(("/system/aws/", "/system/github/"))},
            {"/system/aws/batch": 4, "/system/aws/billing": 5,
             "/system/aws/codepipeline": 9, "/system/aws/ec2": 10,
             "/system/aws/lambda": 8, "/system/aws/s3": 6,
             "/system/github/actions": 2, "/system/github/issues": 1,
             "/system/github/pull_requests": 1})
        self.assertEqual(sum(path.startswith("/little-sister/") for path in meta), 7)
        self.assertEqual(meta["/computer/local/linux01/disk"]["handbook"],
                         "/handbook/computer/local/linux01/disk")
        volume = meta["/computer/local/nas01/system/disk/usb1"]
        self.assertNotIn("handbook", volume)
        self.assertIn("this filesystem", volume["about"])

    def test_nothing_of_the_deployment_is_in_the_hosts_tree(self):
        if not _PRIVATE_STRINGS.is_file():
            raise SkipTest("the release's private strings are not in this tree")
        patterns = [line.strip() for line in
                    _PRIVATE_STRINGS.read_text(encoding="utf-8").splitlines()
                    if line.strip() and not line.startswith("#")]
        self.assertTrue(patterns)
        app_module.app.config["TESTING"] = True
        saved = app_module.status_tree
        self.addCleanup(setattr, app_module, "status_tree", saved)
        app_module.status_tree = hosts_tree.build()
        client = app_module.app.test_client()
        client.post("/login", data={"username": "pan", "password": "12345678"})
        texts = {
            "the shapes": hosts_tree.SHAPES.read_text(encoding="utf-8"),
            "the builder": Path(hosts_tree.__file__).read_text(encoding="utf-8"),
            "the wall": client.get("/status").get_data(as_text=True),
        }
        for what, text in texts.items():
            for pattern in patterns:
                self.assertIsNone(re.search(pattern, text, re.IGNORECASE),
                                  f"{pattern!r} in {what}")


class WallCostTests(TestCase):
    """The fragment's cost, the render's time and its peak memory."""

    def setUp(self) -> None:
        app_module.app.config["TESTING"] = True
        self.saved_tree = app_module.status_tree
        self.saved_config = app_module.config
        self.saved_looks = app_module.first_looks
        self.addCleanup(self._restore)
        # the deployment's line budget (§3.9); depth at its default
        app_module.config = replace(app_module.config,
                                    reason_cap=anonymized_tree.REASON_CAP)
        self.client = app_module.app.test_client()
        self.client.post("/login", data={"username": "pan", "password": "12345678"})

    def _restore(self) -> None:
        app_module.status_tree = self.saved_tree
        app_module.config = self.saved_config
        app_module.first_looks = self.saved_looks

    def _as(self, role: str) -> None:
        with self.client.session_transaction() as session:
            session["admin"] = role == "admin"

    def _load(self, variant: str) -> None:
        """The variant's tree, its deployment's line budget and its first look."""
        app_module.status_tree = tree_of(variant)
        app_module.config = replace(app_module.config,
                                    reason_cap=reason_cap_of(variant))
        app_module.first_looks = looks_of(variant, app_module.status_tree)

    def _fetch(self, variant: str, role: str, url: str) -> bytes:
        self._load(variant)
        self._as(role)
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200, url)
        return response.data

    def test_the_fragments_bytes_and_elements_hold(self):
        for (variant, role, url), baseline in BASELINE.items():
            with self.subTest(variant=variant, role=role, url=url):
                got = cost(self._fetch(variant, role, url))
                for measure in ("bytes", "elements"):
                    expected = getattr(baseline, measure)
                    actual = getattr(got, measure)
                    self.assertLessEqual(
                        abs(actual - expected), expected * _COST_TOLERANCE,
                        f"{url} for a {role} on the {variant} tree: {actual:,} "
                        f"{measure} against a baseline of {expected:,}")

    def test_the_fragments_weight_on_the_wire_holds(self):
        for (variant, role, url), baseline in WIRE.items():
            with self.subTest(variant=variant, role=role, url=url):
                self._load(variant)
                self._as(role)
                response = self.client.get(url, headers={"Accept-Encoding": "gzip"})
                self.assertEqual(response.headers.get("Content-Encoding"), "gzip")
                actual = len(response.data)
                self.assertLessEqual(
                    abs(actual - baseline), baseline * _WIRE_TOLERANCE,
                    f"{url} for a {role} on the {variant} tree weighs {actual:,} "
                    f"bytes on the wire against a baseline of {baseline:,}")
                # and it is the fragment, whole
                rendered = cost(self._fetch(variant, role, url))
                self.assertLess(actual * 15, rendered.bytes)

    def test_the_hosts_wall_is_drawn_as_its_types_propose(self):
        # the NAS's disk fans out, and host-metrics proposes its filesystems as chips
        # and itself as one of its host's: a chip, where the density would leave a
        # branch open — and on the Mac's node, which two types share, the watched
        # processes are a chip as macos-memory proposes, where the density left
        # their branch open
        body = self._fetch("hosts", "viewer", "/status?fragment=1").decode("utf-8")
        self.assertIn('data-node="/computer/local/nas01/system/disk" '
                      'data-state="closed"', body)
        self.assertIn('data-node="/computer/local/macmini/system/processes" '
                      'data-state="closed"', body)

    def test_an_admins_fragment_carries_the_marks_and_no_editor(self):
        # what an admin's swap pays over a viewer's: ‖ on every open head of a node
        # with no pin of its own, and never an editor, which is the page's one
        viewer = cost(self._fetch("recorded", "viewer", "/status?fragment=1"))
        fragment = self._fetch("recorded", "admin", "/status?fragment=1")
        admin = cost(fragment)
        self.assertGreater(admin.bytes, viewer.bytes)
        self.assertGreater(admin.elements, viewer.elements)
        self.assertIn(b'data-control="pin"', fragment)
        self.assertNotIn(b"maintenance-editor-form", fragment)

    def test_the_render_time_and_peak_memory_hold(self):
        app_module.status_tree = anonymized_tree.build()
        self._as("viewer")
        self.client.get("/status?fragment=1")  # warm: the templates compiled
        took = []
        for _ in range(5):
            started = time.perf_counter()
            self.assertEqual(self.client.get("/status?fragment=1").status_code, 200)
            took.append(time.perf_counter() - started)
        render = statistics.median(took)
        self.assertLessEqual(
            render, _RENDER_CEILING_S,
            f"the fragment rendered in {render:.3f} s (the five: "
            f"{', '.join(f'{t:.3f}' for t in took)})")
        tracemalloc.start()
        try:
            self.client.get("/status?fragment=1")
            _current, peak = tracemalloc.get_traced_memory()
        finally:
            tracemalloc.stop()
        self.assertLessEqual(
            peak, _PEAK_CEILING_BYTES,
            f"the render peaked at {peak:,} bytes of traced memory")
