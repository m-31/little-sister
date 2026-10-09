# Little Sister — Testing the web UI

The web surface has to hold its shape against **extremes**, not just the friendly
local tree — a card drowning in a hundred linked reasons, a 200-line `code()`
block, a tree eight levels deep, a node that falls silent — and it has to hold it
in every theme. Six dev-only harnesses under `tests/` let you see the GUI under
synthetic scenarios **without a real deployment**: a **static fixture sheet** for
judging layout (the fast loop), a **live demo** for the dynamics a static page
can't show, a **render matrix** that shoots `/links` across the theme roster, and
a **contrast sweep** that measures what the eye cannot judge, **browser
boundary checks** for layout claims paint has to prove, and a **walk** that goes
through the pages as a reader does and says what did not hold. All render the *real*
templates, so a variant that looks right here is most of the implementation.

---

## Mode 1 — the static fixture sheet (layout)

`tests/render_ui_fixtures.py` feeds hand-built extreme fixtures through the real
`status.html` / `_status_grid.html` and writes one static HTML page each — no
server, no engine, no login. The realistic multi-front incident also renders
through the real **Copy** page, so its complete outline, long code block and
clipboard controls sit in the same sheet:

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
empty engine-down tree, the engine-start failure banner (a `Fixture` with
`engine_error` set renders the header alert over the empty grid), an admin
member-leaf page carrying rendered node/entry maintenance explanations plus their
closed editors, a leaf page whose lines and measured record carry times — read
in the configured zone, beside a null, a time-shaped value under an untyped name and
a time past the calendar, which are shown as stored — and a subject's **series** twice
([ADR-0092](adr/0092-a-check-declares-its-measures.md)): an `http` leaf with eight hours
of response times, a burst of failed requests and one alone marked in the curve's lane,
an hour and a half asleep left plain, and the newest ten readings beneath; and a host
branch whose two measures are two curves, one of them in `%`. A `Fixture` with an
`engine` lends the page the engine its series is read from. A subject's **runs**
stand twice ([ADR-0111](adr/0111-a-runs-mark-says-how-the-run-stood.md)): a job
name's leaf whose thirty days of runs are stems to their run time — the oldest bare
and muted, having kept no verdict, a hollow ring and a mark in the lane for each
failure, the warning's triangle where the run time crept past its limit, and four
days of a run every two hours, a crowd in which a passing run's head gives way — and
a workflow's leaf with the same runs and no measure, each a tick whose height says
how it stood. A second,
**realistic-wall** tier embeds the extremes in a
populated overview (all content synthetic): an 80-root mixed wall (root scale), a
multi-front incident wall (eruption + trace + stale/idle/maintenance at once), an
overview with two tall roots, dozens of descendants, chips off and spare grid columns
(subtree balance), an
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
type and the login list's door, and points the application at a demo tree —
dogfooding the same public seams a real deployment uses (see
[`implementing-checks.md`](implementing-checks.md) §4). Importing it starts nothing:
the server's start runs the engine, so gunicorn needs the hooks module on its line
like any instance, and the development server calls the start itself:

```bash
uv run gunicorn -w1 --threads 8 --config python:little_sister.gunicorn_hooks \
    tests.demo_wsgi:app                                  # then http://localhost:8000
# or the Flask dev server:
uv run python tests/demo_wsgi.py
```

It stays on **8000** while an instance serves on 8888, and it keeps what a restart
keeps — its state directory, the lease on it, its log — in `var/demo/` rather than in
the checkout's own `var/`, so the demo and a real instance of this checkout can run
side by side rather than fighting for one port or one state directory, whose lease
admits one writer ([ADR-0090](adr/0090-one-state-directory-one-writer.md)).
`LITTLE_SISTER_DEMO_DIR` names another directory; `test_demo_check.py` uses it to
start the demo where it writes nothing into the checkout. Stop it and start it again to
see what a restart does to a history
([ADR-0094](adr/0094-a-restart-is-no-transition.md)): a node reading what it read
before keeps its period across the restart, `/events` gains an event only for a node
whose reading changed or whose pin ran out meanwhile, and `/history/little-sister`
shows the gap — *undefined, the instance was not running*, from the stop until the
first beat. For the pin
([ADR-0107](adr/0107-an-event-is-a-change-of-what-a-node-shows.md)), pin
`/services/api` for `1m`, stop the demo, and start it once the minute is over: the
node's first reading writes the pin's end — on `/events` a row with the *maintenance
ended* chip, and a second one *held back* beside it where the reading moved meanwhile
— its History closes the maintenance row at that reading, and its **Time** card says
*since* then, *when its maintenance ended*.

A pin that outlives the stop shows what a start does with one its log has lost
([ADR-0110](adr/0110-what-every-node-last-showed-is-kept-beside-the-log.md) decision
6). Pin `/storage/backup` for a day, stop the demo, put an empty log in the kept one's
place, and start it:

```bash
echo '{"events": []}' > var/demo/var/state/events.json
uv run python tests/demo_wsgi.py
```

The node's **Time** card says *maintenance since* the moment it was pinned — the
instant its block gives under *Edit*, *Pinned by …* — and not since this start, while
`/events?under=/storage/backup` lists the pin's set at the start, when this log learned
of it. Clear the pin afterwards.

For the wait
([ADR-0110](adr/0110-what-every-node-last-showed-is-kept-beside-the-log.md)) a start
has to find a failure, and every scenario starts at the top of its cycle, where none
fails. `LITTLE_SISTER_DEMO_OFFSET=36s` starts each of them that far in, where the build
has failed:

```bash
uv run python tests/demo_wsgi.py     # stop it within twenty seconds: pipelines is green
LITTLE_SISTER_DEMO_OFFSET=36s uv run python tests/demo_wsgi.py
```

For three readings — some five seconds, since a failing check is retried early — the
pipelines card on `/status/ci` reads *error · 1 of 3 to escalate*, then *2 of 3*, while
the page's head stays yellow, and afterwards `/events?under=/ci/pipelines` shows that
row with the *damping* chip, which a failure published at once does not carry, and
above it the row of the third reading with the chip *reached*
([ADR-0119](adr/0119-a-wait-that-ends-by-its-count-writes-a-row.md)). Stop the demo
within that wait and start it with `43s`: the wait goes on. The kept file's entry of
`/ci/pipelines` says `"publishes": "OK"`, the card reads *2 of 3* at the node's first
reading, and the *reached* row comes with the next. A node the log holds no row of is
the other half. Start the demo without an offset and leave it for eighty seconds —
`/services/web` fails a few requests 54 seconds in and reads *ok* again a quarter of a
minute later — then stop it, empty the kept log's rows and leave its table of what
every node last showed, and start it:

```bash
python3 -c "import json, pathlib; kept = pathlib.Path('var/demo/var/state/events.json'); \
log = json.loads(kept.read_text()); log['events'] = []; kept.write_text(json.dumps(log))"
uv run python tests/demo_wsgi.py
```

`/events` gains a row only for a node that reads something else than it last showed,
and for the instance's own gap, where every node got one dated the start. And no
**Time** card lost its *since*, which the table keeps for every node (ADR-0110 decision
5): `/status/services/web` says *since* its recovery, to the second, with no row of it
left in the log, and a quiet node's, `/status/security/audit`, says *since before* the
same instant as before the stop — the bound it was given when it was first seen, which
no longer moves with the log. History's row for the period that holds says the same on
each.

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
  reported, ages past the freshness threshold, and shows **stale**, then returns fresh.
  (This is how a live check demonstrates staleness: its result says nothing of whether
  its children are complete, so the tree keeps the child it leaves out and lets it age.
  `runs`, below, is the other half: its node says so, and a child it stops returning is
  removed.)
- **children** — disk / memory / load in a shifting mix, so the card's roll-up
  moves. Its three also carry a **declared rank** (below), which is why they read in
  that order rather than with `load` filed in the middle.
- **audit** — a wiz-style findings leaf that stays **OK** while its reason list
  swells to ~150 long lines, then clears: a skyscraper card growing and
  collapsing under the poll without ever changing color. Its findings are
  **members** (see below).
- **severity** — a cloud-posture scanner reporting into **severity bands**, five
  children each declaring its `order` ([ADR-0055](adr/0055-sibling-order.md)) — so
  the row reads *critical high medium low informational* rather than the
  alphabetical *critical high informational low medium* that files **nothing to do**
  third and puts **low** before **medium**. The counts climb over five phases and
  clear, so the colors travel along a row that **never re-sorts**: that is the
  property a declared rank has and a sort by live grade would not. It is also where
  the title rule is visible, because every band's title is only its own name
  capitalized — the chips must read `critical`, never `critical Critical`, while the
  root's *Cloud posture* survives because it says something the name does not. Drop
  the `order=` arguments in `tests/demo_check.py` and the row falls back to
  alphabetical, which is the demonstration *and* the proof that a check declaring
  nothing is unaffected. One band is not a chip at all: `informational` declares
  `show_when_quiet` ([ADR-0063](adr/0063-declining-the-density-trade.md)), so it
  keeps its box and its four inventory lines beside four siblings that collapse —
  the band whose text is read *because* nothing is wrong, no longer visible only
  when something is. Point `_SHOW_WHEN_QUIET` at another band and the box moves;
  empty it and the whole card chips again.
- **reviews** — a small queue of pull requests waiting for a reviewer, whose reasons
  are a keyed **mapping**. Never empty, never more than six lines, and re-worded on
  every run.
- **pipelines** — the latest run per workflow, as **coded entries**
  ([ADR-0042](adr/0042-entries-carry-their-own-code.md)): each line declares its
  own verdict, the check declares no node code at all, and one build walks the
  whole arc in a cycle — passed, a rerun in italic on a passing job, failed,
  the retry running *while the line stays red*, recovered. That build line carries
  its run's record, so the leaf page shows a line's times in the configured zone —
  the completed run's `completed.at`, and a run in flight's `running.started` beside
  a null `running.ended` — and every demo node's *Measured* card shows its reading's
  own `at`.
- **latency** — a site's answer, recorded as `http` records one: a status and a
  response time, both null where the request failed. `/services/web` keeps it as a
  series and declares its one measure in its YAML (`measures:`), so its page shows the
  **Series** card ([ADR-0092](adr/0092-a-check-declares-its-measures.md),
  [ADR-0097](adr/0097-a-nodes-series-have-a-view-of-their-own.md)): the response-time
  curve, and the way to its Series view, which lists the newest eight readings beneath
  it, and to its History page, which lists every one.
  Each three-minute cycle fails a few requests — marked in the curve's lane, the
  retry making them several — and hangs one run for 45 seconds: nothing is read
  meanwhile, the node goes stale, and the curve breaks there with no mark. Watch a
  cycle go by, then compare the two breaks.
- **workflows** — three repositories' latest CI runs, read in **one run** the way a
  provider type reads its subjects, each graded into the line that carries it. Twice
  in each two-minute cycle a provider's answer breaks the seam — `octo/web`'s time
  comes without its offset, `octo/docs` carries a log past `record_limit` — and each
  costs its own reading and nothing else
  ([ADR-0093](adr/0093-a-record-the-seam-refuses-costs-its-line.md)): `/ci/workflows`
  turns amber with a line naming the repository and why, ahead of the healthy one;
  `/little-sister/runtime` holds a line for each; and `/system` marks the record it
  saw *refused* while the heavy one is in. Where the two stretches overlap, `octo/api`
  is graded alone.
- **runs** — four job names and their runs, the demo's **subject with a history**
  ([ADR-0106](adr/0106-a-subject-with-a-history-has-a-node-of-its-own.md),
  [ADR-0111](adr/0111-a-runs-mark-says-how-the-run-stood.md)). `/ci/jobs` hands back a
  node for each job name its source lists — `import`, `export`, `cleanup` and, two
  minutes of every three, `backfill` — whose line carries the job's newest run, and
  every run is a reading that names the run it is of, so each node draws its runs as
  marks at their own times, on its page and in its Series view. `import` and `export`
  carry a run time, which the check's `measures:` draws as a stem for each run;
  `cleanup` and `backfill` carry none and are drawn as ticks. Every seventh run fails —
  a hollow ring in the failure ink, and under a run time a short stem and a mark in the
  lane — and a run that takes more than a minute warns, under the warning's triangle.
  The source lists a job name's six newest runs, and each poll reads all of them:
  `import`, `export` and `backfill` say how every listed run stood, **for the record
  alone** (`for_record`), so their older runs keep their verdicts; `cleanup` says it of
  its newest run only, so a run of it loses its verdict when the next one takes the
  line, and is a bare, muted tick from then on. The runs are on the wall clock —
  `import` and `backfill` every twenty seconds, `cleanup` every forty, `export` every
  minute — so a restart finds the runs it left. On `/series/ci/jobs` the job names share
  one axis, as long as the slowest job's kept runs reach back, so `import`'s runs crowd
  there: its passing heads give way, its failures and warnings keep theirs, and a strip
  under the pointer names its column's runs.

  `backfill` **comes and goes**
  ([ADR-0109](adr/0109-a-node-says-its-children-are-complete.md)): it runs for two
  minutes and then not for one, and its source does not list a job name that is not
  running. `/ci/jobs` says that its children are complete, so `backfill`'s node leaves
  the wall with the first poll that does not find it, and is back with the first that
  does. While it is gone, `/events?cause=removed` holds its row — *undefined*, the chip
  *removed*, *no longer reported by its check* — `/history/ci/jobs` lists the runs the
  check still keeps of it, the Series index and `/series/ci/jobs` do not name it, and
  its own address — Status, History or Series — is a `404` whose page says *removed*,
  when and why, and names `ci/jobs` as the nearest node that stands
  ([ADR-0116](adr/0116-a-path-with-no-node-says-what-is-known-of-it.md)). When it returns its runs stand
  on its node again, the new ones behind the old, and its History shows the time it was
  away as a period of *undefined* between two of *ok*.

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
audit leaf **members means ~150 stable per-line controls and their closed native
editor disclosures on one page**. None opens on hover; the anchored form appears only
after its control is activated. The review queue is the
pleasant everyday version, and it is deliberately small enough to pin *every* member,
which is the case worth walking: with all of them pinned the card reads
**MAINTENANCE** on the dashboard, the strip pill's popover says *all 5 reasons* — the
row that explains the blue card — and `/maintenance` states each pin as a block that
opens with the line it silences. Follow a block's *this line* and you land on that
line, marked, rather than at the top of the page. Pin a line on `/security/audit`
too, and then wait out a cycle: the audit list clears at the end of it, and the node
page tells you the pin's line is no longer being reported rather than leaving you to
wonder.

