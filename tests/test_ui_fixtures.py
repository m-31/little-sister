"""The UI-harness fixtures (testing-the-gui.md) double as test data.

Rendering an extreme tree through the real templates is the cheapest guard that
the dashboard survives it: a template error on a 200-line reason, a depth-8 tree
or the empty engine-down tree is a real defect, caught here rather than in a
screenshot. A few invariants keep each fixture meaningful.
"""
from __future__ import annotations

import json
import re
from datetime import UTC, datetime, timedelta
from html import unescape
from unittest import TestCase

from little_sister.status import StatusCode
from little_sister.tree import StatusTree
from tests import ui_fixtures
from tests.page_tree import parse
from tests.render_ui_fixtures import render_copy_page, render_page
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
                if fixture.detail:
                    self.assertIn("maintenance-edit.js", html)
                else:
                    self.assertIn('data-rendered-at="2026-07-20 12:00:00"', html)

    def test_overview_density_lists_every_host(self):
        html = self._render("hosts_ok_40")
        self.assertIn("host01", html)
        self.assertIn("host40", html)

    def test_eruption_keeps_all_twelve_linked_reasons(self):
        html = self._render("eruption_12_reasons")
        self.assertEqual(html.count("ci.example/runs/"), 12)
        self.assertIn("web", html)          # calm neighbor still present
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
        self.assertIn("under-maintenance", html)       # the pinned node, by name
        self.assertIn("planned kernel upgrade", html)  # and its pin's note
        self.assertIn("undefined", html)               # the never-reported node

    def test_a_deep_pin_is_surfaced_by_the_pill_and_a_pip(self):
        html = self._render("maintenance_deep_pin")
        self.assertIn('maintenance-pill__count">1<', html)
        self.assertIn("/nexus/disk/smart/bay-7", html)
        self.assertIn('data-pop-for="/nexus"', html)   # the card's pip

    def test_twelve_pins_fold_behind_the_cap(self):
        html = self._render("maintenance_many_pins")
        self.assertIn('maintenance-pill__count">12<', html)
        self.assertIn("+7 more", html)

    def test_no_fixture_pins_what_it_never_wrote(self):
        # a pin makes no node (ADR-0109 decision 4), so a fixture that pins a path
        # it did not write shows no pinned node, and nothing on its page says so
        tree = StatusTree()
        tree.upsert("/written", StatusCode.OK)
        tree.set_maintenance("/never/written", "planned",
                             expires_at=datetime.now(UTC) + timedelta(days=1))
        with self.assertRaisesRegex(AssertionError, "/never/written"):
            ui_fixtures._snapshot(tree)

    def test_reasons_graduated_keeps_the_largest_card(self):
        html = self._render("reasons_graduated")
        # every reason stays in the DOM (nothing is cut), even on the 20-reason card
        self.assertIn("reason line 20 of 20", html)
        # the cards carry the line budget; the show-all/collapse chevron is client-side
        self.assertIn("--reason-lines: 6", html)
        self.assertNotIn("show all", html)       # the bottom text link is gone

    def test_empty_tree_shows_the_engine_down_hint(self):
        html = self._render("empty_engine_down")
        self.assertIn("No checks", html)
        self.assertNotIn("Engine not started", html)   # disabled ≠ failed

    def test_engine_error_banner_renders_the_alert(self):
        html = self._render("engine_error_banner")
        self.assertIn("Engine not started", html)
        self.assertIn("unknown check type", html)
        self.assertIn("No checks", html)   # the empty grid beneath the banner

    def test_multi_front_incident_renders_through_copy_page(self):
        html = render_copy_page()
        # in the root's band, under its tabs, as the route draws it
        self.assertRegex(html, r'<a class="ls-views__tab is-current" href="/copy"')
        self.assertIn("little-sister status", html)
        self.assertIn("Copy Markdown", html)
        self.assertIn("Copy Rich HTML", html)
        self.assertIn("actions", html)
        self.assertNotIn("host01 ✅", html)  # calm leaves are pruned

    def test_maintenance_editor_fixture_has_read_and_edit_states(self):
        html = self._render("maintenance_editor_member_leaf")
        self.assertIn("<strong>Ada owns this</strong>", html)
        # the node's block and the pinned line's, each with its editor, and a
        # pause mark on the lines still to be pinned (ADR-0104)
        self.assertIn("Edit<span class=\"visually-hidden\"> this node's "
                      "maintenance</span>", html)
        self.assertIn("Edit<span class=\"visually-hidden\"> this line's "
                      "maintenance</span>", html)
        self.assertIn("Set maintenance for this line", html)
        self.assertIn("maintenance-reason-source", html)
        self.assertIn("&lt;script&gt;shown as text&lt;/script&gt;", html)


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

    def test_two_large_roots_keeps_both_high_count_subtrees(self):
        html = self._render("two_large_roots")
        self.assertIn(">quality</a>", html)
        self.assertIn(">stress</a>", html)
        self.assertIn("pull-requests", html)
        self.assertIn("dependency-alerts", html)
        self.assertIn("production", html)
        self.assertIn("staging", html)
        # chips off: every node drawn open
        self.assertNotIn('data-state="closed"', html)

    @staticmethod
    def _layout(html: str) \
            -> tuple[list[int], list[list[int]], list[list[object]]]:
        """The stable weights, useful steps and compact plan breakpoints."""
        weights = [int(value) for value in re.findall(
            r'data-layout-weight="(\d+)"', html)]
        steps = [
            [int(span) for span in value.split(",")]
            for value in re.findall(r'data-layout-steps="([\d,]+)"', html)
        ]
        match = re.search(r"data-layout-breakpoints='([^']+)'", html)
        assert match is not None, "the grid carries no plan breakpoints"
        return weights, steps, json.loads(unescape(match.group(1)))

    @staticmethod
    def _plan_at(breakpoints: list[list[object]],
                 width_tenths: int) -> list[int]:
        """The plan the client selects at a grid width in tenths of a pixel.

        Bands publish in the model's unit; the client scales its fractional
        measurement by ten rather than rounding a threshold.
        """
        plan: list[int] | None = None
        for threshold, _tracks, candidate in breakpoints:
            if int(threshold) > width_tenths:
                break
            assert isinstance(candidate, list)
            plan = [int(span) for span in candidate]
        assert plan is not None
        return plan

    def test_two_large_roots_get_the_calibrated_four_track_plan(self):
        weights, steps, breakpoints = self._layout(
            self._render("two_large_roots"))
        self.assertEqual(weights, [30, 66])
        # 13680 tenths is exactly four minimum-width tracks — the case.
        self.assertEqual(self._plan_at(breakpoints, 13680), [1, 3])
        self.assertTrue(all(profile[0] == 1 for profile in steps))
        self.assertTrue(all(2 not in profile for profile in steps))

    def test_two_equal_roots_get_the_split_the_width_actually_pays_for(self):
        weights, steps, breakpoints = self._layout(
            self._render("two_equal_large_roots"))
        self.assertEqual(len(weights), 2)
        self.assertEqual(weights[0], weights[1])
        # At exactly four 330px tracks a two-track card is ~10px too narrow
        # for two nested columns, so the diagnostic minimum-width steps skip
        # span two and the plan spends both spares on one root.  A real
        # 1635px four-track grid resolves ~396px tracks, where span two does
        # fit — so there the same topology splits 2 + 2, the arrangement the
        # minimum-priced model refused (it painted a 1949px tower instead).
        self.assertTrue(all(2 not in profile for profile in steps))
        self.assertEqual(self._plan_at(breakpoints, 13680), [3, 1])
        self.assertEqual(self._plan_at(breakpoints, 16350), [2, 2])

    def test_configured_reason_budget_changes_stable_height_not_live_text(self):
        normal = self._layout(self._render("two_equal_large_roots"))
        tall = self._layout(
            self._render("two_equal_large_roots_reason_cap_30"))
        self.assertTrue(all(high > low
                            for low, high in zip(normal[0], tall[0], strict=True)))
        self.assertIn("--reason-lines: 30",
                      self._render("two_equal_large_roots_reason_cap_30"))

    def test_eighty_roots_ship_one_breakpoint(self):
        weights, steps, breakpoints = self._layout(
            self._render("roots_80_mixed"))
        self.assertEqual(len(weights), 80)
        self.assertTrue(all(profile == [1] for profile in steps))
        self.assertEqual(len(breakpoints), 1)
        # One all-ones band riding auto-fill, from the narrowest grid up.
        self.assertEqual(breakpoints[0][:2], [1, 0])

    def test_chip_run_no_longer_disables_a_mixed_nested_grid(self):
        html = self._render("mixed_chip_branches")
        self.assertIn('class="tree-run"', html)
        self.assertGreaterEqual(html.count('class="status-node '), 3)
        page = parse(html)
        card = page.one("status-card")
        level = next(item for item in card.one("status-panel").children
                     if not isinstance(item, str) and item.has("tree-kids"))
        runs = [item for item in level.children
                if not isinstance(item, str) and item.has("tree-run")]
        self.assertTrue(runs)
        self.assertTrue(all(
            node.attrs.get("data-state") == "closed"
            for run in runs for node in run.all("tree-node")))
        self.assertGreaterEqual(sum(len(run.all("tree-node")) for run in runs), 2)

    def test_security_findings_flood_collapses_to_a_chip(self):
        # Layout (ADR-0056): the OK "informational" leaf that floods 150 findings is a
        # band of a card whose bands start as chips, as the wiz type proposes, so at
        # the overview it collapses to a single name+color chip — the skyscraper is
        # tamed and its findings live on the leaf's own page, not the card. Reasons ≠
        # bad status: an OK card no longer drowns the grid.
        html = self._render("security_findings_150")
        page = parse(html)
        band = next(node for node in page.all("tree-node")
                    if node.attrs.get("data-node", "").endswith("/informational"))
        self.assertEqual(band.attrs.get("data-state"), "closed")   # a chip
        self.assertIn("informational", band.one("tree-chip").text())   # names it
        # its findings ride in its box, hidden until found (ADR-0127 decision 1),
        # so they are off the overview's face and a click away without a request
        hold = band.one("tree-hold")
        self.assertEqual(hold.attrs.get("hidden"), "until-found")
        self.assertIn("End of Life Software", hold.text())
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

    def test_fixture_observation_times_are_pinned(self):
        # ADR-0027 put an observation time on the cards, so the sheet must pin it like
        # `_RENDERED_AT`: a build-time `now` would make every re-run — and every
        # machine — diff. The stamp carries an offset, so the rendered time of day is
        # the configured timezone's wherever the harness runs.
        html = self._render("hosts_ok_10")
        self.assertIn('<span class="status-card__time">11:59</span>', html)
        self.assertEqual(html.count('class="status-card__time"'), 10)

    def test_observation_times_fixture_contrasts_present_and_absent(self):
        # Three cards, one time: `solo` covers exactly one check and inherits its run
        # time; `pair` covers two, so no single value can answer for both; the
        # `never-run` mount has not reported, and registration is not an observation.
        html = self._render("observation_times")
        page = parse(html)
        names = [name.text() for name in page.all("status-card__name")]
        for name in ("solo", "pair", "never-run"):
            self.assertIn(name, names)
        # one in a card's head; the leaves beneath `pair` carry theirs in their
        # boxes, drawn beside their chips and hidden until found (ADR-0127)
        heads = page.all("status-card__head")
        self.assertEqual(sum(len(head.all("status-card__time")) for head in heads), 1)

    def test_the_series_leaf_draws_its_curve_with_both_breaks(self):
        # ADR-0092 on the sheet, as ADR-0096 and ADR-0097 amend it: one curve, the
        # four failed requests marked in its lane (and once more as the summary's
        # key), the night's sleep counted and left unmarked, the slow first answer
        # in the unit's second rung — and the readings left to the Series view
        html = self._render("series_http_leaf")
        self.assertEqual(html.count('<figure class="ls-curve"'), 1)
        self.assertEqual(len(re.findall(r'<line class="ls-curve__none"', html)), 5)
        self.assertIn("4 failed", html)
        self.assertIn("1 stretch without readings", html)
        self.assertIn("highest 1.9 s", html)
        self.assertNotIn("ls-readings", html)
        self.assertIn('href="/series/web/site#node"', html)

    def test_the_runs_leaf_draws_a_stem_for_each_run(self):
        # ADR-0111 on the sheet: one plot of runs under its measure, no line
        # joining them; each failure a hollow ring and a mark in the lane, each
        # warning the triangle — once more each as the summary's key — and the
        # runs that kept no verdict counted with theirs
        html = self._render("runs_stems_leaf")
        self.assertEqual(html.count('<figure class="ls-curve"'), 1)
        self.assertNotIn('class="ls-curve__line"', html)
        self.assertEqual(html.count('class="ls-curve__failed"'), 3 + 1)
        self.assertEqual(html.count('class="ls-curve__warned"'), 4 + 1)
        self.assertEqual(len(re.findall(r'<line class="ls-curve__none"', html)), 3)
        words = " ".join(re.sub(r"<[^>]+>", " ", html).split())
        self.assertIn("75 runs · newest 42m 45s · lowest 6m · highest 1h 5m · "
                      "3 failed · 4 warned · 9 without a verdict", words)
        # in the crowd of the last four days a passing run's head gives way: far
        # fewer heads than the 59 runs that passed
        heads = len(re.findall(r'<circle class="ls-curve__dot"', html))
        self.assertGreater(heads, 10)
        self.assertLess(heads, 30)
        self.assertIn('href="/series/batch/transform#node"', html)

    def test_the_runs_leaf_without_a_measure_draws_ticks(self):
        # the same runs as ticks: a plot as tall as its marks, titled by what they
        # are, a failure told by its ring alone and no lane beneath it
        html = self._render("runs_ticks_leaf")
        self.assertIn('<span class="ls-curve__title">Runs</span>', html)
        self.assertIn('<svg class="ls-curve__plot" viewBox="0 0 760 64"', html)
        self.assertNotIn('<line class="ls-curve__none"', html)
        self.assertNotIn('class="ls-curve__dot"', html)
        words = " ".join(re.sub(r"<[^>]+>", " ", html).split())
        self.assertIn("75 runs · 3 failed · 4 warned · 9 without a verdict", words)

    def test_the_refused_records_leaf_says_why_in_the_records_place(self):
        # ADR-0093 on the sheet: the line that lost its record stands with its own
        # tint and says why where the list would be; the engine's line names the
        # reading's subject; the record that passed is listed as ever
        html = self._render("refused_records_leaf")
        self.assertEqual(html.count('class="reason-refused'), 1)
        self.assertIn("Record refused: it is 2,811 bytes and the limit is 2,048",
                      html)
        self.assertIn("the record of octo/web was refused, and not graded", html)
        self.assertEqual(html.count('<dl class="reason-record'), 1)

    def test_the_series_branch_keeps_two_measures_on_two_axes(self):
        # never one chart with two scales: each measure is its own curve, and the
        # free-text unit labels its axis once
        html = self._render("series_host_branch")
        self.assertEqual(html.count('<figure class="ls-curve"'), 2)
        self.assertEqual(
            len(re.findall(r'<text class="ls-curve__unit"[^>]*>%</text>', html)), 1)
