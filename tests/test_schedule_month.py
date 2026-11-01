"""The editor's month (ADR-0150, landing 5; #35's note, decision 4).

Beneath an editor's fields comes its month: six weeks from the Monday on or before its
first day, each day of it a button whose name says its date, its hours, what the text
and the holiday list say of it and what a click does; paged by month and by year, from
this month to a year on; a night the clocks change marked, a day the holiday list names
by its name, a date left out with its time struck. A click on a day adds or leaves out
its window, each listed beneath with ×, and nothing is written — without script every
day and every page a button that sends the editor back with it done, as with script,
where the part beneath the fields comes alone, the month apart from what is read out.
And a window added beside an open one-off, by hand or by a click, is written beside it
rather than dropped. A standing entry's editor comes without its month, which *Preview*
draws and the editor asks for as it opens, so that *Handled* draws none.

What the browser does with the month — one tab stop, the arrow keys, the bar on a
phone, a standing entry's asked for as its *Edit* opens — is
``tests/test_schedule_month_browser.py``'s.
"""
from __future__ import annotations

import re
from datetime import date, timedelta
from pathlib import Path
from typing import Any, ClassVar

from little_sister.holidays import HolidayList, Holidays
from little_sister.schedule import Schedule
from little_sister.status import StatusCode
from tests.page_tree import Element, parse
from tests.test_schedule_editor import (
    CLOSES,
    NIGHTS,
    OPENED,
    PATH,
    _Page,
    submitted,
)

ERROR, MAINTENANCE = StatusCode.ERROR, StatusCode.MAINTENANCE
WEEK = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]


class _Month(_Page):
    """The editor's month as a page draws it."""

    #: Every day from 22:00 for two hours, from Wednesday 4 November 2026 to the year's
    #: end.
    TYPED: ClassVar[dict[str, str]] = {"repeat": "daily", "starts": "2026-11-04 22:00",
                                       "duration": "2h", "until": "2026-12-31"}
    #: Every Saturday from 22:00 for eight hours, through November.
    WEEKLY: ClassVar[dict[str, str]] = {"repeat": "weekly", "weekday": "SA",
                                        "starts": "2026-11-07 22:00", "duration": "8h",
                                        "until": "2026-11-30"}

    @staticmethod
    def month(page: Element) -> Element:
        return page.one("ls-cal")

    def day(self, page: Element, value: str) -> Element:
        (button,) = [each for each in self.month(page).all(tag="button")
                     if each.attrs.get("name") == "day"
                     and each.attrs.get("value") == value]
        return button

    def label(self, page: Element, value: str) -> str:
        return self.day(page, value).attrs["aria-label"]

    @staticmethod
    def hours(day: Element) -> list[tuple[str, ...]]:
        """A day's hours as it draws them: each window's from and to, and the time
        of one it leaves out, struck."""
        return [tuple(part for part in each.children if isinstance(part, str))
                for each in day.all("ls-cal__hours")]

    @staticmethod
    def items(page: Element) -> list[str]:
        return [each.text() for each in page.all("ls-handmade__item")]

    @staticmethod
    def pages(page: Element) -> list[tuple[str, str, bool, str]]:
        return [(each.attrs["data-page"], each.attrs["value"], "disabled" in each.attrs,
                 each.attrs["aria-label"]) for each in page.all("ls-cal__page")]

    def again(self, drawn: Element, **fields: Any) -> Element:
        """The editor ``drawn`` gave back, sent again as a browser sends it with one of
        its own buttons, ``fields``."""
        sent: dict[str, Any] = dict(submitted(drawn.one("ls-schedule-form")))
        sent.update(fields)
        return self.answer(self.client.post("/pins/maintenance", data=sent))

    def saved(self, page: Element) -> Any:
        """The editor ``page`` gave back, set as it stands."""
        return self.client.post("/pins/maintenance",
                                data=submitted(page.one("ls-schedule-form")))


