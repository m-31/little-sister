"""A node's handbook on a tab of its own (ADR-0133 decision 3).

The *Handbook* tab stands on every view of a node that has a handbook, after Status,
Series and History and before Copy, and on no view of one that has none. Its page
stands in the node's band as the node's other views do: crumbs that open each
ancestor's handbook where it has one, the tabs, and beneath them the handbook as the
node's own text — a status it names drawn as its sign, its headings anchored as
GitHub anchors them. The hover card says that a node has one, by the tab's address.
What states a handbook and how a file is read is ``tests/test_handbooks.py``'s.
"""
from __future__ import annotations

import os
import re
from unittest import TestCase

os.environ.setdefault("SECRET_KEY", "test-key")

from little_sister import app as app_module
from little_sister.status import StatusCode
from little_sister.tree import StatusTree
from tests.page_tree import Element, parse
from tests.test_copy_tab import crumbs, tabs

OK, ERROR, UNDEFINED = StatusCode.OK, StatusCode.ERROR, StatusCode.UNDEFINED

SERVERS = ("# Servers\n\n[Sign in](#sign-in) first.\n\n## Sign in\n\nThrough the "
           "bastion.\n\n## When it fails\n\n### {error}: the disk\n\nReplace it.\n\n"
           "## Sign in\n")


class _Pages(TestCase):
    def setUp(self) -> None:
        app_module.app.config["TESTING"] = True
        self._original = app_module.status_tree
        self.addCleanup(setattr, app_module, "status_tree", self._original)
        self.tree = StatusTree()
        app_module.status_tree = self.tree
        self.client = app_module.app.test_client()
        self.client.post("/login", data={"username": "pan", "password": "12345678"})
        self.tree.upsert("/servers", UNDEFINED, None, frequency_seconds=120)
        self.tree.upsert("/servers/web01/disk", ERROR, "97 % used")
        self.tree.upsert("/servers/web01/cpu", OK, "9 % busy")
        self.tree.set_handbook("/servers", SERVERS)
        self.tree.set_handbook("/servers/web01/disk", "Replace the drive.")

    def page(self, url: str, status: int = 200) -> Element:
        response = self.client.get(url)
        self.assertEqual(response.status_code, status, url)
        return parse(response.get_data(as_text=True))


class TheTabTests(_Pages):
    def test_every_view_of_a_node_that_has_one_carries_it_before_copy(self):
        for path in ("/servers", "/servers/web01/disk"):
            for view in ("status", "history", "handbook", "copy"):
                with self.subTest(view=view, path=path):
                    self.assertEqual(tabs(self.page(f"/{view}{path}")), [
                        ("Status", f"/status{path}", view == "status"),
                        ("History", f"/history{path}", view == "history"),
                        ("Notes", f"/notes{path}", False),
                        ("Handbook", f"/handbook{path}", view == "handbook"),
                        ("Copy", f"/copy{path}", view == "copy")])

    def test_no_view_of_a_node_that_has_none_carries_it(self):
        for url in ("/status/servers/web01", "/status/servers/web01/cpu",
                    "/history/servers/web01/cpu", "/copy/servers/web01", "/status"):
            with self.subTest(url=url):
                self.assertNotIn("Handbook",
                                 [word for word, _, _ in tabs(self.page(url))])

    def test_the_roots_stands_on_its_views_where_it_has_one(self):
        self.tree.set_handbook("", "What this instance watches, and who runs it.")
        self.assertEqual(tabs(self.page("/handbook")), [
            ("Status", "/status", False), ("Handbook", "/handbook", True),
            ("Copy", "/copy", False)])
        self.assertEqual(tabs(self.page("/status"))[1],
                         ("Handbook", "/handbook", False))


class ThePageTests(_Pages):
    def test_it_is_the_nodes_own_text_with_github_s_anchors(self):
        page = self.page("/handbook/servers")
        article = page.one("ls-handbook", tag="article")
        self.assertEqual(
            [(found.tag, found.attrs.get("id")) for found in article.all()
             if re.fullmatch(r"h[1-6]", found.tag)],
            [("h1", "servers"), ("h2", "sign-in"), ("h2", "when-it-fails"),
             ("h3", "error-the-disk"), ("h2", "sign-in-1")])
        # a link into a section stays in the page
        link = article.one(tag="a")
        self.assertEqual((link.attrs["href"], link.attrs.get("target")),
                         ("#sign-in", None))
        # a status it names is its sign, whose cue the page holds the shape of
        self.assertEqual([found.text() for found in article.all("ls-sign")],
                         ["error"])
        page.with_id("ls-cue-error")

    def test_its_crumbs_open_each_ancestors_handbook_where_it_has_one(self):
        self.assertEqual(crumbs(self.page("/handbook/servers/web01/disk")), [
            ("nodes", "/status"), ("servers", "/handbook/servers"),
            ("web01", "/status/servers/web01"), ("disk", None)])
        self.tree.set_handbook("", "The estate.")
        self.assertEqual(crumbs(self.page("/handbook/servers"))[0],
                         ("nodes", "/handbook"))

    def test_a_node_that_has_none_answers_404_and_says_so(self):
        page = self.page("/handbook/servers/web01", status=404)
        self.assertEqual(page.all("ls-handbook"), [])
        said = page.one("ls-handbook__none").text()
        self.assertIn("No handbook is written for /servers/web01", said)
        self.assertEqual([word for word, _, _ in tabs(page)],
                         ["Status", "History", "Notes", "Copy"])

    def test_a_path_no_node_stands_at_is_answered_as_its_other_addresses_are(self):
        page = self.page("/handbook/gone/away", status=404)
        self.assertEqual(len(page.all("ls-no-node")), 1)
        self.assertEqual(page.all("ls-views"), [])

    def test_it_is_behind_the_gate(self):
        self.client.get("/logout")
        response = self.client.get("/handbook/servers")
        self.assertEqual(response.status_code, 302)
        self.assertIn("/login", response.headers["Location"])


class TheHoverCardTests(_Pages):
    def test_the_map_says_that_a_node_has_one_by_its_address(self):
        self.tree.set_about("/servers/web01/disk", "The data volume.")
        with app_module.app.test_request_context():
            meta = app_module._node_meta_map(self.tree.snapshot(""))
        # a node with a handbook and nothing else to say has a card, which links it
        self.assertEqual(meta["/servers"], {"handbook": "/handbook/servers"})
        self.assertEqual(meta["/servers/web01/disk"]["handbook"],
                         "/handbook/servers/web01/disk")
        self.assertNotIn("/servers/web01/cpu", meta)
        # the handbook itself rides in no fragment
        self.assertNotIn("bastion", repr(meta))
