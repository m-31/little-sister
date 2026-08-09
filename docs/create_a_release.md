# Creating a release

How a release of this repository is produced, and what a release *is*. The
process is repo-agnostic, and that is a statement of fact rather than of intent:
the client-app repository and the three plugin repositories —
**little-sister-github**, **little-sister-wiz** and **little-sister-jira** — release
the same way, each on its own version line.

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
2. **`prep`** — validates, runs the quality gate, rolls `[Unreleased]` into a
   `## [<version>] - <date>` section, and commits. No tag yet: the version and
   CHANGELOG are single-sourced on the working branch; `main` only gates and
   tags.

**On the `main` worktree** (a dedicated worktree, created on first run —
the everyday checkout is never touched):

3. **`sync`** — snapshots the working branch's *committed* tree onto `main`
   (a file sync, not a merge), condenses the docs (drops the
   working-branch-only files, strips their release markup, validates), scans
   the tree for private strings, and stages the result. Nothing is committed
   until a human has **reviewed the staged diff**.
4. **`release`** — runs the quality gate again on the condensed tree
   (a second net under the validation), commits `Release v<version>`, and
   creates the annotated tag with the CHANGELOG notes. Push after a final
   look: `git push github main --follow-tags`.

A failed validation is fixed on the working branch with ordinary commits, then
step 3 is re-run. Nothing on `main` is ever hand-edited, and step 2 runs once
per version.

