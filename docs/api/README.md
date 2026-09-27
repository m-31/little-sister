# Little Sister — Status API

A small, **read-only JSON** view of the aggregated status tree. The same routes serve
the HTML dashboard; the representation is chosen by the `Accept` header. This page is
the practical guide; the normative reference is the [`openapi.yaml`](openapi.yaml)
beside it (design rationale lives in little-sister's ADR-0080 — every record this
page and the spec name is little-sister's, also in the copy a client keeps).

## At a glance

- **Base URL** — per deployment (the spec's sample server is `http://localhost:8888`).
- **Auth** — a bearer token (below). Required for JSON; the browser/session path is
  separate and not part of this contract.
- **Format** — request `Accept: application/json`. Responses are a versioned envelope
  (`schema_version`, `generated_at`, `instance`, `status`).
- **Endpoints**
  - `GET /status` — the whole tree.
  - `GET /status/{node_path}` — the subtree at an absolute, slash-separated path, e.g.
    `system/db` (the leading `/` is implied by the route; a segment may be an FQDN).
- **No pagination** — a request returns the whole (sub)tree in one response.

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

**What a node carries is what the dashboard shows.** Three statuses — `reported`
(what the check said), `own` (what the node shows once its own pins apply) and `code`
(rolled up, degraded when stale) — plus `contribution`, which is non-null only when
something kept this node out of its parent's count and names the rule that did.
`changes` is how many times this node's own status changed in the last hour, counting
only moves between `OK`, `WARN` and `ERROR` — the one number that says *this thing is
flapping*, since a subject that recovers between failures never trips the escalation
counter. `contribution` names the rule and carries what was counted: null for a rule that
withholds the node, a real code for one that transforms what it publishes — `damping`,
where a node has read a worse code but not yet often enough in a row for this
deployment to believe it. `entries` holds the node's reasons: `addressable` says whether they are members with
stable slugs that can be pinned one by one, and each item carries its `text`, its own
`code` where the check declared one, its own `maintenance`, the `subject` it is about
and the `data` the check read — free-form JSON in the check's own vocabulary, of which
only `at`, `started` and `ended` are typed, as RFC 3339 UTC date-times at any depth. `run` holds the timing
— `observed_at`, `wall_seconds`, `next_at`, `frequency_seconds` where a check reads
this node's subject on an interval, and `stale_after_seconds`, the tolerance the
server measured freshness by, wherever it applied one — and is **absent entirely**
where nothing answers for the node, which is not the same as present with a null
`observed_at`. The last two come apart: a node the server re-asserts on its own tick
names a tolerance and no interval, and so will a paced unit. `maintenance` is one object or null, and the text on it is `note`. The
Markdown metadata is `about`, `title`, `description`, `config` (what the check ran
with) and `report` (what its last run found) — **raw Markdown**, render it
client-side. `order` is the declared rank, `show_when_quiet` a tri-state, and
`children` are in rank-then-name order. Full field docs are in
[`openapi.yaml`](openapi.yaml).

## Errors

Failures are **Problem JSON** (RFC 9457), media type `application/problem+json`:

```json
{ "type": "about:blank", "title": "Unauthorized", "status": 401 }
```

- `401` — missing or invalid bearer token.
- `404` — no node at the given path.

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
children itself will otherwise disagree with the server about the tree.

**2.5.0 adds `subject` and `record` to a node** — the object its check measured and
what that run read about it. Additive. This is where a measurement now lives: a check
that reads one object records it on the node that stands for it, and only an object with
no node of its own carries its record on a line instead.

**2.6.0 adds `refused` to an entry** — why the server refused that line's record, where
it did, in the sentence the server's own page shows, with `data` null beside it; null on
every other line. Additive. The line stands as its check graded it, so its text and code
mean what they always did: only the record is missing, and `refused` is what says so
rather than leaving a client to believe the check carried none.

Decode defensively all the same: tolerate unknown fields and any child order, and
treat an absent `run` as *nothing answers for this node* rather than as an error.

## The golden envelope

[`openapi.yaml`](openapi.yaml) says what the envelope *may* contain; `envelope-2.json`
beside it is one envelope that contains all of it — a node with a `run` and one without,
a run on a schedule carrying `frequency_seconds` and `stale_after_seconds` and one
carrying neither, entries addressable and prose, an entry carrying `subject` and `data`,
one carrying neither and one whose record was `refused`, a record carrying the typed
`at` / `started` / `ended` keys at two depths, a `maintenance` pin and a null, and the
`instance` block. It carries **both** shapes of `contribution`: the pin's, which
*withholds* a node and reports `code: null`, and a damped node's, which *transforms* one
— the node reads ERROR, the parent counted OK, and `contribution.code` is that OK. Those
two are deliberately both here: before damping every rule withheld, so a fixture with
only the null would quietly teach a client that `contribution` means *not counted*. It
is **generated from the server's own API** and a test holds the server to it, so it
cannot quietly stop being true.

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
