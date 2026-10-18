"""The settings menu and the dead verdict hold AA in every theme.

ADR-0028 puts the accessibility bar above any picked swatch and says status
color is verified by *measurement*, not by class presence. The faithful
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
on a rule that sets a color. The token was picked and measured undimmed at 7.6:1,
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
# row measured against `--ls-ink` would be measuring a color nobody paints.
DROPDOWN_INK = {"light": "#212529", "dark": "#dee2e6"}

# (label, the token block to read, which dropdown surface). `auto` is the dark
# block a second time — the browser resolves it, and its light half is byte-for-
# byte the `:root` set `plain` already covers.
THEMES = (
    ("plain", None, "light"),
    ("vivid", 'body[data-ls-theme="vivid"]', "light"),
    ("pastel", 'body[data-ls-theme="pastel"]', "light"),
    ("dark", 'body[data-ls-theme="dark"]', "dark"),
    ("auto", 'body[data-ls-theme="auto"]', "dark"),
    ("cyberpunk", 'body[data-ls-theme="cyberpunk"]', "dark"),
)

# Every theme owes the bar — cyberpunk too, the library's default theme (ADR-0028),
# which was the declared fun theme, measured and reported and never gated, until it
# became the default.
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
# ink from us precisely because `btn-outline-secondary` paints one gray on every
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

# The folds of the links page's setup guide are cards, and a card's surface is
# Bootstrap's, as the dropdown's is: white on a light canvas and #212529 on a dark
# one. What a fold's summary adds beside its name is muted, from our token rather
# than Bootstrap's `.text-muted`, so that it can be measured here on that surface.
FOLD_ROWS = (
    (".ls-links__aside", "--ls-muted"),
)

# The /about hero paints no surface of its own — it sits on the page canvas in
# every theme, which is what settled the light themes. What it does own is a
# **color vocabulary**, and these are the two readings that carry meaning: a
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
               ".reason-quiet-count", ".reason-orphan",
               ".event-suppressed", ".event-cause",
               # a rule's block (ADR-0104): the same pair, on its own surface —
               # on a node's page, on the Maintenance page, in a card on the wall
               # and in a branch's head, where it took over from the strip
               '.rule-block[data-rule="maintenance"]')


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
    asking about `a:hover` should not have to know what it was grouped with. The list
    splits where the rule's own commas stand: one inside ``:is()`` or ``:not()``
    belongs to the selector it is in.
    """
    table = {}
    for key, body in blocks.items():
        for part in _selectors(key):
            table.setdefault(part, body)
    return table


def _selectors(group):
    """A rule's selector list, split at its own commas and never inside brackets."""
    parts, depth, start = [], 0, 0
    for i, char in enumerate(group):
        if char in "([":
            depth += 1
        elif char in ")]":
            depth -= 1
        elif char == "," and depth == 0:
            parts.append(group[start:i].strip())
            start = i + 1
    parts.append(group[start:].strip())
    return parts


def _tokens(blocks, selector):
    """A theme's effective palette: ``:root`` with the theme's overrides on top."""
    palette = dict(re.findall(r"(--ls-[\w-]+)\s*:\s*([^;]+);", blocks[":root"]))
    if selector is not None:
        palette.update(
            re.findall(r"(--ls-[\w-]+)\s*:\s*([^;]+);", blocks[selector]))
    return {name: value.strip() for name, value in palette.items()}


