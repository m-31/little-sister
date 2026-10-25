# ADR-0028 — Design tokens: one named palette, and a theme is an override of it

- **Status:** Accepted
- **Date:** 2026-10-25 (accepted 2026-08-01)
- **Related:** [`../architecture.md`](../architecture.md) §6 (the dim/vivid status
  model this paints), [ADR-0005](0005-dashboard-freshness-and-self-monitoring.md) (the freshness
  signals a theme must not weaken),
  [ADR-0029](0029-per-user-presentation-preferences.md) (how a viewer chooses one, and
  which theme a browser that never chose draws in),
  [ADR-0127](0127-the-wall-is-a-tree-and-a-click-opens-or-closes-a-node.md) (decision
  12: the runs' estimate a theme's letter feeds).
- **Register:** [`../decisions.md`](../decisions.md)

## Context
Every color the web surface painted was a literal in `overview.css`. That was fine while
there was one scheme, and it stopped being fine the moment a second was wanted: a dark
mode, a roster of themes, and — later — a deployment restyling the surface without
forking the packaged templates. Each of those, against literals, means copying rules and
editing the copies, so the schemes drift apart one fix at a time.

The surface also already had a **model**, and it was not the one the design sheets used.
The sheets described a warn card as a pale box with a filled "reason box" inside and a
colored status word. What actually ships is the dim/vivid split: per status a
**vivid** fill for a node reporting its own problem — the culprit — and a **pale tint**
for a node that is merely healthy or derived, each with the ink that reads on it. Any
token vocabulary had to mirror the shipped model, not the sketch of it.

And colors are not decoration here. The dashboard's job is to be believed at a glance,
so a scheme that makes a warn word hard to read is a monitoring defect wearing a brand
color — the red-line fix (a stale line that rendered muted instead of red) had already
made that concrete once.

## Decision
**`overview.css` names its palette once, on `:root`, and paints only from it.** No rule
below the token block carries a literal color.

The vocabulary mirrors the shipped model, per status `S`:

- `--ls-S` — the vivid fill, and `--ls-S-ink` the ink on it. `ok` has no vivid entry: a
  healthy box is pale at every depth.
- `--ls-tint-S` — the pale fill, and `--ls-tint-S-ink` its ink; the events/history row
  tints share these, so the table and the dimmed boxes match by construction — in hue
  and ink in every theme, and in lightness wherever a theme does not restate them for
  its logs (below).
- Status **borders are not tokens**: they are `color-mix()` of the matching ink at the
  alpha the surface wants, so a scheme that moves an ink moves its edges with it.
- Chrome — canvas, ink, muted, panel, line, nav, rail, accent, and the brand mark's own
  inks — is named the same way, so a theme can re-ink the brand without forking its SVG.

**Every other level of node steps its pale fill toward its state's ink**, so that a pale
box nested in a box of its own fill — a failing host's box in the failing card, a
healthy host's in the healthy box around it — and a quiet chip in a box of its own fill
read apart from it rather than as one with it, a 22 % edge the only line between them: a
card's own boxes and chips step, and so do the boxes and chips two levels inside them,
and so on down, counting from a page's cards on a node's page as on the wall. The
template marks the node, `is-stepped`, so that one mark serves its box and its chip. How
far is each theme's, `--ls-tint-step`: 12 % in the plain palette, 14 % in cyberpunk,
whose near-black tints need the longer step, and 8 % in the dark theme and auto's dark
half, whose tints sit nearer their inks. The words on a stepped fill step the other way,
30 % toward the page's ink, so each name, count and state word reads there at the bar
or, where it was below it — the quiet OK — no lower than on the fill it stepped from;
the title keeps its own look. A culprit keeps its vivid fill, as a failing chip does.

**A theme is an override block, never a fork:** `body[data-ls-theme="…"]` restates the
variables it changes, which wins over `:root` for everything inside `<body>`. The
in-core roster is *plain* (the `:root` set itself), *vivid*, *pastel*, *dark*,
*cyberpunk* and *auto*, and **the library's theme is cyberpunk**: the one a browser that
never chose draws in where the deployment's `settings.yaml` names none (ADR-0029).
Themes whose canvas is dark also set Bootstrap's `data-bs-theme="dark"`, so stock chrome
follows where our variables do not reach; `auto` is resolved in the browser (ADR-0029)
because only it knows what the OS wants. A deployment's own theme (the web-customization
phase) arrives through this same seam.

A theme may also restate a token on one kind of page as it does on `<body>`: an override
one level down, never a fork. Cyberpunk does so on its logs — the Events page and a
node's History tab, each a `.ls-log` — where its near-black tints lie so close to the
canvas that only their hues would tell a log's rows apart, an error's the faintest of
all. There the five status tints stand half the way toward a weight by status, a
failure's row lifted off the canvas, maintenance's between and ok's sunk toward it, so a
failure stands out of a log that is mostly recoveries; and each row's status word wears
its state's ink with the theme's glow, undefined's without one. So in cyberpunk the
tables and the dimmed boxes differ in lightness, never in hue or ink; the wall and a
node's Status tab keep the theme's tints.

