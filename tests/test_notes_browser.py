"""A node's Notes tab in a real browser (ADR-0145): the chosen kind's form in view and
every other hidden, the words and the part following a change of kind, a write coming
back to the tab, a refusal taking the eye to why — and the layout, two columns at a
desk and one on a phone, in the order the drawer reads.

What the server answers and what a page draws of it is ``tests/test_notes_tab.py``'s.
Served by a real server to headless Chromium as ``tests/test_seen_browser.py`` is,
whose estate this one shares, and skipped where Playwright or a Chromium binary is
unavailable (``docs/testing-the-gui.md``, Mode 5).
"""
from __future__ import annotations

from typing import Any

from little_sister import app as app_module
from little_sister.pins import SEEN
from tests.test_pin_browser import _BrowserCase
from tests.test_seen_browser import _wall

_EDITING = ("document.documentElement.classList"
            ".contains('maintenance-edit-enhanced')")


class NotesTabBrowserTests(_BrowserCase):
    """The Notes tab's form and layout — in Chromium."""

    estate = staticmethod(_wall)

    def setUp(self) -> None:
        super().setUp()
        # the start's wiring: every pin the tree ends is recorded in its note
        app_module.status_tree.on_pin_end(app_module.notes_book.pin_ended)

    def _tab(self, url: str = "/notes/ci/build") -> Any:
        self.page.goto(f"{self.base}{url}")
        self.page.wait_for_function(_EDITING)
        return self.page.locator(".ls-tab__form")

    def _shown(self, form: Any) -> list[str]:
        """The kinds whose forms are in view."""
        return [kind for kind in ("note", "seen", "silenced", "maintenance")
                if form.locator(f"form[data-kind={kind}]").is_visible()]

    def test_the_chosen_kind_s_form_shows_and_the_words_and_the_part_follow(self):
        form = self._tab("/notes/ci/build?reason=test")
        self.assertEqual(self._shown(form), ["seen"])
        seen = form.locator("form[data-kind=seen]")
        self.assertEqual(seen.locator("select[name=slug]").input_value(), "test")
        seen.locator("textarea[name=note]").fill("the runner flaps")
        form.locator(".ack-kind", has_text="Note").click()
        self.assertEqual(self._shown(form), ["note"])
        note = form.locator("form[data-kind=note]")
        self.assertEqual(note.locator("textarea[name=text]").input_value(),
                         "the runner flaps")
        # the line the tab opened on is the note's choice too, and a part chosen
        # after is every kind's that may be set on it
        self.assertEqual(note.locator("select[name=slug]").input_value(), "test")
        note.locator("select[name=slug]").select_option("docs")
        form.locator(".ack-kind", has_text="Maintenance").click()
        self.assertEqual(self._shown(form), ["maintenance"])
        maintenance = form.locator("form[data-kind=maintenance]")
        self.assertEqual(maintenance.locator("select[name=slug]").input_value(), "docs")
        self.assertEqual(maintenance.locator("textarea[name=note]").input_value(),
                         "the runner flaps")
        # and Silence, which may be set on a line that reads ok too, follows it
        # (ADR-0144 decision 1), while Seen, which may be set on what fails alone,
        # keeps the line the tab opened on
        form.locator(".ack-kind", has_text="Silence").click()
        self.assertEqual(self._shown(form), ["silenced"])
        self.assertEqual(form.locator("form[data-kind=silenced] select[name=slug]")
                         .input_value(), "docs")
        form.locator(".ack-kind", has_text="Seen").click()
        self.assertEqual(self._shown(form), ["seen"])
        self.assertEqual(form.locator("form[data-kind=seen] select[name=slug]")
                         .input_value(), "test")

    def test_a_seen_set_from_the_tab_comes_back_to_it(self):
        form = self._tab("/notes/ci/build?reason=test")
        form.locator("form[data-kind=seen] textarea[name=note]").fill("known")
        with self.page.expect_navigation():
            form.locator("form[data-kind=seen] button[type=submit]").click()
        self.assertTrue(self.page.url.endswith("/notes/ci/build"), self.page.url)
        pin = app_module.status_tree.acknowledgment("/ci/build", "test")
        assert pin is not None
        self.assertEqual((pin.kind, pin.note), (SEEN, "known"))
        self.assertIn("known", self.page.locator(".ls-tab__stands").inner_text())

    def test_a_refusal_takes_the_eye_to_why_with_the_words_in_the_form(self):
        self.page.set_viewport_size({"width": 390, "height": 700})
        form = self._tab("/notes/ci/build?reason=test&kind=silenced")
        silence = form.locator("form[data-kind=silenced]")
        silence.locator("textarea[name=note]").fill("it flaps every night")
        silence.locator("input[name=deadline]").fill("45d")
        with self.page.expect_navigation():
            silence.locator("button[type=submit]").click()
        refused = self.page.locator(".ls-notes__refused")
        self.page.wait_for_function(
            "document.activeElement !== null"
            " && document.activeElement.classList.contains('ls-notes__refused')")
        self.assertTrue(refused.is_visible())
        box = refused.bounding_box()
        assert box is not None
        self.assertLess(box["y"], 700, "scrolled into view")
        self.assertEqual(self._shown(self.page.locator(".ls-tab__form")),
                         ["silenced"])
        self.assertEqual(silence.locator("textarea[name=note]").input_value(),
                         "it flaps every night")

    def test_two_columns_at_a_desk_and_one_on_a_phone(self):
        app_module.notes_book.add("/ci/build", "", "an older note", by="ada",
                                  context=app_module.context_of(
                                      app_module.status_tree.snapshot("/ci/build")))
        self.page.set_viewport_size({"width": 1300, "height": 900})
        self._tab()
        parts = [".ls-tab__fails", ".ls-tab__before", ".ls-tab__stands",
                 ".ls-tab__form", ".ls-tab__history"]

        def boxes() -> list[dict[str, float]]:
            found = []
            for selector in parts:
                box = self.page.locator(selector).bounding_box()
                assert box is not None, selector
                found.append(box)
            return found

        fails, line, stands, form, history = boxes()
        self.assertGreaterEqual(history["x"], form["x"] + form["width"],
                                "the history beside the form")
        self.assertLess(fails["y"], line["y"])
        self.assertLess(line["y"], stands["y"])
        self.assertLess(stands["y"], form["y"])
        self.page.set_viewport_size({"width": 390, "height": 844})
        ys = [box["y"] for box in boxes()]
        self.assertEqual(ys, sorted(ys), "one column, in the drawer's order")
        width = self.page.evaluate("document.documentElement.scrollWidth")
        self.assertLessEqual(width, 390, "and no page wider than the phone")
