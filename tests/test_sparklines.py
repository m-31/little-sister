"""A curve seen small, and the number on a node's Series tab (ADR-0114).

The Series index names every curve a node's series draw and drew none of them; a
node's Series tab said that a view was there and not how much was on it. Read against
the record's sentences:

* in a row's fold every curve has a sparkline beside its label — the curve's own
  line on the curve's own scale, so it starts at zero as the curve does, and breaks
  where the curve breaks — and beside it the newest, lowest and highest value, in the
  words the curve's summary has them;
* the Series tab carries the number of curves its view draws, and no number where it
  draws none.

The estate is the Series index's own (``tests/test_series_index.py``), with four
mounts more: one whose readings never move, one that reads zero, one with a reading
that failed between others, and a host whose check draws a curve on each of two
nodes beneath it.
"""
from __future__ import annotations

import html
import re
from datetime import timedelta
from typing import Any
from unittest import TestCase

from little_sister import app as app_module
from little_sister import curves
from little_sister.engine import Engine
from little_sister.series import MemoryStore, SeriesKey, SeriesRecord
from little_sister.status import StatusCode
from little_sister.tree import StatusTree
from tests.test_series_index import ESTATE, T0, _Kept, _words

#: Four mounts more: a value that never moves, one that reads zero at its third
#: reading, one whose third reading failed — each one curve — and a host whose two
#: measures each name a node beneath it.
MORE: dict[str, tuple[type[_Kept], dict[str, object], Any]] = {
    "/sparks/flat": (_Kept, {"free": ""}, lambda step: {"free": 50}),
    "/sparks/zero": (_Kept, {"queued": ""},
                     lambda step: {"queued": 0 if step == 2 else 40}),
    "/sparks/broken": (_Kept, {"ms": "ms"},
                       lambda step: ({"error": "no answer"} if step == 2
                                     else {"ms": 100 + step})),
    "/sparks/host": (_Kept, {"load": {"unit": "", "node": "cpu"},
                             "rpm": {"unit": "", "node": "fan"}},
                     lambda step: {"load": 1 + step, "rpm": 900 + step}),
}
#: The nodes that host's measures name.
BENEATH = ("/sparks/host/cpu", "/sparks/host/fan")

_ROW = re.compile(r'<li class="ls-spark-row">(.*?)</li>', re.S)
_SVG = re.compile(r'<svg class="ls-spark"([^>]*)>(.*?)</svg>', re.S)
_LINE = re.compile(r'<path class="ls-spark__line" d="([^"]*)"')
_POINT = re.compile(r"[ML]\s*(-?[\d.]+) (-?[\d.]+)")
_FIGURE = re.compile(r'<figure class="ls-curve">(.*?)</figure>', re.S)
_TAB = re.compile(r'<a class="ls-views__tab[^"]*" href="([^"]*)"[^>]*>(.*?)</a>', re.S)
_COUNT = re.compile(r'<span class="ls-views__count">(\d+)</span>')


class _Estate(TestCase):
    def setUp(self) -> None:
        saved = (app_module.status_tree, app_module.engine)
        self.addCleanup(lambda: setattr(app_module, "status_tree", saved[0]))
        self.addCleanup(lambda: setattr(app_module, "engine", saved[1]))
        tree = StatusTree()
        store = MemoryStore()
        checks = []
        for path, (kind, measures, record) in (ESTATE | MORE).items():
            checks.append(kind(path=path, series_keep=20, frequency_seconds=60,
                               measures=measures or None))
            for step in range(5):
                store.add(SeriesKey(kind.type_name, path, "subject"),
                          SeriesRecord(record(step), T0 + timedelta(minutes=step),
                                       code=StatusCode.OK), keep=20)
            tree.upsert(path, StatusCode.OK, frequency_seconds=60)
        for path in BENEATH:
            tree.upsert(path, StatusCode.OK, frequency_seconds=60)
        app_module.status_tree = tree
        app_module.engine = Engine(checks, tree, series=store)
        self.client = app_module.app.test_client()
        self.client.post("/login", data={"username": "pan", "password": "12345678"})

    def _page(self, url: str) -> str:
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200, url)
        return response.get_data(as_text=True)

    def _curves(self, path: str) -> dict[str, dict[str, Any]]:
        """Each curve of a node's Series view by its label: the lines it draws and
        what its summary says."""
        found = {}
        for figure in _FIGURE.findall(self._page(f"/series{path}")):
            label = re.search(r'<span class="ls-curve__title">(.*?)</span>', figure,
                              re.S)
            says = re.search(r'<span class="ls-curve__summary">(.*?)</span>\s*'
                             r"</figcaption>", figure, re.S)
            assert label is not None and says is not None, figure[:200]
            found[_words(label.group(1))] = {
                "lines": re.findall(r'<path class="ls-curve__line" d="([^"]*)"',
                                    figure),
                "says": _words(says.group(1))}
        return found


