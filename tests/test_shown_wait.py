"""The wait before an escalation counts what a node shows (ADR-0108).

A node may wait before it escalates (ADR-0083), and its counter counted the code the
check reported. With a line pinned that is not what the node shows, so the counter
counted readings the node did not show (backlog #89's B16):

* A pinned line that failed spent the wait beneath its pin — the node green, its card
  saying *1 of 3 to escalate* — and the first failure of an unpinned line then reached
  the parent at once.
* A pinned line that flapped restarted the count at every reading, so a failure the
  node showed never reached its parent.

The counter counts the node's own status, and a change of it that a pin made is
published at once: only a reading starts a wait.
"""
from __future__ import annotations

import os
from datetime import UTC, datetime, timedelta
from unittest import TestCase

os.environ.setdefault("SECRET_KEY", "test-key")

from little_sister import app as app_module
from little_sister.reasons import Entry
from little_sister.status import StatusCode, worst_of
from little_sister.tree import Event, StatusSnapshot, StatusTree
from tests.page_tree import Element, parse

OK, WARN, ERROR = StatusCode.OK, StatusCode.WARN, StatusCode.ERROR
MAINTENANCE = StatusCode.MAINTENANCE

PATH = "/ci/actions"
PARENT = "/ci"
TOKEN = "secret-token"
JSON = {"Accept": "application/json", "Authorization": f"Bearer {TOKEN}"}
_SOON = timedelta(hours=1)


def _write(tree: StatusTree, needed: int = 3, **codes: StatusCode) -> None:
    """One run of a check whose lines carry codes: the lines, and the worst of them as
    the node's — what the engine stores for such a node (ADR-0042) — on a node that
    waits ``needed`` readings before it escalates."""
    lines = [Entry(slug, f"{slug}: {code.name.lower()}", code=code)
             for slug, code in codes.items()]
    tree.upsert(PATH, worst_of(codes.values()), lines, members=True,
                escalate_after=needed)


def _pin(tree: StatusTree, slug: str, lasts: timedelta = _SOON) -> None:
    written = tree.set_entry_maintenance(
        PATH, slug, "being reworked", expires_at=datetime.now(UTC) + lasts,
        set_by="ada")
    assert written.applied


def _node(tree: StatusTree) -> StatusSnapshot:
    node = tree.snapshot(PATH)
    assert node is not None
    return node


def _hold(tree: StatusTree) -> tuple[StatusCode, int] | None:
    """The hold the node states: the status it waits to publish, and how many
    readings of it are in."""
    held = _node(tree).damping
    return None if held is None else (held.pending, held.seen)


def _above(tree: StatusTree) -> StatusCode:
    """What the level above the node shows."""
    parent = tree.snapshot(PARENT)
    assert parent is not None
    return parent.code


def _last(tree: StatusTree) -> Event:
    return [event for event in tree.recent_events() if event.path == PATH][-1]


