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
overview with two tall roots, dozens of descendants, every node open and spare grid columns
(subtree balance), an
**OK** severity leaf flooding 150 long audit findings (the real-deployment case
that once made a skyscraper column — since the ADR-0056 chips it collapses to one
quiet pill, the flood in its box beside the chip, hidden until found, and on its leaf
page), single-token reasons — a
~300-char URL, an image digest, a 500-char `code()` line — that stress *width*
rather than length, and a **deployment's own tree**, its names replaced
(`tests/anonymized_tree.py`, from `tests/fixtures/anonymized_tree.json`): 265 nodes
under two teams, six levels deep, a level of 20 repositories with 63 workflows and a
security band of findings over 1,000 characters, every line made-up text of the
recorded length, shown with the deployment's `reason_cap` of 30 — the tree the
interactive wall's design round measured its answers on, whose cost today
`tests/test_wall_cost.py` holds as the baseline the interactive
wall's stages state their growth against: the refresh's fragment in bytes and
elements for a viewer and for an admin, on the tree as recorded, made worse four
ways and mounted as the deployment that runs mounts it — one team's five checks as
the wall's cards, the variant `deployed` — its weight on the wire where the browser
takes gzip, and the render's time and peak memory (what a browser pays for the same
wall is Mode 5's). The file is read by eye and scanned against `release/private_strings.txt`
before it changes. Beside it stands a **second deployment's wall** in the same shape
(`tests/hosts_tree.py`, from `tests/fixtures/hosts_tree.json`): 101 nodes under two
cards, nine hosts the library's own types write — `host-metrics` on each, `macos-memory`
beside it on one, `qnap-metrics` on the NAS — and a card of the family's checks, every
name the deployment's own replaced by a generic one of its length and every line
made-up text of the recorded length, read with that deployment's `reason_cap` of 6 —
the wall the host types are measured on when they say how their levels start, as the
variant `hosts` of the same two files, drawn with what the three types propose as the
deployment mounts them (`hosts_tree.checks()`) and with what they say of their nodes, an
about and a handbook an aspect. It is no fixture of the sheet. Add a case by appending a
`Fixture` there; every fixture is also rendered as a smoke test in
`tests/test_ui_fixtures.py`, so a template that breaks on an extreme is caught by the
gate.

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
ended · at its end* chip, and a second one *held back* beside it where the reading moved meanwhile
— its History closes the maintenance row at that reading, and its **Time** card says
*since* then, *when its maintenance ended*.

A pin that outlives the stop shows what a start does with one its log has lost
([ADR-0110](adr/0110-what-every-node-last-showed-is-kept-beside-the-log.md) decision
6). Pin `/storage/backup` for a day, stop the demo, put an empty log in the kept one's
place, and start it:

```bash
echo '{"events": []}' | gzip > var/demo/var/state/events.json.gz
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
python3 -c "import gzip, json, pathlib; kept = pathlib.Path('var/demo/var/state/events.json.gz'); \
log = json.loads(gzip.decompress(kept.read_bytes())); log['events'] = []; \
kept.write_bytes(gzip.compress(json.dumps(log).encode()))"
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
- **fleet** — twelve hosts of two quiet leaves each under `/hosts/fleet`, a level no
  file speaks for that, opened, would draw thirty-six boxes: past the built-in look's
  thirty, so its hosts start as **chips** with their counts — the net for a level
  nobody expected to be big ([ADR-0128](adr/0128-where-a-nodes-first-look-comes-from.md)).
  Mid-cycle one host's disk fills: the failure budget opens that host with its disk,
  and once it clears it is a chip again, while a host the viewer opened stays open.
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
  starts open with its four inventory lines beside four siblings that start as
  chips — the band whose text is read *because* nothing is wrong, no longer visible
  only when something is; a click opens any of the four, and ▤ on `wiz` folds all
  five. Point `_SHOW_WHEN_QUIET` at another band and the box moves; empty it and the
  whole card chips again.
- **reviews** — a small queue of pull requests waiting for a reviewer, whose reasons
  are a keyed **mapping**. Never empty, never more than six lines, and re-worded on
  every run.
- **pipelines** — the latest run per workflow, as **coded entries**
  ([ADR-0042](adr/0042-entries-carry-their-own-code.md)): each line declares its
  own verdict, the check declares no node code at all, and one build walks the
  whole arc in a cycle — passed, a rerun in italic on a passing job, failed,
  the retry running *while the line stays red*, recovered. Its eight lines come in
  the check's own order, by repository and workflow, the build seventh — past the
  wall's budget of six — so on the wall the box shows its **failing lines first**:
  the failed build and the waiting gate lead while they fail, the healthy ones fill
  the rest of the budget, and *⌄ all 8* beneath them shows the lot; on `/status/ci/pipelines`
  the lines stand as the check wrote them, the build seventh. That build line carries
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

**The demo starts as its files say**
([ADR-0128](adr/0128-where-a-nodes-first-look-comes-from.md)), each layer speaking once.
The `demo` type proposes how each scenario's own node starts (`_FIRST_LOOK` in
`tests/demo_check.py`): the job names, a host's, the backup's and the scanner's
children as chips, and the pipelines' and the workflows' passing lines folded behind
*✓ +N ok*. The demo's own files take two of those back — `ci_jobs.yaml` opens the job
names (`chips: false`) and `ci_workflows.yaml` shows the workflows' lines
(`fold_ok: false`) — and `nodes.yaml` starts `/network`'s tunnel as a chip, a container
no check writes getting its look where it gets its title. Everything else is drawn as
nobody spoke for it, `fleet`'s *+2 more* among it. A failure under a chip opens its way,
three to a card, errors first: when `vpn` flaps red its chip opens, and when `medium`
warns among the bands its box opens beside chips, `high` and `critical` after it as
they fail, while `informational` stands open throughout by its claim. The pipelines'
box shows its failing lines with *✓ +N ok* after them, and its funnel shows the rest.

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
row that explains the blue card — and *Handled* states each pin as a block that
opens with the line it holds. Follow a block's *this line* and you land on that
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
the maintenance tint with its cue still saying *error*: pinning the one failing
workflow no longer holds (or discolors) the rest. The node's **Time** card says
*since* that moment, *when a line's pin was set*, and `/events?under=/ci/pipelines`
lists the row with a *line's pin set* chip and, for its reason, the line and the pin's
note ([ADR-0107](adr/0107-an-event-is-a-change-of-what-a-node-shows.md)). Leave the
pin through a cycle: what the build does beneath it is on Events as rows marked
*maintenance*, the node's own changes beside them, and the node's History lists only
what the node showed. Clear the pin while the build is red: the card says *error
since* that moment, *when a line's maintenance ended*, and the row carries that chip,
with why — *line's maintenance ended · by hand*. Pin a line that builds, edit its note
and clear it: three rows that change nothing the node shows, *line's pin set*, *line's
pin edited* and *line's maintenance ended · by hand*
([ADR-0145](adr/0145-a-nodes-notes-tab-is-the-place-to-act-and-every-pin-leaves-an-entry.md)
decision 9), and a wait under way (below) goes on through them.
The healthy lines are emitted deliberately, so `hide_ok` is worth toggling here too:
the green lines vanish with their node when it reads OK, exactly as an operator who
asked for problems-only asked.

The same node **waits before it escalates** — `escalate_after: 3` in its YAML, the one
demo node that does ([ADR-0083](adr/0083-a-node-may-wait-before-it-escalates.md)).
Each turn for the worse is on the node at once: its card says *1 of 3 to escalate*, a
rail down its right edge in the color the level above still counts
([ADR-0143](adr/0143-a-handled-part-carries-its-jobs-mark-and-a-rail-in-the-color-it-counts-as.md)),
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
- **Handbooks**: `checks/services_api.yaml` gives the API gateway its runbook,
  `handbook/api-gateway.md`, and links it from its about by the short form;
  `nodes.yaml` gives `/services` one as text
  ([ADR-0133](adr/0133-a-node-says-what-it-is-in-a-card-and-at-length-in-a-handbook.md)
  decisions 3 and 4) — see *Handbook* below.
- **Details**: `nodes.yaml` gives `/services` an owner, a link to whom to call and where
  its tickets go, and `/hosts` its site; `checks/services_api.yaml` gives the gateway
  an owner of its own and its documentation, `checks/hosts_fleet.yaml` the fleet's
  rack; and the `demo` type gives `/hosts/nas`, its disk and each of the fleet's hosts
  the details of their objects with every run
  ([ADR-0133](adr/0133-a-node-says-what-it-is-in-a-card-and-at-length-in-a-handbook.md)
  decision 6) — see *Details* below.
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

**Coded, in `demo_wsgi.py`.** Three `slots.register` calls against `tests/demo_extension`
— the third the *Notes* tab's, with its draft function, which *The door, the drawer and
◇ details* below files a ticket with — and one `register_assets`. What only this half can show: a provider that **declines**
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
holds. **Copy Markdown** should put the visible source on the clipboard as plain
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
(`/status/ci`) the tab leads to `/copy/ci`, which says what the branch shows and where
that comes from, since when it has shown it and what began it — *begun by a reading of
… beneath it*, the *From* and *What* of the newest row of its History's first table
([ADR-0132](adr/0132-a-branch-keeps-the-period-of-what-it-shows-beside-the-log.md)
decision 6): compare the two — and lists what needs attention beneath it.

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

### The door, the drawer and ◇ details

One door, ◇, stands where ‖ and ✓ stood
([ADR-0147](adr/0147-one-door-opens-a-nodes-notes-tab-in-a-drawer-over-the-wall.md)):
every kind is set on a node's *Notes* tab, which ◇ opens in a drawer over the page.

1. **The door on a head.** Every open head ends its icons in ◇, for every reader —
   *Handle it* for whoever may set something there, *Notes* for whoever may not. Where
   something is handled at or beneath the node it is lit with the number of parts:
   pin `/ci/reviews` and mark a line of `/ci/pipelines` seen, and `/ci`'s ◇ says *2*,
   its tooltip *Handle it — 2 handled: 1 node in maintenance, 1 line seen*, as the
   chip of a closed `/ci` counts it. Under the library's look, whose buttons show only
   under the pointer, a lit ◇ stands at the start of the card's state instead, in
   sight at rest and staying put under the pointer, and the toolbar carries none; a
   plain one shows with the toolbar. The kiosk draws the lit number as a mark and
   nothing to click.
2. **The door on a line.** On `/status/ci/reviews` every member line ends in ◇ in its
   seat, *Handle this line*, where nothing handles the line, and in the mark of what
   does where something does. ◇ opens the tab with its form on that line; a mark opens
   it at the block it marks, its editor open.
3. **The drawer at a desk.** Click `/ci`'s ◇: the drawer stands over the wall 480
   pixels wide — at the right, at the left where the card would sit under it — with
   the node's *Notes* tab in it whole but for the site's bar, rail and band, its head
   the card's name and state, *Status* and *Notes* leading to the node's page and tab,
   and ✕. The wall behind it is shaded but for the card, which stays lit, and it waits:
   the drawer says *updates paused* under the node's name at once, muted, while the line
   above the grid reads as it did — *updated …*, its width kept, so that nothing on the
   wall moves however narrow the window — nothing is refreshed, and after a minute the
   wall dims. ✕, Escape and a click on the wall each close it, the focus back on ◇; a
   click with Ctrl or ⌘ opens the tab in a new browser tab instead. A leaf's page,
   which nothing refreshes, opens the same drawer with no *updates paused*.
4. **A write and a refusal.** Mark the failures under `/ci` seen in the drawer: it
   closes, and the wall is up to date at once — each part keeps its color under the
   ringed check, and `/ci`'s ◇ counts them. Open it again and silence a line of
   `/ci/pipelines` with `45d`: refused, why above the form, the words, the line and the
   level back in it, and the drawer stays. On a leaf's page, which is not refreshed, a
   write loads the page again.
5. **The question.** Type a few words in the form and press Escape: *Discard what you
   wrote?*, *Keep writing* chosen. Escape again keeps writing, the cursor back in the
   words; *Discard* closes it. Nothing is kept: the next drawer's form is empty. A
   click on the wall, ✕ and *Status* in the drawer's head ask the same; words a refusal
   gave back count as unsent.
6. **On a phone.** With a phone's device emulation, 390 pixels wide, tap ◇ on a card low
   on the wall: a sheet rises from the foot, the card scrolled into the strip above it,
   lit. A tap on the strip closes it.
7. **◇ details, and the block as the button.** The band's third switch, *◇ details* —
   its tooltip *Show who handles a part, until when and why, on the wall* — is off: the
   demo keeps the library's default, `handled_details: false`. A handled part says so by
   its color and its mark, and ◇ by its number. Turn it on: every block of what handles
   a part stands on the wall where it stands — the pin on `/ci/reviews`, the seen in
   `/ci/pipelines`' box, a configured rule's on the nightly while it erupts — each one
   link, its sentence its name and a chevron at its end, washing under the pointer and
   ringed under the keyboard. Click one: the drawer opens at that block under
   *What stands*, its editor open with the note's source and the cursor at its end;
   *Cancel*, and the block stands whole, its note and who set it, with *Edit* and
   *Clear*. A configured rule's opens the drawer at the rule's block: its note and its
   file, and no buttons. Turn the switch off: the blocks go, and nothing that counts
   moves — ◇'s numbers, a closed chip's ◇ and the band's pill say the same. A reload
   keeps the switch, as it keeps *hide ok*, in a cookie named `handled_details`, as its
   query parameter and its key in `settings.yaml` are — `?handled_details=1` turns it on
   for a link; the kiosk follows the key alone, whatever a browser chose.
8. **A ticket from the words** ([ADR-0148](adr/0148-a-ticket-is-drafted-from-a-notes-words-by-the-package-that-fills-its-slot.md)). The demo's coded filler fills the
   *Notes* tab's slot. Open `/ci`'s ◇ and write two lines under *Seen*, the first a
   summary: *Mark seen* is followed by *File in the tracker ↗*, and beneath the row a
   line says what it does. Press it: a new tab opens at
   `https://tracker.example.org/new`, its title `/ci: ` and your first line, its body
   your words, every failure listed and the tab's own address, `/notes/ci` — the
   reserved example domain answers nothing, so read the draft in the tab's address bar.
   Back in the first tab the drawer is still open, *updates paused*, the words still in
   it and nothing marked; Escape still asks before it drops them. Press Enter in *Until,
   if it should end sooner*: it marks seen, as the kind's own button does, and files
   nothing. `/system/installed` lists the filler, *draft* beside its template.

