"""The Series index says where each link leads, and names each node once (ADR-0103),
read against the record's sentences.

Four roots. A host, ``gaffsie``, whose check is mounted on the root itself and draws two
curves. A cloud account, ``aws``, whose own check keeps a series that draws none, with a
batch queue beneath it that draws one. ``lab``, which keeps nothing itself, with a host
beneath whose own series draw nothing and a site beneath that which draws one. And
``services``, which keeps nothing itself either, with a site that draws a curve, a
heartbeat that keeps readings and draws none, and a box whose name only begins like
the heartbeat's, which draws one.
"""
from __future__ import annotations

import html
import re
from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from typing import Any
from unittest import TestCase

from little_sister import app as app_module
from little_sister.checks.base import Check, CheckResult, Measurement
from little_sister.engine import Engine
from little_sister.series import MemoryStore, SeriesKey, SeriesRecord
from little_sister.status import StatusCode
from little_sister.tree import StatusTree

T0 = datetime(2026, 9, 26, 15, 0, tzinfo=UTC)


class _Kept(Check):
    """A check whose readings the test writes into the store the engine reads."""

    type_name = "kept"

    def measure(self) -> Measurement:
        return Measurement(record={})

    def grade(self, measurements: Sequence[Measurement],
              now: datetime) -> CheckResult:
        return CheckResult(StatusCode.OK)


class _Cost(_Kept):
    type_name = "cost"


#: Each mount: its check, and the record of its ``step``-th reading.
ESTATE: dict[str, tuple[type[_Kept], dict[str, object], Any]] = {
    "/gaffsie": (_Kept, {"load": "", "mem": {"unit": "%", "label": "Memory"}},
                 lambda step: {"load": 0.5 + step, "mem": 20 + step}),
    "/aws": (_Cost, {}, lambda step: {"usd": 12}),
    "/aws/batch": (_Kept, {"jobs": ""}, lambda step: {"jobs": step}),
    "/lab/host": (_Kept, {}, lambda step: {"up": 1}),
    "/lab/host/web": (_Kept, {"ms": "ms"}, lambda step: {"ms": 99 + step}),
    "/services/web": (_Kept, {"ms": {"unit": "ms", "label": "Response time"}},
                      lambda step: {"ms": 120 + step}),
    "/services/beat": (_Kept, {}, lambda step: {"modified": "a while ago"}),
    "/services/beatbox": (_Kept, {"bpm": ""}, lambda step: {"bpm": 90 + step}),
}


def _words(markup: str) -> str:
    return " ".join(html.unescape(re.sub(r"<[^>]+>", " ", markup)).split())


def _cells(row: str, name: str) -> list[str]:
    return re.findall(rf'<td class="[^"]*\bls-series-index__{name}\b[^"]*"[^>]*>'
                      r"(.*?)</td>",
                      row, re.S)


def _cell(row: str, name: str) -> str | None:
    found = _cells(row, name)
    return found[0] if found else None


def _lines(body: str) -> list[dict[str, Any]]:
    """Each line of the index, in its order: whether it heads a root, the node's name
    and where it leads, the cells beside it, and the words of its links."""
    lines = []
    for kind, row in re.findall(r'<tr class="ls-series-index__(top|row)">(.*?)</tr>',
                                body, re.S):
        name = re.search(r'<a class="ls-series-index__node" href="([^"]*)">(.*?)</a>',
                         row, re.S)
        assert name is not None, row
        views = "".join(_cells(row, "views"))
        links = {words: html.unescape(href) for href, words in
                 re.findall(r'<a href="([^"]*)">([^<]*)</a>', views)}
        curves = _cell(row, "curves") or ""
        summary = re.search(r"<summary[^>]*>(.*?)</summary>(.*?)</details>", curves,
                            re.S)
        lines.append({
            "kind": kind, "name": _words(name.group(2)),
            "status": html.unescape(name.group(1)),
            "curves": links.get("curves"), "readings": links.get("readings"),
            "views": sorted(links),
            "count": _words(summary.group(1)) if summary else _words(curves),
            "labels": ", ".join(_words(label) for label in re.findall(
                r'<span class="ls-spark-row__label">(.*?)</span>',
                summary.group(2), re.S)) if summary else "",
            "kinds": _words(_cell(row, "kinds") or ""),
            "kept": _words(_cell(row, "kept") or ""),
            "newest": _words(_cell(row, "newest") or "")})
    return lines