def _rgb(value):
    """A hex color as three 0–255 floats. Only hex reaches here by design."""
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
    """The WCAG contrast ratio between two opaque colors."""
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
        # `btn btn-sm` for the shape, our ink for the color: Bootstrap's outline
        # secondary is one gray on every canvas, and the measurements above are
        # fiction the moment this row takes its color from it instead
        rules = _by_selector(self.blocks)
        for rule in (".ls-links__recheck .btn",
                     ".ls-links__recheck .btn:hover"):
            with self.subTest(rule=rule):
                self.assertIn("color: var(--ls-ink)", rules[rule])

    def test_every_theme_paints_opaque_navigation_chrome(self):
        # Sticky chrome now crosses the page as it scrolls. A translucent nav
        # token would composite against each card it passes and make every
        # contrast measurement above a moving target, so the surface itself is
        # part of the contract now. Keep it an explicit opaque color in every
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
                # a declaration wherever it stands: in a rule written on one line
                # it follows a semicolon, and no line begins with it
                self.assertNotRegex(
                    body, r"(?m)(?:^|;)\s*opacity\s*:",
                    f"{selector} sets an --ls-* ink and dims it; the token was "
                    f"measured undimmed, so the rendered value is unmeasured")

    def test_the_silenced_reason_paints_its_own_surface(self):
        # the other half: measuring the pair above is only meaningful while the
        # block actually carries that background. Drop it and the ink lands on a
        # card fill again — or on Bootstrap's alert — and the numbers are fiction.
        rules = _by_selector(self.blocks)
        for rule in (".status-node__reason.is-quiet", ".check-reason.is-quiet",
                     ".reason-quiet-count", ".reason-orphan",
                     ".event-suppressed", ".event-cause",
                     '.rule-block[data-rule="maintenance"]'):
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

    def test_every_row_clears_aa_in_every_theme(self):
        for theme, selector, canvas in THEMES:
            palette = _tokens(self.blocks, selector)
            for row, token, hoverable in MENU_ROWS:
                for hover in (False, True) if hoverable else (False,):
                    with self.subTest(theme=theme, row=row, hover=hover):
                        ratio = self._measure(palette, token, canvas, hover)
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
                    self.assertGreaterEqual(
                        round(ratio, 2), AA,
                        f"{row} is {ratio:.2f}:1 on {palette[surface]}")

    def test_a_folds_aside_clears_aa_on_the_card(self):
        rules = _by_selector(self.blocks)
        for theme, selector, canvas in THEMES:
            palette = _tokens(self.blocks, selector)
            for row, ink in FOLD_ROWS:
                with self.subTest(theme=theme, row=row):
                    # a literal, or another token, and the number is fiction
                    self.assertIn(f"color: var({ink})", rules[row])
                    ratio = _ratio(_rgb(palette[ink]), _rgb(DROPDOWN[canvas]))
                    self.assertGreaterEqual(
                        round(ratio, 2), AA,
                        f"{row} is {ratio:.2f}:1 on {DROPDOWN[canvas]}")

    def test_every_hero_row_clears_aa_in_every_theme(self):
        # The hero is on the canvas, so each theme paints it with its own inks —
        # which is the point, and which means each theme owes the bar.
        for theme, selector, _ in THEMES:
            palette = _tokens(self.blocks, selector)
            for row, ink, surface in HERO_ROWS:
                with self.subTest(theme=theme, row=row):
                    ratio = _ratio(_rgb(palette[ink]), _rgb(palette[surface]))
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
                    self.assertGreaterEqual(
                        round(ratio, 2), AA,
                        f"a silenced reason at opacity {dim} is {ratio:.2f}:1 "
                        f"on {palette[QUIET_SURFACE]}")

    def test_a_coded_reason_line_clears_aa_on_its_own_tint(self):
        """Every coded line (ADR-0042) paints its own tint pair at full
        opacity — `.is-coded` resets the reason wash — so the pair *is* the
        measurement, on every theme, independent of the card beneath. All
        four states, because a mixed list sits on a vivid fill, where a
        surfaceless line would inherit the drama; the quiet override keeps a
        pinned coded line on the maintenance pair, measured above."""
        for theme, selector, _ in THEMES:
            palette = _tokens(self.blocks, selector)
            for state in ("ok", "warn", "error", "undefined"):
                with self.subTest(theme=theme, state=state):
                    ratio = _ratio(_rgb(palette[f"--ls-tint-{state}-ink"]),
                                   _rgb(palette[f"--ls-tint-{state}"]))
                    self.assertGreaterEqual(
                        round(ratio, 2), AA,
                        f"a coded {state} line is {ratio:.2f}:1 on its tint "
                        f"in {theme}")

    def test_a_removal_s_chip_and_a_suspended_pin_s_sentence_clear_aa(self):
        """What a removed node paints (ADR-0109): the chip of its row wears the
        undefined pair on a surface of its own, since no pin wrote that row, and
        the sentence over a pin whose node is not reported the muted ink on the
        page's canvas."""
        rules = _by_selector(self.blocks)
        chip, sentence = rules[".event-cause--removed"], rules[".pin-node__suspended"]
        self.assertIn("background: var(--ls-tint-undefined)", chip)
        self.assertIn("color: var(--ls-tint-undefined-ink)", chip)
        self.assertIn("color: var(--ls-muted)", sentence)
        pairs = (("--ls-tint-undefined-ink", "--ls-tint-undefined"),
                 ("--ls-muted", "--ls-canvas"))
        for theme, selector, _ in THEMES:
            palette = _tokens(self.blocks, selector)
            for ink, surface in pairs:
                with self.subTest(theme=theme, ink=ink):
                    ratio = _ratio(_rgb(palette[ink]), _rgb(palette[surface]))
                    self.assertGreaterEqual(
                        round(ratio, 2), AA,
                        f"{ink} is {ratio:.2f}:1 on {palette[surface]} in {theme}")

    def test_a_reached_rows_chip_wears_the_pair_of_its_status(self):
        """What the end of a wait paints (ADR-0119 decision 3): the chip of its
        row wears the pair of the status the row shows, on a surface of its own.
        No pin wrote that row, so the chip is not on a pin's tint; and only a
        worse status is ever held back, so a row that reached shows *warn* or
        *error*."""
        rules = _by_selector(self.blocks)
        for state in ("error", "warn"):
            chip = rules[f".row-{state} .event-cause--reached"]
            self.assertIn(f"background: var(--ls-tint-{state})", chip)
            self.assertIn(f"color: var(--ls-tint-{state}-ink)", chip)
            self.assertNotRegex(chip, r"opacity\s*:")
            for theme, selector, _ in THEMES:
                palette = _tokens(self.blocks, selector)
                with self.subTest(state=state, theme=theme):
                    ratio = _ratio(_rgb(palette[f"--ls-tint-{state}-ink"]),
                                   _rgb(palette[f"--ls-tint-{state}"]))
                    self.assertGreaterEqual(
                        round(ratio, 2), AA,
                        f"a chip that says reached is {ratio:.2f}:1 on its "
                        f"{state} tint in {theme}")

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
        """A head's row never wraps and its state cluster never breaks internally
        (ADR-0127 decision 3): a floated cluster dropped out of its box under
        width pressure (action chips) and overlaid the next one, and a card's
        state used to wrap between its time and its word. Where the name would
        be cut, the cluster takes a line of its own beneath — placed from the
        head, never a full-basis flex line, which a toolbar's item cannot take.
        Structural, because no rendered-count test can see a float escape its
        container."""
        sheet = STYLESHEET.read_text()
        card_head = re.search(r"\.status-card__head\s*\{([^}]*)\}", sheet)
        self.assertIsNotNone(card_head, "the card head rule is gone")
        assert card_head is not None
        self.assertIn("display: flex", card_head.group(1))
        self.assertIn("flex-wrap: nowrap", card_head.group(1))
        self.assertIn("position: relative", card_head.group(1))
        # a box's row, and a node page's head, which is the row a box draws
        box_row = re.search(
            r":is\(\.tree-box, \.viewed-head\) > \.status-node__self"
            r"\s*\{([^}]*)\}", sheet)
        self.assertIsNotNone(box_row, "the box row rule is gone")
        assert box_row is not None
        self.assertIn("flex-wrap: nowrap", box_row.group(1))
        for selector in (r"\.status-node__state", r"\.status-card__state"):
            block = re.search(r"(?m)^" + selector + r"\s*\{([^}]*)\}", sheet)
            with self.subTest(rule=selector):
                self.assertIsNotNone(block)
                assert block is not None
                self.assertIn("white-space: nowrap", block.group(1))
                self.assertNotIn("float", block.group(1))
                self.assertNotIn("flex-basis", block.group(1))
        # the toolbar holds the cluster among the controls and never wraps either
        toolbar = re.search(r"(?m)^\.node-controls\s*\{([^}]*)\}", sheet)
        self.assertIsNotNone(toolbar, "the toolbar rule is gone")
        assert toolbar is not None
        self.assertIn("display: inline-flex", toolbar.group(1))
        self.assertIn("flex: none", toolbar.group(1))
        # the head places the state's line, not the toolbar
        self.assertNotIn("position: relative", toolbar.group(1))
        # The standing second line is the deployment's opt-in (settings.yaml
        # `card_status_line: below`, rendered as a body attribute) or the script's
        # word where the name would be cut (`.is-state-below`): the cluster is
        # placed at the head's foot, and the head is padded by a line for it.
        below = re.search(
            r"\.is-state-below > \.node-controls > \.status-card__state,\s*"
            r"\.is-state-below > \.node-controls > \.status-node__state,\s*"
            r"body\[data-ls-card-state=\"below\"\] \.status-card__head > "
            r"\.node-controls > \.status-card__state\s*\{([^}]*)\}", sheet)
        self.assertIsNotNone(below, "the standing-second-line rule is gone")
        assert below is not None
        self.assertIn("position: absolute", below.group(1))
        self.assertIn("bottom: 0", below.group(1))
        padded = re.search(
            r"\.status-card__head\.is-state-below,\s*"
            r":is\(\.tree-box, \.viewed-head\) > "
            r"\.status-node__self\.is-state-below,\s*"
            r"body\[data-ls-card-state=\"below\"\] \.status-card__head\s*\{([^}]*)\}",
            sheet)
        self.assertIsNotNone(padded, "the head's padding for the line is gone")
        assert padded is not None
        self.assertIn("padding-bottom", padded.group(1))
        # The head's middle (the title) has zero say in line-fitting, so it gives
        # way first; nothing is laid over it any more, so no rail sits absolutely in
        # it and no veil repaints the fill under a chip.
        middle = re.search(r"\.status-head__middle\s*\{([^}]*)\}", sheet)
        self.assertIsNotNone(middle, "the head-middle rule is gone")
        assert middle is not None
        self.assertIn("flex: 1 1 0", middle.group(1))
        self.assertIn("min-width: 0", middle.group(1))
        self.assertNotIn(".status-head__middle > .node-actions", sheet)
        # the node's actions are shown always, as the head's own icons are
        chip = re.search(r"\.node-action\s*\{([^}]*)\}", sheet)
        assert chip is not None
        self.assertNotRegex(chip.group(1), r"opacity\s*:")
        # Where the name broke onto a second line anyway, the state stands on it
        # (`.is-state-beside`, Lex's word of 2026-10-16): no padding for a line of
        # its own, and the toolbar level with the name's first line.
        beside = re.search(
            r"\.status-card__head\.is-state-below\.is-state-beside,\s*"
            r":is\(\.tree-box, \.viewed-head\) > "
            r"\.status-node__self\.is-state-below\.is-state-beside,\s*"
            r"body\[data-ls-card-state=\"below\"\] \.status-card__head\.is-state-beside"
            r"\s*\{([^}]*)\}", sheet)
        self.assertIsNotNone(beside, "the state's place beside a broken name is gone")
        assert beside is not None
        self.assertIn("padding-bottom: 0", beside.group(1))
        self.assertRegex(sheet, r"\.is-state-beside > \.node-controls\s*\{\s*"
                                r"align-self: flex-start;")

    def test_the_heads_glyphs_and_a_cards_lines_have_their_room(self):
        """The head's glyph is two thirds of its square, 16 of 24 pixels at the
        browser's own size, and in rem as the square is, so a larger font grows
        both alike; and a card's children stand 6 pixels below its own lines, as a
        box's do (Lex's word of 2026-10-16) — and a title squeezed below two
        letters shows nothing rather than a clipped glyph. Held in Chromium by
        `test_tree_browser.py`; here so the gate, which has no browser, holds them
        too."""
        sheet = STYLESHEET.read_text()
        self.assertRegex(sheet, r"(?m)^\.node-icon\s*\{[^}]*width: 1\.5rem;[^}]*"
                                r"height: 1\.5rem;")
        self.assertRegex(sheet, r"(?m)^\.icon-mark\s*\{[^}]*width: 1rem; height: 1rem;")
        self.assertRegex(sheet, r"(?m)^\.node-action\.is-icon > \.action-icon\s*\{"
                                r"[^}]*width: 1rem; height: 1rem;")
        self.assertRegex(sheet, r"\.status-panel > \.reason-block ~ \.node-children\s*"
                                r"\{\s*margin-top: 6px;")
        self.assertRegex(sheet, r"\.status-node__children\s*\{\s*margin-top: 6px;")
        self.assertRegex(sheet, r"\.status-head__middle\s*\{\s*"
                                r"container-type: inline-size;")
        self.assertRegex(sheet, r"@container \(max-width: 2\.5em\)\s*\{\s*"
                                r"\.status-head__middle > \.node-title\s*\{\s*"
                                r"visibility: hidden;")

    def test_a_heads_row_answers_the_pointer_from_its_tokens(self):
        """A head's row opens and closes its node by a click anywhere on it but its
        own controls, and with the caret gone says so itself (Lex's word of
        2026-10-16): under the pointer, where hover is the input's, an outline of
        its surface's ink at 60 %, 3 pixels out; pressed, a wash of 12 %, 4 pixels
        past it; neither on a control of its own; both from tokens, which a viewer's
        choice of the wash will set. The name no longer underlines. Held in Chromium
        by `test_tree_browser.py`; here for the gate."""
        sheet = _strip_comments(STYLESHEET.read_text())
        palette = _tokens(_blocks(sheet), None)
        self.assertEqual((palette["--ls-toggle-hover-line"],
                          palette["--ls-toggle-hover-wash"],
                          palette["--ls-toggle-press-wash"]), ("60%", "0%", "12%"))
        heads = r":is\(\.status-card__head, \.tree-box > \.status-node__self\)"
        own = (r":not\(:has\(:is\(\.node-icons, \.node-actions, \.node-more, "
               r"\.node-actions-menu, \.maintenance-pip\):{0}\)\)")
        hover = re.search(
            r"@media \(hover: hover\)\s*\{\s*" + heads + ":hover" + own.format("hover")
            + r"\s*\{([^}]*)\}", sheet)
        self.assertIsNotNone(hover, "the row's outline under the pointer is gone")
        assert hover is not None
        self.assertIn("outline: 1px solid color-mix(in srgb, currentColor "
                      "var(--ls-toggle-hover-line), transparent);", hover.group(1))
        self.assertIn("outline-offset: 3px;", hover.group(1))
        self.assertIn("background-color: color-mix(in srgb, currentColor "
                      "var(--ls-toggle-hover-wash), transparent);", hover.group(1))
        self.assertIn("box-shadow: 0 0 0 4px color-mix(in srgb, currentColor "
                      "var(--ls-toggle-hover-wash), transparent);", hover.group(1))
        press = re.search(r"(?m)^" + heads + ":active" + own.format("active")
                          + r"\s*\{([^}]*)\}", sheet)
        self.assertIsNotNone(press, "the row's wash when pressed is gone")
        assert press is not None
        self.assertIn("background-color: color-mix(in srgb, currentColor "
                      "var(--ls-toggle-press-wash), transparent);", press.group(1))
        self.assertIn("box-shadow: 0 0 0 4px color-mix(in srgb, currentColor "
                      "var(--ls-toggle-press-wash), transparent);", press.group(1))
        self.assertRegex(sheet, r"(?m)^" + heads + r"\s*\{\s*border-radius: 4px;")
        # the row's cursor is the pointer's, and only a name whose pause brings
        # the node's card wears the help cursor (ADR-0019 decision 3)
        self.assertRegex(sheet, r"(?m)^" + heads + r"\s*\{\s*cursor: pointer;")
        self.assertRegex(sheet, r"(?m)^:is\(\.status-card__name, \.status-node__name, "
                                r"\.ls-strip__name\)\.inspect-trigger\s*\{\s*"
                                r"cursor: help;")
        self.assertRegex(sheet, r"(?m)^\.status-node__self\s*\{\s*cursor: default;")
        self.assertNotIn("tree-caret", sheet)
        self.assertNotIn(".status-card__name:hover", sheet)
        self.assertRegex(sheet, r'(?m)^\.status-node a:not\(\[data-control="toggle"\], '
                                r'\.tree-chip\):hover\s*\{\s*'
                                r'text-decoration: underline;')

    def test_a_chip_answers_the_pointer_as_the_row_does(self):
        """A chip, which a click opens as a head's row closes, says so as the row
        does (Lex's word of 2026-10-16): under the pointer, where hover is the
        input's, an outline of its ink from the row's token, a pixel out where chips
        stand close, never over a keyboard's focus ring; pressed a wash of its ink
        laid over its tint, which stays; its name no longer underlined. Held in
        Chromium by `test_tree_browser.py`; here for the gate."""
        sheet = _strip_comments(STYLESHEET.read_text())
        hover = re.search(r"@media \(hover: hover\)\s*\{\s*"
                          r"\.tree-chip:hover:not\(:focus-visible\)\s*\{([^}]*)\}",
                          sheet)
        self.assertIsNotNone(hover, "the chip's outline under the pointer is gone")
        assert hover is not None
        self.assertIn("outline: 1px solid color-mix(in srgb, currentColor "
                      "var(--ls-toggle-hover-line), transparent);", hover.group(1))
        self.assertIn("outline-offset: 1px;", hover.group(1))
        self.assertIn("background-image: linear-gradient(color-mix(in srgb, "
                      "currentColor var(--ls-toggle-hover-wash), transparent),",
                      hover.group(1))
        self.assertNotIn("background-color", hover.group(1))
        press = re.search(r"(?m)^\.tree-chip:active:not\(:focus-visible\)"
                          r"\s*\{([^}]*)\}", sheet)
        self.assertIsNotNone(press, "the chip's wash when pressed is gone")
        assert press is not None
        self.assertIn("background-image: linear-gradient(color-mix(in srgb, "
                      "currentColor var(--ls-toggle-press-wash), transparent),",
                      press.group(1))
        self.assertNotIn(".tree-chip:hover .tree-chip__name", sheet)

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


