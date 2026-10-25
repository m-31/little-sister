# Little Sister — Decisions

> One digest per decision: the heading, the answer in a few lines, and a link to the
> Architecture Decision Record in [`adr/`](adr/) for the context, the alternatives and
> the date. The digest says **what** was decided; the record says why, and holds the
> history.
>
> Every decision here is in force: a record that is superseded or withdrawn leaves, and
> its digest with it.

---

### ADR-0001 — Process & threading model (the in-memory baseline)

One process — `gunicorn --workers 1 --threads N` — with the engine running the checks
on background threads over a single in-memory status tree and event log. A single
worker is a hard constraint; the engine starts once, after the fork, at the server's
start through the hooks module the library ships, and a stop abandons a run in flight
rather than waiting for it; every check keeps a timeout of its own. → [record](adr/0001-in-process-threaded-engine.md)

### ADR-0002 — Synchronizing the shared state

One `threading.RLock` guards the tree and the event log, since the GIL makes no compound
operation atomic. Writers and change detection hold it — a run's store from its first
write to its last, so nobody reads half a run — and readers copy a snapshot under it and
render outside it. → [record](adr/0002-rlock-snapshot-synchronization.md)

### ADR-0003 — Configuration & secrets via a `.env` file

The Flask secret key and the check and API credentials come from one git-ignored
`.env`, read through the process environment — never from code or version control.
→ [record](adr/0003-config-and-secrets-via-env-file.md)

### ADR-0005 — Dashboard freshness & engine self-monitoring

A node not observed within its stated freshness tolerance — about twice its interval
where it has a `frequency`, the ceiling it declares where it has none
([ADR-0079](adr/0079-freshness-is-a-stated-tolerance.md)) — is **stale** and degrades
to at least `WARN` at render time; the dashboard polls a fragment every ~10 s and flags
a failed refresh; the engine heartbeats a `little-sister` node each tick, so a stalled
scheduler goes red through staleness, and an external supervisor handles whole-process
death. → [record](adr/0005-dashboard-freshness-and-self-monitoring.md)

### ADR-0007 — Checks may report a branch (recursive `CheckResult`)

`CheckResult` is a small recursive value with `name`, `description` and `children`; the
engine upserts the root at `check.full_path` and each child beneath it, while identity,
observation time, maintenance and events stay the tree's concern. A leaf result is
unchanged. → [record](adr/0007-check-result-branches.md)

### ADR-0009 — Per-profile remote metrics scripts

The `host-metrics` script is three scripts by userland —
`host-metrics-{linux,macos,busybox}.sh` — chosen by a host's `profile` (default
`linux`), which also picks the interpreter; each self-guards on `uname` and reports a
mismatch as a visible `WARN`. → [record](adr/0009-per-profile-metrics-scripts.md)

### ADR-0011 — SSH check family

One transport (`SshConnection`) and an `ssh-` family named by intent — `ssh-connect`,
`ssh-command`, `ssh-script`, `host-metrics`, `qnap-metrics` — over a shared pure
`ssh_metrics` toolkit in a `checks/ssh/` subpackage; a non-post-quantum key exchange
surfaces as `WARN` on every connecting check. → [record](adr/0011-ssh-check-family.md)

### ADR-0012 — Node metadata: an `about` note, separate from check descriptions

A node's `about` is a Markdown note fed in precedence order `nodes.yaml` (keyed by
path, so container nodes and graft points are reachable) > inline on the owning check >
empty, kept separate from `description`; branch checks describe each leaf through a
`descriptions:` map; a startup pass warns about an `about` path no check covers and
notes one past 400 characters, an `about` being a node's short account (ADR-0133). An
entry's `tags:` add up with every other place that writes them (ADR-0139).
→ [record](adr/0012-node-metadata.md)

### ADR-0013 — Surface check config as node display metadata

A check pushes a curated allow-list of its configuration onto the `CheckResult`, stored
on the node like `description` — static display metadata for leaf detail pages, out of
aggregation, without an event, and not in the JSON envelope. Refines
[ADR-0007](adr/0007-check-result-branches.md). → [record](adr/0013-check-config-on-node.md)

### ADR-0014 — Persist maintenance to a file, with auto-expiry

A maintenance side-table written through to `var/state/pins.json` and replayed before
the engine runs, keyed by `path` and by `(path, slug)`; a pin is held against its path
and makes no node. Its times are instants in UTC, and a file of another shape or with a
time without a zone is refused, never migrated. Every pin expires — a week by default,
at least the slowest covered check's interval, at most a year — is swept by the
scheduler, and is reaped at startup unless a check or the instance's own node covers it.
An edit is a compare-and-set on `set_at`, keeps an expiry left as it was filled, and
writes nothing where nothing changed. → [record](adr/0014-maintenance-persistence.md)

### ADR-0015 — Check discovery: a union of config directories

`LITTLE_SISTER_CHECKS_DIR` is a list of directories loaded as a union; checks say which
nodes they own and overlapping ownership is a hard error; configuration applies at
startup, with no live reload. → [record](adr/0015-check-discovery-union.md)

### ADR-0016 — Node addressing: a single absolute slash path

A node is addressed by one absolute slash-separated path (`/system/alpha/disk`); a
segment may contain dots, so a node can be named for its FQDN; `name` is the derived
last segment, no longer authored; the separator lives in `status.py` helpers.
→ [record](adr/0016-node-addressing.md)

### ADR-0017 — Node title: a short display label

An optional one-line Markdown `title`, fed like `about` (`nodes.yaml` > inline on the
owning check > empty), shown after the node name on an open node's head, in the
inspection card and beside the breadcrumb in a page header — a chip draws none — never
replacing the name. → [record](adr/0017-node-title.md)

### ADR-0018 — Markdown rendering for node text

Every text — `title`, `about`, `description`, a handbook, `reasons`, a maintenance
reason — renders server-side through one markdown-it-py renderer with safe defaults —
raw HTML escaped, link schemes validated, `noopener noreferrer` on links, bare `http(s)`
URLs linkified, GitHub's tables and strikethrough — and the check base provides
`plain()` and `code()` so captured output is folded in safely. The renderer is handed
the node: `handbook#…` leads into its handbook, and a status a text names, `{error}`, is
drawn as its sign (ADR-0133). The JSON envelope keeps raw Markdown.
→ [record](adr/0018-markdown-rendering.md)

### ADR-0019 — Inspection popover (hover card)

A client-side hover card shows a node's name, title and the first block of its `about` —
its `description` where it has none — its tags and a link to its handbook, as
server-rendered Markdown from a path-keyed map every refresh of the grid carries, and
never its live state. It opens on a pause on a node's name where a browser's look says
so — the library's look keeps it closed — is not offered on touch, stays on its node
through the grid swaps, replaces the `title=` tooltips and needs no new route. A rule's
note opens in a card of its look, on its machinery.
→ [record](adr/0019-inspection-popover.md)

### ADR-0021 — Script resolution: packaged defaults with an override

The generic measurement scripts are package data; a built-in check's default script
resolves `LITTLE_SISTER_SCRIPTS_DIR` → the config's own directory → the packaged copy,
first match wins, and an explicit `script:` is unchanged.
→ [record](adr/0021-script-resolution.md)

### ADR-0022 — Public releases from a generated, condensed `main`

`main` is generated per release: the working branch's tree is snapshotted onto a
worktree, condensed (documents classified keep/drop/error, trailers and dev-only
blocks stripped, links validated, the surviving tree scanned against a private-strings
denylist), reviewed, and landed as one squash commit with an annotated tag. Humans
review and push. → [record](adr/0022-generated-release-branch.md)

### ADR-0023 — Secret references with deployment-registered resolvers

A reference names its source — `scheme://address` — `env://` built in, any other scheme
a resolver the application registered before the app import; only addresses appear in
configuration. Secrets resolve once, at check instantiation; a malformed reference
fails the load, a failed resolution pins the check to ERROR; `SECRET_KEY` and the API
tokens may themselves be references. → [record](adr/0023-secret-references.md)

### ADR-0025 — Check-provided subnode metadata (`about` / `title` on `CheckResult`)

A type declares `subnode_defaults` and `label_tokens` as data; the library resolves each
field once (configured text, else the default, `{default}` and `{token}`s substituted —
no token named `default` or for a status) and the engine stores it per child name.
Precedence per field is `nodes.yaml` > declared or check-provided > empty, kept by
seed-once semantics; labels — `title`, `about`, `handbook` — freeze at first fill, a
`CheckResult` child's the fallback and, beneath `nodes.yaml`, the only source for a
child a run names (ADR-0118). `details` are no label, and the block carries `tags:` too.
→ [record](adr/0025-check-provided-subnode-metadata.md)

### ADR-0026 — Reading values from decoded bags (`values.py`)

Narrowing lives where `Any` enters: `little_sister.values` (`text`, `number`, `real`,
`flag`, `rows`) takes a bag plus a key path and always returns the declared type —
absent → default, `required` → `CheckError`, present-but-uncoercible always raises.
`CheckError` lives in `errors.py`. → [record](adr/0026-reading-values-from-decoded-bags.md)

### ADR-0027 — Observation timestamps: stamped where written, rolled up while unambiguous

A timestamp appears only where "when did the check behind this node run?" has one
answer: none at construction, a written node's own last write, an unwritten ancestor's
sole mount inherited at snapshot time (a mount shared by two checks counts as two), and
no timestamp above two or more mounts. Observation times never aggregate; freshness
stays `stale`; the JSON `timestamp` is nullable.
→ [record](adr/0027-observation-timestamp-semantics.md)

