"""The walk's facts, each seen marking a page that is broken in its way
(``tests/walk_gui.py``, Mode 6 of ``docs/testing-the-gui.md``).

A walk never fails, so a fact that marks nothing looks exactly like a page with
nothing wrong. Each fact is therefore held here against two pages of the test's own:
one broken in the way the fact is about, which it has to mark, and the same page
sound, which it has to pass. What the walk measures outside the document — the
console, the reports a page sends, how far its layout shifted — is held the same
way, through a step.

A browser file, so a run that collects ``tests/`` leaves it out
(``tests/conftest.py``) and it runs where it is named, skipped wherever Playwright or
a Chromium binary is unavailable. What of the walk needs no browser is
``tests/test_walk_gui.py``, which every run collects.
"""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from typing import Any

from tests.browser_binary import chromium
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
         "<span class='status-card__state'>ok</span>"
         "<span class='node-controls' style='display:inline-flex;gap:3px'>"
         "<span class='node-actions'>"
         "<a class='node-action' style='{action}'>file</a></span>"
         "<span class='node-icons'><a class='node-icon'>x</a></span></span></div>")

#: A head whose name broke onto a second line, its state on that line at the row's
#: end, ``state`` pixels wide: inside the name's box at 100 but clear of its words,
#: over them at 230.
_BROKEN = ("<div class='status-card__head' data-path='/queue' style='display:flex;"
           "width:240px;position:relative;font:16px/24px monospace'>"
           "<a class='status-card__name' style='display:block;width:150px'>"
           "aaaaaaaaaaaaaaa bb</a>"
           "<span class='node-controls' style='display:inline-flex;align-items:center;"
           "align-self:flex-start'>"
           "<span class='node-icons'><a class='node-icon' style='display:inline-block;"
           "width:24px'>x</a></span></span>"
           "<span class='status-card__state' style='position:absolute;right:0;bottom:0;"
           "width:{state}px'>ok</span></div>")

#: A card's head as the pointer looks draw it (ADR-0127 decision 3): the
#: toolbar right after the name and taking no room, so that it lies over what follows
#: — the title, or where ``title`` is empty the state — shown at ``opacity`` 1, and at
#: 0 as the look keeps it until the pointer rests on the head, fading the toolbar as a
#: whole. ``head`` adds a class to the head, ``name`` a style to the name.
_POINTER = ("<div class='status-card__head{head}' data-path='/hosts' "
            "style='display:flex;width:300px;position:relative;"
            "font:16px/24px monospace'>"
            "<a class='status-card__name' style='{name}'>hosts</a>"
            "<span class='node-controls' style='display:inline-flex;width:0;"
            "position:relative;z-index:1;opacity:{opacity}'>"
            "<span class='node-icons' style='display:inline-flex'>"
            "<a class='node-icon' style='display:inline-block;width:24px'>x</a></span>"
            "<span class='node-actions' style='display:inline-flex'>"
            "<a class='node-action' style='display:inline-block;width:40px'>file</a>"
            "</span></span>"
            "<span class='status-head__middle'>{title}</span>"
            "<span class='status-card__state'>ok since 11:59</span></div>")

#: A plot whose line ends at ``x``.
_PLOT = ("<svg class='ls-curve__plot' viewBox='0 0 760 180' width='760' height='180'"
         " aria-label='load'><path class='ls-curve__line' d='M72 100 L{x} 60'/></svg>")


