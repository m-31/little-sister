# Changelog

All notable changes to little-sister, newest first. The format follows
[Keep a Changelog](https://keepachangelog.com/); releases are cut with the release
pipeline (see [`docs/create_a_release.md`](docs/create_a_release.md)), which rolls
the **[Unreleased]** notes below into the tagged version. The JSON API
contract versions **separately** — see `docs/api/openapi.yaml` `info.version`.

## [Unreleased]

## [0.2.4] - 2026-08-03

### Fixed

- **A branch whose children are all silenced no longer reads as "nothing here has
  reported yet".** The roll-up skips a pinned child, and a parent with nothing left to
  count fell through to `UNDEFINED` — the idle state — so silencing every host in a
  rack turned the rack card grey and dropped it out of the view as unmonitored, rather
  than blue and accounted for. *We silenced everything under here* and *nothing under
  here has ever reported* are different facts and one of them is an operator's own
  doing. The parent now reads `MAINTENANCE` when a child was skipped because it is
  silenced, and stays `UNDEFINED` when the children have merely not reported.

  This is the edge case ADR-0032's amendment left open, and the model had already
  answered it one level down: a node whose *reasons* are all pinned reads maintenance,
  and its reasons are virtual children of exactly this walk. Real and virtual children
  reading differently in one model was the bug.

- **A silenced node no longer forgets what it is silencing — and clearing a pin puts
  it back at once.** Pinning a node used to *write* `MAINTENANCE` over its status and
  its reason list, so the check's real answer was not hidden but destroyed: while the
  pin was on, the tree could not tell you whether the thing you had silenced was
  healthy or on fire, and every run threw the new reading away. Clearing then had
  nothing to restore, so the node sat blank — no status, no reasons — until the check
  next ran, which on the leaf page (not polled) meant it came back only on a reload.

  A pin is now **recorded, never written**. The node keeps reporting underneath it and
  the maintenance status is derived when the page is built, which is the same move
  per-reason pins already made. Three things follow. A pinned card says
  **`maintenance · error`** and shows the failure text, with a banner above the
  reasons naming who silenced it, until when and why — the banner sits outside the
  reason clamp, so the explanation for the color can never be the line that gets cut.
  Clearing restores the last known state immediately. And a node carrying both its own
  pin and individually pinned lines is finally a state the tree can even reach.

  **A pinned check that dies now escalates.** `_is_stale` exempted every pinned node,
  so a pin meant to quiet a known state silently covered a dead check for as long as
  it lasted. That exemption could not simply be deleted — it was holding up the first
  problem: the stale escalation takes the worst of the node's reading and `WARN`, and
  a node holding a written-in `MAINTENANCE` had no severity to compare, so removing
  the exemption alone crashed the dashboard. Correcting the first made the second a
  two-word deletion. A pinned check that stops running now degrades exactly as any
  other does — never softening a known `ERROR` — while its card still shows blue and
  explains itself. The same fix closes a latent crash for a check that reports
  `MAINTENANCE` on its own.

  For JSON clients: `own_code` and `code` are unchanged in every case, since the
  derivation reproduces what used to be written. A pinned node's `reasons` now carry
  what its check is actually saying instead of a copy of the pin's text, which has
  always also been in `maintenance_details`.

- **A silenced reason was under the accessibility bar in every light theme, and the
  gate could not see it.** The line carried the maintenance ink and an `opacity` of
  0.75, and that dim was the whole defect: the ink is 7.6:1 against the pale card
  fills it was picked for, and a quarter-dim composited it to 4.2 — under AA, on text
  Bootstrap sizes as `small`, so the large-text exemption does not reach it. Two of
  the six themes never declared the token at all and failed identically without ever
  appearing in a search for it.

  Measuring the rest of the surfaces turned up the larger half. That ink was landing
  on **four different backgrounds**: our pale `--ls-tint-*` card fills, our *vivid*
  `--ls-error` / `--ls-maintenance` fills — a node reporting its own problem is not
  drawn dim, so a pinned line on a failing node sat on the saturated fill at
  **2.7:1** — and Bootstrap's `.alert-*` on the leaf page, which is not ours to
  measure at all. So the line now paints its **own** maintenance tint instead of
  inking onto whatever is beneath it: one pair, both tokens ours, 7.1-9.1:1 in every
  theme, whatever it is sitting on. That is what the maintenance pill, the pip and
  the maintenance leaf chip have always done; the silenced reason, its count and the
  suspended-pin notice were the stragglers. The strikethrough goes with it — the
  color is the signal now.

  The gate learned the shape of the miss, which is a different one from the last
  contrast regression. That was a surface nobody had written down, which the browser
  sweep exists to find. This was a **listed ink dimmed by a later declaration in its
  own rule** — the gate already folds alpha for the hover wash, so it knew how; it
  just never looked. It now refuses any rule that sets an `--ls-*` ink and dims it,
  and measures the silenced-reason block as the composite it is, at every opacity
  that reaches its text.

- **A clamped reason no longer breaks a link in half.** Dashboard cards clamp each
  reason to 400 characters *before* rendering it as Markdown, so a cut landing inside
  `[#4821](https://…)` put the raw syntax and half a URL on the card — longer than
  the text it replaced, and unreadable. The clamp now backs up to the start of the
  link it would have split, or keeps the link whole when nothing else would fit: a
  link's source is long and what a reader sees is its label, so keeping it costs
  almost no width and losing it costs the whole reason. Text with no link is
  unchanged.

- **A silenced *reason* now shows up where every other pin does.** Pinning one finding
  of a twenty-finding node worked, and then the pin was visible on exactly one page:
  the node's own. The maintenance index walked node pins only, so an entry pin reached
  neither the status strip's pill, nor the "contains maintenance" pip on the card above
  it, nor `/maintenance`. Two consequences, and the second is the sharp one. An admin
  asking *what is silenced right now?* got an answer that was quietly incomplete — the
  worst kind, because nothing about it looked partial. And a node whose findings were
  **all** pinned went blue on the dashboard, correctly, while the maintenance page
  denied any pin existed there: a suppression that no index claimed, which is precisely
  what a monitor must never do.

  The two surfaces answer different questions, so they now have different shapes. The
  **popover** behind the strip pill summarizes **one row per node** — *3 of 20 reasons*,
  or *all 20 reasons* where nothing is left reporting, which is the row that finally
  explains the blue card — because it is capped, and twenty rows from one node would
  push every other node out of it. **`/maintenance`** lists **one row per pin**, node
  pins and reason pins alike, entries in the check's order under their node's own. It
  gains a **Silenced** column for what a pin covers, kept apart from **Why** it is
  covered: both are called "reason" in the code and they are not the same kind of
  thing, and one heading over both is a table nobody can read. The opaque slug appears
  on neither page.

  An entry row **links to its line**, not just to its page: on a node with 150 findings
  those are very different places to arrive. The page marks the line it was asked for
  and, when the pin's line is no longer being reported — a pin is suspended by absence,
  never deleted by it — says so in words, which is a state that used to be visible
  nowhere at all. The "contains maintenance" pip follows one widened rule: only a
  **node** pin takes a card out of the set, because a node pin cancels its whole
  subtree and an entry pin cancels nothing below it. That matters most where it is
  least visible — a node with everything pinned reads `MAINTENANCE`, which is neither
  warn nor error, so in the dense grid it collapses to a chip that draws no reasons and
  no count, and the pip on the card above is the only thing left pointing at it.

- **A maintenance window can no longer be zero, negative or absurd.** `-1d` and `0`
  were written happily, landed the expiry in the past, and the next sweep — within
  seconds — dropped the pin, taking the reason text and both authorships with it,
  behind a redirect that looked like a success. That is exactly the lost-explanation
  failure the conflict page exists to prevent, arriving through the other door. A
  window is now at least one second and at most a year, and anything outside that is
  **refused**: the form comes back with your words intact and a sentence saying what
  was wrong. Relatedly, `inf`, `1e20` and `99999999d` used to return a 500 — the first
  overflowed inside the duration parser, the other two overflowed the date arithmetic
  — and now land on the same page. Only the deployment's configured default still
  falls back silently, so a `settings.yaml` typo cannot make the form unusable.

- **A blank reason on an edit no longer erases the stored one.** It used to overwrite
  it with the literal `maintenance`, which every surface then renders as "no reason".
  Blank now means "I did not touch this field", so an edit that only moves the window
  keeps the explanation; on a *new* pin, blank still means `maintenance`.

- **`GET /links` no longer 500s on a misspelled `interval:`.** `check: {interval: '6
  hours'}` — a plausible thing to type — took the whole page down: the value is kept as
  raw text and validated nowhere, and the parser raises rather than falling back, which
  is the opposite of what the code beside it promised. It now falls back to the
  documented default with a warning, and so does a zero or negative interval, which
  would otherwise have made every open trigger a probe.

- **One host that never finishes answering no longer freezes reachability until the
  next restart.** `REQUEST_TIMEOUT` bounds a socket *operation*, not a request, so a
  server that dribbles a byte every four seconds never times out — and the pass waiting
  on it could not end, because the thread pool was entered as a context manager and
  leaving one waits for every worker. Since the single pass slot was released only on
  the way out, that one host held it for the life of the process: no open and no *check
  now* could start another pass, and the page went on showing ages that crept upward
  with nothing behind them. A pass now carries a deadline of its own — derived from how
  many targets there are, floored above the *check now* deadline — and at the deadline
  it **gives up on what is still on the wire** rather than waiting: what answered keeps
  its verdict, what started and did not finish is marked *no answer*, and a target the
  pass never reached keeps the verdict and age it already had. A pass that somehow
  outlives even that is superseded by the next one, and each pass carries a generation
  so the superseded one stops writing rather than interleaving its answers with the
  newer pass's.

  What this cannot do is take back a request already sent, so a probe abandoned this way
  goes on holding a thread until the host lets go. Those are counted, and past three of
  them the page stops starting new passes and **says so** — the one condition under
  which the ages beside the entries stop meaning what they say.

- **Every verdict now lands as it arrives, not in the order the probes were started.**
  The sweep collected results with `Executor.map`, which yields strictly in submission
  order, while the comment above it said "as they arrive": the probes did run
  concurrently, but one slow target held every later answer out of the store until it
  finished. Harmless while a pass always completed — and the whole point once a pass may
  be abandoned, since "keep what came back" is what a deadline promises.

- **One malformed link target no longer aborts the whole reachability pass.** A server
  answering something that is not HTTP — a typo'd port, `http://host:22/` — raises
  `http.client.BadStatusLine`, which is neither an `OSError` nor a `ValueError` and so
  escaped the probe unwrapped and killed the sweep. Every other entry was then left
  without an answer, which the trigger read as "never asked", so *every* subsequent
  open started another doomed pass. A garbage answer is now that one target's verdict
  ("no answer") and nothing else's.

- **The dashboard's ~10s refresh no longer throws away what you are typing in the pin
  dialog.** The poll replaces the grid wholesale, so the dialog's anchor was detached
  on every single refresh — not only when the card genuinely went away — and the dialog
  closed, discarding the reason you were mid-sentence in. It now re-anchors to the
  replacement control without touching the fields, and closes only when the node is
  really gone. (Its `set_at` token is deliberately *not* refreshed: quietly re-aiming
  the write at whatever landed in the meantime is the compare-and-set guard defeating
  itself.)

- **The pin dialog's duration field is cleared between cards.** One dialog serves every
  card, and the duration was never reset — so typing `2h` for one card and then opening
  another silently gave the second a two-hour window, and on an edit silently re-timed a
  window you only meant to re-word.

- **A deployment's node action no longer disappears at depth 0.** The single-card view
  rendered the per-reason slot but not the node one, so a configured action vanished at
  one depth setting and its sibling did not.

### Added

- **You can now find out whether something broke while it was silenced.** A pin used
  to stop the node being written at all, so nothing happened underneath it and there
  was no transition to record: an admin who silenced a flapping service for a week and
  came back had no way to learn it had gone red on Tuesday and stayed there. The
  reading survives the pin now, so those transitions exist — and `/events` keeps every
  one of them, **marked** with the rule that held it back. The row keeps the color it
  would have alarmed in, because that is what it would have alarmed as; the chip beside
  the code is what says it did not.

  The marker names the **rule**, not the word "maintenance". Maintenance is the first
  of several policies that withhold a transition — an aggregation clamp, a dependency
  shield, a damping counter — and a boolean would have been four booleans by the third
  one, all spelling the same property. One sentence defines the field and is worth
  holding to: *an unmarked event is one that alarmed; a marked one is one that didn't.*
  So a node whose *check* reported maintenance is not marked (nothing suppressed it, it
  said so itself), a partly pinned node is not marked (its other lines still alarm), and
  an admin's own set, edit or clear is not marked either — that transition **is** the
  change, and it is what everyone sees.

  **`/history` is unchanged, deliberately.** It answers *what did this node show over
  time*, and a check that went red under a pin did not change what the node showed — it
  stayed in maintenance. Counting those would chop one window into a dozen phantom
  `ERROR` periods that no surface ever displayed. The two pages now answer two
  questions instead of one, which is what the marker buys. A long window over a noisy
  check will write rows nobody wants at the top of `/events`; hiding marked ones by
  default is a question about the log as a whole, and it rides with retention rather
  than arriving as a special case for one rule.

- **The three decisions that had grown under one title are three records.** ADR-0004
  answered *how does a parent accumulate*, *what does a failing check become* and
  *what does an administrator's pin do* under the heading of the first — which is how
  its maintenance half sat in contradiction with its own roll-up half for months
  without anyone noticing. It is superseded by **ADR-0039** (roll-up), **ADR-0040**
  (a failing check) and **ADR-0041** (maintenance is a contribution rule, not a
  value), and kept for the history; every citation in the code now points at the piece
  it actually meant. `engine.py` has cited ADR-0004 for "any failure becomes an
  `ERROR`" since before that ADR said anything about failures.

- **The live demo grew into the features it is meant to prove.** `tests/demo_wsgi.py`
  showed the dashboard *move* — poll and swap, an eruption's reflow, staleness,
  roll-up — and nothing since; a feature nobody can click is a feature nobody reviews.
  It now declares **member** reasons, so the per-line pin control can be exercised
  without hand-writing a check, and the two nodes that do it are a matched pair:
  `/security/audit` reads its findings as members from one `entries: true` line and
  demonstrates the *derived* slug promise (its texts never change, only their number,
  so a pin set on finding 7 survives the list swelling to ~150 and back), while a new
  `/ci/reviews` queue demonstrates the *declared* one (every line is re-worded on
  every run and the pull-request keys do not move). `tests/demo_config/` gained a
  `settings.yaml` — the budgeted retry on, so `/system` finally has a retry marker,
  with one node that re-arms its budget and one that spends it — a `nodes.yaml`, so
  the container nodes are labeled instead of bare path segments, and an
  `actions.yaml`; and the wrapper registers a coded slot filler beside the configured
  one, which is the only way to see a provider **decline** one reason line of a node
  it otherwise fills, two fillers landing in one rail, and the `/ext` asset route.
  The maintenance conflict page needed no code, only a recipe, and it is in
  [`docs/testing-the-gui.md`](docs/testing-the-gui.md) Mode 2 with the rest. All
  dev-only: nothing under `tests/` enters the package.

- **A chip on a node, from four lines of YAML — no code at all.** Wanting "open this
  node in our issue tracker" used to mean shipping an importable Python package with a
  template directory and a context provider, to express a URL with a query string. Now
  it is `config/actions.yaml`: `label`, `url`, which `slot` it fills, and optionally an
  `icon` and an `under:` path to aim it at one subtree. The URL is a template over
  `{path}`, `{name}`, `{code}`, `{reason}` and `{reasons}` — on a node action `{reason}`
  is the node's first line, its summary, and `{reasons}` is the whole condition, so an
  issue form gets a title and a body. Every substituted value is percent-encoded, so a
  reason full of ampersands and quotes survives intact and an action can never carry
  markup onto a page; a template naming something we do not provide is refused when the
  file loads, because a button that lies is worse than no button. Roots layer like the
  checks, so a site root adds its actions to a base root's.
  It is not a replacement for writing a filler — a configured action is a link, and
  anything that has to compose something before it posts still wants code. It renders
  *through* the same slot seam, so a configured chip and a coded one sit in one rail in
  one order and `/system` lists both, marked *built-in* or *extension*. See
  [ADR-0038](docs/adr/0038-declarative-action-list.md). An example `config/actions.yaml`
  ships with the library, inert until you uncomment something.

- **A slot filler can ship its own stylesheet and script.** Until now an extension
  could render a link or a form and nothing more — there was no way to serve it a
  `.js`, which is exactly what a node action wants: "file a ticket about this node" has
  a title and a body to compose before it posts. A package now declares what it ships
  with `slots.register_assets(package, "chip.css", "chip.js")` — bare file names inside
  its own `static/` directory, `.css` and `.js` only, the same sandbox an icon pack
  gets.
  **little-sister emits the tags, not the extension**: a `<link>` and a deferred
  `<script>` in our own header, once per page, in registration order, after our
  stylesheet and after Bootstrap. They are served from **our own origin** at
  `/ext/<package>/<member>` and never from a third-party URL — which is also what keeps
  a future `script-src 'self'` able to cover an extension's code without a nonce for
  something we never saw. Each URL carries the file's own content hash, so a changed
  file is a changed URL and the response can be cached hard. Login-gated, and the kiosk
  loads none of it, for the same reason it renders no chips. Worth saying plainly: an
  extension's script runs with the page's full authority, so installing one is trusting
  it. See [ADR-0037](docs/adr/0037-extension-static-assets.md).

- **A deployment's action can now sit on a node, not only on a reason line.** The
  template-slot roster gains a second slot, `node.actions`, in a dashboard card's header
  and beside the status on a leaf's own page. It exists because reasons split into two
  kinds: where a check declares its findings as members, an action is about *one* of
  them and belongs on the line; where the reasons are prose — a failure message and its
  stack trace are one condition in several paragraphs — there is exactly one thing to
  act on and it is the node, and a per-line button there would offer to raise a ticket
  about a stack trace. A filler gets `node` and `surface`, declines what it does not
  want by returning `None` as before, and puts `.node-action` chips in the
  `.node-actions` rail core emits — the same chip shape as a reason action, because an
  action is an action. Nothing changes for an existing filler, and a deployment with no
  extension pays one empty span per card. See
  [ADR-0034](docs/adr/0034-template-slots-for-dependent-packages.md).

- **Silence one finding, not the whole node.** A check that discovers things — security
  findings under a severity band, waiting pull requests under an aspect, jobs under a
  build server — puts many of them into one node's reasons. An operator picks one, opens
  a ticket and starts working; until now the only way to stop it alarming was to pin the
  node, which silenced the other nineteen. A node's reasons are now **addressable**: on
  the leaf detail page an admin gets a *Silence this one* control on each line, with its
  own reason and duration. The rest keep alarming, which is the entire point.
  A silenced line stays **visible** — struck through in the maintenance color, saying who
  silenced it and until when — and the node states how many of its reasons are quiet,
  because the card's reason clamp can push the silenced line below the fold. When every
  one of a node's reasons is silenced it reads `maintenance` and contributes nothing to
  its parent, exactly as a pinned node does. A check that **stops running** still
  escalates through staleness, silenced or not: a suppression must never end up covering
  a dead check.
  For check authors: `CheckResult.reason` now accepts a `{slug: text}` mapping or
  `(slug, text)` pairs as well as a string or a list, and a list of strings can declare
  itself with `entries=True`. **Prose is the default** — a failure message and its stack
  trace are one condition in several paragraphs, not two suppressible things — so no
  existing check changes behavior and nothing moves on any surface until a check opts in.
  An entry a check does not key gets a content-hash slug, so returning a stable string is
  enough to get a durable pin; the pin lives beside the tree rather than in the check's
  output, so the next run cannot destroy it, and a finding that disappears **suspends**
  its pin instead of deleting it. See
  [ADR-0036](docs/adr/0036-addressable-reasons.md).
  The JSON API is **unchanged** in this release: the additive `reasons` array rides the
  client-contract round so there is one `schema_version` bump rather than two.

### Changed

- **`var/maintenance.json` is a clean break.** The file now holds two tables —
  `{"nodes": …, "entries": …}` — because a pin may name one reason of a node as well as
  the node itself. There is **no migration**: a file in the old flat shape is ignored
  with a warning and rewritten on the next save, so any pins in it are lost once. This
  is runtime state the program owns and never hand-authors, and every pin in it is
  bounded by a finite expiry, so a compatibility branch in the read path forever was the
  worse trade. Nothing needs to be done by hand.

- **A maintenance pin can be edited without being cleared first, and two admins can
  no longer overwrite each other in silence.** A pinned node used to offer exactly one
  control — *Clear* — so "one more day" meant clearing and re-setting: the node alarmed
  in the gap, and because a blank reason falls back to the literal `maintenance`, the
  re-set usually threw the explanation away. The **set form is now reachable while
  pinned and prefilled** with the stored reason, beside *Clear*, on both surfaces (the
  node page's maintenance card and the dashboard card's dialog). Duration is
  deliberately not prefilled — blank still means the window configured in
  `settings.yaml`, pinned or not.
  And the write had no precondition at all: it built a fresh entry and overwrote
  whatever was there — reason, expiry and author — with nothing said. Every form now
  carries the entry's `set_at` as a hidden token and the write is a **compare-and-set**;
  when the pin has changed underneath, **nothing is written** and you get a page showing
  *both* reasons, who set the stored one and when, your own words still in the field,
  and one click to take the stored ones instead. *Clear* carries the same token —
  clearing someone else's pin should not be the one write that stays quiet.
  The entry now carries **both dates**: `created_at` / `created_by` join `set_at` /
  `set_by`, which keep meaning the last write, so a pin reads *pinned by Anna three days
  ago, last changed by Ben an hour ago* on the node page and in the `/maintenance` table
  (the popover, having room for one name, shows the last writer); a pin that carries
  neither creation field reads as its own creation, i.e. set once and never edited.
  Editing a pin also **emits an event**, which
  `MAINTENANCE → MAINTENANCE` never used to; a re-submit that changes neither reason nor
  expiry stays silent. See
  [ADR-0014](docs/adr/0014-maintenance-persistence.md).

- **Your deployment's configuration is one directory now — `config/`** — and it is
  layered. `checks/` was accurately named when it held checks; it had come to hold node
  metadata as well, while `config.yaml` and `users.yaml` sat outside it and could not be
  layered at all. All of it moves into **`config/`**, whose entries are *aspects*:
  `config/checks/`, `config/nodes.yaml`, `config/settings.yaml` (what `config.yaml` was)
  and `config/users.yaml`. **`LITTLE_SISTER_CONFIG_DIR` replaces
  `LITTLE_SISTER_CHECKS_DIR`** and stays a path-list, so `base:sites/alpha` now composes
  *every* aspect and not just the checks — each with the combining rule that suits it:
  checks union (overlapping ownership still a hard error), settings shallow-merged per
  key with the later root winning, node metadata later-root-wins per field, and the user
  list deliberately **not** merged — the first root declaring it wins whole, and a second
  is named in a warning. `LITTLE_SISTER_CONFIG` and `LITTLE_SISTER_USERS` keep working as
  single-file overrides that bypass layering entirely.
  An aspect is a file where one file can hold it and a directory where it cannot;
  `checks` is always a directory, because its unit of data *is* the file. Both forms at
  once, or an aspect in a form it does not have, is an error rather than a precedence
  rule; an unrecognized `*.yaml` or directory warns and is ignored, while a `README.md`,
  a dotfile or an editor's `.bak` passes in silence.
  **This is a clean break: there is no compatibility shim, and `checks/` is never
  consulted.** Every deployment does the move once. See
  [ADR-0031](docs/adr/0031-deployment-config-directory.md).

- **A misconfigured instance refuses to start instead of serving a green page** — no
  configuration directory, a root named in `LITTLE_SISTER_CONFIG_DIR` that does not
  exist, or no `checks/` directory in *any* root now stops the process, each naming the
  resolved path it looked at; when the old layout is still in the working directory, the
  message names the moves. A missing checks directory used to be survivable, which after
  this change would have let an unmigrated deployment come up looking alive while
  watching nothing.
  The one survivable case stays survivable and gets **louder**: a `config/checks/` that
  exists but holds **no checks** — a fresh install, a deployment mid-bring-up — starts,
  warns with the directories it searched, and carries that same sentence on the
  **heartbeat at WARN**, so the dashboard says it too and not only the log. With zero
  checks the tree is *only* the heartbeat, so an OK there would have rolled up to an
  all-green root while nothing at all was being watched.

- **The README opens with the name, not with a feature sentence** — a reader arriving at
  the repository was met by "a web application that shows the status of various systems"
  and left to guess what the name was doing there. It now leads with the mark, the
  lowercase wordmark and the tagline, and then the introduction in her own voice — the
  same telling a running instance gives on `/about`, so the repository and the product
  say one thing instead of two. The install guide follows it, unchanged.

- **The tab knows whose it is** — every page's title now reads *page* · **little sister**,
  taking the name from the one place it is written, so a browser full of tabs says which
  of them is the monitoring and which page of it. The page comes first, both because a
  narrow tab truncates from the right and because the poller prefixes "(stale) " to
  whatever the title says. A **detail page names its node** rather than its section, so
  three leaf tabs open at once are tellable apart. `/copy` had been titling itself "Text"
  while its route, its nav entry and its rail tooltip all said "Copy"; the tab now says
  what you clicked.
  The **`favicon.ico`** shipped with the brand assets is finally linked, too — it had
  been served only to whatever asked for it by name at the site root. With it, every
  icon the package ships is actually referenced by something.

### Fixed

- **The edge between a culprit and a parent of its own status is visible again** — a
  nested box is drawn with a translucent edge, which is the *only* thing separating it
  from a parent of the same status. That edge was a literal white, from when every vivid
  fill carried white text; on the yellower warn surface it had all but disappeared, and
  it would have gone the same way on the error red once that took a dark ink too. It is
  now mixed from `currentColor`, so it follows whatever ink its surface ended up with —
  a dark hairline on warn and error, and, measured against the old value, **not one
  pixel different** on maintenance and undefined, whose ink is still white. A theme's
  inks now re-ink their own edges.

- **The detail page's History button rejoins the palette** — it was Bootstrap's `btn-info`
  cyan, the one color on that page that belonged to no theme and followed none of them.
  It is now secondary, like the maintenance buttons beneath it.

### Security

- **A return path that a browser would rewrite is refused** — the settings menu posts a
  `next` field saying which page to come back to, and it was checked for a leading `/`
  and a leading `//`. That misses characters the browser resolves *differently from the
  check*: a backslash is normalized to `/`, and tab, CR and LF are stripped outright, so
  `/\host` and `/<tab>/host` both arrive as the scheme-relative `//host` the check
  exists to reject. Any `next` carrying one of those is now refused rather than
  sanitized — a legitimate return path never contains them. Exposure was low (the form
  is POST-only behind a `SameSite=Lax` session), but the promise the code made was not
  true, and now it is.

### Added

- **A deployment can put its own interaction on the page — template slots.** Some
  clicks belong to one company and to no library: on a failing leaf, raise a ticket in
  the house issue tracker, pre-filled from that node and that reason line. little-sister
  now declares **named slots** — a place in its templates plus the exact context handed
  over there — and a dependent package fills one with **a template of its own** and an
  optional **context provider**, registered in the same import-before-app slot check
  types and icon packs already use. Data is computed in Python, HTML is authored in
  Jinja and rendered by little-sister's environment, so autoescaping still owns the
  untrusted halves of the context; a provider returning `None` means *nothing here*,
  which is how the filler — not the core template — decides where its action applies.
  Extension templates resolve only as `ext/<package>/<name>`, behind our own loader, so
  a registration can **add** to a place and never **replace** a template; several
  packages may fill one slot and all of them render. A broken provider or template is
  logged and contributes nothing rather than taking the page down. The first slot is
  **`reason.actions`**, beside every rendered reason line on the dashboard and on the
  leaf detail page, with the node, the *unshortened* reason, its index and which
  surface it is on; little-sister owns the affordance frame so two extensions look like
  one product, the kiosk renders no slot, and `/system` lists what registered. The JSON
  API is untouched — a slot is presentation. Extension `.js` / `.css` files are
  deliberately **not** part of this: a filler can render a link or a form, which is
  what a pre-filled issue URL needs. See
  [ADR-0034](docs/adr/0034-template-slots-for-dependent-packages.md).

- **An extension's configuration lives in `config/` like everything else.**
  `config_dir.register_aspect(name, …)` lets a dependent package declare a
  `config/<name>.yaml` of its own, so its operator-editable parameters get the same
  shape enforcement, the same `LITTLE_SISTER_CONFIG_DIR` layering and the same
  first-root-wins helper the built-in aspects get — instead of earning the "not a known
  configuration aspect" warning on every start, which is what would have trained
  everyone to ignore the one warning that catches a real typo. The library's own
  aspects are the floor and cannot be redefined; a bad registration is a warning and a
  skip, never a stopped monitor. This is the registry seam ADR-0031's own table note
  predicted. See [ADR-0035](docs/adr/0035-registering-a-config-aspect.md).

- **Pin a whole subtree from the dashboard** — maintenance finally has a surface for
  the container case the model always supported: every card head grows
  an admin-only **pin control** (hover-revealed; a link to the node's page without
  JavaScript) that opens a small dialog — reason, duration, and a plain sentence
  saying exactly what the pin silences — and each branch page carries the same
  **maintenance card** the leaf page always had, which is also where a pin *on that
  node* is finally visible. "The server goes down tonight" is one click on the
  server's card, not one pin per check beneath it. The kiosk layout stays
  control-free, and the overview root deliberately gets no form — silencing
  *everything* stays a curl away, not a click.

- **A faster second look on failure**
  ([ADR-0033](docs/adr/0033-budgeted-failure-retry.md)) — while a check's last
  result is not OK it can be rechecked at a **retry interval** instead of its
  frequency, at most `retry_attempts` times per failure episode, then back to
  normal cadence until it recovers. Off by default: `settings.yaml`
  `retry_interval` / `retry_attempts`, overridable per check (`retry_interval: 0`
  switches one check off). Staleness keeps judging by the nominal frequency, and
  the `/system` page marks a retry slot (`· retry 1/2`). A five-minute check that
  fails no longer needs fifteen minutes to be believed three times.

- **`/links` is a page now, not a placeholder** — the shared toolbox around a
  failure: the two or three dashboards and tools you want *while something is on
  fire*, without hunting through a wiki. Your groups flow into columns in the order
  you wrote them, each entry a mark and a title, with an optional line of Markdown
  under it. A long title wraps under the text, not back under the icon. An icon that
  ships a light/dark pair swaps with the theme; anything else — one file, a site's
  own favicon — sits on a chip that keeps it legible whichever theme you are on; and
  an icon that fails to load is replaced by a neutral glyph, so the page never shows
  a broken-image square. Problems in your links file are shown **on the page**,
  because the person who maintains it is the person looking at it. An empty
  deployment gets a page that says where the file goes rather than a blank one —
  and names every icon it can already write, each drawn on both the light and the
  dark background it ships for, so picking one is reading rather than guessing.
  And once a toolbox grows past a screenful, **typing is how you navigate it**: the
  filter box is focused the moment the page opens, narrows as you type with no round
  trip, and matches an entry's title **and its group's** — so typing a category name
  pulls up that whole category. Every word you type narrows further, in any order;
  `Esc` clears. Your order is never re-sorted, filtered or not.

- **`/about` is one hero now, and the page itself is watching** — the identity
  used to be told three times over: the bar, a block of its own, and a scrolling
  gimmick underneath the story. It is told **once**. The gaze stays where it was
  and the things she watches now orbit *behind the eyes*, on two faint rings, on
  the page's own canvas — no panel, no black box, and wider than the reading
  column, because the terms are the page's air and the paragraphs are its
  content. The page centres itself in the window rather than piling its empty
  space underneath.
  Underneath, she says a line at a time: a couple of the ways systems go wrong,
  one longer observation, then nine short lines that end on the promise the page
  exists to make — and then it stops, so the story begins on a quiet page.
  **Colour means something here.** Green is *seen*: it is spent only on the term
  the eyes are on — and on the phrase in the paragraph that names it, so
  *my eyes stay on the things you care about* lights up as it says it. Pink is
  her, and nothing else takes it. Everything at rest is muted, and monospace is
  kept for the machine's own words. There is far more text than one visit shows,
  drawn fresh each time, so the second visit reads differently. All of it stops
  for `prefers-reduced-motion`: the rings hold still, nothing is marked as seen,
  and the ending shows its last line alone.

- **A link that has rotted says so, where you can fix it** — the `check:` block in
  your links file is acted on now. **Opening `/links` is what starts a pass**, and
  only when the newest answer is older than the configured `interval:` (`6h` by
  default): the page probes where it is read, rather than on a clock that runs
  whether or not anybody is looking. The open itself **never waits** — the page
  renders from what is already in memory, each verdict carrying its own age, and the
  answers one open triggers land on the next. An entry opts in with `check: true`,
  and a failure is drawn under its title (*HTTP 404 · checked > 3h ago*); a **remote**
  icon that stopped answering joins the problems block above, named by the mark it
  draws. Only `404`, `410`, a name that does not resolve and a refused port count as
  **gone**: an auth wall (`401` / `403`) is alive, and a timeout or a `500` reads as
  *no answer* rather than as an accusation about your entry. A healthy row is left
  undecorated, and one line beside the filter says how fresh the answers are — with a
  green tick when **every** answer came back alive, so a page showing no failures is
  never confused with a page nothing has asked about. That age is a **floor**, not a
  claim: the page does not poll, so it says *checked > 3h ago* rather than a number
  that quietly rots while the tab sits open (under a minute it names the clock time
  instead).
  None of it reaches the status tree: a moved wiki page must not turn the dashboard
  amber for everyone. See [ADR-0030](docs/adr/0030-curated-links.md).

- **And a *check now* button, for the moment you have just fixed a URL** — the time
  gate is exactly wrong there, so this one ignores it and **waits for its answers**
  before it hands you the page back. It is a plain form button (no JavaScript) in the
  filter row, at the far end from the search box, and **every logged-in viewer** may
  press it — whoever maintains the links file is not necessarily an admin. A press
  that lands while a pass is running **joins** it rather than starting a second, so
  ten readers cost one sweep; a press within fifteen seconds of the last one changes
  nothing, which is the whole of the abuse story for the only control here that
  spends outbound requests on purpose. It waits ten seconds at most: anything slower
  keeps its previous verdict and age while the pass finishes in the background, and
  the page says a pass is still going so you know a reload will show the rest.

- **Your deployment's curated links now have a file** — `config/links.yaml` (or
  `config/links/links.yaml`, once you ship icon files of your own) holds the shared
  toolbox that `/links` shows: one flat level of groups, each an ordered list of
  entries with a title, a URL, an icon **name**, and an optional one-line note. Beside
  them an `icons:` map names your own marks — a single file, an `on_light` / `on_dark`
  pair named for the background it goes on, or `none` to suppress a mark — and a
  `check:` block sets how reachability is probed. It is a configuration **aspect**, so
  it layers like the rest: groups with the same title **merge and concatenate**, base
  root first, so a site root adds entries to a group the shared base declares, while an
  icon name resolves per name, a later root replacing that one entry whole.
  **Your order is never sorted** — an entry put first stays first. A structural mistake
  (an unusable URL scheme, a misspelled key, an icon file that is not there, a title
  used twice) is reported and skipped rather than fatal: a typo in your links cannot
  take the monitor down. And the file is **re-read when it changes**, so fixing a URL
  costs no restart — which matters while status history lives only in memory. See
  [ADR-0030](docs/adr/0030-curated-links.md).

