"""Gate coverage for the live demo (testing-the-gui.md, Mode 2).

The scenario functions are pure ``(elapsed, period) -> CheckResult``, so they are
tested directly at chosen points of the cycle; the config directory is loaded
through the real loaders — checks, settings, nodes and actions — to prove the demo
tree wires up. That last part earns its keep: the demo is the only place several of
these aspects are exercised together, and a demo that has quietly stopped
demonstrating something is worse than one that never did, because nobody re-reads a
harness they believe works.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import textwrap
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest import TestCase, mock

from little_sister import self_report, slots
from little_sister.actions import PLACEMENTS, load_actions
from little_sister.checks import load_checks
from little_sister.checks.base import (
    CheckError,
    CheckResult,
    Measurement,
    parse_duration,
)
from little_sister.config import load_config
from little_sister.engine import Engine
from little_sister.links import load_links
from little_sister.nodes import NodeMeta, load_nodes, resolve_metadata
from little_sister.reasons import DERIVED_PREFIX, Entry
from little_sister.status import (
    HEARTBEAT_PATH,
    StatusCode,
    effective_code,
    join_path,
    on_same_line,
    split_path,
)
from little_sister.titles import shown_title
from little_sister.tree import StatusTree
from tests.demo_check import SCENARIOS, DemoCheck
from tests.demo_extension import REASON_BUDGET, review_action
from tests.running import run_check, subprocess_env

_DEMO_CONFIG_DIR = Path(__file__).resolve().parent / "demo_config"
_REPO_ROOT = Path(__file__).resolve().parent.parent
_DEMO_PACKAGE = "tests.demo_extension"


class DemoScenarioTests(TestCase):
    def _codes_over_cycle(self, name: str, period: float = 60.0,
                          samples: int = 24) -> list[StatusCode]:
        fn = SCENARIOS[name]
        return [fn((i / samples) * period, period).code for i in range(samples)]

    def test_escalate_cycles_ok_warn_error_then_recovers(self):
        codes = self._codes_over_cycle("escalate")
        self.assertIn(StatusCode.OK, codes)
        self.assertIn(StatusCode.WARN, codes)
        self.assertIn(StatusCode.ERROR, codes)
        self.assertEqual(SCENARIOS["escalate"](0.95 * 60, 60).code, StatusCode.OK)

    def test_escalate_reason_list_grows(self):
        early = SCENARIOS["escalate"](0.55 * 60, 60)
        late = SCENARIOS["escalate"](0.85 * 60, 60)
        self.assertEqual(early.code, StatusCode.ERROR)
        self.assertEqual(late.code, StatusCode.ERROR)
        self.assertLess(len(early.reason), len(late.reason))

    def test_eruption_blows_up_to_twelve_links(self):
        erupt = SCENARIOS["eruption"](0.8 * 60, 60)
        self.assertEqual(erupt.code, StatusCode.ERROR)
        self.assertEqual(len(erupt.reason), 12)
        self.assertTrue(all("https://" in r for r in erupt.reason))
        self.assertEqual(SCENARIOS["eruption"](0.1 * 60, 60).code, StatusCode.OK)

    def test_flap_toggles_within_the_period(self):
        self.assertEqual(SCENARIOS["flap"](0.0, 20).code, StatusCode.OK)
        self.assertEqual(SCENARIOS["flap"](15.0, 20).code, StatusCode.ERROR)

    def test_silent_drops_the_cache_child_midcycle(self):
        present = {c.name for c in SCENARIOS["silent"](0.1 * 90, 90).children}
        self.assertEqual(present, {"db", "cache"})
        silent = {c.name for c in SCENARIOS["silent"](0.5 * 90, 90).children}
        self.assertEqual(silent, {"db"})            # cache fell silent → will go stale

    def test_children_reports_a_named_subtree(self):
        result = SCENARIOS["children"](0.65 * 45, 45)
        self.assertEqual({c.name for c in result.children},
                         {"disk", "memory", "load"})

    def test_audit_swells_to_150_findings_while_staying_ok(self):
        early = SCENARIOS["audit"](0.0, 120)
        late = SCENARIOS["audit"](0.89 * 120, 120)
        self.assertEqual(early.code, StatusCode.OK)
        self.assertEqual(late.code, StatusCode.OK)   # never leaves OK — that
        self.assertLessEqual(len(early.reason), 10)  # is the point
        self.assertGreater(len(late.reason), 140)

    def test_audit_clears_at_the_end_of_the_cycle(self):
        cleared = SCENARIOS["audit"](0.95 * 120, 120)
        self.assertEqual(cleared.code, StatusCode.OK)
        self.assertFalse(cleared.reason)             # findings list is gone

    def test_severity_bands_declare_a_rank_and_no_band_repeats_its_name(self):
        # The demo's ADR-0055 card, and the guard that keeps it demonstrating what
        # its YAML claims: rank order (not alphabetical), and a title on every band
        # that the surfaces are supposed to swallow.
        result = SCENARIOS["severity"](0.0, 100)
        by_rank = sorted(result.children, key=lambda c: (c.order, c.name))
        self.assertEqual([c.name for c in by_rank],
                         ["critical", "high", "medium", "low", "informational"])
        # Alphabetical is genuinely different, or the fixture proves nothing.
        self.assertNotEqual([c.name for c in by_rank],
                            sorted(c.name for c in result.children))
        # The titles are declared now, not stamped (ADR-0025), so read them where
        # they live — on the check, resolved. Reading
        # the result's empty `title` would still pass and prove nothing.
        check = DemoCheck.from_config(
            {"type": "demo", "path": "/security/posture", "scenario": "severity"},
            Path("."))
        for child in result.children:
            with self.subTest(band=child.name):
                declared = check.subnode_labels[child.name]["title"]
                self.assertEqual(declared, child.name.capitalize())
                self.assertEqual(shown_title(child.name, declared), "")
                self.assertTrue(check.subnode_labels[child.name]["about"])

    def test_severity_climbs_and_clears_without_reordering(self):
        # The root declares OK and the bands carry the news, so read the children:
        # what the card shows is the tree's roll-up of these.
        worst = [effective_code(StatusCode.OK,
                                [c.code for c in
                                 SCENARIOS["severity"]((i / 20) * 100, 100).children])
                 for i in range(20)]
        self.assertIn(StatusCode.OK, worst)
        self.assertIn(StatusCode.WARN, worst)
        self.assertIn(StatusCode.ERROR, worst)
        # …and the ranks are a property of the band, never of what it reports now,
        # so the row the colors travel along never re-sorts.
        ranks = {tuple((c.name, c.order) for c in
                       SCENARIOS["severity"]((i / 20) * 100, 100).children)
                 for i in range(20)}
        self.assertEqual(len(ranks), 1)

    def test_informational_never_alarms_however_many_lines_it_carries(self):
        for moment in (0.0, 40.0, 99.0):
            with self.subTest(moment=moment):
                bands = {c.name: c for c in SCENARIOS["severity"](moment, 100).children}
                self.assertTrue(bands["informational"].reason)
                self.assertEqual(bands["informational"].code, StatusCode.OK)

    def test_exactly_one_band_declines_the_density_trade(self):
        # The demo's ADR-0063 node: `informational` is the band whose lines are
        # read *because* nothing is wrong, so it keeps its box while the other
        # four chip. The flag is **declared** beside that band's label now, so it
        # is read off the check — a band this type can name is not a child a run
        # discovered, and reading the result would be testing the channel this
        # deliberately stopped using. It must carry lines in every phase, or the
        # box is empty and there is nothing to look at; and its siblings must stay
        # silent on the field, or the card demonstrates a wall rather than a
        # declaration.
        check = DemoCheck.from_config(
            {"type": "demo", "path": "/security/wiz", "scenario": "severity"},
            Path("."))
        self.assertEqual(check.subnode_show_when_quiet, {"informational": True})
        for moment in (0.0, 40.0, 99.0):
            with self.subTest(moment=moment):
                bands = {c.name: c
                         for c in SCENARIOS["severity"](moment, 100).children}
                self.assertTrue(bands["informational"].reason)
                for band in bands.values():
                    # nothing is stamped: every one of these names is declared
                    self.assertIsNone(band.show_when_quiet)


class ReviewsScenarioTests(TestCase):
    """The demo's **declared-slug** member producer (ADR-0036 decision 4)."""

    _PERIOD = 90.0

    def _at(self, fraction: float) -> CheckResult:
        return SCENARIOS["reviews"](fraction * self._PERIOD, self._PERIOD)

    def _slugs(self, fraction: float) -> set[str]:
        return {entry.slug for entry in self._at(fraction).reason_entries}

    @staticmethod
    def _derived(texts) -> dict[str, str]:
        """The same lines keyed the other way — a *derived* slug per text."""
        keyed = CheckResult(StatusCode.WARN, list(texts), entries=True)
        return {entry.slug: entry.text for entry in keyed.reason_entries}

    def test_the_queue_is_never_empty(self):
        # A per-line control that vanishes between polls is not clickable, which is
        # the whole reason this node exists beside the audit leaf.
        for step in range(24):
            result = self._at(step / 24)
            self.assertEqual(result.code, StatusCode.WARN)
            self.assertGreaterEqual(len(result.reason_entries), 4)

    def test_its_entries_are_members_with_declared_slugs(self):
        result = self._at(0.1)
        self.assertTrue(result.members)
        self.assertIn("pr-4833", {e.slug for e in result.reason_entries})
        self.assertFalse([e for e in result.reason_entries
                          if e.slug.startswith(DERIVED_PREFIX)])

    def test_a_declared_slug_survives_its_line_being_reworded(self):
        """The identity claim, and the reason the scenario re-words at all.

        A pin names a slug. Here the text is rebuilt with a new waiting time every
        run while the key stays put, so a pin set early is still on the same entry
        later. The second half is the contrast that makes the first half mean
        something: hand the *same two lists* over as prose-with-``entries``, where
        the slug is a hash of the text, and the surviving keys are **exactly** the
        lines that did not move — which is the rule stated precisely. A derived slug
        *is* the wording, no more and no less, so the review waiting on its author
        (it quotes no clock) keeps its key while every line counting hours loses it.
        """
        early = {e.slug: e.text for e in self._at(0.0).reason_entries}
        late = {e.slug: e.text for e in self._at(0.5).reason_entries}
        self.assertIn("pr-4833", early)
        self.assertIn("pr-4833", late)
        self.assertNotEqual(early["pr-4833"], late["pr-4833"])
        derived_early = self._derived(early.values())
        derived_late = self._derived(late.values())
        survived = {derived_early[slug]
                    for slug in set(derived_early) & set(derived_late)}
        self.assertEqual(survived, set(early.values()) & set(late.values()))
        self.assertNotIn(early["pr-4833"], survived)

    def test_the_set_churns_within_one_cycle(self):
        # one entry is merged near the end, another opens mid-cycle — so an entry
        # pin can be watched through both arrival and departure.
        self.assertIn("pr-4846", self._slugs(0.1))
        self.assertNotIn("pr-4846", self._slugs(0.9))
        self.assertNotIn("pr-4852", self._slugs(0.1))
        self.assertIn("pr-4852", self._slugs(0.9))

    def test_it_is_small_enough_to_pin_every_member(self):
        # pinning all of them is how the maintenance-index gap (plan 5b item 1) is
        # reproduced by hand: `_own_code` reads MAINTENANCE, `/maintenance` does not
        # yet say so. That is only a demo if the clicking is finishable.
        for step in range(12):
            self.assertLessEqual(len(self._at(step / 12).reason_entries), 8)


