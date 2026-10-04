"""A wall the filters emptied says what they hid, in the switches' own words.

With *hide ok* on, the wall is the list of problems, and on a good day it is empty.
It said *No checks reporting yet match the current filters* then — as if nothing
reported, at the moment everything did and was well — and a branch's page said *No
checks match the current filters*. Each now counts what the filters hid of the nodes
the page shows: the overview's top-level nodes, a branch's nodes beneath it.
"""
from __future__ import annotations

import html
import re
from unittest import TestCase

from little_sister import app as app_module
from little_sister.engine import Engine
from little_sister.status import StatusCode
from little_sister.tree import StatusTree

OK, ERROR, UNDEFINED = StatusCode.OK, StatusCode.ERROR, StatusCode.UNDEFINED


def _words(markup: str) -> str:
    return " ".join(html.unescape(re.sub(r"<[^>]+>", " ", markup)).split())


class FilteredWallTests(TestCase):
    """What the overview and a branch's page say when hide ok and hide idle leave no
    node to show, and that they say nothing new when one is left."""

    def setUp(self) -> None:
        self._saved = (app_module.status_tree, app_module.engine)
        self.addCleanup(self._restore)
        self.tree = StatusTree()
        app_module.status_tree = self.tree
        app_module.engine = Engine([], self.tree)
        self.client = app_module.app.test_client()
        self.client.post("/login", data={"username": "pan", "password": "12345678"})

    def _restore(self) -> None:
        app_module.status_tree, app_module.engine = self._saved

    def _says(self, url: str) -> list[str]:
        """The page and its poll, the two places the grid is rendered."""
        bodies = []
        for each in (url, f"{url}&fragment=1"):
            response = self.client.get(each)
            self.assertEqual(response.status_code, 200)
            bodies.append(response.get_data(as_text=True))
        return bodies

    def _estate(self, **roots: StatusCode) -> None:
        for name, code in roots.items():
            self.tree.upsert(f"/{name}/aspect", code)

    def assertSays(self, url: str, sentence: str) -> None:
        for body in self._says(url):
            with self.subTest(url=url):
                self.assertIn(f" {sentence} ", f" {_words(body)} ")
                self.assertNotIn("match the current filters", body)
                self.assertNotIn("No checks reporting yet", body)

    # --- the overview ---------------------------------------------------------------

    def test_hide_ok_with_nothing_wrong_says_every_node_is_ok(self) -> None:
        self._estate(aws=OK, dns=OK, web=OK)
        self.assertSays("/status?view=1&hide_ok=1", "All 3 nodes are ok.")

    def test_one_node_is_the_only_one(self) -> None:
        self._estate(web=OK)
        self.assertSays("/status?view=1&hide_ok=1", "The only node is ok.")

    def test_hide_idle_with_nothing_reported_says_every_node_is_idle(self) -> None:
        self._estate(lab=UNDEFINED, spare=UNDEFINED)
        self.assertSays("/status?view=1&hide_idle=1", "All 2 nodes are idle.")
        self.tree = StatusTree()
        app_module.status_tree = self.tree
        self._estate(lab=UNDEFINED)
        self.assertSays("/status?view=1&hide_idle=1", "The only node is idle.")

    def test_both_switches_count_both(self) -> None:
        self._estate(aws=OK, web=OK, lab=UNDEFINED)
        self.assertSays("/status?view=1&hide_ok=1&hide_idle=1",
                        "2 nodes are ok and 1 is idle.")
        self.tree = StatusTree()
        app_module.status_tree = self.tree
        self._estate(web=OK, lab=UNDEFINED)
        self.assertSays("/status?view=1&hide_ok=1&hide_idle=1",
                        "1 node is ok and 1 is idle.")

    def test_a_filter_that_leaves_a_problem_shows_it_and_counts_nothing(self) -> None:
        self._estate(aws=OK, web=ERROR)
        for body in self._says("/status?view=1&hide_ok=1"):
            self.assertIn('href="/status/web"', body)
            self.assertNotIn("are ok.", body)
            self.assertNotIn("is ok.", body)

    def test_an_empty_tree_still_says_no_check_reports(self) -> None:
        for url in ("/status?view=1", "/status?view=1&hide_ok=1&hide_idle=1"):
            for body in self._says(url):
                with self.subTest(url=url):
                    self.assertIn("No checks reporting yet.", body)
                    self.assertNotIn("match the current filters", body)

    # --- a branch's page ------------------------------------------------------------

    def test_a_branch_says_it_of_the_nodes_beneath_it(self) -> None:
        for account in ("prod", "staging"):
            self.tree.upsert(f"/aws/{account}", OK)
        self.assertSays("/status/aws?view=1&hide_ok=1",
                        "All 2 nodes beneath aws are ok.")

    def test_a_failing_branch_whose_children_are_well_says_so(self) -> None:
        # The node's own error stands in its head; the sentence says the problem is
        # not beneath it.
        self.tree.upsert("/aws/prod", OK)
        self.tree.upsert("/aws", ERROR, "credentials expired")
        bodies = self._says("/status/aws?view=1&hide_ok=1")
        self.assertSays("/status/aws?view=1&hide_ok=1",
                        "The only node beneath aws is ok.")
        for body in bodies:
            self.assertIn("credentials expired", body)
