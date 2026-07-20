"""Gate coverage for the live-demo harness (backlog #25, Mode 2).

The scenario functions are pure ``(elapsed, period) -> CheckResult``, so they are
tested directly at chosen points of the cycle; the config directory is loaded
through the real loader (with the ``demo`` type registered, as the WSGI wrapper
does) to prove the demo tree wires up.
"""
from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path
from unittest import TestCase

from little_sister.checks import load_checks
from little_sister.checks.base import CheckError, CheckResult
from little_sister.status import StatusCode
from little_sister.tree import StatusTree
from tests.demo_check import SCENARIOS, DemoCheck

_DEMO_CHECKS_DIR = Path(__file__).resolve().parent / "demo_checks"


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


class DemoCheckTests(TestCase):
    def test_run_returns_a_result(self):
        check = DemoCheck(path="/x", scenario="escalate", period=60.0)
        self.assertIsInstance(check.run(), CheckResult)

    def test_unknown_scenario_is_rejected(self):
        with self.assertRaises(CheckError):
            DemoCheck.from_config(
                {"type": "demo", "path": "/x", "scenario": "nope"}, Path("."))

    def test_demo_configs_all_load(self):
        # the WSGI wrapper registers `demo` before this runs; importing DemoCheck
        # above did the same. Every config in the demo dir must load cleanly.
        checks = load_checks(_DEMO_CHECKS_DIR)
        self.assertEqual(len(checks), 6)
        self.assertTrue(all(isinstance(c, DemoCheck) for c in checks))
        self.assertEqual({c.path for c in checks},
                         {"/services/api", "/ci/nightly", "/network/vpn",
                          "/storage/backup", "/hosts/nas", "/security/audit"})

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
        later = tree.snapshot("/backup", now=datetime.now() + timedelta(seconds=60))
        assert later is not None
        cache = next(c for c in later.children if c.name == "cache")
        self.assertTrue(cache.stale)
