"""The UI-harness fixtures (backlog #25) double as test data.

Rendering an extreme tree through the real templates is the cheapest guard that
the dashboard survives it: a template error on a 200-line reason, a depth-8 tree
or the empty engine-down tree is a real defect, caught here rather than in a
screenshot. A few invariants keep each fixture meaningful.
"""
from __future__ import annotations

from unittest import TestCase

from tests.render_ui_fixtures import render_page
from tests.ui_fixtures import FIXTURES, FIXTURES_BY_NAME


class FixtureRenderTests(TestCase):
    def _render(self, name: str) -> str:
        return render_page(FIXTURES_BY_NAME[name])

    def test_every_fixture_renders(self):
        # No fixture may raise a template error, and each yields a full page
        # carrying the harness's fixed server-seeded stamp.
        for fixture in FIXTURES:
            with self.subTest(fixture=fixture.name):
                html = render_page(fixture)
                self.assertIn("<!DOCTYPE", html)
                self.assertIn("</html>", html)
                self.assertIn('data-rendered-at="2026-07-20 12:00:00"', html)

    def test_overview_density_lists_every_host(self):
        html = self._render("hosts_ok_40")
        self.assertIn("host01", html)
        self.assertIn("host40", html)

    def test_eruption_keeps_all_twelve_linked_reasons(self):
        html = self._render("eruption_12_reasons")
        self.assertEqual(html.count("ci.example/runs/"), 12)
        self.assertIn("web", html)          # calm neighbour still present
        self.assertIn("s-error", html)      # the erupting card rolled up to ERROR

    def test_hundred_long_links_all_render(self):
        # the real deployment case: 100 reason lines, each a full link (each
        # reason is short enough to survive shorten(400), so the links stay intact)
        html = self._render("eruption_100_long_links")
        self.assertEqual(html.count("ci.example.com/andro-meda"), 100)
        self.assertIn("shard 100/100", html)   # the 100th entry rendered

    def test_code_reason_is_truncated_on_the_card(self):
        # The overview card runs each reason through shorten(400) before markdown,
        # so a 200-line code() reason renders as a <pre> cut mid-fence — the very
        # overflow the reason-overflow step must tame. The full block stays on the
        # leaf detail page.
        html = self._render("code_reason_200_lines")
        self.assertIn("<pre>", html)
        self.assertIn("module_1.py", html)      # early lines survive the cut
        self.assertNotIn("module_200.py", html)  # the tail is truncated on the card
        self.assertIn("…", html)                 # shorten's ellipsis

    def test_wide_host_renders_all_leaves(self):
        html = self._render("wide_host_15_leaves")
        self.assertIn("disk01", html)
        self.assertIn("disk15", html)

    def test_deep_tree_renders_to_depth_eight(self):
        html = self._render("deep_tree_depth_8")
        self.assertIn("level1", html)
        self.assertIn("level8", html)
        self.assertIn("eight levels down", html)

    def test_long_text_reaches_the_header(self):
        html = self._render("long_names_titles")
        # viewed at the branch, so the long title + about land in the header
        self.assertIn("ellipse", html)                 # from the long title
        self.assertIn("about", html)                   # the long about paragraph

    def test_idle_mix_shows_each_state(self):
        html = self._render("idle_maintenance_stale_mix")
        self.assertIn("connection refused", html)      # live ERROR
        self.assertIn("stale", html)                   # the short-frequency node
        self.assertIn("maintenance", html)             # the admin pin
        self.assertIn("undefined", html)               # the never-reported node

    def test_reasons_graduated_keeps_the_largest_card(self):
        html = self._render("reasons_graduated")
        # every entry stays in the DOM (nothing is cut), even on the 20-card
        self.assertIn("reason line 20 of 20", html)
        # …but the over-cap cards carry the entry cap (K = 6) and a "show all (N)"
        self.assertIn("show all (7)", html)
        self.assertIn("show all (20)", html)
        self.assertNotIn("show all (6)", html)   # exactly the cap renders whole

    def test_empty_tree_shows_the_engine_down_hint(self):
        html = self._render("empty_engine_down")
        self.assertIn("No checks", html)
        self.assertNotIn("Engine not started", html)   # disabled ≠ failed

    def test_engine_error_banner_renders_the_alert(self):
        html = self._render("engine_error_banner")
        self.assertIn("Engine not started", html)
        self.assertIn("unknown check type", html)
        self.assertIn("No checks", html)   # the empty grid beneath the banner


class WallFixtureTests(TestCase):
    """The "realistic wall" tier: extremes embedded in a populated overview."""

    def _render(self, name: str) -> str:
        return render_page(FIXTURES_BY_NAME[name])

    def test_eighty_roots_all_render(self):
        html = self._render("roots_80_mixed")
        self.assertIn("host01", html)
        self.assertIn("host80", html)
        self.assertIn("with-a-name-that-runs-long", html)   # ragged widths
        self.assertIn("stale", html)                        # the silent one aged
        self.assertIn("maintenance", html)                  # the admin pin

    def test_wall_incident_carries_every_extreme_at_once(self):
        html = self._render("wall_incident")
        self.assertIn("host16", html)                       # the calm majority
        self.assertEqual(html.count("ci.example/runs/"), 12)  # the eruption
        self.assertIn("<pre>", html)                        # the code() trace
        self.assertIn("stale", html)
        self.assertIn("maintenance", html)
        self.assertIn("undefined", html)                    # the idle node

    def test_security_findings_flood_collapses_to_a_chip(self):
        # Layout (#24): the OK "informational" leaf that floods 150 findings is a
        # quiet leaf, so at the overview it collapses to a single name+colour chip
        # — the skyscraper is tamed and its findings live on the leaf's own page,
        # not the card. Reasons ≠ bad status: an OK card no longer drowns the grid.
        html = self._render("security_findings_150")
        self.assertIn("leaf-chip", html)                     # the quiet leaves chipped
        self.assertIn("informational", html)                # the chip still names it
        self.assertNotIn("End of Life Software", html)      # findings off the overview
        self.assertNotIn("show all (150)", html)            # no reason block on a chip
        self.assertNotIn("s-error", html)                   # everything is OK
        # the engine heartbeat is lifted out of the grid into the status strip
        self.assertIn("ls-strip", html)
        self.assertIn("little-sister", html)                # shown in the strip

    def test_unbreakable_tokens_survive_the_shortener(self):
        # each token is far longer than any sane wrap point; the card must
        # break/scroll it, and shorten(400) must not have eaten the digest
        html = self._render("unbreakable_tokens")
        self.assertIn("artifacts.example/build/", html)
        self.assertIn("sha256:", html)
        self.assertIn("part33", html)                       # ident tail intact
