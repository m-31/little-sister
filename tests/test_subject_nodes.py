"""A subject with a history has a node of its own, and the node shows its series
(ADR-0106 decisions 1, 2 and 4), read against the record's sentences.

The estate is one check that reads a queue: the queue itself, which is the object the
check declares, and the newest run of each job name in it. Its grading hands back a
node for two of the job names, each with its line on it, beneath a level of their own,
and one node that carries the lines of two others. The engine runs the check, so the
nodes and the series are what three runs leave.

A second check reads functions, for the line that names its node's subject without
carrying one of that subject's readings: each function's newest bucket on every poll,
which is what its line is written from, and in full the runs a poll finds new.
"""
from __future__ import annotations

import html
import re
from collections.abc import Sequence
from dataclasses import replace
from datetime import datetime
from typing import Any
from unittest import TestCase, mock

from little_sister import app as app_module
from little_sister.checks.base import Check, CheckResult, Measurement
from little_sister.engine import Engine
from little_sister.reasons import Entry
from little_sister.status import StatusCode
from little_sister.tree import StatusTree
from tests.test_web import _curves

#: The job names, and how long the first run of each took.
JOBS = {"import": 61, "export": 12, "a": 5, "b": 7}
RUN_TIME = {"seconds": {"unit": "s", "label": "Run time"}}


class _Queue(Check):
    """Reads a queue and the newest run of each job name in it."""

    type_name = "queue"

    def __init__(self, *, measures: dict[str, Any] | None = None,
                 own_on_child: bool = False, flat: bool = False,
                 noted: bool = False, mirrored: bool = False,
                 **kwargs: Any) -> None:
        super().__init__(measure_defaults=measures or {}, **kwargs)
        self.own_on_child = own_on_child
        self.flat = flat
        self.noted = noted
        self.mirrored = mirrored
        self.runs = 0

    def measure(self) -> Sequence[Measurement]:
        self.runs += 1
        return [Measurement(record={"jobs": len(JOBS)}, subject=self.subject,
                            state="open"),
                *(Measurement(record={"job": name, "seconds": seconds + self.runs},
                              subject=f"job/{name}", identity=f"{name}-{self.runs}")
                  for name, seconds in JOBS.items())]

    def grade(self, measurements: Sequence[Measurement],
              now: datetime) -> CheckResult:
        read = {reading.subject: reading for reading in measurements}

        def line(subject: str) -> Entry:
            reading = read[subject]
            return Entry(subject.rpartition("/")[2], f"read {subject}",
                         code=StatusCode.OK, subject=subject,
                         data=dict(reading.record))

        if self.flat:
            # a type that has not moved: every subject's line on the check's own node
            return CheckResult(reason=[line(f"job/{name}") for name in JOBS])
        imported = [line("job/import")]
        if self.noted:
            # a line that names no subject, beside the one that names the job
            imported.append(Entry("note", "queued by the nightly plan",
                                  code=StatusCode.OK))
        children = [
            CheckResult(StatusCode.UNDEFINED, name="nightly", children=(
                CheckResult(name="import", reason=imported,
                            children=(CheckResult(StatusCode.OK, name="timing"),)),
                CheckResult(name="export", reason=[line("job/export")]))),
            CheckResult(name="adhoc", reason=[line("job/a"), line("job/b")])]
        if self.own_on_child:
            children.append(CheckResult(name="state", reason=[line(self.subject)]))
        if self.mirrored:
            # a second node whose line names the same job, earlier in the tree
            children.append(CheckResult(name="mirror", reason=[line("job/import")]))
        return CheckResult(StatusCode.UNDEFINED, children=tuple(children))


#: What two polls of the functions' check read: of each function its newest bucket —
#: its errors and its time — and the runs that poll read in full, each a time and its
#: errors. The second is a quiet poll: the newest buckets again, and no run.
POLLS: tuple[dict[str, tuple[int, str, tuple[tuple[str, int], ...]]], ...] = (
    {"hourly": (0, "2026-10-01T03:00:00+00:00",
                (("2026-10-01T02:00:00+00:00", 0), ("2026-10-01T03:00:00+00:00", 0))),
     "nightly": (2, "2026-10-01T03:00:00+00:00",
                 (("2026-10-01T03:00:00+00:00", 2),))},
    {"hourly": (0, "2026-10-01T03:00:00+00:00", ()),
     "nightly": (2, "2026-10-01T03:00:00+00:00", ())},
)


