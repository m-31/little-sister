"""A line marked done in a real browser (ADR-0146): its words beside its OK cue and the
failure it closed, on its node's page and on the wall, and a seen's block's editor
choosing *Done*, its form in view and the others hidden, the note following.

What the server answers to `POST /pins/done` and what a page draws of it is
`tests/test_done_pages.py`'s; what the tree does with it `tests/test_done.py`'s.
Served by a real server to headless Chromium as ``tests/test_seen_browser.py`` is,
whose case this one shares, and skipped where Playwright or a Chromium binary is
unavailable (``docs/testing-the-gui.md``, Mode 5).
"""
from __future__ import annotations

from typing import Any

from little_sister import app as app_module
from little_sister.pins import DONE, SEEN
from little_sister.reasons import Entry
from little_sister.status import StatusCode
from little_sister.tree import StatusTree
from tests.test_pin_browser import _BrowserCase
from tests.test_seen_browser import _FOCUS_IN_NOTE

_EDITING = ("document.documentElement.classList"
            ".contains('maintenance-edit-enhanced')")


def _build() -> StatusTree:
    """A build whose lines are members, its test a run that names its event and
    fails, under a host that is well."""
    tree = StatusTree()
    tree.upsert("/gaffsie/cpu", StatusCode.OK, "within its limits")
    tree.upsert("/ci/build", StatusCode.ERROR, [
        Entry("test", "test failed in run 7, the runner out of disk",
              code=StatusCode.ERROR, occurrence="run 7/1"),
        Entry("docs", "docs built", code=StatusCode.OK, occurrence="run 7/1")],
        members=True)
    return tree


class DoneBrowserTests(_BrowserCase):
    """A done line and a seen made done — in Chromium."""

    estate = staticmethod(_build)

    def _mark(self, kind: str) -> None:
        write = app_module.status_tree.set_acknowledgment(
            "/ci/build", "test", kind, "looked into", expires_at=None, set_by="ada")
        self.assertTrue(write.applied, write.problem)

    def _beside(self, line: Any) -> None:
        """The line's words begin on its first line, beside the OK cue and the failure
        it closed, rather than on a line of their own beneath them."""
        closed = line.locator(
            ":scope > .line-closed, .check-reason__body > .line-closed")
        words = line.locator(":scope > p, .check-reason__body > p")
        self.assertEqual(closed.inner_text(), "· error ·")
        gloss = closed.bounding_box()
        text = words.evaluate(
            "p => { const r = document.createRange(); r.selectNodeContents(p);"
            " const box = r.getClientRects()[0];"
            " return {top: box.top, left: box.left}; }")
        assert gloss is not None
        self.assertLess(abs(text["top"] - gloss["y"]), gloss["height"] / 2,
                        "the words start a line of their own beneath the cue")
        self.assertGreater(text["left"], gloss["x"] + gloss["width"] - 1)

    def test_its_words_stand_beside_its_cue_and_the_failure_it_closed(self):
        self._mark(DONE)
        page = self.page
        page.goto(f"{self.base}/status/ci/build")
        self._beside(page.locator(".check-reason.is-done"))
        page.goto(f"{self.base}/status")
        self._beside(page.locator(".status-node__reason.is-done"))

    def test_a_seens_editor_chooses_done_its_form_alone_and_the_note_follows(self):
        self._mark(SEEN)
        page = self.page
        page.goto(f"{self.base}/status/ci/build")
        page.wait_for_function(_EDITING)
        block = page.locator('.rule-block[data-rule="seen"]').first
        block.locator("details.rule-block__edit > summary").click()
        page.wait_for_function(_FOCUS_IN_NOTE)
        forms = {kind: block.locator(f"form[data-kind={kind}]")
                 for kind in ("done", "seen", "silenced")}
        self.assertEqual({kind: form.is_visible() for kind, form in forms.items()},
                         {"done": False, "seen": True, "silenced": False})
        page.keyboard.press("End")
        page.keyboard.type(", and it is over")
        block.locator(".ack-kind", has_text="Done").click()
        self.assertEqual({kind: form.is_visible() for kind, form in forms.items()},
                         {"done": True, "seen": False, "silenced": False})
        note = forms["done"].locator("textarea[name=note]")
        self.assertEqual(note.input_value(), "looked into, and it is over")
        with page.expect_navigation():
            forms["done"].locator("button[type=submit]").click()
        pin = app_module.status_tree.acknowledgment("/ci/build", "test")
        assert pin is not None
        self.assertEqual((pin.kind, pin.occurrence, pin.status, pin.note),
                         (DONE, "run 7/1", StatusCode.ERROR,
                          "looked into, and it is over"))