**Cyberpunk's culprit is a neon tube.** The theme's block restates the four vivid pairs
as lit dark glass under white-hot words, and each state's neon — the ink its words wear
elsewhere in the theme, `--ls-tint-S-ink`, set on the surface as the theme's own
`--ls-neon` rather than as a token of the palette — draws the tube's edge, an inner and
an outer glow, and a halo on its name and state word, on every vivid surface: a failing
box or card, a closed card that fails, a failing chip and the heartbeat pill. Its words
read at 13:1 or more, and since they are white the neon is a second color, handed to
each word's halo by name. The two marks painted from the vivid fills follow: the pause
pip keeps an edge in maintenance's neon, and a measure's warned triangle is filled with
the warning's. And since the theme draws in a monospace face, where every character of
a chip's name is a whole `0`, its block says so to the runs' estimate before the script,
with `--ls-chip-letter: 1` where the system's faces take 0.85
([ADR-0127](0127-the-wall-is-a-tree-and-a-click-opens-or-closes-a-node.md) decision
12).

**The accessibility bar outranks any picked swatch.** Status text holds AA (≥4.5:1) in
every theme — plain, vivid, pastel, dark and cyberpunk. Concretely: **light themes
render status words in their dark state inks — yellow lives on surfaces, never as words
there — and dark themes may use bright words**, which clear the bar on a dark canvas.
Every vivid fill but cyberpunk's glass takes a dark ink, maintenance's and undefined's
as an error's and a warning's do; a state word on those two keeps the quiet 80 % an
error's and a warning's are lifted from, so each ink is as dark as keeps that word over
the bar too — `#030810` reads 6.06:1 on the blue and 4.77:1 at 80 %, `#15181b` 6.75:1 on
the grey and 4.81:1 at 80 % — and every culprit's words are measured, from the tokens
and in the browser. Every pale pair but the quiet OK's keeps a state word over the bar
at the quiet 80 % — the undefined pair's ink is `#45494d`, 7.97:1 on its tint and 4.75:1
at 80 % in the plain palette, which the vivid and pastel themes keep, and cyberpunk's
`#86a0ae`, 6.75:1 and 4.73:1, the undefined culprit's neon there too, where the dark
theme's reads 5.15:1 — and the contrast test holds every pale pair's state word in every
theme, so that none falls below the bar where one appears. Cyberpunk's muted ink,
`#6593a5`, reads 4.61:1 on Bootstrap's dark `#212529`, the surface the contrast test
reads six rows on — the menu's headings and its disabled item, the links page's aside
and the curve's axes words — and 5.5:1 or more on the theme's own surfaces; the contrast
test and the browser's sweep gate it with the others. When a pick and the bar collide
the bar wins and **the pick finds a different vehicle**, flagged for a look, never
silently both. Two recorded exceptions, both deliberate:

- the **quiet OK** — the healthy status word and the strip's state sit at `opacity: .8`
  and measure 3.6–4.1:1 in the light themes. A healthy node is meant to recede, the
  shape cue is its non-color channel, and only the problem states are lifted to full
  weight. Not a defect; do not "fix" it in a later pass.
- the **wordmark** is brand, not status: at 19px/600 it is large text, where the bar is
  3:1, and every theme's accent clears that.

Verification is by **computed style and rendered pixels, never class presence** — the
red-line lesson — measured per theme.

## Consequences
- A restyle is a set of variables. Adding a scheme adds no rules and cannot drift from
  the others, because there is only one set of rules.
- Status-color verification becomes a per-theme sweep: every signal's *computed* color
  against its effective background, opacity folded in. That found real defects the first
  time it ran — light ink on the dark theme's amber at 2.75:1, and white on the error
  red at 3.16:1 in **every** theme, shipped long before the roster existed.
- Bootstrap's stock chrome follows only where `data-bs-theme` reaches; anything of ours
  that borrowed a Bootstrap utility color (`.bg-light` on the bar) had to move onto a
  token, or a dark theme would wear a white bar.
- `auto` duplicates the dark block inside a `prefers-color-scheme` query, because a
  media query cannot share a selector with a rule outside it. A test compares the two
  blocks so they cannot drift.
- **A nested box stands off the box around it**: 1.16:1 to 1.46:1 where it stood at
  1.00, and a healthy box's title in the dark theme, which keeps its own look on a
  stepped fill, reads 4.3:1 where it read 4.7.
- One token, `--ls-warn-accent`, is defined and deliberately unused: it is the picked Y3
  yellow, barred from being a status word by the rule above, kept for a decorative use
  at ≥3:1. If none materializes it retires unused, which is an acceptable outcome.

## Alternatives considered
- **Per-theme stylesheets.** Rejected: the same forking the tokens exist to prevent, and
  four copies of every rule to keep in step.
- **Sass variables compiled per theme.** Rejected: adds a build step to a project that
  ships plain static files, and the values would stop being inspectable in the browser —
  which is exactly where the per-theme verification has to happen.
- **The sheets' three-slot warn vocabulary** (`warn-bg`, `warn-word`, `reason-bg`).
  Rejected: it describes a card that does not exist here. Mapping it onto the shipped
  dim/vivid model is what this ADR records instead.
- **A firmer edge alone** for a nested box: it drew the line and left the fills alike.
- **A step at every level**: it put the third level's words below the bar in the plain
  theme, and past it gave a box its parent's fill again.
- **The tint on the card alone**: it gave two failing boxes inside each other one
  neutral fill again.
- **Tokenizing borders as their own variables.** Rejected: the alphas differ per surface
  (22/25/28/50%), so it would have meant several border tokens per status that a theme
  would have to remember to move together with the ink.
