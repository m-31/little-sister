# Little Sister — Implementing a check type

How to implement a **new check _type_** — a Python class the engine can schedule.
This is the developer-side companion to [`checks/README.md`](../config/checks/README.md),
which covers the other half: how to _author_ a check (write the YAML for a type
that already exists).

Everything here applies to all three places a type can live: the **built-in** types
in this repo, the types a **deployment** adds through the public `CHECK_TYPES` seam
([`architecture.md`](architecture.md) §11), and the types an **installed package**
adds through the same seam. The class is identical in all three; only §4
(registration timing) differs, and §9 says which of the three a type belongs in.

That third one is not a plan any more. A type that outgrows the deployment it was
written in gets a repository of its own and arrives as an ordinary dependency —
`little-sister-github`, `little-sister-wiz` and `little-sister-jira` all did, and
their move was the evolution of this seam it was always described as, not a rewrite.
[`plugin-repository.md`](plugin-repository.md) is the procedure.

> Grounded in `src/little_sister/checks/` (`base.py`, `loader.py`, the built-in
> types) and `app.py`. If a name here drifts from the source, the source wins —
> update this doc.

---

## 1. The mental model

little-sister is **checks → engine → shared status tree → web + JSON API**. A *check*
is a small class that measures one thing and returns a value; the *engine* schedules
it at its `frequency`, and writes the result into the one shared status tree that the
web and JSON surfaces read. A check is a **pure function of the world → a result**: it
never touches identity, timestamps, maintenance or event history — those belong to the
tree ([ADR-0007](adr/0007-check-result-branches.md)).

Two things that sound alike but aren't:

- **Authoring** a check — writing a `checks/*.yaml` that configures an existing type.
  That's [`checks/README.md`](../config/checks/README.md).
- **Implementing** a check type — writing the Python class behind a `type:`. That's
  this document.

---

## 2. The `Check` contract

Everything is imported from the package `little_sister.checks` — the **check-authoring
surface** of the version contract ([`architecture.md`](architecture.md) §11), which
promises those names and leaves the modules beneath the package free to move. A check
type is a subclass of `Check` decorated with `@register("<type>")`:

```python
from __future__ import annotations

from pathlib import Path
from typing import Any

from little_sister.checks import (
    Check, CheckError, CheckResult, config_markdown, plain, register,
)
from little_sister.status import StatusCode


@register("example")            # the YAML `type:` name; also sets cls.type_name
class ExampleCheck(Check):
    """One-line description of what this check measures."""

    def __init__(self, *, url: str, **kwargs: Any) -> None:
        super().__init__(**kwargs)          # common fields (path, frequency, …)
        self.url = url                       # your own parsed fields

    @classmethod
    def _extra_from_config(cls, config: dict[str, Any],
                           base_dir: Path) -> dict[str, Any]:
        """Parse type-specific YAML into constructor kwargs. Raise CheckError
        on anything invalid — the loader prefixes it with the file name."""
        url = config.get("url")
        if not url:
            raise CheckError("example check requires a 'url'")
        return {"url": str(url)}

    def config_summary(self) -> str:
        """Optional: a curated, secret-free view of the params, shown on the
        node's detail page (ADR-0013)."""
        return config_markdown({"url": self.url})

    def run(self) -> CheckResult:
        """Do the work. A non-OK result MUST carry a reason."""
        ...
```

What the base class gives you and expects:

- **`run(self) -> CheckResult`** — the one abstract method. Bound by
  `self.timeout_seconds`; a non-OK result must carry a reason.
- **Construction from YAML** — `Check.from_config(config, base_dir)` merges the common
  fields (`_parse_common`) with your `_extra_from_config(...)` and calls the
  constructor. You override only `_extra_from_config`; you never parse `path` /
  `frequency` / `timeout` yourself.
- **Common fields** (parsed for you, all keyword-only on `__init__`): `path`
  (**required**, absolute and slash-separated, e.g. `/hosts/example.org`,
  [ADR-0016](adr/0016-node-addressing.md)), `description`, `about`, `title`,
  `frequency_seconds`, `timeout_seconds`. Durations accept `30s` / `15m` / `2h` /
  `1d` or a bare number. **`name:` in YAML is rejected** — it was merged into `path`
  (ADR-0016).
- **`config_summary(self) -> str`** *(optional)* — Markdown display metadata for the
  detail page ([ADR-0013](adr/0013-check-config-on-node.md)). Build it with
  `config_markdown({"label": value, ...})`; **never** put a secret in here. Default
  is empty.
