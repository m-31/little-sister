"""The budgeted failure retry (ADR-0033, amended by ADR-0060 decision 4).

A non-OK completion pulls the check's armed next slot to the retry interval —
earlier, never later — at most ``retry_attempts`` times per episode. **Any change
of the reading ends an episode and re-arms the budget**, not only an OK, and a
completed ``UNDEFINED`` arms nothing at all. Staleness keeps judging by the
nominal frequency; ``/system`` says when a slot is a retry slot.
"""

import os
import tempfile
from collections.abc import Sequence
from dataclasses import replace
from datetime import datetime, timedelta
from pathlib import Path
from unittest import TestCase, mock

from little_sister.checks import Measurement

os.environ.setdefault("SECRET_KEY", "test-key")

from little_sister import app as app_module
from little_sister import engine as engine_module
from little_sister.checks import Check, CheckError, CheckResult, Entry
from little_sister.config import load_config
from little_sister.engine import CheckInfo, Engine, EngineInfo
from little_sister.status import StatusCode
from little_sister.tree import StatusTree


class _Probe(Check):
    """A controllable check: returns whatever ``self.result`` currently is."""

    def __init__(self, **kwargs: object) -> None:
        super().__init__(**kwargs)   # type: ignore[arg-type]
        self.result = CheckResult(StatusCode.ERROR, ["down"])

    def measure(self) -> Sequence[Measurement]:
        return ()

    def grade(self, measurements: Sequence[Measurement],
              now: datetime) -> CheckResult:
        return self.result


