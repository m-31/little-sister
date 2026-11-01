# ADR-0150 — A maintenance entry is its schedule, and holds while a window of it is open

- **Status:** Accepted
- **Date:** 2026-11-01 (accepted 2026-10-31)
- **Related:** [ADR-0014](0014-maintenance-persistence.md) (the maintenance entry and
  its end — amended), [ADR-0141](0141-every-pin-is-one-thing-with-a-kind-and-the-envelope-lists-what-handles-a-part.md)
  (every pin in one file — decision 1 amended for maintenance),
  [ADR-0149](0149-a-deployments-holidays-are-named-lists-of-the-days-nobody-works.md)
  (the holiday list an entry's `not_on` names), [ADR-0120](0120-every-stored-time-is-an-instant.md)
  (decision 7: the configured zone, which an entry keeps in its text),
  [ADR-0032](0032-status-contribution-boundary.md) (rule 7: what cannot be read does
  not apply), [ADR-0107](0107-an-event-is-a-change-of-what-a-node-shows.md) (decisions
  1 and 5: a pin's rows, and a pin's end the first reading after a restart writes),
  [ADR-0145](0145-a-nodes-notes-tab-is-the-place-to-act-and-every-pin-leaves-an-entry.md)
  (decisions 4, 6, 7, 8 and 9: every end told, what an entry and the Copy document say
  — amended — and a line's pin a row of its node),
  [ADR-0132](0132-a-branch-keeps-the-period-of-what-it-shows-beside-the-log.md)
  (decision 2: one write), [ADR-0110](0110-what-every-node-last-showed-is-kept-beside-the-log.md)
  (decision 6: when a replayed pin's period began — amended),
  [ADR-0109](0109-a-node-says-its-children-are-complete.md) (decision 4: a pin whose
  part is away is suspended, and only its own end disposes of it),
  [ADR-0036](0036-addressable-reasons.md) (a line's pin),
  [ADR-0071](0071-what-a-restart-keeps-is-a-directory-of-files.md) (every service a
  package), [ADR-0104](0104-a-pin-is-one-block-on-what-it-silences.md) (a pin's block —
  decision 8: a rule the configuration declares is read-only on the page),
  [ADR-0080](0080-the-envelope-is-the-snapshot-published.md) (decision 1: a client shows
  what the page says), [ADR-0135](0135-a-handled-part-keeps-its-true-color-and-every-surface-says-by-what.md)
  (decision 8: *Handled*),
  [ADR-0147](0147-one-door-opens-a-nodes-notes-tab-in-a-drawer-over-the-wall.md)
  (decisions 2, 3 and 5: the door's number, the tab's blocks, and the question before
  a close drops what was written),
  [ADR-0072](0072-the-instance-reports-on-itself.md) (the instance's own lines)
- **Register:** [`../decisions.md`](../decisions.md)

## Context

Maintenance is to be planned and recurring (#35): *every weekday from 22:00 for eight
hours, not on holidays*, set on the page, a series ending at most a year away. The
round's walk-through settled how such a window reads the calendar — a start that is a
wall time in the entry's zone and a length in days or in hours, each window worked out
from its own date, iCalendar's recurrence set kept as its text — and its design pass,
put to Lex from 2026-10-31, settled the entry's shape in `pins.json`, its rows, the
upgrade, and the slice's landings. This record is the third landing, in two halves:
the model underneath (decisions 1 to 8), and what can then be seen — a window set ahead,
and what is planned on every surface (decisions 9 to 12), each of whose questions Lex
settled one at a time on the same day. The fourth landing is a series set and changed
on the page, the editor's repeat and the block's two rows together, so that no release
sets a series without *End now* beside *Clear*'s question (decisions 13 to 16); the one
question its build put, how a window an edit keeps is said, Lex settled on 2026-11-01.
The fifth landing is the editor's month, a day's window added or left out by a click on
it (decision 17). What Lex's walk of his instance found on 2026-11-01 is folded in where
each belongs, and an entry's note counts its windows, so that what came before says what
of them ran (decision 18).

## Decision

1. **A maintenance entry is its schedule, a recurrence set in RFC 5545 text, in the
   subset this library writes and reads.** `DTSTART` with a `TZID`, an IANA name, the
   zone written once and the only zone of the text; then either `DTEND`, an instant,
   for one window, or `DURATION` — `PnD`, days that follow the calendar, or `PTnHnMnS`,
   real time, to the second so that a one-off a window joins keeps the end typed for it
   (decision 14). A rule is `RRULE` with `FREQ` `DAILY`, `WEEKLY` or `MONTHLY` and
   `INTERVAL`; `BYDAY` for a week's days, and for a month one `BYMONTHDAY` counted from
   either end or one weekday of it, the first to the fourth or the last; `WKST` Monday
   only; and `UNTIL`, required, in UTC, at most a year after the first start. `RDATE`
   adds a start, with the length, or an interval of its own (`VALUE=PERIOD`, two
   instants); `EXDATE` leaves out the window that starts when it says. A `DTSTART` the
   rule would not pick is refused, as RFC 5545 leaves such a set undefined (section
   3.8.5.3), and so is everything else — `COUNT`, another frequency, a property or a
   part the subset has no use for — which fails toward alarming. Beside the text the
   entry keeps `not_on`, the key of the holiday list its rule leaves out, which has no
   line in RFC 5545, and `changed`, the windows changed alone, each by its start as
   `RECURRENCE-ID` keys one, with its end, the words why, who and when. `expires_at`
   leaves the entry's file: its end is its schedule's (decision 4). A one-off window is
   the same entry with one interval, `DTEND` its end and `DTSTART` its start: where it
   was first set, or the start *Starts* names (decision 11). An edit that names its end
   alone keeps that start — an open window's has passed, and a planned one's is moved
   by naming another — so that its text says what it covers, as a calendar reads it,
   and a one-off whose start lies ahead of its creation opened by the clock. An entry
   of the old shape is dropped as the file is read (decision 7).

2. **One implementation of the windows, on `zoneinfo`, and every reader asks it.** A
   window is worked out from its own date, never by adding a period to the last
   (ZBX-20162): its start the date at the first start's time of day, a wall time a night
   skips landing after the jump and one it repeats taking its first pass (RFC 5545
   section 3.3.5); its end that many days later at the same time of day, or that much
   real time later. So *22:00, eight hours* ends at 07:00 the night the clock springs
   forward and at 05:00 the night it falls back, and *Sunday 00:00, one day* is the whole
   of the 23-hour and of the 25-hour Sunday alike. A window belongs to the day it starts
   on; windows that overlap or touch are one. The rule's windows on the days the entry's
   list names are left out, and those in a year the list is not complete for
   ([ADR-0149](0149-a-deployments-holidays-are-named-lists-of-the-days-nobody-works.md)
   decision 2); a start or an interval added by hand stands whatever the list says. An
   entry whose list cannot be had has no windows at all, and holds nothing
   ([ADR-0032](0032-status-contribution-boundary.md) rule 7). Nothing else works out a
   window at runtime: the tree asks this one, once a schedule, and every surface asks
   the tree.

3. **The text is standard, and a test proves it, with one difference named.** A test
   reads every schedule the subset writes with `recurring-ical-events`, over
   `icalendar`, and compares its windows with these, both clock-change nights of two
   years among them. The two are a dependency of the test group alone, never of the
   library: `recurring-ical-events` is LGPL-3.0-or-later and brings three dependencies
   of its own. They agree on every start. They differ in one place, which the test
   holds them to: `recurring-ical-events` ends a window of hours its length after the
   wall time its start is written as, on the wall clock, so a window of hours that
   crosses a clock change ends an hour off there, and one starting at a time the night
   skips ends before it begins. RFC 5545 makes a length in hours exact (section 3.3.6),
   and so did the walk-through; the library keeps it so.

4. **An entry stands until its schedule ends, and holds while a window of it is open.**
   Its end, the one every surface reads, is the end of the last window its own text
   writes, a window changed alone included — so *Extend* or *End now* on the last
   window moves it — and its holiday list never moves it. A window the list leaves
   out, by a day it names, by a year it does not cover or by being unreadable, is shut,
   and the entry stands, holding nothing, as a pin whose part is away is suspended and
   only its own end disposes of it
   ([ADR-0109](0109-a-node-says-its-children-are-complete.md) decision 4): a list not
   brought forward for a year keeps that year's windows shut rather than ending the
   entry at the year's turn, before anybody could add the year. While an entry stands
   on nothing it says so where it is listed, naming the year its list does not cover
   and the day its windows stop applying, so that the year can be added before its
   first window (decision 10). An entry that holds nothing counts
   nowhere: its node shows what it reads, the snapshot carries no pin of it, no period
   of its node begins, and a reading gone stale reads as it would with nothing on its
   node.

5. **Open and closed are decided at the moment a snapshot is asked, and the tick decides
   them between two.** The tick opens every window that is due and closes every one
   that is past, a node's and a line's, each a row of its node, the first of a node's
   from what it showed
   ([ADR-0145](0145-a-nodes-notes-tab-is-the-place-to-act-and-every-pin-leaves-an-entry.md)
   decision 9): `pin-opened` and `pin-closed`, `line-pin-opened` and `line-pin-closed`,
   a close saying why, `clock`, or `hand` where an edit leaves no window open now. The
   last close of an entry is its end, one row, `pin-ended` or `line-pin-ended`, and its
   end told (decision 4 there); an entry that holds nothing when its schedule ends goes
   with its end told and no row, since it showed nothing. What one sweep finds due, with
   the acknowledgments that end in it, is one write
   ([ADR-0132](0132-a-branch-keeps-the-period-of-what-it-shows-beside-the-log.md)
   decision 2). An entry set while a window is open writes its set alone, so a one-off
   window from now reads exactly as a pin always did; one set before its first window
   writes nothing until that opens. A snapshot asked at the clock's moment opens and
   closes what is due first, with the same rows, so that no page shows a window open in
   the second after its end; one asked at a moment of its own reads the windows as the
   last tick left them. History replays an opening as a set and a close as an end. Each
   surface says these rows in its words: the Events page's chip *window opened* and
   *window closed*, *line's window opened* and *line's window closed*; History's *a
   window opened*, *a window closed*, and a line's; the Copy document's *a window opened
   on …*; and a period a closed window began *when its window closed*. On the Events
   page a row of a node's own pin or window where the node reports nothing of its own —
   its status and its reading both `UNDEFINED`, the Copy document's own test for such a
   node, read off the row so that an old row keeps its word as the tree changes — says
   *nothing of its own* for its status: a branch's window closing, a pin's end on it.
   Its tint and the *undefined* switch read its code, which the switch's title says, and
   its node's History says what it showed. The gap where the instance was not running,
   which no pin wrote, keeps *undefined*, and so does a pin's end on a node not read yet
   since a start, whose check reported what the log kept.

6. **A restart and an adopted file split what stands into what holds and what holds
   nothing.** An entry that holds is replayed as a pin always was; one that holds
   nothing stands, holding nothing, until its next window opens. A window that opened
   while the instance was down is a replay its log does not hold, its row an opening
   and its node's period begun at the window's start, not at the entry's creation
   ([ADR-0110](0110-what-every-node-last-showed-is-kept-beside-the-log.md) decision 6
   amended) — a one-off's too, where its start lies ahead of its creation, and one set
   now beginning at its creation, which its start is (decision 1). A window that closed
   meanwhile, on a node that showed `MAINTENANCE` at the stop, is
   the row of its close, written as a pin's end that ran out meanwhile is: by the
   node's first reading
   ([ADR-0107](0107-an-event-is-a-change-of-what-a-node-shows.md) decision 5), or, for
   a node nothing reports to, at the window's end. An adopted file's entry that held
   here and holds nothing in it closes; one that holds now and did not here opens.

7. **The upgrade is a clean break, with no word in the product.** An entry of the old
   shape, an `expires_at` and no schedule, is dropped as the file is read, with no line
   at the start and no import; the acknowledgments read on. A new entry carries no
   `expires_at`, so that no older reader takes a series for one pin in force from its
   set to its last date; an older release refuses the new file whole instead, which
   fails toward alarming and takes every pin with it. The CHANGELOG says both in one
   clause.

8. **Not built, and kept open: windows from outside, and a feed of ours.** Dates will
   come from outside later, for an entry's windows as for holiday lists — an ICS file
   or feed, a Google calendar, or a Microsoft 365 calendar, where Teams calendars live.
   None of it is built here, and no runtime dependency comes for it. A later source
   fills an entry's windows through a seam, a package as every service is
   ([ADR-0071](0071-what-a-restart-keeps-is-a-directory-of-files.md)), handing over
   dates and intervals, which the calendar services return with any recurrence already
   expanded, and the one implementation decides what is open; an entry may one day say
   where it came from and be read-only on the page, as a configured rule is
   ([ADR-0104](0104-a-pin-is-one-block-on-what-it-silences.md) decision 8), an added key
   and never a change of the entry's shape. A feed of planned maintenance, when one is
   published, gives each window its own start and end, never a rule with a length in
   hours: readers disagree across a clock change (decision 3), and a window written out
   says the same to every one of them.

9. **What holds and what is planned are listed apart on every surface, and what is
   planned counts nowhere.** The snapshot carries, beside each pin that holds, the
   window of it open now, whose end is its time left — never a series' schedule's end
   a year away — and, apart from it, the entry that stands and holds nothing now, a
   node's and a line's: a window set ahead, a series between two of its windows, or one
   whose holiday list keeps every window left shut, with its next window and what of
   its windows the list stops. One on a part not reported now is carried in that part's
   record, which such an entry alone now makes. *Handled* lists them under *Planned*,
   in maintenance's section after what is in maintenance, the soonest next window
   first, with a count of their own that says what it counts, a window set ahead being
   a window and any other entry a schedule, listed by its next window — *1 window and
   1 schedule on 2 nodes, the soonest first*
   ([ADR-0135](0135-a-handled-part-keeps-its-true-color-and-every-surface-says-by-what.md)
   decision 8); a node's page beneath its blocks, one line each, the node's own and its
   lines', each a door that opens the drawer at its block; the *Notes* tab in a section
   of its own beneath what stands; and the Copy document after its part's pins, *🛠️
   Planned — once, from … until …, by anna*. The door, ◇, the pill, the chips and the
   healthy fold count what holds alone, so that ◇'s number is what the tab lists under
   what stands
   ([ADR-0147](0147-one-door-opens-a-nodes-notes-tab-in-a-drawer-over-the-wall.md)
   decision 2), and the wall shows nothing of a planned window. A planned block is
   drawn without maintenance's tint, since it holds nothing: a one-off's says its
   sentence and *· starts in 6d*, the countdown after *until …* naming the start; a
   series' its sentence and *· next … · in 6d*, *· next …* and *· in 6d* each kept on
   one line and a line ending between them where the block is narrow. A one-off's
   *Edit* is the editor with
   *Starts* and its end filled, and its *Clear* asks nothing, as a one-off's always did.
   A series' *Edit* is the editor filled (decision 13), and its *Clear* asks first —
   *This ends every window of the schedule, those to come* — with *Clear the schedule*
   and *Keep it*; its window open is two rows (decision 15).

10. **An entry is said in one sentence, written once, as each surface writes an
    instant.** `schedule.sentence` writes it: the rule, the time of day its windows
    start at and how long each is, `until`, the entry's end, the windows added and left
    out by hand, and the list its rule leaves out by the list's name — *Every Saturday
    from 22:00 for 8 hours, until 2027-10-31 05:00:00, not on holidays in Bavaria* — and
    one window alone *Once, from … until …*. Its instants are written by the surface's
    own writer, a page's in the deployment's zone and time format and the Copy
    document's with their offset too, never a date of its own beside them; and the
    entry's zone is named beside its time of day where it is not the surface's, the
    instants being the surface's own, and a page keeps each instant's words whole, a
    line ending between them and never inside a date, as a block's own instants are
    kept. Every surface asks it, the envelope and the editor among them. **It says only
    what is still ahead** of the moment the surface is drawn,
    which it is handed: a window added counts while its start lies after that moment,
    and so does a start left out, and a schedule without a rule says its own first window
    only while that lies ahead too — *1 more window, until …* once it has begun — so that
    the window open now is said by its block's first row alone, and what has passed is
    History's to say. A length that is not whole minutes is said by its window's end,
    never by its seconds: *From 2026-11-01 14:37:12 to 2026-11-01 18:00:00*. Where an
    entry's list stops its windows, the same
    surfaces say why, in place of a next start or beside it: *applies not at all* and
    the startup record's reason, where the list cannot be had; *from 2028-01-01 00:00:00
    its windows do not apply: the list is not complete for 2028*, from the first year it
    does not state that a window of the rule starts in; and *no window is to open: each
    one left is on a day its list names*. The instance's own node says what the lists
    stop (decision 16).

11. ***Starts* sets a window ahead.** On the form for a new window and in a planned
    one-off's editor, above the end, read in the end field's grammar
    ([ADR-0014](0014-maintenance-persistence.md) decisions 21 and 22) in the
    configured zone, which the entry's text keeps, blank meaning now; a duration in the
    end field then counts from the start, and an end is an end. Refused, nothing
    written and the words back: a typed start that has passed, *leave Starts blank* in
    the reason; an end not after the start; a window too short for the slowest covered
    check's next run, counted from the start; and an end more than a year from now — so
    that nothing set on the page stands longer than a year from when it was set, the
    renewal ADR-0014 decision 13 ties to a year, which a year-long window starting any
    time would stretch toward two. The subset's year from the text's first window stays
    the file's, and the page's bound is the stricter. A planned window's editor fills
    *Starts* and keeps the stored start exactly while the field still reads it, as an
    end is kept ([ADR-0104](0104-a-pin-is-one-block-on-what-it-silences.md) decision
    5), and starts the window now where it is emptied; an open one-off's editor leaves
    it blank, its start having passed, and takes one only with a repeat (decision 13):
    with script *Starts* shows there once a repeat is chosen, and without script it
    stands with its hint to leave it blank unless one is.
    **A set that plans a window is answered at the tab, at its new block**: the
    drawer shows an answer other than its form's `next` rather than taking it for a
    write gone through, so it stays open on the block, which takes the focus, its
    sentence read at once with *Edit* and *Clear* beside it; a set that opens a window
    closes the drawer onto the wall, as every write that goes through does, and without
    script the tab is the page.

12. **The envelope carries what the page says**
    ([ADR-0080](0080-the-envelope-is-the-snapshot-published.md) decision 1), additive
    in the 3.1.0 that has not shipped, `schema_version` 3. Every maintenance item in
    `handled` gains `starts_at` and `until`, its `expires_at` the window open's end — a
    one-off's start, and its end twice — and `sentence`, the page's words. A node gains
    `planned`, beside `handled` and never among it: its own entry and its reported
    lines', a line's with its `slug`, the soonest first, each the pin's fields without
    `counts_as`, since it counts nothing until a window opens, with its next window's
    `starts_at` and `expires_at`, both null where none is to open, `until`, `sentence`
    and `why`, null where its list stops none. A line or a node not reported now
    carries its planned entry in its own record, `planned` beside `handled`, so that
    `entries.not_reported` and `nodes_not_reported` list what stands on or is planned
    for a part not reported now. The golden envelope carries a planned one-off, a
    series' window open and a series planned with no window to open — its holiday list
    one the instance cannot have, the null a decoder expecting a date breaks on — its
    scene set and read at one fixed instant, so that every run, on whatever day it is
    checked, sees the same windows. The fourth landing adds no field: an extended
    window's end is its item's `expires_at`, and a series' last window's `until` the
    same instant.

13. **The editor sets a repeat.** The Maintenance kind keeps its first look — *On*,
    *Note*, *Starts* and the end field — and gains *Repeats*: *Once*; every N days;
    every N weeks on the weekdays ticked, *weekend* and *working week* one click each,
    its start's weekday where none is ticked; every N months on a day counted from the
    month's start or its end, its start's day where none is written, or on the first to
    the fourth or the last of a weekday. A repeat or a later start opens the rest in
    place, the browser's own disclosure: the repeat's days, *Until*, *Not on* by its
    list's name, the zone — *Times in*, one of the IANA names, written as the text's
    `TZID` and every field read in it — and *Add an interval*; and beneath them what
    follows from them: each window added by hand with its ×, the next five windows — the
    first on the first day on or after *Starts* that the rule picks, which `DTSTART` is
    written as, and a clock-change night's marked with how long it really lasts, *23
    hours: the clocks go forward* — and the sentence, the last thing read before *Set
    maintenance*. With a repeat the end field is *Length*, a length alone, `8h` exact
    across a clock change too and `1d` calendar days, long enough for the slowest
    covered check's next run, which its placeholder asks for; a length is in no zone,
    so the zone the end field reads a time in is said under it for *Once* alone, and
    *Times in* names the repeat's. *Until* is required, a date alone taking in its day
    and shown back as typed, the date alone where it ends that day, at most a year from
    now — or, where an edit keeps the window open now (decision 15), a
    year from that window's start, as the subset counts its year from the earliest start
    in the text — which the field says. *Not on* is a box where one list can be read and
    a select where several can, the file's default first, and is disabled with why where
    the list cannot be read, the server refusing it: an entry that leaves out a list
    that cannot be read would never be told apart from one that applies. Without script
    *Preview*, *Add an interval*, an ×, *weekend* and *working week* are the form's
    buttons, each answered as a refusal is, in full — the editor back with what it would
    set beneath it, nothing written, the page saying it holds words somebody wrote
    (`data-ls-mine`) and never at the form's `next`, which the drawer takes for a write
    gone through. With script the part beneath the fields follows them, drawn by the
    same macro from `POST /pins/maintenance/preview`, which asks what a set asks, and
    the buttons do in place what they do without, a window added or taken out counting
    as words written for the drawer's question. A standing entry's editor is the same
    fields filled — a series' *Starts* at its rule's start in the window open now or
    else its next, never a window added by hand, whose time of day is not the rule's;
    its rule, its length, *Until*, *Not on*, its zone, and what it adds or leaves out by
    hand that is still to come; and a schedule without a rule *Once*, its window open or
    next by its start and its end — with *Save changes*. Refused, nothing written and
    the editor back as it was typed: a repeat without *Until* or past its year, without
    a length or with an end for one, a zone that is none, a list that cannot be read, a
    rule that picks no day between *Starts* and *Until*.

14. **A window set where an entry stands joins it**, one entry a place (#35's note,
    decision 2). The form offers every part, one an entry stands on *— a schedule stands
    on it*, with that entry's token; a window set there is added to the entry's schedule
    as an interval, the entry keeping its note and its creation, and the window's words
    are a note of their own beside it in the Notes history, *A window joins the schedule,
    from … until …*. The entry is replaced only where the person chooses *this replaces
    it*, which is an edit of it; a repeat or windows added by hand, set where an entry
    stands, are refused otherwise. A one-off, whose text carries no added interval, is
    rewritten as its window with a length — its `DTSTART` and a `DURATION` exact to the
    second, so that its end stays where it was typed — and the window joins it as an
    `RDATE` period.

15. **A series' window open is two rows.** The first is the window: *This node is in
    maintenance by anna until … · 7h left*, by whoever set the schedule, and after an
    extension *until …, extended by lex · 1h 20m left*, the time left the window's alone,
    the schedule's end standing in its sentence and never counting down. *Extend* —
    30 minutes and 1, 2 and 4 hours counted from the window's end, or *Until*, read as
    the end field is, from now, Enter in it pressing no preset — is an edit, its row the
    edit's, and **never shortens**: an *Until* not after the window's end is refused, the
    reason naming *End now*. An extension that reaches the next window's start joins the
    two. *End now* closes the window, *window closed · by hand*, the windows to come
    standing, and every part of a joined window ends with it; on the schedule's last
    window, which the rows say, it is the entry's end, *maintenance ended · by hand*.
    Each is kept beside the schedule as a window changed alone (decision 1), with the
    words why where they are given, which the Notes history keeps as a note of their own.
    The window is named by its start, so that an *Extend* or *End now* that arrives after
    it closed is refused as a stale edit is, saying when it closed and offering *Set
    maintenance* filled with the end asked for and the words — a window from now, which
    joins the schedule, or stands alone where the entry ended with it: nothing reopens a
    window by itself. The second row is the schedule, its sentence and *· next …*, the
    start after this window, or *· its last window*, with *Edit*, which shapes the windows
    to come — the window open now copied in as an added interval from its start to its
    current end, a start of the rule within it left out so that it keeps that end, and
    the changes on windows that passed dropped — and *Clear*, which asks, *This ends
    every window of the schedule, this one and those to come*. A start of the rule
    exactly at the kept window's end lies outside it and stays, and windows that touch
    are one (decision 2): an edit that starts the next window as the open one ends makes
    the two one longer window, its first row counting down to the joined end — meant,
    back-to-back windows being one maintenance. Each of the four is the
    browser's own disclosure around a form the refresh waits for, its accessible name
    saying how far it reaches — *Extend this node's window*, *End now this node's
    window*, *Edit this node's schedule*, *Clear this node's schedule*. On the wall, with
    *◇ details* on, the block is the first row's sentence; the drawer and the tab have
    both. A one-off keeps its one row, its *Clear* asking nothing. A window open at the
    moment its entry is set writes the set row alone, as a pin set does. The Copy
    document says the schedule beside the window: *🛠️ Maintenance — by anna, until …;
    its schedule: every day from 22:00 for 8 hours, until … · next …*.

16. **The instance says what the holiday lists stop**, on a child of its own,
    `/little-sister/holidays`
    ([ADR-0149](0149-a-deployments-holidays-are-named-lists-of-the-days-nobody-works.md)
    decision 3), read from what the tree holds and never a probe: for each list an entry
    names that cannot be read, from the start, how many entries it stops — *2
    maintenance entries that leave out the holiday list DE-BY apply not at all: …* — the
    line an entry's *applies not at all* leads to; and for each list not complete for a
    year in which a standing entry's windows start, from 1 December for the coming year
    and from 1 January for the year begun, until the list states the year and the
    instance restarts — *holidays in Bavaria (DE-BY) is not complete for 2028: from
    2028-01-01 00:00:00 the windows of 1 maintenance entry do not apply. State 2028 in
    holidays.yaml, its days with it, and restart the instance.* Each warns.

17. **The editor's month** (#35's note, decision 4). First beneath the fields, before
    what is read out of them, stands the month: its name between its paging — the year
    and the month before, the month and the year after — from this month to a year on,
    as far as anything set on the page reaches, and six weeks from the Monday on or
    before its first day, each day of it a button of the form; a day of the month before
    or after stands for where it is, drawn and not read. A day shows its hours — each
    window that starts on it, from and to, a window belonging to the day it starts on —
    and on a phone instead its span as a bar, the hours of it any window covers, a
    night's window the evening of one day and the morning of the next; the time of a
    window it leaves out struck; a night the clocks change its note, *+1h* or *−1h*; and
    a day the holiday list names marked. Its accessible name, its title too, says the
    rest: its date, its windows and a clock-change night's real length, the list's name
    for it, when the clocks move, and what a click does — *Saturday, 7 November: a
    window from 22:00 to 06:00 the next day. A click leaves its window out.* A click
    adds or leaves out a day's window, each listed beneath with its ×, nothing written:
    the rule's window left out, and a start left out put back; on a day the holiday
    list leaves out, the window added back as a start of its own, which stands whatever
    the list says (#35's note, decision 6); a start or a window added by hand taken out;
    and on a day without a window, one at the rule's time of day and of its length. A
    day whose window has begun is not for a click — *Extend* and *End now* change the
    window open now — nor is a schedule without a rule's own window, which *Starts* and
    the end field set. The month shown is the first window's until somebody pages it or
    clicks a day of it, and from then the one the form keeps, `month`, which every
    button gives back. Without script every day and every page is a button answered as
    decision 13's are; with script the grid is one tab stop that the arrow keys move
    across, as a date picker's is — a day, a week, the week's first and last day in the
    month, Page Up and Page Down a month and with Shift a year — paging onto the month
    before or after where a move leaves this one, a day or a page done in place and the
    focus kept on it. The month is a part of its own beside the live region that says
    the windows listed, the next windows and the sentence, so that a screen reader hears
    what the fields would set as they change, not every day again. **A standing entry's
    editor draws its month only when it is asked for** — by *Preview* without script,
    and with script as its *Edit* opens, through the same server rendering, put in
    place beside the live region, which says nothing again — since a page lists an
    editor for every entry that stands, *Handled* one for each, and a month is most of
    each one's weight, some 22 KB of markup and 5 ms of render; the form for a new
    window draws its month as its fields are read, and the refusal's page, one editor
    alone, draws it at once. *Handled* still grows by each schedule's block and its
    editor's fields — measured with a window open on half its series and the rest
    planned, each series adds some 16.8 KB of markup, 0.7 KB gzipped and 0.7 ms of
    render, where with its month it added 37.4 KB, 4.2 KB and 1.6 ms — and the whole
    editor drawn only when its *Edit* opens was declined on Lex's word of 2026-11-01: a
    request at every *Edit*, and a second path for a page without script, against 0.7 KB
    and 0.7 ms a schedule. And an open one-off's window, whose start is its own, is
    written with a length where a window is added beside it, by hand or by a click: from
    its start to the end typed, as decision 14 writes a one-off a window joins.

18. **An entry's note counts its windows, and what came before says what of them ran**
    (Lex, 2026-11-01, on the walk of his instance, where History said maintenance on a
    schedule none of whose windows had opened). The note is the one record that ties a
    window to its entry and outlives the log's pruning — an Events row names no entry,
    and the schedule's text counts windows that never held — so the tree tells the notes
    what it sees of an entry's windows, as it tells every end
    ([ADR-0145](0145-a-nodes-notes-tab-is-the-place-to-act-and-every-pin-leaves-an-entry.md)
    decision 4): the window that holds as the entry is set or edited, as the tick opens
    one and as a start replays one, and that none holds as an edit or the tick closes
    one and as a start finds it closed; an adoption tells nobody, its notes coming with
    its pins. The note counts each window that held, once: one open as its entry is set,
    which no tick opened — *Starts* left blank — and the open window of one set from now
    that is given a repeat, which it keeps; a restart inside a window counts it no more;
    one that opened and closed while the instance was down is counted nowhere, as no row
    and no period says it; one open at the stop closes at its own end. Beside the count
    it keeps how long those that closed held, each from when it began to hold, and the
    last that closed, from when until when and how — why in the log's words, and by whom
    where a person closed it — its start and its end said nowhere yet, so that a line
    naming them later needs nothing the file lacks. It says too what its entry was
    planned as, in the nouns *Handled* counts in (decision 9): a *window*, one set ahead;
    a *schedule*, every other entry with windows, which an edit that makes it one window
    leaves a schedule; and one window set from now neither, which keeps the words a pin
    always had. **The two ends are kept apart.** The history entry and the line on what
    came before say the entry's own — *by hand, by pan*, or, where it ended at its end,
    *with its last window*, a window's *with its window* — and what ran in place of how
    long it stood, which would read as maintenance from its set to its end: *Planned as
    a schedule by pan · ended: with its last window*, *3 windows ran, 2h 10m in all*, *1
    window ran, 1m 11s*, *no window opened*, a window's *it ran 1m 11s* or *it never
    opened*. How the last window closed is said by its block alone, on the *Notes* tab
    while the entry stands: *· 3 windows ran, the last closed by hand, by pan*, the
    window open now not among them. The Copy document writes *set* where *from* would
    read as in maintenance since then, and the noun: *🛠️ Maintenance, planned as a
    schedule — by pan, set …: no window has opened yet, and it stands*, *3 windows have
    opened*, and once it has ended *…: 3 windows ran, 2h 10m in all, until …, ended:
    with its last window*. What came before still lists only entries that ended. A note
    written before notes counted windows counts none and says what it said; what a note
    counts reaches no snapshot, and the envelope carries none of it.

## Consequences

- The page sets one window, from now or from a start ahead, or a series, and changes
  either where its block stands; the file says each in the new shape. A series' window
  open is lengthened or ended alone, and its schedule changed for the windows to come.
- One entry stands on a part: a second window set there joins it, and a second
  schedule replaces it only by choice. Several entries a part are the round's *Later*.
- A one-off a window joined is a series in its text, a `DTSTART` with a `DURATION` and
  an added interval, and its block the two rows of one.
- An edit made while a window is open keeps that window in its text, an interval and a
  start left out, until an edit after it has closed drops them.
- A day's window is left out, put back, added back from a holiday or added on the month
  as on the fields, the text writing an `EXDATE` or an `RDATE`; what each day shows is
  read off the windows themselves (`schedule.days`), so the month and the next windows
  never disagree.
- An open one-off with a window added beside it, by hand or on the month, is a schedule
  without a rule, its own window from its start to the end typed, as one a window
  joins is.
- A page that lists what stands grows by each entry's block and its fields, never by a
  month: an editor asks the server for its month the first time it opens, and without
  script it takes a *Preview* to see it.
- A window set ahead holds nothing until its start: listed under *Planned*, counted on
  no door, and shown nowhere on the wall. The drawer staying open on it is the
  confirmation that the day and the time typed were read as meant.
- The maintenance pins standing at the upgrade are gone from it, to be set again, and a
  rollback past this release refuses the file whole and loses every pin; keep a copy of
  `var/state/pins.json` where a rollback may be needed.
- An entry whose end has passed when it is set holds nothing and goes at the next tick,
  told and with no row. The form never writes one: it refuses an end that has passed.
- A one-off window's end is kept to the second across a restart, as its text says it,
  and so is a start set ahead, which *Starts* reads to the second.
- A one-off's start is its own: an edit no longer moves it to the edit's moment, and a
  window set ahead opens with its row and its period at its start. A one-off a build of
  the first half wrote and then edited reads as having opened at that edit — a file of
  this unreleased round's alone.
- What a line's window that opened or closed while the instance was down changed, the
  node's first reading says as a reading's row: which windows held on a line at the
  stop is not kept. A window that both opened and closed while the instance was down
  leaves no row, as nothing saw it.
- A series is checked with a library its tests run against and its users never install.
- An entry's note counts its windows from this release on: an entry set before it says
  what it said, and a window that opened and closed while the instance was down is
  counted nowhere, as no row says it.
- A row a node's own pin or window wrote where the node reports nothing of its own says
  *nothing of its own* on the Events page, and the *undefined* switch still finds it.

## Alternatives considered

- **A shape of our own** — fields for a rule, a length and dates. As small to read, but
  no tool reads it, a file or feed from outside arrives in RFC 5545 and would be
  translated in, and RFC 5545 has already decided every case a shape of our own would
  have to decide again.
- **`dateutil.rrule` or `recurring-ical-events` at runtime.** A dependency of the
  library — the latter under the LGPL, with three of its own — and its idea of a length
  across a clock change, which is not the walk-through's; the subset is small enough to
  write on `zoneinfo`, and the second is the test's instead.
- **Open and closed decided by the tick alone.** A page asked in the second after a
  window's end would show it open, and one asked in the second after its start would
  not; the snapshot's moment decides, on Lex's word.
- **An entry ending at the last window its list leaves standing.** It would end an
  entry whose list was not brought forward for the coming year at the turn of the year,
  before anybody could add the year, and the windows would be gone when the list came;
  the schedule's own end decides, and a list that is not complete keeps the year's
  windows from opening, which is said where the reader stands.
- **The old pins read on, as one-off windows.** A compatibility reader, which ADR-0014
  rules out; and naming each one dropped at the start, which the design pass first
  had, said in the product what the CHANGELOG says once.
- **A series shown as its next window alone, or with a note-only *Edit*, until the
  fourth landing.** The first leaves the surfaces saying less than the model knows;
  the second builds an editor the fourth landing throws away.
- **A planned one-off said with a subject, as an open one is, or by its start and
  length alone.** The first puts two shapes of row under one heading; the second
  hides the end the person typed, which is the one they check.
- **One flat `planned` per node with `counts_as`, or a structured reason.** The first
  puts a line not reported now in two places and lets a planned item look like one in
  force; the second brings the holiday lists' keys into the contract with no reader,
  and every client would build the page's sentence for itself.
- ***Starts* with the zone chosen, or with the sentence beneath it, in the third
  landing.** A select before anyone asked, and a preview the fourth landing builds
  around the repeat.
- **The instance's line built with what is planned, or not at all.** A contributor only
  a file written by hand could wake, or decision 6 of #35's note dropped where the
  operator looks; it came with *Not on*.
- **A window an edit keeps said in both rows, or counted for the entry's life** (Lex,
  2026-11-01). The first says tonight's window twice while it is open; the second keeps
  a window that passed counted in every sentence after it.
- **An edit keeping the rule's window of today beside the one kept.** A longer length
  would lengthen the window open now, which *Extend* and *End now* alone change.
- **A window set where an entry stands refused, or a second entry beside it.** The
  first sends every second window through *Clear*; the second is the round's *Later*.
- **A one-off a window joins refused, or kept to whole minutes.** The subset's one-off
  carries one interval, and a length cut to the minute would move the end typed.
- **Every day of the month a tab stop with script, or a picker of its own.** Forty-two
  stops on the way to *Preview*; and a picker reads dates in a second grammar beside the
  end field's, which the server reads.
- **The month in the live region with the rest.** Every keystroke in a field would have
  every day of the month read out again.
- **Every standing entry's editor drawn with its month.** *Handled* grew by a month and
  its render with every series, for editors most of which nobody opens.
- **A day of the month before or after clickable.** It would act on a month not in
  view; a move onto one pages there first.
- **A day's bar of the windows that start on it alone.** A night's window would show as
  a sliver at the end of its day, and its morning nowhere.
- **What ran counted from the log, or from the schedule's text** (Lex, 2026-11-01). An
  Events row names no entry and is pruned, and the text counts windows that never held
  — one wholly inside the instance's downtime, one its holiday list shut; the note alone
  ties a window to its entry and outlives the pruning.
- **One end for both, *1 window ran, 1m 11s, ended by hand, by pan*.** It reads either
  way, and a series whose last window closed at its end and which was cleared by hand
  later would say the wrong one.
- **The word read off the tree, or *nothing of its own* for every node that reports
  nothing above nodes beneath** (Lex, 2026-11-01). The first changes an old row's word
  as the tree changes; the second takes the instance's own restart-gap rows too, which
  are undefined because nothing watched. Neither the log rewritten nor the rolled-up
  status: the filter and the tint read the row's own code.
