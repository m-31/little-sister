# ADR-0008 — JSON output (backend mode): endpoint, schema & token auth

- **Status:** Accepted
- **Date:** 2026-06-25
- **Related:** [ADR-0002](0002-rlock-snapshot-synchronization.md) (snapshots are the
  serializable copy), [ADR-0003](0003-config-and-secrets-via-env-file.md) (`.env`
  secrets/tokens), [ADR-0004](0004-status-aggregation-semantics.md) (roll-up),
  [ADR-0005](0005-dashboard-freshness-and-self-monitoring.md) (freshness),
  [ADR-0007](0007-check-result-branches.md) (the recursive result is the same tree
  shape this format carries).
- **Register:** [`../decisions.md`](../decisions.md)
- **Contract:** [`../api/openapi.yaml`](../api/openapi.yaml) — the normative schema.

## Context
`project.md` §2.9: the web app should serve the status tree (or a
branch by `path`) as **JSON**, so other apps can use little-sister as a backend — the
motivating client is a native **macOS Swift** app on another machine — and so a
central instance can **graft** a satellite's branch (the JSON format *is* the
federation protocol). This ADR settles the **serving** side.

We align with the [Zalando RESTful API
Guidelines](https://opensource.zalando.com/restful-api-guidelines/) and describe the
result as an **OpenAPI 3.1** document (the contract above). Where we deviate, it is
listed and justified.

We already have the hard part. `StatusTree.snapshot(path)` (ADR-0002) returns an
immutable `StatusSnapshot` subtree — `own_code`, rolled-up `code`, `reason`,
`timestamp`, `description`, `frequency_seconds`, `maintenance`, `stale`, `children` —
all computed under the lock. JSON output is a **pure serialization of that snapshot**
plus a representation branch and an auth gate: no new state, no new threads, the
single-worker constraint (ADR-0001) untouched.

Two wrinkles drive the decisions: (1) timestamps are stored **naive server-local**
(ADR-0006), ambiguous once a value crosses machines; (2) the same bytes serve **two
readers** — a display client (wants the rolled-up code) and a federating parent
(wants each node's *own* code so it can re-roll locally).

## Decision

1. **Content negotiation on the existing, unversioned resource.** `GET /status` and
   `GET /status/<node_path>` stay the canonical URLs; the **representation** is chosen
   by `Accept`. `Accept: application/json` (strict `best_match`) returns JSON; the
   browser default and the dashboard's `?fragment=1` poll keep getting HTML,
   unchanged. **No version in the path** (Zalando #115); the URL identifies the
   resource, not the format. This also matches `project.md` §2.9's "content
   negotiation" wording.

2. **A top-level JSON object** (Zalando #110) carrying the protocol version and the
   serving instance's clock:
   ```json
   { "schema_version": 1, "generated_at": "2026-06-25T18:05:00Z", "status": { "…": "node" } }
   ```

3. **Node schema** — a recursive serialization of `StatusSnapshot`, named per the
   guidelines:
   ```json
   {
     "path": "system.db", "name": "db",
     "own_code": "ERROR", "code": "ERROR",
     "reasons": ["HTTP 503 from /health"],
     "timestamp": "2026-06-25T18:04:55Z",
     "description": "Primary database", "frequency_seconds": 60,
     "maintenance": false, "stale": false,
     "children": []
   }
   ```
   - **`snake_case` property names** (Zalando #118).
   - **Codes are `UPPER_SNAKE_CASE` string enums** — `"OK"` / `"WARN"` / `"ERROR"` /
     `"MAINTENANCE"` / `"UNDEFINED"` (Zalando #240), never the `auto()` numbers.
   - **`reasons` is plural** because it is an array (Zalando #120) — renamed from the
     model's `reason`.
   - **Both `own_code` and `code`.** `own_code` is the node's raw reported code;
     `code` is the serving instance's rolled-up, stale-degraded effective status. A
     display client reads `code`; a federating parent grafts `own_code` + `children`
     and **re-rolls locally** (avoids double aggregation).
   - **`timestamp` / `generated_at` are RFC 3339 `date-time` in UTC** with upper-case
     `T`/`Z` (`…Z`), converted at serialization (Zalando #238, naming #235). Internal
     storage stays naive-local (ADR-0006); only the wire is normalized, so
     cross-machine age/staleness is well-defined.

4. **Errors are Problem JSON** — `application/problem+json` per RFC 9457 (Zalando
   #176): `type`, `title`, `status`, `detail`. `401` (missing/bad token), `404` (no
   such node), `406` (JSON not acceptable). **No stack traces** (Zalando #177).

5. **Bearer-token auth, representation-coupled.** A JSON request carries
   `Authorization: Bearer <token>`; HTML keeps the session cookie. Tokens are
   **named, per-client** entries provisioned in `.env` (ADR-0003), compared with
   `secrets.compare_digest`; the name is for logging/telemetry later. No new
   dependency.

6. **Compatible evolution, never URL versioning.** Additive fields keep
   `schema_version: 1` and the spec's semver minor (Zalando #113, #116). A
   **breaking** change bumps `schema_version`, the OpenAPI `info.version` major, and —
   on the wire — uses **media-type versioning** via a custom `application/…+json`
   type negotiated by `Accept` (Zalando #114), not a `/v2` path (#115).

7. **One self-contained OpenAPI 3.1 document** at `docs/api/openapi.yaml` (Zalando
   #101) with the required meta — `title`, semver `version`, `description`,
   `contact`, `x-api-id`, `x-audience: component-internal` (Zalando #218/#215/#219).

8. **Read-only, this slice.** Serving only. Write **actions** (e.g. set maintenance)
   and **per-token scopes** are deferred; the `.env` token format stays extensible (a
   token may later map to name + scopes) so adding them doesn't break the wire.

## Consequences
- The Swift client and any satellite read a stable, documented tree with no
  persistence and no second worker — a thin layer over existing snapshots.
- **Federation falls out of the schema.** A parent upserts each node's `own_code`
  and lets ADR-0004 roll up; a remote node in `MAINTENANCE` still cancels its subtree
  (roll-up keys on the code). The parent recomputes staleness from the now-unambiguous
  UTC `timestamp` — **cross-host clock skew** is a known limit; `generated_at` gives a
  future graft a reference point to correct against.
- `schema_version` + media-type versioning is the evolution lever; satellites can
  refuse an unknown major.
- Read-only means a leaked token exposes status, not control — a deliberately small
  blast radius for the first cut (a new required `.env` key, fail-fast per ADR-0003).

> **Update (2026-06-26):** the envelope gained the Phase-2 node-metadata fields —
> `about` (ADR-0012), `title` (ADR-0017), `config` (ADR-0013), all **raw Markdown**
> (the client renders, ADR-0018) — and a nullable **`maintenance_details`** object
> (`reason` / `set_by` / `set_at` / `expires_at`, ADR-0014) beside the existing
> `maintenance` bool. All **additive**, so `schema_version` stays **1** and the existing
> `maintenance` bool is unchanged; the federating parent now renders grafted nodes (and
> their maintenance windows) exactly as the origin. Contract + register:
> [`api/openapi.yaml`](../api/openapi.yaml), [`../decisions.md`](../decisions.md).

## Deliberate deviations from Zalando
- **Static bearer tokens, not OAuth2.** The guidelines assume an OAuth2 provider;
  little-sister is **internal-only** (`project.md` §5) with no IdP, so a per-client
  token from `.env` is the proportionate choice. The `Authorization: Bearer` shape is
  kept, so a move to OAuth2 later is non-breaking.
- **`X-Flow-ID` (Zalando #233) not required.** It exists to correlate requests across
  Zalando's distributed infra; we are one process. We will **echo** an inbound
  `X-Flow-ID` if present, but not mandate or generate one.

## Alternatives considered
- **`/api/v1/...` path versioning.** Rejected: Zalando
  #115 forbids URL versioning and #114 mandates media-type versioning; content
  negotiation also keeps one canonical resource URL and matches §2.9.
- **Ad-hoc `{ "error": … }` body.** Rejected for Problem JSON (#176).
- **Codes as numbers** (the `auto()` values). Rejected: brittle and not the severity
  order; string enums per #240.
- **Rolled-up `code` only.** Rejected: a federating parent would double-aggregate.
- **Reuse the session cookie for JSON.** Rejected: couples a browser concern to a
  machine client; a bearer token is the standard fit and cleanly representation-keyed.
