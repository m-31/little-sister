"""What the pages say of a node its check no longer reports (ADR-0109 decisions 3
to 6): the Events page lists each removal and can hide them by their cause, the
Maintenance page lists a pin whose node is gone, and the check's History page holds
the readings kept of a subject no node stands for any more.
"""
from __future__ import annotations

import html
import os
import re
from datetime import UTC, datetime, timedelta
from unittest import TestCase
from urllib.parse import parse_qs, urlsplit

os.environ.setdefault("SECRET_KEY", "test-key")

from little_sister import app as app_module
from little_sister.engine import Engine
from little_sister.event_filter import EventFilter
from little_sister.status import StatusCode
from little_sister.tree import CAUSE_PIN_ENDED, CAUSE_REMOVED, Event, StatusTree
from tests.page_tree import Element, parse
from tests.test_pruning import EXPORT, IMPORT, JOBS, US, _grown, _pin, _Queue

#: The three kinds of cause the Events page offers a switch for, in its order.
CAUSES = ("reading", "pin", "removed")


class _PageCase(TestCase):
    def setUp(self) -> None:
        app_module.app.config["TESTING"] = True
        self._saved = (app_module.status_tree, app_module.engine)
        self.addCleanup(self._restore)
        self.tree = _grown(StatusTree())
        app_module.status_tree = self.tree
        app_module.engine = None
        self.client = app_module.app.test_client()
        self.client.post("/login",
                         data={"username": "pan", "password": "12345678"})

    def _restore(self) -> None:
        app_module.status_tree, app_module.engine = self._saved

    def _viewer(self) -> None:
        with self.client.session_transaction() as sess:
            sess["username"] = "viewer"
            sess["firstname"] = "Vera"
            sess["admin"] = False

    def _get(self, url: str, status: int = 200) -> str:
        response = self.client.get(url)
        self.assertEqual(response.status_code, status, url)
        return response.get_data(as_text=True)


class EventsTests(_PageCase):
    """The Events page lists these rows and can hide them by their cause
    (decision 5)."""

    def setUp(self) -> None:
        super().setUp()
        # a pin's row, a removal's three, and the readings' five before them
        _pin(self.tree, IMPORT)
        self.tree.prune(JOBS, {"import"})

    def _rows(self, url: str = "/events") -> list[Element]:
        body = parse(self._get(url)).one(tag="tbody")
        return [row for row in body.all(tag="tr") if len(row.all(tag="td")) == 4]

    @staticmethod
    def _chips(row: Element) -> list[str]:
        return [chip.text() for chip in row.all("event-cause")]

    @staticmethod
    def _path(row: Element) -> str:
        return row.all(tag="td")[2].text()

    def test_a_removals_row_says_so_in_a_chip(self) -> None:
        rows = {self._path(row): row for row in self._rows()[:3]}
        self.assertEqual(sorted(rows), sorted([EXPORT, US, "/ci/jobs/export/eu"]))
        for row in rows.values():
            self.assertEqual(self._chips(row), ["removed"])
            # in the ink of the nothing it moved to, not a pin's
            self.assertTrue(row.one("event-cause").has("event-cause--removed"))
            self.assertEqual(row.all(tag="td")[1].text().split()[0], "undefined")
        self.assertIn("no longer reported by its check",
                      rows[EXPORT].all(tag="td")[3].text())

    def test_a_removed_nodes_row_is_no_dead_link(self) -> None:
        by_path = {self._path(row): row for row in self._rows()}
        self.assertEqual(by_path[EXPORT].all(tag="td")[2].all(tag="a"), [])
        self.assertEqual(len(by_path[IMPORT].all(tag="td")[2].all(tag="a")), 1)

    def test_the_page_offers_a_switch_for_each_kind_of_cause(self) -> None:
        group = [group for group in parse(self._get("/events")).all(
            "ls-events-filter__group") if group.attrs.get("aria-label") == "Cause"]
        self.assertEqual(len(group), 1)
        boxes = group[0].all(tag="input")
        self.assertEqual([box.attrs["value"] for box in boxes], list(CAUSES))
        self.assertTrue(all(box.attrs["name"] == "cause" and "checked" in box.attrs
                            for box in boxes))
        self.assertEqual([label.text() for label in group[0].all(tag="label")],
                         ["readings", "pins", "removals"])

    def test_removals_are_hidden_by_their_cause(self) -> None:
        every = self._rows()
        shown = self._rows("/events?cause=reading&cause=pin")
        self.assertEqual(len(shown), len(every) - 3)
        self.assertTrue(all(self._chips(row) != ["removed"] for row in shown))
        said = parse(self._get("/events?cause=reading&cause=pin")).one(
            "ls-events__count").text()
        self.assertEqual(said, f"{len(shown)} of {len(every)} events match")

    def test_removals_alone(self) -> None:
        shown = self._rows("/events?cause=removed")
        self.assertEqual([self._chips(row) for row in shown], [["removed"]] * 3)

    def test_a_pins_rows_alone(self) -> None:
        shown = self._rows("/events?cause=pin")
        self.assertEqual([(self._path(row), self._chips(row)) for row in shown],
                         [(IMPORT, ["set"])])
        self.assertFalse(shown[0].one("event-cause").has("event-cause--removed"))

    def test_every_switch_on_filters_nothing_and_is_written_into_no_link(
            self) -> None:
        url = "/events?cause=reading&cause=pin&cause=removed"
        self.assertEqual(len(self._rows(url)), len(self._rows()))
        self.assertEqual(parse(self._get(url)).all("ls-events__reset"), [])

    def test_the_switches_that_are_on_are_the_ones_the_url_names(self) -> None:
        page = parse(self._get("/events?cause=removed"))
        on = [box.attrs["value"] for box in page.all(tag="input")
              if box.attrs.get("name") == "cause" and "checked" in box.attrs]
        self.assertEqual(on, ["removed"])
        self.assertEqual(len(page.all("ls-events__reset")), 1)

    def test_the_windows_links_keep_the_cause(self) -> None:
        page = parse(self._get("/events?cause=removed"))
        links = [link.attrs["href"] for link in page.all(tag="a")
                 if "from=" in link.attrs.get("href", "")]
        self.assertTrue(links)
        for href in links:
            self.assertEqual(parse_qs(urlsplit(href).query)["cause"], ["removed"])

    def test_a_cause_the_page_does_not_offer_is_refused(self) -> None:
        body = self._get("/events?cause=magic", 400)
        self.assertIn("cause", body)
        self.assertIn("magic", body)


