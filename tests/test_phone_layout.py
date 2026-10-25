"""A page says what width it is laid out at, and is no wider (ADR-0105).

Two things the live review found (backlog #89's B6 and B8), which are one thing:

* No document declared its viewport, so a phone laid every page out at its
  980-pixel fallback and scaled it to the screen. None of the narrow layouts was
  ever reached on a phone.
* At a phone's width pages were wider than the screen, so the whole page scrolled
  sideways, its bar and rail with it: by the filters in the band of the Status
  pages, which did not wrap; by the tables of Events, System and — over an estate
  with long reasons — History; by the trail of a node with a deep path, which was
  kept on one line; and by a name or a word with nowhere to break.

This file holds what a response and the sources can show: the declaration, a box
around every table of every template, and that nothing keeps the band's filters,
its trail or the wall's strip on one line, or a name from breaking. What a phone
then makes of it is Chromium's to say, emulating one
(`tests/test_phone_browser.py`).
"""
from __future__ import annotations

import os
from pathlib import Path
from unittest import TestCase

os.environ.setdefault("SECRET_KEY", "test-key")

from little_sister import app as app_module
from little_sister.status import StatusCode
from tests.page_tree import Element, css_rule, parse
from tests.test_series_window import HOST, estate

#: The declaration: the device's own width, at its own scale. Nothing is said
#: about zooming, which stays the reader's.
VIEWPORT = "width=device-width, initial-scale=1"
_TAG = f'<meta name="viewport" content="{VIEWPORT}">'

_TEMPLATES = Path(app_module.__file__).resolve().parent / "templates"


class _SignedIn(TestCase):
    """The estate `tests/test_series_window.py` reads — a host with readings, and
    an engine whose two checks give System its schedule — with a node that has
    changed its mind, so Events and History have rows."""

    def setUp(self) -> None:
        app_module.app.config["TESTING"] = True
        self._saved = (app_module.status_tree, app_module.engine)
        self.addCleanup(self._restore)
        self.tree, app_module.engine = estate()
        app_module.status_tree = self.tree
        self.tree.upsert("/db/replica", StatusCode.OK, "in step")
        self.tree.upsert("/db/replica", StatusCode.ERROR,
                         "replication lag of 512 seconds")
        self.client = app_module.app.test_client()
        self.client.post("/login",
                         data={"username": "pan", "password": "12345678"})

    def _restore(self) -> None:
        app_module.status_tree, app_module.engine = self._saved

    def _get(self, url: str) -> Element:
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200, url)
        return parse(response.get_data(as_text=True))


class ViewportTests(_SignedIn):
    """Every document declares the device's width."""

    def test_every_document_declares_it_or_takes_the_shared_head(self):
        # the shared head says it once, and the two documents that stand before
        # there is a session to build a header from say it themselves
        self.assertEqual((_TEMPLATES / "_header.html").read_text().count(_TAG), 1)
        documents = [template for template in sorted(_TEMPLATES.glob("*.html"))
                     if "<!DOCTYPE" in template.read_text()]
        self.assertGreater(len(documents), 10)
        alone = []
        for template in documents:
            source = template.read_text()
            takes = source.count("{% include '_header.html' %}")
            with self.subTest(template=template.name):
                self.assertEqual(takes + source.count(_TAG), 1)
            if not takes:
                alone.append(template.name)
        self.assertEqual(alone, ["choose_door.html", "login.html"])

    def test_it_reaches_the_page(self):
        routes = ("/status", f"/status{HOST}", "/events", "/system",
                  "/system/installed", "/series", f"/history{HOST}",
                  "/handled", "/links", "/copy", "/about")
        for url in routes:
            with self.subTest(url=url):
                self.assertEqual(self._declared(self._get(url)), [VIEWPORT])

    def test_the_login_page_declares_it_too(self):
        signed_out = app_module.app.test_client()
        response = signed_out.get("/login")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            self._declared(parse(response.get_data(as_text=True))), [VIEWPORT])

    @staticmethod
    def _declared(page: Element) -> list[str]:
        return [meta.attrs.get("content", "") for meta in page.all(tag="meta")
                if meta.attrs.get("name") == "viewport"]


