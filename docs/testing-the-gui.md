# Little Sister — Testing the web UI

The web surface has to hold its shape against **extremes**, not just the friendly
local tree — a card drowning in a hundred linked reasons, a 200-line `code()`
block, a tree eight levels deep, a node that falls silent — and it has to hold it
in every theme. Four dev-only harnesses under `tests/` let you see the GUI under
synthetic scenarios **without a real deployment**: a **static fixture sheet** for
judging layout (the fast loop), a **live demo** for the dynamics a static page
can't show, a **render matrix** that shoots `/links` across the theme roster, and
a **contrast sweep** that measures what the eye cannot judge. All render the
*real* templates, so a variant that looks right here is most of the
implementation.

---

## Mode 1 — the static fixture sheet (layout)

`tests/render_ui_fixtures.py` feeds hand-built extreme fixtures through the real
`status.html` / `_status_grid.html` and writes one static HTML page each — no
server, no engine, no login:

```bash
uv run python tests/render_ui_fixtures.py
```

It writes `var/ui-harness/*.html` plus an `index.html` (all git-ignored) and prints
the path; open the index in a browser (`open var/ui-harness/index.html` on macOS).
Pass `--out DIR` for a different location.

**The edit loop.** The pages link the packaged stylesheet by a relative path, so
edit `src/little_sister/static/css/overview.css` (or a template), re-run the
command, and refresh — you compare a CSS or template variant across every fixture
at a glance. (Bootstrap loads from a CDN, so view the sheet online; your
`overview.css` loads from disk either way.)

**The fixtures** live in `tests/ui_fixtures.py` (the `FIXTURES` list). The first
tier isolates one extreme beside a calm neighbor: all-OK overviews at 2/10/40
hosts, a 12- and a 100-linked-reason eruption, a 200-line `code()` reason, a
15-leaf host, a depth-8 tree, over-long names/titles/`about`, a
live+stale+idle+maintenance mix, graduated reason counts (cap boundaries), the
empty engine-down tree, and the engine-start failure banner (a `Fixture` with
`engine_error` set renders the header alert over the empty grid). A second,
**realistic-wall** tier embeds the extremes in a
populated overview (all content synthetic): an 80-root mixed wall (root scale), a
multi-front incident wall (eruption + trace + stale/idle/maintenance at once), an
**OK** severity leaf flooding 150 long audit findings (the real-deployment case
that once made a skyscraper column — since the ADR-0024 chips it collapses to one
quiet pill, the flood living on its leaf page), and single-token reasons — a
~300-char URL, an image digest, a 500-char `code()` line — that stress *width*
rather than length. Add a case by appending a `Fixture` there; every fixture is
also rendered as a smoke test in `tests/test_ui_fixtures.py`, so a template that
breaks on an extreme is caught by the gate.

---

## Mode 2 — the live demo (dynamics)

Some things only show live: the ~10-second poll/swap, an eruption reflowing its
neighbors, a node ageing into **stale**, a popover surviving a fragment swap,
the freshness line escalating into the outage banner (stop the server and wait
out six polls).
`tests/demo_wsgi.py` is a dev WSGI wrapper that registers a scripted `demo` check
type and starts the engine against a demo tree — dogfooding the same public
`CHECK_TYPES` seam a real deployment uses (see
[`implementing-checks.md`](implementing-checks.md) §4):

```bash
uv run gunicorn -w1 --threads 8 tests.demo_wsgi:app     # then http://localhost:8000
# or the Flask dev server:
uv run python tests/demo_wsgi.py
```

Log in with the committed fixture user **`pan` / `12345678`**. Use a single worker:
the engine and the status tree live in-process.

The demo tree cycles on fast frequencies. Each node in `tests/demo_config/checks/*.yaml`
names a scenario, replayed by `tests/demo_check.py` as a pure function of elapsed
time:

- **escalate** — ok → warn → error with a *growing* reason list → recover.
- **eruption** — mostly ok, then a burst of 12 linked failures, then recovery. It
  stays **prose** on purpose: it sits one card away from `reviews`, so one dashboard
  carries two long reason lists that look alike and behave differently.
- **flap** — flips healthy/failed each half-cycle (stresses the fragment swap).
- **silent** — a branch whose `cache` child falls silent mid-cycle: it stops being
  reported, ages past the freshness threshold, and shows **stale**, then returns
  fresh. (This is how a live check demonstrates staleness — the tree never prunes
  an omitted child, it lets it age.)
- **children** — disk / memory / load in a shifting mix, so the card's roll-up
  moves.
- **audit** — a wiz-style findings leaf that stays **OK** while its reason list
  swells to ~150 long lines, then clears: a skyscraper card growing and
  collapsing under the poll without ever changing color. Its findings are
  **members** (see below).
- **reviews** — a small queue of pull requests waiting for a reviewer, whose reasons
  are a keyed **mapping**. Never empty, never more than six lines, and re-worded on
  every run.

### Members, and the two slug promises

Nothing the library itself emits declares members — every built-in reason is prose,
by design ([ADR-0036](adr/0036-addressable-reasons.md)) — so without a producer here
the per-line pin control cannot be clicked at all, and the only way to see an entry
pin was to hand-write a check. The demo is the right home for one precisely *because*
it is not shipped: `tests/` is dev-only scaffolding, so a findings-style scenario
gives a clickable control without borrowing a deployment's private check type, and
nothing under `tests/` ever becomes a built-in.

The two nodes are a **pair**, and each shows the promise the other cannot:

- `/security/audit` is **derived**. Its check config carries one extra line,
  `entries: true`, which reads the same reason list as members instead of prose; the
  slug is then a hash of each line's text. The scenario's finding texts are constant
  across runs — only the *count* grows — so a pin set on finding 7 survives the list
  swelling to ~150 and back. That is the ergonomic claim the ADR makes for derived
  slugs (return a stable string and per-entry pins just work), demonstrated by data
  that does not change at all. Flip the line off to compare the same node as prose.
- `/ci/reviews` is **declared**. Its slugs are the pull requests' own numbers, and
  every line is rebuilt with a fresh waiting time each run — so the text moves on
  more or less every poll while the key does not. A pin set on `pr-4833` holds
  straight through that; under a derived slug the same edit would drop it, because
  there the slug *is* the wording. Watch a pin through the churn, too: one review is
  merged near the end of the cycle and another opens mid-cycle.

What that costs is worth seeing once: `check.html` renders every reason, so on the
audit leaf **members means ~150 per-line forms on one page**. The review queue is the
pleasant everyday version, and it is deliberately small enough to pin *every* member,
which is the case worth walking: with all of them pinned the card reads
**MAINTENANCE** on the dashboard, the strip pill's popover says *all 5 reasons* — the
row that explains the blue card — and `/maintenance` lists each pin with the line it
silences. Click one of those rows and you land on that line, marked, rather than at
the top of the page. Pin a line on `/security/audit` too, and then wait out a cycle:
the audit list clears at the end of it, and the node page tells you the pin's line is
no longer being reported rather than leaving you to wonder.

### What the demo tree carries besides its checks

`tests/demo_config/` is a configuration root like any other, and it grew the aspects
that make the features above visible:

- **`settings.yaml`** turns the budgeted failure retry on
  ([ADR-0033](adr/0033-budgeted-failure-retry.md)) so `/system` has a retry marker to
  show. Two seconds, which is shorter than every demo frequency — the retry only ever
  pulls a check's next run *earlier*, so a longer interval would be a no-op. Two
  things to watch: `/network/vpn` flaps, so each recovery re-arms its budget and it
  is in `retry 1/6`, `2/6`, … for the whole of every red window; `/ci/reviews` never
  recovers, so it spends its six fast attempts once and settles back — that is the
  *budget* in the name.