class EntriesKnobTests(TestCase):
    """``entries: true`` in a check config — the same node read both ways."""

    def _audit(self, fraction: float) -> CheckResult:
        return SCENARIOS["audit"](fraction * 120, 120)

    def test_off_by_default(self):
        check = DemoCheck(path="/x", scenario="audit", period=120.0)
        self.assertFalse(check.entries)
        self.assertFalse(run_check(check).members)
        self.assertNotIn("entries", check.config_summary())

    def test_it_turns_a_prose_scenario_into_members(self):
        check = DemoCheck(path="/x", scenario="audit", period=120.0, entries=True)
        result = run_check(check)
        self.assertTrue(result.members)
        self.assertTrue(all(e.slug.startswith(DERIVED_PREFIX)
                            for e in result.reason_entries))
        self.assertIn("entries", check.config_summary())

    def test_it_leaves_a_mapping_scenario_alone(self):
        # `reviews` already said it in the stronger form; the knob cannot add to it
        # and must not re-key it.
        keyed = DemoCheck(path="/x", scenario="reviews", period=90.0, entries=True)
        self.assertTrue(run_check(keyed).members)
        self.assertFalse([e for e in run_check(keyed).reason_entries
                          if e.slug.startswith(DERIVED_PREFIX)])

    def test_it_is_read_from_the_config(self):
        check = DemoCheck.from_config(
            {"type": "demo", "path": "/x", "scenario": "audit", "entries": True},
            Path("."))
        self.assertTrue(check.entries)

    def test_the_audit_findings_keep_their_derived_slugs_as_the_list_grows(self):
        """The ergonomic claim from the other side: return a stable string and
        per-entry pins just work. Nothing in this scenario's data changes — only the
        *count* — so every slug the early list produced is still there, in order,
        when the list has swollen to ~130."""
        early = replace(self._audit(0.05), entries=True)
        late = replace(self._audit(0.8), entries=True)
        early_slugs = [e.slug for e in early.reason_entries]
        late_slugs = [e.slug for e in late.reason_entries]
        self.assertLess(len(early_slugs), len(late_slugs))
        self.assertEqual(late_slugs[:len(early_slugs)], early_slugs)


