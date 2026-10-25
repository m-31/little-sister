# ADR-0027 — Observation timestamps: stamped where written, rolled up while unambiguous

- **Status:** Accepted
- **Date:** 2026-09-20 (accepted 2026-08-01)
- **Related:** [ADR-0039](0039-status-rollup-semantics.md) (status roll-up),
  [ADR-0005](0005-dashboard-freshness-and-self-monitoring.md) (staleness),
  [ADR-0080](0080-the-envelope-is-the-snapshot-published.md) (JSON contract),
  [ADR-0120](0120-every-stored-time-is-an-instant.md) (timestamp storage & rendering).
- **Register:** [`../decisions.md`](../decisions.md)

## Context
`Status.timestamp` is meant to be the **observation time**: `update()` re-stamps it on
every check write, `touch()` on a maintenance-pinned refresh. But `__init__` stamped it
too, so a node **no check ever writes** — a container above the check mounts, the root
above all — served the **process start time** as its "observation" for as long as the
process lived. The effective *code* rolls up (ADR-0039); the timestamp did not, and the
asymmetry was easy to miss: `GET /status` returned a root `timestamp` equal to boot
time, and the menu-bar client's data-age line dutifully displayed a ten-day-old instant
as if it were current.

Meanwhile every node a check *does* write already carries a true stamp: the engine
upserts the check's whole result subtree on every run — leaves, inner branch nodes, and
the mount itself; two checks sharing one mount (host metrics plus a memory probe on one
host) each re-stamp it in turn.

The dashboard also wants to *show* when a check last ran; the freshness **alarm** is
already `stale`'s job (ADR-0005), normalized per check frequency.

## Decision
A node's timestamp answers one question — **"when did the check behind this node
run?"** — and it exists only where that question has **exactly one answer**:

1. **No stamp at construction.** `timestamp` is `None` until the node's first
   `update()` / `touch()`. Having a timestamp *means* a check has written the node.
   On a branch container, *having a timestamp* means *the check behind this node ran*.
2. **A written node shows its own last write.** A mount written by two checks shows
   the later of the two — still this node's own observation, no attribution needed.
3. **An unwritten ancestor with exactly one check mount in its subtree inherits that
   mount's stamp.** A deployment whose only check mounts at
   `/system/node_a/host_metrics` reports that check's run time on `/system/node_a`,
   `/system`, and `/` alike. The engine's own heartbeat node is not a check mount and
   never blocks (or feeds) this roll-up — its line is reserved and rendered as the
   status strip anyway ([ADR-0056](0056-stable-useful-dashboard-flow.md) decision 3).
4. **Two or more mounts below: no timestamp.** Any single value there would attribute
   one check's run time to another check's data.
5. **No aggregation statistics — deliberately.** `min(children)` ("nothing below is
   older") and `max(children)` ("something below is this fresh") are both rejected.
   Raw age across heterogeneous frequencies carries no signal: a healthy 90-day check
   would make a min-rolled root look ancient, and a reader would need each check's
   frequency to interpret the number — which is precisely the normalization `stale`
   already performs and rolls up. Codes aggregate (worst-of, ADR-0039); observation
   times do not. Whoever wants detail drills into the branch of interest, where every
   written node answers exactly.

**Mechanics.** The tree stores only own-observation stamps and stays check-agnostic;
the engine seeds its mount paths at startup (the shape of the metadata seeding,
[ADR-0012](0012-node-metadata.md)), and `snapshot()` resolves the displayed
timestamp — own stamp, sole-mount stamp, or `None` — in the same locked recursion that
computes effective code and staleness
([ADR-0002](0002-rlock-snapshot-synchronization.md)). Nothing derived is stored, so a topology change can never leave
a stale roll-up behind. The mount registry **counts checks per path** instead of
holding a set of paths, which enforces rule 4 by count rather than by the accident of a
node being unwritten: a set collapsed two checks legitimately sharing one mount (host
metrics beside a hardware probe) into one entry, so rule 3 stamped the **unwritten
ancestors above them** with a value that flips between two checks' run times — rule 4's
ambiguity, smuggled upward. With the count those ancestors inherit **no** stamp, while
the shared node itself still answers with its own last write (rule 2).

**Web.** A dashboard card shows its node's resolved time when present — rendered via
`localtime` as a time of day (ADR-0120 decision 7), inside the polled fragment so it
refreshes with the grid — and nothing when `None`. The detail page's Time block says "not yet
observed" instead of inventing an instant.

**JSON.** The snapshot semantics flow through unchanged (one snapshot, one truth):
`timestamp` becomes **nullable** in the contract, `null` exactly where the dashboard
shows nothing — notably the root of any deployment with more than one check. Clients
lose a root-level "data observed at" value at this stage; what an alerting client
should get instead — above all the *cause* behind a non-OK status, plus whatever
freshness view it needs — is deliberately deferred and designed with the client in
one contract change. Strictly, required-to-nullable is an incompatible change under
ADR-0080 decision 1's versioning rule; `schema_version` stays **1** until that round and the
formal bump is consolidated into it — the field's one consumer is first-party and
updates in lockstep.

That round is [ADR-0080](0080-the-envelope-is-the-snapshot-published.md), and it
settled the nullable field by **removing** it rather than by making it non-nullable:
a `run` object is **absent** where nothing answers for a node, and present with a
null `observed_at` where something answers and has never written. The two states this
record could only spell as one null are two there, and the bump deferred above
arrived with them.

## Consequences
- "Has a timestamp" now equals "unambiguously attributable" — boot time can no longer
  impersonate freshness, on the dashboard or over the API.
- Roll-up presence is **topology-dependent by design**: adding a second check under a
  container clears the container's inherited stamp, because the question stopped
  having one answer. The value never silently changes meaning — it disappears instead.
- `stale` is untouched: a never-written node was always exempt, and staleness already
  rolls up as any-below (ADR-0005).
- A branch check's own node **is** written — the engine stores the check's result at
  the check's own path on every run, exactly as this record's context says ("leaves,
  inner branch nodes, and the mount itself") — so no container sits stampless in the
  model; the gap is in rendering, and [ADR-0044](0044-run-facts-on-the-node.md)'s
  display rule (decision 5) is what closes it. What the engine will newly write is the
  run's **facts** — wall time and next run, which no upsert carries today
  ([ADR-0044](0044-run-facts-on-the-node.md) decision 4, a later slice).
- A branch container is subject to staleness, deliberately: a branch check that stops
  running degrades where it is named.
- The event log and `history()` only ever involve written nodes, so they carry real
  stamps as before (typing narrows; behavior doesn't change).
- `openapi.yaml` updates `timestamp`'s wording and required-ness in the same change as
  the code; the client-facing enrichment lands separately.

## Alternatives considered
- **Keep the construction stamp** — the lie this ADR removes.
- **min roll-up** (a freshness floor) — honest as a guarantee, useless as information
  (decision §5); its one consumer-facing benefit, a root data-age line, reads wrong
  exactly on deployments with slow checks.
- **max roll-up** — worse: hides a stalled branch behind the freshest sibling.
- **Leaf-only stamps** — discards true observations: mounts and inner branch nodes are
  directly written every run, and a shared mount has no single "owning check" while
  "when was this node last written" stays exact.
- **Storing the roll-up on the nodes** — needs invalidation on every topology change;
  deriving at snapshot time keeps one source of truth.