# A measure's curve (ADR-0092) sits on a card, and **Bootstrap paints the card**:
# `--bs-card-bg` is `--bs-body-bg`, the same two surfaces the menu rows sit on, so
# the curve is measured against :data:`DROPDOWN`. What it draws is ours: the line
# and its dots in the body ink, a reading without a value in the danger ink — the
# links page's *does not answer*, which is what a failed request says — and the axes'
# words in the muted ink. Marks are graphics and owe 3:1 (WCAG 1.4.11); the axes'
# words are text and owe the text bar. (rule, the property it paints, the token.)
#
# A run's mark (ADR-0111) is drawn from the same inks: its stem in the body ink, in
# the danger ink where it failed and in the muted ink where it kept no verdict; a
# hollow ring in the danger ink for a head that failed; and for one that warned the
# cue's triangle, whose **outline** is the body ink and is what is measured — the
# warning's yellow inside it is a fill no ink could be on a card.
CURVE_MARKS = (
    (".ls-curve__line", "stroke", "--ls-ink"),
    (".ls-curve__dot", "fill", "--ls-ink"),
    (".ls-curve__none", "stroke", "--ls-danger-ink"),
    (".ls-curve__stem", "stroke", "--ls-ink"),
    (".ls-curve__stem--failed", "stroke", "--ls-danger-ink"),
    (".ls-curve__stem--unjudged", "stroke", "--ls-muted"),
    (".ls-curve__failed", "stroke", "--ls-danger-ink"),
    (".ls-curve__warned", "stroke", "--ls-ink"),
)
CURVE_WORDS = (
    (".ls-curve__tick", "fill", "--ls-muted"),
    (".ls-curve__time", "fill", "--ls-muted"),
    (".ls-curve__unit", "fill", "--ls-muted"),
)
GRAPHICS = 3.0


