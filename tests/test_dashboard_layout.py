"""Stable-flow layout tests for ADR-0056, width-priced breakpoints included."""

import re
from pathlib import Path
from unittest import TestCase

from little_sister.dashboard_layout import (
    MAX_LAYOUT_TRACKS,
    FlowStep,
    allocate_spans,
    dashboard_layout,
    flow_profile,
    visible_node_count,
)
from little_sister.status import StatusCode
from little_sister.tree import StatusSnapshot, StatusTree

_CSS = (Path(__file__).resolve().parent.parent
        / "src" / "little_sister" / "static" / "css" / "overview.css")


def _snapshot(tree: StatusTree, path: str) -> StatusSnapshot:
    node = tree.snapshot(path)
    assert node is not None
    return node


def _profile(*steps: tuple[int, int]) -> tuple[FlowStep, ...]:
    return tuple(FlowStep(span, height) for span, height in steps)


def _band_at(layout, width_tenths: int) -> tuple[int, tuple[int, ...]]:
    """The (tracks, plan) band the client selects at a grid width in tenths.

    Bands are published in the model's own unit, so this is the client's
    comparison exactly: it scales its fractional measurement by ten rather
    than rounding a threshold.
    """
    band: tuple[int, tuple[int, ...]] | None = None
    for threshold, tracks, plan in layout.breakpoints:
        if threshold > width_tenths:
            break
        band = (tracks, plan)
    assert band is not None, f"no band applies at {width_tenths / 10}px"
    return band


def _plan_at(layout, width_tenths: int) -> tuple[int, ...]:
    return _band_at(layout, width_tenths)[1]


def _best_legal_page(pieces, width_tenths: int) -> int:
    """The shortest modeled page any **legal** track count offers here.

    Legal is the planner's own rule (:func:`_track_floor`), not every count:
    the floor exists to forbid track widths the responsive design never
    exhibits, so a candidate below it is not an alternative the planner
    passed over.
    """
    from little_sister import dashboard_layout as model
    return min(
        model._allocation_at(pieces, width_tenths, candidate)[0]
        for candidate in range(model._track_floor(width_tenths),
                               model._track_count(width_tenths) + 1)
    )


class ModelConstantsMirrorTheStylesheetTests(TestCase):
    """The five layout constants are hand-copied from overview.css; if the
    stylesheet moves, this is the red test instead of a slowly wrong layout."""

    @classmethod
    def setUpClass(cls):
        cls.css = _CSS.read_text()

    def _rule(self, selector: str) -> str:
        marker = selector + " {"
        self.assertIn(marker, self.css, f"stylesheet lost the {selector} rule")
        return self.css.split(marker, 1)[1].split("}", 1)[0]

    def test_track_width_and_outer_gap_match_the_status_grid(self):
        from little_sister import dashboard_layout as model
        rule = self._rule(".status-grid")
        match = re.search(r"minmax\(min\(100%, (\d+)px\), 1fr\)", rule)
        assert match is not None
        self.assertEqual(int(match.group(1)) * 10, model._TRACK_WIDTH)
        gap = re.search(r"gap: ([\d.]+)rem", rule)
        assert gap is not None
        self.assertEqual(round(float(gap.group(1)) * 160), model._OUTER_GAP)

    def test_nested_track_and_gap_match_the_node_children_grid(self):
        from little_sister import dashboard_layout as model
        marker = ".status-card .node-children:has(> .status-node:nth-of-type(2)) {"
        self.assertIn(marker, self.css)
        rule = self.css.split(marker, 1)[1].split("}", 1)[0]
        match = re.search(r"minmax\(min\(100%, (\d+)px\), 1fr\)", rule)
        assert match is not None
        self.assertEqual(int(match.group(1)) * 10, model._TRACK_WIDTH)
        gap = re.search(r"gap: ([\d.]+)rem", rule)
        assert gap is not None
        self.assertEqual(round(float(gap.group(1)) * 160), model._NESTED_GAP)

    def test_card_inset_matches_the_card_padding(self):
        from little_sister import dashboard_layout as model
        rule = self._rule(".status-card")
        match = re.search(r"padding: (\d+)px (\d+)px", rule)
        assert match is not None
        self.assertEqual(2 * int(match.group(2)) * 10, model._CARD_INSET)

    def test_node_inset_matches_the_box_padding_and_border(self):
        from little_sister import dashboard_layout as model
        rule = self._rule(".status-node")
        padding = re.search(r"padding: (\d+)px (\d+)px", rule)
        border = re.search(r"border: (\d+)px solid", rule)
        assert padding is not None and border is not None
        horizontal = 2 * (int(padding.group(2)) + int(border.group(1)))
        self.assertEqual(horizontal * 10, model._NODE_INSET)


