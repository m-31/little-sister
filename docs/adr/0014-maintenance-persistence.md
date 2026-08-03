# ADR-0014 — Persist maintenance to a file, with auto-expiry

- **Status:** Accepted
- **Date:** 2026-06-25
- **Related:** [ADR-0001](0001-in-process-threaded-engine.md) (one process, in
  memory), [ADR-0002](0002-rlock-snapshot-synchronization.md) (the tree owns state),
  [ADR-0003](0003-config-and-secrets-via-env-file.md) (config / secrets in files),
  [ADR-0006](0006-config-file-and-timezones.md) (`config.yaml`),
  [ADR-0015](0015-check-discovery-union.md) (the static check set the reaper keys
  off), [ADR-0008](0008-json-output-api.md) (JSON envelope, unchanged here).
- **Register:** [`../decisions.md`](../decisions.md)

> **Update (2026-08-02):** the entry carries **both dates** and the write is a
> **compare-and-set** — see *Editing a pin, and two admins writing it* below. Decision
> §1's entry shape grows `created_at` / `created_by` beside `set_at` / `set_by`, and a
> pinned node's set form becomes reachable and prefilled, so extending a window is an
> edit rather than a clear and a re-set.
>
> The side-table's **key widens** the same day — `(path, slug)` for a pin on one
> reason ([ADR-0036](0036-addressable-reasons.md)) — so the file grows a second table;
> see *Per-entry pins in the side-table* below. The file's shape is a **clean break**,
> not a migration.
>
> A later pass the same day makes §4's *finite* expiry **positive and bounded**, and
> settles what a blank reason means on an edit — see *A window is positive and bounded*
> below.
>
> Everything else stands: the file is still the side-table serialized, restored once at
> startup, reaped by coverage, and every entry still carries a mandatory expiry.

