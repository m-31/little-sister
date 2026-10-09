# ADR-0123 — A node says one status wherever it is read

- **Status:** Accepted
- **Date:** 2026-10-10
- **Related:** [ADR-0032](0032-status-contribution-boundary.md) (decision 1, the
  statuses a node has — reported, own, effective — and rule 6, staleness judges the
  raw reading), [ADR-0039](0039-status-rollup-semantics.md) (the roll-up, and rule 3,
  what maintenance cancels), [ADR-0005](0005-dashboard-freshness-and-self-monitoring.md)
  (a stale reading counts degraded),
  [ADR-0107](0107-an-event-is-a-change-of-what-a-node-shows.md) (decision 1, an event
  is a change of a node's own status, which decision 4 keeps; decision 3, what a
  period says of its beginning),
  [ADR-0099](0099-a-status-that-still-holds-says-since-when.md) (decision 1, the Time
  card's sentence, which this amends),
  [ADR-0115](0115-a-copy-document-says-where-it-is-from-and-since-when.md) (decision
  5, a branch's document, which this amends),
  [ADR-0094](0094-a-restart-is-no-transition.md) (decision 5, a node that declares
  nothing names no period),
  [ADR-0102](0102-a-readings-table-keeps-time-and-names-in-view.md) (decision 3,
  History's rows), [ADR-0110](0110-what-every-node-last-showed-is-kept-beside-the-log.md)
  (the table that keeps when a period began),
  [ADR-0083](0083-a-node-may-wait-before-it-escalates.md) (decision 7, the count of a
  node's changes), [ADR-0080](0080-the-envelope-is-the-snapshot-published.md)
  (decision 2, the three statuses in the envelope),
  [ADR-0106](0106-a-subject-with-a-history-has-a-node-of-its-own.md) (a subject's
  node, beneath a node that says its scope),
  [ADR-0044](0044-run-facts-on-the-node.md) (decision 8, the one block of a node's
  own facts), [ADR-0079](0079-freshness-is-a-stated-tolerance.md) (the tolerance a
  reading is stale past)
- **Register:** [`../decisions.md`](../decisions.md)

## Context

A node has a status of its own and a status it rolls up to (ADR-0032, ADR-0039), and
for a node with nothing beneath it the two are one. A node above others can be well of
its own while a node beneath it fails: an `aws` check's account that was read, its
aspect whose one line counts what is in scope, a `github` check's own node, which
says how much of its estate it read, the instance's own node above what it reports of
itself. The tree rolled such a node up as it should, and its card on the page above,
its one card at depth 0, the Series view and the API's `code` said what it rolls up
to.

Its own page did not. From depth 1 the head stated the node's **own** status, on the
ground that the nodes right below say theirs, and only a node that declares nothing
headed with what it rolls up to. So a node whose own line was well headed its page
green, `ok`, over a child in error, while the page above drew the same node red: one
node, two statuses, by where it was read. The Time card beneath said *Status ok since
…*, the node's Copy document said the same two lines under *Shown as: error*, and
History said *ok — current*. The period is the own status's (ADR-0099 decision 1), and
each surface stated it as the node's. It stayed wrong once the child had recovered:
*ok since* a day on which the node's card had stood red. And nothing on the page said
since when the node had shown what it showed: the time a node beneath it had begun to
fail was on that node's page alone.

Each surface chose for itself. It was handed the node's two statuses and decided which
of them to call *the status*, and three surfaces worked out whether a color is the
node's own in three ways: the head by whether the node declares anything, a card by
whether its two statuses differ, the Copy outline by what the tree counts for the
node. Only the last was right for a reading gone stale. A node whose own check has
stopped shows a warning that is its own (ADR-0005), and its card drew it pale, as it
draws a color that comes from a child.

The shape is the common one. In one deployment's kept table, eleven of the thirteen
nodes that had nodes beneath them declared a status of their own, and three of the
eleven headed their pages `ok` over something worse when the file was saved.

## Decision

### 1. A node's status is what it rolls up to, on every surface that says it

The head of a node's page says what its card says on the page above: the node's
effective status (ADR-0032 decision 1), at every depth, on the page and in the part
its refresh asks for. A surface that says *status* of a node and no more says that
one: the head, a card, a box, a leaf's page, the Series view, a Copy document's
heading and its *Shown as*, and the API's `code`.

### 2. Whose a status is, the snapshot says

What a node counts for itself in what it rolls up to is its own status — or, where its
own reading is stale, what its check reported, degraded (ADR-0005, ADR-0032 rule 6).
The snapshot states that, by the expression it rolls the node up with, and states
whether what the node shows is **derived**: not what it counts for itself, and so from
beneath it. A surface reads that and compares nothing itself.

A head is pale where its status is derived, since the node that makes it so is right
below, and vivid where the status is the node's own: a failure of its own, or its own
reading gone stale. A card and a box are pale where they are well, as they were, and
where their status is derived and the nodes beneath them are drawn.

### 3. A period is the own status's, and a node above others names it so

A node's periods stay those of its own status (decision 4). What a node above others
shows counts the nodes beneath it, so its own status is one part of that, and a
surface that states a period of such a node says whose it is:

- the Time card, *Its own status ok since …*, and what kind of beginning it had after
  it, as before (ADR-0099 decision 8, ADR-0107 decision 3);
- the node's Copy document, ***Its own status ok** since …*, beneath its *Shown as*;
- History, under its table: *The periods of its own status: its page heads with what
  it rolls up to, the nodes beneath it included.*

It is named so while the node is well too, since the period is not the node's then
either. The count of a node's changes in the last hour (ADR-0083 decision 7) is of
its own check's, and reads *1 change of its own status in the last hour* there.

**Where the node shows something its own status does not account for, the Time card
says that first, and names the node beneath it that makes it so, with that node's own
*since*:** *Status error, from staging/codepipeline/load-fixtures beneath it, error
since 10:42, and 2 more*. The node named counts the branch's code for itself, and
every node between them counts it on: a branch on the way down that only passes the
code on is never the one, and a node that warns beneath a red branch is not named. Of
several, it is the one that has shown the code the longest, and the line says how many
others there are. Its *since* is the period its own Time card states, in the same
words where that period began *before* a bound or when a pin ended, and its name is a
link to its page. One that counts the code because its own reading went stale is named
as stale, with when it was last observed — *stale, last observed 10:40* — since its
period is of something else; it has counted the code since its reading went stale, its
last observation and its tolerance after it (ADR-0079), and is weighed from then. A
status that no one node makes, *ok* or *maintenance*, is *from the nodes beneath it*.
Where the named node's code has counted all along, the branch has shown it at least
since then — as much as the card can say without a row of the branch's own
(decision 4); the Events page under the branch lists every change beneath it.

Three kinds of node do not name their period their own. A node with nothing beneath
it shows its own status: *Status error since …*. A node in maintenance, by a pin or by
its check's own word, cancels what is beneath it (ADR-0039 rule 3), so its period is
the node's: *Status maintenance since …*; one whose lines are all silenced cancels
nothing, nor does a pinned one whose own reading went stale, and each names its period
its own
([ADR-0124](0124-a-node-whose-lines-are-all-silenced-still-counts-the-nodes-beneath-it.md)).
And a node that declares nothing has no own status for a period to name, and states its
observation (ADR-0094 decision 5), beneath the line that says where what it shows comes
from, since all of it does.

Which status a period names, whether it is named the node's own and which node beneath
makes what the node shows are decided where the period's bound is decided, once, from
the node before a view's filter takes its children away. The Time card, on either page
and in its poll, prints what that says, and the Copy document reads the same answer
off its node.

### 4. No row is written for a node when a node beneath it changes

An event stays a change of a node's own status (ADR-0107 decision 1), and History,
*since* and the kept table (ADR-0110) stay what they are. A change beneath a node is a
row of the node that changed, and the Events page lists it under every node above.
Since when a branch has shown what it shows is said by the node beneath it that makes
it so: on that node's own page, and in the line the branch's Time card gives it
(decision 3), never by a row of the branch's.

## Consequences

- **A page that headed green over a failing node heads red, and pale.** Its head, its
  card on the page above, its one card at depth 0 and the API say one status, and the
  node that fails is the vivid one beneath it.
- **The Time card of every node above others reads differently**, also where nothing
  is wrong: *Its own status ok since …* where it read *Status ok since …*, and its
  changes as its own status's. So does such a node's Copy document.
- **A branch whose status comes from beneath it names the node that makes it so**, on
  its Time card, with that node's own *since* and a link to its page: since when the
  branch has shown it, as far as one node's period can say. A container that declares
  nothing says the line above its observation, where it said *Observed …* alone. The
  Copy document names no such node: its outline lists the nodes beneath with their
  periods.
- **A stale reading of a node's own is drawn as the node's**: vivid on its head, on
  its card and on its box. The card and the box drew it pale where the nodes beneath
  them were drawn.
- **[ADR-0099](0099-a-status-that-still-holds-says-since-when.md) decision 1 and
  [ADR-0115](0115-a-copy-document-says-where-it-is-from-and-since-when.md) decision 5
  are amended**: on a node above others the period is named its own status's, and
  what a pin's end or a line's pin says of its beginning follows those words.
- **The envelope does not move.** `reported`, `own` and `code` say what they said
  (ADR-0080 decision 2). Whose `code` is, is not in it: a client that compares `own`
  with `code` reads a stale reading of the node's own as one from beneath it, as the
  cards did.
- **A Copy document's *Shown as* stands where it stood**: where a node shows
  something other than it reported, which its own reading gone stale is as well.
- **A branch's page a reader cannot pin still opens without a head** where its node
  declares nothing and carries no line: it says no status of the node, and the nodes
  beneath it say theirs.
- **One test file reads every surface** for a node whose check passes over a node
  that fails, and holds them to one status.

## Alternatives considered

- **A row of a node for every change of what it rolls up to**, so that History and
  *since* are those of what the node shows: one status and one history, and nothing
  to name. It changes what an event is, on which ADR-0099, ADR-0102 and ADR-0110
  rest, and it has questions of its own: what the first readings after a restart do
  to a roll-up that is partial until every check has run, what becomes of the node's
  own reading while a node beneath it is worse, the cause and the reason of such a
  row, and what the bounded log pays. Replayed over one deployment's kept log of a
  day and a half, 611 rows, it would have written 467 more: 422 of them the
  instance's own node following one line of its engine, and 45 beside the 158 rows of
  every other branch. Left to a round of its own.
- **The same period derived where it is read, from the rows beneath the node, and no
  row written.** It holds as far back as the log holds those rows; keeping the
  beginning past that needs, at every write, the bookkeeping the rows would need; and
  staleness and the end of a shield are no rows to read.
- **The head alone.** The page then heads *error* and says *Status ok since …*
  beneath it.
- **Every node above others read as one that declares nothing**, with no period. It
  loses since when the node's own check has failed, which is what the period is for
  on a run that times out or a region that cannot be read.
- **The period named its own only while the two statuses differ.** *Status ok since*
  a day on which the node's card stood red.
- ***Its own reading***, the Copy document's phrase for what a roll-up starts from.
  With a line pinned the own status is not the reading, and the words would be wrong
  where the card adds *when a line was silenced*.
- ***From the nodes beneath it* and no more.** True, and it leaves since when the
  branch has shown what it shows to the pages beneath it; where a node beneath makes
  it so, the card can say that without either answer the round on a branch's own
  history waits for.
- **Every node beneath that makes it so, named.** A branch above thirty failing
  pipelines would carry thirty names and thirty periods on its Time card, which the
  nodes beneath it draw already; the line names one and counts the rest.
- **The one that began to show it last.** It says what changed most recently, which the
  Events page says; the line answers since when, and the oldest period is the nearest
  a node beneath can come to that.
- **A stale node weighed from its last observation.** Until its tolerance ran out it
  counted what it read, or nothing under a pin, so it would be named for a time it did
  not make the branch's status.
- **Every status named, *ok* included.** No one node makes a branch well.
- **Each surface comparing the two statuses**, as it was: three surfaces, three
  answers, and a stale reading wrong in two of them.
- **The types declaring nothing on such nodes.** An account that was read, a scope
  that is well and the instance's beat are each a status with a meaning, and the
  library draws whatever a type hands back.

