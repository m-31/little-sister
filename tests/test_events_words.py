"""A row of the Events page says its status in a word of its own where a node's own pin
or window wrote it on a node that reports nothing of its own (ADR-0150): *nothing of its
own*, read off the row — its status and its reading both undefined, the Copy document's
own test for such a node — and never off the tree, so that an old row keeps its word as
the tree changes. Its tint and the *undefined* switch read its code, and the switch's
title says so. The gap where the instance was not running, which no pin wrote, keeps
*undefined*, and so does a pin's end on a node not read yet since a start, whose check
reported what the log kept."""
from __future__ import annotations

import json
import os
from datetime import timedelta
from unittest import TestCase, mock

os.environ.setdefault("SECRET_KEY", "test-key")

from little_sister import app as app_module
from little_sister import instants
from little_sister.status import StatusCode
from little_sister.tree import CAUSE_PIN_ENDED, StatusTree, events_from_payload
from tests.page_tree import Element, parse
from tests.test_windows import BEFORE, FIRST, FIRST_CLOSE, NIGHTLY, _Clock, _Kept

OK, ERROR = StatusCode.OK, StatusCode.ERROR
UNDEFINED = StatusCode.UNDEFINED
HOSTS = "/site/hosts"


class TheWordTests(TestCase):
    """A branch, ``/site/hosts``, that reports nothing of its own above a host that is
    down, beside a web node that is fine; read by an admin on a clock the test sets."""

    def setUp(self) -> None:
        app_module.app.config["TESTING"] = True
        self.clock = _Clock(BEFORE)
        self.kept = _Kept()
        self.tree = StatusTree(pin_store=self.kept)
        for patched in (mock.patch.object(instants, "now", self.clock),
                        mock.patch.object(app_module, "status_tree", self.tree)):
            patched.start()
            self.addCleanup(patched.stop)
        self.tree.upsert(f"{HOSTS}/a", ERROR, "down")
        self.tree.upsert("/site/web", OK, "fine")
        self.client = app_module.app.test_client()
        self.client.post("/login", data={"username": "pan", "password": "12345678"})

    def page(self, query: str = "") -> Element:
        answer = self.client.get(f"/events{query}")
        self.assertEqual(answer.status_code, 200)
        return parse(answer.get_data(as_text=True))

    def rows(self, path: str, query: str = "") -> list[tuple[str, str, str]]:
        """The rows the page lists of ``path``, newest first: each one's word, its tint
        and its chip."""
        found = []
        for row in self.page(query).all(tag="tr"):
            cells = row.all(tag="td")
            if len(cells) < 3 or cells[2].text() != path:
                continue
            chip = row.all("event-cause")
            found.append((row.one("ls-log__status").text(), row.attrs["class"],
                          chip[0].text() if chip else ""))
        return found

    def nightly_window(self) -> None:
        """The branch's nightly patching, its first window opened and closed."""
        self.tree.set_maintenance(HOSTS, "nightly patching", schedule=NIGHTLY,
                                  set_by="ada")
        for moment in (FIRST, FIRST_CLOSE):
            self.clock.at = moment
            self.tree.sweep_expired()

    def restarted(self) -> StatusTree:
        """A new process on what this one kept, an hour on, read by the page."""
        self.clock.at += timedelta(hours=1)
        new = StatusTree(pin_store=self.kept)
        new.restore_events(events_from_payload(
            json.loads(json.dumps(self.tree.events_payload()))))
        new.restore_maintenance(dict(self.kept.nodes), now=self.clock.at)
        patched = mock.patch.object(app_module, "status_tree", new)
        patched.start()
        self.addCleanup(patched.stop)
        return new

    def test_a_branch_s_window_closing_says_nothing_of_its_own(self):
        self.nightly_window()
        self.assertEqual(self.rows(HOSTS)[:2], [
            ("nothing of its own", "row-undefined", "window closed · at its end"),
            ("maintenance", "row-maintenance", "window opened")])

    def test_a_pin_s_end_on_a_branch_says_nothing_of_its_own(self):
        self.tree.set_maintenance(HOSTS, "patching", set_by="ada",
                                  expires_at=BEFORE + timedelta(hours=2))
        self.tree.clear_maintenance(HOSTS, by="ben")
        self.assertEqual(self.rows(HOSTS), [
            ("nothing of its own", "row-undefined", "maintenance ended · by hand"),
            ("maintenance", "row-maintenance", "set")])

    def test_the_gap_where_the_instance_was_not_running_keeps_its_word(self):
        self.tree.upsert("/little-sister/engine", OK, "running")
        self.tree.upsert("/little-sister", OK, "serving")
        stopped = self.clock.at
        new = self.restarted()
        self.assertTrue(new.close_unobserved("/little-sister", stopped,
                                             "the instance was not running"))
        self.assertEqual(self.rows("/little-sister")[0],
                         ("undefined", "row-undefined", ""))

    def test_a_pin_s_end_on_a_node_not_read_since_the_start_keeps_its_word(self):
        self.tree.upsert("/db", OK, "fine")
        self.tree.set_maintenance("/db", "reindex", set_by="ada",
                                  expires_at=BEFORE + timedelta(hours=4))
        new = self.restarted()
        new.clear_maintenance("/db", by="ben")
        (row,) = [event for event in new.recent_events()
                  if event.path == "/db" and event.cause == CAUSE_PIN_ENDED]
        self.assertEqual((row.new, row.reported), (UNDEFINED, OK),
                         "what its check reported is the log's")
        self.assertEqual(self.rows("/db")[0],
                         ("undefined", "row-undefined", "maintenance ended · by hand"))

    def test_the_undefined_switch_selects_them_and_its_title_says_so(self):
        self.nightly_window()
        self.assertEqual(self.rows(HOSTS, "?status=undefined"), [
            ("nothing of its own", "row-undefined", "window closed · at its end")])
        self.assertNotIn("nothing of its own",
                         [word for word, _, _ in self.rows(HOSTS,
                                                           "?status=maintenance")])
        (switch,) = [label for label in self.page().all(tag="label")
                     if label.attrs.get("for") == "status-undefined"]
        self.assertEqual(switch.attrs["title"],
                         "Also the rows that say nothing of its own: a pin's or a "
                         "window's, on a node that reports nothing")
        self.assertEqual(switch.text(), "undefined")
