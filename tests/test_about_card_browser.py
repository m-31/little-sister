"""A node's About card stands beside its facts at a desk and among them on a phone —
held against a real browser (ADR-0133 decision 1).

``tests/test_web.py``'s ``AboutCardTests`` hold what the response says: the card after
the facts' own column in the document, *Configuration* marked, the block the
container its columns ask. Where the card lands is the browser's: beside *Time*,
from the top of the facts, where the block holds the facts at their measure, a gap
and the card — a leaf's page widening for it — and before *Configuration*, after
the rest, where it does not. And a status the about names, ``{error}:``, is drawn
as its sign (decision 5): its cue drawn from the page's shape, its word on its own
tint, on one line and no taller than the sentence it stands in. A table the about
writes, and one a line writes, keeps its words whole in their cells and scrolls
sideways inside what holds it where it is wider (ADR-0018 decision 14), where the
card's and the line's ``anywhere`` would have narrowed every column to a letter. And
the card's details (decision 6) stand beneath its texts, each key on one line and a
long value broken within its cell, so that the table never widens the card.
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
from tests.browser_looks import looks
from tests.browser_server import PageServer

try:  # pragma: no cover - environment probe
    from playwright.sync_api import sync_playwright
except ImportError:  # pragma: no cover
    sync_playwright = None  # type: ignore[assignment]

_SANDBOX_CHROMIUM = Path("/opt/pw-browsers/chromium-1194/chrome-linux/chrome")
_BOOTSTRAP = (Path(__file__).resolve().parent.parent / "var" / "bootstrap"
              / "node_modules" / "bootstrap" / "dist")

#: A desk, a laptop, and a phone as an emulated one: a phone's user agent and touch,
#: which is what makes Chromium lay the page out at the screen's width.
_DESK, _LAPTOP = (1440, 900), (1280, 800)
_PHONE = {
    "viewport": {"width": 390, "height": 844},
    "device_scale_factor": 3,
    "is_mobile": True,
    "has_touch": True,
    "user_agent": ("Mozilla/5.0 (Linux; Android 14; Pixel 8) AppleWebKit/537.36 "
                   "(KHTML, like Gecko) Chrome/140.0.0.0 Mobile Safari/537.36"),
}

_DESCRIPTION = ("Reads the last week's loadtest runs from `loadtest_results`; a run is "
                "red until its analysis is written.")
_ABOUT = ("{error}: open the run on the [loadtest board](https://example.org/), add "
          "its status and a sentence of analysis; the next scan clears the line.")
#: A table wider than a phone and than the card beside *Time*, which its about writes
#: and so does one of its lines.
_TABLE = ("| Who | Where | When | How |\n|---|---|---|---|\n"
          "| the platform team's engineer on call | the operations channel, then the "
          "number on the contact page | at any hour | `ssh -J bastion.example.org "
          "web01.example.org` |")

#: Where the facts' cards and the About card stand, by their headings, and how wide
#: the page is against its screen.
_MEASURED = """() => {
    const box = element => {
        if (!element) { return null; }
        const at = element.getBoundingClientRect();
        return {left: Math.round(at.left), right: Math.round(at.right),
                top: Math.round(at.top + scrollY),
                bottom: Math.round(at.bottom + scrollY),
                width: Math.round(at.width)};
    };
    const cards = Array.from(document.querySelectorAll('.node-facts .card'));
    const named = name => cards.find(card =>
        (card.querySelector('h3') || {}).textContent?.trim() === name);
    const grid = document.querySelector('#status-grid .status-grid, .status-grid');
    return {about: box(named('About')), time: box(named('Time')),
            report: box(named('Report')), config: box(named('Configuration')),
            grid: box(grid),
            over: document.documentElement.scrollWidth - window.innerWidth};
}"""

#: Each table on the page: where it stands, its width against what holds it, whether
#: it scrolls, and the words of its cells that break across two lines — a hyphen's
#: break is a break between words.
_TABLES = """() => Array.from(document.querySelectorAll('.md-body table'), table => {
    const broken = [];
    for (const cell of table.querySelectorAll('th, td')) {
        const walker = document.createTreeWalker(cell, NodeFilter.SHOW_TEXT);
        for (let node = walker.nextNode(); node; node = walker.nextNode()) {
            for (const word of node.textContent.matchAll(/[^\\s-]+/g)) {
                const range = document.createRange();
                range.setStart(node, word.index);
                range.setEnd(node, word.index + word[0].length);
                if (range.getClientRects().length > 1) { broken.push(word[0]); }
            }
        }
    }
    return {where: table.closest('.ls-node-about') ? 'about' : 'line',
            width: table.getBoundingClientRect().width,
            room: table.parentElement.getBoundingClientRect().width,
            scrolls: table.scrollWidth > table.clientWidth, broken,
            over: document.documentElement.scrollWidth - window.innerWidth};
})"""

#: The card's details: each row's key, the lines its key and its value take, the key's
#: tooltip; where the table ends against the room its card gives it, and whether the
#: box it stands in has to scroll it; and how much wider the page is than its screen.
_DETAILS = """() => {
    const box = document.querySelector('.ls-node-about__details');
    const table = box.querySelector('table');
    const body = table.closest('.card-body');
    const lines = element => {
        const range = document.createRange();
        range.selectNodeContents(element);
        return new Set(Array.from(range.getClientRects(),
                                  rect => Math.round(rect.top))).size;
    };
    const rows = Array.from(table.querySelectorAll('tr'), row => ({
        key: row.querySelector('th').textContent.trim(),
        title: row.querySelector('th').getAttribute('title'),
        keyLines: lines(row.querySelector('th')),
        valueLines: lines(row.querySelector('td'))}));
    const room = body.getBoundingClientRect().right
        - parseFloat(getComputedStyle(body).paddingRight);
    return {rows, right: table.getBoundingClientRect().right, room,
            scrolls: box.scrollWidth > box.clientWidth,
            over: document.documentElement.scrollWidth - window.innerWidth};
}"""

#: The sign the card's about opens with: its word, its boxes, the cue's and the shape
#: its cue refers to, its paint, and the line of the sentence it stands in.
_SIGNED = """() => {
    const sign = document.querySelector('.ls-node-about .ls-sign');
    const cue = sign.querySelector('svg');
    const href = cue.querySelector('use').getAttribute('href');
    const sentence = sign.closest('p');
    const style = getComputedStyle(sign);
    const at = sign.getBoundingClientRect();
    const mark = cue.getBoundingClientRect();
    return {word: sign.textContent, boxes: sign.getClientRects().length,
            height: at.height,
            line: parseFloat(getComputedStyle(sentence).lineHeight),
            cue: {width: mark.width, height: mark.height,
                  left: mark.left - at.left},
            shape: document.getElementById(href.slice(1)) !== null,
            background: style.backgroundColor, color: style.color,
            glow: style.textShadow};
}"""


class _Quiet(WSGIRequestHandler):
    def log_message(self, format: str, *args: object) -> None:
        pass


class AboutCardBrowserTests(unittest.TestCase):
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
        tree.upsert("/quality/loadtest", StatusCode.ERROR, "DEVELOP run 2h ago — "
                    "analysis not gradable", description=_DESCRIPTION,
                    report="\n".join(f"- 2026-10-{day} 12:55:13 — **DEVELOP** — INFO"
                                     for day in (15, 17, 20, 22)),
                    config="\n".join(["- **table:** loadtest_results (eu-central-1)",
                                      "- **window:** 7d", "- **timeout:** 3m"]))
        tree.set_about("/quality/loadtest", _ABOUT)
        tree.upsert("/quality/handover", StatusCode.WARN,
                    ["2 runs without an owner", f"Who to call:\n\n{_TABLE}"])
        tree.set_about("/quality/handover", f"Who takes a run over:\n\n{_TABLE}")
        tree.upsert("/system/aws", StatusCode.OK, "1 account in scope",
                    description="Alarms, instances and functions of one AWS account.",
                    config="- **accounts:** live")
        tree.set_about("/system/aws", "Sign in first, then open a line's console link.")
        for aspect in ("ec2", "lambda", "s3"):
            tree.upsert(f"/system/aws/{aspect}", StatusCode.OK, "nothing in scope")
        # details given down from the account, and a function's own, too long for a
        # phone's line (ADR-0133 decision 6)
        tree.set_details("/system/aws", (
            ("on call", "the platform team's engineer"),
            ("login", "[sign in](handbook#sign-in)")))
        tree.upsert("/system/aws/lambda", StatusCode.OK, "nothing in scope",
                    type_details=(("function", "`arn:aws:lambda:eu-central-1:"
                                   "123456789012:function:batch-import-nightly`"),))
        tree.set_about("", "Everything this instance watches.")
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

    def _measure(self, path: str, script: str = _MEASURED, theme: str = "",
                 **context_args: Any) -> dict[str, Any]:
        context = self.browser.new_context(reduced_motion="reduce", **context_args)
        self.addCleanup(context.close)
        if theme:
            context.add_cookies([looks(self.base, theme=theme)])
        page = context.new_page()
        page.route("https://cdn.jsdelivr.net/**", self._vendored)
        page.goto(f"{self.base}/login")
        page.fill("#username", "pan")
        page.fill("#password", "12345678")
        with page.expect_navigation():
            page.click("button[type=submit]")
        page.goto(f"{self.base}/status{path}")
        page.wait_for_selector(".ls-node-about")
        measured: dict[str, Any] = page.evaluate(script)
        return measured

    def _at(self, size: tuple[int, int]) -> dict[str, Any]:
        return {"viewport": {"width": size[0], "height": size[1]}}

    def test_a_leafs_card_stands_beside_time_at_a_desk(self) -> None:
        for size in (_DESK, _LAPTOP):
            with self.subTest(width=size[0]):
                got = self._measure("/quality/loadtest", **self._at(size))
                about, time = got["about"], got["time"]
                # beside the facts, from their top, and reaching down beside them
                self.assertGreater(about["left"], time["right"], got)
                self.assertLessEqual(abs(about["top"] - time["top"]), 1, got)
                self.assertLess(about["top"], got["config"]["top"], got)
                # the facts at their measure, and the card with room for its
                # sentences
                self.assertEqual(time["width"], 820, got)
                self.assertGreaterEqual(about["width"], 288, got)
                self.assertLessEqual(got["over"], 0)

    def test_a_branchs_card_stands_beside_time_after_its_children(self) -> None:
        got = self._measure("/system/aws", **self._at(_DESK))
        about, time = got["about"], got["time"]
        self.assertGreater(about["left"], time["right"], got)
        self.assertLessEqual(abs(about["top"] - time["top"]), 1, got)
        self.assertGreater(about["top"], got["grid"]["bottom"], got)

    def test_where_it_does_not_fit_beside_them_the_facts_keep_their_measure(self):
        # a window the card does not fit beside the facts in: one column, at the
        # facts' measure, the card before Configuration
        got = self._measure("/quality/loadtest", **self._at((1000, 800)))
        about = got["about"]
        self.assertLessEqual(got["time"]["width"], 820, got)
        self.assertEqual(about["width"], got["time"]["width"], got)
        self.assertGreaterEqual(about["top"], got["report"]["bottom"], got)
        self.assertLessEqual(about["bottom"], got["config"]["top"], got)

    def test_on_a_phone_it_stands_before_configuration(self) -> None:
        got = self._measure("/quality/loadtest", **_PHONE)
        about = got["about"]
        # one column: after the report, before the configuration, as wide as both
        self.assertGreaterEqual(about["top"], got["report"]["bottom"], got)
        self.assertLessEqual(about["bottom"], got["config"]["top"], got)
        self.assertEqual(about["left"], got["time"]["left"], got)
        self.assertEqual(about["width"], got["config"]["width"], got)
        self.assertLessEqual(got["over"], 0)

    def test_a_status_the_about_names_is_drawn_as_its_sign(self) -> None:
        # the library's theme, which glows, and the plain one, which does not
        for theme in ("", "plain"):
            with self.subTest(theme=theme or "cyberpunk"):
                got = self._measure("/quality/loadtest", _SIGNED, theme,
                                    **self._at(_DESK))
                self.assertEqual(got["word"], "error", got)
                # one piece, no taller than the sentence it stands in
                self.assertEqual(got["boxes"], 1, got)
                self.assertLessEqual(got["height"], got["line"], got)
                # its cue drawn, from the shape the page holds, before its word
                self.assertTrue(got["shape"], got)
                self.assertGreater(got["cue"]["width"], 0, got)
                self.assertGreater(got["cue"]["height"], 0, got)
                self.assertGreater(got["cue"]["left"], 0, got)
                # on a surface of its own
                self.assertNotIn(got["background"], ("", "rgba(0, 0, 0, 0)",
                                                     "transparent"), got)
                self.assertEqual(got["glow"] != "none", not theme, got)

    def test_a_table_keeps_its_words_whole_and_scrolls_inside_its_room(self) -> None:
        # the card's about and a line, on a phone and in the card beside Time at a
        # desk: a cell breaks between words, so a table wider than its room scrolls
        for name, context in (("phone", _PHONE), ("desk", self._at(_DESK))):
            with self.subTest(name):
                got: Any = self._measure("/quality/handover", _TABLES, **context)
                self.assertEqual(sorted(table["where"] for table in got),
                                 ["about", "line"], got)
                for table in got:
                    self.assertEqual(table["broken"], [], table)
                    self.assertLessEqual(table["width"], table["room"], table)
                    self.assertLessEqual(table["over"], 0, table)
                    # the card is narrower than the table everywhere, a line only
                    # on a phone
                    self.assertEqual(table["scrolls"],
                                     name == "phone" or table["where"] == "about",
                                     table)

    def test_its_details_keep_each_key_on_one_line_and_break_a_long_value(self) -> None:
        for name, context in (("phone", _PHONE), ("desk", self._at(_DESK))):
            with self.subTest(name):
                got = self._measure("/system/aws/lambda", _DETAILS, **context)
                self.assertEqual([(row["key"], row["title"]) for row in got["rows"]],
                                 [("function", None), ("on call", "/system/aws"),
                                  ("login", "/system/aws")], got)
                self.assertTrue(all(row["keyLines"] == 1 for row in got["rows"]), got)
                # the function's name, longer than the card is wide, is broken
                # within its cell, and the table stays inside its card
                self.assertGreater(got["rows"][0]["valueLines"], 1, got)
                self.assertLessEqual(got["right"], got["room"] + 0.5, got)
                self.assertFalse(got["scrolls"], got)
                self.assertLessEqual(got["over"], 0, got)

    def test_the_roots_card_stands_at_the_walls_foot(self) -> None:
        got = self._measure("", **self._at(_DESK))
        # after the wall, a gap between them as between the facts and the cards
        self.assertGreaterEqual(got["about"]["top"] - got["grid"]["bottom"], 16, got)
        self.assertIsNone(got["time"])


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
