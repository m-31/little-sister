import os
import tempfile
import time
import unittest
import urllib.error
from pathlib import Path
from unittest import TestCase, mock

from little_sister.checks import CheckError, code, load_checks, parse_duration
from little_sister.checks.base import CheckResult
from little_sister.checks.command import CommandCheck
from little_sister.checks.file import FileFreshnessCheck
from little_sister.checks.http import HttpCheck
from little_sister.checks.ssh.command import RemoteCommandCheck
from little_sister.checks.ssh.connect import ConnectCheck
from little_sister.checks.ssh.host_metrics import DEFAULT_THRESHOLDS, HostMetricsCheck
from little_sister.checks.ssh.qnap_metrics import QnapMetricsCheck
from little_sister.checks.ssh.script import ScriptCheck
from little_sister.status import StatusCode

HERE = Path(".")


class _FakeResponse:
    def __init__(self, status: int) -> None:
        self.status = status

    def __enter__(self) -> _FakeResponse:
        return self

    def __exit__(self, *args: object) -> bool:
        return False


class DurationTests(TestCase):
    def test_parse_duration_units(self):
        self.assertEqual(parse_duration("30s", 0), 30)
        self.assertEqual(parse_duration("15m", 0), 900)
        self.assertEqual(parse_duration("2h", 0), 7200)
        self.assertEqual(parse_duration("1d", 0), 86400)
        self.assertEqual(parse_duration(45, 0), 45)
        self.assertEqual(parse_duration(None, 900), 900)

    def test_parse_duration_invalid(self):
        with self.assertRaises(CheckError):
            parse_duration("abc", 0)


class PathTests(TestCase):
    def test_single_absolute_path(self):
        check = HttpCheck.from_config(
            {"type": "http", "path": "/services/api", "url": "http://x"}, HERE)
        self.assertEqual(check.path, "/services/api")
        self.assertEqual(check.name, "api")          # the last segment

    def test_relative_path_is_made_absolute(self):
        check = HttpCheck.from_config(
            {"type": "http", "path": "services/api", "url": "http://x"}, HERE)
        self.assertEqual(check.path, "/services/api")

    def test_name_field_is_rejected(self):
        with self.assertRaises(CheckError):     # merged into `path` (ADR-0016)
            HttpCheck.from_config(
                {"type": "http", "path": "/web", "name": "x", "url": "http://x"},
                HERE)


class HttpCheckTests(TestCase):
    def _check(self, **extra):
        config = {"type": "http", "path": "/web", "url": "http://x"}
        config.update(extra)
        return HttpCheck.from_config(config, HERE)

    def test_ok_when_status_expected(self):
        with mock.patch("little_sister.checks.http.urllib.request.urlopen",
                        return_value=_FakeResponse(200)):
            self.assertEqual(self._check().run().code, StatusCode.OK)

    def test_error_on_unexpected_http_status(self):
        error = urllib.error.HTTPError("http://x", 503, "down", {}, None)  # type: ignore[arg-type]
        with mock.patch("little_sister.checks.http.urllib.request.urlopen",
                        side_effect=error):
            result = self._check().run()
        self.assertEqual(result.code, StatusCode.ERROR)
        self.assertIn("503", result.reason[0])

    def test_error_on_transport_failure(self):
        with mock.patch("little_sister.checks.http.urllib.request.urlopen",
                        side_effect=urllib.error.URLError("boom")):
            result = self._check().run()
        self.assertEqual(result.code, StatusCode.ERROR)
        self.assertIn("request failed", result.reason[0])

    def test_expected_status_list(self):
        with mock.patch("little_sister.checks.http.urllib.request.urlopen",
                        return_value=_FakeResponse(204)):
            self.assertEqual(
                self._check(expected_status=[200, 204]).run().code, StatusCode.OK)


