"""The ringed check in a real browser (ADR-0142): the page's one editor cloned into a
box, the head's own on a node's page, a line's beside its line, and the refresh that
waits while one is open.

What the server answers to `POST /pins/seen` and what a page draws of it is
`tests/test_seen_pages.py`'s; what the tree does with it `tests/test_seen.py`'s. Served
by a real server to headless Chromium as ``tests/test_pin_browser.py`` is, whose case
this one shares, and skipped where Playwright or a Chromium binary is unavailable
(``docs/testing-the-gui.md``, Mode 5).
"""
from __future__ import annotations

import re
from datetime import UTC, datetime, timedelta
from typing import Any
from urllib.parse import parse_qs, urlsplit

from little_sister import app as app_module
from little_sister.pins import SEEN
from little_sister.reasons import Entry
from little_sister.status import StatusCode
from little_sister.tree import StatusTree
from tests.test_pin_browser import _BrowserCase

_FOCUS_IN_NOTE = ("document.activeElement !== null"
                  " && document.activeElement.name === 'note'")
_NO_CLONE = "document.querySelector('#status-grid details.is-clone') === null"
_FRAGMENT = re.compile(r"[?&]fragment=1")
_PAUSED = ("document.getElementById('status-updated').textContent"
           ".trim().endsWith('paused while editing')")
#: The page's clock where a test holds it, as ``tests/test_pin_browser.py`` does.
_NOON = datetime(2026, 10, 3, 12, 0, 0, tzinfo=UTC)


def _wall() -> StatusTree:
    """A host two of whose parts fail, a leaf that warns, a host that is well, and
    a build whose lines are members, two of them failing."""
    tree = StatusTree()
    tree.upsert("/hemulen/cpu", StatusCode.OK, "within its limits")
    tree.upsert("/hemulen/disk", StatusCode.ERROR, "disk 97 % full")
    tree.upsert("/hemulen/memory", StatusCode.WARN, "swap 60 % used")
    tree.upsert("/uplink", StatusCode.WARN, "packet loss of 2 %")
    tree.upsert("/gaffsie/cpu", StatusCode.OK, "within its limits")
    tree.upsert("/ci/build", StatusCode.ERROR, [
        Entry("test", "test fails", StatusCode.ERROR),
        Entry("lint", "lint warns", StatusCode.WARN),
        Entry("docs", "docs build", StatusCode.OK)], members=True)
    return tree


