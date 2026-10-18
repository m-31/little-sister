"""The Series index with its folds open fits a narrow screen (ADR-0114 decision 3) —
held against a real browser.

A fold opens to a line for each curve: its label, the curve seen small, its three
values. Kept on one line in the Curves cell, they made that column as wide as the
longest of them, so on an estate with real names the table outgrew its box at a
laptop's window; and on a phone the table is wider than the screen whatever its folds
do, so the column the folds stand in was out of sight altogether.

The estate is shaped like a deployment's: a dozen hosts with names of a real length,
each keeping five curves whose labels and units are a few words long, beside checks
that draw none. Served by a real server to headless Chromium, at the 946 pixels the
finding was made at and on an emulated phone. Skipped wherever Playwright or a Chromium
binary is unavailable, so the ordinary gate does not grow a browser dependency
(``docs/testing-the-gui.md``, Mode 5).
"""
from __future__ import annotations

import threading
import unittest
from datetime import timedelta
from pathlib import Path
from typing import Any
from wsgiref.simple_server import WSGIRequestHandler, WSGIServer, make_server

from little_sister import app as app_module
from little_sister.engine import Engine
from little_sister.series import MemoryStore, SeriesKey, SeriesRecord
from little_sister.status import StatusCode
from little_sister.tree import StatusTree
from tests.browser_looks import looks
from tests.browser_server import PageServer
from tests.test_series_index import T0, _Cost, _Kept

try:  # pragma: no cover - environment probe
    from playwright.sync_api import sync_playwright
except ImportError:  # pragma: no cover
    sync_playwright = None  # type: ignore[assignment]

_SANDBOX_CHROMIUM = Path("/opt/pw-browsers/chromium-1194/chrome-linux/chrome")
_BOOTSTRAP = (Path(__file__).resolve().parent.parent / "var" / "bootstrap"
              / "node_modules" / "bootstrap" / "dist")

_HOSTS = ("gaffsie", "hemulen", "snufkin", "sniff.example", "toffle", "fillyjonk",
          "moomin", "the-groke-of-the-north")
#: What a host's check draws: five curves, named and united as a host's are.
_MEASURES: dict[str, object] = {
    "mem": {"unit": "%", "label": "Memory in use"},
    "cpu": {"unit": "%", "label": "CPU busy"},
    "load": {"unit": "per core", "label": "Load per core"},
    "disk": {"unit": "%", "label": "Disk space used"},
    "free": {"unit": "GiB", "label": "Free space"},
}



class _Host(_Kept):
    type_name = "host-metrics"


class _Mac(_Kept):
    type_name = "macos-memory"


#: The laptop's window the finding was made at, and a phone.
_DESK = {"viewport": {"width": 946, "height": 900}}
_PHONE = {"viewport": {"width": 375, "height": 812}, "device_scale_factor": 2,
          "is_mobile": True, "has_touch": True,
          "user_agent": ("Mozilla/5.0 (Linux; Android 14; Pixel 8) "
                         "AppleWebKit/537.36 (KHTML, like Gecko) "
                         "Chrome/126.0.0.0 Mobile Safari/537.36")}

_OPEN_ALL = ("() => document.querySelectorAll('.ls-series-index details')"
             ".forEach(fold => { fold.open = true; })")
#: The table against the box it scrolls in.
_TABLE = """() => {
    const box = document.querySelector('.ls-series-index').closest('.table-responsive');
    return {table: box.scrollWidth, box: box.clientWidth,
            page: document.documentElement.scrollWidth, screen: window.innerWidth};
}"""
#: How many lines each open fold's three numbers take.
_SAYS_LINES = """() => Array.from(document.querySelectorAll(
    '.ls-series-index details[open] .ls-spark-row__says'))
    .map(says => Math.round(says.getBoundingClientRect().height
         / parseFloat(getComputedStyle(says).lineHeight)))"""
#: How each open fold's three numbers may wrap.
_SAYS_WRAP = """() => Array.from(document.querySelectorAll(
    '.ls-series-index details[open] .ls-spark-row__says'))
    .map(says => getComputedStyle(says).whiteSpace)"""
#: Every part of every open fold, and each fold's own control, that is not wholly
#: inside the screen's width.
_OUTSIDE = """() => Array.from(document.querySelectorAll(
        '.ls-series-index summary, .ls-series-index details[open] .ls-spark-row__label,'
        + ' .ls-series-index details[open] svg.ls-spark,'
        + ' .ls-series-index details[open] .ls-spark-row__says'))
    .map(part => [part, part.getBoundingClientRect()])
    .filter(([_part, at]) => at.width === 0 || at.left < 0
            || at.right > window.innerWidth + 0.5)
    .map(([part, at]) => `${part.tagName.toLowerCase()}.${part.getAttribute('class')}`
         + ` ${Math.round(at.left)}..${Math.round(at.right)}`)"""


