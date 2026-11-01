"""A planned set in a real browser (ADR-0150, landing 3b's fourth question): a set
from the drawer that plans a window, rather than opening one, is answered at the tab,
at its new block, which the drawer shows — it stays open, the block in view with the
focus on it and *Edit* beside its sentence — while a set that opens a window closes the
drawer onto the wall, as every write that goes through does.

What the server answers — the tab at the block, in the panel — is
``tests/test_planned.py``'s. Served by a real server to headless Chromium as
``tests/test_drawer_browser.py`` is, whose case and estate this one shares, and
skipped where Playwright or a Chromium binary is unavailable
(``docs/testing-the-gui.md``, Mode 5).
"""
from __future__ import annotations

from typing import Any, ClassVar

from little_sister import app as app_module
from tests.test_drawer_browser import _LOADED, _OPEN, _READY, _SHUT
from tests.test_pin_browser import _BrowserCase
from tests.test_seen_browser import _wall

#: The block the frame's page landed at, planned, and where the focus is in it.
_AT_PLANNED = ("(function () { var f = document.querySelector('.ls-drawer__frame');"
               " var d = f && f.contentDocument;"
               " var at = d && d.getElementById('at');"
               " return at !== null && at.classList.contains('rule-block--planned')"
               " && document.activeElement === f && d.activeElement === at; })()")


class PlannedSetBrowserTests(_BrowserCase):
    """A window set ahead from the drawer, and one set now — in Chromium."""

    estate = staticmethod(_wall)
    drawn_in: ClassVar[dict[str, Any]] = {
        "viewport": {"width": 1300, "height": 800}, "reduced_motion": "reduce"}

    def _open_uplink(self) -> Any:
        """The wall, and the drawer opened at the uplink's door: its page, the
        panel."""
        page = self.page
        page.goto(f"{self.base}/status")
        page.wait_for_function(_READY)
        page.locator(".status-card").filter(
            has=page.locator('.status-card__head[data-path="/uplink"]')).locator(
            '.status-card__head .node-icons [data-control="door"]').click()
        page.wait_for_function(_OPEN)
        page.wait_for_function(_LOADED)
        return page.frame_locator(".ls-drawer__frame")

    def _set(self, frame: Any, *, starts: str, duration: str) -> None:
        frame.locator(".ack-kind", has_text="Maintenance").click()
        form = frame.locator(".ls-kind-form[data-kind=maintenance]")
        form.locator("textarea[name=note]").fill("the provider swaps the router")
        form.locator("input[name=starts]").fill(starts)
        form.locator("input[name=duration]").fill(duration)
        # the kind's own button: the editor's own — Preview, Add an interval, weekend,
        # working week — are submit buttons too (ADR-0150, landing 4)
        form.locator(".maintenance-editor-form__actions > button[type=submit]").click()

    def test_a_planned_set_stays_open_at_its_new_block(self):
        page = self.page
        frame = self._open_uplink()
        self._set(frame, starts="3d", duration="2h")
        page.wait_for_function(_AT_PLANNED, timeout=5000)
        self.assertTrue(page.evaluate(_OPEN), "the drawer stays open on it")
        entry = app_module.status_tree.standing_entry("/uplink")
        assert entry is not None and entry.schedule is not None
        self.assertIsNone(app_module.status_tree.maintenance_entry("/uplink"),
                          "it holds nothing until its start")
        block = frame.locator("#at")
        self.assertIn("starts in 2d 23h", block.locator(".rule-block__what")
                      .inner_text())
        self.assertTrue(block.locator(".rule-block__edit > summary").is_visible(),
                        "Edit stands beside its sentence")
        # nothing was written that a close would drop: it closes without asking
        page.locator(".ls-drawer__close").click()
        page.wait_for_function(_SHUT, timeout=3000)

    def test_a_set_that_opens_a_window_closes_it(self):
        page = self.page
        frame = self._open_uplink()
        self._set(frame, starts="", duration="2h")
        page.wait_for_function(_SHUT, timeout=5000)
        self.assertIsNotNone(app_module.status_tree.maintenance_entry("/uplink"))
