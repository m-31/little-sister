# Changelog

All notable changes to little-sister, newest first. The format follows
[Keep a Changelog](https://keepachangelog.com/); releases are cut with the release
pipeline (see [`docs/create_a_release.md`](docs/create_a_release.md)), which rolls
the **[Unreleased]** notes below into the tagged version. The JSON API
contract versions **separately** — see `docs/api/openapi.yaml` `info.version`.

## [Unreleased]

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