class StableTopologyTests(TestCase):
    def test_depth_counts_only_renderable_levels(self):
        tree = StatusTree()
        tree.upsert("/root/branch/leaf", StatusCode.OK)
        node = _snapshot(tree, "root")
        self.assertEqual(visible_node_count(node, 0), 1)
        self.assertEqual(visible_node_count(node, 1), 2)
        self.assertEqual(visible_node_count(node, 2), 3)
        self.assertEqual(visible_node_count(node, 99), 3)

    def test_status_and_reason_content_do_not_change_a_profile(self):
        calm = StatusTree()
        hot = StatusTree()
        for tree, code in ((calm, StatusCode.OK), (hot, StatusCode.ERROR)):
            reason = None if code is StatusCode.OK else "a very long live reason"
            for name in ("alpha", "beta", "gamma", "delta"):
                tree.upsert(f"/root/branch/{name}", code, reason)
        self.assertEqual(
            flow_profile(_snapshot(calm, "root"), 8, reason_cap=6),
            flow_profile(_snapshot(hot, "root"), 8, reason_cap=6),
        )

    def test_status_churn_does_not_change_the_breakpoints(self):
        calm = StatusTree()
        hot = StatusTree()
        for tree, code in ((calm, StatusCode.OK), (hot, StatusCode.ERROR)):
            reason = None if code is StatusCode.OK else "boom"
            for name in ("alpha", "beta", "gamma", "delta"):
                tree.upsert(f"/quality/{name}", code, reason)
                tree.upsert(f"/stress/{name}", code, reason)
        self.assertEqual(
            dashboard_layout(_snapshot(calm, "").children, 8).breakpoints,
            dashboard_layout(_snapshot(hot, "").children, 8).breakpoints,
        )

    def test_reason_cap_prices_every_visible_node_stably(self):
        tree = StatusTree()
        for name in ("alpha", "beta", "gamma", "delta"):
            tree.upsert(f"/root/{name}", StatusCode.ERROR, "one current line")
        node = _snapshot(tree, "root")
        compact = flow_profile(node, 8, reason_cap=6)
        tall = flow_profile(node, 8, reason_cap=30)
        self.assertEqual(compact[0].height, 5)
        self.assertEqual(tall[0].height, 25)
        # The current one-line reasons do not enter either result; the configured
        # budget makes every one of the five possible reason hosts cost five rows.
        self.assertEqual(tall[1], FlowStep(3, 15))


class FlowProfileTests(TestCase):
    def test_profile_skips_width_that_cannot_open_a_nested_column(self):
        # At the 330px minimum this fixed-width diagnostic profile skips span
        # two; the width-priced breakpoints below reintroduce it exactly where
        # a real grid's wider tracks make it fit.
        tree = StatusTree()
        for name in ("alpha", "beta", "gamma", "delta"):
            tree.upsert(f"/root/{name}", StatusCode.OK)
        profile = flow_profile(_snapshot(tree, "root"), 8, reason_cap=6)
        self.assertEqual(tuple(step.span for step in profile), (1, 3, 4))
        self.assertNotIn(2, (step.span for step in profile))

    def test_depth_aware_profile_finds_a_later_deep_branch_step(self):
        tree = StatusTree()
        for name in ("alpha", "beta", "gamma", "delta"):
            tree.upsert(f"/root/shell/{name}", StatusCode.OK)
        profile = flow_profile(_snapshot(tree, "root"), 8, reason_cap=30)
        spans = tuple(step.span for step in profile)
        self.assertEqual(spans[0], 1)
        self.assertGreater(spans[1], 2)

    def test_a_linear_root_has_no_useful_wider_step(self):
        tree = StatusTree()
        tree.upsert("/root/a/b/c/d/e", StatusCode.ERROR, "boom")
        profile = flow_profile(_snapshot(tree, "root"), 8, reason_cap=30)
        self.assertEqual(tuple(step.span for step in profile), (1,))