### Maintenance

Maintenance is not a scenario — a check cannot set a real pin (that is the tree's
concern). Set one as an admin (`pan` is one) on a node's *Notes* tab, *Maintenance*
chosen in its form
([ADR-0147](adr/0147-one-door-opens-a-nodes-notes-tab-in-a-drawer-over-the-wall.md)):
◇ at the end of a head's icons opens the tab in the drawer — on the wall, or in the
head of a node's page — and a line's ◇, in its seat at the end of each line of
`/ci/reviews` and `/security/audit` that nothing handles, opens it with the form on that
line; where something handles the line, its mark stands in the seat and opens the same
form. Without script ◇ is a link to the tab.

The read/edit interaction has one concrete walk:

1. Open `/status/security/audit` while its findings are present. Every line ends in ◇
   in its seat. Move the pointer down them without clicking: no reason or control
   should move, and no form should appear. Tab through the same controls; each has a
   visible focus ring, and its name is *handle this line of /security/audit*.
2. Click the ◇ of a line far down the list. The drawer opens on the node's *Notes*
   tab, its form on that line, the cursor in the note. Choose *Maintenance*: the line
   stays chosen under *On*, the form says what a pin does, and the **Duration or
   expiry** field names the configured timezone; open *Which formats can I use?* by
   click and keyboard and confirm the full table fits the drawer. Enter
   `**owned** — [ticket](https://example.com/ticket)` plus `Friday` and save. The
   drawer closes and the page, which nothing refreshes, loads again where it stood:
   the line stays in place, takes the maintenance tint and carries its block — who put
   it in maintenance, the resolved expiry with what is left of it, and the bold word
   and link as rendered HTML — and its seat holds ‖ where its ◇ stood. Repeat on
   another line with `07-10` or a day such as `17` and confirm the displayed boundary
   is the next future midnight described by the help.
3. Click *Edit* in the block. The textarea contains the exact Markdown source, not text
   recovered from the rendered DOM, with the cursor at its end, and the expiry field
   holds the stored expiry; click into it and all of it is selected. Change the note
   and cancel once — the block returns with the stored note unchanged — then change
   the note alone and save: the expiry in the block has not moved. Edit again, empty
   the expiry field and save: the pin runs for the configured default from now. The
   line never alarms between the writes, and each save comes back **at the line**,
   ringed and in view, far down the list as it is. Then open *Edit* once more and
   save with **nothing changed**: who pinned it gains no *Last changed* beside it, and
   the same pin's editor left open in a second tab still saves. *Clear* remains a
   separate action, and comes back at the line too.
4. Repeat at node depth: ◇ in the head's row opens the drawer at the tab's top, and
   *Maintenance* there is *On* the node. Pinned, the node's block heads the page's
   frame, which runs round every line, the line pinned before says *also in
   maintenance on its own*,
   and raw `<script>` entered as a note stays visible as escaped text rather than
   becoming an element. With scripts disabled each *Edit* still opens its editor, and
   ◇ and each mark lead to the tab. A branch's page states its node's pin in its
   head, above the children, and ◇ stands there: open `/status/ci`, set a pin from the
   head's ◇ — *On* says *the node and everything beneath it* — and read it back in the
   block, whose *Edit* fills the expiry field the same
   way. Open `/status/ci/reviews`: its frame is headed by `/ci`'s block too, without
   buttons — *This node is in maintenance from /ci* — whose link leads back to the
   pin. Back on `/status/ci`, edit the node's note once more and read
   its **Time** card and its History: the card still says *maintenance since* the
   moment the pin was set, and History has one maintenance row, *current*, with the
   note as it reads now
   ([ADR-0099](adr/0099-a-status-that-still-holds-says-since-when.md) decisions 6 to
   8). *Clear* the pin: the card says *since* that moment, *when its maintenance
   ended*, and History's maintenance row has its end and keeps the note.
5. On the wall every open head carries ◇ — a box's as a card's — its tooltip *Handle
   it*; Tab to a head's name and on to its buttons, then → to the last of the head's own
   icons, reaches it without the pointer. Click the services card's: the drawer opens
   on `/services`' tab, the card
   lit behind it and the wall waiting (*The door, the drawer and ◇ details* above walks
   the drawer itself), and *Maintenance* is *On* *the node and everything beneath it*.
   Close it and open the `api` box's ◇: the drawer's head names the box, which is what
   stays lit. Then set the services pin, with *hide idle* on and a depth of your own in
   the address. The drawer closes and the wall, as it was asked for, is up to date at
   once: the card blue, and its ◇ lit with *1* beside its state, its tooltip *Handle it
   — 1 handled: 1 node in maintenance*. With *◇ details* on the card states its pin as
   the block in its wall's form — who, until when and what is left — one link that
   opens the drawer at it, its editor open holding the note's source and the stored
   expiry; *Cancel* there, and the note and *Clear* stand beside *Edit*. With scripts
   disabled ◇ is a link to the tab. On the kiosk the lit ◇
   is a mark, and the block — where `handled_details` puts it there — a sentence,
   neither a link; a viewer's ◇ says *Notes*, and the tab it opens has no form.
6. Pin a second node, so that two are, and open **Handled**. Under *In maintenance*
   the pins stand under their node's path, the node whose pins have stood longest
   first: *The whole node* first, then its lines in the order the node's own page lists
   them, each opening with its line and, under the node's pin, saying it is *also in
   maintenance on its own*; a node with only lines pinned has no first block.
   Beneath each note stands who pinned it, and who last changed it where somebody has.
   Click *Edit* in a line's block: the editor opens in the block, in place of that
   record, with the note's source and the expiry filled as in step 3. Save. The page
   comes back with that node's section ringed and in view, and no other marked.
   *Clear* one the same way, and follow *this line* in another: it lands on the line
   on its node's page. Narrow the window to a phone's width with an editor open;
   nothing on the page scrolls sideways.

**What is handled, and why a branch has its color**
([ADR-0135](adr/0135-a-handled-part-keeps-its-true-color-and-every-surface-says-by-what.md))
need a node's pin with a long note, a line's pin and a branch with something failing
beneath it:

1. Pin `/services` for `7d` with a note of several paragraphs — paste three of this
   page's — and open the wall with *◇ details* on. The card states the pin in one
   sentence, *In maintenance by pan until … · 7d left*, a chevron at its end; the note
   itself is not on the wall. Click the sentence: the drawer opens at the pin's block
   under *What stands*, for an admin its editor open — who set it and when, the note's
   source scrolling past a height — and *Cancel* showing the note whole; a viewer's
   block, which has no editor, shows the note whole at once. With scripts disabled the
   block is a link to the tab at it. With *◇ details* off the card says the pin by its
   blue and its lit ◇ alone.
2. The block's edge is dashed, and the block keeps its blue; nothing else on the wall
   has a dashed edge. No underline marks it as a link: it washes under the pointer and
   is ringed under the keyboard.
3. Pin one red line of `/ci/pipelines` with its ◇ on its page and close `/ci` on the
   wall: its chip carries ◇ and *1* after its counts, and its tooltip ends *1 handled:
   1 line in maintenance*. Pin a leaf beneath it whole: it counts as ‖ among the
   chip's counts, and the chip's ◇ still says *1*.
4. Open `/status/ci`. Right after the Time card a card says why the branch has its
   color — *Why error* or *Why warn* while something beneath it fails, listing each
   part that counts with its status and since when, or *Why ok* — and beneath ◇ and
   *‖ In maintenance* the two pins, the line's saying what it reads, each with who
   set it and until when and linked to where it stands. The Time card's *and N more*,
   where it has one, leads to it. A leaf's page and a pinned node's have none. Copy
   `/ci`'s document: after *Beneath it*, *Handled beneath it* lists the same.
5. The band's pill reads ◇ and the number of pins that stand, its tooltip by kind —
   *3 handled: 2 nodes in maintenance, 1 line in maintenance* — and leads to
   **Handled**; `/maintenance` in the address lands there too, its query kept.

**A pin whose node is not reported**
([ADR-0109](adr/0109-a-node-says-its-children-are-complete.md) decision 4) needs the job
name that comes and goes. Pin `/ci/jobs/backfill` for `10m` from its ◇ while it is on
the wall, and open *Handled* once it has left, within two minutes at the latest. Its
section stands under its path, which is no link there, says that the node is not
reported at present and that its pin holds nothing, and its block opens *The whole
node, when it is reported,*. It still stands, and is counted where it stands: the
wall's pill counts it, its row for `/ci/jobs/backfill` saying *not reported now*, and
`/ci/jobs`' ◇ stays lit, *1 node in maintenance* among its words — the drawer it opens
lists it beneath what stands, *backfill not reported now · by pan until …*, its link
opening the page of its path, which states the pin with *Edit* and *Clear*; on
`/status/ci` the *why* card lists *jobs/backfill not reported now*. *Edit* the note in
the block on *Handled* and save: the page comes back with the section marked, and no
node appears on the wall. When `backfill` returns it is in maintenance from its first
reading — `/events?under=/ci/jobs/backfill` shows its return as *maintenance*, and
beside it the reading its pin holds back — its section reads as any other, and the
drawer of `/ci/jobs` lists the pin as `backfill`'s own. Pin a line of
`/ci/jobs/backfill` instead, with its ◇ on its page, and the section says *One of its
lines, when it is reported,* and names no line while the node is away, the drawer of
`/ci/jobs` saying *a line of backfill not reported now*.

**A pin on a line its node does not report now** needs the review `/ci/reviews` merges
near the end of its 90-second cycle. Before 76 seconds into it, pin #4846 for `10m`
from its seat on `/status/ci/reviews` — the § of the rule that counts a short queue as
ok, or ◇ while six wait — *Maintenance* chosen in the drawer, *On* its line. When the
review is merged its line goes and its pin stays, holding nothing: *Handled* lists
it under *In maintenance* as *A line not reported now is in maintenance by pan until
…*, with no link and no slug, and with *Edit* and *Clear*; `reviews`' ◇ stays lit, *1
line in maintenance* among its words, and the tab it opens lists the same block under
*What stands*; the band's pill counts it, its row for `/ci/reviews` saying *1 line not
reported now*, the row's link landing on the node's page, which says the line is no
longer reported. *Clear* it on *Handled* before the cycle turns: the page comes back
without it, and so does the tab. Left alone, the pin holds the line again when the
review comes back next cycle. A silence on the line stands under *Silenced* the same
way until its deadline, where a seen ends as its line goes.

The **conflict page** needs no code either, only a recipe, because it is about two
people and one node. Every maintenance form carries the pin's `set_at` as a
compare-and-set token, and an *empty* token says "I believe nothing is pinned". A new
pin is set on the *Notes* tab, which answers such a refusal itself — two tabs on an
**unpinned** node:

1. Open the same node's *Notes* tab in **two tabs** and choose *Maintenance* in both.
   Neither form has a token yet.
2. Submit one of them.
3. Submit the other. The table now says something is pinned, its empty token no
   longer matches, and instead of silently overwriting the first pin the tab comes
   back with why above the form — *This node was put in maintenance since this tab was
   drawn* — your own words in it, and the first pin under *What stands*.

An edit lands on the conflict page itself, with a real token: open an existing pin's
*Edit* in two tabs — on its node's page, or in the drawer — submit the newer, then the
older: both reasons side by side, your own words intact; in the drawer the page stands
in it, and so does each way off it. An **entry** pin conflicts identically and the
page carries its slug, so the two tabs can be two per-line pins on the same reason of
`/ci/reviews`.

Do it once from **Handled** as well: open it in two tabs, open the same block's *Edit*
in both, save one and then the other. The conflict page is answered at the write's own
address, `/pins/maintenance`, so check each way off it — *Change nothing* above all, which is
a plain link — loads *Handled* again with that node's section marked, rather than
staying where it is.

