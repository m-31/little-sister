"""The Links page opens with one sentence and folds its setup guide (ADR-0030).

With no links configured the page *was* the guide: a sample file, where to put it,
every installed icon name with both its drawings, and how to add a mark — more than
a screen at a desk and two on a phone before anybody had a link (the live GUI
review). And a deployment that had written its file lost the roster with it, so
adding a fortieth link meant guessing an icon's name.

So the guide is two folds, the browser's own disclosures and closed: *Add links*,
the file's shape and where it goes, and *Icon names*, the roster and how to add a
mark. An empty page opens with one sentence and both; a page that has links keeps
*Icon names* at its foot. A viewer reads what an admin reads: the page knows no
roles.

The page is read as a tree (`tests/page_tree.py`), since every claim here is about
where something stands. What a browser has to show — that an opened fold fits a
phone, and what its inks measure on the card — is `tests/test_phone_browser.py`'s
and Mode 4's (`tests/sweep_contrast.py`).
"""
from __future__ import annotations

import os
from unittest import TestCase, mock

os.environ.setdefault("SECRET_KEY", "test-key")

from little_sister import app as app_module
from little_sister import icons, links
from tests.page_tree import Element, css_rule, parse

#: The sentence an empty page opens with.
LEAD = ("No links yet. This page is the deployment's toolbox, the dashboards and "
        "tools to have at hand in an incident, and it has not been filled in.")
ADD = "Add links · one file in this deployment's configuration"

#: A page that has links: one group, one entry.
FILLED = links.LinksConfig(groups=(links.Group(title="Toolbox", links=(
    links.Link(title="Grafana", url="https://grafana.example.org/",
               icon="grafana"),)),))


def _icon_names(count: int) -> str:
    return f"Icon names · {count} installed, and how to add your own"


class _LinksCase(TestCase):
    """`/links` for one configuration, read by an admin unless a test says
    otherwise, with the network held out as `tests/test_web.py` holds it."""

    def setUp(self) -> None:
        app_module.app.config["TESTING"] = True
        self.client = app_module.app.test_client()
        self.client.post("/login",
                         data={"username": "pan", "password": "12345678"})

    def _viewer(self) -> None:
        with self.client.session_transaction() as sess:
            sess["username"] = "viewer"
            sess["firstname"] = "Vera"
            sess["admin"] = False

    def _page(self, config: links.LinksConfig) -> Element:
        """The page's own part of the document: what stands under its heading."""
        with mock.patch.object(app_module, "current_links", return_value=config):
            response = self.client.get("/links")
        self.assertEqual(response.status_code, 200)
        return parse(response.get_data(as_text=True)).with_id("ls-links-page")

    @staticmethod
    def _folds(page: Element) -> list[Element]:
        return page.all("ls-links__fold", tag="details")

    @staticmethod
    def _said(fold: Element) -> str:
        """What a closed fold says: its summary, the first thing in it."""
        summary = fold.first()
        assert summary.tag == "summary", summary
        return summary.text()

    @staticmethod
    def _folded(element: Element) -> bool:
        node = element.parent
        while node is not None:
            if node.tag == "details" and node.has("ls-links__fold"):
                return True
            node = node.parent
        return False

    @staticmethod
    def _roster(fold: Element) -> list[str]:
        """The names a fold's table lists, in its order."""
        return [row.one(tag="code").text()
                for row in fold.one("ls-links__pack").one(tag="tbody").all(tag="tr")]

    @staticmethod
    def _shape(element: Element) -> list[tuple[str, tuple[tuple[str, str], ...], str]]:
        """Everything under ``element`` as written: tags, attributes and words."""
        return [(part.tag, tuple(sorted(part.attrs.items())), part.source())
                for part in element.walk()]


class EmptyPageTests(_LinksCase):
    """No links: one sentence, then the guide in two folds."""

    def test_it_opens_with_one_sentence_and_two_folds(self):
        page = self._page(links.LinksConfig())
        empty = page.one("ls-links__empty")
        parts = [part for part in empty.children if isinstance(part, Element)]
        self.assertEqual([part.tag for part in parts], ["p", "details", "details"])
        self.assertEqual(parts[0].text(), LEAD)
        self.assertEqual(parts[0].one(tag="strong").text(), "No links yet.")
        # and nothing of the guide stands on the page outside a fold
        guide = page.all("ls-links__sample") + page.all("ls-links__pack")
        self.assertEqual(len(guide), 2)
        for part in guide:
            self.assertTrue(self._folded(part), part)
        self.assertEqual(
            [paragraph for paragraph in page.all(tag="p")
             if not self._folded(paragraph)], [parts[0]])

    def test_both_folds_are_closed_and_say_what_they_hold(self):
        folds = self._folds(self._page(links.LinksConfig()))
        self.assertEqual(
            [self._said(fold) for fold in folds],
            [ADD, _icon_names(len(icons.known_names()))])
        for fold in folds:
            # the browser's own disclosure, closed until somebody opens it
            self.assertNotIn("open", fold.attrs)

    def test_add_links_holds_the_file_and_where_it_goes(self):
        add = self._folds(self._page(links.LinksConfig()))[0]
        sample = add.one("ls-links__sample").text()
        for line in ("groups:", "- title: Toolbox", "url: https://grafana.example.org/",
                     "icon: grafana"):
            self.assertIn(line, sample)
        self.assertIn(app_module._links_file_hint(),
                      [code.text() for code in add.all(tag="code")])
        # and nothing of the roster: that is the other question
        self.assertEqual(add.all("ls-links__pack"), [])

    def test_icon_names_holds_the_roster_and_how_to_add_a_mark(self):
        names = self._folds(self._page(links.LinksConfig()))[1]
        self.assertEqual(self._roster(names), list(icons.known_names()))
        said = names.text()
        self.assertIn("takes a name, never a URL", said)
        for word in ("icons/", "firewall.svg", "firewall-on-light.svg",
                     "firewall-on-dark.svg"):
            self.assertIn(word, [code.text() for code in names.all(tag="code")])
        self.assertEqual(names.all("ls-links__sample"), [])

    def test_the_fold_says_how_to_add_a_mark_without_the_other_fold(self):
        # under a page that has links there is no *Add links* to read first, so
        # the sentence names the file it means
        names = self._folds(self._page(links.LinksConfig()))[1]
        self.assertIn("put an icons/ directory beside links.yaml", names.text())
        self.assertNotIn("beside that file", names.text())


