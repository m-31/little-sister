# ADR-0080 — The envelope is the snapshot, published: `schema_version` 3

- **Status:** Accepted
- **Date:** 2026-10-25 (accepted 2026-09-06; decision 8 and the minor-version rule of
  decision 1 accepted 2026-06-27, rewritten 2026-08-23)
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
  [ADR-0083](0083-a-node-may-wait-before-it-escalates.md) and
  [ADR-0084](0084-a-check-may-be-reached-through-another.md) (damping and the shield,
  two of the rules a `contribution` names),
  [ADR-0047](0047-node-notes-and-their-retention.md) (a pin's text, `note` in the model
  as in the envelope), [ADR-0003](0003-config-and-secrets-via-env-file.md) (the token),
  [ADR-0120](0120-every-stored-time-is-an-instant.md) (the instants the date-times are
  spelled from), [ADR-0130](0130-a-unit-has-a-period-of-its-own.md) (a unit's own
  node and period, which `run` says without a key of its own),
  [ADR-0132](0132-a-branch-keeps-the-period-of-what-it-shows-beside-the-log.md) (a
  node's periods, `own_period` and `period` — 2.9.0),
  [ADR-0133](0133-a-node-says-what-it-is-in-a-card-and-at-length-in-a-handbook.md) (a
  node's `handbook` and `details`, and what a text's links and statuses mean — 2.10.0),
  [ADR-0137](0137-a-deployment-says-in-a-table-how-a-part-counts-above-it.md)
  (`aggregation`, and an entry's `contribution` — 2.11.0),
  [ADR-0139](0139-a-node-carries-every-tag-written-for-it-or-above-it.md) (a node's
  `tags` — 2.12.0),
  [ADR-0141](0141-every-pin-is-one-thing-with-a-kind-and-the-envelope-lists-what-handles-a-part.md)
  (`handled`, `contribution.rule` and `maintenance` gone — `schema_version` 3),
  [ADR-0142](0142-a-failure-marked-seen-counts-as-ok-above-until-it-changes.md) (`seen`,
  a second kind of pin in `handled`)
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
in the same change.** Such an addition is compatible — `schema_version` stays and the
spec's `info.version` moves a minor, the rule of 2026-06-27 kept — so the cost is a
line of serialization and a line of schema, paid by whoever adds the field rather than
by whoever notices the gap two releases later. It is also what keeps a major version
rare: one is only for a field that **changes meaning** or goes, as `maintenance` went
when every rule on a part became one list, `handled` — `schema_version` 3, the spec
3.0.0 (decision 4).

The rule cuts both ways, and the second edge is the one that needs saying: **the
envelope does not publish what the snapshot cannot produce.** A field declared in the
schema and never emitted is a promise no test can check and no reader can trust. So the
entry keeps `slug`, `text`, `code`, `running` and `handled` here, and `subject`,
`observed_at` and `data` join it in the change that adds them to the snapshot — a minor
under this rule, invisible to a client that does not want them. Tags are the same case:
nothing is reserved for them here.

`subject` and `data` took exactly that route: they joined the entry with the change
that put them in the snapshot, `schema_version` stayed 2 and the spec moved to 2.1.0
([ADR-0082](0082-a-line-carries-what-it-is-about-and-what-it-read.md)). So did a node's
periods (2.9.0) and every entry's `contribution` (2.11.0), which decision 2 says, and a
node's `handbook` and `details` (2.10.0) and its `tags` (2.12.0), which decision 10
says. `observed_at` is still unpublished, for the reason above — nothing can emit it
yet.

**The rule has a second half, and it is an obligation rather than a rule.** One
envelope is written down — `src/little_sister/contract/envelope-3.json`, generated from
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

Two of them say since when: `own_period` beside `own`, when the node's own status
began, and `period` beside `code`, since when the node has shown it
([ADR-0132](0132-a-branch-keeps-the-period-of-what-it-shows-beside-the-log.md)). Each
carries `since`, `before` where the beginning is a bound, `was` and `cause`, and
`period` also `by`, the node whose change began it. Each is absent where the node has
no such period, as `run` is (decision 5), and `period` also where it is not of the
`code` beside it.

`contribution` is the fourth value that record defines and no surface has ever
published: what this node's **parent accumulated**, and the rule that made it so.

- It is **null** when the parent counted the node's `code` — which is the ordinary
  case, so the field costs nothing on a healthy tree.
- Otherwise it is `{"code": …, "by": …, "rule": …}`. `code` is what the parent counted,
  and **null means the node was not counted at all** — which is what *contributes
  nothing* has always meant for `MAINTENANCE` and `UNDEFINED` (ADR-0039 rules 2 and 3,
  restated from the node's side by ADR-0032 decision 2). `by` names the rule —
  `maintenance`, `undefined`, `dependency` for a shield
  ([ADR-0084](0084-a-check-may-be-reached-through-another.md)), `damping`
  ([ADR-0083](0083-a-node-may-wait-before-it-escalates.md)), `seen` for a failure a
  person accepted as it stands, which the parent counts as OK
  ([ADR-0142](0142-a-failure-marked-seen-counts-as-ok-above-until-it-changes.md)
  decision 8), and `aggregation` for a rule the deployment configured, its code what
  the parent counts or null where it counts nothing
  ([ADR-0137](0137-a-deployment-says-in-a-table-how-a-part-counts-above-it.md)
  decision 12) — and a further rule is a further name, an added enum value and
  therefore a compatible change. `rule` is the `id` of the item of `handled` that
  decided (decision 4), and null for a mechanism — damping, a shield, a node not yet
  reported — and for a node that is maintenance because every one of its entries is
  pinned or its check said so.

Every entry carries `contribution` too, the same object, saying what its node counted
of it — `maintenance` with a null code where the entry is pinned, `seen` where a person
accepted its failure, `aggregation` where a configured rule on the node's lines changes
how it counts, and null on the rest — so that the virtual children read as the real
ones do. A node's and an entry's own `code` stay what they read.

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
             "code": "WARN", "running": false, "handled": []}]
}
```

`addressable` is the snapshot's `members`: whether these items may be pinned one by
one. Each item is the `ReasonLine` the snapshot already holds — `slug` the key
([ADR-0036](0036-addressable-reasons.md)), `text` raw Markdown as before, `code` the
entry's own where the check declared one and **null** where it carries the node's
([ADR-0042](0042-entries-carry-their-own-code.md)), `running` display-only work in
flight, `handled` what handles this entry (decision 4). Order is the check's order and
is never sorted. The bare string array goes; a client that wants the old shape reads
`items[].text`.

### 4. What handles a part is one list, `handled`

The bool and `maintenance_details` were one fact in two fields, and the bool is the
half that cannot say anything. One list takes both slots — the node's and the entry's —
`handled`, what handles the part now
([ADR-0141](0141-every-pin-is-one-thing-with-a-kind-and-the-envelope-lists-what-handles-a-part.md)
decision 3): a person's pin while it stands, and a configured rule while it changes
what counts. Each item carries its `id`, its `kind` — the word `contribution.by` says
it in — its `source`, `person` or `configuration`, its `note` and `counts_as`. A pin
adds who set it and when, who first did and when, and when it ends; a configured rule
its file, its date, its level and the lines or children it names. A pin's two dates
always ship, because both are always kept: a pin whose creation was never recorded
reads its set, so there is no absent case to describe
([ADR-0014](0014-maintenance-persistence.md)). *Pinned* is a `maintenance` item in
`handled`.

A pin of the kind `seen` is a failure a person accepted as it stands
([ADR-0142](0142-a-failure-marked-seen-counts-as-ok-above-until-it-changes.md)
decision 8): its part keeps its `code`, its item says the `status` it was set at and
the `occurrence` it is bound to, and its `expires_at` is null where it was given no
end.

**The text is `note`**, in the envelope as in the model
([ADR-0047](0047-node-notes-and-their-retention.md) decision 1). The envelope took the
name before the model did, because a rename is a *breaking* change to this contract:
publishing `reason` would have bought a second major version for one word. The value
is what it always was.

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
therefore never be stale by its own stamp. No key names the unit: a unit's `run`
stands on the node it answers for, and `frequency_seconds` and `stale_after_seconds`
are per node already, so the envelope needs no field of its own for it
([ADR-0130](0130-a-unit-has-a-period-of-its-own.md) decision 5). What
[ADR-0078](0078-the-unit-is-what-the-engine-releases.md) decision 5 owed *this* round
is not a key but the **rule** — that `run` may appear below the node a check is mounted
at — and the rule is in the sentence above and in the schema, where a client reads it.

**Absent, not null, is the point**, and it buys a distinction the old shape could not
draw. The block is **absent** where nothing answers for the node; it is **present with
a null `observed_at`** where something answers and has never written — a check pinned
by an unresolvable secret, which never runs and still has an armed slot
([ADR-0023](0023-secret-references.md)), or one that has simply not run yet. Those
were one null before this version, which is the contract's own versioning rule broken
under pressure ([ADR-0027](0027-observation-timestamp-semantics.md) said so when it
made the change),
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

### 8. How the API is reached and spelled — decided 2026-06-27

**Content negotiation on the unversioned resources** — `GET /status` and
`GET /status/<node_path>` stay the canonical URLs and `Accept` chooses the
representation; the URL identifies the resource, not the format. **A top-level object**
carrying `schema_version` and
`generated_at`. **`snake_case` properties**, **`UPPER_SNAKE_CASE` code enums**, **RFC
3339 UTC date-times** with `T`/`Z`, spelled at serialization from what the tree stores:
instants, and not the machine's clock without a zone
([ADR-0120](0120-every-stored-time-is-an-instant.md)). **Problem JSON** for
errors (RFC 9457) with no stack traces, `401` / `404` / `406`. **A bearer token per
client**, provisioned in `.env` ([ADR-0003](0003-config-and-secrets-via-env-file.md))
and compared with a constant-time equality. **One self-contained OpenAPI 3.1 document**
with the required meta, and it is normative. **Read-only**: no write actions and no
per-token scopes in this slice. **Children in `(rank, name)` order** — declared rank
first, then natural case-insensitive name ([ADR-0055](0055-sibling-order.md)). **One
response, no pagination**, and an inbound `X-Flow-Id` echoed but never required.

**Why.** The API follows the Zalando RESTful API Guidelines and says where it departs
from them. The URL names the resource and never a version (Zalando #115), so one
canonical address serves both representations. A code is a string (#240), never the
number the model counts with, which is brittle and is not the severity order. An error
is Problem JSON (#176), never an ad-hoc `{"error": …}` body. A machine client sends a
bearer token and never the session cookie, which would tie a browser's concern to a
reader that is no browser. The token is static and one per client, where the guidelines
assume an OAuth2 provider: the doors that sign a person in
([ADR-0069](0069-identity-comes-from-outside-and-one-account-does-not.md)) leave the
API's tokens alone, and its reader is a machine none of them serves, so a token
provisioned per client beside the instance is still the proportionate answer — in the
`Authorization: Bearer` shape, so that a move to OAuth2 later breaks nothing.
`X-Flow-Id` (#233) correlates the requests of a distributed system, and this is one
process, so it is echoed and never demanded or made.

### 9. No versioned media type, and no compatibility window

The rule of 2026-06-27 offered a breaking change through a custom
`application/…+json` type negotiated by `Accept`. This is the first breaking change and
it does **not** do that, deliberately, nor does `schema_version` 3 after it. A
versioned media type buys one thing — two shapes served at once while consumers
migrate — and there is no consumer to migrate: the client and the packages are ours and
are released with the server. Two shapes would mean two serializers, two sets of
fixtures and two truths about what a node is, which is the condition this record exists
to end. `schema_version` remains the lever, and a client that meets a version it does
not know says so and stops, which the macOS client already does. Should there ever be a
consumer we cannot release with, the media type is still available and adding it breaks
nothing.

### 10. What a node says of itself rides with it: `handbook`, `details` and `tags`

A node carries `handbook`, the absolute address of its handbook where it has one, as
the request reached the server, and `details`, its own as the snapshot holds them, each
key with its Markdown and who gave it, `type` or `deployment`, in their order — the
type's first, each as given
([ADR-0133](0133-a-node-says-what-it-is-in-a-card-and-at-length-in-a-handbook.md)). A
handbook's text is no field of the node, and the envelope, which carries what the
snapshot holds (decision 1), carries none, nor a card's resolved rows. A text keeps its
Markdown raw, a link written `handbook#<section>` and a status written `{error}` among
it, and the contract says what they mean — the handbook the node's `handbook` names,
and its section; the status of that name, as `code` spells it — and that what the
deployment gives holds for every node beneath its own, key by key, the nearest winning,
where the type's stand first on their own node, so that a client draws the card as the
dashboard does.