class PipelinesRecordTests(TestCase):
    """The build line of ``pipelines`` carries its run's record: the demo's one
    line whose own times the leaf page reads in the configured timezone
    (testing-the-gui.md, Mode 2). Its times are counted from the reading's, and
    they reach the tree the way any check's do — through the seam, in UTC."""

    def _build(self, fraction: float) -> Entry:
        check = DemoCheck(path="/ci/pipelines", scenario="pipelines", period=60.0)
        # a reading taken at 10:38 in a zone two hours east of UTC
        read = Measurement(record={"elapsed_seconds": fraction * 60,
                                   "period_seconds": 60.0,
                                   "at": "2026-09-22T10:38:00+02:00"})
        result = run_check(check, measurements=[read])
        return next(e for e in result.reason_entries if e.slug == "web-build")

    def test_a_run_in_flight_carries_its_start_and_no_end(self):
        # fifteen seconds into the retry: the text says so, and the record says
        # when that was, beside the run the build last completed
        build = self._build(0.75)
        self.assertIn("#4217 running 15s", build.text)
        self.assertEqual(build.data, {
            "workflow": "build", "branch": "main", "run_number": 4216,
            "completed": {"at": "2026-09-22T08:37:36Z"},
            "running": {"run_number": 4217, "started": "2026-09-22T08:37:45Z",
                        "ended": None}})

    def test_a_finished_run_carries_when_it_completed(self):
        build = self._build(0.9)
        self.assertEqual(build.data, {
            "workflow": "build", "branch": "main", "run_number": 4217,
            "completed": {"at": "2026-09-22T08:37:54Z"}})

    def test_the_other_lines_carry_none(self):
        check = DemoCheck(path="/ci/pipelines", scenario="pipelines", period=60.0)
        result = run_check(check)
        self.assertEqual([e.slug for e in result.reason_entries if e.data],
                         ["web-build"])