class CauseTests(TestCase):
    """Which switch a row answers to, by what wrote it."""

    @staticmethod
    def _row(cause: str) -> Event:
        return Event(path="/db", name="db", old=StatusCode.OK,
                     new=StatusCode.ERROR, reason=("down",),
                     timestamp=datetime(2026, 9, 26, 17, 0, tzinfo=UTC), cause=cause)

    def _answers_to(self, cause: str) -> list[str]:
        return [kind for kind in CAUSES
                if EventFilter(causes=(kind,)).matches(self._row(cause))]

    def test_a_row_that_says_no_cause_is_a_readings(self) -> None:
        # a log written before a row said its cause (ADR-0107 decision 6): it is
        # drawn without a chip, and is filtered as it is drawn
        self.assertEqual(self._answers_to(""), ["reading"])

    def test_every_row_a_pin_wrote_is_a_pins(self) -> None:
        self.assertEqual(self._answers_to(CAUSE_PIN_ENDED), ["pin"])
        self.assertEqual(self._answers_to("line-pin-set"), ["pin"])

    def test_a_removal_is_neither(self) -> None:
        self.assertEqual(self._answers_to(CAUSE_REMOVED), ["removed"])


class MaintenanceTests(_PageCase):
    """The Maintenance page lists a pin whose node is no longer reported
    (decision 4)."""

    def _sections(self) -> dict[str, Element]:
        page = parse(self._get("/maintenance"))
        return {section.one("pin-node__path").text(): section
                for section in page.all("pin-node")}

    def test_a_pin_on_a_removed_node_is_listed_as_not_reported(self) -> None:
        _pin(self.tree, EXPORT, note="until the queue moves")
        self.tree.prune(JOBS, {"import"})
        sections = self._sections()
        self.assertEqual(list(sections), [EXPORT])
        section = sections[EXPORT]
        self.assertTrue(section.has("pin-node--suspended"))
        # its path leads nowhere, so it is no link
        self.assertEqual(section.one("pin-node__path").all(tag="a"), [])
        said = section.one("pin-node__suspended").text()
        self.assertIn("not reported", said)
        self.assertIn("until the queue moves", section.text())

    def test_a_pin_on_a_node_that_is_reported_reads_as_it_did(self) -> None:
        _pin(self.tree, EXPORT)
        section = self._sections()[EXPORT]
        self.assertFalse(section.has("pin-node--suspended"))
        self.assertEqual(len(section.one("pin-node__path").all(tag="a")), 1)
        self.assertEqual(section.all("pin-node__suspended"), [])

    def test_the_count_includes_it(self) -> None:
        _pin(self.tree, EXPORT)
        _pin(self.tree, IMPORT)
        self.tree.prune(JOBS, {"import"})
        page = parse(self._get("/maintenance"))
        self.assertEqual(page.one("pin-count").text(), "2 pins on 2 nodes.")

    def test_a_lines_pin_on_a_removed_node_is_listed_beneath_it(self) -> None:
        self.tree.set_entry_maintenance(
            EXPORT, "newest", "known",
            expires_at=datetime.now(UTC) + timedelta(hours=1), set_by="lex")
        self.tree.prune(JOBS, {"import"})
        section = self._sections()[EXPORT]
        self.assertTrue(section.has("pin-node--suspended"))
        block = section.one("rule-block")
        self.assertTrue(block.has("rule-block--line"))
        self.assertIn("known", block.text())
        # the line is not there to be shown, and its slug is never text
        self.assertNotIn("newest", block.one("rule-block__what").text())

    def test_an_admin_edits_and_clears_it_there(self) -> None:
        pin = _pin(self.tree, EXPORT)
        self.tree.prune(JOBS, {"import"})
        section = self._sections()[EXPORT]
        forms = section.all(tag="form")
        self.assertEqual(len(forms), 2)
        response = self.client.post("/maintenance", data={
            "path": EXPORT, "action": "clear", "set_at": pin.token,
            "next": "/maintenance?node=/ci/jobs/export#pinned-node"})
        self.assertEqual(response.status_code, 302)
        self.assertIsNone(self.tree.maintenance_entry(EXPORT))
        self.assertIsNone(self.tree.snapshot(EXPORT))
        self.assertIn("No nodes are in maintenance.", self._get("/maintenance"))

    def test_an_edit_keeps_it_and_makes_no_node(self) -> None:
        pin = _pin(self.tree, EXPORT)
        self.tree.prune(JOBS, {"import"})
        response = self.client.post("/maintenance", data={
            "path": EXPORT, "action": "set", "set_at": pin.token,
            "reason": "until Monday", "duration": "3d"})
        self.assertEqual(response.status_code, 302)
        stored = self.tree.maintenance_entry(EXPORT)
        assert stored is not None
        self.assertEqual(stored.reason, "until Monday")
        self.assertIsNone(self.tree.snapshot(EXPORT))
        self.assertTrue(self._sections()[EXPORT].has("pin-node--suspended"))

    def test_a_viewer_reads_it_without_buttons(self) -> None:
        _pin(self.tree, EXPORT)
        self.tree.prune(JOBS, {"import"})
        self._viewer()
        section = self._sections()[EXPORT]
        self.assertEqual(section.all(tag="form"), [])
        self.assertTrue(section.has("pin-node--suspended"))

    def test_the_strip_counts_only_what_is_silenced_now(self) -> None:
        # a suspended pin silences nothing, so the wall's pill does not count it
        _pin(self.tree, EXPORT)
        self.tree.prune(JOBS, {"import"})
        self.assertNotIn(EXPORT, self._get("/status"))


