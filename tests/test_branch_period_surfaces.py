"""The surfaces that say the period of what a branch shows (ADR-0132 decisions 3, 6
and 7), read against the record's sentences.

* History lists first the periods of what a node above others shows, newest first:
  each one's status, since and until when — *current* for the one that holds — the
  node whose change began it, by its path beneath the node and linked to its own
  History, and what moved it; both empty where the beginning is a bound, or a tick
  found a difference no change explained. The newest fifty stay open, and the rest
  stand in one fold beneath them. Beneath it, the periods of its own status, as
  before (decision 6).
* The Copy document states the period of what the node shows above ***Its own
  status***, with what began it in one clause after the instant, in History's words:
  *begun by a reading of load-fixtures beneath it*, *of its own*, *on it*, and a
  dependency outside the branch by its full path and why it is named. A bound, and a
  difference no change explains, end at the instant (decision 6).
* A period is said only where it is of what the node shows (decision 3). After a
  restart, until the unit that answers for a node beneath a branch has run, and for
  the moment between a reading gone stale and the tick that dates it, the envelope
  carries no ``period``, the Time card says no *since*, History no period that holds
  and the Copy document ***Its own status*** alone; then each says the period from
  where it began, not from the restart or the tick.

The pages are read as trees (`tests/page_tree.py`), on a clock the test moves by
hand.
"""
from __future__ import annotations

import json
import os
from datetime import UTC, datetime, timedelta
from typing import Any
from unittest import TestCase, mock

os.environ.setdefault("SECRET_KEY", "test-key")

from little_sister import app as app_module
from little_sister import instants
from little_sister.reasons import Entry
from little_sister.status import StatusCode
from little_sister.tree import (
    CAUSE_READING,
    Beginning,
    Period,
    StatusTree,
    events_from_payload,
    nodes_from_payload,
)
from tests.page_tree import Element, parse

OK, WARN, ERROR = StatusCode.OK, StatusCode.WARN, StatusCode.ERROR
UNDEFINED = StatusCode.UNDEFINED
TOKEN = "branch-period-token"
JSON = {"Accept": "application/json", "Authorization": f"Bearer {TOKEN}"}
#: What History says beneath the periods of what a node above others shows.
SHOWN = ("The periods of what it shows: what it rolls up to, the nodes beneath it "
         "included.")
#: What it says beneath the periods of its own status.
OWN = ("The periods of its own status: its page heads with what it rolls up to, the "
       "nodes beneath it included.")
#: The one row of a table of periods that lists none.
NONE_RECORDED = ("No status changes recorded.",)


def _shown(instant: datetime) -> str:
    """An instant as a page writes it."""
    return str(app_module.app.jinja_env.filters["localtime"](instant))


def _copied(instant: datetime) -> str:
    """An instant as a Copy document writes it, with its offset."""
    return app_module._copy_style().at(instant)


class _Clock:
    """The clock the tree and the pages read (`instants.now`), moved by hand. It
    starts on the second after the machine's, so a signed-in session stays valid."""

    def __init__(self) -> None:
        self.at = (datetime.now(UTC) + timedelta(seconds=1)).replace(microsecond=0)

    def __call__(self) -> datetime:
        return self.at

    def go(self, seconds: float) -> datetime:
        self.at += timedelta(seconds=seconds)
        return self.at