### ADR-0028 — Design tokens: one named palette, and a theme is an override of it

The stylesheet names its palette once on `:root` — per status a vivid fill and a pale
tint, each with its ink, borders mixed from the ink — and paints only from it; a theme
is an override block on `body[data-ls-theme]`, never a fork; the library's theme is
cyberpunk. The accessibility bar outranks any swatch: status text holds AA in every
theme, and a pick that collides finds another vehicle.
→ [record](adr/0028-design-tokens-and-themes.md)

### ADR-0029 — Presentation preferences live in a cookie, not in the server

One long-lived `ls_prefs` cookie per browser, read server-side onto `<body>` — the
layout, the theme and the looks of one roster: how chips run and boxes fill a level,
whether the inspection card opens, how a row answers the pointer, where a head keeps its
buttons, whether a failure opens its way — each defaulting to the deployment's
`settings.yaml`, so the page renders in the chosen look; every failure mode lands on the
defaults per key; the settings menu, a line beneath each heading saying what it changes,
posts to `/preferences`. The look is the browser's; per-user settings wait for a store.
→ [record](adr/0029-per-user-presentation-preferences.md)

### ADR-0030 — Curated links come from a deployment-supplied file

`/links` is a structured `links.yaml` aspect of `config/` — one flat level of groups,
merged by title across roots, file order preserved — with icons resolved by name through
the deployment's map and `links/icons/`, packages' packs, the built-in pack, the origin's
favicon and a neutral glyph; a remote mark or a favicon is fetched by the viewer's
browser from a host the page's own policy allows. Structural validation runs at load and
never touches the network, and nothing is probed: a dead link is found by clicking it, a
tool whose availability matters is an `http` check. → [record](adr/0030-curated-links.md)

### ADR-0031 — One deployment config directory, split by aspect

`config/` is one layered directory of aspects, `LITTLE_SISTER_CONFIG_DIR` a path list of
roots, each saying how its layers combine: checks union, an overlap a hard error;
`actions`, `csp`, `tags.yaml` and `nodes.yaml`'s tags add up; `nodes.yaml` otherwise wins
per field from the later root, `settings.yaml` per key, links by title; `users` is the
first root's whole; `aggregation.yaml` reads every root's rules, the last-named first; a
`handbook/` file is named in its own root. `.env` and `var/` stay out; startup refuses a
missing tree or no `checks` and warns about an unclaimed file. The override ladder —
packaged default → package override → deployment file — is the house pattern. → [record](adr/0031-deployment-config-directory.md)

### ADR-0032 — The contribution boundary: what a node shows and what it publishes

A node has three statuses — reported (stored), own and effective (`own_code`, `code`)
and its **contribution** to the parent — and every policy that changes what a node
reports upward (maintenance, staleness, a shield, a counter, a deployment's configured
table, ADR-0137) is a contribution rule applied in the snapshot, never a value written
into the tree and never a sixth code. A transformed contribution is visible and
attributable, keeps a liveness backstop, and an unusable rule does not apply. The
boundary reaches one level below a node: its addressable entries are virtual children.
→ [record](adr/0032-status-contribution-boundary.md)

### ADR-0033 — A faster second look: the budgeted failure retry

A run that rolls up to something other than `OK` pulls its armed next slot to
`min(armed, now + retry_interval)` — earlier, never later — at most `retry_attempts`
times per failure episode, which any change of what the run rolls up to ends; staleness
keeps judging by the nominal frequency, `/system` marks a retry slot, a secret-pinned
check never retries. `retry_interval` is off by default.
→ [record](adr/0033-budgeted-failure-retry.md)

### ADR-0034 — Template slots for dependent packages

The library declares a closed roster of named slots with the context each hands over; a
dependent package registers its own template (only as `ext/<package>/<name>`, additive,
never shadowing) plus an optional context provider, which receives the names it declares
and returns `None` for *nothing here*. A broken filler contributes nothing and the page
renders. Slots: `reason.actions` (with the whole `line`) and `node.actions`, in the
head's row of every open box and of a node's page's frame, `place` telling a card, a box
and a frame apart; both hand over `written_out` and `details` for a draft.
→ [record](adr/0034-template-slots-for-dependent-packages.md)

### ADR-0035 — A dependent package registers its own configuration aspect

`config_dir.register_aspect(name, as_file=…, as_directory=…)` in the import-before-app
slot makes a package's file an ordinary aspect — same shape enforcement, same layering
helpers — while its schema stays the package's; a built-in name is refused, the first
registration of a name wins, and registered aspects show on `/system/installed`.
→ [record](adr/0035-registering-a-config-aspect.md)

### ADR-0036 — Addressable reasons: keyed entries, and maintenance on one of them

A reason is a keyed entry, `slug → text`, in the check's order; prose is the default and
members are declared (a mapping, or `entries=True`), an undeclared entry keyed by a
content hash. A pin lives in the maintenance side-table under `(path, slug)`, joined in
the snapshot; absence suspends a pin and only expiry disposes of it; entries are virtual
children, so a node whose members are all pinned has an own status of `MAINTENANCE` that
counts and cancels nothing, and reads it whole only where nothing beneath it counts. An
entry pin is set on its node's own page, a leaf's or a branch's, and is addressed by
`?reason=<slug>`, never a path segment. → [record](adr/0036-addressable-reasons.md)

### ADR-0037 — Extension static assets: a filler may ship CSS and JS

`slots.register_assets(package, *members)` — bare `.css` / `.js` members of the
package's `static/` — and the library emits the tag, once per page, from our own origin
at `/ext/<package>/<member>` with a content hash in the URL; login-gated, none of it in
the kiosk. An extension's script runs with the page's full authority.
→ [record](adr/0037-extension-static-assets.md)

### ADR-0038 — The declarative action list: `config/actions.yaml`

A built-in aspect, layered like the checks: an entry is `label`, `url`, `slot` and
optionally `icon`, `under` (a node path compared segment-wise) and `tag` (one tag);
`url` is a template over `{path}`, `{name}`, `{code}`, `{reason}`, `{reasons}`, every
value percent-encoded, an unknown placeholder refused at load. It registers through the
slot seam as a `builtin` filler, so a configured chip and a coded one share one rail; a
configured action is a link, and anything more is a package filler.
→ [record](adr/0038-declarative-action-list.md)

### ADR-0039 — Status roll-up: how a parent derives its status

The pure derivation: worst-of `ERROR > WARN > OK` among counted statuses, never a
downgrade — a rule a deployment declares may transform what a part counts above, visibly
(ADR-0137); `UNDEFINED` (*not reported yet*) ignored; `MAINTENANCE` — a pin on the node,
or its check's word for it — contributes nothing and cancels its subtree, while a node
whose lines are all pinned cancels nothing; an updater owning a branch may set its
status explicitly. A node whose children are all ignored reads `MAINTENANCE` when any
was in maintenance, else `UNDEFINED`. `Status.get_status_code()` is this and no more.
→ [record](adr/0039-status-rollup-semantics.md)

### ADR-0040 — What a failing check becomes

`ERROR`, decided by the engine — never a skipped update or a stale `OK` — with the
reason `check error: <message>` escaped like any untrusted string and, by default and
globally, a second reason carrying the innermost frames as an inert code block. A
measurement that raised also leaves an error reading against the check's declared
object; a check whose secret references failed is `ERROR` without ever running.
→ [record](adr/0040-what-a-failing-check-becomes.md)

### ADR-0041 — Maintenance is a contribution rule, not a value

A pin is recorded, never written: the check keeps reporting, `MAINTENANCE` is derived
in the snapshot, the snapshot carries `reported_code` beside the derived `own_code`, and
clearing restores nothing because nothing was destroyed. A pinned check that dies
escalates like any other. Transitions under a pin are recorded and marked —
`Event.suppressed_by` names the rule — and history counts only unmarked events.
→ [record](adr/0041-maintenance-is-a-contribution-rule.md)

### ADR-0042 — A reason entry carries its own code

No sixth code; `INFO` collapses onto `WARN`. An entry may declare a code, and an
entry-bearing node's own status is the worst of its unsuppressed entries (an empty set
reads `OK`; declaring both a node code and entry codes is refused). A per-entry
`running` flag is display only, so a failed job's verdict stays red under its rerun.
Healthy entries are per-aspect opt-in; ordering is the check's duty: non-OK, in flight,
healthy. → [record](adr/0042-entries-carry-their-own-code.md)

### ADR-0043 — The coverage backstop: an empty scope is never silently green

A check that discovers its own scope reports it: zero scope is a `WARN` on the check's
own node naming the filter; the count rides as an `OK` reason, the roster goes in
`report`; the expectation is the check's one `expect_min`, floored at 1 so a deployment
cannot silence the backstop. → [record](adr/0043-coverage-backstop.md)

### ADR-0044 — The run on the node: the container stamp, run facts, and `report`

The mount registry counts checks per path, and the engine writes a run's facts onto a
sole-check container after each run: a `run` object (wall time, next run,
engine-sourced) and a `report` field — what the run found, write-through Markdown beside
`config`, shown on the node's page and never a status claim. Four facts belong to the
check that owns the node alone. The time shows on the topmost visible node, with the
next update beside it (`22:25 → 22:30`), and the branch head is a real node header.
→ [record](adr/0044-run-facts-on-the-node.md)

