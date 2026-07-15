import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import TestCase, mock

from little_sister.checks import CheckError, code
from little_sister.checks.ssh.command import RemoteCommandCheck
from little_sister.checks.ssh.connect import ConnectCheck
from little_sister.checks.ssh.script import ScriptCheck
from little_sister.status import StatusCode

HERE = Path(".")
RUN = "little_sister.checks.ssh.transport.subprocess.run"

# An ssh advisory banner (decorated with ``**``) — what the transport turns into a
# WARN-worthy notice and every SSH check surfaces.
PQ_BANNER = ("** WARNING: connection is not using a post-quantum key exchange"
             " algorithm. **\n")


def _patch_run(stdout="", returncode=0, stderr=""):
    completed = subprocess.CompletedProcess([], returncode, stdout, stderr)
    return mock.patch(RUN, return_value=completed)


class ConnectCheckTests(TestCase):
    def _check(self, **extra):
        config = {"type": "ssh-connect", "path": "/c", "host": "host.example"}
        config.update(extra)
        return ConnectCheck.from_config(config, HERE)

    def test_reachable_is_ok(self):
        with _patch_run(returncode=0):
            result = self._check().run()
        self.assertEqual(result.code, StatusCode.OK)
        self.assertIn("host.example reachable", result.reason[0])

    def test_unreachable_is_error(self):
        with _patch_run(returncode=255,
                        stderr="ssh: connect to host host.example port 22: "
                               "Connection refused"):
            result = self._check().run()
        self.assertEqual(result.code, StatusCode.ERROR)
        self.assertIn("cannot reach", result.reason[0])
        self.assertIn("Connection refused", result.reason[0])

    def test_timeout_is_error(self):
        with mock.patch(RUN, side_effect=subprocess.TimeoutExpired("ssh", 2)):
            result = self._check(timeout="2s").run()
        self.assertEqual(result.code, StatusCode.ERROR)
        self.assertIn("timed out", result.reason[0])

    def test_spawn_failure_is_error(self):
        with mock.patch(RUN, side_effect=OSError("no ssh binary")):
            result = self._check().run()
        self.assertEqual(result.code, StatusCode.ERROR)
        self.assertIn("failed to run ssh", result.reason[0])

    def test_kex_advisory_warns_and_strips_banner(self):
        with _patch_run(returncode=0, stderr=PQ_BANNER):
            result = self._check().run()
        self.assertEqual(result.code, StatusCode.WARN)
        joined = " ".join(result.reason)
        self.assertIn("post-quantum", joined)
        self.assertNotIn("**", joined)

    def test_runs_true_and_sudo_prefixes(self):
        with _patch_run(returncode=0) as run:
            self._check().run()
        self.assertEqual(run.call_args.args[0][-1], "true")
        self.assertEqual(run.call_args.kwargs["input"], "")
        with _patch_run(returncode=0) as run:
            self._check(sudo=True).run()
        self.assertEqual(run.call_args.args[0][-1], "sudo -n true")

    def test_debug_surfaces_raw_stderr(self):
        with _patch_run(returncode=0, stderr="chatter on stderr"):
            result = self._check(debug=True).run()
        joined = " ".join(result.reason)
        self.assertIn("debug: exit=0", joined)
        self.assertIn("chatter on stderr", joined)


