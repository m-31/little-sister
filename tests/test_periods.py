"""A period is a run of events that show the same status (ADR-0099).

What a pin did to its node's periods, found in walking the built block on a running
deployment (backlog #89's B9):

* An edit of the pin writes an event, deliberately (ADR-0014 decision 9), and every
  event began a period: a node silenced at 11:19:02 and edited at 11:20:44 read
  *maintenance since 11:20:44*, and History listed two maintenance periods.
* The row that held showed the node's own lines, or nothing on a branch, where an
  ended one showed the note the pin was set with.
* A period that a pin's end began read as the moment the node broke or recovered:
  *ok since 11:29:33* for a reading that had not changed in days.

An edit is an event and no period; a maintenance row shows the pin's note as it last
stood; and a period that a pin's end began says so, on the Time card and in the Copy
document.
"""
from __future__ import annotations

import os
import re
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from unittest import TestCase

os.environ.setdefault("SECRET_KEY", "test-key")

from little_sister import app as app_module
from little_sister.copy_status import TimeStyle, format_node_markdown
from little_sister.maintenance import MaintenanceEntry
from little_sister.status import StatusCode
from little_sister.tree import Event, StatusPeriod, StatusTree
from tests.page_tree import Element, parse

OK, WARN, ERROR = StatusCode.OK, StatusCode.WARN, StatusCode.ERROR
MAINTENANCE, UNDEFINED = StatusCode.MAINTENANCE, StatusCode.UNDEFINED

#: Yesterday, to the second: a restored log is written at instants a page can show
#: apart, where two writes of one test stand microseconds from each other.
_DAY = (datetime.now(UTC) - timedelta(days=1)).replace(microsecond=0)
_SOON = datetime.now(UTC) + timedelta(days=2)


def _at(minutes: int) -> datetime:
    return _DAY + timedelta(minutes=minutes)


def _event(path: str, old: StatusCode, new: StatusCode, minutes: int,
           *reason: str) -> Event:
    return Event(path=path, name=path.rsplit("/", 1)[-1], old=old, new=new,
                 reason=reason, timestamp=_at(minutes), suppressed_by="")


def _pin(note: str) -> MaintenanceEntry:
    """A pin as the store holds one."""
    tree = StatusTree()
    tree.set_maintenance("/any", note, expires_at=_SOON, set_by="lex")
    entry = tree.maintenance_entry("/any")
    assert entry is not None
    return entry


def _codes(periods: list[StatusPeriod]) -> list[StatusCode]:
    return [period.code for period in periods]