### ADR-0045 — User avatars live with the user-list aspect

The `users` aspect declares a directory form — `users.yaml` beside `avatars/` — and a
per-user `avatar:` is a bare name resolved only inside that directory, falling back to
the packaged neutral avatar; a login-gated `/user/avatar` serves only the session user's
file. → [record](adr/0045-user-avatars.md)

### ADR-0046 — The user list comes from the configuration roots, and nowhere else

`LITTLE_SISTER_USERS` is retired and startup refuses while it is set: `users` is taken
whole from the first root, so a users-only root named first in the path list already is
a single-file override. `LITTLE_SISTER_CONFIG` stays, since settings merge per key.
The library ships no users, only an example, and a list that is not there fails the
start. → [record](adr/0046-user-list-from-the-configuration-roots.md)

### ADR-0047 — A node keeps notes, and they outlive it

The pin's explanation is renamed `note` and a node keeps a note history: a pin's note
appended when the pin is set, editable while the pin is live and frozen afterwards, and
an admin's own, on a node or a line, editable while it is the newest — each capturing
the node's code and reason lines as they stood, read on the node's *Notes* tab. Notes
transform no code, are exempt from coverage reaping, live in `var/state/notes.json`, and
retire by four `settings.yaml` parameters (`notes_keep` 10, `notes_cap` 50,
`notes_min_age` 13mo, `notes_max_age` 25mo), the count floor winning.
→ [record](adr/0047-node-notes-and-their-retention.md)

### ADR-0048 — The Content-Security-Policy is assembled, never a constant

A `csp` module composes the header at application creation from the library's defaults
(`img-src` names no host and takes `data:`), packages' contributions
(`csp.allow(directive, source, by=…)` — an origin, never a keyword; a
deployment-specific host declared as `csp.origin_of("<aspect>.<field>")`) and the
deployment's `csp` block, which has the last word; a page adds what its own
configuration names — `/links` the hosts its icons load from. The first policy shipped
is Report-Only; `/system/installed` shows the effective policy with its contributors.
→ [record](adr/0048-an-assembled-content-security-policy.md)

### ADR-0049 — The check-authoring surface is contract, and the gate holds it

`architecture.md` §11 names what a check type outside this repository may import, at
the package `little_sister.checks`, and `tests/test_public_surface.py` holds the list
against the code in both directions. Adding a name is compatible; removing or renaming
one is a version bump and a record. Logging is promised as a behavior: the library logs
through the standard hierarchy and configures the root logger only when the application
has not, at INFO unless `LOG_LEVEL` says otherwise.
→ [record](adr/0049-the-check-authoring-surface.md)

### ADR-0050 — A declared slug comes from the provider's identifiers

`slug(*parts)` in `little_sister.reasons` builds identity from identifiers the provider
already owns — never from the text (a hash is the wording) and never from a position;
it narrows to `[A-Za-z0-9._-]` and keeps a readable prefix plus a hash for an over-long
value. Which identifiers a check uses stays with the check.
→ [record](adr/0050-slugs-from-provider-identifiers.md)

### ADR-0051 — What startup refuses at the plugin boundary

A `type:` name is claimed once — a second registration raises naming both classes — and
the check-authoring surface has an epoch, `API_VERSION`, that a package declares with
`require_api(n)` and a mismatch refuses naming both numbers; the epoch is held by a
snapshot of the promised names the gate checks. Both refusals are hard;
`/system/installed` lists every type with its package and version.
→ [record](adr/0051-what-startup-refuses.md)

### ADR-0052 — Plugin names: one convention for a git dependency and a published one

One word in three spellings — distribution `little-sister-<x>`, import package
`little_sister_<x>`, check type `<x>` — so publishing to an index deletes a
`[tool.uv.sources]` table and changes no code; a name is claimed by the package's own
first release, and there is no `little_sister.` sub-namespace.
→ [record](adr/0052-plugin-names.md)

### ADR-0054 — A supported floor of 3.11, developed on 3.14

`requires-python >= 3.11`, the measured floor; development, the uv-pinned interpreter
and the everyday gate stay on 3.14. The floor is checked rather than declared — `mypy
--python-version 3.11` on every commit, the full suite on 3.11 once per release —
`ruff`'s `target-version` is the floor, and there are no compatibility shims.
→ [record](adr/0054-python-floor-and-development-version.md)

### ADR-0055 — Sibling order: alphabetical, unless somebody declares a rank

Siblings sort by `(order, name)` — a declared rank, then the natural case-insensitive
name — once in the snapshot. `CheckResult` grows `order: int = 0`, read on the root as
well as the children; `order:` inline on a check and in `nodes.yaml` overrule it, and a
stated `0` is a real declaration. Ordering by the live grade stays rejected.
→ [record](adr/0055-sibling-order.md)

### ADR-0056 — Dashboard layout follows stable, useful flow

Under the library's rows a card's position is a function of the node set alone (a viewer
may pack, ADR-0138); reason caps, chips and the status strip bound its height. Each
root's flow profile comes from the filtered topology, its first look (ADR-0128) and
`reason_cap` — never from status, reasons, a click or measured height; a span is useful
only when it removes a modeled row per added track; the server publishes
`(tenths, tracks, plan)` breakpoints and the browser sets that many tracks from its
width. `dashboard_columns: plain` withholds the plan; auto-fill CSS is the fallback.
→ [record](adr/0056-stable-useful-dashboard-flow.md)

### ADR-0058 — `little_sister.transport`: a vocabulary for asking something that might not answer

Share the policy, never the client: a stdlib-only module promising `Deadline` (with
`budget(timeout)` and `affords(wait)`), `DeadlineExceeded`, `Fault` (*transient* /
*answered* / *malformed*), `RemoteError` (status, fault, optional `retry_after`) and
`ask` (one bounded retry the deadline can veto). A check builds its deadline from its
own `timeout_seconds`, which bounds the whole run; there is no mapping from a `Fault`
to a `StatusCode`, because whether the endpoint is the subject or the instrument is the
check's to say. → [record](adr/0058-transport-policy-vocabulary.md)

### ADR-0060 — A line makes no claim; the node says it could not look

No sixth code: a line keeps `UNDEFINED` and makes no claim about its subject, and the
node the check owns says `WARN` — the instrument is degraded, the reading incomplete —
counting the could-not-ask kind only. A read failure never replaces a last-known
reading: the check omits the node and freshness says the entries are old. Two amendments
to ADR-0033: the retry budget re-arms on any change of what a run rolls up to, and a
completed run that rolls up to `UNDEFINED` does not arm a retry.
→ [record](adr/0060-a-line-makes-no-claim.md)

### ADR-0061 — Decoration cannot substitute for the thing it decorates

A title with no letter and no digit in it (`isalnum` per character, so a Japanese or
Cyrillic title is a word) cannot stand in for a name and is drawn with it — `critical 🔴`
— on the one surface that draws the title instead of the name, `/copy`; display only.
→ [record](adr/0061-decoration-is-not-a-label.md)

### ADR-0062 — Navigation chrome is layout behavior, not a preference

Keeping the rail or top bar reachable while the page scrolls belongs to the layout the
viewer already chose: no cookie key, no menu switch; a short window keeps the chrome
pinned and scrolls only its constrained child, and the kiosk is untouched.
→ [record](adr/0062-navigation-chrome-is-layout-behavior.md)

### ADR-0063 — A node may decline the density trade (`show_when_quiet`)

An optional tri-state boolean on the node — `nodes.yaml` > the deployment's `subnodes:`
block > the type's declared default > a stamped child result > unstated — read for every
type, on the first look's addresses, `children:` included (ADR-0128); a child that says
a run names it, `dynamic=True`, takes nothing declared for its name, but its parent's
`children:` and then its own result, beneath `nodes.yaml` (ADR-0118). A declared node
starts open whatever its parent's `chips` says, and no configured fold hides it. Display
metadata only: no event, no aggregation, no cookie, no envelope change; *hide idle*
still hides it. → [record](adr/0063-declining-the-density-trade.md)

### ADR-0064 — A secret resolver is a registration like the others

A scheme claim records the package that made it, a second claim from a different package
refuses at startup naming both, the same package registering again replaces silently,
and replacing somebody else's scheme is said out loud with `replace=True`.
`/system/installed` prints the whole scheme list with its owners.
→ [record](adr/0064-the-resolver-is-a-registration.md)

### ADR-0065 — The connection decides what is secure

`request.is_secure` — the socket gunicorn is holding — marks all three cookies `Secure`
exactly when this process terminated TLS; not a configuration value, not the host name,
not a forwarded header. A configured `True` still wins, nothing removes the flag from a
TLS connection, and there is no HSTS.
→ [record](adr/0065-the-connection-decides-what-is-secure.md)

### ADR-0066 — `/health` answers liveness, and says almost nothing

`200` while the process serves, whatever the engine is doing, with `engine` reported in
the body as `running` / `disabled` / `failed`; no login gate, no failure reason, no
version, not part of the JSON API, `no-store`.
→ [record](adr/0066-health-answers-liveness-and-says-almost-nothing.md)

### ADR-0067 — The run scripts can serve TLS, and never verify it

`--tls` on `start.sh`, `stop.sh` and `test_api.sh`, per run; the port moves with the
scheme (`TLS_PORT`, 8443); `TLS_CERT` / `TLS_KEY` both or neither, else a throwaway
P-384 certificate minted into `var/tls/` and overwritten at the next start; the scripts
never verify it and report instead whether the machine trusts a supplied one. One
checkout serves one instance, recognized by its working directory; `--any-instance` is
the way past the refusal. → [record](adr/0067-the-run-scripts-can-serve-tls.md)

