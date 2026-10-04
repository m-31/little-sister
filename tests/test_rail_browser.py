"""On a phone the rail gives way to the top bar — held against a real browser.

The rail keeps its 52 pixels at every width, and on a phone that is a seventh of the
screen. Below 576 pixels a viewer whose layout is the rail gets the top-bar layout as
it is at that width: no rail, the bar's sections folded behind its toggler, the page
at the screen's full width. The preference is not touched, so the rail is back when
the window is wide again. The top-bar layout and the kiosk are as they were.

Served by a real server to headless Chromium. Skipped wherever Playwright or a
Chromium binary is unavailable, so the ordinary gate does not grow a browser
dependency (``docs/testing-the-gui.md``, Mode 5).
"""
from __future__ import annotations

import threading
import unittest
from pathlib import Path
from typing import Any
from wsgiref.simple_server import WSGIRequestHandler, WSGIServer, make_server

from little_sister import app as app_module
from little_sister.status import StatusCode
from little_sister.tree import StatusTree

try:  # pragma: no cover - environment probe
    from playwright.sync_api import sync_playwright
except ImportError:  # pragma: no cover
    sync_playwright = None  # type: ignore[assignment]

_SANDBOX_CHROMIUM = Path("/opt/pw-browsers/chromium-1194/chrome-linux/chrome")
_BOOTSTRAP = (Path(__file__).resolve().parent.parent / "var" / "bootstrap"
              / "node_modules" / "bootstrap" / "dist")

#: What shows of the navigation, and how wide the page is beside it.
_SHOWN = """() => {
    const seen = (selector) => {
        const found = document.querySelector(selector);
        if (!found) { return false; }
        const box = found.getBoundingClientRect();
        return getComputedStyle(found).display !== 'none'
            && box.width > 0 && box.height > 0;
    };
    const page = document.querySelector('.ls-page').getBoundingClientRect();
    return {rail: seen('.ls-rail'), toggler: seen('.ls-bar__toggler'),
            sections: seen('.ls-bar__nav .nav-link'),
            page_left: Math.round(page.left), page_width: Math.round(page.width),
            screen: window.innerWidth,
            scrolls: document.documentElement.scrollWidth > window.innerWidth,
            layout: document.body.dataset.lsLayout};
}"""

#: The widest card's state line against the screen: whether it runs out of it.
_STATE_FITS = """() => [...document.querySelectorAll('.status-node__state, .card')]
    .every((found) => found.getBoundingClientRect().right <= window.innerWidth + 0.5)"""


class _Quiet(WSGIRequestHandler):
    def log_message(self, format: str, *args: object) -> None:
        pass


class RailBrowserTests(unittest.TestCase):
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
        tree = StatusTree()
        for host in ("alpha", "beta"):
            tree.upsert(f"/{host}/cpu", StatusCode.OK, "within its limits")
            tree.upsert(f"/{host}/disk", StatusCode.WARN, "83% used on /")
        app_module.status_tree = tree
        cls.server = make_server("127.0.0.1", 0, app_module.app, handler_class=_Quiet)
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

    @staticmethod
    def _vendored(route: Any) -> None:
        name = route.request.url.rsplit("/", 1)[-1]
        for candidate in (_BOOTSTRAP / "css" / name, _BOOTSTRAP / "js" / name):
            if candidate.is_file():
                route.fulfill(path=str(candidate))
                return
        route.continue_()

    def _page(self, width: int, layout: str = "rail") -> Any:
        context = self.browser.new_context(
            reduced_motion="reduce", viewport={"width": width, "height": 800})
        self.addCleanup(context.close)
        context.add_cookies([{"name": "ls_prefs", "value": f"layout={layout}",
                              "url": self.base}])
        page = context.new_page()
        page.route("https://cdn.jsdelivr.net/**", self._vendored)
        page.goto(f"{self.base}/login")
        page.fill("#username", "pan")
        page.fill("#password", "12345678")
        with page.expect_navigation():
            page.click("button[type=submit]")
        page.goto(f"{self.base}/status")
        page.wait_for_selector(".ls-page")
        return page

    def _shown(self, width: int, layout: str = "rail") -> dict[str, Any]:
        shown: dict[str, Any] = self._page(width, layout).evaluate(_SHOWN)
        self.assertEqual(shown["layout"], layout, shown)
        return shown

    def test_on_a_phone_the_rail_is_gone_and_the_bars_toggler_stands(self) -> None:
        for width in (320, 375, 575):
            with self.subTest(width=width):
                shown = self._shown(width)
                self.assertFalse(shown["rail"], shown)
                self.assertTrue(shown["toggler"], shown)
                # folded: the sections are behind the toggler until it is opened
                self.assertFalse(shown["sections"], shown)
                self.assertEqual((shown["page_left"], shown["page_width"]),
                                 (0, width), shown)
                self.assertFalse(shown["scrolls"], shown)

    def test_from_576_pixels_the_rail_stands_as_before(self) -> None:
        for width in (576, 700, 1000, 1400):
            with self.subTest(width=width):
                shown = self._shown(width)
                self.assertTrue(shown["rail"], shown)
                self.assertFalse(shown["toggler"], shown)
                self.assertFalse(shown["sections"], shown)
                self.assertEqual(shown["page_left"], 52, shown)

    def test_on_a_phone_the_toggler_opens_the_sections_and_they_lead(self) -> None:
        page = self._page(375)
        page.click(".ls-bar__toggler")
        page.wait_for_selector(".ls-bar__nav.show")
        opened = page.evaluate(_SHOWN)
        self.assertTrue(opened["sections"], opened)
        self.assertFalse(opened["scrolls"], opened)
        with page.expect_navigation():
            page.click(".ls-bar__nav .nav-link[href='/events']")
        self.assertTrue(page.url.endswith("/events"))

    def test_on_a_phone_it_is_the_top_bars_own_layout(self) -> None:
        # the same parts in the same places as a viewer who chose the top bar has
        as_rail, as_bar = self._page(375), self._page(375, "topbar")
        places = """() => ['.ls-brand', '.ls-bar__toggler', '.ls-bar__who', '.ls-page']
            .map((selector) => {
                const box = document.querySelector(selector).getBoundingClientRect();
                return [selector, Math.round(box.left), Math.round(box.top),
                        Math.round(box.width)];
            })"""
        self.assertEqual(as_rail.evaluate(places), as_bar.evaluate(places))

    def test_the_preference_is_kept_and_the_rail_returns_with_the_width(self) -> None:
        page = self._page(375)
        self.assertFalse(page.evaluate(_SHOWN)["rail"])
        page.set_viewport_size({"width": 900, "height": 800})
        wide = page.evaluate(_SHOWN)
        self.assertTrue(wide["rail"], wide)
        self.assertEqual(wide["layout"], "rail")
        # and the settings menu still says which layout is chosen
        self.assertTrue(page.evaluate(
            "() => document.querySelector(\"input[name=layout][value=rail]\").checked"))

    def test_the_top_bar_layout_is_as_it_was(self) -> None:
        for width, toggler in ((375, True), (700, True), (1000, False)):
            with self.subTest(width=width):
                shown = self._shown(width, "topbar")
                self.assertFalse(shown["rail"], shown)
                self.assertEqual(shown["toggler"], toggler, shown)
                self.assertEqual(shown["sections"], not toggler, shown)

    def test_with_the_rail_chosen_a_wall_fits_320_pixels(self) -> None:
        page = self._page(320)
        self.assertTrue(page.evaluate(_STATE_FITS))
        self.assertFalse(page.evaluate(_SHOWN)["scrolls"])


if __name__ == "__main__":
    unittest.main()
