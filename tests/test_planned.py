"""What is planned can be seen (ADR-0150, landing 3b).

The snapshot carries a maintenance entry that stands and holds nothing now apart from
what holds — a node's, a line's, and one on a part not reported now, whose record a
planned window alone makes — with its next window and what of its windows its holiday
list stops; and every pin that holds carries its window open, whose end is its time
left. A planned window counts nowhere. A one-off's start is its own: set ahead, it
opens by the clock, its period begun at its start, and an edit that names its end alone
keeps it. Every surface says an entry in one function's words, its instants as that
surface writes them.
"""
from __future__ import annotations

import os
import re
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from unittest import TestCase
from urllib.parse import parse_qs, urlsplit
from zoneinfo import ZoneInfo

os.environ.setdefault("SECRET_KEY", "test-key")

from little_sister import app as app_module
from little_sister.copy_status import TimeStyle, format_node_markdown
from little_sister.holidays import HolidayList, Holidays
from little_sister.reasons import Entry as Line
from little_sister.schedule import Schedule
from little_sister.status import StatusCode
from little_sister.tree import (
    EntryWords,
    Shut,
    StatusTree,
    door_counts,
    handled_parts,
)
from tests.page_tree import Element, parse
from tests.test_windows import (
    BEFORE,
    ERROR,
    FIRST,
    FIRST_CLOSE,
    LAST_CLOSE,
    MAINTENANCE,
    NIGHTLY,
    SECOND,
    SECOND_CLOSE,
    YEAR_END,
    _utc,
    _WindowCase,
)

BERLIN = ZoneInfo("Europe/Berlin")


def page(moment: datetime) -> str:
    """An instant as a page in Berlin with the default time format writes it."""
    return moment.astimezone(BERLIN).strftime("%Y-%m-%d %H:%M:%S")


WORDS = EntryWords(page, "Europe/Berlin",
                   lambda key: "holidays in Bavaria" if key == "DE-BY" else key)


class ThePlannedEntryTests(_WindowCase):
    """An entry that stands and holds nothing now is listed apart from what holds, with
    its next window; a pin that holds carries its window open."""

    def test_a_series_between_windows_is_planned_with_its_next_window(self):
        entry = self.nightly()
        planned = self.node().planned_entry
        assert planned is not None
        self.assertEqual(planned.pin, entry)
        assert planned.next is not None
        self.assertEqual((planned.next.start, planned.next.end), (FIRST, FIRST_CLOSE))
        self.assertIsNone(planned.shut)
        self.assertIsNone(self.node().maintenance_entry)
        self.assertIsNone(self.node().maintenance_window)
        self.at(FIRST_CLOSE)
        planned = self.node().planned_entry
        assert planned is not None and planned.next is not None
        self.assertEqual(planned.next.start, SECOND, "the next is the one to come")

    def test_an_open_window_carries_its_own_end_and_is_planned_no_more(self):
        entry = self.nightly()
        self.at(FIRST)
        node = self.node()
        self.assertEqual(node.maintenance_entry, entry)
        assert node.maintenance_window is not None
        self.assertEqual((node.maintenance_window.start, node.maintenance_window.end),
                         (FIRST, FIRST_CLOSE))
        self.assertEqual(entry.expires_at, LAST_CLOSE, "its schedule ends days later")
        self.assertIsNone(node.planned_entry, "an entry stands in one place at a time")

    def test_a_line_s_planned_entry_and_its_open_window(self):
        entry = self.nightly(line="slow")
        line = next(line for line in self.node().reasons if line.slug == "slow")
        assert line.planned is not None and line.planned.next is not None
        self.assertEqual((line.planned.pin, line.planned.next.start), (entry, FIRST))
        self.assertIsNone(line.maintenance)
        self.at(FIRST)
        line = next(line for line in self.node().reasons if line.slug == "slow")
        self.assertEqual(line.maintenance, entry)
        assert line.window is not None
        self.assertEqual(line.window.end, FIRST_CLOSE)
        self.assertIsNone(line.planned)

    def test_a_line_not_reported_now_carries_its_planned_entry_alone(self):
        entry = self.nightly(line="gone")
        (record,) = self.node().not_reported
        self.assertEqual(record.slug, "gone")
        assert record.planned is not None
        self.assertEqual(record.planned.pin, entry)
        self.assertIsNone(record.maintenance)

    def test_a_node_not_reported_now_carries_its_planned_entry_alone(self):
        write = self.tree.set_maintenance("/db/replica", "resync", schedule=NIGHTLY,
                                          set_by="ada")
        (record,) = self.node().nodes_not_reported
        self.assertEqual(record.path, "/db/replica")
        assert record.planned_entry is not None
        self.assertEqual(record.planned_entry.pin, write.current)
        self.assertIsNone(record.maintenance_entry)
        self.at(FIRST)
        (record,) = self.node().nodes_not_reported
        self.assertEqual(record.maintenance_entry, write.current)
        assert record.maintenance_window is not None
        self.assertEqual(record.maintenance_window.end, FIRST_CLOSE)
        self.assertIsNone(record.planned_entry)

    def test_a_planned_window_counts_nowhere(self):
        self.nightly()
        self.nightly(line="slow")
        node = self.node()
        self.assertEqual((node.own_code, node.code), (ERROR, ERROR))
        self.assertEqual(handled_parts(node), ())
        self.assertEqual(door_counts(node)["/db"].by_job, {})

    def test_the_standing_entry_is_the_one_an_edit_names(self):
        entry = self.nightly()
        line = self.nightly(line="slow")
        self.assertIsNone(self.tree.maintenance_entry("/db"), "it holds nothing")
        self.assertEqual(self.tree.standing_entry("db"), entry)
        self.assertEqual(self.tree.standing_line_entry("/db", "slow"), line)
        self.at(FIRST)
        self.assertEqual(self.tree.standing_entry("/db"), entry)
        self.assertEqual(self.tree.maintenance_entry("/db"), entry)


