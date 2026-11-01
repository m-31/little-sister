"""A failure marked seen in a real browser (ADR-0142, as ADR-0147 amends it): marked in
the drawer a door opens — a head's for each failure at and beneath it, a line's for
the line — the part keeping its color under the ringed check, the line's mark standing
where its door stood, the block's editor on a node's page, and the refresh that waits
while it is open.

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
from urllib.parse import urlsplit

from little_sister import app as app_module
from little_sister.pins import SEEN
from little_sister.reasons import Entry
from little_sister.status import StatusCode
from little_sister.tree import StatusTree
from tests.test_pin_browser import _BrowserCase

_FOCUS_IN_NOTE = ("document.activeElement !== null"
                  " && document.activeElement.name === 'note'")
_FRAGMENT = re.compile(r"[?&]fragment=1")
#: The page waits for an open editor, and the editor says so at the top of its form,
#: the stamp keeping its width (ADR-0147 decision 4).
_PAUSED = ("Array.from(document.querySelectorAll('#status-grid .ls-paused'))"
           ".some(line => line.checkVisibility())")
_EDITING = ("document.documentElement.classList"
            ".contains('maintenance-edit-enhanced')")
#: The drawer open with its page whole in its frame, and shut (ADR-0147).
_DRAWN = ("(function () { var f = document.querySelector('.ls-drawer__frame');"
          " var d = f && f.contentDocument;"
          " return document.getElementById('ls-drawer').open"
          " && d && d.readyState === 'complete' && d.body"
          " && d.body.hasAttribute('data-ls-panel'); })()")
_SHUT = ("!document.getElementById('ls-drawer').open"
         " && document.querySelector('.ls-drawer__frame') === null")
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
    """A seen set in the drawer, on a head and on a line, and its block's editor — in
    Chromium."""

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
        self.page.wait_for_function(_EDITING)
        if clock:
            # short of the first tick, which is ten seconds in
            self.page.clock.pause_at(_NOON + timedelta(seconds=5))

    def _card(self, name: str) -> Any:
        return self.page.locator(".status-card").filter(
            has=self.page.locator(f'.status-card__head[data-path="/{name}"]'))

    @staticmethod
    def _door_of(card: Any) -> Any:
        """◇ on the card's head — among its icons, or lit in its state."""
        return card.locator('.status-card__head [data-control="door"]')

    def _line(self, text: str) -> Any:
        return self.page.locator(".check-reason").filter(
            has=self.page.locator(".check-reason__body", has_text=text))

    def _accepted(self) -> tuple[list[str], list[tuple[str, str]]]:
        nodes, lines = app_module.status_tree.acknowledgments()
        return sorted(nodes), sorted(lines)

    def test_a_cards_door_marks_each_failure_beneath_it_in_the_drawer(self):
        page = self.page
        self._wall_at()
        card = self._card("hemulen")
        self._door_of(card).click()
        page.wait_for_function(_DRAWN)
        frame = page.frame_locator(".ls-drawer__frame")
        frame.locator(".ack-kind", has_text="Seen").click()
        form = frame.locator(".ls-kind-form[data-kind=seen]")
        # each failure at and beneath the head, each its own
        self.assertEqual(form.locator("select[name=slug] option:checked")
                         .inner_text().strip(),
                         "all 2 failures listed above, each its own")
        form.locator("textarea[name=note]").fill("the disk is on order")
        form.locator("button[type=submit]").click()
        page.wait_for_function(_SHUT, timeout=5000)
        self.assertEqual(self._accepted(),
                         (["/hemulen/disk", "/hemulen/memory"], []))
        pin = app_module.status_tree.acknowledgment("/hemulen/disk")
        assert pin is not None
        self.assertEqual((pin.kind, pin.note, pin.set_by, pin.expires_at),
                         (SEEN, "the disk is on order", "pan", None))
        # the wall is up to date at once: each part keeps its color under the ringed
        # check, and the card's door counts them
        page.wait_for_function(
            "document.querySelectorAll('#status-grid"
            " .tree-node[data-node^=\"/hemulen/\"] .head-ack').length === 2",
            timeout=3000)
        disk = page.locator(
            '.status-node:has(> .status-node__self[data-path="/hemulen/disk"])')
        memory = page.locator(
            '.status-node:has(> .status-node__self[data-path="/hemulen/memory"])')
        self.assertIn("s-error", disk.get_attribute("class"))
        self.assertIn("s-warn", memory.get_attribute("class"))
        self.assertEqual(self._door_of(self._card("hemulen")).inner_text().strip(), "2")
        self.assertEqual(urlsplit(page.url).path, "/status")

    def test_a_line_marked_seen_keeps_its_color_its_mark_where_its_door_stood(self):
        page = self.page
        self._wall_at("/status/ci/build")
        line = self._line("test fails")
        door = line.locator(".line-door")
        stood = door.bounding_box()
        row = line.bounding_box()
        assert stood is not None and row is not None
        seat = (stood["x"] - row["x"], stood["y"] - row["y"])
        door.click()
        page.wait_for_function(_DRAWN)
        frame = page.frame_locator(".ls-drawer__frame")
        frame.locator(".ack-kind", has_text="Seen").click()
        form = frame.locator(".ls-kind-form[data-kind=seen]")
        self.assertEqual(form.locator("select[name=slug] option:checked")
                         .inner_text().strip(), "its line: test fails")
        form.locator("textarea[name=note]").fill("flaky since the runner move")
        # a leaf's page, which nothing refreshes, is loaded again
        with page.expect_navigation():
            form.locator("button[type=submit]").click()
        page.wait_for_function(_EDITING)
        self.assertEqual(self._accepted(), ([], [("/ci/build", "test")]))
        line = self._line("test fails")
        self.assertIn("s-error", line.get_attribute("class"))
        self.assertIn("This line is marked seen by pan",
                      " ".join(line.locator('.rule-block[data-rule="seen"]')
                               .first.inner_text().split()))
        # the door used became the mark where it stood (ADR-0147 decision 7)
        self.assertEqual(line.locator(".line-door").count(), 0)
        mark = line.locator(".line-ack").bounding_box()
        now = line.bounding_box()
        assert mark is not None and now is not None
        self.assertLessEqual(abs(mark["x"] - now["x"] - seat[0]), 1.5)
        self.assertLessEqual(abs(mark["y"] - now["y"] - seat[1]), 1.5)
        # the line that still warns keeps its door
        self.assertEqual(self._line("lint warns").locator(".line-door").count(), 1)

    def test_a_seen_s_editor_on_a_branch_s_page_makes_the_refresh_wait(self):
        # a branch with lines of its own, one of them marked seen: its page's head
        # states the line's block, whose editor stands in what the refresh swaps
        tree = app_module.status_tree
        tree.upsert("/ci", StatusCode.WARN, [
            Entry("queue", "the queue is long", StatusCode.WARN)], members=True)
        write = tree.set_acknowledgment("/ci", "queue", SEEN, "known",
                                        expires_at=None, set_by="ada")
        assert write.current is not None, write.problem
        page = self.page
        self._wall_at("/status/ci", clock=True)
        line = page.locator(".viewed-head .check-reason").filter(
            has=page.locator(".check-reason__body", has_text="the queue is long"))
        line.locator(".rule-block__edit > summary").click()
        page.wait_for_function(_FOCUS_IN_NOTE)
        page.wait_for_function(_PAUSED, timeout=3000)
        page.keyboard.type(", and growing")
        page.clock.run_for(35_000)
        page.wait_for_timeout(300)          # room for a request that must not come
        self.assertEqual(self.fragments, [])
        self.assertEqual(page.evaluate("document.activeElement.value"),
                         "known, and growing")
        page.keyboard.press("Escape")
        page.wait_for_function(f"!({_PAUSED})", timeout=3000)

    def test_without_script_a_cards_door_is_a_link_to_the_tab(self):
        page = self._signed_in(java_script_enabled=False, **self.drawn_in)
        page.goto(f"{self.base}/status")
        card = page.locator(".status-card").filter(
            has=page.locator('.status-card__head[data-path="/hemulen"]'))
        with page.expect_navigation():
            card.locator('.status-card__head [data-control="door"]').click()
        self.assertEqual(urlsplit(page.url).path, "/notes/hemulen")
        # whose form marks each failure seen, every kind's form whole without script
        form = page.locator(".ls-kind-form[data-kind=seen]")
        self.assertTrue(form.is_visible())
        self.assertEqual(form.locator("select[name=slug] option:checked")
                         .inner_text().strip(),
                         "all 2 failures listed above, each its own")