class TheMonthTests(_Month):
    """The month: six weeks, Monday first, each day's hours and what a click does;
    paged by month and by year as far as a year on; a clock-change night, a holiday's
    name, a year the list is not complete for; a zone of its own in its title."""

    def test_six_weeks_from_the_monday_before_its_first_each_day_its_hours(self):
        page = self.answer(self.post(preview="1", **self.TYPED))
        month = self.month(page)
        self.assertEqual(month.one("ls-cal__title").text(), "November 2026")
        self.assertEqual(month.one("ls-cal__title").attrs["id"], "conflict-month")
        grid = month.one("ls-cal__grid")
        self.assertEqual(grid.attrs["aria-labelledby"], "conflict-month")
        self.assertNotIn("role", grid.attrs, "a grid only where script moves across it")
        self.assertEqual([each.attrs["abbr"] for each in grid.all(tag="th")], WEEK)
        rows = grid.one(tag="tbody").all(tag="tr")
        self.assertEqual(len(rows), 6)
        cells = [cell for row in rows for cell in row.all(tag="td")]
        self.assertEqual(len(cells), 42)
        # a day of the month before or after stands for where it is, and is not read
        before = cells[0].first()
        self.assertEqual((before.tag, before.text(), before.attrs["aria-hidden"]),
                         ("span", "26", "true"))
        self.assertTrue(before.has("is-other-month"))
        days = [each.attrs["value"] for each in month.all(tag="button")
                if each.attrs.get("name") == "day"]
        self.assertEqual(days, [f"2026-11-{day:02d}" for day in range(1, 31)])
        fifth = self.day(page, "2026-11-05")
        self.assertEqual(fifth.attrs["aria-label"],
                         "Thursday, 5 November: a window from 22:00 to 00:00 the next "
                         "day. A click leaves its window out.")
        self.assertEqual(fifth.attrs["title"], fifth.attrs["aria-label"])
        self.assertEqual(self.hours(fifth), [("22:00", "00:00")])
        self.assertIn("data-ls-nowrite", fifth.attrs)
        self.assertEqual(fifth.attrs["type"], "submit")
        today = self.day(page, "2026-11-04")
        self.assertEqual(today.attrs["aria-label"],
                         "Wednesday, 4 November, today: a window from 22:00 to 00:00 "
                         "the next day. A click leaves its window out.")
        self.assertEqual(today.attrs["aria-current"], "date")
        self.assertIn("data-focus", today.attrs, "the tab stop where script runs")
        past = self.day(page, "2026-11-03")
        self.assertEqual(past.attrs["aria-label"], "Tuesday, 3 November: no window.")
        self.assertEqual(past.attrs["aria-disabled"], "true")
        self.assertTrue(past.has("is-past"))
        sent = submitted(page.one("ls-schedule-form"))
        self.assertEqual(sent["month"], [""], "it follows the first window till paged")
        # the month first, then what is read out as the fields change
        region = page.one("ls-schedule-preview")
        self.assertNotIn("aria-live", region.attrs)
        shown, said = [each for each in region.children if isinstance(each, Element)]
        self.assertTrue(shown.has("ls-schedule-month"))
        self.assertTrue(said.has("ls-schedule-said"))
        self.assertEqual(said.attrs["aria-live"], "polite")
        self.assertTrue(said.one("ls-schedule-next").within(said))
        self.assertIsNone(self.tree.standing_entry(PATH))

    def test_paged_by_month_and_by_year_from_this_month_to_a_year_on(self):
        page = self.answer(self.post(preview="1", **self.TYPED))
        self.assertEqual(self.pages(page), [
            ("year-before", "", True, "the year before"),
            ("month-before", "", True, "the month before"),
            ("month-after", "2026-12", False, "the month after, December 2026"),
            ("year-after", "2027-11", False, "the year after, November 2027")])
        self.assertTrue(all("data-ls-nowrite" in each.attrs
                            for each in page.all("ls-cal__page")))
        page = self.again(page, page="2026-12")
        self.assertEqual(self.month(page).one("ls-cal__title").text(), "December 2026")
        self.assertEqual(submitted(page.one("ls-schedule-form"))["month"], ["2026-12"],
                         "kept once paged")
        self.assertEqual(self.pages(page), [
            ("year-before", "2026-11", False, "the year before, November 2026"),
            ("month-before", "2026-11", False, "the month before, November 2026"),
            ("month-after", "2027-01", False, "the month after, January 2027"),
            ("year-after", "2027-11", False, "the year after, November 2027")])
        # the month kept is the month every button gives back
        page = self.again(page, preview="1")
        self.assertEqual(self.month(page).one("ls-cal__title").text(), "December 2026")
        page = self.again(page, page="2027-11")
        self.assertEqual([(each[0], each[2]) for each in self.pages(page)], [
            ("year-before", False), ("month-before", False), ("month-after", True),
            ("year-after", True)])
        page = self.again(page, page="2031-01")
        self.assertEqual(self.month(page).one("ls-cal__title").text(), "November 2027",
                         "a year on, as far as anything set here reaches")
        self.assertIsNone(self.tree.standing_entry(PATH))

    def test_until_somebody_moves_it_the_month_is_its_first_window_s(self):
        page = self.answer(self.post(preview="1", **{
            **self.TYPED, "starts": "2027-02-10 22:00", "until": "2027-03-31"}))
        month = self.month(page)
        self.assertEqual(month.one("ls-cal__title").text(), "February 2027")
        self.assertIn("data-focus", self.day(page, "2027-02-10").attrs)
        # once paged, a once's rest stays open without script, its month kept
        page = self.answer(self.post(page="2026-12", duration="2h"))
        self.assertIn("open", page.one("ls-schedule-rest").attrs)
        self.assertEqual(self.month(page).one("ls-cal__title").text(), "December 2026")
        self.assertIn("data-focus", self.day(page, "2026-12-01").attrs)

    def test_a_day_s_bar_is_the_hours_its_windows_cover(self):
        page = self.answer(self.post(preview="1", **self.WEEKLY))

        def bars(value: str) -> list[str]:
            return [each.attrs["style"]
                    for each in self.day(page, value).all(tag="span")
                    if each.parent is not None and each.parent.has("ls-cal__bar")]

        saturday = self.day(page, "2026-11-07")
        self.assertEqual(self.hours(saturday), [("22:00", "06:00")])
        self.assertEqual(bars("2026-11-07"), ["left: 91.67%; width: 8.33%"])
        # the night's window: the end of its Saturday, and the start of its Sunday
        sunday = self.day(page, "2026-11-08")
        self.assertEqual(bars("2026-11-08"), ["left: 0.00%; width: 25.00%"])
        self.assertEqual(self.hours(sunday), [], "its hours are its Saturday's")
        self.assertFalse(sunday.has("is-window"))
        self.assertEqual(bars("2026-11-09"), [])

    def test_a_night_the_clocks_change_is_marked(self):
        page = self.answer(self.post(preview="1", repeat="weekly", weekday="SA",
                                     starts="2027-03-27 12:00", duration="1d",
                                     until="2027-04-30"))
        self.assertEqual(self.month(page).one("ls-cal__title").text(), "March 2027")
        self.assertEqual(self.label(page, "2027-03-27"),
                         "Saturday, 27 March: a window from 12:00 to 12:00 the next "
                         "day, 23 hours: the clocks go forward. A click leaves its "
                         "window out.")
        sunday = self.day(page, "2027-03-28")
        self.assertEqual(sunday.attrs["aria-label"],
                         "Sunday, 28 March: no window; the clocks go forward an hour "
                         "at 02:00. A click adds a window.")
        self.assertEqual(sunday.one("ls-cal__note").text(), "+1h")
        self.assertTrue(sunday.has("is-clock"))
        page = self.answer(self.post(preview="1", repeat="weekly", weekday="SA",
                                     starts="2027-10-30 12:00", duration="1d",
                                     until="2027-11-04"))
        sunday = self.day(page, "2027-10-31")
        self.assertEqual(sunday.attrs["aria-label"],
                         "Sunday, 31 October: no window; the clocks go back an hour at "
                         "03:00. A click adds a window.")
        self.assertEqual(sunday.one("ls-cal__note").text(), "−1h")

    def test_a_day_the_list_names_says_its_name_its_window_struck(self):
        typed = {**self.TYPED, "not_on": "DE-BY"}
        page = self.answer(self.post(page="2026-12", **typed))
        christmas = self.day(page, "2026-12-25")
        self.assertEqual(christmas.attrs["aria-label"],
                         "Friday, 25 December: Christmas Day on holidays in Bavaria; "
                         "its window from 22:00 left out. A click adds its window "
                         "back.")
        self.assertTrue(christmas.has("is-listed"))
        self.assertEqual(christmas.one("ls-cal__struck").text(), "22:00")
        self.assertEqual(self.label(page, "2026-12-26"),
                         "Saturday, 26 December: a window from 22:00 to 00:00 the next "
                         "day. A click leaves its window out.")

    def test_a_year_the_list_is_not_complete_for_leaves_its_windows_out(self):
        bavaria = HolidayList("DE-BY", "holidays in Bavaria", frozenset({2026}),
                              {date(2026, 12, 25): "Christmas Day"},
                              Path("holidays.yaml"))
        self.use(Holidays(lists={"DE-BY": bavaria}, default="DE-BY",
                          files=(Path("holidays.yaml"),)))
        page = self.answer(self.post(page="2027-01", **{
            **self.TYPED, "until": "2027-01-31", "not_on": "DE-BY"}))
        monday = self.day(page, "2027-01-04")
        self.assertEqual(monday.attrs["aria-label"],
                         "Monday, 4 January: holidays in Bavaria is not complete for "
                         "2027; its window from 22:00 left out. A click adds its "
                         "window back.")
        self.assertTrue(monday.has("is-uncovered"))

    def test_a_zone_of_its_own_is_named_in_the_title_and_read_in_it(self):
        page = self.answer(self.post(preview="1", **{
            **self.TYPED, "zone": "America/New_York", "starts": "2026-11-04 20:00"}))
        self.assertEqual(self.month(page).one("ls-cal__title").text(),
                         "November 2026 (America/New_York)")
        self.assertEqual(self.label(page, "2026-11-05"),
                         "Thursday, 5 November: a window from 20:00 to 22:00. A click "
                         "leaves its window out.")


