# ADR-0122 — A series is read over the API as it stands: its node, its key, its measures as drawn, its readings

- **Status:** Accepted
- **Date:** 2026-10-04
- **Related:** [ADR-0106](0106-a-subject-with-a-history-has-a-node-of-its-own.md)
  (decision 6, the read at the Series view's own URL, which this builds and whose open
  half it settles; decisions 2 and 4, the node a series is shown on),
  [ADR-0097](0097-a-nodes-series-have-a-view-of-their-own.md) (decision 1, what stands
  at or beneath a node; decision 3, a tab read from what is declared; decision 4, the
  index at the root), [ADR-0098](0098-a-series-view-is-drawn-over-a-window.md)
  (decision 1, the window `from` and `to` name; decision 2, a curve with no reading in
  it keeps its place), [ADR-0096](0096-a-measure-names-its-node-and-its-things.md)
  (decision 1, the node a measure names; decision 2, the `*` that picks a key),
  [ADR-0117](0117-a-measure-says-where-its-axis-reaches.md) (`axis_to`),
  [ADR-0087](0087-a-check-keeps-its-subjects-readings.md) (the key, both clocks, the
  identity and the state, and what stood where a reading landed),
  [ADR-0082](0082-a-line-carries-what-it-is-about-and-what-it-read.md) (a record's
  typed times), [ADR-0080](0080-the-envelope-is-the-snapshot-published.md) (decision 1,
  an addition is a minor and one answer is written down; decision 8, one URL, the
  bearer token, Problem JSON, one response),
  [ADR-0068](0068-the-login-gate-refuses-by-default.md) (the gate, and the routes that
  choose their own credential),
  [ADR-0116](0116-a-path-with-no-node-says-what-is-known-of-it.md) (a path no node
  stands at), [ADR-0120](0120-every-stored-time-is-an-instant.md) (how an instant is
  spelled), [ADR-0067](0067-the-run-scripts-can-serve-tls.md) (the run scripts)
- **Register:** [`../decisions.md`](../decisions.md)
- **Contract:** [`../api/openapi.yaml`](../api/openapi.yaml) — the normative schema.

## Context

[ADR-0106](0106-a-subject-with-a-history-has-a-node-of-its-own.md) decision 6 settled
that the API reads a series at the Series view's own URL, and what each series says: the
node it stands on, the key it is kept under, the measures its check declares, and its
readings in the window. It built nothing, because nothing read a series, and it left to
the build everything a reader then holds for good: the names, what a measure looks like,
what a node without series answers, the root, the refusals. Once a reader holds a name,
changing it is a `schema_version` 3
([ADR-0080](0080-the-envelope-is-the-snapshot-published.md) decision 1).

What reads a series is now named, and it is neither of the readers the family had in
mind. The macOS client draws no history and says so. What does happen is that a session
or a person opens the state directory of the checkout beside them and reads
`series.json` by hand — how many readings a function keeps, what a day of them weighs —
which works next to the process that wrote the file and nowhere else, and answers
nothing about where a series is shown.

The questions were settled one at a time over a prototype of the answer, built from the
Series view's own helpers and run over one deployment's kept readings: thirteen series
of the library's own types, 7,584 readings. A node over one hour answered 4 to 29 KiB, a
host over everything kept 659 KiB, and everything the instance kept 3,082 KiB — 230 KiB
compressed — built in 30 ms.

## Decision

### 1. The first reader is a session or a script that reads a running instance

The read is cut for a reader that wants what an instance keeps, as it keeps it: whole
records, both clocks, the key a series is kept under, and the node it is shown on. It is
not cut for a picture: nothing is reduced, projected or drawn, and nothing in the answer
is there for a curve alone. A client that draws one reads the same answer.

### 2. `GET /series` reads the root as `GET /series/<node_path>` reads a node

The rule is [ADR-0106](0106-a-subject-with-a-history-has-a-node-of-its-own.md) decision
6's own — every series that stands at or beneath the node — and the root is a node:
`GET /series` with `Accept: application/json` answers every series the instance keeps,
over the window, as `GET /status` answers the whole tree. The page at that URL is the
index of the same series
([ADR-0097](0097-a-nodes-series-have-a-view-of-their-own.md) decision 4), which lists
them and draws none. What the first reader asks first is what the instance keeps, and
without the root it would ask the status read for the top-level nodes and then each of
them.

### 3. A series is in the answer where it is shown at or beneath the node, or one of its measures stands there

