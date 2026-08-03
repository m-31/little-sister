import tempfile
import threading
import time
import unittest
from dataclasses import replace
from datetime import datetime, timedelta
from pathlib import Path
from unittest import TestCase
from unittest.mock import patch

from little_sister import engine as engine_module
from little_sister.checks.base import Check, CheckResult
from little_sister.config import config
from little_sister.engine import Engine
from little_sister.status import StatusCode
from little_sister.tree import StatusTree


class _FakeCheck(Check):
    """A controllable check for tests."""

    def __init__(self, *, result: CheckResult | None = None,
                 raises: Exception | None = None,
                 ran: threading.Event | None = None,
                 block: threading.Event | None = None, **kwargs: object) -> None:
        super().__init__(**kwargs)   # type: ignore[arg-type]
        self._result = result or CheckResult(StatusCode.OK)
        self._raises = raises
        self._ran = ran
        self._block = block

    def run(self) -> CheckResult:
        if self._block is not None:
            self._block.wait(timeout=5)
        if self._raises is not None:
            raise self._raises
        if self._ran is not None:
            self._ran.set()
        return self._result


class _ConfiguredCheck(_FakeCheck):
    """A leaf check that reports a config summary (ADR-0013)."""

    def config_summary(self) -> str:
        return "- **url:** http://x"


def _wait_for(predicate, timeout: float = 2.0) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        if predicate():
            return True
        time.sleep(0.01)
    return predicate()