class IndexSparklineTests(_Estate):
    def setUp(self) -> None:
        super().setUp()
        self.body = self._page("/series")

    def _fold(self, name: str) -> dict[str, dict[str, Any]]:
        """The fold of the index's line for ``name``: each curve by its label, with
        its sparkline's box and lines and the words beside it."""
        row = re.search(
            rf'<a class="ls-series-index__node" href="/status/{name}">.*?</tr>',
            self.body, re.S)
        assert row is not None, name
        found = {}
        for item in _ROW.findall(row.group(0)):
            label = re.search(r'<span class="ls-spark-row__label">(.*?)</span>', item)
            says = re.search(
                r'<span class="ls-spark-row__says[^"]*">(.*)</span>\s*\Z', item, re.S)
            svgs = _SVG.findall(item)
            assert label is not None and says is not None, item
            self.assertEqual(len(svgs), 1, item)
            box = re.search(r'viewBox="([^"]*)"', svgs[0][0])
            assert box is not None
            found[_words(label.group(1))] = {
                "box": [float(part) for part in box.group(1).split()],
                "lines": _LINE.findall(svgs[0][1]),
                "says": _words(html.unescape(says.group(1)))}
        return found

    def test_every_curve_a_row_names_has_a_sparkline_beside_its_label(self) -> None:
        self.assertEqual(list(self._fold("gaffsie")), ["load", "Memory"])
        self.assertEqual(list(self._fold("services/web")), ["Response time"])
        self.assertEqual(list(self._fold("sparks/flat")), ["free"])
        # a curve that stands on a node beneath is named on the row of the node
        # whose series draws it
        self.assertEqual(list(self._fold("sparks/host")), ["load", "rpm"])

    def test_a_row_that_draws_no_curve_has_none(self) -> None:
        self.assertEqual(self._fold("services/beat"), {})
        self.assertEqual(self._fold("aws"), {})

    def test_it_is_the_curves_own_line(self) -> None:
        for name in ("gaffsie", "services/web", "sparks/broken", "sparks/zero"):
            on_view = self._curves(f"/{name}")
            for label, spark in self._fold(name).items():
                with self.subTest(name=name, label=label):
                    self.assertTrue(spark["lines"])
                    self.assertEqual(spark["lines"], on_view[label]["lines"])

    def test_it_shows_the_plot_and_nothing_around_it(self) -> None:
        # The curve's plot from its left end to its right and from the top of its
        # scale down to its baseline: the same scale, cut out.
        box = self._fold("gaffsie")["load"]["box"]
        self.assertEqual(box, [curves.LEFT, curves.TOP,
                               curves.RIGHT - curves.LEFT,
                               curves.BOTTOM - curves.TOP])

    def test_a_reading_of_zero_stands_on_its_lower_edge(self) -> None:
        spark = self._fold("sparks/zero")["queued"]
        lowest = max(float(y) for line in spark["lines"]
                     for _x, y in _POINT.findall(line))
        self.assertEqual(lowest, spark["box"][1] + spark["box"][3])

    def test_a_value_that_never_moves_is_a_flat_line_above_it(self) -> None:
        # From zero and not from the lowest reading: a series that stands at 50 is
        # drawn level, clear of the edge its zero would stand on.
        spark = self._fold("sparks/flat")["free"]
        heights = {float(y) for line in spark["lines"]
                   for _x, y in _POINT.findall(line)}
        self.assertEqual(len(heights), 1)
        top, bottom = spark["box"][1], spark["box"][1] + spark["box"][3]
        self.assertTrue(top < next(iter(heights)) < bottom, heights)

    def test_a_reading_that_failed_breaks_the_line(self) -> None:
        self.assertEqual(len(self._fold("sparks/broken")["ms"]["lines"]), 2)
        self.assertEqual(len(self._fold("sparks/flat")["free"]["lines"]), 1)

    def test_beside_it_stand_the_newest_the_lowest_and_the_highest(self) -> None:
        self.assertEqual(self._fold("gaffsie")["load"]["says"],
                         "newest 4.5 · lowest 0.5 · highest 4.5")
        for name in ("gaffsie", "sparks/broken"):
            on_view = self._curves(f"/{name}")
            for label, spark in self._fold(name).items():
                with self.subTest(name=name, label=label):
                    self.assertEqual(spark["says"], on_view[label]["says"])

    def test_the_closed_row_still_counts_its_curves(self) -> None:
        row = re.search(r'href="/status/gaffsie">.*?</tr>', self.body, re.S)
        assert row is not None
        self.assertIn('<summary class="text-nowrap">2 curves</summary>',
                      row.group(0))