class CurveContrastTests(TestCase):
    """The curve's marks and words, on the card surface, in every theme."""

    @classmethod
    def setUpClass(cls):
        cls.blocks = _blocks(STYLESHEET.read_text(encoding="utf-8"))

    def test_the_curve_paints_from_the_tokens_measured_here(self):
        # a literal, or another token, and the numbers below are fiction
        rules = _by_selector(self.blocks)
        for rule, prop, token in CURVE_MARKS + CURVE_WORDS:
            with self.subTest(rule=rule):
                self.assertIn(f"{prop}: var({token})", rules[rule])
                self.assertNotRegex(rules[rule], r"(?m)^\s*(opacity|fill-opacity|"
                                                 r"stroke-opacity)\s*:")

    def test_every_mark_clears_the_graphics_bar_on_the_card(self):
        for theme, selector, canvas in THEMES:
            palette = _tokens(self.blocks, selector)
            for rule, _, token in CURVE_MARKS:
                with self.subTest(theme=theme, rule=rule):
                    ratio = _ratio(_rgb(palette[token]), _rgb(DROPDOWN[canvas]))
                    self.assertGreaterEqual(round(ratio, 2), GRAPHICS,
                                            f"{rule} is {ratio:.2f}:1")

    def test_a_warnings_head_is_filled_from_the_warning_and_a_failures_from_the_card(
            self):
        # the two fills that are no ink: the warning's own surface color inside the
        # ink's outline, and the card's surface inside a failure's ring, which is
        # what makes it hollow in every theme
        rules = _by_selector(self.blocks)
        self.assertIn("fill: var(--ls-warn)", rules[".ls-curve__warned"])
        self.assertIn("fill: var(--bs-card-bg, var(--bs-body-bg))",
                      rules[".ls-curve__failed"])

    def test_every_word_on_the_axes_clears_aa_on_the_card(self):
        for theme, selector, canvas in THEMES:
            palette = _tokens(self.blocks, selector)
            for rule, _, token in CURVE_WORDS:
                with self.subTest(theme=theme, rule=rule):
                    ratio = _ratio(_rgb(palette[token]), _rgb(DROPDOWN[canvas]))
                    self.assertGreaterEqual(round(ratio, 2), AA,
                                            f"{rule} is {ratio:.2f}:1")


