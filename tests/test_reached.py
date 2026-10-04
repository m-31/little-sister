"""A wait that ends by its count writes a row (ADR-0119), read against the record's
sentences.

A node that waits before it escalates (ADR-0083) shows a worse status at once and
publishes it to the level above after ``escalate_after`` consecutive readings of it.
The row of that change is written when the node shows it, marked ``damping``. The
reading that completed the count wrote nothing, so the log said of no failure that it
had reached, and the Events page listed one that turned the wall red as held back
(backlog #89's B18).

* The reading that completes a count writes a row: the status the node shows,
  unmarked, by the cause ``reached``. It begins no period and counts as no change.
* Only a wait that ends by its count writes it.
* On the Events page the row says *reached*, and it is a reading's row that reached.
* An entry of the kept table says what a waiting node publishes.

What a restart reads of that entry is in ``tests/test_restart_wait.py``, beside the
rest of what a wait counts from.
"""
from __future__ import annotations

import json
import os
from datetime import UTC, datetime, timedelta
from typing import Any
from unittest import TestCase

os.environ.setdefault("SECRET_KEY", "test-key")

from little_sister import app as app_module
from little_sister import instants
from little_sister import tree as tree_module
from little_sister.event_filter import cause_kind
from little_sister.reasons import Entry
from little_sister.status import StatusCode, worst_of
from little_sister.tree import DAMPING_RULE, DEPENDENCY_RULE, Event, StatusTree
from tests.page_tree import Element, parse

OK, WARN, ERROR = StatusCode.OK, StatusCode.WARN, StatusCode.ERROR
MAINTENANCE, UNDEFINED = StatusCode.MAINTENANCE, StatusCode.UNDEFINED

PATH = "/site/probe"
PARENT = "/site"
GATE = "/site/gate"
NEEDED = 3
#: The cause a row carries that ends a wait by its count, as the kept file writes it.
REACHED = "reached"


def _read(tree: StatusTree, code: StatusCode, *, path: str = PATH,
          needed: int = NEEDED) -> bool:
    """One reading of a node that waits ``needed`` readings before it escalates;
    whether it wrote an event."""
    return tree.upsert(path, code, f"it reads {code.name.lower()}",
                       escalate_after=needed)


def _was(tree: StatusTree, *codes: StatusCode, needed: int = NEEDED) -> StatusTree:
    for code in codes:
        _read(tree, code, needed=needed)
    return tree


def _rows(tree: StatusTree, path: str = PATH) -> list[Event]:
    return [event for event in tree.recent_events() if event.path == path]


def _said(row: Event) -> tuple[StatusCode, StatusCode, str, str]:
    """What a row says: from what to what, which rule held it back, and its cause."""
    return row.old, row.new, row.suppressed_by, row.cause


def _above(tree: StatusTree) -> StatusCode:
    """What the level above the node shows."""
    parent = tree.snapshot(PARENT)
    assert parent is not None
    return parent.code


def _kept(tree: StatusTree) -> dict[str, Any]:
    """What the tree writes to its file, through the file's own shape."""
    kept: dict[str, Any] = json.loads(json.dumps(tree.events_payload()))
    return kept


def _local(stamp: str) -> str:
    """An event's instant as a page writes it."""
    written: str = app_module.app.jinja_env.filters["localtime"](stamp)
    return written


FIRST = (UNDEFINED, OK, "", "reading")
HELD = (OK, ERROR, DAMPING_RULE, "reading")
IT_REACHED = (ERROR, ERROR, "", REACHED)