class _Surfaces(TestCase):
    """A tree the pages and the API read, by a signed-in admin."""

    def setUp(self) -> None:
        saved = (app_module.status_tree, app_module.api_tokens)
        self.addCleanup(self._put_back, saved)
        app_module.app.config["TESTING"] = True
        self.use(StatusTree())
        app_module.api_tokens = {"tester": TOKEN}
        self.client = app_module.app.test_client()
        self.client.post("/login", data={"username": "pan", "password": "12345678"})
        self.clock = _Clock()
        held = mock.patch.object(instants, "now", self.clock)
        held.start()
        self.addCleanup(held.stop)

    @staticmethod
    def _put_back(saved: tuple[StatusTree, dict[str, str]]) -> None:
        app_module.status_tree, app_module.api_tokens = saved

    def use(self, tree: StatusTree) -> None:
        self.tree = tree
        app_module.status_tree = tree

    def restarted(self) -> StatusTree:
        """A new process on what this one kept."""
        payload = json.loads(json.dumps(self.tree.events_payload()))
        new = StatusTree()
        new.restore_events(events_from_payload(payload), nodes_from_payload(payload))
        return new

    def page(self, url: str) -> Element:
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200, url)
        return parse(response.get_data(as_text=True))

    def shown_tables(self, path: str) -> list[Element]:
        """History's tables of the periods of what the node shows: the open one, and
        the one in the fold where there is one."""
        return self.page(f"/history/{path.lstrip('/')}").all(
            "ls-history__shown", tag="table")

    @staticmethod
    def rows(table: Element) -> list[tuple[str, ...]]:
        """A table's rows, cell by cell."""
        return [tuple(cell.text() for cell in row.all(tag="td"))
                for row in table.one(tag="tbody").all(tag="tr")]

    def history(self, path: str) -> list[tuple[str, ...]]:
        """The open rows of History's first table: status, since, until, from and
        what."""
        tables = self.shown_tables(path)
        self.assertTrue(tables, f"History of {path} lists no periods of what it shows")
        return self.rows(tables[0])

    def named(self, path: str) -> list[str | None]:
        """What each open row's *From* links to: its `href`, or ``None``."""
        table = self.shown_tables(path)[0]
        links = []
        for row in table.one(tag="tbody").all(tag="tr"):
            found = row.all(tag="td")[3].all(tag="a")
            links.append(found[0].attrs["href"] if found else None)
        return links

    def envelope(self, path: str) -> dict[str, Any]:
        """The node's entry in the envelope the API answers with."""
        answer = self.client.get(f"/status/{path.lstrip('/')}", headers=JSON)
        self.assertEqual(answer.status_code, 200)
        status: dict[str, Any] = answer.get_json()["status"]
        return status

    def copy(self, path: str) -> list[str]:
        """The node's Copy document, as its page hands it over: its lines."""
        page = self.page(f"/copy/{path.lstrip('/')}")
        return page.one(tag="textarea").source().splitlines()

    def shown_line(self, path: str) -> list[str]:
        """The lines of the node's Copy document that state the period of what it
        shows: *Status …*, never *Its own status …*."""
        return [line for line in self.copy(path) if line.startswith("- **Status ")]

    def time_card(self, path: str) -> list[str]:
        """The sentences of the node's Time card, in the card's order."""
        page = self.page(f"/status/{path.lstrip('/')}?depth=1")
        cards = [card for card in page.all("card-body")
                 if card.all(tag="h3") and card.all(tag="h3")[0].text() == "Time"]
        self.assertEqual(len(cards), 1, f"{len(cards)} Time cards on {path}")
        return [line.text() for line in cards[0].all(tag="p")]