class RemoteCommandCheckTests(TestCase):
    def _check(self, command="echo hi", **extra):
        config = {"type": "ssh-command", "path": "/c", "host": "h",
                  "command": command}
        config.update(extra)
        return RemoteCommandCheck.from_config(config, HERE)

    def test_ok_on_exit_zero_with_output_reason(self):
        with _patch_run(stdout="hello\n", returncode=0):
            result = self._check().run()
        self.assertEqual((result.code, result.reason),
                         (StatusCode.OK, [code("hello")]))

    def test_nonzero_is_error_with_captured_output(self):
        with _patch_run(stdout="", returncode=3, stderr="boom\n"):
            result = self._check(capture="both").run()
        self.assertEqual(result.code, StatusCode.ERROR)
        self.assertIn("boom", result.reason[0])

    def test_nonzero_without_output_reports_exit_code(self):
        with _patch_run(returncode=7):
            result = self._check().run()
        self.assertEqual(result.code, StatusCode.ERROR)
        self.assertEqual(result.reason, ["exit code 7"])

    def test_output_shortening_head(self):
        with _patch_run(stdout="abcdef", returncode=0):
            result = self._check(max_chars=3, keep="head").run()
        self.assertEqual(result.reason, [code("abc")])

    def test_connection_failure_falls_back_to_stderr(self):
        # capture defaults to stdout; a connection failure (empty stdout) still
        # surfaces ssh's own stderr rather than a bare exit code.
        with _patch_run(stdout="", returncode=255,
                        stderr="ssh: connect ... Connection refused"):
            result = self._check().run()
        self.assertEqual(result.code, StatusCode.ERROR)
        self.assertIn("Connection refused", result.reason[0])

    def test_kex_advisory_warns_on_success(self):
        with _patch_run(stdout="ok\n", returncode=0, stderr=PQ_BANNER):
            result = self._check().run()
        self.assertEqual(result.code, StatusCode.WARN)
        joined = " ".join(result.reason)
        self.assertIn("ok", joined)
        self.assertIn("post-quantum", joined)

    def test_passes_command_through_and_sudo_prefixes(self):
        with _patch_run(stdout="x", returncode=0) as run:
            self._check(command="df -h").run()
        self.assertEqual(run.call_args.args[0][-1], "df -h")
        with _patch_run(stdout="x", returncode=0) as run:
            self._check(command="df -h", sudo=True).run()
        self.assertEqual(run.call_args.args[0][-1], "sudo -n df -h")

    def test_requires_a_command(self):
        with self.assertRaises(CheckError):
            RemoteCommandCheck.from_config(
                {"type": "ssh-command", "path": "/c", "host": "h"}, HERE)

    def test_command_must_be_a_string(self):
        with self.assertRaises(CheckError):
            RemoteCommandCheck.from_config(
                {"type": "ssh-command", "path": "/c", "host": "h",
                 "command": ["df", "-h"]}, HERE)

    def test_invalid_capture_rejected(self):
        with self.assertRaises(CheckError):
            RemoteCommandCheck.from_config(
                {"type": "ssh-command", "path": "/c", "host": "h",
                 "command": "x", "capture": "nonsense"}, HERE)


class ScriptCheckTests(TestCase):
    def _check(self, directory, **extra):
        (Path(directory) / "do.sh").write_text("echo hi\n")
        config = {"type": "ssh-script", "path": "/s", "host": "h",
                  "script": "do.sh"}
        config.update(extra)
        return ScriptCheck.from_config(config, Path(directory))

    def test_ok_pipes_script_and_returns_output(self):
        with tempfile.TemporaryDirectory() as directory:
            with _patch_run(stdout="output\n", returncode=0) as run:
                result = self._check(directory).run()
        self.assertEqual((result.code, result.reason),
                         (StatusCode.OK, [code("output")]))
        self.assertEqual(run.call_args.kwargs["input"], "echo hi\n")
        self.assertEqual(run.call_args.args[0][-1], "bash -s --")

    def test_interpreter_override(self):
        with tempfile.TemporaryDirectory() as directory:
            with _patch_run(stdout="x", returncode=0) as run:
                self._check(directory, interpreter="sh").run()
        self.assertEqual(run.call_args.args[0][-1], "sh -s --")

    def test_nonzero_is_error(self):
        with tempfile.TemporaryDirectory() as directory:
            with _patch_run(stdout="nope\n", returncode=1):
                result = self._check(directory).run()
        self.assertEqual(result.code, StatusCode.ERROR)
        self.assertIn("nope", result.reason[0])

    def test_kex_advisory_warns_on_success(self):
        with tempfile.TemporaryDirectory() as directory:
            with _patch_run(stdout="x\n", returncode=0, stderr=PQ_BANNER):
                result = self._check(directory).run()
        self.assertEqual(result.code, StatusCode.WARN)
        self.assertIn("post-quantum", " ".join(result.reason))

    def test_requires_a_script(self):
        with self.assertRaises(CheckError):
            ScriptCheck.from_config(
                {"type": "ssh-script", "path": "/s", "host": "h"}, HERE)

    def test_missing_script_file_raises(self):
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaises(CheckError):
                ScriptCheck.from_config(
                    {"type": "ssh-script", "path": "/s", "host": "h",
                     "script": "nope.sh"}, Path(directory))


if __name__ == "__main__":
    unittest.main()
