"""Chromium boundary checks for the stable-flow spans (ADR-0056).

The Python suite proves the model against itself; these two tests prove it
against paint, at the exact widths where the promises live.  They render the
fixture sheet's pages through the real templates and drive headless Chromium
at one-pixel resolution across a boundary.  Skipped wherever Playwright or a
Chromium binary is unavailable, so the ordinary gate does not grow a browser
dependency — but where a browser exists, the boundary claims are held to it.
"""
from __future__ import annotations

import shutil
import tempfile
import unittest
from pathlib import Path

try:  # pragma: no cover - environment probe
    from playwright.sync_api import sync_playwright
except ImportError:  # pragma: no cover
    sync_playwright = None  # type: ignore[assignment]

# `document.scrollHeight` is clamped to the viewport, so a page shorter than
# the window reports the window's height and a "did it grow?" assertion goes
# vacuously true (it did, on macOS, where tighter text fits the fixture under
# a 1200px window while it did not in CI).  Measure the grid and the card
# themselves — unclamped, and the actual subjects of every claim here.
_GRID_METRICS = """
() => {
  const grid = document.querySelector('#status-grid .status-grid');
  const cards = [...grid.children]
      .filter(c => c.classList.contains('status-card'));
  const mixed = cards.find(c => c.querySelector('[data-path="/zmix"]'));
  const nested = mixed ? mixed.querySelector('.node-children') : null;
  return {
    width: grid.getBoundingClientRect().width,
    grid: Math.round(grid.getBoundingClientRect().height),
    mixed: mixed ? Math.round(mixed.getBoundingClientRect().height) : 0,
    columns: nested === null ? 0 :
        getComputedStyle(nested).gridTemplateColumns.trim()
            .split(/\\s+/).length,
    heights: cards.map(c => Math.round(c.getBoundingClientRect().height)),
  };
}
"""


class ChromiumBoundaryTests(unittest.TestCase):
    """One-pixel walks across the widths the model publishes bands at."""

    browser = None
    playwright = None
    out: Path | None = None

    @classmethod
    def setUpClass(cls):
        if sync_playwright is None:
            raise unittest.SkipTest("playwright is not installed")
        try:
            cls.playwright = sync_playwright().start()
            cls.browser = cls.playwright.chromium.launch()
        except Exception as error:  # pragma: no cover - no browser here
            if cls.playwright is not None:
                cls.playwright.stop()
            raise unittest.SkipTest(
                f"no chromium available: {error}") from error
        from tests.render_ui_fixtures import (
            FIXTURES_BY_NAME,
            _localize_static,
            render_page,
        )
        # A unique directory per run: a fixed one under `var/` races a
        # concurrent run and can delete its artifacts mid-test.
        cls.out = Path(tempfile.mkdtemp(prefix="ls-browser-boundary-"))
        for name in ("two_equal_large_roots", "mixed_nested_flip"):
            html = render_page(FIXTURES_BY_NAME[name])
            (cls.out / f"{name}.html").write_text(
                _localize_static(html, cls.out))

    @classmethod
    def tearDownClass(cls):
        if cls.browser is not None:
            cls.browser.close()
        if cls.playwright is not None:
            cls.playwright.stop()
        if cls.out is not None:
            shutil.rmtree(cls.out, ignore_errors=True)

    def _metrics_at(self, page, name: str, grid_px: int) -> dict:
        """Load ``name`` with the grid resolved to exactly ``grid_px``.

        The page chrome (rail, paddings) between viewport and grid is an
        environment constant; measure it once at a probe width, then size the
        viewport so the grid lands on the requested pixel exactly.
        """
        page.set_viewport_size({"width": grid_px + 200, "height": 1200})
        page.goto((self.out / f"{name}.html").as_uri())
        page.wait_for_timeout(120)
        measured = page.evaluate(_GRID_METRICS)
        chrome = (grid_px + 200) - round(measured["width"])
        page.set_viewport_size({"width": grid_px + chrome, "height": 1200})
        page.wait_for_timeout(120)
        result = page.evaluate(_GRID_METRICS)
        assert round(result["width"]) == grid_px, (
            f"grid resolved {result['width']}px, wanted {grid_px}px")
        return result

    def test_the_outer_track_boundary_paints_flat(self):
        # The original flaw, held to real paint: at 1,714px auto-fill used to
        # snap five minimum tracks in and grow the page by nearly a screen.
        # With the band carrying its track count, one more pixel of viewport
        # must not change a single card height.
        page = self.browser.new_page()
        try:
            before = self._metrics_at(page, "two_equal_large_roots", 1713)
            after = self._metrics_at(page, "two_equal_large_roots", 1714)
            self.assertEqual(before["heights"], after["heights"])
            self.assertEqual(before["grid"], after["grid"])
        finally:
            page.close()

    def test_the_model_flip_matches_the_painted_flip_within_a_pixel(self):
        # [P2] With a full pixel of column tolerance the model promoted the
        # mixed card's fourth nested column a visible pixel before Chromium
        # did, so event-driven tests probed the wrong width.  The tolerance
        # is one tenth now; model and paint must flip within one pixel of
        # each other — and the painted rise itself is the documented limit
        # of the outer planner, not a defect.
        from little_sister import dashboard_layout as model
        from tests.ui_fixtures import FIXTURES_BY_NAME
        root = FIXTURES_BY_NAME["mixed_nested_flip"].build()
        cost = model._reason_cost(6)
        pieces = tuple(model._height_pieces(node, 7, cost)
                       for node in root.children)
        layout = model.dashboard_layout(root.children, max_depth=8)

        def band_at(tenths: int):
            band = None
            for width, tracks, plan in layout.breakpoints:
                if width > tenths:
                    break
                band = (tracks, plan)
            assert band is not None
            return band

        model_flip = None
        for px in range(1330, 1400):
            tracks, plan = band_at(px * 10)
            chosen = tracks or model._track_count(px * 10)
            page_cost, _ = model._plan_cost(pieces, px * 10, chosen, plan)
            if page_cost > 16:
                model_flip = px
                break
        assert model_flip is not None

        page = self.browser.new_page()
        try:
            paint_flip = None
            for px in range(model_flip - 2, model_flip + 3):
                metrics = self._metrics_at(page, "mixed_nested_flip", px)
                if metrics["columns"] >= 4:
                    paint_flip = px
                    break
            self.assertIsNotNone(
                paint_flip,
                f"chromium never painted the fourth column near "
                f"{model_flip}px")
            self.assertLessEqual(abs(paint_flip - model_flip), 1)
            # The card genuinely grows there — the limit is real, and it is
            # the card's own, not the outer selection's.  The mixed card is
            # the one that re-chunks, so it is the one measured; the grid
            # follows it because no other card changes.
            tall = self._metrics_at(page, "mixed_nested_flip", paint_flip)
            short = self._metrics_at(page, "mixed_nested_flip",
                                     paint_flip - 1)
            self.assertLess(short["columns"], tall["columns"])
            self.assertGreater(tall["mixed"], short["mixed"])
            self.assertGreater(tall["grid"], short["grid"])
        finally:
            page.close()


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
