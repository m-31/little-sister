"""A node's series have a view of their own, beside its status and its history
(ADR-0097), read against the record's sentences.

The estate is one host read by two checks that share its node — its metrics and its
memory, as a Mac is — with a website mounted beneath it and a heartbeat file beside
that, whose series declares no measure. Their kept readings are written into the
store the engine reads, the way the engine writes them, and the nodes are left as the
newest runs left them.
"""
from __future__ import annotations

import html
import re
import tempfile
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from unittest import TestCase, mock

from little_sister import app as app_module
from little_sister.checks.file import FileFreshnessCheck
from little_sister.checks.http import HttpCheck
from little_sister.checks.ssh import HostMetricsCheck
from little_sister.checks.ssh.macos_memory import MacosMemoryCheck
from little_sister.engine import Engine
from little_sister.reasons import Entry
from little_sister.series import MemoryStore, SeriesKey, SeriesRecord
from little_sister.status import StatusCode
from little_sister.tree import StatusTree
from tests.test_web import _curves, _reading_rows

T0 = datetime(2026, 9, 26, 15, 0, tzinfo=UTC)
HOST = "/hosts/alpha"
SITE = "https://www.example.org"


def _host_reading(step: int) -> dict[str, Any]:
    if step == 7:
        return {"exit_code": 255, "error": "ssh to alpha.example failed (exit 255): "
                "refused", "mem_pct": None, "cpu_pct": None, "load1": None,
                "load1_per_core": None, "ncpu": None, "disk_pct": None}
    return {"exit_code": 0, "mem_pct": 60 + step % 5, "mem_used_kb": 5_000_000,
            "mem_total_kb": 8_388_608, "cpu_pct": 10 + step, "load1": 0.4,
            "ncpu": 4, "load1_per_core": 0.1, "disk_pct": 51,
            "disk_avail_kb": 45_000_000, "disk_total_kb": 90_000_000,
            "disk_path": "/", "os": "Linux", "hostname": "alpha"}


def _window_range(body: str) -> str:
    """The window as the Series view's bar names it, read as text."""
    said = re.search(r'<p class="ls-window__range">(.*?)</p>', body, re.S)
    assert said is not None, "the page names no window"
    return " ".join(html.unescape(re.sub(r"<[^>]+>", "", said.group(1))).split())


def _mac_reading(step: int) -> dict[str, Any]:
    return {"exit_code": 0, "pressure_level": 1, "compressor_pct": 15 + step % 3,
            "swap_used_mb": 0, "swap_total_mb": 0,
            "processes": {"mail": {"count": 1, "rss_kb": 400_000 + 1000 * step,
                                   "elapsed_seconds": 60 * step}}}


