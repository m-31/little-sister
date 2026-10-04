"""The walk's facts, each seen marking a page that is broken in its way
(``tests/walk_gui.py``, Mode 6 of ``docs/testing-the-gui.md``).

A walk never fails, so a fact that marks nothing looks exactly like a page with
nothing wrong. Each fact is therefore held here against two pages of the test's own:
one broken in the way the fact is about, which it has to mark, and the same page
sound, which it has to pass. What the walk measures outside the document — the
console, the reports a page sends, how far its layout shifted — is held the same
way, through a step.

The part that needs no browser runs in the ordinary gate: what a vendored URL
resolves to, how a report reads, and that the gallery leads with what was marked.
The rest is skipped wherever Playwright or a Chromium binary is unavailable.
"""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from typing import Any

from tests import walk_gui
from tests.walk_gui import FACTS, PROFILES, Step, Walk

try:  # pragma: no cover - environment probe
    from playwright.sync_api import sync_playwright
except ImportError:  # pragma: no cover
    sync_playwright = None  # type: ignore[assignment]

_PAGE = "<!DOCTYPE html><html><body style='margin:0'>{}</body></html>"

#: A card's head as the wall writes it: a name, a title and a state on one line.
_HEAD = ("<div class='status-card__head' data-path='/hosts' style='display:flex;"
         "width:300px;position:relative'>"
         "<a class='status-card__name' style='{name}'>hosts</a>"
         "<span class='status-head__middle' style='flex:1'>the hosts</span>"
         "<span class='status-card__state'>ok</span></div>")

#: A plot whose line ends at ``x``.
_PLOT = ("<svg class='ls-curve__plot' viewBox='0 0 760 180' width='760' height='180'"
         " aria-label='load'><path class='ls-curve__line' d='M72 100 L{x} 60'/></svg>")


class WithoutABrowserTests(unittest.TestCase):
    def test_a_vendored_url_is_the_file_beneath_the_vendored_root(self) -> None:
        with tempfile.TemporaryDirectory() as holder:
            root = Path(holder).resolve() / "node_modules"
            css = root / "bootstrap" / "dist" / "css" / "bootstrap.min.css"
            core = root / "@floating-ui" / "core" / "dist" / "core.umd.min.js"
            for path in (css, core):
                path.parent.mkdir(parents=True)
                path.write_text("")
            (root.parent / "outside.js").write_text("")
            cdn = "https://cdn.jsdelivr.net/npm"
            self.assertEqual(walk_gui.vendored(
                f"{cdn}/bootstrap@5.3.2/dist/css/bootstrap.min.css", root), css)
            self.assertEqual(walk_gui.vendored(
                f"{cdn}/@floating-ui/core@1.6.8/dist/core.umd.min.js", root), core)
            # not vendored, not a CDN URL, and a path that leaves the root
            self.assertIsNone(walk_gui.vendored(
                f"{cdn}/bootstrap@5.3.2/dist/js/missing.js", root))
            self.assertIsNone(walk_gui.vendored(
                "https://example.org/npm/bootstrap@5.3.2/dist/css/bootstrap.min.css",
                root))
            self.assertIsNone(walk_gui.vendored(
                f"{cdn}/bootstrap@5.3.2/../../outside.js", root))

    def test_a_report_reads_as_its_directive_and_what_it_blocked(self) -> None:
        self.assertEqual(
            walk_gui.csp_said(json.dumps({"csp-report": {
                "effective-directive": "img-src", "blocked-uri": "data"}})),
            "img-src blocked data")
        self.assertEqual(walk_gui.csp_said("not json"),
                         "a report that could not be read")

    def test_the_gallery_leads_with_what_was_marked_and_counts_by_fact(self) -> None:
        steps = [
            Step("desk-1440", "wall", "http://x/status"),
            Step("desk-1440", "about", "http://x/about",
                 findings={"page-width": ["the page is 48px wider than its screen"]}),
            Step("phone-390", "about", "http://x/about",
                 findings={"page-width": ["the page is 3px wider than its screen"],
                           "csp": ["img-src blocked data"]})]
        self.assertEqual(walk_gui.facts_counted(steps), {"page-width": 2, "csp": 1})
        page = walk_gui.gallery(steps)
        self.assertIn("3 steps, 2 marked.", page)
        marked, every = page.split("<h2>Every step</h2>")
        self.assertEqual(marked.count("<article"), 2)
        self.assertNotIn("<h3>wall</h3>", marked)
        self.assertEqual(every.count("<article"), 3)
        self.assertIn("48px wider", marked)
        # every fact is named with what it holds a step to, marked or not
        for name in (*FACTS, "layout-shift", "console", "csp"):
            self.assertIn(f"<td>{name}</td>", page)

    def test_what_a_page_says_is_escaped_into_the_gallery(self) -> None:
        page = walk_gui.gallery([Step("desk-1440", "<b>wall</b>", "http://x/?a=1&b=2",
                                      findings={"console": ["<script>x</script>"]})])
        self.assertNotIn("<script>x</script>", page)
        self.assertIn("&lt;b&gt;wall&lt;/b&gt;", page)

    def test_a_walk_with_nothing_marked_says_so(self) -> None:
        self.assertIn("<h2>Marked</h2><p>None.</p>",
                      walk_gui.gallery([Step("desk-1440", "wall", "http://x/")]))