class CountTests(TestCase):
    """The counter counts what the node shows, whatever its pinned lines do."""

    def setUp(self) -> None:
        self.tree = StatusTree()
        _write(self.tree, deploy=OK, tests=OK)

    def test_a_pinned_line_s_failure_spends_no_wait(self):
        _pin(self.tree, "deploy")
        for _ in range(3):
            _write(self.tree, deploy=ERROR, tests=OK)
        _write(self.tree, deploy=ERROR, tests=ERROR)    # the other line's first
        self.assertEqual((_hold(self.tree), _node(self.tree).counted),
                         ((ERROR, 1), OK))
        self.assertIs(_above(self.tree), OK)
        _write(self.tree, deploy=ERROR, tests=ERROR)
        self.assertEqual((_hold(self.tree), _above(self.tree)), ((ERROR, 2), OK))
        _write(self.tree, deploy=ERROR, tests=ERROR)
        self.assertEqual((_hold(self.tree), _above(self.tree)), (None, ERROR))

    def test_it_states_no_hold_over_a_status_it_does_not_show(self):
        _pin(self.tree, "deploy")
        _write(self.tree, deploy=ERROR, tests=OK)
        node = _node(self.tree)
        self.assertIs(node.own_code, OK)
        self.assertIsNone(node.damping)
        self.assertIsNone(node.contribution)

    def test_a_pinned_line_that_flaps_restarts_nothing(self):
        # reported: error, warn, error — a different worse code at every reading;
        # shown: warn, warn, warn
        _pin(self.tree, "deploy")
        _write(self.tree, deploy=ERROR, tests=WARN)
        self.assertEqual(_hold(self.tree), (WARN, 1))
        _write(self.tree, deploy=OK, tests=WARN)
        self.assertEqual((_hold(self.tree), _above(self.tree)), ((WARN, 2), OK))
        _write(self.tree, deploy=ERROR, tests=WARN)
        self.assertEqual((_hold(self.tree), _above(self.tree)), (None, WARN))

    def test_what_it_publishes_after_its_wait_is_what_it_shows(self):
        # warn for three readings beside a pinned line that is red: what the level
        # above then counts is the warn, and an error after it waits from there
        _pin(self.tree, "deploy")
        for _ in range(3):
            _write(self.tree, deploy=ERROR, tests=WARN)
        self.assertEqual((_hold(self.tree), _above(self.tree)), (None, WARN))
        _write(self.tree, deploy=ERROR, tests=ERROR)
        contribution = _node(self.tree).contribution
        assert contribution is not None
        self.assertEqual((_hold(self.tree), contribution.code), ((ERROR, 1), WARN))

    def test_a_different_worse_status_restarts_it_beside_a_pinned_failure(self):
        # reported: error throughout; shown: warn, then error — another claim
        _pin(self.tree, "deploy")
        _write(self.tree, deploy=ERROR, tests=WARN)
        _write(self.tree, deploy=ERROR, tests=ERROR)
        self.assertEqual(_hold(self.tree), (ERROR, 1))
        _write(self.tree, deploy=ERROR, tests=ERROR)
        self.assertEqual((_hold(self.tree), _above(self.tree)), ((ERROR, 2), OK))

    def test_a_recovery_of_what_it_shows_is_immediate(self):
        _pin(self.tree, "deploy")
        _write(self.tree, deploy=ERROR, tests=ERROR)
        self.assertEqual(_hold(self.tree), (ERROR, 1))
        _write(self.tree, deploy=ERROR, tests=OK)   # the pinned line stays red
        self.assertEqual((_hold(self.tree), _above(self.tree)), (None, OK))
        _write(self.tree, deploy=ERROR, tests=ERROR)
        self.assertEqual(_hold(self.tree), (ERROR, 1), "the count starts over")

    def test_what_it_holds_back_is_what_it_published_of_what_it_showed(self):
        # warn, shown and published; then error beside a pinned line: the level
        # above keeps counting warn while the node waits
        _write(self.tree, needed=2, deploy=OK, tests=WARN)
        _write(self.tree, needed=2, deploy=OK, tests=WARN)
        _pin(self.tree, "deploy")
        _write(self.tree, needed=2, deploy=ERROR, tests=ERROR)
        contribution = _node(self.tree).contribution
        assert contribution is not None
        self.assertEqual((contribution.code, contribution.by), (WARN, "damping"))

    def test_with_every_line_pinned_it_holds_nothing(self):
        _pin(self.tree, "deploy")
        _pin(self.tree, "tests")
        _write(self.tree, deploy=ERROR, tests=ERROR)
        node = _node(self.tree)
        self.assertIs(node.own_code, MAINTENANCE)
        self.assertIsNone(node.damping)
        assert node.contribution is not None
        self.assertEqual(node.contribution.by, "maintenance")

    def test_beneath_a_node_s_pin_it_holds_nothing(self):
        self.tree.set_maintenance(PATH, "planned",
                                  expires_at=datetime.now(UTC) + _SOON)
        _write(self.tree, deploy=ERROR, tests=OK)
        node = _node(self.tree)
        self.assertIs(node.own_code, MAINTENANCE)
        self.assertIsNone(node.damping)

    def test_without_a_pin_it_counts_as_it_did(self):
        _write(self.tree, deploy=ERROR, tests=OK)
        self.assertEqual((_hold(self.tree), _above(self.tree)), ((ERROR, 1), OK))
        _write(self.tree, deploy=ERROR, tests=OK)
        _write(self.tree, deploy=ERROR, tests=OK)
        self.assertEqual((_hold(self.tree), _above(self.tree)), (None, ERROR))

    def test_a_node_that_does_not_wait_publishes_at_once_beside_a_pinned_line(self):
        # `escalate_after: 1`, which is what every deployment has until it asks
        tree = StatusTree()
        _write(tree, needed=1, deploy=OK, tests=OK)
        _pin(tree, "deploy")
        _write(tree, needed=1, deploy=ERROR, tests=ERROR)
        self.assertEqual((_hold(tree), _above(tree)), (None, ERROR))

    def test_a_reading_s_row_says_that_its_node_waits(self):
        # the node's own turn, beside a pinned line that has been red for long
        _pin(self.tree, "deploy")
        for _ in range(3):
            _write(self.tree, deploy=ERROR, tests=OK)
        _write(self.tree, deploy=ERROR, tests=ERROR)
        event = _last(self.tree)
        self.assertEqual((event.old, event.new, event.cause, event.suppressed_by),
                         (OK, ERROR, "reading", "damping"))


