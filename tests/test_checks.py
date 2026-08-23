import os
import tempfile
import time
import unittest
from email.message import Message
from pathlib import Path
from typing import ClassVar
from unittest import TestCase, mock

from little_sister.checks import (
    CHECK_TYPES,
    Check,
    CheckError,
    Entry,
    code,
    load_checks,
    parse_duration,
)
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
from little_sister.fetch import Response
from little_sister.status import StatusCode
from little_sister.transport import Fault, RemoteError

HERE = Path(".")


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

    @staticmethod
    def _answering(status):
        """`fetch` hands back a status whatever it is — a 503 is an answer, and for
        this check the answer *is* the measurement."""
        return mock.patch("little_sister.checks.http.fetch",
                          return_value=Response(status=status, url="http://x",
                                                headers=Message(), body=b""))

    def test_ok_when_status_expected(self):
        with self._answering(200):
            self.assertEqual(self._check().run().code, StatusCode.OK)

    def test_error_on_unexpected_http_status(self):
        with self._answering(503):
            result = self._check().run()
        self.assertEqual(result.code, StatusCode.ERROR)
        self.assertIn("503", result.reason[0])

    # --- `follow_redirects:`, and the two readings it chooses between ---------

    @staticmethod
    def _asked():
        """`fetch` recording the keyword arguments it was called with."""
        return mock.patch(
            "little_sister.checks.http.fetch",
            return_value=Response(status=200, url="http://x",
                                  headers=Message(), body=b""))

    def test_redirects_are_followed_unless_the_config_says_otherwise(self):
        """The default is today's behavior, and it has to stay that way: a check
        written against a URL that answers 200 after a 301 would turn red on upgrade,
        on a config nobody edited."""
        with self._asked() as fetched:
            self._check().run()
        self.assertIs(fetched.call_args.kwargs["follow_redirects"], True)

    def test_a_config_can_ask_for_the_stricter_reading(self):
        """The point of the key: with redirects reported, a `200` at the end of a chain
        is no longer proof the page is there — a login wall answers one too."""
        with self._asked() as fetched:
            self._check(follow_redirects=False).run()
        self.assertIs(fetched.call_args.kwargs["follow_redirects"], False)

    def test_a_reported_redirect_is_the_reading(self):
        """End to end: not following turns the 3xx into the status this check grades,
        so a deployment that wants it accepts the codes it means to in
        `expected_status`."""
        with self._answering(301):
            moved = self._check(follow_redirects=False).run()
        self.assertEqual(moved.code, StatusCode.ERROR)
        self.assertIn("301", moved.reason[0])
        with self._answering(301):
            allowed = self._check(follow_redirects=False,
                                  expected_status=[200, 301]).run()
        self.assertEqual(allowed.code, StatusCode.OK)

    def test_a_quoted_boolean_is_refused_rather_than_read_as_true(self):
        """`bool("false")` is `True`, so a quoted YAML boolean would switch following
        **on** while the config says off, and nothing downstream could notice. A switch
        that can silently mean its opposite is worth less than none."""
        for bad in ("false", "true", "no", 0, 1, [], {}):
            with self.assertRaises(CheckError) as caught:
                self._check(follow_redirects=bad)
            self.assertIn("follow_redirects", str(caught.exception))

    def test_an_absent_key_is_the_default_and_not_a_refusal(self):
        """`None` is what an absent key reads as, and it must not reach the strict
        parser — otherwise every config that never mentioned this key would fail to
        load."""
        self.assertIs(self._check().follow_redirects, True)
        self.assertIs(self._check(follow_redirects=None).follow_redirects, True)

    # --- and the refusal nothing exercised (roadmap item 6) -------------------

    def test_the_policy_has_exactly_one_default(self):
        """`follow_redirects` is required on `__init__`, so the default lives in exactly
        one place — where the config is read.

        Every instance comes through `from_config`, which always supplies the key, so
        a default on `__init__` would be **unreachable** — a second statement of the
        policy, free to drift out of step with the first while no test could tell. A
        mutation proved it: flipping that default broke nothing at all.
        """
        with self.assertRaises(TypeError):
            HttpCheck(url="http://x", expected_status={200}, path="/web")

    def test_a_config_with_no_url_is_refused_at_load(self):
        """One of two branches this suite never reached. Refused at load, where
        little-sister's refusal to start makes it one loud event, rather than at the
        first run — or at the first run that happens to matter."""
        for config in ({"type": "http", "path": "/web"},
                       {"type": "http", "path": "/web", "url": ""}):
            with self.assertRaises(CheckError) as caught:
                HttpCheck.from_config(config, HERE)
            self.assertIn("requires a 'url'", str(caught.exception))

    def test_error_on_transport_failure(self):
        # The endpoint is the subject of this measurement, so a failure to answer is
        # the reading — this check needs nothing from the fault vocabulary.
        with mock.patch("little_sister.checks.http.fetch",
                        side_effect=RemoteError("request failed for GET http://x: "
                                                "boom", fault=Fault.TRANSIENT)):
            result = self._check().run()
        self.assertEqual(result.code, StatusCode.ERROR)
        self.assertIn("request failed", result.reason[0])

    def test_expected_status_list(self):
        with self._answering(204):
            self.assertEqual(
                self._check(expected_status=[200, 204]).run().code, StatusCode.OK)

    def test_it_follows_redirects_and_reads_no_body(self):
        # Both are decisions, not defaults. Following is what it has always done, so a
        # check whose URL answers 200 after a 301 does not turn red on upgrade; and a
        # check that wants a status has no use for the page behind it.
        with mock.patch("little_sister.checks.http.fetch",
                        return_value=Response(200, "http://x", Message(), b"")) as f:
            self._check().run()
        self.assertEqual(f.call_args.kwargs["follow_redirects"], True)
        self.assertEqual(f.call_args.kwargs["read_body"], False)


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

    def test_http_summary_names_the_redirect_reading(self):
        """The two readings differ on the same URL, so an operator looking at a verdict
        they did not expect needs to know which one was taken — and `follow_redirects`
        is not visible anywhere else on the node."""
        followed = HttpCheck.from_config(
            {"type": "http", "path": "/web", "url": "http://x"}, HERE)
        self.assertIn("followed", followed.config_summary())
        reported = HttpCheck.from_config(
            {"type": "http", "path": "/web", "url": "http://x",
             "follow_redirects": False}, HERE)
        self.assertIn("reported", reported.config_summary())

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