class AllocateSpansTests(TestCase):
    def test_one_track_keeps_every_card_at_one(self):
        profiles = (
            _profile((1, 30), (3, 10)),
            _profile((1, 60), (3, 20)),
        )
        self.assertEqual(allocate_spans(profiles, 1), (1, 1))

    def test_equal_roots_take_only_a_whole_useful_step(self):
        profiles = (
            _profile((1, 30), (3, 20)),
            _profile((1, 30), (3, 20)),
        )
        self.assertEqual(allocate_spans(profiles, 3), (1, 1))
        self.assertEqual(allocate_spans(profiles, 4), (3, 1))

    def test_the_tallest_card_wins_because_the_row_is_as_tall_as_it(self):
        # Min-max: the shorter card's step has the better reduction per track
        # (8 versus 4), but spending there leaves the row exactly as tall as
        # before — the 66-row neighbor still owns the row height.
        profiles = (
            _profile((1, 30), (2, 22)),
            _profile((1, 66), (2, 62)),
        )
        self.assertEqual(allocate_spans(profiles, 3), (1, 2))

    def test_equal_roots_grow_alternately_not_one_page_wide_bar(self):
        # The measured failure of the pure gain-per-track objective: two equal
        # roots on a fourteen-track grid gave one root twelve tracks and the
        # other two.  Under min-max they take turns and end symmetric.
        profile = _profile((1, 30), (2, 16), (3, 11), (6, 5), (12, 3))
        self.assertEqual(allocate_spans((profile, profile), 14), (6, 6))

    def test_greater_reduction_per_track_breaks_a_height_tie(self):
        profiles = (
            _profile((1, 66), (3, 34)),
            _profile((1, 66), (3, 40)),
        )
        self.assertEqual(allocate_spans(profiles, 4), (3, 1))
        flipped = (profiles[1], profiles[0])
        self.assertEqual(allocate_spans(flipped, 4), (1, 3))

    def test_full_rows_stay_ordinary_and_last_row_spends_useful_spares(self):
        profile = _profile((1, 20), (2, 10), (4, 5))
        profiles = (profile,) * 5
        self.assertEqual(allocate_spans(profiles, 4), (1, 1, 1, 1, 4))

    def test_a_linear_root_leaves_spare_tracks_empty(self):
        profile = _profile((1, 40))
        self.assertEqual(allocate_spans((profile, profile), 8), (1, 1))

    def test_ties_are_deterministic_in_source_order(self):
        profile = _profile((1, 30), (2, 20))
        self.assertEqual(allocate_spans((profile, profile), 3), (2, 1))

    def test_invalid_inputs_are_rejected(self):
        valid = _profile((1, 3), (3, 1))
        with self.assertRaisesRegex(ValueError, "track_count"):
            allocate_spans((valid,), 0)
        with self.assertRaisesRegex(ValueError, "start"):
            allocate_spans((_profile((2, 1)),), 2)
        with self.assertRaisesRegex(ValueError, "rise"):
            allocate_spans((_profile((1, 2), (1, 1)),), 2)
        with self.assertRaisesRegex(ValueError, "fall"):
            allocate_spans((_profile((1, 2), (2, 2)),), 2)


def _live_equal_roots() -> StatusSnapshot:
    """The overview shape from the 2026-08-12 review: two equal teams."""
    tree = StatusTree()
    for team in ("quality", "stress"):
        tree.upsert(f"/{team}/github/actions", StatusCode.ERROR, "x")
        for band in ("critical", "error", "high", "low", "medium", "none",
                     "note", "warning"):
            tree.upsert(f"/{team}/github/code_scanning_alerts/{band}",
                        StatusCode.OK)
            tree.upsert(f"/{team}/github/security_advisories/{band}",
                        StatusCode.OK)
        for aspect in ("issues", "pull_requests", "sbom_check"):
            tree.upsert(f"/{team}/github/{aspect}", StatusCode.OK)
    for band in ("critical", "high", "informational", "low", "medium"):
        tree.upsert(f"/quality/wiz/{band}", StatusCode.OK)
    for account in ("backup", "develop", "infrastructure", "live"):
        tree.upsert(f"/stress/aws/{account}", StatusCode.ERROR, "denied")
    return _snapshot(tree, "")


def _nine_roots_with_trailing_chains() -> StatusSnapshot:
    """Eight leaf roots and one root whose sorted children end in two deep
    chains — the shape whose nested grid re-chunks worst on a column flip."""
    tree = StatusTree()
    for index in range(1, 9):
        tree.upsert(f"/r{index}/leaf", StatusCode.OK)
    for name in ("a", "b", "c", "d", "e"):
        tree.upsert(f"/zz/{name}", StatusCode.OK)
    for name in ("y", "z"):
        chain = "/".join(f"d{depth}" for depth in range(5))
        tree.upsert(f"/zz/{name}/{chain}", StatusCode.OK)
    return _snapshot(tree, "")