class SeriesTabCountTests(_Estate):
    def _tab(self, url: str) -> tuple[str, int | None]:
        """The Series tab of the page at ``url``: where it leads, and its number."""
        for href, words in _TAB.findall(self._page(url)):
            if _words(words).split()[0] == "Series":
                count = _COUNT.search(words)
                return html.unescape(href), int(count.group(1)) if count else None
        raise AssertionError(f"no Series tab on {url}")

    def test_it_says_how_many_curves_its_view_draws(self) -> None:
        for path in ("/gaffsie", "/lab", "/lab/host", "/aws", "/services", "/sparks"):
            with self.subTest(path=path):
                href, count = self._tab(f"/status{path}")
                self.assertEqual(href, f"/series{path}")
                self.assertEqual(count, len(self._curves(path)))
        self.assertEqual(self._tab("/status/gaffsie")[1], 2)
        self.assertEqual(self._tab("/status/services")[1], 2)

    def test_a_curve_that_stands_beside_the_node_is_not_counted(self) -> None:
        # One check draws on two nodes beneath its own: each has the one curve that
        # stands on it, the host both.
        self.assertEqual(self._tab("/status/sparks/host")[1], 2)
        self.assertEqual(self._tab("/status/sparks/host/cpu")[1], 1)
        self.assertEqual(self._tab("/status/sparks/host/fan")[1], 1)

    def test_a_view_that_draws_none_has_no_number(self) -> None:
        self.assertEqual(self._tab("/status/services/beat"),
                         ("/series/services/beat", None))

    def test_the_root_counts_every_curve(self) -> None:
        href, count = self._tab("/status")
        self.assertEqual(href, "/series")
        self.assertEqual(count, 11)
        # and from the tree's Copy page, which is a view of the root too
        self.assertEqual(self._tab("/copy"), ("/series", 11))

    def test_the_number_is_on_the_tab_from_every_view_of_the_node(self) -> None:
        for url in ("/status/gaffsie", "/series/gaffsie", "/history/gaffsie",
                    "/copy/gaffsie"):
            with self.subTest(url=url):
                self.assertEqual(self._tab(url)[1], 2)

    def test_it_is_said_in_words_to_a_reader_that_hears_the_page(self) -> None:
        body = self._page("/status/gaffsie")
        self.assertRegex(
            body, r'<span class="ls-views__count">2</span>'
                  r'<span class="visually-hidden"> curves</span>')
        self.assertRegex(
            self._page("/status/lab"),
            r'<span class="ls-views__count">1</span>'
            r'<span class="visually-hidden"> curve</span>')


class LongSeriesSparklineTests(TestCase):
    """A series with more readings than a strip has columns, drawn small."""

    #: Ten hours of a reading a minute that stands at 20, but for one at 90.
    READINGS = 600
    SPIKE = 417

    def setUp(self) -> None:
        check = _Kept(path="/long", series_keep=1000, frequency_seconds=60,
                      measures={"ms": "ms"})
        store = MemoryStore()
        for step in range(self.READINGS):
            store.add(SeriesKey("kept", "/long", "subject"),
                      SeriesRecord({"ms": 90 if step == self.SPIKE else 20},
                                   T0 + timedelta(minutes=step),
                                   code=StatusCode.OK), keep=1000)
        tree = StatusTree()
        tree.upsert("/long", StatusCode.OK, frequency_seconds=60)
        engine = Engine([check], tree, series=store)
        kept = engine.series_near("/long")
        self.measure = next(iter(check.measures.values()))
        self.readings = kept[0].readings
        self.small = curves.draw(self.measure, self.readings, tolerance=120,
                                 small=True)
        self.full = curves.draw(self.measure, self.readings, tolerance=120)

    def test_it_is_drawn_over_the_strips_columns(self) -> None:
        points = [point for run in self.small.runs for point in run]
        # a column draws at most its first, last, lowest and highest reading
        self.assertLessEqual(len(points), 4 * curves.SPARK_COLUMNS)
        self.assertGreater(len(points), curves.SPARK_COLUMNS)
        self.assertLess(len(points),
                        len([point for run in self.full.runs for point in run]))

    def test_no_spike_is_lost(self) -> None:
        def peak(curve: curves.Curve) -> float:
            return min(point.y for run in curve.runs for point in run)
        self.assertEqual(peak(self.small), peak(self.full))
        self.assertLess(peak(self.small), curves.BOTTOM - 0.7 * (curves.BOTTOM
                                                                 - curves.TOP))

    def test_it_stands_on_the_curves_scale_and_reads_as_the_curve_does(self) -> None:
        def level(curve: curves.Curve) -> float:
            return max(point.y for run in curve.runs for point in run)
        self.assertEqual(level(self.small), level(self.full))
        self.assertEqual((self.small.newest, self.small.lowest, self.small.highest),
                         (self.full.newest, self.full.lowest, self.full.highest))
        self.assertEqual((self.small.newest, self.small.lowest, self.small.highest),
                         ("20 ms", "20 ms", "90 ms"))

    def test_it_says_nothing_under_a_pointer_and_has_no_axis(self) -> None:
        self.assertEqual(self.small.hover, ())
        self.assertEqual(self.small.ticks, ())
        self.assertEqual(self.small.time_ticks, ())
        self.assertEqual((self.small.first, self.small.last), ("", ""))
        self.assertTrue(self.full.hover and self.full.ticks)