class TheOneOffSetAheadTests(_WindowCase):
    """A one-off's start is its own: set ahead it holds nothing until its start, opens
    there by the clock, and an edit naming its end alone keeps it."""

    def ahead(self) -> Schedule:
        return Schedule.one_off(FIRST, FIRST_CLOSE, "Europe/Berlin")

    def test_it_is_planned_until_its_start_and_its_period_begins_there(self):
        write = self.tree.set_maintenance("/db", "patching", schedule=self.ahead(),
                                          set_by="ada")
        self.assertEqual(self.rows(), [], "set ahead, it holds nothing")
        planned = self.node().planned_entry
        assert planned is not None and planned.next is not None
        self.assertEqual(planned.next.start, FIRST)
        self.at(FIRST)
        self.assertEqual(self.rows(), [("pin-opened", ERROR, MAINTENANCE, "")])
        node = self.node()
        assert node.own_period is not None
        self.assertEqual(node.own_period.at, FIRST, "its period begins at its start")
        self.assertEqual(node.maintenance_entry, write.current)
        self.at(FIRST_CLOSE)
        self.assertEqual(self.rows()[-1][0], "pin-ended")

    def test_an_edit_by_its_end_alone_keeps_a_planned_start(self):
        write = self.tree.set_maintenance("/db", "patching", schedule=self.ahead(),
                                          set_by="ada")
        assert write.current is not None
        edit = self.tree.set_maintenance(
            "/db", "patching", expires_at=FIRST_CLOSE + timedelta(hours=1),
            set_by="bo", expected_set_at=write.current.token)
        assert edit.current is not None and edit.current.schedule is not None
        self.assertEqual(edit.current.schedule.starts_at, FIRST)
        self.assertEqual(edit.current.expires_at, FIRST_CLOSE + timedelta(hours=1))
        self.assertIsNone(self.tree.maintenance_entry("/db"), "still planned")

    def test_an_edit_by_its_end_alone_keeps_an_open_window_s_start(self):
        made = self.clock.at
        write = self.tree.set_maintenance("/db", "patching",
                                          expires_at=made + timedelta(hours=3),
                                          set_by="ada")
        assert write.current is not None
        self.clock.at = made + timedelta(hours=1)
        edit = self.tree.set_maintenance(
            "/db", "patching", expires_at=made + timedelta(hours=5), set_by="bo",
            expected_set_at=write.current.token)
        assert edit.current is not None and edit.current.schedule is not None
        self.assertEqual(edit.current.schedule.starts_at, made)
        node = self.node()
        assert node.maintenance_window is not None and node.own_period is not None
        self.assertEqual(node.maintenance_window.start, made)
        self.assertEqual(node.own_period.at, made, "it began where it was set")

    def test_a_save_that_changes_nothing_writes_nothing(self):
        write = self.tree.set_maintenance("/db", "patching", schedule=self.ahead(),
                                          set_by="ada")
        assert write.current is not None
        again = self.tree.set_maintenance(
            "/db", "patching", expires_at=FIRST_CLOSE, set_by="bo",
            expected_set_at=write.current.token)
        self.assertFalse(again.applied)
        self.assertEqual(again.current, write.current)

    def test_a_series_given_one_end_becomes_one_window_from_now(self):
        self.nightly()
        stored = self.tree.standing_entry("/db")
        assert stored is not None
        edit = self.tree.set_maintenance("/db", "now", expires_at=self.clock.at
                                         + timedelta(hours=1), set_by="bo",
                                         expected_set_at=stored.token)
        assert edit.current is not None and edit.current.schedule is not None
        self.assertTrue(edit.current.schedule.is_one_off)
        self.assertEqual(edit.current.schedule.starts_at,
                         self.clock.at.replace(microsecond=0))


