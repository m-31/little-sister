"""A tap on an action in a box follows it on the first try — in a browser.

A card's head and a box's row are what the inspection card answers to (ADR-0019), and
a line's Copy chip, a deployment's chip on a line and a node's own chip stand inside
that row (ADR-0034): the chips of a nested box's lines and of every head. On a touch
screen the card has no hover to open on, so the first tap on the row opened it and
the second followed what was tapped — and a tap on a chip there was a tap on the row.
``tests/test_actions.py`` holds where the chips stand; that one tap on a chip is the
tap on its link, and raises no card, is a touch screen's to show.

A tap reaches the page in two shapes. Chromium gives a link the focus before the
click, and the focus is what raised the card, so the click then passed to the link
with the card standing over it; a browser that gives a link no focus for a tap — Safari
— sends the pointer down and up and then the click, and the click raised the card
instead of following the link. Both shapes are tried, the browser's own and the other
dispatched as that browser sends it.

Served by a real server to headless Chromium emulating a phone. Skipped wherever
Playwright or a Chromium binary is unavailable, so the ordinary gate does not grow a
browser dependency (``docs/testing-the-gui.md``, Mode 5).
"""
from __future__ import annotations

import threading
import unittest
from pathlib import Path
from typing import Any
from wsgiref.simple_server import WSGIRequestHandler, WSGIServer, make_server

from little_sister import app as app_module
from little_sister import slots
from little_sister.status import StatusCode
from little_sister.tree import StatusTree
from tests.browser_looks import looks
from tests.browser_server import PageServer
from tests.demo_extension import action, node_action

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

#: The phone ``tests/test_phone_browser.py`` reads its pages on: a touch screen.
_PHONE = {
    "viewport": {"width": 390, "height": 844},
    "device_scale_factor": 3,
    "is_mobile": True,
    "has_touch": True,
    "user_agent": ("Mozilla/5.0 (Linux; Android 14; Pixel 8) AppleWebKit/537.36 "
                   "(KHTML, like Gecko) Chrome/140.0.0.0 Mobile Safari/537.36"),
}

#: A box in a card whose lines are members, each with its Copy chip and a
#: deployment's chip; a box whose one line is prose, so its head carries the
#: deployment's chip for the node; and a card that is a leaf, its head the same.
#: Each has a title, so its name is one the inspection card answers to.
_LINES = "/ci/reviews"
_REVIEWS = {
    f"api-pr-{number}": (
        f"[#{number}](https://forge.example.org/acme/api/pulls/{number}) waiting "
        f"{number % 5 + 2}h for a reviewer")
    for number in range(4810, 4814)
}
_BOX = "/ci/build"
_CARD = "/uplink"

#: Where the deployment's chips lead, as ``tests/demo_extension`` writes them.
_TRACKER = "https://tracker.example.org/**"

#: A tap as a browser that gives a link no focus for it sends it to the page: the
#: pointer down and up, then the click, and nothing between them. Chromium's own
#: tap, `locator.tap()`, focuses the link first.
_TAP_WITHOUT_A_FOCUS = """
    chip => {
      for (const kind of ['pointerdown', 'pointerup']) {
        chip.dispatchEvent(new PointerEvent(kind, {
            pointerType: 'touch', bubbles: true, cancelable: true, composed: true}));
      }
      chip.dispatchEvent(new MouseEvent('click', {
          bubbles: true, cancelable: true, composed: true, detail: 1}));
    }
"""

#: Whether the inspection card was shown at any moment from here on.
_WATCH_THE_CARD = """
    () => {
      const card = document.getElementById('inspect-card');
      window.__cardShown = !card.hidden;
      new MutationObserver(() => { if (!card.hidden) { window.__cardShown = true; } })
          .observe(card, {attributes: true, attributeFilter: ['hidden']});
    }
"""


def _estate() -> StatusTree:
    tree = StatusTree()
    tree.upsert(_LINES, StatusCode.WARN, dict(_REVIEWS), members=True)
    tree.set_title(_LINES, "Pull requests waiting for a reviewer")
    tree.upsert(_BOX, StatusCode.ERROR, "the build failed on main")
    tree.set_title(_BOX, "The main build")
    tree.upsert("/ci/deploy", StatusCode.OK, "deployed this morning")
    tree.upsert(_CARD, StatusCode.WARN, "packet loss of 2 %")
    tree.set_title(_CARD, "The line out")
    return tree


class _Quiet(WSGIRequestHandler):
    def log_message(self, format: str, *args: object) -> None:
        pass


