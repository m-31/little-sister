# Changelog

All notable changes to little-sister, newest first. The format follows
[Keep a Changelog](https://keepachangelog.com/); releases are cut with the release
pipeline (see [`docs/create_a_release.md`](docs/create_a_release.md)), which rolls
the **[Unreleased]** notes below into the tagged version. The JSON API
contract versions **separately** — see `docs/api/openapi.yaml` `info.version`.

## [Unreleased]

## [0.2.1] - 2026-07-19

### Added

- **Secret references** ([ADR-0023](docs/adr/0023-secret-references.md)): a check
  credential in YAML names its source — a bare environment-variable name (the
  unchanged default, fed by `.env`) or a `scheme://address` reference resolved by
  a resolver the deployment registers in code
  (`little_sister.secrets.register_resolver`). Secrets resolve **once, at check
  construction**, never during runs; a reference that cannot be resolved pins
  just that check to a visible ERROR ("secret unresolvable: …") instead of
  stopping the engine.
- The application settings `SECRET_KEY` and `LITTLE_SISTER_API_TOKENS` may now
  themselves be **secret references** (`scheme://address`), resolved once at
  startup through the deployment's registered resolvers — one step closer to
  running without any `.env` file. An unresolvable reference degrades safely
  (random session key / no API tokens, loudly logged); a malformed one fails
  startup.
- A developer guide for building custom check types,
  [`docs/implementing-checks.md`](docs/implementing-checks.md) — the `Check`
  contract, branch results, registration and startup wiring, secret references,
  testing.

### Fixed

- The dashboard's live-refresh line ("updated …" / "could not refresh — last
  ok …") now renders its timestamp with the configured `time_format` and
  timezone (`config.yaml`), matching every other displayed time. It previously
  used the browser's locale, so a 24-hour deployment saw a 12-hour "AM/PM"
  clock in that one spot.
- Distribute a `py.typed` marker (PEP 561) so downstream projects can
  type-check against little-sister. Without it, type checkers treated the
  installed package as untyped and reported missing type information for
  `little_sister` imports.

### Security

- Without `SECRET_KEY`, little-sister now generates a **random session key at
  each start** instead of falling back to a fixed, insecure development key.
  Sessions (logins) reset on a restart unless an explicit key is configured.

## [0.2.0] - 2026-07-15

First release. little-sister is a small, self-hosted status dashboard:
configurable **checks** run on background threads in a single process, their
results aggregate into one **status tree**, and the tree is served as a web
dashboard and a read-only **JSON API**.

- **Checks:** `http`, `file`, `command`, and an SSH family — `ssh-connect`,
  `ssh-command`, `ssh-script`, `host-metrics`, `qnap-metrics` — with
  per-userland metrics scripts (Linux, macOS, busybox) shipped as package
  data; example configs in `checks/examples/`.
- **Status semantics:** worst-of roll-up with `MAINTENANCE` and `UNDEFINED`
  handling, freshness (an unobserved node degrades to WARN), engine
  self-monitoring, node metadata (`about`, `title`, `config` — Markdown),
  an event log and per-node history.
- **Web UI:** dashboard with drill-down and breadcrumbs, node detail pages,
  admin **maintenance** windows (always with an expiry), and a system page;
  session login with viewer/admin roles.
- **JSON API:** content negotiation on `GET /status[/<path>]`, named
  per-client bearer tokens, Problem-JSON errors; the normative contract is
  `docs/api/openapi.yaml` (OpenAPI 3.1) — this release serves **contract
  version 1.1.0** (envelope `schema_version: 1`).
- **Packaged as a library**, consumed by a separate deployment repository
  that holds the real checks, users and secrets; configuration and secrets
  come from the working directory and a git-ignored `.env`.

A native macOS menu-bar client lives in its own repository,
[little-sister-app](https://github.com/m-31/little-sister-app), and consumes
the JSON API.
