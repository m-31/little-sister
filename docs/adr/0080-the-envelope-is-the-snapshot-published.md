# ADR-0080 — The envelope is the snapshot, published: `schema_version` 2

- **Status:** Accepted
- **Date:** 2026-09-20 (accepted 2026-09-06)
- **Supersedes:** [ADR-0008](0008-json-output-api.md) wholly (accepted 2026-06-27,
  rewritten 2026-08-23). Everything that record decided and this one keeps is
  restated below with its original reasoning, so nothing has to be read out of a
  superseded record: the unversioned routes and content negotiation, the top-level
  envelope object, Problem JSON, the bearer token, the single OpenAPI document, and
  read-only. What changes is the **node**, and one rule about how it may change again.
- **Related:** [ADR-0002](0002-rlock-snapshot-synchronization.md) (the snapshot this
  publishes), [ADR-0032](0032-status-contribution-boundary.md) (the three statuses and
  the fourth this names for the first time),
  [ADR-0036](0036-addressable-reasons.md) / [ADR-0042](0042-entries-carry-their-own-code.md)
  (the entry vocabulary), [ADR-0014](0014-maintenance-persistence.md) (the pin's
  details), [ADR-0044](0044-run-facts-on-the-node.md) (the run facts and their
  ownership rule), [ADR-0027](0027-observation-timestamp-semantics.md) (the nullable
  stamp this retires), [ADR-0055](0055-sibling-order.md) (the rank),
  [ADR-0063](0063-declining-the-density-trade.md) (`show_when_quiet`),
  [ADR-0078](0078-the-unit-is-what-the-engine-releases.md) (whose unit the run facts
  now follow), [ADR-0079](0079-freshness-is-a-stated-tolerance.md) (the tolerance
  beside the verdict), [ADR-0005](0005-dashboard-freshness-and-self-monitoring.md)
  (`stale`), [ADR-0039](0039-status-rollup-semantics.md) (the roll-up),
  [ADR-0003](0003-config-and-secrets-via-env-file.md) (the token)
- **Register:** [`../decisions.md`](../decisions.md)
- **Contract:** [`../api/openapi.yaml`](../api/openapi.yaml) — the normative schema.

## Context

The dashboard and the JSON API are two views of one thing, and they stopped agreeing.
Everything a page renders comes from `StatusSnapshot` (ADR-0002): three status codes,
keyed entries that can each be pinned and can each carry their own code, a maintenance
pin with who and why and until when, the last run's wall time and next slot, the
check's own text, the declared sibling rank. The envelope publishes an older, smaller
projection of that: `reasons` as bare strings, `maintenance` as a bool beside a details
object, one `timestamp` that is sometimes null, and nothing at all for
`reported_code`, `report`, `order`, `show_when_quiet` or the run facts.

The gap is not an oversight; it is what a rule that says *additive only* does over
eight months. Each field held back was held back correctly — ADR-0027 could not make
`timestamp` non-nullable without breaking a client, ADR-0036 could not spend the name
`reasons` twice, ADR-0042 and ADR-0044 and ADR-0055 and ADR-0063 each ended with *this
half rides the client contract round* — and each of those sentences named this round
rather than shipping into a shape that could not hold it. So the debt is deliberate and
this is where it is paid.

Two things make paying it cheap now. Every consumer is ours: the macOS client and the
four packages are internal, so there is nobody to keep a compatibility window for.
And the two decisions that would have forced a second break — whether the engine
releases units ([ADR-0078](0078-the-unit-is-what-the-engine-releases.md)) and what
*stale* measures against ([ADR-0079](0079-freshness-is-a-stated-tolerance.md)) — were
taken first, precisely because each turned out to be a field of this envelope.

## Decision

### 1. The envelope is the snapshot, published — and stays that way

Everything the dashboard renders it renders from `StatusSnapshot`. A client that reads
the envelope holds the same facts and no others, so that *what a client can show* is
never a second question beside *what the page can show*.

The rule that keeps it closed: **a field added to the snapshot is added to the envelope
in the same change.** Such an addition is compatible — `schema_version` stays 2 and the
spec's `info.version` moves a minor, ADR-0008 decision 6's rule kept — so the cost is a
line of serialization and a line of schema, paid by whoever adds the field rather than
by whoever notices the gap two releases later. It is also what makes a `schema_version`
3 unlikely: a major version is now only for a field that **changes meaning** or goes.

