import threading
import time
import unittest
from datetime import datetime, timedelta
from unittest import TestCase

from little_sister.checks.base import Check, CheckResult
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

    def test_engine_heartbeats_self_tile(self):
        from little_sister.engine import HEARTBEAT_PATH
        tree = StatusTree()
        engine = Engine([_FakeCheck(path="/x")], tree)
        engine.start()
        try:
            self.assertTrue(_wait_for(
                lambda: tree.snapshot(HEARTBEAT_PATH) is not None))
        finally:
            engine.stop()


if __name__ == '__main__':
    unittest.main()