class SeriesIndexTests(TestCase):
    """Where the index's links lead, what its Curves column says, and its roots."""

    def setUp(self) -> None:
        self._saved = (app_module.status_tree, app_module.engine)
        self.addCleanup(self._restore)
        self.tree = StatusTree()
        store = MemoryStore()
        checks = []
        for path, (kind, measures, record) in ESTATE.items():
            checks.append(kind(path=path, series_keep=20, frequency_seconds=60,
                               measures=measures or None))
            for step in range(5):
                store.add(SeriesKey(kind.type_name, path, "subject"),
                          SeriesRecord(record(step), T0 + timedelta(minutes=step),
                                       code=StatusCode.OK), keep=20)
            self.tree.upsert(path, StatusCode.OK, frequency_seconds=60)
        app_module.status_tree = self.tree
        app_module.engine = Engine(checks, self.tree, series=store)
        self.client = app_module.app.test_client()
        self.client.post("/login", data={"username": "pan", "password": "12345678"})
        response = self.client.get("/series")
        self.assertEqual(response.status_code, 200)
        self.body = response.get_data(as_text=True)
        self.lines = {line["name"]: line for line in _lines(self.body)}

    def _restore(self) -> None:
        app_module.status_tree, app_module.engine = self._saved

    # --- decision 1: a name opens its node; a row says where else it leads --------

    def test_every_name_opens_its_nodes_status_page(self) -> None:
        for name, line in self.lines.items():
            with self.subTest(name=name):
                self.assertEqual(line["status"], f"/status/{name}")

    def test_curves_opens_the_series_view_where_a_curve_stands_at_or_beneath(
            self) -> None:
        self.assertEqual({name: line["curves"] for name, line in self.lines.items()}, {
            "aws": "/series/aws", "aws/batch": "/series/aws/batch",
            "gaffsie": "/series/gaffsie",
            "lab": "/series/lab", "lab/host": "/series/lab/host",
            "lab/host/web": "/series/lab/host/web",
            "services": "/series/services", "services/beat": None,
            "services/beatbox": "/series/services/beatbox",
            "services/web": "/series/services/web"})

    def test_readings_opens_the_history_page_where_the_node_keeps_a_series(
            self) -> None:
        readings = {name: line["readings"] for name, line in self.lines.items()}
        self.assertEqual(readings, {
            "aws": "/history/aws", "aws/batch": "/history/aws/batch",
            "gaffsie": "/history/gaffsie",
            "lab": None, "lab/host": "/history/lab/host",
            "lab/host/web": "/history/lab/host/web",
            "services": None, "services/beat": "/history/services/beat",
            "services/beatbox": "/history/services/beatbox",
            "services/web": "/history/services/web"})

    def test_the_views_are_named_in_words_and_nothing_else_links_there(self) -> None:
        for name, line in self.lines.items():
            with self.subTest(name=name):
                self.assertLessEqual(set(line["views"]), {"curves", "readings"})
        self.assertNotIn('href="/history/lab"', self.body)

    # --- decision 2: the Curves column counts; the labels fold behind the count ---

    def test_the_curves_column_counts_and_folds_the_labels(self) -> None:
        self.assertEqual(
            {name: (line["count"], line["labels"])
             for name, line in self.lines.items()},
            {"aws": ("—", ""), "aws/batch": ("1 curve", "jobs"),
             "gaffsie": ("2 curves", "load, Memory"),
             "lab": ("", ""), "lab/host": ("—", ""),
             "lab/host/web": ("1 curve", "ms"),
             "services": ("", ""), "services/beat": ("—", ""),
             "services/beatbox": ("1 curve", "bpm"),
             "services/web": ("1 curve", "Response time")})

    def test_no_row_says_where_its_readings_are_in_a_sentence(self) -> None:
        self.assertNotIn("its readings are on its History page", self.body)

    # --- decision 3: a root appears once, its heading its own row -----------------

    def test_a_root_appears_once_its_heading_its_own_row(self) -> None:
        self.assertEqual([(line["kind"], line["name"]) for line in _lines(self.body)], [
            ("top", "aws"), ("row", "aws/batch"),
            ("top", "gaffsie"),
            ("top", "lab"), ("row", "lab/host"), ("row", "lab/host/web"),
            ("top", "services"), ("row", "services/beat"),
            ("row", "services/beatbox"), ("row", "services/web")])

    def test_a_root_that_keeps_series_carries_them_on_its_heading(self) -> None:
        gaffsie, aws = self.lines["gaffsie"], self.lines["aws"]
        self.assertEqual((gaffsie["kinds"], gaffsie["kept"]), ("kept", "5"))
        self.assertEqual((aws["kinds"], aws["kept"]), ("cost", "5"))
        self.assertTrue(gaffsie["newest"])

    def test_a_root_that_keeps_nothing_itself_leaves_its_cells_empty(self) -> None:
        lab = self.lines["lab"]
        self.assertEqual((lab["kinds"], lab["count"], lab["kept"], lab["newest"]),
                         ("", "", "", ""))

    def test_no_total_stands_beside_a_root(self) -> None:
        self.assertNotIn("at or beneath", self.body)

    # --- what the look found: the table reads in columns at any width -------------

    def test_curves_and_readings_each_keep_a_column_of_their_own(self) -> None:
        heading = re.search(r"<thead>(.*?)</thead>", self.body, re.S)
        assert heading is not None
        spans = [int(span.group(1)) if span else 1 for span in
                 (re.search(r'colspan="(\d+)"', attributes) for attributes in
                  re.findall(r"<th\b([^>]*)>", heading.group(1)))]
        for row in re.findall(r'<tr class="ls-series-index__(?:top|row)">(.*?)</tr>',
                              self.body, re.S):
            views = [_words(cell) for cell in _cells(row, "views")]
            with self.subTest(row=_words(row)[:24]):
                self.assertEqual(len(re.findall(r"<td\b", row)), sum(spans))
                self.assertEqual(len(views), 2)
                self.assertIn(views[0], ("curves", ""))
                self.assertIn(views[1], ("readings", ""))

    def test_on_a_narrow_page_the_table_scrolls_inside_its_card(self) -> None:
        # Positioned, so the visually hidden headings, which are absolutely placed,
        # scroll with the table instead of widening the page beyond it.
        self.assertRegex(self.body, r'<div class="table-responsive position-relative">'
                                    r'\s*<table class="[^"]*\bls-series-index\b')
        for summary in re.findall(r"<summary\b[^>]*>", self.body):
            with self.subTest(summary=summary):
                self.assertRegex(summary, r'class="[^"]*\btext-nowrap\b')
