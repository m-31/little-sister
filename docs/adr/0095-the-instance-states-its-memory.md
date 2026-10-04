# ADR-0095 — The instance states its memory, and a rise names what was running

- **Status:** Accepted
- **Date:** 2026-09-27
- **Related:** [ADR-0072](0072-the-instance-reports-on-itself.md) (the engine's own
  lines, the `memory` line among them, and that nothing here probes),
  [ADR-0074](0074-this-instance-has-a-name.md) (the question it left open, answered in
  decision 2), [ADR-0076](0076-the-instance-node-is-a-branch.md) (a fact is the
  child's `report`), [ADR-0075](0075-a-check-declares-what-it-costs.md) and
  [ADR-0087](0087-a-check-keeps-its-subjects-readings.md) (the card the figures join,
  and the series file the tick rewrites), [ADR-0044](0044-run-facts-on-the-node.md)
  (the run facts the per-run figures stay out of),
  [ADR-0071](0071-what-a-restart-keeps-is-a-directory-of-files.md) (the state layer's
  interval save), [ADR-0088](0088-a-stop-ends-at-its-save.md) (the stop),
  [ADR-0120](0120-every-stored-time-is-an-instant.md) (decision 9, the clock the log is
  stamped in)
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
had stood, and a line clears when its condition does (ADR-0072 decision 5).

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
