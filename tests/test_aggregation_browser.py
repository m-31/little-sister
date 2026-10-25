"""A configured rule on the wall, in Chromium (ADR-0137 decision 10).

Its block stands where its rule changes a count, its note behind the note mark, which
opens it in the card a pin's note opens in (ADR-0135 decision 3) — the node, the
block's sentence, the note whole and where the rule is configured — and nothing on
it, for an admin either, is a button: a configured rule is changed in the
configuration. A line it counts otherwise keeps its color and carries § before its
words, without moving them. What the pages say is ``tests/test_aggregation_pages.py``'s;
this file is what only a browser can tell.

Skipped wherever Playwright or a Chromium binary is unavailable
(``docs/testing-the-gui.md``, Mode 5).
"""
from __future__ import annotations

import threading
import unittest
from datetime import date
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit
from wsgiref.simple_server import WSGIRequestHandler, WSGIServer, make_server

from little_sister import app as app_module
from little_sister.aggregation import AggregationRule, RuleSet, Table
from little_sister.checks import Entry
from little_sister.status import StatusCode
from little_sister.tree import StatusTree
from tests.browser_server import PageServer

try:  # pragma: no cover - environment probe
    from playwright.sync_api import sync_playwright
except ImportError:  # pragma: no cover
    sync_playwright = None  # type: ignore[assignment]

#: A sandbox pins one browser build; a Playwright from the lock may expect another,
#: so the one that is there is what runs (as ``tests/sweep_contrast.py`` does).
_SANDBOX_CHROMIUM = Path("/opt/pw-browsers/chromium-1194/chrome-linux/chrome")

#: Bootstrap as ``tests/sweep_contrast.py`` vendors it (``docs/testing-the-gui.md``,
#: Mode 4), where there is a copy; the CDN otherwise.
_BOOTSTRAP = (Path(__file__).resolve().parent.parent / "var" / "bootstrap"
              / "node_modules" / "bootstrap" / "dist")

OK, WARN, ERROR = StatusCode.OK, StatusCode.WARN, StatusCode.ERROR

_CAPPED = "/aws/develop"
_NOTE = "The develop account is **no production**; it turns `/aws` amber at most."
_NOTE_READ = "The develop account is no production; it turns /aws amber at most."
_HEALED = "/aws/prod/ec2"

#: Where the first letter of a line's words is drawn: its own box, which a float
#: beside it moves, where the paragraph's box does not move.
_FIRST_GLYPH = """(line) => {
    const words = line.querySelector('.check-reason__body p');
    const text = document.createTreeWalker(words, NodeFilter.SHOW_TEXT).nextNode();
    const range = document.createRange();
    range.setStart(text, 0);
    range.setEnd(text, 1);
    const box = range.getBoundingClientRect();
    return {x: box.x, y: box.y, height: box.height};
}"""


def _rule(name: str, under: str, table: Table, order: int, **where: Any
          ) -> AggregationRule:
    return AggregationRule(
        name=name, under=under, segments=tuple(under.strip("/").split("/")),
        table=table, note=_NOTE if order == 0 else "An instance's CPU credits.",
        since=date(2026, 9, 5), file=Path("config/aggregation.yaml"),
        root=Path("config"), order=order, **where)


def _estate() -> StatusTree:
    """An account capped at a warning over a red function, and an account's ec2
    whose amber lines heal."""
    tree = StatusTree()
    tree.use_aggregation(RuleSet((
        _rule("develop advises", _CAPPED, Table(((ERROR, WARN),)), 0),
        _rule("ec2 heals", _HEALED, Table(((WARN, OK),)), 1, lines=("*",)))))
    tree.upsert(f"{_CAPPED}/lambda/fn", ERROR, "timed out after 30s")
    tree.upsert(_HEALED, WARN, [
        Entry("i-0a1", "i-0a1: CPU credit balance low", code=WARN),
        Entry("i-0b2", "i-0b2: within its limits", code=OK)], members=True)
    return tree


class _Quiet(WSGIRequestHandler):
    def log_message(self, format: str, *args: object) -> None:
        pass