class TheListsStopTests(_WindowCase):
    """What of a planned entry's windows its holiday list stops, said where it is
    listed (decision 6 of #35's note): every one, where the list cannot be had; those
    from the first year it does not state; or every one left, each on a listed day."""

    def use(self, *, complete: frozenset[int] = frozenset({2026}),
            dates: dict[date, str] | None = None) -> None:
        self.tree.use_holidays(Holidays(lists={"DE-BY": HolidayList(
            "DE-BY", "holidays in Bavaria", complete, dates or {},
            Path("holidays.yaml"))}))

    def test_a_list_that_cannot_be_had_stops_every_window(self):
        self.tree.use_holidays(Holidays(
            unreadable={"DE-BY": "holidays.yaml: the holiday list DE-BY cannot be "
                                 "read — it writes 2026-12-25 twice"},
            files=(Path("holidays.yaml"),)))
        self.nightly(not_on="DE-BY")
        self.nightly(line="slow", not_on="ACME")
        planned = self.node().planned_entry
        assert planned is not None
        self.assertIsNone(planned.next)
        self.assertEqual(WORDS.why(planned),
                         "applies not at all: holidays.yaml: the holiday list DE-BY "
                         "cannot be read — it writes 2026-12-25 twice")
        line = next(line for line in self.node().reasons if line.slug == "slow")
        assert line.planned is not None
        self.assertEqual(WORDS.why(line.planned),
                         "applies not at all: holidays.yaml lists no ACME")

    def test_a_year_the_list_does_not_state_stops_its_windows_from_its_start(self):
        self.use()
        self.clock.at = _utc(30, 12, month=12)
        self.nightly(not_on="DE-BY", schedule=YEAR_END)
        planned = self.node().planned_entry
        assert planned is not None and planned.next is not None
        self.assertEqual(planned.next.start, _utc(30, 21, month=12), "2026's comes")
        self.assertEqual(planned.shut, Shut("DE-BY", year=2027,
                                            begins=_utc(31, 23, month=12)))
        self.assertEqual(WORDS.why(planned),
                         "from 2027-01-01 00:00:00 its windows do not apply: the "
                         "list is not complete for 2027")
        self.at(_utc(30, 21, month=12), _utc(30, 23, month=12),
                _utc(31, 21, month=12), _utc(31, 23, month=12))
        planned = self.node().planned_entry
        assert planned is not None
        self.assertIsNone(planned.next, "2027's is all that is left")
        self.assertEqual(planned.shut, Shut("DE-BY", year=2027,
                                            begins=_utc(31, 23, month=12)))

    def test_every_window_left_on_a_listed_day(self):
        self.use(dates={date(2026, 11, 3): "a day off", date(2026, 11, 4): "another"})
        self.nightly(not_on="DE-BY")
        self.at(FIRST, FIRST_CLOSE)
        planned = self.node().planned_entry
        assert planned is not None
        self.assertIsNone(planned.next)
        self.assertEqual(planned.shut, Shut("DE-BY"))
        self.assertEqual(WORDS.why(planned),
                         "no window is to open: each one left is on a day its list "
                         "names")

    def test_a_list_that_states_every_year_stops_nothing(self):
        self.use(dates={date(2026, 11, 3): "a day off"})
        self.nightly(not_on="DE-BY")
        planned = self.node().planned_entry
        assert planned is not None and planned.next is not None
        self.assertIsNone(planned.shut)
        self.assertEqual(WORDS.why(planned), "")
        self.at(FIRST_CLOSE)
        planned = self.node().planned_entry
        assert planned is not None and planned.next is not None
        self.assertEqual(planned.next.start, _utc(4, 21), "the listed day is skipped")


