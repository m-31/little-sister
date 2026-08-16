# ADR-0049 — The check-authoring surface is contract, and the gate holds it

- **Status:** Accepted
- **Date:** 2026-08-08 (decided while preparing the first check types to move into
  repositories of their own)
- **Related:** [ADR-0022](0022-generated-release-branch.md) (the tag a dependent
  pins — the thing a surface makes meaningful),
  [ADR-0034](0034-template-slots-for-dependent-packages.md) (the slot contract,
  whose add-is-compatible rule this repeats),
  [ADR-0026](0026-reading-values-from-decoded-bags.md) (the typed readers now
  promised), [ADR-0036](0036-addressable-reasons.md) /
  [ADR-0042](0042-entries-carry-their-own-code.md) (the entry vocabulary now
  promised), [ADR-0043](0043-coverage-backstop.md) (a rule the gate measures rather
  than a rule we remember)
- **Register:** [`../decisions.md`](../decisions.md)

> **Update (2026-08-10):** the surface promises **names**, and this note adds what it
> does *not* promise, because the difference drew blood. The **common config fields
> every check shares grow** — `order` joined them in
> [ADR-0055](0055-sibling-order.md) — and each one becomes a keyword argument
> `Check.from_config` passes to the constructor. A check type that spells those
> keywords out instead of taking `**kwargs` therefore stops binding the day a field
> is added, although every promised *name* still imports. **So the obligation on a
> check type is: accept `**kwargs` and hand them to `super().__init__()`.** Adding a
> common field stays a compatible change under this record's add-is-compatible rule,
> and a constructor that refuses one is now reported as a `CheckError` naming the
> file, the type and the keyword, instead of a bare `TypeError` from inside the
> loader. The epoch (`API_VERSION`) does not move: nothing was removed or renamed.

> **Update (2026-08-16):** decision 4's guard stands; what it guards had a **level of
> its own** to choose, and the choice was wrong. The default was `DEBUG` — which
> collects no record little-sister writes, because nothing in it logs below `INFO`,
> and every record written by everything it is installed beside. That is also what the
> `httpx` and `markdown_it` caps beside it are: dependencies noticed one at a time,
> each after somebody read a log. A deployment carrying an AWS check type made the
> shape plain by being two thirds SDK request detail. **So the default is now `INFO`,
> and `LOG_LEVEL` names it** — inside the guard, like the level it replaces, so a
> stray variable in a deployment's environment cannot overrule the level that
> deployment chose in code. An unrecognized name falls back to `INFO` and says so in
> the log it just opened, because a typo in an environment is not a reason to refuse
> to log. Nothing about the promise moves: logging is still a behavior rather than a
> name, `little_sister.logger` is still not importable by a plugin, and a chatty
> dependency is still quieted by capping **its own** logger — which adds no handler
> to root, and so leaves this default running rather than replacing it.

## Context

`architecture.md` §11 has always promised the *registry*: a deployment adds its own
check types by importing them before `little_sister.app:app`, and `CHECK_TYPES` is
stable across a tag. What it never promised is the part a check type actually
consists of. The three types in the private deployment repository import, between
them: `Check`, `CheckError`, `CheckResult`, `register`, `coerce_code`,
`config_markdown`, `parse_secret_refs`, `plain`, the metadata helpers
`parse_subnodes` / `resolve_text` / `expand_tokens`, `load_checks`, the reason
vocabulary `Entry` / `derived_slug` / `MAX_SLUG_LENGTH` / `normalize` /
`ReasonError`, `StatusCode`, the `values` readers, and the shared `logger` object.
Every one of those is internal by the letter of the contract.

That was harmless while the code lived in a repository we bump in a single commit:
a rename here broke a check there, in the same change, loudly. It stops being
harmless the moment a check type lives behind **its own tag** — which is exactly
what the plugin repositories do. Then the deployment upgrades little-sister on
Tuesday and a plugin pinned to last month's floor keeps importing a name that moved,
and the failure surfaces as an `ImportError` at process start in somebody else's
repository.

A version contract that covers the registry but not the base class is not a version
contract; it is a promise about the one name nobody's code writes against.

## Decision

1. **§11 gains a check-authoring surface, name by name**, and the doc is the source
   of truth for it. It lists what a check type written outside this repository may
   import: the `little_sister.checks` facade, the slug and entry vocabulary in
   `reasons`, `StatusCode` and `join_path` in `status`, and the `values` readers.
   What each name
   *does* stays documented where it is designed, and that documented behavior travels
   with the name — a promise about `CheckResult` that covered its existence but not
   its field meanings would be worth nothing.