# Cyberpunk's logs (ADR-0028): a log — the Events page, a node's
# History tab — restates the five status tints, weighed by status, and lights each
# row's status word in its state's neon. The logs alone: the wall and a node's Status
# tab keep the theme's own tints, so the restated ones live on the log's block and
# nowhere else.
LOG_BLOCK = 'body[data-ls-theme="cyberpunk"] .ls-log'
STATES = ("error", "warn", "maintenance", "ok", "undefined")
GLOWING = ("error", "warn", "maintenance", "ok")


class CyberpunkLogTests(TestCase):
    """A log's rows weighed by their status, and their words lit, in the logs alone."""

    @classmethod
    def setUpClass(cls):
        cls.blocks = _blocks(STYLESHEET.read_text(encoding="utf-8"))
        cls.rules = _by_selector(cls.blocks)
        cls.theme = _tokens(cls.blocks, 'body[data-ls-theme="cyberpunk"]')
        restated = re.findall(r"(--ls-[\w-]+)\s*:\s*([^;]+);", cls.blocks[LOG_BLOCK])
        cls.log = {**cls.theme, **{name: value.strip() for name, value in restated}}

    def _off_the_canvas(self, palette, state):
        return _ratio(_rgb(palette[f"--ls-tint-{state}"]), _rgb(palette["--ls-canvas"]))

    def test_a_failures_row_stands_further_from_the_canvas_than_a_recovery(self):
        # the theme's own near-black tints put an error's row nearest the canvas of
        # all; in a log every failure's row stands further from it than an ok's
        recovery = self._off_the_canvas(self.log, "ok")
        for state in ("error", "warn", "maintenance"):
            with self.subTest(state=state):
                self.assertGreater(self._off_the_canvas(self.log, state), recovery)

    def test_the_failures_are_lifted_and_a_recovery_sunk_in_the_logs_alone(self):
        for state in ("error", "warn", "maintenance"):
            with self.subTest(state=state):
                self.assertGreater(self._off_the_canvas(self.log, state),
                                   self._off_the_canvas(self.theme, state))
        self.assertLess(self._off_the_canvas(self.log, "ok"),
                        self._off_the_canvas(self.theme, "ok"))
        # a tint is declared by the root, by a theme, and by cyberpunk's log — by no
        # other rule, so nothing else of the theme's is lifted
        declared = {selector for selector, body in self.blocks.items()
                    if re.search(r"--ls-tint-[\w-]+\s*:", body)}
        self.assertIn(LOG_BLOCK, declared)
        for selector in declared - {LOG_BLOCK}:
            with self.subTest(selector=selector):
                self.assertRegex(selector, r'^(:root|body\[data-ls-theme="[a-z]+"\])$')

    def test_each_status_word_wears_its_states_ink_and_glows_but_undefined(self):
        for state in STATES:
            rule = self.rules[f"{LOG_BLOCK} .row-{state} .ls-log__status"]
            with self.subTest(state=state):
                self.assertIn(f"color: var(--ls-tint-{state}-ink)", rule)
                if state in GLOWING:
                    # the theme's glow, as its state words wear it on the wall
                    self.assertIn("text-shadow: 0 0 7px currentColor", rule)
                else:
                    self.assertNotIn("text-shadow", rule)
                self.assertNotRegex(rule, r"opacity\s*:")

    def test_each_word_reads_on_its_row(self):
        # the lift stops where an error's pink still reads on its row
        for state in STATES:
            with self.subTest(state=state):
                ratio = _ratio(_rgb(self.log[f"--ls-tint-{state}-ink"]),
                               _rgb(self.log[f"--ls-tint-{state}"]))
                self.assertGreaterEqual(round(ratio, 2), AA,
                                        f"the {state} word is {ratio:.2f}:1 on its row")