class RunTests(TestCase):
    """An edit is an event and no period."""

    def setUp(self) -> None:
        self.tree = StatusTree()
        self.tree.upsert("/nas/drive4", WARN, "reallocated sectors: 12")
        self.tree.set_maintenance("/nas/drive4", "Replacing it on Saturady.",
                                  expires_at=_SOON, set_by="lex")

    def _events(self) -> list[Event]:
        return [event for event in self.tree.recent_events()
                if event.path == "/nas/drive4"]

    def test_an_edit_of_the_note_begins_no_period(self):
        self.tree.set_maintenance("/nas/drive4", "Replacing it on Saturday.",
                                  expires_at=_SOON, set_by="lex")
        warn, pinned = self.tree.history("/nas/drive4")
        _, the_set, the_edit = self._events()
        self.assertEqual((the_edit.old, the_edit.new), (MAINTENANCE, MAINTENANCE),
                         "the edit is still an event (ADR-0014 decision 9)")
        self.assertEqual((pinned.code, pinned.since), (MAINTENANCE, the_set.timestamp))
        self.assertEqual(warn.until, the_set.timestamp)

    def test_an_edit_of_the_expiry_begins_none_either(self):
        self.tree.set_maintenance("/nas/drive4", "Replacing it on Saturady.",
                                  expires_at=_SOON + timedelta(days=1),
                                  set_by="anna")
        self.assertEqual(len(self._events()), 3)
        self.assertEqual(_codes(self.tree.history("/nas/drive4")),
                         [WARN, MAINTENANCE])

    def test_a_period_ends_where_the_next_status_begins(self):
        self.tree.set_maintenance("/nas/drive4", "Replacing it on Saturday.",
                                  expires_at=_SOON, set_by="lex")
        self.tree.clear_maintenance("/nas/drive4")
        warn, pinned, again = self.tree.history("/nas/drive4")
        the_clear = self._events()[-1]
        self.assertEqual(_codes([warn, pinned, again]), [WARN, MAINTENANCE, WARN])
        self.assertEqual(pinned.until, the_clear.timestamp)
        self.assertEqual(again.since, the_clear.timestamp)

    def test_a_second_pin_is_a_period_of_its_own(self):
        # cleared and set again: two windows, with the status between them
        self.tree.clear_maintenance("/nas/drive4")
        self.tree.set_maintenance("/nas/drive4", "And again.", expires_at=_SOON,
                                  set_by="lex")
        self.assertEqual(_codes(self.tree.history("/nas/drive4")),
                         [WARN, MAINTENANCE, WARN, MAINTENANCE])

    def test_a_period_says_what_the_node_showed_before_it(self):
        # before its first event, that is: an edit within it shows nothing new
        self.tree.set_maintenance("/nas/drive4", "Replacing it on Saturday.",
                                  expires_at=_SOON, set_by="lex")
        self.tree.upsert("/nas/drive4", ERROR, "reallocated sectors: 80")
        self.tree.clear_maintenance("/nas/drive4")
        warn, pinned, error = self.tree.history("/nas/drive4")
        self.assertEqual((warn.previous, pinned.previous, error.previous),
                         (UNDEFINED, WARN, MAINTENANCE))

    def test_a_run_whose_first_event_is_an_edit_began_before_the_log(self):
        # the pin's set has left the bounded log and an edit of it is kept: the
        # period began before that event, which says so itself
        tree = StatusTree()
        tree.restore_events([
            _event("/db", MAINTENANCE, MAINTENANCE, 5, "a longer window")])
        tree.restore_maintenance({"/db": _pin("a longer window")})
        # a replay makes no node (ADR-0109 decision 4): its check's first run does
        tree.upsert("/db", OK, "in step")
        period, = tree.history("/db")
        self.assertEqual((period.code, period.previous, period.since),
                         (MAINTENANCE, MAINTENANCE, _at(5)))


