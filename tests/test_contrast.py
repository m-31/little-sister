"""The settings menu and the dead verdict hold AA in every gated theme.

ADR-0028 puts the accessibility bar above any picked swatch and says status
colour is verified by *measurement*, not by class presence. The faithful
measurement is a browser one — that is Mode 4 of the UI harness,
``tests/sweep_contrast.py`` — but a harness that needs Playwright cannot be the
thing that stops a regression landing, and one did land: the logout link kept
painting a raw ``--ls-danger`` red long after the dead verdict had moved onto an
ink that clears the bar, and nothing failed.

So this module measures what *can* be measured without a browser. Every value
comes out of the stylesheet's own token blocks — the inks, the hover wash and its
alpha, the canvas — and is folded exactly as the browser folds it. The only
numbers written down here are the two surfaces Bootstrap paints and we do not
(see :data:`DROPDOWN`), and those are re-verified by the Mode 4 sweep.

What that buys: swap an ink for a surface token, re-pick a theme's ink too dim,
add a theme without a danger-ink override, or change the hover wash so it lifts a
dark row toward its own ink — each of those moves a number here, and this fails.
What it cannot see: a surface we did not know about. Only the browser finds
those, which is why the harness exists too.

A second regression landed anyway, through a **different** hole, and
:data:`QUIET_BLOCK` plus ``test_no_rule_dims_an_ink_it_also_sets`` are the patch.
The logout link was a surface nobody had written down — the blind spot the
paragraph above already names. The silenced-reason line was not: it was a *listed
ink that a later declaration in its own rule dimmed*. This module folds alpha — it
does it for the hover wash — so it knew how; it simply never looked for ``opacity``
on a rule that sets a colour. The token was picked and measured undimmed at 7.6:1,
``opacity: 0.75`` composited it to 4.2, and nothing re-measured the result. So: a
rule may not dim an ink it also sets, and where an opacity applies inside a block,
the number measured here is the composite.
"""
import re
from pathlib import Path
from unittest import TestCase

import little_sister

STYLESHEET = (Path(little_sister.__file__).parent
              / "static" / "css" / "overview.css")

# The menu is a Bootstrap dropdown and **Bootstrap paints its surface**, not us:
# `--bs-dropdown-bg` is `--bs-body-bg`, so the rows sit on white in a light theme
# and on #212529 wherever `data-bs-theme="dark"` is set — including cyberpunk,
# whose `--ls-panel: #0c1420` never reaches the dropdown at all. Reasoning from
# `--ls-panel` here is how the logout link was mis-measured in the first place;
# these two came off the rendered page and `tests/sweep_contrast.py` re-checks
# them against whatever Bootstrap version is actually linked.
DROPDOWN = {"light": "#ffffff", "dark": "#212529"}

# And the same for a row that takes `color: inherit`: what it inherits is
# Bootstrap's `--bs-dropdown-color`, not our `--ls-ink`. The two happen to agree
# on a light canvas and do not on a dark one (#dee2e6 against our #e9edf1), so a
# row measured against `--ls-ink` would be measuring a colour nobody paints.
DROPDOWN_INK = {"light": "#212529", "dark": "#dee2e6"}

# (label, the token block to read, which dropdown surface). `auto` is the dark
# block a second time — the browser resolves it, and its light half is byte-for-
# byte the `:root` set `default` already covers.
THEMES = (
    ("default", None, "light"),
    ("vivid", 'body[data-ls-theme="vivid"]', "light"),
    ("pastel", 'body[data-ls-theme="pastel"]', "light"),
    ("dark", 'body[data-ls-theme="dark"]', "dark"),
    ("auto", 'body[data-ls-theme="auto"]', "dark"),
    ("cyberpunk", 'body[data-ls-theme="cyberpunk"]', "dark"),
)

# Cyberpunk is the declared fun theme (ADR-0028): measured and reported, never
# gated. Every other theme owes the bar.
UNGATED = {"cyberpunk"}
AA = 4.5

# The rows the menu actually renders: the ink each one paints with — a token of
# ours, or ``None`` for the inherited Bootstrap ink — and whether a pointer can
# wash it. `.ls-menu__item.is-disabled` carries a `:hover { background: none }`
# of its own (asserted below, so this stays true) and headings are not items.
MENU_ROWS = (
    (".ls-menu__logout", "--ls-danger-ink", True),
    (".ls-menu__item", None, True),                # color: inherit
    (".ls-menu__item.is-disabled", "--ls-muted", False),
    (".ls-menu__heading", "--ls-muted", False),
)