2. **The import point is the package `little_sister.checks`, never a module beneath
   it.** `checks.base` is where most of these names live today, which is a fact about
   the current layout and not something a dependent should have to know. The facade
   already existed for `Entry` ("so a check type imports its whole vocabulary from
   one place"); this makes it the rule and adds the names that were missing from it
   (`register`, `coerce_code`, `config_markdown`, `parse_secret_refs`, and the
   subnode-metadata helpers `parse_subnodes` / `resolve_text` / `expand_tokens`). The
   library's own built-in checks keep importing `.base` directly — they are imported
   *by* the facade, so it does not exist yet when they run. A public face the
   library's own modules cannot use is normal for a facade, and worth saying out loud
   once.

   Two consequences of taking that seriously. The subnode-metadata helpers are
   re-exported here rather than promised at `checks.metadata`: promising a module
   path we had just declared *not* to be the promise would have left a plugin no
   legal way to import the three names `implementing-checks.md` tells every branch
   check to use. And `join_path` **is** promised, from `little_sister.status`, for
   the same kind of reason — `owned_nodes` is a documented override, every branch
   check in this repository builds its child paths with it, and a plugin left to
   assemble paths by hand would re-derive [ADR-0016](0016-node-addressing.md)'s
   normalization by guesswork.

3. **The gate holds the surface, in both directions.** `tests/test_public_surface.py`
   parses the block out of §11, imports every name in it (doc → code) and, for every
   module that declares `__all__`, requires the two lists to be **identical** (code →
   doc). `values` and `checks.metadata` gain an `__all__` so that second direction
   reaches them: everything public in those two is contract — `metadata` through the
   facade — so the declaration costs nothing and buys the check. `reasons` and
   `status` carry public internals (`derive_code`, `ReasonInput`, `effective_code`)
   and stay one-way. The point of the second direction is not symmetry — it is that a
   name joining the surface should be a decision somebody wrote down, not a side
   effect of an export.

   What the gate measures here is **drift**: a name renamed or dropped by a refactor
   that looked local, or exported without being promised. A rename that edits the
   code and the doc in one commit slips past *this* check by construction — which is
   why [ADR-0051](0051-what-startup-refuses.md) then pins the surface to a snapshot
   per **check API epoch**, the one thing a same-commit edit cannot satisfy without
   moving the epoch.

4. **Logging is promised as a behavior, not as a name.** `little_sister.logger` and
   its `logger` object are *not* on the list. A plugin calls
   `logging.getLogger(__name__)` like any Python library. What the library promises
   instead is where those records go: little-sister logs through the standard
   hierarchy, never switches propagation off, and configures the **root** logger only
   when the application has not — so a deployment or a plugin that sets up its own
   logging *before* importing `little_sister.app` keeps its handlers and its level,
   and little-sister's own records arrive there too. Writing that down forced a fix:
   the root `setLevel(DEBUG)` ran *outside* the has-no-handlers guard, so a dependent
   that had chosen INFO silently got DEBUG. It now sits inside the guard, with the
   third-party noise caps that belong to our default and to nobody else's setup.
   `tests/test_logger.py` holds it.

5. **Adding a name is compatible; removing or renaming one is a version bump and a
   new ADR** — [ADR-0034](0034-template-slots-for-dependent-packages.md)'s rule for
   slots, for the same reason and now with a test behind it.

## Consequences

- **A refactor inside `checks/base.py` is free again**, as long as the facade keeps
  exporting the name. That is what promising the package rather than the module buys,
  and it is the more valuable half of this decision: the surface is now a thing we
  can hold still *without* holding the implementation still.
- **The surface is now something to say no to.** Every helper a future check wants
  arrives as a request to widen a promise, which is the right conversation to have
  before the name is in three repositories rather than after.
- **A plugin repository can state its dependency as a floor** (`little-sister >= x`)
  and mean something by it, because "what x promised" is now written down and
  measured. Two plugins pinning exact versions could not be installed together, so
  the floor is the only workable form — and a floor is only honest against a surface.
- The library's own log records are named `little_sister.logger` rather than per
  module, because every module imports that one object. A dependent that wants to
  quiet the library can still do it by namespace (`logging.getLogger("little_sister")`);
  per-module names would be a nicer surface and are not worth touching thirteen
  imports for today.

## Alternatives considered

- **Leave §11 as prose and be careful.** Free, and it decays on the first rename that
  looks local — which is precisely the rename that will happen inside `base.py`,
  since nothing in this repository imports these names the way a plugin does. The
  whole point of a contract is that it survives the author's attention.
- **Generate the list from the code.** Then it can never disagree with the code — and
  it stops being a promise, because it changes when the code changes. An inventory
  that follows the implementation is the drift, formalized.
- **Promise `little_sister.checks.base` as the import path**, matching what every
  existing check writes today. It is one less edit now and freezes the module layout
  forever; the migration cost is a single import line per check type, paid once, by
  the same change that moves them into their own repositories.
- **Declare `__all__` on every promised module** so the code → doc direction is
  universal. `reasons` and `status` genuinely export names that are internal to the
  library (`derive_code`, `ReasonInput`, `effective_code`), so their `__all__` would
  have to list them and then the "identical" rule would promise them by accident — a
  weaker contract bought with more machinery.
- **Promise the logger object too.** It is one import, and it is what the three
  existing check types do. But it makes a *name* out of what should be a behavior,
  and the behavior is what a dependent needs: a plugin that calls
  `logging.getLogger(__name__)` gets its own name in the log lines *and* lands in
  whatever the application configured, which the shared object cannot offer.
