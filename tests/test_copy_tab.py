"""Copy as a view of its node (ADR-0115 decision 7, ADR-0097 decision 3).

Every view of every node carries a *Copy* tab, the root's leading to the tree's
document. And the Copy page stands in the node's band as its other views do: the
breadcrumb, whose crumbs open the Copy page of each ancestor; the tabs, with *Copy* the
current one and *Status* the way back; and beneath them the sentence that says which
of the four documents the page holds. The tab is the one way to a node's document: no
Status page carries the two buttons, or makes a document.

``tests/test_series_view.py`` holds the same tabs on a node that has a Series view.
"""
from __future__ import annotations

import os
from unittest import TestCase, mock

os.environ.setdefault("SECRET_KEY", "test-key")

from little_sister import app as app_module
from little_sister.reasons import Entry
from little_sister.status import StatusCode
from little_sister.tree import StatusTree
from tests.page_tree import Element, parse

OK, WARN, ERROR, UNDEFINED = (StatusCode.OK, StatusCode.WARN, StatusCode.ERROR,
                              StatusCode.UNDEFINED)


def tabs(page: Element) -> list[tuple[str, str, bool]]:
    """A page's view tabs: each one's word, where it leads, and whether it is the
    view this page is."""
    return [(tab.text(), tab.attrs["href"], tab.attrs.get("aria-current") == "page")
            for tab in page.one("ls-views").all("ls-views__tab")]


def crumbs(page: Element) -> list[tuple[str, str | None]]:
    """The breadcrumb: each crumb's name and where it leads — nowhere, for the node
    the page is about."""
    found: list[tuple[str, str | None]] = []
    for part in page.one("ls-crumbs").children:
        if isinstance(part, Element) and part.text() != "/":    # not a separator
            found.append((part.text(), part.attrs.get("href")))
    return found


def said(page: Element) -> str:
    """What the page says of its document: the sentence beneath its band."""
    band = page.one("ls-band")
    assert band.parent is not None
    after = band.parent.children[band.parent.children.index(band) + 1:]
    return next(part for part in after
                if isinstance(part, Element) and part.tag == "p").text()


class _Pages(TestCase):
    def setUp(self) -> None:
        app_module.app.config["TESTING"] = True
        self._original = app_module.status_tree
        self.addCleanup(setattr, app_module, "status_tree", self._original)
        self.tree = StatusTree()
        app_module.status_tree = self.tree
        self.client = app_module.app.test_client()
        self.client.post("/login", data={"username": "pan", "password": "12345678"})
        self.tree.upsert("/nexus", UNDEFINED, None, frequency_seconds=120)
        self.tree.upsert("/nexus/cpu", OK, "9 % busy")
        self.tree.upsert("/nexus/disk", ERROR, "97 % used")
        self.tree.upsert("/ci/reviews", WARN,
                         [Entry("pr-1", "PR one waits", WARN)], members=True)

    def page(self, url: str, status: int = 200) -> Element:
        response = self.client.get(url)
        self.assertEqual(response.status_code, status, url)
        return parse(response.get_data(as_text=True))


class TheTabTests(_Pages):
    """A tab on every view of every node, and on the root."""

    def test_a_leafs_and_a_branchs_views_carry_it(self):
        for path in ("/nexus/disk", "/nexus"):
            for view in ("status", "history"):
                with self.subTest(view=view, path=path):
                    found = tabs(self.page(f"/{view}{path}"))
                    self.assertEqual([word for word, _, _ in found],
                                     ["Status", "History", "Copy"])
                    self.assertEqual(found[-1], ("Copy", f"/copy{path}", False))

    def test_the_roots_leads_to_the_trees_document(self):
        self.assertEqual(tabs(self.page("/status")),
                         [("Status", "/status", True), ("Copy", "/copy", False)])


