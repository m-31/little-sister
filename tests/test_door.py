"""One door, ◇, and what it counts (ADR-0147 decisions 1 to 3 and 7).

The tree's half: ``tree.handled_parts`` lists every part at and beneath a node that
something handles now, each once, and ``tree.door_counts`` counts them for every node in
one walk — the one function that gives a node's *Notes* tab its list and its door its
number. The page's half: a mark is a door, a link to the node's tab at the block it
marks (`?at=`); the tab, asked at a block, carries the page's one anchor there and
opens its editor for whoever may change it; and the tab lists what stands beneath a
node in every state. The door on every head, its number and its words, are
`tests/test_card_list.py`'s and `tests/test_web.py`'s; a line's seat is
`tests/test_pin_block.py`'s.
"""
from __future__ import annotations

import os
from datetime import UTC, datetime, timedelta
from unittest import TestCase

os.environ.setdefault("SECRET_KEY", "test-key")

from flask import g

from little_sister import app as app_module
from little_sister.pins import SEEN
from little_sister.reasons import Entry
from little_sister.status import StatusCode
from little_sister.tree import DoorCount, StatusTree, door_counts, handled_parts
from tests.page_tree import Element, parse
from tests.test_aggregation_tree import CAP, HEAL, rule, ruled

ERROR, WARN, OK = StatusCode.ERROR, StatusCode.WARN, StatusCode.OK
LATER = timedelta(days=1)


def _pin(tree: StatusTree, path: str, slug: str = "") -> None:
    expires = datetime.now(UTC) + LATER
    if slug:
        tree.set_entry_maintenance(path, slug, "planned", expires_at=expires,
                                   set_by="ada")
    else:
        tree.set_maintenance(path, "planned", expires_at=expires, set_by="ada")


def _seen(tree: StatusTree, path: str, slug: str = "") -> None:
    write = tree.set_acknowledgment(path, slug, SEEN, "looked into", expires_at=None,
                                    set_by="ada")
    assert write.current is not None, write.problem


class PartsTests(TestCase):
    """What stands at and beneath a node, part by part."""

    def setUp(self) -> None:
        self.tree = StatusTree()
        self.tree.upsert("/site/web/disk", ERROR, "disk 97 % full")
        self.tree.upsert("/site/web/cpu", OK)
        self.tree.upsert("/site/ci/build", ERROR, [
            Entry("test", "test fails", code=ERROR),
            Entry("lint", "lint warns", code=WARN)], members=True)

    def node(self, path: str):
        found = self.tree.snapshot(path)
        assert found is not None
        return found

    def test_each_part_once_in_the_tree_s_order_its_own_before_its_lines(self):
        _seen(self.tree, "/site/web/disk")
        _pin(self.tree, "/site/ci/build", "lint")
        _seen(self.tree, "/site/ci/build", "test")
        _pin(self.tree, "/site/ci/build")
        parts = handled_parts(self.node("/site"))
        self.assertEqual([(part.path, part.slug, part.job) for part in parts], [
            ("/site/ci/build", "", "node"),
            ("/site/ci/build", "test", SEEN),
            ("/site/ci/build", "lint", "line"),
            ("/site/web/disk", "", SEEN)])

    def test_a_part_two_things_handle_is_one_part_with_both(self):
        # a node's pin and its own acknowledgment beside it, which decides nothing
        # under the pin: one part, the pin its job, both its rules
        _seen(self.tree, "/site/web/disk")
        _pin(self.tree, "/site/web/disk")
        node = self.node("/site/web/disk")
        (part,) = handled_parts(node)
        self.assertEqual(part.job, "node")
        self.assertEqual([rule_.job for rule_ in part.rules], ["maintenance", SEEN])
        self.assertEqual(door_counts(node)[node.path].count, 1)

    def test_a_line_a_rule_acts_on_is_a_part_of_its_own(self):
        tree = ruled(rule("lint heals", "/site/ci/build", HEAL, lines=["lint"]))
        tree.upsert("/site/ci/build", ERROR, [
            Entry("test", "test fails", code=ERROR),
            Entry("lint", "lint warns", code=WARN)], members=True)
        node = tree.snapshot("/site/ci/build")
        assert node is not None
        (part,) = handled_parts(node)
        self.assertEqual((part.slug, part.job), ("lint", "rule"))
        self.assertEqual(door_counts(node)[node.path].by_job, {"rule": 1})

    def test_a_door_counts_what_is_at_and_beneath_and_nothing_above(self):
        _seen(self.tree, "/site/web/disk")
        _pin(self.tree, "/site/ci/build", "lint")
        _pin(self.tree, "/site")
        doors = door_counts(self.node("/"))
        self.assertEqual(doors["/site"].by_job, {"node": 1, SEEN: 1, "line": 1})
        # the pin on /site is its own door's, not one beneath it
        self.assertEqual(doors["/site/web"].by_job, {SEEN: 1})
        self.assertEqual(doors["/site/web/cpu"].count, 0)
        self.assertEqual(doors["/site/ci/build"].by_job, {"line": 1})
        # one walk, the same as each node's list counted
        for path, door in doors.items():
            with self.subTest(path=path):
                self.assertEqual(door.count, len(handled_parts(self.node(path))))

    def test_a_rule_on_a_node_counts_while_it_changes_the_count(self):
        tree = ruled(rule("web advises", "/site/web", CAP))
        tree.upsert("/site/web/disk", ERROR, "disk 97 % full")
        node = tree.snapshot("/site")
        assert node is not None
        self.assertEqual(door_counts(node)["/site"].by_job, {"rule": 1})
        tree.upsert("/site/web/disk", OK)
        node = tree.snapshot("/site")
        assert node is not None
        self.assertEqual(door_counts(node)["/site"].count, 0)

    def test_its_words_say_how_many_of_each_in_the_order_handled_lists(self):
        self.assertEqual(DoorCount({}).words, "")
        self.assertEqual(DoorCount({SEEN: 2, "line": 1, "rule": 1}).words,
                         "4 handled: 1 line in maintenance, 2 seen, 1 by a rule")
        self.assertEqual(DoorCount({"node": 2}).words,
                         "2 handled: 2 nodes in maintenance")