class RetrySchedulingTests(TestCase):
    def setUp(self):
        self.now = 1000.0

    def _engine(self, check):
        tree = StatusTree()
        engine = Engine([check], tree, clock=lambda: self.now)
        item = engine._scheduled[0]
        item.stagger = 0.0          # the one-time phase is noise here
        return engine, tree, item

    def _run(self, engine, item):
        """One scheduled run, inline: arm the nominal slot the way _tick's
        submit does, then execute — the retry decision happens at completion."""
        item.next_due = self.now + item.check.frequency_seconds + item.stagger
        item.stagger = 0.0
        item.retrying = False
        engine._execute(item)

    def test_failure_pulls_the_slot_to_the_retry_interval(self):
        check = _Probe(path="/svc", frequency_seconds=300,
                       retry_interval_seconds=30, retry_attempts=2)
        engine, _tree, item = self._engine(check)
        self._run(engine, item)
        self.assertEqual(item.next_due, self.now + 30)
        self.assertEqual(item.retry_used, 1)
        self.assertTrue(item.retrying)

    def test_budget_exhausts_back_to_nominal(self):
        check = _Probe(path="/svc", frequency_seconds=300,
                       retry_interval_seconds=30, retry_attempts=2)
        engine, _tree, item = self._engine(check)
        for _ in range(2):
            self._run(engine, item)
        self.assertEqual(item.retry_used, 2)
        self._run(engine, item)                            # budget spent
        self.assertEqual(item.next_due, self.now + 300)    # nominal again
        self.assertFalse(item.retrying)
        self.assertEqual(item.retry_used, 2)               # episode still open

    def test_ok_ends_the_episode_and_rearms_the_budget(self):
        check = _Probe(path="/svc", frequency_seconds=300,
                       retry_interval_seconds=30, retry_attempts=2)
        engine, _tree, item = self._engine(check)
        self._run(engine, item)
        check.result = CheckResult(StatusCode.OK)
        self._run(engine, item)
        self.assertEqual(item.retry_used, 0)
        self.assertFalse(item.retrying)
        self.assertEqual(item.next_due, self.now + 300)
        check.result = CheckResult(StatusCode.WARN, ["hm"])
        self._run(engine, item)                            # a WARN triggers too
        self.assertEqual(item.retry_used, 1)
        self.assertEqual(item.next_due, self.now + 30)

    def test_a_change_of_reading_rearms_the_budget(self):
        """ADR-0060 decision 4(a). ADR-0033 re-armed only on an `OK`, which assumed a
        non-OK check was a failing one. A check whose *ordinary* state is non-OK then
        spent its budget in the first cycles and had no fast look left on the day its
        reading finally changed — which is the one day it is worth paying for."""
        check = _Probe(path="/svc", frequency_seconds=300,
                       retry_interval_seconds=30, retry_attempts=2)
        engine, _tree, item = self._engine(check)
        check.result = CheckResult(StatusCode.WARN, ["queue"])
        for _ in range(3):                                 # spend it, then some
            self._run(engine, item)
        self.assertEqual(item.retry_used, 2)

        check.result = CheckResult(StatusCode.ERROR, ["down"])
        self._run(engine, item)
        self.assertEqual(item.retry_used, 1)               # a new episode
        self.assertEqual(item.next_due, self.now + 30)
        self.assertTrue(item.retrying)

    def test_a_steady_reading_does_not_rearm(self):
        """The other half, and the one that keeps ADR-0033's promise intact: a burst
        is bounded because an unchanged reading is not news. Without this the budget
        would refill every run and a three-day outage would fast-cycle throughout."""
        check = _Probe(path="/svc", frequency_seconds=300,
                       retry_interval_seconds=30, retry_attempts=2)
        engine, _tree, item = self._engine(check)
        check.result = CheckResult(StatusCode.WARN, ["queue"])
        for _ in range(5):
            self._run(engine, item)
        self.assertEqual(item.retry_used, 2)               # never refilled
        self.assertEqual(item.next_due, self.now + 300)    # nominal
        self.assertFalse(item.retrying)

    def test_a_completed_undefined_arms_nothing(self):
        """ADR-0060 decision 4(b): a line that makes no claim is not a failure to
        confirm. The live case is `github-rate-limit` on an installation that reports
        no limit for a resource — a derived `UNDEFINED` every run, forever, where
        asking again in thirty seconds cannot change the answer."""
        check = _Probe(path="/svc", frequency_seconds=300,
                       retry_interval_seconds=30, retry_attempts=2)
        engine, _tree, item = self._engine(check)
        check.result = CheckResult(
            reason=[Entry("core", "no limit for this resource",
                          StatusCode.UNDEFINED)])
        self.assertIs(check.result.stored_code, StatusCode.UNDEFINED)
        for _ in range(3):
            self._run(engine, item)
        self.assertEqual(item.retry_used, 0)               # nothing spent
        self.assertEqual(item.next_due, self.now + 300)    # nothing pulled in
        self.assertFalse(item.retrying)

    def test_an_unknown_that_becomes_a_failure_still_arms(self):
        """The complement, so *unknown arms nothing* cannot quietly become *a check
        that was ever unknown can never retry again*."""
        check = _Probe(path="/svc", frequency_seconds=300,
                       retry_interval_seconds=30, retry_attempts=2)
        engine, _tree, item = self._engine(check)
        check.result = CheckResult(
            reason=[Entry("core", "no limit", StatusCode.UNDEFINED)])
        self._run(engine, item)
        check.result = CheckResult(StatusCode.ERROR, ["gone"])
        self._run(engine, item)
        self.assertEqual(item.retry_used, 1)
        self.assertEqual(item.next_due, self.now + 30)

    def test_retry_never_pushes_the_slot_later(self):
        # a retry interval beyond the frequency changes nothing at all, and the
        # fast look that would not be fast does not count against the budget
        check = _Probe(path="/svc", frequency_seconds=60,
                       retry_interval_seconds=600, retry_attempts=2)
        engine, _tree, item = self._engine(check)
        self._run(engine, item)
        self.assertEqual(item.next_due, self.now + 60)
        self.assertEqual(item.retry_used, 0)
        self.assertFalse(item.retrying)

    def test_no_retry_when_off(self):
        check = _Probe(path="/svc", frequency_seconds=300)   # defaults: off
        engine, _tree, item = self._engine(check)
        self._run(engine, item)
        self.assertEqual(item.next_due, self.now + 300)
        self.assertEqual(item.retry_used, 0)

    def test_secret_pinned_check_never_retries(self):
        # pinned until restart (ADR-0023): a fast retry would burn the pool
        # confirming a result that cannot change
        check = _Probe(path="/svc", frequency_seconds=300,
                       retry_interval_seconds=30, retry_attempts=2)
        check.secret_errors.append("store unreachable")
        engine, tree, item = self._engine(check)
        self._run(engine, item)
        self.assertEqual(item.next_due, self.now + 300)    # not pulled
        self.assertEqual(item.retry_used, 0)
        self.assertEqual(tree.snapshot("/svc").own_code, StatusCode.ERROR)

    def test_staleness_keeps_the_nominal_frequency(self):
        # the upsert carries the nominal frequency unchanged, so ADR-0005's
        # freshness math never sees the retry
        check = _Probe(path="/svc", frequency_seconds=300,
                       retry_interval_seconds=30, retry_attempts=2)
        engine, tree, item = self._engine(check)
        self._run(engine, item)
        snap = tree.snapshot("/svc")
        self.assertEqual(snap.frequency_seconds, 300)      # never the retry
        self.assertFalse(snap.stale)

    def test_info_reports_the_retry_state(self):
        check = _Probe(path="/svc", frequency_seconds=300,
                       retry_interval_seconds=30, retry_attempts=2)
        engine, _tree, item = self._engine(check)
        self._run(engine, item)
        info = engine.info().checks[0]
        self.assertTrue(info.retrying)
        self.assertEqual(info.retry_attempt, 1)
        self.assertEqual(info.retry_attempts, 2)
        check.result = CheckResult(StatusCode.OK)
        self._run(engine, item)
        self.assertFalse(engine.info().checks[0].retrying)


