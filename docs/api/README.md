# Little Sister — Status API

A small, **read-only JSON** view of the aggregated status tree. The same routes serve
the HTML dashboard; the representation is chosen by the `Accept` header. This page is
the practical guide; the normative reference is the [`openapi.yaml`](openapi.yaml)
beside it (design rationale lives in the project's ADR-0008).

## At a glance

- **Base URL** — per deployment (the spec's sample server is `http://localhost:8000`).
- **Auth** — a bearer token (below). Required for JSON; the browser/session path is
  separate and not part of this contract.
- **Format** — request `Accept: application/json`. Responses are a versioned envelope
  (`schema_version`, `generated_at`, `status`).
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
BASE=http://localhost:8000

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

A node in the response carries its status (`own_code` / `code` / `reasons` / `stale`),
timing (`timestamp`, `frequency_seconds`), Markdown metadata (`about`, `title`,
`description`, `config` — **raw Markdown**, render it client-side), `maintenance` plus
`maintenance_details` when pinned, and `children` (name-sorted). Full field docs are in
[`openapi.yaml`](openapi.yaml).

## Errors

Failures are **Problem JSON** (RFC 9457), media type `application/problem+json`:

```json
{ "type": "about:blank", "title": "Unauthorized", "status": 401 }
```

- `401` — missing or invalid bearer token.
- `404` — no node at the given path.

## Versioning

Compatible changes are **additive** and bump the spec's minor `info.version`;
`schema_version` (in the envelope) bumps only on a **breaking** change, which is offered
through a versioned media type — never a versioned URL. Decode defensively: tolerate
unknown fields, and refuse an unknown `schema_version` major.

## Rendering the spec

[`openapi.yaml`](openapi.yaml) is OpenAPI 3.1. Browse it with any viewer, e.g.
[Redoc](https://github.com/Redocly/redoc) or
[Swagger UI](https://github.com/swagger-api/swagger-ui), or generate a client with
[openapi-generator](https://openapi-generator.tech/).
