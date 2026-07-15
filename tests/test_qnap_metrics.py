import os
import platform
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import TestCase, mock

from little_sister.checks import CheckError
from little_sister.checks.ssh.qnap_metrics import QnapMetricsCheck
from little_sister.status import StatusCode

QNAP_SAMPLE = (
    "model=TS-419P\nsys_temp_c=41\n"
    "drive1_bay=1\ndrive1_temp_c=42\ndrive1_smart=GOOD\n"
    "drive2_bay=2\ndrive2_temp_c=42\ndrive2_smart=GOOD\n"
    "drive3_bay=3\ndrive3_temp_c=43\ndrive3_smart=GOOD\n"
    "drive4_bay=4\ndrive4_temp_c=44\ndrive4_smart=Warning\n"
    "drive_count=4\n")


class QnapMetricsCheckTests(TestCase):
    def _check(self, directory, **extra):
        (Path(directory) / "qnap.sh").write_text("echo hi\n")
        config = {"type": "qnap-metrics", "path": "/nexus", "host": "nexus62",
                  "script": "qnap.sh"}
        config.update(extra)
        return QnapMetricsCheck.from_config(config, Path(directory))

    def _run(self, directory, stdout, *, returncode=0, stderr="", **extra):
        check = self._check(directory, **extra)
        completed = subprocess.CompletedProcess([], returncode, stdout, stderr)
        with mock.patch("little_sister.checks.ssh.transport.subprocess.run",
                        return_value=completed):
            return check.run()

    def _kids(self, result):
        return {child.name: child for child in result.children}

    def test_temperature_and_smart_branches(self):
        with tempfile.TemporaryDirectory() as directory:
            result = self._run(directory, QNAP_SAMPLE)
        self.assertEqual(result.code, StatusCode.UNDEFINED)
        kids = self._kids(result)
        self.assertEqual(set(kids), {"temperature", "smart"})
        temps = {c.name: c for c in kids["temperature"].children}
        self.assertEqual(set(temps),
                         {"system", "drive1", "drive2", "drive3", "drive4"})
        self.assertEqual(temps["system"].reason, ["41 °C"])
        self.assertEqual(temps["system"].code, StatusCode.OK)
        self.assertEqual(temps["drive4"].reason, ["44 °C"])
        smart = {c.name: c for c in kids["smart"].children}
        self.assertEqual(smart["drive1"].code, StatusCode.OK)
        self.assertEqual(smart["drive1"].reason, ["GOOD"])
        self.assertEqual(smart["drive4"].code, StatusCode.WARN)   # Warning
        self.assertEqual(smart["drive4"].reason, ["Warning"])

    def test_temperature_children_carry_thresholds(self):
        with tempfile.TemporaryDirectory() as directory:
            result = self._run(directory, QNAP_SAMPLE)
        kids = self._kids(result)
        temps = {c.name: c for c in kids["temperature"].children}
        self.assertIn("50 °C", temps["system"].config)   # default warn
        self.assertIn("60 °C", temps["system"].config)   # default error
        # the shared host container stays bare
        self.assertEqual(result.config, "")

    def test_descriptions_override_branch_descriptions(self):
        with tempfile.TemporaryDirectory() as directory:
            result = self._run(
                directory, QNAP_SAMPLE,
                descriptions={"temperature": "thermals", "smart": "drive health"})
        kids = self._kids(result)
        self.assertEqual(kids["temperature"].description, "thermals")
        self.assertEqual(kids["smart"].description, "drive health")

    def test_temperature_grading(self):
        stdout = ("sys_temp_c=65\n"
                  "drive1_bay=1\ndrive1_temp_c=55\ndrive1_smart=GOOD\n"
                  "drive_count=1\n")
        with tempfile.TemporaryDirectory() as directory:
            result = self._run(directory, stdout)
        temps = {c.name: c for c in self._kids(result)["temperature"].children}
        self.assertEqual(temps["system"].code, StatusCode.ERROR)   # 65 (>=60)
        self.assertEqual(temps["drive1"].code, StatusCode.WARN)    # 55 (50..60)

    def test_temperature_threshold_override(self):
        stdout = "drive1_bay=1\ndrive1_temp_c=44\ndrive1_smart=GOOD\ndrive_count=1\n"
        with tempfile.TemporaryDirectory() as directory:
            result = self._run(
                directory, stdout,
                thresholds={"temperature": {"warn": 40, "error": 45}})
        temps = {c.name: c for c in self._kids(result)["temperature"].children}
        self.assertEqual(temps["drive1"].code, StatusCode.WARN)    # 44 (40..45)

    def test_smart_failure_is_error(self):
        stdout = "drive1_bay=1\ndrive1_smart=Abnormal\ndrive_count=1\n"
        with tempfile.TemporaryDirectory() as directory:
            result = self._run(directory, stdout)
        smart = {c.name: c for c in self._kids(result)["smart"].children}
        self.assertEqual(smart["drive1"].code, StatusCode.ERROR)

    def test_no_qnap_data_is_failure(self):
        with tempfile.TemporaryDirectory() as directory:
            result = self._run(directory, "some banner\n")
        kids = self._kids(result)
        self.assertEqual(kids["temperature"].code, StatusCode.ERROR)
        self.assertEqual(kids["smart"].code, StatusCode.ERROR)
        self.assertIn("no QNAP data", kids["temperature"].reason[0])

    def test_connection_failure_marks_aspects_error(self):
        with tempfile.TemporaryDirectory() as directory:
            result = self._run(directory, "", returncode=255,
                                stderr="ssh: connect ... Connection refused")
        kids = self._kids(result)
        self.assertEqual(kids["temperature"].code, StatusCode.ERROR)
        self.assertIn("Connection refused", kids["temperature"].reason[0])

    def test_requires_host(self):
        with tempfile.TemporaryDirectory() as directory:
            (Path(directory) / "qnap.sh").write_text("echo hi\n")
            with self.assertRaises(CheckError):
                QnapMetricsCheck.from_config(
                    {"type": "qnap-metrics", "path": "/x", "script": "qnap.sh"},
                    Path(directory))

    def test_script_against_fake_getsysinfo(self):
        if platform.system() not in ("Linux", "Darwin") or not shutil.which("bash"):
            self.skipTest("needs bash on Linux/macOS")
        script = (Path(__file__).resolve().parent.parent / "src" /
                  "little_sister" / "scripts" / "qnap-health.sh")
        with tempfile.TemporaryDirectory() as shim:
            fake = Path(shim) / "getsysinfo"
            fake.write_text(
                "#!/bin/sh\n"
                'case "$1" in\n'
                "  hdnum) echo 2;;\n"
                '  systmp) echo "41 C/106 F";;\n'
                "  hdstatus) echo 0;;\n"
                '  hdtmp) echo "42 C/107 F";;\n'
                '  hdsmart) [ "$2" = 2 ] && echo Warning || echo GOOD;;\n'
                '  *) echo "";;\n'
                "esac\n")
            fake.chmod(0o755)
            env = dict(os.environ, PATH=f"{shim}:{os.environ['PATH']}")
            completed = subprocess.run(
                ["bash", str(script)], capture_output=True, text=True,
                timeout=30, env=env)
        metrics = dict(
            line.split("=", 1)
            for line in completed.stdout.splitlines() if "=" in line)
        self.assertEqual(metrics.get("sys_temp_c"), "41")
        self.assertEqual(metrics.get("drive_count"), "2")
        self.assertEqual(metrics.get("drive2_smart"), "Warning")


if __name__ == "__main__":
    unittest.main()
