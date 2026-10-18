"""A pin's write and its editor, held against a real browser (ADR-0104).

Where a page comes back to after a write is the server's to say, and
``tests/test_pin_write.py`` holds it. Whether the line is then *in view* is the
browser's: a fragment, a sticky bar and a page of 80 lines. And where the cursor
stands in an editor that has just opened is nothing a response can show.

And on the wall an editor stands inside what the ten-second refresh swaps, so the
refresh waits for it (decision 7): that a timer holds off, that a stamp changes
at once and that a page dims a minute later are a running page's to show.

Served by a real server to headless Chromium, which scrolls, clicks and types as a
hand does. Skipped wherever Playwright or a Chromium binary is unavailable, so the
ordinary gate does not grow a browser dependency (``docs/testing-the-gui.md``,
Mode 5).
"""
from __future__ import annotations

import re
import threading
import unittest
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, ClassVar
from urllib.parse import parse_qs, urlsplit
from wsgiref.simple_server import WSGIRequestHandler, WSGIServer, make_server

from little_sister import app as app_module
from little_sister.checks import Entry
from little_sister.status import StatusCode
from little_sister.tree import StatusTree
from tests.browser_looks import looks
from tests.browser_server import PageServer

try:  # pragma: no cover - environment probe
    from playwright.sync_api import sync_playwright
except ImportError:  # pragma: no cover
    sync_playwright = None  # type: ignore[assignment]

#: A sandbox pins one browser build; a Playwright from the lock may expect another,
#: so the one that is there is what runs (as ``tests/sweep_contrast.py`` does).
_SANDBOX_CHROMIUM = Path("/opt/pw-browsers/chromium-1194/chrome-linux/chrome")

#: Bootstrap as ``tests/sweep_contrast.py`` vendors it (``docs/testing-the-gui.md``,
#: Mode 4), where there is a copy; the CDN otherwise.
_BOOTSTRAP = (Path(__file__).resolve().parent.parent / "var" / "bootstrap"
              / "node_modules" / "bootstrap" / "dist")

#: A node with more lines than a window holds, each one a line that can be pinned,
#: and the one a test pins: far enough down that the page's top is out of sight.
_LONG = "/ci/audit"
_FINDINGS = {f"finding-{number:03d}": f"finding {number}: a package is behind"
             for number in range(1, 81)}
_FAR = "finding-060"

#: A node pinned whole, with a note worth adding to.
_PINNED = "/ci/actions"
_NOTE = "The runners are being replaced until Sunday evening."

#: And one whose note is longer than its field grows.
_WORDY = "/ci/runbook"
_LONG_NOTE = "\n".join(f"Step {number}: wait for the runner to drain."
                       for number in range(1, 61))

_FOCUS_IN_NOTE = ("document.activeElement !== null"
                  " && document.activeElement.name === 'reason'")

#: The page's editor, cloned into a node's box by ‖, has gone again — a close is
#: the browser's `toggle`, which comes a task after Cancel or Escape.
_NO_CLONE = "document.querySelector('#status-grid details.pin-setter') === null"

#: The wall's refresh, as a request: the page's own address with `fragment=1`.
_FRAGMENT = re.compile(r"[?&]fragment=1")
#: The page's clock where a test holds it: the refresh is a timer's, and a minute
#: of waiting is not a test's to sit through.
_NOON = datetime(2026, 10, 3, 12, 0, 0, tzinfo=UTC)
_PAUSED = ("document.getElementById('status-updated').textContent"
           ".trim().endsWith('paused while editing')")
_SWAPPED = "document.querySelector('#status-grid [data-drawn]') === null"
_HOST_NOTE = "Kernel update and reboot. Back by 23:30."

#: An aspect of `aws`'s shape: lines of its own above a node for each pipeline.
_ASPECT = "/cloud/codepipeline"
_UNREAD = "read/eu-west-1"
_CANNOT = "eu-west-1: pipelines cannot be read: AccessDenied"


def _estate() -> StatusTree:
    tree = StatusTree()
    tree.upsert(_LONG, StatusCode.ERROR, dict(_FINDINGS))
    tree.upsert(_PINNED, StatusCode.ERROR,
                {"web-build": "web build failed on main",
                 "mobile-build": "mobile build is disabled"})
    tree.set_maintenance(_PINNED, _NOTE, set_by="lex",
                         expires_at=datetime.now(UTC) + timedelta(days=2))
    tree.upsert(_WORDY, StatusCode.WARN, "the runbook is being followed")
    tree.set_maintenance(_WORDY, _LONG_NOTE, set_by="lex",
                         expires_at=datetime.now(UTC) + timedelta(days=2))
    return tree


def _wall() -> StatusTree:
    """A wall of three cards: a host pinned whole, a host that is not — with a
    title, so its head is one the inspection card answers to — and a leaf."""
    tree = StatusTree()
    for host in ("gaffsie", "hemulen"):
        for part in ("cpu", "disk", "memory"):
            tree.upsert(f"/{host}/{part}", StatusCode.OK, "within its limits")
    tree.set_title("/hemulen", "The build host")
    tree.upsert("/uplink", StatusCode.WARN, "packet loss of 2 %")
    tree.set_maintenance("/gaffsie", _HOST_NOTE, set_by="lex",
                         expires_at=datetime.now(UTC) + timedelta(days=2))
    return tree


def _aspect() -> StatusTree:
    """A branch with two lines of its own — its scope, `OK`, and a region that cannot
    be read, `WARN` — above a node for each pipeline, one of them failing; titled, so
    its head is one the inspection card answers to."""
    tree = StatusTree()
    tree.upsert(_ASPECT, StatusCode.WARN, [
        Entry("scope", "3 pipelines in scope (eu-central-1)", StatusCode.OK),
        Entry(_UNREAD, _CANNOT, StatusCode.WARN,
              data={"region": "eu-west-1", "error": "AccessDenied"})],
        members=True)
    for name, code in (("build-site", StatusCode.OK),
                       ("deploy-site", StatusCode.ERROR),
                       ("load-fixtures", StatusCode.OK)):
        tree.upsert(f"{_ASPECT}/{name}", code, f"last execution {code.name.lower()}")
    tree.set_title(_ASPECT, "CodePipeline pipelines")
    return tree


class _Quiet(WSGIRequestHandler):
    def log_message(self, format: str, *args: object) -> None:
        pass


