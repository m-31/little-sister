"""A series set and changed on the page (ADR-0150, landing 4; #35's note, decisions 2
to 6).

The editor sets a repeat: its first window on the first day on or after *Starts* that
its rule picks, each *Length* long, *Until* at most a year away, *Not on* a list that
can be read, its times in a zone of its own, and windows added by hand; beneath its
fields the next five windows and the sentence, a preview answered as a refusal is,
nothing written. A window open of a series is two rows: its own end with *Extend*,
which never shortens, and *End now*, which on the last window ends the entry; and the
schedule's sentence with *Edit*, which shapes the windows to come, and *Clear*, which
asks. A late *Extend* or *End now* is refused, offering *Set maintenance*, which joins
the schedule, as every window set where a schedule stands does. The instance says how
many entries a holiday list stops, and the Copy document says the schedule beside the
window.
"""
from __future__ import annotations

import os
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any, ClassVar
from unittest import TestCase, mock
from zoneinfo import ZoneInfo

os.environ.setdefault("SECRET_KEY", "test-key")

from little_sister import app as app_module
from little_sister import instants, local_login
from little_sister.copy_status import TimeStyle, format_node_markdown
from little_sister.holidays import HolidayList, Holidays
from little_sister.notes import Note, NoteBook, Tally
from little_sister.pins import Pin
from little_sister.schedule import Schedule
from little_sister.status import StatusCode
from little_sister.tree import (
    ENDED_CLOCK,
    ENDED_HAND,
    NOT_LATER,
    WINDOW_CLOSED,
    StatusTree,
)
from tests.page_tree import Element, parse
from tests.test_windows import (
    FIRST,
    FIRST_CLOSE,
    LAST,
    SECOND,
    SECOND_CLOSE,
    _Clock,
    _WindowCase,
)

OK, WARN, ERROR = StatusCode.OK, StatusCode.WARN, StatusCode.ERROR
MAINTENANCE = StatusCode.MAINTENANCE
BERLIN = ZoneInfo("Europe/Berlin")
STATIC = Path(app_module.__file__).parent / "static" / "js"


class TheWindowChangedAloneTests(_WindowCase):
    """*Extend* and *End now* change the window open now alone: an extension never
    shortens, is kept beside the schedule with who and why, and joins the next window
    where it reaches it; an end closes the window, the schedule standing, or on its
    last window ends the entry; a window that closed before the change arrived is not
    reopened, and the token guards each as every write."""

    def open_first(self, line: str = "") -> Pin:
        self.nightly(line=line)
        self.at(FIRST + timedelta(minutes=30))
        entry = (self.tree.entry_maintenance("/db", line) if line
                 else self.tree.maintenance_entry("/db"))
        assert entry is not None
        return entry

    def test_extend_moves_the_open_window_s_end_alone_and_says_who(self):
        entry = self.open_first()
        later = FIRST_CLOSE + timedelta(hours=1)
        write = self.tree.change_window("/db", opened=FIRST, until=later,
                                        note="the backup runs long", by="ben",
                                        expected_set_at=entry.token)
        self.assertTrue(write.applied)
        current = write.current
        assert current is not None
        self.assertEqual((current.schedule, current.note, current.created_by),
                         (entry.schedule, "nightly backup", "ada"))
        (change,) = current.changed
        self.assertEqual((change.start, change.end, change.note, change.by),
                         (FIRST, later, "the backup runs long", "ben"))
        opened = self.tree.open_series(current)
        assert opened is not None and opened.next is not None
        self.assertEqual((opened.window.start, opened.window.end), (FIRST, later))
        self.assertEqual((opened.extended_by, opened.next.start, opened.last),
                         ("ben", SECOND, False))
        self.assertEqual(self.rows()[-1], ("pin-edited", MAINTENANCE, MAINTENANCE, ""))
        self.at(FIRST_CLOSE + timedelta(minutes=30))
        self.assertEqual(self.shows(), MAINTENANCE, "open until its new end")
        self.at(later)
        self.assertEqual(self.shows(), ERROR)
        self.at(SECOND)
        self.assertEqual(self.shows(), MAINTENANCE, "the next opens as it would have")

    def test_extend_never_shortens(self):
        entry = self.open_first()
        count = len(self.tree.recent_events())
        for until in (FIRST_CLOSE - timedelta(minutes=10), FIRST_CLOSE):
            write = self.tree.change_window("/db", opened=FIRST, until=until, by="ben",
                                            expected_set_at=entry.token)
            self.assertEqual((write.applied, write.problem), (False, NOT_LATER))
        self.assertEqual(self.tree.maintenance_entry("/db"), entry)
        self.assertEqual(len(self.tree.recent_events()), count)

    def test_an_extension_that_reaches_the_next_window_joins_it(self):
        entry = self.open_first()
        write = self.tree.change_window("/db", opened=FIRST,
                                        until=SECOND + timedelta(minutes=30),
                                        by="ben", expected_set_at=entry.token)
        assert write.current is not None
        opened = self.tree.open_series(write.current)
        assert opened is not None and opened.next is not None
        self.assertEqual((opened.window.start, opened.window.end,
                          opened.window.starts), (FIRST, SECOND_CLOSE, (FIRST, SECOND)))
        self.assertEqual(opened.next.start, LAST)

    def test_end_now_closes_the_window_and_the_schedule_stands(self):
        entry = self.open_first()
        write = self.tree.change_window("/db", opened=FIRST, note="done early",
                                        by="ben", expected_set_at=entry.token)
        self.assertTrue(write.applied)
        self.assertEqual(self.rows()[-1],
                         ("pin-closed", MAINTENANCE, ERROR, ENDED_HAND))
        self.assertEqual((self.shows(), self.ends), (ERROR, []))
        assert write.current is not None
        self.assertEqual(self.tree.standing_entry("/db"), write.current)
        (change,) = write.current.changed
        self.assertEqual((change.start, change.end, change.note),
                         (FIRST, FIRST + timedelta(minutes=30), "done early"))
        self.at(SECOND)
        self.assertEqual(self.shows(), MAINTENANCE, "the next opens by the clock")

    def test_end_now_on_the_last_window_ends_the_entry(self):
        self.nightly()
        self.at(FIRST, FIRST_CLOSE, SECOND, SECOND_CLOSE, LAST + timedelta(minutes=30))
        entry = self.tree.maintenance_entry("/db")
        assert entry is not None
        opened = self.tree.open_series(entry)
        assert opened is not None
        self.assertEqual((opened.last, opened.next), (True, None))
        write = self.tree.change_window("/db", opened=LAST, by="ben",
                                        expected_set_at=entry.token)
        self.assertTrue(write.applied)
        self.assertEqual(self.rows()[-1], ("pin-ended", MAINTENANCE, ERROR, ENDED_HAND))
        self.assertEqual(self.ends, [("/db", "", ENDED_HAND, "ben")])
        self.assertIsNone(self.tree.standing_entry("/db"))

    def test_a_window_closed_before_the_change_arrived_is_not_reopened(self):
        entry = self.open_first()
        self.at(FIRST_CLOSE + timedelta(minutes=1))
        count = len(self.tree.recent_events())
        for until in (FIRST_CLOSE + timedelta(hours=1), None):
            write = self.tree.change_window("/db", opened=FIRST, until=until, by="ben",
                                            expected_set_at=entry.token)
            self.assertEqual((write.applied, write.problem), (False, WINDOW_CLOSED))
        self.at(SECOND + timedelta(minutes=1))
        write = self.tree.change_window("/db", opened=FIRST, by="ben",
                                        expected_set_at=entry.token)
        self.assertEqual(write.problem, WINDOW_CLOSED, "another window is open")
        self.assertEqual(len(self.tree.recent_events()), count + 1, "its opening alone")
        self.assertEqual(self.shows(), MAINTENANCE)

    def test_a_stale_token_is_refused_and_writes_nothing(self):
        self.open_first()
        write = self.tree.change_window("/db", opened=FIRST, by="ben",
                                        expected_set_at="2026-11-02T18:00:00Z")
        self.assertTrue(write.refused)
        self.assertEqual(self.shows(), MAINTENANCE)

    def test_a_line_s_window_is_changed_as_a_node_s(self):
        entry = self.open_first(line="slow")
        write = self.tree.change_window("/db", "slow", opened=FIRST, by="ben",
                                        expected_set_at=entry.token)
        self.assertTrue(write.applied)
        self.assertIsNone(self.tree.entry_maintenance("/db", "slow"))
        self.assertIsNotNone(self.tree.standing_line_entry("/db", "slow"))
        self.assertEqual(self.rows()[-1][0], "line-pin-closed")


#: A Wednesday, 11:00 in Berlin.
NOW = datetime(2026, 11, 4, 10, 0, tzinfo=UTC)
PATH = "/ci/jobs"
TAB = "/notes/ci/jobs"
#: Every day from 10:30 in Berlin for an hour, Wednesday 4 to Friday 6 November 2026:
#: from 09:30 to 10:30 UTC, the first window open at NOW.
DAILY = Schedule.parse(
    "DTSTART;TZID=Europe/Berlin:20261104T103000\nDURATION:PT1H\n"
    "RRULE:FREQ=DAILY;UNTIL=20261106T225959Z")
