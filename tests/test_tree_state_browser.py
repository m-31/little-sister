"""The tab's map: what a viewer opened stands through the refresh — in a browser.

ADR-0127 decisions 9 and 10, their first stage: today's two folds — a level's *+N
more* and a box's *⌄ all N* beneath its lines, the chevron as it stood — survive every
refresh and a reload of the tab,
in one map one script owns, `tree.js`, in the tab's `sessionStorage`; a new tab starts
as configured, and no cookie is written. Around the swap the keyboard's focus stays
on its control and an open inspection card on its node. On the kiosk the map lives
in memory alone, and five minutes without input bring the first look back. The
system page, which has no map, refreshes as it did.

Served by a real server to headless Chromium, on the page's own clock where a
refresh is waited for (``tests/test_pin_browser.py``'s way). Skipped wherever
Playwright or a Chromium binary is unavailable, so the ordinary gate does not grow a
browser dependency (``docs/testing-the-gui.md``, Mode 5).
"""
from __future__ import annotations

import json
import re
import threading
import unittest
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, ClassVar
from wsgiref.simple_server import WSGIRequestHandler, WSGIServer, make_server

from little_sister import app as app_module
from little_sister.status import StatusCode
from little_sister.tree import StatusTree
from tests.browser_looks import looks
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

#: The map's key in the tab's storage, and its shape.
_KEY = "ls-wall-map"
_MAP = f"window.sessionStorage.getItem({_KEY!r})"

#: Whether `ls-tree-pending` ever stood on <html>, watched from before the page's
#: own scripts run (an init script): the grid held back until the map is applied.
_WATCH_PENDING = """
    window.__pendingSeen = false;
    new MutationObserver(() => {
      const html = document.documentElement;
      if (html && html.classList.contains('ls-tree-pending')) {
        window.__pendingSeen = true;
      }
    }).observe(document, {attributes: true, subtree: true,
                          attributeFilter: ['class']});
"""

#: The wall's refresh, as a request: the page's own address with `fragment=1`.
_FRAGMENT = re.compile(r"[?&]fragment=1")
#: The page's clock where a test holds it: the refresh is a timer's.
_NOON = datetime(2026, 10, 16, 12, 0, 0, tzinfo=UTC)

#: A card whose level folds quiet boxes behind *+N more* (five quiet aspects past a
#: cap of three), one of them erupting with more lines than the budget shows, so a
#: nested box carries *⌄ all N*; and a card erupting on its own, with a title, so
#: its name is one the inspection card answers to.
_LEVEL = "/nas"
_NESTED = "/nas/zeta/probe"
_CARD = "/db"
_LINES = [f"line {number}: a reading the budget does not show" for number in range(12)]


def _estate() -> StatusTree:
    tree = StatusTree()
    for aspect in ("alpha", "beta", "gamma", "delta", "epsilon"):
        tree.upsert(f"{_LEVEL}/{aspect}/probe", StatusCode.OK)
    tree.upsert(_NESTED, StatusCode.ERROR, _LINES)
    tree.upsert(_CARD, StatusCode.ERROR, _LINES)
    tree.set_title(_CARD, "The database")
    tree.set_about(_CARD, "Where the readings are kept.")
    return tree


class _Quiet(WSGIRequestHandler):
    def log_message(self, format: str, *args: object) -> None:
        pass