class FileFreshnessTests(TestCase):
    def test_ok_when_fresh_error_when_stale_and_missing(self):
        with tempfile.TemporaryDirectory() as directory:
            heartbeat = Path(directory) / "hb.txt"
            heartbeat.write_text("x")
            check = FileFreshnessCheck.from_config(
                {"type": "file", "path": "/hb", "file": str(heartbeat),
                 "max_age": "20m"}, Path(directory))
            self.assertEqual(check.run().code, StatusCode.OK)

            stale = time.time() - 3600
            os.utime(heartbeat, (stale, stale))
            result = check.run()
            self.assertEqual(result.code, StatusCode.ERROR)
            self.assertIn("stale", result.reason[0])

            missing = FileFreshnessCheck.from_config(
                {"type": "file", "path": "/x",
                 "file": str(Path(directory) / "nope")}, Path(directory))
            self.assertEqual(missing.run().code, StatusCode.ERROR)

    def test_relative_path_resolves_under_home(self):
        # base_dir (/tmp) is ignored; relative paths resolve under $HOME.
        bare = FileFreshnessCheck.from_config(
            {"type": "file", "path": "/x", "file": "sub/app.log"}, Path("/tmp"))
        self.assertEqual(bare.file_path, str(Path.home() / "sub/app.log"))
        tilde = FileFreshnessCheck.from_config(
            {"type": "file", "path": "/x", "file": "~/a/b.log"}, Path("/tmp"))
        self.assertEqual(tilde.file_path, str(Path.home() / "a/b.log"))
        absolute = FileFreshnessCheck.from_config(
            {"type": "file", "path": "/x", "file": "/var/log/x.log"}, Path("/tmp"))
        self.assertEqual(absolute.file_path, "/var/log/x.log")

    def test_custom_stale_code(self):
        with tempfile.TemporaryDirectory() as directory:
            heartbeat = Path(directory) / "hb.txt"
            heartbeat.write_text("x")
            old = time.time() - 3600
            os.utime(heartbeat, (old, old))
            check = FileFreshnessCheck.from_config(
                {"type": "file", "path": "/hb", "file": str(heartbeat),
                 "max_age": "1m", "stale_code": "WARN"}, Path(directory))
            self.assertEqual(check.run().code, StatusCode.WARN)


class CommandCheckTests(TestCase):
    def _check(self, command, **extra):
        config = {"type": "command", "path": "/c", "command": command}
        config.update(extra)
        return CommandCheck.from_config(config, HERE)

    def test_ok_on_exit_zero_with_stdout_reason(self):
        result = self._check("echo hello").run()
        self.assertEqual(result.code, StatusCode.OK)
        # captured output is fenced as a code block (ADR-0018)
        self.assertEqual(result.reason, [code("hello")])

    def test_error_on_nonzero_with_stderr_capture(self):
        result = self._check("echo oops >&2; exit 3", capture="stderr").run()
        self.assertEqual(result.code, StatusCode.ERROR)
        self.assertIn("oops", result.reason[0])

    def test_argv_list_command(self):
        result = self._check(["echo", "hi"]).run()
        self.assertEqual((result.code, result.reason), (StatusCode.OK, [code("hi")]))

    def test_output_shortening_tail_and_head(self):
        tail = self._check("printf abcdef", max_chars=3, keep="tail").run()
        self.assertEqual(tail.reason, [code("def")])
        head = self._check("printf abcdef", max_chars=3, keep="head").run()
        self.assertEqual(head.reason, [code("abc")])

    def test_timeout_is_error(self):
        result = self._check("sleep 5", timeout="1s").run()
        self.assertEqual(result.code, StatusCode.ERROR)
        self.assertIn("timed out", result.reason[0])


class CheckResultTreeTests(TestCase):
    def test_child_result_requires_a_name(self):
        with self.assertRaises(CheckError):
            CheckResult(StatusCode.OK,
                        children=(CheckResult(StatusCode.OK),))

    def test_leaf_result_is_unchanged(self):
        leaf = CheckResult(StatusCode.OK, ["fine"])
        self.assertEqual((leaf.name, leaf.children), ("", ()))