class LatencyScenarioTests(TestCase):
    """The ``latency`` scenario records what ``http`` does (ADR-0092): its node
    stands for a site and shows the series its check keeps — the demo's one curve
    (testing-the-gui.md, Mode 2), with a marked break, a plain one and the noise
    between on every cycle."""

    def _check(self) -> DemoCheck:
        check, = (check for check in load_checks(_DEMO_CONFIG_DIR)
                  if check.path == "/services/web")
        assert isinstance(check, DemoCheck)
        return check

    def test_it_stands_for_its_site_and_draws_its_response_time(self):
        check = self._check()
        self.assertEqual(check.subject, "https://www.example.org")
        self.assertGreater(check.series_keep, 0)
        self.assertEqual(check.measures["response_ms"].unit, "ms")
        self.assertEqual(check.measures["response_ms"].label, "Response time")

    def test_it_is_graded_as_http_grades_an_answer(self):
        check = self._check()
        failed = run_check(check, measurements=[Measurement(record={
            "status": None, "response_ms": None, "error": "timed out"})])
        self.assertEqual(failed.code, StatusCode.ERROR)
        self.assertEqual(failed.reason_texts, ["request failed: timed out"])
        answered = run_check(check, measurements=[Measurement(record={
            "status": 200, "response_ms": 212})])
        self.assertEqual(answered.code, StatusCode.OK)
        self.assertEqual(answered.reason_texts, ["HTTP 200 in 212 ms"])

    def test_its_cycle_fails_hangs_and_answers(self):
        # the three things the curve tells apart, where the cycle puts them
        check = self._check()
        with mock.patch("tests.demo_check.time") as clock:
            clock.monotonic.return_value = check._start + 0.33 * check._period
            self.assertIsNone(check.measure().record["response_ms"])
            clock.monotonic.return_value = check._start + 0.10 * check._period
            self.assertIsInstance(check.measure().record["response_ms"], int)
            clock.sleep.assert_not_called()
            clock.monotonic.return_value = check._start + 0.61 * check._period
            check.measure()
            clock.sleep.assert_called_once_with(45.0)


class WorkflowsScenarioTests(TestCase):
    """The ``workflows`` scenario reads three repositories in one run, and twice a
    cycle one repository's answer breaks the seam (ADR-0093): the demo's live look
    at a record that costs its reading and nothing else."""

    def setUp(self) -> None:
        self_report.runtime.forget()
        self.addCleanup(self_report.runtime.forget)

    def _check(self) -> DemoCheck:
        check, = (check for check in load_checks(_DEMO_CONFIG_DIR)
                  if check.path == "/ci/workflows")
        assert isinstance(check, DemoCheck)
        return check

    def test_outside_the_two_stretches_every_repository_is_graded(self):
        check = self._check()
        with mock.patch("tests.demo_check.time") as clock:
            clock.monotonic.return_value = check._start + 0.10 * check._period
            readings = check.measure()
        assert not isinstance(readings, Measurement)
        self.assertEqual([reading.subject for reading in readings],
                         ["octo/api", "octo/web", "octo/docs"])
        result = run_check(check, measurements=readings)
        self.assertEqual(result.stored_code, StatusCode.OK)
        self.assertEqual([entry.subject for entry in result.reason_entries],
                         ["octo/api", "octo/web", "octo/docs"])

    def test_outside_a_run_each_refusal_raises_where_the_record_is_built(self):
        # what the type's own tests would meet: the seam is strict by default
        check = self._check()
        for phase in (0.30, 0.70):
            with self.subTest(phase=phase), \
                    mock.patch("tests.demo_check.time") as clock:
                clock.monotonic.return_value = check._start + phase * check._period
                with self.assertRaises(CheckError):
                    check.measure()

    def test_in_a_run_each_refusal_costs_its_reading_and_nothing_else(self):
        # where both stretches overlap, two readings are refused and the third
        # is graded alone
        check = self._check()
        tree = StatusTree()
        engine = Engine([check], tree)
        with mock.patch("tests.demo_check.time") as clock:
            clock.monotonic.return_value = check._start + 0.50 * check._period
            engine.run_once()
        node = tree.snapshot("/ci/workflows")
        assert node is not None
        self.assertEqual(node.reported_code, StatusCode.WARN)
        self.assertEqual([line.slug for line in node.reasons],
                         ["refused-octo-web", "refused-octo-docs", "octo-api-ci"])
        info, = engine.info().checks
        self.assertTrue(info.record_refused)
        self.assertEqual(len([line for line in self_report.runtime.lines()
                              if "/ci/workflows" in line.text]), 2)


