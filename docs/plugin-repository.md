# Giving a check type a repository of its own

A check type usually starts inside the deployment that needed it: a module beside
that deployment's config, registered by its `wsgi.py`
([`implementing-checks.md`](implementing-checks.md) §4). That is the right place to
start and, for many types, the right place to stay. This document is the procedure
for the ones that outgrow it — how to lift a check type (or a surface extension) out
of a deployment and give it an installable repository of its own, without a rewrite
and without a moment where anything is red.

It starts where [`implementing-checks.md`](implementing-checks.md) §9 stops. That
section holds the *design* advice — build a type so it lifts out cleanly, and the
**type vs deployment** line that decides what may travel. This one holds the
*procedure*. Read §9 first if you have not; everything here assumes its table.

---

## 1. Does this type deserve a repository?

One question decides it: **would it ever have a second user?**

A type that reads a *product* — GitHub, Jira, a cloud-security service, a monitoring
API — describes something outside your organization, so a second deployment could
install it and know nothing but its README. That type has earned a repository.

A type that reads *your* system — a company-specific job queue, a database whose
schema only you have, a script only your hosts run — has exactly one user forever. A
repository for it is a version boundary, a release pipeline and a second checkout,
bought with nothing. Leave it in the deployment; §9's design advice keeps it liftable
if the answer ever changes.

Two rules follow from the question, not from taste:

- **One check type per repository.** A deployment installs the checks it wants and no
  more; each type versions on its own line; and a repository carrying two types never
  has to make its seams honest, because the second type can always reach into the
  first. Two types that genuinely share code share it the way any two packages do —
  through a dependency, or by both being simple enough not to.
- **The deployment keeps its configuration.** Every extraction moves *code*. What the
  check watches, with which credentials, at which thresholds, stays in the
  deployment's YAML. If something in the module cannot move because it names your
  hosts, that is not a blocker — it is the line telling you where it is.

---

## 2. The names — chosen once, for both worlds

One word, `<x>`, in three spellings:

| | | |
|---|---|---|
| **distribution** | `little-sister-<x>` | what a `pyproject.toml` depends on, what PyPI would list |
| **import package** | `little_sister_<x>` | what `wsgi.py` imports |
| **check type** | `<x>` | what a check YAML puts after `type:` |

Pick them together, before the first tag, because **all three are hard to change
afterwards**: a distribution rename is a new project for every consumer, an import
rename edits every deployment's `wsgi.py`, and a `type:` rename edits every check
config — and silently orphans nothing, which is worse, because the checks simply stop
loading.

**The convention already spans git and PyPI, and that is deliberate.** A
`[tool.uv.sources]` entry is a *source redirect* — it says where to fetch a
distribution, not which distribution it is. The dependency name and every `import`
statement are identical whether the wheel was built from a git tag or downloaded from
an index, so publishing later means **deleting three lines** from the consumers'
configuration and changing no code, no config and no import. That only holds if the
git era already uses the name the published era will — which is the whole reason to
settle this now rather than at publication.

Two consequences worth knowing:

- **The hyphen and the underscore are the same name.** Index names normalize
  (`little-sister-<x>`, `little_sister_<x>` and `Little.Sister.<X>` are one project),
  so the pair above is a spelling difference rather than two names to keep in step.
  Because the mapping is mechanical, `/system` can derive one from the other and show
  which distribution answers for a registered type.
- **Do not reach for `little_sister.<x>` or `little_sister.plugins.<x>`.**
  `little_sister` is an ordinary package with its own `__init__.py`, so a separate
  distribution cannot legally add a submodule to it; making it a namespace package to
  allow that would break the library's own imports. The flat `little_sister_<x>` is
  the form that works today, works after PyPI, and never has two distributions
  writing into one directory.

**Name the package after the type it registers.** `little-sister-github` registers
`github`. Type names are bare and claimed once (§8), so when two packages do collide
the refusal names two projects whose names say what they claim — and when discovery
by entry point arrives, the entry point's key is already obvious.

---

## 3. The repository template

```
little-sister-<x>/                     distribution: little-sister-<x>
├── src/
│   └── little_sister_<x>/             import package: little_sister_<x>
│       ├── __init__.py                declares the API epoch, imports for registration
│       ├── <x>.py                     the check type (or the extension)
│       ├── py.typed                   empty; without it your types are invisible
│       └── templates/  static/        only a surface extension has these (§7)
├── tests/
│   └── test_<x>.py
├── examples/
│   └── <x>.yaml                       a neutral, annotated example config
├── docs/                              the type's own docs and ADRs
├── hooks/pre-commit                   the gate, as in every repo in the family
├── release/                            wrappers + the private-strings denylist
├── README.md   CHANGELOG.md   LICENSE
└── pyproject.toml
```

