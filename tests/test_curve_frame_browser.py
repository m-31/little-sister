"""On a phone a curve opens at its newest end — held against a real browser.

A drawing is never scaled below thirty rem, under which its axes' words could not be
read, so in a card narrower than that — a phone's — it scrolls sideways inside its
frame. The frame opened at its left end: the oldest readings, with the newest, which
the curve's own summary speaks of first, out of sight. It opens at its right end now,
on a node's page and in a Series view, whatever window the view is drawn over; and on
a page that refreshes itself, where a reader has scrolled a frame to stays where it
is across the refresh.

The estate is the one ``tests/test_series_window.py`` reads — a host whose metrics
were read every minute for an hour — served by a real server to headless Chromium
emulating a phone. Skipped wherever Playwright or a Chromium binary is unavailable, so
the ordinary gate does not grow a browser dependency (``docs/testing-the-gui.md``,
Mode 5).
"""
from __future__ import annotations

import threading
import unittest
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from wsgiref.simple_server import WSGIRequestHandler, WSGIServer, make_server

from little_sister import app as app_module
from tests.browser_server import PageServer
from tests.test_series_window import HOST, estate

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
_DESK = {"viewport": {"width": 1280, "height": 900}}
_NOON = datetime(2026, 10, 3, 12, 0, 0, tzinfo=UTC)

#: Each curve's frame against its drawing: how much wider the drawing is, how far its
#: right end stands from the frame's, and whether the newest reading's dot is inside
#: the frame.
_FRAMES = """() => Array.from(
        document.querySelectorAll('figure.ls-curve')).map(figure => {
    const frame = figure.querySelector('.ls-curve__frame').getBoundingClientRect();
    const plot = figure.querySelector('svg.ls-curve__plot').getBoundingClientRect();
    const dots = figure.querySelectorAll('svg.ls-curve__plot circle.ls-curve__dot');
    const newest = dots.length ? dots[dots.length - 1].getBoundingClientRect() : null;
    return {label: figure.querySelector('.ls-curve__title').textContent.trim(),
            wider: Math.round(plot.width - frame.width),
            short: Math.round(plot.right - frame.right),
            newest: newest === null ? null
                : newest.left >= frame.left - 0.5 && newest.right <= frame.right + 0.5};
})"""


class _Quiet(WSGIRequestHandler):
    def log_message(self, format: str, *args: object) -> None:
        pass


