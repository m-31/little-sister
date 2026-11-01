"""A maintenance entry stands for its schedule, and holds while a window of it is open
(ADR-0150).

The tick opens and closes an entry's windows, each a row of its node, a line's beside a
node's, and an entry ends at the close its schedule has nothing after, that close its
one row; an entry set while a window is open writes its set alone, and one edited to
hold nothing now closes the window by hand. A snapshot at the clock's moment decides
open and closed as the tick would. A restart and an adopted file split what stands into
what holds and what holds nothing, and a window that closed while the instance was down
is its node's row. A holiday list leaves out the rule's windows on its days and in the
years it is not complete for, and one that cannot be had leaves an entry nothing to
hold; an entry that holds nothing counts nowhere, and stands until its schedule ends.
"""
from __future__ import annotations

import json
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from unittest import TestCase, mock

from little_sister import instants
from little_sister.holidays import HolidayList, Holidays
from little_sister.notes import Context, Note, NoteBook, Tally
from little_sister.pins import MAINTENANCE as PIN_MAINTENANCE
from little_sister.pins import Pin
from little_sister.reasons import Entry as Line
from little_sister.schedule import Schedule
from little_sister.status import StatusCode
from little_sister.tree import (
    ENDED_CLOCK,
    ENDED_GONE,
    ENDED_HAND,
    StatusSnapshot,
    StatusTree,
    events_from_payload,
)

OK, WARN, ERROR = StatusCode.OK, StatusCode.WARN, StatusCode.ERROR
MAINTENANCE, UNDEFINED = StatusCode.MAINTENANCE, StatusCode.UNDEFINED

#: Every night from 22:00 for two hours, Monday 2 to Wednesday 4 November 2026 — in
#: Berlin, an hour ahead of UTC then, so from 21:00 to 23:00 UTC.
NIGHTLY = Schedule.parse(
    "DTSTART;TZID=Europe/Berlin:20261102T220000\nDURATION:PT2H\n"
    "RRULE:FREQ=DAILY;UNTIL=20261104T230000Z")
#: The same nights from Tuesday on.
FROM_TUESDAY = Schedule.parse(
    "DTSTART;TZID=Europe/Berlin:20261103T220000\nDURATION:PT2H\n"
    "RRULE:FREQ=DAILY;UNTIL=20261104T230000Z")
#: The last two nights of 2026 and the first of 2027.
YEAR_END = Schedule.parse(
    "DTSTART;TZID=Europe/Berlin:20261230T220000\nDURATION:PT2H\n"
    "RRULE:FREQ=DAILY;UNTIL=20270101T230000Z")


def _utc(day: int, hour: int, minute: int = 0, *, month: int = 11,
         year: int = 2026) -> datetime:
    return datetime(year, month, day, hour, minute, tzinfo=UTC)


BEFORE = _utc(2, 20)
FIRST, FIRST_CLOSE = _utc(2, 21), _utc(2, 23)
SECOND, SECOND_CLOSE = _utc(3, 21), _utc(3, 23)
LAST, LAST_CLOSE = _utc(4, 21), _utc(4, 23)
NIGHTS = (FIRST, FIRST_CLOSE, SECOND, SECOND_CLOSE, LAST, LAST_CLOSE)
LINES = (Line("slow", "queries are slow", code=ERROR),
         Line("disk", "disk at 91%", code=WARN))


class _Clock:
    """The clock the tree reads, which a test sets."""

    def __init__(self, at: datetime) -> None:
        self.at = at

    def __call__(self) -> datetime:
        return self.at


class _Kept:
    """The pins file, as a store that remembers the last table saved."""

    def __init__(self) -> None:
        self.nodes: dict[str, Pin] = {}
        self.lines: dict[tuple[str, str], Pin] = {}

    def save(self, entries, entry_pins=None, acknowledged=None,
             lines_acknowledged=None) -> None:
        self.nodes = dict(entries)
        self.lines = dict(entry_pins or {})