class ConfiguredBlockBrowserTests(unittest.TestCase):
    """A real server and headless Chromium; for each test the estate anew and a page
    signed in as an admin, who may set pins and finds no button on a configured
    rule."""

    playwright: Any = None
    browser: Any = None
    server: WSGIServer | None = None
    base = ""

    @classmethod
    def setUpClass(cls) -> None:
        if sync_playwright is None:
            raise unittest.SkipTest("playwright is not installed")
        try:
            cls.playwright = sync_playwright().start()
            cls.browser = cls.playwright.chromium.launch(
                executable_path=(str(_SANDBOX_CHROMIUM) if _SANDBOX_CHROMIUM.is_file()
                                 else None))
        except Exception as error:  # pragma: no cover - no browser here
            if cls.playwright is not None:
                cls.playwright.stop()
            raise unittest.SkipTest(f"no chromium available: {error}") from error
        cls.saved = app_module.status_tree
        cls.server = make_server("127.0.0.1", 0, app_module.app,
                                 server_class=PageServer, handler_class=_Quiet)
        threading.Thread(target=cls.server.serve_forever, daemon=True).start()
        cls.base = f"http://127.0.0.1:{cls.server.server_port}"

    @classmethod
    def tearDownClass(cls) -> None:
        if cls.server is not None:
            cls.server.shutdown()
            cls.server.server_close()
        app_module.status_tree = cls.saved
        cls.browser.close()
        cls.playwright.stop()

    def setUp(self) -> None:
        app_module.status_tree = _estate()
        context = self.browser.new_context(viewport={"width": 1200, "height": 800},
                                           reduced_motion="reduce")
        self.addCleanup(context.close)
        page = context.new_page()
        page.route("https://cdn.jsdelivr.net/**", self._vendored)
        page.goto(f"{self.base}/login")
        page.fill("#username", "pan")
        page.fill("#password", "12345678")
        with page.expect_navigation():
            page.click("button[type=submit]")
        self.page = page

    @staticmethod
    def _vendored(route: Any) -> None:
        """Bootstrap from the vendored copy where there is one, the CDN otherwise."""
        name = route.request.url.rsplit("/", 1)[-1]
        for candidate in (_BOOTSTRAP / "css" / name, _BOOTSTRAP / "js" / name):
            if candidate.is_file():
                route.fulfill(path=str(candidate))
                return
        route.continue_()

    def _block(self, name: str) -> Any:
        return self.page.locator(
            '#status-grid .rule-block[data-rule="aggregation"]'
            f'[data-rule-name="{name}"]')

    def _apart(self, card: Any, block: Any) -> bool:
        """Whether the card stands clear of the block, above or below it."""
        mine, theirs = card.bounding_box(), block.bounding_box()
        return (mine["y"] + mine["height"] <= theirs["y"] + 1
                or mine["y"] >= theirs["y"] + theirs["height"] - 1)

    def test_its_note_opens_from_its_mark_in_the_note_card(self):
        page = self.page
        page.goto(f"{self.base}/status")
        block = self._block("develop advises")
        self.assertEqual(block.count(), 1)
        card = page.locator("#note-card")
        self.assertTrue(card.is_hidden())
        mark = block.locator(".rule-note-mark")
        self.assertEqual(urlsplit(mark.get_attribute("href")).path,
                         "/status/aws/develop")
        mark.click()
        card.wait_for(state="visible")
        self.assertEqual(urlsplit(page.url).path, "/status")
        # the node, the block's sentence, the note whole and where the rule is
        # written — and no button anywhere in it
        self.assertEqual(card.locator(".inspect-card__title").inner_text(), "develop")
        self.assertTrue(" ".join(card.locator(".note-card__sentence").inner_text()
                                 .split()).endswith("by the rule develop advises"))
        self.assertEqual(card.locator(".note-card__note").inner_text().strip(),
                         _NOTE_READ)
        self.assertEqual(card.locator(".note-card__record").inner_text().strip(),
                         "Configured in config/aggregation.yaml since 2026-09-05.")
        self.assertEqual(card.locator("button, form, input, textarea").count(), 0)
        page.wait_for_timeout(50)
        self.assertTrue(self._apart(card, block))
        # Escape closes it and gives the mark the focus back
        page.keyboard.press("Escape")
        card.wait_for(state="hidden")
        self.assertTrue(page.evaluate(
            "document.activeElement.classList.contains('rule-note-mark')"))

    def test_an_admin_finds_no_button_on_it(self):
        page = self.page
        page.goto(f"{self.base}/status")
        block = self._block("develop advises")
        block.hover()
        page.wait_for_timeout(50)
        # the pin's pencil and its editor are a pin's; a configured rule has none
        self.assertEqual(block.locator("button, form, details, .rule-block__edit")
                         .count(), 0)
        # and on the node's page, where a pin's block says *Edit* and *Clear*
        page.goto(f"{self.base}/status/aws/develop")
        head = page.locator(
            '.viewed-head .rule-block[data-rule="aggregation"]')
        self.assertEqual(head.count(), 1)
        self.assertEqual(head.locator("button, form, details").count(), 0)
        self.assertIn("Configured in config/aggregation.yaml since 2026-09-05.",
                      head.inner_text())

    def test_a_line_it_counts_otherwise_keeps_its_place_and_its_color(self):
        page = self.page
        page.goto(f"{self.base}/status/aws/prod/ec2")
        line = page.locator(".check-reason").filter(
            has=page.locator(".check-reason__body", has_text="i-0a1"))
        self.assertIn("s-warn", line.get_attribute("class") or "")
        mark = line.locator(".line-rule")
        self.assertEqual(mark.get_attribute("title"),
                         "Counts as ok by the rule ec2 heals")
        # § stands before the words, on their first line, and moves none of them
        # onto a line of their own
        mine = mark.bounding_box()
        first = line.evaluate(_FIRST_GLYPH)
        self.assertLess(abs(mine["y"] + mine["height"] / 2
                            - (first["y"] + first["height"] / 2)), first["height"])
        self.assertLessEqual(mine["x"] + mine["width"], first["x"] + 1)
        # the line it does not change carries no mark
        calm = page.locator(".check-reason").filter(
            has=page.locator(".check-reason__body", has_text="i-0b2"))
        self.assertEqual(calm.locator(".line-rule").count(), 0)


if __name__ == "__main__":
    unittest.main()
