# ADR-0046 — The user list comes from the configuration roots, and nowhere else

- **Status:** Accepted
- **Date:** 2026-08-08 (decisions 1 to 4 taken 2026-07-11)
- **Related:** [ADR-0031](0031-deployment-config-directory.md) (the configuration
  path-list, and the first-root-wins rule for `users` — the mechanism that makes a
  separate override redundant),
  [ADR-0045](0045-user-avatars.md) (the aspect's two legal forms, and where a
  deployment's avatar files live),
  [ADR-0003](0003-config-and-secrets-via-env-file.md) (`.env`: secrets are read
  before anything else and stay out of the configuration tree),
  [ADR-0022](0022-generated-release-branch.md) (the release branch, which is why a
  consumer upgrades deliberately rather than by surprise)
- **Register:** [`../decisions.md`](../decisions.md)

## Context

**Why the list left the package** *(2026-07-11).* The allowed
users were once read from **inside** the package — `app.py` loaded
`importlib.resources.files("little_sister")/"users.yaml"`, shipped as git-ignored
package data. The repo split turned little-sister into a **library** consumed by a
separate deployment repository, and a deployment must define **its own** users while
the library carries **none**. While the file lived inside the package, a deployment
could not supply its user list without editing installed package files.

**Why one door is now enough** *(2026-08-08).* The answer of 2026-07-11 had two paths:
`LITTLE_SISTER_USERS` if set, otherwise a conventional location beside the process's
other runtime files. Two later records moved the conventional half —
[ADR-0031](0031-deployment-config-directory.md) made it the `users` **aspect** of a
configuration **path-list**, and [ADR-0045](0045-user-avatars.md) gave that aspect a
directory form — and each kept the variable, described as an explicit single-file
override that bypasses layering.

That description is what has quietly stopped being a reason. ADR-0031 gave `users`
alone a combining rule the other aspects do not have: it **does not layer**, and the
first root declaring it **wins whole**. A path-list whose first entry is a root
carrying only a user list therefore *is* a single-file override — same file, same
bypass, no second mechanism:

```
LITTLE_SISTER_CONFIG_DIR=/etc/little-sister/identity:config
```

What the second door costs is not hypothetical. It was a second resolution branch in
the loader, carrying its own rule for where that file's `avatars/` sat; a second
branch in the run scripts' preflight, so the shell and the library could disagree
about which file was authoritative; two error messages that had to teach the variable;
and tests for all of it. And it is a second path into the one decision in this program
that must never be ambiguous — **who may log in**.

The mirror image is the argument's proof. `LITTLE_SISTER_CONFIG` (a single
`settings.yaml`) is **not** redundant and stays: settings **merge per key** across
roots, so a settings root named first *layers over* the base instead of replacing it,
and no spelling of the path-list reproduces "this file, whole". Users are the one
aspect whose combining rule makes an override root exactly equivalent to a file
override — which is why this record retires that one variable and only that one.

## Decision

1. **The user list is deployment-controlled and never packaged.** *(2026-07-11)* The
   library ships no real users; a deployment owns and git-ignores its own list.
2. **The package ships `users.example.yaml` as a template only.** *(2026-07-11)*
3. **Fail fast.** *(2026-07-11)* A resolved list that is not there raises at startup,
   naming the paths it looked at. An instance with no user list is not a running
   instance with a login problem; it is a misconfiguration, and it says so.
4. **The format is unchanged.** *(2026-07-11)* One top-level key per login name, with
   `firstname` / `lastname` / `password` / optional `admin`, plus the optional
   `avatar` [ADR-0045](0045-user-avatars.md) added. This record changes a **location**,
   not an auth mechanism: plaintext passwords and the viewer/admin role model are
   untouched, password hashing stays a later phase, and a pluggable auth provider
   would make this static file merely the *default* provider.
5. **Path resolution is the `users` aspect of the configuration roots — and nothing
   else.** *(2026-08-08)* `LITTLE_SISTER_CONFIG_DIR` (default `config`) is the only
   input: the first root declaring the aspect wins whole, in either legal form
   ([ADR-0031](0031-deployment-config-directory.md),
   [ADR-0045](0045-user-avatars.md)). A deployment that wants one exact file, outside
   the tree its checks live in, gives that file a configuration root of its own and
   names that root **first**. There is no file-shaped entrance beside the aspect, and
   the loader has no idea an environment variable was ever involved.
6. **`LITTLE_SISTER_USERS` is a hard cut — never honored again — and startup
   **refuses** while it is set.** *(2026-08-08)* The name is read in exactly one
   place, the application's startup seam, for exactly one purpose: to refuse, naming
   the move. The run scripts' preflight refuses identically, so `./start.sh` fails
   before it forks a worker. The refusal is **permanent**, not a sunset: it costs a
   few lines, and a sunset would need a later deletion nobody is scheduled to make.

   This is a deliberate departure from how
   [ADR-0031](0031-deployment-config-directory.md) §7 retired
   `LITTLE_SISTER_CHECKS_DIR` — "deliberately never read, not even as a hint", on the
   argument that one `os.environ` read keeps a dead name alive in the code that
   removed it. That argument holds where the removal **announces itself**, and that
   one did: an instance with nowhere to find checks refuses to start on its own. This
   removal does not. A deployment that upgrades with the variable still set in its
   unit file, and a user list also present in its configuration tree, comes up looking
   perfectly healthy while authenticating against **a different list** — silently
   changing who can log in, which is the worst failure this file has available. The
   principle is the same one both records serve: the retired name must never *work*.
   Refusing is not honoring it; it is the opposite, said out loud.

## Consequences

- A deployment reads its users from the same path-list its checks, nodes, settings,
  links and actions already come from — one environment variable for the whole
  configuration tree, which is what makes the tree comprehensible.
- Keeping the login list outside the main tree is still expressible, and is now
  expressed in the mechanism the operator already has to understand. It also composes:
  that root is layered against, not switched between.
- An upgrade that forgets the variable **stops**, with a message naming the move,
  instead of quietly serving a different set of accounts. The cost is a startup
  failure for a deployment that would otherwise have kept running — which is the
  intended trade: a refusal is loud, recoverable in one edit, and cannot be missed.
- The loader shrinks: one resolution path, one avatars rule, one set of error
  messages, and the shell preflight and the library now agree by construction rather
  than by two implementations of the same intent.
- Consumers pin a released tag ([ADR-0022](0022-generated-release-branch.md)) and
  upgrade deliberately, so a compatibility shim would have been dead code from the day
  it shipped — the same reasoning ADR-0031 §7 used for its own clean break.

## Alternatives considered

- **Keep the override** — rejected: it is redundant, and redundancy in the path that
  decides who may log in is not a convenience but a second thing to keep true.
- **Remove it silently, as ADR-0031 §7 removed `LITTLE_SISTER_CHECKS_DIR`** — rejected for the
  reason in decision 6: that removal was self-announcing and this one is not.
- **Keep honoring it for one release, with a deprecation warning** — rejected: a
  warning in a service log is exactly what nobody reads, and it would keep both
  resolution paths alive for the release in which they are most likely to disagree.
- **Sunset the refusal after one release** — rejected: the refusal is three lines and
  a message; scheduling its deletion is more machinery than keeping it.
- **Retire `LITTLE_SISTER_CONFIG` in the same move** — rejected, and instructive:
  settings merge per key, so a prepended settings root layers rather than replaces.
  That override is not redundant, and the symmetry of the two names is not an
  argument — the aspects' combining rules are.
