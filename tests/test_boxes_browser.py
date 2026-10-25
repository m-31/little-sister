"""The look `boxes`: a level's boxes in rows, or packed beneath the shortest column — in
a browser (ADR-0138).

Under `packed` every grid of open boxes — the wall's cards and a level of two or more
open boxes in a card — stands each box beneath the shortest column, so that a tall box
leaves no gap beside it, and boxes of about one height as rows stand them; a run of
chips stands in one column as a box does; a box takes its column when the page is
drawn, by the heights the tab's map leaves, and when its level's columns change, and
keeps it through a refresh, a click and its own growth — a box a click closes leaves
its chip where it stood, a chip a click opens its box where the chip stood, and a
column a click empties stays where it stood; the plan is priced for packing, so that a
tall card takes the tracks that pack the wall shortest; the wall is shown once its
boxes have their columns; no box ever stands over another; the page's order, and the
keyboard's, is the source's. Under `rows`, the library's, nothing of it is drawn, and
on a phone, one column wide, neither look moves a box.

Served by a real server to headless Chromium, on the page's own clock where a refresh
is waited for (``tests/test_tree_state_browser.py``'s way). Skipped wherever Playwright
or a Chromium binary is unavailable, so the ordinary gate does not grow a browser
dependency (``docs/testing-the-gui.md``, Mode 5).
"""
from __future__ import annotations

import re
import threading
import unittest
from dataclasses import replace
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

_SANDBOX_CHROMIUM = Path("/opt/pw-browsers/chromium-1194/chrome-linux/chrome")
_BOOTSTRAP = (Path(__file__).resolve().parent.parent / "var" / "bootstrap"
              / "node_modules" / "bootstrap" / "dist")
_FRAGMENT = re.compile(r"[?&]fragment=1")
_NOON = datetime(2026, 10, 16, 12, 0, 0, tzinfo=UTC)

#: The budget the boxes are drawn with: a tall box stands its twenty lines.
_REASON_CAP = 20

#: A card of six open boxes, the second tall, the others one line each — a level that
#: in rows leaves a column's height empty beside the tall box — and a second card of
#: one line beside it.
_CARD = "/team"
_BOXES = ("alpha", "bravo", "charlie", "delta", "echo", "foxtrot")
_TALL = "/team/bravo"
_OTHER = "/web"


def _line(number: int) -> str:
    return f"line {number}: a reading long enough to say why it is red"


def _estate(tall: tuple[str, ...] = ("bravo",),
            two: tuple[str, ...] = ()) -> StatusTree:
    tree = StatusTree()
    for name in _BOXES:
        path = f"{_CARD}/{name}"
        if name in tall:
            tree.upsert(path, StatusCode.ERROR, [_line(n) for n in range(_REASON_CAP)])
        elif name in two:
            tree.upsert(path, StatusCode.OK, ["one line", "and another"])
        else:
            tree.upsert(path, StatusCode.OK, ["one line"])
    tree.upsert(_OTHER, StatusCode.OK, ["one line"])
    return tree


def _alike(count: int = 24) -> StatusTree:
    """A card of ``count`` open boxes of one line each, and the second card."""
    tree = StatusTree()
    for number in range(count):
        tree.upsert(f"{_CARD}/b{number:02d}", StatusCode.OK, ["one line"])
    tree.upsert(_OTHER, StatusCode.OK, ["one line"])
    return tree


#: The wall's own cards: the second tall, the others one line each.
_CARDS = ("/able", "/baker", "/charlie", "/dog", "/easy")


def _cards() -> StatusTree:
    tree = StatusTree()
    for path in _CARDS:
        if path == "/baker":
            tree.upsert(path, StatusCode.ERROR, [_line(n) for n in range(_REASON_CAP)])
        else:
            tree.upsert(path, StatusCode.OK, ["one line"])
    return tree


#: Every box of every packed level, by its node's path: where it stands and how
#: tall, and its level's packed columns.
_BOXES_JS = """
() => {
  const out = {};
  for (const node of document.querySelectorAll('.tree-node[data-node]')) {
    const box = node.getBoundingClientRect();
    if (!box.height) { continue; }
    out[node.dataset.node] = {left: box.left, top: box.top, bottom: box.bottom,
                              right: box.right};
  }
  return out;
}
"""

#: Every pair of grid items of one level that stand over one another.
_OVERLAPS_JS = """
() => {
  const found = [];
  for (const level of document.querySelectorAll(
          '.status-grid, .status-card .node-children')) {
    if (getComputedStyle(level).display !== 'grid') { continue; }
    const items = [];
    for (const child of level.children) {
      const display = getComputedStyle(child).display;
      if (display === 'none') { continue; }
      if (display === 'contents') { items.push(...child.children); continue; }
      items.push(child);
    }
    for (let i = 0; i < items.length; i += 1) {
      for (let j = i + 1; j < items.length; j += 1) {
        const a = items[i].getBoundingClientRect();
        const b = items[j].getBoundingClientRect();
        const wide = Math.min(a.right, b.right) - Math.max(a.left, b.left);
        const tall = Math.min(a.bottom, b.bottom) - Math.max(a.top, b.top);
        if (wide > 1 && tall > 1) {
          found.push(`${items[i].dataset.node || items[i].className} over `
                     + `${items[j].dataset.node || items[j].className}`);
        }
      }
    }
  }
  return found;
}
"""


