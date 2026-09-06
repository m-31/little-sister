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
`entries` holds the node's reasons: `addressable` says whether they are members with
stable slugs that can be pinned one by one, and each item carries its `text`, its own
`code` where the check declared one, and its own `maintenance`. `run` holds the timing
— `observed_at`, `wall_seconds`, `next_at`, and where there is a schedule
`frequency_seconds` and the `stale_after_seconds` the server measured freshness by —
and is **absent entirely** where nothing answers for the node, which is not the same
as present with a null `observed_at`. `maintenance` is one object or null, and the text on it is `note`. The
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

Decode defensively all the same: tolerate unknown fields and any child order, and
treat an absent `run` as *nothing answers for this node* rather than as an error.

## Rendering the spec

[`openapi.yaml`](openapi.yaml) is OpenAPI 3.1. Browse it with any viewer, e.g.
[Redoc](https://github.com/Redocly/redoc) or
[Swagger UI](https://github.com/swagger-api/swagger-ui), or generate a client with
[openapi-generator](https://openapi-generator.tech/).
