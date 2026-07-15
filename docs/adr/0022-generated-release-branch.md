# ADR-0022 — Public releases from a generated, condensed `main`

- **Status:** Accepted
- **Date:** 2026-07-15
- **Related:** [ADR-0020 — Deployment-supplied user list](0020-user-list-location.md)
  (the library/deployment split this publishing model completes).
- **Register:** [`../decisions.md`](../decisions.md)

## Context
Development happens on a private working branch, with full history and a set of
working notes (roadmap, open questions, idea inbox) that are written freely —
they carry operational detail about the private deployment and half-formed
thinking that is not meant for an audience. The public repository should still
offer developers a complete, current picture: the code, its tests, the
current-state documentation, and the design rationale (this `adr/` set and its
digest). Publishing the working branch as-is would leak the notes and every
private string ever committed; curating each release by hand would rot.

## Decision
`main` is a **generated release branch**: per release, the working branch's
committed tree is snapshotted onto a dedicated `main` worktree (a file-tree
sync, not a merge), **condensed**, reviewed, and landed as **one squash
commit** tagged `v<x.y.z>` (annotated, carrying the CHANGELOG notes). Enforced
by tooling, fix-forward only — nothing on `main` is ever edited by hand:

1. **Three-way doc classification.** Every tracked Markdown file is on a keep
   list or a drop list; one on neither fails the release. The drop set is the
   thinking space plus the release tooling itself.
2. **Release markup, stripped on release.** Kept docs never name a dropped doc
   in prose; such pointers live in `> Rationale:` / `> Dev:` blockquote
   trailers or `<!-- dev-only -->` blocks, both removed by the condense and
   validated — dangling links, leftover names, and unbalanced markers all fail.
3. **A private-strings denylist**, scanned over the **entire** surviving tree —
   code, tests, configs, not just docs: real hostnames, private
   infrastructure, personal contact data. A hit fails the release; the list
   lives with the tooling and never ships.
4. **A split pipeline.** Version bump and CHANGELOG roll happen on the working
   branch, where both are single-sourced; `main` only gates and tags. A human
   reviews the staged diff between sync and release, and a human pushes —
   never a script.
5. **Push discipline.** The working branch and its tags never reach the public
   remote — a reachable tag republishes its entire history, squash or not.
6. **Independent versioning.** Library, client app, and future plugins each
   keep their own version line and CHANGELOG; coordination happens through the
   JSON API contract, with clients stating the minimum library version needed.
7. **Contact without a mailbox.** Package metadata carries a name-only author
   plus project URLs; bug reports and requests go through GitHub issues,
   security reports through GitHub's private vulnerability reporting.
   Published metadata is irrevocable, so no personal email is ever in it.

## Consequences
- "Well-written for release" is a **checkable property**: classification,
  markup stripping, link/name validation and the denylist all run in the
  condense step, and the ordinary quality gate re-runs on the condensed tree
  as a second net.
- Public `main` reads clean — one commit per release on top of the
  pre-existing public history (kept: nothing pins it, and rewriting published
  history buys only cosmetics) — with no working notes and no dangling
  references.
- The working branch stays a free thinking space; the price is small
  release-time discipline (trailers instead of inline pointers to the notes).
- Contributions arrive as issues and PRs against `main`; an accepted PR is
  absorbed into the working branch and lands in the next release squash,
  credited with `Co-authored-by`.
- The process is repo-agnostic — the how-to is
  [`../create_a_release.md`](../create_a_release.md) — and the client-app
  repository runs the same tooling with its own lists and its own
  (`xcodebuild`) gate.

## Alternatives considered
- **Publish everything, scrubbed.** Rejected: a string denylist cannot catch
  "reveals too much operational detail", so the working notes would have to be
  written as if public forever — defeating the point of a private branch.
- **Squash-merges on a shared history.** Rejected: couples the branches and
  still needs every doc and string cleaned at merge time; a generated snapshot
  is simpler, and the condense makes the cleaning checkable.
- **An orphan, clean-start `main`.** Rejected: the few pre-split public
  commits are harmless and nothing pins them; a force-push buys nothing.
- **Manual curation per release.** Rejected: unverifiable, and exactly the
  kind of by-hand discipline that rots.
