"""A line a grading decided names that grading (ADR-0131 decision 1): the entry
carries it from ``Check.verdict`` through the engine to the tree, and the node's own
page shows it beside the line — the name whose keys a deployment writes to grade the
line differently — after the form the line was written from, where there is one."""
from __future__ import annotations

import os
import tempfile
import time
from datetime import UTC, datetime
from pathlib import Path
from unittest import TestCase

from little_sister import app as app_module
from little_sister.checks import Measurement
from little_sister.checks.file import FileFreshnessCheck
from little_sister.checks.ssh import HostMetricsCheck
from little_sister.engine import Engine
from little_sister.reasons import Entry
from little_sister.status import StatusCode
from little_sister.tree import StatusTree

HERE = Path(".")


class TheGradingOfALineTests(TestCase):
    def setUp(self) -> None:
        app_module.app.config["TESTING"] = True
        self.addCleanup(setattr, app_module, "status_tree", app_module.status_tree)
        self.tree = StatusTree()
        app_module.status_tree = self.tree
        self.client = app_module.app.test_client()
        self.client.post("/login", data={"username": "pan", "password": "12345678"})

    def test_the_grading_reaches_the_node_through_the_engine(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            beat = Path(directory) / "heartbeat"
            beat.write_text("", encoding="utf-8")
            an_hour_ago = time.time() - 3600
            os.utime(beat, (an_hour_ago, an_hour_ago))
            check = FileFreshnessCheck.from_config(
                {"path": "/beat", "file": str(beat), "max_age_warn": "20m",
                 "max_age_reason": "The job touches it every ten minutes."}, HERE)
            Engine([check], self.tree).run_once()
        snapshot = self.tree.snapshot("/beat")
        assert snapshot is not None
        (line,) = snapshot.reasons
        self.assertEqual((line.grading, line.form), ("max_age", ""))
        self.assertTrue(line.text.startswith("stale: last changed "), line.text)
        self.assertTrue(line.text.endswith(
            " ago (max 20m) — The job touches it every ten minutes."), line.text)

    def test_the_engine_hands_on_what_each_check_grades(self) -> None:
        check = FileFreshnessCheck.from_config(
            {"path": "/beat", "file": "/var/heartbeat"}, HERE)
        (info,) = Engine([check], StatusTree()).info().checks
        self.assertEqual(info.gradings, check.grading_declarations)
        self.assertEqual([grading.name for grading in info.gradings], ["max_age"])

    def test_a_line_no_grading_decided_names_none(self) -> None:
        self.tree.upsert("/db", StatusCode.ERROR, "connection refused")
        snapshot = self.tree.snapshot("/db")
        assert snapshot is not None
        self.assertEqual([line.grading for line in snapshot.reasons], [""])

    def test_the_nodes_page_shows_it_beside_the_line(self) -> None:
        self.tree.upsert("/host", StatusCode.WARN, [
            Entry("disk", "disk: 85% used", code=StatusCode.WARN, grading="max_disk"),
            Entry("build", "CI: failed (#41)", code=StatusCode.ERROR,
                  form="actions.verdict", grading="actions.conclusion_map"),
            Entry("lint", "lint passed", code=StatusCode.OK)], members=True)
        body = self.client.get("/status/host").get_data(as_text=True)
        disk, build, lint = body.split('class="small check-reason')[1:4]
        self.assertIn('<p class="reason-form small">Graded by <code>max_disk</code>'
                      '</p>', disk)
        self.assertIn('<p class="reason-form small">Written from the form '
                      '<code>actions.verdict</code> · graded by '
                      '<code>actions.conclusion_map</code></p>', build)
        self.assertNotIn("reason-form", lint)

    def test_a_grading_switched_off_names_no_grading_on_its_line(self) -> None:
        """``max_load: null`` grades the load not at all, so its line names no
        grading — the node's page says no *graded by* where the card says *not
        graded* — while the disk's, which holds its levels, names ``max_disk``."""
        with tempfile.TemporaryDirectory() as directory:
            (Path(directory) / "metrics.sh").write_text("echo hi\n")
            check = HostMetricsCheck.from_config(
                {"type": "host-metrics", "path": "/host", "host": "host.example",
                 "script": "metrics.sh", "max_load": None}, Path(directory))
        result = check.grade((Measurement(record={
            "exit_code": 0, "disk_pct": 93, "disk_avail_kb": 70000,
            "disk_total_kb": 1000000, "disk_path": "/", "mem_pct": 50,
            "cpu_pct": 7, "load1": 9.4, "ncpu": 4, "os": "Linux",
            "hostname": "alpha", "uptime_seconds": 90061}),), datetime.now(UTC))
        named = {child.name: [entry.grading for entry in child.reason_entries]
                 for child in result.children}
        self.assertEqual((named["load"], named["disk"], named["memory"]),
                         ([""], ["max_disk"], ["max_memory"]))
        self.assertEqual(check.grading_summary("max_load"), None)