class ConstructorRefusalTests(TestCase):
    """A common field growing must stay diagnosable for a check type nobody here
    wrote (ADR-0049 promises names, not a frozen constructor signature)."""

    class _Enumerating(Check):
        """A third-party shape: the common keywords spelled out instead of
        `**kwargs`. Deliberately does *not* list `order`, so it reproduces what
        adding a common field does to a check written before it."""

        type_name = "enumerating-for-test"

        def __init__(self, *, path: str, description: str = "", about: str = "",
                     title: str = "", frequency_seconds: int = 900,
                     timeout_seconds: float = 30.0,
                     retry_interval_seconds: int | None = None,
                     retry_attempts: int | None = None) -> None:
            super().__init__(
                path=path, description=description, about=about, title=title,
                frequency_seconds=frequency_seconds,
                timeout_seconds=timeout_seconds,
                retry_interval_seconds=retry_interval_seconds,
                retry_attempts=retry_attempts)

        def run(self) -> CheckResult:
            return CheckResult(StatusCode.OK)

    class _BrokenBody(Check):
        """A check whose constructor *binds* and then fails on its own bug."""

        type_name = "broken-body-for-test"

        def __init__(self, **kwargs: object) -> None:
            super().__init__(**kwargs)   # type: ignore[arg-type]
            raise TypeError("the check's own bug")

        def run(self) -> CheckResult:
            return CheckResult(StatusCode.OK)

    def test_a_constructor_that_will_not_bind_names_the_type_and_the_keyword(self):
        with self.assertRaises(CheckError) as caught:
            self._Enumerating.from_config({"type": "x", "path": "/a/thing"}, HERE)
        message = str(caught.exception)
        self.assertIn("enumerating-for-test", message)
        self.assertIn("'order'", message)
        self.assertIn("**kwargs", message)

    def test_the_loader_puts_the_file_name_in_front_of_it(self):
        # The whole point: a bare TypeError escaped the loader's `except
        # CheckError`, so the operator got neither the file nor the type.
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "checks").mkdir()
            (root / "checks" / "thing.yaml").write_text(
                "type: enumerating-for-test\npath: /a/thing\n")
            with mock.patch.dict(
                    CHECK_TYPES,
                    {"enumerating-for-test": self._Enumerating}, clear=False):
                with self.assertRaises(CheckError) as caught:
                    load_checks(root)
        self.assertIn("thing.yaml", str(caught.exception))

    def test_a_type_error_from_inside_the_constructor_is_not_relabelled(self):
        # Relabelling this would send its author looking in the wrong place.
        with self.assertRaises(TypeError) as caught:
            self._BrokenBody.from_config({"type": "x", "path": "/a/thing"}, HERE)
        self.assertNotIsInstance(caught.exception, CheckError)
        self.assertIn("the check's own bug", str(caught.exception))

    def test_a_kwargs_constructor_is_untouched(self):
        # The shape every built-in and all three plugins use: nothing to report.
        check = HttpCheck.from_config(
            {"type": "http", "path": "/web", "url": "http://x"}, HERE)
        self.assertEqual(check.path, "/web")


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

    def test_order_is_parsed_beside_the_labels(self):
        # ADR-0055: a rank belongs in the same file that already states this node's
        # title and about. It used to load and vanish, which is the failure mode the
        # ADR refuses one paragraph away, for the non-numeric case.
        check = HttpCheck.from_config(
            {"type": "http", "path": "/web", "url": "http://x", "order": 2}, HERE)
        self.assertEqual(check.order, 2)

    def test_order_defaults_to_unstated_and_a_written_zero_does_not(self):
        bare = HttpCheck.from_config(
            {"type": "http", "path": "/web", "url": "http://x"}, HERE)
        self.assertIsNone(bare.order)
        zero = HttpCheck.from_config(
            {"type": "http", "path": "/web", "url": "http://x", "order": 0}, HERE)
        self.assertEqual(zero.order, 0)      # a stated rank, not silence

    def test_a_non_numeric_order_fails_the_load(self):
        with self.assertRaises(CheckError) as caught:
            HttpCheck.from_config(
                {"type": "http", "path": "/web", "url": "http://x",
                 "order": "soon"}, HERE)
        self.assertIn("whole number", str(caught.exception))

    def test_show_when_quiet_is_parsed_beside_the_labels(self):
        # The check root's own declaration (ADR-0063): this node's quiet lines are
        # still information. It sits in the file that already states its title and
        # about, which is why the *result*'s copy is ignored on the root.
        check = HttpCheck.from_config(
            {"type": "http", "path": "/aws/ec2", "url": "http://x",
             "show_when_quiet": True}, HERE)
        self.assertIs(check.show_when_quiet, True)

    def test_show_when_quiet_defaults_to_unstated_and_a_written_false_does_not(self):
        bare = HttpCheck.from_config(
            {"type": "http", "path": "/web", "url": "http://x"}, HERE)
        self.assertIsNone(bare.show_when_quiet)
        stated = HttpCheck.from_config(
            {"type": "http", "path": "/web", "url": "http://x",
             "show_when_quiet": False}, HERE)
        self.assertIs(stated.show_when_quiet, False)   # a statement, not silence

    def test_a_non_boolean_show_when_quiet_fails_the_load(self):
        with self.assertRaises(CheckError) as caught:
            HttpCheck.from_config(
                {"type": "http", "path": "/web", "url": "http://x",
                 "show_when_quiet": "false"}, HERE)
        self.assertIn("true or false", str(caught.exception))

    def test_the_subnodes_flag_is_parsed_into_every_type(self):
        # The deployment's per-subnode declarations are a common field the
        # library reads (ADR-0063): an `http` check has no children and no
        # subnodes code of its own, and the map still lands — which is what
        # lets a deployment state the key for any installed branch type
        # without that type changing.
        check = HttpCheck.from_config(
            {"type": "http", "path": "/aws", "url": "http://x",
             "subnodes": {"ec2": {"show_when_quiet": True},
                          "batch": {"about": "no flag stated here"}}}, HERE)
        self.assertEqual(check.subnode_show_when_quiet, {"ec2": True})

    def test_a_malformed_subnodes_flag_fails_the_load_on_any_type(self):
        # The block's shape is the library's to validate, so a quoted boolean
        # fails fast even on a type that never reads `subnodes:` itself.
        with self.assertRaises(CheckError) as caught:
            HttpCheck.from_config(
                {"type": "http", "path": "/aws", "url": "http://x",
                 "subnodes": {"ec2": {"show_when_quiet": "yes"}}}, HERE)
        self.assertIn("subnodes.ec2.show_when_quiet", str(caught.exception))