class _Functions(Check):
    """Reads each function's newest bucket on every poll, and in full the runs a poll
    finds new. The bucket's reading names no subject, so no series keeps it; a run
    names its function, and the instant it ran as its event."""

    type_name = "functions"

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.polls = 0

    def measure(self) -> Sequence[Measurement]:
        poll = POLLS[min(self.polls, len(POLLS) - 1)]
        self.polls += 1
        readings: list[Measurement] = []
        for name, (errors, at, runs) in poll.items():
            readings.append(Measurement(record={
                "kind": "function", "name": name, "errors": errors, "at": at}))
            readings.extend(
                Measurement(record={"kind": "run", "name": name, "at": ran,
                                    "errors": failed},
                            subject=f"function/{name}", identity=ran)
                for ran, failed in runs)
        return readings

    def grade(self, measurements: Sequence[Measurement],
              now: datetime) -> CheckResult:
        def code(errors: int) -> StatusCode:
            return StatusCode.ERROR if errors else StatusCode.OK

        children: list[CheckResult] = []
        for reading in measurements:
            record = reading.record
            if record["kind"] != "function":
                continue
            subject = f"function/{record['name']}"
            # written from the function's own reading, which names no subject, and
            # naming the function all the same
            line = Entry(record["name"],
                         f"{record['errors']} errors in its newest bucket",
                         code=code(record["errors"]), subject=subject,
                         data=dict(record))
            runs = [Entry("run", f"ran with {run.record['errors']} errors",
                          code=code(run.record["errors"]), subject=run.subject,
                          data=dict(run.record))
                    for run in measurements if run.subject == subject]
            children.append(CheckResult(name=record["name"], reason=[line],
                                        for_record=runs))
        return CheckResult(StatusCode.UNDEFINED, children=tuple(children))


def _words(markup: str) -> str:
    return " ".join(html.unescape(re.sub(r"<[^>]+>", " ", markup)).split())


def _kept_of(body: str) -> list[str]:
    """The subjects a History page lists readings of, in the page's order."""
    return [html.unescape(subject) for subject in re.findall(
        r"kept of <code>(.*?)</code>", body)]


def _groups(body: str) -> list[str]:
    """The id of each group of a Series view, in the page's order."""
    return re.findall(r'<section class="card ls-series-group" id="([^"]*)"', body)


def _quiet(body: str) -> list[tuple[str, str]]:
    """Each line of a Series view about readings that draw no curve: what it says,
    and the History page it points at."""
    found = []
    for line in re.findall(r'<p class="[^"]*\bls-series-quiet\b[^"]*">(.*?)</p>',
                           body, re.S):
        link = re.search(r'href="([^"]+)"', line)
        # a name stands in a tag of its own, and what follows it is punctuation
        said = re.sub(r" ([,.])", r"\1", _words(line))
        found.append((said, link.group(1) if link else ""))
    return found


def _index_rows(body: str) -> dict[str, tuple[str, str]]:
    """The Series index, by node: how many readings its row counts, and where its
    *readings* link leads."""
    rows = {}
    for row in re.findall(r"<tr class=\"ls-series-index__(?:top|row)\">(.*?)</tr>",
                          body, re.S):
        node = re.search(r'class="ls-series-index__node" href="[^"]*">([^<]*)</a>',
                         row)
        kept = re.search(r'ls-series-index__kept"[^>]*>(\d*)</td>', row)
        readings = re.search(r'<a href="([^"]*)">readings</a>', row)
        assert node is not None and kept is not None, row
        rows[node.group(1)] = (kept.group(1), readings.group(1) if readings else "")
    return rows


