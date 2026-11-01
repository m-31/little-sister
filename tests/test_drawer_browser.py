"""The drawer in a real browser (ADR-0147 decisions 3 to 5): a door opening the node's
*Notes* tab framed over the wall, which waits; its head the box's; at a desk at the
side the box clicked leaves free, on a phone a sheet with the box in the strip above;
a write that goes through closing it and bringing the wall up to date, a refusal
staying in it; the question before a close drops words; the focus into the frame and
back to the door.

What the server draws — the tab's panel mode, the drawer's markup — is
``tests/test_drawer.py``'s. Served by a real server to headless Chromium as
``tests/test_pin_browser.py`` is, whose case this one shares, on the estate of
``tests/test_seen_browser.py``, and skipped where Playwright or a Chromium binary is
unavailable (``docs/testing-the-gui.md``, Mode 5).
"""
from __future__ import annotations

import re
from datetime import UTC, datetime, timedelta
from typing import Any, ClassVar
from urllib.parse import parse_qs, urlsplit

from little_sister import app as app_module
from little_sister import slots
from little_sister.pins import SEEN
from tests.demo_extension import TRACKER, draft_issue
from tests.test_pin_browser import _BrowserCase
from tests.test_seen_browser import _wall

_READY = ("document.documentElement.classList"
          ".contains('maintenance-edit-enhanced')")
_FRAGMENT = re.compile(r"[?&]fragment=1")
#: The pause, said where its cause is (decision 4, on Lex's word of 2026-10-30): the
#: drawer's head says *updates paused* under the node's name while the page waits for
#: it, an editor open in the grid at the top of its form; the stamp keeps its width.
_PAUSED = "document.querySelector('.ls-drawer__paused').checkVisibility()"
_EDITING = ("Array.from(document.querySelectorAll('#status-grid .ls-paused'))"
            ".some(line => line.checkVisibility())")
#: Every frame the head's editor stands open in, from before the click that opens it:
#: whether its *updates paused* shows, and where the record beneath it stands.
_FRAMES = """() => {
    window.__frames = [];
    const form = document.querySelector(
        '.viewed-head .rule-block--node form.maintenance-editor-form');
    const record = form.querySelector('.rule-block__record');
    const line = form.querySelector('.ls-paused');
    let left = 90;
    requestAnimationFrame(function frame() {
        if (form.closest('details').open) {
            window.__frames.push([line.checkVisibility(),
                                  record.getBoundingClientRect().top + window.scrollY]);
        }
        if (--left > 0) { requestAnimationFrame(frame); }
    });
}"""
#: Where the wall stands in the page, whatever the page's scroll.
_WALL_TOP = ("document.getElementById('status-grid').getBoundingClientRect().top"
             " + window.scrollY")
_OPEN = "document.getElementById('ls-drawer').open"
_SHUT = ("!document.getElementById('ls-drawer').open"
         " && document.querySelector('.ls-drawer__frame') === null")
_ASKING = "!document.querySelector('.ls-drawer__ask').hidden"
#: The drawer's frame holds its page, the panel, whole.
_LOADED = ("(function () { var f = document.querySelector('.ls-drawer__frame');"
           " var d = f && f.contentDocument;"
           " return d && d.readyState === 'complete' && d.body"
           " && d.body.hasAttribute('data-ls-panel'); })()")