OPENED = datetime(2026, 11, 4, 9, 30, tzinfo=UTC)
CLOSES = datetime(2026, 11, 4, 10, 30, tzinfo=UTC)
WINDOW = "2026-11-04T09:30:00Z"
#: Every night from 22:00 for two hours, Thursday 5 to Tuesday 10 November 2026: a
#: schedule planned at NOW.
NIGHTS = Schedule.parse(
    "DTSTART;TZID=Europe/Berlin:20261105T220000\nDURATION:PT2H\n"
    "RRULE:FREQ=DAILY;UNTIL=20261110T225959Z")
BAVARIA = HolidayList("DE-BY", "holidays in Bavaria", frozenset({2026, 2027}),
                      {date(2026, 12, 25): "Christmas Day"}, Path("holidays.yaml"))
LISTS = Holidays(lists={"DE-BY": BAVARIA}, default="DE-BY",
                 files=(Path("holidays.yaml"),))
UNREADABLE = Holidays(
    unreadable={"DE-BY": "holidays.yaml: the holiday list DE-BY cannot be read — it "
                         "writes 2026-12-25 twice"},
    files=(Path("holidays.yaml"),))


def submitted(form: Element) -> dict[str, list[str]]:
    """What a browser sends of ``form`` with its default button: each field's value, a
    box or a choice where it is ticked, a select's chosen option or else its first —
    nothing that is disabled, and no button."""
    sent: dict[str, list[str]] = {}
    for field in form.walk():
        name = field.attrs.get("name")
        if not name or "disabled" in field.attrs:
            continue
        if field.tag == "input":
            kind = field.attrs.get("type", "text")
            if kind in ("submit", "button", "reset", "image"):
                continue
            if kind in ("checkbox", "radio"):
                if "checked" in field.attrs:
                    sent.setdefault(name, []).append(field.attrs.get("value", "on"))
                continue
            sent.setdefault(name, []).append(field.attrs.get("value", ""))
        elif field.tag == "textarea":
            sent.setdefault(name, []).append(field.source())
        elif field.tag == "select":
            options = field.all(tag="option")
            chosen = [each for each in options if "selected" in each.attrs]
            for each in chosen or options[:1]:
                sent.setdefault(name, []).append(each.attrs.get("value", each.text()))
    return sent


class _Page(TestCase):
    """A node failing by its own reading and its Notes tab, on a clock the test sets
    at NOW; the deployment's one holiday list, Bavaria's; signed in as the suite's
    admin, the tree telling the notes of every pin it ends, as the start wires it."""

    def setUp(self) -> None:
        app_module.app.config["TESTING"] = True
        self.clock = _Clock(NOW)
        self.tree = StatusTree()
        self.book = NoteBook()
        self.tree.on_pin_end(self.book.pin_ended)
        self.tree.use_holidays(LISTS)
        for patched in (mock.patch.object(instants, "now", self.clock),
                        mock.patch.object(app_module, "status_tree", self.tree),
                        mock.patch.object(app_module, "notes_book", self.book),
                        mock.patch.object(app_module, "holiday_lists", LISTS)):
            patched.start()
            self.addCleanup(patched.stop)
        self.tree.upsert(PATH, ERROR, "export failed")
        self.count = len(self.tree.recent_events())
        self.client = app_module.app.test_client()
        self.client.post("/login", data={"username": "pan", "password": "12345678"})

    def use(self, holidays: Holidays) -> None:
        """The deployment's holiday lists as the start read them: the page's and the
        tree's — the patch above puts the page's back."""
        app_module.holiday_lists = holidays
        self.tree.use_holidays(holidays)

    def at(self, moment: datetime) -> None:
        """The clock at ``moment``, and the tick there."""
        self.clock.at = moment
        self.tree.sweep_expired()

    def page(self, url: str = TAB) -> Element:
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200, url)
        return parse(response.get_data(as_text=True))

    def post(self, **fields: Any) -> Any:
        data = {"path": PATH, "action": "set", "set_at": "", **fields}
        return self.client.post("/pins/maintenance", data=data)

    def answer(self, response: Any) -> Element:
        """A page that answers in place — a refusal, a preview — and is no redirect."""
        self.assertEqual(response.status_code, 200, response.headers.get("Location"))
        return parse(response.get_data(as_text=True))

    def stored(self) -> Pin:
        entry = self.tree.standing_entry(PATH)
        assert entry is not None
        return entry

    def text(self) -> str:
        schedule = self.stored().schedule
        assert schedule is not None
        return schedule.text()

    def rows(self) -> list[tuple[str, StatusCode, StatusCode, str]]:
        return [(event.cause, event.old, event.new, event.ended)
                for event in self.tree.recent_events()[self.count:]
                if event.path == PATH]

    def notes(self) -> list[str]:
        return [each.text for each in self.book.entries(PATH)]

    def tab_form(self, page: Element | None = None) -> Element:
        (form,) = [each for each in (page or self.page()).all("ls-kind-form")
                   if each.attrs["data-kind"] == "maintenance"]
        return form

    def series_block(self, page: Element) -> Element:
        (block,) = [each for each in page.all("rule-block")
                    if each.attrs.get("data-rule") == "maintenance"]
        return block

    @staticmethod
    def rows_of(block: Element) -> list[Element]:
        return [each for each in block.children
                if isinstance(each, Element) and each.has("rule-block__head")]

    @classmethod
    def named(cls, block: Element) -> list[str]:
        """The accessible names of a block's own buttons, row by row: each disclosure's
        summary, and each button a row holds in a form of its own."""
        names = []
        for row in cls.rows_of(block):
            for child in row.children:
                if isinstance(child, Element) and child.tag == "details":
                    names.append(child.first().text())
                elif isinstance(child, Element) and child.tag == "form":
                    names.append(child.one(tag="button").text())
        return names

    @staticmethod
    def selected(form: Element, name: str) -> list[str]:
        (select,) = [each for each in form.all(tag="select")
                     if each.attrs.get("name") == name]
        return [each.attrs["value"] for each in select.all(tag="option")
                if "selected" in each.attrs]

    @staticmethod
    def ticked(form: Element) -> list[str]:
        return [each.attrs["value"] for each in form.all(tag="input")
                if each.attrs.get("name") == "weekday" and "checked" in each.attrs]

    def open_series(self) -> Pin:
        write = self.tree.set_maintenance(PATH, "nightly reindex", schedule=DAILY,
                                          set_by="lex")
        assert write.current is not None
        return write.current

    def planned(self) -> Pin:
        write = self.tree.set_maintenance(PATH, "nightly reindex", schedule=NIGHTS,
                                          set_by="lex")
        assert write.current is not None
        return write.current


