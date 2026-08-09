# ADR-0050 — A declared slug comes from the provider's identifiers

- **Status:** Accepted
- **Date:** 2026-08-08 (decided while promoting the deployment's slug helper into the
  library; the rule itself was first recorded in the deployment on 2026-08-03)
- **Related:** [ADR-0036](0036-addressable-reasons.md) (addressable reasons — the
  seam a slug fills, and the content hash this is the alternative to),
  [ADR-0042](0042-entries-carry-their-own-code.md) (the entry a slug keys),
  [ADR-0014](0014-maintenance-persistence.md) (what a slug is stored against, and why
  its shape is a stored contract),
  [ADR-0049](0049-the-check-authoring-surface.md) (the surface `slug` joins)
- **Register:** [`../decisions.md`](../decisions.md)

## Context

[ADR-0036](0036-addressable-reasons.md) made a reason line addressable: a check may
hand over `(slug, text)` pairs instead of strings, which declares the lines
**members** — each individually pinnable, so an operator working on one finding does
not silence the other nineteen. It deliberately did not decide **where a slug comes
from**, because only the check knows what its provider considers a durable identity.
The library shipped one answer for the check that has nothing better:
`derived_slug`, a hash of the text.

Every check that discovers findings from an API then has to answer the question
again, and the first two that did — a GitHub check and a cloud-security check in the
private deployment repository — answered it identically, through one shared helper
recorded in that repository's ADR-0004. Those check types are now moving into
repositories of their own. A helper copied into each would maintain **one identity
rule in three places**, and it is not a rule about GitHub or about a deployment: it
is a rule about little-sister's own slug contract, written against
`MAX_SLUG_LENGTH`, about tokens that travel in `?reason=` values and maintenance
files.

So it belongs here, and so does the reasoning, which is where the value is.

## Decision

1. **`slug(*parts)` lives in `little_sister.reasons`**, beside `derived_slug` and
   `MAX_SLUG_LENGTH`, and joins the check-authoring surface
   ([ADR-0049](0049-the-check-authoring-surface.md)). One implementation, one set of
   tests, one place the rule is written down — for every check type in the family,
   not just the two that needed it first.

2. **A declared slug is built from identifiers the provider already owns, never from
   the rendered text.** A hash of the text *is* the wording, so improving a line
   silently drops every pin on it — and the lines worth pinning are exactly the ones
   we keep rewording. `derived_slug` stays the honest default for a check with
   nothing better: it invalidates itself on a re-wording rather than pointing at a
   stranger. A check that has real ids uses them.

3. **And never from a position.** An index slides onto a *different* finding the
   moment an entry above it is inserted or closed, and nothing about the pin looks
   wrong afterwards — the operator sees a maintained line, just not the one they
   maintained. This is the failure mode the whole scheme exists to prevent, and it is
   why the over-long case below is a hash rather than a truncation.

4. **The helper narrows harder than the library validates.** `slug` keeps
   `[A-Za-z0-9._-]` and collapses everything else to a single `-`, so a branch's `/`
   and the space in an entity name never reach a `?reason=` value. `normalize` would
   accept more; a token that needs no escaping *anywhere* is one less thing for a
   call site that forgets to encode it to get wrong. Empty parts — blank, or `None`
   for a field the provider did not send — drop out, so a missing branch leaves no
   dangling separator rather than a literal `None` every entity would then share.

5. **Nothing that was there is allowed to vanish.** The two bounded cases are one
   rule. An **over-long** result keeps a readable prefix plus a hash of the whole
   value; a part that survives the narrowing with **nothing left** (an entity named
   in Cyrillic, in Japanese, in emoji — the ASCII keep-set erases it) is replaced by
   a hash of itself. Both alternatives — truncating, or dropping the part — map two
   findings onto one slug, and `normalize` then separates them with a `-2` suffix in
   *emission order*: the pin lands on whichever the provider happened to return
   first, which is decision 3's failure by a side door. What stays deliberately
   unbounded is a part that merely *changed* (`a/b` and `a-b` still meet): every part
   is an identifier the provider minted, those are ASCII and separator-free by
   construction, and hashing every changed part would re-point every pin holding a
   slug built from a branch name today.

6. **What shape a given check's slugs take stays with that check.** Which
   identifiers, in which order, with which kind word — that is a fact about the
   provider and about the check type, so it is recorded by the *type's* own
   repository, not here. This ADR governs how the identity is built, never what it
   is made of.

## Consequences

- **A slug shape is a stored contract.** A pin lives in the maintenance file against
  `(path, slug)` ([ADR-0014](0014-maintenance-persistence.md)), so renaming a kind
  word silently orphans every pin on that aspect, with no error anywhere. Treat it
  like a database column: change it with a migration, or not at all. This is the rule
  a check type inherits by using the helper, and the reason the acceptance test for
  moving a check type into its own repository is *the same entry slugs*, not a green
  gate.
- **A rename at the provider orphans its pins** — a repository renamed upstream
  re-discovers its findings under the new name. That is the honest outcome: a pin
  that survived would be claiming an identity the provider itself does not.
- **One overlap, documented rather than fixed:** `Entry.derived` reads the `h-`
  prefix, so a declared slug whose first part is `h` reports itself as derived. The
  property is advisory — nothing routes on it — and rewriting the token to avoid the
  collision would silently re-point every pin holding the old one, which is the
  failure this record exists to prevent. It is measured by a test rather than left as
  a warning.
- The deployment's own ADR-0004 keeps its per-type shapes (which identifiers each of
  its check types uses) until those types reach their own repositories; this record
  takes over the general rule and the helper. When the move completes, that ADR is
  superseded **wholly** — by this one plus each new repository's own shape record —
  rather than half-retired now.

## Alternatives considered

- **Copy the helper into each plugin repository.** No library change, and three
  copies of an identity rule that must never diverge, in repositories that release
  independently. The first divergence would not look like a bug; it would look like a
  pin that stopped working.
- **Leave every line on the content hash.** Zero code, fully supported. But no line
  survives an edit to its own wording, and re-wording a reason is one of the most
  common improvements anybody makes to a check.
- **Put `slug` in `checks.base`** with the other authoring helpers. It belongs with
  the thing it is bounded by: `MAX_SLUG_LENGTH`, `normalize` and `derived_slug` are
  all in `reasons`, and a slug helper that lived elsewhere would be the one part of
  the slug vocabulary you had to look for in a second place.
- **A namespaced or opaque global id** (the provider's `node_id`, a UUID). Stable and
  collision-free, and unreadable in a URL, a log line and a maintenance file —
  legibility is most of what makes a stored key debuggable.