# The links page's own rows. These sit on **our** canvas rather than on a surface
# Bootstrap paints, which is what lets them be measured from the tokens alone. The
# button is the interesting one: it wears `btn btn-sm` for the shape and takes its
# ink from us precisely because `btn-outline-secondary` paints one grey on every
# canvas — 3.76:1 on the dark one, the logout link's mistake a second time.
# (row, its ink token, the token for the surface it lands on.)
PAGE_ROWS = (
    (".ls-links__recheck .btn", "--ls-ink", "--ls-canvas"),
    (".ls-links__recheck .btn:hover", "--ls-ink", "--ls-rail-active"),
    (".ls-links__probe", "--ls-muted", "--ls-canvas"),
    # the all-clear line borrows the status family's green, which is declared for
    # the ok *tint* — legitimate here only because it is measured on the canvas
    (".ls-links__probe--ok", "--ls-tint-ok-ink", "--ls-canvas"),
    (".ls-links__verdict", "--ls-muted", "--ls-canvas"),
    (".ls-links__verdict--dead", "--ls-danger-ink", "--ls-canvas"),
)

# The /about hero paints no surface of its own — it sits on the page canvas in
# every theme, which is what settled the light themes. What it does own is a
# **colour vocabulary**, and these are the two readings that carry meaning: a
# quiet signal (information, one step firmer than the furniture it rides) and a
# term the eyes are on (seen, and the only green on the page). The signal ink is
# a mix, so the weight is written down here as the sheet writes it.
SIGNAL_MIX = ("--ls-ink", "--ls-muted", 0.55)
HERO_ROWS = (
    (".ls-hero__signal.is-seen", "--ls-tint-ok-ink", "--ls-canvas"),
    (".ls-topic.is-seen", "--ls-tint-ok-ink", "--ls-canvas"),
    (".ls-hero__version", "--ls-muted", "--ls-canvas"),
)

# The silenced-reason block (ADR-0036), and why it is measurable from tokens at all:
# it paints its **own** surface. The same markup lands on our pale `--ls-tint-*` card
# fills, on our vivid `--ls-error` / `--ls-maintenance` fills (a node reporting its
# own problem is not `dim`) and on Bootstrap's `.alert-*` on the leaf page — three
# different backgrounds, one of them not ours. Inking onto that was the defect: 7.3:1
# on the pale ones, 2.7:1 on the vivid ones. With a tint of its own there is one pair
# to measure and it is ours.
#
# The rules named are the ones whose `opacity` reaches text inside the block. They
# are listed rather than assumed empty: the point of this entry is that a dim is part
# of the measurement, so a new one has to be written down here to be allowed at all.
QUIET_INK, QUIET_SURFACE = "--ls-tint-maintenance-ink", "--ls-tint-maintenance"
QUIET_RULES = (".status-node__reason.is-quiet", ".check-reason.is-quiet",
               ".reason-quiet-count", ".reason-quiet-note", ".reason-orphan",
               ".pin-banner", ".event-suppressed")


def _strip_comments(css):
    """The sheet without its commentary — which is most of it, and all prose."""
    return re.sub(r"/\*.*?\*/", "", css, flags=re.S)


def _blocks(css):
    """Every ``selector { … }`` body in the sheet, brace-matched, by selector.

    Nested rules count: ``auto``'s dark half lives inside a
    ``@media (prefers-color-scheme: dark)`` and is found by its own selector.
    """
    css = _strip_comments(css)
    out = {}
    for match in re.finditer(r"(?m)^\s*([^{}@\s][^{}]*?)\s*\{", css):
        depth, i = 1, match.end()
        while depth:
            if css[i] == "{":
                depth += 1
            elif css[i] == "}":
                depth -= 1
            i += 1
        out.setdefault(match.group(1).strip(), css[match.end():i - 1])
    return out


def _by_selector(blocks):
    """The same bodies, keyed by each **single** selector in a grouped rule.

    ``a:hover, a:focus-visible { … }`` is one block under one long key; a reader
    asking about `a:hover` should not have to know what it was grouped with.
    """
    table = {}
    for key, body in blocks.items():
        for part in key.split(","):
            table.setdefault(part.strip(), body)
    return table