class TheEditorTests(_Page):
    """The editor sets a repeat (#35's note, decision 4): its first window the first
    day on or after *Starts* that its rule picks, *Length* each window's, *Until*
    required and at most a year away, *Not on* a list that can be read, and its times
    in a zone of its own — and refuses what it cannot set, giving the editor back."""

    def test_a_weekly_repeat_starts_on_the_first_day_on_or_after_starts_it_picks(self):
        response = self.post(note="reindex", starts="2026-11-04 22:00", repeat="weekly",
                             interval="1", weekday="SA", duration="8h",
                             until="2027-03-31", zone="Europe/Berlin")
        self.assertEqual((response.status_code, response.headers["Location"]),
                         (302, f"{TAB}?at=maintenance#at"), "answered at its block")
        self.assertEqual(self.text(),
                         "DTSTART;TZID=Europe/Berlin:20261107T220000\nDURATION:PT8H\n"
                         "RRULE:FREQ=WEEKLY;BYDAY=SA;UNTIL=20270331T215959Z")
        self.assertEqual(self.stored().note, "reindex")
        self.assertEqual(self.rows(), [], "a window planned writes no row")
        (block,) = self.page().all("rule-block--planned")
        said = block.one("rule-block__what").text(shown=True)
        self.assertIn("Every Saturday from 22:00 for 8 hours, until 2027-03-28 "
                      "07:00:00", said)
        self.assertIn("· next 2026-11-07 22:00:00", said)

    def test_a_monthly_repeat_on_a_weekday_or_a_day_counted_from_the_month_s_end(self):
        self.post(starts="2026-11-05 03:00", repeat="monthly", month_by="weekday",
                  month_nth="1", month_weekday="SU", duration="2h", until="2027-06-30")
        self.assertEqual(self.text(),
                         "DTSTART;TZID=Europe/Berlin:20261206T030000\nDURATION:PT2H\n"
                         "RRULE:FREQ=MONTHLY;BYDAY=1SU;UNTIL=20270630T215959Z")
        self.tree.upsert("/ci/other", ERROR, "import failed")
        self.post(path="/ci/other", starts="2026-11-05 03:00", repeat="monthly",
                  month_by="day", month_day="1", month_from="end", duration="2h",
                  until="2027-06-30")
        other = self.tree.standing_entry("/ci/other")
        assert other is not None and other.schedule is not None
        self.assertEqual(other.schedule.text(),
                         "DTSTART;TZID=Europe/Berlin:20261130T030000\nDURATION:PT2H\n"
                         "RRULE:FREQ=MONTHLY;BYMONTHDAY=-1;UNTIL=20270630T215959Z")

    def test_until_is_required_and_at_most_a_year_away_and_the_field_says_so(self):
        said = self.page().with_id("form-maintenance-until-said").text()
        self.assertEqual(said, "Required: its last date, at most a year from now. A "
                               "date alone takes in that day.")
        refused = self.answer(self.post(note="nightly", repeat="daily", duration="1h",
                                        until=""))
        self.assertIn("Nothing was saved. A repeat needs Until, its last date — at "
                      "most a year from now.", refused.text())
        form = refused.one("ls-schedule-form")
        self.assertEqual(self.selected(form, "repeat"), ["daily"])
        self.assertEqual(submitted(form)["duration"], ["1h"])
        self.assertEqual(form.with_id("conflict-note").source(), "nightly")
        refused = self.answer(self.post(repeat="daily", duration="1h",
                                        until="2027-11-05"))
        self.assertIn("Until '2027-11-05' is more than a year from now: 2027-11-04 "
                      "23:59:59 at the latest.", refused.text())
        self.assertIsNone(self.tree.standing_entry(PATH))
        self.post(repeat="daily", duration="1h", until="2027-11-04")
        self.assertIn("UNTIL=20271104T225959Z", self.text(), "a date takes in its day")

    def test_length_is_how_long_each_window_lasts_and_its_label_says_so(self):
        label = self.page().with_id("form-maintenance-duration-label")
        self.assertEqual([(span.attrs["class"], span.text())
                          for span in label.all(tag="span")],
                         [("ls-when-once", "Duration or expiry"),
                          ("ls-when-repeat", "Length")])
        refused = self.answer(self.post(repeat="daily", duration="",
                                        until="2026-11-30"))
        self.assertIn("With a repeat, Length says how long each window is: 8h for "
                      "eight hours, 1d for whole days.", refused.text())
        refused = self.answer(self.post(repeat="daily", duration="Friday",
                                        until="2026-11-30"))
        self.assertIn("'Friday' is no length: with a repeat, Length says how long "
                      "each window is", refused.text())
        self.post(repeat="weekly", weekday="SA", starts="2026-11-07 09:00",
                  duration="1d", until="2026-11-30")
        self.assertIn("\nDURATION:P1D\n", self.text())

    def test_not_on_names_its_list_and_is_kept(self):
        form = self.tab_form()
        box = form.with_id("form-maintenance-not-on")
        self.assertEqual((box.attrs["type"], box.attrs["name"], box.attrs["value"]),
                         ("checkbox", "not_on", "DE-BY"))
        (label,) = [each for each in form.all(tag="label")
                    if each.attrs.get("for") == "form-maintenance-not-on"]
        self.assertEqual(label.text(), "Not on holidays in Bavaria")
        self.post(repeat="daily", starts="2026-11-05 22:00", duration="2h",
                  until="2026-12-31", not_on="DE-BY")
        self.assertEqual(self.stored().not_on, "DE-BY")
        (block,) = self.page().all("rule-block--planned")
        self.assertIn(", not on holidays in Bavaria",
                      block.one("rule-block__what").text(shown=True))

    def test_not_on_a_list_that_cannot_be_read_is_disabled_and_refused(self):
        self.use(UNREADABLE)
        form = self.tab_form()
        box = form.with_id("form-maintenance-not-on")
        self.assertIn("disabled", box.attrs)
        self.assertNotIn("name", box.attrs, "a box disabled sends nothing")
        (label,) = [each for each in form.all(tag="label")
                    if each.attrs.get("for") == "form-maintenance-not-on"]
        self.assertEqual(label.text(), "Not on DE-BY")
        self.assertEqual(form.with_id("form-maintenance-not-on-said").text(),
                         "It cannot be read: holidays.yaml: the holiday list DE-BY "
                         "cannot be read — it writes 2026-12-25 twice.")
        refused = self.answer(self.post(repeat="daily", starts="2026-11-05 22:00",
                                        duration="2h", until="2026-12-31",
                                        not_on="DE-BY"))
        self.assertIn("Not on: holidays.yaml: the holiday list DE-BY cannot be read — "
                      "it writes 2026-12-25 twice — a window that leaves out a list "
                      "that cannot be read would never be told apart from one that "
                      "applies. Set it without Not on.", refused.text())
        self.assertIsNone(self.tree.standing_entry(PATH))

    def test_times_in_a_zone_of_its_own_and_a_zone_that_is_none(self):
        refused = self.answer(self.post(repeat="daily", starts="2026-11-04 22:00",
                                        duration="2h", until="2026-11-30",
                                        zone="Mars/Olympus"))
        self.assertIn("Times in 'Mars/Olympus': that is no time zone. Choose one of "
                      "the IANA names, such as Europe/Berlin.", refused.text())
        self.post(repeat="daily", starts="2026-11-04 22:00", duration="2h",
                  until="2026-11-30", zone="America/New_York")
        self.assertTrue(self.text().startswith(
            "DTSTART;TZID=America/New_York:20261104T220000\n"), self.text())
        page = self.page()
        (block,) = page.all("rule-block--planned")
        self.assertIn("Every day from 22:00 (America/New_York) for 2 hours",
                      block.one("rule-block__what").text(shown=True))
        # the zones are offered once a page, to every editor on it
        (zones,) = [each for each in page.walk() if each.tag == "datalist"]
        self.assertEqual(zones.attrs["id"], "ls-zones")
        names = [each.attrs["value"] for each in zones.all(tag="option")]
        self.assertTrue({"America/New_York", "Europe/Berlin", "UTC"} <= set(names))
        fields = [each for each in page.all(tag="input")
                  if each.attrs.get("name") == "zone"]
        self.assertEqual(len(fields), 2, "the block's editor and the form")
        self.assertEqual({each.attrs.get("list") for each in fields}, {"ls-zones"})

    def test_a_repeat_whose_window_is_open_when_it_is_set_writes_the_set_alone(self):
        response = self.post(note="now and daily", repeat="daily", duration="1h",
                             until="2026-11-10")
        self.assertEqual(response.headers["Location"], "/status/ci/jobs")
        self.assertEqual(self.text(),
                         "DTSTART;TZID=Europe/Berlin:20261104T110000\nDURATION:PT1H\n"
                         "RRULE:FREQ=DAILY;UNTIL=20261110T225959Z")
        self.assertEqual(self.rows(), [("pin-set", ERROR, MAINTENANCE, "")])
        self.at(NOW + timedelta(minutes=1))
        self.assertEqual(self.rows(), [("pin-set", ERROR, MAINTENANCE, "")],
                         "the tick opens nothing")
        self.at(NOW + timedelta(hours=1))
        self.assertEqual(self.rows()[-1], ("pin-closed", MAINTENANCE, ERROR,
                                           ENDED_CLOCK))

    def test_decision_three_s_daily_rule_two_minutes_ahead_lasting_three(self):
        response = self.post(note="the recipe", starts="11:02", repeat="daily",
                             duration="3m", until="2026-11-05")
        self.assertEqual(response.headers["Location"], f"{TAB}?at=maintenance#at")
        self.assertEqual(self.text(),
                         "DTSTART;TZID=Europe/Berlin:20261104T110200\nDURATION:PT3M\n"
                         "RRULE:FREQ=DAILY;UNTIL=20261105T225959Z")
        self.at(NOW + timedelta(minutes=2))
        self.assertEqual(self.rows(), [("pin-opened", ERROR, MAINTENANCE, "")])
        self.at(NOW + timedelta(minutes=5))
        self.assertEqual(self.rows()[-1], ("pin-closed", MAINTENANCE, ERROR,
                                           ENDED_CLOCK))