class TheWordsTests(_WindowCase):
    """An entry in one function's words, its instants as the surface writes them."""

    def test_a_series_and_a_one_off(self):
        entry = self.nightly(not_on="DE-BY")
        self.assertEqual(WORDS.sentence(entry),
                         "Every day from 22:00 for 2 hours, until 2026-11-05 00:00:00, "
                         "not on holidays in Bavaria")
        once = self.tree.set_maintenance(
            "/db/replica", "resync",
            schedule=Schedule.one_off(SECOND, SECOND_CLOSE, "Europe/Berlin"))
        assert once.current is not None
        self.assertEqual(WORDS.sentence(once.current),
                         "Once, from 2026-11-03 22:00:00 until 2026-11-04 00:00:00")

    def test_a_surface_in_another_zone_names_the_entry_s(self):
        entry = self.nightly()
        words = EntryWords(lambda moment: moment.astimezone(UTC).isoformat(), "UTC")
        self.assertEqual(words.sentence(entry),
                         "Every day from 22:00 (Europe/Berlin) for 2 hours, until "
                         "2026-11-04T23:00:00+00:00")
        self.assertTrue(BEFORE < FIRST)


# --- the pages ---------------------------------------------------------------------

PATH = "/ci/actions"
#: The node as the page's own forms name it: the route's `branch`.
FORM_PATH = "ci/actions"


def _wall(moment: datetime) -> str:
    """An instant as a schedule's text writes a start, in Berlin."""
    return moment.astimezone(BERLIN).strftime("%Y%m%dT%H%M%S")


def _daily(first: datetime, *, hours: int = 2, days: int = 10) -> Schedule:
    """Every day from ``first``'s time of day for ``hours``, for ``days``."""
    until = (first + timedelta(days=days)).astimezone(UTC).strftime("%Y%m%dT%H%M%SZ")
    return Schedule.parse(f"DTSTART;TZID=Europe/Berlin:{_wall(first)}\n"
                          f"DURATION:PT{hours}H\nRRULE:FREQ=DAILY;UNTIL={until}")


class _PageCase(TestCase):
    """A workflow check's node with two lines, read by an admin on the real clock."""

    def setUp(self) -> None:
        app_module.app.config["TESTING"] = True
        self.tree = StatusTree()
        app_module.status_tree = self.tree
        self.client = app_module.app.test_client()
        self.client.post("/login", data={"username": "pan", "password": "12345678"})
        self.tree.upsert(PATH, ERROR, [Line("build", "build failed", code=ERROR),
                                       Line("lint", "lint passed",
                                            code=StatusCode.OK)], members=True)
        self.now = datetime.now(UTC).replace(microsecond=0)

    def page(self, url: str) -> Element:
        answer = self.client.get(url)
        self.assertEqual(answer.status_code, 200, url)
        return parse(answer.get_data(as_text=True))

    def ahead(self, days: int = 6, hours: int = 8, slug: str = "") -> Schedule:
        """A one-off ``days`` ahead, ``hours`` long, set on the node or a line."""
        once = Schedule.one_off(self.now + timedelta(days=days),
                                self.now + timedelta(days=days, hours=hours),
                                "Europe/Berlin")
        if slug:
            self.tree.set_entry_maintenance(PATH, slug, "patch day", schedule=once,
                                            set_by="anna")
        else:
            self.tree.set_maintenance(PATH, "patch day", schedule=once,
                                      set_by="anna")
        return once

    def planned_blocks(self, page: Element) -> list[Element]:
        return page.all("rule-block--planned")