class LoaderTests(TestCase):
    def test_loads_configs_by_type(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            (base / "a.yaml").write_text(
                "type: http\npath: /web\nurl: http://x\nfrequency: 5m\n")
            (base / "b.yml").write_text("type: command\npath: /c\ncommand: 'true'\n")
            checks = load_checks(base)
            self.assertEqual(len(checks), 2)
            by_name = {c.name: c for c in checks}
            self.assertIsInstance(by_name["web"], HttpCheck)
            self.assertEqual(by_name["web"].frequency_seconds, 300)
            self.assertIsInstance(by_name["c"], CommandCheck)

    def test_unknown_type_raises(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            (base / "bad.yaml").write_text("type: nope\npath: /x\n")
            with self.assertRaises(CheckError):
                load_checks(base)

    def test_missing_directory_raises(self):
        with self.assertRaises(CheckError):
            load_checks(Path(tempfile.gettempdir()) / "little-sister-does-not-exist")

    def test_loads_union_across_directories(self):
        with tempfile.TemporaryDirectory() as d1, tempfile.TemporaryDirectory() as d2:
            base, host = Path(d1), Path(d2)
            (base / "one.yaml").write_text("type: http\npath: /one\nurl: http://x\n")
            (host / "two.yml").write_text(
                "type: command\npath: /two\ncommand: 'true'\n")
            sep = os.pathsep
            # blank segments (a doubled / trailing separator, stray whitespace)
            # are ignored, so a path-list stays forgiving.
            checks = load_checks(f" {base}{sep}{sep}{host}{sep}")
            self.assertEqual({c.name for c in checks}, {"one", "two"})

    def test_missing_directory_in_list_raises(self):
        with tempfile.TemporaryDirectory() as directory:
            present = Path(directory)
            (present / "ok.yaml").write_text("type: http\npath: /ok\nurl: http://x\n")
            missing = Path(tempfile.gettempdir()) / "little-sister-missing-dir"
            with self.assertRaises(CheckError):
                load_checks(f"{present}{os.pathsep}{missing}")

    def test_duplicate_owned_node_across_dirs_is_rejected(self):
        with tempfile.TemporaryDirectory() as d1, tempfile.TemporaryDirectory() as d2:
            base, host = Path(d1), Path(d2)
            (base / "web.yaml").write_text("type: http\npath: /web\nurl: http://x\n")
            (host / "web.yaml").write_text("type: http\npath: /web\nurl: http://y\n")
            with self.assertRaises(CheckError) as caught:
                load_checks(f"{base}{os.pathsep}{host}")
            self.assertIn("web", str(caught.exception))

    def test_leaf_owning_a_parent_node_is_rejected(self):
        # A leaf owns its subtree, so a check on `db` collides with one on `db.replica`.
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            (base / "parent.yaml").write_text("type: http\npath: /db\nurl: http://x\n")
            (base / "child.yaml").write_text(
                "type: http\npath: /db/replica\nurl: http://y\n")
            with self.assertRaises(CheckError):
                load_checks(base)

    def test_metrics_pair_shares_a_host_node(self):
        # host-metrics + qnap-metrics own disjoint child subtrees of one host node,
        # so the union loads both (architecture.md §4.5, ADR-0015).
        with tempfile.TemporaryDirectory() as d1, tempfile.TemporaryDirectory() as d2:
            base, host = Path(d1), Path(d2)
            (base / "probe.sh").write_text("echo hi\n")
            (host / "probe.sh").write_text("echo hi\n")
            (base / "metrics.yaml").write_text(
                "type: host-metrics\npath: /nas\nhost: h\nscript: probe.sh\n")
            (host / "qnap.yaml").write_text(
                "type: qnap-metrics\npath: /nas\nhost: h\nscript: probe.sh\n")
            checks = load_checks(f"{base}{os.pathsep}{host}")
            self.assertEqual(len(checks), 2)

    def test_nodes_yaml_is_not_loaded_as_a_check(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            (base / "nodes.yaml").write_text("system: {about: hi}\n")
            (base / "web.yaml").write_text("type: http\npath: /web\nurl: http://x\n")
            checks = load_checks(base)
            self.assertEqual([c.name for c in checks], ["web"])


class OwnedNodesTests(TestCase):
    def test_leaf_check_owns_only_its_node(self):
        check = HttpCheck.from_config(
            {"type": "http", "path": "/services/web", "url": "http://x"},
            HERE)
        self.assertEqual(check.owned_nodes(), {"/services/web"})

    def test_host_metrics_owns_its_metric_subtrees_not_the_container(self):
        check = HostMetricsCheck(path="/system/alpha", host="h",
                                 script_path="x", thresholds=DEFAULT_THRESHOLDS)
        self.assertEqual(check.owned_nodes(), {
            "/system/alpha/ssh", "/system/alpha/disk", "/system/alpha/memory",
            "/system/alpha/cpu", "/system/alpha/load"})
        self.assertNotIn("/system/alpha", check.owned_nodes())

    def test_qnap_metrics_owns_its_aspect_subtrees(self):
        check = QnapMetricsCheck(path="/nexus", host="h",
                                 script_path="x", temp_warn=50.0, temp_error=60.0)
        self.assertEqual(check.owned_nodes(), {"/nexus/temperature", "/nexus/smart"})


class ConfigSummaryTests(TestCase):
    def test_http_summary_lists_url_and_status(self):
        check = HttpCheck.from_config(
            {"type": "http", "path": "/web", "url": "http://x",
             "expected_status": [200, 204]}, HERE)
        summary = check.config_summary()
        self.assertIn("http://x", summary)
        self.assertIn("200, 204", summary)

    def test_file_summary_lists_path(self):
        check = FileFreshnessCheck.from_config(
            {"type": "file", "path": "/hb", "file": "/tmp/beat", "max_age": "20m"},
            HERE)
        self.assertIn("/tmp/beat", check.config_summary())

    def test_command_summary_lists_command(self):
        check = CommandCheck.from_config(
            {"type": "command", "path": "/c", "command": "echo hi"}, HERE)
        self.assertIn("echo hi", check.config_summary())

    def test_ssh_leaf_summaries_carry_connection(self):
        connect = ConnectCheck.from_config(
            {"type": "ssh-connect", "path": "/h", "host": "server.example"}, HERE)
        self.assertIn("server.example", connect.config_summary())
        command = RemoteCommandCheck.from_config(
            {"type": "ssh-command", "path": "/h", "host": "server.example",
             "command": "uptime"}, HERE)
        self.assertIn("server.example", command.config_summary())
        self.assertIn("uptime", command.config_summary())
        script = ScriptCheck(path="/h", host="server.example",
                             script_path="/checks/probe.sh", interpreter="bash",
                             capture="stdout", max_chars=1000, keep="tail")
        self.assertIn("probe.sh", script.config_summary())
        self.assertIn("bash", script.config_summary())

    def test_branch_checks_leave_the_container_bare(self):
        host = HostMetricsCheck(path="/system/alpha", host="h",
                                script_path="x", thresholds=DEFAULT_THRESHOLDS)
        qnap = QnapMetricsCheck(path="/nexus", host="h",
                                script_path="x", temp_warn=50.0, temp_error=60.0)
        self.assertEqual(host.config_summary(), "")
        self.assertEqual(qnap.config_summary(), "")


class InlineAboutTests(TestCase):
    def test_about_is_parsed_from_config(self):
        check = HttpCheck.from_config(
            {"type": "http", "path": "/web", "url": "http://x",
             "about": "the public marketing site"}, HERE)
        self.assertEqual(check.about, "the public marketing site")

    def test_about_defaults_empty(self):
        check = HttpCheck.from_config(
            {"type": "http", "path": "/web", "url": "http://x"}, HERE)
        self.assertEqual(check.about, "")

    def test_title_is_parsed_and_defaults_empty(self):
        check = HttpCheck.from_config(
            {"type": "http", "path": "/web", "url": "http://x",
             "title": "Marketing site"}, HERE)
        self.assertEqual(check.title, "Marketing site")
        bare = HttpCheck.from_config(
            {"type": "http", "path": "/web", "url": "http://x"}, HERE)
        self.assertEqual(bare.title, "")


if __name__ == '__main__':
    unittest.main()