class HistoryTests(TestCase):
    """A series no node stands for is listed on its check's History page
    (decision 6), and a removed node's own page is gone."""

    def setUp(self) -> None:
        app_module.app.config["TESTING"] = True
        self._saved = (app_module.status_tree, app_module.engine)
        self.addCleanup(self._restore)
        self.tree = StatusTree()
        app_module.status_tree = self.tree
        self.check = _Queue(path="/batch", subject="queue/live", series_keep=5)
        self.check.jobs = {"import": "succeeded", "export": "failed"}
        app_module.engine = Engine([self.check], self.tree)
        app_module.engine.run_once()
        self.client = app_module.app.test_client()
        self.client.post("/login",
                         data={"username": "pan", "password": "12345678"})

    def _restore(self) -> None:
        app_module.status_tree, app_module.engine = self._saved

    def _get(self, url: str, status: int = 200) -> str:
        response = self.client.get(url)
        self.assertEqual(response.status_code, status, url)
        return response.get_data(as_text=True)

    def test_the_removed_childs_readings_are_on_its_checks_history_page(
            self) -> None:
        self.assertNotIn("job/export", self._get("/history/batch"))
        self.assertIn("job/export", self._get("/history/batch/export"))
        del self.check.jobs["export"]
        assert app_module.engine is not None
        app_module.engine.run_once()
        page = self._get("/history/batch")
        self.assertIn("job/export", page)
        self.assertIn("export failed", page)

    def test_the_series_view_says_whose_the_kept_readings_are(self) -> None:
        # While its node stands a job's runs are drawn under it. Removed, they are
        # kept and drawn nowhere: the view of the node above names the job they are
        # of, where it said only that its check keeps readings.
        self.assertNotIn("job/export", self._get("/series/batch"))
        del self.check.jobs["export"]
        assert app_module.engine is not None
        app_module.engine.run_once()
        quiet = re.findall(r'<p class="[^"]*\bls-series-quiet\b[^"]*">(.*?)</p>',
                           self._get("/series/batch"), re.S)
        said = [re.sub(r" ([,.])", r"\1", " ".join(
            html.unescape(re.sub(r"<[^>]+>", " ", line)).split())) for line in quiet]
        self.assertEqual(
            said[0], "batch keeps 1 reading of job/export, which has no node of its "
                     "own, and draws no curve — they are on its History page.")
        self.assertIn("<code>job/export</code>", quiet[0])
        # the job that still has its node is named as itself, as before
        self.assertEqual(
            said[1:], ["batch/import keeps 2 readings and draws no curve — they are "
                       "on its History page."])

    def test_the_removed_nodes_own_page_is_gone(self) -> None:
        del self.check.jobs["export"]
        assert app_module.engine is not None
        app_module.engine.run_once()
        # one page for every view of it, and a 404 (ADR-0116; `test_no_node.py`
        # reads what it says)
        self.assertIn("ls-no-node", self._get("/status/batch/export", status=404))
        self.assertNotIn("batch/export", self._get("/status/batch"))
        # its History said that no change was recorded, where the log holds its
        # removal
        history = self._get("/history/batch/export", status=404)
        self.assertIn("ls-no-node", history)
        self.assertNotIn("No status changes recorded", history)
        self.assertIn("ls-no-node", self._get("/series/batch/export", status=404))
        self.assertIn("ls-no-node", self._get("/copy/batch/export", status=404))

    def test_a_node_nothing_has_written_keeps_its_sentence(self) -> None:
        self.tree.set_about("/batch/idle", "Read by nothing yet.")
        history = self._get("/history/batch/idle")
        self.assertIn("No status changes recorded", history)
        self.assertNotIn("ls-no-node", history)