def _estate() -> tuple[StatusTree, Engine]:
    tree = StatusTree()
    store = MemoryStore()
    checks: list[_Kept] = []

    def keep(kind: type[_Kept], path: str, measures: dict[str, object] | None,
             record: Any) -> None:
        checks.append(kind(path=path, series_keep=40, frequency_seconds=60,
                           measures=measures))
        for step in range(30):
            store.add(SeriesKey(kind.type_name, path, "subject"),
                      SeriesRecord(record(step), T0 + timedelta(minutes=step),
                                   code=StatusCode.OK), keep=40)
        tree.upsert(path, StatusCode.OK, frequency_seconds=60)

    for host in _HOSTS:
        keep(_Host, f"/{host}", _MEASURES, lambda step: {
            "mem": 72 + step % 9, "cpu": 15 + (step * 37) % 80,
            "load": 0.547 + step / 100, "disk": 87, "free": 824.6 + step / 300})
    # two checks on one node, and a node deep in its branch: what makes the columns
    # beside the folds as wide as a deployment's are
    keep(_Mac, "/hemulen", {"pressure": {"unit": "%", "label": "Memory pressure"}},
         lambda step: {"pressure": 30 + step})
    keep(_Host, "/fillyjonk/nas/smart", None,
         lambda step: {"running": 1})
    keep(_Cost, "/aws", None, lambda step: {"usd": 12})
    keep(_Cost, "/github-rate-limit", None, lambda step: {"left": 4998})
    return tree, Engine(checks, tree, series=store)


class _Quiet(WSGIRequestHandler):
    def log_message(self, format: str, *args: object) -> None:
        pass