**A pin's schedule, a window set ahead, and the upgrade**
([ADR-0150](adr/0150-a-maintenance-entry-is-its-schedule-and-holds-while-a-window-of-it-is-open.md))
read the demo's state directory, `var/demo/var/state/`, and the envelope, `curl -H
'Accept: application/json' -H 'Authorization: Bearer demo-token'` on a node's address.
Set `/services/api` in maintenance for `2m` from its ◇, *Starts* left blank: the drawer
closes onto a blue box, as it always did, and its entry in `pins.json` keeps a
`schedule` — `DTSTART;TZID=Europe/Berlin:` the moment it was set and `DTEND:` its end in
UTC — and no `expires_at`. Copy the entry. Two minutes later the box comes back on its
own, and `/events?under=/services/api` says *maintenance ended*.

Then a window **set ahead**: on `/services/web`'s ◇ choose *Maintenance*, *Starts* `2m`
and the end `2m`. The drawer stays open, at the new block under *Planned* beneath *What
stands*, which takes the focus — *The whole node · Once, from … until … · starts in 1m*,
with *Edit* and *Clear*, and no blue: it holds nothing yet, and the wall shows nothing
of it, ◇ counting none. The node's page lists it beneath its head's blocks, a door to
that block; *Handled* under *Planned*, *1 window on 1 node, the soonest first*; and the
envelope in the node's `planned`, its `starts_at`, `expires_at`, `until` and the
`sentence` the page shows. *Edit* opens with *Starts* and the end filled: change the
note alone and the start stays to the second; a *Starts* typed as a time already past is
refused, *To start the window now, leave Starts blank*, your words back in the form. At
its start the box turns blue by itself, *window opened* on the Events page, and
`/services`' History says *web a window opened*; two minutes later it ends, *a pin
ended*, its last window being its end, and its entry under *What came before* on the
*Notes* tab says *Planned as a window by pan · ended: with its window* and *· it ran 2m*,
where one set from now says how long it stood. Set `/services` itself, which reads
nothing of its own, in maintenance for `1m`: when it ends, its row on the Events page
says *nothing of its own*, still found by the *undefined* switch, whose title says so.

**A series on the page**
([ADR-0150](adr/0150-a-maintenance-entry-is-its-schedule-and-holds-while-a-window-of-it-is-open.md)
decisions 13 to 16): on `/services/web`'s ◇ choose *Maintenance* and *Repeats* *Daily* —
the rest opens in place, and the end field's label reads *Length* — with *Starts* two
minutes from now, `HH:MM`, *Length* `3m` and *Until* a week on, a date. Beneath the
fields the next five windows, the first today at that time, and the sentence, *Every day
from … for 3 minutes, until …*, follow the fields; without script *Preview* draws the
same in the page, nothing written. *Set maintenance*: the drawer stays open at the new
block under *Planned* — *Every day from … for 3 minutes, until … · next … · in 1m*, or
*2m* — its *Edit* the editor filled and its *Clear* asking first, *This ends every
window of the schedule, those to come*. When its window opens the box turns blue,
*window opened* on the Events page, and the block is two rows: the window, *by pan until
… · 2m left*, with *Extend* and *End now*; and the schedule, its sentence and *· next*
tomorrow's start, with *Edit* and *Clear*, which asks *this one and those to come*. In
the envelope its `handled` item's `expires_at` is that window's end and its `until` a
week on. *Extend* by *30 minutes*: the drawer closes on the write, the box stays blue,
and the block says *until …, extended by pan · 32m left*; an *Extend* whose *Until* is
before that end is refused, naming *End now*, your words back. *End now*: the box comes
back, *window closed* on the Events page, and the block stands under *Planned* with
tomorrow's start and *· 1 window ran, the last closed by hand, by pan*, the entry staying
in `pins.json` with its `changed`, and its note in `notes.json` with its `tally`. Set a window from
now on the same node: the form says *— a schedule stands on it* and *this window joins
it, beside its note*, and the Notes keep *A window joins the schedule, from … until …*;
while it is open, *Edit* the schedule to *Length* `5m` — *Starts* is the rule's next
start, not the window's — and the window keeps its end, `pins.json`'s text carrying it
as an `RDATE` period, the rule starting tomorrow; an edit while one of the rule's own
windows is open leaves that start out too, an `EXDATE`. For the instance's line, stop
the demo, take the current year out of `acme`'s `complete` in
`tests/demo_config/holidays.yaml`, start it, and set a series *Not on* *ACME's company
holidays*: from the next tick `/little-sister/holidays` says *ACME's company holidays
(acme) is not complete for …* and that it stops one maintenance entry, and the entry's
block from when its windows do not apply; put the year back. Then the upgrade: while
`/services/api` fails, silence it for `1d` and set
it in maintenance for `2m`, stop the demo, take the entry's `schedule` away and give it
an `expires_at`, as a release before this one wrote it, and start the demo. The start
says nothing of it; *Handled* lists the silence and not the entry, and `pins.json`,
written once the start has read it, no longer holds it.

**The month**
([ADR-0150](adr/0150-a-maintenance-entry-is-its-schedule-and-holds-while-a-window-of-it-is-open.md)
decision 17): on `/services/web`'s ◇ choose *Maintenance*, *Repeats* *Weekly* with
*Saturday* alone ticked, *Starts* `Sat 22:00`, *Length* `8h` and *Until* two months on,
a date. Above the next windows stands the month of the first Saturday: its name between
« ‹ and › », the two before greyed in this month; six weeks from a Monday, each
Saturday from the first saying *22:00* over *06:00* in maintenance's tint, today ringed,
the days before it dimmed and those of the months beside it faint. A day's title says
it — *Saturday, …: a window from 22:00 to 06:00 the next day. A click leaves its window
out.* Click the second Saturday: its *22:00* is struck, *Left out: the window from …
22:00:00 ×* is listed beneath, the sentence says *1 left out*, and `pins.json` is
untouched; click it again and the window is back. Click a Tuesday ahead: *A window from
… 22:00:00 ×*, the Tuesday saying *22:00* over *06:00*, and its × takes it out. Page
with › and then »: the name follows, and a year on both are greyed; « comes back. Leave
the second Saturday out and give the Tuesday a window again, and ✕ asks *Discard what
you wrote?*; keep writing, and *Set maintenance*: the entry's text in `pins.json` has an
`EXDATE` for the one and an `RDATE` for the other. On *Handled* the series' editor is
drawn without its month — the page's source holds no `ls-cal`, however many schedules
stand — and its *Edit* brings it as it opens, one `POST /pins/maintenance/preview` in
the network panel and none when it opens again; without script *Preview* brings it,
each day a button again. On another node, with *Not on*
*holidays in Bavaria*, page to a month with a Saturday the list names — Saint Stephen's
Day in December 2026: its title says its name, its *22:00* is struck, and a click adds
its window back, *A window from …*. From the keyboard the grid is one stop, Tab
reaching it once, at the first Saturday: the arrow keys move a day or a week, Home and
End to the week's ends, Page Down the month after on the same day — with Shift a year —
and Enter does the day, the focus staying on it. At a phone's width each day shows a
bar instead of its hours, the hours of it a window covers — a Saturday's last twelfth
and its Sunday's first quarter — and the drawer's sheet does not scroll sideways. A
series of *Starts* `2027-03-27 12:00`, *Length* `1d`, marks Sunday 28 March *+1h*, its
title *the clocks go forward an hour at 02:00*. Without script each day and each page
is a button that sends the editor back with it done. And an open window set once —
`/services/api` for `2h` — keeps its start when its *Edit* adds an interval beside it:
*Save changes* writes a `DURATION` and an `RDATE` period, and its block is the two rows
of a schedule.

### Seen

A failure marked seen
([ADR-0142](adr/0142-a-failure-marked-seen-counts-as-ok-above-until-it-changes.md))
needs no code either: an admin marks one on the node's *Notes* tab, *Seen* chosen in its
form — which ◇ on a head opens on *Seen* wherever something fails at or beneath the
node, and a failing line's ◇ on the line. The part keeps its color and counts as ok one
level up until it changes. The wall's blocks below stand there with *◇ details* on.

1. **A worsening ends it.** `/services/api` in its amber quarter, 15 to 30 seconds into
   its minute: its box's ◇ opens the drawer on *Seen*, *On* *its own failure*. Save it
   with a note: the box stays amber, the ringed check beside its state on its own green
   tint and a green rail down its right edge, its block saying *Seen by pan at* {warn}
   *· until it changes*, and `/services` counts it ok —
   the configured floor on the gateway counts after the seen, from the ok it passes. At
   30 seconds the gateway turns red, the seen ends and `/services` counts it red;
   `/events?under=/services/api` shows the row *seen* and the row *seen ended · worse*.
   Mark it seen again while it is red: at 54 seconds it recovers, *seen ended ·
   recovered*.
2. **A line, at its own page.** `/status/ci/pipelines` while the build fails, 32 to 72
   seconds into its 90: the build's line ends in ◇, which opens the drawer on *Seen*,
   *On* that line. Mark it seen, and the page loads again: the line keeps its red cue
   and tint, the green ringed check standing where its ◇ stood and a green rail down
   the whole row, with its block beneath it, *This line is marked seen by pan at*
   {error}. On the wall the line carries the ringed check at its top right, which opens
   the drawer at that block. The node is green — the waiting gate is healed by its rule
   — and at 72 seconds the build passes: *line's seen ended · recovered*.
3. **A line no longer reported.** `/status/ci/reviews` before 76 seconds into its 90:
   mark #4846 seen from its seat — the § of the rule that counts a short queue as ok, or
   ◇ while six wait — which opens the drawer on *Seen* with the line chosen. When it is
   merged, near the end of the cycle, its line goes and the seen with it, *line's seen
   ended · no longer reported*; when it comes back next cycle it alarms as new.
4. **A head's, each its own.** On the wall, while the nightly erupts — from 42 seconds
   into its minute — with the reviews waiting, open `/ci`'s ◇: the drawer's tab lists
   every failure at and beneath `/ci` under *What fails here now*, linked, and its form
   is *On* *all N failures listed above, each its own*. Save: each is a seen of its own,
   sharing the note; `/handled` lists them under *Accepted*, *N seen on M nodes, the
   longest standing first*, and each ends by itself as its failure changes. Open the
   drawer again, wait until a review opens mid-cycle (50 seconds into its 90) and
   save: refused above the form, *What fails here changed since this was opened.*, the
   failures listed as they stand now and the words kept; sent again, it marks those.
5. **Edit, Clear, and what it holds.** On a node's page the block's *Edit* changes the
   note and may give an end — *2h*, read as a pin's expiry is — which the sentence then
   says, *or* the time *· 2 h left*; *Clear* ends it at once, *seen ended · by hand*.
   The tab offers no *Seen* on a node in maintenance, on a green one, on one failing
   only because its reading went stale, or on what is seen already.
6. **What says it elsewhere.** A closed chip's ◇ counts what is seen beneath it, *2
   seen*, and the band's pill counts each seen beside the pins. `/services`' ◇ is lit,
   *1 handled: 1 seen*, and the tab it opens lists the gateway under *What stands*,
   under *Accepted* — *api, reads warn · seen by pan at warn · until it changes* — after
   anything in maintenance beneath it, as its *why* card on `/status/services` does.
   Copy `/services/api`'s document while it is seen: *☑️ Seen — by pan at warn ⚠️, until
   it changes*, and *☑️ Accepted* in `/services`'s list of what is handled. The JSON
   (`Accept: application/json` with the demo's token) says
   `"contribution": {"code": "OK", "by": "seen", "rule": "<its id>"}` on the gateway,
   and its `handled` lists the seen with the `status` it was set at.

### Silenced

A failure silenced
([ADR-0144](adr/0144-a-failure-silenced-counts-at-its-level-above-until-its-deadline.md))
needs no code either: an admin silences one on the node's *Notes* tab as a seen is
marked, *Silence* chosen over *Seen*, wherever something fails now — and on a part that
reads ok as well, a line or a node that reads by itself. The part keeps its color and
counts one level up as ok, or as a warning at most, through every recovery, until its
deadline. The wall's blocks below stand there with *◇ details* on.

1. **It holds through every return.** `/network/vpn` flips between ok and error every
   ten seconds. While it is red, open its ◇ and choose *Silence*, *On* *its own
   failure*: the form asks for a note, what it *Counts above as* — ok, or *at most a
   warning* — and a deadline whose placeholder names the default, *7d*. Save it with a
   note and the deadline blank: the box stays red, the struck bell beside its state on
   ok's green, its block saying *Silenced by pan, counting as* {ok} *until …*, and
   `/network` counts it ok. Ten seconds later vpn recovers and the silence stays; ten
   more and it fails again, silenced still — `/events?under=/network/vpn` shows the row
   *silenced* and no end. *At most a warning* draws the bell and the rail amber
   instead, and `/network` counts a warning. Clear it, and while vpn is green open its
   ◇ again: *Seen* is not offered, *Silence* is, *On* *the node*. Save one *at most a
   warning*: nothing changes until vpn fails, and then its bell and rail stand amber
   and `/network` counts a warning.
2. **A deadline it will not take.** Type *45d* as its deadline: refused above the form —
   *'45d' is more than thirty days away, which is longer than a silence may stand* —
   with the note, the level and *45d* back in it, and the drawer stays.
3. **An extension says what changed.** On `/status/network/vpn` the block's *Edit*
   fills in the deadline it keeps; type *14d* and save with *What changed* empty: it is
   refused, *an extension says what changed*. Write a sentence and save:
   `/notes/network/vpn` lists *Silence extended until … .* and the sentence, beside the
   silence's own note.
4. **Seen and silence change places.** While vpn is red, *Edit* on the silence's block —
   on its page, or in the drawer its bell opens — offers *Seen*: choose it and save —
   the silence ends, *silence ended · made seen*, and a seen stands, which ends at the
   next recovery. While vpn is green it offers the silence's own form alone.
5. **What says it elsewhere.** ◇ and the band's pill count *1 silenced*, *Handled* lists
   it under *Silenced*, and the tab `/network`'s ◇ opens lists vpn under *Silenced* —
   *silenced by pan, counting as ok · until …* and what is left of its deadline. Copy
   `/network/vpn`'s document: *🔕 Silenced — by pan, counting as
   ok ✅, until …*. The JSON says
   `"contribution": {"code": "OK", "by": "silenced", "rule": "<its id>"}` while vpn is
   red, and its `handled` lists the silence with `counts_as`
   `{"WARN": "OK", "ERROR": "OK"}` and its `expires_at`.

### Done

An event looked into and over, closed
([ADR-0146](adr/0146-an-event-marked-done-shows-ok-until-its-line-reads-anything-else.md)),
needs no code either: an admin marks a failed run done on its node's *Notes* tab, *Done*
chosen in the form, wherever a failing line says which event it is. The line shows ok
with the failure it closed beside it and counts as ok one level up, until it reads
anything else. In the demo the job names' runs are such events: `/ci/jobs/export` runs
once a minute and one run in seven fails, its line reading *run N failed in 4s* for that
minute.

1. **A failed run, closed.** While export's run fails, open `/notes/ci/jobs/export`: the
   form offers *Done* between *Note* and *Seen*, *On* its line, and says what it does —
   *until it reads anything else: its next run ends it, and alarms as new if it
   fails*. Save it with a note: the tab comes back, and under *What stands* the line's
   block says *… — this line is marked done by pan, closing* {error} *· until it reads
   anything else*. On `/status/ci/jobs/export` the line shows ok — its green cue with
   *· error ·* beside it, its own words unchanged, the ringed check at its end in ok's
   green and no rail — and the node is green, *Status ok since …, when a line was marked
   done*, as `/ci/jobs` is where no other job fails; on the wall the line folds with the
   healthy ones, and `/history/ci/jobs` says *a line marked done* began its period.
2. **The next run ends it, and alarms as new if it fails.** A minute later the next run is read and the done
   ends, whether that run failed or passed: `/events?under=/ci/jobs/export` shows the
   row *line done* and the row *line's done ended · a new occurrence*. A done never
   covers the run after the one it closed — when a run fails again, six minutes on, it
   alarms as any failure does.
3. **Where there is no event.** On `/notes/ci/pipelines`, while its build fails, the
   form offers no *Done*: nothing tells one failure of the build from the next. Nor on
   `/notes/network/vpn`: a node's own failure is a stretch, not an event.
4. **Seen, silence and done change places.** While export fails, mark its line seen
   with its ◇. *Edit* on the seen's block on `/status/ci/jobs/export` offers *Done* as
   well: choose it and save — *line's seen ended · made done*, and the done stands.
   *Edit* on the done's offers *Seen* and *Silence* back.
5. **Clear, and a form opened on another run.** *Clear* on the done's block ends it at
   once, *line's done ended · by hand*, and the line reads its error again. Open the
   tab's form while a run fails, wait for the next run, and save: refused above the
   form, the line reading ok now, the words kept and nothing written.
6. **What says it elsewhere.** ◇ and the band's pill count *1 done*, and *Handled* lists
   it under *Accepted*, *1 done on 1 node*, its block's *Edit* offering *Seen* and
   *Silence*. Copy `/ci/jobs/export`'s document: *✅ run N failed in 4s*, and beneath it
   *☑️ Done — by pan, closing error ⛔, until it reads anything else*. The JSON says
   `"contribution": {"code": "OK", "by": "done", "rule": "<its id>"}` on the line, whose
   `code` stays `ERROR`, and its `handled` lists the done with the `status` it closed,
   `ERROR`, and its `occurrence`, `export-N`.

### Configured rules

A deployment's configured rules
([ADR-0137](adr/0137-a-deployment-says-in-a-table-how-a-part-counts-above-it.md)) need
no code either: `tests/demo_config/aggregation.yaml` writes one rule of each kind on the
scripted checks, and the demo reads it at its start as a deployment reads its own. Every
part keeps its true color; what changes is what it counts as one level up, under § and a
sentence that names the rule. The wall's blocks below stand there with *◇ details* on.

1. **The cap.** When `/ci/nightly` erupts, from 42 seconds into its minute, its box
   stays red with its twelve lines and an amber § beside its state, and beneath its
   head a block with a dashed edge and no fill says *{error} counts as {warn} above, by
   the rule nightly advises*, the two statuses drawn as their signs; a click on it
   opens the drawer at the rule's block, its note and *Configured in
   …/aggregation.yaml since 2026-10-24*, with no buttons for an admin either. `/ci`
   counts the nightly amber. Close `/ci`: its chip counts the nightly as an error among
   its counts, and its ◇ says *1 by a rule*.
2. **The floor.** `/services/api` in its amber quarter, from 15 to 30 seconds into its
   minute: the gateway's box is amber under *{warn} counts as {error} above*, and
   `/services` is red. `/status/services` says *Why error*, and lists the gateway under
   *§ By a rule*: what it reads, what it counts and the rule, since when.
3. **Healing one named line.** `/ci/pipelines` while `deploy-gate` waits and the build
   passes — 27 to 31 and 72 to 81 seconds into its 90: the gate's line keeps its amber
   cue and tint, a green § at its top right beside a green rail, its tooltip *Counts as
   ok by the rule a waiting gate is no failure*, the node's block says *On 1 of its
   lines, {warn} counts as {ok}*, and
   the node is green. While the build fails the node is red, the rule changing nothing
   of it.
4. **A count over lines.** `/ci/reviews` is green while five reviews wait, each line
   with § at its top right on its own green tint, its rail on a strip of the page, since
   a line with no tint of its own stands on the card's fill, and its block says *… while
   fewer than 6 fail — 5 do*. From 50 to 76
   seconds into its 90 six wait: the block leaves the wall, the lines count as they read
   and the node is amber, and its page keeps the block with *— 6 do · changes nothing
   now*.
5. **A count over children.** `/hosts/fleet` while node-04's disk is full, 24 to 42
   seconds into its minute: node-04 and its disk stay red, node-04 with an amber § beside
   its state and an amber rail, the fleet's block says *Of its children, {error} counts
   as {warn} while fewer than 2 fail — 1 does*, node-04's
   page says *Among /hosts/fleet's children, …*, and the fleet is amber.
6. **What changes nothing now.** `/handled` lists the six under *By a rule*, the longest
   standing first — here the file's order, every rule dated the same day — each its
   block with the path it picks, its note and its file, and beneath it what it changes
   the count of now, each part linked, or *changes nothing now* and why. *backfill is a
   one-off* picks nothing while the job is away; while it is on the wall it changes the
   count of `/ci/jobs/backfill`, which counts nothing above. The band's pill counts the
   parts the rules change now beside the pins, and its popover's *N by a rule…* leads to
   the section.
7. **The log and the envelope.** `/events?under=/ci/nightly` shows the eruption's row
   with the chip *aggregation*, which *held back* hides; `/events?under=/ci/pipelines`
   shows the gate's wait as a row of its own, the reading the node did not show, marked
   the same. The JSON (`Accept: application/json` with the demo's token) says
   `"contribution": {"code": "WARN", "by": "aggregation"}` on the nightly, and the
   gate's entry carries `"contribution": {"code": "OK", "by": "aggregation"}`. Copy
   `/ci`'s document: *Handled beneath it* lists *§ By a rule* after *In maintenance*.
8. **A rule that cannot apply.** Stop the demo, change `nightly advises` to
   `counts_as: {ERROR: OK}` and start it: `/little-sister`'s startup line names the file
   and the rule, and says that it does not apply because a worse status would count for
   less than a milder one; the nightly turns `/ci` red again, and the other five apply.
   Put the file back.

### Holidays

A deployment's holidays ([ADR-0149](adr/0149-a-deployments-holidays-are-named-lists-of-the-days-nobody-works.md)) are a
file as well: `tests/demo_config/holidays.yaml` lists *holidays in Bavaria*, the state's
public holidays of 2026 and 2027, and *ACME's company holidays*, and the demo reads it at
its start as a deployment reads its own. Nothing on the wall reads the lists yet —
maintenance that leaves a list's days out is the first reader — so what there is to see
is what of the file cannot be read, on the instance's own node.

1. **A list that cannot be read.** Stop the demo, write `2026-11-01: Allerheiligen` among
   `DE-BY`'s dates — the day a second time — and start it: on `/status/little-sister` the
   *startup* card turns amber, `/little-sister` with it, and says *…/holidays.yaml: the
   holiday list DE-BY cannot be read — it writes 2026-11-01 twice*; ACME's list stands,
   named nowhere.
2. **A file that cannot be read.** Put the day back and write `regions: {}` at the top
   level instead: the line says *…/holidays.yaml writes regions, which it does not know,
   so no holiday list can be read*. Put the file back and start the demo once more: no
   line of the holidays is left.

### Tags

The demo tags its nodes as a deployment does
([ADR-0139](adr/0139-a-node-carries-every-tag-written-for-it-or-above-it.md)):
`tests/demo_config/nodes.yaml` gives `/services` *production* and *customer-facing*,
`/ci` *internal*, `/storage` *production* and `/hosts` *hall-2*, the fleet's own check
file gives `/hosts/fleet` *production*, and `tests/demo_config/tags.yaml` says what each
means.

1. **On a node.** `/status/services/api`: the *About* card lists *production* and
   *customer-facing* as chips between its text and its details, each one's tooltip what
   the tag means and *written on /services*. The wall's hover card names them in one
   line, and the Copy document lists them under *Tags*.
2. **The wall filtered.** The band's list beside *hide idle* offers the four tags in
   `tags.yaml`'s order. Choose *production*: the address says `?tag=production`, the
   cards are `/services`, `/hosts/fleet` — *hosts ›* muted before its name — and
   `/storage`, and the line above them says what the tag means, names the failing parts
   the filter hides — `/ci` while a pipeline fails, `/hosts/nas` while its disk is full
   — and leads back to every node. A click on *fleet* closes it to its head, and the
   refresh keeps both the close and the filter. A chip on an *About* card leads to the
   same wall.
3. **Beneath a node.** `/status/hosts?tag=production` is the fleet alone in `/hosts`'s
   frame, with `/hosts/nas` among what it hides; `/status/ci?tag=production` says
   *Nothing beneath ci carries production.*
4. **Nothing remembers it.** Open `/status` again: every node, the list on *every node*.
5. **Events.** `/events?tag=production` lists the changes of what carries the tag — the
   gateway's, the fleet's, the backup's — and counts them against the log; its *tag*
   list offers the same tags.
6. **A rule by a tag.** Stop the demo, add to `tests/demo_config/aggregation.yaml`

   ```yaml
     - name: internal advises
       tag: internal
       counts_as: {ERROR: WARN}
       note: Delivery is ours alone; it advises.
       since: 2026-10-24
   ```

   and start it. While a job or a build fails, `/ci` stays red on its own box and its
   block says *{error} counts as {warn} above, by the rule internal advises*; `/handled`
   names what it picks *What carries internal*. Write `tag: intenral` and start again:
   `/little-sister`'s startup line says the rule picks what carries *intenral*, a tag
   the configuration writes for no node, and does not apply. Put the file back.

### History

`/history/services/web` lists every reading the latency scenario keeps
([ADR-0102](adr/0102-a-readings-table-keeps-time-and-names-in-view.md)). Scroll the
readings box both ways: its heading row and its Time column hold still, and its
scrollbars stay at its edges; tab into it and scroll with the arrow keys and Page Down.
*Response time · ms* heads the declared column over `response_ms`, before the fields
nothing declares. `/history/services` declares nothing of its own and says so in the
table of its own periods, beneath the periods of what it shows
([ADR-0132](adr/0132-a-branch-keeps-the-period-of-what-it-shows-beside-the-log.md)
decision 6): each names under *From* the node whose change began it, linked to that
node's History — *itself* where its own change did it — and under *What* what moved it,
the oldest neither, since it began before the log's oldest row; past fifty, the older
ones stand in one fold, *N earlier periods*, that opens without a script. A node the
log holds no change of shows the period that holds, since *before* the log's oldest
event — after a long run, or with a seeded log (below) whose events name other nodes.

`/history/ci/jobs/import` lists every kept run of a job name with its code's cue and its
sentence, the older runs' from the lines its grading wrote for the record;
`/history/ci/jobs/cleanup` lists its older runs without either, which is what their bare
ticks say. `/history/ci/jobs` lists `backfill`'s kept runs while that job name is gone —
*All 6 readings kept of* `jobs/backfill` — and no such table while its node stands,
where they are the node's own (ADR-0109 decision 6).

### Notes

`/notes/ci/reviews` is the place to act on the review queue
([ADR-0145](adr/0145-a-nodes-notes-tab-is-the-place-to-act-and-every-pin-leaves-an-entry.md)):
two columns at a desk, one on a phone — what fails, the line on what came before, what
stands, the form, then what came before. *What fails here now* lists every review
waiting, each linked to its line, and the form opens on *Seen*, *On* every failure
listed. On the Status page a line's seat — the § of the rule that counts a short queue
as ok, or ◇ once six wait — opens the tab in the drawer, its form on that line, *Seen*
chosen, the line failing; *Note* keeps the line chosen. On the tab itself write one
with a link,
`[OPS-4411](https://tracker.example.org/OPS-4411)`: the write comes back to the tab, which
says *Notes 1*; the note heads *What came before*, and the line above *What stands* says
*Noted once here since …* with *OPS-4411 ↗*. Type a few words under *Note* and choose
*Seen*: the words follow, and so does the line chosen. Mark that line seen: its block
stands under *What stands*, with *Edit* and *Clear*, and nothing joins the history while
it stands; *Clear* it there and it joins *What came before* — *Seen · on its line …*,
from when to when, *ended: by hand, by pan* — and the line says *Last time: seen …*.
Set a line's maintenance from the form with `2h` and clear it: the same, in
maintenance's words. Silence a line with `45d`: refused, why above the form, and the
words, the line, the level and `45d` back in it, nothing written. On `/notes/ci`, *Seen*
on every failure listed marks each part beneath it in one act; while they stand
`/notes/ci` lists them under *What stands* as its *why* card does, and once every one
has ended it has one entry — *… parts in one act*, folded to its parts, each with the
status it was seen at — and `/notes/ci/reviews` the same act, its own parts of it, *…
parts of … in one act, made on /ci*. The demo's jobs fail and mend every few seconds,
so the act may come back refused — *What fails here changed since this was opened*,
what fails listed anew and the words kept — and is sent again as it comes back. The
newest note of its own keeps *Edit* until a pin is set after it: an edit from a second
tab, opened before it, is refused in its editor with its words kept.
*What the line showed then* folds what the node and the line said as the note was
written. `/copy/ci/reviews` has a *Notes* block after its reasons, the newest note with
words whole, its pin said as the tab says it — *☑️ Seen — by pan …, ended: by hand, by
pan* — and how many entries more there are. Write a note on `/ci/jobs/backfill` while
it stands, and its address lists it once the node is gone. A pins file a version before
wrote, a pin's text under `reason`, starts its pins without their text, and
`/little-sister/startup` says how many.

### Handbook

`/status/services/api` carries a *Handbook* tab between *Notes* and *Copy*, and so
does every other view of the node; `/status/services` carries one too, and
`/status/services/web` none
([ADR-0133](adr/0133-a-node-says-what-it-is-in-a-card-and-at-length-in-a-handbook.md)
decision 3). `/handbook/services/api` is the gateway's runbook, a file of the demo's
`handbook/` that its check's file names: its *Sign in* link opens at its section,
beneath the sticky bar and not under it, and so does its *when it fails*, written in the
short form, `handbook#when-it-fails`, which on its own page stays in the page;
`/handbook/services/api#when-it-fails` opens at that heading. `{warn}` and `{error}` in
its headings are drawn as their signs, and its *Who to call* is a table, drawn as GitHub
draws one, its *weekends* struck through — on a phone it scrolls sideways inside itself
where it is wider than the screen, its words whole in their cells. Its crumb `services`
opens the services' handbook, and `nodes` the overview, the root having none. Hover the
gateway's name on the wall: the card ends in a *Handbook* line, and so does the
services' card. `/handbook/services/web` answers `404` and says where a handbook is
written.

The gateway's About card says *what to do*, a link its about writes in the short form
(decision 4): it opens the runbook at *When it fails* in a tab of its own, and so does
the same link in the hover card. Its Copy tab names the runbook beside *Dashboard*, its
address as the page was reached. Write `handbook: handbook/gateway.md` in the gateway's
check file in place of its own, a file the demo does not have, and restart: the tab is
gone, and the startup node says which file the check names and that its about links
`handbook#when-it-fails` on a node with no handbook.

### Details

`/status/services/api`'s About card ends, after a thin rule, in a table of its details
([ADR-0133](adr/0133-a-node-says-what-it-is-in-a-card-and-at-length-in-a-handbook.md)
decision 6): *owner* first, *API squad*, the gateway's own, standing in the row
`/services` named first; then *on call* and *tickets*, given down from `/services` —
hover either key and its tooltip says `/services` — and *docs* last, its own. *on call*
opens the services' handbook at *Who to call*, the handbook of the node it is given on
and not the gateway's runbook. `/status/hosts/fleet/node-03` reads *host* first, its
object's name from the run, then *site* from `/hosts` and *rack* from the fleet's check
file: a place told level by level. `/status/hosts/nas` and its disk read their objects'
details first, and the site beneath them. On a phone the table keeps each key on one
line and breaks a long value anywhere rather than widening the card. The gateway's Copy
tab carries the same rows under *Details*, after its facts, *on call* written out to
the services' handbook's full address. Write `tickets:` with no value under the
gateway's `details:` and restart: its row is gone from the gateway's card, and stays on
`/status/services`.

### Events

`/events` shows what its URL names
([ADR-0101](adr/0101-the-events-page-is-filtered-by-its-url.md)), and the demo's own
log grows too slowly to judge that by. Give it a busy one: stop the demo, write a log
into `var/demo/var/state/events.json.gz` — `{"events": [...]}` under gzip, oldest first, each event
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
page and on *Handled*: it fits. Tap an action chip once — *Copy* or
*Nudge* on a line of `/status/ci/reviews`' head, *File it* in a card's head on the
wall: the link is followed on that tap, and no inspection card comes up for the node
the chip stands in; a tap on the node's name opens or closes the node, and no card
comes up for it either. Two things do
not fit, and are known: the rail's labels, opened, stand beside the page and take half
a phone's width, and at 320 pixels the wall under the rail is a few pixels wider than
the screen.

### The tree, and the tab's map

Every node on the wall is closed, a **chip**, or open, a **box**, and a click on it
changes which, where it stands
([ADR-0127](adr/0127-the-wall-is-a-tree-and-a-click-opens-or-closes-a-node.md)
decision 1). Click the `web` chip in the services card: it opens in its place to a
box with its head and its lines, the chips beside it standing where they were, and
the focus is on the box's name; click anywhere on that head — the name, the title,
the state word, the space between — and it closes to the chip again, but a click on
its icons or on the *File it* action is that control's, and a drag that selects the
head's text toggles nothing. Ctrl-click (⌘-click) a chip or a name: the node's page
opens in a new tab, as the link says. Tab to a chip and press Enter or Space: the
same. A click on a card's head closes the card to one line, its head and its counts —
*hosts* reads *● 2 ✓ 11*, or *● 1 ✓ 12* in the half minute `node-04`'s disk is fine,
and *security* *6* — in its place, the other cards unmoved, and a click opens it
again; a closed card that fails is vivid, as a failing chip is. Each chip says what
is beneath it: a cue, its name and its counts, one total where all share a state and
each state's glyph and count where they mix, none on a leaf of one line — `audit`
reads *53*, `web` its cue and name alone; rest the pointer on a chip and the words
are the tooltip — *53 ok*, *1 ok*, and on a card's name *2 errors, 11 ok*. In the
developer tools each node carries `data-why`, the rule that
decided its look: `drawn`, `entry` once you clicked it, `swq` on `informational`,
`parent` after its parent's ▤, `mode` under a band button, `page` for a page's own
node and its children, `kept` for a card an open node beneath it keeps open under
*Close all*.

The **head's icons**, right after each open head's name and shown while the pointer
is on the head (*Head's buttons*, below): ↗ opens the node's
page; the **funnel** folds the node's healthy children and lines behind *✓ +N ok*
after the rest, pressed while they are folded, its tooltip the count — on `fleet` it
folds the four green hosts behind *✓ +4 ok* and leaves `node-04`, and on `wiz` a
press takes `informational` too, which the configuration would leave open; **▤**
folds every
child to a chip, pressed while all are, released while all are open and half-washed
between, and a click on one child afterwards changes that child alone; and last,
for every reader, **◇**, the node's door (*The door, the drawer and ◇ details*,
below). A dot on a button says the viewer set it differently from the configured
look. On the
kiosk no head carries them, and a tap toggles a node as anywhere.

The **head's row** never wraps: before the state stand the node's **actions** — on
the security card *Runbook*, a square wearing its icon, its label the tooltip, and
*File it*, a chip wearing its label since it names no icon — and the state and the
icons end the row, the title between the name and them giving way first, with an
ellipsis (`jobs`' *Batch j…*). Narrow the window to a phone's: the actions a row has
no room for fold behind **⋯** — `wiz`'s box folds *File it* and *Runbook*,
`informational`'s all three — but never one alone where the state's own line keeps
it in the row: `jobs`' box keeps *File it* and carries its state on a line beneath.
Open ⋯ by a click or by Enter: its menu lists the folded by their labels, ↓ and ↑
walk it, Escape closes it and gives ⋯ the focus back, and so does a click elsewhere;
widen the window and the actions are back in the row within a moment. The
demo's cards carry their state on a standing second line (`card_status_line: below`
in its `settings.yaml`); set it to `beside` and a card's state stands in the row,
dropping beneath only where the name would be cut with every action folded. A box's
state does the same without a setting: on a phone `ci`'s `jobs` and `pipelines`
boxes, whose rows hold a time beside the word, put the state beneath and keep *File
it* in the row; narrower still, a name wraps, last of all, where its words meet —
`collect-queue` after its hyphen, a name of underscores after one of them, never
inside a word that fits a line — and a copy of it is the name whole; and where
it has broken onto a second line the state stands on that line, beneath the icons,
instead of a third of its own — at a small phone's 320 pixels `pipelines`,
`workflows` and `wiz`'s `informational` show it, while `nightly` and `reviews`, whose
names stay whole, keep the state on a line of its own. Each square's symbol is 16 of
its 24 pixels — two thirds, and still two thirds with the browser's font set larger —
and a card's chips stand a little below its own lines, as a box's do. Narrow a card
until its title has less room than two letters: it goes rather than leave a clipped
letter. No caret stands before a head's cue: move the pointer along a head, and the
row is washed with its own ink wherever a click would open or close it — on the
name, the title, the state, the space between — and not on its squares, its actions,
⋯, its menu or a card's ◇ lit beside its state; press, and the wash deepens; the name
underlines no more. A chip answers the same way, its press a deeper wash over its
color; Tab to a
chip and its focus ring stays under the pointer. That is the look `toggle_hover:
wash`, the library's since 2026-10-18; choose *Under the pointer: outline* in the
settings menu and the row and the chip wear an outline of their ink instead, a chip's
a pixel out, the press still a wash. On a phone neither the outline nor the underline
shows, only the press. The
controls of a head are **one toolbar**: Tab stops once in it, on the control last
used there, and ←, →, Home and End walk the rest; put the keyboard on *File it*,
wait for a refresh, and the focus is on *File it* of the same node. On a touch
screen the squares stand 8 pixels apart, and a tap in the gap lands on the nearer
one. A box whose lines run past the budget ends them in **⌄ all N** — `nightly`'s
*⌄ all 12*, `pipelines`' *⌄ all 8* — which shows the lot and reads *⌃ less* until
clicked again. Where the lot stands taller than about half the window, it scrolls
inside the box: make the window short until `nightly`'s twelve pass half of it, Tab to
the lines and scroll them with the keys, wait ten seconds, and they stand where you
left them; *⌃ less* folds them to their first lines.

The band's three buttons: **Close all** closes everything the configuration opened
and keeps what you opened, with the nodes above it — open `web`'s `api` first, press
*Close all*, and the services card and `api` stand open while everything else is a
chip or a one-line card; the button is pressed and carries *· 1*, the one node the
map holds, and a second click on it closes everything. **Open all** opens every node,
the healthy shown; **As configured** brings the first
look back and empties the map, and with a `depth=` in the address loads the address
without it. `depth=2` in the address closes every node two levels below the wall —
the cards' children — for that one load, the viewer's word, and writes no cookie;
`depth=0` keeps the one-card overview, closed to its head and counts, which a click
opens to its own lines.

**Find** in the page (Ctrl-F, ⌘-F): type a word of a chip's line — of `node-02`'s
disk reading under the fleet, or of an audit finding under `security`'s `audit` chip
— and the match opens its node and every closed node above it as a click would,
the band counting them; type a letter at a time in Safari, Firefox and Chrome and
watch which boxes close again — a reveal is provisional for two seconds, and a later
match elsewhere within them closes what the earlier one opened, but for the nodes
above the new match, while a click or a key in the page keeps it; a closed node's
name is on its chip and in its hidden head, so stepping through a name's matches
opens the node at the second; what the funnel folds stays beyond the find.

A close **holds for its incident** (decision 9): close `node-04`'s `disk` box under
the fleet while it fails, and it stays a red chip through the half minute it recovers
in each cycle — a recovery shorter than ten minutes by the server's clock is a
flicker, and only a failure after ten minutes out of failure opens the node again.

A **node's page** is the same tree, framed (decision 8). Open `/status/ci`: the frame
wears the node's state at its edge, and its head is the node's own row — its name,
title and state, its actions and its icons, the funnel, ▤ and ◇, and no ↗ —
with what the check says of itself beneath it and the page's cards inside the frame; a
click on that head opens and closes nothing. Press ▤ and the cards close; back on the
wall, `ci`'s children are chips there too. Open a leaf's page,
`/status/security/audit`: it is framed the same way, with no status card — its head,
then its findings inside the frame and its facts after them — and its funnel folds the
healthy findings: open `audit`'s chip on the wall, and they are folded there too. ◇
in either head's row opens the node's *Notes* tab in the drawer; with scripts disabled
it is a link to the tab. On a
node's Status tab its *About* card stands beside its facts (ADR-0133): what its check
reads, muted, and its *about* beneath. At a desk it stands to the right of *Time*, the
facts at their 820 pixels and a leaf's page as wide as 1,300 for it; narrow the window
until it no longer fits beside them, or open the page on a phone, and it stands among
the facts, before *Configuration*. A branch's stands beside its facts after its
children. The node's other views — Series, History, Handbook, Copy — show neither text,
and its head no longer says what its check reads. `/status/services/api`'s about names the
statuses it cycles through, `{ok} → {warn} → {error}`, and the card draws each as its
sign — the status's cue and its word on its own tint, glowing in cyberpunk — where the
file says it in braces; switch the theme in the settings menu and each stays readable
on its card.

What a viewer opens on the wall stands through the refresh and a reload (decisions 9
and 10): one script, `static/js/tree.js`, keeps it in the tab's `sessionStorage`
under `ls-wall-map`, and `poll.js` hands it the swap. Open **+2 more** on the hosts
card and *⌄ all 8* on `/ci/pipelines`' box, then wait ten seconds: the grid is
swapped and both stand, the card's new readings under them. Reload the tab: both
stand, and the grid does not flash its first look before they come back —
`tree-pending.js` in the head hides it until the map is applied. Open the wall in a
**new tab**: it starts as configured, and the first tab keeps its own. Put the
keyboard's focus on *⌃ less* (Tab to it) and wait for a refresh: the focus is on the
same control of the same box, and the page did not scroll; the same for a chip or a
box's name. Rest the pointer on a card's name until its inspection card is up and
wait for a refresh: the card stays on its node. In the developer tools, *Application
› Session storage*, the map reads
`{"v":1,"mode":null,"nodes":{"/hosts/fleet":{"more":true},"/ci/pipelines":{"lines":true}}}`,
a click on a chip adds `{"open":true}` under its path, a press of ▤ `{"chips":true}`,
and a second click on each empties it; no cookie is written. Switch the layout to
**kiosk** and open a fold: a reload starts as configured and the storage holds no map
— the kiosk keeps it in memory, and five minutes without a pointer, a touch, a key or
the wheel bring the first look back, with the address's `depth=` as it was.
`/system` refreshes as it did; it has no map.

### The runs of chips, the hover card, and the looks a browser chooses

A run of chips lines up in the columns its level shares
([ADR-0127](adr/0127-the-wall-is-a-tree-and-a-click-opens-or-closes-a-node.md)
decision 12). On the hosts card the fleet's chips stand in columns, each stretched to
its column with its count at the right, and the runs on either side of an open box
line up, one `x` down a column. Open a chip, wait for a refresh, reload: the columns
stay where they were. Narrow the window until two columns no longer fit: the run
wraps as it comes, each chip at its own width, sharing lines, and no name is cut; widen
it again and the columns come back. A name wider than its column wraps where its words
meet. In the settings menu *Chips: wrapped* draws every run as it comes; and with
JavaScript off the columns still stand, sized by the server's estimate, which decides
too where a run has room for one column only — so a run near the line may change from
one to the other as the page's script measures its level.

The card answers a node's name alone ([ADR-0019](adr/0019-inspection-popover.md)'s
updates), once a browser asks for it: the library's look is `inspection_card: off`
since 2026-10-18, so first choose *Hover card: on a pause* in the settings menu. Then
rest the pointer on the name of a chip that wears the help cursor — its node
has a title, an *about* or a description — and about two thirds of a second later its card comes up — the name and the title as the head draws
them, the first block of its *about*, and *… N more paragraphs on its page* linking
there where more follows, or what its check reads where it has no *about* — and not
sooner; moving on the name starts the pause again.
Rest it on the rest of a head's row, its title, its state or an icon: nothing comes,
and only the names that have a card wear the help cursor, the row the pointer's. Click
a name: the node opens or closes and no card follows, even with the hand still moving
on it. Tab to a name: the card is up at once, and Escape closes it. On a node's page
its own head has none — its *About* card stands on the page. Back in the settings menu:
*Hover card: off* keeps the card closed for the pointer and the keyboard, and no name
wears the help cursor; with the operating system's high contrast on (forced colors) a
head's row and a chip wear the outline whichever look answers the pointer. Both
survive a reload, and `/preferences` writes a look into the cookie only once it is
chosen: set `inspection_card: pause` in `tests/demo_config/settings.yaml` and restart
the demo, and a browser that never chose has the card, while one that chose *off*
keeps none. The demo is drawn in the library's theme, cyberpunk; *Theme: plain* is
the light palette the other themes are drawn from.

