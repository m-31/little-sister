"""A path no node stands at has one page, and it says what is known of the path
(ADR-0116), read against the record's sentences.

A queue hands back a node for each job name it lists and says that these are all of
them, so a job name it stops listing is removed. ``export`` is removed here; ``import``
stays; and ``nope`` is a path nothing ever stood at.
"""
from __future__ import annotations

import html
import os
import re
from unittest import TestCase

os.environ.setdefault("SECRET_KEY", "test-key")

from little_sister import app as app_module
from little_sister.engine import Engine
from little_sister.tree import CAUSE_REMOVED, StatusTree
from tests.test_pruning import _pin, _Queue

GONE = "batch/export"
#: The views of a node, each at its own address.
VIEWS = ("/status/", "/series/", "/history/", "/copy/")

_PAGE = re.compile(
    r'<section class="ls-no-node"[^>]*>(.*?)</section>\s*<!-- /no-node -->', re.S)


def _words(markup: str) -> str:
    said = " ".join(html.unescape(re.sub(r"<[^>]+>", " ", markup)).split())
    return re.sub(r" ([,.:])", r"\1", said)


class _Estate(TestCase):
    def setUp(self) -> None:
        app_module.app.config["TESTING"] = True
        saved = (app_module.status_tree, app_module.engine)
        self.addCleanup(lambda: setattr(app_module, "status_tree", saved[0]))
        self.addCleanup(lambda: setattr(app_module, "engine", saved[1]))
        self.tree = StatusTree()
        app_module.status_tree = self.tree
        self.check = _Queue(path="/batch", subject="queue/live", series_keep=5)
        self.check.jobs = {"import": "succeeded", "export": "failed"}
        app_module.engine = Engine([self.check], self.tree)
        app_module.engine.run_once()
        self.client = app_module.app.test_client()
        self.client.post("/login",
                         data={"username": "pan", "password": "12345678"})

    def _remove(self) -> None:
        del self.check.jobs["export"]
        assert app_module.engine is not None
        app_module.engine.run_once()

    def _said(self, url: str, status: int = 404) -> str:
        """The page a path with no node is answered with: its words."""
        response = self.client.get(url)
        self.assertEqual(response.status_code, status, url)
        found = _PAGE.search(response.get_data(as_text=True))
        assert found is not None, url
        return found.group(1)


class OnePageTests(_Estate):
    """Decision 1: one page, whichever view was asked for, and it is a 404."""

    def test_each_view_of_a_removed_node_answers_404_with_the_same_page(self) -> None:
        self._remove()
        pages = [self._said(f"{view}{GONE}") for view in VIEWS]
        for view, page in zip(VIEWS[1:], pages[1:], strict=True):
            with self.subTest(view=view):
                self.assertEqual(page, pages[0])
        self.assertIn("batch/export", _words(pages[0]))

    def test_a_line_asked_of_a_path_with_no_node_is_answered_the_same(self) -> None:
        # there is no node to have lines: the address of one is answered with the
        # path's page, and not with a sentence about a line
        self._remove()
        self.assertEqual(self._said(f"/copy/{GONE}?reason=newest"),
                         self._said(f"/status/{GONE}"))

    def test_a_path_nothing_stood_at_is_answered_the_same_way(self) -> None:
        for view in VIEWS:
            with self.subTest(view=view):
                self.assertIn("nope", _words(self._said(f"{view}nope")))

    def test_it_stands_under_the_breadcrumb_and_has_no_view_tabs(self) -> None:
        self._remove()
        for view in VIEWS:
            body = self.client.get(f"{view}{GONE}").get_data(as_text=True)
            with self.subTest(view=view):
                self.assertIn('class="ls-crumbs"', body)
                self.assertIn('href="/status/batch"', body)
                self.assertNotIn("ls-views__tab", body)
                # nor the wall's filters, which filter a node's children
                self.assertNotIn('id="hide_ok"', body)

    def test_a_node_that_stands_is_answered_as_it_was(self) -> None:
        self._remove()
        for view in VIEWS:
            with self.subTest(view=view):
                response = self.client.get(f"{view}batch/import")
                self.assertEqual(response.status_code, 200)
                self.assertNotIn("ls-no-node", response.get_data(as_text=True))

    def test_a_node_that_returns_has_its_pages_again(self) -> None:
        self._remove()
        self.assertEqual(self.client.get(f"/status/{GONE}").status_code, 404)
        self.check.jobs["export"] = "succeeded"
        assert app_module.engine is not None
        app_module.engine.run_once()
        self.assertEqual(self.client.get(f"/status/{GONE}").status_code, 200)

    def test_the_json_read_is_as_it_was(self) -> None:
        self._remove()
        response = self.client.get(
            f"/status/{GONE}", headers={"Accept": "application/json",
                                        "Authorization": "Bearer nope"})
        self.assertEqual(response.status_code, 401)