class RowTests(TestCase):
    """The reading that completes a count writes a row (decision 1)."""

    def test_the_reading_that_completes_the_count_writes_it(self) -> None:
        tree = StatusTree()
        self.assertTrue(_read(tree, OK))
        self.assertTrue(_read(tree, ERROR), "the node shows it at once: held back")
        self.assertEqual((_above(tree), [_said(row) for row in _rows(tree)]),
                         (OK, [FIRST, HELD]))
        self.assertFalse(_read(tree, ERROR), "the second of three writes nothing")
        self.assertEqual((_above(tree), len(_rows(tree))), (OK, 2))
        self.assertTrue(_read(tree, ERROR), "the third completes the count")
        self.assertEqual((_above(tree), [_said(row) for row in _rows(tree)]),
                         (ERROR, [FIRST, HELD, IT_REACHED]))
        self.assertFalse(_read(tree, ERROR), "and no reading after it writes one")
        self.assertEqual(len(_rows(tree)), 3)

    def test_it_is_dated_by_that_reading_and_says_the_nodes_lines(self) -> None:
        tree = _was(StatusTree(), OK, ERROR, ERROR)
        tree.upsert(PATH, ERROR, "it reads error, and worse", escalate_after=NEEDED)
        held, row = _rows(tree)[-2:]
        node = tree.snapshot(PATH)
        assert node is not None
        self.assertEqual(row.timestamp, node.timestamp)
        self.assertGreater(row.timestamp, held.timestamp)
        self.assertEqual(row.reason, ("it reads error, and worse",))
        self.assertIs(row.reported, ERROR)
        self.assertEqual((row.path, row.name), (PATH, "probe"))

    def test_the_held_row_keeps_its_mark(self) -> None:
        tree = _was(StatusTree(), OK, ERROR, ERROR, ERROR)
        self.assertEqual([row.suppressed_by for row in _rows(tree)],
                         ["", DAMPING_RULE, ""])

    def test_it_begins_no_period(self) -> None:
        tree = _was(StatusTree(), OK, ERROR, ERROR, ERROR)
        held = _rows(tree)[1]
        periods = tree.history(PATH)
        self.assertEqual([period.code for period in periods], [OK, ERROR])
        self.assertEqual((periods[-1].since, periods[-1].before),
                         (held.timestamp, False))
        entry = _kept(tree)["nodes"][PATH]
        self.assertEqual((entry["since"], entry["was"], entry["cause"]),
                         (instants.stamp(held.timestamp), "OK", "reading"))

    def test_it_is_no_change_of_what_the_check_reported(self) -> None:
        tree = _was(StatusTree(), OK, ERROR, ERROR, ERROR)
        node = tree.snapshot(PATH)
        assert node is not None
        self.assertEqual(node.changes, 1, "ok to error, once")

    def test_it_says_what_the_node_shows_where_its_check_reports_another(
            self) -> None:
        # A silenced line goes on failing beneath its pin. What waits, and what
        # reaches, is the other line's warning, which is what the node shows
        # (ADR-0108 decision 1).
        tree = StatusTree()

        def run(**codes: StatusCode) -> None:
            lines = [Entry(slug, f"{slug}: {code.name.lower()}", code=code)
                     for slug, code in codes.items()]
            tree.upsert(PATH, worst_of(codes.values()), lines, members=True,
                        escalate_after=NEEDED)

        run(deploy=ERROR, tests=OK)
        tree.set_entry_maintenance(PATH, "deploy", "being reworked", set_by="ada",
                                   expires_at=datetime.now(UTC) + timedelta(hours=1))
        for _ in range(NEEDED):
            run(deploy=ERROR, tests=WARN)
        held, row = _rows(tree)[-2:]
        self.assertEqual(_said(held), (OK, WARN, DAMPING_RULE, "reading"))
        self.assertEqual(_said(row), (WARN, WARN, "", REACHED))
        self.assertIs(row.reported, ERROR)
        self.assertEqual(_above(tree), WARN)

    def test_a_wait_from_a_status_that_had_reached(self) -> None:
        tree = _was(StatusTree(), WARN, ERROR, ERROR)
        self.assertEqual(_above(tree), WARN)
        _read(tree, ERROR)
        self.assertEqual(_above(tree), ERROR)
        self.assertEqual([_said(row) for row in _rows(tree)], [
            (UNDEFINED, WARN, "", "reading"), (WARN, ERROR, DAMPING_RULE, "reading"),
            IT_REACHED])

    def test_a_warning_reaches_as_a_failure_does(self) -> None:
        tree = _was(StatusTree(), OK, WARN, WARN, needed=2)
        self.assertEqual(_said(_rows(tree)[-1]), (WARN, WARN, "", REACHED))
        self.assertEqual(_above(tree), WARN)