def _fifteen_leaves_and_a_mixed_root() -> StatusSnapshot:
    """Fifteen leaf roots plus one root with chains of heights (3,3,3,7,5).

    The undodgeable case (Lex, 2026-08-12): inside an unchanged three-track
    band the mixed card's nested auto-fit flips three columns to four, the
    7-chain re-chunks beside the 5-chain instead of above it, and the fixed
    plan rises 16 -> 18 modeled rows — while every alternative track count
    costs 28 or more.  No outer choice exists; the rise is the card's own.
    """
    tree = StatusTree()
    for index in range(15):
        tree.upsert(f"/leaf{index:02d}", StatusCode.OK)
    for index, height in enumerate((3, 3, 3, 7, 5)):
        chain = "".join(f"/d{level}" for level in range(height - 1))
        tree.upsert(f"/zmix/c{index}{chain}", StatusCode.OK)
    return _snapshot(tree, "")


def _fractional_band_roots() -> StatusSnapshot:
    """Two branchy roots whose band starts land between whole pixels.

    At a 30-line reason budget this wall's first useful step is earned at
    1037.5px.  Published as a whole pixel that band arrived at 1038px, and
    across the 0.9px gap the wall carried a 105-row plan while a legal count
    offered 75 — a browser reports fractional widths, so the gap was real.
    """
    tree = StatusTree()
    for index, height in enumerate((2, 3)):
        chain = "".join(f"/d{level}" for level in range(height - 1))
        tree.upsert(f"/alpha/c{index}{chain}", StatusCode.OK)
    for index, height in enumerate((4, 2)):
        chain = "".join(f"/d{level}" for level in range(height - 1))
        tree.upsert(f"/beta/c{index}{chain}", StatusCode.OK)
    return _snapshot(tree, "")


def _twelve_linear_roots() -> StatusSnapshot:
    """Twelve linear roots of mixed heights (5,7,5,7,6,4,6,8,8,2,7,6).

    All profiles are one-step, so the whole wall used to ride one auto-fill
    band — and at 2,752px the eighth track re-chunked the heterogeneous
    heights into worse rows (15 -> 16 modeled rows) with nobody comparing
    before and after.
    """
    tree = StatusTree()
    for index, height in enumerate((5, 7, 5, 7, 6, 4, 6, 8, 8, 2, 7, 6)):
        chain = "".join(f"/d{level}" for level in range(height - 1))
        tree.upsert(f"/r{index:02d}{chain}", StatusCode.OK)
    return _snapshot(tree, "")


def _deep_branch_root() -> StatusSnapshot:
    """`stress -> aws -> four environments`, each a branch of branches."""
    tree = StatusTree()
    for environment in ("develop", "infrastructure", "production",
                        "staging"):
        for branch, leaves in (("cloudwatch", 3), ("ec2", 4),
                               ("lambda", 2), ("databases", 2)):
            for index in range(leaves):
                tree.upsert(
                    f"/stress/aws/{environment}/{branch}/leaf-{index}",
                    StatusCode.OK)
    tree.upsert("/quality/github/actions", StatusCode.ERROR, "x")
    return _snapshot(tree, "")