class HistoryListsWhatABranchShowedTests(_Surfaces):
    """Decision 6: History's first table, of the periods of what the node shows."""

    def _shop(self) -> datetime:
        """A branch well of its own above two nodes that are well; when it first
        stood."""
        with self.tree.storing("/shop"):
            self.tree.upsert("/shop", OK, "answers")
            self.tree.upsert("/shop/db", OK, "answers")
            self.tree.upsert("/shop/web", OK, "answers")
        return self.clock.at

    def test_newest_first_each_with_the_node_that_began_it_and_what_moved_it(self):
        first = self._shop()
        broke = self.clock.go(600)
        with self.tree.storing("/shop/db"):
            self.tree.upsert("/shop/db", ERROR, "refuses connections")
        mended = self.clock.go(600)
        with self.tree.storing("/shop/db"):
            self.tree.upsert("/shop/db", OK, "answers")
        self.assertEqual(self.history("/shop"), [
            ("ok", _shown(mended), "current", "db", "a reading"),
            ("error", _shown(broke), _shown(mended), "db", "a reading"),
            # the oldest is a bound at the log's oldest row, and names nothing
            ("ok", f"before {_shown(first)}", _shown(broke), "", ""),
        ])
        self.assertEqual(self.named("/shop"),
                         ["/history/shop/db", "/history/shop/db", None])

    def test_a_node_deeper_down_is_named_by_its_path_beneath_the_node(self):
        self._shop()
        self.tree.upsert("/shop/db/disk", OK, "62 % used")
        full = self.clock.go(60)
        self.tree.upsert("/shop/db/disk", ERROR, "98 % used")
        self.assertEqual(self.history("/shop")[0],
                         ("error", _shown(full), "current", "db/disk", "a reading"))
        self.assertEqual(self.named("/shop")[0], "/history/shop/db/disk")
        self.assertEqual(self.history("/shop/db")[0],
                         ("error", _shown(full), "current", "disk", "a reading"))

    def test_its_own_change_is_itself_and_no_link(self):
        # its own row began the period, and this is its History
        self._shop()
        refused = self.clock.go(60)
        self.tree.upsert("/shop", ERROR, "refuses orders")
        self.assertEqual(self.history("/shop")[0],
                         ("error", _shown(refused), "current", "itself", "a reading"))
        self.assertIsNone(self.named("/shop")[0])

    def test_a_shield_names_the_dependency_by_its_full_path(self):
        # the dependency stands outside the branch (ADR-0084)
        self.tree.set_dependency("/services/cache", "/net/vpn")
        with self.tree.storing("/services"):
            self.tree.upsert("/services/web", OK)
            self.tree.upsert("/services/cache", ERROR, "no route to host")
        self.tree.upsert("/net/vpn", OK)
        shielded = self.clock.go(60)
        with self.tree.storing("/net/vpn"):
            self.tree.upsert("/net/vpn", ERROR, "the tunnel is down")
        self.assertEqual(
            self.history("/services")[0],
            ("ok", _shown(shielded), "current", "/net/vpn", "a reading"))
        self.assertEqual(self.named("/services")[0], "/history/net/vpn")

    def test_a_pin_set_and_a_pin_ended(self):
        self._shop()
        self.tree.upsert("/shop/db", ERROR, "refuses connections")
        pinned = self.clock.go(60)
        self.tree.set_maintenance("/shop/db", "a disk swap",
                                  expires_at=pinned + timedelta(days=1),
                                  set_by="lex")
        shows = self.tree.snapshot("/shop")
        assert shows is not None
        self.assertEqual(self.history("/shop")[0],
                         (shows.code.name.lower(), _shown(pinned), "current", "db",
                          "a pin set"))
        ended = self.clock.go(60)
        self.tree.clear_maintenance("/shop/db")
        self.assertEqual(self.history("/shop")[0],
                         ("error", _shown(ended), "current", "db", "a pin ended"))

    def test_a_line_silenced_and_its_pin_ended(self):
        with self.tree.storing("/b"):
            self.tree.upsert("/b/x", OK)
            self.tree.upsert("/b/y", WARN, [Entry("disk", "disk 91 %", code=WARN)],
                             members=True)
        silenced = self.clock.go(60)
        self.tree.set_entry_maintenance("/b/y", "disk", "cleaning up",
                                        expires_at=silenced + timedelta(days=1),
                                        set_by="lex")
        self.assertEqual(
            self.history("/b")[0],
            ("ok", _shown(silenced), "current", "y", "a line's pin set"))
        ended = self.clock.go(60)
        self.tree.clear_entry_maintenance("/b/y", "disk")
        self.assertEqual(
            self.history("/b")[0],
            ("warn", _shown(ended), "current", "y", "a line's pin ended"))

    def test_a_removal_names_a_node_the_tree_no_longer_holds_and_no_link(self):
        # as the Events page links only a node that stands
        with self.tree.storing("/r"):
            self.tree.upsert("/r/a", ERROR, "down")
            self.tree.upsert("/r/b", OK)
        run = self.clock.go(60)
        with self.tree.storing("/r"):
            self.tree.upsert("/r/b", OK)
            self.tree.prune("/r", {"b"})
        self.assertEqual(self.history("/r")[0],
                         ("ok", _shown(run), "current", "a", "a removal"))
        self.assertIsNone(self.named("/r")[0])

    def test_a_difference_no_change_explains_names_nothing(self):
        with self.tree.storing("/b"):
            self.tree.upsert("/b/a", OK)
        # what a missed change leaves behind: a period that is not what the tree
        # rolls up to, which the next tick puts right from that tick
        self.tree._periods["/b"] = Period(
            WARN, Beginning(self.clock.at, was=OK, cause=CAUSE_READING), by="/b/a")
        tick = self.clock.go(5)
        with self.assertLogs("little_sister.logger", level="WARNING"):
            self.tree.compare_periods()
        self.assertEqual(self.history("/b")[0],
                         ("ok", _shown(tick), "current", "", ""))

    def _turns(self, times: int) -> None:
        """A node beneath ``/f`` that turns red and back ``times`` times, a minute
        apart: ``times`` periods of what ``/f`` shows after its first."""
        self.tree.upsert("/f/x", OK)
        for index in range(times):
            self.clock.go(60)
            self.tree.upsert("/f/x", ERROR if index % 2 == 0 else OK,
                             f"turn {index}")

    def test_the_newest_fifty_stay_open_and_the_rest_stand_in_one_fold(self):
        self._turns(59)
        page = self.page("/history/f")
        opened, folded = page.all("ls-history__shown", tag="table")
        fold = page.one("ls-history__earlier", tag="details")
        self.assertNotIn("open", fold.attrs)
        self.assertEqual(fold.one(tag="summary").text(), "10 earlier periods")
        self.assertTrue(folded.within(fold))
        self.assertFalse(opened.within(fold))
        newest, oldest = self.rows(opened), self.rows(folded)
        self.assertEqual((len(newest), len(oldest)), (50, 10))
        self.assertEqual(newest[0][2], "current")
        # newest first through both, the fold ending on the bound
        self.assertEqual(oldest[0][2], newest[-1][1])
        self.assertTrue(oldest[-1][1].startswith("before "), oldest[-1])

    def test_one_period_past_fifty_is_one_earlier_period(self):
        self._turns(50)
        page = self.page("/history/f")
        self.assertEqual(
            page.one("ls-history__earlier", tag="details").one(tag="summary").text(),
            "1 earlier period")

    def test_fifty_periods_have_no_fold(self):
        self._turns(49)
        page = self.page("/history/f")
        self.assertEqual(page.all("ls-history__earlier"), [])
        self.assertEqual(len(self.rows(page.one("ls-history__shown", tag="table"))),
                         50)

    def test_beneath_them_the_periods_of_its_own_status_as_before(self):
        first = self._shop()
        page = self.page("/history/shop")
        shown = page.one("ls-history__shown", tag="table")
        own = page.one("ls-history__own", tag="table")
        notes = page.all("text-muted", tag="p")
        self.assertEqual([note.text() for note in notes], [SHOWN, OWN])
        self.assertEqual(
            [element.order for element in (shown, notes[0], own, notes[1])],
            sorted(element.order for element in (shown, notes[0], own, notes[1])))
        self.assertEqual(self.rows(own),
                         [("ok", f"before {_shown(first)}", "current", "answers")])

    def test_a_node_that_declares_nothing_lists_what_it_shows(self):
        self.tree.upsert("/host/disk", OK, "62 % used")
        full = self.clock.go(60)
        self.tree.upsert("/host/disk", ERROR, "98 % used")
        self.assertEqual(self.history("/host")[0],
                         ("error", _shown(full), "current", "disk", "a reading"))
        own = self.page("/history/host").one("ls-history__own", tag="table")
        self.assertEqual(self.rows(own), [(
            "Declares nothing of its own: its page heads with what its children roll "
            "up to.",)])

    def test_a_node_with_nothing_beneath_it_has_one_table(self):
        self._shop()
        page = self.page("/history/shop/db")
        self.assertEqual(page.all("ls-history__shown"), [])
        self.assertEqual(len(page.all("ls-history__own", tag="table")), 1)
        self.assertNotIn(SHOWN, [note.text() for note in page.all("text-muted",
                                                                   tag="p")])