class _BrowserCase(unittest.TestCase):
    """A real server and headless Chromium for a class of tests; for each test a
    tree of its own, since every one of them writes pins, and a page signed in as
    an admin."""

    playwright: Any = None
    browser: Any = None
    server: WSGIServer | None = None
    base = ""
    #: What a page is drawn in. No smooth scrolling and no fades: where the page
    #: stands, and what shows, is read once it has loaded.
    drawn_in: ClassVar[dict[str, Any]] = {
        "viewport": {"width": 1000, "height": 700}, "reduced_motion": "reduce"}

    @staticmethod
    def estate() -> StatusTree:
        raise NotImplementedError

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

    def setUp(self) -> None:
        app_module.status_tree = self.estate()
        self.page = self._signed_in(**self.drawn_in)

    def _signed_in(self, **drawn_in: Any) -> Any:
        """A page of a context of its own, past the login."""
        context = self.browser.new_context(**drawn_in)
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
        """Bootstrap from the vendored copy where there is one, the CDN otherwise."""
        name = route.request.url.rsplit("/", 1)[-1]
        for candidate in (_BOOTSTRAP / "css" / name, _BOOTSTRAP / "js" / name):
            if candidate.is_file():
                route.fulfill(path=str(candidate))
                return
        route.continue_()


class PinWriteBrowserTests(_BrowserCase):
    """The way back to a line, and the cursor in a note — in Chromium."""

    estate = staticmethod(_estate)

    # --- the hand ---------------------------------------------------------------------

    def _where(self) -> tuple[str, dict[str, list[str]], str]:
        parts = urlsplit(self.page.url)
        return parts.path, parse_qs(parts.query), parts.fragment

    def _line_in_view(self) -> dict[str, float]:
        """Where the line the page marks stands in the window, with the block that
        states its pin where it has one."""
        self.page.wait_for_selector("#pinned-reason")
        return self.page.evaluate(
            """
            () => {
              const line = document.querySelector('#pinned-reason');
              const stated = line.querySelector(
                  '.rule-block--line:not(.rule-block--new)');
              const bar = document.querySelector('.ls-bar');
              const lowest = (stated ?? line).getBoundingClientRect().bottom;
              return {
                name: line.querySelector('.check-reason__body').textContent.trim(),
                pinned: stated !== null,
                ringed: line.classList.contains('is-focused'),
                top: line.getBoundingClientRect().top,
                bottom: lowest,
                bar: bar.getBoundingClientRect().bottom,
                window: window.innerHeight,
                scrolled: window.scrollY,
              };
            }
            """)

    def assert_back_at_the_line(self, *, pinned: bool) -> None:
        self.assertEqual(self._where(),
                         (f"/status{_LONG}", {"reason": [_FAR]}, "pinned-reason"))
        seen = self._line_in_view()
        self.assertEqual(seen["name"], _FINDINGS[_FAR], seen)
        self.assertEqual(seen["pinned"], pinned, seen)
        self.assertTrue(seen["ringed"], seen)
        # in the window, clear of the bar, the block that states the pin with it
        self.assertGreaterEqual(seen["top"], seen["bar"], seen)
        self.assertLessEqual(seen["bottom"], seen["window"], seen)
        # and it is far down: the page did not simply open at its top
        self.assertGreater(seen["scrolled"], seen["window"], seen)

    # --- B10: a line's write comes back to the line -----------------------------------

    def test_a_line_pinned_far_down_comes_back_in_view(self):
        page = self.page
        page.goto(f"{self.base}/status{_LONG}")
        line = page.locator(".check-reason").filter(
            has=page.locator(".check-reason__body", has_text=_FINDINGS[_FAR]))
        line.scroll_into_view_if_needed()
        self.assertGreater(page.evaluate("window.scrollY"), 700)
        line.locator(".reason-pin > summary").click()
        page.wait_for_function(_FOCUS_IN_NOTE)
        page.keyboard.type("looking at it")
        with page.expect_navigation():
            line.locator(".reason-pin button[type=submit]").click()
        self.assert_back_at_the_line(pinned=True)

        # an edit comes back to it
        block = page.locator("#pinned-reason .rule-block--line")
        block.locator(".rule-block__edit > summary").click()
        page.wait_for_function(_FOCUS_IN_NOTE)
        page.keyboard.type(" Still looking.")
        with page.expect_navigation():
            block.locator("button[type=submit]", has_text="Save changes").click()
        self.assert_back_at_the_line(pinned=True)
        self.assertEqual(
            page.locator("#pinned-reason .rule-block__note").inner_text().strip(),
            "looking at it Still looking.")

        # and so does a clear, to the line as it stands without its pin
        with page.expect_navigation():
            page.locator("#pinned-reason .rule-block__clear button").click()
        self.assert_back_at_the_line(pinned=False)

    # --- the cursor in an opened editor -----------------------------------------------

    def _caret(self) -> list[int]:
        return self.page.evaluate(
            "() => { const note = document.activeElement; return "
            "[note.selectionStart, note.selectionEnd, note.value.length]; }")

    def test_an_opened_editor_starts_at_the_end_of_its_note(self):
        # a note is added to more often than it is begun again
        for url in (f"/status{_PINNED}", "/maintenance"):
            with self.subTest(page=url):
                page = self.page
                page.goto(f"{self.base}{url}")
                page.wait_for_function(
                    "document.documentElement.classList"
                    ".contains('maintenance-edit-enhanced')")
                page.click(".rule-block--node .rule-block__edit > summary")
                # `toggle` is a task of its own: the note takes focus a moment
                # after the click returns
                page.wait_for_function(_FOCUS_IN_NOTE)
                self.assertEqual(self._caret(),
                                 [len(_NOTE), len(_NOTE), len(_NOTE)])
                page.keyboard.type(" Back on Monday.")
                self.assertEqual(
                    page.evaluate("document.activeElement.value"),
                    _NOTE + " Back on Monday.")

    def test_a_note_longer_than_its_field_opens_at_its_end(self):
        # the cursor is at the end, so the end is what the field shows
        page = self.page
        page.goto(f"{self.base}/status{_WORDY}")
        page.click(".rule-block--node .rule-block__edit > summary")
        page.wait_for_function(_FOCUS_IN_NOTE)
        self.assertEqual(self._caret(), [len(_LONG_NOTE)] * 3)
        field = page.evaluate(
            "() => { const note = document.activeElement; return "
            "[note.scrollTop, note.clientHeight, note.scrollHeight]; }")
        self.assertGreater(field[2], field[1], field)       # it does scroll
        self.assertGreaterEqual(field[0] + field[1], field[2] - 1, field)

    def test_a_new_pins_editor_opens_in_its_empty_note(self):
        page = self.page
        page.goto(f"{self.base}/status{_LONG}")
        page.locator(".check-reason .reason-pin > summary").first.click()
        page.wait_for_function(_FOCUS_IN_NOTE)
        self.assertEqual(self._caret(), [0, 0, 0])