class EngineTests(TestCase):
    def test_run_once_upserts_and_rolls_up(self):
        tree = StatusTree()
        checks = [
            _FakeCheck(path="/svc/a", result=CheckResult(StatusCode.OK)),
            _FakeCheck(path="/svc/b",
                       result=CheckResult(StatusCode.ERROR, ["boom"])),
        ]
        Engine(checks, tree).run_once()
        self.assertEqual(tree.effective("/svc"), StatusCode.ERROR)
        node_b = tree.snapshot("/svc/b")
        assert node_b is not None
        self.assertEqual(node_b.own_code, StatusCode.ERROR)
        self.assertEqual(node_b.reason, ("boom",))

    def test_leaf_config_lands_on_its_node(self):
        tree = StatusTree()
        Engine([_ConfiguredCheck(path="/svc/api")], tree).run_once()
        node = tree.snapshot("/svc/api")
        assert node is not None
        self.assertIn("http://x", node.config)

    def test_branch_child_config_with_bare_container(self):
        tree = StatusTree()
        # A branch check's container reports no config (its config_summary is
        # empty); each child carries its own slice (ADR-0013).
        result = CheckResult(StatusCode.UNDEFINED, children=(
            CheckResult(StatusCode.OK, name="disk", config="- **warn at:** 80%"),))
        Engine([_FakeCheck(path="/host", result=result)], tree).run_once()
        container = tree.snapshot("/host")
        child = tree.snapshot("/host/disk")
        assert container is not None and child is not None
        self.assertEqual(container.config, "")
        self.assertEqual(child.config, "- **warn at:** 80%")

    def test_raising_check_becomes_error(self):
        tree = StatusTree()
        check = _FakeCheck(path="/boom", raises=RuntimeError("nope"))
        Engine([check], tree).run_once()
        node = tree.snapshot("/boom")
        assert node is not None
        self.assertEqual(node.own_code, StatusCode.ERROR)
        self.assertIn("check error", node.reason[0])

    def test_exception_message_is_escaped(self):
        # the message carries whatever the failure carried — a captured line, a
        # path, an API error body — so it is folded in like any untrusted text
        # (ADR-0018) rather than rendering as Markdown on the dashboard
        tree = StatusTree()
        check = _FakeCheck(path="/boom",
                           raises=RuntimeError("bad *value* in [x](y)"))
        Engine([check], tree).run_once()
        node = tree.snapshot("/boom")
        assert node is not None
        self.assertIn(r"bad \*value\* in \[x\](y)", node.reason[0])

    def test_stacktrace_is_shown_as_a_code_block(self):
        tree = StatusTree()
        check = _FakeCheck(path="/boom", raises=RuntimeError("nope"))
        with patch.object(engine_module, "config",
                          replace(config, stacktrace=True)):
            Engine([check], tree).run_once()
        node = tree.snapshot("/boom")
        assert node is not None
        self.assertEqual(len(node.reason), 2)
        trace = node.reason[1]
        self.assertTrue(trace.startswith("```"))     # inert, verbatim (ADR-0018)
        self.assertIn("RuntimeError: nope", trace)
        self.assertIn("Traceback (most recent call last)", trace)

    def test_stacktrace_can_be_switched_off(self):
        tree = StatusTree()
        check = _FakeCheck(path="/boom", raises=RuntimeError("nope"))
        with patch.object(engine_module, "config",
                          replace(config, stacktrace=False)):
            Engine([check], tree).run_once()
        node = tree.snapshot("/boom")
        assert node is not None
        self.assertEqual(len(node.reason), 1)
        self.assertNotIn("Traceback", node.reason[0])

    def test_stacktrace_keeps_the_innermost_frames_and_the_cause(self):
        def _boom() -> None:
            try:
                raise ValueError("root cause")
            except ValueError as error:
                raise RuntimeError("wrapped") from error

        tree = StatusTree()
        check = _FakeCheck(path="/boom", raises=None)
        check.run = _boom                              # type: ignore[method-assign]
        with patch.object(engine_module, "config",
                          replace(config, stacktrace=True)):
            Engine([check], tree).run_once()
        node = tree.snapshot("/boom")
        assert node is not None
        trace = node.reason[1]
        self.assertIn("ValueError: root cause", trace)   # the chained __cause__
        self.assertIn("RuntimeError: wrapped", trace)

    def test_tick_sweeps_expired_maintenance(self):
        tree = StatusTree()
        tree.set_maintenance("/db", "planned",
                             expires_at=datetime.now() - timedelta(seconds=1))
        engine = Engine([_FakeCheck(path="/x")], tree, poll_interval=0.02)
        engine.start()
        try:
            self.assertTrue(_wait_for(
                lambda: tree.effective("/db") == StatusCode.UNDEFINED))
        finally:
            engine.stop()

    def test_check_roots_lists_full_paths(self):
        tree = StatusTree()
        engine = Engine([_FakeCheck(path="/svc/a"),
                         _FakeCheck(path="/b")], tree)
        self.assertEqual(set(engine.check_roots()), {"/svc/a", "/b"})

    def test_scheduled_run_updates_tree(self):
        tree = StatusTree()
        ran = threading.Event()
        check = _FakeCheck(path="/probe",
                           result=CheckResult(StatusCode.OK), ran=ran)
        engine = Engine([check], tree)
        engine.start()
        try:
            self.assertTrue(ran.wait(timeout=2))
            self.assertTrue(_wait_for(
                lambda: (s := tree.snapshot("/probe")) is not None
                and s.own_code == StatusCode.OK))
        finally:
            engine.stop()

    def test_slow_check_does_not_block_fast_one(self):
        tree = StatusTree()
        block = threading.Event()
        slow = _FakeCheck(path="/slow",
                          result=CheckResult(StatusCode.OK), block=block)
        fast = _FakeCheck(path="/fast", result=CheckResult(StatusCode.OK))
        engine = Engine([slow, fast], tree, max_workers=4)
        engine.start()
        try:
            # fast result must appear while slow is still blocked
            self.assertTrue(_wait_for(
                lambda: (s := tree.snapshot("/fast")) is not None
                and s.own_code == StatusCode.OK))
            self.assertIsNone(tree.snapshot("/slow"))
        finally:
            block.set()
            engine.stop()

    def test_stop_is_clean(self):
        tree = StatusTree()
        engine = Engine([_FakeCheck(path="/x")], tree)
        engine.start()
        engine.stop()
        # a second stop is a no-op
        engine.stop()

    def test_no_checks_is_fine(self):
        engine = Engine([], StatusTree())
        self.assertEqual(engine.check_count, 0)
        engine.start()
        engine.stop()

    def test_info_reports_engine_state(self):
        engine = Engine([_FakeCheck(path="/a"),
                         _FakeCheck(path="/svc/b")], StatusTree())
        info = engine.info()
        self.assertEqual(info.check_count, 2)
        self.assertIsNone(info.started_at)
        self.assertEqual({c.path for c in info.checks}, {"/a", "/svc/b"})

    def test_children_are_written_as_a_branch(self):
        tree = StatusTree()
        result = CheckResult(StatusCode.OK, ["host up"], children=(
            CheckResult(StatusCode.WARN, ["85% used"], name="disk",
                        description="Disk space"),
            CheckResult(StatusCode.OK, ["50% used"], name="memory"),
        ))
        check = _FakeCheck(path="/system/host", result=result,
                           description="Host over SSH", frequency_seconds=120)
        Engine([check], tree).run_once()
        # the worst aspect rolls up to the host node
        self.assertEqual(tree.effective("/system/host"), StatusCode.WARN)
        root = tree.snapshot("/system/host")
        assert root is not None
        self.assertEqual(root.own_code, StatusCode.OK)
        self.assertEqual(root.description, "Host over SSH")
        disk = tree.snapshot("/system/host/disk")
        assert disk is not None
        self.assertEqual(disk.own_code, StatusCode.WARN)
        self.assertEqual(disk.reason, ("85% used",))
        self.assertEqual(disk.description, "Disk space")
        # child inherits the check's frequency, so freshness applies (ADR-0005)
        self.assertEqual(disk.frequency_seconds, 120)

    def test_child_about_and_title_land_on_child_nodes(self):
        # A branch check captions the subnodes it emits (ADR-0025): each child's
        # about/title ride onto its node like description/config.
        tree = StatusTree()
        result = CheckResult(StatusCode.OK, ["host up"], children=(
            CheckResult(StatusCode.OK, name="disk",
                        about="Free space on the data volume.", title="Disk"),))
        Engine([_FakeCheck(path="/host", result=result)], tree).run_once()
        disk = tree.snapshot("/host/disk")
        assert disk is not None
        self.assertEqual(disk.about, "Free space on the data volume.")
        self.assertEqual(disk.title, "Disk")

    def test_root_result_labels_are_ignored(self):
        # The root's labels keep their startup sources (nodes.yaml / inline check),
        # so about/title on the root result are ignored like its name (ADR-0025).
        tree = StatusTree()
        result = CheckResult(StatusCode.OK, about="ignored", title="ignored")
        Engine([_FakeCheck(path="/host", result=result)], tree).run_once()
        root = tree.snapshot("/host")
        assert root is not None
        self.assertEqual((root.about, root.title), ("", ""))

    def test_nodes_yaml_label_beats_check_provided_child(self):
        # A nodes.yaml value is seeded (set_about) before the first tick and wins
        # over the check-provided child label; resolved per field.
        tree = StatusTree()
        tree.set_about("/host/disk", "Declared in nodes.yaml.")
        result = CheckResult(StatusCode.OK, children=(
            CheckResult(StatusCode.OK, name="disk",
                        about="From the check.", title="Disk"),))
        Engine([_FakeCheck(path="/host", result=result)], tree).run_once()
        disk = tree.snapshot("/host/disk")
        assert disk is not None
        self.assertEqual(disk.about, "Declared in nodes.yaml.")   # yaml wins
        self.assertEqual(disk.title, "Disk")                      # yaml left it empty

    def test_elapsed_none_before_first_run(self):
        engine = Engine([_FakeCheck(path="/a")], StatusTree())
        self.assertIsNone(engine.info().checks[0].elapsed_seconds)

    def test_run_records_elapsed(self):
        engine = Engine([_FakeCheck(path="/a")], StatusTree())
        engine.run_once()
        elapsed = engine.info().checks[0].elapsed_seconds
        assert elapsed is not None
        self.assertGreaterEqual(elapsed, 0.0)

    def test_raising_run_records_elapsed(self):
        # A run that blows up (or times out) still shows how long it took.
        engine = Engine([_FakeCheck(path="/boom", raises=RuntimeError("nope"))],
                        StatusTree())
        engine.run_once()
        self.assertIsNotNone(engine.info().checks[0].elapsed_seconds)

    def test_pinned_check_records_no_elapsed(self):
        # A secret-pinned check never runs (ADR-0023), so it has no runtime.
        check = _FakeCheck(path="/pinned")
        check.secret_errors.append("db-password: store unreachable")
        engine = Engine([check], StatusTree())
        engine.run_once()
        info = engine.info().checks[0]
        self.assertIsNone(info.elapsed_seconds)
        self.assertIsNone(info.last_run_at)

    def test_run_records_last_run_start(self):
        engine = Engine([_FakeCheck(path="/a")], StatusTree())
        engine.run_once()
        info = engine.info().checks[0]
        assert info.last_run_at is not None
        datetime.fromisoformat(info.last_run_at)      # a real timestamp
        # the finished run is no longer reported as in flight
        self.assertIsNone(info.running_since)
        self.assertIsNone(info.running_seconds)

    def test_next_run_at_is_a_timestamp(self):
        engine = Engine([_FakeCheck(path="/a")], StatusTree())
        info = engine.info().checks[0]
        datetime.fromisoformat(info.next_run_at)      # parseable, wall clock

    def test_info_carries_type_name(self):
        class _TypedCheck(_FakeCheck):
            type_name = "fake"
        engine = Engine([_TypedCheck(path="/t")], StatusTree())
        self.assertEqual(engine.info().checks[0].type_name, "fake")

    def test_running_check_reports_its_start(self):
        tree = StatusTree()
        block = threading.Event()
        slow = _FakeCheck(path="/slow", block=block)
        engine = Engine([slow], tree)
        engine.start()
        try:
            self.assertTrue(_wait_for(
                lambda: engine.info().checks[0].running_since is not None))
            info = engine.info().checks[0]
            self.assertTrue(info.running)
            self.assertIsNotNone(info.running_seconds)
            self.assertIsNone(info.last_run_at)       # first run still in flight
        finally:
            block.set()
            engine.stop()

    def test_stagger_is_stable_and_capped(self):
        from little_sister.engine import STAGGER_WINDOW_SECONDS, _stagger
        check = _FakeCheck(path="/svc/a", frequency_seconds=120)
        first = _stagger(check)
        self.assertEqual(first, _stagger(check))       # deterministic
        self.assertGreaterEqual(first, 0.0)
        self.assertLess(first, STAGGER_WINDOW_SECONDS)
        fast = _FakeCheck(path="/svc/a", frequency_seconds=30)
        self.assertLess(_stagger(fast), 30.0)          # capped by the period

    def test_same_root_different_type_get_distinct_phases(self):
        # two checks may share a root node (host-metrics + macos-memory on one
        # host) — the pair hitting one host must separate most of all
        from little_sister.engine import _stagger

        class _Metrics(_FakeCheck):
            type_name = "host-metrics"

        class _Memory(_FakeCheck):
            type_name = "macos-memory"

        self.assertNotEqual(
            _stagger(_Metrics(path="/host", frequency_seconds=120)),
            _stagger(_Memory(path="/host", frequency_seconds=120)))

    def test_start_lockstep_dissolves_after_first_rearm(self):
        # both checks run in the immediate first sweep, but re-arm onto
        # distinct personal phases (frequency + stagger, once)
        from little_sister.engine import _stagger
        a = _FakeCheck(path="/a", frequency_seconds=120)
        b = _FakeCheck(path="/b", frequency_seconds=120)
        expected = abs(_stagger(a) - _stagger(b))
        self.assertGreater(expected, 0.5)   # these paths do differ clearly
        engine = Engine([a, b], StatusTree())
        engine.start()
        try:
            self.assertTrue(_wait_for(
                lambda: all(c.last_run_at for c in engine.info().checks)))
            nexts = {c.path: c.next_in_seconds for c in engine.info().checks}
            self.assertAlmostEqual(
                abs(nexts["/a"] - nexts["/b"]), expected, delta=1.0)
        finally:
            engine.stop()

    def test_engine_heartbeats_self_node(self):
        from little_sister.engine import HEARTBEAT_PATH
        tree = StatusTree()
        engine = Engine([_FakeCheck(path="/x")], tree)
        engine.start()
        try:
            self.assertTrue(_wait_for(
                lambda: tree.snapshot(HEARTBEAT_PATH) is not None))
        finally:
            engine.stop()

    def test_heartbeat_carries_a_default_about(self):
        # The dashboard strip's hover card explains the self-monitor out of
        # the box (ADR-0024); a later seed (the startup nodes.yaml pass) overrides.
        from little_sister.engine import HEARTBEAT_ABOUT, HEARTBEAT_PATH
        tree = StatusTree()
        Engine([_FakeCheck(path="/x")], tree)
        snap = tree.snapshot(HEARTBEAT_PATH)
        self.assertIsNotNone(snap)
        self.assertEqual(snap.about, HEARTBEAT_ABOUT)
        self.assertIn("scheduler", snap.about)
        tree.set_about(HEARTBEAT_PATH, "custom note")
        self.assertEqual(tree.snapshot(HEARTBEAT_PATH).about, "custom note")

    def test_construction_registers_each_check_as_a_mount(self):
        # ADR-0027: the engine knows where its checks write, so the containers above
        # a sole check can publish its run time. Registration happens at
        # construction — before the first tick — and creates no nodes (only the
        # heartbeat's `about` seed does, and that is not a mount).
        from little_sister.engine import HEARTBEAT_PATH
        tree = StatusTree()
        Engine([_FakeCheck(path="/system/node_a/host_metrics")], tree)
        root = tree.snapshot()
        assert root is not None
        self.assertEqual([child.path for child in root.children], [HEARTBEAT_PATH])
        self.assertIsNone(tree.snapshot("/system"))   # registration is not a node
        self.assertIsNone(root.timestamp)             # nor an observation

    def test_a_sole_check_stamps_the_root_after_one_sweep(self):
        # End to end: one check, one run — the mount's time climbs to the root.
        tree = StatusTree()
        Engine([_FakeCheck(path="/system/node_a/host_metrics")], tree).run_once()
        mount = tree.snapshot("/system/node_a/host_metrics")
        root = tree.snapshot()
        assert mount is not None and root is not None
        self.assertIsNotNone(mount.timestamp)
        self.assertEqual(root.timestamp, mount.timestamp)

    def test_two_checks_leave_the_root_without_a_timestamp(self):
        tree = StatusTree()
        Engine([_FakeCheck(path="/system/node_a/host_metrics"),
                _FakeCheck(path="/system/node_b/host_metrics")], tree).run_once()
        root = tree.snapshot()
        assert root is not None
        self.assertIsNone(root.timestamp)

    def test_branch_check_children_do_not_count_as_mounts(self):
        # Only the check's own path is a mount; the result subtree it writes below
        # that path is one check's data, so the mount node still answers for it.
        tree = StatusTree()
        result = CheckResult(StatusCode.OK, children=(
            CheckResult(StatusCode.OK, name="disk"),
            CheckResult(StatusCode.OK, name="memory"),
        ))
        Engine([_FakeCheck(path="/system/node_a/host_metrics", result=result)],
               tree).run_once()
        mount = tree.snapshot("/system/node_a/host_metrics")
        root = tree.snapshot()
        assert mount is not None and root is not None
        self.assertEqual(len(mount.children), 2)
        self.assertEqual(root.timestamp, mount.timestamp)