class IndexFoldsBrowserTests(unittest.TestCase):
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
        app_module.status_tree, app_module.engine = _estate()
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

    def _index(self, *, theme: str | None = None, **drawn_in: Any) -> Any:
        context = self.browser.new_context(reduced_motion="reduce", **drawn_in)
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
        page.goto(f"{self.base}/series")
        page.wait_for_selector(".ls-series-index")
        return page

    @staticmethod
    def _vendored(route: Any) -> None:
        name = route.request.url.rsplit("/", 1)[-1]
        for candidate in (_BOOTSTRAP / "css" / name, _BOOTSTRAP / "js" / name):
            if candidate.is_file():
                route.fulfill(path=str(candidate))
                return
        route.continue_()

    # --- a laptop's window --------------------------------------------------------

    def test_with_every_fold_open_the_table_is_no_wider_than_its_box(self) -> None:
        # up to the width where the numbers keep one line, wrapping beneath their
        # strips, in the library's theme and in the plain one; at the laptop's window
        # in the plain theme's proportional faces alone: cyberpunk's monospace one
        # stands the table a pixel past its box there with every fold closed and 27
        # with every fold open, a scroll in the box (2026-10-18)
        for theme, widths in (("plain", (946, 1200, 1499)),
                              ("cyberpunk", (1200, 1400, 1499))):
            for width in widths:
                page = self._index(theme=theme,
                                   viewport={"width": width, "height": 900})
                with self.subTest(theme=theme, width=width):
                    closed = page.evaluate(_TABLE)
                    self.assertLessEqual(closed["table"], closed["box"], closed)
                    page.evaluate(_OPEN_ALL)
                    opened = page.evaluate(_TABLE)
                    self.assertLessEqual(opened["table"], opened["box"], opened)
                    self.assertEqual(page.locator("svg.ls-spark").count(),
                                     5 * len(_HOSTS) + 1)
                    # below the one line's width they may wrap, in every theme
                    self.assertEqual(set(page.evaluate(_SAYS_WRAP)), {"normal"})

    def test_a_closed_fold_is_one_line_in_its_row(self) -> None:
        # ADR-0103 decision 2, as it was: closed, a fold is its count and nothing
        # more — as tall as the readings' number beside it.
        page = self._index(**_DESK)
        tall = page.evaluate("""() => {
            const row = Array.from(document.querySelectorAll(
                '.ls-series-index tbody tr')).find(row => row.querySelector(
                'a.ls-series-index__node[href="/status/gaffsie"]'));
            const high = (part) => row.querySelector(part)
                .getBoundingClientRect().height;
            return [high('details'), high('summary'), high('.ls-series-index__kept')];
        }""")
        self.assertEqual(tall[0], tall[1])
        self.assertLess(tall[0], tall[2])

    def test_the_strips_of_a_fold_stand_in_a_column(self) -> None:
        page = self._index(**_DESK)
        page.evaluate(_OPEN_ALL)
        lefts = page.evaluate("""() => Array.from(document.querySelector(
            '.ls-series-index details').querySelectorAll('svg.ls-spark'))
            .map(strip => Math.round(strip.getBoundingClientRect().left))""")
        self.assertEqual(len(lefts), 5)
        self.assertEqual(len(set(lefts)), 1, lefts)

    def test_an_opened_folds_row_stands_at_its_top(self) -> None:
        # the node's name, what keeps it, its count and its links belong to the
        # fold's first line, and stood in the middle of a row five curves tall
        for width in (946, 1400):
            page = self._index(viewport={"width": width, "height": 900})
            page.evaluate(_OPEN_ALL)
            tops = page.evaluate("""() => {
                const row = Array.from(document.querySelectorAll(
                    '.ls-series-index tbody tr')).find(row => row.querySelector(
                    'a.ls-series-index__node[href="/status/gaffsie"]'));
                const top = (part) => Math.round(row.querySelector(part)
                    .getBoundingClientRect().top);
                return {summary: top('summary'), name: top('a.ls-series-index__node'),
                        kept: top('.ls-series-index__kept'),
                        newest: top('.ls-series-index__newest'),
                        link: top('.ls-series-index__views a'),
                        high: Math.round(row.getBoundingClientRect().height)};
            }""")
            with self.subTest(width=width):
                self.assertGreater(tops["high"], 150, tops)
                for part in ("name", "kept", "newest", "link"):
                    self.assertLess(abs(tops[part] - tops["summary"]), 6,
                                    (part, tops))

    def test_on_a_wide_window_a_curves_numbers_are_one_line(self) -> None:
        # newest, lowest and highest beneath a strip, where the table has the room:
        # from 1500 pixels, in every theme. How much room is the face's to say — this
        # estate's table needs 1097 pixels with the numbers on one line in Inter and
        # 1162 in DejaVu Sans, against a box of 1066 at 1200, and cyberpunk's
        # monospace face 1309, against a box of 1266 at 1400 (2026-10-18) — and the
        # line has to hold in each
        for theme in ("plain", "cyberpunk"):
            for width in (1500, 1600):
                page = self._index(theme=theme,
                                   viewport={"width": width, "height": 900})
                page.evaluate(_OPEN_ALL)
                lines = page.evaluate(_SAYS_LINES)
                with self.subTest(theme=theme, width=width):
                    self.assertGreater(len(lines), 5)
                    self.assertEqual(set(lines), {1}, lines)
                    # and the table is still no wider than its box
                    measured = page.evaluate(_TABLE)
                    self.assertLessEqual(measured["table"], measured["box"], measured)

    # --- a phone ------------------------------------------------------------------

    def test_on_a_phone_every_folds_control_is_on_the_screen(self) -> None:
        page = self._index(**_PHONE)
        self.assertEqual(page.evaluate(_OUTSIDE), [])
        self.assertEqual(page.locator(".ls-series-index summary").count(),
                         len(_HOSTS))

    def test_on_a_phone_an_open_fold_is_on_the_screen(self) -> None:
        page = self._index(**_PHONE)
        page.evaluate(_OPEN_ALL)
        self.assertEqual(page.evaluate(_OUTSIDE), [])
        measured = page.evaluate(_TABLE)
        self.assertLessEqual(measured["page"], measured["screen"], measured)

    def test_on_a_phone_a_row_still_says_everything_it_said(self) -> None:
        # the node, what keeps it, how much it holds, the newest reading, and where
        # else a reader goes — each inside the screen
        page = self._index(**_PHONE)
        row = page.locator(".ls-series-index tbody tr").filter(
            has=page.locator('a.ls-series-index__node[href="/status/hemulen"]'))
        words = " ".join(row.inner_text().split())
        for said in ("hemulen", "host-metrics", "macos-memory", "6 curves", "60",
                     "curves", "readings"):
            self.assertIn(said, words)
        outside = row.evaluate("""row => Array.from(row.querySelectorAll('td'))
            .filter(cell => cell.textContent.trim() !== '')
            .map(cell => cell.getBoundingClientRect())
            .filter(at => at.left < 0 || at.right > window.innerWidth + 0.5).length""")
        self.assertEqual(outside, 0)