- **Seventeen link icons ship with it, and cost you no configuration** — `grafana`,
  `prometheus`, `jenkins`, `github`, `gitlab`, `kibana`, `elastic`, `jira`,
  `confluence`, `keycloak`, `docker`, `kubernetes`, `argo`, `sonar`, `nexus`,
  `pagerduty` and `aws` resolve out of the box, from our own origin, with **no outbound
  request**. They are glyphs **drawn for little-sister** — a cloud for `aws`, a git
  graph for `github` — not the vendors' marks, so nothing here depends on a logo we
  would have to be licensed to redistribute. Each ships as a light/dark pair, so it
  stays legible across the theme roster. Want the real mark instead? One line in your
  own `icons:` map replaces it, and `aws: none` switches a built-in off entirely.
  **Your own marks need no configuration either:** drop `firewall.png` into
  `config/links/icons/` and write `icon: firewall` — the file *is* the name, and
  `firewall-on-light.png` / `firewall-on-dark.png` give it a light/dark pair the same
  way ours are named. The `icons:` map is still there for what a file cannot say — a
  remote URL, or `none` — and wins where both name the same mark.
  A **package you install can bring a whole pack** — `icons.register_pack()` in the
  same slot you already register check types — so a house library of company-internal
  marks reaches every deployment that installs it. Overrides apply **per name**: a pack
  that defines one icon leaves the rest standing, and when two packs claim a name the
  log says which won and which lost.