- **`resolve_secret(self, reference)`** — resolve a credential **in the
  constructor** and keep the value; see §6
  ([ADR-0023](adr/0023-secret-references.md)).
- **`owned_nodes(self) -> set[str]`** *(optional)* — override only for a **branch**
  check (see §3): return the child subtrees you own, *not* the shared container node,
  so peers can share it ([ADR-0015](adr/0015-check-discovery-union.md)). Leaf checks
  get the default (`{self.path}`).

Raise **`CheckError`** for any bad configuration; the loader names the offending file.

---

## 3. `CheckResult`: a leaf or a whole tree

`CheckResult` is a frozen dataclass:

```python
CheckResult(
    code:        StatusCode | None,        # required — unless the entries carry their own (ADR-0042)
    reason:      list[str] = [],           # required when not OK; rendered as Markdown
    name:        str = "",                 # a child's id under its parent; empty on the root
    description: str = "",                 # node metadata
    children:    tuple[CheckResult, ...] = (),
    config:      str = "",                 # per-child config markdown (branch checks)
    report:      str = "",                 # what this run FOUND, markdown; root and children (ADR-0044)
    about:       str = "",                 # subnode subject label; child-only, fills empty (ADR-0025)
    title:       str = "",                 # subnode short label; child-only, fills empty (ADR-0025)
)
```

- **Leaf** — the common case: `CheckResult(StatusCode.OK)` or
  `CheckResult(StatusCode.ERROR, ["what went wrong"])`.
- **Branch (a dynamic subtree)** — return a root whose `children` are named
  `CheckResult`s; each child may itself have children. The engine upserts the root at
  `check.path` and each child beneath it
  ([ADR-0007](adr/0007-check-result-branches.md)). **Every child must set `name`**
  (enforced in `__post_init__`). This is exactly how one check can own a
  discovered-at-runtime tree — e.g. a repository check → one child per **aspect**
  (pull requests, security findings, …), each listing the repositories it flags (or a
  child per repository — both are just `children`).
- **Roll-up** — a container's displayed status is the **worst-of** its subtree; the
  tree computes that on read. So a branch root is normally `OK` and child problems
  surface through the roll-up. Use the **root's own** code for a check-wide failure:
  if discovery itself fails (bad token, API down), return
  `CheckResult(StatusCode.ERROR, ["discovery failed: …"])` with **no children**, and
  the whole branch goes red.
- **Status codes** — a check returns `StatusCode.OK`, `WARN`, or `ERROR`.
  `MAINTENANCE` / `UNDEFINED` are the tree's concern, not a check's (an *entry* may
  additionally carry `UNDEFINED` — a run that has never concluded; see the coded
  entries below). `coerce_code(...)`
  turns a config string (e.g. `stale_code: WARN`) into a `StatusCode`.
- **Coded entries** ([ADR-0042](adr/0042-entries-carry-their-own-code.md)) — where
  one node's lines have verdicts of their own (this workflow failed, that one
  passed), hand over `Entry` values and **omit `code`**; the node's stored code is
  then derived (worst-of the entries' codes, `UNDEFINED` ignored, an empty
  entry-bearing set reading `OK` — "nothing to report" is not "nothing reported"):

  ```python
  from little_sister.checks import Entry

  return CheckResult(reason=[
      Entry("web-build", "web (main) / build: failed after 8m14s · #4216 running 2m",
            StatusCode.ERROR, running=True),
      Entry("api-tests", "api (main) / tests: passed in 2m01s", StatusCode.OK),
  ])
  ```

  Declaring **both** a result code and entry codes is refused at construction — a
  silently ignored code would be believed. `running` marks a line whose subject
  has work in flight; it is display (an italic and a class), never severity, so
  the line's **text must still say it** in words. An entry carrying a code or
  `running` declares members by shape, like a mapping. Three author rules come
  with the power: **order the list non-OK first, then in-flight, then healthy**
  (`reason_cap` clamps the card, and healthy lines above the fold would bury the
  failures); **seen and counted ⇒ `WARN`, available but not counted ⇒ `OK` with a
  reason** (a permanent informational `WARN` holds the root amber — a legitimate
  choice, but a choice); and **split the node when the *group* is what an operator
  acts on, code the line when the *finding* is** — a severity band is a real node
  with a pin that silences the whole band, while a coded line keeps its pin when
  its state moves. Emitting healthy lines is a per-aspect choice, off by default;
  a run in flight should always produce a line.