### ADR-0068 — The login gate refuses by default, and every route is classified

One `before_request` hook refusing by default; `OPEN_ENDPOINTS` answer with no identity
(the login form and its stylesheet, logout, `/csp-report`, `/health`, two redirects) and
`SELF_AUTHENTICATING_ENDPOINTS` choose their own credential: `/status`, `/series` and
`/series/<path>`. `identity.current_user()` returns an `Identity` or `None`;
`signed_in()` behind the gate answers `401`; `admin` is the only role.
→ [record](adr/0068-the-login-gate-refuses-by-default.md)

### ADR-0069 — Identity comes from outside, and never from a chain

Deciding who somebody is is not the library's job: a provider answers `identify()` and
`challenge()`, with four optional login hooks, and the installation registers every
**door** by name, the built-in list too (`local_login.use_local()`). Several doors are
allowed, an ordered chain is not: a session records its door and `current_user()` asks
that provider only. A duplicate door or default refuses, a missing one logs, a provider
that raises is no identity, a failed credential closes its door. The library ships one
door of its own, the **system admin**; `choose_at_login()` makes `/login` a chooser; and
a route asks `Identity.may(<act>)`, never `admin`. → [record](adr/0069-identity-comes-from-outside-and-one-account-does-not.md)

### ADR-0070 — The report on unclaimed configuration files runs at the end of registration

Resolving a root is silent, and the report on files no aspect claims runs once, from
`config_dir.announce_aspects()` at the app import, over every configured root, naming
the known aspects with the packages that read them — because the registering call was
itself the first resolution, so no ordering could avoid the warning.
→ [record](adr/0070-the-unclaimed-file-report-runs-at-the-end-of-registration.md)

### ADR-0071 — What a restart keeps is a directory of files, and a keeper carries it

Three layers: memory; `var/state/`, JSON files read at startup — `pins.json`,
`events.json.gz`, `series.json.gz`, `notes.json` — written through for pins and notes,
kept at most once per `state_interval` and at the stop's one save for the rest, by temp
file and `os.replace`, by the directory's one leaseholder; and packages behind two
seams, a store per record and a **keeper** mirroring the directory (S3 first). A failure
never refuses to start and is a line on `/little-sister`: a load that failed at ERROR
while the process runs, a save that failed at WARN until one succeeds.
→ [record](adr/0071-what-a-restart-keeps-is-a-directory-of-files.md)

### ADR-0072 — The instance reports on itself through one seam, in lines that clear

Contributors register a name and a callable; every tick the engine writes each
contributor's lines onto its own child of `/little-sister`, as member entries whose
codes derive that child's own and roll up to the root. A report is recorded state, never
a probe; a contributor that raises is caught and stands as one WARN line naming it; a
slug is the contributor's own on its own node — the flat view prefixes the contributor's
name — claimed once under ADR-0064's rules, so a line is pinnable and a re-wording moves
no pin; a line a contributor stops returning clears. `/system/installed` lists each
package's contributors. → [record](adr/0072-the-instance-reports-on-itself.md)

### ADR-0073 — A readiness answer beside `/health`, and it latches

`/ready` answers *has this instance finished coming up*: `200` once a door is
registered, the machine can verify a TLS certificate and the engine has run every check
once; `503 {"waiting_for": [...]}` from the closed vocabulary `doors` / `trust` /
`first-pass` until then. It **latches**, so no later failure withdraws a serving
instance and takes its explaining page with it. An engine switched off is ready, one
that could not load its configuration never is. Ungated, `no-store`, outside the JSON
API; `readiness.trust` (ERROR) and `readiness.all-erroring` (WARN) are the rollout's two
silent failures, and `readiness.saves` (ERROR) a lost state-directory lease. → [record](adr/0073-a-readiness-answer-beside-health.md)

### ADR-0074 — This instance has a name, and the library owns it

`little_sister.instance` resolves one mark per process on first use,
`<name>:<pid>:<started>:<tag>`; `/system` says which instance this is, first and in a
section of its own. `name` comes from `settings.yaml`'s `instance:`, the hostname
otherwise, and a bad one falls back with a warning rather than refusing the start. The
eight-hex `tag` is what makes an equality test on the mark sound: two containers of one
deployment share a name, run as pid 1 and start in the same second. Never parsed; the
promises are that no two processes share a mark and that one process's never moves.
→ [record](adr/0074-this-instance-has-a-name.md)

### ADR-0075 — A check declares what it costs, and startup adds it up

A type may answer `expected_cost()` (worker seconds per run), `expected_entries()` and
`expected_record()` — estimates, not bounds, nothing by default, and a silent check
contributes nothing. Startup sums the first two, each cost over its period against the
pool it will run and the entries against the entry limit, and **compares the third per
check** against `record_limit`, which bounds one record and not a shared ceiling. Past
a limit it refuses by name before the tree is touched; at 80 % it is a fact on the
engine's node. Each declared figure stands beside its measurement on `/system`, and
every limit here is a setting. → [record](adr/0075-a-check-declares-what-it-costs.md)

## Decided without a record

Small display and contract changes recorded here and nowhere else.

### A title that only repeats the name is not drawn (no ADR)

One predicate in `titles.py`, called by every surface, folds case, `_`, `-`, spaces and
whitespace runs, and drops a title that says the name again (`critical Critical`).
Display only: the snapshot and the JSON envelope keep the field.

### Clickable breadcrumbs (no ADR)

Each ancestor segment of the header trail links to its level through a `breadcrumbs`
filter and a shared partial; the current node is plain text.

### The core stays service-free; deployments extend through the seams (no ADR)

External services — an identity provider, a secret store, cloud storage — enter only
deployment-side, through the provider seams ([ADR-0023](adr/0023-secret-references.md),
[ADR-0069](adr/0069-identity-comes-from-outside-and-one-account-does-not.md)): the core
gains no SDK, no service and no extra deploy step, and a plain local install keeps
working with none of it. Whether a durable store holds the same line is the store's own
question.

---

### ADR-0076 — The instance's node is a branch: a child per contributor, an action per child

`/little-sister` is a branch: the root carries the beat, one child per speaker —
`/little-sister/engine` and `/little-sister/<contributor>` — each written every tick
with that speaker's lines under their own slugs, OK and present when it has none. The
strip is the roll-up and links to the page. A contributor declares its title and about
at registration; a package may offer an admin-only action on its child, run by
`POST /little-sister/<contributor>/act/<slug>` and rendered through the slot seam.
**Breaking before the first release:** every pin on `/little-sister` moves to its child.
→ [record](adr/0076-the-instance-node-is-a-branch.md)

### ADR-0077 — Authority follows the lease: a state file is adopted in a running process

Whoever holds a keeper's lease wrote the truth up to the moment it lapsed; an instance
that stood by holds a shadow. A state file gains a `restore` direction and the keeper
an optional `changed_since_sync()`; when the keeper's `tick` turns from declining
saves to taking them, every file it names is adopted before the first save — the
process first, then the live file set aside as `.bak` and the store's copy in its
place. The `.bak` never leaves the machine; the `state` child lists it beside the live
copy, and *take the backups* swaps them back through the same adoption.
→ [record](adr/0077-authority-follows-the-lease.md)

### ADR-0078 — The unit is what the engine releases, and a check declares its own

The engine releases **units**, never checks: a type may answer `units()` with the keys
it reads and `run_unit(key)` with one of them, and a check that says nothing is a
one-unit check — today's behavior as the degenerate case. Additive, so the check API
epoch does not move and no package has to release. A unit answers for the nodes it
writes, so [ADR-0044](adr/0044-run-facts-on-the-node.md)'s ownership rule counts units
rather than checks, and failure, retry and coverage are per unit rather than per check.
The envelope carries `run` wherever a unit answered, and no key names the unit.
→ [record](adr/0078-the-unit-is-what-the-engine-releases.md)

### ADR-0079 — Freshness is judged against a stated tolerance, never a derived one

`frequency + max(frequency, 30s)` where there is a period
([ADR-0005](adr/0005-dashboard-freshness-and-self-monitoring.md), unchanged); the
**cycle ceiling** the check declares (`stale_after:`, required of a paced check and
refused at startup when absent) where there is none. A derived expected cycle is never
a status input — it is a line on `/little-sister` beside `late.<path>`, since a
collapsed pace is a fact about the engine, not about somebody's repository. The
envelope publishes the verdict and the tolerance applied (`run.stale_after_seconds`),
never the rule. → [record](adr/0079-freshness-is-a-stated-tolerance.md)

### ADR-0080 — The envelope is the snapshot, published: `schema_version` 3

What the JSON publishes is what the dashboard renders, and **a field added to the
snapshot is added to the envelope in the same change**, additively. `reported` / `own`
/ `code` with a `contribution` naming the rule the parent's count came from; `entries`
(addressable or prose) for the string `reasons`; `handled` for every rule on a part;
`run` — present where a **unit** answered, absent elsewhere — for the nullable
`timestamp`; `report`, `order`, `show_when_quiet`; an `instance` block. No versioned
media type: the client ships with the server. Content negotiation, Problem JSON and a
per-client bearer token stand. → [record](adr/0080-the-envelope-is-the-snapshot-published.md)

