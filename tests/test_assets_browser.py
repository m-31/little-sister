"""An open page that holds other files than the server links loads itself afresh
(ADR-0112) — held against a real browser.

That a page states a digest and every part it fetches states one is a response's to
show, and ``tests/test_hashed_assets.py`` holds it. What a running page does when
the two differ is a browser's: it reloads, once for a digest, and waits for an open
editor as every refresh does.

Served by a real server to headless Chromium, with the page's clock in the test's
hand. Skipped wherever Playwright or a Chromium binary is unavailable, so the
ordinary gate does not grow a browser dependency (``docs/testing-the-gui.md``,
Mode 5).
"""
from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any
from unittest import mock

from flask import request

from little_sister import app as app_module
from tests.test_pin_browser import _FRAGMENT, _BrowserCase, _wall

_NOON = datetime(2026, 10, 3, 12, 0, 0, tzinfo=UTC)

#: The digest of the files a process links after an upgrade.
_NEWER = "feedf00d"

#: What the page says of its files — nothing yet, while a document is on its way.
_SAYS = ("(document.querySelector('script[data-assets]') || {dataset: {}})"
         ".dataset.assets")
#: A mark on the document itself, which a reload takes with it and a swap does not.
_MARK = "window.lsLoadedOnce = true"
_MARKED = "window.lsLoadedOnce === true"
_GRID_MARK = ("document.querySelector('#status-grid .status-card')"
              ".dataset.drawn = 'before'")
_GRID_CHANGED = "window.sessionStorage.getItem('ls-test-grid-changed')"
_READY = ("document.documentElement.classList"
          ".contains('maintenance-edit-enhanced')")


class StaleAssetsBrowserTests(_BrowserCase):
    estate = staticmethod(_wall)

    def setUp(self) -> None:
        super().setUp()
        self.asked: list[str] = []
        self.page.on("request", lambda asked: (
            self.asked.append(asked.url) if _FRAGMENT.search(asked.url) else None))
        self.page.clock.install(time=_NOON)
        self.page.goto(f"{self.base}/status")
        self.page.wait_for_function(_READY)
        # short of the first tick, which is ten seconds in
        self.page.clock.pause_at(_NOON + timedelta(seconds=5))
        self.older = self.page.evaluate(_SAYS)
        self.page.evaluate(_MARK)
        self.page.evaluate(_GRID_MARK)

    # --- the hand ---------------------------------------------------------------------

    def _upgrade(self, says: Any = _NEWER) -> None:
        """From now on the server links other files — ``says`` their digest, or what
        answers for one."""
        patch = mock.patch.object(
            app_module.own_assets, "set_digest",
            side_effect=says if callable(says) else (lambda others=(): says))
        patch.start()
        self.addCleanup(patch.stop)

    def _tick(self) -> None:
        """One tick of the refresh, and its answer taken."""
        before = len(self.asked)
        with self.page.expect_response(_FRAGMENT):
            self.page.clock.run_for(10_000)
        self.assertEqual(len(self.asked), before + 1)
        self.page.wait_for_timeout(100)

    def _watch_the_grid(self) -> None:
        """Note every change of what the refresh swaps where a reload leaves it:
        in the session's storage."""
        self.page.evaluate(
            "new MutationObserver(function () {"
            " window.sessionStorage.setItem('ls-test-grid-changed', 'yes'); })"
            ".observe(document.getElementById('status-grid'), {childList: true})")

    def _marked(self) -> bool:
        self.page.wait_for_load_state("load")
        return bool(self.page.evaluate(_MARKED))

    def _swapped(self) -> bool:
        return self.page.locator("#status-grid [data-drawn]").count() == 0

    # --- what a page does -------------------------------------------------------------

    def test_a_page_whose_files_are_the_servers_is_swapped_and_stays(self) -> None:
        self._watch_the_grid()
        self._tick()
        self.assertEqual(self.page.evaluate(_GRID_CHANGED), "yes")
        self.assertTrue(self._marked())
        self.assertTrue(self._swapped())

    def test_a_page_that_holds_older_files_loads_itself_afresh(self) -> None:
        self.assertNotEqual(self.older, _NEWER)
        self._upgrade()
        self._tick()
        self.page.wait_for_function(f"{_SAYS} === '{_NEWER}'")
        self.assertFalse(self._marked())
        # and is then a page like any other: the next answer is swapped in
        self.page.wait_for_function(_READY)
        self.page.evaluate(_MARK)
        self.page.evaluate(_GRID_MARK)
        self._tick()
        self.assertTrue(self._marked())
        self.assertTrue(self._swapped())

    def test_the_answer_written_for_other_files_is_not_swapped_in(self) -> None:
        self._watch_the_grid()
        self._upgrade()
        self._tick()
        self.page.wait_for_function(f"{_SAYS} === '{_NEWER}'")
        self.assertFalse(self._marked())
        self.assertIsNone(self.page.evaluate(_GRID_CHANGED))

    def test_it_waits_for_an_open_editor(self) -> None:
        card = self.page.locator(".status-card").filter(
            has=self.page.locator('.status-card__head[data-path="/hemulen"]'))
        card.locator('.status-card__head [data-control="pin"]').click()
        self.page.wait_for_function(
            "document.activeElement !== null"
            " && document.activeElement.name === 'reason'")
        self.page.keyboard.type("half a sentence")
        self._upgrade()
        before = len(self.asked)
        self.page.clock.run_for(30_000)
        self.page.wait_for_timeout(100)
        self.assertEqual(len(self.asked), before)
        self.assertTrue(self._marked())
        self.assertEqual(self.page.evaluate("document.activeElement.value"),
                         "half a sentence")
        # the editor closes, and the next tick finds the difference
        self.page.keyboard.press("Escape")
        self._tick()
        self.page.wait_for_function(f"{_SAYS} === '{_NEWER}'")
        self.assertFalse(self._marked())

    def test_a_server_that_says_two_digests_in_turn_reloads_a_page_once(self) -> None:
        # Two workers either side of an upgrade: the page is drawn by the one that
        # still links the older files, its refresh answered by the other.
        older = self.older
        self._upgrade(lambda others=(): (
            _NEWER if request.args.get("fragment") else older))
        self._tick()
        self.page.wait_for_function(f"!({_MARKED})")
        self.page.wait_for_function(_READY)
        self.assertEqual(self.page.evaluate(_SAYS), older)
        self.page.evaluate(_MARK)
        self.page.evaluate(_GRID_MARK)
        self._tick()
        self.assertTrue(self._marked())
        # what it is sent is still shown: an old page with new readings, not a
        # page that stopped
        self.assertTrue(self._swapped())
