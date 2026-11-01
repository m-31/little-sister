"""A pin's write and its editor, held against a real browser (ADR-0104, as ADR-0147
amends it).

Where a page comes back to after a write is the server's to say, and
``tests/test_pin_write.py`` holds it. Whether the line is then *in view* is the
browser's: a fragment, a sticky bar and a page of 80 lines. And where the cursor
stands in an editor that has just opened is nothing a response can show.

A node's page states its pins whole in its head, and so does the card a page draws at
depth 0: each editor stands inside what the ten-second refresh swaps, so the refresh
waits for it (decision 7) — that a timer holds off, that a stamp changes at once and
that a page dims a minute later are a running page's to show. On the wall a block is
the link that opens the drawer at its pin (ADR-0147 decision 7): where its words and
its link stand is held here, the drawer it opens in ``tests/test_drawer_browser.py``.

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
from zoneinfo import ZoneInfo

from little_sister import app as app_module
from little_sister.checks import Entry
from little_sister.schedule import Schedule
from little_sister.status import StatusCode
from little_sister.tree import StatusTree
from tests.browser_binary import chromium
from tests.browser_looks import looks
from tests.browser_server import PageServer

try:  # pragma: no cover - environment probe
    from playwright.sync_api import sync_playwright
except ImportError:  # pragma: no cover
    sync_playwright = None  # type: ignore[assignment]

#: Bootstrap as ``tests/sweep_contrast.py`` vendors it (``docs/testing-the-gui.md``,
#: Mode 4), where there is a copy; the CDN otherwise.
_BOOTSTRAP = (Path(__file__).resolve().parent.parent / "var" / "bootstrap"
              / "node_modules" / "bootstrap" / "dist")

#: A node with more lines than a window holds, each one a member line that can be
#: pinned, and the one a test pins: far enough down that the page's top is out of
#: sight.
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
                  " && document.activeElement.name === 'note'")
_EDITING = ("document.documentElement.classList"
            ".contains('maintenance-edit-enhanced')")

#: The wall's refresh, as a request: the page's own address with `fragment=1`.
_FRAGMENT = re.compile(r"[?&]fragment=1")
#: The page's clock where a test holds it: the refresh is a timer's, and a minute
#: of waiting is not a test's to sit through.
_NOON = datetime(2026, 10, 3, 12, 0, 0, tzinfo=UTC)
#: The page waits, and says so where the wait comes from: an open editor's form shows
#: *updates paused* at its top, the stamp keeping its width (ADR-0147 decision 4).
_PAUSED = ("Array.from(document.querySelectorAll('#status-grid .ls-paused'))"
           ".some(line => line.checkVisibility())")
_SWAPPED = "document.querySelector('#status-grid [data-drawn]') === null"
_HOST_NOTE = "Kernel update and reboot. Back by 23:30."

#: The drawer (ADR-0147 decisions 3 to 5), open with its page whole in its frame,
#: and shut.
_DRAWN = ("(function () { var f = document.querySelector('.ls-drawer__frame');"
          " var d = f && f.contentDocument;"
          " return document.getElementById('ls-drawer').open"
          " && d && d.readyState === 'complete' && d.body"
          " && d.body.hasAttribute('data-ls-panel'); })()")
_SHUT = ("!document.getElementById('ls-drawer').open"
         " && document.querySelector('.ls-drawer__frame') === null")
#: The frame has the focus, and in it a note.
_FOCUS_IN_FRAMED_NOTE = (
    "(function () { var f = document.querySelector('.ls-drawer__frame');"
    " var a = f && f.contentDocument && f.contentDocument.activeElement;"
    " return document.activeElement === f && a && a.name === 'note'; })()")

#: An aspect of `aws`'s shape: lines of its own above a node for each pipeline.
_ASPECT = "/cloud/codepipeline"
_UNREAD = "read/eu-west-1"
_CANNOT = "eu-west-1: pipelines cannot be read: AccessDenied"


def _estate() -> StatusTree:
    tree = StatusTree()
    tree.upsert(_LONG, StatusCode.ERROR, dict(_FINDINGS), members=True)
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


def _held_still(page: Any) -> None:
    """``page`` held still from here on: every request its refresh makes is kept on its
    way and never answered, so that nothing is swapped — as nothing is while an open
    editor pauses the refresh (ADR-0104 decision 7) — and the page's own timers run on,
    as a held clock would not have them do. Routed before the page loads, so that no
    answer is already on its way."""
    page.route(_FRAGMENT, lambda route: None)


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
                executable_path=chromium())
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

    def _details(self, page: Any = None) -> None:
        """*◇ details* on for the page's browser, as the band's switch leaves it in a
        cookie (ADR-0147 decision 6): the wall draws the blocks of what handles a
        part."""
        (page or self.page).context.add_cookies(
            [{"name": "handled_details", "value": "1", "url": self.base}])

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

    def _far_line(self) -> Any:
        return self.page.locator(".check-reason").filter(
            has=self.page.locator(".check-reason__body", has_text=_FINDINGS[_FAR]))

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
        page.wait_for_function(_EDITING)
        line = self._far_line()
        line.scroll_into_view_if_needed()
        self.assertGreater(page.evaluate("window.scrollY"), 700)
        # its ◇ opens the node's Notes tab in the drawer, the form on this line, where
        # a pin is set (ADR-0147 decision 1); a leaf's page loads again once it is
        line.locator(".line-door").click()
        page.wait_for_function(_DRAWN)
        page.wait_for_function(_FOCUS_IN_FRAMED_NOTE, timeout=3000)
        frame = page.frame_locator(".ls-drawer__frame")
        frame.locator(".ack-kind", has_text="Maintenance").click()
        form = frame.locator(".ls-kind-form[data-kind=maintenance]")
        form.locator("textarea[name=note]").fill("looking at it")
        with page.expect_navigation():
            form.locator(".maintenance-editor-form__actions > "
                         "button[type=submit]").click()
        page.wait_for_function(_EDITING)
        entry = app_module.status_tree.entry_maintenance(_LONG, _FAR)
        assert entry is not None
        self.assertEqual(entry.note, "looking at it")
        self.assertEqual(self._far_line().locator(".rule-block--line").count(), 1)

        # an edit in the line's block comes back to the line, in view
        block = self._far_line().locator(".rule-block--line")
        block.scroll_into_view_if_needed()
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
        for url in (f"/status{_PINNED}", "/handled", f"/notes{_PINNED}"):
            with self.subTest(page=url):
                page = self.page
                page.goto(f"{self.base}{url}")
                page.wait_for_function(_EDITING)
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

    def test_a_new_pins_form_opens_in_its_empty_note(self):
        # a line's ◇ opens the tab's form on the line, in the drawer, the cursor in
        # its empty note
        page = self.page
        page.goto(f"{self.base}/status{_LONG}")
        page.wait_for_function(_EDITING)
        page.locator(".check-reason .line-door").first.click()
        page.wait_for_function(_DRAWN)
        page.wait_for_function(_FOCUS_IN_FRAMED_NOTE, timeout=3000)
        self.assertEqual(page.evaluate(
            "(function () { var n = document.querySelector('.ls-drawer__frame')"
            ".contentDocument.activeElement;"
            " return [n.selectionStart, n.selectionEnd, n.value.length]; })()"),
            [0, 0, 0])


class HeadEditorBrowserTests(_BrowserCase):
    """An editor in a node's head, or in the card a page draws at depth 0, and the
    refresh that waits for it (ADR-0104 decisions 3 and 7) — in Chromium. On the wall
    a block is a link and carries none (ADR-0147 decision 7)."""

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

    def _at(self, url: str = "/status/gaffsie", *, clock: bool = False) -> None:
        """Open a page that refreshes itself. Where a test is about the refresh the
        page's clock is the test's: installed before the page loads, so the page's
        timers are its own, and stopped, so that only `run_for` moves it."""
        if clock:
            self.page.clock.install(time=_NOON)
        self.page.goto(f"{self.base}{url}")
        self.page.wait_for_function(_EDITING)
        if clock:
            # short of the first tick, which is ten seconds in
            self.page.clock.pause_at(_NOON + timedelta(seconds=5))

    @staticmethod
    def _card_on(page: Any, name: str) -> Any:
        return page.locator(".status-card").filter(
            has=page.locator(f'.status-card__head[data-path="/{name}"]'))

    def _card(self, name: str) -> Any:
        return self._card_on(self.page, name)

    def _head(self) -> Any:
        return self.page.locator(".viewed-head")

    def _edit(self) -> Any:
        """*Edit* on the pin's block the head states."""
        return self._head().locator(".rule-block--node .rule-block__edit > summary")

    def _open(self) -> None:
        """Open the editor of the pin the head states; the note takes the cursor."""
        self._edit().click()
        self.page.wait_for_function(_FOCUS_IN_NOTE)

    def _stamp(self) -> str:
        return " ".join(self.page.locator("#status-updated").inner_text().split())

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

    # --- decision 7: the refresh waits ------------------------------------------------

    def test_the_refresh_waits_while_an_editor_is_open(self):
        self._at(clock=True)
        page = self.page
        # one tick, to see the refresh at work: a request, and a grid swapped in
        self._mark_grid()
        page.clock.run_for(10_000)
        page.wait_for_function(_SWAPPED)
        self.assertEqual(len(self.fragments), 1)
        fresh = self._stamp()
        self.assertRegex(fresh, r"^updated \S")
        self.assertNotIn("paused", fresh)

        self._open()
        # at once: the clock has not moved, so no tick said it — and said in the
        # editor's own head, the stamp as it was at rest
        page.wait_for_function(_PAUSED, timeout=3000)
        paused = self._head().locator(".rule-block__editor .ls-paused")
        self.assertEqual((paused.is_visible(), paused.inner_text().strip()),
                         (True, "updates paused"))
        self.assertEqual(self._stamp(), fresh)
        page.keyboard.type(" And the fans.")
        self._mark_grid()
        page.clock.run_for(35_000)
        page.wait_for_timeout(300)          # room for a request that must not come
        self.assertEqual(len(self.fragments), 1)
        self.assertTrue(self._grid_kept())
        self.assertEqual(page.evaluate("document.activeElement.value"),
                         _HOST_NOTE + " And the fans.")
        self.assertEqual(self._stamp(), fresh)

        # Closing it: the editor's words go with it at once, and that is all. A swap
        # would take the cursor from *Edit*, which Escape has just put it back on.
        page.keyboard.press("Escape")
        page.wait_for_function(f"!({_PAUSED})", timeout=3000)
        self.assertEqual(self._stamp(), fresh)
        page.wait_for_timeout(300)          # room for a request that must not come
        self.assertEqual(len(self.fragments), 1)
        self.assertTrue(self._grid_kept())
        self.assertTrue(
            self._edit().evaluate("edit => edit === document.activeElement"))
        # the next tick brings the page up to date, as every tick did before
        page.clock.run_for(10_000)
        page.wait_for_function(_SWAPPED)
        self.assertEqual(len(self.fragments), 2)
        self.assertNotIn("paused", self._stamp())
        # and an editor opened after that makes the page wait again
        self._open()
        page.wait_for_function(_PAUSED, timeout=3000)

    def test_an_answer_that_was_on_its_way_is_dropped(self):
        # The editor opens between a tick's request and its answer. The head that
        # answer would replace holds what is being typed.
        self._at(clock=True)
        page = self.page
        held = self._held_tick()
        fresh = self._stamp()
        self._open()
        page.keyboard.type(" Half a sentence")
        self._mark_grid()
        with page.expect_response(_FRAGMENT):
            held[0].continue_()
        page.wait_for_timeout(300)          # room for a swap that must not come
        self.assertTrue(self._grid_kept())
        self.assertEqual(page.evaluate("document.activeElement.value"),
                         _HOST_NOTE + " Half a sentence")
        self.assertEqual(self._stamp(), fresh)

    def test_a_miss_that_lands_while_an_editor_is_open_is_said_when_it_closes(self):
        self._at(clock=True)
        page = self.page
        held = self._held_tick()
        fresh = self._stamp()
        self._open()
        held[0].abort()
        page.wait_for_timeout(300)          # room for the miss to be counted
        # the editor says the page waits, which is what the reader is doing, and the
        # stamp keeps what it said
        page.wait_for_function(_PAUSED, timeout=3000)
        self.assertEqual(self._stamp(), fresh)
        page.keyboard.press("Escape")
        page.wait_for_function(f"!({_PAUSED})", timeout=3000)
        self.assertEqual(
            self._stamp(),
            f"could not refresh — last ok {fresh.removeprefix('updated ')}")
        self.assertIn("text-danger",
                      page.locator("#status-updated").get_attribute("class"))

    def test_an_editor_closed_within_the_minute_leaves_no_dim_behind(self):
        self._at(clock=True)
        page = self.page
        self._open()
        page.wait_for_function(_PAUSED, timeout=3000)
        page.clock.run_for(30_000)
        page.keyboard.press("Escape")
        page.wait_for_function(f"!({_PAUSED})", timeout=3000)
        # the minute the page was counting ended with the editor
        page.clock.run_for(45_000)
        page.wait_for_timeout(300)
        self.assertFalse(self._dimmed())

    def test_a_branchs_head_makes_the_refresh_wait_and_stays_lit(self):
        # on a screen wide enough for the editor to fit beside the node's name
        self.page.set_viewport_size({"width": 2200, "height": 900})
        self._at(clock=True)
        page = self.page
        self._open()
        page.wait_for_function(_PAUSED, timeout=3000)
        # the editor stands in the block, a row of the head's own: under the name,
        # and inside the head
        head = self._head()
        name = head.locator(".status-node__name").bounding_box()
        editor = head.locator(".rule-block__editor").bounding_box()
        whole = head.bounding_box()
        self.assertGreaterEqual(editor["y"], name["y"] + name["height"])
        self.assertGreaterEqual(editor["x"], whole["x"])
        self.assertLessEqual(editor["x"] + editor["width"], whole["x"] + whole["width"])
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

    def test_the_card_at_depth_zero_left_with_an_editor_open_dims_after_a_minute(self):
        # the overview at depth 0 is one card, every node there is, which states a
        # pin on everything whole, as Handled does, and changes it there
        app_module.status_tree.set_maintenance(
            "", "The datacenter moves.", set_by="lex",
            expires_at=datetime.now(UTC) + timedelta(days=2))
        self._at("/status?depth=0", clock=True)
        page = self.page
        card = page.locator(".status-card")
        card.locator(".status-card__name").click()       # open it to its panel
        card.locator(".rule-block__edit > summary").click()
        page.wait_for_function(_FOCUS_IN_NOTE)
        page.wait_for_function(_PAUSED, timeout=3000)
        page.clock.run_for(59_000)
        self.assertFalse(self._dimmed())
        page.clock.run_for(1_000)
        self.assertTrue(self._dimmed())
        # as a page that lost its server dims — all but the card being typed in
        page.wait_for_function(
            "getComputedStyle(document.querySelector('.strip-band')).opacity"
            " === '0.45'")
        self.assertEqual(self._opacity(card), 1.0)
        # closing the editor is the end of it
        self._mark_grid()
        with page.expect_response(_FRAGMENT):
            card.locator(".maintenance-editor-cancel").click()
        page.wait_for_function(_SWAPPED)
        self.assertFalse(self._dimmed())
        page.wait_for_function(
            "getComputedStyle(document.querySelector('.strip-band')).opacity"
            " === '1'")

    def test_a_cards_edit_at_depth_zero_shows_on_hover_or_keyboard_focus(self):
        page = self.page
        self._at("/status/gaffsie?depth=0")
        card = self._card("gaffsie")
        card.locator(".status-card__name").click()       # open it to its panel
        sentence = card.locator(".rule-block__what")
        sentence.wait_for(state="visible")
        edit = card.locator(".rule-block__edit > summary")
        clear = card.locator(".rule-block__clear > button")
        page.mouse.move(2, 2)
        self.assertEqual((self._opacity(edit), self._opacity(clear)), (0.0, 0.0))
        at_rest = sentence.bounding_box()
        sentence.hover()
        self.assertEqual((self._opacity(edit), self._opacity(clear)), (1.0, 1.0))
        # they kept their place while hidden: nothing moves to make room for them
        self.assertEqual(sentence.bounding_box(), at_rest)
        page.mouse.move(2, 2)
        self.assertEqual(self._opacity(edit), 0.0)
        # and the keyboard reaches them without a pointer
        edit.focus()
        self.assertEqual(self._opacity(edit), 1.0)
        # its editor says *Save changes* and *Cancel*; *Clear* is a form of its own
        edit.click()
        editor = card.locator(".rule-block__editor")
        editor.wait_for(state="visible")
        labels = [button.inner_text().strip() for button in
                  editor.locator(".maintenance-editor-form__actions > button").all()]
        self.assertEqual(labels, ["Save changes", "Cancel"])
        page.keyboard.press("Escape")

        # a branch's head is one node on its own page: there they show always
        page.goto(f"{self.base}/status/gaffsie")
        page.mouse.move(2, 2)
        self.assertEqual([self._opacity(self._edit()),
                          self._opacity(self._head().locator(
                              ".rule-block__clear > button"))],
                         [1.0, 1.0])

    def test_the_editor_does_not_wear_the_cursor_of_the_nodes_card(self):
        # a branch's head, whose row is no toggle, keeps its own cursor while the
        # node's pin is being written, and the editor wears none of its row's
        self.page.context.add_cookies([looks(self.base, inspection_card="pause")])
        self._at()
        self._open()
        cursor = "element => getComputedStyle(element).cursor"
        head = self._head()
        self.assertEqual(head.locator(".status-node__self").evaluate(cursor), "default")
        self.assertEqual(head.locator(".rule-block__editor").evaluate(cursor), "auto")

    def test_where_nothing_hovers_the_buttons_show_and_the_editor_fits(self):
        page = self._signed_in(viewport={"width": 390, "height": 844},
                               is_mobile=True, has_touch=True,
                               reduced_motion="reduce")
        page.goto(f"{self.base}/status/gaffsie?depth=0")
        page.wait_for_function(_EDITING)
        self.assertTrue(page.evaluate("matchMedia('(hover: none)').matches"))
        card = self._card_on(page, "gaffsie")
        card.locator(".status-card__name").tap()
        edit = card.locator(".rule-block__edit > summary")
        edit.wait_for(state="visible")
        self.assertEqual((self._opacity(edit),
                          self._opacity(card.locator(".rule-block__clear > button"))),
                         (1.0, 1.0))
        # and the editor a tap opens is no wider than the phone, with the table of
        # formats open in it too, whose examples have nowhere to break
        edit.tap()
        page.wait_for_function(_FOCUS_IN_NOTE, timeout=3000)
        card.locator(".maintenance-expiry-help > summary").tap()
        card.locator(".maintenance-expiry-help__table").wait_for(state="visible")
        editor = card.locator(".rule-block__editor").bounding_box()
        whole = card.bounding_box()
        self.assertLessEqual(editor["x"] + editor["width"],
                             whole["x"] + whole["width"])
        self.assertLessEqual(whole["x"] + whole["width"], 390)
        self.assertLessEqual(
            page.evaluate("document.documentElement.scrollWidth"), 390)
        # and so is the one a branch's head opens, on a phone as narrow as one in
        # use gets: the table would have the editor as wide as itself
        page.set_viewport_size({"width": 360, "height": 800})
        page.goto(f"{self.base}/status/gaffsie")
        head = page.locator(".viewed-head")
        head.locator(".rule-block--node .rule-block__edit > summary").tap()
        page.wait_for_function(_FOCUS_IN_NOTE, timeout=3000)
        head.locator(".maintenance-expiry-help > summary").tap()
        head.locator(".maintenance-expiry-help__table").wait_for(state="visible")
        editor = head.locator(".rule-block__editor").bounding_box()
        whole = head.bounding_box()
        self.assertLessEqual(editor["x"] + editor["width"],
                             whole["x"] + whole["width"])
        self.assertLessEqual(
            page.evaluate("document.documentElement.scrollWidth"), 360)