### ADR-0081 — An instance's own node states a freshness tolerance, never a period

A node may **state** how old its reading may get (`Status.stale_after`), and a stated
tolerance is what freshness measures — one resolution behind both the stale verdict and
the number the envelope publishes. The instance's own branch states the tick's tolerance
and carries no `frequency_seconds`, so nothing renders the scheduler tick as a check's
period; the 31-second dead-scheduler window is unchanged. A surface shows the period
where there is one and the promise where there is not. The envelope does not move:
[ADR-0079](adr/0079-freshness-is-a-stated-tolerance.md) had separated the two fields.
→ [record](adr/0081-an-instance-node-states-a-tolerance-not-a-period.md)

### ADR-0082 — A line carries what it is about and what it read

An entry gains **`subject`** — the source's identifier for the entity the line stands
for, which a slug cannot be split back into and which nothing may be pinned by — and
**`data`**, the record of what the check read beside the sentence it wrote; `text` does
not move, and neither declares members. Typed: `at`, `started`, `ended` at any depth,
offset-bearing or null, UTC at the seam. A refused record — not a mapping, a non-time
under a timed name, or over `record_limit` bytes (default 3 KB) — costs its line, not
the run (ADR-0093). A line also carries its occurrence, which a *seen* is bound to.
→ [record](adr/0082-a-line-carries-what-it-is-about-and-what-it-read.md)

### ADR-0083 — A node may wait before it escalates

A node publishes a worse code upward only after `escalate_after` **consecutive
readings** of it, counted on the reading and on what the node shows. The leaf is honest
from the first failure; only the escalation waits, and a held node publishes **what it
published before** — the first rule here that transforms a contribution rather than
withholding one, so the snapshot carries it and `contribution.code` can be a real code
(spec 2.2.0). Recovery is immediate, a different worse code restarts the count, an
unranked move is none, and staleness goes past it. Default 1 ≡ today; memory, not state.
→ [record](adr/0083-a-node-may-wait-before-it-escalates.md)

### ADR-0084 — A check may be reached through another

A check names one check it is reached **through** (`depends_on`, a path; unknown targets
and cycles refused at load). While that dependency reports `ERROR`, the node keeps its
own reading and contributes **nothing** upward — its `OK` as much as its `ERROR`, since a
reading taken through a broken path is no evidence either way. The mark sits at the
check's mount; a never-reported or stale dependency does not shield, a stale dependent is
not shielded, and a shielded dependency does not shield on. Derived per snapshot. Both
ends say so, and the envelope carries `shielded_by` (spec 2.4.0).
→ [record](adr/0084-a-check-may-be-reached-through-another.md)

### ADR-0085 — A measure is read out of a record, not declared into it

A **measure is a projection over the record**, chosen when it is drawn, not a typed field
declared at the seam — the footing grading and rendering already have. The unit belongs
to the projection, so a wrong one costs an axis label and not a poisoned series. A check
run reads **one object** and the result is **one record** — nodes, children and lines are
derived from it — held by a `Measurement` (ADR-0086); a line carries one only where the
object has no node. A measurement that is to have a history names its object, since a
node path is the deployment's label. The `http` check times the endpoint, not our run.
→ [record](adr/0085-a-measure-is-read-out-of-a-record.md)

### ADR-0086 — A check measures, and then grades what it measured

`run()` becomes **`measure()`**, which reads the world and hands back a record per
object, and **`grade(measurements, now)`**, which answers the codes and the texts as one
`CheckResult`. The grading is **pure over (record, configuration, now)**, so the series
can ask it again over old records; a record is not the check's working state, and free
text entering one is clipped once and **in bytes**, making `expected_record()` a ceiling
the seam cannot exceed. A check declares its **object** at construction, the engine
writes the failure record when a measurement raises, and `Measurement` holds both.
→ [record](adr/0086-a-check-measures-and-grades.md)

### ADR-0087 — A check keeps its subjects' readings, and an identity keeps each event once

A **series** is a subject's records over time, keyed by the check — its **type and its
mount** — and the **subject**. An **identity** replaces the kept record of its event, a
**state** the newest record while it holds, and neither appends. Retention is
`series_keep`, a **count** in the check's own YAML, default **0**; order is the record's
own `at`, else first seen. A kept reading carries the **code and the sentence as they
stood**, and `series.json` keeps it across a restart. `series_limit` bounds all of them
in bytes, evicting the one written to longest ago at ERROR; a **projection** past it is
a WARN from the first tick. → [record](adr/0087-a-check-keeps-its-subjects-readings.md)

### ADR-0088 — A stop ends at its save

The engine stops at gunicorn's `worker_exit`, through a hooks module loaded with
`--config python:little_sister.gunicorn_hooks` (`atexit` the backstop), abandons the runs
in flight on a pool the interpreter does not join, ends what they started, and makes one
final save with nothing written after it. Keep-alive is off; the grace is one value,
`GRACEFUL_TIMEOUT` (30 s); `stop.sh` waits for every process it read before the TERM;
and a container names its stop timeout beside the grace.
→ [record](adr/0088-a-stop-ends-at-its-save.md)

### ADR-0089 — A process a check starts ends with it

`little_sister.process.run` is promised, `fetch`'s counterpart: a group of its own,
`/dev/null` for stdin, a bound, both streams read under a cap, the group ended at the
bound and at the stop, and an answer that says how the process ended. The library's
`command` and `ssh` and `little-sister-aws`'s login use it, and an `ssh` run's remote
command ends with its connection through a wrapper that signals only a group it leads or
one `setsid` gave the command, with the script on stdin ahead of the hang-up line and a
command line of at most 1,024 bytes.
→ [record](adr/0089-a-process-a-check-starts-ends-with-it.md)

### ADR-0090 — One state directory, one writer

A lease file beside `var/state/`, beating every 10 s and lapsing at 30 s, with a kernel
lock for the machine the kernel sees: under one kernel the lock decides, across kernels
the heartbeat. A process that cannot take it restores, runs and saves nothing; a start
refuses rather than waits; a holder that loses it stops its engine and its writes,
serves its last view, and says so on the readiness node.
→ [record](adr/0090-one-state-directory-one-writer.md)

### ADR-0091 — An import is not an instance

Importing the application builds it and writes nothing. The server's start takes the
lease, opens the log with what the import logged, resolves the settings' references and
starts the engine; a start the lease refuses halts the server naming the holder, and a
server without the start says so while `/health` stays `200`. `LITTLE_SISTER_ENGINE=0`
stays for a server without an engine, and the epoch does not move.
→ [record](adr/0091-an-import-is-not-an-instance.md)

### ADR-0092 — A check declares its measures, and the node that stands for a subject shows its series

`measures:` in a check's YAML maps a record field's dotted name to its unit, merged per
field over the `measure_defaults` its type declares (`null` removes one), as `subnodes:`
is. A unit is free text; `ms` and `s` are written through `format_span`, `B` to `TiB`
through `format_weight`. A point sits on its series' own clock, to scale; a reading with
an `error` is a marked break, one without a number or a hole a plain one. A node's page
shows the curves that stand on it, its Series view every curve at or beneath it and the
newest `reading_cap` readings (10, in `settings.yaml` or per check); History has them
all. → [record](adr/0092-a-check-declares-its-measures.md)

### ADR-0093 — A record the seam refuses costs its line, not the run

Any of the four refusals costs the line or the reading the record belongs to, never the
run. A line keeps its text and code and carries **`refused`**, the reason, beside a null
`data` (spec 2.6.0). A refused reading is not graded: its series keeps the engine's
failure record, and the node a `WARN` line in the node's own form — a run with no
reading left stands as one that raised. The instance holds a `WARN` for each, the seam
raises as before outside the engine's runs, and `/system` counts the refused as seen.
→ [record](adr/0093-a-record-the-seam-refuses-costs-its-line.md)

### ADR-0094 — A restart is no transition, and the instance's own node records the gap

A node's first reading after a restart is compared with what the restored log last
recorded for it: the same reading keeps its period, any other — `UNDEFINED` included —
changes from the old code, and a pin the log already holds writes nothing at its replay.
A change seen across a restart is not marked. `/little-sister` alone records the gap,
closed at the later of the stop's `stopped_at` stamp and the lease's last beat. On
`/history`, a container's current `UNDEFINED` is no row, as on its Time card.
→ [record](adr/0094-a-restart-is-no-transition.md)

### ADR-0095 — The instance states its memory, and a rise names what was running

Linux reads the size now and the peak, macOS the peak alone; the `memory` line grades
what it graded before, held: the worst reading of ten minutes, with when it was and the
size now. `/system`'s engine block and the engine's `report` carry the figures, and
*This instance* stays what is settled at import. The log carries them every ten minutes
on the clock, at the first tick and the stop. A run's line and the tick's own carry what
rose from 1 MiB *while it ran*, naming what else was in flight, never a cost, and after
a run that rose a paced collection. What the machine has left is a fact; its line is
decided, not built; no recycle. → [record](adr/0095-the-instance-states-its-memory.md)

### ADR-0096 — A measure names its node and its things, and a curve marks only a reading that failed

A measure's `node` names the node its curve stands on, relative to the one its reading
stands on. A type keys the things a record counts by their nodes' names — `volumes`,
`drives`, `processes` — and a declaration's `*` picks the key. `KiB` to `TiB` join `B`
as family units, through `format_weight`. A reading whose record carries an `error` is
marked on every curve, and a failed run in the lane; one that answered without a number
breaks the line plainly, and a measure with no number draws no curve. `host-metrics`
writes `load1_per_core`, and the library's types declare the numbers they grade.
→ [record](adr/0096-a-measure-names-its-node-and-its-things.md)