A node's `tags` are every tag it carries — those its deployment writes for it and for
every node above it, added up — as text, in the order its card lists them
([ADR-0139](0139-a-node-carries-every-tag-written-for-it-or-above-it.md) decision 6):
the node's whole set, so that a subtree fetched by its path says them of its root too.
Each of the three is absent where the node has none, as `run` is.

## Consequences

- **The macOS client breaks and is updated in the same round.** It decodes
  `reasons: [String]`, `timestamp`, `frequency_seconds` and the `maintenance` bool, all
  of which go, and it refuses any `schema_version` but the one it knows — which is the
  behavior a coordinated release wants. The two ship as one round: a library version
  and a client version that name each other in their notes. `schema_version` 3 is the
  same: where `maintenance` gives way to `handled`, the client takes 3 in the same
  release.
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
  rides this round; each now says where it went. A reader who
  arrives at one of them from a code comment is not sent to a promise with no date.
- **`docs/api/README.md` and the client's byte-identical copy of the spec move with
  it**, the standing one-way sync.

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
- **Keep the `maintenance` bool beside the pin** for the clients that read it.
  Rejected: the bool says again whether a maintenance pin stands, with a second chance
  to disagree, and two fields that must agree eventually will not.
- **Publish `subject`, `observed_at` and `data` on the entry now**, so the client is
  written once. Rejected by decision 1's second edge — they are not in the snapshot
  yet, so the schema would promise what no code can emit and no test can check. They
  arrive additively in the change that adds them, and the client tolerates unknown
  fields until it wants them.
- **A `contribution` object on every node**, uniform rather than null in the ordinary
  case. Rejected for size: it would appear on every node of every response to say
  *nothing happened*, and the interesting case is exactly the one that is easier to
  find when it is the only one present.