An open head's buttons stand right after its name under the library's look,
`head_buttons: pointer`
([ADR-0127](adr/0127-the-wall-is-a-tree-and-a-click-opens-or-closes-a-node.md)'s
updates): at rest a head shows its name, its title right after it and its state, and
the pointer anywhere on the head shows its buttons over the title, on the box's fill —
nothing moves — and leaving it hides them again, after a click on one of them too; Tab
onto a name shows its head's, and an open ⋯ menu keeps them while the pointer goes
elsewhere. On a phone they show always. *Head's
buttons: on a line beneath* gives them a line of their own under the name; narrow the
window until a long name and its state no longer share a line and the state goes
beneath, at the right, nothing behind ⋯ — and the demo's `card_status_line: below`
puts a card's state at the right of the buttons' line. *Head's buttons: at the end,
the name opens the page* puts the state and then the buttons at the row's end and ↗
out of sight: the name underlines under the pointer and a click on it opens the
node's page, a click on the rest of the row opens and closes the node, and from the
keyboard Enter and Space on the name open and close it, while Tab and the arrows
reach ↗ in the toolbar, shown once it has the focus.

Open the settings menu: its first row says whom the browser is signed in as, and *Log
out* at its far end is a button, there to press as the menu opens — shorten the window
until the looks scroll inside the menu, and it still is. Beneath it the headline
*Display* says where the choices are kept: in this browser, not in the account. At its
foot *Using the wall* opens `/help`, the account of using the wall the package ships: at
a desk it stands at the last column's foot, and the menu fits the window as it did; on
a phone it ends the menu. `/help#the-band` opens at the band beneath the bar. Each group
says beneath its heading what it changes, the layout's too, in a muted line that wraps
in its column and never widens the menu; a screen reader names the group by its heading
and reads its line as the focus enters it. At a desk the groups stand in three columns,
read down each in turn, and the menu fits a laptop's window without scrolling; narrow
the window below 72rem and they stand in two, below 36rem, a phone's, in one. The last
group, *Failures*, is the failure budget's switch
([ADR-0127](adr/0127-the-wall-is-a-tree-and-a-click-opens-or-closes-a-node.md) decision
5): under *open their way*, the default, a failure beneath a chip opens
its way, the first three in each card with the nodes on their paths; choose *stay chips*
and every failure stays the red chip its look drew and the wall keeps its size, and the
group's line says to keep the default, a kiosk's too. Set `failures: chips` in
`tests/demo_config/settings.yaml` and restart the demo, and a browser that never chose
keeps its failures shut while one that chose *open their way* opens them. *Close all*
turns the budget off for the tab whatever the look. Choose any look and the page draws
itself again with it, the menu open on your choice and the focus on it; a click inside
the menu that changes nothing leaves it open, and *Escape* or a click beside it closes
it. The band's *hide ok* reloads the page too, and leaves the menu shut.

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

