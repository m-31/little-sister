# ADR-0051 — What startup refuses at the plugin boundary

- **Status:** Accepted
- **Date:** 2026-10-04 (accepted 2026-08-08, decided while writing the procedure for
  moving a check type into a repository of its own)
- **Related:** [ADR-0049](0049-the-check-authoring-surface.md) (the surface this
  versions, and the gate this completes),
  [ADR-0022](0022-generated-release-branch.md) (the tag a dependent pins),
  [ADR-0035](0035-registering-a-config-aspect.md) /
  [ADR-0034](0034-template-slots-for-dependent-packages.md) (the neighboring
  registration seams, whose failures are a warning and a skip — and why these two
  are not), [ADR-0021](0021-script-resolution.md) (the other place where "which of
  these two things is answering" had to be made explicit),
  [ADR-0100](0100-system-is-two-views.md) (the *Installed* view of `/system`, which
  names who answers for each type)
- **Register:** [`../decisions.md`](../decisions.md)

## Context

A check type registered in-source by the deployment that owns it cannot surprise
anybody: one repository, one commit, one process. Once a type arrives as a
**separately released package**, two failures become possible that the code has no
answer for today, and both are silent.

**Two packages can claim one `type:` string.** `CHECK_TYPES[type_name] = cls`
overwrites. Whichever module imported last wins, and the loser's configuration —
its YAML, its credentials, its thresholds — is then handed to somebody else's class.
Nothing logs, nothing fails, and the dashboard looks fine.

**A plugin can outlive the surface it was built against.** The install-time floor a
package declares (`little-sister >= x`) is a floor and deliberately never a pin: two
plugins that each pinned an exact library version could not be installed together.
But a floor has no ceiling. A deployment upgrades little-sister, a name the plugin
imports has legitimately moved on a version bump ([ADR-0049](0049-the-check-authoring-surface.md)
decision 5), and the failure surfaces as an `ImportError` from inside a package whose
author is not in the room. When the break is *semantic* rather than a missing name —
a changed default, a signature that grew a keyword — nothing surfaces at all.

There is a third thing these two share: the version of little-sister that *matters*
to a plugin is not the release, it is the **check-authoring surface**. Tying a plugin
to the library's version line would force a plugin release for every UI change, and
would still not say what the plugin actually depends on.

## Decision

1. **A type name is claimed once, and names stay bare.** `type: github` keeps its
   spelling — the common case does not pay for the rare one, and every existing
   config keeps working. `register` refuses a second claim on a name with a
   `CheckError` that names **both classes**, so the failure says who is fighting over
   what. Re-registering the *same* class is not a conflict: a module re-imported
   under a reloading server re-runs its decorators, and refusing that would refuse
   the server.

2. **The check-authoring surface has an epoch of its own** — `API_VERSION`,
   currently 1. It bumps when a promised name is removed or renamed, or a documented
   behavior changes. It does **not** bump when a name is added, nor for anything else
   in a release: a plugin should follow the part of the library that is its contract,
   not the library's release cadence.

3. **A plugin declares the epoch it was built for**, with `require_api(n)` beside its
   registrations, and a mismatch **refuses at startup** naming both numbers, the
   library's version and the package. This is the second line of defense, not the
   first: the floor keeps a *too old* library out at install time; the epoch catches
   the upgrade the floor cannot see.

4. **The epoch is enforced by a snapshot.** `tests/fixtures/check_api_v<n>.txt`
   records the surface epoch *n* promised, and the gate requires the current §11
   block to still contain every line of it. This closes the hole
   [ADR-0049](0049-the-check-authoring-surface.md) left open: its two directions
   compare the doc against the code *as they are now*, so a rename that edits both in
   one commit passes. The snapshot is what a *released* plugin was built against, and
   a same-commit edit does not touch it. Removing a name therefore forces the choice
   into the open — restore it, or bump the epoch and write the next snapshot. A
   snapshot file is append-only within its epoch.

5. **Both refusals are hard, unlike the neighboring registration seams.** A slot
   filler, an asset, a policy contribution or an aspect that fails to register is a
   **warning and a skip** (ADR-0034 / 0035 / 0037 / 0048): the page renders with one
   thing missing, and a monitoring system that still monitors is worth more than one
   that will not start. These two are the opposite case. A duplicate type name means
   checks run against configuration that was not written for them, and an epoch
   mismatch means the code answering for a check is not the code that was tested —
   both produce a system that *reports*, confidently, without measuring what the
   operator believes it measures. A monitoring tool that is wrong is worse than one
   that is down, so these refuse.

6. **`/system`'s *Installed* view names who answers for each type**, at
   `/system/installed` ([ADR-0100](0100-system-is-two-views.md)) — every registered
   type with its module, its distribution and that distribution's version. Once a type
   can come from a package released elsewhere, this is not derivable from this
   repository at all; the running process is the only source. It sits beside the slot
   fillers and the assembled policy, for the same reason they are there.

## Consequences

- **Two vendors of a `github` check cannot be installed together.** That is the
  honest outcome of bare names, and it is loud: the process does not start, and the
  message names both classes. The workaround is available to whoever hits it — rename
  the type in one package — and it stays a rename rather than a resolution rule
  everybody has to learn.
- **An epoch bump obliges every plugin to release.** That is the cost of a coarse
  boundary, and it is why the bump is defined narrowly: only a name leaving the
  surface or a documented behavior changing. Adding names — the common growth — costs
  nobody anything.
- **The snapshot is the first thing in this repository that makes a *deliberate*
  breaking change visible to a test.** Everything before it caught inattention.
- **A semantic break still slips through.** A default that changes, a signature that
  gains a keyword: the names are all present, the epoch does not notice, and the
  plugin runs against behavior it was not written for. What the epoch buys is that
  such a change must be a *documented behavior* change to be legitimate — which makes
  it an epoch bump by decision 2, enforced by review rather than by the gate. Being
  explicit that this is the boundary of the mechanism is better than believing the
  mechanism is total.
- `require_api` is itself on the surface, which means it can never be renamed without
  the epoch it exists to police. It is in epoch 1's snapshot for that reason.

## Alternatives considered

- **Namespace the type names** (`little_sister_github/github`). Collisions become
  impossible and the YAML says which package answers. But every existing config line
  changes, the library's own built-ins acquire a prefix they do not need, and the
  common case — one package, one obvious name — pays for a collision that may never
  happen. A refusal costs nothing until the day it fires, and on that day it says
  more than a prefix would have.
- **Bare by default, namespace as a tie-break.** Two spellings for one thing, plus a
  resolution rule to document, test and explain, in exchange for making a hard
  failure soft. If two plugins really must coexist, renaming a type in one of them is
  a one-line change in that package.
- **First registration wins, with a warning.** Consistent with the other seams, and
  wrong here: the loser's checks silently run the winner's code. A warning in a log
  is not where an operator learns that their `github` checks are somebody else's.
- **An upper cap in the plugin's metadata** (`little-sister >= 0.2.5, < 0.3`). Pure
  packaging, no library code, and the resolver enforces it before anything runs — but
  every library minor release then forces a release of every plugin, whether or not
  the surface moved. On a 0.x line the cap would move constantly and mean nothing.
- **Match on the library's version instead of an epoch.** Same problem in a different
  place: a plugin would be pinned to a cadence rather than to a contract, and the
  number in `require_api` would stop describing anything a plugin author can reason
  about.
- **Generate the epoch snapshot from the code at release time.** Then it records what
  the code *is* rather than what was *promised*, which is the drift the snapshot
  exists to catch. It is written once, by hand, when an epoch opens.