- **Reasons are Markdown** — fold untrusted text in safely: `plain(text)` escapes an
  inline value (a path, an error, an API message); `code(text)` fences multi-line /
  log output as a verbatim block ([ADR-0018](adr/0018-markdown-rendering.md)). Never
  interpolate raw external bytes straight into a reason.
- **`report` — what the run found** ([ADR-0044](adr/0044-run-facts-on-the-node.md)) —
  the outputs field beside `config`'s inputs: the repositories in scope, the volumes
  enumerated, the queues discovered. Markdown, shown on the node's own page — never
  on a card, because volume is exactly what `reason_cap` exists to keep off the grid
  — and **written through on every run**: hand over an empty one and the last is
  cleared, which is the point, since a roster that outlives the run that found it is
  a lie by the next tick.

  Two author rules. **It is never a status claim**: anything that should alarm is a
  reason, and this field must not become a second, quieter reason channel. What
  separates them is **status, not volume** — a list whose items each carry a verdict
  belongs in the reasons as coded entries (and the card clamps them); a list whose
  items carry none is scope and belongs here. *The roster is presence; an entry is a
  claim.* So the **count** of what was found is an `OK` reason, where it is seen
  without opening anything, and the forty **names** go in `report`, where they cost
  nothing. **And it belongs to whoever owns the node alone**: put a whole-check
  statement on the root of a container your check owns outright; on a container
  **shared** with another check, tag the owned children instead — a shared node
  publishes neither `config` nor `report`, by the same rule that withholds its
  timestamp. A check with whole-check information to publish should own its own node.
- **Subnode labels — `about` / `title`** — a branch check can caption the subnodes it
  emits by setting a child's `about` (subject: what the aspect *is* and how it grades)
  and, rarely, `title` (a short label) ([ADR-0025](adr/0025-check-provided-subnode-metadata.md)).
  Set these only for **type-inherent** identity — a label the same in every deployment
  (a metrics type's `disk` / `memory` aspects) — and leave **deployment-specific**
  identity (this host's location, this box's role) to the deployment's `nodes.yaml`.
  They are **ignored on the root** (like `name`) and **fill an empty node field only**,
  so a `nodes.yaml` declaration always wins and the label freezes at its first fill;
  text that changes with each run belongs in `reason`, not here.

---

## 4. Registration & startup wiring

The loader resolves each YAML `type:` through the **`CHECK_TYPES`** registry
(`little_sister.checks`), and the engine loads checks **at process start**
(`app.py` calls `_start_engine_once()` → `create_engine()` → `load_checks()` at
import). So a type must be in `CHECK_TYPES` **before `little_sister.app` is imported**.
`@register(...)` populates the registry as a side effect of importing the module that
defines the class — the whole game is making that import happen first.

**In a deployment** — add a thin WSGI wrapper that imports its checks, then the app:

```python
# wsgi.py — register the deployment's check types, then expose the app.
# The order is load-bearing and deliberately not sorted: importing
# little_sister.app builds the engine and loads the check configs at import time,
# so everything this deployment registers must already be in place. An import
# sorter puts `little_sister` first and silently inverts exactly that.
# isort: off
import my_deployment.checks          # noqa: F401  registration side effects
from little_sister.app import app    # builds the engine, loads the checks
# isort: on

__all__ = ["app"]
```

and point the runner at it (gunicorn → `wsgi:app` instead of
`little_sister.app:app`). The check package must be importable — run from the
directory where it resolves on `sys.path`. The same wrapper (and the same import
slot) also registers **secret resolvers** (§6), **template slot fillers**
([ADR-0034](adr/0034-template-slots-for-dependent-packages.md)) and **configuration
aspects** ([ADR-0035](adr/0035-registering-a-config-aspect.md)).

The `# isort: off` fence is not decoration, and `# noqa: E402` is not superstition:
the app import must follow the registrations, so it cannot sit with the others at
the top of the file. Do not carry the `noqa` into a file where nothing sits between
the two imports — with this repo's ruff selection an unused one is itself an error.

**In an installed package** — identical, and it is *still a wrapper*: the deployment
writes `import little_sister_github` in the same slot, and the package's
`__init__.py` does the importing that registers. What a package changes is who
maintains the type and on what version line, not how it arrives. Discovery without
an import — an entry point that would let a deployment install a type and write no
line at all — does not exist yet; when it does, that import is what it replaces.

**In the library** — the built-ins do the same thing via a side-effect import in
`little_sister/checks/__init__.py` (it imports `http`, `file`, `command`, `ssh`).

`CHECK_TYPES`, `little_sister.app:app`, `little_sister.secrets`, the
`LITTLE_SISTER_*` environment variables and every name in §2 above are part of
little-sister's **published version contract** ([`architecture.md`](architecture.md)
§11), so a tag won't move them under a deployment. Logging is on that contract as a
*behavior* rather than a name: call `logging.getLogger(__name__)` and your records
reach whatever the application configured — including your own setup, if you install
it before importing `little_sister.app`.