The other three modes are for *looking*. Contrast is the one property looking is bad at:
a red that reads fine to you can be under the bar, and the accessibility bar outranks
any picked swatch. `tests/sweep_contrast.py` walks every theme — the settings menu
opened on `/status`, the rows on `/links` that are not plain body text and the folds of
its setup guide, closed and opened, the coded reason lines of a seeded tree, on its leaf
page a pin's block with its buttons and its opened editor, *Handled*'s count, headings
and records, the same block on the wall while *◇ details* is on — in a box inside a
card, the link that opens the drawer at it, its sentence at rest and on the wash the
pointer lays over it, its chevron and its dashed edge — in the card a node's page draws
at depth 0, its editor opened and saying *updates paused* at its top, and in a branch's
head — the drawer a door opens over the wall, its head's state, links and
*updates paused* — a configured rule's block on a red, an amber and a green node, its
words, its chevron and its dashes, what handles a part — a line's mark on a warning's
tint, an error's and a box's fill, a head's mark and its lit ◇, § on a line, and their
rails, against the non-text bar — and a shield's words beside its state, every culprit's
own name and state word on its fill, a failing box's, a warning's, a pinned box's and an
undefined card's, the head's row's chips, *⌄ all N* and the band's buttons, and its
squares, the icons on an error's and an ok's fill, ⋯ on a card drawn narrow for it and
an action wearing its icon, their glyphs and their resting edges against the non-text
bar — and the chips and status words in the rows of the Events page and of a node's
History tab, and measures each as the eye actually gets it: the *computed* ink, the
background composited from every translucent layer above the first opaque one, stacked
opacity folded in — but a head's buttons, which under the library's look show only under
the pointer or the keyboard's focus, are measured as they show, their toolbar's opacity
whole while they are. It prints the WCAG ratio:

```bash
npm i --prefix var/bootstrap bootstrap@5.3.2     # once; var/ is gitignored
uv run python tests/sweep_contrast.py
```

It exits non-zero if a theme misses AA — every theme, cyberpunk too since it
became the library's default on 2026-10-18, where it had been the declared fun
theme, measured and reported and never gated.

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

It found the second one the same way: a button written as a `btn-outline-secondary`,
which Bootstrap paints `#6c757d` on **every** canvas — 3.76:1 on the dark one. A
button wears `btn btn-sm` for the shape and takes its ink from our tokens, which is
the general answer whenever a Bootstrap component's own color has to hold the bar on
six canvases.

A pin's block is walked for the same reason. Its statement and its note sit on the
block's own tint, a pair the tokens can measure; but on the wall, under the pointer, the
block's sentence stands on a wash of its own ink laid over that tint — an inset shadow,
which no computed background reads, so the sweep composites it as a layer of its own —
and the editor's labels, muted help and *Cancel* are Bootstrap's inks on our panel. So
the block's buttons draw from the ink they stand in rather than wearing an outline
variant, and the sweep opens the editor and reads each of those rows where it lands. On *Handled* the same blocks
stand on the page's own canvas, with rows a node's page does not have: the count
above them, which is Bootstrap's muted ink, a node's path, which is a link on the
canvas, the link to its line inside a block's sentence, and the record beneath a
note. The sweep reads those there.

A configured rule's block has no fill of its own (ADR-0137): its words and its marks are
its node's ink on its node's fill, whichever status gives it, where maintenance's stand
on its tint. So the sweep reads one on a red node, one on an amber and one on a green —
the first in a card that is not the pinned one's, by the rule's name — with its dashes
at the 75 % of its ink the sheet draws them at, where maintenance's 65 % fell to 2.86:1
on an amber node in the dark theme.

What handles a part is walked for the same reason
([ADR-0143](adr/0143-a-handled-part-carries-its-jobs-mark-and-a-rail-in-the-color-it-counts-as.md)).
A line's mark and its rail are a status's tint ink on the line's own tint, a pair the
tokens measure; but a line with no tint of its own stands on its box's fill, and a box's
rail on its edge, where the inks fall under the non-text bar on the vivid red and, in
dark, the vivid amber — so the mark there stands on its own tint and the rail on a strip
of the page, and the sweep reads each where it lands, on a build whose lines are partly
seen, a disk seen for itself and a unit a failing gateway shields. A rail is a shadow,
which no computed color reads: its ink is what `--ls-rail` resolves to. A head's mark
and its lit ◇ are links since
[ADR-0147](adr/0147-one-door-opens-a-nodes-notes-tab-in-a-drawer-over-the-wall.md), and in
a box every link takes the box's ink — so they keep the ink of their own tint, which the
sweep found them without on a box of another status: 1.43:1 in the dark theme.

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

**The browser files read the library's look**, as a browser that never chose does:
since 2026-10-18 the cyberpunk theme, in a monospace face, the inspection card off and
a wash under the pointer. A file that tests the card on a pause, the outline under the
pointer, or a premise of the plain theme's proportional face — a name that breaks at
a width, a band whose trail keeps one line, a table whose numbers keep one line — chooses
that look as a viewer does in the settings menu, with the presentation cookie
`tests/browser_looks.py` writes; a premise of the plain face says so where it is chosen,
and what the monospace face does there instead.

**The browser files launch the Chromium `tests/browser_binary.py` finds**, and so do the
tools that drive a browser. An environment that brings its own browsers says where with
`PLAYWRIGHT_BROWSERS_PATH`, as the cloud container does: the link `chromium` there where
it is a file, else the newest revision's `chromium-*/chrome-linux*/chrome` beneath it;
elsewhere the revision the installed Playwright pins, which `playwright install
chromium` fetches. No file names a revision, so an image that brings another one asks
nothing of them.