class OnlyTheCountTests(TestCase):
    """Only a wait that ends by its count writes it (decision 2)."""

    def test_a_recovery_writes_its_own_row(self) -> None:
        tree = _was(StatusTree(), OK, ERROR, OK, OK, OK)
        self.assertEqual([_said(row) for row in _rows(tree)],
                         [FIRST, HELD, (ERROR, OK, "", "reading")])

    def test_another_status_restarts_the_count_with_its_own_row(self) -> None:
        tree = _was(StatusTree(), OK, WARN, ERROR, ERROR)
        self.assertEqual([_said(row) for row in _rows(tree)], [
            FIRST, (OK, WARN, DAMPING_RULE, "reading"),
            (WARN, ERROR, DAMPING_RULE, "reading")])
        self.assertEqual(_above(tree), OK)
        _read(tree, ERROR)                       # the third reading of error
        self.assertEqual(_said(_rows(tree)[-1]), IT_REACHED)
        self.assertEqual((_above(tree), len(_rows(tree))), (ERROR, 4))

    def test_a_pin_ends_a_wait_with_its_own_row(self) -> None:
        tree = _was(StatusTree(), OK, ERROR)
        soon = datetime.now(UTC) + timedelta(hours=1)
        tree.set_maintenance(PATH, "planned", set_by="ada", expires_at=soon)
        _was(tree, ERROR, ERROR, ERROR)          # beneath the pin
        tree.clear_maintenance(PATH)
        _was(tree, ERROR, ERROR, ERROR)          # what the pin's end uncovered
        self.assertEqual([_said(row) for row in _rows(tree)], [
            FIRST, HELD, (ERROR, MAINTENANCE, "", "pin-set"),
            (MAINTENANCE, ERROR, "", "pin-ended")])
        self.assertEqual(_above(tree), ERROR)

    def test_a_node_that_does_not_wait_writes_none(self) -> None:
        tree = _was(StatusTree(), OK, ERROR, ERROR, ERROR, needed=1)
        self.assertEqual([_said(row) for row in _rows(tree)],
                         [FIRST, (OK, ERROR, "", "reading")])

    def test_a_first_reading_writes_none(self) -> None:
        tree = _was(StatusTree(), ERROR, ERROR, ERROR, ERROR)
        self.assertEqual([_said(row) for row in _rows(tree)],
                         [(UNDEFINED, ERROR, "", "reading")])

    def test_a_wait_made_shorter_ends_at_the_next_reading(self) -> None:
        tree = _was(StatusTree(), OK, ERROR)
        self.assertTrue(_read(tree, ERROR, needed=2))
        self.assertEqual(_said(_rows(tree)[-1]), IT_REACHED)

    def _behind_a_gate(self) -> StatusTree:
        tree = StatusTree()
        tree.set_check_mount(GATE)
        tree.set_check_mount(PATH)
        tree.set_dependency(PATH, GATE)
        tree.upsert(GATE, OK, "up")
        _read(tree, OK)
        tree.upsert(GATE, ERROR, "down")
        return tree

    def test_a_count_that_completes_behind_a_shield_writes_none(self) -> None:
        tree = _was(self._behind_a_gate(), ERROR, ERROR, ERROR, ERROR)
        self.assertEqual([_said(row) for row in _rows(tree)],
                         [FIRST, (OK, ERROR, DEPENDENCY_RULE, "reading")])

    def test_a_count_that_completes_once_the_shield_has_lifted_writes_it(
            self) -> None:
        tree = _was(self._behind_a_gate(), ERROR)        # one reading, shielded
        tree.upsert(GATE, OK, "up")
        self.assertFalse(_read(tree, ERROR))             # the second, held by the wait
        self.assertTrue(_read(tree, ERROR))              # the third completes it
        self.assertEqual([_said(row) for row in _rows(tree)],
                         [FIRST, (OK, ERROR, DEPENDENCY_RULE, "reading"), IT_REACHED])


