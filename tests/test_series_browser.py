"""A Series view's drag and its line, held against a real pointer (ADR-0098 decision 6).

The estate is the one ``tests/test_series_window.py`` reads — a host whose metrics were
read every minute for an hour from 17:00 in Berlin, with the page's clock at 18:00 —
served by a real server to headless Chromium, which drags and points as a hand does.
Every position is worked out from the drawing's own geometry, not from what the script
reads: over the window 17:00 to 18:00, a minute is 11.2 of the plot's 760 units, from
72 to 744. Skipped wherever Playwright or a Chromium binary is unavailable, so the
ordinary gate does not grow a browser dependency (``docs/testing-the-gui.md``, Mode 5).
"""
from __future__ import annotations

import re
import threading
import unittest
from dataclasses import replace
from datetime import timedelta
from pathlib import Path
from typing import Any
from unittest import mock
from urllib.parse import parse_qs, urlsplit
from wsgiref.simple_server import WSGIRequestHandler, WSGIServer, make_server

from little_sister import app as app_module
from tests.test_series_window import HOST, SETTINGS, T0, estate

try:  # pragma: no cover - environment probe
    from playwright.sync_api import sync_playwright
except ImportError:  # pragma: no cover
    sync_playwright = None  # type: ignore[assignment]

#: A sandbox pins one browser build; a Playwright from the lock may expect another,
#: so the one that is there is what runs (as ``tests/sweep_contrast.py`` does).
_SANDBOX_CHROMIUM = Path("/opt/pw-browsers/chromium-1194/chrome-linux/chrome")

#: Bootstrap as ``tests/sweep_contrast.py`` vendors it (``docs/testing-the-gui.md``,
#: Mode 4): the page bar's menu is Bootstrap's to fold away, and unfolded it covers
#: the top of the view the pointer is sent to.
_BOOTSTRAP = (Path(__file__).resolve().parent.parent / "var" / "bootstrap"
              / "node_modules" / "bootstrap" / "dist")

#: The drawing's geometry (``little_sister.curves``): the plot's width and where the
#: window's two ends stand on it.
_WIDTH, _LEFT, _RIGHT = 760, 72.0, 744.0

#: The hour the pages are drawn over, and the clock they are drawn by.
_HOUR = f"/series{HOST}?from=now-1h"


def _unit(minutes: float, window: tuple[float, float] = (0, 60)) -> float:
    """Where ``minutes`` after 17:00 stands on a plot over ``window``, in minutes after
    17:00 — the hour to 18:00 unless it says otherwise."""
    first, last = window
    return _LEFT + (minutes - first) / (last - first) * (_RIGHT - _LEFT)


def _query(url: str) -> tuple[str, dict[str, str], str]:
    parts = urlsplit(url)
    query = {key: values[0] for key, values in parse_qs(parts.query).items()}
    return parts.path, query, parts.fragment


def _z(minutes: float) -> str:
    return (T0 + timedelta(minutes=minutes)).strftime("%Y-%m-%dT%H:%M:%SZ")


class _Quiet(WSGIRequestHandler):
    def log_message(self, format: str, *args: object) -> None:
        pass