**A file that measures across a long loop holds the page still for it.** The wall, a
branch's page and the system page swap what their refresh fetches every ten seconds,
and on a loaded machine — the files on four to six workers — ninety widths read twice
each, or a scan of a whole page, outlast that: a read after the swap measures another
element than the one the loop set. Such a test routes the refresh's requests before
the page loads and never answers them — `_held_still` in `tests/test_pin_browser.py`,
a context's route in `tests/test_a11y_browser.py` — which swaps nothing, as an open
editor's pause swaps nothing, and leaves the page's timers running, which a held clock
stops and axe-core needs; and it marks what it measures first, so that a swap that
took it all the same fails by name.

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
it needs a browser download, and a run that collects `tests/` leaves every
`tests/test_*_browser.py` out (`collect_ignore_glob` in `tests/conftest.py`), whatever
the environment holds. Named on the command line a file runs — naming `tests` beside it
leaves it out again — and without Playwright or Chromium the whole module skips.
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
([ADR-0104](adr/0104-a-pin-is-one-block-on-what-it-silences.md), as
[ADR-0147](adr/0147-one-door-opens-a-nodes-notes-tab-in-a-drawer-over-the-wall.md)
amends it): a real server over a node of 80 member lines, and Chromium scrolling to the
60th and pinning it in the drawer its ◇ opens, then editing and clearing it in its block
— the page has to come back with that line in the window, clear of the bar — and opening
an editor on a note, where the cursor has to stand at the note's end, or a new pin's
form in the drawer, its note empty. Over a branch's page and the card a page draws at
depth 0, with the page's clock in the test's hand: the refresh holding off while the
head's editor is open and dropping an answer that was on its way, the editor saying
*updates paused* at the top of its form at once and the stamp as it was, the page
dimming a minute later but for the head or the card being edited, a card's *Edit* and
*Clear* at depth 0 showing under the pointer or the keyboard and always where nothing
hovers, and the editor no wider than a phone. And over the wall with *◇ details* on: a
block one link, its sentence its name and a chevron its end, washing under the pointer
and ringed under the keyboard, opening the drawer at its pin with its editor open, a
link to the tab without script, a tap opening the drawer and no inspection card, and its
sentence ending no line inside the date of its expiry at any width a card comes in; and
a line's ◇ in a branch's head opening the drawer on the line, an edit in its block
coming back to it. Run it when `maintenance-edit.js`, `poll.js`, `drawer.js`,
`inspect.js`, the block's templates or styles, or what `POST /pins/maintenance` returns
to change:

```
uv run pytest tests/test_pin_browser.py
```

`tests/test_actions_browser.py` holds a tap on an action chip to its link
([ADR-0034](adr/0034-template-slots-for-dependent-packages.md)): a real server over a
card with a nested box of member lines, a nested box of prose and a leaf card, each
with a title so its name is one the inspection card answers to, a deployment's chips
beside the library's Copy, and Chromium emulating a phone. One tap on a line's Copy,
on a deployment's chip on a line and on a node's own chip in a box's head and a card's
has to follow the link — to the line's document, or to a new tab at the chip's address
— and raise no card, in both shapes a tap reaches the page in: Chromium's own, which
gives the link the focus first, and one dispatched as a browser that gives it none
sends it, the pointer down and up and then the click. And the phone has to keep every
line's Copy chip and a head's chip in view — shown outright where nothing hovers, inside
the screen, and large enough to tap — on the wall and on a leaf's own page. Run it when
`inspect.js`, the chips' templates, their stylesheet rules or the rows that carry them
in `_status_grid.html` change:

```
uv run pytest tests/test_actions_browser.py
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

`tests/test_about_card_browser.py` holds where a node's About card stands
([ADR-0133](adr/0133-a-node-says-what-it-is-in-a-card-and-at-length-in-a-handbook.md)
decision 1): a real server and Chromium at a desk, a laptop, a window too narrow for
the card beside the facts, and an emulated phone. At a desk and on the laptop the card
has to stand to the right of *Time*, from its top, the facts at their 820 pixels — a
leaf's page and a branch's, after its children; in the narrow window the facts keep
that measure and the card stands, as wide as they are, after the report and before
*Configuration*, as on the phone, which is no wider than its screen; and the root's
card stands at the wall's foot. A status the about names, `{error}:`, has to be drawn
as its sign (decision 5), in the library's theme and the plain one: in one piece, no
taller than its sentence's line, its cue drawn from the shape the page holds, on a
surface of its own, and glowing in cyberpunk alone. A table the about writes, and one a
line writes, has to keep its words whole in their cells and scroll sideways inside what
holds it where it is wider — the card beside *Time*, a phone
([ADR-0018](adr/0018-markdown-rendering.md) decision 14). The card's details (decision
6) have to stand beneath its texts, each key on one line, a long value breaking within
its cell rather than widening the card, at a desk and on the phone. Run it when
`_node_facts.html`, `_about_card.html`, the node-facts, sign or tables' rules of the
stylesheet, `render.sign` or a leaf page's width change:

```
uv run pytest tests/test_about_card_browser.py
```

`tests/test_handbook_browser.py` holds a node's handbook on its page
([ADR-0133](adr/0133-a-node-says-what-it-is-in-a-card-and-at-length-in-a-handbook.md)
decision 3): a real server and Chromium at a desk and on an emulated phone. A link into
a section has to open it in the page, at its anchor and in no tab of its own, with the
heading beneath the sticky bar and not under it, and so does an address that names the
section; on the phone a long line of code, a word longer than the screen and a table
wider than it have to keep to it, the table scrolling sideways inside itself. Run it
when `handbook.html`, the handbook's or the tables' rules of the stylesheet or the
renderer's anchors and link rule change:

```
uv run pytest tests/test_handbook_browser.py
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
wider than its box — in the library's theme and in the plain one, and at 946 in the
plain one alone, where cyberpunk's monospace face scrolls it in its box — a curve's three
numbers have to keep one line from 1500 in both and may wrap below it, a fold's
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
refresh and not swap that answer in; to wait while the drawer is open, as for an open
editor; and, over a server that draws the page with one digest and answers the refresh
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

`tests/test_brand_browser.py` holds the icons the package serves to the drawing they are
rendered from, `src/little_sister/brand/`: it renders every one again through
`tests/render_brand.py` and compares each committed image with its fresh render, pixel
by pixel, allowing what a rasterizer moves on its own from one build to another — so an
icon edited by hand fails, and so does one carrying a digest copied from another image.
Whether each image is the drawing as it is now is the everyday gate's,
`tests/test_brand.py`, which reads the digest every image carries. After changing the
drawing, render the icons again and run it:

```
uv run --group browser python tests/render_brand.py
uv run pytest tests/test_brand_browser.py
```

`tests/test_a11y_browser.py` lets a scanner look at whole pages where the files above
each hold one claim: axe-core, injected by `axe-playwright-python` from the browser
group, runs the rules tagged for WCAG 2.2 at A and AA over the demo's wall, a branch's
page and the kiosk's wall, at 1,280 pixels and on an emulated phone of 390, each in the
library's theme, cyberpunk, and in the plain one the baseline was first taken in. The
demo runs in a child interpreter on a port of its own, 36 seconds into its scenarios and
held there (`LITTLE_SISTER_DEMO_HOLD`), so that every scan reads the same wall.
**Every finding is held to a baseline** in the test — what the scan found on the wall
before the interactive wall was built, each entry a rule and the component it stands on
with the reason it stands, the brand's inks and the head's small words on a vivid fill
among them, and the plain theme's own entries, its pale tints' and its bar's, apart —
so a change that adds a finding fails the day it is made, and an entry that no scan of
its theme finds any more fails too and leaves with the change that mended it. What the
scanner could not decide is not a finding. Run it when a template, a slot's filler or
the stylesheet changes, and at every slice of the interactive wall:

```
uv run --group browser pytest tests/test_a11y_browser.py
```

`tests/test_tree_state_browser.py` holds the tab's map on the page's own clock, as
`test_pin_browser.py` does: a box's *⌄ all N* opened by a click stands through a
refresh and a reload, with the grid held back until it is back and nothing of it in a
cookie; a nested box's too; a new tab starts as
configured; the keyboard's focus returns to the same control of the same node
without a scroll; an open inspection card stays on its node; the system page
refreshes without the map; a map of another version is dropped whole; a browser
that refuses storage keeps the map for the page's life; and on the kiosk a reload
starts as configured, nothing reaches the storage, a pointer that only moves holds
the five minutes off, and five minutes without input bring the first look back with
the address's `depth=`; and a branch's page whose children all left polls on — the
swap lands, saying what stands there, no banner rises, and a reload is the leaf's
page:

```
uv run --group browser pytest tests/test_tree_state_browser.py
```

`tests/test_tree_browser.py` holds the tree's mechanics the same way, the server's
clock held where a test reads the time a render carries: a click opening a chip in
its place and closing it again, a card closing to one line with its counts and no
card moving, a click on a head's title or state closing it and one on its icons not,
a drag that selects the head's text not, a modified click keeping the link, Enter
and Space, a chip opened below the fold brought into view and one in view not moving,
the focus on the other face after each toggle and put back after a swap without a
scroll; a node a click closes or folds at the page's end standing where it stood, in
its `PageEnd` classes — closed by its state and by Space on a card's name, folded by
▤ in rows and packed, by the funnel and by *⌃ less*, and on a phone a card closed by
a tap 150 pixels above the end, its name still under the finger — the room left at
the page's foot giving way as the window scrolls up through it and to a box opened,
✓ or a line a refresh brings, standing through the swap, and gone after a reload,
*Close all* and the kiosk's five minutes; ▤ folding every child and opening them all,
mixed once a click opens one, a
child whose claim would keep it open given an entry of its own, and on a fold every
failing one, so that one made on a node's page holds on the wall; the funnel folding
the healthy and a press taking `show_when_quiet` and a roster's own quiet lines, its
tooltip and *✓ +N ok* counting the fold in force, and standing on a green node as on a
failing one; the band's three buttons, the one in force pressed with the count of the
map's nodes and a `depth=`, *Close all* keeping a node the viewer opened and the
nodes above it while the statuses beneath change, a click on the button in force
dropping what it counts, *Open all* showing the healthy, *As configured* loading the
address without its `depth=`, and with `tree.js` held back the band's buttons in their
place from the first paint, as the script draws them, and a node's page's ◇ in its
head's row — without script, no buttons, and ◇ a link still; the icons' edge and wash
at rest, pressed and mixed, the
band's at rest and in force, and `.is-changed` cleared by
*As configured*; everything through a swap and a reload; a close giving way once the
node was out of failure for ten minutes of the server's clock, a pin beneath it or
not, holding through a shorter recovery, through renders that skip the hold's end and
in a tab that saw no render out of failure, and an open never giving way; a find's
reveal by a fragment naming a line beneath two closed nodes — `beforematch` at both,
the innermost first, both opened with their entries, the level re-formed around the
node and the node itself in place, kept through a swap — a second fragment within two
seconds closing the first reveal's nodes but those above the new match, two seconds
apart or with a click between both standing, and a closed wrapper's `display` kept
against Bootstrap's `[hidden]`; `data-why` for each rule; a swap and a click waking
the three other scripts' observers once each; on the kiosk a tap toggling and no
head carrying icons; a phone's tap toggling without an inspection card; and a node's
page framed, its node open whatever the map holds and a click on its head writing
nothing, its ▤ folding the page's cards and its funnel the healthy ones and its own
lines by the node's own entries, so the wall follows, a leaf's page keeping its fold,
and its head one toolbar. Its
`HeadRow` classes hold the head's row over a wall where every node carries three
actions, under the library's look: the buttons right after the name, on a card and
on a box the head's icons first and ↗ the first of them, then the actions, the title
and the state after them, and a head with no icon — a leaf's own page, the leaf with
a pin of its own — keeping no room for them; what a narrowed
card's row has no room for folding behind ⋯, whose menu lists the folded by their
labels and gives the focus back on Escape; nothing folding where ⋯'s own square and
gap would give the row's overflow back; a lone action keeping its place, the state
taking its line beneath, where that line keeps it in the row, and folding alone, the
state in the row, where it does not; the state dropping beneath where the name would
be cut, the name wrapping last, and `card_status_line: below` giving every
card's state its line and the actions the room back — not where the row's own line
holds it; a name broken onto a second line carrying the state there, at the row's
end, a card's under `below` as a box's, a name of one line never, and a state that
would touch the name's words, or stand nearer them than the toolbar's gap, keeping its
own line; the glyphs
16 pixels in their 24-pixel squares; a card's children 6 pixels below its lines; a
title squeezed below 2.5em hidden at every width a card narrows through; the glyphs
growing with their squares at a 20-pixel font; a long name broken only after its
underscores and copied whole; the row under the pointer outlined in
its own ink at 60 %, 3 pixels out, on a card's head and a box's, from its title, name,
state and cue — not from an icon, the gap between two, an action, ⋯, its menu or a
card's ◇ lit beside its state — and pressed a wash of 12 % reaching 4 pixels past it,
not where a control of its own is pressed, the name not underlined, the pointer's
cursor on the row and
the help cursor on a name whose pause brings the card, both looks from their tokens,
and the look `toggle_hover: wash` setting them, the outline standing under forced
colors; a chip on a card, in a box and failing,
outlined a pixel out with its tint kept and nothing underlined, its focus ring kept
under the pointer, pressed a wash over its tint, from the same tokens; the row read
with nothing squeezed, at every
width of a card and of a box,
down to the half pixel where folding every action still leaves the row short; a box
a click, the map or a reload opens measured at once, and a window that grows giving
the row its room back once the grid's observer has seen the new width; a head's
controls one toolbar walked with the arrow keys from ↗ through the icons to the
actions, its stop kept through a swap; *⌄ all N* beneath clipped lines, whether the server drew it
or the script found a wrapping line; ◇ opening the drawer and the swap waiting for
it; a refresh reading again only the rows the server drew otherwise or that stand at
another width — none on a quiet one, the rest drawn as they were read, their folds, ⋯
and the state beneath or beside — every row read at the width the planner gives its
card, a spanned one's as on the load, and the planner's frame after a swap writing
nothing; the rows this page drew read again when asked for, all of them when the
pointer turns coarse, the toolbar's gap read anew, and when the root's font grows; and
on a phone a card of three actions keeping its name whole, its squares 8
pixels apart with a tap in the gap landing on one of them and none two pixels past
the toolbar's first square or its last — ⋯, the last action or the last icon, and a
page's own first action where it has no icon — a row and a chip under a finger
wearing no outline and their press the wash, and the buttons shown always. Its
`PointerHeadTests`, `PointerNameHeadTests`, `LineHeadTests` and `NameHeadTests` hold
the look `head_buttons`: under `pointer` the buttons shown while the pointer is on the head,
the keyboard's focus is in it or its menu is open — a click's focus leaving none shown —
taking no room, the title right after the name and the buttons over it on the box's
fill, keeping their room where the name breaks, and nothing moving when they show;
under `line` the buttons on a line beneath the row, from under the name, the state at
the right and clear of the title, wrapping beneath where the row has no room for it
and breaking between its parts where even that line has none, nothing folding, and
under `card_status_line: below` a card's state at the right of
the buttons' line, the head no taller; under `name` the state and then the
buttons at the row's end, a state that would touch them keeping its own line; under
`pointer-name` the buttons where `pointer` puts them, ↗ taking no room, and nothing
moving when they show; and under both the latter ↗ out of sight until the
keyboard's Tab from the name lands on it, Enter and Space on the name opening and
closing the node and a pointer's click on it opening the node's page, a closed
card's name opening the card, and the name underlined under the pointer with the
row's wash off it. Its `StateBreakTests` hold a state wider than the line it has to
itself: broken between its parts, right-aligned — the reading beside the word first,
then a card's time apart from its cue and word — and inside a part, the stale mark's
as any other's, only where that part alone is wider than the line, nothing of it out
of its box; the head making room for every line it takes, under
`card_status_line: below` too, and a closed card's state taking those lines in the
head's own flow, under `below` as beside, no room kept from when it was open; and the
room drawn from what was read through a refresh that reads no row. Its
`ChipRunTests` hold
the runs of chips: the runs on either side of an open child lining up, every chip
stretched to its column, nothing cut; a level's width what its widest name and its
largest count need, measured in pixels, and neither a click, a count nor a reload in
another state moving it; a name past the level's bound wrapping inside its column
where its words meet, its row standing taller; counts that do not fit beside a name
beneath it, at the right; the look `wrapped` drawing each chip at its own width; and
without script the server's estimate in characters. Its `HoverCardTests`
hold the card on the page's own clock: on a pause of two thirds of a second on a
chip's name or a head's, and nothing sooner nor over the rest of the row; moving on
the name starting the pause again; no card while a click is under way, from a pause
it ended, or from the hand that clicked moving just after; the keyboard opening it at
once and Escape closing it; `off` keeping it closed and marking no name; a node a run
names after the load having its card after the next swap, and a refresh during the
pause opening it on the name it drew; the help cursor on the names that have one; and
its heading the name as text and a glyph title beside it. Chromium moves nothing in a
page for a pointer moved past the window's edge, so they bring each name into view
first:

```
uv run --group browser pytest tests/test_tree_browser.py
```

`tests/test_boxes_browser.py` holds the look `boxes`
([ADR-0138](adr/0138-a-viewer-may-pack-a-levels-boxes.md)) on the page's own clock the
same way, on a card of six open boxes, the second twenty lines tall: in rows the boxes
after the first row start beneath the tall one and nothing of the packing is drawn;
packed they stand beside it, two boxes of a column the level's gap apart and packing
again moving none, boxes of about one height in the columns rows give them, a level's
first boxes one to a column, a level of boxes alike as deep in each column as rows stand
them in as many columns, and the wall's own cards packed the same way. A run of chips
stands in one column as a box does, where the first of its nodes stood, and keeps its
column through a refresh; a box a click closes leaves its chip where it stood, the chip
at its run's top, and a chip a click opens stands its box where the chip stood, from a
run of two too; a column a click empties stays where it stood and as wide; a run a click
forms is read one column wide before anything reads the page; a level drawn again lays
as many columns as its boxes and runs fill; and a level a click leaves one open box
keeps nothing of the packing. Packed, the plan gives a card of six boxes both tracks of
a wall 1,000 pixels wide where rows' plan gives it one, the wall the lower for it. A
refresh, a click and a box growing of itself keep every box in its column, each packed
before anything reads the page, and the window stands where it stood; a width that
changes a level's columns packs it afresh, a reload too, and one of a single column
leaves nothing of the packing; a load packs by the heights the tab's map leaves,
whatever a frame before the map packed, and the wall is hidden until then, a `tree.js`
that never comes leaving it hidden for a second; the page's order is the source's; and
on a phone neither look moves a box. Five of them run on the browser's own clock, where
what they wait for comes in an animation frame or when the browser says a box changed
size, which a held clock may leave waiting:

```
uv run --group browser pytest tests/test_boxes_browser.py
```

`tests/test_boxes.py`, which every gate runs, holds the server's half without a browser:
the plan each look publishes, and the refresh's fragment carrying the same.

`tests/test_settings_menu_browser.py` holds the settings menu's staying open (ADR-0029):
a click inside it keeps it open, the choice already in force and a heading alike; a
choice brings the page back with the menu open and the focus on it, the look in force
and the tab's entry gone, and the next choice the same way, while a reload no choice
brought opens nothing; *Escape* and a click outside close it; the band's filter switch
leaves it shut; and where the tab's session storage is refused the choice still applies,
the menu shut and no error:

```
uv run --group browser pytest tests/test_settings_menu_browser.py
```

`tests/test_wall_cost_browser.py` takes what the wall costs a browser on the anonymized
tree of Mode 1, in the library's theme — cyberpunk since 2026-10-18, whose monospace
face reads every wall taller than the plain theme's did — today's numbers the baseline
the interactive wall's stages state their growth against: the **screens** the design
round read off its prototype, measured again
on the real wall — a page's height over 900 pixels on a desk and 780 on a phone, the
window as tall — the whole wall at 1,280 and 1,920 pixels and on a phone, a node's pages
at 1,024 as the prototype's boards were, and a team's card and its github box on the
wall at the width the planner gives them, on the tree as recorded and made worse as the
round made it: an outage of every workflow, every leaf failing, a branch of 100
repositories, a band of 300 findings. The **deployed wall** is read beside them — the
tree mounted as the deployment that runs mounts it, one team's five checks as the
wall's cards — on the desk it is mostly looked at on, 2,560 pixels wide with a screen
of 1,300 there, its aws card and its github card on their own, and at 1,920 and 1,280
pixels and on a phone; and so is the **hosts wall** of Mode 1, at the same four widths.
Each is read as an admin, and the walls as a viewer too — the same session, signed
again with `admin` false — ◇ on every open head for both, so that what a team sees and
what is an admin's alone stand side by side. The prototype's reading stands beside each case as what the round
worked from; it copied today's look by hand, drew a card alone at 700 pixels and a
page's facts at a typical size, so a card's and a page's reading is near it, not the
same. And the **swap**: one refresh asked of `poll.js` as a tab coming back asks it,
timed from the fragment's last byte to the second frame after it is in the page, with
the CPU throttled four times — the parse, the observers a swap wakes and the layout,
where stage 2 applies the tab's map. A reading may differ from its baseline by 15 % or
0.3 screens, the wrapping another machine's face gives (below), never a stage's growth,
which raises the number in the file and says so:

```
uv run --group browser pytest tests/test_wall_cost_browser.py
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

**A page is served from `tests/browser_server.py`.** `wsgiref`'s server answers one
request at a time, and the connections that arrive meanwhile wait in its socket's listen
queue, which `socketserver` makes five long. A page's stylesheets and scripts come six at
a time, more than a dozen of them on a node's page, and under coverage the server is
still on the first when the rest arrive. Linux keeps a connection that finds
the queue full waiting until there is room; macOS resets it, and the page loads without
that file — on a Mac, `maintenance-edit.js` failed so with `net::ERR_CONNECTION_RESET`,
and the test waited thirty seconds for the class that script sets, in a different test
each run and never in a sandbox.
`PageServer` is `wsgiref`'s server with the platform's longest queue, and every browser
file serves its pages from it:
`make_server("127.0.0.1", 0, app, server_class=PageServer, handler_class=…)`.

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
uv run python tests/walk_gui.py --look boxes=packed      # a look of the menu besides
```

On every screen it opens the wall and a branch's wall and points at each card head — a
tap on the phone — which raises the inspection card where a node has one, its browser
choosing the card on a pause as a viewer does in the settings menu, since the library's
look keeps it off (`CHOSEN_LOOKS` in the script, to which `--look KEY=VALUE` adds a
look of the menu, as `--look boxes=packed` walks every screen packed); a branch's
page, a leaf's and its History; a subject's branch and node; Events, Handled, both
System views, Links, Copy and About; the Series index with every fold open; and two
Series views, with a pointer at rest on a curve and, with a mouse, a stretch dragged
across it. Once, on the widest screen, it pins the demo's job name that comes and goes
in the drawer its card's ◇ opens, waits until its node has left the tree, and then visits
what a removed node leaves on every screen: its row on Events, its suspended pin on
Handled, the branch it left, its own address, and its check's History and Series.
Last it opens every page of the fixture sheet on the widest screen and on the phone.
A walk takes about eight minutes, most of it the demo's own clock.

**Every step leaves a screenshot and what the browser said** while it was taken: the
console's errors, the Content-Security-Policy reports the page sent, and how far the
layout shifted with no input. **And every step is measured** against a short list of
facts (`FACTS` in the script): a page no wider than its screen, a raised card inside
the screen, the name, the title, the actions, the state and the icons of a head's
row — a card's and a box's — not lying over one another as a reader sees them, no box
of a level — the wall's cards, a card's open boxes — standing over another, and
everything a curve or a sparkline draws inside its plot. Of a head's row a name is
read as its lines rather than its box, since the state may stand on a broken name's
second line; a part the page hides or fades, itself or by a box around it, is none,
as the pointer looks fade a head's whole toolbar until the pointer rests on it; and a
shown toolbar over the title is no mark where `pointer` and `pointer-name` lay it
there on purpose, though over the name or the state it is one under every look. A
fact that does not hold **marks** the step.

**Nothing fails.** A review collects, so the walk always ends with its gallery,
`var/gui-walk/index.html`: each fact with how many steps it marked, the marked steps
first, then every step in the order it was taken; `walk.json` beside it is the same as
data. One thing to know when reading it: a layout shift is counted whatever caused it
— but for a raised card's own move from one node to the next, which a browser counts
and nothing in the layout makes — and the demo's readings change under the walk, so a refresh that swapped in a longer
list marks a step as a real shift does — a mark that comes back at the same step on a
second walk is the one to believe.

**A baseline.** Before the interactive wall's stage 2 the walk was taken twice on
4174324, in the cloud container, and marked the same nine steps both times; its
gallery was kept beside the checkout, git-ignored, until the walks after the wall's
stages 3 and 4 had been read against it. A walk is read against a baseline so:
`walk.json`'s facts and their counts first, then the marked steps, then the same step's
screenshot side by side — a mark the baseline carries is today's, a new one is the
stage's. Two of the
baseline's marks are the walk's own reading of what the page does on purpose or
has always done: the console's 404 on a removed node's own address, which that page
answers (ADR-0116), and a layout shift on the sheet's large walls at 1,440 pixels,
where `dashboard-layout.js` plans the grid again after the first paint. The baseline
is drawn in the plain theme, then called *default*; a walk since 2026-10-18 draws the
library's cyberpunk, whose monospace face sets every name wider, so its screenshots
differ from the baseline's in every face and the facts' counts and the marked steps are
what read across.

**A fact that is fixed moves into a test of Mode 5**, which is where a claim is held;
the walk finds, Mode 5 keeps. `tests/test_walk_gui_browser.py` holds the facts
themselves, each against a page of the test's own that is broken in its way, which it
has to mark, and the same page sound, which it has to pass — a walk that never fails
would otherwise look the same with a fact that measures nothing; it is a browser file,
run where it is named. `tests/test_walk_gui.py` holds what of the walk needs no browser,
and every run collects it: the walk's own end — the server stops, then the demo's
instance, its one save, its lease let go, and the process goes back where it was,
before the directory the demo ran in goes — how a report reads, the gallery, and the
looks its browser chooses. Run both when a fact is added or changed:

```
uv run pytest tests/test_walk_gui_browser.py tests/test_walk_gui.py
```

It walks synthetic shapes. A real estate's are looked at on a deployment, by hand,
beside it.

## Not part of a deployment

All six harnesses are **dev-only**: they live under `tests/`, carry no real
checks, and start no engine except when you run the demo wrapper. Keep them green
with the rest of the gate (`hooks/pre-commit`) and run Mode 5 by hand
when the dashboard layout changes.