class KeptTests(TestCase):
    """The kept file says which nodes are waiting (decision 4)."""

    def test_an_entry_says_what_a_waiting_node_publishes(self) -> None:
        tree = _was(StatusTree(), OK, ERROR)
        entry = _kept(tree)["nodes"][PATH]
        self.assertEqual((entry["shows"], entry["reported"], entry["publishes"]),
                         ("ERROR", "ERROR", "OK"))
        _read(tree, ERROR)
        self.assertEqual(_kept(tree)["nodes"][PATH]["publishes"], "OK")
        _read(tree, ERROR)                               # the count is complete
        self.assertNotIn("publishes", _kept(tree)["nodes"][PATH])

    def test_it_is_what_the_node_published_before_and_not_ok(self) -> None:
        tree = _was(StatusTree(), WARN, ERROR)
        self.assertEqual(_kept(tree)["nodes"][PATH]["publishes"], "WARN")

    def test_it_stands_from_the_held_row_to_the_row_that_ends_the_wait(self) -> None:
        soon = datetime.now(UTC) + timedelta(hours=1)
        endings = {
            "a recovery": lambda tree: _read(tree, OK),
            "a pin": lambda tree: tree.set_maintenance(
                PATH, "planned", set_by="ada", expires_at=soon),
            "its count": lambda tree: _was(tree, ERROR, ERROR)}
        for name, end in endings.items():
            with self.subTest(ended_by=name):
                tree = _was(StatusTree(), OK, ERROR)
                rows = len(_rows(tree))
                self.assertIn("publishes", _kept(tree)["nodes"][PATH])
                end(tree)
                self.assertNotIn("publishes", _kept(tree)["nodes"][PATH])
                self.assertEqual(len(_rows(tree)), rows + 1, "a row ended it")

    def test_a_node_that_is_not_waiting_has_no_such_key(self) -> None:
        tree = StatusTree()
        _was(tree, OK, ERROR, needed=1)
        _read(tree, ERROR, path="/site/first")
        _read(tree, OK, path="/site/quiet")
        for path, entry in _kept(tree)["nodes"].items():
            with self.subTest(path=path):
                self.assertNotIn("publishes", entry)

    def test_the_table_is_read_back_with_it(self) -> None:
        kept = tree_module.nodes_from_payload(_kept(_was(StatusTree(), OK, ERROR)))
        assert kept is not None
        self.assertIs(kept[PATH].publishes, OK)
        quiet = tree_module.nodes_from_payload(_kept(_was(StatusTree(), OK)))
        assert quiet is not None
        self.assertIsNone(quiet[PATH].publishes)

    def test_a_key_that_names_no_code_refuses_the_file(self) -> None:
        for said in ("SOMETIMES", "ok", 3, ["OK"], ""):
            entry = {"shows": "ERROR", "reported": "ERROR", "publishes": said}
            with self.subTest(publishes=said), self.assertRaises(ValueError):
                tree_module.nodes_from_payload({"events": [], "nodes": {PATH: entry}})


class _Page(TestCase):
    """The pages of a tree whose one waiting node has reached."""

    def setUp(self) -> None:
        self._saved = app_module.status_tree
        self.addCleanup(self._restore)
        self.tree = _was(StatusTree(), OK, ERROR, ERROR, ERROR)
        app_module.status_tree = self.tree
        self.client = app_module.app.test_client()
        self.client.post("/login", data={"username": "pan", "password": "12345678"})

    def _restore(self) -> None:
        app_module.status_tree = self._saved

    def _get(self, url: str) -> str:
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200, url)
        return response.get_data(as_text=True)

    def _events(self, url: str = "/events") -> list[Element]:
        """The rows of the node on the Events page, newest first."""
        body = parse(self._get(url)).one(tag="tbody")
        return [row for row in body.all(tag="tr")
                if len(row.all(tag="td")) == 4
                and row.all(tag="td")[2].text() == PATH]


