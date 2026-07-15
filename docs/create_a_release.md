# Creating a release

How a release of this repository is produced, and what a release *is*. The
process is repo-agnostic — the client-app repository and future plugin
repositories release the same way, each on its own version line.

## What `main` is

`main` carries **releases only**: one squash commit per version, tagged
`v<major.minor.patch>` (annotated; the tag message carries the release notes).
It is **generated** — a condensed file-tree snapshot of the private working
branch — never merged into or edited directly. Development history, working
notes (the roadmap, open questions, the idea inbox), and the release tooling
itself stay on the working branch; what ships is the current state: the code,
its tests, and the documentation set that is useful to consumers.

Two properties are enforced by tooling at release time, not by convention:

- **Docs are classified.** Every Markdown file is deliberately marked
  ship / don't-ship; an unclassified one fails the release.
- **No private strings.** The entire released tree — code, tests, configs —
  is scanned against a denylist of private strings (real hostnames, private
  infrastructure, personal contact data). A hit fails the release.

## The pipeline

Two scripted steps per side, a human review in between — and a human pushes,
never a script.

**On the working branch:**

1. Bump the version in `pyproject.toml` by hand — the bump *is* the decision
   to release — and write consumer-facing notes under `## [Unreleased]` in
   [`CHANGELOG.md`](../CHANGELOG.md).
2. **`release_prep.sh`** — validates, runs the quality gate (`ruff` + `mypy` +
   `pytest`), rolls `[Unreleased]` into a `## [<version>] - <date>` section,
   and commits. No tag yet: the version and CHANGELOG are single-sourced on
   the working branch; `main` only gates and tags.

**On the `main` worktree** (a dedicated worktree, created on first run —
the everyday checkout is never touched):

3. **`sync_main.sh`** — snapshots the working branch's *committed* tree onto
   `main` (a file sync, not a merge), condenses the docs (drops the
   working-branch-only files, strips their release markup, validates), scans
   the tree for private strings, and stages the result. Nothing is committed
   until a human has **reviewed the staged diff**.
4. **`release_main.sh`** — runs the quality gate again on the condensed tree
   (a second net under the validation), commits `Release v<version>`, and
   creates the annotated tag with the CHANGELOG notes. Push after a final
   look: `git push github main --follow-tags`.

A failed validation is fixed on the working branch with ordinary commits, then
step 3 is re-run. Nothing on `main` is ever hand-edited, and
`release_prep.sh` runs once per version.

## Consuming releases

- Pin a **tag** (`v<x.y.z>`); `main` moves only at releases, one commit each.
- Release notes live in the tag message and in [`CHANGELOG.md`](../CHANGELOG.md).
- The repositories in this family (library, client app, plugins) version
  **independently**; when the JSON API contract changes, a client states the
  minimum library version it needs. The contract is
  [`api/openapi.yaml`](api/openapi.yaml).
- Bugs and requests:
  [GitHub issues](https://github.com/m-31/little-sister/issues).

