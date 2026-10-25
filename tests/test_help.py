"""The account of using the wall, drawn at `/help` (ADR-0136).

One Markdown file the package ships beside its code says what a viewer sees on the wall
and what a click does, and the page draws it as a handbook is drawn, its headings
anchored. What a browser does with it — the menu's foot reached without scrolling, a
section opened beneath the bar — is ``tests/test_help_browser.py``'s; what the response
says, and that the account keeps up with the menu it describes, is this file's.
"""
import os
from importlib.resources import files
from unittest import TestCase

os.environ.setdefault("SECRET_KEY", "test-key")

from little_sister import app as app_module
from little_sister.app import LAYOUTS
from little_sister.first_look import BIG_LEVEL
from little_sister.looks import LOOKS
from tests.page_tree import parse

#: The layouts' words, as the settings menu draws them (`_settings_menu.html`).
LAYOUT_WORDS = {"rail": "left rail", "topbar": "top bar", "kiosk": "kiosk"}


def _said(text: str) -> str:
    """The account with its lines joined, as a reader reads a wrapped sentence."""
    return " ".join(text.split())


class HelpPageTests(TestCase):
    def setUp(self):
        app_module.app.config["TESTING"] = True
        self.client = app_module.app.test_client()
        self.client.post("/login", data={"username": "pan", "password": "12345678"})

    def test_the_account_is_drawn_at_help_its_headings_anchored(self):
        response = self.client.get("/help")
        self.assertEqual(response.status_code, 200)
        page = parse(response.get_data(as_text=True))
        article = page.one("ls-help")
        self.assertEqual(article.one(tag="h1").text(), "Using the wall")
        anchored = {heading.attrs.get("id") for heading in article.walk()
                    if heading.tag in ("h2", "h3")}
        for anchor in ("the-wall", "chips-and-boxes", "the-band", "a-heads-buttons",
                       "a-nodes-page", "maintenance-and-what-is-handled",
                       "the-settings-menu", "the-kiosk", "on-a-phone"):
            with self.subTest(anchor=anchor):
                self.assertIn(anchor, anchored)
        # every link the account writes into itself lands on a heading it has
        targets = {link.attrs["href"][1:] for link in article.all(tag="a")
                   if link.attrs.get("href", "").startswith("#")}
        self.assertTrue(targets)
        self.assertLessEqual(targets, anchored)

    def test_it_is_the_file_the_package_ships(self):
        shipped = files("little_sister").joinpath("help", "using-the-wall.md")
        self.assertTrue(shipped.is_file())
        self.assertEqual(app_module.help_account(), shipped.read_text(encoding="utf-8"))

    def test_the_settings_menus_foot_leads_to_it(self):
        # the last thing in the groups' flow, after every group (ADR-0136)
        panel = parse(self.client.get("/status").get_data(as_text=True)).one(
            "ls-menu__panel")
        link = panel.one("ls-menu__help")
        self.assertEqual((link.tag, link.attrs.get("href"), link.text()),
                         ("a", "/help", "Using the wall"))
        flow = [child for child in panel.one("ls-menu__groups").children
                if not isinstance(child, str)]
        self.assertIs(flow[-1], link)
        self.assertTrue(all(group.has("ls-menu__group") for group in flow[:-1]))


class AccountTests(TestCase):
    """The account cannot fall behind what it describes: a group added to the settings
    menu, renamed or given a value fails here until the account says it."""

    account = _said(app_module.help_account())

    def test_it_names_every_group_of_the_settings_menu_and_each_value(self):
        for look in LOOKS:
            with self.subTest(look=look.key):
                self.assertIn(f"**{look.heading}**", self.account)
                for value in look.values:
                    words = (f"*{look.label(value)}*", f"*{value}*")
                    self.assertTrue(any(said in self.account for said in words),
                                    f"{look.key}: neither of {words}")
        self.assertIn("**Layout**", self.account)
        for layout in LAYOUTS:
            with self.subTest(layout=layout):
                self.assertIn(f"*{LAYOUT_WORDS[layout]}*", self.account)

    def test_it_names_the_bands_buttons_the_heads_and_a_nodes_tabs(self):
        for said in ("**Close all**", "**Open all**", "**As configured**",
                     "**hide ok**", "**hide idle**", "**↗**", "**The funnel**", "**▤**",
                     "**‖**", "**⋯**", "**⌄ all N**", "**⌃ less**",
                     "**Status**", "**Series**", "**History**", "**Handbook**",
                     "**Copy**", "**Log out**", "**Exit**"):
            with self.subTest(said=said):
                self.assertIn(said, self.account)

    def test_it_says_how_big_a_level_nobody_configured_may_open(self):
        # the built-in look's net (`first_look.BIG_LEVEL`), in the words a viewer
        # reads: the account changes with the number
        self.assertEqual(BIG_LEVEL, 30)
        self.assertIn("would draw more than thirty boxes", self.account)
        self.assertNotIn("+N more", self.account)

    def test_it_names_every_page_of_the_navigation(self):
        for section in ("Series", "Events", "Handled", "Links", "Copy", "System",
                        "About"):
            with self.subTest(section=section):
                self.assertIn(f"- **{section}** —", self.account)