class TheCopyDocumentSaysWhatBeganItTests(_Surfaces):
    """Decision 6: the Copy document's line for the period of what the node shows,
    and the clause after its instant."""

    def _shop(self) -> datetime:
        """A branch well of its own above two nodes that are well; when it first
        stood."""
        with self.tree.storing("/shop"):
            self.tree.upsert("/shop", OK, "answers")
            self.tree.upsert("/shop/db", OK, "answers")
            self.tree.upsert("/shop/web", OK, "answers")
        return self.clock.at

    def test_the_line_stands_above_its_own_status(self):
        self._shop()
        broke = self.clock.go(60)
        self.tree.upsert("/shop/db", ERROR, "refuses connections")
        document = self.copy("/shop")
        line = (f"- **Status error** since {_copied(broke)}, begun by a reading of "
                "db beneath it")
        own = [index for index, said in enumerate(document)
               if said.startswith("- **Its own status ok** since ")]
        self.assertEqual(own, [document.index(line) + 1])

    def test_a_node_deeper_down_is_named_by_its_path_beneath_it(self):
        self._shop()
        self.tree.upsert("/shop/db/disk", OK, "62 % used")
        full = self.clock.go(60)
        self.tree.upsert("/shop/db/disk", ERROR, "98 % used")
        self.assertEqual(self.shown_line("/shop"), [
            f"- **Status error** since {_copied(full)}, begun by a reading of "
            "db/disk beneath it"])

    def test_its_own_change_is_a_reading_of_its_own(self):
        self._shop()
        refused = self.clock.go(60)
        self.tree.upsert("/shop", ERROR, "refuses orders")
        self.assertEqual(self.shown_line("/shop"), [
            f"- **Status error** since {_copied(refused)}, begun by a reading of "
            "its own"])

    def test_a_pin_ended_on_it(self):
        # its own pin cancelled what was beneath it, and its period was its own;
        # the pin's end begins the period of what it shows
        self._shop()
        self.tree.upsert("/shop/db", ERROR, "refuses connections")
        self.tree.set_maintenance("/shop", "a move", set_by="lex",
                                  expires_at=self.clock.at + timedelta(days=1))
        self.assertEqual(self.shown_line("/shop")[0][:26],
                         "- **Status maintenance** s")
        ended = self.clock.go(60)
        self.tree.clear_maintenance("/shop")
        self.assertEqual(self.shown_line("/shop"), [
            f"- **Status error** since {_copied(ended)}, begun by a pin ended on "
            "it"])

    def test_a_pin_set_and_ended_beneath_it(self):
        self._shop()
        self.tree.upsert("/shop/db", ERROR, "refuses connections")
        pinned = self.clock.go(60)
        self.tree.set_maintenance("/shop/db", "a disk swap", set_by="lex",
                                  expires_at=pinned + timedelta(days=1))
        shows = self.tree.snapshot("/shop")
        assert shows is not None
        self.assertEqual(self.shown_line("/shop"), [
            f"- **Status {shows.code.name.lower()}** since {_copied(pinned)}, begun "
            "by a pin set on db beneath it"])
        ended = self.clock.go(60)
        self.tree.clear_maintenance("/shop/db")
        self.assertEqual(self.shown_line("/shop"), [
            f"- **Status error** since {_copied(ended)}, begun by a pin ended on db "
            "beneath it"])

    def test_its_own_reading_gone_stale(self):
        # a check that stopped running: its own node is the first in the tree's
        # order that now counts the warning for itself
        with self.tree.storing("/s"):
            self.tree.upsert("/s", OK, "answers", stale_after=300.0)
            self.tree.upsert("/s/a", OK)
        went = self.clock.at + timedelta(seconds=300)
        self.clock.go(400)
        self.tree.compare_periods()
        self.assertEqual(self.shown_line("/s"), [
            f"- **Status warn** since {_copied(went)}, begun by its own reading "
            "going stale"])
        self.assertEqual(self.history("/s")[0],
                         ("warn", _shown(went), "current", "itself", "gone stale"))

    def test_a_line_silenced_and_its_pin_ended(self):
        with self.tree.storing("/b"):
            self.tree.upsert("/b/x", OK)
            self.tree.upsert("/b/y", WARN, [Entry("disk", "disk 91 %", code=WARN)],
                             members=True)
        silenced = self.clock.go(60)
        self.tree.set_entry_maintenance("/b/y", "disk", "cleaning up",
                                        expires_at=silenced + timedelta(days=1),
                                        set_by="lex")
        self.assertEqual(self.shown_line("/b"), [
            f"- **Status ok** since {_copied(silenced)}, begun by a line's pin set on "
            "y beneath it"])
        ended = self.clock.go(60)
        self.tree.clear_entry_maintenance("/b/y", "disk")
        self.assertEqual(self.shown_line("/b"), [
            f"- **Status warn** since {_copied(ended)}, begun by a line's pin ended "
            "on y beneath it"])

    def test_a_line_of_its_own_silenced_is_on_it(self):
        with self.tree.storing("/b"):
            self.tree.upsert("/b", WARN, [Entry("scope", "1 of 2 read", code=WARN)],
                             members=True)
            self.tree.upsert("/b/x", OK)
        silenced = self.clock.go(60)
        self.tree.set_entry_maintenance("/b", "scope", "known",
                                        expires_at=silenced + timedelta(days=1),
                                        set_by="lex")
        self.assertEqual(self.shown_line("/b"), [
            f"- **Status ok** since {_copied(silenced)}, begun by a line's pin set on "
            "it"])

    def test_a_removal(self):
        with self.tree.storing("/r"):
            self.tree.upsert("/r/a", ERROR, "down")
            self.tree.upsert("/r/b", OK)
        run = self.clock.go(60)
        with self.tree.storing("/r"):
            self.tree.upsert("/r/b", OK)
            self.tree.prune("/r", {"b"})
        self.assertEqual(self.shown_line("/r"), [
            f"- **Status ok** since {_copied(run)}, begun by the removal of a "
            "beneath it"])

    def test_a_dependency_outside_the_branch_says_why_it_is_named(self):
        self.tree.set_dependency("/services/cache", "/net/vpn")
        with self.tree.storing("/services"):
            self.tree.upsert("/services/web", OK)
            self.tree.upsert("/services/cache", ERROR, "no route to host")
        self.tree.upsert("/net/vpn", OK)
        shielded = self.clock.go(60)
        with self.tree.storing("/net/vpn"):
            self.tree.upsert("/net/vpn", ERROR, "the tunnel is down")
        self.assertEqual(self.shown_line("/services"), [
            f"- **Status ok** since {_copied(shielded)}, begun by a reading of "
            "/net/vpn, which a node beneath it is reached through"])

    def test_a_bound_ends_at_the_instant(self):
        first = self._shop()
        self.assertEqual(self.shown_line("/shop"),
                         [f"- **Status ok** since before {_copied(first)}"])

    def test_a_difference_no_change_explains_ends_at_the_instant(self):
        with self.tree.storing("/b"):
            self.tree.upsert("/b", OK, "answers")
            self.tree.upsert("/b/a", OK)
        self.tree._periods["/b"] = Period(
            WARN, Beginning(self.clock.at, was=OK, cause=CAUSE_READING), by="/b/a")
        tick = self.clock.go(5)
        with self.assertLogs("little_sister.logger", level="WARNING"):
            self.tree.compare_periods()
        self.assertEqual(self.shown_line("/b"),
                         [f"- **Status ok** since {_copied(tick)}"])

    def test_a_node_that_declares_nothing_has_it_above_its_observation(self):
        self.tree.upsert("/host", UNDEFINED, "3 disks")
        self.tree.upsert("/host/disk", OK, "62 % used")
        full = self.clock.go(60)
        self.tree.upsert("/host/disk", ERROR, "98 % used")
        document = self.copy("/host")
        line = (f"- **Status error** since {_copied(full)}, begun by a reading of "
                "disk beneath it")
        self.assertEqual(document[document.index(line) + 1][:16], "- **Observed:** ")
        self.assertEqual([said for said in document if "own status" in said], [])

    def test_one_nothing_has_written_is_observed_never_and_says_its_period(self):
        # a container that is no node of a check's: *Not yet observed* is for a
        # node with neither an observation nor a period (ADR-0115 decision 6)
        self.tree.upsert("/rack/fan", OK, "spins")
        full = self.clock.go(60)
        self.tree.upsert("/rack/fan", ERROR, "stopped")
        document = self.copy("/rack")
        self.assertIn(f"- **Status error** since {_copied(full)}, begun by a reading "
                      "of fan beneath it", document)
        self.assertNotIn("- **Not yet observed.**", document)

    def test_a_pinned_branch_keeps_the_one_line_it_had(self):
        self._shop()
        pinned = self.clock.go(60)
        self.tree.set_maintenance("/shop", "a move", set_by="lex",
                                  expires_at=pinned + timedelta(days=1))
        self.assertEqual(self.shown_line("/shop"),
                         [f"- **Status maintenance** since {_copied(pinned)}"])

    def test_a_leaf_has_its_one_period(self):
        self._shop()
        self.assertEqual(len(self.shown_line("/shop/db")), 1)
        self.assertNotIn("begun by", "\n".join(self.copy("/shop/db")))