def _tokens(blocks, selector):
    """A theme's effective palette: ``:root`` with the theme's overrides on top."""
    palette = dict(re.findall(r"(--ls-[\w-]+)\s*:\s*([^;]+);", blocks[":root"]))
    if selector is not None:
        palette.update(
            re.findall(r"(--ls-[\w-]+)\s*:\s*([^;]+);", blocks[selector]))
    return {name: value.strip() for name, value in palette.items()}


def _rgb(value):
    """A hex colour as three 0–255 floats. Only hex reaches here by design."""
    value = value.strip().lstrip("#")
    if len(value) == 3:
        value = "".join(c * 2 for c in value)
    return tuple(float(int(value[i:i + 2], 16)) for i in (0, 2, 4))


def _over(top, bottom, alpha):
    """``top`` at ``alpha`` composited over ``bottom`` — what color-mix does."""
    return tuple(top[i] * alpha + bottom[i] * (1 - alpha) for i in range(3))


def _luminance(rgb):
    def channel(c):
        c /= 255
        return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4
    red, green, blue = (channel(c) for c in rgb)
    return 0.2126 * red + 0.7152 * green + 0.0722 * blue


def _ratio(ink, surface):
    """The WCAG contrast ratio between two opaque colours."""
    light, dark = sorted((_luminance(ink), _luminance(surface)), reverse=True)
    return (light + 0.05) / (dark + 0.05)


class StylesheetTests(TestCase):
    """The parse this module measures from — kept honest against the sheet."""

    @classmethod
    def setUpClass(cls):
        cls.css = STYLESHEET.read_text(encoding="utf-8")
        cls.blocks = _blocks(cls.css)

    def test_the_hover_wash_is_a_token_at_a_known_alpha(self):
        # everything below folds this mix by hand, so read it rather than
        # assume it: a change to either the token or the alpha must land here
        rule = self.blocks[".ls-menu__item:hover"]
        self.assertRegex(
            rule,
            r"background:\s*color-mix\(in srgb, var\(--ls-menu-hover\) 8%,"
            r"\s*transparent\);")

    def test_a_disabled_row_takes_no_wash(self):
        # why MENU_ROWS marks it un-hoverable; the muted ink would not clear the
        # bar under the wash, and a disabled control is exempt only while it
        # genuinely never gets one
        self.assertIn("background: none",
                      self.blocks[".ls-menu__item.is-disabled:hover"])

    def test_the_logout_link_paints_from_a_token(self):
        # the regression itself: a literal here (or a surface token) is how the
        # link came to fail, and the measurements below would then be fiction
        self.assertEqual(self.blocks[".ls-menu__logout"].strip(),
                         "color: var(--ls-danger-ink);")

    def test_the_check_now_button_paints_from_our_tokens(self):
        # `btn btn-sm` for the shape, our ink for the colour: Bootstrap's outline
        # secondary is one grey on every canvas, and the measurements above are
        # fiction the moment this row takes its colour from it instead
        rules = _by_selector(self.blocks)
        for rule in (".ls-links__recheck .btn",
                     ".ls-links__recheck .btn:hover"):
            with self.subTest(rule=rule):
                self.assertIn("color: var(--ls-ink)", rules[rule])

    def test_every_theme_paints_opaque_navigation_chrome(self):
        # Sticky chrome now crosses the page as it scrolls. A translucent nav
        # token would composite against each card it passes and make every
        # contrast measurement above a moving target, so the surface itself is
        # part of the contract now. Keep it an explicit opaque colour in every
        # effective theme palette.
        for theme, selector, _ in THEMES:
            with self.subTest(theme=theme):
                nav = _tokens(self.blocks, selector)["--ls-nav"]
                self.assertRegex(nav, r"^#[0-9a-fA-F]{6}$")

    def test_no_rule_dims_an_ink_it_also_sets(self):
        """The patch for the hole the silenced-reason line went through.

        Every ink in this sheet was picked and measured **undimmed**. A rule that
        sets one and then declares an ``opacity`` composites it against whatever is
        behind, and the number that was checked is no longer the number on the
        screen: `.is-quiet` was 7.6:1 as a token and 4.2:1 as rendered, and nothing
        anywhere noticed. Dimming an ink is not forbidden in principle — but it has
        to be a **picked value on a known surface**, which means the rule stops
        setting the ink and the pair goes in a table above. Enforced structurally
        rather than by measurement because the surface is exactly what a rule like
        this does not pin down.
        """
        for selector, body in self.blocks.items():
            if not re.search(r"color:\s*var\(--ls-[\w-]+\)", body):
                continue
            with self.subTest(rule=selector):
                self.assertNotRegex(
                    body, r"(?m)^\s*opacity\s*:",
                    f"{selector} sets an --ls-* ink and dims it; the token was "
                    f"measured undimmed, so the rendered value is unmeasured")

    def test_the_silenced_reason_paints_its_own_surface(self):
        # the other half: measuring the pair above is only meaningful while the
        # block actually carries that background. Drop it and the ink lands on a
        # card fill again — or on Bootstrap's alert — and the numbers are fiction.
        rules = _by_selector(self.blocks)
        for rule in (".status-node__reason.is-quiet", ".check-reason.is-quiet",
                     ".reason-quiet-count", ".reason-orphan", ".pin-banner",
                     ".event-suppressed"):
            with self.subTest(rule=rule):
                self.assertIn(f"background: var({QUIET_SURFACE})", rules[rule])
                self.assertIn(f"color: var({QUIET_INK})", rules[rule])

    def test_no_raw_danger_token_survives(self):
        # `--ls-danger` was deleted rather than kept unused, precisely so no
        # later rule can reach for a red that cannot be text on any canvas
        self.assertNotRegex(self.css, r"--ls-danger\s*:")
        self.assertNotRegex(self.css, r"var\(--ls-danger\)")


