# Little Sister — Status API

A small, **read-only JSON** view of the aggregated status tree, and of what the
instance keeps of its subjects over time. The same routes serve the HTML dashboard;
the representation is chosen by the `Accept` header. This page is the practical guide;
the normative reference is the [`openapi.yaml`](openapi.yaml) beside it (design
rationale lives in little-sister's ADR-0080, and for the series read in ADR-0106 and
ADR-0122 — every record this page and the spec name is little-sister's, also in the
copy a client keeps).

## At a glance

- **Base URL** — per deployment (the spec's sample server is `http://localhost:8888`).
- **Auth** — a bearer token (below). Required for JSON; the browser/session path is
  separate and not part of this contract.
- **Format** — request `Accept: application/json`. Responses are a versioned envelope
  (`schema_version`, `generated_at`, `instance`, `status`); the series read's carries
  `path`, `window` and `series` where the status read's carries `status`.
- **Endpoints**
  - `GET /status` — the whole tree.
  - `GET /status/{node_path}` — the subtree at an absolute, slash-separated path, e.g.
    `system/db` (the leading `/` is implied by the route; a segment may be an FQDN).
  - `GET /series` — every series the instance keeps.
  - `GET /series/{node_path}` — the series that stand at or beneath a node;
    `?from=…&to=…` names the window on both.
- **No pagination** — a request returns the whole (sub)tree, or every series asked
  for, in one response.

## Authentication

Send your token as a bearer header:

```
Authorization: Bearer <token>
```

Tokens are issued by the application's **operator/admin** — request one from them
(provisioning is an operator concern, out of scope here; operators: see the project's
top-level `README`). There is no self-service flow today. A missing or invalid token
yields `401` (see Errors).

## Examples

```bash
TOKEN=s3cr3t
BASE=http://localhost:8888

# the whole tree
curl -s -H "Accept: application/json" -H "Authorization: Bearer $TOKEN" \
  "$BASE/status"

# a subtree
curl -s -H "Accept: application/json" -H "Authorization: Bearer $TOKEN" \
  "$BASE/status/system/db"

# pass a correlation id; it is echoed in the response X-Flow-Id header
curl -si -H "Accept: application/json" -H "Authorization: Bearer $TOKEN" \
  -H "X-Flow-Id: abc-123" "$BASE/status" | grep -i '^x-flow-id'
```

**What a node carries is what the dashboard shows.** Three statuses — `reported` (what
the check said), `own` (what the node shows once its own pins apply) and `code` (rolled
up, degraded when stale) — plus `contribution`, which is non-null only when something
kept this node out of its parent's count and names the rule that did. `changes` is how
many times this node's own status changed in the last hour, counting only moves between
`OK`, `WARN` and `ERROR` — the one number that says *this thing is flapping*, since a
subject that recovers between failures never trips the escalation counter.
`contribution` names the rule and carries what was counted: null for a rule that
withholds the node, a real code for one that transforms what it publishes — `damping`,
where a node has read a worse code but not yet often enough in a row for this deployment
to believe it. `entries` holds the node's reasons: `addressable` says whether they are
members with stable slugs that can be pinned one by one, and each item carries its
`text`, its own `code` where the check declared one, what handles it, `handled`, the
`subject` it is about and the `data` the check read — free-form JSON in the check's own
vocabulary, of which only `at`, `started` and `ended` are typed, as RFC 3339 UTC
date-times at any depth — and the `form` its text was written from, where the check's
grading named one: the key a deployment re-words that line under, to show beside it and
never to parse. `run` holds the timing — `observed_at`, `wall_seconds`, `next_at`,
`frequency_seconds` where a check reads this node's subject on an interval, and
`stale_after_seconds`, the tolerance the server measured freshness by, wherever it
applied one — and is **absent entirely** where nothing answers for the node, which is
not the same as present with a null `observed_at`. The last two come apart: a node the
server re-asserts on its own tick names a tolerance and no interval, and so will a paced
unit. `handled` lists what handles a node now — a pin a person set, while it stands,
and a rule the deployment configured, while it changes what counts — each with its
`id`, its `kind`, its `source` and its `note`; an entry carries its own. The Markdown
metadata is `about`, `title`, `description`, `config` (what the check ran with) and
`report` (what its last run found) — **raw Markdown**, render it client-side, as an
entry's `text`, the `note` of what handles a part and a reading's `texts` are. Every
one is CommonMark with GitHub's tables and strikethrough, the dialect the dashboard
renders, and in every one a status written in braces — `{ok}`, `{warn}`, `{error}`,
`{maintenance}` or `{undefined}`, in either case — names that status, as `code` spells
it: the dashboard draws the status's sign there, its cue and its word on its tint, so
`{error}: restart it` reads as an instruction for the failing case. Render it as the
client shows that status; one in code — a code span or a code block — or escaped
(`\{error}`) is text. And in every one a link written `handbook` leads to the handbook
of the node the text belongs to and `handbook#<section>` to a section of it, a heading
anchored as GitHub anchors one, `## Sign in` at `#sign-in`: a node that has a handbook
says where it is, `handbook`, the absolute address of its Handbook view as your request
reached the server, which a link it writes so leads to with the section after it. The
handbook's text rides in no envelope; open the address in a browser. A node's
`description` says what its check reads, and its `about` where the thing stands, how to
reach it and what to do. A node's `details` are named values whose keys its team chose —
whom to ask, where tickets go, a place, how to log in, the name of the object it stands
for — each `{"key", "text", "by"}`, its text one line of Markdown, and absent where it
has none. The envelope carries a node's **own**, as given: its check type's first
(`by: type`), the details of its object, which are the node's alone; then its
deployment's (`by: deployment`), which **hold for every node beneath**, key by key, the
nearest winning — a key both name stands once for each. The dashboard shows a node its
own `type` details first, then the `deployment` ones of the nodes above it, the
outermost first, then its own `deployment` ones; a key stands once, where it is named
first, with its nearest value — its own `deployment` one over its own `type` one, either
over one from above — and a nearest value that is empty stands nowhere, which is how a
deployment takes a key back for a subtree. A link a detail writes in the short form
leads into the handbook of the node it is given on. A node's `tags` are every tag it
carries, the words its deployment writes for it and for every node above it, added up —
`production`, `rack-4` — in the order the dashboard lists them: its whole set, unlike
its details, so that a subtree fetched by its path says them of its root too, and
absent where it carries none. `order` is the declared rank,
`show_when_quiet` a tri-state, and `children` are in rank-then-name order. Full field
docs are in [`openapi.yaml`](openapi.yaml).

## Reading a series

A check may keep what it read of a subject over time — its **series** — and a node's
Series view draws them. The same URL, asked for JSON, answers them as data: what an
instance keeps, as it keeps it, for a script or a session that reads a running
instance.

```bash
# every series at or beneath a node, over the last six hours
curl -s -H "Accept: application/json" -H "Authorization: Bearer $TOKEN" \
  "$BASE/series/hosts/alpha?from=now-6h"

# everything the instance keeps, over one stretch
curl -s -H "Accept: application/json" -H "Authorization: Bearer $TOKEN" \
  "$BASE/series?from=2026-09-26T15:00:00Z&to=2026-09-26T16:00:00Z"
```

**The window is `from` and `to`**, read as the Series view's own URL reads them:
`now`; `now-` and a duration in seconds, minutes, hours, days or weeks (`now-90s`,
`now-15m`, `now-6h`, `now-1d`, `now-1w`); or an ISO 8601 instant — sent with a `Z` or
an offset, because one without is read in the server's configured timezone. `to` is
`now` where it is left out, and a request without `from` reaches back to the oldest
reading kept, so one that names neither answers **everything kept**, which for a whole
instance can be megabytes. The answer's `window` says the two instants the server read
them as, each null where the request left it open, and `generated_at` is the `now` it
measured from.

**Which series come back.** Every one that stands at or beneath the node asked, and
`path` says which node that was. A series stands on the node that stands for its
subject — a job name, a function, a workflow with a node of its own — and on its
check's own node where none does; `node` is that node's path. One thing reaches down
from above: a series shown *above* the node asked comes back where one of its measures
names a node at or beneath it, so a host's series answers at the host's `memory` node,
with the one measure that stands there. **A node that exists always answers `200`** —
with an empty `series` where none stands at or beneath it, which is also what an
instance that runs no engine answers everywhere, and its `instance.engine` says so.
A series with no reading inside the window keeps its place, with no readings. The
order is the tree's: a node above the one asked first, then the node and what is
beneath it — a node before its children, siblings by rank and then by name — and by
type, mount and subject where several stand on one node.

**A series has a key and a node, and they are different things.** `key` is what its
readings are kept under: the `type` and the `mount` of the check that took them, and
the `subject` they are of. `node` is where the tree shows it. A rename at the source
moves the node and leaves the key, so follow a subject by its key.

**A reading** carries two clocks: `at`, the time on the series' own clock — the
record's own top-level `at` where it has one, so a run sits where it finished, and
otherwise when the reading was first observed — and `observed_at`, when the server
last took it. A window is asked of `at`, both ends included, and readings come oldest
first. `code` and `texts` are how the reading stood where it landed — its line's, or
its node's — and `code` is **null** where no line carried it: a null is never an `OK`.
`identity` names the event a reading is of, where the source keeps a history of such
events, and `state` the state a subject stood in, where a reading is one spell of it —
the same event or an unchanged state read again stays one reading; both are empty
for a reading that is always a new one. `record` is what was read, whole and in the
check's own keys, with the same typed `at`, `started` and `ended` as everywhere else,
and an `error` that is not null where the reading failed.

**A measure** is a field of the record that is drawn as a curve: its `field`, its
`unit`, its `label`, the `node` its curve stands on and `axis_to`, where its value
axis reaches, or null. Only the measures that stand at or beneath the node asked are
listed. A deployment may declare one measure for every thing a record counts — every
volume, every process — and those arrive already told apart: one for each such thing
the kept readings hold, whatever the window. **Read a field in one way**: flatten the
record, joining the keys from the top down to each value with `.`, and look `field`
up. Never split `field` at its dots — a key may hold one:

```python
def flatten(record, above=""):
    found = {}
    for key, value in record.items():
        name = f"{above}.{key}" if above else str(key)
        if isinstance(value, dict):
            found.update(flatten(value, name))
        else:
            found[name] = value
    return found

value = flatten(reading["record"]).get(measure["field"])
```

## Errors

Failures are **Problem JSON** (RFC 9457), media type `application/problem+json`:

```json
{ "type": "about:blank", "title": "Unauthorized", "status": 401 }
```

- `400` — a window the server cannot read, or whose `from` does not come before its
  `to`; `detail` names the parameter and what it takes. The series read only.
- `401` — missing or invalid bearer token.
- `404` — no node at the given path. A node without series is not one: the series read
  answers it an empty list.

## Versioning

A field added to the served snapshot is added to this contract in the same change,
and such an addition is **compatible**: `schema_version` stays and the spec's minor
`info.version` moves. `schema_version` and the major move only when a field changes
meaning or goes. There is no versioned media type and no compatibility window — the
clients of this API are released with the server, and a client that meets a
`schema_version` it does not know should say so and stop rather than guess.

**2.0.0 is the first version in which the envelope is the snapshot** rather than an
older projection of it, so nothing in it is compatible with 1.3.0: `own_code` became
`own` and `reported` joined it, `contribution` is new, the string array `reasons`
became `entries`, the `maintenance` bool and `maintenance_details` became one nullable
object, the nullable `timestamp` and `frequency_seconds` became `run` — absent where
nothing answers for a node — and `report`, `order`, `show_when_quiet` and the
envelope's `instance` are new.

**2.1.0 adds `subject` and `data` to an entry** — what a line is about, and the record
the check read about it. Both are additive: a client that reads neither is unaffected.

**2.2.0 is the first version in which `contribution.code` can be a real code** rather
than only null. No field moves: a rule that withholds a node still reports null, and the
new `damping` rule reports what the parent counted. A client that showed
`contribution` only as *withheld* should read the code.

**2.3.0 adds `changes` to a node** — its status changes in the last hour. Additive.

**2.4.0 adds `shielded_by` to a node** — the failing dependency it is reached
through, or null. Additive, and worth reading: while it is set, the node's `code`
is still its own but nothing of it reaches its parent, so a client that sums
children itself will otherwise disagree with the server about the tree. Its
`contribution` says the same — `by: dependency`, `code: null` — unless the node is
pinned or has never reported, which are named first.

**2.5.0 adds `subject` and `record` to a node** — the object its check measured and
what that run read about it. Additive. This is where a measurement now lives: a check
that reads one object records it on the node that stands for it, and only an object with
no node of its own carries its record on a line instead.

**2.6.0 adds `refused` to an entry** — why the server refused that line's record, where
it did, in the sentence the server's own page shows, with `data` null beside it; null on
every other line. Additive. The line stands as its check graded it, so its text and code
mean what they always did: only the record is missing, and `refused` is what says so
rather than leaving a client to believe the check carried none.

**2.7.0 adds the series read** — `GET /series` and `GET /series/{node_path}`, their
schemas, and the first `400` this API answers. Additive: nothing of the status read
moves, and a client that reads no series is unaffected.

**2.8.0 adds `form` and `grading` to an entry** — the form its line was written from,
where its check's grading named one (little-sister ADR-0126), and the grading that
decided its code, where one did (little-sister ADR-0131); each null on every other line.
Additive: `text` is still the line, rendered on the server, and `code` still its code,
so a client that reads neither is unaffected; one that shows them beside the line tells
a reader what a deployment writes to make that line say more, and to grade it
differently.

**2.9.0 adds a node's two periods, each beside the code it is of** (little-sister
ADR-0132): `own_period` beside `own`, when the node's own status began, and `period`
beside `code`, since when the node has shown that code, how that began — `was`, `cause`
— and `by`, the node whose change began it, which need not stand beneath it. Each says
`since`, with `before` where that is a bound. Additive, and absent where there is none:
`own_period` on a node that declares nothing, `period` on a leaf, whose one period is
`own_period`, and `period` also wherever it is not of the `code` beside it — after a
restart until the units beneath the node have run, and for the moment a reading has gone
stale before the server dates it — so a client shows what it reads and compares nothing.

