"""The account of using the wall at `/help`, held against a real browser (ADR-0136).

``tests/test_help.py`` holds what the response says. What a browser does is this file's:
the settings menu's foot leads to the account and stands in the menu's room at a desk —
at the last column's foot, the menu no taller for it — in every theme, and at the
menu's end on a phone; and an address that names a section of the account opens it
beneath the sticky bar. Served by a real server to headless Chromium. Skipped wherever
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
from little_sister.status import StatusCode
from little_sister.tree import StatusTree
from tests.browser_looks import looks
from tests.browser_server import PageServer

try:  # pragma: no cover - environment probe
    from playwright.sync_api import sync_playwright
except ImportError:  # pragma: no cover
    sync_playwright = None  # type: ignore[assignment]

_SANDBOX_CHROMIUM = Path("/opt/pw-browsers/chromium-1194/chrome-linux/chrome")
_BOOTSTRAP = (Path(__file__).resolve().parent.parent / "var" / "bootstrap"
              / "node_modules" / "bootstrap" / "dist")

_DESK = {"viewport": {"width": 1280, "height": 800}}
_PHONE = {"viewport": {"width": 390, "height": 800}}

#: Where the link stands in the open menu: whether the menu scrolls to show it, which
#: of its columns it stands in, and whether anything of its column stands below it.
_FOOT = """() => {
    const panel = document.querySelector('.ls-menu__panel');
    const box = panel.getBoundingClientRect();
    const link = panel.querySelector('.ls-menu__help');
    const own = link.getBoundingClientRect();
    const columns = parseInt(getComputedStyle(
        panel.querySelector('.ls-menu__groups')).columnCount, 10) || 1;
    const column = el => Math.min(columns, Math.floor(
        (el.getBoundingClientRect().left - box.left + 1) / (box.width / columns)) + 1);
    const below = [...panel.querySelectorAll('label, .ls-menu__heading')]
        .filter(el => column(el) === column(link)
            && el.getBoundingClientRect().top >= own.bottom - 0.5).length;
    return {scrolls: panel.scrollHeight > panel.clientHeight + 1,
            inside: own.left >= box.left - 0.5 && own.right <= box.right + 0.5
                && own.top >= box.top - 0.5 && own.bottom <= box.bottom + 0.5,
            column: column(link), columns: columns, below: below, height: box.height};
}"""


class _Quiet(WSGIRequestHandler):
    def log_message(self, format: str, *args: object) -> None:
        pass


class HelpBrowserTests(unittest.TestCase):
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
        tree.upsert("/servers/web01", StatusCode.OK, "up")
        app_module.status_tree = tree
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

    @staticmethod
    def _vendored(route: Any) -> None:
        name = route.request.url.rsplit("/", 1)[-1]
        for candidate in (_BOOTSTRAP / "css" / name, _BOOTSTRAP / "js" / name):
            if candidate.is_file():
                route.fulfill(path=str(candidate))
                return
        route.continue_()

    def _page(self, address: str, theme: str | None = None, **context_args: Any) -> Any:
        context = self.browser.new_context(reduced_motion="reduce", **context_args)
        self.addCleanup(context.close)
        if theme is not None:
            context.add_cookies([looks(self.base, theme=theme)])
        page = context.new_page()
        page.route("https://cdn.jsdelivr.net/**", self._vendored)
        page.goto(f"{self.base}/login")
        page.fill("#username", "pan")
        page.fill("#password", "12345678")
        with page.expect_navigation():
            page.click("button[type=submit]")
        page.goto(f"{self.base}{address}")
        return page

    def _menu(self, page: Any) -> None:
        page.wait_for_function("typeof window.bootstrap?.Dropdown === 'function'")
        page.click("#ls-settings")
        page.wait_for_selector(".ls-menu__panel.show")

    def test_the_menus_foot_leads_to_the_account_in_the_menus_room(self) -> None:
        # at a desk the link stands at the last column's foot, the third, inside the
        # menu, and the menu fits a laptop's window as it did without it — in the
        # library's theme and in the light one, whose letters are another font's
        for theme in (None, "plain"):
            with self.subTest(theme=theme or "cyberpunk"):
                page = self._page("/status", theme, **_DESK)
                self._menu(page)
                got: dict[str, Any] = page.evaluate(_FOOT)
                self.assertFalse(got["scrolls"], got)
                self.assertTrue(got["inside"], got)
                self.assertEqual(got["columns"], 3, got)
                self.assertEqual(got["column"], 3, got)
                self.assertEqual(got["below"], 0, got)
        page.click(".ls-menu__help")
        page.wait_for_url(f"{self.base}/help")
        self.assertEqual(page.locator(".ls-help h1").inner_text(), "Using the wall")

    def test_on_a_phone_it_ends_the_menu(self) -> None:
        page = self._page("/status", **_PHONE)
        self._menu(page)
        page.evaluate("() => { const p = document.querySelector('.ls-menu__panel');"
                      " p.scrollTop = p.scrollHeight; }")
        got: dict[str, Any] = page.evaluate(_FOOT)
        self.assertEqual(got["column"], 1, got)
        self.assertEqual(got["below"], 0, got)
        self.assertTrue(got["inside"], got)

    def test_an_address_that_names_a_section_opens_it_beneath_the_bar(self) -> None:
        page = self._page("/help#the-settings-menu", **_DESK)
        page.wait_for_function("() => scrollY > 0")
        got = page.evaluate("""() => ({
            bar: document.querySelector('.ls-bar').getBoundingClientRect().bottom,
            heading: document.getElementById('the-settings-menu')
                .getBoundingClientRect().top})""")
        self.assertGreaterEqual(got["heading"], got["bar"], got)
        self.assertLess(got["heading"] - got["bar"], 64, got)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
