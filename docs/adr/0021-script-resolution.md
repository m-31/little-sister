# ADR-0021 — Script resolution: packaged defaults with an override

- **Status:** Accepted
- **Date:** 2026-07-10
- **Related:** [ADR-0009 — Per-profile metrics scripts](0009-per-profile-metrics-scripts.md),
  [ADR-0011 — SSH check family](0011-ssh-check-family.md),
  [ADR-0015 — Check discovery: a union of config directories](0015-check-discovery-union.md).
- **Register:** [`../decisions.md`](../decisions.md)

## Context
A check that runs a shell script resolves it **relative to its own config file's
directory**. For the SSH-script family, `SshScriptCheck._connection_from_config`
(`checks/ssh/base.py`) takes `config["script"]` or the type's `default_script`,
`expanduser()`s it, and — if relative — joins it to `base_dir` (the YAML's own directory),
erroring if the file is absent. The built-in metrics checks default that script to a
**relative path**: `host-metrics`' `PROFILES` map (`scripts/host-metrics-linux.sh` and
friends, `host_metrics.py`), `qnap-metrics`' `DEFAULT_SCRIPT`, `macos-memory`'s default.
The generic measurement scripts live in the repo's **top-level `checks/scripts/`** —
outside the package, so they are **not** in the wheel.

There is **no shared search path**: the check-directory union
(`LITTLE_SISTER_CHECKS_DIR`, [ADR-0015](0015-check-discovery-union.md)) concatenates the
checks it loads but gives scripts no common home. The built-in defaults resolve today only
because the private YAMLs sit in the same repo as `checks/scripts/`.

The repo split moves the private configs into a separate deployment
repo, which would **strand** the generic scripts they call. And those scripts are
**safety-sensitive** — they must run on macOS's bash 3.2 and a 32-bit busybox router
([ADR-0009](0009-per-profile-metrics-scripts.md)) — so keeping **two divergent copies**
across repos is a real hazard, not a convenience.

## Decision
**Single-source the generic scripts in the library and give built-in defaults a search
path.**

- **Ship the generic scripts as package data.** Move them from the repo's top-level
  `checks/scripts/` into the `little_sister` package (e.g. `little_sister/scripts/`), so
  they ship in the wheel — as `templates/` and `static/` already do.
- **Explicit `script:` is unchanged.** An absolute or `~` path is used as given; a relative
  `script:` resolves against the **config's own directory** (today's behaviour) — so a
  deployment's bespoke scripts keep working exactly as now.
- **A built-in check's *default* script (no `script:` given) resolves against a search
  path, first match wins:**
  1. **`LITTLE_SISTER_SCRIPTS_DIR`** if set (the override / escape hatch),
  2. the **config's own directory** (so a deployment can *shadow* a bundled script by
     dropping a same-named file beside its config),
  3. the **packaged library scripts** (the single-sourced default).
- **Scope:** this governs the check types that take a `script:` (the SSH-script family and
  the metrics checks' defaults). The `command` check runs an arbitrary shell command with
  its `working_dir` as cwd and is **unaffected** — its scripts are deployment-owned.

## Consequences
- A deployment using built-in check types gets the measurement scripts **for free** — just
  `type: host-metrics, profile: linux`, no scripts to carry — while the safety-sensitive
  scripts stay **single-sourced** in the library (no drift).
- The deployment repo holds only its **configs** plus its **own** bespoke scripts.
- A deployment can **shadow** a bundled script (a same-named file beside the config) or
  **relocate** the whole set with `LITTLE_SISTER_SCRIPTS_DIR`.
- The top-level `checks/scripts/` moves into the package; the `PROFILES` / `DEFAULT_SCRIPT`
  defaults and any tests that assumed the top-level path are updated. The default-script
  lookup now checks up to three locations (a minor cost).
- Localised change: the default-script resolution in
  `SshScriptCheck._connection_from_config` and the metrics-check defaults; packaging picks
  up the moved scripts automatically.

## Alternatives considered
- **Vendor (copy) the scripts into each deployment repo** — rejected: duplicates the
  safety-sensitive scripts, and silent divergence is exactly the failure mode the "verify
  on real hosts" concern warns about.
- **Absolute paths in every config** — rejected: not portable across machines / users,
  verbose, and it discards the `profile:` convenience.
- **A required `LITTLE_SISTER_SCRIPTS_DIR`, no packaged default** — rejected: every
  deployment would have to configure it; the packaged default keeps built-ins zero-config.
  Kept as the optional override.