- **`/about` — the thing watching your systems introduces itself** — the gaze at full
  size, the wordmark and tagline, the version of the instance you are actually looking
  at, why it is called what it is, and a link to the repository. Login-required like
  every other surface: it is not a public shopfront, and naming a running instance's
  version is not something to hand to whoever asks. It is entered from the **rail's
  foot** — below the spacer, apart from the sections, because it is not a place you go
  to work — and from a small trailing entry in the top bar.
  It is also the **one place motion is allowed**. The dashboard is deliberately still,
  because anything moving there competes with the single signal that should be moving;
  so the gaze blinks here, and a retro scroller runs here, and the grid does neither.
  Both stop dead for a visitor whose system asks for reduced motion — measured, not
  assumed: the scroller travels 87px in two and a half seconds normally, and exactly
  none under `prefers-reduced-motion: reduce`. The scroller is marked decorative, so a
  screen reader is spared it, and there is room in that corner for a small easter egg
  that ships in its own round.

### Changed

- **A kiosk layout, for the screen on the wall** — the third layout, and the first one
  meant for nobody in particular: a **single slim line** — the brand sentence, the time
  the data is from, and the way out — and then the status strip and the grid, unchanged.
  No bar, no rail, no filters, no user chrome. Everything that exists to be clicked is
  gone, because at a wall display nobody is standing there to click it, and what is left
  is what a passer-by can read from across the room.
  **Exit is not a mode switch.** It writes the default layout back to the one
  presentation cookie and goes home, so leaving a kiosk is the same act as choosing a
  layout from the settings menu, through the same route and the same validation
  ([ADR-0029](docs/adr/0029-per-user-presentation-preferences.md)). The kiosk reaches
  every page rather than just the dashboard, so that exit is never out of reach — pick
  it while reading the events log and there is still a way back.
  A kiosk that has stopped hearing from the server **says so, loudly**: the freshness
  stamp keeps its identity, so the sustained-outage escalation behaves exactly as it
  does on the dashboard — quiet for the first few missed polls, then a banner above the
  grid, the frozen content dimmed, the line in red and the tab title prefixed
  ([ADR-0005](docs/adr/0005-dashboard-freshness-and-self-monitoring.md)). That is the
  whole point of the mode: a frozen wall display that still looks alive is worse than a
  blank one. With the kiosk built, the settings menu now offers all three layouts.

