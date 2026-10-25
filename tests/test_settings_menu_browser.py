"""The settings menu stands open while a viewer chooses, held against a real browser
(ADR-0029).

A click inside the menu no longer closes it, and the page a choice reloads opens it
again with the focus on that choice, which is in force there; Escape and a click outside
close it; a filter switch of the band, which reloads the page too, leaves it shut; and
where the tab's session storage is refused the page a choice brings stands with the menu
shut, as it always did. Served by a real server to headless Chromium. Skipped wherever
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
from tests.browser_server import PageServer

try:  # pragma: no cover - environment probe
    from playwright.sync_api import sync_playwright
except ImportError:  # pragma: no cover
    sync_playwright = None  # type: ignore[assignment]

_SANDBOX_CHROMIUM = Path("/opt/pw-browsers/chromium-1194/chrome-linux/chrome")
_BOOTSTRAP = (Path(__file__).resolve().parent.parent / "var" / "bootstrap"
              / "node_modules" / "bootstrap" / "dist")

_DESK = {"viewport": {"width": 1280, "height": 800}}

#: Whether the menu stands open, and the choice the focus is on.
_STATE = """() => {
    const focused = document.activeElement;
    return {open: document.querySelector('.ls-menu__panel').classList.contains('show'),
            expanded: document.getElementById('ls-settings')
                .getAttribute('aria-expanded'),
            focus: focused && focused.matches('.ls-menu__radio')
                ? `${focused.name}=${focused.value}` : null,
            left: sessionStorage.getItem('ls-menu-reopen')};
}"""

#: A tab whose session storage is refused, as a browser's privacy setting refuses it.
_NO_STORAGE = """
Object.defineProperty(window, 'sessionStorage', {
    get() { throw new DOMException('refused', 'SecurityError'); }});
"""


class _Quiet(WSGIRequestHandler):
    def log_message(self, format: str, *args: object) -> None:
        pass


class SettingsMenuBrowserTests(unittest.TestCase):
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
        tree.upsert("/servers/web02", StatusCode.ERROR, "down")
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

    def _page(self, *, storage: bool = True) -> Any:
        """``/status`` signed in at a desk; where ``storage`` is false, in a tab whose
        session storage is refused."""
        context = self.browser.new_context(reduced_motion="reduce", **_DESK)
        self.addCleanup(context.close)
        if not storage:
            context.add_init_script(_NO_STORAGE)
        page = context.new_page()
        self.errors: list[str] = []
        page.on("pageerror", lambda error: self.errors.append(str(error)))
        page.route("https://cdn.jsdelivr.net/**", self._vendored)
        page.goto(f"{self.base}/login")
        page.fill("#username", "pan")
        page.fill("#password", "12345678")
        with page.expect_navigation():
            page.click("button[type=submit]")
        page.goto(f"{self.base}/status")
        return page

    def _open(self, page: Any) -> None:
        page.wait_for_function("() => typeof window.bootstrap?.Dropdown === 'function'")
        page.click("#ls-settings")
        page.wait_for_selector(".ls-menu__panel.show")

    def _choose(self, page: Any, key: str, value: str) -> None:
        """A click on one choice of the menu, and the page it brings."""
        with page.expect_navigation():
            page.click(f'.ls-menu__radio[name="{key}"][value="{value}"]')
        page.wait_for_load_state()

    def _state(self, page: Any) -> dict[str, Any]:
        state: dict[str, Any] = page.evaluate(_STATE)
        return state

    def test_a_click_inside_keeps_it_open(self) -> None:
        # the choice already in force, which changes nothing, and a heading: each used
        # to close the menu, Bootstrap closing it on every click
        page = self._page()
        self._open(page)
        page.click('.ls-menu__radio[name="theme"]:checked')
        page.click("#ls-menu-heading-theme")
        state = self._state(page)
        self.assertTrue(state["open"], state)
        self.assertEqual(state["expanded"], "true", state)

    def test_a_choice_brings_the_page_back_with_the_menu_open_on_it(self) -> None:
        page = self._page()
        self._open(page)
        self._choose(page, "boxes", "packed")
        page.wait_for_selector(".ls-menu__panel.show")
        state = self._state(page)
        self.assertEqual(state["focus"], "boxes=packed", state)
        self.assertEqual(page.get_attribute("body", "data-ls-boxes"), "packed")
        self.assertIsNone(state["left"], "the entry is read once and gone")
        # and the next choice the same way, from the menu the last one opened
        self._choose(page, "toggle_hover", "outline")
        page.wait_for_selector(".ls-menu__panel.show")
        state = self._state(page)
        self.assertEqual(state["focus"], "toggle_hover=outline", state)
        self.assertEqual(page.get_attribute("body", "data-ls-toggle-hover"), "outline")
        # a reload of that page, which no choice brought, opens nothing
        page.reload()
        page.wait_for_load_state()
        self.assertFalse(self._state(page)["open"])
        self.assertEqual(self.errors, [])

    def test_escape_and_a_click_outside_close_it(self) -> None:
        page = self._page()
        self._open(page)
        page.keyboard.press("Escape")
        self.assertFalse(self._state(page)["open"])
        self._open(page)
        page.click(".ls-band__title", position={"x": 2, "y": 2})
        self.assertFalse(self._state(page)["open"])
        self.assertEqual(page.url, f"{self.base}/status")

    def test_a_filter_switch_leaves_it_shut(self) -> None:
        # the band's switch reloads the page as a choice does, from outside the menu
        page = self._page()
        with page.expect_navigation():
            page.click("label[for=hide_ok]")
        page.wait_for_load_state()
        self.assertTrue(page.is_checked("#hide_ok"))
        state = self._state(page)
        self.assertFalse(state["open"], state)
        self.assertIsNone(state["left"], state)

    def test_without_the_tabs_storage_the_menu_stands_shut_as_it_did(self) -> None:
        page = self._page(storage=False)
        self._open(page)
        self._choose(page, "boxes", "packed")
        self.assertEqual(page.get_attribute("body", "data-ls-boxes"), "packed")
        self.assertFalse(page.evaluate(
            "() => document.querySelector('.ls-menu__panel').classList"
            ".contains('show')"))
        self.assertEqual(self.errors, [])


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