class _DeclaringCheck(Check):
    """A branch type that **declares** its subnode labels and one token, the way
    ADR-0025's 2026-08-19 update says a type states them: two common constructor
    keywords, no reading and no layering of its own."""

    DEFAULTS: ClassVar[dict[str, dict[str, str]]] = {
        "disk": {"title": "Disk", "about": "Volumes on {host}."},
        "memory": {"about": "RAM in use."}}

    def __init__(self, **kwargs: object) -> None:
        super().__init__(subnode_defaults=self.DEFAULTS,      # type: ignore[arg-type]
                         label_tokens={"host": "alpha"}, **kwargs)

    def run(self) -> CheckResult:
        return CheckResult(StatusCode.OK)


def _declaring(defaults: dict, **config: object) -> Check:
    """A check type that declares `defaults`, built from `config` like any other.

    Written as a factory because what is under test is the *declaration* — a fact
    about a type, not a value a config can set — so each case needs a type of its
    own rather than a keyword.
    """
    class _Declared(Check):
        def __init__(self, **kwargs: object) -> None:
            super().__init__(subnode_defaults=defaults,   # type: ignore[arg-type]
                             **kwargs)                    # type: ignore[arg-type]

        def run(self) -> CheckResult:
            return CheckResult(StatusCode.OK)

    return _Declared.from_config({"type": "x", "path": "/host", **config}, HERE)