**2.10.0 says how every Markdown text is written and what two things mean in it**
(little-sister ADR-0018 and ADR-0133): CommonMark with GitHub's tables and
strikethrough, the dialect the dashboard renders; `{error}` and the other four, in
either case, naming that status, which the dashboard draws as its sign; and a link
written `handbook` or `handbook#<section>`, which leads into the handbook of the node
the text belongs to. A node that has a handbook gains `handbook`, the absolute address
of its Handbook view, absent on one that has none. A node that has details gains
`details`, its own, each saying who gave it — its check type, whose are the node's
alone, or its deployment, whose hold for every node beneath it, key by key, the nearest
winning — so a client resolves what the dashboard shows from the nodes above, as above.
The descriptions of a node's `about` and `description` say what each is for as the
dashboard divides them — `description` what the node's check reads, `about` where the
thing stands, how to reach it and what to do. No field moves, and the text stays raw: a
client that renders none shows the braces, a table's pipes and a link's `handbook#…`,
which still read; one that does renders each status as it shows the status of that name,
a table as a table, and the short form as a link to the node's `handbook` with the
section after it.

**2.11.0 adds a deployment's configured rules** (little-sister ADR-0137): a node's
`contribution.by` may say `aggregation`, a rule in the deployment's configuration
changing what its parent counts of it — a cap, healing, a floor, the node left out —
with the code counted, or null where it counts nothing; and every entry gains
`contribution`, the same object, saying what its node counted of it: `maintenance`
with a null code where the entry is pinned, `aggregation` where a configured rule on
the node's lines changes how it counts, and null on most entries, which count as they
read. Additive: a node's and an entry's own `code` stay what they read, so a client
that reads neither field is unaffected; one that does can say why a red line leaves
its node green, as it says why a red node leaves its parent amber. A branch's `period`
may say `rule` as its `cause` — a configured rule beginning to count beneath it, at the
start that brought it — and name the rule in `rule`, beside the `by` of the node whose
count it changed: a word a client that does not know it shows as it reads.