class WidthPricedBreakpointTests(TestCase):
    def test_equal_roots_split_two_and_two_at_a_real_four_track_grid(self):
        # The review's headline case: a 1635px grid resolves four tracks of
        # ~396px, where a two-track card really fits two nested columns.  The
        # minimum-priced model allocated [3, 1] here — one wide card beside a
        # 1949px tower — although [2, 2] painted 1137px/1137px.
        layout = dashboard_layout(_live_equal_roots().children, max_depth=4)
        self.assertEqual(_band_at(layout, 16350), (4, (2, 2)))

    def test_the_same_grid_at_its_330px_minimum_honestly_declines_span_two(self):
        # At exactly four minimum tracks a two-track card offers ~656px and two
        # nested columns need ~666px, so span two is genuinely useless there;
        # the width-priced plan spends the spare tracks on one root instead.
        layout = dashboard_layout(_live_equal_roots().children, max_depth=4)
        self.assertEqual(_band_at(layout, 13680), (4, (3, 1)))

    def test_a_one_pixel_wider_grid_keeps_the_four_wide_tracks(self):
        # The boundary snap (found live, 2026-08-12): at 1714px CSS auto-fill
        # adds a fifth track and every track collapses to the 330px minimum,
        # so the [2, 2] split physically loses its nested columns — the page
        # jumped from 1582px to 2567px for one pixel of extra viewport.  The
        # band now names its own track count, and the four wide tracks stay.
        layout = dashboard_layout(_live_equal_roots().children, max_depth=4)
        self.assertEqual(_band_at(layout, 17130), _band_at(layout, 17140))
        self.assertEqual(_band_at(layout, 17140), (4, (2, 2)))

    def test_a_wider_grid_never_shows_a_worse_modeled_page(self):
        # These fixtures contain no undodgeable inner re-chunk (the
        # fifteen-plus-one fixture below holds that class), so on them the
        # published page must never rise at all — and checking only at
        # published band starts is not enough, because the *fixed* active
        # plan can change cost inside an unchanged band.  So the active
        # band's fixed cost is evaluated immediately before and at **every
        # model event**, the only widths anything can change at.
        from little_sister import dashboard_layout as model
        for build, depth in ((_live_equal_roots, 4), (_deep_branch_root, 8),
                             (_nine_roots_with_trailing_chains, 8),
                             (_twelve_linear_roots, 8),
                             (_fractional_band_roots, 8)):
            root = build()
            cost = model._reason_cost(6)
            pieces = tuple(model._height_pieces(node, depth - 1, cost)
                           for node in root.children)
            layout = dashboard_layout(root.children, max_depth=depth)

            def active(width_tenths, breakpoints=layout.breakpoints):
                band = None
                for tenths, tracks, plan in breakpoints:
                    if tenths > width_tenths:
                        break
                    band = (tracks, plan)
                return band

            # Bands publish at the exact tenth that earns them, so each
            # event is probed at the tenth before it and at the tenth
            # itself — the client's own comparison, with nothing rounded.
            probes = sorted({
                width
                for event in model._band_events(pieces)
                for width in (event - 1, event)
                if width >= 1
            })
            previous = None
            for width in probes:
                band = active(width)
                if band is None:
                    continue
                tracks = band[0] or model._track_count(width)
                page, _total = model._plan_cost(pieces, width, tracks,
                                                band[1])
                with self.subTest(build=build.__name__, width=width):
                    if previous is not None:
                        self.assertLessEqual(page, previous)
                previous = page

    def test_the_incumbents_own_count_dodges_a_mid_band_column_flip(self):
        # The compact counterexample (Lex, 2026-08-12): nine roots, the ninth
        # ending in five short children and two deep chains.  At ~2,032px its
        # nested grid flips from five to six columns, the chains land in
        # separate rows, and the held plan rises 12 -> 17 modeled rows —
        # while the challenger floor, grown past the incumbent's own four
        # tracks, banned the same-count re-allocation that dodges the flip.
        # The published wall must not get taller for one more pixel.
        from little_sister import dashboard_layout as model
        root = _nine_roots_with_trailing_chains()
        cost = model._reason_cost(6)
        pieces = tuple(model._height_pieces(node, 7, cost)
                       for node in root.children)
        layout = dashboard_layout(root.children, max_depth=8)
        before = _band_at(layout, 20310)
        after = _band_at(layout, 20320)
        cost_before = model._plan_cost(
            pieces, 20310, before[0] or model._track_count(20310), before[1])
        cost_after = model._plan_cost(
            pieces, 20320, after[0] or model._track_count(20320), after[1])
        self.assertLessEqual(cost_after[0], cost_before[0])
        # The dodge is a re-span at the incumbent's own count, not a jump to
        # a different track count.
        self.assertEqual(after[0], before[0])
        self.assertNotEqual(after[1], before[1])

    def test_an_auto_fill_band_breaks_before_a_new_track_rechunks_worse(self):
        # The second counterexample (Lex, 2026-08-12): twelve linear roots of
        # mixed heights ride one auto-fill band, and at 2,752px the eighth
        # track re-chunks them 15 -> 16 modeled rows.  The seven-track hold
        # sat below the old `min(roots, auto-fill)` floor, which grew with
        # the viewport and disqualified exactly the counts holding the page.
        # Under the track-width floor the sweep pins an explicit seven-track
        # band through the harmful region and returns to auto-fill only when
        # a larger count genuinely ties or wins.
        from little_sister import dashboard_layout as model
        root = _twelve_linear_roots()
        layout = dashboard_layout(root.children, max_depth=8)
        self.assertEqual(layout.weights, (5, 7, 5, 7, 6, 4, 6, 8, 8, 2, 7, 6))
        self.assertEqual(_band_at(layout, 27510)[0], 0)     # auto, 7 tracks
        self.assertEqual(_band_at(layout, 27520)[0], 7)     # pinned through 8
        cost = model._reason_cost(6)
        pieces = tuple(model._height_pieces(node, 7, cost)
                       for node in root.children)
        for width, expected in ((27510, 15), (27520, 15)):
            band = _band_at(layout, width)
            tracks = band[0] or model._track_count(width)
            page, _total = model._plan_cost(pieces, width, tracks, band[1])
            self.assertEqual(page, expected)

    def test_a_fixed_plans_own_card_can_rise_and_nothing_can_dodge_it(self):
        # [P1] The limit of the outer planner, held still as a fixture: the
        # mixed card's nested auto-fit re-chunks at its own column flip, the
        # incumbent itself becomes taller, and every alternative track count
        # is worse — the modeled page rises 16 -> 18 and that rise is
        # *unavoidable*, not a selection failure.  The universal
        # "wider never gets taller" claim died on this shape; what the
        # selection promises instead is that the published band is never
        # worse than the best available choice at its width.
        from little_sister import dashboard_layout as model
        root = _fifteen_leaves_and_a_mixed_root()
        cost = model._reason_cost(6)
        pieces = tuple(model._height_pieces(node, 7, cost)
                       for node in root.children)
        layout = dashboard_layout(root.children, max_depth=8)
        band = _band_at(layout, 13590)
        self.assertEqual(band, _band_at(layout, 13600))  # same band spans it
        tracks = band[0] or model._track_count(13600)
        before, _ = model._plan_cost(pieces, 13580, tracks, band[1])
        after, _ = model._plan_cost(pieces, 13600, tracks, band[1])
        self.assertEqual((before, after), (16, 18))
        # The rise is unavoidable: no candidate holds the old page height.
        best = min(model._allocation_at(pieces, 13600, candidate)[0]
                   for candidate in range(1, model._track_count(13600) + 1))
        self.assertEqual(best, after)

    def test_randomized_walls_are_never_worse_than_the_best_legal_choice(self):
        # A seeded property sweep, probing both sides of every model event.
        # The invariant is deliberately NOT "never taller": a card's own
        # nested column flip can raise a fixed plan with no dodge in
        # existence (trial 9 contains one, as does the fifteen-plus-one
        # fixture).  What the selection promises is optimality **at every
        # width, not only where the page rose** — a flat-but-beatable plan
        # is just as much a planning failure as a rising one — and against
        # the counts the track-width floor actually permits, since a count
        # below it was never an alternative the planner passed over.
        # Deterministic; the seed is part of the fixture.
        import random

        from little_sister import dashboard_layout as model
        rng = random.Random(20260812)
        for trial in range(12):
            tree = StatusTree()
            for index in range(rng.randint(2, 14)):
                if rng.random() < 0.5:
                    chain = "".join(f"/d{level}"
                                    for level in range(rng.randint(1, 7)))
                    tree.upsert(f"/t{index:02d}{chain}", StatusCode.OK)
                else:
                    for child in range(rng.randint(2, 7)):
                        chain = "".join(f"/e{level}"
                                        for level in range(rng.randint(0, 3)))
                        tree.upsert(f"/t{index:02d}/c{child}{chain}",
                                    StatusCode.OK)
            root = _snapshot(tree, "")
            reason_cap = rng.choice((6, 6, 30))
            cost = model._reason_cost(reason_cap)
            pieces = tuple(model._height_pieces(node, 7, cost)
                           for node in root.children)
            layout = dashboard_layout(root.children, max_depth=8,
                                      reason_cap=reason_cap)

            def active(width_tenths, breakpoints=layout.breakpoints):
                band = None
                for tenths, tracks, plan in breakpoints:
                    if tenths > width_tenths:
                        break
                    band = (tracks, plan)
                return band

            probes = sorted({
                width
                for event in model._band_events(pieces)
                for width in (event - 1, event)
                if width >= 1
            })
            for width in probes:
                band = active(width)
                if band is None:
                    continue
                tracks = band[0] or model._track_count(width)
                page, _total = model._plan_cost(pieces, width, tracks,
                                                band[1])
                best = _best_legal_page(pieces, width)
                if page > best:
                    self.fail(
                        f"trial {trial}: published page {page} at "
                        f"{width / 10}px although a legal count offers "
                        f"{best}")

    def test_the_wall_never_stacks_into_page_wide_banners(self):
        # One enormous card is often the modeled-shortest page; the track
        # floor keeps a sparse row side by side anyway.
        layout = dashboard_layout(_live_equal_roots().children, max_depth=4)
        for tenths, tracks, _plan in layout.breakpoints:
            if tracks:
                with self.subTest(width=tenths / 10):
                    self.assertGreaterEqual(tracks, 2)

    def test_a_deep_branch_gets_the_step_the_minimum_pricing_hid(self):
        # `stress -> aws -> four environments`, each a branch of branches: the
        # review measured a 1763px -> 918px drop at span four that the fixed
        # 330px pricing skipped, because the fourth nested environment column
        # missed the minimum width by a hair.  At a real seven-track grid the
        # width-priced profile must contain a step at span four or less that
        # the minimum-priced profile at the same span count did not reach.
        root = _deep_branch_root()
        layout = dashboard_layout(root.children, max_depth=8)
        plan = _plan_at(layout, 24750)
        position = [child.name for child in root.children].index("stress")
        self.assertGreaterEqual(plan[position], 4)

    def test_bands_publish_the_exact_tenth_that_earns_them(self):
        # [P1] Bands used to publish the ceiling in whole pixels, leaving one
        # up to 0.9px late — nine times the column tolerance — against a
        # browser that measures fractionally.  Every band start must now be
        # a model event exactly, and selection at a fractional width must
        # already be optimal there rather than at the next whole pixel.
        from little_sister import dashboard_layout as model
        root = _fractional_band_roots()
        cost = model._reason_cost(30)
        pieces = tuple(model._height_pieces(node, 7, cost)
                       for node in root.children)
        layout = dashboard_layout(root.children, max_depth=8, reason_cap=30)
        events = set(model._band_events(pieces))
        starts = [width for width, _tracks, _plan in layout.breakpoints]
        self.assertTrue(set(starts) <= events,
                        "a band start is not a model event — it was rounded")
        # The fixture's fractional start, and the gap it used to open.
        self.assertIn(10375, starts)
        for tenths in (10374, 10375, 10379, 10380):
            band = _band_at(layout, tenths)
            tracks = band[0] or model._track_count(tenths)
            page, _total = model._plan_cost(pieces, tenths, tracks, band[1])
            with self.subTest(width=tenths / 10):
                self.assertLessEqual(page, _best_legal_page(pieces, tenths))
        self.assertEqual(_band_at(layout, 10375), _band_at(layout, 10379))
        self.assertNotEqual(_band_at(layout, 10374), _band_at(layout, 10375))

    def test_breakpoint_widths_rise_strictly_and_bands_differ(self):
        layout = dashboard_layout(_live_equal_roots().children, max_depth=4)
        widths = [width for width, _tracks, _plan in layout.breakpoints]
        self.assertEqual(widths, sorted(set(widths)))
        self.assertGreaterEqual(widths[0], 1)
        from itertools import pairwise
        for before, after in pairwise(layout.breakpoints):
            self.assertNotEqual(before[1:], after[1:])

    def test_every_published_span_fits_its_bands_own_tracks(self):
        from little_sister import dashboard_layout as model
        layout = dashboard_layout(_live_equal_roots().children, max_depth=4)
        for tenths, tracks, plan in layout.breakpoints:
            # A band start is already in tenths, the model's own unit.  This
            # test used to scale it again, so it asked about a viewport ten
            # times wider: at 1037.5px it compared against roughly thirty
            # tracks instead of three, and any illegal explicit count would
            # have passed it.
            ceiling = model._track_count(tenths)
            chosen = tracks or ceiling
            with self.subTest(width=tenths / 10):
                # An explicit count never exceeds what auto-fill could hold
                # at this width, so every track is at least 330px wide.
                self.assertLessEqual(chosen, ceiling)
                self.assertLessEqual(max(plan), chosen)
                self.assertLessEqual(sum(plan), max(chosen, len(plan)))


