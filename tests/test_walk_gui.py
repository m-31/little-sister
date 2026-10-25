"""The walk's facts, each seen marking a page that is broken in its way
(``tests/walk_gui.py``, Mode 6 of ``docs/testing-the-gui.md``).

A walk never fails, so a fact that marks nothing looks exactly like a page with
nothing wrong. Each fact is therefore held here against two pages of the test's own:
one broken in the way the fact is about, which it has to mark, and the same page
sound, which it has to pass. What the walk measures outside the document — the
console, the reports a page sends, how far its layout shifted — is held the same
way, through a step.

The part that needs no browser runs in the ordinary gate: what a vendored URL
resolves to, how a report reads, that the gallery leads with what was marked, and
that the walk leaves the demo it ran before the demo's directory goes. The rest is
skipped wherever Playwright or a Chromium binary is unavailable.
"""
from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path
from typing import Any

from tests import walk_gui
from tests.running import subprocess_env
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


#: The walk's demo, started and left as the walk does, in a child interpreter: the
#: application starts once a process and stops once, and this suite's never starts.
_DEMO_CHILD = """
    import json, os, urllib.request
    from tests import walk_gui
    here = os.getcwd()
    with walk_gui.demo() as base:
        ran_in = os.getcwd()
        served = urllib.request.urlopen(base + "/health", timeout=10).status
    try:
        urllib.request.urlopen(base + "/health", timeout=2)
        after = "answered"
    except OSError as error:
        refused = isinstance(getattr(error, "reason", error), ConnectionRefusedError)
        after = "refused" if refused else "unanswered"
    print(json.dumps({"served": served, "after": after,
                      "where": "back" if os.getcwd() == here else os.getcwd(),
                      "directory": "kept" if os.path.exists(ran_in) else "gone"}))
"""


class TheDemoTests(unittest.TestCase):
    def test_the_walk_leaves_the_demo_before_its_directory_goes(self) -> None:
        # The demo runs in a directory of its own, and its instance keeps its state
        # and its lease there: the server stops, then the instance — its one save,
        # its lease let go — and the process goes back where it was, all while the
        # directory is still there. The stop at exit came after the directory had
        # gone, found no lease, and logged that the instance no longer saved.
        directory = self.enterContext(tempfile.TemporaryDirectory())
        environment = subprocess_env()
        # the demo's own configuration roots and log, as a walk has them
        for name in ("LITTLE_SISTER_CONFIG_DIR", "LITTLE_SISTER_ENGINE", "LOG_FILE",
                     "LITTLE_SISTER_DEMO_DIR"):
            environment.pop(name, None)
        environment["PYTHONPATH"] = str(Path(__file__).resolve().parent.parent)
        environment["LOG_LEVEL"] = "INFO"  # the engine's stop says what reached it
        done = subprocess.run([sys.executable, "-c", textwrap.dedent(_DEMO_CHILD)],
                              cwd=directory, env=environment, capture_output=True,
                              text=True, timeout=120)
        self.assertEqual(done.returncode, 0, done.stderr[-3000:])
        self.assertEqual(json.loads(done.stdout.strip().splitlines()[-1]),
                         {"served": 200, "after": "refused", "where": "back",
                          "directory": "gone"})
        self.assertIn("engine: stopped, reached by the walk's end", done.stderr)
        self.assertNotIn("no longer saves", done.stderr)


class _Stopped(Exception):
    """Where the fake browser's page ends a walk: at its first use."""


class TheWalksLooksTests(unittest.TestCase):
    def test_the_walks_browser_chooses_the_card_it_raises(self) -> None:
        # The walk rests on every card head's name, which raises the inspection
        # card; the library's look keeps the card off since 2026-10-18, so the
        # walk's browser chooses it on a pause, as a viewer does in the settings
        # menu, and every other look stays the library's
        cookies: list[dict[str, str]] = []

        class Page:
            def add_init_script(self, _script: str) -> None:
                raise _Stopped

        class Context:
            def add_cookies(self, added: list[dict[str, str]]) -> None:
                cookies.extend(added)

            def new_page(self) -> Page:
                return Page()

        class Browser:
            def new_context(self, **_drawn_in: Any) -> Context:
                return Context()

        base = "http://127.0.0.1:5123"
        out = Path(self.enterContext(tempfile.TemporaryDirectory()))
        with self.assertRaises(_Stopped):
            walk_gui.walk_demo(Browser(), base, out, [])
        self.assertEqual([(cookie["name"], cookie["url"]) for cookie in cookies],
                         [("ls_prefs", base)])
        from little_sister import app as app_module
        from little_sister.looks import LOOKS
        with app_module.app.test_request_context():
            never_chose = app_module._presentation()
        with app_module.app.test_request_context(
                headers={"Cookie": f"ls_prefs={cookies[0]['value']}"}):
            drawn = app_module._presentation()
        self.assertEqual(drawn["inspection_card"], "pause")
        for look in LOOKS:
            if look.key != "inspection_card":
                with self.subTest(look=look.key):
                    self.assertEqual(drawn[look.key], never_chose[look.key])


class AnotherLookTests(unittest.TestCase):
    def test_look_adds_a_look_of_the_settings_menus_to_the_walks_own(self) -> None:
        # `--look boxes=packed` walks the demo packed (ADR-0138), the card still on a
        # pause; a look or a value the menu does not have stops the walk before it
        # starts, naming the looks
        self.assertEqual(walk_gui.chosen_looks(["boxes=packed"]),
                         {**walk_gui.CHOSEN_LOOKS, "boxes": "packed"})
        self.assertEqual(walk_gui.chosen_looks([]), walk_gui.CHOSEN_LOOKS)
        for asked in ("boxes=masonry", "packing=packed", "boxes"):
            with self.subTest(asked=asked), self.assertRaises(SystemExit) as stop:
                walk_gui.chosen_looks([asked])
            self.assertIn("boxes", str(stop.exception))


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