class ThePreviewTests(_Page):
    """Beneath its fields the editor says the next five windows and the sentence (#35's
    note, decision 4): *Preview*, *Add an interval*, an ×, *weekend* and *working week*
    answer as a refusal does, the editor back with what it would set and nothing
    written, never at the form's ``next``; with script, the part beneath the fields
    alone, from a route that asks what a set asks."""

    TYPED: ClassVar[dict[str, str]] = {"repeat": "daily", "starts": "2026-11-04 22:00",
                                       "duration": "2h", "until": "2026-11-30"}

    def test_preview_answers_as_a_refusal_does_and_writes_nothing(self):
        page = self.answer(self.post(panel="1", next=f"{TAB}?panel=1", preview="1",
                                     note="nightly", **self.TYPED))
        body = page.one(tag="body")
        self.assertIn("data-ls-panel", body.attrs)
        self.assertIn("data-ls-mine", body.attrs, "the drawer asks before it drops it")
        self.assertIn("A preview: nothing is saved until you choose Set maintenance.",
                      page.text())
        self.assertNotIn("Nothing was saved", page.text())
        self.assertIsNone(self.tree.standing_entry(PATH))
        listed = [each.text() for each in page.one("ls-schedule-next").all(tag="li")]
        self.assertEqual(listed, [
            "2026-11-04 22:00:00 until 2026-11-05 00:00:00",
            "2026-11-05 22:00:00 until 2026-11-06 00:00:00",
            "2026-11-06 22:00:00 until 2026-11-07 00:00:00",
            "2026-11-07 22:00:00 until 2026-11-08 00:00:00",
            "2026-11-08 22:00:00 until 2026-11-09 00:00:00",
            "and more"])
        self.assertEqual(page.one("ls-schedule-sentence").text(),
                         "Every day from 22:00 for 2 hours, until 2026-12-01 00:00:00")
        form = page.one("ls-schedule-form")
        self.assertEqual(self.selected(form, "repeat"), ["daily"])
        self.assertEqual(form.with_id("conflict-note").source(), "nightly")
        self.assertEqual(submitted(form)["panel"], ["1"], "it stays in the drawer")

    def test_the_part_beneath_the_fields_alone_for_whoever_may_set(self):
        fields = {"path": PATH, "prefix": "form-maintenance", "repeat": "weekly",
                  "weekday": "SA", "starts": "2026-11-04 22:00", "duration": "8h",
                  "until": "2027-03-31"}
        response = self.client.post("/pins/maintenance/preview", data=fields)
        self.assertEqual(response.status_code, 200)
        body = response.get_data(as_text=True)
        self.assertNotIn("<html", body)
        part = parse(body)
        listed = part.one("ls-schedule-next")
        self.assertEqual(listed.attrs["aria-labelledby"], "form-maintenance-next")
        self.assertEqual(listed.all(tag="li")[0].text(),
                         "2026-11-07 22:00:00 until 2026-11-08 06:00:00")
        self.assertIn("Every Saturday from 22:00 for 8 hours",
                      part.one("ls-schedule-sentence").text())
        self.assertIsNone(self.tree.standing_entry(PATH))
        fields["until"] = ""
        part = parse(self.client.post("/pins/maintenance/preview", data=fields)
                     .get_data(as_text=True))
        self.assertEqual(part.one("ls-schedule-problem").text(),
                         "A repeat needs Until, its last date — at most a year from "
                         "now.")
        with mock.patch.dict(local_login.registered().users,
                             {"viewer": {"firstname": "V", "lastname": "R",
                                         "password": "pw", "admin": False}}):
            viewer = app_module.app.test_client()
            viewer.post("/login", data={"username": "viewer", "password": "pw"})
            self.assertEqual(viewer.post("/pins/maintenance/preview",
                                         data=fields).status_code, 403)

    def test_a_clock_change_night_says_how_long_its_window_really_lasts(self):
        page = self.answer(self.post(preview="1", repeat="weekly", weekday="SA",
                                     starts="2027-03-27 12:00", duration="1d",
                                     until="2027-04-30"))
        self.assertEqual(page.one("ls-schedule-next").all(tag="li")[0].text(),
                         "2027-03-27 12:00:00 until 2027-03-28 12:00:00 · 23 hours: "
                         "the clocks go forward")
        page = self.answer(self.post(preview="1", repeat="weekly", weekday="SA",
                                     starts="2027-10-30 12:00", duration="1d",
                                     until="2027-11-04"))
        self.assertEqual(page.one("ls-schedule-next").all(tag="li")[0].text(),
                         "2027-10-30 12:00:00 until 2027-10-31 12:00:00 · 25 hours: "
                         "the clocks go back")

    def test_an_interval_added_listed_with_its_x_and_taken_out_again(self):
        page = self.answer(self.post(add="1", add_begins="2026-11-07 09:00",
                                     add_ends="2h", **self.TYPED))
        (item,) = page.all("ls-handmade__item")
        self.assertEqual(item.text(), "A window from 2026-11-07 09:00:00 until "
                                      "2026-11-07 11:00:00 ×")
        (kept,) = [each for each in item.all(tag="input")
                   if each.attrs.get("name") == "added"]
        value = kept.attrs["value"]
        self.assertEqual(value, "2026-11-07T08:00:00Z/2026-11-07T10:00:00Z")
        drop = item.one("ls-handmade__drop")
        self.assertEqual((drop.attrs["name"], drop.attrs["value"]), ("drop", "added:0"))
        self.assertIn("data-ls-nowrite", drop.attrs)
        self.assertEqual(drop.attrs["aria-label"], "take out the window from "
                         "2026-11-07 09:00:00 until 2026-11-07 11:00:00")
        sent = submitted(page.one("ls-schedule-form"))
        self.assertEqual((sent["add_begins"], sent["add_ends"]), ([""], [""]),
                         "emptied for the next")
        self.assertEqual(page.one("ls-schedule-sentence").text(),
                         "Every day from 22:00 for 2 hours, until 2026-12-01 "
                         "00:00:00, 1 more window")
        self.assertIsNone(self.tree.standing_entry(PATH))
        page = self.answer(self.post(drop="added:0", added=value, **self.TYPED))
        self.assertEqual(page.all("ls-handmade__item"), [])
        self.post(added=value, **self.TYPED)
        self.assertIn("\nRDATE;VALUE=PERIOD:20261107T080000Z/20261107T100000Z",
                      self.text())

    def test_weekend_and_working_week_tick_their_days(self):
        typed = {"repeat": "weekly", "starts": "2026-11-07 09:00", "duration": "2h",
                 "until": "2026-11-30"}
        form = self.tab_form()
        self.assertEqual([(each.attrs["name"], each.attrs["value"],
                           "data-ls-nowrite" in each.attrs)
                          for each in form.all("ls-pick")],
                         [("pick", "weekend", True), ("pick", "week", True)])
        page = self.answer(self.post(pick="weekend", weekday="MO", **typed))
        self.assertEqual(self.ticked(page.one("ls-schedule-form")), ["SA", "SU"])
        page = self.answer(self.post(pick="week", **typed))
        self.assertEqual(self.ticked(page.one("ls-schedule-form")),
                         ["MO", "TU", "WE", "TH", "FR"])
        self.assertIsNone(self.tree.standing_entry(PATH))


