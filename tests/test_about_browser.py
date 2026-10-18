"""About is no wider than its screen, and no word of its rings is cut — held against a
real browser.

The hero's two rings were as wide as a share of the **window**, and the page they
stand on is narrower than the window by the rail and its own margins. So below a wide
screen a ring reached past the page: the terms at its two ends were cut — by the rail
on one side, by the window's edge on the other — and the page scrolled sideways. A
ring is as wide as its field allows now, less the room a term at its end needs.

A term travels along its ring, so where it stands when a test looks proves little.
What is held is the geometry: a ring's width and the width of its widest term together
are no more than the page, at every width a page comes in. Served by a real server to
headless Chromium. Skipped wherever Playwright or a Chromium binary is unavailable, so
the ordinary gate does not grow a browser dependency (``docs/testing-the-gui.md``,
Mode 5).
"""
from __future__ import annotations

import threading
import unittest
from pathlib import Path
from typing import Any
from wsgiref.simple_server import WSGIRequestHandler, WSGIServer, make_server

from little_sister import app as app_module
from tests.browser_server import PageServer

try:  # pragma: no cover - environment probe
    from playwright.sync_api import sync_playwright
except ImportError:  # pragma: no cover
    sync_playwright = None  # type: ignore[assignment]

_SANDBOX_CHROMIUM = Path("/opt/pw-browsers/chromium-1194/chrome-linux/chrome")
_BOOTSTRAP = (Path(__file__).resolve().parent.parent / "var" / "bootstrap"
              / "node_modules" / "bootstrap" / "dist")

#: The widths the finding was made at, a wide screen, and a phone's.
_WIDTHS = (1440, 1000, 946, 700, 576, 375)

#: The page against its screen, and each ring that is drawn: how far a term at either
#: end of it reaches — half the ring's widest term past the ring — against the page
#: the hero stands on.
_MEASURED = """() => {
    const page = document.querySelector('main.ls-page').getBoundingClientRect();
    const rings = Array.from(document.querySelectorAll('.ls-hero__ring'))
        .filter(ring => getComputedStyle(ring).display !== 'none')
        .map(ring => {
            const at = ring.getBoundingClientRect();
            const widest = Math.max(...Array.from(ring.querySelectorAll('b'))
                .map(term => term.getBoundingClientRect().width));
            return {width: Math.round(at.width),
                    terms: ring.querySelectorAll('b').length,
                    left: Math.round(at.left - widest / 2 - page.left),
                    right: Math.round(Math.min(page.right, window.innerWidth)
                                      - at.right - widest / 2)};
        });
    const eyes = document.querySelector('.ls-hero__brand svg').getBoundingClientRect();
    return {over: document.documentElement.scrollWidth - window.innerWidth, rings,
            eyes: Math.round(eyes.width)};
}"""


class _Quiet(WSGIRequestHandler):
    def log_message(self, format: str, *args: object) -> None:
        pass


class AboutBrowserTests(unittest.TestCase):
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
        cls.server = make_server("127.0.0.1", 0, app_module.app,
                                 server_class=PageServer, handler_class=_Quiet)
        threading.Thread(target=cls.server.serve_forever, daemon=True).start()
        cls.base = f"http://127.0.0.1:{cls.server.server_port}"

    @classmethod
    def tearDownClass(cls) -> None:
        if cls.server is not None:
            cls.server.shutdown()
            cls.server.server_close()
        cls.browser.close()
        cls.playwright.stop()

    def _about(self, width: int) -> dict[str, Any]:
        context = self.browser.new_context(
            viewport={"width": width, "height": 800}, reduced_motion="reduce")
        self.addCleanup(context.close)
        page = context.new_page()
        page.route("https://cdn.jsdelivr.net/**", self._vendored)
        page.goto(f"{self.base}/login")
        page.fill("#username", "pan")
        page.fill("#password", "12345678")
        with page.expect_navigation():
            page.click("button[type=submit]")
        page.goto(f"{self.base}/about")
        page.wait_for_selector(".ls-hero__ring", state="attached")
        measured: dict[str, Any] = page.evaluate(_MEASURED)
        return measured

    @staticmethod
    def _vendored(route: Any) -> None:
        name = route.request.url.rsplit("/", 1)[-1]
        for candidate in (_BOOTSTRAP / "css" / name, _BOOTSTRAP / "js" / name):
            if candidate.is_file():
                route.fulfill(path=str(candidate))
                return
        route.continue_()

    def test_the_page_is_no_wider_than_its_screen(self) -> None:
        for width in _WIDTHS:
            with self.subTest(width=width):
                self.assertLessEqual(self._about(width)["over"], 0)

    def test_a_term_at_the_end_of_a_ring_is_inside_the_page(self) -> None:
        for width in _WIDTHS:
            measured = self._about(width)
            self.assertTrue(measured["rings"], width)
            for ring in measured["rings"]:
                with self.subTest(width=width, ring=ring["width"]):
                    self.assertGreater(ring["terms"], 0)
                    self.assertGreaterEqual(ring["left"], 0, ring)
                    self.assertGreaterEqual(ring["right"], 0, ring)

    def test_a_wide_screen_keeps_both_rings_and_their_widths(self) -> None:
        # what a narrow page gives up is not taken from a wide one
        rings = self._about(1440)["rings"]
        self.assertEqual(sorted(ring["width"] for ring in rings), [608, 928])

    def test_a_phone_keeps_the_ring_the_story_names(self) -> None:
        measured = self._about(375)
        rings = measured["rings"]
        self.assertEqual(len(rings), 1)
        # and the ring still passes outside the eyes, not across them
        self.assertGreater(measured["eyes"], 100)
        self.assertGreater(rings[0]["width"], measured["eyes"])

