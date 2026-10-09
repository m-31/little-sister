# ADR-0095 — The instance states its memory, and a rise names what was running

- **Status:** Accepted
- **Date:** 2026-10-10 (accepted 2026-09-27)
- **Related:** [ADR-0072](0072-the-instance-reports-on-itself.md) (the engine's own
  lines, the `memory` line among them, that nothing here probes, and the held record of
  its decision 7), [ADR-0036](0036-addressable-reasons.md) (a pin is on a line's slug),
  [ADR-0074](0074-this-instance-has-a-name.md) (the question it left open, answered in
  decision 2), [ADR-0076](0076-the-instance-node-is-a-branch.md) (a fact is the
  child's `report`), [ADR-0075](0075-a-check-declares-what-it-costs.md) and
  [ADR-0087](0087-a-check-keeps-its-subjects-readings.md) (the card the figures join,
  and the series file the tick rewrites), [ADR-0044](0044-run-facts-on-the-node.md)
  (the run facts the per-run figures stay out of),
  [ADR-0071](0071-what-a-restart-keeps-is-a-directory-of-files.md) (the state layer's
  interval save), [ADR-0088](0088-a-stop-ends-at-its-save.md) (the stop, which is what a
  recycled worker costs), [ADR-0120](0120-every-stored-time-is-an-instant.md) (decision
  9, the clock the log is stamped in),
  [ADR-0001](0001-in-process-threaded-engine.md) (a check runs in the one worker),
  [ADR-0086](0086-a-check-measures-and-grades.md) (the record between a check's two
  halves, which is what would cross a process boundary),
  [ADR-0078](0078-the-unit-is-what-the-engine-releases.md) (decision 6, the scheduler's
  round)
- **Register:** [`../decisions.md`](../decisions.md)

## Context

The engine reads the process's resident size on every tick and says it only as the
`memory` line on `/little-sister/engine`, from 80 % of its limit — half of what the
machine gives the process ([ADR-0072](0072-the-instance-reports-on-itself.md)). On a
laptop that limit is gigabytes, so a process holding a few hundred mebibytes says
nothing at all: no log line carries the figure, and `/system` shows the entries and the
series the process holds but not the process. A deployment's instance on a Mac, with
series kept on its checks, had to be measured from outside, with `memory.sh` sampling
the worker every ten seconds for nine hours: its largest resident size rose in ten steps
of 5 MiB or more over the first ninety minutes, from 140 to 369 MiB, and then did not
move for seven hours, while the size itself swung between 95 and 369 MiB. Nothing the
instance kept could say which run was behind a step.

A second deployment asks the question from the other side. Its instance runs in a
container on a 1 GiB cloud machine and holds about 400 MiB, and its `memory` line went
amber and clear again within minutes. Measured on a Mac at ten-second samples, each run
of the `aws` check it runs every minute gains 25–45 MiB within seconds and gives it back
within forty — after the run has ended. There the process reaches its high-water mark in
its first minutes, and every run after that rises and falls beneath the mark, so nothing
that reads the high-water mark alone can say which check holds what the process holds.

What a platform can say differs, and the difference decides what a figure per run can
be. Linux keeps the size now (`/proc/self/statm`) and the high-water mark beside it
(`getrusage`); on macOS the standard library has the high-water mark alone. The
high-water mark moves only when the process reaches a new high — the first deployment's
steps. The size now falls as well as rises, and what a run still holds when it ends —
the second deployment's question — shows only in it.

The second deployment then showed what becomes of a line graded on the tick's own figure
where a process sits on its limit, past it on one tick and below it on the next.
`/little-sister/engine` changed its status 425 times in a day and a half, two of every
three events the instance wrote, and 380 of those changes were between WARN and ERROR,
on two sentences that named one figure — `resident size 504 MiB, past the limit of 504
MiB` and `resident size 504 MiB, 100 % of the limit of 504 MiB`, each followed by what
the machine gives the process. The `lag` line beside it is written from a held record
([ADR-0072](0072-the-instance-reports-on-itself.md) decision 7: each occurrence kept for
a window after it was seen), as the `series` line is where a sweep has evicted, and this
one was not.

It showed, too, what that line's measure cannot see. The resident size stood between 418
and 519 MiB from the process's first half hour on, and its machine ran out three hours
later, with 29 MiB available of 916: whatever ran out in between, the figure the line
grades did not show it.

And what a run can leave behind was weighed in a probe: garbage that only the cycle
collector frees, and the collector runs on a count of allocations and not on what they
weigh. What thirty runs of the `aws` type build took a process to 419 MiB at its highest
and, with a collection after each, to 150 (`little-sister-aws` ADR-0011).

[ADR-0074](0074-this-instance-has-a-name.md) put the instance's name on `/system` and
left open whether the runtime figures move beside it.

## Decision

### 1. Two figures where the platform has two

`limits.resident_size()` answers the **size now** where the kernel keeps one — Linux's
`/proc/self/statm` — and the **peak**, the high-water mark `getrusage` keeps, on every
platform that has it, raised to the size now where the two, read a moment apart,
disagree. macOS answers with the peak alone, and every surface marks it as the peak. The
`memory` line grades what it graded before: the size now where there is one, the peak
where it is all there is. A line that graded a high-water mark could never clear once it
had stood, and a line clears when its condition does (ADR-0072 decision 5). It is
written from the worst reading of ten minutes and not from the tick's own (decision 6).

### 2. The figures stand in the engine block, and in the engine's report

`/system`'s polled engine block carries the figures as the fourth row of the card that
holds the entries and the series against their limits: the size and its peak, against
the `memory` line's limit and what the machine gives the process. The engine child's
`report` carries them as a fact, rewritten every tick beside the series' — readable by
anyone signed in, on the node where the `memory` line stands when it does, and in the
envelope — and never as a line: below the amber share they claim nothing
([ADR-0076](0076-the-instance-node-is-a-branch.md) decision 1).

This answers what ADR-0074 left open: the runtime figures stay in the polled engine
block, and *This instance* stays what is settled at import. A live figure there would go
stale between page loads or pull the card into the poll, and a resident size is how the
process runs, not what is installed.

### 3. The log carries them every ten minutes

On the first tick past each ten-minute mark of the clock the log is stamped in, which
is the configured zone's (ADR-0120 decision 9), the engine logs one INFO line with the
card's figures — the size and its peak against the limit, what the series hold, and
the tree's entry count:

    engine: memory — resident size 312 MiB, peak 369 MiB, of a limit of 8.0 GiB; the series hold 3.1 MiB, the tree 12,345 entries

On macOS it begins `peak resident size 369 MiB`. The same line comes once at the first
tick, as `engine: memory at the start`, the baseline, and once when the engine stops, as
`engine: memory at the stop` — at the stop, or when a lost lease halts it — so every
process's life in the log is bracketed by its figures and ends on the highest it
reached. Ten minutes is a constant in `limits.py`, not a setting: it is `memory.sh`'s
own background cadence, and about one line in a hundred of a busy log. Aligned to the
clock, the lines of two instances, or of one across a restart, stand at the same
minutes.

### 4. A run's line carries what rose while it ran, and says it is the process's

The engine reads the size and the peak when a run starts and when it ends. Where the
platform has the size now, the run's log line carries its rise across the run — the size
at the end, less the size at the start — and the peak's rise beside it; on macOS, the
peak's alone. Each is said only where it rose by 1 MiB or more, and a fall is never
said: below that a rise is pages, a fall is some other run's memory given back, and the
ten-minute line carries the drift. They stand inside the parentheses beside the elapsed
time — before the reasons, whose truncation cannot reach them:

    check /web: OK (5812 ms; resident +38.2 MiB, peak +12.1 MiB while it ran, beside /hosts/alpha and /nas1) — …

The two answer two questions. The size's rise names what a run still holds when it
ends: a check whose memory is given back only after it has finished shows there on every
run, however long ago the process reached its high. The peak's rise names the run in
flight when the process reached a new high — where a machine's memory runs out first, a
spike freed before the run ended included — and it is the figure a Mac's line can be
compared with.

Both are **process-wide**: whatever allocated or freed while the run was in flight moved
them. So the line says *while it ran*, never *used*, and names every other run that was
in flight at any point of it, five and a count. The same step then stands on each of
their lines, and a reader takes it to the runs it names, never to one of them. Neither
is a run's cost, and nothing may read one as that.

The figures stay in the log. The run facts hold one run
([ADR-0044](0044-run-facts-on-the-node.md)), so the one that mattered would be
overwritten before anyone read it, and carrying them there would move the envelope for
figures that are nothing on most runs.

### 5. The tick is measured the same way

The scheduler tick allocates too — its state save rebuilds every kept file in memory,
the whole of `series.json` among them
([ADR-0087](0087-a-check-keeps-its-subjects-readings.md) decision 9) — and a step it
made would otherwise stand only on the lines of whichever runs were in flight. The
engine reads the size and the peak around each tick, and where the tick raised either by
1 MiB or more it logs a line of its own with the same figures, saying whether the tick
ran the state layer's interval save and naming the runs in flight:

    engine: resident +12.3 MiB, peak +3.0 MiB during the tick, including a state save, beside /web

Web requests are not measured. A step only a request made stands on no line; the
ten-minute line still shows it.

### 6. The `memory` line holds what it saw

A process that sits on its limit is past it on one tick and below it on the next, and a
line graded on the tick's own figure turns ERROR and back every time (Context). So the
engine records every tick's reading that stands at or past the amber share in a held
record of its own ([ADR-0072](0072-the-instance-reports-on-itself.md) decision 7), over
the `lag` line's ten minutes — a constant in `limits.py`, `MEMORY_HOLD_SECONDS` — and
writes the line from the worst reading inside that window: its code, what it was and
when it was read, on the clock every line's time is written on, and beside it what the
size is now:

    resident size 514 MiB at 09:12, past the limit of 504 MiB (now 481 MiB of the 917 MiB the machine gives the process)

The line steps down, ERROR to WARN to nothing, only when the whole window stood below,
so a size that crosses the limit on one tick and not on the next is one event and not
two, and a second crossing inside the window is none. What is graded is decision 1's:
the size now where there is one, the peak where it is all a platform has. A peak is said
without a time and without a size now — a high-water mark has no moment the process can
name and nothing beside it — and since it never falls, the hold changes nothing for it.
One thing follows from holding: where the platform keeps a size now, a tick that could
not read it records nothing. All such a tick has is the high-water mark, which is not
what the process holds, and where that mark is past the limit the one tick, held, would
stand as an ERROR for ten minutes.

The size is compared with the limit in bytes, and where the sentence would read as
though the size were the limit — the two figures written as one, or a size below the
limit that comes to 100 % of it — it says how far apart they are instead: `97.0 KiB past
the limit of 504 MiB`, `1.0 MiB below the limit of 504 MiB`. So a size past its limit
never reads as equal to it, nor one below it, and a peak is said the same way.

A reading is recorded without a log line of its own: it comes every tick, and the log
has the ten-minute line and a run's rise (decisions 3 to 5). The slug stays `memory`, so
a pin on the line holds ([ADR-0036](0036-addressable-reasons.md)), and nothing a
deployment configures moves.

### 7. What the machine has left gets a line of its own

The `memory` line grades what the process holds against a share of what the machine
gives it, and the share is a proxy for what the machine has left: on the second
deployment what the line grades stood where it was while the machine ran out (Context).
So the engine reads `MemAvailable` from `/proc/meminfo` and, under a cgroup with a
memory limit, what the limit leaves, and says the smaller of the two.

What a limit leaves is not the limit less the usage, because the usage counts file cache
that the kernel gives up before the limit ends anything. Under cgroup v1, in a cgroup
limited to 200 MiB, 193 MiB of a usage of 198 were file cache, and a process took 150
MiB more with nothing killed. Under cgroup v2, in one limited to 48 MiB with 32 MiB of a
file in its cache, the limit less the usage said 14.5 to 14.6 MiB, and 46 were taken
before the kernel killed. What had promised them, at 46.5 to 46.6, was the limit less
the usage with the two lists of file pages counted back, `inactive_file` and
`active_file` in `memory.stat`. Neither `file` nor the inactive list alone is that sum:
`file` counts `shmem`, which is not given up, and with the multi-generational LRU
switched off the whole cache stood on the active list. Both were read on Linux, 6.18 and
6.8, on a cache that was clean.

Under no limit there is the one figure, and it is the machine's: the second deployment's
container ran under none when it was read, on cgroup v2, and the `/proc/meminfo` inside
it was the machine's.

The cgroup is the process's own, as `/proc/self/cgroup` names it beneath the mount, and
every cgroup above it to the root of the mount — under cgroup v2, or v1 where the
machine mounts the memory controller there. A container sees its own cgroup at the root
of the mount, and under v1 names the host's path for it, which is no directory there; on
a bare host the process runs in a service's cgroup beneath a slice, and a limit on
either binds it. So a limit counts wherever it is set on that chain and is smaller than
the physical memory: what is left is the least any of them leaves, and the smallest of
them is what the machine gives the process, of which the `memory` line's limit is a
share ([ADR-0072](0072-the-instance-reports-on-itself.md)). The root of the mount alone
had been read for that, which is right in a container and on a bare host is the
machine's own, so a service's limit went unseen. Read on Linux 6.18 with the memory
controller v1's, a process in a cgroup limited to 5.8 GiB on a machine of 7.8 is given
5.8 GiB where the root said nothing; in a cgroup of 48 MiB beneath it the limit
left 36.5 MiB with 24 MiB of a file read into the cache, and after a process beside it
had taken 120 MiB and been ended, its count said one. The count is the process's own
cgroup's, since a slice's counts every service beneath it.

The figure is a fact first — in the engine's report, on `/system` and in the ten-minute
line — and then a line under a slug of its own, held as `memory` is, once a reading on a
deployment says where its threshold stands: 29 MiB was where that machine ended, not
where its trouble began. What is left is what that line grades, and nothing beside it,
because it is what moves. On the second deployment's instance, read every minute for an
hour once its container ran under a limit of 512 MiB, `MemAvailable` fell from 197 MiB
to 58 in fifty-one minutes, while the process grew from 289 MiB to 445; a minute later
it stood at 490, with that process gone — ended at the limit, to judge by its size and
the moment — and the next one starting. The `memory` line stays what it is, on every
platform, so a pin on it keeps its meaning; whether it stays beside the new line is
decided when that one has stood. Where a platform has neither file, as on macOS, there
is no figure and no line.

Two figures stand beside it as facts, in the same three places, and neither is graded.

**How long the machine stalled on memory**: the share of the last ten minutes in which
the kernel counted some task stalled, from two readings of the counter `total` in
`/proc/pressure/memory` — the machine's figure, which a process in a container reads as
well. The kernel's own averages are not that share: between two readings of the
deployment's instance before its limit, at 129 MiB available and some twenty-five
minutes later at 50, the counter rose by 27 seconds, about 1.8 % of that time, while the
average over ten seconds read 2.5 % at the first and 0.9 % at the second. And the share
is no measure to grade. In the hour above it rose from 1.3 % of ten minutes, with 172
MiB available, to 1.7 % with 58; by the minute it was 5.5 % in the one in which the
process went, and 0.4 to 1.0 % in the six after, with 261 MiB and more available: a
floor that is no shortage, and above it a range too narrow for a threshold.

**How often the kernel has ended a process of this cgroup**, where the process runs
under a memory limit: `oom_kill` in `memory.events`, or in `memory.oom_control` under
cgroup v1. A worker ended that way leaves nothing in the tree: the next begins with
every line clear, and no stop was reached that could have said so (decision 9). The
count is the one trace. It stays with the container, and a process that begins in it
reads it.

In the three places, with a deployment's figures under a limit:

    the machine has 41 MiB left, stalled on memory for 1.7 % of the last 10m, and the kernel has ended no process of this cgroup

— a fact of its own in the engine's report, after the process's, where the second part is
joined as `; it stalled`; on `/system` the card's fifth row, *Left on the machine*, the
figure and beside it the other two; and in the ten-minute line, after the process's
figures. The share is of the ten minutes between two of the log's lines, by the
engine's clock; a process younger than that says the share of what it has read and
names it — `of the last 4m` — and at its first tick, with one reading, says none. Under
a limit a count of none is said as well: the count stays with the cgroup, so in a
process that began anew, none says that the one before it was not ended so. Where a
part cannot be read it is left out, and the rest stands.

The fact is built; the line waits for a deployment's reading of where its threshold
stands.

### 8. The engine collects after a run that rose, at a pace its own cost sets

After a run across which the process rose by `RISE_LOGGED` or more — the 1 MiB from
which a run's line says a rise (decision 4) — the engine calls the cycle collector, and
never for more than a hundredth of the time: a collection that took *p* is followed by
none for a hundred times *p*, a constant in `limits.py`, `COLLECTION_SPACING`, and none
starts while one runs, whichever run asked first. What it is for is the garbage a run
leaves that nothing else frees, which took a process to 419 MiB (Context).

The pace is there because a collection stops every thread while it runs, and for longer
the more is alive: 15 to 20 ms where the `aws` type builds its sessions on one loader,
109 to 124 ms where it did not, and 230 to 255 ms over 533 MiB that were all alive, read
on Linux on arm64 with CPython 3.14.6. It is built whatever a deployment's lines say
once a type has shed its weight at the source, since it is the fence for the type nobody
has measured yet. On macOS a run's rise is the peak's (decision 4), so there a
collection follows a run that raised the high-water mark. On Linux it is the size's: a
peak that rose while the size did not is a spike the run gave back before it ended, and
asks for none.

The run's own line says it, after the rise and inside the parentheses:

    check /aws: OK (5812 ms; resident +38.2 MiB while it ran; collected after it in 18 ms, resident −31.0 MiB)

— what the collection took, and the size's fall across it, said from `RISE_LOGGED` as a
rise is and a rise never; on macOS, which keeps no size now, the time alone. The line is
written once the collection is done, so that it can say it, a fraction of a second
later; a run that rose and that the pace leaves uncollected says nothing of it. Read on
Linux on arm64 with CPython 3.14.6, a check that left some 58 MiB behind in reference
cycles was followed by a collection of 4 ms that gave back 58.2 MiB, and its next two
runs, inside the 0.4 s after it, by none.

### 9. The library recycles no worker of its own, and a run in a process of its own waits for the scheduler

A check runs in the one worker's thread pool
([ADR-0001](0001-in-process-threaded-engine.md)), so nothing ends with a run, and
decision 8 is the fence the library builds. A worker that ends and is booted again gives
back whatever the process had accumulated, at the price of a stop
([ADR-0088](0088-a-stop-ends-at-its-save.md)): the runs in flight, every check at once
on the next start, and what the checks held in memory. A deployment that wants that has
it already. gunicorn's `--max-requests` ends a worker after that many requests, and
under the library's hooks the stop is reached, the next worker takes the lease and no
request is refused — the one across the change was answered after 0.4 to 0.8 s, on a
configuration with no package and no keeper. A container's memory limit is the hard
form, the kernel's KILL: no stop and so no save, and a worker killed that way was
followed by one running an engine 0.4 s later, on the lease the dead one left.

What the library could add is a trigger, and the two at hand read the process's own
size: by the second deployment's figures, the held line standing ERROR for its window
would have restarted its instance about every hour, and a whole window past the limit
would not have come before its machine ran out. Neither is what ended it. A recycle on
what the machine has left (decision 7) stays open until that figure has been read on a
deployment.

A run in a process of its own is the one fence that bounds a run's damage to the run —
at 44 to 45 MiB and 0.3 s of imports before a run of that type begins, records that
cross a process boundary ([ADR-0086](0086-a-check-measures-and-grades.md)), and what a
check holds in memory left behind with every run — and it belongs with the scheduler's
round ([ADR-0078](0078-the-unit-is-what-the-engine-releases.md) decision 6), not before
it.

## Consequences

- A reader of the log can say which runs were in flight when the size or the peak rose,
  and what a run still held when it ended, from the instance's own log, on every
  deployment — a container's included, where `memory.sh` does not run.
- On macOS the figures go quiet once the process has reached its high: a step beneath it
  moves no peak, and the peak is all macOS reports. That is the platform's limit, stated
  rather than worked around.
- The engine child's `report` changes every tick, as it already did with the series.
- A few reads of the size and the peak per run and per tick — the process asking the
  kernel about itself, which is not the probe ADR-0072 decision 2 forbids.
- `StateLayer.tick()` says whether it ran the interval save, so the tick's line can.
- `Resident` carries the size now and the peak, where it carried one figure and a flag.
  It is not on the promised surface (`architecture.md` §11).
- The `memory` line stands for ten minutes after the size has fallen, saying beside the
  worst reading what the size is now, and the events of `/little-sister/engine` carry
  one change where a process crosses its limit and one when it has stayed below it for
  the window, where there was one for every crossing.
- Where the platform keeps a size now, a tick that cannot read it is not graded: the
  line keeps what it held and names no size now for that tick.
- A pin on `memory` holds, and `memory_share` configures what it configured.
- What the machine has left stands beside the process's figures in the report, on
  `/system` and in the ten-minute line, with how long the machine stalled on memory and,
  under a limit, how often the kernel has ended a process of the cgroup.
- Its line is decided here and not built: until it is, the share is the only measure
  graded.
- A run that rose is followed by a collection a hundredth of the time at most, and its
  line, written once the collection is done, says what that took and gave back.
- A worker the kernel ends under a memory limit is counted where the instance reads it:
  the next one's report and ten-minute line say how many the cgroup has had.
- On a bare host whose service runs under a memory limit of its own, or under a slice's,
  that limit is what the machine gives the process and the `memory` line's limit a share
  of it, as in a container.
- The files of `/proc` and the cgroups' are read every tick: some fifty microseconds on
  the device VM, and up to four hundred on a machine where each read of them costs ten
  to forty. Ten minutes of the stall counter's readings are kept, one a tick.
- A deployment that wants its worker recycled does it with its server or its container;
  the library has no switch for it.

## Alternatives considered

- **One figure per platform, as before, with the peak read on Linux for the per-run rise
  only.** The smallest change, and `/system` and the log would then show a size on Linux
  and a high-water mark on a Mac, so a reader comparing a container's log with a Mac's
  would compare two different quantities.
- **The peak's rise alone, on both platforms.** One figure with one meaning everywhere —
  and silent on the second deployment on every run after its first minutes, where the
  question is what a run still holds.
- **The size's rise alone on Linux**, the peak's on macOS, following what decision 1
  grades. One figure a line, and a spike a run frees before it ends shows nowhere,
  though that is the moment memory runs out.
- **The size now on macOS too**, through `ctypes` into the kernel's task information.
  The platforms would match, in code only a Mac can exercise — and on macOS the resident
  size is not the figure a reader knows: Activity Monitor shows the physical footprint.
- **The figures beside the instance's name**, answering ADR-0074 the other way. Rejected
  in decision 2.
- **The log line with the state layer's save**, every `state_interval`: sixty lines an
  hour at the default, and a deployment that tunes its saves would retune its memory log
  without knowing it. **Hourly**: the growth of a night becomes two points.
- **The per-run figures in the run facts** as well. Rejected in decision 4.
- **A figure on every run's line**, a rise of nothing and a fall included: noise on
  nearly every line.
- **The state save's share of the tick's rise.** With two figures it is two shares;
  whether the tick ran the save says what a reader needs.
- **Subtracting the tick's share from a run's**, so that each rise is put on one unit.
  It would claim an attribution the process cannot make — a rise has no owner — and the
  overlap already says what can be said.
- **The line graded on the tick's own figure**, as it first was. On a process that sits
  on its limit that is two events for every crossing: the second deployment's 425
  changes.
- **`format_size` carrying the difference** between a size and its limit, with a digit
  more where the two would be written alike. The same function writes the figures on
  `/system` and in the log, and one figure spelled two ways is two figures to a reader
  comparing them; the sentence says the distance instead.
- **A tick without a size now graded on the peak.** Graded and held, one such tick is an
  ERROR for ten minutes over a process that may hold a fraction of its high-water mark.
- **What the machine has left as the one line's measure.** The number that matters, and
  then no longer whose memory it is, absent on macOS — where the line would be gone —
  with a pin on `memory` holding something other than it was set for, and `memory_share`
  with nothing left to configure.
- **The one line left alone.** Free, and blind to whatever else holds the machine's
  memory.
- **What is left as the only fact.** The least to build. A worker the kernel ends then
  leaves no trace an instance can state, and nothing says whether a machine with little
  left is stalling or only full.
- **The kernel's stall figure as what the line grades.** It is the kernel's own word for
  trouble, and in an hour read by the minute it kept to 1.1 to 2.1 % from 197 MiB
  available down to 58 and to 0.4 to 1.0 % with some 300: a threshold on it would stand
  inside what it does anyway.
- **The kernel's averages over ten, sixty and three hundred seconds** in place of the
  counter. Nothing to subtract, and windows that are not the log's ten minutes, the
  shortest of which read less with 50 MiB left than with 129.
- **The cgroup at the root of the mount alone**, as the limit had been read. Right in a
  container, which sees its own cgroup there, and blind on a bare host, where a
  service's cgroup and its limit stand beneath the root.
- **The share said only once ten minutes have been read.** Simpler to read, and a
  process's first lines would carry none — the minutes after a worker began anew.
- **A count said only from one.** A shorter line, and nothing in a process that began
  anew would say whether the one before it was ended by the kernel.
- **A collection that says nothing**: a fence nobody could see fire, or see what it
  bought. **A line of its own for each**: the easiest to search for, and on a busy tree
  one every few seconds. **A count and the pause in the ten-minute line**: the least
  noise, and no collection tied to the run that asked for it.
- **No collection**, which is how a process came to 419 MiB. **A collection after every
  run that rose**, unpaced: right at one such run in two minutes and wrong on a large
  tree with many runs a minute, since the pause grows with what is alive. **A collection
  only where a deployment's lines still stand above the amber share** once its type has
  shed its weight: a reading of the one type that was measured.
- **The engine recycling its own worker when the held line has stood ERROR for its
  window.** Rejected in decision 9: a restart by the clock, on the deployment it was
  meant for.
- **A run in a process of its own, now.** Its price is in decision 9, and it is the
  scheduler's round that pays it.
