# ADR-0090 — One state directory, one writer: a lease file with a heartbeat, and a kernel lock for the machine the kernel sees

- **Status:** Accepted
- **Date:** 2026-09-26
- **Related:** [ADR-0071](0071-what-a-restart-keeps-is-a-directory-of-files.md) (the
  directory this gives one writer), [ADR-0074](0074-this-instance-has-a-name.md) (the
  mark the lease is written in), [ADR-0077](0077-authority-follows-the-lease.md) and
  `little-sister-aws` ADR-0004 (the store's lease, whose shape this takes),
  [ADR-0073](0073-a-readiness-answer-beside-health.md) (the readiness node, where a lost
  lease is said), [ADR-0088](0088-a-stop-ends-at-its-save.md) (the save that releases
  it), [ADR-0091](0091-an-import-is-not-an-instance.md) (the start that takes it)
- **Register:** [`../decisions.md`](../decisions.md)

## Context

[ADR-0071](0071-what-a-restart-keeps-is-a-directory-of-files.md) made `var/state/` what a
restart keeps, and said of itself that nothing in it is designed for a second process.
One deployment met two. An old worker that outlived its stop saved over the files a new
instance had just restored — [ADR-0088](0088-a-stop-ends-at-its-save.md) ends that one.
And a process that was not the instance started an engine and recorded a transition for
every node into the running instance's event log — all ten checks to ERROR, for secrets
it could not resolve and credentials it did not have — which the next start restored as
that instance's history. Which process it was, and on which machine, was never
established: its log went elsewhere.

There are two machines in that picture. The Mac runs the instance; the device VM that
agents work in reaches the same checkout through a FUSE mount. **A kernel lock does not
cross that mount**: a `flock` or a POSIX lock taken on the VM holds between the VM's own
processes (measured on a connected folder) and is the VM kernel's alone, and a lock the
Mac takes is the Mac kernel's. Whatever keeps two writers apart has to be something both
kernels see, and that is a file. Measured from the VM on the same folder: creating a file
that already exists with `O_EXCL` is refused, and the two clocks differed by between
0.3 s and about a second, the Mac's ahead, against the running instance's log writes as
the VM saw them; after the Mac has slept, not measured.

The family already runs one lease. The S3 keeper holds one object per prefix
(`little-sister-aws` ADR-0004): its holder writes it every interval, with its mark and a
time to live it sets itself; anybody else only reads it; it is taken with a
compare-and-swap and released with a heartbeat of zero; and a holder whose heartbeat is
refused stops writing before it writes. That lease keeps two instances apart on one
store. A directory's two writers are two processes of one checkout, and the same shape
serves them with a file for the object.

## Decision

1. **A lease file beside the directory.** `var/state.lease` names its holder: the
   instance mark ([ADR-0074](0074-this-instance-has-a-name.md)) and, as fields of their
   own because the mark is never parsed, its host, its pid and the kernel it runs under;
   the `ttl_seconds` it sets itself; how it came by the lease — `free`, `released`,
   `lapsed` or `gone` — and, in a field of its own, whether it still holds it: `held`,
   or `released` once it has let it go; and the last four claims, each with when and how
   it was taken. Only the second of those two fields decides anything. A graceful
   restart takes a released lease, and a holder that came by its lease that way holds it
   and beats like any other; read as a release, it would be a live lease that another
   kernel takes at once. Beside the directory rather than in it, so that no keeper
   mirrors it and no restore reads it, and as fixed as the directory
   ([ADR-0071](0071-what-a-restart-keeps-is-a-directory-of-files.md) decision 2). It is
   written through a temporary name and `os.replace`, so a reader sees one lease or the
   next and never half of one.
2. **A heartbeat, on a thread of its own.** The holder rewrites the lease every 10 s,
   from a thread of its own so that a long tick never makes a live holder look dead. A
   lease whose last beat is older than its `ttl_seconds` — three beats, 30 s — has
   lapsed. The age is the file's modification time against the reader's clock; the two
   clocks that meet here were a second apart at most, and a lapse of thirty absorbs that.
3. **A kernel lock for the machine the kernel sees.** The holder also holds an
   exclusive `flock` for its whole life on `var/state.lock`, an empty file beside the
   lease that is never replaced, and the kernel lets go of it however the process ends.
   - **Under the same kernel, the lock decides.** A process that can take it knows that
     no process under this kernel holds the lease, so a lease its kernel wrote belongs to
     a holder that is gone, whatever its heartbeat says, and it takes over at once.
   - **Under another kernel, the heartbeat decides.** A fresh beat is a live holder, and
     a lapsed one is watched for one more beat before it is taken, so that a holder that
     has just woken — a Mac back from sleep — keeps it.
   - **The kernel is recognized by its boot identity**: Linux's `boot_id`, which the
     containers on one host share, and the macOS boot session, `kern.bootsessionuuid`;
     the host name where neither answers.
4. **Taken at the start, before anything reads the directory; released by the final
   save.** The server's start takes the lease before the restore
   ([ADR-0091](0091-an-import-is-not-an-instance.md)), and the stop's one save releases
   it ([ADR-0088](0088-a-stop-ends-at-its-save.md) decision 3): the lease's state
   rewritten as released — how it was taken stays what it was — then the kernel lock let
   go. A release is a write rather than a delete, so it needs no permission that a write
   does not. Only a lease its holder released reads as released.
5. **A process that cannot take the lease refuses rather than standing by.** It restores
   nothing, runs no checks and saves nothing. Two processes on one directory are never a
   rollout, the way two instances on one store are, and a standby would still run every
   check against the same sources on the same tokens. A refused start halts the server
   with the holder named ([ADR-0091](0091-an-import-is-not-an-instance.md) decision 3).
6. **A start that finds the directory held refuses rather than waits.** The run scripts
   now wait for the old instance themselves ([ADR-0088](0088-a-stop-ends-at-its-save.md)
   decision 9), so whatever still holds the directory when a start comes is somebody
   else, and saying whose it is is worth more than waiting for it.
7. **A holder checks that the lease is still its own before every save, and one that
   has lost it stops.** A holder whose lease was taken — across kernels, while it was not
   beating — stops writing before it writes, and its engine stops with it: the scheduler
   ends, the runs in flight are abandoned as at a stop and what they started is ended,
   and no check runs again in that process. One that went on would spend the same tokens
   on the same sources beside the new holder, which is what refusing rather than standing
   by (decision 5) is for. There is no save and no release, since the directory is the
   new holder's. The instance goes on serving the last view it had, and says why where it
   is watched and not only in the log: the readiness node carries an ERROR line, *this
   instance runs no more checks and saves nothing*, naming who holds the directory now.
   A restart is the way back, and it meets the rules above.
8. **A takeover says so.** A takeover across kernels logs a WARNING naming the holder it
   replaced and when that holder last beat; a takeover under the same kernel, of a
   holder that is gone, logs an INFO line naming it. Both are among the lease's claims,
   each of which says how it was taken.

## Consequences

- [ADR-0071](0071-what-a-restart-keeps-is-a-directory-of-files.md)'s *nothing here is
  designed for a second process* stops being true, and it is updated; the readiness
  node's third line updates [ADR-0073](0073-a-readiness-answer-beside-health.md).
- The S3 keeper's lease is unchanged, and the two are independent: this one keeps two
  processes of one checkout apart, the store's keeps two instances apart across
  machines. An instance in a container holds an uncontested lease on its own directory.
- A start right after a crash or a KILL on the same machine never waits. A start on the
  device VM beside a live instance on the Mac is refused and says whose the directory is.
- A holder that loses the lease is its last view: its engine's beat goes stale, its
  readiness line says why, and it spends nothing more on any source.
- **What the lease cannot stop is a process that takes a free directory** — an import on
  the device VM while the instance is stopped. [ADR-0091](0091-an-import-is-not-an-instance.md)
  closes that: an import takes no lease, because an import is not an instance.

## Alternatives considered

- **A lease file alone.** Seen wherever the file is, and a holder killed on its own
  machine blocks a restart there until its lease lapses, while a holder that slept past
  the lapse looks dead to every other process — its own machine's included.
- **A kernel lock alone.** Released however the process ends, and invisible across the
  device VM's mount, which is where the question came from.
- **A marker without a heartbeat**, written at the start and removed at the stop. A
  holder that dies leaves it behind, and from another machine nothing but a person can
  tell it is stale — the latch `little-sister-aws` ADR-0004's first shape was rewritten
  to leave.
- **A standby**, the S3 keeper's answer: right for two instances during a rollout, and
  here a second engine reading every source on the same tokens.
- **No lock**: leave a second server started by hand, and a process on the device VM, to
  the rule against running them in a deployment's checkout.