class SeriesViewTests(TestCase):
    """The view, the node pages beside it, and how a reader moves between them."""

    def setUp(self) -> None:
        self.tree = StatusTree()
        self._saved = (app_module.status_tree, app_module.engine)
        self.addCleanup(self._restore)
        app_module.status_tree = self.tree
        settings = mock.patch(
            "little_sister.config.config",
            replace(app_module.config, timezone="Europe/Berlin",
                    time_format="%Y-%m-%d %H:%M:%S"))
        settings.start()
        self.addCleanup(settings.stop)
        self.client = app_module.app.test_client()
        self.client.post("/login", data={"username": "pan", "password": "12345678"})
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self._deploy()

    def _restore(self) -> None:
        app_module.status_tree, app_module.engine = self._saved

    def _deploy(self, mac_minutes: int = 2, **config: Any) -> None:
        base = Path(self.directory.name)
        (base / "metrics.sh").write_text("echo hi\n")
        host = HostMetricsCheck.from_config(
            {"type": "host-metrics", "path": HOST, "host": "alpha.example",
             "script": "metrics.sh", "frequency": "2m", "series_keep": 720,
             **config}, base)
        mac = MacosMemoryCheck.from_config(
            {"type": "macos-memory", "path": HOST, "host": "alpha.example",
             "script": "metrics.sh", "frequency": f"{mac_minutes}m",
             "series_keep": 720,
             "processes": [{"name": "mail", "pattern": "Mail.app"}]}, base)
        site = HttpCheck.from_config(
            {"type": "http", "path": f"{HOST}/web", "url": SITE, "frequency": "3m",
             "series_keep": 480}, base)
        beat = FileFreshnessCheck.from_config(
            {"type": "file", "path": f"{HOST}/beat", "file": "/tmp/beat",
             "max_age": "5m", "frequency": "3m", "series_keep": 480}, base)
        self.checks = (host, mac, site, beat)
        store = MemoryStore()
        for step in range(20):
            at = T0 + timedelta(minutes=2 * step)
            store.add(SeriesKey("host-metrics", HOST, "alpha.example"),
                      SeriesRecord(_host_reading(step), at,
                                   code=StatusCode.ERROR if step == 7
                                   else StatusCode.OK, texts=("read",)), keep=720)
            store.add(SeriesKey("macos-memory", HOST, "alpha.example"),
                      SeriesRecord(_mac_reading(step),
                                   T0 + timedelta(minutes=mac_minutes * step),
                                   code=StatusCode.OK, texts=("memory fine",)),
                      keep=720)
        for step in range(10):
            at = T0 + timedelta(minutes=1 + 3 * step)
            store.add(SeriesKey("http", f"{HOST}/web", SITE),
                      SeriesRecord({"status": 200, "response_ms": 200 + step}, at,
                                   code=StatusCode.OK,
                                   texts=(f"HTTP 200 in {200 + step} ms",)),
                      keep=480)
            store.add(SeriesKey("file", f"{HOST}/beat", "/tmp/beat"),
                      SeriesRecord({"modified": {"at": "2026-09-26T14:00:00Z"}}, at,
                                   code=StatusCode.OK, texts=("fresh",)), keep=480)
        app_module.engine = Engine(list(self.checks), self.tree, series=store)
        self.tree.upsert(HOST, StatusCode.UNDEFINED, frequency_seconds=120,
                         subject="alpha.example")
        for name, said in (("memory", "62% used — 4.8 GiB of 8.0 GiB"),
                           ("cpu", "29% busy"),
                           ("load", "0.10 per core — load1 0.40 over 4 CPUs"),
                           ("disk", "51% used"), ("ssh", "alpha reachable"),
                           ("pressure", "normal"), ("compressor", "16% compressed"),
                           ("swap", "0 B used of 0 B allocated")):
            self.tree.upsert(f"{HOST}/{name}", StatusCode.OK, [Entry("x", said)],
                             frequency_seconds=120)
        self.tree.upsert(f"{HOST}/processes/mail", StatusCode.OK,
                         [Entry("x", "410.2 MiB RSS over 1 process")],
                         frequency_seconds=120)
        self.tree.upsert(f"{HOST}/web", StatusCode.OK,
                         [Entry("response", "HTTP 200 in 209 ms")],
                         frequency_seconds=180, subject=SITE,
                         record={"status": 200, "response_ms": 209})
        self.tree.upsert(f"{HOST}/beat", StatusCode.OK, [Entry("x", "fresh")],
                         frequency_seconds=180, subject="/tmp/beat")
        self.tree.upsert("/other/thing", StatusCode.OK, frequency_seconds=60)

    def _get(self, url: str, status: int = 200) -> str:
        response = self.client.get(url)
        self.assertEqual(response.status_code, status, url)
        return response.get_data(as_text=True)

    @staticmethod
    def _titles(body: str) -> list[str]:
        """The title of every curve on the page, in its order."""
        return [re.sub(r"<[^>]+>", "", title) for title in
                re.findall(r'<span class="ls-curve__title">(.*?)</span>', body)]

    @staticmethod
    def _groups(body: str) -> list[tuple[str, list[str]]]:
        """Each group of a Series view: the node it stands under, and its curves."""
        found = []
        pattern = r'<section class="[^"]*\bls-series-group\b.*?</section>'
        for group in re.findall(pattern, body, re.S):
            name = re.search(r'<a class="ls-series-group__node"[^>]*>(.*?)</a>',
                             group, re.S)
            found.append((name.group(1).strip() if name else "",
                          SeriesViewTests._titles(group)))
        return found

    @staticmethod
    def _tabs(body: str) -> list[tuple[str, str, bool]]:
        """The view tabs: each label, where it goes, and whether it is this page."""
        nav = re.search(r'<nav class="ls-views".*?</nav>', body, re.S)
        if nav is None:
            return []
        return [(label, href, "aria-current" in attributes)
                for href, attributes, label in re.findall(
                    r'<a class="ls-views__tab[^"]*" href="([^"]*)"([^>]*)>'
                    # the tab's word; the Series tab's number follows it (ADR-0114)
                    r'([^<]*?)(?: <span.*?)?</a>',
                    nav.group(0), re.S)]

    @staticmethod
    def _crumbs(body: str) -> list[tuple[str, str | None]]:
        """The breadcrumb: each crumb's text, and where it links (``None`` for the
        node the page is about)."""
        trail = re.search(r'<span class="ls-crumbs">(.*?)</span>\s*'
                          r'(?:<span class="node-title|</h1>)', body, re.S)
        assert trail is not None
        crumbs: list[tuple[str, str | None]] = []
        for link, text, plain in re.findall(
                r'<a href="([^"]*)"[^>]*class="[^"]*crumb[^"]*">([^<]*)</a>'
                r'|<span class="text-muted">([^<]*)</span>', trail.group(1)):
            if link or text:
                crumbs.append((text, link))
            elif plain.replace("&nbsp;", " ").strip() != "/":
                crumbs.append((plain, None))
        return crumbs

    # --- decision 1: `/series/<path>` ---------------------------------------------

    def test_the_view_carries_every_curve_at_or_beneath_the_node(self) -> None:
        titles = self._titles(self._get(f"/series{HOST}"))
        for title in ("Memory in use", "CPU busy", "Load per core", "Disk space used",
                      "Memory pressure level", "Compressed memory", "Swap used",
                      "Resident memory of mail", "Response time"):
            with self.subTest(title=title):
                self.assertIn(title, titles)

    def test_each_curve_stands_under_the_node_it_stands_on(self) -> None:
        groups = dict(self._groups(self._get(f"/series{HOST}")))
        self.assertEqual(groups["memory"], ["Memory in use"])
        self.assertEqual(groups["pressure"], ["Memory pressure level"])
        self.assertEqual(groups["processes/mail"], ["Resident memory of mail"])
        self.assertEqual(groups["web"], ["Response time"])

    def test_in_the_tree_s_order(self) -> None:
        names = [name for name, _ in self._groups(self._get(f"/series{HOST}"))]
        self.assertEqual(names, ["compressor", "cpu", "disk", "load", "memory",
                                 "pressure", "processes/mail", "swap", "web"])

    def test_each_group_is_headed_by_its_node_s_status_and_sentence(self) -> None:
        body = self._get(f"/series{HOST}")
        group = re.search(r'<section class="[^"]*\bls-series-group\b[^"]*" '
                          r'id="memory".*?</section>', body, re.S)
        assert group is not None
        self.assertIn(f'href="/status{HOST}/memory"', group.group(0))
        self.assertIn("62% used — 4.8 GiB of 8.0 GiB", group.group(0))
        self.assertIn('aria-label="ok"', group.group(0))

    def test_all_of_it_stands_on_one_time_axis(self) -> None:
        body = self._get(f"/series{HOST}")
        self.assertIn("on one time axis.", body)
        # the window's bar names its ends to the minute (ADR-0098 decision 3) ...
        self.assertEqual(_window_range(body),
                         "Everything kept · 2026-09-26 17:00 – 17:38 CEST")
        # ... and each curve's accessible name to the second (ADR-0098 decision 4)
        times = {end for ends in re.findall(r'aria-label="[^"]* from ([^"]*) to '
                                            r'([^"]*)"', body) for end in ends}
        # the oldest reading any series keeps, and the newest: 17:00 and 17:38
        self.assertEqual(times, {"2026-09-26 17:00:00", "2026-09-26 17:38:00"})

    def test_the_axis_spans_the_series_the_curves_are_drawn_from(self) -> None:
        # the site's readings run from 17:01 to 17:28; the host's two checks, above
        # it, keep theirs to 17:38 and draw nothing on the site's view
        body = self._get(f"/series{HOST}/web")
        # its ends are named in each curve's accessible name (ADR-0098 decision 4)
        times = {end for ends in re.findall(r'aria-label="[^"]* from ([^"]*) to '
                                            r'([^"]*)"', body) for end in ends}
        self.assertEqual(times, {"2026-09-26 17:01:00", "2026-09-26 17:28:00"})

    def test_a_failed_reading_is_marked_on_every_curve_of_its_series(self) -> None:
        groups = re.findall(r'<section class="[^"]*\bls-series-group\b.*?</section>',
                            self._get(f"/series{HOST}"), re.S)
        marked = {name for name, section in zip(
            [n for n, _ in self._groups(self._get(f"/series{HOST}"))], groups,
            strict=True) if 'class="ls-curve__none"' in section}
        self.assertEqual(marked, {"cpu", "disk", "load", "memory"})

    def test_beneath_the_curves_each_series_newest_readings_folded(self) -> None:
        body = self._get(f"/series{HOST}")
        self.assertEqual(len(re.findall(r'<details class="[^"]*ls-series-readings',
                                        body)), 3)
        rows = _reading_rows(body)
        self.assertEqual(len(rows), 30)             # reading_cap, 10 a series
        self.assertIn(f'href="/history{HOST}"', body)
        self.assertIn(f'href="/history{HOST}/web"', body)

    def test_a_series_that_declares_no_measure_links_its_history_page(self) -> None:
        body = self._get(f"/series{HOST}")
        line = re.search(r'<p class="[^"]*ls-series-quiet[^"]*">(.*?)</p>', body,
                         re.S)
        assert line is not None
        self.assertIn("beat", line.group(1))
        self.assertIn(f'href="/history{HOST}/beat"', line.group(1))

    def test_no_declared_curves_preserve_readings_without_claiming_an_axis(
            self) -> None:
        body = self._get(f"/series{HOST}/beat")
        self.assertIn("No curves to display.", body)
        self.assertNotIn("one time axis", body)
        self.assertEqual(self._titles(body), [])
        self.assertIn("keeps 10 readings and draws no curve", body)
        self.assertIn(f'href="/history{HOST}/beat"', body)

    def test_configured_curves_with_no_readings_do_not_claim_an_axis(self) -> None:
        app_module.engine = Engine(list(self.checks), self.tree, series=MemoryStore())
        body = self._get(f"/series{HOST}/web")
        self.assertIn("No curves to display.", body)
        self.assertNotIn("one time axis", body)
        self.assertEqual(self._titles(body), [])
        self.assertEqual(_reading_rows(body), [])
        self.assertIn(("History", f"/history{HOST}/web", False), self._tabs(body))

    def test_retained_readings_without_numbers_do_not_claim_an_axis(self) -> None:
        store = MemoryStore()
        store.add(SeriesKey("http", f"{HOST}/web", SITE),
                  SeriesRecord({"status": 0, "response_ms": None}, T0,
                               code=StatusCode.ERROR, texts=("connection refused",)),
                  keep=480)
        app_module.engine = Engine(list(self.checks), self.tree, series=store)
        body = self._get(f"/series{HOST}/web")
        self.assertIn("No curves to display.", body)
        self.assertNotIn("one time axis", body)
        self.assertEqual(self._titles(body), [])
        self.assertIn("keeps 1 reading and draws no curve", body)
        self.assertIn(f'href="/history{HOST}/web"', body)

    def test_one_plottable_time_keeps_its_axis_and_readings(self) -> None:
        store = MemoryStore()
        store.add(SeriesKey("http", f"{HOST}/web", SITE),
                  SeriesRecord({"status": 200, "response_ms": 200}, T0,
                               code=StatusCode.OK, texts=("HTTP 200 in 200 ms",)),
                  keep=480)
        app_module.engine = Engine(list(self.checks), self.tree, series=store)
        body = self._get(f"/series{HOST}/web")
        self.assertEqual(_window_range(body), "Everything kept · 2026-09-26 17:00 CEST")
        self.assertNotIn("No curves to display.", body)
        self.assertEqual(self._titles(body), ["Response time"])
        self.assertEqual(len(_reading_rows(body)), 1)
        self.assertIn(f'href="/history{HOST}/web"', body)

    def test_a_shared_mount_shows_both_checks_series(self) -> None:
        # the node withholds its one subject and record (ADR-0044) — and still
        # both checks' curves and readings are on the view
        self.assertEqual(self.tree.snapshot(HOST.strip("/")).subject, "")
        body = self._get(f"/series{HOST}")
        titles = self._titles(body)
        self.assertIn("Memory in use", titles)             # host metrics
        self.assertIn("Memory pressure level", titles)      # memory check
        self.assertIn(">host-metrics<", body)
        self.assertIn(">macos-memory<", body)

    def test_each_check_s_curves_break_by_its_own_period(self) -> None:
        # the node the two share carries the period of whichever check wrote it last
        # — the metrics' two minutes here — while the memory check reads every five:
        # its curves break only where its own readings are further apart than its
        # own period allows, and these are not
        self._deploy(mac_minutes=5)
        body = self._get(f"/series{HOST}")
        group = re.search(r'<section class="[^"]*\bls-series-group\b[^"]*" '
                          r'id="compressor".*?</section>', body, re.S)
        assert group is not None
        self.assertNotIn("without readings", group.group(0))

    def test_the_view_is_not_polled(self) -> None:
        self.assertNotIn("poll.js", self._get(f"/series{HOST}"))

    def test_reading_cap_counts_the_rows_it_shows(self) -> None:
        with mock.patch.object(app_module, "config",
                               replace(app_module.config, reading_cap=3)):
            rows = _reading_rows(self._get(f"/series{HOST}"))
        self.assertEqual(len(rows), 9)

    def test_a_node_nothing_keeps_a_series_under_is_no_view(self) -> None:
        self._get("/series/other/thing", status=404)
        self._get("/series/no/such/node", status=404)

    # --- decision 2: a node's page shows the curves that stand on it ----------------

    def test_an_aspect_s_page_shows_its_own_curve(self) -> None:
        body = self._get(f"/status{HOST}/memory")
        self.assertEqual(self._titles(body), ["Memory in use"])
        self.assertIn(f'href="/series{HOST}#memory"', body)

    def test_a_check_s_own_node_shows_a_measure_that_names_no_other(self) -> None:
        self.assertEqual(self._titles(self._get(f"/status{HOST}/web")),
                         ["Response time"])

    def test_the_host_s_page_carries_none_of_its_aspects_curves(self) -> None:
        body = self._get(f"/status{HOST}")
        self.assertEqual(_curves(body), [])
        self.assertEqual(_curves(self._get(f"/status{HOST}?fragment=1")), [])

    def test_and_no_node_s_page_carries_a_readings_table(self) -> None:
        for path in (HOST, f"{HOST}/memory", f"{HOST}/web", f"{HOST}/beat"):
            with self.subTest(path=path):
                self.assertNotIn("ls-readings", self._get(f"/status{path}"))

    def test_history_keeps_every_reading_of_both_checks(self) -> None:
        rows = _reading_rows(self._get(f"/history{HOST}"))
        self.assertEqual(len(rows), 40)

    # --- decision 3: where, which view, which section --------------------------------

    def test_the_breadcrumb_names_the_tree_and_keeps_the_view(self) -> None:
        self.assertEqual(self._crumbs(self._get(f"/status{HOST}/memory")), [
            ("nodes", "/status"), ("hosts", "/status/hosts"),
            ("alpha", f"/status{HOST}"), ("memory", None)])
        self.assertEqual(self._crumbs(self._get(f"/series{HOST}")), [
            ("nodes", "/series"), ("hosts", "/series/hosts"), ("alpha", None)])
        self.assertEqual(self._crumbs(self._get(f"/history{HOST}")), [
            ("nodes", "/status"), ("hosts", "/history/hosts"), ("alpha", None)])
        self.assertEqual(self._crumbs(self._get(f"/copy{HOST}")), [
            ("nodes", "/copy"), ("hosts", "/copy/hosts"), ("alpha", None)])

    def test_a_node_s_views_are_tabs(self) -> None:
        expected = [("Status", f"/status{HOST}"), ("Series", f"/series{HOST}"),
                    ("History", f"/history{HOST}"), ("Copy", f"/copy{HOST}")]
        for view, url in (("Status", f"/status{HOST}"),
                          ("Series", f"/series{HOST}"),
                          ("History", f"/history{HOST}"),
                          ("Copy", f"/copy{HOST}")):
            with self.subTest(view=view):
                tabs = self._tabs(self._get(url))
                self.assertEqual([(label, href) for label, href, _ in tabs], expected)
                self.assertEqual([label for label, _, current in tabs if current],
                                 [view])

    def test_the_series_tab_is_where_the_configuration_puts_a_curve(self) -> None:
        def labels(url: str) -> list[str]:
            return [label for label, _, _ in self._tabs(self._get(url))]
        # nothing keeps a series here
        self.assertEqual(labels("/status/other/thing"), ["Status", "History", "Copy"])
        # a check keeps one on this node
        self.assertIn("Series", labels(f"/status{HOST}/web"))
        # a check above keeps one and declares a measure standing here, or beneath
        self.assertIn("Series", labels(f"/status{HOST}/memory"))
        self.assertIn("Series", labels(f"/status{HOST}/processes"))
        # — a `*` naming any node there
        self.assertIn("Series", labels(f"/status{HOST}/processes/mail"))
        # a check above keeps one, and no measure of its stands here
        self.assertEqual(labels(f"/status{HOST}/ssh"), ["Status", "History", "Copy"])

    def test_the_root_has_no_history_tab(self) -> None:
        self.assertEqual(self._tabs(self._get("/status")),
                         [("Status", "/status", True), ("Series", "/series", False),
                          ("Copy", "/copy", False)])
        self._get("/history", status=404)

    def test_the_history_page_takes_the_same_title_and_tabs(self) -> None:
        body = self._get(f"/history{HOST}")
        self.assertNotIn("back to check", body)
        self.assertNotIn("— history", body)

    def test_the_time_card_leaves_history_to_its_tab(self) -> None:
        body = self._get(f"/status{HOST}/memory")
        self.assertNotIn('class="btn btn-outline-secondary" href="/history', body)

    def test_the_rail_gains_series_lit_on_every_series_view(self) -> None:
        for url in ("/series", f"/series{HOST}"):
            with self.subTest(url=url):
                body = self._get(url)
                self.assertRegex(body, r'<a class="ls-rail__item is-on" href="/series"')
        self.assertRegex(self._get(f"/status{HOST}"),
                         r'<a class="ls-rail__item is-on" href="/status"')

    def test_the_routes_do_not_move(self) -> None:
        for url in (f"/status{HOST}", f"/status{HOST}/memory", f"/history{HOST}"):
            with self.subTest(url=url):
                self._get(url)

    # --- decision 4: the roots --------------------------------------------------------

    def test_status_is_the_overview_titled_nodes(self) -> None:
        body = self._get("/status")
        self.assertEqual(self._crumbs(body), [("nodes", None)])
        self.assertIn('href="/status/hosts"', body)             # the root nodes' cards

    def test_series_is_an_index_of_every_node_a_series_is_kept_on(self) -> None:
        body = self._get("/series")
        self.assertEqual(_curves(body), [])
        rows = re.findall(r'<tr class="ls-series-index__row">(.*?)</tr>', body, re.S)
        found = {re.search(r'<a class="ls-series-index__node" href="([^"]*)">'
                           r'([^<]*)</a>', row).group(2): row
                 for row in rows}
        self.assertEqual(set(found), {"hosts/alpha", "hosts/alpha/web",
                                      "hosts/alpha/beat"})
        self.assertIn("host-metrics · macos-memory", found["hosts/alpha"])
        self.assertIn("Response time", found["hosts/alpha/web"])
        self.assertIn(">40<", found["hosts/alpha"])                # 20 + 20 readings
        self.assertIn("2026-09-26 17:38", found["hosts/alpha"])    # the newest
        top = re.findall(r'<tr class="ls-series-index__top">(.*?)</tr>', body, re.S)
        self.assertEqual(len(top), 1)
        self.assertIn('href="/series/hosts"', top[0])

    def test_a_name_opens_its_node_and_its_row_says_where_else_it_leads(
            self) -> None:
        # ADR-0103 decision 1: the name opens the node's Status page; *curves* its
        # Series view, where a curve stands at or beneath it; *readings* its History
        body = self._get("/series")
        for path, curves in ((HOST, True), (f"{HOST}/web", True),
                             (f"{HOST}/beat", False)):
            with self.subTest(path=path):
                row = re.search(rf'<a class="ls-series-index__node" '
                                rf'href="/status{path}">{path[1:]}</a>(.*?)</tr>',
                                body, re.S)
                assert row is not None, path
                self.assertEqual(f'<a href="/series{path}">curves</a>' in row.group(1),
                                 curves)
                self.assertIn(f'<a href="/history{path}">readings</a>', row.group(1))