class ThePlannedBlockTests(_PageCase):
    """A planned window's block (ADR-0150, landing 3b's first two questions): its one
    sentence and when it starts, untinted; a one-off's *Edit* with *Starts* and its
    end filled, and *Clear* asking nothing; a series with no *Edit* and a *Clear* that
    asks first."""

    def test_a_one_off_set_ahead_says_its_sentence_and_starts_in(self):
        self.ahead()
        tab = self.page(f"/notes/{FORM_PATH}")
        (block,) = self.planned_blocks(tab)
        said = block.one("rule-block__what").text(shown=True)
        start = page(self.now + timedelta(days=6))
        end = page(self.now + timedelta(days=6, hours=8))
        self.assertIn(f"The whole node · Once, from {start} until {end} · starts in "
                      f"5d 23h", said)
        self.assertEqual(block.attrs["data-rule"], "maintenance")
        self.assertIn("Pinned by anna",
                      block.all("rule-block__record", tag="p")[-1].text())

    def test_its_edit_fills_starts_and_the_end_and_its_clear_asks_nothing(self):
        self.ahead()
        (block,) = self.planned_blocks(self.page(f"/notes/{FORM_PATH}"))
        editor = block.one("rule-block__editor")
        fields = {element.attrs.get("name"): element.attrs.get("value", "")
                  for element in editor.all(tag="input")}
        start = app_module._expiry_input(self.now + timedelta(days=6))
        self.assertEqual((fields["starts"], fields["starts_was"]), (start, start))
        self.assertEqual(fields["duration"], fields["expiry_was"])
        self.assertEqual(block.all("rule-block__ask"), [],
                         "a one-off's Clear asks nothing")
        self.assertEqual(len(block.all("rule-block__clear")), 1)

    def test_a_series_planned_has_its_editor_filled_and_its_clear_asks(self):
        tomorrow = self.now + timedelta(days=1)
        self.tree.set_entry_maintenance(PATH, "lint", "nightly", schedule=_daily(
            tomorrow), set_by="lex")
        (block,) = self.planned_blocks(self.page(f"/notes/{FORM_PATH}"))
        said = block.one("rule-block__what").text(shown=True)
        self.assertIn(f"Every day from {tomorrow.astimezone(BERLIN):%H:%M:%S} for 2 "
                      f"hours", said)
        self.assertIn(f"· next {page(tomorrow)} · in 23h 59m", said)
        # landing 4: the series' editor, every field filled — its next window's start,
        # its length, its rule and its last date
        editor = block.one("rule-block__edit").one(tag="form")
        values = {each.attrs.get("name"): each.attrs.get("value", "")
                  for each in editor.all(tag="input")}
        start = app_module._expiry_input(tomorrow)
        self.assertEqual((values["starts"], values["starts_was"]), (start, start))
        self.assertEqual(values["duration"], "2h")
        self.assertEqual(values["until"], values["until_was"])
        (repeat,) = [each for each in editor.all(tag="select")
                     if each.attrs.get("name") == "repeat"]
        self.assertEqual([each.attrs["value"] for each in repeat.all(tag="option")
                          if "selected" in each.attrs], ["daily"])
        asked = block.one("rule-block__ask")
        self.assertIn("This ends every window of the schedule, those to come.",
                      asked.text())
        self.assertEqual([button.text() for button in asked.all(tag="button")],
                         ["Clear the schedule", "Keep it"])

    def test_an_open_series_window_is_two_rows_its_own_end_and_its_schedule(self):
        began = self.now - timedelta(minutes=30)
        self.tree.set_entry_maintenance(PATH, "build", "nightly", schedule=_daily(
            began), set_by="lex")
        tab = self.page(f"/notes/{FORM_PATH}")
        (block,) = [each for each in tab.all("rule-block")
                    if each.attrs.get("data-rule") == "maintenance"]
        first, second = block.all("rule-block__head")
        said = first.one("rule-block__what").text(shown=True)
        self.assertIn(f"until {page(began + timedelta(hours=2))} · 1h 29m left", said)
        self.assertNotIn("planned", block.attrs.get("class", ""))
        # landing 4: the window's row with Extend and End now, the schedule's with
        # its next start, Edit and Clear, which asks
        def buttons(row: Element) -> list[str]:
            return [child.first().text(shown=True) for child in row.children
                    if isinstance(child, Element) and child.tag == "details"]

        self.assertEqual(buttons(first), ["Extend", "End now"])
        schedule = second.one("rule-block__schedule").text(shown=True)
        self.assertIn("Every day from", schedule)
        self.assertIn(f"· next {page(began + timedelta(days=1))}", schedule)
        self.assertEqual(buttons(second), ["Edit", "Clear"])
        self.assertIn("this one and those to come",
                      block.one("rule-block__ask").text())

    def test_a_planned_window_is_listed_apart_and_counted_nowhere(self):
        self.ahead()
        tab = self.page(f"/notes/{FORM_PATH}")
        stands = tab.one("ls-tab__stands")
        self.assertEqual(self.planned_blocks(stands), [])
        self.assertIn("Nothing stands here now", stands.text())
        section = tab.one("ls-tab__planned")
        self.assertIn("1 window planned, the soonest first.", section.text())
        # what is counted is said: a window set ahead is a window, a series a schedule
        self.tree.set_entry_maintenance(PATH, "lint", "nightly", schedule=_daily(
            self.now + timedelta(days=1)), set_by="lex")
        section = self.page(f"/notes/{FORM_PATH}").one("ls-tab__planned")
        self.assertIn("1 window and 1 schedule planned, the soonest first.",
                      section.text())

    def test_a_planned_sentence_keeps_its_dates_whole_and_ends_a_line_before_in(self):
        # On a phone a line ended inside them: *until 2027-* and *02-01 00:00:00* in
        # the drawer's block, *2027-02-* and *01* in the head's line, each date's
        # words kept whole as a standing block keeps an instant's; and *· next … ·
        # in 4h 51m*, kept on one line, was wider than the block.
        tomorrow = (self.now + timedelta(days=1)).astimezone(BERLIN).replace(
            hour=22, minute=0, second=0)
        self.tree.set_maintenance(PATH, "nightly", schedule=_daily(tomorrow, days=90),
                                  set_by="lex")
        (block,) = self.planned_blocks(self.page(f"/notes/{FORM_PATH}"))
        (line,) = self.page(f"/status/{FORM_PATH}").all("planned-line")
        for said in (block.one("rule-block__what"), line.one("planned-line__said")):
            text = said.text(shown=True)
            whole = [run.text(shown=True) for run in said.all("text-nowrap")]
            dates = re.findall(r"\d{4}-\d{2}-\d{2}", text)
            times = re.findall(r"\d{2}:\d{2}:\d{2}", text)
            self.assertEqual(len(dates), 2, text)
            for word in (*dates, *times):
                self.assertIn(word, whole, text)
            nexts = [run for run in whole if run.startswith("· next ")]
            ins = [run for run in whole if run.startswith("· in ")]
            self.assertEqual((len(nexts), len(ins)), (1, 1), whole)
            self.assertNotIn("· in", nexts[0])

    def test_its_holiday_list_says_why_no_window_is_to_open(self):
        self.tree.set_maintenance(PATH, "on a list it cannot have",
                                  schedule=_daily(self.now + timedelta(days=1)),
                                  not_on="DE-BY", set_by="ada")
        (block,) = self.planned_blocks(self.page(f"/notes/{FORM_PATH}"))
        said = block.one("rule-block__what").text(shown=True)
        self.assertIn("not on DE-BY", said)
        self.assertIn("· applies not at all:", said)
        self.assertNotIn("next", said)