class NoteTests(TestCase):
    """A maintenance row shows the pin's note as it last stood."""

    def setUp(self) -> None:
        self.tree = StatusTree()
        self.tree.upsert("/nas/drive4", WARN, "reallocated sectors: 12")
        self.tree.set_maintenance("/nas/drive4", "Replacing it on Saturady.",
                                  expires_at=_SOON, set_by="lex")

    def test_the_row_that_holds_shows_the_pins_note(self):
        # it showed the node's own lines, which stay on its Status page
        self.assertEqual(self.tree.history("/nas/drive4")[-1].reason,
                         ("Replacing it on Saturady.",))

    def test_as_the_note_stands_after_an_edit(self):
        self.tree.set_maintenance("/nas/drive4", "Replacing it on Saturday.",
                                  expires_at=_SOON, set_by="lex")
        self.assertEqual(self.tree.history("/nas/drive4")[-1].reason,
                         ("Replacing it on Saturday.",))

    def test_an_ended_row_shows_the_wording_its_period_ended_with(self):
        self.tree.set_maintenance("/nas/drive4", "Replacing it on Saturday.",
                                  expires_at=_SOON, set_by="lex")
        self.tree.clear_maintenance("/nas/drive4")
        warn, pinned, again = self.tree.history("/nas/drive4")
        self.assertEqual(pinned.reason, ("Replacing it on Saturday.",))
        # and the rows around it read as they did
        self.assertEqual(warn.reason, ("reallocated sectors: 12",))
        self.assertEqual(again.reason, ("reallocated sectors: 12",))

    def test_a_pinned_branch_shows_its_note_too(self):
        # nothing writes a branch, so the row that held was empty
        self.tree.upsert("/hosts/a/cpu", OK, "fine")
        self.tree.set_maintenance("/hosts/a", "Kernel update.", expires_at=_SOON,
                                  set_by="lex")
        self.tree.set_maintenance("/hosts/a", "Kernel update, back by 23:30.",
                                  expires_at=_SOON, set_by="lex")
        period, = self.tree.history("/hosts/a")
        self.assertEqual(period.reason, ("Kernel update, back by 23:30.",))

    def test_a_pin_stored_without_a_note_leaves_its_row_empty(self):
        # a set through the tree writes a placeholder for a blank note; a pins file
        # written by hand can hold none, and its event carries none either
        tree = StatusTree()
        tree.upsert("/quiet", OK, "fine")
        tree.restore_maintenance({"/quiet": replace(_pin("x"), reason="")})
        self.assertEqual(tree.recent_events()[-1].reason, ())
        self.assertEqual(tree.history("/quiet")[-1].reason, ())

    def test_the_note_is_the_stored_pins_and_not_the_logs(self):
        # a pins file changed while the process was down: its replay writes
        # nothing (ADR-0094 decision 2), and the row says what the pin says now
        tree = StatusTree()
        tree.restore_events([_event("/db", UNDEFINED, OK, 0),
                             _event("/db", OK, MAINTENANCE, 5, "planned")])
        tree.restore_maintenance({"/db": _pin("planned, and a day longer")})
        self.assertEqual(len(tree.recent_events()), 2)
        # the node is its check's to write, as it stood: nothing for the restart
        self.assertFalse(tree.upsert("/db", OK))
        self.assertEqual(tree.history("/db")[-1].reason,
                         ("planned, and a day longer",))

    def test_a_check_that_reports_maintenance_keeps_its_own_words(self):
        # no pin: the status is the check's own reading, and so is its reason
        tree = StatusTree()
        tree.upsert("/pool", OK, "serving")
        tree.upsert("/pool", MAINTENANCE, "draining")
        tree.upsert("/pool", MAINTENANCE, "drained, 0 connections")
        self.assertEqual(tree.history("/pool")[-1].reason,
                         ("drained, 0 connections",))

    def test_another_status_s_rows_read_as_they_did(self):
        tree = StatusTree()
        tree.upsert("/db", OK, "in step")
        tree.upsert("/db", ERROR, "down")
        tree.upsert("/db", OK, "recovered")
        tree.upsert("/db", OK, "in step again")
        ok, error, current = tree.history("/db")
        self.assertEqual((ok.reason, error.reason, current.reason),
                         (("in step",), ("down",), ("in step again",)))


class _Pages(TestCase):
    """A log written at instants a page shows apart, read by the pages."""

    def setUp(self) -> None:
        app_module.app.config["TESTING"] = True
        self._saved = app_module.status_tree
        self.addCleanup(self._restore)
        self.client = app_module.app.test_client()
        self.client.post("/login",
                         data={"username": "pan", "password": "12345678"})

    def _restore(self) -> None:
        app_module.status_tree = self._saved

    def _serve(self, *events: Event, pins: dict[str, str] | None = None,
               write: tuple[str, StatusCode, str] | None = None) -> StatusTree:
        """A tree restarted on ``events``, its ``pins`` replayed, and one node
        written again as it was, so that it has been observed."""
        tree = StatusTree()
        tree.restore_events(events)
        tree.restore_maintenance(
            {path: _pin(note) for path, note in (pins or {}).items()})
        if write is not None:
            path, code, reason = write
            self.assertFalse(tree.upsert(path, code, reason),
                             "the same reading: no event for the restart")
        app_module.status_tree = tree
        return tree

    def _page(self, url: str) -> Element:
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200, url)
        return parse(response.get_data(as_text=True))

    @staticmethod
    def _shown(minutes: int) -> str:
        """An instant as a page writes it."""
        return str(app_module.app.jinja_env.filters["localtime"](_at(minutes)))

    def _period(self, url: str) -> str:
        """The Time card's sentence about the status that holds: a node's own,
        named so on a node above others (ADR-0123 decision 3)."""
        for paragraph in self._page(url).all(tag="p"):
            text = paragraph.text()
            if text.startswith(("Status ", "Its own status ")):
                return text
        self.fail(f"no period on {url}")