class RunsScenarioTests(TestCase):
    """The ``runs`` scenario is the demo's subject with a history (ADR-0106,
    ADR-0111): four job names, each a node of its own, each run a reading with an
    identity — and the one place the demo shows a line written for the record
    alone, and what a run keeps without one. One of the four comes and goes
    beneath a node that says its children are complete (ADR-0109)."""

    #: The wall clock the scenario reads: a moment between two runs of every job,
    #: in a stretch in which `backfill` runs — its fifth run of six.
    NOW = 1_790_000_010.0
    #: Two of `backfill`'s intervals on it does not run, and five on it runs again.
    GONE, BACK = NOW + 40, NOW + 100

    def _check(self) -> DemoCheck:
        check, = (check for check in load_checks(_DEMO_CONFIG_DIR)
                  if check.path == "/ci/jobs")
        assert isinstance(check, DemoCheck)
        return check

    def _read(self, check: DemoCheck, now: float | None = None) -> list[Measurement]:
        with mock.patch("tests.demo_check.time") as clock:
            clock.time.return_value = self.NOW if now is None else now
            readings = check.measure()
        assert not isinstance(readings, Measurement)
        return list(readings)

    def test_it_reads_every_listed_run_of_each_job_name(self):
        readings = self._read(self._check())
        by_job: dict[str, list[Measurement]] = {}
        for reading in readings:
            by_job.setdefault(reading.subject, []).append(reading)
        self.assertEqual({subject: len(runs) for subject, runs in by_job.items()},
                         {"jobs/import": 6, "jobs/export": 6, "jobs/cleanup": 6,
                          "jobs/backfill": 6})
        # each names the run it is of, and no two the same
        self.assertEqual(len({reading.identity for reading in readings}), 24)
        self.assertTrue(all(reading.identity for reading in readings))

    def test_a_run_finishes_on_the_wall_clock_so_a_restart_finds_it_again(self):
        check = self._check()
        first = {reading.identity: reading.record for reading in self._read(check)}
        # another check, built later, reads the same runs at the same moment
        again = {reading.identity: reading.record
                 for reading in self._read(self._check())}
        self.assertEqual(first, again)
        # and a poll five seconds on reads them again, before any job has run anew
        later = {reading.identity for reading in self._read(check, self.NOW + 5)}
        self.assertEqual(later, set(first))

    def test_a_job_that_says_its_run_time_is_drawn_by_it_and_cleanup_is_not(self):
        check = self._check()
        self.assertGreater(check.series_keep, 0)
        self.assertEqual(check.measures["seconds"].label, "Run time")
        for reading in self._read(check):
            with self.subTest(run=reading.identity):
                self.assertEqual("seconds" in reading.record,
                                 reading.subject in ("jobs/import", "jobs/export"))

    def test_each_job_name_is_a_node_whose_line_carries_its_newest_run(self):
        check = self._check()
        readings = self._read(check)
        result = run_check(check, measurements=readings)
        self.assertEqual([child.name for child in result.children],
                         ["import", "export", "cleanup", "backfill"])
        for child in result.children:
            with self.subTest(job=child.name):
                newest = [reading for reading in readings
                          if reading.subject == f"jobs/{child.name}"][-1]
                line, = child.reason_entries
                self.assertEqual((line.subject, line.data),
                                 (newest.subject, dict(newest.record)))

    def test_three_job_names_say_how_each_listed_run_stood_and_cleanup_does_not(
            self):
        check = self._check()
        result = run_check(check, measurements=self._read(check))
        self.assertEqual({child.name: len(child.for_record)
                          for child in result.children},
                         {"import": 5, "export": 5, "cleanup": 0, "backfill": 5})

    # ----- the job name that comes and goes (ADR-0109) -----

    def test_the_node_above_the_job_names_says_that_they_are_all_of_them(self):
        check = self._check()
        result = run_check(check, measurements=self._read(check))
        self.assertTrue(result.children_complete)
        self.assertFalse(any(child.children_complete for child in result.children))

    def test_a_job_name_that_is_not_running_is_not_listed(self):
        check = self._check()
        readings = self._read(check, self.GONE)
        self.assertEqual({reading.subject for reading in readings},
                         {"jobs/import", "jobs/export", "jobs/cleanup"})
        result = run_check(check, measurements=readings)
        self.assertEqual([child.name for child in result.children],
                         ["import", "export", "cleanup"])
        self.assertTrue(result.children_complete)

    def test_listed_again_its_newest_runs_reach_into_its_last_stretch(self):
        check = self._check()
        before = [reading.identity for reading in self._read(check)
                  if reading.subject == "jobs/backfill"]
        after = [reading.identity for reading in self._read(check, self.BACK)
                 if reading.subject == "jobs/backfill"]
        # six runs each time, oldest first; none of the three it did not run
        self.assertEqual((len(before), len(after)), (6, 6))
        self.assertEqual(before[-1], "backfill-89500000")
        self.assertEqual(after, [*before[-4:], "backfill-89500001",
                                 "backfill-89500005"])

    def test_in_the_engine_its_node_is_removed_and_returns_with_its_runs(self):
        check = self._check()
        tree = StatusTree()
        engine = Engine([check], tree)

        def run(now: float) -> list[str]:
            with mock.patch("tests.demo_check.time") as clock:
                clock.time.return_value = now
                engine.run_once()
            node = tree.snapshot("/ci/jobs")
            assert node is not None
            return [child.name for child in node.children]

        def kept() -> list[str]:
            series, = (series for series in engine.series_near("/ci/jobs")
                       if series.subject == "jobs/backfill")
            return [str(placed.record.identity) for placed in series.readings]

        self.assertEqual(run(self.NOW), ["backfill", "cleanup", "export", "import"])
        before = kept()
        self.assertEqual(run(self.GONE), ["cleanup", "export", "import"])
        removed, = (event for event in tree.recent_events()
                    if event.cause == "removed")
        self.assertEqual((removed.path, removed.new),
                         ("/ci/jobs/backfill", StatusCode.UNDEFINED))
        # what the check kept of it stays, with no node to stand for it
        self.assertEqual(kept(), before)
        self.assertEqual(run(self.BACK), ["backfill", "cleanup", "export", "import"])
        self.assertEqual(kept(), [*before, "backfill-89500001", "backfill-89500005"])

    def test_in_the_engine_an_older_run_of_cleanup_keeps_no_verdict(self):
        check = self._check()
        engine = Engine([check], StatusTree())
        with mock.patch("tests.demo_check.time") as clock:
            clock.time.return_value = self.NOW
            engine.run_once()
        kept = {series.subject: [placed.record.code for placed in series.readings]
                for series in engine.series_near("/ci/jobs")}
        self.assertTrue(all(code is not None for code in kept["jobs/import"]))
        self.assertTrue(all(code is not None for code in kept["jobs/export"]))
        self.assertEqual([code is None for code in kept["jobs/cleanup"]],
                         [True] * 5 + [False])

    def test_its_runs_end_in_every_way_a_mark_tells_apart(self):
        # over a stretch of the wall clock: passed, warned and failed
        check = self._check()
        outcomes = {str(reading.record["outcome"])
                    for step in range(40)
                    for reading in self._read(check, self.NOW + 20 * step)}
        self.assertEqual(outcomes, {"succeeded", "slow", "failed"})