class TheBlockTests(_Page):
    """A window open of a series is two rows (#35's note, decision 5): its own end,
    with *Extend* and *End now*, and the schedule, its sentence and its next start,
    with *Edit* and *Clear*, which asks — each named by how far it reaches."""

    def test_two_rows_each_named_by_how_far_it_reaches(self):
        self.open_series()
        block = self.series_block(self.page())
        first, second = self.rows_of(block)
        self.assertIn("is in maintenance by lex until 2026-11-04 11:30:00 · 30m left",
                      first.one("rule-block__what").text(shown=True))
        self.assertEqual(second.one("rule-block__schedule").text(shown=True),
                         "Every day from 10:30 for 1 hour, until 2026-11-06 11:30:00 · "
                         "next 2026-11-05 10:30:00")
        self.assertEqual(self.named(block),
                         ["Extend this node's window", "End now this node's window",
                          "Edit this node's schedule", "Clear this node's schedule"])
        extend = block.one("rule-block__extend").one(tag="form")
        self.assertEqual([(each.attrs["value"], each.text())
                          for each in extend.all("rule-block__preset")],
                         [("1800", "30 minutes"), ("3600", "1 hour"),
                          ("7200", "2 hours"), ("14400", "4 hours")])
        self.assertEqual(extend.one("rule-block__presets").first().text(),
                         "By, from its end at 2026-11-04 11:30:00:")
        self.assertTrue(extend.all(tag="button")[0].has("ls-default-submit"),
                        "Enter in Until presses no preset")
        sent = submitted(extend)
        self.assertEqual((sent["action"], sent["window"]), (["extend"], [WINDOW]))
        end = block.one("rule-block__end")
        self.assertIn("It ends this window now; the schedule's windows to come stay.",
                      end.text())
        self.assertEqual(submitted(end.one(tag="form"))["action"], ["end"])
        asked = block.one("rule-block__ask")
        self.assertIn("This ends every window of the schedule, this one and those to "
                      "come.", asked.text())
        self.assertEqual([button.text() for button in asked.all(tag="button")],
                         ["Clear the schedule", "Keep it"])

    def test_a_one_off_keeps_its_one_row_and_its_clear_asks_nothing(self):
        self.post(note="a long export", duration="2h")
        block = self.series_block(self.page())
        self.assertEqual(len(self.rows_of(block)), 1)
        self.assertEqual(self.named(block), ["Edit this node's maintenance",
                                             "Clear this node's maintenance"])
        self.assertEqual(block.all("rule-block__ask"), [])
        clear = block.one("rule-block__clear")
        self.assertEqual((clear.tag, submitted(clear)["action"]), ("form", ["clear"]))

    def test_extend_by_a_preset_counted_from_the_window_s_end(self):
        entry = self.open_series()
        response = self.post(action="extend", window=WINDOW, set_at=entry.token,
                             preset="1800", next=TAB)
        self.assertEqual((response.status_code, response.headers["Location"]),
                         (302, TAB))
        held = self.tree.maintenance_entry(PATH)
        assert held is not None
        opened = self.tree.open_series(held)
        assert opened is not None
        self.assertEqual((opened.window.end, opened.extended_by, held.schedule),
                         (CLOSES + timedelta(minutes=30), "pan", DAILY))
        self.assertEqual(self.notes(), ["nightly reindex"], "no words, no note")
        first = self.rows_of(self.series_block(self.page()))[0]
        self.assertIn("by lex until 2026-11-04 12:00:00, extended by pan · 1h left",
                      first.one("rule-block__what").text(shown=True))

    def test_the_words_why_are_a_note_of_their_own(self):
        entry = self.open_series()
        self.post(action="extend", window=WINDOW, set_at=entry.token, preset="3600",
                  note="the reindex runs long")
        self.assertIn("Window extended until 2026-11-04 12:30:00. the reindex runs "
                      "long", self.notes())
        self.assertEqual(self.stored().note, "nightly reindex", "the schedule's stays")

    def test_extend_never_shortens_and_names_end_now(self):
        entry = self.open_series()
        page = self.answer(self.post(action="extend", window=WINDOW,
                                     set_at=entry.token, until="11:15",
                                     note="sooner", next=TAB))
        self.assertIn("Nothing was saved. '11:15' is not after this window's end, "
                      "2026-11-04 11:30:00: Extend never shortens a window — to end "
                      "it sooner, use End now.", page.text())
        (form,) = [each for each in page.all(tag="form")
                   if submitted(each).get("action") == ["extend"]]
        sent = submitted(form)
        self.assertEqual((sent["until"], sent["window"], sent["set_at"], sent["note"]),
                         (["11:15"], [WINDOW], [entry.token], ["sooner"]))
        self.assertEqual(self.tree.maintenance_entry(PATH), entry)

    def test_end_now_closes_the_window_and_the_schedule_stands(self):
        entry = self.open_series()
        response = self.post(action="end", window=WINDOW, set_at=entry.token,
                             note="done early", next=TAB)
        self.assertEqual(response.status_code, 302)
        self.assertIsNone(self.tree.maintenance_entry(PATH))
        self.assertEqual(self.rows()[-1],
                         ("pin-closed", MAINTENANCE, ERROR, ENDED_HAND))
        self.assertIn("Window ended early. done early", self.notes())
        (block,) = self.page().all("rule-block--planned")
        self.assertIn("· next 2026-11-05 10:30:00",
                      block.one("rule-block__what").text(shown=True))

    def test_on_the_last_window_the_row_says_so_and_end_now_ends_the_entry(self):
        self.open_series()
        self.at(datetime(2026, 11, 6, 9, 45, tzinfo=UTC))
        entry = self.tree.maintenance_entry(PATH)
        assert entry is not None
        block = self.series_block(self.page())
        self.assertIn("· its last window",
                      block.one("rule-block__schedule").text(shown=True))
        self.assertIn("It is its schedule's last window: ending it ends the schedule.",
                      block.one("rule-block__end").text())
        response = self.post(action="end", window="2026-11-06T09:30:00Z",
                             set_at=entry.token)
        self.assertEqual(response.status_code, 302)
        self.assertIsNone(self.tree.standing_entry(PATH))
        self.assertEqual(self.rows()[-1], ("pin-ended", MAINTENANCE, ERROR, ENDED_HAND))

    def test_clear_asks_and_ends_every_window(self):
        self.open_series()
        asked = self.series_block(self.page()).one("rule-block__ask").one(tag="form")
        self.assertEqual(self.client.post("/pins/maintenance",
                                          data=submitted(asked)).status_code, 302)
        self.assertIsNone(self.tree.standing_entry(PATH))
        self.assertEqual(self.rows()[-1], ("pin-ended", MAINTENANCE, ERROR, ENDED_HAND))

    def test_a_late_extend_is_refused_offering_set_maintenance_which_joins(self):
        entry = self.open_series()
        self.at(CLOSES + timedelta(minutes=1))
        page = self.answer(self.post(action="extend", window=WINDOW,
                                     set_at=entry.token, preset="1800",
                                     note="still at it", next=TAB))
        self.assertIn("Nothing was saved. This window closed 2026-11-04 11:30:00, "
                      "before what you sent arrived, and a window that closed is not "
                      "opened again by itself.", page.text())
        self.assertIn("Set maintenance, joining its schedule", page.text())
        form = page.one("ls-schedule-form")
        sent = submitted(form)
        self.assertEqual((sent["with"], sent["set_at"], sent["duration"], sent["note"]),
                         (["join"], [entry.token], ["2026-11-04 12:00:00"],
                          ["still at it"]))
        self.assertIsNone(self.tree.maintenance_entry(PATH), "nothing reopened")
        self.assertEqual(self.client.post("/pins/maintenance",
                                          data=sent).status_code, 302)
        joined = self.stored()
        assert joined.schedule is not None
        self.assertEqual(joined.schedule.text(),
                         DAILY.text() + "\nRDATE;VALUE=PERIOD:20261104T103100Z/"
                                        "20261104T110000Z")
        self.assertEqual(joined.note, "nightly reindex")
        self.assertIsNotNone(self.tree.maintenance_entry(PATH), "a window from now")
        self.assertIn("A window joins the schedule, from 2026-11-04 11:31:00 until "
                      "2026-11-04 12:00:00. still at it", self.notes())

    def test_a_late_end_now_is_refused_and_where_its_entry_is_gone_too(self):
        entry = self.open_series()
        self.at(CLOSES + timedelta(minutes=1))
        page = self.answer(self.post(action="end", window=WINDOW,
                                     set_at=entry.token))
        self.assertIn("This window closed 2026-11-04 11:30:00, before what you sent "
                      "arrived", page.text())
        self.at(datetime(2026, 11, 6, 10, 31, tzinfo=UTC))
        self.assertIsNone(self.tree.standing_entry(PATH))
        page = self.answer(self.post(action="end", window="2026-11-06T09:30:00Z",
                                     set_at=entry.token, note="all done"))
        self.assertIn("This window has closed, before what you sent arrived",
                      page.text())
        sent = submitted(page.one("ls-schedule-form"))
        self.assertNotIn("with", sent, "nothing to join")
        self.assertEqual((sent["set_at"], sent["note"]), ([""], ["all done"]))