## Context
Maintenance (`project.md` §2.6) is a sticky admin override held **only in memory**
(`Status.maintenance` plus the tree's state). A restart loses it — the node reverts
to `UNDEFINED` and the next check can redden a system that is still intentionally
down. And maintenance currently **never ends**, so a forgotten or orphaned pin
lingers. Full durable persistence is deferred to Phase 8; maintenance needs a
restart-survival answer **sooner**, without pulling that decision forward.

## Decision
Persist maintenance to a small JSON file and restore it on startup; bound every
entry with an expiry.

1. **A maintenance side-table in the tree.** `StatusTree` owns
   `dict[path → entry]`, where an entry is `{reason, set_at, expires_at, set_by}`;
   `Status.maintenance` stays the in-tree bool that drives roll-up
   ([ADR-0004](0004-status-aggregation-semantics.md)) and the `upsert` guard.
   `set_maintenance` / `clear_maintenance` are the single choke points that keep the
   two in sync.
2. **Write-through JSON at `var/maintenance.json`.** Every set / clear / expiry /
   reap rewrites the whole file **atomically** (temp + `os.replace`); the file is
   exactly the side-table serialized. It is runtime state the app writes (not
   hand-authored config), so the path is **fixed** (not env-overridable) and
   git-ignored. A failed write logs and keeps the in-memory state for the session —
   there is **no flush-on-shutdown**, so a crash right after a set never loses it.
3. **Restore post-fork, before the engine starts** (single worker,
   [ADR-0001](0001-in-process-threaded-engine.md), so once). Replay each non-expired
   entry via `set_maintenance` — which auto-creates the node, so replay before any
   check has run is safe (`upsert` respects the flag). Already-expired entries are
   dropped and the file rewritten once.
4. **Auto-expiry.** Setting maintenance applies a **default duration** — one week,
   configurable in `config.yaml` ([ADR-0006](0006-config-file-and-timezones.md)) —
   unless an explicit duration is given (`parse_duration`: `2h`, `3d`, …). **No
   indefinite.** The scheduler ([ADR-0001](0001-in-process-threaded-engine.md))
   sweeps each tick and clears entries past `expires_at` via `clear_maintenance` — a
   real `MAINTENANCE → UNDEFINED` transition and event — and the next check refills
   the node.
5. **Orphan reaping at startup, by static check-root coverage.** After loading the
   checks and restoring the file, drop any maintenance entry whose path **no
   configured check covers.** A check at `full_path` *Q* **covers** path *P* when the
   two lie on the same root-to-leaf line, compared **segment-wise**: `P == Q`, *P* is
   an ancestor of *Q*, or *Q* is an ancestor of *P*. This keys off the **statically
   known check roots**, not the nodes a run happens to produce — so it is decidable
   immediately and is unaffected by a branch check that emitted only its root this
   run. The check set is fixed for the process (no live reload,
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
   **prefilled with the stored reason**, beside *Clear*, on both surfaces (the node
   page's maintenance card and the card dialog). Duration is deliberately **not**
   prefilled: blank means the configured default here exactly as it does on an unpinned
   node, so there is one rule to know rather than a context-dependent one. Setting an
   already-pinned node is an **edit** — it keeps the entry, replaces reason and expiry,
   and never passes through an unpinned state.
7. **Both dates.** The entry becomes `{reason, set_at, expires_at, set_by, created_at,
   created_by}`. `set_at` / `set_by` keep meaning **the last write**, which is what the
   code always stored — every set rebuilds the entry — and `created_at` / `created_by`
   mean the first. An entry that carries neither reads as its own creation: a pin set
   once and never edited. Clearing drops the entry, so a clear-and-re-pin — and an
   expiry sweep followed by a new pin — honestly starts a new creation; there is
   nothing extra to rule.
8. **The write is a compare-and-set.** Every form carries the entry's `set_at` as a
   hidden token; the write names the pin it believes it is replacing, and an empty token
   is the claim *"nothing is pinned"*. The comparison is **exact rather than
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
   re-submit that changes neither does not, so a double-click is not history. History
   beyond that single event stays out.

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
    and bounds with a finite expiry anyway.
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
    > 2026-08-02; see [ADR-0036](0036-addressable-reasons.md)'s second update for the
    > shape the two surfaces settled on. `/maintenance` now lists **one row per pin**
    > and gains a *Silenced* column — what a pin covers, as against *Why* it does —
    > because "reason" names two different things here and one heading over both is a
    > table nobody can read.

### A window is positive and bounded, and a blank field changes nothing
*(decided 2026-08-02, after review; decision §4's "always a finite expiry" is made
precise, nothing above is withdrawn)*

Three defects with one shape: a write that quietly did something other than what was
asked.

13. **A window must be a positive, bounded number of seconds** — at least one, at most
    a year. §4 said *finite*, and finite was not enough. `-1d` and `0` parse cleanly,
    land `expires_at` in the past, and the very next sweep drops the entry — so the
    reason text and both authorships are gone within a tick, behind a redirect that
    looked like a success. That is exactly the lost-explanation failure the
    compare-and-set guard exists to prevent, arriving through the other door. At the
    far end, `99999999d` and `1e20` parse and then raise `OverflowError` out of the
    date arithmetic, and `inf` raises it inside the duration parser — which is not a
    `CheckError`, so catching that alone turned a typo into a 500. A year is far past
    any real window and keeps the arithmetic nowhere near the overflow.
14. **Out of range is refused, not clamped.** The form comes back with the admin's
    words intact and a sentence saying what was wrong — the same page and the same
    posture as a refused compare-and-set, because the situation is the same: nothing
    was written, and the words are still theirs. An admin who typed `-1d` and silently
    got a week has learned nothing. The one value that still falls back is the
    deployment's **configured default**: a `settings.yaml` typo must not make the form
    unusable.
15. **A blank reason on an edit keeps the stored text.** Blank means *"I did not touch
    this field"*, so an edit that only moves the window keeps the explanation. On a
    **new** pin there is nothing to keep and the literal `maintenance` stays the honest
    placeholder. This is the same principle as the duration rule above: a field the
    admin left alone must not change anything.

## Consequences
- Maintenance survives restarts; an intentionally-down system stays blue across a
  deploy.
- Nothing pins forever: expiry bounds forgotten and orphaned entries, and the sweep
  emits proper events so history stays honest.
- **Coverage keeps the legitimate cases.** A container / subsystem pin (use-case #3,
  `payments`) is covered because a check root sits *beneath* it; a branch-leaf pin
  (`system.alpha.disk`) is covered because the `host-metrics` root sits *above* it —
  even when the host is unreachable and that run wrote no `disk` leaf. Only a path
  with no check anywhere on its line (a removed check) is reaped.
- `set_maintenance` gains `expires_at` / `set_by`; the maintenance form gains an
  optional duration; the detail page shows "set by X, expires …".
- Crash-safe: write-through at mutation time means a `kill -9` never loses a just-set
  pin.
- The persisted record is a small contract; Phase 8's durable store subsumes this
  file — the side-table is the seam.
- The JSON envelope ([ADR-0008](0008-json-output-api.md)) is **not** changed here;
  whether `maintenance_expires_at` joins it is the Phase 2 API item.
- *(2026-08-02)* **The token is designed once and widens later.** Per-entry pins key the
  side-table by `(path, slug)` ([ADR-0036](0036-addressable-reasons.md)); the same guard
  has to cover them, which is why the concurrency answer lands before them rather than
  after.
- *(2026-08-02)* **The two dates read differently by surface**, following the density
  rules: the popover has room for one name and takes `set_by` — the writer whose reason
  text it is showing — the card dialog says who set it and how long is left, and the
  whole four-field reading (*pinned by Anna three days ago, last changed by Ben an hour
  ago*) belongs on the node page and in the `/maintenance` table, where there is room
  for it. The second line appears only on a pin that has actually been edited.
- *(2026-08-02)* **A ticket reference will be a named field on the entry**, not text
  inside `reason` — so moving it to acknowledgment is later a migration and not a parse.

## Alternatives considered
- **Wait for the Phase 8 store.** Rejected: restart-survival and an expiry are wanted
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