class OffsetTests(TestCase):
    """``LITTLE_SISTER_DEMO_OFFSET`` — a start that finds every scenario that far
    into its cycle. A scenario is a function of the time since its check was built,
    so a start otherwise finds every node at the top of its cycle, where none of
    them fails; with it a start finds the waiting node red, which is what it takes
    to see what a restart does to a wait (ADR-0110, testing-the-gui.md)."""

    VARIABLE = "LITTLE_SISTER_DEMO_OFFSET"

    def _first(self, offset: str | None, scenario: str = "pipelines",
               period: str = "90s") -> tuple[float, CheckResult]:
        """How far into its cycle the first reading finds a check built with the
        variable saying ``offset`` — or unset — and what that reading grades to,
        on a clock that stands still."""
        with (mock.patch.dict(os.environ),
              mock.patch("tests.demo_check.time") as clock):
            os.environ.pop(self.VARIABLE, None)
            if offset is not None:
                os.environ[self.VARIABLE] = offset
            clock.monotonic.return_value = 5000.0
            check = DemoCheck.from_config(
                {"type": "demo", "path": "/x", "scenario": scenario,
                 "period": period}, Path("."))
            reading = check.measure()
        assert isinstance(reading, Measurement)
        return (float(reading.record["elapsed_seconds"]),
                run_check(check, measurements=[reading]))

    def _build(self, result: CheckResult) -> StatusCode | None:
        return next(entry.code for entry in result.reason_entries
                    if entry.slug == "web-build")

    def test_without_it_a_start_finds_the_top_of_the_cycle(self):
        elapsed, result = self._first(None)
        self.assertEqual(elapsed, 0.0)
        self.assertIs(self._build(result), StatusCode.OK)

    def test_it_starts_a_scenario_that_far_into_its_cycle(self):
        elapsed, result = self._first("36s")
        self.assertEqual(elapsed, 36.0)
        # ... which is where the build has failed: the start finds the node red
        self.assertIs(self._build(result), StatusCode.ERROR)

    def test_every_scenario_starts_there_by_its_own_period(self):
        # one offset for the whole tree: past a shorter period it wraps
        elapsed, result = self._first("36s", scenario="flap", period="20s")
        self.assertEqual(elapsed, 16.0)
        self.assertIs(result.code, StatusCode.ERROR)

    def test_an_empty_one_starts_at_the_top(self):
        self.assertEqual(self._first("")[0], 0.0)

    def test_a_negative_one_counts_back_from_the_top(self):
        self.assertEqual(self._first("-10s")[0], 80.0)

    def test_a_check_built_by_hand_starts_at_the_top(self):
        # the variable is read where a config is: a check a test builds has none
        with mock.patch("tests.demo_check.time") as clock:
            clock.monotonic.return_value = 5000.0
            check = DemoCheck(path="/x", scenario="pipelines", period=90.0)
            reading = check.measure()
        assert isinstance(reading, Measurement)
        self.assertEqual(reading.record["elapsed_seconds"], 0.0)

    def test_what_is_no_duration_is_refused_where_the_check_is_built(self):
        with self.assertRaises(CheckError):
            self._first("soon")


