"""The engine's own pill above the wall holds on a phone — held against a real browser.

The wall lifts the instance's own node out of its cards into a pill: an eye, the
node's name, its title where it has one, and how it stands. On a phone there is no
room for a title of any length beside the rest, and the pill gave way where it should
not: its name broke in two or its state took a second line, and the title was squeezed
to a few letters and dots. A title has a width of its own — what it says, up to the
length every title on the wall is kept to — and the pill shows it at that width or
not at all: where there is no room for it beside the name and the state, the title
steps out. It is the node's, and its page and its inspection card still say it.

Served by a real server to headless Chromium at a desk's width and emulating a phone.
Skipped wherever Playwright or a Chromium binary is unavailable, so the ordinary gate
does not grow a browser dependency (``docs/testing-the-gui.md``, Mode 5).
"""
from __future__ import annotations

import threading
import unittest
from pathlib import Path
from typing import Any
from wsgiref.simple_server import WSGIRequestHandler, WSGIServer, make_server

from little_sister import app as app_module
from little_sister.status import HEARTBEAT_PATH, StatusCode
from little_sister.tree import StatusTree

try:  # pragma: no cover - environment probe
    from playwright.sync_api import sync_playwright
except ImportError:  # pragma: no cover
    sync_playwright = None  # type: ignore[assignment]

_SANDBOX_CHROMIUM = Path("/opt/pw-browsers/chromium-1194/chrome-linux/chrome")
_BOOTSTRAP = (Path(__file__).resolve().parent.parent / "var" / "bootstrap"
              / "node_modules" / "bootstrap" / "dist")

_PHONE = {"viewport": {"width": 375, "height": 812}, "device_scale_factor": 2,
          "is_mobile": True, "has_touch": True,
          "user_agent": ("Mozilla/5.0 (Linux; Android 14; Pixel 8) "
                         "AppleWebKit/537.36 (KHTML, like Gecko) "
                         "Chrome/126.0.0.0 Mobile Safari/537.36")}
_DESK = {"viewport": {"width": 1000, "height": 800}}

#: A title a phone's pill has no room for, and one it has.
_LONG = "The instance that watches the others, and itself"
_SHORT = "itself"

#: The pill: how many lines it and its name take, whether its state is inside it, and
#: how wide its title is shown — nothing where it stepped out.
_PILL = """() => {
    const pill = document.querySelector('.ls-strip');
    const at = pill.getBoundingClientRect();
    const name = pill.querySelector('.ls-strip__name');
    const state = pill.querySelector('.ls-strip__state').getBoundingClientRect();
    const title = pill.querySelector('.node-title');
    let seen = 0;
    if (title) {
        const box = title.getBoundingClientRect();
        const frame = title.parentElement.getBoundingClientRect();
        // out of sight: beneath the one line its frame shows, and not painted there
        const there = document.elementFromPoint(box.left + box.width / 2,
                                                box.top + box.height / 2);
        const painted = there !== null && title.contains(there);
        seen = box.top >= frame.bottom - 0.5 && !painted ? 0 : Math.round(box.width);
        if (box.top >= frame.bottom - 0.5 && painted) { seen = -1; }
    }
    return {high: at.height, line: parseFloat(getComputedStyle(pill).lineHeight),
            name_lines: name.getClientRects().length, title: seen,
            state_inside: state.right <= at.right + 0.5 && state.left >= at.left,
            on_screen: at.left >= 0 && at.right <= window.innerWidth + 0.5};
}"""


class _Quiet(WSGIRequestHandler):
    def log_message(self, format: str, *args: object) -> None:
        pass


class StripBrowserTests(unittest.TestCase):
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

    def _pill(self, title: str | None, **drawn_in: Any) -> dict[str, Any]:
        tree = StatusTree()
        for host in ("alpha", "beta"):
            tree.upsert(f"/{host}/cpu", StatusCode.OK, "within its limits")
        tree.upsert(HEARTBEAT_PATH, StatusCode.WARN, "the last tick took 4.2 seconds")
        if title is not None:
            tree.set_title(HEARTBEAT_PATH, title)
        app_module.status_tree = tree
        context = self.browser.new_context(reduced_motion="reduce", **drawn_in)
        self.addCleanup(context.close)
        page = context.new_page()
        page.route("https://cdn.jsdelivr.net/**", self._vendored)
        page.goto(f"{self.base}/login")
        page.fill("#username", "pan")
        page.fill("#password", "12345678")
        with page.expect_navigation():
            page.click("button[type=submit]")
        page.goto(f"{self.base}/status")
        page.wait_for_selector(".ls-strip")
        pill: dict[str, Any] = page.evaluate(_PILL)
        return pill

    @staticmethod
    def _vendored(route: Any) -> None:
        name = route.request.url.rsplit("/", 1)[-1]
        for candidate in (_BOOTSTRAP / "css" / name, _BOOTSTRAP / "js" / name):
            if candidate.is_file():
                route.fulfill(path=str(candidate))
                return
        route.continue_()

    def _one_line(self, pill: dict[str, Any]) -> None:
        self.assertEqual(pill["name_lines"], 1, pill)
        # one line of text and the pill's own padding and border
        self.assertLess(pill["high"], pill["line"] * 1.5, pill)
        self.assertTrue(pill["state_inside"], pill)
        self.assertTrue(pill["on_screen"], pill)

    def test_on_a_desk_a_title_has_its_own_width(self) -> None:
        long, short = self._pill(_LONG, **_DESK), self._pill(_SHORT, **_DESK)
        self._one_line(long)
        self._one_line(short)
        self.assertGreater(short["title"], 10, short)
        # a long one is kept to the length every title on the wall is
        self.assertGreater(long["title"], 3 * short["title"], long)

    def test_on_a_phone_a_long_title_steps_out_and_the_pill_is_one_line(self) -> None:
        # the narrowest phone: at 375 pixels the page has the screen's whole width
        # since the rail gives way there, and this title has room
        pill = self._pill(_LONG, **{**_PHONE, "viewport": {"width": 320,
                                                            "height": 812}})
        self._one_line(pill)
        # 0 is out of sight; a title painted beneath the pill would read -1
        self.assertEqual(pill["title"], 0, pill)

    def test_on_a_phone_a_title_there_is_room_for_is_shown_at_its_width(self) -> None:
        pill = self._pill(_SHORT, **_PHONE)
        self._one_line(pill)
        self.assertEqual(pill["title"], self._pill(_SHORT, **_DESK)["title"], pill)

    def test_a_title_is_never_squeezed(self) -> None:
        # at every width between a phone and a desk it is as wide as on the desk, or
        # it is not there
        full = self._pill(_LONG, **_DESK)["title"]
        for width in (375, 420, 480, 560, 640):
            with self.subTest(width=width):
                pill = self._pill(_LONG, viewport={"width": width, "height": 800})
                self._one_line(pill)
                self.assertIn(pill["title"], (0, full), pill)

    def test_a_pill_without_a_title_is_as_it_was(self) -> None:
        self._one_line(self._pill(None, **_PHONE))

