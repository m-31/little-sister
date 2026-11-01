"""How a handled part looks (ADR-0143): it keeps its true color, its tint and its
place, carries its job's mark at its top right and, wherever one level up counts it as
something other than it shows, a rail on its right edge in the color it counts as
instead — a line's in its node's own status, a node's in what its parent counts.

What a rail is drawn in is the tree's to say (`node_rail`, `line_rail`); where the
mark and the rail stand is the pages'. The colors' contrast is
`tests/test_contrast.py`'s.
"""
from __future__ import annotations

import os
from datetime import UTC, datetime, timedelta
from unittest import TestCase, mock

os.environ.setdefault("SECRET_KEY", "test-key")

from little_sister import app as app_module
from little_sister import local_login
from little_sister.aggregation import ALL, RuleSet
from little_sister.pins import SEEN
from little_sister.reasons import Entry
from little_sister.status import StatusCode
from little_sister.tree import StatusTree, line_rail, node_rail
from tests.page_tree import Element, parse
from tests.test_aggregation_tree import CAP, HEAL, rule

ERROR, WARN, OK = StatusCode.ERROR, StatusCode.WARN, StatusCode.OK
LATER = timedelta(days=1)


def _line(tree: StatusTree, path: str, slug: str):
    node = tree.snapshot(path)
    assert node is not None
    (line,) = [line for line in node.reasons if line.slug == slug]
    return node, line


class RailTests(TestCase):
    """What a rail is drawn in: what one level up counts of a part, where that is
    not what it shows — and nothing where the two are one."""

    def setUp(self) -> None:
        self.tree = StatusTree()
        self.tree.upsert("/ci/build", ERROR, [
            Entry("test", "test fails", code=ERROR),
            Entry("lint", "lint warns", code=WARN),
            Entry("docs", "docs build", code=OK)], members=True)

    def seen(self, path: str, slug: str = "") -> None:
        self.tree.set_acknowledgment(path, slug, SEEN, "looked into",
                                     expires_at=None, set_by="ada")

    def test_a_seen_line_counts_as_ok_and_one_nobody_has_seen_as_it_reads(self):
        self.seen("/ci/build", "test")
        self.assertEqual(line_rail(*_line(self.tree, "/ci/build", "test")), "ok")
        self.assertIsNone(line_rail(*_line(self.tree, "/ci/build", "lint")))
        self.assertIsNone(line_rail(*_line(self.tree, "/ci/build", "docs")))

    def test_a_pinned_line_counts_nothing_as_maintenance_does_and_draws_none(self):
        self.tree.set_entry_maintenance("/ci/build", "test", "rerun",
                                        expires_at=datetime.now(UTC) + LATER)
        node, line = _line(self.tree, "/ci/build", "test")
        self.assertTrue(line.quiet)
        self.assertIsNone(line_rail(node, line))

    def test_a_node_seen_for_itself_counts_as_ok_where_nothing_fails_beneath(self):
        self.tree.upsert("/host/disk", ERROR, "disk 97 % full")
        self.seen("/host/disk")
        disk = self.tree.snapshot("/host/disk")
        assert disk is not None
        self.assertIs(disk.code, ERROR, "it keeps its true color")
        self.assertEqual(node_rail(disk), "ok")

    def test_one_with_a_failure_beneath_counts_as_that_failure_and_draws_none(self):
        self.tree.upsert("/host", ERROR, "the host itself fails")
        self.tree.upsert("/host/disk", ERROR, "disk 97 % full")
        self.seen("/host")
        host = self.tree.snapshot("/host")
        assert host is not None
        self.assertIsNotNone(host.acknowledgment)
        self.assertIsNone(node_rail(host))

    def test_a_damped_node_draws_what_its_parent_still_counts(self):
        self.tree.upsert("/svc/api", OK, escalate_after=3)
        self.tree.upsert("/svc/api", ERROR)
        api = self.tree.snapshot("/svc/api")
        assert api is not None and api.damping is not None
        self.assertIs(api.code, ERROR)
        self.assertEqual(node_rail(api), "ok")

    def test_a_shielded_node_counts_nothing_above(self):
        self.tree.upsert("/net/vpn", ERROR)
        self.tree.upsert("/svc/api", ERROR)
        self.tree.set_dependency("/svc/api", "/net/vpn")
        api = self.tree.snapshot("/svc/api")
        assert api is not None and api.shielded_by == "/net/vpn"
        self.assertEqual(node_rail(api), "nothing")

    def test_a_node_in_maintenance_or_not_reported_counts_as_it_shows(self):
        self.tree.set_maintenance("/ci/build", "rewiring",
                                  expires_at=datetime.now(UTC) + LATER)
        self.tree.upsert("/quiet", StatusCode.UNDEFINED)
        for path in ("/ci/build", "/quiet"):
            node = self.tree.snapshot(path)
            assert node is not None
            with self.subTest(path=path):
                self.assertIsNone(node_rail(node))