class DemoServerTests(TestCase):
    """The wrapper as Mode 2 serves it (testing-the-gui.md): imported the way
    gunicorn's worker imports it, with none of this suite's configuration, the
    committed fixture user signs in, and the server's start runs the demo's engine
    in the demo's own directory. In an interpreter of its own, because the import
    registers a door, a check type and slot fillers and moves the process into that
    directory, and a started engine takes a lease there — none of which may reach
    this suite's process or the checkout."""

    SCRIPT = textwrap.dedent("""
        import json, os
        import tests.demo_wsgi as demo
        from little_sister import app as application
        client = demo.app.test_client()
        before = client.get("/status")
        client.post("/login", data={"username": "pan", "password": "12345678"})
        after = client.get("/status").status_code
        application.start()
        try:
            engine = client.get("/health").get_json()["engine"]
            error = application.engine_error
        finally:
            application.stop()
        print(json.dumps({"before": [before.status_code, before.location],
                          "after": after, "engine": engine, "error": error,
                          "cwd": os.getcwd()}))
    """)

    def test_pan_signs_in_and_the_start_runs_the_engine_in_the_demos_directory(
            self):
        with (tempfile.TemporaryDirectory() as started,
              tempfile.TemporaryDirectory() as home):
            env = subprocess_env()
            env.pop("LITTLE_SISTER_CONFIG_DIR")     # the demo names its own roots
            env.pop("LITTLE_SISTER_ENGINE", None)
            env["LITTLE_SISTER_DEMO_DIR"] = home
            env["PYTHONPATH"] = os.pathsep.join(
                filter(None, (str(_REPO_ROOT), env.get("PYTHONPATH"))))
            done = subprocess.run([sys.executable, "-c", self.SCRIPT], cwd=started,
                                  env=env, capture_output=True, text=True,
                                  timeout=120)
            self.assertEqual(done.returncode, 0, done.stderr[-3000:])
            said = json.loads(done.stdout.strip().splitlines()[-1])
            # a stranger is sent to the door, and pan comes in through it
            status, door = said["before"]
            self.assertEqual(status, 302)
            self.assertTrue(door.startswith("/login"), door)
            self.assertEqual(said["after"], 200)
            # the demo's own configuration loaded, and its engine ran
            self.assertEqual(said["engine"], "running")
            self.assertIsNone(said["error"])
            # ... in the demo's directory, and nowhere else
            self.assertEqual(Path(said["cwd"]).resolve(), Path(home).resolve())
            self.assertTrue((Path(home) / "var" / "state.lease").is_file())
            self.assertEqual(list(Path(started).iterdir()), [])


class DemoConfigTests(TestCase):
    """The aspects the demo tree carries, read by the loaders that read a real one.

    Each case pins a *reason* the file says what it says, so a well-meaning edit
    that quietly stops the demo demonstrating something fails here instead.
    """

    def _checks(self):
        return load_checks(_DEMO_CONFIG_DIR)

    def test_the_audit_leaf_declares_its_findings_as_members(self):
        audit = next(c for c in self._checks() if c.path == "/security/audit")
        self.assertTrue(audit.entries)

    def test_the_pipelines_node_waits_before_it_escalates(self):
        # The one demo node whose lines carry codes and can be pinned is the one
        # that waits (ADR-0083), so the walk can show what a pinned line does to a
        # wait and what its pin's end does (ADR-0108). Every other node publishes
        # at once, which is what a deployment has until it asks.
        waits = {c.path: c.escalate_after for c in self._checks()
                 if c.escalate_after is not None}
        self.assertEqual(waits, {"/ci/pipelines": 3})
        self.assertEqual(load_config(config_dir=_DEMO_CONFIG_DIR).escalate_after, 1)

    def test_the_settings_turn_the_budgeted_retry_on(self):
        config = load_config(config_dir=_DEMO_CONFIG_DIR)
        interval = parse_duration(config.retry_interval or None, 0)
        self.assertGreater(interval, 0)
        self.assertGreater(config.retry_attempts, 0)

    def test_the_retry_interval_is_shorter_than_every_demo_frequency(self):
        # The retry only ever pulls a check's next run *earlier* (ADR-0033), so an
        # interval at or above the frequency is a no-op and `/system` would never
        # show a retry marker — the one thing this settings file is here for.
        config = load_config(config_dir=_DEMO_CONFIG_DIR)
        interval = parse_duration(config.retry_interval or None, 0)
        for check in self._checks():
            self.assertLess(interval, check.frequency_seconds, check.path)

    def test_every_container_node_is_described(self):
        # Containers are created by the tree from the check paths and no check owns
        # them, which is precisely what the `nodes` aspect is for. Without it the
        # demo dashboard is a wall of bare path segments.
        checks = self._checks()
        metadata = resolve_metadata(checks, load_nodes(_DEMO_CONFIG_DIR))
        for check in checks:
            segments = split_path(check.path)
            for depth in range(1, len(segments)):
                container = join_path(*segments[:depth])
                self.assertTrue(metadata.get(container, NodeMeta()).about,
                                container)

    def test_no_declared_node_is_an_orphan(self):
        # `run_consistency_pass` warns for a declaration no check covers; the
        # heartbeat owns no check and is covered anyway (ADR-0005).
        roots = [check.path for check in self._checks()] + [HEARTBEAT_PATH]
        for path in load_nodes(_DEMO_CONFIG_DIR):
            self.assertTrue(any(on_same_line(path, root) for root in roots), path)

    def test_the_actions_fill_both_slots(self):
        actions = load_actions(_DEMO_CONFIG_DIR)
        self.assertEqual({action.slot for action in actions}, set(PLACEMENTS))

    def test_the_per_reason_action_is_scoped_off_the_audit_leaf(self):
        # `reason.actions` is offered on every reason of every node, so an unscoped
        # entry would put a chip on each of the ~150 audit findings.
        for action in load_actions(_DEMO_CONFIG_DIR):
            if action.slot == "reason.actions":
                self.assertTrue(action.under, action.label)
                self.assertFalse(action.applies_to("/security/audit"))

    def test_every_action_icon_is_a_name_the_demo_links_define(self):
        # An unknown name renders no icon and says nothing in the log — so the demo
        # would show a bare chip and look like the icon rung is broken.
        known = load_links(_DEMO_CONFIG_DIR)
        for action in load_actions(_DEMO_CONFIG_DIR):
            if action.icon:
                self.assertIsNotNone(known.icon_for(action.icon), action.icon)