**`pyproject.toml`.** Copy a deployment's and change one thing — a plugin is a
**built package**:

```toml
[project]
name = "little-sister-<x>"
requires-python = ">=3.14"
dependencies = ["little-sister>=<the release that promised your surface>"]

[tool.uv]
package = true                      # the one line that differs from a deployment

[build-system]
requires = ["uv_build>=0.11.14,<0.12.0"]
build-backend = "uv_build"

# For local development against an unreleased library. Commented out in what you
# commit: a consumer must resolve the dependency from the tag, not from your disk.
#[tool.uv.sources]
#little-sister = { git = "file:///path/to/little-sister" }

[dependency-groups]
dev = ["mypy>=2.1.0", "pytest>=9.0.3", "pytest-cov>=7.1.0", "ruff>=0.15.13",
       "types-PyYAML"]
```

**A `src/` layout, not a flat one.** `uv_build` looks for the import package under
`src/` by default, so a package at the repository root fails to build with
`Expected a Python module at: src/little_sister_<x>/...` — before any of your code
runs. (`[tool.uv.build-backend] module-root = ""` is the alternative; `src/` is what
the library itself uses, and one layout across the family is worth more than the
saved directory.)

`little-sister >= x` is a **floor, and never a pin.** A deployment pins; two plugins
that each pinned an exact version could not be installed together at all. The floor
says "I need at least what this release promised", which is a statement about the
check-authoring surface ([`architecture.md`](architecture.md) §11) rather than about
a release.

Copy the `[tool.ruff]` selection and the `[tool.mypy]` strictness from the library as
they stand, so every repository in the family runs one gate and a contributor moving
between them meets one set of rules. The `[tool.pytest.ini_options]` block is the one
to **adapt rather than copy**: its `addopts` names a coverage target, and
`--cov=little_sister` would measure the library from your repository — a number about
somebody else's code. Point it at your own package:

```toml
[tool.pytest.ini_options]
addopts = "--cov=little_sister_<x> --cov-report=term-missing"
```

**`py.typed` is an empty file and not optional.** It is the marker that says this
package's annotations are meant to be read (PEP 561). Without it, a deployment that
runs `mypy` over its own wiring gets *"module is installed, but missing library stubs
or py.typed marker"* on the one import your package exists to be — and it is easy to
miss from inside the repository, because your own gate only ever type-checks `src/`
and never *imports* you the way a consumer does. It must sit **inside** the import
package, beside `__init__.py`, or the wheel will not carry it.

**`src/little_sister_<x>/__init__.py`** is four lines, and two of them do the work:

```python
"""little-sister check type: <x>."""
from little_sister.checks import require_api

require_api(1)                       # the check API epoch this package was built for

from little_sister_<x> import <x>    # noqa: E402,F401  registration side effect
```

The import is what makes a deployment's wiring one line — `import little_sister_<x>`
in its `wsgi.py`, before `little_sister.app`. The `require_api` call is what makes a
mismatch a sentence instead of an `ImportError` from inside your package: it names
both epochs and refuses at startup (see §8).

**A local `[tool.uv.sources]` does not stay local.** uv reads the sources table of
a dependency it resolves from a path or a git checkout, not just the workspace
root's — so a plugin that commits `little-sister = { path = "../little-sister" }`
imposes that path on **every deployment that installs it**, and a deployment whose
own checkout sits somewhere else fails to sync with an error naming a repository
it never configured. That is the real reason the line is commented out in what you
commit, and it is stronger than "it exists on one machine": the line is not
private to your repository at all.

**`examples/<x>.yaml`** is not the deployment's config with the names changed. It is
the *shape*: every key the type accepts, placeholder values, and a comment per knob
saying what it decides. A credential is a **reference** (`env://SOME_TOKEN`), never a
value — see [`implementing-checks.md`](implementing-checks.md) §6.

**`README.md`** states the two-line contract every repository in the family states:
**which little-sister floor it needs**, and **which `type:` names it registers**. A
second user should be able to install and configure the type from the README and the
example alone.

---

## 4. What travels

[`implementing-checks.md`](implementing-checks.md) §9's table is the rule. Beyond the
code it covers, three things travel that are easy to leave behind:

- **The tests.** They move with the module, unchanged if possible. A test that only
  passes against your deployment's fixtures was testing your deployment.
- **The type's documentation**, including any ADR that records a decision about *this
  type* — how it derives its slugs, why an aspect is shaped as it is. A decision
  about the deployment (which teams it watches, what it grades as an error) stays.
- **The subnode prose.** A branch check's per-aspect `title` / `about` is
  type-inherent ([`implementing-checks.md`](implementing-checks.md) §3), so it
  travels *in the code*, with its `{token}` grammar. Deployment-specific wording
  belongs in the deployment's `subnodes:` block, which can extend the shipped text
  with `{default}` rather than replacing it.

And one thing that must **not** travel: anything naming your infrastructure. See §6.

---

## 5. The cutover, in order

The order exists so that every step ends green and nothing is ever half-moved. Do not
compress it — in particular, do not delete the deployment's module before its
replacement is resolving from a tag.

1. **Cut the repository** from §3's template. Empty of your code, its gate green.
2. **Move the module and its tests** in, unchanged. Adjust imports only: the check's
   own package name, and the library's names to their promised spellings
   ([`architecture.md`](architecture.md) §11).
3. **Green on its own gate** — `ruff`, `mypy --strict`, `pytest`. Anything that fails
   here is something the module was borrowing from the deployment.
4. **Tag `v0.1.0`** and release it through the pipeline
   ([ADR-0022](adr/0022-generated-release-branch.md)), private-strings scan included.
5. **The deployment adds the dependency** — `little-sister-<x>` in its
   `dependencies`, with a `[tool.uv.sources]` entry naming the tag — and changes its
   import from the local module to the package.
6. **Delete the local module and its test.** This is one commit with step 5, not a
   later cleanup: two copies of a check type in one process, one of them
   unregistered, is a debugging trap.
7. **Both sides green**, and both configs still loading (the smoke test in
   [`implementing-checks.md`](implementing-checks.md) §8).

**Then accept it behaviorally, because a green gate does not prove this move.** Start
the deployment and compare against what it served before:

- the **same tree** — the same nodes, in the same places;
- the same **aspects** under the check's node;
- the same **entry slugs**, which is the one nobody notices. A slug is a stored key:
  maintenance pins live against `(path, slug)`, so a slug that shifted in the move
  silently re-points every pin, and nothing about the result looks wrong. Compare the
  actual strings — from `?reason=` values, or the maintenance file — not the rendered
  lines;
- the **live pins** still attached to what they were attached to.

If a slug did shift, treat it as a defect in the move, not as a new baseline.

---

## 6. The private-strings sweep

An extraction takes code *out of a private deployment* and publishes it. That makes
this the moment the sweep matters most — more than in any other release, because the
material has never been public before.

What hides in a lifted module: organization and team names, hostnames and regional
endpoints, account and field identifiers from a tracker's API, internal project
slugs, a colleague's name in a docstring, a real URL in a test fixture.

Two passes:

- **Mechanical.** The release pipeline scans the whole tree against a denylist and
  fails on a hit. Give the new repository the same denylist the deployment's family
  uses; it is cheap and it is the only pass that runs every time.
- **By eye, once.** Read the moved module, its tests, its example and its docs as
  somebody outside your organization. A denylist only catches what somebody thought
  to add to it, and the first extraction is exactly when a string nobody listed gets
  published.

Everything the sweep finds belongs in the deployment's YAML anyway. That is the same
type-vs-deployment line as §4, arriving from the other direction.

---

## 7. A surface extension brings four more seams

A check type is the easy case: one registration, no templates, no package data, no
configuration of its own. An extension that adds to little-sister's *surfaces* — a
chip on a reason line, an action on a node — touches three things a check never does.

- **Templates and assets are package data.** With `uv_build` everything under the
  import package ships, so `templates/` and `static/` inside `little_sister_<x>/`
  need no declaration — the library's own templates ship exactly that way. What a
  source checkout hides is everything *outside* it: a template one directory up, a
  file the tests reach by relative path, anything found today because the repository
  happens to be the working directory. So verify the way that cannot lie — install
  the **built wheel** into a clean environment and render the page — rather than
  running from the checkout. Static assets are served from `/ext/<package>/`
  ([ADR-0037](adr/0037-extension-static-assets.md)), which is why `'self'` already
  covers them in the policy.
- **A configuration aspect is now owned by a package.** `register_aspect("<x>")`
  ([ADR-0035](adr/0035-registering-a-config-aspect.md)) claims a name in every
  deployment that installs you — `config/<x>.yaml` is yours from then on. Name it
  after the package, not after the concept: `jira`, not `tickets`.