class _WindowCase(TestCase):
    """A tree on a clock the test sets, its pins written through, every end it tells
    heard, and ``/db`` failing on one of its two lines, read an hour before the first
    window."""

    def setUp(self) -> None:
        self.clock = _Clock(BEFORE - timedelta(hours=1))
        patcher = mock.patch.object(instants, "now", self.clock)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.kept = _Kept()
        self.ends: list[tuple[str, str, str, str]] = []
        self.tree = self.new_tree()
        self.tree.upsert("/db", ERROR, list(LINES), members=True)
        self.count = len(self.tree.recent_events())

    def new_tree(self) -> StatusTree:
        tree = StatusTree(pin_store=self.kept)
        tree.on_pin_end(lambda path, slug, pin, why, by, when:
                        self.ends.append((path, slug, why, by)))
        return tree

    def at(self, *moments: datetime, tree: StatusTree | None = None) -> None:
        """The clock at each of ``moments`` in turn, and the tick there."""
        for moment in moments:
            self.clock.at = moment
            (tree or self.tree).sweep_expired()

    def rows(self, tree: StatusTree | None = None, path: str = "/db"
             ) -> list[tuple[str, StatusCode, StatusCode, str]]:
        """The rows of ``path`` written since the setup: the cause, what the node
        showed before and after, and why an end ended."""
        return [(event.cause, event.old, event.new, event.ended)
                for event in (tree or self.tree).recent_events()[self.count:]
                if event.path == path]

    def node(self, path: str = "/db", tree: StatusTree | None = None
             ) -> StatusSnapshot:
        snapshot = (tree or self.tree).snapshot(path)
        assert snapshot is not None
        return snapshot

    def shows(self, path: str = "/db", tree: StatusTree | None = None) -> StatusCode:
        return self.node(path, tree).own_code

    def nightly(self, *, line: str = "", not_on: str = "",
                schedule: Schedule = NIGHTLY) -> Pin:
        """The nightly backup set on ``/db``, or on its line ``line``, now."""
        if line:
            write = self.tree.set_entry_maintenance(
                "/db", line, "reindex", schedule=schedule, not_on=not_on,
                set_by="ada")
        else:
            write = self.tree.set_maintenance("/db", "nightly backup",
                                              schedule=schedule, not_on=not_on,
                                              set_by="ada")
        self.assertTrue(write.applied)
        assert write.current is not None
        return write.current

    def restarted(self, at: datetime) -> StatusTree:
        """A new process on what this one kept — its log, through the file's own
        shape, and its pins — started at ``at``."""
        self.clock.at = at
        new = self.new_tree()
        new.restore_events(events_from_payload(
            json.loads(json.dumps(self.tree.events_payload()))))
        new.restore_maintenance(dict(self.kept.nodes), now=at,
                                entry_pins=dict(self.kept.lines))
        return new


