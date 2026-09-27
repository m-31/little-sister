# ADR-0089 — A process a check starts ends with it: one promised function, and a remote command that ends with its connection

- **Status:** Accepted
- **Date:** 2026-09-26
- **Related:** [ADR-0088](0088-a-stop-ends-at-its-save.md) (the stop that ends what a
  run started), [ADR-0058](0058-transport-policy-vocabulary.md) (the transport policy,
  whose `Deadline` bounds a process as it bounds a request),
  [ADR-0049](0049-the-check-authoring-surface.md) (what a check may import, which this
  adds to), [ADR-0086](0086-a-check-measures-and-grades.md) (the measurement a run's
  outcome becomes), `little-sister-aws` ADR-0001 (the package whose login is a process)
- **Register:** [`../decisions.md`](../decisions.md)

## Context

A check reaches out two ways. A request goes through `little_sister.fetch`, promised with
the transport policy beside it ([ADR-0058](0058-transport-policy-vocabulary.md)), which
settles its timeout, its body cap and how it fails. A process goes through nothing
promised: each caller starts its own, and each has answered the same questions
differently.

Two of those answers leave processes behind, and a stop that abandons a run
([ADR-0088](0088-a-stop-ends-at-its-save.md)) would inherit both.

- **The `command` type's own timeout ends the shell and not what the shell started.**
  It runs a string command through `subprocess.run(shell=True, timeout=…)`, which kills
  the child it started: after a one-second timeout of `sleep 41; echo done`, the `sleep`
  was still running, its parent now `init`. A run's timeout has left processes behind
  since the type was written, stop or no stop.
- **Ending the `ssh` client hangs up nothing on the remote host.** The type runs the
  local client without a terminal, and OpenSSH starts such a command as a session leader
  in a process group of its own; with the client's group killed, the remote command ran
  on under `init` until it finished or wrote into the closed channel (measured with
  OpenSSH 9.6p1 against a local `sshd`).

And a package starts processes too: `little-sister-aws` runs `aws sso login` in one
place, reached from its check's run, from its secret references and from a deployment's
own check — a login that may wait minutes for a person at a browser, which a stop has no
way to end today.

## Decision

1. **`little_sister.process` is promised: `fetch`'s counterpart for a process.**
   `run(argv, *, timeout, deadline=None, max_bytes=…, env=None, cwd=None, send=b"",
   hang_up=False)` runs one process to its end and answers a `Finished`:
   - **An argument vector, never a guess about a shell.** A shell command is
     `["/bin/sh", "-c", command]`, said by the caller.
   - **A session and a process group of its own, and `/dev/null` for stdin** — or the
     bytes `send` names, written while the output is read and followed by the end of
     stdin. With `hang_up=True`, stdin is held open for the rest of the run instead,
     after whatever was sent, and closed when the run ends, which is what an `ssh`
     client carries to the remote side as its connection closing.
   - **Bounded by `timeout`**, clamped to what the run's `Deadline` has left, the way
     `fetch` clamps a socket timeout.
   - **Both streams read by the function**, each up to `max_bytes` — 1 MiB by default —
     and the rest read and dropped, so a child never blocks on a full pipe.
   - **The group ends at the bound and at the stop**: TERM, a grace of 2 s, then KILL, to
     the whole group, so a shell's children go with the shell.
   - **The answer is a fact**: the exit status (or the signal that ended it), both
     streams, **how the process ended** — `Ended.EXITED`, `Ended.BOUND` or `Ended.STOP` —
     and **whether either stream was cut at the cap**, so a check reports a truncated or
     ended run as what it was.
   - **It raises only where the command could not start** — `NotStarted`, with the
     `OSError` as its cause — as `fetch` raises only where no status came back.
   - **POSIX only**, and the module says so.

   The four names — `Ended`, `Finished`, `NotStarted`, `run` — join the promised surface
   (`architecture.md` §11). Adding a name does not move the epoch.
2. **The stop reaches every group the function started.** The module keeps the groups
   that are running, and the engine's stop ends them — TERM, the grace, KILL — before its
   save ([ADR-0088](0088-a-stop-ends-at-its-save.md) decision 3).