class DeclaredShowWhenQuietTests(TestCase):
    """A type declares the flag in the same entry that declares its labels, and
    the deployment's `subnodes:` block is merged over it (ADR-0063 §2-§3).

    The merged map is what the engine already reads, so these read it where it is
    made — on the check. What the engine then does with it is `test_engine.py`.
    """

    ROSTER: ClassVar[dict[str, dict[str, object]]] = {
        "ec2": {"about": "The instances.", "show_when_quiet": True},
        "batch": {"about": "The queues."}}

    def test_a_declaration_alone_reaches_the_map(self):
        check = _declaring(self.ROSTER)
        self.assertEqual(check.subnode_show_when_quiet, {"ec2": True})

    def test_a_name_that_declares_only_labels_stays_absent(self):
        # Absence is the tri-state's third value: a type declaring text must not
        # be declaring `false` by accident, or it would shut out a stamped value.
        check = _declaring(self.ROSTER)
        self.assertNotIn("batch", check.subnode_show_when_quiet)
        # …and the labels of both names still resolve, from the same entries.
        self.assertEqual(check.subnode_labels["batch"]["about"], "The queues.")
        self.assertEqual(check.subnode_labels["ec2"]["about"], "The instances.")

    def test_the_blocks_false_beats_the_declared_true(self):
        # Deployment file over package code, per name — the same direction as
        # every other rung of this lattice.
        check = _declaring(self.ROSTER,
                           subnodes={"ec2": {"show_when_quiet": False}})
        self.assertEqual(check.subnode_show_when_quiet, {"ec2": False})

    def test_the_block_may_add_a_name_the_type_said_nothing_about(self):
        check = _declaring(self.ROSTER,
                           subnodes={"batch": {"show_when_quiet": True}})
        self.assertEqual(check.subnode_show_when_quiet,
                         {"ec2": True, "batch": True})

    def test_a_non_boolean_declaration_refuses_the_load(self):
        # `bool("false")` is `True`, so a quoted boolean in a *declaration* would
        # switch a node on while the package's source says off. It is refused like
        # the config key's, and the message names the subnode.
        with self.assertRaises(CheckError) as caught:
            _declaring({"ec2": {"show_when_quiet": "true"}})
        self.assertIn("subnode_defaults.ec2.show_when_quiet",
                      str(caught.exception))
        self.assertIn("true or false", str(caught.exception))

    def test_a_type_that_declares_no_flag_is_unchanged(self):
        check = _declaring({"ec2": {"about": "The instances."}})
        self.assertEqual(check.subnode_show_when_quiet, {})