**2.12.0 adds a node's tags** (little-sister ADR-0139): `tags`, every tag the node
carries — the words its deployment writes for it and for every node above it, added up,
each a fact about what the node is, such as `production` or `rack-4` — in the order the
dashboard lists them, absent where it carries none. Unlike `details` it is the node's
whole set rather than its own, so that whether a node carries a tag is answered by the
node in hand, the root of a subtree fetched by its path among them. Additive: nothing
else moves.

**3.0.0 says every rule on a part in one list** (little-sister ADR-0141), and
`schema_version` is 3. A node and an entry carry `handled`, what handles them now: a
pin a person set, while it stands, and a rule the deployment configured, while it
changes what counts — what a node passes up, how its parent counts it among its
children, how its children or its entries count in it. Each has its `id`, its `kind`
(`maintenance`, `seen`, `aggregation`), its `source` (`person`, `configuration`), its
`note` and `counts_as`, in the notation a configured rule is written in: `nothing`, or
each status it names with what that counts as. A pin adds who set it and when, who
first did and when it ends; a configured rule its `file`, the day it stands `since`,
its `level`, and what it names and counts where it does. `maintenance`, the one object
a pin had, goes: a client that read it reads the `maintenance` item of `handled`. A
`contribution` names the rule that decided, `rule` — the `id` its part's `handled`
lists it under — and null for `damping`, `dependency` and `undefined`, and for a node
that is `maintenance` because every one of its entries is pinned or its check said
so. A failure a person accepted as it stands is a pin of the kind `seen`
(little-sister ADR-0142): its part keeps its `code` and is counted `OK` above it —
`contribution.by` says `seen`, on a node and on an entry — and its item adds the
`status` the part read when it was marked, which a worse one ends, and the
`occurrence` it is bound to, which another one ends: its line's, null where it is the
failing stretch it was set in. Its `expires_at` is null where it was given no end. A
kind or a source a client does not know is shown as it reads: further kinds come
without another major.