3. **The library's own `command` and `ssh` are its first users**, so a run's own timeout
   no longer leaves processes behind either: a `command` check's shell children end with
   its bound, and so does an `ssh` run's remote command. That was a defect of its own,
   and the CHANGELOG says it is fixed.
4. **An `ssh` run ends its remote command through a remote wrapper**, without a terminal.
   A few lines of POSIX `sh`, sent as the remote command, keep the connection's stdin as
   a hang-up line: a watcher reads it, and when the connection closes it sends TERM to
   the command's group and, after a short grace, KILL; at a normal end it sends the same
   to whatever the command left behind. Four rules hold for it:
   - **It signals only a group it leads or one it gave the command.** It reads its own
     group from `/proc/$$/stat` where there is one and from `ps -o pgid=` where there is
     not (macOS), and where neither answers it takes itself to lead none. Where it leads
     its group, as OpenSSH starts a command, the command runs in that group. Where it
     does not, as Dropbear starts one, `setsid` — util-linux's, or BusyBox's applet —
     gives the command a group of its own, and that is the group signaled. Where the
     host has no `setsid` either, the wrapper ends only the one process it started and
     says so on the run's stderr. A group it does not lead is never signaled: under
     Dropbear it is the daemon's, and a signal to it would end the server and every
     session on it.
   - **The command's own stdin is `/dev/null`**, and the hang-up line is none of its
     descriptors, so nothing it runs can read the hang-up line.
   - **A script travels on stdin, ahead of the hang-up line.** `run_script` sends a line
     with the script's length in lines and then the script, which begins with a `set --`
     carrying its arguments. The wrapper reads that many lines — `sh`'s `read` takes a
     pipe a byte at a time, so nothing past them is read — and pipes them to the
     command. A length in lines rather than bytes, because `sh` alone cannot read a
     given number of bytes.
   - **The command line carries the wrapper and the command, and nothing else.** The
     wrapper travels without its comments and its indentation, and holds no single
     quote, which the quoting would turn into five bytes: 879 bytes, and 924 with the
     longest command the library builds, `sudo -n bash -s`. A test holds every command
     the library builds within **1,024 bytes**, which even Dropbear 2012.55 takes: its
     `sysoptions.h` lets a string be at most 1,400 bytes (`MAX_STRING_LEN`) and refuses
     an exec request whose command is over 1,024 (`MAX_CMD_LEN`).

   Measured against a local `sshd`, OpenSSH 9.6p1: in dash, bash and BusyBox `sh`, with
   the client's group killed the remote command and its background child were gone; at a
   normal end the exit status, stdout and stderr were the command's own, a background
   child it left was ended, and the run took 0.22 s; and `sudo -n sleep` ended as well,
   sudo 1.9.15p5 relaying the TERM, where before it ran on.

   **Measured on a router a deployment reads, Dropbear 2020.81** with BusyBox 1.24.1's
   `ash`, every process running as the login user. The command's shell leads neither its
   group nor its session: `echo $$; cat /proc/$$/stat` printed `4667`, then
   `4667 (sh) S 4666 1300 1300 0 -1 …` — group and session 1300, the daemon's. Its
   source says why: `svr-main.c` guards each connection's `setsid()` with
   `#ifndef DEBUG_NOFORK`, and `debug.h` defines `DEBUG_NOFORK` as 0, so the call is
   never compiled and every connection stays in the daemon's session. (Dropbear 2012.55
   leaves `DEBUG_NOFORK` undefined and gives each connection a session, which a
   command's shell sits in without leading it.) The first rule is what keeps a run from
   ending the server. Its `sysoptions.h` defines `MAX_CMD_LEN` as 9,000 and
   `MAX_STRING_LEN` as `MAX(MAX_CMD_LEN, 2400)`, and a longer string makes the server
   process exit, which the client sees as the connection closed by the remote host:
   `true` and 8,900 bytes more ran, 9,100 more closed the connection (exit 255). The
   router's BusyBox script is 10,593 bytes, and this decision's first form, which
   carried the script in the command line, failed there on every run.

   **BusyBox 1.24.1's `ash` is the oldest shell this names.** It has no `command`
   builtin, its `ps` has no `-o`, and it runs the last command of `sh -c` as a child
   rather than in its own place. Run against a build of it, with the daemon's group
   stood in for by a shell that leads it: the BusyBox script arrived whole and ran in
   1.03 s, a second of it its own `sleep 1`; killed during that sleep, its whole group
   was gone within 0.3 s with `setsid`, and without `setsid` the login shell ended at
   once and the script under it within a second. The watcher is the last of a run on the
   host, for the two seconds before its KILL. A remote host needs `sh`, `cat` and
   `kill`, and `setsid` where its server gives a command no group of its own.
