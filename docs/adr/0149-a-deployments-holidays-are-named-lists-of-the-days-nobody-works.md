# ADR-0149 — A deployment's holidays are named lists of the days nobody works, each complete for the years it states

- **Status:** Accepted
- **Date:** 2026-10-31
- **Related:** [ADR-0031](0031-deployment-config-directory.md) (the configuration
  directory — the `holidays` aspect, a file in each root, decisions 2 and 4 amended),
  [ADR-0032](0032-status-contribution-boundary.md) (rule 7: an unusable rule does not
  apply), [ADR-0137](0137-a-deployment-says-in-a-table-how-a-part-counts-above-it.md)
  (a configured file that stops nothing, what cannot apply named on the startup record),
  [ADR-0014](0014-maintenance-persistence.md) (maintenance, the first reader),
  [ADR-0120](0120-every-stored-time-is-an-instant.md) (decision 7: the configured zone,
  which an entry keeps as it keeps a list's key),
  [ADR-0071](0071-what-a-restart-keeps-is-a-directory-of-files.md) (every service a
  package — a calendar that wants credentials among them),
  [ADR-0104](0104-a-pin-is-one-block-on-what-it-silences.md) (decision 8: a rule the
  configuration declares is read-only on the page)
- **Register:** [`../decisions.md`](../decisions.md)

## Context

Maintenance is to recur (#35), and a recurring window may leave out the days nobody
works: *every weekday from 22:00 for eight hours, not on holidays*. Two more readers
want the same days, both named by the round: the watch window, a node's verdict that
does not apply while the shop is closed, and quiet hours, in which nobody is on duty.
#35's walk-through settled what holidays are and where they live. They are a data
source, not a rule — region-specific, year-specific, and in Germany specific to the
state — and they are the deployment's data, a plain list in its configuration, edited
once a year: no library, which brings a dependency and its own idea of a holiday, and
no feed, which brings network from the engine, a refresh and a failure mode. A list
that cannot be read keeps whatever needs it from applying, since silence is the
direction a naive reader fails in
([ADR-0032](0032-status-contribution-boundary.md) rule 7).

What was left is the file, put to Lex in the round's design pass on 2026-10-31: what it
holds, how a reader names a list, what of it can be read, and how the configuration's
roots combine. His answer widened the question. A company's own days off are a list
beside a region's public holidays, and every reader the vision names wants days nobody
works — maintenance's *not on holidays*, the watch window's closed shop, quiet hours'
nobody on duty — so the file is the deployment's, named for that, and each list means
that one thing to every reader.

## Decision

1. **One file of named lists, `config/holidays.yaml`, of the days nobody works.** The
   file is the deployment's, not maintenance's: a region's public holidays and a
   company's own days off are lists beside each other, and each means one thing —
   days nobody works — that every reader uses the same way: maintenance's *not on
   holidays*, the first, and the watch window's closed shop and quiet hours' nobody on
   duty when they come. A freeze, a day people work, is no such list. The aspect is a
   file, the library's own
   ([ADR-0031](0031-deployment-config-directory.md) decisions 2 and 3).

2. **A list is keyed by a name its reader keeps, and says its name, the years it is
   complete for and its days.** The key is the deployment's to choose — an ISO 3166-2
   code by convention for a region's public holidays, `DE-BY`, anything for a
   company's own — letters and digits with hyphens, dots or underscores between them.
   A reader keeps it, as a maintenance entry keeps `not_on: DE-BY` beside the zone it
   keeps ([ADR-0120](0120-every-stored-time-is-an-instant.md) decision 7), so that
   nothing a later file says of its default moves the entry. `name` reads after *not
   on* in a sentence: *not on holidays in Bavaria*, *not on ACME's company holidays*.
   `complete` is the years the list is complete for, **stated, never inferred**:
   inferred from its days it would misread a list that rightly has no day in a year —
   a company's with none in 2027 would read as incomplete and stop every window of
   2027 — so a year written there is complete with no day in it, a day written in a
   year not written there makes that year no more complete, and a reader that needs a
   year the list does not state has it missing. `dates` maps each day, `YYYY-MM-DD`,
   to its name, which a page marks the day with. `default` names the list an editor
   offers first, and may be left out:

   ```yaml
   lists:
     DE-BY:
       name: holidays in Bavaria
       complete: [2026, 2027]
       dates:
         2026-11-01: All Saints' Day
         2026-12-25: Christmas Day
     acme:
       name: ACME's company holidays
       complete: [2026]
       dates:
         2026-12-24: Christmas Eve
   default: DE-BY
   ```

3. **What cannot be read does not apply, and the start names it**
   ([ADR-0032](0032-status-contribution-boundary.md) rule 7). Within a list, any
   mistake — a day that is no date or carries a time, a day written twice, a day or the
   list with no name, no year stated complete or one that is no year, a key a list does
   not know — leaves that list unreadable whole, since a day missing from it would put
   a window on that day; the others stand. Outside the lists, any mistake — a file that
   does not parse or is no mapping, a key it does not know or one written twice, `lists`
   that are no mapping — leaves the file unreadable, and a file that cannot be read
   leaves every list unreadable, any of them being possibly written in it. Each is a
   line on the startup record, a warning on the instance's own node for the life of the
   process, and nothing here stops the monitor
   ([ADR-0137](0137-a-deployment-says-in-a-table-how-a-part-counts-above-it.md)). A
   `default` that names no list hides nothing, so it stops nothing: it is named, and no
   list is offered first. A reader asks for a list by its key and has it, or why not —
   the file's line, the list's own, or that no file lists it — and what it does without
   one is its own, failing toward alarming: maintenance's record says what an entry
   that leaves out a list it cannot have does, and an occurrence in a year its list
   does not state. **A year a list does not cover is said on the instance's own node a
   month ahead**: from 1 December, where what a reader stands for reaches into the
   coming year and its list does not state that year, a line names the list, the year
   and how many of the reader's entries it stops, and from 1 January it stays until the
   list states the year and the instance restarts. The month is fixed: coverage is by
   whole years, so the gap always opens on 1 January, and the yearly edit is the one
   easily forgotten, which a line starting on New Year's Day would bring to notice only
   when a window did not open. The reader writes the line — maintenance's comes with
   its editor's *Not on*.

4. **Every root's file is read, a list named in two roots the later root's, whole.** In
   path-list order ([ADR-0031](0031-deployment-config-directory.md) decision 4): a list
   keeps the place it was first named in, and its name, its years and its days are the
   later root's together — never merged day by day, since a list merged from two files
   would be complete for what neither of them said. `default` is the later root's. The
   file is read once, at the start, as all configuration is until a reload in place
   (#31).

5. **Not built, and kept open: lists from outside.** Dates will come from outside later
   — an ICS file or feed, a Google calendar, or a Microsoft 365 calendar, where Teams
   calendars live — for holiday lists as for maintenance windows. None of it is built
   here, and no runtime dependency comes for it. A later source fills a list through a
   seam, a package as every service is
   ([ADR-0071](0071-what-a-restart-keeps-is-a-directory-of-files.md)), handing over
   days, which the calendar services return with any recurrence already expanded; and
   a list may one day say where it came from and be read-only on the page, as a
   configured rule is ([ADR-0104](0104-a-pin-is-one-block-on-what-it-silences.md)
   decision 8). A list is a mapping of named keys, so that such a key is an addition
   and never a change of the file's shape. Not now either, each to be added with no
   reader's entry changing: a list that includes another — a company's holidays on top
   of Bavaria's — and a command that drafts a year of a region's public holidays for an
   operator to check. The reader takes the file alone.

## Consequences

- A deployment writes its lists once, and a year's days, with the year, once a year. A
  list not brought forward stops what reads it in the year it does not state, rather
  than letting a window run on its days: loud on the instance's own node from 1 December
  before that year, and said where the reader stands.
- Maintenance's *Not on* is the first reader
  ([ADR-0150](0150-a-maintenance-entry-is-its-schedule-and-holds-while-a-window-of-it-is-open.md)
  decisions 13 and 16): a deployment sees on `/little-sister` what of the file cannot be
  read, and on `/little-sister/holidays` what a list stops of the entries that read it.
- A list renamed is a list whatever named it names no more, which each reader says in
  its own place.
- A region's lists repeat their country's holidays, about ten a year each, until a list
  may include another.
- A mistake warns on `/little-sister` the day it is written, whether or not anything
  reads the list yet, and the reader is strict: one mistake takes a whole list, one
  outside the lists the whole file.

## Alternatives considered

- **One list a deployment, no regions.** The cheapest, and enough for a deployment in
  one place; but it cannot say which of two places a window follows, and given lists
  later it would either read `true` as whichever list is the default — a change of the
  default moving every entry, which the zone an entry keeps is there to prevent — or
  change the format of what keeps it.
- **A region an iCalendar file**, copied once a year from a published calendar. No
  typing, and the names come with it; but it is a second reader for a wider format
  than the subset a schedule writes, and published calendars differ — yearly rules,
  timed events, days *observed*, several languages in one file — so a copied file is
  refused more often than a typed one, a whole region with it.
- **A holidays library.** A dependency with rules per region and a region setting, and
  the library's idea of a holiday where the deployment's is wanted: a company's days
  off are out of its reach.
- **A feed the engine reads.** Network from the engine, a refresh cycle and a failure
  mode, for a list that changes once a year; kept open as a source behind a seam
  (decision 5).
- **The years a list is complete for, inferred from its days.** It misreads a list that
  rightly has no day in a year (decision 2).
- **A file of any dated days, `days.yaml`**, a change freeze among them. Every reader
  the vision names wants days nobody works, and a list that meant anything else would
  mean something different to each.
