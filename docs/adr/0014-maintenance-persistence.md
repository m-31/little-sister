# ADR-0014 — Persist maintenance to a file, with auto-expiry

- **Status:** Accepted
- **Date:** 2026-10-04 (accepted 2026-06-27)
- **Related:** [ADR-0001](0001-in-process-threaded-engine.md) (one process, in
  memory), [ADR-0002](0002-rlock-snapshot-synchronization.md) (the tree owns state),
  [ADR-0003](0003-config-and-secrets-via-env-file.md) (config / secrets in files),
  [ADR-0006](0006-config-file-and-timezones.md) (`settings.yaml`),
  [ADR-0015](0015-check-discovery-union.md) (the static check set the reaper keys
  off), [ADR-0008](0008-json-output-api.md) (JSON envelope, unchanged here),
  [ADR-0071](0071-what-a-restart-keeps-is-a-directory-of-files.md) (the state layer
  this file belongs to, and the path it moved to),
  [ADR-0104](0104-a-pin-is-one-block-on-what-it-silences.md) (the block that states a
  pin and holds its editor, the expiry an edit keeps, and the set that writes nothing),
  [ADR-0099](0099-a-status-that-still-holds-says-since-when.md) (an edit of a pin
  begins no period), [ADR-0109](0109-a-node-says-its-children-are-complete.md) (a pin
  is held against its path and makes no node),
  [ADR-0076](0076-the-instance-node-is-a-branch.md) (the instance's own branch, whose
  pins the reaper keeps),
  [ADR-0110](0110-what-every-node-last-showed-is-kept-beside-the-log.md) (the
  forgetting of what every node last showed, which takes the reaper's roots),
  [ADR-0120](0120-every-stored-time-is-an-instant.md) (a pin's times are instants,
  written in UTC and read strictly).
- **Register:** [`../decisions.md`](../decisions.md)

## Context
Maintenance (`project.md` §2.6) is a sticky admin override held **only in memory**
(`Status.maintenance` plus the tree's state). A restart loses it — the node reverts
to `UNDEFINED` and the next check can redden a system that is still intentionally
down. And maintenance currently **never ends**, so a forgotten or orphaned pin
lingers. A durable store is deferred to the persistence phase; maintenance needs a
restart-survival answer **sooner**, without pulling that decision forward.

## Decision
Persist maintenance to a small JSON file and restore it on startup; bound every
entry with an expiry.

1. **A maintenance side-table in the tree.** `StatusTree` owns
   `dict[path → entry]`, where an entry is `{reason, set_at, expires_at, set_by}`;
   `Status.maintenance` stays the in-tree bool that drives roll-up
   ([ADR-0004](0004-status-aggregation-semantics.md)) and the `upsert` guard.
   `set_maintenance` / `clear_maintenance` are the single choke points that keep the
   two in sync. A pin is held against its path and makes no node
   ([ADR-0109](0109-a-node-says-its-children-are-complete.md) decision 4), whether it
   is set, replayed at a start or adopted: `Status.maintenance` is the flag of a node
   the tree holds, and a node the tree makes at a pinned path takes it from the
   side-table.
2. **Write-through JSON at `var/state/maintenance.json`.** Every set / clear / expiry /
   reap rewrites the whole file **atomically** (temp + `os.replace`); the file is
   exactly the side-table serialized. It is runtime state the app writes (not
   hand-authored config), so the path is **fixed** (not env-overridable) and
   git-ignored. The file is one of the state layer's
   ([ADR-0071](0071-what-a-restart-keeps-is-a-directory-of-files.md)), which does the
   writing and holds every state file to this discipline; the move out of `var/` is a
   clean break in the spirit of decision 11 — the old path is not read, and a file
   still sitting there is named once at startup. A failed write keeps the in-memory
   state for the session — there is **no flush-on-shutdown**, so a crash right after a
   set never loses it — and it is a line on `/little-sister` under a stable slug, as
   is a file that could not be read at startup: what this decision left to the log,
   the layer says where somebody looks (ADR-0071 §4).
3. **Restore post-fork, before the engine starts** (single worker,
   [ADR-0001](0001-in-process-threaded-engine.md), so once). Replay each non-expired
   entry via `set_maintenance` — which makes no node
   ([ADR-0109](0109-a-node-says-its-children-are-complete.md) decision 4), so a replay
   before any check has run brings back the pins and no nodes: each node is pinned
   from its first reading, and a pin whose node its check has stopped reporting stays
   in the file, suspended, until the node returns or the pin expires. Already-expired
   entries are dropped and the file rewritten once.
4. **Auto-expiry.** Setting maintenance applies a **default duration** — one week,
   configurable in `settings.yaml` ([ADR-0006](0006-config-file-and-timezones.md)) —
   unless an explicit duration is given (`parse_duration`: `2h`, `3d`, `2w`, …). **No
   indefinite.** The scheduler ([ADR-0001](0001-in-process-threaded-engine.md))
   sweeps each tick and clears entries past `expires_at` via `clear_maintenance` — a
   real `MAINTENANCE → UNDEFINED` transition and event — and the next check refills
   the node.
5. **Orphan reaping at startup, by static check-root coverage.** After loading the
   checks and restoring the file, drop any maintenance entry whose path **neither a
   configured check nor the instance's own node covers.** A check at `full_path` *Q*
   **covers** path *P* when the two lie on the same root-to-leaf line, compared
   **segment-wise**: `P == Q`, *P* is an ancestor of *Q*, or *Q* is an ancestor of *P*.
   This keys off the **statically known check roots**, not the nodes a run happens to
   produce — so it is decidable immediately and is unaffected by a branch check that
   emitted only its root this run. The instance's own node and its children are written
   by no check: by the check roots alone, a pin on one of them — a node's or a line's —
   would be replayed at a start and then reaped as orphaned, though
   [ADR-0071](0071-what-a-restart-keeps-is-a-directory-of-files.md) decision 4 gives the
   state layer's lines stable slugs so that either can be pinned, and
   [ADR-0076](0076-the-instance-node-is-a-branch.md) decision 1 counts on pinning a
   child's one warning. So the reaping takes the instance's own root beside the roots of
   the configured checks, as the forgetting of what every node last showed does
   ([ADR-0110](0110-what-every-node-last-showed-is-kept-beside-the-log.md) decision 4).
   The check set is fixed for the process (no live reload,
   [ADR-0015](0015-check-discovery-union.md)), so once at startup suffices; expiry is
   the guaranteed backstop.

### Editing a pin, and two admins writing it
*(decided 2026-08-02; the entry shape in §1 and the form behavior grow, nothing above
is withdrawn)*

A pinned node used to offer exactly one control — *Clear* — so extending a window meant
clearing and re-setting: the node alarmed in the gap, and because a blank reason falls
back to the literal `maintenance`, the re-set usually threw the explanation away. And
the write had no precondition at all: `POST /maintenance` built a fresh entry and
overwrote whatever was there — reason, expiry and author — with nothing said, so two
admins pinning the same node a minute apart silently lost the first one's words. The
reason field is the whole point of a pin; losing it quietly is the bad kind of cheap.

6. **A pin is editable in place.** The set form is reachable **while pinned** and
   **prefilled with the stored reason**, beside *Clear*, in the block that states the
   pin (§16, [ADR-0104](0104-a-pin-is-one-block-on-what-it-silences.md)). The expiry
   field (§20) is filled with the stored expiry, and a field left as it was filled
   keeps that instant exactly; emptied, it means the configured default from now, as
   a blank field does on an unpinned node. Setting an already-pinned node is an
   **edit** — it keeps the entry, replaces reason and expiry, and never passes through
   an unpinned state.
7. **Both dates.** The entry becomes `{reason, set_at, expires_at, set_by, created_at,
   created_by}`. `set_at` / `set_by` mean **the last write that changed the pin** — a
   set that says what the stored pin says, the same reason and the same expiry, writes
   nothing ([ADR-0104](0104-a-pin-is-one-block-on-what-it-silences.md)) — and
   `created_at` / `created_by` mean the first. An entry that carries neither reads as
   its own creation: a pin set once and never edited. Clearing drops the entry, so a
   clear-and-re-pin — and an expiry sweep followed by a new pin — honestly starts a new
   creation; there is nothing extra to rule.
8. **The write is a compare-and-set.** Every form carries a hidden token, the entry's
   `set_at` as it is spelled ([ADR-0120](0120-every-stored-time-is-an-instant.md)); the
   write names the pin it believes it is replacing, and an empty token is the claim
   *"nothing is pinned"*. The comparison is **exact rather than
   best-effort**, because one process holds one lock
   ([ADR-0001](0001-in-process-threaded-engine.md),
   [ADR-0002](0002-rlock-snapshot-synchronization.md)). On a mismatch **nothing is
   written**; the admin gets a page showing *both* texts, naming who set the stored one
   and when, with their own words preserved and a one-click way to take the stored ones
   instead — losing the second author's work would be the same bug in a different coat.
   `action=clear` carries the same token: clearing someone else's pin should not be the
   one write that stays silent. A post carrying **no** token field at all — a
   hand-rolled client, never one of our forms — writes unguarded, as before.
9. **An edit emits an event.** Editing a pin is `MAINTENANCE -> MAINTENANCE`, which the
   status code alone cannot see, so an extended window or a rewritten reason would leave
   no trace anywhere. A changed **reason or expiry** therefore emits a transition too; a
   re-submit that changes neither does not, so a double-click is neither history nor a
   write (§7). History beyond that single event stays out. The event is in the log and
   on the Events page, and it begins no period
   ([ADR-0099](0099-a-status-that-still-holds-says-since-when.md) decision 6): a node's
   History view shows an edited pin as one row, and the node holds *maintenance since*
   its pin was set.

`set_at` doing double duty — the last-write stamp *and* the concurrency token — is why
both dates exist rather than one: `created_at` is then the one piece of history kept
without a history.

### Per-entry pins in the side-table
*(decided 2026-08-02, with [ADR-0036](0036-addressable-reasons.md); decision §1's key
space and §2's file shape grow, nothing above is withdrawn)*

10. **The key widens from `path` to `(path, slug)`.** A pin may name **one reason** of
    a node instead of the node ([ADR-0036](0036-addressable-reasons.md) decision 5).
    The two live in one side-table and one file, under separate keys, because they are
    one mechanism at two depths: the same entry shape, the same author and expiry
    fields, the same compare-and-set token, the same startup replay, the same coverage
    reap, the same sweep. Only the *effect* differs — a node pin writes
    `MAINTENANCE` into the tree, an entry pin writes nothing and is joined at snapshot
    time, which is what [ADR-0032](0032-status-contribution-boundary.md) rule 3 asks
    for and what the node pin does not yet do.
11. **The file holds two tables**: `{"nodes": {path: entry}, "entries": {path: {slug:
    entry}}}`. This is a **clean break** with the bare node table the file used to be —
    there is no reader for the old shape and no migration, in the spirit of the
    `config/` move ([ADR-0031](0031-deployment-config-directory.md)). An old file is
    ignored with a warning naming what it dropped, and the next save rewrites it. The
    cost is a pin or two on one upgrade; the alternative is a compatibility branch
    sitting in the read path forever, for state the program owns, never hand-authors,
    and bounds with a finite expiry anyway. A pin's `set_at`, `created_at` and
    `expires_at` are instants, written in UTC
    ([ADR-0120](0120-every-stored-time-is-an-instant.md)), and the file is read
    strictly: one of them without a zone refuses the file whole, as the bare node table
    is refused, so the pins of a version before that record are not in force after the
    upgrade.
12. **An entry pin emits no event.** It changes no stored code — the node's own status
    is derived at snapshot time — so there is no transition to record, exactly as
    staleness has none ([ADR-0005](0005-dashboard-freshness-and-self-monitoring.md)).
    A node whose entries all go quiet therefore reads `MAINTENANCE` without an entry in
    the log. That is the accepted price of not flooding the log with per-entry events
    ([ADR-0036](0036-addressable-reasons.md) decision 11), and the pin itself is
    visible on the node, in the maintenance surfaces and in `/maintenance`.

    > *That last clause was written ahead of the code and was untrue for a week:* the
    > index walked node pins only, so an entry pin reached none of those surfaces, and
    > a node whose members were all pinned showed a blue card the maintenance page
    > denied — a suppression with no entry in any index, which
    > [ADR-0032](0032-status-contribution-boundary.md) rule 5 forbids. Repaired
    > 2026-08-02; see [ADR-0036](0036-addressable-reasons.md) decisions 10 and 12
    > for the shape the two surfaces settled on. `/maintenance` now lists **one row per pin**
    > and gains a *Silenced* column — what a pin covers, as against *Why* it does —
    > because "reason" names two different things here and one heading over both is a
    > table nobody can read.

### A window is positive and bounded, and a blank field changes nothing
*(decided 2026-08-02, after review; decision §4's "always a finite expiry" is made
precise, nothing above is withdrawn)*

Three defects with one shape: a write that quietly did something other than what was
asked.

13. **A window must be positive, bounded, and long enough to silence a run.** At least
    one second and at most a year — and, because a window that ends before the check
    it covers runs again silences no run of it, at least the longest `frequency`
    among the checks that **cover** the pin, *covers* read exactly as §5 reads it.
    §4 said *finite*, and finite was not enough. `-1d` and `0` parse cleanly,
    land `expires_at` in the past, and the very next sweep drops the entry — so the
    reason text and both authorships are gone within a tick, behind a redirect that
    looked like a success. That is exactly the lost-explanation failure the
    compare-and-set guard exists to prevent, arriving through the other door. At the
    far end, `99999999d` and `1e20` parse and then raise `OverflowError` out of the
    date arithmetic, and `inf` raises it inside the duration parser — which is not a
    `CheckError`, so catching that alone turned a typo into a 500. A year is far past
    any real window and keeps the arithmetic nowhere near the overflow. The floor a
    frequency sets is refused the same way and named: the form says which check and
    what interval the window is held to, and an equal window passes, because one run
    lands inside it. Where **no** check covers the path, or the app cannot see the
    check set, the one-second floor is the whole of it. A pin that expired before its
    check ran again was the same defect in another coat: the stale reading came back,
    and the write had quietly done less than it said.
14. **Out of range is refused, not clamped.** The form comes back with the admin's
    words intact and a sentence saying what was wrong — the same page and the same
    posture as a refused compare-and-set, because the situation is the same: nothing
    was written, and the words are still theirs. An admin who typed `-1d` and silently
    got a week has learned nothing. The one value that still falls back is the
    deployment's **configured default**: a `settings.yaml` typo must not make the form
    unusable. A blank field therefore keeps that exemption whole — the default is
    never refused, and is held to no floor of §13's.
15. **A blank reason on an edit keeps the stored text.** Blank means *"I did not touch
    this field"*, so an edit that only moves the window keeps the explanation. On a
    **new** pin there is nothing to keep and the literal `maintenance` stays the honest
    placeholder. This is the same principle as the duration rule above: a field the
    admin left alone must not change anything.

### Read first, edit on intent
*(decided 2026-08-02; decision §6's in-place edit grows to entry pins and the form's
presentation changes, nothing above is withdrawn)*

A maintenance explanation is something viewers read far more often than an admin
changes it. Keeping its raw field permanently open makes it look like unfinished input,
and hiding a whole per-entry form behind hover made the pointer move the form it was
trying to reach. The two depths now follow one interaction.

16. **Pinned is a read state.** A pinned node or entry shows its rendered explanation,
    authorship and expiry with explicit *Edit* and *Clear* actions, in one block that
    states the pin where it acts — on a node's page, under a line, on the Maintenance
    page and in a card ([ADR-0104](0104-a-pin-is-one-block-on-what-it-silences.md)).
    *Edit* opens the editor there, with a prefilled textarea and the expiry field
    filled with the stored expiry (§6); *Save* is the same guarded `action=set`, and
    *Cancel* writes nothing. An unpinned item has one *Set maintenance* disclosure into
    the same editor.
17. **Entry pins edit in place.** The entry form carries `(path, slug)` and the stored
    entry's `set_at`, exactly as the node form carries `path` and its token. Rewording or
    extending one therefore never clears it and never lets the finding alarm in the
    gap. Blank reason and duration keep the rules in §§15 and 6.
18. **Hover never owns the form.** A member reason has a compact control in a stable
    action rail. Hover or focus may change its emphasis, but only activation opens the
    editor. This is a web presentation rule, not a new maintenance state.
19. **The persisted contract does not move.** Rendering and disclosure add no field and
    change no file shape. If a future maintenance change genuinely needs a different
    shape, it follows §11's hard-cut precedent — loud old-shape warning, new writes only,
    no migrator or compatibility reader — rather than making this UI pass a migration.

### Naming the expiry instead of calculating a duration
*(decided 2026-08-02; decision §4's explicit input widens, and §13's bound applies to
the resolved result; nothing persisted changes)*

An admin often knows *until when* a maintenance lasts — the end of a change window or
the next handover — and making them calculate `3h` from a clock is unnecessary work.
The form now accepts that boundary directly, with a small grammar rather than a
natural-language parser whose meaning changes by locale or library version.

20. **One field accepts duration or expiry.** Blank still means the configured default
    duration. Unit-suffixed durations (`17s`, `90m`, `2h`, `3d`, `2w` — a `w` is seven
    days) keep their meaning, and the suffix is **case-sensitive**: `6M` is refused by
    name rather than read as six *minutes*, because a month is not a number of seconds
    and a calendar belongs to the windows work
    ([ADR-0033](0033-budgeted-failure-retry.md)).
    The posted field remains named `duration`, but a digits-only value is now reserved
    for a day of the month: seconds must carry `s`. This compatibility cut is confined
    to the maintenance form; the shared check-configuration duration parser is
    unchanged.
21. **Calendar input has an enumerated grammar.** A full ISO date or timestamp is
    accepted; a date without a time ends at midnight. `MM-DD` means the next such date
    in ISO order, `1` through `31` means the next occurrence of that day at midnight,
    `HH:MM` means the next occurrence of that time, and `Mon 14:30` / `Monday 14:30`
    means the next matching weekday and time. A same-day midnight has already passed,
    so a month/day rolls to next year and a day-of-month rolls to the next month in
    which it exists; impossible days are skipped, never clamped. Locale-dependent date
    order and free-form prose are refused.
22. **Resolve once, in the operator's timezone.** The route captures one `now` for
    parsing and bounds. Unzoned calendar input uses `settings.yaml`'s timezone; `Z` or
    a numeric UTC offset wins when present. A DST hole or fold is refused and asks for
    an explicit offset. After resolution, the expiry must clear every floor §13 sets —
    one second, and the covering checks' longest `frequency` — and be at most 365 days
    away. It is an instant in UTC, which the tree stores as it is
    ([ADR-0120](0120-every-stored-time-is-an-instant.md)): nothing turns it back into
    the machine's clock.
23. **The grammar is visible at the field.** Every shared maintenance editor labels
    the control *Duration or expiry*, states the configured timezone and carries a
    click-opened, keyboard-native format table. It is closed by default and never
    depends on hover or placeholder text; a refused write returns the raw input and
    compare-and-set token unchanged.

### Giving a bare weekday a time
*(decided 2026-08-02; additive refinement of decision 21)*

24. **A bare weekday means noon.** `Fri`, `Friday` and case variants resolve to the
    next Friday at 12:00 in the configured timezone. When today already has that
    name, the result is the following week regardless of the current time. An explicit
    weekday time continues to win when supplied and may therefore still select today.

## Consequences
- Maintenance survives restarts; an intentionally-down system stays blue across a
  deploy.
- Nothing pins forever: expiry bounds forgotten and orphaned entries, and the sweep
  emits proper events so history stays honest.
- **Coverage keeps the legitimate cases.** A container / subsystem pin (use-case #3,
  `payments`) is covered because a check root sits *beneath* it; a branch-leaf pin
  (`system.alpha.disk`) is covered because the `host-metrics` root sits *above* it —
  even when the host is unreachable and that run wrote no `disk` leaf. Only a path
  with neither a check nor the instance anywhere on its line (a removed check) is
  reaped.
- `set_maintenance` gains `expires_at` / `set_by`; the maintenance form gains an
  optional duration; the detail page shows "set by X, expires …".
- Crash-safe: write-through at mutation time means a `kill -9` never loses a just-set
  pin.
- The persisted record is a small contract, and it is the durable state itself: what
  a database was going to subsume is a store per record behind a package's seam
  ([ADR-0071](0071-what-a-restart-keeps-is-a-directory-of-files.md) §6), never a
  service in the core.
- The JSON envelope ([ADR-0008](0008-json-output-api.md)) is **not** changed here;
  whether `maintenance_expires_at` joins it is the API-envelope round's decision.
- *(2026-08-02)* **The token is designed once and widens later.** Per-entry pins key the
  side-table by `(path, slug)` ([ADR-0036](0036-addressable-reasons.md)); the same guard
  has to cover them, which is why the concurrency answer lands before them rather than
  after.
- *(2026-08-02)* **The two dates read differently by surface**, following the density
  rules: the popover has room for one name and takes `set_by` — the writer whose reason
  text it is showing — a card's block says who set it and how long is left, and the
  whole four-field reading (*pinned by Anna three days ago, last changed by Ben an hour
  ago*) belongs on the node page and on the Maintenance page, where there is room for
  it. The second line appears only on a pin that has actually been edited.
- *(2026-08-02)* **A ticket reference will be a named field on the entry**, not text
  inside `reason` — so moving it to acknowledgment is later a migration and not a parse.

## Alternatives considered
- **Wait for the durable store.** Rejected: restart-survival and an expiry are wanted
  now and don't need the store's open choices settled.
- **Expire at render / snapshot time** (compute "expired" like staleness). Rejected:
  it desyncs the in-memory flag from the file and emits no transition event; a read
  shouldn't mutate.
- **Reap by observed nodes after a full cycle.** Rejected: a branch check that is
  unreachable on that cycle writes only its root, so its leaves don't exist yet — a
  legitimate pin on such a leaf would be wrongly reaped, and node existence isn't
  decidable on any single cycle. Static check-root coverage sidesteps the timing
  entirely.
- **Reap by exact check-path equality.** Rejected: a container / subsystem path is
  never a check `full_path`, so equality wrongly reaps legitimate subsystem
  maintenance (use-case #3).
- **No reaping; rely on expiry alone.** A valid simplification (≤ one-week bound);
  startup coverage is kept because it clears a removed check's pin promptly instead
  of waiting out the week.
- **Default to no expiry / allow indefinite.** Rejected for now: indefinite
  reintroduces the "stays forever" orphan; a generous default (one week) bounds it
  without cutting real windows short, and an admin can extend explicitly.