class EmptyConfigurationTests(TestCase):
    """A configured deployment with no checks in it *yet* is a real, temporary
    state — so the engine runs and the heartbeat says so (ADR-0031 §7 / ADR-0005).
    Having nowhere to look for checks is a different thing and refuses to start;
    that lives in the loader's tests."""

    def _root(self, directory: str) -> Path:
        (Path(directory) / "checks").mkdir()
        return Path(directory)

    def test_empty_checks_aspect_starts_and_warns_on_the_heartbeat(self):
        from little_sister.engine import HEARTBEAT_PATH, create_engine
        tree = StatusTree()
        with tempfile.TemporaryDirectory() as directory:
            root = self._root(directory)
            with self.assertLogs(level="WARNING"):
                engine = create_engine(str(root), tree=tree)
            # The scheduler runs with nothing scheduled — the heartbeat is the
            # one thing it still has to publish.
            engine.start()
            try:
                self.assertTrue(_wait_for(
                    lambda: tree.snapshot(HEARTBEAT_PATH) is not None
                    and tree.snapshot(HEARTBEAT_PATH).code is StatusCode.WARN))
            finally:
                engine.stop()
            snap = tree.snapshot(HEARTBEAT_PATH)
            assert snap is not None
            # WARN, not OK: with zero checks the tree is *only* the heartbeat, so
            # an OK here would roll up to an all-green root while nothing at all is
            # being watched.
            self.assertIn("no checks configured", " ".join(snap.reason))
            # The searched paths ride in a code block, not loose in the prose:
            # a reason is Markdown and a path with underscores would italicize.
            self.assertIn(str(root.resolve()), " ".join(snap.reason))
            self.assertTrue(any(part.startswith("```") for part in snap.reason))
            root_snap = tree.snapshot()
            assert root_snap is not None
            self.assertEqual(root_snap.code, StatusCode.WARN)

    def test_a_configured_check_keeps_the_heartbeat_ok(self):
        from little_sister.engine import HEARTBEAT_PATH
        tree = StatusTree()
        engine = Engine([_FakeCheck(path="/web")], tree)
        engine.start()
        try:
            self.assertTrue(_wait_for(
                lambda: tree.snapshot(HEARTBEAT_PATH) is not None))
        finally:
            engine.stop()
        snap = tree.snapshot(HEARTBEAT_PATH)
        assert snap is not None
        self.assertEqual(snap.code, StatusCode.OK)
        self.assertEqual(snap.reason, ())


if __name__ == '__main__':
    unittest.main()
