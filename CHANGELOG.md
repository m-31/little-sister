# Changelog

All notable changes to little-sister, newest first. The format follows
[Keep a Changelog](https://keepachangelog.com/); releases are cut with the release
pipeline ([ADR-0022](docs/adr/0022-generated-release-branch.md)), which rolls the
**[Unreleased]** notes below into the tagged version. The JSON API
contract versions **separately** — see `docs/api/openapi.yaml` `info.version`.

## [Unreleased]

## [0.3.16] - 2026-09-06

**Breaking — the JSON API is `schema_version` 2, and nothing about a node is
compatible with version 1.** The envelope is now the snapshot the dashboard renders,
rather than an older and smaller projection of it: `own_code` is `own` and `reported`
joins it, `contribution` says what a node's parent counted and which rule made it so,
the string array `reasons` is the `entries` object, the `maintenance` bool and
`maintenance_details` are one nullable `maintenance` object whose text is `note`, and
the nullable `timestamp` with `frequency_seconds` beside it is a `run` object that is
**absent** where nothing answers for a node. `report`, `order`, `show_when_quiet` and
an envelope-level `instance` block are new. Nothing else in this application changed:
the pages read the same snapshot they always did. Update a client in the same step —
the macOS app is released with this version — and read
[`docs/api/openapi.yaml`](docs/api/openapi.yaml), which is normative and now 2.0.0
([ADR-0080](docs/adr/0080-the-envelope-is-the-snapshot-published.md)).

### Added

- **`run.stale_after_seconds`, the freshness tolerance the server applied.** The
  snapshot now carries the number the staleness rule measured against — roughly two
  intervals — and the API publishes it, so a client can say how fresh a reading is
  meant to be without holding a second copy of a rule that is about to grow a branch
  ([ADR-0079](docs/adr/0079-freshness-is-a-stated-tolerance.md)).

- **Two records that decide how a check with more than one thing to read will
  behave**, taken before the JSON contract is rewritten because each turned out to be
  a field of it. **Nothing in this release behaves differently**: both describe a
  scheduler that is not built yet, and both are written so that a check type which
  says nothing keeps working exactly as it does today.
  [ADR-0078](docs/adr/0078-the-unit-is-what-the-engine-releases.md) makes the **unit**
  what the engine releases — a type may say what it reads, one key at a time, and a
  check that says nothing is a one-unit check. It is additive, so the check API epoch
  does not move and no installed package has to be re-released.
  [ADR-0079](docs/adr/0079-freshness-is-a-stated-tolerance.md) settles what *stale*
  means for a check with no interval: the tolerance a deployment **states**, never one
  the engine derives from how much there is to read — a derived tolerance grows with
  the estate, and green would stop meaning freshly verified exactly when the estate
  outgrew what can be read.
  [ADR-0005](docs/adr/0005-dashboard-freshness-and-self-monitoring.md) carries an
  update saying its rule is the one for a check that has an interval, which is every
  check that exists.

### Changed

## [0.3.15] - 2026-09-05

**Breaking, before the first release with a self-report:** every maintenance pin set
on `/little-sister` holds nothing after this version. The instance's node is a
branch now — one child per contributor — and a line lives on its contributor's child
under its own slug: what was `/little-sister` + `engine.lag` is `/little-sister/engine`
+ `lag`, `state.load.maintenance.json` is `/little-sister/state` + `load.maintenance.json`.
Set the pin again on the child. No migration is written; no released instance has
such a pin ([ADR-0076](docs/adr/0076-the-instance-node-is-a-branch.md)).

### Added

- **Authority follows the lease: an instance that takes a keeper's lease over
  adopts what the store changed while it stood by.** Whoever holds the lease wrote
  the truth up to the moment it lapsed, so a standby that becomes the holder — or a
  demoted holder that takes the lease back — no longer writes its own hours-old pins
  over the store. A state file gains the other direction: `keep(name, producer,
  restore=…)`, or `restore_with(name, restore)` for a file written through, registers
  a callable that takes the parsed payload of an adopted copy and replaces what the
  running process holds — the pins and the event log both have one. The keeper seam
  gains one optional method, `changed_since_sync() -> Sequence[str]`: the files whose
  copy in the store differs from what this instance last restored or saved, by a token
  the library never sees. At the moment the keeper's `tick` turns from declining
  saves to taking them, every file it names is adopted before the first save — parsed
  and handed to its `restore`, then the live file set aside as `<file>.bak` (an older
  one overwritten) and the store's copy written in its place; a keeper that names
  nothing, or has no such method, makes it a silent takeover with the instance's own
  state, which is what every takeover was before. A file whose adoption failed —
  one key of three unreachable — is held out of the mirror until one lands and
  retried every interval, so the interval's saves never put a standby's shadow over
  the store. A `.bak` is this machine's own and is never mirrored, and a keeper that
  lists one is refused as it would be for a path outside the directory.
  `/little-sister/state` lists every `.bak` beside its live copy
  with both ages as uncoded `backup.<file>` lines, and offers **take the backups** —
  admin-only, `POST /little-sister/state/act/take-backups` — which sets the live
  files aside as `.bak` in turn and adopts the backups through the same path; a
  `.bak` matching no file the layer keeps is listed and left alone. A copy the process
  cannot take in, or a disk that refuses it, is the `load.<file>` ERROR line with
  *adopt* as the verb; a file with no `restore` a WARN saying it was swapped on disk
  only. Found on the way and fixed beside it: the first flush after a
  restore from a keeper no longer sends every restored file back once
  ([ADR-0077](docs/adr/0077-authority-follows-the-lease.md); the S3 keeper's half —
  the ETag per key, *take the lease, then adopt, then save* — is `little-sister-aws`'s
  next slice, and until it ships every takeover is the silent kind).

- **The instance's node is a branch, and a package may offer an action on its
  child.** `/little-sister` carries the beat; `/little-sister/engine` the engine's
  own lines; `/little-sister/<name>` every registered contributor's — present and OK
  when it has nothing to say, its code the worst of its lines, the root's the
  roll-up, which is what the status strip shows before it links to the page. A
  contributor declares its child's `title` and `about` at registration
  (`nodes.yaml` still wins), and the library's own six say what they are. A pin
  lands on one speaker or one line of it, and the event log records a transition
  per child. New on the seam: `self_report.register_action(contributor, slug,
  label, handler)` — an admin-only button on the child, run by
  `POST /little-sister/<contributor>/act/<slug>`, answered on the page it came back
  to, rendered through the slot seam beside the declarative chips, and followed by
  a flush of the state layer, so what the action changed reaches the store in the
  click rather than at the next interval. The first two
  are the S3 keeper's *take over* and *release*, in `little-sister-aws`
  ([ADR-0076](docs/adr/0076-the-instance-node-is-a-branch.md); the strip decision of
  [ADR-0056](docs/adr/0056-stable-useful-dashboard-flow.md) lifts the branch with its
  children).


- **A check type can say what it costs, and startup adds it up.** A type may now
  answer `expected_cost()` — the worker seconds one run of *this* configuration is
  expected to occupy — and `expected_entries()`, both computed from its own settings
  and both optional. At startup the engine sums **what is declared**: each cost over
  that check's own frequency against `max_workers`, and the entries against
  `entry_limit`. Past either it refuses to start, naming the largest contributors
  with their numbers, and the pages stay up with the *engine not started* banner
  saying why; at 80 % of either it warns in the log and carries an uncoded
  `capacity.threads` / `capacity.entries` line on `/little-sister`. Until now a
  configuration that could not be served was discovered by being served badly — the
  pool saturating, every check late, and nothing anywhere saying the arrangement was
  impossible.

  A check that declares nothing costs nothing in these sums, which is why they refuse
  the impossible and promise nothing about what passes; the library's own built-in
  types declare nothing, because an `http` check's fraction of a second is noise in
  such a sum. Declare an **estimate of a normal run** and never a bound — a type that
  declares its timeout will refuse deployments that have been running for months —
  and a declaration that raises or is not a non-negative number is logged against the
  check's path and ignored rather than stopping the start. `/system` shows what each
  check declared beside the wall time it actually took, and the sums beside the
  entries the tree holds now
  ([ADR-0075](docs/adr/0075-a-check-declares-what-it-costs.md)).

- **Three engine limits are settings.** `config/settings.yaml` gains `max_workers`
  (the worker ceiling, default 8 — also what declared costs are measured against),
  `entry_limit` (default 100,000, the number the engine's own `entries` line watches)
  and `memory_share` (default 0.5, the share of what the machine gives the process
  before the `memory` line turns red). They were constants; raising `max_workers` is
  how a deployment answers a refusal it disagrees with. A bad value falls back to the
  default with a warning, like every other setting.

- **This instance has a name.** `little_sister.instance` answers with one mark for
  the life of the process — `<name>:<pid>:<started>:<tag>` — and `/system` says which
  installation this is, in a section of its own, first. Until now nothing in the
  library named the running process: that page listed what was installed and never
  said which instance had installed it.

  `name` is yours, from `instance:` in `config/settings.yaml`, and the **hostname**
  where you say nothing — which in a container is already the task or pod name. A
  name that carries the mark's own separator, carries whitespace, or runs past 64
  characters falls back to the hostname with a warning rather than refusing the
  start.

  The eight random hex characters at the end are not decoration: they are what makes
  an **equality test** on the mark sound, and without them two containers of one
  deployment — one name, pid 1, started in the same second — could hold one mark and
  read each other as themselves. So a name of your own is safe to give: the
  uniqueness is the library's and you cannot take it away.

  The mark is **never parsed**. Two things are promised, and a package keeping state
  outside this machine depends on both: no two processes share a mark, and one
  process's does not change while it runs
  ([ADR-0074](docs/adr/0074-this-instance-has-a-name.md)).

- **A readiness answer beside `/health`.** `GET /ready` answers *has this instance
  finished coming up*, which `/health` deliberately does not: `200 {"status":
  "ready"}` once an identity door is registered, the machine's trust store holds CA
  certificates and the engine has run every configured check once, and `503
  {"status": "not ready", "waiting_for": [...]}` until then — from the closed
  vocabulary `doors` / `trust` / `first-pass` and nothing else, three words that name
  no path, count, version or configuration and answer the one question the caller of
  an unready instance cannot answer for itself: **wait, or roll back**. The answer
  **latches** — all three are startup facts, so the route goes `503` to `200` once and
  never back, and a later failure can never withdraw a serving instance and take away
  the page whose banner explains it. An engine switched off with
  `LITTLE_SISTER_ENGINE=0` has no pass to wait for and is ready at once; one that
  could not load its configuration never becomes ready. Ungated like `/health` and
  `no-store` for the same reasons, outside the JSON API, and `/health` itself is
  unchanged — which of the two a load balancer aims at is the deployment's choice,
  `/ready` behind several instances and `/health` behind one, since draining your only
  target takes away the explanation
  ([ADR-0073](docs/adr/0073-a-readiness-answer-beside-health.md)).

- **The instance says what it cannot see.** Two failures that were silent behind a
  `200` and a `running` engine are lines on `/little-sister` now, on the self-report
  seam and clearing when their condition does. `readiness.trust` at **ERROR** — *the
  machine's trust store holds no CA certificates* — is a container built without its
  distribution's CA bundle, where every check reading an `https` address fails on the
  certificate rather than on the subject and no node says the fault is local.
  `readiness.all-erroring` at **WARN** — *every check this instance runs is erroring,
  all N of them* — is the pattern no single node can report: N failures are more likely
  one cause than N, and it stays at WARN because the failures are already ERROR where
  they belong and because the world may simply be down. It needs more than one check,
  since with one it would say nothing that check's own node does not
  ([ADR-0073](docs/adr/0073-a-readiness-answer-beside-health.md)).

- **What a restart keeps is a directory of files: `var/state/`.** The event log
  survives a restart now. It is written to `var/state/events.json` at most once per
  `state_interval` (`settings.yaml`, default 60 s) and once more at graceful
  shutdown — an unclean shutdown loses at most the interval — and read back at
  startup, so `/events` and every node's history start where the last process left
  off; the first run after a restart still records `UNDEFINED → OK`, because the node
  *was* unobserved. Every write is a temporary file and `os.replace`, the discipline
  the maintenance file always had, and a kept file whose state did not change is not
  rewritten. **A failure never refuses to start, and is never silent**: a file that
  cannot be read starts that state empty and is a line on `/little-sister` at ERROR
  for as long as the process runs (*what it held before the restart is not in
  force*); a write that fails keeps the state in memory and is a WARN line until a
  write succeeds. Nothing that is a service enters the core — a store per record and
  a **keeper** that mirrors the directory to somewhere durable (S3 first) are the
  seams a package fills, the keeper next
  ([ADR-0071](docs/adr/0071-what-a-restart-keeps-is-a-directory-of-files.md)).

- **The instance reports on itself through one seam.** Anything with something to
  say about the running instance registers a **contributor** —
  `little_sister.self_report.register_contributor(name, callable)`, in the same
  import-before-app block as a resolver, under the same claimed-once rules — and
  every scheduler tick the heartbeat carries the engine's own lines and every
  contributor's as pinnable member entries, `<name>.<slug>`, the node's status the
  worst of what they claim and OK when nothing claims anything. A report is recorded
  state, never a probe; a contributor that raises is caught and stands as one WARN
  line naming it; a line a contributor stops returning clears. The no-checks warning
  is the first of the engine's lines (`engine.no-checks`), the state layer's two
  failure lines the first contributor's (`state.load.<file>`, `state.save.<file>`),
  and `/system` lists each package's contributors beside its other seams
  ([ADR-0072](docs/adr/0072-the-instance-reports-on-itself.md)).

- **Two records on the self-report seam, so the log and the node cannot drift
  apart.** `little_sister.self_report.Standing` keeps a line for the life of the
  process — `note(slug, text, code)` writes the line and the log entry in one call
  — and the library's own, `self_report.startup`, reports under `startup`: what the
  process learned at startup and cannot undo goes there, one call site at a time.
  `Held(hold_seconds)` keeps what recurs, each occurrence for a window after it was
  seen — `see(slug, text, code, measure)` — so a line stands while the condition
  does, clears when it stops, and counts (*17 times in the last 10m*) rather than
  repeats; where an occurrence has a size, the worst inside the window is the one
  reported. The engine's `lag` line is the first on that shape, and a late tick is
  now a log entry as well as a line
  ([ADR-0072](docs/adr/0072-the-instance-reports-on-itself.md) §7).

- **What the process used to say to the log alone, it says on `/little-sister`.**
  Three contributors, on the two records: `startup` for what the process learned at
  startup and cannot undo — an unresolved `SECRET_KEY` reference (every session
  ends at the next restart) or `LITTLE_SISTER_API_TOKENS` reference (the JSON API
  rejects every request), no identity door or none the default, the system-admin
  password unresolved, a `config/` file no aspect claims, an aspect refused at
  registration or declared in two roots, `instance:` refused, `retry_interval`
  unreadable, `nodes.yaml` metadata no check covers, a links interval unreadable, an
  avatar not shown, the retired maintenance file, a slot template, asset, icon or
  action refused, the theme bootstrap's hash missing — at WARN, and at ERROR where
  nobody can sign in; `runtime` for what recurs, held ten minutes with a count — a
  slot's provider or template raising, an identity door raising, a scheduler tick or
  an upsert raising, a reachability pass failing, overrunning, stuck or giving up;
  and `security` — failed logins as a rate, a fact below five in ten minutes and WARN
  from five, and the system-admin account used. Every one is still a log entry, from
  the same call. `little_sister.reasons.plain` is `little_sister.checks.plain`,
  promised from both ([ADR-0072](docs/adr/0072-the-instance-reports-on-itself.md)
  §7).

- **The engine's own lines.** `/little-sister` now says what the engine measures
  against its limits as it runs — recorded on its side, read on the tick, never
  probed, and clearing when the condition does. `engine.entries`: the tree's entry
  count against a limit of 100,000, WARN at 80 % and ERROR at the limit.
  `engine.memory`: the process's resident size against half of what the machine
  gives it (physical memory, or a cgroup's smaller limit), the same shape, and no
  line where the machine cannot say. `engine.pool`: a check that has waited for a
  worker longer than 10 s, with how many are waiting and the longest wait — the
  first sweep, where every check is due at once, excepted. `engine.lag`: a
  scheduler tick that came more than 5 s late, standing for ten minutes.
  `engine.late.<path>`: a check whose run in flight or last run took longer than
  its `frequency`, at WARN — a late run, not a broken one. And a `timeout` longer
  than the `frequency` is now **warned about at engine construction and carried as
  an uncoded line** (`engine.may-run-late.<path>`), never refused; before, such a
  check simply ran late in silence. Every line is pinnable by its slug like any
  entry; the numbers are constants until the declared costs make them settings
  ([ADR-0072](docs/adr/0072-the-instance-reports-on-itself.md)).

- **A keeper carries `var/state/` off the machine.** A deployment that registers one —
  `little_sister.keeper.register_keeper(name, keeper)`, in the same
  import-before-app block as a resolver — has the whole directory restored from it
  **before anything reads**, and mirrored back to it after the writer, on the same
  `state_interval` and once more at graceful shutdown. So an instance redeployed onto
  a fresh machine comes up with the pins and the history it left on the old one. A
  keeper answers three methods in bytes — `load(name)`, `save(name, data)`, `list()` —
  and never knows what it carries, so it moves a package's own file as readily as the
  library's; there is **one per instance**, and a second from another package refuses
  at startup naming both. Two more it *may* answer: `tick(interval_seconds) -> bool`,
  called every interval before any save whether or not a file changed — where a store
  that holds a lease on its prefix renews it — and whose answer says whether this
  interval's saves are wanted at all; and `close()`, once at graceful shutdown after
  the last save, so a lease can be given up rather than left to lapse. **A failure
  never refuses to start**: a keeper that cannot be reached leaves every local file as
  it is and is an ERROR line on `/little-sister` for the life of the process; a save
  it would not take is a WARN line naming the file until one lands, and a `tick` that
  raises is a WARN line with no save behind it that interval. The library ships no
  keeper — a local installation registers none and loses nothing by it — and the
  first one is S3, in `little-sister-aws`
  ([ADR-0071](docs/adr/0071-what-a-restart-keeps-is-a-directory-of-files.md)).

- **`little_sister.spans.local_time(moment, fmt=None)` joins the public surface** —
  one instant in the `timezone` and `time_format` of `settings.yaml`, the rendering
  every page already used through the application's own formatter, which now
  delegates to it. Promised so that a plugin writing *when* into a line says it in
  the page's words; before, the only thing a plugin could write was `GMT`.

- **Durations know weeks: `1w`.** Everywhere a duration is written — a check's
  `frequency`, `timeout` or `retry_interval`, `maintenance_default_expiry`, a
  plugin's own duration fields, the maintenance form — `w` is seven days, and an
  interval that is a whole number of weeks reads back as one (`1w`, never `7d`)
  wherever a page shows a configured interval.

### Changed

- **A `/little-sister` child's facts are its report; every line is a claim.** A
  contributor's line without a code — *this instance holds the lease*, *the last
  transitions*, the paths searched for checks, a configuration that *may* run
  late, a `.bak` set aside, a few failed logins below the rate — used to arrive on
  its child uncoded, and an uncoded entry on a coded set carries the node's code,
  the worst of the warnings beside it: the child stayed WARN after its one warning
  was pinned, until every fact was pinned too. Facts are now the child's `report`
  (ADR-0044 decision 6) — `register_contributor(…, report=)` answers Markdown,
  shown on the child's page and never on a card — and only claims are lines, so
  pinning the one warning quiets the child and the per-line pin sits only where a
  claim is ([ADR-0076](docs/adr/0076-the-instance-node-is-a-branch.md) decision
  1). A line that arrives without a code is refused into a WARN under its own slug
  that says so; `Standing.note` and `Held.see` take a `StatusCode`, no longer
  `None`. `security_report`, `StateLayer.report` and `EngineReport.report` carry
  the moved facts. The `no-checks.searched`, `may-run-late.<check>`,
  `capacity.<limit>` and `backup.<file>` slugs are gone — nothing could usefully
  pin them.
- **Duration units are lowercase, and `M` is refused by name.** The parser used to
  lowercase the text first, so `5H` read as five hours and `6M` as six *minutes* — a
  `6M` that meant six months was a pin gone in six minutes, or an `error_max_age` of
  six. A configuration that wrote a capital unit now fails to load at startup naming
  the value: write `5h`. For `M` the refusal says what `m` is and why a month is not a
  unit here — it is not a number of seconds — and to write weeks or days instead.
- **A maintenance window has to reach the next run of the check it silences.** The
  form refuses a duration or expiry shorter than the interval of the slowest check
  the pin covers — the check on the node, the checks below a container, the branch
  check above a leaf — and names it: `'2m' ends before /payments/reconcile (every
  20m) runs again, so the pin would cover no run of it. Use at least 20m.` A pin that
  ends before the check runs again silences nothing, and once it expired the stale
  reading came back anyway. A window equal to the interval passes; a blank field
  still takes the configured default whatever the interval, because that value never
  refuses ([ADR-0014](docs/adr/0014-maintenance-persistence.md)).
- **`var/maintenance.json` moved to `var/state/maintenance.json`, and the old path is
  not read.** A deployment that upgrades moves the file before the restart or loses
  its pins — a warning at startup names the file while it still sits at the old
  path. A clean break rather than a migration, for the reason the file's shape
  change was one: runtime state the program owns, bounded by a finite expiry, and
  nothing outside the family reads it
  ([ADR-0071](docs/adr/0071-what-a-restart-keeps-is-a-directory-of-files.md)).
  `MaintenanceStore` now takes the state layer rather than a path, and a file of an
  older shape is a load-failure line on the heartbeat rather than a log warning.
- **The heartbeat's reasons are entries with declared slugs**, so the no-checks
  warning can be pinned like any other line and its status now moves — WARN or
  ERROR while a line stands, OK when it clears — with the transitions in the event
  log. A client reading `reasons` sees the same texts as before.

## [0.3.14] - 2026-08-29

### Removed

- **`config_dir.forget_scanned_roots()`.** It undid a once-per-root cache that no
  longer exists: the report on unclaimed configuration files is emitted once, at the
  app import, rather than at each root's first resolution
  ([ADR-0070](docs/adr/0070-the-unclaimed-file-report-runs-at-the-end-of-registration.md),
  and the *Fixed* entry below for what moved). A test suite that called it between
  cases has nothing left to reset and can drop the call.

### Added

- **A deployment can hand the library an identity implementation of its own.**
  `little_sister.identity.use(name, provider)` registers one as a named **door**
  ([ADR-0069](docs/adr/0069-identity-comes-from-outside-and-one-account-does-not.md)),
  in the same import-before-app slot check types, slot fillers, assets, configuration
  aspects and secret resolvers already use — because authentication is different in
  every organization, and the only honest shape is to rely on an implementation the
  library does not own. What a provider answers is **who is this request**
  (`identify()`) and **what does an unidentified one get** (`challenge()`); a login
  flow is four *optional* hooks reached at library-owned routes (`/login/<door>`,
  `/auth/callback/<door>`, and `/logout`), so a provider sitting behind something that
  has already completed the exchange — a load balancer injecting a signed header —
  implements the two required methods and nothing else, and a provider never registers
  a route of its own. **Several ways in are allowed; an ordered list of them to try is
  not**: `sign_in()` records which door produced the session and `current_user()` asks
  that provider and no other, so registration order can never decide who somebody is —
  which matters here more than in most applications, because a name is a **stored key**
  that maintenance pins and event authorship are held against, and two directories that
  both know `michael` cannot be told apart afterwards. A door name is claimed once and
  exactly one door is the default; a second claim on either **refuses at startup**,
  naming both. A provider that raises is treated as **no identity**, logged, and never
  as *let them through* — a failing door takes down itself and no other. That holds for
  every call into a provider, not only `identify()`: an `enterable()` that raises means
  *not enterable*, so a provider probing an unreachable directory cannot take the login
  page down for every **other** door, and an `end_session()` that raises is logged while
  the local session is cleared anyway, because logging out has to work whatever the
  provider does — including fails. Where a
  registration is merely **missing**, the application starts and says so instead: a
  contradiction refuses, an omission logs. No door at all, and doors with none of them
  the default, are each a startup `WARNING` naming the line to add, on an instance that
  still serves `/health` and answers `401` everywhere gated. Refusing to start would
  take a monitoring application down for a mistake it can describe — and would refuse
  the *more* usable of the two, since doors without a default still admit anybody who
  knows `/login/<door>`. **A default door can also stop being there**, and that is
  nobody's omission: a credential that fails to resolve closes its own door, so an
  installation whose provider was the default keeps doors that work with none of them
  marked. Where such an installation asked for `identity.choose_at_login()`, an
  unidentified request is sent to `/login` — the page the library serves, listing
  whatever is still enterable — instead of being refused while that page sits there
  offering a way in. Without the chooser `/login` is the default door's own step and
  answers `404`, so `401` stays the honest answer; either way the refusal now says which
  of the two states it is in, and says it once at startup rather than once per request.
- **The built-in login list is now one of those providers**, on the `local` door —
  and, like every other door, **the installation registers it**:
  `local_login.use_local()`, in the same import-before-app block
  (ADR-0069 §3). The library adds no door on anybody's behalf, so *can anybody log into
  this instance* is answered by reading one file rather than by working out what would
  have been inferred from what else was registered. **This is a breaking change for a
  deployment that supplied no provider**: without that line the instance starts, warns
  that nobody can sign in, and lets nobody in. `setup.sh` and the shipped `wsgi.py`
  carry the line, so a checkout of this repository is unaffected.
  **The `users` aspect is read by that call and by nothing else**, so a deployment with
  an identity provider of its own carries no `config/users.yaml` at all and never looks
  for one. It could not before — the list was loaded while the application was being
  imported, so such an instance died there whatever its provider knew. A broken list is
  still a startup failure rather than a surprise at the first login. The per-user
  avatars ([ADR-0045](docs/adr/0045-user-avatars.md)) belong to that same aspect and
  follow it: under another provider there are none, and every viewer gets the packaged
  neutral image.
- **A system-admin account, for the morning the identity provider is the thing that
  broke.** `identity.use_system_admin(reference="env://…")` configures one — a secret
  reference ([ADR-0023](docs/adr/0023-secret-references.md)) resolved **once at
  startup**, or the discouraged `password=…` for a deployment whose store has no
  resolver here; exactly one keyword, and each refuses the other's shape, because a
  reference handed over as a password would quietly make the address the credential
  and nothing would say so until the account was needed. It is a **door like any
  other** — `/login/system-admin`, login name `admin`, and a constant-time comparison
  over bytes (`secrets.same_secret`, because the standard library's own refuses a
  non-ASCII `str` and would answer a `500` to the first umlaut anybody types) — and
  never the default, which is what keeps it a local form under a provider that redirects to
  somewhere unreachable. Nothing is ever generated: a generated password has to be
  readable by the operator, which means putting a live admin credential in the log or
  on the disk. A credential that **fails to resolve** shuts that door and leaves the
  application serving, because an unreachable parameter store must not take the
  dashboard down during the kind of event it is watching; `/system` says *configured
  but unavailable* and names the reference. It is visible while in use — a distinct
  packaged avatar and `System admin` where the chrome prints a name, a `WARNING` on
  every login and every failed attempt — and deliberately without a page banner. The
  built-in login page links to it below the form while the account is configured *and*
  its credential resolved, never to the `404` an unusable door answers with and never
  on that door's own form; it is worth being clear that this reaches the install whose
  `/login` is a local form and **not** the redirecting install the account mostly
  exists for, where `/login` renders nothing of ours. What a pin or an event records is
  still the name alone.
- **`.env` is read when `little_sister.secrets` is imported, not when the application
  is.** The file, its precedence (an environment value already set wins) and its
  absence being fine are all unchanged
  ([ADR-0003](docs/adr/0003-config-and-secrets-via-env-file.md)); what moved is the
  moment, and it moved because a **registration** can now name a secret. A deployment
  resolves `env://…` in its `wsgi.py`, *before* it imports the app — so a file read
  during that import arrives after its only reader, and the credential would be
  reported as unresolvable on every real start. The module that owns `env://` is the
  one that fills it now, and importing anything that can resolve a reference implies
  the file has been read.
- **`setup.sh` writes a different pair of credentials, and they are opposites on
  purpose.** The generated login is now `viewer` and is **not** an admin, keeping the
  placeholder password `change-me` because that one is meant to be *edited*; `.env`
  gains a generated `LITTLE_SISTER_SYSTEM_ADMIN_PASSWORD`, because that one is meant to
  be *read*. After a fresh setup the powerful account is the one with real entropy and
  the everyday one is the weak editable placeholder — the right way round, and the
  admin of a fresh install is behind the system-admin door rather than in the user
  list. An existing installation is untouched: `setup.sh` writes nothing over files
  that are already there.
- **`/login` can offer the doors instead of going to the default one.**
  `identity.choose_at_login()`, beside the registrations it is about, makes that address
  render a page listing every door somebody can actually go through, each as a link to
  its own route and each under a `label=` worth reading. **What an unidentified request
  gets is unchanged**, and that is the point rather than an omission: under an identity
  provider with a live session the redirect it gets is *silent* — somebody clicks a
  dashboard link and arrives logged in, having seen no login page at all — so a page in
  that path would turn zero interactions into one on every visit, forever. What changes
  is the address somebody **types**, which becomes a page little-sister serves and
  therefore one that still answers on the morning the identity provider does not. Until
  now a deployment behind a redirect had no such page: `/login` *was* the redirect, so
  the system-admin door was reachable only by somebody who remembered its address, and
  `/system`, which lists it, is behind the login that is not working. Under the new line
  `/login` is not a door — it renders on `GET` and refuses a `POST`, because a credential
  is taken at a door's own route — while `/login/<door>` is untouched, which is what
  keeps the page from linking back to itself. A provider whose flow is a redirect adds
  one method to appear there, a `login_page()` returning that redirect; one that verifies
  a header has no login step and is not listed, which is how *that* deployment gets a
  login page for the first time. Nothing is required of an installation that says
  nothing: without the line, `/login` is what it always was. The one case where the line
  does reach an unidentified request is the one where there is nothing to leave
  unchanged: a default door that closed leaves no provider to ask, and this page is then
  the only address of ours that still means anything (see the doors entry above).
- **A door can be called something.** `identity.use(…, label="Company SSO")`, defaulting
  to the door's name, which is a path segment and not a sentence; the library's own two
  doors bring their own words (*Local account*, *System administrator*). `/system` prints
  the label beside the name where they differ. A provider may also answer `enterable()` —
  whether its door can take a credential right now — which the system-admin account does,
  because its page is a `404` while its password has not resolved; it is asked once, of
  the door, by both the chooser and the built-in login page's link.
- **`/system` now shows the ways in.** One row per registered door — its route, the
  provider behind it, the package that registered it and which one is the default —
  plus whether a system-admin account is configured and which keyword configured it.
  A deployment's provider is registered in its own `wsgi.py`, which is not on the
  screen when somebody is asking *who can log in here, and how*.
- **`GET /health`** — a machine-readable liveness answer for something that is not a
  person ([ADR-0066](docs/adr/0066-health-answers-liveness-and-says-almost-nothing.md)).
  `200` while the process serves, **whatever the engine is doing**: a check config that
  fails to load already leaves the application serving behind a banner naming the
  reason, and a health check that answered "not well" there would have a load balancer
  remove the one page explaining why. The engine is *reported* instead — `{"status":
  "ok", "engine": "running" | "disabled" | "failed"}` — with `disabled` (a deployment
  said `LITTLE_SISTER_ENGINE=0`) told apart from `failed` (a configuration this instance
  could not load). **No login gate**, because a load balancer has neither a session nor
  a bearer token; the bound on that is that the route says almost nothing — not the
  failure reason, not the version, not the configuration. It is deliberately **not**
  part of the token-authed JSON API and is not in `api/openapi.yaml`. A readiness probe
  can point `LITTLE_SISTER_PROBE_PATH` here instead of at `/login`.
- **The run scripts can serve HTTPS** — `./start.sh --tls`, and the same flag on
  `./stop.sh` and `./test_api.sh`, which also have to reach the instance
  ([ADR-0067](docs/adr/0067-the-run-scripts-can-serve-tls.md)). The port moves with the
  scheme (`TLS_PORT` in `instance.sh`, `8443` by default), so the two can never be
  confused for one address. Set `TLS_CERT` and `TLS_KEY` — both or neither — to serve a
  certificate you already have; with neither, `--tls` mints a self-signed one for the
  run (P-384, 200 days, in the gitignored `var/tls/`) and overwrites it at the next
  start. The scripts deliberately **do not verify** the certificate: each is talking to
  a process on this machine it started seconds ago, and a probe that failed on trust
  would report a serving instance as dead — so `start.sh` *reports* instead when nothing
  on the machine trusts a supplied certificate. A plain run is unchanged, and
  `PROBE_PATH` now defaults to `/health`. **A checkout still serves one instance**: the
  scripts ask whether a *stranger* holds the port they are about to bind of that port
  alone, and whether *this checkout is already serving* of both — so `./start.sh --tls`
  replaces a plain instance rather than running beside it and truncating the log it is
  still writing to, and `./stop.sh` stops whatever is running without being told which
  scheme it was started under. **An instance belongs to the checkout it runs in**,
  recognized by its working directory rather than by the WSGI target two checkouts can
  share — so a second checkout on the same port is refused instead of being adopted and
  stopped. Deliberately not by anything in the command line: macOS `ps` truncates that,
  and gunicorn rewrites it when `setproctitle` is installed. **`--any-instance`** is the
  way past the resulting refusal, named in the refusal itself; it reaches a gunicorn and
  nothing else. The processes named in these refusals are also no longer truncated.

### Changed

- **The default port is `8888`, not `8000`** — `PORT` in `instance.sh`, with the
  fallback in `lib.sh` following it, so an installation that never edited either lands
  in the same place. Nothing else moves: an explicit `LITTLE_SISTER_PORT` still wins,
  and `--tls` still serves on `TLS_PORT` (`8443`). The demo harness of
  `tests/demo_wsgi.py` deliberately stays on `8000`, which now lets it run beside a real
  instance instead of fighting it for one port.

- **The login gate is one gate, and it refuses by default**
  ([ADR-0068](docs/adr/0068-the-login-gate-refuses-by-default.md)). *Who is this
  request* was `session['username']` read in fourteen views; it is now
  `identity.current_user()`, and a single `before_request` hook refuses any request with
  no identity unless its endpoint is named in one of two lists — `OPEN_ENDPOINTS` (the
  login form and its stylesheet, logout, `/csp-report`, `/health`, and the two
  redirects — `/` onto `/status`, which refuses on its own account, and `/favicon.ico`
  onto the packaged icon) and `SELF_AUTHENTICATING_ENDPOINTS` (`/status`
  alone, which negotiates between a session and a bearer token and would otherwise
  redirect an API client to a login page). The polarity is the point: a route added
  tomorrow is closed until somebody classifies it, where a per-view decorator would have
  left it silently open. The role reaches the templates the same way: the shared nav's
  admin-only entry asks `current_user()` through a context processor rather than reading
  the session, so it follows the identity and not the place that identity is kept.
  Nothing a visitor sees changes.

### Fixed

- **A non-ASCII bearer token no longer answers `500` to the JSON API.**
  `secrets.compare_digest` accepts `str` only while both sides are ASCII and raises
  `TypeError` otherwise, so a token arriving off the wire with anything else in it
  turned a request that should have been refused into a server error — a difference
  somebody probing can read. The comparison moved to `secrets.same_secret`, which
  compares bytes and is now the one place in the library any credential is checked
  ([ADR-0008](docs/adr/0008-json-output-api.md)).

- **A registered configuration aspect is no longer reported as unknown at every
  start.** The warning about files in a configuration root that no aspect claims fired
  at the **first resolution** of each root — and since every package that registers an
  aspect declares it and then immediately reads it, so that a broken configuration file
  fails at startup rather than at the first click, that first read *was* the scan.
  Whichever registration ran first performed it, and every aspect registered after it
  was named unknown for the life of the process; no import order fixed that, because
  being a registration is what scanned. The scan is now silent and the report runs once
  at the end of the registration window, from `config_dir.announce_aspects()` at the app
  import — where the set of aspects is final
  ([ADR-0070](docs/adr/0070-the-unclaimed-file-report-runs-at-the-end-of-registration.md)).
  It is public, so a tool that never builds an app can ask for it; it now covers
  **every** configured root rather than only the ones something resolved; and the
  message names the known aspects **with the packages that read them**, so a misspelled
  `identiy.yaml` points at the `identity` it missed. A genuine stray file still warns,
  and still stops nothing.

### Security

- **Every cookie this application sets is now marked `Secure` when the request that
  set it arrived over TLS** — the session cookie that carries a login, the
  presentation preferences and the view switches
  ([ADR-0065](docs/adr/0065-the-connection-decides-what-is-secure.md)). The
  **transport** decides, per request: `request.is_secure`, which gunicorn sets from
  the socket it is holding, so the flag is right on a laptop and on an instance behind
  a load balancer without either being configured, and it cannot drift from how the
  process was actually started. A plain-HTTP deployment is unchanged — a `Secure`
  cookie there is one the browser never sends back, which reads as a login page that
  will not stay logged in. An explicitly configured `SESSION_COOKIE_SECURE` still
  wins, so the connection can only ever *add* the flag; there is deliberately no way
  to remove it from a TLS connection. **No `Strict-Transport-Security` header**: it is
  scoped to a host and ignores the port, so a library sending one would make every
  other service on that host unreachable in that browser — a promise about a whole
  host name is a deployment's to make.
- **The session cookie says `SameSite=Lax`.** It was the one cookie carrying a login
  and the only one left to whatever the browser defaults to, while `ls_prefs` and the
  fold-depth cookie — a theme and a disclosure state — both said `Lax` outright. On an
  application whose state-changing POSTs carry no CSRF token, that attribute *is* the
  defense against a cross-site form post. `Lax` rather than `Strict`, because a door's
  callback is a top-level navigation back from an identity provider and `Strict` would
  arrive there with no cookie.
- **`setup.sh` will not invent the system admin's password out of a constant.** Its
  generator fell back to the literal `change-me` when `python3` was missing — tolerable
  while it only produced a session key, wrong once it mints the credential of the most
  powerful account there is, and printed as "random" either way. It now uses `python3`,
  falls back to `openssl` (which `lib.sh` already requires to mint a certificate), and
  **refuses** rather than guessing a third time.
- **`setup.sh` adds the system-admin password to an `.env` that predates it.** Every
  existing installation takes exactly this path: answering *no* to the overwrite prompt
  kept a file with no `LITTLE_SISTER_SYSTEM_ADMIN_PASSWORD` in it, which is a door
  registered and shut — the state you find on the morning it is needed. The one missing
  key is appended and named on stdout; nothing else in the file is touched, because
  regenerating `SECRET_KEY` would end every open session and the API tokens are the
  deployment's own. Answering *yes* still rewrites the file, and the prompt now says so
  before you answer.
- `start.sh`'s warning for a missing `.env` said "insecure dev session key", which
  stopped being true when the app started minting a random key per start. The cost is
  that every restart logs everyone out, which is what it says now.

## [0.3.13] - 2026-08-23

### Removed

- **Breaking — three names leave the check-authoring surface, and the check API
  epoch is now 2.** `parse_subnodes`, `resolve_text` and `expand_tokens` are gone
  from `little_sister.checks`. They were how a branch check read and layered its
  own `subnodes:` block; little-sister reads that block itself now, for every check
  type, so a type has nothing left to call them for (see *Changed*). **Every
  check-type package must release**: change `require_api(1)` to `require_api(2)`,
  delete the three imports and the code around them, and declare
  `subnode_defaults` / `label_tokens` instead. There is deliberately **no
  compatibility window** — a package built for epoch 1 refuses at startup naming
  both numbers, which is the point of the epoch
  ([ADR-0051](docs/adr/0051-what-startup-refuses.md)). Nothing in a *deployment's*
  configuration changes: the `subnodes:` block is written exactly as before, and it
  now works for check types that never read it.

### Added

- **A node can say that its quiet lines are still worth reading.** The dense
  dashboard buys height by painting a quiet leaf as a chip and folding surplus quiet
  boxes behind *+N more*, which is right for reason text that explains a problem and
  wrong for an **inventory** — a list of instances, volumes or accounts that is read
  precisely *because* everything is fine, and which was therefore visible only while
  something else was broken. Such a node now declares `show_when_quiet`, and the
  dense view keeps its full box and never folds it. Set it beside `title` and
  `about` — in a check's YAML for its own node, in `config/nodes.yaml` for any node
  by path, or per aspect in the check's `subnodes:` block, which **little-sister
  reads itself, for every branch check type**: a deployment can declare it for any
  installed check without that check changing.

  **A check type declares it beside the label, in the same entry** — its
  `subnode_defaults` map is shaped like the block a deployment writes, key for key
  — so an aspect that is a roster *by construction* (an `ec2` inventory, one line
  per instance) is stated once in the package and inherited by every account of
  every installation. What a deployment writes in its own `subnodes:` block beats
  that per name, `config/nodes.yaml` beats both per path, and a value a check
  *stamps* on a child result is the fallback for a child only the run could have
  named. Stating `show_when_quiet: false` — in the block or in `nodes.yaml` — is
  how a declaration a type ships is declined; leaving the key out says nothing.
  A value that is not a real boolean fails the load, in a declaration as in a
  config file, naming the subnode.

  Nothing changes for a node that says nothing,
  density off is unaffected, *hide idle* and *hide ok* still answer to the viewer,
  no card moves, and the JSON envelope is unchanged
  ([ADR-0063](docs/adr/0063-declining-the-density-trade.md)).

- **One name joins the check-authoring surface.** `values.strict_flag` is a
  configuration boolean that must actually be one, beside `values.flag`'s truthiness
  read of a payload: a quoted YAML boolean — `enabled: "false"` — is truthy, so the
  lenient read switches a thing *on* while its config says off, and this one refuses
  the value instead. No reader of the `subnodes:` block is on the surface — the
  library runs them all for every check type, so a check calls none of them (the
  three that used to be there are in *Removed* above). One consequence for every
  type: a malformed `subnodes:` block now fails the load rather than sitting inert
  in a config the type never read.

### Changed

- **A secret resolver is now a registration like the others, and a scheme is
  claimed once.** `secrets.register_resolver()` was the last of the five seams a
  package reaches an instance through that recorded nothing about who registered
  what: a second claim on a scheme silently replaced the first, where a second
  `type:` claim refuses at startup naming both. It now records the **package** that
  made the claim — inferred from the call site, as a configuration aspect's
  registrant is — and a claim on a scheme **another** package holds raises
  `SchemeConflictError` before the process starts, naming both and the scheme.
  A scheme is where a credential is read from, so import order must not be what
  decides it; the alternative is one package's checks authenticating against
  another's store, which fails on a machine nobody is watching or, worse, quietly
  succeeds.

  Registering the same scheme again **from the same package** still replaces it
  silently — that is a reloading server re-running its own registrations.
  Replacing *another* package's scheme is still available and now has to be said:
  `register_resolver(scheme, resolver, replace=True)`. A deployment that
  substitutes its own implementation of the built-in `env` resolver keeps that
  feature and adds one keyword; what it stops doing is happening by accident. What
  a replacement displaced is remembered and shown.

  **`/system` prints the seam twice.** Each package's inventory row gains
  `secret <scheme>://` beside its types, slots, assets and aspects; and the
  extensions card gains the **whole scheme list** — scheme, package, what it
  replaced, and whether it is the library's own — as a table shaped like the slot
  table above it. The built-in `env` is in it, unlike the aspects line beside it,
  because the schemes are additive and a reference names exactly one, so the full
  list is the only answer to *what may I write in this field*; and unlike the
  entries beside it, this one is never absent.
  Nothing on the check-authoring surface moves and the epoch stays 2:
  `little_sister.secrets` has never been in §11's fenced block
  ([ADR-0064](docs/adr/0064-the-resolver-is-a-registration.md)).

- **A deployment can label any installed branch check's subnodes, without that
  check's help.** `subnodes: {disk: {title: …, about: …}}` in a check's own config
  is read by little-sister itself now, exactly like the `show_when_quiet` beside it:
  a check type **declares** the labels it ships (`subnode_defaults`) and any values
  its text reuses (`label_tokens`), the library resolves each field once — the
  configured text when present, the declared default otherwise, `{default}`
  extending rather than replacing and `{token}`s expanded by a plain replace that
  leaves Markdown intact — and the engine writes the result per subnode *name*, at
  any depth. Two things change for the better: a `subnodes:` label written against a
  type that never read the block used to do nothing at all, silently, and now
  reaches every branch type; and text substitution is one library contract rather
  than one per check type. Precedence is unchanged — `config/nodes.yaml` still wins
  per field, and a label still freezes at a node's first fill — and a label a check
  puts on a **dynamically named** child (a volume it discovered) still applies,
  where nothing declared or configured that name
  ([ADR-0025](docs/adr/0025-check-provided-subnode-metadata.md)).

- **The dashboard navigation stays reachable while a long tree scrolls.** The bar
  remains at the top in both interactive layouts, and the left rail stays beneath
  its height — from a safe scriptless default refined by measurement — and gains
  its own scroll on a short window. An expanded narrow top bar uses its measured
  first-row footprint to scroll the section list without clipping the separately
  bounded settings menu, so both last choices remain reachable. The document is
  still the scroll container; content panels
  pass behind the chrome while viewport-positioned popovers remain above it, and
  the kiosk remains unchanged
  ([ADR-0062](docs/adr/0062-navigation-chrome-is-layout-behavior.md)).

### Fixed

- **A run's log line no longer cuts the reason that explains the run.** It carried
  the **first** reason, truncated at 120 characters — and both halves of that were
  wrong exactly when the line is read. A check that could not measure at all words
  its refusal in two reasons on purpose, what went wrong and then what to do about
  it, because the second is the actionable half and a provider's error is long
  enough to push it off the edge of a card; the log kept the first and dropped the
  second, then cut the first mid-sentence. A real `AssumeRole` refusal ended at
  *"…when calling the AssumeRole operation:"* — precisely before the part naming
  who was refused and for what, which was the whole content. Now every reason is
  carried, joined, under a cap generous enough for a provider's message to arrive
  whole; what the cap truncates is a *roster*, where the leading entries are
  representative, and it says so with an ellipsis rather than stopping where a
  reader would take the end for the message's own.

- **An action chip no longer reads through to the title underneath it.** In a card
  head the chip rail sits over the title's space on purpose — a chip is something to
  click — but a chip is transparent, so a deployment's `+ Jira` landed in the middle
  of a word and neither could be read. Every card and node box now declares its fill
  as a token and the rail repaints that exact fill beneath its chips while they are
  showing, the title fading into it; a card at rest offers nothing to click and keeps
  its whole title
  ([ADR-0034](docs/adr/0034-template-slots-for-dependent-packages.md)).

## [0.3.12] - 2026-08-16

### Added

- **`follow_redirects:` on the `http` check**, default `true` — which is what the check
  has always done, so nothing changes until you ask it to. Set it `false` and a `3xx`
  becomes the reading rather than a step on the way to one: list the redirect codes you
  accept in `expected_status` (`[200, 301]`), and a *new* redirect turns the check. That
  is the stricter reading, and it is the one worth having where a `200` at the end of a
  chain might be a login wall rather than the page you asked for. The node's config
  summary says which reading is in force, because the two differ on the same URL.

  It must be a real boolean: `follow_redirects: "false"` — quoted, as YAML makes easy —
  is refused when the check loads rather than read as true. A switch that can silently
  mean its opposite is worse than no switch.

- **A check can say what a failed request means, in one vocabulary.** Everything a
  check type may import is promised by name (`docs/architecture.md` §11), and until
  now nothing on that list said a word about a request that does not answer — so
  every check reading a remote API decided four things for itself: how long one
  request may take, what bounds a run that asks fifty times, what is worth asking
  again, and what a failure *means*. `little_sister.transport` now promises the
  **policy** for all four, and no client:

  - **`Deadline`** — a run's budget, with `budget(timeout)` clamping a per-request
    timeout to what the run has left. That clamp is what makes a check's `timeout:`
    a bound: without it a fifteen-second request can start with two seconds left
    and overrun by thirteen.
  - **`Fault`** — *transient* / *answered* / *malformed*, decided by status and
    never by message text. Three states rather than two, because "they answered
    with something unusable" is not the same fact as "they answered no", and a
    check whose error type cannot tell them apart cannot report the difference.
  - **`RemoteError`** — carries the status and the fault; `fault` is required with
    no default, and it is meant to be subclassed, so a package keeps its own error
    class and messages.
  - **`DeadlineExceeded`** — deliberately *not* a `RemoteError`, so a handler that
    turns a failure into one line per item cannot turn one run-level fact into
    forty item-level ones.
  - **`ask`** — one bounded retry: only a transient fault, only while attempts
    remain, and only while the deadline can still afford the backoff.

  There is **no I/O and no HTTP** in it, which is the point: a check whose transport
  is a vendor SDK wears the same policy while the SDK does the socket work. It
  promises **no** mapping from a fault to a status code either — for an `http` check
  the endpoint *is* the subject of the measurement, while for a check reading an API
  to grade something else it is the instrument, and only the check knows which it
  has. Adding names does not move the check API epoch, which stays at **1**.

- **And one place that makes the request.** `little_sister.fetch` promises `fetch`,
  `Response` and `fault_for`. `fetch` makes one request and hands back a `Response`
  for **every** status — a `500` is an answer, not an exception, which is what lets a
  check whose measurement *is* the status use it at all. Only a request that never
  reached a status raises, as a transient `RemoteError` carrying the original
  exception as `__cause__`.

  Five things that used to be decided per call site are now decided once:
  `timeout` and `follow_redirects` are **required arguments** (a request with no
  timeout, and a redirect policy nobody chose, are the two defects this keeps
  rediscovering); every request identifies itself as `little-sister/<version>` rather
  than as `Python-urllib`, which an outbound filter is far more likely to answer with
  an uninterpretable `403`; proxies and the system trust store are honored as the
  environment sets them, and certificate verification **cannot** be switched off; and
  a response body is read in bounded chunks against a 16 MiB cap.

  That last part closes a hole worth naming: `urlopen(timeout=…)` bounds one **socket
  operation**, not a request, so a server sending one byte every few seconds never times
  out. Given a `Deadline`, `fetch` reads the body against the run's clock and gives up
  when the budget is gone.

  It reads with `read1` to manage it, and that is the whole of why it works: `read(n)`
  blocks until it has all *n* bytes, so against a trickle the first call would not return
  until the body was complete, and the clock would be consulted once — after the overrun
  it was there to prevent. Measured against a real socket, a 1.5-second budget gave up
  after **7.8 seconds** that way, and after 1.6 with `read1`. Two limits are stated rather
  than implied: the clock bites only when a `deadline` is given *and* a body is actually
  read, and it does not reach the status line and headers, which urllib reads inside its
  own opener — a server trickling *those* is bounded only by the socket timeout per read.

- **A service that answers *not now* is understood.** `retry_after(headers)` reads the
  standard `Retry-After` header — both forms it may take, a number of seconds or an
  HTTP-date — and returns seconds, or nothing at all if the value is unreadable.
  `RemoteError` carries the number as `retry_after`, and `ask` waits that long instead
  of its own backoff, still only while the run's budget allows it: a two-second pause
  is absorbed, a ten-minute one is refused and reported rather than taken, because a
  wait outliving the budget a check granted is not a request's to spend.

  There is deliberately **no separate fault for a throttle**. Being asked to wait is
  already *transient* — asking again could change the answer — and no status identifies
  one: a service may answer `403` or `429` when it means *not yet*, while a bare `403`
  may equally mean *not visible to this credential*. Only a caller that knows the
  service can tell those apart, so classifying a throttle is the caller's, and a
  service's own reset header is its dialect rather than something this library guesses
  at. For the same reason `fault_for` still reads a `429` as *answered*: a `429` with
  no `Retry-After` may be nothing more than crawler protection, and pressing a service
  that is already complaining about volume is how access gets withdrawn.

- **A check can declare the order of its own nodes.** Siblings have always rendered
  alphabetically, which is wrong wherever the set has an order of its own: a severity
  band row read `critical high informational low medium`, filing *nothing to do* third,
  and `low` before `medium` is a wrong statement about severity. `CheckResult` now
  carries an `order: int = 0` and the tree sorts siblings by `(order, name)` — a
  negative value pulls a node up, a positive one pushes it down, and ties still break
  by name. A deployment can overrule any of it from its own configuration — `order:`
  sits beside `title:` and `about:`, both inline on a check and in `nodes.yaml`
  ([ADR-0055](docs/adr/0055-sibling-order.md)).

  `0` is the rank an unranked node carries, so a node given it sorts with them — ahead
  of every positive rank and behind every negative one. Stating `order: 0` on one child
  of a ranked set therefore moves that child to the *front*; putting a whole set back to
  plain alphabetical order means stating it on every sibling.

  **Nothing changes for a deployment that declares no ranks.** The default `0` on every
  node reproduces the previous alphabetical order exactly. Where a rank *is* declared,
  a node's `children` move in the JSON envelope as well as on the dashboard. The API
  spec had promised plain name order, so it moves to **1.3.0** and now documents
  `(rank, name)`; `schema_version` stays `1`, as it did for the nullable `timestamp`.
  The rank itself is not an envelope field yet — it ships with the batched
  client-contract revision.

- **`/system` now says which checks a check type is used by.** The check-type roster
  printed *used by 2 checks* under a type name and nothing else, so the one number on
  that page an operator might doubt was the one number the page could not
  substantiate — *two of what?*, when a type named in two check files, rendering in two
  different branches of the tree, is the ordinary case. The count is still what the row
  leads with, and it now opens into the node path of every check behind it, each a link
  to that node. A type nothing uses offers no list. Everything else on the page already
  named its subjects; this row does too.

### Changed

- **The default log level is now `INFO`, and `LOG_LEVEL` names it**
  ([ADR-0049](docs/adr/0049-the-check-authoring-surface.md)). This reaches
  only installations that let little-sister configure logging: an application that
  sets up its own — before importing `little_sister.app` — keeps its level exactly as
  it did, and `LOG_LEVEL` does not reach it.

  The old default was `DEBUG`, which collects no line little-sister writes, since
  nothing in it logs below `INFO`, and every line written by everything installed
  beside it. One deployment's log ran two thirds AWS SDK request detail nobody had
  asked for. `LOG_LEVEL=DEBUG` asks for the old behavior back for a debugging
  session; an unrecognized name falls back to `INFO` and says so in the log it just
  opened.
  - A dependency that is chatty at `INFO` is quieted the way it always was, by
    capping **its own** logger — `logging.getLogger("botocore").setLevel(WARNING)`,
    beside the check-type registrations. That adds no handler to the root logger, so
    the default setup still runs: quieting a dependency does not cost you ownership
    of logging.

- **A title with no word in it no longer stands in for a node's name**
  ([ADR-0061](docs/adr/0061-decoration-is-not-a-label.md)). Most surfaces draw the
  name and the title side by side; two draw the title *instead of* the name — the
  `/copy` hand-off and the inspection popover's card — which is right while a title is
  a word, and wrong for a glyph. A node titled `🔴` used to paste into a ticket as a
  circle and nothing else, in the one surface with no chips and no styling to carry
  the meaning. It now reads `critical 🔴`, name first.
  - The test is `isalnum` per character, so it is a **Unicode** one: a Japanese,
    Cyrillic or Greek title is a word and is unaffected; an emoji, an arrow or a
    bullet is not. A digit counts.
  - **Only nodes whose titles are already wordless change**, and only on those two
    surfaces — nothing that was drawn stops being drawn. Display only, as before: the
    tree still stores the title and the JSON envelope still emits it, so a client
    drawing its own chips keeps its own decision about the glyph.

- **The fast failure retry now re-arms whenever a check's reading changes**, not only
  when it goes `OK` — and a run that reports `UNDEFINED` no longer arms it at all
  ([ADR-0033](docs/adr/0033-budgeted-failure-retry.md), amended by
  [ADR-0060](docs/adr/0060-a-line-makes-no-claim.md) decision 4). Only deployments
  that set `retry_interval` are affected.

  The old rule assumed a non-`OK` check was a failing one. Since a node's code can be
  derived from its lines, a check can sit at `WARN` for weeks as its *ordinary* state —
  and it then spent `retry_attempts` in its first few cycles and had none left on the
  day its reading actually changed, which is the one day a second look is worth
  paying for. Nothing said so either: `/system` marks only a pulled-in slot, so a
  spent budget looked exactly like a check that never had one.

  A burst is still bounded, because an unchanged reading is not news: a three-day
  outage costs `retry_attempts` fast runs and then normal cadence, exactly as before.
  What changed is that the budget comes back when the news does.

- **The built-in `http` check and the links page now share one request path.** The
  `http` check keeps following redirects and keeps reporting any transport failure as
  `ERROR` — the endpoint is what it measures — and now identifies itself by name like
  every other request. The links page keeps reporting a redirect instead of following
  it, and keeps its own three-way reading of what a failure means for a link.

- **The SSH connection module is now `checks/ssh/connection.py`** (was
  `transport.py`), naming what it holds rather than the layer it sits in and freeing
  `transport` for the policy above. `SshConnection` and `RemoteResult` are imported
  from `little_sister.checks.ssh` as before, so nothing outside the package changes.

- **Copy one node, not just the tree.** A leaf's detail page now carries the same
  two clipboard buttons as `/copy`, aimed at that node. What they hand over is
  what an operator otherwise retypes into a ticket: the node's name, title and
  **path**, when it was **observed** and since when it has held that status, the
  **next update**, how long the **last run** took, how often it is checked, what
  the run **reported**, what it ran **with**, and every reason line **in full** —
  a truncated API error included. Both formats come from one document, and one
  formatter writes it and the tree hand-off, so the node cannot describe itself
  one way on its own page and another inside `/copy`.

  **Every instant names its offset** — `2026-01-15 10:00:00 +01:00` — in both
  documents, including a maintenance pin's expiry on `/copy`. The pages render
  local time and say nothing about the zone, which is right for a screen somebody
  is standing in front of and useless in a document read somewhere else.

  **A pin does not change what is copied.** A pin changes what the tree *reports*;
  it does not change what the check *measured*, and a hand-off is about the
  measurement — so the document keeps the reading and says a pin is in force,
  instead of quietly presenting the pinned code as the answer.

  **A reason line that declared a code of its own keeps it**, in both documents: a
  line's cue sits before its text, so a healthy workflow under a failing node reads
  as healthy in a pasted incident too, and a line that declared no code takes no
  cue because it carries its node's. A line whose subject is **running** says so in
  words — the page renders that as an italic, and a document has no glance to serve.

  Containers get no buttons: their page is a dashboard of their children, and the
  hand-off for a subtree is `/copy`.

- **Copy one finding.** The line an operator is actually opening a ticket about is
  one of twenty on a node, and both documents above carry the other nineteen. Every
  reason line that a check declared as a **member** now has a **Copy** chip beside
  it — on the dashboard and on the detail page — leading to a page that hands over
  that line alone, with the node's title, path and observation so a pasted finding
  still says where it came from. Nothing else: the run's facts, the report and the
  configuration describe the node, and the button that carries them is one click
  away. Reasons that are **prose** get no chip — a failure message and its stack
  trace are one condition, and half of one condition is not a hand-off.

  `/copy` grew a path for it: `/copy/<node>` is that node's document and
  `/copy/<node>?reason=<slug>` is one line's, so every hand-off now has a URL that
  can itself be pasted into the ticket. The chip is an ordinary link, which is what
  keeps the documents *out of* the pages that offer them — a node with two hundred
  findings would otherwise carry two hundred documents on every render.

- **A slot's context provider now receives the names it declares.** `reason.actions`
  gained a `line` name (the whole reason entry — slug, code, `running`, any pin),
  and a provider that spelled its keyword arguments out would have broken on the
  addition: a `TypeError`, a logged failure, and a deployment quietly losing its
  chips on an upgrade of little-sister. Providers are now handed exactly the
  parameters they declare, or everything when they declare `**kwargs`, so a filler
  written against an earlier context keeps working untouched and a new one can ask
  for what it needs. No action is required of any existing extension.

- **The clipboard buttons are named after what they write.** *Copy rich text* is
  now **Copy Rich HTML**: the clipboard member is `text/html`, not RTF, and
  *Copy Markdown* beside it read as though the other one were not text. Every page
  that offers a document — `/copy` and its per-node and per-line pages, and a
  leaf's detail page — renders one partial, so the pair keeps meaning the same
  thing wherever it appears.

- **`little_sister.spans` — how a span of time is written**, on the public API
  surface (`architecture.md` §11) so a check type outside this repository can
  write *"the backup took 2h 7m"* into a reason line and match the page it renders
  onto. Three functions, because there are three readings: `format_span` for a
  span whose size *is* the information (a runtime, a countdown), `coarse_span` for
  one where it is approximately the information (*how long ago*, *how much is
  left*) and the value has to stay true on a page nobody is re-rendering, and
  `format_duration` for a **configured** interval written back in the units
  somebody typed it in (`900` is `15m`, where a measured span would say `15m 0s`).
  `parse_duration` reads a span from a config; these write one to a screen.

- **`/system` no longer prints an absolute path to every loaded module.** Both tables
  that say where something was loaded from — the check-type roster and the package
  inventory — showed the whole string, which on a real deployment is
  `/Users/<someone>/…/.venv/lib/python3.14/site-packages/little_sister_github/github.py`:
  nine tenths of it the same prefix on every row, and the leading part somebody's home
  directory on a page that is read over a shoulder and pasted into tickets. The path is
  now drawn against the nearest root the reader has — `site-packages/…` for an
  installed package, `./…` for one under the working directory — which is what the path
  was for in the first place: a source copy shadowing an installed distribution of the
  same name still reads as one at a glance. A module under neither root keeps its full
  path, which is itself the answer to *where did this come from*, and the whole string
  is still one hover away. Display only: the origin objects are unchanged.

- **Large dashboard roots now spend only columns their nested flow can use.**
  Each root gets stable useful-width steps derived from the visible tree, view depth
  and configured reason-line budget. A step that cannot open another nested column
  is skipped, so the layout can jump directly from span one to three; a deeply
  linear root remains one track, and a spare that buys no shorter flow stays empty.
  Among useful next steps, the greatest modeled-height reduction per track wins.
  The representative lopsided four-track fixture still splits 1:3.

  Status, current reasons, measured card height and chip/box painting never enter
  the model, so a status-only poll cannot move a root. A larger configured reason
  budget does deliberately give potential reason hosts more stable weight.
  Consecutive quiet chips now share a full-row wrapper, allowing full boxes at the
  same mixed level to use nested columns while the chips keep wrapping compactly.
  Poll fragments send only plan-change breakpoints instead of 32 complete plans;
  an 80-root overview therefore carries one unchanged plan rather than roughly
  2,560 repeated spans. The auto-fill grid remains the no-JavaScript fallback
  ([ADR-0056](docs/adr/0056-stable-useful-dashboard-flow.md)).

  Spans are priced at the width the grid actually resolved, and the tallest card
  in a row spends first. The first flow model evaluated every span at the 330 px
  track minimum, while real `auto-fill` tracks are almost always wider: two equal
  roots on a real four-track grid were allocated one wide card beside a 1,949 px
  tower where a 2 + 2 split paints 1,137 px twice, and a root branching four wide
  at its second level missed a 1,763 → 918 px step by a few pixels of track
  slack. Breakpoints are therefore keyed in **pixels of grid width** — the script
  measures the grid and selects the last applicable band; track counts remain
  only as the safety clamp — and the allocator now hands the next useful step to
  the currently **tallest** card, since a grid row is exactly as tall as its
  tallest member (summed-gain greed measurably gave one of two equal roots twelve
  of fourteen tracks). A structural test pins the model's five width constants to
  `overview.css`, so a stylesheet change turns a silently wrong layout into a red
  test. New `settings.yaml` key `dashboard_columns: flow | plain` — `plain`
  withholds the span plan entirely, leaving the plain auto-fill grid a browser
  without JavaScript shows; anything else warns and falls back to `flow`. The
  key is an enum on purpose: a per-viewer value and a possible `packed` mode are
  later steps of the same control.

  A wider viewport can no longer paint a worse wall. At the exact width where
  CSS `auto-fill` fits one more 330 px track, every track snaps back to its
  minimum — one extra pixel of viewport turned a 1,582 px page into a 2,567 px
  one, because the half-and-half split physically lost its nested columns to an
  odd number of minimum tracks. A published band now names the track count its
  plan was priced for and the script sets the grid to exactly that many equal
  tracks, so the four wide tracks simply stay; candidates are compared by
  modeled page height, may never drop below `min(roots, auto-fill)` tracks (a
  single page-wide banner is often the modeled-shortest page, and is still
  wrong), and an incumbent band yields only to a strictly better challenger.
  The floor is a track-width rule — a chosen track never stretches wider than
  the widest track auto-fill itself can produce — and it constrains new counts
  only: the incumbent's own count stays challengeable, because a card's nested
  column count can flip inside an unchanged band and re-chunk its children
  into worse rows, and the dodge is a re-span at that same count or a return
  to a count the old roots-based floor would have banned. The
  wider-never-worse property is tested on both sides of every model event —
  across the hand-built counterexample walls and a seeded randomized sweep —
  as an invariant the sweep maintains, not a theorem. Its final form is
  narrower still: a card's own nested auto-fit can re-chunk at a column flip
  with no outer dodge in existence, so the planner promises no harmful outer
  snap and never-worse-than-the-best-available-choice; strict monotonicity is
  asserted only where no undodgeable inner re-chunk exists. A Chromium
  boundary test (an opt-in `browser` dependency group, documented with its
  command; skipped without a browser) walks the snap boundary and holds the
  model's nested flips to within one pixel of paint — the column tolerance is
  now genuinely sub-pixel. Bands publish in **tenths of a pixel**, the model's
  own unit, and the script scales its measurement to match: rounding
  thresholds up to whole pixels left a band up to 0.9px late against a
  browser's fractional width, long enough for a wall to carry a plan far worse
  than an available one.
  All-ones plans keep riding auto-fill, so flat walls ship one band and paint
  byte-identically. Deep deployments also stop paying a per-poll modeling tax:
  the height model now merges children's pieces bottom-up instead of re-walking
  the subtree at every threshold (ten thousand leaves: 6.7 s → ~150 ms) and the
  finished layout is memoized on the depth-limited tree shape, so a status-only
  poll costs a lookup.

- **A node title that only repeats its name is no longer drawn.** Where a check has
  nothing better to say it hands back the name again with a capital letter, so a row of
  severity bands read `critical Critical`, `medium Medium`, `none None` — twice the
  width and no second fact, on a card whose chips already compete for one line. The
  title is now suppressed wherever it would say the same thing as the name it sits
  beside: the dashboard's chips, box and card heads and heartbeat strip, the page band,
  the hover card, the maintenance table and the `/copy` hand-off. "The same thing" folds
  case, `_` / `-` / a space and runs of whitespace, so `pull_requests` beside
  *Pull requests* and `code_scanning_alerts` beside *Code-scanning alerts* both count;
  a title that adds anything at all is untouched.

  This is a **display** change only. The JSON API still emits `title` exactly as before
  — a client that renders its own chips makes its own decision about the word — and a
  `nodes.yaml` title is stored as written.

### Fixed

- **A span no longer stays in seconds however large it grows.** The `/system`
  page rendered a quarter-hour wait as `in 812s` beside a two-minute run reading
  `115 s`, and a check stale for two hours read `7500s`, because each surface
  formatted its own. They all call `format_span` now, which changes units as the
  value grows — `412 ms`, `3.1 s`, `43 s`, `1m 55s`, `2h 7m`, `1d 3h` — so the
  number stays about the same width whatever the span. Affects the `elapsed`
  Jinja filter, the system page's Running / Next run / Last run cells and its
  uptime card, and the staleness line on the dashboard and the check page. A
  *configured* interval still renders through `duration` in the units the config
  wrote it in (`15m`), which is a different question and a different answer.

- **A check type that does not accept a new common field now fails with a message
  that names it.** The fields every check shares grow — `order` is the newest — and
  each becomes a keyword argument the loader passes to a check's constructor. A check
  type written outside this repository that spells those keywords out instead of
  taking `**kwargs` used to fail with a bare `TypeError` from inside the loader,
  naming neither the configuration file nor the check type. It is now a `CheckError`
  naming the file, the type and the keyword it refused, and saying what to do about
  it. A `TypeError` raised *inside* a constructor is deliberately left alone, so a
  real defect in a check is never relabelled as this.

## [0.3.11] - 2026-08-09

### Changed

- **`requires-python` is now `>=3.11`**, down from `>=3.14`. Nothing in the library ever
  needed 3.14: the high floor was a deliberate choice made while the only consumer was a
  host whose interpreter we provisioned, and that arithmetic changes as soon as the
  library is installed by people who choose their own
  ([ADR-0054](docs/adr/0054-python-floor-and-development-version.md)). 3.11 is the
  **measured** minimum, not an estimate — every interpreter from 3.9 up was fetched and
  the suite run against it. Development and the everyday quality gate stay on 3.14, so
  that remains the best-tested interpreter, and the floor is checked rather than
  declared: the type check runs against 3.11 on every commit and the whole suite runs
  against 3.11 on every release. The version number is that floor, on purpose.

## [0.3.0] - 2026-08-09

### Removed

- **`LITTLE_SISTER_USERS` is gone.** The user list comes only from the `users` aspect
  of the configuration roots now — `config/users.yaml`, or `config/users/users.yaml`
  beside `config/users/avatars/`. A deployment that already keeps its list there needs
  to change nothing.

  A deployment that used the variable to name a file elsewhere gives that file a
  **configuration root of its own** and names it first:

  ```
  LITTLE_SISTER_CONFIG_DIR=/etc/little-sister/identity:config
  ```

  That does exactly what the variable did: `users` is the one aspect that does not
  layer, so the first root declaring it wins whole and the rest of the tree still comes
  from the roots behind it. Avatars for such a list live in that root's
  `users/avatars/`, as they do anywhere else.

  **The variable is not ignored — it is refused.** A startup that finds it set stops
  with a message naming the move, and `./start.sh` fails before it starts the server.
  Leaving it set while a user list also sits in the configuration tree would otherwise
  bring the instance up looking healthy while authenticating against a *different* set
  of accounts, and a silent change to who can log in is not something to find out
  about later.

### Added

- **A check type can now be a package of its own, and the boundary is enforced.**
  Three things in the library back it up:

  - **The check API epoch.** `little_sister.checks.API_VERSION` is **1**. It moves
    only when a promised name leaves the check-authoring surface or a documented
    behavior changes — never for anything else in a release — so your package follows
    the contract it uses rather than the library's version line. Declare it with
    `require_api(1)` beside your registrations and a mismatch refuses at startup,
    naming both epochs, instead of failing as an `ImportError` inside your package.
    Your dependency stays a **floor** (`little-sister >= x`, never a pin, or two
    plugins could not be installed together); the epoch is what catches the upgrade a
    floor cannot see.
  - **A `type:` name is claimed once.** Names stay bare — `type: github` — so two
    packages *can* now claim one; the second registration refuses at startup and
    names both classes, rather than letting import order decide whose code answers
    for whose configuration. Re-registering the same class (a reloading server) is
    still fine.
  - **`/system` lists the check types** with the module, the path it was loaded from,
    and the distribution and version answering for each. When a type can come from a
    package released elsewhere, this is the only place that question has an answer —
    and the path is there because a source copy on the path shadows an installed one
    while the metadata keeps reporting the version you installed. The types your
    configuration runs lead the table, each with the number of checks behind it; the
    rest fold into a disclosure, so a plugin that registered but has no check on it
    yet is one click away instead of nine rows of noise.
  - **`/system` also lists the packages**, one row per installation beside the
    library: distribution, version, the file it was loaded from, and everything it
    registered — check types, filled slots, served assets, configuration aspects. A
    check type is only one of four ways a package reaches the instance, and an
    extension that registers none of them — a chip package, say — previously had its
    version nowhere on the page. Registering a configuration aspect now records the
    package that did it, so `config/<name>.yaml` says who reads it.
  - **A naming convention that survives publication.** Distribution
    `little-sister-<x>`, import package `little_sister_<x>`, check type `<x>`. A git
    source is a *redirect*, not a different package, so moving these to an index later
    deletes a `[tool.uv.sources]` table and changes no import and no config — as long
    as the name was right from the first tag. Reserve it when you cut the repository.

- **The version contract now covers what a check type is actually written against.**
  If you write check types — in your deployment, or in a package of their own — this
  is the release to pin. `architecture.md` §11 gained a **check-authoring surface**:
  the base class and result type, `register`, the config helpers (`coerce_code`,
  `config_markdown`, `parse_duration`, `parse_secret_refs`, `plain`, `code`), the
  subnode-metadata helpers (`parse_subnodes`, `resolve_text`, `expand_tokens`, now
  re-exported from `little_sister.checks` itself), the reason vocabulary (`Entry`,
  `derived_slug`, `slug`, `normalize`, `MAX_SLUG_LENGTH`, `ReasonError`),
  `StatusCode`, `join_path` — what a branch check's `owned_nodes` override needs — and
  the typed `values` readers. Those names are promised across a tag now, and the gate
  fails on a rename that drops one, so a check type behind its own tag cannot be
  broken by a refactor it never saw.

  **Import them from the package `little_sister.checks`, not from
  `little_sister.checks.base`.** The package is the promise; the modules under it stay
  free to move. Existing imports keep working — nothing was removed — but only the
  package spelling is covered going forward, so it is worth the one-line change.

- **`slug()` — a reason entry's key, built from the identifiers your provider already
  owns.** `from little_sister.reasons import slug`; `slug(repo, "pr", 42)` →
  `repo-pr-42`. Unsafe characters collapse, empty parts drop out, and an over-long
  slug keeps a readable prefix plus a hash of the whole value rather than being
  truncated onto a neighbor's key. A part that keeps nothing at all — an entity named
  in Cyrillic or Japanese — is hashed rather than dropped, so two findings can never
  collapse onto one key; a `None` part drops out like an empty one. Use it wherever a
  check discovers findings that carry real ids: `derived_slug`'s content hash *is*
  the wording, so improving a line drops every maintenance pin on it, while an
  id-based key survives the re-wording.
  Which ids to use is your check's call; the shape of the token is now the library's.

- **Every page now carries a Content-Security-Policy — as a report, not yet as a
  rule.** The header is `Content-Security-Policy-Report-Only`, so a violation is
  logged at `WARNING` and **nothing is blocked**: no page changes behavior, and the
  log starts saying what a strict policy *would* have caught before anyone commits to
  one. Nothing is stored, so this waits on no persistence decision.

  The policy is **assembled, never a constant**: the library's own defaults, plus
  origins a dependent package declares, plus an optional `config/csp.yaml` of your
  own. That matters if you ship a package against these seams — `script-src` names
  origins rather than files, so `'self'` already covers a filler's *code*, but not the
  hosts that code **reaches**. Declare one with
  `csp.allow("connect-src", "https://…", by="your_package")` from the same
  import-before-app block you register check types in, or
  `csp.allow("connect-src", csp.origin_of("<aspect>.<field>"), by=…)` where the host is
  the deployment's own and already sits in your configuration aspect. A package may
  name an **origin, never a keyword**: `'unsafe-inline'` and friends are the
  deployment's call, in `config/csp.yaml`, which is also where an origin nobody
  anticipated goes — so a source you did not foresee is a configuration line and never
  a fork. A source must also be a single token: whitespace, `;`, `,` and control
  characters are refused on both paths, because the header separates sources by
  whitespace and directives by `;`. Refusals are a warning and a skip, as everywhere
  else in these seams.

  `/system` prints the effective policy directive by directive with the contributor of
  every source, because a request blocked inside somebody else's package is otherwise
  undebuggable from the running instance.

- **A node can now say what the run *found*, and a container finally has a page
  that shows it.** Checks may set `report` on any result — the outputs field
  beside `config`'s inputs: the repositories in scope, the volumes enumerated, the
  queues discovered. It is Markdown, it is written through on every run (a run
  that finds nothing clears what the last one found, so a roster cannot outlive
  it), and it never appears on a card. It is never a status claim either —
  anything that should alarm stays a reason; the roster is presence, an entry is
  a claim.

  The leaf page's Time and Configuration cards are now **one shared block**, with
  a Report card added, and `/status/<branch>` renders it below its child grid: the
  container acquires the detail page it never had, so its stored configuration —
  which nothing had ever displayed — its report and its run facts are all visible
  where the node is named, and the two pages can no longer drift. The run's **wall
  time** surfaces there, and `config` finally renders as Markdown instead of the
  literal `- **scope:** org` it had been showing. The kiosk keeps none of it.

  One ownership rule now covers four facts: the run time, the wall time, the next
  run and the check's own text all belong to the check that owns a node **alone**,
  so a container two checks share publishes no `config` and no `report` — the same
  refusal that already withheld its timestamp, and the reason a check with
  whole-check information to publish should own its own node. The JSON envelope is
  untouched until the client contract round.

### Changed

- **little-sister no longer overrides logging you configured yourself.** The library
  sets up the root logger — stdout plus `var/little-sister.log` — only when nothing
  else has, which was already true of the handlers but **not** of the level: a
  `setLevel(DEBUG)` ran unconditionally at import, so a deployment that had chosen
  INFO quietly got DEBUG (and, with it, the third-party chatter the same module was
  suppressing). Configure your logging **before** importing `little_sister.app`, in
  the same block where you register check types, and it now stays exactly as you set
  it — with little-sister's own records arriving in it, since nothing here switches
  propagation off. A check type in its own package should call
  `logging.getLogger(__name__)` rather than importing a logger from little-sister.

- **The preference controls submit through a script instead of an inline handler.**
  The dashboard's filter switches and the settings menu's theme/layout radios used an
  `onchange` attribute, which no Content-Security-Policy can cover by hash or nonce.
  They now carry `data-ls-submit` and one delegated listener does the submitting;
  each form keeps a `<noscript>` Apply button, so a choice can still be applied
  without JavaScript. The login page's copy of the theme-resolving inline script was
  folded into the partial the header already used, so the two documents share one
  script — and one hash — rather than two. No behavior changes.


- **A nested box now ends its head line the way a card does: time and status
  word together, right-aligned.** A box used to append its time straight after
  the title with no status word at all, so the time read displaced and the state
  incomplete beside the cards. The box keeps its single leading shape cue; the
  status word (with the silenced reading beside it, where a pin applies) joins
  the topmost-visible time and staleness in one right-aligned cluster. With the
  word visible, a problem box's cue no longer needs its screen-reader name — the
  word is the accessible channel, on boxes as on cards; a coded reason line's
  labeled cue is unchanged. Under width pressure — action chips, long titles —
  the **title yields first**, shrinking into its ellipsis, and action chips sit
  **over the title's space** rather than beside it, so a chip to click never
  costs the row its state: a cluster never breaks between its time and its
  word, and never spills over the box below. Where a **card's** cluster sits is
  now the deployment's choice — `card_status_line` in `settings.yaml`: `beside`
  (the default) keeps the compact one-line head, `below` gives every card a
  standing second line — name, title and chips above, the time and status word
  right-aligned below — a calmer, more uniform grid that spends vertical space
  for it. The demo runs `below`; an unconfigured deployment's markup is
  unchanged.

- **The check time now shows on the topmost node visible in the current view — a
  branch check's container included — and is suppressed below, where it would be
  identical.** A branch page's head line carries its node's time, a nested box on
  the grid shows its own where no visible ancestor already shows the same one, and
  cards behave as before minus the duplicates — so one check writing seven aspects
  in one run reads as one observation, not seven. And an ancestor above one mount
  **shared by two checks** no longer inherits a stamp at all: the mount registry
  counts checks per path, so a value that would flip between the two checks' run
  times disappears instead of attributing one check's time to the other's data;
  the shared node itself still shows its own last write (ADR-0044; ADR-0027 as
  amended).

- **Maintenance can now end at a named time, not only after a calculated duration.**
  The shared field accepts unit-suffixed durations, full ISO dates/timestamps,
  yearless `MM-DD`, a day of month, a time of day, or a weekday with an optional time
  (bare weekdays use 12:00). Short forms choose their next future occurrence in the configured timezone; explicit offsets
  are respected, while ambiguous clock-change times and results outside the existing
  one-second-to-365-day bound are refused without writing. A click-opened format table
  beside every maintenance field makes the grammar discoverable. Persistence and the
  JSON shape are unchanged.

- Fully qualified bare `http://` and `https://` URLs in Markdown fields now render as
  links with the same new-tab and scheme-safety policy as explicit Markdown links.
  Hostnames without a scheme, email addresses, FTP, code spans and `plain()`-escaped
  captured output remain literal.

- **Maintenance explanations now read like content and edit only on intent.** Node
  and per-reason pins render their explanation as safe Markdown throughout the web
  interface, including the maintenance index, compact dashboard summaries, refused
  writes and the Copy page. Raw HTML remains escaped; editors preserve the exact
  Markdown source, and the persisted file and JSON schema are unchanged.

  A pinned item now opens in rendered read mode with explicit **Edit** and **Clear**
  actions. A per-reason control occupies a stable end rail and opens its anchored form
  only after a click, so moving the pointer down a long findings list no longer makes
  the form jump under the cursor. Pinned reasons can be reworded or extended in place
  with the same compare-and-set guard as node pins, without clearing them or briefly
  re-arming the finding.

- **The `node.actions` slot is now offered on every box the grid draws, not only on
  card heads.** A dependent package's whole-node action — the Jira chip a deployment
  fills it with — appeared on the top-level cards and on a leaf's own page, and
  nowhere in between. That is precisely backwards: a card at depth 1 is usually a
  *container*, whose reading is rolled up from below and whose own reason list is
  empty, while the thing actually on fire sits in a nested box two rows down. So the
  chip was offered where there was nothing to file a ticket about and withheld where
  there was, and the filler — which declines a node with no reasons — quietly rendered
  nothing on most dashboards.

  The slot now renders in `render_nodes` as well, with the same context (`node`,
  `surface`) and the same decline-by-returning-`None` contract. A quiet leaf still
  draws as a chip and carries no slot. Nothing is required of a filler that already
  exists: it is offered more often and declines as before. This widens a **version
  contract** — a package pinned to an older little-sister sees the old placement
  (ADR-0034).

### Fixed

- **A pinned container that no check has ever written no longer 500s on its
  history.** An admin pin is a real transition and lands on nodes a check never
  writes, but the history walk asserted that a node with a transition is stamped;
  the current period now simply has no end (rendered `—`) instead of taking the
  page down.

- **User avatars now sit beside the login list and appear in the settings trigger.**
  The existing `config/users.yaml` form remains valid; deployments that want custom
  pictures move it to `config/users/users.yaml`, put images in
  `config/users/avatars/`, and add `avatar: name` (or an explicit filename) to each
  relevant account. There is no separate registry: the value resolves directly inside
  that one directory, and a missing, invalid or ambiguous image falls back to the new
  packaged neutral avatar without affecting login.

  Custom bytes are exposed only through the signed-in user's username-free
  `/user/avatar` route, with a private short cache and ETag. The configuration
  framework still does not guess aspect shapes: `users` explicitly opts into file and
  directory forms, as dependent aspects do through their registration API (ADR-0045).

- **The dashboard now says when the next update is due.** Wherever a check time
  shows and the node is answered for by a single check, the armed next run joins
  it: `22:25 → 22:30` — on the grid's cards and boxes and the branch page's head
  line (the detail pages state it in words instead, in their Time card, where
  printing both would say it twice). The value is **engine-sourced**, never
  `timestamp + frequency` arithmetic: while you watch a failure, the fast retry
  slot is what shows. The format is absolute on purpose — when polling fails, the
  staleness dim leaves the page on screen, and a frozen relative "in 4m" would
  keep looking live while a frozen `→ 22:30` stays true and recedes into the
  past. Grid times drop their seconds with this — the whole pair is minute
  precision, saving the row width — and the arrow is suppressed where it would
  repeat the value beside it, so a sub-minute schedule shows a bare time. A
  mount two checks share and the leaves below a branch check keep their bare
  times. The run's wall time lands in the model beside it and surfaces in the
  node-facts block below; the JSON envelope is untouched until the client
  contract round.

- **A reason entry can carry its own status code — so one node's lines can
  disagree, and a running rerun no longer hides a failure.** A check whose lines
  have verdicts of their own (this workflow failed, that one passed) hands over
  `Entry(slug, text, code, running)` values and declares no node code at all: the
  node derives it from the lines, an empty entry set reads OK ("nothing to
  report" is not "nothing reported"), and declaring both is refused at
  construction rather than silently resolved. Pinning the one failing line now
  turns the node the worst of what is left — silencing one finding no longer
  discolors the rest — and pinning every line reads maintenance, exactly as with
  real children (ADR-0042).

  On the dashboard and the leaf page, every coded line paints its state's own
  measured tint with a small labeled shape cue (a line has no status word, so the
  cue is its accessible name) — a passed line is green even inside a red card,
  which is the point — and `running: true` renders in italic while the line's
  words still say it: a failed build's retry is legible at a glance without
  displacing the verdict.
  Existing checks change nothing: entries without codes keep carrying their
  node's, permanently. The JSON envelope is untouched; per-entry codes reach it
  with the client contract round. The live demo grows a `/ci/pipelines` node
  that walks the whole arc.

- **The Copy page now turns the live incident into paste-ready Markdown or rich
  text.** It keeps every non-OK leaf and only the ancestor chain needed to locate
  it, drops wholly healthy branches, preserves authored reason formatting, and
  marks status without relying on color. Maintenance stays accountable in the
  snapshot: whole-node and per-reason pins name who set them and when they expire,
  while a silenced node still shows the status it is suppressing.

  Both buttons use one immutable tree snapshot and one canonical Markdown document.
  **Copy Markdown** writes plain text; **Copy rich text** writes HTML with the same
  Markdown as its plain-text fallback. The page shows the exact source for manual
  copying when clipboard access is unavailable, and an all-OK tree gets a clear
  empty state instead of copying an empty document.


- **`./start.sh` now accepts both legal forms of the `users` aspect.** Its early
  preflight was still hard-coded to `config/users.yaml`, so it rejected the
  `config/users/users.yaml` layout that carries avatars before the app could load it.
  The preflight now follows `LITTLE_SISTER_CONFIG_DIR` in root order, accepts `.yaml`
  and `.yml` file or directory forms, and rejects the same duplicate or malformed
  shapes as the loader.

## [0.2.4] - 2026-08-02

### Fixed

- **A branch whose children are all silenced no longer reads as "nothing here has
  reported yet".** The roll-up skips a pinned child, and a parent with nothing left to
  count fell through to `UNDEFINED` — the idle state — so silencing every host in a
  rack turned the rack card gray and dropped it out of the view as unmonitored, rather
  than blue and accounted for. *We silenced everything under here* and *nothing under
  here has ever reported* are different facts and one of them is an operator's own
  doing. The parent now reads `MAINTENANCE` when a child was skipped because it is
  silenced, and stays `UNDEFINED` when the children have merely not reported.

  This is the edge case ADR-0032 left open, and the model had already
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
  content. The page centers itself in the window rather than piling its empty
  space underneath.
  Underneath, she says a line at a time: a couple of the ways systems go wrong,
  one longer observation, then nine short lines that end on the promise the page
  exists to make — and then it stops, so the story begins on a quiet page.
  **Color means something here.** Green is *seen*: it is spent only on the term
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
  ([ADR-0023](docs/adr/0023-secret-references.md)). **Breaking**
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


## [0.2.2] - 2026-07-19

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

## [0.2.0] - 2026-07-18

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