class _BrowserCase(unittest.TestCase):
    """A real server and headless Chromium for a class of tests; for each test a
    page of a context of its own, signed in."""

    playwright: Any = None
    browser: Any = None
    server: WSGIServer | None = None
    base = ""
    drawn_in: ClassVar[dict[str, Any]] = {
        "viewport": {"width": 1000, "height": 700}, "reduced_motion": "reduce"}

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
        self.context = self.browser.new_context(**self.drawn_in)
        self.addCleanup(self.context.close)
        self.context.route("https://cdn.jsdelivr.net/**", self._vendored)
        self.page = self._signed_in(self.context)
        self.fragments: list[str] = []
        self.page.on("request", lambda request: (
            self.fragments.append(request.url)
            if _FRAGMENT.search(request.url) else None))

    def _signed_in(self, context: Any) -> Any:
        page = context.new_page()
        page.goto(f"{self.base}/login")
        page.fill("#username", "pan")
        page.fill("#password", "12345678")
        with page.expect_navigation():
            page.click("button[type=submit]")
        return page

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

    def _wall(self, page: Any | None = None, url: str = "/status") -> Any:
        """The wall on the page's own clock, stopped short of the first tick."""
        page = page or self.page
        page.clock.install(time=_NOON)
        page.goto(f"{self.base}{url}")
        page.wait_for_selector("#status-grid .status-card")
        page.clock.pause_at(_NOON + timedelta(seconds=5))
        return page

    def _more(self, page: Any | None = None) -> Any:
        page = page or self.page
        return page.locator(f'.node-children[data-branch="{_LEVEL}"] > .branch-more')

    def _level(self, page: Any | None = None) -> Any:
        page = page or self.page
        return page.locator(f'.node-children[data-branch="{_LEVEL}"]')

    def _chevron(self, path: str, page: Any | None = None) -> Any:
        """The *⌄ all N* of the node at ``path``, shown: after the block of its own
        lines, in a card's panel or a nested box (ADR-0127 decision 3)."""
        page = page or self.page
        return page.locator(
            f'.reason-block[data-reason-node="{path}"] + .reason-more:not([hidden])')

    def _block(self, path: str, page: Any | None = None) -> Any:
        page = page or self.page
        return page.locator(f'.reason-block[data-reason-node="{path}"]')

    def _map(self, page: Any | None = None) -> dict[str, Any] | None:
        raw = (page or self.page).evaluate(_MAP)
        return None if raw is None else json.loads(raw)

    def _swap(self, page: Any | None = None) -> None:
        """One tick of the refresh, and the swap it brings."""
        page = page or self.page
        page.evaluate("document.querySelector('#status-grid .status-card')"
                      ".dataset.drawn = 'before'")
        before = len(self.fragments)
        page.clock.run_for(10_000)
        page.wait_for_function(
            "document.querySelector('#status-grid [data-drawn]') === null",
            timeout=5000)
        self.assertGreater(len(self.fragments), before)

    def _open_both(self, page: Any | None = None) -> None:
        """Open the level's *+N more* and the card's *⌄ all N* by a click each."""
        page = page or self.page
        self._more(page).click()
        self._chevron(_CARD, page).click()
        self.assertTrue(self._level(page).evaluate(
            "level => level.classList.contains('is-expanded')"))
        self.assertTrue(self._block(_CARD, page).evaluate(
            "block => block.classList.contains('is-open')"))

    def _both_open(self, page: Any | None = None) -> tuple[bool, bool]:
        page = page or self.page
        return (self._level(page).evaluate(
                    "level => level.classList.contains('is-expanded')"),
                self._block(_CARD, page).evaluate(
                    "block => block.classList.contains('is-open')"))


