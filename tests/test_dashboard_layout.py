"""Stable-flow layout tests for ADR-0056, width-priced breakpoints included."""

import re
from pathlib import Path
from unittest import TestCase

from little_sister.checks.metadata import Stated
from little_sister.config import Config
from little_sister.dashboard_layout import (
    MAX_LAYOUT_TRACKS,
    FlowStep,
    Priced,
    allocate_spans,
    dashboard_layout,
    flow_profile,
    visible_node_count,
)
from little_sister.first_look import FirstLooks, draw
from little_sister.nodes import NodeMeta
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
    """The layout constants are hand-copied from overview.css; if the
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
        # two or more direct open nodes establish the nested grid (ADR-0127: an open
        # node stands directly in its level, a closed one inside a run)
        marker = (".status-card .node-children:has(> :is(.tree-node, .tree-solo)"
                  " ~ :is(.tree-node, .tree-solo)) {")
        self.assertIn(marker, self.css)
        rule = self.css.split(marker, 1)[1].split("}", 1)[0]
        match = re.search(r"minmax\(min\(100%, (\d+)px\), 1fr\)", rule)
        assert match is not None
        self.assertEqual(int(match.group(1)) * 10, model._TRACK_WIDTH)
        gap = re.search(r"gap: ([\d.]+)rem", rule)
        assert gap is not None
        self.assertEqual(round(float(gap.group(1)) * 160), model._NESTED_GAP)

    def test_the_chips_column_gap_matches_an_aligned_run(self):
        from little_sister import dashboard_layout as model
        rule = self._rule('body[data-ls-chip-runs="aligned"] .tree-run')
        gap = re.search(r"gap: [\d.]+rem ([\d.]+)rem", rule)
        assert gap is not None
        self.assertEqual(round(float(gap.group(1)) * 160), model._CHIP_GAP)

    def test_a_run_asks_its_own_column_how_many_it_holds(self):
        # A run with room for one column only wraps as it comes (backlog #91's note,
        # §2, 2026-10-17), and from two on stands in as many as fit, each a query on
        # the run's own width against its line height — one column and the gap, the
        # model's — with the stylesheet's fallback column the model's too.
        from little_sister import dashboard_layout as model
        rule = self._rule('body[data-ls-chip-runs="aligned"] .tree-run')
        self.assertIn("container-type: inline-size;", rule)
        self.assertIn("display: flex;", rule)
        height = re.search(r"line-height: calc\(var\(--chip-w, (\d+)ch\) \+ "
                           r"([\d.]+)rem\);", rule)
        assert height is not None, rule
        self.assertEqual(int(height.group(1)) * model._CHIP_CH,
                         model._CHIP_FALLBACK)
        self.assertEqual(round(float(height.group(2)) * 160), model._CHIP_GAP)
        # two columns from twice the line height less one gap, each further column a
        # line height more, up to the most tracks the planner plans
        two = "@container (width >= calc(2lh - 0.3rem)) {"
        self.assertIn(two, self.css)
        node = self.css.split(two, 1)[1].split("\n}\n", 1)[0]
        self.assertIn("flex: 1 1 var(--chip-w, 12ch);", node)
        self.assertIn(
            "max-width: calc((100cqi + 0.3rem) / var(--columns, 2) - 0.3rem);", node)
        found = [(int(lines), int(columns)) for lines, columns in re.findall(
            r"@container \(width >= calc\((\d+)lh - 0\.3rem\)\) \{ "
            r'body\[data-ls-chip-runs="aligned"\] \.tree-run > \.tree-node '
            r"\{ --columns: (\d+); \} \}", self.css)]
        self.assertEqual(found,
                         [(k, k) for k in range(3, model.MAX_LAYOUT_TRACKS + 1)])

    def test_a_chips_estimate_takes_its_anatomy_from_the_stylesheet(self):
        # The server's estimate of a chip before the script measures it (backlog
        # #91's note, §2, 2026-10-17): its padding and border, its cue and the cue's
        # margin, the counts' margin where its level counts, and its font, as the
        # stylesheet sizes them under the aligned look.
        from little_sister import dashboard_layout as model

        def alone(selector: str) -> str:
            marker = "\n" + selector + " {\n"
            self.assertEqual(self.css.count(marker), 1, selector)
            return self.css.split(marker, 1)[1].split("}", 1)[0]
        chip = alone(".tree-chip")
        padding = re.search(r"padding: 1px (\d+)px;", chip)
        border = re.search(r"border: (\d+)px solid", chip)
        size = re.search(r"font-size: ([\d.]+)rem;", chip)
        assert padding is not None and border is not None and size is not None
        self.assertEqual(2 * (int(padding.group(1)) + int(border.group(1))),
                         model.CHIP_EDGE_PX)
        self.assertEqual(round(float(size.group(1)) * 160), model._CHIP_EM)
        cue = re.search(r"width: ([\d.]+)em;", alone(".status-cue"))
        cue_margin = re.search(r"margin-right: ([\d.]+)em;", self._rule(
            'body[data-ls-chip-runs="aligned"] .tree-chip > .status-cue'))
        counts = re.search(r"margin-left: ([\d.]+)em;", self._rule(
            'body[data-ls-chip-runs="aligned"] .tree-chip > .tree-counts'))
        assert cue is not None and cue_margin is not None and counts is not None
        self.assertAlmostEqual(float(cue.group(1)) + float(cue_margin.group(1)),
                               model.CHIP_CUE_EM)
        self.assertAlmostEqual(float(counts.group(1)), model.CHIP_COUNTS_EM)

    def test_each_themes_letter_is_the_one_the_planner_counts(self):
        # The estimate's length reads `--ls-chip-letter` (backlog #91's note, §2,
        # 2026-10-18): the root's for the system's faces, and a theme drawn in a
        # face of its own restates it in its block — the planner's faces hold the
        # same letters, theme by theme, and no theme restates one the planner does
        # not know.
        from little_sister import dashboard_layout as model
        root = re.findall(r"^:root \{ --ls-chip-letter: ([\d.]+); \}$", self.css,
                          re.M)
        self.assertEqual([float(letter) for letter in root], [model.CHIP_LETTER])
        self.assertEqual(model.CHIP_FACE.letter, model.CHIP_LETTER)
        themed = {}
        for theme, block in re.findall(
                r'^body\[data-ls-theme="([a-z]+)"\] \{\n(.*?)^\}', self.css,
                re.M | re.S):
            letter = re.search(r"--ls-chip-letter: ([\d.]+);", block)
            if letter is not None:
                themed[theme] = float(letter.group(1))
        self.assertEqual(themed, {theme: face.letter
                                  for theme, face in model.CHIP_FACES.items()})
        self.assertEqual(themed, {"cyberpunk": 1.0})

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
        walked = AssertionError("_height_pieces walked the subtree again")
        with mock.patch.object(model, "_flow_height", side_effect=walked), \
                mock.patch.object(model, "_shape_height", side_effect=walked):
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


def _card(tree: StatusTree, path: str) -> StatusSnapshot:
    node = tree.snapshot(path)
    assert node is not None
    return node


class FirstLookPricingTests(TestCase):
    """The planner prices the page's first look (ADR-0128 decision 6): a closed node
    a chip in its level's run, each run its lines of chips at the level's width, a
    closed top-level card one row, and each node's own line budget — never a status,
    so what the failure budget opens moves no card."""

    def setUp(self):
        from little_sister import dashboard_layout as model
        self.model = model
        model._memo.clear()

    def test_a_chip_is_estimated_at_its_characters_and_its_chrome(self):
        # each character of a name and a count at 0.85 of a `0`, seven pixels; the
        # padding and border, 20 pixels; the cue and its margin, 1.15 em of the
        # chip's 12.8 pixels, and the counts' margin, half an em, where they stand
        from little_sister.dashboard_layout import (
            CHIP_FACE,
            chip_estimate,
            chip_face,
            chip_width,
        )
        self.assertEqual(chip_width(10, counts=False), round(10 * 59.5 + 200 + 147.2))
        self.assertEqual(chip_width(10, counts=True), round(10 * 59.5 + 200 + 211.2))
        self.assertEqual(chip_width(0, counts=False), 347)
        # in cyberpunk's monospace face each character is a whole `0` of 0.6 em,
        # 7.7 pixels (2026-10-18); every other theme draws in the system's faces
        mono = chip_face("cyberpunk")
        self.assertEqual(chip_width(10, counts=False, face=mono),
                         round(10 * 77 + 200 + 147.2))
        for theme in ("auto", "plain", "vivid", "pastel", "dark", "no such"):
            with self.subTest(theme=theme):
                self.assertEqual(chip_face(theme), CHIP_FACE)
        # and the same as the stylesheet's length, which the run's font resolves at
        # the theme's letter
        self.assertEqual(chip_estimate(10, counts=False),
                         "calc(10 * var(--ls-chip-letter) * 1ch + 20px + 1.15em)")
        self.assertEqual(chip_estimate(9, counts=True),
                         "calc(9 * var(--ls-chip-letter) * 1ch + 20px + 1.65em)")

    def test_a_closed_top_level_card_is_one_row(self):
        tree = StatusTree()
        for leaf in ("a", "b", "c", "d"):
            tree.upsert(f"/one/{leaf}", StatusCode.OK)
            tree.upsert(f"/two/{leaf}", StatusCode.OK)
        roots = _snapshot(tree, "").children
        self.assertEqual(dashboard_layout(roots, 8).weights, (5, 5))
        layout = dashboard_layout(roots, 8, priced=Priced(closed=frozenset({"/one"})))
        self.assertEqual(layout.weights, (1, 5))

    def test_closed_children_are_a_run_of_chips_and_nothing_beneath_is_priced(self):
        tree = StatusTree()
        for leaf in ("a", "b", "c", "d"):
            for deep in ("x", "y", "z"):
                tree.upsert(f"/card/{leaf}/{deep}", StatusCode.OK)
        card = _card(tree, "card")
        kids = frozenset(child.path for child in card.children)
        width = 3300                      # one ordinary track's content
        open_rows = self.model._flow_height(card, 7, width, 1)
        self.assertEqual(open_rows, 1 + 4 * 4)
        # four chips of eight characters share one line at that width
        priced = Priced(closed=kids, chip_w={"/card": 8 * self.model._CHIP_CH})
        self.assertEqual(self.model._flow_height(card, 7, width, 1, priced), 1 + 1)

    def test_a_run_takes_a_heading_row_for_each_line_of_chips(self):
        tree = StatusTree()
        for leaf in ("a", "b", "c", "d", "e"):
            tree.upsert(f"/card/{leaf}", StatusCode.OK)
        card = _card(tree, "card")
        priced = Priced(closed=frozenset(child.path for child in card.children),
                        chip_w={"/card": 10 * self.model._CHIP_CH})
        chip = 10 * self.model._CHIP_CH + self.model._CHIP_GAP
        for per_line, lines in ((1, 5), (2, 3), (4, 2), (5, 1)):
            width = per_line * chip - self.model._CHIP_GAP
            with self.subTest(per_line=per_line):
                self.assertEqual(
                    self.model._flow_height(card, 7, width, 1, priced), 1 + lines)
                # a tenth narrower, one chip fewer to a line
                self.assertEqual(
                    self.model._flow_height(card, 7, width - 1, 1, priced),
                    1 + -(-5 // max(1, per_line - 1)))

    def test_a_run_that_holds_one_column_wraps_as_it_comes(self):
        # Below two of its level's columns and their gap a run draws its chips at
        # their own widths, sharing lines (backlog #91's note, §2, 2026-10-17): eight
        # names of seven characters with their chips' room and two of thirty-four,
        # in a level whose columns are thirty-four wide. Each chip takes its own
        # width and the gap after it; a line holds what fits.
        tree = StatusTree()
        names = [f"dock_{letter}" for letter in "abcdefgh"] + ["quay_1", "quay_2"]
        for name in names:
            tree.upsert(f"/card/{name}", StatusCode.OK)
        card = _card(tree, "card")
        ch = self.model._CHIP_CH
        own = {f"/card/{name}": (34 if name.startswith("quay") else 7) * ch
               for name in names}
        priced = Priced(closed=frozenset(own), chip_w={"/card": 34 * ch}, chip_own=own)
        bound = 2 * 34 * self.model._CHIP_CH + self.model._CHIP_GAP
        # at 400 pixels: seven docks, then the eighth and a quay, then a quay
        self.assertEqual(self.model._flow_height(card, 7, 4000, 1, priced), 1 + 3)
        # from two columns on, the level's columns line the run up as before, two
        # to a line; a tenth short of them, eight docks, a quay and a quay
        self.assertEqual(self.model._flow_height(card, 7, bound, 1, priced), 1 + 5)
        self.assertEqual(
            self.model._flow_height(card, 7, bound - 1, 1, priced), 1 + 3)
        # and a chip whose own width is not given is as wide as its column
        without = Priced(closed=frozenset(own), chip_w={"/card": 34 * ch})
        self.assertEqual(self.model._flow_height(card, 7, 4000, 1, without), 1 + 10)

    def test_a_line_of_chips_is_full_where_their_widths_and_gaps_are(self):
        tree = StatusTree()
        for name in ("a", "b", "c", "d"):
            tree.upsert(f"/card/{name}", StatusCode.OK)
        card = _card(tree, "card")
        ch = self.model._CHIP_CH
        own = {f"/card/{name}": 10 * ch for name in ("a", "b", "c", "d")}
        priced = Priced(closed=frozenset(own), chip_w={"/card": 40 * ch}, chip_own=own)
        chip = 10 * self.model._CHIP_CH + self.model._CHIP_GAP
        # each chip's own width and the gap after it: four fit at exactly that
        # much, a tenth less leaves the fourth for a line of its own
        for per_line, lines in ((4, 1), (3, 2), (2, 2), (1, 4)):
            with self.subTest(per_line=per_line):
                self.assertEqual(self.model._flow_height(
                    card, 7, per_line * chip, 1, priced), 1 + lines)
        self.assertEqual(self.model._flow_height(card, 7, 4 * chip - 1, 1, priced),
                         1 + 2)
        self.assertEqual(self.model._flow_height(card, 7, 2 * chip - 1, 1, priced),
                         1 + 4)

    def test_boxes_beside_a_run_keep_every_track_that_fits(self):
        # A run spans every track of its level, so none is empty and the boxes
        # beside it keep the width of all the tracks that fit (measured in
        # Chromium): at four tracks two boxes each take a quarter, where without
        # the run they take half each.
        def card(beside: bool) -> StatusSnapshot:
            tree = StatusTree()
            for box in ("a", "b"):
                for leaf in ("x", "y"):
                    tree.upsert(f"/card/{box}/{leaf}", StatusCode.OK)
            if beside:
                tree.upsert("/card/c", StatusCode.OK)
            return _card(tree, "card")
        # wide enough for two boxes of two tracks each, and so for four tracks
        width = 2 * (2 * 3364 - 64 + 180) + 64
        self.assertEqual(self.model._nested_columns(width, 2), 2)
        self.assertEqual(self.model._nested_columns(width, 2, runs=True), 4)
        # alone, each box holds its two leaves side by side; beside the run each
        # box is one track wide and they stack, and the run is a line of its own
        alone = self.model._flow_height(card(False), 7, width, 1)
        beside = self.model._flow_height(card(True), 7, width, 1,
                                         Priced(closed=frozenset({"/card/c"})))
        self.assertEqual(alone, 1 + 2)
        self.assertEqual(beside, 1 + 3 + 1)

    def test_each_node_is_priced_at_its_own_line_budget(self):
        tree = StatusTree()
        tree.upsert("/card/a", StatusCode.OK)
        tree.upsert("/card/b", StatusCode.OK)
        roots = _snapshot(tree, "").children
        self.assertEqual(dashboard_layout(roots, 8).weights, (3,))
        priced = Priced(caps={"/card/a": 30})
        self.assertEqual(dashboard_layout(roots, 8, priced=priced).weights, (7,))

    def test_what_a_status_opens_or_closes_is_never_priced(self):
        # the failure budget's openings, and today's density, which closes a
        # quiet leaf by its status: the planner reads the configured look alone
        def wall(failing: bool):
            tree = StatusTree()
            for leaf in ("a", "b", "c", "d"):
                tree.upsert(f"/card/svc/{leaf}", StatusCode.OK, "in step")
            tree.upsert("/plain/x/one", StatusCode.OK)
            if failing:
                tree.upsert("/card/svc/b", StatusCode.ERROR, "down")
                tree.upsert("/plain/x/one", StatusCode.ERROR, "down")
            root = _snapshot(tree, "")
            looks = FirstLooks((), {"/card/svc": NodeMeta(look=Stated(chips=True))},
                               Config(), lambda _path: False)
            drawn = draw(root, looks)
            return root, drawn
        calm, calm_drawn = wall(failing=False)
        hot, hot_drawn = wall(failing=True)
        self.assertIn("/card/svc/b", hot_drawn.budget)
        self.assertIn("/plain/x/one", calm_drawn.closed)    # the density's chip
        self.assertEqual(calm_drawn.priced, hot_drawn.priced)
        priced = Priced(closed=calm_drawn.priced, chip_w={"/card/svc": 420})
        self.assertEqual(
            dashboard_layout(calm.children, 8, priced=priced).breakpoints,
            dashboard_layout(hot.children, 8, priced=Priced(
                closed=hot_drawn.priced, chip_w={"/card/svc": 420})).breakpoints)

    def test_the_memo_is_keyed_on_what_the_look_closes_and_costs(self):
        tree = StatusTree()
        for leaf in ("a", "b", "c"):
            tree.upsert(f"/card/{leaf}", StatusCode.OK)
        roots = _snapshot(tree, "").children
        priced = Priced(closed=frozenset({"/card/a"}), chip_w={"/card": 280})
        first = dashboard_layout(roots, 8, priced=priced)
        self.assertIs(first, dashboard_layout(roots, 8, priced=Priced(
            closed=frozenset({"/card/a"}), chip_w={"/card": 280})))
        self.assertIsNot(first, dashboard_layout(roots, 8))
        self.assertIsNot(first, dashboard_layout(roots, 8, priced=Priced(
            closed=frozenset({"/card/a"}), chip_w={"/card": 2800})))
        self.assertIsNot(first, dashboard_layout(roots, 8, priced=Priced(
            closed=frozenset({"/card/a"}), chip_w={"/card": 280},
            caps={"/card/b": 30})))
        self.assertIsNot(first, dashboard_layout(roots, 8, priced=Priced(
            closed=frozenset({"/card/a"}), chip_w={"/card": 280},
            chip_own={"/card/a": 210})))

    def test_bottom_up_pieces_match_the_reference_with_closed_levels(self):
        # the same differential as the open wall's, over seeded walls whose
        # levels mix runs and boxes at every depth, each box its own budget
        import random
        rng = random.Random(20261017)
        for trial in range(10):
            tree = StatusTree()
            for index in range(rng.randint(1, 4)):
                for child in range(rng.randint(1, 9)):
                    for grand in range(rng.randint(0, 5)):
                        chain = "".join(f"/e{level}"
                                        for level in range(rng.randint(0, 2)))
                        tree.upsert(f"/t{index}/c{child}/g{grand}{chain}",
                                    StatusCode.OK)
                    if not rng.randint(0, 3):
                        tree.upsert(f"/t{index}/c{child}", StatusCode.OK)
            root = _snapshot(tree, "")
            paths: list[str] = []

            def walk(node, paths=paths):
                for kid in node.children:
                    paths.append(kid.path)
                    walk(kid)
            walk(root)
            closed = frozenset(path for path in paths
                               if path.count("/") > 1 and rng.random() < 0.4)
            priced = Priced(
                closed=closed,
                caps={path: rng.choice((0, 6, 12, 30)) for path in paths
                      if rng.random() < 0.3},
                chip_w={path: rng.randint(300, 3000) for path in paths},
                chip_own={path: rng.randint(250, 4500) for path in closed
                          if rng.random() < 0.9})
            for node in root.children:
                pieces = self.model._height_pieces(node, 7, 1, priced)
                probes = {bound for bound, _height in pieces}
                probes |= {bound - 1 for bound in probes if bound > 1}
                probes |= set(range(1, self.model._MAX_CONTENT_WIDTH, 7919))
                # and finely where a run that holds one column wraps its chips
                probes |= set(range(1, 9000, 37))
                for width in sorted(probes):
                    with self.subTest(trial=trial, node=node.name, width=width):
                        self.assertEqual(
                            self.model._piece_height(pieces, width),
                            self.model._flow_height(node, 7, width, 1, priced))