---

## 5. Configuration (YAML → your check)

- One `config/checks/*.yaml` = one check; `type:` selects your class, the rest are
  your fields plus the common ones. Configs are read **once at startup** across the
  path-list union of `checks/` directories under `LITTLE_SISTER_CONFIG_DIR` (default
  `config`); sub-directories are ignored, and nothing is skipped by name because
  `config/checks/` holds checks and nothing else
  ([ADR-0015](adr/0015-check-discovery-union.md),
  [ADR-0031](adr/0031-deployment-config-directory.md)). A restart re-reads them.
- **Relative paths resolve against the config file's own directory** (`base_dir` in
  `_extra_from_config`) — e.g. a bundled script sits next to its YAML.
- **Node metadata** (`title`, `about`) resolves **per field** by precedence:
  `nodes.yaml` keyed by node path **>** the check **>** empty
  ([ADR-0012](adr/0012-node-metadata.md) / [ADR-0017](adr/0017-node-title.md)). For a
  check's **root** node the check source is an inline `about:` / `title:` in its YAML;
  for the **subnodes a branch check emits** it is the child `CheckResult`'s
  `about` / `title`, which fill an empty field only
  ([ADR-0025](adr/0025-check-provided-subnode-metadata.md); see §3). A container node no
  single check owns can still be labeled via `nodes.yaml`.