class TheTickTests(_WindowCase):
    """The tick opens and closes an entry's windows, each a row of its node, and the
    last close is the entry's end, its one row."""

    def test_a_series_set_before_its_first_window_holds_nothing_and_writes_nothing(
            self):
        entry = self.nightly()
        self.assertEqual(self.shows(), ERROR)
        self.assertEqual(self.rows(), [])
        self.assertEqual(self.tree.pins(), ({"/db": entry}, {}), "it stands")
        self.assertEqual(self.kept.nodes, {"/db": entry}, "and is written through")

    def test_each_window_opens_and_closes_with_a_row_and_the_last_close_ends_it(self):
        self.nightly()
        self.at(FIRST)
        self.assertEqual(self.shows(), MAINTENANCE)
        self.assertEqual(self.tree.recent_events()[-1].timestamp, FIRST,
                         "dated by the tick that opened it")
        self.at(FIRST_CLOSE)
        self.assertEqual(self.shows(), ERROR)
        self.assertEqual(self.ends, [], "a window closed, and nothing ended")
        self.assertIn("/db", self.kept.nodes, "the entry stands for the next")
        self.at(SECOND, SECOND_CLOSE, LAST, LAST_CLOSE)
        self.assertEqual(self.rows(), [
            ("pin-opened", ERROR, MAINTENANCE, ""),
            ("pin-closed", MAINTENANCE, ERROR, ENDED_CLOCK),
            ("pin-opened", ERROR, MAINTENANCE, ""),
            ("pin-closed", MAINTENANCE, ERROR, ENDED_CLOCK),
            ("pin-opened", ERROR, MAINTENANCE, ""),
            ("pin-ended", MAINTENANCE, ERROR, ENDED_CLOCK)])
        self.assertEqual(self.ends, [("/db", "", ENDED_CLOCK, "")])
        self.assertEqual((self.tree.pins(), self.kept.nodes), (({}, {}), {}))

    def test_a_tick_between_two_windows_writes_nothing(self):
        self.nightly()
        self.at(FIRST, FIRST_CLOSE)
        count = len(self.tree.recent_events())
        self.at(FIRST_CLOSE + timedelta(hours=1), SECOND - timedelta(seconds=1))
        self.assertEqual(len(self.tree.recent_events()), count)

    def test_a_set_while_a_window_is_open_writes_the_set_alone(self):
        self.clock.at = FIRST + timedelta(minutes=30)
        self.nightly()
        self.at(FIRST + timedelta(minutes=31), FIRST_CLOSE)
        self.assertEqual(self.rows(), [
            ("pin-set", ERROR, MAINTENANCE, ""),
            ("pin-closed", MAINTENANCE, ERROR, ENDED_CLOCK)])

    def test_an_edit_that_leaves_no_window_open_closes_it_by_hand(self):
        self.clock.at = FIRST + timedelta(minutes=30)
        entry = self.nightly()
        write = self.tree.set_maintenance(
            "/db", "nightly backup", schedule=FROM_TUESDAY, set_by="ben",
            expected_set_at=entry.token)
        self.assertTrue(write.applied)
        self.assertEqual(self.rows()[-1],
                         ("pin-closed", MAINTENANCE, ERROR, ENDED_HAND))
        self.assertEqual((self.shows(), self.ends), (ERROR, []), "it stands")
        self.at(SECOND)
        self.assertEqual(self.rows()[-1][0], "pin-opened")

    def test_clearing_one_that_holds_nothing_writes_no_row_and_tells_its_end(self):
        entry = self.nightly()
        write = self.tree.clear_maintenance("/db", by="ben",
                                            expected_set_at=entry.token)
        self.assertTrue(write.applied)
        self.assertEqual(self.rows(), [])
        self.assertEqual(self.ends, [("/db", "", ENDED_HAND, "ben")])
        self.assertEqual((self.tree.pins(), self.kept.nodes), (({}, {}), {}))

    def test_a_line_s_windows_are_rows_of_its_node(self):
        self.nightly(line="slow")
        self.assertEqual((self.rows(), self.shows()), ([], ERROR))
        self.at(FIRST)
        self.assertEqual(self.shows(), WARN, "the slow line held, the disk's warning")
        self.at(FIRST_CLOSE, SECOND, SECOND_CLOSE, LAST, LAST_CLOSE)
        self.assertEqual(self.rows(), [
            ("line-pin-opened", ERROR, WARN, ""),
            ("line-pin-closed", WARN, ERROR, ENDED_CLOCK),
            ("line-pin-opened", ERROR, WARN, ""),
            ("line-pin-closed", WARN, ERROR, ENDED_CLOCK),
            ("line-pin-opened", ERROR, WARN, ""),
            ("line-pin-ended", WARN, ERROR, ENDED_CLOCK)])
        self.assertEqual(self.ends, [("/db", "slow", ENDED_CLOCK, "")])
        self.assertEqual(self.kept.lines, {})

    def test_a_line_s_and_its_node_s_windows_open_in_one_write(self):
        self.nightly(line="slow")
        self.nightly()
        self.at(FIRST)
        opened = list(self.tree.recent_events()[self.count:])
        self.assertEqual([(event.cause, event.old, event.new) for event in opened], [
            ("line-pin-opened", ERROR, WARN),
            ("pin-opened", WARN, MAINTENANCE)])
        self.assertEqual({event.timestamp for event in opened}, {FIRST})

    def test_a_reap_takes_what_holds_nothing_and_writes_it_through(self):
        self.nightly()
        self.nightly(line="slow")
        self.assertEqual(self.tree.reap_uncovered(["/elsewhere"]), ["/db"])
        self.assertEqual(sorted(self.ends), [("/db", "", ENDED_GONE, ""),
                                             ("/db", "slow", ENDED_GONE, "")])
        self.assertEqual((self.kept.nodes, self.kept.lines), ({}, {}))
        self.assertEqual(self.rows(), [], "nothing showed them")