class QuietLineTests(TestCase):
    """What a Series view says of readings that draw no curve, by whose they are."""

    def _said(self, **quiet: object) -> str:
        with app_module.app.test_request_context("/series/batch"):
            macro = app_module.app.jinja_env.get_template("_series.html").module
            line = str(macro.quiet_line(  # type: ignore[attr-defined]
                app_module._Quiet(path="batch", **quiet)))  # type: ignore[arg-type]
        return re.sub(r" ([,.])", r"\1", " ".join(
            html.unescape(re.sub(r"<[^>]+>", " ", line)).split()))

    _TAIL = "and draws no curve — they are on its History page."

    def test_a_checks_own_readings_are_said_as_they_were(self) -> None:
        self.assertEqual(self._said(kept=10, subjects=1),
                         f"batch keeps 10 readings {self._TAIL}")
        self.assertEqual(self._said(kept=1, subjects=1),
                         f"batch keeps 1 reading {self._TAIL}")
        self.assertEqual(self._said(kept=4, subjects=2),
                         f"batch keeps 4 readings of 2 subjects {self._TAIL}")

    def test_one_subject_without_a_node_is_named(self) -> None:
        self.assertEqual(
            self._said(kept=3, subjects=1, unstood=("job/export",), unstood_kept=3),
            f"batch keeps 3 readings of job/export, which has no node of its own, "
            f"{self._TAIL}")

    def test_beside_the_checks_own_it_says_how_many_are_the_subjects(self) -> None:
        self.assertEqual(
            self._said(kept=7, subjects=3, unstood=("job/a", "job/b"), unstood_kept=6),
            f"batch keeps 7 readings, 6 of them of job/a and job/b, which have no "
            f"node of their own, {self._TAIL}")

    def test_three_are_named_and_more_are_counted(self) -> None:
        self.assertEqual(
            self._said(kept=9, subjects=3, unstood=("a", "b", "c"), unstood_kept=9),
            f"batch keeps 9 readings of a, b and c, which have no node of their own, "
            f"{self._TAIL}")
        self.assertEqual(
            self._said(kept=9, subjects=4, unstood=("a", "b", "c", "d"),
                       unstood_kept=9),
            f"batch keeps 9 readings of a, b, c and 1 more, which have no node of "
            f"their own, {self._TAIL}")
        self.assertEqual(
            self._said(kept=9, subjects=5, unstood=("a", "b", "c", "d", "e"),
                       unstood_kept=9),
            f"batch keeps 9 readings of a, b, c and 2 more, which have no node of "
            f"their own, {self._TAIL}")