`/ci/pipelines` adds the **coded** third
([ADR-0042](adr/0042-entries-carry-their-own-code.md)): its lines disagree — a red
build over a green test suite, a warn gate, a never-concluded nightly wearing the
ring cue — and the node's color is *derived* from them. Two things to walk. Watch
`web-build` fail and then rerun: the line goes italic and **stays red** — the
verdict is not displaced by the retry, which is the whole design in one line. Then
pin that one red line: the node takes the color of the lines that are left — yellow
while the gate waits, **green** once it is approved — while the pinned line sits in
the maintenance tint with its cue still saying *error*: silencing the one failing
workflow no longer silences (or discolors) the rest. The node's **Time** card says
*since* that moment, *when a line was silenced*, and `/events?under=/ci/pipelines`
lists the row with a *line silenced* chip and, for its reason, the line and the pin's
note ([ADR-0107](adr/0107-an-event-is-a-change-of-what-a-node-shows.md)). Leave the
pin through a cycle: what the build does beneath it is on Events as rows marked
*maintenance*, the node's own changes beside them, and the node's History lists only
what the node showed. Clear the pin while the build is red: the card says *error
since* that moment, *when a line's maintenance ended*, and the row carries that chip.
The healthy lines are emitted deliberately, so `hide_ok` is worth toggling here too:
the green lines vanish with their node when it reads OK, exactly as an operator who
asked for problems-only asked.

The same node **waits before it escalates** — `escalate_after: 3` in its YAML, the one
demo node that does ([ADR-0083](adr/0083-a-node-may-wait-before-it-escalates.md)).
Each turn for the worse is on the node at once: its card says *1 of 3 to escalate*,
its page *Showing warn — 1 of 3 consecutive readings before this escalates, so the
level above still counts ok*, and its row on Events is marked *damping*; the level
above counts it two readings later, which the demo's retry makes a few seconds, and a
second row on Events says when: the same status, with the chip *reached* (ADR-0119).
What is counted is what the node shows
([ADR-0108](adr/0108-the-wait-before-an-escalation-counts-what-a-node-shows.md)), so
walk it with the build pinned. Pin the red line: the node takes its new color and
states no wait, a pin's change being published at once. Through the next cycle the
gate's own turn to yellow waits its three readings while the build goes red beneath
its pin, and neither the card nor the page says anything of an error the node does
not show. Clear the pin while the build is red: the node turns red and states no wait
— what a pin's end uncovers is published at once.

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
  *budget* in the name. The same file deliberately sets `card_status_line: below`,
  opting the demo into a standing second line on every dashboard card so that
  non-default shape remains visible somewhere; a deployment omitting the key keeps
  the compact `beside` default and emits no card-state body attribute.
- **`nodes.yaml`** labels the container nodes (`/ci`, `/security`, …), which the tree
  creates from the check paths and no check owns. Without it the dashboard is a wall
  of bare path segments. It also names the engine's heartbeat, which feeds the status
  strip's hover card. And it carries the **deployment** half of
  [ADR-0055](adr/0055-sibling-order.md): an `order:` on each top-level container, so
  the wall reads outside-in (`services`, `ci`, `security`, `hosts`, `storage`,
  `network`) rather than alphabetically. The bands under `/security/wiz` are ranked by
  their *check*; these are ranked by the person reading the wall. Delete **every**
  `order:` key and it goes back to alphabetical on the next restart — deleting one is
  not the same thing, because a node left at the default rank sorts ahead of its
  positively-ranked siblings rather than at its alphabetical place. The **third**
  source is in `checks/security_wiz.yaml`: an inline `order: -1` beside that check's
  own `title:`, which is what puts the posture card ahead of `audit`.
- **`actions.yaml`** puts a deployment's own links on the pages — see below.
- **`csp.yaml`** adds one source to the assembled Content-Security-Policy, so the
  `/system/installed` readout has a line whose contributor is *this deployment* rather than the
  library or a package — see below.
- **`links/links.yaml`**, so `/links` has a page worth judging: many groups, a title
  long enough to wrap, notes, and every rung of the icon search path — a built-in
  pair, a deployment's own single file (on the chip), a deployment-supplied pair
  (rendered bare), a built-in switched off with `none`, and a name nothing defines.
  It takes the **directory** form (`links/links.yaml` with `links/icons/` beside it),
  which is the shape an aspect that ships files grows into: an `icons/` directory
  sitting next to a `config/links.yaml` is a directory in a configuration root that
  nobody has claimed, and the startup report would rightly name it as not a known
  aspect.

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

### The Content-Security-Policy, and how to make it complain

The policy is the one feature with **nothing to look at on a page** — it is a response
header, it ships as `Content-Security-Policy-Report-Only`, and it blocks nothing
([ADR-0048](adr/0048-an-assembled-content-security-policy.md),
`architecture.md` §5.4). Two places show it anyway.

**`/system/installed`, as an admin.** The policy table prints every directive with the
contributor of each source, and the demo is rigged so all three kinds appear at once:
`'self'`, `data:` and the CDN from the library, `https://tracker.example.org` in
`connect-src` from **`tests.demo_extension`** (a `csp.allow` in `demo_wsgi.py` — the
origin its `demo.js` would call, which `'self'` cannot cover), and
`https://assets.example.org` in `img-src` from **`demo_config/csp.yaml`** (a source no
package knew about, which only the deployment can add). That the package's line is
there at all is the decision demonstrating itself: it was registered before the app
import, and the policy was assembled after it. The table's last row is what `/links`
adds to its own `img-src`: the hosts of the two favicons the demo's links fall back
to — CyberChef's, a name no rung defines, and PagerDuty's, a mark the demo turns off
— answerable to `demo_config/links/links.yaml`.