class RefreshTests(_Estate):
    """Decision 2: the part an open page's refresh asks for is answered 200."""

    def test_the_refresh_of_an_open_page_is_answered_and_says_the_same(self) -> None:
        self._remove()
        response = self.client.get(f"/status/{GONE}", query_string={"fragment": "1"})
        self.assertEqual(response.status_code, 200)
        # it is a fragment the page's script takes: it dates itself
        self.assertTrue(response.headers.get("X-Rendered-At"))
        found = _PAGE.search(response.get_data(as_text=True))
        assert found is not None
        self.assertEqual(found.group(1), self._said(f"/status/{GONE}"))

    def test_the_refresh_of_a_path_nothing_stood_at_is_answered_too(self) -> None:
        response = self.client.get("/status/nope", query_string={"fragment": "1"})
        self.assertEqual(response.status_code, 200)
        self.assertIn("ls-no-node", response.get_data(as_text=True))


class LostChildrenTests(_Estate):
    """A branch that loses its children while its page polls gets a fragment, not
    a leaf's page (ADR-0127 decision 10): the page's script reads a page without
    `X-Rendered-At` as a lost session. The next load of the address is the leaf's
    page, as it was."""

    def _lose_them(self) -> None:
        self.check.jobs = {}
        assert app_module.engine is not None
        app_module.engine.run_once()

    def test_the_refresh_of_a_branch_whose_children_left_is_a_fragment(self) -> None:
        page = self.client.get("/status/batch")
        self.assertEqual(page.status_code, 200)
        self.assertIn('id="status-grid"', page.get_data(as_text=True))
        self._lose_them()
        self.assertEqual(len(self.tree.snapshot("/batch").children), 0)
        response = self.client.get("/status/batch", query_string={"fragment": "1"})
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.headers.get("X-Rendered-At"))
        body = response.get_data(as_text=True)
        self.assertNotIn("<html", body)
        self.assertNotIn("maintenance-edit.js", body)
        # it says what stands where the children stood, and not that nothing has
        # reported yet
        self.assertIn("Nothing stands beneath batch now.", body)
        self.assertNotIn("No checks reporting yet.", body)

    def test_a_load_of_the_address_is_the_leafs_page_as_it_was(self) -> None:
        self._lose_them()
        page = self.client.get("/status/batch")
        self.assertEqual(page.status_code, 200)
        body = page.get_data(as_text=True)
        self.assertNotIn('id="status-grid"', body)
        self.assertIn("maintenance-edit.js", body)
        self.assertNotIn("Nothing stands beneath", body)

    def test_the_wall_and_a_branch_with_children_say_nothing_of_it(self) -> None:
        for url in ("/status", "/status/batch"):
            with self.subTest(url=url):
                body = self.client.get(url, query_string={"fragment": "1"}
                                       ).get_data(as_text=True)
                self.assertNotIn("Nothing stands beneath", body)
                self.assertNotIn("No checks reporting yet.", body)