class ActionTapTests(unittest.TestCase):
    """One tap on a chip in a row that has a card, on an emulated phone."""

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
        app_module.status_tree = _estate()
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
        # a deployment's chips beside the library's Copy: on every line of a leaf,
        # and in the head of every node that has lines of its own. Registered for
        # each test, since the suite empties the registry before every one
        # (`conftest.py`); a reset puts the library's own fillers back
        slots.register("reason.actions", "tests.demo_extension", "reason_action.html",
                       action)
        slots.register("node.actions", "tests.demo_extension", "node_action.html",
                       node_action)
        self.addCleanup(slots.forget_fillers)
        self.context = self.browser.new_context(**_PHONE, reduced_motion="reduce")
        self.addCleanup(self.context.close)
        # rows the inspection card answers to: the card on a pause, a viewer's
        # choice since the library's look is `off`
        self.context.add_cookies([looks(self.base, inspection_card="pause")])
        self.context.route("https://cdn.jsdelivr.net/**", self._vendored)
        # the tracker a chip opens in a new tab answers, so the tab has an address
        self.context.route(_TRACKER, lambda route: route.fulfill(
            content_type="text/html", body="<title>tracker</title>"))
        self.page = self.context.new_page()
        self.page.goto(f"{self.base}/login")
        self.page.fill("#username", "pan")
        self.page.fill("#password", "12345678")
        with self.page.expect_navigation():
            self.page.click("button[type=submit]")

    @staticmethod
    def _vendored(route: Any) -> None:
        """Bootstrap from the vendored copy where there is one, the CDN otherwise."""
        name = route.request.url.rsplit("/", 1)[-1]
        for candidate in (_BOOTSTRAP / "css" / name, _BOOTSTRAP / "js" / name):
            if candidate.is_file():
                route.fulfill(path=str(candidate))
                return
        route.continue_()

    # --- the hand ---------------------------------------------------------------------

    def _wall(self) -> None:
        self.page.goto(f"{self.base}/status")
        self.page.wait_for_selector(f'.status-node__self[data-path="{_LINES}"] '
                                    '.status-node__name.inspect-trigger')
        self.page.evaluate(_WATCH_THE_CARD)

    def _row(self, path: str, name: str) -> Any:
        """The row of the node at ``path`` — a box's, or a card's head — whose name
        is one the inspection card answers to."""
        row = self.page.locator(f'.{name}[data-path="{path}"]')
        self.assertEqual(row.count(), 1, path)
        self.assertTrue(row.locator('[data-control="toggle"]').evaluate(
            "name => name.classList.contains('inspect-trigger')"), path)
        return row

    #: The two shapes a tap reaches the page in (the module's docstring).
    _SHAPES = ("the browser's own tap", "a tap that gives the link no focus")

    def _tap(self, chip: Any, shape: str) -> None:
        if shape == self._SHAPES[0]:
            chip.tap()
        else:
            chip.evaluate(_TAP_WITHOUT_A_FOCUS)

    def _opens_in_a_new_tab(self, chip: Any, shape: str) -> None:
        """One tap on ``chip``, a link to a new tab: the tab opens at the chip's
        address, and the wall raised no card for the node the chip stands in."""
        href = chip.get_attribute("href")
        self.assertIsNotNone(href)
        with self.context.expect_page(timeout=3000) as opened:
            self._tap(chip, shape)
        tab = opened.value
        tab.wait_for_load_state()
        self.assertEqual(tab.url, href)
        self.assertFalse(self.page.evaluate("window.__cardShown"))
        tab.close()

    # --- one tap ----------------------------------------------------------------------

    def _lines(self) -> Any:
        # a box's lines stand after its row, in the box (ADR-0127 decision 3)
        box = self._row(_LINES, "status-node__self").locator("xpath=..")
        lines = box.locator(":scope > .reason-block > .status-node__reason")
        self.assertEqual(lines.count(), len(_REVIEWS))
        return lines

    def test_a_tap_on_a_lines_chip_follows_it_on_the_first_try(self):
        # a nested box's lines stand in the row its card answers to, and each line
        # carries the deployment's chip, to a new tab, and its Copy, to the line's
        # own document. Each tap is the first on a wall just loaded: the second tap
        # on a row followed its link all along
        for shape in self._SHAPES:
            with self.subTest(shape=shape, chip="the deployment's"):
                self._wall()
                self._opens_in_a_new_tab(
                    self._lines().nth(1).locator(".reason-action", has_text="raise"),
                    shape)
            with self.subTest(shape=shape, chip="Copy"):
                self._wall()
                copy = self._lines().nth(2).locator(".reason-action", has_text="Copy")
                href = copy.get_attribute("href")
                self.assertIsNotNone(href)
                self.assertIn(f"/copy{_LINES}?reason=", href)
                self._tap(copy, shape)
                self.page.wait_for_url(f"{self.base}{href}", timeout=3000)

    def test_a_phone_keeps_every_lines_chips_and_a_heads_in_view(self):
        # finding 14 of the GUI review, held through the stages of the interactive wall
        # (backlog #91): on a phone every line keeps its Copy chip, shown outright where
        # nothing hovers, inside the screen, and so does a node's chip in its head —
        # on the wall and on the leaf's own page
        shown = """
            el => {
              const box = el.getBoundingClientRect();
              return {visible: el.checkVisibility(),
                      shown: parseFloat(getComputedStyle(el).opacity) >= 0.6,
                      inside: box.left >= 0 && box.right <= window.innerWidth,
                      sized: box.width > 8 && box.height > 8};
            }
        """
        # shown outright: 0.6 where nothing hovers, 0.75 on a leaf's own page
        in_view = {"visible": True, "shown": True, "inside": True, "sized": True}
        for url in ("/status", f"/status{_LINES}"):
            with self.subTest(url=url):
                self.page.goto(f"{self.base}{url}")
                self.page.wait_for_selector(".reason-action")
                copies = self.page.locator(".reason-action", has_text="Copy")
                self.assertEqual(copies.count(), len(_REVIEWS), url)
                for index in range(copies.count()):
                    self.assertEqual(copies.nth(index).evaluate(shown), in_view,
                                     (url, index))
        self.page.goto(f"{self.base}/status")
        self.page.wait_for_selector(".node-action")
        head_chip = self._row(_CARD, "status-card__head").locator(".node-action")
        self.assertEqual(head_chip.evaluate(shown), in_view)

    def test_a_tap_on_a_heads_chip_follows_it_on_the_first_try(self):
        # the deployment's chip for the node, in a box's head and in a card's
        heads = ((_BOX, "status-node__self"), (_CARD, "status-card__head"))
        for shape in self._SHAPES:
            for path, name in heads:
                with self.subTest(shape=shape, path=path):
                    self._wall()
                    head = self._row(path, name)
                    self._opens_in_a_new_tab(
                        head.locator(".node-actions .node-action", has_text="file"),
                        shape)