Decode defensively all the same: tolerate unknown fields and any child order, and
treat an absent `run` as *nothing answers for this node* rather than as an error.

## The golden envelope

[`openapi.yaml`](openapi.yaml) says what the envelope *may* contain; `envelope-3.json`
beside it is one envelope that contains all of it — a node with a `run` and one without,
a run that has never written (present, with a null `observed_at`), a run on a schedule
carrying `frequency_seconds` and `stale_after_seconds`, the `wall_seconds` it took and
the `next_at` it is due, and one carrying none of them, entries addressable and prose,
an entry carrying `subject` and `data`, one carrying neither and one whose record was
`refused`, an entry written from a `form` beside entries that carry none, an entry whose
work is `running` and one a pin of its own handles, a `period` that is a
bound and one a change began, naming `by`, an `own_period` of each kind, a leaf without
`period` and a container without `own_period`, a node with a `handbook` and one without,
`details` its check type gave and its deployment gave, a key both name and one given
empty, `tags` a node carries from above and of its own beside nodes that carry none, a
record carrying the typed `at` / `started` / `ended` keys at two depths, what handles a
node — a person's pin, a configured rule on what a node passes up and one on its
lines, a failure a person marked seen, a node's own with no end and a line's bound to
its occurrence until a day — and nothing, `show_when_quiet` in all three of its states,
and the `instance` block. It carries **both** shapes of `contribution`: the withheld
one, which reports `code: null` and names its rule (a pin's `maintenance`, a shielded
node's `dependency`, and `undefined` for a node that has never reported), and a damped
node's, which *transforms* one — the node reads ERROR, the parent counted OK, and
`contribution.code` is that OK — beside a node a configured rule heals, which transforms
one too and names `aggregation`, and one a person marked seen, which names `seen`. Those
two shapes are deliberately both here: before damping every rule withheld, so a fixture
with only the null would quietly teach a client that `contribution` means *not counted*.
An entry carries `contribution` in each of its shapes as well: a pinned line's
`maintenance`, a line a rule heals, `aggregation` with the OK its node counted, a line
marked seen, `seen` with the same OK, and the null on every other — each naming its
`rule`, which the part's own `handled` lists. It is **generated from the server's own
API** and a test holds the server to it, so it cannot quietly stop being true.

Which means it has an obligation attached. A field added to the served snapshot is added
to this contract in the same change — and it makes this artifact stale in that same
change, so **regenerating it belongs to the change that adds the field**, not to a
follow-up. `python tests/test_contract_fixture.py` rewrites it; the diff is the review.

It exists so that the server and its clients test **one** artifact instead of each
keeping hand-written JSON that drifts apart. It ships inside the Python wheel, where a
plugin reads it without a copy:

```python
from little_sister import contract

envelope = contract.golden_envelope()          # as GET /status answers it
artifact = contract.golden_artifact()          # plus schema_version and volatile
```

A client that cannot import the wheel carries the identical bytes as a shared file of
the family.

**The series read has a golden answer of its own**, `series-3.json`, beside the
envelope in that package: one request and what it is answered — a series on its
check's node and one on its subject's, a measure told apart by key and one with no
`axis_to`, a series without measures, a reading that failed, a run with its own time,
a run without a verdict, a state, and a series with no reading in the window. It is
generated and held to the server the same way, from a scene whose every instant is
fixed, so every time a reading carries is a real value to decode and only
`generated_at` and the instance's `version` are volatile:

```python
answer = contract.golden_series()              # as GET /series answers the request
artifact = contract.golden_series_artifact()   # plus request, schema_version, volatile
```

It ships in the wheel alone: no client of ours that cannot import it reads a series.

Some field **names** are volatile — they differ between two correct runs — and the
artifact names them itself under `volatile`, so a consumer keeps no list of its own:
`generated_at`, `observed_at` and `next_at`, the instance's `version`, and a pin's
`set_at` and `created_at`. Wherever they occur the artifact holds `"<volatile>"`;
normalize both sides before comparing, and what is left is the shape and every stable
value. A pin's `expires_at` is deliberately **not** volatile — the scene fixes it, so a
client's date decoding is tested against a real one.

## Rendering the spec

[`openapi.yaml`](openapi.yaml) is OpenAPI 3.1. Browse it with any viewer, e.g.
[Redoc](https://github.com/Redocly/redoc) or
[Swagger UI](https://github.com/swagger-api/swagger-ui), or generate a client with
[openapi-generator](https://openapi-generator.tech/).