class TheSnapshotTests(_WindowCase):
    """Open and closed are decided at the moment a snapshot is asked: what the tick
    would open or close a moment later, a snapshot at the clock's moment opens or
    closes, with its rows; one asked at a moment of its own reads the windows as the
    tick left them."""

    def test_a_snapshot_at_the_clock_s_moment_opens_and_closes_before_the_tick(self):
        self.nightly()
        self.clock.at = FIRST + timedelta(seconds=1)
        self.assertEqual(self.shows(), MAINTENANCE)
        self.assertEqual(self.rows(), [("pin-opened", ERROR, MAINTENANCE, "")])
        self.assertIn("/db", self.kept.nodes)
        self.clock.at = FIRST_CLOSE
        self.assertEqual(self.shows(), ERROR)
        self.at(FIRST_CLOSE + timedelta(seconds=1))
        self.assertEqual(len(self.rows()), 2, "and the tick finds nothing left to do")

    def test_one_asked_at_a_moment_of_its_own_opens_nothing(self):
        self.nightly()
        snapshot = self.tree.snapshot("/db", now=FIRST + timedelta(seconds=1))
        assert snapshot is not None
        self.assertEqual(snapshot.own_code, ERROR)
        self.assertEqual(self.rows(), [])


class WhatHoldsNothingTests(_WindowCase):
    """An entry that holds nothing counts nowhere: its node shows what it reads, its
    parent counts that, the snapshot carries no pin, and a reading gone stale reads as
    it would with nothing on its node."""

    def test_it_counts_nowhere_until_a_window_opens(self):
        self.tree.upsert("/site/db", ERROR, list(LINES), members=True)
        self.tree.set_maintenance("/site/db", "nightly backup", schedule=NIGHTLY,
                                  set_by="ada")
        db = self.node("/site/db")
        self.assertEqual((db.own_code, db.maintenance, db.maintenance_entry),
                         (ERROR, False, None))
        self.assertEqual(self.node("/site").code, ERROR)
        self.at(FIRST)
        db = self.node("/site/db")
        assert db.maintenance_entry is not None
        self.assertEqual((db.own_code, db.maintenance, db.maintenance_entry.note),
                         (MAINTENANCE, True, "nightly backup"))
        self.assertNotEqual(self.node("/site").code, ERROR)

    def test_a_stale_reading_reads_as_it_would_with_nothing_on_its_node(self):
        for path in ("/s/a", "/s/b"):
            self.tree.upsert(path, OK, stale_after=300.0)
        self.tree.set_maintenance("/s/a", "nightly backup", schedule=NIGHTLY,
                                  set_by="ada")
        self.clock.at = BEFORE
        a, b = self.node("/s/a"), self.node("/s/b")
        self.assertTrue(a.stale)
        self.assertEqual((a.code, a.own_code, a.stale), (b.code, b.own_code, b.stale))