class MenuContrastTests(TestCase):
    """Every menu row, at rest and under the pointer, on the real surface."""

    @classmethod
    def setUpClass(cls):
        cls.blocks = _blocks(STYLESHEET.read_text(encoding="utf-8"))

    def _measure(self, palette, token, canvas, hover):
        surface = _rgb(DROPDOWN[canvas])
        ink = _rgb(DROPDOWN_INK[canvas] if token is None else palette[token])
        if not hover:
            return _ratio(ink, surface)
        # `--ls-menu-hover: currentColor` means the row washes with its own ink;
        # a dark block re-homes it to a literal so the wash goes down, not up
        wash = palette["--ls-menu-hover"]
        tint = ink if wash == "currentColor" else _rgb(wash)
        return _ratio(ink, _over(tint, surface, 0.08))

    def test_every_row_clears_aa_in_every_gated_theme(self):
        for theme, selector, canvas in THEMES:
            palette = _tokens(self.blocks, selector)
            for row, token, hoverable in MENU_ROWS:
                for hover in (False, True) if hoverable else (False,):
                    with self.subTest(theme=theme, row=row, hover=hover):
                        ratio = self._measure(palette, token, canvas, hover)
                        if theme in UNGATED:
                            # measured, not gated — but it must still be a
                            # number, so a broken palette cannot hide here
                            self.assertGreater(ratio, 1.0)
                            continue
                        self.assertGreaterEqual(
                            round(ratio, 2), AA,
                            f"{row} is {ratio:.2f}:1 on {DROPDOWN[canvas]}")

    def test_the_dead_verdict_clears_aa_on_every_canvas(self):
        # the same ink, on the surface it was picked for: the links page's own
        # canvas rather than a dropdown Bootstrap paints
        for theme, selector, _ in THEMES:
            palette = _tokens(self.blocks, selector)
            with self.subTest(theme=theme):
                ratio = _ratio(_rgb(palette["--ls-danger-ink"]),
                               _rgb(palette["--ls-canvas"]))
                if theme in UNGATED:
                    self.assertGreater(ratio, 1.0)
                    continue
                self.assertGreaterEqual(round(ratio, 2), AA,
                                        f"dead verdict is {ratio:.2f}:1")

    def test_every_links_page_row_clears_aa_on_its_own_surface(self):
        # The page's own rows, on our canvas rather than on Bootstrap's dropdown:
        # the freshness line, the two verdict inks and the *check now* button at
        # rest and under the pointer. The dead verdict is measured above as well,
        # deliberately — that ink is the one this table exists to protect.
        for theme, selector, _ in THEMES:
            palette = _tokens(self.blocks, selector)
            for row, ink, surface in PAGE_ROWS:
                with self.subTest(theme=theme, row=row):
                    ratio = _ratio(_rgb(palette[ink]), _rgb(palette[surface]))
                    if theme in UNGATED:
                        self.assertGreater(ratio, 1.0)
                        continue
                    self.assertGreaterEqual(
                        round(ratio, 2), AA,
                        f"{row} is {ratio:.2f}:1 on {palette[surface]}")

    def test_every_hero_row_clears_aa_in_every_gated_theme(self):
        # The hero is on the canvas, so each theme paints it with its own inks —
        # which is the point, and which means each theme owes the bar.
        for theme, selector, _ in THEMES:
            palette = _tokens(self.blocks, selector)
            for row, ink, surface in HERO_ROWS:
                with self.subTest(theme=theme, row=row):
                    ratio = _ratio(_rgb(palette[ink]), _rgb(palette[surface]))
                    if theme in UNGATED:
                        self.assertGreater(ratio, 1.0)
                        continue
                    self.assertGreaterEqual(round(ratio, 2), AA,
                                            f"{row} is {ratio:.2f}:1")

    def test_a_silenced_reason_clears_aa_as_the_composite_it_is(self):
        """The silenced-reason block, folded at every opacity that reaches its text.

        This is the measurement that was missing. The ink and the surface are both
        ours, because the block paints its own tint — and every `opacity` inside it
        is read out of the sheet and composited, rather than being assumed away. A
        dim added later moves this number, which is the whole point: the previous
        one moved nothing and the page went under AA for a week.
        """
        dims = [1.0]
        for rule in QUIET_RULES:
            found = re.search(r"(?m)^\s*opacity\s*:\s*([\d.]+)",
                              _by_selector(self.blocks)[rule])
            if found:
                dims.append(float(found.group(1)))
        for theme, selector, _ in THEMES:
            palette = _tokens(self.blocks, selector)
            surface = _rgb(palette[QUIET_SURFACE])
            for dim in dims:
                with self.subTest(theme=theme, opacity=dim):
                    ratio = _ratio(_over(_rgb(palette[QUIET_INK]), surface, dim),
                                   surface)
                    if theme in UNGATED:
                        self.assertGreater(ratio, 1.0)
                        continue
                    self.assertGreaterEqual(
                        round(ratio, 2), AA,
                        f"a silenced reason at opacity {dim} is {ratio:.2f}:1 "
                        f"on {palette[QUIET_SURFACE]}")

    def test_a_coded_reason_line_clears_aa_on_its_own_tint(self):
        """Every coded line (ADR-0042) paints its own tint pair at full
        opacity — `.is-coded` resets the reason wash — so the pair *is* the
        measurement, on every gated theme, independent of the card beneath. All
        four states, because a mixed list sits on a vivid fill, where a
        surfaceless line would inherit the drama; the quiet override keeps a
        pinned coded line on the maintenance pair, measured above."""
        for theme, selector, _ in THEMES:
            palette = _tokens(self.blocks, selector)
            for state in ("ok", "warn", "error", "undefined"):
                with self.subTest(theme=theme, state=state):
                    ratio = _ratio(_rgb(palette[f"--ls-tint-{state}-ink"]),
                                   _rgb(palette[f"--ls-tint-{state}"]))
                    if theme in UNGATED:
                        self.assertGreater(ratio, 1.0)
                        continue
                    self.assertGreaterEqual(
                        round(ratio, 2), AA,
                        f"a coded {state} line is {ratio:.2f}:1 on its tint "
                        f"in {theme}")

    def test_a_coded_line_resets_the_reason_wash(self):
        """The base reason rule carries `opacity: 0.95`; a line that paints its
        own opaque surface must not inherit the wash, or the pair measured above
        is not the pair rendered — the silenced-reason lesson, one rule over."""
        sheet = STYLESHEET.read_text()
        block = re.search(
            r"\.status-node__reason\.is-coded,\s*"
            r"\.check-reason\.is-coded\s*\{([^}]*)\}", sheet)
        self.assertIsNotNone(block, "the .is-coded base rule is gone")
        assert block is not None
        self.assertIn("opacity: 1", block.group(1))

    def test_the_state_clusters_hold_their_rows(self):
        """A box's self row is a wrapping flex row and its state cluster never
        breaks internally — a floated cluster dropped out of its box under
        width pressure (action chips) and overlaid the next one, and a card's
        state used to wrap between its time and its word. Structural, because
        no rendered-count test can see a float escape its container."""
        sheet = STYLESHEET.read_text()
        self_row = re.search(r"\.status-node__self\s*\{([^}]*)\}", sheet)
        self.assertIsNotNone(self_row, "the box self-row rule is gone")
        assert self_row is not None
        self.assertIn("display: flex", self_row.group(1))
        self.assertIn("flex-wrap: wrap", self_row.group(1))
        for selector in (r"\.status-node__state", r"\.status-card__state"):
            block = re.search(selector + r"\s*\{([^}]*)\}", sheet)
            with self.subTest(rule=selector):
                self.assertIsNotNone(block)
                assert block is not None
                self.assertIn("white-space: nowrap", block.group(1))
                self.assertIn("margin-left: auto", block.group(1))
                self.assertNotIn("float", block.group(1))
        # The standing second line is the deployment's opt-in (settings.yaml
        # `card_status_line: below`, rendered as a body attribute): the compact
        # default keeps the cluster beside the title, so the base rule must NOT
        # carry the full basis — and the opted-in block must.
        card_state = re.search(r"\.status-card__state\s*\{([^}]*)\}", sheet)
        assert card_state is not None
        self.assertNotIn("flex-basis", card_state.group(1))
        below = re.search(
            r"body\[data-ls-card-state=\"below\"\] \.status-card__state"
            r"\s*\{([^}]*)\}", sheet)
        self.assertIsNotNone(below, "the standing-second-line rule is gone")
        assert below is not None
        self.assertIn("flex-basis: 100%", below.group(1))
        self.assertIn("text-align: right", below.group(1))
        # The head's middle (title + action chips) has zero say in line-fitting:
        # wrapping preempts shrinking, so only a zero-basis middle stays out of
        # the equation — and the chips inside it sit absolutely, over the title
        # where the two collide, costing the row no width at all.
        middle = re.search(r"\.status-head__middle\s*\{([^}]*)\}", sheet)
        self.assertIsNotNone(middle, "the head-middle rule is gone")
        assert middle is not None
        self.assertIn("flex: 1 1 0", middle.group(1))
        self.assertIn("min-width: 0", middle.group(1))
        self.assertIn("position: relative", middle.group(1))
        chips = re.search(
            r"\.status-head__middle > \.node-actions\s*\{([^}]*)\}", sheet)
        self.assertIsNotNone(chips, "the overlaying-chips rule is gone")
        assert chips is not None
        self.assertIn("position: absolute", chips.group(1))

    def test_a_quiet_signal_clears_aa_as_the_mix_it_is(self):
        # A term at rest is a `color-mix` of the body ink and the muted furniture
        # — brighter than the ring it rides, quieter than the prose. Both ends
        # clear the bar on the canvas, so the mix between them does too; this
        # measures it rather than trusting the argument.
        ink_token, muted_token, weight = SIGNAL_MIX
        for theme, selector, _ in THEMES:
            palette = _tokens(self.blocks, selector)
            with self.subTest(theme=theme):
                mixed = _over(_rgb(palette[ink_token]),
                              _rgb(palette[muted_token]), weight)
                ratio = _ratio(mixed, _rgb(palette["--ls-canvas"]))
                if theme in UNGATED:
                    self.assertGreater(ratio, 1.0)
                    continue
                self.assertGreaterEqual(round(ratio, 2), AA,
                                        f"a quiet signal is {ratio:.2f}:1")

    def test_the_sheet_still_mixes_the_signal_the_way_this_measures_it(self):
        # The one number written down twice. If the sheet re-weighs the mix, the
        # measurement above becomes fiction, so it has to fail here first.
        rule = _by_selector(self.blocks)[".ls-hero__signal b"]
        self.assertIn("color-mix(in srgb, var(--ls-ink) 55%, var(--ls-muted))",
                      rule)

    def test_every_theme_re_homes_the_danger_ink_it_needs(self):
        # a new dark theme that forgot the override would inherit the light
        # canvas's ink and fail above; this says the same thing in the form the
        # next person reads first
        for theme, selector, canvas in THEMES:
            if canvas != "dark":
                continue
            with self.subTest(theme=theme):
                self.assertIn("--ls-danger-ink", self.blocks[selector])
                self.assertIn("--ls-menu-hover", self.blocks[selector])