class TheEditTests(_Page):
    """*Edit* shapes the windows to come (#35's note, decision 5): its *Starts* is the
    window open now's, the window kept as an interval to its current end, a start of
    the rule within it left out, the changes on what passed gone; *Until* capped a
    year from the kept window's start, which the field says."""

    def test_the_open_window_is_kept_and_the_windows_to_come_change(self):
        entry = self.open_series()
        self.post(action="extend", window=WINDOW, set_at=entry.token, preset="1800")
        block = self.series_block(self.page())
        form = block.one("rule-block__edit").one(tag="form")
        sent = submitted(form)
        self.assertEqual((sent["starts"], sent["starts_was"], sent["duration"],
                          sent["repeat"], sent["until"]),
                         (["2026-11-04 10:30:00"], ["2026-11-04 10:30:00"], ["1h"],
                          ["daily"], ["2026-11-06"]))
        self.assertEqual(form.with_id("tab-maintenance-until-said").text(),
                         "Required: its last date, at most a year from the start of "
                         "the window open now, 2026-11-04 10:30:00, which keeps its "
                         "end. A date alone takes in that day.")
        self.assertEqual(form.one("ls-schedule-next").all(tag="li")[0].text(),
                         "open now · 2026-11-04 10:30:00 until 2026-11-04 12:00:00")
        sent["duration"] = ["2h"]
        self.assertEqual(self.client.post("/pins/maintenance",
                                          data=sent).status_code, 302)
        edited = self.stored()
        assert edited.schedule is not None
        self.assertEqual(edited.schedule.text(),
                         "DTSTART;TZID=Europe/Berlin:20261104T103000\nDURATION:PT2H\n"
                         "RRULE:FREQ=DAILY;UNTIL=20261106T225959Z\n"
                         "RDATE;VALUE=PERIOD:20261104T093000Z/20261104T110000Z\n"
                         "EXDATE;TZID=Europe/Berlin:20261104T103000")
        self.assertEqual(edited.changed, (), "what changed of the open window is in it")
        self.assertEqual((edited.created_by, edited.note), ("lex", "nightly reindex"))
        opened = self.tree.open_series(edited)
        assert opened is not None and opened.next is not None
        self.assertEqual((opened.window.start, opened.window.end),
                         (OPENED, CLOSES + timedelta(minutes=30)), "it keeps its end")
        self.assertEqual((opened.next.start, opened.next.end),
                         (datetime(2026, 11, 5, 9, 30, tzinfo=UTC),
                          datetime(2026, 11, 5, 11, 30, tzinfo=UTC)))
        second = self.rows_of(self.series_block(self.page()))[1]
        self.assertEqual(second.one("rule-block__schedule").text(shown=True),
                         "Every day from 10:30 for 2 hours, until 2026-11-06 12:30:00 "
                         "· next 2026-11-05 10:30:00")

    def test_a_rule_start_at_the_kept_window_s_end_makes_one_longer_window(self):
        # meant, on Lex's word: back-to-back windows are one maintenance
        self.open_series()
        form = self.series_block(self.page()).one("rule-block__edit").one(tag="form")
        sent = submitted(form)
        sent["starts"] = ["2026-11-04 11:30"]
        self.assertEqual(self.client.post("/pins/maintenance",
                                          data=sent).status_code, 302)
        self.assertEqual(self.text(),
                         "DTSTART;TZID=Europe/Berlin:20261104T113000\nDURATION:PT1H\n"
                         "RRULE:FREQ=DAILY;UNTIL=20261106T225959Z\n"
                         "RDATE;VALUE=PERIOD:20261104T093000Z/20261104T103000Z",
                         "a start at the kept window's end is not left out")
        first = self.rows_of(self.series_block(self.page()))[0]
        self.assertIn("until 2026-11-04 12:30:00 · 1h 30m left",
                      first.one("rule-block__what").text(shown=True),
                      "the first row says the joined end")

    def test_until_is_capped_a_year_from_the_kept_window_s_start(self):
        across = Schedule.parse(
            "DTSTART;TZID=Europe/Berlin:20261103T220000\nDURATION:PT4H\n"
            "RRULE:FREQ=DAILY;UNTIL=20261106T225959Z")
        self.clock.at = datetime(2026, 11, 4, 0, 0, tzinfo=UTC)
        self.tree.set_maintenance(PATH, "overnight", schedule=across, set_by="lex")
        form = self.series_block(self.page()).one("rule-block__edit").one(tag="form")
        sent = submitted(form)
        sent["until"] = ["2027-11-04"]
        refused = self.answer(self.client.post("/pins/maintenance", data=sent))
        self.assertIn("Until '2027-11-04' is more than a year from this window's "
                      "start, 2026-11-03 22:00:00: 2027-11-03 23:59:59 at the latest.",
                      refused.text())
        sent["until"] = ["2027-11-03"]
        self.assertEqual(self.client.post("/pins/maintenance",
                                          data=sent).status_code, 302)
        self.assertIn("UNTIL=20271103T225959Z", self.text())

    def test_an_open_window_added_by_hand_leaves_the_rule_its_time_of_day(self):
        self.planned()
        sent = submitted(self.tab_form())
        sent.update(note=["a hotfix"], duration=["2h"])
        self.client.post("/pins/maintenance", data=sent)
        form = self.series_block(self.page()).one("rule-block__edit").one(tag="form")
        sent = submitted(form)
        self.assertEqual(sent["starts"], ["2026-11-05 22:00:00"],
                         "the rule's next start, not the window added by hand")
        self.assertEqual(self.client.post("/pins/maintenance",
                                          data=sent).status_code, 302)
        self.assertEqual(self.text(),
                         NIGHTS.text() + "\nRDATE;VALUE=PERIOD:20261104T100000Z/"
                                         "20261104T120000Z")

    def test_a_one_off_a_window_joined_is_edited_as_once_its_windows_kept(self):
        self.clock.at = NOW + timedelta(seconds=7)
        self.post(note="a long export", duration="13:00")
        sent = submitted(self.tab_form())
        sent.update(starts=["2026-11-05 09:00"], duration=["2h"])
        self.client.post("/pins/maintenance", data=sent)
        before = self.text()
        form = self.series_block(self.page()).one("rule-block__edit").one(tag="form")
        sent = submitted(form)
        self.assertEqual((sent["repeat"], sent["starts"], sent["duration"]),
                         (["once"], ["2026-11-04 11:00:07"], ["2026-11-04 13:00:00"]))
        self.assertEqual(sent["added"], ["2026-11-05T08:00:00Z/2026-11-05T10:00:00Z"])
        self.assertEqual(self.client.post("/pins/maintenance",
                                          data=sent).status_code, 302)
        self.assertEqual(self.text(), before, "saved as filled, it says what it said")


class TheFieldsSayItOnceTests(_Page):
    """What the editor's fields say (ADR-0150 decisions 11 and 13): with a repeat the
    end field asks a length alone and *Times in* alone names the zone; an open
    one-off's *Starts* stands for a repeat, blank; and *Until* comes back as it was
    typed, one end said one way in its field."""

    @staticmethod
    def field(form: Element, name: str) -> Element:
        (found,) = [each for each in form.walk()
                    if each.tag in ("input", "textarea")
                    and each.attrs.get("name") == name]
        return found

    @staticmethod
    def holder(form: Element, name: str) -> Element:
        """The row that holds ``form``'s field ``name``."""
        found = [each for each in form.walk() if each.tag == "div"
                 and any(child.tag == "input" and child.attrs.get("name") == name
                         for child in each.children if isinstance(child, Element))]
        return found[-1]

    def test_with_a_repeat_the_end_field_asks_a_length_and_the_zone_is_said_once(self):
        default = app_module.config.maintenance_default_expiry
        once = f"e.g. 2h or Friday — default {default}"
        length = "a length, e.g. 8h or 1d"
        end = self.field(self.tab_form(), "duration")
        self.assertEqual((end.attrs["placeholder"], end.attrs["data-once-said"],
                          end.attrs["data-length-said"]), (once, once, length))
        self.planned()
        form = self.series_block(self.page()).one("rule-block__edit").one(tag="form")
        self.assertEqual(self.field(form, "duration").attrs["placeholder"], length)
        # the zone a time typed is read in is the once's line alone: with a repeat a
        # length is in no zone, and *Times in* names the one the repeat reads
        for each in (self.tab_form(), form):
            zone = [line for line in each.all("form-text")
                    if line.text().startswith("Timezone:")]
            self.assertEqual([line.has("ls-when-once") for line in zone], [True])
        self.assertIn('"data-once-said"', (STATIC / "maintenance-edit.js").read_text())

    def test_an_open_one_off_s_starts_stands_for_a_repeat_and_says_so(self):
        self.post(note="a quick swap", duration="2h")
        form = self.series_block(self.page()).one("rule-block__edit").one(tag="form")
        self.assertEqual(self.field(form, "open_once").attrs["value"], "1")
        starts = self.holder(form, "starts")
        self.assertTrue(starts.has("ls-starts-open-once"))
        self.assertEqual(self.field(form, "starts").attrs.get("value", ""), "")
        self.assertIn("This window is open, and its start has passed: leave it blank. "
                      "With a repeat, it is when the windows to come start",
                      starts.text())
        # with script the stylesheet shows it once a repeat is chosen; a window set
        # ahead, a series and the form for a new one keep theirs in sight
        css = (STATIC.parent / "css" / "overview.css").read_text()
        rule = css.split(".ls-starts-open-once {", 1)[0].rsplit("}", 1)[1]
        self.assertIn(".maintenance-edit-enhanced form:has(select[name=\"repeat\"] "
                      "option[value=\"once\"]:checked)", rule)
        self.assertFalse(self.holder(self.tab_form(), "starts").has(
            "ls-starts-open-once"))

    def test_until_comes_back_as_it_was_typed(self):
        # *Until 2027-01-31*, the sentence *until 2027-02-01 00:00:00* — its last
        # window's end — and *Edit* said *2027-01-31 23:59:59*
        self.post(note="reindex", starts="2026-11-07 22:00", repeat="weekly",
                  weekday="SA", duration="8h", until="2027-01-31")
        self.assertIn("UNTIL=20270131T225959Z", self.text())
        form = self.series_block(self.page()).one("rule-block__edit").one(tag="form")
        sent = submitted(form)
        self.assertEqual((sent["until"], sent["until_was"]),
                         (["2027-01-31"], ["2027-01-31"]))
        self.assertEqual(self.client.post("/pins/maintenance",
                                          data=sent).status_code, 302)
        self.assertIn("UNTIL=20270131T225959Z", self.text(), "kept as it stood")
        # one typed with a time of day comes back with it
        sent = submitted(form)
        sent["until"] = ["2027-01-31 18:00"]
        sent["set_at"] = [self.stored().token]
        self.assertEqual(self.client.post("/pins/maintenance",
                                          data=sent).status_code, 302)
        form = self.series_block(self.page()).one("rule-block__edit").one(tag="form")
        self.assertEqual(submitted(form)["until"], ["2027-01-31 18:00:00"])