- **How the surface looks is now the viewer's choice** — theme and layout were the
  deployment's, fixed for everyone. A **settings menu** on the user's name (radio
  circles, GitHub-style) offers a **theme** — auto, following the OS, plus default,
  vivid, pastel, dark and cyberpunk — and a **layout** — the left rail or the top bar,
  with kiosk shown but not yet choosable. **Logout moves inside it**, so the bar loses
  its red button and keeps only brand and user, and a grayed *settings…* reserves the
  per-user overrides of `config.yaml` that need a durable store.
  The choice lives in **one long-lived cookie per browser** and is read **server-side**
  onto `<body>`, so a page renders in the chosen scheme instead of switching into it
  after load — no flash on any navigation. It is presentation only: nothing in it
  changes what the surface *says*, there is no server state to migrate, the look
  survives a logout (the login page wears it too), and every failure — no cookie, an
  unparsable one, a retired or hand-typed value — falls back to the defaults key by key,
  because a preference must never be able to break a page
  ([ADR-0029](docs/adr/0029-per-user-presentation-preferences.md)).
  A theme is now an **override of the design tokens, never a fork of the rules**
  ([ADR-0028](docs/adr/0028-design-tokens-and-themes.md)); dark-canvas themes also hand
  Bootstrap its own dark chrome, and `auto` is resolved by three inline lines before
  first paint, since only the browser knows what the OS wants.
  Every status signal was then re-measured **in every theme by computed color, not by
  class presence** — and it found two real defects. The dark theme's warn box had light
  ink on amber at **2.75:1**, the same flaw the token slice fixed for the light themes,
  so the surface keeps its color and the ink goes dark. And **white on the error red
  measured 3.16:1 in every theme** — shipped long before any of this — so the error
  surface now takes a dark ink too, at 5.78:1, exactly as warn did. Pastel's accent
  moved a shade deeper for the same reason: at 2.49:1 the wordmark was not readable.
  Two exceptions are recorded rather than "fixed": the **quiet OK**, which recedes on
  purpose and carries its meaning in a shape cue, and the **wordmark**, which is brand
  rather than status and is large text.