class PinTests(TestCase):
    """A change of what a node shows that a pin made is published at once."""

    def setUp(self) -> None:
        self.tree = StatusTree()
        _write(self.tree, deploy=OK, tests=OK)

    def _published(self, code: StatusCode) -> None:
        """The node shows ``code``, holds nothing back, and the level above counts
        it — now, and after the next reading of the same."""
        node = _node(self.tree)
        self.assertEqual((node.own_code, node.damping, node.counted),
                         (code, None, code))
        self.assertIs(_above(self.tree), code)

    def test_the_end_of_a_line_s_pin_is_published_at_once(self):
        _pin(self.tree, "deploy")
        _write(self.tree, deploy=ERROR, tests=OK)   # red for one reading beneath it
        self.tree.clear_entry_maintenance(PATH, "deploy")
        self._published(ERROR)

    def test_the_readings_after_it_start_no_wait(self):
        _pin(self.tree, "deploy")
        _write(self.tree, deploy=ERROR, tests=OK)
        self.tree.clear_entry_maintenance(PATH, "deploy")
        _write(self.tree, deploy=ERROR, tests=OK)
        self._published(ERROR)

    def test_an_older_failure_s_is_published_as_it_was(self):
        _pin(self.tree, "deploy")
        for _ in range(5):
            _write(self.tree, deploy=ERROR, tests=OK)
        self.tree.clear_entry_maintenance(PATH, "deploy")
        self._published(ERROR)
        _write(self.tree, deploy=ERROR, tests=OK)
        self._published(ERROR)

    def test_a_line_s_pin_that_runs_out_is_published_at_once(self):
        _pin(self.tree, "deploy", lasts=timedelta(minutes=1))
        _write(self.tree, deploy=ERROR, tests=OK)
        self.tree.sweep_expired(datetime.now(UTC) + timedelta(minutes=5))
        _write(self.tree, deploy=ERROR, tests=OK)
        self._published(ERROR)

    def test_an_adopted_table_without_the_pin_is_published_at_once(self):
        _pin(self.tree, "deploy")
        _write(self.tree, deploy=ERROR, tests=OK)
        self.tree.adopt_maintenance({}, {})
        _write(self.tree, deploy=ERROR, tests=OK)
        self._published(ERROR)

    def test_the_end_of_a_node_s_pin_is_published_at_once(self):
        self.tree.set_maintenance(PATH, "planned",
                                  expires_at=datetime.now(UTC) + _SOON)
        _write(self.tree, deploy=ERROR, tests=OK)   # red for one reading beneath it
        self.tree.clear_maintenance(PATH)
        self._published(ERROR)
        _write(self.tree, deploy=ERROR, tests=OK)
        self._published(ERROR)

    def test_a_node_s_pin_set_and_ended_within_a_wait_ends_the_wait(self):
        _write(self.tree, deploy=ERROR, tests=OK)
        self.assertEqual(_hold(self.tree), (ERROR, 1))
        self.tree.set_maintenance(PATH, "planned",
                                  expires_at=datetime.now(UTC) + _SOON)
        self.tree.clear_maintenance(PATH)           # no reading between the two
        self._published(ERROR)

    def test_a_line_s_pin_takes_the_wait_with_the_failure_it_silences(self):
        _write(self.tree, deploy=ERROR, tests=OK)
        self.assertEqual(_hold(self.tree), (ERROR, 1))
        _pin(self.tree, "deploy")
        self._published(OK)                         # before any reading says so
        _write(self.tree, deploy=ERROR, tests=OK)
        self._published(OK)

    def test_what_a_pin_s_end_published_is_what_the_next_wait_holds(self):
        # two lines pinned, one red and one amber: the amber one's pin ends, and
        # what is published is the warn the node shows — not the error its check
        # reports. An error read after it waits, the level above counting the warn
        _pin(self.tree, "deploy")
        _pin(self.tree, "gate")
        _write(self.tree, deploy=ERROR, gate=WARN, tests=OK)
        self.tree.clear_entry_maintenance(PATH, "gate")
        self._published(WARN)
        _write(self.tree, deploy=ERROR, gate=WARN, tests=ERROR)
        node = _node(self.tree)
        assert node.contribution is not None
        self.assertEqual((_hold(self.tree), node.contribution.code),
                         ((ERROR, 1), WARN))

    def test_a_pin_that_changes_nothing_it_shows_leaves_a_wait_as_it_is(self):
        # two lines red, one of them pinned: the other's failure is being counted,
        # and un-pinning the first changes nothing the node shows
        _pin(self.tree, "deploy")
        _write(self.tree, deploy=ERROR, tests=ERROR)
        self.tree.clear_entry_maintenance(PATH, "deploy")
        self.assertEqual((_hold(self.tree), _above(self.tree)), ((ERROR, 1), OK))
        _write(self.tree, deploy=ERROR, tests=ERROR)
        self.assertEqual((_hold(self.tree), _above(self.tree)), ((ERROR, 2), OK))

    def test_a_pin_s_row_is_not_one_that_waits(self):
        _pin(self.tree, "deploy")
        _write(self.tree, deploy=ERROR, tests=OK)
        self.tree.clear_entry_maintenance(PATH, "deploy")
        event = _last(self.tree)
        self.assertEqual((event.old, event.new, event.cause, event.suppressed_by),
                         (OK, ERROR, "line-pin-ended", ""))


