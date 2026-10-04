"""A node that stands for a subject draws its runs (ADR-0106 decision 5, as ADR-0111
completes it), read against the plan's sentence for the commission: its runs are ticks
on its page and in its Series view, and stems where its check declares a measure, a
failed run in the failure ink and in the lane; and the window, a stretch of the axis
and the line across every curve read them as they read a gauge's curve.

The estate is one check of a queue. It reads the queue — a state — and every run of
two job names its source still lists, and hands back a node for each job name: its
line carries the newest run, and each older run a line for the record alone, but for
one, which so keeps no verdict.
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
from little_sister.reasons import Entry
from little_sister.status import StatusCode
from little_sister.tree import StatusTree
from tests.test_web import _curves

T0 = datetime(2026, 9, 2, 12, 0, tzinfo=UTC)
RUN_TIME = {"seconds": {"unit": "s", "label": "Run time"}}
CODES = {"succeeded": StatusCode.OK, "slow": StatusCode.WARN,
         "failed": StatusCode.ERROR}
#: Each job name's runs: the day it finished on, how long it took, and how it ended —
#: ``unsaid`` for a run its grading says nothing of.
LISTED: dict[str, list[tuple[int, int | None, str]]] = {
    "import": [(0, 600, "unsaid"), (7, 660, "succeeded"), (14, 60, "failed"),
               (21, 4000, "slow"), (28, 720, "succeeded")],
    "export": [(3, 30, "succeeded"), (24, 45, "succeeded")],
}


class _Jobs(Check):
    """Reads a queue and every run of each job name in it."""

    type_name = "jobs"

    def __init__(self, *, measures: dict[str, Any] | None = None,
                 flat: bool = False, **kwargs: Any) -> None:
        super().__init__(measure_defaults=measures or {}, **kwargs)
        self.flat = flat

    def measure(self) -> Sequence[Measurement]:
        readings = [Measurement(record={"jobs": len(LISTED)}, subject=self.subject,
                                state="open")]
        for name, runs in LISTED.items():
            for day, seconds, outcome in runs:
                readings.append(Measurement(
                    record={"job": name, "seconds": seconds, "outcome": outcome,
                            "at": (T0 + timedelta(days=day)).isoformat()},
                    subject=f"job/{name}", identity=f"{name}-{day}"))
        return readings

    def grade(self, measurements: Sequence[Measurement],
              now: datetime) -> CheckResult:
        def line(reading: Measurement) -> Entry:
            record = reading.record
            return Entry(reading.identity, f"{reading.identity} {record['outcome']}",
                         code=CODES[str(record["outcome"])], subject=reading.subject,
                         data=dict(record))

        nodes: list[CheckResult] = []
        shown: list[Entry] = []
        kept: list[Entry] = []
        for name in LISTED:
            *older, newest = [reading for reading in measurements
                              if reading.subject == f"job/{name}"]
            said = [line(reading) for reading in older
                    if reading.record["outcome"] != "unsaid"]
            if self.flat:
                shown.append(line(newest))
                kept.extend(said)
            else:
                nodes.append(CheckResult(name=name, reason=[line(newest)],
                                         for_record=said))
        if self.flat:
            # a type that has not moved: every job name's line on the check's own node
            return CheckResult(reason=shown, for_record=kept)
        return CheckResult(StatusCode.UNDEFINED, children=tuple(nodes))


def _words(markup: str) -> str:
    return " ".join(html.unescape(re.sub(r"<[^>]+>", " ", markup)).split())


def _figures(body: str) -> dict[str, str]:
    """Each plot on the page, whole, by its title."""
    found = {}
    for figure in re.findall(r'<figure class="ls-curve">.*?</figure>', body, re.S):
        title = re.search(r'class="ls-curve__title">([^<]*)<', figure)
        assert title is not None
        found[title.group(1)] = figure
    return found


#: What a plot says beside its title, as markup.
_SAID = re.compile(r'<span class="ls-curve__summary">(.*?)</span>\s*</figcaption>',
                   re.S)


def _summary(figure: str) -> str:
    said = _SAID.search(figure)
    assert said is not None, figure
    return _words(said.group(1))


def _count(figure: str, mark: str) -> int:
    """How many elements of one class a plot draws, its summary's keys left out."""
    plot = re.search(r'<svg class="ls-curve__plot".*?</svg>', figure, re.S)
    assert plot is not None
    return len(re.findall(rf'class="{mark}"', plot.group(0)))


def _stems(figure: str, verdict: str) -> int:
    """How many stems of one verdict a plot draws."""
    path = re.search(rf'class="ls-curve__stem ls-curve__stem--{verdict}" d="([^"]*)"',
                     figure)
    return path.group(1).count("M") if path else 0