class WallBlockBrowserTests(_BrowserCase):
    """On the wall, while *◇ details* is on, a block is one link that opens the
    drawer at its pin (ADR-0147 decisions 6 and 7) — in Chromium."""

    estate = staticmethod(_wall)

    def setUp(self) -> None:
        super().setUp()
        self._details()

    def _block_on(self, page: Any, name: str = "gaffsie") -> Any:
        return page.locator(
            f'.status-card:has(> .status-card__head[data-path="/{name}"]) '
            '.status-panel > a.rule-block--door')

    #: How many lines each date a sentence holds stands on, how many the sentence
    #: stands on, and how many of the runs it keeps on one line are wider than it.
    _DATE_LINES = """
        (box, selector) => {
          const lines = range => new Set(Array.from(
              range.getClientRects(), rect => Math.round(rect.top))).size;
          const said = box.querySelector(selector);
          const whole = document.createRange();
          whole.selectNodeContents(said);
          const dates = [];
          const walker = document.createTreeWalker(said, NodeFilter.SHOW_TEXT);
          for (let node = walker.nextNode(); node; node = walker.nextNode()) {
            for (const found of node.data.matchAll(/\\d{4}-\\d{2}-\\d{2}/g)) {
              const date = document.createRange();
              date.setStart(node, found.index);
              date.setEnd(node, found.index + found[0].length);
              dates.push(lines(date));
            }
          }
          const room = said.getBoundingClientRect().width;
          const wider = Array.from(said.querySelectorAll('.text-nowrap')).filter(
              run => run.getBoundingClientRect().width > room + 1).length;
          return {dates: dates, sentence: lines(whole), wider: wider};
        }
    """

    def _planned(self) -> None:
        """A series planned on the build host, its first window tomorrow night, its
        end three months on: its sentence holds two dates, *until* and *next*."""
        zone = ZoneInfo(app_module.config.timezone)
        start = (datetime.now(zone) + timedelta(days=1)).replace(
            hour=22, minute=0, second=0, microsecond=0)
        until = (start + timedelta(days=90)).astimezone(UTC)
        schedule = Schedule.parse(
            f"DTSTART;TZID={zone.key}:{start:%Y%m%dT%H%M%S}\nDURATION:PT8H\n"
            f"RRULE:FREQ=DAILY;UNTIL={until:%Y%m%dT%H%M%SZ}")
        write = app_module.status_tree.set_maintenance(
            "/hemulen", "the nightly reindex", schedule=schedule, set_by="lex")
        assert write.current is not None

    def _measured(self, box: Any, said: str) -> None:
        """``box`` drawn at every width a card comes in, and narrower — some ninety
        widths, two reads each — and its sentence, ``said``, read at each: no date
        it holds stands on two lines, and from 260 pixels, a phone's drawer and
        narrower, nothing it keeps on one line is wider than it. The box is marked
        first, so that one swapped while it was measured fails by name."""
        box.evaluate("box => { box.dataset.drawn = 'before'; }")
        broken, wrapped, wider = [], [], []
        for width in range(150, 421, 3):
            box.evaluate(
                "(box, width) => { box.style.width = width + 'px';"
                " box.style.minWidth = '0'; box.style.justifySelf = 'start'; }",
                width)
            seen = box.evaluate(self._DATE_LINES, said)
            self.assertTrue(seen["dates"], width)
            if any(lines != 1 for lines in seen["dates"]):
                broken.append(width)
            if seen["sentence"] > 1:
                wrapped.append(width)
            if width >= 260 and seen["wider"]:
                wider.append(width)
        self.assertEqual(box.evaluate("box => box.dataset.drawn || ''"), "before",
                         "the box was swapped while it was measured")
        self.assertEqual((broken, wider), ([], []))
        # the sentence did wrap, at most of these widths: the date had its chance
        self.assertGreater(len(wrapped), 40)

    def test_a_block_is_one_link_its_sentence_its_name_a_chevron_at_its_end(self):
        page = self.page
        page.goto(f"{self.base}/status")
        page.wait_for_function(_EDITING)
        block = self._block_on(page)
        said = block.locator(".rule-block__what").inner_text().strip()
        self.assertTrue(said.startswith("In maintenance by lex until"), said)
        # what a screen reader hears is what the block says
        link = page.get_by_role("link", name=re.compile(r"^In maintenance by lex"))
        self.assertEqual(link.count(), 1)
        self.assertTrue(link.evaluate("link => link.classList.contains("
                                      "'rule-block--door')"))
        # the chevron at its right end, on the sentence's line
        chevron = block.locator(".rule-block__chevron").bounding_box()
        whole = block.bounding_box()
        what = block.locator(".rule-block__what").bounding_box()
        self.assertAlmostEqual(chevron["x"] + chevron["width"],
                               whole["x"] + whole["width"], delta=14)
        self.assertGreaterEqual(chevron["x"], what["x"] + what["width"] - 1)
        # no underline, at rest or under the pointer, where it washes instead
        decoration = "link => getComputedStyle(link).textDecorationLine"
        shadow = "link => getComputedStyle(link).boxShadow"
        page.mouse.move(2, 2)
        self.assertEqual(block.evaluate(decoration), "none")
        self.assertEqual(block.evaluate(shadow), "none")
        block.hover()
        self.assertEqual(block.evaluate(decoration), "none")
        self.assertIn("inset", block.evaluate(shadow))
        # and the ring every link takes on the keyboard's focus
        page.mouse.move(2, 2)
        block.focus()
        page.keyboard.press("Shift+Tab")
        page.keyboard.press("Tab")
        self.assertTrue(block.evaluate("link => link === document.activeElement"))
        self.assertEqual(block.evaluate(
            "link => getComputedStyle(link).outlineStyle"), "solid")

    def test_a_click_opens_the_drawer_at_its_pin_its_editor_open(self):
        page = self.page
        page.goto(f"{self.base}/status")
        page.wait_for_function(_EDITING)
        block = self._block_on(page)
        block.click()
        page.wait_for_function(_DRAWN)
        src = page.evaluate("document.querySelector('.ls-drawer__frame').src")
        self.assertIn("/notes/gaffsie?", src)
        self.assertIn("at=maintenance", src)
        self.assertIn("panel=1", src)
        page.wait_for_function(
            "(function () { var f = document.querySelector('.ls-drawer__frame');"
            " var a = f && f.contentDocument.activeElement;"
            " return document.activeElement === f && a && a.name === 'note'"
            " && a.closest('#at') !== null; })()", timeout=3000)
        # the note, the record and *Clear* stand there, as on the node's page
        frame = page.frame_locator(".ls-drawer__frame")
        self.assertEqual(frame.locator("#at .rule-block__note").inner_text().strip(),
                         _HOST_NOTE)
        self.assertEqual(frame.locator("#at .rule-block__clear").count(), 1)
        page.keyboard.press("Escape")
        page.wait_for_function(_SHUT)
        self.assertTrue(self._block_on(page).evaluate(
            "link => link === document.activeElement"))

    def test_without_script_a_block_is_a_link_to_the_tab_at_its_pin(self):
        page = self._signed_in(java_script_enabled=False, **self.drawn_in)
        self._details(page)
        page.goto(f"{self.base}/status")
        with page.expect_navigation():
            self._block_on(page).click()
        parts = urlsplit(page.url)
        self.assertEqual((parts.path, parse_qs(parts.query), parts.fragment),
                         ("/notes/gaffsie", {"at": ["maintenance"]}, "at"))
        # the block it names stands with its editor open
        self.assertTrue(page.locator("#at details.rule-block__edit").evaluate(
            "details => details.open"))

    def test_a_tap_opens_the_drawer_and_not_the_nodes_card(self):
        # where the inspection card opens on a pause, a first tap on a block is the
        # tap on its link
        page = self._signed_in(has_touch=True, **self.drawn_in)
        self._details(page)
        page.context.add_cookies([looks(self.base, inspection_card="pause")])
        page.goto(f"{self.base}/status")
        page.wait_for_function(_EDITING)
        self._block_on(page).tap()
        page.wait_for_function(_DRAWN)
        self.assertTrue(page.locator("#inspect-card").is_hidden())

    def test_a_blocks_sentence_never_ends_a_line_inside_its_date(self):
        # *until 2026-10-*, and the day and the time on the next line: a pin's block
        # on the wall, and a planned window's sentence — its block on the node's tab,
        # where a phone's drawer saw *until 2027-* and *02-01 00:00:00*, and its line
        # in the node's head, *2027-02-* and *01* — and *· next … · in 4h 51m*, kept
        # on one line, wider than the block.
        # At which width a line ends there is the font's to say, so each is drawn at
        # every width a card comes in, and narrower, which on a loaded machine
        # outlasts the ten-second refresh: the page is held still for it, and the box
        # read last is the one the first width was set on. It runs in one process,
        # as every browser file does: on workers it has failed by load alone.
        page = self.page
        _held_still(page)
        page.goto(f"{self.base}/status")
        page.wait_for_function(_EDITING)
        self._measured(page.locator(".status-card").filter(
            has=page.locator('.status-card__head[data-path="/gaffsie"]')),
            ".rule-block__what")
        self._planned()
        page.goto(f"{self.base}/status/hemulen")
        page.wait_for_function(_EDITING)
        self._measured(page.locator(".planned-line").first, ".planned-line__said")
        page.goto(f"{self.base}/notes/hemulen")
        page.wait_for_function(_EDITING)
        self._measured(page.locator(".rule-block--planned").first,
                       ".rule-block__what")