class CurveFrameBrowserTests(unittest.TestCase):
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
        cls.saved = (app_module.status_tree, app_module.engine)
        app_module.status_tree, app_module.engine = estate()
        cls.server = make_server("127.0.0.1", 0, app_module.app,
                                 server_class=PageServer, handler_class=_Quiet)
        threading.Thread(target=cls.server.serve_forever, daemon=True).start()
        cls.base = f"http://127.0.0.1:{cls.server.server_port}"

    @classmethod
    def tearDownClass(cls) -> None:
        if cls.server is not None:
            cls.server.shutdown()
            cls.server.server_close()
        app_module.status_tree, app_module.engine = cls.saved
        cls.browser.close()
        cls.playwright.stop()

    def _signed_in(self, **drawn_in: Any) -> Any:
        context = self.browser.new_context(reduced_motion="reduce", **drawn_in)
        self.addCleanup(context.close)
        page = context.new_page()
        page.route("https://cdn.jsdelivr.net/**", self._vendored)
        page.goto(f"{self.base}/login")
        page.fill("#username", "pan")
        page.fill("#password", "12345678")
        with page.expect_navigation():
            page.click("button[type=submit]")
        return page

    @staticmethod
    def _vendored(route: Any) -> None:
        name = route.request.url.rsplit("/", 1)[-1]
        for candidate in (_BOOTSTRAP / "css" / name, _BOOTSTRAP / "js" / name):
            if candidate.is_file():
                route.fulfill(path=str(candidate))
                return
        route.continue_()

    def _frames(self, page: Any, url: str) -> list[dict[str, Any]]:
        page.goto(f"{self.base}{url}")
        page.wait_for_selector("figure.ls-curve")
        frames: list[dict[str, Any]] = page.evaluate(_FRAMES)
        return frames

    def _at_the_newest_end(self, frames: list[dict[str, Any]]) -> None:
        self.assertTrue(frames)
        for frame in frames:
            with self.subTest(curve=frame["label"]):
                # the drawing is wider than its frame, or the claim is about nothing
                self.assertGreater(frame["wider"], 50, frame)
                self.assertEqual(frame["short"], 0, frame)

    def test_a_series_views_curves_open_at_their_newest_end(self) -> None:
        frames = self._frames(self._signed_in(**_PHONE), f"/series{HOST}")
        self.assertGreaterEqual(len(frames), 4)
        self._at_the_newest_end(frames)
        # A view's curves share one time axis, so the right end is the newest
        # reading of the view: a curve read up to it has its last dot in the frame,
        # and one last read fifty minutes before has not.
        newest = {frame["label"]: frame["newest"] for frame in frames}
        self.assertIs(newest["load"], True)
        self.assertIs(newest["temp"], False)

    def test_a_nodes_own_curves_do(self) -> None:
        self._at_the_newest_end(
            self._frames(self._signed_in(**_PHONE), f"/status{HOST}"))

    def test_a_window_chosen_by_its_url_opens_at_its_own_end(self) -> None:
        page = self._signed_in(**_PHONE)
        frames = self._frames(
            page, f"/series{HOST}?from=2026-09-26T17:10&to=2026-09-26T17:20")
        self._at_the_newest_end(frames)
        # and the view still says which window it is drawn over
        self.assertEqual(page.locator(".ls-series-grid").get_attribute("data-end"),
                         "2026-09-26T15:20:00Z")

    def test_on_a_desk_nothing_scrolls_and_nothing_moved(self) -> None:
        for frame in self._frames(self._signed_in(**_DESK), f"/series{HOST}"):
            with self.subTest(curve=frame["label"]):
                self.assertEqual(frame["wider"], 0, frame)
                self.assertEqual(frame["short"], 0, frame)

    def test_a_drawings_words_still_read_from_the_left(self) -> None:
        # The frame is turned to open at its right end; what is drawn in it is not.
        page = self._signed_in(**_PHONE)
        self._frames(page, f"/series{HOST}")
        ticks = page.evaluate("""() => {
            const plot = document.querySelector('svg.ls-curve__plot');
            const at = plot.getBoundingClientRect();
            const tick = plot.querySelector('text.ls-curve__tick')
                .getBoundingClientRect();
            return {direction: getComputedStyle(plot).direction,
                    tick: Math.round(tick.right - at.left),
                    summary: getComputedStyle(document.querySelector(
                        '.ls-curve__summary')).direction};
        }""")
        self.assertEqual(ticks["direction"], "ltr")
        self.assertEqual(ticks["summary"], "ltr")
        # a step's words stand at the plot's left end, within its margin
        self.assertLess(ticks["tick"], 50, ticks)

    def test_a_refresh_leaves_a_frame_where_a_reader_scrolled_it(self) -> None:
        page = self._signed_in(**_PHONE)
        page.clock.install(time=_NOON)
        page.goto(f"{self.base}/status{HOST}")
        page.wait_for_selector("figure.ls-curve")
        page.clock.pause_at(_NOON + timedelta(seconds=5))
        moved = page.evaluate("""() => {
            const frame = document.querySelector('.ls-curve__frame');
            frame.scrollBy(-120, 0);
            frame.dataset.seen = 'before';
            return Math.round(Math.abs(frame.scrollLeft));
        }""")
        self.assertGreater(moved, 100)
        with page.expect_response(lambda response: "fragment=1" in response.url):
            page.clock.run_for(10_000)
        page.wait_for_function(
            "document.querySelector('.ls-curve__frame[data-seen]') === null")
        after = page.evaluate(
            "Math.round(Math.abs(document.querySelector('.ls-curve__frame')"
            ".scrollLeft))")
        self.assertEqual(after, moved)

