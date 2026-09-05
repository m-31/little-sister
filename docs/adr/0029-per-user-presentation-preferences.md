# ADR-0029 — Presentation preferences live in a cookie, not in the server

- **Status:** Accepted
- **Date:** 2026-08-01
- **Related:** [ADR-0028](0028-design-tokens-and-themes.md) (what a theme *is*),
  [ADR-0001](0001-in-process-threaded-engine.md) / [ADR-0002](0002-rlock-snapshot-synchronization.md)
  (why there is nowhere to put server state),
  [ADR-0014](0014-maintenance-persistence.md) (the one thing that *is* persisted).
- **Register:** [`../decisions.md`](../decisions.md)

## Context
The surface grew choices that belong to the person looking at it: a **theme** from the
in-core roster, and a **layout** — the collapsed rail, the top bar, or the kiosk wall
display. Two viewers of the same deployment can reasonably want different answers, and
the same person can want a different answer on the wall-mounted screen in the corridor
than on their laptop.

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
renders them onto `<body>` as `data-ls-theme` and `data-ls-layout`.

- The cookie is `ls_prefs`, urlencoded (`theme=…&layout=…`) so a later key joins it
  without a migration; a year's `max-age` and `SameSite=Lax`, matching the view cookies
  it sits beside. It is **presentation only** — nothing in it changes what the surface
  *says*, only how it looks.
- **Every failure mode lands on the defaults, independently per key**: no cookie, an
  unparsable one, a value the roster no longer has, a value typed by hand. A preference
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
reserves a grayed entry for them so the seam is visible.

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