# Cyberpunk's culprit (ADR-0028): a node reporting its own
# problem is a neon tube — its fill dark glass, its words white-hot, and its edge, an
# inner and an outer glow and its words' halo in its state's neon, which is the ink its
# state's words wear everywhere else in the theme. Every vivid surface, in this theme
# alone.
THEME = 'body[data-ls-theme="cyberpunk"]'
VIVID = ("error", "warn", "maintenance", "undefined")
EVERY_STATE = ":is(.s-error, .s-warn, .s-maintenance, .s-undefined)"
FAILING = ":is(.s-error, .s-warn)"
TUBES = (
    f"{THEME} :is(.status-card, .status-node){EVERY_STATE}:not(.dim)",
    f"{THEME} .status-card.is-closed.dim{FAILING}",
    f"{THEME} .tree-chip{FAILING}",
    f"{THEME} .ls-strip{EVERY_STATE}",
)
WORDS = (
    f"{THEME} .status-card{EVERY_STATE}:not(.dim) > .status-card__head"
    " > .status-card__name",
    f"{THEME} .status-card{EVERY_STATE}:not(.dim) > .status-card__head > .node-controls"
    " > .status-card__state",
    f"{THEME} .status-card.is-closed.dim{FAILING} > .status-card__head"
    " > .status-card__name",
    f"{THEME} .status-card.is-closed.dim{FAILING} > .status-card__head > .node-controls"
    " > .status-card__state",
    f"{THEME} .status-node{EVERY_STATE}:not(.dim) > .status-node__self"
    " > .status-node__name",
    f"{THEME} .status-node{EVERY_STATE}:not(.dim) > .status-node__self > .node-controls"
    " > .status-node__state",
    f"{THEME} .tree-chip{FAILING} > .tree-chip__name",
    f"{THEME} .ls-strip{EVERY_STATE} > .ls-strip__name",
    f"{THEME} .ls-strip{EVERY_STATE} > .ls-strip__state",
)