class WhatIsKnownTests(_Estate):
    """Decision 3: what the log and the pins know, and the nearest node above."""

    def test_a_removed_node_is_said_to_be_removed_with_when_and_why(self) -> None:
        self._remove()
        removal = [event for event in self.tree.recent_events()
                   if event.path == "/batch/export" and event.cause == CAUSE_REMOVED]
        self.assertEqual(len(removal), 1)
        page = self._said(f"/status/{GONE}")
        said = _words(page)
        self.assertIn("No node stands at batch/export.", said)
        self.assertRegex(said, r"Removed \d{4}-\d\d-\d\d \d\d:\d\d:\d\d: no longer "
                               r"reported by its check\.")
        when = app_module._format_local(removal[0].timestamp)
        self.assertIn(f"Removed {when}:", said)
        self.assertIn('<a href="/events?under=/batch/export">Events</a>', page)

    def test_a_path_nothing_is_recorded_of_says_so_and_links_no_rows(self) -> None:
        page = self._said("/status/nope")
        said = _words(page)
        self.assertIn("No node stands at nope.", said)
        self.assertIn("Nothing is recorded of it", said)
        self.assertNotIn("Removed", said)
        self.assertNotIn("/events", page)

    def test_it_names_the_nearest_node_above_that_stands(self) -> None:
        self._remove()
        for path in (GONE, f"{GONE}/eu/shard-3"):
            page = self._said(f"/status/{path}")
            with self.subTest(path=path):
                self.assertIn('<a href="/status/batch">batch</a>', page)
                self.assertIn('<a href="/history/batch">History</a>', page)

    def test_it_says_where_kept_readings_are_only_of_a_removal_it_knows(
            self) -> None:
        kept = ("Readings kept of a subject that was removed are listed on its "
                "History page")
        # a path nothing is recorded of, beside a node that stands
        self.assertNotIn(kept, _words(self._said("/status/batch/nope")))
        self._remove()
        self.assertIn(kept, _words(self._said(f"/status/{GONE}")))
        # a path beneath the removed node has no removal of its own in the log
        self.assertNotIn(kept, _words(self._said(f"/status/{GONE}/eu/shard-3")))

    def test_above_a_path_at_the_first_level_is_the_wall(self) -> None:
        page = self._said("/status/nope")
        self.assertIn('<a href="/status">nodes</a>', page)
        self.assertNotIn("/history/", page)

    def test_a_pin_held_against_it_is_stated_and_an_admin_changes_it_there(
            self) -> None:
        _pin(self.tree, "/batch/export", "being moved to the new queue")
        self._remove()
        page = self._said(f"/status/{GONE}")
        said = _words(page)
        self.assertIn("being moved to the new queue", said)
        self.assertIn("when it is reported", said)
        self.assertIn("maintenance-editor-form", page)
        self.assertRegex(page, r"<button[^>]*>Clear<")

    def test_clearing_the_pin_there_comes_back_to_the_page_without_it(self) -> None:
        entry = _pin(self.tree, "/batch/export", "being moved to the new queue")
        self._remove()
        page = self._said(f"/status/{GONE}")
        self.assertIn(f'name="next" value="/status/{GONE}"', page)
        cleared = self.client.post("/maintenance", data={
            "path": "/batch/export", "action": "clear", "set_at": entry.token,
            "next": f"/status/{GONE}"})
        self.assertEqual(cleared.status_code, 302)
        self.assertTrue(cleared.headers["Location"].endswith(f"/status/{GONE}"))
        self.assertNotIn("rule-block", self._said(f"/status/{GONE}"))

    def test_a_pin_beneath_it_is_stated_under_its_own_path(self) -> None:
        _pin(self.tree, "/batch/export", "the job is being moved")
        _pin(self.tree, "/batch/export/eu", "the region is closed")
        self._remove()
        page = self._said(f"/status/{GONE}")
        said = _words(page)
        self.assertIn("the job is being moved", said)
        self.assertIn("the region is closed", said)
        # the path's own pin needs no heading; the one beneath is under its path
        self.assertEqual(re.findall(r'<h2 class="pin-node__path">([^<]*)</h2>', page),
                         ["/batch/export/eu"])
        self.assertLess(said.index("the job is being moved"),
                        said.index("/batch/export/eu"))
        # two editors, and their fields do not share an id
        ids = re.findall(r' id="([^"]+)"', page)
        self.assertEqual(len(ids), len(set(ids)))

    def test_a_pin_above_it_or_beside_it_is_not_its_own(self) -> None:
        _pin(self.tree, "/batch/export", "the job is being moved")
        _pin(self.tree, "/batch/exporter", "another job")
        self._remove()
        beneath = _words(self._said(f"/status/{GONE}/eu"))
        self.assertNotIn("the job is being moved", beneath)
        self.assertNotIn("another job", _words(self._said(f"/status/{GONE}")))
        self.assertNotIn("the job is being moved",
                         self.client.get("/status/batch").get_data(as_text=True))

    def test_a_viewer_reads_the_pin_without_buttons(self) -> None:
        _pin(self.tree, "/batch/export", "being moved to the new queue")
        self._remove()
        with self.client.session_transaction() as sess:
            sess["username"] = "viewer"
            sess["firstname"] = "Vera"
            sess["admin"] = False
        response = self.client.get(f"/status/{GONE}")
        self.assertEqual(response.status_code, 404)
        body = response.get_data(as_text=True)
        self.assertIn("being moved to the new queue", body)
        self.assertNotIn("maintenance-editor-form", body)

    def test_a_path_with_no_pin_states_none(self) -> None:
        self._remove()
        self.assertNotIn("rule-block", self._said(f"/status/{GONE}"))