class RunFactsScheduleTests(TestCase):
    """The run facts the engine writes beside each result (ADR-0044) carry the
    **armed slot** — which under ADR-0033 is the pulled-in retry slot when one
    is armed, never ``timestamp + frequency`` arithmetic."""

    def setUp(self):
        self.now = 1000.0

    def _engine(self, check):
        tree = StatusTree()
        engine = Engine([check], tree, clock=lambda: self.now)
        item = engine._scheduled[0]
        item.stagger = 0.0
        return engine, tree, item

    def _run(self, engine, item):
        """One scheduled run, inline, as RetrySchedulingTests drives it."""
        item.next_due = self.now + item.check.frequency_seconds + item.stagger
        item.stagger = 0.0
        item.retrying = False
        engine._execute(item)

    def _facts(self, tree, path="/svc"):
        snap = tree.snapshot(path)
        assert snap is not None and snap.run is not None
        return snap.run

    def test_the_nominal_slot_is_projected_onto_the_wall_clock(self):
        check = _Probe(path="/svc", frequency_seconds=300)
        check.result = CheckResult(StatusCode.OK)
        engine, tree, item = self._engine(check)
        before = datetime.now()
        self._run(engine, item)
        after = datetime.now()
        facts = self._facts(tree)
        assert facts.next_run_at is not None
        got = datetime.fromisoformat(facts.next_run_at)
        self.assertGreaterEqual(got, before + timedelta(seconds=300))
        self.assertLessEqual(got, after + timedelta(seconds=300))
        self.assertIsNotNone(facts.wall_seconds)

    def test_a_failure_writes_the_pulled_slot_not_the_frequency(self):
        # The ADR-0044 point of sourcing from the engine: while someone watches
        # a failure, the next update shown is the fast retry — arithmetic from
        # the frequency would confidently say five minutes.
        check = _Probe(path="/svc", frequency_seconds=300,
                       retry_interval_seconds=30, retry_attempts=2)
        engine, tree, item = self._engine(check)
        before = datetime.now()
        self._run(engine, item)
        after = datetime.now()
        facts = self._facts(tree)
        assert facts.next_run_at is not None
        got = datetime.fromisoformat(facts.next_run_at)
        self.assertGreaterEqual(got, before + timedelta(seconds=30))
        self.assertLessEqual(got, after + timedelta(seconds=30))

    def test_a_pinned_check_writes_no_wall_but_keeps_its_slot(self):
        # It never runs (ADR-0023), so there is no honest duration — but the
        # pinned ERROR still re-asserts on schedule, so the next slot is real.
        check = _Probe(path="/svc", frequency_seconds=300)
        check.secret_errors.append("store unreachable")
        engine, tree, item = self._engine(check)
        self._run(engine, item)
        facts = self._facts(tree)
        self.assertIsNone(facts.wall_seconds)
        self.assertIsNotNone(facts.next_run_at)


class RetrySettingsResolutionTests(TestCase):
    """Per-check fields first, then the settings defaults — resolved once, at
    engine construction, where a bad settings value can fall back with a
    warning instead of failing the start."""

    def _with_config(self, **fields):
        return mock.patch.object(engine_module, "config",
                                 replace(engine_module.config, **fields))

    def test_settings_defaults_apply_when_the_check_is_silent(self):
        with self._with_config(retry_interval="45s", retry_attempts=3):
            engine = Engine([_Probe(path="/svc")], StatusTree())
        item = engine._scheduled[0]
        self.assertEqual(item.retry_interval_seconds, 45)
        self.assertEqual(item.retry_attempts, 3)

    def test_bare_seconds_work_in_settings(self):
        with self._with_config(retry_interval="30"):
            engine = Engine([_Probe(path="/svc")], StatusTree())
        self.assertEqual(engine._scheduled[0].retry_interval_seconds, 30)

    def test_per_check_fields_beat_settings(self):
        with self._with_config(retry_interval="45s", retry_attempts=3):
            engine = Engine([_Probe(path="/svc", retry_interval_seconds=10,
                                    retry_attempts=1)], StatusTree())
        item = engine._scheduled[0]
        self.assertEqual(item.retry_interval_seconds, 10)
        self.assertEqual(item.retry_attempts, 1)

    def test_a_check_can_switch_itself_off(self):
        with self._with_config(retry_interval="45s"):
            engine = Engine([_Probe(path="/svc", retry_interval_seconds=0)],
                            StatusTree())
        self.assertEqual(engine._scheduled[0].retry_interval_seconds, 0)

    def test_junk_settings_interval_stays_off_with_a_warning(self):
        with self._with_config(retry_interval="soon"):
            with self.assertLogs(level="WARNING") as logs:
                engine = Engine([_Probe(path="/svc")], StatusTree())
        self.assertEqual(engine._scheduled[0].retry_interval_seconds, 0)
        self.assertTrue(any("retry_interval" in line for line in logs.output))