class CyberpunkCulpritTests(TestCase):
    """The culprit a neon tube in the theme's own neons, on every vivid surface."""

    @classmethod
    def setUpClass(cls):
        cls.blocks = _blocks(STYLESHEET.read_text(encoding="utf-8"))
        cls.rules = _by_selector(cls.blocks)
        cls.theme = _tokens(cls.blocks, THEME)

    def test_a_culprit_is_lit_dark_glass_and_its_words_white_hot(self):
        # the theme's own block restates each vivid pair: a fill a little off the
        # canvas, where today's were the plain theme's lit fills, and words that
        # read at 13:1 or more on it
        canvas = _rgb(self.theme["--ls-canvas"])
        own = re.findall(r"(--ls-[\w-]+)\s*:", self.blocks[THEME])
        for state in VIVID:
            with self.subTest(state=state):
                self.assertIn(f"--ls-{state}", own)
                self.assertIn(f"--ls-{state}-ink", own)
                fill = _rgb(self.theme[f"--ls-{state}"])
                off = _ratio(fill, canvas)
                self.assertGreater(off, 1.1, f"{state}'s glass is unlit, {off:.2f}:1")
                self.assertLess(off, 1.5, f"{state}'s glass is a lit fill, {off:.2f}:1")
                words = _ratio(_rgb(self.theme[f"--ls-{state}-ink"]), fill)
                self.assertGreaterEqual(round(words, 2), 13.0,
                                        f"the {state} words are {words:.2f}:1")

    def test_each_state_burns_in_the_neon_its_words_wear(self):
        for state in VIVID:
            rule = self.rules[f"{THEME} :is(.status-card, .status-node, .tree-chip,"
                              f" .ls-strip).s-{state}"]
            with self.subTest(state=state):
                self.assertEqual(rule.strip(),
                                 f"--ls-neon: var(--ls-tint-{state}-ink);")
                # the edge is a graphic, and clears its bar against the canvas
                edge = _ratio(_rgb(self.theme[f"--ls-tint-{state}-ink"]),
                              _rgb(self.theme["--ls-canvas"]))
                self.assertGreaterEqual(round(edge, 2), GRAPHICS)

    def test_every_vivid_surface_is_a_tube_drawn_from_its_neon(self):
        for tube in TUBES:
            with self.subTest(tube=tube):
                rule = self.rules[tube]
                self.assertIn("border-color: var(--ls-neon)", rule)
                shadow = re.search(r"box-shadow:([^;]+);", rule).group(1)
                self.assertRegex(shadow, r"^\s*0 0 0 1px var\(--ls-neon\),")
                self.assertRegex(shadow, r"inset 0 0 \d+px color-mix\(in srgb, "
                                         r"var\(--ls-neon\) \d+%, transparent\)")
                self.assertRegex(shadow, r",\s*0 0 \d+px color-mix\(in srgb, "
                                         r"var\(--ls-neon\) \d+%, transparent\)\s*$")
                self.assertNotRegex(rule, r"#[0-9a-fA-F]{3,6}\b")

    def test_every_culprits_words_wear_a_halo_of_its_neon(self):
        for words in WORDS:
            with self.subTest(words=words):
                rule = self.rules[words]
                self.assertRegex(rule, r"text-shadow:\s*0 0 \d+px var\(--ls-neon\)"
                                       r"(,\s*0 0 \d+px var\(--ls-neon\))+;")
                self.assertNotRegex(rule, r"opacity\s*:")

    def test_the_tube_is_this_themes_alone(self):
        for selector, body in self.blocks.items():
            if "--ls-neon" in body:
                with self.subTest(selector=selector):
                    for part in _selectors(selector):
                        self.assertTrue(part.startswith(THEME + " "), part)

    def test_the_pip_keeps_its_edge_and_the_warned_mark_its_amber(self):
        # two marks painted from the vivid fills, which the glass turned dark: the
        # pause pip on a parent's head is ringed in maintenance's neon, and the warned
        # triangle on a measure's curve filled with the warning's
        pip = self.rules[f"{THEME} .maintenance-pip"]
        self.assertRegex(pip, r"box-shadow:\s*0 0 0 1px "
                              r"var\(--ls-tint-maintenance-ink\)")
        warned = self.rules[f"{THEME} .ls-curve__warned"]
        self.assertIn("fill: var(--ls-tint-warn-ink)", warned)
        amber = _ratio(_rgb(self.theme["--ls-tint-warn-ink"]), _rgb(DROPDOWN["dark"]))
        self.assertGreaterEqual(round(amber, 2), GRAPHICS)



