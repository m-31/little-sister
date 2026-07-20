# Little Sister — Testing the web UI

The web surface has to hold its shape against **extremes**, not just the friendly
local tree — a card drowning in a hundred linked reasons, a 200-line `code()`
block, a tree eight levels deep, a node that falls silent. Two dev-only harnesses
under `tests/` let you see the GUI under synthetic scenarios **without a real
deployment**: a **static fixture sheet** for judging layout (the fast loop) and a
**live demo** for the dynamics a static page can't show. Both render the *real*
templates, so a variant that looks right here is most of the implementation.

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
tier isolates one extreme beside a calm neighbour: all-OK overviews at 2/10/40
hosts, a 12- and a 100-linked-reason eruption, a 200-line `code()` reason, a
15-leaf host, a depth-8 tree, over-long names/titles/`about`, a
live+stale+idle+maintenance mix, graduated reason counts (cap boundaries), the
empty engine-down tree, and the engine-start failure banner (a `Fixture` with
`engine_error` set renders the header alert over the empty grid). A second,
**realistic-wall** tier embeds the extremes in a
populated overview (all content synthetic): an 80-root mixed wall (root scale), a
multi-front incident wall (eruption + trace + stale/idle/maintenance at once), an
**OK** severity leaf flooding 150 long audit findings (the real-deployment case
that once made a skyscraper column — since the #24 chips it collapses to one
quiet pill, the flood living on its leaf page), and single-token reasons — a
~300-char URL, an image digest, a 500-char `code()` line — that stress *width*
rather than length. Add a case by appending a `Fixture` there; every fixture is
also rendered as a smoke test in `tests/test_ui_fixtures.py`, so a template that
breaks on an extreme is caught by the gate.

---

## Mode 2 — the live demo (dynamics)

Some things only show live: the ~10-second poll/swap, an eruption reflowing its
neighbours, a node ageing into **stale**, a popover surviving a fragment swap,
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

The demo tree cycles on fast frequencies. Each node in `tests/demo_checks/*.yaml`
names a scenario, replayed by `tests/demo_check.py` as a pure function of elapsed
time:

- **escalate** — ok → warn → error with a *growing* reason list → recover.
- **eruption** — mostly ok, then a burst of 12 linked failures, then recovery.
- **flap** — flips healthy/failed each half-cycle (stresses the fragment swap).
- **silent** — a branch whose `cache` child falls silent mid-cycle: it stops being
  reported, ages past the freshness threshold, and shows **stale**, then returns
  fresh. (This is how a live check demonstrates staleness — the tree never prunes
  an omitted child, it lets it age.)
- **children** — disk / memory / load in a shifting mix, so the card's roll-up
  moves.
- **audit** — a wiz-style findings leaf that stays **OK** while its reason list
  swells to ~150 long lines, then clears: a skyscraper card growing and
  collapsing under the poll without ever changing colour.

**Maintenance** is not a scenario — a check cannot set a real maintenance pin
(that is the tree's concern). Demo it from the admin **Set maintenance** button on
any node (`pan` is an admin).

---

## Not part of a deployment

Both harnesses are **dev-only**: they live under `tests/`, carry no real checks,
and start no engine except when you run the demo wrapper. Keep them green with the
rest of the gate — `ruff` + `mypy` + `pytest`.