class FactsInChromiumTests(unittest.TestCase):
    playwright: Any = None
    browser: Any = None

    @classmethod
    def setUpClass(cls) -> None:
        if sync_playwright is None:
            raise unittest.SkipTest("playwright is not installed")
        try:
            cls.playwright = sync_playwright().start()
            chromium = walk_gui._SANDBOX_CHROMIUM
            cls.browser = cls.playwright.chromium.launch(
                executable_path=str(chromium) if chromium.is_file() else None)
        except Exception as error:  # pragma: no cover - no browser here
            if cls.playwright is not None:
                cls.playwright.stop()
            raise unittest.SkipTest(f"no chromium available: {error}") from error

    @classmethod
    def tearDownClass(cls) -> None:
        cls.browser.close()
        cls.playwright.stop()

    def setUp(self) -> None:
        self.holder = tempfile.TemporaryDirectory()
        self.addCleanup(self.holder.cleanup)
        context = self.browser.new_context(**PROFILES[1].context())
        self.addCleanup(context.close)
        self.steps: list[Step] = []
        self.walk = Walk(context.new_page(), PROFILES[1], Path(self.holder.name),
                         self.steps)
        self.page = self.walk.page

    def _found(self, fact: str, body: str) -> list[str]:
        self.page.set_content(_PAGE.format(body))
        found: list[str] = self.page.evaluate(FACTS[fact][1])
        return found

    def test_a_page_wider_than_its_screen_is_marked(self) -> None:
        self.assertEqual(self._found("page-width", "<div style='width:900px'>x</div>"),
                         [])
        found = self._found("page-width", "<div style='width:1048px'>x</div>")
        self.assertEqual(found, ["the page is 48px wider than its screen"])

    def test_a_card_raised_past_the_screen_is_marked(self) -> None:
        card = ("<div id='inspect-card' style='position:fixed;width:200px;"
                "height:100px;left:{left}px;top:10px'{hidden}>about</div>")
        self.assertEqual(self._found("popover-on-screen",
                                     card.format(left=700, hidden="")), [])
        self.assertEqual(self._found("popover-on-screen",
                                     card.format(left=850, hidden="")),
                         ["#inspect-card stands 50px past the right"])
        # one that is not raised is nowhere
        self.assertEqual(self._found("popover-on-screen",
                                     card.format(left=850, hidden=" hidden")), [])

    def test_a_name_lying_over_a_title_is_marked(self) -> None:
        self.assertEqual(self._found("head-overlap", _HEAD.format(name="")), [])
        found = self._found("head-overlap",
                            _HEAD.format(name="margin-right:-30px"))
        self.assertEqual(len(found), 1)
        self.assertRegex(found[0], r"\A/hosts: \.status-card__name and "
                                   r"\.status-head__middle overlap by \d+×\d+px\Z")

    def test_a_pause_mark_on_the_states_seat_is_not(self) -> None:
        seated = _HEAD.format(name="").replace(
            "</div>", "<details class='maintenance-editor-disclosure' style='"
                      "position:absolute;right:0;top:0'><summary>pause</summary>"
                      "</details></div>")
        self.assertEqual(self._found("head-overlap", seated), [])

    def test_a_line_that_leaves_its_plot_is_marked(self) -> None:
        self.assertEqual(self._found("curve-in-plot", _PLOT.format(x=744)), [])
        self.assertEqual(self._found("curve-in-plot", _PLOT.format(x=790)),
                         ["load: a .ls-curve__line leaves the plot"])

    def test_a_step_keeps_what_the_browser_said_and_a_screenshot(self) -> None:
        self.page.set_content(_PAGE.format(
            "<script>console.error('broken on purpose')</script>"
            "<div style='width:1048px'>x</div>"))
        step = self.walk.step("a broken page")
        self.assertEqual(step.findings["console"], ["broken on purpose"])
        self.assertIn("page-width", step.findings)
        self.assertTrue(step.marked)
        self.assertTrue((Path(self.holder.name) / step.shot).is_file())
        # what was said belongs to the step it was said in
        self.page.set_content(_PAGE.format("<p>sound</p>"))
        self.assertFalse(self.walk.step("a sound page").marked)

    def test_a_raised_card_that_moves_is_no_shift_of_the_layout(self) -> None:
        # The inspection card is one element, moved from node to node: a browser
        # counts the move, and nothing in the layout made it.
        self.page.route("http://walk.test/", lambda route: route.fulfill(
            content_type="text/html", body=_PAGE.format(
                "<div id='inspect-card' style='position:absolute;left:20px;top:20px;"
                "width:700px;height:380px;background:#ccc'><p>about a node</p></div>"
                "<div id='below' style='height:500px;background:#888'>content</div>")))
        self.page.goto("http://walk.test/")
        self.page.wait_for_timeout(600)
        self.assertFalse(self.walk.step("at rest").marked)
        self.page.evaluate(
            "() => { const card = document.getElementById('inspect-card');"
            " card.style.left = '280px'; card.style.top = '400px'; }")
        self.page.wait_for_timeout(600)
        self.assertNotIn("layout-shift", self.walk.step("the card moved").findings)
        # the same move by anything else is one
        self.page.evaluate(
            "() => { const card = document.getElementById('inspect-card');"
            " card.id = 'something-else'; card.style.left = '20px';"
            " card.style.top = '20px'; }")
        self.page.wait_for_timeout(600)
        self.assertIn("layout-shift",
                      self.walk.step("something else moved").findings)

    def test_a_report_the_page_sends_is_marked(self) -> None:
        # A policy the page breaks, and the browser's own report of it.
        self.page.route("http://walk.test/csp-report",
                        lambda route: route.fulfill(status=204))
        self.page.route("http://walk.test/", lambda route: route.fulfill(
            content_type="text/html",
            headers={"Content-Security-Policy-Report-Only":
                     "img-src 'self'; report-uri /csp-report"},
            body=_PAGE.format(
                "<img src='data:image/gif;base64,R0lGODlhAQABAAAAACw='>")))
        with self.page.expect_request("http://walk.test/csp-report"):
            self.page.goto("http://walk.test/")
        step = self.walk.step("an image the policy does not allow")
        self.assertEqual(step.findings.get("csp"), ["img-src blocked data"])

    def test_a_layout_that_shifts_with_no_input_is_marked(self) -> None:
        # A document that is navigated to: the watch is installed before a page's
        # own scripts, and a document written into an open page has none.
        self.page.route("http://walk.test/", lambda route: route.fulfill(
            content_type="text/html", body=_PAGE.format(
                "<div id='top' style='height:0'></div>"
                "<div style='height:500px;background:#888'>content</div>")))
        self.page.goto("http://walk.test/")
        self.page.wait_for_timeout(600)
        self.assertFalse(self.walk.step("at rest").marked)
        self.page.evaluate(
            "() => { document.getElementById('top').style.height = '300px'; }")
        self.page.wait_for_timeout(600)
        step = self.walk.step("pushed down")
        self.assertIn("layout-shift", step.findings)
        self.assertRegex(step.findings["layout-shift"][0],
                         r"\Athe layout shifted by 0\.\d\d with no input\Z")