class _Pages(TestCase):
    """A host whose disk fails for itself and a build whose lines are members;
    signed in as the suite's admin."""

    def setUp(self) -> None:
        app_module.app.config["TESTING"] = True
        self.tree = StatusTree()
        app_module.status_tree = self.tree
        self.client = app_module.app.test_client()
        self.client.post("/login", data={"username": "pan", "password": "12345678"})
        self.tree.upsert("/site/web/disk", ERROR, "disk 97 % full")
        self.tree.upsert("/site/web/cpu", OK)
        self.tree.upsert("/site/ci/build", ERROR, [
            Entry("test", "test fails", code=ERROR),
            Entry("lint", "lint warns", code=WARN),
            Entry("docs", "docs build", code=OK)], members=True)

    def page(self, url: str) -> Element:
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200, url)
        return parse(response.get_data(as_text=True))

    def seen(self, path: str, slug: str = "") -> None:
        self.tree.set_acknowledgment(path, slug, SEEN, "looked into",
                                     expires_at=None, set_by="ada")

    @staticmethod
    def line_of(page: Element, words: str,
                kind: str = "status-node__reason") -> Element:
        found = [line for line in page.all(kind) if words in line.text()]
        assert len(found) == 1, (words, found)
        return found[0]

    @staticmethod
    def box_of(page: Element, path: str) -> Element:
        """The node's box: a card, or the box a tree node holds."""
        (node,) = [node for node in page.all("tree-node")
                   if node.attrs.get("data-node") == path]
        if node.has("status-card"):
            return node
        # the node's own box comes first; the boxes of the nodes beneath it follow
        return node.all("tree-box")[0]

    @staticmethod
    def classes(element: Element) -> list[str]:
        return element.attrs.get("class", "").split()


class WallLineTests(_Pages):
    """On the wall a handled line carries its mark top right, a link to the line on
    its node's page, and its rail."""

    def test_a_seen_line_carries_its_mark_after_its_words_and_a_green_rail(self):
        self.seen("/site/ci/build", "test")
        line = self.line_of(self.page("/status?depth=3"), "test fails")
        self.assertTrue(line.has("has-mark"))
        self.assertIn("rail-ok", self.classes(line))
        self.assertTrue(line.has("s-error"), "it keeps its true color")
        mark = line.one("line-mark")
        # the mark ends the line, where the stylesheet places it at its top right
        self.assertIs([child for child in line.children
                       if isinstance(child, Element)][-1], mark)
        # its door: the node's Notes tab at the seen (ADR-0147 decision 7)
        self.assertEqual(mark.tag, "a")
        self.assertEqual(mark.attrs.get("href"),
                         "/notes/site/ci/build?reason=test&at=seen#at")
        self.assertEqual(mark.attrs.get("title"),
                         "Seen by ada, until it changes · counts as ok")
        self.assertIn("mark-ok", self.classes(mark))

    def test_a_line_nobody_has_handled_carries_neither(self):
        self.seen("/site/ci/build", "test")
        line = self.line_of(self.page("/status?depth=3"), "lint warns")
        self.assertFalse(line.has("has-mark"))
        self.assertFalse(line.has("has-rail"))
        self.assertEqual(line.all("line-mark"), [])

    def test_a_pinned_line_carries_its_pause_mark_and_no_rail(self):
        self.tree.set_entry_maintenance("/site/ci/build", "lint", "rerun",
                                        expires_at=datetime.now(UTC) + LATER,
                                        set_by="ada")
        line = self.line_of(self.page("/status?depth=3"), "lint warns")
        self.assertFalse(line.has("has-rail"))
        mark = line.one("line-pin")
        self.assertIn("mark-maintenance", self.classes(mark))
        self.assertTrue(mark.attrs.get("title", "").startswith(
            "In maintenance by ada until "), mark.attrs.get("title"))