class WallEditorBrowserTests(_BrowserCase):
    """An editor in a card or in a branch's head, and the refresh that waits for it
    (ADR-0104 decisions 3 and 7) — in Chromium. On the wall the editor is the page's
    one, which ‖ among a head's icons clones into the node's box (ADR-0127 decision
    3); a branch's head keeps its own."""

    estate = staticmethod(_wall)

    def setUp(self) -> None:
        super().setUp()
        self.fragments = self._count_fragments(self.page)

    # --- the hand ---------------------------------------------------------------------

    @staticmethod
    def _count_fragments(page: Any) -> list[str]:
        """Every request the refresh makes from now on, as it is made."""
        asked: list[str] = []
        page.on("request", lambda request: (
            asked.append(request.url) if _FRAGMENT.search(request.url) else None))
        return asked

    def _wall_at(self, url: str = "/status", *, clock: bool = False) -> None:
        """Open a page that refreshes itself. Where a test is about the refresh the
        page's clock is the test's: installed before the page loads, so the page's
        timers are its own, and stopped, so that only `run_for` moves it."""
        if clock:
            self.page.clock.install(time=_NOON)
        self.page.goto(f"{self.base}{url}")
        self.page.wait_for_function(
            "document.documentElement.classList"
            ".contains('maintenance-edit-enhanced')")
        if clock:
            # short of the first tick, which is ten seconds in
            self.page.clock.pause_at(_NOON + timedelta(seconds=5))

    @staticmethod
    def _card_on(page: Any, name: str) -> Any:
        return page.locator(".status-card").filter(
            has=page.locator(f'.status-card__head[data-path="/{name}"]'))

    def _card(self, name: str) -> Any:
        return self._card_on(self.page, name)

    def _stamp(self) -> str:
        return " ".join(self.page.locator("#status-updated").inner_text().split())

    @staticmethod
    def _mark_of(card: Any) -> Any:
        """‖ among the card's head's icons."""
        return card.locator('.status-card__head [data-control="pin"]')

    def _open(self, name: str) -> Any:
        """Open a card's editor by its ‖; the note takes the cursor."""
        card = self._card(name)
        self._mark_of(card).click()
        self.page.wait_for_function(_FOCUS_IN_NOTE)
        return card

    def _mark_grid(self) -> None:
        """A mark on what the page shows now, which a swap takes with it."""
        self.page.evaluate(
            "document.querySelector('#status-grid .status-card')"
            ".dataset.drawn = 'before'")

    def _grid_kept(self) -> bool:
        return self.page.locator("#status-grid [data-drawn]").count() == 1

    def _opacity(self, element: Any) -> float:
        return float(element.evaluate("element => getComputedStyle(element).opacity"))

    def _dimmed(self) -> bool:
        return "poll-waiting" in (
            self.page.locator("#status-grid").get_attribute("class") or "")

    def _held_tick(self) -> list[Any]:
        """One tick whose request is held on its way; the test lets it go, or
        loses it."""
        held: list[Any] = []
        self.page.route(_FRAGMENT, lambda route: held.append(route))
        self.page.clock.run_for(10_000)
        for _ in range(100):
            if held:
                break
            self.page.wait_for_timeout(20)
        self.assertEqual(len(held), 1)
        return held

    # --- decision 3: the editor opens in the card ------------------------------------

    def test_a_cards_mark_opens_the_pages_editor_in_the_card(self):
        self._wall_at()
        page = self.page
        card = self._card("hemulen")
        closed = card.bounding_box()
        # the page holds one editor of a pin still to be set, in a template outside
        # the grid, and no card carries one until ‖ is clicked (a pinned card's
        # block carries its own, of the pin that stands)
        self.assertEqual(page.locator("template#pin-editor").count(), 1)
        self.assertEqual(page.locator("#status-grid details.pin-setter").count(), 0)
        self._open("hemulen")
        # the cursor stands in this card's note
        self.assertEqual(
            page.evaluate("document.activeElement.closest('.status-card')"
                          ".querySelector('.status-card__head').dataset.path"),
            "/hemulen")
        self.assertEqual(page.locator("#status-grid details.pin-setter").count(), 1)
        opened = card.bounding_box()
        panel = card.locator(".status-panel").bounding_box()
        editor = card.locator(".rule-block--new").bounding_box()
        # the editor stands in the card's panel, where the pin's block will stand —
        # first in it, above the children — which grew to hold it and got no wider
        self.assertGreater(opened["height"], closed["height"] + 150)
        self.assertAlmostEqual(opened["width"], closed["width"], delta=0.5)
        self.assertAlmostEqual(editor["x"], panel["x"], delta=3)
        self.assertAlmostEqual(editor["x"] + editor["width"],
                               panel["x"] + panel["width"], delta=3)
        self.assertAlmostEqual(editor["y"], panel["y"], delta=3)
        self.assertLess(editor["y"] + editor["height"],
                        card.locator(".node-children").bounding_box()["y"])
        # the clone says what the pin covers and whose it is
        self.assertEqual(card.locator(".rule-block__scope").inner_text().strip(),
                         "Maintenance for hemulen and everything beneath it.")
        self.assertEqual(card.locator("input[name=path]").input_value(), "/hemulen")
        self.assertEqual(self._mark_of(card).get_attribute("aria-expanded"), "true")

        page.keyboard.type("New fans, back on Monday.")
        card.locator("input[name=duration]").fill("2h")
        with page.expect_navigation():
            card.locator("button[type=submit]").click()
        # back on the wall, where the card states its pin and has no mark to set one
        self.assertEqual(urlsplit(page.url).path, "/status")
        card = self._card("hemulen")
        self.assertEqual(
            card.locator(".status-panel > .rule-block .rule-block__note")
            .inner_text().strip(),
            "New fans, back on Monday.")
        self.assertEqual(self._mark_of(card).count(), 0)

    def test_a_boxs_mark_opens_the_editor_in_the_box_after_its_row(self):
        # every open head of a node with no pin of its own carries ‖, a box's as
        # well as a card's (ADR-0127 decision 3); one editor at a time
        tree = app_module.status_tree
        tree.upsert("/hemulen/raid/disk1", StatusCode.WARN, "rebuilding")   # a box
        self._wall_at()
        page = self.page
        row = page.locator('.status-node__self[data-path="/hemulen/raid"]')
        mark = row.locator('[data-control="pin"]')
        self.assertEqual(mark.get_attribute("href"), "/status/hemulen/raid")
        mark.click()
        page.wait_for_function(_FOCUS_IN_NOTE)
        box = row.locator("xpath=..")
        clone = box.locator(":scope > details.pin-setter")
        self.assertEqual(clone.count(), 1)
        self.assertTrue(row.evaluate(
            "row => row.nextElementSibling.classList.contains('pin-setter')"))
        self.assertEqual(clone.locator(".rule-block__scope").inner_text().strip(),
                         "Maintenance for raid and everything beneath it.")
        self.assertEqual(clone.locator("input[name=path]").input_value(),
                         "/hemulen/raid")
        # a leaf's says the node alone; and the one editor moves to the mark clicked
        leaf = page.locator('.status-node__self[data-path="/hemulen/raid/disk1"]')
        leaf.locator('[data-control="pin"]').click()
        page.wait_for_function(_FOCUS_IN_NOTE)
        self.assertEqual(page.locator("#status-grid details.pin-setter").count(), 1)
        self.assertEqual(page.locator("#status-grid .rule-block__scope")
                         .inner_text().strip(), "Maintenance for disk1.")
        self.assertEqual(mark.get_attribute("aria-expanded"), "false")

    def test_the_mark_shows_always_and_the_keyboard_walks_to_it(self):
        # the head's icons are shown always, ‖ among them: a wall of marks is what
        # an admin's wall is; the keyboard comes to the toolbar from the card's name
        # and walks to its end
        self._wall_at()
        page = self.page
        card = self._card("hemulen")
        mark = self._mark_of(card)
        page.mouse.move(2, 2)
        self.assertEqual(self._opacity(mark), 1.0)
        # a link in the markup, a control that says it opens the editor once the
        # script has the toolbar
        self.assertEqual(mark.get_attribute("aria-expanded"), "false")
        card.locator(".status-card__name").focus()
        page.keyboard.press("Tab")
        page.keyboard.press("End")
        self.assertTrue(mark.evaluate("mark => mark === document.activeElement"))

    def test_escape_closes_the_editor_and_gives_the_mark_back(self):
        self._wall_at()
        card = self._open("hemulen")
        self.page.keyboard.type("not after all")
        self.page.keyboard.press("Escape")
        self.page.wait_for_function(_NO_CLONE, timeout=3000)
        mark = self._mark_of(card)
        self.assertEqual(card.locator("form.maintenance-editor-form").count(), 0)
        self.assertTrue(mark.is_visible())
        # the cursor is back on what opened it, which says so, and what was typed
        # is gone with the clone: the next ‖ clones the editor afresh
        self.assertTrue(mark.evaluate("mark => mark === document.activeElement"))
        self.assertEqual(mark.get_attribute("aria-expanded"), "false")
        self._open("hemulen")
        self.assertEqual(
            card.locator("textarea[name=reason]").input_value(), "")

    def test_the_mark_ends_the_row_after_the_state(self):
        # ‖ is the last of the head's icons, which end the head's first row, after
        # the state: at a desk and on a phone, with the state in the row and with
        # the standing second line (`card_status_line: below`), where the state
        # alone is beneath
        page = self.page
        for width in (1000, 360):
            for below in (False, True):
                with self.subTest(width=width, below=below):
                    page.set_viewport_size({"width": width, "height": 700})
                    self._wall_at()
                    if below:
                        page.evaluate(
                            "document.body.dataset.lsCardState = 'below'")
                    for name in ("hemulen", "uplink"):
                        seat = self._card(name).evaluate(
                            """
                            card => {
                              const box = name => {
                                const rect = card.querySelector(name)
                                    .getBoundingClientRect();
                                return {left: rect.left, right: rect.right,
                                        top: rect.top, bottom: rect.bottom};
                              };
                              return {head: box('.status-card__head'),
                                      name: box('.status-card__name'),
                                      state: box('.status-card__state'),
                                      icons: box('.node-icons'),
                                      mark: box('[data-control="pin"]')};
                            }
                            """)
                        mark, state, icons = seat["mark"], seat["state"], seat["icons"]
                        # the last icon, on the name's line, inside the head
                        self.assertAlmostEqual(mark["right"], icons["right"], delta=0.5)
                        self.assertLessEqual(mark["right"],
                                             seat["head"]["right"] + 0.5, seat)
                        self.assertLess(mark["top"], seat["name"]["bottom"], seat)
                        self.assertGreater(mark["bottom"], seat["name"]["top"], seat)
                        if below:
                            # the state alone beneath, right-aligned under the icons
                            self.assertGreaterEqual(state["top"], icons["bottom"] - 0.5,
                                                    seat)
                            self.assertAlmostEqual(state["right"], icons["right"],
                                                   delta=1)
                        else:
                            self.assertLessEqual(state["right"], mark["left"], seat)
                            self.assertLess(state["top"], mark["bottom"], seat)

    def test_without_script_the_mark_is_a_link_to_the_nodes_page(self):
        page = self._signed_in(java_script_enabled=False, **self.drawn_in)
        page.goto(f"{self.base}/status")
        card = self._card_on(page, "hemulen")
        mark = self._mark_of(card)
        self.assertEqual(card.locator("form.maintenance-editor-form").count(), 0)
        with page.expect_navigation():
            mark.click()
        # whose head keeps *Set maintenance*, with an editor of its own
        self.assertEqual(urlsplit(page.url).path, "/status/hemulen")
        head = page.locator(".viewed-head")
        form = head.locator("form.maintenance-editor-form")
        self.assertFalse(form.is_visible())
        head.locator("details.rule-setter > summary").click()
        self.assertTrue(form.is_visible())

    def test_a_tap_on_the_mark_opens_the_editor_and_not_the_nodes_card(self):
        # A card's head is where the inspection card answers, on its name, and on
        # a touch screen a first tap inside it opened that card instead of what was
        # tapped — where the card opens on a pause, a viewer's choice.
        page = self._signed_in(has_touch=True, **self.drawn_in)
        page.context.add_cookies([looks(self.base, inspection_card="pause")])
        page.goto(f"{self.base}/status")
        page.wait_for_selector('.status-card__head[data-path="/hemulen"] '
                               '.status-card__name.inspect-trigger')
        card = self._card_on(page, "hemulen")
        self._mark_of(card).tap()
        page.wait_for_function(_FOCUS_IN_NOTE, timeout=3000)
        self.assertTrue(card.locator("form.maintenance-editor-form").is_visible())
        self.assertTrue(page.locator("#inspect-card").is_hidden())

    #: Longer than the inspection card takes to come up, which is two thirds of a
    #: second after the pointer comes to rest on a name.
    _CARD_IS_DUE = 1000

    #: Longer than the moment after a click in which a movement on a name starts no
    #: pause (`inspect.js`), so that what the hand does then is the test's.
    _CLICK_IS_PAST = 700

    def _left_on(self, row: Any, spot: dict[str, float], *,
                 control: bool = False) -> None:
        """The pointer stays where it clicked, as a hand's does that has gone to the
        keyboard, and the browser says what now stands under it: the control it
        clicked has given way, so a `mouseover` goes to the node's own row. A window
        on a screen sends that once the layout has settled, after the note took the
        focus; this one sends it sooner, where the focus moving on would still
        cancel what it started, so the test sends it when a screen would — and the
        `mousemove` of a hand that rests on the mouse beside it."""
        at = [spot["x"] + spot["width"] / 2, spot["y"] + spot["height"] / 2]
        under = row.evaluate(
            """
            (row, at) => {
              const under = document.elementFromPoint(at[0], at[1]);
              const seen = {
                row: row.contains(under),
                control: under.closest(
                    '.maintenance-pip, .pin-setter, .rule-setter, .rule-block,'
                    + ' .node-icons')
                    !== null,
              };
              under.dispatchEvent(new MouseEvent('mouseover', {
                  bubbles: true, clientX: at[0], clientY: at[1]}));
              under.dispatchEvent(new MouseEvent('mousemove', {
                  bubbles: true, clientX: at[0], clientY: at[1]}));
              return seen;
            }
            """, at)
        # on the row, and on no control of the pin's unless said: those the
        # inspection card leaves alone anyway
        self.assertEqual(under, {"row": True, "control": control})

    def test_a_clicked_mark_leaves_no_inspection_card_over_the_wall(self):
        # #89's B12. The pointer that clicked ‖ is left on the card's head — whose
        # name the inspection card answers to — and a hand that goes on to the
        # keyboard may leave it anywhere on the row: the card came up over the card
        # above and stood there while the note was typed. ‖ is a control of the
        # head's own, which asks for no card; the name beside it answers while the
        # editor is open as a head whose pin is being written: not at all.
        self._wall_at()
        page = self.page
        card = self._card("hemulen")
        mark = self._mark_of(card)
        mark.click()
        page.wait_for_function(_FOCUS_IN_NOTE)
        page.wait_for_timeout(self._CLICK_IS_PAST)
        self._left_on(card.locator(".status-card__head"), mark.bounding_box(),
                      control=True)
        spot = card.locator(".status-card__name").bounding_box()
        self._left_on(card.locator(".status-card__head"), spot)
        page.keyboard.type("New fans, back on Monday.")
        page.wait_for_timeout(self._CARD_IS_DUE)
        self.assertTrue(page.locator("#inspect-card").is_hidden())
        self.assertEqual(card.locator("textarea[name=reason]").input_value(),
                         "New fans, back on Monday.")

    def test_nor_does_set_maintenance_in_a_branchs_head(self):
        # the page's head opens the editor it keeps with its own ‖, a control of
        # the row's, which asks for no card — and the page's own head, whose
        # `about` is open in the band, has none; where the card opens on a pause,
        # and in the plain theme's face, where the spot ‖ was is the row's still once
        # the editor stands beneath it
        self.page.context.add_cookies([looks(self.base, inspection_card="pause",
                                             theme="plain")])
        self._wall_at("/status/hemulen")
        page = self.page
        head = page.locator(".viewed-head")
        button = head.locator('.node-icons > [data-control="pin"]')
        spot = button.bounding_box()
        button.click()
        page.wait_for_function(_FOCUS_IN_NOTE)
        page.wait_for_timeout(self._CLICK_IS_PAST)
        self._left_on(head.locator(".status-node__self"), spot, control=True)
        self._left_on(head.locator(".status-node__self"),
                      head.locator(".status-node__name").bounding_box())
        page.keyboard.type("New fans, back on Monday.")
        page.wait_for_timeout(self._CARD_IS_DUE)
        self.assertTrue(page.locator("#inspect-card").is_hidden())

    #: The page's own ‖ says whether the editor its head keeps is open.
    _HEAD_MARK_SAYS = ("document.querySelector('.viewed-head [data-control=\"pin\"]')"
                       ".getAttribute('aria-expanded') === '{}'")

    def test_a_pages_mark_opens_the_editor_its_head_keeps(self):
        # A node's page keeps the editor for the node's pin beneath its head's row:
        # the browser's *Set maintenance* where there is no script (above). With
        # script ‖ opens it, as ‖ opens one on every head, and until then it stands
        # out of sight, so the row's mark is the one control that says it — on a
        # branch's page, and on a leaf's, whose head is the same.
        page = self.page
        for name in ("hemulen", "uplink"):
            with self.subTest(page=name):
                page.goto(f"{self.base}/status/{name}")
                head = page.locator(".viewed-head")
                mark = head.locator('.node-icons > [data-control="pin"]')
                setter = head.locator(":scope > details.rule-setter")
                mark.wait_for(state="visible")
                self.assertTrue(setter.is_hidden())
                self.assertEqual(mark.get_attribute("aria-expanded"), "false")
                mark.click()
                page.wait_for_function(_FOCUS_IN_NOTE)
                self.assertTrue(setter.is_visible())
                self.assertEqual(mark.get_attribute("aria-expanded"), "true")
                # Escape closes it and gives the mark back, which says so
                page.keyboard.press("Escape")
                page.wait_for_function(self._HEAD_MARK_SAYS.format("false"),
                                       timeout=3000)
                self.assertTrue(setter.is_hidden())
                self.assertTrue(
                    mark.evaluate("mark => mark === document.activeElement"))
                # and the mark closes what it opened
                mark.click()
                page.wait_for_function(self._HEAD_MARK_SAYS.format("true"),
                                       timeout=3000)
                mark.click()
                page.wait_for_function(self._HEAD_MARK_SAYS.format("false"),
                                       timeout=3000)
                self.assertTrue(setter.is_hidden())

    def test_a_node_whose_pin_is_being_written_raises_no_inspection_card(self):
        # The editor stands inside the head the inspection card answers to. While
        # it is open the head says nothing else about its node, wherever in it the
        # pointer is; closed, it answers as it did — where the card opens on a pause.
        self.page.context.add_cookies([looks(self.base, inspection_card="pause")])
        app_module.status_tree.set_title("/uplink", "The line out")
        self._wall_at()
        page = self.page
        shown = page.locator("#inspect-card")
        name = self._card("hemulen").locator(".status-card__name")
        name.hover()
        page.wait_for_selector("#inspect-card", state="visible")
        self.assertEqual(shown.inner_text().strip(), "hemulen The build host")
        self._open("hemulen")
        page.wait_for_selector("#inspect-card", state="hidden")
        page.wait_for_timeout(self._CLICK_IS_PAST)
        name.hover()
        page.wait_for_timeout(self._CARD_IS_DUE)
        self.assertTrue(shown.is_hidden())
        # one editor is one node's: another head answers as it did
        self._card("uplink").locator(".status-card__name").hover()
        page.wait_for_selector("#inspect-card", state="visible")
        self.assertEqual(shown.inner_text().strip(), "uplink The line out")
        page.keyboard.press("Escape")
        page.mouse.move(2, 2)
        page.wait_for_selector("#inspect-card", state="hidden")
        name.hover()
        page.wait_for_selector("#inspect-card", state="visible")
        self.assertEqual(shown.inner_text().strip(), "hemulen The build host")

    def test_the_editor_does_not_wear_the_cursor_of_the_nodes_card(self):
        # where a name hints at its card, which opens on a pause, a viewer's choice
        self.page.context.add_cookies([looks(self.base, inspection_card="pause")])
        app_module.status_tree.set_title("/uplink", "The line out")
        self._wall_at()
        page = self.page
        card = self._open("hemulen")
        # nor does the editor wear the cursor of the head it stands under: the
        # row's is the toggle's, and its name, which hints at the card elsewhere,
        # wears the same while the node's pin is being written and it has none
        cursor = "element => getComputedStyle(element).cursor"
        self.assertEqual(card.locator(".status-card__head").evaluate(cursor), "pointer")
        self.assertEqual(card.locator(".status-card__name").evaluate(cursor), "pointer")
        self.assertEqual(self._card("uplink").locator(".status-card__name")
                         .evaluate(cursor), "help")
        self.assertEqual(card.locator(".rule-block--new").evaluate(cursor), "auto")
        # and neither does one in a branch's head, whose row is no toggle
        self._wall_at("/status/hemulen")
        head = page.locator(".viewed-head")
        head.locator('.node-icons > [data-control="pin"]').click()
        page.wait_for_function(_FOCUS_IN_NOTE)
        self.assertEqual(head.locator(".status-node__self").evaluate(cursor), "default")
        self.assertEqual(head.locator(".rule-block--new").evaluate(cursor), "auto")

    #: How many lines the date of a block's expiry stands on, and how many the
    #: sentence that holds it.
    _DATE_LINES = """
        card => {
          const lines = range => new Set(Array.from(
              range.getClientRects(), rect => Math.round(rect.top))).size;
          const said = card.querySelector('.rule-block__what');
          const whole = document.createRange();
          whole.selectNodeContents(said);
          const walker = document.createTreeWalker(said, NodeFilter.SHOW_TEXT);
          for (let node = walker.nextNode(); node; node = walker.nextNode()) {
            const found = /\\d{4}-\\d{2}-\\d{2}/.exec(node.data);
            if (found === null) { continue; }
            const date = document.createRange();
            date.setStart(node, found.index);
            date.setEnd(node, found.index + found[0].length);
            return {date: lines(date), sentence: lines(whole)};
          }
          return {date: 0, sentence: lines(whole)};
        }
    """

    def test_a_cards_sentence_never_ends_a_line_inside_its_date(self):
        # #89's B12: *until 2026-10-*, and the day and the time on the next line.
        # At which width a line ends there is the font's to say, so the card is
        # drawn at every width a card comes in, and narrower.
        self._wall_at()
        card = self._card("gaffsie")
        broken, wrapped = [], []
        for width in range(150, 421, 3):
            card.evaluate(
                "(card, width) => { card.style.width = width + 'px';"
                " card.style.minWidth = '0'; card.style.justifySelf = 'start'; }",
                width)
            seen = card.evaluate(self._DATE_LINES)
            self.assertGreater(seen["date"], 0, width)
            if seen["date"] != 1:
                broken.append(width)
            if seen["sentence"] > 1:
                wrapped.append(width)
        self.assertEqual(broken, [])
        # the sentence did wrap, at most of these widths: the date had its chance
        self.assertGreater(len(wrapped), 40)

    def test_where_nothing_hovers_the_mark_and_the_buttons_show(self):
        page = self._signed_in(viewport={"width": 390, "height": 844},
                               is_mobile=True, has_touch=True,
                               reduced_motion="reduce")
        page.goto(f"{self.base}/status")
        self.assertTrue(page.evaluate("matchMedia('(hover: none)').matches"))
        pinned = self._card_on(page, "gaffsie")
        self.assertEqual(
            [self._opacity(pinned.locator(".rule-block__edit > summary")),
             self._opacity(pinned.locator(".rule-block__clear > button"))],
            [1.0, 1.0])
        card = self._card_on(page, "hemulen")
        mark = self._mark_of(card)
        self.assertEqual(self._opacity(mark), 1.0)
        # and the editor a tap opens is no wider than the phone, with the table of
        # formats open in it too, whose examples have nowhere to break
        mark.tap()
        page.wait_for_function(_FOCUS_IN_NOTE, timeout=3000)
        card.locator(".maintenance-expiry-help > summary").tap()
        card.locator(".maintenance-expiry-help__table").wait_for(state="visible")
        editor = card.locator(".rule-block--new").bounding_box()
        whole = card.bounding_box()
        self.assertLessEqual(editor["x"] + editor["width"],
                             whole["x"] + whole["width"])
        self.assertLessEqual(whole["x"] + whole["width"], 390)
        self.assertLessEqual(
            page.evaluate("document.documentElement.scrollWidth"), 390)
        # and so is the one a branch's head opens, on a phone as narrow as one in
        # use gets: the table would have the editor as wide as itself
        page.set_viewport_size({"width": 360, "height": 800})
        page.goto(f"{self.base}/status/hemulen")
        head = page.locator(".viewed-head")
        head.locator('.node-icons > [data-control="pin"]').tap()
        page.wait_for_function(_FOCUS_IN_NOTE, timeout=3000)
        head.locator(".maintenance-expiry-help > summary").tap()
        head.locator(".maintenance-expiry-help__table").wait_for(state="visible")
        editor = head.locator(".rule-block--new").bounding_box()
        whole = head.bounding_box()
        self.assertLessEqual(editor["x"] + editor["width"],
                             whole["x"] + whole["width"])
        self.assertLessEqual(
            page.evaluate("document.documentElement.scrollWidth"), 360)

    # --- decision 7: the refresh waits ------------------------------------------------

    def test_the_refresh_waits_while_an_editor_is_open(self):
        self._wall_at(clock=True)
        page = self.page
        # one tick, to see the refresh at work: a request, and a grid swapped in
        self._mark_grid()
        page.clock.run_for(10_000)
        page.wait_for_function(_SWAPPED)
        self.assertEqual(len(self.fragments), 1)
        fresh = self._stamp()
        self.assertRegex(fresh, r"^updated \S")
        self.assertNotIn("paused", fresh)

        self._open("hemulen")
        # at once: the clock has not moved, so no tick said it
        page.wait_for_function(_PAUSED, timeout=3000)
        self.assertEqual(self._stamp(), f"{fresh} — paused while editing")
        page.keyboard.type("half a sentence")
        self._mark_grid()
        page.clock.run_for(35_000)
        page.wait_for_timeout(300)          # room for a request that must not come
        self.assertEqual(len(self.fragments), 1)
        self.assertTrue(self._grid_kept())
        self.assertEqual(page.evaluate("document.activeElement.value"),
                         "half a sentence")
        self.assertEqual(self._stamp(), f"{fresh} — paused while editing")

        # Closing it: the stamp drops the words at once, and that is all. A swap
        # would take the cursor from the mark that Escape has just put it back on.
        page.keyboard.press("Escape")
        page.wait_for_function(_NO_CLONE, timeout=3000)
        page.wait_for_function(f"!({_PAUSED})", timeout=3000)
        self.assertEqual(self._stamp(), fresh)
        page.wait_for_timeout(300)          # room for a request that must not come
        self.assertEqual(len(self.fragments), 1)
        self.assertTrue(self._grid_kept())
        self.assertTrue(self._mark_of(self._card("hemulen")).evaluate(
            "mark => mark === document.activeElement"))
        # the next tick brings the page up to date, as every tick did before
        page.clock.run_for(10_000)
        page.wait_for_function(_SWAPPED)
        self.assertEqual(len(self.fragments), 2)
        self.assertNotIn("paused", self._stamp())
        # and an editor opened after that makes the page wait again
        self._open("uplink")
        page.wait_for_function(_PAUSED, timeout=3000)

    def test_an_editor_opened_from_a_nested_boxs_block_makes_the_refresh_wait(self):
        # A pinned branch beneath a card is a box with its block, whose *Edit* opens
        # an editor in the box — the one editor a nested box has today (decision 3),
        # and the refresh waits for it as for a card's (decision 7). Held through the
        # stages of the interactive wall (backlog #91), which narrow the shape the
        # refresh looks for.
        tree = app_module.status_tree
        for disk in ("disk1", "disk2"):
            tree.upsert(f"/hemulen/raid/{disk}", StatusCode.OK, "healthy")
        tree.set_maintenance("/hemulen/raid", "Rebuilding after a swap.", set_by="lex",
                             expires_at=datetime.now(UTC) + timedelta(days=2))
        self._wall_at(clock=True)
        page = self.page
        self._mark_grid()
        page.clock.run_for(10_000)
        page.wait_for_function(_SWAPPED)
        self.assertEqual(len(self.fragments), 1)
        fresh = self._stamp()
        box = page.locator(".status-node").filter(
            has=page.locator('.status-node__self[data-path="/hemulen/raid"]'))
        box.hover()
        box.locator(".rule-block__edit > summary").click()
        page.wait_for_function(_FOCUS_IN_NOTE)
        page.wait_for_function(_PAUSED, timeout=3000)
        page.keyboard.type(" Back on Monday.")
        self._mark_grid()
        page.clock.run_for(35_000)
        page.wait_for_timeout(300)          # room for a request that must not come
        self.assertEqual(len(self.fragments), 1)
        self.assertTrue(self._grid_kept())
        self.assertEqual(page.evaluate("document.activeElement.value"),
                         "Rebuilding after a swap. Back on Monday.")
        self.assertEqual(self._stamp(), f"{fresh} — paused while editing")
        page.keyboard.press("Escape")
        page.wait_for_function(f"!({_PAUSED})", timeout=3000)
        page.clock.run_for(10_000)
        page.wait_for_function(_SWAPPED)
        self.assertEqual(len(self.fragments), 2)

    def test_an_answer_that_was_on_its_way_is_dropped(self):
        # The editor opens between a tick's request and its answer. The grid that
        # answer would replace holds what is being typed.
        self._wall_at(clock=True)
        page = self.page
        held = self._held_tick()
        fresh = self._stamp()
        self._open("hemulen")
        page.keyboard.type("half a sentence")
        self._mark_grid()
        with page.expect_response(_FRAGMENT):
            held[0].continue_()
        page.wait_for_timeout(300)          # room for a swap that must not come
        self.assertTrue(self._grid_kept())
        self.assertEqual(page.evaluate("document.activeElement.value"),
                         "half a sentence")
        self.assertEqual(self._stamp(), f"{fresh} — paused while editing")

    def test_a_miss_that_lands_while_an_editor_is_open_is_said_when_it_closes(self):
        self._wall_at(clock=True)
        page = self.page
        held = self._held_tick()
        fresh = self._stamp()
        self._open("hemulen")
        held[0].abort()
        page.wait_for_timeout(300)          # room for the miss to be counted
        # the stamp says that the page waits, which is what the reader is doing
        self.assertEqual(self._stamp(), f"{fresh} — paused while editing")
        page.keyboard.press("Escape")
        page.wait_for_function(f"!({_PAUSED})", timeout=3000)
        self.assertEqual(
            self._stamp(),
            f"could not refresh — last ok {fresh.removeprefix('updated ')}")
        self.assertIn("text-danger",
                      page.locator("#status-updated").get_attribute("class"))

    def test_an_editor_closed_within_the_minute_leaves_no_dim_behind(self):
        self._wall_at(clock=True)
        page = self.page
        self._open("hemulen")
        page.wait_for_function(_PAUSED, timeout=3000)
        page.clock.run_for(30_000)
        page.keyboard.press("Escape")
        page.wait_for_function(f"!({_PAUSED})", timeout=3000)
        # the minute the page was counting ended with the editor
        page.clock.run_for(45_000)
        page.wait_for_timeout(300)
        self.assertFalse(self._dimmed())

    def test_a_wall_left_with_an_editor_open_dims_after_a_minute(self):
        self._wall_at(clock=True)
        page = self.page
        card = self._open("hemulen")
        page.wait_for_function(_PAUSED, timeout=3000)
        page.clock.run_for(59_000)
        self.assertFalse(self._dimmed())
        self.assertEqual(self._opacity(self._card("gaffsie")), 1.0)
        page.clock.run_for(1_000)
        self.assertTrue(self._dimmed())
        # as a page that lost its server dims — all but the card being typed in
        page.wait_for_function(
            "getComputedStyle(document.querySelector('.strip-band')).opacity"
            " === '0.45'")
        self.assertEqual(self._opacity(self._card("gaffsie")), 0.45)
        self.assertEqual(self._opacity(self._card("uplink")), 0.45)
        self.assertEqual(self._opacity(self._card("hemulen")), 1.0)
        for above in ("#status-grid", "#status-grid > .status-grid"):
            self.assertEqual(self._opacity(page.locator(above)), 1.0, above)

        # closing the editor is the end of it
        self._mark_grid()
        with page.expect_response(_FRAGMENT):
            card.locator(".maintenance-editor-cancel").click()
        page.wait_for_function(_SWAPPED)
        self.assertFalse(self._dimmed())
        page.wait_for_function(
            "getComputedStyle(document.querySelector('.strip-band')).opacity"
            " === '1'")
        self.assertEqual(self._opacity(self._card("gaffsie")), 1.0)

    def test_a_branchs_head_makes_the_refresh_wait_and_stays_lit(self):
        # on a screen wide enough for the editor to fit beside the node's name
        self.page.set_viewport_size({"width": 2200, "height": 900})
        self._wall_at("/status/hemulen", clock=True)
        page = self.page
        head = page.locator(".viewed-head")
        head.locator('.node-icons > [data-control="pin"]').click()
        page.wait_for_function(_FOCUS_IN_NOTE)
        page.wait_for_function(_PAUSED, timeout=3000)
        # the editor is a row of the head's own all the same: under the name, and
        # as wide as the head
        name = head.locator(".status-node__name").bounding_box()
        editor = head.locator(".rule-block--new").bounding_box()
        whole = head.bounding_box()
        self.assertGreaterEqual(editor["y"], name["y"] + name["height"])
        self.assertAlmostEqual(editor["x"], whole["x"], delta=12)
        self.assertAlmostEqual(editor["x"] + editor["width"],
                               whole["x"] + whole["width"], delta=12)
        self._mark_grid()
        page.clock.run_for(60_000)
        page.wait_for_timeout(300)
        self.assertEqual(self.fragments, [])
        self.assertTrue(self._grid_kept())
        # the page dimmed, but for the head somebody is typing in
        self.assertTrue(self._dimmed())
        page.wait_for_function(
            "getComputedStyle(document.querySelector('#status-grid .status-card'))"
            ".opacity === '0.45'")
        self.assertEqual(self._opacity(head), 1.0)
        # the cards dim, not the grid they stand in, nor the frame the grid stands
        # in: that would dim them twice
        self.assertEqual(self._opacity(page.locator("#status-grid .node-frame__box > "
                                                    ".status-grid")), 1.0)
        self.assertEqual(self._opacity(page.locator("#status-grid > .node-frame")), 1.0)
        with page.expect_response(_FRAGMENT):
            page.keyboard.press("Escape")
        page.wait_for_function(_SWAPPED)
        self.assertEqual(len(self.fragments), 1)
        self.assertFalse(self._dimmed())

    def test_a_cards_edit_and_clear_show_on_hover_or_keyboard_focus(self):
        # three cards abreast, each as narrow as a card on a desk gets
        self.page.set_viewport_size({"width": 1160, "height": 700})
        self._wall_at()
        page = self.page
        card = self._card("gaffsie")
        sentence = card.locator(".rule-block__what")
        buttons = (card.locator(".rule-block__edit > summary"),
                   card.locator(".rule-block__clear > button"))

        def shown() -> list[float]:
            return [self._opacity(button) for button in buttons]

        page.mouse.move(2, 2)
        self.assertEqual(shown(), [0.0, 0.0])
        at_rest = sentence.bounding_box()
        sentence.hover()
        self.assertEqual(shown(), [1.0, 1.0])
        # they kept their place while hidden: nothing moves to make room for them
        self.assertEqual(sentence.bounding_box(), at_rest)
        # and that place is beside the sentence, which wraps to leave it
        for button in buttons:
            box = button.bounding_box()
            self.assertLess(box["y"], at_rest["y"] + at_rest["height"])
            self.assertGreaterEqual(box["x"], at_rest["x"] + at_rest["width"])
        page.mouse.move(2, 2)
        self.assertEqual(shown(), [0.0, 0.0])
        # and the keyboard reaches them without a pointer
        buttons[0].focus()
        self.assertEqual(shown(), [1.0, 1.0])

        # a branch's head is one node on its own page: there they show always
        page.goto(f"{self.base}/status/gaffsie")
        page.mouse.move(2, 2)
        head = page.locator(".viewed-head")
        self.assertEqual(
            [self._opacity(head.locator(".rule-block__edit > summary")),
             self._opacity(head.locator(".rule-block__clear > button"))],
            [1.0, 1.0])