class TheWindowThatJoinsTests(_Page):
    """A window set on a part a schedule stands on joins it (#35's note, decision 2):
    added to its schedule, the entry keeping its note, the window's words a note
    beside it; a one-off it joins written with a length exact to the second; a repeat
    replaces it only where the person chose to."""

    def test_a_window_set_where_a_schedule_stands_joins_it_beside_its_note(self):
        entry = self.planned()
        sent = submitted(self.tab_form())
        self.assertEqual((sent["slug"], sent["set_at:"], sent["with"]),
                         ([""], [entry.token], ["join"]))
        sent.update(note=["a hotfix"], duration=["2h"])
        self.assertEqual(self.client.post("/pins/maintenance",
                                          data=sent).status_code, 302)
        joined = self.stored()
        assert joined.schedule is not None
        self.assertEqual(joined.schedule.text(),
                         NIGHTS.text() + "\nRDATE;VALUE=PERIOD:20261104T100000Z/"
                                         "20261104T120000Z")
        self.assertEqual((joined.note, joined.created_by), ("nightly reindex", "lex"))
        self.assertIsNotNone(self.tree.maintenance_entry(PATH), "the window from now")
        self.assertIn("A window joins the schedule, from 2026-11-04 11:00:00 until "
                      "2026-11-04 13:00:00. a hotfix", self.notes())

    def test_a_window_that_joins_a_one_off_keeps_its_end_to_the_second(self):
        self.clock.at = NOW + timedelta(seconds=7)
        self.post(note="a long export", duration="13:00")
        once = self.stored()
        assert once.schedule is not None and once.schedule.is_one_off
        sent = submitted(self.tab_form())
        sent.update(starts=["2026-11-05 09:00"], duration=["2h"])
        self.assertEqual(self.client.post("/pins/maintenance",
                                          data=sent).status_code, 302)
        self.assertEqual(self.text(),
                         "DTSTART;TZID=Europe/Berlin:20261104T110007\n"
                         "DURATION:PT1H59M53S\n"
                         "RDATE;VALUE=PERIOD:20261105T080000Z/20261105T100000Z")
        block = self.series_block(self.page())
        first, second = self.rows_of(block)
        self.assertIn("until 2026-11-04 13:00:00",
                      first.one("rule-block__what").text(shown=True),
                      "its end where it was typed")
        self.assertEqual(second.one("rule-block__schedule").text(shown=True),
                         "1 more window, until 2026-11-05 11:00:00 · next 2026-11-05 "
                         "09:00:00")

    def test_a_repeat_where_a_schedule_stands_replaces_it_only_where_chosen(self):
        entry = self.planned()
        sent = submitted(self.tab_form())
        sent.update(repeat=["weekly"], weekday=["SA"], starts=["2026-11-07 09:00"],
                    duration=["4h"], until=["2026-12-31"], note=["weekends instead"])
        page = self.answer(self.client.post("/pins/maintenance", data=sent))
        self.assertIn("A schedule stands on this part, and a window set here joins "
                      "it; a repeat, or windows added by hand, would replace it: "
                      "choose 'this replaces it', or change the schedule with its "
                      "Edit.", page.text())
        self.assertEqual(self.stored(), entry)
        form = self.tab_form(page)
        self.assertEqual(self.selected(form, "repeat"), ["weekly"])
        sent["with"] = ["replace"]
        self.assertEqual(self.client.post("/pins/maintenance",
                                          data=sent).status_code, 302)
        replaced = self.stored()
        self.assertEqual((replaced.note, replaced.created_by, replaced.created_at),
                         ("weekends instead", "lex", entry.created_at))
        self.assertTrue(self.text().startswith(
            "DTSTART;TZID=Europe/Berlin:20261107T090000\nDURATION:PT4H\n"
            "RRULE:FREQ=WEEKLY;BYDAY=SA;"), self.text())

    def test_a_window_joined_is_kept_to_the_second_its_text_says(self):
        self.planned()
        self.clock.at = NOW + timedelta(microseconds=600000)
        sent = submitted(self.tab_form())
        sent.update(duration=["2h"])
        self.client.post("/pins/maintenance", data=sent)
        schedule = self.stored().schedule
        assert schedule is not None
        self.assertEqual(Schedule.parse(schedule.text()), schedule)


class TheInstanceSaysWhatTheListsStopTests(_Page):
    """The instance's line (#35's note, decision 6, 3b's fifth question): one for each
    list an entry names that cannot be read, from the start; and one for each list not
    complete for a year a standing entry's windows start in — from 1 December for the
    coming year, and from 1 January on until the list states the year and the instance
    restarts — each saying how many entries it stops."""

    WEEKLY = Schedule.parse(
        "DTSTART;TZID=Europe/Berlin:20261205T220000\nDURATION:PT8H\n"
        "RRULE:FREQ=WEEKLY;BYDAY=SA;UNTIL=20270227T225959Z")
    SHORT = Holidays(lists={"DE-BY": HolidayList(
        "DE-BY", "holidays in Bavaria", frozenset({2026}), {}, Path("holidays.yaml"))},
        files=(Path("holidays.yaml"),))

    def lines(self) -> list[tuple[str, str, StatusCode]]:
        return [(line.slug, line.text, line.code)
                for line in app_module._list_stop_lines()]

    def test_from_the_first_of_december_a_list_not_complete_for_the_coming_year(self):
        self.use(self.SHORT)
        self.tree.set_maintenance(PATH, "weekends", schedule=self.WEEKLY,
                                  not_on="DE-BY", set_by="lex")
        self.clock.at = datetime(2026, 11, 30, 22, 59, tzinfo=UTC)
        self.assertEqual(self.lines(), [], "30 November in Berlin")
        said = ("holidays in Bavaria (DE-BY) is not complete for 2027: from 2027-01-01 "
                "00:00:00 the windows of 1 maintenance entry do not apply. State 2027 "
                "in holidays.yaml, its days with it, and restart the instance.")
        self.clock.at = datetime(2026, 11, 30, 23, 0, tzinfo=UTC)
        self.assertEqual(self.lines(), [("not-on-DE-BY-2027", said, WARN)])
        self.tree.set_entry_maintenance(PATH, "export", "weekends too",
                                        schedule=self.WEEKLY, not_on="DE-BY",
                                        set_by="lex")
        self.clock.at = datetime(2027, 1, 2, 10, 0, tzinfo=UTC)
        ((_, text, _),) = self.lines()
        self.assertIn("the windows of 2 maintenance entries do not apply", text,
                      "from 1 January on")
        self.use(LISTS)
        self.assertEqual(self.lines(), [], "the list states the year: restarted")

    def test_a_list_that_cannot_be_read_stops_every_window_from_the_start(self):
        self.use(UNREADABLE)
        self.tree.set_maintenance(PATH, "nightly", schedule=NIGHTS, not_on="DE-BY",
                                  set_by="lex")
        self.assertEqual(self.lines(), [(
            "not-on-DE-BY",
            "1 maintenance entry that leaves out the holiday list DE-BY applies not at "
            "all: holidays.yaml: the holiday list DE-BY cannot be read — it writes "
            "2026-12-25 twice", WARN)])
        self.tree.set_entry_maintenance(PATH, "export", "nightly too", schedule=NIGHTS,
                                        not_on="DE-BY", set_by="lex")
        ((_, text, _),) = self.lines()
        self.assertTrue(text.startswith("2 maintenance entries that leave out the "
                                        "holiday list DE-BY apply not at all: "), text)
        # each entry's words lead there
        blocks = self.page().all("rule-block--planned")
        self.assertEqual(len(blocks), 2)
        for block in blocks:
            (link,) = block.one("rule-block__why").all(tag="a")
            self.assertEqual(link.attrs["href"],
                             "/status/little-sister/holidays?reason=not-on-DE-BY"
                             "#pinned-reason")


