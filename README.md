<div align="center">

<img src="src/little_sister/static/favicon.svg" width="96" alt="">

# little sister

*is watching for you.*

</div>

I am little sister.

Unlike Big Brother, I’m not watching you — I’m watching for you. My eyes stay on
the things you care about: disks filling up, batch jobs failing, security
advisories appearing, and automated workflows turning red.

You decide where I look. I’ll keep watch and let you know when something needs
your attention, so you can work peacefully — and sleep calmly.

> *Big Brother watches you, little sister watches out for you.*

---

## Description
little sister is a small monitoring application you can stand up in an afternoon. It
runs configurable **checks** on background threads, aggregates their results into a
single status **tree**, and serves that tree over a small web interface.

A check is an ordinary Python script. If you can write one, you can teach little sister
to watch something — and for the usual suspects there are ready-made check types to
configure instead of writing anything at all.

It is built to start small and stay useful as the situation grows. Watching a homelab
needs nothing beyond a configuration directory: a few checks, a user list, and the
install below. Serving as a team's dashboard inside a larger organization is the same
application after some adaptation — running in the cloud behind a load balancer, taking
its secrets from a secret store rather than an `.env` file, authenticating against
something other than its own user list. Those are seams the design makes room for
rather than features already shipped. What *is* shipped is the surface they rest on: a
check type, an extra page, or a connection to the ticket system of your choice can live
in a package of its own and register itself at startup.