class FactsInChromiumTests(unittest.TestCase):
    playwright: Any = None
    browser: Any = None

    @classmethod
    def setUpClass(cls) -> None:
        if sync_playwright is None:
            raise unittest.SkipTest("playwright is not installed")
        try:
            cls.playwright = sync_playwright().start()
            cls.browser = cls.playwright.chromium.launch(executable_path=chromium())
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

    def _found(self, fact: str, body: str, *, look: str | None = None,
               page: Any = None) -> list[str]:
        """What ``fact`` finds on a page of ``body``, drawn under the look
        `head_buttons` ``look`` where one is given, as the server writes it onto the
        body, and in ``page`` where one is given — another screen's."""
        page = page or self.page
        page.set_content(_PAGE.format(body))
        if look is not None:
            page.evaluate("look => { document.body.dataset.lsHeadButtons = look; }",
                          look)
        found: list[str] = page.evaluate(FACTS[fact][1])
        return found

    def _pointer(self, *, opacity: int = 1, title: str = "the hosts", head: str = "",
                 name: str = "") -> str:
        return _POINTER.format(opacity=opacity, title=title, head=head, name=name)

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
        self.assertEqual(self._found("head-overlap", _HEAD.format(name="", action="")),
                         [])
        found = self._found("head-overlap",
                            _HEAD.format(name="margin-right:-30px", action=""))
        self.assertEqual(len(found), 1)
        self.assertRegex(found[0], r"\A/hosts: \.status-card__name and "
                                   r"\.status-head__middle overlap by \d+×\d+px\Z")

    def test_a_state_beside_a_broken_names_last_line_is_no_overlap(self) -> None:
        # a name is its lines, not its box: the state may stand on its second line
        # beside the words, and is marked only where it lies over them
        self.assertEqual(self._found("head-overlap", _BROKEN.format(state=100)), [])
        found = self._found("head-overlap", _BROKEN.format(state=230))
        self.assertEqual(len(found), 1)
        self.assertRegex(found[0], r"\A/queue: \.status-card__name and "
                                   r"\.status-card__state overlap by \d+×\d+px\Z")

    def test_an_action_lying_over_the_state_is_marked_too(self) -> None:
        # the row's controls are parts of the fact as the name and the title are
        found = self._found("head-overlap",
                            _HEAD.format(name="", action="margin-left:-8px"))
        self.assertEqual(len(found), 1)
        self.assertRegex(found[0], r"\A/hosts: \.status-card__state and "
                                   r"\.node-action overlap by \d+×\d+px\Z")

    def test_a_toolbar_out_of_sight_lies_over_nothing(self) -> None:
        # The pointer looks fade a head's whole toolbar until the pointer rests on
        # it: its parts keep their own opacity, and none of them is seen.
        for title in ("the hosts", ""):
            for look in ("pointer", "pointer-name", "name"):
                self.assertEqual(self._found("head-overlap",
                                             self._pointer(opacity=0, title=title),
                                             look=look), [], (title, look))

    def test_a_shown_toolbar_over_the_title_is_the_pointer_looks_own(self) -> None:
        # Under `pointer` and `pointer-name` the toolbar, shown, lies over the
        # title on purpose; under any other look, or none, that is an overlap.
        for look in ("pointer", "pointer-name"):
            self.assertEqual(self._found("head-overlap", self._pointer(), look=look),
                             [], look)
        for look in ("name", "line", None):
            found = self._found("head-overlap", self._pointer(), look=look)
            self.assertEqual(len(found), 2, look)
            self.assertRegex(found[0], r"\A/hosts: \.node-icons and "
                                       r"\.status-head__middle overlap by \d+×\d+px\Z")
            self.assertRegex(found[1], r"\A/hosts: \.node-action and "
                                       r"\.status-head__middle overlap by \d+×\d+px\Z")
        # a crowded head keeps the toolbar's room, and one being measured reads the
        # row with it in, so an overlap there is one under every look
        for head in (" is-crowded", " is-measuring"):
            self.assertEqual(len(self._found("head-overlap", self._pointer(head=head),
                                             look="pointer")), 2, head)

    def test_a_shown_toolbar_over_the_state_or_the_name_is_marked(self) -> None:
        # what the row has no room for folds behind ⋯ before the state, so a
        # toolbar over it is a fault under the pointer looks as under any other
        found = self._found("head-overlap", self._pointer(title=""), look="pointer")
        self.assertEqual(len(found), 2)
        self.assertRegex(found[0], r"\A/hosts: \.node-icons and "
                                   r"\.status-card__state overlap by \d+×\d+px\Z")
        self.assertRegex(found[1], r"\A/hosts: \.node-action and "
                                   r"\.status-card__state overlap by \d+×\d+px\Z")
        found = self._found("head-overlap",
                            self._pointer(name="margin-right:-30px"), look="pointer")
        self.assertTrue(any(f.startswith("/hosts: .status-card__name and .node-icons ")
                            for f in found), found)
        # and only the toolbar lies over the title: a name over it is marked there too
        found = self._found("head-overlap",
                            self._pointer(opacity=0, name="margin-right:-30px"),
                            look="pointer")
        self.assertEqual(len(found), 1)
        self.assertRegex(found[0], r"\A/hosts: \.status-card__name and "
                                   r"\.status-head__middle overlap by \d+×\d+px\Z")

    def test_on_a_touch_screen_a_toolbar_over_the_title_is_marked(self) -> None:
        # with no pointer to rest on a head, the look keeps the toolbar's room
        context = self.browser.new_context(**PROFILES[-1].context())
        self.addCleanup(context.close)
        found = self._found("head-overlap", self._pointer(), look="pointer",
                            page=context.new_page())
        self.assertEqual(len(found), 2)

    def test_a_box_over_another_in_a_level_is_marked(self) -> None:
        # the wall's cards, and a card's open boxes, one of them standing in the grid
        # through a wrapper drawn without a box of its own (`.tree-solo`)
        level = ("<div class='status-grid' style='display:grid;"
                 "grid-template-columns:200px 200px;grid-auto-rows:20px'>"
                 "<div class='status-card' data-node='/a' style='grid-area:1/1/4/2'>a"
                 "</div><div class='status-card' data-node='/b' "
                 "style='grid-area:{b}'>b</div></div>")
        self.assertEqual(self._found("box-overlap", level.format(b="1/2/3/3")), [])
        found = self._found("box-overlap", level.format(b="2/1/5/2"))
        self.assertEqual(len(found), 1)
        self.assertRegex(found[0], r"\A/a and /b overlap by \d+×\d+px\Z")
        nested = ("<div class='status-card'><div class='node-children' "
                  "style='display:grid;grid-template-columns:150px 150px;"
                  "grid-auto-rows:20px'>"
                  "<div class='tree-node' data-node='/c/x' style='grid-area:1/1/3/2'>x"
                  "</div><div class='tree-solo' style='display:contents'>"
                  "<div class='tree-node' data-node='/c/y' style='grid-area:{y}'>y"
                  "</div></div></div></div>")
        self.assertEqual(self._found("box-overlap", nested.format(y="1/2/2/3")), [])
        self.assertEqual(len(self._found("box-overlap", nested.format(y="2/1/4/2"))), 1)

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