- **The sections move into a rail, and each page's header becomes one band** — the
  sections used to share the top bar with the brand, the user and a logout button, and
  every page opened with a title row, a loose about paragraph and a freshness caption
  stacked loosely down the page. The default layout is now a **left rail collapsed to
  icons**, each with its name as a tooltip and a burger that swaps in the labels; the
  bar keeps brand and user. The per-page block becomes one aligned **band** —
  breadcrumb/title on the left, the freshness line and the filters gathered to the
  right, the node's about beneath, a single rule under all of it — and the detail page
  gets the same band without the parts it has no business showing, since it is not
  polled and has nothing to filter.
  The **freshness line stops being chrome**. It is the promise that the page dates its
  own data ([ADR-0005](docs/adr/0005-dashboard-freshness-and-self-monitoring.md)), so it reads as a
  measurement: tabular figures, so the digits do not dance on each poll, and a rule
  marking it off from the controls it is not one of. The ~10s poll itself is untouched —
  the stamp keeps its id, its server-seeded `data-rendered-at` and the class the poller
  swaps for the red one, and it stays outside `#status-grid`, so the fragment swap, the
  sustained-outage banner and its insertion point all behave exactly as before.
  Both layouts ship from **one markup**: `body[data-ls-layout]` decides whether the
  sections are shown in the rail or in the bar, and they are written once either way, so
  adding a section reaches both. The previous top-bar arrangement is therefore still
  here as the other value of that attribute — a later slice turns it into a per-user
  choice, and nothing else has to move for that. It does gain one fix on the way: the
  bar no longer sits in a centered, max-width container over full-width page content,
  which had left the brand floating inboard of everything below it. Both layouts now run
  the bar the full width on the same gutter the pages use, so under the top bar the
  brand lines up with the content beneath it. The rail's expanded state is
  deliberately **not** remembered: collapsed is the layout's default and the burger is a
  peek at the labels, not a setting. Because the pages are still standalone documents,
  the shell is opened by `_header.html` and closed by a one-line `_page_end.html` that
  each page carries; a real base layout stays paired with the web-customization phase.