class TimeCardTests(_Pages):
    """*Since* on the Time card: of the run, and saying where a pin's end began it."""

    def test_an_edited_pin_holds_since_its_set(self):
        self._serve(_event("/db", UNDEFINED, WARN, 0, "lagging"),
                    _event("/db", WARN, MAINTENANCE, 5, "planed"),
                    _event("/db", MAINTENANCE, MAINTENANCE, 9, "planned"),
                    pins={"/db": "planned"}, write=("/db", WARN, "lagging"))
        self.assertEqual(self._period("/status/db"),
                         f"Status maintenance since {self._shown(5)}")

    def test_a_period_a_pins_end_began_says_so(self):
        self._serve(_event("/db", UNDEFINED, OK, 0, "in step"),
                    _event("/db", OK, MAINTENANCE, 5, "planned"),
                    _event("/db", MAINTENANCE, OK, 9, "in step"),
                    write=("/db", OK, "in step"))
        self.assertEqual(
            self._period("/status/db"),
            f"Status ok since {self._shown(9)}, when its maintenance ended")

    def test_on_a_branch_s_page_too(self):
        self._serve(_event("/hosts/a", UNDEFINED, OK, 0),
                    _event("/hosts/a", OK, MAINTENANCE, 5, "kernel"),
                    _event("/hosts/a", MAINTENANCE, OK, 9),
                    write=("/hosts/a", OK, ""))
        app_module.status_tree.upsert("/hosts/a/cpu", OK, "fine")
        self.assertEqual(
            self._period("/status/hosts/a"),
            f"Its own status ok since {self._shown(9)}, when its maintenance ended")

    def test_a_period_a_reading_began_says_nothing_more(self):
        self._serve(_event("/db", UNDEFINED, OK, 0, "in step"),
                    _event("/db", OK, ERROR, 5, "down"),
                    write=("/db", ERROR, "down"))
        self.assertEqual(self._period("/status/db"),
                         f"Status error since {self._shown(5)}")

    def test_nor_does_the_pin_itself(self):
        # a status that came after maintenance, not maintenance after a status
        self._serve(_event("/db", UNDEFINED, OK, 0, "in step"),
                    _event("/db", OK, MAINTENANCE, 5, "planned"),
                    pins={"/db": "planned"}, write=("/db", OK, "in step"))
        self.assertEqual(self._period("/status/db"),
                         f"Status maintenance since {self._shown(5)}")

    def test_a_pin_whose_set_left_the_log_holds_since_before_its_oldest_edit(self):
        self._serve(_event("/db", MAINTENANCE, MAINTENANCE, 9, "planned"),
                    pins={"/db": "planned"})
        app_module.status_tree.upsert("/db", OK, "in step")
        self.assertEqual(self._period("/status/db"),
                         f"Status maintenance since before {self._shown(9)}")


class CopyTests(_Pages):
    """The Copy document says the same."""

    def test_a_period_a_pins_end_began_says_so(self):
        self._serve(_event("/db", UNDEFINED, WARN, 0, "lagging"),
                    _event("/db", WARN, MAINTENANCE, 5, "planned"),
                    _event("/db", MAINTENANCE, ERROR, 9, "down"),
                    write=("/db", ERROR, "down"))
        style: TimeStyle = app_module._copy_style()
        expected = (f"- **Status error** since {style.at(_at(9))}, when its "
                    f"maintenance ended\n")
        source = self._page("/copy/db").with_id("ls-copy-source").source()
        self.assertIn(expected, source)

    def test_an_edited_pin_holds_since_its_set(self):
        self._serve(_event("/db", UNDEFINED, WARN, 0, "lagging"),
                    _event("/db", WARN, MAINTENANCE, 5, "planed"),
                    _event("/db", MAINTENANCE, MAINTENANCE, 9, "planned"),
                    pins={"/db": "planned"}, write=("/db", WARN, "lagging"))
        style: TimeStyle = app_module._copy_style()
        source = self._page("/copy/db").with_id("ls-copy-source").source()
        self.assertIn(f"- **Status maintenance** since {style.at(_at(5))}\n", source)

    def test_a_pin_whose_set_left_the_log_holds_since_before_its_oldest_edit(self):
        self._serve(_event("/db", MAINTENANCE, MAINTENANCE, 9, "planned"),
                    pins={"/db": "planned"})
        app_module.status_tree.upsert("/db", OK, "in step")
        style: TimeStyle = app_module._copy_style()
        source = self._page("/copy/db").with_id("ls-copy-source").source()
        self.assertIn(f"- **Status maintenance** since before "
                      f"{style.at(_at(9))}\n", source)

    def test_a_node_without_a_period_reports_its_observation(self):
        # nothing to bound: no *since*, and so no word about how it began
        tree = StatusTree()
        tree.upsert("/db", UNDEFINED, "no data")
        app_module.status_tree = tree
        source = self._page("/copy/db").with_id("ls-copy-source").source()
        self.assertIn("- **Observed:** ", source)
        self.assertNotIn("since", source)

    def test_the_formatter_takes_it_as_it_takes_before(self):
        tree = StatusTree()
        tree.upsert("/db", ERROR, "down")
        node = tree.snapshot("/db")
        assert node is not None
        style: TimeStyle = app_module._copy_style()
        plain = format_node_markdown(node, style, _at(9))
        ended = format_node_markdown(node, style, _at(9),
                                     began="when its maintenance ended")
        self.assertIn(f"- **Status error** since {style.at(_at(9))}\n", plain)
        self.assertNotIn("when its maintenance ended", plain)
        self.assertIn(f"- **Status error** since {style.at(_at(9))}, when its "
                      f"maintenance ended\n", ended)


