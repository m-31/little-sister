# ADR-0035 — A dependent package registers its own configuration aspect

- **Status:** Accepted
- **Date:** 2026-08-01
- **Related:** [ADR-0031](0031-deployment-config-directory.md) (the `config/`
  directory, the aspect vocabulary and the unknown-candidate warning this extends),
  [ADR-0034](0034-template-slots-for-dependent-packages.md) (the sibling seam, decided
  in the same pass — a slot is where an extension's *HTML* goes, an aspect is where its
  *configuration* goes), [ADR-0023](0023-secret-references.md) (a credential in that
  file is still a secret reference), [ADR-0020](0020-user-list-location.md)
- **Register:** [`../decisions.md`](../decisions.md)

## Context

ADR-0031 made `config/` the one place an operator authors input, and made the set of
**aspects** — `checks`, `links`, `nodes`, `settings`, `users` — a closed table in the
library. Anything else found in a configuration root warns ("not a known configuration
aspect and is ignored") and is skipped. That table carried a note predicting its own
successor: *"A registry seam in the shape of `CHECK_TYPES` is the later move if a
plugin package ever needs to add one; nothing needs it today."*

ADR-0034 makes something need it today. A dependent package that fills a template slot
has parameters an operator must be able to edit — an issue tracker's base URL, project
id, issue type — and they belong in the tree the operator already knows, layered by the
same path-list, not in a second configuration mechanism invented per extension. Put the
file there without saying anything and the library warns about it on every start, which
trains everyone to ignore the one warning that catches a real typo.

## Decision

`config_dir.register_aspect(name, *, as_file=True, as_directory=False)` — a dependent
package declares an aspect it reads, before the app is imported.

1. **The library's own table is the floor.** `BUILTIN_ASPECTS` is fixed; `ASPECTS` is
   it plus whatever was registered. A registration naming a built-in is **refused**
   with both shapes logged: an extension may add an aspect, never redefine `checks`
   or `users`.
2. **A registered aspect is an ordinary aspect.** It gets the same shape enforcement
   (`aspect_in` still refuses `config/jira/` for a file-only aspect and refuses both
   forms at once), the same path-list layering via `aspect_files`, and the same
   first-root-wins helper `sole_aspect_file`. The *combining rule* stays the caller's,
   exactly as it is for the built-ins — the library does not know how someone else's
   document layers.
3. **The name is a bare lower-case stem** (`[a-z][a-z0-9_-]*`). It is turned straight
   into a path under a configuration root, so a separator, a dot or a `..` is refused.
4. **Every refusal is a warning and a skip.** A bad registration costs the deployment
   its feature, not its monitoring — the same posture the check loader and the icon
   packs take. First registration of a name wins; a later, differing one is logged and
   ignored, so import order cannot silently redefine a shape.
5. **Register before the app is imported.** The unknown-candidate warning fires once
   per root at the first resolution, so a registration arriving after it has nothing
   left to prevent. This is the same import-before-app slot check types, icon packs
   and slot fillers use.
6. **Registered aspects are visible on `/system`**, beside the slot fillers, for the
   reason given in ADR-0034 §9.

## Consequences

- An extension's configuration sits in `config/<name>.yaml` beside the library's, is
  layered by `LITTLE_SISTER_CONFIG_DIR` like everything else, and no longer earns a
  warning; a *genuine* stray file still does, so the warning keeps its meaning.
- The aspect table is no longer a constant. Code reading `ASPECTS` must not assume the
  five names — `_warn_unknown_candidates` and `aspect_in` already read it live, and
  `forget_aspects()` exists so one test's registration cannot decide another's warning.
- The library still reads none of it. A registered aspect is a *name and a shape*; the
  document's schema, its validation and its error messages belong entirely to the
  package that registered it. That is the boundary that keeps this a seam rather than
  a plugin format.
- A credential in such a file is still a secret reference (ADR-0023), and `.env` and
  `var/` are still not aspects (ADR-0031).

## Alternatives considered

- **Leave the table closed and let extensions read a file outside `config/`.** No
  library change at all, but it splits operator-editable input across two places, skips
  the path-list layering that makes multi-site deployments DRY, and every extension
  re-invents "where does my config live".
- **Drop the unknown-candidate warning and treat any `config/*.yaml` as fine.** One
  line, and it loses the check that catches `config/node.yaml` (singular) sitting there
  doing nothing — the exact failure ADR-0031 §3 added the warning for.
- **A single `config/extensions.yaml` with one block per extension.** One name to
  register instead of a seam, but it makes two extensions share a document (so a
  syntax error in one breaks the other), and it puts the library in the business of
  parsing a top level it does not understand.
- **Discover aspects from registered slot fillers' packages.** Cute, and wrong: an
  extension may want configuration without filling a slot, and a slot filler may need
  none. The two seams are independent on purpose.