class WherePlannedIsListedTests(_PageCase):
    """*Planned* on a node's page — one line each, a door to its block — and on
    *Handled*, with its own count, the soonest first (ADR-0150, decision 5)."""

    def test_a_node_s_page_lists_them_beneath_its_blocks_each_a_door(self):
        self.ahead()
        self.tree.set_entry_maintenance(PATH, "lint", "nightly", schedule=_daily(
            self.now + timedelta(days=1)), set_by="lex")
        head = self.page(f"/status/{FORM_PATH}")
        lines = head.all("planned-line")
        self.assertEqual(len(lines), 2)
        first, second = (line.text(shown=True) for line in lines)
        self.assertTrue(first.startswith("lint passed · Every day from"), first)
        self.assertIn("The whole node · Once, from", second)
        self.assertIn("· starts in 5d 23h", second)
        door = lines[0].one("planned-line__door")
        self.assertIn("data-door", door.attrs)
        where = urlsplit(door.attrs["href"])
        self.assertEqual(where.path, f"/notes/{FORM_PATH}")
        self.assertEqual(parse_qs(where.query), {"at": ["maintenance"],
                                                  "reason": ["lint"]})
        self.assertEqual(where.fragment, "at")

    def test_handled_has_planned_with_its_own_count(self):
        self.ahead()
        self.tree.upsert("/db", ERROR, "slow")
        self.tree.set_maintenance("/db", "vacuum", schedule=_daily(
            self.now + timedelta(days=1)), set_by="lex")
        handled = self.page("/handled")
        self.assertIn("Nothing is in maintenance now.", handled.text())
        self.assertIn("1 window and 1 schedule on 2 nodes, the soonest first.",
                      handled.text())
        first, second = self.planned_blocks(handled)
        self.assertIn("/db", first.text(shown=True), "the soonest first")
        self.assertIn(PATH, second.text(shown=True))

    def test_the_tab_lands_on_a_planned_block_asked_at(self):
        self.ahead(slug="lint")
        tab = self.page(f"/notes/{FORM_PATH}?at=maintenance&reason=lint")
        landed = tab.with_id("at")
        self.assertTrue(landed.has("rule-block--planned"))
        self.assertIn("autofocus", landed.attrs)

    def test_the_form_offers_a_window_that_joins_a_part_one_is_planned_for(self):
        self.ahead(slug="lint")
        entry = self.tree.standing_line_entry(PATH, "lint")
        assert entry is not None
        tab = self.page(f"/notes/{FORM_PATH}")
        form = [each for each in tab.all("ls-kind-form")
                if each.attrs.get("data-kind") == "maintenance"]
        (maintenance,) = form
        (on,) = [each for each in maintenance.all(tag="select")
                 if each.attrs.get("name") == "slug"]
        offered = {option.attrs.get("value"): option.text(shown=True)
                   for option in on.all(tag="option")}
        # landing 4: the part is offered, its window joining the entry, whose token
        # the form carries for it
        self.assertIn("— a schedule stands on it", offered["lint"])
        self.assertNotIn("schedule", offered["build"])
        hidden = {each.attrs.get("name"): each.attrs.get("value", "")
                  for each in maintenance.all(tag="input")
                  if each.attrs.get("type") == "hidden"}
        self.assertEqual(hidden["set_at:lint"], entry.token)
        self.assertNotIn("set_at:build", hidden)
        self.assertEqual([each.attrs.get("value")
                          for each in maintenance.all(tag="input")
                          if each.attrs.get("name") == "with"], ["join", "replace"])