class TheClickTests(_Month):
    """A click on a day adds or leaves out its window, listed beneath with ×, nothing
    written: the rule's window left out and put back, a day without a window given one
    of the rule's time and length, one added by hand taken out, a holiday's added back;
    a day whose window has begun is not for a click."""

    def test_what_is_listed_beneath_keeps_each_date_whole(self):
        # on a phone a window left out stood on two lines, *2026-* and *11-15*: each
        # date and time beneath the fields is kept whole, as a block keeps an
        # instant's, and the ×'s name, read and never seen, stays the words
        page = self.answer(self.post(panel="1", day="2026-11-10", **self.TYPED))
        said = page.one("ls-schedule-said")
        windows = [window for window in said.one("ls-schedule-next").all(tag="li")
                   if not window.has("ls-schedule-next__more")]
        for part in (said.one("ls-handmade__item"), *windows,
                     said.one("ls-schedule-sentence")):
            text = part.text()
            words = re.findall(r"\d{4}-\d{2}-\d{2}|\d{2}:\d{2}:\d{2}", text)
            self.assertTrue(words, text)
            whole = [run.text() for run in part.all("text-nowrap")]
            for word in words:
                self.assertIn(word, whole, text)
        self.assertEqual(said.one("ls-handmade__drop").attrs["aria-label"],
                         "put back the window from 2026-11-10 22:00:00")

    def test_a_click_leaves_a_window_out_and_another_puts_it_back(self):
        page = self.answer(self.post(panel="1", day="2026-11-10", **self.TYPED))
        self.assertIn("data-ls-mine", page.one(tag="body").attrs,
                      "the drawer asks before it drops it")
        self.assertIn("A preview: nothing is saved until you choose Set maintenance.",
                      page.text())
        self.assertEqual(self.items(page),
                         ["Left out: the window from 2026-11-10 22:00:00 ×"])
        tenth = self.day(page, "2026-11-10")
        self.assertEqual(tenth.attrs["aria-label"],
                         "Tuesday, 10 November: its window from 22:00 left out. A "
                         "click puts its window back.")
        self.assertEqual(self.hours(tenth), [("22:00",)])
        self.assertEqual(tenth.one("ls-cal__struck").text(), "22:00")
        self.assertTrue(tenth.has("is-left-out"))
        self.assertIn(", 1 left out", page.one("ls-schedule-sentence").text())
        self.assertEqual(submitted(page.one("ls-schedule-form"))["month"], ["2026-11"])
        self.assertIsNone(self.tree.standing_entry(PATH))
        again = self.again(page, day="2026-11-10")
        self.assertEqual(self.items(again), [])
        self.assertEqual(self.label(again, "2026-11-10"),
                         "Tuesday, 10 November: a window from 22:00 to 00:00 the next "
                         "day. A click leaves its window out.")
        self.assertEqual(self.saved(page).status_code, 302)
        self.assertIn("\nEXDATE;TZID=Europe/Berlin:20261110T220000", self.text())

    def test_a_click_gives_a_day_without_one_a_window_of_the_rule_s_time(self):
        page = self.answer(self.post(day="2026-11-10", **self.WEEKLY))
        self.assertEqual(self.items(page), ["A window from 2026-11-10 22:00:00 ×"])
        self.assertEqual(self.label(page, "2026-11-10"),
                         "Tuesday, 10 November: a window from 22:00 to 06:00 the next "
                         "day. A click takes the window added out.")
        self.assertIn("2026-11-10 22:00:00 until 2026-11-11 06:00:00",
                      [each.text() for each in page.one("ls-schedule-next").all(
                          tag="li")])
        self.assertEqual(self.items(self.again(page, day="2026-11-10")), [])
        self.assertEqual(self.saved(page).status_code, 302)
        self.assertIn("\nRDATE;TZID=Europe/Berlin:20261110T220000", self.text())

    def test_a_click_takes_out_a_window_added_by_hand(self):
        page = self.answer(self.post(add="1", add_begins="2026-11-10 09:00",
                                     add_ends="2h", **self.WEEKLY))
        self.assertEqual(self.label(page, "2026-11-10"),
                         "Tuesday, 10 November: a window from 09:00 to 11:00. A click "
                         "takes the window added out.")
        self.assertEqual(self.items(self.again(page, day="2026-11-10")), [])

    def test_a_click_adds_back_the_window_a_holiday_leaves_out(self):
        typed = {**self.TYPED, "not_on": "DE-BY"}
        page = self.answer(self.post(day="2026-12-25", **typed))
        self.assertEqual(self.items(page), ["A window from 2026-12-25 22:00:00 ×"])
        self.assertEqual(self.month(page).one("ls-cal__title").text(), "December 2026",
                         "the month of the day clicked")
        self.assertEqual(self.label(page, "2026-12-25"),
                         "Friday, 25 December: a window from 22:00 to 00:00 the next "
                         "day; Christmas Day on holidays in Bavaria; its window from "
                         "22:00 added back. A click takes the window added out.")
        self.assertEqual(self.saved(page).status_code, 302)
        self.assertTrue(self.text().endswith(
            "\nRDATE;TZID=Europe/Berlin:20261225T220000"))
        self.assertEqual(self.stored().not_on, "DE-BY")

    def test_a_day_whose_window_has_begun_is_not_for_a_click(self):
        self.open_series()
        shown = self.again(self.series_block(self.page()), preview="1")
        today = self.day(shown, "2026-11-04")
        self.assertEqual(today.attrs["aria-label"],
                         "Wednesday, 4 November, today: a window from 10:30 to 11:30.")
        self.assertEqual(today.attrs["aria-disabled"], "true")
        self.assertEqual(self.label(shown, "2026-11-05"),
                         "Thursday, 5 November: a window from 10:30 to 11:30. A click "
                         "leaves its window out.")
        self.assertEqual(self.label(shown, "2026-11-07"),
                         "Saturday, 7 November: no window. A click adds a window.")
        sent: dict[str, Any] = dict(submitted(shown.one("ls-schedule-form")))
        page = self.answer(self.client.post("/pins/maintenance",
                                            data={**sent, "day": "2026-11-04"}))
        self.assertEqual(self.items(page), [], "nothing done, nothing listed")
        today = self.day(page, "2026-11-04")
        self.assertEqual(today.attrs["aria-label"],
                         "Wednesday, 4 November, today: a window from 10:30 to 11:30.",
                         "the window kept open is not said left out")
        page = self.answer(self.client.post("/pins/maintenance",
                                            data={**sent, "day": "2026-11-03"}))
        self.assertEqual(self.items(page), [])
        self.assertEqual(self.rows(), [("pin-set", ERROR, MAINTENANCE, "")])

    def test_the_part_beneath_the_fields_alone_holds_the_month_apart(self):
        fields = {"path": PATH, "prefix": "form-maintenance", "day": "2026-11-10",
                  **self.TYPED}
        response = self.client.post("/pins/maintenance/preview", data=fields)
        self.assertEqual(response.status_code, 200)
        part = parse(response.get_data(as_text=True))
        month, said = part.one("ls-schedule-month"), part.one("ls-schedule-said")
        self.assertNotIn("aria-live", month.attrs)
        self.assertEqual(said.attrs["aria-live"], "polite")
        self.assertEqual(month.one("ls-cal__title").attrs["id"],
                         "form-maintenance-month")
        self.assertEqual([each.text() for each in said.all("ls-handmade__item")],
                         ["Left out: the window from 2026-11-10 22:00:00 ×"])
        self.assertEqual(self.label(part, "2026-11-10"),
                         "Tuesday, 10 November: its window from 22:00 left out. A "
                         "click puts its window back.")
        self.assertIsNone(self.tree.standing_entry(PATH))
        region = self.tab_form().one("ls-schedule-preview")
        self.assertNotIn("aria-live", region.attrs)
        self.assertEqual(region.one("ls-schedule-said").attrs["aria-live"], "polite")