class SeriesPointerTests(unittest.TestCase):
    """The drag, the line, and the place a move keeps — in Chromium."""

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
        cls.patches = [
            mock.patch("little_sister.config.config",
                       replace(app_module.config, **SETTINGS)),
            mock.patch.object(app_module, "_now",
                              return_value=T0 + timedelta(minutes=60))]
        for patch in cls.patches:
            patch.start()
        cls.server = make_server("127.0.0.1", 0, app_module.app, handler_class=_Quiet)
        threading.Thread(target=cls.server.serve_forever, daemon=True).start()
        cls.base = f"http://127.0.0.1:{cls.server.server_port}"

    @classmethod
    def tearDownClass(cls) -> None:
        if cls.server is not None:
            cls.server.shutdown()
            cls.server.server_close()
        for patch in reversed(cls.patches):
            patch.stop()
        app_module.status_tree, app_module.engine = cls.saved
        cls.browser.close()
        cls.playwright.stop()

    def setUp(self) -> None:
        self.context = self.browser.new_context(
            viewport={"width": 1000, "height": 700}, reduced_motion="reduce")
        self.addCleanup(self.context.close)
        self.page = self.context.new_page()
        self.page.route("https://cdn.jsdelivr.net/**", self._vendored)
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

    # --- the hand -------------------------------------------------------------------

    def _open(self, url: str = _HOUR) -> None:
        self.page.goto(f"{self.base}{url}")

    def _plot(self, title: str) -> Any:
        figure = self.page.locator("figure.ls-curve").filter(
            has=self.page.locator(".ls-curve__title",
                                  has_text=re.compile(f"^{title}$")))
        plot = figure.locator("svg.ls-curve__plot")
        plot.evaluate("plot => plot.scrollIntoView({block: 'center'})")
        return plot

    def _at(self, drawing: Any, minutes: float,
            window: tuple[float, float] = (0, 60)) -> tuple[float, float]:
        """The point on ``drawing`` — a plot or its axis — ``minutes`` after 17:00."""
        box = drawing.bounding_box()
        assert box is not None
        return (box["x"] + _unit(minutes, window) / _WIDTH * box["width"],
                box["y"] + box["height"] * 0.4)

    def _drag(self, drawing: Any, start: float, end: float, *, release: bool = True,
              window: tuple[float, float] = (0, 60)) -> None:
        mouse = self.page.mouse
        mouse.move(*self._at(drawing, start, window))
        mouse.down()
        mouse.move(*self._at(drawing, (start + end) / 2, window), steps=4)
        mouse.move(*self._at(drawing, end, window), steps=4)
        if release:
            mouse.up()

    def _marked(self) -> list[tuple[float, float]]:
        """The stretch each plot marks, as it is drawn: its left and its right."""
        return self.page.evaluate("""() => [...document.querySelectorAll(
            'svg.ls-curve__plot')].map(plot => {
                const band = plot.querySelector('.ls-curve__band');
                if (!band || getComputedStyle(band).display === 'none') return null;
                const x = +band.getAttribute('x');
                return [x, x + +band.getAttribute('width')];
            })""")

    def _figure(self, title: str) -> Any:
        return self.page.locator("figure.ls-curve").filter(
            has=self.page.locator(".ls-curve__title",
                                  has_text=re.compile(f"^{title}$")))

    def _summary(self, title: str) -> str:
        """What a curve's summary line says to the eye: the line's reading where one
        is shown over it, and its own words otherwise."""
        figure = self._figure(title)
        reading = figure.locator(".ls-curve__reading")
        summary = figure.locator(".ls-curve__summary:not(.ls-curve__reading)")
        if reading.count() and reading.is_visible():
            self.assertFalse(summary.is_visible())
            return " ".join(reading.inner_text().split())
        return " ".join(summary.inner_text().split())

    def _layout(self) -> list[tuple[float, float]]:
        """Where every curve's figure stands, and how tall it is."""
        return self.page.evaluate("""() => [...document.querySelectorAll(
            'figure.ls-curve')].map(figure => {
                const box = figure.getBoundingClientRect();
                return [box.top + scrollY, box.height];
            })""")

    def _stays(self) -> None:
        """Nothing navigated: the page is the hour it was opened on."""
        self.page.wait_for_timeout(300)
        self.assertEqual(_query(self.page.url)[:2],
                         (f"/series{HOST}", {"from": "now-1h"}))

    # --- a drag chooses a stretch ---------------------------------------------------

    def test_a_drag_across_a_curve_opens_the_view_over_the_stretch(self) -> None:
        self._open()
        with self.page.expect_navigation():
            self._drag(self._plot("load"), 15.3, 29.8)
        # two instants, to the minute over an hour, back at the curve's group
        self.assertEqual(_query(self.page.url),
                         (f"/series{HOST}", {"from": _z(15), "to": _z(30)}, "node"))
        named = self.page.locator(".ls-window__range").inner_text()
        self.assertIn("2026-09-26 17:15 – 17:30 CEST", " ".join(named.split()))

    def test_a_stretch_of_a_window_under_an_hour_is_chosen_to_the_second(self) -> None:
        self._open(f"/series{HOST}?from=now-30m")          # 17:30 to 18:00
        with self.page.expect_navigation():
            self._drag(self._plot("load"), 40.25, 50.5, window=(30, 60))
        self.assertEqual(_query(self.page.url)[:2],
                         (f"/series{HOST}", {"from": _z(40.25), "to": _z(50.5)}))

    def test_a_drag_either_way_chooses_the_same_stretch(self) -> None:
        self._open()
        with self.page.expect_navigation():
            self._drag(self._plot("rate"), 30, 15)
        self.assertEqual(_query(self.page.url),
                         (f"/series{HOST}", {"from": _z(15), "to": _z(30)}, "rate"))

    def test_a_drag_marks_the_stretch_on_every_curve_with_its_two_ends(self) -> None:
        self._open()
        plot = self._plot("load")
        self._drag(plot, 15, 30, release=False)
        marked = self._marked()
        self.assertEqual(len(marked), self.page.locator("svg.ls-curve__plot").count())
        for left, right in marked:
            self.assertAlmostEqual(left, _unit(15), delta=1.5)
            self.assertAlmostEqual(right, _unit(30), delta=1.5)
        ends = plot.locator("xpath=following-sibling::*[1]").locator(
            ".ls-curve__chosen").all_text_contents()
        self.assertEqual([" ".join(end.split()) for end in ends], ["17:15", "17:30"])
        self.page.mouse.up()

    def test_escape_lets_a_drag_go(self) -> None:
        self._open()
        self._drag(self._plot("load"), 15, 30, release=False)
        self.page.keyboard.press("Escape")
        self.assertEqual(set(map(tuple, filter(None, self._marked()))), set())
        self.page.mouse.up()
        self._stays()

    def test_a_drag_shorter_than_a_few_pixels_is_a_click(self) -> None:
        self._open()
        plot = self._plot("load")
        x, y = self._at(plot, 20)
        self.page.mouse.move(x, y)
        self.page.mouse.down()
        self.page.mouse.move(x + 2, y)
        self.page.mouse.up()
        self._stays()
        # on the time axis the click is the stretch's link
        axis = plot.locator("xpath=following-sibling::*[1]")
        x, y = self._at(axis, 20)
        with self.page.expect_navigation():
            self.page.mouse.move(x, y)
            self.page.mouse.down()
            self.page.mouse.move(x + 2, y)
            self.page.mouse.up()
        self.assertEqual(_query(self.page.url),
                         (f"/series{HOST}", {"from": _z(15), "to": _z(30)}, "node"))

    def test_a_drag_along_the_time_axis_chooses_a_stretch_too(self) -> None:
        self._open()
        axis = self._plot("load").locator("xpath=following-sibling::*[1]")
        with self.page.expect_navigation():
            self._drag(axis, 10, 25)
        self.assertEqual(_query(self.page.url),
                         (f"/series{HOST}", {"from": _z(10), "to": _z(25)}, "node"))

    def test_touch_keeps_the_page_scrolling(self) -> None:
        self._open()
        start, end = self._at(self._plot("load"), 15), self._at(self._plot("load"), 30)
        self.page.evaluate("""([start, end]) => {
            const at = (x, y) => document.elementFromPoint(x, y);
            const send = (type, [x, y]) => at(x, y).dispatchEvent(
                new PointerEvent(type, {bubbles: true, cancelable: true,
                    pointerType: 'touch', isPrimary: true, pointerId: 7, button: 0,
                    buttons: 1, clientX: x, clientY: y}));
            send('pointerdown', start);
            send('pointermove', end);
            send('pointerup', end);
        }""", [start, end])
        self.assertEqual(set(map(tuple, filter(None, self._marked()))), set())
        self._stays()

    def test_nothing_is_selected_by_a_drag_with_the_script_or_without_it(self) -> None:
        # the hand that selected the value axis's labels: from one of them, right and
        # down across the plot
        for scripted in (True, False):
            with self.subTest(scripted=scripted):
                if not scripted:
                    self.page.route("**/js/series.js", lambda route: route.abort())
                self._open()
                label = self._plot("load").locator(".ls-curve__tick").nth(1)
                box = label.bounding_box()
                assert box is not None
                x, y = box["x"] + box["width"] / 2, box["y"] + box["height"] / 2
                mouse = self.page.mouse
                mouse.move(x, y)
                mouse.down()
                for step in range(1, 11):
                    mouse.move(x + 20 * step, y + 6 * step)
                selected = self.page.evaluate("String(getSelection())")
                self.page.keyboard.press("Escape")
                mouse.up()
                self.assertEqual(selected.strip(), "")

    # --- one line reads every curve at one instant ---------------------------------

    def test_one_line_crosses_every_curve_at_the_instant_pointed_at(self) -> None:
        self._open()
        self.page.mouse.move(*self._at(self._plot("load"), 30))
        crosses = self.page.evaluate("""() => [...document.querySelectorAll(
            'svg.ls-curve__plot')].map(plot => {
                const line = plot.querySelector('.ls-curve__cross');
                return line && getComputedStyle(line).display !== 'none'
                    ? +line.getAttribute('x1') : null;
            })""")
        self.assertTrue(crosses)
        for x in crosses:
            self.assertIsNotNone(x)
            self.assertAlmostEqual(x, _unit(30), delta=0.6)

    def test_each_curve_s_summary_says_what_its_strip_there_says(self) -> None:
        self._open()
        before = self._summary("load")
        self.page.mouse.move(*self._at(self._plot("load"), 30))
        self.assertEqual(self._summary("load"), "2026-09-26 17:30:00 · 30")
        self.assertEqual(self._summary("rate"), "2026-09-26 17:30:00 · 50 %")
        self.assertEqual(self._summary("late"), "2026-09-26 17:30:00 · no value")
        # and until the pointer leaves: then each says what it said
        self.page.mouse.move(5, 5)
        self.assertEqual(self._summary("load"), before)
        self.assertEqual(self.page.evaluate("""() => [...document.querySelectorAll(
            '.ls-curve__cross')].filter(line =>
                getComputedStyle(line).display !== 'none').length"""), 0)

    def test_the_line_moves_nothing_on_the_page(self) -> None:
        # narrow enough that a summary beside its title wraps where the reading over
        # it would not, and the reverse — and, at the narrowest, that a reading is
        # longer than its line: no width moves a curve while the line reads
        for width in (320, 400, 480, 560, 640, 900, 1280):
            with self.subTest(width=width):
                self.page.set_viewport_size({"width": width, "height": 700})
                self._open()
                plot = self._plot("temp")
                self.page.mouse.move(5, 5)
                resting = self._layout()
                for minutes in (5, 30, 55):
                    self.page.mouse.move(*self._at(plot, minutes))
                    self.assertEqual(self._layout(), resting)
                    # each reading lies over its summary, to the caption's end, on
                    # one line
                    for placed in self._readings_placed():
                        self.assertAlmostEqual(placed["left"], placed["summaryLeft"],
                                               delta=1)
                        self.assertAlmostEqual(placed["top"], placed["summaryTop"],
                                               delta=1)
                        self.assertAlmostEqual(placed["right"], placed["captionRight"],
                                               delta=1)
                        self.assertLessEqual(placed["height"], placed["line"] + 1)

    def _readings_placed(self) -> list[dict[str, float]]:
        """Each shown reading's box beside its summary's, and one line's height."""
        return self.page.evaluate("""() => [...document.querySelectorAll(
            '.ls-curve__reading')].filter(reading => !reading.hidden).map(reading => {
                const box = reading.getBoundingClientRect();
                const summary = reading.parentNode.querySelector(
                    '.ls-curve__summary:not(.ls-curve__reading)')
                    .getBoundingClientRect();
                return {left: box.left, top: box.top, height: box.height,
                        right: box.right,
                        summaryLeft: summary.left, summaryTop: summary.top,
                        captionRight: reading.parentNode.getBoundingClientRect().right,
                        line: parseFloat(getComputedStyle(reading).lineHeight)};
            })""")

    def test_the_strips_tooltips_give_way(self) -> None:
        self._open()
        self.assertEqual(self.page.evaluate("""() => getComputedStyle(
            document.querySelector('.ls-curve__hover')).pointerEvents"""), "none")

    # --- a move from the bar keeps the reader's place -------------------------------

    def test_a_move_from_the_bar_returns_to_the_group_scrolled_to(self) -> None:
        # the last half hour, which a zoom out moves, on a window short enough that
        # the host's own group can scroll away above the bar
        self.page.set_viewport_size({"width": 1000, "height": 420})
        self._open(f"/series{HOST}?from=now-30m")
        # the rate group scrolled up to just beneath the bar, where the bar sticks
        self.page.evaluate("""() => {
            const bar = document.querySelector('.ls-window');
            const stuck = bar.offsetHeight + parseFloat(getComputedStyle(
                document.documentElement).getPropertyValue('--ls-bar-height'));
            const rate = document.getElementById('rate').getBoundingClientRect().top;
            window.scrollTo(0, rate + scrollY - stuck - 4);
        }""")
        self.page.wait_for_timeout(100)
        self.assertLess(self.page.evaluate(
            "document.getElementById('node').getBoundingClientRect().bottom"),
            self.page.evaluate(
                "document.querySelector('.ls-window').getBoundingClientRect().bottom"))
        with self.page.expect_navigation():
            self.page.click(".ls-window__link:text-is('zoom out')")
        path, _written, fragment = _query(self.page.url)
        self.assertEqual((path, fragment), (f"/series{HOST}", "rate"))
        # the group stands beneath the bar, not at the top of the page
        top = self.page.evaluate(
            "document.getElementById('rate').getBoundingClientRect().top")
        bar = self.page.evaluate(
            "document.querySelector('.ls-window').getBoundingClientRect().bottom")
        self.assertGreaterEqual(top, bar)
        self.assertLess(top, bar + 120)

    def test_a_move_from_the_top_of_the_view_stays_at_the_top(self) -> None:
        self._open(f"/series{HOST}?from=now-30m")
        with self.page.expect_navigation():
            self.page.click(".ls-window__link:text-is('zoom out')")
        self.assertEqual(_query(self.page.url)[2], "")
