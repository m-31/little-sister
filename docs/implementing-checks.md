# Little Sister — Implementing a check type

How to implement a **new check _type_** — a Python class the engine can schedule.
This is the developer-side companion to [`checks/README.md`](../checks/README.md),
which covers the other half: how to _author_ a check (write the YAML for a type
that already exists).

Everything here applies both to the **built-in** types in this repo and to the
types a **deployment** adds through the public `CHECK_TYPES` seam
([`architecture.md`](architecture.md) §11) — that a deployment can carry its own
check types is the whole idea. Only §4 (registration timing) differs between the
two. Later, deployment types lift out into installable plugin packages "as an
evolution of this, not a rewrite" — in the packaging-and-PyPI phase of the roadmap.

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
  That's [`checks/README.md`](../checks/README.md).
- **Implementing** a check type — writing the Python class behind a `type:`. That's
  this document.

---

## 2. The `Check` contract

Everything lives in `little_sister.checks.base`. A check type is a subclass of `Check`
decorated with `@register("<type>")`:

```python
from __future__ import annotations

from pathlib import Path
from typing import Any

from little_sister.checks.base import (
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
    code:        StatusCode,               # required
    reason:      list[str] = [],           # required when not OK; rendered as Markdown
    name:        str = "",                 # a child's id under its parent; empty on the root
    description: str = "",                 # node metadata
    children:    tuple[CheckResult, ...] = (),
    config:      str = "",                 # per-child config markdown (branch checks)
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
  `MAINTENANCE` / `UNDEFINED` are the tree's concern, not a check's. `coerce_code(...)`
  turns a config string (e.g. `stale_code: WARN`) into a `StatusCode`.
- **Reasons are Markdown** — fold untrusted text in safely: `plain(text)` escapes an
  inline value (a path, an error, an API message); `code(text)` fences multi-line /
  log output as a verbatim block ([ADR-0018](adr/0018-markdown-rendering.md)). Never
  interpolate raw external bytes straight into a reason.

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
import my_deployment.checks          # noqa: F401  registration side effects
from little_sister.app import app    # noqa: E402  builds engine, loads checks

__all__ = ["app"]
```

and point the runner at it (gunicorn → `wsgi:app` instead of
`little_sister.app:app`). The check package must be importable — run from the
directory where it resolves on `sys.path`. The same wrapper (and the same import
slot) also registers **secret resolvers** (§6).

**In the library** — the built-ins do the same thing via a side-effect import in
`little_sister/checks/__init__.py` (it imports `http`, `file`, `command`, `ssh`).
That's the graduation path for a deployment check at the packaging-and-PyPI phase:
same class, moved into
a package whose import registers it (eventually via entry points) — no wrapper
needed.

`CHECK_TYPES`, `little_sister.app:app`, `little_sister.secrets` and the
`LITTLE_SISTER_*` environment variables are part of little-sister's **published
version contract** ([`architecture.md`](architecture.md) §11), so a tag won't move
them under a deployment.

---

## 5. Configuration (YAML → your check)

- One `checks/*.yaml` = one check; `type:` selects your class, the rest are your
  fields plus the common ones. Configs are read **once at startup** across the
  path-list union in `LITTLE_SISTER_CHECKS_DIR` (default `checks`); sub-directories
  are ignored and `nodes.yaml` is skipped
  ([ADR-0015](adr/0015-check-discovery-union.md)). A restart re-reads them.
- **Relative paths resolve against the config file's own directory** (`base_dir` in
  `_extra_from_config`) — e.g. a bundled script sits next to its YAML.
- **Node metadata** (`title`, `about`) may come inline on the check or from a
  `nodes.yaml` keyed by node path; `nodes.yaml` wins
  ([ADR-0012](adr/0012-node-metadata.md) / [ADR-0017](adr/0017-node-title.md)). A
  container node no single check owns can still be labelled via `nodes.yaml`.
- **Ownership** — two checks may not own overlapping nodes; the loader rejects the
  whole load with a named conflict. A branch check overrides `owned_nodes()` to own
  its child subtrees (not the shared container) so peers can coexist (ADR-0015).

---

## 6. Secrets & credentials

A check credential in YAML is a **secret reference**
([ADR-0023](adr/0023-secret-references.md)). A **bare name** (`GITHUB_TOKEN`) reads
that environment variable — fed by the git-ignored `.env`, which little-sister loads
into `os.environ` at import with `setdefault`, so a real environment variable
overrides the file ([ADR-0003](adr/0003-config-and-secrets-via-env-file.md)). A
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
- **Make the reference a config field** with a sensible bare-name default
  (`token:` defaulting to `GITHUB_TOKEN`), so a deployment moves that one secret to a
  store by editing one YAML line — no code change.
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
  an eventual plugin thin and its extraction clean.

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

Build a deployment check type so it lifts out cleanly later: a **self-contained
module** (class + tests + an example YAML + a short doc), **minimal dependencies**,
and credentials behind **secret references** (§6). Then packaging it as an
installable `little-sister-<x>` with an entry point is "an evolution of this, not a
rewrite" ([`architecture.md`](architecture.md) §11). Until then a deployment's checks
are an integral part of its repo.
