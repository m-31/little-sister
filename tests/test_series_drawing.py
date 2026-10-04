"""The Series pages draw only what they show (plan item 0d, backlog #89's B3).

The index says what every node draws and draws none of it; a Series view draws each
curve it shows once; a node's page draws the curves that stand on it and no other —
and each still shows what it showed when it drew them all. The estate is built for
the rules a curve is drawn by (ADR-0096 decisions 2 and 4): a fixed measure and a `*`
over things counted by name, whose keys come in the order they first appear; two
subjects of one check and two checks on one mount; a zero, a boolean, a number that
is not finite, text, a field no reading has and one that only the newest has; numbers
only in readings that failed; a series with no measure, and a check that has kept
nothing yet.
"""
from __future__ import annotations

import re
from collections import Counter
from collections.abc import Callable, Sequence
from datetime import UTC, datetime, timedelta
from typing import Any
from unittest import TestCase, mock

from little_sister import app as app_module
from little_sister import curves as curves_module
from little_sister.checks.base import Check, CheckResult, Measurement
from little_sister.engine import Engine
from little_sister.series import MemoryStore, SeriesKey, SeriesRecord
from little_sister.status import StatusCode
from little_sister.tree import StatusTree

T0 = datetime(2026, 9, 26, 15, 0, tzinfo=UTC)
HOST = "/lab/host"


class _Kept(Check):
    """A check whose readings the test writes into the store the engine reads."""

    type_name = "kept"

    def measure(self) -> Measurement:
        return Measurement(record={})

    def grade(self, measurements: Sequence[Measurement],
              now: datetime) -> CheckResult:
        return CheckResult(StatusCode.OK)


class _Beside(_Kept):
    """The same shape under another type — a second check on the same mount."""

    type_name = "beside"


def _alpha(step: int) -> dict[str, Any]:
    things: dict[str, Any] = {"c": {"n": "many"}, "a": {"n": step}}
    if step >= 2:
        things["b"] = {"n": 2 * step}
    return {"error": None, "load": 0.5 + step, "zero": 0, "flag": bool(step % 2),
            "odd": float("nan") if step % 2 else float("inf"), "word": "high",
            "things": things, **({"late": 7} if step == 4 else {})}


def _beside(step: int) -> dict[str, Any]:
    failed = step % 2 == 0
    return {"load": 1 + step, "failed_only": 3 if failed else None,
            "error": "timed out" if failed else None}


