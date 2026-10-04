"""System is two pages: what is running, and what is installed (ADR-0100).

One long page said the process's live figures and its schedule, which the poll
refreshes, and beneath them everything the installation settled at startup —
check types, packages, extensions, identity doors, the policy. The two have
different readers and different lives, so they are two views of one heading.
"""
import re
from datetime import UTC, datetime
from unittest import TestCase, mock

from little_sister import app as app_module
from little_sister.engine import CheckInfo, EngineInfo
from little_sister.tree import StatusTree

INSTALLED = ("Check types", "Identity", "Content-Security-Policy")


def _check(**facts):
    """One row of the schedule, with everything a row needs and nothing more."""
    base = {"path": "/svc/a", "type_name": "http", "frequency_seconds": 300,
            "running": False, "running_since": None, "running_seconds": None,
            "next_run_at": datetime(2026, 7, 31, 10, 5, tzinfo=UTC),
            "next_in_seconds": 240.0,
            "last_run_at": datetime(2026, 7, 31, 10, 0, tzinfo=UTC),
            "elapsed_seconds": 0.4}
    return CheckInfo(**(base | facts))


class SystemViewsTests(TestCase):

    def setUp(self):
        app_module.app.config["TESTING"] = True
        self._tree = app_module.status_tree
        app_module.status_tree = StatusTree()
        self.addCleanup(setattr, app_module, "status_tree", self._tree)
        engine = mock.patch.object(app_module, "engine", None)
        engine.start()
        self.addCleanup(engine.stop)
        self.client = app_module.app.test_client()
        self.client.post("/login",
                         data={"username": "pan", "password": "12345678"})

    def _page(self, url):
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200, url)
        return response.get_data(as_text=True)

    def test_running_says_what_runs_and_refreshes(self):
        body = self._page("/system")
        self.assertIn("This instance", body)
        self.assertIn('id="system-info"', body)
        self.assertIn('data-target="system-info"', body)
        self.assertIn('id="status-updated"', body)
        for heading in (*INSTALLED, "Packages", "Extensions"):
            self.assertNotIn(f'uppercase">{heading}<', body)

    def test_installed_says_what_startup_settled_and_does_not_refresh(self):
        body = self._page("/system/installed")
        for heading in INSTALLED:
            self.assertIn(f'uppercase">{heading}<', body)
        self.assertNotIn("This instance", body)
        self.assertNotIn('id="system-info"', body)
        self.assertNotIn("js/poll.js", body)
        self.assertNotIn('id="status-updated"', body)

    def test_the_two_are_tabs_under_one_heading(self):
        for url, current in (("/system", "Running"),
                             ("/system/installed", "Installed")):
            with self.subTest(url=url):
                body = self._page(url)
                tabs = re.findall(
                    r'<a class="ls-views__tab( is-current)?" href="([^"]+)"[^>]*>'
                    r"([^<]+)</a>", body)
                self.assertEqual([(href, label) for _, href, label in tabs],
                                 [("/system", "Running"),
                                  ("/system/installed", "Installed")])
                self.assertEqual([label for on, _, label in tabs if on], [current])
                self.assertRegex(body, r">System <span[^>]*>· little-sister ")

    def test_installed_opens_every_section_under_an_index(self):
        body = self._page("/system/installed")
        index = body.split('aria-label="Sections"', 1)[1].split("</nav>", 1)[0]
        for anchor, heading in (("check-types", "Check types"),
                                ("identity", "Identity"),
                                ("csp", "Content-Security-Policy")):
            with self.subTest(anchor=anchor):
                self.assertIn(f'href="#{anchor}"', index)
                self.assertRegex(
                    body, rf'id="{anchor}"[^>]*>\s*<div class="card-body">\s*'
                    rf'<h3 class="h6 text-muted text-uppercase">{heading}</h3>')

    def test_installed_is_an_admins_page_too(self):
        with self.client.session_transaction() as session:
            session["username"] = "viewer"
            session["admin"] = False
        self.assertEqual(self.client.get("/system/installed").status_code, 403)

    def test_the_rail_says_system_on_both(self):
        body = self._page("/system/installed")
        self.assertRegex(body, r'href="/system" title="System"\s+aria-current="page"')


class ScheduleTests(TestCase):
    """The schedule on Running: a row per check, and each column saying what it
    holds. `Declared` held the type's estimate and, in parentheses, the heaviest
    record the last run carried, so its heading described half of its cells; the
    type and what a check is reached through were columns of their own, one an em
    dash nearly everywhere, and the times wrapped."""

    def setUp(self):
        app_module.app.config["TESTING"] = True
        self.client = app_module.app.test_client()
        self.client.post("/login",
                         data={"username": "pan", "password": "12345678"})

    def _schedule(self, *checks):
        info = EngineInfo(started_at=datetime(2026, 7, 31, 10, 0, tzinfo=UTC),
                          uptime_seconds=5.0,
                          max_workers=8, check_count=len(checks), running=0,
                          checks=checks)
        stub = mock.Mock()
        stub.info.return_value = info
        with mock.patch.object(app_module, "engine", stub):
            body = self.client.get("/system?fragment=1").get_data(as_text=True)
        table = body.split("<table", 1)[1].split("</table>", 1)[0]
        heads = re.findall(r"<th>([^<]+)</th>", table.split("</thead>", 1)[0])
        rows = table.split("<tbody>", 1)[1].split("</tr>")[:-1]
        return body, heads, [re.findall(r"<td[^>]*>(.*?)</td>", row, re.S)
                             for row in rows]

    def test_each_column_says_what_it_holds(self):
        body, heads, _ = self._schedule(_check())
        self.assertEqual(heads, ["Check", "Every", "Running", "Next run",
                                 "Last run", "Declared", "Seen"])
        # one line says how the two halves compare
        self.assertIn("ls-schedule__legend", body)

    def test_the_check_carries_its_type_and_what_it_is_reached_through(self):
        _, _, rows = self._schedule(
            _check(path="/svc/a", type_name="http", depends_on="/net/vpn"),
            _check(path="/svc/b", type_name="command"))
        first, second = rows[0][0], rows[1][0]
        self.assertIn('href="/status/svc/a">/svc/a</a>', first)
        self.assertIn("http", first)
        self.assertIn('through <a href="/status/net/vpn">/net/vpn</a>', first)
        self.assertIn("command", second)
        self.assertNotIn("through", second)

    def test_declared_is_the_estimate_and_seen_the_record_the_run_carried(self):
        _, _, rows = self._schedule(
            _check(expected_cost=2.0, expected_entries=1, expected_record=512,
                   record_bytes=3473, record_refused=True),
            _check(path="/svc/b"))
        declared, seen = rows[0][5], rows[0][6]
        self.assertIn("2.0 s", declared)
        self.assertIn("1 entry", declared)
        self.assertIn("512 B record", declared)
        self.assertNotIn("3,473", declared)
        self.assertIn("3,473 B", seen)
        self.assertIn("refused", seen)
        # nothing declared and nothing seen are dashes, never a zero
        self.assertEqual([cell.strip() for cell in rows[1][5:7]], ["—", "—"])