class SeenBrowserTests(_BrowserCase):
    """✓ on a card, on a page's head and on a line — in Chromium."""

    estate = staticmethod(_wall)

    def setUp(self) -> None:
        super().setUp()
        self.fragments: list[str] = []
        self.page.on("request", lambda request: (
            self.fragments.append(request.url) if _FRAGMENT.search(request.url)
            else None))

    def _wall_at(self, url: str = "/status", *, clock: bool = False) -> None:
        if clock:
            self.page.clock.install(time=_NOON)
        self.page.goto(f"{self.base}{url}")
        self.page.wait_for_function(
            "document.documentElement.classList"
            ".contains('maintenance-edit-enhanced')")
        if clock:
            # short of the first tick, which is ten seconds in
            self.page.clock.pause_at(_NOON + timedelta(seconds=5))

    def _card(self, name: str) -> Any:
        return self.page.locator(".status-card").filter(
            has=self.page.locator(f'.status-card__head[data-path="/{name}"]'))

    @staticmethod
    def _check_of(card: Any) -> Any:
        return card.locator('.status-card__head [data-control="ack"]')

    @staticmethod
    def _scope(within: Any) -> str:
        said = within.locator(".rule-block__scope strong").inner_text()
        return " ".join(said.split())

    def _accepted(self) -> tuple[list[str], list[tuple[str, str]]]:
        nodes, lines = app_module.status_tree.acknowledgments()
        return sorted(nodes), sorted(lines)

    def test_a_cards_check_marks_each_failure_beneath_it_from_the_pages_editor(self):
        page = self.page
        self._wall_at()
        # one editor for the page, outside the grid, and none in a card until ✓
        self.assertEqual(page.locator("template#ack-editor").count(), 1)
        self.assertEqual(page.locator("#status-grid details.ack-setter").count(), 0)
        card = self._card("hemulen")
        check = self._check_of(card)
        digest = check.get_attribute("data-ack-parts")
        self.assertEqual(check.get_attribute("data-ack-count"), "2")
        check.click()
        page.wait_for_function(_FOCUS_IN_NOTE)
        clone = card.locator("details.ack-setter.is-clone")
        self.assertEqual(clone.count(), 1)
        self.assertEqual(check.get_attribute("aria-expanded"), "true")
        self.assertEqual(self._scope(clone), "Mark seen the 2 failures at and beneath "
                                             "hemulen, each its own.")
        self.assertEqual(clone.locator("input[name=path]").input_value(), "/hemulen")
        self.assertEqual(clone.locator("input[name=parts]").input_value(), digest)
        # a leaf that fails for itself is the one failure at it
        self._check_of(self._card("uplink")).click()
        page.wait_for_function(_FOCUS_IN_NOTE)
        self.assertEqual(clone.count(), 0)                  # one editor at a time
        uplink = self._card("uplink").locator("details.ack-setter.is-clone")
        self.assertEqual(self._scope(uplink), "Mark seen the one failure at uplink.")
        page.keyboard.press("Escape")
        page.wait_for_function(_NO_CLONE, timeout=3000)

        check.click()
        page.wait_for_function(_FOCUS_IN_NOTE)
        page.keyboard.type("the disk is on order")
        with page.expect_navigation():
            card.locator("details.ack-setter button[type=submit]").click()
        self.assertEqual(urlsplit(page.url).path, "/status")
        self.assertEqual(self._accepted(),
                         (["/hemulen/disk", "/hemulen/memory"], []))
        pin = app_module.status_tree.acknowledgment("/hemulen/disk")
        assert pin is not None
        self.assertEqual((pin.kind, pin.note, pin.set_by, pin.expires_at),
                         (SEEN, "the disk is on order", "pan", None))
        # what was marked offers no check any longer, and each box beneath the head
        # states its seen
        self.assertEqual(self._check_of(self._card("hemulen")).count(), 0)
        self.assertEqual(self._check_of(self._card("uplink")).count(), 1)
        stated = self._card("hemulen").locator('.rule-block[data-rule="seen"]')
        self.assertEqual(stated.count(), 2)
        self.assertIn("Seen by pan at", " ".join(stated.first.inner_text().split()))

    def test_its_check_and_its_pause_mark_share_the_one_place(self):
        # ✓ and ‖ open their editors where the block will stand, one at a time:
        # the one opened last takes the other's place
        page = self.page
        self._wall_at()
        card = self._card("hemulen")
        self._check_of(card).click()
        page.wait_for_function(_FOCUS_IN_NOTE)
        card.locator('.status-card__head [data-control="pin"]').click()
        page.wait_for_function(_FOCUS_IN_NOTE)
        self.assertEqual(card.locator("details.ack-setter").count(), 0)
        self.assertEqual(card.locator("details.pin-setter.is-clone").count(), 1)
        self.assertEqual(self._check_of(card).get_attribute("aria-expanded"), "false")
        page.keyboard.press("Escape")
        page.wait_for_function(_NO_CLONE, timeout=3000)
        # Escape gives the focus back to what opened the editor, which says so
        self._check_of(card).click()
        page.wait_for_function(_FOCUS_IN_NOTE)
        page.keyboard.type("not after all")
        page.keyboard.press("Escape")
        page.wait_for_function(_NO_CLONE, timeout=3000)
        check = self._check_of(card)
        self.assertTrue(check.evaluate("check => check === document.activeElement"))
        self.assertEqual(check.get_attribute("aria-expanded"), "false")
        self.assertEqual(self._accepted(), ([], []))

    def test_the_refresh_waits_while_its_editor_is_open(self):
        page = self.page
        self._wall_at(clock=True)
        self._check_of(self._card("uplink")).click()
        page.wait_for_function(_FOCUS_IN_NOTE)
        page.wait_for_function(_PAUSED, timeout=3000)
        page.keyboard.type("half a sentence")
        page.clock.run_for(35_000)
        page.wait_for_timeout(300)          # room for a request that must not come
        self.assertEqual(self.fragments, [])
        self.assertEqual(page.evaluate("document.activeElement.value"),
                         "half a sentence")
        page.keyboard.press("Escape")
        page.wait_for_function(_NO_CLONE, timeout=3000)
        page.wait_for_function(f"!({_PAUSED})", timeout=3000)

    def test_a_pages_check_opens_the_editor_its_head_keeps_listing_each(self):
        page = self.page
        page.goto(f"{self.base}/status/hemulen")
        head = page.locator(".viewed-head")
        check = head.locator('.node-icons > [data-control="ack"]')
        setter = head.locator(":scope > details.ack-setter")
        check.wait_for(state="visible")
        self.assertTrue(setter.is_hidden())
        self.assertEqual(check.get_attribute("aria-expanded"), "false")
        check.click()
        page.wait_for_function(_FOCUS_IN_NOTE)
        self.assertTrue(setter.is_visible())
        self.assertEqual(check.get_attribute("aria-expanded"), "true")
        listed = [" ".join(item.split())
                  for item in setter.locator(".ack-parts li").all_inner_texts()]
        self.assertEqual(listed, ["/hemulen/disk, its own failure",
                                  "/hemulen/memory, its own failure"])
        page.keyboard.type("both known")
        with page.expect_navigation():
            setter.locator("button[type=submit]").click()
        self.assertEqual(self._accepted(),
                         (["/hemulen/disk", "/hemulen/memory"], []))
        self.assertEqual(urlsplit(page.url).path, "/status/hemulen")
        # the page offers it no longer
        self.assertEqual(page.locator('.viewed-head [data-control="ack"]').count(), 0)

    def test_a_line_is_marked_beside_it_and_the_write_comes_back_to_it(self):
        page = self.page
        page.goto(f"{self.base}/status/ci/build")
        line = page.locator(".check-reason").filter(
            has=page.locator(".check-reason__body", has_text="test fails"))
        line.locator(".reason-ack > summary").click()
        page.wait_for_function(_FOCUS_IN_NOTE)
        self.assertEqual(self._scope(line.locator(".reason-ack")),
                         "Mark seen this line.")
        page.keyboard.type("flaky since the runner move")
        with page.expect_navigation():
            line.locator(".reason-ack button[type=submit]").click()
        where = urlsplit(page.url)
        self.assertEqual((where.path, parse_qs(where.query), where.fragment),
                         ("/status/ci/build", {"reason": ["test"]}, "pinned-reason"))
        self.assertEqual(self._accepted(), ([], [("/ci/build", "test")]))
        marked = page.locator("#pinned-reason")
        self.assertIn("This line is marked seen by pan",
                      " ".join(marked.locator('.rule-block[data-rule="seen"]')
                               .first.inner_text().split()))
        self.assertEqual(marked.locator(".line-ack").count(), 1)
        self.assertEqual(marked.locator(".reason-ack").count(), 0)
        # the line that still warns keeps its own
        lint = page.locator(".check-reason").filter(
            has=page.locator(".check-reason__body", has_text="lint warns"))
        self.assertEqual(lint.locator(".reason-ack").count(), 1)

    def test_without_script_a_cards_check_is_a_link_to_the_nodes_page(self):
        page = self._signed_in(java_script_enabled=False, **self.drawn_in)
        page.goto(f"{self.base}/status")
        card = page.locator(".status-card").filter(
            has=page.locator('.status-card__head[data-path="/hemulen"]'))
        with page.expect_navigation():
            card.locator('.status-card__head [data-control="ack"]').click()
        self.assertEqual(urlsplit(page.url).path, "/status/hemulen")
        # whose head keeps *Mark seen*, the browser's own disclosure
        head = page.locator(".viewed-head")
        form = head.locator("details.ack-setter form.maintenance-editor-form")
        self.assertFalse(form.is_visible())
        head.locator("details.ack-setter > summary").click()
        self.assertTrue(form.is_visible())