5. **A package's process goes through the same function.** `little-sister-aws`'s
   `run_sso_login` starts `aws sso login` through `run`, in the library release that
   brings it and before that package's own release. The AWS CLI prints its URL — with a
   code in the device flow — on stdout, opens the browser itself and reads nothing from
   stdin (aws-cli v2's source), so a group of its own and `/dev/null` for stdin change
   nothing a login needs as far as the source can say; that the browser still opens from
   a process in a session of its own is checked on a Mac, by hand, before the move. The
   function answers with the streams when the process has ended, and gives no line by
   line: a login on a server, where no browser opens, reaches nobody today and will reach
   nobody after the move, and a callback that let it log its URL while it waits is left
   out until somebody needs it.

## Consequences

- A check author who starts a process calls `run`, and the group, the bound, both
  streams and the stop are the library's. What a caller still decides is its argument
  vector, its bound and what a status means to it.
- An abandoned run never leaves a process behind, and neither does a run's own timeout.
- The `ssh` type's command line changes shape — it carries the wrapper and the command,
  and the script travels on stdin ahead of the hang-up line — and a remote host needs
  `sh`, `cat` and `kill`, which every host the family reads has. Where the server keeps
  a command in its own group and the host has no `setsid`, a run's command ends with
  its connection and what it started does not.

## Alternatives considered

- **A registration only**: a package starts its own process in a group of its own and
  hands it to the engine to end. A smaller promise, and every package solves the group,
  the bound and the read loop again — the solving that left the `command` type's timeout
  with processes behind.
- **Nothing promised**: the stop ends what the library started, and a package's process
  may outlive it.
- **A sweep at the stop**: the engine finds the worker's children and ends them, whoever
  started them. A process scan per platform, blind to what a shell left under `init` and
  to a daemon in a session of its own, and no help to a run's own timeout.
- **A terminal for `ssh` (`-tt`)**: the remote command is hung up when the connection
  goes, and the run changes shape — stdout and stderr arrive as one stream with CRLF
  endings, a script sent on stdin is echoed back and turns `sh -s` interactive, and a line
  longer than 4,096 characters never arrives, so the run hangs to its timeout (measured).
- **A second connection at the stop**, ending a remote group recorded at the start: a
  round trip per host inside the stop, failing exactly when the host cannot be reached.
- **A remote `timeout`**: bounds the command rather than ending it, and macOS has none by
  default.
- **A script in the command line, under a stated bound** — this decision's first form:
  at most 131,071 bytes of command line, what one argument may carry to a Linux side
  (measured: 131,072 and the local `ssh` could not start, `Argument list too long`).
  The bound that mattered was the server's — Dropbear closes the connection over 9,000
  bytes of command and Dropbear 2012.55 refuses one over 1,024 — and the BusyBox script
  alone is over it.
- **A length in bytes**: exact for any script, and `sh` cannot read a given number of
  bytes by itself — `dd bs=1 count=N` would, adding `dd` to what a host needs, with
  BSD's `count=0` meaning everything there is.
- **`setsid` everywhere**, whether or not the wrapper leads its group: one path instead
  of two, and a Mac, which has no `setsid`, would end only its command where OpenSSH
  already gives it a group to end.