The rule cuts both ways, and the second edge is the one that needs saying: **the
envelope does not publish what the snapshot cannot produce.** A field declared in the
schema and never emitted is a promise no test can check and no reader can trust. So the
entry keeps `slug`, `text`, `code`, `running` and `maintenance` here, and `subject`,
`observed_at` and `data` join it in the change that adds them to the snapshot — a minor
under this rule, invisible to a client that does not want them. Tags are the same case
and were always going to be: nothing is reserved for them here.

`subject` and `data` took exactly that route: they joined the entry with the change
that put them in the snapshot, `schema_version` stayed 2 and the spec moved to 2.1.0
([ADR-0082](0082-a-line-carries-what-it-is-about-and-what-it-read.md)). `observed_at`
is still unpublished, for the reason above — nothing can emit it yet.

**The rule has a second half, and it is an obligation rather than a rule.** One
envelope is written down — `src/little_sister/contract/envelope-2.json`, generated from
this API, shipped in the wheel and shared with the client, so both sides test one
artifact instead of two hand-written ones. A field added to the snapshot is therefore
added to the contract **and the artifact regenerated**, all in the same change:
`python tests/test_contract_fixture.py` rewrites it and the diff is the review. Left to
a follow-up it is not a follow-up at all — it is a red gate somebody meets later and
has to reconstruct the reason for. The same holds for a field that changes meaning: the
artifact is the only place the shape is written as a *value*, and a value nobody
regenerates is the one that teaches the old shape. That is not hypothetical — the
artifact's first version carried only `contribution.code: null`, because every rule at
that boundary withheld until damping
([ADR-0083](0083-a-node-may-wait-before-it-escalates.md)) transformed one, and a client
written against it would have read the withheld case right and the damped case wrong.

### 2. A node carries three statuses and says what its parent counted

`reported` (what the check said), `own` (the first derived value — a pin, or a member
set every one of whose entries is pinned) and `code` (the effective, rolled-up,
stale-degraded status) are [ADR-0032](0032-status-contribution-boundary.md)'s three
statuses under their own names. `own_code` is renamed `own` and `reported` is published
for the first time; a display client still reads `code`, and a federating parent still
grafts `own` plus `children` and re-rolls locally rather than double-aggregating.

`contribution` is the fourth value that record defines and no surface has ever
published: what this node's **parent accumulated**, and the rule that made it so.

- It is **null** when the parent counted the node's `code` — which is the ordinary
  case, so the field costs nothing on a healthy tree.