class SubnodeLabelTests(TestCase):
    """The resolution table (ADR-0025, update 2026-08-19): what each named
    subnode's `title` / `about` finally reads, resolved once at construction from
    what the type declared and what the deployment's `subnodes:` block says."""

    def _check(self, **config: object) -> Check:
        return _DeclaringCheck.from_config(
            {"type": "x", "path": "/host", **config}, HERE)

    def test_a_declaration_alone_resolves(self):
        labels = self._check().subnode_labels
        self.assertEqual(labels["memory"], {"about": "RAM in use."})

    def test_a_declared_token_expands(self):
        # The type's own value, in its own text — the `{token}` half.
        self.assertEqual(self._check().subnode_labels["disk"]["about"],
                         "Volumes on alpha.")

    def test_the_config_beats_the_declaration_per_field(self):
        labels = self._check(subnodes={"disk": {"about": "The NVMe only."}}
                             ).subnode_labels
        self.assertEqual(labels["disk"],
                         {"title": "Disk", "about": "The NVMe only."})

    def test_the_config_may_extend_the_declaration(self):
        # `{default}` puts the shipped text back inside the deployment's own,
        # and the token inside *that* still expands.
        labels = self._check(
            subnodes={"disk": {"about": "{default} Ask #storage first."}}
        ).subnode_labels
        self.assertEqual(labels["disk"]["about"],
                         "Volumes on alpha. Ask #storage first.")

    def test_a_token_in_the_configured_text_expands_too(self):
        labels = self._check(subnodes={"memory": {"title": "RAM on {host}"}}
                             ).subnode_labels
        self.assertEqual(labels["memory"]["title"], "RAM on alpha")

    def test_a_name_the_type_never_declared_still_resolves(self):
        # The hole this update closes: a `subnodes:` label written against a type
        # that had no reader used to be a silent no-op.
        labels = self._check(subnodes={"lambda": {"about": "Functions."}}
                             ).subnode_labels
        self.assertEqual(labels["lambda"], {"about": "Functions."})

    def test_a_field_nobody_stated_is_absent_rather_than_empty(self):
        # Absent is not the same as empty one layer up: the engine reads the
        # child result's own label exactly where this map is silent, which is
        # what keeps a dynamically named child labelled by its check.
        labels = self._check().subnode_labels
        self.assertNotIn("title", labels["memory"])
        self.assertNotIn("lambda", labels)

    def test_a_type_that_declares_nothing_has_the_blocks_labels(self):
        # Every type gets the reader, exactly as it gets the flag's.
        check = HttpCheck.from_config(
            {"type": "http", "path": "/aws", "url": "http://x",
             "subnodes": {"ec2": {"title": "EC2", "show_when_quiet": True}}}, HERE)
        self.assertEqual(check.subnode_labels, {"ec2": {"title": "EC2"}})

    def test_the_flag_stays_out_of_the_label_map(self):
        # Two readers over one block: a boolean must not arrive among the strings.
        check = self._check(subnodes={"disk": {"show_when_quiet": True}})
        self.assertEqual(check.subnode_labels["disk"],
                         {"title": "Disk", "about": "Volumes on alpha."})
        self.assertEqual(check.subnode_show_when_quiet, {"disk": True})


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