class DrawerBrowserTests(_BrowserCase):
    """The drawer — in Chromium."""

    estate = staticmethod(_wall)
    drawn_in: ClassVar[dict[str, Any]] = {
        "viewport": {"width": 1300, "height": 800}, "reduced_motion": "reduce"}

    def setUp(self) -> None:
        super().setUp()
        app_module.status_tree.on_pin_end(app_module.notes_book.pin_ended)
        self.fragments: list[str] = []
        self.page.on("request", lambda request: (
            self.fragments.append(request.url) if _FRAGMENT.search(request.url)
            else None))

    # --- the hand -------------------------------------------------------------------

    def _at(self, url: str = "/status") -> None:
        self.page.goto(f"{self.base}{url}")
        self.page.wait_for_function(_READY)

    def _card(self, name: str) -> Any:
        return self.page.locator(".status-card").filter(
            has=self.page.locator(f'.status-card__head[data-path="/{name}"]'))

    def _door_of(self, name: str) -> Any:
        return self._card(name).locator(
            '.status-card__head .node-icons [data-control="door"]')

    def _open(self, door: Any) -> Any:
        """Click ``door`` and wait for the drawer's frame: its page, the panel."""
        door.click()
        self.page.wait_for_function(_OPEN)
        self.page.wait_for_function(_LOADED)
        return self.page.frame_locator(".ls-drawer__frame")

    def _focused_in_frame(self) -> dict[str, str] | None:
        return self.page.evaluate(
            "(function () { var f = document.querySelector('.ls-drawer__frame');"
            " if (!f || document.activeElement !== f) { return null; }"
            " var a = f.contentDocument.activeElement;"
            " return {tag: a.tagName.toLowerCase(), name: a.getAttribute('name') || '',"
            " id: a.id || '', cls: a.className || ''}; })()")

    def _box(self, selector: str) -> dict[str, float]:
        box = self.page.locator(selector).bounding_box()
        assert box is not None, selector
        return box

    # --- opening and closing --------------------------------------------------------

    def test_a_heads_door_opens_the_tab_over_the_wall_which_waits(self):
        page = self.page
        self._at()
        stamp = page.locator("#status-updated").bounding_box()
        assert stamp is not None
        wall = page.evaluate(_WALL_TOP)
        door = self._door_of("uplink")
        frame = self._open(door)
        src = page.evaluate("document.querySelector('.ls-drawer__frame').src")
        self.assertTrue(src.endswith("/notes/uplink?panel=1"), src)
        # the panel: the tab without the site's bar, rail and band
        self.assertEqual(frame.locator(".ls-bar").count(), 0)
        self.assertEqual(frame.locator(".ls-band").count(), 0)
        self.assertEqual(frame.locator(".ls-tab__form").count(), 1)
        # the head is the box's: its name, its state, and where its page and tab are
        title = page.locator(".ls-drawer__title").inner_text()
        self.assertIn("uplink", title)
        self.assertIn("warn", title)
        self.assertTrue(page.locator('.ls-drawer__to[data-to="page"]')
                        .get_attribute("href").endswith("/status/uplink"))
        self.assertTrue(page.locator('.ls-drawer__to[data-to="tab"]')
                        .get_attribute("href").endswith("/notes/uplink"))
        # the wall waits, and the drawer says so under the node's name, muted; the
        # stamp says what it says at rest, its width kept
        page.wait_for_function(_PAUSED, timeout=3000)
        paused = page.locator(".ls-drawer__paused")
        self.assertEqual(paused.inner_text().strip(), "updates paused")
        name = page.locator(".ls-drawer__title").bounding_box()
        under = paused.bounding_box()
        assert name is not None and under is not None
        self.assertGreaterEqual(under["y"], name["y"] + name["height"] - 1)
        self.assertAlmostEqual(under["x"], name["x"], delta=1)
        self.assertNotIn("paused", page.locator("#status-updated").inner_text())
        self.assertEqual(page.locator("#status-updated").bounding_box()["width"],
                         stamp["width"])
        # so nothing on the wall moves as it opens: at this width the stamp's words
        # once wrapped the band, and the wall dropped beneath the shade
        self.assertEqual(page.evaluate(_WALL_TOP), wall)
        before = list(self.fragments)
        page.evaluate("document.dispatchEvent(new Event('visibilitychange'))")
        page.wait_for_timeout(300)          # room for a request that must not come
        self.assertEqual(self.fragments, before)
        # ✕ closes it: the frame goes, the focus is back on the door
        page.locator(".ls-drawer__close").click()
        page.wait_for_function(_SHUT)
        self.assertTrue(door.evaluate("el => el === document.activeElement"))
        page.wait_for_function(f"!({_PAUSED})", timeout=3000)

    def test_the_drawer_and_an_editor_each_say_the_pause_in_their_own_head(self):
        # the pause is said where its cause is: an editor open in the grid at the top
        # of its form, the drawer opened over it under the node's name, each while it
        # holds the page — the editor's words staying as the drawer closes over it
        page = self.page
        app_module.status_tree.set_maintenance(
            "/hemulen", "new disks", set_by="lex",
            expires_at=datetime.now(UTC) + timedelta(days=1))
        self._at("/status/hemulen")
        page.evaluate(_FRAMES)
        page.locator(".viewed-head .rule-block--node "
                     ".rule-block__edit > summary").click()
        page.wait_for_function(_EDITING, timeout=3000)
        self.assertNotIn("paused", page.locator("#status-updated").inner_text())
        # the line comes in the frame the editor opens in, and nothing in the editor
        # moves after it: shown from the editor's `toggle`, it came a frame late and
        # pushed the form down
        page.wait_for_function("() => window.__frames.length >= 3")
        frames = page.evaluate("window.__frames")
        self.assertTrue(all(shown for shown, _ in frames), frames)
        self.assertEqual(len({top for _, top in frames}), 1, frames)
        door = page.locator('.status-card__head[data-path="/hemulen/disk"] '
                            '[data-control="door"]').first
        self._open(door)
        page.wait_for_function(f"({_PAUSED}) && ({_EDITING})", timeout=3000)
        page.keyboard.press("Escape")
        page.wait_for_function(_SHUT)
        page.wait_for_function(f"!({_PAUSED}) && ({_EDITING})", timeout=3000)
        # and the editor's close goes on with the page
        page.locator(".viewed-head .maintenance-editor-cancel").click()
        page.wait_for_function(f"!({_EDITING}) && !({_PAUSED})", timeout=3000)

    def test_at_a_desk_it_stands_at_the_side_the_box_clicked_leaves_free(self):
        page = self.page
        self._at()
        sides = {}
        for name in ("ci", "gaffsie", "hemulen", "uplink"):
            self._open(self._door_of(name))
            panel = self._box(".ls-drawer__panel")
            self.assertAlmostEqual(panel["width"], 480, delta=1)
            card = self._card(name).bounding_box()
            assert card is not None
            # the box is in sight beside the drawer, wherever it stands
            under = (min(card["x"] + card["width"], panel["x"] + panel["width"])
                     - max(card["x"], panel["x"]))
            self.assertLessEqual(under, 0, name)
            sides[name] = "left" if panel["x"] < 1 else "right"
            page.keyboard.press("Escape")
            page.wait_for_function(_SHUT)
        # at the right where it can, at the left where the box would sit under it
        self.assertEqual(sides, {"ci": "right", "gaffsie": "left", "hemulen": "left",
                                 "uplink": "right"})

    def test_a_line_wider_than_the_room_keeps_where_it_begins_in_sight(self):
        page = self.page
        self._at("/status/ci/build")
        door = page.locator(".check-reason .line-door").first
        self._open(door)
        panel = self._box(".ls-drawer__panel")
        line = door.locator("xpath=ancestor::div[contains(@class, 'check-reason')][1]")
        box = line.bounding_box()
        assert box is not None
        # it would sit under the drawer at either side, at the left where it begins
        self.assertLess(box["x"], 480)
        self.assertGreater(box["x"] + box["width"], 1300 - 480)
        # at the right: the line's words are in sight, where it begins
        self.assertAlmostEqual(panel["x"] + panel["width"], 1300, delta=1)
        self.assertLess(box["x"], panel["x"])

    def test_a_lit_door_stands_in_the_state_and_stays_put_under_the_pointer(self):
        # under the library's look the toolbar shows only under the pointer: a lit ◇
        # stands at the start of the state, at rest and under the pointer, and the
        # toolbar carries none; a plain one comes with the toolbar (decision 1)
        page = self.page
        write = app_module.status_tree.set_acknowledgment(
            "/hemulen/disk", "", SEEN, "known", expires_at=None, set_by="ada")
        assert write.current is not None, write.problem
        self._at()
        head = page.locator('.status-card__head[data-path="/hemulen"]')
        door = head.locator(".status-card__state > .state-door")
        self.assertTrue(door.is_visible())
        self.assertEqual(door.inner_text().strip(), "1")
        at_rest = door.bounding_box()
        head.locator(".status-card__name").hover()
        page.wait_for_timeout(100)
        self.assertEqual(door.bounding_box(), at_rest)
        self.assertEqual(head.locator('.node-icons [data-control="door"]').count(), 0)
        self.assertTrue(head.locator('.node-icons [data-control="page"]').is_visible())
        plain = self._card("uplink").locator(
            '.status-card__head .node-icons [data-control="door"]')
        self.assertEqual(plain.count(), 1)
        self.assertFalse(plain.evaluate("el => el.classList.contains('is-lit')"))
        # and it opens the drawer, as every door does
        self._open(door)
        page.keyboard.press("Escape")
        page.wait_for_function(_SHUT)
        self.assertTrue(door.evaluate("el => el === document.activeElement"))

    def test_the_box_clicked_is_lit_in_the_shade(self):
        page = self.page
        self._at()
        self._open(self._door_of("uplink"))
        lit = self._box(".ls-drawer__lit")
        card = self._card("uplink").bounding_box()
        assert card is not None
        for edge in ("x", "y", "width", "height"):
            self.assertAlmostEqual(lit[edge], card[edge], delta=1, msg=edge)
        # a click on the wall closes it, where nothing was written
        page.mouse.click(lit["x"] + 5, lit["y"] + 5)
        page.wait_for_function(_SHUT)

    def test_on_a_phone_a_sheet_and_the_box_in_the_strip_above_it(self):
        page = self.page
        page.set_viewport_size({"width": 390, "height": 800})
        self._at()
        door = self._door_of("ci")
        door.scroll_into_view_if_needed()
        page.evaluate("window.scrollTo(0, document.documentElement.scrollHeight)")
        self._open(door)
        panel = self._box(".ls-drawer__panel")
        self.assertAlmostEqual(panel["width"], 390, delta=1)
        self.assertAlmostEqual(panel["y"] + panel["height"], 800, delta=1)
        self.assertGreater(panel["y"], 100)
        lit = self._box(".ls-drawer__lit")
        self.assertGreaterEqual(lit["y"], 0)
        self.assertLessEqual(lit["y"] + lit["height"], panel["y"] + 1)
        # a tap on the strip closes it
        page.mouse.click(195, max(5, lit["y"] - 5) if lit["y"] > 10 else lit["y"] + 5)
        page.wait_for_function(_SHUT)

    # --- writing --------------------------------------------------------------------

    def test_a_write_that_goes_through_closes_it_and_brings_the_wall_up_to_date(self):
        page = self.page
        self._at()
        door = self._door_of("uplink")
        frame = self._open(door)
        form = frame.locator(".ls-kind-form[data-kind=seen]")
        frame.locator(".ack-kind", has_text="Seen").click()
        form.locator("textarea[name=note]").fill("the provider knows")
        before = len(self.fragments)
        form.locator("button[type=submit]").click()
        page.wait_for_function(_SHUT, timeout=5000)
        pin = app_module.status_tree.acknowledgment("/uplink", "")
        assert pin is not None
        self.assertEqual((pin.kind, pin.note), (SEEN, "the provider knows"))
        # brought up to date at once, not at the next tick
        page.wait_for_function(
            "document.querySelector("
            "'.status-card__head[data-path=\"/uplink\"] .head-ack') !== null",
            timeout=3000)
        self.assertGreater(len(self.fragments), before)
        page.wait_for_function(
            "document.activeElement !== null && document.activeElement.matches"
            "('.status-card__head[data-path=\"/uplink\"] [data-control=\"door\"]')",
            timeout=3000)

    def test_a_refusal_stays_in_the_drawer_the_focus_on_why(self):
        page = self.page
        self._at()
        frame = self._open(self._door_of("uplink"))
        frame.locator(".ack-kind", has_text="Silence").click()
        form = frame.locator(".ls-kind-form[data-kind=silenced]")
        form.locator("textarea[name=note]").fill("it flaps every night")
        form.locator("input[name=deadline]").fill("45d")
        form.locator("button[type=submit]").click()
        page.wait_for_function(
            "(function () { var f = document.querySelector('.ls-drawer__frame');"
            " return f && f.contentDocument"
            " && f.contentDocument.querySelector('.ls-notes__refused') !== null; })()",
            timeout=5000)
        self.assertTrue(page.evaluate(_OPEN))
        self.assertIsNone(app_module.status_tree.acknowledgment("/uplink", ""))
        page.wait_for_function(
            "(function () { var f = document.querySelector('.ls-drawer__frame');"
            " return document.activeElement === f && f.contentDocument.activeElement"
            ".classList.contains('ls-notes__refused'); })()", timeout=3000)
        self.assertEqual(frame.locator(
            ".ls-kind-form[data-kind=silenced] textarea[name=note]").input_value(),
            "it flaps every night")
        # the words a refusal gave back are asked about before a close drops them
        page.locator(".ls-drawer__close").click()
        page.wait_for_function(_ASKING)

    def test_a_button_that_opens_another_tab_leaves_the_drawer_and_the_words(self):
        # A filler's button posts the form in a new tab (ADR-0148): it writes nothing
        # in the frame, so the drawer neither closes on it nor on the frame's next
        # landing at the address the form names — a reload of the frame, say — where
        # it used to take that landing for the write gone through and drop the words.
        slots.register("notes.actions", "tests.demo_extension", "notes_action.html",
                       draft=draft_issue)
        self.addCleanup(slots.forget_fillers)
        page = self.page
        self._at()
        frame = self._open(self._door_of("uplink"))
        form = frame.locator(".ls-kind-form:visible")
        words = form.locator("textarea").first
        words.fill("the provider knows\nsince the storm")
        # What the new tab is sent to is this test's; where it lands is not: no
        # tracker answers here, and a route catches no redirect a new tab follows.
        with page.context.expect_event(
                "request", lambda request: request.url.startswith(f"{TRACKER}?"),
        ) as asked, page.context.expect_page() as opened:
            form.locator(".notes-action").click()
        self.assertIn("/draft/uplink?", asked.value.redirected_from.url)
        sent = parse_qs(urlsplit(asked.value.url).query)
        self.assertEqual(sent["title"], ["/uplink: the provider knows"])
        self.assertEqual(sent["body"][0].splitlines()[:2],
                         ["the provider knows", "since the storm"])
        opened.value.close()
        self.assertTrue(page.evaluate(_OPEN))
        self.assertEqual(words.input_value(), "the provider knows\nsince the storm")
        self.assertIsNone(app_module.status_tree.acknowledgment("/uplink", ""))
        # the frame lands where its form's write would come back, with no write
        page.evaluate("document.querySelector('.ls-drawer__frame')"
                      ".contentWindow.__before = true")
        page.evaluate("document.querySelector('.ls-drawer__frame')"
                      ".contentWindow.location.reload()")
        page.wait_for_function(
            "(function () { var f = document.querySelector('.ls-drawer__frame');"
            " if (!f) { return true; }"
            " var w = f.contentWindow;"
            " return w && !w.__before && f.contentDocument.readyState === 'complete'"
            " && f.contentDocument.body"
            " && f.contentDocument.body.hasAttribute('data-ls-panel'); })()",
            timeout=5000)
        self.assertTrue(page.evaluate(_OPEN), "the reload was taken for a write")

    # --- the question ---------------------------------------------------------------

    def test_a_close_asks_before_it_drops_what_was_written(self):
        page = self.page
        self._at()
        frame = self._open(self._door_of("uplink"))
        note = frame.locator(".ls-kind-form:visible textarea").first
        note.fill("half a sentence")
        # Escape in the frame asks, *Keep writing* focused
        note.press("Escape")
        page.wait_for_function(_ASKING)
        self.assertEqual(page.evaluate("document.activeElement.dataset.ask"), "keep")
        self.assertEqual(page.locator(".ls-drawer__ask-words").inner_text(),
                         "Discard what you wrote?")
        # Escape on the question keeps writing, the focus back in the words
        page.keyboard.press("Escape")
        page.wait_for_function(f"!({_ASKING})")
        self.assertTrue(page.evaluate(_OPEN))
        focused = self._focused_in_frame()
        assert focused is not None
        self.assertEqual(focused["tag"], "textarea")
        # a click on the wall asks too; *Discard* closes
        lit = self._box(".ls-drawer__lit")
        page.mouse.click(lit["x"] + 5, lit["y"] + 5)
        page.wait_for_function(_ASKING)
        page.locator('[data-ask="discard"]').click()
        page.wait_for_function(_SHUT)
        # nothing was kept: the next opening's form is empty, and closes at once
        frame = self._open(self._door_of("uplink"))
        self.assertEqual(frame.locator(".ls-kind-form:visible textarea").first
                         .input_value(), "")
        page.keyboard.press("Escape")
        page.wait_for_function(_SHUT)

    def test_a_link_that_would_leave_the_page_asks_first(self):
        page = self.page
        self._at()
        frame = self._open(self._door_of("uplink"))
        frame.locator(".ls-kind-form:visible textarea").first.fill("a thought")
        page.locator('.ls-drawer__to[data-to="page"]').click()
        page.wait_for_function(_ASKING)
        page.locator('[data-ask="keep"]').click()
        page.wait_for_function(f"!({_ASKING})")
        self.assertTrue(page.url.endswith("/status"), page.url)

    # --- where it opens -------------------------------------------------------------

    def test_a_mark_opens_the_tab_at_its_block_its_editor_open(self):
        page = self.page
        write = app_module.status_tree.set_acknowledgment(
            "/uplink", "", SEEN, "known", expires_at=None, set_by="ada")
        assert write.current is not None, write.problem
        self._at()
        mark = self._card("uplink").locator(".status-card__head a.head-ack[data-door]")
        self._open(mark)
        src = page.evaluate("document.querySelector('.ls-drawer__frame').src")
        self.assertIn("at=seen", src)
        self.assertIn("panel=1", src)
        page.wait_for_function(
            "(function () { var f = document.querySelector('.ls-drawer__frame');"
            " var a = f && f.contentDocument.activeElement;"
            " return document.activeElement === f && a && a.name === 'note'"
            " && a.closest('#at') !== null; })()", timeout=3000)

    def test_on_a_leaf_s_page_a_line_s_door_opens_its_form_a_write_reloads(self):
        page = self.page
        self._at("/status/ci/build")
        door = page.locator(".check-reason .line-door").first
        frame = self._open(door)
        src = page.evaluate("document.querySelector('.ls-drawer__frame').src")
        self.assertIn("reason=", src)
        # nothing refreshes a leaf's page, so nothing is paused: the drawer says none
        self.assertTrue(page.locator(".ls-drawer__paused").is_hidden())
        focused = self._focused_in_frame()
        assert focused is not None
        self.assertEqual(focused["tag"], "textarea")
        form = frame.locator(".ls-kind-form:visible")
        form.locator("textarea").fill("on the line")
        with page.expect_navigation():
            form.locator("button[type=submit]").click()
        page.wait_for_function(_READY)
        self.assertFalse(page.evaluate(
            "document.getElementById('ls-drawer').open"))