class EventsTests(_Page):
    """On the Events page the row says *reached* (decision 3)."""

    def test_the_row_says_reached_in_a_chip_beside_its_status(self) -> None:
        reached, held, first = self._events()
        cell = reached.all(tag="td")[1]
        self.assertEqual(cell.text().split(), ["error", "reached"])
        chip = cell.one("event-cause")
        self.assertEqual(chip.text(), "reached")
        self.assertEqual(cell.all("event-suppressed"), [])
        # and the row before it still says which rule held it back, and no cause
        cell = held.all(tag="td")[1]
        self.assertEqual(cell.text().split(), ["error", DAMPING_RULE])
        self.assertEqual(cell.one("event-suppressed").text(), DAMPING_RULE)
        self.assertEqual(cell.all("event-cause"), [])
        self.assertEqual(first.all(tag="td")[1].text().split(), ["ok"])

    def test_its_chip_wears_the_pair_of_its_status_and_not_a_pins(self) -> None:
        reached = self._events()[0]
        self.assertTrue(reached.has("row-error"))
        chip = reached.one("event-cause")
        self.assertTrue(chip.has("event-cause--reached"))
        self.assertFalse(chip.has("event-cause--removed"))

    def test_it_stands_at_the_reading_that_completed_the_count(self) -> None:
        reached, held, _first = self._events()
        whens = [row.all(tag="td")[0].text() for row in (reached, held)]
        rows = _rows(self.tree)
        self.assertEqual(whens, [_local(rows[2].timestamp), _local(rows[1].timestamp)])
        self.assertNotEqual(rows[2].timestamp, rows[1].timestamp)
        self.assertEqual(reached.all(tag="td")[3].text(), "it reads error")

    def test_reached_lists_it_and_held_back_lists_the_row_before_it(self) -> None:
        def said(url: str) -> list[list[str]]:
            return [row.all(tag="td")[1].text().split() for row in self._events(url)]
        self.assertEqual(said("/events?held=no"), [["error", "reached"], ["ok"]])
        self.assertEqual(said("/events?held=yes"), [["error", DAMPING_RULE]])

    def test_it_is_a_readings_row(self) -> None:
        self.assertEqual(len(self._events("/events?cause=reading")), 3)
        self.assertEqual(self._events("/events?cause=pin"), [])
        self.assertEqual(self._events("/events?cause=removed"), [])
        row = _rows(self.tree)[-1]
        self.assertEqual(row.cause, REACHED)
        self.assertEqual(cause_kind(row), "reading")

    def test_the_error_switch_lists_it_by_the_status_it_shows(self) -> None:
        self.assertEqual(len(self._events("/events?status=error")), 2)
        self.assertEqual(len(self._events("/events?status=ok")), 1)


class PeriodTests(_Page):
    """It begins no period: History and the Time card go on saying since the row the
    node began to show its status with (decision 1)."""

    def test_history_lists_one_period_of_the_failure(self) -> None:
        body = parse(self._get("/history/site/probe")).all(tag="tbody")[0]
        rows = [[cell.text() for cell in row.all(tag="td")]
                for row in body.all(tag="tr")]
        held = _rows(self.tree)[1]
        since = _local(held.timestamp)
        self.assertEqual([(row[0], row[1], row[2]) for row in rows],
                         [("error", since, "current"), ("ok", rows[1][1], since)])

    def test_the_time_card_says_since_the_held_row(self) -> None:
        body = self._get("/status/site/probe")
        card = body.split(">Time</h3>", 1)[1].split("</div>", 1)[0]
        held = _rows(self.tree)[1]
        self.assertIn(f"since {_local(held.timestamp)}", " ".join(card.split()))
        self.assertIn("1 status change in the last hour", " ".join(card.split()))