class HistoryPageTests(_Pages):
    """History lists the runs."""

    def _rows(self, url: str) -> list[list[str]]:
        table = self._page(url).all(tag="table")[0]
        return [[cell.text() for cell in row.all(tag="td")]
                for row in table.one(tag="tbody").all(tag="tr")]

    def test_an_edited_pin_is_one_row_with_its_last_note(self):
        self._serve(_event("/db", UNDEFINED, WARN, 0, "lagging"),
                    _event("/db", WARN, MAINTENANCE, 5, "planed"),
                    _event("/db", MAINTENANCE, MAINTENANCE, 9, "planned"),
                    pins={"/db": "planned"}, write=("/db", WARN, "lagging"))
        # the oldest row is the node's first reading, and a bound (decision 9)
        self.assertEqual(self._rows("/history/db"), [
            ["maintenance", self._shown(5), "current", "planned"],
            ["warn", f"before {self._shown(0)}", self._shown(5), "lagging"]])

    def test_a_cleared_pin_is_one_row_between_the_statuses_around_it(self):
        self._serve(_event("/db", UNDEFINED, OK, 0, "in step"),
                    _event("/db", OK, MAINTENANCE, 5, "planed"),
                    _event("/db", MAINTENANCE, MAINTENANCE, 7, "planned"),
                    _event("/db", MAINTENANCE, OK, 9, "in step"),
                    write=("/db", OK, "in step"))
        self.assertEqual(self._rows("/history/db"), [
            ["ok", self._shown(9), "current", "in step"],
            ["maintenance", self._shown(5), self._shown(9), "planned"],
            ["ok", f"before {self._shown(0)}", self._shown(5), "in step"]])

    def test_a_pin_whose_set_left_the_log_began_before_its_oldest_edit(self):
        self._serve(_event("/db", MAINTENANCE, MAINTENANCE, 9, "planned"),
                    pins={"/db": "planned"})
        app_module.status_tree.upsert("/db", OK, "in step")
        self.assertEqual(self._rows("/history/db"), [
            ["maintenance", f"before {self._shown(9)}", "current", "planned"]])

    def test_the_events_page_still_lists_every_edit(self):
        self._serve(_event("/db", UNDEFINED, WARN, 0, "lagging"),
                    _event("/db", WARN, MAINTENANCE, 5, "planed"),
                    _event("/db", MAINTENANCE, MAINTENANCE, 9, "planned"),
                    pins={"/db": "planned"}, write=("/db", WARN, "lagging"))
        table = self._page("/events").all(tag="table")[0]
        rows = [[cell.text() for cell in row.all(tag="td")]
                for row in table.one(tag="tbody").all(tag="tr")]
        self.assertEqual([(row[1], row[3]) for row in rows], [
            ("maintenance", "planned"), ("maintenance", "planed"),
            ("warn", "lagging")])
        self.assertTrue(all(re.fullmatch(r"\d{4}-.*", row[0]) for row in rows))