class BranchLineBrowserTests(_BrowserCase):
    """A branch's own lines take a pin on its own page (ADR-0036 decision 12): the
    pause mark on a line of its head, the way a write comes back to the line, the
    refresh that waits for the editor, and the inspection card that leaves the mark
    alone — in Chromium."""

    estate = staticmethod(_aspect)

    def _line(self, page: Any, text: str) -> Any:
        return page.locator(".viewed-head .check-reason").filter(
            has=page.locator(".check-reason__body", has_text=text))

    def test_a_lines_pin_set_in_the_head_comes_back_to_the_line(self):
        page = self.page
        page.goto(f"{self.base}/status{_ASPECT}?depth=2")
        line = self._line(page, _CANNOT)
        line.locator(".reason-pin > summary").click()
        page.wait_for_function(_FOCUS_IN_NOTE)
        page.keyboard.type("the role is being granted")
        with page.expect_navigation():
            line.locator(".reason-pin button[type=submit]").click()
        parts = urlsplit(page.url)
        # the page as it was asked for, at the line
        self.assertEqual(
            (parts.path, parse_qs(parts.query), parts.fragment),
            (f"/status{_ASPECT}", {"depth": ["2"], "reason": [_UNREAD]},
             "pinned-reason"))
        page.wait_for_selector("#pinned-reason")
        seen = page.evaluate(
            """
            () => {
              const line = document.querySelector('#pinned-reason');
              const bar = document.querySelector('.ls-bar');
              return {
                head: line.closest('.viewed-head') !== null,
                name: line.querySelector('.check-reason__body').textContent.trim(),
                ringed: line.classList.contains('is-focused'),
                quiet: line.classList.contains('is-quiet'),
                note: line.querySelector('.rule-block__note').textContent.trim(),
                top: line.getBoundingClientRect().top,
                bottom: line.getBoundingClientRect().bottom,
                bar: bar.getBoundingClientRect().bottom,
                window: window.innerHeight,
              };
            }
            """)
        self.assertEqual(
            (seen["head"], seen["name"], seen["ringed"], seen["quiet"], seen["note"]),
            (True, _CANNOT, True, True, "the role is being granted"), seen)
        self.assertGreaterEqual(seen["top"], seen["bar"], seen)
        self.assertLessEqual(seen["bottom"], seen["window"], seen)
        # the node's own part says its other line, and the pipeline beneath it red
        self.assertIn("error", page.locator(
            ".viewed-head > .status-node__self .status-node__state").inner_text())

    def test_a_lines_editor_in_the_head_makes_the_refresh_wait(self):
        page = self.page
        asked: list[str] = []
        page.on("request", lambda request: (
            asked.append(request.url) if _FRAGMENT.search(request.url) else None))
        page.clock.install(time=_NOON)
        page.goto(f"{self.base}/status{_ASPECT}")
        page.wait_for_function(
            "document.documentElement.classList"
            ".contains('maintenance-edit-enhanced')")
        page.clock.pause_at(_NOON + timedelta(seconds=5))
        self._line(page, _CANNOT).locator(".reason-pin > summary").click()
        page.wait_for_function(_FOCUS_IN_NOTE)
        page.wait_for_function(_PAUSED, timeout=3000)
        page.keyboard.type("half a sentence")
        page.evaluate("document.querySelector('#status-grid .status-card')"
                      ".dataset.drawn = 'before'")
        page.clock.run_for(35_000)
        page.wait_for_timeout(300)          # room for a request that must not come
        self.assertEqual(asked, [])
        self.assertEqual(page.locator("#status-grid [data-drawn]").count(), 1)
        self.assertEqual(page.evaluate("document.activeElement.value"),
                         "half a sentence")

    def test_a_tap_on_a_lines_mark_opens_its_editor_and_not_the_nodes_card(self):
        # a first tap on a line's ‖ opens its editor: a touch screen once gave it to
        # the inspection card the head's row answered to, and the page's own head
        # has no card now
        page = self._signed_in(has_touch=True, **self.drawn_in)
        page.goto(f"{self.base}/status{_ASPECT}")
        page.wait_for_function("document.documentElement.classList"
                               ".contains('maintenance-edit-enhanced')")
        line = self._line(page, "3 pipelines in scope")
        line.locator(".reason-pin > summary").tap()
        page.wait_for_function(_FOCUS_IN_NOTE, timeout=3000)
        self.assertTrue(line.locator("form.maintenance-editor-form").is_visible())
        self.assertTrue(page.locator("#inspect-card").is_hidden())
        # its first sentence says what is left alarming, the nodes beneath counted
        self.assertEqual(
            " ".join(line.locator(".rule-block__scope").inner_text().split()),
            "Maintenance for this line only. The other one keeps alarming.")