- **little sister has a face** — the web surface shipped a placeholder tab-icon set and
  a bar that read "Overview", naming the page rather than the product. The bar now reads
  the whole sentence — the **mark**, the lowercase **wordmark**, and a muted italic
  «*is watching for you.*» — and it is the way home; "Overview" is gone. The mark is one
  off-center eye, mirrored so the lashes point left and the invisible nose sits right,
  and it **winks** when you point at the brand: two SVG groups swap, so nothing is
  fetched and no layout property animates. The **login page** gets the full
  introduction instead — the gaze, both eyes blinking together, above the wordmark and
  the tagline — while the form beneath it is untouched and stays the default provider's.
  Motion is confined to those two gestures, the dashboard itself has none, and both stop
  entirely for a visitor whose system asks for reduced motion.
  The tab icons are the real set now, including a **`favicon.svg` that re-inks itself
  for a dark tab strip**, and `site.webmanifest` finally carries a name instead of two
  empty strings. The brand name is written in exactly **one template place**
  (`_brand.html`, defaulting to "little sister") — the seam the later web-customization
  phase takes over — and the mark's inks are `--ls-*` tokens, so a theme can re-ink the
  eye without forking the drawing. Internally the `.text-pink` helper, which had held a
  literal `pink` since the beginning, becomes `.ls-accent` and takes the brand's deep
  rose; the user's name in the bar wears it too.

- **The web surface paints from `--ls-*` design tokens** — every color `overview.css`
  used was a literal, so a second scheme (a dark mode, a deployment's branding) meant
  forking the rules rather than restating the palette. The stylesheet now names its
  palette once on `:root` and paints only from it, in the model the surfaces already
  used: per status a **vivid** fill — a node reporting its own problem, the culprit —
  and a **pale tint** — healthy, or a status only *derived* from a visible child — each
  with the ink that reads on it. Status borders are mixed from that ink, so a scheme
  that moves an ink moves its edges with it, and the events / history row tints keep
  sharing the dimmed boxes' palette by construction rather than by coincidence.
  One intended visible change rides along: the **vivid warn surface** moves from
  `#e0a836` to `#efc93f` and its text from white to `#2f2405`. White measured about
  2:1 on the old amber and worse on the yellower fill; the dark ink holds about 8.6:1.
  The pale warn tint `#fcf3d6` and its `#6d5012` ink are deliberately untouched, so a
  warn *status word* keeps the contrast it always had — status text holds AA in every
  light scheme, and where a picked color and that bar collide, the bar wins. Nothing
  else moved: every affected selector was rendered under both stylesheets, and outside
  the vivid-warn surfaces the two images differ by zero pixels. Groundwork for the
  theme roster and for deployment-side theming; the ADR lands with the themes.

- **A node's `timestamp` is `null` until a check writes it** — every node used to be
  stamped when the tree created it, so a container above the checks, and the root above
  all of them, served the **process start time** as its "observation" for as long as the
  process lived: `GET /status` returned a root `timestamp` equal to boot time, and a
  client's data-age line dutifully showed a days-old instant as if it were current. A
  timestamp now answers one question — *when did the check behind this node run?* — and
  exists only where that has exactly one answer
  ([ADR-0027](docs/adr/0027-observation-timestamp-semantics.md)): a node a check writes
  carries its own last write, and an ancestor covering exactly **one** check inherits
  that check's run time, so a single-check deployment still reports it all the way up to
  the root. Above two or more checks it is `null`, because any single value would
  attribute one check's run time to another check's data. Observation times are never
  aggregated — no min or max; `stale` stays the freshness signal, normalized per check
  frequency, and it still rolls up. Dashboard cards now show the time where it exists,
  and a leaf's detail page no longer invents an instant for a node nothing has observed.
  **For JSON clients:** `timestamp` is nullable in the contract
  (`docs/api/openapi.yaml` `info.version` 1.2.0) and is `null` on the root of any
  deployment with more than one check — a client that decodes it non-optionally must be
  updated together with this library. `schema_version` stays **1**; the formal bump is
  consolidated into a later, client-facing enrichment of the contract.

- **A check's exception message is escaped before it reaches the dashboard** — the
  engine folded `check error: {error}` into the reason raw, so Markdown in an exception
  message (an API error body, a captured line, a path) rendered as formatting or a
  link. Now escaped with `plain()`, like every other folded-in text (ADR-0018).

- **`plain()` and `code()` accept any object** — a value read out of an untyped
  payload (a JSON number, a `Path`, an exception) is stringified and *then* escaped,
  instead of raising `AttributeError`. `code()` in particular used to scan the
  argument itself for backticks, so a non-string iterable produced a fence that could
  be broken out of by its own content. The boundary helpers (`plain`, `code`,
  `parse_duration`, `coerce_code`) now take `object` rather than `Any`, which keeps
  `mypy --strict` checking their bodies.

- **A secret reference always carries a scheme now** — an environment variable is
  `env://GITHUB_TOKEN`, not a bare `GITHUB_TOKEN`
  ([ADR-0023](docs/adr/0023-secret-references.md), 2026-07-27 update). **Breaking**
  for any config that used a bare name: prefix it with `env://`. The point is that a
  bare name and a pasted credential are the same shape, so a config holding the
  secret itself used to be looked up as a variable name, fail, and print that secret
  into the check's visible ERROR reason; without the bare form it is a malformed
  reference, rejected at load with a message that does not quote it. No built-in
  check type takes a credential, so nothing in the library changes behavior.

### Added

- **A failing check shows its stack trace on the node** — the innermost 5 frames as
  a fenced `code()` block beside `check error: <message>`, chained causes included, so
  an operator on a deployment whose log is awkward to reach can diagnose from the
  dashboard. `config.yaml`'s **`stacktrace: false`** turns it off. Default **on**.

- **`little_sister.values` — typed reads out of a decoded YAML/JSON bag**
  ([ADR-0026](docs/adr/0026-reading-values-from-decoded-bags.md)).
  `values.text` / `number` / `real` / `flag` / `rows` take a bag plus a path of keys
  and always return the declared type, so a config or payload value is narrowed where
  `Any` enters rather than at the last helper before rendering. An absent value yields
  the default, `required=True` makes absence a `CheckError`, and a present-but-uncoercible
  value always raises instead of falling back. Public API for deployment repos writing
  their own check types. `CheckError` now lives in `little_sister.errors` and is
  re-exported from `little_sister.checks.base`, so existing imports are unaffected.

- **A check names its credentials in a `secrets:` block** —
  `secrets: {token: env://GITHUB_TOKEN}`, parsed by
  `little_sister.checks.base.parse_secret_refs`, with every declared name required
  and an unrecognized key rejected as a typo. A check type therefore no longer bakes
  in *which* secret it uses, so a deployment can run the same type several times —
  one GitHub check per team, each with its own token
  ([ADR-0023](docs/adr/0023-secret-references.md)).

- **A check's built-in subnode labels can be extended, not just replaced.** A check type
  that ships default `title` / `about` text for the subnodes it emits (`host-metrics`, and
  any deployment check type) resolves each label through
  `little_sister.checks.metadata.resolve_text`: the config's `subnodes:` value when
  present, the default otherwise — and a config value that contains `{default}` now
  splices the built-in text in at that point, so a deployment can annotate a label instead
  of restating it ([ADR-0025](docs/adr/0025-check-provided-subnode-metadata.md) §5). This
  matters most when one check type runs several times in a deployment — one per team —
  which would otherwise copy the same paragraphs into every instance's config.

### Fixed

- **`./start.sh` no longer reports success when the app failed to start.** It waited
  for the bind port to be listening, but the gunicorn master binds *before* it forks
  the worker that imports the app — so a worker dying on an import error left the
  script announcing "is up" a second or two before gunicorn shut itself down.
  Readiness is now a real HTTP request to `/login` (override with
  `LITTLE_SISTER_PROBE_PATH`), which only a booted worker can answer, and a worker
  that cannot boot at all is reported immediately with the log tail instead of after
  the start timeout. The run scripts now need `curl` alongside `lsof`.
- **`./start.sh` also fails when the app comes up without its engine.** A broken check
  config does not stop the app — the engine stays unstarted and the dashboard shows an
  "Engine not started" banner rather than an unexplained empty tree — so the server
  answers requests while monitoring nothing, and the script used to call that a
  successful start. It now reports the engine's own message and exits non-zero,
  leaving the process running so the banner stays readable.

## [0.2.3] - 2026-07-26

### Added

- **Checks can label the subnodes they emit**: a branch check's `CheckResult` now
  carries optional `about` / `title` for each child, so a reusable check type ships the
  **subject metadata for its aspects once** instead of every deployment copy-pasting it
  into `nodes.yaml`
  ([ADR-0025](docs/adr/0025-check-provided-subnode-metadata.md)). The labels are ignored
  on the check's root (its own keep their `nodes.yaml` / inline sources) and **fill an
  empty node field only** — a `nodes.yaml` declaration still wins, per field, and a
  label freezes at its first fill (text that changes each run belongs in `reason`).
  `host-metrics` adopts it, shipping a per-aspect `about` for
  `ssh` / `disk` / `memory` / `cpu` / `load` — what each measures and how it grades, the
  thresholds staying in each leaf's config. No web or JSON-API change (`about` / `title`
  were already node fields).