- **Where a branch check gets its subnode labels.** The `CheckResult.about` / `title` a
  branch check emits can be **hardcoded** (a per-aspect default in code, like
  `host-metrics`' built-in `about`s) or read from the check's **own config** — a
  `subnodes:` block, `name → {title, about}`, sitting beside the root's inline metadata.
  `little_sister.checks` provides the reader: `parse_subnodes(config)` →
  `{name: {title, about}}`, and `expand_tokens(text, {…})` to fill `{token}` placeholders
  (a plain replace, never `str.format`, so backticks / braces in the Markdown survive).
  `resolve_text(configured, default, tokens)` layers a check that has both: the config
  value when present, the default otherwise, and config text containing `{default}`
  **extends** the default rather than replacing it — before, after or around it. Ship
  defaults in code for anything true of the check *type*: a deployment can still retune or
  annotate one aspect without touching code or `nodes.yaml`, and a type that runs several
  times in one deployment (one check per team) then carries its prose once instead of once
  per config file.
- **Ownership** — two checks may not own overlapping nodes; the loader rejects the
  whole load with a named conflict. A branch check overrides `owned_nodes()` to own
  its child subtrees (not the shared container) so peers can coexist (ADR-0015).

---

## 6. Secrets & credentials

A check names its credentials in a **`secrets:` block**, each value a **secret
reference** ([ADR-0023](adr/0023-secret-references.md)):

```yaml
secrets:
  token: env://GITHUB_TOKEN        # or aws-sm://myteam/github-token
```

**`env://NAME`** reads that environment variable — fed by the git-ignored `.env`,
which little-sister loads into `os.environ` at import with `setdefault`, so a real
environment variable overrides the file
([ADR-0003](adr/0003-config-and-secrets-via-env-file.md)). Any other
**`scheme://address`** reference (`aws-sm://team/github-token`) goes through the
resolver the application registered for that scheme
(`little_sister.secrets.register_resolver`) — registered in the same
import-before-app slot as the check types (§4); the library ships no store client.

- **Resolve at construction, never in `run()`.** Call
  `self.resolve_secret(reference)` from the constructor and keep the value — cloud
  stores bill per read, and rotation is a restart, like any other config change.
- **The failure split is handled for you.** A malformed reference (unknown scheme)
  raises `CheckError`, so the load fails loudly like any config typo. A well-formed
  reference that cannot be resolved (store unreachable, secret absent) is recorded on
  the check, and the engine **pins** it: the node shows `ERROR` with
  *"secret unresolvable: …"*, `run()` is never called, and there is no retry until
  restart. Don't wrap `resolve_secret` in your own try/except — the return value and
  the pinning already do the right thing.
- **Parse the block with `parse_secret_refs(config, "token", …)`** in
  `_extra_from_config`, and resolve what it returns in the constructor. Every name
  you list is required — deliberately: a default reference baked into the check type
  ties every instance of it to the same credential, which is what stops a deployment
  running the type twice, once per team, with a token each. A deployment then moves
  that one secret to a store by editing one YAML line — no code change.
- Secrets **never** reach the repo, `config_summary()` or a reason. `.env` stays
  git-ignored; only the *address* of a secret may appear in YAML.

---

## 7. External I/O: timeouts, failure, rate limits

- **Bound every call** by `self.timeout_seconds`. The engine relies on checks to time
  themselves out (the built-ins pass `timeout=self.timeout_seconds` to `urllib` /
  `subprocess`); custom checks must too.
- **Never raise out of `run()` for an expected failure.** Catch transport / API errors
  and return `CheckResult(StatusCode.ERROR, [plain(str(err))])` — see `http.py` for the
  pattern.
- **Respect the upstream's rate limits.** Batch where you can, keep `frequency` sane,
  and prefer few calls per run. (API-specific tactics belong in the check's own doc.)
- **Keep dependencies light.** The built-ins use stdlib `urllib`; matching that keeps
  a plugin thin and its extraction clean — and that is measured, not hoped for: both
  check types extracted so far reached their provider over stdlib `urllib` and ship
  with little-sister as their only dependency.

---

## 8. Testing & the gate

- Match the repo's discipline: keep **`ruff` + `mypy` + `pytest`** green.
- **Unit-test `run()` against recorded fixtures / a fake transport — no live network
  in tests.** Assert the returned `code`, the `reason`, and (for a branch) the child
  tree shape and names. For a check with a credential, substitute a fake resolver /
  environment and cover both the resolved and the pinned path (see
  `tests/test_secrets.py` for the patterns).
- **Smoke-test config loading** without starting the server:

  ```bash
  uv run python -c "import my_deployment.checks; \
      from little_sister.checks import load_checks; \
      print(len(load_checks()), 'checks OK')"
  ```

  (Import the module first so the types are registered; for the built-ins alone the
  import line is unnecessary.)

---

## 9. Extraction to a plugin

Build a deployment check type so it lifts out cleanly: a **self-contained module**
(class + tests + an example YAML + a short doc), **minimal dependencies**, and
credentials behind **secret references** (§6). This section is the *design*
advice — what makes a type liftable. The **procedure** for actually lifting one, when
it turns out to have a second user, is
[`plugin-repository.md`](plugin-repository.md): the repository template, the cutover
order that stays green at every step, the private-strings sweep an extraction out of
a private deployment needs, and how a deployment then consumes the result.

The table below is no longer a prediction. Three extractions have run against it and
every row that applied held — what could not move turned out to be configuration
already, which is the same line arriving from the other direction. Only the two check
types exercised the whole table; the surface extension has no credential and no
subnode prose, so it tested the knob row alone.

The line to build against is **type vs deployment**: what is true of the check *type*
travels inside the package, what is true of one installation stays in that
deployment's YAML — and being explicit there is a feature, not duplication, because a
plugin user should be able to read their own choices without knowing the type's
defaults.

| Travels with the plugin | Stays in the deployment's config |
|-------------------------|----------------------------------|
| subnode `title` / `about` prose, its `{token}` grammar, severity legends (§3) | which org / team / host, and every threshold, ignore list and tuning knob |
| the default for each optional knob | the value this installation actually chose |
| the code that reads a credential | the **reference** naming where that credential lives (§6) |

Two consequences are worth designing for before the plugin exists. A credential
reference is **required, never defaulted**: a type that bakes in `GITHUB_TOKEN` ties
every instance to one secret, so a deployment cannot run it twice with different
credentials — one check per team. And the type's prose stops being a file the
deployment can edit, so a label must be **extendable**, not only replaceable: that is
what `{default}` in a `subnodes:` value buys (§3), letting a deployment append its own
note to shipped text and still inherit the next version of it.