See `docs/` for the full picture — `project.md` (what it is), `architecture.md`
(how the code is built), `use-cases.md` (the vision, in concrete scenes),
`implementing-checks.md` (how to build a check type of your own),
`testing-the-gui.md` (previewing the web UI under extreme layouts and live
scenarios).
Design rationale is in `decisions.md` + `adr/`. The JSON API contract is
`docs/api/openapi.yaml` (usage notes alongside). The native macOS menu-bar client
lives in its own repository,
[little-sister-app](https://github.com/m-31/little-sister-app), and consumes the JSON API.

## Installation and local testing

### Prerequisites

#### Software
Python **3.11 or later** ([ADR-0054](docs/adr/0054-python-floor-and-development-version.md)).
Development and the quality gate run on 3.14, so that is the best-tested interpreter; the
floor is checked rather than assumed — the type check runs against it on every commit and
the whole test suite runs against it on every release. No external services are required —
all state is kept in memory.

#### Ways in
**An install can have several doors, and which ones it has is its own choice**
([ADR-0069](docs/adr/0069-identity-comes-from-outside-and-one-account-does-not.md)).
A *door* is a registered identity provider with a name and a route of its own —
`/login/<door>` — and `/login` is whichever one the install made the default. **An
install registers its own doors, all of them**, in the `wsgi.py` it already has,
before the app is imported; the library adds none on anybody's behalf, so what that
file says is what the instance has. One that registers nothing starts, warns that
nobody can sign in, and lets nobody in. Nothing below is required reading for the case
this project protects: a personal dashboard on your own machine gets the built-in
login list, and the line for it is already in the file.

- **The built-in login list** (`local`), described just below: `local_login.use_local()`
  registers it as the default door, so `/login` is its form. It is the only reader of
  the user list, which is why an install with a provider of its own needs none.
- **Your own identity provider**, registered in the same place:
  `identity.use(name, provider, default=True)`. What a provider answers is
  *who is this request*, not *the login flow*, so one that verifies a header a load
  balancer already signed implements two methods and no flow at all. A deployment
  with a provider of its own **needs no `config/users.yaml`**: the list is read only
  when its door is the one in use.
- **The system-admin account** (`system-admin`), the one door the library ships,
  because the provider can stop answering and that is when somebody needs to get in.
  It is configured — never generated, never assumed — in the same place:

  ```python
  identity.use_system_admin(reference="env://LITTLE_SISTER_SYSTEM_ADMIN_PASSWORD")
  ```

  Login name `admin`, at `/login/system-admin`, always a local form even under a
  provider that redirects elsewhere. The password is named rather than carried, so a
  literal in a committed `wsgi.py` fails at startup; if the reference does not
  resolve, that door is shut and the application keeps serving. A session opened
  through it wears a distinct avatar and says *System admin* on every page. The
  built-in login page links to it while it can take a password — which is a
  convenience for the install whose `/login` is a local form, and not the incident
  path: under a provider that redirects, `/login` renders nothing of ours.

**Several ways in are allowed; an ordered list of them to try is not.** A session
records the door that opened it and only that provider is ever asked, so no
registration order can decide who somebody is. Every door an install has is on
`/system`, with the package that registered it.

**`/login` can offer the doors instead of going to the default one** — add
`identity.choose_at_login()` beside your registrations, and give each door a `label=`
worth reading. What an *unidentified request* gets is unchanged, which is the point:
under an identity provider with a live session that redirect is silent and stays
silent, while the address somebody types becomes a page we serve — and therefore one
that still answers on the morning that provider does not. A redirecting provider needs
a `login_page()` returning its own redirect to appear on it.

**After `./setup.sh`, the only admin is behind the system-admin door**: the generated
login is `viewer` with the editable placeholder password, and the credential with real
entropy is `LITTLE_SISTER_SYSTEM_ADMIN_PASSWORD` in `.env`, which is meant to be read
rather than typed. Add `admin: true` to a user in the list below for an everyday admin.

#### Users
The allowed users are defined by the `users` aspect of the configuration roots: either
**`config/users.yaml`** on its own or **`config/users/users.yaml`** beside optional
avatar files. The first configuration root declaring either form wins whole — so a
deployment that keeps its login list somewhere else gives that file a configuration
root of its own and names it **first** in `LITTLE_SISTER_CONFIG_DIR`, which is the only
way in
([ADR-0046](docs/adr/0046-user-list-from-the-configuration-roots.md),
[ADR-0031](docs/adr/0031-deployment-config-directory.md),
[ADR-0045](docs/adr/0045-user-avatars.md)). Start with the directory form so pictures
can be added without another layout change:

```bash
mkdir -p config/users/avatars
cp src/little_sister/users.example.yaml config/users/users.yaml
```

What you just copied — the format is one top-level key per login name:

```yaml
jdoe:
  firstname: "Jane"
  lastname: "Doe"
  password: "change-me"
  admin: true
  avatar: jdoe
amorgan:
  firstname: "Alex"
  lastname: "Morgan"
  password: "change-me-too"
```

`avatar` is a bare file name inside `config/users/avatars/`. The extension is optional,
so `avatar: jdoe` finds a single `jdoe.svg`, `jdoe.png`, `jdoe.webp`, or another
supported image; `avatar: jdoe.png` selects that file exactly. No top-level avatar map
is needed because each picture belongs to one user. A user without a usable image gets
the packaged neutral avatar, and a bad reference never prevents login.

So out of the box `jdoe` logs in with password `change-me` and has admin rights,
`amorgan` is a viewer — change both passwords before anyone else can reach the
instance. (Both forms of the real user aspect are git-ignored.) What `./setup.sh`
writes instead is one `viewer` login and no admin at all, because the admin of a fresh
install is the system-admin account above.

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
  ([ADR-0080](docs/adr/0080-the-envelope-is-the-snapshot-published.md)) — named
  per-client bearer
  tokens; clients send them as `Authorization: Bearer <token>` with
  `Accept: application/json`. Without them the JSON API rejects all requests:

  ```bash
  LITTLE_SISTER_API_TOKENS="swift-app=s3cret,satellite-eu=an0ther"
  ```

- **Check credentials** — a check's YAML names its secrets in a `secrets:`
  block, each a **secret reference**
  ([ADR-0023](docs/adr/0023-secret-references.md)): `env://GITHUB_TOKEN` reads
  that environment variable, and a reference like `aws-sm://team/token` is
  resolved by a resolver the deployment registers in its own code — once at
  startup, never during runs. Because the reference lives in the config, one
  check type serves several instances with a credential each (one per team, say).

##### Running without a `.env` file

A deployment can retire the file entirely. `SECRET_KEY` and
`LITTLE_SISTER_API_TOKENS` accept a **value that is itself a reference** — e.g.
`SECRET_KEY="aws-sm://team/session-key"` — resolved once at startup through the
same deployment-registered resolvers (which reach their store with ambient
credentials, e.g. an instance role); or simply omit `SECRET_KEY` for the random
per-start key. Check credentials move to a store via their references. What would
otherwise remain is the **user list** (`config/users.yaml` or
`config/users/users.yaml`,
[ADR-0046](docs/adr/0046-user-list-from-the-configuration-roots.md)) behind the
built-in username/password login — and a deployment that supplies an **identity
provider of its own** carries no such file at all
([ADR-0069](docs/adr/0069-identity-comes-from-outside-and-one-account-does-not.md)):
the list is read by `local_login.use_local()` and by nothing else, so an installation
that does not register that door never looks for it. An install that keeps the
built-in login keeps
that one secret-bearing file, which is the right trade for the case it serves — one
person, one machine, nothing else to run.

#### The configuration directory (`config/`)

Everything a deployment authors lives in one place — **`config/`**, whose entries are
*aspects*: `checks/`, `nodes.yaml`, `settings.yaml`, `csp.yaml` and `users.yaml` or
`users/` ([ADR-0031](docs/adr/0031-deployment-config-directory.md)). `LITTLE_SISTER_CONFIG_DIR`
selects it and is a **path-list**: `base:sites/alpha` composes a shared base with a
site's own additions, and each aspect combines its layers in the way that suits it —
checks union, settings merge per key, the user list is taken whole from the first root
that declares it. Startup is strict about the tree and tolerant about its contents: no
configuration directory, a named root that does not exist, or no `checks/` anywhere and
the process **refuses to start**, naming the path it looked at; a `config/checks/` that
exists but is still empty runs, warns, and shows **WARN** on the heartbeat.

`.env` stays outside it — that is secrets, not authored configuration — and so does
`var/`, which is what the process writes rather than what you give it.

#### Checks
Check configs are loaded from `config/checks/` in every configuration root. This repo
ships **templates** in `config/checks/examples/` — copy the ones you need up into
`config/checks/`, or point `LITTLE_SISTER_CONFIG_DIR` at your own tree. A full
private deployment (real per-host checks, users and secrets) lives in its **own
repository** that consumes little-sister as a library. Writing your **own check
type** — a new `type:` backed by a Python class, registered through the public
`CHECK_TYPES` seam — is covered in
[`docs/implementing-checks.md`](docs/implementing-checks.md).

#### General options (`config/settings.yaml`)

Display and runtime options live in an optional **`config/settings.yaml`**, read once
at startup and shallow-merged per key across the configuration roots, the later
winning (override the whole thing with a single file via `LITTLE_SISTER_CONFIG`);
every key has a default, so a missing file is fine
([ADR-0006](docs/adr/0006-config-file-and-timezones.md)). A deployment carries
its **own** copy — the file in this repo configures a local run here and doubles as
the template. Three of its keys, to show the shape:

```yaml
timezone: Europe/Berlin              # IANA name for displayed timestamps
time_format: "%Y-%m-%d %H:%M:%S"     # strftime for displayed timestamps
maintenance_default_expiry: 7d       # maintenance window when none is given
```

The shipped file documents the rest inline — the dashboard caps (`reason_cap`,
`branch_cap`, `maintenance_cap`), whether a failing check keeps its `stacktrace`,
the card-head placement (`card_status_line`: compact `beside` by default, or the
standing second line `below`), how cards spend a wide grid's columns
(`dashboard_columns`: `flow` by default, or `plain` for the fixed one-track
grid), the failure-retry budget (`retry_interval`, `retry_attempts`), how often
the kept state files are written (`state_interval`), how many consecutive worse
readings a node needs before the level above counts it (`escalate_after`), and the
engine's four sizing numbers — `max_workers`, `entry_limit`, `memory_share` and
`record_limit`, which are both what the instance measures itself against while it runs
and what a check type's declarations are measured against at startup.

#### Curated links (`config/links.yaml`)

The shared toolbox `/links` shows — the dashboards and tools a team reaches for while
something is on fire — is an optional aspect of the same directory
([ADR-0030](docs/adr/0030-curated-links.md)): one flat level of `groups:`, each an
ordered list of entries with a `title`, a `url`, an icon **name** and an optional
one-line `note`. Seventeen marks are built in and need no configuration; a `check:`
block turns on reachability probing, which runs when somebody **opens** the page and
the answers are older than its `interval:`, never on a timer.

**Shipping marks of your own makes this aspect a directory.** The two legal forms are
`config/links.yaml` on its own, and `config/links/` holding `links.yaml` beside an
`icons/` directory. Only the second can carry files: an `icons/` sitting next to a
flat `config/links.yaml` is a directory in a configuration root, so it warns as an
unrecognized aspect and is ignored
([ADR-0031](docs/adr/0031-deployment-config-directory.md)). Growing from one form into
the other is a move, not a rename.

```
config/links/
├── links.yaml
└── icons/
    ├── firewall.svg              # `icon: firewall` — the file is the name
    ├── payments-on-light.svg     # a pair, named for the background it goes on
    └── payments-on-dark.svg
```

#### Content-Security-Policy sources (`config/csp.yaml`)

Every page carries a **`Content-Security-Policy-Report-Only`** header: a violation is
logged and **nothing is blocked**, so it costs no page any behavior and tells you what
a strict policy would have caught. The policy is *assembled* — the library's own
defaults, plus origins a dependent package declares in code, plus this optional file
([ADR-0048](docs/adr/0048-an-assembled-content-security-policy.md)). Two things belong
here and nowhere else: an origin no package knew about (an image host a check's
Markdown embeds), and a policy **keyword** such as `'unsafe-inline'` — a package may
contribute an origin and never one of those, because one dependency able to relax the
policy would make it decorative for every other. One key per directive, each a list of
sources, **added** to the policy and layered across the configuration roots like the
rest:

```yaml
img-src:
  - https://assets.example.org
connect-src:
  - https://tickets.example.org
```

`/system` prints the effective policy with the contributor of every source, so what
this file did is visible from the running instance. The shipped copy is an example
with every entry commented out.

### Installation

#### From the package index

For running little sister. It needs **Python 3.11 or later**
([ADR-0054](docs/adr/0054-python-floor-and-development-version.md)) — on anything older
the resolver declines to install, which is the intent rather than a packaging mistake.

```bash
pip install little-sister            # or: uv pip install little-sister
```

The package is the application, not a configuration. It starts from a **configuration
directory** and refuses to start without one; the smallest that works is a user list
and a `checks/` directory, which may be empty:

```bash
mkdir -p config/checks config/users
cat > config/users/users.yaml <<'YAML'
admin:
  firstname: "Admin"
  lastname: "User"
  password: "change-me"
  admin: true
YAML
cat > wsgi.py <<'PY'
# An install registers its own doors, all of them, before the app is imported;
# with none registered nobody can sign in. This one is the built-in login list.
from little_sister import local_login
local_login.use_local()
from little_sister.app import app  # noqa: E402
PY

# A SINGLE worker: the engine and the status tree live in-process.
gunicorn --workers 1 --threads 8 --bind 0.0.0.0:8888 wsgi:app
```

One worker is not a suggestion — the engine and the status tree live in the process
([ADR-0001](docs/adr/0001-in-process-threaded-engine.md)), so a second worker is a
second, disagreeing tree. The packaged `users.example.yaml` documents every field of
the user list, avatars included.

An empty `checks/` is allowed and reports itself — *nothing is being watched* is a
state little sister shows you, not a reason to refuse to start. The same node,
`/little-sister`, carries what the instance says about itself while it runs: a check
that runs longer than its `frequency`, a pool with checks waiting for a worker, a
scheduler tick that came late, the entry count and the resident size near their
limits, and a `timeout` longer than its `frequency` (warned about, never refused)
— each a line that clears when the condition does, pinnable like any other. Set
`SECRET_KEY` before
anyone relies on staying logged in: without one a random key is made per start, so
sessions end with the process. Runtime state is written to `var/` beside the
configuration: the log, and under `var/state/` what a restart keeps — the maintenance
pins and the event log. That directory is what a **keeper** carries: a deployment that
registers one has it restored from there at startup and mirrored back to it while the
instance runs, so a redeployment onto a fresh machine comes up with the state it left
on the old one. Where two instances share a keeper's store, whoever holds its lease is
the authority: an instance that takes the lease over adopts what the store changed
while it stood by, keeps what it had beside each file as `.bak`, and lists them on
`/little-sister/state`, where an admin can take them back. None ships with the
library, and an installation that registers none keeps its state on the machine it
is on.

On your browser, navigate to `http://localhost:8888`.

#### From a checkout

For developing little sister itself, or running a branch. The project is managed with
[uv](https://docs.astral.sh/uv/) (it reads `uv.lock`).

```bash
uv sync                              # create .venv and install from the lockfile
uv run gunicorn --workers 1 --threads 8 --bind 0.0.0.0:8888 little_sister.app:app
```

First-time setup: on a fresh checkout, **`./setup.sh`** creates
`config/users/users.yaml`, its empty `avatars/` directory, and `.env` (one `viewer`
login — the admin of a fresh install is the system-admin door above — and a random
session key), prompting before it overwrites anything. An
existing flat `config/users.yaml` is kept and the script prints the manual move needed
before adding avatars. Then the
repo's helper scripts (they need `lsof` and `curl`) manage the run: **`./start.sh`**
runs gunicorn in the background with safe port handling — it restarts its own instance,
under either scheme (a checkout serves one instance, so starting one way replaces one
started the other), and refuses to touch a foreign process on the port — logging to
`var/`. Its preflight
accepts both users-aspect forms (and follows the configured root path-list) before it
starts. **`./stop.sh`** stops it, whichever scheme it was started under; **`./test_api.sh`**
smoke-tests the running JSON API
(token from `LITTLE_SISTER_API_TOKENS`). Override the bind with
`LITTLE_SISTER_HOST` / `LITTLE_SISTER_PORT`.

An instance belongs to the checkout it runs in — so a second checkout of this
application on the same port is refused rather than quietly restarted or stopped. The refusal says what is in the
way; **`--any-instance`** on `./start.sh` or `./stop.sh` acts on it anyway. It reaches a
gunicorn and nothing else: anything else on the port is still refused.

**`--tls` serves HTTPS**, on its own port (`TLS_PORT` in `instance.sh`, `8443` by
default) so the two schemes can never be confused for one address. All three scripts
take it, because each of them has to reach the instance:

```bash
./start.sh --tls        # https://localhost:8443
./test_api.sh --tls
./stop.sh --tls
```

Set `TLS_CERT` and `TLS_KEY` (both, or neither) to serve a certificate you already
have; `start.sh` says so if nothing on the machine trusts it. With neither set, it
**mints a self-signed certificate for the run** and overwrites it at the next start —
enough for a local instance, and for one behind something that terminates the public
certificate itself, but a browser will warn every time. The scripts never verify the
certificate themselves: they are talking to a process on this machine that they just
started, and a probe that failed on trust would report a serving instance as dead.

To query the read-only JSON API, send a bearer token (from
`LITTLE_SISTER_API_TOKENS`) with `Accept: application/json`:

```bash
curl -H "Accept: application/json" -H "Authorization: Bearer s3cret" \
     http://localhost:8888/status/system/db
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
