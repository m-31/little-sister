# ADR-0028 — Design tokens: one named palette, and a theme is an override of it

- **Status:** Accepted
- **Date:** 2026-08-01
- **Related:** [ADR-0024](0024-dashboard-layout.md) (the dim/vivid status model this
  paints), [ADR-0005](0005-dashboard-freshness-and-self-monitoring.md) (the freshness
  signals a theme must not weaken),
  [ADR-0029](0029-per-user-presentation-preferences.md) (how a viewer chooses one).
- **Register:** [`../decisions.md`](../decisions.md)

## Context
Every color the web surface painted was a literal in `overview.css`. That was fine while
there was one scheme, and it stopped being fine the moment a second was wanted: a dark
mode, a roster of themes, and — later — a deployment restyling the surface without
forking the packaged templates. Each of those, against literals, means copying rules and
editing the copies, so the schemes drift apart one fix at a time.

The surface also already had a **model**, and it was not the one the design sheets used.
The sheets described a warn card as a pale box with a filled "reason box" inside and a
colored status word. What actually ships is the ADR-0024 dim/vivid split: per status a
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
  tints share these, so the table and the dimmed boxes match by construction.
- Status **borders are not tokens**: they are `color-mix()` of the matching ink at the
  alpha the surface wants, so a scheme that moves an ink moves its edges with it.
- Chrome — canvas, ink, muted, panel, line, nav, rail, accent, and the brand mark's own
  inks — is named the same way, so a theme can re-ink the brand without forking its SVG.

**A theme is an override block, never a fork:** `body[data-ls-theme="…"]` restates the
variables it changes, which wins over `:root` for everything inside `<body>`. The
in-core roster is *default* (the `:root` set itself), *vivid*, *pastel*, *dark*,
*cyberpunk* and *auto*. Themes whose canvas is dark also set Bootstrap's
`data-bs-theme="dark"`, so stock chrome follows where our variables do not reach;
`auto` is resolved in the browser (ADR-0029) because only it knows what the OS wants.
A deployment's own theme (the web-customization phase) arrives through this same seam.

**The accessibility bar outranks any picked swatch.** Status text holds AA (≥4.5:1) in
default, vivid, pastel and dark. Concretely: **light themes render status words in their
dark state inks — yellow lives on surfaces, never as words there — and dark themes may
use bright words**, which clear the bar on a dark canvas. Cyberpunk is declared a fun
theme: measured and reported, not gated. When a pick and the bar collide the bar wins
and **the pick finds a different vehicle**, flagged for a look, never silently both.
Two recorded exceptions, both deliberate:

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
- **Tokenizing borders as their own variables.** Rejected: the alphas differ per surface
  (22/25/28/50%), so it would have meant several border tokens per status that a theme
  would have to remember to move together with the ink.