class FilledPageTests(_LinksCase):
    """A page that has links keeps the icon names within reach, at its foot."""

    def test_the_icon_names_stand_folded_at_its_foot(self):
        # adding a fortieth link meant guessing a name, or emptying the file
        page = self._page(FILLED)
        fold, = self._folds(page)
        self.assertEqual(self._said(fold), _icon_names(len(icons.known_names())))
        self.assertNotIn("open", fold.attrs)
        foot = page.one("ls-links__foot")
        self.assertTrue(fold.within(foot))
        # under the links, where it competes with nothing that is on fire
        self.assertLess(page.all("ls-links__group")[-1].order, foot.order)
        self.assertEqual(
            [part.tag for part in page.children if isinstance(part, Element)][-1],
            "div")
        self.assertIs([part for part in page.children
                       if isinstance(part, Element)][-1], foot)

    def test_it_is_the_roster_the_empty_page_shows(self):
        filled, = self._folds(self._page(FILLED))
        empty = self._folds(self._page(links.LinksConfig()))[1]
        self.assertEqual(self._roster(filled), list(icons.known_names()))
        self.assertEqual(self._shape(filled), self._shape(empty))

    def test_a_page_that_has_links_does_not_say_how_to_start(self):
        page = self._page(FILLED)
        self.assertEqual(page.all("ls-links__empty"), [])
        self.assertEqual(page.all("ls-links__sample"), [])
        self.assertNotIn("No links yet", page.text())
        self.assertNotIn("Add links", page.text())

    def test_the_fold_counts_what_the_registry_holds(self):
        # a house pack's names are a deployment's to use, so they are its to read
        before = len(icons.known_names())
        icons.register_pack("little_sister.icon_pack",
                            {"firewall": "aws-on-light.svg"})
        for config in (links.LinksConfig(), FILLED):
            with self.subTest(empty=config.is_empty()):
                fold = self._folds(self._page(config))[-1]
                self.assertEqual(self._said(fold), _icon_names(before + 1))
                self.assertIn("firewall", self._roster(fold))

    def test_the_filter_does_not_reach_the_fold(self):
        # the filter hides entries and the groups they leave empty; the fold is
        # neither, so typing a link's name never takes the names away
        page = self._page(FILLED)
        fold, = self._folds(page)
        for group in page.all("ls-links__group"):
            self.assertFalse(fold.within(group))
        self.assertFalse(fold.within(page.one("ls-links")))
        self.assertEqual(
            [part for part in [fold, *fold.walk()] if "data-ls-match" in part.attrs],
            [])


class EveryReaderTests(_LinksCase):
    """The page knows no roles: a viewer reads what an admin reads."""

    def test_a_viewer_reads_the_page_an_admin_reads(self):
        for config in (links.LinksConfig(), FILLED):
            with self.subTest(empty=config.is_empty()):
                admin = self._shape(self._page(config))
                self._viewer()
                self.assertEqual(self._shape(self._page(config)), admin)
                self.setUp()


class SheetTests(_LinksCase):
    """What the stylesheet owes the folds."""

    def setUp(self) -> None:
        super().setUp()
        self.css = self.client.get(
            "/static/css/overview.css").get_data(as_text=True)

    def test_a_folds_summary_reads_as_something_to_open(self):
        self.assertIn("cursor: pointer",
                      css_rule(self.css, ".ls-links__fold > summary"))

    def test_the_foot_keeps_the_measure_of_the_empty_page(self):
        # a roster as wide as a filled page puts a name a hand from its drawing
        measure = "max-width: 46rem"
        self.assertIn(measure, css_rule(self.css, ".ls-links__empty"))
        self.assertIn(measure, css_rule(self.css, ".ls-links__foot"))

    def test_what_a_summary_adds_is_muted_from_a_token(self):
        # on a card, which Bootstrap paints: its own muted ink is not ours to
        # vouch for, so the aside takes the one `tests/test_contrast.py` measures
        self.assertIn("color: var(--ls-muted)",
                      css_rule(self.css, ".ls-links__aside"))
        for config in (links.LinksConfig(), FILLED):
            for fold in self._folds(self._page(config)):
                aside = fold.first().one(tag="span")
                self.assertEqual(aside.attrs.get("class"), "ls-links__aside")