A series is shown on the node that stands for its subject, and on its check's own node
where none does
([ADR-0106](0106-a-subject-with-a-history-has-a-node-of-its-own.md) decisions 2 and 4).
It is in the answer where that node is the one asked or beneath it. A series shown above
the node asked is in the answer where one of its measures names a node at or beneath it
([ADR-0097](0097-a-nodes-series-have-a-view-of-their-own.md) decision 1): a host's
series answers at the host's `memory` node by the measure that stands there.

Which series stand is read from where the lines stand and from what is declared, never
from a reading's numbers — the rule of the Series tab
([ADR-0097](0097-a-nodes-series-have-a-view-of-their-own.md) decision 3) — and from
everything kept, whatever the window: a series with no reading inside the window keeps
its place and answers an empty list of readings, as its curve keeps its place on the
page ([ADR-0098](0098-a-series-view-is-drawn-over-a-window.md) decision 2).

Each series says the `node` it stands on, by its path, and its `key`: the `type` and
the `mount` of its check, and its `subject`. The key rides inside for a reader that
follows a subject across a rename, where the node changes and the key does not.

### 4. A measure is published as the page draws it

A declaration may hold a `*` for the key a record counts a thing by, and names its node
from the node its reading stands on
([ADR-0096](0096-a-measure-names-its-node-and-its-things.md) decisions 1 and 2,
[ADR-0106](0106-a-subject-with-a-history-has-a-node-of-its-own.md) decision 2). The
answer carries what that stands for: **one measure for every key the kept readings
hold**, each with its `field` — the dotted name, the key in the `*`'s place — its
`unit`, its `label`, the `node` its curve stands on as a path from the root, and
`axis_to`, where its value axis reaches
([ADR-0117](0117-a-measure-says-where-its-axis-reaches.md)), or null. They are expanded
over everything the series keeps, whatever the window, as the page decides which curves
stand, and **only the measures that stand at or beneath the node asked are listed**.

A measure is the check's and not the series': each of a check's series lists it, a
series of states the measure its runs are drawn by. And a measure is listed whether or
not a reading gives it a number, since that would be read from the readings; what a `*`
needs is a key to stand for, so a declaration no kept reading holds a key for lists
nothing.

**A reader reads a field in one way:** it flattens a record by joining the keys from
the top down to each value with `.`, and looks the measure's `field` up. It never
splits the name, since a key may hold a `.` itself.

### 5. A reading says where it stands in time, how it stood, and what was read

As [ADR-0106](0106-a-subject-with-a-history-has-a-node-of-its-own.md) decision 6 lists
it: `at`, the time on the series' clock, which is the record's own time where it has
one and otherwise when it was first observed; `observed_at`, when the engine last took
it; `code` and `texts`, the code and the sentences as they stood where the reading
landed; `identity` and `state`; and `record`
([ADR-0087](0087-a-check-keeps-its-subjects-readings.md) decisions 3, 6 and 8).

- `code` is null where the reading kept none, and an absence is never an `OK`.
- `texts` is an array, since a reading placed on a node keeps that node's lines, a
  reading a line carried that line's one, and a reading that stood nowhere none.
- `identity` and `state` are text, at most one of them set, and both empty for a
  reading that is always a new one.
- `record` is the record whole, in the check's own keys, its typed times in UTC
  ([ADR-0082](0082-a-line-carries-what-it-is-about-and-what-it-read.md)). It is the
  word a node's measurement has in the status read, where a line's is `data`.

Readings are listed oldest first, in the order the series keeps them, and a reading is
in the window where its `at` is, both ends included.

### 6. The answer says what was asked, and orders what it holds

Beside `schema_version`, `generated_at` and `instance`, which are the status read's, the
answer carries `path`, the node asked, `/` for the root; `window`, the two instants the
server read `from` and `to` as, each null where the URL left it to what is kept; and
`series`. A window back from now is read by the server's clock
([ADR-0098](0098-a-series-view-is-drawn-over-a-window.md) decision 1), so the answer
says which instants it meant.

Series are ordered by the node each stands on: a node above the one asked first, then
the tree's own order at and beneath it — a node before its children, siblings by rank
and then by name — and by type, mount and subject where several stand on one node.

### 7. A node that stands answers a list, and three things are refused

A node that stands answers `200` and a list, **empty where no series stands at or
beneath it** — a node no check keeps a series of, a check that has read nothing yet,
and every node of an instance that runs no engine, where `instance` says so. The page
answers the first and the last of those `404`; to a reader `404` then meant two things.

Refused, in the page's order, each as Problem JSON: `401` without a valid bearer token;
`404` where no node stands at the path
([ADR-0116](0116-a-path-with-no-node-says-what-is-known-of-it.md)), and for nothing
else; `400` for a window the server cannot read, or whose `from` is not before its
`to`, with the page's sentence as its `detail`
([ADR-0098](0098-a-series-view-is-drawn-over-a-window.md) decision 1). The `400` is the
first the API answers.