class TheWindowsRanTests(_Page):
    """What ran of an entry (ADR-0150), which its note counts from what the tree tells,
    as the start wires it: each window once — one that opens as the entry is set, with
    *Starts* blank, though no tick opened it, and the open window of one set from now
    that is given a repeat, which it keeps — and what the tab and the Copy document say:
    what it was planned as, *set* in place of *from*, what of its windows ran in place
    of how long it stood, its end *with its last window*, and, while it stands, how the
    last of its windows closed; one window set from now saying what it said."""

    def setUp(self) -> None:
        super().setUp()
        self.tree.on_window(self.book.window_seen)

    def note(self) -> Note:
        """The note of the entry set last on the node."""
        notes = [each for each in self.book.of(PATH) if each.kind == "maintenance"]
        return notes[0]

    def tally(self) -> Tally:
        tally = self.note().tally
        assert tally is not None
        return tally

    def entry(self, page: Element) -> Element:
        """The newest entry of what came before."""
        return page.all("ls-entry")[0]

    def through(self, *moments: datetime) -> None:
        """The clock at each of ``moments`` in turn, and the tick there."""
        for moment in moments:
            self.at(moment)

    def test_a_window_open_as_it_is_set_counts_though_no_tick_opened_it(self):
        self.post(note="now and daily", repeat="daily", duration="1h",
                  until="2026-11-10")
        self.assertEqual((self.tally().windows, self.tally().open_since), (1, NOW),
                         "Starts blank: its first window opened as it was set")
        self.at(NOW + timedelta(minutes=1))
        self.assertEqual(self.tally().windows, 1, "the tick opens nothing")
        self.at(NOW + timedelta(hours=1))
        self.assertEqual((self.tally().ran, self.tally().held), (1, 3600.0))
        self.at(NOW + timedelta(days=1))
        self.assertEqual(self.tally().windows, 2)

    def test_one_window_set_from_now_given_a_repeat_keeps_its_first(self):
        self.post(note="a quick swap", duration="2h")
        self.assertEqual((self.tally().windows, self.note().planned), (1, ""))
        self.clock.at = NOW + timedelta(minutes=30)
        sent = submitted(self.series_block(self.page()).one("rule-block__edit")
                         .one(tag="form"))
        sent.update(repeat=["daily"], duration=["2h"], until=["2026-11-10"])
        self.assertEqual(self.client.post("/pins/maintenance", data=sent).status_code,
                         302)
        self.assertEqual((self.tally().windows, self.tally().open_since,
                          self.tally().open_until, self.note().planned),
                         (1, NOW, NOW + timedelta(hours=2), "schedule"))
        self.at(NOW + timedelta(hours=2))
        self.assertEqual((self.tally().ran, self.tally().held), (1, 7200.0))
        self.at(NOW + timedelta(days=1, minutes=45))
        self.assertEqual(self.tally().windows, 2)

    def test_a_schedule_cleared_before_any_window_says_none_opened(self):
        self.post(note="nightly reindex", starts="2026-11-05 22:00", repeat="daily",
                  duration="2h", until="2026-11-10")
        self.clock.at = NOW + timedelta(hours=3)
        self.post(action="clear", set_at=self.stored().token)
        page = self.page()
        entry = self.entry(page)
        self.assertEqual(entry.one("ls-entry__when").text(),
                         "2026-11-04 11:00:00 → 2026-11-04 14:00:00 · no window opened")
        self.assertEqual(entry.one("ls-note__said").text(),
                         "Planned as a schedule by pan · ended: by hand, by pan.")
        self.assertEqual(page.one("ls-before__last").text(),
                         "Last time: maintenance on the node, planned as a schedule by "
                         "pan 2026-11-04 11:00:00: no window opened — ended: by hand, "
                         "by pan.")

    def test_a_schedule_s_windows_ran_and_its_last_ended_it(self):
        self.post(note="now and daily", repeat="daily", duration="1h",
                  until="2026-11-05")
        self.through(NOW + timedelta(hours=1), NOW + timedelta(days=1),
                     NOW + timedelta(days=1, hours=1))
        self.assertIsNone(self.tree.standing_entry(PATH), "its last window ended it")
        entry = self.entry(self.page())
        self.assertEqual(entry.one("ls-entry__when").text(),
                         "2026-11-04 11:00:00 → 2026-11-05 12:00:00 · 2 windows ran, "
                         "2h in all")
        self.assertEqual(entry.one("ls-note__said").text(),
                         "Planned as a schedule by pan · ended: with its last window.")
        copied = self.client.get(f"/copy{PATH}").get_data(as_text=True)
        self.assertIn("🛠️ Maintenance, planned as a schedule — by pan, set "
                      "2026-11-04 11:00:00", copied)
        self.assertIn(": 2 windows ran, 2h in all, until 2026-11-05 12:00:00", copied)
        self.assertIn(", ended: with its last window", copied)

    def test_while_it_stands_its_row_says_how_the_last_window_closed(self):
        self.post(note="now and daily", repeat="daily", duration="1h",
                  until="2026-11-10")
        copied = self.client.get(f"/copy{PATH}").get_data(as_text=True)
        self.assertIn("🛠️ Maintenance, planned as a schedule — by pan, set "
                      "2026-11-04 11:00:00", copied)
        self.assertIn(": 1 window has opened, and it stands", copied)
        self.clock.at = NOW + timedelta(minutes=20)
        self.post(action="end", window="2026-11-04T10:00:00Z",
                  set_at=self.stored().token)
        planned = self.page().one("rule-block--planned")
        self.assertTrue(planned.one("rule-block__what").text().endswith(
            "· 1 window ran, the last closed by hand, by pan"))
        self.at(NOW + timedelta(days=1))
        row = self.rows_of(self.series_block(self.page()))[1]
        self.assertTrue(row.one("rule-block__schedule").text().endswith(
            "· 1 window ran, the last closed by hand, by pan"),
            "the window open now is not among what ran")
        self.at(NOW + timedelta(days=1, hours=1))
        planned = self.page().one("rule-block--planned")
        self.assertTrue(planned.one("rule-block__what").text().endswith(
            "· 2 windows ran, the last closed at its end"))

    def test_a_window_set_ahead_says_it_ran_or_that_it_never_opened(self):
        self.post(note="patch day", starts="2026-11-05 10:00", duration="2h")
        self.through(datetime(2026, 11, 5, 9, 0, tzinfo=UTC),
                     datetime(2026, 11, 5, 11, 0, tzinfo=UTC))
        entry = self.entry(self.page())
        self.assertTrue(entry.one("ls-entry__when").text().endswith("· it ran 2h"))
        self.assertEqual(entry.one("ls-note__said").text(),
                         "Planned as a window by pan · ended: with its window.")
        self.post(note="patch day again", starts="2026-11-06 10:00", duration="2h")
        self.post(action="clear", set_at=self.stored().token)
        entry = self.entry(self.page())
        self.assertTrue(entry.one("ls-entry__when").text().endswith(
            "· it never opened"))
        self.assertEqual(entry.one("ls-note__said").text(),
                         "Planned as a window by pan · ended: by hand, by pan.")

    def test_one_window_set_from_now_says_what_it_said(self):
        self.post(note="a quick swap", duration="2h")
        self.clock.at = NOW + timedelta(minutes=65)
        self.post(action="clear", set_at=self.stored().token)
        entry = self.entry(self.page())
        self.assertEqual(entry.one("ls-entry__when").text(),
                         "2026-11-04 11:00:00 → 2026-11-04 12:05:00 · 1h 5m")
        self.assertEqual(entry.one("ls-note__said").text(),
                         "By pan · ended: by hand, by pan.")
        copied = self.client.get(f"/copy{PATH}").get_data(as_text=True)
        self.assertIn("🛠️ Maintenance — by pan, from 2026-11-04 11:00:00", copied)
        self.assertIn("(1h 5m), ended: by hand, by pan", copied)


class TheCopyAndTheScriptsTests(_Page):
    """The Copy document says a series' schedule beside its window, as its block's two
    rows do; and every form of a series' block is an editor the refresh waits for,
    the editor's own buttons ones the drawer takes for no write."""

    def test_the_copy_says_the_schedule_beside_the_window(self):
        self.open_series()
        node = self.tree.snapshot(PATH)
        assert node is not None
        for style in (TimeStyle(BERLIN, opened=self.tree.open_series),
                      app_module._copy_style()):
            self.assertIn(
                "🛠️ Maintenance — by lex, until 2026-11-04 11:30:00 +01:00; its "
                "schedule: every day from 10:30 for 1 hour, until 2026-11-06 "
                "11:30:00 +01:00 · next 2026-11-05 10:30:00 +01:00",
                format_node_markdown(node, style))

    def test_every_form_of_a_series_block_is_an_editor_the_refresh_waits_for(self):
        self.open_series()
        block = self.series_block(self.page())
        forms = block.all(tag="form")
        self.assertEqual(len(forms), 4, "Extend, End now, Edit and Clear")
        for form in forms:
            assert form.parent is not None
            self.assertTrue(form.has("maintenance-editor-form"))
            self.assertEqual(form.parent.tag, "details")
            self.assertTrue(form.parent.has("maintenance-editor-disclosure"))
        own = [each.attrs["name"] for each in block.all(tag="button")
               if "data-ls-nowrite" in each.attrs]
        self.assertEqual(sorted(set(own)), ["add", "pick", "preview"])
        # and so are its month's days and pages, which *Edit* asks for as it opens
        # (decision 17)
        edit = block.one("ls-schedule-form")
        month = parse(self.client.post("/pins/maintenance/preview", data={
            **submitted(edit), "prefix": "edit"}).get_data(as_text=True))
        asked = [each.attrs["name"] for each in month.all(tag="button")
                 if "data-ls-nowrite" in each.attrs]
        self.assertEqual(sorted(set(asked)), ["day", "page"])
        drawer = (STATIC / "drawer.js").read_text(encoding="utf-8")
        self.assertIn('e.submitter.hasAttribute("data-ls-nowrite")', drawer)
        self.assertIn('doc.querySelector("form[data-ls-dirty]")', drawer)