class _Pages(TestCase):
    """A site whose disk fails for itself and a build whose lines are members, read
    by the suite's admin."""

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
            Entry("lint", "lint warns", code=WARN)], members=True)

    def body(self, url: str) -> str:
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200, url)
        return response.get_data(as_text=True)

    def page(self, url: str) -> Element:
        return parse(self.body(url))

    def viewer(self) -> None:
        with self.client.session_transaction() as sess:
            sess["admin"] = False

    @staticmethod
    def at(page: Element) -> list[Element]:
        return [element for element in page.walk() if element.attrs.get("id") == "at"]


class MarkDoorTests(_Pages):
    """A mark of what handles a part is its door (decision 7): a link to its node's
    *Notes* tab at the block it marks, the mark alone on the kiosk."""

    def test_a_head_s_mark_opens_the_tab_at_its_block(self):
        _seen(self.tree, "/site/web/disk")
        page = self.page("/status")
        (mark,) = page.all("head-ack")
        self.assertEqual((mark.tag, mark.attrs.get("href")),
                         ("a", "/notes/site/web/disk?at=seen#at"))
        self.assertIn("data-door", mark.attrs)
        self.assertTrue(mark.attrs.get("title", "").startswith("Seen by ada"))

    def test_a_rule_s_head_mark_opens_the_tab_at_the_rule(self):
        tree = ruled(rule("web advises", "/site/web", CAP))
        app_module.status_tree = tree
        tree.upsert("/site/web/disk", ERROR, "disk 97 % full")
        (mark,) = self.page("/status").all("head-rule")
        self.assertEqual(mark.attrs.get("href"), "/notes/site/web?at=rule#at")

    def test_a_line_s_mark_opens_the_tab_at_its_block(self):
        _pin(self.tree, "/site/ci/build", "lint")
        _seen(self.tree, "/site/ci/build", "test")
        for url in ("/status", "/status/site/ci/build"):
            with self.subTest(url=url):
                page = self.page(url)
                self.assertEqual(
                    sorted(mark.attrs.get("href") for mark in page.all("line-mark")),
                    ["/notes/site/ci/build?reason=lint&at=maintenance#at",
                     "/notes/site/ci/build?reason=test&at=seen#at"])

    def test_a_click_on_a_head_s_mark_never_toggles_its_node(self):
        script = self.client.get("/static/js/tree.js").get_data(as_text=True)
        self.assertIn('+ "[data-door], .rule-block, "', script)

    def test_the_kiosk_draws_the_marks_alone(self):
        _seen(self.tree, "/site/web/disk")
        _pin(self.tree, "/site/ci/build", "lint")
        self.client.set_cookie("ls_prefs", "layout=kiosk")
        page = self.page("/status")
        for mark in page.all("head-ack") + page.all("line-mark"):
            with self.subTest(mark=mark.attrs.get("class")):
                self.assertEqual(mark.tag, "span")
                self.assertNotIn("href", mark.attrs)


