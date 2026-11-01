"""The choice of *Seen* or *Silence* in a real browser (ADR-0144, as ADR-0147 amends
it): in a seen's block's editor the chosen kind's form in view and the other's hidden,
the note following a change of kind, Cancel putting the choice back; a card's door
silencing each failure beneath it in the drawer; and a silence's editor selecting the
deadline it keeps.

What the server answers to `POST /pins/silenced` and what a page draws of it is
`tests/test_silenced_pages.py`'s. Served by a real server to headless Chromium as
``tests/test_seen_browser.py`` is, whose case and estate this one shares, and skipped
where Playwright or a Chromium binary is unavailable (``docs/testing-the-gui.md``,
Mode 5).
"""
from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from little_sister import app as app_module
from little_sister.pins import SEEN, SILENCED
from little_sister.status import StatusCode
from tests.test_pin_browser import _BrowserCase
from tests.test_seen_browser import _DRAWN, _FOCUS_IN_NOTE, _SHUT, _wall

_EDITING = ("document.documentElement.classList"
            ".contains('maintenance-edit-enhanced')")


class SilencedBrowserTests(_BrowserCase):
    """*Seen* or *Silence*, chosen in one editor — in Chromium."""

    estate = staticmethod(_wall)

    def _line_editor(self) -> Any:
        """The editor of the seen a line's block states, on its node's page: its own
        kind's form, *Seen*, and the other's, *Silence*, which makes it a silence."""
        app_module.status_tree.set_acknowledgment(
            "/ci/build", "test", SEEN, "", expires_at=None, set_by="ada")
        page = self.page
        page.goto(f"{self.base}/status/ci/build")
        page.wait_for_function(_EDITING)
        line = page.locator(".check-reason").filter(
            has=page.locator(".check-reason__body", has_text="test fails"))
        line.locator(".rule-block__edit > summary").click()
        page.wait_for_function(_FOCUS_IN_NOTE)
        return line.locator("details.rule-block__edit")

    def _focused(self) -> tuple[str, str]:
        """The focused field's name, and the kind of the form it stands in."""
        return tuple(self.page.evaluate(
            "() => [document.activeElement.name,"
            " document.activeElement.closest('.ack-form').dataset.kind]"))

    def test_the_chosen_kind_s_form_shows_and_the_note_follows(self):
        editor = self._line_editor()
        seen = editor.locator("form[data-kind=seen]")
        silence = editor.locator("form[data-kind=silenced]")
        self.assertEqual((seen.is_visible(), silence.is_visible()), (True, False))
        self.assertEqual(self._focused(), ("note", "seen"))
        self.page.keyboard.type("the runner flaps")
        editor.locator(".ack-kind", has_text="Silence").click()
        self.assertEqual((seen.is_visible(), silence.is_visible()), (False, True))
        # the note follows to the form in view, and the focus with it
        self.assertEqual(self._focused(), ("note", "silenced"))
        self.assertEqual(silence.locator("textarea[name=note]").input_value(),
                         "the runner flaps")
        # Cancel closes the editor and puts the choice and the notes back
        silence.locator(".maintenance-editor-cancel").click()
        self.assertFalse(editor.evaluate("details => details.open"))
        editor.locator(":scope > summary").click()
        self.page.wait_for_function(_FOCUS_IN_NOTE)
        self.assertEqual((seen.is_visible(), silence.is_visible()), (True, False))
        self.assertEqual([seen.locator("textarea[name=note]").input_value(),
                          silence.locator("textarea[name=note]").input_value()],
                         ["", ""])

    def test_a_cards_door_silences_each_failure_beneath_it_in_the_drawer(self):
        page = self.page
        page.goto(f"{self.base}/status")
        page.wait_for_function(_EDITING)
        card = page.locator(".status-card").filter(
            has=page.locator('.status-card__head[data-path="/hemulen"]'))
        card.locator('.status-card__head [data-control="door"]').click()
        page.wait_for_function(_DRAWN)
        frame = page.frame_locator(".ls-drawer__frame")
        frame.locator(".ack-kind", has_text="Silence").click()
        silence = frame.locator(".ls-kind-form[data-kind=silenced]")
        silence.locator("textarea[name=note]").fill("a noisy week")
        silence.locator("input[name=level][value=warn]").check()
        silence.locator("button[type=submit]").click()
        page.wait_for_function(_SHUT, timeout=5000)
        nodes, lines = app_module.status_tree.acknowledgments()
        self.assertEqual((sorted(nodes), sorted(lines)),
                         (["/hemulen/disk", "/hemulen/memory"], []))
        week = datetime.now(UTC) + timedelta(days=7)
        for pin in nodes.values():
            assert pin.expires_at is not None
            self.assertEqual((pin.kind, pin.level, pin.note, pin.set_by),
                             (SILENCED, StatusCode.WARN, "a noisy week", "pan"))
            self.assertLess(abs((pin.expires_at - week).total_seconds()), 120)

    def test_a_silences_editor_chooses_it_and_selects_the_deadline_it_keeps(self):
        page = self.page
        app_module.status_tree.set_acknowledgment(
            "/hemulen/disk", "", SILENCED, "the vendor patches friday",
            expires_at=datetime.now(UTC) + timedelta(days=3), set_by="ada",
            level=StatusCode.WARN)
        page.goto(f"{self.base}/status/hemulen/disk")
        page.wait_for_function(_EDITING)
        block = page.locator('.rule-block[data-rule="silenced"]').first
        block.locator("details.rule-block__edit > summary").click()
        page.wait_for_function(_FOCUS_IN_NOTE)
        silence = block.locator("form[data-kind=silenced]")
        self.assertTrue(silence.is_visible())
        self.assertFalse(block.locator("form[data-kind=seen]").is_visible())
        self.assertEqual(self._focused(), ("note", "silenced"))
        deadline = silence.locator("input[name=deadline]")
        deadline.click()
        page.wait_for_function(
            "() => { const field = document.activeElement;"
            " return field.name === 'deadline' && field.selectionStart === 0"
            " && field.selectionEnd === field.value.length; }")
        self.assertTrue(deadline.input_value())

    def test_one_that_fails_no_longer_opens_its_own_form_alone(self):
        # a seen takes a part that fails now: the editor of a silence that held
        # through a recovery shows the silence's form, with no choice, its note in
        # focus
        page = self.page
        app_module.status_tree.set_acknowledgment(
            "/hemulen/disk", "", SILENCED, "the vendor patches friday",
            expires_at=datetime.now(UTC) + timedelta(days=3), set_by="ada",
            level=StatusCode.OK)
        app_module.status_tree.upsert("/hemulen/disk", StatusCode.OK, "disk 60 % full")
        page.goto(f"{self.base}/status/hemulen/disk")
        page.wait_for_function(_EDITING)
        block = page.locator('.rule-block[data-rule="silenced"]').first
        block.locator("details.rule-block__edit > summary").click()
        page.wait_for_function(_FOCUS_IN_NOTE)
        self.assertTrue(block.locator("form[data-kind=silenced]").is_visible())
        self.assertEqual((block.locator("form[data-kind=seen]").count(),
                          block.locator(".ack-kinds").count()), (0, 0))
        self.assertEqual(self._focused(), ("note", "silenced"))