- **Author subnode labels in a check's config**: a branch check can read a `subnodes:`
  block — `name → {title, about}` — from its own YAML, beside the root's inline
  `about:` / `title:`, so per-aspect display text lives *with the check* instead of being
  copy-pasted per node into `nodes.yaml`. The new `little_sister.checks.metadata` helper
  reads it (`parse_subnodes`, plus `expand_tokens` for `{token}` placeholders a label
  reuses); `host-metrics` layers a config `subnodes:` override on its built-in defaults,
  and a deployment's own branch checks can keep their labels wholly in config
  ([ADR-0025](docs/adr/0025-check-provided-subnode-metadata.md)).
- **Dashboard reason overflow, configurable and foldable**: a card clamps its
  reasons to a **line budget** — `config.yaml`'s `reason_cap` (default 6), plumbed to
  both the full page and the ~10s `?fragment` swap — so short reasons show that many
  while a reason that wraps to several lines uses more of the budget. A single
  **chevron in the card header**, just after the status word, reveals the rest in
  place (▼) and folds it back (▲), with an empty aligned slot when nothing overflows;
  every reason stays in the DOM (clipped by CSS, never mid-HTML), and the leaf detail
  page stays complete.
- **Reasons are separated by a tight rule**: stacked reasons in a card used to run
  together — a wrapped reason's later lines shared the leading of the next reason's first
  line, so several reasons read as one paragraph. Consecutive reasons now carry a thin
  hairline and a tight gap (never above the first), on the dashboard and the leaf detail
  page alike, drawn from `currentColor` so the line reads on every status fill without a
  per-color rule. The added per-reason height is folded into the `reason_cap` line budget,
  so the fold-away chevron still shows about that many entries.
- **Leaf density is a view toggle, and the filters stick**: a **chips** switch joins
  *hide ok* / *hide idle* / *depth* in the status bar (default on — today's look);
  turn it off and a card's quiet leaves render as full boxes instead of chips. All
  three switches now **persist across visits** in a `SameSite=Lax` cookie, like
  `depth` already did — set only on an explicit change and read back on a plain visit,
  so a viewer's chosen shape sticks. (A hidden form marker tells an unchecked switch,
  which sends nothing, from a fresh visit — the trick that lets the default-on density
  switch round-trip.)
- **Branch density caps deep cards**: in the dense ("chips") view a card's quiet
  (non-warn/error) sub-**branches** past a `config.yaml` budget — `branch_cap`
  (default 3), the count-cap sibling of `reason_cap` — fold behind a **"+N more"** you
  expand in place, so a NAS whose `disk` / `smart` / `system` / `temperature` each box
  a chip-row no longer towers over the grid. A warn/error branch is never folded, so
  nothing urgent hides; with the density switch off, every node is spelled out. The
  reveal survives the ~10s refresh.
- **Status is no longer shown by color alone**: every card, node box and the
  self-monitor strip now carries a small per-state shape cue — a check (ok), triangle
  (warn), filled disc (error), pause bars (maintenance), a hollow ring (idle) — beside
  the color fill, and the warn/error word is lifted out of the muted state text. The
  status word stays for screen readers, so a red/green color-blind viewer can tell the
  states apart. HTML/CSS only.
