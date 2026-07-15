# Little Sister

## Description
Little Sister is a web application that shows the status of various systems. It
runs configurable **checks** on background threads, aggregates their results into
a single status **tree**, and serves it over a small web interface.

See `docs/` for the full picture — `project.md` (what it is), `architecture.md`
(how the code is built), and `use-cases.md` (the vision, in concrete scenes).
Design rationale is in `decisions.md` + `adr/`. The JSON API contract is
`docs/api/openapi.yaml` (usage notes alongside). The native macOS menu-bar client
lives in its own repository,
[little-sister-app](https://github.com/m-31/little-sister-app), and consumes the JSON API.

## Installation and local testing

### Prerequisites

#### Software
Python 3.14 or later. No external services are required — phase 1 keeps all state
in memory.

#### Users
The allowed users are currently defined in a `users.yaml` file. little-sister reads it from
`LITTLE_SISTER_USERS` if set, otherwise `users.yaml` in the working directory
([ADR-0020](docs/adr/0020-user-list-location.md)). Copy the shipped template to start:

```bash
cp src/little_sister/users.example.yaml users.yaml
```

The format:

```yaml
jdoe:
  firstname: "Jane"
  lastname: "Doe"
  password: "test1234"
  admin: true
amorgan:
  firstname: "Alex"
  lastname: "Morgan"
  password: "passw0rd"
```

With the above, `jdoe` logs in with password `test1234` and has admin rights.
(`users.yaml` is git-ignored.)

#### Secrets
Configuration secrets are read from a git-ignored `.env` file — at minimum the
Flask session key:

```bash
SECRET_KEY="change-me"
```

For the read-only JSON API ([ADR-0008](docs/adr/0008-json-output-api.md)), define
named per-client bearer tokens. Clients send them as `Authorization: Bearer <token>`
with `Accept: application/json`:

```bash
LITTLE_SISTER_API_TOKENS="swift-app=s3cret,satellite-eu=an0ther"
```

#### Checks
Check configs are loaded from the directory in `LITTLE_SISTER_CHECKS_DIR` (default
`checks/`). This repo ships **templates** in `checks/examples/` — copy the ones you
need into `checks/`, or point `LITTLE_SISTER_CHECKS_DIR` at your own directory. A full
private deployment (real per-host checks, users and secrets) lives in its **own
repository** that consumes little-sister as a library.

### Installation

This project is managed with [uv](https://docs.astral.sh/uv/) (it reads `uv.lock`).

```bash
uv sync                              # create .venv and install from the lockfile

# Run with a SINGLE worker: the engine and the status tree live in-process
# (see docs/adr/0001-in-process-threaded-engine.md).
uv run gunicorn --workers 1 --threads 8 --bind 0.0.0.0:8000 little_sister.app:app
```

On your browser, navigate to `http://localhost:8000`.

First-time setup: **`./setup.sh`** creates `users.yaml` and `.env` (a default `admin`
login and a random session key), prompting before it overwrites anything. Then the
repo's helper scripts (they need `lsof`) manage the run: **`./start.sh`**
runs gunicorn in the background with safe port handling — it restarts its own instance
and refuses to touch a foreign process on the port — logging to `var/`; **`./stop.sh`**
stops it; **`./test_api.sh`** smoke-tests the running JSON API (token from `LITTLE_SISTER_API_TOKENS`). Override the bind with
`LITTLE_SISTER_HOST` / `LITTLE_SISTER_PORT`.

To query the read-only JSON API, send a bearer token (from
`LITTLE_SISTER_API_TOKENS`) with `Accept: application/json`:

```bash
curl -H "Accept: application/json" -H "Authorization: Bearer s3cret" \
     http://localhost:8000/status/system/db
```

## Testing scripts locally

```bash
ssh your-host bash -xs < src/little_sister/scripts/host-metrics-linux.sh
```

## Quality gate

`ruff` + `mypy` + `pytest`. Run them with uv:

```bash
uv run ruff check      # lint
uv run mypy            # type-check (strict, on src)
uv run pytest          # tests
```

## Git hooks

A pre-commit hook that runs those three lives in `hooks/`
(version-controlled, unlike `.git/hooks/`). Enable it once per clone:

```bash
git config core.hooksPath hooks
```

After that, commits are blocked if lint or tests fail.

## Contributing

Development happens on a private working branch; `main` carries releases only —
one squashed commit per version. Bug reports and feature requests go through
[GitHub issues](https://github.com/m-31/little-sister/issues). Pull requests are
welcome too: an accepted PR is absorbed into the working branch and lands in the
next release, credited with `Co-authored-by`.