class AtTests(_Pages):
    """The tab, asked at a block (decision 3): the page's one anchor there, `at`, its
    editor open for whoever may change it."""

    def test_at_the_node_s_pin(self):
        _pin(self.tree, "/site/web/disk")
        page = self.page("/notes/site/web/disk?at=maintenance")
        (block,) = self.at(page)
        self.assertTrue(block.has("is-at") and block.has("rule-block--node"))
        self.assertEqual(block.attrs.get("data-rule"), "maintenance")
        self.assertIn("open", block.one("rule-block__edit").attrs)

    def test_at_a_line_s_pin_and_a_line_s_seen(self):
        _pin(self.tree, "/site/ci/build", "lint")
        _seen(self.tree, "/site/ci/build", "test")
        for slug, job in (("lint", "maintenance"), ("test", SEEN)):
            with self.subTest(job=job):
                page = self.page(f"/notes/site/ci/build?reason={slug}&at={job}")
                (block,) = self.at(page)
                self.assertEqual(block.attrs.get("data-rule"), job)
                self.assertIn({"lint": "lint warns", "test": "test fails"}[slug],
                              block.text())
                self.assertIn("open", block.one("rule-block__edit").attrs)
                # every other block stands closed
                self.assertEqual(len([edit for edit in page.all("rule-block__edit")
                                      if "open" in edit.attrs]), 1)

    def test_at_a_rule_on_the_node_and_on_its_lines(self):
        tree = ruled(rule("web advises", "/site/web", CAP),
                     rule("lint heals", "/site/ci/build", HEAL, lines=["lint"]))
        app_module.status_tree = tree
        tree.upsert("/site/web/disk", ERROR, "disk 97 % full")
        tree.upsert("/site/ci/build", ERROR, [
            Entry("test", "test fails", code=ERROR),
            Entry("lint", "lint warns", code=WARN)], members=True)
        (block,) = self.at(self.page("/notes/site/web?at=rule"))
        self.assertEqual(block.attrs.get("data-rule-name"), "web advises")
        (block,) = self.at(self.page("/notes/site/ci/build?reason=lint&at=rule"))
        self.assertEqual(block.attrs.get("data-rule-name"), "lint heals")

    def test_a_viewer_is_taken_there_and_given_no_editor(self):
        _pin(self.tree, "/site/web/disk")
        self.viewer()
        (block,) = self.at(self.page("/notes/site/web/disk?at=maintenance"))
        self.assertEqual(block.all("rule-block__edit"), [])

    def test_nothing_is_marked_where_nothing_stands_or_nothing_is_asked(self):
        _pin(self.tree, "/site/web/disk")
        for query in ("", "?at=seen", "?at=nonsense", "?at=maintenance&reason=nope"):
            with self.subTest(query=query):
                self.assertEqual(self.at(self.page(f"/notes/site/web/disk{query}")), [])


class BeneathTests(_Pages):
    """The tab lists what stands beneath its node in every state, as many parts as its
    door says with the node's own and its lines' (decision 2)."""

    def test_a_branch_in_maintenance_lists_what_stands_beneath_it(self):
        _seen(self.tree, "/site/web/disk")
        _pin(self.tree, "/site/ci/build", "lint")
        _pin(self.tree, "/site")
        tab = self.page("/notes/site")
        # the door's number heads what stands: its own pin and the two beneath
        self.assertEqual(" ".join(tab.one("ls-tab__handled").text().split()),
                         "3 handled")
        beneath = tab.one("ls-tab__beneath")
        self.assertEqual([" ".join(job.text().split())
                          for job in beneath.all("why-card__job")],
                         ["In maintenance", "Accepted"])
        self.assertEqual(len(beneath.all(tag="li")), 2)
        # its own pin stands above, and the door counts it with the two beneath
        self.assertEqual(len([block for block in tab.one("ls-tab__stands")
                              .all("rule-block") if block.has("rule-block--node")]), 1)
        doors = [link for link in self.page("/status").walk()
                 if link.attrs.get("href") == "/notes/site"
                 and link.attrs.get("data-control") == "door"]
        self.assertEqual([door.attrs.get("title") for door in doors],
                         ["Handle it — 3 handled: 1 node in maintenance, "
                          "1 line in maintenance, 1 seen"])

    def test_a_part_two_things_handle_is_listed_once_with_both(self):
        # a node's own seen beside its pin, which decides nothing under it
        _seen(self.tree, "/site/web/disk")
        _pin(self.tree, "/site/web/disk")
        beneath = self.page("/notes/site").one("ls-tab__beneath")
        (row,) = beneath.all(tag="li")
        said = " ".join(row.text().split())
        self.assertTrue(said.startswith("web/disk, reads error · by ada until"), said)
        self.assertIn("— and · seen by ada at error · until it changes", said)


class DoorOfTests(TestCase):
    """The template's `door_of` reads what the route counted, and counts the node
    itself where the route counted nothing."""

    def test_it_reads_the_route_s_count_and_else_counts_the_node(self):
        tree = StatusTree()
        tree.upsert("/a/b", ERROR, "x")
        _pin(tree, "/a/b")
        node = tree.snapshot("/a")
        assert node is not None
        with app_module.app.test_request_context("/status"):
            self.assertEqual(app_module._door_of(node).by_job, {"node": 1})
            self.assertIn("/a/b", g.doors)
        with app_module.app.test_request_context("/status"):
            g.doors = {"/a": DoorCount({SEEN: 7})}
            self.assertEqual(app_module._door_of(node).count, 7)