class ThePageTests(_Pages):
    """The Copy page stands in its node's band, as the node's other views do."""

    def test_it_takes_the_nodes_title_and_tabs(self):
        for path in ("/nexus/disk", "/nexus"):
            with self.subTest(path=path):
                page = self.page(f"/copy{path}")
                # the band's title is the page's heading, and the only one
                heading = page.one(tag="h1")
                self.assertTrue(heading.has("ls-band__title"), heading)
                self.assertTrue(page.one("ls-crumbs").within(heading))
                # Copy is the view this is, and Status the way back to the node
                self.assertEqual(tabs(page), [
                    ("Status", f"/status{path}", False),
                    ("History", f"/history{path}", False),
                    ("Copy", f"/copy{path}", True)])

    def test_its_crumbs_open_the_copy_page_of_each_ancestor(self):
        self.assertEqual(crumbs(self.page("/copy/nexus/disk")), [
            ("nodes", "/copy"), ("nexus", "/copy/nexus"), ("disk", None)])

    def test_the_trees_page_stands_in_the_roots_band(self):
        page = self.page("/copy")
        self.assertEqual(crumbs(page), [("nodes", None)])
        self.assertEqual(tabs(page),
                         [("Status", "/status", False), ("Copy", "/copy", True)])

    def test_the_trees_page_says_what_the_root_is_as_the_overview_does(self):
        self.tree.set_title("", "The whole estate")
        self.tree.set_about("", "Everything this instance watches.")
        for url in ("/status", "/copy"):
            with self.subTest(url=url):
                band = self.page(url).one("ls-band")
                self.assertEqual(band.one("node-title--header").text(),
                                 "The whole estate")
                self.assertEqual(band.one("ls-band__about-body").text(),
                                 "Everything this instance watches.")

    def test_a_lines_page_stands_in_its_nodes_band(self):
        page = self.page("/copy/ci/reviews?reason=pr-1")
        self.assertEqual(crumbs(page), [
            ("nodes", "/copy"), ("ci", "/copy/ci"), ("reviews", None)])
        # the tab is the node's document: a line has no view of its own
        self.assertEqual(tabs(page), [
            ("Status", "/status/ci/reviews", False),
            ("History", "/history/ci/reviews", False),
            ("Copy", "/copy/ci/reviews", True)])

    def test_it_says_which_document_it_holds_beneath_the_band(self):
        for url, scope in (
                ("/copy", "A compact incident snapshot: every status that needs "
                          "attention, with just enough of the tree to locate it."),
                ("/copy/nexus", "A branch: what it shows, what needs attention "
                                "beneath it, and what its own run found."),
                ("/copy/nexus/disk", "One node: what its check reported, since when, "
                                     "and what its run found and ran with."),
                ("/copy/ci/reviews?reason=pr-1", "One line of this node, and where "
                                                 "it came from.")):
            with self.subTest(url=url):
                self.assertEqual(said(self.page(url)), scope)

    def test_a_path_no_node_stands_at_is_answered_as_its_other_addresses_are(self):
        # ADR-0116: one page for every address of such a path, and no tabs, there
        # being no node to have views; its crumbs open what stands above it
        page = self.page("/copy/gone/away", status=404)
        self.assertEqual(len(page.all("ls-no-node")), 1)
        self.assertEqual(page.all("ls-views"), [])
        self.assertEqual(crumbs(page), [
            ("nodes", "/status"), ("gone", "/status/gone"), ("away", None)])
        self.assertNotIn("No such node", page.text())
        self.assertEqual([part for part in page.walk()
                          if "data-copy-format" in part.attrs], [])

    def test_a_line_no_longer_reported_keeps_its_nodes_band(self):
        page = self.page("/copy/ci/reviews?reason=merged", status=404)
        self.assertEqual(crumbs(page)[-1], ("reviews", None))
        self.assertEqual(tabs(page)[-1], ("Copy", "/copy/ci/reviews", True))
        self.assertIn("That line is no longer reported", page.text())

    def test_a_wall_display_has_no_band_and_the_page_still_hands_over(self):
        # the kiosk draws no band on any page; the document names its node itself
        self.client.set_cookie("ls_prefs", "layout=kiosk")
        page = self.page("/copy/nexus/disk")
        self.assertEqual(page.all("ls-band"), [])
        self.assertEqual(len([part for part in page.walk()
                              if "data-copy-format" in part.attrs]), 2)
        document = page.with_id("ls-copy-source").source()
        self.assertTrue(document.startswith("## disk ⛔"), document[:40])


class TheOneWayTests(_Pages):
    """The tab is the one way to a node's document: a leaf's page carried two buttons
    that copied its document in place, and carries them no longer."""

    STATUS_PAGES = ("/status/nexus/disk", "/status/ci/reviews", "/status/nexus",
                    "/status")

    def test_no_status_page_carries_the_buttons_or_a_document(self):
        for url in self.STATUS_PAGES:
            with self.subTest(url=url):
                page = self.page(url)
                self.assertEqual([part for part in page.walk()
                                  if "data-copy-format" in part.attrs], [])
                # neither the source a hand selects nor the payload a button writes
                self.assertEqual([part.attrs["id"] for part in page.walk()
                                  if part.attrs.get("id", "").startswith("ls-copy")],
                                 [])
                self.assertEqual([part.attrs["src"] for part in page.all(tag="script")
                                  if "js/copy.js" in part.attrs.get("src", "")], [])

    def test_a_status_page_makes_no_document(self):
        with mock.patch.object(app_module, "_node_markdown",
                               wraps=app_module._node_markdown) as made:
            for url in self.STATUS_PAGES:
                self.page(url)
            made.assert_not_called()
            # its Copy page does, when it is asked for
            self.page("/copy/nexus/disk")
            made.assert_called_once()

    def test_a_leafs_tab_leads_to_its_document_and_the_two_buttons(self):
        word, href, _ = tabs(self.page("/status/nexus/disk"))[-1]
        self.assertEqual((word, href), ("Copy", "/copy/nexus/disk"))
        page = self.page(href)
        self.assertEqual([part.attrs["data-copy-format"] for part in page.walk()
                          if "data-copy-format" in part.attrs], ["markdown", "rich"])
        document = page.with_id("ls-copy-source").source()
        self.assertTrue(document.startswith("## disk ⛔"), document[:40])
        self.assertEqual([part.attrs["src"].split("/")[-1].split("?")[0]
                          for part in page.all(tag="script")
                          if "js/copy.js" in part.attrs.get("src", "")], ["copy.js"])

    def test_the_copy_page_shows_its_document_before_it_is_copied(self):
        for url, heading in (("/copy", "little-sister status ⛔"),
                             ("/copy/nexus", "nexus ⛔"),
                             ("/copy/nexus/disk", "disk ⛔"),
                             ("/copy/ci/reviews?reason=pr-1", "reviews ⚠️")):
            with self.subTest(url=url):
                preview = self.page(url).one("ls-copy__preview")
                self.assertEqual(preview.one(tag="h2").text(), heading)