- **`nodes.yaml`** labels the container nodes (`/ci`, `/security`, …), which the tree
  creates from the check paths and no check owns. Without it the dashboard is a wall
  of bare path segments. It also names the engine's heartbeat, which feeds the status
  strip's hover card.
- **`actions.yaml`** puts a deployment's own links on the pages — see below.
- **`links/links.yaml`**, so `/links` has a page worth judging: many groups, a title
  long enough to wrap, notes, and every rung of the icon search path — a built-in
  pair, a deployment's own single file (on the chip), a deployment-supplied pair
  (rendered bare), a built-in switched off with `none`, and a name nothing defines.
  It takes the **directory** form (`links/links.yaml` with `links/icons/` beside it),
  which is the shape an aspect that ships files grows into: an `icons/` directory
  sitting next to a `config/links.yaml` is a directory in a configuration root, and
  the loader would rightly warn that `icons` is not a known aspect.

### The two ways a slot gets filled

The demo fills both template slots
([ADR-0034](adr/0034-template-slots-for-dependent-packages.md)) twice over, because
the two routes to a chip have different things to show and they land in the same
rail.

**Configured, no code at all.** `demo_config/actions.yaml` is the declarative list
([ADR-0038](adr/0038-declarative-action-list.md)): `actions` is a built-in aspect and
the library registers its own filler for both slots, so the file alone makes both
slots draw. It exercises URL templating (`{path}` `{name}` `{code}` `{reason}`
`{reasons}`), the percent-encoding on the way in — open **File it** on the audit leaf
and the body is ~150 findings full of parentheses and dashes, every one of them
encoded; a very long href is the honest consequence — icon resolution through the
links registry (the **Nudge** chip wears the deployment's own `phoenix` mark), and
`under:` scoping (**Runbook** appears on `/security` and nowhere else).

**Coded, in `demo_wsgi.py`.** Two `slots.register` calls against `tests/demo_extension`
and one `register_assets`. What only this half can show: a provider that **declines**
with `None`, so a chip is present on some lines and absent on others — on
`/ci/reviews` the review waiting on its *author* gets no coded chip while its
neighbors do, and the configured entry, which has no way to express that, sits on all
of them; two fillers in one rail, so the promise that a configured chip and a coded
one land together in one order can be looked at rather than believed — both are
`.reason-action` siblings inside one `reason-actions` span, the wrapper's first
because it registered before the app import did; and `/ext/<package>/<member>`
([ADR-0037](adr/0037-extension-static-assets.md)), the route serving an extension's
own stylesheet and script from our origin — `demo.css` italicizes the node chip, so
if it is upright the asset route is broken.

The reason-level action is scoped narrowly from both sides (the configured entry by
`under:`, the coded one by its provider's own reason budget), which is not fussiness:
`reason.actions` is offered on *every* reason of every node, so an unscoped entry
puts a chip on each of the ~150 audit findings.

One free check while you are here: switch the layout to **kiosk** and both slots
vanish. That is the `_slot()` gate demonstrating itself.

### Maintenance

Maintenance is not a scenario — a check cannot set a real pin (that is the tree's
concern). Set one from the admin **Set maintenance** button on any node (`pan` is an
admin), or from the per-line control on `/ci/reviews` and `/security/audit`.

The **conflict page** needs no code either, only a recipe, because it is about two
people and one node. Every maintenance form carries the pin's `set_at` as a
compare-and-set token, and an *empty* token says "I believe nothing is pinned" — so
the shortest way in is two tabs on an **unpinned** node:

1. Open the same node's page in **two tabs** and open the Set-maintenance dialog in
   both. Neither form has a token yet.
2. Submit one of them.
3. Submit the other. The table now says something is pinned, its empty token no
   longer matches, and instead of silently overwriting the first pin you land on the
   conflict page — both reasons side by side, your own words intact.

Editing works the same way with a real token: open an existing pin's edit form in two
tabs, submit the newer, then the older. An **entry** pin conflicts identically and
the page carries its slug, so the two tabs can be two per-line pins on the same
reason of `/ci/reviews`.

---

## Mode 3 — the links render matrix (themes)

The whole point of the icon design is surviving the theme roster, which is not
something to reason about. `tests/render_links_matrix.py` runs a real server
against the demo links configuration, serves Bootstrap from disk so the shot is
faithful offline, and walks six themes × two layouts into `var/ui-harness/links/`:

```bash
npm i --prefix var/bootstrap bootstrap@5.3.2     # once; var/ is gitignored
uv run python tests/render_links_matrix.py
```

Vendoring into `var/` is deliberate: an `npm i` in the repo root would leave
`node_modules/`, a `package.json` and a lockfile untracked beside the source, and
the release check walks the tree. Skip the install and the CDN request is simply
let through, which needs the network.

It needs Playwright and a browser, so it is **not** part of the gate. What to look
for: the light/dark pair actually swapping between the light and dark themes, the
chip keeping a single-file mark legible on every canvas, a wrapped title hanging
under the text rather than the icon, and the neutral glyph standing in wherever a
favicon could not be fetched. The **filter** needs a real browser rather than a
screenshot: type a category name (`loadtest`) and the whole category should stand
alone, `Esc` should put every entry back, and the count beside the box should track
what is showing.

---

## Mode 4 — the contrast sweep (color)

The other three modes are for *looking*. Contrast is the one property looking is
bad at: a red that reads fine to you can be under the bar, and the accessibility
bar outranks any picked swatch. `tests/sweep_contrast.py` walks every theme — the
settings menu opened on `/status`, then the rows on `/links` that are not plain
body text — and measures each as the eye actually gets it: the *computed* ink,
the background composited from every translucent layer above the first opaque
one, stacked opacity folded in. It prints the WCAG ratio:

```bash
npm i --prefix var/bootstrap bootstrap@5.3.2     # once; var/ is gitignored
uv run python tests/sweep_contrast.py
```

It exits non-zero if a gated theme misses AA. Cyberpunk is the declared fun
theme: measured and reported, never gated.

**Why a browser, when the tokens are right there.** The menu is a Bootstrap
dropdown, and *Bootstrap paints it*: `.ls-menu__panel` sets a width and a
padding, but the fill is `--bs-dropdown-bg` and the inherited ink is
`--bs-dropdown-color`. So a row sits on white in a light theme and on `#212529`
wherever `data-bs-theme="dark"` is set — cyberpunk included, whose own panel
token never reaches it — and a row taking `color: inherit` is `#dee2e6` there,
not our ink. Reasoning about the menu from our tokens is how a logout link came
to sit at 3.41:1 while everything nearby was measured and fine. This is what
finds a surface we do not own; it is also what re-checks those two constants when
the Bootstrap pin moves.

It found the second one the same way: the links page's *check now* button was
written as a `btn-outline-secondary`, which Bootstrap paints `#6c757d` on **every**
canvas — 3.76:1 on the dark one. The button now wears `btn btn-sm` for the shape
and takes its ink from our tokens, which is the general answer whenever a
Bootstrap component's own colour has to hold the bar on six canvases.

The /about hero needs neither half: it paints no surface, so every reading of it
is a token on the canvas and the gate test measures all of them. Use a browser
there for the thing no measurement covers — that the term the eyes are on and
the phrase it names in the prose light **together**.

**And the gate half.** `tests/test_contrast.py` measures the same rows with no
browser at all, folding the sheet's own inks and hover wash exactly as the
browser folds them, against the two surfaces above written down as constants. It
runs on every commit, so the regression this harness would have caught cannot
land again between manual runs — but it can only measure surfaces someone already
knew about. The two are a pair: the sweep discovers, the test remembers.

---

## Not part of a deployment

All four harnesses are **dev-only**: they live under `tests/`, carry no real
checks, and start no engine except when you run the demo wrapper. Keep them green
with the rest of the gate — `ruff` + `mypy` + `pytest`.