class APeriodIsSaidOfWhatTheNodeShowsTests(_Surfaces):
    """Decision 3: no surface says a period that is not of what the node shows."""

    def test_after_a_restart_a_node_its_unit_has_not_run_for_keeps_it_unsaid(self):
        # a branch red from its slow unit's node: after a restart the fast unit
        # runs first, and the branch shows ok while its period, which goes on from
        # the slow node's entry, is error
        with self.tree.storing("/b"):
            self.tree.upsert("/b", OK, "two units")
            self.tree.upsert("/b/fast", OK, "read")
            self.tree.upsert("/b/slow", OK, "read")
        first = self.clock.at
        broke = self.clock.go(60)
        with self.tree.storing("/b/slow"):
            self.tree.upsert("/b/slow", ERROR, "refuses to answer")
        self.clock.go(3600)
        self.use(self.restarted())
        self.clock.go(60)
        with self.tree.storing("/b/fast"):
            self.tree.upsert("/b", OK, "two units")
            self.tree.upsert("/b/fast", OK, "read")
        period = self.tree.period("/b")
        assert period is not None
        self.assertEqual((period.code, period.began.at), (ERROR, broke))
        status = self.envelope("/b")
        self.assertEqual(status["code"], "OK")
        self.assertNotIn("period", status)
        self.assertEqual(self.time_card("/b")[0], "Status ok")
        # History lists the periods that ended, and none that holds
        self.assertEqual(self.history("/b"),
                         [("ok", f"before {_shown(first)}", _shown(broke), "", "")])
        # and the Copy document its own status alone
        self.assertEqual(self.shown_line("/b"), [])
        self.assertTrue([line for line in self.copy("/b")
                         if line.startswith("- **Its own status ok** since ")])
        # once the slow unit has run and the branch shows error: from where it began
        self.clock.go(60)
        with self.tree.storing("/b/slow"):
            self.tree.upsert("/b/slow", ERROR, "refuses to answer")
        status = self.envelope("/b")
        self.assertEqual(status["code"], "ERROR")
        self.assertEqual(status["period"],
                         {"since": instants.stamp(broke), "was": "OK",
                          "cause": "reading", "by": "/b/slow"})
        self.assertEqual(self.time_card("/b")[0],
                         f"Status error since {_shown(broke)}, from slow beneath it")
        self.assertEqual(self.history("/b"), [
            ("error", _shown(broke), "current", "slow", "a reading"),
            ("ok", f"before {_shown(first)}", _shown(broke), "", ""),
        ])
        self.assertEqual(self.shown_line("/b"), [
            f"- **Status error** since {_copied(broke)}, begun by a reading of slow "
            "beneath it"])

    def test_a_reading_gone_stale_between_ticks_is_said_once_the_tick_dates_it(self):
        with self.tree.storing("/s"):
            self.tree.upsert("/s", OK, "answers")
            self.tree.upsert("/s/a", OK, "read", stale_after=300.0)
            self.tree.upsert("/s/b", OK, "read")
        first = self.clock.at
        went = first + timedelta(seconds=300)
        self.clock.go(400)
        status = self.envelope("/s")
        self.assertEqual(status["code"], "WARN")
        self.assertNotIn("period", status)
        self.assertEqual(
            self.time_card("/s")[0],
            f"Status warn, from a beneath it, stale, last observed {_shown(first)}")
        self.assertEqual(self.history("/s"), [NONE_RECORDED])
        self.assertEqual(self.shown_line("/s"), [])
        self.tree.compare_periods()
        status = self.envelope("/s")
        self.assertEqual(status["period"],
                         {"since": instants.stamp(went), "was": "OK",
                          "cause": "stale", "by": "/s/a"})
        self.assertEqual(
            self.time_card("/s")[0],
            f"Status warn since {_shown(went)}, from a beneath it, stale, last "
            f"observed {_shown(first)}")
        self.assertEqual(self.history("/s"), [
            ("warn", _shown(went), "current", "a", "gone stale"),
            ("ok", f"before {_shown(first)}", _shown(went), "", ""),
        ])
        self.assertEqual(self.shown_line("/s"), [
            f"- **Status warn** since {_copied(went)}, begun by a beneath it going "
            "stale"])