class TheHolidaysTests(_WindowCase):
    """A holiday list leaves out the rule's windows on its days and in the years it is
    not complete for, and stops nothing else; one that cannot be had leaves an entry
    nothing to hold, and it stands, holding nothing, until its schedule ends."""

    def use(self, *, complete: frozenset[int] = frozenset({2026}),
            dates: dict[date, str] | None = None) -> None:
        self.tree.use_holidays(Holidays(lists={"DE-BY": HolidayList(
            "DE-BY", "holidays in Bavaria", complete, dates or {},
            Path("holidays.yaml"))}))

    def test_a_rule_s_window_on_a_listed_day_does_not_open(self):
        self.use(dates={date(2026, 11, 3): "a day off"})
        self.nightly(not_on="DE-BY")
        self.at(*NIGHTS)
        self.assertEqual([row[0] for row in self.rows()],
                         ["pin-opened", "pin-closed", "pin-opened", "pin-ended"])

    def test_a_year_the_list_is_not_complete_for_holds_nothing_and_ends_nothing(self):
        self.use()
        self.clock.at = _utc(30, 12, month=12)
        self.nightly(not_on="DE-BY", schedule=YEAR_END)
        self.at(_utc(30, 21, month=12), _utc(30, 23, month=12),
                _utc(31, 21, month=12), _utc(31, 23, month=12))
        self.assertEqual([row[0] for row in self.rows()], [
            "pin-opened", "pin-closed", "pin-opened", "pin-closed"])
        self.assertEqual(self.ends, [], "a window of 2027 is to come in its schedule")
        self.at(_utc(1, 21, month=1, year=2027))
        self.assertEqual(self.shows(), ERROR, "2027's is left out")
        self.at(_utc(1, 23, month=1, year=2027))
        self.assertEqual(self.ends, [("/db", "", ENDED_CLOCK, "")])
        self.assertEqual(len(self.rows()), 4, "its end changes nothing it shows")
        self.assertEqual(self.tree.pins(), ({}, {}))

    def test_a_list_that_cannot_be_had_leaves_nothing_to_hold(self):
        self.tree.use_holidays(Holidays(unreadable={"DE-BY": "a day written twice"}))
        self.nightly(not_on="DE-BY")
        self.nightly(line="slow", not_on="ACME")
        for moment in (FIRST, SECOND, LAST):
            self.at(moment)
            self.assertEqual(self.shows(), ERROR)
        self.assertEqual(self.rows(), [])
        self.assertEqual([list(table) for table in self.tree.pins()],
                         [["/db"], [("/db", "slow")]], "both stand, holding nothing")
        self.at(LAST_CLOSE)
        self.assertEqual(self.tree.pins(), ({}, {}), "until their schedule ends")
        self.assertEqual(sorted(self.ends), [("/db", "", ENDED_CLOCK, ""),
                                             ("/db", "slow", ENDED_CLOCK, "")])
        self.assertEqual(self.rows(), [])