class TableBoxTests(_SignedIn):
    """A table stands in a box that scrolls it, so a wide one is the box's to
    scroll and not the page's."""

    #: The boxes: Bootstrap's, the readings table's own, which scrolls both ways
    #: (ADR-0102), and the one around the formats an expiry field takes.
    _BOXES = ("table-responsive", "ls-readings-box",
              "maintenance-expiry-help__table-wrap")

    @classmethod
    def _box(cls, table: Element) -> Element | None:
        node = table.parent
        while node is not None:
            if any(node.has(name) for name in cls._BOXES):
                return node
            node = node.parent
        return None

    def test_no_template_writes_a_table_outside_one(self):
        # read off the sources, so that it holds for a table no test's estate
        # brings to a page — a package's, a secret scheme's
        tables = 0
        for template in sorted(_TEMPLATES.glob("*.html")):
            for table in parse(template.read_text()).all(tag="table"):
                tables += 1
                with self.subTest(template=template.name,
                                  table=table.attrs.get("class", "")):
                    box = self._box(table)
                    self.assertIsNotNone(box)
                    assert box is not None
                    if box.has("table-responsive"):
                        self.assertTrue(box.has("position-relative"))
        self.assertGreaterEqual(tables, 14)

    def test_every_table_of_these_pages_stands_in_one(self):
        for url in ("/events", f"/history{HOST}", "/history/db/replica",
                    "/system", "/system/installed", "/series"):
            page = self._get(url)
            tables = page.all(tag="table")
            self.assertGreater(len(tables), 0, url)
            for table in tables:
                with self.subTest(url=url, table=table.attrs.get("class", "")):
                    box = self._box(table)
                    self.assertIsNotNone(box)
                    assert box is not None
                    # a visually hidden heading is placed absolutely: the box
                    # has to be what it is placed in, or it widens the page
                    if box.has("table-responsive"):
                        self.assertTrue(box.has("position-relative"))

    def test_a_reason_keeps_a_width_to_be_read_at(self):
        # a table wider than its box gives every column its narrowest, and a
        # reason's narrowest is its longest word: a column of single words, in
        # rows a screen tall. In a box it keeps a line's worth of width instead
        css = self.client.get("/static/css/overview.css").get_data(as_text=True)
        self.assertIn("min-width: 16rem",
                      css_rule(css, ".table-responsive td.md-body"))
        for url in ("/events", "/history/db/replica"):
            with self.subTest(url=url):
                reasons = [cell for cell in self._get(url).all("md-body", "td")
                           if self._box(cell) is not None]
                self.assertGreater(len(reasons), 0)

    def test_the_schedule_keeps_its_box_when_it_is_fetched_again(self):
        # System's Running page swaps this part of itself in on every poll
        response = self.client.get("/system?fragment=1")
        self.assertEqual(response.status_code, 200)
        fragment = parse(response.get_data(as_text=True))
        [schedule] = fragment.all("ls-schedule")
        self.assertIsNotNone(self._box(schedule))


class BandTests(_SignedIn):
    """Where the band is narrower than what stands in it, its filters and its
    trail take a second line."""

    def setUp(self) -> None:
        super().setUp()
        self.css = self.client.get(
            "/static/css/overview.css").get_data(as_text=True)

    def test_the_filters_may_take_a_second_line(self):
        self.assertIn("flex-wrap: wrap", css_rule(self.css, ".status-filters"))
        # and nothing forbids the form to be narrower than its four controls
        self.assertNotIn("flex-shrink: 0", css_rule(self.css, ".status-filters"))

    def test_the_walls_strip_may_take_a_second_line(self):
        # the count of pins and the engine's own node, above the cards
        self.assertIn("flex-wrap: wrap", css_rule(self.css, ".strip-band"))

    def test_the_trail_may_take_a_second_line(self):
        trail = self._get(f"/status{HOST}").one("ls-crumbs")
        # nothing on it keeps it on one line, as Bootstrap's `text-nowrap` did
        self.assertEqual(trail.attrs["class"], "ls-crumbs")
        rule = css_rule(self.css, ".ls-crumbs")
        self.assertNotIn("nowrap", rule)
        # nor forbids it to be narrower than its words in a row, which is how a
        # trail wider than the band comes to be as wide as the band
        self.assertNotIn("flex", rule)
        # and a name wider than a line breaks inside itself
        self.assertIn("overflow-wrap: anywhere", rule)
        # and the node's title takes the next line where the trail fills this one
        self.assertIn("flex-wrap: wrap", css_rule(self.css, ".ls-band__title"))
        # having no say in whether the two fit one line: it takes what is left
        self.assertIn("flex: 1 1 0", css_rule(self.css, ".node-title--header"))

    def test_a_line_of_the_trail_ends_in_its_separator(self):
        # the space before a slash does not break and the one after it does: a
        # line ends "… /" and the next begins with a name
        for url in (f"/status{HOST}", f"/history{HOST}", f"/series{HOST}",
                    f"/copy{HOST}"):
            with self.subTest(url=url):
                trail = self._get(url).one("ls-crumbs")
                separators = [span.source() for span in trail.all(tag="span")
                              if "/" in span.source()]
                self.assertEqual(separators, ["\xa0/ "] * HOST.count("/"))


class WordTests(_SignedIn):
    """A name, or a word of a line, that has nowhere to break and is wider than
    the screen breaks inside itself where a page prints it outside a table."""

    def test_what_prints_a_name_lets_it_break(self):
        css = self.client.get("/static/css/overview.css").get_data(as_text=True)
        for selector in (".ls-crumbs", ".status-card__name", ".status-node__name",
                         ".rule-block__what", ".rule-block__record"):
            with self.subTest(selector=selector):
                self.assertIn("overflow-wrap: anywhere", css_rule(css, selector))

    def test_the_copy_pages_heading_is_the_bands_trail(self):
        # Copy is a view of its node (ADR-0115 decision 7): its heading is the trail
        # every view carries, which takes the lines it needs and breaks a name
        heading = self._get(f"/copy{HOST}").one(tag="h1")
        self.assertTrue(heading.has("ls-band__title"))
        self.assertEqual(heading.one("ls-crumbs").attrs["class"], "ls-crumbs")