class PageTests(TestCase):
    """The hold a node states is about the status it shows."""

    def setUp(self) -> None:
        app_module.app.config["TESTING"] = True
        self._saved = app_module.status_tree
        self.addCleanup(self._restore)
        self.client = app_module.app.test_client()
        self.client.post("/login",
                         data={"username": "pan", "password": "12345678"})
        self.tree = StatusTree()
        app_module.status_tree = self.tree
        _write(self.tree, deploy=OK, tests=OK)
        _pin(self.tree, "deploy")

    def _restore(self) -> None:
        app_module.status_tree = self._saved

    def _page(self, url: str) -> Element:
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200, url)
        return parse(response.get_data(as_text=True))

    def _card_says(self) -> list[str]:
        """What the node's card on its branch's page says beside its status."""
        return [mark.text() for mark in
                self._page("/status" + PARENT).all("status-reported")]

    def _page_says(self) -> list[str]:
        """The sentences about a wait on the node's own page."""
        return [note.text() for note in
                self._page("/status" + PATH).all("damping-note")]

    def test_no_wait_is_stated_over_a_node_that_shows_none(self):
        _write(self.tree, deploy=ERROR, tests=OK)
        self.assertEqual(self._card_says(), [])
        self.assertEqual(self._page_says(), [])

    def test_the_wait_of_an_unpinned_line_is_stated_beside_a_pinned_one(self):
        for _ in range(3):
            _write(self.tree, deploy=ERROR, tests=OK)
        _write(self.tree, deploy=ERROR, tests=ERROR)
        self.assertEqual(self._card_says(), ["· 1 of 3 to escalate"])
        self.assertEqual(self._page_says(), [
            "Showing error — 1 of 3 consecutive readings before this escalates, "
            "so the level above still counts ok."])


class EnvelopeTests(TestCase):
    """The envelope carries what the level above counts of what the node shows."""

    def setUp(self) -> None:
        app_module.app.config["TESTING"] = True
        self._saved = (app_module.status_tree, app_module.api_tokens)
        self.addCleanup(self._restore)
        self.tree = StatusTree()
        app_module.status_tree = self.tree
        app_module.api_tokens = {"tester": TOKEN}
        self.client = app_module.app.test_client()
        _write(self.tree, deploy=OK, tests=OK)
        _pin(self.tree, "deploy")

    def _restore(self) -> None:
        app_module.status_tree, app_module.api_tokens = self._saved

    def _node(self) -> dict[str, object]:
        response = self.client.get("/status" + PATH, headers=JSON)
        self.assertEqual(response.status_code, 200)
        node = response.get_json()["status"]
        assert isinstance(node, dict)
        return node

    def test_a_pinned_line_s_failure_is_no_wait_in_it(self):
        _write(self.tree, deploy=ERROR, tests=OK)
        node = self._node()
        self.assertEqual((node["code"], node["contribution"]), ("OK", None))

    def test_the_wait_of_an_unpinned_line_is_in_it(self):
        for _ in range(3):
            _write(self.tree, deploy=ERROR, tests=OK)
        _write(self.tree, deploy=ERROR, tests=ERROR)
        node = self._node()
        # a mechanism decided, and no rule: ``rule`` is null (ADR-0141 decision 3)
        self.assertEqual((node["code"], node["contribution"]),
                         ("ERROR", {"code": "OK", "by": "damping", "rule": None}))
