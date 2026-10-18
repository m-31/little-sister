# ADR-0029 — Presentation preferences live in a cookie, not in the server

- **Status:** Accepted
- **Date:** 2026-10-18 (accepted 2026-08-01)
- **Related:** [ADR-0028](0028-design-tokens-and-themes.md) (what a theme *is*, and the
  library's), [ADR-0019](0019-inspection-popover.md) (the inspection card a look opens),
  [ADR-0127](0127-the-wall-is-a-tree-and-a-click-opens-or-closes-a-node.md) (decisions
  11 and 12: how a row answers the pointer, and how a run of chips is drawn),
  [ADR-0001](0001-in-process-threaded-engine.md) / [ADR-0002](0002-rlock-snapshot-synchronization.md)
  (why there is nowhere to put server state),
  [ADR-0014](0014-maintenance-persistence.md) (the one thing that *is* persisted).
- **Register:** [`../decisions.md`](../decisions.md)

## Context
The surface grew choices that belong to the person looking at it: a **theme** from the
in-core roster, a **layout** — the collapsed rail, the top bar, or the kiosk wall
display — and the wall's **looks**: how a run of chips is drawn, whether the inspection
card opens on a pause, how a head's row and a chip answer the pointer. Two viewers of
the same deployment can reasonably want different answers, and the same person can want
a different answer on the wall-mounted screen in the corridor than on their laptop.

little-sister has no durable store on purpose (ADR-0001/0002): state is in memory and
the only thing that survives a restart is admin maintenance, in a `var/` file
(ADR-0014). Adding a user-preferences table would drag the persistence decision forward
years ahead of the phase that is supposed to make it.

The surface already had the shape of an answer. Depth and the filter switches have been
remembered per browser in year-long cookies since the dashboard's early slices — the
same class of thing, the same lifetime, the same "if it's lost, nothing breaks".

A theme must also be applied **before the first paint**. A preference resolved in
JavaScript after load means every navigation flashes the wrong scheme, which is worse
than having no themes at all.

## Decision
**One long-lived cookie per browser holds the presentation preferences**, and the server
renders them onto `<body>`: the layout as `data-ls-layout`, and each look as `data-ls-`
and its key with hyphens, the theme as `data-ls-theme`.

- The cookie is `ls_prefs`, urlencoded (`theme=…&layout=…`) so a later key joins it
  without a migration; a year's `max-age` and `SameSite=Lax`, matching the view cookies
  it sits beside. It is **presentation only** — nothing in it changes what the surface
  *says*, only how it looks.
- **The looks are one roster**, `looks.py`: the theme, `theme`; how a run of chips is
  drawn, `chip_runs`, `aligned` or `wrapped`
  ([ADR-0127](0127-the-wall-is-a-tree-and-a-click-opens-or-closes-a-node.md) decision
  12); whether the inspection card opens on a pause on a name, `inspection_card`,
  `pause` or `off` ([ADR-0019](0019-inspection-popover.md)); and how a head's row and a
  chip answer the pointer, `toggle_hover`, `outline` or `wash` — the outline of their
  ink, or a wash of it at 10 % in the outline's place, the outline standing under forced
  colors either way (ADR-0127 decision 11). Each look is a key of the cookie and of
  `settings.yaml`, with its values, the library's default, its group's heading and its
  values' words in the settings menu, and its attribute on `<body>`, so a look joins in
  one line and the stylesheet answers its attribute. The menu shows the theme, the
  layout, then the other looks.
- **A look's default is the deployment's**, `settings.yaml`'s, and the library's is
  `cyberpunk` ([ADR-0028](0028-design-tokens-and-themes.md)), `aligned`, `off` and
  `wash`; the layout alone keeps a constant default. So a look is written into the
  cookie only once a browser chooses it, and a browser that never chose follows a
  changed default. *Chosen* is a value the menu posts that differs from the deployment's
  default, or one that replaces a value the cookie already carried, which keeps a
  browser that chose the default on it when the deployment's changes. An unquoted `off`
  in `settings.yaml` is YAML's false, and is read as the word.
- **Every failure mode lands on the defaults, independently per key**: no cookie, an
  unparsable one, a value the roster no longer has — `theme=default`, the plain theme's
  old name, which older cookies carry, among them — a value typed by hand. A preference
  is a look, so a bad one must never be able to break a page; the worst it can do is
  show the default.
- The settings menu **posts** its choice to `/preferences`, which validates, sets the
  cookie and sends the viewer back to the page they were on. Validation therefore lives
  in one place — the server — and an edited form cannot write a value that every later
  page then has to defend against. The return path is accepted only if it is a plain
  same-site path, so the form's hidden field cannot become an open redirect.
- **Server-rendered, so no flash.** The one exception is `auto`, which follows the OS:
  the stylesheet tracks it with a `prefers-color-scheme` query, and three inline lines
  at the top of `<body>` set Bootstrap's `data-bs-theme` before anything paints, because
  that is the one fact a server cannot know.
- **The look belongs to the browser, not the session:** it survives a logout, and the
  login page wears the theme too. A kiosk browser keeps its own choice, and the kiosk
  layout's exit is simply a write of the default layout back to this cookie.
- **Logout moves into the menu.** Once the bar is only brand and user, a red button has
  nowhere to sit, and signing out is something you do to a session rather than a place
  you navigate to.
- A value the roster no longer *offers* is still **honored** if a browser already
  carries it, so a preference is never silently thrown away by a change of menu.

**Explicitly not covered:** per-user *functional* settings — overrides of `settings.yaml`
defaults, which are about what the surface reports rather than how it looks. Those need
a real store and a real identity, so they wait for the persistence phase; the menu
reserves a grayed entry for them so the seam is visible. The looks are presentation,
how the page draws what it says, although a deployment sets their defaults. And what a
viewer opens and closes on the wall stays out of the cookie: it lasts for the tab
(ADR-0127).

## Consequences
- No server state, no schema, no migration, and nothing to clean up when a user is
  removed from `users.yaml`.
- Preferences are **per browser, not per account**: the same person on a second machine
  starts from the defaults, and a shared kiosk browser keeps the kiosk's choice rather
  than the last person's. For presentation that is the behavior we want; for the
  functional settings above it would not be, which is part of why they are separate.
- Clearing cookies resets the look. Acceptable: nothing is lost but a preference.
- The cookie is not signed. It does not need to be — it selects between values the
  server already validates against a fixed roster, so the worst a forged one achieves is
  a theme the user could have picked from the menu anyway.
- `auto` is the only theme that depends on JavaScript, and only for Bootstrap's own
  chrome; without it `auto` degrades to the light scheme rather than to something broken.

## Alternatives considered
- **A cookie per key**, matching the shipped `depth` / `hide_ok` idiom. Genuinely
  tempting, and rejected so that presentation preferences read as one thing with one
  lifetime — and so a later key joins without adding another cookie to the jar.
- **JavaScript writes the cookie and reloads.** Rejected: validation would live in two
  places, and the parsing half — the half that has to survive junk — would be the half
  no test could reach.
- **Server-side per-user preferences** in `users.yaml` or a store. Rejected for now: it
  pulls the persistence decision forward, and it answers a question nobody asked, since
  a look is a property of the screen you are at, not of who you are.
- **`localStorage`.** Rejected: a second persistence mechanism competing with the
  cookie, and unreadable by the server — which would put the flash back.