class SeriesDrawingTests(TestCase):
    """What the three pages show, against what drawing every curve showed."""

    def setUp(self) -> None:
        self.tree = StatusTree()
        self._saved = (app_module.status_tree, app_module.engine)
        self.addCleanup(self._restore)
        app_module.status_tree = self.tree
        self.client = app_module.app.test_client()
        self.client.post("/login", data={"username": "pan", "password": "12345678"})
        metrics = _Kept(path=HOST, series_keep=50, frequency_seconds=60, measures={
            "load": "", "zero": "%", "flag": "", "odd": "", "word": "", "absent": "",
            "late": "", "things.*.n": {"unit": "", "label": "N of *",
                                       "node": "things/*"}})
        beside = _Beside(path=HOST, series_keep=50, frequency_seconds=120, measures={
            "load": {"unit": "", "node": "cpu"}, "failed_only": ""})
        quiet = _Kept(path="/lab/quiet", series_keep=20)
        empty = _Kept(path="/lab/empty", series_keep=20, measures={"load": ""})
        site = _Kept(path="/other/site", series_keep=20, measures={"ms": "ms"})
        store = MemoryStore()
        for step in range(5):
            at = T0 + timedelta(minutes=step)
            store.add(SeriesKey("kept", HOST, "alpha"),
                      SeriesRecord(_alpha(step), at, code=StatusCode.OK), keep=50)
            store.add(SeriesKey("beside", HOST, "host"),
                      SeriesRecord(_beside(step), at, code=StatusCode.OK), keep=50)
            store.add(SeriesKey("kept", "/lab/quiet", "beat"),
                      SeriesRecord({"modified": {"at": "2026-09-26T14:00:00Z"}}, at,
                                   code=StatusCode.OK), keep=20)
            store.add(SeriesKey("kept", "/other/site", "https://www.example.org"),
                      SeriesRecord({"ms": 120 + step}, at, code=StatusCode.OK),
                      keep=20)
        store.add(SeriesKey("kept", HOST, "beta"),
                  SeriesRecord({"load": 1, "things": {"d": {"n": 3}}}, T0,
                               code=StatusCode.OK), keep=50)
        app_module.engine = Engine([metrics, beside, quiet, empty, site], self.tree,
                                   series=store)
        for path in (HOST, f"{HOST}/cpu", f"{HOST}/things/a", f"{HOST}/things/b",
                     f"{HOST}/things/c", f"{HOST}/things/d", "/lab/quiet",
                     "/lab/empty", "/other/site"):
            self.tree.upsert(path, StatusCode.OK, frequency_seconds=60)

    def _restore(self) -> None:
        app_module.status_tree, app_module.engine = self._saved

    def _counting(self) -> Callable[[], int]:
        """Count every curve the application draws from here on."""
        drawn = [0]
        real = app_module.draw

        def draw(*args: Any, **kwargs: Any) -> curves_module.Curve:
            drawn[0] += 1
            return real(*args, **kwargs)
        patch = mock.patch.object(app_module, "draw", draw)
        patch.start()
        self.addCleanup(patch.stop)
        return lambda: drawn[0]

    def _get(self, url: str) -> str:
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200, url)
        return response.get_data(as_text=True)

    @staticmethod
    def _labels_drawn(where: str = "/", *, on: str | None = None) -> list[str]:
        """What drawing every curve at or beneath ``where`` finds: the labels, by
        the node each stands on and then by the mount — the reference."""
        assert app_module.engine is not None
        drawn = app_module._drawn(app_module.engine.series_near(where), where=where)
        return [curve.label for path, curves in drawn.items()
                if on is None or path == on for curve, _series in curves]

    # --- the index ---------------------------------------------------------------

    def test_the_index_writes_no_readings_time(self) -> None:
        # It draws every curve small (ADR-0114 decision 1), and a curve's cost is a
        # formatted time for each reading it is drawn over: the index writes none —
        # not through the page's writer, not through the drawing's own.
        with mock.patch.object(app_module, "_times", side_effect=AssertionError), \
                mock.patch.object(curves_module, "local_time",
                                  side_effect=AssertionError):
            body = self._get("/series")
        self.assertIn("lab/host", body)
        self.assertIn('<svg class="ls-spark"', body)

    def test_the_index_lists_what_drawing_every_curve_found(self) -> None:
        assert app_module.engine is not None
        drawn: dict[str, list[str]] = {}
        for curves in app_module._drawn(app_module.engine.series_near("/")).values():
            for curve, series in curves:
                drawn.setdefault(series.check.path.strip("/"), []).append(curve.label)
        with app_module.app.test_request_context("/series"):
            tops = app_module._series_index()
        rows = {row.path: row for top in tops
                for row in (top.own, *top.rows) if row is not None}
        self.assertEqual({path: list(row.labels) for path, row in rows.items()},
                         {path: drawn.get(path, []) for path in rows})
        for path, row in rows.items():
            with self.subTest(path=path):
                self.assertEqual(row.curves,
                                 f"/series/{path}" if drawn.get(path) else "")
                self.assertEqual(row.readings, f"/history/{path}")
        self.assertEqual({top.name: top.curves for top in tops},
                         {"lab": "/series/lab", "other": "/series/other"})

    def test_by_the_rules_a_curve_is_drawn_by(self) -> None:
        with app_module.app.test_request_context("/series"):
            tops = app_module._series_index()
        rows = {row.path: row for top in tops for row in top.rows}
        # a number, a zero, a field only the newest reading has, and each key a `*`
        # finds a number for, per subject — the same label once for every curve;
        # never a boolean, a number that is not finite, text, a field no reading
        # has, a key whose values are text, or a number in a reading that failed
        self.assertEqual(Counter(rows["lab/host"].labels),
                         Counter({"load": 3, "zero": 1, "late": 1, "N of a": 1,
                                  "N of b": 1, "N of d": 1}))
        self.assertEqual(rows["lab/host"].kept, 11)
        self.assertEqual(rows["lab/host"].kinds, ("kept", "beside"))
        # a series that declares no measure offers its History page and no Series view
        self.assertEqual(rows["lab/quiet"].labels, ())
        self.assertEqual((rows["lab/quiet"].curves, rows["lab/quiet"].readings),
                         ("", "/history/lab/quiet"))
        # a check that has kept nothing yet is no row
        self.assertNotIn("lab/empty", rows)
        self.assertEqual(rows["other/site"].labels, ("ms",))

    # --- the Series view and a node's page ---------------------------------------

    def test_a_series_view_draws_each_curve_it_shows_once(self) -> None:
        drawn = self._counting()
        body = self._get(f"/series{HOST}")
        self.assertEqual(drawn(), body.count('<figure class="ls-curve"'))
        self.assertEqual(Counter(self._titles(body)), Counter(self._labels_drawn(HOST)))
        self.assertEqual(len(self._titles(body)), 8)

    def test_a_node_s_page_draws_only_the_curves_that_stand_on_it(self) -> None:
        for url, on, shown in ((f"/status{HOST}", HOST, 4),
                               (f"/status{HOST}?fragment=1", HOST, 4),
                               (f"/status{HOST}/cpu", f"{HOST}/cpu", 1),
                               (f"/status{HOST}/things/c", f"{HOST}/things/c", 0)):
            with self.subTest(url=url):
                drawn = self._counting()
                body = self._get(url)
                self.assertEqual(drawn(), shown)
                self.assertEqual(Counter(self._titles(body)),
                                 Counter(self._labels_drawn(on, on=on)))

    def test_a_page_writes_each_reading_s_time_once(self) -> None:
        # however many curves are drawn over a reading, its hover strips, an axis
        # end, the view's range and its row in a table of readings share one writing
        instants = {T0 + timedelta(minutes=step) for step in range(5)}
        for url, shown in ((f"/series{HOST}", 8), (f"/status{HOST}", 4),
                           (f"/status{HOST}?fragment=1", 4)):
            with self.subTest(url=url):
                body, written = self._written(url)
                self.assertEqual(body.count('<figure class="ls-curve"'), shown)
                self.assertEqual({at: count for at, count in written.items()
                                  if at in instants}, dict.fromkeys(instants, 1))

    def _written(self, url: str) -> tuple[str, Counter[datetime]]:
        """The page at ``url``, and how often it wrote each instant it wrote."""
        written: Counter[datetime] = Counter()
        real = app_module.local_time

        def counting(moment: datetime, fmt: str | None = None) -> str:
            written[moment] += 1
            return real(moment, fmt)
        with mock.patch.object(app_module, "local_time", counting), \
                mock.patch.object(curves_module, "local_time", counting):
            return self._get(url), written

    @staticmethod
    def _titles(body: str) -> list[str]:
        return [re.sub(r"<[^>]+>", "", title) for title in
                re.findall(r'<span class="ls-curve__title">(.*?)</span>', body)]