class BranchLineBrowserTests(_BrowserCase):
    """A branch's own lines take a pin on its own page (ADR-0036 decision 12): a
    line's ◇ in its head opening the drawer on it, the way an edit comes back to the
    line, and the refresh that waits for the editor — in Chromium."""

    estate = staticmethod(_aspect)

    def _line(self, page: Any, text: str) -> Any:
        return page.locator(".viewed-head .check-reason").filter(
            has=page.locator(".check-reason__body", has_text=text))

    def _pin_the_unread_region(self) -> None:
        write = app_module.status_tree.set_entry_maintenance(
            _ASPECT, _UNREAD, "the role is being granted",
            expires_at=datetime.now(UTC) + timedelta(days=1), set_by="lex",
            expected_set_at=None)
        assert write.current is not None

    def test_a_lines_pin_edited_in_the_head_comes_back_to_the_line(self):
        self._pin_the_unread_region()
        page = self.page
        page.goto(f"{self.base}/status{_ASPECT}?depth=2")
        page.wait_for_function(_EDITING)
        line = self._line(page, _CANNOT)
        line.locator(".rule-block__edit > summary").click()
        page.wait_for_function(_FOCUS_IN_NOTE)
        page.keyboard.type(" by Friday")
        with page.expect_navigation():
            line.locator("button[type=submit]", has_text="Save changes").click()
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
            (True, _CANNOT, True, True, "the role is being granted by Friday"), seen)
        self.assertGreaterEqual(seen["top"], seen["bar"], seen)
        self.assertLessEqual(seen["bottom"], seen["window"], seen)
        # the node's own part says its other line, and the pipeline beneath it red
        self.assertIn("error", page.locator(
            ".viewed-head > .status-node__self .status-node__state").inner_text())

    def test_a_lines_editor_in_the_head_makes_the_refresh_wait(self):
        self._pin_the_unread_region()
        page = self.page
        asked: list[str] = []
        page.on("request", lambda request: (
            asked.append(request.url) if _FRAGMENT.search(request.url) else None))
        page.clock.install(time=_NOON)
        page.goto(f"{self.base}/status{_ASPECT}")
        page.wait_for_function(_EDITING)
        page.clock.pause_at(_NOON + timedelta(seconds=5))
        self._line(page, _CANNOT).locator(".rule-block__edit > summary").click()
        page.wait_for_function(_FOCUS_IN_NOTE)
        page.wait_for_function(_PAUSED, timeout=3000)
        page.keyboard.type(" half a sentence")
        page.evaluate("document.querySelector('#status-grid .status-card')"
                      ".dataset.drawn = 'before'")
        page.clock.run_for(35_000)
        page.wait_for_timeout(300)          # room for a request that must not come
        self.assertEqual(asked, [])
        self.assertEqual(page.locator("#status-grid [data-drawn]").count(), 1)
        self.assertEqual(page.evaluate("document.activeElement.value"),
                         "the role is being granted half a sentence")

    def test_a_tap_on_a_lines_door_opens_the_drawer_on_it_and_not_the_nodes_card(self):
        # a first tap on a line's ◇ opens the drawer on the line: a touch screen once
        # gave such a tap to the inspection card the head's row answered to, and the
        # page's own head has no card now
        page = self._signed_in(has_touch=True, **self.drawn_in)
        page.goto(f"{self.base}/status{_ASPECT}")
        page.wait_for_function(_EDITING)
        line = self._line(page, "3 pipelines in scope")
        line.locator(".line-door").tap()
        page.wait_for_function(_DRAWN)
        self.assertTrue(page.locator("#inspect-card").is_hidden())
        src = page.evaluate("document.querySelector('.ls-drawer__frame').src")
        self.assertIn("reason=scope", src)
