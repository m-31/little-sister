# ADR-0052 — Plugin names: one convention for a git dependency and a published one

- **Status:** Accepted
- **Date:** 2026-08-23 (accepted 2026-08-08, decided while writing the extraction
  procedure, looking ahead to publication)
- **Related:** [ADR-0051](0051-what-startup-refuses.md) (the type name this pins, and
  the roster that reads the mapping),
  [ADR-0049](0049-the-check-authoring-surface.md) (what a plugin depends on),
  [ADR-0022](0022-generated-release-branch.md) (the tag a git dependency resolves)
- **Register:** [`../decisions.md`](../decisions.md)

## Context

The first plugin repositories are consumed as **git dependencies** — a
`[tool.uv.sources]` entry naming a tag — because that is what the library and the
deployments already do and it needs no index. Publication to an index comes later.

That ordering is a trap if the names are chosen for the interim. A distribution name
is the one identifier that is genuinely expensive to change: renaming it is a *new
project* for every consumer, and on an index the old name keeps existing, held by
whoever asks for it next. An import package name is nearly as bad — it edits every
deployment's `wsgi.py` — and a `type:` name is worse in a quieter way, because
renaming it does not orphan anything; the checks simply stop loading.

So the question is not what to call the first three packages. It is whether the names
chosen now survive the move to an index unchanged, and what would have to be true for
that to hold.

## Decision

1. **One word, three spellings, derived mechanically.** For a plugin `<x>`: the
   distribution is `little-sister-<x>`, the import package is `little_sister_<x>`, and
   the check type it registers is `<x>`. Nothing else is chosen.

2. **A git source is a redirect, not a different package.** `[tool.uv.sources]` says
   where to fetch a distribution, never which one it is: the dependency name and every
   `import` statement are identical whether the wheel came from a tag or an index. So
   publication is the deletion of a table from the consumers' `pyproject.toml`, and
   changes no code, no configuration and no import — *provided* the git era already
   uses the published name. That proviso is this record's reason to exist.

3. **The name is *checked* when the repository is cut, and claimed by its own first
   release.** A git dependency claims nothing, and a name discovered to be taken after
   deployments pin it is a rename in every consumer — which decision 1 exists to avoid.
   What avoiding it costs is a **check**, not an upload: every package in the family has
   working code and a version to cut, so its claim is its own first publication and
   nothing has to be invented to hold a name ahead of time. The window between the check
   and the claim is accepted knowingly, and what bounds it is publishing the family
   close together rather than one package a year.

4. **No `little_sister.` sub-namespace.** `little_sister.plugins.<x>` reads better and
   cannot be had: `little_sister` is an ordinary package with its own `__init__.py`,
   so a separate distribution may not add submodules to it, and converting the library
   to a namespace package to allow it would mean giving up its own `__init__`. Flat
   names also keep two distributions from ever writing into one directory.

5. **The type name is the package's suffix.** `little-sister-github` registers
   `github`. Type names are bare and claimed once
   ([ADR-0051](0051-what-startup-refuses.md)), so a collision refusal then names two
   projects whose names say what they claim; and entry-point discovery, when it
   arrives, has an obvious key rather than a mapping to invent.

## Consequences

- **Publication becomes a packaging change, not a migration.** That was the point of
  doing the repository split before the index, and this is the part of it that had to
  be decided at the start rather than at the end. The convention is what made the move
  cost nothing: the git era used the names the published era now uses, so no consumer
  renamed anything.
- **The hyphen/underscore pair is one name, not two.** Index names normalize, so
  `little-sister-<x>` and `little_sister_<x>` are the same project. That is what lets
  `/system` derive the distribution from a registered type's import package and show
  which package answers for it. It is a *convention* the code leans on, not a
  guarantee the packaging system makes — which is why the roster shows the loaded
  path beside the version rather than trusting the mapping alone.
- **A plugin that wants a name outside the convention** — a vendor's own prefix, a
  type name that differs from its package — is not forbidden, but it gives up the
  derivation: the roster will show its distribution as unknown. That is a fair price
  and a visible one.
- **A reservation that holds is a real minimal release, not a placeholder.** PEP 541
  names "package has no functionality or is empty" as exactly the condition under which
  a project may be removed from the index on request — its own definition of name
  squatting — so a name held with an empty shell can be taken back by a determined
  claimant, which is the opposite of what a reservation is for. The distinction only
  ever bites for a name agreed *ahead* of its code, a fifth plugin agreed but unwritten
  say; every name here has code behind it, so each is claimed by its own first release
  (decision 3) and none of them needs a reservation at all.
- **The window is closed, and the four names are held by a real release** —
  `little-sister` 0.3.11 and the three plugins at 0.1.0, each claimed by its own
  first upload. The one near name is not a collision: `littlesis` is taken — a
  wrapper for an unrelated public-interest database whose own name makes the same
  joke this project's does — and it normalizes differently, so it is a confusion
  rather than a conflict; what tells the two apart where a reader meets them is the
  `description`.

## Alternatives considered

- **Name them for the git era and rename at publication.** Every consumer's
  `pyproject.toml` and `wsgi.py` change on a day that was supposed to be a packaging
  detail, and the old names stay on the index forever, held by nobody or by somebody
  else.
- **A `little_sister.plugins.<x>` namespace.** Rejected on the mechanics above, but
  also on the seam: a plugin that imports as part of the library reads as *inside* the
  version contract, when the whole point of [ADR-0049](0049-the-check-authoring-surface.md)
  is that it is outside it.
- **A shorter prefix** (`ls-<x>`, `lsp-<x>`). Shorter to type, and it stops saying
  what the package is for. These names appear in a deployment's dependency list, where
  "which of these is a little-sister plugin" is the question being asked.
- **Namespaced type names** to make the distribution derivable from the YAML. Rejected
  in [ADR-0051](0051-what-startup-refuses.md) for the common case's sake; decision 5
  buys most of the same legibility by convention instead.
