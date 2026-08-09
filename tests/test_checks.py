import os
import tempfile
import time
import unittest
import urllib.error
from pathlib import Path
from unittest import TestCase, mock

from little_sister.checks import CheckError, Entry, code, load_checks, parse_duration
from little_sister.checks.base import CheckResult
from little_sister.checks.command import CommandCheck
from little_sister.checks.file import FileFreshnessCheck
from little_sister.checks.http import HttpCheck
from little_sister.checks.ssh.command import RemoteCommandCheck
from little_sister.checks.ssh.connect import ConnectCheck
from little_sister.checks.ssh.host_metrics import DEFAULT_THRESHOLDS, HostMetricsCheck
from little_sister.checks.ssh.qnap_metrics import QnapMetricsCheck
from little_sister.checks.ssh.script import ScriptCheck
from little_sister.errors import ConfigError
from little_sister.status import StatusCode

HERE = Path(".")


class _FakeResponse:
    def __init__(self, status: int) -> None:
        self.status = status

    def __enter__(self) -> "_FakeResponse":
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

    def test_result_about_and_title_default_empty(self):
        leaf = CheckResult(StatusCode.OK, ["fine"])
        self.assertEqual((leaf.about, leaf.title), ("", ""))

    def test_result_carries_about_and_title(self):
        # A branch check captions the subnodes it emits (ADR-0025).
        child = CheckResult(StatusCode.OK, name="disk",
                            about="Free space on the data volume.", title="Disk")
        self.assertEqual(child.about, "Free space on the data volume.")
        self.assertEqual(child.title, "Disk")


def _root(directory: str, **files: str) -> Path:
    """A configuration root (ADR-0031) whose ``checks/`` holds ``files``.

    Checks live one level down now — ``config/checks/*.yaml`` — so the loader tests
    build the tree the loader actually reads rather than a bare directory.
    """
    root = Path(directory)
    checks = root / "checks"
    checks.mkdir(exist_ok=True)
    for name, text in files.items():
        (checks / name.replace("__", ".")).write_text(text)
    return root