class TreeStateTests(_BrowserCase):
    """A viewer's folds through the refresh and a reload, on a desk."""

    def test_a_fold_stands_through_the_refresh_and_a_reload(self):
        self._wall()
        self.assertEqual(self._both_open(), (False, False))
        self.assertIsNone(self._map())
        self._open_both()
        # the map holds the two entries, keyed by the level and by the block
        held = self._map()
        assert held is not None
        self.assertEqual(held["v"], 1)
        self.assertIsNone(held["mode"])
        self.assertEqual(held["nodes"], {_LEVEL: {"more": True},
                                         _CARD: {"lines": True}})
        # ten seconds on: the refresh swapped the grid, and both stand
        self._swap()
        self.assertEqual(self._both_open(), (True, True))
        # a reload of the tab: both stand, and the grid was held back until they
        # did — the pending class stood on <html> before the page's own scripts
        # ran, and is gone once the map is applied — and is shown
        self.page.add_init_script(_WATCH_PENDING)
        self.page.reload()
        self.page.wait_for_selector("#status-grid .status-card")
        self.assertEqual(self._both_open(), (True, True))
        self.assertTrue(self.page.evaluate("window.__pendingSeen"))
        self.assertFalse(self.page.evaluate(
            "document.documentElement.classList.contains('ls-tree-pending')"))
        self.assertEqual(self.page.evaluate(
            "getComputedStyle(document.getElementById('status-grid')).visibility"),
            "visible")
        # and a second click folds each again, which empties the map; a load with
        # an empty map hides nothing
        self._more().click()
        self._chevron(_CARD).click()
        self.assertEqual(self._both_open(), (False, False))
        self.assertIsNone(self._map())
        self.page.reload()
        self.page.wait_for_selector("#status-grid .status-card")
        self.assertFalse(self.page.evaluate("window.__pendingSeen"))
        # nothing of it went to a cookie
        self.assertEqual(sorted(cookie["name"] for cookie in self.context.cookies()),
                         sorted(cookie["name"] for cookie in self._cookies_at_login()))

    def _cookies_at_login(self) -> list[dict[str, Any]]:
        context = self.browser.new_context(**self.drawn_in)
        self.addCleanup(context.close)
        self._signed_in(context)
        return context.cookies()

    def test_a_nested_boxs_chevron_stands_too(self):
        # the nested box stands behind +N more? no: it fails, so it is shown; its
        # *⌄ all N* stands after its lines, in the box
        self._wall()
        self._chevron(_NESTED).click()
        self.assertTrue(self._block(_NESTED).evaluate(
            "block => block.classList.contains('is-open')"))
        self._swap()
        self.assertTrue(self._block(_NESTED).evaluate(
            "block => block.classList.contains('is-open')"))
        held = self._map()
        assert held is not None
        self.assertEqual(held["nodes"], {_NESTED: {"lines": True}})

    def test_a_new_tab_starts_as_configured(self):
        self._wall()
        self._open_both()
        other = self._signed_in(self.context)
        self._wall(other)
        self.assertEqual(self._both_open(other), (False, False))
        self.assertIsNone(self._map(other))
        # and the first tab's folds are its own still
        self.assertEqual(self._both_open(), (True, True))

    def test_the_focus_stays_on_its_control_through_a_swap(self):
        # a short window, the controls below its fold: the focus comes back to the
        # same control of the same node, and the wall does not scroll to it
        self.page.set_viewport_size({"width": 1000, "height": 300})
        self._wall()
        for name, control, node in (
                ("+N more", self._more(), lambda: self._more()),
                ("the chevron", self._chevron(_CARD), lambda: self._chevron(_CARD))):
            with self.subTest(control=name):
                control.evaluate("control => control.focus({preventScroll: true})")
                self.page.evaluate("window.scrollTo(0, 0)")
                self.assertTrue(control.evaluate(
                    "control => control === document.activeElement"))
                self._swap()
                self.assertTrue(node().evaluate(
                    "control => control === document.activeElement"), name)
                self.assertEqual(self.page.evaluate("window.scrollY"), 0)

    def test_an_open_inspection_card_stays_on_its_node(self):
        # the card on a pause, a viewer's choice since the library's look is `off`
        self.context.add_cookies([looks(self.base, inspection_card="pause")])
        self._wall()
        name = self.page.locator(
            f'.status-card__head[data-path="{_CARD}"] .status-card__name')
        name.hover()
        self.page.clock.run_for(700)          # the pause the card waits for
        card = self.page.locator("#inspect-card")
        self.page.wait_for_function(
            "!document.getElementById('inspect-card').hidden", timeout=3000)
        self.assertIn("The database", card.inner_text())
        self.assertEqual(name.get_attribute("aria-describedby"), "inspect-card")
        old = name.element_handle()
        self._swap()
        self.page.wait_for_timeout(200)       # a hide, if one came, has come
        self.assertFalse(card.evaluate("card => card.hidden"))
        # on the name the swap brought, which is another element than the old
        self.assertFalse(old.evaluate("name => name.isConnected"))
        self.assertEqual(name.get_attribute("aria-describedby"), "inspect-card")
        # the card stands at its node still, not where the old element was
        left = "element => element.getBoundingClientRect().left"
        head = self.page.locator(f'.status-card__head[data-path="{_CARD}"]')
        self.assertLess(abs(card.evaluate(left) - head.evaluate(left)),
                        head.evaluate("head => head.getBoundingClientRect().width"))

    def test_the_system_page_refreshes_as_before(self):
        # no map there, and nothing called: the swap comes, and the console says
        # nothing
        errors: list[str] = []
        self.page.on("console", lambda message: (
            errors.append(message.text) if message.type == "error" else None))
        self.page.on("pageerror", lambda error: errors.append(str(error)))
        self.page.clock.install(time=_NOON)
        self.page.goto(f"{self.base}/system")
        self.page.wait_for_selector("#system-info")
        self.page.clock.pause_at(_NOON + timedelta(seconds=5))
        self.assertIsNone(self.page.evaluate("window.lsTree || null"))
        self.page.evaluate(
            "document.querySelector('#system-info > *').dataset.drawn = 'before'")
        self.page.clock.run_for(10_000)
        self.page.wait_for_function(
            "document.querySelector('#system-info [data-drawn]') === null",
            timeout=5000)
        self.assertEqual(errors, [])

    def test_a_map_of_another_version_is_dropped_whole(self):
        self._wall()
        self.page.evaluate(
            f"window.sessionStorage.setItem({_KEY!r}, JSON.stringify("
            f"{{v: 2, mode: null, nodes: {{{_LEVEL!r}: {{more: true}}}}}}))")
        self.page.reload()
        self.page.wait_for_selector("#status-grid .status-card")
        self.assertEqual(self._both_open(), (False, False))
        self.assertIsNone(self._map())

    def test_without_storage_the_map_lives_for_the_page(self):
        # a browser that refuses storage: a fold still stands through the refresh,
        # and a reload starts as configured
        self.page.add_init_script(
            "Object.defineProperty(window, 'sessionStorage', "
            "{get() { throw new Error('no storage here'); }});")
        errors: list[str] = []
        self.page.on("pageerror", lambda error: errors.append(str(error)))
        self._wall()
        self._open_both()
        self._swap()
        self.assertEqual(self._both_open(), (True, True))
        self.page.reload()
        self.page.wait_for_selector("#status-grid .status-card")
        self.assertEqual(self._both_open(), (False, False))
        self.assertEqual(errors, [])