- Otherwise it is `{"code": …, "by": …}`. `code` is what the parent counted, and
  **null means the node was not counted at all** — which is what *contributes nothing*
  has always meant for `MAINTENANCE` and `UNDEFINED` (ADR-0004 §2/§3, restated from
  the node's side by ADR-0032 decision 2). `by` names the rule: `maintenance` and
  `undefined` today, a shield or a cap or a damping counter when those land, each an
  added enum value and therefore a compatible change.

This is [ADR-0032](0032-status-contribution-boundary.md) rule 5 — *a transformed
contribution is visible and attributable* — reaching the API at last, and it is what
lets a client explain a red root by walking down it instead of guessing.

### 3. `entries` replaces `reasons`

An object, not an array, because prose and members are different things
([ADR-0036](0036-addressable-reasons.md)):

```json
"entries": {
  "addressable": true,
  "items": [{"slug": "stress-api-pr-42", "text": "PR #42 waiting 6d",
             "code": "WARN", "running": false, "maintenance": null}]
}
```

`addressable` is the snapshot's `members`: whether these items may be pinned one by
one. Each item is the `ReasonLine` the snapshot already holds — `slug` the key
([ADR-0036](0036-addressable-reasons.md)), `text` raw Markdown as before, `code` the
entry's own where the check declared one and **null** where it carries the node's
([ADR-0042](0042-entries-carry-their-own-code.md)), `running` display-only work in
flight, `maintenance` the pin on this entry or null. Order is the check's order and is
never sorted. The bare string array goes; a client that wants the old shape reads
`items[].text`.

### 4. `maintenance` is one object or null

The bool and `maintenance_details` were one fact in two fields, and the bool is the
half that cannot say anything. One nullable object takes both slots — the node's and
the entry's — carrying `note`, `set_by`, `set_at`, `expires_at`, `created_by` and
`created_at`. Both dates always ship, because both are always kept: an entry whose
creation was never recorded reads its set, so there is no absent case to describe
([ADR-0014](0014-maintenance-persistence.md)). *Pinned* is `maintenance !== null`.

**The text is `note` and the model still calls it `reason`**, which is the one place
this record lets the two names differ. [ADR-0047](0047-node-notes-and-their-retention.md)
renames the field when the note history is built, and a rename is a *breaking* change
to this contract — so publishing `reason` today would buy a second major version for
one word. This is the release in which changing it costs nothing, so it is changed
here: the value is what it always was, and the name is the one that will be true.

### 5. `run` replaces `timestamp` and `frequency_seconds`

[ADR-0044](0044-run-facts-on-the-node.md)'s run facts, under the ownership rule that
record states and [ADR-0078](0078-the-unit-is-what-the-engine-releases.md) generalizes:
`run` is present exactly where **one unit answered for this node**, and **absent — not
null** — everywhere else. A one-unit check is the statement ADR-0044 already makes; a
check that reads many things stamps each unit's own subtree, which is why the block may
appear below the node a check is mounted at.

```json
"run": {"observed_at": "…", "wall_seconds": 3.2, "next_at": "…",
        "frequency_seconds": 420, "stale_after_seconds": 840}
```

`observed_at` is this node's own last write. `wall_seconds` is null for a
secret-pinned check, which never runs. `next_at` is the engine's armed slot, projected
once at write time — never `observed_at + frequency`, because a failing check's slot is
pulled in ([ADR-0033](0033-budgeted-failure-retry.md)) and the arithmetic answer is
confidently wrong exactly when somebody is watching a failure.
`stale_after_seconds` is the tolerance freshness actually applied, whichever rule
produced it ([ADR-0079](0079-freshness-is-a-stated-tolerance.md)), and is absent
together with `frequency_seconds` where the node is read on no schedule and can
therefore never be stale by its own stamp. The `unit` key
[ADR-0078](0078-the-unit-is-what-the-engine-releases.md) decision 5 names arrives with
the units themselves, by decision 1 above: nothing can produce a unit name until the
scheduler releases units, and a key that is null in every response of every release
until then is exactly the promise this record declines to make. What that decision
owed *this* round is not the key but the **rule** — that `run` may appear below the
node a check is mounted at — and the rule is in the sentence above and in the schema,
where a client reads it.

**Absent, not null, is the point**, and it buys a distinction the old shape could not
draw. The block is **absent** where nothing answers for the node; it is **present with
a null `observed_at`** where something answers and has never written — a check pinned
by an unresolvable secret, which never runs and still has an armed slot
([ADR-0023](0023-secret-references.md)), or one that has simply not run yet. Those
were one null before this version, which is ADR-0008's own rule broken under pressure
([ADR-0027](0027-observation-timestamp-semantics.md) said so when it made the change),
and the cost was concrete: a client that guessed read a container's inherited stamp as
its own data age. Inside the block a null stays a fact of its own — `wall_seconds` for
a check that never ran, `next_at` for a one-shot with no live schedule.

`stale` stays exactly what it is — a boolean the server computed, which the client
shows and never recomputes from a clock it does not share
([ADR-0005](0005-dashboard-freshness-and-self-monitoring.md)).

### 6. Three fields the page has and the envelope never had

`report` — what the run **found**, beside `config`'s what it ran **with**, under the
same ownership rule as the run facts ([ADR-0044](0044-run-facts-on-the-node.md));
`order` — the declared sibling rank the children were sorted by
([ADR-0055](0055-sibling-order.md)), so a client can *see* the order it was handed
rather than infer it from the sequence; and `show_when_quiet` — the tri-state
([ADR-0063](0063-declining-the-density-trade.md)), null where nobody said, where a
stated `false` is a declaration and not a silence. A client drawing its own chips was
entitled to its own decision only while it could not read ours.

### 7. `instance` says who answered, once

A block at the top of the envelope beside `generated_at`, carrying the serving
instance's `version` and its `engine` state (`running` / `disabled` / `failed`). These
are the two facts `/health` deliberately withholds from an ungated caller
([ADR-0066](0066-health-answers-liveness-and-says-almost-nothing.md)) and they are fine behind the bearer
token, where the reader has already said who they are. Per envelope, never per node:
one response is one instance's answer.

### 8. What ADR-0008 decided and this record keeps

Restated so the superseded record never has to be read: **content negotiation on the
unversioned resources** — `GET /status` and `GET /status/<node_path>` stay the
canonical URLs and `Accept` chooses the representation; the URL identifies the
resource, not the format. **A top-level object** carrying `schema_version` and
`generated_at`. **`snake_case` properties**, **`UPPER_SNAKE_CASE` code enums**, **RFC
3339 UTC date-times** with `T`/`Z`, converted at serialization while storage stays
naive-local ([ADR-0006](0006-config-file-and-timezones.md)). **Problem JSON** for
errors (RFC 9457) with no stack traces, `401` / `404` / `406`. **A bearer token per
client**, provisioned in `.env` ([ADR-0003](0003-config-and-secrets-via-env-file.md))
and compared with a constant-time equality. **One self-contained OpenAPI 3.1 document**
with the required meta, and it is normative. **Read-only**: no write actions and no
per-token scopes in this slice. **Children in `(rank, name)` order** — declared rank
first, then natural case-insensitive name ([ADR-0055](0055-sibling-order.md)). **One
response, no pagination**, and an inbound `X-Flow-Id` echoed but never required.

### 9. No versioned media type, and no compatibility window

ADR-0008 decision 6 said a breaking change would be offered through a custom
`application/…+json` type negotiated by `Accept`. This is the first breaking change and
it does **not** do that, deliberately. A versioned media type buys one thing — two
shapes served at once while consumers migrate — and there is no consumer to migrate:
the client and the packages are ours and are released with the server. Two shapes would
mean two serializers, two sets of fixtures and two truths about what a node is, which
is the condition this record exists to end. `schema_version` remains the lever, and a
client that meets a version it does not know says so and stops, which the macOS client
already does. Should there ever be a consumer we cannot release with, the media type is
still available and adding it breaks nothing.

## Consequences

- **The macOS client breaks and is updated in the same round.** It decodes
  `reasons: [String]`, `timestamp`, `frequency_seconds` and the `maintenance` bool, all
  of which go, and it refuses any `schema_version` but the one it knows — which is the
  behavior a coordinated release wants. The two ship as one round: a library version
  and a client version that name each other in their notes.
- **Nothing else consumes the envelope.** The four packages extend the *check* surface,
  not this one; the deployments render HTML. So the blast radius of a breaking change
  here is exactly one repository, which will not be true forever and is the reason to
  spend it now.
- **The web templates do not change.** They read the snapshot, and the snapshot is
  unchanged: this record moves nothing into the tree and nothing out of it.
- **A federating parent gets a better graft than it had** — `reported`, `own` and
  `contribution` let it distinguish what a remote check said from what the remote
  instance's own rules made of it, which one code could not express. Federation itself
  stays unbuilt.
- **The debt sentences retire.** Six records end with a clause about a field that
  rides this round; each now carries an update saying where it went. A reader who
  arrives at one of them from a code comment is not sent to a promise with no date.
- **`docs/api/README.md` and the client's byte-identical copy of the spec move with
  it**, the one-way sync ADR-0008 established.

## Alternatives considered

- **A minimal v2** — `entries` for `reasons` and the maintenance object, the rest
  later. Cheaper this week and dearer twice: `report`, `order`, `show_when_quiet`, the
  run facts and `reported` are each already written and waiting, and each deferred
  field is a second coordinated release, because the client has to be rebuilt to use
  it whether it arrives now or in November.
- **Additive under `schema_version` 1** — the shape argued for while a compatibility
  window still seemed necessary. Withdrawn once the client and the packages were
  established as internal: it would carry two spellings of the reason list for as long
  as either client lived, and it cannot express *absent* at all, since adding a field
  can only ever add null.
- **Keep the `maintenance` bool beside the object** for the clients that read it.
  Rejected: the bool is `maintenance !== null` with a second chance to disagree, and
  two fields that must agree eventually will not.
- **Publish `subject`, `observed_at` and `data` on the entry now**, so the client is
  written once. Rejected by decision 1's second edge — they are not in the snapshot
  yet, so the schema would promise what no code can emit and no test can check. They
  arrive additively in the change that adds them, and the client tolerates unknown
  fields until it wants them.
- **A `contribution` object on every node**, uniform rather than null in the ordinary
  case. Rejected for size: it would appear on every node of every response to say
  *nothing happened*, and the interesting case is exactly the one that is easier to
  find when it is the only one present.