#: Before `tree.js` runs — at the parser's last pause before it, once the scripts
#: ahead of it have run — the plan laid and the boxes packed as a frame would lay and
#: pack them there, and where each then stood, by its node's path.
_PACKED_EARLY_JS = """
(() => {
  const early = new MutationObserver(() => {
    if (!document.querySelector('script[src*="/js/tree.js"]')) { return; }
    early.disconnect();
    window.lsLayout.apply();
    window.lsLayout.pack();
    const out = {};
    for (const node of document.querySelectorAll('.tree-node[data-node]')) {
      out[node.dataset.node] = node.getBoundingClientRect().left;
    }
    window.lsPackedEarly = out;
  });
  early.observe(document, {childList: true, subtree: true});
})();
"""


class _Quiet(WSGIRequestHandler):
    def log_message(self, format: str, *args: object) -> None:
        pass


class BoxesTests(unittest.TestCase):
    """The look `boxes` on a desk, and on a phone."""

    playwright: Any = None
    browser: Any = None
    server: WSGIServer | None = None
    base = ""
    desk: ClassVar[dict[str, Any]] = {
        "viewport": {"width": 1600, "height": 900}, "reduced_motion": "reduce"}

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
        cls.saved = (app_module.status_tree, app_module.config)
        app_module.status_tree = _estate()
        app_module.config = replace(app_module.config, reason_cap=_REASON_CAP)
        cls.server = make_server("127.0.0.1", 0, app_module.app,
                                 server_class=PageServer, handler_class=_Quiet)
        threading.Thread(target=cls.server.serve_forever, daemon=True).start()
        cls.base = f"http://127.0.0.1:{cls.server.server_port}"

    @classmethod
    def tearDownClass(cls) -> None:
        if cls.server is not None:
            cls.server.shutdown()
            cls.server.server_close()
        app_module.status_tree, app_module.config = cls.saved
        cls.browser.close()
        cls.playwright.stop()

    def setUp(self) -> None:
        app_module.status_tree = _estate()
        self.fragments: list[str] = []

    @staticmethod
    def _vendored(route: Any) -> None:
        name = route.request.url.rsplit("/", 1)[-1]
        for candidate in (_BOOTSTRAP / "css" / name, _BOOTSTRAP / "js" / name):
            if candidate.is_file():
                route.fulfill(path=str(candidate))
                return
        route.continue_()

    def _signed_in(self, boxes: str, drawn_in: dict[str, Any] | None = None) -> Any:
        """A page signed in under ``boxes``."""
        context = self.browser.new_context(**(drawn_in or self.desk))
        self.addCleanup(context.close)
        context.route("https://cdn.jsdelivr.net/**", self._vendored)
        context.add_cookies([looks(self.base, boxes=boxes)])
        page = context.new_page()
        page.on("request", lambda request: (
            self.fragments.append(request.url)
            if _FRAGMENT.search(request.url) else None))
        page.goto(f"{self.base}/login")
        page.fill("#username", "pan")
        page.fill("#password", "12345678")
        with page.expect_navigation():
            page.click("button[type=submit]")
        return page

    def _wall(self, boxes: str, drawn_in: dict[str, Any] | None = None, *,
              held: bool = True) -> Any:
        """The wall under ``boxes``, signed in — where ``held``, on the page's own
        clock stopped short of the first refresh."""
        page = self._signed_in(boxes, drawn_in)
        if held:
            page.clock.install(time=_NOON)
        page.goto(f"{self.base}/status")
        page.wait_for_selector("#status-grid .status-card")
        if held:
            page.clock.pause_at(_NOON + timedelta(seconds=5))
        return page

    @staticmethod
    def _shown(page: Any) -> str:
        shown: str = page.evaluate(
            "getComputedStyle(document.getElementById('status-grid')).visibility")
        return shown

    def _swap(self, page: Any) -> None:
        """One tick of the refresh, and the swap it brings."""
        page.evaluate("document.querySelector('#status-grid .status-card')"
                      ".dataset.drawn = 'before'")
        before = len(self.fragments)
        page.clock.run_for(10_000)
        page.wait_for_function(
            "document.querySelector('#status-grid [data-drawn]') === null",
            timeout=5000)
        self.assertGreater(len(self.fragments), before)

    def _boxes(self, page: Any) -> dict[str, dict[str, float]]:
        boxes: dict[str, dict[str, float]] = page.evaluate(_BOXES_JS)
        return boxes

    def _level(self, page: Any) -> list[str]:
        return [f"{_CARD}/{name}" for name in _BOXES]

    def _columns(self, page: Any) -> int:
        columns: int = page.evaluate(
            f"""() => {{
              const level = document.querySelector(
                  '.tree-node[data-node="{_CARD}"] .node-children');
              return getComputedStyle(level).gridTemplateColumns.split(' ')
                  .filter(t => parseFloat(t) > 0).length;
            }}""")
        return columns

    def test_rows_leave_the_tall_boxs_row_mates_columns_empty(self) -> None:
        # the library's look, as ADR-0056 draws it: the boxes after the first row
        # start beneath the tall box, and nothing of the packing is drawn
        page = self._wall("rows")
        columns = self._columns(page)
        self.assertGreaterEqual(columns, 2)
        boxes = self._boxes(page)
        after = f"{_CARD}/{_BOXES[columns]}"
        self.assertGreaterEqual(boxes[after]["top"], boxes[_TALL]["bottom"])
        self.assertEqual(page.locator(".is-packed").count(), 0)
        self.assertEqual(page.evaluate(
            "[...document.querySelectorAll('.tree-node')]"
            ".filter(n => n.style.gridRow).length"), 0)
        self.assertEqual(page.evaluate(_OVERLAPS_JS), [])

    def test_packed_fills_the_columns_beside_the_tall_box(self) -> None:
        page = self._wall("packed")
        columns = self._columns(page)
        self.assertGreaterEqual(columns, 2)
        boxes = self._boxes(page)
        level = self._level(page)
        # every box after the tall one's row stands beside it, beneath a short one
        for path in level[columns:]:
            with self.subTest(box=path):
                self.assertLess(boxes[path]["top"], boxes[_TALL]["bottom"])
                self.assertNotAlmostEqual(boxes[path]["left"], boxes[_TALL]["left"],
                                          delta=1)
        self.assertEqual(page.evaluate(_OVERLAPS_JS), [])
        # the gap between two boxes of a column is the level's gap, as in rows
        first, below = level[0], next(
            path for path in level[columns:]
            if abs(boxes[path]["left"] - boxes[level[0]]["left"]) < 1)
        gap = page.evaluate(
            f"""() => parseFloat(getComputedStyle(document.querySelector(
                '.tree-node[data-node="{_CARD}"] .node-children')).columnGap)""")
        self.assertAlmostEqual(boxes[below]["top"] - boxes[first]["bottom"], gap,
                               delta=0.5)
        # packed again, nothing moves: the margin that stands a box is not its height
        page.evaluate("window.lsLayout.pack()")
        again = self._boxes(page)
        for path in level:
            with self.subTest(again=path):
                self.assertAlmostEqual(again[path]["top"], boxes[path]["top"],
                                       delta=0.5)

    def test_boxes_of_about_one_height_keep_their_reading_order(self) -> None:
        # the first box a line taller than the others: the next takes the leftmost
        # column within the tolerance of the shortest (`PACK_TOLERANCE`, 32 pixels),
        # not the shortest itself, so a level of boxes of about one height stands each
        # in the column rows give it
        app_module.status_tree = _estate(tall=(), two=("alpha",))
        rows = self._boxes(self._wall("rows"))
        page = self._wall("packed")
        packed = self._boxes(page)
        level = self._level(page)
        taller = packed[level[0]]["bottom"] - packed[level[0]]["top"]
        short = packed[level[1]]["bottom"] - packed[level[1]]["top"]
        self.assertGreater(taller - short, 4)
        self.assertLess(taller - short, 32)
        for path in level:
            with self.subTest(box=path):
                self.assertAlmostEqual(packed[path]["left"], rows[path]["left"],
                                       delta=1)

    def test_a_level_of_boxes_alike_stands_no_taller_packed(self) -> None:
        # 24 boxes of one line, fewer than make a level big: each column as many
        # boxes deep as rows stand them in as many columns, and the level as tall as
        # rows make it there — the plan priced for packing may give the card other
        # columns than rows' plan does, so the level is held to its own
        app_module.status_tree = _alike()
        page = self._wall("packed")
        self.assertGreater(page.locator(".is-packed").count(), 0)
        columns = self._columns(page)
        boxes = self._boxes(page)
        level = [f"{_CARD}/b{number:02d}" for number in range(24)]
        lefts: dict[int, int] = {}
        for path in level:
            left = round(boxes[path]["left"])
            lefts[left] = lefts.get(left, 0) + 1
        self.assertEqual(len(lefts), columns)
        deep = -(-24 // columns)
        self.assertEqual(sorted(lefts.values(), reverse=True)[0], deep)
        box = boxes[level[0]]["bottom"] - boxes[level[0]]["top"]
        gap = page.evaluate(
            f"""() => parseFloat(getComputedStyle(document.querySelector(
                '.tree-node[data-node="{_CARD}"] .node-children')).rowGap)""")
        height = page.evaluate(f"""() => document.querySelector(
            '.tree-node[data-node="{_CARD}"] .node-children').getBoundingClientRect()
            .height""")
        self.assertAlmostEqual(height, deep * box + (deep - 1) * gap, delta=1)
        self.assertEqual(page.evaluate(_OVERLAPS_JS), [])

    def test_a_levels_first_boxes_stand_one_to_a_column(self) -> None:
        # the first box drawn shorter than the tolerance: the next takes the empty
        # column beside it, as rows' first row stands, rather than going beneath it
        page = self._wall("packed")
        first = f"{_CARD}/alpha"
        page.evaluate(f"""() => {{
            const box = document.querySelector('.tree-node[data-node="{first}"]');
            box.style.height = '12px';
            box.style.overflow = 'hidden';
            window.lsLayout.draw();
        }}""")
        boxes = self._boxes(page)
        columns = self._columns(page)
        lefts = {round(boxes[path]["left"]) for path in self._level(page)[:columns]}
        self.assertEqual(len(lefts), columns)
        self.assertEqual(page.evaluate(_OVERLAPS_JS), [])

    def test_the_page_order_is_the_sources(self) -> None:
        # the keyboard walks the page's order, which the packing does not touch
        rows = self._wall("rows")
        packed = self._wall("packed")
        order = "[...document.querySelectorAll('.tree-node[data-node]')]" \
                ".map(n => n.dataset.node)"
        self.assertEqual(packed.evaluate(order), rows.evaluate(order))

    def test_a_refresh_keeps_every_box_in_its_column(self) -> None:
        # the first box grows as tall as the second: a page drawn afresh would stand
        # the boxes after them elsewhere, and the refresh restacks them where they are
        page = self._wall("packed")
        before = self._boxes(page)
        app_module.status_tree = _estate(tall=("alpha", "bravo"))
        self._swap(page)
        after = self._boxes(page)
        for path in self._level(page):
            with self.subTest(box=path):
                self.assertAlmostEqual(after[path]["left"], before[path]["left"],
                                       delta=1)
        self.assertGreater(after[f"{_CARD}/alpha"]["bottom"],
                           before[f"{_CARD}/alpha"]["bottom"] + 100)
        self.assertEqual(page.evaluate(_OVERLAPS_JS), [])
        # drawn again, the page packs afresh: a box beneath the first, which grew,
        # takes the shortest column now
        page.reload()
        page.wait_for_selector("#status-grid .status-card")
        drawn = self._boxes(page)
        moved = [path for path in self._level(page)
                 if abs(drawn[path]["left"] - after[path]["left"]) > 1]
        self.assertTrue(moved, "a page drawn afresh packs afresh")
        self.assertEqual(page.evaluate(_OVERLAPS_JS), [])

    def test_a_refresh_is_packed_before_anything_reads_the_page(self) -> None:
        # what reads the page as the swap ends — tree.js putting the window back, a
        # script listening for the swap — finds every box where it is then drawn
        page = self._wall("packed")
        page.evaluate(f"""() => document.getElementById('status-grid').addEventListener(
            'ls:swapped', () => {{ window.lsSwapped = ({_BOXES_JS})(); }},
            {{once: true}})""")
        app_module.status_tree = _estate(tall=("alpha", "bravo"))
        self._swap(page)
        swapped: dict[str, dict[str, float]] = page.evaluate("window.lsSwapped")
        after = self._boxes(page)
        for path in self._level(page):
            with self.subTest(box=path):
                self.assertAlmostEqual(swapped[path]["left"], after[path]["left"],
                                       delta=1)
                self.assertAlmostEqual(swapped[path]["top"], after[path]["top"],
                                       delta=1)

    def test_a_click_is_packed_before_anything_reads_the_page(self) -> None:
        # the third box closed to a chip: what reads the page as the click ends finds
        # every box where the frames after it draw it, on the browser's own clock
        page = self._wall("packed", held=False)
        closed = f"{_CARD}/charlie"
        drawn: list[dict[str, dict[str, float]]] = page.evaluate(f"""async () => {{
            const boxes = {_BOXES_JS};
            document.querySelector(
                '[data-path="{closed}"] [data-control="toggle"]').click();
            const clicked = boxes();
            await new Promise(
                r => requestAnimationFrame(() => requestAnimationFrame(r)));
            return [clicked, boxes()];
        }}""")
        clicked, later = drawn
        self.assertTrue(page.locator(
            f'.tree-run > .tree-node[data-node="{closed}"]').count())
        for path in self._level(page):
            with self.subTest(box=path):
                self.assertAlmostEqual(clicked[path]["left"], later[path]["left"],
                                       delta=1)
                self.assertAlmostEqual(clicked[path]["top"], later[path]["top"],
                                       delta=1)

    def test_a_refresh_leaves_the_window_where_it_stood(self) -> None:
        # scrolled down to a box beneath the first, which the refresh makes taller:
        # the box moves down its column, and the window with it (ADR-0127 decision 10)
        low = {"viewport": {"width": 1600, "height": 400}, "reduced_motion": "reduce"}
        page = self._wall("packed", low)
        # room beneath the wall, so the window can follow the box as far as it goes
        page.add_style_tag(content="body { padding-bottom: 2000px; }")
        anchor = f"{_CARD}/foxtrot"
        page.evaluate(f"""() => window.scrollTo(0, document.querySelector(
            '.tree-node[data-node="{anchor}"]').getBoundingClientRect().top
            + window.scrollY - 40)""")
        stood = self._boxes(page)[anchor]["top"]
        app_module.status_tree = _estate(tall=("alpha", "bravo"))
        self._swap(page)
        self.assertGreater(page.evaluate("window.scrollY"), 0)
        self.assertAlmostEqual(self._boxes(page)[anchor]["top"], stood, delta=1)
        self.assertEqual(page.evaluate(_OVERLAPS_JS), [])

    def test_a_click_keeps_every_other_box_in_its_column(self) -> None:
        # *⌄ all N* on the tall box: it grows, and every box keeps its column
        app_module.config = replace(app_module.config, reason_cap=6)
        self.addCleanup(lambda: setattr(app_module, "config", replace(
            app_module.config, reason_cap=_REASON_CAP)))
        page = self._wall("packed")
        before = self._boxes(page)
        page.locator(f'.reason-block[data-reason-node="{_TALL}"] '
                     f'+ .reason-more:not([hidden])').click()
        page.wait_for_function(
            f"""() => document.querySelector(
                '.reason-block[data-reason-node="{_TALL}"]').classList
                .contains('is-open')""")
        after = self._boxes(page)
        self.assertGreater(after[_TALL]["bottom"], before[_TALL]["bottom"] + 50)
        for path in self._level(page):
            with self.subTest(box=path):
                self.assertAlmostEqual(after[path]["left"], before[path]["left"],
                                       delta=1)
        self.assertEqual(page.evaluate(_OVERLAPS_JS), [])

    def test_a_box_that_grows_of_itself_restacks_its_column(self) -> None:
        # a box grows with no refresh and no click — as a font arriving grows it: the
        # browser says so, and the boxes beneath it in its column move down with it, on
        # the browser's own clock, which delivers what it says at once
        page = self._wall("packed", held=False)
        level = self._level(page)
        before = self._boxes(page)
        first = level[0]
        below = next(path for path in level[1:]
                     if abs(before[path]["left"] - before[first]["left"]) < 1)
        page.evaluate(f"""() => document.querySelector(
            '.tree-node[data-node="{first}"]').style.paddingBottom = '300px'""")
        page.wait_for_function(f"""() => {{
            const box = (path) => document.querySelector(
                `.tree-node[data-node="${{path}}"]`).getBoundingClientRect();
            return box("{below}").top >= box("{first}").bottom;
        }}""", timeout=5000)
        self.assertEqual(page.evaluate(_OVERLAPS_JS), [])
        after = self._boxes(page)
        for path in level:
            with self.subTest(box=path):
                self.assertAlmostEqual(after[path]["left"], before[path]["left"],
                                       delta=1)

    def test_a_width_that_changes_the_columns_packs_afresh(self) -> None:
        # on the browser's own clock, since the plan is laid again in an animation
        # frame and the boxes restack when the browser says they changed size, both
        # of which a held clock may leave waiting; the test is done long before the
        # refresh
        page = self._wall("packed", held=False)
        columns = self._columns(page)
        # narrower, where the card's level has another number of columns
        page.set_viewport_size({"width": 1000, "height": 900})
        page.wait_for_function(
            f"""() => getComputedStyle(document.querySelector(
                '.tree-node[data-node="{_CARD}"] .node-children'))
                .gridTemplateColumns.split(' ').filter(t => parseFloat(t) > 0)
                .length === 2""")
        page.evaluate("() => new Promise(r => requestAnimationFrame("
                      "() => requestAnimationFrame(r)))")
        self.assertNotEqual(self._columns(page), columns)
        self.assertGreaterEqual(self._columns(page), 2)
        self.assertEqual(page.evaluate(_OVERLAPS_JS), [])
        # every column the level has stands a box, the packing being afresh
        boxes = self._boxes(page)
        lefts = {round(boxes[path]["left"]) for path in self._level(page)}
        self.assertEqual(len(lefts), self._columns(page))

    def test_a_width_of_one_column_draws_the_level_as_rows(self) -> None:
        # packed at a desk, then narrowed to a phone's width, where the level has one
        # column: nothing of the packing is left on it, and its boxes stand as rows
        # stand them, on the browser's own clock as the width before
        page = self._wall("packed", held=False)
        self.assertGreater(page.locator(".is-packed").count(), 0)
        page.set_viewport_size({"width": 390, "height": 844})
        page.wait_for_function(
            "() => document.querySelectorAll('.is-packed').length === 0")
        page.evaluate("() => new Promise(r => requestAnimationFrame("
                      "() => requestAnimationFrame(r)))")
        left: int = page.evaluate(
            "() => [...document.querySelectorAll('.tree-node')].filter(n =>"
            " n.style.gridRow || n.style.marginTop).length")
        self.assertEqual(left, 0)
        rows = self._wall("rows", {"viewport": {"width": 390, "height": 844},
                                   "reduced_motion": "reduce"}, held=False)
        packed, drawn = self._boxes(page), self._boxes(rows)
        for path in self._level(page):
            with self.subTest(box=path):
                self.assertAlmostEqual(packed[path]["top"] - packed[_CARD]["top"],
                                       drawn[path]["top"] - drawn[_CARD]["top"],
                                       delta=1)

    def test_a_card_whose_span_changes_packs_its_level_afresh(self) -> None:
        # the plan of another width laying as many tracks, the first card two of them
        # wide where it was one: the wall is packed afresh, as a page drawn then packs
        app_module.status_tree = _cards()
        page = self._wall("packed")

        def band(plan: list[int]) -> None:
            page.evaluate(f"""() => {{
                const grid = document.querySelector('.status-grid');
                grid.setAttribute('data-layout-breakpoints',
                                  JSON.stringify([[1, 3, {plan}]]));
                window.lsLayout.apply();
            }}""")

        band([1] * len(_CARDS))
        page.evaluate("() => window.lsLayout.draw()")
        band([2] + [1] * (len(_CARDS) - 1))
        self.assertEqual(page.get_attribute(
            f'.status-card[data-node="{_CARDS[0]}"]', "data-layout-span"), "2")
        page.evaluate("() => window.lsLayout.pack()")
        packed = self._boxes(page)
        page.evaluate("() => window.lsLayout.draw()")
        drawn = self._boxes(page)
        for path in _CARDS:
            with self.subTest(card=path):
                self.assertAlmostEqual(packed[path]["left"], drawn[path]["left"],
                                       delta=1)
        self.assertEqual(page.evaluate(_OVERLAPS_JS), [])

    def test_packed_fills_the_walls_columns_too(self) -> None:
        # the wall's cards are a level of the same kind: in rows the cards after the
        # first row start beneath the tall one, packed they stand beside it
        app_module.status_tree = _cards()
        narrow = {"viewport": {"width": 1000, "height": 900},
                  "reduced_motion": "reduce"}
        rows = self._boxes(self._wall("rows", narrow))
        page = self._wall("packed", narrow)
        packed = self._boxes(page)
        tracks: int = page.evaluate(
            "getComputedStyle(document.querySelector('.status-grid'))"
            ".gridTemplateColumns.split(' ').filter(t => parseFloat(t) > 0).length")
        self.assertGreaterEqual(tracks, 2)
        after = _CARDS[tracks]
        self.assertGreaterEqual(rows[after]["top"], rows["/baker"]["bottom"])
        self.assertLess(packed[after]["top"], packed["/baker"]["bottom"])
        self.assertEqual(page.evaluate(_OVERLAPS_JS), [])

    def _close(self, page: Any, path: str) -> None:
        page.locator(f'[data-path="{path}"] [data-control="toggle"]').first.click()
        page.wait_for_selector(f'.tree-run > .tree-node[data-node="{path}"]')

    def _open(self, page: Any, path: str) -> None:
        page.locator(f'.tree-node[data-node="{path}"] > .tree-chip').click()
        page.wait_for_selector(f'.tree-node[data-node="{path}"][data-state-now="open"]')

    @staticmethod
    def _run(page: Any, path: str) -> dict[str, float]:
        """Where the run that holds ``path``'s chip stands, and the chip in it."""
        run: dict[str, float] = page.evaluate(f"""() => {{
            const node = document.querySelector('.tree-node[data-node="{path}"]');
            const r = node.closest('.tree-run').getBoundingClientRect();
            const chip = node.querySelector(':scope > .tree-chip')
                .getBoundingClientRect();
            return {{left: r.left, top: r.top, bottom: r.bottom, width: r.width,
                     chip_left: chip.left, chip_top: chip.top}};
        }}""")
        return run

    def test_a_card_a_click_closes_leaves_its_chip_where_its_box_stood(self) -> None:
        # the fourth box, beneath the first, closed to a chip: its run stands in one
        # column, the one the box stood in and where it stood, the chip at the run's
        # top and not as low as the box stood; the boxes in the other columns stand as
        # they stood, and the one beneath it moves up its column
        page = self._wall("packed")
        before = self._boxes(page)
        closed = f"{_CARD}/delta"
        self.assertGreater(before[closed]["top"], before[f"{_CARD}/alpha"]["bottom"])
        self._close(page, closed)
        after = self._boxes(page)
        run = self._run(page, closed)
        self.assertAlmostEqual(run["left"], before[closed]["left"], delta=1)
        self.assertAlmostEqual(run["top"], before[closed]["top"], delta=1)
        wide = before[closed]["right"] - before[closed]["left"]
        self.assertAlmostEqual(run["width"], wide, delta=1)
        self.assertAlmostEqual(run["chip_top"], run["top"], delta=1)
        beneath = [path for path in self._level(page)
                   if path != closed
                   and abs(before[path]["left"] - before[closed]["left"]) < 1
                   and before[path]["top"] > before[closed]["top"]]
        self.assertTrue(beneath, "a box beneath the closed one, in its column")
        for path in self._level(page):
            if path == closed:
                continue
            with self.subTest(box=path):
                self.assertAlmostEqual(after[path]["left"], before[path]["left"],
                                       delta=1)
                if path in beneath:
                    self.assertLess(after[path]["top"], before[path]["top"] - 10)
                    self.assertGreaterEqual(after[path]["top"], run["bottom"])
                else:
                    self.assertAlmostEqual(after[path]["top"], before[path]["top"],
                                           delta=1)
        self.assertEqual(page.evaluate(_OVERLAPS_JS), [])

    def test_a_chip_a_click_opens_stands_its_box_where_the_chip_stood(self) -> None:
        # closed, then opened again by its chip: the box stands where the chip stood,
        # and every other box in the column it had
        page = self._wall("packed")
        opened = f"{_CARD}/charlie"
        self._close(page, opened)
        closed = self._boxes(page)
        run = self._run(page, opened)
        self._open(page, opened)
        after = self._boxes(page)
        self.assertAlmostEqual(after[opened]["left"], run["left"], delta=1)
        self.assertAlmostEqual(after[opened]["top"], run["top"], delta=1)
        for path in self._level(page):
            if path == opened:
                continue
            with self.subTest(box=path):
                self.assertAlmostEqual(after[path]["left"], closed[path]["left"],
                                       delta=1)
        self.assertEqual(page.evaluate(_OVERLAPS_JS), [])

    def test_a_chip_opened_from_a_longer_run_stands_in_the_runs_column(self) -> None:
        # the tall box and its neighbour after it closed into one run, in the tall
        # one's column, and the neighbour opened again: its box stands in the run's
        # column beneath what is left of the run, not in the column it stood in first
        page = self._wall("packed")
        first, second = _TALL, f"{_CARD}/charlie"
        stood = self._boxes(page)[second]["left"]
        self._close(page, first)
        self._close(page, second)
        run = self._run(page, second)
        self.assertAlmostEqual(self._run(page, first)["left"], run["left"], delta=1)
        self._open(page, second)
        after = self._boxes(page)
        left = self._run(page, first)
        self.assertAlmostEqual(after[second]["left"], run["left"], delta=1)
        self.assertNotAlmostEqual(after[second]["left"], stood, delta=1)
        self.assertAlmostEqual(left["left"], run["left"], delta=1)
        self.assertGreaterEqual(after[second]["top"], left["bottom"])
        self.assertEqual(page.evaluate(_OVERLAPS_JS), [])

    def test_a_run_stands_where_the_first_of_its_nodes_stood(self) -> None:
        # the fourth box closed, then the third, its neighbour before it: one run of
        # the two, in the third's column, whichever closed first
        page = self._wall("packed")
        before = self._boxes(page)
        third, fourth = f"{_CARD}/charlie", f"{_CARD}/delta"
        self.assertNotAlmostEqual(before[third]["left"], before[fourth]["left"],
                                  delta=1)
        self._close(page, fourth)
        self.assertAlmostEqual(self._run(page, fourth)["left"], before[fourth]["left"],
                               delta=1)
        self._close(page, third)
        run = self._run(page, fourth)
        self.assertAlmostEqual(run["left"], before[third]["left"], delta=1)
        self.assertAlmostEqual(self._run(page, third)["top"], run["top"], delta=1)
        self.assertEqual(page.evaluate(_OVERLAPS_JS), [])

    def test_a_run_keeps_its_column_through_a_refresh(self) -> None:
        # the fourth box closed beneath the first, which the refresh makes tall: the
        # run stays beneath it, where a page drawn afresh would stand it elsewhere
        page = self._wall("packed")
        closed = f"{_CARD}/delta"
        self._close(page, closed)
        run = self._run(page, closed)
        before = self._boxes(page)
        app_module.status_tree = _estate(tall=("alpha", "bravo"))
        self._swap(page)
        self.assertAlmostEqual(self._run(page, closed)["left"], run["left"], delta=1)
        after = self._boxes(page)
        for path in self._level(page):
            if path == closed:
                continue
            with self.subTest(box=path):
                self.assertAlmostEqual(after[path]["left"], before[path]["left"],
                                       delta=1)
        self.assertEqual(page.evaluate(_OVERLAPS_JS), [])

    def test_a_column_a_click_empties_stays_where_it_stood(self) -> None:
        # the first box closed, then the tall one beside it, alone in its column: one
        # run of the two in the first's column, the tall one's column left empty, and
        # the columns beside it as wide as they were, where they were
        page = self._wall("packed")
        before = self._boxes(page)
        first = f"{_CARD}/alpha"
        alone = [path for path in self._level(page) if path != _TALL
                 and abs(before[path]["left"] - before[_TALL]["left"]) < 1]
        self.assertEqual(alone, [])
        self._close(page, first)
        self._close(page, _TALL)
        self.assertAlmostEqual(self._run(page, _TALL)["left"], before[first]["left"],
                               delta=1)
        after = self._boxes(page)
        for path in self._level(page):
            if path in (first, _TALL):
                continue
            with self.subTest(box=path):
                self.assertAlmostEqual(after[path]["left"], before[path]["left"],
                                       delta=1)
                self.assertAlmostEqual(after[path]["right"], before[path]["right"],
                                       delta=1)
        self.assertEqual(page.evaluate(_OVERLAPS_JS), [])

    def test_a_drawn_level_lays_as_many_columns_as_its_items_fill(self) -> None:
        # wide enough for six columns of the card's level: the last four boxes closed
        # into one run leave three items, which keep the six columns the clicks found;
        # drawn again, the level lays three, a third of it each, where the
        # stylesheet's would keep every track the run spans
        wide = {"viewport": {"width": 2800, "height": 900}, "reduced_motion": "reduce"}
        page = self._wall("packed", wide)
        self.assertEqual(self._columns(page), 6)
        for name in _BOXES[2:]:
            self._close(page, f"{_CARD}/{name}")
        self.assertEqual(self._columns(page), 6)
        page.reload()
        page.wait_for_selector(f'.tree-run > .tree-node[data-node="{_CARD}/foxtrot"]')
        self.assertEqual(self._columns(page), 3)
        widths: list[float] = page.evaluate(f"""() => {{
            const level = document.querySelector(
                '.tree-node[data-node="{_CARD}"] .node-children');
            return [level.getBoundingClientRect().width,
                    ...[...level.children].map(c => c.getBoundingClientRect().width)];
        }}""")
        level, items = widths[0], widths[1:]
        self.assertEqual(len(items), 3)
        for width in items:
            self.assertAlmostEqual(width, (level - 2 * 6.4) / 3, delta=1)
        self.assertEqual(page.evaluate(_OVERLAPS_JS), [])

    def test_a_run_a_click_forms_is_read_one_column_wide(self) -> None:
        # chips too wide for two to a column's line: the fourth box closed, then the
        # fifth, which joins its run — a run new to the level, two lines in its column
        # and one across the level — and what reads the page as the click ends finds
        # every box where the frames after it draw it
        page = self._wall("packed", held=False)
        page.add_style_tag(
            content=".tree-run > .tree-node { min-width: 250px !important; }")
        fourth, fifth = f"{_CARD}/delta", f"{_CARD}/echo"
        self._close(page, fourth)
        drawn: list[dict[str, dict[str, float]]] = page.evaluate(f"""async () => {{
            const boxes = {_BOXES_JS};
            document.querySelector(
                '[data-path="{fifth}"] [data-control="toggle"]').click();
            const clicked = boxes();
            await new Promise(
                r => requestAnimationFrame(() => requestAnimationFrame(r)));
            return [clicked, boxes()];
        }}""")
        clicked, later = drawn
        run = self._run(page, fifth)
        self.assertGreater(run["bottom"] - run["top"], 40)
        for path in self._level(page):
            with self.subTest(box=path):
                self.assertAlmostEqual(clicked[path]["top"], later[path]["top"],
                                       delta=1)
        self.assertEqual(page.evaluate(_OVERLAPS_JS), [])

    def test_a_level_a_click_leaves_one_open_box_stands_as_rows_do(self) -> None:
        # every box but the tall one closed: the level is no grid, nothing of the
        # packing is left on it, and nothing stands its chips or the box lower
        page = self._wall("packed")
        for name in _BOXES:
            path = f"{_CARD}/{name}"
            if path != _TALL:
                self._close(page, path)
        left: list[str] = page.evaluate(
            f"""() => {{
              const level = document.querySelector(
                  '.tree-node[data-node="{_CARD}"] .node-children');
              return [level, ...level.querySelectorAll(':scope > *, :scope > * > *')]
                  .filter(el => el.style.marginTop || el.style.gridRow
                                || el.style.gridTemplateColumns
                                || el.classList.contains('is-packed'))
                  .map(el => el.dataset.node || el.className);
            }}""")
        self.assertEqual(left, [])

    def test_a_tall_card_takes_the_tracks_that_pack_the_wall_shortest(self) -> None:
        # two tracks: rows' plan gives the card of six boxes one of them, since a row
        # of two cards has no track to spare; packed, the plan priced for packing
        # (ADR-0138) gives it both, the second card beneath it, and the wall is lower
        narrow = {"viewport": {"width": 1000, "height": 900},
                  "reduced_motion": "reduce"}
        spans = ("() => [...document.querySelector('.status-grid').children]"
                 ".map(card => card.dataset.layoutSpan)")
        height = ("() => document.querySelector('.status-grid')"
                  ".getBoundingClientRect().height")
        rows = self._wall("rows", narrow)
        packed = self._wall("packed", narrow)
        self.assertEqual(rows.evaluate(spans), ["1", "1"])
        self.assertEqual(packed.evaluate(spans), ["2", "1"])
        self.assertLess(packed.evaluate(height), rows.evaluate(height) - 100)
        self.assertEqual(packed.evaluate(_OVERLAPS_JS), [])

    def test_packed_the_wall_is_shown_once_its_boxes_have_their_columns(self) -> None:
        # a first paint in rows would have the packing move every box beside the tall
        # one, so under `packed` the wall is hidden until tree.js has drawn it: here a
        # tree.js that never comes, on a clock stopped from the first paint — hidden
        # until tree-pending.js's timer shows it after a second; under `rows` at once
        for boxes, first in (("rows", "visible"), ("packed", "hidden")):
            with self.subTest(boxes=boxes):
                page = self._signed_in(boxes)
                page.route("**/static/js/tree.js*", lambda route: route.abort())
                page.clock.install(time=_NOON)
                page.clock.pause_at(_NOON + timedelta(seconds=1))
                page.goto(f"{self.base}/status")
                page.wait_for_selector("#status-grid .status-card", state="attached")
                self.assertEqual(self._shown(page), first)
                page.clock.run_for(1_000)
                self.assertEqual(self._shown(page), "visible")
        # drawn, the wall is shown at once, its boxes in their columns
        page = self._wall("packed")
        self.assertEqual(self._shown(page), "visible")
        self.assertGreater(page.locator(".is-packed").count(), 0)

    def test_a_load_packs_by_the_heights_the_tabs_map_leaves(self) -> None:
        # the tall box closed by a click, which the tab's map keeps through a reload:
        # the page is drawn with it closed, and a frame that packed the boxes before
        # tree.js put the map back — as on a long wall, which paints while the parser
        # is still on its way to the scripts — leaves no column behind
        page = self._wall("packed")
        page.locator(f'[data-path="{_TALL}"] [data-control="toggle"]').first.click()
        page.wait_for_selector(f'.tree-run > .tree-node[data-node="{_TALL}"]')
        page.reload()
        page.wait_for_selector(f'.tree-run > .tree-node[data-node="{_TALL}"]')
        drawn = self._boxes(page)
        page.add_init_script(_PACKED_EARLY_JS)
        page.reload()
        page.wait_for_selector(f'.tree-run > .tree-node[data-node="{_TALL}"]')
        early: dict[str, float] = page.evaluate("window.lsPackedEarly")
        again = self._boxes(page)
        boxes = [path for path in self._level(page) if path != _TALL]
        # the frame before the map stood a box elsewhere, by the tall box's height
        self.assertTrue([path for path in boxes
                         if abs(early[path] - drawn[path]["left"]) > 1])
        for path in boxes:
            with self.subTest(box=path):
                self.assertAlmostEqual(again[path]["left"], drawn[path]["left"],
                                       delta=1)
        self.assertEqual(page.evaluate(_OVERLAPS_JS), [])

    def test_on_a_phone_neither_look_moves_a_box(self) -> None:
        phone = {"viewport": {"width": 390, "height": 844}, "device_scale_factor": 2,
                 "is_mobile": True, "has_touch": True, "reduced_motion": "reduce"}
        rows = self._boxes(self._wall("rows", phone))
        page = self._wall("packed", phone)
        self.assertEqual(page.locator(".is-packed").count(), 0)
        packed = self._boxes(page)
        for path in self._level(page):
            with self.subTest(box=path):
                self.assertAlmostEqual(packed[path]["top"], rows[path]["top"], delta=1)


if __name__ == "__main__":
    unittest.main()