class DashboardLayoutTests(TestCase):
    def test_layout_builds_diagnostic_plans_and_width_breakpoints(self):
        tree = StatusTree()
        tree.upsert("/quality/a/b", StatusCode.OK)
        tree.upsert("/stress/a/b/c", StatusCode.ERROR, "boom")
        root = _snapshot(tree, "")
        layout = dashboard_layout(root.children, max_depth=8)
        self.assertEqual(layout.weights, (3, 4))
        self.assertEqual(len(layout.plans), MAX_LAYOUT_TRACKS)
        self.assertTrue(all(len(plan) == 2 for plan in layout.plans))
        # Two linear roots: one all-ones band riding auto-fill ("tracks 0"),
        # applying from the narrowest grid up.
        self.assertEqual(layout.breakpoints, ((1, 0, (1, 1)),))

    def test_view_depth_and_reason_cap_change_only_stable_inputs(self):
        tree = StatusTree()
        tree.upsert("/quality/a/b", StatusCode.OK)
        root = _snapshot(tree, "")
        self.assertEqual(dashboard_layout(root.children, 1).weights, (1,))
        self.assertEqual(dashboard_layout(root.children, 3).weights, (3,))
        self.assertEqual(
            dashboard_layout(root.children, 3, reason_cap=30).weights,
            (15,),
        )

    def test_eighty_linear_roots_ship_one_auto_fill_breakpoint(self):
        tree = StatusTree()
        for index in range(80):
            tree.upsert(f"/root-{index:02d}", StatusCode.OK)
        root = _snapshot(tree, "")
        layout = dashboard_layout(root.children, max_depth=8)
        self.assertEqual(len(layout.breakpoints), 1)
        tenths, tracks, plan = layout.breakpoints[0]
        self.assertEqual((tenths, tracks), (1, 0))
        self.assertEqual(plan, (1,) * 80)

    def test_bottom_up_pieces_match_the_reference_evaluation(self):
        # `_flow_height` walks the whole subtree at one width and stays as
        # the reference; `_height_pieces` merges children bottom-up for
        # speed (6.7s at ten thousand leaves before).  They must agree at
        # every width the model can be asked about.
        from little_sister import dashboard_layout as model
        root = _deep_branch_root()
        cost = model._reason_cost(6)
        for node in root.children:
            pieces = model._height_pieces(node, 7, cost)
            probes = {bound for bound, _height in pieces}
            probes |= {bound - 1 for bound in probes if bound > 1}
            probes |= set(range(1, model._MAX_CONTENT_WIDTH, 9973))
            for width in sorted(probes):
                with self.subTest(node=node.name, width=width):
                    self.assertEqual(
                        model._piece_height(pieces, width),
                        model._flow_height(node, 7, width, cost))

    def test_bottom_up_pieces_never_fall_back_to_the_subtree_walk(self):
        # The scaling cliff (0.4s at a thousand leaves, 6.7s at ten thousand)
        # came from evaluating `_flow_height` over the whole subtree at every
        # threshold.  A timing test cannot hold that door shut; this does:
        # the reference walk must not be reachable from the fast path at all.
        from unittest import mock

        from little_sister import dashboard_layout as model
        root = _deep_branch_root()
        cost = model._reason_cost(6)
        expected = model._height_pieces(root.children[0], 7, cost)
        with mock.patch.object(
                model, "_flow_height",
                side_effect=AssertionError(
                    "_height_pieces walked the subtree again")):
            self.assertEqual(
                model._height_pieces(root.children[0], 7, cost), expected)

    def test_the_layout_is_memoized_on_the_depth_limited_shape(self):
        from little_sister import dashboard_layout as model
        calm = StatusTree()
        hot = StatusTree()
        for tree, code in ((calm, StatusCode.OK), (hot, StatusCode.ERROR)):
            reason = None if code is StatusCode.OK else "boom"
            for name in ("alpha", "beta", "gamma"):
                tree.upsert(f"/root/{name}", code, reason)
        model._memo.clear()
        first = dashboard_layout(_snapshot(calm, "").children, 8)
        # Same shape, different statuses and reasons: the identical object.
        self.assertIs(first,
                      dashboard_layout(_snapshot(hot, "").children, 8))
        # A different view depth is a different shape.
        self.assertIsNot(first,
                         dashboard_layout(_snapshot(calm, "").children, 1))
        # A different reason budget is a different pricing.
        self.assertIsNot(
            first,
            dashboard_layout(_snapshot(calm, "").children, 8, reason_cap=30))
