"""System is two pages: what is running, and what is installed (ADR-0100).

One long page said the process's live figures and its schedule, which the poll
refreshes, and beneath them everything the installation settled at startup —
check types, packages, extensions, identity doors, the policy. The two have
different readers and different lives, so they are two views of one heading.
"""
import html
import logging
import re
from datetime import UTC, datetime
from unittest import TestCase, mock

from little_sister import app as app_module
from little_sister import logger as default
from little_sister import noise
from little_sister.engine import CheckInfo, EngineInfo
from little_sister.logger import Entries
from little_sister.tree import StatusTree

INSTALLED = ("Check types", "Identity", "Content-Security-Policy", "Logging")


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
                                ("csp", "Content-Security-Policy"),
                                ("logging", "Logging")):
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


def _said(markup):
    """What a reader reads in a piece of the page: its text, on one line, a line
    break of the page read as a space."""
    text = re.sub(r"<[^>]+>", "", re.sub(r"<br>|</h3>|</p>|</td>", " ", markup))
    return " ".join(html.unescape(text).split())


class LoggingSectionTests(TestCase):
    """Installed says what the log leaves out (ADR-0121 decision 7): whether the
    library's default is in charge, the root's level with where it comes from,
    every logger that carries a level of its own with where *that* comes from — a
    cap a package declared, an entry of ``LOG_LEVEL``, or neither — every declared
    cap that was not set with the reason, every level an entry took off, and every
    entry that could not be read.

    Each test plays a deployment's start against real loggers — the default
    installed, packages declaring, the code of the slot, the application's import —
    and reads the page. Everything it touches is put back: the table, the two
    things the logger module decided, and every logger's level.
    """

    def setUp(self):
        app_module.app.config["TESTING"] = True
        engine = mock.patch.object(app_module, "engine", None)
        engine.start()
        self.addCleanup(engine.stop)
        self.client = app_module.app.test_client()
        self.client.post("/login",
                         data={"username": "pan", "password": "12345678"})
        root = logging.getLogger()
        standing = {logger: logger.level for logger in self._loggers()}
        self.addCleanup(self._put_back, (noise._caps, default.in_charge,
                                         default.entries), standing, root.level)
        for logger in standing:
            logger.setLevel(logging.NOTSET)
        noise.forget_caps()
        default.in_charge = True

    @staticmethod
    def _loggers():
        return [logger for logger in logging.Logger.manager.loggerDict.values()
                if isinstance(logger, logging.Logger)]

    def _put_back(self, decided, standing, root_level):
        noise._caps, default.in_charge, default.entries = decided
        for logger in self._loggers():
            logger.setLevel(standing.get(logger, logging.NOTSET))
        logging.getLogger().setLevel(root_level)

    def _start(self, variable=""):
        """The default installed, as the first import of the library does it."""
        default.entries = Entries.read(variable)
        default._set_levels(default.entries)

    @staticmethod
    def _package(name):
        """``noise.cap`` as that package's registration module calls it."""
        return lambda logger, level, hides: noise._caps.declare(
            logger, level, hides=hides, package=name)

    def _section(self):
        response = self.client.get("/system/installed")
        self.assertEqual(response.status_code, 200)
        body = response.get_data(as_text=True)
        return body, body.split('id="logging">', 1)[1].split("</body>", 1)[0]

    @staticmethod
    def _tables(section):
        """Each table of the section: its headings, and its rows as text."""
        tables = []
        for table in re.findall(r"<table.*?</table>", section, re.S):
            heads = re.findall(r"<th>([^<]+)</th>", table)
            rows = table.split("<tbody>", 1)[1].split("</tr>")[:-1]
            tables.append((heads, [[_said(cell) for cell in re.findall(
                r"<td[^>]*>(.*?)</td>", row, re.S)] for row in rows]))
        return tables

    def test_it_says_where_every_level_comes_from(self):
        self._start("DEBUG,example_sdk.credentials=DEBUG")
        aws = self._package("little_sister_example")
        aws("example_sdk.credentials", logging.WARNING,
            "where each new session found its credentials, a line a run")
        aws("example_sdk.wire", logging.WARNING, "a line a request")
        logging.getLogger("example_http").setLevel(logging.ERROR)   # the slot's code
        noise._caps.settle(in_charge=True, entries=default.entries)

        _, section = self._section()

        (heads, rows), _not_set = self._tables(section)
        self.assertEqual(heads, ["Logger", "Level", "From"])
        self.assertEqual(rows, [
            ["example_http", "ERROR",
             "the application's code, or the dependency itself"],
            ["example_sdk.credentials", "DEBUG",
             "LOG_LEVEL entry example_sdk.credentials=DEBUG"],
            ["example_sdk.wire", "WARNING",
             "cap, declared by little_sister_example — hides a line a request"],
            ["markdown_it", "INFO",
             "cap, declared by little_sister — hides a DEBUG line for each block "
             "rule of every render"]])

    def test_it_says_who_is_in_charge_and_where_the_roots_level_comes_from(self):
        for variable, code_sets, said in (
                ("WARNING", None,
                 "The root logger is at WARNING: the level LOG_LEVEL names."),
                ("", None, "The root logger is at INFO: the default, since "
                           "LOG_LEVEL names no level."),
                ("WARNING", logging.ERROR,
                 "The root logger is at ERROR: set by code, after the default was "
                 "installed."),
                ("", logging.DEBUG,
                 "The root logger is at DEBUG: set by code, after the default was "
                 "installed.")):
            with self.subTest(variable=variable, code=code_sets):
                self._start(variable)
                if code_sets is not None:
                    logging.getLogger().setLevel(code_sets)
                first = _said(self._section()[1].split("</p>", 1)[0])
                self.assertEqual(first, "Logging The library's default is in "
                                        "charge of this log. " + said)

    def test_a_cap_two_packages_declared_names_both(self):
        """Two packages may bring one dependency: the higher level stands, and
        the page names both, the lower one with the level it declared."""
        self._start("DEBUG")
        self._package("little_sister_example")(
            "example_sdk.credentials", logging.WARNING, "a line a run")
        self._package("another_package")(
            "example_sdk.credentials", logging.INFO, "how it looked for them")
        noise._caps.settle(in_charge=True, entries=default.entries)

        _, section = self._section()

        (_, rows), = self._tables(section)
        self.assertEqual(rows[0], [
            "example_sdk.credentials", "WARNING",
            "cap, declared by another_package at INFO — hides how it looked for "
            "them cap, declared by little_sister_example — hides a line a run"])

    def test_every_cap_that_was_not_set_says_why(self):
        """The first of the four reasons that held, for each."""
        self._start("INFO,example_sdk.credentials=DEBUG")
        aws = self._package("little_sister_example")
        aws("example_sdk.credentials", logging.WARNING, "a line a run")
        aws("example_sdk.wire", logging.INFO, "its DEBUG lines")
        aws("example_http", logging.WARNING, "a line a connection")
        logging.getLogger("example_http").setLevel(logging.DEBUG)   # the slot's code
        noise._caps.settle(in_charge=True, entries=default.entries)

        _, section = self._section()

        _levels, (heads, rows) = self._tables(section)
        self.assertEqual(heads, ["Logger", "Cap", "Declared by", "Not set because"])
        self.assertEqual(rows, [
            ["example_http", "WARNING",
             "little_sister_example — hides a line a connection",
             "example_http is at DEBUG, set by the application's code or by the "
             "dependency itself"],
            ["example_sdk.credentials", "WARNING",
             "little_sister_example — hides a line a run",
             "LOG_LEVEL names example_sdk.credentials"],
            ["example_sdk.wire", "INFO",
             "little_sister_example — hides its DEBUG lines",
             "it would take no line away — without it the logger is at INFO "
             "already, through the root"],
            ["markdown_it", "INFO",
             "little_sister — hides a DEBUG line for each block rule of every "
             "render",
             "it would take no line away — without it the logger is at INFO "
             "already, through the root"]])

    def test_a_cap_two_packages_declared_and_that_was_not_set_names_both(self):
        """As a cap that was set does: each package, with what its cap hides, and
        the lower one with the level it declared."""
        self._start("INFO,example_sdk=DEBUG")
        self._package("little_sister_example")(
            "example_sdk.credentials", logging.WARNING, "a line a run")
        self._package("another_package")(
            "example_sdk.credentials", logging.INFO, "how it looked for them")
        noise._caps.settle(in_charge=True, entries=default.entries)

        _, section = self._section()

        _levels, (_, rows) = self._tables(section)
        self.assertEqual(rows[0], [
            "example_sdk.credentials", "WARNING",
            "another_package at INFO — hides how it looked for them "
            "little_sister_example — hides a line a run",
            "LOG_LEVEL names example_sdk"])

    def test_it_says_how_a_capped_loggers_lines_come_back(self):
        """By name, with a logger of this instance in the example. The line is
        the variable as it was read with one entry more, and the entry names the
        level the logger is at without its cap — the root's ``DEBUG`` here. The
        example and the index's count are of the *capped* loggers: a level an
        entry named or the deployment's code set is no cap, and where nothing is
        capped neither is shown."""
        self._start("DEBUG,an_entry=ERROR")
        self._package("little_sister_example")(
            "example_sdk.credentials", logging.WARNING, "a line a run")
        logging.getLogger("a_choice").setLevel(logging.WARNING)     # the slot's code
        noise._caps.settle(in_charge=True, entries=default.entries)
        body, section = self._section()
        self.assertEqual([row[0] for row in self._tables(section)[0][1]], [
            "a_choice", "an_entry", "example_sdk.credentials", "markdown_it"])
        self.assertIn("A capped logger's lines come back by name, at the next "
                      "start: LOG_LEVEL=DEBUG,an_entry=ERROR,"
                      "example_sdk.credentials=DEBUG, in .env or in the "
                      "environment.", _said(section))
        index = body.split('aria-label="Sections"', 1)[1].split("</nav>", 1)[0]
        self.assertRegex(index, r'href="#logging">Logging <span[^>]*>2 capped</span>')

        noise.forget_caps()
        for logger in self._loggers():
            logger.setLevel(logging.NOTSET)
        self._start("INFO,an_entry=ERROR")
        logging.getLogger("a_choice").setLevel(logging.WARNING)
        noise._caps.settle(in_charge=True, entries=default.entries)
        body, section = self._section()
        self.assertEqual([row[0] for row in self._tables(section)[0][1]],
                         ["a_choice", "an_entry"])
        self.assertNotIn("come back by name", _said(section))
        index = body.split('aria-label="Sections"', 1)[1].split("</nav>", 1)[0]
        self.assertRegex(index, r'href="#logging">Logging</a>')

    def test_the_example_is_the_variable_as_read_and_one_entry_more(self):
        """Pasting it changes one thing. Under the default's root the entry is
        ``INFO`` — what a cap at ``WARNING`` hid, and nothing below it. An entry
        the variable already has stays, one that could not be read does not, and
        the bare level in front is the variable's own, or the default's where it
        names none: not the root's as code has moved it since."""
        for variable, example in (
                ("INFO,an_entry=ERROR",
                 "LOG_LEVEL=INFO,an_entry=ERROR,example_sdk.credentials=INFO"),
                ("an_entry=ERROR,chatty",
                 "LOG_LEVEL=INFO,an_entry=ERROR,example_sdk.credentials=INFO"),
                ("", "LOG_LEVEL=INFO,example_sdk.credentials=INFO")):
            with self.subTest(variable=variable):
                noise.forget_caps()
                for logger in self._loggers():
                    logger.setLevel(logging.NOTSET)
                self._start(variable)
                self._package("little_sister_example")(
                    "example_sdk.credentials", logging.WARNING, "a line a run")
                noise._caps.settle(in_charge=True, entries=default.entries)
                logging.getLogger().setLevel(logging.DEBUG)         # code, later
                self.assertIn(f"at the next start: {example}, in .env or in the "
                              "environment.", _said(self._section()[1]))

    def test_a_level_taken_off_twice_is_said_once(self):
        """The entries are said with the default and again where the caps are
        set, so a level the startup file sets a second time is taken off a second
        time. The page says what was taken off, once."""
        logging.getLogger("example_orm.pool").setLevel(logging.WARNING)
        self._start("INFO,example_orm=DEBUG")                 # said with the default
        logging.getLogger("example_orm.pool").setLevel(logging.WARNING)   # again
        noise._caps.settle(in_charge=True, entries=default.entries)

        said = _said(self._section()[1])

        self.assertEqual(len(default.entries.taken_off), 2)
        self.assertIn("Taken off by LOG_LEVEL: WARNING on example_orm.pool, "
                      "which the entry for example_orm speaks for.", said)
        self.assertEqual(said.count("on example_orm.pool,"), 1)

    def test_it_says_what_an_entry_took_off_and_what_could_not_be_read(self):
        logging.getLogger("example_orm.pool").setLevel(logging.WARNING)
        self._start("INFO,example_orm=DEBUG,example_sdk=LOUD,chatty")
        noise._caps.settle(in_charge=True, entries=default.entries)

        said = _said(self._section()[1])

        self.assertIn("Taken off by LOG_LEVEL: WARNING on example_orm.pool, "
                      "which the entry for example_orm speaks for.", said)
        self.assertIn("Entries of LOG_LEVEL that could not be read, and were "
                      "skipped: example_sdk=LOUD ('LOUD' is not a level name); "
                      "chatty ('chatty' is not a level name).", said)

    def test_nothing_is_said_of_what_did_not_happen(self):
        self._start("")
        noise._caps.settle(in_charge=True, entries=default.entries)
        said = _said(self._section()[1])
        self.assertNotIn("Taken off", said)
        self.assertNotIn("could not be read", said)
        self.assertIn("No logger carries a level of its own.", said)

    def test_an_application_that_configured_logging_is_said_first(self):
        """No level is the library's to set then: the root is the application's,
        the variable does nothing, and every declared cap is listed as not set."""
        default.in_charge = False
        default.entries = Entries.read("DEBUG,example_orm=DEBUG,chatty")
        logging.getLogger().setLevel(logging.ERROR)
        logging.getLogger("example_orm").setLevel(logging.WARNING)   # its own
        self._package("little_sister_example")(
            "example_sdk.credentials", logging.WARNING, "a line a run")
        noise._caps.settle(in_charge=False, entries=default.entries)

        _, section = self._section()

        self.assertEqual(
            _said(section.split("</p>", 1)[0]),
            "Logging The application configured logging itself, so no level is "
            "the library's to set: the root logger, at ERROR, is the "
            "application's, LOG_LEVEL does nothing, and no declared cap is set.")
        (_, levels), (_, not_set) = self._tables(section)
        self.assertEqual(levels, [
            ["example_orm", "WARNING",
             "the application's code, or the dependency itself"]])
        self.assertEqual([(row[0], row[3]) for row in not_set], [
            ("example_sdk.credentials",
             "the application configured logging itself"),
            ("markdown_it", "the application configured logging itself")])
        self.assertNotIn("could not be read", _said(section))

    def test_the_package_inventory_names_a_packages_caps(self):
        """Beside its other registrations — set or not, which the section says."""
        self._start("")
        aws = self._package("little_sister_example")
        aws("example_sdk.credentials", logging.WARNING, "a line a run")
        aws("example_sdk.wire", logging.INFO, "its DEBUG lines")
        noise._caps.declare("example_sdk.retries", logging.INFO,
                            hides="a line a retry", package="")
        noise._caps.settle(in_charge=True, entries=default.entries)

        body, section = self._section()

        packages = body.split('id="packages">', 1)[1].split(
            '<div class="card mb-3"', 1)[0]
        (row,) = [row for row in packages.split("</tr>")
                  if "<code>little_sister_example</code>" in row]
        self.assertEqual(
            [_said(item) for item in re.findall(
                r'<span class="ls-system__register">(.*?)</span>', row)],
            ["cap example_sdk.credentials", "cap example_sdk.wire"])
        # the library's own is no row of the inventory, and neither is a caller
        # that names no installation — whose cap the section lists all the same
        self.assertNotIn("cap markdown_it", _said(packages))
        self.assertNotIn("example_sdk.retries", _said(packages))
        self.assertIn("example_sdk.retries INFO an unidentified caller (__main__) "
                      "— hides a line a retry", _said(section))
