# ADR-0132 — A branch keeps the period of what it shows beside the log

- **Status:** Accepted
- **Date:** 2026-10-25 (accepted 2026-10-24)
- **Related:** [ADR-0002](0002-rlock-snapshot-synchronization.md) (the one lock, which
  a run's store now holds whole),
  [ADR-0123](0123-a-node-says-one-status-wherever-it-is-read.md) (one
  status wherever a node is read; its decision 4, no row for a branch, which stands,
  and its decision 3 and its envelope, which this amends),
  [ADR-0110](0110-what-every-node-last-showed-is-kept-beside-the-log.md) (the entry
  beside the log, whose decision 5 a branch's entry doubles),
  [ADR-0107](0107-an-event-is-a-change-of-what-a-node-shows.md) (what an event is, which
  stays), [ADR-0099](0099-a-status-that-still-holds-says-since-when.md) (since when a
  status holds, and its bounds), [ADR-0094](0094-a-restart-is-no-transition.md) (a
  restart is no transition, carried a level up),
  [ADR-0039](0039-status-rollup-semantics.md) (the roll-up a branch's period is of),
  [ADR-0005](0005-dashboard-freshness-and-self-monitoring.md) and
  [ADR-0079](0079-freshness-is-a-stated-tolerance.md) (staleness, and the tolerance it
  is dated by), [ADR-0084](0084-a-check-may-be-reached-through-another.md) (a shield,
  which ends when its dependency goes silent),
  [ADR-0077](0077-authority-follows-the-lease.md) (a takeover adopts the entries),
  [ADR-0102](0102-a-readings-table-keeps-time-and-names-in-view.md) (History's table),
  [ADR-0115](0115-a-copy-document-says-where-it-is-from-and-since-when.md) (the Copy
  document), [ADR-0080](0080-the-envelope-is-the-snapshot-published.md) (the envelope,
  and how it grows),
  [ADR-0137](0137-a-deployment-says-in-a-table-how-a-part-counts-above-it.md) (decision
  11: a configured rule in the periods a branch keeps, and the period a start that
  brings one begins), [ADR-0135](0135-a-handled-part-keeps-its-true-color-and-every-surface-says-by-what.md)
  (decision 2, maintenance's own words, in which History and the Copy document say a
  line's pin), [ADR-0141](0141-every-pin-is-one-thing-with-a-kind-and-the-envelope-lists-what-handles-a-part.md)
  (decision 3, `schema_version` 3, the contract the periods are part of),
  [ADR-0142](0142-a-failure-marked-seen-counts-as-ok-above-until-it-changes.md) (decision
  7, the words a seen is said in)
- **Register:** [`../decisions.md`](../decisions.md)

## Context

[ADR-0123](0123-a-node-says-one-status-wherever-it-is-read.md) made a node's status one
— what it rolls up to, on every surface — and kept its periods those of its own status.
On a node above others the Time card says *Its own status ok since …*, and where the
node shows something its own status does not account for, it first names the node
beneath that makes it so, with that node's own *since*: *Status error, from
staging/codepipeline/load-fixtures beneath it, error since 10:42, and 2 more*. No row is
written for a branch (its decision 4). So nothing says since when a branch has shown
what it shows. A branch that turned red at 10:00 from one node, which has recovered, and
that another has kept red since 10:42 reads *error since 10:42*, the second node's
period; and the traffic light the open questions sketch — the root's color, and since
when it has held — has nothing to read.

ADR-0123 left two answers to a round of their own. **A row of a node at every change of
what it rolls up to** gives a branch one status and one history, at the price of what
an event is (ADR-0107 decision 1, on which ADR-0099, ADR-0102 and ADR-0110 rest), of
the node's own history beside it, and of the bounded log, since a change is written once
for every level it moves. Replayed through ADR-0039's roll-up over one deployment's kept
log, it would have added 467 rows to a day and a half of 611, 422 of them the instance's
own node following one line of its engine that turned with every tick; over the same
deployment's eight days after the release that held that line, 43 to 147, about five a
day beside eighteen, which brings the thousand rows the log keeps from some 57 days back
to 44. **The period derived where it is read**, from the rows at and beneath the node,
writes nothing, holds only as far back as the log does, and finds no row for a node
that goes stale or a shield that ends.

## Decision

### 1. A branch's period is derived where it is read, and the beginning of the one it is in is kept beside the log

Every node above others — the root included, and a node that declares nothing of its own
— keeps in its entry beside the log the period of what it shows: since when, what it
showed before, and what moved it (decision 4), beside its own status's period (ADR-0110
decision 5) where it has one. The period is written whenever what the node rolls up to
changes, and never as a row: an event stays a change of a node's own status (ADR-0107
decision 1), and ADR-0123 decision 4 stands. A branch's earlier periods are derived from
the rows at and beneath it, as far back as the log holds them. A node with nothing
beneath it keeps the one period it has, its own. A branch first seen showing a status,
with nothing kept of it, has a bound at that reading (ADR-0110 decision 5), except the
instance's own branch, which begins with its process; a node that comes to stand above
others takes its own period as the period of what it shows; and a branch its check
removes keeps *undefined* since its removal, by itself, so that its return is a change
the tree saw rather than a new bound.

### 2. What moves it is what the branch shows, staleness included

**A write is a stored run, seen whole.** The engine stores a run as several writes — the
run's node, then each node beneath it, then what it no longer returns, and a unit's
failure over its node last (ADR-0078 decision 4) — and a branch compared between two of
them would read a state the run never showed. So a run's store holds the tree's lock
from its first write to its last, the lock each of those writes re-enters (ADR-0002),
and the bookkeeping compares every branch above what the run wrote once, when the store
ends, and dates a change by the run's one instant. A tick, a page and the API see a run
whole or not at all. Outside a run a pin set or edited is one write, and so is a node
the configuration no longer has; the pins a sweep finds run out at one instant, a node's
and a line's alike, are one write together, so that a branch whose pinned children both
end at 18:00 goes from maintenance to what they show and never through what one of them
shows alone. What a change moves of a node is what the node counts for itself, the
shield on it, and what a wait publishes for it; and a branch that a change moves only
through a shield on a node beneath it is compared as though the change had written
there.

The bookkeeping runs where the snapshot is made — on every tick, as well as at a write
— so a branch moves where a node beneath goes stale and counts at least WARN (ADR-0005),
and where a dependency shield ends because its dependency went silent (ADR-0084), as it
moves at a reading or a pin. A change that no write made is dated when the reading went
stale, its last observation and its tolerance after it (ADR-0079), and not when a tick
saw it: the moment ADR-0123 decision 3 weighs a stale node from. A branch orange because
a leaf stopped reporting says *warn since 10:45* and names the leaf *stale, last
observed 10:40*. A leaf keeps its own period and *stale, last observed* as before.

A rule the deployment configures counts in it as the snapshot counts it — at a part's
top, on a node's lines, over a count of its children
([ADR-0137](0137-a-deployment-says-in-a-table-how-a-part-counts-above-it.md) decision 11) —
so that the period of what a branch shows is the period of what it counted; and a
replay of the past, a restart's and History's, reads each rule from where it began:
from the start that brought it while a kept period says so, and else from the day its
`since:` names.

### 3. A restart carries the entries

Until the unit that answers for a node has run once in this process, the node counts for
the bookkeeping at what its entry says it showed; then as the tree has it, and not at
all where the tree has it no more. A branch's period so continues across a restart
wherever the first readings say what was kept —
[ADR-0094](0094-a-restart-is-no-transition.md) decision 1, a level up — and a change is
dated by the reading that made it. A carried node is not weighed stale: its last
observation is from before the gap, which the instance's own node states (ADR-0094
decision 4). A takeover adopts the holder's entries, their periods with them (ADR-0077),
and a difference its next tick finds, which no change of this process explains, begins a
period at that tick, with no cause and no `by`. Such a difference anywhere else means
the bookkeeping missed a change, and the log says so.

A start that brings a rule the deployment configures — a new one, or a table edited —
begins the period of each branch it moves at that start, where what the rules make of
the kept entries differs from what the entries count without them: its cause `rule`, its
`by` the node whose count the rule changed, and the rule named, rather than a period
begun at the run that ends the entries' count. A replay names one it finds beginning
inside the log alike (ADR-0137 decision 11).

**A period is said only where it is of what the node shows.** The snapshot holds only
what this process has written, so until the units beneath it have run, a branch's period
can be of a code the branch does not show: after a restart the root reads *ok* while
only the instance's own beat is written, and its period *error* since the day before. So
it can for the moment between a change no write makes — a reading gone stale, an adopted
file — and the comparison that dates it. No surface says such a period as the node's:
the envelope leaves it out (decision 7), and the Time card, History and the Copy
document say none (decisions 5 and 6).

### 4. The entry names the node whose change began the period

Beside since when and what came before — `since`, or `since` and `before` where the
beginning is a bound, and `was` — a branch's period carries `cause`, what moved it (a
reading, a pin set or ended, a removal, a reading gone stale, a rule's beginning), and
`by`, the path of the node whose change it was: the branch's own where its own row began
it, and where a rule began it the node whose count the rule changed, the rule named in
`rule` (decision 3). So what began a branch's period is still said once the log has
dropped its row, and apart from the node ADR-0123 decision 3 names as keeping the branch
so now, which may be another.

**Where one change moves several nodes at once** — a stored run that fails two
pipelines, or two nodes gone stale at one instant — `by` is the first, in the tree's
order, of the nodes it moved that answers for the branch's new period. Where the branch
now shows a worse failure than it did — warn or error after ok, maintenance or
undefined, or error after warn — that is a node that now counts the new code for itself,
ADR-0123 decision 3's maker. Where it shows less failure than before, it is a node that
counted the old code for itself, whose recovery ended it: a branch red from one node and
orange from another that nothing touched, whose run turns the red one ok and a third
warn, names the one that recovered, since the third made no difference. Where no moved
node is such a one, and where the branch moved between ok, maintenance and undefined, it
is the first node whose own part the change moved. Where a shield moved the branch, it
is the dependency the shielded nodes are reached through (ADR-0084), which need not
stand beneath the branch, so `by` does not always name a node beneath it. The tree's
order is the order it draws — a node before its children, siblings in their declared
order ([ADR-0055](0055-sibling-order.md)) — so a branch whose own part moved, and
answers for the period, names itself before anything beneath it.

### 5. The Time card says the branch's period, and the named node's only where it began later

Its first line is the period of what the node shows, and the node beneath that makes it
so keeps its own *since* only where that began after the branch's: *Status error since
10:00, from load-fixtures beneath it, error since 10:42, and 2 more*, and where one node
made the whole period *Status error since 10:00, from load-fixtures beneath it*. *Its
own status … since …* stays beneath it, and a well branch says *Status ok since …*, true
now of everything beneath it. A node that declares nothing says, where no one node
beneath it makes what it shows, that the nodes beneath it do — *Status ok since …, from
the nodes beneath it* — and its observation beneath the line as before: *Observed …*
where it has one, and *Not yet observed* only where it has no period either (ADR-0115
decision 6). A node whose own status cancels what is beneath it — a pin on it, or its
check's word for it (ADR-0124) — keeps the one line it had, since its own period is the
period of what it shows. A beginning nobody knows is a bound, *since before …* (ADR-0099
decision 1). Where the period is not of what the branch shows (decision 3), the line
says the status without a *since*, and the node beneath that makes it so with its own,
as ADR-0123 decision 3 had it: *Status ok*, or *Status error, from load-fixtures beneath
it, error since 10:42*; and a node that declares nothing, with no observation,
configuration, report or period of its own, then has no card, as a container without a
period had none (ADR-0115 decision 6). What began the period is History's and the Copy
document's to say, not the card's.

### 6. History has two tables, and the Copy document says the period of what the node shows

A node above others lists first the periods of what it shows, newest first: the one that
holds from its entry, as the Time card states it, so that it is said past the log's
reach; and those that ended derived from the rows at and beneath it, and of each
dependency a shield there is reached through, as far back as the log holds them — the
rows one write emits carry its one instant, so the derivation reads a write whole as the
bookkeeping does — the oldest stated by a bound. Each says its status, since and until
when, the node that began it — by its path beneath the node, or the full path of a
dependency outside it, linked to that node's History while the tree holds it; or
*itself*, unlinked, since that History is the page it stands on — and what moved it, in
a few words: *a reading*, *a pin set*, *edited* or *ended*, *a line's pin set*, *a
line's pin ended*, *a removal*, *gone stale*, and where a rule began it the rule named,
*the rule develop advises began*; neither where the beginning is a bound or a difference
no change explains (decision 3). Those words name the act that moved the period — a
pin — and not the status a node left, as the Time card's *when its maintenance ended*
does (ADR-0107 decision 3): a pin is a rule an admin sets, maintenance only its first
kind (ADR-0104 decision 8), and one that capped what it covers or let an error through
would show no maintenance, while a window that ended would be no pin's end. A seen, the
pin a person accepts a failure with, says its own: *marked seen*, *a seen changed*, *no
longer seen*, and their lines' forms
([ADR-0142](0142-a-failure-marked-seen-counts-as-ok-above-until-it-changes.md)
decision 7). The newest fifty stand open and the rest in one fold beneath them, since a
node above a busy check lists hundreds. Beneath them come the periods of its own status
as ADR-0123 decision 3 has them, since its own check failing — a region it cannot read,
a run that times out — is what that history is for. The Copy document states the period
of what the node shows in its own labels, beside ***Its own status*** as before
([ADR-0115](0115-a-copy-document-says-where-it-is-from-and-since-when.md)), with what
began it in one clause after the instant, in History's words: ***Status error** since
10:00, begun by a reading of load-fixtures beneath it*, or *of its own* where its own
change did it; *by a pin set, edited or ended on db beneath it*, or *on it*; *by a
line's pin set on web beneath it*; *by a line's pin ended on it*; *by the removal of a
beneath it*; *by load-fixtures beneath it going stale*, or *by its own reading going
stale*; *by the rule develop advises beginning to count develop beneath it*, where a
rule began it; and where the node named stands outside the branch, *by a reading of
/net/vpn, which a node beneath it is reached through*. A bound, and a difference no
change explains, end at the instant. On a node that declares nothing the line stands
above its observation. Where the period is not of what the node shows (decision 3),
neither says one holds: History lists the periods that ended — and where none has, says
*No status changes recorded*, as ADR-0102 decision 3's quiet log does of a node with no
period — and the Copy document ***Its own status*** alone.

### 7. The envelope carries both periods, beside the codes they are of

A node's entry in the envelope gains `period` beside `code` and `own_period` beside
`own`, each in the kept entry's words — `since`, `before` where the beginning is a
bound, `was`, `cause` — and on `period` the `by` of the node whose change began it and,
where a rule began it, `rule`, the rule's name (decision 4). Each is absent where the
node has no such period, as `run` is
([ADR-0080](0080-the-envelope-is-the-snapshot-published.md)): `own_period` on a node
that declares nothing, `period` on a leaf, whose one period is `own_period` and whose
`stale` and `run.observed_at` say when its code is degraded; and `period` where it is
not of the `code` beside it (decision 3), so that no client has to compare the two. The
change is additive (ADR-0080 decision 1) and moves no major of its own: the contract
that carries the periods is `schema_version` 3, whose break is
[ADR-0141](0141-every-pin-is-one-thing-with-a-kind-and-the-envelope-lists-what-handles-a-part.md)'s
(decision 3).

## Consequences

- **A branch says since when it has shown what it shows** — on its Time card, in History
  and in its Copy document, and for the period it is in past the log's reach — and so
  does the root, which is what the traffic light needs; the light's route and what it
  calls critical stay open.
- **A run's store is one hold of the tree's lock.** ADR-0002's mutation becomes the run
  rather than each node it writes: a reader waits out a store, which is in memory and
  takes milliseconds, and no reader sees half a run.
- **Seven records are amended**, each where it decided otherwise: ADR-0002's mutation,
  the run's store whole; ADR-0123 decision 3 and its consequence that the envelope does
  not move; ADR-0099 decision 1's words for a node above others and for one that
  declares nothing, which has a period; ADR-0110 decision 5's entry; ADR-0102 decision
  3's table; ADR-0115 decision 6, under which a container that declares nothing had no
  period and no card; and ADR-0080's envelope.
- **The bounded log pays nothing**: no row is written. What the bookkeeping costs,
  measured on a tree shaped like one deployment's, 165 nodes: the tree rolled up twice
  at every write, under the lock — a write outside a run from 0.005 ms to about 1.2, a
  run's store about that much more, and some 2 ms at a tick — and about 5 ms a run at
  550 nodes. A tree of thousands of nodes would want a cache of the last comparison,
  which saves half of it, or a roll-up kept incrementally, which saves most. And nothing
  of it waits for the cycle collector: no closure of the tree calls itself, since one
  that does is a reference cycle that would hold each roll-up's parts until the
  collector ran, about once a tick. On one deployment's kept log, 162 entries and 1,000
  rows, a bare interpreter holding the tree settles 0.4 MiB above the release before, a
  tick takes 1.8 ms, the first start's seed 0.4 s and a later start no time to measure;
  History derives a branch's periods at each view, outside the lock, in some 45 ms for a
  branch of 100 nodes.
- **A unit whose measurement keeps raising still writes two rows a run**, its grading
  and then its failure over its node (ADR-0078 decision 4), each a change of what the
  node shows (ADR-0107 decision 1), so its node's own period begins again at every run;
  this record does not change that. Its branch's period no longer moves with it, since
  the run is seen whole.
- **The kept file's entries grow** by the period of what a branch shows, in a key of its
  own. A release before this one reads the keys it knows — what a node shows and
  reported, and its own period's beginning — and passes over others, so a rollback
  restores the file; the build proves it on the release before.
- **The first start on this release seeds every branch's period** from the log it
  restores: its beginning where the rows at and beneath it say it, and a bound at the
  log's oldest row where they do not.
- **For a while after a restart a branch may say no *since***: until the units beneath
  it have run its period goes on from the entries, and is said wherever the branch shows
  what it is of — from where it began, not from the restart.
- **A log written before this release lists periods of milliseconds** in a branch's
  History, where one run's rows took instants apart, which a run's rows no longer do;
  they leave the log with their rows, and move no period a branch keeps.
- **A pin's end reads two ways**: History and the Copy document say *a pin ended*, the
  act that moved the period, and the Events page's chips *maintenance ended*, the status
  the node left (ADR-0107 decision 3), in the words maintenance takes on every surface
  (ADR-0135 decision 2).
- **The contract gains the two periods**, and the OpenAPI document and the golden
  envelope with them. The macOS client decodes only what it shows, and reads the periods
  when it shows them.

## Alternatives considered

- **A row of a node for every change of what it rolls up to.** One status and one
  history, and an event that is no longer a change of a node's own status, a change
  written once for every level it moves, and a log that holds weeks less: 43 rows more in
  eight days on one deployment, and 616 more in two days while one line beneath turned
  with every tick.
- **The derivation alone.** Nothing kept, and nothing said past the log's reach: a
  branch whose period began before the log's oldest row could state only a bound.
- **Each locked write a write.** Simplest to wire, and a half-stored run begins and ends
  real periods: a unit whose measurement raised writes its grading, then its failure over
  its node, so a branch red throughout reads ok for the instant between and its *since*
  resets to that run. **The stored run with the locks as they were**, the tree told
  where a store begins and ends and the bookkeeping passing over the branches above one
  in flight: the same periods, a marker for the tick to read, and pages and the API still
  able to see half a run.
- **The period of what the nodes last showed, staleness left out**, the bookkeeping at
  writes alone and a stale node said beside it: *ok since …* beneath a status that is
  not ok, the disagreement ADR-0123 took out of the head.
- **Every branch's period held until the first pass is done, and dated then.** A change
  dated only as closely as the pass is long, and every period above a unit that never
  finishes frozen. **Nothing special at a restart**: a period begun for most branches at
  every push and every restart.
- **A node's pin run out as a write of its own**, beside the lines' pins that run out
  together as one: a branch whose two pinned children end at one instant reads one
  child's state between them — *error since 18:00, was ok* where it was in maintenance,
  and an ok period of no length in its history.
- **Maintenance and undefined as moves of their own** in the direction test: from
  maintenance to error it named the first node moved, not the one that now fails.
- **The maker among the moved nodes, whichever way the branch moved.** Where the branch
  got better it names a node that made no difference — a third that turned warn beside
  an orange one nothing touched — where the node that recovered is what began the
  period.
- **The kind alone as what moved it**, *beneath* or *stale*, and **since and what came
  before alone**: a beginning that keeps its date and loses its reason past the log's
  reach.
- **The branch's time in place of the named node's** on the Time card, which reads as
  though that node had made the whole period; and **both times always**, one time said
  twice where one node made it.
- **One table on History**, of what the node shows, which leaves when its own check
  failed to the Events page's rows; and **the own table with the current period above
  it**, which leaves a branch's earlier periods there too.
- **The envelope as it was**, which ADR-0123 kept, and **the shown period alone**, which
  would bring periods into the API by one of the two.
- **The period beside its code whatever that code is**, or with a code of its own:
  *Status ok since* the day before on a root that is green only because nothing has run
  yet, or every client left to compare the two.
- **The same fields flat on the node** — nine keys, the pairing with `code` and `own` in
  the names alone — and **one `periods` object**, which moves the two away from the codes
  they describe.