class TheRestartTests(_WindowCase):
    """A restart splits what the pins file keeps into what holds and what holds
    nothing; a window that opened while the instance was down is a replay its log does
    not hold, its period begun at the window's start, and one that closed is the row of
    its close."""

    def test_one_between_two_windows_holds_nothing_and_the_next_opens_it(self):
        self.nightly()
        self.nightly(line="slow")
        new = self.restarted(FIRST_CLOSE + timedelta(hours=1))
        count = len(new.recent_events())
        self.assertFalse(new.upsert("/db", ERROR, list(LINES), members=True),
                         "its first reading changes nothing")
        self.assertEqual((self.shows(tree=new), len(new.recent_events())),
                         (ERROR, count))
        self.at(SECOND, tree=new)
        self.assertEqual([event.cause for event in new.recent_events()[count:]],
                         ["line-pin-opened", "pin-opened"])

    def test_a_window_that_opened_meanwhile_began_at_its_start(self):
        self.nightly()
        new = self.restarted(FIRST + timedelta(minutes=30))
        self.assertEqual(self.rows(new)[-1], ("pin-opened", ERROR, MAINTENANCE, ""))
        new.upsert("/db", ERROR, list(LINES), members=True)
        current = new.history("/db")[-1]
        self.assertEqual((current.code, current.since, current.cause),
                         (MAINTENANCE, FIRST, "pin-opened"))

    def test_a_window_open_across_it_continues_and_writes_nothing(self):
        self.nightly()
        self.at(FIRST)
        new = self.restarted(FIRST + timedelta(minutes=30))
        count = len(new.recent_events())
        self.assertFalse(new.upsert("/db", ERROR, list(LINES), members=True))
        self.assertEqual((len(new.recent_events()), self.shows(tree=new)),
                         (count, MAINTENANCE))

    def test_a_window_that_closed_meanwhile_is_the_first_reading_s_row(self):
        self.nightly()
        self.at(FIRST)
        new = self.restarted(FIRST_CLOSE + timedelta(hours=1))
        count = len(new.recent_events())
        self.assertTrue(new.upsert("/db", ERROR, list(LINES), members=True))
        self.assertEqual([(event.cause, event.old, event.new, event.ended)
                          for event in new.recent_events()[count:]],
                         [("pin-closed", MAINTENANCE, ERROR, ENDED_CLOCK)])
        self.assertEqual(self.ends, [], "it closed, and nothing ended")
        self.at(SECOND, tree=new)
        self.assertEqual(self.rows(new)[-1][0], "pin-opened")

    def test_on_a_branch_nothing_reports_to_its_close_is_written_at_its_end(self):
        self.tree.upsert("/hosts/a/cpu", OK, "fine")
        self.tree.set_maintenance("/hosts/a", "kernel", schedule=NIGHTLY,
                                  set_by="ada")
        self.at(FIRST)
        new = self.restarted(FIRST_CLOSE + timedelta(hours=1))
        closed = [event for event in new.recent_events()
                  if event.path == "/hosts/a"][-1]
        self.assertEqual((closed.cause, closed.old, closed.new, closed.timestamp),
                         ("pin-closed", MAINTENANCE, UNDEFINED, FIRST_CLOSE))

    def test_one_whose_schedule_ended_meanwhile_ended_at_its_end(self):
        self.nightly()
        self.at(LAST)
        new = self.restarted(LAST_CLOSE + timedelta(hours=1))
        self.assertEqual(self.ends, [("/db", "", ENDED_CLOCK, "")])
        count = len(new.recent_events())
        new.upsert("/db", ERROR, list(LINES), members=True)
        self.assertEqual([event.cause for event in new.recent_events()[count:]],
                         ["pin-ended"])
        self.assertEqual(new.pins(), ({}, {}))


class TheAdoptionTests(_WindowCase):
    """An adopted file's entries are split as a restart splits them: what holds
    nothing stands and opens at its next window, and what held here and holds nothing
    in the file closes."""

    def stood(self) -> Pin:
        return Pin(PIN_MAINTENANCE, "nightly backup", BEFORE - timedelta(hours=2),
                   set_by="ada", schedule=NIGHTLY)

    def test_one_between_two_windows_holds_nothing_and_opens_at_the_next(self):
        self.clock.at = BEFORE
        self.tree.adopt_maintenance({"/db": self.stood()},
                                    {("/db", "slow"): self.stood()})
        self.assertEqual((self.rows(), self.shows()), ([], ERROR))
        self.at(FIRST)
        self.assertEqual([row[0] for row in self.rows()],
                         ["line-pin-opened", "pin-opened"])

    def test_one_open_here_and_holding_nothing_in_the_file_closes(self):
        entry = self.nightly()
        self.at(FIRST)
        self.clock.at = FIRST_CLOSE + timedelta(minutes=5)
        self.tree.adopt_maintenance({"/db": entry})
        self.assertEqual(self.rows()[-1],
                         ("pin-closed", MAINTENANCE, ERROR, ENDED_CLOCK))
        self.assertEqual(self.tree.pins(), ({"/db": entry}, {}))

    def test_one_that_opened_meanwhile_is_its_window_s_opening(self):
        self.clock.at = FIRST + timedelta(minutes=5)
        self.tree.adopt_maintenance({"/db": self.stood()})
        self.assertEqual(self.rows(), [("pin-opened", ERROR, MAINTENANCE, "")])


