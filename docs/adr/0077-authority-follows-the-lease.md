# ADR-0077 — Authority follows the lease: a state file is adopted in a running process

- **Status:** Accepted
- **Date:** 2026-09-05
- **Related:** [ADR-0071](0071-what-a-restart-keeps-is-a-directory-of-files.md) (the
  state layer and the keeper seam this record gives a second direction; its §5 points
  here), [ADR-0072](0072-the-instance-reports-on-itself.md) (the lines, and the rule
  that a report is recorded state and never a probe),
  [ADR-0076](0076-the-instance-node-is-a-branch.md) (the `state` child the backups are
  listed on, and the action seam *take the backups* uses),
  [ADR-0014](0014-maintenance-persistence.md) (the pins, whose replacement at runtime
  is a transition like any other), [ADR-0002](0002-rlock-snapshot-synchronization.md)
  (the lock the swap is made under and held no longer than the swap)
- **Register:** [`../decisions.md`](../decisions.md)

## Context

The first keeper holds a lease on its prefix (little-sister-aws ADR-0004): one
instance writes the store, and a second on the same prefix stands by, reading the
lease and saving nothing. The first real run with two instances showed what the lease
alone does not settle. A standby restores the store at startup and then keeps its own
state for as long as it stands by — pins set on it, the events it observes — while the
holder keeps writing the store. When the holder's lease lapses and the standby takes
it, the seam's rule so far was *its own state is what it writes*, and the standby's
first save put hours-old pins over what the holder had written. A rollout produces
exactly that overlap: the new instance up first, the old one terminated minutes
later. For the successor of a holder that died before anybody wrote again the rule was
right — its state is the predecessor's plus what happened since — and for two alive
together it was wrong.

The state layer could not do the alternative: it restores files before anything
reads them, at startup, and has no way to replace what the process holds afterwards.
A keeper, for its part, moves bytes and knows nothing about the files.

## Decision

1. **Authority follows the lease.** Whoever holds the lease wrote the truth up to the
   moment it lapsed. An instance that stood by holds a *shadow* of the store — never
   its competitor — and when it becomes the holder it continues with the store's
   state, not its own. It needs no operator, because a deployment under an autoscaling
   group has none.

2. **A state file has a second direction: `restore`.** Beside the producer of a kept
   file (`keep(name, producer, restore=…)`), or on its own for a file written through
   (`restore_with(name, restore)`), a callable takes the parsed payload of an adopted
   copy and replaces what the running process holds — under the process's own lock,
   and never inside it for longer than the swap. The event log's replaces the log
   wholesale; the side-table's clears every pin the new table lacks with a real
   transition, applies every pin it carries as a set or an edit with the event each
   earns, and replaces the per-entry pins whole — nothing is written through, since the
   file on disk is the copy being adopted. Both are written into one registry of
   `restore` callables keyed by name — `keep(…, restore=)` is sugar over
   `restore_with` — by their owners: the tree's `adopt_events` beside the log's
   producer, and the side-table's by `MaintenanceStore` at construction, where the
   file's shape is known. Files are adopted in registration order, so the log is
   registered before the pins whose adoption writes into it. Nothing else registers
   until the series file exists.

3. **The keeper may answer `changed_since_sync()`**: the names of the files whose copy
   in the store differs from what this instance last restored or last saved, by
   whatever token the store keeps — S3's ETag, a version, a checksum. The library never
   sees the token. A keeper without the method names nothing, which is what every keeper
   did before; one whose answer raises, or names something that is not a state file
   name, has failed its tick — the WARN line ADR-0071 already carries — and no save
   runs behind it that interval; it is asked again the next.

4. **The moment is the flip.** When the keeper's `tick` turns from *not taking saves*
   to *taking them* — a standby became the holder, a demoted holder took the lease
   back, or the first interval a keeper takes at all — the layer asks, and adopts every
   name answered before this interval's first save. The order on the keeper's side is
   *take the lease, then let the layer adopt, then save*, so the store is frozen while
   it is read. A keeper that names nothing makes it a silent takeover: the successor of
   a holder that died before anybody wrote again continues with its own state, which
   is the case that must work out of the box.

5. **Adoption is the process first, then the disk — and on the disk, the temporary
   file first.** The store's copy is parsed and handed to `restore`; then it is written
   to the temporary file, the live file set aside as `<name>.bak` — an older one
   overwritten — and the temporary file renamed into place: the one write that can
   fail fails before anything has moved, the two renames in one directory leave no
   moment with the live file gone, and should the last of them fail all the same, the
   live file is put back from `.bak` before the failure is raised. Then the digest the
   mirror compares against is seeded with the bytes that landed, so what arrived from
   the store is not sent back until it changes. A copy whose bytes are the local
   file's already — a token that moved without its bytes moving — is nothing to adopt:
   the digest is seeded and no `.bak` is made of a file for its own copy. A file with
   no `restore` is set aside and written but not swapped in memory, and its line says
   so. The order makes every failure leave a consistent
   state: a copy the process cannot take — not JSON, a `restore` that raises — changes
   nothing, and a disk that refuses moves nothing; each is the `load.<file>` line at
   ERROR, with *adopt* as the verb, standing until an adoption of that file lands.

   **A file whose adoption failed is held out of the mirror until one lands.** The
   instance holds the lease now and the interval's saves run — and a save of that file
   would put its shadow over the authoritative copy, the one thing the rule forbids;
   without the hold the failure path would be worse than the rule it replaces. Every
   interval the keeper takes saves, the held files are adopted again **by name**, not
   through `changed_since_sync()`: a token that differs because *this instance's* last
   save failed names a file it rightly holds newer, and adopting the store's copy of
   that would overwrite it. The hold lifts with the adoption that lands, or with a
   store that no longer holds the file, since there is nothing left to overwrite.

