import os
import platform
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import TestCase, mock

from little_sister.checks import CheckError
from little_sister.checks.ssh.macos_memory import MacosMemoryCheck
from little_sister.status import StatusCode

MEMORY_SAMPLE = (
    "os=Darwin\npressure_level=1\nfree_pct=62\n"
    "swap_total_mb=3072\nswap_used_mb=1419\n"
    "mem_total_kb=8388608\ncompressor_kb=1258291\ncompressor_pct=15\n"
    "proc1_pattern=FindMy.app\nproc1_count=1\nproc1_rss_kb=421888\n"
    "proc1_elapsed_seconds=7980\n"
    "proc2_pattern=System Events.app\nproc2_count=1\nproc2_rss_kb=102400\n"
    "proc2_elapsed_seconds=90061\n"
    "proc3_pattern=findmy-pull\nproc3_count=0\n"
    "proc_count=3\n")

PROCESSES = [
    {"name": "findmy", "pattern": "FindMy.app"},
    {"name": "system-events", "pattern": "System Events.app"},
    {"name": "findmy-pull", "pattern": "findmy-pull", "warn_mb": 512,
     "error_mb": 1024},
]


class MacosMemoryCheckTests(TestCase):
    def _check(self, directory, **extra):
        (Path(directory) / "memory.sh").write_text("echo hi\n")
        config = {"type": "macos-memory", "path": "/macmini/system",
                  "host": "macmini", "script": "memory.sh"}
        config.update(extra)
        return MacosMemoryCheck.from_config(config, Path(directory))

    def _run(self, directory, stdout, *, returncode=0, stderr="", **extra):
        check = self._check(directory, **extra)
        completed = subprocess.CompletedProcess([], returncode, stdout, stderr)
        with mock.patch("little_sister.checks.ssh.transport.subprocess.run",
                        return_value=completed):
            return check.run()

    def _kids(self, result):
        return {child.name: child for child in result.children}

    def test_reports_all_aspects(self):
        with tempfile.TemporaryDirectory() as directory:
            result = self._run(directory, MEMORY_SAMPLE, processes=PROCESSES)
        self.assertEqual(result.code, StatusCode.UNDEFINED)
        kids = self._kids(result)
        self.assertEqual(set(kids), {"pressure", "swap", "compressor",
                                     "processes"})
        self.assertEqual(kids["pressure"].code, StatusCode.OK)
        self.assertEqual(kids["pressure"].reason,
                         ["normal — 62% of memory free system-wide"])
        self.assertEqual(kids["swap"].code, StatusCode.OK)
        self.assertEqual(kids["swap"].reason,
                         ["1419 MB used of 3072 MB allocated"])
        self.assertEqual(kids["compressor"].code, StatusCode.OK)
        self.assertEqual(kids["compressor"].reason,
                         ["15% compressed — 1.2 GiB of 8.0 GiB RAM"])

    def test_processes_branch_grades_rss(self):
        with tempfile.TemporaryDirectory() as directory:
            result = self._run(directory, MEMORY_SAMPLE, processes=PROCESSES)
        procs = {c.name: c for c in self._kids(result)["processes"].children}
        self.assertEqual(set(procs), {"findmy", "system-events", "findmy-pull"})
        self.assertEqual(procs["findmy"].code, StatusCode.OK)     # 412 MB
        self.assertEqual(procs["findmy"].reason,
                         ["412 MB RSS over 1 process, oldest up 2h 13m"])
        self.assertEqual(procs["system-events"].reason,
                         ["100 MB RSS over 1 process, oldest up 1d 1h"])
        # not running is OK by design — liveness belongs to other checks
        self.assertEqual(procs["findmy-pull"].code, StatusCode.OK)
        self.assertEqual(procs["findmy-pull"].reason, ["not running"])

    def test_no_processes_configured_omits_branch(self):
        with tempfile.TemporaryDirectory() as directory:
            result = self._run(directory, MEMORY_SAMPLE)
        self.assertEqual(set(self._kids(result)),
                         {"pressure", "swap", "compressor"})

    def test_pressure_levels_grade_semantically(self):
        for level, expected in ((1, StatusCode.OK), (2, StatusCode.WARN),
                                (4, StatusCode.ERROR)):
            with tempfile.TemporaryDirectory() as directory:
                result = self._run(directory, f"pressure_level={level}\n")
            self.assertEqual(self._kids(result)["pressure"].code, expected,
                             f"level {level}")

    def test_swap_and_compressor_grading_and_overrides(self):
        stdout = "pressure_level=1\nswap_used_mb=5000\ncompressor_pct=40\n"
        with tempfile.TemporaryDirectory() as directory:
            result = self._run(directory, stdout)
        kids = self._kids(result)
        self.assertEqual(kids["swap"].code, StatusCode.WARN)        # 5000 ≥ 4096
        self.assertEqual(kids["compressor"].code, StatusCode.WARN)  # 40 ≥ 35
        with tempfile.TemporaryDirectory() as directory:
            result = self._run(
                directory, stdout,
                thresholds={"swap": {"warn": 1000, "error": 4500},
                            "compressor": {"warn": 10, "error": 30}})
        kids = self._kids(result)
        self.assertEqual(kids["swap"].code, StatusCode.ERROR)
        self.assertEqual(kids["compressor"].code, StatusCode.ERROR)

    def test_process_rss_grading_uses_per_process_thresholds(self):
        stdout = ("pressure_level=1\n"
                  "proc1_pattern=findmy-pull\nproc1_count=2\n"
                  "proc1_rss_kb=614400\nproc_count=1\n")   # 600 MB over 2 procs
        with tempfile.TemporaryDirectory() as directory:
            result = self._run(
                directory, stdout,
                processes=[{"name": "findmy-pull", "pattern": "findmy-pull",
                            "warn_mb": 512, "error_mb": 1024}])
        procs = {c.name: c for c in self._kids(result)["processes"].children}
        self.assertEqual(procs["findmy-pull"].code, StatusCode.WARN)
        # no elapsed key (older script): the reason simply omits the uptime
        self.assertEqual(procs["findmy-pull"].reason,
                         ["600 MB RSS over 2 processes"])

    def test_missing_proc_keys_are_unavailable(self):
        with tempfile.TemporaryDirectory() as directory:
            result = self._run(directory, "pressure_level=1\n",
                               processes=PROCESSES)
        procs = {c.name: c for c in self._kids(result)["processes"].children}
        self.assertEqual(procs["findmy"].code, StatusCode.WARN)
        self.assertEqual(procs["findmy"].reason, ["unavailable"])

    def test_leaves_carry_thresholds_and_pattern(self):
        with tempfile.TemporaryDirectory() as directory:
            result = self._run(directory, MEMORY_SAMPLE, processes=PROCESSES)
        kids = self._kids(result)
        self.assertIn("4096 MB", kids["swap"].config)
        self.assertIn("50%", kids["compressor"].config)
        procs = {c.name: c for c in kids["processes"].children}
        self.assertIn("FindMy.app", procs["findmy"].config)
        self.assertIn("512 MB", procs["findmy-pull"].config)
        # the shared host container stays bare
        self.assertEqual(result.config, "")

    def test_descriptions_override(self):
        with tempfile.TemporaryDirectory() as directory:
            result = self._run(directory, MEMORY_SAMPLE,
                               descriptions={"compressor": "panic precursor"})
        self.assertEqual(self._kids(result)["compressor"].description,
                         "panic precursor")

    def test_profile_mismatch_is_warn(self):
        stdout = "os=Linux\nprofile_error=macos-memory expects a Darwin host\n"
        with tempfile.TemporaryDirectory() as directory:
            result = self._run(directory, stdout)
        kids = self._kids(result)
        self.assertEqual(kids["pressure"].code, StatusCode.WARN)
        self.assertIn("profile mismatch", kids["pressure"].reason[0])

    def test_no_memory_data_is_failure(self):
        with tempfile.TemporaryDirectory() as directory:
            result = self._run(directory, "some banner\n", processes=PROCESSES)
        kids = self._kids(result)
        self.assertEqual(set(kids), {"pressure", "swap", "compressor",
                                     "processes"})
        for child in kids.values():
            self.assertEqual(child.code, StatusCode.ERROR)
        self.assertIn("no memory data", kids["pressure"].reason[0])

    def test_connection_failure_marks_aspects_error(self):
        with tempfile.TemporaryDirectory() as directory:
            result = self._run(directory, "", returncode=255,
                               stderr="ssh: connect ... Connection refused")
        kids = self._kids(result)
        self.assertEqual(kids["compressor"].code, StatusCode.ERROR)
        self.assertIn("Connection refused", kids["pressure"].reason[0])

    def test_script_args_carry_patterns(self):
        with tempfile.TemporaryDirectory() as directory:
            check = self._check(directory, processes=PROCESSES)
        self.assertEqual(check._script_args(),
                         ["FindMy.app\nSystem Events.app\nfindmy-pull"])
        with tempfile.TemporaryDirectory() as directory:
            self.assertEqual(self._check(directory)._script_args(), [])

    def test_owned_nodes_follow_configuration(self):
        with tempfile.TemporaryDirectory() as directory:
            with_procs = self._check(directory, processes=PROCESSES)
            without = self._check(directory)
        self.assertEqual(with_procs.owned_nodes(),
                         {"/macmini/system/pressure", "/macmini/system/swap",
                          "/macmini/system/compressor",
                          "/macmini/system/processes"})
        self.assertNotIn("/macmini/system/processes", without.owned_nodes())

    def test_requires_host(self):
        with tempfile.TemporaryDirectory() as directory:
            (Path(directory) / "memory.sh").write_text("echo hi\n")
            with self.assertRaises(CheckError):
                MacosMemoryCheck.from_config(
                    {"type": "macos-memory", "path": "/x",
                     "script": "memory.sh"}, Path(directory))

    def test_process_config_validation(self):
        for processes in ("FindMy",                      # not a list
                          [{"pattern": "FindMy.app"}],   # missing name
                          [{"name": "findmy"}],          # missing pattern
                          [{"name": "x", "pattern": "a"},
                           {"name": "x", "pattern": "b"}],   # duplicate name
                          [{"name": "x", "pattern": "a",
                            "warn_mb": "lots"}]):        # non-numeric bound
            with tempfile.TemporaryDirectory() as directory:
                with self.assertRaises(CheckError, msg=repr(processes)):
                    self._check(directory, processes=processes)

    def test_script_against_fake_tools(self):
        # End-to-end script run with shimmed Darwin tools — validates parsing,
        # pattern matching (incl. spaces) and RSS summing without a real Mac.
        # bash-3.2 behavior itself still needs one run on a real macOS host.
        if platform.system() not in ("Linux", "Darwin") or not shutil.which("bash"):
            self.skipTest("needs bash on Linux/macOS")
        script = (Path(__file__).resolve().parent.parent / "src" /
                  "little_sister" / "scripts" / "memory-macos.sh")
        ps_table = (
            "  310  1 415000   05:12:33 "
            "/System/Applications/FindMy.app/Contents/MacOS/FindMy\n"
            "  311  1  6888      12:45 "
            "/System/Applications/FindMy.app/Contents/MacOS/helper\n"
            "  400  1 99000 1-00:00:10 /System/Library/CoreServices/"
            "System Events.app/Contents/MacOS/System Events\n"
            "  500  1 51200      42:17 /usr/bin/python3 /x/.venv/bin/findmy-pull\n")
        with tempfile.TemporaryDirectory() as shim:
            for name, body in (
                    ("uname", 'case "$1" in -s|"") echo Darwin;; '
                              "*) echo Darwin fake;; esac\n"),
                    ("sysctl", 'case "$2" in\n'
                               "  kern.memorystatus_vm_pressure_level) echo 2;;\n"
                               '  vm.swapusage) echo "total = 3072.00M  used = '
                               '1418.75M  free = 1653.25M  (encrypted)";;\n'
                               "  hw.memsize) echo 8589934592;;\n"
                               "esac\n"),
                    ("vm_stat", 'echo "Mach Virtual Memory Statistics: '
                                '(page size of 16384 bytes)"\n'
                                'echo "Pages occupied by compressor:      '
                                '76800."\n'),
                    ("memory_pressure", 'echo "System-wide memory free '
                                        'percentage: 43%"\n'),
                    ("ps", f"cat <<'TABLE'\n{ps_table}TABLE\n")):
                tool = Path(shim) / name
                tool.write_text("#!/bin/sh\n" + body)
                tool.chmod(0o755)
            env = dict(os.environ, PATH=f"{shim}:{os.environ['PATH']}")
            completed = subprocess.run(
                ["bash", str(script),
                 "FindMy.app\nSystem Events.app\nfindmy-pull"],
                capture_output=True, text=True, timeout=30, env=env)
        self.assertEqual(completed.returncode, 0, completed.stderr)
        metrics = dict(
            line.split("=", 1)
            for line in completed.stdout.splitlines() if "=" in line)
        self.assertEqual(metrics.get("pressure_level"), "2")
        self.assertEqual(metrics.get("free_pct"), "43")
        self.assertEqual(metrics.get("swap_total_mb"), "3072")
        self.assertEqual(metrics.get("swap_used_mb"), "1419")
        self.assertEqual(metrics.get("compressor_pct"), "15")   # 1.2G of 8G
        self.assertEqual(metrics.get("proc1_count"), "2")       # app + helper
        self.assertEqual(metrics.get("proc1_rss_kb"), "421888")
        self.assertEqual(metrics.get("proc1_elapsed_seconds"), "18753")  # oldest
        self.assertEqual(metrics.get("proc2_count"), "1")       # space in pattern
        self.assertEqual(metrics.get("proc2_rss_kb"), "99000")
        self.assertEqual(metrics.get("proc2_elapsed_seconds"), "86410")  # dd- form
        self.assertEqual(metrics.get("proc3_count"), "1")
        self.assertEqual(metrics.get("proc3_elapsed_seconds"), "2537")   # mm:ss
        self.assertEqual(metrics.get("proc_count"), "3")


if __name__ == "__main__":
    unittest.main()