class DemoFillerTests(TestCase):
    """The coded filler the wrapper registers — the half a configured action cannot
    express (ADR-0034): declining."""

    def _node(self, path: str, reasons, *, members: bool = True):
        tree = StatusTree()
        tree.upsert(path, StatusCode.WARN, reasons, members=members)
        node = tree.snapshot(path)
        assert node is not None
        return node

    def _offer(self, node, reason: str):
        return review_action(node=node, reason=reason, index=0, surface="detail")

    def test_it_fills_a_line_waiting_on_a_reviewer(self):
        waiting = "[#4821](https://forge.example.org/x/y/pulls/4821) t — waiting 9h " \
                  "for a reviewer"
        node = self._node("/ci/reviews", {"pr-4821": waiting})
        offered = self._offer(node, waiting)
        assert offered is not None
        self.assertEqual(offered["label"], "nudge")

    def test_it_declines_a_line_waiting_on_its_author(self):
        # the case no config entry can express: present on some lines of a node,
        # absent on others.
        waiting = "PR #1 t — waiting 9h for a reviewer"
        blocked = "PR #2 t — changes requested, waiting on the author"
        node = self._node("/ci/reviews", {"pr-1": waiting, "pr-2": blocked})
        self.assertIsNotNone(self._offer(node, waiting))
        self.assertIsNone(self._offer(node, blocked))

    def test_it_declines_a_prose_node(self):
        line = "worker unreachable — waiting 9h for a reviewer"
        node = self._node("/services/api", [line], members=False)
        self.assertIsNone(self._offer(node, line))

    def test_it_declines_a_wall_of_findings(self):
        line = "finding %d — waiting 9h for a reviewer"
        few = {f"f-{i}": line % i for i in range(REASON_BUDGET)}
        many = {f"f-{i}": line % i for i in range(REASON_BUDGET + 1)}
        self.assertIsNotNone(
            self._offer(self._node("/security/audit", few), line % 0))
        self.assertIsNone(
            self._offer(self._node("/security/audit", many), line % 0))

    def test_the_wrapper_registrations_are_accepted(self):
        # `slots.register` refuses a missing template with a warning and a skip, so
        # a renamed template would cost the demo its chips in silence.
        slots.register("reason.actions", _DEMO_PACKAGE, "review_action.html",
                       review_action)
        slots.register_assets(_DEMO_PACKAGE, "demo.css", "demo.js")
        self.assertEqual([f.package for f in slots.extension_fillers()],
                         [_DEMO_PACKAGE])
        self.assertEqual({asset.member for asset in slots.assets()},
                         {"demo.css", "demo.js"})


class DemoCheckTests(TestCase):
    def test_run_returns_a_result(self):
        check = DemoCheck(path="/x", scenario="escalate", period=60.0)
        self.assertIsInstance(run_check(check), CheckResult)

    def test_unknown_scenario_is_rejected(self):
        with self.assertRaises(CheckError):
            DemoCheck.from_config(
                {"type": "demo", "path": "/x", "scenario": "nope"}, Path("."))

    def test_demo_configs_all_load(self):
        # the WSGI wrapper registers `demo` before this runs; importing DemoCheck
        # above did the same. Every config in the demo dir must load cleanly.
        checks = load_checks(_DEMO_CONFIG_DIR)
        self.assertEqual(len(checks), 12)
        self.assertTrue(all(isinstance(c, DemoCheck) for c in checks))
        self.assertEqual({c.path for c in checks},
                         {"/services/api", "/services/web", "/ci/nightly",
                          "/ci/pipelines", "/ci/reviews", "/ci/workflows",
                          "/ci/jobs",
                          "/network/vpn", "/storage/backup", "/hosts/nas",
                          "/security/audit", "/security/wiz"})

    def test_dropped_child_ages_to_stale(self):
        # the mechanism the `silent` scenario relies on: a child omitted from a
        # later result (as _silent drops `cache`) is never pruned by the tree, so
        # it stops being re-observed and, once its age passes the freshness
        # threshold, shows stale (ADR-0005). (In the live scenario its still-
        # reported sibling stays fresh because it keeps being re-observed every
        # round — see the live smoke; that recency can't be forced in a unit test
        # since upsert stamps wall-clock now.)
        tree = StatusTree()
        for path in ("/backup", "/backup/db", "/backup/cache"):
            tree.upsert(path, StatusCode.OK, frequency_seconds=5)
        fresh = tree.snapshot("/backup")               # just observed → nothing stale
        assert fresh is not None
        self.assertFalse(any(c.stale for c in fresh.children))
        # a minute on with `cache` never re-observed, it has aged past 5s + 30s
        later = tree.snapshot("/backup", now=datetime.now(UTC) + timedelta(seconds=60))
        assert later is not None
        cache = next(c for c in later.children if c.name == "cache")
        self.assertTrue(cache.stale)