6. **The `.bak` is the only copy kept, and it never leaves the machine.** It is this
   instance's shadow of the store — the three minutes a successor observed before it
   took over, or hours of a standby's own pins — excluded from the mirror like a
   half-written file, because a keeper that carried it would hand it to the next
   instance as a state file; and refused from a keeper's listing by the same rule that
   refuses a walk upwards, at startup and at a takeover alike, since a store that offers
   `maintenance.json.bak` is not offering a state file. What is lost is the gap between
   the holder's last heartbeat and the takeover; merging it into the store's log would
   be the merge ADR-0004 refused.

7. **What was set aside is shown, and the way back is a button.** The `state` child on
   `/little-sister` lists every `.bak` in the directory in its `report` — a fact, not a
   line ([ADR-0076](0076-the-instance-node-is-a-branch.md) decision 1): when it was
   last written beside when the live copy was, both local files on one clock, from
   stamps the layer records as it writes and reads once from the disk at startup
   (`take_stock`), never from a stat at report time (ADR-0072). *Take
   the backups* is the layer's one action on that child, admin-only through the seam of
   ADR-0076: for every `.bak` beside a file the layer keeps or restores, the live file
   is set aside as `.bak` in turn and the backup written back and handed to the same
   `restore` — a second caller of the adoption, not a second mechanism — and the mirror
   then takes what came back, since the store holds what was live. A `.bak` whose name
   matches no registered file is listed and left alone.

8. **`restore_from_keeper` seeds the same digest** for every file it writes, so the
   first flush after a start no longer sends every restored file back once — found on
   the way and fixed beside it, the same rule as decision 5.

## Consequences

- An instance that stood by while another held the lease takes over with the store's
  pins and events and not its own, keeps what it had as `.bak`, shows it, and can take
  it back on a button; the successor of a holder that died before anybody wrote again
  takes over with its own state, silently. Both are tests on the real tree.
- The keeper seam gains one optional method; the S3 keeper's half — the ETag per key,
  the takeover line, *take the lease, then adopt, then save* — is that repository's
  next slice, and until it ships every takeover is the silent kind.
- `StateLayer` gains `restore_with`, `take_stock` and `take_backups`, a `wall` clock
  beside the monotonic one, and a `.bak` beside a live file whenever an adoption
  replaced it. A package that keeps its own file under `var/state/` sees it adopted on
  disk with a WARN line until it registers a `restore` of its own or the instance
  restarts.
- The two adoptions — the flush's and the button's — are serialized on a lock of their
  own, so a takeover on the scheduler thread and an admin's press cannot rename the
  same file under each other; a pin written through never waits on it.
- Every failure of an adoption is the `load.<file>` line ADR-0071 already has, under
  the same slug, so a pin on it silences the takeover's version too — but not the
  hold, which is the rule and not a report: a held file is out of the mirror until an
  adoption lands, pinned or not.

## Alternatives considered

- **Keep the rule *its own state is what it writes***. Right for the dead-holder
  successor, wrong for every rollout; rejected the day the first rollout showed it.
- **Merge the standby's observations into the store's log at takeover.** The merge
  ADR-0004 refused, for three minutes of observations the dead holder mostly made too.
- **Restart the standby instead of adopting**: a restart restores the store and needs
  no runtime swap. A standby under an autoscaling group is the instance that is about
  to serve; killing it to make it right is the rollout failing on purpose, and a demoted
  holder that takes the lease back has nobody to restart it.
- **The `.bak` in the store, versioned.** One copy per file is ADR-0004's decision,
  to be revisited when the series file joins the store; the shadow is one instance's
  and belongs on that instance.
- **List the `.bak` files from the disk at report time.** A stat is cheap and this is
  the local disk, and the rule of ADR-0072 is that a report never measures; the stamps
  cost one scan at startup and one assignment per write.
- **Adopt the disk first, then the process**, as the rule reads. Unobservable on the
  success path; on failure it leaves the disk holding the store's copy and the process
  its own, which the next flush of a kept file then writes over. Process first leaves
  nothing to repair after the failure it reports.
- **Rename the live file to `.bak` and then write the store's copy in place.** The
  same result, with a moment in which the live file is gone and its replacement not yet
  there: harmless while the process lives, and a crash in that moment restarts with
  that state empty. The temporary file first costs nothing and closes it.
- **Save the local copy of a file whose adoption failed**, as any other file. That is
  the standby's shadow over the store, the exact thing the rule forbids, on the one
  path where the store is known to hold something newer. The hold is the smaller cost.
- **Retry a held file by asking `changed_since_sync()` again.** The natural probe, and
  the token does still differ — but the same answer names a file whose token differs
  because this instance's own save failed, and adopting that would overwrite state it
  rightly holds newer. Retrying by name asks the store only about the files in question.
