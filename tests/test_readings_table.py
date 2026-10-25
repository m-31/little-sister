"""A readings table keeps time and names in view; a quiet log says what it means
(ADR-0102), read against the record's sentences.

One host, ``/lab/host``, read every two minutes for an hour from 17:00 in the
configured zone by a check whose type declares what it thinks worth reading: CPU
busy and memory in use in percent, the space used on each volume, the one-minute
load under nothing but its field's name, the run's elapsed time in seconds,
labeled by its field, and swap in use, which this host never reports. Its records
carry the rest among fields nobody declared, in an order of their own. Every fifth
reading lacks ``mem_used_kb``, and the oldest reads memory at zero.
"""
from __future__ import annotations

import html
import re
from collections.abc import Sequence
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from typing import Any
from unittest import TestCase, mock

from little_sister import app as app_module
from little_sister.checks.base import Check, CheckResult, Measurement
from little_sister.engine import Engine
from little_sister.series import MemoryStore, SeriesKey, SeriesRecord
from little_sister.status import StatusCode
from little_sister.tree import Beginning, Event, LastShown, StatusTree

T0 = datetime(2026, 9, 26, 15, 0, tzinfo=UTC)          # 17:00 in Berlin
HOST = "/lab/host"
READINGS = 30

#: The configuration the page is read in: Berlin's clock, written to the second.
SETTINGS = {"timezone": "Europe/Berlin", "time_format": "%Y-%m-%d %H:%M:%S"}

#: What the type declares, in its order.
MEASURES: dict[str, object] = {
    "cpu_pct": {"unit": "%", "label": "CPU busy"},
    "mem_pct": {"unit": "%", "label": "Memory in use"},
    "volumes.*.pct": {"unit": "%", "label": "Disk used on *"},
    "load1": "",
    "elapsed": {"unit": "s"},
    "swap_pct": {"unit": "%", "label": "Swap in use"},
}


class _Host(Check):
    """A check whose readings the test writes into the store the engine reads."""

    type_name = "host"

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(measure_defaults=MEASURES, **kwargs)

    def measure(self) -> Measurement:
        return Measurement(record={})

    def grade(self, measurements: Sequence[Measurement],
              now: datetime) -> CheckResult:
        return CheckResult(StatusCode.OK)


def _record(step: int) -> dict[str, object]:
    """The record of the ``step``-th reading, in the order the host writes it."""
    record: dict[str, object] = {
        "exit_code": 0, "mem_pct": 0 if step == 0 else 18 + step % 3,
        "mem_used_kb": 2_880_000 + step, "elapsed": 1.25, "cpu_pct": 8 + step % 5,
        "load1": 0.47, "volumes": {"root": {"pct": 41}, "data": {"pct": 73}},
        "uptime_seconds": 1_399_000 + 120 * step}
    if step % 5 == 4:
        del record["mem_used_kb"]
    return record


def _stamp(minutes: float) -> datetime:
    """The instant ``minutes`` after 17:00, as an event holds its time."""
    return T0 + timedelta(minutes=minutes)


def _words(markup: str) -> str:
    return " ".join(html.unescape(re.sub(r"<[^>]+>", " ", markup)).split())


def _boxes(body: str) -> list[tuple[dict[str, str], str]]:
    """Each readings box on the page: its attributes, and what it holds."""
    found = []
    for attributes, inside in re.findall(
            r'<div class="ls-readings-box"([^>]*)>(.*?)</div>', body, re.S):
        found.append(({key: html.unescape(value) for key, value in
                       re.findall(r'([\w-]+)="([^"]*)"', attributes)}, inside))
    return found


def _headings(body: str) -> list[str]:
    """The first readings table's column headings, as a reader reads them."""
    table = re.search(r'<table class="[^"]*\bls-readings\b[^"]*">(.*?)</table>', body,
                      re.S)
    assert table is not None, "no readings table"
    head = table.group(1).split("</thead>", 1)[0]
    return [_words(cell) for cell in re.findall(r"<th\b[^>]*>(.*?)</th>", head, re.S)]


def _rows(body: str) -> list[list[str]]:
    """The first readings table's rows, cell by cell; the Time cell read as its time
    and then its cue's name."""
    table = re.search(r'<table class="[^"]*\bls-readings\b[^"]*">(.*?)</table>', body,
                      re.S)
    assert table is not None, "no readings table"
    rows = []
    for row in re.findall(r"<tr[^>]*>(.*?)</tr>", table.group(1).split("<tbody>", 1)[1],
                          re.S):
        cells: list[str] = []
        for cell in re.findall(r"<td[^>]*>(.*?)</td>", row, re.S):
            cells.append(_words(cell))
            cue = re.search(r'aria-label="([^"]+)"', cell)
            if cue:
                cells.append(cue.group(1))
        rows.append(cells)
    return rows