class TheStandingEntrysMonthTests(_Month):
    """A standing entry's editor comes without its month (ADR-0150 decision 17): its
    part drawn empty and marked for the script to ask for as the editor opens, what the
    fields set said beside it as before; *Preview* draws the month without script, and
    the part the script asks for draws the same, so that *Handled*, which draws an
    editor for every schedule, draws no month however many stand. The form for a new
    window keeps its month as it was."""

    def asked(self, edit: Element) -> Element:
        """The part beneath ``edit``'s fields as its script asks for it when the editor
        opens: every field as it stands, and the prefix of its ids."""
        prefix = edit.one("ls-schedule-preview").attrs["data-prefix"]
        response = self.client.post("/pins/maintenance/preview",
                                    data={**submitted(edit), "prefix": prefix})
        self.assertEqual(response.status_code, 200)
        return parse(response.get_data(as_text=True))

    def test_its_editor_comes_without_its_month_marked_to_ask_for_it(self):
        self.planned()
        page = self.page()
        edit = self.series_block(page).one("ls-schedule-form")
        self.assertEqual(edit.all("ls-cal"), [])
        part = edit.one("ls-schedule-month")
        self.assertIn("data-ls-ask", part.attrs)
        self.assertEqual((list(part.walk()), part.text().strip()), ([], ""))
        self.assertNotIn("month", submitted(edit), "no month, so no month kept")
        # what the fields set is said beside it, as before
        self.assertEqual(edit.one("ls-schedule-next").all(tag="li")[0].text(),
                         "2026-11-05 22:00:00 until 2026-11-06 00:00:00")
        self.assertTrue(edit.one("ls-schedule-sentence").text().startswith(
            "Every day from 22:00 for 2 hours"))
        # the form for a new window asks for nothing: its part follows its fields
        self.assertNotIn("data-ls-ask",
                         self.tab_form(page).one("ls-schedule-month").attrs)

    def test_preview_draws_it_without_script_and_a_click_on_it_is_saved(self):
        self.planned()
        page = self.again(self.series_block(self.page()), preview="1")
        self.assertNotIn("data-ls-ask", page.one("ls-schedule-month").attrs)
        self.assertEqual(self.month(page).one("ls-cal__title").text(), "November 2026")
        self.assertEqual(self.label(page, "2026-11-05"),
                         "Thursday, 5 November: a window from 22:00 to 00:00 the next "
                         "day. A click leaves its window out.")
        self.assertEqual(self.label(page, "2026-11-11"),
                         "Wednesday, 11 November: no window. A click adds a window.")
        self.assertIn("data-focus", self.day(page, "2026-11-05").attrs)
        self.assertEqual(submitted(page.one("ls-schedule-form"))["month"], [""])
        page = self.again(page, day="2026-11-06")
        self.assertEqual(self.items(page),
                         ["Left out: the window from 2026-11-06 22:00:00 ×"])
        self.assertEqual(self.saved(page).status_code, 302)
        self.assertIn("\nEXDATE;TZID=Europe/Berlin:20261106T220000", self.text())

    def test_the_part_its_edit_asks_for_draws_it_with_script(self):
        self.planned()
        edit = self.series_block(self.page()).one("ls-schedule-form")
        prefix = edit.one("ls-schedule-preview").attrs["data-prefix"]
        part = self.asked(edit)
        month = part.one("ls-schedule-month")
        self.assertNotIn("data-ls-ask", month.attrs)
        self.assertEqual(month.one("ls-cal__title").attrs["id"], f"{prefix}-month")
        self.assertEqual(month.one("ls-cal__title").text(), "November 2026")
        self.assertEqual(self.label(part, "2026-11-05"),
                         "Thursday, 5 November: a window from 22:00 to 00:00 the next "
                         "day. A click leaves its window out.")
        self.assertEqual(part.one("ls-schedule-sentence").text(),
                         edit.one("ls-schedule-sentence").text(),
                         "the fields as they stand, said as the editor says them")
        self.assertIsNotNone(self.tree.standing_entry(PATH))

    def test_handled_draws_no_month_however_many_schedules_stand(self):
        self.open_series()
        for name in ("build", "lint", "docs"):
            self.tree.upsert(f"/ci/{name}", ERROR, "it failed")
            write = self.tree.set_maintenance(f"/ci/{name}", f"the {name} runners",
                                              schedule=NIGHTS, set_by="lex")
            self.assertIsNotNone(write.current)
        page = self.page("/handled")
        self.assertEqual(page.all("ls-cal"), [])
        parts = page.all("ls-schedule-month")
        self.assertEqual(len(parts), 4, "one editor for each schedule")
        self.assertTrue(all("data-ls-ask" in each.attrs and not list(each.walk())
                            for each in parts))


