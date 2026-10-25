"""A node's handbook on its page, held against a real browser (ADR-0133 decision 3).

``tests/test_handbook_tab.py`` holds what the response says: the tab, the anchors on
the headings, a link into a section without a tab of its own. What a browser does with
them is this file's: a link into a section opens it beneath the sticky bar rather than
under it, in the page and not in a tab of its own, and so does an address that names a
section; and on a phone a handbook's long line of code, its long word and a table wider
than the screen keep to it, the table scrolling sideways inside itself. Served by a real
server to headless Chromium. Skipped wherever Playwright or a Chromium binary is
unavailable, so the ordinary gate does not grow a browser dependency
(``docs/testing-the-gui.md``, Mode 5).
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
_PHONE = {
    "viewport": {"width": 390, "height": 844},
    "device_scale_factor": 3,
    "is_mobile": True,
    "has_touch": True,
    "user_agent": ("Mozilla/5.0 (Linux; Android 14; Pixel 8) AppleWebKit/537.36 "
                   "(KHTML, like Gecko) Chrome/140.0.0.0 Mobile Safari/537.36"),
}

#: A runbook long enough that its section is well below the first screen, and goes on
#: for more than a screen after it, so that the page can bring it to the top.
_HANDBOOK = "\n\n".join([
    "# Servers",
    "[When it fails](#when-it-fails) · [Sign in](#sign-in)",
    "## Sign in",
    "Through the bastion, as yourself:",
    "    ssh -J bastion.example.org -o ServerAliveInterval=30 -o "
    "ServerAliveCountMax=4 web01.internal.example.org journalctl -u gateway -f",
    "A word longer than a phone: "
    "averyveryverylongidentifierthatnobodywouldeverbreakbyhand_0123456789abcdef.",
    "| Who | Where | When | How |\n|---|---|---|---|\n"
    "| the platform team's on-call engineer | the operations channel, then the "
    "on-call number | at any hour | `ssh -J bastion.example.org web01.example.org` |",
    *(f"Paragraph {number}: what holds for every server beneath this node, said at "
      f"length, as a runbook says it." for number in range(40)),
    "## When it fails",
    "### {error}: the disk",
    *(f"Step {number}: what to do, in the order it is done." for number in range(40)),
])

#: Where the bar ends and where the section's heading stands, the page's width against
#: its screen, and the table's against the column it stands in.
_PLACED = """() => {
    const bar = document.querySelector('.ls-bar').getBoundingClientRect();
    const heading = document.getElementById('when-it-fails').getBoundingClientRect();
    const table = document.querySelector('.ls-handbook table');
    const column = document.querySelector('.ls-handbook').getBoundingClientRect();
    return {bar: bar.bottom, heading: heading.top, scrolled: scrollY,
            hash: location.hash, path: location.pathname,
            over: document.documentElement.scrollWidth - window.innerWidth,
            table: table.getBoundingClientRect().width, column: column.width,
            scrolls: table.scrollWidth > table.clientWidth};
}"""


class _Quiet(WSGIRequestHandler):
    def log_message(self, format: str, *args: object) -> None:
        pass


class HandbookBrowserTests(unittest.TestCase):
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
        tree.set_handbook("/servers", _HANDBOOK)
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

    def _page(self, address: str, **context_args: Any) -> Any:
        context = self.browser.new_context(reduced_motion="reduce", **context_args)
        self.addCleanup(context.close)
        page = context.new_page()
        page.route("https://cdn.jsdelivr.net/**", self._vendored)
        page.goto(f"{self.base}/login")
        page.fill("#username", "pan")
        page.fill("#password", "12345678")
        with page.expect_navigation():
            page.click("button[type=submit]")
        page.goto(f"{self.base}{address}")
        page.wait_for_selector(".ls-handbook")
        return page

    def _beneath_the_bar(self, got: dict[str, Any]) -> None:
        self.assertGreater(got["scrolled"], 0, got)
        self.assertGreaterEqual(got["heading"], got["bar"], got)
        self.assertLess(got["heading"] - got["bar"], 64, got)

    def test_a_link_into_a_section_opens_it_beneath_the_bar_in_the_page(self) -> None:
        page = self._page("/handbook/servers", **_DESK)
        pages = len(page.context.pages)
        page.click(".ls-handbook a[href='#when-it-fails']")
        page.wait_for_function("() => location.hash === '#when-it-fails'")
        got: dict[str, Any] = page.evaluate(_PLACED)
        self._beneath_the_bar(got)
        self.assertEqual(got["path"], "/handbook/servers", got)
        self.assertEqual(len(page.context.pages), pages)

    def test_an_address_that_names_a_section_opens_there(self) -> None:
        page = self._page("/handbook/servers#when-it-fails", **_DESK)
        page.wait_for_function("() => scrollY > 0")
        self._beneath_the_bar(page.evaluate(_PLACED))

    def test_on_a_phone_its_long_line_word_and_table_keep_to_the_screen(self) -> None:
        # the table, wider than a phone, scrolls sideways inside itself
        page = self._page("/handbook/servers", **_PHONE)
        got: dict[str, Any] = page.evaluate(_PLACED)
        self.assertLessEqual(got["over"], 0, got)
        self.assertLessEqual(got["table"], got["column"], got)
        self.assertTrue(got["scrolls"], got)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