def _periods(body: str) -> list[list[str]]:
    """The rows of the table of the node's own periods, cell by cell: the one table
    of a node with nothing beneath it, the second of a node above others, beneath
    the periods of what it shows (ADR-0132 decision 6)."""
    table = re.search(r'<table class="[^"]*\bls-history__own\b[^"]*">\s*<thead>'
                      r"\s*<tr><th>Status</th>(.*?)</table>", body, re.S)
    assert table is not None, "no periods table"
    return [[_words(cell) for cell in re.findall(r"<td[^>]*>(.*?)</td>", row, re.S)]
            for row in re.findall(r"<tr[^>]*>(.*?)</tr>",
                                  table.group(1).split("<tbody>", 1)[1], re.S)]


class ReadingsTableTests(TestCase):
    """The box, its headings, and what History says above it."""

    def setUp(self) -> None:
        self._saved = (app_module.status_tree, app_module.engine)
        self.addCleanup(self._restore)
        settings = mock.patch("little_sister.config.config",
                              replace(app_module.config, **SETTINGS))
        settings.start()
        self.addCleanup(settings.stop)
        self.deploy()
        self.client = app_module.app.test_client()
        self.client.post("/login", data={"username": "pan", "password": "12345678"})

    def _restore(self) -> None:
        app_module.status_tree, app_module.engine = self._saved

    def deploy(self, **measures: object) -> None:
        """The estate, with the deployment's ``measures:`` block where one is given."""
        self.tree = StatusTree()
        check = _Host(path=HOST, series_keep=500, frequency_seconds=120,
                      measures=measures or None)
        store = MemoryStore()
        for step in range(READINGS):
            store.add(SeriesKey("host", HOST, "alpha"),
                      SeriesRecord(_record(step), T0 + timedelta(minutes=2 * step),
                                   code=StatusCode.OK), keep=500)
        self.tree.upsert(HOST, StatusCode.OK, "all well", frequency_seconds=120)
        app_module.status_tree = self.tree
        app_module.engine = Engine([check], self.tree, series=store)

    def _get(self, url: str) -> str:
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200, url)
        return response.get_data(as_text=True)

    # --- decision 1: a box that keeps its times and names in view -----------------

    def test_the_table_is_a_named_region_a_keyboard_can_scroll(self) -> None:
        (attributes, inside), = _boxes(self._get(f"/history{HOST}"))
        self.assertEqual(attributes.get("role"), "region")
        self.assertEqual(attributes.get("tabindex"), "0")
        self.assertEqual(attributes.get("aria-label"), "Readings of alpha")
        self.assertIn("ls-readings", inside)

    def test_every_reading_stays_on_the_page_newest_first(self) -> None:
        rows = _rows(self._get(f"/history{HOST}"))
        self.assertEqual(len(rows), READINGS)
        self.assertEqual(rows[0][0], "2026-09-26 17:58:00")
        self.assertEqual(rows[-1][0], "2026-09-26 17:00:00")

    def test_the_time_column_carries_the_cue(self) -> None:
        body = self._get(f"/history{HOST}")
        self.assertEqual(_headings(body)[:2], ["Time", "CPU busy · % cpu_pct"])
        self.assertEqual(_rows(body)[0][:2], ["2026-09-26 17:58:00", "ok"])

    def test_history_readings_take_the_pages_width_and_its_periods_keep_theirs(
            self) -> None:
        body = self._get(f"/history{HOST}")
        narrow = re.search(r'<div class="ls-history__periods">(.*?)</table>', body,
                           re.S)
        assert narrow is not None, "no narrow periods block"
        self.assertIn("<th>Since</th>", narrow.group(1))
        self.assertNotIn("ls-readings", narrow.group(1))
        self.assertNotIn("max-width: 980px", body)

    def test_the_series_view_tables_sit_in_the_same_box(self) -> None:
        (attributes, _inside), = _boxes(self._get(f"/series{HOST}"))
        self.assertEqual(attributes.get("role"), "region")
        self.assertEqual(attributes.get("aria-label"), "Readings of alpha")

    # --- decision 2: a column says what its check declares; the declared lead -----

    def test_the_declared_columns_lead_headed_by_label_and_unit_over_the_field(
            self) -> None:
        self.assertEqual(_headings(self._get(f"/history{HOST}")), [
            "Time",
            "CPU busy · % cpu_pct",
            "Memory in use · % mem_pct",
            "Disk used on root · % volumes.root.pct",
            "Disk used on data · % volumes.data.pct",
            "load1",
            "elapsed · s",
            "exit_code", "mem_used_kb", "uptime_seconds",
            "Reason"])

    def test_a_label_that_is_its_field_stands_once_with_the_unit_beside_it(
            self) -> None:
        body = self._get(f"/history{HOST}")
        table = body[body.index('class="table table-sm align-middle ls-readings"'):]
        head = table.split("</thead>", 1)[0]
        cells = [cell for cell in re.findall(r"<th\b[^>]*>(.*?)</th>", head, re.S)
                 if "elapsed" in cell]
        self.assertEqual(len(cells), 1)
        self.assertEqual(cells[0].count("elapsed"), 1)
        self.assertEqual(_words(cells[0]), "elapsed · s")

    def test_a_field_the_deployment_stops_declaring_keeps_its_name_alone(
            self) -> None:
        self.deploy(cpu_pct=None)
        headings = _headings(self._get(f"/history{HOST}"))
        self.assertEqual(headings[1], "Memory in use · % mem_pct")
        self.assertEqual(headings[-5:], ["exit_code", "mem_used_kb", "cpu_pct",
                                         "uptime_seconds", "Reason"])

    def test_a_cell_holds_the_value_as_stored_and_a_missing_field_stays_empty(
            self) -> None:
        rows = _rows(self._get(f"/history{HOST}"))
        oldest, newest = rows[-1], rows[0]
        # Time, cue, CPU, memory, root, data, load1, elapsed, exit_code, used, uptime
        self.assertEqual(oldest[2:11], ["8", "0", "41", "73", "0.47", "1.25", "0",
                                        "2880000", "1399000"])
        self.assertEqual(rows[-5][9], "")     # the fifth reading has no mem_used_kb
        self.assertEqual(newest[3], str(18 + 29 % 3))

    def test_the_series_view_heads_its_columns_the_same_way(self) -> None:
        self.assertEqual(_headings(self._get(f"/series{HOST}")),
                         _headings(self._get(f"/history{HOST}")))

    # --- decision 3: a quiet log says what it means -------------------------------

    def test_a_container_that_declares_nothing_says_so(self) -> None:
        body = self._get("/history/lab")
        self.assertIn("Declares nothing of its own: its page heads with what its "
                      "children roll up to.", _words(body))
        self.assertNotIn("No status changes recorded", body)

    def test_a_container_whose_one_change_was_to_declare_nothing_says_so_once(
            self) -> None:
        self.tree.restore_events([
            Event(path="/lab", name="lab", old=StatusCode.OK,
                  new=StatusCode.UNDEFINED, reason=(), timestamp=_stamp(20))])
        body = self._get("/history/lab")
        sentence = ("Declares nothing of its own since 2026-09-26 17:20:00: its page "
                    "heads with what its children roll up to.")
        self.assertEqual(_periods(body), [[sentence]])
        self.assertEqual(_words(body).count("Declares nothing of its own"), 1)

    def test_a_steady_node_shows_the_period_that_holds_before_the_logs_oldest_event(
            self) -> None:
        # a kept file written before an entry said when a period began, whose log
        # holds no row of the node: the bound is the log's oldest event
        self.tree.restore_events([
            Event(path="/lab/other", name="other", old=StatusCode.OK,
                  new=StatusCode.WARN, reason=("slow",), timestamp=_stamp(30)),
            Event(path="/lab/other", name="other", old=StatusCode.WARN,
                  new=StatusCode.OK, reason=("fast",), timestamp=_stamp(40))],
            {HOST: LastShown(StatusCode.OK, StatusCode.OK)})
        self.assertEqual(_periods(self._get(f"/history{HOST}")),
                         [["ok", "before 2026-09-26 17:30:00", "current", "all well"]])

    def test_a_steady_node_whose_beginning_was_kept_shows_it(self) -> None:
        self.tree.restore_events([], {HOST: LastShown(
            StatusCode.OK, StatusCode.OK,
            Beginning(_stamp(10), was=StatusCode.ERROR, cause="reading"))})
        self.assertEqual(_periods(self._get(f"/history{HOST}")),
                         [["ok", "2026-09-26 17:10:00", "current", "all well"]])

    def test_a_node_no_check_has_written_keeps_no_status_changes_recorded(
            self) -> None:
        self.tree.set_about("/lab/fresh", "Read by nothing yet.")
        self.assertEqual(_periods(self._get("/history/lab/fresh")),
                         [["No status changes recorded."]])

    def test_a_node_the_log_holds_changes_of_keeps_its_periods(self) -> None:
        self.tree.upsert(HOST, StatusCode.WARN, "slow")
        self.tree.upsert(HOST, StatusCode.OK, "all well")
        periods = _periods(self._get(f"/history{HOST}"))
        self.assertEqual([period[0] for period in periods], ["ok", "warn", "ok"])
        self.assertNotIn("before", periods[0][1])
        self.assertNotIn("before", periods[1][1])
        # the oldest is the node's first reading, which found it as it was
        self.assertIn("before", periods[2][1])