class RunPagesTests(TestCase):
    """What a subject's node, its Series view and the index show of its runs."""

    def setUp(self) -> None:
        self._saved = (app_module.status_tree, app_module.engine)
        self.addCleanup(self._restore)
        settings = mock.patch(
            "little_sister.config.config",
            replace(app_module.config, timezone="Europe/Berlin",
                    time_format="%Y-%m-%d %H:%M"))
        settings.start()
        self.addCleanup(settings.stop)
        self.client = app_module.app.test_client()
        self.client.post("/login", data={"username": "pan", "password": "12345678"})
        self._deploy()

    def _restore(self) -> None:
        app_module.status_tree, app_module.engine = self._saved

    def _deploy(self, **options: Any) -> None:
        self.tree = StatusTree()
        app_module.status_tree = self.tree
        check = _Jobs(path="/batch", subject="queue/live", series_keep=10, **options)
        app_module.engine = Engine([check], self.tree)
        app_module.engine.run_once()

    def _get(self, url: str, status: int = 200) -> str:
        response = self.client.get(url)
        self.assertEqual(response.status_code, status, url)
        return response.get_data(as_text=True)

    # --- without a measure, a run is a tick ------------------------------------------

    def test_a_subjects_node_draws_its_runs_as_ticks(self) -> None:
        figures = _figures(self._get("/status/batch/import"))
        self.assertEqual(list(figures), ["Runs"])
        runs = figures["Runs"]
        self.assertEqual({verdict: _stems(runs, verdict) for verdict in
                          ("unjudged", "passed", "warned", "failed")},
                         {"unjudged": 1, "passed": 2, "warned": 1, "failed": 1})
        # a hollow ring for the run that failed, the triangle for the one that warned,
        # and no head on a tick that passed or kept no verdict
        self.assertEqual((_count(runs, "ls-curve__failed"),
                          _count(runs, "ls-curve__warned"),
                          _count(runs, "ls-curve__dot")), (1, 1, 0))

    def test_no_line_joins_two_runs_and_no_lane_marks_a_tick(self) -> None:
        runs = _figures(self._get("/status/batch/import"))["Runs"]
        self.assertEqual((_count(runs, "ls-curve__line"),
                          _count(runs, "ls-curve__none")), (0, 0))

    def test_the_summary_counts_the_runs_and_what_did_not_pass_by_kind(self) -> None:
        runs = _figures(self._get("/status/batch/import"))["Runs"]
        self.assertEqual(_summary(runs),
                         "5 runs · 1 failed · 1 warned · 1 without a verdict")
        # a kind no run is of is left out
        self.assertEqual(_summary(_figures(self._get("/status/batch/export"))["Runs"]),
                         "2 runs")

    def test_each_kind_is_counted_with_its_mark_as_the_key(self) -> None:
        said = _SAID.search(_figures(self._get("/status/batch/import"))["Runs"])
        assert said is not None
        keys = re.findall(r'<span class="ls-curve__key"><svg[^>]*>(.*?)</svg>([^<]*)',
                          said.group(1), re.S)
        self.assertEqual([(re.search(r'class="([^"]*)"', mark).group(1),  # type: ignore[union-attr]
                           words.strip()) for mark, words in keys],
                         [("ls-curve__failed", "1 failed"),
                          ("ls-curve__warned", "1 warned"),
                          ("ls-curve__stem ls-curve__stem--unjudged",
                           "1 without a verdict")])

    def test_the_plot_is_named_by_its_runs(self) -> None:
        runs = _figures(self._get("/status/batch/import"))["Runs"]
        self.assertIn('aria-label="Runs, 5 runs from 2026-09-02 14:00 to '
                      '2026-09-30 14:00"', runs)

    def test_a_run_says_how_it_stood_under_the_pointer(self) -> None:
        runs = _figures(self._get("/status/batch/import"))["Runs"]
        self.assertEqual(re.findall(r"<title>([^<]*)</title>", runs), [
            "2026-09-02 14:00 · no verdict", "2026-09-09 14:00 · passed",
            "2026-09-16 14:00 · failed", "2026-09-23 14:00 · warned",
            "2026-09-30 14:00 · passed"])

    # --- with a measure, a run is a stem to its value --------------------------------

    def test_with_a_measure_its_runs_are_stems_to_their_values(self) -> None:
        self._deploy(measures=RUN_TIME)
        figures = _figures(self._get("/status/batch/import"))
        # the measure's plot, and no ticks beside it
        self.assertEqual(list(figures), ["Run time"])
        stems = figures["Run time"]
        self.assertEqual({verdict: _stems(stems, verdict) for verdict in
                          ("unjudged", "passed", "warned", "failed")},
                         {"unjudged": 1, "passed": 2, "warned": 1, "failed": 1})
        # every run that kept a verdict has a head, and the one that failed a mark
        # in the lane as well
        self.assertEqual((_count(stems, "ls-curve__dot"),
                          _count(stems, "ls-curve__warned"),
                          _count(stems, "ls-curve__failed"),
                          _count(stems, "ls-curve__none")), (2, 1, 1, 1))
        self.assertEqual(_count(stems, "ls-curve__line"), 0)

    def test_its_summary_says_the_three_values_over_every_run(self) -> None:
        self._deploy(measures=RUN_TIME)
        stems = _figures(self._get("/status/batch/import"))["Run time"]
        # the lowest is the run that failed after a minute
        self.assertEqual(_summary(stems),
                         "5 runs · newest 12m · lowest 1m · highest 1h 6m · 1 failed "
                         "· 1 warned · 1 without a verdict")
        self.assertIn('aria-label="Run time, 5 runs from ', stems)

    # --- where a run is drawn, and where it is not -----------------------------------

    def test_a_series_no_node_stands_for_draws_no_ticks(self) -> None:
        # a type that has not moved its lines shows what it showed: its readings on
        # its History page, and no plot
        self._deploy(flat=True)
        self.assertEqual(_curves(self._get("/status/batch")), [])
        body = self._get("/series/batch")
        self.assertIn("No curves to display.", body)
        # and it says whose they are: the queue's own one, and each job name's,
        # neither of which has a node
        said = re.sub(r" ([,.])", r"\1", _words(body))
        self.assertIn(
            "batch keeps 8 readings, 7 of them of job/export and job/import, which "
            "have no node of their own, and draws no curve", said)

    def test_a_type_that_has_not_moved_draws_its_measure_as_stems(self) -> None:
        # where its curves stood, on the check's own node
        self._deploy(flat=True, measures=RUN_TIME)
        plots = _curves(self._get("/status/batch"))
        self.assertEqual(len(plots), len(LISTED))
        self.assertTrue(all('class="ls-curve__stem ' in plot for plot in plots))
        self.assertFalse(any('class="ls-curve__line"' in plot for plot in plots))

    def test_a_measure_no_run_gives_a_number_leaves_its_runs_as_ticks(self) -> None:
        # the check declares a measure and these runs carry no such field: the
        # subject's node draws what it would draw without one
        self._deploy(measures={"bytes": {"unit": "B", "label": "Output"}})
        self.assertEqual(list(_figures(self._get("/status/batch/import"))), ["Runs"])

    def test_a_record_with_a_state_is_no_run(self) -> None:
        # the queue's own reading names the state it is in: its node draws nothing,
        # and its Series view says where its one reading is
        self.assertEqual(_curves(self._get("/status/batch")), [])
        said = _words(self._get("/series/batch"))
        self.assertIn("batch keeps 1 reading and draws no curve", said)
        self.assertNotIn("batch/import keeps", said)

    def test_the_series_view_puts_each_subjects_runs_under_its_node(self) -> None:
        body = self._get("/series/batch")
        self.assertEqual(
            re.findall(r'<section class="card ls-series-group" id="([^"]*)"', body),
            ["export", "import"])
        self.assertEqual(len(_curves(body)), 2)
        # on one time axis: the job with two runs is drawn over the other's window
        export = _figures(self._get("/series/batch/export"))["Runs"]
        self.assertIn("from 2026-09-05 14:00 to 2026-09-26 14:00", export)
        both = re.findall(r'aria-label="Runs, \d+ runs from ([^"]*)"', body)
        self.assertEqual(both, ["2026-09-02 14:00 to 2026-09-30 14:00"] * 2)

    def test_a_window_without_runs_says_so(self) -> None:
        body = self._get("/series/batch/import?from=2026-08-01T00:00:00Z"
                         "&to=2026-08-02T00:00:00Z")
        self.assertEqual(_summary(_figures(body)["Runs"]), "no runs in this window")

    def test_a_window_counts_the_runs_it_holds(self) -> None:
        body = self._get("/series/batch/import?from=2026-09-10T00:00:00Z"
                         "&to=2026-09-25T00:00:00Z")
        self.assertEqual(_summary(_figures(body)["Runs"]),
                         "2 runs · 1 failed · 1 warned")

    def test_the_index_counts_a_subjects_runs_as_a_curve(self) -> None:
        body = self._get("/series")
        row = re.search(r'href="/status/batch/import">.*?</tr>', body, re.S)
        assert row is not None
        self.assertIn("1 curve Runs", _words(row.group(0)))
        self.assertIn('href="/series/batch/import"', row.group(0))

    def test_the_nodes_page_leads_to_its_own_series_view_and_history(self) -> None:
        page = self._get("/status/batch/import")
        card = re.search(r'<div class="card mb-3 ls-series">.*?</p>', page, re.S)
        assert card is not None
        self.assertIn('href="/series/batch/import#node"', card.group(0))
        self.assertIn('href="/history/batch/import"', card.group(0))
        self.assertNotIn('href="/history/batch"', card.group(0))