**The log, by causing a violation.** This one is a recipe rather than a state, because
a demo that permanently violated its own policy would just look broken:

1. Put an external image in something the page renders as Markdown — the simplest is
   `about:` on a node in `demo_config/nodes.yaml`, e.g.
   `![x](https://upload.wikimedia.org/x.png)`. Restart the demo.
2. Load `/status`. The image fails to load (it does not exist), and the browser posts
   a report to `/csp-report`.
3. The demo's log gets one `WARNING` naming `img-src`, the document, and the blocked
   URI. Nothing was blocked — Report-Only — so the only change on the page is the
   broken image you asked for.
4. Add `https://upload.wikimedia.org` under `img-src` in `demo_config/csp.yaml`,
   restart, reload: the report is gone. That is the whole operator loop the header
   exists for.

Take the change back out afterwards; the demo tree is committed.

One more free check: `curl -sI` any page and the header is there; ask for JSON
(`Accept: application/json` with the demo's token) and it is not — the policy governs
documents, and on a JSON body it would be a header no browser consults.

### Copy

Open `/copy` at different points in the demo cycle. The document opens with a head —
*little-sister status*, the wall's address as *Dashboard*, the instant it was made as
*As of* — and a count, *Needs attention — 3 of 14 nodes: …*; with nothing wrong it
says *Nothing needs attention* and is a document still. Beneath the count the outline
keeps only non-OK leaves and their ancestor chains, so a healthy scenario disappears
and a recovering one leaves no empty heading behind, and each node it lists says since
when: compare one against the *since* on that node's own Time card. The review queue
proves authored links survive; the maintenance recipe below proves both a whole-node
pin and an individually pinned reason are named and attributed, and a pin set on a
**branch** from its head has to stand on the branch's own line, above what it
silences. **Copy Markdown** should put the visible source on the clipboard as plain
text; **Copy Rich HTML** should paste as a nested list in a rich editor and still
carry the Markdown as its plain-text fallback — also where the page has no clipboard
interface, which is any instance opened by a host's name over plain `http`: the
button copies through the browser's copy event there. Mode 5 holds both in Chromium.

A **node's** document is behind its **Copy** tab, which stands on every view of every
node — the overview's leads to the tree's document — and the Copy page keeps the
node's trail and tabs. No Status page offers the buttons, a leaf's no more than a
container's. Open the tab on a leaf, `/status/services/api`: the same two buttons
hand over that one node instead of the tree. Four things to check there, because
they are what the tree document cannot say. The pasted document names the node's
path and states the frequency the way the node's page does (`15m`, not `15m 0s`).
Every instant carries an offset: compare one against the node's Time card, which
shows the same moment without one. Pin the node on its Status tab and open Copy
again — the document must still report what the check **measured** and say a pin is
in force, never present `maintenance` as the reading. And on a **container**
(`/status/ci`) the tab leads to `/copy/ci`, which says what the branch shows and
where that comes from, and lists what needs attention beneath it.

`/ci/pipelines` is the one to copy for coded lines: each line that declared a code
carries its own cue, the uncoded advisory beside them carries none, and a running
line says `(running)` in the text rather than leaning on the italic the page uses.
The same lines, cues and all, must appear on `/copy`.

Then the **Copy chip** on a single line. Hover a reason on `/ci/reviews` — on the
card *and* on the detail page — and the chip appears in the same rail a
deployment's own chips use; it leads to that line's own page, which carries the
line and the node's identity and nothing else. Three things to confirm there,
because each is a rule rather than a detail. `/ci/nightly` during its eruption —
twelve linked failures as **prose** — offers no chip on any of them, which is the
members/prose split doing its job on two nodes that look alike. Editing the URL's
`reason=` to a slug the check
is not reporting answers `404` saying the line is no longer reported, rather than
rebuilding it from the pin. And the URL itself is the hand-off's other half: paste
it into the ticket beside the document.

### Maintenance

Maintenance is not a scenario — a check cannot set a real pin (that is the tree's
concern). Set one from the admin **Set maintenance** button on a node's status line
(`pan` is an admin), or from the pause mark at the end of a line on `/ci/reviews` and
`/security/audit`.

The read/edit interaction has one concrete walk:

1. Open `/status/security/audit` while its findings are present. Every line ends in a
   pause mark. Move the pointer down them without clicking: no reason or control
   should move, and no form should appear. Tab through the same controls; each has a
   visible focus ring, and its name is *Set maintenance for this line*.
2. Click one mark. Its editor opens beneath the line and moves the lines below it
   down, its first sentence says it is for this line only and how many keep alarming,
   and the cursor is in the note. The **Duration or expiry** field names the
   configured timezone; open *Which formats can I use?* by click and keyboard and
   confirm the full table fits the editor. Enter
   `**owned** — [ticket](https://example.com/ticket)` plus `Friday` and save. The
   line stays in place, takes the maintenance tint and carries its block: who silenced
   it, the resolved expiry with what is left of it, and the bold word and link as
   rendered HTML. The page comes back **at that line**, ringed — pin one far down the
   list, where the top of the page would be out of sight of it. Repeat once with
   `07-10` or a day such as `17` and confirm the displayed boundary is the next future
   midnight described by the help.
3. Click *Edit* in the block. The textarea contains the exact Markdown source, not text
   recovered from the rendered DOM, with the cursor at its end, and the expiry field
   holds the stored expiry; click into it and all of it is selected. Change the note
   and cancel once — the block returns with the stored note unchanged — then change
   the note alone and save: the expiry in the block has not moved. Edit again, empty
   the expiry field and save: the pin runs for the configured default from now. The
   line never alarms between the writes, and each save comes back at the line. Then
   open *Edit* once more and save with **nothing changed**: who pinned it gains no
   *Last changed* beside it, and the same pin's editor left open in a second tab
   still saves. *Clear* remains a separate action, and comes back at the line too.
4. Repeat at node depth: *Set maintenance* on the status line opens the node's editor
   beneath it, saying how many lines it silences. Pinned, the node's block heads a
   frame round every line, the line pinned before says *also silenced on its own*,
   and raw `<script>` entered as a note stays visible as escaped text rather than
   becoming an element. With scripts disabled, each *Edit* and each mark still opens
   its editor. A branch's page states its node's pin in its head, above the children,
   and an admin's *Set maintenance* stands there: open `/status/ci`, set a pin from the
   head and read it back in the block, whose *Edit* fills the expiry field the same
   way. Open `/status/ci/reviews`: its frame is headed by `/ci`'s block too, without
   buttons — *This node is silenced from /ci* — whose link leads back to the pin. Back
   on `/status/ci`, edit the node's note once more and read
   its **Time** card and its History: the card still says *maintenance since* the
   moment the pin was set, and History has one maintenance row, *current*, with the
   note as it reads now
   ([ADR-0099](adr/0099-a-status-that-still-holds-says-since-when.md) decisions 6 to
   8). *Clear* the pin: the card says *since* that moment, *when its maintenance
   ended*, and History's maintenance row has its end and keeps the note.
5. On the dashboard, move the pointer over a card that is not pinned: a pause mark
   shows at the end of its head, and Tab reaches it without the pointer. Click it. The
   editor opens **in the card**, which grows to hold it, and its first sentence names
   what the pin covers — *services and everything beneath it*. The line above the grid
   reads *updated … — paused while editing* at once. Type half a sentence and leave it
   for half a minute: the grid does not refresh and what was typed stays. Press
   Escape: the editor closes, the mark has the focus again, the line drops the words,
   and the next refresh, at most ten seconds on, brings the grid up to date. Open the
   editor again and leave it for more than a minute: everything but that card dims, as
   the page does when it loses its server
   ([ADR-0104](adr/0104-a-pin-is-one-block-on-what-it-silences.md) decision 7);
   *Cancel*, and the page refreshes at once. Then set the pin, with *hide idle* on and
   a depth of your own in the address. The wall comes back as it was asked for, and
   the card states its pin as the block: who, until when and what is left, and the
   note in full. *Edit* and *Clear* show while the pointer is over the card or the
   keyboard is on them, *Edit* holds the stored expiry, and the card has no pause mark
   while it is pinned. With scripts disabled the mark still opens the editor and
   closes it again. The kiosk layout and a viewer's wall show the block without
   buttons, and no mark.
6. Pin a second node, so that two are, and open **Maintenance**. The pins stand under
   their node's path: *The whole node* first, then its lines in the order the node's
   own page lists them, each opening with its line and, under the node's pin, saying
   it is *also silenced on its own*; a node with only lines pinned has no first block.
   Beneath each note stands who pinned it, and who last changed it where somebody has.
   Click *Edit* in a line's block: the editor opens in the block, in place of that
   record, with the note's source and the expiry filled as in step 3. Save. The page
   comes back with that node's section ringed and in view, and no other marked.
   *Clear* one the same way, and follow *this line* in another: it lands on the line
   on its node's page. Narrow the window to a phone's width with an editor open;
   nothing on the page scrolls sideways.

**A pin whose node is not reported**
([ADR-0109](adr/0109-a-node-says-its-children-are-complete.md) decision 4) needs the job
name that comes and goes. Pin `/ci/jobs/backfill` for `10m` while it is on the wall, and
open the Maintenance page once it has left, within two minutes at the latest. Its
section stands under its path, which is no link there, says that the node is not
reported at present and that its pin silences nothing, and its block opens *The whole
node, when it is reported,*. The wall's pill does not count it. *Edit* the note in the
block and save: the page comes back with the section marked, and no node appears on the
wall. When `backfill` returns it is in maintenance from its first reading —
`/events?under=/ci/jobs/backfill` shows its return as *maintenance*, and beside it the
reading its pin holds back — its section reads as any other, and the pill counts it
again. Pin a line of `/ci/jobs/backfill` instead, with the pause mark at its end, and
the section says *One of its lines, when it is reported,* and names no line while the
node is away.

The **conflict page** needs no code either, only a recipe, because it is about two
people and one node. Every maintenance form carries the pin's `set_at` as a
compare-and-set token, and an *empty* token says "I believe nothing is pinned" — so
the shortest way in is two tabs on an **unpinned** node:

1. Open the same node's page in **two tabs** and open *Set maintenance* in both.
   Neither form has a token yet.
2. Submit one of them.
3. Submit the other. The table now says something is pinned, its empty token no
   longer matches, and instead of silently overwriting the first pin you land on the
   conflict page — both reasons side by side, your own words intact.

Editing works the same way with a real token: open an existing pin's edit form in two
tabs, submit the newer, then the older. An **entry** pin conflicts identically and
the page carries its slug, so the two tabs can be two per-line pins on the same
reason of `/ci/reviews`.

Do it once from the **Maintenance** page as well: open it in two tabs, open the same
block's *Edit* in both, save one and then the other. The conflict page is answered at
the Maintenance page's own address, so check each way off it — *Change nothing*
above all, which is a plain link — loads the Maintenance page again with that node's
section marked, rather than staying where it is.

### History

`/history/services/web` lists every reading the latency scenario keeps
([ADR-0102](adr/0102-a-readings-table-keeps-time-and-names-in-view.md)). Scroll the
readings box both ways: its heading row and its Time column hold still, and its
scrollbars stay at its edges; tab into it and scroll with the arrow keys and Page Down.
*Response time · ms* heads the declared column over `response_ms`, before the fields
nothing declares. `/history/services` declares nothing of its own and says so in its
periods table; a node the log holds no change of shows the period that holds, since
*before* the log's oldest event — after a long run, or with a seeded log (below) whose
events name other nodes.

`/history/ci/jobs/import` lists every kept run of a job name with its code's cue and its
sentence, the older runs' from the lines its grading wrote for the record;
`/history/ci/jobs/cleanup` lists its older runs without either, which is what their bare
ticks say. `/history/ci/jobs` lists `backfill`'s kept runs while that job name is gone —
*All 6 readings kept of* `jobs/backfill` — and no such table while its node stands,
where they are the node's own (ADR-0109 decision 6).

### Events

`/events` shows what its URL names
([ADR-0101](adr/0101-the-events-page-is-filtered-by-its-url.md)), and the demo's own
log grows too slowly to judge that by. Give it a busy one: stop the demo, write a log
into `var/demo/var/state/events.json` — `{"events": [...]}`, oldest first, each event
as `Event.to_dict()` writes it, its time without an offset on this machine's clock —
and start the demo again, which restores it. Seed an outage that takes five aspects of
one host down at one moment, among a few hundred unrelated transitions and a pin over a
flapping check. Then find the outage's first failure with `under` and *error* alone,
its recovery by turning *ok* back on, and what the pin held back with *reached* off;
type into a field and press Enter, and toggle a switch from the keyboard. Move the
window with the bar and confirm every link keeps the filters; open a window reaching
back past the log, which must say where the log begins, and filters that match
nothing, which must say how many they were over; *reset* returns the whole log. Scroll
the table: the filters, the bar and the count stay above it from the md breakpoint up.
The third switch group is what wrote a row (ADR-0109 decision 5): after the demo has
run some minutes, *removals* off hides `backfill`'s goings, *removals* alone lists
them, each a row whose path is no link while the node is away, and *pins* alone lists
what an admin set, edited and cleared. A wait that ended by its count is two rows of
its node (ADR-0119): the change the wait held back, with the chip *damping*, and at the
reading that completed the count the same status with the chip *reached*. With *held
back* off the page lists the second and not the first; `/ci/pipelines` writes such a
pair in every cycle of the demo.

### A phone

Look at the demo as a phone lays it out
([ADR-0105](adr/0105-a-page-is-laid-out-at-its-screens-width.md)): with a browser's
device emulation — a touch device with a phone's user agent, 390 pixels wide or 360 —
and not with a narrow window alone, which shows the same layout now and would have
shown it before any document declared its viewport. No page scrolls sideways. On the
wall the filters stand on two lines beneath the stamp, and with a node pinned the
strip takes the line beneath the count of pins. On `/status/security/wiz/informational`
the trail takes two lines, the first ending in its slash; on `/status/services/web`
it keeps one, and the node's title stands on the line beneath, where the trail left
it less room than a word needs. On Events, History and both System views a table
scrolls inside its box while the bar and the rail stay put, and System's schedule,
scrolled to *Seen*, is still there after the next poll. Open an editor on a node's
page and on the Maintenance page: it fits. Two things do not, and are known: the
rail's labels, opened, stand beside the page and take half a phone's width, and at
320 pixels the wall under the rail is a few pixels wider than the screen.

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
settings menu opened on `/status`, the rows on `/links` that are not plain body
text and the folds of its setup guide, closed and opened, the coded reason lines of a
seeded tree, on its leaf page a pin's block
with its buttons and its opened editor, the Maintenance page's count, headings
and records, the same block on the wall — in a box inside a card, in the editor a
card's pause mark opens, and in a branch's head — and the chips in the rows of the
Events page, and measures each as the eye actually gets it: the *computed* ink,
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
Bootstrap component's own color has to hold the bar on six canvases.

A pin's block is walked for the same reason. Its statement and its note sit on the
block's own tint, a pair the tokens can measure; but *Set maintenance* stands on the
page's alert, which Bootstrap paints, and the editor's labels, muted help and
*Cancel* are Bootstrap's inks on our panel. So the block's buttons draw from the ink
they stand in rather than wearing an outline variant, and the sweep opens the editor
and reads each of those rows where it lands. On the Maintenance page the same blocks
stand on the page's own canvas, with rows a node's page does not have: the count
above them, which is Bootstrap's muted ink, a node's path, which is a link on the
canvas, the link to its line inside a block's sentence, and the record beneath a
note. The sweep reads those there.

The Links page's setup guide is walked for it too. Its folds are cards, which
Bootstrap paints, so what a fold's summary says beside its name takes our muted ink
rather than Bootstrap's; and opened, the roster is Bootstrap's inks on Bootstrap's
surfaces throughout — its `code` ink stands at 4.50:1 on a light card, which is the
bar itself. The sample file, which only a page with no links has, is the card's ink
on the sheet's own code fill; the sweep empties the links for that one row.

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

**The coded lines are the third thing it walks**, and the one row that paints its
own surface: `.is-coded` resets the reason wash to full opacity so the declared tint
pair is the rendered one ([ADR-0042](adr/0042-entries-carry-their-own-code.md)). The
gate measures those four pairs from the sheet's own inks; only a browser can say
that the vivid card fill underneath — or the leaf page's alert — has not
re-composited them on the way to the eye. The sweep serves Mode 1's coded-entry
fixture (`ui_fixtures.coded_workflow_tree`, seeded straight into the tree because
the engine is off), so the sheet you look at and the ratios measured here are the
same roster: every tint, the running variant, the pinned line's maintenance tint
over the code it covers, and the uncoded advisory beside them, on the overview card
and again on the member leaf page.

---

## Mode 5 — the browser boundary checks (layout and chrome, against paint)

Modes 1 to 4 are for *looking*; some layout claims need measurements.
The stable-flow model
([ADR-0056](adr/0056-stable-useful-dashboard-flow.md)) needs one thing looking
cannot give: proof that the widths it publishes are the widths Chromium acts on.
`tests/test_dashboard_browser.py` renders four fixture pages through the real
templates and drives headless Chromium across a boundary one pixel at a time —
the outer-track snap must paint flat, and the model's nested column flip must
land within a pixel of the painted one. It also renders a genuinely tall wall in
a short viewport: both interactive layouts keep their bar at the top while the
window scrolls; the rail occupies and scrolls within the exact space below it;
the settings menu's last layout choice remains reachable; and a border-box height
change proves the measured rail offset follows the rendered bar rather than a
constant. The CSS-only path proves the seeded offset plus the rail's inset still
clears the rendered bar, then checks the control and anchor positions. A narrow case
enlarges the first row, proves its measured viewport budget, opens the collapsed
sections, scrolls to their last entry, then opens the settings menu and reaches its
last layout choice. A reason editor scrolled into the bar proves content panels paint
beneath the chrome. And without Bootstrap's stylesheet, on a phone's window and on a
short desk's, the bar keeps its height: the settings panel then stands in the bar's
own flow, and a cap on it read from the bar's measured height made the bar grow and
shrink twice a second. These claims have all been wrong before, and none is visible in
one screenshot.

The same module carries one claim that is about **paint alone**: an action chip laid
over a node's title must not read through to it
([ADR-0034](adr/0034-template-slots-for-dependent-packages.md)). It is measured by
comparing the pixels inside a chip with the title in place and with it hidden — the
same image while the chip is showing, but for the level the rasterizer moves a pixel
by on its own, and a *different* one on a card at rest, which is what keeps the first
comparison from passing on a blind measurement or on a veil that never lifts. That
page is not on the fixture sheet: the sheet registers no filler, so it has no chip to
collide with anything, which is how the collision shipped. The check builds its own
page through the same `render_page` pipeline, with the demo package filling the real
slot.

This module, like every browser file below, is one the ordinary gate does **not** run:
it needs a browser download. Without Playwright or Chromium the whole module skips.
Its two stable-flow boundary checks abort every jsDelivr request before their first
navigation, assert that Bootstrap CSS was among the intercepted requests, and compare
a consistently unstyled render. Each chrome test declares whether it needs Bootstrap
CSS or its behavior bundle; the harness probes those exact URLs in a blank page and
skips only the affected test when that asset is directly unavailable. Fixture
navigation waits for the DOM and the specific Bootstrap condition, not for unrelated
tail scripts such as Floating UI. Run it explicitly when the layout model,
`dashboard-layout.js`, `rail.js`, the shell or card templates, or the grid/chrome
stylesheet rules change:

```
uv sync --group browser
uv run playwright install chromium
uv run pytest tests/test_dashboard_browser.py
```

It takes a minute or two — most of it is Chromium re-laying out the page at each
probe width. Each run renders into its own temporary directory, so concurrent
runs cannot delete each other's artifacts.

`tests/test_series_browser.py` holds a Series view's script against a real pointer
([ADR-0098](adr/0098-a-series-view-is-drawn-over-a-window.md) decision 6): a real
server over the estate `tests/test_series_window.py` reads, logged into by the
form, and Chromium dragging, pointing and pressing Escape at positions worked out
from the drawing's geometry rather than from what the script reads. It takes
Bootstrap from the copy Mode 4 vendors, where there is one, since the page bar's
menu unfolded would cover the view the pointer is sent to. Run it the same way
when `series.js`, the Series templates or the curves' stylesheet rules change:

```
uv run pytest tests/test_series_browser.py
```

`tests/test_pin_browser.py` holds a pin's write and its editor the same way
([ADR-0104](adr/0104-a-pin-is-one-block-on-what-it-silences.md)): a real server over
a node of 80 lines that can each be pinned, and Chromium scrolling to the 60th,
pinning, editing and clearing it — the page has to come back with that line in the
window, clear of the bar, each time — and opening an editor on a note, where the
cursor has to stand at the note's end. And over a wall of three cards, with the
page's clock in the test's hand: a card's pause mark opening its editor in the card,
the refresh holding off while it is open and dropping an answer that was on its way,
the line saying *paused while editing* at once, the page dimming a minute later but
for the card being edited, and the mark keeping its seat at the end of the state
however the head wraps — with a pointer, with the keyboard, by touch and without
script. A node's inspection card stays away while its editor is open, and a pinned
card is drawn at every width a card comes in, its sentence ending no line inside the
date of its expiry. Run it when `maintenance-edit.js`, `poll.js`, `inspect.js`, the
block's templates or styles, or what `POST /maintenance` returns to change:

```
uv run pytest tests/test_pin_browser.py
```

`tests/test_phone_browser.py` holds every page to a phone
([ADR-0105](adr/0105-a-page-is-laid-out-at-its-screens-width.md)): a real server over
an estate with a deep path, a name and a word with nowhere to break, long reasons and
a pin on each, and Chromium **emulating a phone** — a touch device with a phone's user
agent, at 390 pixels and at 360 — in the three layouts. Each page has to be laid out
at the screen's width, at its own scale, with nothing reaching past the screen outside
a box of its own. The band's filters, its trail at every width a line can end at, a
title beside its trail, the wall's strip, a table in its box, a reason's width there,
the Links page's guide with its folds opened and the schedule's place over a poll are
each held, and a desk's window confirms that
the band reads there as it did. A narrow window is not a phone: a desktop browser lays
a page out at its window's width whatever the document declares, which is how pages
drawn 980 pixels wide on every phone passed the checks that set one. It takes
Bootstrap from the copy Mode 4 vendors where there is one and from the CDN otherwise;
with neither it measures an unstyled page, and fails. Run it when a template gains a
table, when the shared head, the band, the wall's cards or `poll.js` change:

```
uv run pytest tests/test_phone_browser.py
```

---

`tests/test_strip_browser.py` holds the instance's own pill above the wall: a real
server over a tree whose instance node has a title, and Chromium at a desk's width, on
an emulated phone and at five widths between. The pill has to be one line high with its
name and its state unbroken, and its title has to be as wide as on the desk or out of
sight — never squeezed, and never painted beneath the pill. Run it when the strip's
markup in `_status_grid.html` or its stylesheet rules change:

```
uv run pytest tests/test_strip_browser.py
```

`tests/test_rail_browser.py` holds where the rail gives way
([ADR-0105](adr/0105-a-page-is-laid-out-at-its-screens-width.md) decision 8): a real
server and Chromium with the rail chosen, at widths from 320 pixels to 1400. Below 576
there has to be no rail, the bar's toggler has to stand with the sections folded
behind it, opening them and leading, and the page has to start at the screen's edge
with the bar's parts where a viewer who chose the top bar has them; from 576 the rail
stands and the page starts beside it; a window made wider gets its rail back with the
preference untouched; and the top-bar layout is as it was. Run it when the bar's or
the rail's markup in `_header.html` or their stylesheet rules change:

```
uv run pytest tests/test_rail_browser.py
```

`tests/test_about_browser.py` holds About to its screen: a real server and Chromium at
six widths from 1440 pixels down to a phone's. The page has to be no wider than the
screen, and a ring's width with the width of its widest word has to fit the page —
the geometry, since a word travels along its ring and where it stands when a test
looks proves little; a wide screen keeps both rings at their full widths, and a phone
keeps the one the story names, passing outside the eyes. Run it when `about.html` or
the hero's stylesheet rules change:

```
uv run pytest tests/test_about_browser.py
```

`tests/test_curve_frame_browser.py` holds where a curve's frame opens on a phone: a real
server over the estate `tests/test_series_window.py` reads, and Chromium emulating one.
A drawing wider than its frame has to stand with its right end at the frame's — in a
Series view, on a node's own page, and over a window chosen by its URL — while its words
still read from the left; on a desk nothing scrolls; and, with the page's clock in the
test's hand, a frame scrolled back has to be where it was after a refresh. Run it when
the curves' stylesheet rules, `_series.html` or `poll.js` change:

```
uv run pytest tests/test_curve_frame_browser.py
```

`tests/test_index_folds_browser.py` holds the Series index to a narrow screen
([ADR-0114](adr/0114-a-curve-seen-small-and-the-series-tabs-count.md) decision 3): a
real server over an estate shaped like a deployment's — eight hosts of five curves each,
two checks on one node, checks that draw nothing — and Chromium at desk widths from
946 pixels to 1600 and emulating a phone. With every fold open the table has to be no
wider than its box, a curve's three numbers have to keep one line from 1400, a fold's
strips have to stand in a column, and a closed fold has to be one line; on the phone
every fold's control and every open fold's label, strip and values have to be inside
the screen, and a row has to say everything its columns said. Run it when
`series_index.html` or the index's and the sparklines' stylesheet rules change:

```
uv run pytest tests/test_index_folds_browser.py
```

`tests/test_assets_browser.py` holds what an open page does when the server links other
files than the page was loaded with
([ADR-0112](adr/0112-our-own-assets-carry-their-content-hash.md)): a real server over a
wall of three cards, the page's clock in the test's hand, and the server's digest of its
files changed under a page that is open. The page has to load itself afresh at the next
refresh and not swap that answer in; to wait while an editor is open, keeping what was
typed; and, over a server that draws the page with one digest and answers the refresh
with another, to reload once and then go on showing what it is sent. Run it when
`poll.js` or `little_sister.assets` change:

```
uv run pytest tests/test_assets_browser.py
```

`tests/test_csp_browser.py` holds our own pages to sending no Content-Security-Policy
report ([ADR-0048](adr/0048-an-assembled-content-security-policy.md),
[ADR-0030](adr/0030-curated-links.md)): every `securitypolicyviolation` a page raises is
counted, on the wall and a node's page — whose switches Bootstrap draws as `data:`
images, which the check first makes sure of, since a page its stylesheet never reached
would report nothing and prove nothing — and on `/links`, whose icon from a remote mark
and whose favicon sit on names reserved never to resolve, so each is asked for, fails
and becomes the neutral glyph, which is how the check knows it was asked for; at a
desk's width and a phone's, where the bar shows its burger. Its conditions are asked
from the test rather than through `wait_for_function`, which evaluates in the page and
would raise a `script-src` report of the test's own. Run it when the policy, the
templates' images or `links.py`'s marks change:

```
uv run pytest tests/test_csp_browser.py
```

`tests/test_copy_browser.py` holds the two Copy buttons to what a paste receives
([ADR-0115](adr/0115-a-copy-document-says-where-it-is-from-and-since-when.md) decision
8): one real server reached twice — on `127.0.0.1`, where a page has a clipboard
interface, and by a name the browser is told to resolve to the same server, where over
plain `http` it has none — and Chromium pressing a button on every page that offers
the pair, then pasting into a field that keeps the members it was handed. *Copy Rich
HTML* has to hand over the rendered document beside its Markdown on both, and *Copy
Markdown* the Markdown alone; a sentence copied by hand stands on the clipboard before
each press, so a button that says it copied and did not is seen. An interface that
refuses, a copy event that never arrives and a browser that copies nothing are each
played, and where the interface is missing the copy has to be made while the click is
still being answered. Run it when `copy.js` or `_copy_controls.html` change:

```
uv run pytest tests/test_copy_browser.py
```

**A width is measured in the face the machine has.** A browser draws `system-ui` in
its machine's typeface: San Francisco on a Mac, and in the cloud container it has been
Inter and it has been DejaVu Sans. The faces differ by more than a layout's margins —
one breadcrumb trail of the phone checks is 595 pixels on a Mac, 624 in Liberation
Sans, 640 in Inter and 742 in DejaVu Sans — so a check whose premise is a width, a
name wider than its column or a line that fits its box, makes the premise hold in every
face and asserts it before it relies on it, or reads which way the page has to go off
the widths it measures. One written to hold in the face it was written in is red in
another. On Linux, Chromium draws `system-ui` in the face fontconfig puts first for
`sans-serif`, so a file that puts another face there, named in `FONTCONFIG_FILE`, runs
a check in that face:

```
cat > var/scratch/dejavu.conf <<'EOF'
<?xml version="1.0"?>
<!DOCTYPE fontconfig SYSTEM "fonts.dtd">
<fontconfig>
  <include ignore_missing="yes">/etc/fonts/fonts.conf</include>
  <match target="pattern">
    <test name="family"><string>sans-serif</string></test>
    <edit name="family" mode="prepend" binding="strong"><string>DejaVu Sans</string></edit>
  </match>
</fontconfig>
EOF
FONTCONFIG_FILE=var/scratch/dejavu.conf uv run pytest tests/test_phone_browser.py
```

## Mode 6 — the walk (a review, repeated)

The other modes each hold one claim. `tests/walk_gui.py` goes looking: it starts the
live demo on a port of its own, 36 seconds into its scenarios so the wall it meets is
not all green, renders the fixture sheet beside it, and drives headless Chromium over
both at three widths of a desk — 1440, 1000 and 700 pixels — and on an emulated phone.

```
npm i --prefix var/bootstrap bootstrap@5.3.2 \
    @floating-ui/core@1.6.8 @floating-ui/dom@1.6.12     # once; var/ is gitignored
uv sync --group browser
uv run python tests/walk_gui.py                          # → var/gui-walk/index.html
```

On every screen it opens the wall and a branch's wall and points at each card head — a
tap on the phone — which raises the inspection card where a node has one; a branch's
page, a leaf's and its History; a subject's branch and node; Events, Maintenance, both
System views, Links, Copy and About; the Series index with every fold open; and two
Series views, with a pointer at rest on a curve and, with a mouse, a stretch dragged
across it. Once, on the widest screen, it pins the demo's job name that comes and goes
through the wall's own editor, waits until its node has left the tree, and then visits
what a removed node leaves on every screen: its row on Events, its suspended pin on
Maintenance, the branch it left, its own address, and its check's History and Series.
Last it opens every page of the fixture sheet on the widest screen and on the phone.
A walk takes about eight minutes, most of it the demo's own clock.

**Every step leaves a screenshot and what the browser said** while it was taken: the
console's errors, the Content-Security-Policy reports the page sent, and how far the
layout shifted with no input. **And every step is measured** against a short list of
facts (`FACTS` in the script): a page no wider than its screen, a raised card inside
the screen, the name, the title and the state of a card's head not lying over one
another, and everything a curve or a sparkline draws inside its plot. A fact that does
not hold **marks** the step.

**Nothing fails.** A review collects, so the walk always ends with its gallery,
`var/gui-walk/index.html`: each fact with how many steps it marked, the marked steps
first, then every step in the order it was taken; `walk.json` beside it is the same as
data. One thing to know when reading it: a layout shift is counted whatever caused it
— but for a raised card's own move from one node to the next, which a browser counts
and nothing in the layout makes — and the demo's readings change under the walk, so a refresh that swapped in a longer
list marks a step as a real shift does — a mark that comes back at the same step on a
second walk is the one to believe.

**A fact that is fixed moves into a test of Mode 5**, which is where a claim is held;
the walk finds, Mode 5 keeps. `tests/test_walk_gui.py` holds the facts themselves, each
against a page of the test's own that is broken in its way, which it has to mark, and
the same page sound, which it has to pass — a walk that never fails would otherwise
look the same with a fact that measures nothing. Its half that needs no browser runs in
the ordinary gate. Run it when a fact is added or changed:

```
uv run pytest tests/test_walk_gui.py
```

It walks synthetic shapes. A real estate's are looked at on a deployment, by hand,
beside it.

## Not part of a deployment

All six harnesses are **dev-only**: they live under `tests/`, carry no real
checks, and start no engine except when you run the demo wrapper. Keep them green
with the rest of the gate (`hooks/pre-commit`) and run Mode 5 by hand
when the dashboard layout changes.