class SubjectNodeTests(TestCase):
    """Where a subject's series is shown, once its line stands on a node of its
    own."""

    def setUp(self) -> None:
        self._saved = (app_module.status_tree, app_module.engine)
        self.addCleanup(self._restore)
        settings = mock.patch(
            "little_sister.config.config",
            replace(app_module.config, timezone="Europe/Berlin",
                    time_format="%Y-%m-%d %H:%M:%S"))
        settings.start()
        self.addCleanup(settings.stop)
        self.client = app_module.app.test_client()
        self.client.post("/login", data={"username": "pan", "password": "12345678"})
        self._deploy()

    def _restore(self) -> None:
        app_module.status_tree, app_module.engine = self._saved

    def _deploy(self, runs: int = 3, **options: Any) -> None:
        self.tree = StatusTree()
        app_module.status_tree = self.tree
        self.check = _Queue(path="/batch", subject="queue/live", series_keep=5,
                            **options)
        app_module.engine = Engine([self.check], self.tree)
        for _ in range(runs):
            app_module.engine.run_once()

    def _get(self, url: str, status: int = 200) -> str:
        response = self.client.get(url)
        self.assertEqual(response.status_code, status, url)
        return response.get_data(as_text=True)

    # --- decision 2: a node stands for the subject its line names ------------------

    def test_a_node_whose_lines_name_one_subject_lists_that_subjects_readings(
            self) -> None:
        body = self._get("/history/batch/nightly/import")
        self.assertEqual(_kept_of(body), ["job/import"])
        # every kept reading of it, one for each run, and no other subject's
        self.assertIn("All 3 readings kept of", _words(body))
        self.assertNotIn("job/export", body)

    def test_the_checks_history_keeps_what_no_node_stands_for(self) -> None:
        # its own object, and the two subjects whose lines share a node; the two
        # that have a node of their own are listed there and not twice
        self.assertEqual(sorted(_kept_of(self._get("/history/batch"))),
                         ["job/a", "job/b", "queue/live"])

    def test_a_node_that_carries_several_subjects_lines_stands_for_none(self) -> None:
        self.assertEqual(_kept_of(self._get("/history/batch/adhoc")), [])

    def test_a_level_above_a_subjects_node_lists_no_readings(self) -> None:
        self.assertEqual(_kept_of(self._get("/history/batch/nightly")), [])

    def test_a_line_that_names_no_subject_names_no_other(self) -> None:
        self._deploy(noted=True)
        self.assertEqual(_kept_of(self._get("/history/batch/nightly/import")),
                         ["job/import"])

    def test_where_two_nodes_name_a_subject_the_first_in_the_tree_stands_for_it(
            self) -> None:
        # siblings stand in the order of their names: `mirror` before `nightly`
        self._deploy(mirrored=True)
        self.assertEqual(_kept_of(self._get("/history/batch/mirror")), ["job/import"])
        self.assertEqual(_kept_of(self._get("/history/batch/nightly/import")), [])

    def test_the_checks_own_subject_stays_on_the_checks_node(self) -> None:
        # the one object the check declares is the check's own node's, wherever a
        # line that names it stands
        self._deploy(own_on_child=True)
        self.assertIn("queue/live", _kept_of(self._get("/history/batch")))
        self.assertEqual(_kept_of(self._get("/history/batch/state")), [])

    def test_a_type_that_has_not_moved_shows_what_it_showed(self) -> None:
        # every subject's line on the check's own node: their readings are on its
        # History page, and their curves on its page
        self._deploy(flat=True, measures=RUN_TIME)
        self.assertEqual(sorted(_kept_of(self._get("/history/batch"))),
                         ["job/a", "job/b", "job/export", "job/import",
                          "queue/live"])
        self.assertEqual(len(_curves(self._get("/status/batch"))), len(JOBS))

    # --- decision 2: a measure names its node from the subject's -------------------

    def test_a_declared_measure_draws_its_curve_on_the_subjects_node(self) -> None:
        self._deploy(measures=RUN_TIME)
        page = self._get("/status/batch/nightly/import")
        self.assertEqual(len(_curves(page)), 1)
        self.assertIn("Run time", page)
        self.assertEqual(len(_curves(self._get("/status/batch/nightly/export"))), 1)
        # the two whose lines share a node keep their curves on the check's own
        self.assertEqual(len(_curves(self._get("/status/batch"))), 2)
        self.assertEqual(len(_curves(self._get("/status/batch/adhoc"))), 0)

    def test_a_measure_that_names_a_node_names_it_from_the_subjects(self) -> None:
        self._deploy(measures={"seconds": {"unit": "s", "label": "Run time",
                                           "node": "timing"}})
        self.assertEqual(
            len(_curves(self._get("/status/batch/nightly/import/timing"))), 1)
        self.assertEqual(len(_curves(self._get("/status/batch/nightly/import"))), 0)
        # the node the measure names has a Series view of its own, for that curve
        self.assertEqual(_groups(self._get("/series/batch/nightly/import/timing")),
                         ["node"])

    # --- decision 4: shown where a node's series is --------------------------------

    def test_the_series_view_groups_a_curve_under_the_subjects_node(self) -> None:
        self._deploy(measures=RUN_TIME)
        body = self._get("/series/batch")
        # the check's own node, then each subject's in the tree's order
        self.assertEqual(_groups(body), ["node", "nightly-export", "nightly-import"])
        # a node one of whose series draws is not named for what draws nothing: the
        # check's own carries two subjects' curves beside its own object's record
        self.assertEqual(_quiet(body), [])
        # the newest readings of a subject's series lead to its own node's History
        self.assertIn('href="/history/batch/nightly/import"', body)
        self.assertIn('href="/history/batch/nightly/export"', body)

    def test_a_subjects_node_has_a_series_view_of_its_own(self) -> None:
        self._deploy(measures=RUN_TIME)
        body = self._get("/series/batch/nightly/import")
        self.assertEqual(_groups(body), ["node"])
        self.assertEqual(len(_curves(body)), 1)
        # and so has the level above it, with both of its subjects' curves
        self.assertEqual(_groups(self._get("/series/batch/nightly")),
                         ["export", "import"])
        # its tab stands on the node's page
        self.assertIn('href="/series/batch/nightly/import"',
                      self._get("/status/batch/nightly/import"))
        # and not on a node no curve stands at or beneath: the two subjects whose
        # lines share `adhoc` keep their curves on the check's own node
        self._get("/series/batch/adhoc", status=404)

    def test_without_a_measure_the_series_view_draws_each_subjects_runs(
            self) -> None:
        # a run is drawn as a mark (ADR-0111): each subject's node has its runs, and
        # the check's own node, none of whose series draws, is named with what it
        # keeps — its own object's one record and the two subjects' whose lines
        # share a node
        body = self._get("/series/batch")
        self.assertEqual(_groups(body), ["nightly-export", "nightly-import"])
        self.assertEqual(
            _quiet(body),
            [("batch keeps 7 readings, 6 of them of job/a and job/b, which have no "
              "node of their own, and draws no curve — they are on its History page.",
              "/history/batch")])

    def test_without_a_measure_a_subjects_node_still_has_a_series_view(self) -> None:
        # with its runs on it, as ticks
        body = self._get("/series/batch/nightly/import")
        self.assertEqual(_groups(body), ["node"])
        self.assertEqual(len(_curves(body)), 1)
        self.assertEqual(_quiet(body), [])
        self.assertIn('href="/series/batch/nightly/import"',
                      self._get("/status/batch/nightly/import"))
        # the level above has both of its subjects' runs
        self.assertEqual(_groups(self._get("/series/batch/nightly")),
                         ["export", "import"])
        # and a node no series is shown at or beneath has none
        self._get("/series/batch/adhoc", status=404)
        self.assertNotIn('href="/series/batch/adhoc"',
                         self._get("/status/batch/adhoc"))

    def test_the_index_has_a_row_for_the_subjects_node(self) -> None:
        rows = _index_rows(self._get("/series"))
        self.assertEqual(rows["batch/nightly/import"],
                         ("3", "/history/batch/nightly/import"))
        self.assertEqual(rows["batch/nightly/export"],
                         ("3", "/history/batch/nightly/export"))
        self.assertEqual(rows["batch"], ("7", "/history/batch"))

    def test_the_index_counts_a_curve_on_the_node_its_series_stands_on(self) -> None:
        self._deploy(measures=RUN_TIME)
        body = self._get("/series")
        row = re.search(r'href="/status/batch/nightly/import">.*?</tr>', body, re.S)
        assert row is not None
        self.assertIn("1 curve", _words(row.group(0)))
        self.assertIn('href="/series/batch/nightly/import"', row.group(0))


