# ADR-0031 — One deployment config directory, split by aspect

- **Status:** Accepted
- **Date:** 2026-10-25 (accepted 2026-08-01)
- **Related:** [ADR-0015](0015-check-discovery-union.md) (the path-list this generalizes),
  [ADR-0012](0012-node-metadata.md) (`nodes.yaml`, the first non-check tenant),
  [ADR-0030](0030-curated-links.md) (`links.yaml`, the third),
  [ADR-0120](0120-every-stored-time-is-an-instant.md) (decision 7, the settings file),
  [ADR-0046](0046-user-list-from-the-configuration-roots.md) (the user list, whose
  only input is the `users` aspect), [ADR-0003](0003-config-and-secrets-via-env-file.md) (`.env`, which
  stays out), [ADR-0014](0014-maintenance-persistence.md) (`var/`, which also stays out),
  [ADR-0021](0021-script-resolution.md) (packaged defaults with an override — the same
  shape, one level down),
  [ADR-0137](0137-a-deployment-says-in-a-table-how-a-part-counts-above-it.md) (the
  `aggregation` aspect, a file in each root, every root's read),
  [ADR-0133](0133-a-node-says-what-it-is-in-a-card-and-at-length-in-a-handbook.md)
  (decision 3: the `handbook` aspect, a directory of the files a node's handbook names),
  [ADR-0139](0139-a-node-carries-every-tag-written-for-it-or-above-it.md) (the `tags`
  aspect, decision 3, and the tags of `nodes.yaml`, which add up across the roots,
  decision 2), [ADR-0038](0038-declarative-action-list.md) (the `actions` aspect) and
  [ADR-0048](0048-an-assembled-content-security-policy.md) (decision 5: the `csp`
  aspect), each a root's to add to,
  [ADR-0035](0035-registering-a-config-aspect.md) (the seam through which a dependent
  package registers an aspect of its own).
- **Register:** [`../decisions.md`](../decisions.md)

## Context
`checks/` was accurately named when it held checks. It now holds three unrelated kinds
of thing — check configs, `nodes.yaml` (node metadata, which `load_checks` carries a
skip-list to step over, [ADR-0012](0012-node-metadata.md)), and `links.yaml` if
[ADR-0030](0030-curated-links.md) is accepted. The deployment's other authored inputs sit
*beside* the directory in the working directory: `config.yaml`
([ADR-0120](0120-every-stored-time-is-an-instant.md) decision 7), `users.yaml`
([ADR-0046](0046-user-list-from-the-configuration-roots.md)), `.env`
([ADR-0003](0003-config-and-secrets-via-env-file.md)). The web-customization phase adds
another — a brand, which is a little data plus some asset files.

The misleading name is the visible problem. The real one is underneath it.

**Only checks are layerable.** `LITTLE_SISTER_CHECKS_DIR` is a **path-list** — a
deployment composes `base:sites/alpha` and the checks union in order
([ADR-0015](0015-check-discovery-union.md)). That is how a deployment with several sites
stays DRY. But it belongs to *checks* by accident of history: `nodes.yaml` and
`links.yaml` inherit it only because they happen to sit in the same folder, and
`config.yaml` and `users.yaml` cannot have it at all. Layering ought to be a property of
**the deployment's configuration**, not of whichever aspect was written first.

Left alone, each new aspect either squats in a directory named for something else, or
grows its own environment variable and its own answer to "what happens when there are
two of them."

## Decision

**One layered configuration directory, `config/`, whose entries are aspects.**

1. **`LITTLE_SISTER_CONFIG_DIR` is a path-list** (`os.pathsep`-joined, default
   `config`), replacing `LITTLE_SISTER_CHECKS_DIR`. The list says **where** to look; each
   aspect says **how** its layers combine. Every root must exist, as today.

2. **An aspect is a file when one file can hold it, a directory when it cannot.**
   `config/<aspect>.yaml` for an aspect that is a single document; `config/<aspect>/` when
   it needs more than one file — either because its data *is* a set of files, or because it
   carries assets beside its data. Both forms present in one root is an **error**, not a
   precedence rule, and an aspect can grow from a file into a directory later without a
   second migration.

   **`checks` is always a directory.** Its unit of data is the file — one check per
   `*.yaml`, resolved relative to that file's own location — so there is no single document
   to put in `config/checks.yaml`, and inventing one would mean either a file whose plural
   name holds one check or a second, list-shaped way to declare checks. This is the rule
   applied, not an exception to it. `links` takes the directory form for the other reason:
   only once it ships icon files of its own. **`handbook` is always a directory** for the
   first reason: Markdown files, each a node's handbook that a statement names —
   `handbook: handbook/ec2.md` in a check's file or in `nodes.yaml` — relative to the
   root the statement is in, and never found by a node's path
   ([ADR-0133](0133-a-node-says-what-it-is-in-a-card-and-at-length-in-a-handbook.md)
   decision 3). `aggregation`, the deployment's configured rules, which say how a part
   of the tree counts above it
   ([ADR-0137](0137-a-deployment-says-in-a-table-how-a-part-counts-above-it.md)
   decision 2), and `tags`, the known tags, each with a line of what it means, which
   gives no node a tag
   ([ADR-0139](0139-a-node-carries-every-tag-written-for-it-or-above-it.md) decision 3),
   are always a file.

   ```
   config/
     checks/            many *.yaml — one per check
     actions.yaml       the configured actions
     aggregation.yaml   the configured rules
     csp.yaml           what the deployment adds to the content policy
     handbook/          the handbooks, one Markdown file each
     links.yaml         curated links
     nodes.yaml         node metadata
     settings.yaml      the settings, once config.yaml
     tags.yaml          the known tags
     users.yaml         the user list
   ```

3. **An aspect joins the table when its loader lands, not before.** A name the library
   recognizes but nobody reads would be a worse lie than the honest "not a known aspect"
   warning, so an aspect joins with the record that brings the loader reading it —
   `links` with [ADR-0030](0030-curated-links.md), and each that came after it with the
   record decision 4 names beside it — and until it does, a file of its name warns, which
   is true.

   **Aspect names are known to the library, not discovered.** A **candidate aspect** is a
   `*.yaml` / `*.yml` file or a directory; an unrecognized candidate **warns and is
   ignored** — but not at the moment the root is resolved. Resolving a configuration root is
   **silent**, and the report runs once at the end of the registration window, from
   `config_dir.announce_aspects()`
   ([ADR-0070](0070-the-unclaimed-file-report-runs-at-the-end-of-registration.md)). Emitted
   at the first resolution it named every aspect not yet registered at that instant, which
   the seam [ADR-0035](0035-registering-a-config-aspect.md) added made unfollowable rather
   than merely delicate. Late, it also covers **every** configured root rather than only the
   resolved ones, and it names the packages that read the aspects it knows. Everything else
   in `config/` — a `README.md`, a dotfile, an editor's `.bak`
   — is not a candidate and passes in **silence**, which matters because the library
   itself ships `config/checks/README.md` into that tree and a permanent warning about a
   deployment's own documentation would train everyone to ignore the log. Nothing here
   stops the monitor either way. A dependent package adds an aspect of its own through a
   registry seam in the shape of `CHECK_TYPES`
   ([ADR-0035](0035-registering-a-config-aspect.md)); the library's own aspects are the
   floor it cannot move.

4. **Combining rules stay per aspect.** The shared directory list deliberately does not
   impose one, because the aspects disagree for good reasons:

   | aspect | across roots |
   |---|---|
   | `checks/` | union; overlapping node ownership is a hard error ([ADR-0015](0015-check-discovery-union.md)) — unchanged |
   | `actions.yaml` | union: a site root adds its actions to a base root's ([ADR-0038](0038-declarative-action-list.md)) |
   | `nodes.yaml` | per **field**, later root wins; an override is logged with both files named — an entry's `tags` excepted, which add up (below) |
   | `links` | groups merge by title, file order preserved ([ADR-0030](0030-curated-links.md)) |
   | `handbook/` | nothing of its own: a root's statement names a file of its own root, and which statement wins is `nodes.yaml`'s rule per field and the check's ([ADR-0133](0133-a-node-says-what-it-is-in-a-card-and-at-length-in-a-handbook.md) decision 3) |
   | `settings.yaml` | shallow merge, later root wins **per key** — the file is a flat mapping of scalars, so this is well defined |
   | `aggregation.yaml` | every root's file read, the root named last first, so that a site's root decides where it and a shared base pick one place — a later root winning, as everywhere else in the chain; a rule's name is unique across them ([ADR-0137](0137-a-deployment-says-in-a-table-how-a-part-counts-above-it.md) decision 2) |
   | `tags.yaml` | every root's file read and added up, the later root's line winning for a tag two of them name, each tag keeping the place it was first named in ([ADR-0139](0139-a-node-carries-every-tag-written-for-it-or-above-it.md) decision 3) |
   | `csp.yaml` | union: a site root adds its sources, and there is nothing to overwrite ([ADR-0048](0048-an-assembled-content-security-policy.md) decision 5) |
   | `users.yaml` | the **first** root that declares it wins entirely; a second is a warning |

   Users are the odd one deliberately: merging identities across layers is a security
   question wearing a convenience costume, and a deployment that wants it can say so
   later.

   **`nodes` merges per field, not per entry**, because that is already the grain of the
   thing: [ADR-0012](0012-node-metadata.md) resolves `about` and `title` independently, and
   [ADR-0025](0025-check-provided-subnode-metadata.md) spells it out — a declaration that
   sets only `title` still lets the check fill `about`. Whole-entry replacement across roots
   would make one file behave two different ways depending on whether another root happened
   to name the same path, and would defeat the case the layering exists for: a site root
   retitling one node of a shared base. This **replaces the previous hard error** on a path
   declared in two files, which was a loader convention rather than an ADR decision; the
   override is logged at INFO with winner and loser named, because a silent winner decided
   by root order is indistinguishable from a bug. A later root can **override** a field but
   not **clear** it — an empty value means "not declared here", not "blank it" — which is
   deliberate and the same reading every other layer of this precedence chain uses. One
   field combines otherwise: an entry's `tags` add up across the roots, as tags add up
   wherever they are written
   ([ADR-0139](0139-a-node-carries-every-tag-written-for-it-or-above-it.md) decision 2).

5. **`config.yaml` becomes `config/settings.yaml`, and `users.yaml` becomes
   `config/users.yaml`.** Moving them in the same change is the point — a deployment
   reorganizes its layout **once**, not once per aspect. `settings` rather than `config`
   because `config/config.yaml` reads as a mistake.
   [ADR-0046](0046-user-list-from-the-configuration-roots.md) removes
   `LITTLE_SISTER_USERS` — *because* of this record's own first-root-wins rule for
   `users`, which already expresses a single-file override as a users-only root named
   first — and makes startup refuse while the name is set. `LITTLE_SISTER_CONFIG` keeps
   working as an explicit single-file override that **bypasses layering entirely**,
   which is what an override should mean: settings **merge per key**, so a prepended
   settings root layers rather than replaces, and nothing in the path-list reproduces
   it. That is a restatement of the record it belongs to, not a decision taken here.

6. **`.env` and `var/` stay out.** `.env` is secrets and process environment
   ([ADR-0003](0003-config-and-secrets-via-env-file.md),
   [ADR-0023](0023-secret-references.md)); it is read before anything else and must not be
   layerable. `var/` is what the process **writes** ([ADR-0014](0014-maintenance-persistence.md)).
   The line is clean and worth stating once: **`config/` is read-only input the operator
   authors; `var/` is state the program owns.**

7. **A clean break, and a startup contract that is strict about the tree but tolerant
   about its contents.** There is no compatibility shim: `LITTLE_SISTER_CHECKS_DIR` is gone
   and a `checks/` directory is never consulted. Every consumer pins a released tag and
   upgrades deliberately, so a shim would be dead code from the day it shipped and would
   double the loader's paths for the rest of its life.

   **Fatal — the process refuses to start**, each case naming the resolved path it looked
   at, in the exception and in the log:

   - `LITTLE_SISTER_CONFIG_DIR` unset or empty **and** no `config/` directory;
   - a root named in `LITTLE_SISTER_CONFIG_DIR` that does not exist (point 1's rule, held
     to);
   - **no root provides a `config/checks/` directory at all** — an instance with nowhere to
     look for checks is misconfigured, not empty. **One** root providing it is enough: a
     site root carrying only its own `nodes.yaml` is normal, and demanding checks in every
     root would defeat the layering this ADR exists for;
   - the config directory absent while a **legacy marker** sits beside it (a `checks/`
     directory, a top-level `config.yaml`, or a top-level `users.yaml`). This is the first
     case wearing a better message rather than a fourth rule — the refusal is the same
     either way, and the markers only let it **name the moves**. The old layout is detected
     *only in order to refuse*. That is a diagnostic, not compatibility.

     **`LITTLE_SISTER_CHECKS_DIR` is deliberately not among the markers.** The break is
     clean enough that the retired name is not read anywhere, not even as a hint: leaving
     one `os.environ` read behind would keep the variable alive in the code that exists to
     have removed it, and would then owe an answer to "what if it is set *and* the tree is
     fine?" — a question worth nothing to anyone. The three files are the surer signal
     anyway. An environment variable is the likeliest leftover to outlive the deployment
     that set it, and it is also the one an operator can fix without knowing anything about
     this ADR.

   **Allowed, but loud — a checks aspect that holds no checks.** A fresh install, or a
   deployment mid-bring-up, legitimately watches nothing yet. The engine starts, a
   **warning names the reason and the directories it searched**, and the engine's own
   heartbeat node reports **WARN** carrying that reason
   ([ADR-0005](0005-dashboard-freshness-and-self-monitoring.md)). The status pill is the
   right place for it: with zero checks the tree is *only* the heartbeat, so an OK
   heartbeat would roll up to an all-green root while nothing at all is being watched —
   the exact lie that ADR's first decision exists to prevent.

   The line between the two lists is *"you have not configured me"*, where nothing about
   the instance can be right and there is no useful degraded mode, versus *"you have
   configured me to watch nothing yet"*, which is a real and temporary state. Today's
   treatment of a missing checks directory as non-fatal belongs to the first case and
   becomes fatal. A **broken** check config is unaffected and keeps its current behavior —
   the engine does not start and the header carries `engine_error` — because that is a typo
   in one file, already visible, and not an unconfigured deployment.

   **Named on the startup record, the start going on — what describes a node, and a rule
   that cannot apply.** A handbook is a node's metadata, which must not stop monitoring,
   so a `handbook.yaml` is named on the startup record rather than refusing the start, as
   is a file in `handbook/` that no statement names
   ([ADR-0133](0133-a-node-says-what-it-is-in-a-card-and-at-length-in-a-handbook.md)
   decision 3); so is what cannot be read in `tags.yaml`, a tag being a node's metadata
   too ([ADR-0139](0139-a-node-carries-every-tag-written-for-it-or-above-it.md)
   decision 3), and a rule in `aggregation.yaml` that cannot apply, the alarm it was to
   quiet staying
   ([ADR-0137](0137-a-deployment-says-in-a-table-how-a-part-counts-above-it.md)
   decision 2). The program never writes `aggregation.yaml`, as it writes nothing in
   `config/` (decision 6).

8. **The override ladder is the house pattern.** Three features now share one shape —
   scripts ([ADR-0021](0021-script-resolution.md)), icons
   ([ADR-0030](0030-curated-links.md)), and the brand the customization phase will want:
   **a packaged default, then an override registered by a dependent package, then a file
   the deployment authors.** Later steps win **per named item, never wholesale**, so a
   package that overrides one entry leaves the rest of the defaults standing. A feature of
   this kind follows the ladder rather than inventing a fourth arrangement — and anything
   that resolves by *import order*, the slot where `CHECK_TYPES` registration already
   lives, **logs when order actually decided something**, because a silent winner there is
   indistinguishable from a bug.

## Consequences
- **This deletes code.** `load_checks` stops needing `NODES_FILENAME` and its skip
  branch, because `config/checks/` contains only checks. The one aspect that shares a
  directory with another stops sharing.
- **Every aspect gets layering**, so `base:sites/alpha` composes settings and links the
  same way it already composes checks — and the answer to "what happens with two of
  them" is written down once per aspect instead of invented per feature.
- **The docs get one place to point.** "Your deployment's configuration is `config/`"
  replaces four separate location rules learned from four separate ADRs.
- **Every deployment repo does a one-time move**, and there is no window in which both
  layouts work. They pin a released tag, so none is surprised in place, and an upgrade that
  forgets the move **fails loudly with the moves named** rather than drifting into a
  half-loaded tree.
- **A misconfigured instance no longer serves a reassuring page.** The failures in point 7
  are the ones where every answer the dashboard could give would be wrong, so refusing to
  start is the honest response; the one survivable case — a configured deployment with no
  checks in it yet — stays visible on the surface rather than only in a log.
- The `checks/README.md` + `checks/examples/` that a deployment repo one-way-copies from
  here move with the directory; its sync script needs the path updated.
- **Two ways to spell an aspect is more loader code** and one more thing to explain.
  Bounded by making "both present" an error, so no deployment has to reason about which
  one wins — and by the rule in point 2 deciding the form per aspect rather than leaving it
  to taste, so `checks` has exactly one legal shape and nobody has to wonder whether
  `config/checks.yaml` would work.
- Nothing about check *config* changes — a check file is unchanged, and relative paths
  inside it still resolve against their own file's directory, so a check that moved one
  level deeper needs no edit.

## Alternatives considered
- **Leave `checks/` alone and keep adding files.** Free, and it is what happens if
  nobody decides. Rejected: the name already misleads, and the layering asymmetry gets
  worse with every aspect added — each one either squats or grows its own variable.
- **Rename to `config/` but keep it flat**, checks mixed in with the single-file
  aspects. A simpler loader, but a real deployment has dozens of check files and they
  would bury the four aspects that are one file each.
- **A per-aspect environment variable** (`LITTLE_SISTER_LINKS_DIR`,
  `LITTLE_SISTER_BRAND_DIR`, …). Explicit and requires no migration, but it is N paths to
  document, N defaults to remember, and no shared layering story — exactly the drift this
  ADR exists to stop.
- **One `deployment.yaml` holding every aspect.** Attractive for a three-check
  installation and hostile for a real one: a file per check is what makes checks
  reviewable in a diff, and a single document cannot be layered per aspect.
- **Discoverable aspects through a registry now**, so a dependent package could add one.
  Over-built: nothing outside the library needed an aspect yet, and the shape was easy to
  add once something did — [ADR-0035](0035-registering-a-config-aspect.md) adds it.
- **Merging `users.yaml` across roots** like the other aspects. Rejected as the default —
  identity is where a surprising merge does the most damage.
- **A one-release compatibility window** that loads the legacy layout with a deprecation
  warning. This was the earlier draft of point 7. Rejected: with every consumer pinned to a
  tag, nobody is upgraded into the change by surprise, so the shim would be dead code from
  the day it shipped — two resolution paths through the loader, two sets of tests, and a
  deletion to remember a release later. A failure that names the moves does the same job in
  a tenth of the code and cannot rot.
