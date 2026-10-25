import json
import tempfile
import unittest
from pathlib import Path
from unittest import TestCase, mock

from little_sister import process
from little_sister.checks import CheckError, code
from little_sister.checks.output import OUTPUT_RECORD
from little_sister.checks.ssh.command import RemoteCommandCheck
from little_sister.checks.ssh.connect import ConnectCheck
from little_sister.checks.ssh.connection import SshConnection
from little_sister.checks.ssh.host_metrics import PROFILES
from little_sister.checks.ssh.script import ScriptCheck
from little_sister.limits import RECORD_LIMIT, Limits, capacity
from little_sister.status import StatusCode
from tests.running import (
    SSH_RUN,
    finished,
    record_of,
    remote_args,
    remote_parts,
    run_check,
)

HERE = Path(".")
RUN = SSH_RUN

# An ssh advisory banner (decorated with ``**``) — what the transport turns into a
# WARN-worthy notice and every SSH check surfaces.
PQ_BANNER = ("** WARNING: connection is not using a post-quantum key exchange"
             " algorithm. **\n")


def _patch_run(stdout="", returncode=0, stderr=""):
    return mock.patch(RUN, return_value=finished(stdout, returncode, stderr))


def _start(check, record_limit):
    """What a start at ``record_limit`` says of ``check`` (ADR-0075)."""
    return capacity([check], max_workers=8,
                    limits=Limits(record_limit=record_limit), record_floor=0)


#: The longest command the oldest server the family reads takes. Dropbear 2012.55
#: refuses an exec request whose command is over its MAX_CMD_LEN, 1,024 bytes, before
#: the 1,400 its MAX_STRING_LEN lets any string be (both in its sysoptions.h) — so it
#: is this, and not 1,400, that a command line has to stay within for that server.
OLDEST_DROPBEAR_COMMAND = 1024


def _no_ssh(*args, **kwargs):
    raise process.NotStarted("ssh could not be started") from OSError("no ssh binary")


