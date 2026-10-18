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

#: A sandbox pins one browser build; a Playwright from the lock may expect another,
#: so the one that is there is what runs (as ``tests/sweep_contrast.py`` does).
#: Without it this file launched Playwright's own revision and skipped where the
#: other browser files ran.
_SANDBOX_CHROMIUM = Path("/opt/pw-browsers/chromium-1194/chrome-linux/chrome")

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
            cls.browser = cls.playwright.chromium.launch(
                executable_path=(str(_SANDBOX_CHROMIUM) if _SANDBOX_CHROMIUM.is_file()
                                 else None))
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
                    # it without submitting a preference, scroll it to its last
                    # choice — the last look's, below the layout's — and prove
                    # that choice is reachable inside the menu's own bounded
                    # scrollport.
                    menu = page.evaluate(
                        """
                        () => {
                          const panel = document.querySelector('.ls-menu__panel');
                          panel.classList.add('show');
                          panel.scrollTop = panel.scrollHeight;
                          const choices = panel.querySelectorAll('input[type=radio]');
                          const choice = choices[choices.length - 1].closest('label');
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

    def test_an_unstyled_bar_keeps_its_height_on_a_short_window(self):
        # Without Bootstrap's stylesheet the settings panel stands in the bar's own
        # flow, and its cap was read from the height rail.js measures off the bar,
        # which the cap then changed: on a window too short for the panel the bar
        # grew and shrank twice a second, and the page under a pointer with it
        # (`.ls-menu__panel.show` in overview.css). A phone, where the rail gives
        # way and the sections join the bar, and a short desk window.
        for width, height in ((360, 700), (1200, 600)):
            page = self.browser.new_page()
            try:
                page.set_viewport_size({"width": width, "height": height})
                aborted = _make_cdn_deterministically_unavailable(page)
                self._open_fixture(page, "two_equal_large_roots", rail_script=True)
                self.assertIn(_BOOTSTRAP_CSS, aborted)
                heights = set()
                for _ in range(10):
                    heights.add(page.evaluate(
                        "document.querySelector('.ls-bar')"
                        ".getBoundingClientRect().height"))
                    page.wait_for_timeout(100)
                with self.subTest(width=width, height=height):
                    self.assertEqual(len(heights), 1, sorted(heights))
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
                  const choices = panel.querySelectorAll('input[type=radio]');
                  const choice = choices[choices.length - 1].closest('label');
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

    def test_an_open_editor_slides_beneath_the_bar(self):
        # A line's editor stands in the flow (ADR-0104), so it scrolls under
        # the sticky bar like the line it belongs to; the panel it replaces
        # was anchored over the page and had to be kept beneath the bar by
        # its layer.
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
                  const setters = [...document.querySelectorAll('.reason-pin')];
                  const setter = setters[setters.length - 1];
                  setter.open = true;
                  const editor = setter.querySelector('.rule-block');
                  const barHeight = bar.getBoundingClientRect().height;
                  const top = editor.getBoundingClientRect().top + window.scrollY;
                  document.documentElement.style.scrollBehavior = 'auto';
                  window.scrollTo(0, top - barHeight / 2);
                  const box = editor.getBoundingClientRect();
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

    def test_a_lines_editor_opens_beneath_its_line(self):
        """ADR-0104 decisions 3 and 4, in paint: the pause mark is drawn on the
        seat the rail keeps for it at the line's end — beside the rail's own
        box, in its band — and the editor it opens stands under the line and
        moves the next line down, where the panel it replaces floated over
        the lines beneath."""
        page = self.browser.new_page()
        try:
            page.set_viewport_size({"width": 1200, "height": 900})
            self._open_fixture(
                page,
                "maintenance_editor_member_leaf",
                bootstrap=True,
            )
            measured = page.evaluate(
                """
                () => {
                  const setter = document.querySelector(
                      '.check-reason .reason-pin');
                  const line = setter.closest('.check-reason');
                  const next = line.nextElementSibling;
                  const mark = setter.querySelector('summary')
                      .getBoundingClientRect();
                  const rail = line.querySelector('.check-reason__rail')
                      .getBoundingClientRect();
                  const text = line.querySelector('.check-reason__body')
                      .getBoundingClientRect();
                  const lineBox = line.getBoundingClientRect();
                  const before = next.getBoundingClientRect().top;
                  setter.open = true;
                  const editor = setter.querySelector('.rule-block')
                      .getBoundingClientRect();
                  const after = next.getBoundingClientRect().top;
                  return {
                    markWidth: mark.width,
                    markOnSeat: mark.left >= rail.right - 1
                        && mark.right <= lineBox.right + 1
                        && mark.top >= rail.top - 1
                        && mark.bottom <= rail.bottom + 1,
                    markAtLineEnd: lineBox.right - mark.right,
                    textBottom: text.bottom,
                    editorTop: editor.top,
                    editorBottom: editor.bottom,
                    editorHeight: editor.height,
                    nextTop: after,
                    pushed: after - before,
                  };
                }
                """
            )
            self.assertGreater(measured["markWidth"], 10, measured)
            self.assertTrue(measured["markOnSeat"], measured)
            self.assertLess(measured["markAtLineEnd"], 12, measured)
            self.assertGreaterEqual(
                measured["editorTop"], measured["textBottom"] - 1, measured)
            self.assertGreater(measured["editorHeight"], 100, measured)
            self.assertGreaterEqual(
                measured["nextTop"], measured["editorBottom"], measured)
            self.assertGreaterEqual(
                measured["pushed"], measured["editorHeight"], measured)
        finally:
            page.close()

    def test_an_open_editor_does_not_widen_a_phones_page(self):
        # An open disclosure is a flex item in its block's head, and a flex
        # item keeps the width of what it holds: the node's editor stood 8px
        # past a 390px viewport and a line's 32px before it was told not to.
        page = self.browser.new_page()
        try:
            page.set_viewport_size({"width": 390, "height": 844})
            self._open_fixture(
                page,
                "maintenance_editor_member_leaf",
                bootstrap=True,
            )
            measured = page.evaluate(
                """
                () => {
                  const root = document.documentElement;
                  const closed = root.scrollWidth;
                  const widths = {};
                  for (const [name, selector] of [
                      ['node', '.rule-block--node .rule-block__edit'],
                      ['line', '.rule-block--line .rule-block__edit'],
                      ['new', '.check-reason .reason-pin']]) {
                    const editor = document.querySelector(selector);
                    editor.open = true;
                    widths[name] = root.scrollWidth;
                    editor.open = false;
                  }
                  return {viewport: root.clientWidth, closed, widths};
                }
                """
            )
            self.assertLessEqual(
                measured["closed"], measured["viewport"], measured)
            for name, width in measured["widths"].items():
                with self.subTest(editor=name):
                    self.assertLessEqual(width, measured["viewport"], measured)
        finally:
            page.close()

    def test_an_untouched_expiry_is_selected_when_its_field_is_entered(self):
        """ADR-0104 decision 5, where script runs: Edit starts in the note,
        the expiry's text is selected when its field takes focus while it is
        as it was filled, and one keystroke then replaces it."""
        page = self.browser.new_page()
        try:
            page.set_viewport_size({"width": 1200, "height": 900})
            self._open_fixture(
                page,
                "maintenance_editor_member_leaf",
                bootstrap=True,
            )
            page.wait_for_function(
                "document.documentElement.classList"
                ".contains('maintenance-edit-enhanced')")
            page.click(".rule-block--node .rule-block__edit > summary")
            # `toggle` is a task of its own, so the note takes focus a moment
            # after the click returns; a wait that never comes true fails
            page.wait_for_function(
                "document.activeElement !== null"
                " && document.activeElement.name === 'reason'")
            field = page.locator("#head-maintenance-duration")
            was = field.input_value()
            self.assertRegex(was, r"^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}$")
            field.click()
            # the selection is made after the click has placed its caret
            page.wait_for_function(
                "(() => { const f = document.activeElement; return f !== null"
                " && f.id === 'head-maintenance-duration' && f.value !== ''"
                " && f.selectionStart === 0"
                " && f.selectionEnd === f.value.length; })()")
            page.keyboard.type("3d")
            self.assertEqual(field.input_value(), "3d")
            # changed, it is somebody's text: entering it again selects nothing
            page.click("#head-maintenance-reason")
            field.click()
            page.wait_for_timeout(150)
            ends = page.evaluate(
                "() => { const f = document.activeElement; return "
                "[f.id, f.selectionStart, f.selectionEnd]; }")
            self.assertEqual(ends[0], "head-maintenance-duration")
            self.assertEqual(ends[1], ends[2])
            # Escape puts the block back as it was read, the field as filled
            page.keyboard.press("Escape")
            self.assertFalse(page.evaluate(
                "document.querySelector("
                "'.rule-block--node .rule-block__edit').open"))
            self.assertEqual(field.input_value(), was)
        finally:
            page.close()


class ActionRowTests(unittest.TestCase):
    """A node's actions stand in the head's row, shown always, and nothing is laid
    over the title any more (ADR-0127 decision 3).

    The rail of actions used to sit over the title's space on purpose and veil what
    it covered, quiet until the card was hovered; a real deployment's `+ Jira` chip
    once sat in the middle of the word "analysis" (ADR-0034). The head's row now
    holds the actions among its controls, before the state and the head's own
    icons: the title gives way to them, with an ellipsis, so no pixel of a title is
    ever under a chip, and the chips are shown at rest as the icons are. Measured
    in geometry, which is what the claim is about now, on the real Jinja pipeline
    with the demo package filling the real slot — the fixture sheet registers no
    filler, so it has no chip to collide with anything, which is exactly how the
    collision shipped.
    """

    browser = None
    playwright = None
    out: Path | None = None

    #: Long enough that the title would reach under the rail at card width, if
    #: anything let it.
    TITLE = "A very long human-friendly title that ought to ellipse"
    REASON = "analysis not readable: no status at all, and no freetext"

    @classmethod
    def setUpClass(cls):
        if sync_playwright is None:
            raise unittest.SkipTest("playwright is not installed")
        try:
            cls.playwright = sync_playwright().start()
            cls.browser = cls.playwright.chromium.launch(
                executable_path=(str(_SANDBOX_CHROMIUM) if _SANDBOX_CHROMIUM.is_file()
                                 else None))
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
                "action_chip_in_the_row",
                "a card whose action chip stands in its head's row", build))
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

    def _open(self):
        """One card on a phone's window, 360 pixels: narrow enough that the title
        has to give way to the chip, on a page that has stopped moving."""
        page = self.browser.new_page()
        page.set_viewport_size({"width": 360, "height": 700})
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
    def _geometry(page):
        return page.evaluate(
            """
            () => {
              const card = document.querySelector('.status-card');
              const head = card.querySelector('.status-card__head');
              const rail = head.querySelector('.node-controls > .node-actions');
              const chip = rail.querySelector('.node-action');
              const title = head.querySelector('.node-title');
              const name = head.querySelector('.status-card__name');
              const box = element => {
                const b = element.getBoundingClientRect();
                return {x: b.x, y: b.y, width: b.width, height: b.height,
                        right: b.right, bottom: b.bottom};
              };
              return {
                rail: box(rail), chip: box(chip), title: box(title), name: box(name),
                state: box(head.querySelector('.node-controls > .status-card__state')),
                icons: box(head.querySelector('.node-icons')),
                titleCut: title.scrollWidth > title.clientWidth,
                chipOpacity: getComputedStyle(chip).opacity,
                railPosition: getComputedStyle(rail).position,
              };
            }
            """
        )

    def test_the_title_gives_way_to_the_chip_and_nothing_lies_under_it(self):
        page = self._open()
        try:
            page.mouse.move(0, 0)
            geometry = self._geometry(page)
            # the premise: at card width the title would reach under the chip
            self.assertTrue(geometry["titleCut"])
            # so it ends before the chip, which stands in the row's flow, before the
            # state and the head's own icons
            self.assertLessEqual(geometry["title"]["right"],
                                 geometry["chip"]["x"] + 1)
            self.assertEqual(geometry["railPosition"], "static")
            self.assertLess(geometry["chip"]["right"], geometry["state"]["x"] + 1)
            self.assertLess(geometry["state"]["right"], geometry["icons"]["x"] + 1)
            # on the name's line, whole
            chip_middle = geometry["chip"]["y"] + geometry["chip"]["height"] / 2
            name_middle = geometry["name"]["y"] + geometry["name"]["height"] / 2
            self.assertLess(abs(chip_middle - name_middle),
                            geometry["name"]["height"] / 2)
        finally:
            page.close()

    def test_the_chip_is_shown_at_rest_and_the_same_under_the_pointer(self):
        page = self._open()
        try:
            page.mouse.move(0, 0)
            at_rest = self._geometry(page)
            self.assertEqual(at_rest["chipOpacity"], "1")
            page.mouse.move(at_rest["title"]["x"] + 4,
                            at_rest["title"]["y"] + at_rest["title"]["height"] / 2)
            page.wait_for_timeout(200)
            hovered = self._geometry(page)
            self.assertEqual(hovered["chipOpacity"], "1")
            self.assertEqual(hovered["chip"], at_rest["chip"])
            self.assertEqual(hovered["title"], at_rest["title"])
        finally:
            page.close()


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