class LineWithoutItsReadingTests(TestCase):
    """A line may name its node's subject without carrying one of that subject's
    readings (ADR-0106 decision 2).

    The line a function's node shows is written from the function's newest bucket,
    read on every poll: that reading names no subject, and the line names the
    function. The function's runs are other readings, each written for the record."""

    def setUp(self) -> None:
        self._saved = (app_module.status_tree, app_module.engine)
        self.addCleanup(self._restore)
        self.client = app_module.app.test_client()
        self.client.post("/login", data={"username": "pan", "password": "12345678"})
        self.tree = StatusTree()
        app_module.status_tree = self.tree
        app_module.engine = Engine([_Functions(path="/lambda", series_keep=5)],
                                   self.tree)
        app_module.engine.run_once()        # a poll that read a run of each in full

    def _restore(self) -> None:
        app_module.status_tree, app_module.engine = self._saved

    def _get(self, url: str) -> str:
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200, url)
        return response.get_data(as_text=True)

    def test_the_node_stands_for_the_subject_its_line_names(self) -> None:
        self.assertEqual(_kept_of(self._get("/history/lambda/nightly")),
                         ["function/nightly"])
        self.assertEqual(_kept_of(self._get("/history/lambda/hourly")),
                         ["function/hourly"])

    def test_it_stands_for_it_in_a_poll_that_read_no_run(self) -> None:
        app_module.engine.run_once()        # the quiet poll
        body = self._get("/history/lambda/nightly")
        self.assertEqual(_kept_of(body), ["function/nightly"])
        # with the run the first poll kept, as that poll said it stood
        self.assertIn("ran with 2 errors", _words(body))

    def test_the_lines_own_reading_is_kept_nowhere(self) -> None:
        app_module.engine.run_once()
        # two polls read each function's newest bucket twice: a node lists its
        # function's runs and nothing more, and the check's own page, which lists
        # what no node stands for, lists nothing
        self.assertIn("All 1 reading kept of",
                      _words(self._get("/history/lambda/nightly")))
        self.assertIn("All 2 readings kept of",
                      _words(self._get("/history/lambda/hourly")))
        self.assertEqual(_kept_of(self._get("/history/lambda")), [])