class StartsTests(_PageCase):
    """*Starts* on the form for a new window (ADR-0150, landing 3b's fourth question):
    read in the end field's grammar, blank meaning now, a duration counting from it;
    refused where it has passed, where the end is not after it, and where the end is
    more than a year from now; and a set that plans a window answered at the tab, at
    its new block."""

    def set(self, starts: str, duration: str = "2h", **more: str):
        form = {"path": FORM_PATH, "action": "set", "set_at": "", "note": "patch",
                "starts": starts, "duration": duration, "next": "/", **more}
        return self.client.post("/pins/maintenance", data=form)

    def test_a_start_ahead_plans_one_window_its_duration_counted_from_it(self):
        answer = self.set("3d", "2h")
        self.assertEqual(answer.status_code, 302)
        self.assertIsNone(self.tree.maintenance_entry(PATH), "it holds nothing yet")
        entry = self.tree.standing_entry(PATH)
        assert entry is not None and entry.schedule is not None
        start = entry.schedule.starts_at
        self.assertAlmostEqual((start - self.now).total_seconds(), 3 * 86400, delta=5)
        self.assertEqual(entry.expires_at - start, timedelta(hours=2))

    def test_a_planned_set_is_answered_at_the_tab_at_its_block(self):
        answer = self.set("3d")
        where = urlsplit(answer.headers["Location"])
        self.assertEqual(where.path, f"/notes/{FORM_PATH}")
        self.assertEqual(parse_qs(where.query), {"at": ["maintenance"]})
        self.assertEqual(where.fragment, "at")
        in_panel = self.set("3d", panel="1", set_at=self.tree.standing_entry(
            PATH).token)
        self.assertEqual(parse_qs(urlsplit(in_panel.headers["Location"]).query),
                         {"at": ["maintenance"], "panel": ["1"]})

    def test_a_blank_start_opens_the_window_now_and_goes_back_as_before(self):
        answer = self.set("")
        self.assertEqual(answer.headers["Location"], "/")
        self.assertIsNotNone(self.tree.maintenance_entry(PATH))

    def test_a_start_that_has_passed_is_refused_leave_it_blank(self):
        passed = (self.now - timedelta(days=1)).astimezone(
            app_module.config.tzinfo).strftime("%Y-%m-%d %H:%M")
        answer = self.set(passed)
        self.assertEqual(answer.status_code, 200)
        said = parse(answer.get_data(as_text=True)).text()
        self.assertIn("has passed. To start the window now, leave Starts blank.",
                      said)
        self.assertIsNone(self.tree.standing_entry(PATH))

    def test_an_end_not_after_the_start_is_refused(self):
        start = (self.now + timedelta(days=2)).astimezone(app_module.config.tzinfo)
        end = start - timedelta(hours=1)
        answer = self.set(start.strftime("%Y-%m-%d %H:%M"),
                          end.strftime("%Y-%m-%d %H:%M"))
        said = parse(answer.get_data(as_text=True)).text()
        self.assertIn("A maintenance window has to end after it starts", said)
        self.assertIsNone(self.tree.standing_entry(PATH))

    def test_an_end_more_than_a_year_from_now_is_refused(self):
        answer = self.set("30d", "350d")
        said = parse(answer.get_data(as_text=True)).text()
        self.assertIn("ends more than a year from now", said)
        self.assertIsNone(self.tree.standing_entry(PATH))

    def test_a_planned_window_s_start_is_kept_moved_or_emptied(self):
        self.set("3d")
        entry = self.tree.standing_entry(PATH)
        assert entry is not None and entry.schedule is not None
        filled = app_module._expiry_input(entry.schedule.starts_at)
        end = app_module._expiry_input(entry.expires_at)
        kept = self.set(filled, end, set_at=entry.token, starts_was=filled,
                        expiry_was=end, note="patch, longer")
        self.assertEqual(kept.status_code, 302)
        after = self.tree.standing_entry(PATH)
        assert after is not None and after.schedule is not None
        self.assertEqual(after.schedule.starts_at, entry.schedule.starts_at)
        past_its_end = self.set("4d", end, set_at=after.token, starts_was=filled,
                                expiry_was=end)
        self.assertIn("has to end after it starts",
                      parse(past_its_end.get_data(as_text=True)).text())
        an_hour_on = app_module._expiry_input(after.schedule.starts_at
                                              + timedelta(hours=1))
        moved = self.set(an_hour_on, end, set_at=after.token, starts_was=filled,
                         expiry_was=end)
        self.assertEqual(moved.status_code, 302)
        later = self.tree.standing_entry(PATH)
        assert later is not None and later.schedule is not None
        self.assertEqual(later.schedule.starts_at,
                         after.schedule.starts_at + timedelta(hours=1))
        self.assertEqual(later.expires_at, after.expires_at, "its end kept")
        emptied = self.set("", "2h", set_at=later.token, starts_was=app_module
                           ._expiry_input(later.schedule.starts_at))
        self.assertEqual(emptied.status_code, 302)
        self.assertIsNotNone(self.tree.maintenance_entry(PATH), "it starts now")