# A culprit's words on its vivid fill (ADR-0028): every
# vivid pair clears the bar in every theme — its name and its lines at full ink,
# and its state word at the weight the sheet gives it, which lifts an error's and a
# warning's to the full ink and leaves maintenance's and undefined's at the quiet
# opacity every state word starts from.
STATE_WORDS = (".status-card__state", ".status-node__state", ".ls-strip__state")
LIFTED = ("error", "warn")


def _resolved(palette, token):
    """A token's color, following a token that names another (`var(--ls-…)`)."""
    value = palette[token]
    while value.startswith("var("):
        value = palette[re.fullmatch(r"var\((--ls-[\w-]+)\)", value).group(1)]
    return value


def _in_order(css):
    """Every rule of the sheet as ``(selector, body)``, in the sheet's order — a
    selector stated twice is two rules, which :func:`_blocks` keeps one of."""
    css = _strip_comments(css)
    out = []
    for match in re.finditer(r"(?m)^\s*([^{}@\s][^{}]*?)\s*\{", css):
        depth, i = 1, match.end()
        while depth:
            depth += {"{": 1, "}": -1}.get(css[i], 0)
            i += 1
        out.append((match.group(1).strip(), css[match.end():i - 1]))
    return out


class VividWordsTests(TestCase):
    """Every culprit's words read on its fill, in every theme."""

    @classmethod
    def setUpClass(cls):
        css = STYLESHEET.read_text(encoding="utf-8")
        cls.blocks = _blocks(css)
        cls.in_order = _in_order(css)

    def _quiet(self):
        """The opacity a state word starts from: the last one the sheet gives each of
        the three on its own, the same for all three."""
        alphas = set()
        for word in STATE_WORDS:
            given = [float(found.group(1)) for selector, body in self.in_order
                     if word in _selectors(selector)
                     for found in [re.search(r"opacity:\s*([\d.]+)", body)] if found]
            self.assertTrue(given, word)
            alphas.add(given[-1])
        self.assertEqual(len(alphas), 1, alphas)
        return alphas.pop()

    def test_only_an_errors_and_a_warnings_state_word_is_lifted(self):
        # what the quiet opacity below is measured for: the rules that lift a state
        # word to the full ink name an error's and a warning's, and no other state's
        lifts = [selector for selector, body in self.blocks.items()
                 if re.search(r"(?m)^\s*opacity:\s*1\s*;", body)
                 and any(word in selector for word in STATE_WORDS)]
        named = {state for selector in lifts
                 for state in re.findall(r"\.s-(\w+)", selector)}
        self.assertEqual(named, set(LIFTED))

    def test_every_culprits_words_clear_aa_in_every_theme(self):
        quiet = self._quiet()
        for theme, selector, _ in THEMES:
            palette = _tokens(self.blocks, selector)
            for state in ("error", "warn", "maintenance", "undefined"):
                fill = _rgb(_resolved(palette, f"--ls-{state}"))
                ink = _rgb(_resolved(palette, f"--ls-{state}-ink"))
                weight = 1.0 if state in LIFTED else quiet
                with self.subTest(theme=theme, state=state):
                    name = _ratio(ink, fill)
                    self.assertGreaterEqual(round(name, 2), AA,
                                            f"{state}'s words are {name:.2f}:1")
                    word = _ratio(_over(ink, fill, weight), fill)
                    self.assertGreaterEqual(round(word, 2), AA,
                                            f"{state}'s state word is {word:.2f}:1")