class ConnectCheckTests(TestCase):
    def _check(self, **extra):
        config = {"type": "ssh-connect", "path": "/c", "host": "host.example"}
        config.update(extra)
        return ConnectCheck.from_config(config, HERE)

    def test_reachable_is_ok(self):
        with _patch_run(returncode=0):
            result = run_check(self._check())
        self.assertEqual(result.code, StatusCode.OK)
        self.assertIn("host.example reachable", result.reason[0])

    def test_the_object_is_the_host_and_the_reading_is_how_it_answered(self):
        """The host is what this check reads; running `true` is only how it reads
        it. The reading is therefore about the host, and a failure to answer *is*
        the measurement rather than an obstacle to it."""
        check = self._check()
        self.assertEqual(check.subject, "host.example")
        with _patch_run(returncode=0):
            healthy = record_of(check)
        self.assertEqual(healthy["exit_code"], 0)
        self.assertNotIn("error", healthy)
        with _patch_run(returncode=255, stderr="Connection refused"):
            refused = record_of(check)
        self.assertEqual(refused["exit_code"], 255)
        self.assertIn("Connection refused", refused["detail"])

    def test_a_transport_record_cannot_outgrow_what_it_declares(self):
        """Every free-text field in one is clipped in the bytes the seam counts,
        which is what makes the declaration a ceiling rather than a hope — and
        the worst case is not ASCII: JSON writes an emoji as a surrogate pair."""
        for chatter in ("x" * 4000, "ä" * 4000, "\U0001f600" * 4000):
            with self.subTest(kind=chatter[0]):
                check = self._check(debug=True)
                with _patch_run(returncode=13, stderr=chatter):
                    record = record_of(check)
                weighed = len(json.dumps(record).encode("utf-8"))
                self.assertLessEqual(weighed, check.expected_record())
                self.assertLessEqual(check.expected_record(), RECORD_LIMIT)

    def test_unreachable_is_error(self):
        with _patch_run(returncode=255,
                        stderr="ssh: connect to host host.example port 22: "
                               "Connection refused"):
            result = run_check(self._check())
        self.assertEqual(result.code, StatusCode.ERROR)
        self.assertIn("cannot reach", result.reason[0])
        self.assertIn("Connection refused", result.reason[0])

    def test_timeout_is_error(self):
        with mock.patch(RUN, return_value=finished(returncode=-15,
                                                   ended=process.Ended.BOUND)):
            result = run_check(self._check(timeout="2s"))
        self.assertEqual(result.code, StatusCode.ERROR)
        self.assertIn("timed out", result.reason[0])

    def test_spawn_failure_is_error(self):
        with mock.patch(RUN, side_effect=_no_ssh):
            result = run_check(self._check())
        self.assertEqual(result.code, StatusCode.ERROR)
        self.assertIn("failed to run ssh", result.reason[0])

    def test_kex_advisory_warns_and_strips_banner(self):
        with _patch_run(returncode=0, stderr=PQ_BANNER):
            result = run_check(self._check())
        self.assertEqual(result.code, StatusCode.WARN)
        joined = " ".join(result.reason)
        self.assertIn("post-quantum", joined)
        self.assertNotIn("**", joined)

    def test_runs_true_and_sudo_prefixes(self):
        with _patch_run(returncode=0) as run:
            run_check(self._check())
        self.assertEqual(remote_parts(run), ("true", None))
        self.assertEqual(run.call_args.kwargs["send"], b"0\n")
        with _patch_run(returncode=0) as run:
            run_check(self._check(sudo=True))
        self.assertEqual(remote_parts(run)[0], "sudo -n true")

    def test_debug_surfaces_raw_stderr(self):
        with _patch_run(returncode=0, stderr="chatter on stderr"):
            result = run_check(self._check(debug=True))
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
            result = run_check(self._check())
        self.assertEqual((result.code, result.reason),
                         (StatusCode.OK, [code("hello")]))

    def test_nonzero_is_error_with_captured_output(self):
        with _patch_run(stdout="", returncode=3, stderr="boom\n"):
            result = run_check(self._check(capture="both"))
        self.assertEqual(result.code, StatusCode.ERROR)
        self.assertIn("boom", result.reason[0])

    def test_nonzero_without_output_reports_exit_code(self):
        with _patch_run(returncode=7):
            result = run_check(self._check())
        self.assertEqual(result.code, StatusCode.ERROR)
        self.assertEqual(result.reason, ["exit code 7"])

    def test_output_shortening_head(self):
        with _patch_run(stdout="abcdef", returncode=0):
            result = run_check(self._check(max_chars=3, keep="head"))
        self.assertEqual(result.reason, [code("abc")])

    def test_connection_failure_falls_back_to_stderr(self):
        # capture defaults to stdout; a connection failure (empty stdout) still
        # surfaces ssh's own stderr rather than a bare exit code.
        with _patch_run(stdout="", returncode=255,
                        stderr="ssh: connect ... Connection refused"):
            result = run_check(self._check())
        self.assertEqual(result.code, StatusCode.ERROR)
        self.assertIn("Connection refused", result.reason[0])

    def test_kex_advisory_warns_on_success(self):
        with _patch_run(stdout="ok\n", returncode=0, stderr=PQ_BANNER):
            result = run_check(self._check())
        self.assertEqual(result.code, StatusCode.WARN)
        joined = " ".join(result.reason)
        self.assertIn("ok", joined)
        self.assertIn("post-quantum", joined)

    def test_passes_command_through_and_sudo_prefixes(self):
        with _patch_run(stdout="x", returncode=0) as run:
            run_check(self._check(command="df -h"))
        self.assertEqual(remote_parts(run)[0], "df -h")
        with _patch_run(stdout="x", returncode=0) as run:
            run_check(self._check(command="df -h", sudo=True))
        self.assertEqual(remote_parts(run)[0], "sudo -n df -h")

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

    def test_the_transport_half_and_the_output_share_one_record(self):
        """The output's budget is what a record of `OUTPUT_RECORD` bytes leaves after
        the transport half, where the transport half used to come on top of an output
        that filled the record alone. At the default `max_chars`, in the worst
        encodings, with `debug` and without, the record weighs no more than the check
        declares, and the check declares 2,048 bytes at the most."""
        for debug in (False, True):
            for chatter in ("x" * 4000, "ä" * 4000, "\U0001f600" * 4000):
                with self.subTest(debug=debug, kind=chatter[0]):
                    check = self._check(capture="both", debug=debug)
                    with _patch_run(stdout=chatter, returncode=3, stderr=chatter):
                        record = record_of(check)
                    weighed = len(json.dumps(record).encode("utf-8"))
                    self.assertLessEqual(weighed, check.expected_record())
                    self.assertLessEqual(check.expected_record(), OUTPUT_RECORD)

    def test_the_templates_configuration_starts_at_the_default_and_at_2048(self):
        """`max_chars: 1000`, the shipped template's, which declared 2,672 bytes and
        refused the start at the default `record_limit` while the transport half came
        on top: it declares 2,048 now, so a start at the default says nothing of it,
        and one at 2,048 takes it."""
        check = self._check(capture="both", max_chars=1000)
        self.assertEqual(check.expected_record(), OUTPUT_RECORD)
        for limit in (RECORD_LIMIT, OUTPUT_RECORD):
            with self.subTest(limit=limit):
                self.assertEqual(_start(check, limit).refusals(), ())
        said = _start(check, RECORD_LIMIT).warnings()
        self.assertNotIn("record", [limit for limit, _ in said])