class NodePageLineTests(_Pages):
    """On a node's own page the rail runs down the whole row, and the mark stands in
    the line's one seat, where ◇ stands while nothing handles the line, for the reader
    who may set something there (ADR-0147 decision 1)."""

    def test_the_ringed_check_stands_in_the_line_s_seat(self):
        self.seen("/site/ci/build", "test")
        row = self.line_of(self.page("/status/site/ci/build"), "test fails",
                           "check-reason")
        self.assertIn("rail-ok", self.classes(row))
        mark = row.one("line-mark")
        # its door, as on the wall
        self.assertEqual((mark.tag, mark.attrs.get("href")),
                         ("a", "/notes/site/ci/build?reason=test&at=seen#at"))
        self.assertTrue(mark.has("is-seated"))
        self.assertIs(mark.parent, row.one("check-reason__box"))
        self.assertTrue(row.one("check-reason__rail").has("check-reason__rail--seat"))
        self.assertEqual(row.all("line-door"), [], "no ◇ beside its mark")

    def test_a_pin_s_mark_stands_in_the_pause_mark_s_seat(self):
        self.tree.set_entry_maintenance("/site/ci/build", "lint", "rerun",
                                        expires_at=datetime.now(UTC) + LATER)
        row = self.line_of(self.page("/status/site/ci/build"), "lint warns",
                           "check-reason")
        mark = row.one("line-pin")
        self.assertTrue(mark.has("is-seated"))
        self.assertTrue(row.one("check-reason__rail").has("check-reason__rail--seat"))
        self.assertFalse(row.has("has-rail"))

    def test_a_reader_with_no_seats_finds_the_mark_ending_the_line_s_rail(self):
        self.seen("/site/ci/build", "test")
        self.client.get("/logout")
        with mock.patch.dict(local_login.registered().users,
                             {"viewer": {"firstname": "V", "lastname": "R",
                                         "password": "pw", "admin": False}}):
            self.client.post("/login", data={"username": "viewer", "password": "pw"})
            page = self.page("/status/site/ci/build")
        row = self.line_of(page, "test fails", "check-reason")
        mark = row.one("line-mark")
        self.assertFalse(mark.has("is-seated"))
        self.assertTrue(mark.within(row.one("check-reason__rail")))


