# ADR-0009 — Per-profile remote metrics scripts (selected by host `profile`)

- **Status:** Accepted
- **Date:** 2026-06-25
- **Related:** [ADR-0007](0007-check-result-branches.md) (the `host-metrics` check reports a branch).
- **Register:** [`../decisions.md`](../decisions.md)

## Context
The `host-metrics` check pipes a shell script to each monitored host and reads its
`key=value` metrics. One script had to run across wildly different userlands:
macOS (bash 3.2, BSD `sysctl` / `vm_stat`, no `/proc`), mainstream Linux (GNU
coreutils, `/proc`), CentOS 6.10 (an old kernel without `MemAvailable`, but real
GNU tools), and **busybox** on a QNAP and on an ASUS/ash router (an `awk` that can
crash on a non-trivial program, a `df` that rejects `-P` and a path argument,
integer-only `sleep`, 32-bit shell arithmetic).

Supporting the weakest host inside one file taxed every host: defensive fallbacks
and parse-time landmines lived in code a capable host never needs. The worst was
structural — a `case` written inside `$( … )` is mis-parsed by bash 3.2, a parse
error that downs the script on *every* host, not just the weak one. Deciding "is
this a dependable `awk`?" at runtime is what produced those traps.

Separately, the script was always piped to `bash -s`, but on the ASUS router
`/bin/bash` is a symlink to busybox (so it already ran as `ash`), and such a host
may have no real bash at all.

## Decision
- Split the metrics script by **userland capability**, not OS name, into three:
  `host-metrics-linux.sh`, `host-metrics-macos.sh`,
  `host-metrics-busybox.sh`. The linux and macos scripts trust `awk` + `df -P`;
  the busybox script keeps the pure-shell `df` fallback and the other paranoid
  handling and is strict POSIX `sh`.
- A host declares its **`profile`** (`linux` | `macos` | `busybox`, default
  `linux`) in its check YAML. The profile selects the default script **and** the
  interpreter it is piped to — `bash` for linux/macos, `sh` for busybox. An
  unknown profile is a config error (no silent fallback).
- Each script **self-guards**: it asserts the OS family it requires via `uname`
  and, on a mismatch, emits `profile_error=…` and stops; the check renders that as
  a **WARN** `ssh` leaf (a config defect, not an outage). The linux script applies
  the same hard guard to a **busybox** userland — detected via busybox `df`'s
  `--help` banner, which `readlink` can't reliably probe on an old router — so a
  busybox host wrongly set to `linux` is caught, not left to a crashing `awk`.

## Consequences
- Each script is smaller and uses the best tools for its world; a capable host no
  longer carries the busybox fallbacks, and a landmine is contained to the file
  that needs it.
- The `key=value` contract must stay identical across the three. A contract test
  (`MetricsScriptTests`) plus the shared output keys pin it; the static
  `case`-inside-`$()` and POSIX-`sh` tests now scan every script.
- A new host needs a one-line `profile` only when it isn't plain Linux; a mis-set
  profile surfaces as a visible WARN with an actionable message rather than
  silently-missing or garbage metrics.
- The `qnap-metrics` check is unchanged (still piped to `bash`); it can gain a profile
  later if a QNAP ever needs `sh`.

## Alternatives considered
- **Keep one script with runtime capability detection.** What we had: every host
  pays the worst case, and a parse error in shared code breaks all hosts at once.
- **Probe the host (`uname`) on a first SSH, then send the right script.** A
  second round-trip every run for something the static per-host config already
  knows.
- **Split, but select by runtime detection rather than config.** The OS *family*
  (and a busybox userland) is detectable, but auto-selecting still wants a probe
  round-trip on first contact; declaring the profile keeps the choice stable and
  testable, with the `uname` and busybox guards as backstops against a wrong
  declaration.