class TheWindowsCountedTests(_WindowCase):
    """An entry's note counts the windows of it that held (ADR-0150), from what the
    tree tells, each once: the tick's; one open as the entry is set, which no tick
    opened; one a restart inside it replays; and none that opened and closed while the
    instance was down, which no row and no period says either — one open at the stop
    closing at its own end. With them how long those that closed held and how the last
    closed, kept through the notes' file; an adopted file tells nobody."""

    def setUp(self) -> None:
        self.book = NoteBook()
        super().setUp()

    def new_tree(self) -> StatusTree:
        tree = super().new_tree()
        tree.on_pin_end(self.book.pin_ended)
        tree.on_window(self.book.window_seen)
        return tree

    def nightly(self, *, line: str = "", not_on: str = "",
                schedule: Schedule = NIGHTLY) -> Pin:
        """The nightly backup set, and its note entered as the route enters it: after
        the set, which told its window first where one opened as it was set."""
        pin = super().nightly(line=line, not_on=not_on, schedule=schedule)
        self.book.pinned("/db", line, pin, Context())
        return pin

    def tally(self, line: str = "") -> Tally:
        (note,) = [each for each in self.book.of("/db") if each.slug == line]
        assert note.tally is not None
        return note.tally

    def restarted(self, at: datetime) -> StatusTree:
        """A new process on what this one kept, its notes through their file's own
        shape among it."""
        kept = {path: [Note.from_dict(path, json.loads(json.dumps(note.to_dict())))
                       for note in notes]
                for path, notes in self.book.tables().items()}
        self.book = NoteBook()
        self.book.restore(kept)
        return super().restarted(at)

    def test_each_window_the_tick_opens_counts_once_with_how_long_it_held(self):
        self.nightly()
        self.assertEqual(self.tally(), Tally(), "set before its first window")
        self.at(FIRST, FIRST + timedelta(minutes=30))
        self.assertEqual((self.tally().windows, self.tally().open_since,
                          self.tally().open_until), (1, FIRST, FIRST_CLOSE))
        self.at(FIRST_CLOSE, SECOND, SECOND_CLOSE, LAST, LAST_CLOSE)
        self.assertEqual(self.tally(), Tally(
            windows=3, held=3 * 7200.0, last_start=LAST, last_end=LAST_CLOSE,
            last_closed=ENDED_CLOCK))
        (note,) = self.book.of("/db")
        self.assertEqual((note.planned, note.ended, note.ended_at),
                         ("schedule", ENDED_CLOCK, LAST_CLOSE))

    def test_a_window_open_as_the_entry_is_set_counts_though_no_tick_opened_it(self):
        self.clock.at = FIRST + timedelta(minutes=30)
        self.nightly()
        self.nightly(line="slow")
        for line in ("", "slow"):
            self.assertEqual((self.tally(line).windows, self.tally(line).open_since),
                             (1, FIRST + timedelta(minutes=30)),
                             "it began to hold as it was set")
        self.at(FIRST_CLOSE, SECOND)
        self.assertEqual((self.tally().windows, self.tally().ran, self.tally().held),
                         (2, 1, 5400.0))

    def test_a_window_ended_now_closes_by_hand_and_says_whose_hand(self):
        pin = self.nightly()
        self.at(FIRST + timedelta(minutes=20))
        self.assertTrue(self.tree.change_window("/db", opened=FIRST, by="ben",
                                                expected_set_at=pin.token).applied)
        self.assertEqual(self.tally(), Tally(
            windows=1, held=1200.0, last_start=FIRST,
            last_end=FIRST + timedelta(minutes=20), last_closed=ENDED_HAND,
            last_closed_by="ben"))
        self.at(SECOND)
        self.assertEqual((self.tally().windows, self.tally().last_closed_by),
                         (2, "ben"))

    def test_a_line_s_windows_are_counted_in_its_note(self):
        self.nightly(line="slow")
        self.at(FIRST, FIRST_CLOSE)
        self.assertEqual((self.tally("slow").windows, self.tally("slow").ran,
                          self.tally("slow").open_since,
                          self.tally("slow").last_closed), (1, 1, None, ENDED_CLOCK))
        self.at(SECOND)
        self.assertEqual((self.tally("slow").windows, self.tally("slow").ran), (2, 1))

    def test_a_restart_inside_a_window_is_one_window(self):
        self.nightly()
        self.at(FIRST)
        tree = self.restarted(FIRST + timedelta(minutes=30))
        self.assertEqual((self.tally().windows, self.tally().open_since), (1, FIRST),
                         "replayed, and not counted again")
        self.at(FIRST_CLOSE, tree=tree)
        self.assertEqual((self.tally().windows, self.tally().ran, self.tally().held),
                         (1, 1, 7200.0))

    def test_a_window_wholly_inside_the_downtime_is_counted_nowhere(self):
        self.nightly()
        self.at(FIRST, FIRST_CLOSE)
        tree = self.restarted(SECOND_CLOSE + timedelta(hours=1))
        tree.upsert("/db", ERROR, list(LINES), members=True)  # its first reading
        self.assertEqual((self.tally().windows, self.tally().ran), (1, 1))
        self.assertEqual([event.cause for event in tree.recent_events()
                          if event.path == "/db" and event.timestamp >= SECOND], [],
                         "no row says it")
        self.assertEqual([period.since for period in tree.history("/db")
                          if period.code is MAINTENANCE], [FIRST], "nor History")
        self.at(LAST, tree=tree)
        self.assertEqual(self.tally().windows, 2)

    def test_a_window_open_at_the_stop_closes_at_its_own_end(self):
        self.nightly()
        self.nightly(line="slow")
        self.at(FIRST)
        self.restarted(FIRST_CLOSE + timedelta(hours=1))
        for line in ("", "slow"):
            self.assertEqual(self.tally(line), Tally(
                windows=1, held=7200.0, last_start=FIRST, last_end=FIRST_CLOSE,
                last_closed=ENDED_CLOCK))

    def test_an_adopted_file_tells_nobody(self):
        self.nightly()
        self.at(FIRST)
        counted = self.tally()
        self.tree.adopt_maintenance({}, {})
        self.assertEqual(self.tally(), counted,
                         "what its holder counted comes with its notes")


class HistoryTests(_WindowCase):
    """History replays a window's opening as a pin's set and its close as its end:
    what a node above a branch in a window showed, read again from the log, is what it
    showed — the window cancelling what fails beneath the branch."""

    def test_a_node_above_reads_again_what_it_showed(self):
        self.tree.upsert("/site/hosts/a", ERROR, "down")
        self.tree.upsert("/site/web", OK, "fine")
        self.tree.set_maintenance("/site/hosts", "nightly patching", schedule=NIGHTLY,
                                  set_by="ada")
        shown = [self.node("/site").code]
        for moment in (FIRST, FIRST_CLOSE, SECOND):
            self.at(moment)
            shown.append(self.node("/site").code)
        self.assertEqual(shown[0], ERROR)
        self.assertNotEqual(shown[1], ERROR, "the window cancelled what failed beneath")
        ended, current = self.tree.shown_history("/site")
        assert current is not None
        self.assertEqual([period.code for period in reversed(ended)] + [current.code],
                         shown)