### ADR-0097 — A node's series have a view of their own, beside its status and its history

`/series/<path>` shows every curve at or beneath a node, each under the node it stands
on, on one time axis, with each series' newest `reading_cap` readings folded beneath; a
series with no measure links its History page. A node's page shows only the curves that
stand on it. The breadcrumb starts at `nodes` and keeps the view, tabs switch between
Status, Series, History, Notes, a handbook where there is one, and Copy, and the rail
gains Series. `/status` stays the overview, `/series` is an index, and there is no
`/history` root.
→ [record](adr/0097-a-nodes-series-have-a-view-of-their-own.md)

### ADR-0098 — A Series view is drawn over the window its URL names

`/series/<path>?from=…&to=…`, Grafana-style: `now`, `now-6h` or an instant. The window
is the Series view's: every curve drawn over it, which curves stand decided by everything
kept. One bar names it and holds the presets and the moves, each in its place; a window
ending now stays live, and a stretch chosen on the time axis or by a drag holds still.
A script adds the drag and a line reading every curve at the pointer, over the links.
Labels fall on round local times; past 336 readings a column draws its first, last,
lowest and highest, which a bucket keeps.
→ [record](adr/0098-a-series-view-is-drawn-over-a-window.md)

### ADR-0099 — A status that still holds says since when

The Time card and a node's Copy document state a status that still holds *since* its
start, read from the kept table where its row has left the log, and when it was *last
observed*; History's current row reads *current*. A node above others states first the
period of what it shows, then its own status's, named so. A period is a run of events
that show one status: a pin's edit is none, and a period a pin's end began says so. A
first reading is a bound, *since before*, kept until the node changes; no gap ends a
period. A node is observed, not checked; the `file` check writes a long age in days; a
run's log line adds a roll-up unlike its own code. → [record](adr/0099-a-status-that-still-holds-says-since-when.md)

### ADR-0100 — System is two views: what is running, and what is installed

Tabs beneath one heading, as a node's views are. *Running*, `/system`: which instance
this is, the engine's figures and the schedule, polled. *Installed*, `/system/installed`:
check types, packages, extensions, identity and the policy, settled at startup, and the
loggers' levels; not polled, every section open under an index. The schedule is a row
per check — its type and what it is reached through beneath its path — with *Declared*,
the type's estimate, beside *Seen*, the heaviest record the last run carried.
→ [record](adr/0100-system-is-two-views.md)

### ADR-0101 — The Events page is filtered by its URL

`under`, a node and everything beneath it; `tag`, the nodes that carry one; `words`, each
found in the reason; a switch per status an event moved to, *reached* and *held back*
apart from them, and one per kind of cause — a reading, a pin, a removal; and the Series
view's window, with its bar. Nothing remembers a filter, and held-back rows stay shown
by default — what the log keeps is retention's. A line counts what matches in the
window, an empty table says which empty it is, and *reset* is `/events`.
→ [record](adr/0101-the-events-page-is-filtered-by-its-url.md)

### ADR-0102 — A readings table keeps time and names in view; a quiet log says what it means

A readings table is a box as wide as the page and about as tall as the window, its
heading row and Time column held while it scrolls both ways, every reading on the page.
A declared measure heads its column by label and unit over the field's name, and the
declared columns lead. A node above others has two tables of periods, of what it shows
and of its own status. Where the log holds no change, History says it declares nothing
of its own, or shows the period that holds, begun when the kept table says or *before*
its bound. → [record](adr/0102-a-readings-table-keeps-time-and-names-in-view.md)

### ADR-0103 — The Series index says where each link leads, and names each node once

A node's name opens its Status page, and each row ends with *curves*, its Series view
where a curve stands at or beneath it, and *readings*, its History page. The Curves
column counts the curves a node's own series draw, the labels folded behind the count.
A root appears once: its heading is its own row, the nodes beneath it indented.
→ [record](adr/0103-the-series-index-says-where-each-link-leads.md)

### ADR-0104 — A pin is one block on what it holds, and it is edited there

One block states a pin wherever one shows — who, until when and what is left, the note
in full, *Edit* and *Clear* for an admin, on the wall its note behind a mark and *Edit*
a pencil — and where it stands says what it covers: a node's frames its lines, a line's
hangs beneath it, and a pin above a node is stated on its page too, without buttons. A
pin is set and edited in place, on a node's page, *Handled* and the wall, whose refresh
waits for an open editor; an edit shows the expiry it would keep, and one that changes
nothing writes nothing. The block is a rule's: maintenance's, *seen*'s (ADR-0142), and
without buttons a configured rule's (ADR-0137). → [record](adr/0104-a-pin-is-one-block-on-what-it-silences.md)

### ADR-0105 — A page is laid out at its screen's width, and is no wider

Every document declares its viewport, so a phone lays a page out at its own width, and
no page is wider than its screen: a table stands in a box that scrolls it, the band's
filters, trail and title and the wall's strip take another line, and a name with
nowhere to break breaks inside itself. On a phone a reason in a scrolled table keeps a
line's width, and a box keeps its place over a poll. Below 576 pixels the rail gives
way to the top bar's layout, the preference untouched. A browser emulating a phone
measures every page, and the gate holds the declaration and each table's box.
→ [record](adr/0105-a-page-is-laid-out-at-its-screens-width.md)

### ADR-0106 — A subject with a history has a node of its own, and a run is a mark at its own time

A subject that one of several measurements names has a node of its own — a status, a
path and a pin — whether or not it is well; a finding stays a line. A node whose lines
name one subject and no other stands for it: a type hands back a node where it handed
back a line, and the check API does not move. Its type says where it hangs and names it
as its provider does; the series, keyed by the subject, survives a rename. A run is a
mark at its own time on the view's shared axis — a tick, or a stem to its value with a
failed run also in the lane beneath. The API reads a series at the Series view's URL.
→ [record](adr/0106-a-subject-with-a-history-has-a-node-of-its-own.md)

### ADR-0107 — An event is a change of what a node shows

The log records every change of what a node shows — a reading's, its pin's, a line's
pin set or ended — and nothing for a line by itself. A change of the reading the node
does not show is a row of its own, held back as `maintenance` — also where only some
lines are pinned — or as `aggregation` where a configured rule counts its lines
otherwise; a run that does both writes two rows. An event carries its cause and what
the check reported, which the restart and the count of changes read. A restart replays
nothing: the first reading is compared with what the log last showed and reported.
→ [record](adr/0107-an-event-is-a-change-of-what-a-node-shows.md)

### ADR-0108 — The wait before an escalation counts what a node shows

The counter that makes a node wait before it escalates counts the node's own status —
what it shows, as the snapshot derives it and the log records it — and no longer the
code its check reported: a pinned line's readings neither spend a wait nor restart
one, and the hold a node states is about the status it shows. A change that a pin
made, set or ended, is published at once; only a reading starts a wait.
→ [record](adr/0108-the-wait-before-an-escalation-counts-what-a-node-shows.md)

### ADR-0109 — A node says its children are complete, and one it no longer returns is removed

A node in a result may say `children_complete=True`, and only then is a direct child it
no longer returns removed, at once; a result that says nothing keeps what it leaves out.
A removal takes the node and nothing kept about it: its readings stay until the ceiling
forgets them, its history is the log's, and a pin on it — held against its path, making
no node — is suspended until the node returns or the pin expires; a seen ends with it.
Each node removed writes an event with the cause *removed*, the first run after a
restart too, which the Events page can hide; a series no node stands for is listed on
its check's History page. → [record](adr/0109-a-node-says-its-children-are-complete.md)

### ADR-0110 — What every node last showed is kept beside the log, and a wait counts from it

A node's first reading in a process is counted from what the node last showed: a failure
a restart finds waits like any other, one that stood stays published, and a wait under
way at a stop goes on. The event log carries, beside its rows, what every node shows,
what its check last reported, what a waiting node publishes and when its period began —
a node above others the period of what it shows too, a pin the tree did not see set its
creation — so a quiet node writes no *undefined → …* at a restart and keeps its *since*.
A file written before is read by its rows; an entry goes when no check covers its node.
→ [record](adr/0110-what-every-node-last-showed-is-kept-beside-the-log.md)

### ADR-0111 — A run's mark says how the run stood, and a grading may say it for the record alone

A run's mark says how its reading stood: a short tick or a filled head for a pass, the
warning's triangle, a hollow ring in the failure ink, and a bare mark in the muted ink
for a run that kept no verdict, which claims nothing. Every run is drawn where it ran,
and in a crowd a passing run's head gives way. A mark is for a record with an identity;
a state has none. The summary counts the runs and what did not pass, by kind. A grading
says how a run it does not show stood in `for_record`: the reading keeps that line's
code and sentence, and no node sees it.
→ [record](adr/0111-a-runs-mark-says-how-the-run-stood.md)

### ADR-0112 — Our own stylesheet and scripts carry their content hash, and an open page notices when they moved

Every URL built for one of our stylesheets or scripts carries eight hex digits of the
file's SHA-256, and is answered as something a browser may keep for good; pictures keep
their plain names. A page that refreshes itself states one digest of the whole set, the
registered packages' assets among them, and every part it fetches states the server's:
where they differ the page loads itself afresh — after an open editor closes, and once
for a digest.
→ [record](adr/0112-our-own-assets-carry-their-content-hash.md)