class TheOpenOneOffTests(_Month):
    """A window added beside an open one-off — by *Add an interval* or by a click on a
    day of the month — is written beside it, the open window keeping its start and the
    end typed, as a one-off a window joins is; it is not dropped."""

    def one_off(self) -> Element:
        self.tree.set_maintenance(PATH, "the disk swap", set_by="lex",
                                  schedule=Schedule.one_off(
                                      OPENED, CLOSES + timedelta(hours=1),
                                      "Europe/Berlin"))
        block = self.series_block(self.page())
        (form,) = [each for each in block.all(tag="form")
                   if submitted(each).get("open_once") == ["1"]]
        return form

    def test_a_window_added_by_hand_is_written_beside_it(self):
        sent: dict[str, Any] = dict(submitted(self.one_off()))
        page = self.answer(self.client.post("/pins/maintenance", data={
            **sent, "add": "1", "add_begins": "2026-11-07 09:00", "add_ends": "2h"}))
        self.assertEqual(self.items(page), ["A window from 2026-11-07 09:00:00 until "
                                            "2026-11-07 11:00:00 ×"])
        self.assertEqual(self.saved(page).status_code, 302)
        self.assertEqual(self.text(),
                         "DTSTART;TZID=Europe/Berlin:20261104T103000\nDURATION:PT2H\n"
                         "RDATE;VALUE=PERIOD:20261107T080000Z/20261107T100000Z")
        self.assertEqual(self.rows(), [("pin-set", ERROR, MAINTENANCE, ""),
                                       ("pin-edited", MAINTENANCE, MAINTENANCE, "")],
                         "the window open stays open")

    def test_a_click_on_another_day_adds_a_window_of_its_time_and_length(self):
        shown = self.answer(self.client.post("/pins/maintenance", data={
            **submitted(self.one_off()), "preview": "1"}))
        self.assertEqual(self.label(shown, "2026-11-10"),
                         "Tuesday, 10 November: no window. A click adds a window.")
        self.assertEqual(self.day(shown, "2026-11-04").attrs["aria-disabled"], "true")
        sent: dict[str, Any] = dict(submitted(shown.one("ls-schedule-form")))
        page = self.answer(self.client.post("/pins/maintenance",
                                            data={**sent, "day": "2026-11-10"}))
        self.assertEqual(self.items(page), ["A window from 2026-11-10 10:30:00 ×"])
        self.assertEqual(self.saved(page).status_code, 302)
        self.assertEqual(self.text(),
                         "DTSTART;TZID=Europe/Berlin:20261104T103000\nDURATION:PT2H\n"
                         "RDATE;TZID=Europe/Berlin:20261110T103000")
        page = self.answer(self.client.post("/pins/maintenance",
                                            data={**sent, "day": "2026-11-04"}))
        self.assertEqual(self.items(page), [], "its own day is not for a click")