class TheRowsAndTheCopyTests(_PageCase):
    """The rows a window's opening and close write, in each surface's words, and the
    Copy document's planned window (ADR-0150)."""

    def test_events_and_history_name_a_window_opened_and_closed(self):
        self.assertEqual(app_module._CAUSE_CHIPS["pin-opened"], "window opened")
        self.assertEqual(app_module._CAUSE_CHIPS["line-pin-closed"],
                         "line's window closed")
        self.assertEqual(app_module._WHAT_MOVED["pin-closed"], "a window closed")
        self.assertEqual(app_module._WHAT_MOVED["line-pin-opened"],
                         "a line's window opened")

    def test_the_copy_lists_a_planned_window_after_the_node_s_pins(self):
        self.ahead()
        node = self.tree.snapshot(PATH)
        assert node is not None
        written = format_node_markdown(node, TimeStyle(BERLIN))
        start = page(self.now + timedelta(days=6))
        self.assertIn(f"🛠️ Planned — once, from {start} +01:00 until", written)
        self.assertIn(", by anna", written)

    def test_the_copy_says_an_open_series_window_s_own_end(self):
        began = self.now - timedelta(minutes=30)
        self.tree.set_maintenance(PATH, "nightly", schedule=_daily(began),
                                  set_by="lex")
        node = self.tree.snapshot(PATH)
        assert node is not None
        written = format_node_markdown(node, TimeStyle(BERLIN))
        self.assertIn(f"🛠️ Maintenance — by lex, until "
                      f"{page(began + timedelta(hours=2))} +01:00", written)