### ADR-0113 — A measurement reads what its check kept, and a grading does not

A check's measuring half reads the window of one of its own subjects, `kept(subject)`:
every kept record as the store holds it, as copies, and no other check's. It is for
deciding what to ask a source that keeps a history, and a record stays a fact about the
world. It answers nothing where the check keeps no series or nothing bound it, and under
the engine only while its own check is measuring: a grading reads what it is handed and
fetches nothing. Additive; ADR-0087 decision 7 is amended.
→ [record](adr/0113-a-measurement-reads-what-its-check-kept.md)

### ADR-0114 — A curve is seen small beside its name, from zero, and the Series tab counts its curves

A sparkline is the curve's own plot with nothing around it, on the curve's scale — from
zero — and broken where the curve breaks; beside it stand the newest, lowest and highest
value. The Series index draws one for each curve in a row's fold, writing no instant.
A node's Series tab carries the number of curves its view draws, and none where it
draws none.
→ [record](adr/0114-a-curve-seen-small-and-the-series-tabs-count.md)

### ADR-0115 — A Copy document says where it is from, when it was made and since when

Every Copy document names the page it was made from — a node's its handbook too — and
the instant it was made, and each finding says since when it has stood. The tree's
document has a head and a count, also where nothing needs attention; an outline says
what a branch itself holds, and a branch's document hands over what is beneath it, the
period of what it shows and what is handled there. A node's document carries its
details, its tags and its newest note, and writes a handbook link and `{error}` out.
Copy is a tab on every node's views, a period is stated wherever there is one, and Copy
Rich HTML copies through the copy event where a page has no clipboard interface. → [record](adr/0115-a-copy-document-says-where-it-is-from-and-since-when.md)

### ADR-0116 — A path with no node has one page, and it says what is known of the path

`/status/<path>`, `/series/<path>`, `/history/<path>` and `/copy/<path>` with no node
at the path answer `404` with one page, under the breadcrumb and without tabs; the part
an open Status page refreshes is still `200`. The page says what the event log, the pins
and the notes know: the removal, with when and why and a link to its rows on Events;
every pin held against the path or beneath it, edited there by an admin; the notes
written for it and beneath it; and the nearest node above that stands, where the kept
readings of a removed subject are listed. Nothing else is stored for it.
→ [record](adr/0116-a-path-with-no-node-says-what-is-known-of-it.md)

### ADR-0117 — A measure says where its axis reaches

`axis_to` is a key of a measure's entry in `measures:` and in a type's
`measure_defaults`: the value axis of its curve and its sparkline reaches there
whatever the readings are below it, so two of one kind compare. A reading above it
grows the axis as before; nothing is cut off or refused. No lower end is declarable,
and a value that is not a positive number refuses the load. The library's own
percents of a whole declare 100.
→ [record](adr/0117-a-measure-says-where-its-axis-reaches.md)

### ADR-0118 — A child a run names says so, and takes nothing declared for its name

`CheckResult(dynamic=True)` says that a node is named by its source, or by what a
deployment's configuration calls a thing, and not by its type's code. Nothing declared
for a name reaches it — neither the type's `subnode_defaults` nor the deployment's
`subnodes:` block — and its labels are the `title` and `about` its own result carries,
with its `show_when_quiet` unless its parent's `children:` says it (ADR-0128);
`nodes.yaml`, by path, still beats them. It is said of one node and of none beneath it,
a root ignores it, and a result that says nothing is read by its name as before.
→ [record](adr/0118-a-child-a-run-names-takes-nothing-declared-for-its-name.md)

### ADR-0119 — A wait that ends by its count writes a row

The reading that completes a node's wait writes a row: the status the node shows,
unmarked, by the cause `reached` — a chip on Events, where the page with *held back* off
lists what alarmed and when. It begins no period and counts as no change. A wait that
ends another way writes its own row or none, and one behind a shield none. The kept
table says what a waiting node `publishes`, and a wait under way at a stop goes on after
the restart, counted from its held row.
→ [record](adr/0119-a-wait-that-ends-by-its-count-writes-a-row.md)

### ADR-0120 — Every stored time is an instant

A node's, an event's and a pin's times are instants held in UTC: read from one clock,
spelled `…Z` by one function in both state files and the API, compared as instants, and
ruff's `DTZ` rules refuse one built without a zone at the gate. A state file that
carries a time without a zone is refused whole and starts empty, an older version's too:
nothing migrates. A check type hands over a time with its zone; `spans.local_time`
refuses one without. Options stay in `config/settings.yaml`: `timezone` and
`time_format` write a page's times, and that zone reads a typed expiry and stamps the
log, with its offset. → [record](adr/0120-every-stored-time-is-an-instant.md)

### ADR-0121 — A noise cap is declared by the package that brings the noise, and `LOG_LEVEL` has the last word by name

`little_sister.noise.cap(logger, level, hides=…)` declares a row and sets no level: a
dependency's logger at `INFO` or `WARNING`, never the root nor the library's own. The
default sets the rows once, where the application is imported, where that takes lines
away and nobody chose: `LOG_LEVEL` does not name the logger or one above it, and no
level that no row set stands on it or on a named logger above. `LOG_LEVEL` is a list,
`INFO,botocore.credentials=DEBUG`, read after `.env`; an entry speaks for its name and
all beneath it. `/system/installed` says every level. The cap on `httpx` leaves.
→ [record](adr/0121-a-noise-cap-is-declared-and-log-level-has-the-last-word.md)

### ADR-0122 — A series is read over the API as it stands: its node, its key, its measures as drawn, its readings

`GET /series/<node_path>` and `GET /series`, asked for JSON with a bearer token, answer
every series that stands at or beneath a node over the window `from` and `to` name: its
`node`, its `key`, its readings whole and oldest first, and its measures as the page
draws them — one for every key the kept readings hold, only those at or beneath the
node asked. A node that stands answers a list, empty where none stands; `404` is a path
no node stands at, `400` a window that cannot be read. Its first reader is a script or a
session reading a running instance, and `test_api.sh` takes a path. One answer is
written down, `series-3.json`. → [record](adr/0122-a-series-is-read-over-the-api-as-it-stands.md)

### ADR-0123 — A node says one status wherever it is read

The head of a node's page says what its card says one page up: what the node rolls up
to. Whose a status is, the snapshot says — what a node counts for itself, a stale
reading of its own degraded, and whether what it shows is derived from beneath it — and
a head, a card and a box are pale by that. A node above others keeps two periods, of
what it shows and of its own status, and no row is written for a node when one beneath
it changes: its Time card says the first, naming the node beneath that makes it so, and
names the second *its own status*, as History and the Copy document do.
→ [record](adr/0123-a-node-says-one-status-wherever-it-is-read.md)

### ADR-0124 — A node whose lines are all in maintenance still counts the nodes beneath it

A node whose lines are all pinned has an own status of `MAINTENANCE` that counts
nothing and cancels nothing: the nodes beneath it count, it shows what they roll up to,
and it reads `MAINTENANCE` whole only where nothing beneath it counts either. What
cancels a subtree is a pin on the node or its check's word for it, said by one
expression the roll-up and the snapshot share. Its head and its card say what it rolls
up to, its Time card names its period its own, and its Copy document says that every
line of its own is in maintenance.
→ [record](adr/0124-a-node-whose-lines-are-all-silenced-still-counts-the-nodes-beneath-it.md)

### ADR-0125 — The failure retry reads what a run rolls up to

What arms the failure retry is what the run rolls up to — its root's code and every
child it returned, by ADR-0039's rules — and not the root's own code, so a branch
check whose root declares nothing retries when a node beneath it fails; an episode
ends when the roll-up changes, and a run that rolls up to `UNDEFINED` arms nothing.
It is read of the result, not the node, so a pin cannot reach it, and
`retry_interval: 0` on one check stays the switch for an estate too expensive to
read twice.
→ [record](adr/0125-the-failure-retry-reads-what-a-run-rolls-up-to.md)

### ADR-0126 — A line is a template over its record, and a deployment may re-word it

A line that carries a record is rendered once, where the grading hands it back
(`Check.line`): the form the grading names, over the record's fields and the words it
hands over under `line.`, which are never stored. It is Markdown, links included; a
segment leaves out what is absent, and nothing else is logic; a time reads in the
configured zone. A type declares its forms, words and fields, a deployment re-words a
form in the check's `display:` block, an undeclared name stops the start, and an entry
names its form. → [record](adr/0126-a-line-is-a-template-over-its-record.md)

### ADR-0127 — The wall is a tree: a node is closed or open, and a click changes which

Every node on the wall and its pages is a chip — its state's cue, its name and its
counts, a branch's own failure among them — or a box; a click changes which where it
stands, a level keeping its order, and a top-level card closes to its head in its place.
An open head's icons and actions stand where a look puts them. Three failures to a card
open their way past chips unless a browser keeps them shut; `branch_cap`, depth and the
chips switch go, and a tag filters the wall. What a viewer opens is a map of what
differs, kept for the tab and put back after every refresh; chip runs line up in
columns, or wrap where a browser says so. → [record](adr/0127-the-wall-is-a-tree-and-a-click-opens-or-closes-a-node.md)

### ADR-0128 — Where a node's first look comes from: `chips`, `fold_ok` and `reason_cap`