- **Screen readers announce a problem node box's status**: a nested node box shows no
  status word (only cards and the strip do), so a **warn/error** box's shape cue now
  carries an accessible name and assistive tech reads out its "error"/"warn" state; quiet
  boxes, and the card and strip cues, stay silent (a card/strip word already speaks, and a
  healthy box's "ok" is not worth reading out). HTML only.
- **Maintenance is easy to find again, and folds away when it piles up**: a node
  pinned for maintenance is surfaced no matter how deep it sits or how shallow the
  depth. A maintenance-tinted **pill** joins the status strip just left of the
  `little-sister` heartbeat — a pause-bars glyph and a live count (`12 in maintenance`),
  shown only when something is pinned; click it for a popover of the pinned nodes (path,
  time left and reason, each a link), capped at `config.yaml`'s `maintenance_cap`
  (default 5) with a **"+N more"** to a dedicated **`/maintenance` page** that lists the
  full set — the pill is itself a link to that page, so the full list stays reachable
  without JavaScript. A clickable **"contains maintenance" pip** still marks any card
  whose subtree
  holds a pin — a glance shows where to drill — and opens the same popover scoped to that
  card. And **hide idle** now hides only never-reported nodes, not maintenance (an
  intentional admin state), so a planned window no longer disappears when you tidy the
  view.

### Changed

- **The self-monitor status strip stands on its own**: the `little-sister` heartbeat
  pill moves from under the "updated …" line to a **right-aligned band beneath the
  view controls**, with a small watching-eye glyph marking it as the monitor watching
  itself. It still refreshes and dims inside the ~10s poll fragment (no `poll.js`
  change), and the freshness line stays put.
- **links open in a new tab**: instead of just following the links the renderer now
  opens the link in a new tab.


## [0.2.2] - 2026-07-20

### Added

- **The dashboard holds its shape under stress**: a card's **quiet
  leaves** (OK or idle) collapse to compact name+color **chips**, so an all-green
  host converges toward a wrapping chip row instead of a stack of boxes — a
  warn/error leaf keeps its full box and reason, and a chip's own reason is a click
  away on its leaf page. Card heights are bounded (the reason caps above, a
  `min-height` floor below), and the always-tiny `little-sister` heartbeat moves out
  of the grid into a compact **status-strip pill** under the "updated …" line —
  a side note, not a summary banner — whose hover card explains the heartbeat
  by default (a `nodes.yaml` `about` overrides it). Card
  **positions stay a function of the node set** (no packing layout), so the everyday
  grid stops looking ragged without anything jumping on a status change. The
  `/little-sister` line is **reserved** — a custom check owning nodes there is
  rejected at load: the one-line strip must never hide a subtree, and the engine
  keeps the namespace for children of its own (should it ever grow some, the
  heartbeat falls back into the grid as a card). A heartbeat `title`/`about` from
  `nodes.yaml` feeds the strip and its hover card like any node's, without the
  orphan warning. HTML/CSS plus that load-time guard; the snapshot and JSON
  envelope are unchanged.
- **Dashboard reason overflow is capped**: a card shows at most six reason entries
  and clamps a tall reason block (a long `code()` trace) to about eight lines, with
  a per-node **"show all (N)"** that expands it in place and survives the ~10s
  fragment swap; every entry stays in the DOM (trimmed by entry and by CSS, never
  mid-HTML), and the leaf detail page and the JSON envelope stay complete. Reins in
  the unbounded card growth that made the grid ragged.
- **Engine-start failures reach the dashboard**: when the checks configuration
  fails to load, every page carries a persistent red banner with the reason
  ("Engine not started — …") instead of a blank, quietly-empty overview with the
  explanation only in the log. Covers the failed-start (`CheckError`) path; a
  deliberate `LITTLE_SISTER_ENGINE=0` disable shows no banner, and the
  standalone login page never shows the reason.
- **A fuller `/system` check table**: a **Type** column (two checks sharing a
  root node stay distinguishable), and three schedule columns each shown as a
  time of day plus an interval — **Running** (the in-flight run's start and
  elapsed so far; "queued" while it waits for a worker), **Next run** (the
  armed slot, shown even while a run is in flight — it replaces the old
  "running" placeholder), and **Last run** (the last completed run's start and
  wall time; a check that raised or timed out shows its full wait; a
  secret-pinned check, which never runs, shows "—").
- A guide to previewing the web UI against synthetic extremes,
  [`docs/testing-the-gui.md`](docs/testing-the-gui.md): a static fixture sheet
  rendered through the real templates (extreme trees, side by side) and a live
  demo tree replaying scripted scenarios — both dev-only, under `tests/`;
  nothing enters the package.

- **`/system` refreshes itself**: the system page carries the same server-seeded
  "updated …" stamp as the dashboard (so it always says from when its
  information is) and re-fetches its info block every ~10 s through the shared
  poll (`static/js/poll.js`), flagging failures the same way.
- **A sustained outage escalates**: the freshness line no longer treats a
  10-second blip and an hour-long outage alike. After ~1 minute of failed polls
  the dashboard and system pages show the outage age ("could not refresh for
  14 min — last ok …"), raise a red banner naming when the frozen data is from,
  dim that content, and prefix the tab title with "(stale) " — all reset by the
  first successful poll. A re-focused or woken tab re-polls immediately instead
  of waiting out the interval, and an expired session gets its own
  "Session expired — reload to log in" banner right away.

### Changed

- **Check schedules spread out**: after the immediate first sweep, each check
  settles onto a stable personal phase (within `min(frequency, 60 s)`, derived
  from its path and type) instead of every equal-frequency check firing in the
  same second forever — no more synchronized SSH bursts onto the worker pool
  and the monitored hosts, and a host carrying two checks is no longer hit by
  both at once. Visible on `/system`'s next-run column.
- The dashboard's freshness stamp is **server-seeded**: the page renders its own
  generation time into the "updated …" line (previously a "live" placeholder
  until the first successful poll), so a dashboard that never reaches the server
  again reports *"could not refresh — last ok \<page render time\>"* instead of
  *"last ok never"*.

### Fixed

- An expired session can no longer let the poll inject the login page into the
  dashboard grid: a fragment response without the `X-Rendered-At` header counts
  as a failed poll (shown red) instead of being swapped in.
- The freshness line's failure state now actually renders **red**: the stamp
  kept its muted styling class alongside the danger class and Bootstrap's
  cascade let muted win, so a dead server showed a gray "could not refresh —
  last ok …" line. The poll now swaps the classes instead of stacking them.

## [0.2.1] - 2026-07-19

### Added

- **Secret references** ([ADR-0023](docs/adr/0023-secret-references.md)): a check
  credential in YAML names its source — a bare environment-variable name (the
  unchanged default, fed by `.env`) or a `scheme://address` reference resolved by
  a resolver the deployment registers in code
  (`little_sister.secrets.register_resolver`). Secrets resolve **once, at check
  construction**, never during runs; a reference that cannot be resolved pins
  just that check to a visible ERROR ("secret unresolvable: …") instead of
  stopping the engine.
- The application settings `SECRET_KEY` and `LITTLE_SISTER_API_TOKENS` may now
  themselves be **secret references** (`scheme://address`), resolved once at
  startup through the deployment's registered resolvers — one step closer to
  running without any `.env` file. An unresolvable reference degrades safely
  (random session key / no API tokens, loudly logged); a malformed one fails
  startup.
- A developer guide for building custom check types,
  [`docs/implementing-checks.md`](docs/implementing-checks.md) — the `Check`
  contract, branch results, registration and startup wiring, secret references,
  testing.

### Fixed

- The dashboard's live-refresh line ("updated …" / "could not refresh — last
  ok …") now renders its timestamp with the configured `time_format` and
  timezone (`config.yaml`), matching every other displayed time. It previously
  used the browser's locale, so a 24-hour deployment saw a 12-hour "AM/PM"
  clock in that one spot.
- Distribute a `py.typed` marker (PEP 561) so downstream projects can
  type-check against little-sister. Without it, type checkers treated the
  installed package as untyped and reported missing type information for
  `little_sister` imports.

### Security

- Without `SECRET_KEY`, little-sister now generates a **random session key at
  each start** instead of falling back to a fixed, insecure development key.
  Sessions (logins) reset on a restart unless an explicit key is configured.

## [0.2.0] - 2026-07-15

First release. little-sister is a small, self-hosted status dashboard:
configurable **checks** run on background threads in a single process, their
results aggregate into one **status tree**, and the tree is served as a web
dashboard and a read-only **JSON API**.

- **Checks:** `http`, `file`, `command`, and an SSH family — `ssh-connect`,
  `ssh-command`, `ssh-script`, `host-metrics`, `qnap-metrics` — with
  per-userland metrics scripts (Linux, macOS, busybox) shipped as package
  data; example configs in `checks/examples/`.
- **Status semantics:** worst-of roll-up with `MAINTENANCE` and `UNDEFINED`
  handling, freshness (an unobserved node degrades to WARN), engine
  self-monitoring, node metadata (`about`, `title`, `config` — Markdown),
  an event log and per-node history.
- **Web UI:** dashboard with drill-down and breadcrumbs, node detail pages,
  admin **maintenance** windows (always with an expiry), and a system page;
  session login with viewer/admin roles.
- **JSON API:** content negotiation on `GET /status[/<path>]`, named
  per-client bearer tokens, Problem-JSON errors; the normative contract is
  `docs/api/openapi.yaml` (OpenAPI 3.1) — this release serves **contract
  version 1.1.0** (envelope `schema_version: 1`).
- **Packaged as a library**, consumed by a separate deployment repository
  that holds the real checks, users and secrets; configuration and secrets
  come from the working directory and a git-ignored `.env`.

A native macOS menu-bar client lives in its own repository,
[little-sister-app](https://github.com/m-31/little-sister-app), and consumes
the JSON API.