class NodeTests(_Pages):
    """A node with a rule on its own part: the job's mark beside its head's state,
    on its own tint, and the rail on its box where it counts as something else."""

    def test_a_node_seen_for_itself_carries_both(self):
        self.seen("/site/web/disk")
        box = self.box_of(self.page("/status?depth=3"), "/site/web/disk")
        self.assertIn("rail-ok", self.classes(box))
        self.assertTrue(box.has("s-error"), "it keeps its true color")
        mark = box.one("head-ack")
        self.assertTrue(mark.has("ls-sign") and mark.has("ls-sign--ok"))
        self.assertEqual(mark.attrs.get("title"),
                         "Seen by ada, until it changes · its own failure counts as "
                         "ok above")

    def test_with_a_failure_beneath_it_keeps_its_mark_and_draws_no_rail(self):
        self.tree.upsert("/site/web", ERROR, "the web tier fails itself")
        self.seen("/site/web")
        box = self.box_of(self.page("/status?depth=3"), "/site/web")
        self.assertFalse(box.has("has-rail"))
        self.assertEqual(len(box.all("head-ack")), 1)

    def test_the_head_of_its_page_carries_them_too(self):
        self.seen("/site/web/disk")
        head = self.page("/status/site/web/disk").one("viewed-head")
        self.assertIn("rail-ok", self.classes(head))
        self.assertEqual(len(head.all("head-ack")), 1)

    def test_a_node_in_maintenance_carries_neither(self):
        self.seen("/site/web/disk")
        self.tree.set_maintenance("/site/web/disk", "swapping it",
                                  expires_at=datetime.now(UTC) + LATER)
        box = self.box_of(self.page("/status?depth=3"), "/site/web/disk")
        self.assertFalse(box.has("has-rail"))
        self.assertEqual(box.all("head-mark"), [])

    def test_a_damped_node_draws_what_its_parent_still_counts(self):
        self.tree.upsert("/site/web/cpu", OK, escalate_after=3)
        self.tree.upsert("/site/web/cpu", ERROR, "load 30")
        box = self.box_of(self.page("/status?depth=3"), "/site/web/cpu")
        self.assertIn("rail-ok", self.classes(box))
        self.assertIn("1 of 3 to escalate", box.one("status-node__state").text())

    def test_a_shield_says_so_beside_its_state_and_draws_nothing(self):
        self.tree.upsert("/net/vpn", ERROR, "tunnel down")
        self.tree.upsert("/site/web/cpu", ERROR, "no answer")
        self.tree.set_dependency("/site/web/cpu", "/net/vpn")
        box = self.box_of(self.page("/status?depth=3"), "/site/web/cpu")
        self.assertIn("rail-nothing", self.classes(box))
        (said,) = [part for part in box.one("status-node__state").all("status-reported")
                   if "reached through" in part.text()]
        self.assertEqual(said.text(), "· reached through vpn")
        self.assertTrue(said.attrs.get("title", "").startswith(
            "Reached through /net/vpn, which is failing"))


class RuleTests(TestCase):
    """A configured rule draws them as a person's acceptance does, in the color its
    table makes of the part."""

    def setUp(self) -> None:
        app_module.app.config["TESTING"] = True
        self.tree = StatusTree()
        self.tree.use_aggregation(RuleSet((
            rule("develop advises", "/aws/develop", CAP),
            rule("ec2 heals", "/aws/*/ec2", HEAL, lines=[ALL]))))
        app_module.status_tree = self.tree
        self.client = app_module.app.test_client()
        self.client.post("/login", data={"username": "pan", "password": "12345678"})
        self.tree.upsert("/aws/develop/lambda", ERROR, "timed out")
        self.tree.upsert("/aws/prod/ec2", WARN, [
            Entry("i-1", "web-1 cpu credits low", code=WARN),
            Entry("i-2", "web-2 running", code=OK)], members=True)

    def page(self, url: str) -> Element:
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200, url)
        return parse(response.get_data(as_text=True))

    def test_a_healed_line_carries_its_section_mark_and_a_green_rail(self):
        page = self.page("/status/aws/prod")
        (line,) = [line for line in page.all("status-node__reason")
                   if "web-1" in line.text()]
        self.assertIn("rail-ok", line.attrs.get("class", "").split())
        mark = line.one("line-rule")
        self.assertIn("mark-ok", mark.attrs.get("class", "").split())
        self.assertEqual(mark.attrs.get("title"), "Counts as ok by the rule ec2 heals")

    def test_a_capped_node_carries_its_section_mark_and_an_amber_rail(self):
        page = self.page("/status?depth=3")
        (node,) = [node for node in page.all("tree-node")
                   if node.attrs.get("data-node") == "/aws/develop"]
        box = node if node.has("status-card") else node.all("tree-box")[0]
        self.assertIn("rail-warn", box.attrs.get("class", "").split())
        mark = box.one("head-rule")
        self.assertTrue(mark.has("ls-sign--warn"))
        self.assertEqual(mark.attrs.get("title"),
                         "Counts as warn above by the rule develop advises")