Three keys per node — whether its children start as chips, whether its healthy ones
start folded, its line budget — resolved most specific first: the viewer for the tab,
`nodes.yaml` by path, the check's file, the type's declaration, `settings.yaml`, built
in (open, healthy shown, a level that would draw over thirty boxes as chips). They ride
the labels' addresses and `children:`, which reaches a level a run names;
`show_when_quiet` stays a key of its own there. They are the web page's settings, never
on the snapshot, and the planner prices the first look they give.
→ [record](adr/0128-where-a-nodes-first-look-comes-from.md)

### ADR-0129 — A rule list is the library's, and a value matches it exactly

A package's rules are the library's rule list: in order, the first match deciding, a
required `name:`, `ignore:` an action refused beside the package's own keys, a key
nobody takes stopping the start. A package declares its axes — named, or one on the
rule — and whether a value can be absent, which `unnamed: true` matches. A value
compares exactly: no case folded, a regex matching the whole value. A rule that matched
nothing is an `INFO` line naming the rule above that decided its value, or a near miss
in case; a line a rule's own keys judged carries the word `rule`. → [record](adr/0129-a-rule-list-is-the-librarys-and-a-value-matches-it-exactly.md)

### ADR-0130 — A unit has a period of its own, and a run stamps only what it answered for

A type declares its units — a key, a period, the node each answers for — and measures
one at a time (`units()`, `measure_unit`); a check that declares none is the one-unit
check. The period is `frequency:` in the unit's own block, else a cadence the type
declares, else the check's. The engine releases units, grades the whole check over the
newest reading of every unit, and writes the unit's own path alone — the containers
above it and the node it answers for — leaving a sibling what its own unit wrote. Run
facts, tolerance, retry and cost are per unit; a unit runs at start, and is never armed
from the series. → [record](adr/0130-a-unit-has-a-period-of-its-own.md)

### ADR-0131 — A type declares what it grades, and the library grades it

A type declares every value it grades — a map from a word to a code, a pair of levels
over a number, a set of accepted values, a window over its kept records — with its
default and the key a deployment writes, and the library reads, refuses, lists and
applies it, handing the line its `reason`. A pair is `<name>_warn` and `_error` beside
`<name>_reason`, `null` switching it off, passing at its level, `max_` above and `min_`
below; a map folds its words and logs a key no word matches; a rule writes what its
block grades; a window is handed to the seam cut at the reading, `since` first.
→ [record](adr/0131-a-type-declares-what-it-grades-and-the-library-grades-it.md)

### ADR-0132 — A branch keeps the period of what it shows beside the log

Every node above others, the root included, keeps beside the log the period of what it
shows — since when, what came before, what moved it and the node whose change it was —
written at every change of what it rolls up to, staleness included, and never as a row;
a run's store holds the tree's lock whole and is compared once, and a restart carries
each node at its entry until its unit has run. The Time card says that period, History
lists it above the own status's, and the envelope carries `period` beside `code` and
`own_period` beside `own`.
→ [record](adr/0132-a-branch-keeps-the-period-of-what-it-shows-beside-the-log.md)

### ADR-0133 — A node says what it is in a card, and at length in a handbook

A node's short account stands in a card, *About*, beside its facts on its Status tab:
its `description`, what the check reads; its `about`, where the thing stands, how to
reach it and what to do; its `details`, named values a team keys — the type's per run,
the deployment's given down key by key, the nearest winning. At length it has a
`handbook`, text or a file from the `about`'s sources, on a tab at `/handbook/<path>`
that a text links as `handbook#<section>`; `{error}` and its kin are drawn as signs.
Copy and the API point to the handbook and carry the details.
→ [record](adr/0133-a-node-says-what-it-is-in-a-card-and-at-length-in-a-handbook.md)

### ADR-0134 — The state is compressed and stamped, and a keeper takes it in two cadences

The event log and the series are written as `events.json.gz` and `series.json.gz`,
compact JSON under gzip at level 1, fixed; `events.json` and `series.json` are retired,
a clean break that starts both empty once at the upgrade. Every file carries a
`generation` — writer, count, held — and at a start a local copy newer by the same
writer, written holding, wins over the store's. Pins go to the keeper as they change;
the observed state every `keeper_interval` (900 s) while nobody stands by, every interval
while anyone does, and at once at a flip, a stop and an action, run between two flushes.
→ [record](adr/0134-the-state-is-compressed-and-stamped.md)

### ADR-0135 — A handled part keeps its true color, and every surface says by what

Every part keeps its true color under the mark of the rule acting on it — ‖ maintenance,
a ringed check accepted, a bell struck through silenced, § a configured rule — and what
it counts as shows one level up; maintenance alone paints blue, in words of its own. On
the wall a block says its sentence, its note opening from a mark in a card, *Edit* a
pencil and *Clear* in the editor, its edge dashed and its fill only where its rule
paints. A closed chip says what is handled beneath it as ◇ and a total, a branch why it
has its color after Time, and every rule stands in one index, *Handled*, at `/handled`.
→ [record](adr/0135-a-handled-part-keeps-its-true-color-and-every-surface-says-by-what.md)

### ADR-0136 — How the wall is used is one file the package ships, read at `/help`

One Markdown file, `src/little_sister/help/using-the-wall.md`, says what a viewer sees on
the wall and what a click does — chips and boxes, the band, a head's buttons, a node's
tabs, what is handled, each group of the settings menu, the kiosk. The package ships it,
the page draws it at `/help` as a handbook is, its headings anchored, and the settings
menu's foot links it, in the room the last column leaves; the README and the
specification point to it, and a test holds it to the menu it describes.
→ [record](adr/0136-how-the-wall-is-used-is-one-file-the-package-ships.md)

### ADR-0137 — A deployment says in a table how a part of its tree counts above it

`config/aggregation.yaml`'s rules, every root's read, the last-named first, each named,
noted and dated: a table per status that never reorders — the cap, healing, the floor, a
part left out — at the top of a part `under:` or `tag:` picks, on its nodes' lines, or
over its children while fewer than N fail; the first written for a place decides, whole.
The table comes last, after damping, and never beneath staleness; `/little-sister` is
out of reach; what cannot apply is named at the start. Every part keeps its true color
under §, and `contribution.by` says `aggregation`, on an entry too (2.11.0).
→ [record](adr/0137-a-deployment-says-in-a-table-how-a-part-counts-above-it.md)

### ADR-0138 — A viewer may pack a level's boxes into its columns

A look, `boxes`: `rows`, the library's, ADR-0056's rows, or `packed`, each box of a grid
of open boxes beneath the shortest column — the leftmost within 32 pixels — so that a
tall box leaves no gap beside it, a run of chips in one column as a box, and the plan
priced for packing. A node takes its column when the page is drawn and when its level's
columns change, and keeps it as a box and as a chip through a refresh, a click and its
own growth; a packed wall is shown once drawn; the page's order stays the source's.
→ [record](adr/0138-a-viewer-may-pack-a-levels-boxes.md)

### ADR-0139 — A node carries every tag written for it or above it

A tag is a word a deployment writes for a node — a fact about the subject, never its
status — in a check's file, its `subnodes:` block or `nodes.yaml`, and a node carries
every tag written for it or above it, added up, and never one from beneath. `tags.yaml`
names the known tags, each with what it means. The *About* card shows them as chips, a
wall filtered by one draws the tagged parts as its cards, `tag:` picks for the rules,
the actions and the Events page, and the envelope carries `tags` (2.12.0).
→ [record](adr/0139-a-node-carries-every-tag-written-for-it-or-above-it.md)

### ADR-0140 — A node's notes stand on a tab of their own, and its hand-off carries the newest

An admin writes a note of its own on a node or on one of its lines, changed while it is
the newest; a pin's note joins the same notes as the pin is set. *Notes*, a tab after
History with its count, lists them newest first with what the node showed then; a
line leads there too, a node's Copy document carries the newest, and the page of a
path no node stands at lists its notes. `reason` became `note` in the model, the form
and `pins.json` at once; the notes are `var/state/notes.json`, retired on the tick.
→ [record](adr/0140-a-nodes-notes-stand-on-a-tab-of-their-own.md)

### ADR-0141 — Every pin is one thing with a kind, in one file, and the envelope lists what handles a part

Every pin a person sets is one thing with a kind — maintenance and *seen* so far — in
one list, `var/state/pins.json`, beside its node's path or its line's, with an id of its
own; `maintenance.json` is retired, a clean break that drops the pins standing at the
upgrade. The envelope is at `schema_version` 3: `handled` lists every pin and every
acting configured rule on a part, `contribution.rule` names the one that decided, and
`maintenance` is gone. Each act has a route and a permission named for its kind,
`Identity.may(<act>)`.
→ [record](adr/0141-every-pin-is-one-thing-with-a-kind-and-the-envelope-lists-what-handles-a-part.md)

### ADR-0142 — A failure marked seen counts as OK above until it changes

A person who has looked into a failure marks it seen with the ringed check: a pin of the
kind `seen` on a line or on a node's own failure, bound to the status it was set at and
to its occurrence — the field a type names as `occurrence=`, else its reading's
identity, else the failing stretch. Its part keeps its color and counts as OK above. It
ends at a recovery, a worsening, a new occurrence, when its part is no longer reported,
at an end it was given or by hand, each end a row saying why. A head's ✓ marks every
failure at and beneath it, each its own.
→ [record](adr/0142-a-failure-marked-seen-counts-as-ok-above-until-it-changes.md)
