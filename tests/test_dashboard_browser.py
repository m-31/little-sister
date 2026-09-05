"""Chromium checks for layout claims that only paint can prove.

The Python suite proves the stable-flow model against itself; the boundary
tests below prove it against paint, at the exact widths where its promises
live.  The chrome tests prove the separate claim that navigation stays
reachable while the document scrolls.  They render the fixture sheet's pages
through the real templates and drive headless Chromium.  Skipped wherever
Playwright or a Chromium binary is unavailable, so the ordinary gate does not
grow a browser dependency.  The two stable-flow boundary checks abort every CDN
request themselves, so their unstyled paint is deterministic; only a chrome
test whose Bootstrap prerequisite is directly unavailable skips.
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

_BOOTSTRAP_CSS = (
    "https://cdn.jsdelivr.net/npm/bootstrap@5.3.2/dist/css/bootstrap.min.css"
)
_BOOTSTRAP_JS = (
    "https://cdn.jsdelivr.net/npm/bootstrap@5.3.2/dist/js/bootstrap.bundle.min.js"
)


def _make_cdn_deterministically_unavailable(page) -> list[str]:
    """Abort every jsDelivr request and record what was aborted.

    A navigation that races a remote, render-blocking stylesheet can mix styled
    and unstyled measurements inside one boundary walk — and, for the paint
    checks further down, can relayout the page *between* two screenshots.
    """
    aborted: list[str] = []

    def abort(route) -> None:
        aborted.append(route.request.url)
        route.abort()

    page.route("**cdn.jsdelivr.net/**", abort)
    return aborted


class ChromiumBoundaryTests(unittest.TestCase):
    """One-pixel walks across the widths the model publishes bands at."""

    browser = None
    playwright = None
    out: Path | None = None
    bootstrap_css_available: bool | None = None
    bootstrap_css_error = "did not produce Bootstrap's navbar display"
    bootstrap_js_available: bool | None = None
    bootstrap_js_error = "did not define bootstrap.Dropdown"

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
        for name in ("two_equal_large_roots", "mixed_nested_flip",
                     "roots_80_mixed", "maintenance_editor_member_leaf"):
            html = render_page(FIXTURES_BY_NAME[name])
            (cls.out / f"{name}.html").write_text(
                _localize_static(html, cls.out))
        cls.bootstrap_css_available = None
        cls.bootstrap_js_available = None

    @classmethod
    def tearDownClass(cls):
        if cls.browser is not None:
            cls.browser.close()
        if cls.playwright is not None:
            cls.playwright.stop()
        if cls.out is not None:
            shutil.rmtree(cls.out, ignore_errors=True)

    @classmethod
    def _probe_bootstrap_css(cls) -> None:
        if cls.bootstrap_css_available is not None:
            return
        # Probe only the exact prerequisite, and only when a chrome test asks
        # for it. The stable-flow tests never invoke this probe. A fixture page
        # also loads unrelated CDN scripts; they must not participate here.
        from playwright.sync_api import Error as PlaywrightError
        probe = cls.browser.new_page()
        probe.set_default_timeout(15_000)
        try:
            probe.set_content('<nav id="bootstrap-probe" class="navbar"></nav>')
            try:
                probe.add_style_tag(url=_BOOTSTRAP_CSS)
                cls.bootstrap_css_available = probe.evaluate(
                    "getComputedStyle(document.querySelector("
                    "'#bootstrap-probe')).display === 'flex'"
                )
            except PlaywrightError as error:  # pragma: no cover - network probe
                cls.bootstrap_css_available = False
                cls.bootstrap_css_error = (
                    f"{_BOOTSTRAP_CSS}: {str(error).splitlines()[0]}"
                )
        finally:
            probe.close()

    @classmethod
    def _probe_bootstrap_js(cls) -> None:
        if cls.bootstrap_js_available is not None:
            return
        from playwright.sync_api import Error as PlaywrightError
        probe = cls.browser.new_page()
        probe.set_default_timeout(15_000)
        try:
            try:
                probe.add_script_tag(url=_BOOTSTRAP_JS)
                cls.bootstrap_js_available = probe.evaluate(
                    "typeof window.bootstrap?.Dropdown === 'function'"
                )
            except PlaywrightError as error:  # pragma: no cover - network probe
                cls.bootstrap_js_available = False
                cls.bootstrap_js_error = (
                    f"{_BOOTSTRAP_JS}: {str(error).splitlines()[0]}"
                )
        finally:
            probe.close()

    def _require_bootstrap(self, *, javascript: bool = False) -> None:
        self._probe_bootstrap_css()
        if not self.bootstrap_css_available:
            self.skipTest(
                f"Bootstrap CSS is unavailable: {self.bootstrap_css_error}")
        if javascript:
            self._probe_bootstrap_js()
            if not self.bootstrap_js_available:
                self.skipTest(
                    f"Bootstrap JavaScript is unavailable: "
                    f"{self.bootstrap_js_error}")

    def _open_fixture(
        self,
        page,
        name: str,
        *,
        bootstrap: bool = False,
        javascript: bool = False,
        rail_script: bool = False,
    ) -> None:
        if bootstrap or javascript:
            self._require_bootstrap(javascript=javascript)
        # A status fixture loads Floating UI after all content and chrome code.
        # Wait for our document and the exact conditions this test needs, not an
        # unrelated third-party request at the tail of the navigation.
        page.goto((self.out / f"{name}.html").as_uri(), wait_until="commit")
        target = (
            ".check-reason"
            if name == "maintenance_editor_member_leaf"
            else "#status-grid .status-grid"
        )
        page.wait_for_selector(target)
        if bootstrap:
            page.wait_for_function(
                "() => { const bar = document.querySelector('.ls-bar'); "
                "return bar !== null && getComputedStyle(bar).display "
                "=== 'flex'; }"
            )
        if javascript:
            page.wait_for_function(
                "typeof window.bootstrap?.Dropdown === 'function'")
        if rail_script:
            page.wait_for_function(
                "getComputedStyle(document.documentElement)"
                ".getPropertyValue('--ls-bar-height').trim().endsWith('px')"
            )

    def _metrics_at(self, page, name: str, grid_px: int) -> dict:
        """Load ``name`` with the grid resolved to exactly ``grid_px``.

        The page chrome (rail, paddings) between viewport and grid is an
        environment constant; measure it once at a probe width, then size the
        viewport so the grid lands on the requested pixel exactly.
        """
        page.set_viewport_size({"width": grid_px + 200, "height": 1200})
        self._open_fixture(page, name)
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
            aborted = _make_cdn_deterministically_unavailable(page)
            before = self._metrics_at(page, "two_equal_large_roots", 1713)
            after = self._metrics_at(page, "two_equal_large_roots", 1714)
            self.assertIn(_BOOTSTRAP_CSS, aborted)
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
            aborted = _make_cdn_deterministically_unavailable(page)
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
            self.assertIn(_BOOTSTRAP_CSS, aborted)
        finally:
            page.close()

    def test_chrome_stays_reachable_while_the_document_scrolls(self):
        page = self.browser.new_page()
        try:
            for layout in ("rail", "topbar"):
                with self.subTest(layout=layout):
                    page.set_viewport_size({"width": 1200, "height": 300})
                    self._open_fixture(
                        page,
                        "roots_80_mixed",
                        bootstrap=True,
                        javascript=True,
                        rail_script=True,
                    )
                    page.evaluate(
                        "layout => document.body.dataset.lsLayout = layout",
                        layout,
                    )
                    page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
                    page.wait_for_timeout(120)
                    measured = page.evaluate(
                        """
                        () => {
                          const bar = document.querySelector('.ls-bar');
                          const rail = document.querySelector('.ls-rail');
                          const settings = document.querySelector('#ls-settings');
                          const nav = document.querySelector('.ls-bar__nav');
                          const rect = element => {
                            const box = element.getBoundingClientRect();
                            return {top: box.top, bottom: box.bottom};
                          };
                          return {
                            scrollY: window.scrollY,
                            pageScroll: document.querySelector('.ls-page').scrollTop,
                            bar: rect(bar),
                            settings: rect(settings),
                            rail: rect(rail),
                            railDisplay: getComputedStyle(rail).display,
                            railOverflow: getComputedStyle(rail).overflowY,
                            railClient: rail.clientHeight,
                            railScroll: rail.scrollHeight,
                            nav: rect(nav),
                            navDisplay: getComputedStyle(nav).display,
                          };
                        }
                        """
                    )
                    self.assertGreater(measured["scrollY"], 0)
                    self.assertEqual(measured["pageScroll"], 0)
                    self.assertAlmostEqual(measured["bar"]["top"], 0, delta=1)
                    self.assertLessEqual(
                        measured["settings"]["bottom"], measured["bar"]["bottom"])
                    if layout == "rail":
                        self.assertEqual(measured["railOverflow"], "auto")
                        self.assertGreater(
                            measured["railScroll"], measured["railClient"])
                        self.assertAlmostEqual(
                            measured["rail"]["top"],
                            measured["bar"]["bottom"],
                            delta=1,
                        )
                        self.assertLessEqual(measured["rail"]["bottom"], 301)
                        about = page.evaluate(
                            """
                            () => {
                              const rail = document.querySelector('.ls-rail');
                              rail.scrollTop = rail.scrollHeight;
                              const item = rail.querySelector('[href="/about"]');
                              const box = item.getBoundingClientRect();
                              return {
                                itemBottom: box.bottom,
                                railBottom: rail.getBoundingClientRect().bottom,
                              };
                            }
                            """
                        )
                        self.assertLessEqual(
                            about["itemBottom"], about["railBottom"] + 1)
                        large_type = page.evaluate(
                            """
                            () => {
                              const rail = document.querySelector('.ls-rail');
                              rail.classList.add('is-expanded');
                              rail.style.fontSize = '2rem';
                              const item = rail.querySelector('.ls-rail__item');
                              item.focus();
                              const focus = getComputedStyle(item);
                              return {
                                overflowX: getComputedStyle(rail).overflowX,
                                client: rail.clientWidth,
                                scroll: rail.scrollWidth,
                                outline: focus.outlineStyle,
                                outlineOffset: focus.outlineOffset,
                              };
                            }
                            """
                        )
                        self.assertEqual(large_type["overflowX"], "hidden")
                        self.assertEqual(
                            large_type["scroll"], large_type["client"])
                        self.assertEqual(large_type["outline"], "solid")
                        self.assertEqual(
                            large_type["outlineOffset"], "-2px")
                    else:
                        self.assertEqual(measured["railDisplay"], "none")
                        self.assertNotEqual(measured["navDisplay"], "none")
                        self.assertLessEqual(
                            measured["nav"]["bottom"], measured["bar"]["bottom"])

                    # Keeping the settings trigger on screen is not enough on a
                    # short window: its menu is taller than this viewport. Show
                    # it without submitting a preference, scroll it to the last
                    # layout choice, and prove that choice is reachable inside
                    # the menu's own bounded scrollport.
                    menu = page.evaluate(
                        """
                        () => {
                          const panel = document.querySelector('.ls-menu__panel');
                          panel.classList.add('show');
                          panel.scrollTop = panel.scrollHeight;
                          const choice = panel.querySelector('[value="kiosk"]')
                              .closest('label');
                          const box = panel.getBoundingClientRect();
                          const item = choice.getBoundingClientRect();
                          return {
                            overflow: getComputedStyle(panel).overflowY,
                            client: panel.clientHeight,
                            scroll: panel.scrollHeight,
                            top: box.top,
                            bottom: box.bottom,
                            itemTop: item.top,
                            itemBottom: item.bottom,
                          };
                        }
                        """
                    )
                    self.assertEqual(menu["overflow"], "auto")
                    self.assertGreater(menu["scroll"], menu["client"])
                    self.assertGreaterEqual(menu["itemTop"], menu["top"] - 1)
                    self.assertLessEqual(menu["itemBottom"], menu["bottom"] + 1)
                    self.assertLessEqual(menu["bottom"], 301)
        finally:
            page.close()

    def test_css_fallback_keeps_the_rail_and_anchors_below_the_bar(self):
        page = self.browser.new_page()
        try:
            # The surface is server-rendered and its forms retain no-JS paths.
            # Block only the progressive measurement so this holds the CSS
            # fallback itself to the same clearance as the enhanced page.
            page.route("**/static/js/rail.js", lambda route: route.abort())
            page.set_viewport_size({"width": 1200, "height": 400})
            self._open_fixture(
                page,
                "maintenance_editor_member_leaf",
                bootstrap=True,
            )
            measured = page.evaluate(
                """
                () => {
                  const bar = document.querySelector('.ls-bar')
                      .getBoundingClientRect();
                  const rail = document.querySelector('.ls-rail');
                  window.scrollTo(0, 500);
                  const reasons = [...document.querySelectorAll('.check-reason')];
                  const reason = reasons[Math.floor(reasons.length / 2)];
                  reason.classList.add('is-focused');
                  reason.scrollIntoView({block: 'start'});
                  const reasonBox = reason.getBoundingClientRect();
                  const railStyle = getComputedStyle(rail);
                  const burgerBox = rail.querySelector('.ls-rail__burger')
                      .getBoundingClientRect();
                  return {
                    barBottom: bar.bottom,
                    barHeight: bar.height,
                    burgerTop: burgerBox.top,
                    reasonTop: reasonBox.top,
                    seededOffset: parseFloat(railStyle.top),
                    railPaddingTop: parseFloat(railStyle.paddingTop),
                    token: getComputedStyle(document.documentElement)
                        .getPropertyValue('--ls-bar-height').trim(),
                  };
                }
                """
            )
            self.assertNotEqual(measured["token"], "")
            self.assertGreaterEqual(
                measured["seededOffset"] + measured["railPaddingTop"],
                measured["barHeight"],
            )
            self.assertGreaterEqual(
                measured["burgerTop"], measured["barBottom"])
            self.assertGreaterEqual(
                measured["reasonTop"], measured["barBottom"] + 15)
        finally:
            page.close()

    def test_rail_tracks_the_rendered_bar_height(self):
        page = self.browser.new_page()
        try:
            page.set_viewport_size({"width": 1200, "height": 500})
            self._open_fixture(
                page,
                "roots_80_mixed",
                bootstrap=True,
                javascript=True,
                rail_script=True,
            )
            page.evaluate("window.scrollTo(0, 500)")
            before = page.evaluate(
                "document.querySelector('.ls-bar').getBoundingClientRect().height")
            page.evaluate(
                "document.querySelector('.ls-bar').style.paddingBottom = '3rem'")
            page.wait_for_timeout(120)
            measured = page.evaluate(
                """
                () => {
                  const bar = document.querySelector('.ls-bar').getBoundingClientRect();
                  const rail = document.querySelector('.ls-rail')
                      .getBoundingClientRect();
                  return {barTop: bar.top, barBottom: bar.bottom,
                          barHeight: bar.height, railTop: rail.top};
                }
                """
            )
            self.assertGreater(measured["barHeight"], before + 20)
            self.assertAlmostEqual(measured["barTop"], 0, delta=1)
            self.assertAlmostEqual(
                measured["railTop"], measured["barBottom"], delta=1)

            # On a wide top bar the nav and settings share the first row. The
            # budget is therefore the whole bar, even when a taller brand puts
            # the nav's top below the bar's top. This is the geometry that keeps
            # rail.js independent of Bootstrap's CSS breakpoint spelling.
            page.evaluate(
                """
                () => {
                  document.body.dataset.lsLayout = 'topbar';
                  const brand = document.querySelector('.ls-brand');
                  brand.style.paddingTop = '1.5rem';
                  brand.style.paddingBottom = '1.5rem';
                }
                """
            )
            page.wait_for_timeout(120)
            desktop = page.evaluate(
                """
                () => {
                  const bar = document.querySelector('.ls-bar')
                      .getBoundingClientRect();
                  const nav = document.querySelector('.ls-bar__nav')
                      .getBoundingClientRect();
                  const who = document.querySelector('.ls-bar__who')
                      .getBoundingClientRect();
                  return {
                    barHeight: bar.height,
                    navTop: nav.top,
                    whoBottom: who.bottom,
                    rowBudget: parseFloat(getComputedStyle(document.documentElement)
                        .getPropertyValue('--ls-bar-row-budget')),
                  };
                }
                """
            )
            self.assertLess(desktop["navTop"], desktop["whoBottom"])
            self.assertAlmostEqual(
                desktop["rowBudget"], desktop["barHeight"], delta=1)
        finally:
            page.close()

    def test_narrow_expanded_topbar_keeps_its_last_section_reachable(self):
        page = self.browser.new_page()
        try:
            page.set_viewport_size({"width": 800, "height": 300})
            self._open_fixture(
                page,
                "roots_80_mixed",
                bootstrap=True,
                javascript=True,
                rail_script=True,
            )
            page.evaluate(
                """
                () => {
                  document.body.dataset.lsLayout = 'topbar';
                  const brand = document.querySelector('.ls-brand');
                  brand.style.paddingTop = '1.5rem';
                  brand.style.paddingBottom = '1.5rem';
                  document.querySelector('.ls-bar__nav').classList.add('show');
                  window.scrollTo(0, document.body.scrollHeight);
                }
                """
            )
            page.wait_for_timeout(120)
            measured = page.evaluate(
                """
                () => {
                  const bar = document.querySelector('.ls-bar');
                  const nav = document.querySelector('.ls-bar__nav');
                  const box = bar.getBoundingClientRect();
                  nav.scrollTop = nav.scrollHeight;
                  const navBox = nav.getBoundingClientRect();
                  const whoBox = document.querySelector('.ls-bar__who')
                      .getBoundingClientRect();
                  const about = nav.querySelector('[href="/about"]')
                      .getBoundingClientRect();
                  const navMaxHeight = parseFloat(
                      getComputedStyle(nav).maxHeight);
                  return {
                    top: box.top,
                    bottom: box.bottom,
                    fixedBarHeight: box.height - navBox.height,
                    rowBudget: innerHeight - navMaxHeight,
                    navTop: navBox.top,
                    whoBottom: whoBox.bottom,
                    navBottom: navBox.bottom,
                    overflow: getComputedStyle(nav).overflowY,
                    client: nav.clientHeight,
                    scroll: nav.scrollHeight,
                    aboutTop: about.top,
                    aboutBottom: about.bottom,
                  };
                }
                """
            )
            self.assertAlmostEqual(measured["top"], 0, delta=1)
            self.assertLessEqual(measured["bottom"], 301)
            self.assertAlmostEqual(
                measured["rowBudget"], measured["fixedBarHeight"], delta=1)
            self.assertGreaterEqual(
                measured["navTop"], measured["whoBottom"])
            self.assertEqual(measured["overflow"], "auto")
            self.assertGreater(measured["scroll"], measured["client"])
            self.assertGreaterEqual(
                measured["aboutTop"], measured["navTop"] - 1)
            self.assertLessEqual(
                measured["aboutBottom"], measured["navBottom"] + 1)

            # The settings trigger is on the first row, not beneath the open
            # section list. Its dropdown therefore keeps the viewport below
            # that row rather than inheriting the expanded bar's tiny remainder.
            page.evaluate(
                "document.querySelector('.ls-bar__nav').scrollTop = 0")
            page.click("#ls-settings")
            menu = page.evaluate(
                """
                () => {
                  const panel = document.querySelector('.ls-menu__panel');
                  panel.scrollTop = panel.scrollHeight;
                  const choice = panel.querySelector('[value="kiosk"]')
                      .closest('label');
                  const box = panel.getBoundingClientRect();
                  const item = choice.getBoundingClientRect();
                  const maxHeight = parseFloat(
                      getComputedStyle(panel).maxHeight);
                  const hit = document.elementFromPoint(
                      item.left + item.width / 2,
                      item.top + item.height / 2);
                  return {
                    client: panel.clientHeight,
                    itemHeight: item.height,
                    rowBudget: innerHeight - maxHeight,
                    top: box.top,
                    bottom: box.bottom,
                    itemTop: item.top,
                    itemBottom: item.bottom,
                    visible: panel.contains(hit),
                  };
                }
                """
            )
            self.assertGreaterEqual(menu["client"], menu["itemHeight"])
            self.assertAlmostEqual(
                menu["rowBudget"], measured["fixedBarHeight"], delta=1)
            self.assertGreaterEqual(menu["itemTop"], 0)
            self.assertLessEqual(menu["itemBottom"], 301, menu)
            self.assertLessEqual(menu["bottom"], 301)
            self.assertTrue(menu["visible"])
        finally:
            page.close()

    def test_content_anchored_panels_slide_beneath_the_bar(self):
        page = self.browser.new_page()
        try:
            page.set_viewport_size({"width": 1200, "height": 500})
            self._open_fixture(
                page,
                "maintenance_editor_member_leaf",
                bootstrap=True,
            )
            measured = page.evaluate(
                """
                () => {
                  const bar = document.querySelector('.ls-bar');
                  const panels = [...document.querySelectorAll('.reason-pin__panel')];
                  const panel = panels[panels.length - 1];
                  panel.closest('.reason-pin').open = true;
                  const barHeight = bar.getBoundingClientRect().height;
                  const panelTop = panel.getBoundingClientRect().top + window.scrollY;
                  document.documentElement.style.scrollBehavior = 'auto';
                  window.scrollTo(0, panelTop - barHeight / 2);
                  const box = panel.getBoundingClientRect();
                  const hit = document.elementFromPoint(
                      box.left + Math.min(20, box.width / 2),
                      Math.max(box.top, 0) + 5);
                  return {
                    overlaps: box.top < bar.getBoundingClientRect().bottom,
                    barOwnsPoint: bar.contains(hit),
                  };
                }
                """
            )
            self.assertTrue(measured["overlaps"])
            self.assertTrue(measured["barOwnsPoint"])
        finally:
            page.close()


class ActionChipPaintTests(unittest.TestCase):
    """A chip laid over a title must not read through to it (ADR-0034).

    The head's action rail is positioned over the title's space on purpose — a
    chip is something to click, a title is a nicety (`.status-head__middle` in
    `overview.css`) — and a chip is deliberately transparent, inking in
    `currentColor` so it reads on every status fill. Together those two right
    decisions drew both sets of glyphs in the same pixels: a real deployment's
    `+ Jira` chip sat in the middle of the word "analysis" and neither could be
    read.

    The claim the fix makes is about **paint**, so it is measured in paint: the
    area the chips occupy is the same image whether the title is there or
    hidden, because the rail repaints the box's own fill underneath. The
    counterpart matters as much and is asserted beside it — at rest the same
    comparison must come out *different*, because a card that offers nothing to
    click keeps every pixel of its title. A test that could not tell those two
    apart would pass just as happily on a veil that is always on, or on a
    screenshot comparison that is blind.

    Both captures are **settled** first — see `_stable_screenshot`. A single
    capture can come back with a band Chromium has not rasterised yet, and that
    is what made the first version of this test fail about one run in five, on
    a machine whose fractional layout made the blank frame likelier. The blank
    band is white, so it reads exactly like a difference in what the veil
    covers; the pixels themselves were never in doubt.

    This builds its own page rather than reading one off the fixture sheet: the
    sheet registers no filler, so it has no chip to collide with anything, which
    is exactly how the collision shipped. The page is the real Jinja pipeline
    with the demo package filling the real slot.
    """

    browser = None
    playwright = None
    out: Path | None = None

    #: Long enough that the title's box reaches under the rail at card width —
    #: asserted, not assumed, by the first test below.
    TITLE = "A very long human-friendly title that ought to ellipse"
    REASON = "analysis not readable: no status at all, and no freetext"

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
        from little_sister import slots
        from little_sister.status import StatusCode
        from little_sister.tree import StatusTree
        from tests.demo_extension import node_action
        from tests.render_ui_fixtures import (
            Fixture,
            _localize_static,
            render_page,
        )
        from tests.ui_fixtures import _snapshot

        def build():
            tree = StatusTree()
            tree.upsert("/loadtest", StatusCode.ERROR, cls.REASON)
            tree.set_title("/loadtest", cls.TITLE)
            return _snapshot(tree)

        slots.register("node.actions", "tests.demo_extension",
                       "node_action.html", node_action)
        try:
            html = render_page(Fixture(
                "action_chip_over_title",
                "a card whose action chip lands on its title", build))
        finally:
            # a reset puts the library's own fillers back; the demo one goes
            slots.forget_fillers()
        cls.out = Path(tempfile.mkdtemp(prefix="ls-action-chip-"))
        (cls.out / "page.html").write_text(_localize_static(html, cls.out))

    @classmethod
    def tearDownClass(cls):
        if cls.browser is not None:
            cls.browser.close()
        if cls.playwright is not None:
            cls.playwright.stop()
        if cls.out is not None:
            shutil.rmtree(cls.out, ignore_errors=True)

    #: The chip's resting and revealed opacities, from `overview.css`. Waiting
    #: for "not 0" would catch the fade mid-flight and compare two screenshots
    #: taken at different opacities — a difference that is about the clock.
    SHOWN = "0.75"
    HIDDEN = "0"

    def _open(self):
        """One card at dashboard width, on a page that has stopped moving.

        Two screenshots taken a moment apart are only comparable if nothing
        relaid out between them, and this page has two ways to move after its
        first paint: a render-blocking stylesheet arriving from a CDN, and
        `rail.js` replacing the scriptless bar height with the measured one.
        Either one slides the card out from under a pointer that never moved,
        the chips fade, and the comparison silently becomes one about `:hover`.
        That is not hypothetical — it failed about one run in five before both
        were pinned down here.

        The clip has to be on screen as well: the header band puts the grid
        below the fold at any sane window height.
        """
        page = self.browser.new_page()
        page.set_viewport_size({"width": 420, "height": 700})
        aborted = _make_cdn_deterministically_unavailable(page)
        page.goto((self.out / "page.html").as_uri(), wait_until="commit")
        page.wait_for_selector(".status-card .node-action")
        page.wait_for_function(
            "() => getComputedStyle(document.documentElement)"
            ".getPropertyValue('--ls-bar-height').trim().endsWith('px')")
        self.assertIn(_BOOTSTRAP_CSS, aborted)
        page.eval_on_selector(
            ".status-card",
            "element => element.scrollIntoView({block: 'center'})")
        return page

    @staticmethod
    def _point_at_card(page):
        """Hover by coordinates, at the middle of the card's own body.

        Playwright's `hover` waits for the element to be *stable* and a status
        page never is — it carries a live countdown and re-measures its rail —
        so the actionability check times out on a card that is perfectly
        hoverable. The pointer only has to be inside the card: that is what the
        `:hover` rule asks for. The **middle**, not an edge, so that the pixel
        or two a browser may still shift cannot leave the pointer outside the
        card it is meant to be on.
        """
        point = page.evaluate(
            """
            () => {
              const box = document.querySelector('.status-card')
                  .getBoundingClientRect();
              return {x: box.x + box.width / 2,
                      y: Math.min(box.y + box.height / 2, innerHeight - 8)};
            }
            """
        )
        page.mouse.move(point["x"], point["y"])

    def _wait_for_chip(self, page, opacity: str):
        page.wait_for_function(
            "expected => getComputedStyle(document.querySelector("
            "'.status-card .node-action')).opacity === expected",
            arg=opacity)

    @staticmethod
    def _chip_opacity(page) -> str:
        return page.evaluate(
            "() => getComputedStyle(document.querySelector("
            "'.status-card .node-action')).opacity")

    @staticmethod
    def _geometry(page):
        return page.evaluate(
            """
            () => {
              const card = document.querySelector('.status-card');
              const rail = card.querySelector(
                  '.status-head__middle > .node-actions');
              const drawn = [...rail.querySelectorAll('.node-action')];
              const chips = drawn.map(c => c.getBoundingClientRect());
              const title = card.querySelector('.node-title');
              const box = element => {
                const b = element.getBoundingClientRect();
                return {x: b.x, y: b.y, width: b.width, height: b.height,
                        right: b.right};
              };
              const span = {
                x: Math.min(...chips.map(c => c.x)),
                y: Math.min(...chips.map(c => c.y)),
                right: Math.max(...chips.map(c => c.right)),
                bottom: Math.max(...chips.map(c => c.bottom)),
              };
              span.width = span.right - span.x;
              span.height = span.bottom - span.y;
              return {
                rail: box(rail), chip: span, title: box(title),
                fill: getComputedStyle(card).backgroundColor,
                veil: getComputedStyle(rail).backgroundImage,
                chipOpacity: getComputedStyle(drawn[0]).opacity,
              };
            }
            """
        )

    def _clip(self, geometry):
        """The pixels the chips occupy — the region the claim is about."""
        chip = geometry["chip"]
        return {"x": chip["x"], "y": chip["y"],
                "width": chip["width"], "height": chip["height"]}

    def _stable_screenshot(self, page, clip):
        """Capture the region until two consecutive frames agree.

        A capture can return a region Chromium has not rasterised yet — a band
        of blank canvas where the card's fill belongs, seen here on a page that
        had just been scrolled. It has nothing to do with what is being
        measured and everything to do with when the frame was taken, so the
        settle is two identical frames in a row. Five tries is many more than
        it has ever needed; never settling is a failure worth reporting as
        itself.
        """
        previous = page.screenshot(clip=clip)
        for _ in range(5):
            current = page.screenshot(clip=clip)
            if current == previous:
                return current
            previous = current
        raise AssertionError("the clipped region never stopped repainting")

    @staticmethod
    def _hide_title(page):
        page.eval_on_selector(
            ".status-card .node-title",
            "element => { element.style.visibility = 'hidden'; }")

    def test_the_title_runs_under_the_chips(self):
        # The premise of everything below: at card width the ellipsed title
        # reaches past the chip's left edge, so its glyphs are painted there.
        page = self._open()
        try:
            geometry = self._geometry(page)
            self.assertGreater(geometry["title"]["right"],
                               geometry["chip"]["x"] + 2)
        finally:
            page.close()

    def test_nothing_of_the_title_paints_inside_a_shown_chip(self):
        page = self._open()
        try:
            self._point_at_card(page)
            self._wait_for_chip(page, self.SHOWN)
            geometry = self._geometry(page)
            self.assertEqual(geometry["chipOpacity"], self.SHOWN)
            clip = self._clip(geometry)
            with_title = self._stable_screenshot(page, clip)
            self._hide_title(page)
            # The pointer has not moved, so the chips must still be shown. If
            # they are not, the page moved under them and the two screenshots
            # are of different states — a failure to report as itself rather
            # than as a difference in what the veil covers.
            self.assertEqual(self._chip_opacity(page), self.SHOWN)
            without_title = self._stable_screenshot(page, clip)
            self.assertEqual(with_title, without_title)
        finally:
            page.close()

    def test_a_card_at_rest_keeps_the_title_it_is_not_covering(self):
        # The same measurement, the opposite verdict: no chip is offered, so
        # nothing may be veiled — and a comparison that cannot see the title
        # here was proving nothing in the test above either.
        page = self._open()
        try:
            page.mouse.move(0, 0)
            self._wait_for_chip(page, self.HIDDEN)
            clip = self._clip(self._geometry(page))
            with_title = self._stable_screenshot(page, clip)
            self._hide_title(page)
            self.assertEqual(self._chip_opacity(page), self.HIDDEN)
            without_title = self._stable_screenshot(page, clip)
            self.assertNotEqual(with_title, without_title)
        finally:
            page.close()

    def test_the_veil_is_the_card_own_fill(self):
        # Not merely *some* opaque color: the fill the chip was already
        # sitting on, which is what keeps every measured ink pair unchanged.
        page = self._open()
        try:
            self._point_at_card(page)
            self._wait_for_chip(page, self.SHOWN)
            geometry = self._geometry(page)
            self.assertIn(geometry["fill"], geometry["veil"])
        finally:
            page.close()


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