- **What the extension's code reaches** may need a policy contribution.
  `script-src` names origins rather than files, so your scripts are covered — but a
  host your code *calls* is not. Declare it with `csp.allow(...)` from the same
  import-before-app slot, and prefer `csp.origin_of("<aspect>.<field>")` where the
  host is the deployment's own
  ([ADR-0048](adr/0048-an-assembled-content-security-policy.md)).

- **What the extension hands the browser has a size limit, and it is not the one you
  are thinking of.** A display budget bounds what a page shows; a *transport* budget
  bounds what a link can carry. Anything an extension folds into a URL travels in a
  query string, where percent-encoding roughly triples a stack trace — and past the
  server's request-line limit the operator gets a 414 instead of the page, from a
  control that still looks like it works. This is the seam a check type has no
  equivalent of, and the one that is invisible in the code: it was found by reading a
  rendered chip. If your extension composes a URL out of check output, bound the whole
  URL, cut only the parts that can be recovered elsewhere, and make what is cut say so.

An extension being extracted for the first time is also, usually, the moment it gets
its **first tests**: the URL assembly and the placement policy are pure functions and
cheap to cover, and they are the parts that break quietly. Two of them are worth
writing whatever else you skip — that the templates are read the way an *installed*
package is read, and that the extension's own placement rules hold, because both are
things a source checkout and a hand-run browser will agree about right up until a
deployment disagrees.

---

## 8. How a deployment consumes it

```toml
# pyproject.toml
[project]
dependencies = ["little-sister", "little-sister-<x>"]

# Only while these come from git. On PyPI, delete this table — nothing else changes.
[tool.uv.sources]
little-sister = { git = "https://github.com/…/little-sister.git", tag = "v0.2.5" }
little-sister-<x> = { git = "https://github.com/…/little-sister-<x>.git", tag = "v0.1.0" }
```

```python
# wsgi.py — registrations first, the app last. The order is load-bearing:
# importing little_sister.app builds the engine and loads the configs.
# isort: off
import little_sister_<x>            # noqa: F401  registers its type
from little_sister.app import app
# isort: on

__all__ = ["app"]                   # without it, lint calls the app import unused
```

The `isort: off` fence is not decoration: an import sorter puts `little_sister`
before `little_sister_<x>` and silently inverts the one ordering this file
exists to state. Do **not** reach for `# noqa: E402` on the app import unless
something actually sits between the two — with the family's ruff selection an
unused `noqa` is itself an error (`RUF100`), so the snippet that carries one
"just in case" fails the gate it was copied to pass.

Three refusals stand between a mis-wired install and a monitoring system that looks
healthy while telling you nothing:

- **The install-time floor.** The resolver refuses a little-sister older than the
  plugin's floor. This is the first line and it costs nothing.
- **The check API epoch.** `require_api(n)` refuses at startup when the library has
  moved past the surface the plugin was built for — the upgrade the floor cannot see,
  because a floor has no ceiling ([ADR-0051](adr/0051-what-startup-refuses.md)).
- **The type-name collision.** Type names are bare (`type: github`), so two packages
  can claim one. The second registration refuses at startup and names both classes,
  rather than letting import order decide whose code answers for whose configuration.

`/system` lists every registered check type with the package and version that answers
for it, which is where you look when a check behaves like a version you did not
install. It is also how you confirm a fresh install registered *before* you configure
anything with it — a type no check uses yet sits under the page's *unused by this
configuration* fold, which is a different answer from not being there at all.

A **surface** extension registers no check type, so it is not on that roster at all.
It is on the page's package list instead, which carries one row per installed package
— distribution, version, the file it was loaded from, and every slot, asset and
aspect it registered. Look there to answer "which build of my chip package is this
instance running", and to see at a glance whether all of a package's registrations
took or only some.

---

## 9. Releasing it

However you already release, with one addition and one habit.

The addition is **§6's sweep, before the first tag** — this code is leaving a
private deployment, and that is the release where a hostname or an internal id gets
published for the first time.

The habit is what your CHANGELOG is for: the deployments that install you, not a
work log. "Added `ignore_archived:`" is a release note; "refactored the client" is
not. And treat **a new `type:` name, a changed slug shape or a removed config key as
a breaking change** — every deployment that has maintenance pins and dashboards
built on those is affected, even though nothing in the code says so. Say it in the
notes, at the top.

