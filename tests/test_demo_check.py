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

from dataclasses import replace
from datetime import datetime, timedelta
from pathlib import Path
from unittest import TestCase

from little_sister import slots
from little_sister.actions import PLACEMENTS, load_actions
from little_sister.checks import load_checks
from little_sister.checks.base import CheckError, CheckResult, parse_duration
from little_sister.config import load_config
from little_sister.links import load_links
from little_sister.nodes import NodeMeta, load_nodes, resolve_metadata
from little_sister.reasons import DERIVED_PREFIX
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

_DEMO_CONFIG_DIR = Path(__file__).resolve().parent / "demo_config"
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
        for child in result.children:
            with self.subTest(band=child.name):
                self.assertEqual(shown_title(child.name, child.title), "")

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
        self.assertFalse(check.run().members)
        self.assertNotIn("entries", check.config_summary())

    def test_it_turns_a_prose_scenario_into_members(self):
        check = DemoCheck(path="/x", scenario="audit", period=120.0, entries=True)
        result = check.run()
        self.assertTrue(result.members)
        self.assertTrue(all(e.slug.startswith(DERIVED_PREFIX)
                            for e in result.reason_entries))
        self.assertIn("entries", check.config_summary())

    def test_it_leaves_a_mapping_scenario_alone(self):
        # `reviews` already said it in the stronger form; the knob cannot add to it
        # and must not re-key it.
        keyed = DemoCheck(path="/x", scenario="reviews", period=90.0, entries=True)
        self.assertTrue(keyed.run().members)
        self.assertFalse([e for e in keyed.run().reason_entries
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
        self.assertIsInstance(check.run(), CheckResult)

    def test_unknown_scenario_is_rejected(self):
        with self.assertRaises(CheckError):
            DemoCheck.from_config(
                {"type": "demo", "path": "/x", "scenario": "nope"}, Path("."))

    def test_demo_configs_all_load(self):
        # the WSGI wrapper registers `demo` before this runs; importing DemoCheck
        # above did the same. Every config in the demo dir must load cleanly.
        checks = load_checks(_DEMO_CONFIG_DIR)
        self.assertEqual(len(checks), 9)
        self.assertTrue(all(isinstance(c, DemoCheck) for c in checks))
        self.assertEqual({c.path for c in checks},
                         {"/services/api", "/ci/nightly", "/ci/pipelines",
                          "/ci/reviews", "/network/vpn", "/storage/backup",
                          "/hosts/nas", "/security/audit", "/security/wiz"})

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