class CommandLineTests(TestCase):
    """What the command line carries is the wrapper and the command, never the script
    or its arguments (ADR-0089 decision 4), so its length is the library's to know."""

    def test_every_command_the_library_builds_fits_the_oldest_dropbear(self):
        interpreters = {"bash", "sh", *(interpreter for _, interpreter
                                        in PROFILES.values())}
        lines: dict[str, str] = {}
        with tempfile.TemporaryDirectory() as directory:
            script = Path(directory) / "s.sh"
            script.write_text("echo hi\n" * 2_000)
            arguments = ["/a/path/on/the/host"] * 50 + ["debug"]
            for sudo in (False, True):
                connection = SshConnection("host.example", sudo=sudo)
                for interpreter in sorted(interpreters):
                    with _patch_run() as run:
                        connection.run_script(str(script), interpreter, arguments)
                    lines[f"a script by {interpreter}, sudo={sudo}"] = (
                        run.call_args.args[0][-1])
                with _patch_run() as run:
                    connection.run("true")
                lines[f"the connect check's true, sudo={sudo}"] = (
                    run.call_args.args[0][-1])
        name, longest = max(lines.items(), key=lambda item: len(item[1].encode()))
        self.assertLessEqual(len(longest.encode()), OLDEST_DROPBEAR_COMMAND, name)


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
                result = run_check(self._check(directory))
        self.assertEqual((result.code, result.reason),
                         (StatusCode.OK, [code("output")]))
        self.assertEqual(remote_parts(run), ("bash -s", "echo hi\n"))
        self.assertEqual(remote_args(run), [])

    def test_the_templates_configuration_shares_one_record_with_its_transport(self):
        """As `ssh-command` does: at the template's `max_chars` the record and its
        transport half weigh 2,048 bytes at the most, whatever the output is written
        in, and a start at the default `record_limit` or at 2,048 takes the check."""
        with tempfile.TemporaryDirectory() as directory:
            check = self._check(directory, max_chars=1000)
            with _patch_run(stdout="ä" * 4000, returncode=0):
                record = record_of(check)
        self.assertLessEqual(len(json.dumps(record).encode("utf-8")),
                             check.expected_record())
        self.assertEqual(check.expected_record(), OUTPUT_RECORD)
        for limit in (RECORD_LIMIT, OUTPUT_RECORD):
            with self.subTest(limit=limit):
                self.assertEqual(_start(check, limit).refusals(), ())

    def test_interpreter_override(self):
        with tempfile.TemporaryDirectory() as directory:
            with _patch_run(stdout="x", returncode=0) as run:
                run_check(self._check(directory, interpreter="sh"))
        self.assertEqual(remote_parts(run)[0], "sh -s")

    def test_the_run_goes_through_the_wrapper_with_a_hang_up_line(self):
        """The remote command ends with its connection: the wrapper is the remote
        command, the script travels on stdin ahead of the hang-up line — its length
        in lines, then the script, whose first line gives it its arguments — and the
        client's stdin is held open for the run (ADR-0089 decision 4)."""
        with tempfile.TemporaryDirectory() as directory:
            with _patch_run(stdout="x", returncode=0) as run:
                run_check(self._check(directory))
        self.assertTrue(run.call_args.args[0][-1].startswith("exec sh -c "))
        self.assertEqual(run.call_args.kwargs["send"], b"2\nset --\necho hi\n")
        self.assertIs(run.call_args.kwargs["hang_up"], True)

    def test_a_script_without_a_last_newline_is_sent_with_one(self):
        """Its length is counted in lines, so its last line is ended."""
        with tempfile.TemporaryDirectory() as directory:
            check = self._check(directory)
            (Path(directory) / "do.sh").write_text("echo hi")
            with _patch_run(stdout="x", returncode=0) as run:
                run_check(check)
        self.assertEqual(run.call_args.kwargs["send"], b"2\nset --\necho hi\n")

    def test_a_long_script_travels_whole_and_leaves_the_command_line_as_it_was(self):
        """The script's size is stdin's business: the command line is the same for a
        script of one line and of twenty thousand."""
        with tempfile.TemporaryDirectory() as directory:
            check = self._check(directory)
            with _patch_run(stdout="x", returncode=0) as run:
                run_check(check)
            short = run.call_args.args[0][-1]
            (Path(directory) / "do.sh").write_text("echo hi\n" * 20_000)
            with _patch_run(stdout="x", returncode=0) as run:
                result = run_check(check)
        self.assertEqual(result.code, StatusCode.OK)
        self.assertEqual(remote_parts(run), ("bash -s", "echo hi\n" * 20_000))
        self.assertEqual(run.call_args.args[0][-1], short)

    def test_nonzero_is_error(self):
        with tempfile.TemporaryDirectory() as directory:
            with _patch_run(stdout="nope\n", returncode=1):
                result = run_check(self._check(directory))
        self.assertEqual(result.code, StatusCode.ERROR)
        self.assertIn("nope", result.reason[0])

    def test_kex_advisory_warns_on_success(self):
        with tempfile.TemporaryDirectory() as directory:
            with _patch_run(stdout="x\n", returncode=0, stderr=PQ_BANNER):
                result = run_check(self._check(directory))
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
