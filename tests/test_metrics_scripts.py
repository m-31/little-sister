import os
import platform
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import TestCase

SCRIPTS_DIR = (Path(__file__).resolve().parent.parent
               / "src" / "little_sister" / "scripts")


class MetricsScriptTests(TestCase):
    def test_emits_expected_keys(self):
        script = {"Linux": "host-metrics-linux.sh",
                  "Darwin": "host-metrics-macos.sh"}.get(platform.system())
        if script is None or not shutil.which("bash"):
            self.skipTest("needs bash on Linux/macOS")
        completed = subprocess.run(
            ["bash", str(SCRIPTS_DIR / script)],
            capture_output=True, text=True, timeout=30)
        self.assertEqual(completed.returncode, 0, completed.stderr)
        metrics = dict(
            line.split("=", 1)
            for line in completed.stdout.splitlines() if "=" in line)
        for key in ("os", "hostname", "ncpu", "disk_pct", "mem_pct",
                    "cpu_pct", "load1"):
            self.assertIn(key, metrics)
        self.assertRegex(metrics["disk_pct"], r"^\d+$")

    def test_disk_from_pathless_busybox_df(self):
        # an old busybox df (QNAP) rejects -P *and* a path argument; the busybox
        # script must still report disk from a no-argument `df` listing, picking
        # the row whose mount matches the target. Linux-only (the busybox guard).
        if platform.system() != "Linux" or not shutil.which("bash"):
            self.skipTest("busybox profile targets Linux")
        script = SCRIPTS_DIR / "host-metrics-busybox.sh"
        table = (
            "Filesystem           1k-blocks      Used Available Use% Mounted on\n"
            "/dev/ram                 33709     17620     16089  52% /\n"
            "/dev/md0             971319676 887712964  83082424  91% /share/MD0_DATA\n")
        with tempfile.TemporaryDirectory() as shim:
            fake_df = Path(shim) / "df"
            fake_df.write_text(
                "#!/bin/sh\n"
                'for a in "$@"; do case "$a" in -*P*) exit 1;; -*) ;; '
                '*) exit 1;; esac; done\n'
                f"cat <<'EOF'\n{table}EOF\n")
            fake_df.chmod(0o755)
            env = dict(os.environ, PATH=f"{shim}:{os.environ['PATH']}")
            completed = subprocess.run(
                ["bash", str(script)], capture_output=True, text=True,
                timeout=30, env=env)
        metrics = dict(
            line.split("=", 1)
            for line in completed.stdout.splitlines() if "=" in line)
        self.assertEqual(metrics.get("disk_pct"), "52")     # the "/" row
        self.assertEqual(metrics.get("disk_path"), "/")

    def test_scripts_run_under_posix_sh(self):
        # guard against bashisms: the busybox script (piped to `sh -s`) and the
        # qnap script must parse + run under a strict POSIX shell — busybox ash /
        # dash — e.g. an ASUS router whose `bash` is really busybox. The busybox
        # profile guards on a Linux kernel, so this is Linux-only.
        if platform.system() != "Linux":
            self.skipTest("busybox profile targets Linux")
        if shutil.which("busybox"):
            posix = [shutil.which("busybox"), "sh"]
        elif shutil.which("dash"):
            posix = [shutil.which("dash")]
        else:
            self.skipTest("no busybox/dash to verify POSIX-sh compatibility")
        sysm = subprocess.run(
            [*posix, str(SCRIPTS_DIR / "host-metrics-busybox.sh")],
            capture_output=True, text=True, timeout=30)
        self.assertEqual(sysm.returncode, 0, sysm.stderr)
        self.assertIn("disk_pct=", sysm.stdout)
        qnap = subprocess.run(
            [*posix, str(SCRIPTS_DIR / "qnap-health.sh")],
            capture_output=True, text=True, timeout=30)
        self.assertEqual(qnap.returncode, 0, qnap.stderr)
        self.assertIn("drive_count=", qnap.stdout)

    def test_macos_script_guards_on_non_darwin(self):
        # the macOS script must refuse cleanly off-Darwin — emit profile_error and
        # no metrics — the mechanism that catches a mis-set profile.
        if platform.system() == "Darwin" or not shutil.which("bash"):
            self.skipTest("only meaningful off-Darwin")
        completed = subprocess.run(
            ["bash", str(SCRIPTS_DIR / "host-metrics-macos.sh")],
            capture_output=True, text=True, timeout=30)
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertIn("profile_error=", completed.stdout)
        self.assertNotIn("disk_pct=", completed.stdout)

    def test_memory_script_guards_on_non_darwin(self):
        # same guard for the macos-memory script (a mis-targeted config must
        # surface as a config error, not garbage metrics).
        if platform.system() == "Darwin" or not shutil.which("bash"):
            self.skipTest("only meaningful off-Darwin")
        completed = subprocess.run(
            ["bash", str(SCRIPTS_DIR / "memory-macos.sh"), "FindMy.app"],
            capture_output=True, text=True, timeout=30)
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertIn("profile_error=", completed.stdout)
        self.assertNotIn("pressure_level=", completed.stdout)
        self.assertNotIn("proc_count=", completed.stdout)

    def test_memory_script_emits_expected_keys_on_darwin(self):
        # real-host coverage on a Mac (CI is Linux and skips): the memory script
        # must report pressure/swap/compressor and match its own pattern arg.
        if platform.system() != "Darwin" or not shutil.which("bash"):
            self.skipTest("needs macOS")
        completed = subprocess.run(
            ["bash", str(SCRIPTS_DIR / "memory-macos.sh"), "kernel_task"],
            capture_output=True, text=True, timeout=30)
        self.assertEqual(completed.returncode, 0, completed.stderr)
        metrics = dict(
            line.split("=", 1)
            for line in completed.stdout.splitlines() if "=" in line)
        for key in ("pressure_level", "swap_used_mb", "compressor_pct",
                    "proc1_count", "proc_count"):
            self.assertIn(key, metrics)
        self.assertRegex(metrics["compressor_pct"], r"^\d+$")

    def test_linux_script_rejects_busybox_userland(self):
        # the linux profile must hard-refuse a busybox userland (its awk can crash
        # and df rejects -P) — detected via busybox df's `--help` self-id, not the
        # router-unreliable `readlink -f`.
        if platform.system() != "Linux" or not shutil.which("bash"):
            self.skipTest("linux profile targets Linux")
        with tempfile.TemporaryDirectory() as shim:
            fake_df = Path(shim) / "df"
            fake_df.write_text(
                "#!/bin/sh\n"
                'if [ "$1" = --help ]; then\n'
                '  echo "BusyBox v1.30.1 (Ubuntu) multi-call binary." >&2\n'
                '  exit 1\n'
                'fi\n'
                'echo boom\n')
            fake_df.chmod(0o755)
            env = dict(os.environ, PATH=f"{shim}:{os.environ['PATH']}")
            completed = subprocess.run(
                ["bash", str(SCRIPTS_DIR / "host-metrics-linux.sh")],
                capture_output=True, text=True, timeout=30, env=env)
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertIn("profile_error=", completed.stdout)
        self.assertIn("busybox", completed.stdout)
        self.assertNotIn("disk_pct=", completed.stdout)

    def test_no_case_statement_inside_command_substitution(self):
        # bash 3.2 (macOS) mis-parses the ")" of a `case` pattern written inside
        # $(...) as the end of the command substitution — a *parse* error that
        # downs the whole script on every host. bash 5 (CI) accepts it, so this
        # can only be caught statically: scan for a `case` keyword while inside an
        # unbalanced $( … ), ignoring single-quoted regions (e.g. awk programs).
        for path in sorted(SCRIPTS_DIR.glob("*.sh")):
            src = path.read_text()
            depth = in_squote = 0
            offenders = []
            i = 0
            while i < len(src):
                ch = src[i]
                if in_squote:
                    if ch == "'":
                        in_squote = 0
                elif ch == "'":
                    in_squote = 1
                elif src[i:i + 2] == "$(":
                    depth += 1
                    i += 2
                    continue
                elif ch == ")" and depth:
                    depth -= 1
                elif (depth and src[i:i + 5] == "case "
                        and (i == 0 or src[i - 1] in " \t\n;(")):
                    offenders.append(src.count("\n", 0, i) + 1)
                i += 1
            self.assertEqual(
                offenders, [],
                f"{path.name}: `case` inside $(...) at line(s) {offenders} — "
                "move it into its own function (bash 3.2 can't parse it)")


if __name__ == "__main__":
    unittest.main()