class RetryConfigKeysTests(TestCase):
    def test_defaults_off(self):
        cfg = load_config(Path(tempfile.gettempdir()) / "ls-no-such-config.yaml")
        self.assertEqual(cfg.retry_interval, "")
        self.assertEqual(cfg.retry_attempts, 2)

    def test_keys_load_and_bare_numbers_survive(self):
        # values.text stringifies, so `retry_interval: 30` (bare seconds — the
        # natural spelling) survives to the parser
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "settings.yaml"
            path.write_text("retry_interval: 30\nretry_attempts: 5\n")
            cfg = load_config(path)
        self.assertEqual(cfg.retry_interval, "30")
        self.assertEqual(cfg.retry_attempts, 5)

    def test_junk_attempts_falls_back(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "settings.yaml"
            path.write_text("retry_attempts: many\n")
            with self.assertLogs(level="WARNING"):
                cfg = load_config(path)
        self.assertEqual(cfg.retry_attempts, 2)

    def test_negative_attempts_becomes_zero(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "settings.yaml"
            path.write_text("retry_attempts: -1\n")
            with self.assertLogs(level="WARNING"):
                cfg = load_config(path)
        self.assertEqual(cfg.retry_attempts, 0)


class RetryCheckFieldTests(TestCase):
    """The two per-check config fields ride _parse_common like frequency and
    timeout: absent inherits the settings default, junk fails the load."""

    def _probe(self, **extra):
        config = {"path": "/svc", **extra}
        return _Probe.from_config(config, Path("."))

    def test_absent_fields_inherit(self):
        check = self._probe()
        self.assertIsNone(check.retry_interval_seconds)
        self.assertIsNone(check.retry_attempts)

    def test_duration_and_bare_seconds(self):
        self.assertEqual(
            self._probe(retry_interval="30s").retry_interval_seconds, 30)
        self.assertEqual(
            self._probe(retry_interval=45).retry_interval_seconds, 45)
        self.assertEqual(
            self._probe(retry_interval=0).retry_interval_seconds, 0)
        self.assertEqual(self._probe(retry_attempts=0).retry_attempts, 0)
        self.assertEqual(self._probe(retry_attempts="3").retry_attempts, 3)

    def test_junk_fails_the_load(self):
        with self.assertRaises(CheckError):
            self._probe(retry_interval="soon")
        with self.assertRaises(CheckError):
            self._probe(retry_attempts="many")
        with self.assertRaises(CheckError):
            self._probe(retry_attempts=-1)


class SystemRetryDisplayTests(TestCase):
    """The /system table says when a next slot is a retry slot — a slot that
    silently contradicts the frequency column looks like a bug."""

    def setUp(self):
        app_module.app.config["TESTING"] = True
        self.client = app_module.app.test_client()
        self.client.post("/login",
                         data={"username": "pan", "password": "12345678"})

    def _body(self, check):
        info = EngineInfo(started_at="2026-07-31T10:00:00", uptime_seconds=5.0,
                          max_workers=8, check_count=1, running=0,
                          checks=(check,))
        stub = mock.Mock()
        stub.info.return_value = info
        with mock.patch.object(app_module, "engine", stub):
            return self.client.get("/system").get_data(as_text=True)

    def test_next_run_marks_a_retry_slot(self):
        body = self._body(CheckInfo(
            path="/svc/a", type_name="http", frequency_seconds=300,
            running=False, running_since=None, running_seconds=None,
            next_run_at="2026-07-31T10:01:00+00:00", next_in_seconds=30.0,
            last_run_at="2026-07-31T10:00:30+00:00", elapsed_seconds=0.2,
            retrying=True, retry_attempt=1, retry_attempts=2))
        self.assertIn("· retry 1/2", body)

    def test_nominal_slot_stays_unmarked(self):
        body = self._body(CheckInfo(
            path="/svc/a", type_name="http", frequency_seconds=300,
            running=False, running_since=None, running_seconds=None,
            next_run_at="2026-07-31T10:05:00+00:00", next_in_seconds=300.0,
            last_run_at=None, elapsed_seconds=None))
        self.assertNotIn("retry", body.split("<tbody>", 1)[1])
