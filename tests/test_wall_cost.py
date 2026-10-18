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
team's checks, and not a word of the deployment's own (R13).
"""
from __future__ import annotations

import re
import statistics
import time
import tracemalloc
from dataclasses import dataclass, replace
from html.parser import HTMLParser
from pathlib import Path
from unittest import SkipTest, TestCase

from little_sister import app as app_module
from little_sister.status import StatusCode
from little_sister.tree import StatusSnapshot
from tests import anonymized_tree
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
#: Lex's word of 2026-10-16, **the caret left every head**, the row saying itself
#: under the pointer that a press opens or closes it: 54 bytes and one element a
#: node, open or closed, 2.1 to 2.8 % of the bytes and 3.1 to 3.9 % of the
#: elements, and 0.3 to 0.6 % on the wire. Before it the fragments were 589,068
#: and 660,269 bytes (7,775 and 8,567 elements) on the recorded wall, 559,960 and
#: 631,161 (7,409 and 8,201) in the outage, 517,797 and 588,998 (6,847 and 7,639)
#: in the blackout, 1,751,569 and 1,970,823 (22,497 and 24,840) wide, and the
#: workflow runs' page 1,371,527 (16,726). And on his word of the same day **a name
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
BASELINE: dict[tuple[str, str, str], Cost] = {
    ("recorded", "viewer", "/status?fragment=1"): Cost(582_031, 7_942),
    ("recorded", "admin", "/status?fragment=1"): Cost(653_232, 8_734),
    ("outage", "viewer", "/status?fragment=1"): Cost(552_923, 7_576),
    ("outage", "admin", "/status?fragment=1"): Cost(624_124, 8_368),
    ("blackout", "viewer", "/status?fragment=1"): Cost(510_760, 7_014),
    ("blackout", "admin", "/status?fragment=1"): Cost(581_961, 7_806),
    ("wide", "viewer", "/status?fragment=1"): Cost(1_725_876, 23_375),
    ("wide", "admin", "/status?fragment=1"): Cost(1_945_130, 25_718),
    ("findings", "viewer", "/status/alpha/wiz/informational"): Cost(267_210, 2_361),
    ("wide", "viewer", "/status/alpha/github/actions?fragment=1"):
        Cost(1_350_042, 17_340),
    ("deployed", "viewer", "/status?fragment=1"): Cost(287_068, 3_949),
    ("deployed", "admin", "/status?fragment=1"): Cost(321_267, 4_345),
}
#: What the fragments weigh **on the wire**, gzipped where the request takes gzip,
#: which every browser's does (`app._compressed_where_asked`, on Lex's word of
#: 2026-10-16): the recorded wall's, the deployed one's and the wide one's, for a
#: viewer and for an admin, a twentieth to a thirty-fifth of the bytes rendered. The
#: bytes above are what the browser parses; these are what the network carries every
#: ten seconds to every open tab. Before the head's row the viewer's weighed 25,576
#: and 48,583, and
#: before the hover card's map rode in the fragment 26,986 and 51,580, an admin's
#: 29,794 and 58,318, and before the chip runs 27,786 and 52,462, 30,551 and 59,044.
WIRE: dict[tuple[str, str, str], int] = {
    ("recorded", "viewer", "/status?fragment=1"): 27_908,
    ("recorded", "admin", "/status?fragment=1"): 30_685,
    ("wide", "viewer", "/status?fragment=1"): 52_484,
    ("wide", "admin", "/status?fragment=1"): 59_095,
    ("deployed", "viewer", "/status?fragment=1"): 14_234,
    ("deployed", "admin", "/status?fragment=1"): 15_577,
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
        # today's wall folds alpha's quiet repositories past branch_cap
        self.assertIn("+16 more", html)
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


class WallCostTests(TestCase):
    """The fragment's cost, the render's time and its peak memory."""

    def setUp(self) -> None:
        app_module.app.config["TESTING"] = True
        self.saved_tree = app_module.status_tree
        self.saved_config = app_module.config
        self.addCleanup(self._restore)
        # the deployment's line budget (§3.9); density, branch_cap and depth default
        app_module.config = replace(app_module.config,
                                    reason_cap=anonymized_tree.REASON_CAP)
        self.client = app_module.app.test_client()
        self.client.post("/login", data={"username": "pan", "password": "12345678"})

    def _restore(self) -> None:
        app_module.status_tree = self.saved_tree
        app_module.config = self.saved_config

    def _as(self, role: str) -> None:
        with self.client.session_transaction() as session:
            session["admin"] = role == "admin"

    def _fetch(self, variant: str, role: str, url: str) -> bytes:
        app_module.status_tree = anonymized_tree.build(variant)
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
                app_module.status_tree = anonymized_tree.build(variant)
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
