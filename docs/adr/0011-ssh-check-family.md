# ADR-0011 — SSH check family: transport, connectivity, command, script

- **Status:** Accepted
- **Date:** 2026-06-25
- **Related:** [ADR-0007](0007-check-result-branches.md) (recursive `CheckResult`
  branches), [ADR-0009](0009-per-profile-metrics-scripts.md) (per-profile scripts).
- **Register:** [`../decisions.md`](../decisions.md)

## Context
Everything SSH lives in `checks/ssh.py` — 521 lines, ~2× the next module. One file
holds the SSH transport, the host-metrics check, output parsing, threshold
grading and formatting; `checks/qnap.py` reuses it by importing the transport base
**plus four underscore-private helpers** (`_grade`, `_parse_metrics`, `_oneline`,
`_unavailable`) across the module boundary. So `ssh.py` is really the de-facto
shared SSH-check library, consumed through the back door — and the moment a third
SSH check arrives, it repeats the pattern.

Two signals that the *structure*, not just the size, is wrong:

- **The name lies.** `type: ssh` today runs a disk / memory / CPU / load report. A
  reader expects `ssh` to mean "can I reach the host?", not a metrics dashboard.
- **There is a natural family.** Over one SSH connection you might just **connect**
  (reachability — and the place to flag a non-PQ key exchange),
  run a **remote command** (the over-SSH twin of the local `command` check), or run
  a **local script** on the host and read its output. Metrics and QNAP are
  specialisations of that last one. Every variant shares the same connection
  parameters (host, user, port, identity, options, sudo, timeout); and the script
  variants must also choose **which script + interpreter** — sometimes from config
  (the `profile` → `host-metrics-{linux,macos,busybox}.sh` mapping of ADR-0009),
  sometimes fixed (QNAP), sometimes user-given.

## Decision
Model SSH as **one transport plus a family of checks**, and rename to fit.

**Transport — `SshConnection` (a value object, not a check).** Carries the
connection config and exposes `run(command)` and `run_script(local_path,
interpreter)` → a `RemoteResult` (stdout, stderr, exit, error). Built once from the
shared connection block; the single place connection config is parsed. It also
detects a weak / non-post-quantum key exchange, which the **connecting checks
surface as `WARN`** — `ssh-connect`, `ssh-command`, `ssh-script` and `host-metrics`;
`qnap-metrics`, sharing a host node with `host-metrics`, leaves it to that peer.
This addresses the non-PQ flagging ask; the deterministic `ssh -v` detection
it asks for stays open.

**Checks, by what they do over the connection:**

- **`ssh-connect` — connectivity.** Connect; OK if reachable, ERROR if not (plus the
  connection's KEX warning the connecting checks carry).
- **`ssh-command` — run a remote command.** OK on exit 0; reason = captured output.
  Mirrors the local `command` check.
- **`ssh-script` — run a local script on the host.** Resolve a script **and** its
  interpreter — a fixed path, a user-given `script:`, or a **config-driven choice**
  such as `profile` — pipe it, return the output. Usable directly, and the base for
  the parsing checks below.
- **`host-metrics` — host metrics** (disk / memory / CPU / load). Today's `ssh`
  check, renamed. An `ssh-script` whose script is chosen by `profile` (ADR-0009),
  parsed and graded into a branch (ADR-0007).
- **`qnap-metrics` — NAS hardware** (temperatures, SMART). An `ssh-script` with a
  fixed script, parsed into its own branches.

**Shared pure toolkit — `ssh_metrics` (no I/O).** `parse_metrics` (key=value),
`grade` (value + thresholds → `StatusCode`), formatting (KB, duration),
`unavailable`. A deliberate **public** API used by `host-metrics` and
`qnap-metrics`, replacing the underscore back-door. Pure, so it is unit-testable
without SSH (feed a captured busybox `df` blob, assert the parse).

**Layout — a `checks/ssh/` subpackage:** `transport.py` (`SshConnection`),
`connect.py`, `command.py`, `script.py`, `metrics.py` (the pure toolkit), and the
domain checks `host_metrics.py` and `qnap_metrics.py`.

## Consequences
- The four underscore cross-imports become a deliberate `ssh_metrics` API; a new SSH
  check composes `SshConnection` + the toolkit instead of reaching into `ssh.py`.
- The fragile output-parsing is isolated and directly unit-testable — the part the
  sandbox can't exercise on real shells — with its own `test_ssh*` modules split out
  of the 687-line `test_checks.py`.
- **Breaking config rename:** `type: ssh` (metrics) → `type: host-metrics`, and the new
  `ssh-connect` means connectivity. We **adapt the existing check YAML in the same change** —
  a clean break, no back-compat alias: the committed `checks/` configs and examples,
  and each deployment's own files (we own the deployments).
- `architecture.md` §4.5 and `checks/README.md` are rewritten around the family.
- Behaviour is otherwise preserved — this is structure and naming, not new function.

## Decided
- **Metrics check name:** `host-metrics` (with `qnap-metrics` in parallel).
- **Layout:** a `checks/ssh/` subpackage.
- **Migration:** clean YAML break — adapt the check configs in the same change, no
  back-compat alias.
- **Scope:** build the full family now — `ssh-connect`, `ssh-command`, `ssh-script`,
  `host-metrics`, `qnap-metrics`. `ssh-connect` and `ssh-command` have immediate uses
  (a reachability probe; a remote `df -h`) and `ssh-script` already backs the two
  metrics checks, so nothing is deferred.

## Alternatives considered
- **Only split the helpers (the minimal refactor).** Move the shared pure functions
  to `ssh_metrics.py`, leave `SshCheck` in `ssh.py`. Kills the underscore back-door
  but keeps the misleading `ssh`-means-metrics name and makes no room for the
  connectivity / command variants. A subset of this ADR, not a substitute.
- **One configurable `ssh` check** with a mode (connect / command / script /
  metrics). Fewer types, but a god-check with mutually-exclusive config and the same
  name overload — worse than distinct types.
- **Leave it.** 521 lines works today; rejected because the next SSH check repeats
  the private-import tangle and the name keeps lying.