### 8. The two routes choose their own credential

`/series` and `/series/<node_path>` join `/status` among the routes the gate leaves to
themselves ([ADR-0068](0068-the-login-gate-refuses-by-default.md)): each answers a
bearer token where `Accept` asks for JSON and a session otherwise, and refuses both
ways. Behind the gate a script with a valid token was redirected to the login page.

### 9. One answer is written down, in the package

`series-2.json` stands beside the golden envelope in `little_sister.contract`, read as
`contract.golden_series()`: one answer that holds every shape the read has — a series
on its check's node and one on its subject's, a measure a `*` expanded and one with no
`axis_to`, a series without measures, a reading that failed, a run with its own time, a
run without a verdict, a state, and a series with no reading in the window. It is
generated from this application's own API over a scene whose instants are fixed, so
every time in it is a value a reader decodes, and a test holds the server to it
([ADR-0080](0080-the-envelope-is-the-snapshot-published.md) decision 1). It ships in
the wheel. It is not a shared file of the family while the macOS client reads no
series.

### 10. The contract moves a minor

The read is additive under `schema_version` 2: `info.version` 2.7.0, in the one OpenAPI
document, with its paragraph in the guide beside it
([ADR-0080](0080-the-envelope-is-the-snapshot-published.md) decisions 1 and 8).

### 11. `test_api.sh` takes a path, and is the first reader

The smoke test reads `/status` and takes the token out of `.env` itself, which is what
lets a session read a running instance at all: a credential is never read by an agent.
It takes the path to ask as its argument — `./test_api.sh
'/series/hosts/alpha?from=now-1h'` — and asks `/status` without one, as it did.

**A refusal is printed as the instance said it**, and the run still fails. The `detail`
of a `400` is the sentence its reader needs (decision 7), and a script that ends on the
status alone has thrown it away.

## Consequences

- **[ADR-0106](0106-a-subject-with-a-history-has-a-node-of-its-own.md) decision 6 and
  [ADR-0097](0097-a-nodes-series-have-a-view-of-their-own.md) are amended**: the read is
  built, the Series view is no longer HTML only, and *the measures its check declares*
  reads *as the page draws them*.
- **Two routes leave the gate** and refuse on their own account, as `/status` does,
  which amends [ADR-0068](0068-the-login-gate-refuses-by-default.md): the routes that
  choose their own credential are three.
- **A reading travels whole.** An aspect's node, whose curve is one field, answers every
  field of its host's readings: 305 KiB for 720 of them. A read that projects a field
  is not built.
- **A root read without a window is everything kept**, some 3 MB at one deployment's
  keeps; `?from=now-1h` there was 137 KiB.
- **The answer follows the readings where a `*` is declared**: a host that reports one
  disk lists nothing for a measure declared over its volumes, and one with four lists
  four.
- **The read answers what the memory tier keeps**, as the pages do. A store behind it
  ([ADR-0087](0087-a-check-keeps-its-subjects-readings.md) decision 7) may widen what a
  window reaches, and not the answer's shape.
- **The macOS client's copies of the spec and its guide move** with the contract, and
  nothing else of the client does.

## Alternatives considered

- **A measure as declared** — the `*` and the node relative to the series' own, the
  reader expanding it: the literal reading of *the measures its check declares*, stable
  against the readings, and a second copy of the `*` rule and of the path join in every
  reader, wrong for a key that holds a `.`.
- **`404` for a node without series, as the page** — one status for a wrong path and
  for a node no check keeps a series of, and the empty answer to handle beside it for a
  check that has read nothing yet.
- **The root left out** — the letter of
  [ADR-0106](0106-a-subject-with-a-history-has-a-node-of-its-own.md) decision 6, and a
  reader that walks the status read before it can ask what the instance keeps.
- **The answer as a second key of the golden envelope** — its volatile fields go by
  name and would blank every reading's `observed_at`, and the client's copy would
  change for a read it does not make; **the second artifact shared with the client** —
  a third file there that nothing reads.
- **`data` for a reading's record** — the word a line's record has in the status read
  and the series file's own; a reading is a measurement and not a line, and
  [ADR-0106](0106-a-subject-with-a-history-has-a-node-of-its-own.md) decision 6 says
  *the record*.
- **The read built for the macOS client, or for no reader** — the first cuts the answer
  for a picture nobody has asked for, and the second fixes names nobody has read.
- **`curl --fail-with-body` for a refusal** — one flag, and one a curl older than
  7.76.0 does not have, in a script that ships to machines nobody here has seen.
