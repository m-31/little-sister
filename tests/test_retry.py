"""The budgeted failure retry (ADR-0033).

A non-OK completion pulls the check's armed next slot to the retry interval —
earlier, never later — at most ``retry_attempts`` times per failure episode; an
OK ends the episode and re-arms the budget; staleness keeps judging by the
nominal frequency; ``/system`` says when a slot is a retry slot.
"""

import os
import tempfile
from dataclasses import replace
from pathlib import Path
from unittest import TestCase, mock

os.environ.setdefault("LITTLE_SISTER_ENGINE", "0")
os.environ.setdefault("SECRET_KEY", "test-key")

from little_sister import app as app_module
from little_sister import engine as engine_module
from little_sister.checks import Check, CheckError, CheckResult
from little_sister.config import load_config
from little_sister.engine import CheckInfo, Engine, EngineInfo
from little_sister.status import StatusCode
from little_sister.tree import StatusTree


class _Probe(Check):
    """A controllable check: returns whatever ``self.result`` currently is."""

    def __init__(self, **kwargs: object) -> None:
        super().__init__(**kwargs)   # type: ignore[arg-type]
        self.result = CheckResult(StatusCode.ERROR, ["down"])

    def run(self) -> CheckResult:
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
