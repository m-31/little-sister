# Little Sister

## Description
Little Sister is a web application that shows the status of various systems. It
runs configurable **checks** on background threads, aggregates their results into
a single status **tree**, and serves it over a small web interface.

See `docs/` for the full picture — `project.md` (what it is), `architecture.md`
(how the code is built), `use-cases.md` (the vision, in concrete scenes),
`implementing-checks.md` (how to build a check type of your own), and
`testing-the-gui.md` (previewing the web UI under extreme layouts and live
scenarios).
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
Configuration secrets reach little-sister through the **environment**
([ADR-0003](docs/adr/0003-config-and-secrets-via-env-file.md)); a git-ignored
`.env` file in the working directory is the simple way to feed it, but any other
way of setting environment variables (a launchd/systemd unit, a container
orchestrator) works the same. Each piece is optional:

- **`SECRET_KEY`** — the Flask session-signing key. Unset, a **random key is
  generated at each start** (secure by default; the cost is that logins reset on
  a restart). Set it to keep sessions across restarts:

  ```bash
  SECRET_KEY="change-me"
  ```

- **API tokens** for the read-only JSON API
  ([ADR-0008](docs/adr/0008-json-output-api.md)) — named per-client bearer
  tokens; clients send them as `Authorization: Bearer <token>` with
  `Accept: application/json`. Without them the JSON API rejects all requests:

  ```bash
  LITTLE_SISTER_API_TOKENS="swift-app=s3cret,satellite-eu=an0ther"
  ```

- **Check credentials** — a check's YAML names its secret as a **secret
  reference** ([ADR-0023](docs/adr/0023-secret-references.md)): a bare name
  reads that environment variable; a `scheme://address` reference (e.g.
  `aws-sm://team/token`) is resolved by a resolver the deployment registers in
  its own code — once at startup, never during runs.

##### Running without a `.env` file

A deployment can retire the file entirely. `SECRET_KEY` and
`LITTLE_SISTER_API_TOKENS` accept a **value that is itself a reference** — e.g.
`SECRET_KEY="aws-sm://team/session-key"` — resolved once at startup through the
same deployment-registered resolvers (which reach their store with ambient
credentials, e.g. an instance role); or simply omit `SECRET_KEY` for the random
per-start key. Check credentials move to a store via their references. What
remains is the **user list** (`users.yaml`,
[ADR-0020](docs/adr/0020-user-list-location.md)) behind the built-in
username/password login — replacing it (an SSO provider such as Keycloak, or
password hashes in a database) is the authorization seam of the roadmap; until
that lands, `users.yaml` is the one secret-bearing file a deployment still owns.

#### Checks
Check configs are loaded from the directory in `LITTLE_SISTER_CHECKS_DIR` (default
`checks/`). This repo ships **templates** in `checks/examples/` — copy the ones you
need into `checks/`, or point `LITTLE_SISTER_CHECKS_DIR` at your own directory. A full
private deployment (real per-host checks, users and secrets) lives in its **own
repository** that consumes little-sister as a library. Writing your **own check
type** — a new `type:` backed by a Python class, registered through the public
`CHECK_TYPES` seam — is covered in
[`docs/implementing-checks.md`](docs/implementing-checks.md).

#### General options (`config.yaml`)

Display and runtime options live in an optional **`config.yaml`**, read once at
startup from the working directory (override the path with
`LITTLE_SISTER_CONFIG`); every key has a default, so a missing file is fine
([ADR-0006](docs/adr/0006-config-file-and-timezones.md)). A deployment carries
its **own** copy in its run directory — the file in this repo's root configures a
local run here and doubles as the template:

```yaml
timezone: Europe/Berlin              # IANA name for displayed timestamps
time_format: "%Y-%m-%d %H:%M:%S"     # strftime for displayed timestamps
maintenance_default_expiry: 7d       # maintenance window when none is given
```

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