class KioskTests(_BrowserCase):
    """On the kiosk the map lives in memory, and five minutes without input empty
    it; a reload starts as configured, and a bookmark's `depth=` stays."""

    def setUp(self) -> None:
        super().setUp()
        self.context.add_cookies([{"name": "ls_prefs", "url": self.base,
                                   "value": "layout=kiosk"}])

    def test_the_kiosk_keeps_nothing_past_five_minutes_without_input(self):
        self._wall(url="/status?depth=8")
        self.assertEqual(self.page.evaluate("document.body.dataset.lsLayout"), "kiosk")
        self._open_both()
        # a reload starts as configured, and nothing was written to the storage
        self.assertIsNone(self._map())
        self.page.reload()
        self.page.wait_for_selector("#status-grid .status-card")
        self.assertEqual(self._both_open(), (False, False))
        self.page.clock.pause_at(_NOON + timedelta(seconds=5))
        self._open_both()
        # a pointer that only moves holds them off: four minutes, a move, four more
        self.page.clock.run_for(4 * 60_000)
        self.page.mouse.move(40, 40)
        self.page.clock.run_for(4 * 60_000)
        self.assertEqual(self._both_open(), (True, True))
        # five minutes without any input: the first look is back, the depth with it
        self.page.clock.run_for(5 * 60_000 + 1000)
        self.assertEqual(self._both_open(), (False, False))
        self.assertIn("depth=8", self.page.url)
        self.assertIsNone(self._map())


class LostChildrenTests(_BrowserCase):
    """A branch's page polls on after a run named none of its children: the refresh
    is answered with a fragment, not a leaf's page the script would read as a lost
    session (ADR-0127 decision 10); the next load of the address is the leaf's page."""

    def tearDown(self) -> None:
        app_module.status_tree = _estate()

    def test_the_page_polls_on_after_its_children_left(self):
        self._wall(url=f"/status{_LEVEL}")
        cards = self.page.locator("#status-grid .status-card")
        self.assertGreater(cards.count(), 1)
        app_module.status_tree.prune(_LEVEL, keep=())
        self._swap()
        # the swap came and said what stands there; nothing rose above the grid
        self.assertEqual(self.page.locator(".poll-alert").count(), 0)
        stamp = " ".join(self.page.locator("#status-updated").inner_text().split())
        self.assertTrue(stamp.startswith("updated"), stamp)
        self.assertNotIn("could not", stamp)
        self.assertIn("Nothing stands beneath nas now.",
                      self.page.locator("#status-grid").inner_text())
        self.assertEqual(cards.count(), 0)
        # and a load of the address is the leaf's page
        self.page.reload()
        self.page.wait_for_selector(".ls-crumbs")
        self.assertEqual(self.page.locator("#status-grid").count(), 0)
        self.assertIn("nas", self.page.title())

