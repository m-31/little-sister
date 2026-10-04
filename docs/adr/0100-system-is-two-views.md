# ADR-0100 — System is two views: what is running, and what is installed

- **Status:** Accepted
- **Date:** 2026-10-03
- **Related:** [ADR-0097](0097-a-nodes-series-have-a-view-of-their-own.md) (a node's
  views as tabs beneath its title, the idiom followed here),
  [ADR-0005](0005-dashboard-freshness-and-self-monitoring.md) (the stamp that dates a
  polled page), [ADR-0074](0074-this-instance-has-a-name.md) (which instance this is),
  [ADR-0075](0075-a-check-declares-what-it-costs.md) (decision 8, the declared figures
  beside the measured ones), [ADR-0084](0084-a-check-may-be-reached-through-another.md)
  (what a check is reached through), and the records whose sections move:
  [ADR-0034](0034-template-slots-for-dependent-packages.md),
  [ADR-0035](0035-registering-a-config-aspect.md),
  [ADR-0037](0037-extension-static-assets.md),
  [ADR-0038](0038-declarative-action-list.md),
  [ADR-0048](0048-an-assembled-content-security-policy.md),
  [ADR-0051](0051-what-startup-refuses.md), [ADR-0052](0052-plugin-names.md),
  [ADR-0064](0064-the-resolver-is-a-registration.md),
  [ADR-0069](0069-identity-comes-from-outside-and-one-account-does-not.md),
  [ADR-0072](0072-the-instance-reports-on-itself.md)
- **Register:** [`../decisions.md`](../decisions.md)

## Context

`/system` was one long page for an administrator. At its top, which instance this is,
the engine's figures — uptime, the pool, the declared load, the entries, the series and
the memory held — and every check's schedule, the part the ~10s poll refreshes. Beneath
it, everything the installation settled at startup: the check types and the code behind
each, the packages beside the library, the extension seams, the ways in, and the
Content-Security-Policy the pages are served under. The two have different readers — one
asks whether the process is near a limit and when a check runs next, the other which
package answers for a type or which doors are installed — and different lives: the first
changes every tick, the second never while the process runs. On one page the reader of
either scrolled past the other, and sixteen schedule rows stood between the live figures
and the reference tables.

The schedule itself crowded: eight columns, the times and their intervals wrapping, a
type column read with the path anyway, a *Through* column that was an em dash for nearly
every check, and a *Declared* column that also carried, in parentheses, the heaviest
record the last run produced — so its heading described half of what was under it.

## Decision

### 1. Two views of one heading

System is two views, tabs beneath one heading, as a node's views are beneath its title:
**Running**, at `/system`, and **Installed**, at `/system/installed`. Both are for an
administrator only, and both are headed *System · little-sister ‹version›*.

### 2. Running is what the process is doing, and the view the poll refreshes

Which instance this is — its name and mark — the engine's figures and the schedule. It
is polled as before (`fragment=1`), and the stamp dating it stands at the right of the
heading. A bookmark of `/system` keeps landing here.

### 3. Installed is what startup settled, every section open under an index

Check types, packages, extensions, identity and the Content-Security-Policy, none of
which changes while the process runs, so nothing on the view is polled. A reader comes
here to read, so every section is open, under an index of links with a count where one
helps; the types this configuration does not use keep their fold, which hides noise
rather than the answer. Identity is here: a door startup could not open is also a line
on the instance's own startup node, where problems are raised, and that line names this
view.

### 4. The schedule is a row per check, and a column for each thing it holds

*Check*, with its type and what it is reached through — where it is — on a muted line
beneath its path; *Every*; *Running*, *Next run* and *Last run*, each a time of day and
its interval on one line; *Declared*, the type's estimate of one run — its time, its
entries, its record; and *Seen*, the heaviest record the last run carried, *refused*
where it was. A line above the table says what compares with what: the declared run
time with *Last run*, the declared record with *Seen* — the comparisons ADR-0075
decision 8 puts side by side.

## Consequences

- **The records that put a section on `/system` name its new place**:
  ADR-0034, ADR-0035, ADR-0037, ADR-0038, ADR-0048, ADR-0051, ADR-0052, ADR-0064,
  ADR-0069 and ADR-0072 for Installed, and ADR-0084 for what a check is reached through,
  now a line beneath it.
- **A bookmark into the reference sections needs its new address**; one of `/system`
  still lands on the live view.
- **The rail's *System* is lit on both views**, since it matches the path beneath it.
- **No contract moves**: both are pages, and the JSON envelope carries neither.

## Alternatives considered

- **One page with named sections and an index**, the reference sections folded behind
  counts: one address and a smaller change, but the page still mixes two jobs and two
  lives.
- **One page, only folding the reference sections**: the page is long again the moment
  anything opens.
- **Identity on Running**, so a shut door stays in front of the admin: it mixes a fact
  settled at startup into the live view, and the door's failure is raised on the
  instance's own node already. **The instance card on Installed**, since it is settled
  at import: Running would no longer say which instance it describes.
- **Installed's sections folded behind counts**: a click for every section, and a
  browser's find cannot reach every row inside a closed one; the index gives the same
  overview.
- **Two schedule tables**, a schedule and a cost table: each comparison reads left to
  right, but every check appears twice and is matched by name. **Relabeling
  *Declared (seen)* and keeping eight columns**: the table stays as crowded as it was.