class LoaderTests(TestCase):
    def test_loads_configs_by_type(self):
        with tempfile.TemporaryDirectory() as directory:
            root = _root(
                directory,
                a__yaml="type: http\npath: /web\nurl: http://x\nfrequency: 5m\n",
                b__yml="type: command\npath: /c\ncommand: 'true'\n")
            checks = load_checks(root)
            self.assertEqual(len(checks), 2)
            by_name = {c.name: c for c in checks}
            self.assertIsInstance(by_name["web"], HttpCheck)
            self.assertEqual(by_name["web"].frequency_seconds, 300)
            self.assertIsInstance(by_name["c"], CommandCheck)

    def test_unknown_type_raises(self):
        with tempfile.TemporaryDirectory() as directory:
            root = _root(directory, bad__yaml="type: nope\npath: /x\n")
            with self.assertRaises(CheckError):
                load_checks(root)

    def test_missing_config_root_raises(self):
        # A named root that is not there is a typo in a unit file, not an empty
        # layer — and fatal rather than a CheckError, so nothing catches it into
        # the engine_error banner (ADR-0031 §7).
        with self.assertRaises(ConfigError):
            load_checks(Path(tempfile.gettempdir()) / "little-sister-does-not-exist")

    def test_root_without_a_checks_aspect_raises(self):
        # Nowhere to look for checks: misconfigured, not empty.
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaises(ConfigError) as caught:
                load_checks(Path(directory))
            self.assertIn("checks/", str(caught.exception))
            # The message names the **resolved** path, which is the promise
            # ADR-0031 §7 makes. On macOS a temporary directory lives under /var,
            # itself a symlink to /private/var, so the two spellings differ there
            # and nowhere else — assert against the one the code sets out to print.
            self.assertIn(str(Path(directory).resolve()), str(caught.exception))

    def test_empty_checks_aspect_loads_nothing(self):
        # Configured to watch nothing *yet* is survivable — the loader returns an
        # empty list and create_engine turns it into the heartbeat's WARN.
        with tempfile.TemporaryDirectory() as directory:
            self.assertEqual(load_checks(_root(directory)), [])

    def test_loads_union_across_roots(self):
        with tempfile.TemporaryDirectory() as d1, tempfile.TemporaryDirectory() as d2:
            base = _root(d1, one__yaml="type: http\npath: /one\nurl: http://x\n")
            host = _root(d2, two__yml="type: command\npath: /two\ncommand: 'true'\n")
            sep = os.pathsep
            # blank segments (a doubled / trailing separator, stray whitespace)
            # are ignored, so a path-list stays forgiving.
            checks = load_checks(f" {base}{sep}{sep}{host}{sep}")
            self.assertEqual({c.name for c in checks}, {"one", "two"})

    def test_one_root_may_carry_the_checks(self):
        # A site root with no checks of its own is normal; only *no* root
        # providing the aspect is fatal.
        with tempfile.TemporaryDirectory() as d1, tempfile.TemporaryDirectory() as d2:
            base = _root(d1, one__yaml="type: http\npath: /one\nurl: http://x\n")
            site = Path(d2)
            (site / "nodes.yaml").write_text("/one: {title: One}\n")
            checks = load_checks(f"{base}{os.pathsep}{site}")
            self.assertEqual([c.name for c in checks], ["one"])

    def test_missing_root_in_list_raises(self):
        with tempfile.TemporaryDirectory() as directory:
            present = _root(directory,
                            ok__yaml="type: http\npath: /ok\nurl: http://x\n")
            missing = Path(tempfile.gettempdir()) / "little-sister-missing-dir"
            with self.assertRaises(ConfigError):
                load_checks(f"{present}{os.pathsep}{missing}")

    def test_checks_as_a_file_is_rejected(self):
        # `checks` is always a directory (ADR-0031 §2). A checks.yaml is the
        # operator plainly meaning checks, so it refuses rather than being ignored.
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "checks.yaml").write_text("type: http\npath: /x\nurl: http://x\n")
            with self.assertRaises(ConfigError) as caught:
                load_checks(root)
            self.assertIn("directory", str(caught.exception))

    def test_duplicate_owned_node_across_roots_is_rejected(self):
        with tempfile.TemporaryDirectory() as d1, tempfile.TemporaryDirectory() as d2:
            base = _root(d1, web__yaml="type: http\npath: /web\nurl: http://x\n")
            host = _root(d2, web__yaml="type: http\npath: /web\nurl: http://y\n")
            with self.assertRaises(CheckError) as caught:
                load_checks(f"{base}{os.pathsep}{host}")
            self.assertIn("web", str(caught.exception))

    def test_reserved_heartbeat_line_is_rejected(self):
        # /little-sister is the engine's own line (ADR-0005): the dashboard
        # lifts it into the status strip, so no custom check may own nodes on it.
        with tempfile.TemporaryDirectory() as directory:
            root = _root(
                directory,
                sneaky__yaml=("type: command\npath: /little-sister/backups\n"
                              "command: 'true'\n"))
            with self.assertRaises(CheckError) as caught:
                load_checks(root)
            self.assertIn("reserved", str(caught.exception))
            self.assertIn("little-sister", str(caught.exception))

    def test_leaf_owning_a_parent_node_is_rejected(self):
        # A leaf owns its subtree, so a check on `db` collides with one on `db.replica`.
        with tempfile.TemporaryDirectory() as directory:
            root = _root(directory,
                         parent__yaml="type: http\npath: /db\nurl: http://x\n",
                         child__yaml="type: http\npath: /db/replica\nurl: http://y\n")
            with self.assertRaises(CheckError):
                load_checks(root)

    def test_metrics_pair_shares_a_host_node(self):
        # host-metrics + qnap-metrics own disjoint child subtrees of one host node,
        # so the union loads both (architecture.md §4.5, ADR-0015).
        with tempfile.TemporaryDirectory() as d1, tempfile.TemporaryDirectory() as d2:
            base = _root(d1, metrics__yaml=(
                "type: host-metrics\npath: /nas\nhost: h\nscript: probe.sh\n"))
            host = _root(d2, qnap__yaml=(
                "type: qnap-metrics\npath: /nas\nhost: h\nscript: probe.sh\n"))
            (base / "checks" / "probe.sh").write_text("echo hi\n")
            (host / "checks" / "probe.sh").write_text("echo hi\n")
            checks = load_checks(f"{base}{os.pathsep}{host}")
            self.assertEqual(len(checks), 2)

    def test_nodes_aspect_is_not_loaded_as_a_check(self):
        # nodes.yaml sits beside checks/ now, not inside it, so the loader needs
        # no skip-list: config/checks/ holds checks and nothing else.
        with tempfile.TemporaryDirectory() as directory:
            root = _root(directory,
                         web__yaml="type: http\npath: /web\nurl: http://x\n")
            (root / "nodes.yaml").write_text("/web: {about: hi}\n")
            checks = load_checks(root)
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


class CodedResultSeamTests(TestCase):
    """The CheckResult seam of ADR-0042: a node with coded entries declares no
    code of its own, and declaring both is refused — loudly, like ``name:`` in a
    check YAML — because a silently ignored code would be believed."""

    def test_declaring_both_is_refused(self):
        with self.assertRaises(CheckError):
            CheckResult(StatusCode.OK, [Entry("w", "x", StatusCode.OK)])

    def test_coded_entries_derive_the_stored_code(self):
        result = CheckResult(reason=[Entry("a", "passed", StatusCode.OK),
                                     Entry("b", "failed", StatusCode.ERROR)])
        self.assertIsNone(result.code)
        self.assertEqual(result.stored_code, StatusCode.ERROR)
        self.assertTrue(result.members)

    def test_an_entry_bearing_empty_set_reads_ok(self):
        # an empty mapping, or entries=True beside an empty list, says "I
        # enumerated and found nothing" — which is OK, not UNDEFINED
        self.assertEqual(CheckResult(reason={}).stored_code, StatusCode.OK)
        self.assertEqual(CheckResult(reason=[], entries=True).stored_code,
                         StatusCode.OK)

    def test_a_result_without_any_code_is_refused(self):
        with self.assertRaises(CheckError):
            CheckResult(reason="boom")                  # prose, no code
        with self.assertRaises(CheckError):
            CheckResult()                               # nothing at all
        with self.assertRaises(CheckError):
            CheckResult(reason={"a": "x"})              # members, none coded

    def test_a_declared_code_is_the_stored_code(self):
        self.assertEqual(CheckResult(StatusCode.WARN, "meh").stored_code,
                         StatusCode.WARN)

    def test_running_alone_rides_a_declared_code(self):
        # `running` is display, not severity — it does not force derivation
        result = CheckResult(StatusCode.WARN, [Entry("a", "x", running=True)])
        self.assertEqual(result.stored_code, StatusCode.WARN)
        self.assertTrue(result.members)     # a per-line claim declares members
